# Projects Delete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The project owner or a parent can delete a project, and anyone allowed can delete a thread, mission or program. It disappears for everyone at once, running work stops and can never write about it again, and once that work has exited every attached row, card and file is removed, leaving nothing behind.

**Architecture:** One module, `services/deletion.py`, owns every hard delete:
- `preview` computes the closure from authoritative fields and returns titles plus a token.
- `start` writes a `deletions` row and `deleting` stamps in one SQLite transaction, then hides and stops.
- `maintain` runs on its own loop. It waits until no registered worker remains for the closure, then deletes children before parents, idempotently, plus an orphan pass.

Every visibility primitive asks `access.gone` first. Workers carry their source in a context variable (`deletion.acting_for`), which storage helpers, the calendar insert, file writes and mail check through `deletion.check()`.

**Tech Stack:** Python 3.14, FastAPI (`chauffeur/main.py`), SQLite-backed storage (`services/storage.py`, `services/storage_sqlite.py`), plain-script tests from `chauffeur/` (`python tests/test_x.py`), Alpine.js templates, Playwright live tests.

**Spec:** `docs/superpowers/specs/2026-10-18-projects-delete-design.md` rev 3, approved by the user 2026-10-18. Read it before any task; section numbers below refer to it.

## Global Constraints

- **Running tests:** from `chauffeur/` with `HA_BASE_URL` unset (`unset HA_BASE_URL`). Run the task's own tests plus the named neighbours. Never the whole suite.
- **Fixture data only.** Tests isolate storage through `tests/harness.py` or a module that imports it. A live test that needs auth enforcement must not import `harness.py`.
- **Refusal texts, verbatim:**
  - "Ask a parent to delete this." (a closure record the actor cannot read)
  - "This project changed. Look again." (the token does not match)
  - "Its work was deleted." (an unfinished step whose mission was deleted)
- **Confirmation tail, verbatim:** "Linked trips, lists and events stay."
- **Gone** means a row is missing, or it carries `deleting`. Hidden means:
  - a 404 shaped like a missing record;
  - the row dropped from lists, previews and counts;
  - no calendar row (the **gone** outcome, not "Busy");
  - no DM, push or speech.
- **Never pass `None` as an access viewer.** House readers use `access.HOUSE` / `access.HOUSE_PARENT`.
- **No browser dialogs.** Use `showGlobalAlert`, `promptConfirm` and `promptInput` only.
- **Tailwind is precompiled.** After a template class change, run `python tools/build_tailwind.py` from the repo root.
- **Every HA touchpoint degrades gracefully.** No Argyle delete tool.
- **Codex tasks** (2, 3, 4, 5, 6) leave changes in the working tree, and never bump `chauffeur/config.yaml` or commit (AGENTS.md). Claude reviews, gates, bumps the patch version (v2.499.N) and commits, with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- **Reviews cross models.** Codex-built tasks get a Claude reviewer; Claude-built tasks (1, 7) get Codex (`codex-companion.mjs task --model gpt-6.1-sol --effort high`, read-only).
- **Do not push between Task 2 and Task 4.** Task 2 enables deleting before Task 4 fences late writers. Push after Task 4's gate is green; until then the routes exist only locally.
- **PowerShell:** no double quotes in commit messages. Use the Bash tool for git.

## Review Focus

1. **Delete pressed twice, or from two devices at once.** The second request must answer cleanly: `changed`, or a 404 for a project already gone. It must never start a second deletion row or 500. Pinned in Task 1 `scenario_double_start`.
2. **A restart while a deletion is half-done.** Startup maintenance must resume and finish, and the project must stay hidden throughout. Pinned in Task 1 `scenario_restart_mid_cleanup`.
3. **The deleting person is disabled between preview and start.** `start` must re-check the actor and refuse. Pinned in Task 1 `scenario_actor_disabled_before_start`.
4. **A project with 50 pieces and long histories.** `start` must stay one transaction and return quickly. Cleanup may take several passes but must converge. Pinned in Task 1 `scenario_large_project_converges`.
5. **A worker that never exits** (a hung browse turn). The project stays hidden, cleanup waits, a re-cancel is logged after 15 minutes, and nothing else errors. Pinned in Task 1 `scenario_hung_worker_waits`.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `chauffeur/services/deletion.py` (new) | closure, authorization, token, `start`, `acting_for` / `check` / registry, `maintain`, orphan pass | 2, 4, 5 |
| `chauffeur/services/storage.py` | `deletions` table helpers; gone-parent refusals on child inserts; `deletion.check()` calls in insert and update helpers; raw-table writers moved behind helpers; chat predicate before pagination | 2, 3, 4 |
| `chauffeur/services/access.py` | `gone()`, first in every primitive; fail-closed pointer; gone outcome for calendar readers | 3 |
| `chauffeur/services/subjects.py` | a subject or history entry naming a gone thread/mission/program/project resolves unreadable | 3 |
| `chauffeur/services/home_board.py` | `deleting` in the access digest; synchronous invalidation | 3 |
| `chauffeur/main.py` | routes; consumers skipping gone rows; push fan-out re-check; maintenance loop in lifespan | 2, 3, 4, 5 |
| `chauffeur/services/{threads,missions,programs,planned,program_lessons,watchers,replies,asks,situations,chat_actions,calendar,browse}.py` | workers wrapped in `acting_for`; creation bound at insert; `cancel_for_delete`; deletion pause; queued-delivery re-checks; typed `refs` on new Argyle messages | 4 |
| `chauffeur/services/access_readers.py`, `services/auth.py` | READERS rows and auth rules for the new routes | 2 |
| `chauffeur/templates/components/projects_page.html`, `threads_page.html`, `missions_page.html`, `record_sheet.html`, `templates/app.html` | Delete and Remove, folding, full mission history (admin and phone) | 7 |
| `chauffeur/tests/test_deletion_*.py` (new) | the contract | 1 |

---

### Task 1 (Claude subagent): the tests

**Files:** create `tests/test_deletion_core.py`, `tests/test_deletion_hide.py`, `tests/test_deletion_late_work.py`, `tests/test_deletion_cleanup.py` and `tests/test_deletion_live.py` (no `harness.py`); extend `tests/access_fixture.py` with one deletable project per class if useful.

**Interfaces (produced by Tasks 2-6):**
- `deletion.preview(kind, id, actor) -> {'status': 'ok', 'token': str, 'items': [{'kind','id','title'}], 'links': int} | {'status': 'refused', 'message': str}`
- `deletion.start(kind, id, actor, token) -> {'status': 'ok', 'deletion_id': str} | {'status': 'refused'|'changed', 'message': str}`
- `deletion.closure(kind, id) -> [(kind, id)]` (authoritative; no permission check)
- `deletion.maintain() -> {'finished': int, 'waiting': int, 'orphans': int}`
- `deletion.acting_for(kind, id)` (context manager); `deletion.check()` raises `deletion.Cancelled`; `deletion.active(kind, id) -> bool`
- `access.gone(kind, row) -> bool`
- `storage.get_deletions() -> list`
- The routes in spec §6.

- [ ] **Step 1: `test_deletion_core.py`.** One scenario per spec §2/§3 bullet:
  - closure by `project_id` with a lost `pieces[]` entry;
  - origin missions homed elsewhere;
  - kit threads;
  - closed under the thread rule;
  - records about P are not in the closure;
  - authorization for owner / parent / other adult / child owner / panel;
  - a closure record unreadable to the actor refuses with "Ask a parent to delete this." and changes nothing;
  - a linked trip never blocks;
  - no hidden title in preview or refusal;
  - a token mismatch (a closure record renamed) gives `changed`;
  - `start` is one transaction (inject a failure after the first stamp; nothing is stamped);
  - Review Focus 1, 3 and 4;
  - standalone deletes of a thread, mission and program;
  - deleting the last piece leaves the project.
- [ ] **Step 2: `test_deletion_hide.py`.** After `start`, the project and every closure record return nothing on:
  - every access primitive (`projects.can_see`, `project_visible`, `record_view`, `channel_view` incl. legacy, `mission_view` incl. origin shortcut, `practice_hidden`, hold readers, `commitment_view`, `finding_view`, `finding_visible`);
  - `/api/projects`, by-id routes, `/api/schedule`, `/api/commitments` (no error, row absent);
  - chat messages, previews and unread counts (a gone card hidden before the limit is applied; `limit=1` still returns the newest surviving message);
  - a warm wall board.

  The fail-closed pointer: a household thread whose subject was a deleted private thread is keeper-only on every surface, and an owner change keeps it failing closed.
- [ ] **Step 3: `test_deletion_late_work.py`.** Each of these, finishing after `start`, writes, creates and delivers nothing:
  - a browse turn;
  - a build stage (`create_thread`, `propose_program`, an update to a linked trip, `create_event` blocked mid-call);
  - a work stage;
  - lesson generation;
  - program approval and resume;
  - a watcher sweep and its posting;
  - a reply classification and deferred DM;
  - ask application;
  - a situation refresh timer;
  - a queued push fan-out;
  - a practice push;
  - a lesson voice timer.

  Also:
  - cleanup waits while each is registered;
  - adoption never creates a replacement wrapper;
  - Review Focus 5.

  Drive the real worker entry points with their external calls (model, browser, Google, mail) stubbed at the boundary.
- [ ] **Step 4: `test_deletion_cleanup.py`.** After `maintain()`, zero rows and files remain for every §5 step:
  - cards by `mission_id` / `thread_id` / `program_id` / `project_id` / `ask_id` / `proposal_id`;
  - mixed messages deleted whole;
  - proposals, asks, findings, commitment exceptions and commitment findings (from the emissions snapshot taken before pause);
  - commitments and lessons;
  - browse folders, new and legacy thread photos;
  - surviving records' history entries, step payloads (`blocked` with "Its work was deleted."), `origin_mission_id`, `wrapped_from`, `pieces[]`, program `emissions.thread_ids` and app-state keys;
  - the deletion row itself.

  Also:
  - an interruption after each step, re-run, converges;
  - a failing commitment delete keeps its program until it succeeds;
  - the orphan pass removes a late screenshot;
  - maintenance runs with watchers off;
  - Review Focus 2.
- [ ] **Step 5: `test_deletion_live.py`** is written in Task 7 with the UI. Here, only add a placeholder list of its scenarios in the file's docstring.
- [ ] **Step 6:** run all four files. Each must be red only because "the new code does not exist yet". Do not commit; the controller commits.

### Task 2 (Codex): deletion core, start and routes

**Files:** create `services/deletion.py` (closure, authorization, token, preview, start); modify `services/storage.py` (`deletions` table and helpers, `deleting` stamp writes in the transaction), `services/threads.py` and `services/missions.py` (`delete` becomes a call into `deletion`), `main.py` (routes from spec §6), `services/access_readers.py`, `services/auth.py`.
- [ ] Implement spec §1, §2, §3 and §4 steps 1-2 and 4:
  - `planned.cancel_for_delete(mid)` stops the plan and its stages without `may_approve`;
  - browse stop flag; missions close as dropped;
  - programs pause **without** releasing commitments, after their emissions (commitment ids, plus per commitment its exception and finding ids) are snapshotted into the deletion row.
- [ ] `start`:
  - takes `storage.db_lock`, then `storage.db.transaction()`;
  - does the stop work after commit, outside the transaction;
  - recomputes the closure and checks the actor (active, allowed) and the token inside the transaction.
- [ ] Gate: `test_deletion_core.py` (all), `test_access_register.py`, `test_auth.py`, `test_threads*.py` and `test_missions*.py` neighbours that exercise `delete`.

### Task 3 (Codex): hide at once

**Files:** `services/access.py`, `services/subjects.py`, `services/storage.py` (chat predicate), `services/home_board.py`, `main.py` (consumers), `services/programs.py` (practice readers).
- [ ] Implement spec §4 step 3:
  - `access.gone(kind, row)`, called first in every primitive listed there;
  - subject resolution treats a pointer to a gone thread, mission, program or project as unreadable;
  - a **gone** outcome for calendar and commitment readers, with every consumer skipping it;
  - one chat-visibility predicate, applied before the limit in `get_channel_messages` and in channel previews, `get_unread_counts` and delivery, resolving refs in one batch per read;
  - the board cache invalidated synchronously from `start`, with `deleting` in `_access_input_digest`.
- [ ] Gate: `test_deletion_hide.py` (all); `test_access_matrix.py` (all classes, `PYTHONUTF8=1`, ~30 min, once at the end); `test_access_core.py`; `test_access_calendar.py`; `test_project_audience_boundaries.py`; the channel and message tests (`grep -l get_channel_messages tests/*.py`).

### Task 4 (Codex): late work cannot write

**Files:** `services/deletion.py` (registry, `acting_for`, `check`, `Cancelled`); `services/storage.py` (child-insert refusals for gone parents; `deletion.check()` in insert and update helpers; raw-table writers moved behind helpers: thread-history append/update, program-session append, program claims, lesson replacement, `app_voice.py` card update); `services/calendar.py` and `services/chat_actions.py` (check before the Google insert); file writes in `browse.py` and `threads.add_photo` (photo path recorded before bytes, under `threads/<thread id>/`); outgoing mail; workers wrapped in `acting_for` (the full inventory in spec §5, with the browse reservation transferred to its daemon); `missions._steer_check` (gone means Stopped); creation bound at insert (`threads.create`, `programs.create_row`, `missions.launch`, kit-thread insert; adoption refuses a gone project or source); queued deliveries (`main._fanout_message_notifications`, practice pushes, lesson voice timers re-check at delivery); typed `refs` on new Argyle messages; `Cancelled` re-raised past broad handlers on these paths.
- [ ] Gate: `test_deletion_late_work.py` (all), `test_deletion_core.py`, `test_deletion_hide.py`, plus the neighbours of every wrapped worker. Find those with `grep -l` over tests for each module touched, and list them in the report. Run the browse, planned, programs, lessons, watchers, replies and asks tests at minimum.
- [ ] After Task 4's review is clean, the controller pushes Tasks 1-4.

### Task 5 (Codex): cleanup and the maintenance loop

**Files:** `services/deletion.py` (`maintain`, the steps in spec §5, the orphan pass); `main.py` lifespan (a 2-minute loop independent of watcher, notification and settings gates, plus one run at startup).
- [ ] Implement spec §5 steps 1-9 and the orphan pass, children before parents, each step idempotent by id. Use the emissions snapshot. Remove legacy thread photos through the media-root lookup before history is deleted.
- [ ] Gate: `test_deletion_cleanup.py` (all), `test_deletion_core.py`, `test_deletion_late_work.py`, `test_project_holds.py`, `test_programs*.py` (release and emissions), `test_watchers.py`.

### Task 6 (Codex): reserved for fix waves

No planned work. If a review finds a cross-task defect too large for a fix round, it is ruled into this task. Otherwise it is skipped.

### Task 7 (Claude subagent): the UI

**Files:**
- `templates/components/projects_page.html`: project Delete next to Drop; piece-card Delete and Remove; folding.
- `templates/components/threads_page.html` and `missions_page.html`: they call the shared preview and confirm instead of their own; all of a thread's missions are listed, removing the 5 cap at `main.py:7246`.
- `templates/app.html`: the phone thread sheet gets a mission-history fetch and Delete.
- `tests/test_deletion_live.py`.
- [ ] One shared helper builds the confirm text: titles, then "Linked trips, lists and events stay.". It handles `refused` and `changed` with `showGlobalAlert`, and previews again after `changed`.
- [ ] Folding follows spec §7 exactly: fold only beneath a rendered thread card that exposes the mission's actions; otherwise the mission keeps its standalone card.
- [ ] Live tests:
  - project Delete names its pieces and deletes;
  - a piece's Delete and Remove;
  - folding when the thread card renders;
  - standalone fallback for a keeper-only viewer and for a missing thread piece;
  - the phone thread sheet lists every mission;
  - a child owner gets "Ask a parent to delete this." when the project holds something they cannot see;
  - screenshots in light and dark at phone width, inspected.
- [ ] Gate: `test_deletion_live.py`, `test_projects_detail_live.py`, `test_projects_live.py`, `test_project_card_live.py`, `test_record_sheet_live.py`, `test_project_sheets_phone_live.py`.

### Task 8 (Claude): close-out

- [ ] Final whole-branch review on the most capable model, then ONE fix wave and one scoped re-review.
- [ ] Gate once more:
  - every file named above;
  - `test_access_matrix.py`, all classes.
- [ ] Docs and memory:
  - `chauffeur/system_capabilities.md`: the top entry, with device steps (rebuild; delete a test project with a running browse mission; confirm it vanishes on every phone and the wall at once; after a few minutes the DM cards and screenshots are gone; a child's Delete on a project holding a parent's mission says "Ask a parent to delete this."). NEXT becomes the program library split spec.
  - memory: `projects-delete-slice.md` and `projects-arc.md`.
- [ ] Bump, commit and push.

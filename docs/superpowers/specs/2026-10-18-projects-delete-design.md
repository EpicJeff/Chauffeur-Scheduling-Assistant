# Projects delete slice

**Status:** rev 2, 2026-10-18. Rev 1 went to Codex adversarial review (19 findings, §11); the user ruled the reach of "gone completely" (option A, §2). For Codex's second review and then the user's review.
**Inputs:** the user's rulings (memory `projects-delete-slice.md`, 2026-10-16/17/18), Codex's 20 findings on the earlier chat design (`2026-10-16-projects-delete-design-review-input.md`), and project audiences (v2.499.533-.546), which removed the wrapper case.

## Rulings this spec carries (user)

- The project owner and parents delete a project.
- Delete means **gone completely**: the project and its pieces, with no tombstone, no history, no record kept.
- Threads, missions and programs get **Delete**. Every other linked kind (trip, occasion, event, member, contact, list, project) gets **Remove** (unlink only).
- One `promptConfirm` names everything that will go.
- Programs are deleted with their project until the program library split.
- A mission launched from a thread in the same project lives inside that thread's card.
- Deleting the last piece never deletes the project.
- **Running work (option A):** the tap hides the project and its pieces at once and stops everything; cleanup finishes once the work has actually stopped; nothing of the mark survives.
- **Reach (option A, 2026-10-18):** the deleted records and everything attached to them go (DM cards, asks, proposals, findings, notes, files, step summaries, thread-history entries). Records elsewhere that merely pointed at them survive without the pointer, readable only by the people who could read them at that moment. Mind insights and a person's own Argyle conversation text that mention the project stay (accepted gap).

## 1. One deletion service

`services/deletion.py` owns every hard delete of a project, thread, mission or program. `threads.delete` and `missions.delete` become thin calls into it, so a standalone delete and a project delete share one closure rule, one start and one cleanup.

```
deletion.preview(kind, id, actor) -> {'status': 'ok', 'token': str, 'items': [{kind, id, title}], 'links': n}
                                   | {'status': 'refused', 'message': str}
deletion.start(kind, id, actor, token) -> {'status': 'ok'} | {'status': 'refused' | 'changed', 'message': str}
deletion.maintain()                     -> one pass of §5 for every started deletion, then the orphan pass
```

## 2. The closure: what goes

Computed from authoritative fields, never from `pieces[]` alone (Codex r1-13):

- **A project P:** every thread, mission and program with `project_id == P`; the project row.
- **A thread T:** T and every mission with `origin_kind == 'thread' and origin_ref == T`, wherever it lives (missions follow their thread).
- **A mission M:** M.
- **A program G:** G and its kit threads (`emissions.thread_ids`) that still exist, with their origin missions.
- Closed under the thread rule.

Records outside the closure that point at a closure record (a subject or `subject_history` entry naming it, or naming P) are **not** deleted (user, option A; Codex r2-3). §5 step 6 removes the pointer and pins their readers. Linked records of other kinds are never touched; their `pieces[]` entry goes with the project row.

## 3. Who may delete, and what the confirmation names

- **A project:** its owner, or a parent who sees it. A device actor (panel, speaker) never qualifies.
- **A thread or mission (standalone):** `access.record_actable(kind, row, actor, 'delete')`, as today.
- **A program (standalone, new):** the owner of its project, or a parent, provided the actor can read the program.
- **Every closure record must be readable by the actor** (`record_view` not None). One that is not refuses the whole delete with "Ask a parent to delete this." and names nothing (Codex r1-3, r1-5, r2-2). So a child owner deletes their own project only when they can see everything in it; parents normally see all of a child's project.
- **The token.** `preview` returns the closure's titles and a token (a hash of the sorted closure ids and their `rev`s). `start` recomputes the closure and refuses with `changed` ("This project changed. Look again.") unless the token matches, so a delete never takes more than the confirmation named (Codex r2-4).
- Linked kinds need no permission (Codex r1-4).

## 4. Start: hide and stop (synchronous, on the tap)

`deletion.start` runs inside one database transaction (`storage_sqlite`'s reentrant transaction, Codex r2-5):

1. Recompute the closure, check §3 and the token.
2. Write one deletion row (`deletions` table: id, kind, root id, closure ids, actor, started_at, state `started`) and stamp `deleting: <deletion id>` on every closure row.

After the transaction commits, still in the request:

3. **Hide.** One check, `access.gone(kind, row)` (the row is missing, or carries `deleting`), runs first in every visibility primitive: `projects.can_see`, `access.project_visible`, `record_view`, `channel_view`, `mission_view`, `practice_hidden`, the hold readers, `commitment_view` and `finding_view` (Codex r2-12). Calendar reads drop practice events, holds and commitments whose emitter is gone. Chat message readers drop a message whose card names a gone record (§5 step 1's refs), so ask and project cards vanish at once (Codex r2-14). The board cache is invalidated synchronously and its access digest includes `deleting` (Codex r2-13). The schedule is marked dirty.
4. **Stop.** Authorized by the delete check, not by plan approval (Codex r1-10): `planned.cancel_for_delete(mid)` stops each closure mission's plan and stages; browse missions get their stop flag; live missions close as dropped; programs pause. These are deletion's own writes and go through normally (Codex r2-6).

The person sees the project gone when the request returns.

## 5. Finish: wait for exit, then clean up

**Workers register (Codex r2-9, r2-10).** Every background worker that can write on behalf of a thread, mission or program enters `deletion.working(kind, id)` (a context manager that registers before dispatch and unregisters in `finally`): the browse daemon (`missions.py` ~1055), mission turns, build and work stage runners, program approval and resume, lesson generation. Each worker also calls `deletion.check(kind, id)` before every side effect (a tool call, a storage write, an external calendar insert, a file write), which raises `deletion.Cancelled` once its source is gone. `missions._steer_check` treats a gone mission as Stopped. Elapsed time never proves a worker has exited: after 15 minutes a still-registered worker is re-cancelled and logged, and cleanup keeps waiting.

**Creation is bound at insert (Codex r2-7).** `threads.create`, `programs.create_row`, `missions.launch` and the program kit-thread insert take their project at insert time; an insert into a gone project, or on behalf of a gone source, is refused before the row exists. Adoption never creates a replacement wrapper for a record whose source or project is gone.

**Children of gone parents are refused (Codex r1-14, r2-8).** Storage refuses to insert a child whose parent is gone: mission steps, asks, findings (by subject), program lessons, commitments (by source program), action proposals (by source), thread-history and program-session appends, and chat messages carrying a gone ref. The raw-table writers Codex listed (thread-history append/update, program-session append, program claims, lesson replacement, `app_voice.py` card update) move behind these helpers.

**Queued deliveries re-check (Codex r2-16).** Push fan-out re-reads the message (and its refs) just before sending; practice pushes and lesson voice timers carry their source ids and re-check before delivery. A request already in flight to an outside service (an email being sent, a Google Calendar insert awaiting its reply) completes; its result is discarded if the source is gone (accepted gap, §9).

**`deletion.maintain()`** runs on its own loop every 2 minutes, independent of watchers, notifications and settings, and once at startup (Codex r2-17). For each `started` deletion with no registered worker left, it removes, **children before parents, each step idempotent by id** (Codex r1-11, r1-12):

1. **Chat copies** (Codex r1-15, r2-15). Before any ledger row is deleted, collect the closure's ask ids and proposal ids. Delete every chat message whose card names a closure record (`mission_id`, `thread_id`, `program_id`, `project_id`) or a collected `ask_id` or `proposal_id`, body and all, including project-start, ask, action and mission-done cards. From now on Argyle messages carry typed refs `refs: [{kind, id}, ...]` (several for a consolidated watcher message); a message is deleted when every ref is gone and has the gone ref removed otherwise. Older plain-text notices with no card and no ref stay (§9).
2. **Ledgers:** action proposals with a closure source; asks on closure records and on their findings.
3. **Findings** on closure records; commitment findings and protected exceptions keyed by the closure programs' commitments (Codex r1-18).
4. **Program emissions:** `release_commitments` keeps failed ids and reports failure; the step retries until every commitment is gone (Codex r1-11). Program lessons.
5. **Files.** Browse screenshots live in `browse/<mission id>/`; thread photos are saved under `threads/<thread id>/` with the path recorded before the bytes are written (Codex r2-11). Both folders are removed.
6. **Surviving records** (Codex r1-1, r1-17, r2-1, r2-18):
   - A surviving thread, mission or program whose `subject` or any `subject_history` entry names a closure record or the deleted project: before the entry is removed, its readers are pinned. `restricted_to` is set to the members who can read it at this moment, and `access.record_view` from then on also requires the viewer to be in `restricted_to`. Only member ids are stored, no content.
   - Thread history entries that summarize a closure mission are removed.
   - On surviving projects:
     - each step that named a closure mission loses its `mission_id`, `attempts`, `found`, `question` and stage payloads;
     - an unfinished step becomes `blocked` with "Its work was deleted.";
     - `origin_mission_id` naming a closure mission is cleared;
     - `wrapped_from` naming a closure record is cleared;
     - the closure record's `pieces[]` entry is removed.
   - A deleted thread's id is removed from surviving programs' `emissions.thread_ids`.
   - App-state keys naming a closure record (`mission_steer:{id}`, triage focus, watcher-notified, practice-pushed) are removed.
7. Mission steps, then mission rows; thread rows; program rows.
8. The project row (a project deletion). Its steps, holds and `pieces[]` go with it. The schedule is refreshed once.
9. The deletion row itself. Nothing of the mark survives.

**The orphan pass** (same loop) removes children whose parent no longer exists (browse and thread folders, lessons, asks, findings, steps, app-state keys) and catches anything a racing writer left between a check and its write.

## 6. Routes

- `GET /api/deletion/{kind}/{id}/preview`, which calls `deletion.preview`.
- `DELETE /api/projects/{id}`, `/api/threads/{id}`, `/api/missions/{id}` and `/api/programs/{id}` (body `{token}`), which call `deletion.start`. A refusal answers 403 with its message, a closure that moved answers 409 with "changed", and a record the actor cannot see answers 404.
- Each route gets a `READERS` row. Auth rules are checked for `/api/programs/*` and `/api/deletion/*` and added if missing.
- No Argyle delete tool; deletion stays by hand only.

## 7. UI

- **Project page.** A red Delete next to Drop, for the owner or a parent who sees the project. It calls `preview`, then shows one `promptConfirm` that lists every thread, mission and program by title and ends "Linked trips, lists and events stay." On `refused` or `changed` it uses `showGlobalAlert`; after `changed` it previews again.
- **Piece cards.** Threads, missions and programs get Delete, with the same preview and confirm for that record. Other linked kinds get Remove (`projects.remove_piece`, which no UI calls today), shown to whoever can act on the project.
- **Thread-origin missions (Codex r1-20, r2-19).** A mission launched from a thread in the same project folds into that thread's card only when that thread card is actually rendered for the viewer and exposes the mission's actions. Otherwise the mission keeps its own card: a missing `pieces[]` entry, a keeper-only viewer, or a phone surface without mission history all leave it standalone. The thread sheet lists **all** its missions, not just five, each with open and Delete, on both admin and phone. The phone thread sheet gains the mission-history fetch.
- No browser dialogs. Tailwind is rebuilt after template changes.

## 8. Tests (written first)

- **Closure:** pieces found by `project_id` even when `pieces[]` lost the entry; origin missions homed in another project; a program's kit thread; closed under the thread rule; a record elsewhere about P is not in the closure.
- **Authorization:**
  - owner, parent, other adult, child owner, panel;
  - a closure record the actor cannot read refuses with "Ask a parent to delete this." and changes nothing;
  - a linked trip never blocks;
  - no hidden title appears in a preview or refusal;
  - a token mismatch refuses with `changed` and deletes nothing.
- **Start:**
  - start is one transaction: a crash between stamps leaves nothing stamped;
  - after `start`, every access-matrix class (4.1-4.8) returns nothing for the project and every closure record, including a warm wall board, a cached schedule, DM cards and the hold readers.
- **Late work:**
  - a browse turn, a build stage row (`create_thread`, `propose_program`, an update to a linked trip, `create_event`), a work stage, lesson generation, program approval and resume, a watcher sweep and a queued push or voice timer, each finishing after `start`, write nothing, create nothing and deliver nothing;
  - cleanup waits while any of them is registered;
  - adoption never makes a replacement wrapper.
- **Cleanup:**
  - zero rows and files left for every table and folder in §5;
  - a pass interrupted after each step and re-run reaches the same end state;
  - a commitment whose delete fails keeps its program until it succeeds;
  - the orphan pass removes a screenshot written after the check;
  - maintenance runs with watchers off and resumes after a restart.
- **Surviving records:**
  - a household thread whose subject was a deleted private thread keeps exactly its readers from the moment of deletion (no widening) and loses the pointer;
  - surviving steps, history, emissions and app state carry nothing of the deleted records.
- **Standalone deletes:** a thread (its missions go, wherever they live), a mission, a program (its kit thread goes); deleting the last piece leaves the project.
- **UI live:**
  - project Delete shows the names and deletes;
  - a piece's Delete and Remove;
  - folding when the thread card renders;
  - standalone fallback for a keeper-only viewer and for a missing thread piece;
  - the phone thread sheet lists all missions.

## 9. Accepted gaps

- Mind insights, and a person's own Argyle conversation text, that mention a deleted record stay (user, option A). An in-flight Mind think may store words from a just-deleted source.
- Argyle notices posted before this ships as plain text, with no card and no ref, stay in DMs.
- Words already sent by mail, pushed or read aloud cannot be recalled. A request already in flight to an outside service completes, and its result is discarded.

## 10. Split

Claude writes the tests first and builds the UI. Codex builds `deletion.py`, the worker registry and checks, the insert binding, the storage refusals, the delivery re-checks, the maintenance loop and the routes. Each side's work is reviewed by the other model, and a final whole-branch review closes it.

## 11. Codex reviews

**Rev 1 (2026-10-18), 19 findings, answered in rev 2:**

| Finding | Where answered |
|---|---|
| 1 Dangling pointers widen readers | §5 step 6 pins readers with `restricted_to` |
| 2 Delete authority vs disclosure, and the child owner | §3: every closure record must be readable |
| 3 Historical association destroys unrelated work | §2: records elsewhere are not deleted (user option A) |
| 4 Delete exceeds the confirmation | §3: the token |
| 5 Start is not atomic | §4: one transaction |
| 6 The fence blocks deletion's own writes | §4 step 4: deletion's own writes go through, and the update fence is dropped in favour of waiting for exit |
| 7 Insert happens before adopt | §5: creation bound at insert |
| 8 Late updates and external writes | §5: `deletion.check` before every side effect |
| 9, 10 No idle signal; the timeout | §5: workers register; time never proves exit |
| 11 Files | §5 step 5: provenance before bytes |
| 12 Read boundaries | §4 step 3: `access.gone` first in every primitive |
| 13 Board cache | §4 step 3 |
| 14 Stored copies and Mind | §4 step 3 hides DM cards; Mind is an accepted gap |
| 15 Card shapes | §5 step 1: ask and proposal ids, typed refs |
| 16 Queued deliveries | §5: re-check at delivery |
| 17 Maintenance tied to watchers | §5: its own loop and startup |
| 18 Derived content on steps and projects | §5 step 6 |
| 19 Folding reachability | §7 |

# Projects delete slice

**Status:** rev 3.1, 2026-10-18 (3.1: the gone definition no longer treats a merely missing row as gone, after the Task 3 review found it would hide retention-pruned history). Rev 1 and rev 2 each went to Codex adversarial review (§11); the user ruled the reach of "gone completely" (option A). Rev 3 replaces rev 2's reader pin with a fail-closed dangling pointer (Claude's call, flagged for the user in the Rulings). For the user's review.
**Inputs:** the user's rulings (memory `projects-delete-slice.md`, 2026-10-16/17/18), Codex's 20 findings on the earlier chat design (`2026-10-16-projects-delete-design-review-input.md`), and project audiences (v2.499.533-.546), which removed the wrapper case.

## Rulings this spec carries (user)

- The project owner and parents delete a project.
- Delete means **gone completely**: the project and its pieces, with no tombstone, no history, no record kept.
- Threads, missions and programs get **Delete**. Every other linked kind (trip, occasion, event, member, contact, list, project) gets **Remove** (unlink only).
- One `promptConfirm` names everything that will go.
- Programs are deleted with their project until the program library split.
- A mission launched from a thread in the same project lives inside that thread's card.
- Deleting the last piece never deletes the project.
- **Survivors fail closed (Claude, rev 3, for the user to confirm):** a surviving record keeps the bare id of the deleted record it pointed at (no content). A pointer to a deleted thread, mission, program or project counts as unreadable, so the survivor is readable only by its own person, at their keeper view. This replaces rev 2's per-reader pin, which Codex showed was captured too late, could promote a keeper to full access, was bypassed by channel and mission reads, and could lock out a newly assigned owner. It narrows option A's "the people who could read it at that moment" to "its own person".
- **Running work (option A):** the tap hides the project and its pieces at once and stops everything; cleanup finishes once the work has actually stopped; nothing of the mark survives.
- **Reach (option A, 2026-10-18):** the deleted records and everything attached to them go (DM cards, asks, proposals, findings, notes, files, step summaries, thread-history entries). Records elsewhere that merely pointed at them survive. Mind insights and a person's own Argyle conversation text that mention the project stay (accepted gap).

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

Records outside the closure that point at a closure record (a subject or `subject_history` entry naming it, or naming P) are **not** deleted (user, option A; Codex r1-3). They keep the pointer; §4 step 3 makes it fail closed. Linked records of other kinds are never touched; their `pieces[]` entry goes with the project row.

## 3. Who may delete, and what the confirmation names

- **A project:** its owner, or a parent who sees it. A device actor (panel, speaker) never qualifies.
- **A thread or mission (standalone):** `access.record_actable(kind, row, actor, 'delete')`, as today.
- **A program (standalone, new):** the owner of its project, or a parent, provided the actor can read the program.
- **Every closure record must be readable by the actor** (`record_view` not None). One that is not refuses the whole delete with "Ask a parent to delete this." and names nothing (Codex r1-2, r1-3, r1-5). So a child owner deletes their own project only when they can see everything in it; parents normally see all of a child's project.
- **The token.** `preview` returns the closure's titles and a token: a hash of the canonical confirmation snapshot, the sorted `(kind, id, title)` triples it displayed (Codex r2-N5; threads and programs carry no reliable `rev`). `start` recomputes the closure and refuses with `changed` ("This project changed. Look again.") unless the token matches, so a delete never takes more than the confirmation named (Codex r1-4).
- Linked kinds need no permission (Codex r1-4).

## 4. Start: hide and stop (synchronous, on the tap)

`deletion.start` runs inside one database transaction (`storage_sqlite`'s reentrant transaction, Codex r1-5):

1. Recompute the closure, check §3 and the token.
2. Write one deletion row (`deletions` table: id, kind, root id, closure ids, actor, started_at, state `started`) and stamp `deleting: <deletion id>` on every closure row.

After the transaction commits, still in the request:

3. **Hide.** One check, `access.gone(kind, row)`, runs first in every visibility primitive (rev 3.1: **gone** means the row carries `deleting`, or an open `deletions` row names it, or, for a survivor's pointer, the pointer entry carries `gone: true` set by cleanup step 6; a row that is merely missing, as after a retention prune, behaves as today, so old history is not hidden; findings about a missing subject are hidden): `projects.can_see`, `access.project_visible`, `record_view`, `channel_view` (including `_legacy_channel_visible`), `mission_view` (including its origin-thread shortcut), `practice_hidden`, the hold readers, `commitment_view`, `finding_view` and `finding_visible` (Codex r1-12, r2-N3, r2-N7). In subject resolution, a subject or history entry naming a gone thread, mission, program or project counts as unreadable for every viewer, which leaves a survivor's own person their keeper view and hides it from everyone else (the fail-closed pointer). Calendar and commitment readers get a third outcome beside full and neutral, **gone**, and every consumer skips gone rows instead of indexing them (`event_view`, `/api/commitments`, `schedule_view`; Codex r2-N7). Chat messages are filtered by one shared predicate (a message whose card or `refs` name a gone record is hidden) applied **before** pagination and in channel previews, unread counts and delivery, with the distinct refs of a read resolved in one batch (Codex r1-14, r2-N9). The board cache is invalidated synchronously and its access digest includes `deleting` (Codex r2-13). The schedule is marked dirty.
4. **Stop.** Authorized by the delete check, not by plan approval (Codex r1-10): `planned.cancel_for_delete(mid)` stops each closure mission's plan and stages; browse missions get their stop flag; live missions close as dropped; programs pause. These are deletion's own writes and go through normally (Codex r1-6). Before a program is paused, the deletion row records its full emissions (commitment ids and, per commitment, the ids of its exceptions and findings), because an ordinary pause releases commitments and clears their ids (Codex r2-N10); the deletion pauses without releasing, and §5 step 4 releases.

The person sees the project gone when the request returns.

## 5. Finish: wait for exit, then clean up

**Workers register and carry their source (Codex r1-9, r1-10, r2-N6).** Work done on behalf of a thread, mission or program runs inside `deletion.acting_for(kind, id)`, which (a) registers the work before it is scheduled and unregisters it when its result has been handled, and (b) sets a context variable naming the source, copied into any thread or timer it starts (`contextvars.copy_context`). A browse daemon receives a reservation made before `Thread.start()` and releases it in its own `finally`. `deletion.check()` reads the context's source and raises `deletion.Cancelled` once it is gone. It is called by the storage insert and update helpers, the Google Calendar insert, file writes and outgoing mail. So a generic tool (`_create_event`, `create_thread`) is fenced without a source argument, and a check and its local write happen under `storage.db_lock` together with the deletion's admission (start takes the same lock). `Cancelled` is re-raised past the broad exception handlers on these paths.

The workers: the browse daemon, mission turns, build and work stage runners, program approval and resume, lesson generation, watcher program mutations, reconciliation and posting, reply classification and deferred DMs, ask application and recovery, coalesced situation-refresh timers, request-driven thread draft, send, research and photo operations, and direct proposal execution (Codex r2-N6). `missions._steer_check` treats a gone mission as Stopped. Elapsed time never proves exit: after 15 minutes a still-registered worker is re-cancelled and logged, and cleanup keeps waiting.

**Creation is bound at insert (Codex r1-7).** `threads.create`, `programs.create_row`, `missions.launch` and the program kit-thread insert take their project at insert time; an insert into a gone project, or on behalf of a gone source, is refused before the row exists. Adoption never creates a replacement wrapper for a record whose source or project is gone.

**Children of gone parents are refused (Codex r1-14, r1-8).** Storage refuses to insert a child whose parent is gone: mission steps, asks, findings (by subject), program lessons, commitments (by source program), action proposals (by source), thread-history and program-session appends, and chat messages carrying a gone ref. The raw-table writers Codex listed (thread-history append/update, program-session append, program claims, lesson replacement, `app_voice.py` card update) move behind these helpers.

**Queued deliveries re-check (Codex r2-16).** Push fan-out re-reads the message (and its refs) just before sending; practice pushes and lesson voice timers carry their source ids and re-check before delivery. A request already in flight to an outside service (an email being sent, a Google Calendar insert awaiting its reply) completes; its result is discarded if the source is gone (accepted gap, §9).

**`deletion.maintain()`** runs on its own loop every 2 minutes, independent of watchers, notifications and settings, and once at startup (Codex r2-17). For each `started` deletion with no registered worker left, it removes, **children before parents, each step idempotent by id** (Codex r1-11, r1-12):

1. **Chat copies** (Codex r1-15, r2-15). Before any ledger row is deleted, collect the closure's ask ids and proposal ids. Delete every chat message whose card names a closure record (`mission_id`, `thread_id`, `program_id`, `project_id`) or a collected `ask_id` or `proposal_id`, body and all, including project-start, ask, action and mission-done cards. From now on Argyle messages carry typed refs `refs: [{kind, id}, ...]` (several for a consolidated watcher message). A message with any gone ref is deleted whole, the same rule the read predicate uses, so a mixed message never reappears with a deleted line in it (Codex r2-N8). Older plain-text notices with no card and no ref stay (§9).
2. **Ledgers:** action proposals with a closure source; asks on closure records and on their findings.
3. **Findings** on closure records; commitment findings and protected exceptions keyed by the closure programs' commitments (Codex r1-18).
4. **Program emissions**, from the snapshot in the deletion row: `release_commitments` keeps failed ids and reports failure, and the step retries until every commitment is gone (Codex r1-11). Program lessons.
5. **Files.** Browse screenshots live in `browse/<mission id>/`. New thread photos are saved under `threads/<thread id>/`, with the path recorded before the bytes are written (Codex r1-11). Existing thread photos are UUID files in the shared media archive. Before a thread's history is deleted, each `media_id` in it is resolved through the media-root lookup and its file removed (Codex r2-N11). Both folders are removed.
6. **Surviving records** (Codex r1-17, r1-18). A survivor's subject pointer to a closure record is **kept** as a bare id with `gone: true` on the entry (written here, before the record row goes, so the pointer fails closed after cleanup too; §4 step 3). Everything else goes:
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
  - a program's emissions are snapshotted before its pause, and the commitment exceptions and findings are still removed later;
  - calendar and commitment readers skip gone rows without error, and chat pagination, previews and unread counts stay consistent when gone messages are hidden;
  - after `start`, every access-matrix class (4.1-4.8) returns nothing for the project and every closure record, including a warm wall board, a cached schedule, DM cards and the hold readers.
- **Late work:**
  - a stage blocked inside `_create_event` when deletion starts inserts nothing afterwards;
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
  - a household thread whose subject was a deleted private thread becomes readable only by its own person, at their keeper view, on every surface (record, channel, mission origin, practice), never widening;
  - a survivor whose owner is later changed keeps failing closed, with no lockout error;
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

**Rev 2 (2026-10-18): 11 of the rev 1 findings answered, 8 partly; 11 new findings (N1-N11), answered in rev 3:**

| Finding | Where answered |
|---|---|
| N1-N4 Reader pin: captured late, promotes keepers, bypassed, can lock out a new owner | §2 and §4 step 3: the pin is dropped; the dangling pointer fails closed |
| N5 No reliable `rev` | §3: the token hashes the displayed snapshot |
| N6 Incomplete worker inventory; nested tools; lifetime | §5: `acting_for` registers and carries the source in a context variable; full inventory; checks under the lock |
| N7 Calendar return contracts | §4 step 3: a gone outcome that consumers skip; `finding_visible` audited |
| N8 Mixed messages | §5 step 1: deleted whole |
| N9 Pagination, previews, counts | §4 step 3: one predicate, before the limit, batched |
| N10 Pause releases emissions | §4 step 4: emissions snapshotted, pause without release |
| N11 Legacy thread photos | §5 step 5 |


**Rev 1 (2026-10-18), 19 findings, answered in rev 2:**

| Finding | Where answered |
|---|---|
| 1 Dangling pointers widen readers | rev 2 pinned readers; rev 3 replaces the pin with a fail-closed pointer (§4 step 3) |
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

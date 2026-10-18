# Projects delete slice

**Status:** draft rev 1, 2026-10-18, for Codex adversarial review and then the user's review.
**Inputs:** the user's rulings (memory `projects-delete-slice.md`, 2026-10-16/17), Codex's 20 findings on the earlier chat design (`2026-10-16-projects-delete-design-review-input.md`), and project audiences (v2.499.533-.546), which removed the wrapper case.

## Rulings this spec carries (user)

- The project owner and parents delete a project.
- Delete means **gone completely**: the project and its pieces, with no tombstone, no history, no record kept.
- Threads, missions and programs get **Delete**. Every other linked kind (trip, occasion, event, member, contact, list, project) gets **Remove** (unlink only).
- One `promptConfirm` names everything that will go.
- Programs are deleted with their project until the program library split.
- A mission launched from a thread in the same project lives inside that thread's card.
- Deleting the last piece never deletes the project.
- **Running work (option A):** the tap hides the project and its pieces at once and stops everything; a transient deleting mark makes every late writer treat them as cancelled; cleanup finishes when the work is idle and removes the mark too.

## 1. One deletion service

`services/deletion.py` owns every hard delete of a project, thread, mission or program. The existing `threads.delete` and `missions.delete` become thin calls into it, so a standalone delete and a project delete share one path, one closure rule and one cleanup.

```
deletion.preview(kind, id, actor) -> {'status': 'ok', 'items': [{kind, id, title}], 'links': n} | {'status': 'refused', 'message'}
deletion.start(kind, id, actor)   -> {'status': 'ok'} | {'status': 'refused', 'message'}
deletion.sweep()                   -> finishes every started deletion whose work is idle (§5)
```

## 2. The closure: what goes

The closure is computed once, from authoritative fields, never from `pieces[]` alone (Codex 13).

- **A project P:** every thread, mission and program with `project_id == P`; every thread or mission whose current subject or any `subject_history` entry is P (records about P, wherever they live); the project row itself.
- **A thread T:** T; every mission with `origin_kind == 'thread' and origin_ref == T` (they follow their thread, wherever they live).
- **A mission M:** M.
- **A program G:** G; its kit threads (`emissions.thread_ids`) that still exist, and their origin missions.
- The closure is closed under the thread rule (a thread in the closure brings its origin missions).

Linked records of other kinds are never in a closure. Their only change is that the deleted project's `pieces[]` goes with its row.

## 3. Who may delete

- A **project**: the actor sees it and is its owner, or a parent who sees it. A device actor (panel, speaker) never qualifies. A child may delete a project they own.
- A **thread or mission**: `access.record_actable(kind, row, actor, 'delete')`, as today.
- A **program**: the owner of its project, or a parent who sees the program. (Today no program delete exists.)
- **Every record in the closure** must pass its own rule for the actor (Codex 3), checked before anything is stopped or written. Linked kinds need no permission (Codex 4).
- **Refusal never names a hidden record** (Codex 5): when any closure record fails, `preview` and `start` both answer "Something in this project isn't yours to delete. Ask a parent." with no titles. `preview` names items only after the whole closure passes.

## 4. Start: hide, stop, fence (synchronous, on the tap)

`deletion.start` runs under `storage.db_lock`, all or nothing:

1. Recompute the closure and re-check §3 (the preview may be stale).
2. Stamp every closure row and the project row (when a project is deleted) with `deleting: {by, at}`.
3. **Hide.** `access.record_view` returns None and `access.project_visible` returns False for any row carrying `deleting`, for every viewer, on every surface. Calendar reads drop practice events, holds and commitments whose emitter (program or project) is missing or deleting (fail closed at read; Codex 2); the schedule is marked dirty.
4. **Stop running work**, authorized by the delete check rather than by plan approval (Codex 10): for each closure mission, `planned.cancel_for_delete(mid)` stops the plan and its stages; browse missions get their stop flag; live missions close as dropped; a program is paused for the scheduler.

Then the request returns. The person sees the project gone at once.

**The fence (Codex 7, 8, 9, 14).** Late writers do not each need their own check; storage refuses them:
- An update of a row carrying `deleting`, or of a row that no longer exists, is a no-op.
- An insert of a child whose parent is missing or deleting is refused with `storage.Cancelled`: mission steps, asks, findings (by subject), program lessons, commitments (by source program), action proposals (by mission), project adoption into a missing or deleting project (no replacement wrapper is created).
- Inserts made while a closure mission is acting (the browse loop and the stage runner set `deletion.acting_for(mission_id)`, a context variable) are refused once that mission is missing or deleting, so a stage's `propose_program` or `create_thread` cannot create a new record after delete.
- `missions._steer_check` treats a missing or deleting mission as Stopped, and the browse loop checks again before each action and before writing a screenshot (`browse_dir` refuses a missing or deleting mission).
- Watcher reconciliation and every DM sender re-read the source before posting; a missing or deleting source posts nothing.

## 5. Sweep: finish when idle

`deletion.sweep()` runs on the watcher tick and once right after `start`. For each row carrying `deleting`, it proceeds when no worker is active for the closure (no browse turn running and no stage claim held for a closure mission; a run that has not reported within 10 minutes counts as finished). It deletes **children before parents, each step idempotent by id**, so a sweep that fails part-way simply runs again on the next tick (Codex 11, 12):

1. Chat messages and cards attributable to the closure: every message whose card names a closure record (`mission_id`, `thread_id`, `program_id`, `project_id`, including project-start, ask and mission-done cards) is deleted, body and all (Codex 15). Argyle messages posted from now on carry `ref: {kind, id}` so plain-text notices are found too; older plain-text notices without a ref stay (accepted gap, §9).
2. Action proposals whose source is a closure record; asks on closure records and on their findings (Codex 16).
3. Findings whose subject is a closure record, and findings and protected exceptions keyed by the closure programs' commitments (Codex 18).
4. Program emissions: `release_commitments` changed to keep failed ids and report failure; the sweep retries until every commitment is gone (Codex 11). Program lessons.
5. Files: browse screenshot folders of closure missions, photos saved by closure threads.
6. References in surviving records (Codex 17, 19): thread history entries that summarize a closure mission; `mission_id` and `attempts` entries on surviving projects' steps; a deleted thread's id in any surviving program's `emissions.thread_ids`; the `pieces[]` entry of a closure record in a surviving project; app-state keys (`mission_steer:{id}`, triage focus, watcher-notified, practice-pushed) that name a closure record.
7. Mission steps, then the mission rows; thread rows; program rows.
8. The project row last. With it go its steps, holds and `pieces[]`. The schedule is marked dirty and refreshed once.

**An orphan pass** on the same tick removes children whose parent no longer exists (browse folders, lessons, asks, findings, steps, app-state keys), catching anything a racing writer left between the fence check and the write.

## 6. Routes

- `GET /api/deletion/{kind}/{id}/preview` -> `deletion.preview`.
- `DELETE /api/projects/{id}`, `DELETE /api/threads/{id}`, `DELETE /api/missions/{id}`, `DELETE /api/programs/{id}` -> `deletion.start`; 403 with the generic message on refusal, 404 for a record the actor cannot see.
- Each route gets a `READERS` row; auth is covered by the existing `/api/projects/*`, `/api/threads/*`, `/api/missions/*` rules (`/api/programs/*` and `/api/deletion/*` checked and added if missing).
- No Argyle delete tool ("by hand only" stays).

## 7. UI

- **Project page:** a red Delete next to Drop, shown to the owner or a parent who sees it. It calls `preview`, then one `promptConfirm` listing every thread, mission and program by title and ending "Linked trips, lists and events stay." On refusal, `showGlobalAlert` with the generic message.
- **Piece cards:** threads, missions and programs get Delete (the same preview + confirm for that record's closure); other linked kinds get Remove (`projects.remove_piece`, which today has no caller), shown to whoever can act on the project.
- **Thread-origin missions (Codex 20):** a mission launched from a thread in the same project is not its own card for a viewer who sees the thread in full; it shows in the thread card, and the thread sheet lists **all** its missions (not five) with each one's open and Delete. A viewer who sees the mission only as its keeper keeps the standalone mission card.
- No browser dialogs; Tailwind rebuild after template changes.

## 8. Tests (written first)

- **Closure:** a project's pieces by `project_id` even when `pieces[]` lost the entry; records about P living elsewhere; origin missions homed in another project; a program's kit thread; closure closed under the thread rule.
- **Authorization:** owner, parent, other adult, child owner, panel; a closure record the actor cannot delete refuses the whole delete with the generic message and changes nothing; a linked trip never blocks; a hidden thread's title never appears in a preview or refusal.
- **Hide at once:** after `start`, every surface in the access matrix returns nothing for the project and every closure record (classes 4.1-4.8), including a cached schedule and a warm wall board.
- **The fence:** a browse turn, a stage row (`create_thread`, `propose_program`), a lesson generation, a program approval and a watcher sweep that each finish after `start` write nothing and send nothing; adoption never creates a replacement wrapper.
- **Sweep:** zero rows left for every table and file in §5; a sweep interrupted after each step and re-run reaches the same end state; a commitment whose delete fails keeps the program until it succeeds; the orphan pass removes a screenshot written after the fence check.
- **Standalone deletes:** thread (its missions go, wherever they live), mission, program (kit thread goes); each clears references in surviving records; deleting the last piece leaves the project.
- **UI live:** project Delete shows the names and deletes; a piece's Delete and Remove; a thread-origin mission inside its thread card; keeper-only viewer keeps the standalone card.

## 9. Accepted gaps

- Argyle notices posted before this ships as plain text, with no card and no ref, stay in DMs.
- A deleted record's words already sent by mail or read aloud cannot be recalled.

## 10. Split

Claude writes the tests first and builds the UI; Codex builds `deletion.py`, the fence, the sweep and the routes; each side's work is reviewed by the other model; a final whole-branch review closes it.

# Programs: a brief, a course page, one-pass setup, a monitoring sheet — design

**Date:** 2026-10-20. **Status:** rev 2, Codex adversarial review of rev 1 folded (33 findings on this spec, §13), for the user's review. **Builds on:** `2026-10-19-program-library-design.md` (library rows, runs, stable lesson ids, progress rules, the Argyle waiting choice), `2026-10-20-lesson-depth-design.md` (scripts, the per-program writing job, claim doors, the player), `2026-08-28-programs-design.md` and the v2.435/v2.436 repairs (curate over generate, three source tiers, footprints and slots). **Sibling:** `2026-10-20-projects-one-list-design.md`. **Locked rules kept:** a person judges a milestone, on any unjudged phase; no completion fraction on a program; curate over generate with the tier said on the face; the unattended writing job never reaches the paid key and never overwrites a hand-edited script without a distinct warning; a child never creates a library row; stable lesson ids; the v2.499.630 Done-today-or-earlier rule.

## Problem

The user, 2026-10-20: "I barely understand how to get through it and end up with a working result and I helped design it." "The main problem for setting up programs is lessons and how obscure they feel. It isn't really clear how you can affect the generated program and lessons to begin with, and ideally you wouldn't need to. And after they are written, there are a long list of steps, but I don't know what those are or how they will look."

The audit found programs living in three places with three vocabularies: the library page (28 button labels; every lesson row shows ▲ ▼ Edit Remove and, per script, a chip, Play, Edit, Regenerate at rest), the run sheet inside a project (58 labels across states; run, claim this time, footprint, Re-shape the week, ready to judge, rotation, variant, script, Write lessons, Regenerate, Made by the app, Published plan, unresolved), and the phone Today card. A parent who picks a library program for their own project lands on a *proposed* run and must open it and "Approve — claim this time". The programs page's own propose form (`programs_page.html` lines 19–107) is unreachable on every host.

The user's rulings: the admin sheet is for setting up and monitoring; practising happens on the wall and the phone and those are fine. Creation: "explain the program you want in plain language and have the agent pull the bits it needs out of that... steer it with more plain language."

## Decisions (the user's, 2026-10-20)

1. **Words in, program out.** A library program is made from a plain-language brief, in the Argyle DM or in a brief box on the Library page; both end at the same course preview with a Steer box and Looks good. The hand editor stays behind ⋯ › Edit by hand.
2. **Steer uses the hand model.** A steer produces one candidate curriculum, validated and committed through the library's own write path, so every rule the hand path enforces holds.
3. **Steer shows its work.** Every steer answers with a server-computed change list naming what moved and any visible runner it touched.
4. **Steering an in-use program changes it in place**, as a hand edit does. A new version only when the person says "make a variant".
5. **The library program page is a course page**: header with source and length, phases numbered with their done-when, each lesson one parent-facing sentence plus Preview.
6. **Preview is the lesson as the person gets it**: the existing player in preview mode.
7. **One-pass setup, lands active** for a parent's or adult's own pick; the times change afterwards from ⋯ › Change the days.
8. **The admin program sheet is monitoring**: stats, the ladder with the lit rung, Reached it, the session log folded, everything else in ⋯.
9. **Vocabulary pass** (§8).

## Rulings made while folding the review (for the user to confirm or overturn)

- **P1. "This week" is a count, never a fraction:** "2 sessions this week", with the shape ("3 a week") already in the header line. (Codex 30; the locked rule.)
- **P2. Reached it stays on every unjudged phase**, not only the current one (Codex 19; the library spec's rule). The current phase's is drawn beside the lit rung; the others sit on their phase heading.
- **P3. The phone keeps Edit by hand** (title, profile, lessons, order); only script editing, Regenerate and Write lessons stay admin-only, as today (Codex 14).
- **P4. ⋯ keeps the run's settings, Look again and Plan without the book** (Codex 15, 16): "Program settings" edits the run's private starting point, minutes and target date; "Look again" and "Plan without the book" are today's operations with their consequences stated (a new library program, progress starts over, scripts regenerate).
- **P5. Adults and parents approve and start.** The backend already allows adults (`main.py:8714`); the UI's parent-only `canApprove` and the copy at line 602 were the mismatch. Children never claim time. (Codex 24.)
- **P6. A brief that names nobody:** in the Argyle chat it is for the speaker (today's default, `agent_tools_v2.py:2681`); on the Library page it makes a library program only and offers "Start it for…". A brief naming a child on the Library page makes the program and opens the setup sheet with that child chosen. (Codex 44.)
- **P7. "Start a session" on the admin sheet is the real Start** with a window chooser (today or ahead, `slot_date` kept), not a "(test)" mode; it sits in ⋯. (Codex 31.)
- **P8. The Re-shape verb is replaced, its effect kept** [confirm]: Change the days covers an active or paused run; emptying the list hands the choice back to the app. A child keeper's change still goes through the proposed state (§5.3).

## 1. The brief

**Input.** One free-text paragraph. A new `services/program_brief.py`:

- `parse(text, actor, members, *, surface) -> {title, for_member_id?, profile: {age_band, minutes, sessions_per_week, assumes}, starting_point?, preferred_days?, target_date?, based_on?, exclude_books?, notes}`. One model call on the free chain (`call_pool_json`, `paid_ok=False`), strict JSON, every field optional; a missing field takes the form's default (band from the named member's age or `any`, 20 minutes, 3 a week). `surface` is `chat` or `library` and decides P6. `based_on` is a named book, site or method; `notes` is whatever else should shape the plan.
- **Every free-text field is screened** (Codex 42): `title`, `assumes`, `starting_point`, `based_on` and `notes` all pass `screen_aim` / `screen_starting_point` (body targets, loads and doses); a refusal is the form's refusal, naming the field. `starting_point` is private to the run and **never** enters the public context; `assumes` is public and the parse may not copy the starting point into it (the parser's prompt says so, and the server rejects a parse whose `assumes` equals or contains the `starting_point`).
- **One public context builder** (Codex 43): `programs_curate.public_context(profile, notes, based_on)` replaces the two context paths (`_context_block` and the library branch's `age_band` path, `programs_curate.py:687-705`); `curate()` takes it for both the form and the brief. `based_on` is added to the research question ("…following {based_on} if it exists") so a named method is searched for, not just mentioned; `exclude_books` is the existing flag.
- The brief's fields persist on the planning mission's program stage so the waiting choice's Make new (library spec §3) curates from the brief, not from the title alone (`agent_tools_v2.py:2695` gains the brief in the choice payload).

**Where it lives.**

- **Library page › New program** is a brief box ("Describe the program: who it's for, what they can already do, how long and how often, anything you want it based on") with Find a plan; today's profile fields stay under "Fill it in by hand".
- **Argyle DM.** `start_project` routes as today; the program stage's `propose_program` receives the brief. The library search and waiting choice run first as today. A chat-made program posts a **course card** (§7).

**Output.** The curated program is published to the library at once (`library.create`); its scripts are queued by the per-program job. A curation that returns `origin: none` (research could not run) publishes a row with no lessons and the reason, as today (`programs_curate.py:725`, `library.py:72`): the course page says "Practice time only · {reason}" with **Look again** (Codex 17), and a run started on it reserves time with neutral windows until a plan exists.

## 2. Steer

`POST /api/library/{id}/steer` with `{text, revision}` (adult or parent; creator or parent for an in-use program, same as edit; refused on an archived program).

**One candidate, validated, committed once** (Codex 33, 34, 35):

1. The server loads the row and refuses if `row.revision != revision` (a new `revision` counter on library rows, bumped by every write; Codex 38) with 409 "The program changed; read it again."
2. One model call on the free chain returns an **edit plan** over these operations only: `update_profile {fields}`, `update_phase {phase_id, fields: name | milestone | what | progression}`, `add_lesson {phase_id, after: lesson_id | null, fields}`, `update_lesson {lesson_id, fields}`, `remove_lesson {lesson_id}`, `order_lessons {ids}`; plus `said` (one sentence). Lesson `fields` may carry `title, sessions, steps, body, url, variants, summary`.
3. The server applies the plan to a **copy** of the row, in order, through the same change functions the hand endpoints use (refactored so `add_lesson` honours `after`, `update_phase` exists, `summary` and `origin` are carried; §6), then validates the whole candidate once with `valid_curriculum` (so removing a phase's last lesson and adding its replacement in one steer is fine) and runs the **content screens** on every model-authored text: `_clean_steps` / `_clean_line` (loads, doses, foreign text) and `screen_starting_point` on `assumes`. Any refusal aborts the whole steer with the reason; nothing is written.
4. **Provenance** (Codex 36): every lesson the plan touches in `steps`, `body`, `url` or `variants` gets `origin: 'generated'` unless the plan cites a page the row's `source.facts` already holds (then the citation is kept by index); an unchanged lesson keeps its origin. The row's source line reads "Based on *X* · cited · 2 lessons changed by the app" when any lesson is generated inside a cited program; script generation reads the lesson's origin, not the program's, for whether to fetch a cited URL (`library_scripts.py:57`).
5. Commit: `library._commit(library_id, candidate, actor)` writes the row, bumps `revision`, reconciles every referencing run once (`reconcile_progress`), and invalidates. The response carries the change list and the refreshed row.
6. **Change list** is computed from before/after by the server: profile changes, phase renames and milestone changes, lessons added (with placement), removed, reworded, resized, reordered; and for each removed or resized lesson a runner line **through the visible-runner projection** (`library.runners`, "Kate is on Scales; she moves on to Chords", "and 1 more affected"; Codex 39).
7. **Scripts** (Codex 37, 38): a touched lesson's *generated* scripts are deleted and re-queued through the per-program job; a touched lesson's **hand-edited** script is kept and marked `stale: true` (the course page shows "edited by hand · may be out of date" with the existing Regenerate confirm that names the hand edit). The writing job's claim carries the row `revision` at queue time; a claim whose revision no longer matches is dropped and the lesson re-queued from the fresh row; `write()` reloads each lesson from the current row before generating.

"Make a variant" (⋯, or those words to Argyle) is today's re-curate: a new library program from the same profile plus the steer text; the original and its runners untouched.

## 3. The course page

`library_page.html`'s program view:

1. Header: title, made-for line, source line ("Based on *Piano Adventures Primer* · cited · 9 lessons · about 6 weeks", "Made by the app · 9 lessons · about 6 weeks", or "Practice time only · {reason}"), a **Why this one** fold holding today's rationale and runners-up (`programs_page.html:195`; Codex 18), runners as today, ⋯.
2. Phases in order, each "N · Name · done when {milestone}" with the phase's progression line ("Next time: one less reminder") beneath when set (Codex 18); each lesson one row: title, **summary** sentence, Preview. `summary` is a new lesson field written by the curator; migration fills it from the first step and the session count; a steer may rewrite it. Variant labels appear inside the sentence.
3. **Preview per variant** (Codex 40): a lesson with one script has one Preview; with several variants the button opens a chooser (Session A / Session B). Preview plays the library script filled for the viewer (`fill=1`). When the viewer may see a run of this program, the chooser also offers "as Kate" and plays that run's script through the run script route; the runners payload gains `run_id` for visible runners only.
4. Chips only while a script is writing or has failed, plus the **short-script note** ("about 8 min, shorter than asked") when the stored script fell short (Codex 41; `library_scripts.py:95`).
5. Under the page, the Steer box (adult or parent) with the last change list above it. ⋯ holds: Steer in words, Edit by hand (today's editor until Done editing; on the phone without the script editor), Write lessons (admin), Make a variant, Archive, Delete, Start it for… (§4).

## 4. One-pass setup

`components/program_setup_sheet.html`, one builder, opened from a project's + Add › Program, the library's Start it for…, and the DM course card's "Set it up for Kate". Three parts and one button:

1. **Who**: member select (a child sees only themselves), band beside it.
2. **Which program**: today's picker rows; "+ Make a new one" expands the brief box inline (never for a child); "Where they're starting from" beneath, labelled private.
3. **Days and times**: `POST /api/programs/preview-slots` with `{member_id, library_id, minutes, sessions_per_week, preferred_days}` (signed-in; the member must be the actor, their child, or any member for a parent or adult) returns `propose_slots` for that member and shape (Codex 28); rows of day select and time; **one duration per run** (the run's `minutes`, shown once above the rows, editable there); "+ Add a time"; "Aim for a date (optional)". Emptying the list means the app picks again at Start. A failed preview shows "Couldn't look at the week" with Retry (Codex §8 finding 3).
4. **Start the program**: `POST /api/programs` with `{library_id, for_member_id, slots, minutes, target_date, project_id, starting_point, activate: true}`.

**Activation contract** (Codex 46, 24): for a parent or adult actor the route creates the run and calls `programs.approve` inside one transaction with the actor as approver. `approve`'s own bracket reverts its emissions on failure and returns `status: error`; the route treats any error except "no time" as an abort of the whole creation (the run and, for Make new, the new library row are not kept), returning the message. "There is no time to claim" keeps the run **proposed** and answers "Made it, but found no free time this week; pick times to start it", opening the proposed-state editor. The script job starts only after commit. A child actor never passes `activate`; their pick lands proposed and the existing approval flow applies.

The project's Add a piece › "A practice program" branch is replaced by this sheet; the thread and mission branches are untouched.

## 5. The monitoring sheet

### 5.1 Layout

`programs_page.html` in sheet mode (admin record sheet):

1. Header: title, "Kate · Mon Wed Fri · 20 min · in the library ›", ⋯. "Made by the app" or "Practice time only" as one muted line when it applies.
2. Stats row from a new `programs.monitor(run)` (Codex 29): `last_practised` (date of the latest session by `ts`), `sessions_this_week` (sessions whose `slot_date`, else `ts` date, falls in the current week), `next_window` (the next practice window with its projected lesson and variant), `sessions_total`, `minutes_total`. Drawn as "last practised Thu · 2 sessions this week · next Fri 4:30 · 6 sessions, 2 h".
3. Phases as sections "Name · done when …" with **Reached it** on every unjudged phase (P2); each a ladder from `monitor.ladder`: per lesson `done_sessions`, `sessions`, `completed`, and for the current lesson `next_variant` taken from the next dated window's `lesson_for` projection and `logged_variants` from the sessions actually logged against it (Codex 20); drawn as "Scales · Session A ✓ · B next". The run's `starting_point` shows under the first phase as "Started from: …" for its keeper and parents.
4. The current rung carries "Another session on this" / "Move on" (the bookmark's Back / Next; Codex 21). Tapping any rung opens that lesson (steps, Preview, link); no bookmark control there.
5. "Session log · N · Show": rows from `monitor.log` (`when` = `slot_date` if set else `ts` date, with "logged {ts date}" when they differ, minutes, lesson title, variant, source), each with **Remove this session** (new `programs.remove_session(run_id, session_id)`: deletes the entry and recomputes `progress` from the remaining sessions; sessions gain a stable `id` by migration). This is the undo for a ticked program row (sibling spec R3).
6. Legacy runs (no `library_id`) keep today's run-side script editor branch until its scheduled removal (Codex 32; lesson-depth spec).
7. ⋯: Change the days (§5.3), Program settings (P4), Log a session, Start a session (P7, with the window chooser), Look again, Plan without the book, Pause / Resume, Done with it, Drop, Delete.

The proposed state keeps today's approval block, its "Not these times?" editor and Approve; copy and `canApprove` fixed per P5.

### 5.2 Not shown

The phone session sheet and Today card, the wall tile and the house books are unchanged.

### 5.3 Change the days

New `programs.replace_schedule(run_id, slots, actor)`, one operation (Codex 22, 23, 25, 26, 27):

- **Active run, adult or parent actor:** in one transaction under `db_lock`: snapshot the current emissions; release the run's commitments (`release_commitments`); claim the new ones with `_emit_commitments` (the same writer `approve` uses); write `shape.slots`, `shape.sessions_per_week = len(slots)`, `shape.preferred_days = [s.day for s in slots]`, and `baseline.schedule_changed_on = today`. Any failure on release or claim restores the snapshot (the commitments made by this attempt deleted, the released ones re-emitted from the snapshot; a re-emit failure is reported with the ids, as `release_commitments` reports today) and returns the error; unrelated emissions (kit thread, target event) are untouched. On success the solver refresh runs after commit. Empty `slots` = `propose_slots` for the member and shape, then the same claim.
- **Paused run:** writes `paused_slots` only (what Resume will claim) and the shape fields; nothing is claimed until Resume.
- **Child keeper (own run):** no claim: the run goes to proposed with the child's slots on `shape.slots` (today's `reshape` effect plus their wish), and a parent or adult approves from the proposed block. The route answers "Saved your times; a parent or adult puts them on the calendar."
- **Drift** (Codex 26): `weekday_shortfall` and `maybe_rebaseline` evaluate `preferred_days` only from `baseline.schedule_changed_on` forward; sessions before that date count against the days that were in force then (the previous slots are kept in `baseline.schedule_history` for the window the drift watcher reads).
- **The watcher's offer** (Codex 27): `watchers.py:642` emits action `change_program_days` whose execution (`chat_actions`) opens nothing and executes nothing server-side; the DM card's button deep-links to the run sheet at ⋯ › Change the days. Stored `reshape_program` offers are mapped to the same no-op on execution (an old tap never releases time); `programs.reshape` stays for the child path above and is otherwise unreferenced.

## 6. Data and API changes

- `library_programs`: `revision` (int, migration 0); `lessons[].summary`; `lessons[].origin` (migration: the program's origin); `scripts` rows gain `stale`.
- `library` write path refactor: `_commit(library_id, candidate, actor)` as the one writer; the hand endpoints build a candidate and call it (behaviour unchanged for them); `add_lesson` honours `after`; `update_phase` added; the field whitelists carry `summary` and `origin`; `_write` refuses an archived row for every edit (Codex 33; today only the job does).
- `programs`: `sessions[].id` (migration), `remove_session`, `replace_schedule`, `monitor`, `baseline.schedule_changed_on` and `schedule_history`.
- Routes: `POST /api/library/{id}/steer`; `POST /api/programs/preview-slots`; `PATCH /api/programs/{id}/schedule` (replace_schedule); `DELETE /api/programs/{id}/sessions/{session_id}`; `GET /api/programs/{id}/monitor`; `POST /api/programs` gains `activate`; `/api/programs/{id}/reshape` route removed, its action retired as §5.3.
- Removed: the unreachable propose form (`programs_page.html` 19–107); the Re-shape button [confirm].
- No change to access cells, deletion, stable ids, the waiting choice's transaction or voice policy.

## 7. The DM course card

After a chat-made program (through the waiting choice's Make new or a no-match curation) the DM posts a course card: title, source line, phases with lesson counts, Preview (opens the library page at the program), Steer (a reply beginning with the card's program; the card's id disambiguates when several programs are in the conversation), and **Set it up for Kate** which opens the setup sheet bound to the **run the waiting choice already created** (`run_id` carried on the card; Codex 45): the sheet configures that run's slots and approves it; it never posts a second `POST /api/programs`. A library-only card (nobody named, P6) carries Start it for… instead. Voice keeps its deferred notice and approval policy (library spec §3).

## 8. Vocabulary

| today | now |
|---|---|
| run (in copy) | program ("the program in the library" for the row) |
| Approve — claim this time | Start the program (own pick); Approve (child's or Argyle's proposal): "Puts these times on Kate's calendar" |
| Approving will claim / footprint | What it adds to the week |
| Re-shape the week | Change the days |
| Finished | Done with it |
| ready to judge: … | every lesson done — reached it? |
| rotation / variant | "Session A / Session B" inside the lesson's sentence |
| Its library program is missing | Needs a program (Pick a program stays) |
| Published plan | Based on {name} · cited |
| hand_written / none tier | Practice time only · {reason} |

## 9. Defects to verify and fix in this slice

- `programs_page.html:602` copy vs `canApprove()` (line ~830): both become adult-or-parent (P5).
- Regenerate's confirm (around line 1725) says "Clear it" and deletes the stored script before writing: the course page uses `library_page.html`'s Regenerate confirm, naming a hand edit.
- A failed footprint or preview fetch shows the failure with Retry (around line 992; §4.3).

## 10. Tests

- `tests/test_program_brief.py`: parse fixtures (child named, nobody named on each surface, book named, body goal in notes refused, starting point copied into assumes refused, defaults), `public_context` reaching the curator prompt and the research question, the brief persisted through the waiting choice, no paid key.
- `tests/test_library_steer.py`: revision mismatch 409; the candidate applied and validated once (remove-then-add in one steer); content screens refuse a load prescription; provenance per lesson and the source line; change list computed server-side with the visible-runner projection; generated scripts re-queued, hand-edited kept and marked stale; claim dropped on revision change; in-use program edited in place; Make a variant leaves the original; archived refused.
- `tests/test_program_setup.py`: preview-slots authorization; one-pass create lands active for a parent and an adult with commitments claimed exactly as `approve` claims them; proposed for a child; "no time" keeps a proposed run with the message; an emission failure aborts creation and leaves no run or library row; the script job runs after commit.
- `tests/test_program_schedule.py`: `replace_schedule` active (release + claim atomic, snapshot restored on failure, unrelated emissions untouched), paused, child → proposed; drift reads `schedule_changed_on`; the watcher's new action executes nothing; an old `reshape_program` offer executes nothing.
- `tests/test_program_monitor.py`: stats, ladder (`next_variant` from the next window, `logged_variants` from sessions), log rows with `slot_date` vs `ts`, `remove_session` recomputing progress, Reached it on a non-current phase.
- `tests/test_library_live.py`, `test_library_scripts_live.py`: the course page at rest (one Preview per lesson, chooser for variants, no editor controls), Edit by hand on admin and phone, Steer posts and renders the change list, Why this one fold, Practice-time-only row; screenshots.
- `tests/test_library_flows.py`, `test_programs_endpoints.py`, `test_library_argyle.py`: the DM card bound to the existing run, no duplicate run; the waiting choice unchanged; voice unchanged.
- `tests/test_programs_reachable.py`: every verb of today's run sheet, library page and approval block reachable from the new sheet, course page, setup sheet or their ⋯ (the never-drop guard), incl. Look again, Plan without the book, Program settings, Reached it on every phase, Edit by hand on the phone.

## 11. Not in this spec

- The wall tile, the phone Today card and session sheet, the player.
- A real time picker for slots.
- Steering a program from voice.

## 12. Build split

Claude: tests first (§10), `program_brief`, `public_context`, the course page and the setup sheet templates, the monitoring sheet template, `programs.monitor`, the capabilities doc. Codex: the steer endpoint (candidate, screens, provenance, change list, revision), the `library._commit` refactor and migrations, `replace_schedule` and the watcher action, the activation contract on `POST /api/programs`, `remove_session`, the three defect fixes, the DM card binding. Claude reviews every Codex task; Codex reviews the whole branch at the end.

## 13. Codex review of rev 1, folded

14 → P3. 15, 16 → P4. 17 → §1 output, §3.1, §8. 18 → §3.1–2. 19 → P2. 20 → §5.1.3. 21 → §5.1.4. 22, 23, 25, 26, 27 → §5.3. 24 → P5. 28 → §4.3. 29 → `programs.monitor`. 30 → P1. 31 → P7. 32 → §5.1.6. 33, 34, 35 → §2 steps 2–3, §6. 36 → §2 step 4. 37, 38 → §2 step 7. 39 → §2 step 6. 40 → §3.3. 41 → §3.4. 42, 43 → §1. 44 → P6. 45 → §7. 46 → §4 activation contract.

# Programs: a brief, a course page, one-pass setup, a monitoring sheet — design

**Date:** 2026-10-20. **Status:** rev 1, for the Codex adversarial review, then the user's review. **Builds on:** `2026-10-19-program-library-design.md` (library rows, runs, stable lesson ids, progress rules, the Argyle waiting choice), `2026-10-20-lesson-depth-design.md` (scripts, the per-program writing job, the player), `2026-08-28-programs-design.md` and the v2.435/v2.436 repairs (curate over generate, three source tiers, footprints and slots). **Sibling:** `2026-10-20-projects-one-list-design.md`. **Locked rules kept:** a person judges a milestone; no completion fraction on a program ("3 of 12"); curate over generate with the tier said on the face; the unattended writing job never reaches the paid key; a child never creates a library row.

## Problem

The user, 2026-10-20: "I barely understand how to get through it and end up with a working result and I helped design it." On the surfaces: "The main problem for setting up programs is lessons and how obscure they feel. It isn't really clear how you can affect the generated program and lessons to begin with, and ideally you wouldn't need to. And after they are written, there are a long list of steps, but I don't know what those are or how they will look. I don't think I could manually set up a program if I wanted to."

The audit found programs living in three places with three vocabularies: the library page (28 button labels; every lesson row shows ▲ ▼ Edit Remove and, per script, a state chip, Play, Edit, Regenerate at rest), the run sheet inside a project (58 distinct labels across states; the person meets run, claim this time, footprint, Re-shape the week, ready to judge, rotation, variant, Session A/B, script, Write lessons, Regenerate, Made by the app, Published plan, unresolved), and the phone Today card (a separate renderer). A parent who picks a library program for their own project still lands on a *proposed* run that they must open and "Approve — claim this time". The programs page's own propose form (`programs_page.html` lines 19–107) is unreachable on every host.

The user's ruling on the split of surfaces: the admin sheet is for setting up and for monitoring; practising happens on the wall and the phone and those are fine. The user's direction for creation: "explain the program you want in plain language and have the agent pull the bits it needs out of that to create and generate the project. If you don't like something about it, you can steer it with more plain language."

## Decisions (the user's, 2026-10-20)

1. **Words in, program out.** A library program is made from a plain-language brief, in the Argyle DM or in a brief box on the Library page; both end at the same course preview with a Steer box and Looks good. The hand editor stays as the power-user path behind ⋯ › Edit by hand.
2. **Steer uses the hand tools.** A steer is Argyle calling the existing library endpoints (add / update / remove / reorder lesson, update profile). Every rule those endpoints enforce holds for free.
3. **Steer shows its work.** Every steer answers with a change list naming what moved and any runner it touched. Nothing changes silently.
4. **Steering an in-use program changes it in place**, as a hand edit does (a removed lesson moves its runner on; the change list names them). A new version is made only when the person says "make a variant".
5. **The library program page is a course page**: header with source and length, phases numbered with their done-when, each lesson one parent-facing sentence plus Preview. Chosen over showing the steps as bullets under each lesson.
6. **Preview is the lesson as the person gets it**: the existing player in preview mode, filled for the chosen runner or for the viewer. Script state chips appear only while a script is writing or has failed.
7. **One-pass setup, lands active.** Adding a program to a project is one sheet: who, which program (library rows, Make a new one inline), days and times (the app's proposal shown, editable), Start the program. No proposed state for a parent's own pick; the parent can change the times afterwards from the program's ⋯ › Change the days, which edits the slots of an active run in one write.
8. **The admin program sheet is monitoring**: four stats on top (last practised, this week, next window, sessions and time), the ladder of lessons with the current rung lit and Reached it on the current phase, the session log folded, everything else in ⋯. Start a session stays, demoted to ⋯ › "Start a session (test)".
9. **Vocabulary pass** (§7).

## 1. The brief

**Input.** One free-text paragraph. The curator already asks for everything a brief carries, through separate fields: title, age band, minutes, sessions per week, assumes, starting point, exclude books, preferred days, target date. A new `services/program_brief.py`:

- `parse(text, actor, members) -> {title, for_member_id?, profile: {age_band, minutes, sessions_per_week, assumes}, starting_point?, preferred_days?, target_date?, based_on?, exclude_books?, notes: [...]}`. One model call on the free chain (`call_pool_json`, `paid_ok=False`), strict JSON, every field optional; a missing field takes the same default the form takes today (band from the named member's age or `any`, 20 minutes, 3 a week). `based_on` is a named book, site or method the person asked for; `notes` is whatever else the person said that the curator should honour, passed into `curate()` as a new `brief` argument that lands in the prompt's context block (`_context_block`) verbatim. The parse screens the title and the starting point through `screen_aim` / `screen_starting_point` exactly as the form does; a refusal is the form's refusal.
- A brief naming a child is a program for that child; a brief naming nobody makes a library program and no run.

**Where it lives.**

- **Library page › New program** becomes a brief box ("Describe the program: who it's for, what they can already do, how long and how often, anything you want it based on") with one button, Find a plan. The profile fields of today's form stay beneath a "Fill it in by hand" fold (the hand path).
- **Argyle DM.** `start_project` (the one chat door) already routes "I want Kate to learn piano" to a project with a program stage; the stage's `propose_program` gains the brief: the planner passes the person's words, and the library search / waiting choice (library spec §3) runs first as today. A chat-made program posts the course preview as a card (title, source line, phases with lesson counts, "Preview" opening the library page at that program, Steer as a reply) in the DM.

**Output.** The curated program is published to the library at once (today's `library.create`), its scripts queued by the per-program job as today. The preview shows lessons immediately; scripts write in the background with the existing "Writing lessons · n of m" line.

## 2. Steer

`POST /api/library/{id}/steer` with `{text}` (adult or parent; creator or parent for an in-use program, same as edit). Implementation: one model call on the free chain with the program's current course (phases, lessons with sentences, steps, variants, profile) and the person's words, returning a **plan of edits** in the vocabulary of the existing endpoints:

```
{"edits": [
  {"op": "update_lesson", "lesson_id": "…", "fields": {"sessions": 2}},
  {"op": "add_lesson", "phase_id": "…", "after": "…", "fields": {"title": "Duet with a parent", "sessions": 1, "steps": […], "summary": "…"}},
  {"op": "update_phase", "phase_id": "…", "fields": {"milestone": "…"}},
  {"op": "remove_lesson", "lesson_id": "…"},
  {"op": "order_lessons", "ids": […]},
  {"op": "update_profile", "fields": {…}}
], "said": "one sentence for the person"}
```

The server applies the edits in order through `library.update_lesson` / `add_lesson` / `remove_lesson` / `order_lessons` / `update`, inside one `_write` lock, refusing the whole steer if any edit is refused (archived program, child actor, unknown id). The response is the applied edits rendered as a change list ("Scales: 3 sessions → 2", "+ Duet with a parent after Chords in C", "Songs now done when …", "Sam is on Scales; he moves on to Chords") plus the refreshed program. The change list is computed by the server from before/after, never taken from the model. A steer that touches a lesson with a stored script marks that script stale and the per-program job rewrites it (lesson-depth spec §8's claim doors apply); the chip shows writing.

Steer never changes `source`: a cited program stays cited and its lessons keep their citations; a steer that adds lessons the pages did not cover makes the added lessons carry `origin: generated` individually and the course page says "2 lessons added by the app" under the source line. (Codex: verify this against `_phases_from` and the tier chip.)

"Make a variant" (words to that effect, or ⋯ › Make a variant) is today's re-curate path: a new library program from the same profile plus the steer text, the original untouched; runners stay on the original.

## 3. The course page

`library_page.html`'s program view is redrawn as:

1. Header: title, made-for line, source line ("Based on *Piano Adventures Primer* · cited · 9 lessons · about 6 weeks", or "Made by the app · 9 lessons · about 6 weeks"), runners as today, ⋯.
2. Phases in order, each "N · Name · done when {milestone}", each lesson one row: title, **summary** sentence, Preview button. `summary` is a new lesson field written by the curator ("Find middle C, sit tall, number the fingers. 1 session.") for the parent; migration writes it for existing lessons from the first step and the session count, and the per-program job may rewrite it when it writes the script. The variant labels appear inside the sentence ("2 sessions: A right hand, B left hand"), not as chips.
3. A state chip on a lesson only when its script is writing or failed; the failed chip opens the same Regenerate confirm as today.
4. Under the page, the Steer box (adult or parent) with its last change list above it, and "Fill it in by hand" nowhere: hand editing is ⋯ › Edit by hand, which turns the page into today's editor (▲ ▼ Edit Remove, Add lesson, the script editor, drag) until ⋯ › Done editing.
5. ⋯ holds: Steer in words (focuses the box), Edit by hand, Write lessons, Make a variant, Archive, Delete, Start it for… (opens §4's setup sheet with the program chosen).

Preview calls today's `playScript` with `fill=1`; when the viewer is a parent and the program has a visible runner, Preview asks "As whom?" only when there is more than one visible runner.

The phone's library home draws the same course page without Steer, Edit by hand or Write lessons (today's phone rule); Preview stays.

## 4. One-pass setup

`components/program_setup_sheet.html`, one builder, opened from a project's + Add › Program, from the library's Start it for…, and from the Argyle card's "Use it for Kate now". Three numbered parts and one button:

1. **Who**: a member select (parents and adults see everyone; a child sees only themselves), with the member's band beside it.
2. **Which program**: today's picker rows (title, made-for, visible runners, archived hidden), one selected; "+ Make a new one" expands to the brief box of §1 inline (a child never sees it); "Where they're starting from" beneath, labelled private to the run.
3. **Days and times**: on choosing who and which, the sheet calls `programs.propose_slots` for that member and shape and lists the proposed windows as rows (day select, time, minutes, remove), "+ Add a time", and "Aim for a date (optional)". Emptying the list means the app picks again at Start.
4. **Start the program**: `POST /api/programs` with `{library_id, for_member_id, slots, target_date, project_id, starting_point}`. For a parent or adult actor the run is created **active** in one transaction with its approval (`programs.approve` with the given slots, `approved_by` = the actor), so commitments are claimed exactly as approval claims them today. For a child actor, or when `slots` is empty and the app's proposal fails, the run is created `proposed` and the existing approval flow applies (a parent still sees "Approving will claim"). A footnote says "Puts these times on Kate's calendar as practice."

The project's Add a piece › "A practice program" form (`project_piece_forms.html`, program branch) is replaced by this sheet. The thread and mission branches are untouched.

## 5. The monitoring sheet

`programs_page.html` in sheet mode (the project record sheet, admin) is redrawn:

1. Header: title, "Kate · Mon Wed Fri · 20 min · in the library ›" (the library link), ⋯.
2. Stats row: last practised (weekday or date), this week "2 of 3" (sessions logged this week over `sessions_per_week`; this is the run's week shape, not a curriculum fraction, and `programs.progress` already computes both), next window, total sessions and time. The "Made by the app" note is one muted line under the title when it applies.
3. Phases as sections "Name · done when …", each a ladder: done lessons struck, the current rung lit with "Session A ✓ · B next" from `progress.lessons`, **Reached it** beside the current phase only. The "ready to judge" state is the lit rung's line reading "every lesson done — reached it?" with the button. Tapping a rung opens that lesson (steps, Preview, link); "Another session on this" and "Move on" (Back / Next of the library spec) live there.
4. Session log folded: "Session log · N · Show", rows as today's log.
5. ⋯: Change the days (the slot editor of today's approval screen, on an active run: `PATCH /api/programs/{id}` with `{slots}` releases and reclaims commitments in one write; emptying the list hands the choice back to the app, which is today's `reshape` outcome without the proposed detour), Log a session, Pause / Resume, Done with it (today's Finished), Drop, Delete, Start a session (test).

The **proposed** state (child's pick, Argyle's proposal, failed proposal) keeps today's approval block, its "Not these times?" editor and Approve, with the copy fixed per §8; the "Re-shape the week" button is removed everywhere since Change the days covers it (a drift finding's offer calls the same slot editor) [confirm: this removes the Re-shape verb as a hand path; its effect is reachable through Change the days › empty the list].

The phone session sheet and Today card, the wall tile and the house books are unchanged.

## 6. Removals and migrations

- The unreachable propose form in `programs_page.html` (lines 19–107) is deleted.
- `lessons[].summary` added; migration fills it as §3.
- `reshape` route and button removed [confirm]; `programs.reshape` stays for the drift watcher until that watcher is pointed at Change the days (its DM offer becomes "Change the days?" opening the sheet).
- No change to the run's data model, progress rules, scripts' keys, access cells or deletion.

## 7. Vocabulary

| today | now |
|---|---|
| run (in copy) | program (the library row is "the program in the library") |
| Approve — claim this time | Start the program (parent's own pick); Approve (child's or Argyle's proposal): "Puts these times on Kate's calendar" |
| Approving will claim / footprint | What it adds to the week |
| Re-shape the week | Change the days |
| Finished | Done with it |
| ready to judge: … | every lesson done — reached it? |
| Another session on this / Move on | kept, inside the lesson row |
| rotation / variant / Session A | "Session A / Session B" inside the lesson's sentence only |
| Write lessons / Regenerate / Reset | kept, behind ⋯ and the failed chip |
| Its library program is missing | Needs a program (Pick a program stays) |
| Made by the app | kept, one line |
| Published plan | Based on {name} · cited |

## 8. Defects to verify and fix in this slice

Reported by the inventory pass; each must be confirmed against the code before the fix lands:

- `programs_page.html:602` says an adult may approve; `canApprove()` (line ~830) is parent-only. Make the copy match the gate (the gate is the library spec's).
- Regenerate's confirm (around line 1725) says "Clear it" and deletes the stored script before writing; the course page's failed chip must use the Regenerate confirm of `library_page.html` (write a fresh one, hand edit named).
- A failed footprint fetch leaves "Working it out…" with no retry (around line 992); the setup sheet's days-and-times part shows the failure and a Retry.

## 9. Tests

- `tests/test_program_brief.py`: parse fixtures (child named, nobody named, book named, body goal refused, defaults), `brief` reaching the curator prompt, no paid key.
- `tests/test_library_steer.py`: the edit plan applied through the hand endpoints; refusal rolls back the whole steer; change list computed server-side and naming runners; script marked stale and rewritten by the job; in-use program edited in place; Make a variant leaves the original.
- `tests/test_program_setup.py`: one-pass create lands active for a parent with commitments claimed exactly as `approve` claims them, proposed for a child, proposed when slots are empty and the proposal fails; Change the days on an active run releases and reclaims; `reshape` route gone.
- `tests/test_library_live.py` and `test_library_scripts_live.py`: the course page at rest shows one Preview per lesson and no editor controls; Edit by hand reveals today's editor; Steer posts and renders the change list; screenshots.
- `tests/test_library_flows.py`, `test_programs_endpoints.py`, `test_library_argyle.py`: the sheet's stats, the ladder, the demoted Start; the DM card; the waiting choice unchanged.
- `tests/test_programs_reachable.py`: every verb of today's run sheet reachable from the new sheet or its ⋯ (the never-drop guard).

## 10. Not in this spec

- The wall tile, the phone Today card and session sheet, the player.
- A real time picker for slots (the day select and time input stay).
- Steering a program from voice.

## 11. Build split

Claude: tests first (§9), `program_brief.parse` and the curator's `brief` argument, the course page and the setup sheet templates, the monitoring sheet template, the capabilities doc. Codex: the steer endpoint and change-list computation, the one-transaction active create and Change the days on an active run, the migration for `summary`, the three defect fixes, the DM card. Claude reviews every Codex task; Codex adversarial-reviews this spec before any code and the whole branch at the end.

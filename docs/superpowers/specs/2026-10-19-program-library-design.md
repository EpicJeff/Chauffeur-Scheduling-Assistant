# Program library

**Status:** rev 1, 2026-10-19, for Codex adversarial review and then the user's review.
**Why:** the user's ruling of 2026-10-16: a program becomes a standalone, person-less library entry with its own page ("learn piano" exists once); a project assigns a run of one to a person and tracks that person's progress, so two children can run the same piano program at once; deleting a project deletes the run, not the program.

## Decisions (user, 2026-10-18/19)

- A library program is an ordered list of lessons. A run references the program and holds which lesson is current, from tracked progress. **Stable lesson ids replace versions:** editing a lesson's content changes no progress; adding, removing and reordering follow the rules in §1. A wholesale rewrite is a new library program.
- Any adult creates a library program and edits their own; parents create and edit any. Children neither.
- Approach 2: today's `programs` row stays the run; the curriculum moves out to a new table; readers reach it through one loader.
- Body goals live on private projects, never on library programs: `screen_aim` keeps refusing a body target as a library title; a private body-goal project runs a behaviour-shaped program from the library.

## 1. Data model

**`library_programs` (new).** One row per program:
- `id`, `title` (the aim, person-less), `created_by`, `created_at`, `updated_at`, `archived: bool` (hidden from pickers; nothing else).
- `made_for: {age_band, minutes, sessions_per_week, starting_point}`: the profile it was curated for, shown on the page, never a person. `age_band` is one of the stage bands (`stages.py`), or empty for an adult.
- `source`: as today (`plan_name`, `url`, `facts`, `origin` cited | generated | none, `reason`, `book_spine`).
- `phases[]`: as today (`name`, `weeks` as the default pacing, `what`, `milestone`, `progression`, `rotation`) with every per-run key removed.
- `lessons[]`: the ordered list, `{id, phase, title, body | url, sessions}`: today's `phases[].units` flattened in phase order, each with an id minted once (`uuid4().hex`) and never changed. Reorder, edit, add and remove keep ids.

**`programs` (existing) is the run.** It keeps `member_id`, `project_id`, `state`, `shape.slots` and `shape.preferred_days`, `baseline`, `emissions`, `sessions`, `paused_at`, `paused_slots`, `finished_at`, `created_by`, `approved_by`, `starting_point` (the person's, distinct from `made_for.starting_point`), and gains:
- `library_id`
- `progress: {completed: [lesson id], current: lesson id | null, phases: {phase name: {weeks, milestone_hit_at}}}`: the per-run pacing (rebaseline writes `weeks` here), milestones and `unit_shift` (folded into `current`).

It no longer stores `title`, `source`, `phases`, `shape.minutes`, `shape.sessions_per_week`. **`programs.load(run)`** returns the run with those fields resolved from its library row (`phases` with the run's `weeks` and `milestone_hit_at` merged back in, `shape` with the library's minutes and sessions per week), so every reader that reads `program['phases']` or `program['title']` keeps working through the loader. `storage.get_program` returns the raw run; services call `programs.load`. A run whose library row is missing reads as **gone** (delete slice rule); a library row cannot be deleted while runs exist, so this only covers corruption.

**Lesson scripts** (`program_lessons`): keyed by run id + lesson id (today: run id, phase, unit, label). Generated per run from the library lesson plus the person; hand edits per run; the wait queue carries the run id.

**Next-lesson rules.** `programs.next_lesson(run)` = the first lesson in library order whose id is not in `progress.completed`; `current` is set to it when a session is logged or a lesson is removed; if `current` names a lesson no longer in the library, it moves to `next_lesson`; reordering never changes `completed`. Completing the last lesson of a phase hits that phase's milestone as today.

## 2. Who may do what

- **See the library:** every active member, children included (titles, made-for, source chip, who is running it with their project); the house (wall, speaker, Mind) sees the same. Library rows are never restricted; nothing secret may live on them (body goals refused at the door; `made_for.starting_point` is a profile, not a person's).
- **Create:** adult or parent. **Edit, reorder lessons, archive:** the creator or any parent; another adult and any child are refused with "Only the person who made this program, or a parent, can change it."
- **Delete:** creator or parent, and only when no run references the program in any state; otherwise refused with "In use by {names}'s project" and the button disabled. One with no runs deletes outright (no closure: a library row owns nothing else).
- **Runs:** unchanged. The run is the piece in its project; who sees it follows the project's audience and the access rule (matrix cells R3, R5p, R15, R17 unchanged); who acts follows `projects.can_act`; deleting a project deletes its runs; Delete on a run card deletes that run; neither touches the library row.
- **Argyle:** `propose_program(title, shape, starting_point, project_id)` becomes "find or make a library program and start a run in this project"; `list_programs` lists library programs with their runners; runs show through `list_projects`/`get_project`; no library delete tool.

## 3. Flows

**Add a piece → Program (hand path).** A picker over the library (title, made-for, runners; archived hidden) with "Make a new one" at the bottom. Picking creates the run in this project (`proposed`), then the usual slots → approve flow. Making a new one is today's create form (aim, minutes, sessions per week, starting point, for = the project's owner by default); it curates a library program (`made_for` from the inputs and the member's age band) and starts the run.

**Argyle.** `start_project` as today; the planner's `propose_program` first searches the library by title words and aim (same dedupe matcher as `start_project`, filler words ignored); a match becomes a card: "There's a piano program in the library, made for ages 7–10 with 20-minute sessions. Use it for Kate, or make a new one?" with Use / Make new / Not now. Use starts the run; Make new curates; no match curates at once and says "I made a new library program: Learn piano." Voice: the same, spoken, with Use/Make new as the two answers.

**The library page.** Admin page `/library` (admin nav, Work group, page bar with the usual gear) and a PWA home under More → Library. One card per program: title, made-for, source chip, "12 lessons", runners by name with their project (buttons to the project), New program for adults, Edit/Archive for creator or parent, Delete when unused. A program's page lists its lessons in order with inline edit (title, body or url, sessions), drag to reorder, Add lesson (mints an id), Remove (when any run is current on it: "Kate is on this lesson; her run moves to the next one."). No browser dialogs; Tailwind rebuilt.

**A run's card** (project page, record sheet, phone): today's look plus "from the library: Learn piano" (a button to the program) and "Lesson 3 of 12 · Scales". Today practice cards, the calendar, pushes, the lesson player: unchanged, reading through the loader.

**Editing a library program with live runs.** Content edits apply to every run at once; already-generated lesson scripts are kept (they were built for that child) until the person taps Regenerate on the run. Reorder, add and remove follow §1. No versions.

**Delete** (delete slice): the library row is never in a closure; a run is deleted like a program today; the project confirm names runs as "Programs: Learn piano (Kate's run)".

## 4. Migration and compatibility

- One migration, `migrate_program_library_v2499`, idempotent (`library_id` set = converted): for each `programs` row, create one `library_programs` row from its curriculum (`made_for` from its shape and the member's age band now; `lessons` flattened from `phases[].units` with fresh ids; per-run keys stripped), set `library_id`, move `milestone_hit_at`, `unit_shift` and the re-paced `weeks` into `progress`, derive `completed` and `current` from the sessions and milestones already logged (every lesson of a phase whose milestone was hit is completed; `current` = `next_lesson`), re-key its lesson scripts by lesson id. One library row per program row (no dedupe by title). Existing programs are test data (user, 2026-10-16).
- `/programs` keeps redirecting to the projects lane; the program sheet keeps working for runs.
- The programs spec's "one program, one person; no sharing across members" is amended: the run is one person; the library is shared.
- Routes: `GET/POST /api/library`, `GET/PATCH/DELETE /api/library/{id}`, `POST /api/library/{id}/archive`, `POST /api/library/{id}/lessons` (add), `PATCH/DELETE /api/library/{id}/lessons/{lesson_id}`, `POST /api/library/{id}/lessons/order`; `/api/programs/*` keep acting on runs; `POST /api/programs` takes `library_id` or the curate inputs. Every new route gets a READERS row (class 4.1 signed-in, kinds `()` since library rows are unrestricted) and an auth rule (`SIGNED_IN`, edit authority in the service).
- Access digest: library rows are not an access input (never restricted); the run's `library_id` is.

## 5. Tests (written first)

- **Model:** library row + run; loader resolves curriculum; missing library row reads gone; stable ids through edit/reorder/add/remove; next-lesson rules; scripts keyed by run + lesson id; `progress.phases.weeks` is what rebaseline writes.
- **Access:** library visible to every member and the house; create adult/parent only; edit by creator or parent, refused for another adult and a child with the exact message; delete refused while any run exists in any state naming the runner; matrix cells R3/R5p/R15/R17 unchanged; a run's card shows the library title only when the run is visible.
- **Flows:** picker → run; make new → library row + run with `made_for`; Argyle match card Use/Make new/no match; project delete leaves the library row; run delete the same; body-goal title refused at the library door; Remove of a current lesson moves the run.
- **Migration:** one library row per program, progress derived, scripts re-keyed, idempotent; matrix and `test_program*.py` neighbours green afterwards.
- **Live:** library page list/new/edit/reorder/archive/delete-disabled/remove-current-lesson copy; the Add-a-piece picker; the run card's library link and lesson position; phone More → Library; light and dark at phone width.

## 6. Split

Claude writes the tests first and builds the UI (library page, picker, run card). Codex builds the model (table, loader, stable ids, progress rules), the service and route changes, the Argyle tool change and the migration. Each side's work is reviewed by the other model; a final whole-branch review closes it.

## 7. Out of scope

- Versions or mappings between rewrites (a rewrite is a new program).
- Measures (weight, diet) on body-goal projects: the measures slice.
- Sharing library programs outside the household.

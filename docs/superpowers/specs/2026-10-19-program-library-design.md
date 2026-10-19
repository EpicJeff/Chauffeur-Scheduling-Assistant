# Program library

**Status:** rev 3, 2026-10-19. Rev 1: 18 Codex findings folded (§9); the user confirmed the five rulings of §8. Rev 2: a second Codex pass, 11 findings folded (§10): an unresolved library is its own state, lessons keep a ladder identity with rotation variants inside, the bookmark moves within the current phase, Back stays, the waiting choice is specified across the stage layers, voice carries its policy. For the user's review, then the plan.
**Why:** the user's ruling of 2026-10-16: a program becomes a standalone, person-less library entry with its own page ("learn piano" exists once); a project assigns a run of one to a person and tracks that person's progress, so two children can run the same piano program at once; deleting a project deletes the run, not the program.

## Decisions (user, 2026-10-18/19)

- A library program is an ordered list of lessons. A run references the program and holds which lesson is current, from tracked progress. **Stable ids replace versions:** editing content changes no progress; adding, removing and reordering follow §1. A wholesale rewrite is a new library program.
- Any adult creates a library program and edits their own; parents create and edit any. Children neither.
- Approach 2: today's `programs` row stays the run; the curriculum moves out to a new table; readers reach it through one loader.
- Body goals live on private projects, never on library programs: `screen_aim` keeps refusing a body target as a library title.
- **Locked rules kept (programs arc):** a person judges a milestone ("Reached it"), never the app; no completion fraction is ever shown (no "3 of 12"); whose turn it is in a rotation is arithmetic over dates.

## 1. Data model

**`library_programs` (new).** One row per program:
- `id`, `title`, `created_by`, `created_at`, `updated_at`, `archived: bool` (hidden from pickers; nothing else).
- `made_for: {age_band, minutes, sessions_per_week, assumes}`: the **public profile** the program was curated for, chosen explicitly at creation (Codex 11): `age_band` is one of the stage bands or `any` (the default when no birthdate is on file; never inferred from a pinned UI stage); `assumes` is a short generic line ("complete beginner", "can read music") the person types or picks, never a copy of anyone's starting point (Codex 1).
- `source`: as today (`plan_name`, `url`, `facts`, `origin` cited | generated | none, `reason`, `book_spine`).
- `phases[]`: `{id, name, weeks (default pacing), what, milestone, steps, progression, rotation}` with a stable phase id (Codex 8) and no per-run key.
- `lessons[]`: the ordered ladder, `{id, phase_id, title, sessions, steps, body | url, variants: [{label, steps, body | url}]}`: today's `phases[].units` in phase order, each with an id minted once (`uuid4().hex`) and never changed. A lesson is one **rung** of the ladder (progress moves rung by rung, as today's `unit_for`); its `variants` are today's rotation sessions (Session A / Session B), and **which variant a given evening gets is still arithmetic over dates**, never progress (Codex r2-2). A phase with steps but no units becomes one lesson carrying the phase's steps; a phase with a rotation but no units becomes one lesson whose variants are the rotation; a time-only phase becomes one content-less lesson, so every program has at least one lesson per phase (Codex 5).

**`programs` (existing) is the run.** It keeps `member_id`, `project_id`, `state`, `shape.slots`, `shape.preferred_days`, `baseline`, `emissions`, `sessions`, `paused_at`, `paused_slots`, `finished_at`, `created_by`, `approved_by`, `starting_point` (the person's own words, private to the run; fed into per-run lesson generation, Codex 12), and gains:
- `library_id`
- `shape.minutes` and `shape.sessions_per_week` stay on the run as the **effective** values: defaults copied from `made_for` at run creation, then owned by the run (slots set `sessions_per_week`, the person may change `minutes`); approval persists the agreed shape on the run rather than re-reading library defaults (Codex 9).
- `progress: {lessons: {lesson id: {done_sessions, completed_at}}, current: lesson id | null, phases: {phase id: {weeks, milestone_hit_at}}}` (Codex 6, 8): per-lesson session counts, the bookmark, the per-run pacing (rebaseline writes `weeks` here) and the person's milestone judgements.

It no longer stores `title`, `source`, `phases`. **`programs.load(run)`** returns the run with those resolved from its library row, `phases` hydrated with `units` rebuilt from `lessons` and the run's `weeks`/`milestone_hit_at` merged in, so every reader that indexes `program['phases']`, `['title']`, `['source']` or `['shape']` keeps working. `storage.get_program` returns the raw run; **every curriculum reader goes through `programs.load`**: the inventory is `programs.py` (`unit_for`, `phase_started_on`, `practice_windows`, `due_asks_for`, `footprint`, `_kit_line`, `maybe_rebaseline`), `program_lessons.py` (`generate_for`, the wait queue), `house_programs.py`, `house_attention.py`, `watchers.py` drift, `subjects.py` adapter, `situations.py`, `projects.py` piece cards and `_wrapper_fields`, `access.py` (`practice_hidden`, `commitment_view` titles), `home_board.py`, `study.py`, `agent_tools_v2.py` list/get, `main.py` routes and `deletion.py` previews; intentional raw readers are `vitals.py` (sessions only) and `deletion.py` cleanup (ids only) (Codex 4). A run whose library row cannot be resolved is **unresolved**, a state of its own, not gone (Codex 17, r2-1; the delete slice's rev 3.1 definition of gone stands): the loader returns the run with an empty curriculum and `unresolved: True`; the run's card shows "Its library program is missing" with Delete and "Pick a program" (rebind) for its keeper and project actors; practice windows and commitments render neutral (time only, no words) until the person resolves it, and still reserve the solver's time as today; Argyle names it only as needing attention; deletion admission and cleanup work on the raw run. The access digest includes each library row's `id` and `updated_at` so a vanished or edited row invalidates warm boards.

**One resolved projection.** `programs.lesson_for(run, date) -> {lesson_id, variant_label, title, steps, body | url, phase_id}` (variant_label empty when the lesson has no variants) is the only way a practice window, a Today card, the lesson player, script generation, lesson help and previews learn what to practise: the bookmark's lesson, with the date choosing the variant. Its `steps` are the lesson's (or the variant's), so editing a library lesson's steps reaches every surface (Codex r2-3).

**Lesson scripts** (`program_lessons`): keyed by `(run id, lesson id, variant_label)` (Codex 3). Generated per run from the resolved projection plus the person (age, autonomy, the run's `starting_point`, minutes); hand edits per run; the wait queue carries the run id. **Stable identity travels end to end** (Codex r2-4): practice windows, the player, script GET/PUT/DELETE, generation, help and completion all carry `lesson_id` and `variant_label`; completion credits the lesson named in the request, never whatever is current at that moment; a request naming a lesson no longer in the library answers 409 "That lesson moved; open it again."; the legacy `(phase_name, unit_n, session_label)` tuple is translated for one release and then removed.

**Progress rules (Codex 6, 7, r2-5, r2-6, r2-7, r2-8).**
- The bookmark (`progress.current`) always points at a lesson of the **current phase**: the first phase in library order whose milestone the person has not judged. It never crosses into a later phase by itself.
- Logging a session adds one to `progress.lessons[current].done_sessions`; when it reaches the lesson's `sessions`, the lesson is completed and the bookmark moves to the next uncompleted lesson of the current phase. When the current phase has no uncompleted lesson left, the bookmark stays on its last lesson, the run reads "ready to judge: *{milestone}*", and further logs count against that lesson (today's behaviour of staying on the last rung).
- **Next** moves the bookmark one lesson forward inside the phase without completing. **Back** ("Another session on this") moves it one lesson back, keeping every `done_sessions` count; today's Stay/`unit_shift` is this pair, and nothing is removed (Codex r2-6).
- A lesson removed from the library while a bookmark sits on it: the bookmark moves to the next lesson of the same phase in the new order, else the previous one, never to an earlier phase (Codex r2-5). Reordering changes no counts; a lesson added into an already judged phase is completed by that judgement (the phase is done).
- **"Reached it" stays the person's call.** On a phase it marks every lesson of that phase completed, stamps `milestone_hit_at`, and moves the bookmark to the first uncompleted lesson of the next unjudged phase; the run finishes and releases its commitments **only when every phase is judged** (today's condition kept; judging the last phase first does not finish the run, Codex r2-8), all in one storage transaction with release failures surfacing as today.

## 2. Who may do what

- **See the library:** every active member and the house. Library rows hold nothing private: **[confirm]** at creation the form shows "Everyone in the household will see this program as: *{title}*" above the title, and the personal starting point is labelled "stays private to {name}'s run" (Codex 1). Migration publishes existing programs' titles and curricula as they are (the user ruled existing programs are test data); their starting points stay on the run.
- **Runners on a library page, picker, card or refusal** are shown only when the viewer can see that run's project; others are counted as "and 1 more"; the in-use refusal names only visible runners and otherwise says "In use by another project" **[confirm]** (Codex 2). These routes carry kinds `('program',)` in READERS and run their runner lists through `record_view`.
- **Create:** adult or parent. **Edit, reorder lessons, archive:** the creator or any parent; others are refused with "Only the person who made this program, or a parent, can change it."
- **Delete:** creator or parent, only when no run references the program in any state.
- **Runs:** today's rules, unchanged: who sees a run follows the access rule (matrix cells R3, R5p, R15, R17 unchanged); **who acts keeps `record_actable` and the existing keeper and approval gates** (a child keeper acts on her own run inside Mom's private project exactly as today; Codex 13); deleting a project deletes its runs; Delete on a run card deletes that run; neither touches the library row.
- **The run's legacy `/edit`** (Codex 10): a retitle is refused ("The name belongs to the library program; rename the project instead."); a shape edit writes the run's effective `minutes`/`sessions_per_week`; Look again / re-curate creates a **new** library program from the same profile and rebinds the run to it after a confirm that says progress starts over and scripts are regenerated.
- **Argyle:** `propose_program` = "find or make a library program and start a run in this project" (§3); `list_programs` lists the library with visible runners; runs show through `list_projects`/`get_project`; no library delete tool.

## 3. Flows

**Add a piece → Program (hand path).** A picker over the library (title, made-for, visible runners; archived hidden) with "Make a new one" at the bottom. Picking creates the run in this project (`proposed`, `shape` defaults from `made_for`), then the usual slots → approve flow. Making a new one is the create form: the public profile (title with the visibility line, age band defaulting from the member's known age or `any`, minutes, sessions per week, assumes) plus the private starting point for this run; it curates a library program from the profile, then starts the run with the starting point on it.

**Argyle (chat).** `start_project` as today; the planner's `propose_program` first searches the library (the `start_project` dedupe matcher) (Codex 14, r2-9). With a match the tool returns `{'status': 'waiting_choice', 'choice_id', 'options': [use, make_new]}`; `chat_actions.run_row` records the row as `waiting_choice` (a durable row state beside done and failed) with the choice id; `run_stage` suspends the rows that depend on it and leaves the stage open; `reconcile` treats a `waiting_choice` row as waiting, never uncertain; `resume` does not re-run it. The choice is a mission ask card with three buttons (the card mechanism plan and stage approvals already use): "There's a piano program in the library, made for ages 7–10 with 20-minute sessions. Use it for Kate, or make a new one?" Use / Make new / Not now. Answering **Use** or **Make new** creates the run and, in the same transaction, binds `run_id` onto the choice and marks the row done with `created: [{kind: 'program', id: run_id}]`; a repeated answer finds the bound run and creates nothing; the stage then continues. **Not now** fails the row with "No program for now" and the stage goes on without it. No match curates at once and says "I made a new library program: Learn piano."

**Voice** (Codex 15, r2-10; ruling confirmed): voice reaches programs only through `start_project`, which persists `interaction: 'voice'` on the planning mission; the program stage reads it and, with exactly one library match, starts the run from it, otherwise curates a new one; the spoken reply at the time is "I'm setting that up" (the stage runs later), and the result arrives as the mission's notice ("I started Kate on the piano program from the library") through the existing notice path with refs and delivery re-checks. Footprint approval stays its own spoken act. No spoken Use/Make new dialog.

**The library page.** Admin page `/library` (admin nav, Work group) and a PWA home under More → Library. One card per program: title, made-for, source chip, lesson count, visible runners with their project (buttons), New program for adults, Edit/Archive for creator or parent, Delete when unused. A program's page lists its lessons in order with inline edit (title, steps, body or url, sessions, rotation label), drag to reorder, Add lesson, Remove (when any visible run is current on it: "Kate is on this lesson; her run moves to the next one."; hidden runs are counted, not named). No browser dialogs; Tailwind rebuilt.

**A run's card** (project page, record sheet, phone): today's look plus "from the library: Learn piano" (a button) and the current lesson by name under its phase ("Scales · Foundations"), never a count (Codex 18). Today practice cards, the calendar, pushes, the lesson player: unchanged through the loader.

**Editing a library program with live runs.** Content edits apply to every run at once; generated scripts are kept until the person taps Regenerate on the run. Reorder, add and remove follow §1.

**Delete** (delete slice): the library row is never in a closure; a run is deleted like a program today; the project confirm names runs as "Programs: Learn piano (Kate's run)".

## 4. Migration and compatibility

- `migrate_program_library_v2499`, per row inside one storage transaction, marking `library_id` **last** so a crash before the mark converts the row again from scratch and a crash after it never reconverts (Codex 16): create one `library_programs` row from the curriculum (`made_for.age_band` from the member's birthdate if on file else `any`, `assumes` empty, minutes and sessions per week from the shape; phases get ids; `lessons` flattened with fresh ids, one per unit per rotation label), copy `minutes`/`sessions_per_week` onto the run as effective values, move `milestone_hit_at` and re-paced `weeks` into `progress.phases`, set `progress` from today's selection: `current` = the lesson `unit_for` selects after `unit_shift`, every earlier lesson of unjudged phases completed, `done_sessions` of `current` = the residual count (cumulative logs minus the requirements of the lessons before it, clamped to 0..sessions-1 so the next log behaves as it would today), phases whose milestone was hit fully completed (Codex r2-7), re-key scripts by lesson id (rotation labels map to their own lesson ids). Run ids, emissions, the kit thread's ownership and commitments are untouched; conversion never calls approve. One library row per program row.
- `/programs` keeps redirecting to the projects lane; the program sheet keeps working for runs.
- The programs spec is amended: the run is one person; the library is shared; milestones and no-fraction rules stand.
- Routes: `GET/POST /api/library`, `GET/PATCH/DELETE /api/library/{id}`, `POST /api/library/{id}/archive`, `POST /api/library/{id}/lessons`, `PATCH/DELETE /api/library/{id}/lessons/{lesson_id}`, `POST /api/library/{id}/lessons/order`; `POST /api/programs` takes `library_id` or the profile + starting point; `/api/programs/{id}/edit` per §2. READERS rows for every new route (kinds `('program',)` where runners are returned) and `SIGNED_IN` auth rules; `test_access_register`'s discovery is extended to `/api/library*` routes and the library getters, and the matrix gains probes that distinguish public curriculum from restricted runner and project fields (Codex r2-11).

## 5. Tests (written first)

- **Model:** library row + run; the loader hydrates `phases[].units`, title, source, shape; `lesson_for` resolves bookmark + date into one projection whose steps follow a library edit; an unresolved library is its own state (card copy, neutral windows, commitments kept, deletable, rebindable) and invalidates a warm board; stable lesson and phase ids through edit/reorder/add/remove; progress rules: partial sessions, Next and Back, the bookmark never leaving the current phase, the exhausted phase, a removed current lesson, a lesson added into a judged phase; "Reached it" on a non-final phase first (no finish), all phases judged (finish + release in one transaction); completion credits the named lesson; a moved lesson answers 409; scripts keyed by run + lesson id with rotation labels distinct; rebaseline writes `progress.phases.weeks` only.
- **Access:** library visible to every member and the house; create adult/parent; edit creator or parent with the exact refusal; delete refused while any run exists; runner lists hide runs whose project the viewer cannot see (Dad never learns of Kate's excluded project through the library); run cells R3/R5p/R15/R17 and the keeper action gates unchanged; a run's starting point never appears on a library surface.
- **Flows:** picker → run with effective shape; make new → library row with the public profile + run with the private starting point; the visibility line on the form; Argyle match → `waiting_choice` row survives a restart and a pause/resume, dependents wait, Use creates one run even on a repeated answer, Make new curates, Not now fails the row and the stage continues; voice persists its policy and a single match auto-uses with the notice delivered later; `/edit` retitle refused, shape writes the run, re-curate makes a new library row and rebinds; project delete leaves the library row; body-goal title refused.
- **Migration:** one library row per program, progress derived from `unit_for` + `unit_shift` + milestones with the residual count checked by logging one more session before and after conversion, scripts re-keyed per variant, crash before and after the mark, idempotent; matrix and `test_program*.py`, `test_house_programs`, `test_lesson_*` green afterwards.
- **Live:** library page list/new/edit/reorder/archive/delete-disabled/remove-current copy; the picker; the run card's library link and lesson name (no count); phone More → Library; light and dark.

## 6. Split

Claude writes the tests first and builds the UI (library page, picker, run card, the create form's visibility line). Codex builds the model (table, loader, ids, progress rules), the service and route changes, the Argyle waiting choice and voice path, and the migration. Each side's work is reviewed by the other model; a final whole-branch review closes it.

## 7. Out of scope

- Versions or mappings between rewrites (a rewrite is a new program).
- Measures (weight, diet) on body-goal projects: the measures slice.
- Sharing library programs outside the household.

## 8. Rulings for the user to confirm

1. **Publication:** the create form states what the household will see; the personal starting point never reaches the library; migration publishes existing (test) programs' titles and curricula.
2. **Hidden runners:** a library surface names a runner only when the viewer can see that run's project; otherwise "and 1 more" / "In use by another project".
3. **Voice:** a single library match is used automatically and announced; no spoken Use/Make new dialog.
4. **Legacy `/edit`:** retitle refused (rename the project), shape writes the run, re-curate makes a new library program and rebinds after a confirm.
5. **Locked rules stand:** milestones are the person's call; no "3 of 12" anywhere.

## 9. Codex review (rev 1 → rev 2)

| Finding | Answer |
|---|---|
| 1 Private inputs become public | §1 `made_for.assumes` + §2 publication line; starting point stays on the run |
| 2 Runner lists disclose private projects | §2 visible runners only; READERS kinds `('program',)` |
| 3 Script key loses rotation variants | §1 one lesson id per rotation label |
| 4 Loader cutover inventory | §1 reader inventory + intentional raw readers |
| 5 Flattening loses steps / phase-only programs | §1 lessons carry steps; one lesson per phase or label; hydration |
| 6 Partial sessions / bookmark | §1 progress rules |
| 7 Milestones | §1 person's call kept; "Reached it" atomic effect |
| 8 Phase names not stable | §1 phase ids |
| 9 Library defaults vs run agreement | §1 effective shape on the run |
| 10 `/edit` destination | §2 |
| 11 `age_band` vs curation input | §1 explicit public profile, `any` when unknown |
| 12 Starting point unused by generation | §1 fed into per-run generation |
| 13 `can_act` replaces keeper actions | §2 keeper gates kept |
| 14 Stage contract | §3 waiting choice |
| 15 Voice path | §3 voice rule |
| 16 Migration idempotence | §4 transactional, mark last |
| 17 Missing library not gone | §1 unresolved outcome + digest |
| 18 "Lesson 3 of 12" | §3 lesson name, no count |

## 10. Codex review (rev 2 → rev 3)

| Finding | Answer |
|---|---|
| 1 Unresolved = gone blocks deletion and hides reservations | §1 unresolved is its own state; rev 3.1 gone stands |
| 2 Flattening variants changes the ladder | §1 lesson = rung, variants inside, date picks the variant |
| 3 Hydrated steps ignored | §1 `lesson_for` projection used everywhere |
| 4 Script identity end to end | §1 lesson_id + variant_label through windows, CRUD, generation, help, completion; 409 on a moved lesson; legacy tuple for one release |
| 5 next_lesson crosses phases / exhausts | §1 bookmark within the current phase; exhausted = ready to judge |
| 6 Stay's backward action removed | §1 Back kept beside Next |
| 7 Migration loses the residual position | §4 residual count |
| 8 Final phase first finishes the run | §1 all phases judged |
| 9 Waiting choice across the layers | §3 `waiting_choice` row state, suspension, reconcile, resume, transactional bind |
| 10 Voice path | §3 `interaction: 'voice'` persisted; notice later |
| 11 Register discovery | §4 |

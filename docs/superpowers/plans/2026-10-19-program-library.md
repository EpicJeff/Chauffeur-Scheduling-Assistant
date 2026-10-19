# Program Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A program lives once in a household library as an ordered ladder of lessons with stable ids; a project assigns a run of it to a person and tracks that person's progress; two children can run the same program; deleting a project deletes the run, never the program.

**Architecture:** Approach 2 of the spec: today's `programs` row stays the run (person, project, state, slots, commitments, sessions, progress); the curriculum moves to a new `library_programs` table and every curriculum reader reaches it through `programs.load(run)` and the single resolved projection `programs.lesson_for(run, date)`. Progress is per-lesson session counts plus a bookmark that never leaves the current phase; milestones stay the person's judgement. A library program carries only a public profile; the person's starting point stays on the run. One transactional migration converts each existing program into a library row plus its run.

**Tech Stack:** Python 3.14, FastAPI (`chauffeur/main.py`), SQLite-backed storage (`services/storage.py`), plain-script tests from `chauffeur/` (`python tests/test_x.py`), Alpine.js templates, Playwright live tests.

**Spec:** `docs/superpowers/specs/2026-10-19-program-library-design.md` rev 3, approved by the user 2026-10-19. Read it before any task: §1 data model, loader, projection and progress rules; §2 authority; §3 flows (picker, Argyle waiting choice, voice, library page); §4 migration and routes; §8 the five confirmed rulings; §9-§10 the Codex findings each clause answers.

## Global Constraints

- **Running tests:** from `chauffeur/` with `HA_BASE_URL` unset. Run the task's own tests plus the named neighbours. Never the whole suite.
- **Fixture data only.** Tests isolate storage through `tests/harness.py` or a module that imports it. A live test that needs auth enforcement must not import `harness.py`.
- **Exact strings:**
  - edit refusal: "Only the person who made this program, or a parent, can change it."
  - in-use refusal: "In use by {names}'s project" / "In use by another project"
  - retitle refusal: "The name belongs to the library program; rename the project instead."
  - moved lesson: 409 "That lesson moved; open it again."
  - unresolved card: "Its library program is missing"
  - create form line: "Everyone in the household will see this program as: {title}"
  - remove-current-lesson copy: "{name} is on this lesson; her run moves to the next one."
  - Argyle match card: "There's a {title} program in the library, made for {made_for}. Use it for {name}, or make a new one?" with Use / Make new / Not now; Not now fails the row with "No program for now".
- **Locked rules (programs arc):** a milestone is judged by the person ("Reached it"); no completion fraction or count is ever shown; rotation variant by date arithmetic, never by progress; Back ("Another session on this") stays.
- **Gone vs unresolved:** the delete slice's rev 3.1 definition of gone stands; a run whose library row is missing is `unresolved`, a distinct state that is deletable and rebindable.
- **Nothing a person can do today disappears** without the user's approval (the retitle change is the one approved cut).
- **Never pass `None` as an access viewer.** House readers use `access.HOUSE`.
- **No browser dialogs.** `showGlobalAlert`, `promptConfirm`, `promptInput` only. Buttons, not anchors, on the phone.
- **Tailwind is precompiled:** after a template class change run `python chauffeur/tools/build_tailwind.py` (from the repo root: `python tools/build_tailwind.py` inside `chauffeur/`).
- **Every HA touchpoint degrades gracefully.**
- **Codex tasks** (2, 3, 4, 5) leave changes in the working tree and never bump `chauffeur/config.yaml` or commit (AGENTS.md). Claude reviews, gates, bumps the patch version (v2.499.N) and commits, with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- **Reviews cross models.** Codex-built tasks get a Claude reviewer; Claude-built tasks (1, 6) get Codex (`codex-companion.mjs task --model gpt-6.1-sol --effort high`, read-only). Codex's sandbox cannot run Playwright; the controller runs live tests.
- **Push gate:** no push until Task 5's migration and Task 6's UI are both reviewed clean, because Task 2 changes what a program row stores and the pages must read through the loader before anyone sees them.
- **PowerShell:** no double quotes in commit messages. Use the Bash tool for git.

## Review Focus

1. **A library edit lands while a child is mid-lesson on the wall.** The player must keep the lesson it opened (named ids), complete the right one, and the next window must pick up the edited steps. Pinned in Task 1 `scenario_edit_during_an_open_lesson`.
2. **Two children on the same program, different phases, same evening.** Windows, pushes and scripts must stay per run with no cross-talk (scripts keyed by run). Pinned in Task 1 `scenario_two_runs_same_program`.
3. **The library row is deleted or corrupted under a live run.** The run reads unresolved, its times stay reserved, Delete and Pick-a-program work, nothing 500s. Pinned in Task 1 `scenario_unresolved_run`.
4. **Migration of a program mid-ladder with `unit_shift` and a rotation.** The next session after conversion lands exactly where it would have before. Pinned in Task 1 `scenario_migration_residual_position`.
5. **Restart while a waiting choice is open.** The row is still waiting after restart and pause/resume; answering creates exactly one run. Pinned in Task 1 `scenario_waiting_choice_survives_restart`.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `chauffeur/tests/test_library_*.py` (new: model, access, flows, migration, live) | the contract | 1 (live in 6) |
| `chauffeur/services/library.py` (new) | library rows: create/edit/archive/delete, lesson CRUD + order with stable ids, visibility, runner lists, in-use check | 2 |
| `chauffeur/services/programs.py` | `load`, `lesson_for`, progress rules (`log_session`, Next/Back, removal), `mark_milestone` all-phases finish, effective shape, unresolved | 2, 3 |
| `chauffeur/services/program_lessons.py` | scripts keyed by (run, lesson, variant); projection-fed generation; legacy tuple translation | 3 |
| `chauffeur/services/storage.py`, `storage_sqlite.py` | `library_programs` table, run fields, script key, `get_library_program(s)` | 2 |
| `chauffeur/models/schemas.py` | `LibraryProgram`, `Program` (run) fields | 2 |
| `chauffeur/services/access.py`, `access_readers.py`, `home_board.py`, `subjects.py`, `projects.py`, `house_programs.py`, `house_attention.py`, `watchers.py`, `situations.py`, `deletion.py`, `study.py`, `agent_tools_v2.py` | the loader cutover (every curriculum reader through `programs.load`) and the digest | 3 |
| `chauffeur/main.py` | `/api/library*` routes; `/api/programs` create with `library_id` or profile; `/edit` per §2; `unit` route → Next/Back; script/help/completion routes carry lesson ids; lessons/wait | 2, 3 |
| `chauffeur/services/programs_curate.py` | curate from the public profile (`made_for`), not the member | 2 |
| `chauffeur/services/planned.py`, `chat_actions.py`, `asks.py`, `agent_tools_v2.py`, `voice_tools.py`, `missions.py` | `propose_program` library match, `waiting_choice` row state, the choice card and answer, voice policy | 4 |
| `chauffeur/services/migrations.py` | `migrate_program_library_v2499` | 5 |
| `chauffeur/templates/library.html` (new), `components/library_card.html` (new), `components/projects_page.html`, `programs_page.html`, `record_sheet.html`, `app.html`, `lesson_player.html`, `nav.html` | the library page and PWA home, the picker, the create form's visibility line, the run card, Next/Back, lesson ids in the player | 6 |

---

### Task 1 (Claude subagent): the tests

**Files:** create `tests/test_library_model.py`, `tests/test_library_access.py`, `tests/test_library_flows.py`, `tests/test_library_migration.py`; `tests/test_library_live.py` with a docstring checklist only (Task 6 writes it). Extend `tests/access_fixture.py` with one library row that R3/R5p/R15/R17 reference (so the matrix keeps running) and the expectation tables with the new library routes.

**Interfaces (produced; implemented by Tasks 2-5):**
- `library.create(fields, actor) -> {'status','program'|'message'}`; `library.update(lid, fields, actor)`; `library.archive(lid, actor)`; `library.delete(lid, actor) -> ok | refused ("In use by ...")`; `library.add_lesson(lid, lesson, actor)`, `library.update_lesson(lid, lesson_id, fields, actor)`, `library.remove_lesson(lid, lesson_id, actor)`, `library.order_lessons(lid, ids, actor)`; `library.runners(lid, viewer) -> {'named': [{name, project_id, project_title}], 'hidden': n}`; `library.can_edit(row, viewer)`.
- `programs.load(run) -> dict` (hydrated; `unresolved: bool`); `programs.lesson_for(run, date) -> {lesson_id, variant_label, title, steps, body|url, phase_id}`; `programs.next_in_phase(run)`; `programs.log_session(run_id, ..., lesson_id=None)`; `programs.step_bookmark(run_id, direction: 'next'|'back')`; `programs.mark_milestone(run_id, phase_id)`; `programs.rebind(run_id, library_id, actor)`.
- `storage.add_library_program/get_library_program/get_library_programs/update_library_program/delete_library_program`; script helpers keyed `(program_id, lesson_id, variant_label)`.
- Routes per spec §4; `POST /api/programs` body `{project_id, library_id}` or `{project_id, title, age_band, minutes, sessions_per_week, assumes, starting_point}`.
- `agent_tools_v2.propose_program(...) -> {'status':'waiting_choice','choice_id','options'}` on a match; `planned` row state `waiting_choice`; the choice answered through the mission ask answer route with `option` in `('use','make_new','not_now')`.
- `migrations.migrate_program_library_v2499()`.

- [ ] **Step 1: `test_library_model.py`** — spec §1: library row + run; `load` hydrates `phases[].units`, title, source, shape with the run's `weeks`/`milestone_hit_at`; `lesson_for` picks the bookmark's lesson and the date's variant, steps follow a library edit; stable lesson and phase ids through edit/reorder/add/remove; progress rules (partial sessions → completion → next in phase; exhausted phase = "ready to judge" and stays on the last lesson; Next and Back keep counts; removed current lesson → next in phase else previous, never an earlier phase; a lesson added into a judged phase is completed); "Reached it" on a non-final phase (no finish) and on the last unjudged phase (finish + release in one transaction, release failure surfaces); completion credits the named lesson; a moved lesson → 409; scripts keyed by run + lesson + variant, two runs of one program never share a script; effective shape on the run (approve persists the agreed shape; `weekday_shortfall` reads the run's); unresolved run (empty curriculum, `unresolved: True`, neutral windows, commitments kept, deletable, rebindable, warm board invalidated when the library row changes). Review Focus 1, 2, 3.
- [ ] **Step 2: `test_library_access.py`** — spec §2: library visible to every member and `access.HOUSE`; create by adult/parent, refused for a child; edit/archive by creator or parent, refused for another adult and a child with the exact message; delete refused while any run exists in any state, named only when the viewer sees the runner's project, otherwise "In use by another project"; `runners()` hides Kate's excluded project from Dad (fixture R15/R17); run cells R3/R5p/R15/R17 and keeper action gates unchanged (reuse `tests/test_access_core.py` tables); a run's `starting_point` never appears in any library payload; `test_access_register` discovers `/api/library*` routes and library getters; matrix probes for public curriculum vs restricted runner fields.
- [ ] **Step 3: `test_library_flows.py`** — spec §3: picker → run with effective shape; make new → library row with the public profile (`assumes`, `age_band` default from birthdate else `any`) + run with the private starting point; the visibility line text in the create payload; Argyle: match → `waiting_choice` row (dependents wait, reconcile keeps it waiting, resume does not re-run it), Use creates one run even on a repeated answer, Make new curates, Not now fails the row and the stage continues; voice persists `interaction: 'voice'`, a single match auto-uses and the notice arrives later, several/none curates; `/edit` retitle refused, shape writes the run, re-curate makes a new library row and rebinds after confirm; project delete leaves the library row; run delete the same; body-goal title refused at the library door. Review Focus 5.
- [ ] **Step 4: `test_library_migration.py`** — spec §4: one library row per program; `made_for` from shape + birthdate; lessons one per unit with variants from rotation labels; progress from `unit_for` + `unit_shift` + milestones; the residual count checked by logging one more session before and after conversion; scripts re-keyed per variant; crash before the mark reconverts from scratch, crash after never reconverts; idempotent; emissions, kit thread and run ids untouched. Review Focus 4.
- [ ] **Step 5:** run all four files; each red only for "new code missing"; existing tests that pin the old shape (`test_programs_*`, `test_program_lessons`, `test_lesson_*`, `test_house_programs`) are listed in the report, not edited (Tasks 2-3 update them under the loader with every assertion kept).

### Task 2 (Codex): storage, library service, loader, progress, routes

**Files:** `models/schemas.py`, `services/storage.py` + `storage_sqlite.py`, new `services/library.py`, `services/programs.py` (`load`, `lesson_for`, progress rules, `mark_milestone`, effective shape, `rebind`, unresolved), `services/programs_curate.py` (curate from the public profile), `main.py` (library routes, create with `library_id` or profile, `/edit` per §2, `unit` → `step_bookmark`), `services/access_readers.py` + `auth.py` rows.
- [ ] Gate: `test_library_model.py`, `test_library_access.py` (service-level parts), `test_programs_storage.py`, `test_programs_endpoints.py`, `test_programs_footprint.py`, `test_programs_living.py` (updated to the new shape with every assertion kept; list each change), `test_access_register.py`, `test_auth.py`.

### Task 3 (Codex): the loader cutover and lesson identity

**Files:** every reader in spec §1's inventory (`programs.py` internals, `program_lessons.py` generation/wait/legacy tuple, `house_programs.py`, `house_attention.py`, `watchers.py`, `subjects.py`, `situations.py`, `projects.py` cards and `_wrapper_fields`, `access.py` practice/commitment titles, `home_board.py` digest with library ids/updated_at, `study.py`, `agent_tools_v2.py` list/get, `deletion.py` previews), `main.py` script/help/completion/wait routes carrying `lesson_id` + `variant_label`.
- [ ] Gate: `test_library_model.py` (all), `test_program_lessons.py`, `test_lesson_endpoints.py`, `test_house_programs.py`, `test_programs_vitals.py`, `test_programs_reachable.py`, `test_programs_agent_tools.py`, `test_deletion_cleanup.py`, `test_deletion_hide.py`, `test_access_core.py`, `test_access_calendar.py`, and `PYTHONUTF8=1 python tests/test_access_matrix.py` (all classes, once at the end).

### Task 4 (Codex): Argyle and voice

**Files:** `services/agent_tools_v2.py` (`propose_program` match + `waiting_choice`, `list_programs` over the library), `services/chat_actions.py` (`run_row` records `waiting_choice`), `services/planned.py` (row state, dependents suspended, `reconcile`/`resume` behaviour), `services/asks.py` + `missions.py` (the three-button card and its answer, transactional bind of `run_id`, idempotent repeat), `services/voice_tools.py` + `agent_tools_v2.start_project` (`interaction: 'voice'` persisted; the stage applies the single-match policy; notice later).
- [ ] Gate: `test_library_flows.py` (Argyle and voice scenarios), `test_planned*.py`, `test_chat_actions.py`, `test_asks.py`, `test_start_mission.py`, `test_front_door_chat.py`, `test_voice*.py` neighbours, `test_deletion_late_work.py` (the stage runner path).

### Task 5 (Codex): migration

**Files:** `services/migrations.py` (`migrate_program_library_v2499`, registered in the runner after the deletion/audience migrations, per-row transaction, `library_id` marked last), `services/programs.py` helpers it needs.
- [ ] Gate: `test_library_migration.py` (all), `test_library_model.py`, `test_programs_endpoints.py`, `test_program_lessons.py`, `test_access_matrix.py` classes 4.1 and 4.7.

### Task 6 (Claude subagent): the UI

**Files:** new `templates/library.html` + `components/library_card.html` (admin `/library` in the Work group, page bar, PWA home under More → Library), `components/projects_page.html` (Add a piece → Program picker + Make a new one; run card "from the library" button and the current lesson by name under its phase, never a count; unresolved copy with Delete / Pick a program), `components/programs_page.html` (create form with the visibility line and the private starting-point label; Next/Back; "Reached it" per phase; retitle removed with the ruled message), `record_sheet.html`, `app.html` (phone library home, picker, run card, Today cards through the projection), `lesson_player.html` (lesson ids in wait/help/completion), `nav.html`; `tests/test_library_live.py`.
- [ ] Live tests: library list/new (visibility line)/edit/reorder/archive/delete-disabled with the in-use copy/remove-current-lesson copy (named runner vs hidden); the picker; the run card's library link and lesson name; unresolved card; phone More → Library; Next/Back; "Reached it" on a non-final phase; light and dark at phone width; screenshots inspected.
- [ ] Gate: `test_library_live.py`, `test_projects_detail_live.py`, `test_projects_live.py`, `test_project_card_live.py`, `test_record_sheet_live.py`, `test_project_sheets_phone_live.py`, `test_programs_runtime.py`, `test_lesson_player_runtime.py`, `test_deletion_live.py`.

### Task 7 (Claude): close-out

- [ ] Final whole-branch review on the most capable model; ONE fix wave; one scoped re-review.
- [ ] Gate: every file named above once more plus `test_access_matrix.py` all classes.
- [ ] `chauffeur/system_capabilities.md` top entry (BUILT, not device-verified; device steps: rebuild; open More → Library on a phone; start Kate on the piano program from the picker and a second run for Sam; practise one evening on the wall and see the lesson by name; edit a lesson's steps in the library and see the next evening pick them up; "Reached it" on phase one; delete Kate's project and see the library program remain; ask Argyle by voice "I want to learn piano" for Sam and hear "I'm setting that up"); amend the programs spec note; NEXT becomes front door slice 3 and the PWA Projects home rules.
- [ ] Memory: `projects-delete-slice.md` (library section) and `programs-arc.md`; bump, commit, push.

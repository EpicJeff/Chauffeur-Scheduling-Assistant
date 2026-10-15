# Projects core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A lasting home for a long-running goal: a project with a goal and done-when in the person's words, pieces of any record kind, and one ordered checklist of the person's steps (optionally held on the calendar) and Argyle's self-starting steps, created when a plan is approved or by hand, on the phone and the admin side.

**Architecture:** `services/subjects.py` moves its per-kind branches behind one adapter registry and gains `project` as the ninth kind. A new `services/projects.py` owns the record, its audience (`can_see`, `can_act`), steps (one write path, dependencies, `advance`), pieces and holds. `services/body_goal.py` is the one body-goal classifier for projects and programs. `services/planned.py` gains project creation on plan approval (one recoverable operation), self-starting work stages, stage cancellation and the `waiting_step` park; `services/missions.py` gains shared status sets. One component, `components/projects_page.html`, serves a new PWA tab and the admin Work group.

**Tech Stack:** Python / FastAPI / document storage (`storage.db_lock`); `services/subjects.py`, `services/projects.py` (new), `services/body_goal.py` (new), `services/programs_curate.py`, `services/planned.py`, `services/missions.py`, `services/situations.py`, `services/agent_tools_v2.py`, `services/agent_router.py`, `services/mind.py`, `services/voice_tools.py`, `services/auth.py`, `main.py` (`_practice_events`, the protected-commitment rule injection), `templates/app.html`, `static/pwa_shell.js`, `static/pwa_child_shell.js`, `templates/nav.html`, `templates/work.html`; plain-script tests from `chauffeur/` with `HA_BASE_URL` unset; node + jsdom for cards; Playwright for screenshots.

**Spec:** `docs/superpowers/specs/2026-10-15-projects-core-design.md` (APPROVED by the user 2026-10-15 after Codex review P1–P14).

## Global Constraints

- Tests from `chauffeur/`, `HA_BASE_URL` unset; the change's own tests plus named neighbours only; never the full suite.
- One audience: `projects.can_see(project, viewer)` and `projects.can_act(project, viewer)` gate every route, tool, card, feed and snapshot; the actor is the authenticated member, never a request's `member_id`.
- One step write path: `projects.set_step_state` / `edit_step` / `add_step` / `remove_step`; steps are never household tasks; no recurrence on steps.
- One body-goal check: `body_goal.is_body_goal(text)` for project titles, goals, done-whens, step titles and program aims; a body-goal project only for an adult owner, pinned `private`.
- Approving a plan writes the project and its steps in one operation under `storage.db_lock` with deterministic ids (mission id + plan rev), marked `approving` first and completed idempotently by `planned.reconcile`.
- Approval gates unchanged for writes, sharing details, booking, buying and outside sends; work stages start themselves after plan approval; build stages still wait for "Do this"; every running Argyle step has Skip and Stop.
- Mission status sets: `missions.LIVE`, `RUNNABLE`, `ATTENTION` replace every inline status list; `waiting_step` is LIVE, not RUNNABLE, not ATTENTION.
- A calendar hold is dated; outside the project's audience, and on walls, speakers and the Mind, it reads "Busy"; a driver's hold is one date-scoped `Rule(constraint_type='unavailable', start_date=end_date=<date>)`; a non-driver's hold reaches no solver input.
- Every new route gets a rule in `services/auth.py`; no browser dialogs; `python tools/build_tailwind.py` after template class changes; read `docs/ui_design_guide.md` before UI work; one shared builder per concept.
- Nothing a person could do is removed (Threads, Missions, Programs, Errands Tasks and their pages stay).
- Codex split: Claude writes each task's tests first and reviews; Codex implements via `codex:codex-rescue`; Claude gates, bumps `config.yaml`, updates `system_capabilities.md`, commits and pushes per task.

## Review Focus

1. A step's owner is archived: the step shows "Unassigned", stays tickable by anyone who `can_act`, and blocks nothing it did not block before. Task 4.
2. Two phones tick the same step at once: one write, one `advance`, one Argyle start. Task 4.
3. A project is dropped while an Argyle step's browse is mid-flight: the late result is dropped and no card arrives. Task 6.
4. A list that is a piece is deleted: the project page omits it and the project still loads. Task 8.
5. A hold's date passes with the step not done: the hold leaves the future calendar and nothing nags (reviews are slice B). Task 9.

---

### Task 1: The record-kind registry

**Files:** `services/subjects.py` (per-kind branches of `_rows`, `visible`, `_closed`, `link`, `context` and `FACETS` move to `ADAPTERS[kind] = Adapter(rows, title, visible, closed, link, context, facets)`; public functions keep their signatures and behaviour). Test: `tests/test_subject_registry.py`.

**Produces:** `subjects.Adapter` (a small dataclass or namedtuple), `subjects.ADAPTERS`, `subjects.register(kind, adapter)`; `KINDS` derived from `ADAPTERS`.

Tests: each of the eight kinds answers `load`, `title_of`, `visible`, `link`, `context`, `facets` exactly as before for a fixture of each (compare against values captured from today's functions in the test); registering a fake ninth kind makes `load`/`visible`/`context`/`find` work for it with no other edit. Neighbours (run unchanged): `test_subjects.py`, `test_subject_audience.py`, `test_mission_subject.py`, `test_subject_retarget.py`, `test_subject_hand_path.py`, `test_subject_voice.py`, `test_subject_hardening.py`, `test_planned_missions_audience.py`.

### Task 2: One body-goal classifier

**Files:** `services/body_goal.py` (NEW `is_body_goal(text) -> bool`: the existing `programs_curate.BODY_PHRASES` plus "weight loss" plus numeric weight and body-measurement targets — kg, lb/lbs/pounds, stone, inches/cm with a body part, BMI, body-fat percent, "lose N"); `services/programs_curate.py` (`screen_aim` and `screen_starting_point` call it). Test: `tests/test_body_goal.py` (block A).

**Produces:** `body_goal.is_body_goal(text: str) -> bool`.

Tests: true for "reach 70 kg", "get down to 185 lbs", "lose 10 pounds", "waist to 24 inches", "weight loss", "BMI under 25", "body fat 15%"; false for "run a 5k in 30 minutes", "deadlift 100 kg" (a load lifted is not a body target), "cook 4 nights a week", "learn Portuguese", "build 3 shelves 24 inches wide"; programs now refuse "reach 70 kg" at `screen_aim` and in the starting point. Neighbours: every `tests/test_programs*.py` and `tests/test_lesson*.py` that touches the body screen (list with `grep -l BODY_PHRASES\|screen_aim tests/*.py`).

### Task 3: The project record, its audience and lifecycle

**Files:** `services/projects.py` (NEW); `services/storage.py` (`projects` table, `add_project`, `get_project`, `get_projects(owner=None)`, `update_project`); `services/storage_sqlite.py` (index on id, owner); `services/subjects.py` (register `project`); `main.py` (`GET/POST /api/projects`, `GET/PATCH /api/projects/{id}`, `POST /api/projects/{id}/state`); `services/auth.py` (rules). Test: `tests/test_projects.py`, `tests/test_body_goal.py` (block B).

**Consumes:** Tasks 1–2.
**Produces:**
- `projects.create(fields, actor) -> dict` (validates, defaults audience by owner age, classifies body goal, refuses per spec §1).
- `projects.can_see(project, viewer) -> bool`, `projects.can_act(project, viewer) -> bool`.
- `projects.update(project_id, fields, actor) -> dict` (the pin: no widening, no minor owner for a body goal).
- `projects.set_state(project_id, state, actor) -> dict` (active/paused/done/dropped; pause, done and drop call `projects.stop_work(project_id)`, a no-op until Task 6).
- `projects.view(project, viewer) -> dict` (the viewer's projection: pieces filtered, steps, next step, steps done count).

Tests: create by hand with each audience; a kid's project defaults to `parents` and is visible to both parents, not to an aunt; an adult's defaults to `private`; a request `member_id` naming someone else never acts (TestClient with the auth stub of `test_subject_audience._as`); body goal allowed for an adult private, pinned (widening refused, owner change to a child refused), refused for a child and for `parents`/`household`; pause/resume/done/drop by `can_act` only; the `project` subject kind loads and reads under audience. Neighbours: `test_auth.py`, `test_subject_registry.py`.

### Task 4: Steps — one write path and dependencies

**Files:** `services/projects.py` (`add_step`, `edit_step`, `remove_step`, `set_step_state`, `advance` for the person side, the archived-owner rule); `main.py` (`POST /api/projects/{id}/steps`, `PATCH/DELETE /api/projects/{id}/steps/{step_id}`, `POST /api/projects/{id}/steps/{step_id}/state`); `services/auth.py`. Test: `tests/test_project_steps.py` (block A).

**Consumes:** Task 3.
**Produces:** `projects.set_step_state(project_id, step_id, state, actor) -> dict`, `projects.add_step(project_id, step, actor)`, `projects.edit_step(...)`, `projects.remove_step(...)`, `projects.advance(project_id) -> list[step_id]` (returns the Argyle steps it would start; starting is Task 6).

Tests: `needs` with a cycle or an unknown id refused; removing a needed step refused; an assignee cannot tick a step with open needs, a parent can; a child ticks only their own steps; ticking twice changes nothing and advances once; two threads ticking at once → one write, one advance (Review Focus 1 and 2: an archived owner shows "Unassigned" and stays tickable); `skipped` satisfies a dependent; reopening re-blocks a dependent that has not started; step titles pass the body classifier rule of Task 3. Neighbours: `test_projects.py`.

### Task 5: Shared mission status sets and `waiting_step`

**Files:** `services/missions.py` (`LIVE`, `RUNNABLE`, `ATTENTION`; the `waiting_step` status; every inline status list in `missions.py`, `planned.py`, `agent_tools_v2.start_mission_for`, `subjects.retarget`, `situations._thread_mission`, triage, the admin active list and the watchers uses the sets); `services/planned.py` (`prepare_next` parks in `waiting_step` when the next stage needs an unfinished person step of the bound project; `reconcile` resumes parked missions whose needs are satisfied). Test: `tests/test_project_steps.py` (block B).

**Consumes:** Task 4.

Tests: a parked mission is not stepped by `tick`, not ranked by triage, raises no finding, appears in the admin active list; `start_mission_for` for the same goal finds it (no duplicate); `subjects.retarget` refuses while it is parked as it does for running; ticking the needed step resumes it in the same write (no tick needed); a restart with the step already ticked resumes it at reconcile. Neighbours: `test_missions_engine.py`, `test_start_mission.py`, `test_subject_retarget.py`, `test_triage.py`, `test_planned_missions.py`.

### Task 6: Argyle's steps — self-start, finish with the stage, cancel

**Files:** `services/planned.py` (`prepare_next` starts a work stage of an approved plan itself: state `running`, no "Go do this part"; `cancel_stage(mission_id, stage_id, actor, outcome)`; `stop_plan` cancels a running work stage first; the runner checks the plan state before each row; late browse and research results check the stage is still running); `services/projects.py` (`advance` starts Argyle steps: resume the stage-backed mission or launch a standalone mission bound to the project; `on_stage_done`, `on_stage_blocked`, `on_question`; `stop_work`); `services/missions.py` (`finish_browse` and the research action drop a late result for a cancelled stage); `services/situations.py` (a running work stage's options: Skip, Stop, Tell it something). Test: `tests/test_project_steps.py` (block C); update `tests/test_planned_work.py`, `tests/test_planned_mission_cards.py`, `tests/test_planned_trip.py`, `tests/test_planned_piano.py` (Claude rewrites their "Go do this part" approvals to the self-start, keeping every other assertion).

**Consumes:** Tasks 4–5.

Tests: a work stage starts itself after plan approval with no tap; a build stage still offers "Do this"; research → a person's demo → more research completes (the first stage's step is done when its stage is done, demo becomes tickable, the mission parks, the tick resumes it); a standalone Argyle step is done when its mission finishes; a failed row marks the step `blocked` with the reason; a question shows on the step; Skip on a running work stage dismisses queued follow-up rows, settles asks as "Stopped", tells a live browse to stop, and satisfies dependents; Stop leaves the step `blocked`; dropping a project mid-browse drops the late result with no card (Review Focus 3); a build stage mid-row finishes that row and runs no more. Neighbours: `test_planned_missions.py`, `test_planned_hardening.py`, `test_browse_mission.py`, `test_planned_budget.py`.

### Task 7: From a plan to a project

**Files:** `services/planned.py` (the plan action accepts `project` {title, goal, done_when, owner, audience, target_date} and `steps` [{id, title, owner, needs, due_date}] for the person's steps and maps Argyle's stages to steps; `approve_plan` → one operation: `approving`, write project and steps with deterministic ids, bind, `approved`; `reconcile` completes an `approving` plan; planning inside a bound project appends steps; `_bind_created` appends pieces); `services/missions.py` (planner prompt documents the project and steps fields); `templates/app.html` and `static/situations.js` (the plan card shows the project and the person's steps beside the stages). Test: `tests/test_project_planning.py`.

**Consumes:** Tasks 3–6.

Tests: the preview carries the project and the person's steps; approving writes the project once and each step once; two concurrent approvals write once; a crash after the project write (simulated by raising between writes) leaves `approving`, and `reconcile` completes it with the same ids; a thread-origin plan binds the thread, the thread's earlier subject becomes the first piece and stays in `subject_history`, `subject_rev` bumps and an old button refuses; sibling missions on the thread read the project; planning inside an existing project appends steps (fresh ids) and creates no project; a record a build stage creates attaches as a piece; the planned mission becomes `origin_mission_id`. Neighbours: `test_planned_missions.py`, `test_planned_party.py`, `test_mission_subject.py`, `test_planned_mission_cards.py`.

### Task 8: Pieces and Argyle's project tools

**Files:** `services/projects.py` (`add_piece`, `remove_piece`, the deleted-record rule); `services/agent_tools_v2.py` (`list_projects`, `get_project` READ; `add_project_step`, `add_to_project`, `set_project_state` proposable; `set_step_state` as a tool with the tap's checks; registry entries and stage `CONTRACT` rows); `services/agent_router.py` (schemas; channel filtering through `situations.channel_visible` with the project as the subject); `main.py` (`POST/DELETE /api/projects/{id}/pieces`, the "Part of" field on the subject situations payload); `services/auth.py`. Test: `tests/test_projects_tools.py`.

**Consumes:** Tasks 3–7.

Tests: attaching by hand only to a project the actor `can_act` on; a piece hidden from the viewer is omitted from the project view; a deleted list piece is omitted and the project loads (Review Focus 4); "Part of" shows only to a viewer who can see the project; each tool through `execute_tool` and through the router with a scripted model; "tick off demo" drives `set_step_state` with the tap's checks; in a mixed channel `list_projects` omits a `parents` project; registry parity still holds. Neighbours: `test_registry_parity.py`, `test_stage_contract.py`, `test_situation_tools.py`, `test_agent_driver_tools.py`.

### Task 9: Calendar holds

**Files:** `services/projects.py` (`find_window(member_id, minutes, by_date)`, `confirm_hold`, `clear_hold`, `calendar_holds(start, end, viewer)`); `main.py` (`POST/DELETE /api/projects/{id}/steps/{step_id}/hold`; the calendar feed merges `calendar_holds` beside `_practice_events`; the solver input injects one date-scoped `Rule` per driver hold beside the protected-commitment rules); `services/mind.py`, `services/voice_tools.py`, the wall's calendar tiles (holds only as "Busy" for non-household projects); `services/auth.py`. Test: `tests/test_project_holds.py`.

**Consumes:** Task 4.

Tests: the finder avoids an overlapping calendar event, a practice window and another hold (interval overlap, not equal start times) and returns `None` with the honest message when there is no time before the due date; confirmation re-checks and refuses a window taken meanwhile; the owner sees the step title on the calendar, a spouse sees "Busy" for a private project, the household sees the title for a `household` project; the wall, a speaker reading the day and the Mind's snapshot see "Busy" for `private` and `parents` projects; a driver's hold makes the matcher treat them unavailable on that date only (the matcher honours `start_date`/`end_date`); a non-driver's hold adds no rule; a past hold leaves the future calendar (Review Focus 5). Neighbours: `test_programs*.py` (practice windows), `test_calendar*.py` (list), `test_mind_endpoints.py`, `test_voice_tools*.py` (list).

### Task 10: Audience across every surface

**Files:** `services/mind.py` (snapshot: no `private` project; `parents` only for the parents' audience); `services/voice_tools.py` (never speaks a `private` or `parents` project to a room); `services/situations.py` and `planned.keeper_view` (keepers of a project-bound mission keep the row and Stop); `main.py` (every project route through `can_see`/`can_act`). Test: `tests/test_projects_audience.py`.

**Consumes:** Tasks 3–9.

Tests: for each of `private`, `parents`, `household`: project detail and list, the PWA tab data, record pages' "Part of", the Mind snapshot, a speaker, a mixed channel, a keeper, every agent tool. Neighbours: `test_planned_missions_audience.py`, `test_subject_hardening.py`, `test_planned_hardening.py`.

### Task 11: The cards and pages

**Files:** `templates/components/projects_page.html` (NEW, one builder: list cards, the project view with goal, done-when, checklist with ticks, Argyle's step states and what they found, Skip/Stop, pieces, conversations, the New project form with "Plan it with Argyle", "Put it on the calendar" with the finder's suggestion and a picker, Pause/Resume/Done/Drop); `templates/app.html` + `static/pwa_shell.js` + `static/pwa_child_shell.js` (a Projects tab wired into `setView`, `applyViewVisibility`, `updateTabBar`, the role and kid-shell orders, `pwaIcon`; every signed-in child sees their own); `templates/nav.html` (`PAGE_GROUPS['work']` first entry Projects; `NAV_ITEMS`); `templates/work.html` (`<section data-page-tab="projects">`); `main.py` (`GET /projects`); the trip, occasion, program and list pages ("Part of" line and an "Add to a project" picker); `python tools/build_tailwind.py`. Read `docs/ui_design_guide.md` first. Test: `tests/test_projects_cards.py` (node + jsdom: the list card, the project view for owner, parent and child, ticks posting to the step route, the hold flow, Skip/Stop, the plan card's project and steps); Playwright screenshots of the PWA tab and the admin tab saved to the scratchpad for review.

**Consumes:** Tasks 3–10.

Tests: both surfaces render through the one component; a child sees their projects whatever `own_account` says; no `alert`/`confirm`/`prompt`; the card never builds words the API did not give it. Neighbours: `test_template_js.py`, `test_nav_runtime.py`, `test_admin_gate_everywhere_live.py`, `test_planned_mission_cards.py`, `test_pwa*.py` (list).

### Task 12: Acceptance — Portuguese, the bathroom, a kid, a private goal

**Files:** tests only, plus the small fixes they expose. Tests: `tests/test_project_portuguese.py`, `tests/test_project_bathroom.py`, `tests/test_project_kid.py`, `tests/test_project_private.py` on the real registry, only the model and the browser faked.

**Consumes:** Tasks 1–11.

- **Portuguese:** "I want to learn Portuguese" → interview → a plan showing the project, a program build stage, a person's step "attend a first class" and an Argyle step "find three meetups nearby"; approve → the project exists with the program as a piece; the meetup step runs by itself and attaches what it found; "attend a first class" gets a hold.
- **Bathroom:** a plan with steps demo (person) → tile research (Argyle) → buy tile (Argyle, a write) → tile the floor (person); approve; research waits; demo ticked → research runs by itself; buying comes back as a card; tiling stays blocked until the purchase step is done.
- **Kid:** Kate creates "learn to ride a bike" by hand; both parents see it; Kate ticks her step; an aunt does not see it.
- **Private:** an adult's "get down to 185 lbs" project, allowed and private; the spouse sees nothing on any surface and "Busy" on the calendar for its hold; changing its audience is refused.

Neighbours: `test_planned_party.py`, `test_planned_trip.py`, `test_planned_piano.py`.

### Task 13: Docs, memory, final review

`system_capabilities.md` entry (BUILT, NOT device-verified, device steps for the four runs), spec status, memory (`projects-arc.md` → slice A built; the MEMORY.md line); whole-branch Codex adversarial review from the plan's base commit, one fix wave with tests first, one scoped re-review (a second targeted wave only for unclosed findings or regressions; verify any "pre-existing" claim against the base commit before accepting it).

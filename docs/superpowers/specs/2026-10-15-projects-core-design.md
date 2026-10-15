# Projects, core — a lasting home for a long-running goal

**Date:** 2026-10-15. **Status:** DRAFT, design approved section by section by the user in conversation (2026-10-15); awaiting Codex adversarial review, then the user's review of this document. Slice A of the Projects arc (A core, B reviews, C measures, D templates and build-project depth).
**Builds on:** `2026-10-14-mission-subject-resolver-design.md` (subjects, binding, audience inheritance), `2026-10-14-planned-missions-design.md` (plans, stages, the stage contract and runner, keeper and channel rules). **Supersedes the framing of** `2026-10-15-mission-wake-conditions-design.md`: its engine is kept and becomes slice B (reviews), revised there.

## Problem

The user (2026-10-15): "The point is to provide a framework for a long-running goal or project that helps you along the way." Their examples: "I want to get down to 185 lbs" (an exercise program, weekly weight and diet, adjusting the program and meals); "I want to learn Portuguese" (a program, check-ins after portions of it, meetups at a proficiency); "I want to renovate my bathroom" (a design, a skills assessment, programs for each skill, a project plan checked off as it goes, finding materials). And: "How do we design something that is flexible enough it can handle any of the examples I gave and others? … the underlying framework should support adding new tools or types of things it can do."

Today a planned mission ends when its plan finishes. Nothing durable holds the program, the lists and the threads that belong to one goal; nothing tracks the person's own steps; and the user's October feedback named Threads versus Missions as confusing. A project is the durable, user-facing thing; missions become Argyle's working sessions inside it and threads its conversations with people outside.

## Decisions (the user's, 2026-10-15)

1. **Reframe as Projects.** Every long-running goal is five parts — goal, pieces, steps, measures, reviews — each extended by adapters, with optional templates. This slice builds goal, pieces and steps.
2. **Order:** A core (this), B reviews, C measures, D templates and build-project depth.
3. **Everyone can own a project, kids included.** Parents see their kids' projects (an advocate, not a warden). An adult's project can be private.
4. **Adults may hold private body goals** (a locked rule changed by the user): never a minor, never visible to another member, never on a wall or a speaker. Weight tracking itself arrives with measures (slice C).
5. **Argyle's steps start themselves.** Approval sits only where something real happens: a write to the family's records, sharing the family's details, booking, buying, anything sent outside the family. Applied to slice 2 as well: a plan's work stages start once the plan is approved; "Go do this part" goes away.
6. **Your steps may go on the calendar, optionally per step,** with Chauffeur suggesting the time.
7. **Any approved plan is a project.** A one-off ("book a plumber") stays a plain mission.
8. **A Projects tab in the phone app,** and Projects as the first tab of the admin Work group.

## Section 1 — The project and its pieces

### Record

```
project = {
  'id', 'title',
  'goal': str, 'done_when': str,           # the person's words
  'owner_member_id': str, 'created_by': str,
  'audience': 'private' | 'parents' | 'household',
  'target_date': 'YYYY-MM-DD' | None,
  'state': 'active' | 'paused' | 'done' | 'dropped',
  'pieces': [{'kind': str, 'id': str, 'added_by': str, 'added_at': float}],
  'origin_mission_id': str | None,
  'created_at', 'updated_at', 'rev': int,
}
```

Storage: a `projects` table (`storage.add_project`, `get_project`, `get_projects(owner=None)`, `update_project`) indexed on id and owner.

**Audience.** `private`: the owner only (a parent of a minor owner always sees it: a child's project is never private from their parents). `parents`: the owner and every active parent. `household`: every active member. A kid-owned project defaults to `parents`; an adult's to `private`. A project whose title, goal or done-when the existing body screen (`programs_curate` body phrases, including the missing "weight loss" the lesson-player arc tracked) would refuse is allowed only when the owner is an adult and the audience is `private`, and is then pinned to `private` (no edit may widen it). Everything else passes the screen as it does for programs.

**Lifecycle.** A project is created when a plan is approved (Section 3) or by hand (the New project form: title, goal, done-when, owner, audience, target date; a "Plan it with Argyle" button starts a planned mission bound to it). Pause, resume, done and drop are one tap each, by the owner or a parent/adult who can see it; when every step is done Argyle offers Mark done, never deciding on its own. Dropping or finishing a project stops its running Argyle work (as Stop does) and leaves its pieces, tasks and records in place.

### Pieces and the record-kind registry

`services/subjects.py` keeps its public functions (`load`, `title_of`, `visible`, `spoken_safe`, `link`, `context`, `subject_records`, `find`, `resolve`, `retarget`) but their per-kind branches move behind one adapter shape, `subjects.KIND_ADAPTERS[kind] = Adapter(rows, title, visible, closed, link, context, facets)`. The eight existing kinds move unchanged (their tests are the proof); `project` becomes the ninth. A new kind of record joins by registering one adapter. A mission or thread binds to a project exactly as to a trip (slice 1), so "inside the project" is that binding.

A piece is a link from a project to a record of any registered kind. Pieces attach: automatically when a stage of the project's plan creates a record (the runner's `_bind_created` also appends the piece); by hand (an "Add to a project" picker on the project page and on each record's page); and by Argyle (`add_to_project(project_id, kind, id)`, a proposable write). A piece keeps its own audience: the project page lists only pieces the viewer may see, and a piece never widens a project's audience nor a project a piece's.

## Section 2 — Steps

One ordered checklist mixing the person's steps and Argyle's.

```
step = {'id', 'order': int, 'title', 'owner': member_id | 'argyle',
        'needs': [step_id], 'due_date': 'YYYY-MM-DD' | None,
        'state': 'todo' | 'doing' | 'done' | 'skipped',
        # a person's step
        'task_id': str,                      # the household task that IS this step
        'window': {'date', 'start', 'end'} | None,
        # an Argyle step
        'goal': str, 'mission_id': str | None, 'stage_id': str | None,
        'found': dict | None, 'waiting_on': str | None}
project['steps'] = [step, ...]
```

**A person's step is a household task.** The task gains `project_id` and `step_id`; its title, assignee, due date and done state are the step's. So a step shows wherever tasks show today (the Errands Tasks tab, the wall's task tile, the family digest) and `complete_household_task` / `claim_household_task` work on it by tap and through Argyle. `stages.refuse_task_assignment` still applies. A step whose `needs` are not done shows "Waiting on: <step>" and cannot be ticked by its assignee; a parent can tick it anyway. Ticking the task ticks the step (one write path: `complete_household_task` calls `projects.on_step_done`).

**On the calendar, optionally.** "Put it on the calendar" asks a one-off variant of the program slot finder (`programs.propose_slots` reads the week's committed time and picks a window that does not sit on it) for the assignee, honouring the due date; the person confirms or picks another time; the chosen window is stored on the step and held the way practice windows are held (a protected commitment for that member on that date, the same path `programs` uses), and appears on the family calendar through the same feed. The task itself never enters the driving solver (the household-tasks rule stands; only the window does).

**An Argyle step** has a goal ("find three tile options under $5 a square that fit a 5 by 8 floor"). When its `needs` are done it starts itself (`projects.advance(project_id)`): a stage of the project's planned mission when it came from the plan, otherwise a new mission bound to the project with the step's goal. Reading, research and browsing run freely; anything that writes, shares the family's details, books or buys comes back as a card to approve, exactly as today. What the work found is attached to the step (`found`); the step is done when its mission finishes; a question it cannot answer shows on the step as "Argyle needs you: <question>" with the existing answer card. A running Argyle step has Skip and Stop.

**Waiting on a person's step.** A planned mission whose next stage needs an unfinished person step parks in a new mission status `waiting_step` (not stepped by the tick, not ranked by triage, no findings); `projects.on_step_done` resumes it (`waiting_step → running`) with no polling. This is the one trigger core needs; dates, replies and schedules are slice B.

**Slice 2 change.** A work stage no longer waits for "Go do this part": when `planned.prepare_next` reaches a work stage of an approved plan it starts it (`state: running`), with Skip and Stop on the card. A build stage still waits for "Do this" (its rows write).

## Section 3 — From a goal to a project

"I want to learn Portuguese" in the Argyle chat: the slice 2 interview, then a plan. The plan now shows three things before the one tap: Argyle's stages (as today), the person's steps (title, who, after what, optional due date), and the project it will become (title, goal, done-when, owner, audience). **Approving the plan writes the project and its steps** (the person's steps as household tasks) — the plan preview is the full statement of those writes, so this is the approval for them; build stages still approve each batch of records they create. The planned mission becomes the project's first working session (`origin_mission_id`), and is bound to the project as its subject (its earlier subject, if any, becomes a piece). Records its stages create attach as pieces.

A kid can create a project by hand and tick their steps; a plan for a kid's project is approved by a parent or adult who can see it (as programs: approving is never a chat tool for a child).

## Section 4 — Where it lives

- **Phone app:** a Projects tab (a ninth tab, wired into `setView`, `applyViewVisibility`, `updateTabBar`, the role and kid-shell orders and `pwaIcon`). It lists the viewer's projects and, for a parent, their kids'; each card: title, next step, steps done (counting up). A project opens to goal and done-when, the checklist (tick your steps; see Argyle's step state and what it found), the pieces (tap through to their pages), what Argyle is doing now, and the project's conversations. A child sees their own projects; the stage capability `own_account` decides whether a young child sees theirs directly or only through a parent.
- **Admin:** Projects is the first tab of the Work group (`PAGE_GROUPS['work']`), a `<section data-page-tab="projects">` on `/work`, and `/projects` serves the same component. One component (`components/projects_page.html`) serves both surfaces; only presentation differs (the kiosk-shares-logic rule).
- **Record pages:** a trip, occasion, program or list that is a piece shows "Part of: <project>" for a viewer who can see the project.
- **Argyle:** read tools `list_projects`, `get_project`; proposable writes `add_project_step`, `add_to_project`, `set_project_state` (pause, resume, done, drop); `complete_household_task` ticks a person's step. "What's next on the bathroom?", "tick off demo", "add the tile list to the bathroom project", "pause Portuguese" all have the tap path above.
- **Routes** (`/api/projects`, `/api/projects/{id}`, `/{id}/steps`, `/{id}/pieces`, `/{id}/state`, `/{id}/steps/{step_id}/window`) each get a rule in `services/auth.py` (`SIGNED_IN` data, writes refused in the handler for a viewer who may not act), following the threads and missions pattern.

## Section 5 — Audience and safety

- A project's words (title, goal, done-when, step titles, what Argyle found) follow its audience everywhere, through the slice 1 and 2 machinery: `subjects.visible` for the `project` kind; keepers (a creator a parent's later change excluded) keep their row and Stop, never the words; a channel some member may not see gets no project words (`situations.channel_visible`); speakers never speak a `private` or `parents` project to a room; the Mind's snapshot carries no `private` project at all and `parents` projects only for the parents' audience.
- A private project never appears on a wall, in the family digest, or in another member's lists; its person steps are household tasks whose rendering on the wall and digest honours the project's audience (a private project's tasks are left off them).
- Argyle's auto-started work is bounded by the existing daily model allowance, the mission step cap and `budget_guard`; approval gates are unchanged.
- Nothing a person could do is removed: Threads, Missions, Programs, Errands Tasks and their pages stay; Projects adds a home above them.

## Section 6 — Tests (written first by Claude; Codex implements)

- `tests/test_projects.py`: the record, audience for each level, kid-owned visible to parents, the adult-private body goal allowed and pinned private, a minor's or non-private body goal refused, lifecycle taps, Mark done offered not applied, dropping stops running work and keeps pieces.
- `tests/test_subject_registry.py`: every existing kind behaves identically through the adapters (the slice 1 subject tests run unchanged as neighbours); `project` loads, titles, links and reads under its audience.
- `tests/test_project_steps.py`: person steps are household tasks; `needs` blocks an assignee's tick and not a parent's; ticking a task ticks its step and starts an Argyle step that needed it; a planned mission in `waiting_step` resumes on the tick with no polling; the window finder suggests a free time, the confirmed window appears on the calendar feed and the task never reaches the solver.
- `tests/test_project_planning.py`: the plan preview carries the project and the person's steps; approving writes them; work stages start themselves; build stages still ask; created records attach as pieces; the mission becomes the project's first working session.
- `tests/test_projects_audience.py`: every surface above for `private`, `parents`, `household` (detail, list, PWA tab data, wall, digest, Mind snapshot, speakers, a mixed channel, a keeper).
- `tests/test_projects_cards.py` (node + jsdom): the PWA tab and the admin component render one shared builder; a Playwright screenshot of each for review.
- Acceptance on the real registry, only the model faked: `tests/test_project_portuguese.py` (a plan becomes a project holding a program; "attend a first class" gets calendar time; "find three meetups nearby" runs by itself and attaches what it found); `tests/test_project_bathroom.py` (an ordered checklist; demo ticked by a person starts tile research by itself; a purchase-shaped write comes back as a card); `tests/test_project_kid.py` (Kate's "learn to ride a bike", seen by her parents); `tests/test_project_private.py` (an adult's private project invisible to their spouse on every surface).

## Out of scope (later slices)

Reviews and check-ins with dates, replies and schedules (slice B, on the wake engine); measures, their sources and thresholds, including weight (slice C); templates, a decisions list, materials sourcing and budgets (slice D).

## Build split (the user's standing rule)

Claude writes every task's tests first; Codex implements each task via `codex:codex-rescue`; Claude reviews the diff, reruns the gate, updates `system_capabilities.md`, bumps `config.yaml` and commits. Codex reviews this spec adversarially before the user sees it, and the whole branch at the end.

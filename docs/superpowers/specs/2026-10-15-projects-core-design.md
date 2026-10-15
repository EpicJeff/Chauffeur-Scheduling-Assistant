# Projects, core — a lasting home for a long-running goal

**Date:** 2026-10-15. **Status:** APPROVED by the user 2026-10-15. Was: DRAFT, design approved section by section by the user in conversation (2026-10-15); Codex adversarial review of the first draft (fourteen findings, P1–P14) folded in, two of which change the approved design and are named in "Changes after review" below; awaiting the user's review of this document. Slice A of the Projects arc (A core, B reviews, C measures, D templates and build-project depth).
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

## Changes after review (for the user's attention)

- **A person's step is no longer a household task (P1, P3, P4).** The approved draft made each step a task so it would show on the Errands Tasks tab, the wall's task tile and the digest. Tasks have six entry points (the API, Errands editing, claiming, recurrence, deletion, the agent's task matching) and a recurrence copies the whole task; each would need new project privacy checks and syncing with the step, and a spouse could read or tick a private body-goal step through them. Steps now live on the project, with one write path and the project's audience. Cost: in this slice a step shows in the Projects tab, the admin Projects page and Argyle, not on the Errands Tasks tab, the wall or the digest; an audience-aware presence there is a later slice.
- **Calendar time needs new pieces (P6, P7, P12).** The practice-window path holds weekly windows with no date, its slot finder ignores overlaps, and its calendar entries carry their full words to everyone and to the Mind. This slice therefore adds dated step holds, an overlap-aware slot finder, and an audience-aware calendar projection in which a viewer outside the project sees only "Busy".

## Section 1 — The project and its pieces

### Record

```
project = {
  'id', 'title',
  'goal': str, 'done_when': str,           # the person's words
  'owner_member_id': str, 'created_by': str,
  'audience': 'private' | 'parents' | 'household',
  'body_goal': bool,                       # set by the classifier, never by a client
  'target_date': 'YYYY-MM-DD' | None,
  'state': 'active' | 'paused' | 'done' | 'dropped',
  'pieces': [{'kind', 'id', 'added_by', 'added_at'}],
  'steps': [step, ...],                    # Section 2
  'origin_mission_id': str | None,
  'created_at', 'updated_at', 'rev': int,
}
```

Storage: a `projects` table (`storage.add_project`, `get_project`, `get_projects(owner=None)`, `update_project`), every write under `storage.db_lock`, `rev` bumped on each.

**Audience.** One function, `projects.can_see(project, viewer)`: `private` — the owner, plus each active parent of a minor owner (a child's project is never private from their parents); `parents` — the owner and every active parent; `household` — every active member. A kid-owned project defaults to `parents`, an adult's to `private`. `projects.can_act(project, viewer)` — the owner, or a parent/adult who can see it (a child acts only on their own project's steps). Every route, tool and surface below uses these two; a request's `member_id` is never the actor (the authenticated actor is, as everywhere since the auth flip).

**Body goals (P8).** One shared classifier, `body_goal.is_body_goal(text) -> bool`, replaces the program screen's phrase list as the single check: the existing phrases (with the missing "weight loss" the lesson-player arc tracked) plus numeric weight and body-measurement targets ("reach 70 kg", "185 lbs", "lose 10 pounds", "waist to 24 inches", BMI and body-fat percentages). It runs on every create and edit of a project's title, goal, done-when and every step title, server-side. A project for which it fires gets `body_goal: true` and is allowed only when the owner is an adult and the audience `private`; it is then pinned: no edit may widen the audience, and no change of owner may move it to a minor. Programs use the same classifier (`programs_curate.screen_aim` and `screen_starting_point` call it), closing the gaps Codex found ("reach 70 kg" passes today); a program is refused as before, except a program whose project is an adult's private body goal, which is allowed and inherits the pin.

**Lifecycle.** A project is created when a plan is approved (Section 3) or by hand (the New project form: title, goal, done-when, owner, audience, target date). Pause, resume, done and drop are one tap each, by anyone who `can_act`; when every step is done or skipped Argyle offers Mark done, never deciding on its own. Pausing stops its running Argyle work (Section 2's cancellation) and starts nothing new until resumed; done and drop do the same and leave pieces and records in place.

### Pieces and the record-kind registry

`services/subjects.py` keeps its public functions (`load`, `title_of`, `visible`, `spoken_safe`, `link`, `context`, `subject_records`, `find`, `resolve`, `retarget`) but their per-kind branches (`_rows`, `visible`, `_closed`, the `link` dict, the `context` readers, `FACETS`) move behind one adapter shape, `subjects.ADAPTERS[kind] = Adapter(rows, title, visible, closed, link, context, facets)`. The eight existing kinds move with no behaviour change, proven by the slice 1 subject tests running unchanged; `project` becomes the ninth (its `visible` is `projects.can_see`, its `context` the goal, done-when, the next steps and the pieces the viewer may see). A new kind of record joins by registering one adapter.

A piece is a link from a project to a record of any registered kind. Pieces attach automatically when a stage of the project's plan creates a record (the runner's `_bind_created` appends the piece in the same write that binds it); by hand (an "Add to a project" picker on the project page and on each record's page, offering only projects the actor `can_act` on); and by Argyle (`add_to_project(project_id, kind, id)`, a proposable write approved as any other). A piece keeps its own audience: the project page lists only pieces the viewer may see; a record page shows "Part of: <project>" only to a viewer who can see the project.

## Section 2 — Steps

One ordered checklist mixing the person's steps and Argyle's, stored on the project; the project is the only write path.

```
step = {'id', 'order': int, 'title', 'owner': member_id | 'argyle',
        'needs': [step_id], 'due_date': 'YYYY-MM-DD' | None,
        'state': 'todo' | 'doing' | 'done' | 'skipped' | 'blocked',
        'done_by': member_id | 'argyle' | None, 'done_at': float | None,
        # a person's step
        'hold': {'date', 'start', 'end', 'confirmed_by'} | None,
        # an Argyle step
        'goal': str, 'mission_id': str | None, 'stage_id': str | None,
        'found': dict | None, 'question': str | None}
```

**Dependencies.** `needs` must name existing steps of the same project; a cycle or a dangling reference refuses the write (P5). `done` and `skipped` satisfy a dependent step (skipping "hire a plumber" because you will do it yourself lets the next step go); `todo`, `doing` and `blocked` do not.

**One write path (P3, P4).** `projects.set_step_state(project_id, step_id, state, actor)` is the only way a step's state changes: it checks `can_act` (a child only on their own steps; an assignee may not tick a step whose needs are open; a parent may, for life happening out of order), is idempotent (ticking a done step again changes nothing and advances nothing), allows reopening (`done → todo`, which re-blocks dependents that have not started), and calls `projects.advance(project_id)` after its write. There is no recurrence on a step. Editing a step's title, owner, due date or needs, adding and removing steps go through `projects.edit_step` / `add_step` / `remove_step` with the same checks; removing a step that others need is refused until they are edited.

**On the calendar, optionally (P6, P7, P12).** "Put it on the calendar" asks a new finder, `projects.find_window(member_id, minutes, by_date) -> {date, start, end} | None`: interval-based over that member's dated calendar events, their program practice windows and every other confirmed step hold, inside waking hours, on or before the due date; `None` says honestly "No free time before <date>". The person confirms or picks another time; confirmation re-checks the window is still free. A confirmed hold is stored on the step (dated, one occurrence). **The calendar shows it through an audience-aware projection:** one new feed source, `projects.calendar_holds(start, end, viewer)`, yields each hold as an entry titled with the step for a viewer who `can_see` the project and as "Busy" (no project words) for anyone else; the wall, the speakers and the Mind's calendar input always get "Busy" for a `private` or `parents` project. **For a member who drives**, a hold adds one date-scoped `Rule(constraint_type='unavailable', start_date=<date>, end_date=<date>, time_start, time_end)` for that driver, injected beside the protected-commitment rules in `main.py` (`Rule` already carries `start_date`/`end_date`; nothing weekly; a test proves the matcher honours the dates); for a non-driver it is shown and socially defended only, as practice windows are (the solver cannot defend a non-driver's time — locked, programs arc). The task-free, solver-free rule for household tasks is untouched.

**Argyle's steps (P5, P11).** A step owned by `argyle` has a goal. `projects.advance(project_id)` starts every Argyle step whose needs are satisfied and which is `todo`: a stage of the project's planned mission when it came from the plan (the mission resumes from `waiting_step`, Section 3), otherwise a new mission bound to the project with the step's goal. Reading, research and browsing run freely; anything that writes, shares the family's details, books or buys comes back as a card to approve, exactly as today. **A stage-backed step is done when its stage is done** (`planned.finish_work` for a work stage, the runner's `done` for a build stage), not when the mission finishes; a standalone step is done when its mission finishes. A stage that cannot go on (a failed row, a blocked mission, a spent budget it cannot carry on from) marks its step `blocked` with the reason; a question it asks shows on the step as "Argyle needs you: <question>" with the existing answer card. What the work found is attached to the step.

**Cancelling running work (P11).** A running Argyle step offers Skip and Stop, which need new engine transitions: `planned.cancel_stage(mission_id, stage_id, actor, outcome)` ends a running work stage (no further planner steps for it, its queued follow-up rows dismissed, its open asks settled as "Stopped", a live browse told to stop through the existing `should_stop` signal) and records the outcome (`skipped` satisfies dependents; `stopped` leaves the step `blocked`); `planned.stop_plan` accepts a plan with a running work stage by cancelling it first. A build stage that is mid-row finishes the row in flight and runs no further rows (the runner checks the plan's state before each row). Every late result (a browse finishing, a research answer) checks its stage is still running before it is applied and is dropped otherwise.

## Section 3 — From a goal to a project

**Creating (P2, P9, P10).** "I want to learn Portuguese" in the Argyle chat: the slice 2 interview, then a plan. The plan now shows three things before the one tap: Argyle's stages (as today), the person's steps (title, who, after what, optional due date), and the project it will become (title, goal, done-when, owner, audience). **Approving the plan writes the project and its steps** — the preview is the full statement of those writes, so the tap approves them; build stages still approve each batch of records they create.

- **One authoritative binding.** The project binds where the mission reads its subject: a thread-origin mission's thread (as `missions.subject_of` and `subjects.subject_records` already read it), otherwise the mission. Its earlier subject, if any, becomes the project's first piece and stays in `subject_history`, so the old audience still narrows what the transcript and its summaries may say (a subject only ever narrows). Sibling missions on the same thread read the project from then on, which is the intent: they are the same conversation. `subject_rev` is bumped, so any stale button refuses.
- **Planning inside an existing project.** When the mission is already bound to a project (New project → "Plan it with Argyle", or "plan the next part of the bathroom"), approval creates no project: the preview shows the steps it will append (and any changes to the project's fields), and approval appends them with fresh step ids, never duplicating a step already there.
- **One recoverable write.** Approval runs as one operation under `storage.db_lock` with deterministic ids derived from the mission id and the plan rev (`project id`, each step id): the plan is marked `approving`, the project and its steps are written, the binding is set, then the plan is marked `approved` and work may start. A crash in between leaves `approving`; `planned.reconcile` (startup and tick) completes it idempotently with the same ids. Two concurrent approvals of the same rev write once.

**Waiting on a person's step (P13).** A planned mission whose next stage needs an unfinished person step parks in a new mission status `waiting_step`. `missions` gains three shared status sets used everywhere a status list exists today: `LIVE` (running, browsing, waiting_user, waiting_retry, waiting_step — for de-duplication in `start_mission_for`, the binding guards in `subjects.retarget`, `situations._thread_mission`, Stop, and the admin active list), `RUNNABLE` (running — the tick), and `ATTENTION` (waiting_user — triage). `projects.advance` resumes a parked mission (`waiting_step → running`) in the same write as the step change, with no polling; `planned.reconcile` at startup resumes any parked mission whose needs are already satisfied.

**Kids.** A child can create a project by hand and tick their own steps; a plan for a kid's project is approved by a parent or adult who can see it (as programs: approving is never a chat tool for a child).

## Section 4 — Where it lives

- **Phone app:** a Projects tab (a ninth tab, wired into `setView`, `applyViewVisibility`, `updateTabBar`, the role and kid-shell orders and `pwaIcon`). It lists the projects the viewer `can_see` (their own and, for a parent, their kids'); each card: title, next step, steps done (counting up). A project opens to goal and done-when, the checklist (tick your steps; see Argyle's step state and what it found), the pieces, what Argyle is doing now, and the project's conversations. **Every signed-in child sees their own projects** (P14): `own_account` is about email-and-password access and is not consulted.
- **Admin:** Projects is the first tab of the Work group (`PAGE_GROUPS['work']`), a `<section data-page-tab="projects">` on `/work`, and `/projects` serves the same component. One component (`components/projects_page.html`) serves both surfaces; only presentation differs (the kiosk-shares-logic rule).
- **Argyle:** read tools `list_projects`, `get_project` (both through `projects.can_see`, and in a channel through `situations.channel_visible` with the project as the row's subject); proposable writes `add_project_step`, `add_to_project`, `set_project_state`; `set_step_state` as a tool that a person's words can drive ("tick off demo") with the same checks as the tap. "What's next on the bathroom?", "add the tile list to the bathroom project", "pause Portuguese" all have the tap path above.
- **Routes** (`/api/projects`, `/api/projects/{id}`, `/{id}/steps`, `/{id}/steps/{step_id}`, `/{id}/steps/{step_id}/hold`, `/{id}/pieces`, `/{id}/state`) each get a rule in `services/auth.py` (`SIGNED_IN` data; writes checked in the handler with `can_act`), following the threads and missions pattern.

## Section 5 — Audience and safety

- A project's words (title, goal, done-when, step titles, what Argyle found, a hold's title) follow its audience everywhere: `projects.can_see` behind the `project` adapter; keepers (a creator a parent's later change excluded) keep their row and Stop, never the words; a channel some member may not see gets no project words (`situations.channel_visible`); speakers never speak a `private` or `parents` project to a room; the Mind's snapshot carries no `private` project and `parents` projects only for the parents' audience; the calendar projection above shows "Busy" to everyone else.
- A body-goal project is pinned private to its adult owner on every write path (Section 1).
- Argyle's self-started work is bounded by the existing daily model allowance, the mission step cap and `budget_guard`; approval gates are unchanged.
- Nothing a person could do is removed: Threads, Missions, Programs, Errands Tasks and their pages stay; "Go do this part" is replaced by work that starts itself plus Skip and Stop on it, so declining a stage is still one tap.

## Section 6 — Tests (written first by Claude; Codex implements)

- `tests/test_projects.py`: the record; `can_see`/`can_act` for each audience; a kid-owned project visible to parents; a request `member_id` never acting; lifecycle taps; Mark done offered not applied; pausing and dropping cancel running work and keep pieces.
- `tests/test_body_goal.py`: the classifier on phrases and numeric targets ("reach 70 kg", "185 lbs", "waist to 24 inches"); an adult private body goal allowed and pinned (widening refused, owner change to a minor refused); a minor's, a `parents` and a `household` body goal refused; step titles screened; programs refuse "reach 70 kg" and allow a program inside an adult's private body-goal project.
- `tests/test_subject_registry.py`: every existing kind behaves identically through the adapters (the slice 1 subject tests run unchanged as neighbours); `project` loads, titles, links and reads under its audience.
- `tests/test_project_steps.py`: dependencies (cycle and dangling refused; skipped satisfies; reopen re-blocks); an assignee cannot tick early, a parent can; idempotent ticks; the advance starts an Argyle step once; a stage-backed step done when its stage is done (research → a person's demo → more research does not deadlock); blocked on failure; Skip and Stop on a running work stage (queued rows dismissed, asks settled, a late browse result dropped); `waiting_step` resumed by the tick of a step with no polling and at startup reconcile; `LIVE` used by de-duplication and the retarget guard.
- `tests/test_project_holds.py`: the finder avoids an overlapping event, practice window and hold and says when there is no time; confirmation re-checks; the calendar shows the step title to the owner and "Busy" to a spouse for a private project, and "Busy" to the wall, the speakers and the Mind; a driver's hold makes them unavailable that date only; a non-driver's hold reaches no solver input.
- `tests/test_project_planning.py`: the preview carries the project and the person's steps; approving writes them once (concurrent approvals; a crash between writes completed by reconcile with the same ids); a thread-origin plan binds the thread and the earlier subject becomes a piece with its audience kept in `subject_history`; planning inside an existing project appends steps and creates no project; work stages start themselves; build stages still ask; created records attach as pieces.
- `tests/test_projects_audience.py`: every surface above for `private`, `parents`, `household` (detail, list, PWA tab data, record pages' "Part of", the Mind snapshot, speakers, a mixed channel, a keeper, the agent tools).
- `tests/test_projects_cards.py` (node + jsdom): the PWA tab and the admin component render one shared builder; a Playwright screenshot of each for review.
- Acceptance on the real registry, only the model faked: `tests/test_project_portuguese.py` (a plan becomes a project holding a program; "attend a first class" gets a hold; "find three meetups nearby" runs by itself and attaches what it found); `tests/test_project_bathroom.py` (an ordered checklist; demo ticked by a person starts tile research by itself; a purchase-shaped write comes back as a card); `tests/test_project_kid.py` (Kate's "learn to ride a bike", seen by her parents, ticked by her); `tests/test_project_private.py` (an adult's private body-goal project invisible to their spouse on every surface, the calendar showing "Busy").

## Out of scope (later slices)

Reviews and check-ins with dates, replies and schedules (slice B, on the wake engine); measures, their sources and thresholds, including weight (slice C); templates, a decisions list, materials sourcing and budgets (slice D); steps on the Errands Tasks tab, the wall and the digest (a later, audience-aware slice); outside helpers owning steps.

## Build split (the user's standing rule)

Claude writes every task's tests first; Codex implements each task via `codex:codex-rescue`; Claude reviews the diff, reruns the gate, updates `system_capabilities.md`, bumps `config.yaml` and commits. Codex reviewed this spec adversarially (P1–P14 folded in) and reviews the whole branch at the end.

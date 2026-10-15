# Projects front door — design

**Date:** 2026-10-15. **Status:** APPROVED by the user 2026-10-15. Slice 1 BUILT v2.499.518 (plan `docs/superpowers/plans/2026-10-15-projects-front-door-slice1.md`); slices 2 and 3 pending. One ruling made while building slice 1 amends §1: a wrapper project's audience is `parents` (household for voice), not `private`, and a wrapper is seen only by someone who may see its record now (§5: the migration never changes who can see a record). **Builds on:** `2026-10-15-projects-core-design.md` (the project record, steps, holds, audience; slice A, built v2.499.500–.513), `2026-10-14-planned-missions-design.md` (interview, plan, stages), `2026-10-14-mission-subject-resolver-design.md` (subjects and binding). **Input:** the parity inventory `2026-10-15-projects-front-door-inventory.md`, which lists every capability of the Threads, Missions and Programs pages and their phone, wall and house surfaces. **Supersedes:** Decision 7 of the core spec ("a one-off stays a plain mission").

## Problem

The user's direction (2026-10-15, after slice A shipped): "I am expecting a project proposal for pretty much everything and then programs, threads, missions fall out of that." "Anything that falls under threads, missions, or programs should be a project ... One concept. One place to look. Simple." Direct actions ("assign Grandma to drive Barney to soccer tomorrow") stay instant.

Today three concepts share the work: a thread (a conversation with someone outside), a mission (Argyle's working session), a program (a practice plan). Each has its own page, its own card shape and its own chat tool, and the user's October feedback named Threads versus Missions as confusing. The reported bug that triggered this spec: "I want to learn Brazilian Portuguese" in the Argyle DM only proposed a program, because `propose_program`'s description cites "I want to learn guitar", `start_mission_for` is described for outside-world errands, the router never routes a goal to a planned mission, and no chat tool starts a project. The acceptance test started the mission directly, so chat routing was never exercised.

## Decisions (the user's, 2026-10-15)

1. **One concept.** Everything that was a thread, a mission or a program is a piece of a project. Direct schedule and record changes stay instant.
2. **The project card comes first in chat.** Argyle creates the project at once and shows its card; the interview and the plan run inside the project. Undo is one tap ("Not a project"). Chosen over a proposal that needs a Start tap (two taps before anything happens) and over folding the project into the plan approval (no project exists while the interview runs).
3. **One chat tool, `start_project`.** `start_mission_for`, `propose_program` and `create_thread` leave the chat declaration list and stay only in the stage contract for the planner. Chosen over wrapping server-side behind the three tools (the model keeps picking `propose_program` for "learn X") and over a deterministic classifier before the router (fragile).
4. **Every existing thread, mission and program is wrapped**, one project each (a thread with its missions; closed rows into done or dropped projects, a change after review), and every new one is adopted at creation: no thread, mission or program exists outside a project.
5. **One Projects page opens a project detail page** (as Trips opens a Trip), pieces as cards, a piece opening in a sheet: a record sheet styled on the settings drawer on the admin pages, the action sheet on the phone. Lessons still open in the lesson player.
6. **Threads, Missions and Programs pages retire only at parity**: every row of the inventory lives in a piece sheet or the Projects drawer, proven by a test, before the redirects ship. Old links redirect to the project with the sheet open.
7. **Mail intake and the Mind propose a project**, never a thread. "Propose a program" exists only as New project → a program if the plan warrants one, or Add a piece → Program.
8. Kids' practice and session cards on Today, the wall Programs tile and the house books stay where they are; only their taps change destination.

## Changes after the Codex adversarial review (for the user's attention)

Nine findings, all verified against the code and folded in below. Two change the design as approved in conversation:

- **Closed records are wrapped too.** The migration wraps every thread, mission and program, closed ones into done or dropped projects, so the invariant is strict (no record exists outside a project) and old history stays reachable through the redirects (a terminal mission can still hold a booking to verify, `missions.verify_open`). Previously: open rows only.
- **A child's project is created but not planned by the child.** The hand path and the plan engine refuse child planning (`main.py` project_plan, `planned.answer_plan`); a child's `start_project` makes the project and its card, and a parent plans it from Needs you. Previously the spec implied the interview ran for the child.

The rest: the project is bound before adoption (launch takes the project); dedupe is scoped to owner and subject and spoken-safe for voice; a keeper's mission and any record whose project a viewer may not see opens in a standalone sheet; project focus resolves to its live mission; the Mind proposes through the action-proposal rail with `start_project` allowlisted; New thread and Launch work survive inside Add a piece.

## Section 1 — The invariant and the start

### The invariant

Every thread, mission and program row carries `project_id`. One helper sets it, `projects.adopt(kind, record_id, actor)`:

- It first looks for the project the record already belongs to: a mission whose subject is a project; a thread-origin mission's thread's project; a thread or program already attached as a piece of a project (`pieces`); a planned mission whose approved plan created a project.
- Otherwise it creates a project from the record (state `active` for a live record, else following the record as the migration paragraph says): title from the thread title, the mission goal (80 characters) or the program aim; goal = the thread goal, mission goal or program aim; owner = the thread owner, the mission creator (the parent of record for a voice-started mission), the program's member; audience = `private` for an adult owner, `parents` for a child owner, `household` when started by voice. The body-goal rule applies to the title and goal exactly as in the core spec (adult only, pinned private). The record becomes the project's first piece.
- It is idempotent: a record with a `project_id` whose project exists is returned unchanged. A record whose project was dropped is re-adopted into a new project only by an explicit act (reopen), never by the sweep.

**Bind before adopt.** Today `POST /api/projects/{id}/plan` and `projects.advance` launch a mission and bind its subject afterwards; adopting inside `launch` would wrap it in a wrong project first and idempotence would keep the wrong one. So `missions.launch` (and `threads.create`, `programs.create`) take an explicit `project_id`; every caller that knows the project passes it (the plan route, `advance`, the planner's build rows, `start_project`, Work this on a thread sheet), and `adopt` runs after the subject is bound. A thread-origin mission is adopted into its thread's project, and `missions.subject_of` keeps reading the thread's subject (binding semantics unchanged); planning, cancellation and redirects read `project_id`. The planner's rows pass the plan's project, so a program a plan proposes inside the Portuguese project is a piece of that project, not a new one.

**Migration** runs once at startup after storage opens (`projects.adopt_existing`): **every** thread, mission and program, closed ones included. A thread and its missions become one project; the project's state follows the record (an open or live row → `active`; done → `done`; dropped, stopped or failed → `dropped`; a program proposal → `active`), so the overview's folded lane holds old history and a terminal mission whose booking still needs "It went through / did not" (`missions.verify_open`) is still reachable through its redirect. The pass is idempotent and recorded in app state (`projects_adopted_rev`) so it never re-runs in full; a record created later is adopted at creation. The invariant is therefore strict: no thread, mission or program exists without a project.

### `start_project`

Declared to the chat model as the one tool for anything that takes steps, time or people outside the family:

- `start_project(goal, title?, for_member_name?)`. Parent or adult for anyone; anyone for themselves; voice as the parent of record (household audience). A child may start their own project (core spec: everyone owns projects). In a channel some member may not see the result, the tool is refused with no words, like the project write tools today; the person's own command in a private chat runs directly.
- **Dedupe:** a live project (active or paused) is a duplicate only when it has the **same owner** (the resolved `for_member_name`, else the caller), the **same subject** when one was resolved through `find_in_chauffeur`, and the same intent words (`_intent_words`, the planned-missions helper), and the caller may see it; for voice, the candidate must also be `spoken_safe` and household-audience, as `start_mission_for` filters today, and in a channel every recipient must be able to see it. A match is named, not doubled: "That's already under way: \"Learn Portuguese\"." and the focus moves to that project. Barney's Portuguese project never blocks Kate's. Two matches: Argyle asks which rather than suppressing creation.
- **Creates the project** through `projects.create` (the body-goal rule, audience defaults), **posts the project card** (below), then, for a parent or adult caller, **launches the planning mission** bound to the project (`subject_kind='project'`, `project_id` passed to launch, as `POST /api/projects/{id}/plan` does today) so the interview runs inside it. The tool returns the project id and the mission id; the card and the plan card share one conversation.
- **A child's `start_project`** creates the project and its card and launches nothing: the card says "Ask a parent to plan it with Argyle", and the project appears in each parent's Needs you lane as "Kate's project needs a plan" with Plan it with Argyle. The parent launches the planning mission, so the parent is its creator, answers the interview and approves; Kate ticks her steps as the core spec allows. `planned.answer_plan`, `missions.answer` and the plan route keep refusing children.
- Missions off, no paid key, or the daily launch cap reached: the project is still created (it is the person's record; it needs no model) and the card says planning is off and why ("Missions are off (Projects settings)"); "Plan it with Argyle" on the project works once they are on.
- **Approval inside a started project appends steps** (the planner's "inside an existing project omit the proposal and append steps" branch is the only branch reached from chat now). The plan card never proposes a project when one already exists. A planning mission started from the project page (hand path) behaves identically.
- **Focus.** `triage` accepts a focus of kind `project` (`situations.KINDS` gains `project`; `situations.load` and `_alive` read the project row, alive while active or paused). A correction in words while a project is the focus (`act_on_situation` with verb `answer`) resolves to the project's single live mission; with two live missions Argyle asks which; with none, a new goal said on the focused project is a new planning mission **inside that project** (the shipped continuation rule, "get available times and pricing" after the first mission finished, now at project level), never a new project.

**Router guidance** (`services/agent_router.py`) is rewritten around one rule: a request that changes the schedule or a record now (reassign a driver, add a list item, send a message, claim a chore, add an errand) is a direct tool or `propose_family_action`; a request that takes steps, time, research, a company, a teacher or a practice plan is `start_project`, with the thing we are talking about passed through `find_in_chauffeur` as before. The ARGYLE ACTS IN THE WORLD paragraph names `start_project` where it named `start_mission_for`. Voice keeps "A household request can start a project" and the release/approval rules unchanged. A correction about work already running on the project we are talking about stays `act_on_situation` with verb `answer`.

**The chat tools that leave the declaration list:** `start_mission_for`, `propose_program`, `create_thread`. Their functions stay (the stage contract, `planned.CONTRACT`, calls them; tests call them), so nothing that a plan can build changes. `tests/test_registry_parity.py` is updated to the new declared set.

### The project card

A new chat card kind `project` (one builder in `services/projects.py`, rendered by the DM renderer in `app.html` beside `mission_ask`, and by the admin chat widget): title, goal in the person's words, owner, an audience chip (Private / Parents / Household), the state. Options, as situation options so they are the same on the card and in words:

- **Rename** (prompts for a title; `promptInput`, never a browser dialog).
- **Make private / Share with parents / Share with the household** (the audience ladder the core spec allows the owner; a body goal cannot leave private; a child's cannot become household).
- **Not a project**: drops the project and stops its planning mission in one write (`projects.set_state('dropped')`, which already stops work); Argyle's reply says what to do instead ("Dropped. Tell me the one thing you want done and I'll do it directly.").

The card follows its audience like every project word (core spec Section 5): in a channel some member may not see the project, no card and no words.

## Section 2 — The Projects page and the project detail

### Overview

`/projects`, the first tab of the admin Work group, and the phone Projects tab; one shared component as today (`components/projects_page.html`). Lanes, in this order:

- **Needs you**: a question from Argyle, a plan or stage to approve, a release or booking to confirm, a reply from outside waiting on you, a program proposal to approve.
- **Moving**: Argyle working, or your next step is ready.
- **Waiting**: on someone outside (a thread waiting on them), or a program whose next session is not yet due.
- **Paused**.
- **Done & dropped**, folded, with "Show closed" remembered per device (localStorage, as the Threads page does today).

A card shows title, owner, the one next step in words (the project's `next_step`, else the most pressing piece's next step), N of M steps, and a state chip. A lane is computed in `projects.lane(view)` from the project's state, its steps and its pieces' situations; it is one function so the phone and the admin page agree.

**New project** opens the existing form (title, goal, done-when, owner, audience, target). It has no program fields: whether a program is a piece is the plan's decision, so the hand path for "propose a program" is New project → Plan it with Argyle, or, inside the detail, Add a piece → Program (the old propose form in a sheet).

**Needs you also lists a child's unplanned project** for each parent ("Kate's project needs a plan", Plan it with Argyle), and, for a mission keeper, **Your work elsewhere**: missions the viewer created whose project they may not see, drawn with the keeper projection (progress and Stop, no words), opening the standalone sheet below.

### Detail

`projects?id=<project>` opens the detail in the same component (the inline open is replaced; `subjects.link('project', id)` already points here). On the phone the Projects tab pushes a detail view with Back; on the admin page the URL changes.

Order on the page: the header (goal, done-when, owner, audience, target, Edit, Pause/Resume/Done/Drop as built); the checklist exactly as built (tick, Argyle's steps with what they found, Skip/Stop, Put it on the calendar); then **piece cards**, one per piece, drawn by the piece's adapter: a thread card (next step, who is on the other end, a stalled chip, the situation options), a mission card (the situation card as today), a program card (next session, progress, Approve when proposed), a trip, occasion or list card (title and a link to its own page, unchanged). The Conversations list goes: every thread and mission is a piece now. **Plan it with Argyle** stays. **Add a piece** offers: an existing record (the picker from `static/project_links.js`); **New thread** (the Threads page form: title, goal, project|vendor kind, owner, contact or name and email, first next action and date); **Launch work** (the Missions page form: goal and tier Pro|Flash, so a Flash-only household keeps its launch path and a vendor thread can be opened with planning off); **New program** (the propose form). Each creates the record with this project's id (bind before adopt).

### Sheets

A piece card opens its sheet, and `projects?id=<project>&piece=<kind>:<id>` deep-links to it open:

- **Admin:** a right-side record sheet, a new shared builder `components/record_sheet.html` + `static/record_sheet.js`, framed like the settings drawer (same width, header, close, scroll inside, fixed positioning) but not the drawer: the drawer is for the page's settings only (design guide rule). The design guide gains the record sheet as a named pattern.
- **Phone:** the `_pwaModal` action sheet.
- **Standalone:** `projects?piece=<kind>:<id>` with no project id opens the sheet alone, for a viewer who may see the record but not its project: a mission keeper (`planned.is_keeper`) gets the keeper projection (progress, Stop, no words), exactly the neutral Missions page card they act on today. The project route's 404 for an invisible project is untouched; the standalone sheet checks the record's own visibility (`situations.can_see`) and never the project's words.

The sheet body is the record's own full component moved out of its page, so the capability set is the page's:

- **Thread sheet:** goal, next step, counterparty, owner, kind; history with photos and "Argyle read it as…"; the missions opened from the thread with their transcripts; Draft, edit, Send (confirm with `promptConfirm`), Redraft; Add note; Advance; Research (answer and sources); Photo; Work this (a planning mission inside this project, not a bare mission); Edit; Done/Drop; Delete (cascades missions). The asks ledger (said yes/no/Sent it).
- **Mission sheet:** tier, started, finished, error; the transcript steps; answer/steer; the plan stepper and every stage option; Drop; OK; Delete; "Full transcript" opens `mission_transcript` as today (screenshots, raw JSON stay there).
- **Program sheet (full height):** plan source tier, Why this one / Also considered, progress, phase steps and rotation, Next time, Done when, the lesson ladder with Open the lesson (the player), the lesson editor (play, edit beats, reorder, delete, add up to 12, Save, Regenerate), Another session / Move on, Reached it, Tonight windows and Start session, the footprint and "Not these times?" editor, Plan without the book, Approve — claim this time, Edit, Look again, Dismiss, Log a session, Pause, Resume, Finished, Re-shape the week, Drop.

Permissions are unchanged: thread and mission writes parent or adult, program writes owner or parent, approve parent only; a child sees their own program sheet with the controls they hold today on the phone.

**Parity rule:** every row of the inventory maps to a sheet control, a project-page control or a drawer setting. The implementation plan carries that table, one test assertion per row, and the redirects (Section 3) ship only when it is green.

## Section 3 — Retiring Threads, Missions and Programs

- **Redirects.** `/threads`, `/missions`, `/programs`, `work?tab=threads`, `work?tab=missions` and `rhythms?tab=programs` redirect: with `?id=` to `projects?id=<project>&piece=<kind>:<id>` (the project found through the record's `project_id`, which every record has after the migration; an unknown id lands on `projects`), and the page itself falls back to the standalone sheet when the viewer may see the record but not the project (a keeper); without an id to `projects`; `/programs` and `rhythms?tab=programs` to `projects?lane=programs`, a filter chip on the overview that shows the projects holding a program, so "all programs" still has one place. The settings-index anchors follow the drawer move below.
- **Navigation.** The Threads and Missions tabs leave the Work group (Projects, Intake, Mind remain); Programs leaves the Rhythms group (Chores, Routines remain). The kiosk hide list adds `projects`. `services/auth.py` keeps `/projects` ANYONE (the shell) and `/api/projects*` SIGNED_IN; the retired page routes keep their rules until they are redirects, then the redirect rule is ANYONE.
- **Settings** move into the Projects drawer as three sections keeping their anchors so the settings index and old anchors still land: **Argyle's work** (`missions-settings`, `browse` including Check the network, `contact-card`), **Threads** (`threads-settings`: `thread_stall_days`), **Programs** (`programs-settings`, `lessons` including Write lessons now with its per-slot Play, `programs-pacing`). The registry `page=` fields repoint to `work?tab=projects`.
- **Deep links** repoint through the adapters: `subjects.link` for thread, mission and program returns `projects?id=<project>&piece=<kind>:<id>`; the "Argyle: …" lines on occasions and trips, `static/study.js`, the About chip and the project page's own links follow; the plain-text "/missions" in `services/watchers.py` says "the Projects page".
- **Phone and wall surfaces stay** (Decision 8): the House tab Threads section, More › My programs, the program and session cards on Today and Family, the wall Programs tile, the house books and the Study binder keep their place and their domain logic (kiosk shares logic); any tap that opened `threads` or `programs` opens the project sheet instead. `renderPracticeNow`, built but never rendered, is left as it is (out of scope).
- **The mission transcript page stays** as a deep view, gated as today.

## Section 4 — Intake and the Mind propose projects

- **The Mind.** The prompt clause "You may also propose starting a thread when you spot real outside-facing work with no home yet" becomes "propose a project". The bind step runs the router propose-only as today, and that rail refuses every acting tool (`PROPOSE_ONLY_TOOLS`), so `start_project` is NOT reached there; instead `start_project` joins the action-proposal allowlist (`chat_actions.ADMIN_ACTIONS`) as a proposable action with an execution handler that runs `start_project` as the **accepting** parent (goal in the insight's words, owner the person named). The bind step therefore yields an action-proposal card, the parent's Approve creates the project. Direct execution stays forbidden on the propose-only rail. Dismissal identity stays structural (subject + kind); a dismissed project proposal for the same refs is not re-proposed.
- **Mail intake.** A new proposal kind `project` beside `event` and `task`: the extract step may return it for a message that is outside-facing work with no event in it (a vendor's estimate to answer, a school asking for a form, a renewal to arrange), with the message's gist as the goal. It lands in the same proposals queue the parent reads; Accept runs `start_project` as the accepting parent with the mail attached as the first thread piece (a thread whose history holds the message), Skip dismisses. Events and supplies proposals are unchanged; a message that is both an event and work yields both rows as today's event-plus-supplies does.
- **Hand paths** exist already: New project, and Add a piece → Thread from a mail on the Intake page.

## Section 5 — Audience and safety

- A project's audience governs its pieces' words everywhere (core spec Section 5). Adoption only **narrows**: a record adopted into a project is shown to someone outside the project's audience by the keeper rules (progress only, no words), never widened. A wrapped program for a child gets a `parents` audience with the child as owner, so the child still sees their own.
- `start_project` in a channel some member may not see the result: refused with no words; the project card and the plan card never appear there.
- Voice: `start_project` as the parent of record, `household` audience, a spoken-safe card read back as "Started a project: <title>"; approvals stay on the phone as today.
- The migration never changes who can see a record: a thread visible to its owner and parents today becomes a project with the same audience; a mission's keeper keeps the row and Stop.
- Every new surface that carries a project's words (the card, the lanes, the sheets, the redirects, the intake queue) is covered by an audience test before it ships (the lesson of slices 1 and 2).

## Section 6 — Tests (written first by Claude; the split below)

- `tests/test_front_door_chat.py`: through the real router with a stub model that sees the declared tools — "I want to learn Brazilian Portuguese" picks `start_project` (never `propose_program`); the project exists and its card is the first message; the planning mission is bound to it and carries its `project_id`; approval appends steps and proposes no second project. "Get the dishwasher fixed" also picks `start_project`. "Assign Grandma to drive Barney to soccer tomorrow" is `propose_family_action`, no project. Dedupe names the live project for the same owner and subject only (Barney's Portuguese never blocks Kate's; two matches ask); a household voice request never names a parent's private project. Not a project drops the project and stops the mission in one write. Missions off still creates the project with the right card line. A child's start creates the project, launches nothing, and the parent's Needs you offers Plan it with Argyle. A correction with a project focus reaches its live mission; a new goal on a finished project's focus plans inside it.
- `tests/test_project_adopt.py`: every create path leaves a `project_id`; the plan route and `advance` bind the project before adoption (one project, never two); a thread-origin mission joins its thread's project and `subject_of` still reads the thread; a planner row inside a project joins that project; migration wraps a thread and its missions into one project, a kid's program into a parents project, closed rows into done or dropped projects (a terminal mission with `verify_open` still reachable), and is idempotent; owners and audiences as Section 1.
- `tests/test_keeper_sheet.py`: a keeper's redirected mission link opens the standalone sheet with progress and Stop and no project words; the keeper's Your work elsewhere row; the project route still 404s for them.
- `tests/test_projects_lanes.py`: `projects.lane` for each lane case; the phone and admin render the same lane.
- `tests/test_record_sheet_live.py` (a real browser, throwaway data, the parity table): thread, mission and program sheets reach every control in the inventory; deep link `&piece=` opens the sheet; phone action sheet for the same records.
- `tests/test_retire_redirects.py`: every old link form in the inventory lands on the right project and sheet, including a pre-migration closed thread, a terminal mission and a finished program; the registry pages and anchors resolve; the nav groups and kiosk hide list; New thread, Launch work (tier) and New program inside Add a piece are in the parity table.
- `tests/test_front_door_audience.py`: the card, lanes, sheets and intake rows under private, parents and household projects; the channel refusal; voice.
- `tests/test_intake_mind_projects.py`: the Mind's bind step yields a `start_project` action proposal (the propose-only rail still refuses the tool directly), Approve creates the project as the accepting parent; the intake `project` kind, Accept and Skip.
- Updated: `test_registry_parity.py` (declared set), `test_project_portuguese.py` (through chat, not a direct launch), the planned-missions card tests for the new first message.

## Out of scope

Reviews and measures (slices B and C of the core spec); a people model; typed replies under a Chauffeur ask card; media GC; `renderPracticeNow`; wall tiles for threads or missions; outside helpers owning steps.

## Slices (each its own implementation plan)

1. **Chat front door and the invariant:** Sections 1 and 5 (adopt, migration, `start_project`, the card, router guidance, the declared set).
2. **Detail page, piece sheets, lanes, settings move, redirects:** Sections 2 and 3. Retirement ships only when the parity test is green.
3. **Intake and the Mind:** Section 4.

## Build split (the user's standing rule)

Codex adversarial-reviews this spec before any plan. For each slice Claude writes the failing tests first. Codex (via `codex:rescue`) takes `projects.adopt` and the migration, the redirects, the registry repoint and the link repoint through the adapters. Claude builds the router guidance, the chat card, the record sheet builder and the templates. Whoever did not write the code reviews it; Claude runs the gate tests, updates `system_capabilities.md`, bumps and commits.

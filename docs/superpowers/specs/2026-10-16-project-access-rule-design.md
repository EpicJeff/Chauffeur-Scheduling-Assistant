# The project access rule — design

**Status:** design approved section by section by the user on 2026-10-16; this written spec awaits Codex adversarial review, then the user's review.
**Follows:** Projects front door slice 2 (v2.499.520), which shipped with the rule backed out. Core spec §5 (`2026-10-15-projects-core-design.md`) said a project's audience governs its pieces; slice 2 made it possible to put any thread, mission or program inside a private project, and three patch rounds (c697645e, 5724de1e, branch `privacy-round3-wip`) each fixed the spots a review named and broke others. This spec decides every case once.

## 1. The promise

A thread, mission or program inside a **private** or **parents** project is seen only by the project's audience, the record's own person, and — when that person is a child — the child's active parents. That holds everywhere: pages and by-id links, Argyle in any channel, voice, the wall and other shared screens, the calendar, the Mind, and every nudge or finding. Shared screens and the Mind treat the record as not there; its calendar time reads "Busy". (User, 2026-10-16: "Full secrecy", chosen over "hidden from people, house keeps it" and "card-only, labelled".)

**Today's model, which this layers on and does not replace.** Each record kind has its own rule. Threads and missions are open to parents and adults (`situations._can_see_base`, `WRITE_ROLES`), narrowed by their subjects (`subjects.subject_records`: a private occasion, a parents-only trip, a project named as subject, a live mission's proposed project), with the record's owner exempt for the row itself (`situations.can_see`). Programs are open to parents and adults and otherwise to their own member (`subjects._program_visible`, `_program_scope_id`). A project's own visibility is `projects.can_see` (owner; household = everyone active; parents = owner + active parents; private = owner, plus active parents when the owner is a child; a wrapper also needs its record visible now).

**Why the patch rounds failed.** Not the rule. Three gaps under it: (1) about twenty readers check only the viewer's role or nothing (by-id mission and thread actions, the wall's program reads, Study, the calendar feed, `/api/asks`, action proposals); (2) readers with no person — wall, speaker, Mind, registry, a mission's own reads — passed `viewer=None`, which had no defined meaning against `projects.can_see`; (3) "the record's own person" was confused with "a parent of a child owner", which broke gift secrecy (I1) and the keeper's own DM (I2).

## 2. Terms

- **Containing project (P).** `storage.get_project(row['project_id'])` when the row has a `project_id` and that project has no `wrapped_from`. A wrapper adds nothing (its visibility already defers to the record, `projects._wrapped_visible`). No `project_id`, or a missing project, means no P.
- **Restricted.** P exists and `P['audience'] in ('private', 'parents')`. A household P is not restricted.
- **Keeper.** The record's own person: thread `owner_member_id`, mission `created_by`, program `member_id`. The id must be non-empty and the member active (`projects._active`). An empty owner never matches an empty viewer id (closes M1, `None == None`).
- **Keeper's parents.** Active parents (`role == 'parent'`, not a child, `_active`) when the keeper is a child (`projects._child`). They count **only** in the project layer (§3), never in subject audiences (I1).
- **HOUSE.** A named viewer constant, `{'id': None, 'role': 'adult', 'house': True}`, used by every reader that has no person: the wall and panels, speakers, the Mind snapshot, registry reads, and a mission's generic reads. `HOUSE_PARENT` (`role: 'parent'`) is the existing parents-only variant `missions.read_viewer` already returns for a transcript whose subjects are parents-only. Nothing passes `None` as a viewer any more.

## 3. The rule

`access.record_visible(kind, row, viewer) = base(kind, row, viewer) and project_layer(kind, row, viewer)`

- **base** is today's rule, unchanged: `situations.can_see` for threads and missions (subjects included, the owner's row exemption included, with the owner match requiring a non-empty viewer id), the program adapter for programs.
- **project_layer** is true when any of:
  1. there is no restricted P;
  2. the viewer is the keeper;
  3. the viewer is an active parent of a child keeper;
  4. `projects.can_see(P, viewer)`.

  HOUSE and HOUSE_PARENT pass only through (1).
- Viewers must be active members or HOUSE/HOUSE_PARENT; a disabled or archived member sees nothing (M2).

**What a keeper sees when they cannot see P.**
- Mission: the existing keeper projection (`planned.keeper_view`; `situations.view` keeper branch): metadata and their own options (OK, Delete, steer), no transcript, no plan words, no cached status note. `planned.is_keeper` becomes "can see the row but not everything around it", where "around it" now includes P.
- Thread: the existing thread keeper redaction in `situations.view` (no cached notes or suggestions, mission history reduced to timestamps), triggered by P as well as by subjects.
- Program: the whole program. It is their own practice and they need its lessons; they do not see the project card.

`access.record_actable(kind, row, viewer, verb) = record_visible(...) and the action's existing role check`, and a keeper projection allows only the keeper's options (the existing `situations.view` filter).

**Kinds are registered**, so trips, occasions and lists can become pieces later without touching the rule: `access.register(kind, keeper_field, base_check, keeper_projection=None)`. This slice registers thread, mission and program only.

## 4. Surfaces

Every reader belongs to exactly one class. "Hidden" means, per class: a 404 shaped like a missing record (never 403 — existence is not disclosed); the row dropped from a list or search; Argyle answering as if nothing matched; "Busy" on the calendar; no finding and no DM.

1. **Signed-in pages and by-id routes (read and act).** `record_visible` / `record_actable` with the signed-in person. Lists and search filter rows. Includes `/api/projects/for/{kind}/{id}`, both deep-link forms (`projects?piece=` and `projects?id=…&piece=`), the record sheet and the phone's piece sheet, every by-id mission action (answer, release, submit, verify, delete, drop, ack, shots, plan answers, launch with `origin_ref`), every by-id thread action (PATCH, note, advance, close, delete, photo, draft, send, research), program approve and every gated program write, `/api/action-proposals` and its act route, `/api/asks` with an option, `/api/subjects/search`, `/api/subjects/{kind}/{sid}/situations`. An admin surface with no resolved person uses HOUSE, not `parent_of_record`. That fixes the two minor id-less admin routes, plus `/api/missions/admin`, `/api/missions/{id}`, `/api/situations`, `/api/subjects/{kind}/{sid}/situations`, `/api/action-proposals` and `/api/findings` (which today lets an unresolved caller through). **Ruling to verify in review:** someone who reaches the admin pages through HA ingress without a Chauffeur sign-in sees restricted pieces only after signing in. A restricted piece is never shown to "whoever is at the admin page". `/api/threads` also applies `record_visible` to every row, not only to rows that have a subject. Today a signed-in child receives every unbound thread; that is pre-existing, and it is fixed here because the base rule says otherwise. The DM approve cards' program actions (`chat_actions` `log_program_session`, `reshape_program`) use `record_actable` for the approver, not `requires_admin` alone.
2. **Argyle in a private DM.** The speaker is the viewer. Argyle reached with no member (the wall's chat, the admin widget without a sign-in) reads as HOUSE. Today `agent_router` substitutes `parent_of_record` for situation and project tools there, which would show a restricted piece on a shared screen. Registry calls with no actor (`_REGISTRY_READER`) are HOUSE, and `_registry_parent` writes are HOUSE_PARENT.
3. **Argyle in a group channel.** `access.channel_visible(kind, row, focus_key)`: a record passes when every human in the channel passes `record_visible`, a keeper (and a child keeper's parents) passing the project layer as in §3 (I2). Records with no restricted P keep today's channel rule (every human may read its subjects). Title matching (`_match_thread`, `_match_program`, `launch_mission(thread_title=…)`, `start_mission_for`'s "already under way") searches visible records only; when nothing visible matches, the old fallback stands (a plain mission with no thread, M5) and a hidden title is never named.
4. **A mission's own reads (the engine).** `access.mission_reader(mission)` reads what `missions.read_viewer` reads today (HOUSE or HOUSE_PARENT), **plus** the pieces of the mission's own P, **plus** the mission's own origin thread (`origin_ref` of a thread-origin mission, I6). Never the creator's other private records: those would leak into a transcript that a wider audience can read. `missions._finder` (subject context authorised as the creator) is unchanged for the subject itself and does not widen to other records.
5. **Voice.** HOUSE plus `spoken_safe`: a speaker has a room around it, whoever asked. A voice approval of an ask on a restricted record is refused aloud ("That one's private — open it on your phone") and changes nothing. `voice_approval` uses `record_visible(…, HOUSE)` for the spoken check.
6. **Shared screens** — the wall and panels, House, the Study board and binders (`study._board`, `study._binders`), board tiles, lesson scenes and lesson help, the practice session (`house_programs.session`, `house_programs.objects`), celebrations (`programs` celebrations), home-board and House attention counts. `access.shared_screen_visible(kind, row, viewer) = record_visible(kind, row, HOUSE) or (viewer is a person and record_visible(kind, row, viewer))`: a signed-in child never sees less than the anonymous wall (I4), and a restricted piece is absent for HOUSE. Counts follow the same rule.
7. **Calendar and practice windows.** A restricted program's practice window is neutral like a project hold (`_project_hold_events`): title "Busy", no steps, cached colour kept. `/api/practice-windows` and the calendar feed (`get_calendar_events` and every consumer: wall, speaker, Mind, Argyle's calendar tools) carry the neutral copy. `/api/schedule` restores the words for a signed-in viewer who passes `record_visible`, **only** when the cached copy is the neutral one, computing restore data at most once per day per request, and keeping the cached colour and every other field — only title and steps come back (I5).
8. **Signals** — watchers, findings, the Mind, DMs.
   - The Mind snapshot reads as HOUSE.
   - A record inside a restricted P never makes a household Finding.
   - A signal that would have DM'd under the household path is DM'd privately instead: to the keeper; for a `parents` P, to the parents who pass `record_visible`; for a child keeper, to the child and their parents as the household path would. Same `watcher_notified` dedupe. Signals that never DM on the household path (quiet thread_stall, mission_done, mission_blocked) are dropped for restricted records (M3, watcher signal policy). An item with no eligible recipient ages out — `at` is not refreshed on every sweep.
   - A record restricted **only** by its subject (an occasion, a trip) keeps today's household Finding path unchanged (I3).
   - Program drift and rebaseline findings follow the same rule.
   - A mission with no creator DMs only the parents who pass `record_visible` (`missions._dm_person`). For a restricted thread, `replies._recipients` (the owner, else all parents) and `replies.flush_pending_dms` follow the same rule.
   - Practice pushes (`programs.due_practice_pushes`, sent to the owner's driver) carry the program's words only when the recipient passes `record_visible`. Otherwise they say a neutral "Practice time", with no title or steps.
   - The household briefing (`family_digest.build_household_briefing`) reads the cached schedule, which already carries the neutral copy (class 7). It must not list a neutral practice window or a hold as an uncovered event.
   - Aggregate counts that name nothing (`vitals.measure_day` open-thread and session counts) stay INTERNAL. They feed the family's own baseline and never name a record.

**Internal readers stay raw**: the solver, migrations, `projects.adopt`, storage itself, and any job that acts for everyone and shows nothing. They are listed in the register as INTERNAL so the decision is visible.

## 5. Where it lives

- **`services/access.py`** (new): the kind table and `register`; `HOUSE`, `HOUSE_PARENT`; `containing_project(row)` (memoised per request through a `contextvars.ContextVar` cache set by a middleware and cleared after the response; outside a request it reads through); `keeper_of(kind, row)`; `record_visible`; `record_actable`; `channel_visible`; `mission_reader`; `shared_screen_visible`; `READERS`.
- Existing helpers become thin calls into it, with their callers unchanged where possible: `situations.channel_visible` (records), `missions.read_viewer` / the engine's thread matching, `subjects.visible`'s program branch for person viewers, `planned.is_keeper`, the thread keeper test in `situations.view`. The ad-hoc copies the backed-out rounds added do not come back.
- **`READERS`** is a table shaped like `auth.RULES`. One row per reader: `(id, surface_class, kinds, check)`, where `id` is `('route', METHOD, path_template)`, `('tool', name)` or `('reader', 'module.function')`, `surface_class` is one of the eight classes in §4, `INTERNAL`, or `NONE`. `NONE` is for a route whose path matches a keyword but reads no piece: the page shells, `/api/house/facades*`, trips, coverage asks, `/api/lessons/speak|wait`. and `check` names the access function it calls. The initial rows are the inventory in Appendix A.

## 6. Tests

All tests run from `chauffeur/` as plain scripts with `HA_BASE_URL` unset.

- **One fixture household** (`tests/access_fixture.py`), used by every access test. Members: Mom (parent), Dad (parent), Aunt (adult), Kate (child of Mom and Dad), Hal (helper), Pat (disabled parent). Records:
  - R1 Aunt's thread in Mom's **private** project.
  - R2 Aunt's mission in Mom's private project.
  - R3 Kate's program in Mom's private project.
  - R4 Mom's thread in Mom's **parents** project.
  - R5 Dad's thread and Kate's program in a **household** project.
  - R6 Kate's thread whose subject is a private occasion shared with Kate and Mom, no project.
  - R7 R6's twin inside Mom's private project.
  - R8 an unowned thread whose subject is a parents-only occasion.
  - R9 Mom's mission in Mom's private project whose origin thread is Mom's thread in the same project; and Mom's mission in the household project naming R1 by title.

  Viewers: Mom, Dad, Aunt, Kate, Hal, Pat, HOUSE, the family channel, a Mom+Aunt group channel.
- **`tests/test_access_matrix.py`.** For every `READERS` row and every viewer, run the reader for real — a TestClient request with that person's token, a tool handler with that acting member and focus, a function call — and assert seen/hidden and acted/refused against the table in §7. Cells come from §7 and only §7.
- **`tests/test_access_register.py`.** Enumerates `main.app.routes`: any route whose path names threads, missions, programs, situations, asks, action-proposals, projects, practice, lesson, study, house, schedule, calendar or subjects must have a `READERS` row. Enumerates the Argyle registry: any tool whose name names thread, mission, program, project, situation, ask, lesson or practice must have a row. A new reader without a row fails, the way an unclassified route fails `test_auth`.
- **The rounds' regressions are cells**, each named after its finding: B1, B2, I1–I6, M1–M5, the two minor id-less routes.
- **Live:** the backed-out browser scenario returns — a private piece through both deep-link forms on the admin record sheet and on the phone's piece sheet discloses nothing to Dad, and opens for Mom.

## 7. The matrix (expected outcomes)

✓ seen in full · K keeper projection · ✗ hidden · B "Busy" on calendar surfaces. Columns are viewers in a signed-in page, private DM or by-id route (classes 1–2). Rows R1–R8 from §6.

| | Mom | Dad | Aunt | Kate | Hal | Pat | HOUSE |
|---|---|---|---|---|---|---|---|
| R1 Aunt's thread, Mom's private P | ✓ | ✗ | K | ✗ | ✗ | ✗ | ✗ |
| R2 Aunt's mission, Mom's private P | ✓ | ✗ | K | ✗ | ✗ | ✗ | ✗ |
| R3 Kate's program, Mom's private P | ✓ | ✓ (parent of child keeper) | ✗ | ✓ | ✗ | ✗ | ✗ / B |
| R4 Mom's thread, Mom's parents P | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| R5 Dad's thread, household P | ✓ | ✓ | ✓ | ✗ (base) | ✗ (base) | ✗ | ✓ |
| R5 Kate's program, household P | ✓ | ✓ | ✓ | ✓ | ✗ (scope) | ✗ | ✓ |
| R6 Kate's thread, Kate+Mom occasion | ✓ | ✗ (subject) | ✗ | ✓ (keeper row) | ✗ | ✗ | ✗ |
| R7 R6 inside Mom's private P | ✓ | ✗ (I1: subject still binds) | ✗ | ✓ | ✗ | ✗ | ✗ |
| R8 unowned, parents-only occasion | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ (M1) |

Per class, the differences from that table:

- **Group channels (3).** Family channel: R1–R4, R6–R8 ✗; R5 as HOUSE. Mom+Aunt channel: R1 ✓ (Mom sees P; Aunt is keeper), R2 ✓, R3 ✗ (Aunt), R4 ✗.
- **Mission engine (4).** R9's private-project mission reads its origin thread and R1-like pieces of its own P; the household-project mission's title match for R1 finds nothing and falls back to a plain draft without naming it.
- **Voice (5).** Only rows HOUSE sees and that are `spoken_safe`; a voice approval of an ask on R2 is refused aloud.
- **Shared screens (6).** HOUSE column for the anonymous wall; a signed-in person sees HOUSE ∪ their own column (Kate on the wall sees R3 and R5's program titled; Aunt sees R5, not R3).
- **Calendar (7).** R3's window: B for HOUSE, Aunt, Hal, the feed and every speaker; titled with the cached colour for Mom, Dad, Kate in `/api/schedule`.
- **Signals (8).** R1 stalled past the paging threshold: no household Finding, a DM to Aunt only; a quiet R1 stall: nothing. R4 waiting: DM to Mom and Dad. R6 and R8 (subject-only): today's household path. Pat never receives anything.
- **No-member Argyle and admin surfaces.** The wall's chat and an admin surface with no person get the HOUSE column, never the Mom column.
- **Practice push.** R3's push to Hal as driver says "Practice time" with no title; to Dad it is titled.
- **Child lists.** Kate on `GET /api/threads` sees only her own threads (R6, R7), never R5's or R8.
- **Acting.** Dad on R2 answer/release/submit/verify/delete/drop/ack: 404. Aunt on R2: OK, Delete, steer allowed; approve_plan and run_stage refused. Aunt approving R3: 404. Dad approving R3: allowed.

## 8. Build order and split (the standing Codex rule, said at approval)

1. **Claude:** `tests/access_fixture.py`, `test_access_matrix.py` (red), `test_access_register.py` (red), and `services/access.py`'s core (§3, §5) turning the base cells green.
2. **Codex, one task per surface class**, each reviewed by Claude: (a) routes and pages; (b) Argyle DM and channel tools; (c) the mission engine; (d) voice; (e) shared screens; (f) calendar and practice windows; (g) signals. Each task turns its class's cells green and adds its rows to `READERS`.
3. **Codex:** whole-branch adversarial review.
4. **Claude:** docs (`system_capabilities.md`), bump, push.

`privacy-round3-wip` is a reference implementation only, never a base. Its tests may be mined for probes.

## 9. Out of scope

Trips, occasions and lists as project pieces (the kind table has the slots). How a project's audience is chosen or changed. Kids' practice and session cards on Today (unchanged; they read as the child, class 1). Media and photo storage access.

## Appendix A — the reader inventory

From a read-only sweep of the code on 2026-10-16; line numbers are as of v2.499.520. Each entry becomes a `READERS` row. Where today's check is weaker than its class requires, "today" names it.

**Class 1: signed-in pages and by-id routes (`main.py`)**
- **Threads:** `GET /api/threads` (today: rows without a subject are unfiltered, a child included, and no viewer gets everything), `POST /api/threads`, `GET /api/threads/{id}/missions`, `PATCH /api/threads/{id}`, `POST …/note`, `…/advance`, `DELETE /api/threads/{id}`, `…/close`, `…/draft` (sends the thread to the LLM), `…/photo`, `…/send` (sends mail), `…/research`. All are role-only today except `/missions`.
- **Missions:** `GET /api/missions/admin` and `GET /api/missions/{id}` (no viewer means unfiltered), `POST /api/missions/launch` (`origin_ref` unchecked), `…/proposals/{pid}/act`, `GET …/shots/{name}`, `…/release`, `…/submit`, `…/verify`, `…/plan/answers`, `…/answer`, `DELETE /api/missions/{id}`, `…/drop`, `…/ack`. Release, submit, verify, answer, delete, drop and ack are role-only today.
- **Programs:** `GET /api/programs`, `POST /api/programs`, `…/edit`, `…/unit`, `GET|PUT|DELETE …/lesson`, `POST /api/programs/lessons/sweep` (its report names every program), `GET …/footprint`, `POST …/approve` (role-only today), `…/session`, `…/milestone`, `…/finish`, `…/reshape`, `…/pause`, `…/resume`, `…/drop`.
- **Situations and asks:** `GET /api/situations`, `GET /api/situations/{kind}/{sid}`, `GET /api/subjects/{kind}/{sid}/situations`, `POST /api/situations/{kind}/{sid}/act`, `POST /api/asks` (no situation check today), `POST /api/asks/{id}/answer` (its effect advances a thread).
- **Projects:** `GET /api/projects`, `GET /api/projects/elsewhere`, `GET /api/projects/for/{kind}/{id}`, `GET /api/projects/{id}/pieces`, `GET /api/projects/{id}`, `POST /api/projects/{id}/plan`, `…/steps/{sid}/cancel`, `…/steps/{sid}/hold` (practice times only), `POST …/pieces`, `…/pieces/remove`, `GET /api/subjects/search`, `GET /api/subjects/{kind}/{sid}/projects`.
- **Signals read by people:** `GET /api/findings` (an unresolved caller passes today), `GET /api/action-proposals`, `POST /api/action-proposals/{id}/act` and its `chat_actions` program actions.
- **Study:** `GET /api/study/state`. `study._board` returns every open thread with its notes and `study._binders` every program; both are role-only today. It gets the class 6 rule, applied to a signed-in page.

**Classes 2 and 3: Argyle (the `agent_tools_v2.py` registry and the chat router)**
- `list_situations`, `next_situation`, `explain_situation`, `act_on_situation`, `start_ask`, `mark_ask_sent`, `answer_ask`, `start_mission_for`, `start_project`, `list_projects`, `get_project`, `add_project_step`, `add_to_project`, `set_project_state`, `set_step_state`, `find_in_chauffeur`.
- `list_threads` (today: checks subject-bound rows only, with no channel check), `create_thread`, `update_thread_action`, `add_thread_note` and `draft_thread_message` (title path unchecked today), `close_thread`, `launch_mission` (`missions._match_thread` is unchecked and seeds the thread into the mission).
- `list_programs`, `program_progress`, `log_program_session`, `propose_program`.
- In `agent_router`: the focus injection (FOCUS and ABOUT), the voice focus injection, and the tool-dispatch actor resolution (today, no member means `parent_of_record`).
- `triage.next_for`, `triage.get_focus`, `triage.focus_live_asks`.

**Class 4: the mission engine (`missions.py`, `planned.py`)**
- The `_apply_planner_action` branches: tool (READ_TOOLS as `read_viewer`), `find_in_chauffeur`, subject, draft (origin thread or `_match_thread`, unchecked today), ask_user.
- `_match_thread`, `_seed_thread_context`, `launch`, `about_block` / `_finder`, `_user_prompt`, `ask_card`, `_land_finish` (DMs the thread title to the creator).
- `planned.is_keeper`, `keeper_view`, `may_approve`, `approve_plan`.

**Class 5: voice**
- `POST /api/v2/converse` → `voice_tools.dispatch` (`find_in_chauffeur`, `start_project`, `prepare_voice_approval`); `voice_approval.valid`, `prepare`, `intercept`.

**Class 6: shared screens**
- `GET /api/house/state` (`house_programs.objects` gives every program's title and colour; `house_attention._programs` gives a count).
- `GET /api/house/programs/{id}/session` (`house_programs.session`).
- `GET /api/programs/{id}/lesson-scenes`.
- `POST /api/programs/{id}/lesson-help` (sends the title to the LLM).
- `GET /api/programs/celebrations`.
- `home_board._tile_programs`, `home_board._tile_mind`.
- Study when it is shown on a panel.

**Class 7: calendar and practice windows**
- `GET /api/practice-windows` (WALL, no check today).
- `main._practice_events` → the cached schedule → `GET /api/schedule`.
- `GET /api/packing/day` (the `family_day` practice payload).
- `main._project_hold_events` / `_project_hold_titles`, `programs.practice_windows`.
- `GET /api/debug/event_subjects` (PARENTS tier) stays raw and is marked INTERNAL-debug.

**Class 8: signals**
- `watchers._thread_stalls`, `_mission_states`, `_program_findings`, `run_watchers`, `_post_action_cards`, `_heads_up_line`.
- `replies.read`, `_send`, `_notify`, `dm_line`, `_recipients`, `flush_pending_dms`.
- `missions._dm_person`, `planned._ask`.
- `mind.snapshot` (its threads and findings sections) and `mind._gather_deltas`.
- `programs.due_practice_pushes`, `family_digest.build_household_briefing`.

**INTERNAL: raw by design, listed so the decision is visible**
- The loaders and checks themselves: `situations.load`, `subjects.load`, the adapters, `subject_records`, `_thread_mission`.
- `situations._facts` / `refresh` (the LLM status note, shown only through `view`) and `options_for` (built without a viewer, shown only through `view`).
- `projects.adopt`, `adopt_existing`, the migration, `_work_missions`, `advance`, `resume_waiting`, `_work_step`, `on_question`, `on_mission_closed`, `_busy_intervals`, `find_window`.
- `threads.match_inbound`, `email_ingest._match_thread`, `threads.is_stalled` / `stalled` (their callers apply the rule), and `threads.open_by_owner` and `vitals.measure_day` (counts only).
- `missions.tick`, `planned.reconcile`, `_bind_created`, `program_lessons.generate_due` / `generate_for` / `_windows_to_scan`, `programs.maybe_rebaseline`, `orphaned_emissions`.
- `programs.due_session_asks` and `projects.project_for` have no callers. The plan deletes them or marks them INTERNAL.

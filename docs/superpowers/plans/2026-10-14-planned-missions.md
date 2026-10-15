# Planned missions (any goal) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Any goal ("plan Kate's party", "plan our Disney trip", "I want to learn piano") can become a planned mission: an interview, a visible plan of build and work stages, each approved once, run by one guarded, atomic, resumable runner, on a registry that reaches every chat tool.

**Architecture:** Registry parity first (missions reach all 29 chat-only tools, with reads run as the transcript's audience, never a named person). A stage contract table (`services/planned.py`) says per tool which args are ids, whether it is idempotent, what it creates and whether it calls a model. `plan` lives on the mission; planner actions interview/answers/plan/stage/work/stage_done feed it; one runner executes build stages; work stages are planner steps scoped by a CURRENT STAGE block. Budget guard on every nested model call. Cards, keeper redaction and recipient-aware delivery on top.

**Tech Stack:** Python / FastAPI / document storage; `services/missions.py`, `services/chat_actions.py`, `services/agent_tools_v2.py`, `services/agent_router.py`, `services/occasions.py`, `services/trip_*`, `services/programs*.py`, `services/llm.py`, `services/web.py`; situations cards and the mission chat card; plain-script tests from `chauffeur/` with `HA_BASE_URL` unset; node + jsdom for cards.

**Spec:** `docs/superpowers/specs/2026-10-14-planned-missions-design.md` (APPROVED by the user 2026-10-14 after two Codex reviews: F1–F12, H1–H7).

## Global Constraints

- Tests from `chauffeur/`, `HA_BASE_URL` unset; the change's own tests plus named neighbours only.
- Every new route gets a rule in `services/auth.py`; no browser dialogs; `python tools/build_tailwind.py` after template class changes.
- Free-text missions (no `plan`) behave exactly as today.
- Nothing in the family's data is written before the stage that writes it is approved; interview answers stay on the mission.
- Caps: 5 questions per round, 2 rounds; 7 stages (follow-up builds not counted); 15 rows per build stage; 3 model-calling rows per build stage; work stage `step_budget` ≤ 12; build stage run bounded at 120 s.
- Build-stage rows run only through `planned.run_stage`; per-proposal endpoints and the `do` verb refuse a proposal with `stage_id`.
- Verbs `approve_plan` and `run_stage` (`plan` is the Mind's insight verb).
- The Mind's `PROPOSE_ONLY_TOOLS`, its gift/DM exclusion, and `voice_tools.TOOLS` are unchanged by registry parity.
- Mission READs run as the registry adult (unbound) or an id-less parent (parents-only subject set); never a named person.
- Trip itinerary state is written only by the CP-SAT bulk path (locked: trip scheduling ownership).
- Codex split: Claude writes each task's tests first and reviews; Codex implements via `codex:codex-rescue`; Claude gates, bumps `config.yaml`, updates `system_capabilities.md`, commits and pushes per task.

## Review Focus

1. Two parents tap "Do this" (or "Go do this part") within a second: it runs once. Tasks 7 and 9.
2. A last-year occasion and a past trip with the same titles exist: every row addresses the new record by id. Task 12.
3. The add-on restarts mid-stage: running rows become `uncertain`, never re-run. Task 7.
4. A parent's own birthday: the presents list excludes them; no other parent → refused. Task 5.
5. "Yes" typed in the family channel while a stage waits: nothing approved; neutral reply. Task 11.

---

### Task 1: Registry parity

**Files:** `services/agent_tools_v2.py` (registry handlers + schemas for the 29 declared-but-unregistered tools; each adapter takes `acting_member` from the caller); `services/missions.py` (`READ_TOOLS` gains the reads; `step` passes the read viewer); `services/agent_router.py` (no behaviour change for chat; the Mind's rail untouched). Test: `tests/test_registry_parity.py`.

Read viewer: `missions.read_viewer(mission)` → `{'id': None, 'role': 'adult'}` unbound; `{'id': None, 'role': 'parent'}` when every record in the subject set is invisible to the id-less adult and visible to the id-less parent. Writes keep the approver.

Tests: declared ⊆ handlers minus {`send_direct_message`, `announce_to_room`, `prepare_voice_approval`}; reads in READ_TOOLS, writes proposable; adapters ignore a model-supplied actor; Mind bind still refuses `draft_thread_message` and every non-allowlisted tool and never reaches a gift tool (drive `process_agent_request(..., propose_only=True)` with a scripted model); satellite still refuses non-`voice_tools.TOOLS`; an unbound mission's `list_threads` read stores no thread bound to a parents-only occasion; a parents-bound mission's read stores no record private to a named person. Neighbours: `test_agent_driver_tools.py`, `test_mind_endpoints.py`, `test_mind_plans*.py` (list with `ls tests | grep mind`), `test_voice_identity.py`, `test_missions_engine.py`, `test_situation_tools.py` (keeps its one pre-existing failure).

### Task 2: The budget guard

**Files:** `services/budget_guard.py` (NEW: a `ContextVar` holding `{cap_kind, remaining}`; `charge(n=1)` raises `BudgetExhausted` when the day's `mission_cap_pro_calls` would be exceeded, using `missions._bump_call`); `services/llm.py` `call_model` and `services/web.py` `research` call `budget_guard.charge()` when a guard is active (no guard → unchanged). Test: `tests/test_planned_budget.py` (block A).

Tests: no guard → no charge (existing callers unchanged); a guard charges each `call_model` and each `research`; `programs_curate.curate` under a guard with 2 calls left stops with `BudgetExhausted` at the third (research, shaping, retry each charged); the exception leaves no partial program row.

### Task 3: The trip scheduler, server-side

**Files:** `services/trip_schedule.py` (NEW `run_bulk(event_id) -> {'scheduled': [poi_id], 'unplaced': [{poi_id, reason}]}`, the CP-SAT bulk path moved out of `main.schedule_pois_bulk_api`, persisting through the same storage writes); `main.py` (`schedule_pois_bulk_api` consumes `run_bulk`, response unchanged); `services/agent_tools_v2.py` NEW `schedule_trip_itinerary(trip_id)` (registry write; the old `auto_schedule_trip_itinerary` UI action stays for chat). Test: `tests/test_trip_schedule.py`.

Tests: `run_bulk` persists scheduled windows for unscheduled POIs; an impossible POI reported unplaced; the endpoint and the tool produce the same stored state; nothing but this path writes itinerary state (grep-free: run the existing trip scheduler tests as neighbours: `ls tests | grep -i trip`).

### Task 4: Creators — `create_trip`, `create_list`

**Files:** `services/agent_tools_v2.py` NEW `create_trip(title, location, start_date, end_date, travelers, idem)` (draft trip through the same code as `main.create_trip_api`'s draft path, extracted to a service function both call) and `create_list(name, audience='household', shared_with=None, idem)`; both return `created`; registry + schemas. Hand paths exist (Trips page New trip, Lists page New list). Test: `tests/test_planned_creators.py`.

Tests: each creates exactly one record, twice with the same `idem` → one record; `create_trip` result is visible on `/api/trips` like a page-made draft; `create_list` private audience honoured (`scope.audience_allows`); both proposable, neither a READ.

### Task 5: Occasion stage tools and the private presents list

As the previous plan's Task 3: `add_occasion` (idem, created, `occasion_id`), `add_occasion_guests` / `set_occasion_attendance` / `source_for_occasion` gain `occasion_id`; NEW `answer_occasion_question`, `stamp_occasion_template`, `add_occasion_dishes` (occasion scope, F11), `set_occasion_menu`, `add_occasion_gift_list` (private, shared with active parents minus the honoree; refuses when empty; hand path `POST /api/occasions/{id}/gift-list` + a gift-panel button); `chat_actions.act_on_proposal` keeps and stores `created`. Test: `tests/test_planned_occasion_tools.py` (Review Focus 4 included).

### Task 6: The stage contract and the plan record

**Files:** `services/planned.py` (NEW: `CONTRACT` for every tool in spec Section 3's table; `CAPS`; `new_plan`; `snapshot(stage, subject)` for build and work; `check_row(row) -> error | None` (contract present, target args are ids or `$ref`, model-row count)); `services/storage.py` (`add_mission` default `plan: None`). Test: `tests/test_stage_contract.py`.

Tests: every contract entry names a real registry handler (or `draft_message`); a name in a target arg refused; `$ref` accepted; idem tools return the same record twice; snapshot changes with any row, exclusion, goal, budget, plan rev or subject triple.

### Task 7: Interview, plan approval, build stages and the runner

**Files:** `services/missions.py` (actions `interview`, `answers`, `plan` (admission formula with work-stage reserve), `stage`); `services/planned.py` (`answer_plan`, `approve_plan`, `drop_stage`, `propose_stage`, `exclude_row`, `run_stage`, `reconcile`, `may_approve`); `services/chat_actions.py` (`create_action_proposal(extra=)`, `run_row(proposal_id, approver, idem)` the runner's only door with an atomic `proposed → executing` claim; `act_on_proposal` refuses stage rows); `main.py` (both proposal endpoints refuse stage rows; the mission route checks `origin_id` and `can_see`; `POST /api/missions/{id}/plan/answers` + auth rule; startup calls `planned.reconcile()`); `services/situations.py` (verbs `approve_plan`, `run_stage`; `do` refuses stage rows; `TAP_ONLY_ASKS` gains `plan` and `stage` for free-text routing; free text on an interview stays an answer); `services/subjects.py` (retarget refused while a stage is proposed/running). Test: `tests/test_planned_missions.py` (blocks A–D of the previous plan, unchanged in substance).

Tests (abridged; the previous plan's Task 1, 2, 4, 5 lists apply verbatim): interview answers held (spy `occasions.answer`, `meals.set_plate_hosting`); plan admission refuses an over-budget plan with words; stale `rev`; snapshots; concurrent "Do this" runs once (Review Focus 1); `$ref`; failed prerequisites skip dependents; `created` stored; stage 1's created occasion/trip binds as subject; `reconcile` → `uncertain`, never re-run (Review Focus 3); 120 s bound; direct endpoints refuse stage rows; retarget blocked.

### Task 8: The budget guard in the runner

**Files:** `services/planned.py` (`run_stage` sets the guard per model-calling row from `CONTRACT`; `BudgetExhausted` → row `failed` "the day's limit", stage `partial`, "carry on tomorrow"). Test: `tests/test_planned_budget.py` (block B).

Tests: a `propose_program` row with too little budget fails cleanly and the stage resumes the next day (simulate the date); a non-model row never charges.

### Task 9: Work stages

**Files:** `services/missions.py` (`work` start via `run_stage` on a work stage: atomic claim, snapshot over goal/budget/rev/subject; CURRENT STAGE block above the transcript; proposals during a work stage are queued as rows of its child build stage instead of being proposed one by one; `stage_done`; step budget; the subject guard: `subject` refused mid-stage except a first binding, which pauses the stage (proposed again, new snapshot) and asks "Now about <title> — go on?"); `services/planned.py` (`queue_row`, `insert_followup`, admission re-check with the "raise the step cap" ask). Test: `tests/test_planned_work.py`.

Tests: approval starts once (two taps); an old card after a steer is stale; CURRENT STAGE in the prompt; browse and release inside a work stage behave as in browse missions; proposals become one follow-up build stage placed right after; `stage_done` records `found`; the budget ends it `partial`; mid-stage `subject` refused; first binding pauses and asks; near-cap insertion waits with the ask.

### Task 10: Drafts, the finish, and the cards

**Files:** `services/planned.py` (`draft_message` rows); `services/missions.py` (finish: summary, `occasions.gap_report` for an occasion subject, plan `done`; `ask_card` kinds `interview`, `plan`, `stage`); `templates/app.html` (`renderMissionAskCard` for the three kinds, build rows and work goal/found); `static/situations.js` (`approve_plan`, `run_stage`, interview submission); `templates/components/missions_page.html` (stepper); back-link lines on the occasion card, trip page and program row ("Plan: stage n of m — <title>"). Tailwind. Tests: `tests/test_planned_mission_cards.py` (node), block E of `tests/test_planned_missions.py`.

### Task 11: Audience — keepers, channels, speakers, the Mind

As the previous plan's Task 8: `planned.redacted(plan)` on every surface for a keeper; group/family channel neutral reply with details to the asker's DM; approval verbs refused outside a private conversation (Review Focus 5); spoken plans only for spoken-safe subjects and never presents rows; `mind.snapshot()` never carries plan content. Test: `tests/test_planned_missions_audience.py`.

### Task 12: Acceptance — Kate's party

`tests/test_planned_party.py` with a scripted planner on the REAL registry, a last-year "Kate's birthday" occasion in the fixture (Review Focus 2): interview → five build stages → the new occasion has guests, an occasion-scoped menu, a supplies list, the cake errand, a private presents list Kate cannot see, three drafts; last year's untouched; the gap report closes it; nothing written before each stage's approval; "yes, do the menu" in the private chat approves stage 2; "make it pizza" re-proposes it. Fixes found here go in this task's commit.

### Task 13: Acceptance — the Disney trip and learning piano

`tests/test_planned_trip.py`: "help me plan our Disney trip in January" → interview (dates, travellers, budget, must-dos, dining style) → build: `create_trip`, `add_trip_accommodation`, attractions and dining (`category: 'food'`) via `add_trip_poi` with `$ref`, `schedule_trip_itinerary` (stored windows asserted) → the trip bound as subject → work: "get dining reservations" (a fake browse runner reports the login wall) hands off with each restaurant and its window → finish. A past trip of the same name untouched.
`tests/test_planned_piano.py`: "I want to learn piano" → interview (who, starting point, minutes, days, budget) → build: `propose_program` (a fake curator; the program lands as a proposal on the Programs page) → work: "find lessons nearby" (fake research; `create_thread` ×2 queued) → its follow-up build: the two threads with `draft_thread_message` → work: "find a piano and books" → follow-up build: `create_list` "Piano" + `add_shopping_items` by `list_id` + `draft_message` → finish.

### Task 14: Docs, memory, final review

`system_capabilities.md` entry (BUILT, NOT device-verified, device steps for all three runs), spec status, memory (`mission-subject-model.md` → slice 2 built; MEMORY.md line); whole-branch Codex adversarial review, one fix wave, one scoped re-review (a second targeted wave only for new leaks or regressions, as in slice 1).

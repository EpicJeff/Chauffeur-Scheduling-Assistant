# Wake conditions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A mission (or a plan's stage) can sleep until a date, a reply on its thread, a weekly program check or a change to its linked record, checked by the existing 30-second tick with no model call; on waking it re-reads the record and brings one card, never writing without a tap.

**Architecture:** One new module, `services/wake.py`, holds the shapes, the resolvers (`record_dates`, the watch end, `fingerprint`, `describe`), the checks and `fire`. `missions.tick` calls `wake.check` after `waiting_retry` promotion. A new mission status `sleeping`; `mission['sleep']` carries the waits and their consumed occurrences; `mission['wakes']` counts the day's wakes. The planner gains a `sleep` action and, while woken, an action allowlist with its own step budget. A plan stage may carry `starts`. Situations get `wake`/`rewait` verbs and a sleeping card; the record pages get a watching line under real subject visibility.

**Tech Stack:** Python / FastAPI / document storage; `services/missions.py`, `services/planned.py`, `services/situations.py`, `services/triage.py`, `services/watchers.py`, `services/mind.py`, `services/agent_tools_v2.py`, `services/settings_registry.py`, `main.py`; `templates/components/missions_page.html`, `static/situations.js`, the trip/occasion/program pages; plain-script tests from `chauffeur/` with `HA_BASE_URL` unset; node + jsdom for cards; Playwright for one screenshot.

**Spec:** `docs/superpowers/specs/2026-10-15-mission-wake-conditions-design.md` (APPROVED by the user 2026-10-15 after Codex review W1–W9).

## Global Constraints

- Tests from `chauffeur/`, `HA_BASE_URL` unset; the change's own tests plus named neighbours only; never the full suite.
- No model call while checking; a model call only after `wake.fire` claims a wake.
- No write without a tap: a woken mission admits only the spec's allowlist (READ `tool`, `research`, `subject`, `propose`, `ask_user`, `stage`/`plan` on its plan, `sleep`, `finish`); `draft` and `browse` are refused during a wake; a finish during a wake never changes the thread's next action or date.
- Each occurrence fires once (`wait['fired']`), written in the same locked write that claims the wake; `mission['wakes']` survives every re-sleep and retry.
- The fingerprint is a canonical projection of stable domain values per kind; never `subjects.context()` text.
- The principal for every check, re-check and fingerprint is `missions._finder(mission)`; `missions.read_viewer` stays the transcript-storage audience.
- Program shortfalls are never stored (locked: programs arc); counts live only in the prompt being built. Paused programs are never checked.
- A keeper keeps Stop and nothing else on a sleeping mission's card; the record page's watching line needs `subjects.visible` for the viewer.
- Every limit is a setting in `services/settings_registry.py`, group `missions`, page `work?tab=missions`, drawer section `missions-wake`: `mission_wake_steps` 3, `mission_wakes_per_day` 2, `mission_watch_max_days` 90, `mission_change_check_minutes` 5, `mission_change_settle_minutes` 10, `mission_reply_read_wait_minutes` 10, `mission_wake_hour` 8, `mission_quiet_hour` 21.
- Free-text missions that never sleep behave exactly as today.
- Every new route gets a rule in `services/auth.py`; no browser dialogs (`promptChoice`/`promptInput`/`promptConfirm`/`showGlobalAlert`); `python tools/build_tailwind.py` after template class changes; same concept, same shared builder (`wake.describe` is the only place a wait becomes words).
- Codex split: Claude writes each task's tests first and reviews; Codex implements via `codex:codex-rescue`; Claude gates, bumps `config.yaml`, updates `system_capabilities.md`, commits and pushes per task.

## Review Focus

1. A wait set at 22:00 for today: it fires at the next wake hour, once, never twice. Task 2.
2. Two sleeping missions bound to the same trip: one edit wakes each once, independently, and neither suppresses the other. Task 3.
3. A session backdated into last week after that week's check ran: no second check for that week. Task 3.
4. "Change the wait" tapped while the mission is mid-wake (`running`): refused with "It is working on it now"; the new wait is not lost silently. Task 6.
5. The creator is archived while the mission sleeps: the parent of record stands in for the re-check and receives the card. Task 2.

---

### Task 1: The wake module's shapes, resolvers and settings

**Files:** `services/wake.py` (NEW); `services/settings_registry.py` (eight entries); `templates/components/missions_page.html` (drawer section `missions-wake` "Waking" listing them through the existing `settings_section` macro); `python tools/build_tailwind.py`. Test: `tests/test_wake.py` (block A).

**Produces:**
- `wake._now() -> datetime.datetime` (local time; the one clock, patched in tests).
- `wake.settings() -> dict` (the eight values with their defaults).
- `wake.record_dates(kind, sid) -> {'start': date|None, 'end': date|None}` (occasion `anchor_date`; trip `subjects.trip_dates`; program start and `baseline.target_date`; event start/end; anything else both None).
- `wake.validate_wait(wait, mission) -> str|None` (an error in words or None: exactly one of `on`/`before_days` for a date; `before_days` needs a record date; `reply` needs a thread; `program_week` needs an active or paused program; `record_change` needs a subject).
- `wake.resolve_day(wait, mission) -> date|None` (a fixed day, or the record's start/end minus `before_days`, re-read now).
- `wake.watch_end(mission) -> date` (explicit `deadline`; else the record end plus one day; else `armed_on` plus `mission_watch_max_days`).
- `wake.describe(sleep, viewer) -> str` (the only words for a wait: "Waiting for: 21 days before Kate's 10th birthday (March 1)", "Waiting for: the plumber's reply", "Checking piano every Monday", "Watching the Disney trip for changes", "… until March 20"; a viewer who cannot see the subject gets "Waiting").

Tests: each resolver per kind; a lead time follows a moved record; `watch_end` for explicit, bound-with-end, bound-without-end, unbound; `validate_wait` refusals; `describe` for each kind and the hidden-viewer neutral form; each setting registered with its default and anchor `missions-wake`; the drawer renders the section (TestClient GET `/work?tab=missions` contains each label). Neighbours: `test_settings_registry*.py` (list with `ls tests | grep -i settings`).

### Task 2: Arm, fire, and the date and reply checks; the tick

**Files:** `services/wake.py`; `services/missions.py` (`'sleeping'` status; `tick` calls `wake.check(now)` after `waiting_retry` promotion; `answer` on a sleeping mission records a steer and leaves it asleep). Test: `tests/test_wake.py` (block B).

**Consumes:** Task 1.
**Produces:**
- `wake.arm(mission_id, waits, reason, set_by, deadline=None, stage_id=None) -> dict` (validates, fills `seen`/`fired`/`weekday`/`eligible_from`, sets `sleep`, status `sleeping` via `missions._close`).
- `wake.check(now=None) -> dict` (per sleeping mission: watch end first, then each wait; quiet hours and the daily limit set `held_until`; returns counts).
- `wake.fire(mission_id, trigger) -> dict` (under `storage.db_lock`: compare-and-set `sleeping → running`, write the occurrence key and `mission['wakes']`, add a `woke` step with the trigger kind and occurrence key; re-check per spec §3.1 using `missions._finder`; a failed re-check → `waiting_user` with a plain ask card offering Wake it anyway and Stop).
- `wake.end_watch(mission_id)` (quiet `done`, summary "Stopped watching: <record> has passed").

Tests: a date wait fires at the wake hour on the day, not before, and never again after it fired and the mission re-slept; a postponed record fires once more on its new day; a wait set at 22:00 for today fires at the next wake hour, once (Review Focus 1); a restart (state reloaded) with a passed date fires once; quiet hours hold to the wake hour; the daily limit holds the third met wait to tomorrow across a re-sleep; reply: a `received` entry with `reading` fires, without `reading` fires after the read wait, an older entry never fires; two `fire` calls in threads → one wake; re-check refusals (rev changed, record gone, record hidden from the finder, creator disabled with no parent of record); an archived creator → the parent of record stands in and gets the card (Review Focus 5); a private gift list shared with the creator passes the re-check; the watch end finishes quietly with the summary and no DM; `missions_enabled` off → no checks, and on again → a passed date fires once; `answer` on a sleeping mission keeps it asleep with a steer step. Neighbours: `test_missions_engine.py`, `test_mission_subject.py`, `test_planned_missions.py`.

### Task 3: The record-change and weekly program checks

**Files:** `services/wake.py`. Test: `tests/test_wake.py` (block C).

**Consumes:** Task 2.
**Produces:**
- `wake.fingerprint(kind, sid, principal) -> str|None` (sha256 over canonical JSON per spec §2: occasion title, kind, anchor date, guests (name, headcount), menu dish ids, tasks, lists the principal may read; trip title, location, start/end, accommodations, stops (name, category, scheduled start, duration), flights; program title, state, shape, target date; event title, start, end, location; None when the principal may not read the record).
- the `record_change` check (every `mission_change_check_minutes`; `changed_at` set and reset; met after `mission_change_settle_minutes`; a settled fingerprint equal to `fired.fingerprint` never fires).
- the `program_week` check (on `weekday` at the wake hour, on or after `eligible_from`, skipped while paused, re-armed silently on plan with `fired.week`, met when behind or ahead; resume re-arms with `eligible_from` + 7).

Tests: the same occasion, program and trip fingerprint identically across midnight and across the trips cache ageing (`subjects.trip_dates` cache), an edit to the occasion menu changes it, a change to a list the principal cannot read does not; a burst of three edits wakes once after the settle; two sleeping missions on one trip each wake once from one edit (Review Focus 2); weekly on plan → no planner call (the faked model's prompt list unchanged), no step, `fired.week` recorded; behind and ahead fire; no session count appears in any mission step, plan or row after a weekly wake (scan the stored mission and steps for the digits); a pause spanning two check days fires nothing; the first check after resume is seven days later; a session backdated into a week already checked causes no second check (Review Focus 3). Neighbours: `test_programs*.py` (list with `ls tests | grep -i program`), `test_subjects.py`.

### Task 4: The planner side — `sleep`, WOKE, the allowlist, wake steps

**Files:** `services/missions.py` (`sleep` action → `wake.arm`, refused while a card waits, a stage runs or a browse is live; the `WOKE:` line built at prompt time from the latest `woke` step, program counts recomputed there and never stored; while woken, `wake_steps_used` counted instead of `step_count`, capped by `mission_wake_steps`; the allowlist refusing `draft` and `browse` with a `refused` note; a finish during a wake calls `_land_finish(..., advance=False)`; steps run out → `wake.arm` with the same waits and their `fired` keys and the note "Looked; nothing needs you"; the planner prompt documents `sleep` and the four wait kinds). Test: `tests/test_wake_planner.py` (block A).

**Consumes:** Tasks 1–3.

Tests: `sleep` arms and sends no DM; each refusal (open ask, proposed stage, running stage, live browse, invalid wait, reply without a thread); a woken mission's first prompt leads with `WOKE:`; the weekly WOKE line carries the counts and the "never state a count" instruction, and no count is stored; `draft` and `browse` during a wake refused through the real runner; `finish` during a wake leaves the origin thread's `next_action` and `next_action_at` unchanged and still appends the history line; three steps with no card → back to sleep keeping `fired` (no second wake on the same occurrence); wake steps do not move `step_count`; a spent daily allowance mid-wake → `waiting_retry`, and the retry continues the wake with its remaining steps. Neighbours: `test_missions_engine.py`, `test_planned_work.py`, `test_planned_hardening.py`.

### Task 5: Plans — a stage that starts on a wait

**Files:** `services/planned.py` (plan validation admits `starts` on a stage via `wake.validate_wait`; `prepare_next` arms the mission with the stage's `starts` and `stage_id` when it reaches a pending stage whose start is unmet; on waking with `stage_id` the stage is offered as today; a hand change to a stage's start edits the plan and bumps `plan.rev`); `services/missions.py` (planner prompt documents `starts`). Test: `tests/test_wake_planner.py` (block B).

**Consumes:** Tasks 2 and 4.

Tests: a plan whose third stage starts 21 days before the party is approved with one tap; after stages 1–2 the mission sleeps with `stage_id`; on the day the stage is offered with no extra model call for a work stage and one for a build stage; an invalid `starts` refuses the plan; changing the stage's start by hand bumps the rev and makes the old approve buttons stale; a stage start of `reply` on a plan without a thread is refused. Neighbours: `test_planned_missions.py`, `test_planned_party.py`.

### Task 6: Situations and endpoints — the sleeping card, `wake`, `rewait`, Stop

**Files:** `services/situations.py` (`_state` for sleeping; `_options_mission` for sleeping: Wake now `wake`, Change the wait `rewait`, Stop (the existing stop door); a keeper sees Stop only; `wake` and `rewait` in `VERBS`; `act` routes them to `wake.fire(..., 'hand')` and `wake.arm` / a stage-start edit; `rewait` on a `running` mission → refused "It is working on it now" (Review Focus 4)); `services/triage.py` and `services/watchers.py` (a sleeping mission never ranks and raises no finding); `services/planned.py` `keeper_view` (the allowlist gains `sleep` reduced to `{'state': 'sleeping'}`); `services/mind.py` snapshot (no wait reason or woke line for a subject the snapshot audience may not see); `main.py` `subject_situations` (a `watch_line` from `wake.describe` only when `subjects.visible(kind, record, viewer)`); `services/auth.py` (rules for any new route). Test: `tests/test_wake_hand_path.py` (block A).

**Consumes:** Tasks 1–5.

Tests: the sleeping card's words and options for a parent; a keeper's card shows "Waiting" and Stop only, and the keeper can stop it after the subject became hidden; Wake now fires once even when a tick fires the same moment; `rewait` re-arms with the new wait and keeps nothing of the old one's `fired`; `rewait` while running is refused with the message; triage `tier`/`triage_rank` and `watchers.run_watchers` ignore a sleeping mission; `keeper_view` carries no reason; the Mind snapshot carries no reason for a parents-only subject; `GET /api/subjects/{kind}/{sid}/situations` gives a parent the watching line and gives an excluded mission creator and an excluded thread owner neither line nor date. Neighbours: `test_situations.py`, `test_triage.py`, `test_watchers*.py` (list), `test_planned_missions_audience.py`, `test_subject_hardening.py`, `test_mind_endpoints.py`.

### Task 7: Conversation and the new-mission hand path

**Files:** `services/agent_tools_v2.py` (`start_mission_for` gains an optional `wait` (+ `deadline`) → `missions.launch` then `wake.arm`; `act_on_situation` enum gains `wake`, `rewait` and the missing `submit`/`verify`, fixing `test_situation_tools` parity; `list_situations` lines for sleeping missions use `wake.describe` for the asker, under slice 2's channel rule); `main.py` `POST /api/missions/launch` accepts an optional `wait` and `deadline`; `services/agent_router.py` tool schemas. Test: `tests/test_wake_hand_path.py` (block B).

**Consumes:** Task 6.

Tests: "remind me about Disney dining when it opens" (a scripted model calling `start_mission_for` with a date wait 60 days before the trip) starts a sleeping mission bound to the trip; `act_on_situation` `wake` and `rewait` through the router; "what are you waiting on?" lists sleeping missions with their words, and in a mixed channel omits one bound to a record someone there may not see; `POST /api/missions/launch` with a wait starts it asleep and refuses an invalid wait with the reason; `tests/test_situation_tools.py` 5/5. Neighbours: `test_start_mission.py`, `test_situation_tools.py`, `test_registry_parity.py`, `test_agent_driver_tools.py`.

### Task 8: The cards and pages

**Files:** `templates/components/missions_page.html` (the sleeping card's waiting line, Change the wait sheet: kind, a day or lead-time picker, a deadline; the new-mission form's optional "Start when…" picker); `static/situations.js` (`VERB_LABELS` for `wake`/`rewait`, the rewait sheet through `promptChoice`/`promptInput`, the plan stepper's stage start text); the trip, occasion and program pages (render `watch_line` from `subject_situations` next to the existing plan line); `templates/app.html` (a woken ask card is the existing ask card; the chat card for a refused re-check offers Wake it anyway and Stop); `python tools/build_tailwind.py`. Read `docs/ui_design_guide.md` first. Test: `tests/test_wake_cards.py` (node + jsdom render of the sleeping card for parent and keeper, the rewait sheet's payloads, the stepper start text, the watching line) plus one Playwright screenshot of the Missions page with a sleeping mission saved to the scratchpad for review.

**Consumes:** Tasks 6–7.

Tests: the card shows the words from the API, never builds its own; a keeper's card renders Stop only; the rewait sheet posts each of the four kinds with the right fields; no `alert`/`confirm`/`prompt` in the changed files; the record pages show the watching line only when the API gives one. Neighbours: `test_planned_mission_cards.py`, `test_template_js.py`, `test_mission_chat_card_render.py`.

### Task 9: Acceptance — the party, piano and the trip

**Files:** tests only, plus whatever small fixes they expose. Test: `tests/test_wake_party.py`, `tests/test_wake_piano.py`, `tests/test_wake_trip.py` on the real registry with only the model, the clock and mail intake's reading faked.

**Consumes:** Tasks 1–8.

- **Party:** a plan whose invitations stage starts 21 days before Kate's party; approved; the mission sleeps; the clock moves to 22 days before: asleep; 21 days before at 07:00: asleep; 08:00: the stage is offered; moving the party a week later re-arms it for the new day; after the invitations, a `reply` wait; an RSVP ("yes, 4 of us", read) wakes it and it proposes adding the headcount; approving writes the guest row.
- **Piano:** a program mission with a weekly check; an on-plan week: silent, no model call; a behind week: one card proposing a lighter week whose words state no missed count; a paused week: nothing.
- **Trip:** a dining stage waiting on `record_change` of the trip; the trip's dates move; after the settle the mission wakes, its WOKE line says the record changed, ABOUT shows the new dates, and it proposes the dining stage with the new times.

Neighbours: `test_planned_party.py`, `test_planned_trip.py`, `test_planned_piano.py`.

### Task 10: Docs, memory, final review

`system_capabilities.md` entry (BUILT, NOT device-verified, device steps for the three runs), spec status, memory (`mission-subject-model.md` → slice 3 built; the MEMORY.md line); whole-branch Codex adversarial review from the plan's base commit, one fix wave with tests first, one scoped re-review (a second targeted wave only for unclosed findings or regressions; verify any "pre-existing" claim against the base commit before accepting it).

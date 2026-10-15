# Wake conditions — missions that sleep until the moment comes

**Date:** 2026-10-15. **Status:** DRAFT, design approved section by section by the user in conversation (2026-10-15); awaiting Codex adversarial review, then the user's review of this document. Slice 3 of three (slice 1: subjects, v2.499.459–.472; slice 2: planned missions for any goal, v2.499.473–.493).
**Builds on:** `2026-10-14-mission-subject-resolver-design.md` (subjects, `subject_rev`, `subjects.context()`, audience inheritance), `2026-10-14-planned-missions-design.md` (plans, stages, `planned.prepare_next`, the keeper rules, approval by words only in private), `2026-09-04-mission-engine-design.md` (the planner loop and `missions.tick`).

## Problem

A mission today can only work now or wait for a person. It cannot wait for the world. The examples that drove slices 1 and 2 all need that:

- Disney dining opens 60 days before the trip. "Book dining" is useless before then and urgent on the day.
- Party invitations go out three weeks before the party; RSVPs arrive by mail over the following days.
- A piano plan is only as good as the weeks that follow it: missed sessions should lead to a lighter week, easy weeks to a harder one.
- When the trip's dates move, the dining times the plan proposed are wrong.

What exists (surveyed 2026-10-15): nothing sleeps. A finished mission is final (`missions.answer` rejects terminal states). A reply on a thread (`threads.match_inbound`, `replies.read`) changes the thread card but never wakes a mission. A logged program session (`programs.log_session`) fires nothing. Editing an occasion or a trip bumps nothing a mission could notice (`subject_rev` counts re-bindings, not content). `missions.tick` runs every 30 s from the push loop, promotes `waiting_retry` rows, and steps one `running` mission per tick. A woken mission would already see fresh data: `subjects.context()` is read fresh into every planner prompt. Only the trigger is missing.

## Decisions (the user's, 2026-10-15)

1. **Four triggers:** a date (fixed or a lead time before the record's own date), a reply on the mission's thread, a weekly program check, a change to the linked record.
2. **On waking: think, then ask.** Argyle re-reads the record, works out what to do and brings one card to the person's Argyle chat. Nothing is written without a tap, as in slice 2.
3. **Lifetime: until the record's end.** Party day, the last day of the trip, the program's end; always visible on the Missions page with Stop.
4. **Programs: a weekly check-in,** silent when the week went to plan.
5. **Approach A:** waits are stored on the mission (or its stage) and checked by the existing loop with no model call; a record change is detected by comparing a fingerprint, so every edit path (page, chat, voice, API) is caught without hooks.
6. **Every limit is a setting** with the defaults below, in the settings registry and the Missions page's settings drawer (never `config.html`).

## Section 1 — Shapes

### A wait

```
wait = {
  'id': str,                       # stable within the mission
  'kind': 'date' | 'reply' | 'program_week' | 'record_change',
  # date: exactly one of
  'on': 'YYYY-MM-DD',              # a fixed day
  'before_days': int, 'of': 'start' | 'end',   # a lead time before the record's date
  # program_week
  'program_id': str,               # defaults to the subject when the subject is a program
  'weekday': 0..6,                 # set when armed: the weekday the plan was approved or the wait was set
  # what it saw when armed (filled by wake.arm, never by the planner)
  'seen': {'reply_ts': float|None, 'fingerprint': str|None, 'last_check': float|None,
           'changed_at': float|None, 'week_checked': 'YYYY-MM-DD'|None},
}
```

A lead time is re-measured from the record on every check, so moving the party moves the wake. The record's date comes from one resolver, `wake.record_dates(kind, id) -> {'start': date|None, 'end': date|None}`: an occasion's `anchor_date` (start and end); a trip's destination dates (`subjects.trip_dates`); a program's start and `baseline.target_date`; an event's start and end. A `before_days` wait on a record with no such date is refused when set.

### A sleeping mission

```
mission['sleep'] = {
  'reason': str,                   # in words, shown on every card ("Waiting for the plumber's quote")
  'waits': [wait, ...],            # any one met wakes the mission
  'until': 'YYYY-MM-DD',           # the watch ends after this day
  'stage_id': str | None,          # a plan stage that starts on waking
  'subject_rev': int,              # the binding it slept on
  'since': float, 'set_by': 'argyle' | member_id,
  'wakes': {'date': 'YYYY-MM-DD', 'n': int},     # wakes today
  'held_until': float | None,      # a wake held for quiet hours or the daily limit
}
mission['status'] = 'sleeping'
```

`sleeping` is a new mission status beside `waiting_user` and `waiting_retry`. It is not terminal: the 120-day prune leaves it alone; `missions.answer` accepts words on a sleeping mission as a steer (it stays asleep and the steer is read on waking); triage never ranks a sleeping mission as needing anyone; the watchers raise no finding for one.

**`until`:** the record's end (`record_dates(...)['end']`, plus one day) for a bound mission; for an unbound mission the planner or person states it, at most `mission_watch_max_days` (90) from now; a program watch also ends when the program leaves `active`/`paused`. A watch whose `until` has passed ends quietly: the mission becomes `done` with the summary "Stopped watching: <record> has passed" (Missions page history; no message).

### Who sets a wait

- **In a plan:** a stage may carry `starts: wait` (a `date`, `reply` or `record_change` wait). It is part of the plan and approved with it. When `planned.prepare_next` reaches a pending stage whose `starts` is unmet, the mission sleeps with that wait and `stage_id`.
- **In a plain mission:** a new planner action `{"action": "sleep", "reason": "...", "waits": [...], "until": "YYYY-MM-DD"}`. It writes nothing, so it needs no approval; it is refused while a card waits on the person (an open ask, a proposed stage or proposal), while a stage runs, when no wait is valid, and when a `reply` wait has no thread.
- **By hand:** the Missions page, the thread card and the chat card offer Change the wait (Section 4); `start_mission_for` and the Missions page's new-mission form take an optional starting wait, so a mission can begin asleep ("remind me about Disney dining when it opens").

## Section 2 — The checks (no model call)

One module, `services/wake.py`, called from `missions.tick` after `waiting_retry` promotion and before stepping, gated by `missions_enabled` like the rest of the tick. For each `sleeping` mission:

- **date:** met when today ≥ the resolved day and the local hour ≥ `mission_wake_hour` (8).
- **reply:** the mission's thread (its origin thread, else a thread subject) has a `received` history entry newer than `seen.reply_ts`. Met when that entry has its `reading` (mail intake's `replies.read`), or `mission_reply_read_wait_minutes` (10) after it arrived.
- **program_week:** due once a week on `weekday` at `mission_wake_hour`, never twice for the same date (`seen.week_checked`). Count = sessions logged in the 7 days before today (`programs.sessions_between`); plan = the program's `sessions_per_week`. Equal: re-arm silently, no model call, no message. Behind or ahead: met, with both numbers.
- **record_change:** at most every `mission_change_check_minutes` (5). Fingerprint = sha256 of `subjects.context(kind, id, missions.read_viewer(mission))`, the same text the planner reads, so a change the planner could not see never wakes it. A new fingerprint sets `seen.changed_at`; a further change resets it; met `mission_change_settle_minutes` (10) after the last change.
- **until:** checked first; an ended watch finishes the mission quietly as above.
- **Quiet hours:** a met wait between `mission_quiet_hour` (21) and `mission_wake_hour` (8) holds (`held_until` = the next 08:00) and fires then.
- **Daily limit:** at most `mission_wakes_per_day` (2) per mission; a third met wait holds until tomorrow's wake hour.
- **After a restart:** checks are state-based, so a date that passed while the add-on was down fires once at the next tick, never once per missed tick.

## Section 3 — Waking

`wake.fire(mission_id, trigger)` under `storage.db_lock`, compare-and-set `sleeping → running` (a hand Wake now and a tick can never both fire):

1. **Re-check.** The mission's `subject_of(...)[2]` equals `sleep.subject_rev`; the subject record still loads and is visible to `missions.read_viewer(mission)`; the creator is still `active`. If not, the mission does not act: it goes to `waiting_user` with a plain card ("This was watching Kate's party, which has changed hands / is gone") offering Wake it anyway and Stop.
2. **Woke line.** A `woke` mission step records the trigger and what it saw; the planner prompt leads with `WOKE: <words>` ("Party day is 21 days out"; "The Wilsons replied: yes, 4 of us"; "This week: 1 of 3 piano sessions"; "The trip's dates changed") above the usual fresh ABOUT.
3. **A stage that starts on waking** is offered as stages are today (`prepare_next`): a work stage with no model call, a build stage with one planner call to fill its rows.
4. **Think, then ask.** Otherwise up to `mission_wake_steps` (3) planner steps. They end in one card (an ask, a proposal, a stage offer: the mission goes `waiting_user` as today), a `sleep` action (back to sleep with no message; the reason shows on the Missions page), or `finish`. If the steps run out with none of those, the mission goes back to sleep with the same waits and the note "Looked; nothing needs you".
5. **Budget.** Wake steps are counted in `wake_steps_used`, not `step_count`, so a long watch is not killed by `mission_step_cap`; every step still charges the daily pro-call allowance (`_bump_call`), and a spent allowance retries in 30 minutes as today. Work-stage actions stay under `budget_guard` (slice 2).
6. **Who hears it.** The card goes through `_dm_person` and the slice 2 rules: a keeper gets the neutral line and no card; plan words never reach a channel some member may not see; approval by words only in a private conversation; the Mind's snapshot carries no wait reasons or woke lines for a parents-only subject.

## Section 4 — The hand path and the conversation

- **The card** (Missions page, thread card, chat card) of a sleeping mission says what it waits for in words, built by one function `wake.describe(sleep) -> str` ("Waiting for: 21 days before Kate's 10th birthday (March 1)"; "Waiting for: the plumber's reply"; "Checking piano every Monday"; "Watching the Disney trip for changes"; "until March 20"), with three options: **Wake now** (verb `wake`), **Change the wait** (verb `rewait`, a sheet with the four kinds, a day or lead-time picker, and until), **Stop** (the existing mission stop). Keepers see "Waiting" with no record words and no options.
- **A plan's stepper** shows a stage's start ("Starts 21 days before the party, March 1"); changing a stage's start by hand edits the plan and bumps `plan.rev`, so old buttons go stale.
- **The record's page** (trip, occasion, program, through `subject_situations`) shows "Argyle is watching this: next check March 1" for a sleeping mission bound to it, under the same audience check as slice 2's plan line.
- **Conversation:** "remind me about Disney dining when it opens" → `start_mission_for` with a starting wait; "wake it up" / "watch for her reply instead" / "stop watching the party" → `act_on_situation` with `wake`, `rewait`, stop; "what are you waiting on?" → `list_situations` lists sleeping missions with `wake.describe`. Every one of these has the hand path above.
- `wake` and `rewait` join `situations.VERBS`; the `act_on_situation` enum is widened to match (the existing parity test, which fails today because the enum lacks `submit`/`verify`, is fixed in the same edit).

## Section 5 — Settings

In `services/settings_registry.py` (group `missions`, page `work?tab=missions`, a new drawer section `missions-wake` "Waking"):

| Key | Default | Meaning |
|---|---|---|
| `mission_wake_steps` | 3 | Planner steps one wake may take |
| `mission_wakes_per_day` | 2 | Wakes per mission per day |
| `mission_watch_max_days` | 90 | Longest watch for a mission with no linked record |
| `mission_change_check_minutes` | 5 | How often a record-change wait reads the record |
| `mission_change_settle_minutes` | 10 | Quiet time after the last edit before a change wakes |
| `mission_reply_read_wait_minutes` | 10 | How long a reply wait waits for mail intake's reading |
| `mission_wake_hour` | 8 | Hour a date or weekly wake fires; quiet hours end |
| `mission_quiet_hour` | 21 | Hour quiet hours start |

## Section 6 — Safety

- No write without a tap: waking only ever produces cards; a stage's rows still run through `planned.run_stage`.
- A changed binding refuses (Section 3.1); a re-bound mission's waits are not carried to the new record.
- A sleeping mission blocks nothing: `subjects.retarget` is allowed while asleep (it bumps `subject_rev`, so the next wake refuses and asks).
- One wake at a time: compare-and-set under `db_lock`.
- Every limit is a setting; `missions_enabled` off stops all checks (a mission sleeps through it and checks again when it is turned back on; a date that passed fires once).
- HA is not involved; nothing here touches Home Assistant.

## Section 7 — Tests (written first by Claude; Codex implements)

- `tests/test_wake.py`: the four checks against a fake clock (`wake._now`), including the hour, lead time re-measured after the record moves, reply with and without reading, weekly on-plan silent (no planner call) and behind/ahead firing with counts, change settle and reset, until ending quietly, quiet hours, daily limit, restart firing once, compare-and-set (two fires, one wake), re-check refusals (rev, gone, hidden, creator disabled).
- `tests/test_wake_planner.py`: the `sleep` action and its refusals; a stage with `starts`; wake steps outside `step_count`; ran-out goes back to sleep; steer on a sleeping mission.
- `tests/test_wake_hand_path.py`: `wake`, `rewait`, stop by situation act and endpoints; `start_mission_for` and the new-mission form with a starting wait; `wake.describe`; the record page's watching line; keeper redaction; triage and watchers ignore sleeping missions; settings respected (one test per setting).
- Acceptance on the real registry, only the model faked: `tests/test_wake_party.py` (the invitations stage sleeps until 21 days out; moving the party moves the wake; an RSVP reply wakes the mission and it proposes the headcount), `tests/test_wake_piano.py` (an on-plan week is silent; a behind week wakes a lighter-week proposal), `tests/test_wake_trip.py` (a trip date change wakes the dining stage with the new times).
- Every critical path has a test that runs it (a tick, a TestClient request, a node run of the card JS).

## Out of scope

Waiting on another mission; price or availability watching on outside sites; acting without a tap; fan-out into child missions; sending outside the family (drafts only, as before).

## Build split (the user's standing rule)

Claude writes every task's tests first; Codex implements each task via `codex:codex-rescue`; Claude reviews the diff, reruns the gate, updates `system_capabilities.md`, bumps `config.yaml` and commits. Codex reviews this spec adversarially before the user sees it, and the whole branch at the end.

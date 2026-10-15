# Wake conditions — missions that sleep until the moment comes

**Date:** 2026-10-15. **Status:** FOLDED INTO PROJECTS (2026-10-15): the user reframed long-running goals as Projects (`2026-10-15-projects-core-design.md`); this engine becomes slice B (reviews) and is revised there; not built. Was: DRAFT, design approved section by section by the user in conversation (2026-10-15); Codex adversarial review of the first draft (nine findings, W1–W9) folded in; awaiting the user's review of this document. Slice 3 of three (slice 1: subjects, v2.499.459–.472; slice 2: planned missions for any goal, v2.499.473–.493).
**Builds on:** `2026-10-14-mission-subject-resolver-design.md` (subjects, `subject_rev`, `subjects.context()`, audience inheritance), `2026-10-14-planned-missions-design.md` (plans, stages, `planned.prepare_next`, the keeper rules, approval by words only in private), `2026-09-04-mission-engine-design.md` (the planner loop and `missions.tick`).

## Problem

A mission today can only work now or wait for a person. It cannot wait for the world. The examples that drove slices 1 and 2 all need that:

- Disney dining opens 60 days before the trip. "Book dining" is useless before then and urgent on the day.
- Party invitations go out three weeks before the party; RSVPs arrive by mail over the following days.
- A piano plan is only as good as the weeks that follow it: missed sessions should lead to a lighter week, easy weeks to a harder one.
- When the trip's dates move, the dining times the plan proposed are wrong.

What exists (surveyed 2026-10-15): nothing sleeps. A finished mission is final (`missions.answer` rejects terminal states). A reply on a thread (`threads.match_inbound`, `replies.read`) changes the thread card but never wakes a mission. A logged program session (`programs.log_session`) fires nothing. Editing an occasion or a trip bumps nothing a mission could notice (`subject_rev` counts re-bindings, not content). `missions.tick` runs every 30 s from the push loop, promotes `waiting_retry` rows, and steps one `running` mission per tick. A woken mission already sees fresh data: the planner's ABOUT block (`missions.about_block`) reads `subjects.context()` fresh, as the finder (`missions._finder`), on every call. Only the trigger is missing.

## Decisions (the user's, 2026-10-15)

1. **Four triggers:** a date (fixed or a lead time before the record's own date), a reply on the mission's thread, a weekly program check, a change to the linked record.
2. **On waking: think, then ask.** Argyle re-reads the record, works out what to do and brings one card to the person's Argyle chat. Nothing is written without a tap.
3. **Lifetime: until the record's end.** Party day, the last day of the trip, the program's end; always visible on the Missions page with Stop.
4. **Programs: a weekly check-in,** silent when the week went to plan.
5. **Approach A:** waits are stored on the mission (or its stage) and checked by the existing loop with no model call; a record change is detected by comparing a fingerprint, so every edit path (page, chat, voice, API) is caught without hooks.
6. **Every limit is a setting** with the defaults below, in the settings registry and the Missions page's settings drawer (never `config.html`).

Locked decisions this design honours: a program's shortfall is derived at read time and never stored (programs arc; `programs.weekday_shortfall`); a keeper keeps their row and its neutral controls but never the subject's words (slices 1 and 2); approval by words only in a private conversation (slice 2); no write without a tap for anything a mission does on its own.

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
  'weekday': 0..6,                 # set when armed or resumed
  'eligible_from': 'YYYY-MM-DD',   # first check day: 7 days after approval, arming or resume (W9)
  # what it saw and what it already fired on (filled by wake.arm/fire, never by the planner)
  'seen': {'reply_ts': float|None, 'fingerprint': str|None, 'last_check': float|None,
           'changed_at': float|None},
  'fired': {'date': 'YYYY-MM-DD'|None,         # the resolved day it last fired for (W2)
            'reply_ts': float|None,            # the received entry it last fired for
            'week': 'YYYY-MM-DD'|None,         # the check day it last fired or re-armed on
            'fingerprint': str|None},          # the settled fingerprint it last fired for
}
```

**Occurrences are consumed (W2).** A wait is met only by an occurrence it has not fired for: a date wait whose resolved day differs from `fired.date`; a reply newer than `fired.reply_ts`; a check day other than `fired.week`; a settled fingerprint other than `fired.fingerprint`. `wake.fire` writes the occurrence key in the same locked write that claims the wake. Going back to sleep (by the planner's `sleep`, by spent wake steps, by a retry) keeps `fired`, so the same occurrence never fires twice. A record that moves to a later date resolves to a new day, which is a new occurrence.

A lead time is re-measured from the record on every check, so moving the party moves the wake. The record's dates come from one resolver, `wake.record_dates(kind, id) -> {'start': date|None, 'end': date|None}`: an occasion's `anchor_date` (start and end); a trip's destination dates (`subjects.trip_dates`); a program's start and `baseline.target_date`; an event's start and end. A `before_days` wait on a record with no such date is refused when set.

### A sleeping mission

```
mission['sleep'] = {
  'reason': str,                   # in words, shown on every card ("Waiting for the plumber's quote")
  'waits': [wait, ...],            # any one met wakes the mission
  'deadline': 'YYYY-MM-DD'|None,   # an explicit end someone set; None = derived from the record (W4)
  'armed_on': 'YYYY-MM-DD',        # for the no-end fallback
  'stage_id': str | None,          # a plan stage that starts on waking
  'subject_rev': int,              # the binding it slept on
  'since': float, 'set_by': 'argyle' | member_id,
  'held_until': float | None,      # a wake held for quiet hours or the daily limit
}
mission['wakes'] = {'date': 'YYYY-MM-DD', 'n': int}   # on the mission, not in `sleep`: survives every re-sleep and retry (W2)
mission['status'] = 'sleeping'
```

`sleeping` is a new mission status beside `waiting_user` and `waiting_retry`. It is not terminal: the 120-day prune leaves it alone; `missions.answer` accepts words on a sleeping mission as a steer (it stays asleep and the steer is read on waking); triage never ranks a sleeping mission as needing anyone; the watchers raise no finding for one.

**When a watch ends (W4).** Resolved on every check, before any trigger, never stored: the explicit `deadline` when one is set; otherwise, for a bound mission, the record's end (`record_dates(...)['end']` plus one day, re-read now, so a postponed party extends the watch); for a bound record with no end date (a program without a target date, a list, a thread, a member) or an unbound mission, `armed_on` plus `mission_watch_max_days` (90). A program watch also ends when the program leaves `active`/`paused`. An ended watch finishes the mission quietly: `done`, summary "Stopped watching: <record> has passed" (Missions page history; no message). An explicit deadline may not exceed `armed_on` plus `mission_watch_max_days` for an unbound mission.

### Who sets a wait

- **In a plan:** a stage may carry `starts: wait` (a `date`, `reply` or `record_change` wait). It is part of the plan and approved with it. When `planned.prepare_next` reaches a pending stage whose `starts` is unmet, the mission sleeps with that wait and `stage_id`.
- **In a plain mission:** a new planner action `{"action": "sleep", "reason": "...", "waits": [...], "deadline": "YYYY-MM-DD"|null}`. It writes nothing, so it needs no approval; it is refused while a card waits on the person (an open ask, a proposed stage or proposal), while a stage runs or a browse is live, when no wait is valid, and when a `reply` wait has no thread.
- **By hand:** the Missions page, the thread card and the chat card offer Change the wait (Section 4); `start_mission_for` and the Missions page's new-mission form take an optional starting wait, so a mission can begin asleep ("remind me about Disney dining when it opens").

## Section 2 — The checks (no model call)

One module, `services/wake.py`, called from `missions.tick` after `waiting_retry` promotion and before stepping, gated by `missions_enabled` like the rest of the tick. For each `sleeping` mission, first the watch end (Section 1), then each wait:

- **date:** met when today ≥ the resolved day, the local hour ≥ `mission_wake_hour` (8), and the resolved day ≠ `fired.date`.
- **reply:** the mission's thread (its origin thread, else a thread subject) has a `received` history entry newer than both `seen.reply_ts` and `fired.reply_ts`. Met when that entry carries its `reading` (written by `replies.read` on the history entry), or `mission_reply_read_wait_minutes` (10) after it arrived.
- **program_week:** due on `weekday` at `mission_wake_hour`, on or after `eligible_from`, never for a check day already in `fired.week`. **Skipped entirely while the program is `paused`** (W9; `programs.pause` promises nothing counts against a paused week); resuming re-arms with `eligible_from` seven days after the resume. Due: count the sessions logged in the seven days before the check day (`programs.sessions_between`) against `shape.sessions_per_week`. Equal: record `fired.week`, re-arm silently, no model call, no message. Behind or ahead: met. **The counts are never stored** (W7): the woke step records only "weekly check: off plan"; the numbers are recomputed from the sessions when the planner's prompt is built and live only in that prompt.
- **record_change:** at most every `mission_change_check_minutes` (5). The fingerprint is **not** presentation text (W3): `wake.fingerprint(kind, id, principal)` is a sha256 over a canonical JSON projection of the record's stable domain values, built per kind — occasion: title, kind, anchor date, guests (name, headcount), menu dish ids, tasks, lists the principal may read; trip: title, location, start and end, accommodations, stops (name, category, scheduled start, duration), flights; program: title, state, shape, target date (sessions excluded: the weekly check owns them); event: title, start, end, location — with no relative times, no "days away", no cache ages, no truncation, and nothing the principal may not read. A new fingerprint sets `seen.changed_at`; a further change resets it; met `mission_change_settle_minutes` (10) after the last change, if the settled fingerprint ≠ `fired.fingerprint`.
- **Quiet hours:** a met wait between `mission_quiet_hour` (21) and `mission_wake_hour` (8) holds (`held_until` = the next wake hour) and fires then.
- **Daily limit:** at most `mission_wakes_per_day` (2) per mission (`mission['wakes']`); a further met wait holds until tomorrow's wake hour.
- **After a restart:** checks are state-based and occurrences consumed, so a date that passed while the add-on was down fires once at the next tick, never once per missed tick and never again after it fired.

**The principal (W5).** Every check, the re-check in Section 3 and the fingerprint use one principal: `missions._finder(mission)` (the creator while they still have access, else the parent of record), the same reader as the planner's ABOUT. Visibility is `subjects.visible` for that principal plus the mission's `subject_history` audience. `missions.read_viewer` stays what it is: the audience of what may be STORED in the transcript.

## Section 3 — Waking

`wake.fire(mission_id, trigger)` under `storage.db_lock`: compare-and-set `sleeping → running`, write the occurrence key and the day's wake count in the same write (a hand Wake now and a tick can never both fire, and an occurrence fires once):

1. **Re-check.** The mission's `subject_of(...)[2]` equals `sleep.subject_rev`; the subject record still loads and is visible to the principal (Section 2); the creator is still `active`, or the parent of record stands in. If not, the mission does not act: it goes to `waiting_user` with a plain card ("This was watching Kate's party, which is gone / now points somewhere else") offering Wake it anyway and Stop.
2. **Woke line.** A `woke` mission step records the trigger kind and the occurrence key (never a program's counts). The planner prompt leads with `WOKE: <words>` built at prompt time ("Party day is 21 days out"; "The Wilsons replied: yes, 4 of us"; "Weekly check: 1 of 3 piano sessions this week — propose a change to the plan; never state a count of missed sessions in a card"; "The trip's record changed") above the usual fresh ABOUT.
3. **A stage that starts on waking** is offered as stages are today (`prepare_next`): a work stage with no model call, a build stage with one planner call to fill its rows.
4. **Think, then ask — an allowlist (W1).** Otherwise up to `mission_wake_steps` (3) planner steps, admitting only: READ `tool` calls, `research`, `subject`/find, `propose` (a card), `ask_user` (a card), `stage`/`plan` actions on its plan, `sleep`, and `finish`. Refused during a wake, each with a `refused` note: the legacy `draft` action (it writes thread history; a draft is proposed as `draft_thread_message`), `browse` (a browse is started by approving a work stage, never by a wake), and anything else. A **finish during a wake** writes its summary line to the origin thread's history as every finish does, but never changes the thread's next action or date (`_land_finish` gets a flag that skips `advance`); a next step the planner wants is proposed instead. The steps end in one card (the mission goes `waiting_user` as today), a `sleep` (back to sleep with no message; the reason shows on the Missions page), or `finish`. If the steps run out with none of those, the mission goes back to sleep with the same waits (their `fired` keys kept) and the note "Looked; nothing needs you".
5. **Budget.** Wake steps are counted in `wake_steps_used`, not `step_count`, so a long watch is not killed by `mission_step_cap`; every step still charges the daily pro-call allowance (`_bump_call`), and a spent allowance retries in 30 minutes as today (the retry keeps the wake's remaining steps and its consumed occurrence). Work-stage actions stay under `budget_guard` (slice 2).
6. **Who hears it.** The card goes through `_dm_person` and the slice 2 rules: a keeper gets the neutral line and no card; plan words never reach a channel some member may not see; approval by words only in a private conversation; the Mind's snapshot carries no wait reasons or woke lines for a parents-only subject.

## Section 4 — The hand path and the conversation

- **The card** (Missions page, thread card, chat card) of a sleeping mission says what it waits for in words, built by one function `wake.describe(sleep, viewer) -> str` ("Waiting for: 21 days before Kate's 10th birthday (March 1)"; "Waiting for: the plumber's reply"; "Checking piano every Monday"; "Watching the Disney trip for changes"; "until March 20"), with three options: **Wake now** (verb `wake`), **Change the wait** (verb `rewait`, a sheet with the four kinds, a day or lead-time picker, and a deadline), **Stop** (the existing mission stop). **A keeper (W8)** sees "Waiting" with no record words, no Wake now and no Change the wait, and **keeps Stop**: an adult whose own mission a parent later linked to a hidden record can always end it.
- **A plan's stepper** shows a stage's start ("Starts 21 days before the party, March 1"); changing a stage's start by hand edits the plan and bumps `plan.rev`, so old buttons go stale.
- **The record's page** (trip, occasion, program, through `subject_situations`) shows "Argyle is watching this: next check March 1" for a sleeping mission bound to it, **only to a viewer who can see the subject itself** (`subjects.visible`, not `situations.can_see`, which admits keepers; W6), built from `wake.describe` for that viewer; a keeper gets no watching line and no date from that endpoint.
- **Conversation:** "remind me about Disney dining when it opens" → `start_mission_for` with a starting wait; "wake it up" / "watch for her reply instead" / "stop watching the party" → `act_on_situation` with `wake`, `rewait`, stop; "what are you waiting on?" → `list_situations` lists sleeping missions with `wake.describe` for the asker (and, in a channel, under slice 2's channel rule). Every one of these has the hand path above.
- `wake` and `rewait` join `situations.VERBS`; the `act_on_situation` enum is widened to match (the existing parity test, which fails today because the enum lacks `submit`/`verify`, is fixed in the same edit).

## Section 5 — Settings

In `services/settings_registry.py` (group `missions`, page `work?tab=missions`, a new drawer section `missions-wake` "Waking"):

| Key | Default | Meaning |
|---|---|---|
| `mission_wake_steps` | 3 | Planner steps one wake may take |
| `mission_wakes_per_day` | 2 | Wakes per mission per day |
| `mission_watch_max_days` | 90 | Longest watch for a mission with no record end |
| `mission_change_check_minutes` | 5 | How often a record-change wait reads the record |
| `mission_change_settle_minutes` | 10 | Quiet time after the last edit before a change wakes |
| `mission_reply_read_wait_minutes` | 10 | How long a reply wait waits for mail intake's reading |
| `mission_wake_hour` | 8 | Hour a date or weekly wake fires; quiet hours end |
| `mission_quiet_hour` | 21 | Hour quiet hours start |

## Section 6 — Safety

- No write without a tap: a wake admits only the Section 3.4 allowlist; a finish during a wake never advances the thread; a stage's rows still run through `planned.run_stage`.
- Each occurrence fires once (Section 1), so no loop: a met date is consumed, a re-armed weekly check records its day, a settled fingerprint is remembered.
- A changed binding refuses (Section 3.1); a re-bound mission's waits are not carried to the new record.
- A sleeping mission blocks nothing: `subjects.retarget` is allowed while asleep (it bumps `subject_rev`, so the next wake refuses and asks).
- One wake at a time: compare-and-set under `db_lock`.
- Program shortfalls are never stored (Section 2); a paused program is never checked.
- Every limit is a setting; `missions_enabled` off stops all checks (a mission sleeps through it and checks again when it is turned back on; a date that passed fires once).
- HA is not involved; nothing here touches Home Assistant.

## Section 7 — Tests (written first by Claude; Codex implements)

- `tests/test_wake.py`: the four checks against a fake clock (`wake._now`), including the hour; a lead time re-measured after the record moves; the watch end re-derived when the record is postponed (W4); a fired date never firing again after the steps run out and the mission re-sleeps, and a postponed date firing once more (W2); a restart firing once; reply with and without reading; weekly on-plan silent (no planner call), behind and ahead firing, no count stored in any step or row (W7), a pause spanning two check days firing nothing and the first check seven days after resume (W9); an unchanged occasion, program and trip giving the same fingerprint across midnight and across the trips cache ageing, and an edit to the menu (not in the default context) changing it (W3); change settle and reset; quiet hours; the daily limit across re-sleeps; compare-and-set (two fires, one wake); re-check refusals (rev, gone, hidden, creator disabled); a private gift list shared with the creator passing the re-check (W5).
- `tests/test_wake_planner.py`: the `sleep` action and its refusals; a stage with `starts`; the wake allowlist through the real runner — `draft` and `browse` refused, `finish` leaving the thread's next action and date untouched (W1); wake steps outside `step_count`; ran-out goes back to sleep keeping `fired`; steer on a sleeping mission.
- `tests/test_wake_hand_path.py`: `wake`, `rewait`, stop by situation act and endpoints; `start_mission_for` and the new-mission form with a starting wait; `wake.describe`; the record page's watching line, and `GET /api/subjects/{kind}/{sid}/situations` for an excluded mission creator and an excluded thread owner returning no watching line or date (W6); a keeper's card with Stop and nothing else, and the keeper stopping it after the subject became hidden (W8); triage and watchers ignore sleeping missions; settings respected (one test per setting).
- Acceptance on the real registry, only the model faked: `tests/test_wake_party.py` (the invitations stage sleeps until 21 days out; moving the party moves the wake; an RSVP reply wakes the mission and it proposes the headcount), `tests/test_wake_piano.py` (an on-plan week is silent; a behind week wakes a lighter-week proposal whose card states no missed count), `tests/test_wake_trip.py` (a trip date change wakes the dining stage with the new times).
- Every critical path has a test that runs it (a tick, a TestClient request, a node run of the card JS).

## Out of scope

Waiting on another mission; price or availability watching on outside sites; acting without a tap; fan-out into child missions; sending outside the family (drafts only, as before).

## Build split (the user's standing rule)

Claude writes every task's tests first; Codex implements each task via `codex:codex-rescue`; Claude reviews the diff, reruns the gate, updates `system_capabilities.md`, bumps `config.yaml` and commits. Codex reviewed this spec adversarially (W1–W9 folded in) and reviews the whole branch at the end.

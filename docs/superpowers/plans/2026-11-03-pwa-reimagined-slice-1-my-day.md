# PWA reimagined, slice 1: My Day, the warm brief — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every adult (parent, household adult, keeping-up adult) opens the app on one My Day: the date line and a pencil, the greeting with the weather, Argyle's one sentence, the hero for the next thing that happens to them, the Needs-you pile, and the whole day collapsed behind a fade. Nothing a person can do on today's two My Days is lost.

**Architecture:** The brief is a new adult-only renderer in `static/pwa_myday.js` that paints into the existing `#myday-container`. It reads the payloads the page already fetches and three pure functions decide what it says: `pwaNextThing(rows, now)` picks the hero from the rows "Your day" draws (every row builder stamps `data-kind/start/end/title/place/meta`, so the hero and the list can never disagree), `pwaBriefSentence(facts)` writes Argyle's sentence from counts and the one unusual thing, `pwaNeedsYou(inputs, now)` ranks the pile by deadline then consequence. The server grows one read-only route, `GET /api/weather/now`, sharing the current-conditions code the wall's home board already runs. `HeroCard` gains a phone skin (`opts.phone`) so the wall and the phone stay one renderer. "Your day" hosts the rows the existing builders draw today (driver legs and events from `buildTimeline`, passenger cards from `renderMyDayCard`, program rows, routine items, due-soon rows), re-skinned by the slice-0 tokens; converting the driver chronology to `agendaEventRow` waits for slice 6, which owns the drive states.

**Tech Stack:** FastAPI + Jinja, vanilla JS, precompiled Tailwind (`python tools/build_tailwind.py` after any template class change), Playwright live tests via `tests/live_app.py`, node for pure-JS tests. Tests run from `chauffeur/` as `python tests/test_x.py` with `HA_BASE_URL` unset.

**Spec:** `docs/superpowers/specs/2026-11-03-pwa-reimagined-design.md` ("My Day: the warm brief", "Dispositions", "Calls I made" 2, 3, 12, "Suggested slices" item 1). Inventory: `docs/design/pwa-reimagined/current-state-inventory.md` §3, §4, §11 and the `myday-directions.html` gap table (lines 251-276). Mockup: `docs/design/pwa-reimagined/mockups/myday.html` option A. Slice 0 shell: `docs/superpowers/plans/2026-11-03-pwa-reimagined-slice-0-shell.md` (`PwaNav`, the sky tokens, the orb).

## Global Constraints

- Adult overrides stay under `html[data-audience="adult"]`; `renderMyDay` keeps serving every child stage unchanged (kids call it from `setView`, `pwa_profile_checks.py:60`, `test_school_view_live.py`, `test_moments_past_days_live.py`); `pwa_child_shell.*` untouched; the kid live checks stay green.
- One My Day for parent, household adult and keeping-up adult. Helpers and guests keep their current landing (drives / messages); nothing changes for them in this slice.
- Nothing a person can do today is removed. The inventory's §3 and §4 rows and the `myday-directions.html` gap table are the checklist: status chooser and two-tap clear, requests Yes / Can't / withdraw / Ask for something, routine check and streak, due-soon check / detail / See all / Still open / Clear all, passenger ride facts (legs, Where?, Message, Add a moment), optional Going / Skip / Undo, driver legs with Completed / Driving / Past / Leave / Arrive states, lateness, car-swap cue, prep pills and Confirm packed, program rows and Open the session, untimed programs, loading / failure / empty states, previous / next day and swipe.
- Every hero button is a hand path that exists today: a drive's primary is the leg's `openActionSheet(...)` (the row's tap), its secondary opens the event dialog where "Hand to someone outside" lives; any other kind's single button is that row's own tap. No hero button without a row behind it.
- Numbers come from their owning payloads: drives from `scheduleData`'s stamped legs, rides from `/api/members/{id}/day`, reviews from the chores/redemptions/rewards payloads, requests from `/api/requests`, proposals from `/api/proposals?status=proposed`, situations from `/api/situations?kinds=finding,insight`, needs-a-driver from `scheduleData.true_unassigned`, status from `status_days`. The brief computes nothing a module already computes.
- Weather degrades: no HA, no entity, or no state → `null` and the slot is omitted (never an empty box). Route `GET /api/weather/now` sits under the existing `(ANY, '/api/weather/*', WALL, None)` rule (`services/auth.py:308`), so no auth rule is added; `tests/test_auth.py` must stay green.
- The sentence is a pure function; the numbers in it come from the facts and are never rephrased by a model in this slice.
- Event lifetime is clock-only: a row whose `end` has passed is never the hero (`[event-end-time-is-the-end]`); an underway row (start ≤ now ≤ end) outranks a later one.
- No browser dialogs. Sheets through `_pwaModal`; confirmations through `promptConfirm`; text through `promptInput`.
- The person's hue stays the accent; the sky and cards are slice-0 tokens (`--pwa-card`, `--pwa-card-raised`, `--pwa-radius`, `--pwa-ink`).
- Tab label for adults becomes "My Day" (`pwa_shell.js:139` reads `'Today'` today); `tab-drives` is hidden for every adult, `tab-myday` shown; `chauffeur_view` for an adult that read `drives` resolves to `myday`.
- Tailwind rebuilt before any live run; `chauffeur/config.yaml` → `2.499.752` and a `system_capabilities.md` entry in the last task.

## Review Focus

1. A keeping-up adult (no driver, scope `keeping_up`) must land on My Day with no drive hero and no "Start drive" anywhere, and the family's day in "Your day" (Task 6 live profile `keeping`).
2. A driver whose next leg's event has ended must see the following thing as hero, never the passed launch, and at 18:00 with nothing left the hero slot must be absent, not "all done" (Task 2 node cases `passed_rows_never_next`, `nothing_left_means_no_hero`; Task 6 live at the 18:00 clock).
3. A parent with zero requests, zero reviews, zero proposals, zero situations and no unassigned events must get NO Needs-you section at all (Task 4 node case `empty_pile_is_absent`; Task 6 live `adult` profile).
4. The pencil must not appear when no option applies (a helper would never reach it; a household adult with `can_request` false and no status rights — see Task 7's rule) and must never be a dead control (Task 7's rule + Task 6 live).
5. Weather with HA absent must omit the slot and log nothing as an error; weather with a current state but no forecast must still show temperature and condition (Task 1 TestClient cases `no_ha_is_null`, `state_without_forecast`).

---

### Task 1: `GET /api/weather/now`, the conditions the wall already reads

**Files:**
- Modify: `chauffeur/services/home_board.py:5476-5493` (lift into `current_conditions(settings=None) -> dict | None`), `:5506-5508` (build reads it)
- Modify: `chauffeur/main.py:2283` (add the route beside `/api/weather/daily`)
- Test: `chauffeur/tests/test_weather_now.py`

**Interfaces:**
- Produces: `home_board.current_conditions(settings=None) -> {'temp_now': int|None, 'condition': str|None, 'emoji': str|None, 'line': str|None} | None` (None when no entity or no state; `line` is today's `family_digest.weather_line(today)` or None), and `GET /api/weather/now` returning that dict or `null`, cached like the daily route is not (no cache; it is one HA state read).
- `build()` keeps emitting `temp_now`, `condition`, `condition_emoji` exactly as before, now from the helper.

- [ ] **Step 1: Write the failing test** (`tests/test_weather_now.py`, harness style, `TestClient(main.app)` with `CHAUFFEUR_DATA_DIR` isolated the way `tests/test_pwa_adult_shell_live.py:17-19` does, monkeypatching `services.ha_api.get_state`, `get_entities`, `get_weather_forecast` and `storage.get_settings`):

```python
def scenario_no_ha_is_null():            # get_entities -> [], settings weather_entity '' -> GET returns null, status 200
def scenario_state_without_forecast():   # get_state -> {'state': 'cloudy', 'attributes': {'temperature': 71.4}}, forecast [] -> {'temp_now': 71, 'condition': 'cloudy', 'emoji': <family_digest._WEATHER_EMOJI['cloudy']>, 'line': None}
def scenario_line_is_todays_forecast():  # forecast for today -> 'line' == family_digest.weather_line(today)
def scenario_build_still_says_the_same(): # home_board.build(...)['temp_now'|'condition'|'condition_emoji'] equal the helper's fields with the same mocks
def scenario_wall_tier_serves_a_member_and_a_device():  # X-Member-Token and X-Device-Token both 200; no token -> 401 (reuse the token helpers test_auth.py uses)
```

- [ ] **Step 2: Run it to see it fail** — `python tests/test_weather_now.py` → `AttributeError: current_conditions` / 404.
- [ ] **Step 3: Implement.** Move lines 5479-5493 into `current_conditions(settings=None)` (settings default `storage.get_settings()`), keep the `print` on failure, return None when `ent` is falsy or `get_state` is empty; add `'line'` from `family_digest.weather_line(datetime.date.today())` inside its own try. `build()` calls it once. Route: `@app.get("/api/weather/now") def weather_now(): return home_board.current_conditions()`.
- [ ] **Step 4: Run** `python tests/test_weather_now.py && python tests/test_home_board.py && python tests/test_auth.py` → all ok.

---

### Task 2: Every "Your day" row says what it is, and `pwaNextThing` picks the hero

**Files:**
- Create: `chauffeur/static/pwa_myday.js` (pure functions first; the renderer arrives in Task 7)
- Modify: `chauffeur/static/pwa_shell.js:456-476` (`pwaDriveRow`, `pwaEventRow` stamp the dataset), `chauffeur/templates/app.html:9478` (`renderLegPill` passes `start`/`end`/`legId`/`eventId`/`location` through to `pwaDriveRow` — read how `actionArgs` is built and add the fields it already has in scope), `:1697-1760` (`myDayProgramRow` stamps `data-kind="session"`), `:3342` (`renderMyDayCard` stamps `data-kind="ride"`), `:1262` (`renderRoutineSection` items stamp `data-kind="routine"` with `data-start` = the item's time today), `:1318` (`renderDueSoonRow` stamps `data-kind="task"` with `data-end` = due date end)
- Test: `chauffeur/tests/test_pwa_next_thing.py` (node, `_function_text` pattern from `tests/test_moment_media_token.py:57`)

**Interfaces:**
- Produces: dataset contract on every row the day draws: `data-kind` ∈ `drive|event|ride|session|routine|task`, `data-start` and `data-end` (ISO local, `data-end` may equal start for a point), `data-title`, `data-place` (may be empty), `data-meta` (one line: "18 min drive · the Highlander" / "Until 5:00 PM"), `data-state` ∈ `upcoming|active|past|completed|done` (`pwaDriveRow` already has `data-next`; keep it and add `data-state` with the same value), `data-primary` (the JS expression the row's tap runs, e.g. `openActionSheet(...)`), `data-secondary` (drives only: `openEventModal('<key>')`), `data-leg-id`, `data-event-id`.
- `pwaNextThing(rows: Array<{kind,start,end,title,place,meta,state,primary,secondary,legId,eventId}>, now: Date) -> row | null`: drop rows with `end < now` or state `completed|done|past`; prefer a row with `start <= now <= end` (first by start), else the earliest `start >= now`; ties by kind order `drive, ride, event, session, routine, task`; `null` when nothing qualifies.
- `pwaRowsFromDom(container) -> rows` reads the dataset of every `[data-kind]` element in a container (a thin adapter; the pure function never touches the DOM).
- `pwaHeroNext(row, now) -> next` adapts a row to the `HeroCard` shape: `{ start, end, title, location: place, kind, leave_at|null, leave_label|null, travel_mins|null, driver|null, live, minutes_until, actions: [{label, run}] }` where for a drive `leave_at` = the leg start, `leave_label` = "Leave at h:mm", `actions` = `[{label:'Start drive', run: primary}, {label:'Ask for cover', run: secondary}]`; for every other kind one action `{label: <kind label>, run: primary}` with labels `ride → 'Details'`, `event → 'Details'`, `session → 'Open the session'`, `routine → 'Done'`, `task → 'Open'`.

- [ ] **Step 1: Write the failing node test** with cases (rows as plain objects, `now` fixed at 2026-11-03T15:12 local):

```
'picks_the_earliest_upcoming':   drive 15:40, event 16:00 → drive
'underway_outranks_later':       event 14:00-17:00 underway, drive 15:40 → event
'passed_rows_never_next':        drive end 14:00 past, ride 16:00 → ride
'completed_state_is_skipped':    drive state completed start 15:30, event 16:00 → event
'nothing_left_means_no_hero':    only past rows → null
'kind_breaks_ties':              ride and drive both 15:40 → drive
'drive_hero_has_two_actions':    pwaHeroNext(drive) → actions ['Start drive','Ask for cover'], leave_label 'Leave at 3:40 PM', location, travel_mins from meta '18 min drive'
'routine_hero_has_one_action':   pwaHeroNext(routine) → one action 'Done'
'keeping_up_rows_have_no_drive': rows without drives → hero kind != 'drive'
```
and a source scenario: `pwaDriveRow`, `pwaEventRow`, `renderMyDayCard`, `myDayProgramRow`, `renderRoutineSection`, `renderDueSoonRow` each contain `data-kind="` with the right value, and `pwaDriveRow` stamps `data-start`, `data-end`, `data-primary`, `data-secondary`.

- [ ] **Step 2: Run** `python tests/test_pwa_next_thing.py` → FAIL (`pwaNextThing` not found).
- [ ] **Step 3: Implement** the three functions at top level of `static/pwa_myday.js` (classic script, column-0 statements, no DOM in `pwaNextThing`/`pwaHeroNext`), and stamp the datasets in each builder. `renderLegPill` (`app.html:9478`) already knows `timeStr`, `title`, `mins`, `actionArgs`, `legId`; find the leg's start/end timestamps where it is called from `buildTimeline` (10110-10215) and pass them as two more parameters with defaults so other callers stay valid. `pwaEventRow` has `start`, `event.end`, `event.location`. `renderMyDayCard` has `r.start`, `r.end`, `r.title`, `r.place`. Program rows: the window's start/end. Routine items: today at the item's time; `data-end` = start + 30 min. Due-soon: `data-start` = `data-end` = due date 23:59.
- [ ] **Step 4: Run** `python tests/test_pwa_next_thing.py && python tests/test_template_js.py && python tests/test_programs_reachable.py && python tests/test_panel_chrome.py` → ok (the programs test reads `renderMyDay` / `buildTimeline` bodies; stamping attributes must not rename anything).

---

### Task 3: The greeting and Argyle's sentence

**Files:**
- Modify: `chauffeur/static/pwa_myday.js` (add `pwaGreeting`, `pwaBriefSentence`, `pwaBriefFacts`)
- Test: `chauffeur/tests/test_pwa_brief_sentence.py` (node)

**Interfaces:**
- `pwaGreeting(hour: number, name: string) -> {word: 'Good morning'|'Good afternoon'|'Good evening', first: string}`: 05-11 morning, 12-16 afternoon, 17-04 evening; `first` = the first whitespace token of `name`, or 'there' when empty.
- `pwaBriefFacts({rows, role, isDriver, needs}) -> facts`: `{drives: n, rides: n, sessions: n, firstDrive: row|null, lastEnd: row|null, unusual: [{kind, text, rank}]}` where `unusual` is built from `needs` (Task 4's cards) with rank = card rank, and from `rows`: a drive stamped `data-late` (lateness) → "You're running N min late to <title>." rank 1; the `needs` kinds map to text: `needs_driver` → "<title> <day> still needs a driver.", `status` → "<person> <status label> today.", `review` → "<name> finished <chore> and is waiting on your OK.", `request` → "<asker> asked you for something.", `proposal` → "<n> proposed events are waiting."
- `pwaBriefSentence(facts) -> string`: sentence one from counts: 0 drives and 0 rides → "Nothing on the road today." ; 1 drive → "One drive today" ; n → "<N spelled out up to twelve> drives today" ; append " and <n> ride(s)" when rides > 0 (a ride = a leg someone else drives you); end with "." ; then, if `unusual` is non-empty, one space and the top-ranked unusual text. Never more than two sentences; never a number the facts do not hold.

- [ ] **Step 1: Write the failing node test** — cases: `greeting_bands` (5→morning, 12→afternoon, 17→evening, 2→evening), `first_name_only` ('Jeff Nelson' → 'Jeff'; '' → 'there'), `two_drives_plain` (→ "Two drives today."), `drive_and_ride` ("One drive today and one ride."), `nothing_on_the_road`, `one_unusual_only` (three unusual facts → exactly one appended, the lowest rank number), `numbers_survive` (every digit/word count in the output equals the facts), `never_three_sentences` (count of '. ' ≤ 1 after trimming).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** at top level in `pwa_myday.js`, pure. **Step 4: Run** `python tests/test_pwa_brief_sentence.py` → ok.

---

### Task 4: The Needs-you pile, ranked

**Files:**
- Modify: `chauffeur/static/pwa_myday.js` (add `pwaNeedsYou`, `pwaNeedsYouInputs`, `pwaOpenNeed`)
- Test: `chauffeur/tests/test_pwa_needs_you.py` (node)

**Interfaces:**
- `pwaNeedsYou(inputs, now: Date) -> cards[]` with `inputs = { role, requests: [], reviews: {chores: [], redemptions: [], pools: []}, dueSoon: [], stillOpen: [], proposals: [], situations: [], unassigned: [events], statusDays: [] , canReview: bool, canAssign: bool }` and each card `{ id, kind, icon, title, why, deadline: Date|null, rank: number, open: {view?, fn?, args?} }`:
  - `request` (each `requests[]` row waiting on me): icon '🙋', title "<from_name> asks: <body truncated 60>", why "waiting on your answer", deadline null, rank 2, open `{fn:'pwaOpenNeedRequests'}`.
  - `review` (parent only, `canReview`): one card per done chore ("<claimed_by_name> finished <title>", why "<points> points waiting on your yes"), per pending redemption ("<member_name> wants <reward_title>", why "<cost> points"), per funded pool ("<title> is funded", why "ready to grant"); rank 3; open `{view:'chores', section:'reviews'}`.
  - `needs_driver` (`canAssign`, events in `unassigned` with start within 7 days, not canceled): icon '🚗', title "<title> needs a driver", why "<weekday> <h:mm> · nobody yet", deadline = event start, rank 1, open `{fn:'openEventModal', args:[eventKey]}`.
  - `task` (`dueSoon` + `stillOpen`): icon '📚', title, why "due <label>" / "overdue", deadline = due date, rank 4, open `{fn:'openKidTaskDetail', args:[id]}`.
  - `proposal` (parent, `proposals.length > 0`): ONE card "N proposed events", why "from <source_from of the first>", deadline = earliest start, rank 3, open `{view:'family', anchor:'proposals-container'}`.
  - `situation` (each situation in group `now`): icon from its kind, title, why = its next move line, deadline = `due_at`, rank 2, open `{view:'family', anchor:'mind-container'}`.
  - `status` (each `statusDays` active today): icon = protocol emoji, title "<person>: <status name>", why = the logistical line or "tap to change", deadline null, rank 1, open `{fn:'pwaOpenStatusSheet'}`.
  - Sort: cards with a deadline first by deadline ascending, then by rank ascending, then by title; cards without a deadline after, by rank then title. Empty inputs → `[]`.
- `pwaOpenNeed(card)` routes: `view` → `setView(view)` then, for `section`, `pwaSelectHouse(section)`; for `anchor`, `document.getElementById(anchor)?.scrollIntoView()`; `fn` → `window[fn](...args)`.
- `pwaNeedsYouInputs()` assembles inputs from the globals: `myRequests.waiting_on_me`, `choresData` / `redemptionsData` / `rewardsData` (with `houseChoresAttention()`'s own filters: chores `state === 'done'`, redemptions pending, pools `funded`), the member-day payload's `due_soon` / `still_open` / `status_days`, `proposalsData`, `mindSituations` filtered to group `now`, `scheduleData.true_unassigned || scheduleData.unassigned`, `canReview = role === 'parent' && pwaAllowed('chores') && !houseRevealListsOnly`, `canAssign = role === 'parent' || role === 'adult'`.

- [ ] **Step 1: Write the failing node test** — cases: `empty_pile_is_absent` (all empty → `[]`), `deadlines_come_first` (a task due tomorrow before a request without deadline), `needs_driver_outranks_review_on_the_same_day`, `non_parent_gets_no_reviews` (canReview false, chores done present → no review cards), `proposals_fold_into_one_card`, `status_is_rank_one_without_deadline` (status card before request card), `unassigned_beyond_seven_days_is_skipped`, `every_card_has_a_hand_path` (each card's `open` has `view` or `fn`, and `fn` ∈ the allowed set `['pwaOpenNeedRequests','openEventModal','openKidTaskDetail','pwaOpenStatusSheet']`).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** pure functions at top level; `pwaNeedsYouInputs` and `pwaOpenNeed` may touch globals and DOM. **Step 4: Run** `python tests/test_pwa_needs_you.py` → ok.

---

### Task 5: `HeroCard`'s phone skin, and the card builders the phone shares

**Files:**
- Modify: `chauffeur/templates/components/hero_card.html:152-260` (`html(next, opts)` gains `opts.phone`)
- Modify: `chauffeur/templates/app.html:113-120` (include `components/hero_card.html` and `components/agenda_row.html` after the shell assets; `agenda_row` is included now because slice 0 promised it and Plan (slice 5) reads it)
- Modify: `chauffeur/static/pwa_shell.css` (the `.pwa-hero` skin)
- Test: `chauffeur/tests/test_hero_card_phone.py` (node + source)

**Interfaces:**
- `HeroCard.html(next, { phone: true, now })` returns a `<section class="pwa-hero">` with: `<p class="pwa-hero-kicker">` = "<kind label> · <countdown>" (kind labels: drive → "Next departure", ride → "Next ride", event → "Up next", session → "Next session", routine → "Right now" when underway else "Up next", task → "Due"; countdown from `HeroCard.countdown(next, now).text`), `<h2 class="pwa-hero-big">` = `next.leave_label` for a drive else the start clock, `<p class="pwa-hero-who">` = `next.title`, `<p class="pwa-hero-meta">` = place · meta (travel + car when present), and `<div class="pwa-hero-actions">` with one `<button class="pwa-btn-primary">` for `next.actions[0]` and, when present, `<button class="pwa-btn-secondary">` for `next.actions[1]`; each button's `onclick` is the action's `run` string. The wall's `html(next, opts)` without `phone` is byte-identical to today (`tests/test_home_board.py:717`, `test_screensaver.py:440` and `test_kitchen_overlay.py:57-74` read it).
- CSS (`pwa_shell.css`, adult-scoped): `.pwa-hero { background: var(--pwa-card-raised); border-radius: var(--pwa-radius); padding: 18px; box-shadow: 0 10px 30px rgb(from var(--pwa-accent) r g b / .12) }` — if `rgb(from …)` is not supported by the test Chromium, use `color-mix(in srgb, var(--pwa-accent) 12%, transparent)` (the implementer picks one and says which); kicker 12px/700/uppercase/.08em in `var(--pwa-accent)`; big 30px/700/-.02em; who 16px; meta 13px muted; buttons 13px padding, 14px radius, primary `var(--pwa-ink)` on white text, secondary `rgba(31,29,43,.06)`; dark variants through the tokens.

- [ ] **Step 1: Write the failing test** — node: render `HeroCard.html(driveNext, {phone:true, now})` in a stub `document`-free environment (the component uses string building; check `tests/test_board_render.py:35-76` for how it is loaded) and assert the kicker text, the big line "Leave at 3:40 PM", two buttons with the right labels and `onclick` strings, and that `HeroCard.html(driveNext, {})` output is unchanged from a saved golden of today's output for the same `next` (compute the golden in the test from the committed file at `git show HEAD:chauffeur/templates/components/hero_card.html` so the test proves the wall path did not move). Source: `app.html` includes both components, `pwa_shell.css` has `.pwa-hero`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `python tests/test_hero_card_phone.py && python tests/test_home_board.py && python tests/test_screensaver.py && python tests/test_kitchen_overlay.py && python tests/test_template_js.py` → ok; `python tools/build_tailwind.py`.

---

### Task 6: The live proof (written first; Task 7 makes it green)

**Files:**
- Create: `chauffeur/tests/test_pwa_myday_live.py` (pattern: `tests/test_pwa_adult_shell_live.py` — isolated `CHAUFFEUR_DATA_DIR`, `live_app(seed)`, `page.route` mocks, fixed clock 15:12, `PWA_REVIEW_OUTPUT` screenshots)
- Modify: `chauffeur/tests/test_pwa_adult_shell_live.py:322-371, 395-434` (the parent block: `.pwa-next` assertions become hero assertions — `.pwa-hero h2` equals the upcoming leg's `data-time-label`, the hero's primary opens `#action-sheet`; the `#pwa-page-heading h2 == 'Your afternoon'` assertion becomes the greeting `'Good afternoon'`; `.pwa-next` count-0 after completion becomes "the hero moved to the next row"; the 18:00 block asserts no hero and `.pwa-attention` absent), the `tabs` expectation (`len(tabs) == 5` stays: My Day, Plan, Household, Messages, More), and `chauffeur_view` seeded as `'myday'`
- Modify: `chauffeur/tests/pwa_profile_checks.py` and `tests/test_school_view_live.py` / `test_moments_past_days_live.py` only if they assert on the adult `renderMyDay` output (check first; kids are unchanged)

**Interfaces:** profiles seeded like the adult-shell test (`parent` d1 driver, `adult` d2 driver, `keeping` no driver on `keeping_up`), plus mocks: `/api/schedule` with the three events and stamped legs (copy the adult-shell schedule), `/api/members/*/day` with one ride (a leg driven by d2 at 17:30 for `parent`), `due_soon` one task due tomorrow, `status_days` one active "Sick day" for `keeping`'s day only, `/api/routines/day` with one item at 20:00, `/api/requests` with one waiting-on-me for `parent`, `/api/chores` with one done chore (parent review), `/api/proposals?status=proposed` one row (parent), `/api/situations?*` `[]`, `/api/weather/now` `{temp_now: 71, condition: 'partlycloudy', emoji: '⛅', line: 'clearing by 5'}` for `parent`, `null` for `adult` (the omitted-slot case), `/api/practice-windows` one window 21:00, `/api/programs` one.

- [ ] **Step 1: Write the test** with scenarios per profile (`run()` loops `parent`, `adult`, `keeping`):
  - `greeting_and_weather`: `.pwa-brief-greet` text starts with "Good afternoon" and ends with "Alex"; `parent` shows `.pwa-brief-weather` with "71°"; `adult` has no `.pwa-brief-weather`.
  - `sentence_from_facts`: `.pwa-brief-sentence` text for `parent` == `pwaBriefSentence(pwaBriefFacts(...))` evaluated in the page (the live number must match the pure function on the same inputs), contains "drive", and has at most two sentences.
  - `hero_is_the_next_row`: `.pwa-hero` exists for `parent`; `.pwa-hero h2` text equals the first `[data-kind][data-state="upcoming"]` row's time label; clicking `.pwa-btn-primary` opens `#action-sheet` (close it); `.pwa-btn-secondary` opens `#event-modal` (close it). For `keeping`: `.pwa-hero` absent or its kicker is not "Next departure" and no button reads "Start drive".
  - `needs_you_pile`: `parent` shows `.pwa-need` count 4 (status? no — status is on `keeping` only: request, review, task, proposal → 4) in deadline-then-rank order with the task (due tomorrow) first; tapping the review card lands on Household with `#chores-container[data-section="reviews"]`; back on My Day tapping the request card opens a sheet containing a "Yes" button. `adult` (no requests, no reviews, no proposals) → no `.pwa-need`, no "Needs you" heading. `keeping` → the status card present; tapping it opens a sheet with the protocol chooser or the clear control.
  - `pencil_rule`: `parent` has `.pwa-brief-pencil` and tapping it lists "Family status" and "Ask for something"; after `page.evaluate("localStorage.setItem('chauffeur_myday_day_open','1')")` and re-render, `.pwa-brief-day` is not collapsed.
  - `your_day_collapsed_then_open`: `.pwa-brief-day.is-collapsed` by default with `.pwa-brief-expand` reading "Show the whole day"; the rows inside carry `data-kind`; click expands; the state survives `pwaRenderBrief()`; `#day-nav` next → the following day renders expanded and without a hero; prev → today again.
  - `nothing_removed`: on the driver's day the leg row's tap still opens `#action-sheet`; the ride row shows a "Message" button; the routine item's checkbox posts `**/api/routines/*/check` (route it and record); the due-soon row's check posts `**/api/kid-tasks/*/complete`.
  - `evening_has_no_hero`: clock to 18:30, `buildTimeline()` + `pwaRenderBrief()` → `.pwa-hero` absent and the sentence does not say "0".
  - `tabs_and_landing`: every adult profile has `#tab-myday` visible with label "My Day" and no `#tab-drives`; `chauffeur_view` 'drives' seeded for `adult` still lands on My Day.
  - `widths_and_dark`: 360 and 390 widths without horizontal scroll; `applyTheme('dark')` screenshot; `prefers-reduced-motion` page has no running animation on `.pwa-brief`.
  - Screenshots: `myday-{profile}-light.png`, `myday-parent-dark.png`, `myday-parent-360.png`, `myday-parent-expanded.png`, `myday-parent-pencil.png`.
- [ ] **Step 2: Run it to see it fail** (before Task 7): `python tests/test_pwa_myday_live.py` → FAIL on `.pwa-brief-greet` missing.
- [ ] **Step 3: After Task 7, run** `python tests/test_pwa_myday_live.py && python tests/test_pwa_adult_shell_live.py` → green for every profile, kid checks included.

---

### Task 7: The brief itself: routing, the screen, the pencil, Your day

**Files:**
- Modify: `chauffeur/static/pwa_myday.js` (add `pwaRenderBrief`, `pwaBriefDaySection`, `pwaOpenPencil`, `pwaOpenStatusSheet`, `pwaOpenNeedRequests`, `pwaToggleDay`)
- Modify: `chauffeur/templates/app.html:863-906` (`setView('myday')` for adults → `pwaRenderBrief()`), `:1020-1087` (`applyRoleTabs`: every adult shows `tab-myday`, hides `tab-drives`; keeping-up lands on `myday`; `chauffeur_view === 'drives'` for an adult becomes `myday`), `:3021` (`renderMyDay` early-returns to `pwaRenderBrief()` when `pwaIsAdult()`), `:430-431` (`#myday-container` hosts `#myday-content`; unchanged markup)
- Modify: `chauffeur/static/pwa_shell.js:139` (labels `'My Day'` for adults), `:389-437` (`pwaPageHeading`: on `myday` for adults draw nothing; the brief owns its date line), `:301-363` (`pwaRefreshOverview`: on `myday` for adults do nothing; the `.pwa-next` card is replaced by the hero)
- Modify: `chauffeur/templates/app.html` `:1230` (`mydayShift` also re-renders the brief for adults), `:3073-3078` (the launch row stays for kids; adults get it as the hero)
- Modify: `chauffeur/static/pwa_shell.css` (the brief's skin: `.pwa-brief`, `.pwa-brief-date`, `.pwa-brief-greet`, `.pwa-brief-weather`, `.pwa-brief-sentence`, `.pwa-need`, `.pwa-brief-day`, `.pwa-brief-fade`, `.pwa-brief-expand`)
- Test: `chauffeur/tests/test_pwa_myday_live.py` (Task 6 wrote it first; this task makes it green)

**Interfaces:**
- `pwaRenderBrief()`: paints into `#myday-content`, in order: `.pwa-brief-date` (the selected day's "Tuesday, November 3" via the existing `updateMyDayLabel` text + a `<button class="pwa-brief-pencil" aria-label="What's on my day">` only when `pwaPencilOptions().length > 0`), `.pwa-brief-greet` (`pwaGreeting`, the word on line one, the first name on line two) with `.pwa-brief-weather` to the right when `pwaWeather` (fetched once per render from `api/weather/now`, cached 10 min, null → omitted), `.pwa-brief-sentence`, the hero (`HeroCard.html(pwaHeroNext(pwaNextThing(rows, now)), {phone:true, now})` or nothing when null; for a day other than today no hero), the Needs-you section (`<h3>Needs you <span class="pwa-count">N</span></h3>` + one `.pwa-need` per card, each `onclick="pwaOpenNeed(card)"` by index into `window.pwaNeedCards`; the "Ask for something" chip under the pile when `kidCan('can_request')`; the whole section absent when `[]`), then "Your day" (`pwaBriefDaySection`). Loading: the greeting and the date paint at once; the rest waits on `Promise.allSettled` of the fetches, the hero and pile sections show a one-line "Loading your day…" meanwhile; a failed day fetch shows "Could not load your day." with a Try again button that calls `pwaRenderBrief()`.
- The rows: for a driver, `buildTimeline()` has already drawn `#pane-drives` for the active date; `pwaBriefDaySection` moves that pane's `.pwa-leg-row`, `.pwa-event-row`, `.pwa-program-row` nodes into `.pwa-brief-day` (adopting, not cloning, so their `onclick` handlers live); for a passenger adult, the rides + timed program rows HTML that `renderMyDay` builds at `app.html:3095-3105` is produced by a new `myDayTimelineHtml(data, programItems)` (a pure extraction of those lines; kids and adults both call it); routine items (`renderRoutineSection`) and due-soon rows (`renderDueSoonSection`) are appended into the same list in time order (routine at its time, due-soon at the end). A keeping-up adult gets the family's day: `buildTimeline()`'s Family branch rows for the active date (`#pane-events`), adopted the same way.
- Collapsed state: `.pwa-brief-day` gets class `is-collapsed` (max-height 150px + the fade from the mockup: `linear-gradient(to bottom, transparent, var(--pwa-sky-bottom))`) and a `.pwa-brief-expand` button "Show the whole day ⌄" / "Show less ⌃"; `pwaToggleDay()` flips it and stores `localStorage['chauffeur_myday_day_open'] = '1'|'0'`; a day other than today renders expanded regardless; default collapsed. The section header is "Your day · N things · 9:00 AM – 6:30 PM" (count and span from the rows); with zero rows the section reads "Nothing scheduled" and has no fade.
- Day navigation: `#day-nav` (prev / next) keeps working on My Day for adults and calls `mydayShift(delta)`, which for a driver also moves `activeDateIndex` (`pwaSelectDay`) so `#pane-drives` is the right day before adoption; swipe on `#myday-container` (`app.html:1239-1260`) keeps working.
- The pencil (`pwaOpenPencil()`): a `_pwaModal` sheet titled "My Day" listing `pwaPencilOptions()`: "Family status" (parent/adult, today or future: the existing chooser — `toggleStatusSetRow` content rendered inside the sheet via `renderStatusBanner`'s set row and `statusProtocolsCache`), "Ask for something" (`kidCan('can_request')` → `askForSomething()`), "Show the whole day by default" (a toggle writing `chauffeur_myday_day_open`). Zero options → no pencil.
- The status sheet (`pwaOpenStatusSheet()`): a `_pwaModal` sheet whose body is `renderStatusBanner(status_days, dateStr)` (the existing banner with the protocol chooser and the two-tap clear), so the hand path is byte-for-byte the one that exists.
- `pwaOpenNeedRequests()`: a `_pwaModal` sheet whose body is `renderRequests()` (Yes / Can't / withdraw exactly as today).
- CSS values from the mockup: date line 15px muted centred; greeting 52px/700/-.03em (44px under 360px); weather block: 34px/600 temperature, 12px muted line, absolute right; sentence 17px muted max-width 300px; `.pwa-need` = `--pwa-card` fill, 22px radius, 16px 18px padding, icon tile 40px/14px radius `rgba(31,29,43,.05)`, title 15px/600, why 13px muted, chevron faint; `.pwa-brief-day` rows keep their builders' markup and take the card tokens through `pwa_shell.css` (`.pwa-agenda-row` background `--pwa-card`, radius 18px, no separators).

- [ ] **Step 1: Read Task 6's live test** (it exists before this task starts) and the mockup; list every assertion.
- [ ] **Step 2: Implement** the routing first (tab rules, labels, `setView`), then `pwaRenderBrief` with the greeting, weather, sentence, hero; then Needs you + the pencil + the status and requests sheets; then "Your day" with the adoption, the fade and the memory. Run `python tools/build_tailwind.py`.
- [ ] **Step 3: Run** `python tests/test_pwa_myday_live.py` (Task 6), `python tests/test_pwa_adult_shell_live.py`, `python tests/test_template_js.py`, `python tests/test_programs_reachable.py`, `python tests/test_pwa_next_thing.py`, `python tests/test_pwa_needs_you.py`, `python tests/test_pwa_brief_sentence.py` → all green.

---

### Task 8: Record it, gate it, ship it

**Files:**
- Modify: `chauffeur/docs/ui_design_guide.md` (extend "Adult PWA, reimagined: the vocabulary" with "My Day, the brief": the section order, the dataset contract on rows, `pwaNextThing` as the one source of "next" on the phone, the Needs-you ranking, the pencil rule, the collapsed-day memory key)
- Modify: `chauffeur/system_capabilities.md` (new top entry `v2.499.752`), `chauffeur/config.yaml` (→ `2.499.752`)
- Modify: memory `two-my-day-tabs` is retired by this slice (the controller does it, not the implementer)

- [ ] **Step 1: Docs and version.**
- [ ] **Step 2: Gate** (from `chauffeur/`, `HA_BASE_URL` unset):

```bash
python tests/test_weather_now.py && python tests/test_pwa_next_thing.py && python tests/test_pwa_brief_sentence.py && python tests/test_pwa_needs_you.py && python tests/test_hero_card_phone.py && python tests/test_home_board.py && python tests/test_screensaver.py && python tests/test_kitchen_overlay.py && python tests/test_programs_reachable.py && python tests/test_template_js.py && python tests/test_tailwind_build.py && python tests/test_auth.py && python tests/test_panel_chrome.py && python tests/test_argyle_orb.py && python tests/test_pwa_nav.py && python tests/test_pwa_sky.py && python tests/test_pwa_myday_live.py && python tests/test_pwa_adult_shell_live.py && python tests/test_school_view_live.py && python tests/test_moments_past_days_live.py
```

- [ ] **Step 3: Commit** as one commit `feat(pwa): slice 1 of the reimagined PWA, My Day the warm brief (v2.499.752)` and push.

---

## Sequencing calls (check these while reading)

1. **"Your day" keeps today's row builders in this slice.** The spec draws the driver chronology with `agendaEventRow`; the inventory lists ten states and cues those rows carry (Completed / Driving / Past / Leave / Arrive, lateness, car swap, prep pills, Confirm packed, roll-call entry) that `agendaEventRow` does not know. Slice 6 (the drive) owns those states and converts the rows then; this slice re-skins the existing rows and stamps the dataset contract on them so the hero reads the same rows. Cost if wrong: the conversion happens one slice later.
2. **The member-scoped "next" is computed on the phone**, as a pure function over the rows the day draws, not by growing `home_board._hero(member)` on the server. The member-day payload is built inline in `main.py:13924-14240` (no service to call), while the phone already holds every row with its stamped departure; one function over those rows cannot contradict the list beneath it. The wall's `_hero` is untouched. Cost if wrong: a later move to the server, with the dataset contract as its spec.
3. **Packing cards wait for slice 6.** The PWA has no packing surface today (`packing_card.html` and `pack_dialog.html` are wall-only), so a Needs-you packing card would have no hand path to open. The drive screens carry packing in slice 6; the card joins the pile then.
4. **The status chooser lives in the pencil sheet** (set a status when none is active) and the active status is a Needs-you card that opens the same chooser-and-clear sheet. Nothing of `renderStatusBanner` is rewritten; it renders inside the sheet.
5. **No model rephrase of the sentence in this slice.** The pure sentence ships; the provider hook is a later addition with its own test that the numbers survive.
6. **Helpers and guests are untouched** (they have no My Day today and the spec's "every adult" names parent, household adult and keeping-up).
7. **Slice-0 carry-forwards folded in here** because the first real pushed screen does not arrive until slice 3: none of the `PwaNav` hardening items (stale `pwaDepth` after reload, focus/inert) is in this slice; they ride slice 3 with the first Household screen.

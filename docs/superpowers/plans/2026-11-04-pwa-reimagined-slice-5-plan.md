# PWA reimagined, slice 5: Plan — the family's week, one day at a time — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The adult Plan tab becomes: "Plan" with a "Today" reset; Argyle's one-line lead for the day; people as filter chips; a week strip (weekday, date, weather glyph, event count, a "Proposed" dot); then the selected day as an hour timeline — an all-day band, coloured blocks per event in the person's colour, the now line, the solver's leave-at rows as thin tinted strips — with intake and the Needs-you lane above the timeline. A block tap opens the event the way Plan does today. Previous and next day by swipe and by the arrows. The slice-1 carry-forwards land: one shared clock honouring the 24-hour setting, and the Conflict rule on needs-driver cards. The slice-3 carry-forward lands: `body > header` and `#day-nav` go inert behind a pushed screen. Kids and helpers render unchanged.

**Architecture:** The rows stay the truth. `buildTimeline`'s Family branch keeps building each day's rows with the slice-1 dataset contract, extended with `data-color`, `data-cal` and `data-drivers` so a block knows its colour and its people. A new `static/pwa_plan.js` is pure where it computes: `pwaPlanGeometry(rows, opts)` lays the day out (hour range, lanes for overlaps, block top/height, the all-day band, the now line), `pwaLeaveStrips(sched, dateStr, people)` reads the stamped `legs[].depart` on the schedule's edges, `pwaPlanLead(rows, date, now)` writes the lead, `pwaWeekStrip(dates, counts, weather, proposalDates, today)` words the strip, `pwaPeopleChips(members, sched)` builds the chips, `pwaPlanFilter(rows, chip)` filters. `pwaRenderPlan()` paints the title, lead, chips and week strip into a new `#plan-head` above `#days-container`, and `pwaRenderPlanDay(pane)` replaces each family pane's visible list with the timeline while keeping the row list in the pane (hidden) so the dataset contract and My Day's rebuild rules are untouched; a block's tap runs its row's `data-primary`. A new shared `static/pwa_clock.js` (`pwaClock(date, {use24h})`) replaces the three 12-hour copies and reads the `time_format_24h` setting the page already loads. Weather comes from the existing `GET /api/weather/daily`. `PwaNav.sync` extends `inert` to `body > header` and `#day-nav`.

**Tech Stack:** FastAPI + Jinja, vanilla JS, precompiled Tailwind (`python tools/build_tailwind.py` after any template class change), Playwright live tests via `tests/live_app.py`, node + jsdom via `tests/pwa_pure.py` / `tests/test_pwa_nav.py` patterns. Tests run from `chauffeur/` as `python tests/test_x.py` with `HA_BASE_URL` unset.

**Spec:** `docs/superpowers/specs/2026-11-03-pwa-reimagined-design.md` ("Plan: the family's week, one day at a time", dispositions rows 14-18, 21). Mockup: `docs/design/pwa-reimagined/mockups/plan-and-drive.html` (phone 1; its `<style>` holds the sizes). Inventory: `docs/design/pwa-reimagined/current-state-inventory.md` §6 and the `plan-and-drive.html` gap table (355-363, 400) — the preservation checklist. Slice 1 plan for the dataset contract and My Day's pane rules; slice 3 plan for `PwaNav`.

## Global Constraints

- Adult-only (`html[data-audience="adult"]`, `currentView === 'family'`): driver parents/adults and keeping-up adults. Kids (`kidplan` → `renderMyDay`), helpers and guests (no Plan) are untouched; the kid live checks stay green.
- Nothing a person can do today is removed (inventory §6): every event, errand, practice window, trip banner, suppressed entry and all-day entry of the selected day is reachable (a block or a band item) and opens what the row opens today (`openEventModal`, `openSessionSheet`, `openTripSheet`); intake (parent: Snap a flyer, proposals, Approve / Ignore, the editor) and the Needs-you lane (findings, insights, situations, asks) stay on Plan above the timeline, drawn by `renderProposals` / `renderMind` / `renderHouseThreads` into their ids; the dated status banner (`renderStatusBanner`) stays on other days; `#day-nav`'s prev/next arrows, swipe paging and range paging (`fetchMoreDays`) stay; the keeping-up adult keeps calendar facts and loses driver/leg/car/needs-driver/conflict exactly as today (no leave strips for them).
- The builders keep their names and write targets: `buildTimeline` (Family branch → `#pane-<i>` with `#pane-events`), `renderFamilyDay`, `renderFamilyCard`, `pwaEventRow`, `pwaAgendaRow`, `paneSectionsHtml` (`#proposals-container`, `#mind-container`, `#house-threads`), `renderScheduleAnchors`, `paintPaneSections`, `updateHeaderDate`, `pwaSelectDay`, `prevDay`/`nextDay`. My Day's rules hold: `buildTimeline` removes the adopted brief pane and My Day rebuilds in its own mode before adopting again (`test_pwa_myday_live.py` stays green); `tests/test_pwa_household_live.py` `threads_live_on_plan` (one `#house-threads`, visible on Plan, in the viewport after the My Day card) stays green.
- The dataset contract on every Family row gains `data-color` (the block colour: the first calendar's `backgroundColor`, errand `#F59E0B`, suppressed `#6B7280`, practice the teal `#14B8A6`, default `#3B82F6`), `data-cal` (calendar ids joined by `,`) and `data-drivers` (driver ids joined by `,`); existing attributes are unchanged. The timeline computes nothing a row does not carry; the leave strips read the schedule's `initial_edges` / `route_edges` / `final_edges` `legs[].depart` and `mins` (stamped by `services/leave_by.py`) — no new timing math.
- Numbers and words come from the payloads: `scheduleData` (events, errands, edges, drivers, passengers, `calendar_metadata`), `membersData` (`driver_id`, `passenger_id`, `color_code`), `proposalsData` dates, `GET /api/weather/daily?days=7&start=` (`[{date, emoji, condition, high, low, precip}]`, `[]` without HA — the strip then shows no glyphs), `use24h` from `GET /api/settings` `time_format_24h` (already loaded by `loadClockFormat`).
- A people chip filters the blocks on the phone; it never changes what the server sends (`?viewer=` is untouched) and a row whose people cannot be resolved is never hidden by a chip.
- No browser dialogs; sheets via `_pwaModal`. Page JS fetches `apiBase + 'api/...'`. Pure functions never touch `document`/`window`; every top-level statement at column 0.
- The shared clock: `pwaClock(value, {use24h})` → `h:mm` / `HH:mm`; `pwaClockSuffix(value, opts)` → `h:mm AM` / `HH:mm` (the brief's hero and why lines); the three existing copies (`pwaBriefTime` in pwa_myday.js, the closure in `pwaHouseholdCards`, `pwaTimeLabel` in pwa_messages.js) delegate to it, and every pure input that carries a time gains an optional `use24h` so the pure tests pin both forms. No existing pinned string changes when `use24h` is false.
- Tailwind rebuilt before any live run; `chauffeur/config.yaml` → `2.499.756` and a `system_capabilities.md` entry in the last task.

## Review Focus

1. Two overlapping events (soccer 4:00-5:00, piano 4:30-5:15) must draw side by side in lanes, both tappable, neither hidden under the other (Task 2 pure `overlaps_take_lanes`; Task 3 live `timeline_blocks`).
2. The now line must sit at the right hour on today and be absent on other days; a block whose end has passed is dimmed, never dropped (Task 2 `now_line_today_only`; Task 3 `timeline_blocks`).
3. A keeping-up adult must see blocks and the band but no leave strips, no driver chips and no needs-driver/conflict words, as today's rows for them (Task 3 `keeping_up_plan`).
4. Switching to My Day and back must leave Plan's pane intact and My Day's brief intact (the two views share `#days-container`): the brief adopts its own rebuild, Plan redraws its timeline on return (Task 3 `plan_myday_round_trip`).
5. With the 24-hour setting on, every hour label, block time, leave strip, My Day hero line and Messages time reads `16:30`, never `4:30 PM` (Task 1 pure cases; Task 3 live `clock_24h`).

---

### Task 1: One clock, and the 24-hour carry-forward

**Files:**
- Create: `chauffeur/static/pwa_clock.js` (pure, column 0; script tag before `pwa_myday.js` in `templates/app.html`)
- Modify: `chauffeur/static/pwa_myday.js` (`pwaBriefTime` → `pwaClockSuffix`; `pwaHeroNext`, `pwaNeedsYou` why lines and `pwaBriefFacts` take `opts.use24h` through the existing inputs/now parameters — add an optional trailing `opts` argument, default `{}`), `chauffeur/static/pwa_household.js` (the window pill time through `pwaClock`; `inputs.use24h`), `chauffeur/static/pwa_messages.js` (`pwaTimeLabel(ts, now, opts)` through `pwaClock`), `chauffeur/templates/app.html` (the page passes `{use24h}` from the `use24h` global at the call sites of `pwaRenderBrief`'s pure calls, `pwaHouseholdInputs`, `pwaRenderConversations`; `renderThread`'s message time and `dayDivider` unchanged — they already honour the locale)
- Test: `chauffeur/tests/test_pwa_clock.py` (new), `tests/test_pwa_next_thing.py`, `tests/test_pwa_needs_you.py`, `tests/test_pwa_brief_sentence.py`, `tests/test_pwa_household_cards.py`, `tests/test_pwa_conversations.py` (each +1 case with `use24h: true`)

**Interfaces:**
- `pwaClock(value, opts) -> 'h:mm' | 'HH:mm'` (`value` a Date, ms or ISO; `opts.use24h`); `pwaClockSuffix(value, opts) -> 'h:mm AM' | 'HH:mm'`; invalid → `''`.
- Existing strings are byte-identical when `use24h` is false/absent (every pinned expectation in the five test files stays).

- [ ] **Step 1: Write the failing tests**: `test_pwa_clock.py` (`twelve_hour`, `twenty_four_hour`, `suffix_forms`, `midnight_and_noon`, `invalid_is_empty`, `is_pure`) and one `use24h: true` case in each of the five files (hero `leave_label` "Leave at 16:30", a needs-driver why "Thursday 16:30 · nobody yet", a fact sentence, the household window pill "Piano · Thursday 16:30", a conversation time "16:40").
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** the six files → green.

---

### Task 2: The plan's geometry, lead, strip and chips, pure

**Files:**
- Create: `chauffeur/static/pwa_plan.js` (pure parts; script tag after `pwa_household.js`)
- Test: `chauffeur/tests/test_pwa_plan.py` (node via `tests/pwa_pure.py`)

**Interfaces:**
- `pwaPlanGeometry(rows, opts) -> { hours: [{h, label}], blocks: [{row, top, height, lane, lanes, color, dim}], allDay: [row], now: {top}|null }` with `rows` = the slice-1 row objects (`pwaRowsFromDom` shape) plus `color`, `cal: [id]`, `drivers: [id]`, `eventId`; `opts = {date: 'YYYY-MM-DD', now: Date|ms, hourPx: 66, use24h}`: the hour range is `min(8, floor(first start) - 1)` to `max(19, ceil(last end) + 1)` clamped to 0..24; all-day rows go to `allDay`; timed rows become blocks with `top = (startMins - rangeStart*60) * hourPx/60`, `height = max(22, durationMins * hourPx/60)`; overlapping blocks (start < other end) share a lane group and get `lane`/`lanes` for side-by-side columns; `dim` when `end < now`; `now` only when `date` is now's day, `{top}` from the clock; labels through `pwaClock` ("9 AM" style when 12h: `h AM`, "09:00" when 24h).
- `pwaLeaveStrips(sched, dateStr, opts) -> [{start, end, label, driverId, eventId, color}]`: for every edge in `sched.initial_edges`, `sched.route_edges`, `sched.final_edges` whose `legs[]` carry a `depart` on `dateStr`, one strip per leg: `start = depart`, `end = depart + mins`, `label = '🚗 Leave <time> · <driver first name> drives <passenger first names|event title>'`, `color` the driver's `color_code`; `opts = {drivers, passengers, events, use24h, keepingUp}`; `keepingUp` → `[]`.
- `pwaPlanLead(rows, strips, date, now) -> string`: "Today is …" / "<Weekday> is …" with counts in words: "<n> drive(s) and <m> event(s)." (events = timed non-drive rows; drives = strips), "one all-day thing" when only all-day rows, "quiet." when nothing; e.g. "Tuesday is two drives and three events."
- `pwaWeekStrip(dates, opts) -> [{date, letter, day, today, selected, emoji, count, proposed}]` with `opts = {counts: {date: n}, weather: [{date, emoji}], proposalDates: Set, today, selected}`; `letter` = the weekday's first letter; `emoji` only when the weather has that date.
- `pwaPeopleChips(members, sched) -> [{id: 'everyone'|memberId, name: 'Everyone'|first name, color, cal: [id], driverId}]`: household members (roles parent/adult/child, `status` absent or active), `cal` from `sched.passengers` matching `member.passenger_id`, `driverId` from `member.driver_id`, `color` = `member.color_code`.
- `pwaPlanFilter(rows, chip) -> rows`: `'everyone'` → all; otherwise rows whose `cal` intersects `chip.cal` or whose `drivers` includes `chip.driverId`, plus every row with no `cal` and no `drivers` (unresolvable people are never hidden).

- [ ] **Step 1: Write the failing node test** with a fixture day (soccer 16:00-17:00 Maya, piano 16:30-17:15 Sam, dinner 18:30-19:10, a 9:00 1:1, an all-day trip, a practice window 15:00-15:30; edges with two legs; now 15:12) and scenarios `is_pure`, `hour_range_covers_the_day` (8 AM..8 PM here; a 6 AM row extends it), `overlaps_take_lanes` (soccer and piano `lanes === 2`, different `lane`), `block_geometry` (top/height numbers at 66px/hour, min height 22), `all_day_band`, `now_line_today_only`, `past_blocks_dim`, `leave_strips_from_edges` (two strips, labels "🚗 Leave 3:40 · Jeff drives Maya", colour from the driver; `keepingUp` → none; a leg on another date ignored), `lead_sentences` ("Today is two drives and four events.", "Wednesday is quiet.", "Saturday is one all-day thing."), `week_strip_words` (letters, counts, emoji only where weather exists, `proposed`), `people_chips` (Everyone first, first names, colours, cal/driver resolution, a helper excluded, a disabled member excluded), `filter_keeps_unresolved_rows`, `twenty_four_hour_labels`.
- [ ] **Step 2: Run** → FAIL (module missing). **Step 3: Implement** at column 0. **Step 4: Run** `python tests/test_pwa_plan.py` → ok.

---

### Task 3: The live proof (written before Task 4, green after it)

**Files:**
- Create: `chauffeur/tests/test_pwa_plan_live.py`
- Modify: `chauffeur/tests/test_pwa_adult_shell_live.py` (the Plan block ~462-468: `#pwa-date-strip` → `#plan-head .pwa-week-day`; the `#pane-events .pwa-agenda-row` wait → `#pane-events .pwa-tl .pwa-ev`), `chauffeur/tests/test_pwa_household_live.py` (`threads_live_on_plan` unchanged in intent; if its viewport check needs the lane above the timeline, adjust the comment only)

**Interfaces:** profiles `parent` (d1), `keeping` (keeping_up preset, no driver), `adult` (d2), `navigator` (kid). Mocks: `**/api/schedule?*` → today: a 9:00 1:1 (parent's calendar), soccer 16:00-17:00 (Maya's calendar), piano 16:30-17:15 (Sam's), dinner 18:30 (family calendar), an all-day trip banner, a practice window 15:00; `initial_edges`/`route_edges` with `legs: [{depart: today 15:40, mins: 18}]` for d1 → soccer and a second for d2 → piano; `calendar_metadata` colours; tomorrow: two events; the day after: nothing; `**/api/weather/daily*` → 7 days with emoji (and `[]` for one scenario); `**/api/proposals?*` → one proposal dated tomorrow (parent); `**/api/situations?*` → one finding in `now`; `**/api/settings` → `time_format_24h` false (true in `clock_24h`); `**/api/members/*/day?*`, routines, requests, weather/now, channels as the other tests.

- [ ] **Step 1: Write the test** with scenarios: `plan_head` (parent: `#plan-head .pwa-plan-title` "Plan" 34px, `.pwa-plan-today` "Today" present when the selected day is not today and absent on today; `.pwa-plan-lead` equals `pwaPlanLead(...)` evaluated in the page; `.pwa-people .pwa-pp` texts `['Everyone', 'Alex', 'Robin', 'Maya', 'Sam']` with Everyone `.on`; `.pwa-week .pwa-week-day` seven entries, letters, the selected day's `b` filled with the accent, emoji under each, counts (`.cnt` "4" today, "2" tomorrow, none on the empty day), the `Proposed` dot on tomorrow; `#pwa-page-heading` hidden; screenshot `plan-light.png`); `timeline_blocks` (the pane's `#pane-events` has `.pwa-plan-allday` with the trip, `.pwa-tl .pwa-hr[data-h]` from "8 AM" to "8 PM", `.pwa-ev` blocks whose `top`/`height`/`left`/`width` match `pwaPlanGeometry` over the pane's rows evaluated in the page, soccer and piano side by side, the 9:00 block dimmed (past at 15:12), `.pwa-now` at the 3 PM hour, the row list `.pwa-plan-rows[hidden]` still holding `.pwa-agenda-row`s; two `.pwa-leave` strips with the labels and the drivers' colours; tapping the soccer block opens `#event-modal` with its title; tapping the practice block opens the session sheet; tapping the band item opens the trip sheet); `people_filter` (tap "Maya" → only soccer (and the trip, unresolved people) visible, the chip `.on`, the lead unchanged; tap Everyone → all back); `week_and_arrows` (tap tomorrow in the strip → `activeDateIndex` 1, the pane shows two blocks, "Today" appears; `#btn-prev-day` → back; swipe `#days-container` → next day; the strip's `aria-pressed` follows); `needs_you_and_intake_above` (parent: `#proposals-container` and `#mind-container` precede `#pane-events` in today's pane; the finding card and the proposal row visible); `keeping_up_plan` (keeping: blocks and band present, no `.pwa-leave`, no driver chip text, no "Needs Driver"); `plan_myday_round_trip` (open Plan, tap My Day, the brief draws, back to Plan → the timeline redraws, `#house-threads` once); `clock_24h` (`time_format_24h` true → hour labels "16:00", the leave strip "Leave 15:40", the My Day hero "Leave at 15:40", a Messages row "16:40"); `no_weather` (daily → `[]`: no `.w` glyphs, no errors); `kid_unchanged` (navigator: `#tab-family` hidden, `#tab-kidplan` path unchanged); `widths_and_dark` (360/390 no overflow, `plan-dark.png`, `plan-360.png`); `served.errors()` empty per profile.
- [ ] **Step 2: Run** `python tests/test_pwa_plan_live.py` → FAIL at `#plan-head` missing.
- [ ] **Step 3: After Task 4, run** it and the adjusted tests → green.

---

### Task 4: The Plan view: head, week strip, chips, the timeline

**Files:**
- Modify: `chauffeur/static/pwa_plan.js` (add `pwaRenderPlan()`, `pwaRenderPlanDay(pane)`, `pwaPlanWeather()` (fetch + 10-minute cache like `pwaBriefWeather`), `pwaPlanSelectChip(id)`, `pwaPlanToday()`), `chauffeur/templates/app.html` (`#screen-schedule`: a `<div id="plan-head" class="pwa-adult-only"></div>` before `#day-nav`; `renderFamilyCard`/`pwaEventRow` stamp `data-color`, `data-cal`, `data-drivers` (and the practice/trip rows `data-color`); the Family branch of `buildTimeline` wraps `renderFamilyDay`'s output in `<div class="pwa-plan-rows">` and calls `pwaRenderPlanDay(pane)` for adults after the pane is in the DOM; `updateHeaderDate` calls `pwaRenderPlan()` on the family view; `setView('family')` calls `pwaRenderPlan()` after `buildTimeline`), `chauffeur/static/pwa_shell.js` (`pwaPageHeading`: no entry for `family` for adults; `pwaRefreshOverview`: on the family view the intake and mind containers move BEFORE `#pane-events` (above the timeline), not after; `#pwa-date-strip` hidden on the family view (the week strip replaces it; drives keep it); `pwaSelectDay` unchanged), `chauffeur/static/pwa_shell.css` (the Plan skin)
- Test: Task 3's live test and adjustments; `tests/test_pwa_plan.py`, `test_pwa_myday_live.py`, `test_pwa_household_live.py`, `test_pwa_adult_shell_live.py`, `test_leave_times_live.py`, `test_situations_lane_live.py` (PWA half), `test_template_js.py`

**Interfaces:**
- `pwaRenderPlan()`: paints `#plan-head`: `<h1 class="pwa-plan-title">Plan <button class="pwa-plan-today" onclick="pwaPlanToday()">Today</button></h1>` (the button only when the selected date is not today), `<p class="pwa-plan-lead">` (`pwaPlanLead` over the selected pane's rows and strips), `.pwa-people` chips (`button.pwa-pp[aria-pressed]` with the 22px colour dot, Everyone first), `.pwa-week` (`button.pwa-week-day[aria-pressed]` per date in `currentDates` (7): the letter, `<b>` date, `.w` emoji, `.cnt` count, `.proposed` dot; tap = `pwaSelectDay(i)`); counts come from each pane's `.pwa-plan-rows [data-kind]`. Repaints on `updateHeaderDate`, on a chip tap and after `buildTimeline`.
- `pwaRenderPlanDay(pane)`: reads the pane's `.pwa-plan-rows [data-kind]` rows (+ `data-color/cal/drivers`), applies the active chip, computes `pwaPlanGeometry` and `pwaLeaveStrips`, and writes `<div class="pwa-plan-allday">` (one `button.pwa-band-item` per all-day row, tap = the row's `data-primary`) + `<div class="pwa-tl">` with `.pwa-hr[data-h]` rows (66px) holding `.pwa-ev` blocks (`style="top;height;left:calc(lane/lanes…);width"`, background the row's colour, the title and a `<small>` with the meta's first segment; `aria-label` = title + time; tap = `data-primary`; `.dim` for past), `.pwa-leave` strips (`rgba(91,91,214,.18)` tinted with the driver's colour, 22px, the label) and `.pwa-now` with the time label; the list stays in `.pwa-plan-rows` with `hidden`. Non-adult panes are untouched.
- `pwaPlanToday()`: `reanchorIfDayChanged()` if the anchor moved, then `pwaSelectDay(index of today)`.
- `pwaPlanSelectChip(id)`: stores the active chip in a page variable (session only), repaints every pane's timeline and the lead (the lead counts everyone, never the filter).
- CSS from the mockup: title 34px/700/-.03em with `small`/button 14px accent 600; lead 16px muted 0 0 16px; chips 13px/600 999px `rgba(31,29,43,.05)` muted with a 22px dot, `.on` white ink with the soft shadow; week: 44px columns, letter 12px faint, `b` 36px circle 16px/600, `.on b` accent fill white, `.w` 13px, `.cnt` 16px pill `rgba(31,29,43,.08)` 10px muted, `.proposed` 6px accent dot; timeline: `padding-left 54px`, `.pwa-hr` 66px with the hour label 12px faint at left −54px and a hairline; `.pwa-ev` 14px radius 8px 12px 14px/600 white with `small` 12px .85; `.pwa-leave` 22px 12px accent on the tint; `.pwa-now` 2px `#e0544f` with the time 11px; the band items as pills above the timeline. Dark through the tokens.

- [ ] **Step 1: Read Task 3's test and the mockup**; list every selector and text.
- [ ] **Step 2: Implement** datasets → head → week strip → timeline → strips → filter → CSS; `python tools/build_tailwind.py`.
- [ ] **Step 3: Run** `python tests/test_pwa_plan.py && python tests/test_template_js.py && python tests/test_pwa_plan_live.py && python tests/test_pwa_myday_live.py && python tests/test_pwa_household_live.py && python tests/test_pwa_adult_shell_live.py` → green.

---

### Task 5: Carry-forwards: inert header, the Conflict rule

**Files:**
- Modify: `chauffeur/static/pwa_nav.js` (`sync()` also toggles `inert` + `aria-hidden` on `body > header` and `#day-nav` while `depth() > 0`), `chauffeur/static/pwa_myday.js` (`pwaNeedsYouInputs` passes `isConflict`/`conflictReason` on unassigned rows; `pwaNeedsYou`'s `needs_driver` why reads "<weekday> <h:mm> · <driver> has a conflict" when `isConflict` (the calendar's rule), else "· nobody yet")
- Test: `tests/test_pwa_nav.py` (+1 `header_and_day_nav_go_inert`), `tests/test_pwa_needs_you.py` (+1 `needs_driver_conflict_wording`)

- [ ] **Step 1: Write the failing cases.** **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `python tests/test_pwa_nav.py && python tests/test_pwa_needs_you.py && python tests/test_pwa_argyle.py` → green.

---

### Task 6: Record it, gate it, ship it

**Files:**
- Modify: `chauffeur/docs/ui_design_guide.md` (a "Plan, the week one day at a time" section: rows are the truth + the extended dataset, the pure geometry, the week strip, chips filter-never-hide, leave strips from the solver's legs, the shared clock, inert header), `chauffeur/system_capabilities.md` (new top entry `v2.499.756`), `chauffeur/config.yaml` (→ `2.499.756`)

- [ ] **Step 1: Docs and version.**
- [ ] **Step 2: Gate** (from `chauffeur/`, `HA_BASE_URL` unset):

```bash
python tests/test_pwa_clock.py && python tests/test_pwa_plan.py && python tests/test_pwa_next_thing.py && python tests/test_pwa_needs_you.py && python tests/test_pwa_brief_sentence.py && python tests/test_pwa_household_cards.py && python tests/test_pwa_conversations.py && python tests/test_pwa_nav.py && python tests/test_pwa_argyle.py && python tests/test_template_js.py && python tests/test_tailwind_build.py && python tests/test_auth.py && python tests/test_pwa_plan_live.py && python tests/test_pwa_adult_shell_live.py && python tests/test_pwa_myday_live.py && python tests/test_pwa_household_live.py && python tests/test_pwa_messages_live.py && python tests/test_pwa_argyle_live.py && python tests/test_leave_times_live.py
```

- [ ] **Step 3: Commit** as one commit `feat(pwa): slice 5 of the reimagined PWA, Plan (v2.499.756)` and push.

---

## Sequencing calls (check these while reading)

1. **The timeline is drawn from the rows, not from a second data path.** `renderFamilyDay` keeps building the rows (now with colour and people stamped); the hidden row list stays in the pane; blocks, band items and the lead are computed from the rows' datasets, and a block's tap runs the row's own handler. Two renderings of one row list, one hidden — the price of keeping every existing handler and My Day's pane rules.
2. **Leave strips come from the solver's stamped legs** (`legs[].depart` on the schedule's edges, `services/leave_by.py`), the same seam the driver chronology and the wall hero read; a keeping-up adult gets none, as they get no driver facts today.
3. **People chips filter on the phone** by the row's calendar ids and driver ids resolved through `membersData` (`passenger_id`, `driver_id`); unresolvable rows are never hidden; `?viewer=` is untouched. The lead counts everyone.
4. **Weather is the existing `GET /api/weather/daily`** (WALL tier, `[]` without HA → no glyphs); no new route.
5. **One shared clock lands here** (`pwa_clock.js`), closing the slice-1 24h carry-forward and the slice-4 deferred duplication; `renderThread`/`dayDivider` keep the locale clock they already honour.
6. **Intake and Needs you move above the timeline on Plan** (the spec's placement); on My Day nothing changes. The dated status banner stays where it is.
7. **"Today" resets** through the existing `reanchorIfDayChanged` + `pwaSelectDay`; the driver Today's date strip keeps its collapse/expand; Plan always shows its week.
8. **Not this slice:** the drive screens (slice 6), the header's avatar-top-right Profile (slice 6), a month view, editing events from the timeline (the dialog does that today).

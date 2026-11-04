# PWA reimagined, slice 6: the drive — one screen, two moments; and the header — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For an adult, the drive opens as a pushed screen ("‹ My Day", or the tab it came from) instead of the bottom sheet, in two moments. **Before:** the leave-at card (leave time huge, drive minutes, arrive-by, the car and its range), the stops as a vertical line (where you start, who to pick up and what to bring; the destination with arrive-by and the address), "Everybody in?" and "Packed?" as tap chips (the existing three-state roll call and packing claims), Start drive (primary), Ask someone to cover, then the retro-split options and Mark as completed. **On the road:** the arrival card (place, ETA big, who is aboard), Google / Apple / Waze three across, "Tell {who is waiting}" lines and Send my ETA, Arrived (the one green button), the retro-split options under it. Packing joins My Day's Needs-you pile, the passenger's ride hero carries the ride's own buttons, and the adult header shrinks to the date line with the bell and the avatar (Profile) top-right. Kids keep the bottom sheet and their header.

**Architecture:** The drive keeps every builder, id, handler and endpoint. For an adult, `openActionSheet(...)` pushes `PwaNav.push({id: 'drive'})` and ADOPTS `#action-sheet-content` into the screen body (the slice-3/4 pattern: the node moves, `getElementById` still finds `#btn-start-drive`, `#drive-roll-chips`, `#sheet-state-1`/`#sheet-state-2`, `#btn-arrived`…); `closeActionSheet()` pops for adults and `onPop` runs today's close (stop the live lane, forget the resume, reset). A new `static/pwa_drive.js` holds the pure words — `pwaDriveView(sheet, ctx)` composes the leave-at card, the stops and the arrival card from the `/api/drive_sheet/{leg}` payload (`driveSheetData`) and the drive row's dataset — and `pwaRenderDriveCards()` paints them into two new hosts (`#drive-leave-card` in the before block, `#drive-arrival-card` in the on-road block) after `renderDriveSheet`. The skin is CSS under `html[data-audience="adult"] #pwa-stack`. My Day's pile gains a `packing` kind from the schedule's `prep_by_event` / `prep_confirmed`; ride rows stamp `data-actions` so the passenger hero shows Where? / Message / Add a moment. The header change is markup + CSS + `pwaSyncShell`.

**Tech Stack:** FastAPI + Jinja, vanilla JS, precompiled Tailwind (`python tools/build_tailwind.py` after any template class change), Playwright live tests via `tests/live_app.py`, node + jsdom via `tests/pwa_pure.py`. Tests run from `chauffeur/` as `python tests/test_x.py` with `HA_BASE_URL` unset.

**Spec:** `docs/superpowers/specs/2026-11-03-pwa-reimagined-design.md` ("The drive: one sheet, two moments", "More and the header", dispositions rows 8, 22-24, "Calls I made" 6, 7). Mockup: `docs/design/pwa-reimagined/mockups/plan-and-drive.html` (phones 2 and 3; its `<style>` holds the sizes). Inventory: `docs/design/pwa-reimagined/current-state-inventory.md` §5 (the drive sheet, both states) and §1 (the header) — the preservation checklist. Slice 1 plan (hero, pile), slice 3/4 plans (adoption, `PwaNav`).

## Global Constraints

- Adult-only (`html[data-audience="adult"]`): parents, household adults and helpers who drive (`drives.sheet` / `drives.status_writes` decide what the server returns, as today). Kids keep the bottom sheet (`pwa_child_checks.py` waits on `#action-sheet` and `#sheet-title` 'Your drive' — stays green) and their header.
- Nothing a person can do today is removed (inventory §5): the shared brief (destination, arriving about, be-there-by and late warning, car / range / warning, next drive or "Last drive of the day"); the three-state roll call (unanswered → aboard → not here; never a Start gate; "Come on out" hint); packing with the confirm-on-last-tick; Start (with the best-effort fix); Mark as Completed; Not Staying — Schedule Pick-up / Staying — Cancel Pick-up (both moments, the existing rules); Google / Apple / Waze; the Tell-them catalog from the server; Send my ETA; Arrived with the unresolved-location choice (I've arrived — check it off / Send the family the new time / Still driving); the live lane (wake lock, 45 s ping, Stop/Start preference, auto-arrival); the resume of an in-progress drive (`maybeResumeDriveSheet`, `DRIVE_RESUME_KEY`); map-only opens (`openActionSheet('', place, 'Map to Event')` from the event dialog, `?navigate_dest=` deep links) — a map-only open for an adult is also the pushed screen, on-road moment, without leg operations.
- The builders keep their names, ids and handlers: `openActionSheet(origin, destination, legTitle, eventId, legId)`, `closeActionSheet()`, `renderDriveSheet`, `loadDriveSheet`, `startDrive`, `markCompleted`, `cycleRollCall`, `toggleDrivePrep`, `sendQuickMessage`, `sendMyEta`, `tapArrived`, `handleArrivalCheck`, `declareNotStaying`, `declareStaying`, `openMaps`, `toggleDriveLive`, `enterEnRouteState`, `maybeResumeDriveSheet`; `tests/test_drive_sheet.py` `scenario_the_hand_path_is_on_the_screen` (source strings in app.html: "Everybody in?", 'Send my ETA', 'Arrived', 'Not Staying — Schedule Pick-up', 'Mark as Completed', 'Last drive of the day', `wakeLock`, `DRIVE_PING_MS`…) stays green.
- One pushed drive screen at a time (re-opening the same leg is a no-op; another leg re-uses the screen); `PwaNav` focus/inert/reload rules hold; the Argyle overlay's history accounting holds; hardware Back closes the drive the way the × does today.
- The leave-at card's numbers come from the payload and the row: the leave time is the drive row's `data-start` (the solver's departure, the same value the hero and Plan's strips show), drive minutes from the row's meta / `routeContext`, arrive-by from `sheet.arrive_by`, the car from `sheet.car`, ETA from `sheet.eta_label`, aboard from `sheet.passengers[].aboard === true`, the audience from `sheet.audience`. No timing computed on the phone. Times through `pwaClock` / `pwaClockSuffix` with `{use24h}`.
- Packing cards: one per event today with prep items not yet confirmed (`scheduleData.prep_by_event[baseId]` items, `scheduleData.prep_confirmed[baseId]` falsy) whose drive the viewer has (or whose ride the viewer is on); deadline = that drive's leave time; tap = the drive screen (`openActionSheet` via the row's `data-primary`) for a driver, the event dialog otherwise.
- The header (adults): the date line on the left ("Wednesday, November 4"), the notifications bell and the avatar on the right (the avatar opens Profile, as `#pwa-identity` does today); the name moves into Profile's head; the search button leaves the header (More and Messages carry search — an approved disposition); `#btn-sync`, `#btn-theme`, `#btn-switch-driver`, `#btn-push`, `#btn-pet` stay reachable in Profile (verify each has a Profile action today; add the missing ones to `pwaOpenProfile`'s actions before hiding them in the header). Kids' header unchanged.
- No browser dialogs (the arrival choice stays `promptChoice`). Page JS fetches `apiBase + 'api/...'`. Pure functions never touch `document`/`window`; column-0 top-level statements.
- Tailwind rebuilt before any live run; `chauffeur/config.yaml` → `2.499.757` and a `system_capabilities.md` entry in the last task.

## Review Focus

1. A drive started on the screen, the app reloaded mid-drive: the resume reopens the drive screen in the on-road moment with the live lane running, and hardware Back closes it (stops the lane, forgets the resume) exactly like the × did (Task 2 live `resume_after_reload`).
2. Arrived with an unresolved location: the `promptChoice` sits above the pushed screen (z-order), "Still driving" keeps the screen open on-road, "I've arrived" closes it (Task 2 `arrived_unresolved`).
3. Opening a drive from Plan's timeline block and from My Day's row lands on the same screen with "‹ Plan" / "‹ My Day" and returns to the right tab on Back (Task 2 `opens_from_every_door`).
4. A helper driver (own drives only) gets the drive screen with Start / Arrived and no retro-split; a keeping-up adult never reaches one (Task 2 `helper_drive`).
5. The header: Profile still reaches refresh, theme, switch person, notifications and the critter; the bell still opens the notifications list; search reaches More's field (Task 2 `header_shrinks`).

---

### Task 1: The drive's words, packing cards, the ride hero's buttons — pure

**Files:**
- Create: `chauffeur/static/pwa_drive.js` (pure parts; script tag after `pwa_plan.js`)
- Modify: `chauffeur/static/pwa_myday.js` (`pwaNeedsYou` gains kind `packing`; `pwaHeroNext` takes a ride row's `actions` when present)
- Test: `chauffeur/tests/test_pwa_drive.py` (new, node via `tests/pwa_pure.py` + `clock_source()`), `tests/test_pwa_needs_you.py` (+2), `tests/test_pwa_next_thing.py` (+2)

**Interfaces:**
- `pwaDriveView(sheet, ctx) -> { leave: {time, sub}, stops: [{place, sub, done}], arrival: {place, eta, sub}, cover: bool }` with `ctx = {row: {start, end, meta, title, place}|null, origin, destination, legTitle, now, use24h}`:
  - `leave.time` = `pwaClock(row.start)`; `leave.sub` = "<n> min drive · arrive <arrive_by.short_label or the row's end> · <car.name>[, <range> range][ · ⚠ <car.warn>]" — parts absent when their data is absent; the minutes from the row's meta (`/(\d+) min/`) or omitted.
  - `stops` = `[{place: origin || 'Home', sub: 'Pick up <first names of passengers>' + (prep items ? ' · <items joined by ", ">' : '')}, {place: destination label (sheet.destination.label || legTitle), sub: 'Arrive by <short_label>' + (address ? ' · <address's first segment>' : '')}]`; `done` true on the first stop once any passenger is `aboard === true`.
  - `arrival` = `{place: destination label, eta: sheet.eta_label || '', sub: "<eta minutes> min · <aboard first names> aboard"}` (aboard part omitted when nobody is marked aboard).
  - `cover` true when the row is the viewer's drive and the leg is not in progress (the Ask someone to cover button shows).
  - Map-only (no `sheet`): `leave` null, `stops` `[{place: destination}]`, `arrival` `{place: destination, eta: '', sub: ''}`.
- `pwaNeedsYou(inputs, now, opts)`: `inputs.packing = [{eventId, title, items: [..], leaveAt, primary}]` → cards `{kind: 'packing', icon: '🎒', title: 'Pack for <title>', why: '<items joined by ", "> · leave <time>', deadline: leaveAt, rank: 2, open: {run: primary}}` (the existing open shape for a handler string: read how `pwaOpenNeed` runs `open.fn` / `open.run` and use the one it supports; add `run` support if absent).
- `pwaHeroNext(row, now, opts)`: when `row.kind === 'ride'` and `row.actions` (parsed from `data-actions`: `[{label, run}]`, up to three) is non-empty, the hero's actions are those (first primary); otherwise today's single button.

- [ ] **Step 1: Write the failing tests**: `test_pwa_drive.py` scenarios `is_pure`, `leave_card_words` (fixture payload: car Highlander 210 mi, arrive_by 3:58, row 15:40-15:58 meta "18 min drive" → `leave.time` '3:40', `sub` '18 min drive · arrive 3:58 · Highlander, 210 mi range'), `stops_line` ('Home' / 'Pick up Maya · soccer bag, water'; 'Riverside fields' / 'Arrive by 3:58 · Field 2'), `first_stop_done_when_aboard`, `arrival_card` (eta '3:58', '16 min · Maya aboard'), `map_only`, `twenty_four_hour`; needs-you `packing_is_a_card`, `confirmed_packing_is_not`; next-thing `ride_hero_takes_the_rows_buttons`, `ride_hero_without_actions_unchanged`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** the four files → green.

---

### Task 2: The live proof (written before Tasks 3-4, green after them)

**Files:**
- Create: `chauffeur/tests/test_pwa_drive_live.py`
- Modify: `chauffeur/tests/test_pwa_adult_shell_live.py` (the drive block ~255-279: after the hero primary click wait for `PwaNav.depth() === 1` and `#pwa-stack .pwa-screen[data-screen="drive"] #action-sheet-content`; keep every `driveSheetData` / `#drive-dest` / roll-call / `#btn-start-drive` / dark / overflow assertion; close via `.pwa-back` instead of 'Close drive details' and also once via `closeActionSheet()`; the second block ~427-432 likewise), `chauffeur/tests/test_pwa_myday_live.py` (~340-344, ~455-462: the drive opens as the pushed screen; `closeActionSheet()` pops it)

**Interfaces:** profiles `parent` (d1, drives soccer at 15:40 with Maya, prep items soccer bag + water unconfirmed), `helper` (d3, own drive), `keeping` (no drives), `navigator` (kid with a ride). Mocks: `**/api/schedule?*` with the drive's edges/legs and `prep_by_event`; `**/api/drive_sheet/*` → the payload shape of `services/drive_sheet.py` `sheet()` (destination, eta_label, eta_ts, arrive_by, car, passengers, prep, messages, audience, next_drive, leg_id, event_id, status, toward_waiting); recorders for `api/drive_status` (start/complete), `api/drive_status/roll_call`, `api/prep_status`, `api/drive_status/message`, `api/drive_status/send_eta`, `api/drive_status/arrival` (resolved / unresolved), `api/drive_status/ping`, `api/events/*/attendance`; navigation URLs captured by intercepting the synthetic anchor click.

- [ ] **Step 1: Write the test** with scenarios: `before_moment` (parent: hero Start drive → depth 1, back "‹ My Day", the screen holds `#drive-leave-card` with `.pwa-drive-time` '3:40' (56px/700) and the sub line, `.pwa-drive-stops` two stops with the words from Task 1, `#drive-roll-chips` "Everybody in?" chips cycling three states (POST recorded), `#drive-prep-items` "Packed?" chips (last tick POSTs `confirmed: true`), `#btn-start-drive` primary full-width, an "Ask someone to cover" button that opens `#event-modal`, `#btn-mark-completed` and the retro-split buttons below; no bottom-sheet overlay visible; screenshot `drive-before.png`); `on_the_road` (Start → POST in_progress with or without a fix, the on-road moment: `#drive-arrival-card` with the ETA big and "Maya aboard", three nav buttons in one row, "Tell Lorena" with the catalog's lines (POST message), Send my ETA (POST send_eta), `#btn-arrived` green (the only green), the live banner; screenshot `drive-road.png`); `arrived_resolved` (arrival → arrived true → the screen pops, schedule refetched); `arrived_unresolved` (arrival → arrived false with eta_mins → the `promptChoice` above the screen; "Still driving" keeps it; again → "I've arrived — check it off" → POST completed → pops); `resume_after_reload` (start, reload → the drive screen reopens on-road, `PwaNav.depth() === 1`, the live banner; `page.go_back()` → closed, `localStorage.chauffeur_drive_resume` cleared); `opens_from_every_door` (My Day row, the hero, Plan's timeline block → "‹ Plan" and Back to Plan, the event dialog's map button → map-only on-road screen without Start/Arrived leg operations); `helper_drive` (helper: own drive opens; no retro-split buttons); `packing_on_my_day` (parent: the pile shows "Pack for Soccer practice" with "soccer bag, water · leave 3:40"; tapping opens the drive screen; after both items ticked and Back, the card is gone); `ride_hero_buttons` (navigator kid unchanged; an adult passenger profile if the fixture has one, else the parent's ride next: the hero shows Where? / Message / Add a moment from the ride row); `header_shrinks` (adult: `body > header` shows the date line, `#btn-notif`, the avatar `#pwa-identity`; no visible search button, `#btn-sync`, `#btn-theme`, `#btn-switch-driver`; Profile lists Refresh, Appearance, Switch person / Sign out, Notifications, Critter (when on); the bell opens `#notif-modal`; the kid header unchanged); `kid_unchanged` (navigator: the drive opens the bottom sheet `#action-sheet` with 'Your drive', no `PwaNav` entry); `widths_and_dark` (360/390 no overflow, `drive-before-dark.png`, `drive-road-dark.png`); `served.errors()` empty per profile.
- [ ] **Step 2: Run** `python tests/test_pwa_drive_live.py` → FAIL at the pushed screen missing.
- [ ] **Step 3: After Task 4, run** it and the adjusted tests → green.

---

### Task 3: The drive as a pushed screen, in two moments

**Files:**
- Modify: `chauffeur/static/pwa_drive.js` (add `pwaDriveOpen(...)`, `pwaDriveRestore()`, `pwaRenderDriveCards()`, `pwaDriveCover()`), `chauffeur/templates/app.html` (`openActionSheet`: for an adult (`pwaIsAdult()`), after `routeContext` is set, push `PwaNav.push({id: 'drive', title: <legTitle or 'Your drive'>, render(body) { body.append(#action-sheet-content) }, onPop() { pwaDriveRestore() }})` unless a drive screen is already up (then re-title); skip the overlay's show/translate animation for adults; `closeActionSheet()`: adult with the drive screen on top → `PwaNav.pop()` and let `onPop` run today's close body (moved into `pwaDriveRestore()`: stop the live lane, forget the resume, reset the buttons, `routeContext = null`, `driveSheetData = null`, the node back into `#action-sheet` hidden); kids → today's body; `renderDriveSheet` ends with `pwaRenderDriveCards()`; new hosts `<div id="drive-leave-card">` first in `#sheet-state-1` and `<div id="drive-arrival-card">` first in `#sheet-state-2`; an `#btn-drive-cover` "Ask someone to cover" button in `#sheet-state-1` after Start (adult-only; `pwaDriveCover()` runs the drive row's `data-secondary` — the event dialog's assign/claim — found by `[data-leg-id="<legId>"]`); `.pwa-drive-stops` host in `#sheet-state-1` after the leave card), `chauffeur/static/pwa_shell.css` (the drive skin under `[data-audience="adult"] #pwa-stack`)
- Test: Task 2's live test and adjustments; `tests/test_drive_sheet.py`, `tests/test_pwa_drive.py`, `tests/test_pwa_nav.py`, `tests/test_template_js.py`, `tests/pwa_child_checks.py` via `test_pwa_adult_shell_live.py` kid profiles.

**Interfaces:**
- The screen: the PwaNav back reads "‹ <tab label>" (My Day, Plan); the h1 is the leg title; the sheet's own head (`.pwa-sheet-head`, `#sheet-title`, `#sheet-subtitle`, the grab handle, both Cancel buttons) is hidden inside the stack (the back button and the h1 replace them); `#drive-brief`'s address / ETA / car lines are hidden for adults where the leave card and the arrival card carry them (the nodes stay for kids and for `renderDriveSheet`).
- Order, before: leave card → stops → "Everybody in?" chips → "Packed?" chips → Start drive (primary, full width 56px) → Ask someone to cover (secondary) → the retro-split options → Mark as completed; `#drive-next` and the live banner at the bottom.
- Order, on the road: arrival card → nav three across (Google / Apple / Waze, 64px tiles) → "Tell <audience>" lines in a 2-column grid + Send my ETA → Arrived (green `#1f7a5c`, 56px, the only green) → the retro-split options; `#drive-next` and the live banner at the bottom.
- CSS from the mockup: `.pwa-drive-leave` white card 22px radius, 0 10px 30px accent shadow; `.k` 12px/700 uppercase accent "Leave at" / "On the way · <place>"; `.pwa-drive-time` 56px/700 −.03em; sub 14px muted; stops: 12px dots (filled once done) on a 2px line, place 16px/600, sub 13px muted; chips `.ch` white 999px with a 26px face, aboard = ink fill white text, not-here = muted with ✕; packing chips green `#dcf3e8` when ticked; the big buttons 18px radius 18px/700. Dark through the tokens.

- [ ] **Step 1: Read Task 2's test and the mockup**; list every selector and text.
- [ ] **Step 2: Implement** push/adopt/restore → hosts → cards → order → CSS; `python tools/build_tailwind.py`.
- [ ] **Step 3: Run** `python tests/test_drive_sheet.py && python tests/test_pwa_drive.py && python tests/test_pwa_nav.py && python tests/test_template_js.py && python tests/test_pwa_drive_live.py && python tests/test_pwa_adult_shell_live.py && python tests/test_pwa_myday_live.py` → the drive scenarios green (packing / hero / header still red).

---

### Task 4: Packing on My Day, the ride hero's buttons, the header

**Files:**
- Modify: `chauffeur/static/pwa_myday.js` (`pwaNeedsYouInputs` builds `packing` from `scheduleData.prep_by_event` / `prep_confirmed` for today's events whose drive row is in the brief (the viewer drives) or whose ride row is (the viewer rides), with the row's `data-start` as `leaveAt` and its `data-primary` as `primary`; `pwaOpenNeed` runs `open.run`), `chauffeur/templates/app.html` (the passenger ride row `renderMyDayCard` stamps `data-actions` = JSON `[{label:'Where?', run}, {label:'Message', run}, {label:'Add a moment', run}]` from the buttons it already draws, in their order, only those it draws; the adult header: the date line `#pwa-header-date` (the selected day's long date) on the left, `#btn-notif` and `#pwa-identity` (avatar only) on the right; the search, sync, theme, switch, push and pet buttons hidden for adults by CSS (`html[data-audience="adult"] body > header …`), the name in Profile's head), `chauffeur/static/pwa_shell.js` (`pwaOpenProfile` lists Refresh (`fetchSchedule(true)`), Appearance (`cycleTheme`), Enable notifications (when `#btn-push` would show), the critter (when on), Switch person / Sign out (`clearDriver`) — add whichever is missing; `pwaSyncShell` writes `#pwa-header-date` from the selected day), `chauffeur/static/pwa_shell.css`
- Test: Task 2's `packing_on_my_day`, `ride_hero_buttons`, `header_shrinks`, `kid_unchanged`; `tests/test_pwa_needs_you.py`, `tests/test_pwa_next_thing.py`, `tests/test_pwa_myday_live.py`, `tests/test_pwa_adult_shell_live.py`

- [ ] **Step 1: Implement.** **Step 2:** `python tools/build_tailwind.py`. **Step 3: Run** the listed tests and Task 2's live test → green.

---

### Task 5: Record it, gate it, ship it

**Files:**
- Modify: `chauffeur/docs/ui_design_guide.md` (a "The drive, one screen two moments" section + the header change), `chauffeur/system_capabilities.md` (new top entry `v2.499.757`), `chauffeur/config.yaml` (→ `2.499.757`)

- [ ] **Step 1: Docs and version.**
- [ ] **Step 2: Gate** (from `chauffeur/`, `HA_BASE_URL` unset):

```bash
python tests/test_pwa_drive.py && python tests/test_drive_sheet.py && python tests/test_pwa_needs_you.py && python tests/test_pwa_next_thing.py && python tests/test_pwa_nav.py && python tests/test_pwa_argyle.py && python tests/test_template_js.py && python tests/test_tailwind_build.py && python tests/test_auth.py && python tests/test_drive_arrival.py && python tests/test_attendance_override.py && python tests/test_pwa_drive_live.py && python tests/test_pwa_adult_shell_live.py && python tests/test_pwa_myday_live.py && python tests/test_pwa_plan_live.py && python tests/test_pwa_household_live.py && python tests/test_pwa_messages_live.py && python tests/test_pwa_argyle_live.py
```

- [ ] **Step 3: Commit** as one commit `feat(pwa): slice 6 of the reimagined PWA, the drive and the header (v2.499.757)` and push.

---

## Sequencing calls (check these while reading)

1. **The drive screen adopts `#action-sheet-content`** (the Household / Messages pattern): every id, handler, the live lane and the resume keep working; hardware Back closes the drive the way the × did. Kids keep the bottom sheet.
2. **Before and on-road stay the two existing blocks** (`#sheet-state-1` / `#sheet-state-2`, switched by `enterEnRouteState`); the new leave-at and arrival cards are painted into hosts at the top of each block from the payload and the drive row; nothing is timed on the phone.
3. **"Ask someone to cover" is the event dialog's assign/claim** (the hero's secondary today); no new cover flow.
4. **The retro-split options and Mark as completed keep today's order and rules** (spec: "same order as today"), below the primary button.
5. **Packing joins My Day's pile** (the slice-1 carry-forward) as a card per event with unconfirmed prep, opening the drive screen; the drive screen's "Packed?" chips stay the place to tick.
6. **The passenger's ride hero carries the ride row's own buttons** (Where? / Message / Add a moment), closing the slice-1 'Discuss' carry-forward; the dataset contract gains `data-actions` on ride rows only.
7. **The header shrinks for adults** to the date line with the bell and the avatar (Profile); search, refresh, theme, switch person, notifications and the critter are reached through Profile and More (search leaving the header is an approved disposition). Kids' header unchanged.
8. **Not this slice:** a full-screen map on the drive, a new cover/request flow, kid drive screens, device-only gesture checks.

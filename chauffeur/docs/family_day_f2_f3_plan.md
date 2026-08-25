# Family Day F2 + F3 — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (this plan is being executed inline). Steps use checkbox (`- [ ]`) syntax.

**Goal:** F2 makes the Family Day card speak the household's own language — passenger colour on events, driver colour on outings, passengers visible without a tap, every trip drawn as an outing, and more than one day. F3 moves packing out of the moment it is too late: prep blocks land where a household can act on them, with items as tappable chips.

**Architecture:** `services/family_day.py` grows two derivations — per-event passenger resolution (colour + names from the schedule cache's own `calendar_metadata`, which already carries identity colours) and prep blocks (pure placement over existing outings, no new state). The endpoint serves N days. The card renders day separators, always-container outings, passenger dots, and chip-form items; claims are unchanged.

**Tech Stack:** Python 3 + FastAPI, Jinja + vanilla Alpine, precompiled Tailwind, python scenario tests + jsdom + playwright/chromium.

**Spec:** `docs/family_day_design.md` (sections *What F1 shipped and what it did not*, *Prep is work*, *Items are chips*, *Every trip is an outing*, *More than one day*). Design wins on disagreement. UI work obeys `docs/ui_design_guide.md`.

## Global Constraints

- Tests: `python tools/test.py` (parallel, never piped) before each commit. Known unrelated flake: `test_coverage_ladder.py::scenario_nudges_come_when_a_reply_would_exist`.
- Bump `config.yaml` `version:` per commit; subject ends `(vX.Y.Z)`; no double quotes in messages (`git commit -F`).
- `python tools/build_tailwind.py` after any template change.
- Never `alert()`/`confirm()`/`prompt()`.
- **Sibling precedent or nothing:** item chips copy the drive sheet's (`app.html:6601-6607`) amber→green-✓ vocabulary; passenger dots copy the grid's (`family_calendar.html:730-742`); rows keep using the shared `agendaEventRow`. No third pattern.
- **The pill lives on outings; chips live on prep blocks.** A prep block never draws the pill and never expands.
- **Colour law:** event bar = the event's calendar colour (person). Outing bar = driver colour. Nothing else recolours an event.
- Claims storage is untouched. Prep blocks are derived on read — no new table.
- Locked test hooks: `data-fd-key`, `.fd-inner-line`, `.pk-pill-amber`, `.pk-pill-done`, quiet sentence text. Caret-tap expands, body-tap opens details, no caret without items.

---

## F2 — the family's own language

### Task 1: The blocks payload learns who and whose

**Files:** `services/family_day.py`, `tests/test_family_day.py`

**Produces:** every event-bearing block gains `passengers: [{'id','name','color'}]` and `color` = the event's own calendar colour; outing blocks keep `color` = driver colour but gain `passengers` unioned across their events, and each inner event line gains `passengers` + `color` of its own.

- [ ] **Step 1: failing test** — scenarios: an event on a person's calendar carries that person's colour and name; an event with two people carries both; an outing's colour stays the driver's while its inner lines carry passenger colours; a member with no calendar match yields no passengers (no invention).
- [ ] **Step 2: run, watch fail.**
- [ ] **Step 3: implement** `_passengers_for(ev, members, cal_meta)` — members whose `id` or `calendar_ids` intersect `ev['calendar_ids']` (same rule as `outings._people_on`); colour from `cal_meta[cal_id]['backgroundColor']` falling back to the member's `color_code`; event colour from `cal_meta[ev.calendar_ids[0]]`. Read `sched['calendar_metadata']` (identity colours already applied at cache build, `main.py:16097`).
- [ ] **Step 4: run, watch pass.**
- [ ] **Step 5: sweep, bump, commit** — `The day says whose event it is (vX.Y.Z)`.

### Task 2: N days from the endpoint

**Files:** `main.py`, `tests/test_packing_api.py`

**Produces:** `GET /api/packing/day?days=N` → `{'days': [{'date','is_today','is_tomorrow','label','blocks':[...]}, ...], 'date', 'is_tomorrow'}`. Day one is `day_in_focus`; subsequent days follow it. Legacy top-level `blocks` stays as day one's blocks so nothing breaks mid-plan.

- [ ] **Step 1: failing test** — `days=3` returns three days in order, each with its own blocks; claims resolve per day; default (no param) returns one day and still carries `blocks`.
- [ ] **Step 2–4:** implement by looping the existing per-day assembly; extract the per-day body into `_packing_day_payload(target, sched, now, claims_by_day)`.
- [ ] **Step 5: sweep, bump, commit** — `The card can see past today (vX.Y.Z)`.

### Task 3: Every trip is an outing, and the card draws days

**Files:** `templates/components/packing_card.html`, `services/home_board.py` (a `days` option), `tests/test_packing_card_render.py`, `tests/test_packing_card.py`

- [ ] **Step 1: failing render tests** — a single-event outing draws as a container (not a flat row); an event row's left bar is the passenger colour while its outing's is the driver colour; passenger dots render on rows with passengers; a multi-day payload draws day separators.
- [ ] **Step 2: run, watch fail.**
- [ ] **Step 3: implement** — drop `pkIsContainer`'s ≥2 rule (all outings are containers); pass event `color` and `passengers` into `agendaEventRow` (dots via a new `passengerDots` opt on the shared builder, markup copied from the grid precedent, so the calendar can adopt it later); day separator rows between days (`text-sm font-bold text-gray-300`, label + date, no panel); add the `days` card option (default 1, max 7).
- [ ] **Step 4: build_tailwind, run all card suites, chromium.**
- [ ] **Step 5: screenshot, sweep, bump, commit** — `Every trip is an outing, and the card sees the week (vX.Y.Z)`.

---

## F3 — prep lands where you can act on it

### Task 4: Prep blocks

**Files:** `services/family_day.py`, `tests/test_family_day.py`

**Produces:** `blocks_for` also emits `{'kind':'prep','key': f"prep:{outing_key}", 'for_key','for_title','for_start','passengers','start'(sort anchor),'window'}` for every outing/event block that has items. Placement per the design:

| Outing departs | Prep sorts to the start of |
|---|---|
| before 12:00 | the **previous day's evening** (17:00 anchor) |
| 12:00–17:00 | that day's **morning** (00:00 anchor) |
| after 17:00 | that day's **afternoon** (12:00 anchor) |

Catch-up: if the anchor is already past and the block is unpacked, the anchor becomes `now` so it sorts to the front of what remains.

- [ ] **Step 1: failing tests** — morning outing puts prep on the previous evening; afternoon outing puts it at that morning; evening outing puts it at that afternoon; a passed anchor moves to now; an outing with no items yields no prep block; the prep block names its outing and carries its passengers.
- [ ] **Step 2: run, watch fail.**
- [ ] **Step 3: implement** `_prep_blocks(blocks, now)` — pure, derived, keyed off the source block. Cross-day placement means `blocks_for` for day D must be able to emit a prep block belonging to day D−1; the endpoint (Task 5) places each prep block on the day its anchor falls in.
- [ ] **Step 4: run, watch pass.**
- [ ] **Step 5: sweep, bump, commit** — `Packing is work, and work has a place in the day (vX.Y.Z)`.

### Task 5: Prep blocks reach the endpoint

**Files:** `main.py`, `tests/test_packing_api.py`

- [ ] **Step 1: failing test** — a multi-day request shows tomorrow-morning's prep on today; the prep block carries the same `groups` as its outing; claiming against the prep block's `for_key` moves the outing's count (one truth, two views); a prep key is not itself claimable.
- [ ] **Step 2–4:** implement — prep blocks carry `groups` copied from the source block's computed groups; claims stay keyed to the source block, so `POST /api/packing/claim` needs no change and prep keys are rejected exactly as before.
- [ ] **Step 5: sweep, bump, commit** — `Tomorrow morning is packed tonight (vX.Y.Z)`.

### Task 6: The chip

**Files:** `templates/components/packing_card.html`, `tests/test_packing_card_render.py`, `tests/test_packing_card.py`

- [ ] **Step 1: failing tests** — a prep block draws its items as chips with no caret and no pill; tapping a chip claims (count moves on the block AND on its outing); a `needed>1` chip carries a `− n +` stepper as one non-breaking unit; a packed chip shows green with `✓`; the outing's expanded list uses the same chips.
- [ ] **Step 2: run, watch fail.**
- [ ] **Step 3: implement** — chip markup copied from `app.html:6601-6607` (amber `bg-amber-500/10 border-amber-500/40 text-amber-200` → green `bg-green-600/20 border-green-500/60 text-green-200` with `✓`), kit name as the leading label in `🎒 Bring`'s position; chip+stepper wrapped `inline-flex whitespace-nowrap`; prep block renders no pill, no caret, never expands; replace the outing's vertical item list with the same chips.
- [ ] **Step 4: build_tailwind, all card suites, chromium.**
- [ ] **Step 5: screenshot, sweep, bump, commit** — `Prep items are chips you tap (vX.Y.Z)`.

### Task 7: Say what changed

**Files:** `system_capabilities.md`, `docs/family_day_design.md`

- [ ] Capabilities section rewritten for F2+F3 (colour law, passengers, multi-day, prep placement + catch-up, chips, pill-vs-chips split). Design doc: stamp F2 and F3 shipped with versions. Sweep, bump, commit, push.

## Self-review

**Spec coverage:** colour law + passengers → Tasks 1, 3. Every-trip-an-outing → Task 3. Multi-day → Tasks 2, 3. Prep placement + catch-up → Task 4. Prep reaching the card with shared claims → Task 5. Chips, no pill, no expand on prep → Task 6. Docs → Task 7. F4 (meals) deliberately absent.

**Names:** `_passengers_for`, `_prep_blocks`, `_packing_day_payload`, block kind `prep`, key `prep:<outing_key>`, opts `passengerDots`, card option `days`.

**Known risk:** Task 3 changes every outing into a container, which lengthens the day; Task 6 shortens it again by turning item rows into chips. The two land in the same plan on purpose.

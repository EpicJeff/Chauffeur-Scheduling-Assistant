# Family Day F4 — packing is a decided act

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (executed inline). Steps use checkbox (`- [ ]`) syntax.

**Goal:** One prep block per part of the day instead of one per outing, holding per-event tiles ordered by departure; each tile opens a shared `Pack Items` dialog carrying that event's list; the outing's heading collapses to one line.

**Architecture:** `services/family_day.py` stops emitting a prep block per source block and emits at most one per bucket (`morning|afternoon|evening`), each carrying `tiles` that name their event. The endpoint resolves each tile's groups and counts. A new `templates/components/pack_dialog.html` owns the dialog so P3's kid view and the driver list can consume it. Claims, keys and counts are unchanged.

**Spec:** `docs/family_day_design.md` § *Packing is a decided act (F4)*. UI obeys `docs/ui_design_guide.md`.

## Global Constraints

- `python tools/test.py` before every commit (never piped). Known flake: `test_coverage_ladder.py::scenario_nudges_come_when_a_reply_would_exist`.
- Bump `config.yaml`; subject ends `(vX.Y.Z)`; no double quotes (`git commit -F`).
- `python tools/build_tailwind.py` after template changes.
- Never `alert()`/`confirm()`/`prompt()`.
- **Claims are untouched**: a claim is still `(source block key, item key)`; a tile is a view, and a prep/tile key is never claimable.
- **The outing keeps its own chips** as the door-check fast path.
- Locked hooks: `data-fd-key`, `.fd-inner-line`, `.pk-pill-amber`, `.pk-pill-done`, `.fd-prep`, `.fd-item-chip`, caret-tap-expands / body-tap-details / no-caret-without-items.

---

### Task 1: One prep block per part of the day

**Files:** `services/family_day.py`, `tests/test_family_day.py`

**Produces:** at most three prep blocks per day, keyed `prep:<date>:<bucket>` where bucket is `morning|afternoon|evening`. Each carries:
`{'kind':'prep','key','bucket','start','end','tiles':[{'key','for_key','event_id','title','start','passengers'}]}` — tiles sorted by the departure of the event they serve, then title.

Placement rule is unchanged (`_prep_window`); what changes is that blocks sharing a bucket MERGE rather than stack. Catch-up is now per tile: a tile whose window has passed and is still unpacked moves into the current bucket's block; a bucket whose tiles are all packed keeps them and is rendered collapsed by the card.

- [ ] **Step 1: failing tests** — two morning outings on the same day produce ONE evening block the night before with two tiles; tiles are ordered by departure, not by key (the incident: four Saturday trips sorted alphabetically); a tile names its event and its people; an outing with several events yields one tile per event; buckets do not merge across days.
- [ ] **Step 2: run, watch fail.**
- [ ] **Step 3: implement** — `_prep_blocks` groups by `(target, bucket)`; a source block contributes one tile per event it covers (outing → its `events`; event block → itself).
- [ ] **Step 4: run, watch pass.**
- [ ] **Step 5: sweep, bump, commit** — `A day has three places to pack, not six (vX.Y.Z)`.

### Task 2: Tiles carry their own list

**Files:** `main.py`, `tests/test_packing_api.py`

**Produces:** each tile gains `groups`, `packed`, `needed`, and `done` (packed >= needed and needed > 0); the block gains its own `packed`/`needed` totals summed across tiles. Tile groups resolve against the tile's own event only (`packing_for({'event_ids': [event_id]})`), so a dialog shows one event's list; claims still key on `for_key` (the source block), which is what keeps the outing and the tile in agreement.

- [ ] **Step 1: failing tests** — a tile carries its event's items and a count; ticking against the tile's `for_key` moves both the tile and its outing; a block with every tile packed reports `packed == needed`; a prep or tile key is still refused by `POST /api/packing/claim`.
- [ ] **Step 2–4:** implement and verify.
- [ ] **Step 5: sweep, bump, commit** — `A tile knows its own list (vX.Y.Z)`.

### Task 3: The Pack Items dialog

**Files:** create `templates/components/pack_dialog.html`; `templates/home.html` (+ any page including the card) gains the include; `tests/test_pack_dialog_render.py` (create)

**Produces:** `window.packDialog(opts)` — a shared, self-contained dialog: title (the event), passengers, the chip list (the F3 vocabulary, moved here), and a close control. It takes `{ title, passengers, groups, interactive, onClaim(itemKey, delta) }` and renders; the host owns the claim call so the dialog never fetches. Sibling precedents: the event-details dialog's shell (`family_calendar.html`'s modal) for chrome, `app.html:6601-6607` for the chips.

- [ ] **Step 1: failing render test** — the dialog draws the event title, a dot per passenger, one chip per item, a `−  n  +` stepper for `needed > 1`; `interactive: false` draws no buttons at all; opening it posts nothing.
- [ ] **Step 2–4:** implement and verify.
- [ ] **Step 5: tailwind, sweep, bump, commit** — `A dialog for packing one event (vX.Y.Z)`.

### Task 4: The card draws tiles, and the heading collapses

**Files:** `templates/components/packing_card.html`, `tests/test_packing_card_render.py`, `tests/test_packing_card.py`

- [ ] **Step 1: failing tests** — a prep block draws one tile per event with a title, dots, an `N items` count and a `Pack Items` button, and NO chips inline; a fully-packed tile reads `Packed ✓`; a block whose tiles are all packed collapses to one `Packed ✓` line; the outing heading puts `Outing`, driver-as-text, car-as-chip and the pill on one line with the time beneath; tapping `Pack Items` opens the dialog; a poll while the dialog is open neither closes it nor resets a tick made in it.
- [ ] **Step 2: run, watch fail.**
- [ ] **Step 3: implement** — tiles replace the inline chip sections on prep blocks (the outing's expansion keeps them); `pkOpenPack(b, tile)` mounts the shared dialog and routes its `onClaim` through the existing `pkClaim` so pending/mirror/poll-survival all still apply; heading rebuilt per the design.
- [ ] **Step 4: build_tailwind, run render + chromium suites.**
- [ ] **Step 5: screenshot, sweep, bump, commit** — `Packing is a decided act (vX.Y.Z)`.

### Task 5: Say what changed

**Files:** `system_capabilities.md`, `docs/family_day_design.md`

- [ ] Capabilities gains the F4 entry (bucket blocks, tiles, the dialog and why it is shared, the per-tile catch-up rule, the recorded trade: item names are no longer readable from three metres). Design doc stamps F4 shipped. Sweep, bump, commit, push.

## Self-review

**Spec coverage:** one block per bucket → Task 1. Tiles with counts and ordering → Tasks 1–2. Dialog, shared → Task 3. Card rendering, heading, poll-survival → Task 4. Docs → Task 5. F5 (meals) absent by design.

**Names:** `_prep_blocks` (rewritten), bucket keys `prep:<date>:<bucket>`, `tiles`, `packDialog`, `pkOpenPack`.

**Known risk:** Task 1 changes the prep block's shape, so F3's prep render assertions in `tests/test_packing_card_render.py` must move to tiles in Task 4 — disclosed in that commit rather than silently rewritten.

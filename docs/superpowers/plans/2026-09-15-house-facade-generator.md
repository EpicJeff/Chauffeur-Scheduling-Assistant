# House Facade Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The dollhouse's street elevation is built from a validated facade spec (slots × ground/roof features × style enums) instead of hand-authored blocks; a parent can produce that spec from one photo or by hand, save several, and switch between them.

**Architecture:** `services/house_facade.py` owns the slot table, the canonical spec, normalize/snap laws, storage and the one vision call — pure functions with a thin storage layer. `main.py` exposes CRUD + photo routes and injects the active spec into `house.html` (the scene builds before its first state fetch, so the spec must arrive with the page). `static/house.js` gains `PALETTE`, a JS slot table, one builder per feature kind and `buildElevation()`, all registering through the existing `shellGroup`/`shellRegister` idiom so occlusion, navigation and merge fencing hold with no solver change; AO occluders are derived from the `FABRIC` registry. `config.html` gets a Home section beside Cars.

**Tech Stack:** Python 3 / FastAPI / pydantic `Settings` model, vendored three.js in `static/house.js`, Alpine.js + precompiled Tailwind in `templates/config.html`, Playwright live tests via `tests/live_app.py`, `tools/house_probe.py` for draw budgets, Gemini via `services/model_pools.call_pool_json`.

**Spec:** `docs/superpowers/specs/2026-09-15-house-facade-generator-design.md` (read it first; every law below cites a section).

## Global Constraints

- Every task ends with: bump the patch version in `chauffeur/config.yaml` (read it first, `grep ^version` after), full sweep `env -u HA_BASE_URL python chauffeur/tools/test.py` from the repo root (never piped), commit with the version in the subject `(vX.Y.Z)`, push. Docs-only commits skip the sweep.
- Known-failing baseline to compare against, not to fix: `test_messaging` (15/16), `test_status_protocols` (`scenario_beat_need_overrides_drive_solver`). `HA_BASE_URL` must be unset for the sweep (it fakes a configured HA).
- house.js laws: every geometry through `cgeo`, every material through `mat()`/`box()` opts, `mkTex` owns textures, no per-frame work, render-on-demand. Every new shell piece registers through `shellRegister`/`regFabric`. Ghost edges stay OFF (user ruling); cutaways are the occlusion mode.
- Draw ceilings (quality=high, `--day`): exterior in-frustum ≤ 1400, kitchen ≤ 418, living ≤ 730, mudroom ≤ 382, garage ≤ 539; `buildMs` ≤ 1500.
- No browser dialogs (`alert/confirm/prompt`): use `showGlobalAlert`, `promptConfirm`, `promptInput` from `control_center.html`. After any template class change run `cd chauffeur && python tools/build_tailwind.py`.
- The photo is never written to disk, never logged, never stored. Palette hex never leaves `house.js`.
- Commit messages: normal prose, end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. PowerShell: no double quotes inside `-m` strings; prefer the Bash tool with a heredoc.
- Tests are standalone scripts: `from harness import check`, `scenario_*` functions, a `for fn in (...)` runner at the bottom. Run one file as `cd chauffeur && python tests/test_x.py`; the sweep via `tools/test.py`. Live tests skip cleanly when Playwright is absent (`served is None`).

---

## File map

| file | responsibility |
|---|---|
| `chauffeur/services/house_facade.py` (new) | `SLOT_W`, `FACES`, `slot_table()`, `CANONICAL`, enums, `normalize()`, `worst_case()`, facade storage (`list_facades`, `save_facade`, `update_facade`, `delete_facade`, `set_active`, `active_bundle`), `from_photo()` |
| `chauffeur/tests/test_house_facade.py` (new) | every law in spec §4, storage laws, mocked photo path |
| `chauffeur/models/schemas.py` | `Settings.house_facades`, `Settings.house_facade_active` |
| `chauffeur/services/settings_registry.py` | two entries, page `config`, anchor `home` |
| `chauffeur/services/auth.py` | RULES rows for `/api/house/facades*` |
| `chauffeur/main.py` | facade routes; `house_page` injects `facade_json`; `house_room.state` unchanged except `facade` |
| `chauffeur/services/house_room.py` | `state()['facade']` |
| `chauffeur/templates/house.html` | `window.HOUSE_FACADE` script line before `house.js` |
| `chauffeur/static/house.js` | `PALETTE`, `facadeSlots()`, builders, `buildElevation()`, derived AO occluders, `chfNavProbe {exit}`, `chfFacade()`, `chfFacadeSlots()`, `chfAoOccluders()`, marker table by face |
| `chauffeur/tests/test_house_live.py` | step-0 fix, canonical pin, worst-case scenario, slot-table parity |
| `chauffeur/tests/test_house_state.py` | `facade` present, canonical by default |
| `chauffeur/tools/house_probe.py` | `--facade canonical|worst|<id>` |
| `chauffeur/templates/config.html` | Home section (`id="home"`), Alpine `facade*` state and methods |
| `chauffeur/tests/test_settings_registry.py` | passes unchanged (audit) |
| `chauffeur/system_capabilities.md`, `docs/house_style_bible.md`, spec §10 | wrap docs |

---

### Task 1: AO occluders from the registry + step 0 (the red garage sky-tap)

**Files:**
- Modify: `chauffeur/static/house.js` — `chfNavProbe` (~9656–9745), `AO_OCCLUDERS` literal (~7764–7800), exposure block near `window.chfShellFabric` (~9638)
- Modify: `chauffeur/tests/test_house_live.py:1385-1392` (the garage exit probe), `scenario_shell_fabric_registry` (add the AO check)

**Interfaces:**
- Produces: `window.chfNavProbe({exit:true})` → a canvas point whose ray hits nothing, the sky dome, or the yard group; `window.chfAoOccluders()` → `[[x0,x1,y0,y1,z0,z1], ...]`.

Why it is red today (diagnosed 2026-09-15 with `tools/house_probe.py --views garage --quality low --day`): the garage view's frame is entirely garage interior, the neighbouring roofs and LAWN — no sky pixel exists from `GARAGE_POS`. The navigation law (spec 2026-09-11 §5 rule 5) says sky **or yard** exits, and `onTap` already implements both (`if (!ihit || ihit === webgl.skyDome || inYard(ihit)) goExterior()`, house.js ~9957). The test probes `{sky:true}` only. The probe grows an `{exit:true}` spec that mirrors `onTap`'s own exit test; the scene is not changed.

- [ ] **Step 1: Make the live scenario ask for an exit pixel**

In `chauffeur/tests/test_house_live.py` replace the block at ~1383–1392:

```python
        # spec section 5, rule 5: sky OR yard exits. The garage camera sees
        # no sky since the envelope arc (its frame is interior, roofs and
        # lawn), so probe for any exit pixel — the same test onTap runs.
        enter('garage')
        p = probe("{exit:true}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_timeout(1200)
        check(page.evaluate("window.chfHouseMode()") == 'exterior',
              'a sky or yard tap must still exit to the exterior: %r' % p)
```

- [ ] **Step 2: Run it, expect the new failure**

Run: `cd chauffeur && env -u HA_BASE_URL python tests/test_house_live.py`
Expected: FAIL `no reachable canvas pixel for {exit:true}` (the spec key is unknown, `matches` returns false everywhere).

- [ ] **Step 3: Teach chfNavProbe the exit spec**

In `house.js` `chfNavProbe`, change the guard line

```js
    } else if (!spec.sky && !spec.empty) return null;
```
to
```js
    } else if (!spec.sky && !spec.empty && !spec.exit) return null;
```
and in `matches` add, directly under the `spec.sky` line:
```js
      if (spec.exit) return !hit || hit === webgl.skyDome || inYard(hit);
```
and widen the grid density line to `var n = spec.sky || spec.empty || spec.exit ? 24 : 8;`. `inYard` (~9401) is module scope, same as `chfNavProbe`.

- [ ] **Step 4: Run it, expect green**

Run: `cd chauffeur && env -u HA_BASE_URL python tests/test_house_live.py`
Expected: every scenario `ok`, including `scenario_navigation_real_mouse`.

- [ ] **Step 5: Write the failing AO-derivation check**

In `scenario_shell_fabric_registry`, after the `names` assertions, add:

```python
        # arc 4 prerequisite (spec §6): AO occluders come FROM the registry.
        occ = page.evaluate("window.chfAoOccluders()")
        def has_box(b, tol=0.05):
            return any(all(abs(o[i] - b[i]) <= tol for i in range(6)) for o in occ)
        check(has_box([-6.5, 6.5, 0.0, 5.6, 14.2, 14.55]),
              'south_wall must occlude via its registered box')
        check(has_box([6.5, 6.85, 0.0, 5.6, -5.725, 14.55]),
              'east_wall must occlude via its registered box')
        wallish = [f for f in fab if abs(f['n'][1]) < 0.5]
        check(len(occ) >= len(wallish),
              f'every wall-like piece contributes an occluder: {len(occ)} < {len(wallish)}')
```
`chfShellFabric()` must return `n` per piece: extend its mapper (house.js ~9638) with `n: [f.n.x, f.n.y, f.n.z], box: f.box.slice()` if not already present (read the current shape first: `{name, mode, visible, verdict, edgesVisible, interiorGlow}`).

- [ ] **Step 6: Run, expect FAIL** (`chfAoOccluders is not a function`).

- [ ] **Step 7: Derive the occluders**

In `house.js`, delete the two hand rows inside the `AO_OCCLUDERS` literal:
```js
      [-6.5, 6.5, 0.0, 5.6, 14.2, 14.55],           /* south_wall */
      [6.5, 6.85, 0.0, 5.6, -5.725, 14.55],         /* east_wall */
```
and their preceding SHELL comment paragraph. Directly after the closing `];` of the literal add:

```js
    /* SHELL/arc 4 (facade spec §6): wall-like fabric occludes by its own
       registered box, so a generated wall needs no hand row. Sloped
       pieces (roof decks, |n.y| >= 0.5) still skip: no honest AABB. */
    FABRIC.forEach(function (f) {
      if (Math.abs(f.n.y) >= 0.5 || !boxOk(f.box)) return;
      AO_OCCLUDERS.push(f.box.slice());
    });
```
This sits after the `FABRIC.forEach(... EXT_NO_MERGE ...)` line (~7626), so every `regFabric` call has already run. Expose beside `chfShellFabric`:
```js
  window.chfAoOccluders = function () {
    return webgl && webgl.AO_OCCLUDERS ? webgl.AO_OCCLUDERS.map(function (b) { return b.slice(); }) : [];
  };
```
and add `AO_OCCLUDERS: AO_OCCLUDERS` to the object `buildRoom()` returns (the block at ~8733 that already exports `GARAGE_POS`).

- [ ] **Step 8: Run the live file, then the budget probe**

Run: `cd chauffeur && env -u HA_BASE_URL python tests/test_house_live.py` → all `ok`.
Run: `cd chauffeur && env -u HA_BASE_URL python tools/house_probe.py --views all --budget --quality high --day --out ../scratch/probe-t1` → record every view's `inFrustum` and `buildMs`; all under ceiling (AO changes shading, not counts — `meshes` must equal the pre-task numbers exactly). Paste the table into the commit body.

- [ ] **Step 9: Sweep, bump, commit, push**

```bash
env -u HA_BASE_URL python chauffeur/tools/test.py
# bump chauffeur/config.yaml patch; verify with grep ^version
git add chauffeur/static/house.js chauffeur/tests/test_house_live.py chauffeur/config.yaml
git commit -F - <<'EOF'
fix: derive AO occluders from the fabric registry; exit probe for the garage (vX.Y.Z)

The garage view has had no sky pixel since the envelope arc; the
navigation law exits on sky OR yard, so chfNavProbe gains {exit:true}
mirroring onTap's own test and the real-mouse scenario uses it. AO
occluders for wall-like fabric now come from each piece's registered
box (spec 2026-09-15 §6), replacing the two hand rows, so generated
walls occlude without a hand call site.

Budget (quality=high --day): <table>

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
git push
```

---

### Task 2: `house_facade.py` — slots, canonical, normalize, worst case

**Files:**
- Create: `chauffeur/services/house_facade.py`
- Create: `chauffeur/tests/test_house_facade.py`

**Interfaces:**
- Produces (all pure):
  - `SLOT_W: float = 1.85`; `FACES: list[dict]`; `slot_table() -> list[dict]` each `{i, face, x0, x1, cx, z, eave, room, roof}`
  - `GROUND_KINDS = ('wall','window','door','garage_door','porch')`, `ROOF_KINDS = ('eave','gable','dormer','hip_end')`, `WINDOW_SIZES = ('tall','standard','small')`, `PORCH_TYPES = ('sitting','stoop','covered')`, `GARAGE_STYLES = ('carriage','panel','glass')`, `STYLE = {'cladding': ('batten','clapboard'), 'body': ('white','greige','sage','slate','navy'), 'roof': ('charcoal','weathered','brown'), 'frame': ('black','white'), 'door': ('wood','black','red','sage'), 'trim': ('white','black')}`
  - `PITCH_MIN, PITCH_MAX = 22.5, 35.0`; `MAX_WINDOWS = 10; MAX_DORMERS = 6; MAX_GABLES = 4; MAX_PORCH_SLOTS = 10`
  - `CANONICAL: dict`
  - `normalize(raw) -> tuple[dict, list[str]]`
  - `worst_case() -> dict`

- [ ] **Step 1: Write the failing tests (whole file)**

```python
"""The facade generator's laws (spec docs/superpowers/specs/
2026-09-15-house-facade-generator-design.md sections 2 and 4). Pure:
no storage, no browser."""
import copy
import json

from harness import check
from services import house_facade as hf


def _spec(**over):
    s = copy.deepcopy(hf.CANONICAL)
    s.update(over)
    return s


def scenario_slot_table_is_derived_from_the_faces():
    slots = hf.slot_table()
    check([s['face'] for s in slots].count('garage') == 3, 'garage face: 3 slots')
    check([s['face'] for s in slots].count('mudroom') == 3, 'mudroom face: 3 slots')
    check([s['face'] for s in slots].count('main') == 8, 'main face: 8 slots')
    check([s['face'] for s in slots].count('wing') == 4, 'wing face: 4 slots')
    check(len(slots) == 18 and [s['i'] for s in slots] == list(range(18)),
          'eighteen slots, indexed west to east')
    for a, b in zip(slots, slots[1:]):
        if a['face'] == b['face']:
            check(abs(a['x1'] - b['x0']) < 1e-9, 'slots tile their face')
    for f in hf.FACES:
        own = [s for s in slots if s['face'] == f['face']]
        check(abs(own[0]['x0'] - f['x0']) < 1e-9 and abs(own[-1]['x1'] - f['x1']) < 1e-9,
              f"{f['face']} slots span exactly the face")
        widths = {round(s['x1'] - s['x0'], 6) for s in own}
        check(len(widths) == 1, f"{f['face']} slots are uniform: {widths}")
    main = [s for s in slots if s['face'] == 'main']
    check(abs(main[0]['cx'] - (-6.275)) < 1e-6 and abs(main[4]['cx'] - 0.725) < 1e-6,
          f"main centres per spec 2.2: {[round(s['cx'], 3) for s in main]}")


def scenario_canonical_is_normal_and_idempotent():
    spec, notes = hf.normalize(hf.CANONICAL)
    check(spec == hf.CANONICAL, f'canonical survives normalize unchanged; notes {notes}')
    check(notes == [], 'canonical raises no notes')
    again, _ = hf.normalize(spec)
    check(again == spec, 'idempotent')
    json.dumps(spec)  # serialisable


def scenario_unknown_enums_fall_to_defaults():
    raw = _spec(style={'cladding': 'stucco', 'body': 'pink', 'roof': 'x',
                       'frame': 'y', 'door': 'z', 'trim': 'w'},
                ground=[{'slot': 9, 'span': 1, 'kind': 'window', 'size': 'huge'},
                        {'slot': 10, 'span': 1, 'kind': 'porch', 'type': 'wraparound'},
                        {'slot': 11, 'span': 1, 'kind': 'skylight'}])
    spec, notes = hf.normalize(raw)
    check(spec['style'] == hf.CANONICAL['style'], f"style defaults: {spec['style']}")
    kinds = {(g['slot'], g['kind']) for g in spec['ground']}
    check((9, 'window') in kinds and (11, 'skylight') not in kinds, 'unknown kind dropped')
    win = next(g for g in spec['ground'] if g['slot'] == 9)
    check(win['size'] == 'standard', 'unknown window size -> standard')
    porch = next(g for g in spec['ground'] if g['kind'] == 'porch')
    check(porch['type'] == 'covered', 'unknown porch type -> covered')
    check(any('skylight' in n for n in notes), 'the drop is noted')


def scenario_pitch_clamps():
    check(hf.normalize(_spec(pitch_deg=50))[0]['pitch_deg'] == 35.0, 'high clamps')
    check(hf.normalize(_spec(pitch_deg=5))[0]['pitch_deg'] == 22.5, 'low clamps')
    check(hf.normalize(_spec(pitch_deg='steep'))[0]['pitch_deg'] == hf.CANONICAL['pitch_deg'],
          'garbage -> canonical')


def scenario_spans_truncate_at_face_boundaries():
    # slot 12 is main's east-most (6..13 are main); a span of 4 would cross into the wing
    raw = _spec(ground=[{'slot': 10, 'span': 1, 'kind': 'door'},
                        {'slot': 12, 'span': 4, 'kind': 'porch', 'type': 'stoop'}])
    # NOTE: slots are global indices; main face = 6..13 in the 18-slot table
    spec, notes = hf.normalize(raw)
    porch = next(g for g in spec['ground'] if g['kind'] == 'porch')
    check(porch['slot'] == 12 and porch['span'] == 2,
          f'porch truncated at the wing boundary: {porch}')
    check(any('face' in n for n in notes), 'truncation noted')


def scenario_openings_pin_to_their_room_face():
    raw = _spec(ground=[{'slot': 15, 'span': 1, 'kind': 'door'},                       # on the wing
                        {'slot': 8, 'span': 2, 'kind': 'garage_door', 'style': 'glass', 'leaves': 2}])
    spec, notes = hf.normalize(raw)
    door = [g for g in spec['ground'] if g['kind'] == 'door']
    gd = [g for g in spec['ground'] if g['kind'] == 'garage_door']
    slots = hf.slot_table()
    check(len(door) == 1 and slots[door[0]['slot']]['face'] == 'main', f'door moved to main: {door}')
    check(len(gd) == 1 and gd[0]['slot'] == 0 and gd[0]['span'] == 3 and gd[0]['leaves'] == 2,
          f'garage door forced onto the garage face, whole face: {gd}')
    # no door at all -> the canonical door
    spec2, _ = hf.normalize(_spec(ground=[]))
    check(any(g['kind'] == 'door' for g in spec2['ground']), 'at least one door always')
    # any number of doors on the main face is fine
    spec3, _ = hf.normalize(_spec(ground=[{'slot': 7, 'span': 1, 'kind': 'door'},
                                          {'slot': 11, 'span': 1, 'kind': 'door'}]))
    check(sum(g['kind'] == 'door' for g in spec3['ground']) == 2, 'two doors survive')


def scenario_overlap_priority_trims_the_loser():
    raw = _spec(ground=[{'slot': 7, 'span': 5, 'kind': 'window', 'size': 'small'},
                        {'slot': 9, 'span': 1, 'kind': 'door'}])
    spec, notes = hf.normalize(raw)
    wins = sorted((g['slot'], g['span']) for g in spec['ground'] if g['kind'] == 'window')
    check(wins == [(7, 2), (10, 2)], f'window split around the door: {wins}')
    # porch is an overlay: shares with door and windows, never trims
    raw = _spec(ground=[{'slot': 7, 'span': 5, 'kind': 'porch', 'type': 'sitting'},
                        {'slot': 8, 'span': 1, 'kind': 'window', 'size': 'tall'},
                        {'slot': 9, 'span': 1, 'kind': 'door'}])
    spec, _ = hf.normalize(raw)
    kinds = sorted(g['kind'] for g in spec['ground'])
    check(kinds == ['door', 'porch', 'window'], f'porch overlays: {kinds}')
    # but never on the garage face (the driveway)
    spec, notes = hf.normalize(_spec(ground=[{'slot': 10, 'span': 1, 'kind': 'door'},
                                             {'slot': 0, 'span': 2, 'kind': 'porch', 'type': 'stoop'}]))
    check(not any(g['kind'] == 'porch' for g in spec['ground']), 'no porch in the driveway')
    check(any('driveway' in n or 'garage' in n for n in notes), 'noted')


def scenario_roof_priority_and_no_bans():
    raw = _spec(roof=[{'slot': 6, 'span': 4, 'kind': 'dormer', 'window': True},
                      {'slot': 8, 'span': 2, 'kind': 'gable'},
                      {'slot': 0, 'span': 3, 'kind': 'gable'}])          # garage face gable is fine
    spec, _ = hf.normalize(raw)
    d = [r for r in spec['roof'] if r['kind'] == 'dormer']
    g = sorted((r['slot'], r['span']) for r in spec['roof'] if r['kind'] == 'gable')
    check(d == [{'slot': 6, 'span': 2, 'kind': 'dormer', 'window': True}], f'dormer trimmed: {d}')
    check(g == [(0, 3), (8, 2)], f'both gables kept: {g}')


def scenario_budget_caps_drop_east_most_first():
    ground = [{'slot': i, 'span': 1, 'kind': 'window', 'size': 'tall'} for i in range(6, 14)]
    ground += [{'slot': i, 'span': 1, 'kind': 'window', 'size': 'tall'} for i in range(14, 18)]
    ground += [{'slot': i, 'span': 1, 'kind': 'window', 'size': 'tall'} for i in range(3, 6)]
    ground.append({'slot': 9, 'span': 1, 'kind': 'door'})
    spec, notes = hf.normalize(_spec(ground=ground))
    wins = [g for g in spec['ground'] if g['kind'] == 'window']
    check(len(wins) == hf.MAX_WINDOWS, f'capped at {hf.MAX_WINDOWS}: {len(wins)}')
    check(max(g['slot'] for g in wins) < 17, 'the east-most windows went first')
    check(any('window' in n for n in notes), 'noted')


def scenario_sorted_and_deduped():
    raw = _spec(ground=[{'slot': 9, 'span': 1, 'kind': 'door'},
                        {'slot': 7, 'span': 1, 'kind': 'window', 'size': 'tall'},
                        {'slot': 7, 'span': 1, 'kind': 'window', 'size': 'small'}])
    spec, _ = hf.normalize(raw)
    slots = [g['slot'] for g in spec['ground']]
    check(slots == sorted(slots) and slots.count(7) == 1, f'sorted, one entry per slot: {slots}')


def scenario_wall_and_eave_entries_are_dropped():
    raw = _spec(ground=hf.CANONICAL['ground'] + [{'slot': 3, 'span': 1, 'kind': 'wall'}],
                roof=hf.CANONICAL['roof'] + [{'slot': 3, 'span': 1, 'kind': 'eave'}])
    spec, _ = hf.normalize(raw)
    check(spec == hf.CANONICAL, 'wall/eave are the defaults and never stored')


def scenario_garbage_in_never_raises():
    for raw in (None, 3, 'x', [], {}, {'ground': 'no'}, {'ground': [None, 3, {'kind': 'door'}]},
                {'roof': [{'slot': 'a', 'span': -2, 'kind': 'gable'}]}):
        spec, _ = hf.normalize(raw)
        check(spec['version'] == 1 and any(g['kind'] == 'door' for g in spec['ground']),
              f'{raw!r} -> a valid spec')


def scenario_worst_case_is_within_caps():
    w = hf.worst_case()
    spec, notes = hf.normalize(w)
    check(spec == w, f'worst case is already normal; notes {notes}')
    wins = sum(g['kind'] == 'window' for g in spec['ground'])
    dw = sum(1 for r in spec['roof'] if r['kind'] == 'dormer' and r.get('window'))
    check(wins + dw == hf.MAX_WINDOWS, f'worst case uses every window: {wins}+{dw}')
    check(sum(r['kind'] == 'dormer' for r in spec['roof']) == hf.MAX_DORMERS, 'every dormer')
    check(sum(r['kind'] == 'gable' for r in spec['roof']) == hf.MAX_GABLES, 'every gable')
    check(sum(g['span'] for g in spec['ground'] if g['kind'] == 'porch') == hf.MAX_PORCH_SLOTS,
          'porch slots at the cap')
    gd = next(g for g in spec['ground'] if g['kind'] == 'garage_door')
    check(gd['style'] == 'glass' and gd['leaves'] == 2, 'heaviest garage door')


if __name__ == '__main__':
    for fn in (scenario_slot_table_is_derived_from_the_faces,
               scenario_canonical_is_normal_and_idempotent,
               scenario_unknown_enums_fall_to_defaults,
               scenario_pitch_clamps,
               scenario_spans_truncate_at_face_boundaries,
               scenario_openings_pin_to_their_room_face,
               scenario_overlap_priority_trims_the_loser,
               scenario_roof_priority_and_no_bans,
               scenario_budget_caps_drop_east_most_first,
               scenario_sorted_and_deduped,
               scenario_wall_and_eave_entries_are_dropped,
               scenario_garbage_in_never_raises,
               scenario_worst_case_is_within_caps):
        fn()
        print('  ok ', fn.__name__)
```

- [ ] **Step 2: Run, expect ImportError** (`cd chauffeur && python tests/test_house_facade.py`).

- [ ] **Step 3: Implement `house_facade.py`**

```python
"""The Home's facade generator (spec docs/superpowers/specs/
2026-09-15-house-facade-generator-design.md).

Pure functions above the line, storage below it. The slot table and the
canonical facade are the JS side's single source of truth too: a live
test pins window.chfFacadeSlots() against slot_table()."""
import copy
import math
import time
import uuid

SLOT_W = 1.85
# West to east. Mirrors house.js: FULL_HOUSE, SWZ1, EXT_TOP4, the garage IIFE.
FACES = [
    {'face': 'garage',  'x0': -18.20, 'x1': -12.60, 'z': 10.10, 'eave': 4.7, 'room': 'garage',  'roof': 'massing_service_roof'},
    {'face': 'mudroom', 'x0': -12.60, 'x1': -7.15,  'z': 10.10, 'eave': 5.6, 'room': 'mudroom', 'roof': 'mudroom_cross_roof'},
    {'face': 'main',    'x0': -7.15,  'x1': 6.85,   'z': 14.55, 'eave': 5.6, 'room': 'living',  'roof': 'roof_main'},
    {'face': 'wing',    'x0': 6.85,   'x1': 14.65,  'z': 16.72, 'eave': 5.6, 'room': 'study',   'roof': 'massing_front_roof'},
]

GROUND_KINDS = ('wall', 'window', 'door', 'garage_door', 'porch')
ROOF_KINDS = ('eave', 'gable', 'dormer', 'hip_end')
WINDOW_SIZES = ('tall', 'standard', 'small')
PORCH_TYPES = ('sitting', 'stoop', 'covered')
GARAGE_STYLES = ('carriage', 'panel', 'glass')
STYLE = {
    'cladding': ('batten', 'clapboard'),
    'body': ('white', 'greige', 'sage', 'slate', 'navy'),
    'roof': ('charcoal', 'weathered', 'brown'),
    'frame': ('black', 'white'),
    'door': ('wood', 'black', 'red', 'sage'),
    'trim': ('white', 'black'),
}
PITCH_MIN, PITCH_MAX = 22.5, 35.0
# Draw-budget constants, not grammar (spec 4.7). Tuned in the probe task.
MAX_WINDOWS = 10
MAX_DORMERS = 6
MAX_GABLES = 4
MAX_PORCH_SLOTS = 10

_GROUND_RANK = {'garage_door': 3, 'door': 2, 'window': 1}      # exclusive kinds
_ROOF_RANK = {'gable': 3, 'dormer': 2, 'hip_end': 1}


def slot_table():
    out, i = [], 0
    for f in FACES:
        width = f['x1'] - f['x0']
        n = max(1, int(round(width / SLOT_W)))
        w = width / n
        for k in range(n):
            x0 = f['x0'] + k * w
            out.append({'i': i, 'face': f['face'], 'x0': round(x0, 6), 'x1': round(x0 + w, 6),
                        'cx': round(x0 + w / 2, 6), 'z': f['z'], 'eave': f['eave'],
                        'room': f['room'], 'roof': f['roof']})
            i += 1
    return out


def _face_range(face):
    idx = [s['i'] for s in slot_table() if s['face'] == face]
    return idx[0], idx[-1]


CANONICAL = {
    'version': 1,
    'pitch_deg': round(math.degrees(math.atan2(2.05, 2.95)), 1),   # 34.8, PITCH_FAMILY
    'style': {'cladding': 'batten', 'body': 'white', 'roof': 'charcoal',
              'frame': 'black', 'door': 'wood', 'trim': 'white'},
    'ground': [
        {'slot': 0, 'span': 3, 'kind': 'garage_door', 'style': 'carriage', 'leaves': 1},
        {'slot': 7, 'span': 1, 'kind': 'window', 'size': 'tall'},
        {'slot': 9, 'span': 4, 'kind': 'porch', 'type': 'sitting'},   # sorted by (slot, kind): porch < window
        {'slot': 9, 'span': 1, 'kind': 'window', 'size': 'tall'},
        {'slot': 10, 'span': 1, 'kind': 'door'},
        {'slot': 12, 'span': 1, 'kind': 'window', 'size': 'tall'},
        {'slot': 15, 'span': 1, 'kind': 'window', 'size': 'standard'},
        {'slot': 16, 'span': 1, 'kind': 'window', 'size': 'standard'},
    ],
    'roof': [
        {'slot': 0, 'span': 3, 'kind': 'gable'},
        {'slot': 9, 'span': 4, 'kind': 'gable'},
    ],
}


def _num(v, default):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _pick(v, allowed, default):
    return v if v in allowed else default


def _entries(raw_list, kinds, notes, layer):
    """Shape each entry: known kind, int slot/span, per-kind fields."""
    out = []
    if not isinstance(raw_list, list):
        return out
    nslots = len(slot_table())
    for e in raw_list:
        if not isinstance(e, dict):
            continue
        kind = e.get('kind')
        if kind not in kinds:
            notes.append(f"dropped an unknown {layer} feature '{kind}'")
            continue
        if kind in ('wall', 'eave'):
            continue
        slot = _int(e.get('slot'), -1)
        if slot < 0 or slot >= nslots:
            notes.append(f"dropped a {kind} outside the elevation (slot {e.get('slot')!r})")
            continue
        span = max(1, _int(e.get('span'), 1))
        item = {'slot': slot, 'span': span, 'kind': kind}
        if kind == 'window':
            item['size'] = _pick(e.get('size'), WINDOW_SIZES, 'standard')
        elif kind == 'porch':
            item['type'] = _pick(e.get('type'), PORCH_TYPES, 'covered')
        elif kind == 'garage_door':
            item['style'] = _pick(e.get('style'), GARAGE_STYLES, 'carriage')
            item['leaves'] = 2 if _int(e.get('leaves'), 1) == 2 else 1
        elif kind == 'dormer':
            item['window'] = bool(e.get('window', True))
        out.append(item)
    return out


def _clip_to_face(item, notes):
    """Spans never cross a face (spec 4.3)."""
    slots = slot_table()
    face = slots[item['slot']]['face']
    lo, hi = _face_range(face)
    end = min(item['slot'] + item['span'] - 1, hi)
    if end != item['slot'] + item['span'] - 1:
        notes.append(f"{item['kind']} at slot {item['slot']} truncated at the {face} face boundary")
    item['span'] = end - item['slot'] + 1
    return face


def _resolve_exclusive(items, rank, notes):
    """Higher rank owns its slots; lower ranks are trimmed to what is free,
    split around a winner if needed, dropped when nothing is left."""
    taken = {}
    ordered = sorted(items, key=lambda it: (-rank[it['kind']], it['slot']))
    kept = []
    for it in ordered:
        free = [s for s in range(it['slot'], it['slot'] + it['span']) if s not in taken]
        if not free:
            notes.append(f"dropped a {it['kind']} at slot {it['slot']}: its slots were taken")
            continue
        runs, run = [], [free[0]]
        for s in free[1:]:
            if s == run[-1] + 1:
                run.append(s)
            else:
                runs.append(run); run = [s]
        runs.append(run)
        if len(runs) > 1 or len(free) != it['span']:
            notes.append(f"trimmed a {it['kind']} at slot {it['slot']} around a higher feature")
        for r in runs:
            piece = dict(it); piece['slot'] = r[0]; piece['span'] = len(r)
            kept.append(piece)
            for s in r:
                taken[s] = piece['kind']
    return kept


def normalize(raw):
    notes = []
    raw = raw if isinstance(raw, dict) else {}
    slots = slot_table()
    spec = {'version': 1}
    p = _num(raw.get('pitch_deg'), CANONICAL['pitch_deg'])
    spec['pitch_deg'] = round(min(PITCH_MAX, max(PITCH_MIN, p)), 1)
    st = raw.get('style') if isinstance(raw.get('style'), dict) else {}
    spec['style'] = {k: _pick(st.get(k), allowed, CANONICAL['style'][k])
                     for k, allowed in STYLE.items()}

    ground = _entries(raw.get('ground'), GROUND_KINDS, notes, 'ground')
    roof = _entries(raw.get('roof'), ROOF_KINDS, notes, 'roof')

    # pin openings to their room's face (spec 4.4)
    g_lo, g_hi = _face_range('garage')
    m_lo, m_hi = _face_range('main')
    gds = [g for g in ground if g['kind'] == 'garage_door']
    ground = [g for g in ground if g['kind'] != 'garage_door']
    if gds:
        gd = gds[0]
        if len(gds) > 1:
            notes.append('one garage bay: extra garage doors dropped')
        if gd['slot'] != g_lo or gd['span'] != g_hi - g_lo + 1:
            notes.append('the garage door spans its own bay')
        gd['slot'], gd['span'] = g_lo, g_hi - g_lo + 1
        ground.append(gd)
    doors = [g for g in ground if g['kind'] == 'door']
    for d in doors:
        if not (m_lo <= d['slot'] <= m_hi):
            notes.append(f"front door moved onto the main face (was slot {d['slot']})")
            d['slot'] = min(max(d['slot'], m_lo), m_hi)
        d['span'] = 1
    if not doors:
        ground.append(dict(next(g for g in CANONICAL['ground'] if g['kind'] == 'door')))
        notes.append('a house needs a front door: the canonical one was added')

    # faces are hard boundaries; porch never in the driveway (spec 4.3, 4.5)
    kept = []
    for g in ground:
        face = _clip_to_face(g, notes)
        if g['kind'] == 'porch' and face == 'garage':
            notes.append('no porch in the driveway (garage face)')
            continue
        kept.append(g)
    ground = kept
    for r in roof:
        _clip_to_face(r, notes)

    porches = [g for g in ground if g['kind'] == 'porch']
    exclusive = _resolve_exclusive([g for g in ground if g['kind'] != 'porch'], _GROUND_RANK, notes)
    roof = _resolve_exclusive(roof, _ROOF_RANK, notes)

    # budget caps, east-most first (spec 4.7)
    def cap(items, kind, limit, extra=0):
        own = sorted([i for i in items if i['kind'] == kind], key=lambda i: i['slot'])
        keep = max(0, limit - extra)
        if len(own) > keep:
            notes.append(f"kept {keep} {kind}s of {len(own)} (draw budget)")
        drop = {id(i) for i in own[keep:]}
        return [i for i in items if id(i) not in drop]
    roof = cap(roof, 'dormer', MAX_DORMERS)
    roof = cap(roof, 'gable', MAX_GABLES)
    dormer_windows = sum(1 for r in roof if r['kind'] == 'dormer' and r['window'])
    exclusive = cap(exclusive, 'window', MAX_WINDOWS, extra=dormer_windows)
    total = 0
    porch_keep = []
    for pch in sorted(porches, key=lambda i: i['slot']):
        if total + pch['span'] > MAX_PORCH_SLOTS:
            pch['span'] = MAX_PORCH_SLOTS - total
            notes.append('porch shortened (draw budget)')
        if pch['span'] <= 0:
            continue
        total += pch['span']
        porch_keep.append(pch)
    # porches never overlap each other; later loses
    seen = set()
    porches = []
    for pch in porch_keep:
        cells = set(range(pch['slot'], pch['slot'] + pch['span']))
        if cells & seen:
            notes.append('overlapping porches merged')
            continue
        seen |= cells
        porches.append(pch)

    ground = sorted(exclusive + porches, key=lambda g: (g['slot'], g['kind']))
    spec['ground'] = ground
    spec['roof'] = sorted(roof, key=lambda r: (r['slot'], r['kind']))
    return spec, notes


def worst_case():
    """The heaviest spec the caps allow — the budget probe's input."""
    slots = slot_table()
    g_lo, g_hi = _face_range('garage')
    m_lo, m_hi = _face_range('main')
    ground = [{'slot': g_lo, 'span': g_hi - g_lo + 1, 'kind': 'garage_door', 'style': 'glass', 'leaves': 2},
              {'slot': m_lo, 'span': 1, 'kind': 'door'}]
    roof = []
    dormers = 0
    for s in slots:
        if s['face'] != 'garage' and dormers < MAX_DORMERS:
            roof.append({'slot': s['i'], 'span': 1, 'kind': 'dormer', 'window': True})
            dormers += 1
    windows = MAX_WINDOWS - dormers
    for s in slots[g_hi + 1:]:
        if s['i'] == m_lo or windows <= 0:
            continue
        ground.append({'slot': s['i'], 'span': 1, 'kind': 'window', 'size': 'tall'})
        windows -= 1
    ground.append({'slot': m_lo, 'span': min(MAX_PORCH_SLOTS, m_hi - m_lo + 1), 'kind': 'porch', 'type': 'sitting'})
    left = MAX_PORCH_SLOTS - (m_hi - m_lo + 1)
    if left > 0:
        ground.append({'slot': m_hi + 1, 'span': left, 'kind': 'porch', 'type': 'sitting'})
    gables = 0
    for s in slots:
        if gables >= MAX_GABLES:
            break
        if s['i'] not in {r['slot'] for r in roof}:
            roof.append({'slot': s['i'], 'span': 1, 'kind': 'gable'})
            gables += 1
    spec, _ = normalize({'version': 1, 'pitch_deg': PITCH_MAX,
                         'style': {'cladding': 'clapboard', 'body': 'navy', 'roof': 'brown',
                                   'frame': 'white', 'door': 'red', 'trim': 'black'},
                         'ground': ground, 'roof': roof})
    return spec
```

Adjust `worst_case()` until `scenario_worst_case_is_within_caps` passes (it must produce exactly the cap counts after normalize; if a gable lands on a dormer slot the dormer wins and the gable is lost — choose gable slots from slots without dormers, as written).

- [ ] **Step 4: Run the file until every scenario prints `ok`.** Fix the implementation, never the laws. If a canonical slot number in the test disagrees with `slot_table()` output, the TEST's expectation was derived by hand from spec §2.2 — recompute from `SLOT_W` and the face widths and fix the spec §2.2 numbers in the same commit (docs), never the rule.

- [ ] **Step 5: Sweep, bump, commit, push** — `feat: house facade laws — slots, canonical, normalize (vX.Y.Z)`.

---

### Task 3: Storage, routes, state and the template injection

**Files:**
- Modify: `chauffeur/services/house_facade.py` (storage half)
- Modify: `chauffeur/models/schemas.py` (`Settings`, next to `panel_home_board` ~1372)
- Modify: `chauffeur/services/settings_registry.py` (ENTRIES, `household` group)
- Modify: `chauffeur/services/auth.py` (RULES beside `/api/house/state`, ~368)
- Modify: `chauffeur/main.py` (`house_page` ~1720; new routes beside `house_state_api` ~5453)
- Modify: `chauffeur/services/house_room.py` (`state()`)
- Modify: `chauffeur/templates/house.html:209`
- Test: `chauffeur/tests/test_house_facade.py` (storage + route scenarios), `chauffeur/tests/test_house_state.py`

**Interfaces:**
- Produces:
  - `list_facades() -> list[dict]` (canonical first: `{'id':'canonical','name':'Canonical','readonly':True,'spec':CANONICAL,'source':'builtin'}`)
  - `save_facade(name, spec, activate=False) -> dict` (normalizes; `source` defaults `'hand'`, pass `source='photo'`)
  - `update_facade(fid, name=None, spec=None) -> dict|None` (raises `ValueError('readonly')` for canonical)
  - `delete_facade(fid) -> bool` (active falls back to canonical; canonical raises `ValueError('readonly')`)
  - `set_active(fid) -> str` (raises `KeyError` if unknown)
  - `active_bundle() -> dict` = `{'id', 'name', 'spec', 'slots': slot_table()}`
  - Routes per spec §3.2; `window.HOUSE_FACADE` = `active_bundle()` JSON in `house.html`.

- [ ] **Step 1: Failing storage/route tests** (append to `test_house_facade.py`; these use the harness temp DB):

```python
def _fresh():
    # harness.py replaces storage.get_settings with a constant lambda; the
    # storage laws need the real table, so read it directly.
    from services import storage
    storage.get_settings = lambda: dict((storage.settings_table.all() or [{}])[0])
    storage.update_settings({'calendar_ids': []})


def scenario_storage_laws():
    from services import storage
    _fresh()
    lst = hf.list_facades()
    check(lst[0]['id'] == 'canonical' and lst[0]['readonly'] and len(lst) == 1, 'canonical always listed first')
    check(hf.active_bundle()['id'] == 'canonical', 'canonical active by default')
    rec = hf.save_facade('Ours', hf.worst_case())
    check(rec['id'] and rec['source'] == 'hand' and rec['spec'] == hf.worst_case(), 'saved normalized')
    check(hf.active_bundle()['id'] == 'canonical', 'saving never activates unless asked')
    check(hf.set_active(rec['id']) == rec['id'] and hf.active_bundle()['spec'] == hf.worst_case(), 'activated')
    up = hf.update_facade(rec['id'], name='Ours 2', spec={'ground': []})
    check(up['name'] == 'Ours 2' and any(g['kind'] == 'door' for g in up['spec']['ground']), 'update normalizes')
    try:
        hf.update_facade('canonical', name='x'); check(False, 'canonical is readonly')
    except ValueError:
        pass
    try:
        hf.delete_facade('canonical'); check(False, 'canonical cannot be deleted')
    except ValueError:
        pass
    check(hf.delete_facade(rec['id']) and hf.active_bundle()['id'] == 'canonical', 'deleting the active one falls back')
    check(hf.delete_facade('nope') is False, 'unknown delete is False')
    try:
        hf.set_active('nope'); check(False, 'unknown activate raises')
    except KeyError:
        pass
    storage.update_settings({'calendar_ids': [], 'house_facade_active': 'ghost'})
    check(hf.active_bundle()['id'] == 'canonical', 'a dangling active id never breaks the house')


def scenario_routes_and_template():
    import io, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    auth = io.open(os.path.join(root, 'services', 'auth.py'), encoding='utf-8').read()
    for line in ("('GET', '/api/house/facades', WALL_OR_SERVICE, None)",
                 "('POST', '/api/house/facades', PARENTS, None)",
                 "('POST', '/api/house/facades/preview', PARENTS, None)",
                 "('POST', '/api/house/facades/photo', PARENTS, None)",
                 "('PUT', '/api/house/facades/active', PARENTS, None)",
                 "('PUT', '/api/house/facades/{fid}', PARENTS, None)",
                 "('DELETE', '/api/house/facades/{fid}', PARENTS, None)"):
        check(line in auth, f'auth rule present: {line}')
    tpl = io.open(os.path.join(root, 'templates', 'house.html'), encoding='utf-8').read()
    check('window.HOUSE_FACADE = ' in tpl and tpl.index('window.HOUSE_FACADE') < tpl.index("static/house.js"),
          'the facade is injected before house.js loads (build-once)')
    import main
    out = main.house_facades_api()
    check(out['active'] == 'canonical' and out['facades'][0]['id'] == 'canonical' and len(out['slots']) == 18,
          'GET lists canonical + slots')
    prev = main.house_facade_preview({'spec': {'ground': []}})
    check(any(g['kind'] == 'door' for g in prev['spec']['ground']) and prev['notes'], 'preview normalizes, stores nothing')
    check(len(hf.list_facades()) == 1, 'preview stored nothing')
```

Add both to the runner. In `test_house_state.py` add:

```python
def scenario_state_carries_the_facade():
    _reset()
    storage.get_cached_schedule = lambda: {}
    st = house_room.state(since_ts=0)
    check(st['facade']['id'] == 'canonical' and len(st['facade']['slots']) == 18,
          'state carries the active facade bundle, canonical by default')
```
(`_reset` pins `storage.get_settings = lambda: {}` — `active_bundle()` must treat an empty settings dict as canonical.)

- [ ] **Step 2: Run both files, expect failures** (`AttributeError: list_facades`, missing auth rules).

- [ ] **Step 3: Implement**

`house_facade.py` storage half (below a `# --- storage ---` line):

```python
CANONICAL_ID = 'canonical'


def _settings():
    from services import storage
    return storage.get_settings() or {}


def _write(patch):
    from services import storage
    cur = dict(storage.get_settings() or {})
    cur.update(patch)
    storage.update_settings(cur)


def _saved():
    rows = _settings().get('house_facades') or []
    return [r for r in rows if isinstance(r, dict) and r.get('id')]


def list_facades():
    return [{'id': CANONICAL_ID, 'name': 'Canonical', 'readonly': True,
             'source': 'builtin', 'spec': copy.deepcopy(CANONICAL)}] + copy.deepcopy(_saved())


def save_facade(name, spec, activate=False, source='hand'):
    clean, _ = normalize(spec)
    now = time.time()
    rec = {'id': uuid.uuid4().hex[:12], 'name': (str(name or '').strip() or 'My house')[:60],
           'spec': clean, 'source': source if source in ('hand', 'photo') else 'hand',
           'created_at': now, 'updated_at': now}
    patch = {'house_facades': _saved() + [rec]}
    if activate:
        patch['house_facade_active'] = rec['id']
    _write(patch)
    return rec


def update_facade(fid, name=None, spec=None):
    if fid == CANONICAL_ID:
        raise ValueError('readonly')
    rows = _saved()
    for r in rows:
        if r['id'] == fid:
            if name is not None:
                r['name'] = (str(name).strip() or r['name'])[:60]
            if spec is not None:
                r['spec'], _ = normalize(spec)
            r['updated_at'] = time.time()
            _write({'house_facades': rows})
            return r
    return None


def delete_facade(fid):
    if fid == CANONICAL_ID:
        raise ValueError('readonly')
    rows = _saved()
    keep = [r for r in rows if r['id'] != fid]
    if len(keep) == len(rows):
        return False
    patch = {'house_facades': keep}
    if _settings().get('house_facade_active') == fid:
        patch['house_facade_active'] = CANONICAL_ID
    _write(patch)
    return True


def set_active(fid):
    if fid != CANONICAL_ID and not any(r['id'] == fid for r in _saved()):
        raise KeyError(fid)
    _write({'house_facade_active': fid})
    return fid


def active_bundle():
    fid = _settings().get('house_facade_active') or CANONICAL_ID
    rec = next((r for r in _saved() if r['id'] == fid), None)
    if rec is None:
        return {'id': CANONICAL_ID, 'name': 'Canonical', 'spec': copy.deepcopy(CANONICAL), 'slots': slot_table()}
    spec, _ = normalize(rec.get('spec'))
    return {'id': rec['id'], 'name': rec['name'], 'spec': spec, 'slots': slot_table()}
```

`schemas.py` `Settings`, beside `panel_home_board`:
```python
    # The Home's street elevation (facade generator, spec 2026-09-15). Saved
    # facades are whole specs; the active id selects one, 'canonical' = the
    # built-in elevation. Never edited by hand outside services/house_facade.
    house_facades: List[dict] = Field(default_factory=list)
    house_facade_active: str = 'canonical'
```

`settings_registry.py` ENTRIES (household group):
```python
    _e('house_facades', 'household', 'Saved house facades',
       'Street elevations of the Home you have saved: from a photo or drawn by hand.',
       anchor='home'),
    _e('house_facade_active', 'household', 'Active house facade',
       'Which saved facade the Home builds its street face from.', anchor='home'),
```
(The audit will report `no #home target on 'config'` until Task 7 adds the section — add a placeholder `<div id="home"></div>` inside the family tab NOW so the sweep stays green; Task 7 replaces it.)

`auth.py` RULES, after the `/api/house/state` row:
```python
    # The facade generator (spec 2026-09-15 §3.2): reads are family-safe
    # (a wall builds from the active facade); every write is a parent's.
    ('GET', '/api/house/facades', WALL_OR_SERVICE, None),
    ('POST', '/api/house/facades', PARENTS, None),
    ('POST', '/api/house/facades/preview', PARENTS, None),
    ('POST', '/api/house/facades/photo', PARENTS, None),
    ('PUT', '/api/house/facades/active', PARENTS, None),
    ('PUT', '/api/house/facades/{fid}', PARENTS, None),
    ('DELETE', '/api/house/facades/{fid}', PARENTS, None),
```
Order matters if the matcher is first-wins: `/active` must precede `/{fid}` (check how `RULES` are matched — read the matcher near `auth.py:600-650` before placing).

`main.py`, beside `house_state_api`:
```python
@app.get("/api/house/facades")
def house_facades_api():
    from services import house_facade as _hf
    return {'active': _hf.active_bundle()['id'], 'facades': _hf.list_facades(),
            'slots': _hf.slot_table()}


@app.post("/api/house/facades/preview")
def house_facade_preview(body: dict = Body(default={})):
    """Pure round-trip for the editor: normalize + notes, stores nothing."""
    from services import house_facade as _hf
    spec, notes = _hf.normalize((body or {}).get('spec'))
    return {'spec': spec, 'notes': notes}


@app.post("/api/house/facades")
def house_facade_create(body: dict = Body(default={})):
    from services import house_facade as _hf
    body = body or {}
    rec = _hf.save_facade(body.get('name'), body.get('spec'), activate=bool(body.get('activate')),
                          source=body.get('source') or 'hand')
    return {'facade': rec, 'active': _hf.active_bundle()['id']}


@app.put("/api/house/facades/active")
def house_facade_activate(body: dict = Body(default={})):
    from services import house_facade as _hf
    try:
        fid = _hf.set_active(str((body or {}).get('id') or ''))
    except KeyError:
        raise HTTPException(status_code=404, detail="No such facade")
    return {'active': fid}


@app.put("/api/house/facades/{fid}")
def house_facade_update(fid: str, body: dict = Body(default={})):
    from services import house_facade as _hf
    try:
        rec = _hf.update_facade(fid, name=(body or {}).get('name'), spec=(body or {}).get('spec'))
    except ValueError:
        raise HTTPException(status_code=409, detail="The canonical facade is read-only")
    if rec is None:
        raise HTTPException(status_code=404, detail="No such facade")
    return {'facade': rec}


@app.delete("/api/house/facades/{fid}")
def house_facade_delete(fid: str):
    from services import house_facade as _hf
    try:
        ok = _hf.delete_facade(fid)
    except ValueError:
        raise HTTPException(status_code=409, detail="The canonical facade is read-only")
    if not ok:
        raise HTTPException(status_code=404, detail="No such facade")
    return {'status': 'ok', 'active': _hf.active_bundle()['id']}
```
Declare the `/active` route BEFORE the `/{fid}` routes (FastAPI matches in declaration order).

`house_page`:
```python
@app.get("/house")
def house_page(request: Request):
    """The Home: the dollhouse the panel lives in (spec
    2026-09-08-house-design.md). URL-only until H4 flips the panel home.
    The active facade rides the page: the scene builds before its first
    state fetch, so build-once means the spec arrives with the HTML."""
    import json as _json
    from services import house_facade as _hf
    facade_json = _json.dumps(_hf.active_bundle()).replace('</', '<\\/')
    return templates.TemplateResponse(request=request, name="house.html",
                                      context={'facade_json': facade_json})
```
`house.html:209` becomes:
```html
    <script>window.HOUSE_STATE_URL = (window.chfBase !== undefined ? window.chfBase : '') + 'api/house/state';
            window.HOUSE_FACADE = {{ facade_json|safe }};</script>
```
`house_room.state`, next to `attention`:
```python
    from services import house_facade
    try:
        out['facade'] = house_facade.active_bundle()
    except Exception:
        out['facade'] = None
```
(`house_room.py` must not import `storage` writers — `active_bundle` only reads; the never-writes pin greps `house_room.py` source, not its imports.)

- [ ] **Step 4: Run `test_house_facade.py`, `test_house_state.py`, `test_settings_registry.py`, `test_auth*.py`** → all ok.

- [ ] **Step 5: Sweep, bump, commit, push** — `feat: facade storage, routes and page injection (vX.Y.Z)`.

---

### Task 4: `house.js` — palette, slots, builders, `buildElevation`, canonical pin

**Files:**
- Modify: `chauffeur/static/house.js` — `FARMHOUSE` (~3693–3714), cladding painters (~3759–3812), the south-wall block (~3980–4245: `swWindow`, door, porch, lamp, `porch_roof` call at ~4421), `massing_east_front_south` windows arg (~4425), the garage IIFE door style block (~4620–4720), `garage_gable` call (~4487), `EXTERIOR_HINTS` (~9771), exposure block (~9638)
- Test: `chauffeur/tests/test_house_live.py`

**Interfaces:**
- Consumes: `window.HOUSE_FACADE = {id, name, spec, slots}`.
- Produces: `window.chfFacade()` → the spec built from; `window.chfFacadeSlots()` → the JS slot table; fabric names `facade_<face>_<kind>_<slot>` (+ `_front|_west|_east|...` suffixes `shellGable` already appends); `userData.entry = 'front_door'` on the west-most main-face door; the garage face gable registers with names starting `facade_garage_gable_0`.

- [ ] **Step 1: Record the pre-arc pin (RED-first)**

Add to `test_house_live.py`:

```python
# Recorded at HEAD <sha> before Task 4 replaced the hand-authored street
# face with buildElevation(): exterior, quality=high, INVARIANT_JS meshes.
CANONICAL_EXTERIOR_MESHES = 0   # <- fill with the measured number


def scenario_canonical_facade_pins_the_hand_built_elevation():
    served = live_app()
    if served is None:
        return
    with served.browser() as page:
        page.add_init_script(DAY_LOCK_JS)
        page.goto(served.url('house?quality=high'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_timeout(2200)
        inv = page.evaluate(INVARIANT_JS)
        check(inv['meshes'] == CANONICAL_EXTERIOR_MESHES,
              f"canonical facade builds the same exterior mesh count: {inv['meshes']} != {CANONICAL_EXTERIOR_MESHES}")
        from services import house_facade as hf
        check(page.evaluate('window.chfFacade()') == hf.CANONICAL, 'built from CANONICAL')
        js_slots = page.evaluate('window.chfFacadeSlots()')
        py_slots = hf.slot_table()
        check(len(js_slots) == len(py_slots), 'same slot count')
        for a, b in zip(js_slots, py_slots):
            for k in ('x0', 'x1', 'cx', 'z'):
                check(abs(a[k] - b[k]) < 1e-6, f'slot {b["i"]} {k}: {a[k]} vs {b[k]}')
            check(a['face'] == b['face'] and a['room'] == b['room'], f'slot {b["i"]} face/room')
```
Run once with a temporary `print(inv['meshes'])`, paste the number into `CANONICAL_EXTERIOR_MESHES`, delete the print. Also in `scenario_shell_fabric_registry` change `expected_names` to be checked as a SUBSET of what will remain hand-registered (everything except `south_wall`'s porch/gable pieces, `porch_roof_*`, `garage_gable_*`), and add a second check that every name starting `facade_` in `fab` maps to a `CANONICAL` entry (`facade_main_door_10`, `facade_main_window_7`, `facade_main_porch_9`, `facade_main_gable_9_*`, `facade_garage_gable_0_*`, `facade_wing_window_15`, ...). Update the real-mouse scenario's `exterior_targets` set to `{'patio_slider', 'front_door', 'mudroom_cross_roof_south', 'garage_front'}` (see Step 4 for the marker change).

- [ ] **Step 2: Run the live file → the new scenario fails** (`chfFacade is not a function`).

- [ ] **Step 3: Implement in house.js**

(a) **Palette.** Replace the `FARMHOUSE` literal with:
```js
    var PALETTE = {
      body:  { white: 0xf4f1e9, greige: 0xd9d2c5, sage: 0xb7c2ad, slate: 0x6f7b85, navy: 0x2f3e55 },
      roof:  { charcoal: 0x2b2f33, weathered: 0x7d7a72, brown: 0x5a4636 },
      frame: { black: 0x1b1c1e, white: 0xf7f5ef },
      door:  { wood: 0x6b4a30, black: 0x1b1c1e, red: 0x9b2f2a, sage: 0x7d8f74 },
      trim:  { white: 0xf7f5ef, black: 0x1b1c1e }
    };
    var FACADE = (window.HOUSE_FACADE && window.HOUSE_FACADE.spec) ? window.HOUSE_FACADE : null;
    var FSTYLE = FACADE ? FACADE.spec.style : { cladding: 'batten', body: 'white', roof: 'charcoal', frame: 'black', door: 'wood', trim: 'white' };
    function pal(role, name, fallback) { var t = PALETTE[role]; return (t && t[name] !== undefined) ? t[name] : fallback; }
    var FARMHOUSE = {
      body:     pal('body', FSTYLE.body, 0xf4f1e9),
      roofTone: pal('roof', FSTYLE.roof, 0x2b2f33),
      frame:    pal('frame', FSTYLE.frame, 0x1b1c1e),
      wood:     pal('door', FSTYLE.door, 0x6b4a30),
      trim:     pal('trim', FSTYLE.trim, 0xf7f5ef),
      stoop: 0x8a8175, windowDark: 0x273438, curtainGlow: 0xd9ae73, curtainIntensity: 0.68
    };
    function hex6(c) { return '#' + ('000000' + c.toString(16)).slice(-6); }
```
Every existing `FARMHOUSE.*` read (68 sites) keeps working. In the painters, `battenT`'s `g.fillStyle = '#f4f1e9'` becomes `hex6(FARMHOUSE.body)`; `sidingT`'s base fill likewise; `shingleT`'s `'#2b2f33'` becomes `hex6(FARMHOUSE.roofTone)`. Cladding: define `var CLAD = function () { return FSTYLE.cladding === 'clapboard' ? sidingT : battenT; };` after both painters exist and replace the 22 `map: battenT` cladding call sites with `map: CLAD()` (the `sidingMat` seed line stays as is). Pitch: `var PITCH_FAMILY = FACADE ? FACADE.spec.pitch_deg * Math.PI / 180 : Math.atan2(PITCH_RISE4, PITCH_RUN4);`.

(b) **Slots (JS mirror).** After `FULL_HOUSE`:
```js
    var SLOT_W = 1.85;
    var FACES = [
      { face: 'garage',  x0: -18.20, x1: -12.60, z: 10.10, eave: 4.7, room: 'garage',  roof: 'massing_service_roof' },
      { face: 'mudroom', x0: -12.60, x1: FULL_HOUSE.west, z: 10.10, eave: 5.6, room: 'mudroom', roof: 'mudroom_cross_roof' },
      { face: 'main',    x0: FULL_HOUSE.west, x1: FULL_HOUSE.east, z: SWZ1, eave: EXT_TOP4, room: 'living', roof: 'roof_main' },
      { face: 'wing',    x0: FULL_HOUSE.east, x1: FULL_HOUSE.studyEast, z: FULL_HOUSE.studySouth, eave: 5.6, room: 'study', roof: 'massing_front_roof' }
    ];
    function facadeSlots() {
      var out = [], i = 0;
      FACES.forEach(function (f) {
        var width = f.x1 - f.x0, n = Math.max(1, Math.round(width / SLOT_W)), w = width / n;
        for (var k = 0; k < n; k++) {
          var x0 = f.x0 + k * w;
          out.push({ i: i++, face: f.face, x0: x0, x1: x0 + w, cx: x0 + w / 2, z: f.z,
                     eave: f.eave, room: f.room, roof: f.roof });
        }
      });
      return out;
    }
    var SLOTS = facadeSlots();
    var SPEC = FACADE ? FACADE.spec : null;   /* null -> the hand fallback below never runs: the server always injects */
```
If `SPEC` is null (a served page without injection — only the 2D fallback path), use a JS literal `CANONICAL_JS` equal to Python `CANONICAL` (copy it verbatim; the live pin test guards drift).

(c) **Builders.** Each takes `(slot, feat)` where `slot` is `SLOTS[feat.slot]` and returns nothing; each creates its own `shellGroup()`, fills it with the existing idiom, and ends with `shellRegister(g, name, normal, room, twoSided, pad, cutawayRoom)`. Span extent helpers:
```js
    function spanX(feat) { var a = SLOTS[feat.slot], b = SLOTS[feat.slot + feat.span - 1]; return { x0: a.x0, x1: b.x1, cx: (a.x0 + b.x1) / 2, w: b.x1 - a.x0, slot: a }; }
    var WINDOW_SIZES = { tall: [1.6, 3.7], standard: [1.55, 2.7], small: [1.0, 1.2] };
```
- `windowAt(feat)`: on the `main` face, the existing `swWindow` body (moved into this function, parameterised by `cx`, `w`, `h`, head `WIN_HEAD4`, z from `slot.z`, tagging `userData.room = slot.room`, own `shellGroup`); on every other face, `shellWindow(g, cx, headY - h/2, slot.z + WALL_T4/2 + 0.05, 0, w, h, true)` (the wing/mudroom/garage idiom: dark pane + glow). Head height: main `WIN_HEAD4` (4.4); others `4.15` (today's wing head: y 2.80 + 1.35). Name `facade_<face>_window_<slot>`.
- `doorAt(feat)`: today's door block (leaf via `chamferGeo(0.14,3.2,1.4,0.04)` rotated, casing, panels, knob, coach lamp at `cx - 0.85`) at `x = spanX(feat).cx`, `DOOR_Z4 = slot.z + 0.02`; leaf material colour reads `FARMHOUSE.wood` (so `door: black|red|sage` recolours the leaf: build the leaf with `mat(FARMHOUSE.wood, PBR ? {rough:0.65, map: woodDoor} : {rough:0.65})` — when the door colour is not `wood`, drop the `map`). Stamp `userData.entry = 'front_door'` only when `feat.slot` is the west-most door on the main face (compute once from `SPEC.ground`). Name `facade_main_door_<slot>`.
- `porchAt(feat)`: today's porch block with `PORCH_W4 = spanX(feat).w`, centred at `spanX(feat).cx`; `type` picks: `sitting` = posts + slab + step + benches + top beam; `covered` = posts + slab + step + beam (no benches); `stoop` = slab (depth 1.6) + step only, no posts. Name `facade_<face>_porch_<slot>`; room = slot.room.
- `garageDoorAt(feat)`: the existing carriage block moved out of the IIFE into this builder writing into `garageDoorG` (so the openable trick holds), width `feat.leaves === 2 ? 5.0 : 4.4` centred on the face centre, header/lintel unchanged; `style`: `carriage` = today's field + straps + X-brace + top lights; `panel` = four raised `box()` panels in a 2×2 grid, no brace, no lights; `glass` = frame `FARMHOUSE.frame` + four frosted panes (`0x9fc4dc`, `transparent`, `opacity 0.55`, `userData.glazing = true`) across the top half. Two leaves = one centre stile `box(0.12, doorH, 0.06, FARMHOUSE.frame, ...)`. Registration of `garageDoorG` stays exactly as today (name `garage_door`).
- `gableAt(feat)`: `shellGable('facade_' + face + '_gable_' + feat.slot, x0, x1, slot.z - 2.8, slot.z + (face === 'main' ? PORCH_DEPTH_OF_PORCH_UNDER_OR(2.2) : 2.2), slot.eave - 0.8, true, slot.room, [1], PITCH_FAMILY, null, null, false, slot.room)` — for the main face, when a porch shares the span, the front z is that porch's `PORCH_FRONT_Z4` (today's `porch_roof` call); the garage face reproduces today's `garage_gable` call (`z0 4.0, z1 10.1, eave 5.6, ends [1]`) when the span is the whole face.
- `dormerAt(feat)`: a `shellGroup` with a box body `shellBox(g, w-0.4, 1.9, 1.6, FARMHOUSE.body, cx, y, zc, {rough:0.95, map: CLAD()})` sitting on the face's roof plane (y from the plane: `slot.eave + 0.18 + (zc - slot.z) * -Math.tan(planePitch)` where `planePitch` is `Math.PI/8` for main/wing/mudroom/garage planes — all four street planes are the subordinate `Math.PI/8` slopes), a mini `shellGable` over it (`alongZ true`, `ends [1]`, pitch `PITCH_FAMILY`), and `shellWindow` on its front face when `feat.window`. Registered with `cutawayRoom = slot.room`. Name `facade_<face>_dormer_<slot>`.
- `hipEndAt(feat)`: two triangular `ExtrudeGeometry` returns (via `cgeo('hip|' + w + '|' + rise)`) closing the span's ends on the roof plane with `shingleT`; registered like a roof piece.

`buildElevation()`:
```js
    function buildElevation() {
      var spec = SPEC || CANONICAL_JS;
      var byKind = { window: windowAt, door: doorAt, porch: porchAt, garage_door: garageDoorAt };
      var roofKind = { gable: gableAt, dormer: dormerAt, hip_end: hipEndAt };
      spec.ground.forEach(function (f) { if (byKind[f.kind]) byKind[f.kind](f); });
      spec.roof.forEach(function (f) { if (roofKind[f.kind]) roofKind[f.kind](f); });
    }
```
Call it where the hand blocks used to run (after the south wall slab + `regFabric(southWallG…)` and after the garage IIFE has built its shell, before the `FABRIC.forEach(EXT_NO_MERGE)` line). Delete: the three `swWindow(...)` calls, the door block, the porch block, the second coach lamp block, `shellGable('porch_roof', …)`, the `[[9.10,1.55,true],[12.60,1.55,true]]` windows arg (→ `[]`), `shellGable('garage_gable', …)`, and the carriage-door detail block inside the garage IIFE. The south wall slab, its baseboard and its `regFabric` stay.

(d) **Markers.** `EXTERIOR_HINTS`'s garage row becomes `['garage_front', 'Garage', ['garage', 'errands'], 'front', ['errands']]` and `chfNavProbe` learns `spec.front` (a face name): pick the first `FABRIC` piece whose name starts with `'facade_' + spec.front + '_'` and whose `n[2] > 0.5`, else the piece named `garage_door`; then proceed as `spec.piece` does. `front_door` keeps working through `userData.entry`.

(e) **Exposure:** `window.chfFacade = function () { return webgl ? webgl.SPEC : null; }; window.chfFacadeSlots = function () { return webgl ? webgl.SLOTS : []; };` and export `SPEC`, `SLOTS` from `buildRoom()`.

- [ ] **Step 4: Run the live file** until the pin scenario, the registry scenario and the real-mouse scenario are green. If the mesh count differs from the pin, find the delta with INVARIANT_JS `rows` (the probe's per-group rows) — a builder emitting one extra/missing mesh vs the hand block is a bug in the builder, not a reason to move the pin.

- [ ] **Step 5: Probe the canonical budget**: `env -u HA_BASE_URL python tools/house_probe.py --views all --budget --quality high --day --out ../scratch/probe-t4`; every view's `inFrustum` within +2 of Task 1's table; record.

- [ ] **Step 6: Sweep, bump, commit, push** — `feat: the street elevation builds from the facade spec (vX.Y.Z)` with the budget table in the body.

---

### Task 5: `house_probe --facade`, the worst-case scenario, cap tuning

**Files:**
- Modify: `chauffeur/tools/house_probe.py` (`_seed`, argparse)
- Modify: `chauffeur/tests/test_house_live.py`
- Modify: `chauffeur/services/house_facade.py` (cap constants only, if tuning demands)

- [ ] **Step 1: Probe flag.** Add `ap.add_argument('--facade', default='', help='canonical | worst | <saved id>: seed the active facade before the page loads')` and, in `_seed` (or a wrapper when `--no-seed`), after the cars:
```python
    fac = os.environ.get('HOUSE_PROBE_FACADE', '')
    if fac == 'worst':
        from services import house_facade as hf
        rec = hf.save_facade('Probe worst case', hf.worst_case(), activate=True)
    elif fac and fac != 'canonical':
        from services import house_facade as hf
        hf.set_active(fac)
```
(set `os.environ['HOUSE_PROBE_FACADE'] = args.facade` in `main()` before `live_app(...)` — the seed callback runs inside `live_app`.)

- [ ] **Step 2: Worst-case live scenario (failing first: seeds nothing until the fixture exists)**

```python
def scenario_worst_case_facade_builds_clean():
    """Spec §8: the heaviest spec the caps allow builds with no console
    errors, registers every feature, and the generated front door still
    navigates."""
    from services import house_facade as hf
    served = live_app(lambda: (_seed(), hf.save_facade('worst', hf.worst_case(), activate=True)))
    if served is None:
        return
    with served.browser() as page:
        errors = []
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        page.add_init_script(DAY_LOCK_JS)
        page.goto(served.url('house?quality=high'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_timeout(2600)
        check(not errors, f'worst case builds clean: {errors[:3]}')
        spec = page.evaluate('window.chfFacade()')
        check(spec == hf.worst_case(), 'built from the worst case')
        fab = page.evaluate('window.chfShellFabric()')
        names = {f['name'] for f in fab}
        for g in spec['ground']:
            if g['kind'] in ('window', 'door', 'porch'):
                face = hf.slot_table()[g['slot']]['face']
                check(f"facade_{face}_{g['kind']}_{g['slot']}" in names, f'registered: {g}')
        for r in spec['roof']:
            face = hf.slot_table()[r['slot']]['face']
            check(any(n.startswith(f"facade_{face}_{r['kind']}_{r['slot']}") for n in names), f'registered: {r}')
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        p = page.evaluate("window.chfNavProbe({entry:'front_door'})")
        check(p is not None, 'the generated front door is tappable')
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_function("window.chfNavProbe({settled:true}) && window.chfHouseMode() === 'living'", timeout=20000)
```
`live_app` accepts one seed callable — the lambda above chains both; the fixture DB is the module's `CHAUFFEUR_DATA_DIR`, so **run this scenario in its own served app** (a fresh `live_app(...)` per scenario is the file's existing pattern).

- [ ] **Step 3: Run the worst-case budget**: `HOUSE_PROBE_FACADE=worst` via `--facade worst --views all --budget --quality high --day`. If exterior `inFrustum` > 1400 or `buildMs` > 1500, lower `MAX_DORMERS`/`MAX_WINDOWS`/`MAX_GABLES`/`MAX_PORCH_SLOTS` in that order, re-run `test_house_facade.py` (the worst-case scenario reads the constants), re-probe. Record the final caps and numbers.

- [ ] **Step 4: Sweep, bump, commit, push** — `test: worst-case facade budget and probe flag (vX.Y.Z)`, numbers + final caps in the body.

---

### Task 6: The vision call and the photo route

**Files:**
- Modify: `chauffeur/services/house_facade.py` (`from_photo`, `PHOTO_SYSTEM`)
- Modify: `chauffeur/main.py` (photo route, beside the facade routes)
- Test: `chauffeur/tests/test_house_facade.py`

**Interfaces:**
- Produces: `from_photo(image_b64: str, mime: str) -> (draft: dict|None, error: str|None)`; `POST /api/house/facades/photo` multipart `photo` → `{'draft': spec|None, 'notes': [...], 'error': str|None}`.

- [ ] **Step 1: Failing tests**

```python
def scenario_photo_becomes_a_draft_never_a_save():
    from services import storage, model_pools
    _fresh()
    storage.update_settings({'calendar_ids': [], 'llm_gemini_api_key': 'k'})
    seen = {}
    def fake_pool(tier, key, system, user, **kw):
        seen.update(tier=tier, images=kw.get('images'), strict=kw.get('strict_json'))
        return {'pitch_deg': 30, 'style': {'body': 'sage', 'roof': 'brown'},
                'ground': [{'slot': 9, 'span': 1, 'kind': 'door'},
                           {'slot': 7, 'span': 1, 'kind': 'window', 'size': 'tall'},
                           {'slot': 0, 'span': 3, 'kind': 'garage_door', 'style': 'panel', 'leaves': 2}],
                'roof': [{'slot': 8, 'span': 3, 'kind': 'gable'}]}
    model_pools.call_pool_json = fake_pool
    draft, err = hf.from_photo('AAAA', 'image/jpeg')
    check(err is None and draft['style']['body'] == 'sage' and draft['pitch_deg'] == 30.0, f'draft: {draft} {err}')
    check(seen['tier'] == 'vision' and seen['images'][0]['b64'] == 'AAAA' and seen['strict'], 'vision tier, inline image, strict JSON')
    check(len(hf.list_facades()) == 1 and hf.active_bundle()['id'] == 'canonical', 'nothing saved, nothing activated')


def scenario_photo_failures_are_answers():
    from services import storage, model_pools
    _fresh()
    check(hf.from_photo('AAAA', 'image/jpeg') == (None, 'no LLM API key configured'), 'no key')
    storage.update_settings({'calendar_ids': [], 'llm_gemini_api_key': 'k'})
    model_pools.call_pool_json = lambda *a, **k: {'error': '429 Too Many Requests'}
    d, e = hf.from_photo('AAAA', 'image/jpeg')
    check(d is None and '429' in e, 'pool error surfaces')
    def boom(*a, **k): raise RuntimeError('socket')
    model_pools.call_pool_json = boom
    d, e = hf.from_photo('AAAA', 'image/jpeg')
    check(d is None and 'socket' in e, 'transport error surfaces')
    model_pools.call_pool_json = lambda *a, **k: 'not a dict'
    d, e = hf.from_photo('AAAA', 'image/jpeg')
    check(d is None and e, 'bad shape surfaces')
```
Check `model_pools.call_pool_json` accepts `strict_json` — it does NOT today (its signature ends at `workflow`). Add a pass-through `strict_json: bool = False` in `model_pools.call_pool_json` forwarded to `_llm._call_llm_json(..., strict_json=strict_json)`; pin it in the test above (`seen['strict']`).

- [ ] **Step 2: Run → fails** (`from_photo` missing).

- [ ] **Step 3: Implement**

```python
PHOTO_SYSTEM = """You describe the STREET-FACING elevation of a house from one photo, as JSON only.
The house is drawn on a fixed strip of {n} slots, west to east (left to right as seen from the street):
{faces}
Slot numbers are global (0..{last}). Report only what is on the street face.
Return exactly this shape:
{{"pitch_deg": number between 22.5 and 35, "style": {{"cladding": "batten"|"clapboard", "body": one of {body}, "roof": one of {roof}, "frame": one of {frame}, "door": one of {door}, "trim": one of {trim}}},
  "ground": [{{"slot": int, "span": int, "kind": "window", "size": "tall"|"standard"|"small"}} | {{"slot","span","kind":"door"}} | {{"slot","span","kind":"garage_door","style":"carriage"|"panel"|"glass","leaves":1|2}} | {{"slot","span","kind":"porch","type":"sitting"|"stoop"|"covered"}}],
  "roof": [{{"slot": int, "span": int, "kind": "gable"|"dormer"|"hip_end", "window": bool}}]}}
Rules: colours are the NEAREST palette name, never hex. If the garage is not visible, omit it. If unsure of a count, prefer fewer windows. The front door goes on the main face. No prose."""


def _photo_prompt():
    faces = '\n'.join(f"- {f['face']}: slots {_face_range(f['face'])[0]}..{_face_range(f['face'])[1]}"
                      for f in FACES)
    n = len(slot_table())
    return PHOTO_SYSTEM.format(n=n, last=n - 1, faces=faces,
                               body=list(STYLE['body']), roof=list(STYLE['roof']),
                               frame=list(STYLE['frame']), door=list(STYLE['door']),
                               trim=list(STYLE['trim']))


def from_photo(image_b64, mime):
    """One photo -> a DRAFT facade (normalized) or an error. Never stores."""
    from services import model_pools
    settings = _settings()
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key:
        return None, 'no LLM API key configured'
    try:
        res = model_pools.call_pool_json(
            'vision', api_key, _photo_prompt(),
            'Describe the street-facing elevation of the house in the attached photo.',
            temperature=0.1, timeout_s=90, settings=settings, strict_json=True,
            images=[{'mime': mime or 'image/jpeg', 'b64': image_b64}])
    except Exception as e:
        return None, f'could not read the photo ({e})'
    if not isinstance(res, dict):
        return None, 'could not read the photo (bad response)'
    if res.get('error'):
        return None, f"could not read the photo ({res['error']})"
    spec, _ = normalize(res)
    return spec, None
```

Route (beside the facade routes; `_PHOTO_MAX_BYTES` already exists in main.py):
```python
@app.post("/api/house/facades/photo")
async def house_facade_photo(photo: UploadFile = File(...)):
    """Photo -> DRAFT facade. Returned, never stored: the parent reviews it
    in the editor and saves on purpose (spec 2026-09-15 §5). The bytes live
    in this request only."""
    import base64
    from services import house_facade as _hf
    data = await photo.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload")
    if len(data) > _PHOTO_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (8MB max)")
    mime = (photo.content_type or '').lower()
    if not mime.startswith('image/'):
        raise HTTPException(status_code=400, detail="Only images are supported")
    draft, err = _hf.from_photo(base64.b64encode(data).decode('ascii'), mime)
    notes = _hf.normalize(draft)[1] if draft else []
    return {'draft': draft, 'notes': notes, 'error': err}
```
Declare it before the `/{fid}` routes.

- [ ] **Step 4: Run `test_house_facade.py`, `test_model_pools*.py`, `test_shopping*.py`** → ok.

- [ ] **Step 5: Sweep, bump, commit, push** — `feat: one vision call turns a street photo into a facade draft (vX.Y.Z)`.

---

### Task 7: config.html Home section (the hand path)

**Files:**
- Modify: `chauffeur/templates/config.html` — markup after the Cars panel (~2038–2354, family tab), Alpine state/methods in `configApp()` beside `loadCars` (~5268)
- Modify: `chauffeur/static/tailwind.css` (rebuilt)
- Test: `chauffeur/tests/test_settings_registry.py` (audit passes), a new `scenario_home_section_pins` in `chauffeur/tests/test_house_facade.py`

- [ ] **Step 1: Failing template pin**

```python
def scenario_home_section_pins():
    import io, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tpl = io.open(os.path.join(root, 'templates', 'config.html'), encoding='utf-8').read()
    check('id="home"' in tpl and 'house_facades' in tpl and 'house_facade_active' in tpl, 'the Home section exists')
    for needle in ('facadePhoto(', 'facadeSaveNew(', 'facadeOverwrite(', 'facadeActivate(', 'facadeDelete(', 'facadeRename(', 'facadePreview('):
        check(needle in tpl, f'hand path method {needle}')
    check('From your photo' in tpl, 'the draft banner names its source')
    for bad in ('alert(', 'confirm(', 'prompt('):
        sec = tpl[tpl.index('id="home"'):tpl.index('id="home"') + 20000]
        check(bad not in sec.replace('promptConfirm(', '').replace('promptInput(', ''), f'no browser dialogs: {bad}')
```

- [ ] **Step 2: Run → fails.**

- [ ] **Step 3: Markup** (replace the Task 3 placeholder `<div id="home"></div>`):

```html
                <!-- The Home (People tab sub-panel, beside Cars): the street facade -->
                <div x-show="activeTab === 'family'" x-cloak x-transition.opacity id="home"
                    class="bg-gray-800 p-8 rounded-2xl mb-10 shadow-2xl border border-gray-700">
                    <h2 class="text-3xl font-bold mb-2 text-teal-300">Home</h2>
                    <p class="text-gray-400 text-sm mb-4">The street face of the dollhouse at <a href="house" target="_blank" class="underline">/house</a>.
                        Match it to a photo of your real house, or draw it slot by slot. Nothing changes until you save;
                        the wall builds from the <b>active</b> facade on its next load.
                        <span class="hidden">house_facades house_facade_active</span></p>

                    <div class="grid md:grid-cols-3 gap-4">
                        <div class="space-y-2">
                            <template x-for="f in facades" :key="f.id">
                                <div class="bg-gray-900 p-3 rounded-xl flex items-center gap-2"
                                     :class="facadeDraftId === f.id ? 'ring-2 ring-teal-500' : ''">
                                    <input type="radio" name="facade_active" :checked="facadeActive === f.id" @change="facadeActivate(f.id)">
                                    <button class="flex-1 text-left" @click="facadeLoad(f)" x-text="f.name"></button>
                                    <template x-if="!f.readonly">
                                        <div class="flex gap-1">
                                            <button class="text-xs text-gray-400 hover:text-white" @click="facadeRename(f)">Rename</button>
                                            <button class="text-xs text-red-400 hover:text-red-200" @click="facadeDelete(f)">Delete</button>
                                        </div>
                                    </template>
                                </div>
                            </template>
                            <label class="block bg-gray-900 p-3 rounded-xl cursor-pointer text-center text-teal-300 hover:bg-gray-700">
                                Match a photo…
                                <input type="file" accept="image/*" class="hidden" @change="facadePhoto($event)">
                            </label>
                        </div>

                        <div class="md:col-span-2 space-y-3">
                            <div x-show="facadeDraftSource === 'photo'" class="bg-amber-900/40 border border-amber-600 rounded-lg p-2 text-amber-200 text-sm">
                                From your photo — not saved yet. Review, then Save as new or Overwrite.
                            </div>
                            <div class="flex flex-wrap gap-1" id="facade-strip">
                                <template x-for="face in facadeFaces" :key="face.face">
                                    <div class="flex flex-col">
                                        <span class="text-xs text-gray-500 uppercase" x-text="face.face"></span>
                                        <div class="flex gap-0.5">
                                            <template x-for="s in face.slots" :key="s.i">
                                                <button class="w-9 h-14 rounded text-[10px] leading-tight border"
                                                        :class="facadeCellClass(s.i)" @click="facadeSlot = s.i"
                                                        x-text="facadeCellText(s.i)"></button>
                                            </template>
                                        </div>
                                    </div>
                                </template>
                            </div>
                            <div x-show="facadeSlot !== null" class="bg-gray-900 p-3 rounded-xl grid grid-cols-2 gap-2 text-sm">
                                <label>Ground
                                    <select class="w-full bg-gray-800" x-model="facadeCell.ground.kind" @change="facadeCellApply()">
                                        <option value="wall">wall</option><option value="window">window</option><option value="door">door</option>
                                        <option value="garage_door">garage door</option><option value="porch">porch</option>
                                    </select></label>
                                <label>Roof
                                    <select class="w-full bg-gray-800" x-model="facadeCell.roof.kind" @change="facadeCellApply()">
                                        <option value="eave">eave</option><option value="gable">gable</option><option value="dormer">dormer</option><option value="hip_end">hip end</option>
                                    </select></label>
                                <label x-show="facadeCell.ground.kind === 'window'">Size
                                    <select class="w-full bg-gray-800" x-model="facadeCell.ground.size" @change="facadeCellApply()">
                                        <option>tall</option><option>standard</option><option>small</option></select></label>
                                <label x-show="facadeCell.ground.kind === 'porch'">Porch
                                    <select class="w-full bg-gray-800" x-model="facadeCell.ground.type" @change="facadeCellApply()">
                                        <option>sitting</option><option>stoop</option><option>covered</option></select></label>
                                <label x-show="facadeCell.ground.kind === 'garage_door'">Door
                                    <select class="w-full bg-gray-800" x-model="facadeCell.ground.style" @change="facadeCellApply()">
                                        <option>carriage</option><option>panel</option><option>glass</option></select></label>
                                <label x-show="facadeCell.ground.kind === 'garage_door'">Leaves
                                    <select class="w-full bg-gray-800" x-model.number="facadeCell.ground.leaves" @change="facadeCellApply()">
                                        <option value="1">1</option><option value="2">2</option></select></label>
                                <label x-show="facadeCell.roof.kind === 'dormer'"><input type="checkbox" x-model="facadeCell.roof.window" @change="facadeCellApply()"> dormer window</label>
                                <label>Ground span <input type="number" min="1" class="w-16 bg-gray-800" x-model.number="facadeCell.ground.span" @change="facadeCellApply()"></label>
                                <label>Roof span <input type="number" min="1" class="w-16 bg-gray-800" x-model.number="facadeCell.roof.span" @change="facadeCellApply()"></label>
                            </div>
                            <div class="grid grid-cols-3 gap-2 text-sm">
                                <label>Pitch <input type="range" min="22.5" max="35" step="0.5" class="w-full" x-model.number="facadeDraft.pitch_deg" @change="facadePreview()"> <span x-text="facadeDraft.pitch_deg + '°'"></span></label>
                                <template x-for="role in ['cladding','body','roof','frame','door','trim']" :key="role">
                                    <label><span x-text="role"></span>
                                        <select class="w-full bg-gray-800" x-model="facadeDraft.style[role]" @change="facadePreview()">
                                            <template x-for="opt in facadeStyleOptions[role]" :key="opt"><option :value="opt" x-text="opt"></option></template>
                                        </select></label>
                                </template>
                            </div>
                            <ul class="text-xs text-amber-300" x-show="facadeNotes.length">
                                <template x-for="n in facadeNotes" :key="n"><li x-text="n"></li></template>
                            </ul>
                            <div class="flex gap-2">
                                <button class="px-3 py-1 rounded bg-teal-600" @click="facadeSaveNew()">Save as new</button>
                                <button class="px-3 py-1 rounded bg-gray-600" :disabled="!facadeDraftId || facadeDraftId === 'canonical'" @click="facadeOverwrite()">Overwrite</button>
                                <button class="px-3 py-1 rounded bg-gray-700" @click="facadeLoad(facades[0])">Reset to canonical</button>
                            </div>
                        </div>
                    </div>
                </div>
```

Alpine, in `configApp()` state: `facades: [], facadeActive: 'canonical', facadeSlots: [], facadeFaces: [], facadeDraft: null, facadeDraftId: null, facadeDraftSource: 'hand', facadeSlot: null, facadeCell: {ground:{kind:'wall',span:1}, roof:{kind:'eave',span:1}}, facadeNotes: [], facadeStyleOptions: {cladding:['batten','clapboard'], body:['white','greige','sage','slate','navy'], roof:['charcoal','weathered','brown'], frame:['black','white'], door:['wood','black','red','sage'], trim:['white','black']}`. Methods:

```js
                async loadFacades() {
                    const res = await fetch(`${this.apiBase}api/house/facades`);
                    const data = await res.json();
                    this.facades = data.facades; this.facadeActive = data.active; this.facadeSlots = data.slots;
                    const faces = [];
                    data.slots.forEach(s => { let f = faces.find(x => x.face === s.face); if (!f) { f = { face: s.face, slots: [] }; faces.push(f); } f.slots.push(s); });
                    this.facadeFaces = faces;
                    if (!this.facadeDraft) this.facadeLoad(this.facades.find(f => f.id === this.facadeActive) || this.facades[0]);
                },
                facadeLoad(f) { this.facadeDraft = JSON.parse(JSON.stringify(f.spec)); this.facadeDraftId = f.id; this.facadeDraftSource = 'hand'; this.facadeNotes = []; this.facadeSlot = null; },
                facadeEntry(layer, i) { return (this.facadeDraft[layer] || []).find(e => i >= e.slot && i < e.slot + e.span); },
                facadeCellText(i) { const g = this.facadeEntry('ground', i), r = this.facadeEntry('roof', i); return (g ? g.kind.replace('_', ' ') : '') + '\n' + (r ? r.kind : ''); },
                facadeCellClass(i) { return (this.facadeSlot === i ? 'border-teal-400 ' : 'border-gray-700 ') + (this.facadeEntry('ground', i) ? 'bg-gray-700' : 'bg-gray-900'); },
                facadeCellApply() {
                    const i = this.facadeSlot; if (i === null) return;
                    ['ground', 'roof'].forEach(layer => {
                        const cell = this.facadeCell[layer];
                        this.facadeDraft[layer] = (this.facadeDraft[layer] || []).filter(e => !(i >= e.slot && i < e.slot + e.span));
                        if (cell.kind !== 'wall' && cell.kind !== 'eave') this.facadeDraft[layer].push({ ...cell, slot: i, span: Math.max(1, cell.span || 1) });
                    });
                    this.facadePreview();
                },
                async facadePreview() {
                    const res = await fetch(`${this.apiBase}api/house/facades/preview`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ spec: this.facadeDraft }) });
                    const data = await res.json(); this.facadeDraft = data.spec; this.facadeNotes = data.notes;
                },
                async facadePhoto(ev) {
                    const file = ev.target.files && ev.target.files[0]; if (!file) return;
                    const fd = new FormData(); fd.append('photo', file);
                    const res = await fetch(`${this.apiBase}api/house/facades/photo`, { method: 'POST', body: fd });
                    const data = await res.json(); ev.target.value = '';
                    if (!data.draft) { showGlobalAlert(data.error || 'Could not read the photo'); return; }
                    this.facadeDraft = data.draft; this.facadeNotes = data.notes || []; this.facadeDraftSource = 'photo'; this.facadeSlot = null;
                },
                async facadeSaveNew() {
                    const name = await promptInput('Name this facade', 'My house'); if (!name) return;
                    await fetch(`${this.apiBase}api/house/facades`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, spec: this.facadeDraft, source: this.facadeDraftSource }) });
                    this.facadeDraft = null; await this.loadFacades();
                },
                async facadeOverwrite() {
                    if (!this.facadeDraftId || this.facadeDraftId === 'canonical') return;
                    await fetch(`${this.apiBase}api/house/facades/${this.facadeDraftId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ spec: this.facadeDraft }) });
                    this.facadeDraftSource = 'hand'; await this.loadFacades();
                },
                async facadeActivate(id) { await fetch(`${this.apiBase}api/house/facades/active`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id }) }); this.facadeActive = id; },
                async facadeRename(f) { const name = await promptInput('Rename facade', f.name); if (!name) return; await fetch(`${this.apiBase}api/house/facades/${f.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) }); await this.loadFacades(); },
                async facadeDelete(f) { if (!(await promptConfirm(`Delete "${f.name}"?`))) return; await fetch(`${this.apiBase}api/house/facades/${f.id}`, { method: 'DELETE' }); if (this.facadeDraftId === f.id) this.facadeDraft = null; await this.loadFacades(); },
```
Selecting a slot fills `facadeCell` — add a watcher: `this.$watch('facadeSlot', i => { if (i === null) return; const g = this.facadeEntry('ground', i), r = this.facadeEntry('roof', i); this.facadeCell = { ground: g ? { ...g } : { kind: 'wall', span: 1 }, roof: r ? { ...r } : { kind: 'eave', span: 1 } }; });` in `init()`, and call `this.loadFacades()` from `init()` beside `loadCars()`. Verify `promptInput`/`promptConfirm`/`showGlobalAlert` are in scope on the config page (they come from `control_center.html`; grep the include).

- [ ] **Step 4: `cd chauffeur && python tools/build_tailwind.py`**; run `test_house_facade.py`, `test_settings_registry.py`, `test_tailwind_build.py` → ok. Open `/config` in the served app (or `tools/house_probe.py`-style Playwright) and screenshot the Home section for the commit (UI design guide rule: screenshot proof).

- [ ] **Step 5: Sweep, bump, commit, push** — `feat: Home section on the config page: saved facades, photo draft, slot editor (vX.Y.Z)`.

---

### Task 8: Wrap — docs, results, memory

**Files:**
- Modify: `chauffeur/system_capabilities.md` (a new entry after the v2.499.x house entries)
- Modify: `docs/house_style_bible.md` (the palette table now lives in `PALETTE`)
- Modify: `docs/superpowers/specs/2026-09-15-house-facade-generator-design.md` §10 Results
- Memory: `house-arc.md` (arc 4 SHIPPED, versions, NOT device-verified)

- [ ] **Step 1: system_capabilities.md** — one prose entry in the file's voice: what a facade is, the slot strip and its faces, the two layers and the only limits (faces, garage bay, budget caps, ≥1 door), review-before-save with several saved facades, canonical read-only, the photo path (one vision call, strict JSON, never stored), the hand path on Config → Home, build-once via `window.HOUSE_FACADE`, AO occluders from the registry, the `{exit:true}` probe, the pinned canonical mesh count, and the budget numbers. Mark NOT device-verified.
- [ ] **Step 2: Spec §10** — the tables from Tasks 1, 4, 5; final caps; the canonical mesh pin; deviations.
- [ ] **Step 3: Style bible** — note `PALETTE` roles and the rule that new exterior colours are palette rows, never literals.
- [ ] **Step 4: Bump, commit (docs-only, no sweep), push** — `docs: facade generator wrap (vX.Y.Z)`; then update the `house-arc` memory file.

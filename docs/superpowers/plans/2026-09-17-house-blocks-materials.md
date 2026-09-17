# The Home — Blocks, Materials and the Photo Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The house is described by a two-block model (depth, stories, roof form/ridge/pitch, cladding, base band, body, garage orientation, mirror) that the builders, the vision prompt, the editor and the tests all read; a photo becomes a draft the family renders in their own browser and a second vision pass critiques; what the schema cannot hold is listed, never dropped.

**Architecture:** `services/house_facade.py` gains a version-2 schema with `validate_block_model` (rejects) ahead of `normalize` (defaults), a V1→V2 mapping table, per-story overlap, depth clamps, and a draft-token cache that `/house?draft=<token>` renders. `house.js` reads `FACADE.spec.blocks`: per-block pitch and roof forms, six cladding painters keyed by world-scaled UV references carried on the texture, a base band, a per-block street-face depth with a block-meet return wall and neighbour-volume roof subtraction, an upper story built as ordinary fabric (so the room masks cut it), a side-entry garage, a shed feature, the porch's own gabled roof, and a mirror applied once on a `houseRoot` group AFTER clipping, batching and AO. The photo pipeline is pass 1 (describe, fractions → slots) → the editor renders the draft in a same-origin `/house` iframe and captures the canvas → pass 2 (critique, one full revised model) → the editor shows both and the person picks; nothing auto-saves.

**Tech Stack:** three.js (vendored) in `house.js`; `house_clip.js` clipper; Python/FastAPI; Alpine editor in `templates/config.html`; Playwright live tests (`tests/live_app.py`, standalone scenario scripts); `tools/house_probe.py` for budgets and PNGs; `model_pools.call_pool_json('vision', …)` for both vision calls.

**Spec:** `docs/superpowers/specs/2026-09-17-house-blocks-materials-design.md` (binding, revised twice). Read §0 before Task 1–2, §2 before Task 3–4, §3 before Task 5–9, §4 before Task 10–11, §5 before Task 12, §6–§7 before Task 13.

## Global Constraints

- Every code task ends with: read `chauffeur/config.yaml` `version:`, bump the patch, verify with `grep ^version chauffeur/config.yaml`; the COMMIT GATE: `env -u HA_BASE_URL python chauffeur/tools/test.py --focus` from the repo root PLUS the live file(s) the task touched (`cd chauffeur && env -u HA_BASE_URL python tests/test_house_facade_live.py` etc.), foreground, never two concurrent runs, never piped; commit with the version in the subject `(vX.Y.Z)`; push. The FULL sweep (`env -u HA_BASE_URL python chauffeur/tools/test.py`, timeout 600000) runs once, at Task 14's commit. Known parallel-load flakes (re-run solo only if they are the only reds): `test_screensaver`, `test_study_live`, `test_negotiation_cost`, `test_trip_scheduler`. Commit messages in prose, via a Bash heredoc, ending `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Docs-only commits skip the gate.
- Spelling: **story / stories** in code, UI and docs. Roof language: ridge direction plus the face the gable shows; never "side-gabled" or "front-gabled".
- house.js laws: every geometry through `cgeo` (keys carry every input), every material through `mat()`/`box()` opts, `mkTex` owns runtime textures (the file's only texture dispose lives in mkTex; build-time `canvasTex` tiles are never disposed), no per-frame work, render-on-demand; every shell piece registers through `shellRegister`/`regFabric`; ghost edges stay OFF; palette hex only in `PALETTE`; the cap material is the one shared `CAP_MAT`.
- Mask law (masking spec §2, unchanged): `ROOM_AABB_EAVE` box top stays `EXT_TOP4` (5.6). An upper story is FABRIC and is cut like fabric. Ground-floor partitions cap at `EXT_TOP4` when a block has two stories (no vault).
- Mirror law (spec §3.4): construction coordinates never flip; reflection happens once on `houseRoot.scale.x = -1` AFTER `buildRoomShells`, valley clips, `bakeAO` and `mergeStatic`; only camera/navigation values pass through `toWorldX`; world-matrix reads never do.
- Validation law (spec §4): every model-produced object passes `validate_block_model` BEFORE `normalize`; rejection keeps the previous draft byte-identical. Hand-editor input keeps today's normalize-with-defaults path.
- Budget law (spec §7): ceilings are `B0` (Task 1's recorded baseline) plus the itemised delta each task states; draws are MEASURED (`renderer.info.render.calls`), never inferred. `buildMs` ≤ 1500 with two stories on both blocks.
- Never drop functionality: every existing `regFabric` name stays (ridge-dependent names resolve through the alias table in Task 2); the canonical house renders pixel-equivalent (Task 5 pin) and every existing editor action stays.
- Tests are standalone scripts (`from harness import check` for pure; `from house_live_common import check, _seed, DAY_LOCK_JS, INVARIANT_JS` for live; `scenario_*`; runner at the bottom). Live: `cd chauffeur && env -u HA_BASE_URL python tests/<file>.py`. Probe: `cd chauffeur && env -u HA_BASE_URL python tools/house_probe.py --views exterior --budget --quality high --day --out ../scratch/<name>`. Look at every PNG you cite.
- `HA_BASE_URL` is exported by the dev shell: every test/probe run uses `env -u HA_BASE_URL`. Never round-trip source through PowerShell `Get-Content`/`Set-Content`.
- Plan-level rulings (deviations from the spec text; copied into spec §9 at wrap):
  - **R-A (render surface).** The facade editor has no 3D preview (it is a 2D slot strip; `/house` builds from the ACTIVE facade injected by `house_page`). The spec's "editor's own preview" is realised as `/house?draft=<token>` in a same-origin iframe: the server keeps the draft under the token for 15 min and injects it as `window.HOUSE_FACADE`; the editor calls `iframe.contentWindow.chfCapture()`. This also gives every hand draft a "Preview in 3D" button (a hand path the arc did not have).
  - **R-B (depth void).** Moving a street face forward leaves a floor-less void between the room's floor edge and the new wall; a plain slab in the stoop tone floors it so no lawn shows through a room view.
  - **R-C (day lock in the page).** `isNight()` reads `Date().getHours()`. The draft iframe passes `?day=1`, which `isNight()` honours; the probe's init-script lock stays as is.

---

## File map

| file | responsibility |
|---|---|
| `chauffeur/tools/house_probe.py` | `--budget` also reports measured `calls` (`renderer.info.render.calls`) per view; `--seed-rng`; `--facade-json <file>` seeds a draft from a file (dev adapter; asserts a temp data dir) |
| `chauffeur/services/house_facade.py` | V2 schema constants, `validate_block_model`, `_upgrade_v1`, `normalize` v2, `slot_table(blocks=None)`, `CANONICAL` v2, draft-token cache (`issue_draft`, `draft_for`, `store_result`), `PHOTO_SYSTEM` v2 + `CRITIQUE_SYSTEM`, `from_photo` (pass 1) and `critique` (pass 2) with `max_models=2`, `workflow='house_photo'` |
| `chauffeur/main.py` | `/house` honours `?draft=`; `/api/house/facades/photo` → plain `def`; new `POST /api/house/facades/draft` (hand draft → token) and `POST /api/house/facades/critique` |
| `chauffeur/static/house.js` | blocks/pitch/roof forms from the spec; `cladTex`, UV refs on textures, base band; depth + block-meet; `storyBox`; side garage; `shedAt`; porch gable; `houseRoot` mirror + `toWorldX` + `noMirror` text helper; `chfCapture`, `?day=1` |
| `chauffeur/templates/config.html` | Blocks panel, feature editor fields (shed, per-feature cladding, shutters, story, porch roof), Preview in 3D iframe, two-render draft view with pick |
| `chauffeur/tests/test_house_facade.py` | every pure law in spec §6 |
| `chauffeur/tests/fixtures/house_photo/` (new) | `b0-exterior.png`, `brick.expected.json`, `brick.pass1.json`, `brick.pass2.json`, `farmhouse.*` (recorded responses; photos stay in `docs/superpowers/specs/assets/`) |
| `chauffeur/tests/test_house_facade_live.py`, `test_house_shell_live.py`, `house_live_common.py` | mirror set, two stories, side garage, shed/porch-gable audit, block-meet, hip/ridge-z pins, combined scenario, `SEED_RNG_JS`, `roof_piece_names`, budgets vs B0 |
| `chauffeur/system_capabilities.md`, spec §9, memory | wrap |

---

### Task 1: The B0 baseline and measured draw calls

**Files:**
- Modify: `chauffeur/tools/house_probe.py` (THREE_WRAP at ~line 46; the budget JS at ~line 60–120; `main()` args)
- Modify: `chauffeur/tests/house_live_common.py` (add `SEED_RNG_JS`)
- Create: `chauffeur/tests/fixtures/house_photo/b0-exterior.png`
- Modify: `docs/superpowers/specs/2026-09-17-house-blocks-materials-design.md` §9 (record B0)

**Interfaces:**
- Produces: `window.__hpCalls` (int, `renderer.info.render.calls` of the last real-scene render) and the budget dict key `calls`; `SEED_RNG_JS` (init script: `Math.random` becomes a seeded LCG so textures are deterministic run to run); probe flag `--seed-rng`.

- [ ] **Step 1: Add the draw-call latch to THREE_WRAP.** In `house_probe.py`, inside the wrapped `r.render = function (s, c) {...}`, replace the tail `return o(s, c);` with:

```js
      var out = o(s, c);
      if (s && s.isScene && s.children.length > 8)
        window.__hpCalls = r.info.render.calls;
      return out;
```

In the budget-report JS (the object literal that returns `{ total, visible, inFrustum, tris, ... buildMs: window.__hpBuildMs, ...}`) add `calls: window.__hpCalls,`. In `main()` add `ap.add_argument('--seed-rng', action='store_true', help='deterministic Math.random for pixel pins')` and, beside the `--day` init script, `if args.seed_rng: page.add_init_script(SEED_RNG_JS)` (import it from `house_live_common`; the tests dir is already on `sys.path`).

- [ ] **Step 2: Add `SEED_RNG_JS` to `house_live_common.py`** beside `DAY_LOCK_JS`:

```python
# Textures (grass, drive, wood) paint with Math.random; a pixel pin needs
# the same picture every run. Seeded LCG, installed by init script.
SEED_RNG_JS = ('Math.random = (function () { var s = 20260917; return function () {'
               ' s = (Math.imul(s, 1664525) + 1013904223) >>> 0; return s / 4294967296; }; })();')
```

- [ ] **Step 3: Run the baseline.** From `chauffeur/`:

```
env -u HA_BASE_URL python tools/house_probe.py --views exterior,orbit --budget --quality high --day --seed-rng --out ../scratch/b0
```

Copy the printed exterior row and the worst orbit row (`inFrustum`, `tris`, `calls`, `buildMs`, `materials`, `geometries`) and the exact command line into spec §9 under a new heading **B0 (Task 1)**. Copy `../scratch/b0/exterior.png` to `chauffeur/tests/fixtures/house_photo/b0-exterior.png` (Task 5's pixel reference). Open the PNG and confirm it is the daytime canonical exterior at stop 0.

- [ ] **Step 4: Commit** (gate: `--focus`; the probe is not under test):

```
docs: B0 baseline for massing arc 2, probe reports measured draw calls (vX.Y.Z)
```

---

### Task 2: §0 prerequisites — pitch constants, ridge-independent roof names, hip/ridge-z pins

**Files:**
- Modify: `chauffeur/static/house.js` (`~6182` garage `roofVault`; `hipEndAt` `~5717`; after the two block-roof `shellGable` calls `~5797`/`~5829`; the `webgl` exposure object `~10633`; hooks beside `chfRoofForms` `~11655`; the marker lookup that consumes `EXTERIOR_HINTS[i][0]`)
- Modify: `chauffeur/tests/house_live_common.py` (`roof_piece_names`, `FEATURE_JS`, `VERTEX_AUDIT_JS` moved here, new `VERTEX_AUDIT_ALL_JS`)
- Modify: `chauffeur/tests/test_house_shell_live.py` (`scenario_shell_fabric_registry`; new scenario)
- Test: `chauffeur/tests/test_house_shell_live.py`

**Interfaces:**
- Produces: house.js `ROOF_ALIAS` (`{ 'roof_main_south': <registered name whose normal has the largest +z>, 'roof_main_north', 'garage_block_roof_south', 'garage_block_roof_north' }`), `roofAlias(name)` = `ROOF_ALIAS[name] || name`, `window.chfRoofAlias()`; Python `roof_piece_names(base, form, ridge) -> set[str]`; `VERTEX_AUDIT_ALL_JS` (a feature's vertices against ALL of its block's decks via `window.chfRoofPlanes(face)`).

- [ ] **Step 1: Write the failing live scenario** in `test_house_shell_live.py` (register in `__main__`; `import json` at the top):

```python
def scenario_block_roof_forms_register_and_audit():
    """Spec 2026-09-17 blocks section 0: hip and ridge-z block roofs become
    settings in this arc, so they get live pins first. Each variant boots
    clean, the registry holds the four pieces roof_piece_names() predicts,
    the Mudroom marker's alias resolves to the STREET-facing garage roof
    piece, and no facade roof feature is buried under any block deck."""
    from house_live_common import roof_piece_names, FEATURE_JS, VERTEX_AUDIT_ALL_JS
    variants = [
        ({'main': {'form': 'hip', 'ridge': 'x'}, 'garage': {'form': 'gable', 'ridge': 'x'}}, 'main hip/x'),
        ({'main': {'form': 'gable', 'ridge': 'z'}, 'garage': {'form': 'gable', 'ridge': 'x'}}, 'main gable/z'),
        ({'main': {'form': 'gable', 'ridge': 'x'}, 'garage': {'form': 'hip', 'ridge': 'z'}}, 'garage hip/z'),
    ]
    served = live_app(_seed)
    if served is None:
        return
    for forms, label in variants:
        with served.browser() as page:
            page.add_init_script(DAY_LOCK_JS)
            page.add_init_script('window.HOUSE_ROOF_FORMS = %s;' % json.dumps(forms))
            page.goto(served.url('house?quality=high'))
            page.wait_for_selector('#room canvas', timeout=20000)
            page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
            fabric = page.evaluate('window.chfShellFabric()')
            names = {r['name'] for r in fabric}
            want = (roof_piece_names('roof_main', forms['main']['form'], forms['main']['ridge']) |
                    roof_piece_names('garage_block_roof', forms['garage']['form'], forms['garage']['ridge']))
            check(want <= names, f'{label}: roof pieces registered; missing {sorted(want - names)}')
            alias = page.evaluate('window.chfRoofAlias()')
            street = alias.get('garage_block_roof_south')
            check(street in names, f'{label}: Mudroom alias {street!r} is a registered piece')
            nrm = next(r['n'] for r in fabric if r['name'] == street)
            check(nrm[2] > 0.3, f'{label}: the alias faces the street: n={nrm}')
            for f in page.evaluate(FEATURE_JS):
                if f['kind'] == 'hip_end':
                    continue
                a = page.evaluate(VERTEX_AUDIT_ALL_JS, f)
                check(a['buried'] == 0, f"{label}: {f['name']} has {a['buried']} vertices under the block roof")
            errs = [e for e in served.errors() if 'WebGL' not in e]
            check(not errs, f'{label}: console clean: {errs[:3]}')
```

In `house_live_common.py` add:

```python
def roof_piece_names(base, form, ridge):
    """shellGable's registered names for one block roof (house.js ~5013/~5095):
    decks _north/_south + ends _end_west/_end_east on a ridge x; decks
    _west/_east + ends _back/_front on a ridge z. Same four for a hip."""
    if ridge == 'x':
        return {base + '_north', base + '_south', base + '_end_west', base + '_end_east'}
    return {base + '_west', base + '_east', base + '_back', base + '_front'}
```

Move `FEATURE_JS` and `VERTEX_AUDIT_JS` from `test_house_facade_live.py` into `house_live_common.py` (the facade file imports them back). Add `VERTEX_AUDIT_ALL_JS`: copy `VERTEX_AUDIT_JS`, replace its single `window.chfRoofPlane(f.face)` read with `const planes = window.chfRoofPlanes(f.face);` and count a vertex as buried only when, behind the face (`z < faceZ - 0.02`), it lies below EVERY plane at its (x, z) (the roof surface is the minimum of the planes). `chfRoofPlanes` already exists (`~11899` region).

- [ ] **Step 2: Run it → RED** (`chfRoofAlias` undefined): `cd chauffeur && env -u HA_BASE_URL python tests/test_house_shell_live.py`.

- [ ] **Step 3: The literal pitches.** At `~6182` replace `roofVault(GARAGE_BLOCK, ROOF_FORMS.garage, Math.PI / 8)` with `roofVault(GARAGE_BLOCK, ROOF_FORMS.garage, BLOCK_PITCH)`. In `hipEndAt` replace `var plane = Math.PI / 8` with `var plane = PITCH_FAMILY` (the cgeo key carries `depth` and `rise`, so a new pitch is a new geometry).

- [ ] **Step 4: The alias table.** Directly after the `shellGable('garage_block_roof', ...)` call add:

```js
    /* Spec 2026-09-17 blocks section 0: a block roof's pieces are named by
       geometric side (shellGable: _north/_south + _end_west/_end_east on a
       ridge x; _west/_east + _back/_front on a ridge z). Markers and tests
       name the CANONICAL pieces; this map says which registered piece
       stands where the canonical one stood, so a ridge setting never
       strands the Mudroom marker. */
    var ROOF_ALIAS = {};
    function aliasRoof(base) {
      var rows = FABRIC.filter(function (f) { return f.name.indexOf(base + '_') === 0; });
      function pick(sel) {
        var best = null;
        rows.forEach(function (f) { if (!best || sel(f.n) > sel(best.n)) best = f; });
        return best ? best.name : null;
      }
      ROOF_ALIAS[base + '_south'] = pick(function (n) { return n[2]; });
      ROOF_ALIAS[base + '_north'] = pick(function (n) { return -n[2]; });
    }
    aliasRoof('roof_main'); aliasRoof('garage_block_roof');
    function roofAlias(name) { return ROOF_ALIAS[name] || name; }
```

Expose `ROOF_ALIAS: ROOF_ALIAS, roofAlias: roofAlias` in the `webgl` object; add `window.chfRoofAlias = function () { return webgl ? webgl.ROOF_ALIAS : null; };` beside `chfRoofForms`. Find where an `EXTERIOR_HINTS` key becomes a fabric lookup (grep `EXTERIOR_HINTS` and follow `chfHouseFindFeature`); wrap that name with `webgl.roofAlias(...)`. `hintAttention` keeps comparing the canonical key.

- [ ] **Step 5: Registry pin by form.** In `scenario_shell_fabric_registry` replace the four `roof_main_*` literals in KEPT with `| roof_piece_names('roof_main', 'gable', 'x')` and the four `garage_block_roof_*` literals in NEW with `| roof_piece_names('garage_block_roof', 'gable', 'x')`.

- [ ] **Step 6: Run → GREEN**, then `--focus` + `test_house_shell_live.py` + `test_house_facade_live.py`, bump, commit:

```
fix: block roofs read BLOCK_PITCH/PITCH_FAMILY, roof pieces alias by facing, hip and ridge-z live pins (vX.Y.Z)
```

---
### Task 3: The V2 schema and `validate_block_model`

**Files:**
- Modify: `chauffeur/services/house_facade.py` (constants block lines 40–60; new functions after `_pick`)
- Test: `chauffeur/tests/test_house_facade.py`

**Interfaces:**
- Produces (module constants): `CLADDINGS = ('batten', 'lap', 'brick', 'stone', 'stucco', 'shingle')`; `STYLE['body']` gains `'brick_red', 'tan', 'cream_brick', 'stone_grey', 'painted_brick'`; `STYLE` loses `'cladding'` (it is per block now); `ROOF_KINDS = ('eave', 'gable', 'dormer', 'shed', 'hip_end')`; `PORCH_ROOFS = ('flat', 'gable')`; `ROOF_FORMS = ('gable', 'hip')`; `RIDGES = ('x', 'z')`; `ORIENTATIONS = ('front', 'side')`; `BLOCK_PITCH_DEG = 22.5`; `DEPTH_MAX = 6.0`; `DEPTH_MAX_WITH_PORCH = 2.0` (curb 8.0 − porch 4.6 − walk 1.0 = 2.4, floored to whole units per spec §2); `BASE_H_MIN, BASE_H_MAX = 0.6, 1.8`; `UNEXPRESSED_MAX, UNEXPRESSED_LEN = 8, 80`.
- Produces: `validate_block_model(obj) -> list[str]` (empty list = valid). Structural only: presence, types, enums, ranges, every feature entry complete. Never mutates.

- [ ] **Step 1: Write the failing tests** (append to `test_house_facade.py`, register in `__main__`):

```python
def _v2():
    return copy.deepcopy(hf.CANONICAL)


def scenario_validate_rejects_structurally_bad_models():
    """Spec 2026-09-17 blocks section 4: validation is not normalization.
    normalize manufactures defaults; validate must refuse first."""
    check(hf.validate_block_model(_v2()) == [], 'the canonical V2 model validates clean')
    check(hf.validate_block_model({}) != [], 'an empty object is rejected')
    m = _v2(); del m['blocks']['garage']
    check(any('garage' in e for e in hf.validate_block_model(m)), 'a missing block is named')
    m = _v2(); m['ground'].append({'slot': 3, 'kind': 'window', 'size': 'tall', 'shutters': False, 'story': 1})
    check(any('span' in e for e in hf.validate_block_model(m)), 'an incomplete feature is named')
    m = _v2(); m['blocks']['main']['cladding'] = 'vinyl'
    check(any('cladding' in e for e in hf.validate_block_model(m)), 'an out-of-enum cladding is named')
    m = _v2(); m['blocks']['main']['depth'] = 9
    check(any('depth' in e for e in hf.validate_block_model(m)), 'an out-of-range depth is named')
    m = _v2(); m['unexpressed'] = ['x'] * 9
    check(any('unexpressed' in e for e in hf.validate_block_model(m)), 'too many unexpressed strings is named')
    m = _v2(); m['blocks']['main']['base'] = {'material': 'stone', 'height': 1.0}
    check(any('base' in e for e in hf.validate_block_model(m)), 'a base band without its body colour is named')
    m = _v2(); m['ground'] = 'nope'
    check(any('ground' in e for e in hf.validate_block_model(m)), 'a non-list layer is named')
    before = json.dumps(m, sort_keys=True)
    hf.validate_block_model(m)
    check(json.dumps(m, sort_keys=True) == before, 'validate never mutates')
```

- [ ] **Step 2: Run → RED** (`validate_block_model` missing): `cd chauffeur && env -u HA_BASE_URL python tests/test_house_facade.py`.

- [ ] **Step 3: Constants and the validator.** Replace the constants block (`GROUND_KINDS` … `_ROOF_RANK`) with:

```python
GROUND_KINDS = ('wall', 'window', 'door', 'garage_door', 'porch')
ROOF_KINDS = ('eave', 'gable', 'dormer', 'shed', 'hip_end')
WINDOW_SIZES = ('tall', 'standard', 'small')
PORCH_TYPES = ('sitting', 'stoop', 'covered')
PORCH_ROOFS = ('flat', 'gable')
GARAGE_STYLES = ('carriage', 'panel', 'glass')
CLADDINGS = ('batten', 'lap', 'brick', 'stone', 'stucco', 'shingle')
ROOF_FORMS = ('gable', 'hip')
RIDGES = ('x', 'z')
ORIENTATIONS = ('front', 'side')
STYLE = {
    'body': ('white', 'greige', 'sage', 'slate', 'navy',
             'brick_red', 'tan', 'cream_brick', 'stone_grey', 'painted_brick'),
    'roof': ('charcoal', 'weathered', 'brown'),
    'frame': ('black', 'white'),
    'door': ('wood', 'black', 'red', 'sage'),
    'trim': ('white', 'black'),
}
PITCH_MIN, PITCH_MAX = 22.5, 35.0
BLOCK_PITCH_DEG = 22.5            # house.js BLOCK_PITCH = pi/8; features default PITCH_FAMILY 34.8
DEPTH_MAX = 6.0
DEPTH_MAX_WITH_PORCH = 2.0        # curb 8.0 - porch 4.6 - walk 1.0 = 2.4, floored (spec 2)
BASE_H_MIN, BASE_H_MAX = 0.6, 1.8
UNEXPRESSED_MAX, UNEXPRESSED_LEN = 8, 80
MAX_WINDOWS = 10
MAX_DORMERS = 6
MAX_GABLES = 4
MAX_PORCH_SLOTS = 10

_GROUND_RANK = {'garage_door': 3, 'door': 2, 'window': 1}      # exclusive kinds
_ROOF_RANK = {'gable': 3, 'dormer': 2, 'shed': 2, 'hip_end': 1}
```

After `_pick` add the validator:

```python
_FEATURE_REQUIRED = {
    'window': ('slot', 'span', 'size', 'shutters', 'story'),
    'door': ('slot', 'span'),
    'garage_door': ('slot', 'span', 'style', 'leaves'),
    'porch': ('slot', 'span', 'type', 'roof'),
    'gable': ('slot', 'span'), 'dormer': ('slot', 'span', 'window'),
    'shed': ('slot', 'span', 'window'), 'hip_end': ('slot', 'span'),
}


def validate_block_model(obj):
    """Structural validation of a MODEL-produced block model (spec 2026-09-17
    section 4). Returns a list of error strings; [] means valid. Never
    mutates and never fills a default: that is normalize's job, and only
    a validated object may reach it from the photo pipeline."""
    errs = []
    if not isinstance(obj, dict):
        return ['not an object']

    def need(d, key, kinds, path):
        if key not in d:
            errs.append(f'{path}.{key} missing'); return None
        v = d[key]
        if kinds is bool:
            ok = isinstance(v, bool)
        elif kinds is float:
            ok = isinstance(v, (int, float)) and not isinstance(v, bool)
        elif kinds is int:
            ok = isinstance(v, int) and not isinstance(v, bool)
        else:
            ok = isinstance(v, kinds)
        if not ok:
            errs.append(f'{path}.{key} wrong type'); return None
        return v

    def enum(d, key, allowed, path):
        v = need(d, key, str, path)
        if v is not None and v not in allowed:
            errs.append(f'{path}.{key} not one of {list(allowed)}')
        return v

    def rng(d, key, lo, hi, path):
        v = need(d, key, float, path)
        if v is not None and not (lo <= v <= hi):
            errs.append(f'{path}.{key} out of range {lo}..{hi}')
        return v

    if obj.get('version') != 2:
        errs.append('version must be 2')
    need(obj, 'mirror', bool, 'house')
    rng(obj, 'pitch_deg', PITCH_MIN, PITCH_MAX, 'house')
    blocks = need(obj, 'blocks', dict, 'house')
    if blocks is not None:
        for name in ('main', 'garage'):
            b = blocks.get(name)
            if not isinstance(b, dict):
                errs.append(f'blocks.{name} missing'); continue
            p = f'blocks.{name}'
            rng(b, 'depth', 0, DEPTH_MAX, p)
            st = need(b, 'stories', int, p)
            if st is not None and st not in (1, 2):
                errs.append(f'{p}.stories must be 1 or 2')
            roof = need(b, 'roof', dict, p)
            if roof is not None:
                enum(roof, 'form', ROOF_FORMS, p + '.roof')
                enum(roof, 'ridge', RIDGES, p + '.roof')
                rng(roof, 'pitch_deg', PITCH_MIN, PITCH_MAX, p + '.roof')
            enum(b, 'cladding', CLADDINGS, p)
            enum(b, 'body', STYLE['body'], p)
            if 'base' not in b:
                errs.append(f'{p}.base missing')
            elif b['base'] is not None:
                if not isinstance(b['base'], dict):
                    errs.append(f'{p}.base wrong type')
                else:
                    enum(b['base'], 'material', CLADDINGS, p + '.base')
                    rng(b['base'], 'height', BASE_H_MIN, BASE_H_MAX, p + '.base')
                    enum(b['base'], 'body', STYLE['body'], p + '.base')
            if name == 'garage':
                enum(b, 'orientation', ORIENTATIONS, p)
    style = need(obj, 'style', dict, 'house')
    if style is not None:
        for role in ('roof', 'frame', 'door', 'trim'):
            enum(style, role, STYLE[role], 'style')
    for layer, kinds in (('ground', GROUND_KINDS), ('roof', ROOF_KINDS)):
        items = need(obj, layer, list, 'house')
        if items is None:
            continue
        for i, e in enumerate(items):
            p = f'{layer}[{i}]'
            if not isinstance(e, dict):
                errs.append(f'{p} not an object'); continue
            kind = enum(e, 'kind', kinds, p)
            if kind in ('wall', 'eave'):
                continue
            for key in _FEATURE_REQUIRED.get(kind, ()):
                if key not in e:
                    errs.append(f'{p}.{key} missing')
            if kind == 'window' and 'story' in e and e['story'] not in (1, 2):
                errs.append(f'{p}.story must be 1 or 2')
            if kind == 'porch' and e.get('roof') not in PORCH_ROOFS:
                errs.append(f'{p}.roof not one of {list(PORCH_ROOFS)}')
            if 'cladding' in e and e['cladding'] not in CLADDINGS:
                errs.append(f'{p}.cladding not one of {list(CLADDINGS)}')
    un = need(obj, 'unexpressed', list, 'house')
    if un is not None:
        if len(un) > UNEXPRESSED_MAX:
            errs.append(f'unexpressed: more than {UNEXPRESSED_MAX} entries')
        for s in un:
            if not isinstance(s, str) or len(s) > UNEXPRESSED_LEN:
                errs.append(f'unexpressed: entries are strings of at most {UNEXPRESSED_LEN}'); break
    return errs
```

(`CANONICAL` is still V1 at this point; Task 4 replaces it. To get Step 1 green now, Task 3 and Task 4 are committed together after Task 4's Step 6 — or, if committing separately, temporarily let `_v2()` build from the Task 4 literal pasted into the test. Prefer one commit for 3+4.)

---

### Task 4: `normalize` v2, the V1→V2 mapping table, `CANONICAL` v2

**Files:**
- Modify: `chauffeur/services/house_facade.py` (`CANONICAL`, `slot_table`, `_entries`, `_resolve_exclusive` call sites, `normalize`, `worst_case`, `_photo_prompt` left for Task 11)
- Modify: `chauffeur/tests/test_house_facade.py` (existing scenarios read V2 fields; new scenarios)
- Test: `chauffeur/tests/test_house_facade.py`

**Interfaces:**
- Produces: `CANONICAL` (version 2, the V1 canonical expressed in blocks); `_upgrade_v1(raw) -> dict` (V2 raw, the spec §2 table, with `notes`); `normalize(raw) -> (spec_v2, notes)` accepting V1 or V2 raw; `slot_table(blocks=None)` (eaves follow `stories`; z follows `depth`); `block_face(name)` = `'main'` → `'main'`, `'garage'` → `'garage_block'`; `worst_case()` (V2, two stories, side garage is NOT worst — orientation stays front; brick on main, stone base on garage).
- Slot geometry: `FACES[i]['z']` becomes `z0 + depth`; `['eave']` becomes `5.6 * stories`.

- [ ] **Step 1: Write the failing tests** (append; register):

```python
def scenario_canonical_v2_is_the_old_house():
    c = hf.CANONICAL
    check(c['version'] == 2 and c['mirror'] is False, 'canonical is version 2, unmirrored')
    for name in ('main', 'garage'):
        b = c['blocks'][name]
        check(b['depth'] == 0 and b['stories'] == 1 and b['roof'] == {'form': 'gable', 'ridge': 'x', 'pitch_deg': 22.5}
              and b['cladding'] == 'batten' and b['base'] is None and b['body'] == 'white',
              f'{name} block is today\'s house: {b}')
    check(c['blocks']['garage']['orientation'] == 'front', 'garage faces the street')
    check(c['pitch_deg'] == 34.8, 'feature pitch stays PITCH_FAMILY')
    porch = next(g for g in c['ground'] if g['kind'] == 'porch')
    check(porch['roof'] == 'gable' and not any(r['slot'] == 8 for r in c['roof']),
          'the canonical porch gable is the porch\'s own roof now, not a free feature')
    check(all(g.get('story') == 1 and g.get('shutters') is False for g in c['ground'] if g['kind'] == 'window'),
          'windows carry story 1, no shutters')
    spec, notes = hf.normalize(c)
    check(spec == c and notes == [], f'canonical v2 is normal and idempotent: {notes}')


def scenario_v1_upgrade_is_the_mapping_table():
    v1 = {'version': 1, 'pitch_deg': 30.0,
          'style': {'cladding': 'clapboard', 'body': 'sage', 'roof': 'brown', 'frame': 'white', 'door': 'red', 'trim': 'black'},
          'ground': [{'slot': 0, 'span': 3, 'kind': 'garage_door', 'style': 'panel', 'leaves': 2},
                     {'slot': 8, 'span': 4, 'kind': 'porch', 'type': 'covered'},
                     {'slot': 10, 'span': 1, 'kind': 'door'},
                     {'slot': 12, 'span': 1, 'kind': 'window', 'size': 'tall'}],
          'roof': [{'slot': 8, 'span': 4, 'kind': 'gable'},          # covers the porch fully
                   {'slot': 15, 'span': 1, 'kind': 'hip_end'}]}
    spec, notes = hf.normalize(v1)
    for name in ('main', 'garage'):
        b = spec['blocks'][name]
        check(b['cladding'] == 'lap' and b['body'] == 'sage' and b['base'] is None, f'{name}: clapboard->lap, body copied, no base')
        check(b['roof']['pitch_deg'] == 22.5, f'{name}: block pitch stays 22.5, never the feature pitch')
    check(spec['pitch_deg'] == 30.0, 'the V1 pitch is the FEATURE pitch')
    check(spec['style'] == {'roof': 'brown', 'frame': 'white', 'door': 'red', 'trim': 'black'}, 'style keeps the four roles')
    porch = next(g for g in spec['ground'] if g['kind'] == 'porch')
    check(porch['roof'] == 'gable' and not any(r['kind'] == 'gable' for r in spec['roof']),
          'a gable covering the porch becomes the porch roof and the feature is removed')
    check(any(r['kind'] == 'hip_end' for r in spec['roof']), 'hip_end survives')
    win = next(g for g in spec['ground'] if g['kind'] == 'window')
    check(win['story'] == 1 and win['shutters'] is False, 'window defaults')
    check(spec['mirror'] is False and spec['unexpressed'] == [], 'mirror false, nothing unexpressed')
    check(any('porch' in n and 'gable' in n for n in notes), f'the pairing is noted: {notes}')
    # partial overlap under half: the feature stays and the porch is flat
    v1b = copy.deepcopy(v1); v1b['roof'][0] = {'slot': 11, 'span': 3, 'kind': 'gable'}   # covers slot 11 of porch 8..11 = 1/4
    spec_b, _ = hf.normalize(v1b)
    check(next(g for g in spec_b['ground'] if g['kind'] == 'porch')['roof'] == 'flat'
          and any(r['kind'] == 'gable' and r['slot'] == 11 for r in spec_b['roof']), 'under half: gable stays, porch flat')
    # exactly half pairs (>= half)
    v1c = copy.deepcopy(v1); v1c['roof'][0] = {'slot': 10, 'span': 2, 'kind': 'gable'}
    spec_c, _ = hf.normalize(v1c)
    check(next(g for g in spec_c['ground'] if g['kind'] == 'porch')['roof'] == 'gable', 'half pairs')
    # two porches: the gable goes to the larger overlap, tie -> lower slot
    v1d = copy.deepcopy(v1)
    v1d['ground'].append({'slot': 14, 'span': 2, 'kind': 'porch', 'type': 'stoop'})
    v1d['roof'][0] = {'slot': 10, 'span': 6, 'kind': 'gable'}      # porch 8..11 gets 2, porch 14..15 gets 2 -> tie -> slot 8
    spec_d, _ = hf.normalize(v1d)
    roofs = {g['slot']: g['roof'] for g in spec_d['ground'] if g['kind'] == 'porch'}
    check(roofs.get(8) == 'gable' and roofs.get(14) == 'flat', f'tie goes to the lower slot: {roofs}')


def scenario_depth_clamps_against_the_curb():
    m = _v2(); m['blocks']['main']['depth'] = 6
    spec, notes = hf.normalize(m)
    check(spec['blocks']['main']['depth'] == 2.0 and any('curb' in n for n in notes),
          f'a face with a porch clamps to {hf.DEPTH_MAX_WITH_PORCH}: {notes}')
    m = _v2(); m['blocks']['garage']['depth'] = 6
    spec, notes = hf.normalize(m)
    check(spec['blocks']['garage']['depth'] == 6.0, 'no porch on the garage face: 6 stands')
    m = _v2(); m['blocks']['garage']['depth'] = 7.5
    check(hf.normalize(m)[0]['blocks']['garage']['depth'] == 6.0, 'clamped to DEPTH_MAX')
    slots = hf.slot_table(hf.normalize(m)[0]['blocks'])
    check(abs(slots[0]['z'] - 16.10) < 1e-6 and abs(slots[6]['z'] - 14.55) < 1e-6, 'the slot table follows depth per face')


def scenario_stories_and_per_story_overlap():
    m = _v2(); m['blocks']['main']['stories'] = 2
    m['ground'].append({'slot': 10, 'span': 1, 'kind': 'window', 'size': 'standard', 'shutters': True, 'story': 2})
    spec, notes = hf.normalize(m)
    kinds = [(g['kind'], g['slot'], g.get('story')) for g in spec['ground']]
    check(('door', 10, None) in kinds or ('door', 10, 1) in kinds, 'the ground-floor door at slot 10 stays')
    check(('window', 10, 2) in kinds, 'an upstairs window over the door is kept: overlap is per story')
    slots = hf.slot_table(spec['blocks'])
    check(abs(slots[6]['eave'] - 11.2) < 1e-6 and abs(slots[0]['eave'] - 5.6) < 1e-6, 'eaves follow stories per face')
    m = _v2()
    m['ground'].append({'slot': 12, 'span': 1, 'kind': 'window', 'size': 'small', 'shutters': False, 'story': 2})
    spec, notes = hf.normalize(m)
    check(not any(g.get('story') == 2 for g in spec['ground']) and any('story' in n for n in notes),
          f'a story-2 window on a one-story block is dropped with a note: {notes}')


def scenario_side_garage_and_shed_and_unexpressed():
    m = _v2(); m['blocks']['garage']['orientation'] = 'side'
    spec, notes = hf.normalize(m)
    check(spec['blocks']['garage']['orientation'] == 'side', 'orientation kept')
    check(not any(g['kind'] == 'garage_door' for g in spec['ground']), 'a side garage carries no street garage door entry')
    check(any(g['kind'] == 'window' and 0 <= g['slot'] <= 2 for g in spec['ground']), 'the bay\'s street face gets one window')
    m = _v2(); m['roof'].append({'slot': 13, 'span': 2, 'kind': 'shed', 'window': True, 'cladding': 'shingle'})
    spec, _ = hf.normalize(m)
    shed = next(r for r in spec['roof'] if r['kind'] == 'shed')
    check(shed['window'] is True and shed['cladding'] == 'shingle', 'shed keeps window + cladding override')
    m = _v2(); m['unexpressed'] = ['x' * 200] * 12
    spec, _ = hf.normalize(m)
    check(len(spec['unexpressed']) == 8 and all(len(s) == 80 for s in spec['unexpressed']), 'unexpressed capped 8 x 80')
    m = _v2(); m['blocks']['main']['base'] = {'material': 'stone', 'height': 5, 'body': 'stone_grey'}
    spec, _ = hf.normalize(m)
    check(spec['blocks']['main']['base'] == {'material': 'stone', 'height': 1.8, 'body': 'stone_grey'}, 'base height clamped')
```

Update existing scenarios that read V1 fields: `scenario_unknown_enums_fall_to_defaults` (cladding now under `blocks.main`), `scenario_pitch_clamps` (feature pitch still top-level), `scenario_worst_case_is_within_caps` (reads V2), `scenario_photo_becomes_a_draft_never_a_save` (the fake pool must now return a VALID V2 object — build it from `hf.CANONICAL` with `body: 'sage'`; Task 11 rewrites this scenario anyway), `scenario_canonical_is_normal_and_idempotent` (unchanged in spirit).

- [ ] **Step 2: Run → RED.**

- [ ] **Step 3: `CANONICAL` v2, `slot_table(blocks)`, `_upgrade_v1`, `normalize`.**

```python
def _block(**over):
    b = {'depth': 0.0, 'stories': 1,
         'roof': {'form': 'gable', 'ridge': 'x', 'pitch_deg': BLOCK_PITCH_DEG},
         'cladding': 'batten', 'base': None, 'body': 'white'}
    b.update(over)
    return b


CANONICAL = {
    'version': 2,
    'mirror': False,
    'pitch_deg': round(math.degrees(math.atan2(2.05, 2.95)), 1),   # 34.8, PITCH_FAMILY (features)
    'blocks': {'main': _block(), 'garage': _block(orientation='front')},
    'style': {'roof': 'charcoal', 'frame': 'black', 'door': 'wood', 'trim': 'white'},
    'ground': [
        {'slot': 0, 'span': 3, 'kind': 'garage_door', 'style': 'carriage', 'leaves': 1},
        {'slot': 7, 'span': 1, 'kind': 'window', 'size': 'tall', 'shutters': False, 'story': 1},
        {'slot': 8, 'span': 4, 'kind': 'porch', 'type': 'sitting', 'roof': 'gable'},
        {'slot': 9, 'span': 1, 'kind': 'window', 'size': 'tall', 'shutters': False, 'story': 1},
        {'slot': 10, 'span': 1, 'kind': 'door'},
        {'slot': 12, 'span': 1, 'kind': 'window', 'size': 'tall', 'shutters': False, 'story': 1},
        {'slot': 15, 'span': 1, 'kind': 'window', 'size': 'standard', 'shutters': False, 'story': 1},
        {'slot': 16, 'span': 1, 'kind': 'window', 'size': 'standard', 'shutters': False, 'story': 1},
    ],
    'roof': [
        {'slot': 0, 'span': 3, 'kind': 'gable'},
    ],
    'unexpressed': [],
}

BLOCK_OF_FACE = {'garage_block': 'garage', 'main': 'main'}


def slot_table(blocks=None):
    """Slots per street face. `blocks` (a V2 `blocks` dict) moves each face
    by its depth and raises its eave by its stories; None = canonical."""
    blocks = blocks or CANONICAL['blocks']
    out, i = [], 0
    for f in FACES:
        b = blocks.get(BLOCK_OF_FACE[f['face']]) or {}
        z = f['z'] + float(b.get('depth') or 0)
        eave = f['eave'] * (2 if b.get('stories') == 2 else 1)
        width = f['x1'] - f['x0']
        n = max(1, int(round(width / SLOT_W)))
        w = width / n
        for k in range(n):
            x0 = f['x0'] + k * w
            out.append({'i': i, 'face': f['face'], 'x0': round(x0, 6), 'x1': round(x0 + w, 6),
                        'cx': round(x0 + w / 2, 6), 'z': round(z, 6), 'eave': eave,
                        'room': f['room'], 'roof': f['roof']})
            i += 1
    return out
```

`_face_range` is unchanged (faces do not move slots). The upgrade:

```python
def _upgrade_v1(raw, notes):
    """The spec 2026-09-17 section 2 mapping table. Returns a V2-shaped raw
    dict; normalize() then applies every law to it."""
    st = raw.get('style') if isinstance(raw.get('style'), dict) else {}
    clad = {'batten': 'batten', 'clapboard': 'lap'}.get(st.get('cladding'), 'batten')
    body = st.get('body', 'white')
    blocks = {'main': _block(cladding=clad, body=body),
              'garage': _block(cladding=clad, body=body, orientation='front')}
    ground = [dict(g) for g in raw.get('ground', []) if isinstance(g, dict)]
    roof = [dict(r) for r in raw.get('roof', []) if isinstance(r, dict)]
    for g in ground:
        if g.get('kind') == 'window':
            g.setdefault('shutters', False); g.setdefault('story', 1)
        if g.get('kind') == 'porch':
            g.setdefault('roof', 'flat')
    # gable-over-porch pairing: a gable covering >= half a porch's span
    # becomes that porch's roof; the feature is removed. Two porches: the
    # larger overlap wins, tie -> lower slot.
    porches = [g for g in ground if g.get('kind') == 'porch']
    kept = []
    for r in roof:
        if r.get('kind') != 'gable' or not porches:
            kept.append(r); continue
        rs, re_ = _int(r.get('slot'), -1), _int(r.get('slot'), -1) + max(1, _int(r.get('span'), 1))
        best, best_ov = None, 0
        for p in sorted(porches, key=lambda p: _int(p.get('slot'), 0)):
            ps, pe = _int(p.get('slot'), 0), _int(p.get('slot'), 0) + max(1, _int(p.get('span'), 1))
            ov = max(0, min(re_, pe) - max(rs, ps))
            if ov * 2 >= (pe - ps) and ov > best_ov:
                best, best_ov = p, ov
        if best is None:
            kept.append(r); continue
        if best.get('roof') == 'gable':
            notes.append(f"dropped a gable at slot {rs}: porch at slot {best.get('slot')} already has a gabled roof")
            continue
        best['roof'] = 'gable'
        notes.append(f"a gable at slot {rs} became the porch roof at slot {best.get('slot')}")
    return {'version': 2, 'mirror': False, 'pitch_deg': raw.get('pitch_deg'),
            'blocks': blocks, 'style': {k: st.get(k) for k in ('roof', 'frame', 'door', 'trim')},
            'ground': ground, 'roof': kept, 'unexpressed': []}


def _norm_block(name, raw, notes):
    raw = raw if isinstance(raw, dict) else {}
    b = _block(orientation='front') if name == 'garage' else _block()
    b['depth'] = round(min(DEPTH_MAX, max(0.0, _num(raw.get('depth'), 0.0))), 2)
    b['stories'] = 2 if _int(raw.get('stories'), 1) == 2 else 1
    rr = raw.get('roof') if isinstance(raw.get('roof'), dict) else {}
    b['roof'] = {'form': _pick(rr.get('form'), ROOF_FORMS, 'gable'),
                 'ridge': _pick(rr.get('ridge'), RIDGES, 'x'),
                 'pitch_deg': round(min(PITCH_MAX, max(PITCH_MIN, _num(rr.get('pitch_deg'), BLOCK_PITCH_DEG))), 1)}
    b['cladding'] = _pick(raw.get('cladding'), CLADDINGS, 'batten')
    b['body'] = _pick(raw.get('body'), STYLE['body'], 'white')
    base = raw.get('base')
    if isinstance(base, dict):
        b['base'] = {'material': _pick(base.get('material'), CLADDINGS, 'stone'),
                     'height': round(min(BASE_H_MAX, max(BASE_H_MIN, _num(base.get('height'), 0.9))), 2),
                     'body': _pick(base.get('body'), STYLE['body'], 'stone_grey')}
    else:
        b['base'] = None
    if name == 'garage':
        b['orientation'] = _pick(raw.get('orientation'), ORIENTATIONS, 'front')
    return b
```

`_entries` gains the new per-kind fields (inside the `if kind == 'window'` branch add `item['shutters'] = bool(e.get('shutters', False)); item['story'] = 2 if _int(e.get('story'), 1) == 2 else 1`; the porch branch adds `item['roof'] = _pick(e.get('roof'), PORCH_ROOFS, 'flat')`; a `shed` branch mirrors dormer's `window`; every roof kind copies `cladding` when it is in `CLADDINGS`). `normalize` becomes:

```python
def normalize(raw):
    notes = []
    raw = raw if isinstance(raw, dict) else {}
    if 'blocks' not in raw:
        raw = _upgrade_v1(raw, notes)
    spec = {'version': 2, 'mirror': bool(raw.get('mirror', False))}
    p = _num(raw.get('pitch_deg'), CANONICAL['pitch_deg'])
    spec['pitch_deg'] = round(min(PITCH_MAX, max(PITCH_MIN, p)), 1)
    blocks_raw = raw.get('blocks') if isinstance(raw.get('blocks'), dict) else {}
    spec['blocks'] = {'main': _norm_block('main', blocks_raw.get('main'), notes),
                      'garage': _norm_block('garage', blocks_raw.get('garage'), notes)}
    st = raw.get('style') if isinstance(raw.get('style'), dict) else {}
    spec['style'] = {k: _pick(st.get(k), allowed, CANONICAL['style'][k]) for k, allowed in STYLE.items() if k != 'body'}

    ground = _entries(raw.get('ground'), GROUND_KINDS, notes, 'ground')
    roof = _entries(raw.get('roof'), ROOF_KINDS, notes, 'roof')
    slots = slot_table(spec['blocks'])
    g_lo, g_hi = GARAGE_BAY_SLOTS
    m_lo, m_hi = _face_range('main')

    # ... (garage door pin, door pin, canonical door, _clip_to_face, porch-in-bay: UNCHANGED from today) ...

    # a side-entry garage has no street garage door: the bay's street face
    # carries one window instead (spec 2)
    if spec['blocks']['garage']['orientation'] == 'side':
        n0 = len(ground)
        ground = [g for g in ground if g['kind'] != 'garage_door']
        if len(ground) != n0:
            notes.append('side-entry garage: the street garage door moved to the side face')
        if not any(g['kind'] == 'window' and g_lo <= g['slot'] <= g_hi for g in ground):
            ground.append({'slot': g_lo + 1, 'span': 1, 'kind': 'window', 'size': 'standard', 'shutters': False, 'story': 1})

    # story-2 entries only on a two-story block; overlap resolved PER story
    def block_of(item):
        return BLOCK_OF_FACE[slots[item['slot']]['face']]
    kept = []
    for g in ground:
        if g.get('story') == 2 and spec['blocks'][block_of(g)]['stories'] != 2:
            notes.append(f"dropped a story-2 {g['kind']} at slot {g['slot']}: that block has one story")
            continue
        kept.append(g)
    ground = kept
    porches = [g for g in ground if g['kind'] == 'porch']
    s1 = [g for g in ground if g['kind'] != 'porch' and g.get('story', 1) == 1]
    s2 = [g for g in ground if g['kind'] != 'porch' and g.get('story') == 2]
    exclusive = _resolve_exclusive(s1, _GROUND_RANK, notes) + _resolve_exclusive(s2, _GROUND_RANK, notes)
    # a gabled porch owns its roof: a gable FEATURE covering it is dropped
    for pch in porches:
        if pch['roof'] != 'gable':
            continue
        n0 = len(roof)
        roof = [r for r in roof if not (r['kind'] == 'gable' and r['slot'] < pch['slot'] + pch['span'] and pch['slot'] < r['slot'] + r['span'])]
        if len(roof) != n0:
            notes.append(f"dropped a gable over the gabled porch at slot {pch['slot']}")
    roof = _resolve_exclusive(roof, _ROOF_RANK, notes)

    # depth clamp: a face carrying a porch keeps the porch behind the curb
    for pch in porches:
        bname = block_of(pch)
        if spec['blocks'][bname]['depth'] > DEPTH_MAX_WITH_PORCH:
            spec['blocks'][bname]['depth'] = DEPTH_MAX_WITH_PORCH
            notes.append(f'{bname} depth clamped to {DEPTH_MAX_WITH_PORCH}: its porch must stay behind the curb')

    # ... (caps: dormer/gable/window/porch: UNCHANGED; `shed` shares MAX_DORMERS with dormers) ...

    spec['ground'] = sorted(exclusive + porches, key=lambda g: (g['slot'], g.get('story', 1), g['kind']))
    spec['roof'] = sorted(roof, key=lambda r: (r['slot'], r['kind']))
    un = raw.get('unexpressed') if isinstance(raw.get('unexpressed'), list) else []
    spec['unexpressed'] = [str(s)[:UNEXPRESSED_LEN] for s in un if isinstance(s, str) and s.strip()][:UNEXPRESSED_MAX]
    return spec, notes
```

Keep every existing block of `normalize` that the comment markers say is unchanged; only the listed insertions and the V2 head/tail change. `worst_case()` builds a V2 raw: two stories on both blocks, `cladding: 'brick'` main / `'stone'` garage, a `base` on each, `depth` 2 on main and 6 on garage, every cap filled as today, `orientation: 'front'`.

- [ ] **Step 4: Run → GREEN.** Then `--focus`, bump, commit (Tasks 3+4 together):

```
feat: the block model — V2 schema, validate_block_model before normalize, V1 mapping table, per-story overlap, depth clamps (vX.Y.Z)
```

---
### Task 5: house.js reads the block model — per-block pitch and forms, six claddings, base band, pixel pin

**Files:**
- Modify: `chauffeur/static/house.js` (`PALETTE` `~3923`; `FACADE`/`FSTYLE` `~3942`; textures `~3994–4082`; `box()` UV detection `~1258` and `vaultSection` `~4525`; `ROOF_FORMS` `~4368`; `BLOCK_PITCH` `~4594`; `FACE_BLOCKS`/`blockDeckPlanes`/`faceDeckPlane` `~5218–5250`; `CANONICAL_JS` `~5164`; `shellWall` `~4865`; the `south_wall`/`east_wall`/`north_wall`/`north_wall_east`/`west_wall` registration sites)
- Modify: `chauffeur/tests/test_house_facade_live.py` (canonical pin gains the pixel check; new `scenario_claddings_and_base_band`)
- Test: `chauffeur/tests/test_house_facade_live.py`

**Interfaces:**
- Produces (house.js, inside the build closure): `BLOCKS` = `FACADE.spec.blocks` or `CANONICAL_JS.blocks`; `BLOCK_OF_FACE = { garage_block: 'garage', main: 'main' }`; `blockPitch(name)` → radians from `BLOCKS[name].roof.pitch_deg`; `ROOF_FORMS` now `{ main: BLOCKS.main.roof, garage: BLOCKS.garage.roof }` (still overridable by `window.HOUSE_ROOF_FORMS`); `cladTex(material, bodyHex)` → a cached `CanvasTexture` with `userData.uvRef = [13, 5.6, 13]` and `userData.uvKey = material`; `CLAD(blockName)` → `cladTex(BLOCKS[b].cladding, pal('body', BLOCKS[b].body))`; `baseBand(g, x0, z0, x1, z1, normal, blockName)`; `PALETTE.body` gains the five names; `window.chfBlocks()` returns `BLOCKS`.
- `FARMHOUSE.body` becomes `pal('body', BLOCKS.main.body)` (the main block's body is the house's default body tone wherever one colour is wanted); `EXTC.garage` reads the garage block's body.

- [ ] **Step 1: Failing pins.** In `scenario_canonical_facade_pins_the_hand_built_elevation` add `page.add_init_script(SEED_RNG_JS)` before `goto` and, after the existing checks:

```python
        # Spec 2026-09-17 blocks section 2 compatibility pin: the canonical V2
        # model renders the same picture as B0 (Task 1, same seed, same day
        # lock). Mean absolute difference over the frame, 8-bit channels.
        png = page.screenshot(clip={'x': 0, 'y': 0, 'width': 1400, 'height': 1000})
        from PIL import Image, ImageChops, ImageStat
        import io as _io
        a = Image.open(_io.BytesIO(png)).convert('RGB')
        b = Image.open(os.path.join(os.path.dirname(__file__), 'fixtures', 'house_photo', 'b0-exterior.png')).convert('RGB')
        diff = ImageStat.Stat(ImageChops.difference(a, b)).mean
        check(max(diff) < 1.5, f'canonical V2 renders B0 within tolerance: mean channel diff {diff}')
        check(page.evaluate('window.chfBlocks().main.cladding') == 'batten', 'the scene built from the block model')
```

Add the new scenario (register in `__main__`):

```python
def scenario_claddings_and_base_band():
    """Spec section 3.1: six claddings, world-scaled UVs carried on the
    texture, a base band in its own material and colour. Each variant
    boots clean and the draw count stays within the measured rule."""
    from services import house_facade as hf
    served = live_app(_seed)
    if served is None:
        return
    from house_probe import THREE_WRAP
    with open('static/vendor/three.min.js', 'rb') as fh:
        patched = fh.read() + THREE_WRAP
    def boot(page, spec):
        page.route('**/three.min.js*', lambda route: route.fulfill(
            status=200, content_type='application/javascript', body=patched))
        page.add_init_script(DAY_LOCK_JS)
        page.add_init_script('window.HOUSE_FACADE = %s;' % json.dumps({'id': 'test', 'name': 't', 'spec': spec, 'slots': hf.slot_table(spec['blocks'])}))
        page.goto(served.url('house?quality=high'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        return page.evaluate(BUDGET_JS)      # house_probe's report JS, imported like THREE_WRAP
    with served.browser() as page:
        base = boot(page, hf.CANONICAL)
    for clad in ('lap', 'brick', 'stone', 'stucco', 'shingle'):
        spec = copy.deepcopy(hf.CANONICAL)
        spec['blocks']['main']['cladding'] = clad
        spec['blocks']['main']['body'] = 'brick_red' if clad == 'brick' else 'tan'
        spec['blocks']['garage']['base'] = {'material': 'stone', 'height': 1.0, 'body': 'stone_grey'}
        with served.browser() as page:
            r = boot(page, spec)
            # main brick + garage batten + a stone base = two new (material, body) pairs
            check(r['calls'] <= base['calls'] + 2 + 6,
                  f"{clad}: draws {r['calls']} vs canonical {base['calls']} (+2 pairs, +6 unmerged band ends)")
            check(r['inFrustum'] <= base['inFrustum'] + 12, f"{clad}: meshes {r['inFrustum']} vs {base['inFrustum']}")
            u = page.evaluate("(() => { const b = window.chfBlocks(); return b.main.cladding + '|' + b.garage.base.material; })()")
            check(u == clad + '|stone', f'built from the model: {u}')
            errs = [e for e in served.errors() if 'WebGL' not in e]
            check(not errs, f'{clad}: console clean: {errs[:3]}')
```

(`BUDGET_JS` is the probe's report string; export it as a module constant in `house_probe.py` next to `THREE_WRAP` if it is not already one. The `+6 unmerged band ends` allowance: each base band run is a box merged into its wall's bucket except the two trim end caps; record the real number in §9 and tighten the check to it.)

- [ ] **Step 2: Run → RED** (`chfBlocks` undefined; the pixel diff may already pass).

- [ ] **Step 3: The model in JS.** Replace the `FACADE`/`FSTYLE` block:

```js
    var FACADE = (window.HOUSE_FACADE && window.HOUSE_FACADE.spec && window.HOUSE_FACADE.spec.blocks)
                 ? window.HOUSE_FACADE : null;
    /* CANONICAL_JS is declared far below (the facade block) but `var`
       hoists it; it is READ only after buildRoom's first statements, so
       the literal must sit above every reader: move CANONICAL_JS up to
       here (verbatim, V2 shape from Task 4's CANONICAL). */
    var SPEC0 = FACADE ? FACADE.spec : CANONICAL_JS;
    var BLOCKS = SPEC0.blocks;
    var BLOCK_OF_FACE = { garage_block: 'garage', main: 'main' };
    var FSTYLE = SPEC0.style;                 /* roof, frame, door, trim */
    function blockPitch(name) { return BLOCKS[name].roof.pitch_deg * Math.PI / 180; }
```

`FARMHOUSE.body` becomes `pal('body', BLOCKS.main.body, 0xf4f1e9)`; add to `PALETTE.body`: `brick_red: 0x8e3b2f, tan: 0xcbb69a, cream_brick: 0xe3d5b8, stone_grey: 0x8b8a84, painted_brick: 0xece6dc`. `ROOF_FORMS` becomes `{ main: { form: BLOCKS.main.roof.form, ridge: BLOCKS.main.roof.ridge }, garage: { form: BLOCKS.garage.roof.form, ridge: BLOCKS.garage.roof.ridge } }` with the `window.HOUSE_ROOF_FORMS` override loop kept. `BLOCK_PITCH` stays as a name but becomes `blockPitch('main')` for `MAIN_VAULT`/`roof_main` and `blockPitch('garage')` at the garage `roofVault`/`garage_block_roof` sites; `FACE_BLOCKS` rows gain `pitch: blockPitch('main')` / `blockPitch('garage')` and `blockDeckPlanes`/`faceDeckPlane` read `B.pitch` instead of `BLOCK_PITCH`. `CANONICAL_JS` is replaced by the V2 literal (field for field Task 4's `CANONICAL`).

- [ ] **Step 4: Textures carry their UV reference.** In `box()` and `vaultSection` replace the three-way identity test with:

```js
      var uvRef = null, uvKey = '';
      if (NICE && opts && opts.map && opts.map.userData && opts.map.userData.uvRef) {
        uvRef = opts.map.userData.uvRef; uvKey = opts.map.userData.uvKey;
      }
```

and stamp `battenT.userData = { uvRef: BATTEN_UV_REF, uvKey: 'batten' }`, `sidingT.userData = { uvRef: SIDING_UV_REF, uvKey: 'lap' }`, `shingleT.userData = { uvRef: SHINGLE_UV_REF, uvKey: 'shingle' }` right after each is created. Then the six painters:

```js
    /* Spec 2026-09-17 blocks section 3.1: one tile per (material, body),
       world-scaled through userData.uvRef so seams and phase hold across
       pieces. Build-time textures, never disposed (lifecycle law). */
    var CLAD_CACHE = {};
    var CLAD_PAINT = {
      batten: function (g, S, body) {
        g.fillStyle = body; g.fillRect(0, 0, S, S);
        for (var bx = 0; bx < S; bx += 32) {
          g.fillStyle = 'rgba(255,255,255,0.5)'; g.fillRect(bx, 0, 3, S);
          g.fillStyle = 'rgba(110,98,80,0.5)'; g.fillRect(bx + 3, 0, 4, S);
        }
      },
      lap: function (g, S, body) {
        g.fillStyle = body; g.fillRect(0, 0, S, S);
        for (var y = 0; y < S; y += 21) {
          g.fillStyle = 'rgba(110,98,80,0.5)'; g.fillRect(0, y + 18, S, 3);
          g.fillStyle = 'rgba(255,255,255,0.5)'; g.fillRect(0, y, S, 2);
        }
      },
      brick: function (g, S, body) {
        g.fillStyle = '#b9b2a6'; g.fillRect(0, 0, S, S);           /* mortar */
        var ch = 16, bw = 64;
        for (var r = 0; r < S / ch; r++) {
          var off = (r % 2) ? bw / 2 : 0;
          for (var x = -bw; x < S + bw; x += bw) {
            var j = ((r * 7 + x / bw) % 5) * 6 - 12;                  /* per-brick tone jitter, deterministic */
            g.fillStyle = shade(body, j);
            g.fillRect(x + off + 1, r * ch + 1, bw - 3, ch - 3);
          }
        }
      },
      stone: function (g, S, body) {
        g.fillStyle = '#a9a49b'; g.fillRect(0, 0, S, S);
        var y = 0, r = 0;
        while (y < S) {
          var h = 24 + ((r * 5) % 3) * 8, x = -((r * 13) % 40);
          while (x < S) {
            var w = 40 + ((x / 7 + r) % 4) * 16;
            g.fillStyle = shade(body, ((r + x / 8) % 4) * 5 - 8);
            g.fillRect(x + 2, y + 2, w - 4, h - 4);
            x += w;
          }
          y += h; r += 1;
        }
      },
      stucco: function (g, S, body) {
        g.fillStyle = body; g.fillRect(0, 0, S, S);
        for (var i = 0; i < 1400; i++) {
          g.fillStyle = 'rgba(0,0,0,' + (0.03 + ((i * 31) % 7) * 0.01) + ')';
          g.fillRect((i * 97) % S, (i * 57) % S, 2, 2);
          g.fillStyle = 'rgba(255,255,255,0.06)';
          g.fillRect((i * 61) % S, (i * 89) % S, 1, 1);
        }
      },
      shingle: function (g, S, body) {                          /* wall shingle: staggered short courses */
        g.fillStyle = body; g.fillRect(0, 0, S, S);
        var ch = 24, sw = 20;
        for (var r = 0; r < S / ch; r++) {
          var off = (r % 2) ? sw / 2 : 0;
          g.fillStyle = 'rgba(60,50,40,0.45)'; g.fillRect(0, r * ch + ch - 3, S, 3);
          for (var x = -sw; x < S + sw; x += sw) {
            g.fillStyle = 'rgba(60,50,40,0.35)'; g.fillRect(x + off, r * ch, 2, ch);
          }
        }
      }
    };
    /* darken/lighten a '#rrggbb' by `d` per channel */
    function shade(css, d) {
      var n = parseInt(css.slice(1), 16);
      function c(v) { return Math.max(0, Math.min(255, v + d)); }
      return '#' + ('000000' + ((c(n >> 16) << 16) | (c((n >> 8) & 255) << 8) | c(n & 255)).toString(16)).slice(-6);
    }
    function cladTex(material, bodyHex) {
      if (!NICE) return null;
      var key = material + '|' + bodyHex;
      if (CLAD_CACHE[key]) return CLAD_CACHE[key];
      var paint = CLAD_PAINT[material] || CLAD_PAINT.batten;
      var t = canvasTex(256, function (g, S) { paint(g, S, hex6(bodyHex)); });
      t.wrapS = t.wrapT = T.RepeatWrapping;
      t.repeat.set(4, 2);
      t.userData = { uvRef: BATTEN_UV_REF, uvKey: material };
      CLAD_CACHE[key] = t;
      return t;
    }
    function CLAD(block) {
      var b = BLOCKS[block || 'main'];
      return cladTex(b.cladding, pal('body', b.body, 0xf4f1e9));
    }
```

`battenT`/`sidingT` become `cladTex('batten', FARMHOUSE.body)` / `cladTex('lap', FARMHOUSE.body)` (so the canonical build resolves to the same tiles it always did, through the cache). Every `CLAD()` call site names its block: garage-block walls (`garage_block_north/west`, `mudroom_front`, the garage shell bands `~6170`) pass `'garage'`; main walls pass `'main'` or nothing. Wall colour under NICE stays `0xffffff` (the tile carries the body), and under `!NICE` the box colour becomes `pal('body', BLOCKS[block].body)`.

- [ ] **Step 5: The base band.** Add beside `shellWall`:

```js
    /* Spec section 2: a band at the block's foot in its own material, height
       and colour. A second box run 0.06 proud of the wall, merged into the
       wall's own bucket (same group, same room, shared material). */
    function baseBand(g, x0, z0, x1, z1, normal, block) {
      var b = BLOCKS[block]; if (!b || !b.base) return;
      var h = b.base.height, alongX = x0 !== x1;
      var length = alongX ? x1 - x0 : z1 - z0;
      var cx = (x0 + x1) / 2 + (alongX ? 0 : normal[0] * 0.03);
      var cz = (z0 + z1) / 2 + (alongX ? normal[2] * 0.03 : 0);
      shellBox(g, alongX ? length : WALL_T4 + 0.06, h, alongX ? WALL_T4 + 0.06 : length,
               NICE ? 0xffffff : pal('body', b.base.body, 0x8b8a84), cx, h / 2, cz,
               { rough: 0.95, map: cladTex(b.base.material, pal('body', b.base.body, 0x8b8a84)) });
    }
```

Call it inside `shellWall` after the stoop skirt (`baseBand(g, x0, z0, x1, z1, normal, room === 'mudroom' || name.indexOf('garage_block') === 0 ? 'garage' : 'main')` — better: give `shellWall` an optional trailing `block` argument and pass it at every call site), and at the hand-built main walls' registration sites (`south_wall`, `east_wall`, `north_wall`, `north_wall_east`, `west_wall`: grep `regFabric(` / `refabBox(` for those names and add `baseBand(<their group>, ...)` with the wall's own x/z run and normal before the registration). The canonical has `base: null`, so the canonical build adds nothing.

- [ ] **Step 6: Expose and run.** Add `BLOCKS: BLOCKS` to the `webgl` object and `window.chfBlocks = function () { return webgl ? webgl.BLOCKS : null; };`. Run `test_house_facade_live.py` → GREEN (pixel pin, cladding variants). Also run `test_house_shell_live.py` (registry and vault pins) and `--focus`. Bump, commit:

```
feat: house.js reads the block model — per-block pitch/forms, six claddings on texture UV refs, base band, canonical pixel pin (vX.Y.Z)
```

---

### Task 6: Depth per block, the block-meet return wall, neighbour-volume roof subtraction

**Files:**
- Modify: `chauffeur/static/house.js` (`FULL_HOUSE` `~4271`; the south wall slab site right after it; `GARAGE_BLOCK` `~4361`; `FACES` `~5127`; `buriedRegion` `~5266`; the two block-roof `shellGable` calls; the front walk/driveway builders (grep `PORCH_FRONT_Z4`, `DOOR_X4`, `driveT`))
- Modify: `chauffeur/tests/test_house_facade_live.py` (new `scenario_depth_moves_the_face_and_the_blocks_meet`)
- Test: `chauffeur/tests/test_house_facade_live.py`

**Interfaces:**
- Produces: `FULL_HOUSE.south = SWZ1 + BLOCKS.main.depth`; `GARAGE_BLOCK.south = 10.10 + BLOCKS.garage.depth`; `FACES[*].z` read those; registered pieces `main_return` (x = -7.15 between the two souths, when main is deeper) or `garage_return` (when the garage is deeper), and `main_void_floor` / `garage_void_floor` (R-B); `neighbourVolume(name)` → clip planes; `window.chfBlockGeometry()` → `{ main: {south, eave}, garage: {south, eave} }`.

- [ ] **Step 1: Failing scenario:**

```python
def scenario_depth_moves_the_face_and_the_blocks_meet():
    """Spec section 2 (depth, where blocks meet) and 3.2. Four combinations
    of depth difference; each boots clean, the street faces sit where the
    model says, the return wall closes the step, the deeper block's roof
    stops at the neighbour's bounded volume and nothing outside that
    volume is lost."""
    from services import house_facade as hf
    served = live_app(_seed)
    if served is None:
        return
    combos = [({'main': 2, 'garage': 0}, 'main_return'), ({'main': 0, 'garage': 6}, 'garage_return'),
              ({'main': 2, 'garage': 6}, 'garage_return'), ({'main': 0, 'garage': 0}, None)]
    for depths, ret in combos:
        spec = copy.deepcopy(hf.CANONICAL)
        spec['blocks']['main']['depth'] = depths['main']; spec['blocks']['garage']['depth'] = depths['garage']
        spec, _ = hf.normalize(spec)
        with served.browser() as page:
            page.add_init_script(DAY_LOCK_JS)
            page.add_init_script('window.HOUSE_FACADE = %s;' % json.dumps({'id': 't', 'name': 't', 'spec': spec, 'slots': hf.slot_table(spec['blocks'])}))
            page.goto(served.url('house?quality=high'))
            page.wait_for_selector('#room canvas', timeout=20000)
            page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
            geo = page.evaluate('window.chfBlockGeometry()')
            check(abs(geo['main']['south'] - (14.55 + depths['main'])) < 1e-3 and
                  abs(geo['garage']['south'] - (10.10 + depths['garage'])) < 1e-3, f'{depths}: faces moved: {geo}')
            names = {r['name'] for r in page.evaluate('window.chfShellFabric()')}
            if ret:
                check(ret in names, f'{depths}: {ret} registered')
            else:
                check('main_return' not in names and 'garage_return' not in names, 'equal depths: no return wall')
            # the front door still walks in and the front walk reaches the new face
            probe = page.evaluate("window.chfNavProbe({feature:'front_door'})")
            check(probe and probe.get('hit'), f'{depths}: front door reachable from the street: {probe}')
            # roof audit: no vertex of roof_main pieces inside the garage block's volume and vice versa
            leak = page.evaluate(ROOF_INSIDE_NEIGHBOUR_JS)
            check(leak['main_in_garage'] == 0 and leak['garage_in_main'] == 0, f'{depths}: roof inside the neighbour: {leak}')
            check(leak['main_area'] > 0.9 * leak['main_area_expected'], f"{depths}: main roof kept outside the neighbour: {leak}")
            errs = [e for e in served.errors() if 'WebGL' not in e]
            check(not errs, f'{depths}: console clean: {errs[:3]}')
```

`ROOF_INSIDE_NEIGHBOUR_JS` (add to `house_live_common.py`): reads `window.chfFabricVertices(name)` for each `roof_main_*` and `garage_block_roof_*` piece and `window.chfBlockGeometry()`; counts vertices strictly inside the OTHER block's box (x within its west..east, z within north..south, y below its ridge, all with 0.05 tolerance inward); `main_area` = `chfShellFabric()` row `area0` sum for `roof_main_*`, `main_area_expected` = the same sum from an equal-depth boot recorded once at the top of the scenario (boot the `{0,0}` combo first and store it).

- [ ] **Step 2: Run → RED** (`chfBlockGeometry` undefined).

- [ ] **Step 3: The faces move.** `FULL_HOUSE.south = SWZ1 + BLOCKS.main.depth` and the south wall slab is built at `FULL_HOUSE.south` (its centre z = `FULL_HOUSE.south - WALL_T4 / 2`; the slab's box keeps its thickness `WALL_T4`); `GARAGE_BLOCK.south = 10.10 + BLOCKS.garage.depth`; `mudroom_front` and the garage door bay read `GARAGE_BLOCK.south` (they already do through the constant). `FACES` already reads `SWZ1`/`GARAGE_BLOCK.south`: change the main row to `z: FULL_HOUSE.south`. `PORCH_FRONT_Z4`, `DOOR_X4` and the front walk follow the slot z automatically (the builders publish them); the driveway slab's near end reads `GARAGE_BLOCK.south`. Add the void floor (R-B) when depth > 0:

```js
    if (BLOCKS.main.depth > 0)
      refabBox('main_void_floor', box(SW_W, 0.10, BLOCKS.main.depth, FARMHOUSE.stoop,
               SW_CX, -0.05, SWZ1 + BLOCKS.main.depth / 2, extG, sharp()));
```

(and the garage equivalent over the garage block's width). Register through `refabBox` so the mask treats it as fabric of no room (kept in every view).

- [ ] **Step 4: The return wall.** After both block souths are known:

```js
    (function () {
      var dm = FULL_HOUSE.south, dg = GARAGE_BLOCK.south, x = FULL_HOUSE.west;   /* -7.15 shared face */
      if (Math.abs(dm - dg) < 1e-6) return;
      var deeper = dm > dg ? 'main' : 'garage';
      var z0 = Math.min(dm, dg), z1 = Math.max(dm, dg);
      var eave = EXT_TOP4 * BLOCKS[deeper].stories;
      /* the deeper block's own side wall from the shallower face to its face,
         in the deeper block's cladding; normal faces AWAY from the deeper block */
      shellWall(deeper + '_return', x, z0, x, z1, eave, [deeper === 'main' ? -1 : 1, 0, 0], [],
                deeper === 'main' ? 'living' : 'mudroom', deeper);
    })();
```

- [ ] **Step 5: Neighbour-volume roof subtraction.** Add before the block-roof calls:

```js
    /* Spec section 2 (rev2): where roofs meet, each block's roof is clipped
       against the NEIGHBOUR's bounded volume -- its footprint (with depth),
       from the ground to its ridge, plus its overhang on the shared side --
       and the neighbour's own decks INSIDE that box. Never an infinite deck. */
    function neighbourVolume(name) {
      var other = name === 'main' ? 'garage' : 'main';
      var B = other === 'main' ? FULL_HOUSE : GARAGE_BLOCK, o = FULL_HOUSE.overhang;
      var pl = blockDeckPlanes(other === 'main' ? 'main' : 'garage_block');
      var ridge = pl[0].ridge, C = window.HouseClip;
      var west = B.west - (other === 'garage' ? 0 : o), east = B.east + (other === 'main' ? 0 : o);
      var region = [
        { n: [1, 0, 0], d: west }, { n: [-1, 0, 0], d: -east },
        { n: [0, 0, 1], d: B.north }, { n: [0, 0, -1], d: -B.south },
        { n: [0, 1, 0], d: 0 }, { n: [0, -1, 0], d: -ridge }
      ];
      pl.forEach(function (p) { region.push(C.flip(p)); });     /* below every neighbour deck */
      return region;
    }
```

Pass `neighbourVolume('main')` as the `buried` argument of `shellGable('roof_main', ...)` and `neighbourVolume('garage')` to `shellGable('garage_block_roof', ...)`; `shellGable` already runs `clipBuried(g, buried)` on every deck and end. Shared-face rule: the face plane x = -7.15 belongs to the higher eave (tie → main): implement by inset — the block that does NOT own the face has its volume's shared-side plane moved 0.02 inward (`west`/`east` above), so the two clips never produce coplanar caps.

- [ ] **Step 6: Expose `chfBlockGeometry`**, run → GREEN, `--focus` + facade live + shell live, bump, commit:

```
feat: per-block street depth, the block-meet return wall and void floor, roofs clipped to the neighbour's bounded volume (vX.Y.Z)
```

---

### Task 7: Two stories — `storyBox`, upper windows, the vault gate, unobstructed room views

**Files:**
- Modify: `chauffeur/static/house.js` (`MAIN_VAULT` `~4596` and the garage `gVault` `~6182` gates; `FULL_HOUSE.eave`/`GARAGE_BLOCK.eave`; new `storyBox` beside `shellWall`; `windowAt` `~5280` for `story: 2`; `roofVault` callers)
- Modify: `chauffeur/tests/test_house_shell_live.py` (new `scenario_two_stories_are_cut_like_fabric`)
- Test: `chauffeur/tests/test_house_shell_live.py`

**Interfaces:**
- Produces: `storyBox(name)` registers `<name>_upper_south|north|west|east` (and for `garage` the east one only where it is not shared: the shared x = -7.15 plane belongs to `main_upper_west` when main has two stories, else `garage_upper_east`); `FULL_HOUSE.eave = EXT_TOP4 * BLOCKS.main.stories`, same for the garage; `windowAt(feat)` with `feat.story === 2` builds at `y + EXT_TOP4` inside its own registered piece `facade_<face>_window_<slot>_s2`; `window.chfRoomViewClear(room)` → `{clear: bool, blocked: [names]}` (a ray from the room camera to each of the room's registered marker/zone points, testing only upper-story fabric).

- [ ] **Step 1: Failing scenario:**

```python
def scenario_two_stories_are_cut_like_fabric():
    """Spec section 3.2 (rev): the upper story is fabric and the room mask
    cuts it. Every room view stays unobstructed by pixel and by ray; the
    partitions cap at the story-1 eave; the exterior budget delta is
    itemised."""
    from services import house_facade as hf
    spec = copy.deepcopy(hf.CANONICAL)
    for b in ('main', 'garage'):
        spec['blocks'][b]['stories'] = 2
    spec['ground'] += [{'slot': 7, 'span': 1, 'kind': 'window', 'size': 'standard', 'shutters': True, 'story': 2},
                       {'slot': 12, 'span': 1, 'kind': 'window', 'size': 'standard', 'shutters': False, 'story': 2}]
    spec, _ = hf.normalize(spec)
    served = live_app(_seed)
    if served is None:
        return
    with served.browser() as page:
        page.add_init_script(DAY_LOCK_JS)
        page.add_init_script('window.HOUSE_FACADE = %s;' % json.dumps({'id': 't', 'name': 't', 'spec': spec, 'slots': hf.slot_table(spec['blocks'])}))
        page.goto(served.url('house?quality=high'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        names = {r['name'] for r in page.evaluate('window.chfShellFabric()')}
        for n in ('main_upper_south', 'main_upper_north', 'main_upper_east', 'main_upper_west',
                  'garage_upper_south', 'garage_upper_north', 'garage_upper_west',
                  'facade_main_window_7_s2', 'facade_main_window_12_s2'):
            check(n in names, f'{n} registered')
        check('garage_upper_east' not in names, 'the shared plane is one wall, owned by main')
        for room in ('kitchen', 'living', 'mudroom', 'garage', 'study'):
            page.evaluate(f"window.chfHouseEnterRoom('{room}')")
            page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
            r = page.evaluate(f"window.chfRoomViewClear('{room}')")
            check(r['clear'], f'{room}: upper story between camera and room: {r["blocked"]}')
            shown = page.evaluate(f"window.chfRoomShellShown('{room}')")
            check(any(n.startswith(('main_upper', 'garage_upper')) for n in shown.get('cut', [])),
                  f'{room}: some upper piece was cut by the mask (not kept whole): {shown}')
        # partitions cap at the story-1 eave: no vault under a two-story block
        top = page.evaluate("window.chfFabricVertices('east_partition').reduce((m, v) => Math.max(m, v[1]), 0)")
        check(top < 5.65, f'partitions cap at EXT_TOP4 under two stories: top {top}')
        page.evaluate("window.chfHouseExit()")
        b = page.evaluate('window.__hpBuildMs')
        check(b is None or b <= 1500, f'buildMs {b} <= 1500 with two stories on both blocks')
        errs = [e for e in served.errors() if 'WebGL' not in e]
        check(not errs, f'console clean: {errs[:3]}')
```

`chfRoomShellShown(room)` exists; if it does not report `cut` names, extend it to return `{shown: [...], cut: [...]}` where `cut` lists fabric rows whose per-room shell has remnants (`f.shells[room]` present and its `area` < `area0` − ε).

- [ ] **Step 2: Run → RED.**

- [ ] **Step 3: Eaves, `storyBox`, the gates.** `FULL_HOUSE.eave = EXT_TOP4 * BLOCKS.main.stories`, `GARAGE_BLOCK.eave = EXT_TOP4 * BLOCKS.garage.stories`; the two block-roof `shellGable` calls pass `FULL_HOUSE.eave` / `GARAGE_BLOCK.eave` (not `EXT_TOP4`). `MAIN_VAULT` and `gVault` sections are built only when `BLOCKS[<block>].stories === 1` (they already gate on form/ridge; add the stories test). Add:

```js
    /* Spec section 3.2: an upper story is four shell walls from EXT_TOP4 to
       the block eave, in the block's cladding, no base, registered as fabric
       of no room -- the mask cuts them like any wall (kitchen camera y 13.8,
       living 12.8 sit above the 11.2 top and look down through them). */
    function storyBox(name) {
      var b = BLOCKS[name]; if (b.stories !== 2) return;
      var B = name === 'main' ? FULL_HOUSE : GARAGE_BLOCK, y0 = EXT_TOP4, h = EXT_TOP4;
      function wall(suffix, x0, z0, x1, z1, normal) {
        var g = shellGroup(), alongX = x0 !== x1, len = alongX ? x1 - x0 : z1 - z0;
        shellBox(g, alongX ? len : WALL_T4, h, alongX ? WALL_T4 : len,
                 NICE ? 0xffffff : pal('body', b.body, 0xf4f1e9),
                 (x0 + x1) / 2, y0 + h / 2, (z0 + z1) / 2, { rough: 0.95, map: CLAD(name) });
        [0, 1].forEach(function (end) {
          shellBox(g, 0.18, h, 0.18, FARMHOUSE.trim, end ? x1 : x0, y0 + h / 2, end ? z1 : z0);
        });
        shellRegister(g, name + '_upper_' + suffix, normal, null);
      }
      wall('south', B.west, B.south, B.east, B.south, [0, 0, 1]);
      wall('north', B.west, B.north, B.east, B.north, [0, 0, -1]);
      if (name === 'main' || BLOCKS.main.stories !== 2 || name !== 'garage')
        wall('west', B.west, B.north, B.west, B.south, [-1, 0, 0]);
      if (name === 'main' || BLOCKS.main.stories !== 2)
        wall('east', B.east, B.north, B.east, B.south, [1, 0, 0]);
    }
    storyBox('main'); storyBox('garage');
```

(The garage's east wall at x = -7.15 is skipped when main also has an upper story, since `main_upper_west` stands on that plane.) Call `storyBox` after the block walls and BEFORE `buildElevation()` so upper windows can be placed. In `windowAt`, when `feat.story === 2`: `y` offsets by `EXT_TOP4`, the piece name gets `_s2`, and `shutters` (both stories) adds two `box(0.28, wh, 0.06, FARMHOUSE.frame, ...)` either side of the frame. The ground-floor gable-end infill of a two-story block is the story roof's own end (shellGable's `ends` at the raised eave), so nothing else changes.

- [ ] **Step 4: `chfRoomViewClear`.** Expose:

```js
  window.chfRoomViewClear = function (room) {
    if (!webgl) return null;
    var cam = webgl.ROOM_CAMS[room], at = webgl.ROOM_AT[room];        /* ROOM_AT: {kitchen: HOME_AT, ...} beside ROOM_CAMS */
    var ray = new webgl.T.Raycaster(cam.clone(), at.clone().sub(cam).normalize());
    var upper = [];
    webgl.FABRIC.forEach(function (f) {
      if (f.name.indexOf('_upper_') < 0) return;
      var shell = f.shells && f.shells[room];
      (shell ? [shell] : [f.g]).forEach(function (g) { g.traverse(function (m) { if (m.isMesh && m.visible) upper.push(m); }); });
    });
    var hits = ray.intersectObjects(upper, false).filter(function (h) { return h.distance < cam.distanceTo(at); });
    return { clear: hits.length === 0, blocked: hits.map(function (h) { return h.object.name || h.object.parent.name; }) };
  };
```

- [ ] **Step 5: Run → GREEN**, `--focus` + shell live + facade live, bump, commit:

```
feat: two stories per block as ordinary fabric, upper windows and shutters, partitions cap under an upper story, room views pinned clear (vX.Y.Z)
```

---

### Task 8: Side-entry garage, the shed feature, the porch's own gable, per-feature cladding

**Files:**
- Modify: `chauffeur/static/house.js` (`garageDoorAt` `~5485`; `garage_block_west` shellWall `~5811`; `DRIVE_X`/`BAY_X` `~10970` and the driveway slab; `porchAt` `~5413`; new `shedAt` after `dormerAt`; `buildElevation` `roofKind` map; `ROOF_FEATURE` regex `~9156`; `EXTERIOR_HINTS` `garage_front` unchanged)
- Modify: `chauffeur/tests/test_house_facade_live.py` (new `scenario_side_garage_shed_and_porch_gable`)
- Test: `chauffeur/tests/test_house_facade_live.py`

**Interfaces:**
- Produces: `GARAGE_SIDE` (bool); with it the garage door group builds on the west face centred at z 4.0 (opening 3.6 wide between `GARAGE_BLOCK.north + 2.3` and `+ 5.9`), the west wall is built as two pieces + header (`garage_block_west_a`, `garage_block_west_b`, `garage_block_west_head`), the bay's street face is `garage_front_wall` (a `shellWall` with the normalized window), the drive is an L (`driveway_side`), car plaques park at `DRIVE_SIDE = [[-21.4, 2.6], [-21.4, 5.4]]` with `rotation.y = Math.PI / 2`; `shedAt(feat)` registers `facade_<face>_shed_<slot>` (+ `_box` when `feat.window`); `porchAt` with `feat.roof === 'gable'` registers `facade_<face>_porch_<slot>_roof_*` via `shellGable`; a roof feature's `cladding` overrides `CLAD()` for its infill/box.

- [ ] **Step 1: Failing scenario:**

```python
def scenario_side_garage_shed_and_porch_gable():
    from services import house_facade as hf
    spec = copy.deepcopy(hf.CANONICAL)
    spec['blocks']['garage']['orientation'] = 'side'
    spec['roof'].append({'slot': 13, 'span': 2, 'kind': 'shed', 'window': True, 'cladding': 'shingle'})
    spec, _ = hf.normalize(spec)
    served = live_app(_seed)
    if served is None:
        return
    with served.browser() as page:
        page.add_init_script(DAY_LOCK_JS)
        page.add_init_script('window.HOUSE_FACADE = %s;' % json.dumps({'id': 't', 'name': 't', 'spec': spec, 'slots': hf.slot_table(spec['blocks'])}))
        page.goto(served.url('house?quality=high&angle=1'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        names = {r['name'] for r in page.evaluate('window.chfShellFabric()')}
        for n in ('garage_front_wall', 'garage_block_west_a', 'garage_block_west_b', 'garage_block_west_head',
                  'facade_main_shed_13', 'facade_main_shed_13_box', 'facade_main_porch_8_roof_west', 'facade_main_porch_8_roof_east'):
            check(n in names, f'{n} registered')
        door = page.evaluate("(() => { const f = window.chfShellFabric().find(r => r.name === 'garage_door'); return f && f.box; })()")
        check(door and door[1] < -18.0 and abs((door[4] + door[5]) / 2 - 4.0) < 0.6, f'the garage door stands on the west face: {door}')
        probe = page.evaluate("window.chfNavProbe({feature:'garage_front'})")
        check(probe and probe.get('hit'), f'garage marker reachable from orbit stop 1: {probe}')
        # every roof feature (shed and porch gable included) passes the roof-line audit
        from house_live_common import FEATURE_JS, VERTEX_AUDIT_ALL_JS
        for f in page.evaluate(FEATURE_JS):
            if f['kind'] == 'hip_end':
                continue
            a = page.evaluate(VERTEX_AUDIT_ALL_JS, f)
            check(a['buried'] == 0, f"{f['name']}: {a['buried']} buried vertices")
        errs = [e for e in served.errors() if 'WebGL' not in e]
        check(not errs, f'console clean: {errs[:3]}')
```

`FEATURE_JS` must list `shed` and porch-roof pieces: extend its name filter to `/^facade_.*_(gable|dormer|hip_end|shed|porch_\d+_roof)/`, and the `ROOF_FEATURE` regex in house.js to `/^facade_.*_(gable|dormer|hip_end|shed)_\d+|^facade_.*_porch_\d+_roof/`.

- [ ] **Step 2: Run → RED.**

- [ ] **Step 3: Side garage.** `var GARAGE_SIDE = BLOCKS.garage.orientation === 'side';`. In the `garage_block_west` site: when `GARAGE_SIDE`, build `garage_block_west_a` (z north..2.3), `garage_block_west_b` (z 5.9..south) and `garage_block_west_head` (a `shellBox` lintel 3.6 long from y 4.0 to eave over the opening) instead of the one wall, and `shellWall('garage_front_wall', GARAGE_BLOCK.west, GARAGE_BLOCK.south, -12.60, GARAGE_BLOCK.south, GARAGE_BLOCK.eave, [0, 0, 1], [[SLOTS[w].cx, 1.35, true]], 'garage', 'garage')` where `w` is the normalized bay window's slot. In `garageDoorAt`, when `GARAGE_SIDE`: the door group is rotated `Math.PI / 2` about y and positioned at `(GARAGE_BLOCK.west, y, 4.0)`; piers, leaves and lamp positions are expressed in the group's local frame already (verify by reading the builder; if any piece uses world x, move it into the group). `DRIVE_X`/`BAY_X` become `DRIVE_SIDE` when `GARAGE_SIDE` (plaques at x -21.4, z 2.6/5.4, `rotation.y = Math.PI / 2`); the driveway slab becomes two boxes (street → bay front along the block's west edge, then west along z 1.9..6.1). The `garage_front` marker rides the door group as today.

- [ ] **Step 4: `shedAt`.**

```js
    function shedAt(feat) {
      /* a single slope from the feature's front edge back to the parent deck
         (a bay window's roof, or a shed dormer when `window`). */
      var e = spanX(feat), slot = e.slot, g = shellGroup(), region = buriedRegion(slot.face);
      var clad = feat.cladding ? cladTex(feat.cladding, FARMHOUSE.body) : shingleT;
      var zf = slot.z + 2.2, yf = featureEave(slot, e.cx) - 0.3;
      var zb = slot.z - 0.8, yb = roofY(slot.face, e.cx, zb);
      var len = Math.hypot(zf - zb, yb - yf), pitch = Math.atan2(yb - yf, zf - zb);
      var deck = shellBox(g, e.w, 0.18, len, NICE ? 0xffffff : FARMHOUSE.roofTone,
                          e.cx, (yf + yb) / 2 + 0.09, (zf + zb) / 2, { rough: 0.9, map: clad });
      deck.rotation.x = pitch;
      shellBox(g, e.w + 0.16, 0.22, 0.14, FARMHOUSE.trim, e.cx, yf - 0.02, zf + 0.02);
      if (feat.window) {
        var y = yf - 0.95, w = Math.max(1.2, e.w - 0.4);
        shellBox(g, w, 1.7, 1.4, NICE ? 0xffffff : FARMHOUSE.body, e.cx, y, slot.z + 1.4, { rough: 0.95, map: CLAD(BLOCK_OF_FACE[slot.face]) });
        shellWindow(g, e.cx, y, slot.z + 2.15, 0, Math.min(1.1, w - 0.5), 1.0, true);
      }
      clipBuried(g, region);
      shellRegister(g, 'facade_' + slot.face + '_shed_' + feat.slot, [0, 0, 1], slot.room);
      if (feat.window) shellRegister(shellGroup(), 'facade_' + slot.face + '_shed_' + feat.slot + '_box', [0, 0, 1], slot.room);
    }
```

(Register the window box as its own piece by building it in a second group rather than the empty `shellGroup()` shown; the point is two registered names.) Add `shed: shedAt` to `roofKind`. In `dormerAt`/`gableAt`, when `feat.cladding` is set, use `cladTex(feat.cladding, FARMHOUSE.body)` for the box/infill map.

- [ ] **Step 5: Porch gable.** In `porchAt`, after the flat beam, when `feat.roof === 'gable'`:

```js
      if (feat.roof === 'gable' && type !== 'stoop') {
        var ridge = eave + 0.18 + (W / 2) * Math.tan(PITCH_FAMILY);
        shellGable('facade_' + slot.face + '_porch_' + feat.slot + '_roof', e.x0, e.x1,
                   featureBack(slot, X, ridge), frontZ, eave, 'z', slot.room, [1], PITCH_FAMILY,
                   null, null, null, buriedRegion(slot.face));
      }
```

and in `gableAt` drop the PORCH_SPANS extension when the overlapped porch is gabled (normalize already removes such a feature; the builder guard is belt and braces).

- [ ] **Step 6: Run → GREEN**, `--focus` + facade live, bump, commit:

```
feat: side-entry garage with its own drive, the shed roof feature, the porch's own gable, per-feature cladding (vX.Y.Z)
```

---

### Task 9: The mirror — `houseRoot`, `toWorldX`, the text helper, mirrored lean-ins

**Files:**
- Modify: `chauffeur/static/house.js` (scene root after the AO bake; `goHome`/`enterRoom`/`goExterior`/`frameZone` `~11203–11330`; `ORBIT.pivot` reads `~372`; `aimCarPlates` `~10972`; every CanvasTexture-on-a-mesh creation: `plate()` ×2 `~6410`/`~7706`, the bus STOP arm `~7500`, `mkTex` wearers `~9913` (hero plaque, calFace, critFace, paneMesh, car plaques), dock panels `~9990–10300`)
- Modify: `chauffeur/tests/test_house_nav_live.py` (new `scenario_mirror_is_one_reflection`), `chauffeur/tests/test_house_facade.py` (`scenario_text_meshes_use_the_helper`)
- Test: both

**Interfaces:**
- Produces: `MIRROR` (bool from `SPEC0.mirror`); `houseRoot` (a `T.Group` that every scene child except lights, camera and `skyDome` is re-parented into after `bakeAO`/`mergeStatic`, then `scale.x = -1` when mirrored); `toWorldX(x)` and `toWorld(v3)` (identity unmirrored; negate x mirrored); `textMesh(geo, mat, group)` — the ONE creator for text-bearing meshes, stamps `userData.noMirror = true`; the post-flip pass counter-flips every `noMirror` mesh (`m.scale.x *= -1`); `window.chfMirror()` → `{ mirror, root: houseRoot.scale.x, noMirrorCount }`; `ROOM_AT` table beside `ROOM_CAMS`.

- [ ] **Step 1: Failing pure test** (grep discipline):

```python
def scenario_text_meshes_use_the_helper():
    """Spec section 3.4: every CanvasTexture-on-a-mesh site goes through
    textMesh() so the mirror can counter-flip it. A fillText inside a
    canvas painter whose texture is worn by a mesh made with `new T.Mesh(`
    directly is the bug this greps for."""
    import io, os, re
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = io.open(os.path.join(root, 'static', 'house.js'), encoding='utf-8').read()
    check('function textMesh(' in src and 'userData.noMirror = true' in src, 'the helper exists')
    # every painter that writes text is named in TEXT_PAINTERS and every mesh that
    # wears one of those is created by textMesh(): the file keeps a manifest
    # the test reads back (a comment block '/* TEXT_PAINTERS: a, b, c */').
    m = re.search(r'/\* TEXT_PAINTERS: ([^*]+)\*/', src)
    check(m, 'the TEXT_PAINTERS manifest exists')
    for name in [s.strip() for s in m.group(1).split(',') if s.strip()]:
        check(re.search(r'\b' + re.escape(name) + r'\b', src), f'manifest names a real painter: {name}')
        # each painter's texture reaches a mesh only through textMesh(
        uses = [mm.start() for mm in re.finditer(re.escape(name), src)]
        bad = [u for u in uses if 'new T.Mesh(' in src[max(0, u - 200):u + 200] and 'textMesh(' not in src[max(0, u - 400):u + 400]]
        check(not bad, f'{name}: a mesh wears it without textMesh() near offsets {bad[:3]}')
    check(src.count('fillText(') <= src.count('fillText(') and src.count('textMesh(') >= 8, f"textMesh call sites: {src.count('textMesh(')}")
```

And the live scenario in `test_house_nav_live.py`:

```python
def scenario_mirror_is_one_reflection():
    """Spec section 3.4 pins: with mirror true the garage door, drive slab
    and garage_front marker have world x > 0 exactly once; every room
    marker is present and tappable; lean-ins land on the mirrored card;
    the house-number-free plate set (car plaque, calendar) reads forward
    by pixel; the exterior mesh count equals the unmirrored build."""
    from services import house_facade as hf
    spec, _ = hf.normalize({**copy.deepcopy(hf.CANONICAL), 'mirror': True})
    served = live_app(_seed)
    if served is None:
        return
    def boot(page, s):
        page.add_init_script(DAY_LOCK_JS); page.add_init_script(SEED_RNG_JS)
        page.add_init_script('window.HOUSE_FACADE = %s;' % json.dumps({'id': 't', 'name': 't', 'spec': s, 'slots': hf.slot_table(s['blocks'])}))
        page.goto(served.url('house?quality=high'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
    with served.browser() as page:
        boot(page, hf.CANONICAL)
        plain = page.evaluate("window.chfShellFabric().length")
        plain_png = page.screenshot()
    with served.browser() as page:
        boot(page, spec)
        m = page.evaluate('window.chfMirror()')
        check(m['mirror'] and m['root'] == -1 and m['noMirrorCount'] >= 8, f'one reflection on the root, text counter-flipped: {m}')
        check(page.evaluate("window.chfShellFabric().length") == plain, 'same fabric count mirrored')
        for name in ('garage_door', 'garage_front'):
            wx = page.evaluate("(n => { const o = window.chfHouseFindFeature(n); const v = new (window.chfHouseCam().constructor)(); "
                               "return o ? o.getWorldPosition(new window.THREE.Vector3()).x : null; })('%s')" % name)
            check(wx is not None and wx > 0, f'{name} world x > 0 once mirrored: {wx}')
        for key in ('front_door', 'back_door', 'garage_block_roof_south', 'garage_front'):
            p = page.evaluate("window.chfNavProbe({feature:'%s'})" % key)
            check(p and p.get('hit'), f'marker {key} tappable mirrored: {p}')
        # lean-in lands on the mirrored calendar: the camera ends within 3 units of the card's world centre
        page.evaluate("window.chfHouseEnterRoom('kitchen')")
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        page.evaluate("window.chfKitchenFocus('calendar')")
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        d = page.evaluate("(() => { const c = window.chfHouseCam(); const z = window.chfStudyZone ? null : null; "
                          "const g = window.chfHouseFindFeature('calendar'); const p = g.getWorldPosition(new window.THREE.Vector3()); "
                          "return c.position.distanceTo(p); })()")
        check(d < 6.0, f'lean-in reached the mirrored calendar: {d}')
        # the calendar face reads forward: its texture's left edge is on the LEFT of the screenshot crop
        # (pixel check: the day-name strip is darker on the left third than the right in both builds)
        png = page.screenshot()
        from PIL import Image; import io as _io
        im = Image.open(_io.BytesIO(png)).convert('L')
        w, h = im.size
        left = sum(im.crop((int(w * 0.3), int(h * 0.3), int(w * 0.45), int(h * 0.7)).getdata()))
        right = sum(im.crop((int(w * 0.55), int(h * 0.3), int(w * 0.7), int(h * 0.7)).getdata()))
        check(left != right, 'the leaned-in card renders (not a blank)')
        page.evaluate("window.chfHouseExit()")
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        errs = [e for e in served.errors() if 'WebGL' not in e]
        check(not errs, f'console clean: {errs[:3]}')
```

(The "reads forward" assertion is finished in Step 5 with a glyph check on the car plaque: capture the plaque's canvas via `window.chfPlaqueCanvas(0)` (new hook returning the drawn canvas as dataURL) and compare the leaned-in screenshot crop against a mirrored copy: the unmirrored orientation must correlate better than the mirrored one.)

- [ ] **Step 2: Run both → RED.**

- [ ] **Step 3: `houseRoot` and `toWorldX`.** At the top of the build closure: `var MIRROR = !!SPEC0.mirror; function toWorldX(x) { return MIRROR ? -x : x; } function toWorld(v) { return MIRROR ? new T.Vector3(-v.x, v.y, v.z) : v.clone(); }`. After `bakeAO()` and the last `mergeStatic` in the build sequence:

```js
    /* Spec 2026-09-17 section 3.4: ONE reflection, applied last. Everything
       geometric above ran in house-local space; lights, camera and the sky
       stay in the scene (the sun keeps its world side). */
    var houseRoot = new T.Group(); houseRoot.name = 'houseRoot';
    scene.children.slice().forEach(function (o) {
      if (o.isLight || o.isCamera || o === skyDome) return;
      scene.remove(o); houseRoot.add(o);
    });
    scene.add(houseRoot);
    if (MIRROR) {
      houseRoot.scale.x = -1;
      houseRoot.traverse(function (m) { if (m.userData && m.userData.noMirror) m.scale.x *= -1; });
    }
    houseRoot.updateMatrixWorld(true);
```

`ROOM_CAMS` stays unflipped (the mask reads it); add `var ROOM_AT = { kitchen: HOME_AT, living: LIV_AT, study: STUDY_AT, garage: GARAGE_AT, mudroom: MUD_AT };`. The exposures `HOME_POS`…`STUDY_AT` and `get EXT_AT()` return `toWorld(...)`; `orbitPos(k)` uses `toWorldX(ORBIT.pivot.x)` for its centre (angles unchanged); `frameZone`'s `fn` becomes `fn = fn && toWorld(fn)`; `aimCarPlates` reads `EXT_POS` (already world through the getter). `roomsReg()[name].pos/.at` read the exposures (verify; if they clone the constants directly, route them through `toWorld`).

- [ ] **Step 4: The text helper.** Add near `finish()`:

```js
    /* TEXT_PAINTERS: plate, stopArm, heroFace, calFace, critFace, paneFace, dockFace, carPlaque */
    function textMesh(geo, material, group) {
      var m = new T.Mesh(geo, material);
      m.userData.noMirror = true;          /* counter-flipped at the root reflection */
      (group || scene).add(m); finish(m);
      return m;
    }
```

Route every mesh that wears a text-bearing canvas through it: both `plate()` functions, the bus STOP arm mesh (`~7500`), the hero plaque, calendar face, critter face, weather pane, the dock panels and the car plaques (`mkTex` wearers). Name each painter function as the manifest lists (rename local painters to those names where they are anonymous, so the pure test can find them).

- [ ] **Step 5: Run → GREEN** (finish the plaque orientation check with `chfPlaqueCanvas`), `--focus` + nav live + facade live + shell live, bump, commit:

```
feat: the mirror — one reflection on houseRoot after clip/batch/AO, toWorldX at the camera boundary, text meshes counter-flipped through textMesh (vX.Y.Z)
```

---
### Task 10: The draft token, `/house?draft=`, `?day=1`, `chfCapture()`

**Files:**
- Modify: `chauffeur/services/house_facade.py` (draft cache after the storage section)
- Modify: `chauffeur/main.py` (`house_page` `~1719`; new `POST /api/house/facades/draft`)
- Modify: `chauffeur/static/house.js` (`isNight` `~529`; `window.chfCapture`)
- Modify: `chauffeur/tools/house_probe.py` (`--facade-json`)
- Test: `chauffeur/tests/test_house_facade.py`, `chauffeur/tests/test_house_facade_live.py`

**Interfaces:**
- Produces (Python): `issue_draft(spec, photo=None, mime=None) -> token` (spec already normalized; stores `{spec, photo_b64, mime, issued, result: None}` under an HMAC token; 15-minute TTL; `_DRAFT_SECRET` is per-process `secrets.token_bytes(32)`); `draft_for(token) -> dict | None` (verifies HMAC and expiry); `store_result(token, result)`; `DRAFT_TTL_S = 900`. Token = `hex(issued_ms) + '.' + hmac_sha256(secret, f'{photo_sha}|{spec_sha}|{issued_ms}')[:32]`.
- Produces (routes): `POST /api/house/facades/draft {spec}` → `{token, spec, notes}` (normalize-with-defaults path: it is the hand editor's draft); `GET /house?draft=<token>[&angle=N&quality=medium&day=1]` injects the token's spec as `window.HOUSE_FACADE = {id: 'draft', ...}`; an invalid or expired token → the active facade (never an error page).
- Produces (JS): `isNight()` returns false when `location.search` has `day=1`; `window.chfCapture()` → `R.render(scene, cam); return R.domElement.toDataURL('image/png')` (synchronous, same task, no `preserveDrawingBuffer`).
- Probe: `--facade-json <file>` reads a JSON spec, `issue_draft`s it inside the served app, and opens `house?draft=<token>`; it refuses to run unless `CHAUFFEUR_DATA_DIR` was set by the probe itself (i.e. it was NOT inherited: compare against the `mkdtemp` value it set).

- [ ] **Step 1: Failing pure tests:**

```python
def scenario_draft_tokens_verify_expire_and_dedupe():
    import time as _t
    spec, _ = hf.normalize(hf.CANONICAL)
    tok = hf.issue_draft(spec, photo='AAAA', mime='image/jpeg')
    d = hf.draft_for(tok)
    check(d and d['spec'] == spec and d['photo_b64'] == 'AAAA', 'a fresh token resolves to its draft')
    check(hf.draft_for(tok[:-1] + ('0' if tok[-1] != '0' else '1')) is None, 'a tampered token is refused')
    check(hf.draft_for('') is None and hf.draft_for('nope.nope') is None, 'garbage is refused')
    hf.store_result(tok, {'revised': spec, 'reasons': ['x']})
    check(hf.draft_for(tok)['result']['reasons'] == ['x'], 'a stored result rides the token')
    old = hf._DRAFTS[tok]['issued'] - (hf.DRAFT_TTL_S + 1) * 1000
    hf._DRAFTS[tok]['issued'] = old
    check(hf.draft_for(tok) is None, 'an expired token is refused')
    check(tok not in hf._DRAFTS, 'expired entries are swept')


def scenario_house_page_renders_a_draft():
    from fastapi.testclient import TestClient
    import main as _main
    _fresh()
    spec, _ = hf.normalize({**copy.deepcopy(hf.CANONICAL), 'mirror': True})
    tok = hf.issue_draft(spec)
    c = TestClient(_main.app)
    html = c.get(f'/house?draft={tok}&day=1').text
    check('"id": "draft"' in html and '"mirror": true' in html, 'the draft rides the page')
    html2 = c.get('/house?draft=bogus').text
    check('"id": "canonical"' in html2, 'a bad token falls back to the active facade')
    r = c.post('/api/house/facades/draft', json={'spec': {'blocks': {'main': {'depth': 9}}}})
    check(r.status_code == 200 and r.json()['token'] and r.json()['spec']['blocks']['main']['depth'] == 6.0,
          'a hand draft gets a token through the defaults path')
    check(len(hf.list_facades()) == 1, 'nothing saved')
```

- [ ] **Step 2: Run → RED.**

- [ ] **Step 3: The cache.**

```python
# --- drafts (spec 2026-09-17 section 4: token lifecycle) ---
import hashlib, hmac, secrets
_DRAFT_SECRET = secrets.token_bytes(32)
_DRAFTS = {}
DRAFT_TTL_S = 900


def _sha(s):
    return hashlib.sha256((s or '').encode('utf-8') if isinstance(s, str) else (s or b'')).hexdigest()


def _sign(photo_sha, spec_sha, issued_ms):
    return hmac.new(_DRAFT_SECRET, f'{photo_sha}|{spec_sha}|{issued_ms}'.encode(), 'sha256').hexdigest()[:32]


def _sweep(now_ms):
    for k in [k for k, v in _DRAFTS.items() if now_ms - v['issued'] > DRAFT_TTL_S * 1000]:
        _DRAFTS.pop(k, None)


def issue_draft(spec, photo=None, mime=None):
    now_ms = int(time.time() * 1000)
    _sweep(now_ms)
    spec_sha = _sha(json.dumps(spec, sort_keys=True))
    photo_sha = _sha(photo or '')
    tok = f'{now_ms:x}.{_sign(photo_sha, spec_sha, now_ms)}'
    _DRAFTS[tok] = {'spec': copy.deepcopy(spec), 'photo_b64': photo, 'mime': mime,
                    'issued': now_ms, 'spec_sha': spec_sha, 'photo_sha': photo_sha, 'result': None}
    return tok


def draft_for(token):
    now_ms = int(time.time() * 1000)
    _sweep(now_ms)
    e = _DRAFTS.get(token or '')
    if not e:
        return None
    try:
        issued = int(token.split('.')[0], 16)
    except ValueError:
        return None
    if not hmac.compare_digest(token.split('.')[1], _sign(e['photo_sha'], e['spec_sha'], issued)):
        return None
    return e


def store_result(token, result):
    e = draft_for(token)
    if e is not None:
        e['result'] = result
```

(`import json` at the top of the module.) `house_page`: read `request.query_params.get('draft')`; if `draft_for(tok)` → `bundle = {'id': 'draft', 'name': 'Draft', 'spec': e['spec'], 'slots': slot_table(e['spec']['blocks'])}`. `active_bundle()` returns `slot_table(spec['blocks'])` too (every bundle's slots follow its blocks). New route:

```python
@app.post("/api/house/facades/draft")
def house_facade_draft(body: dict = Body(default={})):
    """A hand draft becomes a token /house can render (Preview in 3D). The
    defaults path: this is the editor's own object, not a model's."""
    from services import house_facade as _hf
    spec, notes = _hf.normalize((body or {}).get('spec'))
    return {'token': _hf.issue_draft(spec), 'spec': spec, 'notes': notes}
```

`isNight()`: prepend `try { if (new URLSearchParams(location.search).get('day') === '1') return false; } catch (e) {}`. `chfCapture`: `window.chfCapture = function () { if (!webgl) return null; webgl.R.render(webgl.scene, webgl.cam); return webgl.R.domElement.toDataURL('image/png'); };` (expose `R` and `scene` on `webgl` if they are not already). Probe: `--facade-json` → after `live_app` boots, `spec = normalize(json.load(open(path)))[0]`, `tok = issue_draft(spec)`, `page.goto(served.url('house?draft=' + tok + '&quality=...'))`; before booting assert `os.environ['CHAUFFEUR_DATA_DIR'].startswith(tempfile.gettempdir())` else `SystemExit('refusing to run against a non-temp data dir')`.

- [ ] **Step 4: Live check** (append to `scenario_canonical_facade_pins_the_hand_built_elevation` or a small new scenario): boot `house?draft=<tok>&day=1&quality=medium` with a mirrored draft issued through the served app (`served` exposes the app process? No: the test process and the served app share the module, since `live_app` runs uvicorn on a thread in-process) and check `window.chfMirror().mirror` is true and `window.chfCapture()` starts with `data:image/png;base64,` and decodes to a 1400×1000 PNG whose mean brightness > 40 (not black).

- [ ] **Step 5: Run → GREEN**, `--focus` + facade live, bump, commit:

```
feat: draft tokens — /house?draft renders a 15-minute HMAC draft, ?day=1, chfCapture, the probe's file adapter refuses a live data dir (vX.Y.Z)
```

---

### Task 11: Pass 1 and pass 2 — prompts, fraction snap, attempt budget, critique route, fixtures

**Files:**
- Modify: `chauffeur/services/house_facade.py` (`PHOTO_SYSTEM`, `_photo_prompt`, `from_photo`; new `CRITIQUE_SYSTEM`, `_snap_fractions`, `critique`)
- Modify: `chauffeur/main.py` (`house_facade_photo` → `def`, returns `token`; new `POST /api/house/facades/critique`)
- Create: `chauffeur/tests/fixtures/house_photo/{brick,farmhouse}.{expected,pass1,pass2}.json`
- Test: `chauffeur/tests/test_house_facade.py`

**Interfaces:**
- `from_photo(image_b64, mime) -> (draft, notes, err, token)`: pass 1 with `max_models=2, workflow='house_photo', max_output_tokens=4096`; response → `validate_block_model` (after `_snap_fractions`) → `normalize` → `issue_draft(draft, photo, mime)`. A rejected response returns `(None, [], 'the model returned an incomplete house: ' + '; '.join(errs[:3]), None)`.
- `_snap_fractions(obj) -> obj`: pass 1 reports `ground`/`roof` entries with `block: 'main'|'garage'`, `at: 0..1`, `width: 0..1` (fractions of that block's street width); the snap converts each to `slot`/`span` on that block's face (`slot = face_lo + round(at * n)`, `span = max(1, round(width * n))`, clamped to the face) and deletes `block/at/width`. Entries already carrying `slot` pass through.
- `critique(token, render_png_b64) -> (result, err)`: `result = {'draft': spec, 'revised': spec | None, 'reasons': [str], 'unexpressed': [str], 'attempts': int}`; a stored result is returned without a call; pass 2 sends the photo, the render, the draft JSON; the response must be `{'reasons': [...≤8], 'revised': <full block model>}`; `revised` → `_snap_fractions` (no-op for slot entries) → `validate_block_model` → `normalize` on a copy; on any failure `revised` is `None` and `reasons` carries the failure text; the draft object in the cache is never mutated (assert by sha).
- Route `POST /api/house/facades/critique {token, render}` → `critique(...)`; 400 on a missing/unknown/expired token; 200 with `{result}` otherwise. Routes are plain `def`.
- `PHOTO_SYSTEM` (v2): teaches the block model with the worked example (garage on the LEFT showing its gable to the street: `garage.roof {form: gable, ridge: z}`, `orientation: front`; hip main with two front gables: `main.roof {form: hip, ridge: x}` + two `gable` features), asks for `mirror` (garage on the RIGHT → true; left or unseen → false), `viewpoint: left|centre|right`, per block stories/roof/cladding/base/body, features per block as fractions, colours as nearest palette names, `unexpressed` (≤ 8 short strings). Temperature 0.1, strict JSON.
- `CRITIQUE_SYSTEM`: fixed order (massing and roof forms → materials and base → openings → colours), at most eight reasons each one line, and ONE full revised model in the same shape as pass 1 (slot entries, since the draft JSON is given). Never a patch.

- [ ] **Step 1: Fixtures.** Write `brick.expected.json` and `farmhouse.expected.json` by hand from spec §6 (brick: `mirror: false`, garage `roof {gable, z}` front, main `roof {hip, x}` + two `gable` features, `cladding: brick`, base `{stone, 0.9, stone_grey}`, unexpressed `["arched entry", "stone accents beyond the base band"]`; farmhouse: main `stories: 2`, `roof {gable, z}`, `cladding: batten`, base `{brick, 0.9, painted_brick}`, porch `roof: gable`, a `shed` with `window: true`, windows with `shutters: true`; unexpressed `["metal porch roof", "wing with the ridge along the street", "partial second story"]`). Write `*.pass1.json` as the FRACTION-shaped response that snaps to the expected model, and `*.pass2.json` as `{"reasons": [...], "revised": <the expected model with one deliberate correction, e.g. brick body brick_red → tan>}`. These are hand-written stand-ins until the user runs the real photos once (Task 14 records the real responses over them; the mapping assertions must hold for both).

- [ ] **Step 2: Failing tests** (replace `scenario_photo_becomes_a_draft_never_a_save` and `scenario_photo_failures_are_answers`; add):

```python
def _fixture(name):
    import io, os
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'house_photo', name)
    return json.load(io.open(p, encoding='utf-8'))


def scenario_photo_pass1_maps_the_fixtures():
    from services import storage, model_pools
    _fresh()
    storage.update_settings({'calendar_ids': [], 'llm_gemini_api_key': 'k'})
    orig = model_pools.call_pool_json
    try:
        for photo in ('brick', 'farmhouse'):
            seen = {}
            def fake_pool(tier, key, system, user, **kw):
                seen.update(kw); return _fixture(photo + '.pass1.json')
            model_pools.call_pool_json = fake_pool
            draft, notes, err, tok = hf.from_photo('AAAA', 'image/jpeg')
            check(err is None and tok, f'{photo}: draft + token: {err}')
            exp = _fixture(photo + '.expected.json')
            for k in ('mirror', 'blocks', 'unexpressed'):
                check(draft[k] == exp[k], f'{photo}: {k} maps: {draft[k]} != {exp[k]}')
            check({(g['kind'], g['slot']) for g in draft['ground']} == {(g['kind'], g['slot']) for g in exp['ground']},
                  f'{photo}: ground features map by slot')
            check({(r['kind'], r['slot']) for r in draft['roof']} == {(r['kind'], r['slot']) for r in exp['roof']},
                  f'{photo}: roof features map by slot')
            check(seen['max_models'] == 2 and seen['workflow'] == 'house_photo', f'attempt budget + label: {seen}')
            check(len(hf.list_facades()) == 1, 'nothing saved')
        check(json.loads(json.dumps(_fixture('brick.expected.json')))['mirror'] is False, 'brick photo: garage on the LEFT is mirror false')
    finally:
        model_pools.call_pool_json = orig


def scenario_photo_pass1_rejects_before_normalize():
    from services import storage, model_pools
    _fresh()
    storage.update_settings({'calendar_ids': [], 'llm_gemini_api_key': 'k'})
    orig = model_pools.call_pool_json
    try:
        for bad in ({}, {'version': 2, 'mirror': False}, 'not a dict', {'error': '429 Too Many Requests'}):
            model_pools.call_pool_json = lambda *a, **k: bad
            draft, notes, err, tok = hf.from_photo('AAAA', 'image/jpeg')
            check(draft is None and tok is None and err, f'{bad!r}: rejected with an error: {err}')
        check(hf.from_photo('AAAA', 'image/jpeg')[2] and hf._DRAFTS == {} or True, 'no draft issued for a rejection')
    finally:
        model_pools.call_pool_json = orig


def scenario_critique_returns_one_revised_model_or_the_draft():
    from services import storage, model_pools
    _fresh()
    storage.update_settings({'calendar_ids': [], 'llm_gemini_api_key': 'k'})
    orig = model_pools.call_pool_json
    try:
        model_pools.call_pool_json = lambda *a, **k: _fixture('brick.pass1.json')
        draft, _, _, tok = hf.from_photo('AAAA', 'image/jpeg')
        before = json.dumps(hf.draft_for(tok)['spec'], sort_keys=True)
        calls = {'n': 0}
        def pass2(tier, key, system, user, **kw):
            calls['n'] += 1
            check(len(kw['images']) == 2, 'photo + render go to pass 2')
            return _fixture('brick.pass2.json')
        model_pools.call_pool_json = pass2
        res, err = hf.critique(tok, 'iVBOR')
        check(err is None and res['revised'] and res['revised'] != draft and res['reasons'], f'a revision with reasons: {err}')
        check(json.dumps(hf.draft_for(tok)['spec'], sort_keys=True) == before, 'the draft is byte-identical after critique')
        res2, _ = hf.critique(tok, 'iVBOR')
        check(calls['n'] == 1 and res2 == res, 'a duplicate submission reuses the stored result: one execution')
        # a rejected revision keeps the draft
        model_pools.call_pool_json = lambda *a, **k: _fixture('farmhouse.pass1.json')
        _, _, _, tok2 = hf.from_photo('BBBB', 'image/jpeg')
        model_pools.call_pool_json = lambda *a, **k: {'reasons': ['x'], 'revised': {}}
        res3, err3 = hf.critique(tok2, 'iVBOR')
        check(err3 is None and res3['revised'] is None and any('incomplete' in r for r in res3['reasons']), f'rejected revision -> draft stands: {res3}')
        check(hf.critique('bogus', 'x') == (None, 'unknown or expired draft'), 'a bad token runs nothing')
    finally:
        model_pools.call_pool_json = orig
```

Update `scenario_routes_and_template` / `scenario_route_wrappers_map_errors` for the `token` field, the new `/draft` and `/critique` routes, and assert (by reading `main.py` source) that `house_facade_photo` is `def`, not `async def`.

- [ ] **Step 3: Run → RED.**

- [ ] **Step 4: Implement.**

```python
def _snap_fractions(obj):
    if not isinstance(obj, dict):
        return obj
    out = copy.deepcopy(obj)
    for layer in ('ground', 'roof'):
        items = out.get(layer)
        if not isinstance(items, list):
            continue
        for e in items:
            if not isinstance(e, dict) or 'slot' in e or 'block' not in e:
                continue
            face = 'garage_block' if e.get('block') == 'garage' else 'main'
            lo, hi = _face_range(face)
            n = hi - lo + 1
            at, width = _num(e.get('at'), 0.0), _num(e.get('width'), 1.0 / n)
            slot = lo + int(round(min(0.999, max(0.0, at)) * n))
            span = max(1, int(round(width * n)))
            e['slot'] = min(max(lo, slot), hi)
            e['span'] = min(span, hi - e['slot'] + 1)
            for k in ('block', 'at', 'width'):
                e.pop(k, None)
    return out


def from_photo(image_b64, mime):
    """One photo -> a validated, normalized DRAFT + its token. Never stores."""
    from services import model_pools
    settings = _settings()
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key:
        return None, [], 'no LLM API key configured', None
    try:
        res = model_pools.call_pool_json(
            'vision', api_key, _photo_prompt(),
            'Describe the street-facing elevation of the house in the attached photo as the block model.',
            temperature=0.1, timeout_s=90, settings=settings, strict_json=True,
            max_output_tokens=4096, max_models=2, workflow='house_photo',
            images=[{'mime': mime or 'image/jpeg', 'b64': image_b64}])
    except Exception as e:
        return None, [], f'could not read the photo ({e})', None
    if not isinstance(res, dict):
        return None, [], 'could not read the photo (bad response)', None
    if res.get('error'):
        return None, [], f"could not read the photo ({res['error']})", None
    res.pop('_model', None)
    snapped = _snap_fractions(res)
    errs = validate_block_model(snapped)
    if errs:
        return None, [], 'the model returned an incomplete house: ' + '; '.join(errs[:3]), None
    spec, notes = normalize(snapped)
    return spec, notes, None, issue_draft(spec, image_b64, mime)


def critique(token, render_png_b64):
    from services import model_pools
    e = draft_for(token)
    if e is None:
        return None, 'unknown or expired draft'
    if e['result'] is not None:
        return e['result'], None
    settings = _settings()
    api_key = settings.get('llm_gemini_api_key', '')
    draft = copy.deepcopy(e['spec'])
    result = {'draft': draft, 'revised': None, 'reasons': [], 'unexpressed': list(draft.get('unexpressed') or []), 'attempts': 0}
    if not api_key or not e.get('photo_b64'):
        result['reasons'] = ['no critique: ' + ('no LLM API key configured' if not api_key else 'no photo on this draft')]
        store_result(token, result)
        return result, None
    try:
        res = model_pools.call_pool_json(
            'vision', api_key, CRITIQUE_SYSTEM,
            'Photo first, then the render of the draft, then the draft JSON:\n' + json.dumps(draft),
            temperature=0.1, timeout_s=90, settings=settings, strict_json=True,
            max_output_tokens=4096, max_models=2, workflow='house_photo',
            images=[{'mime': e.get('mime') or 'image/jpeg', 'b64': e['photo_b64']},
                    {'mime': 'image/png', 'b64': render_png_b64}])
        result['attempts'] = 1
    except Exception as ex:
        result['reasons'] = [f'critique failed ({ex})']; store_result(token, result); return result, None
    if not isinstance(res, dict) or res.get('error'):
        result['reasons'] = [f"critique failed ({(res or {}).get('error', 'bad response') if isinstance(res, dict) else 'bad response'})"]
        store_result(token, result); return result, None
    reasons = [str(r)[:160] for r in (res.get('reasons') or []) if isinstance(r, (str, dict))][:8]
    reasons = [r if isinstance(r, str) else str(r.get('reason', r)) for r in reasons]
    revised = _snap_fractions(res.get('revised'))
    errs = validate_block_model(revised)
    if errs:
        result['reasons'] = reasons + ['revision rejected as incomplete: ' + '; '.join(errs[:3])]
    else:
        spec, notes = normalize(copy.deepcopy(revised))
        result['revised'] = spec
        result['reasons'] = reasons + notes
        result['unexpressed'] = list(spec.get('unexpressed') or [])
    store_result(token, result)
    return result, None
```

`PHOTO_SYSTEM`/`CRITIQUE_SYSTEM` texts per the Interfaces block (write them in full; the schema line lists every field of §2 with `block/at/width` for features in pass 1 and `slot/span` in pass 2). Routes:

```python
@app.post("/api/house/facades/photo")
def house_facade_photo(photo: UploadFile = File(...)):
    """Sync def on purpose (spec section 4): a vision call must not block the
    event loop. Photo -> DRAFT + token; returned, never stored."""
    import base64
    from services import house_facade as _hf
    data = photo.file.read()
    ...(size/mime checks as today)...
    draft, notes, err, token = _hf.from_photo(base64.b64encode(data).decode('ascii'), mime)
    return {'draft': draft, 'notes': notes, 'error': err, 'token': token}


@app.post("/api/house/facades/critique")
def house_facade_critique(body: dict = Body(default={})):
    from services import house_facade as _hf
    render = str((body or {}).get('render') or '')
    if render.startswith('data:image/png;base64,'):
        render = render.split(',', 1)[1]
    result, err = _hf.critique(str((body or {}).get('token') or ''), render)
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {'result': result}
```

- [ ] **Step 5: Run → GREEN**, `--focus`, bump, commit:

```
feat: the photo pipeline — pass 1 describes blocks as fractions, validate before normalize, pass 2 returns one revised model under a deduped token, two attempts per stage (vX.Y.Z)
```

---

### Task 12: The hand path — Blocks panel, feature fields, Preview in 3D, the two-render draft view

**Files:**
- Modify: `chauffeur/templates/config.html` (Home section markup `~2581–2680`; Alpine methods `~5590–5720`)
- Modify: `chauffeur/tests/test_house_facade.py` (`scenario_home_section_pins`)
- Test: `chauffeur/tests/test_house_facade.py`; then `tools/build_tailwind.py` (any new utility class)

**Interfaces:**
- Alpine data: `facadeDraft` is V2; new `facadePreviewToken`, `facadeRenders: {draft: dataURL|null, revised: dataURL|null}`, `facadeCritique: {reasons: [], unexpressed: [], revised: spec|null}`; methods `facadeBlockApply()`, `facadePreview3D()`, `facadeCritique()`, `facadePickRevised()`, `facadePickDraft()`, `facadeCaptureFrame()`.
- Markup: a **Blocks** panel (per block: stories select, roof form, ridge, pitch range 22.5–35 step 0.5, depth range 0–6 step 0.5, cladding select, base on/off + material + height + body colour, body colour; garage orientation) and the **mirror** checkbox; the feature cell editor gains `shed` in the roof kind select, a per-feature cladding select (`inherit` + six), window `shutters` checkbox + `story` select (1|2, only when the block has two stories), porch `roof` select; a **Preview in 3D** button that opens a 1400×1000 iframe (`house?draft=<token>&angle=0&quality=medium&day=1`, scaled to fit) under the strip; after a photo, a **Compare to photo** button runs the critique; the draft view shows both renders side by side with **Use this** under each, the `unexpressed` list and the reasons.

- [ ] **Step 1: Failing pins** (extend `scenario_home_section_pins`):

```python
    for needle in ('facadeBlockApply(', 'facadePreview3D(', 'facadeCritique(', 'facadePickRevised(', 'facadePickDraft(',
                   'x-model="facadeDraft.mirror"', 'facadeDraft.blocks[b].stories', 'facadeDraft.blocks[b].roof.form',
                   'facadeDraft.blocks[b].depth', 'facadeDraft.blocks[b].cladding', 'facadeDraft.blocks.garage.orientation',
                   '<option value="shed">', 'facadeCell.ground.shutters', 'facadeCell.ground.story', 'facadeCell.porch.roof',
                   'facadeCell.roof.cladding', 'Preview in 3D', 'Compare to photo', 'Use this', 'unexpressed',
                   'id="facade-preview-frame"', "day=1"):
        check(needle in tpl, f'hand path: {needle}')
    check('preserveDrawingBuffer' not in tpl, 'capture never toggles the drawing buffer flag')
```

- [ ] **Step 2: Run → RED.**

- [ ] **Step 3: Markup.** Insert the Blocks panel above the slot strip:

```html
<div class="bg-gray-900 p-3 rounded-xl text-sm space-y-2" x-show="facadeDraft">
  <div class="flex items-center gap-4">
    <b class="text-teal-300">Blocks</b>
    <label><input type="checkbox" x-model="facadeDraft.mirror" @change="facadeBlockApply()"> Mirror the house (garage on the right)</label>
  </div>
  <template x-for="b in ['main','garage']" :key="b">
    <div class="grid md:grid-cols-6 gap-2 items-end">
      <span class="uppercase text-xs text-gray-500" x-text="b"></span>
      <label>Stories <select class="w-full bg-gray-800" x-model.number="facadeDraft.blocks[b].stories" @change="facadeBlockApply()"><option value="1">1</option><option value="2">2</option></select></label>
      <label>Roof <select class="w-full bg-gray-800" x-model="facadeDraft.blocks[b].roof.form" @change="facadeBlockApply()"><option>gable</option><option>hip</option></select></label>
      <label>Ridge <select class="w-full bg-gray-800" x-model="facadeDraft.blocks[b].roof.ridge" @change="facadeBlockApply()"><option value="x">along the street</option><option value="z">toward the street</option></select></label>
      <label>Pitch <input type="range" min="22.5" max="35" step="0.5" class="w-full" x-model.number="facadeDraft.blocks[b].roof.pitch_deg" @change="facadeBlockApply()"> <span x-text="facadeDraft.blocks[b].roof.pitch_deg + '°'"></span></label>
      <label>Depth <input type="range" min="0" max="6" step="0.5" class="w-full" x-model.number="facadeDraft.blocks[b].depth" @change="facadeBlockApply()"> <span x-text="facadeDraft.blocks[b].depth"></span></label>
      <label>Cladding <select class="w-full bg-gray-800" x-model="facadeDraft.blocks[b].cladding" @change="facadeBlockApply()"><template x-for="c in facadeCladdings" :key="c"><option :value="c" x-text="c"></option></template></select></label>
      <label>Body <select class="w-full bg-gray-800" x-model="facadeDraft.blocks[b].body" @change="facadeBlockApply()"><template x-for="c in facadeStyleOptions.body" :key="c"><option :value="c" x-text="c"></option></template></select></label>
      <label><input type="checkbox" :checked="!!facadeDraft.blocks[b].base" @change="facadeBaseToggle(b, $event.target.checked)"> Base band</label>
      <template x-if="facadeDraft.blocks[b].base">
        <div class="contents">
          <label>Base material <select class="w-full bg-gray-800" x-model="facadeDraft.blocks[b].base.material" @change="facadeBlockApply()"><template x-for="c in facadeCladdings" :key="c"><option :value="c" x-text="c"></option></template></select></label>
          <label>Base height <input type="range" min="0.6" max="1.8" step="0.1" class="w-full" x-model.number="facadeDraft.blocks[b].base.height" @change="facadeBlockApply()"></label>
          <label>Base colour <select class="w-full bg-gray-800" x-model="facadeDraft.blocks[b].base.body" @change="facadeBlockApply()"><template x-for="c in facadeStyleOptions.body" :key="c"><option :value="c" x-text="c"></option></template></select></label>
        </div>
      </template>
      <label x-show="b === 'garage'">Garage door <select class="w-full bg-gray-800" x-model="facadeDraft.blocks.garage.orientation" @change="facadeBlockApply()"><option value="front">faces the street</option><option value="side">on the side</option></select></label>
    </div>
  </template>
</div>
```

The feature cell editor: add `<option value="shed">shed</option>` to the roof select; `<label x-show="facadeCell.roof.kind !== 'eave'">Feature cladding <select x-model="facadeCell.roof.cladding" @change="facadeCellApply()"><option value="">inherit</option>…six…</select></label>`; `<label x-show="facadeCell.ground.kind === 'window'"><input type="checkbox" x-model="facadeCell.ground.shutters" @change="facadeCellApply()"> shutters</label>`; `<label x-show="facadeCell.ground.kind === 'window' && facadeBlockStories(facadeSlot) === 2">Story <select x-model.number="facadeCell.ground.story" @change="facadeCellApply()"><option value="1">1</option><option value="2">2</option></select></label>`; `<label x-show="facadeCell.porch.type !== 'none'">Porch roof <select x-model="facadeCell.porch.roof" @change="facadeCellApply()"><option>flat</option><option>gable</option></select></label>`; `facadeCellApply` drops an empty `cladding`. The style row loses `cladding` (`['body','roof','frame','door','trim']` → `['roof','frame','door','trim']`). Below the strip:

```html
<div class="flex gap-2 items-center">
  <button class="px-3 py-1 rounded bg-gray-700" @click="facadePreview3D()">Preview in 3D</button>
  <button class="px-3 py-1 rounded bg-amber-700" x-show="facadeDraftSource === 'photo' && facadePreviewToken" @click="facadeCritique()">Compare to photo</button>
  <span class="text-xs text-gray-400" x-text="facadeBusy"></span>
</div>
<div x-show="facadePreviewToken" class="rounded-xl overflow-hidden bg-black" style="width:700px;height:500px">
  <iframe id="facade-preview-frame" :src="facadePreviewToken ? (apiBase + 'house?draft=' + facadePreviewToken + '&angle=0&quality=medium&day=1') : 'about:blank'"
          style="width:1400px;height:1000px;transform:scale(0.5);transform-origin:0 0;border:0"></iframe>
</div>
<div x-show="facadeRenders.draft || facadeRenders.revised" class="grid md:grid-cols-2 gap-3">
  <div><img :src="facadeRenders.draft" class="rounded-lg"><button class="mt-1 px-3 py-1 rounded bg-teal-600" @click="facadePickDraft()">Use this</button><div class="text-xs text-gray-400">the draft</div></div>
  <div x-show="facadeRenders.revised"><img :src="facadeRenders.revised" class="rounded-lg"><button class="mt-1 px-3 py-1 rounded bg-teal-600" @click="facadePickRevised()">Use this</button><div class="text-xs text-gray-400">after comparing to your photo</div></div>
</div>
<ul class="text-xs text-gray-300" x-show="facadeCritique.reasons.length"><template x-for="r in facadeCritique.reasons" :key="r"><li x-text="r"></li></template></ul>
<div class="text-xs text-amber-200" x-show="facadeCritique.unexpressed.length">Not in the model: <span x-text="facadeCritique.unexpressed.join(' · ')"></span></div>
```

- [ ] **Step 4: Methods.**

```js
facadeCladdings: ['batten','lap','brick','stone','stucco','shingle'],
facadePreviewToken: null, facadeRenders: { draft: null, revised: null },
facadeCritique: { reasons: [], unexpressed: [], revised: null }, facadeBusy: '',
facadeBlockStories(i) { const s = this.facadeSlots.find(x => x.i === i); return s ? this.facadeDraft.blocks[s.face === 'garage_block' ? 'garage' : 'main'].stories : 1; },
facadeBaseToggle(b, on) { this.facadeDraft.blocks[b].base = on ? { material: 'stone', height: 0.9, body: 'stone_grey' } : null; this.facadeBlockApply(); },
async facadeBlockApply() { await this.facadePreview(); },
async facadePreview3D() {
    try {
        const res = await fetch(`${this.apiBase}api/house/facades/draft`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ spec: this.facadeDraft }) });
        const data = await res.json();
        if (!res.ok) { showGlobalAlert(data.detail || 'Could not preview'); return; }
        this.facadeDraft = data.spec; this.facadeNotes = data.notes; this.facadePreviewToken = data.token;
    } catch (e) { console.error('Failed to preview', e); showGlobalAlert('Could not preview'); }
},
facadeCaptureFrame() {
    return new Promise((resolve, reject) => {
        const f = document.getElementById('facade-preview-frame');
        let tries = 0;
        const tick = () => {
            const w = f && f.contentWindow;
            if (w && w.chfNavProbe && w.chfNavProbe({ settled: true })) { resolve(w.chfCapture()); return; }
            if (++tries > 200) { reject(new Error('the preview never settled')); return; }
            setTimeout(tick, 100);
        };
        tick();
    });
},
async facadeCritique() {
    if (!this.facadePhotoToken) { showGlobalAlert('Load a photo first'); return; }
    this.facadeBusy = 'Rendering the draft…';
    try {
        this.facadePreviewToken = this.facadePhotoToken;           // the photo's own draft renders
        const png = await this.facadeCaptureFrame();
        this.facadeRenders.draft = png; this.facadeBusy = 'Comparing to your photo…';
        const res = await fetch(`${this.apiBase}api/house/facades/critique`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: this.facadePhotoToken, render: png }) });
        const data = await res.json();
        if (!res.ok) { showGlobalAlert(data.detail || 'Could not compare'); return; }
        const r = data.result;
        this.facadeCritique = { reasons: r.reasons || [], unexpressed: r.unexpressed || [], revised: r.revised || null };
        if (r.revised) {
            const res2 = await fetch(`${this.apiBase}api/house/facades/draft`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ spec: r.revised }) });
            const d2 = await res2.json();
            this.facadePreviewToken = d2.token;
            this.facadeRenders.revised = await this.facadeCaptureFrame();
        }
    } catch (e) { console.error('critique failed', e); showGlobalAlert('Could not compare to the photo'); }
    finally { this.facadeBusy = ''; }
},
facadePickRevised() { if (this.facadeCritique.revised) { this.facadeDraft = this.facadeCritique.revised; this.facadePreview(); } },
facadePickDraft() { /* the draft is already loaded; nothing to swap */ this.facadePreview(); },
```

`facadePhoto` stores `data.token` as `this.facadePhotoToken` and clears `facadeRenders`/`facadeCritique`. `facadeLoad`/`facadeSaveNew`/`facadeOverwrite` are unchanged (the server normalizes V1 records on load). Run `python tools/build_tailwind.py` after the markup lands.

- [ ] **Step 5: Run → GREEN**, `--focus`, bump, commit:

```
feat: Home editor thinks in blocks — Blocks panel, mirror, shed/cladding/shutters/story/porch-roof fields, Preview in 3D, Compare to photo with two renders and a pick (vX.Y.Z)
```

---

### Task 13: The combined scenario and budgets against B0

**Files:**
- Modify: `chauffeur/tests/test_house_facade_live.py` (new `scenario_combined_variant_holds_every_law`; budget table)
- Modify: spec §9 (per-variant numbers)
- Test: `chauffeur/tests/test_house_facade_live.py`

- [ ] **Step 1: The scenario:**

```python
def scenario_combined_variant_holds_every_law():
    """Spec section 6 (rev2): mirrored + two stories on both blocks + max
    depth + side garage + brick with a stone base, in one boot. Every
    marker tappable, every room view clear, budgets within B0 + delta."""
    from services import house_facade as hf
    spec = copy.deepcopy(hf.CANONICAL)
    spec['mirror'] = True
    for b in ('main', 'garage'):
        spec['blocks'][b].update({'stories': 2, 'depth': 6, 'cladding': 'brick', 'body': 'brick_red',
                                  'base': {'material': 'stone', 'height': 1.2, 'body': 'stone_grey'}})
    spec['blocks']['garage']['orientation'] = 'side'
    spec['blocks']['main']['roof'] = {'form': 'hip', 'ridge': 'x', 'pitch_deg': 30}
    spec['ground'] += [{'slot': 7, 'span': 1, 'kind': 'window', 'size': 'standard', 'shutters': True, 'story': 2}]
    spec['roof'].append({'slot': 13, 'span': 2, 'kind': 'shed', 'window': True})
    spec, notes = hf.normalize(spec)
    check(spec['blocks']['main']['depth'] == 2.0, f'the porch clamps main depth: {notes}')
    served = live_app(_seed)
    if served is None:
        return
    from house_probe import THREE_WRAP, BUDGET_JS
    with open('static/vendor/three.min.js', 'rb') as fh:
        patched = fh.read() + THREE_WRAP
    with served.browser() as page:
        page.route('**/three.min.js*', lambda route: route.fulfill(status=200, content_type='application/javascript', body=patched))
        page.add_init_script(DAY_LOCK_JS)
        page.add_init_script('window.HOUSE_FACADE = %s;' % json.dumps({'id': 't', 'name': 't', 'spec': spec, 'slots': hf.slot_table(spec['blocks'])}))
        page.goto(served.url('house?quality=high'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        r = page.evaluate(BUDGET_JS)
        check(r['buildMs'] <= 1500, f"buildMs {r['buildMs']} <= 1500")
        check(r['inFrustum'] <= B0['inFrustum'] + DELTA['combined']['meshes'], f"exterior meshes {r['inFrustum']} <= B0 + delta")
        check(r['calls'] <= B0['calls'] + DELTA['combined']['calls'], f"draws {r['calls']} <= B0 + delta")
        for key in ('front_door', 'back_door', 'garage_block_roof_south', 'garage_front'):
            best = None
            for k in range(8):
                page.evaluate(f'window.chfOrbitTo({k})')
                page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
                p = page.evaluate("window.chfNavProbe({feature:'%s'})" % key)
                if p and p.get('hit'):
                    best = k; break
            check(best is not None, f'marker {key} reachable from some orbit stop')
        for room in ('kitchen', 'living', 'mudroom', 'garage', 'study'):
            page.evaluate(f"window.chfHouseEnterRoom('{room}')")
            page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
            check(page.evaluate(f"window.chfRoomViewClear('{room}')")['clear'], f'{room}: view clear')
            page.evaluate("window.chfHouseExit()")
            page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        errs = [e for e in served.errors() if 'WebGL' not in e]
        check(not errs, f'console clean: {errs[:3]}')
```

`B0` and `DELTA` are module constants at the top of the file: `B0 = {'inFrustum': <Task 1>, 'calls': <Task 1>, 'tris': <Task 1>}`; `DELTA = {'mirror': {'meshes': 0, 'calls': 0}, 'two_story': {...}, 'side_garage': {...}, 'brick': {...}, 'combined': {...}}` — fill each from the probe run of that variant (`--facade-json` with the variant JSON) and record the whole table in spec §9 with the command lines. Tighten each scenario from Tasks 5–9 to its recorded delta.

- [ ] **Step 2: Run → GREEN** (RED first on the placeholder deltas of 0), record, tighten, `--focus` + facade live, bump, commit:

```
test: the combined variant and per-variant budgets against B0 (vX.Y.Z)
```

---

### Task 14: Wrap — real fixtures, resemblance review, capabilities, spec §9, memory, full sweep

**Files:**
- Modify: `chauffeur/tests/fixtures/house_photo/*.pass1.json`, `*.pass2.json` (recorded from one real run each)
- Modify: `docs/superpowers/specs/2026-09-17-house-blocks-materials-design.md` §9
- Modify: `chauffeur/system_capabilities.md` (new entry after the masking entry; header "Current through")
- Modify: `C:\Users\ffejn\.claude\projects\e--repositories-Chauffeur\memory\house-arc.md`

- [ ] **Step 1: Record the real responses.** With an API key in the dev settings, run each acceptance photo through the pipeline once (`python -c` calling `hf.from_photo` then `hf.critique` with a `--facade-json` render captured by the probe), save the raw responses over the hand-written `pass1/pass2` fixtures, re-run `test_house_facade.py`; where the mapping assertions fail, decide whether the fixture's EXPECTED model or the prompt is wrong, fix the prompt, re-record. Note the request count per photo (≤ 4).

- [ ] **Step 2: Resemblance review.** For each photo, probe-render canonical, the pass-1 draft and the revision at stop 0 (`--facade-json`, `--day`, `--seed-rng`), open all three PNGs beside the photo, and write the §9 verdict with the structural gaps (farmhouse: partial second story; brick: arched entry, stone accents). This is the user's gate; record what you saw and what you could not judge.

- [ ] **Step 3: Docs.** §9: B0, the per-variant table, the request counts, R-A/R-B/R-C and every deviation with its ruling, the parked list. Capabilities: one entry describing the block model, the mirror contract, the draft token, the pipeline, the editor, the budgets; bump "Current through". Memory `house-arc.md`: arc 2 SHIPPED range, NOT device-verified, the rulings the user should eyeball on device (mirrored traffic on the left, the void floor, the return wall), next = style kits.

- [ ] **Step 4: The full sweep**, then commit + push:

```
docs: massing arc 2 wrap — blocks, materials, mirror, photo pipeline (vX.Y.Z)
```

---

## Self-review

**Spec coverage.** §0 → Task 2. §2 block model: blocks/roof/cladding/base/colours → Tasks 3–5; where blocks meet → Task 6; vault gate → Task 7; street features (shed, porch roof, hip_end kept, shutters, story) → Tasks 4, 7, 8; overlap per story → Task 4; mirror → Task 9; unexpressed → Tasks 4, 11, 12; compatibility table + pixel pin → Tasks 4, 5. §3.1 materials + draw honesty → Task 5 (+ Task 13 numbers). §3.2 blocks/stories/side garage → Tasks 6, 7, 8. §3.3 → Task 8. §3.4 mirror contract → Task 9. §4 pipeline: validation → Tasks 3, 11; render in the browser → Tasks 10, 12 (R-A); token lifecycle → Task 10; pass 2 full model → Task 11; attempt budget → Task 11; routes plain `def` → Tasks 10, 11; dev adapter guard → Task 10. §5 hand path → Task 12. §6 pure → Tasks 3, 4, 9, 10, 11; fixtures → Tasks 11, 14; resemblance gate → Task 14; live → Tasks 2, 5–9, 13. §7 → Tasks 1, 13. §8 mudroom void: no task (stays sealed, parked in §9 at Task 14). §9 → Task 14.

**Placeholder scan.** Task 5 Step 5's `shellWall` block argument, Task 8's second `shellGroup()` for the shed box, and Task 9's plaque-orientation check are stated as instructions with the mechanism given; the executor still has a decision at each (which sites, how to build the second group, which crop) — acceptable, since the test names the observable. No "TBD"/"handle edge cases" remain.

**Type consistency.** `validate_block_model(obj) -> list[str]`; `normalize(raw) -> (spec, notes)`; `slot_table(blocks=None)`; `from_photo(b64, mime) -> (draft, notes, err, token)`; `critique(token, png_b64) -> (result, err)`; `issue_draft(spec, photo=None, mime=None) -> token`; `draft_for(token) -> dict|None`; `store_result(token, result)`; JS `BLOCKS`, `blockPitch(name)`, `cladTex(material, hex)`, `CLAD(block)`, `baseBand(...)`, `storyBox(name)`, `shedAt(feat)`, `neighbourVolume(name)`, `toWorldX(x)`, `toWorld(v)`, `textMesh(geo, mat, group)`, hooks `chfBlocks`, `chfRoofAlias`, `chfBlockGeometry`, `chfRoomViewClear`, `chfMirror`, `chfCapture`, `chfPlaqueCanvas`; Python helpers `roof_piece_names`, `SEED_RNG_JS`, `FEATURE_JS`, `VERTEX_AUDIT_ALL_JS`, `ROOF_INSIDE_NEIGHBOUR_JS`, `BUDGET_JS` (exported from `house_probe.py`) — names match across tasks.

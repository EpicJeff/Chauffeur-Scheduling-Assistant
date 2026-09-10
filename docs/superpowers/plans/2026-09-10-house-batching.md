# House Batching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut the `/house` scene's draw calls from ~3,100 (exterior) to a few hundred by sharing materials and geometries, instancing the garden, and merging static fabric — with zero visual change.

**Architecture:** Four spec slices in seven code tasks. B0 makes the budget measurable from the repo (`house_probe.py --budget`). B1 lands in three steps: a safety rail (`own()`/`zoneTag()`) that guarantees zone materials stay unique, then the material cache, then the geometry cache. B2 bakes the built yard into `InstancedMesh` buckets keyed by (geometry, material) identity — which is why the caches come first. B3 converts the exterior tap router to explicit room tags (the old height heuristic dies the moment merged meshes sit at group origin), then merges static same-material fabric per visibility group with a hand-rolled geometry merger (`BufferGeometryUtils` is NOT in the vendored bundle — the string in `three.min.js` is only a removal warning).

**Tech Stack:** three.js (legacy vendored `static/vendor/three.min.js`, ~r149, script-tag global `THREE`), vanilla ES5 JS in `chauffeur/static/house.js` (one IIFE, no modules, no build step), Python/Playwright test harness (`tests/live_app.py`), probe tool `chauffeur/tools/house_probe.py`.

**Spec:** `docs/superpowers/specs/2026-09-10-house-batching-design.md` — read it first; the laws L1–L7 there are binding and every task below cites the one it serves.

## Global Constraints

- **ES5 only in `house.js`** — `var`, `function`, no arrow functions, no `const`/`let`, no template literals. (JS passed to `page.evaluate` in Python tests may be modern — it runs in Chromium.)
- **No visual change.** Pixel policy (user ruling): *same or better, not identical* — but the planting is deterministic, so expect pixel-identical and treat any diff as a finding to show the user, not a licence.
- **`static/kitchen.js` is out of scope.** Never touch it.
- **No new dependencies, no downloads.** The vendored three bundle is not modified.
- **Every commit:** bump `chauffeur/config.yaml` `version:` (currently `2.473.0`), commit message in repo style — a short poetic sentence plus `(vX.Y.Z)` — then push. No double quotes inside `git commit -m` arguments when using PowerShell (quoting rule); prefer the Bash tool for commits.
- **Full test sweep before every code commit:** `python tools/test.py` from `chauffeur/` (parallel, ~79s). Run it with NO other Chromium work in flight (the sweep is flaky under browser load — spec §5); a single browser-test failure passes on isolated re-run before being treated as a regression. Inner loop: `python tools/test.py --focus`. Never pipe the sweep (masks the exit code).
- **All probe/screenshot output goes to a scratch directory outside the repo**, e.g. `%TEMP%\house_batching\<stage>` — never into the working tree.
- Line numbers below are as of v2.473.0 and drift as tasks land; anchor by the quoted code, not the number.

## Reference: current numbers (baseline, 2026-09-10, quality=high)

| view | meshes in frustum | triangles |
|---|---|---|
| exterior | 3,106 | 300,728 |
| living | 1,019 | 93,638 |
| kitchen | 1,018 | 93,626 |
| mudroom | 1,175 | 133,220 |
| garage | 606 | 63,008 |

Scene: 3,310 meshes / 3,310 materials / 3,310 geometries. `extG` holds 1,759 of the exterior's in-frustum meshes (the garden).

---

### Task 1: B0 — the budget probe (`--budget`)

**Files:**
- Modify: `chauffeur/tools/house_probe.py`

**Interfaces:**
- Produces: module constants `THREE_WRAP` (bytes, JS appended to the three bundle) and `BUDGET_JS` (str, a `page.evaluate` snippet returning the budget dict). Task 3's live test imports `THREE_WRAP` — the names must match exactly.
- Produces: CLI flag `--budget` printing one budget line + top-group rows per view.

**Why no pytest:** the probe is dev tooling, not an app path; its verification is running it. Adding a dedicated Chromium test would grow the flaky-under-load browser pool for no user-facing coverage.

- [ ] **Step 1: Add the constants and flag**

At module level in `house_probe.py` (after the imports), add:

```python
# The renderer wrapper the --budget flag appends to the vendored three
# bundle via route interception. three assigns render as an INSTANCE
# property, so patching WebGLRenderer.prototype.render is a silent no-op
# — the constructor must be wrapped. No production code ships a debug
# handle; this exists only on probed pages.
THREE_WRAP = b"""
;(function () {
  var OR = window.THREE && window.THREE.WebGLRenderer;
  if (!OR) { window.__hpFail = 'no THREE'; return; }
  function W(p) {
    var r = new OR(p);
    window.__hpT0 = window.__hpT0 || performance.now();
    var o = r.render.bind(r);
    r.render = function (s, c) {
      if (window.__hpBuildMs === undefined)
        window.__hpBuildMs = Math.round(performance.now() - window.__hpT0);
      window.__hpScene = s; window.__hpCam = c; window.__hpR = r;
      return o(s, c);
    };
    return r;
  }
  W.prototype = OR.prototype;
  window.THREE.WebGLRenderer = W;
})();
"""

BUDGET_JS = """() => {
  const T = window.THREE, S = window.__hpScene, C = window.__hpCam;
  if (!S || !C) return { err: 'no captured scene' };
  S.updateMatrixWorld(true); C.updateMatrixWorld(true);
  const fr = new T.Frustum().setFromProjectionMatrix(
    new T.Matrix4().multiplyMatrices(C.projectionMatrix, C.matrixWorldInverse));
  const mats = new Set(), geos = new Set(), rows = {};
  let total = 0, visible = 0, inFrustum = 0, tris = 0;
  function vis(o) { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; }
  S.traverse(o => {
    if (!o.isMesh) return;
    total += 1;
    if (o.material && o.material.uuid) mats.add(o.material.uuid);
    if (o.geometry) geos.add(o.geometry.uuid);
    if (!vis(o)) return;
    visible += 1;
    const inst = o.isInstancedMesh ? o.count : 1;
    if (o.frustumCulled && o.geometry) {
      if (!o.geometry.boundingSphere) o.geometry.computeBoundingSphere();
      const sp = o.geometry.boundingSphere.clone().applyMatrix4(o.matrixWorld);
      if (!fr.intersectsSphere(sp)) return;
    }
    inFrustum += 1;
    const g = o.geometry;
    if (g && g.attributes.position)
      tris += inst * (g.index ? g.index.count / 3 : g.attributes.position.count / 3);
    let top = o; while (top.parent && top.parent !== S) top = top.parent;
    let key;
    if (top === o) key = '(loose)';
    else {
      if (!top.userData.__hpN) {
        let n = 0; top.traverse(q => { if (q.isMesh) n += 1; });
        top.userData.__hpN = n;
      }
      key = 'group@' + ['x', 'y', 'z'].map(a => top.position[a].toFixed(1)).join(',') +
            ' n=' + top.userData.__hpN;
    }
    rows[key] = (rows[key] || 0) + 1;
  });
  return { total, visible, inFrustum, tris: Math.round(tris),
           materials: mats.size, geometries: geos.size,
           buildMs: window.__hpBuildMs,
           rows: Object.entries(rows).sort((a, b) => b[1] - a[1]).slice(0, 8) };
}"""
```

In `main()`, add the argument next to the others:

```python
    ap.add_argument('--budget', action='store_true',
                    help='wrap the renderer and print per-view draw-budget '
                         'numbers (meshes, in-frustum, tris, unique '
                         'materials/geometries, build ms)')
```

Before `page.goto(...)` (inside `with served.browser() as page:`), add:

```python
        if args.budget:
            with open('static/vendor/three.min.js', 'rb') as fh:
                patched = fh.read() + THREE_WRAP
            page.route('**/three.min.js*', lambda route: route.fulfill(
                status=200, content_type='application/javascript',
                body=patched))
```

After each view's screenshot (`print('shot', path)`), add:

```python
            if args.budget:
                b = page.evaluate(BUDGET_JS)
                if b.get('err'):
                    print('budget', view, 'ERR', b['err'])
                else:
                    print('budget %-9s meshes=%d visible=%d inFrustum=%d '
                          'tris=%d materials=%d geometries=%d buildMs=%s'
                          % (view, b['total'], b['visible'], b['inFrustum'],
                             b['tris'], b['materials'], b['geometries'],
                             b['buildMs']))
                    for k, v in b['rows']:
                        print('    %5d  %s' % (v, k))
```

- [ ] **Step 2: Run it and check against the baseline table**

Run from `chauffeur/`:
```
python tools/house_probe.py --views all --budget --quality high --out "%TEMP%\house_batching\baseline"
```
Expected: five `budget` lines. exterior `inFrustum` within ~2% of 3,106; `materials=3310 geometries=3310` (may differ slightly if fixture counts changed — the 1:1:1 mesh:material:geometry ratio is the invariant to confirm); top row a `group@0.0,0.0,0.0 n=~1960`. Exit 0, `ok: no console errors`. The five PNGs in the baseline dir are the pixel baseline every later task compares against — do not delete the directory.

- [ ] **Step 3: Sweep**

Run: `python tools/test.py` (from `chauffeur/`, nothing else driving Chromium).
Expected: exit 0. (A single browser-test failure: re-run that test in isolation before investigating.)

- [ ] **Step 4: Commit**

Bump `chauffeur/config.yaml` to `2.474.0`, then:
```bash
git add -A && git commit -m 'The probe learns to count the cost (v2.474.0)' && git push
```
Paste the baseline budget table into the commit body (single-quoted heredoc via Bash tool to keep PowerShell quoting out of it).

---

### Task 2: B1 rail — `own()` / `zoneTag()` and the stray zone stamps

**Files:**
- Modify: `chauffeur/static/house.js`

**Interfaces:**
- Produces (builder scope, near `mat()`): `function own(m)` — gives mesh `m` a private clone of its material if the material is marked shared; returns `m`. `function zoneTag(m, zone, room)` — stamps `userData.zone` (+ optional `userData.room`) and calls `own(m)`; returns `m`.
- Convention: `material.userData.shared === true` marks a cache-shared material. In this task nothing sets it (the cache lands in Task 3), so `own()` is a no-op rail — pure refactor, behavior identical.

**Why:** Spec L1. ~20 sites stamp `userData.zone` on meshes AFTER creation (outside any `zoneGroup`), so Task 3's cache cannot see them at `mat()` time. The glow loop (`applyState`, `o.material.emissive.setHex` at `:5989`) and `zoneExtra` paint exactly these meshes. Centralizing the stamp in `zoneTag()` makes L1 hold by construction before any sharing exists.

- [ ] **Step 1: Add the helpers**

In `house.js`, directly after the `mat()` function (`:650-666`):

```js
    /* ---- L1 rail (spec 2026-09-10-house-batching-design.md) ----------
       A zone never shares a material: the glow loop writes emissive on
       every mesh a zone owns, wherever it hangs. Materials handed out by
       the cache (Task B1b) carry userData.shared; own() trades a shared
       material for a private clone, and zoneTag() is the ONE way a mesh
       outside a zoneGroup joins a zone. */
    function own(m) {
      if (m && m.isMesh && m.material && m.material.userData &&
          m.material.userData.shared) {
        m.material = m.material.clone();
        m.material.userData.shared = false;
      }
      return m;
    }
    function zoneTag(m, zone, room) {
      if (!m) return m;
      m.userData.zone = zone;
      if (room) m.userData.room = room;
      return own(m);
    }
```

- [ ] **Step 2: Convert every stray stamp site**

Current sites (`grep -n "userData\.zone = " chauffeur/static/house.js`), excluding `:1565` (that is `zoneGroup` itself — leave it):

| line | site | conversion |
|---|---|---|
| 2226, 2247 | `pantryDoor.userData.zone = 'board'` / `pknob...` | `zoneTag(pantryDoor, 'board')` / `zoneTag(pknob, 'board')` |
| 2233, 2236, 2239 | pantry frame pieces `...).userData.zone = 'board'` | wrap the expression: `zoneTag(box(...), 'board')` |
| 2281 | shelf `sh.userData.zone = 'board'` | `zoneTag(sh, 'board')` |
| 2293 | `m.userData.zone = 'board'; m.userData.room = 'kitchen'` | `zoneTag(m, 'board', 'kitchen')` |
| 2372 | `jar.userData.zone = 'board'` | `zoneTag(jar, 'board')` |
| 2925, 3082 | garage `m.userData.room = 'garage'; m.userData.zone = 'garage'` (both orders) | `zoneTag(m, 'garage', 'garage')` |
| 4080 | `busG.userData.zone = 'curb'` (a GROUP) | leave the group stamp, but ALSO keep 4092 per-mesh conversion below — the group stamp routes taps; the mesh stamp is what `zoneExtra` indexes |
| 4092 | bus meshes `m.userData.zone = 'curb'` | `zoneTag(m, 'curb')` |
| 4189 | `grp.userData.zone = 'garage'` (per-car GROUP inside `carsG`) | leave — it is a group; children built into it are covered by Task 3's `inZoneGroup` check |
| 4193 | car plate `m.userData.zone = 'garage'; m.userData.room = 'garage'` | `zoneTag(m, 'garage', 'garage')` |
| 4341 | helper `function gd(m) { if (m) m.userData.zone = 'door'; return m; }` | body becomes `return zoneTag(m, 'door');` (keep the null guard) |
| 4376 | `plaque.userData.zone = 'door'` | `zoneTag(plaque, 'door')` |
| 4658 | helper `function jamb(m) { m.userData.zone = 'door'; return m; }` | `return zoneTag(m, 'door');` |
| 4672 | `m.userData.zone = 'door'; m.userData.room = 'mudroom'; return m;` | `return zoneTag(m, 'door', 'mudroom');` |
| 6128 | `plate.userData.zone = 'garage'` — **runtime**, inside `syncGarage`, module scope where `zoneTag` (builder scope) is not visible | leave the stamp as-is; the plate's material is created fresh in `syncGarage` on every rebuild, never from the cache. Add the comment: `/* fresh material every rebuild: never cache-shared (L1) */` |

Groups stamped at creation via `zoneGroup()` need nothing.

- [ ] **Step 3: Verify identical behavior**

Run from `chauffeur/`:
```
python tests/test_house_live.py
python tools/house_probe.py --views all --budget --quality high --out "%TEMP%\house_batching\t2"
```
Expected: live test OK; budget numbers identical to baseline (same meshes/materials/geometries); screenshots in `t2` visually identical to `baseline` (spot-check exterior + kitchen).

- [ ] **Step 4: Sweep, then commit**

Run: `python tools/test.py` → exit 0.
Bump version to `2.474.1`:
```bash
git add -A && git commit -m 'One way into a zone (v2.474.1)' && git push
```

---

### Task 3: B1 — the material cache

**Files:**
- Modify: `chauffeur/static/house.js`
- Modify: `chauffeur/tests/test_house_live.py`

**Interfaces:**
- Consumes: `own()`/`zoneTag()` and the `material.userData.shared` convention from Task 2; `THREE_WRAP` from Task 1.
- Produces: `mat(c, opts, forceUnique)` — third argument forces a fresh material; cached materials carry `userData.shared = true`. `function inZoneGroup(g)` — true when `g` or any ancestor carries `userData.zone`. Task 7 relies on `userData.shared` to decide mergeability.

- [ ] **Step 1: Write the failing test (sharing invariant, live)**

In `chauffeur/tests/test_house_live.py`, add after the `sys.path` inserts:

```python
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
```

Add at module level:

```python
INVARIANT_JS = """() => {
  const S = window.__hpScene;
  if (!S) return { err: 'no scene captured' };
  const use = new Map();   // material.uuid -> Set of zone-or-'' users
  let meshes = 0;
  S.traverse(o => {
    if (!o.isMesh || !o.material || Array.isArray(o.material)) return;
    meshes += 1;
    let z = '';
    for (let p = o; p; p = p.parent)
      if (p.userData && p.userData.zone) { z = p.userData.zone; break; }
    if (!use.has(o.material.uuid)) use.set(o.material.uuid, new Set());
    use.get(o.material.uuid).add(z);
  });
  let crossing = 0;
  use.forEach(s => { if (s.size > 1) crossing += 1; });
  return { meshes, materials: use.size, crossing };
}"""
```

Inside `scenario_the_house_boots_enters_and_leans_in()`, immediately after `with served.browser() as page:` (BEFORE the `page.goto`), add the route:

```python
        from house_probe import THREE_WRAP
        with open('static/vendor/three.min.js', 'rb') as fh:
            _patched = fh.read() + THREE_WRAP
        page.route('**/three.min.js*', lambda route: route.fulfill(
            status=200, content_type='application/javascript', body=_patched))
```

And at the end of the scenario (after the existing console-error check):

```python
        # L1 (batching spec): no material serves two masters. A material
        # used by any zone mesh is used by that zone alone; scenery
        # sharing is free. And the cache must actually be ON: a scene
        # where every mesh still owns a private material has not batched.
        inv = page.evaluate(INVARIANT_JS)
        check(not inv.get('err'), 'sharing probe captured the scene')
        check(inv['crossing'] == 0,
              'no material crosses a zone boundary: %r' % inv)
        check(inv['materials'] <= inv['meshes'] * 0.5,
              'the material cache is live: %r' % inv)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python tests/test_house_live.py` (from `chauffeur/`)
Expected: FAIL on `the material cache is live` (crossing is already 0 today; materials == meshes because nothing shares yet).

- [ ] **Step 3: Implement the cache**

In `house.js`, restructure `mat()` (`:650`) into a maker plus a cached front:

```js
    var matCache = {};
    function makeMat(c, opts) {
      if (!PBR) {
        var lm = new T.MeshLambertMaterial({ color: c });
        if (opts.map && DETAIL >= 2) lm.map = opts.map;
        return lm;
      }
      var m = new T.MeshStandardMaterial({
        color: c,
        roughness: opts.rough !== undefined ? opts.rough : 0.86,
        metalness: opts.metal !== undefined ? opts.metal : 0.0
      });
      if (opts.map) m.map = opts.map;
      m.envMapIntensity = opts.envInt !== undefined ? opts.envInt
        : (m.metalness > 0.5 ? 1.0 : 0.1);
      return m;
    }
    /* B1 (batching spec): one material per LOOK, not per mesh. The cache
       key is every input makeMat reads. forceUnique is the L1 valve: a
       zone-bound mesh gets a private material the glow loop may paint. */
    function mat(c, opts, forceUnique) {
      opts = opts || {};
      if (forceUnique || opts.unique) return makeMat(c, opts);
      var key = (PBR ? 'p|' : 'l|') + c +
                '|' + (opts.rough !== undefined ? opts.rough : '') +
                '|' + (opts.metal !== undefined ? opts.metal : '') +
                '|' + (opts.envInt !== undefined ? opts.envInt : '') +
                '|' + (opts.map ? opts.map.uuid : '');
      var m = matCache[key];
      if (!m) {
        m = matCache[key] = makeMat(c, opts);
        m.userData.shared = true;
      }
      return m;
    }
    function inZoneGroup(g) {
      for (var p = g; p; p = p.parent)
        if (p.userData && p.userData.zone) return true;
      return false;
    }
```

Thread the valve through the four generic helpers — each currently calls `mat(c, opts)`; each becomes `mat(c, opts, inZoneGroup(group || scene))`:

- `box()` (`:676`): `var g0 = group || scene; var m = new T.Mesh(new T.BoxGeometry(w, h, d), mat(c, opts, inZoneGroup(g0))); ... g0.add(m);`
- `rbox()` (`:699`): same pattern (its `roundedGeo` branch and its `box` fallback both covered).
- `cyl()` (`:704`): same pattern.
- The yard wrappers `yb`/`yr`/`yl` delegate to these ✓ nothing to do. `ysph()` (`:4826`) calls `mat(c, MATT)` directly — it targets `yardG` descendants (never zones): change to `mat(c, MATT, inZoneGroup(g || yardG))` for symmetry.
- Any other direct `mat(...)` call sites (grep `mat(` assignments): materials assigned into meshes that are then added to a zone group or zone-stamped — e.g. `fbody` uses its own `new T.MeshStandardMaterial` (untouched; only `mat()` output is ever cached). Verify with `grep -n "mat(" chauffeur/static/house.js | grep -v "makeMat\|matCache\|format\|animate"` that every call goes through a helper or lands on a non-zone mesh; fix stragglers with the third argument.

Local room helpers (`lb`, `lr`, `lc` in the living-room block, `kPlant`, etc.) delegate to `box`/`rbox`/`cyl` ✓ covered.

- [ ] **Step 4: Run the live test to verify it passes**

Run: `python tests/test_house_live.py`
Expected: PASS — `crossing == 0` (the rail from Task 2 plus `inZoneGroup` hold L1) and materials well under half of meshes.

If `crossing > 0`: the test names nothing, so capture the offenders — temporarily extend `INVARIANT_JS` to also return the first few crossing materials' user zones, find the creation site, and route it through `zoneTag`/`forceUnique`. That is the test doing its job; fix the site, not the assertion.

- [ ] **Step 5: Budget + screenshots**

Run: `python tools/house_probe.py --views all --budget --quality high --out "%TEMP%\house_batching\t3"`
Expected: `materials` drops from 3,310 to low hundreds (the exact floor is the real parameter space — record it); `inFrustum` roughly UNCHANGED (spec: B1 is not expected to move draw calls); `buildMs` same or lower. Compare all five PNGs against baseline:

```
python - <<'PY'
import os
from PIL import Image, ImageChops
base = os.path.expandvars(r'%TEMP%\house_batching\baseline')
new = os.path.expandvars(r'%TEMP%\house_batching\t3')
for f in sorted(os.listdir(base)):
    if not f.endswith('.png'): continue
    a, b = Image.open(os.path.join(base, f)), Image.open(os.path.join(new, f))
    diff = ImageChops.difference(a.convert('RGB'), b.convert('RGB'))
    print(f, diff.getbbox(), max(e[1] for e in diff.getextrema()))
PY
```
Expected: `None` bbox (identical) or peak channel delta < 8 confined to AA edges. Anything larger: STOP, eyeball it, show the user per the pixel policy.

Also verify the scenery knob round-trip: `python tools/house_probe.py --views kitchen --scenery 0 --quality high --out "%TEMP%\house_batching\t3s"` — the printed stats now report a non-zero `clones` count only if a genuinely shared material crosses (should be 0 with L1 holding), and the kitchen shot matches `t3`'s kitchen shot.

- [ ] **Step 6: Sweep, then commit**

Run: `python tools/test.py` → exit 0.
Bump version to `2.475.0`:
```bash
git add -A && git commit -m 'One material per look (v2.475.0)' && git push
```
Include before/after `materials` numbers in the body.

---

### Task 4: B1 — the geometry cache

**Files:**
- Modify: `chauffeur/static/house.js`
- Modify: `chauffeur/tests/test_house_live.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `function cgeo(key, make)` — returns the cached geometry for `key`, building it with `make()` on first use; cached geometries carry `userData.cached = true`. Tasks 5 and 7 rely on shared-geometry identity for bucketing.

- [ ] **Step 1: Extend the invariant test**

In `test_house_live.py`, extend `INVARIANT_JS`'s return with geometry counting — replace the `return { meshes, materials: use.size, crossing };` line and add collection:

```python
INVARIANT_JS = """() => {
  const S = window.__hpScene;
  if (!S) return { err: 'no scene captured' };
  const use = new Map(), geos = new Set();
  let meshes = 0;
  S.traverse(o => {
    if (!o.isMesh || !o.material || Array.isArray(o.material)) return;
    meshes += 1;
    if (o.geometry) geos.add(o.geometry.uuid);
    let z = '';
    for (let p = o; p; p = p.parent)
      if (p.userData && p.userData.zone) { z = p.userData.zone; break; }
    if (!use.has(o.material.uuid)) use.set(o.material.uuid, new Set());
    use.get(o.material.uuid).add(z);
  });
  let crossing = 0;
  use.forEach(s => { if (s.size > 1) crossing += 1; });
  return { meshes, materials: use.size, geometries: geos.size, crossing };
}"""
```

And after the existing invariant checks:

```python
        check(inv['geometries'] <= inv['meshes'] * 0.5,
              'the geometry cache is live: %r' % inv)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python tests/test_house_live.py`
Expected: FAIL on `the geometry cache is live` (geometries still == meshes).

- [ ] **Step 3: Implement**

In `house.js`, next to `matCache`:

```js
    /* B1 (batching spec): geometry is immutable here — every helper sets
       position/rotation/scale on the MESH, so identical dimensions can
       share one BufferGeometry. Also a boot-time win (L7): roundedGeo
       runs a full Shape triangulation per call, and cabinet fronts
       repeat their dimensions dozens of times. */
    var geoCache = {};
    function cgeo(key, make) {
      var g = geoCache[key];
      if (!g) {
        g = geoCache[key] = make();
        g.userData.cached = true;
      }
      return g;
    }
```

Convert the constructors inside the helpers (mesh-level transforms make sharing safe):

- `box()`: `new T.BoxGeometry(w, h, d)` → `cgeo('b|' + w + '|' + h + '|' + d, function () { return new T.BoxGeometry(w, h, d); })`
- `cyl()`: with `var sg = seg || (DETAIL >= 3 ? 18 : 10);` → `cgeo('c|' + rt + '|' + rb + '|' + h + '|' + sg, function () { return new T.CylinderGeometry(rt, rb, h, sg); })`
- `roundedGeo(w, h, d, r)`: wrap its whole body: first line `return cgeo('r|' + w + '|' + h + '|' + d + '|' + r, function () { ...existing body... });` (covers `rbox` and the direct `roundedGeo` call sites like the fridge body).
- `ysph()`: `cgeo('s|' + r + '|' + (Y3 ? 12 : 7) + '|' + (Y3 ? 9 : 5), function () { return new T.SphereGeometry(r, Y3 ? 12 : 7, Y3 ? 9 : 5); })` (tier constants are boot-stable, but keeping them in the key is free insurance).

Guard the one geometry disposal that could now hit a shared object — at `:4372`:

```js
      if (!plaque.geometry.userData.cached) plaque.geometry.dispose();
```

Leave every other `new T.XxxGeometry` site alone (painted faces, sky dome, one-offs — sharing buys nothing there and some are per-payload).

- [ ] **Step 4: Run the live test to verify it passes**

Run: `python tests/test_house_live.py`
Expected: PASS all invariant checks.

- [ ] **Step 5: Budget + screenshots + build time**

Run: `python tools/house_probe.py --views all --budget --quality high --out "%TEMP%\house_batching\t4"`
Expected: `geometries` drops to low hundreds; `buildMs` measurably DOWN (roundedGeo memoization — record the delta, L7); `inFrustum` unchanged; PIL compare vs baseline clean as in Task 3.

- [ ] **Step 6: Sweep, then commit**

Run: `python tools/test.py` → exit 0.
Bump version to `2.475.1`:
```bash
git add -A && git commit -m 'One geometry per shape (v2.475.1)' && git push
```

---

### Task 5: B2 — instance the yard

**Files:**
- Modify: `chauffeur/static/house.js`

**Interfaces:**
- Consumes: shared (geometry, material) identity from Tasks 3–4 — the bucketing key IS object identity, which is why this task needs no knowledge of the shrub/tuft/fence builders.
- Produces: `function instanceYard()` — called once at build, after the yard is fully built, before `applyScenery(0)`. Instanced meshes stay parented under `yardG` (so `yardG.visible = false` and `inYard()` keep working) and set `frustumCulled = false` (instanced bounds are not free; `yardG` hides as a unit indoors and the exterior sees all of it).

**Spec laws in play:** L3 (colour lives in the material — one `InstancedMesh` per (geometry, material) pair, `instanceColor` never used, so `applyScenery` needs zero changes), L4 (zone-stamped curb/bus meshes are skipped and keep routing taps).

- [ ] **Step 1: Implement `instanceYard()`**

In `house.js`, after the yard IIFE completes (after the `tree(...)` back-line calls, before the `skyDome` block), add:

```js
    /* ---- B2 (batching spec): bake the garden into instances ----------
       The yard is ~1,700 meshes drawn one call each, and after B1 its
       repeated props already SHARE geometry and material objects — so
       identical (geometry, material) pairs are the buckets, and no
       builder needs to know it is being instanced. One InstancedMesh per
       pair (L3: tinting stays a material property, applyScenery
       untouched). Zone-stamped meshes (bus, curb) keep their own draw
       so taps keep routing (L4). */
    function instanceYard() {
      var MIN = 8;
      var buckets = {}, kill = [];
      yardG.updateMatrixWorld(true);
      var inv = new T.Matrix4().copy(yardG.matrixWorld).invert();
      yardG.traverse(function (o) {
        if (!o.isMesh || o.isInstancedMesh) return;
        for (var p = o; p && p !== yardG; p = p.parent)
          if (p.userData && p.userData.zone) return;
        if (o.userData.zone) return;
        var k = o.geometry.uuid + '|' + o.material.uuid + '|' +
                (o.castShadow ? 1 : 0) + (o.receiveShadow ? 1 : 0) + '|' +
                (o.renderOrder || 0);
        (buckets[k] = buckets[k] || []).push(o);
      });
      var made = 0, folded = 0;
      Object.keys(buckets).forEach(function (k) {
        var list = buckets[k];
        if (list.length < MIN) return;
        var first = list[0];
        var im = new T.InstancedMesh(first.geometry, first.material,
                                     list.length);
        im.frustumCulled = false;
        im.castShadow = first.castShadow;
        im.receiveShadow = first.receiveShadow;
        im.renderOrder = first.renderOrder;
        var m4 = new T.Matrix4();
        list.forEach(function (o, i) {
          m4.copy(inv).multiply(o.matrixWorld);
          im.setMatrixAt(i, m4);
          kill.push(o);
        });
        im.instanceMatrix.needsUpdate = true;
        yardG.add(im);
        made++; folded += list.length;
      });
      kill.forEach(function (o) { if (o.parent) o.parent.remove(o); });
      (function prune(g) {
        for (var i = g.children.length - 1; i >= 0; i--) {
          var ch = g.children[i];
          if (ch.isGroup) { prune(ch); if (!ch.children.length) g.remove(ch); }
        }
      })(yardG);
      return { made: made, folded: folded };
    }
    instanceYard();
```

Placement note: `instanceYard` must run before the `stampHouse`/tap work of Task 6 exists and before `applyScenery(0)`; putting it immediately after the yard build satisfies both orderings permanently.

- [ ] **Step 2: Budget — the headline number**

Run: `python tools/house_probe.py --views exterior --budget --quality high --out "%TEMP%\house_batching\t5"`
Expected: exterior `inFrustum` drops by ≥1,500 (from ~3,100 toward ~1,500 or lower); `tris` roughly unchanged (instances still counted); no console errors. Record `made`/`folded` by temporarily logging or re-running with the browser console — or simply note the mesh-count delta, which is the same fact.

- [ ] **Step 3: Screenshots + behavior**

Run: `python tools/house_probe.py --views all --budget --quality high --out "%TEMP%\house_batching\t5all"` and PIL-compare vs baseline (Task 3 snippet, `new` pointed at `t5all`).
Expected: exterior pixel-identical or AA-noise only (the planting is deterministic — spec §2: a visible diff here is a FINDING to show the user, stop and do so). Interior views identical (yard hidden). Also run `python tests/test_house_live.py` — PASS (yard hiding on room entry is exercised by every room walk; the sharing invariants still hold — an InstancedMesh `isMesh` is true and its material classifies as scenery).

- [ ] **Step 4: Low-tier check**

Run: `python tools/house_probe.py --views exterior --budget --quality low --out "%TEMP%\house_batching\t5low"`
Expected: no errors; exterior renders; mesh count down versus a fresh low-tier baseline run (`--quality low` against the pre-task commit if in doubt). Low tier has fewer originals (Y2/Y3 loops skipped) but the same mechanism applies.

- [ ] **Step 5: Sweep, then commit**

Run: `python tools/test.py` → exit 0.
Bump version to `2.476.0`:
```bash
git add -A && git commit -m 'The garden learns to draw itself once (v2.476.0)' && git push
```
Body carries the exterior before/after inFrustum numbers.

---

### Task 6: B3 pre — the tap law (L6) and `chfHouseMode`

**Files:**
- Modify: `chauffeur/static/house.js`
- Modify: `chauffeur/tests/test_house_live.py`

**Interfaces:**
- Consumes: `ZONE_ROOM` (module scope, `:6286`) — safe to reference from the builder because `buildRoom` is CALLED after module evaluation.
- Produces: build-time `stampHouse()` (house shell meshes carry `userData.room`), a rewritten exterior branch of `onTap()` with the `position.y` heuristic deleted, and `window.chfHouseMode()` returning `'exterior' | 'kitchen' | 'garage' | 'mudroom' | 'living'` for tests and probes.

**Why now:** merged meshes (Task 7) sit at their group's origin, so `hit.position.y > 0.2` silently stops meaning "the house". The heuristic moves to build time — computed once while every mesh still stands at its own coordinates — and the tap path reads only tags. Two deliberate small behavior changes, named in the commit: a tap on the bus at the curb no longer enters the kitchen (curb maps to no room), and a tap on an overflow car on the driveway now enters the GARAGE rather than the kitchen (its group is zone-tagged `garage`).

- [ ] **Step 1: Write the failing test**

In `test_house_live.py`, inside the scenario right after the `has_room` check (while still at the exterior), add:

```python
        # L6 (batching spec): the house is stamped, not guessed. A tap on
        # the house walks in; a tap on the sky stays a view.
        check(page.evaluate("typeof window.chfHouseMode === 'function'"),
              'chfHouseMode reports the room')
        cbox = page.evaluate(
            "(() => { const r = document.querySelector('#room canvas')"
            ".getBoundingClientRect();"
            " return {x: r.x, y: r.y, w: r.width, h: r.height}; })()")
        page.mouse.click(cbox['x'] + cbox['w'] * 0.5,
                         cbox['y'] + cbox['h'] * 0.55)
        page.wait_for_timeout(1100)
        check(page.evaluate("window.chfHouseMode()") == 'kitchen',
              'a tap on the house walks into the kitchen')
        page.evaluate("window.chfHouseExit()")
        page.wait_for_timeout(1100)
        page.mouse.click(cbox['x'] + 24, cbox['y'] + 24)
        page.wait_for_timeout(1100)
        check(page.evaluate("window.chfHouseMode()") == 'exterior',
              'a tap on the sky stays a view')
```

- [ ] **Step 2: Run to verify it fails**

Run: `python tests/test_house_live.py`
Expected: FAIL at `chfHouseMode reports the room` (the function does not exist yet).

- [ ] **Step 3: Implement**

**(a)** In `house.js`, after `instanceYard();` and after the `skyDome` block (so `skyDome` exists), add:

```js
    /* ---- THE TAP LAW (batching spec L6) -------------------------------
       onTap used to guess "the house" from hit.position.y — a rule that
       dies the moment merged fabric sits at its group's origin, and the
       rule that once let two blob trees open the kitchen. The judgment
       moves HERE, to build time, while every mesh still stands at its
       own coordinates: shell fabric above the plinth is stamped with the
       room it opens (kitchen, unless something nearer already routed
       it), zone-tagged strays borrow their zone's room, and everything
       else out here is scenery. The tap path then reads tags only. */
    extG.updateMatrixWorld(true);
    (function stampHouse() {
      var bb = new T.Box3();
      extG.traverse(function (o) {
        if (!o.isMesh || o === skyDome) return;
        for (var p = o; p && p !== extG; p = p.parent) {
          if (p === yardG) return;                    /* scenery stays a view */
          if (p.userData && p.userData.room) return;  /* already routed */
          if (p.userData && p.userData.zone) {        /* stray: borrow the room */
            var zr = ZONE_ROOM[p.userData.zone];
            if (zr) o.userData.room = zr;
            return;
          }
        }
        bb.setFromObject(o);
        if (bb.max.y > 0.6) o.userData.room = 'kitchen';
      });
    })();
```

**(b)** Rewrite the exterior branch of `onTap()` (`:6543-6556`) to:

```js
    if (mode === 'exterior') {
      /* stamped, not guessed (stampHouse, build time): walk up for a
         room tag; yard and sky stay a view; anything INTERIOR seen
         through the open front is the kitchen. */
      var hit = anyHit(ev.clientX, ev.clientY);
      if (!hit || hit === webgl.skyDome) return;
      var o = hit, room = null;
      while (o) {
        if (o.userData && o.userData.room) { room = o.userData.room; break; }
        o = o.parent;
      }
      if (room && roomsReg()[room]) { enterRoom(room, null); return; }
      if (inYard(hit)) return;                 /* scenery: look, do not enter */
      if (!inExterior(hit)) enterRoom('kitchen', null);
      return;
    }
```

(The `hit.position.y > 0.2` clause is deleted; the `inYard` comment about the garden staying inert survives.)

**(c)** Next to the other `window.chf*` exports (`:6479` area):

```js
  /* read-only, the chfHouseScenery stance: reports, never moves */
  window.chfHouseMode = function () { return mode; };
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python tests/test_house_live.py`
Expected: PASS both new checks and all existing ones. If the house-tap check flakes on framing, nudge the click to `0.5w / 0.6h` — the house fills the exterior frame's centre at every tier.

- [ ] **Step 5: Sweep, then commit**

Run: `python tools/test.py` → exit 0.
Bump version to `2.476.1`:
```bash
git add -A && git commit -m 'The house is stamped, not guessed (v2.476.1)' && git push
```
Body names the two deliberate tap changes (bus inert; driveway car goes to the garage).

---

### Task 7: B3 — merge the static fabric

**Files:**
- Modify: `chauffeur/static/house.js`

**Interfaces:**
- Consumes: `material.userData.shared` (Task 3 — a mesh with an UNSHARED material is somebody's mutation target and is never merged), room tags (Task 6 — merged fabric inherits its bucket's uniform room tag), shared-geometry identity (Task 4).
- Produces: `function mergeGeoms(meshes, originMatrix)` and `function mergeStatic(root, noMerge)`, plus the `NO_MERGE` set. Run once at build, after `stampHouse`, before `applyScenery(0)`.

**Spec laws in play:** L4 (zones merge-exempt — enforced by the zone-ancestor check), L5 (merge only WITHIN a hide-group; the scene-level pass treats every hide-group as a boundary). Hand-rolled merger because `BufferGeometryUtils.mergeBufferGeometries` is NOT in the vendored bundle (the string there is a removal-warning message — verified 2026-09-10).

- [ ] **Step 1: Implement the merger**

In `house.js`, after `stampHouse` (order matters: stamps must exist so buckets can carry them):

```js
    /* ---- B3 (batching spec): merge the static fabric ------------------
       Same material + same shadow flags + same room tag + same
       hide-group = one mesh. Hand-rolled (BufferGeometryUtils is not in
       the vendored bundle): expand to non-indexed, transform into the
       root's space, concatenate. Triangle count is unchanged; draw
       calls collapse. Transparent materials keep their own draws (order
       semantics), unshared materials are somebody's mutation target and
       are skipped, zones are exempt (L4), and each hide-group merges
       only within itself (L5). */
    function mergeGeoms(meshes, originMatrix) {
      var pos = [], nor = [], uv = [];
      var inv = new T.Matrix4().copy(originMatrix).invert();
      var m4 = new T.Matrix4(), n3 = new T.Matrix3(), v = new T.Vector3();
      meshes.forEach(function (o) {
        var g = o.geometry.index ? o.geometry.toNonIndexed() : o.geometry;
        var p = g.attributes.position, n = g.attributes.normal,
            u = g.attributes.uv;
        m4.copy(inv).multiply(o.matrixWorld);
        n3.getNormalMatrix(m4);
        for (var i = 0; i < p.count; i++) {
          v.fromBufferAttribute(p, i).applyMatrix4(m4);
          pos.push(v.x, v.y, v.z);
          if (n) {
            v.fromBufferAttribute(n, i).applyMatrix3(n3).normalize();
            nor.push(v.x, v.y, v.z);
          }
          if (u) uv.push(u.getX(i), u.getY(i)); else uv.push(0, 0);
        }
        if (g !== o.geometry) g.dispose();   /* the temp non-indexed copy */
      });
      var out = new T.BufferGeometry();
      out.setAttribute('position', new T.Float32BufferAttribute(pos, 3));
      if (nor.length)
        out.setAttribute('normal', new T.Float32BufferAttribute(nor, 3));
      out.setAttribute('uv', new T.Float32BufferAttribute(uv, 2));
      return out;
    }
    function mergeStatic(root, noMerge) {
      root.updateMatrixWorld(true);
      var buckets = {};
      root.traverse(function (o) {
        if (!o.isMesh || o.isInstancedMesh) return;
        if (noMerge.has(o)) return;
        for (var p = o; p && p !== root.parent; p = p.parent) {
          if (p !== o && noMerge.has(p)) return;
          if (p.userData && p.userData.zone) return;       /* L4 */
        }
        if (!o.material.userData || !o.material.userData.shared) return;
        if (o.material.transparent) return;
        var roomTag = '';
        for (var q = o; q && q !== root.parent; q = q.parent)
          if (q.userData && q.userData.room) { roomTag = q.userData.room; break; }
        var k = o.material.uuid + '|' + (o.castShadow ? 1 : 0) +
                (o.receiveShadow ? 1 : 0) + '|' + (o.renderOrder || 0) +
                '|' + roomTag;
        (buckets[k] = buckets[k] || []).push(o);
      });
      Object.keys(buckets).forEach(function (k) {
        var list = buckets[k];
        if (list.length < 4) return;
        var first = list[0];
        var mm = new T.Mesh(mergeGeoms(list, root.matrixWorld),
                            first.material);
        mm.castShadow = first.castShadow;
        mm.receiveShadow = first.receiveShadow;
        mm.renderOrder = first.renderOrder;
        var rt = k.split('|')[3];
        if (rt) mm.userData.room = rt;
        root.add(mm);
        list.forEach(function (o) { if (o.parent) o.parent.remove(o); });
      });
    }
    /* Dynamic and painted things keep their own draws: state repaints
       their maps, toggles their visibility, or rebuilds them wholesale. */
    var NO_MERGE = new Set([carsG, busG, mudBagsG, magnets, skyDome,
      calFace, boardFace, critFace, radioFace, paneMesh, plaque, needle,
      steam, steam2, pendants, fridgeDoorTop, pantryDoor]);
    (pantryJars || []).forEach(function (j) { NO_MERGE.add(j); });
    [westWallG, garageDoorG, mudroomRoofG, yardG].forEach(function (g) {
      mergeStatic(g, NO_MERGE);
    });
    var TOP = new Set(NO_MERGE);
    [westWallG, garageDoorG, mudroomRoofG, livingRoofG, yardG]
      .forEach(function (g) { TOP.add(g); });
    mergeStatic(scene, TOP);
```

Note on `Set`: the vendored codebase already relies on ES2015 runtime objects in this file (`Map`/`Set` are safe in every browser that runs WebGL here; the ES5 constraint is about SYNTAX for the old parser, not library objects). If review of the file shows `Set` unused so far and doubt about the parser floor, substitute a plain array + `indexOf` — behavior identical, the lists are short.

Build-order recap (final, all tasks landed): yard build → `instanceYard()` → `skyDome` → `stampHouse()` → `mergeStatic` block → … → `applyScenery(0)` → `zoneExtra` scan → `return {…}` export. The `zoneExtra` scan and export come after merging, so exported references (`calFace` etc.) are the surviving originals — which is exactly why they sit in `NO_MERGE`.

- [ ] **Step 2: Full functional pass**

Run: `python tests/test_house_live.py`
Expected: PASS everything — boots, tap law (merged fabric carries room tags), every room enters, calendar/door/radio lean-ins mount their cards, sharing invariants hold (merged meshes wear shared materials, zone materials untouched), no console errors.

- [ ] **Step 3: Budget + screenshots — the payoff**

Run: `python tools/house_probe.py --views all --budget --quality high --out "%TEMP%\house_batching\t7"`
Expected: kitchen/living `inFrustum` drop materially (the ~350 loose fabric meshes plus grouped statics collapse — spec expectation: rooms roughly halve; record the real numbers); exterior drops further (roof/siding/street fold). `tris` unchanged (merge adds no triangles; non-indexed expansion does not change the count). PIL-compare all five views + `lean_calendar`, `lean_board`, `lean_radio` (`--views lean_calendar,lean_board,lean_radio`) against baseline. Shadow acne or missing shadows on merged fabric = bucket flag bug — check `castShadow`/`receiveShadow` splits before touching biases.

- [ ] **Step 4: Room-walk visibility check**

Run: `python tools/house_probe.py --views mudroom,garage,living --quality high --out "%TEMP%\house_batching\t7rooms"`
Expected: mudroom shows NO west wall and NO mudroom roof (their merged replacements hide with their groups — this is L5 working); garage shows no door; living shows no yard. Compare against baseline's same views.

- [ ] **Step 5: Sweep, then commit**

Run: `python tools/test.py` → exit 0.
Bump version to `2.477.0`:
```bash
git add -A && git commit -m 'The fabric draws as one cloth (v2.477.0)' && git push
```
Body carries the full before/after budget table.

---

### Task 8: Wrap-up — numbers into the spec, capabilities check

**Files:**
- Modify: `docs/superpowers/specs/2026-09-10-house-batching-design.md`
- Maybe modify: `chauffeur/system_capabilities.md`

- [ ] **Step 1: Append the results to the spec**

Add a final section `## 9. Results (implemented v2.474.0–v2.477.0)` with the measured before/after table (all five views: inFrustum, materials, geometries, buildMs) and one line per deliberate behavior change (bus tap inert; driveway car tap → garage).

- [ ] **Step 2: Capabilities doc**

`grep -in "house\|kitchen\|dollhouse" chauffeur/system_capabilities.md` — if a house/kitchen UI section exists, add one line noting the draw-budget tool (`tools/house_probe.py --budget`) and that the scene batches (materials/geometries cached, garden instanced, fabric merged). If no such section exists, skip — do not invent one.

- [ ] **Step 3: Final verification**

Run: `python tools/test.py` → exit 0 (docs-only changes do not require it, but this is the arc's closing gate — run it once more anyway, plus `python tools/house_probe.py --views all --budget --quality high --out "%TEMP%\house_batching\final"` for the numbers quoted in Step 1).

- [ ] **Step 4: Commit**

Bump version to `2.477.1`:
```bash
git add -A && git commit -m 'Write down what the batching bought (v2.477.1)' && git push
```

---

## Self-review notes (already applied)

- **Spec coverage:** B0→Task 1, B1→Tasks 2–4, B2→Task 5, B3→Tasks 6–7 (L6 explicitly before the merge, as the spec requires), results/§6 unlocks→Task 8. L1 has a live invariant test; L2 verified by the scenery round-trip in Task 3 Step 5; L3 honored by bucketing per (geometry, material); L4/L5 encoded as guards in `instanceYard`/`mergeStatic`; L6 is Task 6; L7 tracked via `buildMs` in every budget run.
- **Type consistency:** `THREE_WRAP`/`BUDGET_JS`/`INVARIANT_JS` names match between Tasks 1, 3, 4; `mat(c, opts, forceUnique)` signature consistent across Tasks 3–7; `userData.shared` / `userData.cached` conventions used identically in Tasks 3, 4, 7.
- **Known judgment calls an executor must NOT re-litigate:** transparent materials never merge; `MIN` thresholds (8 instancing / 4 merging); `frustumCulled = false` on yard instances; plate stamp at `:6128` stays a raw stamp with a comment.

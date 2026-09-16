# View-Volume Masking + Roof Valleys Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A room's shell cutaway becomes a geometric mask (camera pyramid over the room's eave-high box, minus the wedge behind its camera-facing faces) computed once per room at build time and swapped at settle; the same clipper cuts facade gables and dormers at the roof they sit on.

**Architecture:** A pure triangle clipper (`house_clip.js`) cuts convex meshes against planes and caps the cut. `buildRoomShells()` in `house.js` runs after the last `regFabric` and before `mergeStatic`: for each of the five room cameras it clips every fabric mesh, clones the kept triangles into a per-room shell group (original material + one shared cap material), merges it with `mergeStatic`, and `bakeAO` bakes it with the rest. `solveShell(camPos, subject)` keeps its name and call sites but now only swaps which shell group is visible. Verdicts, owners, cutawayRoom, twoSided, the corridor rule and the x 6.85 splits are retired. `gableAt`/`dormerAt` clip their decks to the parent roof plane with the same clipper.

**Tech Stack:** three.js (vendored) in `house.js`; a new plain-JS module `chauffeur/static/house_clip.js` loaded by `house.html` before `house.js`; Python/FastAPI services; Playwright live tests (`tests/live_app.py`, standalone scenario scripts); `tools/house_probe.py` for budgets and PNGs.

**Spec:** `docs/superpowers/specs/2026-09-16-house-view-volume-masking-design.md` (binding). Read §2–§4 before Task 3, §5 before Task 4, §6 before Task 5.

## Global Constraints

- Every code task ends with: read `chauffeur/config.yaml` `version:`, bump the patch, verify with `grep ^version chauffeur/config.yaml`; the COMMIT GATE (user ruling 2026-09-16): `env -u HA_BASE_URL python chauffeur/tools/test.py --focus` from the repo root PLUS the live file(s) the task touched (`cd chauffeur && env -u HA_BASE_URL python tests/test_house_live.py` etc.), foreground, never two concurrent runs, never piped; commit with the version in the subject `(vX.Y.Z)`; push. The FULL sweep (`env -u HA_BASE_URL python chauffeur/tools/test.py`, timeout 600000) runs once, at Task 7's commit. Known parallel-load flakes (re-run solo only if they are the only reds): `test_screensaver`, `test_study_live`, `test_negotiation_cost`, `test_trip_scheduler`. Commit messages in prose, via a Bash heredoc, ending `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- house.js laws: every geometry through `cgeo` (keys carry every input), every material through `mat()`/`box()` opts, `mkTex` owns textures (the file's only texture dispose lives in mkTex), no per-frame work, render-on-demand; every shell piece registers through `shellRegister`/`regFabric`; ghost edges stay OFF; palette hex only in `PALETTE`; the cap material is ONE shared `MeshStandardMaterial` created once (`CAP_MAT`, colour from the palette table as `PALETTE.section` / `pal('section', …)`).
- Mask definition (spec §2): B = room AABB, footprint × floor-to-EAVE (`EXT_TOP4` = 5.6); front faces = outward normal toward the camera; P = pyramid through the camera and B's silhouette edges; W = intersection of half-spaces behind each front-face plane; masked = P ∩ ¬W. Shell only. Caps one neutral tone. Lean-ins keep the room mask. Exterior/orbit = full shell.
- Never drop functionality: every `regFabric` name and `room` stays for taps; markers and `chfNavProbe` keep working; the kitchen camera `(4.64, 13.8, 23.0)` and the study camera `(7.02, 4.75, 18.82)` stay.
- Budgets (quality=high `--day`): `buildMs` ≤ 1500 including the five room shells; exterior and every orbit stop unchanged; per-room in-frustum re-baselined and recorded.
- Tests are standalone scripts (`from harness import check`, `scenario_*`, runner at the bottom). Live: `cd chauffeur && env -u HA_BASE_URL python tests/test_house_live.py`. Probe: `cd chauffeur && env -u HA_BASE_URL python tools/house_probe.py --views all --budget --quality high --day --out ../scratch/<name>`. Look at every PNG you cite.
- `HA_BASE_URL` is exported by the dev shell: every test/probe run uses `env -u HA_BASE_URL`. Never round-trip source through PowerShell `Get-Content`/`Set-Content`.

---

## File map

| file | responsibility |
|---|---|
| `chauffeur/static/house_clip.js` (new) | pure clipper: `clipTris`, `subtractTris`, `maskPlanes`, `pointMasked`, `triArea` — no scene state |
| `chauffeur/templates/house.html` | `<script src=".../house_clip.js">` before `house.js` |
| `chauffeur/static/house.js` | `userData.convex` stamps; `CAP_MAT`; `buildRoomShells`; `solveShell` → swap; `chfShellFabric` `maskedFraction`; retire owners/splits; `gableAt`/`dormerAt` valley clip; exposures |
| `chauffeur/services/house_facade.py`, `chauffeur/tests/test_house_facade.py` | retire `STUDY_SLOTS`/`slot_owners`/`owners` |
| `chauffeur/tests/test_house_live.py` | clipper scenario, mask pins, registry/mesh pins re-recorded, valley pin, verdict tables removed |
| `chauffeur/tests/test_house_life_live.py` | `verdict` reads → `maskedFraction` |
| `chauffeur/tools/house_probe.py` | unchanged unless `--roof` needs a note |
| `chauffeur/system_capabilities.md`, `docs/house_style_bible.md`, spec §9 | wrap |

---

### Task 1: The clipper module

**Files:**
- Create: `chauffeur/static/house_clip.js`
- Modify: `chauffeur/templates/house.html` (script tag before `house.js`; find the existing `house_study.js`/`house_features.js` tags and add beside them)
- Test: `chauffeur/tests/test_house_live.py` (new `scenario_clipper_cuts_convex_meshes`, evaluated in the browser)

**Interfaces:**
- Produces `window.HouseClip` with:
  - `clipTris(tris, plane, capSlot)` → `tris`. A tri is `{a, b, c, slot}` where each vertex is `{p:[x,y,z], uv:[u,v]}`; `plane` is `{n:[x,y,z], d}` and the KEPT side is `n·p − d ≥ 0`. Returns the kept triangles (clipped polygons re-fanned) plus the cap triangles (slot `capSlot`) built from the intersection loop.
  - `subtractTris(tris, planes, capSlot)` → `tris`: the part OUTSIDE the convex region `∩ planes` (sequential splitting, no overlaps).
  - `maskPlanes(cam, box)` → `{P: plane[], W: plane[]}` for `cam=[x,y,z]`, `box=[minx,maxx,miny,maxy,minz,maxz]`.
  - `pointMasked(p, planes)` → bool: inside every P plane and outside at least one W plane.
  - `triArea(tris, slot)` → summed area of triangles with that slot (omit slot → all).

- [ ] **Step 1: Write the failing scenario.** Add to `tests/test_house_live.py` (before the runner; register it in `__main__`):

```python
def scenario_clipper_cuts_convex_meshes():
    """Spec 2026-09-16 masking §3: the clipper is exact on a unit cube."""
    served = live_app(_seed)
    if served is None:
        return
    with served.browser() as page:
        page.goto(served.url('house?quality=low'))
        page.wait_for_selector('#room canvas', timeout=20000)
        r = page.evaluate("""() => {
          const C = window.HouseClip;
          if (!C) return {missing: true};
          const v = (x,y,z,u=0,w=0) => ({p:[x,y,z], uv:[u,w]});
          // unit cube 0..1, twelve triangles, slot 0, outward winding
          const q = (a,b,c,d) => [{a,b,c,slot:0},{a,b:c,c:d,slot:0}];
          const P = [v(0,0,0),v(1,0,0),v(1,1,0),v(0,1,0),v(0,0,1),v(1,0,1),v(1,1,1),v(0,1,1)];
          const tris = [].concat(
            q(P[0],P[3],P[2],P[1]), q(P[4],P[5],P[6],P[7]),   // z=0 (facing -z), z=1
            q(P[0],P[1],P[5],P[4]), q(P[3],P[7],P[6],P[2]),   // y=0, y=1
            q(P[0],P[4],P[7],P[3]), q(P[1],P[2],P[6],P[5]));  // x=0, x=1
          const area0 = C.triArea(tris, 0);
          const half = C.clipTris(tris, {n:[1,0,0], d:0.5}, 1);   // keep x >= 0.5
          const kept0 = C.triArea(half, 0), cap = C.triArea(half, 1);
          const out = C.subtractTris(tris, [{n:[1,0,0], d:0.5}, {n:[0,1,0], d:0.5}], 1);
          const outArea = C.triArea(out, 0);
          const m = C.maskPlanes([0, 10, 10], [-1, 1, 0, 2, -1, 1]);
          return {area0, kept0, cap, outArea, nP: m.P.length, nW: m.W.length,
                  inside: C.pointMasked([0, 5, 5], m), behind: C.pointMasked([0, 1, -3], m),
                  outsideCone: C.pointMasked([8, 5, 5], m)};
        }""")
        check(not r.get('missing'), 'window.HouseClip is loaded on /house')
        check(abs(r['area0'] - 6.0) < 1e-6, f"unit cube area 6, got {r['area0']}")
        check(abs(r['kept0'] - 3.0) < 1e-6, f"half cube keeps 3 of the original faces' area, got {r['kept0']}")
        check(abs(r['cap'] - 1.0) < 1e-6, f"one unit cap, got {r['cap']}")
        check(abs(r['outArea'] - 4.5) < 1e-6, f"cube minus its +x+y quarter keeps 4.5 original area, got {r['outArea']}")
        check(r['nP'] >= 4 and r['nW'] >= 1, f"mask planes built: P {r['nP']} W {r['nW']}")
        check(r['inside'] is True, 'a point between the camera and the box is masked')
        check(r['behind'] is False, 'a point beyond the box is kept')
        check(r['outsideCone'] is False, 'a point outside the silhouette is kept')
```

Derivations for the numbers: keeping x ≥ 0.5 keeps the x=1 face (1) and half of each of the four faces y=0, y=1, z=0, z=1 (4 × 0.5 = 2) and drops the x=0 face: **3.0** of original area, plus a **1.0** cap. Cube minus the quarter x ≥ 0.5 ∧ y ≥ 0.5: the removed original area is a quarter of z=0 and z=1 (2 × 0.25) and half of x=1 and y=1 (2 × 0.5): 1.5 removed → **4.5** kept. `pointMasked(p, m)` takes the whole mask object `{P, W}`.

- [ ] **Step 2: Run it → RED** (`window.HouseClip` missing). Command: `cd chauffeur && env -u HA_BASE_URL python tests/test_house_live.py` (or run the single scenario if the runner accepts a name; read the runner).

- [ ] **Step 3: Write `chauffeur/static/house_clip.js`.**

```js
/* House clipper (spec 2026-09-16 view-volume masking §3). Pure functions on
   triangle soups: a tri is {a,b,c,slot}, a vertex {p:[x,y,z], uv:[u,v]}, a
   plane {n:[x,y,z], d} whose KEPT side is n·p - d >= 0. No scene state. */
(function () {
  'use strict';
  var EPS = 1e-7;
  function dot(a, b) { return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]; }
  function sub(a, b) { return [a[0]-b[0], a[1]-b[1], a[2]-b[2]]; }
  function cross(a, b) { return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]; }
  function norm(a) { var l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0]/l, a[1]/l, a[2]/l]; }
  function side(pl, v) { return dot(pl.n, v.p) - pl.d; }
  function lerp(v0, v1, t) {
    return { p: [v0.p[0]+(v1.p[0]-v0.p[0])*t, v0.p[1]+(v1.p[1]-v0.p[1])*t, v0.p[2]+(v1.p[2]-v0.p[2])*t],
             uv: [v0.uv[0]+(v1.uv[0]-v0.uv[0])*t, v0.uv[1]+(v1.uv[1]-v0.uv[1])*t] };
  }
  /* Sutherland–Hodgman on one polygon; returns the kept polygon and the
     (at most one) edge where the plane crossed it. */
  function clipPoly(poly, pl) {
    var out = [], crossings = [];
    for (var i = 0; i < poly.length; i++) {
      var cur = poly[i], nxt = poly[(i + 1) % poly.length];
      var sc = side(pl, cur), sn = side(pl, nxt);
      if (sc >= -EPS) out.push(cur);
      if ((sc >= -EPS) !== (sn >= -EPS)) {
        var t = sc / (sc - sn);
        var x = lerp(cur, nxt, t);
        out.push(x); crossings.push(x);
      }
    }
    return { poly: out, crossings: crossings };
  }
  function fan(poly, slot) {
    var tris = [];
    for (var i = 1; i + 1 < poly.length; i++) tris.push({ a: poly[0], b: poly[i], c: poly[i + 1], slot: slot });
    return tris;
  }
  /* The cut of a CONVEX solid by a plane is a convex polygon: collect every
     crossing point, order them around their centroid in the plane, fan. */
  function cap(points, pl, capSlot) {
    if (points.length < 3) return [];
    var c = [0, 0, 0];
    points.forEach(function (v) { c[0] += v.p[0]; c[1] += v.p[1]; c[2] += v.p[2]; });
    c = [c[0]/points.length, c[1]/points.length, c[2]/points.length];
    var ax = norm(sub(points[0].p, c)), ay = cross(pl.n, ax);
    var ordered = points.slice().sort(function (u, v) {
      var du = sub(u.p, c), dv = sub(v.p, c);
      return Math.atan2(dot(du, ay), dot(du, ax)) - Math.atan2(dot(dv, ay), dot(dv, ax));
    });
    /* de-duplicate coincident crossings (shared edges produce pairs) */
    var uniq = [];
    ordered.forEach(function (v) {
      var last = uniq[uniq.length - 1];
      if (!last || Math.hypot(last.p[0]-v.p[0], last.p[1]-v.p[1], last.p[2]-v.p[2]) > 1e-6) uniq.push(v);
    });
    if (uniq.length < 3) return [];
    /* the cap faces OUT of the kept solid, i.e. along -n */
    var t = fan(uniq.map(function (v) { return { p: v.p, uv: [0, 0] }; }), capSlot);
    var n0 = cross(sub(t[0].b.p, t[0].a.p), sub(t[0].c.p, t[0].a.p));
    if (dot(n0, pl.n) > 0) t = t.map(function (x) { return { a: x.a, b: x.c, c: x.b, slot: x.slot }; });
    return t;
  }
  function clipTris(tris, pl, capSlot) {
    var kept = [], crossings = [];
    tris.forEach(function (t) {
      var r = clipPoly([t.a, t.b, t.c], pl);
      if (r.poly.length >= 3) kept = kept.concat(fan(r.poly, t.slot));
      crossings = crossings.concat(r.crossings);
    });
    if (capSlot !== undefined && capSlot !== null) kept = kept.concat(cap(crossings, pl, capSlot));
    return kept;
  }
  function flip(pl) { return { n: [-pl.n[0], -pl.n[1], -pl.n[2]], d: -pl.d }; }
  /* Everything OUTSIDE the convex region bounded by `planes`, as disjoint
     pieces: outside plane 1; then (inside 1) outside 2; and so on. */
  function subtractTris(tris, planes, capSlot) {
    var out = [], rest = tris;
    planes.forEach(function (pl) {
      out = out.concat(clipTris(rest, flip(pl), capSlot));
      rest = clipTris(rest, pl, capSlot);
    });
    return out;
  }
  function triArea(tris, slot) {
    var s = 0;
    tris.forEach(function (t) {
      if (slot !== undefined && t.slot !== slot) return;
      var c = cross(sub(t.b.p, t.a.p), sub(t.c.p, t.a.p));
      s += 0.5 * Math.hypot(c[0], c[1], c[2]);
    });
    return s;
  }
  /* Mask planes (spec §2). box = [minx,maxx,miny,maxy,minz,maxz]. */
  function maskPlanes(cam, box) {
    var mn = [box[0], box[2], box[4]], mx = [box[1], box[3], box[5]];
    var ctr = [(mn[0]+mx[0])/2, (mn[1]+mx[1])/2, (mn[2]+mx[2])/2];
    var corner = function (i) { return [(i & 1) ? mx[0] : mn[0], (i & 2) ? mx[1] : mn[1], (i & 4) ? mx[2] : mn[2]]; };
    /* faces: axis, sign, corner indices in a ring */
    var faces = [
      { n: [-1,0,0], ring: [0,4,6,2] }, { n: [1,0,0], ring: [1,3,7,5] },
      { n: [0,-1,0], ring: [0,1,5,4] }, { n: [0,1,0], ring: [2,6,7,3] },
      { n: [0,0,-1], ring: [0,2,3,1] }, { n: [0,0,1], ring: [4,5,7,6] }];
    var front = faces.map(function (f) {
      var fc = corner(f.ring[0]);
      return dot(f.n, sub(cam, fc)) > 0;
    });
    var W = [];
    faces.forEach(function (f, i) {
      if (!front[i]) return;
      var fc = corner(f.ring[0]);
      /* keep side = behind the face (box side): -n·p + n·fc >= 0 */
      W.push({ n: [-f.n[0], -f.n[1], -f.n[2]], d: -dot(f.n, fc) });
    });
    /* silhouette edges: shared by one front and one back face */
    var P = [], seen = {};
    faces.forEach(function (f, i) {
      for (var k = 0; k < 4; k++) {
        var a = f.ring[k], b = f.ring[(k + 1) % 4];
        var key = Math.min(a, b) + '-' + Math.max(a, b);
        if (seen[key] !== undefined) {
          if (front[seen[key]] !== front[i]) {
            var pa = corner(a), pb = corner(b);
            var n = norm(cross(sub(pa, cam), sub(pb, cam)));
            var d = dot(n, cam);
            if (dot(n, ctr) - d < 0) { n = [-n[0], -n[1], -n[2]]; d = -d; }
            P.push({ n: n, d: d });
          }
        } else seen[key] = i;
      }
    });
    return { P: P, W: W };
  }
  function pointMasked(p, m) {
    var v = { p: p };
    for (var i = 0; i < m.P.length; i++) if (side(m.P[i], v) < -EPS) return false;
    for (var j = 0; j < m.W.length; j++) if (side(m.W[j], v) < -EPS) return true;
    return false;
  }
  window.HouseClip = { clipTris: clipTris, subtractTris: subtractTris, triArea: triArea,
                       maskPlanes: maskPlanes, pointMasked: pointMasked, flip: flip };
})();
```

The `ring` orders were chosen so each face's ring is counter-clockwise seen from outside; the implementer verifies one face by hand (e.g. `{n:[0,0,1], ring:[4,5,7,6]}` → corners (0,0,1),(1,0,1),(1,1,1),(0,1,1)) and fixes any ring that is not. `subtractTris` and the `cap` only assume the solid is convex, which every fabric mesh cut in Task 3 is.

- [ ] **Step 4: Load it.** In `house.html`, add `<script src="{{ url_for('static', path='house_clip.js') }}"></script>` (match the exact idiom of the neighbouring `house_study.js` tag, including any cache-busting query) BEFORE `house.js`.

- [ ] **Step 5: Run the scenario → GREEN.** Fix the ring orientation or the cap winding until the areas match to 1e-6.

- [ ] **Step 6: Sweep, bump, commit, push** — `feat: house_clip.js — convex triangle clipper with caps and the room mask planes (vX.Y.Z)`.

---

### Task 2: Convex stamps and world-space triangle extraction

**Files:**
- Modify: `chauffeur/static/house.js` — `box()` (~1189-1208), `shellBox` (~4609), the extrude sites in `shellGable` (hip decks ~4700-4750, hip ends ~4795, gable-end infill ~4789-4806), `vaultSection` (~4380-4430), any other `ExtrudeGeometry`/`ShapeGeometry` inside a fabric group (grep `ExtrudeGeometry` and `ShapeGeometry` between the first `shellGroup()` and `mergeStatic`).
- Test: `chauffeur/tests/test_house_live.py` (`scenario_every_fabric_mesh_is_convex_or_a_kit`)

**Interfaces:**
- Produces: `mesh.userData.convex === true` on every convex fabric mesh; `regFabric(group, o)` accepts `o.kit === true` (doors, windows, porch, lamp kits — treated whole); a house.js helper `worldTris(mesh)` → `tris` (world-space, `uv` from the geometry's `uv` attribute, `slot 0`) for indexed and non-indexed geometry; exposure `window.chfFabricConvexity()` → `[{name, meshes, convex, kit}]`.

- [ ] **Step 1: RED.** Add the scenario: load `/house?quality=high`, wait for settle, evaluate `window.chfFabricConvexity()`; `check` that every row has `convex === meshes` or `kit === true`, and that at least one row is a kit (`living_study_door`) and at least one is fully convex (`south_wall`). Run → RED (`chfFabricConvexity` missing).

- [ ] **Step 2: Stamp.** In `box()` after the mesh is created: `m.userData.convex = true;` (a chamfered `rbox` is convex too). In each extrude site in `shellGable`/`vaultSection`: `deck.userData.convex = true;` (the trapezoid, triangle and pentagon shapes are convex; comment that fact at each site). `regFabric`: `kit: !!o.kit`; `shellRegister(g, name, normal, room, twoSided, pad, cutawayRoom, owners, kit)` passes `kit` through; the facade `windowAt`/`doorAt`/`porchAt`/`garageDoorAt` and the two `house_features.js` door fixtures register with `kit: true` (find the `webgl.registerFabric` path ~9541 and pass `spec.kit`). `worldTris(mesh)`:

```js
function worldTris(mesh) {
  var g = mesh.geometry, pos = g.getAttribute('position'), uv = g.getAttribute('uv');
  mesh.updateWorldMatrix(true, false);
  var M = mesh.matrixWorld, tris = [], tmp = new T.Vector3();
  function vert(i) {
    tmp.fromBufferAttribute(pos, i).applyMatrix4(M);
    return { p: [tmp.x, tmp.y, tmp.z], uv: uv ? [uv.getX(i), uv.getY(i)] : [0, 0] };
  }
  var n = g.index ? g.index.count : pos.count;
  for (var i = 0; i < n; i += 3) {
    var i0 = g.index ? g.index.getX(i) : i, i1 = g.index ? g.index.getX(i + 1) : i + 1, i2 = g.index ? g.index.getX(i + 2) : i + 2;
    tris.push({ a: vert(i0), b: vert(i1), c: vert(i2), slot: 0 });
  }
  return tris;
}
```

`chfFabricConvexity`: for each FABRIC row, traverse `f.g` counting meshes and meshes with `userData.convex`.

- [ ] **Step 3: GREEN.** Run the scenario. Any non-kit row with a non-convex mesh: either stamp it (if it is convex) or mark the row `kit`. List every row you marked `kit` in the report.

- [ ] **Step 4: Sweep, bump, commit, push** — `feat: fabric meshes declare convexity; kits are whole (vX.Y.Z)`.

---

### Task 3: Room shells — build, swap, report

**Files:**
- Modify: `chauffeur/static/house.js` — `regFabric` (~957), `solveShell` (~1042), the build tail (after the last `regFabric`/`refabBox` and BEFORE `FABRIC.forEach(function (f) { mergeStatic(f.g, NO_MERGE); })` ~8606; `bakeAO` ~8830), `ROOM_AABB` (~9732-9757), `chfShellFabric` (~10793-10816), exposures.
- Test: `chauffeur/tests/test_house_live.py` (`scenario_room_masks_cut_only_what_blocks_the_room`), `chauffeur/tests/test_house_life_live.py:91` (`verdict` → `maskedFraction`)

**Interfaces:**
- Consumes: `HouseClip` (Task 1), `userData.convex`, `kit`, `worldTris` (Task 2).
- Produces: `f.shells = { kitchen: {group, fraction}, living: …, study: …, garage: …, mudroom: … }` per fabric row; `webgl.roomShellGroups = {room: THREE.Group}`; `solveShell(camPos, subject)` shows the subject room's shell and hides the full shell (`subject === null` → full shell); `chfShellFabric()` rows carry `maskedFraction: {kitchen: 0.42, …}` and keep `verdict` only as `'solid'|'masked'` for the CURRENT view (`masked` when fraction > 0); `window.chfRoomMask(room)` → `{P, W, box}`; `CAP_MAT`.

- [ ] **Step 1: RED scenario.**

```python
ROOMS = ['kitchen', 'living', 'study', 'garage', 'mudroom']

def scenario_room_masks_cut_only_what_blocks_the_room():
    """Spec 2026-09-16 masking §2/§7: per room, only what stands between the
    camera and the room's eave-high box is cut; everything else is whole."""
    served = live_app(_seed)
    if served is None:
        return
    with served.browser() as page:
        page.add_init_script(DAY_LOCK_JS)
        page.goto(served.url('house?quality=high'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        fab = page.evaluate('window.chfShellFabric()')
        by = {f['name']: f for f in fab}
        check('maskedFraction' in by['south_wall'], 'rows report maskedFraction per room')
        def frac(name, room):
            return by[name]['maskedFraction'][room]
        # the great room: its street wall and the roof over it come off, the study's do not
        for room in ('kitchen', 'living'):
            check(frac('south_wall', room) > 0.3, f'{room}: south_wall mostly cut, got {frac("south_wall", room)}')
            check(frac('roof_main_south', room) > 0.2, f'{room}: roof_main_south cut over the room')
            for whole in ('east_partition', 'east_wall', 'north_wall_east', 'future_room_partition',
                          'facade_main_window_15', 'facade_main_window_16', 'north_wall', 'yard'):
                check(frac(whole, room) == 0, f'{room}: {whole} untouched, got {frac(whole, room)}')
        # the study: its own street face and roof, nothing of the great room's
        check(frac('east_partition', 'study') > 0.3, 'study: the partition between camera and room is cut')
        check(frac('south_wall', 'study') > 0.1, 'study: its street face (part of south_wall) is cut')
        check(frac('facade_main_window_7', 'study') == 0, 'study: the great room window is whole')
        check(frac('north_wall', 'study') == 0, 'study: the kitchen north wall is whole')
        # the mudroom: only its part of the garage-block roof
        check(0 < frac('garage_block_roof_south', 'mudroom') < 0.8, 'mudroom: a PART of the garage-block south deck, not all of it')
        check(frac('garage_shell', 'mudroom') == 0 or frac('garage_shell', 'mudroom') < 0.5, 'mudroom: the garage walls mostly whole')
        # exterior: nothing masked
        page.evaluate('window.chfHouseExit()')
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        fab = page.evaluate('window.chfShellFabric()')
        check(all(f['verdict'] == 'solid' for f in fab), 'exterior: every piece solid')
        # each room view shows its shell; the swap happened
        for room in ROOMS:
            page.evaluate(f"window.chfHouseEnterRoom('{room}')")
            page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
            shown = page.evaluate('window.chfRoomShellShown()')
            check(shown == room, f'{room}: its room shell is the visible one (got {shown})')
            # sampled kept vertices lie outside the mask
            bad = page.evaluate(f"window.chfRoomShellLeak('{room}', 2000)")
            check(bad == 0, f'{room}: no kept vertex inside the mask (got {bad})')
        check(not served.errors(), f'console clean: {served.errors()[:3]}')
```

The roof names above assume Task 4 has NOT run yet (the roof is still split): use the names that exist at this point — `roof_main_west_south` for the great room and `roof_main_east_south`/`south_wall_east` for the study — and note in the test that Task 4 renames them; Task 4 updates the pins. Add to the runner. Run → RED.

- [ ] **Step 2: Build the shells.** In house.js, immediately before the `FABRIC.forEach(function (f) { mergeStatic(f.g, NO_MERGE); })` line:

```js
/* ---- VIEW-VOLUME MASKING (spec 2026-09-16 masking §2-§4) ------------
   One shell per room camera, cut at build time: for every fabric mesh,
   keep = (mesh outside the pyramid P) ∪ (mesh inside P and inside W).
   Both pieces are disjoint by construction (the second is clipped to P
   first), so nothing is drawn twice. Kits (doors, windows) go whole or
   not at all, by sampling their box corners. The full shell stays for
   the exterior and the orbit; solveShell only swaps visibility. */
var CAP_MAT = mat(pal('section', FSTYLE.section, 0xe9e4da), { rough: 0.95 });
var ROOM_CAMS = { kitchen: [HOME_POS, ROOM_AABB_EAVE('kitchen')], living: [LIV_POS, ROOM_AABB_EAVE('living')],
                  study: [STUDY_POS, ROOM_AABB_EAVE('study')], garage: [GARAGE_POS, ROOM_AABB_EAVE('garage')],
                  mudroom: [MUD_POS, ROOM_AABB_EAVE('mudroom')] };
var roomShellGroups = {};
function ROOM_AABB_EAVE(room) {
  var b = ROOM_AABB[room].slice();      /* built below today; hoist ROOM_AABB above this block */
  b[3] = Math.min(b[3], EXT_TOP4);       /* eave-high (spec §2 choice A) */
  return b;
}
function keepTris(tris, m) {
  var C = window.HouseClip;
  var outside = C.subtractTris(tris, m.P, 1);
  var inside = m.P.reduce(function (t, pl) { return C.clipTris(t, pl, 1); }, tris);
  var kept = m.W.reduce(function (t, pl) { return C.clipTris(t, pl, 1); }, inside);
  return outside.concat(kept);
}
function trisToMesh(tris, slot, material, like) {
  var sel = tris.filter(function (t) { return t.slot === slot; });
  if (!sel.length) return null;
  var pos = new Float32Array(sel.length * 9), uv = new Float32Array(sel.length * 6);
  sel.forEach(function (t, i) {
    [t.a, t.b, t.c].forEach(function (v, k) {
      pos.set(v.p, i * 9 + k * 3); uv.set(v.uv, i * 6 + k * 2);
    });
  });
  var g = new T.BufferGeometry();
  g.setAttribute('position', new T.BufferAttribute(pos, 3));
  g.setAttribute('uv', new T.BufferAttribute(uv, 2));
  g.computeVertexNormals();
  g.userData.cached = true;             /* lifecycle law: never disposed by a rebuild path */
  var mesh = new T.Mesh(g, material);
  mesh.userData.room = like.userData.room; mesh.userData.fabric = true;
  mesh.castShadow = like.castShadow; mesh.receiveShadow = like.receiveShadow;
  mesh.renderOrder = like.renderOrder;
  return mesh;
}
function boxCorners(b) {
  var out = [];
  for (var i = 0; i < 8; i++) out.push([(i & 1) ? b[1] : b[0], (i & 2) ? b[3] : b[2], (i & 4) ? b[5] : b[4]]);
  out.push([(b[0]+b[1])/2, (b[2]+b[3])/2, (b[4]+b[5])/2]);
  return out;
}
function buildRoomShells() {
  var C = window.HouseClip;
  Object.keys(ROOM_CAMS).forEach(function (room) {
    var cam = ROOM_CAMS[room][0].toArray(), m = C.maskPlanes(cam, ROOM_CAMS[room][1]);
    var group = new T.Group(); group.name = 'shell:' + room; group.visible = false;
    roomShellGroups[room] = group;
    FABRIC.forEach(function (f) {
      var area0 = 0, area1 = 0;
      if (f.kit) {
        var hits = boxCorners(f.box).filter(function (p) { return C.pointMasked(p, m); }).length;
        var whole = hits < 5;
        f.g.traverse(function (mm) { if (mm.isMesh) { var t = worldTris(mm); area0 += C.triArea(t); if (whole) { var c = mm.clone(); c.userData = Object.assign({}, mm.userData); c.matrix.copy(mm.matrixWorld); c.matrixAutoUpdate = false; group.add(c); area1 += C.triArea(t); } } });
      } else {
        f.g.traverse(function (mm) {
          if (!mm.isMesh) return;
          var tris = worldTris(mm); area0 += C.triArea(tris);
          var kept = mm.userData.convex ? keepTris(tris, m)
                   : (boxCorners(fabBox(mm)).filter(function (p) { return C.pointMasked(p, m); }).length < 5 ? tris : []);
          area1 += C.triArea(kept, 0);
          var a = trisToMesh(kept, 0, mm.material, mm), b = trisToMesh(kept, 1, CAP_MAT, mm);
          if (a) group.add(a); if (b) group.add(b);
        });
      }
      f.shells = f.shells || {};
      f.shells[room] = { fraction: area0 ? Math.max(0, Math.min(1, 1 - area1 / area0)) : 0 };
    });
    scene.add(group);
    mergeStatic(group, NO_MERGE);
  });
}
buildRoomShells();
```

`fabBox(mm)` exists for groups; it works for a mesh too (`Box3.setFromObject`). `ROOM_AABB` is built at ~9732 today from the fabric registry — move that derivation up to run right before `buildRoomShells()` (it only needs `FABRIC`), keeping `webgl.ROOM_AABB` exported. `pal('section', …)`: add `section` to the palette table (`PALETTE`/`FARMHOUSE`) as `0xe9e4da` — hex only there. `bakeAO` (~8830) runs after `mergeStatic`: confirm it traverses the hidden room-shell groups (it must; if it skips `visible === false`, set every room-shell group visible for the bake and hide them after, and say so). Kit clones keep their materials shared (glow/emissive loops keep working).

- [ ] **Step 3: Swap.** Replace `solveShell`'s body:

```js
function solveShell(camPos, subject) {
  var room = subject && subject.room && roomShellGroups[subject.room] ? subject.room : null;
  FABRIC.forEach(function (f) { f.g.visible = !room; f.verdict = 'solid'; if (f.edges) f.edges.visible = false; });
  Object.keys(roomShellGroups).forEach(function (r) { roomShellGroups[r].visible = (r === room); });
  if (room) FABRIC.forEach(function (f) { if (f.shells && f.shells[room] && f.shells[room].fraction > 0) f.verdict = 'masked'; });
  if (webgl) webgl.shadowDirty();
}
```

`frameZone`'s call passes `{point, room: mode}` → same room, no change. Exposures: `window.chfRoomShellShown = function () { var r = null; Object.keys(roomShellGroups).forEach(function (k) { if (roomShellGroups[k].visible) r = k; }); return r; }`; `window.chfRoomMask = function (room) { return Object.assign({ box: ROOM_CAMS[room][1] }, window.HouseClip.maskPlanes(ROOM_CAMS[room][0].toArray(), ROOM_CAMS[room][1])); }`; `window.chfRoomShellLeak = function (room, n) { /* sample up to n vertices of roomShellGroups[room]'s meshes (world space), count those with pointMasked(p, mask) true, ignoring cap-material meshes' vertices that lie ON a mask plane (|side| < 1e-3) */ }`. `chfShellFabric()` rows: add `maskedFraction: {room: fraction}` from `f.shells`, keep `verdict`. `chfNavProbe`/`onTap` raycasts: confirm they raycast `scene` recursively and skip invisible objects (read the probe's hit filter; if it does not skip invisible ancestors, add that check, as the study's `shown()` does) so hidden shells are never hit.

- [ ] **Step 4: GREEN.** Run the scenario, then the whole live file. The old verdict-based scenarios (`scenario_shell_fabric_registry`'s EXPECTED tables, `scenario_a_room_cutaway_leaves_other_rooms_enclosed`, `scenario_shell_without_room_is_inert`, `test_house_life_live.py:91`) will fail: convert each to `maskedFraction`/`verdict in ('solid','masked')` semantics with the derivation in the comment — do NOT delete a scenario; `scenario_a_room_cutaway_leaves_other_rooms_enclosed` becomes "for every room, every piece with fraction 0 is whole and every piece with fraction > 0 lies partly in the mask (`chfRoomShellLeak` 0)". `test_house_life_live.py`: `verdict` reads → `maskedFraction[room] == 0` / `> 0`. Probe `--views all --budget` and `--views orbit`; LOOK at the five room PNGs: every other room enclosed, the subject open along its silhouette, caps legible; record buildMs before/after.

- [ ] **Step 5: Sweep, bump, commit, push** — `feat: view-volume masking — one cut shell per room, swapped at settle (vX.Y.Z)` with the fraction table and buildMs in the body.

---

### Task 4: Retire the verdict machinery, the owners and the splits

**Files:**
- Modify: `chauffeur/static/house.js` — `regFabric` fields (`owners`, `cutawayRoom`, `twoSided`, `mode`, `plane`, `pad`), `shellRegister`/`shellWall`/`shellGable` signatures, `south_wall`+`south_wall_east` (~4147-4260), `roof_main_west`/`roof_main_east` (~5235-5256 → one `shellGable('roof_main', …)`), `STUDY_SLOTS`/`slotOwners`/`spanOwners` (~4678-4790), `VAULTED`/`roofVault` (reads the single roof again), every call site (grep each retired name).
- Modify: `chauffeur/services/house_facade.py` (`STUDY_SLOTS` :49, `slot_owners` :52, `slot_table` :82-93), `chauffeur/tests/test_house_facade.py:55-70`.
- Test: `chauffeur/tests/test_house_live.py` (registry KEPT set, mesh pin, roof pins, Task 3's scenario names), `chauffeur/tests/test_house_life_live.py`.

**Interfaces:**
- Produces: `regFabric(group, {name, n, box, room, kit})`; `shellRegister(g, name, normal, room, kit)`; `shellWall(name, x0, z0, x1, z1, height, normal, windows, room)`; `shellGable(name, x0, x1, z0, z1, eave, ridge, room, ends, pitch, slopeRooms, depthEnds, form)`; registered names `roof_main_north/_south/_end_west/_end_east`, `south_wall` (one piece x -7.15..14.65).

- [ ] **Step 1: RED.** In `scenario_shell_fabric_registry`, KEPT/NEW become the spec §2 set of the regular-house spec with `roof_main_*` (four) and no `south_wall_east`; delete the `owners` assertions; Task 3's scenario pins rename `roof_main_west_south` → `roof_main_south` (fraction for kitchen/living > 0.1 — a smaller share of a larger deck) and `south_wall_east`'s study pin → `south_wall` fraction for the study > 0.05. `test_house_facade.py`: remove the owners/STUDY_SLOTS assertions; the parity pin compares slot tables without `owners`. Run both → RED.

- [ ] **Step 2: Remove.** `solveShell` no longer reads any retired field; delete them from `regFabric`, the three signatures and every call (grep `owners`, `cutawayRoom`, `twoSided`, `mode:`, `plane:`, `pad` within fabric registrations → zero hits). Fold `south_wall_east`'s three boxes back into `southWallG` with `SW_W = FULL_HOUSE.east - FULL_HOUSE.west`, `SW_CX = (FULL_HOUSE.west + FULL_HOUSE.east) / 2` (delete `SW_SPLIT4`, `SWE_*`, `southWallEastG`). Replace the two roof calls with `shellGable('roof_main', FULL_HOUSE.west, FULL_HOUSE.east, FULL_HOUSE.north, FULL_HOUSE.south, EXT_TOP4, ROOF_FORMS.main.ridge, null, null, Math.PI / 8, ['kitchen', 'living'], null, ROOF_FORMS.main.form)`. `roofVault`/`VAULTED`: the main deck is one piece again — the vault gate keeps `ROOF_FORMS.main.form === 'gable'` and drops any per-half logic. Python: delete `STUDY_SLOTS`, `slot_owners`, the `owners` key; JS mirror likewise. Docs comments that cite owners: rewrite to cite the mask.

- [ ] **Step 3: GREEN.** Live files green; mesh pin re-recorded RED-first with the derivation (−3 wall boxes, −6 roof pieces' worth of meshes: two decks, two eave trims, two ridge caps become one each; gable ends unchanged); probe `--views all --budget` and `--roof hip` and `--roof '{"main":{"form":"gable","ridge":"z"}}'` — LOOK: the hip main roof is one proper hip again with a 1.15 ridge, masked per room; record in-frustum/tris for each.

- [ ] **Step 4: Sweep, bump, commit, push** — `refactor: the shell solver is the mask — owners, splits and verdict tables retired; roof_main is one roof again (vX.Y.Z)`.

---

### Task 5: Roof valleys

**Files:**
- Modify: `chauffeur/static/house.js` — `shellGable` (accept `clipAbove: plane[]` and clip every deck/trim/cap/end-infill mesh's triangles with `HouseClip.clipTris(worldTris(mesh), plane, 1)` before it is added — build the mesh from the kept triangles the way Task 3's `trisToMesh` does, cap slot to `CAP_MAT`), `gableAt` (~5325-5359), `dormerAt` (~5362-5385), `roofPlaneEave`.
- Test: `chauffeur/tests/test_house_live.py` (`scenario_roof_features_stop_at_the_roof_line`)

**Interfaces:**
- Consumes: `HouseClip`, `worldTris`, `trisToMesh`, `CAP_MAT`.
- Produces: `window.chfRoofPlane(face)` → `{n, d}` of the block deck plane under that face's features (main south deck / garage-block south deck), derived from the block's eave/pitch/ridge exactly as `shellGable` computes them; `window.chfFabricVertices(name)` → `[[x,y,z], …]` world vertices of the named piece's meshes; `shellGable(..., form, clipAbove)`.

- [ ] **Step 1: RED.**

```python
def scenario_roof_features_stop_at_the_roof_line():
    """Spec 2026-09-16 masking §6: every vertex of a facade gable/dormer sits at
    or above the block deck it sits on; its ridge stands proud at the wall."""
    served = live_app(_seed)
    if served is None:
        return
    with served.browser() as page:
        page.add_init_script(DAY_LOCK_JS)
        page.goto(served.url('house?quality=high'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        names = [f['name'] for f in page.evaluate('window.chfShellFabric()')
                 if f['name'].startswith('facade_') and ('_gable_' in f['name'] or '_dormer_' in f['name'])]
        check(names, 'canonical facade has roof features')
        for n in names:
            face = 'garage_block' if n.startswith('facade_garage_block') else 'main'
            worst = page.evaluate(f"""() => {{
              const pl = window.chfRoofPlane('{face}');
              const vs = window.chfFabricVertices('{n}');
              let worst = 1e9;
              vs.forEach(p => {{ const s = pl.n[0]*p[0] + pl.n[1]*p[1] + pl.n[2]*p[2] - pl.d; if (s < worst) worst = s; }});
              return worst;
            }}""")
            check(worst > -0.05, f'{n}: lowest vertex {worst:.3f} below the parent deck plane')
        check(not served.errors(), 'console clean')
```

Add to the runner. Run → RED (`chfRoofPlane` missing; then vertices metres below the plane).

- [ ] **Step 2: Implement.** `roofPlaneOf(block)`: for `FULL_HOUSE`/`GARAGE_BLOCK` with `ROOF_FORMS`, the south deck's centre plane: for ridge `x`, point `(cx, roofEave + 0.09/cos(pitch)… )` — derive it from `shellGable`'s own numbers by factoring them into a helper `deckPlane(x0, x1, z0, z1, eave, ridge, pitch, sign)` that `shellGable` itself uses for its deck placement (so there is ONE derivation), returning `{n, d}` with `n` the deck's upward normal. `gableAt`/`dormerAt`: pass `clipAbove: [deckPlane(...)]` (keep side above the deck: `n·p − d ≥ 0` with `n` upward). Height rule: the feature's ridge at the street wall must stand above the parent plane by the feature's own `rise` (`half · tan(pitch)`). With `parentY` = the parent deck's centre-plane height at the feature's front eave line, the feature's ridge is `eave + 0.18 + rise` (that is `shellGable`'s own formula), so `eave = parentY − 0.18`. Compute `parentY` from `deckPlane`, set the feature's eave from it (replacing the `roofPlaneEave(slot) − 0.8` literal for gables and the `y + 0.95` for dormers where they conflict), and record the resulting eave/ridge per feature in the report. `shellGable` with `clipAbove`: after each deck/trim/cap/infill mesh is built and positioned, replace its geometry by the clipped triangles (`worldTris` → `clipTris` → `trisToMesh` with the mesh's own material; cap tris to `CAP_MAT`); if nothing is kept, drop the mesh. Geometry through `cgeo` keyed on the piece key + the plane. `chfFabricVertices(name)`: world positions of every vertex of the piece's meshes (before merge — expose from a per-piece cache filled at build).

- [ ] **Step 3: GREEN.** Scenario green; live file green (mesh pin re-recorded RED-first: clipped pieces are still one mesh each; say what moved); probe `--views exterior`, `--views orbit` (stops 0, 1, 7), `--views living,kitchen`: LOOK — a gable reads as a gable with two valleys, nothing of it visible under the main deck from inside; record in-frustum/tris.

- [ ] **Step 4: Sweep, bump, commit, push** — `feat: gables and dormers stop at the roof line (vX.Y.Z)`.

---

### Task 6: Wrap

**Files:** `chauffeur/system_capabilities.md` (new entry after the vaulted-partitions paragraph; bump `Current through`), `docs/house_style_bible.md` (cutaways are masks; roof features stop at the roof line), spec §9 Results, memory (controller).

- [ ] **Step 1:** capabilities entry in the file's voice: the mask (definition, choices A/A/A), the clipper, room shells and the swap, what was retired (owners, splits, verdict tables, corridor rule), roof valleys + height rule, budgets before/after per view and per stop, the pins. Ends **NOT device-verified.**
- [ ] **Step 2:** spec §9 tables + deviations; style bible note; fold in the two pending docs nits (the study's east wall plane is 0.06 clear of the slab, not 0.12, at the capabilities massing paragraph and spec §10.11; the missing space at the regular-house spec line 22 "interior;retired").
- [ ] **Step 3:** bump, commit (docs-only, no sweep), push — `docs: view-volume masking + roof valleys wrap (vX.Y.Z)`.

---

### Task 7: Split the house live file so the sweep parallelises

**Files:**
- Modify: `chauffeur/tests/test_house_live.py` (becomes the lifecycle + boot file)
- Create: `chauffeur/tests/test_house_shell_live.py` (masking/shell/vault/clipper scenarios), `chauffeur/tests/test_house_nav_live.py` (navigation, orbit, swipe, idle), `chauffeur/tests/test_house_facade_live.py` (canonical pin, worst case, valleys)
- Create: `chauffeur/tests/house_live_common.py` (shared: `_seed`, `DAY_LOCK_JS`, `CANONICAL_EXTERIOR_MESHES`, `_deck_underside`, any helper two files need)
- Modify: `chauffeur/tools/test.py` only if it enumerates test files by an explicit list (read it; if it globs `tests/test_*.py`, nothing to do)

**Interfaces:** every scenario keeps its name and body; the runner block at the bottom of each file lists only its own scenarios; `house_live_common.py` is imported, never run.

- [ ] **Step 1:** Measure: `cd chauffeur && time env -u HA_BASE_URL python tests/test_house_live.py` (record the wall time).
- [ ] **Step 2:** Move scenarios by concern (read each scenario's docstring; the split is: lifecycle/boot/leak scenarios stay; `scenario_shell_*`, `scenario_a_room_*`, `scenario_room_masks_*`, `scenario_clipper_*`, `scenario_interior_walls_*`, `scenario_every_fabric_*`, `scenario_study_*` → shell file; `scenario_navigation_*`, `scenario_orbit_*`, `scenario_idle_*` → nav file; `scenario_canonical_*`, `scenario_worst_case_*`, `scenario_roof_features_*` → facade file). Shared constants and helpers move to `house_live_common.py` with a one-line docstring each. No scenario is edited beyond its imports.
- [ ] **Step 3:** Run each new file solo (all green, same scenario count as before: count `def scenario_` across the four files and compare with the original 17+N). Then the FULL sweep once: `env -u HA_BASE_URL python chauffeur/tools/test.py` — record the wall time before/after in the report and the commit body.
- [ ] **Step 4:** Update `docs/superpowers` references and `system_capabilities.md` lines that name `tests/test_house_live.py` for a moved scenario (grep); the memory note about fast test runs is the controller's.
- [ ] **Step 5:** bump, commit, push — `test: the house live file splits four ways so the sweep parallelises (vX.Y.Z)` with the before/after wall times.

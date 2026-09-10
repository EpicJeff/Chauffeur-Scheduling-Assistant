# House Quality Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take the /house scene from sharp-edged primitives to the reference image's read — chamfered edges everywhere, lathed and swept detail parts, physical material finishes, baked ambient occlusion, and a real lighting pass — without moving a prop or giving back the batching arc's draw-call wins.

**Architecture:** Five kit slices land infrastructure inside the existing helper layer (`box()`/`rbox()`/`cyl()`/`mat()`/`cgeo`) so 254 call sites upgrade without site edits; then five authored room passes spend the kit prop-by-prop with a screenshot gate to the user after each room; a lighting slice runs last. Everything obeys the batching arc's laws (L1 zone-material uniqueness, cache sharing, merge fences, tag-only routing, honest buildMs).

**Tech Stack:** three.js (vendored legacy `static/vendor/three.min.js` ~r149, global `THREE`), vanilla ES5 in `chauffeur/static/house.js`, Python/Playwright harness (`tests/live_app.py`, `tools/house_probe.py`).

**Spec:** `docs/superpowers/specs/2026-09-10-house-quality-pass-design.md` — binding. The batching spec's laws travel with it: `docs/superpowers/specs/2026-09-10-house-batching-design.md`.

## Global Constraints

- **ES5 syntax only in `house.js`** (var/function; no arrows, const/let, template literals). Set/Map objects are fine. Python tests may use modern JS inside `page.evaluate` strings.
- **Composition freeze:** no prop moves, none removed, no new furniture. Detail parts are parts OF existing props. Any change that would drop something a person can see or tap returns to the user first.
- **Budget guard:** post-batching floors at quality=high — exterior 1,134 / kitchen 363 / living 682 / mudroom 373 / garage 526 in-frustum meshes. Kit slices stay within **+10%** per view; each room pass records a ceiling of **its own post-kit number +15%** and stays under it. Instrument: `python tools/house_probe.py --views all --budget --quality high` from `chauffeur/`.
- **buildMs ceiling:** ≤1500ms at quality=high on the dev desktop (honest instrument since v2.477.3; current ~536-601ms).
- **Batching laws verbatim:** zone-owned parts get unique materials (`inZoneGroup`/`zoneTag` paths); colour lives in materials, never `instanceColor`; transparent materials never merge; merge fences (`NO_MERGE`, `EXT_NO_MERGE`) stay intact; tap routing stays tag-only.
- **Tests:** full sweep `python tools/test.py` from `chauffeur/` before every commit (never piped, no other browser work; one flaky browser failure → isolated re-run). Live test `python tests/test_house_live.py` must stay green in every task.
- **Screenshot judgment:** compare against the previous slice's probe output; wall-clock hero-card digits are known noise (mudroom peak ~238) — use the same-code control-run method (two runs of your own commit diffed) before calling any diff a regression. Save probe output under `$LOCALAPPDATA/Temp/house_quality/<slice>` — never in the repo. Room-pass screenshots are the user's gate: leave them in that directory and NAME the directory in your report; the controller sends them to the user.
- **Commits:** bump `chauffeur/config.yaml` `version:` per task (ladder below, adjust upward if drifted), poetic one-line message + `(vX.Y.Z)`, commit via the Bash tool (single quotes; PowerShell splits double quotes), push. `static/kitchen.js` is never touched.
- Line numbers reference v2.478.0 and drift; anchor by quoted code.

## Version ladder

K1 2.479.0 · K2 2.480.0 · K3 2.481.0 · K4 2.482.0 · K5 2.483.0 · R1 2.484.0 · R2 2.485.0 · R3 2.486.0 · R4 2.487.0 · R5 2.488.0 · L 2.489.0 · wrap 2.489.1. Fix rounds take the next patch on the slice's minor.

---

### Task 1: K1 — chamferBox inside the helpers

**Files:**
- Modify: `chauffeur/static/house.js` (helper layer, ~640-800)

**Interfaces:**
- Consumes: `cgeo(key, make)`, `mat(c, opts, forceUnique)`, `inZoneGroup(g)`, `finish(m)` — all existing.
- Produces: `chamferGeo(w, h, d, ch)` returning a cgeo-cached BufferGeometry; `box()` honoring `opts.ch` (number, 0 = sharp) with a NICE-tier default; `rbox()` redirecting to chamferGeo. Later tasks rely on `opts.ch` and on chamfered geometry being cache-keyed `'b|w|h|d|ch'`.

- [ ] **Step 1: Add the generator** — after `roundedGeo` (~:752), the spike's proven code, ES5, with smoothed strip normals:

```js
    /* ---- K1 (quality spec §3): the chamfered box ----------------------
       44 triangles: 6 faces, 12 one-segment chamfer strips, 8 corner
       tris. Normals are position-averaged after computeVertexNormals so
       the strip SHADES like a fillet — a flat corner facet square to the
       sun reads as a white triangle (the spike's first draft). UVs are
       planar per dominant axis, which matches how the box-face canvas
       maps are authored. Cheap enough to build 254 times on a Pi, which
       roundedGeo (a Shape triangulation) never was. */
    function chamferRaw(w, h, d, ch) {
      var full = [w / 2, h / 2, d / 2];
      var c = Math.max(1e-4, Math.min(ch, full[0] * 0.49, full[1] * 0.49,
                                      full[2] * 0.49));
      var inner = [full[0] - c, full[1] - c, full[2] - c];
      var pos = [], uv = [];
      function tri(a, b, e) {
        var ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2];
        var vx = e[0] - a[0], vy = e[1] - a[1], vz = e[2] - a[2];
        var nx = uy * vz - uz * vy, ny = uz * vx - ux * vz,
            nz = ux * vy - uy * vx;
        var cx = (a[0] + b[0] + e[0]) / 3, cy = (a[1] + b[1] + e[1]) / 3,
            cz = (a[2] + b[2] + e[2]) / 3;
        if (nx * cx + ny * cy + nz * cz < 0) { var t = b; b = e; e = t; }
        var an = Math.abs(nx), bn = Math.abs(ny), dn = Math.abs(nz);
        var i0 = 0, i1 = 1;
        if (an >= bn && an >= dn) { i0 = 2; i1 = 1; }
        else if (bn >= dn) { i0 = 0; i1 = 2; }
        [a, b, e].forEach(function (p) {
          pos.push(p[0], p[1], p[2]);
          uv.push((p[i0] + full[i0]) / (2 * full[i0]),
                  (p[i1] + full[i1]) / (2 * full[i1]));
        });
      }
      function quad(a, b, e, f) { tri(a, b, e); tri(a, e, f); }
      function V() { return [0, 0, 0]; }
      var a, b, e, sa, sb, sc;
      for (a = 0; a < 3; a++) {
        b = (a + 1) % 3; e = (a + 2) % 3;
        for (sa = -1; sa <= 1; sa += 2) {
          var q = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(function (s) {
            var p = V(); p[a] = sa * full[a]; p[b] = s[0] * inner[b];
            p[e] = s[1] * inner[e]; return p;
          });
          quad(q[0], q[1], q[2], q[3]);
        }
      }
      for (a = 0; a < 3; a++) {
        b = (a + 1) % 3; e = (a + 2) % 3;
        for (sa = -1; sa <= 1; sa += 2) for (sb = -1; sb <= 1; sb += 2) {
          var p1 = V(); p1[a] = sa * full[a]; p1[b] = sb * inner[b]; p1[e] = -inner[e];
          var p2 = V(); p2[a] = sa * full[a]; p2[b] = sb * inner[b]; p2[e] = inner[e];
          var p3 = V(); p3[a] = sa * inner[a]; p3[b] = sb * full[b]; p3[e] = inner[e];
          var p4 = V(); p4[a] = sa * inner[a]; p4[b] = sb * full[b]; p4[e] = -inner[e];
          quad(p1, p2, p3, p4);
        }
      }
      for (sa = -1; sa <= 1; sa += 2) for (sb = -1; sb <= 1; sb += 2)
        for (sc = -1; sc <= 1; sc += 2) {
          tri([sa * full[0], sb * inner[1], sc * inner[2]],
              [sa * inner[0], sb * full[1], sc * inner[2]],
              [sa * inner[0], sb * inner[1], sc * full[2]]);
        }
      var g = new T.BufferGeometry();
      g.setAttribute('position', new T.Float32BufferAttribute(pos, 3));
      g.setAttribute('uv', new T.Float32BufferAttribute(uv, 2));
      g.computeVertexNormals();
      var na = g.attributes.normal, pa = g.attributes.position, acc = {}, k, i;
      for (i = 0; i < pa.count; i++) {
        k = (pa.getX(i) * 1e4 | 0) + '_' + (pa.getY(i) * 1e4 | 0) + '_' +
            (pa.getZ(i) * 1e4 | 0);
        var s2 = acc[k] || (acc[k] = [0, 0, 0]);
        s2[0] += na.getX(i); s2[1] += na.getY(i); s2[2] += na.getZ(i);
      }
      for (i = 0; i < pa.count; i++) {
        k = (pa.getX(i) * 1e4 | 0) + '_' + (pa.getY(i) * 1e4 | 0) + '_' +
            (pa.getZ(i) * 1e4 | 0);
        var v2 = acc[k], L2 = Math.sqrt(v2[0] * v2[0] + v2[1] * v2[1] +
                                        v2[2] * v2[2]) || 1;
        na.setXYZ(i, v2[0] / L2, v2[1] / L2, v2[2] / L2);
      }
      na.needsUpdate = true;
      return g;
    }
    function chamferGeo(w, h, d, ch) {
      return cgeo('b|' + w + '|' + h + '|' + d + '|' + ch, function () {
        return chamferRaw(w, h, d, ch);
      });
    }
```

- [ ] **Step 2: Wire `box()` and `rbox()`.** Replace `box()`'s geometry line so NICE tiers chamfer by default:

```js
    function box(w, h, d, c, x, y, z, group, opts) {
      var g0 = group || scene;
      var ch = opts && opts.ch !== undefined ? opts.ch
             : (NICE ? 0.022 : 0);
      var m = new T.Mesh(
        ch > 0 ? chamferGeo(w, h, d, ch)
               : cgeo('b|' + w + '|' + h + '|' + d, function () {
                   return new T.BoxGeometry(w, h, d);
                 }),
        mat(c, opts, inZoneGroup(g0)));
      m.position.set(x, y, z); finish(m); g0.add(m); return m;
    }
```

`rbox()` becomes a redirect (its 39 sites keep authored radii): body =
`return box(w, h, d, c, x, y, z, group, Object.assign({}, opts || {}, { ch: DETAIL < 2 ? 0 : r }));`
— but `Object.assign` may be absent in the legacy parser's runtime targets; use the ES5 copy:

```js
    function rbox(w, h, d, r, c, x, y, z, group, opts) {
      var o = {}, k2;
      if (opts) for (k2 in opts) o[k2] = opts[k2];
      o.ch = DETAIL < 2 ? 0 : r;
      return box(w, h, d, c, x, y, z, group, o);
    }
```

- [ ] **Step 3: Author the sharp opt-outs.** Architecture keeps crisp poche edges. Add `ch: 0` to the opts of: the two floor slabs (`box(13.6, 0.5, 11.6, C.shell, …)` and `box(13.6, 0.5, 8.4, C.shell, …)`), every wall piece in `westWallG` and `wallB`, the section caps (`SECT` block, the `C.shell` header boxes at :864-866 area), baseboards, the exterior `ebox` shell fabric — cleanest as a local wrapper where those blocks build: define `function sharp(o) { var r2 = {}; if (o) for (var k3 in o) r2[k3] = o[k3]; r2.ch = 0; return r2; }` near the wall block and wrap those call sites' opts. Enumerate in the report exactly which call sites got `ch:0` (expected: walls, slabs, section caps, baseboards, roof planes, siding, driveway/street, plinth — surfaces, not props).
- [ ] **Step 4: Retire `roundedGeo` per site.** 11 direct uses. For each: convert to `chamferGeo(w, h, d, r)` (or leave `rbox`, already redirected). The fridge body (`roundedGeo(1.9, 3.95, 1.5, 0.08)`) converts — the spike proved the read at ch 0.075. If EVERY direct use converts, delete `roundedGeo`; if any site genuinely needs multi-segment fillets (judge by screenshot), keep it for those and say which in the report.
- [ ] **Step 5: Verify.** `node --check` equivalent (`node -e "require('fs').readFileSync('static/vendor/../house.js')"` is not a parse; use `node --check chauffeur/static/house.js` from repo root). Then from `chauffeur/`: `python tests/test_house_live.py` (3×), `python tools/house_probe.py --views all --budget --quality high --out "$LOCALAPPDATA/Temp/house_quality/k1"` — budget within +10% of floors (geometry count will RISE ~modestly; chamfer variants split cache keys — record it), buildMs ≤1500, screenshots show highlight lines on prop edges and NO seams on mapped boxes (fridge steel, wood counters — check the kitchen view close). Then full sweep.
- [ ] **Step 6: Commit** — v2.479.0, message `'Every edge learns to catch the light (v2.479.0)'`, body with budget before/after, push.

---

### Task 2: K2 — lathe + sweep + the profile library

**Files:**
- Modify: `chauffeur/static/house.js` (next to chamferGeo)

**Interfaces:**
- Consumes: `cgeo`, `mat`, `inZoneGroup`, `finish`.
- Produces (room passes consume these exact signatures):
  - `latheGeo(key, seg)` — key names a PROFILES entry; returns cgeo-cached unit-scale LatheGeometry.
  - `latheAt(key, s, c, x, y, z, group, opts)` — builds the mesh, scales by `s` (number or `[sx, sy, sz]`), routes materials through `mat` with zone awareness; returns the mesh.
  - `sweepGeo(pts, r, seg, rad)` — TubeGeometry along CatmullRomCurve3 (NOT cached — every sweep path is unique).
  - `sweepAt(pts, r, c, group, opts)` — mesh + finish + add; returns mesh.
  - `PROFILES` — the named library.

- [ ] **Step 1: Implement.**

```js
    /* ---- K2 (quality spec §3): lathe + sweep, the detail vocabulary ---
       Profiles are UNIT-SCALE [x, y] outlines (max radius ~0.5, height
       ~1.0); latheAt() puts size in mesh scale, so every jar shares one
       geometry per segment tier — the batching lesson applied from
       birth. Segment counts tier like cyl(). */
    var PROFILES = {
      jar:    [[0, 0], [0.36, 0], [0.40, 0.06], [0.40, 0.72], [0.32, 0.82],
               [0.34, 0.88], [0.27, 0.92], [0.27, 1.0], [0, 1.0]],
      lid:    [[0, 0], [0.36, 0], [0.37, 0.55], [0.28, 0.8], [0, 1.0]],
      bowl:   [[0, 0.08], [0.18, 0], [0.44, 0.35], [0.50, 0.9], [0.47, 1.0],
               [0.41, 0.42], [0.16, 0.12], [0, 0.2]],
      plate:  [[0, 0], [0.30, 0], [0.48, 0.5], [0.50, 1.0], [0.44, 0.55],
               [0.27, 0.18], [0, 0.18]],
      cup:    [[0, 0], [0.30, 0], [0.34, 0.1], [0.36, 1.0], [0.30, 1.0],
               [0.28, 0.16], [0, 0.16]],
      vase:   [[0, 0], [0.26, 0], [0.38, 0.3], [0.20, 0.75], [0.24, 1.0],
               [0, 1.0]],
      knob:   [[0, 0], [0.18, 0], [0.20, 0.35], [0.42, 0.55], [0.46, 0.8],
               [0.38, 1.0], [0, 1.0]],
      foot:   [[0, 0], [0.46, 0], [0.46, 0.35], [0.30, 0.55], [0.27, 1.0],
               [0, 1.0]],
      hinge:  [[0, 0], [0.30, 0], [0.30, 0.2], [0.40, 0.28], [0.40, 0.72],
               [0.30, 0.8], [0.30, 1.0], [0, 1.0]],
      pull:   [[0, 0], [0.42, 0], [0.46, 0.25], [0.30, 0.5], [0.46, 0.75],
               [0.42, 1.0], [0, 1.0]],
      finial: [[0, 0], [0.20, 0], [0.34, 0.3], [0.12, 0.6], [0.20, 0.85],
               [0, 1.0]],
      shade:  [[0.22, 0], [0.50, 0], [0.34, 1.0], [0.20, 1.0]]
    };
    function latheGeo(key, seg) {
      var sg = seg || (DETAIL >= 3 ? 16 : 10);
      return cgeo('L|' + key + '|' + sg, function () {
        var pts = PROFILES[key].map(function (p) {
          return new T.Vector2(p[0], p[1]);
        });
        return new T.LatheGeometry(pts, sg);
      });
    }
    function latheAt(key, s, c, x, y, z, group, opts) {
      var g0 = group || scene;
      var m = new T.Mesh(latheGeo(key, opts && opts.seg),
                         mat(c, opts, inZoneGroup(g0)));
      if (typeof s === 'number') m.scale.set(s, s, s);
      else m.scale.set(s[0], s[1], s[2]);
      m.position.set(x, y, z); finish(m); g0.add(m); return m;
    }
    function sweepGeo(pts, r, seg, rad) {
      return new T.TubeGeometry(new T.CatmullRomCurve3(
        pts.map(function (p) { return new T.Vector3(p[0], p[1], p[2]); })),
        seg || (DETAIL >= 3 ? 24 : 14), r, rad || (DETAIL >= 3 ? 10 : 7),
        false);
    }
    function sweepAt(pts, r, c, group, opts) {
      var g0 = group || scene;
      var m = new T.Mesh(sweepGeo(pts, r, opts && opts.seg,
                                  opts && opts.rad),
                         mat(c, opts, inZoneGroup(g0)));
      finish(m); g0.add(m); return m;
    }
```

- [ ] **Step 2: Smoke it without visual change.** The kit must be exercised before rooms depend on it: temporarily build one of each profile in a hidden group, verify no console errors, then REMOVE the temporary block — final commit contains helpers only. Proof instead comes from a probe run with zero errors plus `node --check`.
- [ ] **Step 3: Verify.** `node --check`; live test; `python tools/house_probe.py --views exterior --budget --quality high --out .../k2` (numbers unchanged — helpers unused); full sweep.
- [ ] **Step 4: Commit** — v2.480.0, `'A vocabulary of jars and handles (v2.480.0)'`, push.

---

### Task 3: K3 — physical finishes, calibrated on real props

**Files:**
- Modify: `chauffeur/static/house.js` (`makeMat`, `mat` key; fridge doors; pantry jars)

**Interfaces:**
- Consumes: `makeMat(c, opts)` / `mat(c, opts, forceUnique)` and the material cache key.
- Produces: `opts.finish` ∈ `'enamel' | 'glassy' | 'ceramic'` honored at PBR tier; cache key extended with the finish token; room passes use `{ finish: 'enamel' }` etc. in any helper's opts.

- [ ] **Step 1: Extend `makeMat`.** Inside the PBR branch, before the Standard material is built:

```js
      if (opts.finish && PBR) {
        var pm;
        if (opts.finish === 'enamel') {
          pm = new T.MeshPhysicalMaterial({ color: c,
            roughness: opts.rough !== undefined ? opts.rough : 0.34,
            metalness: 0, clearcoat: 1.0, clearcoatRoughness: 0.09 });
          pm.envMapIntensity = opts.envInt !== undefined ? opts.envInt : 0.55;
        } else if (opts.finish === 'glassy') {
          pm = new T.MeshPhysicalMaterial({ color: c,
            roughness: 0.06, metalness: 0, transmission: 0.92,
            thickness: opts.thick !== undefined ? opts.thick : 0.25,
            ior: 1.45, transparent: true });
          pm.envMapIntensity = 1.0;
        } else {                                   /* ceramic */
          pm = new T.MeshPhysicalMaterial({ color: c,
            roughness: opts.rough !== undefined ? opts.rough : 0.2,
            metalness: 0, clearcoat: 0.8, clearcoatRoughness: 0.12 });
          pm.envMapIntensity = opts.envInt !== undefined ? opts.envInt : 0.6;
        }
        if (opts.map) pm.map = opts.map;
        return pm;
      }
```

Below PBR, `finish` is ignored (falls through to Standard/Lambert — parts degrade, props never vanish). Extend `mat()`'s cache key with `'|' + (opts.finish || '')` and `'|' + (opts.thick !== undefined ? opts.thick : '')`.

- [ ] **Step 2: Calibrate on real wearers.** Apply `{ finish: 'enamel' }` to the two teal fridge doors (the `rbox` teal panels — zone props, so they mint unique materials via `inZoneGroup`: correct) and `{ finish: 'glassy', thick: 0.1 }` to the pantry jars (`zoneTag`'d 'board' — unique, correct; **their `jar.visible` count semantics untouched**). THEN calibrate against the linear rig: probe the kitchen view; the spike's clearcoat blew highlights under `LinearToneMapping` — if the door's upper half clips toward white under the pool lamp, lower `envMapIntensity` (0.55 → 0.4) and/or raise `clearcoatRoughness` (0.09 → 0.12) until the teal reads saturated with one restrained highlight streak. Record chosen values in the report; the numbers above are starting points, not gospel.
- [ ] **Step 3: Verify.** Live test 3× (glassy jars are transparent — confirm the sharing invariant and pantry lean-in still pass); probe kitchen + lean_board screenshots (jars read as glass, doors as enamel); budget (transparent jars already unmerged — expect ±0); full sweep.
- [ ] **Step 4: Commit** — v2.481.0, `'Enamel, glass and glaze (v2.481.0)'`, push.

---

### Task 4: K4 — the ambient-occlusion bake

**Files:**
- Modify: `chauffeur/static/house.js` (new bake block in build order; floor subdivision)

**Interfaces:**
- Consumes: build order `… mergeStatic block → [BAKE GOES HERE] → applyScenery(0)`; `SHADOWS`/`DETAIL` tiers.
- Produces: `bakeAO()` run once at build (DETAIL ≥ 2), a scene-wide vertex-colour AO; `AO_OCCLUDERS` (array of world-space AABBs `[x0,x1,y0,y1,z0,z1]`).

**The vertexColors trap (spec §3 K4 — this is the step most likely to ship a bug):** `material.vertexColors = true` on a SHARED material makes every wearer sample the colour attribute; a wearer WITHOUT one renders black. Law: the bake first collects, per material, every mesh wearing it; a material flips `vertexColors` only if ALL its wearers got a colour attribute this pass. The bake therefore writes attributes mesh-by-mesh, then flips materials in a second loop.

- [ ] **Step 1: Author the occluder list.** ~30-40 world AABBs covering the big masses: both floor slabs, every wall run (westWall pieces as one box each, wallB, the great-room east line), the island, the counter runs, the fridge, the range, the built-ins, the hearth mass, the mudroom bench, garage walls + parked-car envelope (static box, cars vary inside it), the pantry closet shell, exterior grade plane. Derive coordinates by reading each builder's authored positions — they are literals in the file. Store as `var AO_OCCLUDERS = [ [x0,x1,y0,y1,z0,z1], … ];` with one comment per row naming the mass.
- [ ] **Step 2: Subdivide the two floors** so the bake has vertices: the kitchen floor `new T.PlaneGeometry(13, 11.6)` → `(13, 11.6, 26, 24)`, the great-room floor `(13, 8.5)` → `(13, 8.5, 26, 18)`. (Walls keep box vertices — chamfers added mid-edge verts in K1; corner-weighted AO on those is the intended look.)
- [ ] **Step 3: Implement the bake** — after the `mergeStatic` block, before `applyScenery(0)`:

```js
    /* ---- K4 (quality spec §3): vertex AO, baked once ------------------
       10 hemisphere directions per vertex, marched against authored
       AABBs. Runs after the merge so merged fabric bakes on its final
       vertices; before applyScenery so the knob classifies materials
       that already wear their vertexColors flag. Materials flip
       vertexColors ONLY when every wearer got an attribute — a shared
       material with one bare wearer renders that wearer black. */
    function bakeAO() {
      if (DETAIL < 2) return { meshes: 0 };
      var DIRS = [], i;
      for (i = 0; i < 10; i++) {
        var az = (i + 0.5) / 10, th = Math.acos(1 - az * 0.92),
            ph = i * 2.39996;
        DIRS.push([Math.sin(th) * Math.cos(ph), Math.cos(th),
                   Math.sin(th) * Math.sin(ph)]);
      }
      var STEPS = [0.05, 0.13, 0.26, 0.46, 0.78];
      var STR = 0.62;                       /* max darkening at a corner */
      var tmp = new T.Vector3(), nrm = new T.Vector3();
      var up = new T.Vector3(), tx = new T.Vector3(), tz = new T.Vector3();
      var nm = new T.Matrix3();
      var perMat = {};                       /* uuid -> {mat, wearers, baked} */
      var count = 0;
      scene.updateMatrixWorld(true);
      scene.traverse(function (o) {
        if (!o.isMesh || o.isInstancedMesh || !o.material) return;
        if (Array.isArray(o.material)) return;
        if (!o.material.isMeshStandardMaterial &&
            !o.material.isMeshLambertMaterial &&
            !o.material.isMeshPhysicalMaterial) return;
        if (o.material.transparent) return;  /* glass keeps its clarity */
        var e = perMat[o.material.uuid] ||
                (perMat[o.material.uuid] = { m: o.material, w: [] });
        e.w.push(o);
      });
      Object.keys(perMat).forEach(function (u) {
        perMat[u].w.forEach(function (mesh) {
          var geo = mesh.geometry, p = geo.attributes.position,
              n = geo.attributes.normal;
          if (!p || !n) return;
          nm.getNormalMatrix(mesh.matrixWorld);
          var col = geo.attributes.color;
          if (!col || col.count !== p.count) {
            col = new T.BufferAttribute(new Float32Array(p.count * 3), 3);
            geo.setAttribute('color', col);
          }
          for (var v = 0; v < p.count; v++) {
            tmp.fromBufferAttribute(p, v).applyMatrix4(mesh.matrixWorld);
            nrm.fromBufferAttribute(n, v).applyMatrix3(nm).normalize();
            up.set(Math.abs(nrm.y) > 0.94 ? 1 : 0,
                   Math.abs(nrm.y) > 0.94 ? 0 : 1, 0);
            tx.crossVectors(up, nrm).normalize();
            tz.crossVectors(nrm, tx);
            var hit = 0;
            for (var d2 = 0; d2 < DIRS.length; d2++) {
              var D = DIRS[d2];
              var dx = tx.x * D[0] + nrm.x * D[1] + tz.x * D[2];
              var dy = tx.y * D[0] + nrm.y * D[1] + tz.y * D[2];
              var dz = tx.z * D[0] + nrm.z * D[1] + tz.z * D[2];
              for (var s3 = 0; s3 < STEPS.length; s3++) {
                var L3 = STEPS[s3];
                var qx = tmp.x + dx * L3, qy = tmp.y + dy * L3,
                    qz = tmp.z + dz * L3;
                var blocked = false;
                for (var ob = 0; ob < AO_OCCLUDERS.length; ob++) {
                  var B = AO_OCCLUDERS[ob];
                  if (qx > B[0] && qx < B[1] && qy > B[2] && qy < B[3] &&
                      qz > B[4] && qz < B[5]) { blocked = true; break; }
                }
                if (blocked) { hit += 1 - s3 / STEPS.length; break; }
              }
            }
            var ao = 1 - (hit / DIRS.length) * STR;
            col.setXYZ(v, ao, ao, ao);
          }
          col.needsUpdate = true;
          count++;
        });
        perMat[u].m.vertexColors = true;
        perMat[u].m.needsUpdate = true;
      });
      return { meshes: count };
    }
    var aoStats = bakeAO();
```

**Shared-geometry caveat this code must handle and the implementer must verify:** `cgeo` geometries are SHARED — writing a colour attribute onto a shared geometry bakes ONE wearer's occlusion onto every wearer. Fix inside the wearer loop: if `geo.userData.cached` and the geometry is worn by more than one mesh in the scene, clone it for this mesh first (`mesh.geometry = geo.clone(); mesh.geometry.userData.cached = false;`) — but ONLY at DETAIL ≥ 2 where the bake runs, and count clones in the report (this trades geometry sharing for per-mesh AO; the budget guard arbitrates — if geometry count explodes past +10%, fall back to baking only meshes whose geometry is unshared plus merged fabric and floors, and say so). Detect multi-wear by a first pass counting `geometry.uuid` occurrences.

- [ ] **Step 4: Verify.** Live test 3×; probe all five views + lean_board at high AND medium — corners, wall/floor junctions, under-counter and behind-fridge darken; nothing renders black (the trap); `budget` geometry count and buildMs against ceilings (bake time shows in buildMs — record it; if > 1500ms, halve DIRS to 6 and STEPS to 4 and re-measure before anything else); low tier unaffected (probe once at low). Full sweep.
- [ ] **Step 5: Commit** — v2.482.0, `'The corners learn shadow (v2.482.0)'`, body with bake stats (meshes baked, clones minted, buildMs), push.

---

### Task 5: K5 — the contact discs join the batch

**Files:**
- Modify: `chauffeur/static/house.js` (`ysh` ~:4930s, `blobShadow` ~:740s)

**Interfaces:**
- Consumes: `cgeo`, `instanceYard` bucket rules (geometry.uuid|material.uuid|flags).
- Produces: `discMat(color, opacity)` — cached, `userData.shared = true`, MeshBasicMaterial with MultiplyBlending; both disc builders using one cgeo unit-circle per segment count and mesh-level scale.

- [ ] **Step 1: Implement.**

```js
    var discMatCache = {};
    function discMat(color, opacity) {
      var k4 = color + '|' + opacity;
      var m = discMatCache[k4];
      if (!m) {
        m = discMatCache[k4] = new T.MeshBasicMaterial({
          color: color, transparent: true, opacity: opacity,
          blending: T.MultiplyBlending, depthWrite: false });
        m.userData.shared = true;
      }
      return m;
    }
```

`blobShadow` (currently `new T.CircleGeometry(1, 20)` + per-call material): geometry → `cgeo('circ|20', function () { return new T.CircleGeometry(1, 20); })`, material → `discMat(C.shadow, 0.16)`; everything else identical. `ysh` (`CircleGeometry(1, Y2 ? 16 : 8)` + per-call material, opacity via colour... read the current body: it passes `color: tone || 0xa8a4aa` with no opacity — MultiplyBlending dark tones): geometry → `cgeo('circ|' + (Y2 ? 16 : 8), …)`, material → `discMat(tone || 0xa8a4aa, 1)` — CHECK the current ysh material's exact fields first and mirror them into discMat's cache key (if ysh sets no opacity, key on colour + blending only; do not invent an opacity it never had).

- [ ] **Step 2: Verify at the tiers that matter.** These discs exist only when `!SHADOWS` (low + medium): `python tools/house_probe.py --views exterior --budget --quality low --out .../k5low` and `--quality medium` — the yard's discs now fold into `instanceYard` (shared geometry+material buckets ≥ 8): record exterior in-frustum delta at low (expect a drop of roughly the yard's disc count minus buckets); screenshots at low/medium — contact discs still read as soft shadows, multiply blending intact, no z-fighting (renderOrder -1 preserved on ysh). High tier byte-identical. Live test; full sweep.
- [ ] **Step 3: Commit** — v2.483.0, `'The shadows share their ink (v2.483.0)'`, push.

---

### Task 6: R1 — the living room

**Files:**
- Modify: `chauffeur/static/house.js` (living-room builder block, ~:930-1560)

**Interfaces:**
- Consumes: `chamferGeo` (already live on every box), `latheAt`, `sweepAt`, `PROFILES`, finishes, `lb/lr/lc` local helpers.
- Produces: nothing new for later tasks — this is authored spend. Report records the room's part inventory and final budget.

**Process for every room pass (repeated verbatim in Tasks 6-10; read once, apply each time):**
1. Record the room's current in-frustum budget (`--views <room> --budget --quality high`) — ceiling = that number +15%.
2. Read the room's builder section fully before touching it. Every part below attaches to an EXISTING prop at coordinates you derive from that prop's authored literals.
3. Parts on zone props go inside the zone group (unique materials arrive automatically); static non-zone parts use shared materials so `mergeStatic` folds them.
4. After authoring: probe the room AND its lean-ins, at high; check the ceiling; run the live test; full sweep; screenshots stay in `$LOCALAPPDATA/Temp/house_quality/<room>/` and the report NAMES the directory (the controller sends shots to the user — do not skip this line).
5. The style bible governs: S2 palette roles, S4 three-accents-max, S7 silhouette/texture rules. A part that reads at neither the room camera nor the lean-in is not built.

**R1 part list (each row: prop → parts → technique/finish):**
- Built-ins (the punch-list "read as blocks") → face-frame strips on every opening (`box` with small `ch`), shelf front lips, `knob` lathe pulls ×doors, a plinth shadow-gap strip in `C.ink` at the base → shared mats, merge-folded.
- Hearth → `sweepAt` fire tools (poker + stand: 3 short sweeps + `finial`), a lathe log-bucket (`vase` profile squashed), mantle edge chamfer check (arrives from K1).
- Reading/floor lamp → `sweepAt` arm (existing lamp's stem coordinates), `shade` lathe at its head, `foot` lathe base.
- Plants → pots become `vase`/`foot` lathes (ceramic finish); leaf masses untouched (composition).
- Armchair + sofa (position frozen) → `foot` lathe feet ×4 each, seam piping as thin `sweepAt` runs along cushion edges (r ~0.012), throw pillow chamfer arrives free.
- TV/console → `knob` pulls, a soundbar chamfer strip, cable `sweepAt` drop (one, subtle, `C.ink`).
- Coffee table → `foot` feet, a `plate`+`cup` lathe pair on top (ceramic), book stack chamfer free.
- Gallery/frames → chamfer free; no new parts.

- [ ] **Step 1:** Budget-before recorded. **Step 2:** author the list. **Step 3:** verify per the room process (probe `--views living,lean_radio,lean_pet`). **Step 4:** Commit v2.484.0 `'The living room earns its keep (v2.484.0)'`, body = part inventory + budget before/after + screenshot dir, push.

---

### Task 7: R2 — the kitchen (the showcase)

**Files:**
- Modify: `chauffeur/static/house.js` (kitchen millwork + appliances, ~:1600-2400)

**Interfaces:** same as R1. Also fixes the open-items tier bug: `kWoodK = NICE ? 0xffffff : …` counter-wood mismatch — make medium's counter tone match high's (author the same effective tint through the tier ladder; verify with one medium-tier probe).

**R2 part list:**
- Fridge (zone) → the spike shipped for real: 4 `hinge` lathes on the west edge, 4 `foot` lathes, `sweepAt` D-pulls replacing the two box handles (keep tap/zone semantics — parts inside the fridge zone group), badge disc lathe, door gasket frames (thin `ch` boxes in `C.ink`), enamel finish already on from K3.
- Range → `knob` dials ×5 (front rail), oven-door `sweepAt` pull, `hinge` caps ×2, a chamfered kick strip; hood rivet dots only if they read (S7 judgment).
- Island → `pull` lathe or swept pulls on every drawer front (count from the millwork loop), corner post chamfers free, stool feet (`foot` ×4 per stool, `C.ink`).
- Sink/faucet → faucet becomes a proper `sweepAt` gooseneck + `knob` handles ×2; sink basin rim chamfer free.
- Open shelving → `jar`+`lid` (glassy + brass), `bowl`, `plate` stack, `cup` ×2 from PROFILES on EXISTING shelf boards, replacing any box stand-ins already there 1:1 (no net new clutter beyond the licence; S4 accent discipline — teal stays the zone's).
- Window/pane hardware → latch `knob`, sill chamfer free.
- Wall calendar/corkboard-successor surfaces: untouched (painted faces).

- [ ] Steps as the room process; probe `--views kitchen,lean_fridge,lean_counter,lean_board,lean_calendar`; medium-tier probe for the counter fix. Commit v2.485.0 `'The kitchen answers the reference (v2.485.0)'`, push.

---

### Task 8: R3 — mudroom + pantry

**Files:**
- Modify: `chauffeur/static/house.js` (mudroom block ~:4300-4700, pantry block ~:2230-2400)

**R3 part list:**
- Hooks → each becomes a `sweepAt` J-hook (brass) on the existing rail coordinates; backpack straps stay honest (count semantics untouched — parts only on the RAIL, never on the bags).
- Bench → `foot` feet, edge chamfer free, a seat-plank groove strip (thin `C.cabShade` inlays).
- Cubbies → face-frame strips + `knob` pulls (matches built-ins language from R1).
- Street door (zone 'door') → panel rails/stiles as shallow `ch` boxes INSIDE the door zone parts, `knob` handle upgrade to lathe, `hinge` ×3 on the jamb side.
- Garage door (interior face, zone 'door' hero surface) → untouched (painted face).
- Pantry (zone 'board') → jars already glassy from K3; add `lid` brass lids if K3 didn't; shelf front lips; the paneled pantry door gets rails/stiles relief (it hides on lean-in — parts ride `pantryDoor` so they hide with it; VERIFY the lean-in still swaps it correctly 3×).

- [ ] Room process; probe `--views mudroom,lean_door,lean_board`. Commit v2.486.0 `'The mudroom hangs its hooks (v2.486.0)'`, push.

---

### Task 9: R4 — garage + the vehicle-artist pass

**Files:**
- Modify: `chauffeur/static/house.js` (`buildVehicle`/`buildCar` ~:3900-4260, garage clutter ~:3400-3700)

**Interfaces:**
- Consumes: the parametric contract — cars build from the car record; `body_type`, `color_code` (paint), `seat_capacity` (length nudge) are the ONLY inputs. Everything below varies by body_type via the existing per-body parameter tables, never by new record fields.

**R4 part list (cars — the punch list's "blocks"):**
- Wheels → real assemblies: tyre torus (existing) + `foot`-profile rim lathe + hub `knob`, ink/steel; one shared geometry per radius via cgeo.
- Lights → head/tail housings as small lathes (`finial` squashed), emissive-free (paint only; glow stays the zones' language).
- Grille → chamfered slat strips per body table; bumpers get end chamfers + `sweepAt` trim line.
- Mirrors → stalk `sweepAt` + chamfer head, both sides.
- Glass → existing inset panes get `finish: 'glassy'`? NO — cars rebuild per payload with fresh materials (L1 note at the plate stamp); transparent car glass at high only, same fresh-material path, `thick: 0.06`; verify rebuild path still disposes nothing shared.
- Body silhouettes → the minivan/van separation (open items): raise the van's roofline constant + lengthen the minivan's bonnet in the body tables until the two read apart at exterior distance (probe proof).
- Door seams → thin `C.ink` recess strips per body table.
- **Budget note:** cars are zone-tagged (unique materials, never merged) — every part is a real draw. Cap the per-car part count so garage stays under its ceiling: target ≤ +12 draws per car at high; degrade parts below high (wheels keep rims, lose hubs; mirrors go; seams stay).
- Garage clutter → existing tool silhouettes get chamfer free; add `sweepAt` hose coil replacing the torus stack if it reads better (judge); shelf boxes get lids (chamfer).
- Bus (curb) → same wheel/light treatment via its existing build path; the stop-arm lettering fix belongs to R5's exterior read — SKIP here.

- [ ] Room process; probe `--views garage,lean_garage` plus exterior (driveway cars show); verify `syncGarage` rebuild ×2 payload changes leak nothing (repeat state flip in live test run). Commit v2.487.0 `'The cars stop being blocks (v2.487.0)'`, push.

---

### Task 10: R5 — the exterior

**Files:**
- Modify: `chauffeur/static/house.js` (exterior textures ~:2780-2900, yard props, curb)

**R5 part list:**
- **Normal maps from the canvases you already draw** (~20 lines): derive height→normal from `shingleT` and `sidingT` canvases (sample luminance neighbours, pack into a second canvas, `material.normalMap = …`, `normalScale` ~0.35); PBR tier only; the material is the roof/siding shared one — flip on its cached instance.
- Door hardware → front door `knob` + plate, kick plate chamfer strip; coach lamp becomes a small lathe (`finial` + `shade`) with its existing glow behavior untouched.
- Gutters/downspouts → `sweepAt` runs along the two eave lines + one downspout per gable end, `EXTC.trim` colour, shared mats (merge-folds).
- Bus-stop arm (open items: reads as no-entry) → paint 'STOP' lettering into a small canvas texture on the octagon face (canvas idiom, cached) — text on a SIGN is scenery language, allowed; verify it reads at curb distance.
- Fence/gate → hinge + latch parts at the gate coordinates (sweep + knob).
- Mailbox → flag `sweepAt` + `knob` finial.
- Planting/yard: untouched (instanced; composition frozen).

- [ ] Room process; probe `--views exterior` + a curb-framed `--cam` shot for the stop arm; confirm instanceYard/merge numbers hold (new shared statics fold). Commit v2.488.0 `'The exterior earns its close-up (v2.488.0)'`, push.

---

### Task 11: L — the lighting slice

**Files:**
- Modify: `chauffeur/static/house.js` (rig ~:360-515, `SUN_OFF`/`aimShadow` ~:437-476, floor/counter textures)

**Interfaces:**
- Consumes: `SUN_OFF = new T.Vector3(21, 24, 9)`, `SHADOW_BOX` table, `aimShadow()`, the light-budget comment (fill+key ≈0.90 square to sun, pools to ~1.05, shade ~0.40), pool lamps, `woodTex`/floor canvas builders.

- [ ] **Step 1: Rake the sun.** Try, in order, `SUN_OFF` candidates `(9, 24, 24)`, `(4, 22, 26)`, `(14, 20, 24)` — each swings the key toward the south-east so it rakes across the north-wall run instead of arriving near-frontal. For each: probe all five views at high; judge (a) form — counters, car hoods, the island show a lit/shade gradient; (b) the kitchen's subject wall (north run) must NOT fall dark — measure with PIL region mean over the upper-third of the kitchen shot, require ≥ 0.9× the pre-rake mean; (c) every room's `SHADOW_BOX` still contains its shadows (no clipped diagonals — the batching-era bug class). Pick the best; record all three sets of numbers.
- [ ] **Step 2: The north fill.** Add beside the rig:

```js
    /* L (quality spec §5): the rake's ransom — a dim cool fill aimed at
       the north run so raking the key for form does not price the
       kitchen's subject wall into shadow. No shadow map; it is a fill. */
    var fillN = new T.DirectionalLight(0xdfe8f2, PBR ? 0.14 : 0.10);
    fillN.position.set(-2, 9, 26);
    fillN.target = sunTarget;
    scene.add(fillN);
```

Tune intensity until the PIL region check from Step 1(b) recovers to ≥1.0× pre-rake while shaded sides keep their gradient (spot-check the range's side faces). Update the light-budget comment with the new arithmetic (fill+key sums, pool peaks).
- [ ] **Step 3: Baked gradients.** Walls: give the shared wall material a subtle vertical-gradient canvas map (cream top → 6% darker at floor, 128px, cached) — mapped materials are exempt from the scenery pull by design, which is correct for architecture; VERIFY `applyScenery` still classifies them (mapped = no lightness pull, saturation still applies). Counters: replace the one shared `woodLight` on counter TOPS with per-run `counterTex(len)` — same grain painter plus a centre-brighter pool (radial +8% under each pool lamp's x) — two or three distinct runs, cgeo/mat cache keyed by run id. Floors already pool (existing idiom) — extend the great-room floor's radial to sit under ITS lamp.
- [ ] **Step 4: Tier consistency.** With the K-slices in: probe kitchen at high, medium, low; fix remaining authored mismatches (the counter tone fix landed in R2; check hood steel, island walnut) so a demoting panel changes fidelity, never colour — quote the tier-ladder comment and update it.
- [ ] **Step 5: Verify + commit.** All five views + lean_calendar/lean_board/lean_fridge before/after at high, medium probes for tiers; budget (lights are free draws but merged-material map flips can split buckets — check); live 3×; sweep. Commit v2.489.0 `'The light finally rakes (v2.489.0)'`, body with the chosen SUN_OFF, fill numbers and the re-stated light budget, push.

---

### Task 12: Wrap-up

**Files:**
- Modify: `docs/superpowers/specs/2026-09-10-house-quality-pass-design.md` (append `## 9. Results`)
- Modify: `docs/superpowers/plans/2026-09-09-house-open-items.md` (mark retired items)
- Maybe: `chauffeur/system_capabilities.md` (Home paragraph — one line: detail kit + AO + lighting pass, tiers unchanged)

- [ ] **Step 1:** Results section: per-room budget before/after vs ceilings, buildMs trajectory, bake stats, chosen lighting numbers, screenshot directories, the retired punch-list items (armchair-read, built-ins-blocks, cars-blocks, minivan/van, bus-arm, counter-tier, wall gradients, sun rake), and any accepted misses.
- [ ] **Step 2:** Open-items doc: strike-through-with-date (do not delete) each retired row; leave live ones.
- [ ] **Step 3:** Final probe `--views all --budget --quality high` + full sweep as the closing gate.
- [ ] **Step 4:** Commit v2.489.1 `'Write down what the detail bought (v2.489.1)'`, push.

---

## Self-review notes (applied)

- **Spec coverage:** §3 K1-K5 → Tasks 1-5; §4 R1-R5 → Tasks 6-10 (each room's punch-list items named in its part list); §5 L → Task 11; §6 guards → Global Constraints + per-task verify steps; §7 settled questions encoded (AO split K4/L; chamfer default-on with authored opt-outs listed in Task 1 Step 3; roundedGeo retirement per-site in Task 1 Step 4; density stop-rule in the room process).
- **Known risk ledger for the controller:** K4's shared-geometry clone trade is the likeliest budget fight (explicit fallback authored); K1's cache-key split (`b|w|h|d|ch`) grows geometry count — bounded by +10% guard; R4's per-car draw cap is the likeliest taste-vs-budget fight (cap stated: ≤ +12 draws/car, degrade order given).
- **Type consistency:** `chamferGeo(w,h,d,ch)` / `opts.ch` (Tasks 1,6-10); `latheAt(key,s,c,x,y,z,group,opts)` + `PROFILES` keys quoted identically in Tasks 2 and 6-10; `opts.finish` tokens `'enamel'|'glassy'|'ceramic'` (Tasks 3,7,9); `AO_OCCLUDERS` row shape `[x0,x1,y0,y1,z0,z1]` single definition (Task 4); `discMat(color, opacity)` (Task 5).

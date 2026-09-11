# House Shell + Occlusion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Seal the house (south wall + full roof), replace the four hand-written hide: arrays with a fabric registry + half-space solver, and render occluding shell fabric as prebuilt ghost edge outlines on every tier.

**Architecture:** Five slices: (1) registry lands and the five existing hide-groups migrate into registrations with zero behavior change; (2) the solver replaces the hide arrays, verdict-for-verdict equal to today's sets; (3) ghost edges replace plain hiding for shell pieces; (4) the new south wall + roof completion seal the house and the whole shell registers; (5) wrap. Everything obeys the batching laws (L1 zone materials, cache sharing, merge fences, tag-only taps, honest buildMs) and the quality-pass lifecycle law (cgeo owns geometry, mkTex owns textures, build-once ghosts are never disposed).

**Tech Stack:** three.js (vendored `static/vendor/three.min.js`, global `THREE` via `T`), vanilla ES5 in `chauffeur/static/house.js`, Python/Playwright harness (`tests/live_app.py`, `tests/test_house_live.py`, `tools/house_probe.py`).

**Spec:** `docs/superpowers/specs/2026-09-11-house-shell-occlusion-design.md` — binding. Batching laws travel: `docs/superpowers/specs/2026-09-10-house-batching-design.md`.

## Global Constraints

- **ES5 only in `house.js`** (var/function; no arrows, const/let, template literals; Set/Map fine). Python tests may use modern JS inside `page.evaluate` strings.
- **Budget ceilings at quality=high:** exterior 1231 / kitchen 418 / living 730 / mudroom 382 / garage 539 in-frustum (quality-pass closing gate) **+10% per slice**; Task 4's new fabric raises exterior/kitchen honestly — record before/after per view. Instrument: `python tools/house_probe.py --views all --budget --quality high --day` from `chauffeur/`.
- **buildMs ≤1500ms at high** (AO ~1100 of it today; EdgesGeometry builds add — measure; lazy-build-on-first-ghost is the authored fallback, not the default).
- **Batching laws verbatim:** registered fabric = its own merge unit (L5); ghost LineSegments never merge with meshes, share ONE LineBasicMaterial; zone-owned parts keep unique materials; tap routing stays stamped-tag-only.
- **Lifecycle law:** ghost edge geometries + the shared line material are build-once — no rebuild path may dispose or re-mint them; the three pinned leak scenarios in `tests/test_house_live.py` stay green.
- **Zero pixel change** for existing fabric when SOLID, at every tier, in every slice (Task 4's additions are the one composition change, gated by user screenshots).
- **Tests:** full sweep `python tools/test.py` from `chauffeur/` before every commit (never piped; one flaky browser failure → isolated re-run). `python tests/test_house_live.py` green in every task. New probe/PIL work runs with `--day`.
- **Commits:** bump `chauffeur/config.yaml` `version:` per task (ladder below), poetic one-line message + `(vX.Y.Z)`, single quotes (PowerShell splits doubles), push. `static/kitchen.js` never touched.
- Line numbers reference v2.490.4 and drift; anchor by quoted code.

## Version ladder

T1 2.491.0 · T2 2.492.0 · T3 2.493.0 · T4 2.494.0 · T5 2.494.1. Fix rounds take the next patch on the slice's minor.

---

### Task 1: The fabric registry (registration only, zero behavior change)

**Files:**
- Modify: `chauffeur/static/house.js` (helper layer near `cgeo`/`mat` ~:700-1000 for the registry; group build sites ~:1210 westWallG, ~:3702 garageDoorG, ~:5203 mudroomRoofG, ~:5810 livingRoofG, ~:5834 yardG; fence assembly ~:6501-6570)
- Test: `chauffeur/tests/test_house_live.py` (new scenario)

**Interfaces:**
- Produces: `regFabric(group, opts)` — registers a shell piece; `opts = {n: [x,y,z] outward unit normal, box: [x0,x1,y0,y1,z0,z1] world AABB, mode: 'ghost'|'hide' (default 'ghost'), name: string}`. `FABRIC` array of `{g, n (T.Vector3), box, mode, name, edges: null}` in build order. `window.chfShellFabric()` (debug/test hook) returns `[{name, mode, visible}]`.
- Produces for Task 2/3: `FABRIC` entries are the solver's domain; `edges` slot is filled by Task 3.

- [ ] **Step 1: Write the failing test.** New scenario in `tests/test_house_live.py` (follow the existing scenario idioms: `_seed`, route via `live_app`, `DAY_LOCK_JS`):

```python
def scenario_shell_fabric_registry(page, served):
    page.goto(served.url('house?quality=high'))
    page.wait_for_selector('#room canvas', timeout=20000)
    page.wait_for_timeout(2200)
    fab = page.evaluate("window.chfShellFabric()")
    names = sorted(f['name'] for f in fab)
    check(names == ['garage_door', 'living_roof', 'mudroom_roof',
                    'west_wall', 'yard'],
          'registry must hold exactly the five migrated pieces: %r' % names)
    yard = [f for f in fab if f['name'] == 'yard'][0]
    check(yard['mode'] == 'hide', 'yard is the one authored hide piece')
    check(all(f['visible'] for f in fab),
          'exterior boot: every piece visible (solid): %r' % fab)
```

- [ ] **Step 2: Run it to verify it fails** (`python tests/test_house_live.py` — `chfShellFabric` undefined).

- [ ] **Step 3: Implement the registry** in the helper layer (ES5):

```js
    /* ---- SHELL (shell spec section 3): the fabric registry -------------
       Every shell piece registers itself where it is built. The solver
       (section 4) reads FABRIC; mergeStatic and the fence sets read it so
       shell membership is declared exactly once. Registration only —
       visibility stays with the legacy hide: arrays until the solver
       lands. */
    var FABRIC = [];
    function regFabric(group, o) {
      FABRIC.push({ g: group, name: o.name,
                    n: new T.Vector3(o.n[0], o.n[1], o.n[2]).normalize(),
                    box: o.box, mode: o.mode || 'ghost', edges: null });
    }
```

Register the five at their build sites (normals face OUTWARD from the interior; yard's normal is up and unused by mode 'hide' but recorded for uniformity). Derive each `box` from the group's built extents — after building the group, compute via `new T.Box3().setFromObject(g)` ONCE at build (ES5, build-time only) and pass the six numbers; do not hand-type guesses:

```js
    regFabric(westWallG,   { name: 'west_wall',   n: [-1, 0, 0], box: wwBox });
    regFabric(garageDoorG, { name: 'garage_door', n: [0, 0, 1],  box: gdBox });
    regFabric(mudroomRoofG,{ name: 'mudroom_roof',n: [0, 1, 0],  box: mrBox });
    regFabric(livingRoofG, { name: 'living_roof', n: [0, 1, 0],  box: lrBox });
    regFabric(yardG,       { name: 'yard', mode: 'hide', n: [0, 1, 0], box: ydBox });
```

- [ ] **Step 4: Registry feeds the fences.** Where `EXT_NO_MERGE` adds `yardG`/`garageDoorG` and `NO_MERGE` adds the shell groups today, replace those SHELL adds with one loop (prop entries stay hand-fenced):

```js
    FABRIC.forEach(function (f) { EXT_NO_MERGE.add(f.g); NO_MERGE.add(f.g); });
```

Verify against the current sets: the loop must reproduce exactly the shell membership the hand adds produced (westWallG was in NO_MERGE; yardG/garageDoorG in EXT_NO_MERGE; mudroomRoofG/livingRoofG per current code — read the two set builds and keep EFFECTIVE membership identical; if a group was deliberately only in one set, preserve that by splitting the loop accordingly and say so in your report).

- [ ] **Step 5: Export the hook** beside the other `window.chf*` exports: `window.chfShellFabric = function () { return FABRIC.map(function (f) { return { name: f.name, mode: f.mode, visible: f.g.visible }; }); };`

- [ ] **Step 6: Verify zero behavior change.** `python tools/house_probe.py --views all --budget --quality high --day`: every number bit-identical to a control run at HEAD~0 before your change (two-run control method). Live test green; new scenario green.

- [ ] **Step 7: Full sweep, commit** `'The shell learns its own name (v2.491.0)'`, push.

---

### Task 2: The solver replaces the hide arrays (verdict-equal swap)

**Files:**
- Modify: `chauffeur/static/house.js` (ROOMS registry ~:7884; enterRoom ~:7906; goExterior ~:7940; frameZone/lean-in path; solver beside the registry)
- Test: `chauffeur/tests/test_house_live.py` (extend the registry scenario into a verdict table)

**Interfaces:**
- Consumes: `FABRIC`, `regFabric` (Task 1); `zoneFaceQuad(key)` (~:7908, existing) for lean-in subjects; `webgl.shadowDirty()`.
- Produces: `solveShell(camPos, subject)` — subject is `{box: [x0,x1,y0,y1,z0,z1]}` (room) or `{point: T.Vector3}` (zone quad centre); applies verdicts (fill visibility now; Task 3 adds edges) and calls `webgl.shadowDirty()`. `roomsReg()` entries gain `aabb: [x0,x1,y0,y1,z0,z1]`. `window.chfShellFabric()` now also returns `verdict: 'solid'|'ghost'|'hide'` per piece. The `hide:` keys and both show-all loops are DELETED.

- [ ] **Step 1: Write the failing verdict-table test** (extends the Task 1 scenario; expected sets are TODAY'S legacy hide sets, proving the swap is behavior-preserving):

```python
    LEGACY = {
        'exterior': [],
        'kitchen':  ['yard'],
        'garage':   ['garage_door', 'yard'],
        'mudroom':  ['mudroom_roof', 'west_wall', 'yard'],
        'living':   ['living_roof', 'yard'],
    }
    for view, expected in LEGACY.items():
        if view == 'exterior':
            page.evaluate("window.chfHouseExit && window.chfHouseExit()")
        elif view == 'kitchen':
            page.evaluate("window.chfHouseEnter()")
        else:
            page.evaluate("window.chfHouseEnterRoom(%r)" % view)
        page.wait_for_timeout(1400)
        fab = page.evaluate("window.chfShellFabric()")
        offed = sorted(f['name'] for f in fab if f['verdict'] != 'solid')
        check(offed == sorted(expected),
              '%s: solver must reproduce the legacy set, got %r' % (view, offed))
```

- [ ] **Step 2: Run to verify it fails** (no `verdict` field yet).

- [ ] **Step 3: Implement the solver** (ES5, beside the registry):

```js
    /* ---- SHELL (spec section 4): the half-space solver ------------------
       Camera-settle only. A piece ghosts when the camera is on its outward
       side and the subject on its inner side, and its box overlaps the
       camera-subject corridor. mode 'hide' pieces hide under the same
       verdict. Exterior: everything solid. */
    function boxCentre(b) {
      return new T.Vector3((b[0]+b[1])/2, (b[2]+b[3])/2, (b[4]+b[5])/2);
    }
    function corridorHits(b, cam, sub, pad) {
      var lo = [Math.min(cam.x, sub.x) - pad, Math.min(cam.y, sub.y) - pad,
                Math.min(cam.z, sub.z) - pad];
      var hi = [Math.max(cam.x, sub.x) + pad, Math.max(cam.y, sub.y) + pad,
                Math.max(cam.z, sub.z) + pad];
      return b[0] <= hi[0] && b[1] >= lo[0] && b[2] <= hi[1] &&
             b[3] >= lo[1] && b[4] <= hi[2] && b[5] >= lo[2];
    }
    function solveShell(camPos, subject) {
      var subPt = subject && subject.point ? subject.point
                : subject ? boxCentre(subject.box) : null;
      FABRIC.forEach(function (f) {
        var v = 'solid';
        if (subPt) {
          var p = boxCentre(f.box);
          var camOut = f.n.dot(new T.Vector3().subVectors(camPos, p)) > 0;
          var subIn  = f.n.dot(new T.Vector3().subVectors(subPt,  p)) < 0;
          if (camOut && subIn && corridorHits(f.box, camPos, subPt, 1.5)) {
            v = f.mode === 'hide' ? 'hide' : 'ghost';
          }
        }
        f.verdict = v;
        /* Task 3 gives 'ghost' its edges; until then ghost draws as hide */
        f.g.visible = (v === 'solid');
      });
      if (webgl) webgl.shadowDirty();
    }
```

- [ ] **Step 4: Wire it in.** `roomsReg()` entries gain `aabb` (derive per room at build the same `Box3` way, from the room's floor+walls extent; kitchen/living share the great-room plate — each room still gets ITS OWN aabb around its furniture footprint). `enterRoom`: delete the show-all/hide loops; call `solveShell(room.pos, {box: room.aabb})` where the hide dance was (before the tween, per spec: solve against the destination). `goExterior`: delete its loop; call `solveShell(webgl.EXT_POS, null)`. Lean-in (`frameZone` callback / `chfKitchenFocus` path): after focus resolves, `solveShell(<zone camera pos>, {point: <zone quad centre>})` — read `zoneFaceQuad(key)` for the quad and reuse its centre; on `announceFocus(null)` re-solve for the room. Update `window.chfShellFabric` to include `verdict`.
- [ ] **Step 5: Tune to verdict-equality.** Run the table test. If a legacy set disagrees (e.g. mudroom's west wall verdict misses because the camera sits inside the wall's plane slack), adjust the piece's registered normal/box (registration data, never per-room code) until all five views match. Every adjustment goes in your report with the geometric reason.
- [ ] **Step 6: Verify.** Table test green; budget probe bit-identical per view (visibility sets identical ⇒ in-frustum identical); live 3x; tap scenario green (`scenario_garage_rebuild...` and the lean-in leak scenario exercise taps/focus).
- [ ] **Step 7: Full sweep, commit** `'The house decides what stands aside (v2.492.0)'`, push.

---

### Task 3: Ghost edges

**Files:**
- Modify: `chauffeur/static/house.js` (post-`mergeStatic` build step ~:6580; solver verdict application; one shared line material near the helper layer)
- Test: `chauffeur/tests/test_house_live.py` (extend verdict scenario with a pixel check)

**Interfaces:**
- Consumes: `FABRIC` (+`edges` slot), `solveShell` verdicts, `mergeStatic` output (each fabric group's merged mesh(es)).
- Produces: per-piece `f.edges` LineSegments (build-once, `.visible=false` default); `GHOST_MAT` shared LineBasicMaterial; verdict `'ghost'` now = fills hidden + edges shown; `'hide'` unchanged (yard).

- [ ] **Step 1: Write the failing pixel test.** Extend the scenario: enter mudroom (west wall verdict `ghost` after Task 4 registers walls... UNTIL then the migrated five include west_wall in mudroom — it ghosts now instead of hiding). Assert (a) verdictry: `west_wall` verdict == `'ghost'`; (b) pixels: screenshot crop over the west wall's screen region contains ≥ N dark-line pixels (PIL count of pixels within tolerance of the ghost line colour 0x2d2018) where the pre-task control crop had ~0. Sample the crop rect from a probe shot; hard-code the rect + N in the test with a comment naming the derivation run.
- [ ] **Step 2: Run to verify it fails** (verdict is ghost but no edges exist — fills just hide, no line pixels).
- [ ] **Step 3: Build the ghosts** after `mergeStatic` (build-once; lifecycle law):

```js
    var GHOST_MAT = new T.LineBasicMaterial({ color: 0x2d2018,
      transparent: true, opacity: 0.55 });
    FABRIC.forEach(function (f) {
      if (f.mode === 'hide') return;                 /* yard never ghosts */
      var segs = [];
      f.g.traverse(function (o) {
        if (o.isMesh && o.geometry) {
          var e = new T.EdgesGeometry(o.geometry, 35);
          var ls = new T.LineSegments(e, GHOST_MAT);
          ls.position.copy(o.position); ls.rotation.copy(o.rotation);
          ls.scale.copy(o.scale); segs.push(ls);
        }
      });
      var eg = new T.Group();
      segs.forEach(function (s) { eg.add(s); });
      eg.visible = false; eg.renderOrder = 5;
      f.g.parent.add(eg); f.edges = eg;
    });
```

(Traverse AFTER merge so each fabric group is few meshes; copy each merged mesh's transform. NO_MERGE must skip `eg` — LineSegments are not meshes, mergeStatic's mesh filter already skips them; verify by reading the filter and state the line in your report.)
- [ ] **Step 4: Apply in the solver.** In `solveShell`'s verdict application: `f.g.visible = (v === 'solid'); if (f.edges) f.edges.visible = (v === 'ghost');`
- [ ] **Step 5: Verify.** Pixel test green; buildMs at high measured 3 runs (edges cost stated; ≤1500 or switch to the authored lazy fallback and say so); budget: ghosted views gain ≤1 in-frustum per ghosted piece (the LineSegments group) — record per view; tiers: probe low/medium/high mudroom, edges visible in all three; leak scenarios green (edges never disposed/rebuilt).
- [ ] **Step 6: Full sweep, commit** `'The walls keep their outline when they step aside (v2.493.0)'`, push.

---

### Task 4: The seal — south wall, roof completion, whole-shell registration

**Files:**
- Modify: `chauffeur/static/house.js` (exterior build ~:1200-1400 wall runs, roof build, garage shell; registrations at each site)
- Test: verdict table gains the new pieces per view

**Interfaces:**
- Consumes: `regFabric`, existing wall/roof/siding material caches (`sidingT`-mapped mat with R5 normal map), pane idiom (`paneMesh` pattern ~:2591), plaster/`wallGradTex` interior idiom (T11), `stampHouse` room tags.
- Produces: sealed exterior; full registration set per spec section 3 (south wall NEW, north/east walls, both main-roof slopes, garage walls+roof registered; names: `south_wall`, `north_wall`, `east_wall`, `roof_south`, `roof_north`, `garage_shell`).

- [ ] **Step 1: Build the south wall.** Derive the great-room south edge + width from the existing floor plate extents (`Box3` on the great-room floor group at build). Full-width clapboard run: exterior face = the shared siding-mapped material (cache hit — R5 normal map rides along); interior face = plaster with `wallGradTex` (T11 idiom, mapped ⇒ scenery-exempt); two windows flanking centre reusing the pane idiom (glass = existing pane material family, `transparent` ⇒ never merges — that is the standing law, keep the panes OUT of the fabric group fills? NO: panes are part of the piece and hide with it; transparent-never-MERGES only constrains mergeStatic, visibility grouping is unaffected); trim + kick consistent with R5 front-door hardware scale. Stamp `room: 'kitchen'` (stampHouse idiom) so exterior taps on it enter the great room. `regFabric(southWallG, { name: 'south_wall', n: [0, 0, 1], box: swBox })`.
- [ ] **Step 2: Complete the roof.** Read the architect-pass main roof (both slopes + fascia): close any cutaway/gap over the great-room front so the shell is watertight from EXT_POS and from a 360 probe orbit (`--cam` overrides, 4 compass shots). Register `roof_south` (n `[0, 0.8, 0.6]`-ish — the slope's true outward normal, computed from its geometry at build, not hand-typed), `roof_north`, `north_wall`, `east_wall`, `garage_shell` (walls+gable as one piece; `garage_door` stays its own piece).
- [ ] **Step 3: Extend the verdict table** for every view with the full registration set (derive expected sets by the solver's own math BY HAND in the test comment — e.g. kitchen HOME camera sits south-east of the great room: expect `south_wall`, `roof_south`, `east_wall`(?) ghost, `north_wall` solid... whatever the registered normals/boxes yield; the point of the table is that a human wrote the expectation down). Assert no view ghosts EVERYTHING (sanity) and exterior ghosts NOTHING.
- [ ] **Step 4: Screenshot gate.** Probe exterior (default + 4 compass `--cam` shots) at high + the five room views + two lean-ins. Save under `$LOCALAPPDATA/Temp/house_quality/shell-T4`. NAME the directory in your report — the controller sends the exterior set to the user and the arc pauses there if redirected.
- [ ] **Step 5: Verify.** Verdict table green; budget: exterior/kitchen raises recorded (new fabric) and under ceilings (+10% on closing gates); zero pixel change control-run for NON-new fabric at exterior; tap scenario: exterior tap on south wall enters kitchen (extend the tap assertion in the live test with one `page.mouse.click` at a south-wall screen point + mode readback via `window.chfHouseMode()`); buildMs re-measured; leak scenarios green.
- [ ] **Step 6: Full sweep, commit** `'The house closes its shell (v2.494.0)'`, push.

---

### Task 5: Wrap-up

**Files:**
- Modify: `docs/superpowers/specs/2026-09-11-house-shell-occlusion-design.md` (append results to `## 9. Results`)
- Modify: `chauffeur/system_capabilities.md` (Home paragraph: one line — sealed shell, ghost-edge occlusion, registry+solver replace hide arrays, all tiers)

- [ ] **Step 1:** Results: registration table (pieces, modes), per-view verdict sets, budget before/after vs ceilings per view, buildMs trajectory incl. edges cost, ghost line constant, screenshot directories, deviations ruled during the arc.
- [ ] **Step 2:** Capabilities line (exact numbers from Step 1, not from memory).
- [ ] **Step 3:** Closing gate: `python tools/house_probe.py --views all --budget --quality high --day` + full sweep.
- [ ] **Step 4:** Commit `'Write down how the house closed (v2.494.1)'`, push.

---

## Self-review notes (applied)

- **Spec coverage:** section 3 registry → T1 (+T4 completes the set); section 4 solver → T2; ghost mechanics → T3; section 6 seal → T4; section 5 tap law → T4 Step 1/5; section 7 guards → Global Constraints + per-task verify; section 8 settled points encoded (ghost constant in T3 code; lean-in subject in T2 Step 4; out-of-scope list untouched by any task).
- **Placeholder scan:** the two derive-at-build values (fabric boxes, roof normals) are method-specified (`Box3`/geometry-computed at build, never hand-typed) — deliberate, since hand-typed world coordinates in a plan rot against the live scene; T3's pixel-rect hard-codes come from a named derivation run.
- **Type consistency:** `regFabric(group, {n, box, mode, name})` and `FABRIC` entry shape identical in T1/T2/T3/T4; `solveShell(camPos, subject)` subject shapes `{box}` | `{point}` | `null` consistent in T2/T4; verdict strings `'solid'|'ghost'|'hide'` everywhere; `window.chfShellFabric()` field growth T1→T2 stated in both tasks.
- **Known risk ledger for the controller:** T2 Step 5 (verdict-equality tuning) is the likeliest fix-loop; T3's per-mesh transform copy assumes merged meshes carry identity-or-simple transforms (mergeStatic bakes world transforms into geometry — if merged meshes sit at identity, the copy is a no-op and correct either way; reviewer verifies); T4's garage_shell-as-one-piece may ghost the whole garage from the living room — the corridor test should prevent it, watch in review.

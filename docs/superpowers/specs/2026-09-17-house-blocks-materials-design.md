# The Home — blocks, materials and the photo pipeline (massing arc 2 of 3)

Binding spec, user-ratified 2026-09-17; **revised 2026-09-17 after two review rounds** (in-session plus third-party, twice; every change is marked *rev*, second-round changes *rev2*). Second of the three massing specs: 1. the regular house + orbit (shipped v2.499.31–.40) → **2. blocks, materials, roof forms, the photo pipeline** (this document) → 3. style kits. Every prior house law travels with it: batching, the lifecycle law (mkTex owns textures; cgeo owns geometry), the shell registry, view-volume masking and the roof valleys (`2026-09-16-house-view-volume-masking-design.md`), and the facade generator (`2026-09-15-house-facade-generator-design.md`: slots, spans, palette names, saved facades, review-before-save).

Spelling: **story / stories** throughout the spec, the code and the UI. Roof language: **ridge direction and the face the gable shows**, never "side-gabled" / "front-gabled" (the two terms contradicted each other in the first draft's worked example).

## 0. Prerequisites (*rev*: parked from arc 1, live bugs the moment these become settings)

Landed first, each with its own commit and pin, before any schema work:

- A ridge-z block renames its roof pieces (`_west/_east` vs `_front/_back`, `house.js` ~5013), so `EXTERIOR_HINTS` and the registry pin are canonical-only. Fix: piece names independent of ridge; the registry pin holds for every ridge.
- `roofVault(GARAGE_BLOCK, …, Math.PI / 8)` reads the literal; must read `BLOCK_PITCH`. `hipEndAt`'s local pitch must read `PITCH_FAMILY`.
- The bay-gable meet is solved against the street deck only; it must solve against whichever deck the bay meets (hip garage variant).
- Hip and ridge-z main roofs are probe-only: add live pins (roof-line audit, exterior budget) for `main hip/x`, `main gable/z`, `garage hip/z`.

## 1. Why

Two photos the user handed over read as "a different house in the right places": a brick house with a gable-end-to-the-street garage (ridge z) on the LEFT beside a hip-roofed main block carrying two front gables; and a farmhouse with a two-story centre showing its gable to the street, a wing with the ridge along the street, a gabled porch, a shed-roofed bay and a garage out of frame. The facade generator cannot express any of that. Its vision prompt describes an 18-slot strip; its vocabulary has two claddings and no roof form, ridge direction, story count, base band or shed; and the one pass is never checked against the photo. The mismatch is silent.

This arc gives the house a **block model** that the builders, the vision prompt, the editor and (next arc) the style kits all read; a real materials vocabulary; a horizontal **mirror** so a garage on the right is one flag; a **describe-then-critique** photo pipeline that renders its own draft in the editor and compares; and an **unexpressed** list so what the schema cannot hold is shown, never dropped.

Ruled out (user, 2026-09-17): free block placement. The two blocks keep their footprints and the rooms keep their local coordinates; the mirror covers the most common asymmetry at a fraction of the cost.

## 2. The block model

```
house: {
  version: 2,
  mirror: false,
  pitch_deg: 22.5..35,          // roof FEATURES (gable/dormer/shed/hip_end), as V1; default 34.8 (PITCH_FAMILY)
  blocks: {
    main:   { depth: 0..6, stories: 1|2, roof: { form: gable|hip, ridge: x|z, pitch_deg: 22.5..35 },   // block pitch, default 22.5 (BLOCK_PITCH)
              cladding: batten|lap|brick|stone|stucco|shingle,
              base: { material, height: 0.6..1.8, body: <palette name> } | null,
              body: <palette name> },
    garage: { same fields, plus orientation: front|side }
  },
  style: { roof: <palette>, frame: <palette>, door: <palette>, trim: <palette> },
  ground: [ window { slot, span, size, shutters: bool, story: 1|2 }
          | door | garage_door
          | porch { slot, span, type, roof: flat|gable } ],
  roof:   [ { slot, span, kind: gable|dormer|shed|hip_end, window: bool, cladding?: <material> } ],
  unexpressed: [ string ≤ 80 chars, ≤ 8 of them ]
}
```

- **Blocks**: the main (x -7.15..14.65) and the garage block (x -18.20..-7.15) keep their footprints. `depth` moves the block's street face toward the street by 0–6 units; the slot table, `SWZ1`, the porch anchor, the front walk and the driveway follow the new face. *rev* **Depth clamp**: the porch is 4.6 deep and the curb sits 8 behind today's face, so `normalize` clamps `depth` to `curb − porch depth − 1.0 walk margin` on any face carrying a porch (2 at most with a porch, 6 without) and writes a note. `stories: 2` adds a shell story on the block (walls, cladding, base-less, an upper window row from `ground` entries with `story: 2`, no interior, no zones, no cameras); the block roof sits on top of the upper story. `orientation: side` puts the garage door on the block's outer side face (west; east after mirror) and gives the street face a wall with the bay's window; the driveway turns to meet it.
- *rev* **Where blocks meet.** The two street faces may differ in depth, height and roof form. Rules: the deeper block's side wall is a real wall from the shallower face to the deeper face, in the deeper block's cladding; a one-story block against a two-story block gets its roof clipped by the taller block's wall plane; a hip end facing a neighbouring block is clipped like any other buried roof. No overhang crosses a block boundary. *rev2* **Roofs meet by subtracting the neighbour's BOUNDED volume, never a deck plane.** Deck planes are infinite and the feature buried region (`buriedRegion`) deliberately leaves one axis open; used between blocks that would remove exposed roofing past the neighbour's footprint. The neighbour volume is its footprint (x/z limits, with `depth`) × height from ground to its ridge, plus its overhang on the shared side only; each block's roof mesh is clipped against that convex box and the neighbour's own roof decks INSIDE that box. Shared face (x = -7.15): the face plane belongs to the block whose eave is higher; on a tie, to `main`. Pinned by the roof-line audit on the four combinations (depth diff × story diff) plus hip-against-gable, and a pixel check that no roofing outside the neighbour's footprint is lost.
- **Roof** per block is `{form, ridge, pitch_deg}` (the mechanism shipped in arc 1; `ROOF_FORMS` is now read from the model). *rev* The vault gate: interior partitions vault only under a gable with the ridge on x **and `stories: 1`**; under two stories the ground-floor partitions cap at the story-1 eave (`EXT_TOP4`), never reach into the upper shell.
- **Cladding** per block from six materials; `base` is a band at the block's foot in its own material, height **and its own body colour** (*rev*: photo 2's painted-white brick under coloured batten was ambiguous with one colour). Gable-end infill and roof-feature cladding default to the block's cladding; a roof feature may override with its own `cladding`.
- **Colours** stay palette names. New names in the palette table: `brick_red`, `tan`, `cream_brick`, `stone_grey`, `painted_brick` (body); roof names unchanged. Hex only in the palette table.
- **Street features**: `gable`, `dormer`, `hip_end` as today (*rev*: `hip_end` survives; a saved V1 facade uses it); `shed` = a single-slope roof from the feature's front edge back to the parent deck (a bay window's roof or a shed dormer, with `window` for the dormer case). *rev* **The porch owns its roof**: `porch.roof: flat|gable` replaces the first draft's free-standing `porch_gable` roof feature, so a gabled porch roof can never disagree with the posts under it. Windows gain `shutters` and `story`. All roof features go through the valley clip (buried region) and the mask like the rest.
- *rev* **Overlap per story.** `_resolve_exclusive` runs once per story on the ground layer: a story-2 window never displaces a story-1 window or door, and story-2 entries are dropped with a note when the block has one story. Porches, doors and garage doors are story 1 only.
- **Mirror**: one flag; the contract is §3.4.
- **Unexpressed** is a list of short strings the vision pass saw but the schema cannot hold (arched entry, stone accents beyond the base band, metal roof, a third gable past the cap). It is stored with the draft and shown beside the render. It never affects geometry. *rev* Capped at 8 strings of 80 characters, escaped as text, never rendered as HTML.
- *rev* **Compatibility is a mapping table, not "defaults".** `normalize` upgrades a version-1 facade:

  | V1 | V2 |
  |---|---|
  | `style.cladding: batten` | both blocks `cladding: batten` |
  | `style.cladding: clapboard` | both blocks `cladding: lap` |
  | `style.body` | both blocks `body`; `base: null` |
  | `pitch_deg` (facade-wide) | *rev2* top-level `pitch_deg` (FEATURES only, as today); block `roof.pitch_deg` stays **22.5** on both blocks. Today's block roofs are 22.5° and the canonical features 34.8°; copying the feature pitch into the blocks would change roof geometry and break the pixel pin |
  | `roof[].kind: hip_end` | kept as a roof feature, unchanged |
  | *rev2* `roof[].kind: gable` whose span covers ≥ half a porch's span on the same face | becomes that porch's `roof: gable`; the feature is removed (never both). Overlap under half: feature stays, porch `roof: flat`. A gable covering two porches attaches to the one it overlaps most; tie → the lower slot. Noted per conversion |
  | (absent) | `mirror: false`, `depth: 0`, `stories: 1`, `roof: {gable, x, 22.5}` per block, `shutters: false`, `story: 1`, `porch.roof: flat` where no gable paired |

  Pin: every saved fixture facade (including one with a gable over its porch, one with a partial overlap) and the canonical render pixel-equivalent before and after the upgrade (exterior view, `--day`). The canonical is today's house expressed in the model: main depth 0, one story, gable/x, batten, no base, body white; garage front, gable/x, batten.

## 3. Builders (`chauffeur/static/house.js`)

### 3.1 Materials

- **`cladTex(material, body)`** in the mkTex pipeline returns a world-scaled tile for each of the six materials (batten and lap exist; brick, stone, stucco and shingle are new canvas patterns, no image assets), UV-referenced in world units the way `SIDING_UV_REF` works so seams and phase hold across pieces. The base band is a second box run at the block's foot with its own tile and colour. Palette hex only in the palette table.
- *rev* **Draw honesty**: mergeStatic merges by material, so each distinct (material, body) pair on the house is at least one more static draw. *rev2* It also splits on room tag, shadow flag, visibility and merge root, and small groups stay unmerged, so "+1 per pair" is a floor, not a rule. The budget is the MEASURED per-view draw count from `house_probe --budget`, capped per variant in §7; the per-pair floor is only the explanation the plan expects to see in the delta. Textures never exceed the mkTex cache's per-house ceiling (recorded in §7).

### 3.2 Blocks, stories, side garage

- `FULL_HOUSE`/`GARAGE_BLOCK` derive their street face from `depth`. `storyBox(block)` builds the upper story from `EXT_TOP4` to `2·EXT_TOP4`: walls, cladding, the story-2 windows, registered as fabric (`main_upper_*`, `garage_upper_*`), no room.
- *rev* **The upper story is fabric and is cut like fabric.** The first draft claimed an upper story is never between a room camera and its box; that is false — the kitchen camera sits at y 13.8 and living at 12.8, above an upper story that tops out at 11.2, looking down through it. The upper walls and the raised roof go through `buildRoomShells` and the room mask like every other convex fabric mesh. `ROOM_AABB_EAVE` keeps the story-1 eave (`EXT_TOP4`) as the box top: the mask cuts what stands between the camera and the room, and keeps the rest. The test is the view, not the shell: each room view pixel-checks a marker inside the room from its camera with two stories on both blocks.
- The block roof's eave rises by one story; `deckPlane` reads the block's eave so the valley clip and the roof-line audit follow.
- **Side garage**: `garageDoorAt` builds on the block's outer side face; the street face takes `shellWall` with one window; the drive slab, the car plaques and the `garage_front` marker follow the door.

### 3.3 Roof features

- `shedAt` (single slope, front edge at the feature's eave line, back edge on the parent deck, clipped by the buried region) and the porch gable inside `porchAt` (a small `shellGable` with ridge z on the porch's own footprint, valley-clipped, eave 4.8 kept). Both register like the existing features and take the ROOF_FEATURE drop rule.

### 3.4 Mirror (*rev*: a coordinate contract, not a camera tweak)

- **Where reflection happens**: once, on `houseRoot.scale.x = -1` covering the house, yard, street and cars, applied AFTER `buildRoomShells`, the valley clip, the AO occluder pass and `mergeStatic`. Everything geometric runs in house-local, unmirrored space: masks, `ROOM_AABB`, `ROOM_CAMS` as the mask reads them (`house.js` ~9158), the slot table (west→east internally, unchanged), shell remnants, AO. Nothing in that pipeline may read a flipped value.
- **What flips, and only these**: *rev2* **nothing that constructs geometry**. Construction coordinates (`GARAGE_BLOCK`, `DRIVE_X`, `BAY_X`, the `garage_front` marker, the slot table, plaque anchors) are never touched: the root reflects them once. Only values that cross INTO world space for a camera or navigation calculation pass through one boundary function, `toWorldX(x)` (identity unmirrored, negation mirrored): the live room camera positions and look-ats; the orbit PIVOT x (-1.8 → +1.8) with stop ANGLES unchanged, so the right chevron, `?angle=`, swipe and ← → still turn the same visual way; `frameZone`'s fixed card-face normals (`house.js` ~11217) and lean-in offsets; plaque re-aim's camera-side input. Anything already read from a world matrix (`getWorldPosition`, raycasts, `chfNavProbe`) is NOT passed through it. Pin: with `mirror: true` the garage door, the drive slab and the `garage_front` marker have world x > 0 exactly once (a sign test on `getWorldPosition`), and the mirrored exterior is the pixel mirror of the unmirrored one within the text-plate regions' tolerance.
- **Text reads forward**: every CanvasTexture-on-a-mesh site (there are ~21 `fillText` sites: calendar, clock, dock panels, car plaques, house number, bus STOP arm) is created through ONE helper introduced this arc that tags `userData.noMirror`; build applies a local counter-flip about the mesh's own centre. A pure test greps for `fillText` reachable from a mesh creation that bypasses the helper.
- **Already correct by world matrices**: `chfNavProbe`, taps, raycasts. Three.js flips front-face winding for a negative-determinant world matrix, so lighting and shadows hold.
- **Look items stated, not fixed**: cars and the bus drive on the left when mirrored; the sun rig stays on the same world side (the mirrored house is lit from its other flank). Both acceptable.
- **Tests**: mirrored lean-ins land on the mirrored card (kitchen calendar, garage plaque); house-number plate and a car plaque read forward by pixel; every room marker present and tappable; exterior mesh count equal to unmirrored; room views unobstructed by pixel.

## 4. The photo pipeline (`chauffeur/services/house_facade.py` + the editor)

*rev* The first draft rendered the draft server-side through `tools/house_probe.py`. That does not ship: the add-on image installs neither Playwright nor Chromium on any architecture, the probe boots a second full application with a 50 s boot budget, and `_seed_facade_from_env` writes `save_facade(..., activate=True)` into whichever `CHAUFFEUR_DATA_DIR` it inherits. The pipeline renders in the family's own browser instead.

- **Pass 1, describe.** The system prompt teaches the block model with one worked example ("a garage on the left showing its gable to the street: garage.roof gable ridge z, orientation front; a hip main with two front gables: main.roof hip ridge x plus two roof features of kind gable"). It asks, in order: `mirror` (garage on the RIGHT as seen from the street → true; on the left or unseen → false); per block stories, roof, cladding, base (material, height, colour), body; street features per block with positions as FRACTIONS of that block's street width (0..1) and spans as fractions; colours by nearest palette name; `unexpressed`. Temperature 0.1, strict JSON. The service **validates** (below) then snaps fractions to slots and runs `normalize`. The route returns the pass-1 DRAFT and a `critique_token`.
- *rev2* **Validation is not normalization.** `normalize` accepts anything and manufactures defaults (`_num`/`_pick` fallbacks), so an empty or half revision would come out as a whole house. A new `validate_block_model(obj) -> errors` runs FIRST on every model-produced object: required keys present at every level (`version`, `mirror`, both blocks with every field, `style`, `ground`, `roof`, `unexpressed`), types exact, enums in range, numbers in range, every feature entry complete. Any error rejects the object whole; the pipeline never normalizes a rejected object. Pass 1 rejected → the route returns the error and no draft. Pass 2 rejected → the pass-1 draft is the result with the rejection in the notes. Pure tests feed `{}`, a model missing one block, a feature missing `span`, and an out-of-enum cladding, and assert the original draft is byte-identical afterwards.
- **Render (in the family's browser).** *plan ruling R-A* The facade editor has no 3D preview of its own (it is a 2D slot strip; `/house` builds from the ACTIVE facade the server injects). So the render is `/house` itself: the server keeps the draft under the `critique_token` and `/house?draft=<token>&angle=N&quality=medium&day=1` injects that draft as `window.HOUSE_FACADE` instead of the active facade; the editor opens it in a same-origin iframe at a fixed comparison pose (`day=1` = 14:00 lighting, the street-facing orbit stop nearest the photo's viewpoint, which pass 1 reports as `viewpoint: left|centre|right`) and calls `iframe.contentWindow.chfCapture()`. The same route gives every hand draft a **Preview in 3D** button. *rev2* `preserveDrawingBuffer` is a context-creation flag, not a per-frame switch: `chfCapture` calls `renderer.render()` explicitly and reads `canvas.toDataURL()` synchronously in the same task, on the live context. If the live context cannot do that (a later renderer change), the preview gets its own render target and reads pixels from it. Never re-create the house context with the flag on for one frame.
- *rev2* **Token lifecycle.** `critique_token` is an HMAC over (photo sha256, pass-1 draft sha256, issued-at), expiring 15 minutes after issue. The critique route accepts only a token that verifies and matches the posted draft; an expired or mismatched token is a 4xx and runs nothing. The server keeps the critique result keyed by token for the token's lifetime: a duplicate submission (browser retry, double tap, reload) returns the stored result and never runs a second execution. One token = at most one execution = at most four provider attempts.
- **Pass 2, critique.** Photo + the draft render + the draft JSON. The prompt asks for a ranked list of differences in a fixed order — massing and roof forms, materials and base, openings, colours — at most eight, each with a one-line reason, and returns ONE full revised block model (*rev*: not JSON patches; slot arrays reorder under `normalize`, so index paths land on the wrong feature). The revision is validated, then normalized on a copy; the original draft object is never mutated. The result is `{draft, revised, reasons, unexpressed}`: the editor shows both renders, the person picks either; nothing auto-saves; review-before-save as today. If pass 2 fails, times out or is rejected, the pass-1 draft is the result and the notes say so.
- *rev* **Attempt budget.** `call_pool_json` tries up to `max_models` (default 4) candidates per call, so two stages could make eight provider requests. Updated v2.499.110: both calls use `max_models=10, total_timeout_s=120` under workflow label `house_photo`. Each model gets one attempt; overload responses receive a short cooldown. This reaches later Flash/Lite candidates while retaining explicit request/time limits and request counts in the notes.
- **Routes** are plain `def` (threadpool), never `async def` around a sync model call (the current `house_facade_photo` blocks the event loop for the vision call's 90 s timeout).
- **Dev adapter.** `tools/house_probe.py --facade-json <file> --views exterior --day` stays for fixture comparison on a dev machine only; it must be run with an explicit temp `CHAUFFEUR_DATA_DIR`, and the pure test asserts the live store is untouched after a pipeline run.
- **Model calls** go through `model_pools.call_pool_json('vision', …)` as today; the recorded responses for the two acceptance photos are test fixtures so no test touches the network.

## 5. Hand path (Config → People → Home)

Beside the existing facade editor: a **Blocks** panel with, per block, stories, roof form, ridge direction, pitch, depth, cladding, base material/height/colour, body colour; garage orientation; the house **mirror** toggle. The street-feature editor gains `shed` and a per-feature cladding; the porch entry gains its roof form; windows gain shutters and story. The draft view shows the two renders side by side (draft, revised), the `unexpressed` list and the critique's reasons, with a pick. Saving is unchanged. Nothing a person could do before is removed.

## 6. Tests

- Pure (`tests/test_house_facade.py`): block-model normalize (defaults; the V1 mapping table row by row; depth clamp with and without a porch; story-2 windows dropped with a note when stories is 1; per-story overlap; side garage moves the door and adds the street window; porch roof form travels with the porch); slot table follows depth; fraction→slot snap; critique revision validated on a copy, original untouched; *rev2* `validate_block_model` rejects `{}`, a missing block, an incomplete feature and an out-of-enum value with the draft byte-identical after; V1 pitch stays on features and blocks stay 22.5; gable-over-porch pairing (full, half, under-half, two porches); token verify/expiry/mismatch and duplicate-submission reuse against a stubbed pool (execution count 1); pass-2 failure returns pass 1; attempt budget respected against a stubbed pool; `unexpressed` cap; live store untouched by the dev adapter; caps unchanged.
- Fixtures: the two acceptance photos (`docs/superpowers/specs/assets/`, **committed with the arc**, 2 MB), each with a hand-written EXPECTED block model of what the schema can hold and a RECORDED pass-1 and pass-2 response; the mapping scenario asserts response→spec. *rev* Photo 1 (brick): **mirror false** (garage on the LEFT), garage gable ridge z front, main hip ridge x with two gables, brick with a stone base, unexpressed: arched entry, stone accents. Photo 2 (farmhouse): main two stories gable ridge z, batten with a painted-brick base in its own colour, porch roof gable, shed with window, shutters; unexpressed: metal porch roof, the wing with its ridge along the street; **known structural gap**: the photo's second story is partial, the model makes the whole main block two stories. That gap is recorded as expected, not a fixture failure.
- *rev* **Resemblance gate**, separate from the mapping tests: the wrap renders both fixtures through the pipeline and the user reviews render-vs-photo with the recorded structural gaps beside them (§9). Recorded responses prove the mapping; only eyes prove resemblance.
- Live (`test_house_facade_live.py`, `test_house_shell_live.py`): the §3.4 mirror set; two stories (upper shell registered, every room view unobstructed by pixel, partitions capped, exterior budget delta itemised); side garage (door on the side face, `garage_front` reachable from an orbit stop); shed and porch gable through the roof-line audit; block-meet combinations through the roof-line audit; §0 hip and ridge-z pins; a brick draft's draw count within the per-material rule; *rev* **one combined scenario**: mirrored + two stories on both blocks + max depth + side garage, every marker tappable, every room view unobstructed, budgets held.
- The one full sweep at the arc's last commit; the commit gate is `--focus` plus the touched live files.

## 7. Budgets

*rev* Ceilings set BEFORE the first build, not rebaselined after. *rev2* **One reproducible baseline first**: the arc-1 spec says exterior 1403, the masking report records 1433 under its fixture (orbit at v2.499.56) — two numbers, two setups. The arc's first commit is a baseline run only: `house_probe --budget --day --views exterior,orbit` on a bare server with the canonical facade, at the §0 HEAD, recorded in §9 as `B0` with the command line. Every ceiling below is `B0` plus an itemised delta the plan states per variant (canonical, mirror, two-story, side garage, brick, combined). `buildMs` ≤ 1500 with two stories on both blocks; exterior in-frustum meshes ≤ `B0.meshes` + delta; **per-view draw calls ≤ `B0.draws` + delta, measured, never inferred from material counts**; texture count ≤ `B0.textures` + the six cladding tiles + base tiles. Every number lands in §9 with its ceiling and `B0` beside it.

## 8. Out of scope, stated

Free block placement; interior refit; arched openings; metal roofs; stone accents beyond the base band; a third block; a partial second story; the darker mudroom (a camera pass, its own item); the mudroom's old street door opening into a sealed void (arc 1 deferred it here; ruling: it stays sealed this arc and goes to the parked list with the interior refit). Those the vision pass can see go to `unexpressed`.

## 9. Results

Filled at wrap: the two acceptance photos before/after (canonical draft vs the pipeline's draft and revision, all renders, the recorded structural gaps), the per-variant budgets against their ceilings, the mirror/story/side-garage/combined pins, the request count per photo, deviations with rulings, parked list.

### B0 (Task 1, 2026-09-17)

Recorded at HEAD `c5c4e42` (v2.499.66), bare server, canonical facade, `--seed-rng` for deterministic textures. Command run from `chauffeur/`:

```
env -u HA_BASE_URL python tools/house_probe.py --views exterior,orbit --budget --quality high --day --seed-rng --out ../scratch/b0
```

Exterior row (stop 0):

```
budget exterior  meshes=2286 visible=1433 inFrustum=1433 tris=299285 materials=1450 geometries=1713 buildMs=1090 calls=2819
```

Worst orbit row (highest `inFrustum`, tied at 1433 across stops 0/1/3/4/5/7; stops 2 and 6 came in at `inFrustum=1430`/`tris=298133`/`calls=2813`, everything else unchanged — the far side of the ring drops three roof-ridge meshes out of frustum). Representative worst row (`orbit0`, identical to the exterior since stop 0 *is* the exterior pose):

```
budget orbit0    meshes=2286 visible=1433 inFrustum=1433 tris=299285 materials=1450 geometries=1713 buildMs=1090 calls=2819
```

So **B0 = inFrustum 1433, tris 299285, calls 2819, buildMs 1090, materials 1450, geometries 1713** (meshes 2286, visible 1433, ghostLines 0, ghostDraws 0, mainPassDraws 1433). Every later ceiling in this spec is this row plus the stated per-variant delta. The exterior PNG from this run is `chauffeur/tests/fixtures/house_photo/b0-exterior.png` (Task 5's pixel reference) — confirmed the daytime canonical exterior at stop 0 (Garage/Mudroom/Living room lean-in markers visible, no night rig).

### Per-variant budgets (Task 13, 2026-09-18)

Measured at HEAD `ca94790` (v2.499.90) by `chauffeur/tests/test_house_variants_live.py`, run from `chauffeur/`:

```
env -u HA_BASE_URL python tests/test_house_variants_live.py
```

**Paired, not against the B0 literal.** The probe's scene is seeded but not frozen: the planting's own seed follows the DATE, so the identical canonical house measured `inFrustum 1433 / calls 2819` on the day B0 was captured (2026-09-17) and `1374 / 2699` here. A ceiling written as "B0 + delta" therefore drifts by a handful of meshes every midnight. The scenario instead boots the CANONICAL first — same served app, same browser session, same seeded temp data dir, `THREE_WRAP` routed, `DAY_LOCK_JS` + `SEED_RNG_JS` installed, `?draft=<token>` so the base takes the identical route a variant does — records that row as `base`, and holds every variant against `base + DELTA[variant]`. The B0 row stays in the file as a recorded number; nothing asserts against it.

All six boots, one session, `quality=high`, orbit stop 0 (`BUDGET_JS`):

| boot | inFrustum | calls | tris | buildMs | Δ meshes | Δ calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| base (canonical) | 1374 | 2699 | 293071 | 1137 | 0 | 0 |
| mirror | 1371 | 2693 | 291919 | 955 | −3 | −6 |
| two_story (both blocks) | 1394 | 2739 | 293166 | 1088 | +20 | +40 |
| side_garage | 1377 | 2705 | 291503 | 970 | +3 | +6 |
| brick (brick main + stone base on the garage) | 1379 | 2709 | 293131 | 1081 | +5 | +10 |
| combined (§6 rev2) | 1430 | 2810 | 291151 | 1047 | +56 | +111 |

Ceilings in the file are the measured delta plus 2 meshes / 4 calls of headroom, floored at the base — `mirror` gets `+2/+4` rather than `−1/−2`, because a ceiling that fails when the mirror costs exactly what the base costs is a rule about frustum noise, not about budget: `mirror 2/4, two_story 22/44, side_garage 5/10, brick 7/14, combined 58/115`. `buildMs ≤ 1500` holds on every boot of a quiet machine, worst 1137 (the base itself). Two runs at these numbers were bit-identical in meshes, calls and tris. **buildMs is paired too**: inside `tools/test.py`'s twelve-worker sweep the SAME canonical measured 1885 ms — a number about machine load, not about the build — so the file holds every variant at `max(1500, base.buildMs + 250)`. On a quiet machine that is exactly the spec's 1500; on a loaded one it is "a variant is no slower to build than the canonical is right now". The base's own conformance to 1500 is printed every run, so a real regression in the canonical build still surfaces.

**The combined boot's laws** (its own scenario, its own server — so its absolute counts sit ~127 meshes higher than the table above: `live_app(_seed)` seeds a second pair of cars into the shared temp data dir, which is exactly why the budget scenario runs first): main depth clamped to 2.0 by the porch with the note, garage at 6.0, street garage door replaced by a window, story-2 shuttered window and shed both survive; `chfBlockMeet()` active on **both** blocks (hip main, gable garage, unequal depth and equal stories) with `main_in_garage = 0`, `garage_in_main = 0`, `main_out = 585`, `garage_out = 960`; markers reachable at `{front:'main'}` stop 0, `{piece:'back_door'}` stop 4, `{piece:'garage_block_roof_south'}` stop 0, `{front:'garage_block'}` stop 0; all five rooms entered and settled; kitchen and living both report a non-empty `chfRoomShellCut` including `_upper_` rows. Under `mirror: true` `chfRoomViewClear` returns `null` by the §3.4 ruling (a house-local ray into a world graph would be a confident lie), so the combined scenario asserts the mask's own record instead of the ray.

### Recorded responses (Task 14, 2026-09-18) — PENDING the user's first real run

The two fixture response files per photo (`chauffeur/tests/fixtures/house_photo/brick.pass1.json`, `brick.pass2.json`, `farmhouse.pass1.json`, `farmhouse.pass2.json`) are still the **hand-written** ones Task 11 authored against the prompt, not responses a model actually produced. `storage.get_settings()['llm_gemini_api_key']` in this dev data dir holds a **one-character placeholder**, so there is no key to call the vision pool with; recording against it would have burned a request and returned an auth error. Nothing was overwritten, and `tests/test_house_facade.py` is green on the hand-written pair — which proves the *mapping* (response shape → normalized spec) and not the *model*.

To record for real, with a key in Config → Intelligence (run from `chauffeur/`, `env -u HA_BASE_URL` in front of every line):

```
# pass 1 — one request per photo; keep the returned token
python -c "import base64,json; from services import house_facade as hf; b=base64.b64encode(open('../docs/superpowers/specs/assets/2026-09-17-photo-brick.jpg','rb').read()).decode(); d,n,e,t=hf.from_photo(b,'image/jpeg'); open('../scratch/wrap/brick.draft.json','w').write(json.dumps(d)); print(t, n, e)"

# render that draft, then pass 2 — one more request per photo
python tools/house_probe.py --facade-json ../scratch/wrap/brick.draft.json --views exterior --day --seed-rng --out ../scratch/wrap/brick-draft
python -c "import base64,json; from services import house_facade as hf; p=base64.b64encode(open('../scratch/wrap/brick-draft/exterior.png','rb').read()).decode(); r,e=hf.critique('<TOKEN>',p); print(json.dumps(r,indent=2))"
```

Save the RAW provider payloads over `*.pass1.json` / `*.pass2.json`, re-run `env -u HA_BASE_URL python tests/test_house_facade.py`, and where a mapping assertion breaks **fix `PHOTO_SYSTEM`/`CRITIQUE_SYSTEM`, not the assertion** — the expected models are the user's reading of the photos. Repeat for `-farmhouse.jpg`.

**Request counts per photo: pending.** The budget is fixed in code and is what the count will be measured against: `max_models=10, total_timeout_s=120` on both calls under `workflow='house_photo'` (v2.499.110), so **at most 10 requests per pass and 20 per photo**, with each stage stopping on success or time-budget expiry; and one `critique_token` can only ever run one execution (`DRAFT_TTL_S = 900`, the result cached under the token for its life, so a retry, a double tap or a reload replays the stored result).

### Resemblance review (Task 14, 2026-09-18) — the user's gate

Rendered at HEAD `1472913` (v2.499.92) from `chauffeur/`, orbit stop 0, `--day --seed-rng`, each EXPECTED model through the dev adapter:

```
python tools/house_probe.py --views exterior --day --seed-rng --out ../scratch/wrap/canonical
python tools/house_probe.py --facade-json tests/fixtures/house_photo/brick.expected.json     --views exterior --day --seed-rng --out ../scratch/wrap/brick
python tools/house_probe.py --facade-json tests/fixtures/house_photo/farmhouse.expected.json --views exterior --day --seed-rng --out ../scratch/wrap/farmhouse
```

All three booted clean (`ok: no console errors`). What follows is **what the reviewer saw**, not a rebaseline: no fixture, pin or expected model was changed because of it.

**Photo 1, brick** (`assets/2026-09-17-photo-brick.jpg` vs `scratch/wrap/brick/exterior.png`).

*Matches.* The massing reads: a low, broad **hip** on the main block (form and the 22.5° block pitch both land) with a gable-ended garage block on the LEFT (`mirror: false`, garage `gable` / ridge `z`) — the photo's silhouette, at the photo's handedness. **Brick cladding reads as brick** at the resting distance: a running bond with visible mortar joints, world-scaled so the courses line up across the corner from the front face onto the east face. The **stone base band** is the clearest win — a grey water table 0.9 high wrapping both the front and the return, exactly the cast-stone base the photo has under its brick. Roof colour (`charcoal`), white trim and black window frames match. The single front door at slot 10 sits where the photo's entry sits.

*What the schema cannot hold* (recorded, expected, not a failure): the **arched entry** — the photo's entry is a brick arch over a leaded oval door and the model draws a flat-headed door with a small canopy; and **stone accents beyond the base band** — the photo's cast stone runs up the entry surround and around the right-hand gable's window, and the base band is the only stone the schema owns. Both are in `unexpressed` and were shown, not dropped.

*What looks wrong, and is ours.* (a) The two **gables at slots 8 and 15 render as small eyebrow roofs standing proud of the wall**, roughly a third of the wall's height, casting a hard shadow onto the brick below them — they read as awnings, not as the photo's cross gables, which run from the eave clear to the ridge and carry a whole triangular wall plane. The feature vocabulary (`gable` as a roof feature over a slot span) can express a dormer-scale gable and cannot express a cross gable that is a piece of the block's own roof. That is an **arc-3 (style kits) item, not a defect of this arc's build** — the geometry is doing exactly what a slot-span roof feature says. (b) The `brick_red` body is a **saturated red**; the photo's brick is a variegated sand/tan. The palette gained `brick_red`, `tan` and `cream_brick`; the hand-written expected model picked `brick_red` where the photo wants `tan` / `cream_brick`. A recorded pass-1 run would likely choose better than the hand fixture did — another reason the recording step above matters. (c) The expected model carries **no windows at all** in `ground` (a garage door and a door), so the front elevation is a blank brick wall where the photo has a mullioned window group left of the entry and a large window in the right gable. That is a gap in the hand-written fixture, not in the builder.

**Photo 2, farmhouse** (`assets/2026-09-17-photo-farmhouse.jpg` vs `scratch/wrap/farmhouse/exterior.png`).

*Matches.* Two stories on the main block with the **gable end to the street** (`gable` / ridge `z`) — the photo's centre block, and the tallest thing in the picture in both. **Board-and-batten reads as board-and-batten**: vertical battens at the right spacing, the same white as the photo, holding phase across the corner. The **gabled porch** is the best single match in either render — a gable on two posts over the entry, at the entry's slot, in the proportion of the photo's portico. **Shutters** show as dark leaves either side of the windows on both stories, and the **stacked story-1/story-2 window pair at slot 13** builds as two windows over each other (the case Task 11's ruling made the mapping test compare as full lists, and Task 12's story switch made hand-editable). The **painted-brick base band** is legible on close inspection — a grey brick course about 0.9 high wrapping the foot of every wall, matching the photo's painted-brick water table (the photo's is white and ours grey — a colour call, and the band's own `body` field exists precisely so it can be white).

*What the schema cannot hold*: the **partial second story** — the photo's second story sits over the middle third only, with one-story wings left and right; ours makes the WHOLE main block two stories, which is what turns the render into a barn where the photo is a composed front. This is §8's stated out-of-scope and §6's stated structural gap, and it is the single biggest resemblance cost in either photo. Also the **wing with its ridge along the street** (the photo's right-hand gable is a separate volume; a third block does not exist) and the **metal (standing-seam) porch and bay roofs** (roof material is not in the vocabulary). All three are in `unexpressed`.

*What looks wrong, and is ours.* (a) The **shed feature at slot 14 reads as a box**, not as a shed dormer — at the resting distance its single slope is nearly edge-on and what shows is a small dark block against the roof, easily mistaken for a chimney. It is geometrically right (its high edge dies onto the parent deck, no floating shard) and simply not legible at this distance; worth an eye on device before anything is changed. (b) The gable-end **rake overhang is thin** next to the photo's, so the two-story mass looks flatter and taller than it is. (c) The garage block sits behind the porch at this stop and is barely assessable from the resting view — the photo does not show it either (it is out of frame), so neither side of that comparison means much.

**Verdict.** Both renders are recognisably the photographed house in massing, roof form, cladding, base and handedness; neither is the house. The gap is concentrated in exactly the two things the spec said it would be — a cross gable that is part of the roof (photo 1) and a partial second story (photo 2) — plus one colour call the hand fixture got wrong. **Nothing here was rebaselined**; this section is the record for the user's own device pass.

### Rulings (Task 14 — the ledger, condensed, in order)

Every controller ruling made while the arc was built, with what it costs if the ruling was wrong. Full context in `.superpowers/sdd/2026-09-17-house-blocks-materials/progress.md`.

1. **`BUDGET_JS` is a module constant.** Task 1 exports the budget report JS from `house_probe.py` so Tasks 5 and 13 import it instead of re-typing it. *Costs nothing if wrong.*
2. **Reachability is `chfNavProbe({front:'main'})` / `{front:'garage_block'}` / `{piece:'back_door'}` / `{piece:<alias>}` returning non-null.** The plan's `chfNavProbe({feature:…}).get('hit')` is not the real contract. *Cost: a weaker "on canvas" test than a real tap.*
3. **The garage's WEST wall is always built; only the garage EAST wall (x −7.15) is skipped when `main.stories === 2`.** The plan's `storyBox` guard skipped the wrong face. *Cost if wrong: the garage's own outer wall missing above the ground floor.*
4. **Add `window.chfRoomShellCut(room)`** — the names of fabric rows whose shell for that room is a clipped remnant. The plan's `chfRoomShellShown(room)` returns a name, not `{cut}`. *Cost: none; a hook the tests needed.*
5. **Add `window.chfWorldBox(name)`** — a registered group's `Box3` AFTER the mirror, so the world-x sign test can read its centre. `chfHouseFindFeature` is an action navigator returning a bool. *Cost: none.*
6. **The mirror's pure test is "every `fillText(` sits inside a function named in the `TEXT_PAINTERS` manifest"** (nearest preceding `function <name>(`). The plan's assertion compared a value with itself and asserted nothing. *Cost if wrong: a lettering site could bypass `textMesh` unnoticed.*
7. **`chfNavProbe({piece:…})` resolves through `roofAlias`,** so a ridge-z block's renamed roof pieces still answer to the canonical names. *Cost: one nav test literal breaks on a ridge-z variant.*
8. **The per-task gate stays `--focus` plus the touched live files; the ONE full sweep is Task 14's.** A reviewer's "full sweep owed here" finding was rejected as conflicting with the plan's Global Constraints. *Cost: a cross-file regression surfaces at Task 14 instead of at the task that caused it.*
9. **`page.add_init_script('window.HOUSE_FACADE = …')` does not inject a facade** — `house.html` assigns `HOUSE_FACADE` inline, after init scripts — so **Task 10 was executed immediately after Task 4**, out of plan order, and every later live test injects with `hf.issue_draft(spec)` + `/house?draft=<token>` (the in-process uvicorn shares the token cache). *Cost: none observed; Task 10 only ever needed the V2 model.*
10. **Bridge now, not at review: the porch-gable replay.** With CANONICAL v2 moving the slot-8 gable into `porch.roof`, `buildElevation` replayed it through `gableAt` so the canonical kept its `facade_main_gable_8_*` pieces and the 1874-mesh pin while Tasks 5–8 were built. Retired at Task 8. *Cost: a few lines removed again. Main never stays red across tasks.*
11. **Bridge two: `FSTYLE` derives body/cladding from `spec.blocks.main`** (lap → clapboard) so a SAVED facade did not render white batten between Tasks 4 and 5 — a never-drop-functionality gap. Retired at Task 5. *Cost: as above.* Process note carried into every later dispatch: **run the touched live files BEFORE the first push.**
12. **`main_return` never exists.** The main's street face is already 4.45 deeper than the garage's at depth 0, so `west_skirt` IS the main's return and now runs to `FULL_HOUSE.south`; only `garage_return` is new. *Cost: none; the wall the spec asked for is the wall that was already there.*
13. **The roof-meet gate is IDENTICAL block roof geometry** — depth AND form AND ridge AND pitch AND eave all equal — not differing depth alone (the provisional ruling the review superseded). *Cost: at identical roofs the arc-1 overlap behaviour stays, i.e. roof pieces interpenetrate inside the mass where nothing can see them.*
14. **One rule owns a shared plane: `sharedFaceOwner()`.** With two stories on both blocks and unequal depths, the owner's upper wall spans `max(FULL_HOUSE.south, GARAGE_BLOCK.south)` and the non-owner's wall on that plane is skipped, so x −7.15 can never stand open above the ground floor. Booted at (2,2) + garage depth 6 and the inverse (1,2). *Cost if wrong: a visible gap between the two souths.*
15. **A side garage still offers the Garage entry at the RESTING stop:** for `orientation: 'side'` the exterior Garage hint resolves to `garage_front_wall` (street-facing, room `garage`, visible at stop 0), not to the bay window. The door stays addressable by name and reachable once the ring comes round. *Cost: one hint-resolution branch to revert.*
16. **Per-feature cladding and the side garage's dressed bay window get behavioural pins** (Task 8 fix round), alongside the marker ruling above and the cheap minors (stale comment, mailbox at the L drive's kerb end, third car on the side apron). *Cost: none.*
17. **Budgets are measured PAIRED, in one run, never against the recorded `B0` literal** — the probe's seeded scene varies with the DATE (the seed's hero event and calendar card), so identical trees read 1427/2807 one day and 1433/2819 another. §9 records both figures and the reason. *Cost: none — paired measurement is strictly more honest.*
18. **`/api/house/facades/photo` returns `viewpoint`** (pass 1's `left|centre|right`), which the route had dropped and Task 12's comparison pose needs. *Cost if wrong: the editor cannot pick the orbit stop nearest the photo.*
19. **The fixture mapping test compares FULL normalized `ground`/`roof` lists** sorted by `(slot, story, kind)`, not `{(kind, slot)}` sets — a set collapses the farmhouse's two stacked windows at slot 13 into one and would pass on a model that lost a window. *Cost if wrong: the arc's own stacked-window feature untested.*
20. **The cell editor is story-aware**: an "Editing: story 1 | story 2" segmented control (shown when the slot's block has two stories), `facadeEntry('ground', i, story)` filtering by story, `facadeCellApply` removing only same-story entries, default story 1 — otherwise a stacked pair could not be authored by hand and editing the shared slot silently deleted one. *Cost if wrong: the hand path cannot reach a shape the agent path can.*
21. **`facadeCellSelect` searches BOTH stories and opens on the story that covers the clicked cell** — the fix for a defect the ruling above introduced (a story-2-only span > 1 entry relocated when a continuation cell was clicked). *Cost: an edit lands on the wrong story.*
22. **`buildMs` is pinned as `max(1500, base.buildMs + 250)`, paired like the mesh counts.** The spec's 1500 is a solo-run ceiling; the same canonical measured 1885 ms inside the twelve-worker sweep. The base's own conformance to 1500 is printed every run, so a real regression still surfaces. *Cost if wrong: a genuine build-time regression could hide behind a loaded machine — mitigated by printing the base.*
23. **Task 14 rebuilds Tailwind first.** `test_tailwind_build.py` went red at `ca94790` when the Blocks panel and the story-aware editor changed `config.html` without a rebuild; the sheets ship as their own commit (v2.499.92) ahead of the docs commit. *Cost: none; the staleness check is green again.*

### Deviations from the spec

Each is a place the shipped arc differs from the text above. All are ruled and recorded; none is silent.

- **R-A (render surface).** The spec's "the editor's own preview" does not exist — the facade editor is a 2D slot strip and `/house` builds from the ACTIVE facade the server injects. Realised instead as **`/house?draft=<token>` in a same-origin iframe**: the server holds the draft under the token for 15 minutes and injects it as `window.HOUSE_FACADE`; the editor calls `iframe.contentWindow.chfCapture()`. Side benefit the arc did not plan: every HAND draft now has a **Preview in 3D** button.
- **R-B (depth void).** Moving a street face forward leaves a floor-less void between the room's floor edge and the new wall, so a plain slab in the stoop tone floors it (`*_void_floor`). Not in the spec's block model; without it a room view shows lawn through the floor.
- **R-C (day lock in the page).** `isNight()` reads `Date().getHours()`, so the draft iframe passes **`?day=1`** and `isNight()` honours it. The probe's init-script lock is unchanged.
- **Task order.** Task 10 (draft token + `/house?draft=`) was executed immediately after Task 4 rather than after Task 9, because the plan's live-test injection idiom does not work (ruling 9). **No init-script facade injection survives anywhere in the arc.**
- **`main_return` never exists.** `west_skirt` is the main's return wall, extended to `FULL_HOUSE.south`; only `garage_return` was added (ruling 12).
- **The roof-meet gate is identical roof geometry**, not "the blocks differ in depth" (ruling 13).
- **`chfNavProbe`'s real contract** is `{settled} | {point} | {piece:name} | {front:face}` returning a projection or `null`; the plan's `{feature:…}` → `{hit}` was never real (ruling 2).
- **`chfRoomViewClear` returns `null` under `mirror: true`** rather than raying a house-local camera into a reflected world; the combined scenario asserts the mask's own record (`chfRoomShellCut`) instead.
- **`textMesh` does not call `finish()`.** The counter-flip is applied by the root pass after the reflection (a `REFLECTED` flag lets meshes minted later — `syncGarage`'s car plaques — take the flip at birth), not by a per-mesh finish step as the spec's wording implied. `plate()` / `dockFace` are not in `TEXT_PAINTERS`: wall plates carry no text and house.js has no dock.
- **Three compatibility bridges existed and are all retired**: the porch-gable replay through `gableAt` (Tasks 3+4, gone at Task 8), `FSTYLE` deriving body/cladding from `spec.blocks.main` (Tasks 3+4, gone at Task 5), and the `shell_live` derivation line. `scenario_the_two_v2_bridges_are_declared` outlived them and now asserts their ABSENCE: the scenario is the standing pin that no bridge crept back.
- **The porch's roof pieces are named `facade_main_porch_8_roof_west/east/front`**, not `facade_main_gable_8_*`. The geometry is byte-identical (same eave 4.8, same front edge, same `featureBack` meet, same `PITCH_FAMILY`); only the names moved, and every registered-name pin moved with them.
- **Budgets are paired, per variant, not `B0 + delta` against the recorded literal** (ruling 17), and **`buildMs` is `max(1500, base + 250)`** (ruling 22).
- **The mudroom's old street door still opens into a sealed void** — §8 said it stays sealed this arc; it does, and it is on the parked list below.

### Parked

Nothing here blocks the arc. **Look items** are things only the user's eyes on a real device can settle; the rest are deferred minors from the ledger (`.superpowers/sdd/2026-09-17-house-blocks-materials/deferred.txt`).

**Look items — for the user, on device.**

- **Mirrored traffic drives on the left.** The road is mirrored with the house, so the cars and the bus keep the right-hand side of a reflected road. Stated in §3.4 as acceptable; worth one look.
- **Mirrored lighting comes from the other flank.** The sun rig keeps its WORLD side, so a mirrored house is lit from the opposite side to an unmirrored one. Also §3.4, also acceptable, also worth a look.
- **`garage.depth > 0` is geometrically legal and visually unfinished.** One item, three faces of it: the garage ROOM does not follow its block (the street face moves forward and the room behind it does not, leaving a deep recess), the bay piers stand proud of the garage room's walls at depth 6, and `garage_void_floor` overlaps the apron's near 0.5 (R-B's slab against the drive). Nothing here is a crash or a wrong number — it is a depth the model allows and the massing has not caught up with. One look settles how far arc 3 has to go.
- **A side garage's door opens onto the garage room's own west wall** (`gWallW`, 0.12 behind it) — the door reads right from outside but is not a through-route into the bay. The same relationship the street door has always had to `garageBackWall`; a massing question, not a facade one.
- **The sealed upper story.** With `stories: 2` the story-2 windows are lit panes over an empty volume — no interior, no zones, no cameras, by design (§2). At night a lit pane over nothing may read wrong.
- **The mudroom's street door still opens into a sealed void** (arc 1 deferred it here; §8 ruled it stays sealed).
- **Depth-6 yard.** The garage-side bed, shrubs and pots move with the block, but F3's garage-side yard move has no `depth > 0` assertion (the ground there is unregistered), so a depth-6 screenshot is the only check.
- **A side garage's garage-room view is never exercised** (the bay face is a solid wall now).

**Deferred minors.**

- `house_probe` imports `SEED_RNG_JS` inside the flag branch rather than at module top.
- `roof_piece_names` ignores `form` (plan-mandated signature); `VERTEX_AUDIT_ALL_JS` computes an unread `proudAtWall` with a different meaning; `yAt` divides by `n[1]` unguarded; `hintChoices` tests `h[3]` twice.
- `active_bundle()` / `house_facades_api` hand out the canonical `slot_table()` beside a spec that carries depth and stories.
- `slot_table` calls `float()` on a garbage depth; `{}` means canonical; `_norm_block` notes unused; the depth clamp runs after the slots are derived; a side-garage window may lose to `_resolve_exclusive`; batten→batten and non-tie overlap rows unpinned; an unreachable already-gabled branch; `validate_block_model`'s docstring claims a caller it only gained at Task 11.
- Draft cache: the HMAC branch is unreachable via the dict lookup (the test proves the lookup, not the HMAC); the scenario name promises a dedupe it does not itself test; `chfCapture` bypasses any composer (none known).
- Materials: `EXTC.garage` is dead; five exterior skins still spell `EXTC.siding` / `CLAD()` instead of `cladColour` / `CLAD(b)`; a partial-blocks payload throws at `ROOF_FORMS`; non-canonical claddings get no PBR normal map and both lap and batten tiles build regardless; the `_js_object` parser is narrow by design.
- Depth and meet: coplanar north decks z-fight at equal depths (pre-existing); a wholly-clipped facade feature registers an empty `+Infinity` box row (`fabBox` should refuse it); the garage east gable infill is removed whole at unequal depths; `garage_return`, centred on the shared plane, leaves a 0.175 step against `west_skirt`; `isBlockRoof`'s literal duplicates the `wantsVerts` prefix.
- Stories: two false comments (~6216, ~6344); `stories` has no `|| 1` default unlike `depth`; `chfRoomViewClear`'s single ray is trivially clear when no upper piece is in view; `null` from `chfFabricVertices` surfaces as a JS `TypeError`.
- Side garage: the side apron has no saw-cuts, centre line or edging; the deck `+0.09` comment overstates; a braceless multi-line `if` at ~13096; `featClad` called twice; a 0.1 sliver beside the side leaf (z 5.80..5.90).
- Mirror: a redundant `.clone()` after `toWorld`; `get EXT_AT()` now returns a copy (a silent semantic change).
- Pipeline: RED was narrated rather than shown for the replaced scenarios.
- Editor: `facadeCellApply` spreads the whole cell object regardless of kind (stray keys; a pre-existing pattern); clicking an already-selected cell whose only change is the story does not re-run `facadeLoadCell` (the segmented control covers it).

### Security judgement

`/house?draft=<token>` is **ANYONE-tier by design, and that is the right tier**. The token is a 128-bit HMAC over (photo sha256, spec sha256, issued-at) with a 15-minute TTL, unguessable and unforgeable; the response carries the facade SPEC only and never the photo the draft came from; and the content is house geometry — slots, claddings, colours — not household data. A bearer URL is acceptable for that, and the alternative (a session on the iframe) would have cost the render path its whole reason for existing. Whoever holds the link sees a drawing of a house for fifteen minutes.

### Final review wave (v2.499.94)

One commit after the whole-branch review. Ten findings, all fixed, each with a pure pin in `tests/test_house_facade.py`:

- **`list_facades()` normalizes every saved row on read** (critical). Pre-arc facades are V1 rows with no `blocks`, `active_bundle()` was fixed at Task 10 and its sibling was not, so the Blocks panel threw on every facade saved before this arc. The editor also refuses to bind a blocks-less spec: it runs it through `normalize` first.
- **`critique()` is single-flight** (important). The replay check was check-then-act; two requests on one token both paid for a vision call — six provider requests against §4's ceiling of four. A module lock now guards the read-and-mark, the first caller marks the entry in flight, and a second gets HTTP **409** (`Still comparing — one moment`). Both model buttons are disarmed while one runs.
- **An unseen garage is a plain default block** (important). The prompt invited omitting it and `validate_block_model` required it — the honest answer was rejected whole. `from_photo` fills an absent or null `blocks.garage` with the default block and says so in the notes; the prompt now asks for a plain default block and never an omission. Same class: `_snap_fractions` names an unknown `block` instead of dropping it silently onto the main face.
- **The draft cache is bounded** (important). `DRAFT_MAX = 8`, oldest evicted first — the entries hold photo bytes for fifteen minutes on a Pi.
- **The request count in the notes is real** (important). §4 claimed it; nothing implemented it. `call_pool_json(..., attempts=[])` records every model it actually sends a request to, both passes write `"N model request(s): …"` into their own notes, `critique` reports a measured `attempts` (it was hard-coded 1) and the token's `requests_total` across both passes.
- **Minors.** The spec sentence about `scenario_the_two_v2_bridges_are_declared` (above); `facadeCellClass` colours a story-2-only slot; `BUS_BODY.noMirror` → `sideMirrors: false`, so the vehicle param no longer shares a name with the `userData.noMirror` text contract; shed windows spend the `MAX_WINDOWS` budget as dormer windows always did; an expired `?draft=` preview is named out loud instead of quietly showing the active house.

**Sweep decision.** `test.py` keeps a `HEAVY` set — `test_house_facade_live`, `test_house_shell_live`, `test_house_variants_live`, `test_house_nav_live` — on a dedicated single-worker lane that runs alongside the ordinary fan-out. The files each boot a real browser and drive a full 3D scene; twelve-wide they starved each other into timeouts and solo they always passed. One command, one report, no timeouts.

**Retired concern.** `chfMirror().fabricDet` measuring −2.43e−05 mirrored (task 9) is **not** a thin pin. The quantifier direction is correct: `fabricDet` is a max over non-`noMirror` meshes, so a mesh that failed to mirror would push the max POSITIVE, not toward zero. A near-zero magnitude is a near-degenerate mesh winning the max, not a weak assertion — the sign is the whole claim and a missed mesh flips it.

### Arc 2, as shipped

**v2.499.67 – v2.499.93, 2026-09-17/18.** Fourteen tasks: the B0 baseline and measured draw calls; the §0 prerequisites; the V2 schema with `validate_block_model` ahead of `normalize` and the V1 mapping table; the six claddings, base bands and the pixel pin; per-block depth with the block-meet return wall, the void floor and neighbour-volume roof subtraction; stories as cut fabric; the side-entry garage, the shed and the porch's own gable; the mirror; the draft token and `/house?draft=`; the two-pass photo pipeline; the Blocks panel and the story-aware cell editor; the per-variant paired budgets; and this wrap. **NOT device-verified** — everything above was measured in a probe or a Playwright boot, never on the wall panel or the add-on. Next in sequence: **arc 3, style kits** (spec not written).

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
- *rev* **Attempt budget.** `call_pool_json` tries up to `max_models` (default 4) candidates per call, so two stages could make eight provider requests. Both calls run with `max_models=2` under workflow label `house_photo`, and the pipeline records its request count in the notes. The earlier quota incident is why.
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

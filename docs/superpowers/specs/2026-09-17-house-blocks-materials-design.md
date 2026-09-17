# The Home — blocks, materials and the photo pipeline (massing arc 2 of 3)

Binding spec, user-ratified 2026-09-17. Second of the three massing specs: 1. the regular house + orbit (shipped v2.499.31–.40) → **2. blocks, materials, roof forms, the photo pipeline** (this document) → 3. style kits. Every prior house law travels with it: batching, the lifecycle law (mkTex owns textures; cgeo owns geometry), the shell registry, view-volume masking and the roof valleys (`2026-09-16-house-view-volume-masking-design.md`), and the facade generator (`2026-09-15-house-facade-generator-design.md`: slots, spans, palette names, saved facades, review-before-save).

Spelling: **story / stories** throughout the spec, the code and the UI.

## 1. Why

Two photos the user handed over read as "a different house in the right places": a brick house with a side-gabled garage beside a hip-roofed main block carrying two front gables; and a farmhouse with a two-story front-gabled centre, a side-gabled wing, a gabled porch, a shed-roofed bay and a garage out of frame. The facade generator cannot express any of that. Its vision prompt describes an 18-slot strip; its vocabulary has two claddings and no roof form, ridge direction, story count, base band or shed; and the one pass is never checked against the photo. The mismatch is silent.

This arc gives the house a **block model** that the builders, the vision prompt, the editor and (next arc) the style kits all read; a real materials vocabulary; a horizontal **mirror** so a garage on the right is one flag; a **describe-then-critique** photo pipeline that renders its own draft and compares; and an **unexpressed** list so what the schema cannot hold is shown, never dropped.

Ruled out (user, 2026-09-17): free block placement. The two blocks keep their footprints and the rooms keep their world coordinates; the mirror covers the most common asymmetry at a fraction of the cost.

## 2. The block model

```
house: {
  version: 2,
  mirror: false,
  blocks: {
    main:   { depth: 0..6, stories: 1|2, roof: { form: gable|hip, ridge: x|z, pitch_deg: 22.5..35 },
              cladding: batten|lap|brick|stone|stucco|shingle, base: { material, height: 0.6..1.8 } | null,
              body: <palette name> },
    garage: { same fields, plus orientation: front|side }
  },
  style: { roof: <palette>, frame: <palette>, door: <palette>, trim: <palette> },
  ground: [ window { slot, span, size, shutters: bool, story: 1|2 } | door | garage_door | porch ],
  roof:   [ { slot, span, kind: gable|dormer|shed|porch_gable, window: bool, cladding?: <material> } ],
  unexpressed: [ string ]
}
```

- **Blocks**: the main (x -7.15..14.65) and the garage block (x -18.20..-7.15) keep their footprints. `depth` moves the block's street face toward the street by 0–6 units; the slot table, `SWZ1`, the porch anchor, the front walk and the driveway follow the new face. `stories: 2` adds a shell story on the block (walls, cladding, base-less, an upper window row from `ground` entries with `story: 2`, no interior, no zones, no cameras); the block roof sits on top of the upper story. `orientation: side` puts the garage door on the block's outer side face (west; east after mirror) and gives the street face a wall with the bay's window; the driveway turns to meet it.
- **Roof** per block is `{form, ridge, pitch_deg}` (the mechanism shipped in arc 1; `ROOF_FORMS` is now read from the model). The vault gate stays: interior partitions vault only under a gable with the ridge on x.
- **Cladding** per block from six materials; `base` is a band at the block's foot in its own material and height (photo 2's painted brick under batten; the stone water table under brick). Gable-end infill and roof-feature cladding default to the block's cladding; a roof feature may override with its own `cladding`.
- **Colours** stay palette names. New names in the palette table: `brick_red`, `tan`, `cream_brick`, `stone_grey`, `painted_brick` (body); roof names unchanged. Hex only in the palette table.
- **Street features**: `gable`, `dormer` as today; `shed` = a single-slope roof from the feature's front edge back to the parent deck (a bay window's roof or a shed dormer, with `window` for the dormer case); `porch_gable` = the porch's roof form (gable instead of the flat overhang). Windows gain `shutters` and `story`. All roof features go through the valley clip (buried region) and the mask like the rest.
- **Mirror**: `scale.x = -1` on the house root; every camera constant flips x when mirrored (getters); text-bearing meshes carry `userData.noMirror` and get a local counter-flip at build so lettering reads forward; the slot table is unchanged internally (west→east); the vision prompt reports left-to-right as seen from the street and the mirror flag maps it.
- **Unexpressed** is a list of short strings the vision pass saw but the schema cannot hold (arched entry, stone accents beyond the base band, metal roof, a third gable past the cap). It is stored with the draft and shown beside the render. It never affects geometry.
- **Compatibility**: saved facades are this object. `normalize` upgrades a version-1 facade with block defaults (canonical blocks, mirror false, no base, one story, shutters false, story 1) so nothing a person saved is lost. The canonical is today's house expressed in the model: main depth 0, one story, gable/x, batten, no base, body white; garage front, gable/x, batten.

## 3. Builders (`chauffeur/static/house.js`)

- **`cladTex(material, body)`** in the mkTex pipeline returns a world-scaled tile for each of the six materials (batten and lap exist; brick, stone, stucco and shingle are new canvas patterns, no image assets), UV-referenced in world units the way `SIDING_UV_REF` works so seams and phase hold across pieces. The base band is a second box run at the block's foot with its own tile. Palette hex only in the palette table.
- **Block geometry**: `FULL_HOUSE`/`GARAGE_BLOCK` derive their street face from `depth`. `storyBox(block)` builds the upper story from `EXT_TOP4` to `2·EXT_TOP4`: walls, cladding, the story-2 windows, registered as fabric (`main_upper_*`, `garage_upper_*`), no room (the mask keeps them in every room view: an upper story is never between a room camera and its eave-high box). The block roof's eave rises by one story; `deckPlane` reads the block's eave so the valley clip, the vault and the mask follow.
- **Side garage**: `garageDoorAt` builds on the block's outer side face; the street face takes `shellWall` with one window; the drive slab, the car plaques and the `garage_front` marker follow the door.
- **Roof features**: `shedAt` (single slope, front edge at the feature's eave line, back edge on the parent deck, clipped by the buried region) and `porch_gable` inside `porchAt` (a small `shellGable` with ridge z on the porch's footprint, valley-clipped). Both register like the existing features and take the ROOF_FEATURE drop rule.
- **Mirror**: one `houseRoot.scale.x = -1` covering the house, yard, street and cars; camera constants become getters that flip x; `chfNavProbe` and taps already use world matrices; `noMirror` counter-flip for text meshes (plates, calendar, clock, house number, signs — tag at build via a `text()`/`plate()` helper argument, not a hand list).

## 4. The photo pipeline (`chauffeur/services/house_facade.py`)

- **Pass 1, describe.** The system prompt teaches the block model with one worked example ("a side-gabled garage on the left, gable end to the street: garage.roof gable ridge z, orientation front; a hip main with two front gables: main.roof hip ridge x plus two roof features of kind gable"). It asks, in order: `mirror` (garage on the RIGHT as seen from the street → true); per block stories, roof, cladding, base, body; street features per block with positions as FRACTIONS of that block's street width (0..1) and spans as fractions; colours by nearest palette name; `unexpressed`. Temperature 0.1, strict JSON. The service snaps fractions to slots and runs `normalize`.
- **Render.** `render_facade(spec) -> png` calls `tools/house_probe.py --facade-json <file> --views exterior --quality medium` as a subprocess (the same headless Chromium the tests use, ~5 s). Where Chromium is unavailable (the Pi add-on) the pipeline degrades to pass 1 only and the notes say so.
- **Pass 2, critique.** Photo + draft render + the draft JSON. The prompt asks for a ranked list of differences in a fixed order — massing and roof forms, materials and base, openings, colours — each as a JSON patch against the block model with a one-line reason, at most eight. Patches apply through `normalize`; one more render; the result is the DRAFT with `unexpressed` and the critique reasons attached. Two vision calls and two renders per photo; no auto-save; review-before-save as today.
- **Model calls** go through `model_pools.call_pool_json('vision', …)` as today; the recorded responses for the two acceptance photos are test fixtures so no test touches the network.

## 5. Hand path (Config → Home)

Beside the existing facade editor: a **Blocks** panel with, per block, stories, roof form, ridge direction, pitch, depth, cladding, base material and height, body colour; garage orientation; the house **mirror** toggle. The street-feature editor gains `shed` and `porch_gable` and a per-feature cladding; windows gain shutters and story. The draft view shows the render, the `unexpressed` list and the critique's reasons. Saving is unchanged. Nothing a person could do before is removed.

## 6. Tests

- Pure (`tests/test_house_facade.py`): block-model normalize (defaults; version-1 upgrade; depth clamped 0–6; story-2 windows dropped with a note when stories is 1; side garage moves the door and adds the street window); slot table follows depth; fraction→slot snap; critique patches apply idempotently; caps unchanged.
- Fixtures: the two acceptance photos (`docs/superpowers/specs/assets/`), each with a hand-written EXPECTED block model of what the schema can hold (photo 1: mirror true, garage gable ridge z front, main hip ridge x with two gables, brick with a stone base, unexpressed: arched entry, stone accents; photo 2: main two stories gable ridge z, batten with a painted-brick base, porch_gable, shed with window, shutters, unexpressed: metal porch roof, side-gabled left wing) and a RECORDED pass-1 and pass-2 response; the mapping scenario asserts response→spec.
- Live (`tests/test_house_facade_live.py` and `test_house_shell_live.py`): mirror (every room marker present and tappable when mirrored; the house-number plate reads forward by pixel check; the exterior mesh count equal to unmirrored); story 2 (upper shell registered, kept in every room view, exterior budget delta itemised); side garage (door on the side face, `garage_front` marker reachable from an orbit stop); shed and porch_gable through the roof-line audit; a brick draft renders with the same draw count as batten.
- The one full sweep at the arc's last commit; the commit gate is `--focus` plus the touched live files.

## 7. Budgets

`buildMs` ≤ 1500 with two stories on both blocks; exterior in-frustum re-baselined per variant (canonical, mirror, two-story, side garage, brick) and recorded; materials add textures, never draws.

## 8. Out of scope, stated

Free block placement; interior refit; arched openings; metal roofs; stone accents beyond the base band; a third block; the darker mudroom (a camera pass, its own item). These go to `unexpressed` where the vision pass sees them.

## 9. Results

Filled at wrap: the two acceptance photos before/after (canonical draft vs the pipeline's draft, both renders), the per-variant budgets, the mirror/story/side-garage pins, deviations with rulings, parked list.

# Exterior layers and fireplace motion

Fork: `feature/living-room-atmosphere`. Version: 2.499.181.

Subsequent review: the user accepted the fire as the baseline, then requested
the kitchen. The following hold notes describe the earlier fire-review stage;
the [kitchen prototype](2026-09-24-house-kitchen.md) is now implemented separately.

## Current prototype

- Blue 2021 Nissan Murano generated inside the immutable exterior photograph
  with Gemini 3.1 Flash Image. A manually reviewed, feathered polygon retains
  the vehicle, contact shadow and local driveway. The WebP has actual alpha.
  The layer uses the **original generated coordinates**, without translation,
  rotation, or independent scaling. Both base and overlay share the cover crop.
- Vehicle preview can independently show/hide the patch. `driveway_car=<id>`
  explicitly binds its visibility to an existing fleet ID; no name matching or
  parking inference. `traffic_demo=1` previews the artwork without changing
  fleet data. This fixture depicts a Murano, not arbitrary household vehicles.
- The fireplace now has static, detailed oak logs in both room backgrounds.
  A flame-only Blender Mantaflow simulation plays above them as a transparent
  400x480 VP9 loop: four seconds, 24 fps. Projection uses source coordinates
  (508,294), size 200x240, matching the native render aspect ratio. Three
  registered log meshes emit fuel from their exposed surfaces, with moving
  ignition textures, inactive bark patches and independently pulsing fuel.
  Collision cores and matching holdout meshes let flames rise around the
  wood while preserving visible log faces. A lower burn rate and stronger
  buoyancy produce taller flames. The photograph stays fixed; no assets
  were purchased.
- Native playback starts only in the visible room overview and stops for
  reduced motion, hidden tabs, object views, exterior navigation or the toggle.
  Failed media leaves the unlit logs. No scene deformation or runtime fluid
  simulation. Source: `chauffeur/tools/render_fire_simulation.py`; asset details
  and image-edit prompts: `chauffeur/static/house_hybrid/fireplace-assets.md`.
- Earlier strip warping, procedural flames, opaque stock-footage composite,
  keyed footage and segmented footage were rejected. They are not the active
  effect. Initial Blender shading also looked like orange smoke and was
  rejected. Four ellipsoid sources were subsequently rejected because fire
  appeared to originate from four balls rather than the log surfaces.
  The current material maps burning-fuel values to opacity and an
  emissive red/orange/yellow/white gradient. Appearance remains for user review.

## Bus failure and rejected work

Five paid image calls total: one car and four bus attempts, no transport retries.
The first bus was too close to/straddling the curb. A more explicit prompt still
placed it too close. A manually translated extraction was tried and rejected:
moving scene-conditioned artwork violates its lighting/ground relationship.
It is **not shipped**. A visual guide was ignored and guide dots appeared in
the output. A final photographic edit failed to move the bus meaningfully.

The old bus atlas and placement are retained unchanged. The generated bus
replacement is unresolved. No generated bus patch is referenced by the page.
Do not claim this experiment solved reliable placement or transparent output:
all returned images were opaque; alpha was constructed locally after review.
The run prompts and usage are recorded in `assets/exterior-layers-2026-09-24`.

## Product boundary

This is an opt-in comparison, not the household image-generation service.
Production needs persisted parking assignments, generated-asset identity,
automatic segmentation/placement validation and failure handling. Separate
lighting conditions need separately validated artwork. Presence changes only
swap cached layers and never invoke Gemini. Masks are specific to one result.

Kitchen stays on hold until the fire preview is accepted: establish its overview and deliberate lean-ins,
with screen/control surfaces and bounded steam regions planned into the image.
Kitchen art, steam and interactive appliances are not included in this slice.

## Verification

The exterior browser regression covers marker quick views/hold navigation,
history, mobile, independent previews, explicitly bound vehicle presence,
fire motion enable/disable, reduced motion, night image selection, and stopping
the effect in object views/exterior. Screenshots are in the local ignored
`scratch/exterior-layer-regression` directory. Generation reports preserve
usage rather than estimating a billed dollar amount.

## Follow-up review

- Car patch reviewed at 390x844, 1400x1000 and 2560x1080. Its 1264x848 RGBA
  source matches the exterior image dimensions; cover scale and bottom/center
  alignment are asserted in the browser. Edges/contact shadow blend with the
  driveway. The phone crop cuts off part of the car along with that part of the
  original scene; the Vehicles shortcut remains available. Artwork unchanged.
- `test_house_flames_live.py` checks decoded video pixels and transparency,
  distinct changing contours and colors in day/night playback, lazy loading,
  loop wrap, projection at three sizes, toggle, reduced motion, visibility,
  object/exterior stops, resume, failed media and native frame cadence.
  Artifacts: `scratch/log-surface-fire-final-review`. All 120 native RGBA frames
  have fully transparent outer rows/columns. Log edits change only pixels
  inside (521,427)-(699,513) relative to each empty background. These checks
  establish behavior and isolation, not user acceptance of the appearance.
- Fire motion sits below the mobile toolbar so it cannot wrap the toolbar over
  the Living room return button. The exterior regression exercises this path.
- Kitchen, steam and weather remain on hold; no changes to them in this review.

## Log surface simulation revision

The three log proxies follow measured endpoints in the static photograph.
Each has a weighted bark emitter, inset fluid collision core and render-visible
holdout twin. There are no sphere emitters. About a quarter of the upper bark
vertices are inactive, with animated procedural textures adding moving gaps.
Fuel pulses have different phases on each log. Burn rate 0.36 and temperature
limits 2/3.5 replace 0.85 and 1.3/2.4 in the first surface-emission bake.

All 120 final RGBA frames have distinct alpha contours and zero alpha at their
outer borders. Flame tips range from source y390 to y417.5 (median y405), above
the crossed log near y452. The holdout-only render is entirely transparent;
at review frame 80 the holdouts remove 19.9% of unmasked alpha coverage. The
encoded 400x480, 24 fps, four-second VP9 alpha file is 1,185,814 bytes.
Editable scene, cache and pixel verification: `scratch/log-surface-fire-varied`.
Both `test_house_flames_live.py` and `test_house_exterior_live.py` pass with
this asset. Browser sampling found eight distinct contours in each lighting
condition and 23.9 fps playback. Clean day/night recordings are in
`scratch/log-surface-fire-final-review/fireplace-preview.mp4` and
`fireplace-closeup.mp4`. Visual acceptance remains with the user.

The smooth-loop revision uses `chauffeur/tools/encode_fire_loop.py`: a one-second
smoothstep overlap blends premultiplied color and alpha, then restores straight
alpha for VP9. The final-to-first join is two consecutive original frames.
Before compression its mean coverage-weighted difference is 0.00483 versus
0.00546 for a typical frame change. The focused browser regression was rerun
for this export; artifacts are in `scratch/log-surface-fire-loop-review`.

## Transparent asset review after rejection

This historical search preceded the Blender implementation. The user ruled
out purchasing except as a last resort, and requested an original simulation.

- Downloaded Mikodrak's CC0 Fire FX sequence from
  https://opengameart.org/content/fire-fx-burning-fire-animation . The archive
  contains two 40-frame RGBA layers, each 81x123. Confirmed transparent corners
  and fractional alpha. Previewed the front sequence over light and dark colors
  in `scratch/fire-asset-review/free-fire-review.mp4`; too coarse for the desired
  photographic appearance. It remains a scratch evaluation only.
- Candidate: Michal Barczyk's Camp Fire, looped flipbook with five view angles:
  https://www.artstation.com/marketplace/p/rr3rv/camp-fire-looped-flipbook-animation-sheet-5-view-angles .
  Listing states 64 frames, 512px per frame, separate base color/transparency,
  alpha, emissive and motion-vector textures; $4 extended commercial license
  listed on September 24, 2026. Promotional images inspected; source alpha and
  temporal seam not yet verified because the downloadable assets are paid.
- Alternative: same creator's Fireplace Flame, three view angles:
  https://www.artstation.com/marketplace/p/njyYW/fireplace-flame-flipbook-sequence-animation-sheets-3-view-angles .
  Listing supplies 64-frame transparent sequences and emissive channel. Its
  description contains an inconsistent explosion reference; verify the actual
  fire sequence and seamless loop before selecting it.

The selected route is an original fluid simulation baked offline to RGBA.
The listed paid assets were not purchased or installed. At this fixed
camera, begin with simple flipbook playback; add particle emitters only if
needed for the hearth's coverage. Check fine edges over light/dark backgrounds,
then scale, perspective, occlusion and the loop seam in the empty firebox.
Kitchen remains on hold.

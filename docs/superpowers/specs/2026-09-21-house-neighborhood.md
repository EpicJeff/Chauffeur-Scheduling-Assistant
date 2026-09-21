# First neighborhood street scene

Implements the deferred neighborhood arc from the batching/facade specifications.
Version 2.499.142. Scope is an exterior street scene around the household's house.

## Design

Five fixed, deterministic lots flank the active house and face it across the street.
Their valid facade-v3 specs vary body/roof colors, wall finishes, mirrored garages,
one/two stories, roof forms/directions, porches and opening groups. Generation is
local and repeatable: no model, address, map service or household data is involved.

`house_neighborhood.js` separates plan generation, a reusable lightweight exterior
projection, and instanced scene construction. It takes the existing renderer's block
envelopes, palette and material factory. The active home's detailed exterior and
interiors remain on their existing build path. This is not a replacement renderer
for all facade features: neighbors use closed low-detail solids, simple windows and
roof forms, without shell clipping, detailed textures, interiors or interaction.

The street/sidewalk continues beyond the active parcel. Each neighbor has a lawn,
driveway, path and simple trees. Neighbor buildings are rendered at 80% scale to
keep the household home visually dominant; lots and street remain at scene scale.
The sky dome and camera far plane expand only in the normal home scene.

## Navigation and lifecycle

The neighborhood is outside `houseRoot`, so mirroring the active home does not move
the street. All its geometry is marked inert yard scenery. Room views hide it;
the existing frame loop updates visibility without adding an animation loop.
Lots whose centers lie within a 24-unit camera-to-house corridor are hidden as a
whole to keep the active home clear. This can make foreground lots appear/disappear
while orbiting; continuous fades and neighborhood exploration are future work.

Photo/editor captures (`editor=1`) omit the neighborhood and retain the old camera
far plane/sky size. No neighbors can enter the photo review's reference render.

Instances share five geometry batches and one material. No neighbor lights or shadow
casters are added. A disposer releases instance buffers, geometries and material;
context-loss fallback calls it before dropping the WebGL scene. Read-only
`chfNeighborhood()` exposes placement, visibility and budget diagnostics.

## Acceptance

- Generated facade specs validate; repeated generation is identical and leaves the
  canonical spec untouched.
- The geometry budget is 429 instances / 5,094 triangles, independent of household
  state. Initial browser measurement: ten additional draw calls on high, five on low.
- Chromium checks high/low tiers, all eight orbit stops, room entry/exit, a real room
  marker click, and photo/editor isolation; desktop and narrow-screen screenshots inspected.
- Pure builder tests cover foreground visibility and resource disposal.
- Existing facade validation/storage scenarios pass.

Device-level Raspberry Pi frame-time testing remains outstanding. Draw-call/triangle
measurements establish the added geometry cost, not a frame-rate guarantee.
Neighbor interiors, saved neighbor editing, roaming cameras and map-derived parcels
are outside this first slice.

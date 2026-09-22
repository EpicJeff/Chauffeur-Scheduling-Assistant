# Map-derived neighborhood streets

The house page uses the configured home location and existing Mapbox key to
replace the generated street grid with surrounding road geometry. House designs
remain illustrative: eight nearest accepted lots use the detailed parametric
renderer, farther lots use the lightweight renderer, and the painted horizon
remains. Mapping does not alter the user's facade or room navigation.

## Data and lifecycle

`services/house_map.py` reuses the existing geocoder and its precision metadata.
Only exact geocodes are eligible. A nearest street too close to the pin, too far
away, or requiring extreme scaling is rejected rather than inventing frontage.
The existing Mapbox disable switch and usage accounting apply.

One lookup fetches up to four latitude-adjusted road tiles and nine zoom-16
building tiles (thirteen total), sequentially,
with connect/read timeouts of 3/5 seconds. It includes ordinary surface streets;
motorways, service alleys, tunnels and bridges are not residential frontage.
Mapbox `road` geometry and full `building` polygon outlines are decoded with
`mapbox-vector-tile`. No Directions, Matrix, imagery, or LLM calls are made.
The dependency's Python 3.11/aarch64 binary wheels were checked; a container build
and hardware frame times were not exercised.

The local `house_map.json` cache lives beside the database. It stores a hashed
home/key identity and projected scene geometry, not the address or token. A
successful result lasts twelve hours; failures have a one-hour cooldown. A lock
coalesces simultaneous clients, and atomic replacement prevents partial reads.
The HTML path only reads the cache and never waits for that lock or a provider.
An uncached first visit uses the generated neighborhood while the endpoint loads
the map, then replaces and disposes that scenery once. Subsequent visits embed
the cached geometry and build only once. Editor/photo pages perform no lookup.
Missing settings, inadequate geometry and provider failures retain the generated
neighborhood. `chfNeighborhood()` reports `layoutSource` and `roadSegments`.

## Deterministic projection

Convert tile coordinates into local east/south meters, rotate the nearest street
to the home's front, and uniformly scale the scene to its authored street
setback. This preserves handedness, bends and junctions. Clip segments at the
scenery boundary and deduplicate matching edges. Road meshes have rounded joins;
the original straight road mesh is excluded from merging so it can be hidden
when mapped roads arrive. There is still only one WebGL renderer.

Building centers suggest frontage positions. Additional candidates are sampled
along streets where building coverage is missing. A deterministic near-to-far
packing pass rejects overlapping rotated yards and road crossings, reserves the
active parcel, and caps the result at 48 houses. Up to eight nearest houses are
detailed. Sparse or irregular streets can produce fewer houses than the generated
grid. The home and neighbor footprints are authored dollhouse sizes, so the
result is a recognizable street layout, not a cadastral reconstruction.

The nearest street is a frontage assumption, especially on corner/deep lots.
Compass heading selection, terrain, water, parks, exact property boundaries,
building heights and real neighboring house appearances are outside this slice.

Version 2.499.147 partially corrected candidate density: generated spacing was at least 54
units for 52-unit yards, rather than dividing roads into intervals of 52 or less.
Redundant 58-unit neighbor and 60-unit home exclusion circles are removed;
rotated yard overlap and street-crossing tests remain authoritative. This avoids
rejecting alternate valid frontages and immediate neighbors. The layout cache
identity is incremented so old sparse results do not survive the update.

Version 2.499.148 replaces sparse midpoints with a two-unit frontage search.
It gives mapped positions priority over generated fill, places full-size yards
first, and fills remaining usable gaps with uniformly scaled 85% or 70% houses
and landscaping. Collision rectangles scale with the models; asphalt retains its
full width. The primary home is always reserved at full size. Scaled instances
retain a common ground level, positive instance matrices, material detail and
the existing near/far rendering tiers. The eight nearest accepted lots receive
detailed rendering after all placement passes. This is an available-space fit,
not reconstruction of exact building outlines: only building centers are
currently retained by the decoder. The layout cache identity changes again.

Mapbox logo and linked attribution appear only for the mapped scene, with a
tooltip explaining that houses and yards are illustrative. Provider references:
[Streets v8](https://docs.mapbox.com/data/tilesets/reference/mapbox-streets-v8/),
[Vector Tiles API](https://docs.mapbox.com/api/maps/vector-tiles/), and
[attribution](https://docs.mapbox.com/help/dive-deeper/attribution/).

## Footprint fitting (v2.499.149)

Mapbox only includes all buildings at zoom 16 and above. The previous road zoom
omitted small residential houses. Fetch the home tile and eight neighbors at z16;
retain successful coverage if a request fails and stop further building requests.
Road-only or partial mapped results retain the twelve-hour success cache.

Join building fragments by ID, deduplicate overlapping copies and omit building
parts, known non-house types, implausible areas and the building covering home.
Mapped centers are not snapped to a fixed street setback. Fit house wall bounds
to each polygon's minimum rotated rectangle, compensating for off-center and
mirrored source geometry. Height uses the geometric mean of width/depth scale.
Attached template gardens are omitted. Outline bounds approximate irregular
shapes; neither exact wall reconstruction nor parcel boundaries are implied.
Accept up to 128 mapped neighbors, nearest eight detailed. Generated frontage
fill is restricted to outside successful building coverage when outlines exist.
Corner frontage uses the nearest street and can still choose the wrong street.
The interactive primary home retains its authored size and navigation.

Use `HOUSE_MAP_FOOTPRINTS=1` with the browser gate for a dense offline footprint
fixture. Geometry tests check rotated/mirrored wall bounds, tile joins, duplicate
removal, dense rows, MVT polygon decoding and provider timeout behavior. The old
user-supplied API response contains no outlines and cannot validate actual new
building coverage; the cache version forces a fresh lookup on the installation.

## Shared home scale and visibility (v2.499.150)

Retain the primary footprint instead of discarding it. On the client, a uniform
similarity transform matches its bounding-box area to the interactive house's
wall area, aligns its facing axis and centers it on the authored wall bounds.
All map coordinates, road widths and neighbor dimensions share the transform;
the interactive home and room picking/navigation remain in authored units.
This approximates the fit without distorting street angles. Missing primary
footprint data retains the earlier scale and is visible in diagnostics.

Mapped houses are never removed by the generated scenery's 24-unit camera
corridor. Ordinary mesh occlusion still applies. Extend ground and the painted
horizon beyond all mapped roads and houses instead of cutting the scene at a
fixed radius. API `home` and `buildingDiagnostics` preserve primary geometry
and filter counts; `chfNeighborhood().homeCalibration` reports the applied fit.
Cache version increments. The supplied refreshed layout contains 43 houses,
all nine tiles, and no primary footprint (the previous version discarded it).
Replay checks visibility for those 43 houses; a separate footprint fixture checks
home scale. Provider completeness for lots absent from that file is not inferred.

## Missing outlines with house-number evidence (v2.499.151)

The updated user layout and matching source tiles confirmed that the immediately
left neighbor has a `housenum_label` point but no building polygon. Its omission
was a source-layer gap, not the rendering limit or primary-home exclusion.

Decode Point geometry with `house_num` from the same nine z16 tiles, respecting
the layer's own extent. After real building placement, consider uncovered label
points within the scene. Estimate width/depth from the median of the nearest five
real residential outlines within 80 scene units (including the home). Face the
nearest street. Try the estimate at 100%, 85%, then 70% only if necessary to avoid
known building outlines, roads and earlier estimates. A spatial index checks all
source building types so a label on a commercial building cannot create a house.
Multiple labels covered by one estimate do not create duplicate houses. Unlabeled
gaps in covered tiles remain empty; this is not indiscriminate street infill.

Estimates use `placementSource: house-number` and `footprint.estimated: true`,
with `addressCount` separate from `footprintCount`. Real outlines and home scale
do not change. No extra requests or dependencies are needed. Cache identity
increments. The matched source replay produces 43 real outlines plus 13 estimated
houses, including the left neighbor. Private map data remains an ignored local
fixture. Unit coverage checks duplicates, nonresidential reservations, road
exclusion, no invented unlabeled houses, absent donors and MVT label decoding.

## Proof

`test_house_map.py` checks real MVT decoding, coordinate direction, request count,
rotation invariance, clipping, frontage orientation, yard/road exclusion,
determinism, bad pins, cache reuse, changed home, disable and failure cooldown.
`test_house_map_live.py` covers initial asynchronous and cached loads, eight
distinct detailed geometry signatures, one canvas, resource replacement, hidden
original road, orbit, rooms, editor isolation and provider failure fallback.
Existing facade and generated-neighborhood tests remain required.

Initial visual checks used an offline street fixture with bends and intersections.
The later user-supplied API response contains 41 road segments and 20 accepted
houses; replaying those roads with the old compiler reproduces all 20 positions
exactly. The new compiler produces 37 houses (28 full-size, three at 85%, six at
70%) on identical roads. No additional map requests are needed for this replay.
Run the browser gate with `HOUSE_MAP_REPLAY` pointing to the supplied JSON to
verify its actual rendering, including instance scales, and `HOUSE_SHOTS` to
capture it. The supplied private layout is not committed as a fixture.

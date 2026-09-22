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

One lookup fetches at most four latitude-adjusted vector tiles, sequentially,
with connect/read timeouts of 3/5 seconds. It includes ordinary surface streets;
motorways, service alleys, tunnels and bridges are not residential frontage.
Mapbox `road` geometry and `building` polygon centers are decoded with
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

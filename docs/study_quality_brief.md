# Study quality pass — September 2026

The Study now uses the house style bible's material and joinery vocabulary.
Its read-only objects still mean the same things: no invented paperwork,
program binders, findings or alerts decorate a quiet household.

## Art direction and level design

Ivory plaster, deep sage paneling, oak, brass, terracotta, teal upholstery and
an oxblood reading chair/rug replace the old uniform sepia treatment. Narrow
staggered floorboards establish scale. The camera fits the calendar and floor
lamp; a library and reading chair/table give the lamp a reason to be there.
Reference books are scenery, physically separate from live program binders.
The window looks onto planting and a fence rather than an unrelated city.

An independent screenshot judge reviewed the baseline, rejected the first
pass (hidden library, empty floor, weak material separation), and passed the
third iteration after those concrete findings were addressed. Captures:
`scratch/study-before/overview.png`, `scratch/study-pass1/overview.png`,
`scratch/study-pass3/overview.png`. Use `tools/study_probe.py` to reproduce a
calm or active view, day/night, at high/medium/low quality.

## Geometry, materials and lighting

The house's 44-triangle chamfer generator gives small solid props edge
highlights. Pots use turned profiles; plants have actual leaf silhouettes.
Inset drawers, keycaps, chair arms, shelf reveals and book spines add useful
detail. Explicit sRGB conversion makes solid swatches match canvas maps;
live signal colors follow the same conversion. Cooler neutral fill preserves
sage/wood separation; a reduced directional key keeps the warm practical
lamps. Shelf cast shadows no longer dominate the empty corkboard.

## Runtime and verification

The canvas uses device pixel ratio 1, matching the house. A settled Study
stops rendering. Camera moves, explicit monitor focus and real paper transfers
can animate; minute clock refreshes do not restart perpetual camera drift.
Reduced-motion suppresses sustained monitor animation. Low tier omits
micro-chamfers/keycaps and real shadows; forced 2D and small screens keep the
existing list. New live tests cover all twelve lean-ins, GPU resource reuse
across repeat visits, stopped idle frames, low tier and 2D fallback. Existing
state tests retain the role filtering, read-only and text-safety contracts.

This is a bounded authored room upgrade, not a port of every house rendering
subsystem: no vertex AO bake, scene batching or physical wall-panel benchmark
is claimed. The calm desktop capture increased from about 130 to 299 draws
and 8.7k to 22.3k triangles while moving; its steady-state render cost is now
zero between explicit updates. Physical wall-panel performance remains to be
verified.

# Edits stop recomputing rain cover for the whole scene

## Measured (owner's 11-20 export, editor, High, Chromium, CPU profile of one post delete)

`view.rebuild` 9.33 s, of which `writeWeatherOpen` (`sky/sky_cover.js`) 7.93 s: `open` 4.15 s (self 1.57), `height` .98, `edgeDistance` .93, `inPolygon` .74, `slabOpen` .97, `clipHorizontalToCover` 1.95, `buildCoverEdges` 1.43. `buildTwin` 2.49 s. Every structural edit on the house pays this (roof edits: 7 to 9 s), on main too.

## Cause

Any change to any roof or supported roof gives a new `staticKey`, so every vertex of every mesh and every instance (yard, grass capacity, furniture, all buildings) is sampled again against all cover.

## Decision

Same output, less work. `weatherOpen`, clipped geometry, ranges and bake inputs stay byte-identical to a fresh computation.

1. **Dirty region.** Compare the previous and the new cover by part (roof triangles, slabs, footprints, interior tops, porches). The changed area in XZ, grown by `EDGE` and the clip margin, is the dirty region. A vertex or instance outside it, with the same world position, face class and slab set, keeps its stored sample. A change that alters a global term (`minimumRoof`, `bounds`) dirties exactly what that term can change; state the argument in a comment.
2. **Rebuilt meshes.** A rebuilt building's batches are new objects. Reuse samples by exact world position (and roof-face flag) from the previous build of that building, outside the dirty region.
3. **Clipping.** `clipHorizontalToCover` and `buildCoverEdges` re-run only for meshes whose bounds meet changed cover edges; otherwise the previous clipped geometry is reused, with its saved base and ranges.
4. **Cheaper math** for what remains: reject by bounds before polygon tests, no arrays per call in the hot path, distance on squared values. Byte-identical results are required; if the last bit differs, keep the old arithmetic.
5. No worker, no time slicing, no change in when results appear.

## Gates

- Byte equality against main on the household fixture and the owner's export (by path only): `weatherOpen`, positions, uvs, indices, snapRanges and draw ranges of every mesh, after each of: first build; delete a post; move a post; raise a roof plate; move a roof edge; add and delete an awning; move a wall; move a room; add a porch; edit hardscape; undo of each; two edits in a row; and the same through `settle` and `rebuild`.
- Owner's export, the same CPU profile: `writeWeatherOpen` under 0.8 s for a post delete and for a pool-house roof edit, under 2 s for a main-house roof edit. First load no slower.
- Memory: the stored samples add no more than 10 percent to geometry memory; report it.
- 0 draws, programs, samplers; no shader change; atlas and bake keys identical.

# Living-room visual comparison

Date: 2026-09-23. Branch: `feature/living-room-atmosphere`.
Baseline: `672df7e6` (v2.499.162). Prototype: v2.499.163.

## Scope and outcome

The marketing reference prompted a bounded test of whether a richer real-time
living room could approach that image. The user clarified that the gap involves
mesh quality, materials, lighting, shadows, and composition together.

The prototype is a more detailed stylized room. **It does not reach the
reference's realism.** The branch is a comparison checkpoint, not a proposal to
roll this rendering approach across the house. It remains isolated from main.

Changes:

- A lower, oblique room camera makes the hearth and furnishings readable.
- Cushions use rounded geometry and curved normals; medium reduces tessellation
  and low uses inexpensive bevels. Furniture and feature coordinates stay fixed.
- Medium/high plants use thin, tapered, curved leaf blades and leaf-vein maps.
- Deterministic room-local fabric, oak, stone, rug and painted-art textures replace
  several flat surfaces. High adds shallow fabric/leaf bump detail.
- The rug carries soft contact shading at the fixed furniture positions.
- The flame now sits in front of the firebox back instead of being occluded by it.
- Two localized light pools replace the living room's one ceiling pool: firelight
  and the reading lamp. They use the existing day/night and interior/exterior
  ownership rules. Low retains zero point lights and a complete lamp silhouette.
- One larger painting replaces the five small color panels. The existing shared
  kitchen/living floor texture uses narrower oak boards and finer grain, keeping
  one finish through the open room.

No changes to photo analysis, facade compilation, room/zone ownership, card
handlers, weather state, quality selection, or backend storage are involved.

## Visual review

Captured from a real Chromium browser at 1400 x 1000, using the shared
`house_probe` seed and renderer instrumentation. State is intercepted with an
explicit sunny day or clear night; household data lives in a new temporary
directory. Math.random is seeded for comparable incidental scene decoration.

The review rejected a tighter camera because the reading lamp obscured the
Program book marker. The retained camera shows Radio, Critters, Home ledger and
Program book; the capture test waits for all four, not just a settled camera.

The richer room gives the hearth a visible flame, clearer upholstery silhouettes,
better surface scale, and stronger localized night light. Remaining gaps include
the limited authored asset detail, hard directional shadows, simple indirect
light, procedural rather than scanned materials, and the toy-like architectural
and furnishing treatment. More small props would not address those limitations.

## Cost and validation

The baseline high view had 746 in-frustum meshes and approximately 138,142
triangles. The retained prototype view has 1,187 and approximately 180,408:
about 59% more mesh submissions estimated by the probe and 31% more triangles.
This includes the different viewpoint and its cutaway geometry, not just the
extra cushion detail. The estimate is not an exact GPU draw-call count.

| Tier | Baseline in-frustum meshes | Prototype | Baseline triangles | Prototype |
| --- | ---: | ---: | ---: | ---: |
| High | 746 | 1,187 | 138,142 | 180,408 |
| Low | 426 | 486 | 23,170 | 24,460 |

Low adds approximately 14% more in-frustum meshes and 6% more triangles. It
continues to use zero point lights. Day and night have identical geometry counts.

CPU render-submission timing was collected, but became highly variable under
host load. It is not suitable evidence of device FPS. No wall-panel hardware
performance claim is made. The branch should not be promoted based on these
desktop captures alone.

Repeat the visual/ownership checks from `chauffeur/`:

```powershell
python tests/test_house_living_visual_live.py --out ../scratch/living-review
python tests/test_house_markers_live.py
python tests/test_house_lighting_live.py --smoke
```

The first command saves high/low day/night PNGs and `stats.json`, checks that all
four living-room features are visible, checks entry/exit mask ownership, rejects
browser errors, and confirms no point lights at low quality. The remaining
commands cover exterior quick views, intentional zone visits, and mirrored
lighting ownership across interior/exterior transitions.

The visual matrix passed in all four combinations on the final prototype, with
zero room or exterior mask leaks. All four screenshots were inspected. JavaScript
syntax and Python compilation checks also passed.

The quick-view browser test passed previews in every room, mobile layout, drag
cancellation, long-press visits, and second-tap room entry. The existing lighting
test initially failed because it mocked `Date.getHours()` although the renderer
now consumes the supplied outdoor sun state. Its fixture now patches the outdoor
state to a fixed clear night for the duration of the matrix; production sun logic
is unchanged. The corrected smoke matrix passed both mirrored layouts in day and
night, including interior/exterior lighting ownership across all five rooms.

## Recommended next comparison

Build one room from a polished rendered background, with the existing live
markers and cards over it. Compare that directly with this branch on the same
device and at the same viewport. Evaluate appearance, loading/interaction delay,
memory, day/night transitions, and whether the navigation still feels spatial.

A potential hybrid keeps the deterministic facade/room model as the source of
viewpoints, architectural geometry, and projected interaction anchors. Render
high-quality backgrounds ahead of time and cache them. Keep cards, status and
selected effects live. Start with curated room interiors; personalized exteriors
can come from the photo-matched model.

Independent generated images for each viewpoint are not an architectural source
of truth: they may disagree about windows, stories, roof directions and room
layout. A shared scene or other explicit geometry conditioning is necessary,
with review for any image-generated enhancements. The lightweight model alone
does not solve asset or rendering quality; the offline asset/lighting pipeline
would still need to demonstrate that quality.

This alternative exchanges free camera motion and inexpensive arbitrary visual
edits for better fixed-view image quality and much lower client rendering work.
It also introduces render generation, caching, resolution/variant management,
and alignment work. A single-room comparison should precede that investment.

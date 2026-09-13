# House navigation recovery

Version 2.496.0 completes Task 7 from the uncommitted work left at `b2c3317` after Claude Code reached its usage limit. The sealed exterior had lost room entry targets, and empty interior clicks still used the old exit behavior.

## Behavior

Shell registrations now declare their entry room. South and north walls and the main roofs enter the kitchen; the east wall enters living; the west wall, west skirt, and mudroom roof enter the mudroom; garage fabric enters the garage. The empty living-roof registration retains its living tag. The yard has no entry room.

Interior clicks on another room's zone or room-tagged fabric enter that room. Own-room zones still focus and open on a second click. Own-room props do nothing. Sky and yard exit, with the kitchen's existing first step back from a focused view retained. Visible roomless shell fabric is inert, including when an interactive zone lies behind it.

The first-visible-hit reader skips hidden objects and hidden ancestors. Ghost outlines remain raycast-immune. Existing zone resolution can still reach a zone through ghosted walls.

## Changes made during recovery

- Replaced the draft's duplicated raycast algorithms in `chfNavProbe` with the production hit readers, and corrected canvas/client coordinate conversion.
- Added tests for all four exterior room entries, a zoneless wall transition, the kitchen's two-step focus return, and roomless shell fixtures.
- Added a read-only settled-state query to the probe. The high-quality porch regression test now waits for camera completion instead of assuming a 1-second delay is sufficient.
- Corrected the test seed's `color_code` field and removed the draft's incorrect claim that an explicit high-quality URL permits automatic demotion. Both explicit high and low disable that benchmark.
- Corrected the east-wall explanation: the wall spans both kitchen and living. Its living entry is an explicit navigation choice from the spec, not proof that it only borders living.

## Control comparison

A route-served copy of `b2c3317` and the navigation build ran with identical fixtures, a fixed random seed, forced high quality, and daytime lighting. No files were swapped in the working tree. Room AABBs, registered boxes and normals, visibility verdicts, total/visible/in-frustum mesh counts, triangles, materials, and geometry counts matched exactly in all five views.

| View | In-frustum meshes, before and after |
|---|---:|
| Exterior | 1273 |
| Kitchen | 417 |
| Living | 732 |
| Mudroom | 388 |
| Garage | 538 |

These counts are mesh counts, not a claim that the existing probe includes ghost-line draw calls. The separately tracked line-count instrumentation gap remains an expansion prerequisite.

Build time measured 1548 ms for the baseline and 1391 ms for navigation in this comparison. This is not a claim of a speed improvement: timings vary with host load, and the baseline itself exceeded 1500 ms once. Geometry and counts can be compared exactly; elapsed build time cannot be required to be bit-identical.

Local artifacts: `scratch/navigation-evidence/control.json`, paired room screenshots in that directory, and `scratch/navigation-control.log`. The comparison precedes the additional roomless-shell pointer guard, which only runs on a click.

## Validation

- `python tools/test.py`: **222/222 files passed in 332 seconds**, including navigation and the initial roomless-shell fixture. The fixture was then strengthened through fault injection.
- Final `python tools/test.py` after strengthening the fixture: **222/222 files passed in 332 seconds**. No production changes followed that run.
- `python tests/test_house_live.py`: passed the room, focus, leak, shell, and navigation checks. The full sweep also includes the subsequently added roomless-shell scenario.
- `node --check chauffeur/static/house.js` and `git diff --check`: passed.
- The comparison's original porch pixel enters the kitchen in both baseline and navigation builds when the camera has settled.

Fresh high-quality builds measured **1212 / 1073 / 1149 ms**, all below the 1500 ms target. These runs occurred after the parallel suite finished. Artifact: `scratch/navigation-evidence/build-times.json`.

Regression sensitivity was checked with route-served source, without editing the working tree: `b2c3317` fails exterior mudroom entry; removing the new interior inert-shell guard fails the strengthened fixture with an actionable zone behind the wall. Both fail at the intended assertion. Artifact: `scratch/navigation-red.log`.

## Plan assessment

Navigation before footprint expansion is the right order. Preserve all built room positions, cameras, zones, and interiors. Keep unbuilt rooms inert.

Task 8 still needs a coherent roof design, not merely more facade surfaces. The recovered reference has connected pitched roof volumes; the current flat flank roofs and exposed ridge-height panels do not reproduce that shape. Derive a footprint and roof section together, then inspect front, side, and back views before treating the expansion as complete. Register distinct roof slopes with their actual normals and let the registry drive new merge units. Preserve the patio and relocate only planting that the expanded footprint displaces.

The recovered reference is at `scratch/navigation-evidence/claude-reference-1.jpg`. The other recovered images show the protruding rear window, blocked patio, and incomplete-house complaint. A perspective reference gives approximate proportions, not an architectural floor plan; document those assumptions rather than presenting guessed dimensions as measurements.

# House editor slice 1: the numbers

Date: 2026-11-18. Plan: `docs/superpowers/plans/2026-11-16-editor-slice1-measure-and-spike.md`. Spec: `docs/superpowers/specs/2026-11-16-twin-editor-overhaul-design.md`.

All numbers are on the owner's exported house, loaded into a scratch data directory through the house-file load path, in Chromium on the development desktop (the HA box), with `main` at v2.499.925. Times are medians in milliseconds.

## Answer

**0.5 s from release to picture is reachable, by a wide margin, with slice 2 as designed.** Keeping the meshes the drag already deformed shows the move 23 to 34 ms after release (six releases, interior and exterior walls). Applying the server's answer on top of it took 45 to 111 ms. Today the same release takes 3.7 s on high.

Two things must change beyond what the spec already says, both listed under "What slice 2 must include".

## Baseline today (`tests/twin_edit_measure.py`, 5 runs)

Scene: 2 buildings, 5 levels, about 455 meshes, 230 draw calls; 3.6 million triangles on high, 0.19 million on low.

| | high: wall | high: plant | low: wall | low: plant |
|---|---|---|---|---|
| release to frame | 3679 | 3863 | 3159 | 1234 |
| request (server and transfer) | 1340 | 1168 | 1743 | 971 |
| client rebuild | 2500 | 2397 | 1268 | 256 |
| of which building generate | 658 | 0 | 772 | 0 |
| of which batching | 294 | 0 | 373 | 0 |
| of which yard | 1284 | 1923 | 3 | 103 |
| response size | 312 KB | 312 KB | 312 KB | 312 KB |

Drag frame while moving a wall: 43 ms median, 79 ms max on high; 36 ms median on low. Idle frame: 16.6 ms on high, 33 ms on low (headless Chromium; low is not slower in practice, the idle number reflects the frame pacing of a hidden page).

Moving one plant costs almost as much as moving a wall on high: the yard rebuild is the largest single client cost.

## Where the server time goes

Unprofiled spans for a wall move (`tests/twin_edit_profile.py`, spike branch): apply 725, normalize 539, round write 47, read back 422, response 28. That is 1.76 s, more than the 0.8 s measured at v2.499.903.

From `cProfile` over `twin_edit.save` (fractions of profiled time):

- **Solar zone checks, about 27 %.** `twin_solar.error` runs ten times per edit (in `solar_clear` and again in `twin_model.normalize`), and each call rebuilds every roof face from scratch (`twin_solar.faces`: clip and subtract over every roof section). Nothing about the roof changed in a wall move. Remember faces per roof input, and skip `solar_clear` when no roof, dormer or solar zone changed.
- **Wall crossing checks, about 25 %.** `twin_model_graph.split_crossings` runs 22 times per edit over every wall pair. It needs only to look at walls near the moved one.
- **Derive, about 20 %.** `twin_model._derive` (rooms, joints, T-junction splits) runs three times per edit.
- **Read back, 0.2 to 0.4 s.** After saving, the server reads the model again and flattens it to build the response. It already holds the model it just wrote.
- **Response, 312 KB.** The whole flat plan and the whole model go back for every edit.
- Normalize now runs once per edit, not twice; that part of the spec's concern is already gone. The model write is 154 KB with two `fsync` calls, 47 ms: not worth changing.

## The local-apply spike (`spike=keep`, spike branch, never merged)

The editor kept the meshes `rebuildLevel` had already deformed during the drag, did not mark the building stale, and applied the server's flat plan to them with `rebuildLevel` when it answered.

| release | release to frame | server answer to settled frame | request |
|---|---|---|---|
| interior wall, 1 ft, three times | 33, 32, 23 | 111, 59, 54 | 982, 716, 856 |
| exterior wall, 1 ft, three times | 34, 27, 28 | 57, 58, 45 | 970, 788, 762 |

### What the picture gets wrong

Screenshots of the kept result against a forced full rebuild from the same camera, top and perspective, for both walls:

- **A pale translucent block over the porch** in every kept picture, for the interior wall too, which is far from the porch. A full rebuild removes it. Cause not yet known. Ruled out: the room pick proxies that `rebuildLevel` replaces with a `BoxGeometry` live on layer 31, which no camera draws. Candidates for slice 2's first task: selection or ghost outlines built from a proxy's box, and per-piece meshes on the focused level that a full rebuild re-batches.
- Apart from that block, walls, openings, the porch posts and deck, floors, roof edge and yard matched. The full rebuild was not visibly different elsewhere at these camera distances.
- Rooms, floors and ceilings are not re-derived locally. Moving a wall by a foot did not change any room outline in this house, so these releases do not show the two-step settle. The spec's Chromium test for a wall that splits another stays required.
- Baked light was not checked: the scratch house carried no bake.

## Live editor suites

**Root cause: the editor could not open on a house with nothing built.** `static/twin/editor/fixtures.js` `refresh` read `plan.light_fixtures` while the plan was still `null`, threw `Cannot read properties of null (reading 'light_fixtures')` into a notice, and `window.__editor.ready` never became true. Both suites seed an empty house, so every scenario after the first waited 60 s and failed. This was a product defect a new household would hit, not a test problem; it is fixed in this slice with a node test that reproduces it.

After the fix, run in the suites' own order (their scenarios share one server and build on each other's house; run in file order instead, 17 fail for that reason alone):

- `test_house_editor_live.py`: 38 of 39. Still failing: `scenario_pause_card_shows_its_reason_cost_and_pins` — after placing registration pins and pressing Looks right, no registration answer arrives within 10 s. The suite stops at its first failure, so it reports only 20 passes before this one.
- `test_house_editor_steps_live.py`: 7 of 8. Still failing: `scenario_add_plans_opens_your_files` — the Your place button (`#editor-manage-sources`) is covered by the Link to Home Assistant step button, so the click never lands.

Both remaining failures are in the automated generation and setup controls that slice 4 moves (the generation bar shows only while generating). They are recorded here and not fixed in slice 1. These suites can gate the overhaul from now on, with these two named as known.

Also found while investigating: two Python processes from the previous session's interrupted Codex run had been alive since 2026-11-17, each holding a hung Chromium launch. They were not the cause of the suite timeouts. While they ran, one probe's Chromium navigation to a test server timed out for over 200 s although the server answered plain HTTP in 0.2 s; after they were stopped, navigation worked. Stopped; if navigation timeouts return, look for leftover Playwright processes first.

## What slice 2 must include

Beyond the spec's slice 2:

1. **Fix the pale block** (the room pick proxy after a deform) before relying on kept meshes.
2. **The yard must not block the first frame.** `buildYard` already reuses unchanged parts, but an exterior wall move changes the `grass` and `furniture` keys (both read the house footprint), and a plant move rebuilds the whole `plants` part. On high that costs 1.3 s for a wall and 1.9 s for one plant. Either rebuild only the grass near the change, or keep the old yard on screen and swap the new one in when it is ready. The second is simpler and fits "untouched work stays untouched".
3. **Plant and yard piece moves need their own local apply.** A plant move has no building work at all but still costs 3.9 s on high today, all of it yard rebuild and round trip.
4. **Cut the server's second step** so rooms and splits settle well under a second: the solar face cache, local crossing checks, no read-back, and a response that carries only what changed. Each is independent and can be measured with `twin_edit_profile.py`'s counts.

## For slice 9 (one implementation of the room logic)

The server's derive and crossing work is about half its time per edit, and all of it is whole-house. Moving that logic to JavaScript does not by itself make it faster; making it local to the edited walls does. Whichever language it ends in, the rewrite should be incremental by construction.

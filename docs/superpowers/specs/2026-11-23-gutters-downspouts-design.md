# Gutters and downspouts

Date: 2026-11-23. Status: design for owner approval.

## Intent

The owner (2026-11-23): "Roof sections should be able to have gutters and gutters should stop eave stream from occurring on that roof edge. I'll give you bonus points if you can have gutters flow into downspouts and have those downspouts placed at the correct locations."

On placement, the owner chose automatic placement that a person can then adjust: "I would hope where they are placed by [the automatic rules] and where my actual downspouts are located end up being the same thing." So the rules must follow how gutters are really installed, well enough to match a real house without any hand placement.

## Today (facts the design builds on)

- **Authored roofs.** `building.roofs[]` has `edges[i]` paired with area segment i→i+1, as `{setting: sloped|gable|clip, pitch?, clip?}`. Validation is at `services/twin_model.py:433-438`. The editor's roof card opens per-edge settings (`editor/cards.js:405-440`, `drawEdge`) through `set_roof_edge` (`services/twin_model_ops.py:1506-1538`). Edge handles are in `editor/handles.js:142`.
- **Flattened sections.** `twin_model_roofs.to_sections` produces rectangular sections with `plane_edges{y0,x1,y1,x0 → authored edge index|null}` (twin_model_roofs.py:90-105). The generator's `roofMesh` (`twin_roof.js:324`) builds the roof, and fascia is added on every exposed perimeter edge (`twin_generator.js:1226-1248`).
- **Eaves for streams.** `extractEaves` (`sky/eave_streams.js:37`) finds the low horizontal edges of roof planes and porch/awning attachments, then `clipExposedEdges` keeps only exposed parts. The authored edge index is known in the group (`g.edge`) but dropped at line 75.
- **Below the eaves:**
  - exterior walls (`b.walls`) and openings (`b.openings`: wall, at, width, kind);
  - porches with columns (`allPorches(b)`);
  - hard surfaces (`collectHardSurfaces`, `sky/precipitation.js:43`);
  - a landing sampler that reports ground, hardscape, deck, roof, bed or water under any point (`createEaveLandingSampler`).
- **No gutter or downspout data or geometry exists anywhere.**

## Goals

1. Any eave edge of any roof can have a gutter. A guttered edge sheds no eave streams.
2. Gutters drain into downspouts placed by rules that match real installation practice, so the automatic result matches the owner's real house.
3. A person can adjust any run's downspouts: drag one along the run, add one, or remove one. The adjustment is stored and survives rebuilds.
4. In rain, each downspout pours its share of the run's runoff out of its outlet onto what is below. The pour follows the same wetting and drying ladder as the streams.
5. Gutters and downspouts look like real K-style aluminium gutters and rectangular downspouts, in the trim colour by default, and are paintable as their own surface kind.

## Non-goals

- Overflow of gutters in extreme rain (a possible later addition).
- Downspouts piped into underground drains (the outlet just pours onto what is below).
- Rain chains and other decorative drains.
- Gutter guards.

## Anti-goals

- **Downspouts in absurd places:** in front of a door or window, dumping onto a walkway or front step, hanging in mid-air, or running across an opening.
- **Existing houses changing on their own.** Gutters are off until a person turns them on.
- Losing a person's adjustments when the roof is rebuilt.

## Approaches considered

1. **Per-edge gutter flag with generated gutters and rule-placed downspouts, plus stored overrides (chosen).** Gutters come from the roof's own edges and stay correct as the roof is edited. The rules give a right answer out of the box, and overrides cover what the rules cannot know.
2. **Gutters and downspouts as placed models.** Rejected: every roof edit would leave them floating or misaligned, and nothing would tie them to eave streams.
3. **A gutter toggle per whole roof only.** Rejected: real houses gutter some edges and not others (e.g. not over a porch with no posts, not on a small bay roof).

## Design

### Data

- `building.roofs[].edges[i].gutter: boolean` (absent = false). Allowed in `twin_model.py` validation and set by `set_roof_edge` (new optional field `gutter`).
- `building.roofs[].edges[i].downspouts?: number[]`: distances in feet along the gutter run segment that belongs to this edge.
  - Absent means automatic.
  - Present means exactly these positions; an empty array means none on this edge.
  - Written when a person drags, adds or removes a downspout. "Reset downspouts" deletes it.
- `to_sections` mirrors the flags onto sections as `gutters: {x0|x1|y0|y1: true}` through `plane_edges`, whitelisted in `twin_plan.py`, so the generator, streams and bake see them without reading authored roofs.
- New surface kind `gutter`, used for gutters and downspouts. It defaults to the building's trim/fascia finish. Entries go in `services/twin_surface_kinds.py` and `static/twin/surface_kinds.js`, in the editor's Trim group.

### Gutter runs

- A run is a chain of guttered, exposed eave segments that are joined end to end: endpoints within 0.3 ft and heights within 2 in. Runs therefore wrap around hip corners and along continuous eaves across sections.
- Runs are computed in one pure module, `static/twin/gutters.js`, from the same eave extraction the streams use, after exposed-edge clipping. Gutters exist only where the eave is actually exposed.

### Downspout placement rules (the heart of "correct locations")

These follow common installation practice:

1. **Count per run:**
   - one downspout per started 35 ft of run;
   - for runs longer than 35 ft, downspouts go at both ends first;
   - a run of 20 ft or less gets one.
2. **Candidates,** in priority order:
   - outside corners of the run, where a downspout sits on a house corner;
   - run ends;
   - then evenly spaced interior points, for long runs only.
3. **Mounting.** Each candidate must have something to come down:
   - an exterior wall face within 2 ft behind the gutter line (the downspout runs down the wall, with offset elbows from gutter to wall);
   - or a porch post within 1.5 ft (the downspout runs down the post).

   Candidates with neither are rejected. That means no free-hanging downspouts, except where a run has no candidate at all; then its end hangs and is flagged in the editor's Check list.
4. **Exclusions.** Reject a candidate when:
   - its wall position falls within an opening (door, window, slider, garage) plus 1 ft on each side;
   - or its outlet would land on a walkway or path, or on a deck stair or step.

   Then slide the candidate along the run (up to 6 ft) to the nearest acceptable spot.
5. **Upper roofs:**
   - when the landing under the outlet is a lower roof, the downspout ends on that roof with an elbow, as on real houses, and its water joins the lower roof's runoff;
   - when it is a deck, it runs down to the deck.
6. **Ties:**
   - prefer the end that drains away from entries (front door, main walkway);
   - otherwise prefer the end nearer a house corner;
   - otherwise prefer the lower-numbered edge, for determinism.
7. **Determinism.** Placement is a pure function of the plan, so the editor and viewer agree and rebuilds are stable.

### Geometry

- **Gutter:**
  - a 5 in K-style profile (front ogee approximated by a few segments, flat back against the fascia, open top);
  - hung on the fascia along the run, with end caps and mitred corners;
  - no visible pitch (real pitch of about 1/4 in per 10 ft is invisible at this scale).
- **Downspout:**
  - 2 x 3 in rectangular section;
  - an outlet under the gutter, then two 45° offset elbows to the wall or post face, then straight down;
  - a bottom elbow with a 3 ft kick-out extension directed away from the foundation, along the outward normal;
  - on a lower roof, a short elbow onto it.
- **Cost:**
  - Gutter and downspout meshes merge with the roof and wall batches: no new draws per piece, and a handful of triangles per foot.
  - Report the triangle count and draws on the owner's house before any look review.
  - They are lightmap receivers like fascia, so `BAKE_GENERATOR_VERSION` is bumped.

### Water

- `extractEaves` carries `side` and `edge` on each eave record and drops guttered segments, so streams leave only unguttered edges.
- **Downspout outlet pours:**
  - a pour is a short stream instance at each kick-out (or elbow onto a lower roof), using the eave-stream material and motion;
  - its flow is the catchment share: the run's roof catchment, approximated by eave length times the plane's horizontal depth, divided among the run's downspouts and normalised;
  - it follows `eaveRunoff` (no pours until the roof wets through) and the drying ladder;
  - pours onto a lower roof feed nothing extra in v1 (the lower roof already runs at the global wetness).
- **Distance and level gates** are the same as the streams: house, building and yard-room focus; floor and room cutaways hide them; LOD out to 120 m.

### Editor and Argyle (every agent capability has a hand path, and vice versa)

- **Edge card:**
  - a "Gutter" toggle beside Sloped/Gable/Clipped, shown only on edges that have an eave;
  - the roof card gets "Gutters on all eaves" and "Remove all gutters".
- **Downspout handles.** With a guttered roof selected, each downspout shows a handle:
  - drag along the run to move it;
  - right-click to remove it;
  - "Add downspout" on the run's card adds one;
  - "Reset to automatic" clears the overrides.

  All of these write `edges[i].downspouts` through one op, `set_roof_edge` with a `downspouts` field.
- **Check list.** It flags a run whose end must hang free.
- **Argyle.** `set_roof_edge` gains `gutter` and `downspouts` in the edit tool description, so Argyle can do the same as the editor.

### Decisions settled after the builder check (Claude's calls)

1. **Override storage.** `edges[i].downspouts` holds fractions 0..1 along authored edge i, measured from its first vertex, so moving that edge rescales them.
   - At build time each fraction snaps to the nearest exposed, mountable point of that edge's gutter.
   - Ops that insert or remove roof area vertices remap `gutter` and `downspouts` the same way they already remap edge-keyed data (`plane_materials`). The builder confirms which ops those are and tests each one.
2. **Edge to eave mapping.**
   - A section side is guttered when the authored edge it maps to through `plane_edges` is guttered (the existing largest-overlap rule). Interior sides cannot have gutters.
   - Porch roofs and awnings (`eaveAttachments`, which have no authored edge) get their own flag: `gutter: true` on the porch record or awning item, with a toggle on the porch/awning card. Real porch roofs usually have gutters, including the owner's front porch.
3. **Ops.**
   - `set_roof_edge` accepts `gutter` and/or `downspouts` without `setting`, and refuses `gutter` on gable or clipped (rake) edges.
   - "Gutters on all eaves" and "Remove all gutters" send one `batch` of `set_roof_edge` ops, so they are one undo step.
   - Porch and awning flags go through their existing update ops.
   - Validation:
     - `gutter` is a boolean;
     - `downspouts` is a list of numbers in [0, 1], at most 8 per edge.
4. **Bake key.**
   - Sections mirror both `gutters{side}` and `downspouts{side: [fractions]}`. Neither is render metadata, so both are hashed by `authoredGeometry` and changes trigger the rebuild.
   - Placement reads only the plan: authored roofs, sections, walls, openings, porches, site hardscape, and the pure-geometry landing sampler. So editor, viewer and Node tests agree.
5. **Inputs and ties.**
   - The plan has no main-entry marker, so the first tie-break becomes: avoid the end that is within 6 ft (along the wall) of any exterior door on any level below the gutter.
   - Opening exclusion checks every exterior wall the downspout passes on its way down, on all levels below the gutter, not just the wall at eave height.
6. **Mounting distance.** "Something to come down" means an exterior wall face or a porch post within the overhang plus 1 ft, measured horizontally from the gutter's back line.
   - Deep overhangs (up to 4 ft) get a horizontal leader run under the soffit from the outlet to the wall, as real installs do.
   - At hip corners the downspout comes down the house corner beneath. Where no corner exists, it moves along the run to the nearest mountable point.
7. **Partial coverage.**
   - Runs contain only guttered, exposed segments.
   - Unguttered parts of the same eave keep their streams.
   - Parts already clipped as unexposed have neither streams nor gutters.
8. **Count.** One downspout per started 35 ft: 35 ft or less gets one; longer runs place both ends first.

### The owner's real house (2026-11-23, overrides the placement rules above where they differ)

"The downspouts are on the outside corners - there is never a downspout on an inner corner. They prefer to go down into grass or plant beds, though there are some that flow onto the driveway."

1. **Outside corners only.**
   - Candidates are the run's outside (convex) house corners, meaning corners where the walls below turn outward.
   - Inner (concave) corners are never candidates, even when a run ends there.
   - A run with no outside corner gets its downspout at the run end that is not an inner corner, mounted on the wall. The Check list flags it.
   - The 35 ft count rule only decides how many outside corners of a long run get one. Interior mid-run downspouts are not used.
2. **Landing preference, applied when sliding or choosing between candidates:**
   1. grass, or a planting bed (`site.beds`);
   2. a driveway;
   3. never a walkway, path, patio step, porch step or deck stair.

   If an outside corner's outlet would land on a walkway, the kick-out turns along the wall toward the nearest grass or bed (up to 4 ft), rather than moving the downspout off the corner.
3. **Acceptance test against the owner's house:**
   - every downspout on an outside corner;
   - none on an inner corner;
   - every outlet on grass, a bed or the driveway.

## Look checks (before the owner sees anything)

Captures on the owner's house:
- default overview, a building-focused view, close-ups of a corner downspout and a porch-post downspout;
- heavy rain and the rain-stopping ladder;
- before and after with gutters on all eaves.

Then a side-by-side with photos of the owner's real downspout locations, if the owner provides them: the placement check against reality.

## Constraints

- Gutters off by default; no change to existing houses until enabled.
- One bake rebuild when gutters are first enabled (geometry and generator version).
- Placement is plan-only and deterministic.

## Left to the builder

- The exact profile vertex counts.
- Mitre construction.
- Elbow geometry.
- The run-joining tolerance tuning, within the stated limits.
- The catchment approximation details.
- Test design: pure placement tests on synthetic houses, generator geometry tests, stream suppression, editor ops and a Chromium look.

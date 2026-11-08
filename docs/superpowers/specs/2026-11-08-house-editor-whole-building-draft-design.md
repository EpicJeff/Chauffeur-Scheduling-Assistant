# House editor: whole-building draft read

Status: design, awaiting approval. Date 2026-11-08.

This replaces how `services/twin_build.py` reads a building that has drawings. Everything else in slice 1b-i stays as it is: Your place, the lot, shells, the place chain, fit, finishes and compose.

## Why

The first device build of Your place (v2.499.766) was rough. The repair in v2.499.767 improved it but did not make it right.

The user asked why the pool house can't be built correctly, when earlier runs guided by hand built it several times. It is the simplest house there is, and it has a full engineering set.

The answer is the architecture.

- **How the engine reads today.** It reads a building in many small cropped reads, and each one answers in positions measured within its own crop:
  - an outline,
  - walls for each wing,
  - openings,
  - rooms,
  - a registration read for each upper floor,
  - the roof,
  - the pitch.
- **How it puts them together.** It stitches the pieces with geometric gates.
- **What goes wrong.** Every seam loses precision. Every read also decides for itself what "the footprint" means: one includes the open porch, the next leaves it out. The result is ghosts, upper floors and roofs shifted by several feet, and pauses the person cannot answer.

The earlier good results came from a person, or Claude, reading the whole set at once and writing the plan in feet from the printed dimensions.

So the engine should read the way the earlier successful runs did: the whole building at once, in feet, from the dimension strings.

## Evidence

Throwaway spikes on 2026-11-08 cost about $2.24 in reads. Each spike made one read per building. That read had all of the building's sheets plus its photos attached together, answered in the current plan schema in feet, and was rendered with the real 3D generator.

**Pool house.** Simple: one storey plus a loft, a gable roof, a shed porch and an awning.
- The read matched the hand-written plan within about 0.2 ft:
  - first floor (L1) 31 x 22;
  - upper floor (L2) placed at x 5.67 to 25.33, elevation 10.9;
  - main gable at plate 10.9, pitch 11;
  - porch shed at 3:12, plate 10;
  - the awning, the columns and the stair.
- The renders match the photo.
- About 130 s and $0.41 per read.

**Main house.** Complex: four staggered wings, hips, cross gables, a storey-and-a-half section and a bonus room.
- A low-effort read (28 s, $0.17) collapsed the staggered fronts and dropped pieces.
- A medium-effort read capped at 64k output took 219 s and cost $0.53, using 16.5k thinking tokens and 5.3k answer tokens. It got these right:
  - **Wing placement.** Every wing's front setback is right within 0.2 ft.
  - **Outline.** The ground-floor outline is 70.00 x 66.33 against the hand key's 70 x 66.31. The fit RMS is 0.09 ft, against 0.29 for the current engine. The mean error without a fit is 0.79 ft, against 2.15.
  - **Roof.** The centre hip has the right ridge axis. The read also found the centre 12:12 front gable and the left gable, both of which the current engine misses. The front render reads like the front photo.
  - **Upper floor.** Its walls close; the engine leaves 4 open ends.
  - **Openings.** They appear on all four sides of the ground floor.
- It still had these gaps:
  - The storey-and-a-half rooms (left bedroom, right room, bonus room) came back as knee-walled roof space with no upper-floor outline or floor.
  - The schema cannot express windows in a gable end whose ridge runs side to side, so 2 were dropped.
  - The rear screened porch was kept as an open porch.
  - Every height is an assumption, because the set has no elevations or section.

An earlier medium read of the main house had a 30k output limit. It spent the whole limit thinking and wrote nothing. What made it work was the 64k limit plus an explicit line in the prompt: "stop reasoning by about 45000".

The spike prompts, answers and renders are in the session scratchpad, in `spike_whole/` and `spike_whole_main/`. The product prompt is written fresh from the rules below. Nothing specific to this household is copied into it.

## Goals

- A building with drawings is built from **one whole-building draft read**. That read answers in feet from the printed dimensions, in one frame for every level.
- **Joints come first.** Walls, floors and roofs meet without gaps or poke-through, even where that means moving a piece a few inches from its measured place (section 6a).
- Both of this household's buildings come out on the first build:
  - recognisable from all four sides;
  - matching the photos;
  - with no pause a person cannot answer.
- The targets carried over from the slice:
  - the whole place builds in under 30 min and for under $5;
  - a first ghost appears within 30 s;
  - the build is never more than 20 s without a visible sign of progress.
- It works for any household's building, not just these two. No prompt or code carries household-specific text.

## Non-goals

- Lot features and ground levels (slice 1b-ii).
- Interior partitions beyond what the rooms read in section 4 gives.
- Changing shells, the lot read, the plot read, placement, fit, finishes or compose.
- Reading a building from photos alone. That is what shells are for.

## Anti-goals

- A draft that settles pieces it is unsure of. A piece that fails a check becomes a ghost with a plain why. It never becomes a silently wrong wall.
- Positions measured in pixels where a dimension string exists.
- A building silently shifted to make two reads agree. That was the old footprint-mismatch failure.
- Losing a person's edits on a rebuild.

## Design

### 1. The steps for a building with drawings

For a building part with floor pages, `plan_steps` returns these steps:

1. **`outline:L1`.** The existing quick outline read of the first-floor page. It is kept only for the **first ghost**.
   - It starts immediately, at low effort, and takes about 15 to 25 s.
   - It draws the ground-floor outline as a ghost.
   - It never settles anything and never pauses.
2. **`draft`.** The whole-building read described in section 2. It runs at the same time as the quick outline read; both start immediately (see "Running two reads at once" below).
   - When it lands, these settle together: the building's levels, exterior walls, openings, roof sections, extensions, porch and stairs.
   - The outline ghost is then replaced.
3. **`rooms`.** One read per building for rooms and interior walls, given the settled draft (section 4).
4. **`finishes`, `fit`, `compose`.** Unchanged. `finishes` runs when there are photos; `fit` runs when there is a lot.

For buildings with drawings, these steps are retired: `registration:<level>`, `walls:<level>:<wing>`, `openings:<level>`, `rooms:<level>`, `roof` and `pitch`.

*My call:* their code stays only as long as the legacy build body `{building, photos}` needs it. Tests pin slice 1's exact steps for that body, and a person cannot reach it from the product. This slice leaves the legacy path untouched; a later cleanup retires it.

Step ids stay the same across rebuilds (`draft`, `rooms`), so the read cache and the build record keep working.

**Running two reads at once.** *My call:* the `draft` step starts the quick outline read on a side thread inside the same step, so the step runner stays one step at a time.
- The cost checkpoint is checked once before the step, against the two reads' combined estimate.
- Both reads' costs go to the ledger.
- If the outline read fails or lands after the draft, it is dropped silently. It only ever draws a ghost.
- Buildings in the place chain still build one after another.

### 2. The draft read

**Inputs.**
- Every page of the building with role floor, roof, elevation or other; pages marked skip are left out.
  - Each page is sent whole, at up to 2576 px on the long side, with its note boxes kept.
  - A crop is used only when a person cropped a region onto this building.
- The building's tagged photos, up to 4, with the front photo first.
- The user prompt lists each image with its role and level name as set in Your place.

**Call.**
- `model_pools.call_pool_json('twin', ...)` with these settings:
  - `strict_json='lenient'` (every completion check of `strict_json=True`, plus the lenient parse below)
  - `thinking_level='medium'`
  - `max_output_tokens=64000`
  - `timeout_s=420`
  - `max_models=1`
- *My call:* medium effort, because low effort failed the main house and the medium read fit with room to spare.
- **Provider.** *My call:* the spikes ran on Claude (`claude-opus-5-5`, the household's twin provider), and Claude is what ship must prove.
  - Other providers get the same prompt, with `max_output_tokens` clamped to the model's limit.
  - A provider whose twin model cannot give at least 32000 output tokens goes straight to the per-level fallback (section 5).
  - Recordings and the acceptance run are Claude only.

**Level ids and sheet registrations.** The answer also carries `pages: [{image, level, anchors}]`, one entry per floor page and the roof page.
- `level` is the level that page draws. The draft owns level ids: they are L1, L2, ... in elevation order, and a half-storey is a level like any other. The page's level name, as set in Your place, becomes that level's name.
- `anchors` gives three or four outline corners of that level, each as `{px:[u,v], at:[x,y]}`, with u and v as fractions of the image.
- The build fits each page's registration from its anchors (the same similarity fit `_fit` uses), so the Sheet tool's drawing under a floor and the `registration` edit keep working on every drawn floor, upper floors included. *My call:* an anchor fit good to a foot or two is fine here, because it only lines up the drawing under a floor and a person can realign it as today; positions in feet still come from the dimensions.
- A page without usable anchors gets no registration. The Sheet tool then shows its existing "not lined up yet" message for that floor.

**Lenient parse.**
- Before validation:
  - strip code fences;
  - strip any text before the first `{`;
  - text after the object is refused, except one stray `}`; a second JSON object is refused;
  - drop one stray trailing brace.
- Nothing else is repaired.
- A reply cut off at the output limit is not retried at the same size, because 64k is the ceiling. It goes to the per-level fallback in section 5.

**Answer shape.**
- `{building: {levels, walls, openings, rooms: [], roof: {sections, extensions}, porch, stairs}, checks: {front_edge, level_sizes, upper_offsets, wing_y}, notes: [...]}`
- This is the existing plan schema, plus the two additions in section 3.
- `twin_plan.normalize` runs on it as it does now. Every piece it drops is named in one plain log sentence (the v2.499.767 rule).

**Cost and time.**
- About $0.40 to $0.90 and 2 to 4 minutes per building.
- The estimate shown before Build includes it.

#### Prompt rules

These rules were learned in the spikes. All of them go in the product prompt, written generically.

**Measuring**
- Work in decimal feet from the printed dimension strings.
- Chain the partial strings against the overall string, and report any that don't add up.
- Never take a position from pixels when a string or a size callout gives it. Name anything that was scaled in the notes.
- Size callouts (`2^8 x 5^2`, `12^0 x 8^0 SLIDER`) are width x height.

**Heights**
- Take heights from the sheet notes (ceiling, plate, window head, door height, knee wall), and from elevations and sections when the set has them.
- When a height is missing, use a typical value checked against the photos, and list each assumed height in the notes.

**One frame for all levels**
- The origin is the front-left corner of the overall dimension box of the enclosed ground floor. +x runs to the right along the front; +y runs toward the rear.
- Find the front by matching the front photo. Plans may be drawn with the front at the bottom of the sheet.
- Place each upper level from the dimension strings it shares with the floor below. The checks say which strings were used.
- Staggered wings: every wing keeps its own front and rear y from the strings. The checks list them.
- Overall dimensions are to the outside face of the walls, so outline points and exterior wall endpoints are on that face.

**Outlines and walls**
- An outline traces enclosed walls only. Open porches and decks are never part of an outline.
- Exterior walls follow the outline exactly, with shared endpoints. This read writes no interior partitions.
- Gable ends apply to gable sections only, never to hips. No upper-floor wall runs along a gable end when that section's plate is below the top of the upper-floor wall.
- Under hips, and under gables whose plate sits on the upper floor's own plate, every upper-floor exterior wall is written so the floor closes.

**Openings**
- `at` is the distance from the wall's from point to the opening's centre.
- Sill and head are measured above the level's floor. The head is never above the wall.

**Roof**
- One section per roof mass. A cross gable is its own section.
- Each section's rect sits on the walls it bears on; the overhang is given separately.
- Read the ridge axis from the ridge line itself.
- Give each section its own plate, and per-side pitches when the drawing shows them.
- Check each ridge height against the photos.
- Run a lower wing into the taller roof so that valleys form.
- The prompt spells out how to read a roof plan: eaves, dashed walls, ridges, hips, valleys and gable brackets.

**Extensions and photos**
- Awnings are extensions, and `brackets` is an integer.
- Photos confirm the front, the roof forms and the look. They never give a dimension.

**Output**
- The prompt states the budget: the whole reply fits in 64000 tokens, so stop reasoning by about 45000.
- The JSON is compact. The first character is `{` and the last is `}`.

### 2b. The roof check (added 2026-11-08 after the user's review of the acceptance renders)

The whole-building read is not consistent on roofs. On the same drawings, the spike read the main house's two-storey centre correctly: a hip with its ridge side to side and a front gable dormer. The acceptance read made the same block a big front-facing gable with no dormer, and simplified the left wing's hip to a gable.

So after the draft (and after the per-level fallback when it ran), the draft step makes one more read, `roof_check`. It checks only the roof:
- **Inputs:** the roof plan, the elevations and the photos, plus the read roof sections as JSON.
- **Answer:** corrections only (changed kind, ridge, pitch, plate or rect; added sections such as dormers and cross gables; removed sections). An empty answer means the roof is right.
- **Read settings:** medium effort, 16000 output.
- **When corrections apply:** before normalize, snap and the checks.
- **What it never touches:** a section a person edited.
- **If the read fails:** the build log says "The roof could not be double-checked; it is shown as first read." and the build carries on.
- **While it runs:** a heartbeat line, "Checking the roof of the <building name> drawings, M:SS so far."
- **Cost:** about $0.10 to $0.20 and under a minute per building, included in the estimate.

### 3. Schema additions

**Half-storey levels.**
- A storey-and-a-half area (rooms under the roof, with knee walls) is still a level: `{id, name, elevation, ceiling, outline, half: true}`.
- Its outline is the floor area inside the knee walls.
- Its knee walls are walls with `exterior: false` and their own height.
- It gets a floor and appears in the floor buttons like any other level.
- The prompt says this explicitly. The main-house read left these rooms without a floor.
- The generator draws the floor slab and the knee walls. The roof above stays the roof.

**Gable openings on either ridge axis.**
- For a gable whose ridge runs along `y`, the opening gives `x`, its centre along the plan x axis, as it does now.
- For a gable whose ridge runs along `x`, the opening gives `y`, its centre along the plan y axis. `gable: "front"` means the x0 end and `"rear"` means the x1 end.
- `twin_plan.normalize` validates the opening's span along the right axis.
- `twin_generator.js` places the window on the right end.

**Screened porch.** *My call:* a screened porch is a porch (open, with its roof), not an enclosed room. That matches what the read did. A person can still draw walls on it in the editor.

### 4. The rooms read

- One read per building, after the draft settles.
- **Inputs:** the floor pages (whole, at the same sizes) plus the settled draft as JSON: levels, exterior walls and openings.
- **It asks for**, in the same frame and in feet:
  - rooms (`{name, level, polygon}`);
  - interior walls (`exterior: false`).
- Medium effort, 32000 output.
- A piece outside its level's outline becomes a ghost with a why.
- *This read was not tested in the spikes.* There is no hand key for rooms, so *my call* is that the acceptance run (section 8) measures it with these checks:
  - every room name printed on a floor page falls inside the polygon of the room with that name;
  - room polygons overlap by less than 1 sq ft;
  - room polygons cover at least 85% of their level's outline.
- If it fails, the rooms fix is planned then, as its own change. No crop fallback is built ahead of time.

### 5. Checks, ghosts and the per-level fallback

After normalize, the draft is checked before anything settles:
- Each level's exterior walls close, with no open end wider than 0.1 ft.
- Every upper level lies inside the level below, with up to 2 ft allowed for cantilevers.
- Every upper level's enclosed area is at least 20% of the level below.
- Every roof section's rect lies within 3 ft of the walls it bears on.
- Every opening lies within its wall's span and below its wall's height.
- The L1 outline agrees in size with the quick outline read, within 2 ft per side. A mismatch logs a plain line, and the draft wins, because it reads dimensions.

What a failure does:
- A piece that fails becomes a ghost with a plain why, for example "The upper floor's walls do not close at the rear left corner." The rest settle.
- Nothing pauses unless the whole first floor fails. Then the build pauses with "The drawings could not be read as one building" and offers Try again.

**Per-level fallback.** It runs when the draft is cut off at the output limit, or when the first floor fails. The build then reads each level on its own, with the same prompt rules, in this order:
1. The first floor.
2. Each upper level, given the settled first floor as JSON.
3. The roof, given all the levels.

Each of these is a medium read with 32000 output.

*My call:* this is the only fallback. The old crop pipeline is not a fallback.

### 6. Progress and the latency targets

- The quick outline ghost meets the 30 s first-ghost target.
- While the draft reads, the build log gets a plain line at least every 15 s, naming what is being read and the elapsed time: "Reading the Main house drawings as one set, 1:45 so far."
  - *My call:* elapsed time rather than a made-up percentage, because the read gives no progress signal.
- Buildings in the place chain still build one after another. Within a building, only the quick outline read and the draft overlap (section 1).

### 6a. Joints: everything meets

The user's ruling after seeing the main-house render (2026-11-08): what stands out most is the seams. You can see through to the inside, and walls poke through the roof. Being accurate to the inch matters less than everything meeting up and fitting together like a real building. So joints come first: when a measured position and a clean joint disagree by a small amount, the joint wins.

**Causes found in the code (the main-house draft, `plan5.json`, and `static/twin/twin_generator.js`):**

1. **Ground-floor walls never reach the roof.** They stop at their ceiling height (10 ft), but the one-storey roofs bear at plate 10.9. That leaves a 0.9 ft open band under every one-storey eave. Ground-floor walls are only fitted to the roof when they own a gable end (`clipRoof = gables.length > 0 || w.level !== first.id`). A wall's top is never raised to meet a roof above it: `top = min(height, roof)`.
2. **Ground-floor walls are never trimmed to the roof either.** Where a lower roof crosses a ground-floor wall (porch roofs, wing junctions), the wall pokes through.
3. **Walls sit on the wrong side of the line, and their corners are open.** The read puts the outside face of each wall on the line. The generator centres the wall on that line instead, so half of every wall stands outside the house and out from under the roof edge. Each wall is also square-ended, so every outside corner is missing a small square notch.
4. **Roof sections meet in steps with nothing filling them.** Each section is its own rectangle, and the roof shown is the highest one at each point. Where a section ends and a lower neighbour carries on, the roof drops in a vertical step with open air under it. Only gable triangles get filled.
5. **The roof has no thickness and no edge trim** except on extensions. At the eaves and rakes you see under it into the house.

**The awning (the pool house window, and the garage bay window on the main house):**

The awning code has been wrong since slice 1, which is why that piece of roof always looks off.

- It slopes the wrong way. A node check of the generator's own maths on the pool-house awning gives 8.90 ft at the wall and 9.56 ft at the outer edge, so the awning rises as it leaves the wall. The read means `eave` as the low outer edge, but the code puts the wall side at `eave`.
- It can only hang from the front edge (`y0`) of the section it names, never from the wall it actually shelters. On the main house that wall is the garage bay, which projects 1 ft in front of the wall line. So the awning sits on the wrong plane and at the wrong depth.

**The fix, in three layers:**

1. **Snap pass, in Python, after normalize and before anything settles** (`twin_plan`, run on every draft, every fallback read and every edit). It moves pieces by at most the tolerances below and logs what it moved.
   - Wall ends within 1 ft weld into one shared corner.
   - Walls within 3 degrees of square or of straight are made square or straight.
   - Coordinates round to the nearest inch.
   - An upper floor's walls within 1 ft of a wall line on the floor below snap onto that line.
   - Each roof section's rect edges snap to the wall lines they bear on, within 1.5 ft.
   - A section's plate snaps to the top of the walls under its eaves, within 1.5 ft. When two sections meet, a plate within 0.5 ft of the other's is made equal to it.
   - An awning is attached to the exterior wall under its span, found by geometry, wherever that wall faces. It slopes down and away from that wall.
2. **Generator rules, so every plan joins, including one a person edited:**
   - Every exterior wall on every level meets the roof above it. It is raised to the roof's underside where the roof is higher and trimmed where the roof is lower. A floor's ceiling height only sets the interior ceiling.
   - Walls are drawn inside the outline, with their outside face on the line, and corners are filled so they close.
   - Wherever the roof steps between sections, the vertical face is filled with siding, the same way gable ends are.
   - The roof gets thickness, a fascia along the eaves, rake trim along gable edges, and a soffit under each overhang.
   - An awning hangs from its wall's outside face. Its high edge is at the wall and its low edge is at `eave` (with the plate side clamped below the floor above). Its brackets sit under it on the wall.
3. **A joint check, in the tests and in the build log.** A geometry pass with no renderer reports each of these:
   - gaps over 1 inch between a wall top and the roof;
   - open corners;
   - roof steps with nothing filling them;
   - walls above the roof.

   A built house should report none. A remaining one is named in the log in plain words.

The read prompt also gets one line: when a drawing is ambiguous, prefer the reading where walls, floors and roofs meet.

### 7. Rebuilds and a person's edits

- The draft's pieces go through the existing `_merge_list`, so a person's moved, deleted or added pieces survive a rebuild.
- **Matching** uses each piece's original read position (`read_geometry`), not its current position. Every piece a person moved is matched on it, not only protected ones. A wall a person moved is then not duplicated when the same wall is read again. This closes the v2.499.767 review finding.
- A building a person placed is never moved by `fit`. A rename never counts as a person placing the building, so a renamed building is still refit. This closes the parked rename finding.

**Buildings already built by the old pipeline.** The old frame differs: its origin is the bottom-left of the traced outline's pixel box, it has +y up the sheet, and it sometimes included the porch. *My call:* on the first draft build of such a building, keep what a person did instead of starting fresh:
1. Fit the old L1 outline to the draft's L1 outline (a similarity fit, enclosed walls only).
2. Map every person-added, person-moved and person-deleted piece through that fit before the merge.
3. Adjust a person-placed building's lot transform by the same fit, so the building stays where the person put it.
4. If the fit is poor (RMS over 2 ft), keep the person pieces as they are and log one plain line saying they may need moving.

Old levels map to new levels by elevation order.

### 8. Tests and acceptance

**Unit tests** (stub reader keyed by step)
- For a drawn building, `plan_steps` gives `outline:L1`, `draft`, `rooms`, `finishes`, `fit`, `compose`.
- The outline ghost never settles.
- The draft settles all its pieces at once.
- Each check failure becomes a ghost with its why.
- A cut-off draft runs the per-level fallback.
- Lenient parse cases: fences, leading text, one trailing brace. A refusal case: two objects.
- A half-storey level renders a floor.
- A ridge-x gable opening validates, and a ridge-y one still does.
- A person-moved wall is not duplicated on rebuild.
- Heartbeat lines come every 15 s, tested with a fake clock.
- Page anchors give a registration for every drawn floor, including an upper floor. The Sheet tool's overlay data exists for L2.
- The outline side read draws a ghost and is dropped when it fails or lands late. The checkpoint sees the combined estimate.
- An old-pipeline building with a person-moved wall and a person placement keeps both after its first draft build. A poor fit leaves them as they were and logs the line.

- Snap pass: two walls whose ends are 0.8 ft apart weld into one corner; a roof rect 1.2 ft off its wall line snaps onto it; a plate 0.9 ft above its wall top snaps to it; nothing moves more than its tolerance.
- Joint check on the main-house and pool-house replays: no gap between a wall top and the roof, no open corners, no unfilled roof steps, no wall above the roof.
- Awning: its edge at the wall is higher than its outer edge, and the outer edge is at `eave`. An awning over a wall that projects in front of its section's edge hangs from that wall. A side-facing awning hangs from its side wall.

**Replay**
- One recorded draft answer per building of this household, recorded once with the product prompt, within $2.
- Each runs through normalize and the checks, and must meet these tolerances:
  - **Pool house:** L1 31 x 22 within 0.25 ft; L2 offset within 0.25 ft.
  - **Main house:** L1 70 x 66.3 within 0.5 ft; every wing's front y within 0.5 ft; upper walls closed; the centre front gable present.

**Live**
- The editor builds a stubbed building: the outline ghost appears, then the draft settles.
- The floor buttons show a half-storey level.

**Acceptance before ship**
1. A local rebuild of the whole place with real reads, under $5 and 30 min, with the renders compared against the six photos from all four sides.
2. The device run (slice 1b-i Task 19).

## Left to the builder

- Image sizing and ordering details beyond what is above.
- How the heartbeat timer is driven: a thread, or the read's own timeout loop.
- The exact wording of ghost whys and log lines, following the plain-sentence rule.
- Where the prompt text lives. The default is a constant in `twin_reads.py`, like the other kinds.

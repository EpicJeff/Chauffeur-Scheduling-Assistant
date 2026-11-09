# House editor: roofs from blocks and photos

Status: design, awaiting approval. Date 2026-11-08.

This replaces how a drawn building's roof is produced in the whole-building draft. The `draft` read's roof sections and the roof check stop deciding the roof form. Everything else stays: walls, levels, openings, rooms, porches, the first look, the heartbeat, anchors, the fallback and the joints. The previous spec is `2026-11-08-house-editor-whole-building-draft-design.md`, and the drawing conventions are in `2026-11-08-plan-reading-conventions.md`.

## Why

The magic of the house editor is generating the house from plans and photos. Without that, it is a worse Live Home 3D. The household's main house showed exactly where generation fails.

- **Walls, floors and dimensions come out within inches** on every read, because they come from printed dimension strings.
- **Roof forms come out differently on every read.** Over two acceptance builds and three spike rounds, the same blocks were read as front gables, side gables, hips and a pyramid.
- **The roof plan is ambiguous evidence.** The household's sheet draws small centred triangles at three ridge ends. By drafting convention these are clipped gables (half-hips), but the house was built with plain gables. The sheet is stamped "changes may have been made during construction".
- **Photos show what was built.** Asking the model what it *sees* in the photos, per block and per side, and deriving the roof form in code, got every main block right, identically across three runs (spike rounds 2 and 3, about $0.08 per read). Asking it to *infer* the roof form from the plan stayed wrong even with the convention spelled out.

So roofs are built the way design tools build them. Code splits each storey's footprint into blocks. Each block gets a roof form from a few observed facts, and code builds the roof over the block. The roof fits the walls by construction.

## Ground truth this must reproduce (the household's main house, confirmed by the user)

- There are no hips anywhere.
- **Middle two-storey block:** side gable (ridge parallel to the street), gable end on its left, front gable dormer over the upper windows (centred about 30 ft, about 15 ft wide). Its right end meets the right upper block.
- **Left wing:** side gable with the gable end facing left (two upper windows in it), ridge parallel to the street.
- **Right upper block:** side gable, ridge parallel to the street.
- **Right front (garage wing):** tall front-facing gable, ridge perpendicular to the street, with the awning.
- **Third garage, far right:** its own small roof with the gable end facing the right side, ridge parallel to the street (photo 26).
- **One long ridge line.** The left wing, the middle block and the right upper block share one ridge line running left to right (user, 2026-11-08). The middle block is raised one storey and has a LOWER slope than the wings: one ridge over its whole depth, not front and back roofs.
- **At the rear,** a separate lower-slope roof sits between the two gables that jut out (the screened porch and the keeping room).
- **Photos:** front 22 (21 is the same), right side 26, left side 23 and rear 20. These are the four photos on the device.

## Goals

- Every roof form in the ground truth above comes out right on a fresh build, with no person input.
- Roof forms are decided by what the photos show. The plan is a fallback, read by the documented conventions.
- A roof side that no photo shows clearly is flagged for a one-tap check. It is never silently guessed.
- Roof heights look right: no ridge far above what the photos show.
- The cost stays under $5 and the time under 30 minutes for the whole place, as before.

## Non-goals

- Curved, mansard, gambrel or complex hip-valley roofs beyond hip, gable, shed, flat and half-hip (clipped gable).
- Buildings with no photos are not a goal to get right. *My call:* they take the same block derivation fed only plan evidence (ridge direction, pitch, dormers). Every end defaults to a gable and is flagged. `roof_check` is retired everywhere.
- Changing walls, rooms or openings.

## Design

### 1. Blocks from the walls (code)

From the settled draft's levels and exterior walls, code splits each storey's outline into rectangular blocks:
- coordinates within 0.5 ft snap together;
- it uses the fewest rectangles, preferring large ones;
- slivers narrower than 7 ft merge into a neighbour.

**Upper blocks** are the upper storey's outline. **Lower blocks** are the parts of the ground floor not under an upper block. Knee-wall rooms (storey-and-a-half) stay inside the lower block beneath them, because their roof is that block's roof.

Each block has an id, a rect in feet and a storey. Blocks are recomputed on every build. A person's roof choice is attached to the block by geometry, so it survives a rebuild (see §6).

### 2. Which photo shows which block (model, constrained)

For each photo tagged to the building, one cheap read gets the block diagram (a top view with block letters and the street side marked) and the photo. It answers:
- which side of the house the photo was taken from;
- which blocks appear, left to right;
- which sides of each block are visible: front, rear, left or right.

Low effort, small output. This replaces the hand-placed letters of the spike.

*Builder's choice:* fold this into the observation read (§3) if one read does both reliably. Spike it first.

All tagged photos are used. If there are more than 8, pick the photos that together show the most block sides, never the first N by tag order.

### 3. Observation questions (model, constrained)

One read, medium effort, gets the block diagram, the photos and the photo-to-block map. For each block and each side (front, rear, left, right) it reports exactly one of:
- `gable_end`: a triangular wall;
- `clipped_gable_end`: a triangular wall with its top cut by a small sloped roof;
- `dormer`: a front-facing triangle on a sloped side, with its rough centre and width;
- `slope`: the roof slopes down to the eave on that side;
- `hidden`.

It also gives a rough pitch per block (in 12ths), says whether a block's slope looks lower than, about the same as, or steeper than its neighbours', and says which photo it judged each side from.

The answer is checked in code. A side reported differently by two photos is `conflict` and is flagged.

### 4. Deriving the roof form (code)

Code applies one principle to every end of every block:
- an end seen as a triangle is a gable end;
- an end seen as a clipped triangle is a half-hip;
- an end seen sloping is a hipped end;
- an end not seen is a gable end and is flagged.

The ridge runs between the two ends that are gable or half-hip ends. A front or rear seen sloping with no end visible implies the ridge runs parallel to that side.

**Mixed ends are in scope.** A section can have one gable end and one hipped or clipped end. The schema gets a per-end field, `ends: {<end>: 'gable'|'hip'|'clip'}`, which the generator, `twin_plan` and the roof card all use.

*My call:* the cases below are worked examples of the principle, not a separate rule list.

Per block:
- **Gable ends on left and right:** a gable with its ridge parallel to the street. **Gable ends on front and rear:** a gable with its ridge perpendicular.
- **A clipped gable end** makes the same gable with a half-hip at that end.
- **Slopes on all four sides:** a hip. Its ridge runs along the long side unless the plan's ridge line says otherwise.
- **Gable ends on exactly one side,** with the opposite side hidden: a gable with the ridge through that side. The hidden end is assumed a gable end and **flagged**.
- **A dormer on a sloped side** becomes a cross gable section. Its rect spans the dormer's width over that side, from the eave back to the main ridge, and its plate is the block's plate.
- **Front and rear both sloped and both ends hidden:** the ridge direction comes from the plan (§5). If the plan gives none, it runs along the long side. Both ends are flagged.
- **A block under a higher block** that the photos never show gets the form its neighbour implies, and is flagged.

The plate comes from the block's storey: ground-floor ceiling or upper-floor ceiling plus framing. The roof sections are written into the plan in the existing schema (`kind`, `ridge`, `rect`, `plate`, `pitch`, half-hip as a new `clip` field on a gable end).

### 5. The plan as fallback (model, read by the conventions)

The draft read keeps reading the roof plan, but by the documented rules in `2026-11-08-plan-reading-conventions.md` §1.6. Its roof sections become *evidence*, not the roof:
- the ridge direction per block (the plan is reliable for this);
- the pitch from the pitch triangles;
- clipped-gable marks;
- dormer positions.

The plan decides only the ridge direction, the pitch and the dormer position. *My call, from the spike:* the plan read called the household's built gables hips even with the convention spelled out. The roof kind and any clip come only from the photos, or from the gable default when an end is unseen and flagged. Where a photo has shown a side, the photo decides.

### 6. Flags and the one-tap check

Any side that is `hidden`, `conflict` or from the drawings only becomes a roof flag on that block.
- **In the build log:** one plain line, for example "The roof over the third garage: its right end was not visible in the photos; I made it a gable."
- **In the editor:** the block's roof gets a "needs a look" marker. Tapping it opens the existing roof card, with the choices in plain words: gable or hip; ridge along the street or across it; which end is a gable.
- **Person edits on the roof card become block choices.** *My call.* A person's change to a derived section on the roof card (kind, ridge, ends, pitch, plate or overhang) is stored as a choice on its block. A person's change to a dormer or another added section stays a person section, kept by `_merge_list` as today.
- **Existing buildings keep their roof edits.** When a building built before this change is first rebuilt, any roof section a person already edited is kept as a person section, and its block takes that section's form as its choice.
- **Person choices are kept.** A choice is stored on the block by geometry (the block's rect within 1 ft) as a person's roof choice. Every rebuild applies it before deriving anything else, and it is never flagged again.

### 7. Heights

- **Pitch, in order of preference:** the plan's pitch triangle for that roof; the elevation sheets; the photo estimate from §3. Clamp to 3 to 14 in 12.
- **Ridge alignment.** Adjacent side-gable blocks in a row whose ridges run parallel share one ridge line in plan (the same y), the way the household's left wing, middle and right upper blocks do. A raised block in the row keeps that ridge line, and its lower slope comes from its own pitch.
- **Lower slope on a raised deep block.** When the photos say a block's slope is lower than its neighbours', its pitch comes from the plan's triangle or the photo estimate, never from the neighbours. The household's middle block, 38 ft deep, is one ridge at a lower pitch.
- **Deep blocks.** A deep block with a side ridge whose ridge would come out more than 1.5 storeys above its plate, against what the photos show, is split into front and rear sections that meet in a valley. This happens only when the photos show two ridges (a `slope` front and rear with a visible valley). Otherwise the photo pitch is used, which keeps the ridge in line with the photo.
- **Ridge check.** A ridge more than 6 ft above any neighbouring block's ridge, where the photos show them about level, is flagged.

### 8. What happens to the existing roof steps

- **`roof_check`** is retired for all buildings. The observation read replaces it.
- **`roof_issues`** stays, as a final consistency check whose leftovers are logged.
- **Draft roof extensions** (awnings) and **porch roofs** stay as read.
- **Cost:** the photo map (§2) is about $0.02 per photo. The observation read (§3) is about $0.08 per building. Both are included in the estimate.

## Acceptance

- **Recordings:** record the household's main house once with the four device photos.
- **Replay test:** every ground-truth line above comes out right, with no person input, and the third garage's ridge is parallel to the street.
- **Dormer:** within 1 ft of centre about 30 ft and width about 15 ft. *My call:* the dormer snaps to the upper floor's wall jog or the plan's position when one is within 2 ft.
- **One ridge line:** the left wing, middle and right upper ridges share one line in plan, and the middle block's pitch is lower than the wings'.
- **Determinism:** across 3 recorded runs, every block's form is identical.
- **Real local build:** a build of both buildings with real reads, under $5, rendered from four sides and compared with the photos.
- **Pool house:** still matches its photo; it is a simple gable with a shed porch.

## Left to the builder

- Whether §2 folds into §3.
- The exact block-diagram rendering.
- How the flag marker looks in the editor (it must reuse the existing ghost and needs-checking visuals and the roof card).
- How the deep-block split is detected beyond the rule above.

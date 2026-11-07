# The house editor: design

Status: draft for review, 2026-11-07. Amends `docs/superpowers/specs/2026-11-06-house-digital-twin-design.md` (the twin design): this document replaces that design's drafting pipeline (§8.1, §8.2) and its phase P1. Everything else in the twin design (what the twin is for, the live layer, idle mode, rendering tiers, the asset library, the cost ledger) stands.

## 1. Intent and why

The twin design decided what the House is: a digital twin of the real house and lot that is the wall panel's way into Home Assistant. P0 (v2.499.763, hidden at `/house/twin`) tried to produce that twin in one shot: a model read every drawing sheet in a single request and returned a whole plan file, and a parent fixed what it got wrong in a JSON text box.

The first live run (2026-11-06, 13 rounds, $7.48 on the ledger) showed that this cannot reach the main house:

- Gemini put one giant gable on posts over the whole main house, offset the upper floor from the lower, and placed the pool house and pool in the wrong orientation. Claude drew only the pool house and ignored the main house sheets; its art director runs often failed.
- The causes are mostly in the plan format, not the models. A roof could only be one rectangular gable with extensions (shaped around the pool house), and the main house is mostly hips with valleys. A building could be placed on the lot but not rotated. Each floor was read from its own sheet with nothing tying the sheets to one frame.
- A JSON text box is not a way for a person to fix a house.

The user's direction (2026-11-07): build it **section by section, watching the model build it**, new pieces appearing as ghosts and turning solid when settled, and build it as **an agent-driven 3D home design application that happens to run in a browser**, not as a tool in an admin page. This is **the house editor: everything about the house is done here.** It is built as a platform other households will install, and most people have never used a 3D program.

## 2. Who uses it and where

- A parent, on a desktop or tablet browser (designer's call: the parents tier, the same as P0's twin routes). Not the wall panel: the panel only shows the finished twin. Not the Pi 5's render budget; the editor can assume a desktop or tablet GPU.
- Other households are the target audience: no 3D experience assumed, and whatever house documents they happen to have.
- Argyle is the designer. The person watches, answers, and fixes.

## 3. Goals, non-goals, anti-goals

**Goals**
- A recognisable twin of a real house built from scratch in a reasonable time, for a reasonable cost, and pleasant to watch and use (targets in §11).
- One editor for everything about the house: building it from documents, fixing it, and later placing devices, furniture and yard, and trying out changes.
- Usable by someone who has never opened a 3D app.
- Works from whatever a household has, from architect sheets down to nothing at all (§5).

**Non-goals**
- A CAD or modelling program. No free 3D handles, no vertex editing, no arbitrary geometry.
- Editing on the wall panel.
- Photoreal output in the editor; the editor renders at the High tier at most.

**Anti-goals** (a failure even if it works)
- An interface that needs 3D experience to fix a wall.
- Spend that happens without being visible.
- Argyle changing the house without showing what it changed.
- Losing work: a stopped build, a bad edit or a closed tab must never cost what was already settled.

## 4. Decisions already made (by the user, 2026-11-06 and 2026-11-07)

- The house is built piece by piece. New pieces appear as ghosts and turn solid as they are settled. Mostly the person just watches: it is "a really cool progress bar".
- The build stops only where a mistake would carry into everything after it (the user agreed): **scale and footprint of the first floor**, **each upper level's alignment**, and **the house's placement and orientation on the lot**. Everything else streams through and is fixed afterwards.
- Roofs are several sections, read from the roof plan. **Pitches are estimated from photos, and the person can adjust them afterwards** (the user knows the real pitches).
- The format must allow for elevation changes (terraces, slopes, retaining walls), because the user's own yard has them and other yards will. Drawing terrain can come later, provided adding it later does not force rework.
- The main house goes through the new approach first, not the pool house.
- It is the house editor: everything about the house happens here. Build a real tool that can do everything rather than hoping automation removes the need for one.
- Built for other households: no 3D experience assumed.
- The look shown in the mockup (§6) is the direction: full-screen 3D scene, Argyle's panel, a tool rail, a floor stack, a timeline.

## 5. What a household starts from

The same editor accepts four starting points, best first. A weaker start means more nudging, never a different tool.

1. **Architect or builder sheets** (like the user's `Reference Plans Lot 58.pdf`: main floor, upper floor with the main floor dashed underneath, roof plan with a small bonus level; and the plot plans). The full automatic build with the three pauses.
2. **A marketing floor plan image** (builder brochure, listing plan), often with few or no dimensions. Argyle traces rooms; one known dimension sets the scale.
3. **A phone LiDAR scan** (later). Measured room shapes import into the same format.
4. **Nothing.** The person draws rooms in plan view or describes them to Argyle ("living room about 16 by 20, kitchen to the left"); photos fill the exterior.

Photos are always welcome and always win where they disagree with drawings (the user's sheets are stamped "changes may have been made during construction").

## 6. What the person sees

The mockup is `.superpowers/brainstorm/1967-1793993307/content/design-app-v1.html` (git-ignored; a screenshot belongs in the plan).

- **The 3D scene fills the screen.** Drawing sheets lie on the ground as an underlay in their registered place; the built house stands on them. Ghosts are translucent with a dashed edge; settled pieces are solid.
- **Argyle's panel** (right): a compact log of finished steps ("Main floor: 70'-0" by 65'-4", 41 walls, 26 openings, 14 rooms"), Argyle's messages where it is unsure or needs the person, quick replies, and a text or voice input. The person can say "shift it a foot toward the street" or "the roof is 8/12".
- **The tool rail** (left): select, move, rotate, pin two points, measure, show the sheet, cut away upper floors. **Plan view**, one button, flips to a flat top-down view of one floor: this is the point-and-click editor most people will use. 3D is for looking and checking.
- **The floor stack** (scene's top right): Roof, Bonus, Upper, Main, Lot; show, hide or isolate each.
- **Piece cards:** tap anything to get a card next to it with plain fields (width, height, pitch, room name, HA area, later the HA device) and "Ask Argyle about this". Advanced fields (roof section geometry) are folded away.
- **Camera presets:** Top, Front, Back, Orbit. Nobody has to learn to fly a camera.
- **The timeline** (bottom): every build step and every edit in order, with the running cost. Dragging it back replays the build for viewing. It is the undo history and replaces P0's rounds list. (Designer's call) History is append-only snapshots, as P0's rounds are: returning to an earlier step restores that state as a **new** entry, so nothing later is ever lost and the person can return forward again. Edits always apply to the latest state. Nothing re-runs automatically: re-reading a step is the person's explicit act and shows its cost. Fixing a registration on the latest state moves every piece read from that sheet (§7.3); that is an edit, not a rewind.
- **Pauses** show the ghost over its sheet with a card: what Argyle read, how sure it is and why ("the stamp hides the corner by the stair"), and Looks right, Drag, Pin two points, Re-read (with its cost).

Interaction rules that keep it usable without 3D experience:
- Dragging always slides along the floor or the ground. Heights, pitches and elevations are numbers on a card, never a vertical drag.
- Walls snap to walls and to right angles; openings snap along walls; later, devices snap to walls and ceilings.
- The words are plain: no "mesh", "extrude", "gizmo", "vertex" anywhere a person can read them.
- Every Argyle capability has a hand path (repo rule), and every hand edit is something Argyle can see and explain.

## 7. The build

### 7.1 Order (the main house from sheets)

1. **Sort the sheets.** Argyle suggests a role for each page (floor plan for a named level, roof plan, plot plan, elevation, other); the person confirms or changes it. Mixed sheets are allowed: the user's roof sheet also carries the bonus level.
2. **Register the first floor sheet: scale and footprint.** Argyle reads an overall dimension (70'-0") to set scale and traces the exterior outline as a ghost over the sheet. **Pause 1.**
3. **Main floor, wing by wing:** walls, then doors and windows, then rooms with names (HA area names offered where drawings leave rooms unlabelled).
4. **Register each upper level** (upper floor, bonus) against the level below: where the sheet draws the lower floor dashed, that outline is the match. **Pause 2** for each. Then its walls, openings and rooms.
5. **Roof, section by section** from the roof plan: hips, gables, sheds, valleys where sections meet. Pitches are estimated from the photos; the card shows "estimated from photos" until the person sets a value.
6. **Place on the lot** from the plot plan: read the lot, find the street edge, fit and rotate each building onto its outline. **Pause 3.** Then the pool, patio, fire pit and retaining wall.
7. **Finishes:** materials and colours from photos (the P0 finishes stage), composed planting (P0's composition rules), then the art director (P0's loop) if the person runs it.

### 7.2 Pieces, ghosts and settling

- Each step is one small, metered model request carrying only the part of the sheet it needs (a cropped region at full resolution, not the whole page downscaled). This works within each provider's image limits (the likely reason Claude dropped the main house) and makes a failure local and obvious.
- A step's result is a set of **pieces**. Pieces enter as ghosts and settle when the step's checks pass (they validate against the plan schema and fit what is already settled) or when the person accepts a pause. A piece that fails checks stays a ghost with a reason, and Argyle says so.
- Every settled piece is saved as soon as it settles. A build stopped at a spend checkpoint, a closed tab or a failed request resumes from the last settled piece without paying again.
- The person can grab a ghost at any time, not only at pauses. Accepting a pause also teaches the next steps (the registration it fixes is used by everything read from that sheet).

### 7.3 Registration: why floors will line up

Every sheet gets a **registration**: scale, rotation and offset from sheet pixels into the building's one frame. Pieces read from a sheet are stored in the building's frame through that sheet's registration. Pause 1 registers the first floor sheet (scale from a known dimension, footprint as the anchor); pause 2 registers each further sheet against what is settled (the dashed outline, the stair, two pinned points). Fixing a registration moves every piece read from that sheet together. This is the fix for "floors don't line up": alignment is decided once per sheet, explicitly, and shown.

### 7.4 Argyle's role

- Argyle drives the build and talks: it narrates the start of each stage, asks when unsure, answers questions about the house, and takes edits in words ("make the patio bigger", "the roof is 8/12", "re-read the stair").
- Argyle is Argyle (the repo's one agent stack: `services/agent_router.py` plus the registry in `services/agent_tools_v2.py`), with new house-editor tools added once. Not a separate agent.
- (Designer's call) Narration for routine steps is written from the step's results without a model call; model turns are spent on pauses, questions, and what the person says. Reading drawings uses the strong (twin) model; conversation can use the household's normal agent model.

## 8. The plan format: what changes

The twin plan file stays the single source of truth; the generator stays deterministic. Changes:

- **Roof sections.** A building's roof is a list of sections, each with a kind (hip, gable, shed, flat), a footprint, ridge direction, pitch (per side where it differs), plate height and overhang. Valleys and hips where sections meet are derived by the generator, not stored. Each pitch records its source: drawn, estimated from photos, or set by a person. P0's single-gable form remains readable (it becomes one section) so the pool house keeps working.
- **Building transform.** Each building has a position, a **rotation** (any angle; quarter turns are the snap points) and a base floor height above the site's reference.
- **Sheet registrations** (§7.3), stored with the sources.
- **Elevation, reserved now, drawn later.** The site gets an optional list of terraces (flat areas at a height, joined by slopes or retaining walls); every site item can carry its own height. The view and the composition code ask one shared "how high is the ground here" function for everything that touches the ground; for now it answers flat ground everywhere. Drawing and reading terraces is a later slice that plugs into that function only.
- **Piece state.** Every item carries a stable id, its state (ghost or settled), where it came from (which sheet and step, or which person), and, for model reads, a confidence and a reason when low.
- **Devices, reserved:** the twin design's device placement block stays as designed; the editor fills it in a later slice.

## 9. Cost, sessions and safety

- Everything spent in the editor, reading and conversation alike, goes through P0's ledger (`services/twin_cost.py`): stops at $10, $20, $30 and $40 that need a parent's Continue, and the hard stop at $50 (the user's ruling, unchanged). The running total is always visible in the editor's top bar. Each household brings its own model key, so this is a product feature, not only a safeguard.
- **Development spend (the user, 2026-11-07): the $50 covers everything.** Building slice 1, tuning included, and the final measured run all fit in what is left of the household's $50 (the ledger shows $7.48 spent in the live run). Tests replay recorded model answers so that few live reads are needed; a live read is spent only to record or to measure.
- A parent reset of the lifetime total ships as a feature for other households (a parent's explicit act, recorded), but it is not used to extend this project's budget.
- **Start over** exists: it clears the house, the build history and the uploaded sources, keeps the spend ledger, and asks with the app's own confirm sheet first. (Found in the live run: there was no way back to an empty house.)
- **Long sessions under HA ingress:** HA signs an ingress tab out after about 15 quiet minutes and answers with a plain-text 401 (found in the live run). The editor keeps its session alive while open and, if HA signs it out anyway, says so plainly with what to do instead of a raw error.
- The editor is a parents tier surface; every new route gets its rule in `services/auth.py`.

## 10. What happens to P0

Kept and extended: the plan format (§8), the generator (hip roofs, sections, rotation, ghost rendering without `transmission`), the yard and composition, render tiers, the library and kit, the cost ledger, sources and photo handling, the finishes stage, the art director, the perf probe, and `/house/twin` as the panel's view of the finished twin.

Replaced: the one-shot three-stage draft (by the step-by-step build) and P0's parent tools sheet (upload, page roles, Draft, art director, rounds, JSON editor) by the editor. Every one of those actions has a place in the editor, so nothing a person can do is lost; the sheet is retired only when the editor covers all of it (repo rule: nothing a person can do is removed without approval, and the user has said "you do everything here").

## 11. How we know slice 1 worked (agreed 2026-11-07, "for now")

Measured on the user's main house from `Reference Plans Lot 58.pdf`, the plot plans and the household photos:
- **Recognisable:** someone in the family identifies the front, back and both sides without being told. Floors line up; the roof matches the roof plan; windows and doors are where they are, within about a foot.
- **Time:** under 30 minutes from upload to a recognisable shell, pauses included, of which no more than 10 minutes is hand fixing.
- **Cost:** under $5 for the main house, from sheets to a finished shell with roof, placed on the lot.
- **Feel:** the first ghost within 30 seconds; never more than about 20 seconds without visible progress; every pause makes clear what Argyle wants; a person without 3D experience makes a fix unaided.

## 11a. Which model reads the drawings (the user, 2026-11-07)

Before prompts are tuned, a short comparison: Gemini and Claude each read the same three or four cropped steps from the user's sheets (the main-floor outline, one wing's walls, one roof section), capped at about $3 in total, judged on accuracy against the sheets and on cost. Slice 1 is then tuned for the winner; the other stays selectable through the provider selector but is not tuned.

## 12. Slices

1. **The main house from sheets, finished, then the pool house** (the user, 2026-11-07: once the main house passes, the pool house's complete drawings go through the same build, roughly $1-2, and both buildings are placed on the lot): the editor shell (scene, Argyle panel, tool rail, plan view, floor stack, piece cards, camera presets, timeline), the step-by-step build with the three pauses, registrations, roof sections with pitches from photos, placement and rotation on the lot with pool and hardscape, the format changes in §8 (terrain reserved, not drawn), start over, the ingress session handling, and build step 7 (finishes, composed planting, the art director) adapted to the new format (designer's call: they only touch materials and the site, so the adaptation is small, and it lets P0's tools sheet retire at the end of slice 1 instead of keeping two surfaces alive).
2. **Other starting points and the lot's shape:** marketing floor plans and drawing from nothing; terraces drawn and read from plot plans.
3. **Devices:** placing HA devices into rooms (feeds the twin's markers and modes).
4. **Furniture and yard editing** beyond the composed planting.
5. **Trying out changes** (what-ifs) and LiDAR import.

## 13. Left to the builder

- The exact schema for roof sections, registrations and piece state, and how P0 plans migrate.
- The roof generation algorithm (hip and valley geometry from sections).
- How a step chooses its crop, and how many pieces a step returns.
- How the build streams to the editor (server-sent events, polling) and how a resumed build rejoins.
- The route name and page structure of the editor, and how its conversation surface relates to the PWA's Argyle overlay.
- Ghost rendering technique within the no-`transmission` rule.

## 14. Risks

- **Model accuracy on scanned, stamped, unlabelled sheets.** Mitigation: small cropped steps, registrations, pauses, photos, and a real editor for the rest.
- **Roof geometry** for hips and valleys is the hardest generator work in the slice.
- **Agent turn cost** in a long session. Mitigation: routine narration without model calls; everything metered and visible.
- **Size.** This is a real application. Slice 1 is deliberately the main house only; later slices reuse its shell.
- **Usability without 3D experience** is a claim until a person without it tries; slice 1's feel target includes that test.

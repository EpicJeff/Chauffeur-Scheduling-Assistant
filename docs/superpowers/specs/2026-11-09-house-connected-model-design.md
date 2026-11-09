# The house as a connected system: design

Status: design, awaiting the user's approval (2026-11-09). It does not replace the 2026-11-06 twin design. It amends how that design's house is structured, edited, generated and linked to Home Assistant. The live layer described there (§5 and §6: levels of detail, markers, modes, room panel, idle mode) still stands, and this document only fixes the order it arrives in.

## 1. Intent and why

On 2026-11-09 the user ran v2.499.771 on the household and called it "really rough". Their verdict covered five areas:

- **Generation:** the left and right wing roofs are wrong, windows are wrong in several places, the third garage door is on the garage's side, the rear roof is "all sorts of weird", and a row of trees stands on the street.
- **Workflow:** nothing says what to do first or next, or whether the app is waiting on the person. A build is text in a panel until a finished house pops in.
- **Editing:** the roof errors cannot really be fixed. Faking a fix leaves one roof split into several pieces, or one section covering too much while its neighbour covers too little. Nothing shows what is selected.
- **Placement on the lot:**
  - The plot plan cannot be seen while placing.
  - The house's scale does not match the lot.
  - Dragging ignores rotation.
  - The outline does not show where the house actually ends up.
  - Moving a placed house is "virtually impossible".
- **Home Assistant:** a room's area is a free-text box, and nothing reads it. The link to Home Assistant was the reason for building the twin, and none of it exists.

The root cause is structural, not a list of bugs. Today the house is a pile of independent pieces:

- Walls are free segments that only meet because their endpoints happen to coincide.
- Rooms are polygons stored on their own, unrelated to the walls around them.
- Roofs are rectangles with a single slope.
- Placement is a separate SVG dialog.

Nothing is linked, so no edit can keep the house coherent, and every tool has to fake it.

**The principle (user, 2026-11-09):** for every part of the design, ask "how do these things fit together, and how do we design them so they form a system?" This is what makes a house editor different from a generic 3D editor.

**Prior art the user named:** Live Home 3D, where they designed the pool house.
- You draw a room and get its floor and walls.
- A room placed next to another merges the shared wall, and dragging that wall updates both rooms.
- Moving a room carries everything in it.
- Building piece by piece still joins corners automatically.
- A roof is the area it covers, which you then shape, and gables and dormers snap to the roof and always reach it.

The same ideas are standard in professional tools (Revit):
- rooms are bounded by walls;
- a "room separation line" is an invisible wall;
- doors and windows are hosted by a wall;
- a footprint roof gives each edge its own slope.

We are adopting thirty years of practice, not inventing it.

## 2. Goals, non-goals, anti-goals

**Goals**
- **One connected house model.** Generated and hand-built houses are the same thing, edited with the same tools.
- **Editing that behaves like an established 3D editor:**
  - a visible selection;
  - direct handles;
  - snapping;
  - live dimensions;
  - undo.
- **A Home Assistant link that works:**
  - rooms tied to real areas;
  - devices placed on real surfaces;
  - the live layer of the twin design.
- **A build the person is led through,** which they can watch piece by piece, stop at any time and steer.
- **Placement on the lot in the same 3D scene,** on the plot plan, at true scale.

**Non-goals**
- A general CAD or modelling tool. Placing library items (plants, furniture, fixtures) is in scope (§5.7). Modelling new shapes is not.
- Terrain (the ground stays flat, as reserved in the format).
- More AI-accuracy work before pieces 1 and 2 (§9) land. The exception is what the reader needs in order to write the new model.
- Editing on a phone. The editor targets the admin page on a desktop or tablet; the live layer targets the wall panel.

**Anti-goals** (any of these makes the work a failure even if it runs)
- A separate simplified view or tool set for something the one 3D scene can already show. A top-down view is the 3D camera looking down (user, 2026-11-09).
- A black box: a long step whose result simply appears, so nobody can tell where it went wrong.
- Spending money the person cannot stop.
- Pieces that drift apart after an edit: seams, gaps, overlapping roofs, a window left floating off its wall.
- A selection you cannot see, or a question with no way to skip it.
- A starting point hidden in a menu.

## 3. Decisions the user made (2026-11-09)

1. **One rule everywhere:** the house is a system. Every part is designed around how it connects to the others.
2. **The plan reader writes the same model a person could build by hand.** The rules of the model may also help the reader produce better output.
3. **Rooms are the spaces walls enclose,** and their floors and ceilings fill those spaces. Rooms sharing a wall share one wall: drag it and both rooms change. Open-plan spaces split with an invisible wall that behaves like any other wall.
4. **Room selection:**
   - Selecting a room highlights its floor in one colour and its walls in another.
   - Dragging a wall resizes the room.
   - Everything outside the room is ghosted and locked.
   - Moving a room moves everything in it.
5. **Everything is anchored to a wall, floor or ceiling:** doors, windows, fixtures and Home Assistant devices.
   - Dragging an item slides it along that surface.
   - Its distance off the surface can be set.
   - Dragging it onto another surface moves it to that surface.
   - On a door or window, dragging the middle moves it and dragging an edge resizes it.
   - Everything snaps.
6. **Roofs:**
   - You draw the area a roof covers, then shape it completely.
   - Each side can have its own slope.
   - Gables and dormers snap to the roof surface and extend to meet it, whatever the slope.
7. **The generation is visible:**
   - Floor outlines, walls, rooms and roofs appear in the real 3D house as they are made.
   - Any operation can be cancelled.
   - The person is led through the process and can steer it where possible.
8. **When there is no house, the empty canvas leads.** It prompts the person to start. Today you must know that Your place in a small menu is the way in.
9. **One view:** the actual 3D house. The separate 2D Plan mode is retired, and its abilities move into the scene. The user did not object when this was stated.
10. **Fixtures shown on the plans become anchors.** Where the plans show lights, switches and similar fixtures, those positions become spots on the right surfaces.
    - Devices are matched to spots in a placement flow: drag a light onto a spot, or pick a spot for each light.
    - The obvious devices place themselves: a garage door opener on its garage door, a lock on its door.
11. **Build order:**
    1. the connected model;
    2. the editor and lot placement;
    3. the Home Assistant link and live layer;
    4. the guided build.
12. **Standing rules still apply:**
    - Never drop functionality without approval first.
    - Every agent capability has a hand path; Argyle's `house_design` tool uses the same operations the editor uses.
    - No browser dialogs.
    - Every Home Assistant touchpoint degrades gracefully.
    - New settings go in `services/settings_registry.py`.
    - All UI follows `docs/ui_design_guide.md`.

## 4. The connected model (piece 1)

### 4.1 Walls form a network

**Joints.** A level holds a set of **joints**, which are points. A wall runs from one joint to another. When walls share a joint they meet: corners are joined and mitred from the network, never by luck, and the generator draws the corner from the joint.

**Moving a joint moves every wall on it.** Moving a wall moves its two joints, which stretches the walls attached to them.

**A wall's fields:**
- its two joints;
- thickness;
- height, which normally follows the level, with the roof-meeting rule from v2.499.768 kept;
- exterior or interior;
- `kind`, which is either:
  - `solid`, a wall that is drawn;
  - `separator`, which is invisible, bounds rooms, has no thickness and no mesh, and is drawn only as a dashed line while editing.

**Drawing.** A wall drawn from or to a point on an existing wall splits that wall at a new joint (a T-junction). A wall drawn over an existing wall merges with it, so there is one wall per line.

### 4.2 Rooms are what walls enclose

A room is a closed region of a level's wall network, its faces in the graph sense. The geometry is always derived from the walls; it is never stored on its own.

**What the room record keeps is its identity:**
- name;
- Home Assistant area;
- floor and ceiling finish;
- a stable id.

**After any edit, identity carries over.** Each new region inherits the identity of the old room it overlaps most:
- splitting a room keeps the identity on the larger part and asks for a name for the other;
- merging two rooms keeps the larger room's identity.

**Floors and ceilings are the room's region.** The slab under a level is the union of its rooms plus the exterior wall thickness.

**A gap that leaves a space unenclosed is a visible defect,** not a silent fallback. It is flagged on the model, where the run of walls fails to close, with the words "This room isn't closed: a wall is missing here."

### 4.3 Everything sits on a host

Doors, windows, plan fixtures and devices are all hosted.

**What each host records:**
- **A wall:** which wall, which side (for devices), the distance along the wall, and the height above the level.
- **A floor or ceiling:** which room, and a position in the room.
- **A roof surface:** used by dormers and skylights.

Each hosted item also has an `offset`, its distance off the surface.

**When a host changes, the item follows by rule:**
- **A wall that moves sideways** carries its items with it.
- **A wall that changes length** keeps each item at its distance from the end that did not move, clamped so the item stays on the wall. This is standard practice in the established editors.
- **On a floor or ceiling,** an item keeps its relative position in the room: a light centred in a room stays centred when the room grows. *(Designer's call.)*
- **An item dragged onto another surface** is re-hosted there.
- **An item whose host is deleted** becomes unhosted. It is kept, visible and flagged, never silently deleted.

**Hosts also include the ground:** the lot's ground, beds, hardscape and the pool deck. Plants, outdoor equipment (pool pumps, sprinkler valves, the mower's dock), cameras on posts and a car's parking spot sit there.

**A porch is a room bounded by separators on its open sides.** A separator may therefore lie outside the enclosed house. The porch's ceiling hosts its recessed lights, fan and heater like any room's. Its columns are items on its floor. *(Designer's call.)*

**Three kinds of hosted item:**
- **Openings:** door, window, slider, bifold, passage, garage. They keep today's fields: width, sill, head, panels, split, glass.
- **Anchors:** spots for fixtures that the plans show or a person adds, with a kind such as light, switch, outlet, fan, camera or sensor. An anchor may hold one device.
- **Devices:** a Home Assistant device id plus a host, or an anchor to sit on. A lock or a contact sensor may be hosted by the door it belongs to, so it moves when the door moves.

### 4.4 Roofs are areas with sloped edges

A roof is a polygon, its **area**, with a setting on every edge. Each edge is one of:
- **sloped,** with its own pitch;
- **gable,** a vertical end;
- **clipped,** a half-hip, with a clip height.

This is the footprint roof of the established tools. It covers every form we have met:
- a hip: every edge sloped;
- a side gable: two edges sloped, two gable;
- a shed: one edge sloped;
- any mix, including a different pitch on each side, which the user needs and the current card cannot set.

**Other roof fields:**
- plate height;
- overhang.

**The roof area is attached to the walls below it.** Each roof edge records which wall line it sits on, plus the overhang. When those walls move, the roof edge follows. A roof edge not attached to a wall (an awning, for example) stays where it was drawn.

**Dormers and cross gables are hosted on a roof surface.** Each has a width, a pitch and a ridge height. Its ridge and valleys always extend to meet the main roof plane, whatever that plane's slope or position. Porches and awnings stay their own small roofs, attached to the wall they hang from. This fixes the v2.499.768 awning that hung from its section edge instead of its wall.

**A house is several roofs, and roofs may overlap.** Each roof has one plate height, so wings at different storeys are separate roofs. Where roofs overlap, the higher surface wins. That is how two roofs meet in a valley, and how a lower roof dies into the wall of a higher storey. It is today's envelope rule, and the established tools draw roofs the same way. *(Designer's call, from the review.)*

**A roof area may be any rectilinear polygon (L, T, U).** It is solved as overlapping rectangles: `twin_blocks` already partitions outlines this way, and each rectangle inherits its outer edges' settings. The higher-surface rule then forms the valleys at inside corners without a general straight-skeleton solver. Areas with angled edges are out of scope. *(Designer's call.)*

**The existing envelope builder stays.** `twin_roof.js` already builds an upper envelope from per-plane slopes; each rectangle's sloped edges become its planes.

**Today's lists migrate as follows:**
- `lights` become light anchors.
- `fixtures` (counters, appliances) become library items on their room's floor.
- `stairs` stay their own pieces, hosted on their level's floor.
- `porches` become porch rooms.

### 4.5 Levels, buildings and the lot

**Levels stack. A wall on one level does not drag the level above it.**
- The walls below are snap targets, so exterior walls line up when the person wants them to.
- The roof-meeting rules of v2.499.768 stay.

**A building has a position and a rotation on the lot.**

**The lot also carries the plot plan,** registered at true scale so it can lie on the ground in the scene (§5.6).

**One placement exists.** What the scene shows is where the building is; no separate outline exists to disagree with it.

### 4.6 One set of operations

Every change goes through one set of model operations that keeps the model coherent:
- move a joint, move a wall, split a wall, add a wall;
- draw a room (a rectangle or a polygon); split a room with a separator;
- move a room; move a building; rotate a building;
- add, move, resize or re-host an opening, anchor or device;
- set a room's area;
- draw a roof area, set an edge, add a dormer;
- add a level;
- delete.

**After each operation the model enforces its invariants:**
- joints are welded;
- rooms are re-derived with their identity carried over;
- hosted items follow their rule;
- roof edges follow their walls;
- no two walls overlap (roofs may overlap, §4.4).

**The same operations serve three callers:**
- the editor;
- Argyle's `house_design` tool;
- the plan reader's assembly step, which builds the reader's output through the same operations so a generated house obeys the same rules.

**Live dragging must run in the browser at frame rate.** The server stays the authority on what is stored, so a drag commits on release and is checked there.
- *Left to the builder:* how the operations are shared between the browser and the server.
- *Constraint:* if they exist in two languages, one shared set of fixture cases must run against both, and a mismatch fails the tests.

### 4.6a Generation and the person's edits

**Ownership is per piece.** Any wall, joint, room, opening, roof or item that a person's operation touched is the person's. That includes the walls stretched by a joint drag. Each piece records this.

**Generation fills in and never overwrites the person's pieces.**
- **Re-running a stage** replaces the pieces nobody touched.
- **A new read that disagrees with a person's piece** is shown as a ghost beside it, with **Use this** and **Dismiss**. It is never applied silently.
- **"Stop, fix, continue" (§6) runs the later stages only,** on the model as it stands.

*(Designer's call, from the review. It keeps today's rule that `src.person` pieces are pinned.)*

### 4.7 Format, migration and history

**This is plan schema 3.**

**The household's current house migrates automatically.** Their walls, rooms, openings, roofs and person edits survive. The steps:
1. Endpoints within 1 ft weld into joints, as `twin_joints.snap` does today.
2. Walls crossing at a T are split.
3. Today's room polygons are matched to the derived regions by overlap, so names and areas carry over.
4. Openings keep their wall and position.
5. Each rectangular roof section becomes a four-edge area. Its ridge, ends and pitches convert to edge settings. A block choice becomes the person's edge settings.
6. **Stored rooms the walls don't separate get separators.** The draft reads rooms and interior walls separately, so the walls may not enclose the stored rooms. Wherever two stored rooms would fall into one region, migration adds a separator along their shared edge, and each added separator is flagged: "I added an invisible wall here to keep the kitchen and the dining room apart; check it." Names and areas are kept. *(Designer's call.)*
7. **Small roof sections marked `dormer_of` become hosted cross gables.** Other overlapping sections stay as their own roofs (§4.4).
8. **Every place the migration could not resolve becomes a flag on the model,** never a silent drop. Examples are an unclosed room, or an opening that matches no wall.

**Migration is tested on the household's real house:** the plan inside the user's 2026-11-09 build record, checked for keys before commit like the earlier recorded fixtures. The synthetic fixtures (`twin_lot58_main`: 9 walls, 1 room) are too small to prove the exit.

**History stays as rounds.** Every round is kept (`twin_store`), so the pre-migration house is always reachable on the timeline.

**Undo and redo are new.** They work per operation within a session (§5.5); the timeline stays for build rounds.

## 5. Editing (piece 2)

There is one 3D scene with camera buttons (Top, Front, Back, Orbit), the floors stack, and a cutaway of the active level.

### 5.1 Selection you can see

- **Hover** pre-highlights what a click would select.
- **Selection** draws an outline and a tint in the scene.
- **Escape** or a click on empty space deselects.
- **The property card** names the selected thing ("Kitchen", "Kitchen, east wall", "Window, kitchen east wall").

### 5.2 Rooms first

**Clicking a room's floor selects the room:**
- the floor is tinted in one colour and its walls in a second colour;
- everything outside the room is ghosted and cannot be clicked;
- the room's walls, openings, anchors and devices respond directly, with no second mode.

**Clicking outside the room steps back out** to the level.

**The building and the level can be selected too:**
- a building to move or turn it on the lot;
- a level for its height settings.

*Designer's call:* exact colours come from the UI guide's tokens, with one tint for the room and one for its walls, consistent across the editor.

### 5.3 Handles

- **A wall:** drag it across its own direction. This resizes the room and stretches the walls joined to it, so a shared wall updates both rooms.
- **A corner joint:** drag it freely.
- **A room:** drag its floor to move the room and its contents. Walls it shares stretch the neighbouring room rather than tearing away from it.
- **A door or window:** dragging the middle slides it along its wall, and dragging an edge resizes width, sill or head.
- **A device or anchor:** dragging slides it along its surface, and crossing onto a neighbouring surface re-hosts it. Its offset is set on the card.
- **A roof:**
  - drag an edge's handle to move the eave line, or to detach the edge from its wall;
  - click an edge to choose sloped, gable or clipped and to type its pitch;
  - drag a dormer along the roof surface, or drag its edges to change its width.

### 5.4 Snapping and dimensions

**Snap targets, in order:**
1. joints;
2. wall lines, and their extensions;
3. right angles;
4. plan anchors;
5. the walls of the level below;
6. a grid of 1 in.

**While dragging,** live dimensions show the distance to the neighbouring walls and the item's own size.

**Typed values:** clicking a dimension lets you type an exact value in feet and inches.

### 5.5 Drawing and other tools

**Drawing tools:**
- **Draw room:** a rectangle, or a polygon drawn click by click. It merges shared walls with the rooms beside it.
- **Draw wall:** a chain, with corners joining automatically.
- **Split room:** a separator.
- **Add door, window or anchor:** drop it on a surface.
- **Add level.**
- **Roof over this:** a roof area from the selected rooms or the building outline.
- **Draw roof area.**
- **Add dormer.**

**Undo and redo** use Ctrl+Z and Ctrl+Y and rail buttons.

**Delete.**

**Cards keep exact values,** with today's labels. The free-text Home Assistant area becomes a pick-list (§7).

**Argyle can make every one of these edits through `house_design`.**

### 5.6 Placement on the lot

**The plot plan lies on the ground in the same scene, at true scale, under the lot outline.**

**Selecting a building gives it two handles:**
- a move handle;
- a turn handle.

**Dragging is always in the building's real orientation.** What you see is where the building is.

**Footprints snap.** The building outline found by the plot read is a snap target: a building dragged close to it snaps on, and the person can still move it off.

**The street edge, footprint suggestions and nudging move into this scene.** Everything a person can do in today's Your place SVG map has a home here before that map is removed (§8).

### 5.7 The library: materials and items

This is another standard feature of 3D applications (user, 2026-11-09). Today a wrong material cannot be fixed, and no plant or piece of furniture can be added.

**One library panel** in the editor shows what the house can use, as browsable thumbnails:
- **Materials**, for example siding, roofing, trim, flooring, paving, lawn and water.
- **Items**, for example plants, furniture, fixtures and outdoor pieces.

It reads from the vetted library that already exists (`twin_library` manifest, style kits), plus anything the household adds (piece 5).

**Materials cascade, so one change fixes the whole house.** The chain is kit, then building, then level or room, then a single surface:
- A building's siding applies to every exterior wall face.
- Setting a material on one wall face, one room's floor or one roof overrides only that surface.
- Clearing an override returns the surface to the inherited material.

The card of any selected surface shows its material and where the material comes from, for example "Siding, from the building".

**Assigning a material** has two hand paths:
- drag a material from the library onto a surface;
- pick it on the card.

Either one sets the override at the level selected: the surface, the room or the building.

**Items are hosted like everything else (§4.3):**
- A plant sits on the ground or in a bed.
- A sofa sits on a room's floor.
- A sconce sits on a wall.

You drag an item from the library onto a surface, and after that it moves, snaps and re-hosts like any hosted item. An item placed in a room moves with the room. Items have a turn handle and a scale within the limits the library sets.

**The yard composer's plants and furniture become ordinary items.** A person can move, delete or add to them. A rebuild keeps the person's items and removals, as `compose_overrides` does today.

**The model never invents an asset** (twin design anti-goal): generation picks only from the library.

## 6. The guided, visible build (piece 4)

**The front door.** With no house, the canvas is empty and invites a start:
- "Let's make your house".
- "Add plans and photos", or "Draw it myself".

**The step strip.** A strip of steps is always visible: Your files, Your lot, Build, Check it, Link to Home Assistant.

**Status is always visible.** One chip always says either **Working** or **Waiting on you**, plus the spend so far and the estimate.

**Pieces appear as they are read.**
- The reader's answers stream (§8.2): each wall, room, opening, anchor and roof appears in the real house the moment it is read, as a ghost that settles.
- The step strip shows the stage: scale, outline, walls, rooms, doors and windows, fixtures, roofs, finishes, yard.

**Stop is always visible** and ends the call in flight. The person pays only for what was produced, and what already arrived is kept.

**Steering.**
- The person can stop at any stage, fix things with the editor, and continue.
- Later stages build on the model as it stands, edits included. The roofs are derived from corrected walls, for example.

**Checks come one at a time.**
- Questions and flags are shown on the model, with the thing in question highlighted.
- Each has a **Looks right**, a **Fix it** (which opens the editor on that thing) and a **Skip for now**.

**The reader is told the model's rules:**
- rooms are closed by walls;
- openings sit on walls;
- fixtures are anchors.

This tests the user's hope that the rules raise output quality.

## 7. The Home Assistant link (piece 3)

**Rooms to areas.**
- A room's area is picked from the real Home Assistant area list (`ha_api.get_area_registry`).
- The build suggests a match by name ("Kitchen" goes with `kitchen`). The suggestion is shown, not silently applied.
- An area with no room is listed so it can be placed.
- An area's HA floor (`floor_id`, via `ha_frontend.registries`) may suggest the level.

**Devices.**
- Every device in a linked area (the device registry, grouped as `services/house.py` already does) sits at an automatic spot in its room until it is placed. So the house is useful as soon as the rooms are linked.

**The placement flow, room by room.**
- The room's devices are listed beside the room's anchors.
- The person drags a device onto a spot, or picks a spot for each device.
- **Blink to identify:** tapping a light in the list flashes the real light, so the person can see which fixture it is. This uses `flash` where the light supports it, and otherwise a quick toggle that restores the earlier state.
- **Count mismatches get a plain note:** "The plan shows 5 lights; Home Assistant has 4 in this area."
- **Obvious devices place themselves**, and the person can still move them:
  - a garage door cover on the garage opening;
  - a lock on the exterior door of its area.

**The live layer**, built per the twin design §5:
- markers per device, with resting and attention states;
- levels of detail by zoom;
- the room panel;
- the Lights mode first.

The other modes (Climate, Energy, Security) follow as their own slices.

**Control, permissions and degradation.**
- Control follows the twin design §10 and its decision 8: taps on the twin are a hand path.
- With no Home Assistant, the house still renders and edits, while the area pick-list, devices and markers are absent, and nothing errors.

## 8. Keep, replace, retire

### 8.1 Kept
- The round store and timeline (`twin_store`).
- The cost ledger and spend checkpoints.
- The read infrastructure and recorded-replay tests.
- The deterministic generator, adapted to joints, derived rooms and hosts.
- The roof envelope builder (`twin_roof.js`).
- The yard and its library, the style kits and the material roles (now the top of the material cascade).
- Blocks from walls (`twin_blocks`), now seeding roof areas.
- The photo roof observation and derivation, now seeding edge settings.
- The joint snap logic, now used in migration and reader assembly.
- The Home Assistant layer (`ha_api`, `house.py`).

### 8.2 Replaced
- Free-segment walls and snap-after-edit, replaced by the wall network.
- Stored room polygons, replaced by derived rooms.
- Rectangular roof sections with ridge, ends and pitches, replaced by roof areas with edge settings.
- Today's editor tools (Move, Turn, plan_view), replaced by the editor of §5.
- The pause cards, replaced by the checks of §6.
- Blocking reads, replaced by streaming reads.
- A Stop that lets the paid read finish, replaced by a Stop that ends the call.
- Polling for build progress, though only if streaming needs it. Live pieces are the requirement, not the transport.

### 8.3 Retired once their abilities live elsewhere
- **The 2D Plan mode.** Approved: its tools move into the scene.
- **The Your place SVG map.** Its street edge, footprint suggestions and moves go into the scene (§5.6). Its building list, uploads and photo tags become the Your files step.
- **The legacy per-floor build path** (outline, registration and openings steps for buildings with no part).

### 8.4 Defects carried
The device-run errors are not fixed here by hand-tuning the reader:
- trees on the street;
- the third garage door on the wrong side;
- the wrong windows;
- the wrong wing and rear roofs.

Piece 2 makes each of them fixable by hand in a minute. Piece 4's reader work is measured against them.

## 9. Pieces and how each is proven

Each piece gets its own plan and review. Pieces 3, 4 and 5 each reach the device on their own.

**Pieces 1 and 2 reach the device together.** *(Designer's call, from the review.)* Piece 1 alone changes the format under today's editor. Shipping it alone would mean either porting the old editor and `house_design` to schema 3 and throwing that port away in piece 2, or leaving the house uneditable for a while, which the never-drop rule forbids without approval. Piece 1 is built and reviewed first and tested on the household's migrated house. The first device run is pieces 1 and 2 together.

**1. The connected model.**
- *Contents:*
  - schema 3;
  - joints and walls;
  - derived rooms;
  - hosts;
  - roof areas with edge settings and dormers;
  - the operation set with its invariants;
  - migration;
  - the generator drawing it with mitred corners;
  - the reader's current output assembled through the operations.
- *Exit:* the household's current house opens migrated, looking at least as good as on v2.499.771, with room names kept and no new seams, and every unresolved item flagged.

**2. The editor and lot placement.**
- *Contents:* everything in §5, the library of §5.7 included (materials and items from the existing library).
- *Exit:*
  - On the device, the user fixes the left and right wing roofs, the rear roof and the third garage door, and moves a window, each without faking.
  - The user places the house on the plot plan so that it matches the plot plan.

**3. The Home Assistant link and live layer.**
- *Contents:*
  - the area pick-list with match suggestions;
  - devices automatically in their rooms;
  - anchors;
  - the placement flow with blink;
  - markers;
  - the room panel;
  - the Lights mode.
- *Exit:* at the wall panel, the user taps the kitchen and sees and controls its devices, and the lights sit where they are in the house.

**4. The guided build.**
- *Contents:* everything in §6.
- *Exit:*
  - A fresh build of the pool house is watched piece by piece.
  - It is stopped once mid-way, fixed by hand and continued.
  - The spend on screen matches the ledger.

**5. Bring your own (a bonus the user named, after piece 4).**
- *Contents:*
  - **Create a material:** pick a colour and finish, or upload a photo of the real surface, which becomes a tiling texture.
  - **Import a model:** glTF/GLB first. The user's Live Home 3D exports USDZ and imports OBJ, so OBJ is a likely second format.
- Imports are household data, backed up with the house and never shipped with the add-on. The shipped library stays CC0/MIT only.
- *Exit:* the user makes a material from a photo of their siding, imports one piece of furniture, and places both.

## 10. Left to the builder

- The exact schema 3 field names, and the room-region algorithm.
- How model operations are shared between browser and server, under the §4.6 constraint.
- How the scene updates while dragging: a partial or full rebuild, provided the drag runs at frame rate on the admin page.
- The look of the handles and dimension labels, within the UI guide.
- The streaming wire format, and how partial reader output is parsed into pieces.
- Whether the room panel uses hosted HA cards or custom controls (as in the twin design §14).

## 11. Risks

- **Rooms derived from imperfect reads.**
  - *Risk:* a reader that leaves gaps produces unclosed rooms.
  - *Mitigation:* the weld, the visible "room isn't closed" flag, and Draw wall to close it in seconds.
- **Two implementations of the operations drifting apart.**
  - *Mitigation:* the shared fixture suite (§4.6).
- **Drag performance.**
  - *Risk:* today every change rebuilds the whole scene.
  - *Mitigation:* measure in piece 2 before adding features.
- **Plans with no fixture symbols.**
  - *Risk:* the household's set may be floor, floor and roof sheets only.
  - *Mitigation:* devices still sit in their rooms, and anchors can be added by hand.
- **Streaming partial JSON from the model.**
  - *Risk:* malformed tails.
  - *Mitigation:* pieces are committed only when complete, and the rest is discarded on Stop.
- **Migration of the household's person edits.**
  - *Mitigation:* every unresolved item is flagged, and the pre-migration round is one tap back on the timeline.

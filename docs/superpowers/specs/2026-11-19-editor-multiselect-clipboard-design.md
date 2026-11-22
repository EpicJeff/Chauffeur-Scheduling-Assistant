# House editor: selecting many things, and cut, copy, paste

Owner request, 2026-11-19: "Some things that seem pretty basic but we have not included at all: Multiselect for like things. Selecting a bunch of walls to set their materials all at once, selecting multiple trees or props to move the whole selection, etc. Cut/Copy/Paste. Being able to select some trees and duplicate them or selecting a window, copying it, pasting it onto another wall to get an identical window or whatever."

## Why

Today the editor acts on one thing at a time. Giving twelve walls the same siding means twelve selections and twelve assignments. Moving a row of shrubs means moving each shrub. A second identical window means adding a new window and re-entering its size, model and materials. Every serious 3D tool the owner uses (Twinmotion, Live Home 3D, SketchUp) lets you work on a set and reuse what you made. Without this, the editor feels like a toy at exactly the moments when a person is doing real work.

## Goals

1. **Select many things** by Ctrl-click (Cmd on a Mac) and by dragging a box (a marquee), in the 3D view and in the Scene tree.
2. **Select by material:** every surface or slot using a given material, either house-wide or within the current selection.
3. **Act on the whole selection:** move, turn, scale, delete, hide, lock, and set materials, in one undo step.
4. **A materials-in-selection list** that shows the materials the selection uses and lets the person replace one material with another across all of them. This works for a single object too: a door with frame, panel and casing lists three entries.
5. **Mixed selections** (walls, trees and a light together) work: shared actions apply to all of them, and kind-specific fields are reached by narrowing the selection to one kind.
6. **Cut, copy, paste and duplicate** for the things a person places: trees and plants, furniture and props, yard pieces, windows, doors and openings, light and effect fixtures. A copy keeps everything that made the original what it is: size, model, materials, tint, UV offset, settings.

## Non-goals

- Copying across houses, or pasting into another program.
- Copying structural pieces that other pieces depend on: walls, rooms, floors, roofs, buildings. They join to their neighbours and do not stand alone. Their materials can still be copied (see "Copying a look").
- Selection groups saved by name, or arrays and patterns ("paste 10 in a row").
- Agent (Argyle) access to the clipboard. Argyle already edits through operations, so multi-piece operations reach it naturally, but this design adds no new agent tool.

## Anti-goals (would make this a failure even if it works)

- A paste that lands somewhere wrong or invisible, such as a window inside a floor or a tree under a pad. A paste either lands sensibly or does nothing and says why.
- A multi-selection that loses the person's work when they misclick. A plain click on empty space clears the selection, exactly as today, and selecting is never an edit, so undo history is untouched.
- Hidden or locked things getting caught in a marquee and edited without the person seeing them.
- Properties jumping to the top or losing focus while the selection changes (owner rule, 2026-11-19).
- A group edit that splits into many undo steps.

## Selecting (owner's methods)

- **Click** selects one thing; **Ctrl-click (Cmd-click)** adds it to the selection or removes it; a click on empty space clears the selection.
- **Marquee:** drag a box starting on empty space in the view (with the Select tool). Everything whose screen footprint lies inside the box is selected. Ctrl-drag adds to the selection, Alt-drag removes from it. *(Claude's call: whole footprint inside, the SketchUp left-to-right convention; a crossing mode is left out to keep one rule.)* A drag that starts on a thing still moves it, as today (slice 3a's drag rules).
- **Scene tree:** Ctrl-click toggles a row, Shift-click selects a range; rows highlight to match the view.
- Hidden things are never selected; locked things are selected only from the Scene tree, never by a click or a marquee in the view (slice 5's rules).
- **Select by material** *(owner)*: right-click a surface, or an entry in the materials-in-selection list, and choose "Select all using <material>"; a second choice limits this to the current selection's buildings or the yard. *(Claude's call on placement.)*

## What a selection shows (Properties)

- **A summary line** at the top: "3 walls · 2 trees · 1 window · 1 light". Clicking a kind narrows the selection to that kind; Ctrl-clicking a kind removes it. *(Claude's proposal, played back to the owner.)*
- **Materials in the selection** *(owner's Live Home 3D idea, adapted to our embedded slot rows)*: a section listing every distinct material the selection uses, with its swatch, name and count ("Painted siding × 14 surfaces", "Oak × 2 frames"). Each entry offers **Use <Library selection>** to replace that material everywhere it appears in the selection (every slot holding it, not other slots, in one undo step), **Select all using it**, and **Show in Library**. A single selected object lists its own materials the same way. The per-slot rows stay where they are, beneath it.
- **One kind selected:** the fields every member shares, edited together; a field whose values differ shows "Mixed" and setting it sets all. Material slot rows act on the same slot of every member (for example the Frame slot of five windows).
- **Mixed kinds:** the summary, the materials list and the shared actions, plus "Narrow to walls (3)" style shortcuts. Kind-specific fields appear only after narrowing.

## Acting on a selection

- **Move, turn, scale** apply to everything movable in the selection about the selection's centre, with the gizmo and typed values from slice 3b; walls move with their joints as a single wall does; things that cannot move freely (a roof plane, a room floor, a pool part, a wall face) stay selected for materials and the summary marks them "moves with its building". *(Claude's call.)*
- **Delete, hide, lock** apply to all.
- Each of these is **one operation and one undo step**, sent as a batch to the server. *(Claude's call: a batch op wrapping the existing per-piece ops, so the server's validation stays in one place.)*

## Cut, copy, paste, duplicate (owner's three paste modes plus the usual)

- **Keys:** Ctrl+C / Ctrl+X / Ctrl+V / Ctrl+D (Cmd on a Mac), toolbar Copy/Paste buttons, and Copy / Cut / Paste / Duplicate in right-click menus. *(Ctrl+P is the browser's print key; the owner meant Ctrl+V.)*
- **What can be copied:** placed things (plants, furniture and props, yard pieces such as pads, paths, beds, fences, fire pits and pool features, openings, light and effect fixtures). Device-bound pieces (anything tied to a Home Assistant entity, such as a device anchor) copy **without** their entity binding and say so, so two pieces never claim one device. *(Claude's call.)*
- **Paste modes** *(owner)*:
  1. **Right-click a surface → Paste:** lands where clicked: an opening on that wall at that point, a plant, prop or yard piece on the ground or deck there, a fixture on that surface as placement does.
  2. **Select a target, then Ctrl+V or Paste:** lands on the selected thing: an opening centred on the selected wall, plants spread over a selected pad keeping their arrangement, a fixture centred on a selected surface.
  3. **Ctrl+C then Ctrl+V with no target:** lands where the original was, offset slightly (one grid step along the view's right and down, *Claude's call*) so it is clearly a new piece; the pasted pieces become the selection.
- **Duplicate** = copy plus paste mode 3 in one step.
- **Sets keep their arrangement** relative to their own centre.
- **Cut** removes and holds; pasting places them anywhere (once or many times); undo restores the cut.
- **Where a paste cannot land** (an opening onto a floor, a fixture onto glass, a piece that would collide with the wall it needs), nothing changes and the status line says why ("A window needs a wall").
- **Copying a look** *(Claude's addition, consistent with the owner's material-replacement goal)*: right-click a slot row or a surface → "Copy material" and "Paste material" copy a slot ref (material, tint, UV offset) to another slot or to every same-kind slot in a selection. This covers walls and other structure that cannot be copied as objects.
- The clipboard lives for the editor session (and survives switching floors and tabs); it is not shared between browser tabs. *(Claude's call.)*

## Constraints

- Repository rules in `AGENTS.md`: no browser dialogs (use the app's alert/confirm/input helpers), every agent capability needs a hand path, never remove anything a person can do, kiosk and read-only variants share logic, Tailwind rebuilt after template class changes.
- The editor's existing structure: the shared picker (`editor/picking.js`, slice 3a), handles and gizmo (slice 3b), the dock, Properties and right-click menus (slice 4), visibility and the Scene tree (slice 5), the Library selection and slot rows (slice 6), surface slots and `resolveSurfaceMaterial` (slice 7). Multiselect extends these rather than adding parallel paths.
- Properties keeps its place when the selection changes or a field reshapes it (`editor/keep_place.js`).
- Every server change goes through the existing operation path and undo history; one user action, one history entry.
- No new texture sampler or lit-material uniform (the GPU budget is full); selection highlighting uses the existing outline/selection drawing.
- Performance: selecting and moving 200 plants stays responsive (a drag frame under 33 ms on the desktop); the marquee test runs on screen-space bounds, not per-triangle picking.

## Claude's calls from the builder check

These settle questions a builder would otherwise guess at. The owner can overturn any of them.

1. **Built on slice 7.** This work is planned after slice 7 (a material slot on every surface) lands: slot refs `{id?, color?, uv?}`, roof `plane_materials`, pool ledge/step slots, the site roles and `resolveSurfaceMaterial(plan, surface) -> {ref, source}` are the contract.
2. **A batch is all or nothing.** The server applies every member of a batch or none; a refused batch names the member and the reason in the status line, and the queue treats the batch as one step (slice 2's drop-and-name rule applies to the batch as a unit).
3. **Selection members are pieces** (a wall, a room, a roof, a plant, an opening, a fixture, a yard piece, a pool feature). Surfaces and slots are not separate selection members. "Select all using <material>" selects the owning pieces and remembers which of their slots matched, so the materials list and its counts ("× 14 surfaces") count slots; a marquee selects pieces. A wall face is edited through its wall.
4. **Which paste mode applies:** if the selection is empty, or is exactly what was copied, paste mode 3 (same place, offset). If the selection holds a valid host for the clipboard, mode 2: openings land on a selected wall; plants, props and yard pieces on a selected pad, deck, room floor or ground piece; fixtures on any selected surface piece. If the selection holds no valid host for anything copied, fall back to mode 3 and say so in the status line.
5. **Pasting a set:** free-standing pieces (plants, props, yard pieces, fixtures) paste as one rigid set keeping their arrangement. Openings re-host: in mode 2 onto the target wall, spaced along it in their original order and spacing (refused if they do not fit); in mode 1 onto the clicked wall; in mode 3 each slides one grid step along its own wall to the next free spot (refused if none). Mode 3 pastes on the original's floor; if the original's wall no longer exists, the opening is refused with a reason.
6. **What copies, kind by kind:**
   - Plants, furniture and props, beds, fire pits: yes, with everything (model, size, materials, tint, UV offset, settings).
   - Pads: yes, the pad alone (not the plants or beds on it); edges and their walls/stairs come with the pad.
   - Paths and fences: yes, as new free pieces; their joins to other pieces are not copied.
   - Pool features (spa, ledge, steps): yes, within the same pool (paste targets that pool); a pool itself does not copy.
   - Openings (windows, doors, garage doors): yes, with model, size, parts' materials and settings.
   - Light and effect fixtures: yes, with their settings and their Home Assistant light or effect binding (two fixtures may show one light; that is already allowed).
   - Device-bound pieces (device anchors): copy without the device binding, and say so.
   - Walls, rooms, floors, roofs, buildings, the lot: no (structure); their looks copy with "Copy material".
7. **Cut keeps identity on its first paste:** the first paste after a cut re-creates the pieces with their original ids, so hide/lock state, Argyle references and device bindings survive a move by cut and paste; later pastes of the same clipboard make new ids (and drop device bindings as copy does). Undoing the cut restores the originals and leaves the clipboard as it was. The clipboard is cleared when the editor reloads.
8. **"Use <material>" in the materials list writes overrides** on each matching slot of the selected pieces, keeping each slot's existing tint and UV offset; it never edits a building or house-wide default (House materials does that). Slots that only inherit the replaced material count, and get an override.
9. **Marquee and select-by-material respect visibility:** they skip hidden and locked pieces; in a floor or room view they consider only that floor's pieces and the yard; in the house view, everything. Occlusion does not matter: a box selects what lies inside it even behind a wall (the SketchUp rule).
10. **Move, turn, scale by kind:**

| Kind | Move | Turn | Scale |
| --- | --- | --- | --- |
| Plants, furniture, props | free | free | uniform transform |
| Yard pieces (pads, paths, beds, fences, fire pits) | free | free | footprint scale |
| Light and effect fixtures | free (stays on its surface) | free | no |
| Openings | slide along their wall only | no | width and height |
| Walls | with their joints | as a set, about the set centre | no |
| Pool features | within their pool | no | no |
| Rooms, floors, roofs, roof planes, pool, buildings | no (moves with its building) | no | no |

## Left to the builder

- How the selection is stored (a list of piece references, alongside today's single selection, which stays the "primary").
- Marquee hit-testing technique (projected bounds per piece; instanced plants by instance).
- The batch operation format and how the server applies it atomically.
- How the summary, the materials list and "Mixed" fields are laid out, within `chauffeur/docs/ui_design_guide.md`.
- Exact offsets and snapping for pasted pieces beyond the rules above.

## Planning

One plan, after slice 7 lands. It touches picking, the gizmo, Properties, the Scene tree, right-click menus and the server's operations, so it is its own slice, slotted before slice 8 (the visual pass) so the visual pass covers its UI.

# Selecting a room or porch is an ordinary selection

Owner, 2026-11-25: "Why does selecting a porch go into this ghosted view that freezes the editor for like 30 seconds? It should just be a selection like any other, right?"

## Measured (owner's 11-20 export, editor, High, headless, busy machine)

| Step | Longest main-thread freeze | House rebuild |
|---|---|---|
| Select a roof | 0.3 s | none |
| Select the pool porch | 34.0 s | 33.9 s |
| Select a roof again | 12.2 s | 12.1 s |
| Select the pool porch again | 13.9 s | 13.9 s |
| Select the back porch | 12.2 s | 12.2 s |

## Cause

`view.setSelection` (twin_view.js, since 2026-11-09) treats a selected room or level as the "editable level": it rebuilds the whole house with that level's pieces unmerged (`perPiece`), shows default-hidden anchors and lamps, ghosts everything outside the room (cloned transparent materials, 18 new shader programs) and limits clicks to the room. Leaving it rebuilds again.

## Decision

1. Selecting a room, porch or level is an outline and a card, as for a roof. No rebuild, no ghosting, no new program, no click limit, nothing hidden or shown. A click on any piece selects that piece.
2. The inside-the-room view stays available as an explicit action, "Focus room", on the card of a room, porch or level and in its right-click menu; Escape or "Leave room" ends it. It behaves as today's selection does: ghosting, clicks limited to the room, hidden anchors shown. Nothing a person can do today is lost.
3. Focus room must not freeze either: entering and leaving it must not rebuild the house. Ghosting and limiting clicks work from the existing merged meshes and their ownership ranges; only what truly needs unmerged pieces may unmerge, for that level only, without rebuilding other levels or buildings.
4. Editing pieces (walls, corners, openings, hosted items, dragging, tinting) keeps working with no room focused, with live previews as today.
5. `view.setEditableLevel` and the top and plan cameras keep framing the selected room (`selectionFloor`, `floorFocus`).

## Gates

On the owner's export, High, in the editor: selecting a room, a porch, a level and another building's room: no `view.rebuild`, no new program, no main-thread task over 250 ms, outline on the next frame. Entering and leaving Focus room: no full rebuild, no task over 500 ms after shaders are warm; the first entry may compile off the main thread while the normal picture keeps drawing. Every present editor capability still works (list it, test it).

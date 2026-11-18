# House editor overhaul: speed, picking, layout

Date: 2026-11-16. Status: approved by the owner 2026-11-16. Slice 1 (measure and spike) landed in v2.499.926; its numbers are in `docs/superpowers/notes/2026-11-16-editor-slice1-numbers.md`. Nothing else here is built except where "already shipped" says so.

Related: `2026-11-12-twin-editor-scope.md` (the feature scope list), `2026-11-13-material-library-design.md` (material identity and the Library page), `chauffeur/docs/ui_design_guide.md`.

## Why

The owner edits a large real house in the editor at `/house/editor` (code under `chauffeur/static/twin/editor/`, server in `chauffeur/services/twin_*.py`). In their words:

- "The editor is still super slow with a house like mine." The real issue: "change something and then wait forever for it to apply the change visually. Drag a point on a line and release, then sit for 5s".
- "I still move things by accident all the time."
- "I am constantly opening and closing dialogs because they are on top of each other."
- "trying to select the thing I want to edit, trying to move a point on a line and dragging it actually selects and moves the thing below it, select a room and edit the fixtures of one device and then there's no way back to the device list to edit another one, no way to hide specific things like the trees and bushes".
- "We need to make it more efficient in just about every way", clarified as: efficient performance, efficient workflows, efficient UI. "Not every process should be optimized Willy-nilly."
- "And if it looked nicer on the process, that's a win-win."

The owner is a game developer of twenty years and expects the editor to behave like a competent level editor: selection is predictable, a drag never does something they did not ask for, an edit shows at once, and panels have fixed places.

## Goals

1. After releasing a drag (a wall, a point, a placed object), the house shows the result within 0.5 seconds on the owner's house.
2. Nothing moves unless the person dragged a handle or used the Move tool.
3. The thing a person clicks is the thing that gets selected, and there is always a way to reach the thing underneath.
4. No panel covers another panel. Every selection is edited in one fixed place, with a way back up.
5. Any item or kind of item can be hidden or locked while editing.
6. Every surface can carry its own material, defaulting to the house material.
7. The editor looks like one designed tool.

## Non-goals

- Touch and the wall panel. The editor targets a desktop browser with mouse and keyboard (the author's assumption; the owner did not object).
- Changing what the viewer (`/house/twin`) shows. Hide and lock are editor-only and never saved into the house.
- New kinds of house content. This is about editing what exists.
- Roof geometry work, SketchUp import, anything keyed to the owner's own house.
- Rewriting the editor in another framework or engine. The measured costs are in rebuild and round trips, not in the language.

## Anti-goals

- An edit that looks applied and is then silently lost.
- Losing several edits because one of them was refused.
- Any performance gain bought with lower render quality. The owner's rule: "optimize, but never at the cost of overall quality".
- Removing anything a person can do today without the owner's approval first. Every control that exists must have a home in the new layout; a move is fine, a loss is not.
- Browser dialogs (`alert`, `confirm`, `prompt`). Use `showGlobalAlert`, `promptConfirm`, `promptInput`, `promptChoice`.
- A new long-lived stream per tab. Each house tab already holds two and the browser allows six per host.

## Constraints

- Repository rules in `AGENTS.md` apply: own worktree per piece of work, tests run from `chauffeur/` as plain scripts with `HA_BASE_URL` unset, Tailwind rebuilt after template class changes, every Home Assistant touchpoint degrades with none present, every agent capability keeps a hand path, vendored Alpine boolean bindings coerced with `!!`.
- The `house_design` agent tool schema is at its size cap and must not grow. Server operations added here are reachable by hand through the editor; if the agent needs one, it goes through an existing operation shape.
- No `transmission`, no second scene render, no planar reflection, no screen grab in the renderer.
- No new packages in `requirements.txt`.
- History keeps the newest 50 steps (`twin_store.HISTORY_KEEP`, shipped v2.499.903). Anything that reads history must tolerate that window, and per-edit data must never grow the `house_twin` settings row.
- Material identity, tint, bake role and UV offset rules from the material library design are locked.

## What is measured, and what is not

Measured on the owner's exported house after the history slice (v2.499.903):

- A wall move costs about 0.8 s on the server and about 0.9 s of client rebuild, on top of the round trip. The state poll response is 7.5 KB.

Not measured, and needed before the plan for slice 2 is final:

- The cost of rebuilding one piece (one wall and its neighbours, one room, one yard piece) instead of the whole house.
- Frame time while dragging.
- Where the server's 0.8 s goes.
- The owner's own timing on their machine (an overlay like the viewer's `?perf=1`).

## The design, by slice

Each slice lands on its own with a version bump and is usable without the later ones. Slices 1 to 3 remove the daily pain and need no new layout; the shell comes before the panels that live in it; the visual pass is last so it is not spent on a layout that is still moving.

### Slice 1: measure and spike

The timing overlay is product code from the start, because it is how the goal is checked on the owner's machine. The spike and the server breakdown are throwaway; nothing from them is kept without coming back for approval.

The house to measure against is the owner's export at `C:\Users\ffejn\Downloads\Current house.chauffeur-house.json`. It is data: read it only by path argument with `python -I`, never copy it into the repository, and never read `chauffeur/data`.

- A timing overlay in the editor (behind a query flag) showing, for the last edit: time from release to first changed frame, server time, client rebuild time, and frame time during the drag.
- A spike that applies one wall move locally and rebuilds only the affected pieces, to learn whether a per-piece rebuild under about 150 ms is reachable and what "affected pieces" has to include (neighbouring walls, the room's floor and ceiling, openings, the roof edge, baked lighting).
- A breakdown of the server's 0.8 s.

Output: numbers, and a short note saying whether 0.5 s is reachable with the approach in slice 2 or what must change. If it is not reachable, stop and report before building slices 2 and 3b.

### Slice 2: fast apply

- **Which edits (author's call).** Every edit goes through the ordered queue, so saving and refusal behave one way. Applying locally before the server answers is built first for drags and moves of existing things (walls, points, placed objects, yard pieces), which is where the owner waits today. Property edits, adds and deletes are queued from the start but show when the server answers until they get their own local apply; the plan orders those by the cost slice 1 measures. The 0.5 second goal is judged on drags first.
- **Someone else changes the house (author's call).** If Argyle, a build or another parent lands a round while steps are queued, the editor takes the new house, then replays its unsent steps on top by the same rule as a refusal: a step that no longer applies is dropped and named, the rest stay. The existing rule that undo never reverts over someone else's round (rule I5 in `history.js`) still holds, including for steps in flight.
- **Apply at release.** When a drag ends, the editor applies the change to its own copy of the house and rebuilds only the affected pieces. The server save runs in the background.
- **Ordered queue.** Each release is one step. Steps are sent to the server in order. A step made while earlier ones are still in flight is applied locally at once and queued.
- **Refusal.** The server stays the final judge. If it refuses a step, only that step snaps back, and any later queued step that cannot exist without it (a door in a wall that was refused) goes with it. Unrelated later steps are replayed on the corrected house and stay. One notice names what was refused, why, and each dependent step that went with it; the refused thing is left selected so it can be redone. The owner accepted exactly this: snap-back is fine, losing unrelated edits is not, losing dependents is acceptable.
- **Network failure is not refusal.** If a save fails for any reason other than a refusal, nothing snaps back. The edits stay on screen, the save state reads unsaved, and the editor retries. Leaving the page with unsaved steps warns first (with `promptConfirm`, not a browser dialog, where the platform allows; a `beforeunload` guard is acceptable as the last resort because no in-page dialog can run there).
- **Check before release.** Rules the editor can evaluate itself (a wall crossing another, an opening off its wall, a shape below its minimum) are checked during the drag and shown, so a refusal after release is rare.
- **Rooms settle in two steps (the owner's decision, for now).** Rooms, floors, ceilings, wall joints and the splitting of a wall where another meets it are worked out by the server in Python (`services/twin_model.py`, `services/twin_joints.py`), because Argyle, builds and the other parent edit the house with no browser open. The browser has no copy of that logic. So at release the editor shows what it can work out itself: the moved wall, its openings, and the neighbouring walls stretched to follow. The rooms, floors, ceilings and any split the move causes are corrected when the server answers. The 0.5 second goal applies to the first step; the second must land without a visible flash or reselect, and the selection must survive a split that gives the wall new ids. The owner chose this to get the rest of the overhaul in sooner, with the proper fix scheduled as slice 9.
- **Baked lighting may lag (author's call, the owner has not ruled).** Geometry is right within the goal. Baked light on the changed pieces catches up afterwards, as it does today, and the editor keeps saying when lights are waiting to re-bake. It must never look worse than today's behaviour during that wait.
- **Untouched work stays untouched.** Baked lighting, the yard and the pool are rebuilt only when the edit reaches them. The state poll must not trigger a rebuild for the editor's own edits.
- **Save state is always visible**: saved, saving N changes, or N unsaved.
- Undo and redo keep working across the queue: undo of a step that is still in flight is allowed and resolves in order.

Left to the builder: how dependency between steps is detected, the shape of the server's response (a delta is expected to be needed), and how local results are reconciled with the server's answer when they differ in detail (the server's version wins, without a visible jump where the difference is below what a person can see).

### Slice 3a: picking and drag rules

One picking pipeline for the whole editor, replacing per-tool hit tests.

- Hover shows an outline of what a click would select.
- A click selects the nearest thing under the pointer. Clicking again in the same place cycles to the thing beneath it.
- The handles of the selected thing always win over anything else under the pointer, with a hit area larger than the drawn handle.
- A drag begins only after the pointer has moved past a small threshold, so a click never nudges.
- Esc cancels a drag in progress and restores the thing exactly.
- A drag that starts on empty space or on an unselected thing always navigates the camera. Movement comes only from a handle or from the Move tool.
- With the Move tool active (author's call): dragging the body of the selected thing moves it; dragging an unselected thing still navigates, and a click selects it first. The Move tool never selects and moves in one gesture.
- Line fixtures (light strips, waterfalls, anything drawn as a path) get real draggable handles at each point. Dragging one moves that point and nothing below it.
- Locked or hidden things (slice 5) are skipped by picking.

### Slice 3b: handles and precision tools

- **Gizmos.** Move works on anything placed. Rotate works on placed objects (plants, fixtures, devices, yard pieces) and on whole buildings; a single wall turns by dragging an end, not by a gizmo. Scale works on placed objects only; walls, rooms and pads resize by handles with real dimensions, never by a factor.
- A typed value beside the gizmo while dragging, so an exact length or angle can be entered.
- Snapping is on by default; holding a modifier key switches it off for that drag.
- **Walls.** A handle at each end. Dropping an end on another wall's end joins them. A wall can be split at a point.

These are the author's calls; the owner asked for gizmos, wall end handles, join and split, and asked that they come with the picking work.

### Slice 4: the shell

The layout the owner chose from two mockups (stacked dock over tabbed dock).

- **Top toolbar**, one row, replacing the left tool column: a menu button (save, open, export, settings), the house name, the save state, then tools as icons with tooltips grouped as select and move, structure (wall, room, door, window, roof), yard (yard, pool, plants), fixtures (light, effect, device, measure), then undo and redo, floor and view pickers.
- **The generation bar** (automated generation controls) shows only while a generation is running.
- **Right dock, stacked.** Top half: tabs for Scene, Layers and Library. Bottom half: Properties, always visible. A folded History section sits under Properties. Nothing floats over the 3D view.
- **Properties is the one place a selection lands.** It carries a back arrow and a breadcrumb, for example Floor 1 > Kitchen > Ceiling lights > Fixtures. Going into a device's fixtures and back to the device list is one click. Every existing shelf, card and drawer that edits a selected thing moves here.
- **Scene selection and Library selection are separate.** Browsing the Library never drops the selected object, so Properties keeps showing it.
- **Other dialogs** (house materials, save and open, import, settings) open centred, one at a time.
- **Status line** at the bottom: what the current tool expects next, and the save state.
- **Right-click menus** in the view and in the lists, offering the actions that apply to the thing under the pointer (for a wall: split here, add door, add window, hide, lock, delete).

Every control that exists today must be listed and given a home before this slice is planned. A control with no obvious home is raised with the owner, not dropped.

### Slice 5: scene and layers

- **Scene** is the house as a tree (floors, rooms, their walls and fixtures, the yard and its pieces, plants). Clicking a row selects the thing; selecting in the view highlights the row.
- **Layers** lists kinds (walls, rooms, roof, yard, plants, lights, effects, devices, the plot plan).
- Each row in both has an eye (hide) and a lock. A hidden thing is not drawn and not pickable; a locked thing is drawn and not pickable. Hidden things remain in the Scene list, dimmed, so they can be found and shown again.
- Hide and lock are editor state only: never written into the house, never seen by the viewer. They are kept in the browser's local storage, keyed by item id (author's call), so they survive a reload on that machine and need no server storage or route. Loading a different saved house keeps the entries whose ids still exist.

### Slice 6: Library in the dock, and assigning

- The Library tab is a picker (editing materials stays on the separate Library page, as already decided). Selecting an asset highlights it; nothing else happens.
- Each material slot in Properties is a row: swatch, name, a "Use selected" button, and clear. "Use selected" is enabled only when the Library selection is of the kind the slot takes, and names what it will assign. Dragging an asset from the Library onto the row does the same.
- Clicking a slot's swatch scrolls the Library to that slot's current material.
- The same row pattern serves any slot that takes a Library asset (a fixture's model, a light's profile).
- Rename, delete and similar actions on an asset move from per-row buttons to an action bar for the selected asset and to the right-click menu.

Not included: dragging a material onto a surface in the 3D view.

### Slice 7: a material slot on every surface

The owner's ruling: "Each surface should have its own material slot. Defaults to house material."

- A surface is: each face of a wall separately (the two sides of an interior wall differ, an exterior face is its own); the floor and the ceiling of each room; each roof plane; each yard piece (pad, path, fence run, retaining wall, with a pad edge wall and its cap as separate surfaces); each pool part (interior, waterline tile, coping, and each sub-shape: ledge, steps, spa); each door, window and trim item, with frame and panel as two slots. The owner confirmed this grain; finer (part of a wall face) is out of scope.
- Stored as overrides only. A house with no override is identical to today's, so nothing migrates.
- An empty slot shows the house material it inherits, greyed, for example "House default: Siding". Clear returns to it.
- The house-wide slots stay, in the centred House materials dialog. Changing one changes every surface that has no override.
- An override keeps the surface's role for the lighting bake (a wall stays a wall). Changing one surface's material should rebake only what that surface affects; this is unverified and must be checked before planning.
- The existing per-surface tint override and UV offset live in the same slot row.
- Cost: each distinct material in view is a batch, and the Pi wall panel is GPU-bound. The same material on many surfaces stays one batch. No cap is planned; the plan must measure a house with many overrides on the low tier and report it.

### Slice 8: visual pass

Icons, spacing, type and colour across the editor, following `chauffeur/docs/ui_design_guide.md`, once the structure above has settled. Earlier slices still follow the guide; this slice is for consistency, not rescue. Mockups go to the owner before it is built.

### Slice 9: one implementation of the room logic

Scheduled after the slices above, by the owner's decision: "do two-step initially to get things to a better place, and then schedule the rewrite to one implementation work to follow". The owner's view of the two-step settle is that it is a flawed workflow to be replaced, not kept.

- The room, joint and split logic is written once, in JavaScript, and used by both the browser and the server. The Python copy is deleted when the swap is done.
- The server runs it through a small Node.js worker that stays running, so an edit does not pay a start-up. This needs Node.js added to the add-on image (`chauffeur/Dockerfile` is `python:3.11-slim` with no JavaScript runtime today; the image grows by roughly 100 MB). It is not a Python package, so `requirements.txt` is untouched. **The owner has not yet approved adding Node.js to the image; that approval is needed before this slice is planned.**
- During the swap both copies run side by side on example houses, including the owner's export, and must agree before the Python copy goes.
- If the worker is down, an edit is refused with a clear message. A house is never saved with stale rooms.
- Result: rooms, floors and splits are right at release, the second step of slice 2 disappears, and the editor can check a move against the real rules during the drag.
- Size is unknown. About 1,200 lines of geometry move, and part of the edit rules in `services/twin_model_ops.py` follows. Slice 1 should note anything it learns about this; the estimate is made when the slice is planned.

## Already shipped toward this

- History keeps the newest 50 steps, with a History list instead of the timeline strip and automatic saved houses (v2.499.903). This took a wall move on the server from about 2.7 s to about 0.8 s on the owner's house.
- Save and open houses by name exists.

## Testing

- Entry points swallow exceptions, so each slice needs at least one test that runs the real path: a node run of the editor modules for logic, and a Chromium run of the real editor for picking, drag and layout.
- Slice 2 needs a Chromium test that moves a wall so it splits another and asserts the selection survives the server's answer.
- Slice 2 needs tests for: a refused step in the middle of a queue with an unrelated later step (stays) and a dependent later step (goes, and is named), a network failure (nothing snaps back, retry succeeds), and undo while steps are in flight.
- Slice 3a needs a Chromium test that drags on empty space over a movable thing and asserts the house is unchanged.
- The timing overlay from slice 1 becomes the way the 0.5 s goal is checked on the owner's machine; a Chromium test asserts a bound on a fixture house as a regression guard, not as proof of the goal.
- Two live editor suites (`test_house_editor_live.py`, `test_house_editor_steps_live.py`) time out on the development machine on untouched main. They cannot gate this work until that is understood; finding out why belongs to slice 1.

## Left to the builder

- Module boundaries for the picking pipeline, the edit queue and the dock, within the existing `static/twin/editor/` layout.
- The server response shape and how deltas are computed.
- Icon set, within the design guide.
- Keyboard shortcuts for tools, proposed in the plan for slice 4.
- How Scene tree rows are virtualised if the house is large.

## Planning

One plan per slice. Slices 1 to 3 are planned in detail first; slices 4 to 9 are planned when reached, because slice 1's numbers and the control inventory in slice 4 will change them.

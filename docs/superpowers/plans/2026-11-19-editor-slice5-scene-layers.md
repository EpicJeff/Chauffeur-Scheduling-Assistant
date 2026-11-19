# Editor slice 5: scene and layers, hide and lock — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The dock's Scene tab becomes the house as a tree and its Layers tab lists every kind of thing; every row has an eye (hide) and a lock. A hidden thing is not drawn and not pickable; a locked thing is drawn and not pickable. Hidden things stay listed (dimmed) so they can be found and shown again.

**Architecture:** One editor-only visibility store (`editor/visibility.js`) holds hidden and locked piece ids and kinds in the browser's localStorage, keyed by house. It applies to the view without a rebuild: a hidden piece inside a merged material batch has its vertex range (slice 2's `snapRanges`) collapsed in place and restored on show; instanced pieces get a zero-scale instance matrix; whole objects (markers, fixtures, effects, models) get `visible = false`. The shared picker (slice 3a, `editor/picking.js`) gets the store's `isPickable`. The view re-applies the store after every settle and rebuild.

**Tech Stack:** plain ES modules under `chauffeur/static/twin/editor/`, the house editor template, three r187, node-driven tests, Chromium live tests.

**Spec:** `docs/superpowers/specs/2026-11-16-twin-editor-overhaul-design.md`, "Slice 5: scene and layers". Slice 4 (the dock, v2.499.940) is shipped: read `editor/dock.js`, the Scene and Layers panes in `templates/house_editor.html`, `editor/context_menu.js`, and the slice 4 entry at the top of `chauffeur/system_capabilities.md`.

## Global Constraints

- Work in `E:\repositories\Chauffeur-editor-slice5` only. Never edit `E:\repositories\Chauffeur`. Never touch `chauffeur/data`. Never open `*_api_key.txt`.
- Do not commit, do not bump `chauffeur/config.yaml`. Leave changes in the working tree and write the report file.
- Do not launch Chromium, Playwright or any browser; never use the user's browser.
- Tests run from `chauffeur/` as plain scripts with `HA_BASE_URL` unset. Run the named tests and neighbours, and before reporting run **every** node test that touches the editor (grep `tests/test_*_js.py` for `static/twin/editor/`, `house_editor.html`, `twin_editor_dom`, `from test_twin_drag_js`); compare any failure with main in a detached baseline worktree outside the repo folder (never edit it).
- **Hide and lock are editor state only**: never written into the house, never sent to the server, never seen by the viewer (`/house/twin`). No server route, no setting.
- **Never remove anything a person can do.** Keep every element id and accessible name from slice 4.
- No browser dialogs. Follow `chauffeur/docs/ui_design_guide.md`. Rebuild Tailwind after template class changes.
- **No new texture sampler in any material** (the owner's GPU allows 16 units; see the slice 1 haze fix, v2.499.939). Hiding must not change any material's program key either.
- Slice 3a/3b/4 rules stay (picking, handles, gizmos, Esc order, the dock).

## Rulings (Claude's calls within the spec)

1. **Storage:** `localStorage['chauffeur.editor.visibility.<houseId>'] = {hidden: [ids], locked: [ids], hiddenKinds: [kinds], lockedKinds: [kinds]}`; `houseId` is the saved house's id when one is open, else `'current'`. Loading a different saved house keeps the entries whose ids exist in it (spec) and drops the rest at load.
2. **Scene tree** (top to bottom): each building, then its floors, each floor's rooms, each room's walls, openings, items, anchors, devices and light/effect fixtures; then Yard: pads, paths and hardscape, beds, edges, pool (and its spa, steps, ledges), fire pits, fences, yard rooms, planting, furniture. A row's click selects the thing (the same selection the view makes); a selection in the view highlights and scrolls to its row. Rows for children of a hidden parent show as hidden. Long lists are virtualised when the tree has more than 300 visible rows (the builder's call how).
3. **Layers kinds:** Walls, Rooms (floors and ceilings), Openings, Roofs, Stairs, Items and furniture, Plants, Yard surfaces (pads, paths, beds, edges, pool, fire pits, fences), Lights (fixtures and lamps), Effects, Devices, plus the existing Sheet underlay and Grade tint rows. Each kind row has an eye and a lock.
4. **Eye and lock controls:** 32 px icon buttons at the row's end, `aria-pressed`, accessible names `Hide <name>` / `Show <name>` and `Lock <name>` / `Unlock <name>`. Hidden rows are dimmed (opacity .5) and keep their eye visible.
5. **Hiding** a piece: the view collapses that piece's vertex ranges in every merged batch to a degenerate point (positions of the range's first vertex), keeping a copy of the original positions to restore; instanced pieces get a zero-scale instance matrix (restored on show); separate objects get `visible = false`. Hidden pieces are excluded from picking, shadows (collapsed triangles cast none) and reflection captures (they re-capture after a change). Re-applied after every `view.settle`/`rebuild`/`rebuildLevel` from the store.
6. **Locking:** the picker's `isPickable` returns false for a locked piece or kind; handles and gizmos never appear for it; a locked thing can still be selected from the Scene tree (to edit it in Properties), but not in the view.
7. **Right-click** (slice 4 menus) gains Hide, Lock (Show / Unlock when applicable) for the thing under the pointer, and the view's empty-space menu gains Show all hidden.
8. **Keyboard:** H hides the selection, Shift+H shows all hidden (only outside text inputs; no Ctrl/Alt/Meta).

## Review Focus

1. A hidden wall inside a merged batch disappears and returns exactly (positions identical), and no other piece in that batch changes.
2. After an edit that rebuilds or deforms the level, hidden and locked pieces stay hidden and locked.
3. The viewer never sees hidden state (open `/house/twin` with the same localStorage: everything drawn).
4. A locked piece under an unlocked one: clicking reaches the unlocked one; cycling never selects the locked one.
5. Hiding everything on a floor and showing it again restores the floor's shadows and reflections.

---

### Task 1: The visibility store and its effect on the view

**Files:**
- Create: `chauffeur/static/twin/editor/visibility.js`
- Modify: `chauffeur/static/twin/twin_view.js` (a small hook to apply hidden piece ids after every settle/rebuild: `view.setHiddenPieces(ids, kinds)`), `chauffeur/static/twin/editor/editor.js` (create the store per house, wire it to the view and the picker), `chauffeur/static/twin/editor/picking.js` callers (`isPickable` from the store), `chauffeur/static/twin/editor/scene_tools.js` (H, Shift+H)
- Test: `chauffeur/tests/test_twin_visibility_js.py` (new); neighbours `tests/test_twin_picking_js.py`, `tests/test_twin_gesture_rules_js.py`, `tests/test_twin_edit_queue_editor_js.py`, `tests/test_twin_editor_shell_js.py`

**Interfaces:** `createVisibility({ houseId, storage = localStorage }) -> { hide(id), show(id), lock(id), unlock(id), hideKind(kind), showKind(kind), lockKind(kind), unlockKind(kind), showAll(), isHidden(id, kind), isLocked(id, kind), isPickable(candidate), forHouse(houseId, existingIds), subscribe(fn), snapshot() }`; `view.setHiddenPieces(ids, kinds)`; a piece kind for every piece (`wall`, `room`, `opening`, `roof`, `stair`, `item`, `anchor`, `device`, `fixture`, `effect`, `planting`, `furniture`, `pad`, `hardscape`, `bed`, `edge`, `pool`, `fire_pit`, `fence`, `yard_room`).

- [ ] Failing tests: store round trip through a fake localStorage per house; `forHouse` keeps only existing ids; a hidden wall in a merged batch collapses exactly its range and restores identical positions; a hidden planting instance gets zero scale and returns; kinds hide every piece of that kind; `isPickable` false for hidden and locked; the shared picker skips them (cycling included); a settle/rebuild re-applies hidden state; no material's program key or version changes; the viewer (`editor` false) ignores the store; H and Shift+H.
- [ ] Run, fail, implement, pass.

### Task 2: The Scene tree and the Layers kinds

**Files:**
- Create: `chauffeur/static/twin/editor/scene_tree.js`
- Modify: `chauffeur/static/twin/editor/dock.js` (Scene and Layers panes), `chauffeur/templates/house_editor.html`, `chauffeur/static/twin/editor/editor.css`, `chauffeur/static/twin/editor/scene_tools.js` (selection to row and row to selection), `chauffeur/static/twin/editor/context_menu.js` users (Hide / Lock / Show all, ruling 7)
- Test: `chauffeur/tests/test_twin_scene_tree_js.py` (new); extend `tests/test_twin_editor_shell_js.py`; neighbours as in Task 1 plus `tests/test_twin_terrain_tools_js.py`, `tests/test_twin_lot_tools_js.py`

**Interfaces:** `createSceneTree({ host, getPlan, getSelection, select, visibility }) -> { refresh(), reveal(id) }`; Layers rows built from ruling 3.
- [ ] Failing tests: the tree lists rulings 2's structure for the test household (counts per level); clicking a row selects that piece; selecting in the view reveals and highlights its row; eye and lock buttons carry the names and `aria-pressed` of ruling 4 and drive the store; hidden rows dim; a child of a hidden parent shows hidden; more than 300 rows virtualise without losing a row's selection; Layers kinds hide and lock every piece of the kind; the existing Sheet and Grade rows keep working; the right-click menu offers Hide/Lock (and Show/Unlock) and Show all hidden; every slice 4 id and name still exists.
- [ ] Run, fail, implement, pass. Rebuild Tailwind if classes change.

### Task 3: Browser checks (Claude)

- [ ] New `tests/test_twin_scene_layers_live.py`: hide a wall from its Scene row and it disappears and returns; lock a tree and a click on it reaches the lawn or pad beneath; hide Plants from Layers and every plant goes; reload keeps the state; the viewer page draws everything; an edit next to a hidden wall keeps it hidden.
- [ ] The editor browser suites stay green (main suite with the continue-past-failure runner in its own order, steps, picking, precision, edit-fast).

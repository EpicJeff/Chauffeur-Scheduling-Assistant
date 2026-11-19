# Editor slice 4: the shell — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The house editor gets one top toolbar, a right dock (Scene / Layers / Library / Argyle tabs over an always-visible Properties, with a folded History), centred dialogs one at a time, a status line, and right-click menus. Nothing floats over the 3D view, and every control that exists today keeps a home.

**Architecture:** The existing elements move; they are not rebuilt. Every element id and data attribute that code or tests use today is kept on the moved element, so the modules keep finding their nodes. A small layout module owns the dock tabs, the Properties host (breadcrumb, back), the dialog host and the context menu; each existing card, shelf and strip renders into the Properties host instead of floating.

**Tech Stack:** Jinja template `chauffeur/templates/house_editor.html`, plain ES modules under `chauffeur/static/twin/editor/`, `editor.css`, precompiled Tailwind, node-driven tests, Chromium live tests.

**Spec:** `docs/superpowers/specs/2026-11-16-twin-editor-overhaul-design.md`, "Slice 4: the shell". **The control inventory is the authority for where every control goes:** `docs/superpowers/notes/2026-11-18-editor-control-inventory.md` (355 rows with file:line, each with its new home; the section "Owner rulings on No obvious home" at the end settles the 12 open ones; "Removed or duplicated" says where each removed element's capability goes; "Notes for the planner" lists traps). Read `chauffeur/docs/ui_design_guide.md` before any UI work.

## Global Constraints

- Work in `E:\repositories\Chauffeur-editor-slice4` only. Never edit `E:\repositories\Chauffeur`. Never touch `chauffeur/data`. Never open `*_api_key.txt`.
- Do not commit, do not bump `chauffeur/config.yaml`. Leave changes in the working tree and write the report file.
- Do not launch Chromium, Playwright or any browser; never use the user's browser.
- Tests run from `chauffeur/` as plain scripts with `HA_BASE_URL` unset. Run only the named tests and neighbours; never the whole suite.
- **Never remove anything a person can do.** Every inventory row keeps a working home; a row whose capability you cannot place is reported, not dropped.
- **Keep every existing element id and `data-*` attribute** that code or tests use (`#rail-*`, `#piece-card`, `#terrain-card`, `#library-panel`, `#editor-floors`, `#editor-history`, `#editor-agent`, `#pause-*`, `#editor-status`, `#editor-save-state`, `[data-editor-camera]`, `[data-editor-lighting]`, and so on). Move nodes; do not recreate them under new ids.
- **Every entry point that opens something still opens it:** code that shows a card, opens the Library (`#rail-library`), focuses Argyle or reveals History must switch the dock to the tab that holds it and scroll it into view.
- No browser dialogs. Follow `chauffeur/docs/ui_design_guide.md` (shared builders for the same concept). After any template class change run `python tools/build_tailwind.py` from `chauffeur/`.
- Slices 3a and 3b rules stay: picking, gizmos, handles, typed values, Esc layering (the inventory lists the order across ten files; keep it).
- Nothing of the viewer (`/house/twin`) changes.

## Rulings (Claude's calls within the spec and the inventory)

1. **New element ids:** `#editor-toolbar` (the top bar, replacing `#editor-rail` as a column and absorbing `#editor-top`), `#editor-genbar` (the generation bar: build chip, check step, resume, stop, steps strip; shown while a build is running, paused or resumable, owner ruling 4), `#editor-dock` (right dock), `#dock-tabs` with buttons `[data-dock-tab="scene|layers|library|argyle"]`, `#dock-pane-scene`, `#dock-pane-layers`, `#dock-pane-library`, `#dock-pane-argyle`, `#dock-properties` (the Properties host) with `#properties-back` and `#properties-crumbs`, `#editor-statusbar` (bottom line), `#editor-dialog` (the one centred dialog host, a `<dialog>`-like layer with a close button, Esc closes it), `#editor-context-menu`, `#rail-measure` (the new Measure tool).
2. **Toolbar groups**, left to right: menu button; house name; save state; Select, Move, Turn, Scale; structure (Draw wall, Draw room, Split room, Add door, Add window, Add stair, Add floor, Roof with Add solar zone in its group); yard (Ground and yard, which is today's terrain entry); fixtures (Add effect, Add anchor, and an Equipment menu with Add meter, Add electric panel, Add charger, Add parking spot); Measure; Delete; Undo, Redo; Sheet; floor picker (a menu of `#editor-floors` levels with show/hide, plus Add floor); view picker (cameras Top / Front / Back / Orbit and lighting Day / Night / Now / Unlit). Icons with tooltips (`title` plus an accessible name equal to today's label, so `get_by_role('button', name=...)` still works). Use one inline SVG icon set in a single module; no icon font or package.
3. **Dock:** top half tabs; Scene holds today's floors panel (slice 5 grows it into the tree); Layers holds the Sheet underlay row and the Grade tint row (owner ruling 6); Library holds `#library-panel` (no longer a floating aside; `#rail-library` switches to this tab); Argyle holds `#editor-agent` (owner ruling 1; a selection's card gets an "Ask Argyle" button that opens the tab with the selection named in the input). Bottom half: Properties, always visible, then a folded History (`#editor-history`) and, with `?timing=1`, an Edit timing section holding `#editor-edit-timing` (owner ruling 10). The dock is resizable by a splitter between the halves; it never covers the 3D view (the view's canvas is sized to the space left of the dock).
4. **Properties** renders, by what is current: the armed tool's options (draw, device, roof, terrain draft, line-fixture modes, stair draft) while a tool is armed (owner ruling 7); else the selection's card (`#piece-card` and its shelves, the fixtures and effects card, the terrain card for a pad or yard shape, the lot placement card for the lot or a building per owner ruling 11, the pause or check card during review); else a short "Nothing selected" note with the house's own entries (House materials, Your place). The breadcrumb names the path (Floor > Room > Device > Fixtures); the back arrow goes one level up (a device's fixtures back to the device, a wall back to its room, a room back to its floor). A selected wall gains a typed **Length** field (owner ruling 12; same rule as the dimension label: moves `joints[1]`).
5. **Library selection is separate from scene selection:** browsing or selecting in the Library tab never clears the scene selection; Properties keeps showing it.
6. **Centred dialogs** (one at a time; opening one closes the previous): Houses (save and open, today's `#houses-panel`), House materials, Your place (`#place-view`, with one tab per step, owner ruling 2; opened from the menu and on its own for a new house), the empty-house front door (`#editor-front-door`, owner ruling 9), Import settings, Advanced plan file, and the menu's settings. The material scope chooser after a material drop **stays as the small menu at the drop point** (owner ruling 8) and is not a dialog.
7. **Status line** (`#editor-statusbar`): what the current tool expects next (`#editor-status` moves here), the save state, and the check count (`N things to check`, owner ruling 3) which walks the check queue, each item opening in Properties.
8. **Right-click menus** in the view and in the dock lists, built from one module, listing only actions that already exist for the thing under the pointer: wall (Select, Split wall here, Add door here, Add window here, Delete), room (Select, Split room, Delete), opening, item, anchor (Select, Delete), yard piece and yard object (Select, Move, Turn, Scale, Mirror left-right, Mirror front-back, Delete), floor row (Show, Hide, Choose), Library row (its existing actions). Hide and lock come with slice 5 and are not shown yet. A right-click never changes the selection silently: choosing an action selects the thing first.
9. **Measure** (new, small): click two points in the view (snapping as walls do, Shift free); a dimension label shows the distance in feet and inches until Esc or another tool; nothing is saved.
10. **Survey bugs fixed here:** Undo/Redo accept Cmd as well as Ctrl; `#device-cancel` runs one handler per click; `cards.edge()` is removed.

## Review Focus

1. A live editor test that clicks a moved control by its old id or accessible name still finds it (the dock switches tabs for it).
2. Esc order: an open context menu closes first, then an open dialog, then the drag or armed tool (slice 3a capture rule), then the selection steps back.
3. The 3D canvas resizes with the dock and window; picking and handles stay aligned after a resize (screen-to-world uses the canvas rect).
4. A card that used to float and be dismissed (terrain card close, lot card close) still has its close or back path in Properties.
5. The generation flow (pause card, check card, Resume, Stop) works end to end while the genbar shows and hides.

---

### Task 1: Toolbar, generation bar, status line, Measure, key fixes

**Files:**
- Modify: `chauffeur/templates/house_editor.html`, `chauffeur/static/twin/editor/editor.css`, `chauffeur/static/twin/editor/editor.js`, `chauffeur/static/twin/editor/scene_tools.js` (tools, Measure), `chauffeur/static/twin/editor/history.js` (Cmd), `chauffeur/static/twin/editor/device_placement.js` (one cancel handler)
- Create: `chauffeur/static/twin/editor/icons.js` (inline SVG icons), `chauffeur/static/twin/editor/measure.js`
- Test: `chauffeur/tests/test_twin_editor_shell_js.py` (new; the toolbar part); neighbours `tests/test_twin_gesture_rules_js.py`, `tests/test_twin_editor_history_js.py`, `tests/test_twin_editor_lighting_js.py`, `tests/test_tailwind_build.py`, `tests/test_twin_import_maps.py`

**Interfaces:** Produces `#editor-toolbar`, `#editor-genbar`, `#editor-statusbar`, `#rail-measure`, `createMeasure({ view, getPlan, layer }) -> { arm(), disarm(), active() }`, `icon(name) -> SVGElement`.

- [ ] **Step 1: failing tests**: every `#rail-*` id from today's rail exists inside `#editor-toolbar` with its accessible name unchanged; groups in ruling 2 order; the Equipment menu holds the four equipment tools; the genbar is hidden when no build runs and shown while running, paused or resumable; `#editor-status` and `#editor-save-state` live in `#editor-statusbar`; Cmd+Z and Cmd+Shift+Z undo and redo; one click on `#device-cancel` runs one cancel; Measure shows a distance label between two clicked points and clears on Esc.
- [ ] **Step 2: run, see them fail.**
- [ ] **Step 3: implement.**
- [ ] **Step 4: tests and neighbours pass.**

### Task 2: The dock and Properties

**Files:**
- Create: `chauffeur/static/twin/editor/dock.js` (tabs, splitter, Properties host, breadcrumb and back)
- Modify: `chauffeur/templates/house_editor.html`, `chauffeur/static/twin/editor/editor.css`, `chauffeur/static/twin/editor/editor.js`, `cards.js`, `terrain_tools.js`, `lot_tools.js`, `fixtures.js`, `effects.js`, `pauses.js`, `library.js`, `panel.js`, `timeline.js`, `edit_timing.js` (each renders into or reveals its dock home), `cards.js` (wall Length field; remove `cards.edge()`), `twin_view.js` only if the canvas sizing needs a hook
- Test: extend `chauffeur/tests/test_twin_editor_shell_js.py` (dock and Properties); neighbours `tests/test_twin_object_shelf_js.py`, `tests/test_twin_site_shapes_js.py`, `tests/test_twin_terrain_tools_js.py`, `tests/test_twin_lot_tools_js.py`, `tests/test_twin_line_point_handles_js.py`, `tests/test_twin_editor_library_js.py`, `tests/test_twin_edit_queue_editor_js.py`, `tests/test_twin_paver_card_js.py`

**Interfaces:** Produces `createDock({ host }) -> { show(tab), properties: { render(node, { crumbs, back }) , clear() }, onResize(fn) }`, the new ids in ruling 1.

- [ ] **Step 1: failing tests**: each card or shelf that showed for a selection kind renders inside `#dock-properties` (wall, room, opening, item, anchor, device fixtures, yard piece, pad, path with pavers, lot, building); an armed draw / device / roof / terrain / line tool shows its options in Properties; the breadcrumb for a device's fixtures reads the floor, room, device and Fixtures, and back returns to the device; opening the Library from `#rail-library` switches to the Library tab and keeps the scene selection; Argyle lives in its tab and "Ask Argyle" names the selection; History is folded under Properties; the wall Length field sends `move_joint` for `joints[1]`; with `?timing=1` the timing section shows under History; the canvas width equals the window minus the dock.
- [ ] **Step 2: run, see them fail.**
- [ ] **Step 3: implement.**
- [ ] **Step 4: tests and neighbours pass.**

### Task 3: Centred dialogs and right-click menus

**Files:**
- Create: `chauffeur/static/twin/editor/dialog.js` (one host), `chauffeur/static/twin/editor/context_menu.js`
- Modify: `houses.js`, `place.js`, `steps.js`, `library.js` (import settings), the house materials and Advanced entry points, `editor.js`, `scene_tools.js` (contextmenu on the canvas through the picker), `editor.css`, the template
- Test: extend `chauffeur/tests/test_twin_editor_shell_js.py` (dialogs and menus); neighbours `tests/test_twin_houses_js.py` (or the houses test that exists), `tests/test_twin_place_js.py` (or the Your place test that exists), `tests/test_twin_split_wall_js.py`, `tests/test_twin_mirror_js.py`, `tests/test_twin_picking_js.py`

**Interfaces:** Produces `openDialog(id, { title }) / closeDialog()`, `createContextMenu({ items(target) }) -> { open(clientXY, target), close() }`.

- [ ] **Step 1: failing tests**: opening Houses then House materials leaves only House materials open; Esc closes the dialog before touching a selection or a drag; Your place opens as a dialog with a tab per step and on its own for a new house; the front door shows as a dialog on an empty house; right-click on a wall offers exactly Select, Split wall here, Add door here, Add window here, Delete, and Split wall here sends `split_wall` at the clicked point after selecting the wall; right-click on a yard object offers the Move, Turn, Scale and Mirror entries; the material drop scope menu still appears at the drop point.
- [ ] **Step 2: run, see them fail.**
- [ ] **Step 3: implement.**
- [ ] **Step 4: tests and neighbours pass.**

### Task 4: Browser checks (Claude)

- [ ] Run the live editor suites and fix any test that addressed a moved control by position rather than id or name (never weaken an assertion): `tests/test_house_editor_live.py`, `tests/test_house_editor_steps_live.py`, `tests/test_twin_picking_live.py`, `tests/test_twin_precision_live.py`, `tests/test_twin_edit_fast_live.py`, `tests/test_twin_site_drawing_live.py`, `tests/test_twin_paver_paths_live.py`, `tests/test_house_editor_model_live_t15.py`, `tests/test_house_editor_model_live_t19.py` (t15 and t19 have known baseline failures; compare with main).
- [ ] New `tests/test_twin_editor_shell_live.py`: toolbar, dock tabs, Properties breadcrumb and back, a dialog, a right-click menu, canvas resize alignment (a handle drag after resizing the dock).
- [ ] Screenshots of the new layout on high for the owner.

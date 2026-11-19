# Editor slice 6: Library in the dock, and assigning — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The dock's Library tab becomes a picker with one selected asset; every slot in Properties that takes a Library asset becomes one shared row (swatch, name, "Use selected", clear) that assigns the selection, accepts a drag from the Library, and scrolls the Library to its current asset; asset actions (Edit in Library, Rename, Delete) move to an action bar for the selected asset and the right-click menu.

**Architecture:** `editor/library.js` gains a selection (`library.selected()`, `library.select(entry)`, `library.onSelect(fn)`, `library.reveal(kind, id)`) and an action bar under the grid. A new `editor/slot_row.js` builds the one row every slot uses; the two current slot UIs (the cards' "material lines" with Change / pick mode, and `material_slot.js` with its inline option list) and the door/window Model grid all render through it, keeping their existing operations. The drop menu at the drop point (dragging onto the 3D view) is untouched.

**Tech Stack:** plain ES modules under `chauffeur/static/twin/editor/`, `templates/house_editor.html`, three r187, node-driven tests, Chromium live tests.

**Spec:** `docs/superpowers/specs/2026-11-16-twin-editor-overhaul-design.md`, "Slice 6: Library in the dock, and assigning". The control inventory `docs/superpowers/notes/2026-11-18-editor-control-inventory.md` (section 13 `material_slot`, section 23 Library, rows 131-133, and the owner's ruling 8) says where each existing control goes. Slices 4 (dock, v2.499.940) and 5 (Scene and Layers, hide and lock) are shipped.

## Global Constraints

- Work in the slice 6 worktree only. Never edit `E:\repositories\Chauffeur`. Never touch `chauffeur/data`. Never open `*_api_key.txt`.
- Do not commit, do not bump `chauffeur/config.yaml`. Leave changes in the working tree and write the report file.
- Do not launch Chromium, Playwright or any browser; never use the user's browser.
- Tests run from `chauffeur/` as plain scripts with `HA_BASE_URL` unset. Run the named tests and neighbours, and before reporting run **every** node test that touches the editor (grep `tests/test_*_js.py` for `static/twin/editor/`, `house_editor.html`, `twin_editor_dom`, `from test_twin_drag_js`); compare any failure with main in a detached baseline outside the repo folder (never edit it).
- **Check against the real household fixture**, not only hand-written plans (slice 5's tree broke on the real house's scalar wall offsets): node tests that build Properties or the Library must also run over the household plan the live harness seeds.
- **Never remove anything a person can do.** Every assignment possible today stays possible: pick mode's "click a tile to apply" becomes "select, then Use selected" (or drag onto the row); the inline option list's per-material buttons become the Library selection; "Use default" becomes the row's clear; the tint override stays (ruling 3). Keep every element id and accessible name the browser suites use unless this plan names its replacement, and update those suites' locators in the same task.
- **The drop menu at the drop point stays exactly as it is** (owner ruling 8): dragging a material onto the 3D view, `#material-chooser` with its scope buttons, direct apply for parts, and item drops are unchanged.
- No browser dialogs (Delete keeps `promptConfirm`). Follow `chauffeur/docs/ui_design_guide.md`: one shared builder for the slot row. Rebuild Tailwind after template class changes. Vendored Alpine: coerce loop-variable boolean bindings with `!!`.
- No new texture sampler in any material; no server route or setting is needed.

## Rulings (Claude's calls within the spec)

1. **Selection.** A tile click selects that asset (`aria-pressed="true"`, a ring), replacing any previous selection; clicking the selected tile again, or Esc while the Library has focus, clears it. Selection is per editor session, survives tab switches and Library re-renders (by id), and clears if the asset disappears from the catalogue. Selecting never applies anything. Dragging a tile does not change the selection.
2. **The slot row** (`createSlotRow({ label, accepts, current, describe, apply, clear, reset, tint, library })`): a swatch (the current asset's thumbnail or colour; empty pattern when none), the current name (or "Default"), a **Use selected** button, a **Clear** button, and the optional reset ("Clear for this floor/building", existing behaviour) and tint controls. "Use selected" is disabled with the name "Use selected" when nothing suitable is selected, and enabled with the name "Use <asset name>" when the selection is of an accepted kind. Clicking the swatch reveals the current asset in the Library (switches the dock to Library, the right sub-tab, scrolls the tile into view, flashes its ring; does not select it). A Library tile dropped on the row applies it if accepted (the row highlights while a valid drag is over it). Accessible names keep the slot's subject: the existing "Change the X material" button becomes the swatch with the name "Show the X material in the Library", and "Use selected" carries `aria-describedby` to the row label.
3. **Tint override** (`material_slot.js` "Override tint" colour input and "Clear override") moves into the row unchanged, next to the swatch, only where it exists today. Slice 7 may reshape it; it is not dropped.
4. **Accepted kinds.** Material slots accept Library materials (any material; the existing quick-pick ordering becomes irrelevant). The door and window Model slot accepts Items-tab assets that are door models for a door and window models for a window (imports of kind door/window and manifest models of that kind); its clear means "Generated". No other slot kinds exist today (no light-profile, lamp-shape or species slots); the row builder must not assume materials only, so a later slot of another kind plugs in with its own `accepts`.
5. **Pick mode retires.** `library.pick(surface)` and the Change button's pick mode are replaced by the row; `library.pick` stays as a thin alias that reveals the Library for that surface's current material, so callers and tests that call it keep working until they are moved.
6. **Action bar.** Under the Library grid, for the selected asset: "Edit in Library" (materials; same link as today), "Rename <name>" and "Delete <name>" (imports; same calls as today, Delete still asks with `promptConfirm`), and "Clear selection". The per-tile Rename/Delete buttons and the per-tile "Edit in Library" link go; the right-click menu on a tile keeps offering the same actions for that tile (it already does). "Select hidden: name" and the equipment buttons stay where they are.
7. **Properties ↔ Library.** When a slot row is focused or hovered, nothing changes in the Library (no surprise scrolling); only the swatch click reveals. When the selection changes, every visible slot row updates its "Use selected" state without a Properties rebuild.

## Review Focus

1. A person who used Change → click a tile can still do it in two steps (select, Use selected) and by dragging the tile onto the row; nothing they could assign before is now unreachable (doors' and windows' Model, the yard parts, pad edges, foundations, porch foundations, house materials, glass panes, water).
2. "Use selected" with a material selected on the Model slot (wrong kind) stays disabled and says nothing will happen; a door model selected on a window's Model slot stays disabled.
3. The drop menu at the drop point behaves exactly as on main (same scopes, same operations, Esc closes it).
4. A selection survives switching dock tabs, a catalogue refresh and an undo, and clears if its asset is deleted.
5. The Library on the real household (hundreds of tiles) scrolls to a revealed tile in both sub-tabs.

---

### Task 1: Library selection, action bar and the slot row

**Files:**
- Create: `chauffeur/static/twin/editor/slot_row.js`
- Modify: `chauffeur/static/twin/editor/library.js` (selection, `select`, `selected`, `onSelect`, `reveal(kind, id)`, action bar, tile click selects, drag payload readable by rows), `chauffeur/templates/house_editor.html` (action bar host under `#library-entries`), `chauffeur/static/twin/editor/editor.css`
- Test: `chauffeur/tests/test_twin_slot_row_js.py` (new); extend `tests/test_twin_editor_library_js.py`; neighbours `tests/test_twin_editor_shell_js.py`, `tests/test_twin_material_slot_js.py`

**Interfaces:** `library.selected() -> {kind:'material'|'furniture'|'shrub'|'tree'|'door'|'window'|..., id, name, thumb} | null`; `library.select(entry|null)`; `library.onSelect(fn) -> unsubscribe`; `library.reveal(kind, id)`; `createSlotRow({ label, subject, accepts(entry) -> bool, current() -> {id, name, thumb, color} | null, apply(entry), clear(), reset?: {label, run}, tint?: {value, set, clear}, library }) -> { element, refresh(), dispose() }`.

- [ ] Failing tests: tile click selects and re-click clears; selection survives a tab switch and a catalogue re-render; selection clears when its asset leaves the catalogue; the action bar shows Edit in Library for a material and Rename/Delete for an import with the same calls as today (Delete through `promptConfirm`); the tile right-click menu still lists the same actions; slot row "Use selected" disabled/enabled with the names of ruling 2 and calls `apply` with the selection; a wrong-kind selection keeps it disabled; dropping a tile on the row applies an accepted asset and ignores another kind; the swatch click calls `library.reveal` with the current asset and switches the dock to Library; tint and reset controls appear only when given; `#material-chooser` drop behaviour unchanged.
- [ ] Run, fail, implement, pass. Rebuild Tailwind if classes change.

### Task 2: Every slot through the row

**Files:**
- Modify: `chauffeur/static/twin/editor/cards.js` (material lines), `library.js` `materialLines` (data only), `material_slot.js` (becomes a thin wrapper over `createSlotRow`, same callers and `onChange` contract), `object_shelf.js` (door/window Model grid becomes a Model slot row; the grid's buttons go), `house_materials.js`, `foundation_shelf.js`, `porch_foundation_shelf.js`, `site_shape_shelf.js`, `terrain_tools.js` (pad edge slots), `scene_tools.js` (`pickMaterial` callers), `editor.js` wiring
- Test: extend `tests/test_twin_item_slot_rows_js.py`, `tests/test_twin_material_slot_js.py`, `tests/test_twin_house_materials_panel_js.py`, `tests/test_twin_foundation_material_js.py`, `tests/test_twin_item_slot_drop_js.py`, `tests/test_twin_editor_library_js.py`, `tests/test_twin_editor_shell_js.py`; update the browser suites' locators (`tests/test_twin_glass_slots_live.py`, `tests/test_house_editor_model_live_t15.py`, `tests/test_house_twin_porch_foundation_live.py`, `tests/test_twin_objects_live.py`) to the new controls without weakening what they prove; neighbours: terrain, lot, pool features, site shapes, pad edges node tests

- [ ] Failing tests, one per slot site: the row renders with the current asset's name and swatch, "Use selected" sends exactly the operation the old control sent for the same choice (assert the op payloads equal), Clear sends the old clear/"Use default" payload, reset and tint keep their payloads; the door Model row accepts a door model and sends `{model:id}`, clear sends the "Generated" payload; the real household plan renders every slot site that exists in it without throwing.
- [ ] Run, fail, implement, pass.

### Task 3: Browser checks (Claude)

- [ ] New `tests/test_twin_library_assign_live.py`: select a material in the Library, select a wall, "Use <name>" assigns it (wall face material changes in the plan and on screen); drag a tile onto a room's floor row assigns it; the swatch reveals the tile in the Library; a door's Model row takes a door model; Rename and Delete from the action bar; the drop menu at the drop point still offers its scopes and applies.
- [ ] The editor browser suites stay green (main suite in its own order with the continue-past-failure runner, steps, picking, precision, edit-fast, glass slots, porch foundation, objects, t15 matching main's known failures).

# House editor: multiselect and clipboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The editor acts on sets: Ctrl-click and marquee selection in the view and the Scene tree, select by material, group move/turn/scale/delete/hide/lock as one undo step, Properties for a set (summary, narrow by kind, shared and Mixed fields, a materials-in-selection list that swaps a material across the set), and cut, copy, paste and duplicate with the owner's three paste modes.

**Architecture:** A selection store (`editor/selection.js`) holds an ordered list of piece references with today's single selection as its primary member, so every existing single-selection path keeps working. The shared picker and a new marquee feed it; the Scene tree mirrors it. Group edits become one server **batch** operation (all or nothing) wrapping the existing per-piece operations, so validation stays in one place and undo records one step. Properties gains a selection view built from slice 6/7's slot rows. A session clipboard (`editor/clipboard.js`) serialises copied pieces and pastes them through the batch operation.

**Tech Stack:** plain ES modules under `chauffeur/static/twin/editor/`, `templates/house_editor.html`, FastAPI ops in `chauffeur/services/twin_model_ops.py` (and the site/terrain/object op modules), three r187, node tests, Chromium live tests.

**Spec:** `docs/superpowers/specs/2026-11-19-editor-multiselect-clipboard-design.md` (owner-approved 2026-11-19), including "Claude's calls from the builder check" (they bind this plan). Builds on slices 4-7 of `docs/superpowers/specs/2026-11-16-twin-editor-overhaul-design.md`: read the top entries of `chauffeur/system_capabilities.md` for slices 4, 5, 6 and 7 before starting. **Execution starts after slice 7 lands: `git merge main` first.**

## Global Constraints

- Work in `E:\repositories\Chauffeur-editor-multiselect` only. Never edit `E:\repositories\Chauffeur`. Never touch `chauffeur/data`. Never open `*_api_key.txt`.
- Do not commit, do not bump `chauffeur/config.yaml`. Leave changes in the working tree and write the report file.
- Do not launch Chromium, Playwright or any browser; never use the user's browser. Claude runs the browser checks.
- Tests run from `chauffeur/` as plain scripts with `HA_BASE_URL` unset. Run the named tests and neighbours, then every node test touching the editor or the twin view; compare failures with main in a detached baseline outside the repo folder. Node tests also run over the real household fixture.
- No browser dialogs (`showGlobalAlert`, `promptConfirm`, `promptInput` only). Never remove anything a person can do; every slice 4-7 element id and accessible name stays. Every agent capability needs a hand path (the batch op is reachable by hand through these controls).
- Selecting is never an edit (no history entry). One person action = one operation = one undo step; a batch is all or nothing and a refused batch names the member and the reason in the status line.
- Hidden and locked pieces are never picked by click, marquee or select-by-material in the view; locked pieces are selectable only from the Scene tree (slice 5).
- Properties keeps its place on every rebuild for the same subject (`editor/keep_place.js`, owner rule 2026-11-19); a selection change that keeps the same members is the same subject.
- No new texture sampler or lit-material uniform (the GPU budget is full); selection highlighting reuses the existing selection outline.
- Performance: a 200-plant selection drags at under 33 ms a frame on the desktop (CPU test budget); the marquee tests projected bounds, never per-triangle picking.
- Rebuild Tailwind after template class changes. Follow `chauffeur/docs/ui_design_guide.md`. Vendored Alpine: coerce loop-variable boolean bindings with `!!`. Every new route has an auth rule; prefer extending the existing editor op route.

## Rulings (Claude's calls within the spec)

1. **Selection store:** `createSelection({ onChange }) -> { members(): Ref[], primary(): Ref|null, set(refs), add(ref), remove(ref), toggle(ref), clear(), has(ref), kinds(): Map<kind, Ref[]>, narrow(kind), subscribe(fn) }`, `Ref = { kind, pieceId, buildingId?, slots? }` (`slots` = the slot names matched by select-by-material). `primary()` is the last member added; existing code reading the single selection reads `primary()` unchanged.
2. **Marquee:** starts on empty space with the Select tool after 4 px of movement; a translucent rectangle overlay (existing editor overlay layer); on release, members = visible, unlocked pieces whose projected screen bounds lie entirely inside; plain = replace, Ctrl = add, Alt = remove; floor/room views consider that floor and the yard only. Instanced plants are tested per instance.
3. **Batch operation:** `{op: 'batch', ops: [...]}` applied atomically by the server (validate every member first, then apply; any refusal returns `{error, member, reason}` and changes nothing), recorded as one history entry; the client edit queue treats it as one step (slice 2's queue, drop-and-name applied to the batch).
4. **Group transforms by kind** follow the spec's table (free / slide along wall / with joints / within pool / not movable); not-movable members stay selected and are skipped by the gizmo; the gizmo pivots on the bounds centre of the movable members.
5. **Properties for a set:** a summary line ("3 walls · 2 trees · 1 window · 1 light"; click narrows, Ctrl-click removes the kind); materials-in-selection list (swatch, name, slot count; **Use <Library selection>** writes overrides on each matching slot keeping tint and UV offset; **Select all using it**; **Show in Library**); one kind: shared fields edited together with "Mixed" for differing values; mixed kinds: summary, materials list, shared actions and "Narrow to <kind> (n)" buttons. A single selected piece also shows its materials list (above its slot rows).
6. **Clipboard:** `createClipboard() -> { copy(refs), cut(refs), paste({ mode, target, point }), duplicate(refs), canPaste(target): {ok, reason}, contents() }`; session-only; serialises piece records (model, size, materials, tint, UV offset, settings) with positions relative to the set's centre; paste mode resolution and kind rules exactly per the spec's calls 4-7; device-bound pieces lose their binding on copy (status line says so); the first paste after a cut reuses the original ids.
7. **Keys and menus:** Ctrl/Cmd+C, X, V, D (outside text inputs, not while a dialog is open), toolbar Copy and Paste buttons, right-click Copy / Cut / Paste / Duplicate / Copy material / Paste material / Select all using <material>; Esc clears a marquee in progress before the selection (slice 4's Esc order).

## Review Focus

1. Ctrl-click on a thing already selected removes it, and a plain click on empty space clears the whole set, with no history entry.
2. A batch that includes one refused member (a window that no longer fits) changes nothing and names the member.
3. Pasting a window with the original still selected lands it beside the original on its own wall (mode 3), never inside it.
4. Properties keeps its scroll and focus when Ctrl-click adds a member of the same kind.
5. Cut, then paste, keeps the pieces' hide/lock state and device binding; undoing the cut restores the originals.

---

### Task 1: The selection store, Ctrl-click, marquee, Scene tree multi-select

**Files:**
- Create: `chauffeur/static/twin/editor/selection.js`, `chauffeur/static/twin/editor/marquee.js`
- Modify: `editor/picking.js` callers and `editor/scene_tools.js` (Ctrl-click toggles; plain click replaces; empty click clears), `editor/scene_tree.js` (Ctrl and Shift click; rows mirror the store), `editor/editor.js` (wiring; `primary()` feeds every existing single-selection path), the selection outline in the view (all members outlined)
- Test: `chauffeur/tests/test_twin_selection_js.py` (new)

**Interfaces:** Produces `createSelection` (ruling 1) and `createMarquee({ view, selection, visibility, getPlan }) -> { pointerDown(event), pointerMove(event), pointerUp(event), cancel() }`.

- [ ] Failing tests: Ctrl-click adds and removes; plain click replaces; empty click clears without a history entry; marquee replace/add/remove with whole-inside rule on the household (walls, plants by instance, openings, fixtures); hidden and locked skipped; floor view limits to that floor and the yard; Scene tree Ctrl/Shift click mirrors the store and the view; `primary()` keeps every existing single-selection test passing (Review Focus 1).
- [ ] Run, fail, implement, pass.

### Task 2: The batch operation and group transforms

**Files:**
- Modify: `chauffeur/services/twin_model_ops.py` (the `batch` op of ruling 3, atomic, one history entry), the editor op route if needed, `editor/gizmo.js` and `editor/scene_tools.js` (group move/turn/scale about the movable members' centre per the kind table), delete/hide/lock for a set (`editor/visibility.js` users), the edit queue
- Test: `chauffeur/tests/test_twin_batch_ops.py` (new; TestClient through the real op route: atomic apply, a refused member changes nothing and names it, one undo step, redo), `chauffeur/tests/test_twin_group_transform_js.py` (new; kind table, pivot, not-movable members skipped, 200-plant drag under the CPU budget)

**Interfaces:** Consumes Task 1's store. Produces `applyBatch(ops) -> Promise` in the editor's op path.

- [ ] Failing tests including Review Focus 2.
- [ ] Run, fail, implement, pass.

### Task 3: Properties for a set, the materials list, select by material

**Files:**
- Create: `chauffeur/static/twin/editor/selection_card.js`
- Modify: `editor/cards.js` (single-piece materials list above slot rows; set view when more than one member), `editor/slot_row.js` users (a slot row acting on the same slot of every member), `editor/context_menu.js` users (Select all using <material>), `editor/editor.css`, the template if needed
- Test: `chauffeur/tests/test_twin_selection_card_js.py` (new: summary text and counts on the household; narrow and remove by kind; Mixed fields and setting all; materials list counts slots (inherited included) and Use writes overrides keeping tint and UV, one batch; Select all using it selects owning pieces with matched slots; keep-place on adding a same-kind member, Review Focus 4)

**Interfaces:** Consumes Tasks 1-2 and slice 7's `resolveSurfaceMaterial`.

- [ ] Failing tests, run, implement, pass. Rebuild Tailwind if classes change.

### Task 4: Cut, copy, paste, duplicate, copy material

**Files:**
- Create: `chauffeur/static/twin/editor/clipboard.js`
- Modify: `editor/editor.js` and `editor/scene_tools.js` (keys of ruling 7), the toolbar (Copy, Paste buttons with icons), `editor/context_menu.js` users (menu items), `chauffeur/services/twin_model_ops.py` only if a create path cannot accept an explicit id (cut's first paste reuses ids)
- Test: `chauffeur/tests/test_twin_clipboard_js.py` (new: each kind of the spec's copy table round-trips with everything it carries; the three paste modes and their resolution rule; sets keep arrangement; openings re-host per call 5 including refusal when they do not fit; device binding dropped on copy and kept by cut's first paste (Review Focus 5); mode 3 offset never overlaps the original (Review Focus 3); can't-land reasons in the status line; Copy material / Paste material onto a slot and onto every same-kind slot of a set; one batch per paste)

**Interfaces:** Consumes Tasks 1-3. Produces `createClipboard` (ruling 6).

- [ ] Failing tests, run, implement, pass.

### Task 5: Browser checks (Claude)

- [ ] New `tests/test_twin_multiselect_live.py`: Ctrl-click three walls and assign a material from the Library to all (one undo step); marquee a group of plants, drag them, undo; select by material and swap it from the materials list; copy a window, right-click another wall, Paste (lands at the click); select a wall and Ctrl+V; Ctrl+C, Ctrl+V on a tree (offset copy, selected); Ctrl+D; cut and paste a device anchor (binding kept); mixed set summary and narrowing; Properties keeps its place when Ctrl-click adds a member.
- [ ] The editor browser suites stay green (main suite in its own order, steps, picking, precision, edit-fast, scene and layers, library assign, surface slots, glass slots).

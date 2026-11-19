# House editor: add a porch by hand — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** A person can add a porch without Argyle: an "Add porch" tool that draws a porch against an exterior wall with a roof in one step, and a Type choice (Room / Porch) on a room's card.

**Why:** Owner, 2026-11-19: "Is there a tool for adding a porch? ... I don't see any way to do it. The agentic building process can do it so there is clearly a tool somewhere for it." Repository rule: every agent capability needs a hand path. Owner approved this change in chat (2026-11-19) and asked for it before multiselect.

**What exists:** the build pipeline writes a porch as a room with `kind: 'porch'`, a `porches_detail` entry (columns, optional screen) and a porch foundation (`services/twin_porches.py` `DEFAULT`), see `services/twin_model_bridge.py` around line 805; its roof is a normal roof (`roof_over` / `draw_roof` ops in `services/twin_model_ops.py`). The editor shows and edits porches (card, `porch_foundation_shelf.js`, column/screen material slots, porch ceiling) but cannot create one: `draw_room` makes ordinary rooms and the room card has no type field (`static/twin/editor/cards.js` fields, `room: ['name', 'floor_offset_ft']`).

## Global Constraints

- Work in `E:\repositories\Chauffeur-editor-porch` only. Never edit `E:\repositories\Chauffeur`. Never touch `chauffeur/data`. Never open `*_api_key.txt`. Do not commit; do not bump `chauffeur/config.yaml`. Do not launch any browser.
- Tests from `chauffeur/` as plain scripts with `HA_BASE_URL` unset; named tests, neighbours and every editor/twin-view node test vs main in a detached baseline; node tests also over the real household fixture.
- One person action = one operation = one undo step. A hand-made porch is identical in data to one the build makes (same room kind, porch detail, foundation default, roof representation), so every existing porch feature works on it.
- No browser dialogs; follow `chauffeur/docs/ui_design_guide.md`; reuse the toolbar, tool options in Properties, and status-line patterns of slices 3b/4 (Draw room is the model). Rebuild Tailwind after class changes. Keep every existing id and accessible name. Properties keeps its place (`editor/keep_place.js`).
- The `house_design` agent tool schema is not changed. Never remove anything a person can do.

## Rulings (Claude's calls)

1. **Op `add_porch`** `{building, level, polygon, roof: 'shed'|'gable'|'none', host_wall?}`: creates the porch room (`kind: 'porch'`, name "Porch", the level, the polygon, `foundation = twin_porches.DEFAULT`), its `porches_detail` entry (square columns, not screened), and for `shed`/`gable` a roof over that room through the same code path as `roof_over` (shed: the low side on the edge farthest from the host wall, pitch 3:12, overhang 1 ft; gable: ridge perpendicular to the host wall, pitch 6:12). All in one op and one history entry. Refusals in words: "Draw the porch against an outside wall.", "A porch needs at least 4 by 4 feet.", "That overlaps a room on this floor."
2. **Op `set_room_kind`** `{building, room, kind: 'room'|'porch'}`: to porch, adds the porch detail and default foundation if missing; to room, removes the porch detail and foundation and keeps everything else (walls, roof, materials). One history entry.
3. **The tool:** toolbar button "Add porch" (structure group, after Draw room; an icon in `editor/icons.js`, accessible name "Add porch"); options in Properties while armed: Roof (Shed / Gable / None). Gesture as Draw room: drag a rectangle or click corners and close; the shape must share an edge with an exterior wall of the current floor (snap to that wall within 1 ft); status line guides ("Drag out from an outside wall."). On success the new porch is selected (its card opens).
4. **Type on the room card:** a Type field (Room / Porch) for every room, sending `set_room_kind`.

## Task 1: Server operations

**Files:** `chauffeur/services/twin_model_ops.py` (ops, refusals, history messages "Added the porch." / "Made this room a porch." / "Made this porch a room."), reuse `twin_porches` and the `roof_over` path. **Test:** `chauffeur/tests/test_twin_add_porch_ops.py` (new; TestClient through the real op route: the porch equals the build's representation field by field for the same polygon; shed and gable roofs exist over it with the stated pitches; none adds no roof; refusals; one undo removes porch and roof together; set_room_kind both ways keeps walls and roof; round trip through save/load).

- [ ] Failing tests, run, implement, pass.

## Task 2: The tool and the Type field

**Files:** `editor/draw.js` (the tool), toolbar markup in `templates/house_editor.html`, `editor/icons.js`, `editor/cards.js` (Type field), `editor/editor.css` if needed. **Test:** `chauffeur/tests/test_twin_add_porch_js.py` (new; the tool against the household: a rectangle from an exterior wall sends exactly the op of ruling 1 with the chosen roof; a shape not touching an outside wall refuses with the status text; the porch is selected after save; the Type field sends ruling 2's op; existing ids and names kept), extend `tests/test_twin_editor_shell_js.py` (the toolbar button).

- [ ] Failing tests, run, implement, pass.

## Task 3: Browser check (Claude)

- [ ] `tests/test_twin_add_porch_live.py`: draw a porch with a shed roof against the household's main house, see it with posts and roof; change its foundation and columns material; undo removes it; draw a room and make it a porch with Type; the editor suites stay green.

## Task 1b: Deleting a porch removes all of it (owner report 2026-11-19)

Owner: "I tried to delete an existing porch and it deletes something, but it leaves the geometry there without all the porch-specific parts and data. The remaining thing is called something like Porch:porch* where * is some long ID. This thing that is left cannot be deleted. You get an error saying the thing doesn't exist."

Cause (Claude): `services/twin_model_ops.py` `_delete` removes a porch room and its exclusive walls but not the building's porch record (`porches_detail`, legacy `porches` / `porch`), which `allPorches` still draws; a selection of that leftover (kind `porch`, id `porch...`) reaches `_delete`, which searches neither collection and refuses "That piece is missing.".

**Rulings:** deleting a porch room also removes its porch record(s) with the same id (every collection `allPorches` reads); deleting a porch record whose room is gone removes the record (so existing leftovers in households can be cleaned up by hand); deleting a porch record whose room exists deletes both; one operation, one undo step, history message "Deleted the porch."; the porch roof stays (it is an ordinary roof the person can delete separately; Claude's call). Load-time repair is NOT added (nothing disappears without the person's action).

**Test:** extend `chauffeur/tests/test_twin_add_porch_ops.py`: delete a build-made porch room (household or poolhouse fixture with a porch) leaves no porch record and nothing porch-specific drawn (generator: no porch slab/posts for that id); delete a leftover porch record (fixture with a record and no room) succeeds; undo restores room and record together; the editor's Delete on a porch selection sends the op that removes both.

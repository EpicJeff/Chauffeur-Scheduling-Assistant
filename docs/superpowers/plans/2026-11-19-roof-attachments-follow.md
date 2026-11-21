# Roof attachments follow roof edits — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Editing a roof never refuses because a solar zone (or other roof attachment) sits on it: each attachment edge stays docked to its roof plane and the attachment moves and resizes with the roof.

**Why (owner, 2026-11-19):** "Why can't roofs be edited when they have something attached to them, like a solar zone? If a wall has a door or window on it, you can still move it. The solar zone (or anything attached) should just follow it and resize itself if necessary. You could just treat each edge of the solar zone as being docked to the roof at that point. So, if it is 2 ft from the edge and you drag the roof edge, the solar zone resizes to stay 2 ft from the roof's edge." Claude's design was stated to the owner in chat (2026-11-19).

**Today:** `services/twin_model_ops.py` `solar_clear(building, previous)` (around line 1306, called at line ~1627 after every building op) refuses any roof change after which a zone fails `twin_solar.error` ("That would move a solar zone off its roof plane. Move or delete the zone before changing the roof."); `_delete` refuses deleting a roof that has zones. Zones are rectangles `rect = [x, y, X, Y]` in a roof plane's orthonormal coordinates (feet), with `roof` and `plane` (`services/twin_solar.py`: `faces`, `basis`, `point`, `project`, `rectangle`, `clip`). Dormers already follow (`_follow_dormers`).

## Global Constraints

- Work in `E:\repositories\Chauffeur-roof-dock` only. Never edit `E:\repositories\Chauffeur`. Never touch `chauffeur/data`. Never open `*_api_key.txt`. Do not commit; do not bump `chauffeur/config.yaml`. Do not launch any browser.
- Tests from `chauffeur/` as plain scripts with `HA_BASE_URL` unset; named tests, neighbours (solar, roof ops, roof edges, dormers, the solar ribbon/energy tests) and every roof/editor node test vs main in a detached baseline; tests also over the real household fixture and the poolhouse fixture.
- One person action = one operation = one undo step; the zone's change is part of the same history entry as the roof edit.
- Every agent capability needs a hand path and vice versa: the agent's roof ops get the same following (they share the op path).
- Never remove anything a person can do; a refusal remains only where the result would be unusable.

## Rulings (Claude's calls, as told to the owner)

1. **Docking:** before applying a roof op, for every zone on an affected roof, record each of its four edges' signed distance to the nearest parallel boundary edge of its plane polygon (in the plane's own coordinates; for non-parallel boundaries, distance along the zone edge's normal to the boundary at the zone edge's midpoint). After the op, find the zone's plane on the changed roof (same section/side identity; fall back to the face whose normal is within 10 degrees and that overlaps the old zone's projected footprint most), recompute its polygon, and place each zone edge at its recorded distance from the corresponding boundary edge. The zone's `plane` and `rect` update in the same op.
2. **Moves of the whole roof or building** (and pitch, plate, overhang, ridge changes) re-derive the same way, so offsets measured along the slope are preserved.
3. **Minimum size:** if a zone would end up smaller than one panel (`panel_width` by `panel_height` in its orientation, from `twin_solar.DEFAULTS` or the zone's own values) or its plane disappears, refuse with the zone named: "That leaves the solar zone on <roof name> too small; resize or delete it first." (or "... its roof plane would be gone ..."). Other zones must not overlap after re-fitting; if two would overlap, shrink the later one's facing edge to touch the first (Claude's call) and refuse only if that makes it smaller than one panel.
4. **Deleting a roof deletes its zones** in the same op and undo step; history message "Deleted the roof and its solar zones." (replaces today's refusal).
5. **Other roof attachments:** audit everything that references a roof (`roof` field on any piece, roof-hosted equipment such as `add_equipment` kinds placed on roofs, the solar ribbon source `model['solar_source_roof']`); give each the same following (or, for a point attachment, keep its position projected onto the new plane and refuse only if it falls off the roof). List every kind found and what was done in the report.

## Task 1: Docked following on the server

**Files:** `chauffeur/services/twin_model_ops.py` (replace the `solar_clear` refusal with re-fitting before validation; roof delete), `chauffeur/services/twin_solar.py` (helpers: `dock_offsets(face, rect)`, `refit(face, offsets) -> rect`), anything the audit of ruling 5 finds. **Test:** `chauffeur/tests/test_twin_roof_attachments.py` (new; through the real op route: drag an eave edge 3 ft and the zone keeps 2 ft to it while its other edges keep theirs; change pitch, overhang, plate and ridge and the zone keeps its along-slope offsets; move the building and zones follow; shrinking below one panel refuses naming the zone; plane removal refuses; two zones never overlap after re-fit; deleting a roof deletes its zones in one undo step and undo restores both; the household's and poolhouse's roofs with seeded zones survive a set of edits with zones valid; the agent op path gets the same behaviour). Update `tests` that asserted the old refusals explicitly (list them; these change by owner decision).

- [ ] Failing tests, run, implement, pass.

## Task 2: Browser check (Claude)

- [ ] Drag a roof edge with a solar zone on it in the editor: the zone resizes and stays docked; undo restores both; delete the roof and the zone goes with it.

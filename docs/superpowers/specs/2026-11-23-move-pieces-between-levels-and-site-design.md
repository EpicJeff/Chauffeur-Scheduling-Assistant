# Move placed pieces between levels, buildings and the site

Date: 2026-11-23. Size: small change (short design). Status: for owner approval.

## Intent

The owner, 2026-11-23: placed models are tied to their building or the site, so "you can't move something placed in the house outside or vice versa. In Live Home 3D, there were actions for moving objects between floors or to the site (ground)." Owner choice: explicit actions only, no re-linking on drag.

Today a building piece lives in `plan.buildings[].items[]` and hangs off a host: a room's floor or ceiling (the room fixes the level), a wall, a roof edge, or the ground. A yard piece lives in `plan.site.furniture[]` at a lot point. No action moves a piece between them. Dragging only re-hosts within the same level (`editor/gizmo.js` `moveHost`).

## Goals

- **Move to ▸** offers every other place the piece can go:
  - `Site`;
  - each level of each building, e.g. `House · Upper floor` or `Pool house · Ground floor`.
- It is offered in the selection card and in the right-click menu next to Duplicate.
- The piece keeps its spot on the plan (same lot x/y), its facing in the world, and its height above whatever it now stands on (floor or ground).
- A multi-selection moves together as one undo step.
- The piece keeps its id. Its selection, hidden or locked state, and properties (tint, scale, shadow, object kind, light link) carry over.
- After the move, the editor switches to the destination level or the site, and the piece stays selected.

## Non-goals

- Re-linking while dragging.
- Moving wall- or roof-hosted pieces: they belong to that wall or roof. Their Move to entry is shown disabled, with the reason.
- Moving plants (`site.planting`): they are site-only kit plants.
- Moving devices, openings or lights.

## Behaviour

- **To another level, the same building or another one:**
  - The piece lands on the floor of the room under its spot on that level.
  - A ceiling-hosted piece lands on that room's ceiling.
  - Same building: one `move_hosted` op. Another building: `delete` plus `add_item` with the same id in one batch.
- **To the site:** `delete` plus `add_site_item` (list `furniture`, same id) in one batch. The lot point comes from `hostPoint` through the building transform. Rotation becomes lot-relative, and elevation becomes the offset above `groundAt`. These are the same conversions the clipboard already uses (`editor/clipboard.js:298-337`).
- **From the site into a building level:** `delete_site_item` plus `add_item` with a floor host in the room under the spot, in one batch.
- **If any selected piece cannot move:** no room under its spot on the target level, a wall- or roof-hosted piece, or a ceiling piece sent to the site. Then nothing moves, and the editor says which pieces and why, through the shared alert (no browser dialog).

## Approach

The move is built in the editor from existing server ops, sent through `applyBatch`, so it is one undo step. There is no new server op.

- A new module, `static/twin/editor/move_to.js`:
  - `moveTargets(plan, refs)` lists the destinations;
  - `moveOps(plan, refs, target)` returns the ops, or the refusal reasons.
- It reuses the clipboard's `world`, `local`, `hostedAt` and rotation helpers, moved into a shared helper so they are not copied a fifth time.
- Argyle can already do the same thing with a `batch` of the same op pairs. Its edit-tool description gains one line saying how to move a piece between a building and the site while keeping its id.

## Tests

- Node tests on `moveOps`:
  - building to site keeps the lot point, world facing and height above the ground;
  - site to building lands in the right room;
  - a move between levels lands in the right room on the new level;
  - wall, roof and no-room cases are refused, and nothing moves;
  - a multi-selection produces one batch.
- One Chromium editor check:
  - right-click, Move to, Site;
  - the piece is on the site list in the same spot;
  - one undo brings it back.

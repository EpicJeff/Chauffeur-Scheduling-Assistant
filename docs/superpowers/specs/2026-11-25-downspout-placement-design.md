# Downspouts: full drops where there is room, and one placed anywhere by hand

Owner, 2026-11-24: "Most of the downspout location are good. Two spots just have a tiny start of a downspout and there is no way to do anything other than remove the downspout completely and have none. There is nothing that I can see preventing it from creating a downspout there either." Owner, 2026-11-25: "Build all 3".

## Cause (owner's export, main v2.499.1001, gutters on every eave: 22 runs, 22 downspouts, 7 stubs)

- Corner (70, 23): the garage door ends exactly 1.0 ft from the corner, and `distance <= openingClearFt + EPS` refuses it.
- Corner (43.33, 66.33): `mountAt` picks one face of the corner. A window is 0.26 ft from the corner on that face. The other face has 3.84 ft clear and is never tried.
- The other five: three 1.2 ft slivers just above a lower roof, one porch end with no wall or post in reach, and one shed eave clipped by other roofs at both ends. Automatic placement may keep these as stubs.

## Part 1: both faces of a corner

`candidate()` with a corner tries every mount wall that meets that corner (`edgeDistance(corner, wall) < .05`), in the existing preference order, and keeps the first that is not blocked. Without a corner nothing changes.

`openingCheck` measures along the wall from the pipe's true position, not the position clamped to the wall's end. A pipe round the corner is therefore farther from the opening.

## Part 2: 1 ft from openings, 0.5 ft before a stub

- Clearance is refused only when strictly inside it: exactly 1.0 ft passes.
- A run's candidates are gathered in this order, and the first non-empty set wins:
  1. outside corners at 1 ft;
  2. outside corners at 0.5 ft;
  3. free ends at 1 ft (existing `no-outside-corner` rule);
  4. free ends at 0.5 ft;
  5. the existing stub fallback.
- `GUTTER.openingClearMinFt = 0.5` is a named constant. No new flag for 0.5 ft.
- A run with any 1 ft corner keeps exactly its present candidates and result.

## Part 3: placed by hand

**Record.** An entry of `downspouts` (roof edge, at most 8) is either
- a number 0..1: unchanged, snaps to the nearest safe corner; or
- `{"at": f}` with f a number 0..1 and no other key: stays exactly at that fraction of the authored edge.

Stored numbers keep their meaning, so no existing downspout moves. `null` is automatic, `[]` none. Every path that carries, validates, mirrors, remaps, migrates, reverts or reads `downspouts` accepts both. Invalid entries are refused with a message by the operation and dropped with a note by the plan reader. Argyle's `set_roof_edge` documents both.

**Placement of `{at}`.**
- The point is the nearest point to that fraction on an exposed segment of that edge. A fraction on a hidden or clipped piece moves to the nearest exposed point of the same edge.
- It never depends on `valid`, corner claims or the run's target count. It never merges with another override. An automatic downspout is not added within 1 ft of one.
- Mount: nearest wall or porch post within the existing reach, at the projection. If none is in reach: a freestanding vertical pipe straight below the outlet, `mount: 'free'`, ending in the normal elbow facing outward.
- It is always a full drop to the receiving surface, whatever it passes. Only a surface closer than the existing minimum drop below the gutter still yields the short spill (`outlet-blocked`).
- Output: `source: 'override'`, `authoredFraction: f`, `exact: true`, `edge.fraction` is the placed fraction.
- Flags, which only inform and can be acknowledged with `gutter_ack`:
  - `placed-off-corner`: not within 1 ft along the eave of a safe outside-corner candidate of its run;
  - `over-opening`: within 0.5 ft of an opening it passes;
  - `no-support`: `mount: 'free'`;
  - `no-safe-landing`: as today.
  `hang` and `stub` are never set on one.
- Both new-flag spellings join `GUTTER_FLAGS` (server), the Check texts and Argyle's flag list.
- Run drainage, shares, pours and `drainsTo` treat it as an ordinary outlet.

**Every placed output also carries `authoredIndex`** (its index in the edge's `downspouts` list) when `source` is `override`, so the editor maps a handle to its entry without matching fractions.

**Editor.**
- Dragging a downspout handle: the handle follows the pointer along the edge. Within 1 ft (along the edge) of a safe candidate of that edge it snaps to that candidate and stores the candidate's number. Elsewhere it stores `{"at": f}`.
- Right-click removes, as now. A stub can be dragged like any other.
- **Add downspout** uses a free safe corner when there is one, otherwise `{"at": f}` at the middle of the longest exposed piece of the edge, at least 1 ft from every existing entry. It is disabled only at 8 or when no such place exists.
- The numeric field stays. For an `{at}` entry the row says "Placed by hand" and editing the number keeps it `{at}`. A number row gains a small "Keep exactly here" button that turns it into `{at: current placed fraction}`; an `{at}` row gains "Snap to a corner", which turns it into the number. Labels use the card's existing button style.
- Reset to automatic clears both kinds. One drag, add, remove or convert is one undo step.
- Check texts:
  - `placed-off-corner`: "This downspout was placed by hand away from an outside corner."
  - `over-opening`: "This downspout passes a door or window."
  - `no-support`: "This downspout has no wall or post to fasten to."

## Not changed

Automatic placement still uses outside corners only, never mid-run, never an inner corner. Porch gutters have no per-downspout hand control today and gain none. `gutterPlacement(plan)` stays the one content-keyed cache: no second placement pass per edit, per drag move or per frame. No new draw, program or sampler.

## Cost gates

On the owner's export with every gutter on: placement time cold and warm no worse than 10% over main (median of 5). 0 draws, 0 programs, 0 samplers. Triangles: report.

## Split

- **Codex** (worktree `Chauffeur-downspouts`): parts 1 and 2, record, validation, placement, drawing of `mount: 'free'`, Argyle text, tests.
- **Gemini** (worktree `Chauffeur-downspouts-ui`): editor half of part 3 and its tests, against this contract.
- **Claude**: contract, reviews, browser checks and pictures, merge, landing.

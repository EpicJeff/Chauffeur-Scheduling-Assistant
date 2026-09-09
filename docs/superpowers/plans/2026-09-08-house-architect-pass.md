# The Home — Architect Pass Implementation Plan (v2.466.x)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the house so it works as a HOUSE (user ruling 2026-09-08 evening): open floorplan where the kitchen flows into a same-scale living room in front; mudroom slotted between garage and great room with an open doorway from the kitchen; pantry as a real closet behind a door; correct gable roofs including the garage; cars rebuilt to the reference-pack standard (extruded silhouettes); a showcase lighting pass toward the ceiling of this stack.

**Fidelity ruling answered honestly (recorded):** the reference render (offline GI) is not reachable in a forward renderer; the target is ~70% of its feel on the high tier — reference-car-pack geometry quality everywhere, tuned lighting, contact-shadow discipline. Pi tiers keep today's costs.

**Spec:** `docs/superpowers/specs/2026-09-08-house-design.md` (this pass amends its room table; H4 unchanged and still last).

## Global constraints
As H1–H3 (arc opens **2.466.0**; bump+commit+push per task; sweep before code commits; fidelity ruling; render-on-demand; frozen /kitchen; zone keys frozen: door/radio/pet/board/garage/curb).

## Layout decisions (world coords)

- **Great room**: kitchen slab + forward-left extension x −7.0..2.4, z 5.7..14.1 (slab box 9.4×8.4 at (−2.3,−0.27,9.9), top y −0.02). **ONE WOOD FLOOR THROUGHOUT** (user ruling mid-plan: no flooring transitions in a modern house) — a new `plankTex` (board rows, offset seams) replaces the kitchen checkerboard AND covers the extension, the mudroom and the pantry; no threshold strip. West wall + siding facade EXTEND to z 14.2. Front/right edges open (cutaway). Living furniture (hearth, sofa, rug, coffee table + crit, radio shelf, lamp) re-placed in the extension; right-back living WING DELETED. Decorative front door on the west wall's forward segment (z ≈ 12.6) + path strips to the street.
- **Garage** shifts WEST by 2.0 (x −14.8..−9.2; every garage mesh, parking spots, driveway → x −12.0, GARAGE_POS/AT x −2.0) and gains a GABLED roof: ridge along z at x −12.0, y ≈ 6.3; east/west shingle slopes to eaves y ≈ 4.85; siding gable triangles front (z 10.1) and back; whole roof lives with the front pieces in garageDoorG (hidden inside).
- **Mudroom** BETWEEN garage and great room: x −9.2..−7.0, z 2.4..9.6; floor slab, north/south walls, its own flat roof (hide-on-enter, `mudroomRoofG` only — garage no longer part of the mudroom's hide list); bench/hooks/coat/bags along the garage-side wall; DOOR ZONE on the south wall facing INTO the room (rotation.y = π — the hero card reads from inside), the driveway right outside. Open DOORWAY cut in the kitchen west wall at z 2.8..4.4 (both the interior wall box and the exterior facade split into two + header + casing) — from the kitchen you see the bench through it.
- **Pantry**: bump-out closet x −8.6..−7.0, z −1.7..0.5, h 3.4, sealed (mini siding walls + tiny roof) except a paneled DOOR in the kitchen wall at the old corkboard spot (z −0.6). Zone 'board': `focused === 'board'` hides the door (micro dollhouse trick) revealing interior shelves + the 8 honest jars (moved in). boardFace invisible plane sits in the doorway for the overlay quad. The open-shelf unit is removed.
- **Main roof read**: cross-section fascia board (16.4 × 2.34) at z −1.98 filling y 6.9..9.24 (the sliced-house read), RIGHT gable triangle mirroring the left at x ≈ +8.35.
- **Cameras**: LIV (8.5, 11, 20) → (−2.5, 1.0, 9.5); MUD (−8.1, 11, 12.5) → (−8.1, 0.9, 5.5); EXT re-aimed by probe (house is longer now). ZONE_ROOM: board → kitchen (unchanged mapping — the pantry door hangs on the kitchen wall).
- **Cars v2** (`buildCar` rewrite): per-body SIDE-PROFILE point lists (length/height plane) → `T.Shape` → ExtrudeGeometry (depth = width − 0.2, bevel 0.06) for the body; a second narrower extrude for the glass cabin (pokes 0.01 per side = side windows); bumpers, DETAIL≥2 grille + wheel-arch discs + hubcaps, DETAIL≥3 lights; truck bed stays open; bus gets the same treatment. Verify each of the 7 profiles by seeded screenshot.
- **Showcase pass** (high tier only): sun to (14, 16, 8); exposure 1.05; two extra warm points (hearth, living); kitchen tile roughness 0.35 + envInt up; extra prop set in the living zone.

## Tasks (each: probe screenshots → full sweep → bump → commit → push)

- [ ] **T1 (2.466.0)** Great room: slab/floor/wall/facade extension, threshold, wing deletion, furniture re-place, front-door decor + path, LIV camera, room tags. Probes: exterior, living, kitchen (open-concept view shows the living zone on purpose now — verify it composes rather than intrudes). Commit `The kitchen learns to flow (v2.466.0)`.
- [ ] **T2 (2.466.1)** Garage west + gable; mudroom between + doorway cut + door zone on the south wall; cameras. Probes: exterior (gable reads), mudroom (bench + door + hero card), kitchen (doorway shows the bench). Commit `The mudroom finds its place between (v2.466.1)`.
- [ ] **T3 (2.466.2)** Pantry closet + door + hide-on-focus + jars. Probes: kitchen (door where cork was), board lean-in (door swings away, jars behind, shopping card mounts). Commit `The pantry gets a door (v2.466.2)`.
- [ ] **T4 (2.466.3)** Main-roof fascia + right gable; EXT reframe. Probe: exterior. Commit `The roof learns which way is down (v2.466.3)`.
- [ ] **T5 (2.466.4)** Cars v2 + bus v2. Probes: garage interior + driveway overflow + curb bus, all 7 bodies seeded once. Commit `Cars earn their silhouettes (v2.466.4)`.
- [ ] **T6 (2.466.5)** Showcase lighting pass. Probes: high-tier exterior + great room, before/after eyeball. Commit `The light learns to pool (v2.466.5)`.
- [ ] **T7 (2.466.6)** test_house_live.py updated (pantry lean-in leg added; existing legs re-verified), HOUSE_SHOTS run, full set READ + sent to user. Commit `The rebuilt house answers in chromium (v2.466.6)`.
- [ ] **T8 (2.466.7)** system_capabilities.md + memory. Commit `The record redraws the floorplan (v2.466.7)`.

## Self-review
- Every user point mapped: open floorplan ✓T1, living size ✓T1, front door ✓T1 (decor), mudroom between + doorway ✓T2, pantry closet + door ✓T3, roof direction + garage gable ✓T2/T4, cars ✓T5, fidelity ceiling ✓T6 + honest answer recorded.
- Zone keys stay frozen; overlay/fallback untouched by moves (same H3 discipline). Kitchen cam: living zone now VISIBLE from it by design (open concept) — acceptance judged by screenshot, not assumed.

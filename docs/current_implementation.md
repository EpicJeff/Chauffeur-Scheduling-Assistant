# Chauffeur implementation status and forward plan

**Baseline:** v2.499.4, 2026-09-14

**Canonical shipped specification:** [`../chauffeur/system_capabilities.md`](../chauffeur/system_capabilities.md)

This file describes current architecture, completed product areas, active work, and next priorities. Dated design documents record decisions made for individual arcs; they are not current status trackers.

## Product objective

Reduce the coordination work required to run a family. Chauffeur should understand the household schedule, solve transportation conflicts, surface the next useful action, and make the family's operational state visible on shared wall panels and personal devices.

The 3D house is the shared spatial interface. Rooms and real-world objects provide stable context for features. The house should also reflect the family's own life through carefully quality-gated, personalized objects and spaces.

## Latest architecture change (2026-09-21, v2.499.126)

House photo matching now compiles an architectural analysis schema deterministically.
The LLM describes visible geometry and revises that description during visual review;
code generates all renderer configuration. See the
[contract and remaining limits](superpowers/specs/2026-09-21-photo-architecture-compiler.md).
Fresh-photo recognition across independent house styles remains the next quality gate.

## Shipped foundation

### Platform

- FastAPI/Jinja server with local, precompiled frontend assets.
- SQLite default storage with migration support for legacy TinyDB data.
- Home Assistant add-on, ingress, wall-panel mode, PWA, device identity, member accounts, and parent-PIN gates.
- Shared theme tokens, panel card builders, responsive overlays, and custom scrollbars.

### Family schedule and logistics

- Google Calendar ingestion and a CP-SAT solver for drivers, cars, constraints, preferences, overlaps, route time, continuity, and optional load balancing.
- Manual overrides with conflict explanations, coverage offers, trips, errands, departure timing, packing, and vehicle telemetry.
- Family Day, next-activity hero, screensaver, personal day and ride views, notifications, and Home Assistant state.

### Family operations

- Family messages, map, chores, routines, rewards, household tasks, meals, groceries, shopping, occasions, moments, music, trips, and configurable boards.
- Intake proposals from ICS, email, and images with parent review.
- Mind findings, household negotiation, missions, programs, interactive lesson sessions, and protected commitments.

### House and Study

- Authored low-poly exterior, porch, landscaping, garage, mudroom, pantry, kitchen, dining area, living room, back room, and integrated east-room Study.
- Touch-first persistent markers with feature icons and labels. Tapping empty scenery returns toward the exterior.
- Per-zone cameras and independent cutaway groups. Walls, roofs, openings, and attached objects hide only with the room view that owns them.
- Exterior clock and compact hero overlay restore ten-foot glanceability.
- Interior feature objects ground routines, chores, programs, packing, findings, and household administration in the environment.
- Study content uses the authored Study factory inside the house renderer. It does not launch a separate floating scene or duplicate garage information.
- Unified door language, a real mudroom-to-garage connection, matching interior/exterior patio slider, open pantry doorway, warm exterior night windows, and unlit interior glass.

## Current interaction rules

1. A marker must identify the object or room it opens.
2. Feature placement must match the house plan. A door cannot imply a room that is elsewhere.
3. Shared features use one real-world object when possible. Avoid duplicate information in multiple rooms.
4. A lean-in must preserve a clear exit: back control plus empty-space tap.
5. Architectural parts register with explicit room cutaway groups. Attached doors and trim follow their owning wall.
6. Panel cards reuse current theme tokens and shared builders. Per-child lanes have a readable minimum width; the overlay grows or scrolls instead of crushing lanes.
7. Exterior windows may glow at night. Interior-facing glass does not emit light.
8. Scrollable panel surfaces use themed scrollbar rules from `panel_skin.html`.

## Active development

### Personalized house authoring

Goal: a program can add a meaningful object or space that mirrors the family's activity—for example, a guitar for guitar lessons, a piano, exercise equipment, or a meditation garden. Tapping the object starts or opens the related program.

Current work is an experiment, not shipped behavior. The pipeline must:

- map a program to a bounded prop or space recipe;
- reuse authored materials, geometry helpers, scale rules, lighting, and interaction registration;
- use Gemini for structured planning and critique rather than unrestricted code execution;
- cache approved results so generation is not repeated at page load;
- enforce request budgets and deterministic fallbacks;
- compare generated guitar or piano output against already-authored reference content;
- reject output that misses silhouette, scale, collision, performance, or style thresholds.

The free-tier constraint makes runtime agent loops unsuitable for every load. Preferred shape is asynchronous authoring on creation or change, followed by validation and reuse of a stored recipe.

## Next priorities

1. Complete the personalized-object experiment and record quality, latency, request count, and fallback results against authored guitar and piano references.
2. Define promotion gates for generated objects: schema validity, geometry budget, visual review, safe placement, touch target, low-quality tier, and rollback.
3. Extend quiet and attention states through physical objects without turning the house into a notification dashboard.
4. Continue device verification for house cutaways, markers, overlays, and performance after repeated lean-ins.
5. Keep living docs synchronized in each release; archive dated plans instead of treating them as current status.

## Release gates

- Focused unit or integration tests pass for changed behavior.
- Tailwind content hash passes after template class changes.
- House changes receive screenshots at high-quality desktop wall size and a touch viewport.
- Repeated room entry and exit does not accumulate render loops, listeners, textures, or animation work.
- Home Assistant ingress paths and panel authentication remain valid.
- `system_capabilities.md`, this file, and affected design references describe shipped behavior accurately.

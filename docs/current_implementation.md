# Chauffeur implementation status and forward plan

**Baseline:** v2.499.4, 2026-09-14

**Canonical shipped specification:** [`../chauffeur/system_capabilities.md`](../chauffeur/system_capabilities.md)

This file describes current architecture, completed product areas, active work, and next priorities. Dated design documents record decisions made for individual arcs; they are not current status trackers.

## Product objective

Reduce the coordination work required to run a family. Chauffeur should understand the household schedule, solve transportation conflicts, surface the next useful action, and make the family's operational state visible on shared wall panels and personal devices.

The 3D house is the shared spatial interface. Rooms and real-world objects provide stable context for features. The house should also reflect the family's own life through carefully quality-gated, personalized objects and spaces.

## Latest architecture change (2026-09-22, v2.499.147)

Mapped neighborhood placement now spaces generated frontages to fit the actual
yard envelope and uses rotated yard overlap tests instead of circular clearance
rules. The previous 58-unit rejection radius discarded roughly alternate
candidates sampled at 52 units or less; a 60-unit home exclusion also removed
valid immediate neighbors. Both redundant radius rules are removed. Road-crossing
checks, the scenery boundary and rendering budgets remain. The cache identity
changes so installations regenerate sparse cached layouts on their next visit.

The neighborhood can follow real streets around the configured home using the
existing Mapbox key. A deterministic compiler aligns and clips road geometry,
uses building centers to guide frontage, and packs varied parametric houses
without overlapping yards or crossing streets. Up to eight nearest houses retain
the detailed renderer. The first lookup is asynchronous, subsequent visits use a
twelve-hour local cache, and missing data/provider failures retain the generated
neighborhood. Lookups are capped at four tiles and use existing usage accounting.
Street geometry is mapped; house appearances and lot spacing remain illustrative.
See [mapped neighborhood scope](superpowers/specs/2026-09-22-mapped-neighborhood.md).

## Detailed neighborhood rendering (v2.499.145)

The eight immediate neighbors now have distinct parametric specifications, built through
the active home's detailed geometry code via an explicit exterior entry point. Roofs,
stories, porches and depths vary as well as materials. Nearby houses no longer copy the
user's design. One renderer is shared, temporary construction resources are released,
and room cutaways/Study/household runtime are excluded from the exterior path. Forty
outer houses and the painted horizon retain their existing lightweight rendering.
Browser verification requires eight different built geometry fingerprints. First high-tier
measurement: about 1.22 million triangles and 547 added draw calls; hardware frame times
remain unverified. See the [neighborhood scope](superpowers/specs/2026-09-21-house-neighborhood.md).

House photo matching uses three bounded stages: compact structure analysis, a rendered
structure review, then details constrained to that architecture. Code compiles all
renderer configuration and verifies that details preserve the structural geometry.
Primary-front coordinates remain authoritative with up to two supplemental angles.
The new contract has no per-feature bounding-box inventory. House calls use Flash only;
failed details resume from cached reviewed structure. Existing saved designs and old
analysis replays remain supported. See the [staged contract and evaluation limits](superpowers/specs/2026-09-21-structure-first-photo-pipeline.md).
Gable edge estimates can be fitted to their declared owner when centred on it with majority overlap; this changes no underlying wall/roof geometry.
Attic window ownership can resolve to a unique existing gable; an ambiguous attic window no longer withholds all other details.
Opening assemblies now separate span from count: windows 1?4 with outside-only shutters, entry doors single/double with shared trim and an exterior light. The editor, renderer, photo prompts and schemas share this contract.
Fresh-photo recognition across independent house styles remains an unproven quality gate.

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

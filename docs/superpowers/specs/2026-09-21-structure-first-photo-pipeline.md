# Structure-first house photo matching

Shipped in 2.499.136. Supersedes the monolithic schema-v2 prompt for new uploads.

The objective is general architectural resemblance: full wall stories, relative widths,
underlying roof directions, cross-gables, projections and porch coverage. Openings and
materials are secondary. The user's authored house is one compiler fixture, not the
target architecture or proof of recognition quality.

## Contracts

1. Structure schema v3 describes front volumes, their stories and roofs, porches,
   gables, dormers, garage side/entry, viewpoint and concise evidence/limitations.
   It excludes openings, materials and bounding-box annotations. All positions share
   the primary image's facade axis. Supplemental images clarify physical architecture;
   their pixel positions must not become front-facade positions.
2. The deterministic compiler produces a structure preview. The existing renderer
   captures that exact draft. The review sees references followed by the render,
   checks five architectural categories and returns only revised structure. Uncertain
   review retains original architecture and reports uncertainty without deleting features.
3. The reviewed structure is cached. A detail-only schema accepts openings, finish
   bands, palette and limitations using existing owner IDs. Code fixes the chosen
   mirror mapping and garage orientation, compiles details, and compares structural
   geometry. A change to block depth, roof form/ridge/pitch, upper spans, roof features
   or porch coverage rejects that detail result and retains architecture. Attic glazing
   and finishes can change. Failed details can be retried without redoing structure.

All renderer configuration is deterministic. Existing compiler approximation notes
remain visible. No photo-specific roof heuristic or house-style template was added.
Legacy analysis schemas remain replayable; saved facade version remains 3.

## Requests and diagnostics

New matching calls use the Flash-only house_photo tier. Flash model rotation remains
possible and every transmitted model ID is recorded; this is not a pinned-model
recognition experiment. An ordinary successful match costs three model requests.
Upload allows three wire attempts; completion allows two, one per stage. Upload pool
deadline is 120 seconds; completion shares 180 seconds, each request at most 90.
Global budget admission, cooldowns, single-flight and 15-minute draft caches remain.
Review failure keeps the structure preview; detail failure keeps reviewed structure.
The UI reports these incomplete stages and permits an explicit retry.

Exported photo_trace records raw responses, compiler mappings, stage request counts,
the locked structure/geometry, review checks and detail-preservation success/errors.
No provider request is made by the compiler or a failed validation repair loop.

## Evidence and remaining gate

Tests exercise stage ordering, caching, failure/resume, geometry invariance, incompatible
detail fields/owners, and uncertainty. A synthetic matrix covers one/two stories,
gable/hip roofs, both ridge directions and left/right/unknown garage placement.
Saved photo8/10/11 analyses replay without requiring their old image annotations.
Browser tests cover automatic capture/adoption and render a staged mixed-story facade,
a single-story hip roof and a two-story gable roof.

These are deterministic and mocked-provider checks. They do not measure recognition.
Before claiming improved general accuracy, run fresh, independently labeled photos
across house types with a fixed eligible model and consistent image ordering. Score
stories, roof directions, massing proportions and porch footprint before detail quality;
separate raw-analysis errors from compiler approximation. No live provider evaluation
was performed for this release.

Renderer limits persist: two fixed blocks and slot quantization cannot reproduce every
L-shaped footprint, intersecting roof, split level or setback. Unknown structures and
unsupported intersections remain explicit limitations rather than invented extra stories.

## Ground mass preservation and live evaluation (2026-09-22)

Structure-first compilation now uses compiler version 5. Optional `masses` entries
(`slot`, `span`, `depth`, `roof`) preserve distinct observed regions within each base
block. Main-house regions can retain separate front planes and roofs; upper-story
spans still determine story count and override the underlying mass roof. Projection
offsets are bounded qualitative approximations, not photogrammetric measurements.
Garage-side masses share the fixed bay depth. The two base envelopes, rear extents
and 18-slot quantization remain limitations.

Normalization preserves mass boundaries, clips openings at those boundaries, and
splits porch coverage when it crosses them. The detail geometry lock includes masses.
The editor exposes section roof and main-house projection controls. Old facades
without masses do not gain them, and legacy `compile_analysis` defaults to version 4.
No saved facade is rewritten by this change.

The renderer reuses its existing volume roof clipping for ground masses and retains
the exposed sloped end of hip roofs at shared block seams. Forward upper-story
sections retain their exposed side returns.

The bounded comparison and prompt-trial findings are recorded in
[the evaluation report](../reports/2026-09-22-house-photo-general-evaluation.md).
Production prompts and Flash-only routing remain unchanged: the trial did not
establish a reliable accuracy improvement or a sound default switch to Flash-Lite.

## Gable bounds correction (2.499.137)

An estimated gable extending past its declared wall/porch is intersected with that
owner when its centre lies inside the owner and at least half its width overlaps.
The compiler records the fit, preserves the input and changes no wall or underlying
roof. Missing owners and gables centred away from their owner remain errors. The
reported g1 failure had no raw coordinates available; synthetic regressions establish
this bounded correction, not an exact replay of that provider response.

## Attic detail ownership (2.499.138)

An attic window naming an existing wall/porch instead of a gable resolves to that
parent's unique gable containing its interval (existing .02 boundary tolerance).
No gable, roof or story is invented. With zero or multiple matches, only that attic
opening is left unplaced with an explicit note; other details still compile. Unknown
owner IDs remain errors. Raw responses remain in diagnostics and the geometry lock
still applies. Synthetic tests cover unique, missing and ambiguous matches; the
reported o10 response was not available in the local export.


## Opening assemblies (2.499.141)

Width/span describes occupied space, not unit count. Windows support 1..4 framed
units, with shutters only at the group edges. Entry doors support 1..2 mirrored
leaves within one assembly, shared outer trim and one outside light. Single units
are centred. Both compiler and editor preserve door spans and explicit counts.
Optional count is backward-compatible: absent means one. The detail response schema
uses kind-specific branches to limit entry count to two; strict compiler validation
also enforces this. Compact window groups fit to the available span. Roof/story
geometry remains locked throughout the detail pass.

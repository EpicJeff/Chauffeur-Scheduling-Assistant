# Photo architecture analysis and deterministic compilation

Implemented in v2.499.126, 2026-09-21. Supersedes the model-generated configuration and structural-correction stages in the earlier house photo specs.

## Contract

The model describes architecture, never renderer configuration. One full-facade, photo-left 0..1 coordinate system applies to every interval. Stable IDs explicitly link wall volumes, porch roofs, gables, dormers and openings. Full rectangular story walls are separate from attic triangles. Underlying roof ridge direction is separate from cross-gables. Window counts describe framed units, not panes. Finishes identify ground, upper or base bands. Unknown evidence remains explicit.

`services/house_photo_compiler.py` owns the provider schema, relationship validation and pure compiler. The same analysis always produces the same house, notes and mapping trace. Validation checks finite intervals, IDs, references, containment, non-overlapping wall volumes and upper/attic ownership. A porch may extend across adjacent wall volumes. No renderer blocks, mirror flags or slots are accepted from the model.

The compiler chooses mirrored mapping from a visible garage side or deterministic entry/porch/wall fit; quantizes global intervals once; splits at fixed block boundaries; emits upper spans, owned roof features, explicit window groups and per-story finishes; then normalizes through the existing house validator. No model requests occur during compilation. Dormers support gable and shed caps. Conflicting cross-gable/perpendicular-ridge observations are reported instead of creating stacked geometry.

## Upload and review

A fresh upload uses one analysis stage, with up to three actual HTTP requests through the vision pool. Valid analysis and resulting drafts are cached for the existing fifteen-minute review window. Duplicate in-flight uploads are rejected; successful cached uploads make no requests. Invalid analysis is not cached as successful.

The existing automatic high-quality render comparison remains one additional request. It revises architectural analysis, then invokes the same compiler. It cannot return house configuration or perform slot arithmetic. Manual comparison allows up to three requests. Review failure retains the draft and remains retryable. No automatic save or activation is introduced. Legacy direct draft-review helpers remain for compatibility; new photo uploads use the deterministic pipeline.

Photo traces retain initial and reviewed analysis, compiler mappings, pre-normalization geometry, adjustments and per-action request counts. Actual transmitted requests, including failed HTTP requests, count. Local admission deferrals do not count or consume a foreground fallback candidate allowance. Global provider pauses still apply.

## Current limits

This is an analysis/compiler contract, not a general building modeller. The renderer still has eighteen fixed slots and two ground blocks. Separate one-story roof forms inside a block, arbitrary depths, more than two stories, bay-window geometry, double entry leaves and some roof forms cannot be represented faithfully. Unsupported or uncertain features are reported. Roof pitch classes map to 22.5/30/35 degrees; unknown defaults to 30. Forward projection maps to 1.5 scene units. Base bands default to 0.8 and wrap a block. Closest-free-slot opening placement can reposition groups; unavailable space is reported. These approximations are not measurements inferred from the photo.

## Evidence and next quality gate

A hand-labeled reference fixture verifies the broad central upper story, three upstairs windows, mixed continuous porch and right-hand cross-gable on a parallel ridge. Unit coverage includes reflection, owner validation, dense openings, dormers, cached/concurrent actions, review recompilation, saved traces and real transport accounting with mocked HTTP. High-quality browser renders cover mirrored, unmirrored and no-upper variants. Existing capture/adoption/fallback tests cover the UI flow.

No live Gemini request was made during this implementation. The hand-labeled render proves compilation, not recognition accuracy. Next evaluation is fresh-photo analysis compared against that fixture; broaden to independent house styles before claiming majority-house recognition. Recognition errors should be fixed in observation semantics/evidence; deterministic mapping bugs should be fixed and replayed locally without additional provider calls.


## Compiler v2 boundary fit (v2.499.127)

Uniform scaling could split one observed perpendicular roof across both fixed renderer
blocks, producing two independently capped roofs. The compiler now chooses the nearest
adjacent-volume boundary to the one-third facade seam, within canonical fractions
0.2..0.5 and with at most 0.025 separation between volumes. It maps that boundary to
slot 6 with continuous linear scaling on each side, shared by every feature layer.
Absent a candidate, the original uniform map remains. Mirror scoring uses unfitted
intervals. The trace records the selected seam and a proportion-adjustment note.
Placement order uses canonical coordinates, making collision handling reflection-stable.

The real photo8 fixture verifies this mapping independently of recognition. The right
wing actually has intersecting parallel and perpendicular ridges and an L-shaped
footprint. The hand-authored parallel roof plus cross-gable is a deliberate simplification,
not ground truth for the literal ridge structure. The current single-roof volume schema
cannot encode that intersection; evidence and limitations should retain it. The missing
porch gable is a separate observation omission. Code does not replace those observations
with reference-specific assumptions. A failed provider visual review left the original analysis untouched.


## Porch opening ownership (v2.499.128)

A ground-floor door or window may reference a porch; the compiler resolves its wall
through the porch owner. Both porch and wall containment are validated. Upper openings
still require a two-story volume, attic openings a gable. Unknown references remain
errors, with the reference included in diagnostics. Mapping traces keep original owner
and resolved wall_owner. This is deterministic relationship resolution, not a guess
based on ID spelling or proximity, and requires no additional model request.


## Compiler v3 bounded reconciliation (v2.499.129)

Before strict relationship validation, gable-owned windows labeled upper become attic.
No wall ownership or story count is inferred. Adjacent overlapping edges may share a
midpoint only when overlap is at most 0.02 facade width and 10% of the smaller volume;
nested volumes and larger overlaps are not flattened. Shape, enum and unique-ID checks
precede recovery. Full relationship validation follows. Raw input remains unchanged;
prepared_analysis and analysis_adjustments are retained in the compilation trace.
This handles redundant-label conflicts and rounding noise without claiming support for
intersecting footprints. Larger overlap diagnostics identify volume IDs and magnitude.


## Multiple views (v2.499.130)

One primary front photo plus zero to two supplemental images enter the same analysis
call. Supplemental labels: front-left, front-right, left, right, rear, unknown, relative
to someone facing the primary facade. Every interval still references image 1; other
views only disambiguate architecture. Evidence/limitations cite numbered images and
report contradictions. Review receives the same ordered references followed by the render.
The renderer and schema have not acquired general multi-view reconstruction capabilities.

The multipart API retains required `photo` and adds repeated `supplemental` and `views`
fields with matching counts, maximum two. All files must be images, each up to 8MB.
Bytes, MIME and view labels participate in cache identity. Drafts retain references for
the existing review lifetime; exported traces retain only view labels alongside analysis.
Single-photo uploads remain compatible. Request limits stay 3 upload attempts plus one
automatic review, with 3 for manual review. More images may increase input tokens.
Browser and ASGI multipart tests exercise the new flow without live Gemini calls.


## Wall faces and evidence contract (v2.499.131)

Analysis schema v2 adds `face` to every feature layer and `coordinate_frame=house_front`.
Roof ridge directions remain parallel/perpendicular but explicitly reference the house
front, independent of camera direction. Side-facing end gables do not imply a
front-to-back ridge. Front wall volumes describe rectangular walls below the eaves;
side attic triangles must not extend the front second story.

`observations` contains feature ID, image number, physical face, normalized image box
(x,y,width,height), and evidence. Boxes stay in their own image coordinate system.
Every identified feature needs evidence; front features require image 1. Compiler checks
face agreement, box bounds, valid owner types, available source images and containment of
front opening boxes within their wall/gable owner. Front at/width remains the facade
coordinate system; non-front at/width is face-local and is never projected into it.

Compiler v4 reduces v2 to its front projection before the existing bounded preparation
and slot mapping. It preserves original analysis and records excluded faces separately.
Side garage observations set side entry without emitting a front garage opening or
occupying front window slots. Door leaves are bounded by renderer capacity; layout and
dimensions use renderer defaults, with explicit notes. Non-front details unsupported by
the renderer remain observations/limitations. Existing v1 analyses retain legacy behavior.

Review schema requires five structural checks: wall faces, story boundaries, roof
directions, opening ownership and porch placement. Each is matched/corrected/uncertain.
Uncertain or missing checks and remaining compiler conflicts prevent auto-adoption;
the original draft remains available and review is retryable. This is a deterministic
acceptance gate, not independent proof that model judgments are correct.

Photo10 raw trace is the regression fixture. Annotating O11 as right-face/image3 proves
the compiler no longer creates a front garage door or drops the displaced window.
Synthetic side-wall/gable observations prove they do not enlarge the front elevation.
No fresh model run was used to establish recognition quality.


## Partial evidence handling (v2.499.132)

Supplemental-only front openings are retained in source analysis but excluded from slot
placement, with `face_projection.unplaced_openings` and explanatory notes. This avoids
rejecting the whole draft without guessing a front position. A visual revision containing
unplaced openings is withheld as structurally unresolved. Structural front volumes and
roof features still require primary-photo evidence; unknown IDs are not guessed.

The reserved observation feature `finishes` references collective material evidence,
since finish bands have no IDs. It must reference a face represented by a finish band;
box validation and available-image checks still apply. Other observation references must
match explicit feature IDs. No additional inference stage or provider request is added.


## Optional evidence versus structural requirements (v2.499.133)

Evidence on unused non-front geometry and collective finishes is supplemental metadata,
not a mandatory gate for compiling the front facade. Missing non-front evidence is noted
and listed under unevidenced_features. Side-entry configuration uses only independently
evidenced garage doors. Finish evidence lacking a matching face is retained as an
annotation and never applied to another wall. Missing front-opening evidence yields an
unplaced opening; missing primary evidence for front structural massing remains an error.
Raw observations remain available in successful draft traces. No geometry is synthesized
to satisfy missing evidence. This supersedes the stricter collective-finish face gate above.
Provider timeout fallback remains bounded by the existing stage deadline and request cap.

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

# Front-plane label review — 2026-09-22

Second visual inspection of the exact hashed reference images, before the new paired
trial. This is assistant adjudication, not independent human ground truth. Historical
evaluation JSON retains the labels actually used by those runs.

| Reference | Directly visible evidence | Judgment and uncertainty |
| --- | --- | --- |
| Sheldrew | Near-frontal window/door wall; two projecting triangular ends flank a recessed entrance. The roof connecting them runs across the facade. | Keep one story across three wall masses, perpendicular/parallel/perpendicular ridges. Central end geometry is obscured by the intersecting wings, so gable-versus-hip at the centre is less certain than ridge direction. Small door canopy; the courtyard is open. |
| Hood | Main arched entry and two rows of windows occupy the long wall on the right. Both visible masonry triangles/chimneys lie on the left-facing end walls. | Keep the long entrance wall as the front, with one-story wing / two-story centre / small one-story wing. Parallel ridges on the visible left and central sections. Exclude the partly obscured far-right roof from automatic scoring. Widths are approximate under strong perspective. |
| Reid | Two rows of front windows and a small columned entry. The right wall has a stepped parapet; the roof deck extends parallel to the entrance wall. | Keep two stories and parallel ridge; the parapet itself is not a roof plane or another story. Gable form is an inference about the hidden far slope. Porch-width threshold is approximate because bushes obscure the floor. |
| Bungalow | A low wall story, deep roof eaves, triangular end, and a sheltered entry are visible. Dense foliage hides wall corners and parts of the porch. | Story count and existence of porch are usable. Exact front-plane extent and roof partition cannot be adjudicated confidently from this single image. Exclude roof and mass-count labels rather than counting guesses as ground truth. |

Source locations and image hashes are in
[`manifest.json`](../../../chauffeur/tests/fixtures/house_photo_eval/manifest.json).
The LOC catalog pages returned HTTP 403 during this review; no catalog text or unseen
plans were used to bolster the image judgments.

The focused prompt adds only a front-plane instruction: use entry, wall corners,
and window rows to distinguish front and side, and assign roof directions relative
to that physical plane. It contains no house names, expected region counts, labels,
or coordinates. It does not include the prior trial's porch/ownership instructions.

For the paired trial, use Sheldrew as the near-frontal control and Hood as the oblique
challenge. Keep all photos and schemas identical across prompt variants. Reverse
variant order on the second repetition. Count transport failures, compilation
failures, and raw architectural errors separately. A successful single response is
not grounds to promote a prompt or change the production model route.

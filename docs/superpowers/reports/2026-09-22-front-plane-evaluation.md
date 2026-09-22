# Focused front-plane experiment — 2026-09-22

Decision: **inconclusive; do not promote the candidate or change model routing.**
One Flash-Lite baseline/candidate pair completed on the near-frontal control. No
pair completed on the oblique challenge, and no second repetitions completed.
Transport failures and quota exhaustion prevented the intended comparison.
The run stopped at the six-minute deadline after nine wire requests: four valid
structure responses, four HTTP 503s, and one daily-quota HTTP 429.

## Review and experiment

The [label review](2026-09-22-front-plane-label-review.md) distinguishes observable
ridge directions from uncertain roof forms and excludes obscured geometry. Bungalow
roof partition and mass count are unscored; Hood's far-wing roof is unscored.
Sheldrew's central form and Reid's parapet-hidden form are also marked uncertain,
while their parallel ridge directions remain scorable. These are assistant visual
judgments, not independent human labels.

The [candidate](2026-09-22-front-plane-candidate.txt) appends only instructions to
identify the entrance-facing wall and distinguish side-facing gables. Production
prompt, response schema, photos, compiler, and provider temperature were held fixed.
No labels, photo names, expected volume counts, or coordinates entered the prompt.

Two photos (Sheldrew control, Hood oblique), two pinned models, two prompt variants,
and two planned repetitions; variant order reverses in repetition two. No fallback.
Structure-only, max 16 wire requests and 360 seconds, one transient retry per job,
real daily budget and cooldowns retained. Flash had four local requests remaining
at the start; repeat coverage was therefore conditional on budget, not promised.
Manifest order controls case order. No detail requests were made.

## Observations

- Lite's completed Sheldrew pair has the same three wall masses, one-story heights,
  and perpendicular/parallel/perpendicular ridges. Both keep the porch small. The
  candidate changes the uncertain central form from hip to gable; that is not a
  demonstrated accuracy gain. It also regresses gable positions to centre-like
  `at` values, which the existing compiler bounds correction trims.
- Flash's Sheldrew baseline retains the three main masses and ridge directions,
  but invents a broad covered courtyard. Its candidate gets 503, then daily-quota
  429 on retry, leaving no comparable architecture.
- Flash's Hood baseline again treats visible side gables as front-facing and
  allocates a side/rear section to the front. It misses the small right wing.
  The candidate was not transmitted after quota exhaustion.
- Lite's first Hood request gets 503. Its candidate and second repetitions do not
  run before the deadline. The oblique-view hypothesis remains untested.

## Artifacts and checks

[Raw run and rescoring](2026-09-22-front-plane-evaluation.json) retain the actual
prompt texts, responses, failures, job states, caps, and model IDs. Raw score version
3 combined form and ridge under the historical `roof_directions` field. Offline
score version 4 separates ridge direction and form and applies all uncertainty
flags from the reviewed manifest. Both snapshots are preserved; no post-hoc score
is presented as the original trial score.

The evaluation tool now supports paired prompt variants and repetitions. Three
focused regression tests pass: wrong half-roof cannot hide at a midpoint boundary,
ambiguous labels are null rather than passes, and uncertain form cannot hide a
known wrong ridge. Python compilation and diff-whitespace checks pass.

No production prompts, routing, compiler, or renderer changed in this follow-up.
Saved facades remain byte-identical, SHA-256
`60290ff232465b2f30dd05b576ce243f7503c6f37438fff5dbb4e4509ca1ec6f`.

The next useful live test is the missing paired Hood comparison after availability
and quota recover, followed by repeated pairs on additional labeled house types.
Do not replace the default model or spend on decorative details on the strength of
this single near-frontal pair.

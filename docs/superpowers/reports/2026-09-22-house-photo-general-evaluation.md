# General house photo evaluation — 2026-09-22

The compiler and renderer now preserve distinct ground masses within the existing
base blocks, including separate roofs and main-house front projections. Production
prompts and Flash-only routing remain unchanged. Flash-Lite completed one full
structure/review/detail pipeline, but this small evaluation does not justify making
it the structural default. The candidate prompt was not promoted.

## Protocol

Read the saved facades and structure-first specification first. An earlier bounded
pilot is documented in `2026-09-22-house-photo-live-baseline.md`; it established a
compiler loss from a non-household brick reference before these changes.

The new comparison pins `gemini-3.1-flash-lite` and `gemini-2.5-flash`, with no
fallback. Four references cover one-story wings, a two-story block, mixed stories,
hip/gable roofs, and oblique views. Labels were recorded by the assistant before
the calls, never sent to the models, and are not independent human ground truth.
The user's house is excluded. Source links and image SHA-256 hashes are in
`chauffeur/tests/fixtures/house_photo_eval/manifest.json`.

Baseline: at most 24 requests / 600 seconds, unchanged production prompts, actual
upload → exact rendered draft → structural review → locked details. One transient
retry per job, after the existing model cooldown. Isolated app storage preserves
the real provider-budget ledger. No facade saves or provider calls by the compiler.
The baseline renderer remained fixed throughout the run; the hip-end repair followed
the run. This is a comparison of models with the new mass compiler, not a paired
measurement of old versus new compiler quality.

Candidate: at most 8 requests / 300 seconds, structure only, same fixed models.
It clarifies interval left edges, front-versus-side planes, same-height separate
wings, porch versus window awning, and schema ownership. Sheldrew and Hood were
diagnostic cases; a bungalow was held out from the baseline. There was no repeated
sampling or further tuning. Exact candidate text and raw results are archived in
the [accompanying JSON](2026-09-22-house-photo-general-evaluation.json).
The candidate stopped at seven requests: three Flash responses, one Lite response,
and three Lite HTTP 503s. Lite's Hood failed both attempts; its bungalow remained
pending after one 503 when the deadline expired. Total new live requests: 26.

## Baseline findings

The baseline stopped at 19 requests: Flash returned 10 provider responses without
transport failure; Lite returned four responses and five HTTP 503s. A successful
provider response can still fail the architectural contract. These are observations
from this short window, not long-run availability estimates.

| Reference | Flash | Flash-Lite |
| --- | --- | --- |
| Brick | Completed all stages; preserved three roof regions. Missed relative setbacks and invented a porch under a window awning. | Completed after a review retry; merged the central and right masses, retaining the right roof as a decorative gable. Review did not fix that. |
| Sheldrew | Three main regions were plausible, but nested a porch under another porch: rejected by validation. Also invented a broad covered courtyard. | Both structure attempts returned 503. |
| Reid | Completed; two wall stories correct, but classified the roof as hip rather than labeled gable and overstated porch width. | Initial structure eventually succeeded with two stories and a parallel gable; review returned 503. Details were not called. |
| Hood | Completed; confused the side-facing gable with the front and omitted a partly obscured one-story wing. Review retained the errors. | No request before the deadline. |

All four completed pipelines retained their locked architecture during details.
That establishes stage/geometry behavior, not visual correctness of their details.
Reviews are not a reliable accuracy oracle: they approved erroneous structures.

The candidate fixed Sheldrew's ownership rejection and removed its broad covered
courtyard for both models. Lite retained its three underlying roof directions;
Flash changed the central roof form to hip. Flash's Hood response still mistook
the side gable and now contained overlapping volumes, so validation rejected it.
Flash's bungalow had one story and a porch, but split the underlying roof into two
regions. The oblique bungalow roof partition is a provisional label needing human
adjudication. These mixed results do not establish a prompt improvement.

The original automatic scores sampled only each labeled region's midpoint and
could miss a wrong roof occupying half a region. They also miss small false porches.
Raw trial scores are retained for audit; the archived `rescored_structure_events`
use three samples per region and separate raw recognition from compilation failure.
No aggregate accuracy percentage or statistical model ranking is claimed.

## Implemented and verified

- Optional mass spans preserve separate underlying roofs and front offsets; old
  facades without mass spans stay unchanged. Legacy analysis replay defaults to
  compiler version 4; structure-first uses version 5.
- Normalization, preview slots, detail locks, and editor controls retain those spans.
- Hip roofs keep exposed sloped ends at shared block seams. The missing end was
  reproduced by a failing browser assertion before the repair.
- Forward upper sections retain exposed side returns.
- 71 photo unit tests passed, along with facade regression scenarios and the actual
  editor-method test. Browser checks passed for three masses, mirror, mixed stories,
  two-story hip closure, stepped upper returns, room masking, and section editing.
- Earlier unchanged renderer cases (staged, one-story hip, two-story gable) passed.
  Final JavaScript syntax and diff-whitespace checks passed.

`data/facades.json` remains byte-identical:
`60290ff232465b2f30dd05b576ce243f7503c6f37438fff5dbb4e4509ca1ec6f`.

The renderer still has two fixed base envelopes, fixed rear extents, and 18-slot
quantization. Main-house projections use qualitative distances; independent
garage-side setbacks remain unsupported. These are visible approximation notes,
not claimed reconstructions. No household-specific rule or model routing change
was introduced.

## Decision

Keep Flash for structure/review and the current production prompt. Lite is callable
and can produce valid details, but there is insufficient quality evidence for a
default switch or a stage-specific routing change. Keep the rejected prompt as an
experiment artifact. Before promotion, independently adjudicate the difficult roof
labels and obtain repeated paired results across a larger set, particularly oblique
views and covered porches. The bounded evaluation is complete even where provider
availability left jobs unfinished.

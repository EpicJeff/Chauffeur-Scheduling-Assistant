# House photo baseline: partial live evaluation, 2026-09-22

No production prompts, compiler rules, renderer configuration or saved facades were
changed. The live pilot produced one initial structure and no completed structural
reviews. Availability prevented an accuracy gate; this is not evidence of improved
general recognition. Stop before prompt tuning.

## Protocol and request accounting

Read `data/facades.json` and the structure-first specification before evaluation.
Visually label references before provider output; keep labels out of model input.
Use the actual `from_photo` / `critique` stages, unchanged prompts, one primary
photo followed by the exact compiled render for review, temperature 0.1 and the
existing response schemas. No supplemental views in this pilot. Pin each run to
one Flash model, one wire attempt per stage, no model fallback. Preserve production
budget admission; serve the app from isolated temporary data. Do not save drafts
over household facades.

The ceiling was nine wire requests; stopped after six:

| Run | Requests | Result |
| --- | ---: | --- |
| Initial local setup | 1 | Local SQLite contained a stale test credential; provider rejected it. |
| Pinned gemini-3.5-flash | 2 | Both structure attempts returned 503 high demand; retry followed the 120-second cooldown. |
| Separate pinned gemini-2.5-flash | 3 | Brick structure succeeded; its rendered review returned 503; Sheldrew structure returned 503. |

The configured free key was read from the repository's legacy local settings after
the setup error. No keys are in these artifacts. The two models' results are not
combined into a recognition score. No detail request was transmitted; failed review
retained the initial draft as specified. No quotas or cooldowns were cleared.

## References and pre-inference labels

1. Existing `2026-09-17-photo-brick.jpg`: one story; left/right perpendicular
   front-gabled wings around a central hip roof with lateral ridge. Approximate
   front widths .40/.32/.28; centre recessed; small entry cover, no broad porch.
   This is an existing reference, not a fresh holdout, and not the user's house.
2. [Victor Sheldrew House, east elevation](https://www.loc.gov/item/id0053/),
   HABS ID-42, photo 059262pv: one story; roughly equal projecting gabled wings
   around recessed centre; perpendicular wing ridges and parallel connecting
   ridge; small entry canopy. The open courtyard is not a covered porch.
3. [Typical California bungalow](https://loc.getarchive.net/media/typical-california-bungalow):
   one full wall story, front-to-back gable, recessed porch at right; precise
   facade proportions and porch roof partly obscured by foliage and oblique view.
   Prepared but not transmitted after availability failures.

The small set lacks two-story/mixed-story cases and independent human adjudication.
Labels were assistant visual judgments made before seeing model output. Wikimedia
downloads failed, so those initially considered images were not used. A three-story
Providence image was inspected and rejected before inference because it exceeds
the current schema. No house-specific optimization was performed.

## One scored initial analysis: brick reference

The [raw response and compiled specification](2026-09-22-house-photo-live-baseline.json)
separate recognition from deterministic representation. Assessments below concern
only the initial analysis, not a successful reviewed match.

| Category | Raw analysis | Compiled outcome |
| --- | --- | --- |
| Full wall stories | Correct: all three regions one story, no invented upper story. | Preserved. |
| Underlying roofs | Matches labels: perpendicular gable / parallel hip / perpendicular gable. | Right wing's distinct gable/ridge lost because it shares the main block with the hip region. Compiler explicitly reports this limitation. |
| Relative widths | .38/.32/.30, within .02 of visual labels. | Quantized to 6/6/6 slots; distinct third mass is not represented. |
| Projections | Centre recessed; right forward; left flush still ahead of recessed centre. | Both fixed blocks have depth zero; centre/right relative depth not represented. |
| Porch footprint | Incorrect: window awning at right becomes a covered porch; entry is called open. | Spurious right porch is rendered, and open entry gets a default cover with a warning. |

The end-gable `at` values .19 and .85 equal the corresponding volume centres,
while widths span the whole volumes. This suggests centre/left-edge confusion.
The bounded owner-fit rule clips them and records adjustments. The structure prompt
does not explicitly define `at` as a left edge; the older analysis prompt does.
That is a general prompt candidate, not a proven fix. Do not add a coordinate
guessing heuristic based on this one response.

The captured render visibly confirms the missing right gabled mass and the invented
right porch. Its view is the existing capture camera, not a pixel-aligned photograph.
Review received this exact render but returned 503, so no review correction or
detail-preservation result can be scored.

## Offline proof

- 17 structure-stage tests, 27 compiler tests and 2 pipeline tests passed (46 total).
- Browser render checks passed for staged mixed-story, single-story hip and
  two-story gable cases. These are synthetic rendering checks, not recognition.
- Recompiling the new brick structure produced identical output and diagnostics.
- The saved `My house - photo 12` raw structure also replays deterministically,
  with geometry matching its saved initial draft. Its trace contains four upload
  attempts and `saved_matches: draft`, not a completed reviewed match.
- `data/facades.json` SHA-256 remained unchanged.

PowerShell stderr redirection reported NativeCommandError/exit 1 for the unittest
commands despite their `OK` summaries; all reported tests passed. The browser
script emitted its explicit PASS line.

## Resume point

Local artifacts are under `scratch/house-eval-2026-09-22/`: pre-inference labels,
bounded harness, separate failed runs, successful raw trace, `brick-structure.png`,
offline renders and test logs. The harness refuses to overwrite an existing run;
do not blindly rerun it. The saved JSON above is the durable, non-private evidence.

Next live gate: a new explicit bounded run with a fixed available Flash model,
fresh two-story and mixed-story references as well as these shape families, and
structure review completed before details. Keep 503 outcomes separate from image
errors. Rehydrate the captured initial structure for review rather than spending
another analysis request on it when feasible. First investigate the general
two-block representation limit: accurate roof observations cannot survive it for
three distinct adjacent masses. Coordinate semantics and porch/awning confusion
are separate recognition candidates. Do not tune to the authored house or claim
that prompt changes alone can repair the lost massing.

## Flash-Lite follow-up

The user asked whether Lite could improve availability. Google's
[gemini-3.1-flash-lite documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite)
confirms image inputs, structured outputs and thinking support. There is no
documented modality/schema obstacle to using it for these stages. The current
`house_photo: ['flash']` chain is a quality policy, not a technical incompatibility.

A separate pinned `gemini-3.1-flash-lite` trial used the unchanged brick photo,
prompt and structure schema. Its first request returned 503 after 4.11 seconds;
no analysis, review or details could be scored. Stopped rather than rotating
models. Total session requests are now seven, still below the original ceiling
of nine. This one Lite failure does not estimate its typical availability.
Local evidence: `scratch/house-eval-lite-2026-09-22/run.json`.

Lite remains an unproven candidate for structural recognition. The locked detail
stage is a lower-risk starting point because deterministic geometry comparison
rejects structural drift, although opening/material accuracy still needs scoring.
Do not enable a blanket Lite fallback based on availability alone; first complete
a labeled comparison covering full wall stories, roof directions and massing.
Production routing remains unchanged.

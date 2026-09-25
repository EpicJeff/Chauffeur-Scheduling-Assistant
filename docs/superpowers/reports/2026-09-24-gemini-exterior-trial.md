# Paid Gemini exterior trial

Version 2.499.176 · `feature/living-room-atmosphere`

Nano Banana and Nano Banana 2 were called through the paid Gemini API, using
the same prompt and three image inputs as the previous combined ImageGen
treatment. This tests an API path available to a future server feature. It
does not wire paid generation into the production app.

## Fixed experiment

The exact prompt is the **Combined model + photo treatment** in
[the saved prompt set](2026-09-24-personalized-exterior-prompts.md). Input order:

1. The three-quarter render of the hand-authored My house facade (camera/structure).
2. The farmhouse photograph (materials).
3. The living-room overview (atmosphere).

No prompt edits or image touch-ups were made between the two models. Requests
used `v1beta/models/{model}:generateContent`, text/image response modalities,
and `imageConfig.aspectRatio: 3:2`. Nano Banana 2 requested 1K; Nano Banana used
its default resolution. These native outputs differ slightly in dimensions
from the earlier 1536 × 1024 ImageGen image, so this is not a resolution-matched
benchmark. Source hashes, returned model versions, configurations, usage and
output hashes are in [the results](2026-09-24-gemini-exterior-results.json).

## Results

| Model | Time | Native output | Visual review |
| --- | --- | --- | --- |
| `gemini-2.5-flash-image` (Nano Banana) | 10.45 s | 1248 × 832 PNG | Preserves broad massing and garage entrances, but keeps low-poly trees, flat lawn and a floating parcel edge. Adds side windows and changes porch detailing. |
| `gemini-3.1-flash-image` (Nano Banana 2) | 9.97 s | 1264 × 848 JPEG | Much more photographic vegetation, setting, shadows and surfaces. Preserves broad massing and garage entrances, but invents side windows, changes a garage projection roof to metal and modifies some finishes/openings. |

Nano Banana 2 is the stronger candidate in this single example. Neither output
passes exact architectural fidelity. Two single samples cannot establish
reliability, failure rate, consistency across viewpoints or general house
accuracy. No production recognition prompt or deterministic compiler changed.

Published standard pricing and reported usage imply approximately **$0.11
total**, including inputs and non-image output. This is an estimate, not a
verified billing record. Nano Banana: 1,283 input tokens, 1,290 image-output
tokens, 13 other output tokens. Nano Banana 2: 1,283 input tokens, 1,120
image-output tokens, 504 other output tokens.

[Google pricing](https://ai.google.dev/gemini-api/docs/pricing) checked on
2026-09-24 lists Nano Banana at $0.039/image plus input, and Nano Banana 2 at
about $0.067/1K image plus input and text/thinking. It also lists the original
Nano Banana for shutdown on October 2, 2026; retain it as a comparison, not a
new production dependency.

## Request-format correction

The first two requests used the guide's v1 `responseFormat.image` example
with string aspect/size values. Both returned HTTP 400 enum-validation errors
before generation; they returned no images or usage metadata. The
[rejected-request record](2026-09-24-gemini-exterior-rejected-requests.json)
is retained. The corrected v1beta `imageConfig` form follows the
[GenerateContent API schema](https://ai.google.dev/api/generate-content#ImageConfig).
There were four POST attempts total: two invalid requests, followed by one
successful generation per model. No automatic retries or model fallbacks ran.

## Files and verification

The comparison page at `/static/house_hybrid/exterior-study/index.html#nano2`
now includes both API results. Assets are saved unchanged as:

- `chauffeur/static/house_hybrid/exterior-study/nano-banana.png`
- `chauffeur/static/house_hybrid/exterior-study/nano-banana-2.jpg`

`chauffeur/tools/evaluate_house_images.py` is an opt-in, two-request trial
runner. `--key-file` reads the explicitly supplied paid-key file in memory;
`--settings` alternatively reads only the paid-key setting from JSON or a
read-only SQLite connection. Without `--live`, it only queries model metadata.
It refuses existing output directories and does not use the free key. Keys,
request headers and inline image payloads are not saved in reports.

Example (paths are placeholders):

```powershell
python chauffeur/tools/evaluate_house_images.py --key-file <paid-key-file> --out scratch/new-gemini-trial
python chauffeur/tools/evaluate_house_images.py --key-file <paid-key-file> --out scratch/new-gemini-trial --live
```

Validation: images decoded and were visually reviewed; browser checks cover
all ten views, selection, fit control, phone layout and hash navigation with
no console errors. Offline checks cover paid-key isolation, one call per model
on 503 failures, result redaction and refusal to repeat an output directory.

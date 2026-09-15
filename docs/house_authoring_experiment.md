# Server-side object authoring experiment

This first slice generates an acoustic guitar with Gemini and compares it with
the existing authored guitar in the served house. It does not automatically
replace objects or run on every program creation. The quality experiment must
establish whether that rollout is justified.

## Run

From `chauffeur/`, with Playwright and Chromium available on the worker host:

```powershell
..\venv\Scripts\python.exe tools/author_house_object.py --out ../scratch/guitar-authoring --settings-file ../data/chauffeur_db.json --model gemini-3.5-flash
```

Alternatively set `GEMINI_API_KEY` and omit `--settings-file`. The settings reader
uses only `llm_gemini_api_key`, never `llm_gemini_paid_api_key`. The application
cannot establish the Google project's billing tier from the key; inspect that
project in AI Studio if its billing status is uncertain. No model fallback,
automatic API retry, search, image generation or paid tool is enabled.

The command creates a synthetic household in a temporary database and starts a
loopback server. It does not modify the live database or send real household
records/screenshots to Gemini. Only the credential is read from the supplied file.
This uses the existing house browser harness; deployed worker packaging still
needs Chromium and its platform dependencies. The wall panel needs neither.

The job directory contains the exact brief, generated recipes, Gemini critique,
request usage, timing, room/detail screenshots and `report.md`. To re-render saved
recipes without spending API quota, repeat the command with `--render-only`.

## Pipeline and acceptance

1. Render the authored baseline and the same room with the guitar removed.
2. Ask Gemini to design a guitar using the room context and a restricted geometry
   vocabulary. It does not receive the authored guitar's source.
3. Validate the JSON recipe, then build and render the candidate with the same
   palette, quality tier, position, room camera and fixed close-up camera.
4. A separate Gemini call critiques baseline/candidate screenshots and measurements.
   This is a model-assisted comparison, not an independent or blinded human study.
5. One correction call revises the recipe. Render and check the corrected result.
6. Leave the result at `review_required` or `rejected`. A model's self-review is
   not sufficient to publish an asset, and the final correction has not received
another model critique within the three-call budget.
If a failed request uses the correction slot, the worker stops after reviewing
the first usable candidate. It records that omission rather than exceeding the cap.
Generation uses low thinking, strict JSON, explicit output caps and a complete
response check. Thinking and visible output both consume the output allowance.

The geometry vocabulary includes beveled boxes, ellipsoids, cylinders, rods and
polygon extrusions with circular holes. Bounded translated repetition keeps strings,
frets and similar details compact (48 definitions, 140 expanded parts maximum).
It contains no executable expressions,
scripts, URLs, textures or arbitrary asset loading. Input limits constrain
coordinates, dimensions, polygon vertices and part counts before browser work.
Rendered gates check the actual bounding box, 140-mesh/25,000-triangle limits,
browser errors, and a real pointer click reaching the intended program ID.
This click test stops at program dispatch; it does not retest the lesson player.

The service persists a call reservation before invoking Gemini. Failed calls
count toward the three-call maximum. Completed stages reuse saved results.
Interrupted calls with unknown outcomes require inspection rather than a silent
retry. A lock prevents two workers spending the same job budget simultaneously;
after a process crash, verify that worker is gone before removing its stale lock.
Multiple unrelated jobs do not yet have a shared quota scheduler.

Measurements report provider token usage and request latency, object geometry,
scene draw calls and short CPU-side render samples. They do not prove wall-panel
frame rate, GPU time, a free Google invoice, or consistent quality across objects.
The current guitar is a comparison baseline, not an assumption of perfect art.

## Next decision

Use the evidence to decide whether the geometry vocabulary, model budget and
visual review produce a worthwhile result. Program-triggered scheduling, shared
quota priority, more object briefs, asset publication and rollback remain outside
this initial experiment. They should follow a successful quality gate rather
than automatically expose an unproven authoring loop to every family.

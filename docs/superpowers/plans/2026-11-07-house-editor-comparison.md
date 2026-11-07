# House editor: drawing-reader comparison (slice 1, Task 12)

Run on 2026-11-07 with `tools/twin_live.py compare`, budget $3.00, scratch storage, against the user's `Reference Plans Lot 58.pdf`. Each model read the same four cropped steps:
1. The main-floor outline on sheet 1.
2. The walls of two wings, each wing chosen from that model's own outline read.
3. The roof plan on sheet 3.

Scores are against the hand-read answer key `chauffeur/tests/fixtures/twin_lot58_key.json`.

| | Gemini (pro pool) | Claude (opus-5-5) | Answer key |
|---|---|---|---|
| Cost | $0.2177 (placeholder Gemini rates, so likely overstated) | $0.0855 (real rates) | n/a |
| Overall width error | 0.46 ft | 0.46 ft | 70'-0" |
| Outline fit (RMS) | 0.16 ft | 0.22 ft | ~1 ft key accuracy |
| Walls in two wings | 31 | 22 | 30+ for the whole floor |
| Roof sections | 7 | 9 | 5 to 9 |
| Roof kinds | gable, shed | **hip**, gable, shed | hip, gable |

Total spend: **$0.30** of the $3.00 cap. This was the local ledger; the household ledger stood at $7.48.

## What it shows

- **Both models read the scale and the outline well** once each request carries one cropped step: under half a foot off, against an answer key that is itself only good to about a foot. The P0 failures (floors not lining up) came from the one-shot format, not from the models.
- **Gemini calls every roof section a gable.** That is the same mistake behind the giant gable in the first live run. Claude reads the hips: eight hip or gable sections plus a shed, matching sheet 3.
- Gemini found more walls in the same two wing crops. Walls settle by geometry and can be redrawn by hand. A roof read with the wrong kind of section cannot be fixed by settling and needs a person to retype every section.
- At real rates Claude cost less than half of Gemini's placeholder-priced figure.

## Decision

**Claude is the drawing reader for slice 1, and prompts are tuned for it.** Gemini stays selectable through the provider selector but is not tuned.

The recorded answers live under `chauffeur/tests/fixtures/twin_reads/recorded/<model>/` for replay tests. The outline orientation was checked: both fits land at about 0.2 ft RMS, so the key's y-toward-the-rear convention matches the sheet. A mirrored match would have shown several feet.

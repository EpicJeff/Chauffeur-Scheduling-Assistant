# Exterior orbit and continuity experiment

Version 2.499.177, isolated branch `feature/living-room-atmosphere`.

## Working preview

`/house?compare=exterior&light=day` opens eight full-screen saved views. Arrows,
keyboard arrows, dots and horizontal swipes change views. The living-room marker
or persistent entry button approaches the existing hybrid living room in the same
document. Radio, critters, home ledger and program book retain their existing
close-up interfaces. Outside, Escape and browser history return through the levels.
The exterior angle survives a room visit. Direct room links and reload work.

No WebGL, image-generation API or paid credentials are used by the browser. Views
load on demand with adjacent prefetch; a failed view leaves the last good image
visible and supports retry. The preview remains opt-in and does not replace Home.
The exterior set is daylight only. The living room retains day/night controls.

## Sources and bounded generation

Source is the saved hand-authored **My house** (`694bcb6c86bb`) facade snapshot,
not a photo-derived variant. Eight seeded, daylight model captures freeze its
camera angles and are saved in `assets/house-orbit-2026-09-24/model-{0..7}.png`.
The original front farmhouse photo cannot validate the rear or side architecture.

Nano Banana 2 model ID: `gemini-3.1-flash-image`, v1beta generateContent,
TEXT+IMAGE modalities, 3:2 at 1K. Credentials read from the explicitly supplied
paid key file, never copied into the branch. Runtime preview uses saved images.

| Batch | Calls | Outcome |
|---|---:|---|
| Model + farmhouse + room style + prior photo treatment | 8 | Attractive images; views 2, 4, 7 copied the wrong camera. Materials and landscaping drifted. |
| Model-only corrections 2, 4, 7 | 3 | Correct camera sides; invented porch/openings and inconsistent finishes remained. Right side retained artificial ground. |
| Shared rear appearance anchor, views 4 and 6 | 2 | Landing/material/planting continuity improved; view 4 chose the wrong camera side. |
| Target model last + explicit screen-side layout, view 4 | 1 | Correct side, improved finishes and landing; still missing walkway and invented gable window. |

14 successful paid calls total this turn, zero automatic retries. This includes
the eight requested views and six targeted corrections/consistency trials, not a
second full batch. Exact prompts, input/output hashes, model versions, usage and
timings are saved beside the captures. Actual billed cost has not been verified;
the user's earlier $0.16 observation was for the previous two-model trial.

Final preview image selection: initial 0, 1, 3, 5; model-only 2, 7; shared-reference
6; camera-corrected shared-reference 4. Earlier rear candidates and a rejected
camera are retained under `static/house_hybrid/exterior-study/consistency/`.

## Visual acceptance: not passed

The user correctly identified vegetation, deck, small features, materials and
color differences. They suggested a single view **only if** consistency could
not be achieved; the eight-view approach remains active for this experiment.

The shared-reference rear trio is evidence of improvement, not proof of a
production-ready generation workflow. Covered porch/wood deck/white brick base
differences were removed from the revised rear pair. Paint, trim, shingles and
low beds are closer to the anchor. The rear-left walk still disappears, gable
windows are invented, camera elevation and individual plants drift. Other views
still have the earlier batch's finish and detail variations. Front-right itself
contains invented upper side openings compared with the deterministic model.

Do not call this an exact reconstruction or consistent orbit. The before/after
review is `/static/house_hybrid/exterior-study/consistency/index.html`.
Further generation should be another bounded continuity test reviewed across
adjacent views, not an unattended full-set regeneration. One-view fallback has
not been selected. Navigation works independently of this unresolved image gate.

## Validation

- `test_house_exterior_live.py`: all 8 angles, wrapping, rapid input, same-document
  entry, four existing destinations, Escape/back/forward, reload/deep link,
  phone touch, animated and reduced-motion entry, failed-image retry; no WebGL.
- `test_house_hybrid_live.py`: existing four day/night destinations, controls,
  focus, actual sun boundary, phone layout and renderer switch.
- `test_house_orbit_generation.py`: offline explicit-call budget, no implicit
  retry or existing-directory rerun, secret redaction and argument guards.
- Desktop/phone screenshots inspected. Entry controls raised above Ask Argyle.

Screenshots/results: ignored `scratch/exterior-review` and `scratch/hybrid-regression`.

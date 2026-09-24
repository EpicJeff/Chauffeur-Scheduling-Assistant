# Personalized hybrid exterior study

Version 2.499.175 · `feature/living-room-atmosphere`

The study compares photographic exterior treatments against the same warm,
material-rich living-room background used by the hybrid prototype. It is a
visual experiment using one supplied matched pair, not evidence of general
photo-matching accuracy.

## Sources and provenance

- Farmhouse photo: `docs/superpowers/specs/assets/2026-09-17-photo-farmhouse.jpg`.
- Saved facade: `E:/repositories/Chauffeur/data/facades.json`, entry
  `694bcb6c86bb`, name **My house**, source **hand**. The explicitly named main
  checkout file was read only. Neither photo-generated variant was used.
- Interior style: `chauffeur/static/house_hybrid/living-habitat-day.png`.
- Selected facade snapshot: `chauffeur/static/house_hybrid/exterior-study/my-house.json`.
  This contains only the selected facade identity and specification.

The specification was passed unchanged to `house_facade.issue_draft` in an
isolated temporary-data app. Browser `chfFacade()` equality was asserted against
the source specification before capture. Captures used Chromium at 1536 × 1024,
high quality, explicit daylight, the existing editor isolation mode, and the
existing seeded texture RNG. Orbit stop 1 supplies the near-front view; stop 0
supplies the three-quarter view. `chfCapture()` saved the canvas without UI.
Both final captures completed without browser errors. This does not promise
pixel-identical rendering across GPUs or browser versions.

## Treatments

All files are under `chauffeur/static/house_hybrid/exterior-study/`:

| File | Image inputs | Purpose |
| --- | --- | --- |
| `photo-led.png` | Farmhouse photo + interior style | Test direct photographic identity/style transfer |
| `model-led.png` | Near-front model render + interior style | Test rendering quality while retaining the authored design |
| `combined-three-quarter.png` | Three-quarter model render + farmhouse photo + interior style | Test model camera/structure with photo materials from an unseen viewpoint |
| `photo-only-three-quarter.png` | Farmhouse photo only | Test a verbally requested three-quarter camera and inferred hidden geometry |
| `model-source.png` | Unretouched model capture | Near-front architectural comparison |
| `model-three-quarter.png` | Unretouched model capture | Three-quarter camera comparison |
| `farmhouse-reference.jpg` | Byte-for-byte source copy | Original photo comparison |

Built-in ImageGen produced one image per treatment. The
[exact prompts](2026-09-24-personalized-exterior-prompts.md) record the input
order and reference priority. There is no generation at runtime.

## Review

The photo treatment retains the recognizable front silhouette and the right
gable's upper window. It changes smaller details, including the porch window
group and entry/post proportions. The model treatment retains the broad roof
arrangement and low right gable but adds or reinterprets some trim, landscaping,
entry details and window divisions. Neither is an exact architectural renderer.

The combined treatment preserves the three-quarter composition, broad roof
arrangement, blank right front gable and side garage projection while adopting
photo-derived finishes, including blue-gray shutters and white masonry. It
still changes porch geometry, opening divisions and landscaping; it is not a
pixel-registered re-render and should not inherit hotspots without review.

The saved model itself differs from the photo: the right front gable is lower
and lacks the upper window, the porch supports and openings differ, and siding
and brick placement differ. Those baseline differences must not be attributed
to image generation. For the combined treatment the prompt gives the model
priority for massing, roof geometry, camera and openings; the photo supplies
surface appearance. Hidden sides cannot be verified from a front photo alone.

## Photo-only alternate angle

The photo-only three-quarter treatment retains the photographed tall right
gable and upper window more closely, but chooses a shallower angle than the
model view. It invents a windowed right side with no garage entrance, despite
the driveway running beside it. The combined treatment retains the modeled
side-entry garage. This single comparison supports using the model to guide
hidden geometry; it does not establish multi-view consistency or general
accuracy. A prompt alone did not reproduce the precise requested camera.

## Validation

Browser checks cover all eight image views, selected-button state, full-frame
fit, living-room link, phone layout and hash navigation. Source captures were
visually inspected alongside all four generated outputs. No production feature
tests were needed because the only app change is an isolated static study page
and the version bump.

## Viewing the study

Open `/static/house_hybrid/exterior-study/index.html` on this fork's app. The
page starts with the combined treatment and offers the other treatments,
unretouched sources and interior reference. Images fill the viewport; **Fit
whole image** reveals the complete frame. **Open living room** links to the
existing interactive hybrid comparison. The study does not implement a camera
transition or replace the production exterior.

The main checkout, deterministic facade compiler, recognition prompts and
production House navigation are unchanged.

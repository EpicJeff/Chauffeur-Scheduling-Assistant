# Albums inside the photographed shelf

Version 2.499.169 · `feature/living-room-atmosphere`

The earlier record strip misinterpreted the intended placement. This revision
recomposes the radio photograph with an actual vinyl bay beside the radio:
upright sleeves, metal bookends, clear foreground space and a continuous oak
shelf. The interactive collection occupies that space. There is no separate
HTML ledge underneath the scene.

One live album faces forward. Neighboring albums rotate almost edge-on and pack
to either side. Clicking a neighboring jacket selects it; clicking the selected
cover plays it. Swipe, previous/next, Left/Right and Home/End browse without
issuing playback commands. The selected sleeve keeps its title and save control.
Sleeve edges, warm shading and contact shadows give the live artwork depth.
The background's larger clusters of sleeves are decorative; the front stack is
the real selected member's collection or current search results.

The image, radio controls and album bay share one coordinate plane. This keeps
the covers on the photographed wood through resizing and camera movement. Small
screens pan between Radio and Records, and move closer to the glass for search.
Successful phone searches return the camera to the albums. Reduced motion removes
the camera and jacket transitions. The existing personal shelves, artwork proxy,
search, playback attribution and remote speaker control remain shared.

## Artwork

Built-in ImageGen produced these new workspace assets:

- `chauffeur/static/house_hybrid/radio-bay-day.png`
- `chauffeur/static/house_hybrid/radio-bay-night.png`

The day scene used the preceding radio photograph as an identity reference. The
night scene edited that new day image with unchanged geometry. Both were inspected
and copied from the generated-image directory; original images remain available.
The [exact prompts](2026-09-24-house-record-bay-prompts.md) are recorded separately.
Existing earlier assets were not overwritten. No external generation API was used.

## Verification

Passed the record shelf/search browser test, radio-control browser test and full
hybrid regression. Added proof for exactly one selected album, spine selection
without playback, swipe without playback, keyboard selection, common image/control
coordinates and the absence of a synthetic ledge. The existing cases retain
personal isolation, artwork proxying, search/save/remove, stale results, error
handling, playback contracts, day/night, touch, focus and navigation coverage.

Desktop day/night and phone radio/search/album captures were visually inspected.
Captures remain in ignored `scratch/record-review/` and `scratch/bay-radio-review/`.
The local preview uses clearly named demo speakers and sample geometric covers;
real household audio has not been auditioned here. This is still the isolated
hybrid comparison, not a production default or a change to the 3D renderer.

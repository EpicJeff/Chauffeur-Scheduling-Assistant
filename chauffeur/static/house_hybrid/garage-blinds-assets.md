# Garage window blinds

Built-in ImageGen edits, 2026-09-26. Supersedes the previous attempt to depict utility storage through these windows.

Saved outputs in this directory:

- `exterior-model-full-block-empty.png`: closed neutral blinds by day.
- `exterior-model-full-block-empty-night.png`: closed blinds with diffuse warm glow at night.

Both are the base artwork used for every parking combination. Existing vehicle masks cover only the garage opening and driveway, leaving these windows supplied by the base.

## Day edit prompt

Use case: precise-object-edit. Input is EDIT TARGET, full house exterior artwork. Modify ONLY the TWO narrow ground-floor garage windows immediately LEFT of the open double garage bay, centered at approximately (48%,64%) and (55%,66%). Install fully lowered CLOSED horizontal Venetian blinds behind the existing glazing covering every pane from top to bottom. Slats must be tilted completely shut: absolutely NO interior view, furniture, pictures, decor, silhouettes or visible gaps into the room. Blinds must have clearly visible fine parallel horizontal slat lines, consistent across both windows. Keep existing mullions, trim and exterior shutters in front unchanged, and preserve foreground tree branches. Do not alter any other window. Keep entire remainder of image unchanged: camera, framing, building edges, roofs, lighting, garden, empty driveway and empty garage. Full-frame 1536x1024; no crop, labels or UI. Day: neutral off-white closed blinds, softly shaded behind glass, no artificial glow.

## Night edit prompt

Use case: precise-object-edit. Input is EDIT TARGET, full house exterior artwork. Modify ONLY the TWO narrow ground-floor garage windows immediately LEFT of the open double garage bay, centered at approximately (48%,64%) and (55%,66%). Install fully lowered CLOSED horizontal Venetian blinds behind the existing glazing covering every pane from top to bottom. Slats must be tilted completely shut: absolutely NO interior view, furniture, pictures, decor, silhouettes or visible gaps into the room. Blinds must have clearly visible fine parallel horizontal slat lines, consistent across both windows. Keep existing mullions, trim and exterior shutters in front unchanged, and preserve foreground tree branches. Do not alter any other window. Keep entire remainder of image unchanged: camera, framing, building edges, roofs, lighting, garden, empty driveway and empty garage. Full-frame 1536x1024; no crop, labels or UI. Night: closed blinds softly backlit with a gentle uniform warm amber glow, dimmer than other house windows. Diffuse light only: no objects or silhouettes visible through the blinds.


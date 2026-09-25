# Fireplace assets

The current fire is an original Blender Mantaflow simulation, not stock footage.
No assets were purchased. The user prefers free/generated assets; purchases are
a last resort. Kitchen, steam and weather remain outside this work.

## Animated layer

- Asset: `fireplace-simulated.webm`, VP9 with alpha, 400x480, silent, 24 fps.
- Source: `chauffeur/tools/render_fire_simulation.py`, Blender 4.5.14 LTS.
- Three camera-registered log meshes emit fuel from their exposed bark.
  Vertex weights leave inactive patches; animated Clouds textures move the
  ignition pattern, and each log has independently phased fuel pulses.
  Three inset collision cores keep the simulated fluid outside the wood.
- Mantaflow gas domain: resolution 96, fuel centered on 0.8 with two small
  oscillations, burn rate 0.36, flame vorticity 0.6, temperature limits 2/3.5,
  initial upward velocity 0.25, time scale 0.85. The longer burn and stronger
  buoyancy increase physical flame height; no display stretching is used.
- Flame-grid values drive both volume extinction and emission through a
  dark red/orange/yellow/white ramp. Coverage is rendered by Blender with
  transparent film, not inferred from footage by keying or segmentation.
- Three matching holdout meshes remain render-visible: they hide fire behind
  the logs while contributing no wood pixels or alpha. Only flames move.
  The still background supplies detailed oak logs and contact shadows.
- Frames 49-168 follow a two-second warmup. A 24-frame eased overlap produces
  a four-second loop. Coverage-weighted (premultiplied-alpha) color blending
  preserves thin flame edges. The wrap joins consecutive simulation frames;
  there is no reverse playback or image warping.
- In-room projection: (508,294), 200x240 in the 1536x1024 source image.
  The native render has the same aspect ratio as this layer. The room and logs
  retain their original geometry.
- Cycles/OptiX, 64 samples, Standard view transform. Base fluid data is used;
  an experimental noise bake was empty and is not used in the final asset.
- Original editable scene, OpenVDB cache, RGBA frames and review artifacts:
  `scratch/log-surface-fire-varied/`. The scene requires its cache directory.

Rebuild from the repository root (replace Blender with its executable path):

```powershell
blender --background --threads 8 --python chauffeur/tools/render_fire_simulation.py -- scratch/log-surface-fire-varied
blender --background --threads 8 --python chauffeur/tools/render_fire_simulation.py -- scratch/log-surface-fire-varied --render-existing
```

## Still backgrounds

`living-logs-day.png` and `living-logs-night.png` contain unlit logs, with no
baked-in flames. Turning motion off therefore leaves a furnished fireplace.
Built-in imagegen added logs to the preceding empty backgrounds. Only a
180x88 region at (520,426), feathered by four pixels, was retained from each
edit. Exact changed-pixel bounds are (521,427)-(699,513) in both images; all
other pixels match the respective empty background.

Day log-edit prompt:

> Use case: precise-object-edit. Edit the supplied 1536x1024 daytime living-room photograph. Change ONLY the lower interior of the empty fireplace. Add three beautifully realistic partially charred split oak logs, with rugged bark, cracked charcoal textures, varied natural irregular forms, resting in a low loosely crossed arrangement directly on the brick hearth. The logs must fit entirely inside approximate source pixel rectangle x542 to668, y462 to494. They should occupy about two thirds of the firebox width and sit back from the front stone lip. Keep their upper edge low, around y465, because a separately simulated flame animation will rise from this location. Add natural contact shadows. The logs are UNLIT: absolutely no flames, no smoke, no glowing embers, no fire glow. Preserve the existing fireplace perspective, rear brick wall, stone surround, mantel, furnishings, lighting elsewhere, camera, exact dimensions and composition. Output the full 1536x1024 image, not a close-up.

Night log-edit prompt (original night target plus generated day reference):

> Use case: precise-object-edit. Image 1 is the target NIGHT living room with empty fireplace. Image 2 is a DAY reference showing the exact three oak logs to insert. In image 1 add the SAME three realistic oak logs in the fireplace, matching reference 2's exact geometry, positions, perspective, size and bark texture, in approximate source rectangle x530-670,y442-502. Adapt only their illumination to the target night image's dim warm ambient light. Include realistic contact shadows. These are unlit static logs for a separate Blender flame overlay: NO flames, NO embers, NO smoke, NO fire glow. Preserve everything else in image 1: the brick firebox, fireplace surround, stone hearth, furniture, decorations, lighting, camera, crop, and exact 1536x1024 dimensions. Output the full image, not a crop.

The earlier empty-firebox edits retained only a 208x190 region at (508,336)
from the generated result over the original living-habitat image, with four
pixels of feathering. Their original prompts follow for reproducibility.

## Built-in imagegen prompts

Day:

> Use case: precise-object-edit. Edit target: the supplied living-room photograph. Change ONLY the interior of the fireplace opening (rough source pixel bounds x518–699, y350–497 in this 1536x1024 image). Make this fireplace COMPLETELY EMPTY and UNLIT: remove all flames, glowing embers, burned logs, metal log grate, and fire glow. Reconstruct its existing dark brown brick rear wall, brick right side and empty dark hearth floor with the exact existing perspective. A real filmed fire will be composited into this empty space later. Keep the stone surround, mantel, room, furniture, artwork, camera, geometry, lighting outside the opening, dimensions and crop unchanged. Output the full edited 1536x1024 room photograph, not a close-up, no other changes.

Night (input 1: original night scene; input 2: generated empty day scene):

> Use case: precise-object-edit. Image 1 is the EDIT TARGET: night living-room photograph. Image 2 is supporting reference showing the desired EMPTY fireplace geometry. In image 1 change ONLY the fireplace interior and immediate fire-light reflection on hearth: remove all flames, embers, logs, grate and orange fire glow, leaving an entirely empty unlit dark brick firebox matching reference 2's geometry. Keep the night room's existing dim illumination; the empty firebox should be darker than in reference 2. Preserve the exact 1536x1024 composition, furnishings, plants, windows, candles, lighting elsewhere, stone surround, mantel, dimensions and perspective of image 1. Output the full edited night room, no crop, no other changes.

## Encoding

From the repository root after rendering:

```powershell
python chauffeur/tools/encode_fire_loop.py scratch/log-surface-fire-varied/frames chauffeur/static/house_hybrid/fireplace-simulated.webm
```

The encoder uses Pillow and NumPy in the application Python environment and
FFmpeg on PATH. It checks that the final-to-first join preserves consecutive
simulation frames and reports coverage-weighted frame differences.

The alpha must be decoded with libvpx-vp9 when inspecting the WebM in FFmpeg.
The browser regression checks real decoded transparency, not just codec tags.

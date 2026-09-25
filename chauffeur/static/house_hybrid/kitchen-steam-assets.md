# Kitchen steam

Original Blender 4.5 Mantaflow simulation, using the same transparent-video
pipeline as the fireplace. No stock footage or generated still-image animation.

The earlier 160x240, 32-sample render had noisy, very faint alpha. Enlarging it
and multiplying alpha in CSS exposed that grain. This replacement renders the
required density directly and uses no browser opacity filter.

- Mantaflow gas domain: resolution 96, open boundaries, buoyant smoke emitted
  from a textured ring around the saucepan lid, with an 18-frame dissolve.
  Smooth height and side falloff in the volume material makes the vapor
  disappear into room air before it reaches the overlay edges.
- Cycles/OptiX: 384x576, 256 samples, adaptive sampling disabled so thin wisps
  receive the full sample count. Color denoising plus a two-render-pixel Gaussian
  reconstruction of premultiplied RGBA in Blender smooths volume coverage.
- Frames 49-192 follow two seconds of simulation warmup. The fireplace encoder
  overlaps 24 frames in premultiplied space to produce a five-second, 24 fps loop.
- VP9 with native alpha; no keying, opacity multiplier, or live WebGL rendering.
- Display rectangle: [649,244,96,144] in the 1536x1024 kitchen photograph.
  Render resolution is four times this display size in both dimensions.
- Editable scene, OpenVDB cache, preview PNGs and full frames are in
  `scratch/kitchen-steam-hq/`. The scene needs its cache directory.

Rebuild from the repository root, using Blender 4.5 and the application Python:

```powershell
blender -b -t 8 --python chauffeur/tools/render_kitchen_steam.py -- scratch/kitchen-steam-hq
blender -b -t 8 --python chauffeur/tools/render_kitchen_steam.py -- scratch/kitchen-steam-hq --render-existing
python chauffeur/tools/encode_fire_loop.py scratch/kitchen-steam-hq/frames chauffeur/static/house_hybrid/kitchen-steam.webm --pattern 'steam_*.png'
```

The first command bakes the simulation and renders three inspection frames.
The second renders the loop frames. The encoder requires FFmpeg on PATH.
When inspecting transparency in FFmpeg, explicitly decode with `libvpx-vp9`.

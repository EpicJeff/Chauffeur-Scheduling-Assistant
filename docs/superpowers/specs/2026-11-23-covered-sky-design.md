# Covered surfaces stop taking blue sky light; a softer sky fill

Date: 2026-11-23. Size: small change. Owner approved the approach ("Go ahead") after a diagnosis.

## Problem (measured)

The owner saw the top of the front porch floor turn blue, while its vertical faces in the same material looked neutral.

- **What lights it:** in the roof's shade, the porch top is lit only by two sky terms, and nothing knows the roof covers it.
  - The HemisphereLight sky colour is the zenith colour scaled so its brightest channel is 1 (`sky/look.js:122-124`, `twin_view.js:1811`, `:1818-1819`). Its intensity is 0.5 (`look.js:102`); live values are sky [.266, .502, 1] and ground [1, .984, .576].
  - The scene environment IBL is at 0.4 (`twin_view.js:163`, `:1813-1814`).
- **Measured** (June noon, owner's house; porch-top sRGB):
  - as now: 32,49,70;
  - hemisphere off: 15,26,39;
  - environment off: 15,25,39;
  - both off: black;
  - simulated cover (hemisphere sky = ground colour, environment x0.3): 47,51,39, which is neutral but olive.
- **Global saturation:** the zenith-based hemisphere over-saturates every shaded upward surface. Open ground in shade with the sun off reads 28,43,62. The cosine-weighted sky irradiance is already computed (`twin_view.js:1799`, `cloudIrradiance.top`).
- **Cover data already exists.** Every lit material already receives `vWeatherOpen` (`sky/weather_surface.js:530-544`), which is 0 under roofs, clipped to the real drip line (`sky/sky_cover.js:326, :345, :542`). Rain uses it; lighting does not.
- **The indoor sky rule** (`twin_view.js:511-531`) scales only the environment, only for materials named interior_wall, floor or ceiling, using the roof fade.

## Design

1. **Covered sky.** In the lit-material patch (wherever `vWeatherOpen` is available; extend the existing weather hook), apply a `cover` term: `cover = (1 - vWeatherOpen) * upFacing`, with `upFacing = smoothstep(0.2, 0.7, worldNormal.y)`. Vertical faces under a roof keep today's look.
   - **Hemisphere:** blend the sky contribution toward a bounce colour by `cover`.
     - The bounce is the hemisphere ground colour mixed toward a neutral of the same luminance (start at 50%), so it reads as bounced daylight, not olive.
     - Tune it against the owner's porch captures. Covered floors should read neutral-warm and slightly darker than open floors in shade.
   - **Environment:** scale diffuse and specular IBL by `mix(1, 0.3, cover)`, the indoor share.
   - **Roof fade:** use the same roof-fade uniform as `applyIndoorSky`, so lifting or hiding the roof gives the sky back.
   - **Interiors:** surfaces already handled by the indoor rule must not be double-scaled. Pick one path and document it.
2. **Softer sky fill.** The hemisphere sky colour comes from the cosine-weighted sky irradiance (`cloudIrradiance.top`), normalised as today, instead of the zenith colour. This calms all shade.
3. **Cost first** (owner rule):
   - FXC instruction slots and transcendentals for a typical lit material, before and after;
   - the D3D11 link time of one lit material;
   - the number of programs that recompile (all lit materials recompile once; measure the total warm-up delta on the owner's house);
   - no new samplers, attributes or uniforms beyond scalars.
4. **Look checks.** Chromium, on the owner's house (`C:\Users\ffejn\Downloads\Current house.chauffeur-house-11-20-2016.json`):
   - the porch at June noon and November noon;
   - the default overview;
   - open lawn in shade;
   - an interior room with the roof on and with it lifted;
   - the pool-house overhang.

   Before and after for each, plus the porch-top RGB through `.riv/porch_probe.py` (the diagnosis script).
   Acceptance:
   - the covered porch top has b/r under 1.25;
   - open sunlit surfaces change by less than 3% in luminance;
   - interiors are unchanged.
5. **Tests.**
   - A node test of the patched GLSL maths: the cover factor is 0 for open or vertical faces and 1 for covered upward faces, and the IBL scale is 0.3 at full cover.
   - The existing weather surface, sky and texture-unit tests stay green.
   - A Chromium check that the porch-top sample on the household fixture is neutral (b/r under 1.25) with the sun off.

## Non-goals

- Baked sky visibility (a possible later addition through the models-in-bake grid).
- Soft gradients toward open edges.

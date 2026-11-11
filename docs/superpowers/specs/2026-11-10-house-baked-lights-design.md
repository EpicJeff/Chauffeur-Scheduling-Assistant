# Baked room lights: design

Status: draft for the user's approval (2026-11-10). Follows the real-time Lights mode (branch `house-real-lights`), which stays as the fallback. Implements the twin design §9.4 for room lights.

## 1. Why

The user, 2026-11-10: "Can we use baked lightmaps for the lights and just toggle those on or off. Since the lights don't move, we should be able to optimize this." And: "The baking needs to follow immediately after" the real-time version.

Real-time point lights cost the whole scene per light. Without shadows they shine through walls into the next room, which the twin design (§9.3) forbids, and shadows are what the Pi 5 cannot afford. A bake does the expensive part once. At runtime each light's stored contribution is multiplied by its brightness and colour, which is exact because light adds linearly. That holds whatever the brightness, colour or on/off state, with soft shadows and no bleed, for about one extra texture read per pixel. It is the twin design's stated "enabler for Low".

## 2. Goals and non-goals

**Goals**
- Every light the house knows about gets a baked contribution:
  - a placed Home Assistant light (piece 3);
  - a fixture anchor read from the plans (piece 4).
- Baked contributions cover floors, ceilings and interior wall faces, including soft shadows and room-bounded light.
- At runtime a light's contribution is scaled by its live brightness and tinted by its live colour. It is the same on every tier, the Pi included.
- A lit room reads as lit from outside, through its windows (§9.3).
- A bake is never blocking. While a bake is missing or stale, the real-time path draws that light.
- The bake runs by itself when it is needed.

**Non-goals (this slice)**
- Daylight and sky bakes (§9.4's other half).
- Global illumination beyond one cheap bounce.
- Moving furniture, or open and shut doors, shown in the bake.

## 3. Decisions

1. **Where the bake runs: in the browser, on the GPU,** on any High or Max tier page that has the twin open (the editor or `/house/twin` on the desktop). The house's meshes exist only in the browser, because the generator is JavaScript and the add-on image has no Node. The HA box and the desktop are the same machine (user, 2026-11-10), so "the desktop browser" is the house's own hardware. The Pi 5 never bakes; it only downloads.
2. **The method: GPU texture-space baking with shadow maps.**
   - For each light, render the house's lightmap atlas in texture space.
   - Each texel takes the light's direct contribution, visibility from a cube shadow map, and N jittered samples of a small spherical light, which together give soft shadows.
   - One cheap bounce follows: the room's average lit albedo times its baked irradiance, added as a flat fill per room.
   - Then a small edge-aware blur.
   - This needs no ray-tracing library and no new package; three.js r187 is already vendored.
3. **Surfaces get a second UV set (`uv2`) built after `mergeStatic`.**
   - Each planar face becomes a chart, scaled to world size at a set texel density (High 8 texels/ft).
   - Charts are packed into atlas pages (2048², several pages if needed) with 2-texel gutters.
   - Deterministic: the same model and generator version give the same atlas.
4. **Storage: per-light single-channel maps, packed four lights to an RGBA page.**
   - The runtime shader sums, for each texel's page, `channel_i × brightness_i × colour_i`.
   - Lights are grouped by room so a surface reads one page.
   - Stored as PNG through a parent-only upload route under the house's data (`DATA_DIR/bakes/<key>/`), served to wall tier pages with ETag caching.
5. **Bake key and staleness.**
   - The key is a hash of the model round's geometry, the generator version, the atlas parameters and each light's spot.
   - A light whose spot or geometry changed is stale. Only stale lights are re-baked.
   - A stale light draws real-time until its new bake lands.
6. **Trigger: automatic, plus a button.**
   - An open High or Max twin page bakes stale lights in the background at low priority, idle frames only, never while the person is dragging.
   - A **Bake lighting now** control lives in the twin's settings.
   - The status chip (piece 4) shows `Baking lights 3 of 12` while it works.
7. **Runtime.**
   - Lights mode on a light with a fresh bake adds its baked term. Real-time pool lights are kept for lights without one.
   - The fixture glow (real-time slice) stays.
   - Windows of a lit room get an emissive spill term so the room reads lit from outside.

## 4. Proven by

- A node test checks that the atlas is deterministic and that no two charts overlap.
- Pixel tests on the household fixture:
  - a baked kitchen light brightens the floor near the fixture more than the far corner;
  - no measurable light lands in the next room through a wall;
  - turning the light off returns the pixels to the unlit values;
  - colour tints follow the live colour.
- A stale-key test: moving a light re-bakes only that light.
- Pi tier frame time with 12 baked lights on is within 5% of all lights off.

## 5. User answers (2026-11-10)

- Trigger: any open 3D view on a High or Max tier (decision 6 stands).
- Daylight: the user asked how daylight can be baked when the lighting must follow the actual sun, moon and time of day. Answer and ruling:
  - **The sun and moon are not baked.** Each stays one real-time directional light that follows its real position (the twin's Time already does this), with its own shadow map. One light is affordable on every tier.
  - **What is baked is sky visibility:** how much of the open sky each texel can see, through windows and doors. The sky's shape changes little over the day, but its colour and brightness change a lot. At runtime that colour and brightness multiply the baked visibility, which gives soft interiors, dark corners and daylight falling off away from windows, at any hour and in any weather.
  - It is one more channel in the same atlas and a cheap extra pass, so it joins this slice as `sky` (designer's call; the user may move it later).
  - Baking the sun at many positions and blending is rejected: the storage and bake time grow with every hour and season, for a result the real-time sun already gives.

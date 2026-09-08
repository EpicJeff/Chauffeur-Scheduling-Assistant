# The Home — the dollhouse the panel lives in

**Date:** 2026-09-08
**Status:** Approved direction (user chose: one dollhouse scene; global toggle default OFF; v1 rooms = kitchen, garage, yard/curb, mudroom, living room)
**Version target:** v2.463.x onward (arcs H1–H4)

## Why

The Kitchen proved the room: furniture that carries the day, lean-ins that
wear the board's own cards, calm as success, a Pi discipline that renders
only when something changes. The user's ruling: scale it to the whole
house. A low-poly dollhouse — full exterior with cutaway rooms — becomes
the panel's ambient home, eventually replacing the home board as the
panel's resting state (behind a toggle, board remains the fallback).

## Laws (all kitchen laws inherited, house-scaled)

1. **Attention-only furniture** — and attention-only ROOMS: at exterior
   view, a room shows warm window light only when a zone inside needs a
   person; a dark quiet house at night is success.
2. **Quiet room = success.**
3. **The room never writes** — house files (house.js / house_room.py)
   perform no mutating verbs, pinned by test. Board cards worn on lean-in
   write through their own WALL-tier endpoints, exactly as on the kitchen
   and every panel (the v2.462.0 nuance, unchanged).
4. **Every signal from one endpoint** — `GET /api/house/state`, every
   section try/except falling to `_CALM`.
5. **Family-safe by construction** — same banned imports (threads,
   missions, mind, watchers, occasions) and banned keys (counterparty,
   gift, sensitive, insight, finding) walk, now over house_room.py too.
6. **Urgency still screams** — the house is ambient, but an imminent
   leave pins the hero card overlay at house level. Replacing the board
   must not bury "leave in 12 minutes".

## The scene (one dollhouse, static/house.js)

- Exterior shell with a cutaway corner (reference: isometric dollhouse
  image, 2026-09-08). Idle camera frames the whole house.
- Tap a room → camera tweens inside; the room behaves exactly as the
  kitchen does today: zones, since-you-were-here glow, lean-in wears the
  board card, ↗ chip is the tap-through. Back chip → exterior.
- **Interiors are lazy-built** (THREE.Group constructed on first entry;
  exterior always resident, low-poly). Only the active room paints zone
  canvas textures. Idle house = zero GPU (render-on-demand carried over:
  tweens, honest animations, state/focus changes only).
- DETAIL tiers, pixelRatio 1, no perpetual RAF — all kitchen discipline.
- Sky dome IS the weather: forecast drives tint/clouds, sun/moon by
  clock. No animated rain in v1 — particles need constant RAF and would
  break idle-zero-GPU. Sky redraws on state change only.

## Rooms and zones (v1)

| Room | Zones (signal) | Lean-in card | Notes |
|---|---|---|---|
| **Kitchen** | fridge (moments/photos — STAYS here, v2.462.2 door art kept), counter/stove (tonight's dishes), **pantry** (shopping — replaces corkboard), window (weather), wall calendar (today) | as today | Corkboard retired. Pantry = shelf closet; honest twist: long list = bare shelves. |
| **Mudroom** | door (next leave, be-ready-at), packing/outing bags, backpack per kid | hero card / packing card | Door signal migrates OUT of kitchen here (H3). |
| **Living room** | radio → real music player, pet bowl → critters, hearth/presence | music player, pet editor/battle | Migrate from kitchen in H3. |
| **Garage** | one parametric car per car record: fuel/battery %, range, plugged-in warning (`readiness_warnings`); car ABSENT when device_tracker says away | car status card | Door connects to kitchen. |
| **Yard/curb** | sky (weather), school bus at curb when `bus_active` says near, driveway presence | — | Bus live layer gets a stage. |

## Parametric cars (the bonus challenge)

- New `body_type` field on the car record: sedan, suv, truck, minivan,
  hatch, wagon, van. Unset = generic car.
- One `buildCar(params)` in house.js; per-type parameter packs: hood
  length, cabin height, bed/hatch flags, wheel radius. `color_code` is
  the paint; `seat_capacity` nudges length.
- **Hand path (law):** body-type picker added to the car editor
  (config.html cars form — an entity field, not a setting). No LLM per
  render, no paid key, no downloaded meshes.

## Surface & data

- `/house` — full-screen room page, URL-only until H4 (kitchen
  precedent: earn the nav).
- `GET /api/house/state` — WALL_OR_SERVICE tier, same reasoning as
  kitchen (panels are devices; content family-safe by construction).
- `services/house_room.py` **imports kitchen_room's section builders**
  (fridge/counter/board/door/calendar/radio/window/pet) — never forks
  them — and adds: garage (cars + `car_levels` + `car_location`), curb
  (`bus_active`/`bus_map_position`), mudroom (door + packing counts),
  living (radio/pet/presence), sky (full forecast, not just wet-flag).
- `/kitchen` and `/api/kitchen/state` untouched until H4, then /kitchen
  redirects into the house framed on the kitchen.

## Rollout (arcs)

- **H1** — house shell + camera model + kitchen transplanted as first
  cutaway + weather sky. `/house` reachable by URL.
- **H2** — garage + parametric cars + body-type editor + curb bus +
  driveway presence.
- **H3** — mudroom + living room; door/radio/pet zones migrate out of
  the kitchen (kitchen slims to food + pantry + window + calendar +
  fridge).
- **H4** — `panel_home_mode` setting (`board` | `house`, default
  **board**) in the panel group of settings_registry beside
  `panel_home_board`; `/home` serves the house when flipped; no-WebGL or
  context-loss navigates to the board REGARDLESS of the toggle (the
  board is the designed fallback, not an apology); /kitchen redirect.
- The flip itself is the user's act, as always.

## Not in v1 (deliberate)

Kids' rooms (routines maybe later — never surveillance), animated
rain/snow, free camera orbit, admin/Study content anywhere in the house
(Study stays its own admin page; at most a locked door), per-panel
toggle granularity (global first), car photo `image` in the garage
scene, room editing/decoration.

## Testing

- house_room state runtime test with seeded fixtures — real numbers
  land (source-reading tests miss runtime breaks).
- Poison every source → status ok, all sections calm.
- Family-safe pin extended: banned imports + banned keys over
  house_room.py and its JSON.
- Never-writes pin: no mutating verbs in house.js / house_room.py.
- body_type CRUD round-trip through /api/cars.
- Endpoint tier gates; template pins (chfBase, no browser dialogs);
  tailwind rebuilt if template classes change.
- Screenshot proof per docs/ui_design_guide.md for each arc.

## Review resolutions (pre-answered)

- **Pi risk compounds an unverified kitchen:** kitchen v2.462.3 not yet
  device-verified; user should give the Pi a look during H1, before H4
  flips anything. Fallback-to-board is the net either way.
- **Moments stay on the fridge**, not a living-room hearth — the fridge
  door photo work (v2.462.2) is beloved and lifelike; hearth carries
  presence instead.
- **Why no text-to-3D for cars:** heavy, off-device, mesh quality
  roulette, hostile to Pi. Parametric silhouettes + real paint color
  read as "your truck" at this art style.
- **Global toggle over per-panel:** ships dark like the mission engine;
  per-panel granularity is a later slice if wanted.

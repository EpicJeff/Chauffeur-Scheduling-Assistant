# The Kitchen — the family's ambient room on the wall

**Date:** 2026-09-06
**Status:** Approved direction (user: "go ahead and build it and we can optimize later")
**Version target:** v2.458.x

## Why

The Study gave the ADMIN side a living room: ten signals as furniture,
glance-and-look, never a scoreboard. The wall panel — the family's shared
screen — has boards but no room. The Kitchen is the Study's family-side twin:
a low-poly 3D kitchen whose furniture carries the household's day, safe for
every eye in the house, calm when nothing needs anyone.

## Laws (ported from the Study, all four locked)

1. **Attention-only furniture** — a zone exists only if its signal can need a
   person; decoration never pretends to be data.
2. **Quiet room = success** — everything calm renders a warm, settled kitchen,
   not an empty error state.
3. **The room never writes** — pinned by test: `services/kitchen.py` and
   `static/kitchen.js` perform no POST/PUT/DELETE and import no mailer.
4. **Every signal is one number from one endpoint** — `GET /api/kitchen/state`,
   each section built inside try/except falling to a `_CALM` form.

Plus the Kitchen's own law: **family-safe by construction.** The state
endpoint may carry NOTHING sensitive: no thread/counterparty data, no gift or
occasion-surprise content, no findings, no mind insights, no mission
transcripts, no member-status or health detail. A source-pin test asserts
`kitchen.py` imports none of `threads`, `missions`, `mind`, `watchers`,
`occasions`, and the state JSON never contains the keys `counterparty`,
`gift`, `sensitive`, `insight`, `finding`.

## Surface

- `/kitchen` — full-screen room, served like the study (`TemplateResponse`),
  shell rule `(ANY, '/kitchen', ANYONE, None)`.
- `GET /api/kitchen/state` — rule `(ANY, '/api/kitchen/state', WALL_OR_SERVICE,
  None)`: **DEVICE tier allowed on purpose** (wall panels are devices; the
  content is family-safe by construction, so the read needs no person).
- NOT in the desktop nav and NOT in the panel shelf vocabulary for v1 —
  reachable by URL (`/kitchen`, `?panel=true` styling applies via the normal
  panel profile); shelf/board integration is a later slice once the room has
  earned its place. `test_nav`'s ADMIN_ONLY_SLUGS is untouched (kitchen is
  not an admin page; it simply has no nav entry yet).

## The furniture (seven zones, one number each)

| Zone | Signal (the number) | Detail on focus | Tap-through |
|---|---|---|---|
| **Fridge** | new family moments since this panel's last visit (localStorage epoch, study idiom) | latest 3 moment captions + who | `/moments` |
| **Counter/stove** | dishes planned tonight (0 = calm) | dish names + hands-on minutes | `/meals` |
| **Corkboard** | open shopping items | top 6 item names | `/lists` |
| **Door** | minutes until the next leave today (none = calm) | "16:40 — Soccer (Maya)" style line from the schedule cache | `/home` |
| **Wall calendar** | family events remaining today | next 3 titles + times | `/calendar` |
| **Radio** | 1 if music is playing anywhere, else 0 | track + artist | `/music` |
| **Pet bowl** | family pets (count) | name + level per pet | `/chores` (pets live on the kid surfaces) |

Sources (all existing, all family-visible already): `storage.
count_event_moments_since` / `get_recent_event_moments`; `meals.eating_plan`
+ `meals.showing_plate` + `meals.plate_totals`; `storage.get_shopping_items
(include_checked=False)`; `storage.get_cached_schedule()` (events +
assignments, today, future-only — the calendar-shows-everything cache, never
recomputed); `ma_api.available()` + `ma_api.command('players')`;
`storage.pets_table`. Every section try/except → `_CALM`.

## The room (static/kitchen.js, modeled line-for-line on study.js patterns)

- Vendored three.js r150 (already at `static/vendor/three.min.js`).
- ZONES registry + declarative FURNITURE map + `applyState` as the sole data
  path; 60s poll with one-time outage chip; since-you-were-here glow
  (localStorage epoch-seconds); tap = focus-tween then tap-through (universal
  lean-in, generic bbox framing — study slice 3); detail painted lazily as
  canvas textures on focus, cached per payload change.
- Geometry: floor/walls/window, fridge, counter + stove + pot, corkboard,
  door with clock plaque, wall calendar, radio, table + chairs, pet bowl,
  ceiling lamp. Low-poly, no shadows, `setPixelRatio(1)`.
- **Render-on-demand (the Pi discipline, new vs the study):** no perpetual
  RAF loop. Render exactly when (a) a camera tween is active, (b) an honest
  animation is active (pot steam only when dishes tonight > 0; radio needle
  only when playing), or (c) state/focus changed. Idle room = zero GPU work.
  `webglcontextlost` → swap to fallback (study idiom).
- **Fallback is first-class:** no-WebGL (or context loss) renders the same
  seven signals as the calm 2D list — `textContent` only, XSS pinned by test.
  The fallback is the DESIGNED experience for weak hardware, not an apology.

## Not in v1 (deliberate)

Weather (HA-degrade questions), announcements/corkboard notes, follow-me,
any write affordance, shelf/board integration, admin data of any kind,
kid-lens variants (the room is already safe for the youngest eye — that IS
the lens).

## Testing

- State shape: seven sections present, each `_CALM`-able (poison every source
  → status still ok, all sections calm) — study's `_reset` idiom.
- Family-safe pin: banned imports + banned keys walk of the JSON.
- Never-writes pin: no mutating HTTP verbs in kitchen.js, no storage writes
  in kitchen.py (except none — reads only).
- Endpoint gates: DEVICE-tier read allowed; shell serves.
- Template pins: chfBase (no self-computed depth), no browser dialogs,
  fallback textContent-only; tailwind rebuilt.
- Runtime: one test RUNS `kitchen.state()` end-to-end with seeded fixtures
  and asserts real numbers land (source-reading tests miss runtime breaks).

## Review resolutions (pre-answered)

- Pi 5 performance: render-on-demand + 1080p + pixelRatio 1 + no shadows;
  the user will optimize later if the panel stutters — fallback is the net.
- Radio via `ma_api.command('players')` inside try/except: MA absent →
  calm zone (HA-degrades-gracefully rule).

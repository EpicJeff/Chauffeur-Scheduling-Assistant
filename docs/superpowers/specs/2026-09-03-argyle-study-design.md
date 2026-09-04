# The Study — a living room-scale admin home

**Date:** 2026-09-03
**Status:** Approved design, pre-implementation
**Origin:** brainstorm 2026-09-03; ceiling proven by a three.js spike the user
approved ("movement of things makes it feel alive"). Spike code is throwaway;
production starts clean.

## Problem

The admin surfaces (/mind, /threads, /intake, and the dials around them) are
text-heavy card piles. Live use named three failures: no **state at a
glance**, no **visible thinking** (pages read as logs, not a mind at work),
and no **pull to return** — checking in feels like homework. Triage speed was
explicitly NOT the complaint.

## Concept

**The Study** is a new admin home page: a low-poly 3D office rendered in
three.js, where every piece of furniture is a live readout of one domain the
household might need attention on. You open it routinely to see how things
are going; every existing page stays exactly where it is as the deep-dive you
reach *through* the room. The room is a **lens — it never writes.** Every
mutation happens on the pages that already own it.

The reference aesthetic is cozy stylized low-poly (approved via spike):
warm-graded lighting, canvas-generated textures (wood, cork, plaster, rug),
rounded-bevel geometry, day/night driven by the local clock, and constant
subtle life — camera drift, cursor parallax, dust motes, steam, a working
wall clock, and periodic "Argyle files a paper from the tray to the board"
animation. The look is flat-shaded charm, deliberately not painterly.

## Laws

1. **Only things that can need attention get a physical form.** Config,
   editors, and registries never appear in the room.
2. **A quiet room is the success state.** Everything handled renders as calm
   (level stacks, empty tray, sagging nothing), never as an empty-state
   apology. This is the app's blank-means-blank ethos in 3D.
3. **The room never writes.** Taps navigate; nothing in the scene mutates
   household state.
4. **Every furniture signal is one number or flag from the state endpoint.**
   No client-side inference.

## Route, access, fallback

- **`GET /study`** — admin-only nav slug (same nav treatment as /mind:
  hidden from kiosk shelves and wall panels). Parents and adults only;
  child/helper/guest get 403 through the same gate the mind endpoints use.
- Not the landing page. Nav gets a Study entry; adoption is by habit.
- **Desktop-first.** Phones and browsers without WebGL get the **honest
  fallback**: a plain prioritized what-needs-attention list rendered from
  the identical state payload (severity-ranked rows, each linking to its
  deep-dive). The fallback is not a stub — it is the mobile experience.

## Furniture inventory (v1 — locked with the user; v2 rows marked inline)

| Furniture | Domain | Signal (all read-only) | Tap → |
|---|---|---|---|
| **Evidence board** | Mind insights + threads | pinned cards (insight lines, thread titles); stalled thread sags/yellows with a decorative dangling thread tail; sensitive rows filtered by role server-side. **v1 amendment (final review, v2.453.11):** cross-pin strings removed — the app stores no real insight-to-thread relation yet, and a drawn string claims one; relation edges return when a stored link exists | /mind |
| **Desk paper stacks** | In-hand plans | one stack per plan, height = open steps; a due step renders as an amber sheet sticking out | /mind |
| **In-tray** | Intake proposals | sheet count | /intake |
| **Monitor stickies** | Findings | sticky count, worst severity colors the top sticky. **v2 amendment (v2.454.0):** the bezel and the glass left this zone for the Monitor screen below; the notes stuck around them stay here | focus only — findings have no page yet (Needs-You tile unbuilt); the focused stickies are the findings view |
| **Monitor screen** *(v2.454.0)* | The household's own week, per person | a live node graph: one cluster per family member, cluster size = that person's events in the next 7 days (an event owned through two of one person's calendars counts once); everyone gets a cluster, including whoever has an empty week. Cap 8. The orbiting, the webbing between near dots and the pulse between two clusters are DECORATION and claim nothing — the cluster sizes are the only data on the glass. Canvas texture, ≤10 redraws/sec, none at all while the tab is hidden | nothing — no such page exists, so the tap focuses the Ask-Argyle bar and pulses it. **The only zone in the room that does not navigate** |
| **Wall map** *(v2.454.0)* | Trips | a pin per planned trip on the free wall between the window and the corner, each on a sagging string back to home — the one relation drawn in this room that the app actually STORES (a trip has a destination; the family leaves from home to reach it). Undated trips keep a pin; past trips lose theirs; the soonest dated one is bigger and lit. Cap 6. Pin placement is a hash of the trip's own name — decoration, stable between polls — and the drawing underneath is a map of nowhere on purpose. A resolved non-parent never sees a `parents`-audience trip (`scope.audience_allows`); `viewer is None` is the admin surface, which `/trips` already shows everything to | /trips |
| **Wall calendar** | Next 7 days of solver output | a day with ≥1 unassigned driver event shows red; driver events only (all-day events never count, per the calendar law) | /dashboard |
| **Window** | Vitals pulse | weather = the week vs the family's own baseline (levels only; never per-person) | /mind (vitals live in its snapshot context) |
| **Key hook** | Cars | one key per active car with telemetry; low fuel/charge or stale telemetry = dangling tag | /config#cars (the cars editor — no standalone cars page exists) |
| **Contracts on desk** | Negotiation | open deals awaiting signatures = slips; count | /dashboard (deal banners live on the schedule surfaces) |
| **Bookshelf binders** | Programs | one binder per active program; pulled-out spine = quiet practice or pending rebaseline offer | /programs |
| **Desk gauges** | System health | mind caps spent today, web-research month count vs cap, ingest error streak | /mind (dials) / /intake |
| **Clock, plant, rug, lamp, photos** | — | decoration; clock shows real time | — |

Adding furniture later requires passing Law 1; the inventory table in this
spec is the registry of record.

### Detail on focus (v2.455.0)

Leaning into a zone triggers a **one-time detail paint** for it: a canvas
drawn once and uploaded as a texture, cached per zone and invalidated only
when `applyState` sees that zone's own slice of the payload change. The idle
room is unchanged — every detail surface is hidden until a lean-in, and its
canvas is not allocated until the first paint, so a visit that never leans
anywhere allocates none of them. **All of it is `fillText` into a canvas,
never `innerHTML`**; a test pins that `study.js` assigns `innerHTML` exactly
once (the fallback list's fixed row template, which carries no model text).
Nothing here bypasses a section's existing filter: the board rides
`visible_insights`, and the desk's `line` rides the same parent-only drop
that already removes the whole row.

| Furniture | What a focused reader gets | New payload |
|---|---|---|
| **Evidence board** | every pin card carries its item's real text, wrapped to 3 lines; the decorative "handwriting" bars stand down | none — `pins[].label` already existed |
| **Desk paper stacks** | the top sheet of each pile prints the plan's own line + "N steps open · one due" | `desk[].line` — no gate of its own; the row is dropped whole for a non-parent |
| **In-tray** | the top sheet lists the waiting proposals | `tray.items[].title`, cap 5 |
| **Monitor stickies** | each note carries its finding's sentence | `stickies.items[] = {line, severity}`, cap 5 |
| **Wall calendar** | the face redraws as a real 7-day grid: dates, up to 3 event titles a day in the assigned driver's own colour, `+N` for the rest, red retained on uncovered days. The idle cells stand down and their red is redrawn here | `calendar.days[].events[] = {title, color}` cap 4, plus `more` — the count that did NOT fit, so `+N` is the day's real remainder. Colour is the driver's `color_code`, ghosts included; unstored → `null` |
| **Window** | a card standing **on the sill** lists the week's signs as levels | `window.signs[]` — worse-first only once `ready` |
| **Key hook** | a card under each key: name, percentage, level bar coloured by low/not | `keys[].pct` + `keys[].kind` (`battery`/`fuel`) — the reading the low call was made on, battery-first as `cars.py` decides it |
| **Contracts on desk** | the top slip prints the deals awaiting answers | `contracts.items[].title`, cap 3 — `seed_title`, falling back to `line` |
| **Bookshelf binders** | each spine reads bottom-to-top: the program title, and under it a compact week | `binders[].detail`, e.g. `3x30min · Breathing`. Read, never defaulted, and deliberately **not** "phase 2 of 4" — `programs.progress` withholds the phase total because a count next to a total is a completion percentage away |
| **Desk gauges** | painted readouts on the dials: think n/cap, research n/cap, ingest errors | none |
| **Monitor screen** | name + count beside each cluster, on its own high-res overlay so the graph stays at 256×150/10fps | none |
| **Wall map** | trip title + date beside each pin, `home` on the home marker; labels route around each other and the pins, and draw a leader back when they had to step away | none |

### Spike punch list, second pass (v2.455.0)

Three modelling faults the room had been carrying, all found by looking at
it rather than at the code:

- **Chair base.** The spoke was yawed by `-a + PI/2` while its caster was
  placed along `a` — the same line only where `cos a` is zero, so four legs
  out of five pointed somewhere their caster was not and the casters read as
  loose pucks on the rug. Rebuilt as five groups, each yawed to its own leg
  and everything inside authored along that group's `+z`, so the spoke and
  the wheel cannot disagree. The base stands on the RUG's top face, not on
  the boards underneath it.
- **Keyboard and mouse.** Laid flat with `rx` and turned with `ry` — but
  with the default XYZ Euler order the `ry` composes *before* the flip, so
  it came out as a tilt about world X: one end buried in the desktop, the
  other lifted into the air. The yaw belongs in `rz`, applied after the
  flip. `TOP` also now includes the rounded-extrude bevel, so everything on
  the desk rests on the wood rather than 2cm inside it.
- **The desk photo frame.** Grounded in the arithmetic (its foot was on the
  wood) but the desk behind it is edge-on from the room's own camera, so it
  read as a picture frame hanging in mid-air against the baseboard. Moved to
  the shelf, beside the plant.

## State endpoint

**`GET /api/study/state`** — one aggregation, parents/adults only, role
passed through so sensitive insight lines are filtered by the exact
`visible_insights` gate that already protects the lane. Response is
`{furniture: {board: {...}, desk: [...], tray: {...}, ...}}` — counts,
flags, short labels, and stable ids only; no prose bodies.

- Every section is built inside its own try/except, `mind.snapshot`-style: a
  provider that raises contributes an empty-calm section and never sinks the
  room (HA-degrades-gracefully applies to every source).
- Sections reuse existing service calls only — `mind.visible_insights`,
  `mind_insights` state `in_hand`, `threads.stalled`/`get_threads`, pending
  `event_proposals`, `findings.open_findings`, the cached schedule's
  unassigned driver events, `vitals.snapshot_section` levels,
  `cars.car_levels`, open negotiation deals, active programs +
  `weekday_shortfall`, mind `_bump_call` counters + `web` month count +
  ingest log tail. **No new state is written anywhere.**
- Client polls every 60s. No SSE/websockets in v1.

## Scene architecture

- **`static/vendor/three.min.js`** — vendored r150 UMD (~600KB), the same
  vendoring pattern as Alpine. Offline HA constraint holds; no CDN.
- **`templates/study.html`** — page shell, auth-gated like /mind; carries the
  fallback list markup and the WebGL/viewport detection that chooses room vs
  list.
- **`static/study.js`** — the scene. Declarative core: a `FURNITURE` table
  maps state keys to scene mutations (stack heights, sag angles, tag
  visibility, calendar cell colors), so adding a signal is a table row, not
  scene surgery. Texture generation via canvas (wood/cork/plaster/rug/sky),
  rounded-extrude geometry helper, day/night from `new Date()`.
- **Interaction:** hover = tooltip naming the thing and its signal; first
  tap on a zone = camera lean-in preset + summary chip; second tap =
  navigate to the mapped page. Escape or clicking empty space = lean back. (v1 has exactly
  two lean-in zones: board and desk; others navigate on first tap.)
  **v2.454.0:** a zone may instead carry an `act` — something to do *here* —
  which runs in place of navigating; the monitor screen is the only one, and
  it focuses the Ask-Argyle bar. An `act` still never writes.
  **v2.455.0 — lean-in is universal.** Every registered zone gets
  focus-then-through. The preset is computed rather than placed:
  `focusFor()` takes the zone's world-space bounding box, reads which way it
  faces off where it sits (back wall / side wall = straight on; anything
  else is on the desk and is read from the yaw it was built with, at a ~26°
  elevation), and backs away until the box fits the band of the page the nav
  bar and the Ask-Argyle chip leave free. A zone may declare `focusMeshes`
  when its registry is wider than its signal (the desk does — its legs are
  hit targets, not the thing you leaned in to read); the board keeps a
  hand-tuned preset. Second tap still navigates, or runs the `act`.
- **Since-you-were-here:** per-device `localStorage` timestamp; items whose
  `changed_ts` exceeds it glow softly until the page has been open 10s, then
  the timestamp updates. Wrapped in try/catch; absent storage = no glows.
- **Life:** camera drift + cursor parallax, monitor glow breathing, steam,
  swaying stalled pins, dust motes, working clock hands, and the
  tray-to-board flying paper every ~90s **only when the tray is non-empty
  and the Mind is enabled** — the animation is honest, not theatrical.
- **Perf:** pixelRatio capped at 2, one 2048 shadow map, static geometry
  (~150 meshes), no postprocessing. Target: idles quietly on a mid laptop.

## Spike punch list (carried into the build, not fixed in the spike)

Corkboard frame rails aligned to the board's actual bounds; monitor
bezel/stand orientation corrected; key-hook props modeled properly; chair
silhouette; color grade pushed nearer the approved reference's saturation.

## Error handling

- State endpoint total failure → room renders fully calm with a small
  "can't reach the house right now" chip; retry on next poll.
- Missing section → that furniture's calm state (Law 2 covers absence).
- WebGL context loss → swap to the fallback list in place.

## Testing

- `tests/test_study_state.py` — per-section aggregation with stubbed
  services; a raising provider yields empty-calm without sinking the
  payload; role filtering (child 403; adult vs parent sensitive-pin
  filtering); unassigned-day math uses driver events only.
- One runtime test driving `GET /api/study/state` through main.py (the
  source-reading-tests-miss-runtime-breaks rule).
- Template pin: study.html references the vendored three path and contains
  the fallback list container.
- Scene visuals: not unit-tested; build ends with a playwright screenshot
  pass (the ui-design-guide screenshot-proof rule) checked by eye.

## Out of scope (named so they stay out)

- In-room drawers rendering real cards (v2 candidate if lean-in proves loved)
- Phone-parity 3D, touch-first camera
- Wall-panel or kiosk exposure
- Any write path from the room
- Replacing or altering any existing page, including /mind's lane
- An Argyle avatar in the room, sounds/music
- SSE/live push; occasions gift-box furniture; channels anything

## Design decisions record

- Room chosen over pure node-graph and zoned-dashboard after a live
  three-way comparison; graph survives as the evidence board.
- Scrubber cut (history without value); kernel kept as since-you-were-here
  glow. Voice briefing cut (redundant with the daily digest).
- Code-authored 3D (ceiling A) chosen over painterly plates + sprite
  pipeline (B) and hybrid (C) after the user judged the spike's ceiling
  live: no asset dependency, infinitely iterable, accepted flat-shaded look.

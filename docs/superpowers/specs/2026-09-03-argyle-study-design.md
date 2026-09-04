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

## Furniture inventory (v1 — locked with the user)

| Furniture | Domain | Signal (all read-only) | Tap → |
|---|---|---|---|
| **Evidence board** | Mind insights + threads | pinned cards (insight lines, thread titles); stalled thread sags/yellows with a decorative dangling thread tail; sensitive rows filtered by role server-side. **v1 amendment (final review, v2.453.11):** cross-pin strings removed — the app stores no real insight-to-thread relation yet, and a drawn string claims one; relation edges return when a stored link exists | /mind |
| **Desk paper stacks** | In-hand plans | one stack per plan, height = open steps; a due step renders as an amber sheet sticking out | /mind |
| **In-tray** | Intake proposals | sheet count | /intake |
| **Monitor + stickies** | Findings | sticky count, worst severity colors the top sticky; screen glow is decoration | /dashboard (findings render there today) |
| **Wall calendar** | Next 7 days of solver output | a day with ≥1 unassigned driver event shows red; driver events only (all-day events never count, per the calendar law) | /dashboard |
| **Window** | Vitals pulse | weather = the week vs the family's own baseline (levels only; never per-person) | /mind (vitals live in its snapshot context) |
| **Key hook** | Cars | one key per active car with telemetry; low fuel/charge or stale telemetry = dangling tag | /config#cars (the cars editor — no standalone cars page exists) |
| **Contracts on desk** | Negotiation | open deals awaiting signatures = slips; count | /dashboard (deal banners live on the schedule surfaces) |
| **Bookshelf binders** | Programs | one binder per active program; pulled-out spine = quiet practice or pending rebaseline offer | /programs |
| **Desk gauges** | System health | mind caps spent today, web-research month count vs cap, ingest error streak | /mind (dials) / /intake |
| **Clock, plant, rug, lamp, photos** | — | decoration; clock shows real time | — |

Adding furniture later requires passing Law 1; the inventory table in this
spec is the registry of record.

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

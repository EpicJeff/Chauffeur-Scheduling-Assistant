# Chauffeur Family-Hub Roadmap

Status of the family-network pivot and the backlog for future phases.
Shipped-feature details live in `system_capabilities.md` (the live spec) —
this file tracks what is NOT built yet, with enough context to pick any item
up cold. Last updated: 2026-08-03 (v2.32.0).

## Shipped (phase 1 + chores arc, v2.8.33 → v2.19.0)

PWA installability · FamilyMember overlay + roles (parent/adult/child/helper)
+ per-member PINs · HA API bridge · family messaging (family/DM/event
channels, web push + HA notify) · family map (HA person entities, Leaflet) ·
passenger "My Day" lens (swipe/day-nav, split-leg collapse) · Music tab
(MA-only players, rich search, favorites, artwork proxy) · **Sendspin phone
player** (each member's phone is a real MA player via the add-on's wss relay)
· chore economy (pot/claims/points ledger/parent verification) · daily
routines + streaks · rewards store with parent-approved redemptions.

## Next-up candidates (no platform prerequisites)

- **Agent tools for the family hub. SHIPPED v2.25.0 (2026-08-01)** — six
  tools in both stacks (send/read family messages + DMs with full push
  fan-out, list/claim chores, routine status), PWA sender identity trusted
  server-side, voice/admin must name the actor or the agent asks. Argyle
  FAB restored on the Messages channel list (still hidden inside open
  threads). Parent-voice chore VERIFICATION remains deliberately out (PIN
  equivalence — see open questions).
- **Voice memos (push-to-talk).** The walkie-talkie moment from the original
  vision. Schema is ready (`ChatMessage.type='audio'` + `attachment`
  reserved); needs MediaRecorder capture, an upload endpoint + storage,
  autoplay-on-open in threads, and a chirpy push. iOS PWA records fine in
  foreground.
- **Gate HA-dependent UI when HA is unreachable** (user request 2026-07-31):
  hide Map/Music tabs + map nav link when `/api/ha/status` says unavailable
  (local dev without HA shows dead features today). Backends already degrade
  gracefully — this is a UI-visibility pass only. Note the proper dev
  alternative: `ha_base_url`/`ha_token` settings point local dev at real HA.
- **Kiosk points leaderboard — ALREADY SHIPPED, stale item (noticed
  2026-08-01).** `/chores?kiosk=true` has been exactly this since v2.20.0
  (leaderboard-only collapse, 60s refresh; `/routines?kiosk=true` = streak
  board). Only unbuilt remnant, if ever wanted: a compact points strip ON
  the main schedule dashboard's kiosk view, so one panel shows both.
- **Per-member notification preferences.** Members with both web push and HA
  notify get every message twice (accepted v1 tradeoff). Add a per-member
  lane preference or dedupe.
- **Unify Config's Drivers/Passengers/Family tabs into one People tab.
  SHIPPED v2.22.0 (2026-08-01)** — member cards are the hub; the intact
  driver/passenger forms open on demand as role profiles; solver toggles
  moved to General → Solver Behavior. Details in system_capabilities.md.

## The intake arc (capture layer — the next big thing, decided 2026-08-01)

The gap: everything downstream of an event existing is automated (solver,
departure pushes, digests, My Day, threads), but every event still enters via
a parent transcribing it into Google Calendar. The "logistics parent" is the
family's API — that's the mental load the app hasn't touched. Close the loop
from "information arrives in messy form" to "event/errand exists, correctly
routed," with parent approval. Intake feeding the solver is the moat
(Skylight Sidekick does email→calendar now, but nobody decides who drives).

Shared infrastructure for all phases: a **proposal queue** — extracted
candidates (events AND errands/todos, e.g. "send $12 by Friday") land as
proposals; parent one-tap approves/edits/ignores; approval writes to the
correct kid's Google calendar via the existing create-event path. Follows
the established parent-verification pattern from chores/rewards. Must be
genuinely one-tap or it's data entry with extra steps.

- **Phase 1 — ICS feed subscriptions. SHIPPED v2.21.0 (2026-08-01).**
  `services/ics_sync.py` + hourly loop; feeds are managed inline on the
  Driver/Passenger edit forms (paste URL → Subscribe; target calendar
  implicit when the person has one). Updates patch, cancellations delete
  future events only, past events are frozen history. Details in
  system_capabilities.md.
- **Phase 2 — email ingest. V1 SHIPPED v2.23.0 (2026-08-01).** Dedicated
  Gmail polled over IMAP+app password (Gmail API service accounts are
  Workspace-only — the Calendar credential pattern does NOT carry over),
  every mailbox message analyzed (v2.23.1: the mailbox IS the filter —
  the family curates via Gmail filters/forwards; the planned allowlist
  gate was cut as redundant and forward-hostile, sender patterns survive
  as optional calendar-routing defaults, with the LLM's member guess as
  fallback router) → LLM extraction (events + 📌 tasks) → proposal queue
  on `/intake` with parent approval, per-message accountability log,
  parent push nudges. Still open from the original design: (a) learned
  per-sender/topic priors from approve/ignore signals;
  (b) editing a proposal's time/title before approving (today: ignore +
  manual entry); (c) drive-errand creation from proposals (tasks become
  all-day 📌 events instead — errands need location+duration); (d) a
  scheduled weekly digest push (the log page exists, nothing pushes it).
- **Phase 3 — vision capture (paper + screenshots).** PWA share-target:
  snap the backpack flyer / screenshot the group text (iOS will never
  expose SMS — share is the permanent ceiling there). Needs a competent
  multimodal cloud model — Gemma won't cut it for flyers; family-scale
  volume is dozens of calls/week, pennies. Recurrence with exceptions
  (spring break, early dismissal) is where extraction embarrasses — v1
  handles single + simple-weekly events only.

## The kid support arc (decided 2026-08-03 — the next big thing)

Priority straight from the family: **help the kids manage stress and be
successful.** Chauffeur models a kid's life as rides + chores; the school
day is invisible. Full design brief: `docs/kid_support_design.md` (phases,
principles — reassurance over reminders, agency not surveillance, kids as
sensors). Phase order: K1 kid evening digest → K2 pickup-clarity pushes →
K3 kid-as-sensor proposals → K4 school model + homework/deadline domain →
K5 school-rhythm prep + morning launch. Prerequisite shipped 2026-08-03
(v2.32.0): proactive parent watchers (`services/watchers.py`).

Open questions ANSWERED 2026-08-05: (1) build K4's school-feed intake
regardless of this district's support — others will have it; (2) no
per-kid phone config — dual delivery ALWAYS (Argyle DM to every child +
kiosk strip), phone kids get both; (3) kid quiet hours are config-page
settings, not hardcoded.

- **K1 — kid evening digest. SHIPPED v2.33.0 (2026-08-05).** Argyle DM per
  child + 🌙 kiosk strip on `/routines?kiosk=true`, kid quiet-hours
  settings (`kid_quiet_start/end`, shared gate for all future kid pushes).
  Details in system_capabilities.md.
- **K2 — pickup-clarity pushes. SHIPPED v2.33.1 (2026-08-05).** On-the-way
  push on first leg start (both PWA + agent paths, once per event/day) and
  near-term gains-only driver-change pushes riding the netted flush buffer;
  kid quiet hours skip. Details in system_capabilities.md.
- **K3 — kid-as-sensor. NEXT.** Kid tells Argyle "practice moved to 5" in
  their DM → the agent creates an action-proposal card for parents (the
  propose_family_action rail; children's approval taps already refused
  server-side). Needs: the proposal tool offered in kid/child agent
  context (today it rides the admin bridge gate), kid-persona prompt
  guidance (always propose, never execute, never interrogate).
- **Deferred from K2** (needs K4's school-hours model): the scheduled
  end-of-school-day "you're getting picked up by X at 3:15" push.

## The native app track (Capacitor wrapper — the big unlock)

Wrap the existing PWA (NOT a rewrite; days not months) and distribute via
TestFlight/Android sideload. Unlocks, in value order:

1. **Lock-screen / background audio** — the Sendspin phone player currently
   stops when iOS locks the screen; the wrapper makes phones real speakers.
   The sendspin-js client code carries over unchanged.
2. **Reliable push** (APNs/FCM instead of iOS web push quirks).
3. **Background location** — family members without the HA companion app,
   and the ONLY route to live location for role=helper drivers (no HA person
   entity; My Day intentionally hides "Where?" for helpers today).
4. **Eventually: live calls** (WebRTC + CallKit/ConnectionService). Until
   then the deliberate answer to "intercom" is voice memos, not calls.

Frictions to plan for: iOS builds need a Mac — **available: a MacBook Pro
(broken screen, works on an external monitor) and a MacBook Air in the
house (noted 2026-08-01), so no cloud CI required** · $99/yr Apple
Developer account · TestFlight builds expire after 90 days (recurring
release cadence) · Apple scrutinizes always-on location permissions.

**Distribution plan (decided 2026-08-01): TestFlight is the workshop, the
App Store is the destination.**
- Phase A — develop on **TestFlight internal testing**: no review at all,
  instant builds; family joins the developer team as internal testers.
- Phase B — once stable, submit as an **App Store release, likely via
  Apple's unlisted-app distribution** (fully reviewed, never expires,
  reachable only by direct link — not searchable; request it from Apple).
  Kills the 90-day expiry treadmill permanently. Public listing is also
  fine — the app is a config-screen shell without a server URL (same shape
  as the HA companion / Plex / Nextcloud apps); strangers downloading it
  get nothing.
- Review hurdles to budget for (one-time, all solvable): Guideline 4.2
  "minimum functionality" (Capacitor passes when the app feels native —
  push/audio/navigation are the point of wrapping); reviewers must be able
  to exercise the app → build a **bundled demo mode with fixture data**
  (the no-hosting alternative to a demo server + credentials); background
  location needs honest purpose strings + a privacy policy URL and is the
  likeliest source of review back-and-forth.
- Server-side prerequisite regardless of distribution: real APNs/FCM push
  (replacing web push for the wrapper) — its own task, second-biggest
  value item after lock-screen audio.

## Nice-to-haves / polish

- Chore fairness nudges via the solver (rotation suggestions for chronically
  unclaimed chores, "Lily did 80% of dishes this month"). The marketplace
  stays primary — this decorates it. (The week-old-unclaimed nudge shipped
  in the v2.32.0 watchers; rotation/percentage analysis still open.)
- Routine reminders (opt-in per item, at `time_of_day`) — deliberately NOT
  default; avoid becoming a nag machine.
- Badge/achievement engine beyond computed streaks — only if the kids ask.
- "Restrict music to own player" per-member kid flag.
- Dashboard-native chat panel (desktop parents currently use the PWA view).
- My Day true drag-swipe (pre-rendered snap-scroll panes like the driver
  timeline; current gesture+transition may be sufficient).
- MA player auto-expose on Sendspin registration (rejected once: MA's config
  API keys are version-fragile for a one-time toggle; revisit if MA grows a
  stable API). Current one-time step per member+device: MA → Settings →
  Players → enable "Expose this player to Home Assistant".
- Harden the open-admin dashboard/config surface (it has always been open;
  PINs currently protect identity switching + point payouts only).

## Cleanups

- Drop TinyDB code path + `CHAUFFEUR_STORAGE` toggle; audit the ~91
  `db_lock` sites (sqlite_migration_design.md §8).
- Repo root is littered with one-off `patch_*.py`/`test_*.py` scratch files
  and `services/trip_planner_hacked*.py` snapshots — delete when brave.

## Explicitly cut (with reasons — don't relitigate casually)

- **Movies/video**: Jellyfin/Plex territory; licensing swamp; bridge-not-build
  if ever.
- **Meals**: no synergy with the solver/logistics DNA; at most a calendar
  concern.
- **Money/allowance mapping for points**: rewards are parent-defined items;
  "$5" can be a reward item, but no currency integration.
- **Solver-assigned chores**: choice drives kid buy-in; the pot won.
- **Points for routines**: personal duties aren't paid work; streaks instead.

## Open design questions

- Parent-voice chore verification via the agent: what stands in for the PIN?
- Should helpers see event threads for events they drive (currently: no,
  DMs with parents only + kid contact relays through the family channel)?
- Multi-family/household support if this ever leaves the house: everything
  assumes one family per install.

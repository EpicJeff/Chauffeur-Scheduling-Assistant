# Chauffeur Family-Hub Roadmap

Status of the family-network pivot and the backlog for future phases.
Shipped-feature details live in `system_capabilities.md` (the live spec) —
this file tracks what is NOT built yet, with enough context to pick any item
up cold. Last updated: 2026-08-05 (v2.76.0 — meals arc M1–M5;
the old "meals" cut reversed).

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
  parent push nudges. **The four open items all SHIPPED 2026-08-03
  (v2.38.0/v2.38.1), two deliberately reshaped**: (b) edit-before-approve
  (title/date/times inline on both approval surfaces, `all_day` override);
  (c) '🚗 Drive errand' approval target (location+duration fields,
  `window_days` from the due date, ErrandRules apply); (a) learned priors
  built DETERMINISTIC — approval remembers sender→target as a prefill tier
  behind explicit sender defaults, 3+ consecutive ignores shows a hint
  (no LLM, no auto-suppression); (d) the weekly push was CUT as a
  redundant channel (watchers already nudge stale items) — the weekly
  family digest gained a 📬 Intake section instead.
- **Phase 3 — vision capture. V1 SHIPPED v2.39.0 (2026-08-03) — THE
  INTAKE ARC AS DESIGNED IS COMPLETE.** Photos/screenshots → the same
  proposal pipeline via a new 'vision' model tier (flash→lite; gemma is
  text-only). Surfaces: 📸 buttons on /intake + the PWA parent strip
  (always visible on Family view now), and an Android share-target
  (`/share`; iOS never supported PWA share targets — in-app buttons are
  the iOS path; SMS stays unreachable there, share/screenshot is the
  permanent ceiling). Still true from the original design: recurrence
  with exceptions (spring break, early dismissal) is where extraction
  embarrasses — v1 handles single + simple-weekly items only. Open
  nice-to-haves: multi-image share, an optional caption field on the
  in-app buttons, HEIC support if a phone ever uploads one.

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
- **K3 — kid-as-sensor. SHIPPED v2.33.2 (2026-08-05).** Kid DM proposal
  cards mirror into the family channel (re-bound so the outcome lands with
  parents); kid-persona prompt (propose + reassure, one question max,
  never lecture). The tool was never admin-gated — approval was always
  the gate; visibility was the real gap. Details in system_capabilities.md.
- **K4a — kid task domain. SHIPPED v2.34.0 (2026-08-05).** KidTask storage
  + REST, My Day "📚 Due Soon" checkbox card, digest/kiosk task lines,
  agent tools in both stacks with kid-owns-their-list scoping. Full K4
  design: `docs/k4_school_design.md` (scope guards: due dates never
  grades; no points/streaks; gentle overdue, never pushed).
- **K4b — intake fills the domain. SHIPPED v2.34.1 (2026-08-05).**
  Task-mode ICS feeds (never calendar/solver load; done tasks final),
  intake To-do proposals approvable onto a kid's list ("tasks:{member}"
  target). Google Classroom deliberately deferred: needs per-kid OAuth,
  and feeds cover this family — revisit on a feed-less school.
- **K4c + K5 — school hours, dismissal push, morning launch. SHIPPED
  v2.35.0 (2026-08-05). THE ARC AS DESIGNED (K1–K5) IS COMPLETE.**
  School-hours fields on members (Config → People, child roles); dismissal
  push names the next ride's driver, silent when nothing is known; morning
  "🚀 Leave by" line (start − travel − buffer from the solver's initial
  edges) on My Day, the kid digest, and kiosk cards.

Post-arc backlog (nice-to-haves surfaced during the build, none urgent):
Google Classroom OAuth sync (only if a feed-less school appears) ·
parent-visible school-task admin list on a dashboard page (agent covers
it today) · milestone templates ("science fair" → standard breakdown) ·
per-kid digest time overrides.
- ~~Deferred from K2: the scheduled end-of-school-day pickup push~~ —
  stale item: this SHIPPED in v2.35.0 as K4c's dismissal push.

## The bus arc (school-bus mornings, decided 2026-08-03)

Bus kids are the majority case the kid arc skipped — the launch/dismissal
machinery was car-centric. The family's district uses Here Comes The Bus,
already flowing into HA via the pcartwright81 HCTB integration (per-student
sensors named by first name). Principle: Chauffeur is the TRANSLATION layer
(deadline where the kids look, calm framing), never a bus tracker; the bus
never enters the solver.

- **B1 — bus model + surfaces. SHIPPED v2.40.0 (2026-08-03).** Per-kid bus
  fields (AM stop = opt-in, PM drop, walk mins, entity-prefix override with
  first-name auto-discovery), bus launch line on My Day/digest/kiosk (live
  HCTB stop estimate when the bus is out today, else static; yields to any
  morning car ride), "🚌 Bus home today" dismissal-push branch. Lateness ≥4
  min only, worded as "no rush". Tests: tests/test_bus.py.
- **School-calendar awareness + generic bus entities. SHIPPED v2.41.0
  (2026-08-03).** `services/school.py` `school_in_session(day)` (weekends /
  year-bounds settings / designated no-school calendar with keyword-matched
  all-day events; cached, fails open) now gates the dismissal push AND the
  bus launch — retroactively fixing K4c's fire-on-holidays gap. Per-kid
  explicit ETA/active entity fields make the live bus layer work with ANY
  district tracker that has an HA integration (HCTB auto-discovery stays
  the zero-config default).
- **B2 — the live morning layer (next).** (1) Kiosk live chip during the AM
  run window: the routines-kiosk digest strip polls a light bus-status
  endpoint (~60s while 6-9am) showing "🚌 on the way · stop ~7:24 ·
  {address}". (2) Opt-in "get ready" push at leave-by − N (setting, default
  ~10 min lead, once per kid per day, quiet-hours gated). (3) "Running
  late — no rush" push when the live estimate exceeds the baseline
  (threshold shared with B1), once per day. All pushes ride
  `_notify_member_lanes` + the `school_end_push_sent`-style marker pattern.
- Explicitly out: a direct reverse-engineered HCTB client in Chauffeur
  (fragile, credentialed — the HA integration boundary keeps that risk
  outside the app); bus in the solver; countdown spam.

## The meals & provisioning arc (decided 2026-08-05)

Feeding a family is one of the largest recurring mental loads in a household,
and the app's previous answer was to declare it out of scope — on a reason
that the codebase disproves (see the reversed cut below). Full design brief:
`docs/meal_design.md`.

The insight: **the load is in the constraints, not the recipes.** At 4pm the
blocker is not a shortage of recipes, it is that practice ends at 7:15, a
parent is on pickup until 6:40, and two kids eat in the car at 5:10 while the
rest eat at home at 7:30 — so the question is what can be made in pieces
before 3:40, packed in three containers, and eaten with a fork in a moving
car. Chauffeur is the only app in the house that knows that. Own the
constraint layer, bridge the content (Mealie/Tandoor/Grocy do recipes well).
Nightly derivation, never a stored weekly plan — a Sunday plan is a static
artifact fighting a schedule that mutates by Tuesday, which is the same
reason this app re-solves rather than schedules once.

Corrected 2026-08-05 by how the family actually eats: meals are prepped in
pieces across the day and eaten **in the car between activities**, and an
entry may be ordered, part-ordered, or all prep. Two consequences — the
standalone "bail-out" phase dissolved (ordered food is ordinary, not an
emergency), and in-car dining rules are **per-family settings, not
constants** (this family eats full meals with utensils in the car; others
won't eat in the car at all).

- **M1 — the shopping list (provisioning). SHIPPED v2.70.0 (2026-08-05).**
  Details in system_capabilities.md. Built as designed; the only reshape was
  photo capture returning STAGED candidates for a one-tap picker rather than
  auto-adding (a shelf photo yields a dozen guesses — this is a picker, not
  an approval gate, so adds stay ungated). Open questions from the brief that
  the build answered: the list DOES get a kiosk surface (read-only, 60s
  refresh), and multi-store shipped in v1 UI, not schema-only. Original
  design text follows. Standing `ShoppingList` /
  `ShoppingItem` entities bound to the recurring grocery errand by tag (NOT
  by errand id — the list outlives any errand instance). Voice/text capture
  in both agent stacks first (~80% of the value); photo capture aimed at
  fridge/pantry/handwritten shots, not held items. First shared mutable
  document in the app: per-item PATCHes, no whole-list PUT, SSE deltas.
  Zero-cost adds land directly with attribution — no proposal gate, kids
  included. Barcode deliberately deferred to the native wrapper (Open Food
  Facts solves the lookup for free; `BarcodeDetector` exists in no iOS
  browser, so today it means a WASM decoder — Capacitor gets ML Kit free).
- **M2 — the day's eating plan (the moat). SHIPPED v2.71.0 (2026-08-05).**
  Details in system_capabilities.md. Two corrections the build forced: a long
  gap between two places is a trip HOME, not time in the car (calling it
  in-car tells a family to pack food they could cook), and sittings must group
  by PLACE before time — clipping to the meal window makes start times
  useless as a discriminator. The cook window is computed from raw un-clipped
  spans, since prep happens before people eat. Original design text follows.
  Read-only derivation over solver
  output: per-person **eating slots** with a modality (`at_home` / `in_car` /
  `at_venue`), spans not timestamps. Passengers can eat during a leg, the
  driver cannot — which is the structural reason the driving parent doesn't
  eat, and "no feasible slot for anyone" is a first-class finding (and the
  honest trigger for route food, replacing any clock heuristic). Packed meals
  are **computed** items on the existing `prep_kits.py` surfaces with counts
  read off the solver's manifest — reuse the surface, not the rule engine.
  `prep_ahead_mins` becomes schedulable into any earlier gap; `needs_ahead`
  (thaw) creates a morning touchpoint on K5's launch line. Ordered/hybrid
  meals route via C3's min-detour machinery, and **delivery is a presence
  constraint the solver can check** ("nobody is home 6:00–6:40").
- **M5 — plates composed from typed dishes. SHIPPED v2.76.0 (2026-08-05).**
  From the family: they don't eat 15-20 different meals, they eat combinations
  of ~25 dishes, so storing combinations was the wrong shape. Dishes carry a
  type (meal/entree/side/dessert); a plate is composed by rule (entree + N
  sides + dessert) and then edited for the evening. Retires `Meal.slots`.
  Details in system_capabilities.md.
- **M4 — dishes as the unit of work. SHIPPED v2.75.0 (2026-08-05).** From the
  family: a meal should break into DISHES (one per option), and a suggestion
  pulls one dish from each pool. Dishes carry their own times, are reused
  across meals, and make per-dish leftovers exact rather than proportional.
  Vague dishes ("potatoes") are guessed, flagged with one question, and
  refinable — never a gate at entry. Details in system_capabilities.md.
- **M3 — the repertoire. SHIPPED v2.72.0 (2026-08-05). THE ARC AS DESIGNED
  (M1–M3) IS COMPLETE.** Details in system_capabilities.md. Built as designed;
  the reshape was that `meals_that_fit` returns BLOCKED entries with their
  reason alongside the fits, so nothing vanishes without explanation, and an
  empty repertoire and a repertoire where nothing fits are different answers.
  Original design text follows. Fit, not method: four timing numbers
  (`prep_ahead`/`finish`/`unattended`/`needs_ahead`) instead of one cook time,
  plus `holds_well`, `portability`, and a `source` axis (prep/ordered/hybrid
  with vendor + `order_lead_mins` + pickup/delivery). Ingredients classed
  staple-vs-fresh — inventory's value with no inventory to maintain. Human
  supplies the name, the LLM fills the metadata, or it never reaches 15
  entries. ~15–25 entries, surfaced as a filter result not a browsable page,
  no steps ever. Mealie import is the later on-ramp. Dietary constraints on
  FamilyMember, mirroring the solver's grammar: allergies hard, prefs soft.

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
- ~~**Meals**: no synergy with the solver/logistics DNA; at most a calendar
  concern.~~ **REVERSED 2026-08-05 — the stated reason was false.**
  `trip_scheduler.py` (MEAL_BLOCKS/MEAL_ANCHOR) and `cars.py` C3
  (propose-a-stop-on-your-route) are both shipped proof of synergy. What is
  actually cut is narrower — **pantry inventory, recipe-site ingestion, and
  multi-week meal plans** — and now lives with real reasons in
  `docs/meal_design.md`. See the meals & provisioning arc above.
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

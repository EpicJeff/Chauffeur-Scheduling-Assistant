# Chauffeur Family-Hub Roadmap

Status of the family-network pivot and the backlog for future phases.
Shipped-feature details live in `system_capabilities.md` (the live spec) —
this file tracks what is NOT built yet, with enough context to pick any item
up cold. Last updated: 2026-08-15 (v2.245.0 — the music arc SHIPPED, closing
the queued slice; covered rides reached the wall and grew a "be ready at",
finishing the visible half of load-arc A1).

**Verification status (2026-08-15): everything shipped through v2.245.0 has
been exercised on device or on the live add-on instance.** Every arc in this
file previously carried an "on-device verification pending" note — presence,
kid support, cars, meals, bus, occasions, load, wall panel, boards, boards
editor, announce, optional events, music — and they are all cleared. New
work starts from a verified baseline, so a pending note from here on means
that arc specifically, not the backlog of everything before it.

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
  **Now a two-layer problem, not one** (2026-08-15): the music arc added a
  SECOND axis — HA reachable but no MA token — and solved its own case with
  the hide-don't-error rule. Music is also a real destination now, not just a
  tab. Whatever ships here should adopt that rule rather than invent a third
  degraded style; `/music` is the worked example.
- **Kiosk points leaderboard — ALREADY SHIPPED, stale item (noticed
  2026-08-01).** `/chores?kiosk=true` has been exactly this since v2.20.0
  (leaderboard-only collapse, 60s refresh; `/routines?kiosk=true` = streak
  board). Only unbuilt remnant, if ever wanted: a compact points strip ON
  the main schedule dashboard's kiosk view, so one panel shows both.
- ~~**Per-member notification preferences.**~~ **FULLY SHIPPED in load-arc A6
  (v2.151.0) — stale item, verified 2026-08-15.** Both halves are done:
  `FamilyMember.notify_lanes` (`all|push|ha`, editable on the member card in
  Config → People) settles the double-delivery this item was written about,
  and member quiet hours put the timing preference on the identity. Nothing
  survives; the item is closed rather than reduced.
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
- **B2 — the live morning layer. SHIPPED v2.235.0 (2026-08-14).** All three
  pieces, with two deliberate reshapes. (1) The live chip needed **no new
  endpoint and no new poll**: the design predates the boards arc, and the
  board already refetches every 60 seconds — so the chip rides the kid-digest
  line the kids card already draws, and REPLACES the plan line while the bus
  is rolling rather than joining it ("out the door by 7:19" is last night's
  sentence; "on the way · stop ~7:24 · Elm & 3rd" is this minute's, and two
  lines about one bus is a wall arguing with itself). (2) The settings are
  **per member, not household** — every other bus field already lives on the
  member card, and a fifteen-year-old does not want the nudge a seven-year-old
  needs. The lead IS the opt-in (blank/0 = off); a switch beside a number is
  two ways to say the same thing. (3) Lateness is its own switch, because news
  and routine are different kinds of message. Details in
  system_capabilities.md.
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

## The occasions arc (SHIPPED 2026-08-07, v2.90.0 → v2.96.0)

Holidays, birthdays and parties. The load is in **planning** — what to feed
sixteen, what a shark party needs, what must be bought by when, and who is
doing all of it — not in storage or visibility, which is why the container was
rejected as the feature. Full brief: `docs/occasion_design.md`; shipped detail
in `system_capabilities.md`.

Named **Occasion**, not Holiday: "holiday" excludes birthdays/graduations and
collides with Trip in British English.

Four teardown conclusions, still not to relitigate: (1) the container is not
the system of record; (2) a derived view is still fine, because derivation is
not ownership; (3) Trips earns container-hood because its contents exist
nowhere else, while an occasion only borrows; (4) membership attaches to the
coarsest wholly-owned entity, with one documented exception on `ShoppingItem`
for the standing grocery list.

- **O0 — cooking for a crowd. SHIPPED v2.90.0–v2.93.0**, deliberately with no
  occasion object: the expensive engineering first, as the test of whether the
  rest earned itself. `Dish.scope` (holiday food out of the Tuesday pool, with
  leftovers bypassing the filter), `services/kitchen.py` replacing the
  hardcoded cook=1 / oven=∞ (reduction to the old sum/max is an asserted
  contract), serving scale, and the CP-SAT run sheet.
- **O1b — the occasion MENU. SHIPPED v2.101.0**, closing a real hole in the
  brief rather than a deferred nice-to-have. The brief sent menu selection to
  `set_plate_lock` "one plate at a time", which was right about the mechanism
  and wrong about the reach: by hand a plate is only editable through the week
  strip, so a menu three weeks out was voice-only. Now each occasion has a
  menu that IS the locked plate on its meal date, a picker that excludes other
  occasions' food, an add-dishes box whose dishes are born occasion-only, and
  the kitchen cost + oven clashes reported beside the choice.
- **O1 — the occasion as context. SHIPPED v2.94.0.** `Occasion` +
  `OccasionGuest`, `/occasions`, full REST, four tools in both stacks, themed
  list generation onto the shipped cart rails, guest diets binding like family
  allergies. Deleting the context clears links and keeps every errand and list.
- **O2 — the interview and the gap report. SHIPPED v2.95.0.** Templates as
  static data whose answers *generate* logistics; the report a DIFF against
  template and last year, sorted by slack with no percentage anywhere;
  unanswered is not no; a watcher anticipating inside three weeks.
- **O3 — the planning intelligence. SHIPPED v2.96.0.** Load distribution,
  open decisions carrying what waiting costs, schedule-aware timing, deadlines
  derived from the food, calendar clashes. This was the part flagged
  do-not-cut, and it was not cut.

Post-arc backlog: **outcome capture** ("three pies last year, one came back
untouched" → suggest two) — highest compounding value, needs a recording
surface nothing has yet · rentals and borrowing (still no API, still needs a
social graph) · local dated-event discovery (still no data source) ·
**gift secrecy**, which remains the blocker on ever modelling presents: the app
has no visibility scoping and lists render on kitchen kiosks, so `hidden_from`
must be designed first, enforced at storage and on every surface, or gifts stay
out.

## Config decentralisation (STARTED 2026-08-07, v2.97.0 — continue this)

Measured when the O0 kitchen block went in: **`templates/config.html` was 5,631
lines and `Settings` carries 83 fields**, all saved through one whole-object
POST. Every arc added to it and none ever took anything out.

The observation that shaped the fix: **the app had been decentralising settings
for a year without calling it that.** ICS feeds live on the driver form.
Pairings live on the dish row. Meal rules live in the "How we eat" panel. Bus
fields live on the member card. Every one went where the family was already
looking, and every one works. config.html is the residue.

**Shipped as the foundation (v2.97.0):**
- `services/settings_registry.py` — all 83 keys declared with label, searchable
  help, group, and the page + anchor that OWNS each one. `audit()` fails on any
  drift and a test calls it, because an index that quietly falls behind the
  model is worse than none: it would claim to be complete while hiding whatever
  was added last.
- **`/settings` — "Find a setting"**, a searchable index over the registry.
  This is the thing decentralisation otherwise destroys: somewhere to look when
  you half-remember a setting but not which page owns it. Secrets show as
  set/not-set and never as values.
- **`audit_ui()` — the nothing-gets-lost guarantee**, enforced by a test. It
  checks every registry claim against the owning template (following
  `{% include %}`). It found **ten settings with no hand path at all**, none of
  them caused by the migration: days-to-solve, sides-per-plate, dessert, the
  three prep-reminder keys and the four Walmart keys. All ten have one now.
- **The whole meals group moved to Shopping & Meals** (v2.98.0) under
  "⚙️ How this works" — dining, plate shape, planning, prep reminders, Walmart,
  kitchen. It POSTs only its own keys: `/api/settings` has always merged with
  `exclude_unset`, so a feature-owned surface needs no new endpoint, only the
  discipline of sending what it owns. config.html keeps pointers, because a
  setting that silently vanishes from where somebody last saw it is worse than
  one in the wrong place. config.html: 5,631 → 5,501 lines.

**What remains — move a group at a time, registry entry first:**
- Kids & school (9) → the member card / kid surfaces.
- Cars (4) → the car entity pages.
- Digests (7) → wherever a digest is configured.
- Daily/household/integrations/AI/maps are the natural residue and can
  legitimately stay on config as plumbing — the index makes them findable
  regardless. Intake (5) already lives on `/intake`; solver tiers (2) already
  live on Chores and Routines.

Rule going forward: **a new setting is registered in the registry and placed on
its feature's surface, never appended to config.html.**

## The load arc (SHIPPED 2026-08-10, v2.146.0 → v2.151.0 — designed and built the same day)

Full brief: `docs/household_load_design.md`. Six arcs, four new primitives,
one derived lens. Built from a code audit, not from these docs. ALL SIX ARCS
SHIPPED: A1 outside hands (v2.146.0) · A2 household tasks + assist tier
(v2.147.0) · A3 requests (v2.148.0) · A4 stages, cutoffs 6/12/15 configurable
(v2.149.0) · A5 dual-income net (v2.150.0) · A6 outlets + member quiet hours
+ household briefing (v2.151.0).
Deferred from the design, with reasons in system_capabilities.md: the carpool
turn ledger (A1 slice 2) and chore/task coverage by outside hands (wants usage
data first); driver availability windows/radius from "Three layers of no"
(the commitment + quiet-hours machinery covers the sharpest cases; per-weekday
work windows are the next slice).

The finding: **the app models the family's work as driving, and anything not
drive-shaped has no home** (`Errand` requires `location`+`duration_mins`
because an errand IS a drive) — and **the child's work is fully modelled while
the adult's work is not modelled at all** (`assigned_to`/`assignee`/
`owner_member`: zero hits repo-wide). That is backwards, because the mental
load is the adults'. A third: an adult's own life exists in this app only as
an OBSTACLE — a personal calendar event's whole function is to make you
unavailable to drive.

Primitives: `HouseholdTask` (work with a deadline and no destination) ·
`Request` (an ask with a state, kid→parent and adult→adult on the same rails) ·
`AssistContact` (someone outside the house who does work for it — NOT a
`helper`, who is external but HOLDS the app) · `Stage` (the developmental band
a child is in) · the **load ledger** (a lens that states and never scores).

**Covering is not carrying** (decided 2026-08-10). A teen who drives is more
like a carpool parent than a second adult — assigned a drive and it is covered;
the difference is only that they hold the app. Carpool drivers, `helper`s and
Copilot teens all carry an `assist` tier. **The tier does exactly one job: load
accounting** — excluded from the ledger and from the balancing term, while
coverage still counts (no needs-a-driver flag, no ghost, no watcher alarm).
Fixes a latent bug: the weekly digest's per-driver counts currently let a
nanny's ten runs make the week look shared. Teen keeps `role='child'` and the
whole kid lens; the Copilot stage unlocks the driver surfaces.

**The tier is MEMBER-level, not on `Driver`** (corrected 2026-08-10 — this one
matters). *Assisting is not driving-specific*: a teenager can cook a night, a
nanny can supervise homework, a grandparent might cook and never drive. Hanging
it on the driver record would re-commit the exact sin this brief is about, and
would leak immediately — a teen who cooks three nights would make the parents'
split look even, because only their drives carried the tier.

**Three layers of "no"** (corrected 2026-08-10 — an earlier draft collapsed
these into a thin driver record and wrongly framed them as teen constraints):

1. **Commitments — where you already are.** School, job, standing obligations.
   Facts, not preferences; they block everything, not just driving. Half exists
   already (`FamilyMember.school_hours_start/end`, never fed to the solver
   because no child was a driver). Keep them TYPED rather than generic windows:
   they suspend (A5 already computes closures and half days, and a closure
   can't reach a generic window), other features already read them (dismissal
   push, bus, aftercare), and they're somebody else's schedule.
2. **Availability — when you'll take work.** Universal: not assist-specific,
   not driving-specific. Several windows, each with days, times and a
   **strength** — preference (soft, tradeable) vs limit (hard, never crossed),
   which is the real axis rather than age. `unavailable = outside every window
   ∪ inside any commitment`. **Opt-in is ONE switch and the windows are its
   scope** — "yes to the 4pm practice run" IS a window, so per-window consent
   needs no extra mechanism; the "what kind of work" dimension already lives in
   routing `Rule`s, `Chore.eligible_member_ids`, and direct task assignment.
3. **Driving constraints — what a drive may look like.** The only genuinely
   drive-specific residue, on the driver profile: radius in **drive minutes**
   (settled — the travel cache speaks in them and traffic is what people
   refuse), passenger cap, and **after dark anchored to sunset** not a clock
   (how both a nervous driver and most graduated licences think; `sun.sun` is
   already read for the panel theme).

**Commitments + per-weekday windows + radius is most of a work model** —
"Tuesday I'm in the office 45 minutes away, Wednesday I'm home" — closing the
no-work-model finding without an employment entity, and sharpening A5's
childcare-gap detection, where "every adult unavailable" currently has to guess
from calendar holds. Teen-specific reduces to the DEFAULTS and WHO HOLDS THE
PEN. Rebuild fix: the current window check tests the EVENT, not the drive, so a
9:00 event with an 8:30 leave-by doesn't violate a 9:00 window.

Seven things, one job each — and **six of the seven are member-level**, which
is the point: **entity** (member or contact) · **role** (what of the app you
reach) · **stage** (which kid surfaces) · **tier** (does your contribution count
as household load) · **commitments** (where you already are) · **availability**
(when you'll take work of any kind) · **driving constraints** (what a drive may
look like — the only one that should be about driving).

- **A1 — outside hands. SHIP FIRST.** Was "the carpool book"; generalised
  2026-08-10 once the tier moved to the member. **Carpool is a kind of HELP,
  not a kind of person** — the neighbourhood girl who does the dishes has no
  place in the app either, and her work is recorded nowhere, which is this
  brief's own thesis pointed at its first draft. So `AssistContact`
  `{name, phone, relation_label, kinds[], relationship, notes}`. `kinds` is a
  free tag list (carpool, housework, childcare…) and **nothing branches on it**
  — behaviour comes from what REFERENCES the contact, or every new kind of help
  is a code change. `relationship` (`reciprocal|paid|volunteer`) exists so
  turn-taking fires for a carpool parent and stays silent for someone you pay;
  that is not a reversal of the money cut, since no amounts are tracked.
  Contacts are `assist` by definition; the tier is only a real choice for
  members. A contact who needs the app is promoted to a `helper` member and
  **their history survives**. Work is a third assignment state — covered, not
  assignable, not unassigned, not ghost-eligible — which kills a standing false
  alarm (`🚨 No driver yet` for rides that were always handled) and its
  off-road twin (a chore the neighbour is coming to do sitting unclaimed in the
  pot). **Slice the machinery, not the noun**: contact book + drive coverage
  first, then the turn ledger ("you've driven 2 of the last 9"), then chore and
  task coverage after A2.

  **A1's visible half finished 2026-08-15 (v2.244.0 → v2.245.0)**, from a
  question asked at the wall: does an event covered by outside help still show
  on the hero so everyone can get ready? It did not — coverage removes the
  event from the SOLVE (that IS the feature), but `todays_runs` read
  `sched['assignments']`, so a covered event was invisible to the hero and the
  drives tile. The kid digest had fixed this exact blindness in A1; the wall
  had carried it for a year. Now covered events build runs from
  `assist_assignments`, with the outside hand in the driver slot wearing the
  household word and a `🤝 covered` chip.
  Then the better correction, again from the family: v2.244.0 showed no time
  but the start, reasoning that we must never state a departure for a car we
  are not driving — but **the drive from OUR door is still computable, so the
  answer is a "be ready at", not silence.** What is not ours is the driving;
  the getting-ready never stopped being ours. `leave_by.ready_for_covered`
  keeps `ready_at`/`ready_label` strictly separate from `leave_at` so no
  surface can ever tell somebody to leave, inherits the silence rule verbatim
  (no cached travel, no location, no home, unroutable → no claim at all), and
  reads cache-only because a wall polls it every 60s — which is why the solve
  now primes covered events' locations even though coverage removed them from
  it. Buffer: `assist_ready_buffer_mins`, on the Outside hands panel rather
  than the config firehose.
  **Still open in A1**: the turn ledger, and chore/task coverage by outside
  hands (both still want usage data first).
- **A2 — household tasks + assignee. The keystone.** Task = do something,
  errand = go somewhere. Yearly recurrence (errands lack it). Unassigned is a
  real state meaning the household owes it. Unlocks intake's fourth target —
  the extraction prompt already names "permission slip due, payment due,
  picture day" and has nowhere to put them.
- **A3 — requests.** A kid can report but cannot ask; an adult can only TAKE a
  drive from their partner, who gets a bare "Schedule Updated" push. One
  object, always answered, accepting performs the change.
- **A4 — stages.** No birthdate/age/grade field exists today; `role=='child'`
  is the whole model, so a 6yo and a 16yo get identical everything and the only
  exit deletes the kid lens. Sprout/Explorer/Navigator/Copilot, suggested from
  birthdate, overridable per capability. Growing up is GRANTED, never silently
  switched; nothing is deleted on transition. Load awareness is the anti-stress
  feature. Explicitly out: mood/journaling/sentiment — health is a scheduling
  problem, not a content problem.
- **A5 — the dual-income safety net.** School days get kinds (half days are the
  sneaky ones), aftercare as a care window that widens the solver's deadline,
  and childcare-gap detection over a 21-day horizon — the app already knows
  school is closed and knows both calendars and never computes the
  intersection. Also fixes: `clear_deck`/`give_space` have no solver effect
  despite the design doc, and the status→solver injection is 14 days against a
  30-day build horizon.
- **A6 — outlets + the household briefing.** Protected commitments the solver
  defends, erosion watch ("you've missed your Thursday run three weeks running
  — every time it was a drive"), coverage that makes an outlet real, recovery
  beats, **quiet hours on the IDENTITY** (not household config: a kid's window
  is a protection set by someone else, an adult's is a preference owned by the
  self — and a night-shift parent, a 6am riser and a hired driver share no
  window; absent = the household default, never off; urgent lanes escape;
  merges with the stale "per-member notification preferences" backlog item),
  and **the briefing**: the tomorrow digest is per-driver today, so the
  non-driving parent learns the day changed by looking at a screen. Show
  OPENINGS, not assignments — the hard part of picking up slack is visibility,
  not willingness.

## The boards editor arc (SHIPPED 2026-08-14, v2.229.0 → v2.232.1)

Board editing was a form at the bottom of the board; it became an in-context
dashboard workflow — a reorderable boards list with **+ Add Board**, an editor
bar on the board itself, a ✎ on every tile, and settings as overlays over the
thing they configure. Four arcs, **B0 → B3**, each deleting its counterpart out
of `#panel-setup`; after B3 `#panel-setup` does not exist. Full brief:
`chauffeur/docs/boards_editor_design.md`.

The load-bearing decision, shipped: **built-in boards are read-only, authored
data** (`chauffeur/services/builtin_boards.json`), households may only hide
them from the shelf, and Duplicate is both the escape hatch and how we author
them — which deleted the silent-fork model where all ten were already forked
and tracked nothing we shipped.

**Remaining board work:**

- **The Occasions board should be a GALLERY, not the home card** (raised
  2026-08-14). The built-in board mounts the `occasions` tile — the home
  page's "Coming up" summary, `count: 10` — so the board that is *named*
  Occasions can only list them. It wants the two-level shape: pick an
  occasion, get its real view (menu, guests, gap report, derived deadlines).
  The mechanism already exists twice — `trips_gallery` and the moments
  gallery are mount points that draw with the PAGE's own renderer
  (`components/trip_gallery.html`, `components/moments_gallery.html`), so a
  card looks identical on a wall and in a browser. So the work is: extract
  `components/occasion_gallery.html` out of `templates/occasions.html` (684
  lines today), add an `occasions_gallery` tile type, point the built-in
  board at it, bump that board's `v`. **Follow the MOMENTS pattern, not the
  trips one** — trips ride the board payload, but occasion detail is two
  levels deep and would make every other card on the board wait on it, so
  the element is an instance-scoped mount (`board-occasions-<id>`) that
  fetches for itself.
- ~~**A Music board — panels should reach Music Assistant**~~ **SHIPPED
  v2.233.0 (2026-08-14).** All three panel decisions landed as designed:
  panel-distance drawing in the board's theme tokens, the room default
  reusing `announce_targets` through `announce.pick_music_player`, and three
  distinct degraded states. Two things the build corrected in the plan
  above: it is NOT a mount-point conversion of the widget — that component
  is a singleton with hardcoded element ids, fixed dark colours and a phone
  player, so the card is a separate drawing over shared logic
  (`static/music_logic.js`); and `/music` became a real destination whose
  page IS its board, the first of those. Detail in system_capabilities.md.
  **v2.234.0 fixed the one thing v1 got wrong**: the card shipped as a remote
  control that could reach every room except the one the panel is bolted to.
  The screen is now a Sendspin player like the phone app, over a shared
  lifecycle in `music_logic.js` — a phone is a person, a panel is a place.

## The music arc (SHIPPED 2026-08-14/15, v2.237.0 → v2.243.2)

The slice queued on 2026-08-14 as "four things, three of them nearly free"
grew into a real arc once the token question was settled. Detail in
`system_capabilities.md`; the shape of what changed:

**The load-bearing decision, shipped: Chauffeur talks to Music Assistant
directly** (`services/ma_api.py`, port 8095, one pasted long-lived token) —
the app's first direct-to-MA channel, taken rather than waiting weeks on a
dedicated HA action. The rule that made it safe to take: **the HA bridge
stays the zero-setup floor for everything that can exist on it, and every
MA-only verb HIDES rather than errors.** No token, no dead buttons.

That reversed the read-only-favourites cut in the plan above — hearts are
now real writes on both piles (a member's shelf, and the house's actual MA
favourites via `music/favorites/add_item`), including un-favourite, the verb
MA's own `favorite_now_playing` button never offered.

Slices as built: `ma_api` (v2.237.0) · search stops flattening MA's groups
(v2.238.0) · radio mode + the queue verbs + the switches (v2.239.0) ·
per-member shelves, never mixed with the house's (v2.240.0) · a visible
editable queue (v2.241.0) · MA shelves + playlist writes, because typing was
the worst part of a wall (v2.242.0) · the house heart (v2.243.0) · the heart
on the thing actually PLAYING, both surfaces (v2.243.1) · and the screen
player finding its own heart (v2.243.2).

Three of the four queued items are therefore done (queue, radio, and the
favourites half that was supposed to be impossible). **Two remain:**

- **Follow me — still unbuilt, and still the only one that is genuinely new
  for a WALL** rather than catching up with the phone. `transfer_queue`
  targets the DESTINATION and takes `source_player` + `auto_play`, so a
  panel's button is "move the music here" with nothing to pick: the card
  already knows its room, and it composes with the local player (bring the
  kitchen queue to this screen). Needs a new endpoint; today `transfer_queue`
  appears in the repo only inside an `ma_api.py` docstring.
- **Return-to-home still kills the music** (reported from the wall
  2026-08-14, unfixed as of v2.245.0). The panel's idle return navigates
  away, the page unloads, `pagehide` stops the local player, and the music
  stops for no reason a person in the room can see. `goHome()` in
  `templates/nav.html` already guards one case — an active screensaver sets
  `_chfSsPendingHome` and lets wake-up do the navigating — and playing audio
  wants the same shape: don't interrupt what somebody is doing. A bug in what
  v2.234.0 shipped, not a new feature, and the cheapest open item in this
  file.

Deliberately still out: writing to MA's favourites from the HA path (no such
action exists), and any second credential beyond the one token.

## The native app track (never written down until 2026-08-14 — it should have been)

Phase 2 of the family-network pivot always named a native app, and it fell out
of this file. Meanwhile four separate arcs deferred work *to* it by name, which
is the real argument: the wrapper is not a feature, it is the **capability
floor** that several shipped features are sitting just below.

What is actually blocked on it today, each already written down elsewhere:
- **Barcode capture** (M1 / `system_capabilities.md`): `BarcodeDetector` exists
  in no iOS browser, so on the web it means shipping a WASM decoder for the
  narrowest capture path; Capacitor gets native ML Kit free.
- **iOS share-target intake** (Phase 3): Android has `/share`; iOS has never
  supported PWA share targets, and in-app buttons were accepted as the
  permanent web ceiling. A native share extension is the only thing that
  removes it.
- **Voice memos** (still unbuilt): iOS PWA records fine *in the foreground*
  only — the walkie-talkie moment wants background capture.
- **Sendspin phone players**: a member's phone is a real MA player, which on
  the web dies with the tab and owns no lock-screen controls.

**Location and push are the STRONGEST part of the case, not the weak part**
(corrected 2026-08-14 — an earlier draft of this section claimed the HA
companion app already covers them, which is wrong and would have mis-sized the
whole track). Two reasons, and the second is architectural:

1. **Nobody will install two apps.** Getting one app onto a helper's or a
   grandparent's phone is already the hard part. "Also install Home Assistant
   so we can see where you are" is a non-starter, and every person the load
   arc just brought into the model — helpers, carpool parents, a teen — is
   exactly the person who won't.
2. **You would never hand a helper HA credentials anyway.** That is the real
   boundary: **Chauffeur is the app outside people are allowed to hold; HA is
   family-internal infrastructure.** The role/PIN model already says this
   (`helper` is "external but HOLDS the app"). Routing an outside person's
   location through the HA companion app inverts it, because it makes
   participating in the family's logistics require access to the house.

The shipped consequence, verified 2026-08-14 and worth recording on its own:
**there is no web location path at all** — `geolocation`/`watchPosition`
appear nowhere in the repo, so the family map is HA person entities or
nothing. Any member without the companion app is permanently invisible on it.
Push degrades the same way but less sharply: `_notify_member_lanes` is web
push + HA notify, so a helper has one lane, and on iOS that lane requires an
add-to-home-screen install and is the least reliable one we have.

So the case is capture **and** presence: share sheet, barcode, background
audio, background recording — plus background location and real push for the
people who will only ever install one app.

**The load-bearing constraint, decide it before any code**: the shell must stay
a thin Capacitor wrapper over the *served* pages, with native plugins as the
only additive layer. Today a release is one add-on rebuild. If app logic
migrates into the shell, every release grows a store review cycle, and the
whole "bump version, commit, rebuild" loop this project runs on stops working.
Keep the web layer the source of truth and only a plugin change needs a store
trip. Real costs to price in regardless: an Apple developer account, signing,
and the fact that the family's install is a LAN/HA add-on — a store build
pointed at a home server is its own configuration problem (first-run URL entry,
not a hardcoded host).

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

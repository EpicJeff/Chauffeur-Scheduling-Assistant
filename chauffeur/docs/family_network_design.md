# Family Network — Access Scope, and the Household Boundary

Status: **BUILDING — Phases 1–3 SHIPPED (S1–S6, v2.330.0–v2.335.0); Phase 4 underway: S7 v2.336.0. Next: S8–S11.** Written 2026-08-20 to settle a question before code.
Revised the same day after the first surface list was found too coarse (§5).
Companions: `docs/auth_design.md` (the tier spine this extends), `docs/kid_support_design.md`
(stages — the per-member override pattern this copies).

---

## 1. The question that started this

> *"There are different types of families. I have my family, my brother has his, and we
> are both part of my parents' family. I don't need the daily workings of his household,
> nor he mine. But his kids may want to chat with my kids, I may want to see moments from
> his kids' activities, we definitely want to battle each other's critters."*

Two candidate answers were on the table: (1) model extended family as a role that only gets
the social surfaces, or (2) a multi-family architecture where several households live in one
Chauffeur and share selected things.

**The answer is (1), and it is not a compromise — it is the whole problem.** (2) is rejected
on evidence, below. The social-federation ambition that motivated (2) is parked with an
explicit trigger, in §3.

The real defect is not that Chauffeur cannot hold two families. It is that **Chauffeur has
one blunt idea of who a person is, and real families are made of gradients.** A grandparent
two states away, a hired nanny, a teenager who half-drives, a co-parent, an aunt who only
wants the photos — today those are four roles with mostly cosmetic enforcement.

---

## 2. Why multi-tenancy is refused

Measured, not asserted (audit run 2026-08-20):

| Fact | Count |
|---|---|
| Tables in `services/storage.py` | 81 |
| ...that would need a `household_id` | 71 (67 domain + 4 solve caches) |
| Functions reading a table with no owner filter | 85 of 458 `def`s |
| `get_settings()` call sites app-wide | 219 |
| Roster call sites (`get_all_members/drivers/passengers`) | 132 across 20 files |

Those numbers are the cost, not the argument. Two things are the argument:

**a. The singletons are `truncate()`-then-`insert()`.** `update_settings`, `patch_settings`,
`set_cached_schedule`, `set_cached_trips` all wipe the table before writing. The day a second
household exists, they silently delete each other's rows. This is not a query to scope; it is
a data-loss bug waiting for a tenant.

**b. Home Assistant is process-global.** The connection is resolved from `SUPERVISOR_TOKEN`
against `http://supervisor/core/api` (`services/ha_api.py:29-31`). Every `ha_person_entity`,
`notify_service`, `media_player_entity`, wall panel and voice satellite points into
*whichever single HA instance the add-on is running inside*. **A household column in the
database does not give another family a second Home Assistant.**

`docs/roadmap.md` already recorded the assumption — *"everything assumes one family per
install"* — and that assumption is correct. **Keep it.** What changes is not the number of
families per install; it is that a household may now have **guests**.

---

## 3. The social layer, and why it is parked

The things wanted across households — chat, moments, critter battles — are precisely the
**append-only, small, HA-free** things. `pet_battle.combatant()` even says it out loud:
*"no member ids beyond a label, no storage handles… what makes the replay portable."*
Cross-house battles would be nearly free.

Parked anyway, on a judgement that should not have to be re-made:

- Extracted from the household context, the social layer is **a worse WhatsApp with a worse
  photo album and a worse game.** None of it justifies an install.
- Engagement is fatally asymmetric. We open Chauffeur daily because it runs our life; a peer
  household would open it to check for a critter challenge. That dies in weeks, and then a
  dead wing must be maintained forever.
- **Federation is a multiplier, never a reason to adopt.** It pays only when two installs are
  each independently worth running. Exactly one exists.

**Trigger to revisit:** *a second household is independently running Chauffeur for its own
logistics.* Not before. If that day comes, start with critter battles, and never let
federated content reach the agent — `@argyle` routes any message to the agent with tools and
can set `schedule_dirty`, so a peer could otherwise drive our solver.

**The one genuinely unique cross-family capability does not need federation at all.**
Chauffeur knows there was a game on Tuesday, prompted for a moment, and knows who was there —
so it can assemble "what the grandkids did this week" with *zero effort from the parents*.
But the unique part is the **curation, not the container**: send it as email or text. For
extended family, Chauffeur should push outward through channels they already have.

---

## 4. The evidence that the real defect is scope

Three attempts to express *"this person sees less"* exist, and all three stalled:

1. **`capability_overrides`** (`models/schemas.py:189`) — ten switches, applied by
   `services/stages.py:169-185`. But `stages.can()` returns `True` unconditionally for anyone
   whose role is not `child`. **Adults have no per-person model at all.**
2. **`assist_tier`** (`schemas.py:167`) — five references, not one an access decision.
3. **`helper`** — has *no tier* in `services/auth.py`. `SIGNED_IN = {MEMBER, PARENT}`
   (`auth.py:50`), every non-parent member resolves to `MEMBER` (`auth.py:468`), so every
   helper restriction is UI-only or a hand-written check in one handler.

Three swings at the same missing abstraction is a signal it is missing, not unwanted.

---

## 5. The unit is a facet, and the test is "name the person"

The first draft of this document listed nine surfaces — schedule, chores, meals, chat,
moments, whereabouts, trips, house, pets. **They were drawn along the app's tab lines, and
tabs are navigation, not decisions.** The household reviewed it and broke it in one pass:

> *"You have the schedule, but there is the driving schedule and there is the calendar. A
> distant adult might like to see what the kids are up to by looking at the calendar but they
> have no need to know who is driving them and when they need to leave. Chat is all messages,
> but there is the family chat, DMs, chats linked to events, driver↔passenger chats, the
> agent chat. Helpers need to chat about an event but shouldn't see any of the other kinds.
> Meals is really meals and lists — all of the lists. Some people might need the grocery
> list, but not lists in general."*

Every one of those objections came with a face. That is the criterion:

> **A facet exists when a real person in this household would want a different answer for it
> than for its neighbours.** Name them, or do not split. Conversely: if someone can be named,
> it does not matter that the app happens to serve both halves from one tab — or, worse, from
> one payload.

The nine survive as **groups** (how the editor is organised, §9). The unit of enforcement is
the **facet** below them. `reach` is unchanged: `none | own | all`, a set of named steps and
not a rank, the same rule `auth.py` holds for tiers.

### And a second question: *whose*

The household's next cut, and it made the model smaller rather than larger:

> *"They want to see the kids' calendar, not the adults'. So really what you want to be able to
> do is share calendar by person."*

Every facet above answers *what kind of thing*. None answers *about whom* — and for the very
first preset we designed, "about whom" is the whole point. A grandparent does not want "the
calendar"; she wants **Emma's and Jack's** calendar.

The tempting build was a subject filter per facet, with computed groups. It is not needed,
because **this is already the grain of the data**: events are attributed to people through
`calendar_ids`, and `_kid_members_for_event` (`main.py:10099`) and
`family_digest._kid_event_match` (`family_digest.py:28`) already resolve which person an event
belongs to — the same matching My Day uses. It is also the sharing model people already
understand from Google Calendar: you share a calendar *with* a person.

So scope gains **one list, not twenty-five**:

```
sees_people: []            # empty = everyone in the household (today's behaviour)
sees_people: [emma, jack]  # only these people's rows
```

It applies to the facets that are *about people* — marked ◍ in §6 — and is ignored by the ones
that are about the household (`meals.repertoire`, `lists.shopping`, `trips.gallery`, `music`).
The three axes stay orthogonal and each answers one question: **facet** = what kind, **reach** =
how much, **sees_people** = whose.

It also generalises past the case that prompted it, at no extra cost: a nanny hired for the
younger child is `sees_people: [jack]`; a co-parent is `sees_people: [their own child]`.

**One operational note:** an explicit list goes stale — a new baby would need adding to every
grandparent's scope, and a list nobody remembers to update fails silently in the *permissive*
direction only if we are lucky. The editor should therefore offer "everyone", "the children"
(computed from `role == 'child'`, so it self-updates) and "choose people…", storing the first
two as intent rather than as a frozen expansion.

---

## 6. The facets

Twenty-seven, plus two capabilities that are not views (§6 Chat B and C). "Justified by" names the person whose want makes it a line; a facet without one
should be deleted at review. "Kind" is how it is enforced and is defined in §7. **◍ marks the
facets that are about people**, and so are also filtered by `sees_people` (§5).

### Calendar & driving

| Facet | What it is | Kind | Justified by |
|---|---|---|---|
| `calendar.events` ◍ | what is happening: title, when | **route** | the grandparent — wants to know Emma has volleyball Tuesday |
| `schedule.assignment` ◍ | who drives this event, per leg, in which car | **field** | the grandparent again — she *does* see this today, on the card |
| `schedule.logistics` ◍ | leave-by times, travel durations, the drive list, the day's chaining | **field** | …and has never seen any of it: the operational picture is the driver's |
| `schedule.diagnostics` | solver reasoning, unassigned causes, AI notes | **field** | nobody but a parent debugging the schedule |
| `schedule.driver_calendars` | `driver_events` — a driver's own private calendar | **field** | the driver, who never agreed to publish it household-wide |
| `schedule.carpool_contacts` | `assist_contacts` — outside people's phone numbers | **field** | the other family, who is not a member here at all |
| `drives.sheet` | the active-drive cockpit: address, ETA, roll call | **route** | the helper, who needs today's drive and nothing else |
| `drives.status_writes` | start/arrive/complete, roll-call taps | **route** | same |

### Chat — three questions wearing one word

Chat was the hardest section to get right, and the reason is that **"chat access" is three
different questions**, which is why every attempt to answer it as one felt confusing:

> **A. Visibility** — which conversations exist for me?
> **B. Initiation** — may I start one, and with whom?
> **C. Contribution** — may I give the family something, and does it become family memory?

Every one of the household's rules lands cleanly on exactly one of them, and they stop
contradicting each other once separated. *"A helper can talk to the parent about the drive"* is
**A**. *"Guests can be added but can't DM whoever they like"* is **B**. *"But if they're the one
at the event, they're the one who can share the moments"* is **C** — and it is not a
contradiction of **A** at all, once you notice they are different questions.

#### A. Visibility

| Facet | What it is | Kind | Justified by |
|---|---|---|---|
| `chat.family` ◍ | the household room | **field** | the guest, whose presence changes what the family says in it |
| `chat.groups` | ad-hoc group threads | **field** | — (membership does the work; the facet gates discovery) |
| `chat.dms` | direct messages | **field** | — (membership does the work; see **B** for who may open one) |
| `chat.event_threads` ◍ | the thread on an event — **where moments accumulate** | **field** + ⚠️ schema | the helper, who must *not* have it: a family's photo history is not a work channel |
| `chat.agent` | Argyle — both the DM and `/api/chat/*` | **route** + field | the guest, who must not reach a tool-holding agent |

**The drive is not the event, and that distinction is the whole helper story.** The household's
words: *"they should be able to have a chat with the parent about the drive to/from the event,
but not the chat where the moments go — sharing media is a big step beyond saying you're
running late."* An event thread is a family's memory of an occasion; a conversation about a
drive is two people coordinating a car.

**But a drive is not a room either.** An earlier draft made `drive` a fifth channel kind,
get-or-create per leg. The household corrected it: *"maybe the drive channel is really just a
thread in the DM with the parents — a drive channel is really just some context about a set of
messages in the DM."* That is right, and for a reason worth stating as a rule:

> **The container is the durable thing; the transient thing is a label on messages.**

The relationship (helper ↔ parent) persists; a drive lasts forty minutes. A channel per leg
would create and archive several channels a day, forever, and would fragment a conversation
humans experience as continuous — the nanny you text, who sometimes texts about today's
pickup.

So there is **no drive channel**. `ChatMessage` gains an optional `context`
(`{kind: 'drive', event_id, leg_id}`) — the same shape as the `attachment` and `card` dicts it
already carries, so this is additive, not structural. Arriving at the DM from the drive sheet
pre-sets the context; the thread renders a small "re: Emma's pickup · today 4:00" chip over
that run of messages. The parent gets context without a new inbox, and the helper gets somewhere
to say "running late" that is unambiguously about this drive.

The moment-gate property survives unchanged and still costs nothing: `main.py:11248` gates
moment creation on `channel.get('kind') == 'event'`, and a DM is not an event — so **a drive
conversation can never produce family memory**, whichever container it lives in.

`invited` in the preset table means `none` at the class level **with instance membership still
honoured** — you do not discover these conversations, but one you are explicitly added to is
yours. That is the Slack external-guest shape, and it is why instance grants are additive over
a facet rather than bounded by it.

#### B. Initiation — `chat.initiate`

Not a view; a capability, and the thing that makes a guest a guest.

```
chat.initiate:  none | parents | household | anyone
```

- **`none`** — cannot open any conversation. May be added to one by somebody who can, and may
  talk freely once inside. The household's model: *"like external people on Slack — someone in
  the company can add them or message them, but they cannot start a message with anyone."*
- **`parents`** — may open a conversation with parents only. This is today's helper rule
  (`main.py:11060`), and the household keeps it: *"helpers DM-ing parents is fine."*
- **`household`** — may open a conversation with household members, never with guests.
- **`anyone`** — household and guests.

This replaces a rule that exists today as hardcoded checks in three places (`main.py:11060`,
`main.py:11084`, `storage.py:4916`) and could not be varied per person.

#### C. Contribution — `moments.contribute`

```
moments.contribute:  none | when_present | all
```

**Contribution is not membership**, and that is the sentence that untangles the helper.

The household spotted the apparent contradiction: a helper is barred from event threads, *but
if they are the adult who actually drove the kid and stayed, they are the one holding the
camera.* Both are right, because giving the family a photo and reading the family's thread are
different acts. `when_present` grants the first without the second: the helper may post a
moment **for an event the schedule places them at**, it lands in that event's thread, the
family sees it — and the helper never gains read access to the thread, its history, or anyone
else's messages in it.

**It is an upload tied to the event, not a message typed into a thread** — the household's own
framing, and the better one. The helper's surface is *"share a photo from Emma's game"*; the
event thread is merely where it lands.

That flow already exists end to end. `run_capture_prompts` (`services/presence.py`) sweeps
live events, resolves `members_at_event` — *"the assigned driver plus every passenger-bound
member"* — and pushes a capture prompt with a deep link. Tap, upload, done; nobody opens a
thread. **The helper is already in `members_at_event`. They are excluded by one filter on one
line**: `role in ('parent', 'adult')`. That line becomes a `moments.contribute` check, and the
capability exists.

So a helper's chat surface is a DM with the parents — which they have today, and keep — and
their contribution surface is a capture prompt. Nothing is taken from them; what changes is
that their messages can carry drive context, and that they may finally share a photo from an
event they actually attended.

### Meals & lists

| Facet | What it is | Kind | Justified by |
|---|---|---|---|
| `meals.plan` | what's for dinner, today and this week | **route** + ⚠️ field | the grandparent — genuinely likes knowing |
| `meals.repertoire` | the household's dish library, rules, history | **route** | — |
| `meals.prep` | prep steps and the run sheet | **route** | — |
| `lists.shopping` | the shopping lists | **route**, per-list **instance** | **the person who gets the grocery list and no other** |
| `lists.errands` | errands the solver places | **route** | — |
| `lists.household_tasks` ◍ | the housework ledger | **route** | the outside hand who holds one task |
| `lists.kid_tasks` ◍ | homework and deadlines | **route** | — |

### Chores & the points economy

| Facet | What it is | Kind | Justified by |
|---|---|---|---|
| `chores.board` ◍ | the pot: what needs doing, who claimed it | **route** | — |
| `routines` ◍ | definitions, today's checklist, streaks | **route** | — |
| `points.balances` ◍ | every kid's balance and tier | **route** | the grandparent who should not be shown a scoreboard of children |
| `points.ledger` ◍ | one member's transaction history | **route** | the teenager, whose ledger is theirs |
| `rewards` | catalogue, redemptions, the pool | **route** | — |

### Presence

| Facet | What it is | Kind | Justified by |
|---|---|---|---|
| `presence.location` ◍ | live coordinates on the map | **route** + ⚠️ field | everyone; this is the sharpest line in the app |
| `presence.status` ◍ | status protocols and status days | **route** | — |
| `presence.moments` ◍ | the photo/video feed | **route** | the guest — this is the one thing they get |

### Trips, occasions, music, pets

| Facet | What it is | Kind | Justified by |
|---|---|---|---|
| `trips.gallery` | that a trip exists, and when | **route** | the grandparent, who wants to know they are away |
| `trips.detail` | the itinerary, bookings, prices | **route** | …and does not need the reservation numbers |
| `trips.planning` | every planning write | **route** | — |
| `occasions` ◍ | parties and gatherings: guests, menus, attendance | **route** | the parent planning a surprise, same as a trip |
| `music` | playback, shelves, playlists, room announcements | **route** | the child, who has the Music tab today |
| `pets` | critters and the arena | **route** | the guest's kid, who is here to battle |

**Administration is not a facet.** Verifying chores, resetting PINs, editing config, member
CRUD, board/panel editing, Walmart ordering, and flipping enforcement stay keyed on
`role == 'parent'` through the existing `PARENTS` tier. Scope answers *what may you see*;
role still answers *what may you administer*.

---

## 7. Three kinds of enforcement — and where scope actually lives

The first draft claimed the request guard would be the single enforcement point for reads.
**That is false**, and the facet audit is what proved it. Three kinds:

**Route** — the facet maps to endpoints that serve nothing else. `auth.RULES` rows gain a
fourth element naming the facet, and `_auth_guard` (`main.py:990`) checks it where it already
checks the tier. Inherits default-deny, the unclassified-route test, and audit mode. **Most
facets are this**, and this is the cheap half.

**Field** — the facet shares a payload with facets a household would want set differently.
The guard cannot help: it can refuse a route, not redact a key. These require the *assembler*
to take a viewer and shape its own output.

**Instance** — the object carries its own allowlist. Already an idiom here, used in four
places with one convention (**empty means everyone**): `Chore.eligible_member_ids`
(`schemas.py:304`), `Car.allowed_driver_ids`/`allowed_passenger_ids` (`schemas.py:103-104`),
`ChatChannel.member_ids` (`schemas.py:259`). A shared list is the same shape: `shared_with`
empty = household-wide (today's behaviour), populated = those people.

**…but the default runs both ways, and secrets must fail closed.** The four existing
allowlists all mean *empty = open*, which is right for a chore anyone may claim. It is wrong
for a surprise. So every shareable object declares an `audience`, and each object **type**
declares its default:

```
audience:     household | parents | shared
shared_with:  [member ids]        # the audience when 'shared'
```

| Type | Default | Because |
|---|---|---|
| shopping lists, chores, cars, channels | `household` | being seen is harmless; today's behaviour |
| **trips** | **`parents`** | *"If I am planning a trip to Disney World, I don't necessarily want the kids seeing that."* |
| **occasions** | **`parents`** | the household's call: same shape as trips |
| gift lists, when they exist | **`parents`**, never `household` | see below |

**This supersedes the `hidden_from` proposal in `docs/occasion_design.md`.** That brief
identified the problem exactly — *"a gift list is the app's first entity that must be hidden
from specific family members, and getting it wrong is not a bug report"* — but chose a
**deny-list**, which fails **open**: forget to add one child and the surprise is gone, silently,
with no error and no way to undo it. An allow-list with a closed default fails **closed**,
where the worst case is *"I can't see the trip you're planning"* — a complaint, not a ruined
Christmas. For anything secret, choose the direction whose failure you can survive.

**Instance grants are additive over a facet** (a guest added to one group has it without the
class), **but a closed default is not a grant.** `trips.gallery: all` does not reveal a
`parents`-audience trip; it means "you may see trips that are yours to see."

**For trips and occasions the wall panel is not one leak among several — it is the only one.**
Checked 2026-08-20: `templates/app.html` contains **zero** references to trips or occasions, and
the PWA's seven tabs are chores, drives, family, map, messages, music, myday. There is no trips
surface on a phone. Both are builtin **board** cards (`services/builtin_boards.json:91`, `:104`)
and dashboard pages. So a child encounters a trip in exactly one place: the kitchen wall.

That sharpens where the work goes. For these two facets the enforcement that matters is, in
order: **the board**, then the agent (*"Argyle, when are we going to Disney?"*), then the
digests, then the dashboard pages. The PWA needs nothing, because there is nothing there yet.

And it is the concrete argument for panels carrying their own scope: **a panel is a place, not
a person, and cannot hold a `parents` audience just because a parent is standing in front of
it.** The countdown tile is where Disney gets spoiled.

### Trips: the choice, stated plainly

Because the panel is the only surface a child meets a trip on, the whole question reduces to a
binary the household put exactly right:

> *"Either trips are private and you mark them public to share them on the panel, or trips are
> public and you mark them private to hide them from the panel."*

**Recommendation: private by default.** Two reasons, and one real objection that has to be
answered rather than waved off.

- **Trip creation is rare** — a handful a year. Friction at a rare moment is nearly free,
  which is what makes a required choice affordable here and not on, say, a shopping item.
- **The failures are wildly asymmetric.** Forgetting to mark a trip public means the wall does
  not show a countdown yet: a complaint, fixed with one tap. Forgetting to mark a trip private
  means Disney is on the kitchen wall at breakfast: unrecoverable, and nobody files it as a bug
  because the damage is already done.

**The objection, which is this repo's own recurring bug:** a default of private means the
countdown tile — a feature the family likes — silently shows nothing until somebody remembers
it exists. This codebase has been burned by exactly that shape more than once (the car
readiness sweep that never ran for 27 releases; the Alpine dialog that could not open). A
feature that quietly does nothing is indistinguishable from one that is working.

**So hiding is never silent — to the people allowed to know.** The same rule the calendar
quarantine already follows (*"skipping is never silent: a skipped calendar is a missing kid"*).
The trips board card and the `/trips` page both say **"2 trips not shown here"** to a viewer
whose scope permits trips, so a parent can always see that the wall is holding something back.
The absence is legible to whoever may know and invisible to everyone else, which is the whole
trick.

**And the UI says what is actually being chosen.** The create form asks *"Show this on the
family wall?"* — not an audience enum. `audience` is the model underneath; the wall is the
decision people are really making, and a label that names the abstraction instead of the
consequence is how a parent picks the wrong one.

**A general note this exposed, worth applying to the whole list:** a facet's risk is a function
of *where it renders*, not only of what it contains. `trips.*` looked like a phone-app
permission and is really a wall-panel one. Before implementing any facet, check its surfaces —
a facet nothing renders cannot leak yet, and one that renders only on a shared screen is a
different problem from one on a personal device.

### The rule that follows

> **Scope is applied where data is ASSEMBLED, not where it is routed.**

Because two payloads re-serve other facets' data, and a route-level check would be a bypass:

- **`GET /api/home_board`** re-serves the schedule blob — assignments, ghost assignments, car
  assignments, `route_edges`, `driver_events` (`services/home_board.py:1386-1402`).
- **`GET /api/presence/*`** re-serves event-channel content: moments are stored as *messages
  in event channels*, so denying `chat.event_threads` does **not** deny the photos, and vice
  versa. Same rows, two doors.

So the redacting viewer belongs in `assemble_*`/`build_*`, and every route that calls it
inherits the redaction for free. For unwelded facets, route and assembler coincide and the
guard remains the whole story.

---

## 8. The welded payloads — the honest cost

Ranked by *how much a household wants the split* against *how welded it is*. This is the
expensive part of the arc and it should not be discovered during implementation.

1. **`GET /api/schedule` (`main.py:15275`) — the worst.** A ~30-key blob, assembled at
   `main.py:15385-15439`, that **takes no viewer parameter at all.** Separating calendar from
   driving means redacting ten keys — `assignments`, `ghost_assignments`, `ghost_drivers`,
   `car_assignments`, `assist_assignments`, `assist_contacts`, `route_edges`,
   `initial_edges`, `final_edges`, `driver_events` — plus the live-drive keys. Giving this
   endpoint a viewer is the single largest piece of work in the arc.

   **The good news, and it is genuinely good:** `GET /api/calendar/events` (`main.py:2961`)
   already returns *only* `id / title / start / event_type / trip_id / source_event_ids`
   (`main.py:2980-2987`) — no location, no driver, no assignments. **The grandparent endpoint
   already exists.** `calendar.events` is route-level today; only the *combined* view is
   welded. A keeping-up adult can be served correctly before `/api/schedule` is touched.

2. **`GET /api/family/locations` (`main.py:10895`)** — four things in one array: raw
   coordinates, a fallback fix harvested from the drive sheet, "driving: en route to
   practice" schedule context, and **car telemetry (location, fuel, battery, range)**. Coords
   and "is currently driving to X" cannot be separated at the route. The existing redaction is
   binary and defeatable (§10).

3. **`GET /api/members/{member_id}/day` (`main.py:8452`)** — welds rides, per-leg driver
   identity, leave-by time, homework due dates, and **status days**. It also takes **no viewer
   parameter**, so any member reads any other member's whole day (§10).

4. **`GET /api/meals/plan` (`main.py:8966`) is a whereabouts feed wearing a meals label.**
   `services/meals.py:377-396` loads the schedule cache and returns per-member slots including
   `where` — a location — and `away_on_trip`. **Granting `meals.plan` grants a derived
   location feed for every member.** This is exactly the kind of thing the tab-line list could
   never have caught, and it is why `meals.plan` is marked route **+ field**.

5. **Event chat threads are `member_ids: []` by construction** — `services/storage.py:4893`,
   commented *"household-visible, like the family channel"*, and `get_channels_for_member`
   returns family and event channels to everyone unconditionally
   (`services/storage.py:4916-4918`). **The helper-on-one-event-thread case needs a schema
   change, not a scope check**: event channels must gain real membership (derived from
   attendance and from the drive assignment) before `chat.event_threads: own` can mean
   anything. This is the most expensive of the household's three requests and the one most
   worth doing, because it is what lets a helper be useful without being inside the family.

6. **`GET /api/channels` (`main.py:11019`) decorates every channel with `last_message`**, so
   the list leaks message *previews* across kinds. Per-kind scope is field-level filtering
   inside `get_channels_for_member`.

---

## 9. Defaults, and why the editor is presets rather than switches

Twenty-four facets cannot be twenty-four dropdowns on a member card. Role supplies a
**preset**; the person deviates from it. This is the stages pattern
(`stage → CAPABILITIES → capability_overrides`) lifted to the household, and it is also the UI:

- A parent picks a preset — **Household adult**, **Keeping up**, **Helper**, **Guest** — and
  in the overwhelming majority of cases stops there.
- Facets are grouped by §6's headings, collapsed, each showing a summary phrase: *"Calendar &
  driving: calendar only"*, *"Chat: event threads only"*.
- Expanded, most rows are a toggle; only `schedule.assignment`, `schedule.logistics`, `chores.board`,
  `chat.event_threads`, `points.ledger` and `presence.location` offer `own`.
- The card shows **deviations from the preset**, so an unedited person is one line.

### The presets

`all` unless marked. `—` is `none`.

| Facet | Household adult | Keeping up | Child | Helper | Guest |
|---|---|---|---|---|---|
| **`sees_people`** | everyone | **the children** | everyone | the kids they drive | — |
| `calendar.events` | all | all | own | own | — |
| `schedule.assignment` | all | — | own | own | — |
| `schedule.logistics` | all | — | own | own | — |
| `schedule.diagnostics` | all | — | — | — | — |
| `schedule.driver_calendars` | all | — | — | — | — |
| `schedule.carpool_contacts` | all | — | — | — | — |
| `drives.sheet` | all | — | — | own | — |
| `drives.status_writes` | all | — | — | own | — |
| `chat.family` | all | all | all | — | invited |
| `chat.groups` | all | all | all | — | invited |
| `chat.dms` | all | all | all | **all** | invited |
| `chat.event_threads` | all | all | all | invited | invited |
| `chat.agent` | all | all | all | — | — |
| **`chat.initiate`** | anyone | household | household | **parents** | **none** |
| **`moments.contribute`** | all | — | all | **when present** | — |
| `meals.plan` | all | all | all | — | — |
| `meals.repertoire` | all | all | all | — | — |
| `meals.prep` | all | all | all | — | — |
| `lists.shopping` | all | — | all | — | — |
| `lists.errands` | all | — | — | — | — |
| `lists.household_tasks` | all | — | own | — | — |
| `lists.kid_tasks` | all | all | own | — | — |
| `chores.board` | all | all | own | — | — |
| `routines` | all | all | own | — | — |
| `points.balances` | all | all | all | — | — |
| `points.ledger` | all | — | own | — | — |
| `rewards` | all | all | all | — | — |
| `presence.location` | all | — | own | — | — |
| `presence.status` | all | all | all | — | — |
| `presence.moments` | all | all | all | — | **all** |
| `trips.gallery` | **parents** | — | — | — | — |
| `trips.detail` | **parents** | — | — | — | — |
| `trips.planning` | **parents** | — | — | — | — |
| `occasions` | **parents** | — | — | — | — |
| `music` | all | all | all | — | — |
| `pets` | all | all | all | — | **all** |

**Two constraints on this table.** First, **Household adult, Child and Helper must reproduce
today's behaviour exactly** — every row is written to match, and where it does not, that is
either a deliberate fix (§10) or a table error, which audit mode (§11) is how we tell apart.
Second, **Keeping up is the one preset that deliberately changes what a person sees, and the
household decided it on 2026-08-20.** The decision, in two parts: *"they do not
need all that driving info — they want to see the calendar"*, and *"they want to see the kids'
calendar, not the adults'."* So the preset is `calendar.events: all` narrowed by
`sees_people: the children` (§5), and every driving facet off.

What she sees today, for the record, because this is a removal and removals get written down.
She has no Drives tab (`isPassengerMode()` is true and `drives` sits in `applyRoleTabs`'s
hidden list, `app.html:867-897`), but the Family tab is *not* a plain agenda:
`renderFamilyCard` (`app.html:6280`) decorates every event via `familyDriverChips()` — the
driver's name, per-leg `Dropoff:`/`Pickup:` labels, the assigned car with an amber `⇄` when it
is not that car's usual driver, and `⚠ Needs Driver`. So today she sees *"Volleyball 4:00–5:30
· Emma · Dropoff: Dad · Pickup: Mom · 🚗 Odyssey ⇄"*, and after this she sees *"Volleyball
4:00–5:30 · Emma"*.

Losing `⚠ Needs Driver` with it is correct rather than incidental: a keeping-up adult has no
driver record — that is the definition of the preset — so a gap she can read is a gap she
cannot close.

`schedule.logistics` was already effectively `none` for her and stays there, which is why it is
a separate facet: **`leave_by` appears nowhere in `app.html`** (be-ready times reach people only
through push and the wall board), and although `route_edges` is destructured in the shared
`buildTimeline`, the family branch renders through `renderFamilyDay` → `renderFamilyCard`,
which draws no travel blocks and no durations. Splitting assignment from logistics keeps the
deliberate change (`assignment`) separate from the invisible tightening (`logistics`, which
only stops shipping keys her client never drew).

**Note where the line falls: inside one UI component, not between two.** The same card renders
`calendar.events` (title, time, location, passengers) and `schedule.assignment` (driver, leg
and car chips). That is the §5 lesson proved from the other direction — a single card carrying
two facets — and it is why these are field-level in the client as well as the payload. The
implementation is correspondingly small: with `schedule.assignment` denied,
`renderFamilyCard` omits `driverChips` and changes nothing else.

`Guest` is the new role and the answer to §1. Note what it is *not*: a "distant adult". A
grandparent is an adult on the **Keeping up** preset, adjusted to taste. **The preset is a
starting point; the household's real answer is the deviation.**

### The keeping-up adult heuristic is retired

`app.html:859-865` derives `isKeepingUpAdult()` — an adult with no driver and no passenger
record — and shapes the shell from it with no server-side counterpart. It was guessing at a
scope nobody could state. It becomes a preset that says so.

---

## 10. Live holes this closes

All verified 2026-08-20. They are *why* enforcement cannot be layered on afterwards.
**Closed in S1 (v2.330.0)** — token-resolved viewers refused immediately, tokenless callers on today's grace until the flip (`tests/test_family_network.py`).

1. **`GET /api/channels/{id}/messages` (`main.py:11098-11102`) has no membership check.** It
   verifies the channel exists and returns its messages — any caller with a channel id reads
   that thread, DMs included. The write path (`main.py:11231`) does check.
2. **`GET /api/family/locations` (`main.py:10896`) trusts a client-supplied `viewer`.**
   `family_eyes = bool(viewer and storage.get_member(viewer))` — any valid member id reveals a
   private-stage child's coordinates. Fix: derive from `auth.acting_member()`.
3. **`GET /api/members/{member_id}/day` (`main.py:8452`) has no viewer at all.** Any member
   reads any other member's whole day, including status days and homework.
4. **`GET /api/chat/conversations` (`main.py:12718`) returns every Argyle conversation in the
   house**, voice sessions included — `get_all_conversations()` takes no member.
5. **`POST /api/members` (`main.py:4850`) skips the role whitelist** that `PUT` enforces
   (`main.py:4869`), so a create can set a role no preset knows.

Three of the five are the same bug: **a read endpoint that never asks who is looking.** That
is the arc in one sentence.

---

## 11. What stays separate, on purpose

- **`capability_overrides` / stages are NOT merged into scope.** A stage capability is about
  what a child is developmentally ready for and changes on its own as they grow; a scope is a
  standing decision that changes only when someone changes it. Different lifecycles. They
  **compose**: a Navigator with `calendar.events: own` still gets `horizon_days: 13`.
- **`assist_tier` stays a ledger label** — "does this person's work count in the household's
  split," not "what may they see." Recorded so nobody later 'fixes' it into an access control.
- **`AssistContact` remains not an identity.** `helps_with` stays a picker filter, never a gate.
- **`status` (`active | disabled | archived`) is orthogonal.** Disabled revokes access
  entirely; scope describes what access *is* when you have it.

---

## 12. Rollout — ordered by what it buys, not by architecture

Audit-mode-first throughout, the discipline `auth_design.md` earned: *flipping before the
evidence exists means discovering the panel cannot reach its board on a school morning.*

### Phase 1 — no model required (start here)

| Slice | What it is | What it buys, immediately |
|---|---|---|
| **S1** ✅ v2.330.0 | The five holes (§10) | Closes live leaks: any member can read any DM by id, spoof `viewer` to unmask a private-stage child's coordinates, read anyone's whole day, and read every Argyle conversation in the house. **These are true today and independent of every decision in this document.** |
| **S2** ✅ v2.331.0 | Widen the capture-prompt filter | A helper who drove your kid to the game can share a photo from it. One filter line (`role in ('parent','adult')` in `run_capture_prompts`) — the rest of the flow already exists. A real new capability for the cost of an afternoon. |

### Phase 2 — the model, dark

| Slice | What it is | What it buys |
|---|---|---|
| **S3** ✅ v2.332.0 | `services/scope.py` — facets, presets, `reach()`, `can_see()`, `sees_people`, `audience`. Nothing calls it. | Nothing visible. Buys the tests that prove the presets reproduce today, which is what makes every later slice safe to ship. |

### Phase 3 — the three cases that started this

| Slice | What it is | What it buys |
|---|---|---|
| **S4** ✅ v2.333.0 | `audience` on trips + occasions, closed default, enforced on the **board card** first, then agent and digests. "N trips not shown here" for those who may know. | **The Disney case.** A surprise trip stops appearing on the kitchen wall. Bounded, because the panel is the only surface a child meets a trip on. |
| **S5** ✅ v2.334.0 | `sees_people` on the ◍ facets, plus pointing the keeping-up shell at `/api/calendar/events` (already returns titles and times with no driver data). *(Shipped: the endpoint is viewer-aware with reach + `sees_people`, the preset has its hand path on the member card, and the keeping-up family card drops every driving chip. The remaining ◍ assemblers pick the filter up with the field-kind work in S9, where their payloads are being reshaped anyway.)* | **The grandparent case.** She sees Emma's and Jack's calendar — what they are up to, nothing about who drives or when anyone leaves. Needs no work on `/api/schedule`. |
| **S6** ✅ v2.335.0 | `chat.initiate`, and instance membership honoured over a `none` facet. *(One documented delta from the old hardcode, per the §9 table: a household adult — initiate `anyone` — may now open a DM with a helper.)* | **The guest case.** Someone can be added to a conversation and talk freely, and can never start one — the Slack external-guest shape, replacing hardcoded checks in three places. |

### Phase 4 — the expensive half

| Slice | What it is | What it buys |
|---|---|---|
| **S7** ✅ v2.336.0 | Route-kind facets on `auth.RULES`, guard in audit mode until the record is boring. | Most of the facet list, cheaply. This is the bulk of the enforcement and the least interesting to write. |
| **S8** | Instance grants: `shared_with` on `ShoppingList` (per-list check on `list_id`, already a route parameter). | Share the grocery list with one person without sharing lists in general. |
| **S9** | Field-kind assemblers, one at a time, largest last: `/api/meals/plan` (a whereabouts feed in disguise), `/api/members/{id}/day`, `/api/family/locations`, then `/api/schedule` **with `/api/home_board` in the same slice** because it re-serves the same blob. | The calendar-without-driving split at the API, and the end of four payloads that answer without asking who is looking. The largest single piece of work in the arc. |
| **S10** | Fan-out audiences: `moment_push_audience`, digest and briefing recipients, `get_channels_for_member`, message fan-out, `_notify_member_lanes`. | Scope reaches the things the server sends unprompted. No meaningful audit mode — a push not sent is invisible — so tests per site. |
| **S11** | Event-channel membership (`member_ids` on event threads, today `[]` by construction). | A guest can be added to one event thread without seeing the rest. Schema change. |

### Phase 5 — the surfaces and the people

| Slice | What it is | What it buys |
|---|---|---|
| **S12** | Message `context` (`{kind:'drive', event_id, leg_id}`), pre-set from the drive sheet. | "re: Emma's pickup" on the helper's DM — context without a new inbox. Additive: `ChatMessage` already carries `attachment` and `card` dicts. |
| **S13** | The shell, driven by the delivered scope map; `isKeepingUpAdult()` retired. | The app stops guessing at a scope nobody could state. |
| **S14** | The editor (§9): presets, grouped disclosure, deviations only. | **The household owns it.** A scope only an agent or a JSON edit can set is not a feature — this is the slice that makes the whole arc real to a person. |
| **S15** | The `guest` role. | Extended family, at last — meaningful only once everything above exists. |
| **The flip** | Household's act, on evidence, exactly as `auth_enforce` is. | Advisory becomes enforced. |

**A standing caveat:** while `auth_enforce` is dark and `service_local_grace` is on, **scope is
advisory.** The two together are the deliverable; either alone is half a door.

---

## 13. What must be true (tests)

- Every route in `RULES` names a facet or is explicitly marked as having none; a test fails on
  any route naming neither. (Extends the existing unclassified-route test in `tests/test_auth.py`.)
- For **Household adult, Child and Helper**, the preset reproduces today's behaviour —
  asserted per facet, not in aggregate. **Keeping up** is asserted against its decided new
  behaviour (§9), with the deviation from today named in the test.
- A `guest` reaches `presence.moments` and `pets` and is refused all twenty-five others, at the
  API and not merely in the shell.
- `calendar.events: all` + `schedule.assignment: none` + `schedule.logistics: none` returns
  titles and times and **no** assignment, edge, car, carpool-contact or driver-calendar key —
  asserted key by key.
- The **Keeping up** preset returns the children's events only — an adult-only event is
  absent entirely — and renders each card with title, time, location and passengers and **no**
  driver chip, leg label, car chip or needs-driver warning — the one intentional
  behaviour change in the table, asserted so it cannot regress by accident in either
  direction.
- `meals.plan` with `presence.location: none` returns no `where` and no `away_on_trip`.
- `/api/home_board` redacts exactly as `/api/schedule` does for the same viewer.
- Denying `chat.event_threads` does not silently leave the photos reachable via
  `/api/presence/event-moments` — the two doors agree.
- A helper with `chat.event_threads: own` sees the thread for an event they drive and no other.
- `sees_people: []` is every member (today's behaviour); `sees_people: [emma]` returns Emma's
  rows and nothing of Jack's, across every ◍ facet — one assertion per facet, since the filter
  is one list applied in many assemblers.
- A `parents`-audience trip is absent from a child's gallery, from a keeping-up adult's, from
  the agent's answers, from the digest, and from the dashboard pages — but **the wall panel's
  countdown tile is the assertion that matters**, since it is the only surface on which a child
  encounters a trip at all.
- Sharing that trip with one child reveals it to that child and to nobody else.
- A hidden trip is *counted* on the trips card and the `/trips` page for a viewer who may see
  trips ("2 trips not shown here"), and produces no trace at all for one who may not.
- A list with `shared_with: []` is household-wide; populated, it is those people plus anyone
  with `lists.shopping: all`.
- The four viewer-less reads (§10) refuse or redact for a viewer who should not see them.
- Scope and stage compose: a Navigator with `calendar.events: own` keeps `horizon_days: 13`.

---

## 14. Open questions

1. **Is board/panel editing administration?** Asserted in §6, not verified. The boards-editor
   arc deliberately put editing *on* the board, which may mean any member at a panel can
   rearrange it — in which case it is a facet after all.
2. **Does `presence.moments` want `own`?** "Moments from events my kid was at" is a plausible
   grandparent scope and the difference between a warm feed and a firehose.
3. **Does a `guest` belong in `chat.family` at all,** or does the household want a separate
   extended-family thread? The preset says no, because a guest in the family room changes what
   the family says in it. A fifth channel kind is the honest answer if it is ever wanted.
4. **Cross-household subjects.** `sees_people` (§5) answers *whose* within this household. It
   does not answer it across households — a shared grandparent seeing two families' children
   is the federation question, parked in §3.
5. **Scope on the agent.** `agent_router` builds the family roster into every prompt and
   `_may_use_family_tools` keys on role. Both should consult scope; a `guest` should reach no
   agent tools at all. Worth its own slice.

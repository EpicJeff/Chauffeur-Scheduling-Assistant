# Family Network — Access Scope, and the Household Boundary

Status: **DRAFT — nothing built.** Written 2026-08-20 to settle a question before code.
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

---

## 6. The facets

Twenty-four. "Justified by" names the person whose want makes it a line; a facet without one
should be deleted at review. "Kind" is how it is enforced and is defined in §7.

### Calendar & driving

| Facet | What it is | Kind | Justified by |
|---|---|---|---|
| `calendar.events` | what is happening: title, when | **route** | the grandparent — wants to know Emma has volleyball Tuesday |
| `schedule.drives` | who drives, legs, which car, leave-by times | **field** | …and does *not* need "Dad leaves at 3:42 in the Odyssey" |
| `schedule.diagnostics` | solver reasoning, unassigned causes, AI notes | **field** | nobody but a parent debugging the schedule |
| `schedule.driver_calendars` | `driver_events` — a driver's own private calendar | **field** | the driver, who never agreed to publish it household-wide |
| `schedule.carpool_contacts` | `assist_contacts` — outside people's phone numbers | **field** | the other family, who is not a member here at all |
| `drives.sheet` | the active-drive cockpit: address, ETA, roll call | **route** | the helper, who needs today's drive and nothing else |
| `drives.status_writes` | start/arrive/complete, roll-call taps | **route** | same |

### Chat

| Facet | What it is | Kind | Justified by |
|---|---|---|---|
| `chat.family` | the household room | **field** | the guest, whose presence changes what the family says in it |
| `chat.groups` | ad-hoc group threads | **field** | — (membership does most of the work; the facet gates joining) |
| `chat.event_threads` | the thread hanging off one event | **field** + ⚠️ schema | **the helper**, who needs the thread for the event he drives |
| `chat.agent` | Argyle — both the DM and `/api/chat/*` | **route** + field | the guest, who must not reach a tool-holding agent |

**DMs are deliberately not a facet.** A direct message is a two-party relationship, not a
household view, and it is already instance-scoped by `member_ids`. Making it a facet would let
a scope edit silently sever a conversation. Who *may* DM whom stays a rule (helpers → parents
only), not a view permission.

### Meals & lists

| Facet | What it is | Kind | Justified by |
|---|---|---|---|
| `meals.plan` | what's for dinner, today and this week | **route** + ⚠️ field | the grandparent — genuinely likes knowing |
| `meals.repertoire` | the household's dish library, rules, history | **route** | — |
| `meals.prep` | prep steps and the run sheet | **route** | — |
| `lists.shopping` | the shopping lists | **route**, per-list **instance** | **the person who gets the grocery list and no other** |
| `lists.errands` | errands the solver places | **route** | — |
| `lists.household_tasks` | the housework ledger | **route** | the outside hand who holds one task |
| `lists.kid_tasks` | homework and deadlines | **route** | — |

### Chores & the points economy

| Facet | What it is | Kind | Justified by |
|---|---|---|---|
| `chores.board` | the pot: what needs doing, who claimed it | **route** | — |
| `routines` | definitions, today's checklist, streaks | **route** | — |
| `points.balances` | every kid's balance and tier | **route** | the grandparent who should not be shown a scoreboard of children |
| `points.ledger` | one member's transaction history | **route** | the teenager, whose ledger is theirs |
| `rewards` | catalogue, redemptions, the pool | **route** | — |

### Presence

| Facet | What it is | Kind | Justified by |
|---|---|---|---|
| `presence.location` | live coordinates on the map | **route** + ⚠️ field | everyone; this is the sharpest line in the app |
| `presence.status` | status protocols and status days | **route** | — |
| `presence.moments` | the photo/video feed | **route** | the guest — this is the one thing they get |

### Trips, music, pets

| Facet | What it is | Kind | Justified by |
|---|---|---|---|
| `trips.gallery` | that a trip exists, and when | **route** | the grandparent, who wants to know they are away |
| `trips.detail` | the itinerary, bookings, prices | **route** | …and does not need the reservation numbers |
| `trips.planning` | every planning write | **route** | — |
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
- Expanded, most rows are a toggle; only `schedule.drives`, `chores.board`,
  `chat.event_threads`, `points.ledger` and `presence.location` offer `own`.
- The card shows **deviations from the preset**, so an unedited person is one line.

### The presets

`all` unless marked. `—` is `none`.

| Facet | Household adult | Keeping up | Child | Helper | Guest |
|---|---|---|---|---|---|
| `calendar.events` | all | all | own | own | — |
| `schedule.drives` | all | — | own | own | — |
| `schedule.diagnostics` | all | — | — | — | — |
| `schedule.driver_calendars` | all | — | — | — | — |
| `schedule.carpool_contacts` | all | — | — | — | — |
| `drives.sheet` | all | — | — | own | — |
| `drives.status_writes` | all | — | — | own | — |
| `chat.family` | all | all | all | — | — |
| `chat.groups` | all | all | all | — | — |
| `chat.event_threads` | all | all | all | **own** | — |
| `chat.agent` | all | all | all | — | — |
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
| `trips.gallery` | all | all | all | — | — |
| `trips.detail` | all | — | all | — | — |
| `trips.planning` | all | — | — | — | — |
| `music` | all | all | all | — | — |
| `pets` | all | all | all | — | **all** |

**Two constraints on this table.** First, **Household adult, Child and Helper must reproduce
today's behaviour exactly** — every row is written to match, and where it does not, that is
either a deliberate fix (§10) or a table error, which audit mode (§11) is how we tell apart.
Second, **Keeping up is a genuine change**: today a keeping-up adult sees the whole solved
schedule because the app had nothing narrower to give them. The preset above hands them
`calendar.events` and takes `schedule.drives` away. That is a removal of something a person
can currently do, and it is the household's call to make, not this document's — it is called
out here rather than buried in a table.

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

## 12. Rollout — audit first, same as S1

- **S1 — the model, dark.** `services/scope.py`: the facet list, the presets, `reach()` and
  `can_see()`. Nothing calls it. Tests prove the presets reproduce today for the three roles
  that must.
- **S2 — the five holes (§10).** Correctness fixes; they do not wait for the rest.
- **S3 — route-kind facets on `auth.RULES`**, guard consults them in **audit mode**: records
  what it would have refused, refuses nothing. Runs until the record is boring. This is most
  of the facet list and it is the cheap half.
- **S4 — instance grants**: `shared_with` on `ShoppingList`, following the empty-means-everyone
  idiom, with the per-list check on `list_id` (already a route parameter, so this is clean).
- **S5 — event-channel membership** (§8.5): real `member_ids` on event threads, derived from
  attendance and drive assignment, so `chat.event_threads: own` means something. Schema change.
- **S6 — the field-kind facets, one assembler at a time**, largest last: `/api/meals/plan`,
  `/api/members/{id}/day`, `/api/family/locations`, then `/api/schedule` with `/api/home_board`
  in the same slice because it re-serves the same blob.
- **S7 — fan-out audiences.** `moment_push_audience` (`presence.py:146`), digest and briefing
  recipients (`family_digest.py`), `get_channels_for_member` (`storage.py:4904`), message
  fan-out and `_notify_member_lanes`. No meaningful audit mode — a push not sent is invisible —
  so tests per site.
- **S8 — the shell**, driven by the delivered scope map; `isKeepingUpAdult()` retired.
- **S9 — the editor** (§9). **The hand path is the point**: a scope only an agent or a JSON
  edit can set is not a feature the household owns.
- **S10 — the `guest` role**, meaningful only once the rest exists.
- **The flip** stays the household's act, on evidence, exactly as `auth_enforce` does.

While `auth_enforce` is dark and `service_local_grace` is on, **scope is advisory.** The two
together are the deliverable.

---

## 13. What must be true (tests)

- Every route in `RULES` names a facet or is explicitly marked as having none; a test fails on
  any route naming neither. (Extends the existing unclassified-route test in `tests/test_auth.py`.)
- For **Household adult, Child and Helper**, the preset reproduces today's behaviour —
  asserted per facet, not in aggregate. **Keeping up** is asserted against its *intended* new
  behaviour, with the deviation from today named in the test.
- A `guest` reaches `presence.moments` and `pets` and is refused all twenty-two others, at the
  API and not merely in the shell.
- `calendar.events: all` + `schedule.drives: none` returns titles and times and **no**
  assignment, edge, car, carpool-contact or driver-calendar key — asserted key by key.
- `meals.plan` with `presence.location: none` returns no `where` and no `away_on_trip`.
- `/api/home_board` redacts exactly as `/api/schedule` does for the same viewer.
- Denying `chat.event_threads` does not silently leave the photos reachable via
  `/api/presence/event-moments` — the two doors agree.
- A helper with `chat.event_threads: own` sees the thread for an event they drive and no other.
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
4. **Whose data, not just which data.** Every facet here answers *what kind*; none answers
   *about whom*. A co-parent wanting only their own child's calendar needs a subject axis.
   Deliberately deferred — but `own` is already a degenerate case of it, so the model should
   not be built in a way that forecloses it.
5. **Scope on the agent.** `agent_router` builds the family roster into every prompt and
   `_may_use_family_tools` keys on role. Both should consult scope; a `guest` should reach no
   agent tools at all. Worth its own slice.

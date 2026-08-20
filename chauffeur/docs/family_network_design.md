# Family Network — Access Scope, and the Household Boundary

Status: **DRAFT — nothing built.** Written 2026-08-20 to settle a question before code.
Companions: `docs/auth_design.md` (the tier spine this extends), `docs/kid_support_design.md`
(stages — the per-member override pattern this copies).

---

## 1. The question that started this

> *"There are different types of families. I have my family, my brother has his, and we
> are both part of my parents' family. I don't need the daily workings of his household,
> nor he mine. But his kids may want to chat with my kids, I may want to see moments from
> his kids' activities, we definitely want to battle each other's critters."*

Two candidate answers were on the table: (1) model extended family as a role that only
gets the social surfaces, or (2) a multi-family architecture where several households
live in one Chauffeur and share selected things.

**The answer is (1), and it is not a compromise — it is the whole problem.** (2) is
rejected on evidence, below. The social-federation ambition that motivated (2) is parked
with an explicit trigger, in §3.

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
`set_cached_schedule`, `set_cached_trips` all wipe the table before writing. The day a
second household exists, they silently delete each other's rows. This is not a query to
scope; it is a data-loss bug waiting for a tenant.

**b. Home Assistant is process-global.** The connection is resolved from `SUPERVISOR_TOKEN`
against `http://supervisor/core/api` (`services/ha_api.py:29-31`). Every `ha_person_entity`,
`notify_service`, `media_player_entity`, wall panel and voice satellite points into
*whichever single HA instance the add-on is running inside*. **A household column in the
database does not give another family a second Home Assistant.** They would have our
panels, our satellites, our person entities — or none at all.

Chauffeur is not a web app that happens to ship as an add-on. Half its value is welded to
one house's hardware. `docs/roadmap.md:792` already recorded the assumption — *"everything
assumes one family per install"* — and that assumption is correct. **Keep it.** What changes
is not the number of families per install; it is that a household may now have **guests**.

---

## 3. The social layer, and why it is parked

The things wanted across households — chat, moments, critter battles — are precisely the
**append-only, small, HA-free** things. That is not a coincidence; it is the same line as
"needs the solver" versus "is just a message." `pet_battle.combatant()` even says it out
loud: *"no member ids beyond a label, no storage handles… what makes the replay portable."*
Cross-house battles would be nearly free.

They are parked anyway, on a judgement the household made and should not have to re-make:

- Extracted from the household context, the social layer is **a worse WhatsApp with a worse
  photo album and a worse game.** None of it justifies an install.
- Engagement is fatally asymmetric. We open Chauffeur daily because it runs our life; a
  peer household would open it to check for a critter challenge. That dies in weeks, and
  then a dead wing must be maintained forever.
- **Federation is a multiplier, never a reason to adopt.** It pays only when two installs
  are each independently worth running. Exactly one exists.

**Trigger to revisit:** *a second household is independently running Chauffeur for its own
logistics.* Not before. If that day comes, start with critter battles (portable combatant +
seed, both sides compute an identical replay, level-matching already protects the younger
kid), and never let federated content reach the agent — `@argyle` routes any message to the
agent with tools and can set `schedule_dirty`, so a peer could otherwise drive our solver.

**The one genuinely unique cross-family capability does not need federation at all.**
Chauffeur knows there was a game on Tuesday, prompted for a moment, and knows who was
there — so it can assemble "what the grandkids did this week" with *zero effort from the
parents*. That is real mental load, borne today by one parent forever. But the unique part
is the **curation, not the container**: send it as email or text. For extended family,
Chauffeur should push outward through channels they already have, never pull them inward.
(Sketched here; not part of this arc's slices.)

---

## 4. The evidence that the real defect is scope

Three separate attempts to express *"this person sees less"* exist in the codebase, and all
three stalled:

1. **`capability_overrides`** (`models/schemas.py:189`) — ten switches, applied by
   `services/stages.py:169-185`. But `stages.can()` (`stages.py:188-192`) returns `True`
   unconditionally for anyone whose role is not `child`. **Adults have no per-person model
   at all.**
2. **`assist_tier`** (`schemas.py:167`, `household | assist`) — five references, and not one
   is an access decision. It is a load-ledger label ("covering is not carrying").
3. **`helper`** — has *no tier* in `services/auth.py`. `SIGNED_IN = {MEMBER, PARENT}`
   (`auth.py:50`) and every non-parent member resolves to `MEMBER` (`auth.py:468`), so every
   helper restriction today is UI-only (`app.html:867-897`) or a hand-written check in a
   single handler.

Three swings at the same missing abstraction is a signal the abstraction is missing, not
that it is unwanted.

---

## 5. The model: surfaces × reach

A member (or a panel) carries a **scope**: a map of surface → reach.

```
reach:  none  |  own  |  all
```

- `none` — the surface does not exist for them: hidden in the shell, refused at the API,
  excluded from every fan-out.
- `own` — only rows that are theirs: the drives they were assigned, the chores they hold,
  the rides they are a passenger on.
- `all` — the household's whole view of that surface.

Not every surface uses all three; `own` is meaningless for `meals` and is simply not
offered there. **`reach` is a set of named steps, not a rank to compare** — the same rule
`auth.py` holds for tiers, for the same reason: ranking forces a lie in one direction.

### The surfaces

Nine, chosen to be the smallest set a parent can reason about on a member card. Each maps
to a family of routes in the `auth.RULES` table.

| Surface | Covers | `own` means |
|---|---|---|
| `schedule` | calendar, events, drives, drive sheet, commitments, school/bus | my drives / my rides |
| `chores` | chores, routines, kid tasks, points, rewards, redemptions | the ones I hold |
| `meals` | meal plan, shopping lists | — |
| `chat` | the family channel and group threads | — |
| `moments` | the photo/video feed and event threads | — |
| `whereabouts` | family map, live locations, presence & status | — |
| `trips` | trip planning and trip boards | — |
| `house` | cars, music, announce, panels and boards | — |
| `pets` | critters and the arena | — |

**DMs are deliberately not a surface.** A direct message is a two-party consent question,
not a household view, and it stays available between members regardless of scope (subject
to the existing helper rules and, if kid-to-kid links are ever added, a parent-approved
allowlist). Making DMs a surface would let a scope edit silently sever a conversation.

**Admin is not a surface either.** Verifying chores, resetting PINs, editing config, and
flipping enforcement stay keyed on `role == 'parent'` via the existing `PARENTS` tier and
`require_parent_token`. Scope answers *what may you see*; role still answers *what may you
administer*.

---

## 6. Defaults — which must reproduce today exactly

Role supplies the bundle; the person overrides it. This is the stages pattern
(`stage → CAPABILITIES → capability_overrides`) lifted to the household.

| Role | schedule | chores | meals | chat | moments | whereabouts | trips | house | pets |
|---|---|---|---|---|---|---|---|---|---|
| `parent` | all | all | all | all | all | all | all | all | all |
| `adult` | all | all | all | all | all | all | all | all | all |
| `child` | own | own | all | all | all | own | all | none | all |
| `helper` | own | none | none | none | none | none | none | none | none |
| **`guest`** *(new)* | none | none | none | none | all | none | none | none | all |

**The load-bearing constraint on this table: shipping it must change nothing.** Every
existing member takes their role's row, and every row is written to reproduce the behaviour
the app has today. If a helper can see something today that the table says `none`, that is
either a bug this arc closes deliberately (§8) or a mistake in the table — and the audit
mode in §10 is how we tell which.

`guest` is the new role, and it is the answer to the question that started this: extended
family who want the social side and nothing else. Note what it is *not* — it is not a
"distant adult". A grandparent who wants the calendar is an `adult` with
`whereabouts: none`, or whatever that family actually decided. **The role is a starting
point; the household's real answer is the override.**

### The keeping-up adult

`templates/app.html:859-865` derives `isKeepingUpAdult()` — an adult with no driver and no
passenger record, "the grandparent two states away" — and shapes the shell from it, with no
server-side counterpart. That heuristic is retired by this model: it was guessing at a scope
nobody could state. The same person becomes an `adult` whose scope says what they see.

---

## 7. Where it is enforced

Two enforcement families, because there are two categorically different ways data leaves
the house. Both call one function:

```python
scope.reach(member_or_device, surface) -> 'none' | 'own' | 'all'
scope.can_see(member_or_device, surface) -> bool          # reach != 'none'
```

### a. Pull — the request guard

`auth.RULES` rows gain an optional fourth element, the surface they belong to:

```python
(ANY, '/api/chores*', WALL, 'chores'),
```

`_auth_guard` (`main.py:990-1029`) already runs on every request and already resolves the
member. It checks the surface in the same place it checks the tier. **This is the single
enforcement point for reads**, and it inherits three things already proven by the auth arc:
default-deny for unmatched routes, a test that fails on any unclassified route, and audit
mode.

Handlers whose surface resolves to `own` still do their own row filtering — the guard
cannot know which drives are yours — but the guard is what decides they may ask at all.

### b. Push — the fan-out audiences

Server-initiated sends do not pass through the guard. These filter rather than refuse, and
each must consult `can_see`:

- `services/presence.py` — `moment_push_audience` (currently `role in ('parent','adult')`)
- `services/family_digest.py` — digest and household-briefing recipients
- `storage.get_channels_for_member` (`storage.py:4904`) — currently a helper check only
- `main.py` message fan-out (`_fanout_message_notifications`) and `_notify_member_lanes`
- the watcher/sweep pushes (car readiness, care gaps, status protocols)

Roughly a dozen sites. They are enumerated in the slice plan rather than discovered later,
because the Argyle lesson applies exactly: *a rule left to each caller was honoured at one
site out of 57.*

### c. The shell is shaped by the same data, and never enforces

`applyRoleTabs()` (`app.html:867-897`) currently hides tabs by role. It hides by **scope**
instead, and the scope map is delivered with the member payload at sign-in — one source of
truth, computed server-side. A hidden tab has never been a security boundary and must not
start being one; §8 exists because it never was.

---

## 8. Two live holes this closes

Both verified 2026-08-20 and both are *why* enforcement cannot be layered on afterwards.

**`GET /api/channels/{id}/messages` (`main.py:11098-11102`) has no membership check.** It
verifies the channel exists and returns its messages. `list_channels` filters carefully;
the message read does not — so any caller holding a channel id reads that thread, DMs
included. Under this model the read requires the tier, plus `can_see(chat)` for
family/group channels, plus membership for `dm`/`group`. **A panel drawing a chat card is
served by its own `chat` reach (§9), not by an exemption** — which is the whole reason the
panel had to be modelled as an identity.

**`GET /api/family/locations` (`main.py:10896`) trusts a client-supplied `viewer`.**
`family_eyes = bool(viewer and storage.get_member(viewer))` — passing any valid member id
reveals a private-stage child's coordinates. The fix is not a new check: it is to derive the
viewer from `auth.acting_member()`, which S2 built for exactly this class of bug, and ignore
the client's claim whenever a token is present.

**Also fold in:** `POST /api/members` (`main.py:4850`) skips the role whitelist that `PUT`
enforces (`main.py:4869`), so a create can set any role string — including one no scope
table knows.

---

## 9. The wall panel is an identity, not an exception

A panel is `DEVICE` tier — *a place, not a person* — and it carries **its own scope map**,
stored on its `trusted_devices` row and edited where the device is managed.

This settles a question that has been fudged: the kitchen panel legitimately draws the
schedule and chores; a panel in a guest room or a workshop should not draw whereabouts. Any
model that treated "kiosk" as a blanket exemption would have to choose between blinding the
kitchen and exposing the guest room.

Panel defaults reproduce today's `WALL` behaviour: `schedule: all`, `chores: all`,
`meals: all`, `moments: all`, `house: all`, `trips: all`, `chat: all`, `pets: all`,
`whereabouts: all`. A parent narrows the ones they care about. **Reproducing today means a
panel that works this morning still works after the flip** — the failure this arc must not
cause is a wall going blank on a school day.

---

## 10. What stays separate, on purpose

- **`capability_overrides` / stages are NOT merged into scope.** A stage capability is about
  what a child is developmentally ready for; it changes on its own as they grow, and the
  household is told when it does. A scope is a standing decision a parent makes about a
  person and changes only when they change it. Different lifecycles, different vocabulary.
  They **compose**: a Navigator with `schedule: own` still gets `horizon_days: 13`.
- **`assist_tier` stays a ledger label.** It answers "does this person's work count in the
  household's split," not "what may they see." Recorded here so nobody later 'fixes' it into
  an access control.
- **`AssistContact` remains not an identity.** A contact is someone the household records,
  not someone who signs in. `helps_with` remains a picker filter and never a gate.
- **`status` (`active | disabled | archived`) is orthogonal.** Disabled revokes access
  entirely; scope describes what access *is* when you have it.

---

## 11. Rollout — audit first, same as S1

The auth arc's own playbook, and it earned its place: *flipping before the evidence exists
means discovering the panel cannot reach its board on a school morning.*

- **S1 — the model, dark.** `services/scope.py` with the surface list, the role defaults,
  `reach()`/`can_see()`. Nothing calls it. Tests prove the defaults reproduce today.
- **S2 — the two holes.** Membership check on the channel read; `acting_member` for the
  locations viewer; role whitelist on member create. These are correctness fixes and do not
  wait for the flip.
- **S3 — surfaces on the route table**, guard consults them in **audit mode**: records what
  it *would* have refused, refuses nothing. Runs until the record is boring.
- **S4 — the fan-out audiences.** These have no audit mode worth the name (a push not sent
  is invisible), so they land behind the same `enforcing()` flag with tests per site.
- **S5 — the shell**, driven by the delivered scope map; `isKeepingUpAdult()` retired.
- **S6 — the editor.** Scope on the member card in Config → People: nine rows, three states,
  the role's defaults shown as the baseline and overrides visibly marked as overrides.
  Panels get the same editor where devices are managed. **The hand path is the point** — a
  scope only an agent or a JSON edit can set is not a feature the household owns.
- **S7 — the `guest` role**, which is only meaningful once S3–S6 exist.
- **The flip** stays the household's act, on evidence, exactly as `auth_enforce` does.

Ordering note: this arc does not require `auth_enforce` to be on, and must not wait for it.
But it is worth saying plainly — **while enforcement is dark and `service_local_grace` is
on, scope is advisory.** The two together are the real deliverable.

---

## 12. What must be true (tests)

- Every route in `RULES` names a surface or is explicitly marked as not having one; a test
  fails on any route that names neither. (Extends the existing unclassified-route test.)
- For each role, the default scope reproduces the app's behaviour today — asserted per
  surface, not in aggregate.
- A `guest` reaches moments and pets and is refused all seven other surfaces, at the API and
  not merely in the shell.
- A member with `chat: none` receives no message push, appears in no digest audience, and
  gets no family channel from `get_channels_for_member`.
- A non-member cannot read a DM by id. A helper cannot read the family channel by id.
- `/api/family/locations` ignores a spoofed `viewer` when a token is present.
- A panel with `whereabouts: none` draws its board without locations and still draws
  everything else.
- Scope and stage compose: a Navigator with `schedule: own` keeps `horizon_days: 13`.

---

## 13. Open questions

1. **Does `own` need to exist for `moments`?** "Moments from events my kid was at" is a
   plausible grandparent scope, and it is the difference between a warm feed and a firehose.
   Deferred until someone wants it.
2. **Kid-to-kid DM links.** Out of scope while there is one household (siblings need no
   allowlist). It becomes required the moment a `guest` child exists.
3. **Does a `guest` belong in the family channel at all,** or does the household want a
   separate extended-family thread? The table says `chat: none` because a guest in the
   family channel changes what the family says in it. A second channel kind is the honest
   answer if it is ever wanted.
4. **Scope on the agent.** `agent_router` builds the family roster into every prompt and
   `_may_use_family_tools` keys on role. Both should consult scope, and a `guest` should
   probably reach no agent tools at all. Worth a slice of its own.

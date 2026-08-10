# The load arc — what the family carries, and who carries it

**STATUS: BUILT.** All six arcs shipped 2026-08-10, v2.146.0-v2.151.0; see roadmap.md for what was deferred. Design brief for the program of work. Six arcs, four new primitives, one
derived lens. Written 2026-08-10 against a code audit (not against the docs).

## The finding this is built on

Two sentences, both verified in code:

**The app models the family's work as driving, and anything not drive-shaped
has no home.** `Errand` requires `location` and `duration_mins`
(`models/schemas.py:813-814`) because an errand *is* a drive the solver
routes. So "sign the permission slip", "call the pediatrician", "renew the
passports", "$12 for picture day" cannot be represented anywhere. They become
a fake calendar event or nothing.

**The child's work is fully modelled and the adult's work is not modelled at
all.** Kids get `KidTask`, chores with claims and verification, routines with
streaks, a points ledger, status tiers and a celebration engine. Adults get
`Errand`. `assigned_to` / `assignee` / `owner_member` return **zero hits
repo-wide**, so nothing an adult owns can be handed to the other adult.

That is backwards, because the mental load is the adults'. Today the app
automates the household's *noticing* superbly — ten proactive lanes, watchers
with once-only markers, occasion gap reports that diff against last year — and
offers nothing for the *doing and the dividing*. It is an excellent secretary
for a family whose only work is driving.

A third finding, from the outlets question, belongs up here too: **an adult's
own life currently exists in this app only as an obstacle.** A personal
calendar event's entire function is to make you unavailable to drive. There is
no concept of your time being *for* something. That is the thing to flip.

## The primitives

Everything below hangs off four new objects and one read-only lens. Keeping
the object count this low is deliberate — the audit's real lesson is that the
app has plenty of machinery and too few nouns.

| Primitive | What it is | Why it must be new |
|---|---|---|
| `HouseholdTask` | work with a deadline and no destination | `Errand` is a drive; a task with no place cannot be one |
| `Request` | an ask with a state, from anyone to anyone | today an ask is either free text or a silent override |
| `AssistContact` | someone outside the house who does work for it | `helper` is an external person *with* app access; a contact has no account at all |
| `Stage` | the developmental band a child is in | `role == 'child'` is currently the entire model |
| **the load ledger** | a lens, not a table: who is carrying what | reads all of the above; states, never scores |

## Covering is not carrying

One cross-cutting property, discovered by asking where a teenage driver
belongs (2026-08-10). The observation was that a teen who drives is more like
a carpool parent than like a second adult: **they can be assigned a drive and
it is covered — the difference is that they have the app and can use the
driving tools.**

That is exactly right, and it generalises past teenagers. There is already a
third case with the same shape: the `helper` role — a hired driver or nanny
who has the app, sees driving surfaces only, and is not family. So the app has
**three kinds of driver on one axis**, which is how much of the app they hold:

| Kind | Has the app? | Assigned how? |
|---|---|---|
| `AssistContact` | no — a contact | recorded; the solver is *told* |
| `helper` (hired driver, nanny) | driving surfaces only | assignable; solver-eligible |
| `Copilot` teen | driving surfaces **plus** their kid lens | assignable; solver-eligible only if allowed |

And all three share one property that the household drivers do not have:

> **They cover the drive. They do not carry the load.**

**The tier belongs on the MEMBER, not on `Driver`** — corrected 2026-08-10,
and the correction matters more than it looks. *"Assisting is not a
driving-specific thing"*: a teenager can cook a night, a nanny can supervise
homework and fold laundry, a grandparent might cook Sunday dinner and never
drive at all.

Putting `household | assist` on the driver record would have re-committed the
exact sin this whole brief is about — attaching a general idea to driving
because driving is what the app happens to model. And it would have leaked
immediately: a teenager who cooks three nights a week would have made the
parents' split look even, because only their *drives* carried the tier.

So it is a member-level property, and it reads the same across every kind of
contribution — a drive, a cooked meal, a completed task, a claimed chore:

> **This person helps. Their help is not the household's load.**

**The tier does exactly one job: load accounting.**

- **Excluded from the load ledger** — every kind of contribution, not just
  drives. If a teenager drives six times and cooks twice, the ledger must not
  report the household as evenly split. The same protection applies to a hired
  driver, which is a bug waiting to happen today: the weekly digest prints
  per-driver drive counts sorted descending, and a nanny's ten runs currently
  make the week look shared.
- **Excluded from the solver's load-balancing term**, exactly as ghost drivers
  already are (`solver/matcher.py:1056`).
- **Coverage still counts.** No `needs a driver` flag, no ghost route, no
  watcher alarm. Work an assist member holds is handled.

An earlier draft also hung *"not auto-assigned by default"* and *"hard rather
than soft constraints"* on the tier. **That was wrong** for the same reason:
they are not properties of being a teenager or a helper, they are ordinary
things anyone might want. See the next section. What remains teen-specific is
only the **defaults** and **who holds the pen** — authority, not capability.

The teen keeps their `child` role and their whole kid lens — becoming useful
is not a reason to be deleted from the family. What the Copilot stage unlocks
is the **driver surfaces** (the Drives tab, start/complete route, the driver
chat agent, leave-by), which the passenger shell hides today. That is precisely
what stage capability flags are for.

There is also a nice social result: driving your sister to practice lands as
being **trusted**, not as being enrolled in the chore economy — which is what
should replace points at that stage anyway.

## Three layers of "no"

Prompted by the obvious question (2026-08-10): *why should a radius, a
passenger cap and a time ceiling be teen constraints — why can't adults
customise their availability the same way?* They can, they should, and framing
them as teen features was the error. Chasing that produced three genuinely
different kinds of "no", which had been collapsed into one thin driver record.

### 1. Commitments — where you already are

School hours, a job, a standing obligation. These are **facts, not
preferences**, they block *everything* rather than driving specifically, and
they are how a teenager with school and a shift, or a parent in the office
Tuesdays, is actually described.

Half of this already exists: `FamilyMember.school_hours_start/end` is a
member-level field driving the dismissal push and the bus lines. It has never
been fed to the solver, because until a Copilot drives, no child was a driver.
The moment one is, their school hours obviously have to block driving.

**Keep them typed rather than folding them into generic windows**, for three
reasons that all bite:

- **They suspend.** A5 already computes school closures and half days. A
  closure has to vacate school hours, and it cannot reach a generic
  unavailability window. The same is true of a job at a holiday.
- **Other features read them.** School hours are not only a blocker — the
  dismissal push, the bus layer, and the aftercare window are all built on
  them.
- **They are somebody else's schedule.** You do not get to prefer your way out
  of the school day.

### 2. Availability — when you'll take work

**Universal, not assist-specific and not driving-specific.** A parent saying
*"I'm free to be given things Tuesday evenings"* and a teenager saying the same
are one object. Several windows, each with days, a time range and a strength.

Effective availability is the obvious composition, stated explicitly because it
is easy to get backwards: **unavailable = outside every window ∪ inside any
commitment.** You are available when you are inside a window *and* not
committed.

**Strength is the real axis, not age.** Today preferred hours are a single
−2,000,000 soft penalty, which is right for *"I'd rather not drive after nine,
but I will if I'm the one at the event"* and wrong for *"I legally may not."*
Both sentences exist for adults:

| | Preference (soft, tradeable) | Limit (hard, never crossed) |
|---|---|---|
| Time | I'd rather not do the late run | I can't drive after my eye appointment |
| Radius | Keep me near home if you can | Not across the county on a school night |
| Passengers | — | Two car seats are in; four kids don't fit |

**Opt-in is a single switch, and the windows are its scope.** An earlier draft
asked whether auto-assign wanted to be per-window; that question was
redundant. *"Yes to the 4pm practice run, no to anything else"* **is** a window
— 15:30 to 17:30 on the days practice happens. Opt-in says *the solver may
volunteer me*; the windows say *when*. Nothing further is needed. The other
dimension people reach for — *"yes to my kids' runs, no to grocery errands"* —
is not a time question and already has homes: routing `Rule`s for events,
`Chore.eligible_member_ids` for the pot, and direct assignment for tasks.

### 3. Driving constraints — what a drive may look like

The genuinely drive-specific residue, on the driver profile:

- **Radius, measured in drive minutes** (settled 2026-08-10). The travel cache
  already speaks in minutes, and forty minutes of traffic is the thing a person
  is actually refusing — not a distance on a map.
- **Passenger cap** — physical, so effectively always a limit.
- **After dark, anchored to sunset rather than a clock.** How both a nervous
  driver and most graduated-licence rules actually think, and darkness moves
  about ninety minutes across a school year. `sun.sun` is already read for the
  panel theme.

**A per-weekday window plus a radius is most of a work model** — *"Tuesday I'm
in the office forty-five minutes away; Wednesday I'm home"* — and with typed
commitments alongside it, the A5 finding that the app has no concept of work
closes without an employment entity.

One correctness note for the rebuild, from the audit: the current check fires
when the **event** starts before `preferred_start` or ends after
`preferred_end` — the *drive* is not considered, so a 9:00 event with an 8:30
leave-by does not violate a 9:00 window. Windows must be evaluated against the
drive, travel and buffer included, which is what the person actually agreed to.

### So what is still teen-specific?

Two things, and neither is a capability:

1. **Defaults.** A Copilot ships with limits already set — a time ceiling, a
   passenger cap, a radius — because the licence says so. An adult's ship
   empty.
2. **Who may edit them.** A teenager must not raise their own ceiling; a parent
   holds the pen. An adult sets their own.

## What each thing is for

| | Job | Lives on |
|---|---|---|
| **entity** | member, or a contact we only record | — |
| **role** | what of the app you can reach | member |
| **stage** | which kid surfaces you get | member (children) |
| **tier** | does your contribution count as household load | member |
| **commitments** | where you already are | member |
| **availability** | when you'll take work of any kind | member |
| **driving constraints** | what a drive may look like | driver profile |

Six of the seven are member-level, which is the point: only the last one is
about driving, and it is the only one that should be.

---

# A1 — Outside hands

**Ship first.** Smallest, immediate relief, and it teaches the codebase the
idea of *coverage that isn't ours* — which A5 then reuses.

## The problem

Carpool is how families actually cover, and the app cannot see it. A
carpool-covered event today is either assigned to a family driver (a lie the
solver then plans around) or left unassigned — which fires the watcher DM
`🚨 No driver yet` at both parents for a ride that was always handled. And
when you need the driver at 4:40 on a Tuesday, her number is in a text thread
from August.

**And it is not only carpool** — corrected 2026-08-10, after the tier moved to
the member. The neighbourhood girl who comes to do the dishes and the cleaning
has no place in this app at all, and her work is recorded nowhere. That is the
same sentence as the carpool one, and it is the thesis of this entire brief
pointed at its own first draft: *household work is being carried, and the app
cannot see it.*

So the noun is not `CarpoolDriver`. Carpool is a **kind of help**, not a kind
of person.

## The model

`AssistContact` — `{id, name, phone, email?, relation_label, kinds[],
relationship, color_code, notes, active}`.

- `relation_label` is how the family actually refers to them: *"Emma's mom"*,
  *"the Kellys' daughter"*.
- `kinds` is a free tag list — `carpool`, `housework`, `childcare`,
  `tutoring`, `pets`. **Nothing branches on it.**
- `relationship` is `reciprocal | paid | volunteer`, and it earns its place
  below.

**Not a `FamilyMember`.** No login, no PIN, no headcount, no wall board, no
DMs. They are a contact precisely *because* they have no account — which is
also the clean line against the existing `helper` role, an external person who
**does** hold the app. Three points on one axis: a contact we only record, a
`helper` with driving surfaces, a full member. If a contact ever needs the app
they are promoted to a `helper` member, and **their history must survive the
promotion** — the record of what they covered belongs to the household, not to
the row.

**Contacts are `assist` by definition.** The household/assist tier is a real
choice only for *members* (a teenager, a nanny with the app). Nobody outside
the house is ever household load.

### The discipline: never branch on `kinds`

The tags are for humans — filtering a list, answering *"who could take this?"*
Behaviour comes from **what references the contact**, not from what they are
labelled. A contact referenced by a drive is functioning as a carpool driver; a
contact referenced by a chore or a task is functioning as house help. Branch on
the tag instead and every new kind of help becomes a code change, which is
exactly the trap this brief keeps walking the app out of.

**Coverage is a third assignment state**, alongside assigned-to-a-household-
member and unassigned. To the solver a covered event is **covered** — not
assignable, not unassigned, not ghost-eligible. It leaves the optimisation
entirely, which is the whole point: outside help *removes* load, and today the
app cannot be told that.

The same false alarm exists off the road and gets the same fix: a chore or task
the neighbour is coming to do on Saturday should not sit in the pot looking
unclaimed, nag the family, or reach the past-due watcher.

## Should we store them, or just type a name?

**Store them.** A free-text name gives you a label and nothing else. Storing
gives you three things a label cannot: they repeat (the same soccer carpool all
season, the same girl every other Saturday), the phone number is the entire
value in the moment you need it, and only a stored contact lets the rest of the
app stop treating the work as open.

## Surfaces

- **Schedule timeline** — a distinct chip in the driver's colour, their name
  on it, visibly not one of our lanes.
- **Tap → contact sheet** — call and text via `tel:` / `sms:`. No SMS
  integration, no external messaging, no accounts for them.
- **Kid digest and My Day** — `🚗 Riding with Emma's mom`. This is exactly the
  certainty the kid arc exists to sell, and it is invisible today.
- **Wall panel** hero and drives tile.
- **Coverage report and the unassigned watcher** — carpool-covered events stop
  counting as needing a driver. This alone removes a recurring false alarm.
- Contact controls are a **parent** surface, not a kid one.

## Slicing

The entity generalises now; the **coverage machinery arrives one kind at a
time**, because that is where the real work is. Generalising the noun costs two
extra fields. Generalising every surface at once is how a small shippable slice
becomes a platform.

1. **The contact book plus drive coverage.** The third assignment state, the
   timeline chip, the contact sheet, the digest line, the watcher exclusion.
2. **The turn ledger** (below).
3. **Chore and task coverage** — the same "covered, not ours" state applied to
   the pot and to `HouseholdTask`, which wants A2 to exist first.

## Slice 2 — the turn ledger, and why `relationship` exists

Reciprocity is what makes a carpool work socially, and remembering that you owe
a turn is classic invisible labour. Each covered event records who did it; each
one *we* take for the same group records our turn. Then:

> Soccer carpool — you've driven 2 of the last 9.

and, inside the lead window, *"you haven't taken a soccer turn since April."*
**Stated, never scored** — the `occasions._load_balance` voice
(`services/occasions.py:715-763`), which counts and names and deliberately
never ranks.

**This is exactly why `relationship` is on the contact.** You owe a carpool
parent a turn; you do not owe the girl who does the dishes a turn, you owe her
money. Turn-taking fires for `reciprocal` and stays silent for `paid`.

To be clear about a line already drawn: this is **not** a reversal of the money
cut. We record that a relationship is paid so the app knows which nudges make
sense. We do not track amounts, rates, or what is owed.

Group membership starts **derived** from the work's matching tag rather than as
a new entity. Promote it to a real group object only if the derivation proves
inadequate.

## Explicitly out

Other-family accounts, shared calendars with them, invitations, SMS/email
integration, cost splitting. Multi-household remains a non-goal; a carpool
driver is a **contact**, not a user.

---

# A2 — Household work: tasks, assignees, whose turn

**The keystone.** Most of the remaining value is downstream of this object.

## The model

`HouseholdTask` — `{id, title, notes, due_date?, assigned_to?, created_by,
status: open|done, completed_at, completed_by, recurrence:
none|daily|weekly|monthly|yearly, category, links: {occasion_id?, member_id?,
event_id?, list_id?}, effort_mins?, source: manual|agent|intake|ics}`

Three decisions worth defending:

**Task = do something. Errand = go somewhere.** Crisp, and it keeps the solver
clean: "renew the passports" must never become a routing job competing for a
Tuesday slot.

**`assigned_to` is optional, and unassigned is a real state** meaning *the
household owes this*. That is where delegation and whose-turn live. An object
that forces an owner at creation just moves the deciding back onto whoever
typed it.

**Yearly recurrence, which errands lack** (`daily|weekly|monthly` only).
Annual is precisely the life-admin cadence: inspection, physicals, passports,
registration windows.

## The intake unlock

Today approving an intake proposal can produce a calendar event, an errand
(which demands a location), or a `KidTask`. A permission slip due Friday fits
none of them. Adding household task as a fourth target is a small change to
the approval router (`main.py:3153-3268`) with an outsized payoff: the capture
layer already reads this mail correctly and has nowhere to put it — the
extraction prompt literally names *"permission slip due, payment due, picture
day"* (`services/email_ingest.py:192`) as targets it should find.

## The load ledger

A read-only lens over completed tasks, drives driven, prep and cook events,
and occasion errands. The presentation rule is inherited whole from occasions
O3 and is not negotiable:

> **State it, never score it.** No percentages, no leaderboards, no charts, no
> "you're at 70% this month." Sentences: *"Eleven of the fourteen jobs for
> Thanksgiving are Lorena's."*

Adults need division of labour, not gamification. The roadmap already cut
solver-assigned chores and points-for-routines for reasons that apply harder
to adults, and a fairness chart between two spouses is a fight generator, not
a feature.

**Whose turn** for recurring tasks: remember the last completer, surface the
turn, never enforce it.

## Surfaces

Adult My Day, a wall-panel tile, the weekly digest, watchers (past-due, and
unclaimed-as-the-due-date-nears), and agent tools in **both** stacks —
`add_task`, `list_tasks`, `claim_task`, `assign_task`, `complete_task` — each
with the hand path the standing rule requires.

---

# A3 — Requests: the ask as a first-class object

Two problems that are the same shape.

**A kid can report but cannot ask.** Kid-as-sensor handles facts well
("practice moved", "I need $12 by Friday") and routes them as parent-approvable
cards. There is no object for *"can you get me at 3 instead of 4"* — the single
most common kid-to-parent logistics message — so it exists only as free text.

**An adult who wants out of a drive can only take it from their partner.** The
override lands and the other parent gets a bare *"Schedule Updated Today"*
push with no indication it was an ask. That is socially terrible, and it is a
large part of why the non-driving parent feels informed-at rather than
invited.

## The model

`Request` — `{id, from_member, to_member?|household, kind:
ride_change|pickup_early|swap_drive|take_task|cover_evening|permission,
subject_ref, body, status: open|accepted|declined|expired, decided_by,
decided_at, expires_at}`

One object for both halves because the state machine, the surfaces and the
notification rails are identical — and because a teen asking for a ride and a
mother asking for Thursday evening then ride exactly the same rails.

Properties that matter:

- **A request is always answered.** Silence is the failure mode this exists to
  fix; expiry carries a nudge rather than a shrug.
- **Accepting performs the change.** The request *is* the mechanism, not a note
  about one — accepting a swap reassigns the drive.
- **Declining is first-class and blameless.** A decline with a reason ("I'm in
  a meeting until 5") beats silence every time.
- Kid requests route through the existing K3 proposal-card machinery rather
  than a parallel copy of it.

This is the connective tissue for the whole program: it serves the teenager,
the parent asking for an outlet, and the parent who would rather be *asked*
than *informed*.

---

# A4 — Stages: the child that grows

## The problem

`role == 'child'` is the entire model. There is **no birthdate, DOB, age or
grade field anywhere**, and nothing in the codebase branches on a child's age.
A six-year-old and a sixteen-year-old get the identical 64px-glyph Buddy card,
the identical `Hi James! 👋`, the identical points economy and the identical
tone. The only exit is a manual role flip to `adult`, which silently deletes
the kid lens in one move.

With a seven-year spread in this house, that is not a rounding error — it is
the difference between a surface a child loves and one a teenager is
embarrassed by.

## The model

`birthdate` on `FamilyMember` yields a **suggested** stage; `stage_override`
lets a parent pin it; and individual capability flags override the bundle, so
a mature eleven-year-old can hold request rights without being aged up
wholesale. Kids differ, and a single number should not be destiny.

Four stages, named for **what changes**, not for how old you are:

| Stage | Roughly | What is true |
|---|---|---|
| **Sprout** | 4–7 | pre/early reader. Glyph- and photo-led, one thing at a time, today only, parent-mediated. |
| **Explorer** | 8–11 | reads, checks off, and the points and streaks land honestly. This is today's Buddy UI, well tuned for exactly this band. |
| **Navigator** | 12–14 | points start to read as babyish. Wants to be trusted and to know the plan. Density up, glyphs down, streaks opt-in, request rights on, week horizon. |
| **Copilot** | 15–18 | a real schedule, own commitments, a job, driving. The points economy retires; responsibility replaces it — assignable household tasks, driving siblings, owning errands. |

**The switch list** — small and explicit, so that no surface ever has to know
a birthday: shell density · glyph scale · points and streak visibility ·
horizon · initiation rights · privacy · responsibility · digest time and
channel.

## Two rules for the transition

**Growing up is granted, never silently switched.** A stage change is
announced and parent-confirmed, and the new capabilities are named out loud —
*"Ellie can now ask for a ride change herself."* Earned, rather than the app
quietly getting different.

**Nothing is deleted when a child moves up.** Points history, streak records,
tier badges: retained, just no longer the point. The current role-flip
behaviour — where growing up erases the evidence that you were ever six — is
the exact opposite of what a family wants.

## Load awareness, which is the anti-stress feature

The app can already see that Tuesday is school plus two activities plus a test
due, and says nothing. Stage-aware:

- Sprout / Explorer → tell the **parent**.
- Navigator / Copilot → tell **them**, and offer to break the project into
  staggered tasks. The kid agent already offers precisely this and only adds
  them on a yes (`services/agent_router.py:194-197`).

## The boundary, stated as a rule

**No mood tracking, no journaling, no sentiment scoring, no wellbeing
dashboard.** We are not qualified to build that, and a family logistics app
pretending to be therapeutic is worse than one that does not try.

What we *can* do honestly: notice schedule-driven overload, give the kid a
private channel that is not the family group chat (the Argyle DM already is
one), and one structured, opt-in, low-frequency way to signal *this week is
too much* — which reaches a parent as **load**, not as a transcript. Same lens
the presence arc already locked: **health is a scheduling problem, not a
content problem.**

## Privacy has to grow too

A Copilot's messages and location should not be as open as a Sprout's. Today
`/api/family/locations` returns every member's coordinates with no auth
(`main.py:6934`) and every child can read every other child's points balance
(`main.py:4122`). Both are fine for a house of small children and wrong for a
sixteen-year-old.

## The teen and the wheel

A Copilot who drives becomes a `Driver` on the **assist** tier while remaining
a `child` member — see *Covering is not carrying* above. The stage unlocks the
driver surfaces; the tier keeps their drives out of the adults' ledger; the
role keeps their kid lens intact.

Two things follow that are worth stating plainly. Their drives must show up in
a sibling's digest in the family's own voice — *"🚗 James is driving you"* is
warmer and truer than naming a driver record. And the household must never be
told it is evenly split because a sixteen-year-old absorbed the week.

---

# A5 — The dual-income safety net

The app knows school is closed. It knows both adults' calendars — it reads
them for scheduling. It never computes the intersection, and that intersection
is the highest-drama moment in a two-income household.

## 1. School days get kinds

`school_in_session` is boolean today, and timed events are explicitly ignored
(`services/school.py:128`), so a two-hour early release is either a full
closure or completely invisible. Add `full | half | closed | delayed`, parsed
from the same calendar with the same fail-open discipline. **Half days are the
sneaky ones** — nobody has PTO booked for a half day.

## 2. Aftercare as a care window

Zero hits today for aftercare, extended day or latchkey — and it is the actual
fallback most two-income families use. Per kid: place, days, end time. The
effect is that the pickup deadline moves from `school_hours_end` to the
aftercare end, which widens the solver's window and converts genuinely
uncoverable events into covered ones. The dismissal push can then tell the kid
the truth: *"you're in aftercare today, Mom gets you at 5:30."*

Out: cost, sessions, billing. We do not model money.

## 3. Childcare gap detection

For every day in a **21-day** horizon — closures are known weeks ahead and PTO
needs lead time, so the 3-day watcher window is far too late — school not full
**and** every caregiving adult unavailable produces a gap.

Surface it as a **decision with a growing cost**, reusing the occasions O3
`_open_decisions` pattern, with a named shortlist: one adult takes the day, a
helper, a carpool family, aftercare extension. Not an alarm — a decision with
a deadline and options.

## 4. The work model, answered cheaply

The audit's other dual-income finding was that the app has **no concept of
work at all**: a job exists as opaque calendar busy-time plus one
`preferred_start`/`preferred_end` pair that covers Monday and Saturday alike.
No work-from-home versus in-office distinction, no shifts, no commute — which
for a hybrid worker is the entire question.

This does **not** want an employment entity. Typed **commitments** plus
per-weekday **availability windows** plus a radius — see *Three layers of "no"*
above — express it directly: *"Tuesday I'm in the office forty-five minutes
away; Wednesday I'm home."* Shift work falls out of the same model, and so does
a teenager with school and a job.

It also sharpens the gap detection two paragraphs up. "Every caregiving adult
unavailable" currently has to mean *has a calendar event*, which is a guess.
With commitments modelled it means something real, and the false positives
(a calendar hold that is not actually work) and false negatives (a job that
was never on a shared calendar) both shrink.

## 5. Two implementation-versus-doc gaps that belong to this arc

- `clear_deck` and `give_space` have **no solver effect**
  (`services/status_protocols.py:411-412`) despite the design doc promising
  the solver protects that evening. A6 gives them their teeth.
- The status→solver unavailability injection runs a **14-day** horizon
  (`main.py:9531-9532`) against a 30-day build horizon, so a cover day 20 days
  out is announced to the whole family while the solver still schedules that
  parent for it.

---

# A6 — Outlets, and the parent who isn't driving

The hardest design problem here, and two people to serve: the parent who needs
an outlet and cannot get one, and the parent who wants to be included and pick
up slack but cannot see what is open.

**The principle, and it is the whole arc: an outlet is a scheduling problem,
not a content problem.** The app cannot make anyone rested. It can make sure
the time exists, is defended, and is *covered*.

## 1. Protected commitments

Mark a recurring personal thing — a run club, therapy, choir, a standing
coffee with a friend — as protected. The solver already knows how to keep
someone free; the difference is that the system now **defends** it and notices
when it erodes. This is where `clear_deck` and `give_space` finally do
something.

## 2. Erosion watch

> You've missed your Thursday run three weeks running — every time it was a
> drive.

That sentence is the feature. It is the invisible thing nobody tracks, the
data is already in the schedule history, and it follows the ledger rule:
stated, never scored.

## 3. Coverage is what makes an outlet real

A protected commitment can declare **needs coverage**, which flows into the
same machinery as a status day: the other adult gets a real coverage report
and open drives get flagged. Wishing for time does not produce time. Covered
time does.

## 4. The recovery beat

After a heavy stretch — five days solo, a hosted holiday, a sick week —
*propose* the outlet instead of waiting to be asked. The status-protocol beat
engine already does time-shifted, audience-aware proposals and this is its
natural second customer.

## 5. The household briefing

**The best value-per-line in the entire plan**, and the direct answer to
"tools to be included and engaged and pick up more of the slack."

Today the tomorrow digest is **per-driver** and shows only your own drives
(`main.py:385-436`), so the non-driving parent learns the day changed by
happening to look at a screen. Replace it with a briefing every adult gets:
tomorrow for the whole family, what is covered, what is open, what needs a
decision, and what is on their partner's plate.

The rule that keeps it from being a nag:

> **It shows openings, not assignments.** *"Two things are open tomorrow:
> James at 4, and the permission slip is due."* Tapping takes it.

That converts awareness into action without anyone having to ask — which is
the real mechanism, because the hard part of picking up slack is not
willingness, it is **visibility**.

## 6. Quiet hours, on the identity

The kid quiet-hours machinery is thorough (`family_digest.in_kid_quiet_hours`,
honoured at eleven call sites) and has no adult counterpart at all; adults can
be pushed at any hour by schedule changes, pending drives and capture prompts.

**It belongs on the member, not in household config** — decided 2026-08-10 —
and the reason is a real difference in kind, not just in schedule:

> **Kid quiet hours are a protection, set for someone by someone else. Adult
> quiet hours are a preference, owned by the self.**

Different ownership means a different home. A household window would also
serve nobody in a house with a night-shift parent and a six-a.m. riser, and
the `helper` case is starker still: a hired driver should not be pinged at ten
at night about tomorrow's run. This lands on the member's own card, which is
where the config-decentralisation rule wants it anyway.

Four details that keep it honest:

- **Absent means the household default, never "off".** The exact trap the
  screensaver settings hit — an unset window must resolve to a default
  (21:00–08:00, matching the constants this replaces), not to no protection at
  all. It also retires two hardcoded magic numbers,
  `watchers.QUIET_END_HOUR` / `QUIET_START_HOUR`.
- **Urgency escapes.** A 5:30am departure push has to fire at 5:10 even inside
  a window that runs to eight, or the first night-shift parent misses a drive.
  Time-critical lanes (leave now, a drive reassigned today) escape; digests,
  watchers, capture prompts and nudges respect the window.
- **Skip versus defer stays per-lane.** Time-sensitive sends *skip* — a stale
  on-the-way push is worse than none. Watcher findings already *defer* to the
  next morning sweep, which is correct for them. Do not flatten these into one
  rule.
- **Merge with the stale roadmap item.** "Per-member notification preferences"
  (members with both web push and HA notify get everything twice) has been on
  the backlog since 2026-07-31. It is the same block on the same card: *how*
  and *when* I want to be reached. Build them together and close both.

## 7. Social, honestly scoped

People outside the household who matter — the friend nobody has seen since
March. Reuse the `AssistContact` shape: a name, a number, no account.
The features are exactly three: **protect the time, remember the person,
notice the lapse.**

Not a social network. No feed, no invitations, no external messaging.

---

# Sequence, and why

1. **A1 outside hands** — smallest, immediate relief, teaches the codebase
   "coverage that isn't ours", and lands kid-visible value in week one
   (*"Riding with Emma's mom"* is pure kid-arc certainty). The entity is
   general from day one; drive coverage ships first and chore/task coverage
   follows A2.
2. **A2 household tasks** — the keystone primitive; everything downstream.
3. **A3 requests** — small, and unblocks both the teenager and the adult ask.
4. **A5 dual-income net** — rides on A2's task object and the decisions
   pattern.
5. **A4 stages** — the largest UI surface; do it once `Request` exists so the
   Navigator's new rights have something to be.
6. **A6 outlets and the briefing** — richest, and wants the ledger and
   requests already in place.

The kid arc is not being made to wait for slice 5: A1 and A3 both deliver
into it first.

# The rules of this program

- **State it, never score it.**
- **Openings, not assignments.**
- **A request is always answered.**
- **Growing up is granted, never silently switched.**
- **Nothing is deleted when a child moves up.**
- **Health and outlets are scheduling problems, not content problems.**
- **Task = do something. Errand = go somewhere.**
- Every agent capability ships with a hand path.
- Inside quiet hours: skip, never defer.

# Explicitly out (with reasons — don't relitigate casually)

- **Mood tracking, journaling, sentiment scoring, wellbeing dashboards.** Not
  qualified; a logistics app pretending to be therapeutic is worse than one
  that does not try.
- **Points or gamification for adults.** Division of labour, not a game —
  extending the existing cuts on solver-assigned chores and points-for-routines.
- **Money**: aftercare billing, carpool cost-splitting, allowance. Consistent
  with the existing money cut.
- **Other-family accounts / multi-household.** Assist contacts are contacts,
  not users; multi-family stays the acknowledged non-goal. A contact who
  genuinely needs the app becomes a `helper` member instead — that path exists
  and keeps their history.
- **External messaging** to carpool parents. `tel:` and `sms:` links only.
- **Grades.** The kid arc's line holds: due dates and events, never grades.
- **Gift secrecy** stays blocked until `hidden_from` is designed properly —
  storage, every list surface, the digest, the kiosk and both agent stacks.
  Not part of this program.

# Open questions

- Carpool turn grouping: derived from the event's matching tag, or a real
  `CarpoolGroup` entity? Start derived; promote only if it fails.
- Do half-days need a per-kid override, given siblings at different schools
  with different calendars?
- Does an assist member's availability need to say **what kind** of help they
  will take — drive, cook, task — or is per-kind eligibility already covered
  where that work lives (`Chore.eligible_member_ids`, task assignment, having
  a `Driver` record at all)? Leaning: already covered, and a capability matrix
  would be the kind of noun this brief exists to avoid.
- A job has holidays and leave the way school has closures. Model them, or
  accept that a commitment you are not actually at is a soft cost the calendar
  can override?
- One screen or two: commitments, availability and quiet hours are the same
  sentence from the person's side — *how and when to use me* — and the driving
  constraints are the only part that belongs somewhere else.

**Answered 2026-08-10.** A teen who drives keeps their `child` role and kid
lens and carries the `assist` tier — which sits on the **member**, not the
driver record, because assisting is not driving-specific (a teenager can cook a
night; a nanny can supervise homework). The tier does load accounting and
nothing else. Quiet hours live on the member's identity, because a preference
owned by the self belongs somewhere different from a protection set by someone
else. Availability is universal and lives on the member as several windows with
days and a strength; opt-in is one switch whose scope IS those windows, so
per-window consent needs no extra mechanism. School and job hours are typed
**commitments**, not windows, because they suspend (closures, holidays) and
other features already read them. Radius is measured in **drive minutes**.

# The load arc — what the family carries, and who carries it

Design brief for the next program of work. Six arcs, four new primitives, one
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
| `CarpoolDriver` | a driver who is not in this household | `helper` is an internal hired person *with* app access |
| `Stage` | the developmental band a child is in | `role == 'child'` is currently the entire model |
| **the load ledger** | a lens, not a table: who is carrying what | reads all of the above; states, never scores |

---

# A1 — The carpool book

**Ship first.** Smallest, immediate relief, and it teaches the codebase the
idea of *coverage that isn't ours* — which A5 then reuses.

## The problem

Carpool is how families actually cover, and the app cannot see it. A
carpool-covered event today is either assigned to a family driver (a lie the
solver then plans around) or left unassigned — which fires the watcher DM
`🚨 No driver yet` at both parents for a ride that was always handled. And
when you need the driver at 4:40 on a Tuesday, her number is in a text thread
from August.

## The model

`CarpoolDriver` — `{id, name, phone, email?, relation_label, kid_names[],
color_code, notes, active}`. `relation_label` is how the family actually
refers to them: "Emma's mom".

**Not a `FamilyMember`.** No login, no PIN, no headcount, no wall board, no
DMs — they belong to another household. The `helper` role is the opposite
thing (an internal hired driver *with* app access), and conflating them would
put another family's parent on the kitchen kiosk.

**Coverage is a third assignment state**, alongside assigned-to-a-family-driver
and unassigned: `carpool_assignments: {event_id: carpool_driver_id}`. To the
solver the event is **covered** — not assignable, not unassigned, not
ghost-eligible. It leaves the optimisation entirely, which is the whole point:
a carpool drive *removes* load, and today the app cannot be told that.

## Should we store them, or just type a name?

**Store them.** A free-text name gives you a label and nothing else. Storing
gives you three things a label cannot: they repeat (the same soccer carpool
runs all season), the phone number is the entire value in the moment you need
it, and only a stored driver lets the solver stop scheduling us.

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

## Slice 2 — the turn ledger

Reciprocity is what makes a carpool work socially, and remembering that you
owe a turn is classic invisible labour. Each carpool-covered event records who
drove; each event *we* drive for the same group records our turn. Then:

> Soccer carpool — you've driven 2 of the last 9.

and, inside the lead window, *"you haven't taken a soccer turn since April."*
**Stated, never scored** — the `occasions._load_balance` voice
(`services/occasions.py:715-763`), which counts and names and deliberately
never ranks.

Group membership starts **derived** from the event's matching tag rather than
as a new entity. Promote it to a real `CarpoolGroup` only if the derivation
proves inadequate.

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

A Copilot who drives should become a `Driver` **while remaining a `child`
member** — that is the entire reason for not flipping the role. The graduated
licensing cap already exists as `Driver.max_passengers`
(`models/schemas.py:74`) and has never had a customer.

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

## 4. Two implementation-versus-doc gaps that belong to this arc

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

## 6. Adult quiet hours

The kid quiet-hours machinery is thorough (`family_digest.in_kid_quiet_hours`,
honoured at eleven call sites) and has no adult counterpart at all; adults can
be pushed at any hour by schedule changes, pending drives and capture prompts.
Mirror it per adult, with the same **skip, do not defer** discipline.

## 7. Social, honestly scoped

People outside the household who matter — the friend nobody has seen since
March. Reuse the carpool-driver contact shape: a name, a number, no account.
The features are exactly three: **protect the time, remember the person,
notice the lapse.**

Not a social network. No feed, no invitations, no external messaging.

---

# Sequence, and why

1. **A1 carpool book** — smallest, immediate relief, teaches the codebase
   "coverage that isn't ours", and lands kid-visible value in week one
   (*"Riding with Emma's mom"* is pure kid-arc certainty).
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
- **Other-family accounts / multi-household.** Carpool drivers are contacts,
  not users; multi-family stays the acknowledged non-goal.
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
- Does a `Copilot` who drives siblings enter the load ledger as an adult, or
  stay outside it? (Leaning: outside — a teenager helping is not a third
  parent, and counting them invites the wrong conversation.)
- Adult quiet hours: per member, or one household window like the kid one?

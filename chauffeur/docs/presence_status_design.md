# Presence & Status Arc — design map (drafted 2026-08-04)

> Status: **P1 SHIPPED v2.53.0 (2026-08-04)** — the "never guess" loop (see
> build order §1). Slices 2–4 (calendar triggers + solver needs, trip
> timeline, Presence) remain design. It is **personal** — this is an affected
> family (a member with serious illness). Co-design is not a step to schedule;
> it's us. Build to lived detail, not to guesses.

## Where this came from

It started as "can Chauffeur do direct health — meditation like Calm, fitness
tracking like Whoop?" The answer we landed on: **no, not as content or
tracking.** We will never out-content Calm or out-hardware Whoop; a wellness
tab inside Chauffeur is a worse version of apps that already exist, and it
dilutes the one thing we're great at.

The reframe that makes it on-brand:

> **Health and connection are a scheduling problem, not a content problem.**

Chauffeur's moat is that it *owns the family schedule*. The solver decides who
goes where — and therefore, unavoidably, **who misses what, and what state
home is in.** Every feature in this arc heals a human cost the schedule itself
creates. They are the emotional complement to the solver: the solver assigns;
this arc handles the fallout of the assignment.

That framing is the whole discipline. Anything that's *detect the strain,
carve out time, protect it, surface the right thing at the right moment,
close the gap the schedule opened* uses the moat. Anything that's *host
content, track metrics, build a feed, gamify streaks* fights outside it and
loses. When in doubt, that's the line.

## Design principles (argue before violating)

1. **Scheduling problem, not content problem.** Own the *when* and the *who*;
   rent the pipe. Deeplink to Calm/Meet/Strava — never rebuild them.
2. **Never nag, never streak.** Wellness apps live on notifications and
   chains. That is *exactly the mental load Chauffeur exists to remove.* A
   health feature that nags has failed on brand. A missed call or a skipped
   day must feel like "catch you tomorrow," never a broken streak.
3. **Never leave a kid guessing.** The core promise, in the family's words.
   Transparency + proactive + *in advance*. The reassurance must be present at
   the door, not stated once at breakfast (see the dismissal-refresh beat).
4. **The family's own words, not generated copy.** The power is entirely in
   the specificity. The system schedules and delivers the message; it does not
   compose it. Authored once, in their voice, reused.
5. **Attached, never a standalone wall.** Every moment lives on an event and
   routes to the people that event kept away. The day it becomes a feed you
   scroll for its own sake, it's a worse Instagram.
6. **Defaults that flex per instance.** Consistent-per-type is right and even
   therapeutic (kids find safety in the same structure every hard day) — but
   chemo day 1 ≠ day 5, a two-week trip ≠ a Tuesday overnight. Strong default,
   one-tap "today's different."
7. **Privacy is the trust surface.** Health and kid media are the most
   sensitive data there is. On-device / HA-hosted, opt-in, and it never leaves
   the house.
8. **Efficacy honesty.** Claim "we protected your time" (provable). Never
   claim "we made you well" (not measurable, not ours to promise).

---

## Pillar 1 — Status Protocols

**Problem.** Kids feel high anxiety when they don't know what state a parent
will be in when they get home. More generally: a member's day-type reshapes
the whole household, and everyone finds out too late, or by walking into it.

**The insight that resolved the model.** A status isn't a mood dial. A
day-type *event* triggers a **protocol** — what it means, what the household
needs, and how we tell everyone — and the status label just falls out of that.
This is the app's native shape: Chauffeur already turns "when X happens, do Y"
into Rule objects. A Status Protocol is a new kind of rule, not a new app.

### The object

One reusable **Status Protocol** per day-type, authored once, in the family's
words:

- **Trigger** — a *generic* matcher, not "chemo." Chemo/surgery/radiation for
  us; night shift, a business-trip return, game-dev crunch, another
  condition's treatment for someone else. Matches a calendar event, a keyword,
  or a manual tag. Built generic from day one.
- **Needs** — a small, human vocabulary; each maps to a concrete system
  action:
  - **Cover for them** — parent's out of the rotation; solver reassigns the
    driving/childcare onto the other parent. (chemo, surgery, night shift)
  - **Bring in help** — the *other* parent is occupied caring for them, so the
    kids need someone else: grandparent, sitter, meal. Genuinely distinct from
    "cover for them" — the family called this out.
  - **Clear the deck** — decline what's optional; a family-time day. Solver
    *protects* the evening rather than filling it. (post-trip, movie night)
  - **Give space** — parent's home but resting; kids keep it low-key. Behaves
    like quiet-hours.
- **Messages** — per audience, in the family's own words: **kids** get
  age-appropriate words + the plan + the family's ritual thing ("Mom's resting
  today, Grandma's got you, she'd love a movie tonight"); the **co-parent**
  gets the logistics/load; a **helper** optionally gets the ask; the
  **affected member** can get "here's what home looks like tonight."

The color/label is just the family's chosen skin on top of this.

### Cautions specific to this pillar

- **The set-burden must not land on the person having the hard day.** On a
  Blue/rest day the affected parent is *least* able to open an app and tap a
  dial — it fails exactly when it matters most. So: the co-parent/caregiver can
  set it, the calendar auto-suggests from a known appointment, and setting is
  one tap from a notification. Never "open the app and navigate."
- **Stale is worse than blank.** Yesterday's color still showing today is an
  active lie to a kid who trusts it. Timestamp it ("set this morning"); decay
  to *"not set yet"* rather than persist.
- **A bare status can create a known fear instead of removing an unknown one.**
  The color alone is the raw wound; the *plan + a small piece of agency* is the
  medicine. Expectation + plan + something the kid can do.
- **If you promise "never guessing," you own the correction.** When the
  appointment moves or the parent feels better than expected, the pre-loaded
  message is now wrong. A gentle "plans changed / doing better today" path is
  required — transparency runs both directions.
- **Authoring is itself heavy — don't make it a wizard.** Capture the protocol
  incrementally and casually the first time such an event lands ("want me to
  remember what these days mean?"), not a setup form on day one.

### The trip timeline (the multi-day case)

A protocol isn't a single moment — it's a **timeline of beats anchored to the
event's start and end.** Short for illness days; long, with a middle, for
trips and hospital stays. Each beat is **(when, who, what)**:

- **when** — relative to start/end: `start−3d`, `start−1d`, each night
  during, `end−1d`, home-day.
- **who** — kids / co-parent / helper / the traveler themselves.
- **what** — a message, a schedule-hold, or a solver action.

Worked trip example:

- `start−3d`, co-parent: **plan-assist** kicks in — the solver reassigns every
  pickup the traveler covers, surfaces the collisions before they happen
  ("Tuesday you can't be at both 3:15 pickups — here's the fix, or who to
  ask"), pre-stages meals/errands. *This is the crown jewel: not a reminder,
  the app doing its actual load-reduction job at the moment load spikes.*
- `start−1d`, kids: "Dad's going on a trip tomorrow."
- each night during: a **soft** call window both ends can slide, in the
  traveler's timezone. Chauffeur owns the *ritual and the moment*; it deeplinks
  into FaceTime/Meet — **it does not build a video pipe.** (The one place
  "video in Chauffeur" might mean something: ringing the family's own kiosk.
  Even then, borrow the pipe.)
- `end−1d`, kids: an *excited* "Dad's home tomorrow!" — and this is where the
  family-time / clear-the-deck beat gets scheduled.

Trip-timeline cautions: **soft-schedule the calls or you build a guilt
machine** (timezones, delayed flights — a missed call must never read as a
broken chain); **scale the beats to the trip** (a rich sequence for two weeks,
a light touch for an overnight).

---

## Pillar 2 — Presence

**Problem.** A parent can only be in one place. You're at soccer, so you miss
volleyball — *every week.* This is the emotional flip side of the solver: it
creates the miss. Distant grandparents and the co-parent-with-another-kid have
the same gap.

**Idea.** Whoever *is* at the activity posts a photo/clip; it reaches everyone
the schedule kept away.

**The moat — and the whole reason it isn't just WhatsApp.** WhatsApp can share
a photo; it *cannot* know the schedule. Chauffeur can, and that's the entire
difference in meaning:

- WhatsApp: a photo drops in a group thread, everyone's pinged, nobody knows
  who was supposed to be there, it's untethered from the game, gone by
  tomorrow.
- Chauffeur: the same photo **attaches to Emma's volleyball game**, **routes to
  the exact people the schedule proves missed it** (you at soccer, Grandma
  three states away), and **stays part of that event.** Identical pixels,
  completely different thing.

Three things a generic feed can never do, and our defensible core:

1. **Prompt the capture at the right moment** — "you're at the game, want to
   send the family the highlight?" A group chat never asks; the moment passes.
2. **Route to the kept-away** — not a broadcast wall; to the specific people
   the schedule proves missed *this* event.
3. **Anchor to the event** — it lands on the game on the calendar.

Note: this is a **small marginal build**, not a platform — Chauffeur already
ships family messaging (network pivot). We're hanging *attach-to-activity* on a
channel we own, not building a WhatsApp.

### Cautions specific to this pillar

- **The capture burden lands on the parent who's actually present.** Turning
  them into a videographer means they watch their kid through a phone. The ask
  must be feather-light — one tap, a burst, a 10-second clip, even just "🏐 she
  got a kill!" Never "document this." The best version costs the present parent
  almost nothing.
- **"Experience it too" → co-presence, not a scrapbook.** A live trickle
  *during* the game ("she's up to serve," a clip of the point) makes the absent
  parent feel *with* them; an album from yesterday is documentation. Lean into
  live-during — the version only Chauffeur can do, because it knows the game is
  happening *now.*
- **The kiosk is the sleeper.** Grandma's kiosk lighting up, unbidden, with a
  clip of the grandkid's game is the warmest, purest-Chauffeur version — the
  family hearth showing you the moment you couldn't be at. Design toward it.
- **Media storage is a real fork, not a hand-wave.** Kid video is the most
  sensitive data there is, plus storage/transcoding weight. Open question:
  does Chauffeur *store* media, or hold the *context + routing* while the media
  lives where the family already keeps it?
- **Emergent, don't aim:** attach moments to events and the schedule quietly
  becomes a family scrapbook (a kid's whole season, browsable). Lovely
  byproduct. Build *for* the scrapbook and you're back in Google Photos' lane.

---

## The shared spine

Both pillars ride plumbing that already exists — a reason to be hopeful this
can be built *well* rather than fast:

- **Events & the Rule/event-type matcher** — triggers and activity-anchoring.
- **The solver** — cover / bring-in-help / clear-the-deck reassignment; the
  trip plan-assist.
- **Family messaging (network pivot)** — the delivery channel and the media
  attach point.
- **Kid Support delivery** — dual delivery, quiet-hour gate, the
  end-of-school-day dismissal push (the "fresh at the door" beat).
- **Kid lens & kiosk** — the display surfaces; the kiosk-as-hearth.

## Open forks (decide before spec)

- Media: store vs. reference-and-render.
- Status authoring UX: incremental casual capture vs. explicit builder.
- Correction path when an advance message goes wrong.
- Exact `when` grammar for beats (offsets from start/end + recurring-during).

## Relationship to existing arcs

Sibling to **Kid Support**. Pillar 1's core reassurance loop is effectively
**K6** and reuses the K-arc delivery directly; Pillar 2 (**Presence**) is a
distinct idea with a distinct trap, tracked separately so it isn't swallowed.

## Suggested build order (thin slices)

1. **Status Protocol object + manual set + kid-facing advance message +
   dismissal refresh.** The "never guess" loop — the thing that matters most to
   this family, buildable almost entirely on existing messaging. Ship value
   before touching the solver.

   **SHIPPED v2.53.0 (2026-08-04).** As designed, with decisions made during
   build: a StatusDay is DATE-BOUND (structural staleness — no dial to go
   stale, principle 6's decay achieved by construction); same protocol + same
   date refreshes note/setter instead of stacking; kid announcements on set
   go out for today/tomorrow only (a further-out day would move the dread up
   — the D-1 evening digest is the heads-up beat) while adults always hear
   immediately (minus the setter); on a status day the K4c dismissal push
   carries the status ON the ride push (one push, not two) and fires even
   with no ride ("💙 About today" — that day, silence IS the alarm); the
   digest includes EVERY kid on a status day, overriding K1's
   nothing-means-nothing omission; clearing a today/tomorrow day announces
   the relief to kids (neutral factual copy — the family authored the day's
   meaning, not its cancellation). Pieces: `StatusProtocol`/`StatusDay`
   models, `services/status_protocols.py`, `/api/status/*` endpoints, My Day
   banner + adult quick-set (armed two-tap clear), Config → People → Status
   Days authoring panel, `set_household_status`/`get_household_status` agent
   tools in both stacks. `keywords` and `need` are stored + displayed now;
   their triggers/solver hooks are slices 2–3. Tests:
   `tests/test_status_protocols.py` (8 scenarios).
2. **Calendar-trigger + solver needs** (cover / help / clear-the-deck).
3. **Trip timeline** — multi-beat, before/during/after, plan-assist, soft call
   windows (deeplinked).
4. **Presence** — light activity-tied capture → route-to-kept-away → kiosk
   render, starting from the messaging layer.

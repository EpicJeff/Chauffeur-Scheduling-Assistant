# Presence & Status Arc — design map (drafted 2026-08-04)

> Status: **P1 v2.53.0, P2 v2.54.0, P3 v2.55.0, P3b v2.56.0 SHIPPED
> (2026-08-04)** — the "never guess" loop; the-calendar-knows + cover/help
> solver needs; the trip timeline (spans, call windows, coverage reports);
> and the full relative beat grammar (anchor±offset × audience × words ×
> need — the chemo recovery arc works now, not just trips).
> Slice 4 (Presence) **SHIPPED v2.57.0 (2026-08-04)** — schedule-triggered
> capture prompt, family-wide access with differentiated push to the
> kept-away, reactions, the kiosk hearth. Media shipped as inline
> downscaled photo renditions on the family's own box (the
> reference-and-render fork's own escape clause invoked — see the slice
> entry). It is
> **personal** — this is an affected
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

- Media: store vs. reference-and-render. **RESOLVED (Slice 4 design): reference-and-render** — then **REVISED at build (v2.57.0)** via the fork's own escape clause: no external store existed to reference, so v1 stores downscaled inline renditions on the family's own box (custody preserved by self-hosting); true reference stays the door for video.
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

   **SHIPPED v2.54.0 (2026-08-04).** Decisions made during build: the sweep
   AUTO-SETS (no propose-approve card) — the family authored the trigger
   keywords deliberately, and asking permission would put the set-burden
   back on a human. Safety is the beat design instead: adults are DM'd
   immediately naming the matched event ("Clear it from My Day if that's
   wrong — I won't re-set it"), kids only ever hear today/tomorrow, so an
   advance auto-set carries a built-in adult review window; clearing a
   calendar-set day writes a 30-day tombstone the sweep respects — a
   parent's dismissal is final. Solver: `cover` and `help` become synthetic
   one-day `unavailable` Rules for the affected member's driver (injected in
   `refresh_schedule_logic`, immune to rule enable-toggles); `clear_deck` /
   `give_space` deliberately never touch driving in this slice (protecting
   the evening from OPTIONAL commitments is a different mechanism than
   banning a driver — deferred rather than faked with a blunt ban). Status
   mutations invalidate schedule caches like rule mutations. Tests: 4 new
   scenarios in `tests/test_status_protocols.py` (12 total).
3. **Trip timeline** — multi-beat, before/during/after, plan-assist, soft call
   windows (deeplinked).

   **SHIPPED v2.55.0 (2026-08-04).** Decisions made during build: no
   user-authored beat grammar — the canonical timeline is BUILT IN and
   day-position derived (day 1 = the family's full message, middle = light
   "day N of M", last = the home-day celebration), because the grammar's
   value was always the beats themselves, not authoring them. Spans are
   `StatusDay.end_date` (sweep collapses cached trip slices to one span;
   agent takes end_date; Config takes date-to-date). The call window is a
   protocol field (`call_time`) rendered soft everywhere — "around", absent
   on the home day, no deeplink yet (the family's pipe choice belongs to a
   later slice). **Plan-assist shipped as the coverage report**: one DM to
   the other adults per cover/help instance showing the re-solved span —
   drivers resolved, gaps flagged with an open count — sent from the sweep
   only after the post-invalidation re-solve lands (retry-not-silent), never
   to the traveler. The full "here's the fix, or who to ask" propose-repair
   loop stays future work; making the collisions VISIBLE at load-spike is
   the 80%. Traveler-as-audience trimmed to: traveler sees the same span
   banner (own My Day) and is excluded from coverage noise. Tests: 5 new
   scenarios (17 total).

   **P3b — the real beat grammar — SHIPPED v2.56.0 (2026-08-04).** Family
   feedback on the P3 ship, same day: "the fixed positional timeline is
   trip-specific — chemo day 1 ≠ day 3 ≠ day 5, everyone's needs and
   timelines differ; a list of beats with times relative to the event is
   the only way to model this." Correct, and it is exactly this doc's
   original model — the P3 'no authorable grammar' call is REVERSED.
   Shipped: `StatusProtocol.beats` = [(anchor start|end, offset_days,
   audience kids|adults|affected|everyone, message, need-override)].
   Beats may land OUTSIDE the instance's own dates (the chemo case: the
   event is one day, the recovery arc isn't); an authored beat's words
   replace the default line for that day; a beat's need changes that day's
   driving rules only (message-only beats outside the span never extend a
   ban). Kids beats deliver via existing surfaces only (no new pings);
   adults/affected beats DM once, morning-of, co-parent excluding the
   affected member. Positional defaults remain the zero-config fallback —
   beat-less protocols behave byte-identically to P3. Helpers as a beat
   audience: deferred. Tests: 4 new scenarios incl. the full chemo
   recovery arc (21 total).
4. **Presence** — light activity-tied capture → schedule-triggered → family-wide
   access with differentiated push → kiosk-as-shared-hearth, on the existing
   Discuss chat.

   **SHIPPED v2.57.0 (2026-08-04).** Decisions made during build:
   **media is inline, not referenced** — the reference-and-render fork's own
   escape clause fired on day one ("revisit only if a concrete capture flow
   proves reference can't carry the live-during trickle"): there is no
   external media store to reference and a share-link flow kills one-tap, so
   moments ship as client-downscaled photo renditions (~1280px JPEG data-URL
   in `ChatMessage.attachment`, server-capped ~1 MB — the avatar precedent,
   bigger) stored on the family's own self-hosted box, which is what the
   custody concern was actually guarding. Video stays out of v1.
   **The capture prompt** (`services/presence.py.run_capture_prompts`, 5-min
   cadence in the push loop): fires once per event per day within the first
   20 min of a ≥30-min non-errand event, only when a present ADULT and a
   kept-away adult both exist (no audience → no ask; never nag), and
   deeplinks `open_channel=…&compose=moment` — browsers refuse a programmatic
   file-picker without a gesture, so the deeplink lands with the 📷 button
   pulsing: still one tap to the camera. Present = assigned driver + every
   passenger-bound member (the My Day four-way binding, adults included).
   **Differentiated push shipped as designed**: a moment in an event channel
   pushes only to kept-away adults with 📸 framing (present suppressed, kids
   never pinged — their surfaces carry it); plain text in the same channel
   keeps the household-wide fan-out untouched. **Reactions**: ❤️ 😂 👏 🎉 💪
   quick-react + toggle pills on every bubble, `/api/messages/{id}/react`,
   and they NEVER push — the sender pockets the phone, reactions accumulate
   silently (fire-and-forget shipped as designed). **Kiosk hearth v1** is the
   routines wall panel: 60-s poll of `/api/presence/moments`, a fresh moment
   pops a 20-s full-screen overlay (celebration-precedent seed-silently
   dedupe) and stays browsable as a "Latest moment" card; the distant-kiosk
   render rides the same endpoint whenever a second panel exists. Tests:
   `tests/test_presence.py` (7 scenarios, both storage backends).

   **v2.58.0 (same day) — family feedback round, five corrections:**
   (1) **Video is the thing** ("Photos of sports does nothing") — the v1
   photo-only call reversed immediately: clips upload as files to the
   family's box (60 MB cap), served with explicit byte-range support, pruned
   with their message; photos stay inline. (2) **No blind nudge** — the
   capture prompt now runs a worthiness gate: medical/solemn keywords
   hard-block, status-protocol matches divert to the inversion, and only a
   moment-worthy allowlist (games, meets, recitals, concerts, parties, kid
   sports/arts) actually prompts; everything else stays organic. (3) **The
   chemo example runs the OTHER way** — the thinking-of-you inversion: on a
   cover/help status day the family is prompted to send love TOWARD the
   affected member, deeplinked into each member's own DM with them (private,
   personal, no new container); give_space days stay silent. This flips the
   presence arrow and is the arc's thesis in one push. (4) **"Moments" is
   the name** — the event-modal button, the PWA Messages-tab strip, the 📸
   event-channel avatar. (5) **The hearth rides EVERY kiosk page** — shared
   component, self-gated on ?kiosk=true, included on all eleven
   kiosk-capable templates so the wall panel lights up no matter which view
   it shows. Plus 👍 joined the quick reactions (the baseline reaction), and
   the prompt cadence tightened to 2 min so it lands in an event's opening
   minutes. Tests: 10 scenarios.

   The design (kept for the record): the container is the existing
   event Discuss chat, anchored to the event forever and reachable from the
   event chip and the chats tab — a small marginal build, not a new platform.
   Everything below is what makes it Chauffeur instead of WhatsApp-with-tags;
   none of it is the chat itself.

   - **The capture prompt IS the feature — schedule-triggered, not
     human-started.** Chauffeur knows Emma's game is live *now*, so it taps the
     present parent: "You're at the game — send the family a moment?" The push
     itself is the capture affordance (tap → burst / 10-sec clip / a bare "🏐
     she got a kill!" → sent), never "navigate into a chat and compose." A
     manually-started chat is the thing a group chat already does and the
     reason the moment passes; the nudge is the defensible core. The Discuss
     chat pre-exists / auto-opens on the anchored event — nobody has to start
     it.
   - **Access is family-wide; push is differentiated.** These are two different
     axes and collapsing them was the early error. *Access:* the whole family
     network minus helpers/temporary members (an existing, clean boundary) can
     open the moment, and it lives on the event forever. There is no per-event
     roster wall — the doc's "not a broadcast wall" is an argument against
     indiscriminate *notification*, not against who may *see* it. *Push:* the
     kept-away (solver-proven absent from *this* instance — the co-parent who
     drew soccer, distant Grandma) get the active "you couldn't be there —
     here's the kill" delivery and framing; everyone else can see it but is not
     interrupted. Identical pixels, framing differs by recipient — preserved as
     a delivery difference, not an access wall.
   - **Family-wide is the SAFER privacy story, not a looser one.** Kid video is
     the most sensitive data in the app; routing by a solver-derived roster
     could leak it to a helper who happened to sit on the driver chat.
     Family-network-minus-helpers is the tighter wall for exactly this media.
   - **Two guardrails so family-wide isn't a dumb broadcast.** (1) Delivery
     still rides the existing gates — quiet-hours, kid lens, dual-delivery; a
     late clip is simply *there* in the morning, it doesn't buzz a kid at 10pm.
     (2) Suppress push to whoever the schedule places AT the event — don't ping
     the parent standing next to the sender. Access-yes, push-no; the schedule
     already knows who was there, so it's free.
   - **Lead with live-during; the forever-thread is the byproduct.** The
     headline experience is a real-time trickle to the kept-away ("she's up to
     serve") that makes the absent parent feel *with* them — the version only
     Chauffeur can do because it knows the game is happening now. The moment
     accreting on the event chip into a browsable season scrapbook is the
     lovely emergent byproduct (principle: don't *build for* the scrapbook or
     you're in Google Photos' lane), not the pitch.
   - **Kiosk is the shared surface, both ends.** The *home* kiosk lights up
     unbidden so whoever's on the couch gets a "Emma's game — live" viewing
     party; the *distant* kiosk (Grandma three states away) lights up with the
     same clip. The warmest, purest-Chauffeur render — the family hearth
     showing you the moment you couldn't be at. Design toward it.
   - **Reactions in, threaded replies out (v1).** Reactions are load-bearing,
     not decoration: Grandma taps ❤️, the present parent sees it at halftime,
     and *that reward is what sustains the next capture* — the answer to the
     capture-burden problem. It's also the right-sized engagement for the
     passive kiosk audience (she'll glance and smile, not thread a reply).
     Threaded replies pulls straight into the WhatsApp-rebuild the moat
     forbids and aims at the wrong user; deferred.
   - **Protect the SENDER, not just the present kid.** The present parent's
     side is fire-and-forget: drop the moment, pocket the phone. Reactions and
     replies accumulate silently for them to see at a break — never a
     per-❤️ ping mid-game, or the reward loop turns them back into a phone-glued
     spectator watching their own kid through a screen.
   - **Media: reference-and-render, not store (resolves the open fork).**
     Chauffeur owns the *anchor + routing + framing*; the media lives where the
     family already keeps it. Delivers 100% of the moat without Chauffeur
     becoming the custodian of the most sensitive data there is, and dodges the
     storage/transcoding weight. Revisit only if a concrete capture flow proves
     reference can't carry the live-during trickle.

   Reuses: family messaging (channel + attach point), the event/Rule matcher
   (trigger + anchor), the solver assignment (who-was-kept-away), Kid Support
   delivery (dual-delivery + quiet-hours gate), kid lens & kiosk (the shared
   hearth). Open sub-forks for spec: the exact "is the event live" trigger
   window; whether the present parent is asked once at start or lightly
   re-nudged; the reference-media handle format.

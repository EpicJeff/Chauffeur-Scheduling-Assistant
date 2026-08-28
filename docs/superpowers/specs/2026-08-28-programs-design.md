# Programs — a goal is a plan, not a block on a calendar

**Status:** design agreed 2026-08-28. Fifth item in the ambient-family-AI
sequence (pulse → web research → threads → negotiation → **programs** →
channels).

**Design authority:** "The Work Nobody Scheduled", §III–IV.

## Why

Taking work off the plate is the smaller idea. The bigger one is giving people
superpowers to do more.

It would be easy to say a goal is a standing claim on time and stop there —
reserve Tuesday at seven, defend it, done. That is real, and the solver could
do it tomorrow. But it is not why goals fail. Nobody reserves forty minutes for
guitar and then sits there wondering what to do with it. They never reserve it,
because they have no idea what would go in it.

Goals feel like pipe dreams because the first step is invisible. Not *I don't
have time to learn guitar* — *I don't know whether I need a teacher, what a
beginner should practice, what to buy, how long any of this takes, or whether
the free thing on YouTube is any good.* That is an expertise problem wearing a
time problem's clothes.

So a goal is a **program**: an aim made concrete, a path with phases, real
resources behind it, and a set of very different demands it makes on the week.

**A program is a generator.** It emits reserved practice time, a thread for the
kit, a real dated event to aim at, and a standing option to bring in a teacher.
Threads and programs are not two features — one produces the other.

The word matters: "family goal" already means a pooled-points reward in this
app (`get_family_goals`, Family Movie Night). This feature is **programs**
throughout, and there is no `Program` in the repo today.

## The object

```
Program  { id, member_id, title, state, created_by, approved_by, created_at,
           phases[], source{}, shape{}, baseline{}, emissions{}, sessions[] }

phases[]   { name, weeks, what, milestone, milestone_hit_at }
source     { plan_name, url, why_this_one, facts[{claim,url}],
             runners_up[{name,url,why_not}], hand_written }
shape      { sessions_per_week, minutes, preferred_days[] }
baseline   { start_date, target_date, target_event_id, rebaselined_at, rebaselines }
emissions  { commitment_ids[], thread_ids[], event_ids[] }
sessions[] { ts, minutes, source: asked|added, note }        # append-only

state      proposed -> active -> (paused <-> active) -> done | dropped
```

Lives in `services/programs.py` with a `programs` table; `Program` in
`models/schemas.py`. It knows nothing about the solver, threads or the
calendar — the emissions are ids it holds.

### The six progress rules are the schema, not the rendering

Every fitness app solves tracking and then quietly weaponises it. The mechanics
that make progress motivating are the same ones that make it punishing, so
these are enforced by what the schema **cannot express**:

- **Count up.** No streak field, no current-run, no last-session-gap. The only
  derivable numbers are `len(sessions)`, total minutes, and milestones hit —
  all monotonic. A streak cannot be rendered from this shape, so it never will
  be. *A streak is a shame machine with one moving part.*
- **Track inputs.** `sessions[]` holds sessions and minutes. There is nowhere
  to put an outcome measure. Measuring someone against a thing they cannot
  control is the definition of demoralising — and this is also where the
  body-goal line gets structural teeth rather than a rule in a docstring.
- **Only mark the wins.** A milestone has `milestone_hit_at` and nothing else.
  No `missed` field, no due date. A milestone that has not happened is one
  without a date, indistinguishable from one still ahead. Nothing renders red
  because a person is behind, because the data to render it does not exist.
- **Pause is a state**, peer to active. The only way out of a program must not
  be to fail it.
- **Compare to yourself.** The only history a program holds is its own. No
  cross-member field exists. A family is not a cohort.
- **Blame the week** is the one rule that is not schema. It lives in the
  finding's wording and needs `baseline.rebaselines` to know when to speak.

`sessions[]` is append-only: a correction is a new entry, never an edit, the
same discipline threads' history uses. The count can be argued with, not
rewritten.

`source.hand_written` is a real flag, not a fallback — see curation.

## Curation: find the plan, don't invent one

The single most important rule in the arc. For nearly every goal a family has,
a good program already exists, built by someone who knows the domain — Justin
Guitar, Couch to 5K, a state's driving-test curriculum, a library's reading
ladder. Enthusiasts know these exist; nobody else does. That gap is the value.

Curation runs between `proposed` and `approved`: the person names the aim, the
agent goes looking, and a parent approves a program that already has a real
plan in it.

The engine is `web.research()`, with the discipline the threads arc locked:
**citations come from `facts`** — never from `sources`, which is merely
everything the search returned. `research()` also reports `dropped`, the
count of citations attributed to pages it never read. Here that gets teeth:

> **A phase that cites nothing is dropped. If dropping empties the plan, the
> program becomes hand-written and says so.**

**As shipped, that rule is only as strong as the research route underneath
it, and the routes are not equal.** This was written as though `facts`
always meant "a claim tied to a page this app fetched". It does on two of
`research()`'s three routes and not on the third, which is the default:

- **Brave / SerpAPI** — the app searches, fetches each result and extracts
  claims from what it read. `facts` really is a per-page citation trail,
  `dropped` really counts unread attributions, and the rule holds as stated.
- **Gemini grounding — the default, and this household's** — Google
  searches and returns an answer plus its own source list; the app fetches
  nothing. `research()` synthesises `facts` as one entry pairing the WHOLE
  answer with the first resolved source, and reports `dropped: 0`. The phase
  check can therefore only catch a model that invents a URL different from
  the one it was handed; it cannot catch a phase that cites that source
  while saying something the source never said.

The substance of the arc survives — a grounded answer with a real search
behind it is still curation rather than invention — but the guarantee is
weaker on the default route than this document originally claimed, and
overstating a safety property is worse than describing a weaker one plainly.
Making grounding fetch its own sources is separate, unshipped work.

That is what stops the named failure: an LLM will happily produce a twelve-week
curriculum for anything, and it will look exactly as good as the real one an
expert spent a decade refining. A plausible phase with no page behind it does
not get to be a phase.

`source` carries the recommendation (`plan_name`, `url`), `why_this_one` in
plain words about *this* person and *this* week, `facts[]` as the citation
trail, and `runners_up[]` each with a `why_not` — so the choice is visibly a
choice rather than an oracle.

**Adaptation is separate from invention.** Phase *content* is quoted and cited
from the pages; phase *pacing* — three 25-minute sessions, short on purpose in
the phase most people quit in — is arithmetic over `shape`. The distinction
matters because pacing is exactly where a model would otherwise start writing
curriculum.

**When nothing good exists**, it says so and offers a hand-written program:
`hand_written = True`, `facts` empty, no fake citations, and the card says
plainly that this one is not from anywhere.

**Cost:** one research run per program, cached in `source` for its life.
Re-curation is an explicit act, never automatic. A background sweep must never
spend research calls.

### The one domain to stay out of

The house supports **behaviour** goals and stays out of **body** goals. Move
four times a week, cook at home five nights, train for a real 5K with a date
and a bib — all excellent, all trackable, all safe. Goal weights, calorie
targets and body-fat numbers are a different thing, and they should never exist
for a minor at all.

Enforcement is **before research ever runs**, and deterministic first: an
obvious keyword screen on the aim, ahead of any model call, because a safety
line that depends on a model's judgement is a safety line with a bad night. A
body-composition aim is refused for anyone, in one plain sentence, with the
behaviour-shaped alternative offered in the same breath. No research call, no
program object, nothing to accept later.

## Approval and the footprint

The parent sees the whole footprint before saying yes. One screen, one tap —
the named killer of assistants is approvals arriving as a drip:

> *Lily — play well enough for campfire songs by summer*
> Claims **Tue, Thu, Sat 7:00–7:25**. Opens a thread to buy **a capo and a
> clip tuner (~$28)**. Puts **Campfire weekend** on the calendar for
> **June 14**.

A kid proposes; a parent approves once. After that the program's reserved time
is defended like anyone else's without further asking — the parent gates it
entering the family's week, not each session.

Approving creates all three as ordinary objects tagged with the program id.
Slots are proposed from the week's existing shape — the cached schedule plus
commitments already on record — and are editable on that screen before the tap.
No CP-SAT run: proposing a practice time is not a solve.

**Application borrows the shape negotiation proved**, because it is the same
problem — several real side effects, one of them external. Pre-flight
everything; apply local writes (commitments, thread) before the calendar event;
stamp each emission id as it lands. If the calendar refuses, the program says
exactly what already happened rather than implying nothing did.

### The asymmetry, stated plainly

A `ProtectedCommitment` reaches the solver through `member.driver_id` →
`Rule(constraint_type='unavailable')`.

For an **adult**, reserved practice time is genuinely defended: CP-SAT will not
assign a drive during it, and negotiation can ask them to give up one
occurrence when the week collides — priced as the most expensive lever in that
model, which is right for someone's own thing.

For a **kid**, there is no such lever. A child is not a driver, so the solver
has no opinion about their Tuesday evening. Their reserved time is real and
visible — PWA, wall, program — and a family event landing on top of it becomes
a finding that names the schedule. It is defended **socially and visibly, not
by the optimiser.**

Building that and saying so beats implying the solver protects a child's guitar
practice when it structurally cannot. It does not undercut the arc: the claim
about kids is that the house *takes their thing seriously* — finds them a real
curriculum, puts their time on the wall beside the adults' obligations, and
notices out loud when it erodes. All three work. The optimiser was never the
part that mattered there.

Making the solver genuinely defend a child's time means teaching it to reason
about non-drivers' commitments as schedulable objects. That is a larger change
and is **out of scope** for this arc.

## Living with a program

**Counting.** A reserved slot elapses and one question arrives for the person
whose program it is — *"Guitar last night — did it happen?"* — one tap, deduped
by slot, never asked twice, held to the existing quiet-hour rules so a 9pm slot
asks in the morning. **"For the person whose program it is" is load-bearing and
was got wrong once:** shipped as a watcher finding, the question went to the
PARENTS (findings are DM'd to parents, `/api/findings` is parent/adult gated,
and the confirm card was admin gated), so a parent could tap "yes, it happened"
about a session nobody watched. It rides the owner's own surface instead — the
PWA card, from `due_asks_for` — which is also the only reading under which
checking the member's quiet hours ever made sense. An evening the family gave
up through negotiation's `lift_protected` is never asked about. Yes appends a session (`source: 'asked'`). Silence appends
nothing. An unscheduled session can be added any time (`source: 'added'`).

**Blaming the week without storing a failure.** To say "Wednesdays keep getting
eaten" you must know Wednesdays were missed — but the schema deliberately has
nowhere to record a miss. So misses are **derived at read time, never stored**:
expected slots since `start_date` (from `shape.preferred_days`) minus sessions
logged, bucketed by weekday. Enough to name the losing day in one sentence with
a fix attached; nothing left in the object for any surface to render red. The
wins are durable; the shortfall is a momentary calculation.

**Re-baselining.** Over a rolling three weeks, if actual sessions per week fall
short of `shape.sessions_per_week`, the timeline stretches on its own,
`rebaselines` increments, and one finding says why — naming the weekday and
offering an alternative, never naming the person and never quoting a total. At
most one re-baseline per fortnight, so it cannot chatter.

It will not move a date the world fixed. If `target_event_id` points at a real
June campfire, the target stays and the phases compress instead — and when they
cannot compress honestly, it says so. A program that lies about fitting is
worse than one that admits it is tight.

**Pause** removes the reservations, stops the asks, stops re-baselining, counts
as nothing. Resuming re-creates the emissions and re-baselines from that day.
Nowhere does a paused program render as behind.

**Drift.** Each sweep the program checks its emission ids still exist. When a
commitment has been deleted by hand, the program says so once, calmly —
*"Tuesday practice isn't on the calendar any more — want it back, or shall I
re-shape the week?"* — and stops believing the time is reserved. It never
silently re-creates it. Someone deleting a thing and the app putting it back is
how people learn to stop trusting an assistant.

**Milestones** are marked hit by a person, because "switch G→C without looking"
is a judgement no app can make. Hitting one stamps `milestone_hit_at`, lights
the wall card, and tells the house. Nothing marks one missed.

**Done** is the last milestone or a person saying so. **Dropped** cleans up the
emissions and leaves. Neither is failure.

## Surfaces

- **`/programs`** — the admin surface: create, curate, approve the footprint,
  pause, drop, re-curate. Parents and adults, kiosk-hidden. Approval uses the
  `_approver_of_record` stand-in (v2.432.1): the control-center pages carry no
  member, and a real claim still wins.
- **The PWA** — the person's own program: next session, the count so far, the
  milestone ahead, the one-tap *did it happen*, add-a-session, mark-a-milestone.
  A kid opening the app sees their thing taken seriously rather than a list of
  what the family needs from them. This is the inversion the arc is for.
- **The wall card** — celebrates, does not measure. Whose milestone is close,
  what got practised, who just hit one. No totals inviting comparison, no
  ranking. Board card per the card-conversion paradigm: section toggles on by
  default, members filter, interactive where there are taps.
- **The seventh vital sign, `progress`** — per member, like `load`. Two things
  keep it from becoming the shame machine the rest of the design avoids: it is
  **Mind-input only**, never a gauge on the wall (already the locked rule for
  the pulse), and it is measured against **the family's own baseline**, so a
  busy fortnight reads as a dip in their own trend rather than failure against
  a target. `_WORSE_WHEN` entry is `down`. Its job is to let the Mind say the
  one thing no other sign can: this family is getting what it wanted, not
  merely surviving what it was handed.
- **Chat, both stacks.** `list_programs` and `program_progress` are reads;
  `propose_program` and `log_session` are writes needing a resolved member —
  allowlist, not blocklist, since `/api/chat` is `WALL_OR_SERVICE`. **Approving
  is not a chat tool**: the footprint claims time in the family's week and that
  stays a deliberate tap on a screen showing what it will do. The v1 admin loop
  gets the reads only.

**Hand paths** for everything: proposing, curating, approving, logging, marking
a milestone, pausing, dropping are all reachable by tap. Nothing is agent-only.

**Settings** in `settings_registry.py` on the programs page: `programs_enabled`,
the ask cadence, the re-baseline window and its cap. Every one must be read by
the code it names.

## Out of scope

- Teaching the solver to defend a non-driver's time.
- Body-composition goals, for anybody.
- Programs shared across members. One program, one person; a family program is
  a different object and the design does not ask for one.
- Any streak, leaderboard or cross-member comparison — there is nowhere in the
  schema to put one.
- Automatic re-curation, or any background research spend.

## Testing

- No streak is derivable: assert the stored shape offers no field from which a
  current-run could be computed.
- A phase citing nothing is dropped; an emptied plan becomes `hand_written`
  with no citations.
- A body-composition aim is refused **before** any research call fires — assert
  the research function is never reached.
- A partly-applied footprint reports what already happened, and pre-flight
  refuses rather than half-applying what it can already tell will fail.
- A hand-deleted commitment is noticed once and never silently re-created.
- Misses are derived, never stored: after a shortfall, assert the object holds
  no miss record while the finding still names the right weekday.
- Re-baselining never moves a `target_event_id` fixed by the world.
- One test that actually **runs** the sweep path end to end — entry points here
  swallow exceptions, so a source-reading test proves nothing.
- Hand-path reachability for each capability.

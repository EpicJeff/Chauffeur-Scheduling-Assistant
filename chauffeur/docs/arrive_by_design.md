# Arrive By — design brief (drafted 2026-08-22)

The family's words: *"There is a buffer routing rule that adds time before
and/or after an event. It is invisible. Nothing anywhere says 'arrive 15 mins
early'."*

That is true, and it has been true since buffer rules shipped. The rule works
— the solver spaces conflicts by it and the drive plan leaves earlier for it —
but no surface in the app has ever said so out loud. A constraint the family
cannot see is a constraint they cannot trust, check, or correct.

## What this brief argued out (read before relitigating)

**1. "Buffer" is not the concept. "Arrive by" is.** A buffer is one of three
ways to arrive at a single question — *what time do we need to be standing
there?* — and the reason it has stayed invisible for so long is that nothing
in the app models the answer. Name the answer and every surface has something
to render; keep calling it a buffer and every surface has to do arithmetic.

**2. There are THREE times per event and they are not interchangeable.**

| | means | side | status |
|---|---|---|---|
| `leave_by` / `ready_at` | get in the car now | home | shipped |
| **`arrive_by`** | be standing there | destination | **this brief** |
| `start` | the whistle blows | destination | shipped |

`leave_by.ready_for_covered` already consumes `buffer_before_mins`, so the
chain half-exists. What is missing is the middle statement, which is the one a
parent actually says out loud to a child.

**3. The earliest arrival wins — max, not precedence.** A household that set a
30-minute rule set it *because* clubs say 15 and they want more than that;
precedence would silently undo the reason the rule exists. Max never makes you
later than any source said, which is the only failure that matters. One rule,
no ordering to remember, and the chip names which source won so it is never
mysterious.

  The single exception is a **typed override**, which replaces everything. A
  person overruling the app must not be argued with.

**4. Never replace the start time. Ever.** This is the whole user-experience
question and it has one answer: `10:15 kickoff · arrive 10:00`, never `10:00`.
The family named the failure themselves — if the app says 10:00 and means
warm-up, then running late at 10:05 feels like missing the game when it has
not started. The buffer is *additional information*, never a substitute for
when the thing begins.

**5. The club's own words are already in the database.**
[ics_sync.py](../services/ics_sync.py) copies the ICS `DESCRIPTION` onto the
Google event, so "arrive by 10:00" from Playmetrics or TeamSnap is sitting in
the event body right now, unread. Nothing needs capturing. It needs parsing,
and the parse is a regex — matching ics_sync's deliberate zero-LLM stance, and
cheap enough to run on every event on every sync.

**6. Do NOT shift the event's start time.** Two reasons, and the first is the
family's own: it destroys the answer to "when does the game actually start",
which is the thing they are anxious about. The second is mechanical —
ics_sync patches on fingerprint change, so every sync would fight the edit
forever.

**7. The shadow "Warm-up" calendar event is deferred, not refused.** It is the
one option with a permanent running cost: two rows in every calendar app for
one game, and — because this app has exactly one event feed — a generated
event would enter that feed and have to be explicitly excluded from the solver
or become a fake ride. It also buys visibility in exactly one place, the
Google Calendar app, while the wall panel, the PWA, the dashboard and the
digest would all already be showing it. Build the value first; decide about
the row once the family knows whether they still miss it. Nothing in V1–V3
forecloses it — `arrive_by` is precisely the input it would need.

## Design principles (argue before violating)

1. **One derivation, many surfaces.** `arrive_by` is computed in one place and
   read everywhere. Two surfaces disagreeing about when to be at the pitch is
   worse than neither saying anything — the same rule the shopping deadline
   spine already holds.
2. **Derived, never stored** — except the explicit override. A stored copy
   drifts the moment a rule changes, and a stale arrival time is a missed
   warm-up.
3. **Say which source won.** "Arrive 10:00 — your rule" and "arrive 10:00 —
   the club says so" are different facts, and a parent deciding whether to
   argue with it needs to know which they are looking at.
4. **Silence beats a guess.** No location, or an all-day event: there is no
   arriving, so there is no chip. A missed parse costs a rule typed once; an
   invented one costs trust in every chip after it.
5. **It is never a ride.** `arrive_by` annotates an event; it never creates
   one, never enters `driver_events`, and never changes what the solver
   considers a commitment. (The calendar-shows-everything rule stands.)

## The vocabulary trap

`ready_at` (home) and `arrive_by` (destination) are adjacent, and on one wall
tile they will read as contradictory if they share a word: "be ready 9:20" and
"be there 10:00" must never both be called *be ready*. Fixed vocabulary, used
everywhere:

- **leave by / be ready** — at home, before the drive. Existing, unchanged.
- **arrive by / be there** — at the destination. New.
- **starts** — the event's own time. Never renamed, never moved.

---

## Build order

**V1 → V2 → V3**, and V4 only if the family still wants it after V3.

## V1 — the value

`services/arrive_by.py`, one function, no UI:

```
derive(event, rules, config) -> {
    'arrive_at': ISO,        # the derived time
    'lead_mins': int,        # how far before the start
    'source': 'override' | 'description' | 'rule',
    'reason': str | None,    # "Warm-up"
} | None
```

Sources, max-wins (§argued-out 3): the event config's typed override, the
description parse (V3 — the hook exists in V1 and returns nothing), and any
matching `buffer` rule. Rule matching reuses the solver's own
`does_event_match_rule` rather than reimplementing it: the whole point is that
the chip states what the solver actually did.

**`Rule.buffer_reason`** ships here, before any calendar question, because it
is what turns a chip into a sentence — *"arrive 10:00 — warm-up"* beats
*"arrive 10:00 (buffer)"*. Default "Warm-up" when a buffer rule has none.

The after-buffer mirrors it: `depart_after`, from `buffer_after_mins`, so
"ends 11:30 · leave 11:50" is available to the same surfaces.

Stamped onto each event in the cached daily schedule so V2 has it without a
second call.

## V2 — say it everywhere

One chip, every surface: drive sheet, event detail, digest lines, wall hero,
PWA My Day, the schedule's own event row. Format is §argued-out 4's contract —
start dominant, arrival secondary, source named on the detail view where there
is room for it.

## V3 — read the club's words

The description parser. Narrow patterns only:

- `arrive by <time>`
- `arrive <n> minutes (before|prior|early)`
- `be there <n> minutes before`
- `players arrive <time>`

Anything ambiguous is skipped (principle 4). Runs on ICS-sourced and
hand-typed events alike — the parse does not care where the description came
from. The club's own phrasing becomes the chip's `reason` when it has one.

## V4 — the shadow event (deferred)

Opt-in per rule, off by default. The lifecycle question has a shipped answer
in this repo: ics_sync's `event_map` — source id → created Google id + content
fingerprint, reconciled every sync (create missing, patch changed, delete
orphaned, past events frozen, 404/410 treated as success). Same shape, keyed
by `extendedProperties.private.chauffeur_buffer_of`, so an orphan is
identifiable even if the map is lost. Rule changed → fingerprint changes →
patch. Rule deleted → no longer derived → orphan → delete.

It must also be excluded from the solver, or the family gets a fake ride to
the warm-up before the ride to the game.

## Explicitly cut — with reasons that hold

- **Shifting the event start.** §argued-out 6.
- **An LLM for the description parse.** ics_sync is deliberately zero-LLM, the
  parse runs on every event on every sync, and a model that resolves "arrive
  15 minutes before" correctly 95% of the time produces a silently wrong
  arrival time the other 5%, which is worse than not reading it at all.
- **Storing `arrive_by` on the event.** Principle 2.
- **A second "arrival" concept for errands.** Errands already carry their own
  `buffer_mins` and a drive errand has no audience waiting for it. If a
  household wants to be early to a haircut, that is a rule.

## Risks

- **The chip is on every surface, which means every surface can get it
  wrong.** One derivation is the mitigation, and the test for it is that
  two surfaces rendering the same event render the same string.
- **Max-wins is arguable** and will look wrong exactly once: when a club says
  15 minutes and a family's forgotten old rule says 45. The mitigation is
  §principle 3 — the chip names the source, so the fix is visible from the
  thing that is wrong.
- **V3's parser will meet phrasings nobody predicted.** It fails closed. The
  honest failure mode is that some sports keep needing a rule typed once.

## Tests when built

- `tests/test_arrive_by.py` — max-wins across sources, the override replacing
  rather than maxing, no chip without a location, no chip on an all-day event,
  the reason defaulting and being overridden, `depart_after` mirroring,
  matching delegated to the solver's own matcher (a rule that does not match
  the event yields nothing).
- V2 additions: the same event rendered by two surfaces produces the same
  string, and the start time is never replaced.
- V3 additions: each supported phrasing, and — more importantly — a set of
  near-miss phrasings that must yield nothing.

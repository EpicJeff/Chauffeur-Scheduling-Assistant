# Subjects — a thread or mission stands inside a Chauffeur record

**Date:** 2026-10-14. **Status:** DRAFT for the user's review; Codex adversarial review pending. Slice 1 of three (resolver + subject; then staged plans with one approval per stage; then wake conditions).
**Builds on:** `2026-10-10-browse-missions-design.md` (missions, threads, the planner's READ/PROPOSE catalog), the mid-mission steer (v2.499.458), the Programs arc (a goal is a plan that claims the week).

## Problem

A mission sees Chauffeur only through the planner's READ tools, and the planner sees those as a flat list of names. "Book dining for the Disney trip" has no path to the trip: there is no trip READ tool at all, and nothing resolves "the Disney trip" to a record. Whatever a mission does read lands in its transcript and scrolls out after 25 steps; a follow-up mission on the same thread starts blind; the record changing after the read is never noticed. A thread knows a counterparty and nothing else. The person's workaround today is to open the trip or occasion, find the thing, and ask about it by name. The goal (the user, 2026-10-14) is the opposite: a vague request during a busy day, and the agent fills in the blanks from what the app already knows.

## Decisions made in this conversation

- **Optional, always.** A free-text goal with no subject keeps working exactly as today. A subject is added when the resolver finds one, when the planner binds one, or when a person picks one. Nothing requires it.
- **The subject lives on the thread; a mission inherits it.** A thread is the long-lived thing ("Disney trip dining"); its missions come and go. A manual mission (no thread) carries its own. One place to set it by hand.
- **One resolver, every kind.** A single `find_in_chauffeur` tool over trips, occasions, events, members, outside contacts, threads, programs and lists. It returns candidates with ids. The same tool serves Argyle's chat and the mission planner, so "which trip" is answered once, the same way, everywhere.
- **Fresh, not remembered.** The subject's current state is rebuilt from storage and put at the top of every planner step and of Argyle's chat prompt while the focus thread has a subject. It never rides in the transcript.
- **Visibility is the record's own.** Candidates are filtered by the asking member before matching: occasions by `scope.audience_allows`, trips by their audience, threads by `situations.can_see`, and a spoken request additionally by `speech_safe`. A child asking about a surprise party gets "nothing on the books" (family-network S4), unchanged.
- **Out of scope for this slice:** staged plans, batch proposals, wake conditions, write-back of results onto the subject (reservation → POI), fan-out. Each is its own slice and is named here only so the record shapes leave room for them.

## Section 1 — The record

Two fields, on `Thread` and on the mission row: `subject_kind: Optional[str]`, `subject_id: Optional[str]`. Kinds in this slice: `trip` (id = the trip's `event_id`, the key `storage.get_trip_metadata` takes), `occasion`, `event` (a cached-schedule event id), `member`, `contact` (an assist contact), `thread`, `program`, `list` (a shopping list). Absent means none. A mission's effective subject is its own when set, else its origin thread's (`missions.subject_of(mission)`).

`services/subjects.py` is the one module that knows the kinds. Per kind, three functions behind one registry:

- `find(kind, query, viewer, spoken=False) -> list[Candidate]` — `Candidate = {kind, id, title, when (ISO date or ''), score}`. Matching is the existing tiers reused, not reinvented: exact title, then substring and first-word, then the sound-folded form `_match_person` already uses, each tier requiring a unique winner before it is trusted. Dates in the query narrow ("the trip in March"). Upcoming and open rows outrank past and closed ones at equal score. Capped at 5 per kind.
- `context(kind, id) -> str` — the record's current state in plain words, at most 1,500 characters, newest-relevant first. Trip: title, where, dates, travellers, accommodations with nights, flights, budget, then the POIs with their scheduled day and time window (scheduled ones first, unscheduled ones named), each with its category so "dining" is a word the planner can match; capped at 30 POIs with "and N more" after. Occasion: `occasions.contents` (date, days away, headcount, guests with headcount, lists, errands left, dishes). Event: title, date, time, location, driver or "no driver yet", passengers. Member: name, role, driver yes/no. Contact: what we call them, relation, helps-with, channels on file (never the numbers themselves in a spoken context). Thread: title, goal, state, counterparty, next action, last three history lines. Program: title, whose, state, this week's sessions. List: name, item count, the first ten items.
- `link(kind, id) -> str` — the page a person opens for it (`/trip?event_id=…`, `/occasions#…`, `/threads`, the member's profile, and so on), used by the card chip.

`find_all(query, viewer, kinds=None, spoken=False)` runs every kind (or the named ones) and returns candidates sorted by score then recency, capped at 8. `resolve(query, viewer, ...)` returns the one candidate when the top score is a clear winner (the same margin rule `_match_person` uses between Grandpa and Grandma), else `None` with the candidates, so the caller can ask "which one?".

## Section 2 — The tool and who calls it

One READ tool, `find_in_chauffeur(query, kind='')`, registered in `agent_tools_v2` and added to `missions.READ_TOOLS`. Result: `{status, candidates: [...], context: str|None}`; `context` is filled when the result is a single clear winner, so one call both finds and reads. The acting member is the viewer; the planner runs as the mission's creator (today's `parent_of_record` fallback when there is none).

**Argyle's chat.** Router rule, next to the start-a-mission rule: before `start_mission_for` for a goal that names a thing the family has (a trip, a party, an event, a person, a list), call `find_in_chauffeur` and pass the winner as `subject_kind`/`subject_id`; when it returns more than one, ask which. `start_mission_for` grows the two optional arguments and writes them on the thread it opens; a focus thread that already has a subject keeps it. Dedupe changes with a subject: a live mission on an open thread with the SAME subject is "already under way" (today's first-three-words rule stays for subject-less goals).

**The planner.** `find_in_chauffeur` is a READ action like any other. A new action `{"action":"subject","kind":"…","id":"…"}` binds the subject on the mission (and on its origin thread when the thread has none); the step is a `note` named `subject`. The system prompt tells the planner: when the goal names something the family has and no subject is set, find it first; when a subject is set, its state is above and is the truth, not the transcript's older reading.

**Fresh context.** `missions._system_prompt` gains, after the family context, `ABOUT: <kind> "<title>"` and the `context()` text when the mission has an effective subject. `agent_router` gains the same block under the FOCUS line when the focus thread has a subject. Both are built per call from storage. Neither is stored.

## Section 3 — The hand path

- **Chip.** The thread card and the mission card show `About: <title>` (the one card builder, `static/situations.js`, `ctx.extraHtml` or a new slot) linking to `link()`; the Threads page and the Missions page draw it the same way.
- **Pick or change it.** Thread card option `_opt('subject', 'Link to something in Chauffeur', {})`, parent/adult, verb `subject` added to `VERBS`; the tap uses `promptInput` for the words, posts `POST /api/situations/thread/{id}/act` with `{verb:'subject', payload:{query}}`; a clear winner binds, else the response carries the candidates and the card asks with `promptChoice`, then posts again with `payload:{kind, id}`. Clearing: the same option with `payload:{clear:true}` ("Unlink"). A manual mission's card gets the same option. Argyle's `act_on_situation` verb `subject` with `text` is the same path.
- **Back-link.** The trip page and the occasion page (the two records this slice is for) show one line, "Argyle: <thread title> — <next step>", for each open thread or live mission whose subject is that record, linking to the Threads page. `GET /api/subjects/{kind}/{id}/situations` serves it (parent/adult; the viewer's `can_see` applied).

## Section 4 — Tests (before the code)

`tests/test_subjects.py`: per kind, `find` ranks exact over substring over sound-fold, drops past and closed at a tie, filters by audience (a child never sees a parents-only occasion or a private trip; a spoken call never sees a speech-unsafe thread), caps; `context` for a trip lists the dining POIs with their windows and stays under the cap; `resolve` returns one on a clear margin and `None` plus candidates on Grandpa/Grandma. `tests/test_mission_subject.py`: a mission with a subject leads every step's system prompt with ABOUT and the fresh context (the record edited between two steps shows the edit), inherits its thread's subject, the `subject` action binds and notes, `find_in_chauffeur` is a READ action, `start_mission_for` writes the subject and dedupes on it. `tests/test_subject_hand_path.py`: the `subject` verb through `situations.act` (query → bound, ambiguous → candidates, clear), `act_on_situation` with text, the back-link endpoint filtered by viewer, and a node run of the card chip. Router: the chat prompt carries ABOUT when the focus thread has a subject (`test_agent_router_*` neighbour).

## Section 5 — What this does not do (named so the next slices start here)

A subject-bound mission still proposes one change at a time, still dies at finish, still never writes its result onto the subject, still cannot wait for a date. Slice 2 (plans) adds the interview, the plan preview card, stages, and one approval per stage; slice 3 (wake) adds sleeping between stages and the triggers (date nearing, a reply, a program session). Both read the subject through the same `context()` and bind through the same two fields, which is why they are two fields and one module rather than per-kind code in the planner.

## Open questions for the review

1. Should `event` be a kind at all in slice 1, or does the Needs-You finding (which already binds an event by `subject_id`) cover every case where a mission is about one event?
2. `context()` for a trip at 1,500 characters: enough for a ten-day Disney itinerary with 30 POIs, or does dining deserve its own `context(kind, id, facet='dining')` now?
3. Is binding by the planner (the `subject` action) worth having in slice 1, or should only the router and the hand path bind, with the planner read-only?

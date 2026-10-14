# Planned missions — an interview, a plan you can see, and stages you approve

**Date:** 2026-10-14. **Status:** DRAFT for the user's review; Codex adversarial review pending. Slice 2 of three (slice 1: subjects, BUILT v2.499.459–.472; slice 3: wake conditions).
**Builds on:** `2026-10-14-mission-subject-resolver-design.md` (subjects, `subject_rev`, ABOUT, audience inheritance, guarded retarget), `2026-09-04-mission-engine-design.md` (the planner loop, READ/PROPOSE, the proposal rail), `2026-09-02-mind-plans-design.md` (2–5 step plans with per-step approval on a propose-only rail), `docs/occasion_design.md` O2 (the template interview whose answers cascade, template stamping, the gap report), the mid-mission steer (v2.499.458), mission chat cards (v2.499.453).

## Problem

The user (2026-10-14): "a thread or mission could be 'help me plan my Disney trip' or 'help me plan Kate's birthday party' and go through the stages of trip or party planning: create the trip or occasion, fill in the attractions, accommodations, guest list, menu, based on details you provide, volunteered or asked for through a questionnaire, and build the thing for you." And: "I want to learn piano" → a program that adapts, a place for lessons, a piano, books.

Today a mission advances one action at a time and every write is its own proposal card. A party would be twenty separate approvals with no picture of the whole, and nothing asks the family what it needs to know up front except one `ask_user` question at a time. The field feedback (2026-10-09) is the bar: every handle shows its plan before acting, nothing hand-wavy, and the least-engaged family member must be able to say yes or no.

## Decisions (made with the user, or assumptions marked ASSUMED for the user to correct)

- **One engine, not verticals.** A planned mission is an ordinary mission that carries a `plan`. The planner decides when a goal deserves one (it plans, organizes, or builds something with parts). Domain knowledge enters through the subject's own primitives: an occasion's template interview and stamping, a trip's POIs and scheduler, a program's curator. The user rejected per-domain verticals for the Mind; the same holds here.
- **Three phases, each visible.** Interview (what Argyle needs to know), plan (what it will build, stage by stage), stages (each stage's rows, approved as one). Nothing is written before the person approves the stage that writes it.
- **One approval per stage** (the user, 2026-10-14). A stage is a batch of ordinary proposals approved together; each still runs through the existing proposal rail, so permissions, audit and audience are unchanged.
- **ASSUMED: approval by tap or by the person's own words in chat.** "Yes, do the menu" approves the stage in conversation the way `act_on_situation` verb `do` approves a proposal today. Releasing contact details and booking stay tap-only (locked, v2.499.368 and the submit gate).
- **ASSUMED: the interview is a card with all its questions (at most five) and a conversation that asks them one at a time.** Either answers them; a person may answer several at once in prose ("twelve kids, chocolate cake, dinosaurs, no presents"); every question offers "You decide".
- **First target: Kate's birthday party** (agreed 2026-10-14): occasions have no login walls, a template, a gap report and audience rules for gift secrecy. Trips follow in the same engine; programs are a stage, not a new engine.
- **Out of scope here:** stages that wait for a date or an event (slice 3), sending anything outside the family (drafts only, as today), buying or paying, guests' contact details (guests stay names).

## Section 1 — The record

The mission row gains `plan: Optional[dict]`, absent for every existing mission (free-text missions are untouched):

```
plan = {
  'state': 'interviewing' | 'proposed' | 'approved' | 'done' | 'stopped',
  'questions': [{'key', 'ask', 'kind': 'yesno'|'number'|'text'|'choice'|'date', 'choices': [...], 'why', 'source': 'template'|'planner',
                 'answer': <value> | None, 'answered_by': member_id | 'you_decide' | None}],
  'stages': [{'id', 'title', 'why', 'makes': ['<one line per thing it will create>'], 'owner_member_id' | None,
              'state': 'pending'|'proposed'|'done'|'partial'|'skipped',
              'proposal_ids': [...], 'results': [{proposal_id, status, message}], 'subject_rev': int | None}],
  'rev': int,                 # bumps on every person-made change to the plan
  'approved_by': member_id | None, 'approved_at': ts | None,
}
```

Caps: at most 5 questions per interview round and 2 rounds; at most 7 stages; at most 15 rows per stage. A stage's `makes` lines are what the plan card shows; its proposals are what the stage card shows.

## Section 2 — The planner's new actions

Three JSON actions join the planner's list, allowed only while their phase is current:

- `{"action":"interview","questions":[...]}` → writes `plan.questions` (state `interviewing`), adds an ask step named `interview`, status `waiting_user`. When the mission's subject is an occasion whose template has unanswered questions (`occasions.interview(id)`), those questions are merged in first with `source: 'template'`, verbatim.
- `{"action":"plan","stages":[...]}` → writes `plan.stages` (state `proposed`), ask step `plan`, `waiting_user`. The planner sees every answer (and every "you decide") above the transcript.
- `{"action":"stage","stage_id":"…","calls":[{"tool":"…","args":{…},"summary":"…"}]}` → for the next approved, pending stage only: each call must be a proposable tool (the same `proposable_tools()` test), each becomes an ordinary action proposal stamped with `origin_kind/origin_id` and `stage_id`; the stage turns `proposed` with its `proposal_ids` and the mission's `subject_rev` at that moment; ask step `stage`, `waiting_user`.

The system prompt states the phases and the caps, and tells the planner: interview only for what no READ tool or the subject already says; plan in stages a person would recognise (create the thing, people, food, things to buy, errands, messages); never put a write outside a stage once a plan exists; after the last stage, finish with what is left (for an occasion, `occasions.gap_report`).

## Section 3 — Answering, approving, changing

- **Interview answers.** `missions.answer_plan(mission_id, answers: {key: value|'you_decide'}, actor)`: parent/adult; writes answers; a `source: 'template'` answer also goes through `occasions.answer` so its cascade runs (headcount scales the kitchen) and the occasion page shows it; when every question has an answer or a "you decide", the mission runs on. Free text in chat on a mission waiting on an interview is a `user_answer` the planner turns into answers with an `answers` action (`{"action":"answers","values":{key: value}}`), shown back on the card.
- **Plan approval.** Verb `plan` options on the mission and thread cards: "Looks good" (`plan:<rev>:approve`), "Change something" (free text, a `user_steer` the planner replans from), "Stop". Each stage line has "Leave this out" (`plan:<rev>:drop:<stage_id>`). An option id carries the plan `rev`; a stale tap after a change answers "the plan moved; look again". Approving writes nothing; it only lets stages be proposed.
- **Stage approval.** Verb `stage` options: "Do this" (`stage:<stage_id>:<subject_rev>:approve`), "Not this one" (skip), "Stop". "Do this" runs each of the stage's proposals in order through the existing approve path (`chat_actions.act_on_proposal` / the mission proposal rail), records each result, and marks the stage `done` or `partial` (failures named in the card and the transcript; the planner sees them and may propose a repair stage). Refused when the mission's `subject_rev` differs from the stage's (the subject moved; the planner re-proposes). A stage card lists every row with "Leave this one out" per row before approving.
- **Tap-only?** Plan and stage approvals may also come from the person's words through `act_on_situation` (ASSUMED above). They are added to `TAP_ONLY_ASKS` for free-text routing only: free text on a waiting plan or stage is a steer, never an approval, unless it comes through the approval verb.
- **Retarget and steer.** A pending stage blocks `subjects.retarget` (it is an ask that commits writes, like a release). A steer while a plan is proposed replans (`plan.rev` + 1); a steer while a stage is proposed withdraws that stage's proposals and re-proposes it.

## Section 4 — The subject is born in stage 1

A party plan's first stage usually creates the occasion. When an approved proposal of a stage returns a created record (`add_occasion` → occasion id; a trip creation → event id; `propose_program` → program id), and the mission (or its thread) has no subject, the record binds as the subject (`subject_rev` + 1, `subject_history` appended) — the creator is the approving parent, so the audience is theirs. From the next step on, ABOUT carries the occasion's live state. Tools that create must therefore return the created id; `add_occasion` today returns only a sentence and gains `occasion_id`.

## Section 5 — Tools the stages need (by hand and by Argyle)

Existing and proposable: `add_occasion`, `add_occasion_guests`, `set_occasion_attendance`, `add_dishes`, `set_hosting`, `source_for_occasion`, `suggest_gift_ideas` (read), `add_trip_poi`, `auto_schedule_trip_itinerary`, `manage_trip_flights`, `propose_program`, `create_thread`, `draft_thread_message`.
New, each with its hand path on the owning page (the "every agent capability has a hand path" rule): `answer_occasion_question(occasion, key, value)` → `occasions.answer` (hand path: the occasion page's interview, exists); `stamp_occasion_template(occasion, keys)` → `occasions.apply_template` (hand path: the page's apply-template button, exists); `set_occasion_menu(occasion, dishes)` → `occasions.set_menu` (hand path: the occasion menu picker, exists). Each is a WRITE (proposable), never a READ.

## Section 6 — The hand path and the cards

The mission chat card (v2.499.453) gains three ask kinds, drawn by `renderMissionAskCard` and the thread/mission situation cards:
- `interview`: each question with its control (yes/no, number, text, choice, date) and "You decide"; "Send answers".
- `plan`: numbered stages with their `makes` lines and owner, "Leave this out" per stage, "Looks good", "Change something", "Stop".
- `stage`: the stage title, every row as a line with "Leave this one out", "Do this", "Not this one", "Stop"; after it runs, the results (done / failed and why).
The Missions page shows a planned mission as its stages with their states (a stepper), the current ask on top. The occasion page's Argyle line (slice 1's back-link) shows "Plan: stage 3 of 5 — Supplies". No browser dialogs; the existing `promptInput`/`promptChoice`/`promptConfirm`.

## Section 7 — Money and model

A planned mission costs one planner call per action (interview, answers, plan, each stage, the finish): about eight to twelve calls for a party. It runs on the mission tier (the selected provider's pro pool, the paid key) under the existing step and daily caps; `mission_step_cap` is checked against the stage count at plan time (a plan whose stages cannot fit the cap is refused with words). No new pool.

## Section 7b — Visibility

Everything slice 1 holds: a planned mission bound to a parents-only occasion is parents-only (its interview answers, plan and stage cards included); stage proposals carry their mission origin; gift rows follow the occasion arc's `_gift_visibility` (private to the planners, never on a kiosk).

## Section 8 — Tests (before the code)

`tests/test_planned_missions.py` — the interview action writes questions and waits; template questions merge first; answers by card and by prose; "you decide"; the plan action; plan approval with stale-rev refusal and per-stage drop; the stage action rejects non-proposable tools and more than 15 rows; "Do this" runs every proposal in order and records partial failures; a subject_rev change refuses the stage; a steer replans; stage 1's created occasion binds as the subject and ABOUT appears next step; caps. `tests/test_planned_missions_party.py` — the acceptance run with a scripted planner: "help me plan Kate's 10th birthday on February 14" → interview (headcount, cake, theme, gifts, where) → plan (occasion + guests, food, supplies, presents, invitations as drafts) → five stage approvals → the occasion has guests, a menu, a supplies list, a cake errand, a private gift list, drafts; the gap report closes the mission; nothing written before its stage was approved. `tests/test_planned_mission_cards.py` — node runs of the three card kinds. Router: "yes, do the menu" in chat approves the pending stage; "make it pizza instead" on a proposed stage steers it.

## Open questions for the user

1. May a stage be approved by words in chat, or only by tap? (ASSUMED: words, like other proposals today.)
2. Interview as one card with up to five questions plus one-at-a-time in chat? (ASSUMED: yes.)
3. Should Argyle start a plan on its own for any multi-part goal, or only when the person says "plan" / "help me plan"? (ASSUMED: the planner decides, and a plan always shows before anything is written.)

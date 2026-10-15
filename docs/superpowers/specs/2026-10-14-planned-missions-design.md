# Planned missions — an interview, a plan you can see, and stages you approve

**Date:** 2026-10-14. **Status:** REVISED for generality at the user's direction (2026-10-14: "this has to work with anything someone might want to plan — trip, long-term goal, etc. — or have a multi-stage mission for"); the first draft's Codex adversarial review (twelve findings, F1–F12) stays folded in; the revision goes back through Codex before the user approves it. Slice 2 of three (slice 1: subjects, BUILT v2.499.459–.472; slice 3: wake conditions).
**Builds on:** `2026-10-14-mission-subject-resolver-design.md` (subjects, `subject_rev`, `subject_history`, ABOUT, audience inheritance, guarded retarget), `2026-09-04-mission-engine-design.md` (the planner loop, READ/PROPOSE, the proposal rail), `2026-10-10-browse-missions-design.md` and the submit gate (browse, release, hand-off), `2026-09-02-mind-plans-design.md` (plans with per-step approval), `docs/occasion_design.md` O2, `2026-08-28-programs-design.md` (the curator), the mid-mission steer (v2.499.458), mission chat cards (v2.499.453).

## Problem

The user (2026-10-14): "a thread or mission could be 'help me plan my Disney trip' or 'help me plan Kate's birthday party' and go through the stages … create the trip or occasion, fill in the attractions, accommodations, guest list, menu … and build the thing for you." And: "I want to learn piano" → a program that adapts, a place to take lessons, a piano, books. And: "this has to work with anything someone might want to plan."

Three things stop that today, beyond one-action-at-a-time missions:
1. **Missions cannot reach most of what Argyle can do.** 29 tools Argyle uses in chat are dispatched by special router code and are absent from the registry missions use: trip itinerary scheduling, flights and rules; creating a program, logging a session, program progress; thread notes, closing, next step, drafting; household tasks; requests; web research; reading the calendar.
2. **Nothing can CREATE a trip or a list** as a tool (trips are made on the Trips page; lists only through occasion sourcing).
3. **A stage that is not a batch of writes has no shape.** "Find piano lessons nearby", "find a used piano", "get dining reservations" are research, browsing, threads and questions.

## Decisions (with the user, or ASSUMED and accepted 2026-10-14)

- **One engine for any goal.** A planned mission is an ordinary mission with a `plan`. The planner decides when a goal deserves one; a plan always shows before anything is written (accepted).
- **Two kinds of stage** (G3). A **build** stage is a batch of writes behind one approval. A **work** stage is a sub-goal Argyle pursues with its normal loop (READ tools, research, browse, threads, questions); approving it means "go do this part", and any write it wants comes back to the person as a build stage.
- **Missions get every chat tool** (G1), through the same registry, with the same actor rules chat uses; named exceptions only.
- **A stage contract, not an occasion allow-list** (G2). A tool may be a build-stage row when it has a contract entry: which arguments are record ids, whether it takes an idempotency key, what it creates, and whether it calls a model. Slice 2 writes contracts for every write in eight domains (occasions, trips, programs, lists, errands, events, threads, household tasks). Anything else is refused as a row with "not stage-ready yet" in words.
- **Approval by tap, or by the person's words in a private conversation** (accepted). Never from a group or family channel. Releasing contact details and booking stay tap-only (locked).
- **Interview: one card with up to five questions, and one at a time in conversation** (accepted).
- **Presents list shared with every parent except the honoree** (accepted).
- **Three acceptance runs** (G4): Kate's birthday party (mostly build), the Disney trip (build plus a work stage that meets Disney's login wall and hands off), learn piano (a program plus work stages for lessons and an instrument).
- **Out of scope:** stages that wait for a date or an event, and a program that adapts as sessions are logged (slice 3, reusing Section 4's runner); sending anything outside the family (drafts only); buying or paying.

## Section 1 — The record

The mission row gains `plan: Optional[dict]`, absent on every existing mission:

```
plan = {
  'state': 'interviewing' | 'proposed' | 'approved' | 'running' | 'done' | 'stopped',
  'rev': int,
  'questions': [{'key', 'ask', 'kind': 'yesno'|'number'|'text'|'choice'|'date', 'choices': [...], 'why',
                 'source': 'template'|'planner', 'template_key': str | None,
                 'answer': value | None, 'you_decide': bool, 'answered_by': member_id | None}],
  'stages': [{'id', 'kind': 'build' | 'work', 'title', 'why', 'makes': [...], 'owner_member_id': id | None,
              'state': 'pending'|'proposed'|'running'|'done'|'partial'|'uncertain'|'skipped',
              'snapshot': digest | None, 'subject': [kind, id, rev] | None,
              # build stages
              'rows': [{'id', 'tool', 'args', 'summary', 'needs': [row_id], 'resumable': bool,
                        'state': 'proposed'|'excluded'|'running'|'done'|'failed'|'skipped'|'uncertain',
                        'proposal_id', 'idem', 'result': {'status', 'message', 'created': [{'kind','id'}]}}],
              # work stages
              'goal': str, 'step_budget': int, 'steps_used': int, 'found': {...}, 'summary': str}],
  'approved_by': id | None, 'approved_at': ts | None,
}
```

Caps: 5 questions per round, 2 rounds; 7 stages; 15 rows per build stage; 3 model-calling rows per build stage; a work stage's `step_budget` at most 12 planner steps.

## Section 2 — Registry parity (G1)

Every tool `agent_tools_v2.get_available_tools()` declares to chat gets a registry handler, so missions (and the Mind's bind rail) reach it. The router's special dispatch shows what each needs: an actor resolved at dispatch, never taken from the model. Registry adapters take the actor the mission supplies: the **finder** for reads (slice 1: the creator, else the parent of record), the **approver** for writes (the parent who approved the stage). A parity test asserts `declared ⊆ TOOL_HANDLERS` minus a named exception list:

- `send_direct_message` (already excluded from missions: DMs are private space), `announce_to_room` (speaks in a room; never from a mission), `prepare_voice_approval` (voice controller only).

Reads join `missions.READ_TOOLS` (calendar events, program progress, thread list, household tasks, requests, coverage); writes become proposable. `research_question` maps to the planner's existing `research` action rather than becoming a second path.

## Section 3 — The stage contract (G2)

`services/planned.py` holds `CONTRACT = {tool: {'targets': {arg: kind}, 'idem': bool, 'creates': kind | None, 'model_calls': int}}`. A build row's tool must have an entry. For each `targets` argument the row must pass an id (a literal or a `$ref` to an earlier row's created record of that kind); name lookups inside a stage are refused (F6). Tools with `idem: true` receive the row's `idem` and return the existing record on a repeat; tools without it run once and become `uncertain` on a restart (`resumable: false`).

Slice 2's contract, by domain (NEW = a tool added here, each with a hand path on its owning page):

| Domain | Tools |
|---|---|
| Occasions | `add_occasion` (creates occasion, idem), `add_occasion_guests`, `set_occasion_attendance` (gain `occasion_id`), NEW `answer_occasion_question`, NEW `stamp_occasion_template`, NEW `add_occasion_dishes` (occasion-scoped, F11), NEW `set_occasion_menu`, `source_for_occasion` (gains `occasion_id`, model 1), NEW `add_occasion_gift_list` (private presents list, F1) |
| Trips | NEW `create_trip` (a draft trip: title, location, dates, travellers; creates trip; hand path: the Trips page's New trip, exists), `add_trip_poi` (gains `idem`, `category`, `meal_type`; creates poi), `add_trip_accommodation` (registry handler exists; declared to chat), `manage_trip_flights` (adapter; model 1 when it parses text), `auto_schedule_trip_itinerary` (adapter) |
| Programs | `propose_program` (adapter; creates program as a PROPOSAL the person approves on the Programs page, as today; model 1 for the curator) |
| Lists | NEW `create_list` (name, audience household or private with `shared_with`; creates list; hand path: the Lists page's New list, exists), `add_shopping_items` (gains `list_id`) |
| Errands, events | `add_errand`, `create_event` (chat_actions admin actions; gain `idem` and `created`) |
| Threads | `create_thread` (creates thread), `add_thread_note`, `draft_thread_message` (adapters; drafts are never sent) |
| Household tasks | `add_household_task` (adapter; creates task) |
| Messages to send yourself | `draft_message` (mission-local; stores the words on the mission; Copy / Share on the done card) |

## Section 4 — The planner's actions and the two stage kinds (G3)

Allowed only while their phase is current:

- `interview` / `answers` / `plan` as in the first draft (interview answers stay on the mission, F7; template questions merged by `template_key`; `plan` refused when the step budget cannot cover the stages: `mission_step_cap − step_count < Σ(build stages × 1 + work stages × step_budget) + 2`, F12).
- `stage` (build): `{"stage_id", "rows": [...]}` for the next approved pending build stage; each row checked against `CONTRACT`; one ordinary proposal per row stamped `origin_*`, `stage_id`, `row_id`, executable only by the runner (F4); a fresh `snapshot` (F2).
- `work` (start): approving a work stage sets it `running`; from then each planner step sees a `CURRENT STAGE: <title> — <goal>` block above the transcript and may use every normal action (READ tools, `research`, `browse`, `ask_user`, `subject`, and proposals, which are queued as rows of a follow-up build stage rather than sent one by one). Release, submit and hand-off work exactly as in browse missions inside a work stage.
- `stage_done`: `{"stage_id", "summary", "found": {...}}` closes the running work stage; its `found` is shown on the card and carried to later stages. A work stage that spends its `step_budget` ends `partial` with "carry on?" offered.

## Section 5 — The stage runner (F3, F4, F5, F6), unchanged from the first draft

One door, `planned.run_stage(mission_id, stage_id, snapshot, actor)`: claim under `db_lock` (state, snapshot, subject triple, approver rule) → `running`; rows in order with `needs`, `$ref` resolution, per-row claim and persisted state before and after each handler, `idem` for resumable tools; results kept as `{status, message, created}` (`chat_actions.act_on_proposal` keeps `created` and stores it); restart reconciliation turns `running` rows `uncertain` (never re-run); 120 s bound; model-calling rows charged to the day's pro-call cap before they run; direct proposal endpoints and the `do` verb refuse stage rows; the mission proposal route checks ownership and visibility. A build stage that creates a record while the mission or its thread has no subject binds it (`subject_rev` + 1, `subject_history`). Work stages do not use the runner (they are planner steps); their proposals arrive as a build stage that does.

## Section 6 — Answering, approving, changing

As in the first draft, with the verbs renamed because `plan` is the Mind's insight verb: `approve_plan` (options carry `rev`; "Looks good", "Leave this out" per stage, "Change something" = a steer, "Stop") and `run_stage` (options carry the snapshot for build stages; "Do this" / "Go do this part" for work, "Leave this one out" per row, "Not this one", "Stop"). Approver = a parent or adult who may see the mission's whole subject set (F9). Free text on a waiting plan or stage is a steer, never an approval. A proposed or running stage blocks `subjects.retarget`.

## Section 7 — Cards, keepers, and where words go (F9, F10)

The mission chat card gains `interview`, `plan`, `stage` (build: every row; work: the goal and, when done, what it found). The Missions page shows a planned mission as a stepper. The subject's page shows "Plan: stage n of m — <title>" (occasion card, trip page, program row — slice 1's back-link). Keepers who may not see the subject get a redacted view everywhere. Cards and results go only to private conversations of members who may approve; group and family channels get "I've sent the details to your Argyle chat"; speakers read a plan only for a spoken-safe subject and never presents. No browser dialogs.

## Section 8 — Money, model, time (F12)

One planner call per action: about ten for a party, more for a trip with a dining work stage, bounded by the plan-time budget check. Model-calling rows are charged before they run, at most 3 per build stage. A build stage run is bounded at 120 s; a work stage by its `step_budget`.

## Section 9 — Tests (before the code)

- `tests/test_registry_parity.py`: every declared tool has a registry handler except the named three; each adapter resolves its actor from the caller, never the model; READ_TOOLS gains the reads.
- `tests/test_stage_contract.py`: every contract entry names a real handler; a target argument refuses a name; idem tools return the same record twice; `resumable: false` rows become `uncertain` on restart.
- `tests/test_planned_missions.py`: the first draft's list (interview held on the mission, plan approval and stale rev, snapshots, concurrent approval runs once, `$ref`, failed prerequisites skip dependents, created results, restart reconciliation, direct endpoints refuse stage rows, retarget blocked, budget refusal, nested-call cap) plus work stages: approval starts it, CURRENT STAGE leads the prompt, proposals inside it become a follow-up build stage, `stage_done` closes it with `found`, the step budget ends it `partial`.
- Acceptance, each with a scripted planner on the REAL registry: `tests/test_planned_party.py` (Kate's 10th: interview, five build stages, a last-year occasion of the same title untouched, a private presents list Kate cannot see, drafts, the gap report); `tests/test_planned_trip.py` ("help me plan our Disney trip in January": interview (dates, travellers, budget, must-dos, dining style) → build: `create_trip` + accommodation + attractions as POIs + dining as `category: 'food'` POIs + `auto_schedule_trip_itinerary` → the trip bound as subject → work: "get dining reservations" browses disneyworld.disney.go.com, meets the login wall, hands off with each restaurant and its scheduled window → finish); `tests/test_planned_piano.py` ("I want to learn piano": interview (who, starting point, minutes, days, budget) → build: `propose_program` → work: "find lessons nearby" (research + `create_thread` proposals drafted to two teachers) → work: "find a piano and books" (research) → build: `create_list` "Piano" with the books and a keyboard line, `draft_message` to the teachers → finish).
- `tests/test_planned_missions_audience.py` and `tests/test_planned_mission_cards.py` as in the first draft.

## Open questions

None from the user's last review. Two rulings in this revision, flagged for the user: (1) a write a work stage wants is not proposed on its own; it is gathered into a follow-up build stage the person approves as one; (2) `propose_program` stays a proposal the person approves on the Programs page even inside an approved stage, because the curator's plan is itself something a person reviews (the programs arc's rule).

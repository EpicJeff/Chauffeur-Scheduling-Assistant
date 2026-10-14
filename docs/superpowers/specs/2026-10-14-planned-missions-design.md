# Planned missions — an interview, a plan you can see, and stages you approve

**Date:** 2026-10-14. **Status:** DRAFT for the user's review. Codex adversarial review done (twelve findings, each verified against the code, all folded in below and named F1–F12 where they land). Slice 2 of three (slice 1: subjects, BUILT v2.499.459–.472; slice 3: wake conditions).
**Builds on:** `2026-10-14-mission-subject-resolver-design.md` (subjects, `subject_rev`, `subject_history`, ABOUT, audience inheritance, guarded retarget), `2026-09-04-mission-engine-design.md` (the planner loop, READ/PROPOSE, the proposal rail), `2026-09-02-mind-plans-design.md` (plans with per-step approval on a propose-only rail), `docs/occasion_design.md` O2 (template interview, cascades, stamping, gap report), the mid-mission steer (v2.499.458), mission chat cards (v2.499.453).

## Problem

The user (2026-10-14): "a thread or mission could be 'help me plan my Disney trip' or 'help me plan Kate's birthday party' and go through the stages of trip or party planning: create the trip or occasion, fill in the attractions, accommodations, guest list, menu, based on details you provide, volunteered or asked for through a questionnaire, and build the thing for you." And: "I want to learn piano" → a program that adapts, a place for lessons, a piano, books.

Today a mission advances one action at a time and every write is its own proposal card. A party would be twenty separate approvals with no picture of the whole, and nothing asks the family what it needs to know up front except one `ask_user` question at a time. The field feedback (2026-10-09) is the bar: every handle shows its plan before acting, nothing hand-wavy, and the least-engaged family member must be able to say yes or no.

## Decisions (made with the user, or ASSUMED for the user to correct)

- **One engine, not verticals.** A planned mission is an ordinary mission that carries a `plan`. Domain knowledge enters through the subject's own primitives (an occasion's template interview, stamping and menu; later a trip's scheduler, a program's curator). The user rejected per-domain verticals for the Mind; the same holds here.
- **Three phases, each visible.** Interview, plan, stages. **Nothing in the family's data is written before the person approves the stage that writes it** — interview answers included (F7).
- **One approval per stage** (the user, 2026-10-14). A stage runs its rows through ONE guarded stage runner, never through the per-proposal endpoints (F3, F4).
- **ASSUMED: approval by tap, or by the person's own words in a conversation only they and Argyle are in** (their Argyle DM, the PWA widget, a verified speaker for a spoken-safe subject). In a group or family channel Argyle never approves a stage and answers neutrally (F10). Releasing contact details and booking stay tap-only (locked).
- **ASSUMED: the interview is a card with all its questions (at most five) and, in conversation, one question at a time;** a person may answer several in prose; every question offers "You decide".
- **First target: Kate's birthday party.** Slice 2's tool work is scoped to it (F8). Trips and programs reuse the same engine in follow-up targets once their tools are registered and return ids; they are named in Section 9, not built here.
- **Out of scope:** stages that wait for a date or an event (slice 3, which reuses Section 4's execution contract), sending anything outside the family (messages are drafts the person sends), buying or paying, guests' contact details.

## Section 1 — The record

The mission row gains `plan: Optional[dict]`, absent on every existing mission (free-text missions are untouched):

```
plan = {
  'state': 'interviewing' | 'proposed' | 'approved' | 'running' | 'done' | 'stopped',
  'rev': int,                                   # bumps on every change to questions, stages or rows
  'questions': [{'key', 'ask', 'kind': 'yesno'|'number'|'text'|'choice'|'date', 'choices': [...], 'why',
                 'source': 'template'|'planner', 'template_key': <occasion template key> | None,
                 'answer': <value> | None, 'you_decide': bool, 'answered_by': member_id | None}],
  'stages': [{'id', 'title', 'why', 'makes': ['<one line per thing it will create>'], 'owner_member_id': <id> | None,
              'state': 'pending'|'proposed'|'running'|'done'|'partial'|'uncertain'|'skipped',
              'snapshot': '<digest>' | None,        # F2: covers row ids, tools, args, exclusions, subject triple
              'rows': [{'id', 'tool', 'args', 'summary', 'needs': [row_id, ...],
                        'state': 'proposed'|'excluded'|'running'|'done'|'failed'|'skipped'|'uncertain',
                        'proposal_id', 'result': {'status', 'message', 'created': [{'kind','id'}]}, 'idem': '<key>'}],
              'subject': [kind, id, rev] | None}],
  'approved_by': member_id | None, 'approved_at': ts | None,
}
```

Caps: at most 5 questions per round and 2 rounds; at most 7 stages; at most 15 rows per stage; at most 3 rows per stage that call a model themselves (F12, Section 7).

## Section 2 — The planner's new actions

Allowed only while their phase is current (the step refuses others with a `refused` note):

- `{"action":"interview","questions":[...]}` → `plan.questions`, state `interviewing`, ask step `interview`, `waiting_user`. When the subject is an occasion whose template has unanswered questions (`occasions.interview(id)`), those come first with `source: 'template'` and their `template_key`. For a party with no occasion yet, the planner includes the birthday template's questions by kind (`occasions.TEMPLATES['birthday']['questions']`), marked `template_key` the same way, so they can be replayed once the occasion exists (F7).
- `{"action":"answers","values":{key: value}}` → turns a person's prose (a `user_answer`) into answers on the card; the card shows them back.
- `{"action":"plan","stages":[...]}` → `plan.stages`, state `proposed`, ask step `plan`. Refused when `remaining planner attempts < stages + 2` (Section 7).
- `{"action":"stage","stage_id":"…","rows":[{"tool","args","summary","needs":[…]}]}` → the next approved pending stage only. Each row's tool must be on the stage allow-list (Section 5), never a READ. A row may reference an earlier row's created record with `{"$ref": "<row_id>", "kind": "occasion"}` in an argument (F6). The stage turns `proposed` with a fresh `snapshot`; one ordinary action proposal per row is created with `origin_kind/origin_id/stage_id/row_id` (so it shows on the mission's history) and is EXECUTABLE ONLY BY THE STAGE RUNNER (F4). Ask step `stage`.

The system prompt states the phases, the caps and the allow-list, and tells the planner: interview only for what no READ tool or ABOUT already says; stages a person would recognise (create the party and its people, food, things to buy, presents, errands, messages to send); after the last stage, finish with what is left (`occasions.gap_report`).

## Section 3 — Answering, approving, changing

- **Interview answers stay on the mission** (F7). `missions.answer_plan(mission_id, answers, actor)` writes only `plan.questions` (parent/adult; `you_decide` is a flag, never a value). Nothing reaches the occasion during the interview. The stage that creates or touches the occasion carries `answer_occasion_question` rows for every `template_key` answer (replayed after creation via `$ref`), so cascades (headcount → kitchen) happen inside an approved stage; `you_decide` answers are left out of those rows and the planner's choice is written as a normal row the person sees.
- **Plan approval.** Verb `plan` options: "Looks good" (`plan:<rev>:approve`), "Leave this out" per stage (`plan:<rev>:drop:<stage_id>`), "Change something" (free text, a steer → replan, `rev` + 1), "Stop". A stale `rev` answers "the plan moved; look again". Approving writes nothing.
- **Stage approval.** Verb `stage` options: "Do this" (`stage:<stage_id>:<snapshot>:approve`), "Leave this one out" per row (`stage:<stage_id>:<snapshot>:exclude:<row_id>` → `rev` + 1, new snapshot, a new card), "Not this one" (skip), "Stop". The option id carries the SNAPSHOT digest (F2): any change to rows, args, exclusions or the subject makes every earlier button stale.
- **Who may approve** (F9): a parent or adult for whom `subjects.visible` holds for the mission's whole subject set (current and history), checked by the runner itself, not only by `can_see` (keepers see the row, never approve).
- **Free text on a waiting plan or stage is a steer, never an approval** (`TAP_ONLY_ASKS` gains `plan` and `stage` for free-text routing); approval in words goes through the approval verb in a private conversation (Decisions).
- **Retarget and steer.** A proposed or running stage blocks `subjects.retarget`. A steer while a plan is proposed replans; a steer while a stage is proposed withdraws its proposals (status `withdrawn`) and re-proposes it.

## Section 4 — The stage runner: one guarded, atomic, resumable execution (F3, F4, F5, F6)

`missions.run_stage(mission_id, stage_id, snapshot, actor)`:
1. **Claim** under `storage.db_lock`: the mission waits on this stage's ask, the stage is `proposed`, its `snapshot` equals the given one, the mission's current subject triple equals the stage's, the actor passes Section 3's approval rule; then stage → `running` and the ask is settled. A second tap finds `running` and answers "already doing it".
2. **Rows in order.** Each row: skip (`skipped`, "needs <row> which did not complete") when a `needs` row is not `done`; resolve `$ref` arguments from the referenced row's `result.created` (refuse the row if missing); claim the row (`proposed` → `running`) and its proposal (`proposed` → `executing`) under the lock, persisting both BEFORE the handler runs; run the tool through `chat_actions` execution with the approving actor; persist `result` = `{status, message, created}` and row/proposal states (`done` / `failed`) right after. `created` is a typed list each stage-allowed tool returns (`[{'kind': 'occasion', 'id': …}]`); `chat_actions.act_on_proposal` is extended to keep handler fields `created` and to store the normalized result on the proposal row (F5).
3. **Idempotency.** Each row carries `idem` = hash(mission, stage, row, snapshot). Tools that create (occasion, list, errand, dishes) accept an idempotency key and return the existing record when they see it again.
4. **Restart.** On add-on start (and in the missions tick), a stage left `running` is reconciled: rows `running` become `uncertain` (never retried automatically), the stage becomes `uncertain`, and the card asks "Check these: …" with the rows named; a person marks each done / not done, or the planner re-proposes the not-done ones as a new stage.
5. **Finish.** All rows `done` → stage `done`; any `failed`/`skipped` → `partial`, failures named on the card and in the transcript; the planner then proposes a repair stage or moves on.
6. **Direct endpoints refuse stage rows** (F4): `/api/action-proposals/{id}/act`, the mission proposal approve route, and the situation `do` verb refuse a proposal with `stage_id` ("approve it as part of its stage"). The pre-existing gap the review found in the mission proposal route — no check that the proposal belongs to the mission or that the actor may see the mission — is fixed in the same change.

Slice 3's wake-driven stages run through this same runner.

## Section 5 — The stage allow-list and the tools it needs (F6, F8, F11, F1)

Only these tools may be stage rows in slice 2; each takes explicit ids (never a name lookup inside a stage), accepts `idem`, and returns `created` when it creates something:

| Tool | Status | Notes |
|---|---|---|
| `add_occasion` | exists | gains `idem`, returns `created: [{occasion, id}]` |
| `add_occasion_guests` | exists | gains `occasion_id` (the name path stays for chat; a stage must pass the id) |
| `set_occasion_attendance` | exists | gains `occasion_id` |
| `answer_occasion_question` | NEW | `occasions.answer(id, key, value)`; hand path: the occasion page interview (exists) |
| `stamp_occasion_template` | NEW | `occasions.apply_template(id, keys)`; hand path: apply-template button (exists) |
| `add_occasion_dishes` | NEW | `occasions.add_dishes(id, description)` — occasion scope and tags, never the everyday repertoire (F11); returns dish ids; hand path: the occasion menu (exists) |
| `set_occasion_menu` | NEW | `occasions.set_menu(id, dish_ids)`; hand path: the occasion menu picker (exists) |
| `source_for_occasion` | exists | gains `occasion_id`; counts as a model-calling row |
| `add_occasion_gift_list` | NEW (F1) | creates the presents list as `audience: 'private'`, `shared_with` = every active parent except the honoree (and except anyone the occasion's `whose_party` names); refuses when that leaves nobody; rows of gift picks go on it; hand path: the occasion page's gift panel gains "Make a private presents list" |
| `draft_message` | NEW, mission-local | not a registry write: the row stores a drafted text on the mission (to, words); the done card shows it with Copy / Share (the share-out sheet); nothing is sent |

`suggest_gift_ideas` stays a READ the planner uses before proposing the gift rows. Trip and program tools are NOT on slice 2's allow-list (Section 9).

## Section 6 — The hand path, the cards, and where words go (F9, F10)

- **Cards.** The mission chat card gains `interview` (each question with its control and "You decide"; "Send answers"), `plan` (numbered stages, `makes` lines, owner, "Leave this out", "Looks good", "Change something", "Stop") and `stage` (every row, "Leave this one out", "Do this", "Not this one", "Stop"; afterwards each row's result). The Missions page shows a planned mission as a stepper with the current ask on top; the occasion page's Argyle line shows "Plan: stage 3 of 5 — Supplies".
- **Keepers get a redacted view** (F9). A creator or owner who may not see the subject (only possible after a parent's hand retarget) sees "Stage 3 of 5, waiting on a parent" and no questions, answers, rows, results or drafts, on every surface (cards, Missions page, `/api/missions/{id}`, DMs). Their DM ask carries no subject words.
- **Recipient-aware delivery** (F10). Interview, plan and stage cards and every stage result go only to the private conversations of members who may approve (Section 3). In a group or family channel, Argyle answers a question about a planned mission with "I've sent the details to your Argyle chat" and posts nothing of the plan; family-channel bodies therefore never carry plan content into the Mind's snapshot. On a speaker, only a spoken-safe subject's plan is read aloud, and never presents.
- No browser dialogs.

## Section 7 — Money, model and time (F12)

- One planner call per action: about eight to twelve for a party. **Budget at plan time**: the plan is refused with words when `mission_step_cap − step_count < stages + 2` (one stage call each, plus finish and slack), or when the day's `mission_cap_pro_calls` cannot cover it.
- **Nested model calls**: a row whose tool calls a model (`source_for_occasion`, `add_occasion_dishes` when it parses text) is a model-calling row: at most 3 per stage, each counted against `mission_cap_pro_calls` before it runs; a cap reached mid-stage stops the stage at that row (`partial`, "the day's limit"), resumable tomorrow.
- **Time**: a stage run is bounded at 120 s; rows still pending at the bound are left `proposed` and the stage `partial` with "carry on" offered.

## Section 8 — Tests (before the code)

`tests/test_planned_missions.py`: the four actions and their phase gates; interview answers stay on the mission (no occasion write, no kitchen write); `you_decide` never reaches a domain call; plan approval, stale `rev`, per-stage drop; stage rows only from the allow-list, at most 15, at most 3 model-calling; the snapshot in the option id and a stale card refused after "Leave this one out"; the runner's claim (a concurrent second approval answers "already doing it" and runs nothing twice); rows in order, `$ref` resolution, a failed prerequisite skips its dependents; the stored normalized result with `created`; a restart turns `running` rows `uncertain` and never re-runs them; direct proposal endpoints refuse stage rows; the mission proposal route checks ownership and visibility; retarget refused while a stage is proposed or running; a subject change makes the stage stale; the plan-time budget check; the nested-call cap stops a stage resumably.
`tests/test_planned_missions_party.py`: the acceptance run with a scripted planner on the REAL registry: "help me plan Kate's 10th birthday on February 14" → interview (headcount, cake, theme, gifts, budget) → plan (party and guests; food; supplies; presents; invitations to send) → stage 1 creates the occasion through `add_occasion`, replays the template answers, binds the occasion as the subject → stages 2–5 by id, never by name (a last-year "Kate's birthday" occasion exists in the fixture and is untouched) → the occasion has guests, a menu of occasion-scoped dishes, a supplies list, the cake errand, a private presents list Kate cannot see, and invitation drafts; the gap report closes the mission; nothing written before its stage was approved.
`tests/test_planned_missions_audience.py`: keeper redaction on every surface; group and family channel answers are neutral and carry no plan words; a spoken plan never names presents; the Mind snapshot never sees plan content.
`tests/test_planned_mission_cards.py`: node runs of the three card kinds and the stepper.

## Section 9 — Next targets on the same engine (not built here)

- **Trips**: register `auto_schedule_trip_itinerary` and `manage_trip_flights` (absent from the registry today), make trip creation and `add_trip_poi` take ids and return `created`, add them to the allow-list.
- **Programs**: register `propose_program` (absent from the registry today) as a stage row returning the program id; a program becomes a stage of "learn piano", with lessons (a thread) and buying (research + drafts) as other stages.
- **Waiting stages** (slice 3): a stage with `not_before` or `on_event` runs through Section 4's runner when woken.

## Open questions for the user

1. May a stage be approved by words in a private conversation, or only by tap? (ASSUMED: words, in private only.)
2. Interview as one card with up to five questions plus one-at-a-time in conversation? (ASSUMED: yes.)
3. Should the planner start a plan on its own for any multi-part goal, or only when the person says "plan" / "help me plan"? (ASSUMED: the planner decides; a plan always shows before anything is written.)
4. Presents list shared with every parent except the honoree — or only with the parent who approved the stage? (ASSUMED: every parent except the honoree.)

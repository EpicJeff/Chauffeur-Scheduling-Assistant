# Planned missions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A mission can carry a plan: an interview the family answers, a plan of stages they approve, and stages that each write a batch of rows through one guarded, atomic, resumable runner — first target "help me plan Kate's 10th birthday".

**Architecture:** `plan` lives on the mission row. Four planner actions (interview, answers, plan, stage) feed it; a new module `services/planned.py` owns the plan record, the stage allow-list, snapshot digests, `$ref` resolution and the stage runner; existing proposals carry `stage_id` and are executable only by that runner. Occasion tools gain ids, idempotency keys and typed `created` results; four occasion tools and a private presents list are new. Cards render three new ask kinds; delivery is recipient-aware.

**Tech Stack:** Python / FastAPI / document storage, the mission planner (`services/missions.py`), the proposal rail (`services/chat_actions.py`), occasions (`services/occasions.py`), situations cards (`services/situations.py`, `static/situations.js`), the mission chat card (`templates/app.html`), plain-script tests from `chauffeur/` with `HA_BASE_URL` unset; node + jsdom for cards.

**Spec:** `docs/superpowers/specs/2026-10-14-planned-missions-design.md` (approved by the user 2026-10-14 with every ASSUMED decision accepted: approval by words in a private conversation; one card plus one-at-a-time in chat; the planner decides when to plan; the presents list shared with every parent except the honoree).

## Global Constraints

- Tests from `chauffeur/`, `HA_BASE_URL` unset; the change's own tests plus named neighbours only.
- Every new route gets a rule in `services/auth.py`.
- No browser dialogs (`promptInput`, `promptChoice`, `promptConfirm`, `showGlobalAlert`).
- `python tools/build_tailwind.py` after any template class change.
- Free-text missions (no `plan`) behave exactly as today.
- Nothing in the family's data is written before the stage that writes it is approved; interview answers stay on the mission.
- Caps: 5 questions per round, 2 rounds; 7 stages; 15 rows per stage; 3 model-calling rows per stage; stage run bounded at 120 s.
- Stage rows run only through `planned.run_stage`; per-proposal endpoints refuse a proposal with `stage_id`.
- Verbs: `approve_plan` (plan approval) and `run_stage` (stage approval) — `plan` is already the Mind's insight verb.
- Codex split: Claude writes each task's tests first and reviews; Codex implements via `codex:codex-rescue`; Claude gates, bumps `config.yaml`, updates `system_capabilities.md`, commits and pushes per task.

## Review Focus

1. Two parents tap "Do this" on the same stage within a second: one runs, the other answers "already doing it"; no row runs twice. Test in Task 5.
2. A last-year occasion with the same title exists: every stage row addresses the new occasion by id; the old one is untouched. Test in Task 9.
3. The add-on restarts mid-stage: rows that were running become `uncertain` and are never re-run on their own. Test in Task 5.
4. The honoree is a parent (a parent's own birthday): the presents list excludes them and is shared with the other parents; when no other parent exists it refuses. Test in Task 3.
5. A person types "yes" in the family channel while a stage waits: nothing is approved, Argyle answers neutrally. Test in Task 8.

---

### Task 1: The plan record, interview and answers

**Files:** Create `services/planned.py`; modify `services/missions.py` (planner actions `interview`, `answers`; `_user_prompt` shows answers above the transcript; free text on a waiting interview is a `user_answer`); `services/storage.py` (`add_mission` default `plan: None`). Test: `tests/test_planned_missions.py` (block A).

**Interfaces produced:** `planned.CAPS = {'questions': 5, 'rounds': 2, 'stages': 7, 'rows': 15, 'model_rows': 3, 'stage_seconds': 120}`; `planned.new_plan() -> dict`; `planned.set_questions(mission_id, questions, subject) -> plan` (merges `occasions.interview` template questions first when the subject is an occasion, else the birthday template's questions by kind when the goal is a party, each with `template_key`); `planned.answer_plan(mission_id, answers: dict, actor) -> {status, message}` (parent/adult; `'you_decide'` sets the flag, never a value; never touches the occasion); `planned.answers_text(plan) -> str` for the prompt.

Tests (A): the `interview` action writes questions, state `interviewing`, ask `interview`, `waiting_user`; template questions first with `template_key`; more than 5 questions or a third round refused with a `refused` note; `answer_plan` by card (dict) and the planner's `answers` action from prose; `you_decide` flag; all answered → `running`; NO occasion write and NO kitchen write during the interview (spy `occasions.answer`, `meals.set_plate_hosting`); a child refused; a free-text mission without a plan unchanged (existing tests stay green).

Neighbours: `test_missions_engine.py`, `test_mission_steer.py`, `test_mission_subject.py`, `test_start_mission.py`.

### Task 2: The plan action, budget, and plan approval

**Files:** `services/planned.py` (`set_stages`, `plan_options`, `approve_plan`, `drop_stage`, `rev` bumps); `services/missions.py` (`plan` action with the budget check; steer while proposed → replan); `services/situations.py` (verb `approve_plan`, options `approve_plan:<rev>:approve|stop|drop:<stage_id>`, routing in `act`/`_run`; `TAP_ONLY_ASKS` gains `plan` for free-text routing); `static/situations.js` VERB_LABELS. Test: block B.

Tests (B): the `plan` action writes 1–7 stages (8 refused); refused when `mission_step_cap − step_count < stages + 2` or the day's pro-call budget cannot cover it, with words; options carry `rev`; approve → `approved`, nothing written; drop a stage → `rev` + 1 and the old option is stale ("the plan moved; look again"); "Change something" is a steer → replan; stop → mission `dropped`; free text on a proposed plan is a steer, never an approval; `approve_plan` refused for an actor the subject excludes.

### Task 3: Stage-ready occasion tools

**Files:** `services/agent_tools_v2.py` (`add_occasion` gains `idem`, returns `created: [{'kind':'occasion','id'}]` and `occasion_id`; `add_occasion_guests`, `set_occasion_attendance`, `source_for_occasion` gain `occasion_id` (name path kept for chat); NEW `answer_occasion_question`, `stamp_occasion_template`, `add_occasion_dishes` (→ `occasions.add_dishes`, returns dish ids), `set_occasion_menu`, `add_occasion_gift_list` (private: `shared_with` = active parents minus the honoree; honoree = the member named by the occasion's `whose_party` answer or matched from the title; refuses when nobody is left); schemas + handlers); `services/chat_actions.py` (`act_on_proposal` keeps the handler's `created` and stores `{status, message, created}` on the proposal row); `templates/occasions.html` (gift panel: "Make a private presents list" button calling a new `POST /api/occasions/{id}/gift-list` with an auth rule). Test: `tests/test_planned_occasion_tools.py`.

Tests: each new tool by id; `add_occasion` twice with the same `idem` returns the same id and creates one row; `add_occasion_dishes` dishes are `scope='occasion'` with the occasion's tags and absent from everyday composition (`meals` pool); the presents list is private, Kate (honoree) cannot see it (`scope.audience_allows`), both parents can; a parent honoree is excluded (Review Focus 4); no other parent → refused; `act_on_proposal` result carries and stores `created`; the hand-path endpoint makes the same list; every new tool is proposable (in `proposable_tools()`), none is a READ.

Neighbours: `test_occasions*.py` (list them with `ls tests | grep occasion`), `test_chat_actions*.py`.

### Task 4: The stage action, allow-list, snapshots, and direct-endpoint refusal

**Files:** `services/planned.py` (`ALLOW = {'add_occasion', 'add_occasion_guests', 'set_occasion_attendance', 'answer_occasion_question', 'stamp_occasion_template', 'add_occasion_dishes', 'set_occasion_menu', 'source_for_occasion', 'add_occasion_gift_list', 'draft_message'}`; `MODEL_ROWS = {'source_for_occasion', 'add_occasion_dishes'}`; `propose_stage(mission, stage_id, rows) -> stage`; `snapshot(stage, subject) -> str` = sha256 of row ids, tools, args, exclusions, subject triple; `exclude_row`); `services/missions.py` (`stage` action); `services/chat_actions.py` (`create_action_proposal(extra=...)` used with `stage_id`, `row_id`; `act_on_proposal` refuses a proposal with `stage_id` unless called by the runner); `main.py` (`/api/action-proposals/{id}/act` and `/api/missions/{id}/proposals/{pid}/act` refuse stage rows; the mission route also requires `prop.origin_id == mission_id` and `situations.can_see('mission', ...)` for the actor); `services/situations.py` (verb `run_stage`, options `run_stage:<stage_id>:<snapshot>:approve|skip|stop|exclude:<row_id>`; the `do` verb refuses stage rows); `services/subjects.retarget` (refused while a stage is `proposed` or `running`). Test: block C.

Tests (C): rows only from `ALLOW`; 16 rows refused; 4 model rows refused; only the next approved pending stage; proposals carry `stage_id`/`row_id`/`origin_*`; the option id carries the snapshot; "Leave this one out" → new snapshot, old button stale; a subject change makes the stage stale; direct endpoints and the `do` verb refuse stage rows; the mission proposal route refuses a proposal from another mission and an actor who may not see the mission; retarget refused while proposed.

### Task 5: The stage runner

**Files:** `services/planned.py` (`run_stage(mission_id, stage_id, snapshot, actor)`, `reconcile()`); `services/missions.py` (`tick` calls `planned.reconcile()` first; the add-on start calls it once — find the startup hook in `main.py`); `services/chat_actions.py` (`run_row(proposal_id, approver, idem)` — the runner's only door: claims `proposed → executing` under `db_lock`, executes, stores the result). Test: block D.

Sketch:

```python
def run_stage(mission_id, stage_id, snap, actor):
    with storage.db_lock:
        m = storage.get_mission(mission_id); plan = (m or {}).get('plan') or {}
        st = _stage(plan, stage_id)
        if not st or st['state'] != 'proposed':
            return {'status': 'success', 'already': True, 'message': 'Already doing it.' if st and st['state'] == 'running' else 'That stage has moved on.'}
        if st['snapshot'] != snap or list(missions.subject_of(m)) != list(st['subject'] or [None, None, 0]):
            return {'status': 'success', 'moved': True, 'message': 'That stage changed; look again.'}
        if not may_approve(m, actor):
            return {'status': 'refused', 'message': 'Only a parent who can see this plan can approve it.'}
        st['state'] = 'running'; st['started_at'] = time.time(); _save(mission_id, plan); _settle_stage_ask(mission_id, stage_id, 'Doing it')
    for row in st['rows']:
        ...  # needs → skipped; $ref → resolve or failed; time bound → leave proposed; model rows → budget; chat_actions.run_row(...)
    ...  # done | partial; bind created occasion as subject when unbound (subject_rev+1, subject_history); planner runs on
```

Tests (D): runs rows in order; a concurrent second call answers "already" and nothing runs twice (Review Focus 1: two threads, a barrier around the first handler); `$ref` resolves to the created occasion id; a failed prerequisite skips its dependents; results stored with `created`; all done → `done`; a failure → `partial` named; stage 1's created occasion binds as the subject and the next step's ABOUT shows it; `reconcile()` turns `running` rows `uncertain` and the stage `uncertain` with a "check these" ask, and never re-runs them (Review Focus 3); the time bound leaves rows `proposed` and the stage `partial` with "carry on"; a model row past the day's budget stops the stage resumably; `may_approve` uses the subject set (a keeper refused).

### Task 6: Drafts and the finish

**Files:** `services/planned.py` (`draft_message` row: stores `{to, words}` on the stage result, no registry write); `services/missions.py` (after the last stage: finish summary with `occasions.gap_report` for an occasion subject; plan state `done`). Test: block E.

Tests (E): a `draft_message` row writes nothing outside the mission; the done result lists the drafts; the finish names the gap report's open items; `plan.state` `done`.

### Task 7: The cards and the Missions stepper

**Files:** `services/missions.py` `ask_card` (kinds `interview`, `plan`, `stage` with their fields); `templates/app.html` `renderMissionAskCard` (the three kinds; controls by question kind; per-row "Leave this one out"; results after a run); `static/situations.js` (`act` flows for `approve_plan` and `run_stage`, interview submission via `POST /api/missions/{id}/plan/answers`); `main.py` (`POST /api/missions/{id}/plan/answers` → `planned.answer_plan`, auth rule); `templates/components/missions_page.html` (stepper: stages with states, current ask on top); `templates/occasions.html` (Argyle line shows "Plan: stage n of m — <title>"). Tailwind rebuild. Test: `tests/test_planned_mission_cards.py` (node + jsdom), plus a TestClient-style call of the answers endpoint.

### Task 8: Audience — keepers, channels, speakers, the Mind

**Files:** `services/planned.py` (`redacted(plan)`: states and counts only); `main.py` (`missions_detail`, `missions_admin` serve `redacted` to a keeper who may not see the subject); `services/missions.py` (`_dm_person` sends a keeper neutral words, no card); `services/agent_router.py` (in a group or family channel, a question about a planned mission answers "I've sent the details to your Argyle chat" and posts the details to the asker's DM; `approve_plan`/`run_stage` through `act_on_situation` refused unless the conversation is private — the asker's DM, the widget `conv:`, or a verified speaker with a spoken-safe subject); `services/voice_tools.py` / spoken prompt (a plan is read aloud only for a spoken-safe subject and never its presents rows). Test: `tests/test_planned_missions_audience.py`.

Tests: keeper redaction on `/api/missions/{id}`, the admin list, the mission card and the DM; group channel neutral reply and no approval from "yes" there (Review Focus 5); family channel the same; the DM gets the details; spoken: presents rows never in a spoken prompt; the Mind snapshot (`mind.snapshot()`) never contains plan questions, answers or rows.

### Task 9: Words in private, steer, and the party acceptance run

**Files:** `services/agent_tools_v2.py` (`act_on_situation` verbs `approve_plan`, `run_stage`, defaults to the pending one; router rule text); `services/agent_router.py` (a steer on a proposed plan/stage is `answer`, an approval is the verb); `tests/test_planned_missions_party.py` (the acceptance run with a scripted planner on the REAL registry, a last-year "Kate's birthday" occasion in the fixture — Review Focus 2).

Party run: "help me plan Kate's 10th birthday on February 14" → interview (headcount 14, cake yes, theme dinosaurs, gifts yes, budget 40) → plan (5 stages) → approve → stage 1: `add_occasion` + `answer_occasion_question` ×4 via `$ref` + `add_occasion_guests` + `stamp_occasion_template` → occasion bound as subject → stage 2 food: `add_occasion_dishes` + `set_occasion_menu` → stage 3 supplies: `source_for_occasion` → stage 4 presents: `add_occasion_gift_list` → stage 5 invitations: `draft_message` ×3 → finish with the gap report. Asserts: nothing written before each stage's approval; the new occasion has the guests, occasion-scoped menu, supplies list, cake errand, a private presents list Kate cannot see, three drafts; last year's occasion untouched; "yes, do the menu" in the private chat approves stage 2; "make it pizza" on stage 2 re-proposes it.

### Task 10: Docs, memory, final review

`system_capabilities.md` entry (BUILT, NOT device-verified, device steps), the spec status, the memory files (`mission-subject-model.md` → slice 2 built; MEMORY.md line), then the whole-branch Codex adversarial review, one fix wave, one scoped re-review.

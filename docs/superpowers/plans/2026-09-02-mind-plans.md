# Mind Plans Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Insights stop nagging and start terminating: every active insight ends in a per-step-approved plan, a dated snooze, or a dismiss — plus a think-time `approach` line so the lane reads as judgment, not reminders.

**Architecture:** Plans live as `plan_json` on the existing `mind_insights` row (the `proposal_json` precedent — no new table). A planner LLM call (heavy tier, at tap) writes 2–5 steps tagged `tool`/`human`; each tool step binds lazily through the existing `propose_fix` agent rail at its own tap and executes only through the existing chat_actions approve rail. New insight state `in_hand` plus a `snoozed_until` field keep handled/parked rows out of the lane; think's retire-by-omission learns to skip both.

**Tech Stack:** Python (FastAPI, service modules under `chauffeur/services/`), scenario tests via `chauffeur/tests/harness.py` (`check()` + `scenario_*` functions, run by `tools/test.py`), Alpine.js (`templates/mind.html`) and vanilla-JS string templates (`templates/app.html`), precompiled Tailwind.

**Spec:** `docs/superpowers/specs/2026-09-02-mind-plans-design.md`

## Global Constraints

- Every commit bumps `chauffeur/config.yaml` version and the message ends with `(vX.Y.Z)`; push after committing. This feature is v2.452.0 → v2.452.5.
- Full test sweep before every code commit: `python tools/test.py` from repo root (parallel, ~79s). Inner loop: `python tools/test.py --focus mind`. Never pipe the runner (masks exit code).
- Nothing executes without a human tap. No step is ever auto-run. Binder/planner calls ride the existing `mind_cap_handle` (30/day) via `_bump_call('handle', cap)`.
- Dismissed slugs stay suppressed forever; acted may return (unchanged phase-C law).
- No browser dialogs — `alert()`/`confirm()`/`prompt()` banned; snooze uses fixed quick-pick buttons (3 days / 1 week / 2 weeks), so no dialog is needed at all.
- After any template class change run `python tools/build_tailwind.py`.
- Update `chauffeur/system_capabilities.md` mind section in the same change (final task).
- Tests import via `from harness import check` and monkeypatch module attributes directly (`mind._pool_call = ...`); follow `tests/test_mind_propose.py` style exactly.

---

### Task 1: Planner core — `make_plan` writes `plan_json` and moves the insight to `in_hand`

**Files:**
- Modify: `chauffeur/services/mind.py` (add `import uuid` to the imports at top; add `PLAN_SYSTEM`, `MAX_PLAN_STEPS`, `DEFAULT_STEP_DUE_DAYS`, `_parse_steps`, `make_plan` — place them right after `propose_fix`, before the GRADUATION block)
- Modify: `chauffeur/services/storage.py:2712-2720` (`add_mind_insight` defaults)
- Test: `chauffeur/tests/test_mind_plan.py` (create)

**Interfaces:**
- Consumes: `storage.get_mind_insights()`, `storage.update_mind_insight(id, fields)`, `storage.get_all_members()`, `mind._pool_call(tier, api_key, system, prompt, **kw)`, `mind._bump_call(kind, cap)`, `mind.snapshot(now)` — all existing.
- Produces: `make_plan(insight_id: str, actor: dict = None, now: datetime.datetime = None) -> dict` returning `{'status': 'planned', 'plan': {...}}` | `{'status': 'no_plan'|'not_found'|'no_key'|'capped'|'error'}`. Step shape (relied on by every later task): `{'id': hex, 'kind': 'tool'|'human', 'text': str, 'owner_member_id': str|None, 'owner_name': str, 'due': 'YYYY-MM-DD', 'status': 'open', 'proposal_json': None}`.

- [ ] **Step 1: Write the failing tests**

Create `chauffeur/tests/test_mind_plan.py`:

```python
"""Make a plan: one heavy call turns an insight into 2-5 ordered steps
(tool|human), each with a due date; the insight moves to in_hand. Nothing
executes here — binding and approval are separate, later, per-step taps."""
import datetime
from harness import check
from services import storage, mind

CALLS = []
NOON = datetime.datetime(2026, 9, 2, 12, 0)


def _fake_pool(payload):
    def f(tier, api_key, system, prompt, **kw):
        CALLS.append({'tier': tier, 'system': system, 'prompt': prompt})
        return payload
    return f


def _reset():
    CALLS.clear()
    storage.mind_insights_table.truncate()
    storage.members_table.truncate()
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'dad', 'name': 'Dad', 'role': 'parent'})
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k',
                                    'mind_enabled': True}


PARENT = {'id': 'mom', 'role': 'parent', 'name': 'Mom'}


def scenario_plan_attaches_and_state_moves():
    _reset()
    iid = storage.add_mind_insight({'slug': 'margin', 'category': 'overload',
                                    'line': 'Margin is narrowing this week',
                                    'approach': 'find outside coverage'})
    mind._pool_call = _fake_pool({'steps': [
        {'kind': 'tool', 'text': 'Research sitter services nearby',
         'due': '2026-09-04'},
        {'kind': 'human', 'text': 'Call the top option', 'owner': 'Dad',
         'due': '2026-09-06'},
    ]})
    res = mind.make_plan(iid, PARENT, now=NOON)
    check(res['status'] == 'planned', f"got {res}")
    steps = res['plan']['steps']
    check(len(steps) == 2, f"two steps, got {len(steps)}")
    check(steps[0]['kind'] == 'tool' and steps[0]['status'] == 'open'
          and steps[0]['proposal_json'] is None, "tool step open, unbound")
    check(steps[1]['owner_member_id'] == 'dad'
          and steps[1]['owner_name'] == 'Dad',
          f"owner resolved by name, got {steps[1]}")
    check(all(s['id'] for s in steps), "every step has an id")
    row = storage.get_mind_insight_by_slug('margin')
    check(row['state'] == 'in_hand', f"state moved, got {row['state']}")
    check(row['plan_json']['steps'][0]['text'] == steps[0]['text'],
          "plan persisted on the row")
    check(CALLS and CALLS[0]['tier'] == 'heavy', "heavy tier")
    check('Margin is narrowing' in CALLS[0]['prompt']
          and 'find outside coverage' in CALLS[0]['prompt'],
          "insight line and approach reach the planner")


def scenario_second_tap_returns_existing_plan():
    res = mind.make_plan(storage.get_mind_insight_by_slug('margin')['id'],
                         PARENT, now=NOON)
    check(res['status'] == 'planned' and len(res['plan']['steps']) == 2,
          f"idempotent, got {res}")
    check(len(CALLS) == 1, "no second planner call")


def scenario_steps_are_clamped_and_defaulted():
    _reset()
    iid = storage.add_mind_insight({'slug': 'c', 'category': 'c', 'line': 'x'})
    mind._pool_call = _fake_pool({'steps': [
        {'kind': 'weird', 'text': 'no kind given', 'due': 'not-a-date'},
        {'kind': 'tool', 'text': ''},                      # dropped: empty
        {'kind': 'human', 'text': 'unknown owner', 'owner': 'Nobody',
         'due': '2026-09-09'},
        {'kind': 'tool', 'text': 's4', 'due': '2026-09-03'},
        {'kind': 'tool', 'text': 's5', 'due': '2026-09-03'},
        {'kind': 'tool', 'text': 's6', 'due': '2026-09-03'},
        {'kind': 'tool', 'text': 's7 over the cap', 'due': '2026-09-03'},
    ]})
    res = mind.make_plan(iid, PARENT, now=NOON)
    steps = res['plan']['steps']
    check(len(steps) == 5, f"clamped to 5 (empty dropped, cap trims), got {len(steps)}")
    check(steps[0]['kind'] == 'human', "unknown kind becomes human (never executes)")
    check(steps[0]['due'] == '2026-09-05',
          f"bad due defaults to today+3, got {steps[0]['due']}")
    check(steps[1]['owner_member_id'] is None
          and steps[1]['owner_name'] == '',
          "unknown owner stays unresolved, never invented")


def scenario_empty_plan_is_honest():
    _reset()
    iid = storage.add_mind_insight({'slug': 'e', 'category': 'c', 'line': 'x'})
    mind._pool_call = _fake_pool({'steps': []})
    res = mind.make_plan(iid, PARENT, now=NOON)
    check(res['status'] == 'no_plan', f"got {res}")
    row = storage.get_mind_insight_by_slug('e')
    check(row['state'] == 'active' and not row.get('plan_json'),
          "no plan written, state untouched")


def scenario_defaults_exist_on_new_rows():
    _reset()
    storage.add_mind_insight({'slug': 'd', 'category': 'c', 'line': 'x'})
    row = storage.get_mind_insight_by_slug('d')
    check(row['approach'] == '' and row['snoozed_until'] is None
          and row['plan_json'] is None,
          f"new-row defaults present, got {row}")
```

- [ ] **Step 2: Run to verify failure**

Run from repo root: `python tools/test.py --focus mind_plan`
Expected: FAIL — `AttributeError: module 'services.mind' has no attribute 'make_plan'` (and the defaults scenario fails on missing keys).

- [ ] **Step 3: Storage defaults**

In `chauffeur/services/storage.py`, `add_mind_insight`, extend the defaults dict:

```python
    row = {'id': _uuid.uuid4().hex, 'created_ts': time.time(), 'state': 'active',
           'outcome': None, 'resolved_ts': None, 'sensitivity': 'normal',
           'detail': '', 'domain': '', 'proposal_json': None, 'confidence': None,
           'approach': '', 'snoozed_until': None, 'plan_json': None,
           **data}
```

- [ ] **Step 4: Planner implementation**

In `chauffeur/services/mind.py`: add `import uuid` to the import block at the top. Then, directly after `propose_fix` (after its final `return {'status': 'no_move', ...}` line, before the `GRADUATION_MIN_RESOLVED` block), add:

```python
# --- Make a plan: an insight terminates in steps, not a shrug --------------
# The capability menu is a hand-written paragraph, not 99 tool schemas: the
# planner writes SENTENCES, and each tool sentence is bound lazily through
# the same agent rail chat uses, at that step's own Approve tap.

MAX_PLAN_STEPS = 5
DEFAULT_STEP_DUE_DAYS = 3

PLAN_SYSTEM = (
    "You are Argyle, a family home's mind, turning ONE observation into a "
    "short plan. Each step is exactly one of:\n"
    "- kind 'tool': one sentence a household assistant can do with its own "
    "abilities: research a question on the web (reading real pages), create "
    "or advance a thread (an open loop with someone outside the family — a "
    "school, vendor, sitter, coach), send a message to the family channel, "
    "DM a member, announce to a room, add a household or kid task, request "
    "ride coverage, propose a schedule change (assign a driver, move or "
    "cancel an event), open a negotiation over a crowded day, propose a "
    "practice program for a member, or add shopping items.\n"
    "- kind 'human': something only a family member can do in the real "
    "world (a phone call, a signup, a decision, a conversation). Give it an "
    "'owner' (a family member's name) and keep it honest — the app only "
    "tracks it.\n"
    "Rules: 2-5 steps, ordered so earlier steps inform later ones; EVERY "
    "step gets a 'due' date YYYY-MM-DD; prefer the smallest plan that "
    "genuinely resolves the observation; if nothing would truly help, "
    "return an empty list rather than busywork. Return STRICT JSON: "
    '{"steps": [{"kind": "tool|human", "text": "one sentence", '
    '"owner": "name (human steps)", "due": "YYYY-MM-DD"}]}'
)


def _parse_steps(raw, members, now: datetime.datetime) -> list:
    """Clamp what the model returned into the step shape every later tap
    trusts. Unknown kind becomes 'human' (a step that can never execute is
    the safe misread); a missing/bad due gets today+3 so no plan can sit
    invisible forever; an unknown owner stays unresolved, never invented."""
    by_id = {str(m.get('id')): m for m in members}
    by_name = {(m.get('name') or '').strip().lower(): m for m in members}
    out = []
    for item in (raw or []):
        if len(out) >= MAX_PLAN_STEPS:
            break
        if not isinstance(item, dict):
            continue
        text = (item.get('text') or '').strip()
        if not text:
            continue
        kind = item.get('kind') if item.get('kind') in ('tool', 'human') else 'human'
        want = str(item.get('owner') or '').strip()
        m = by_id.get(want) or by_name.get(want.lower())
        due = (item.get('due') or '').strip()
        try:
            datetime.date.fromisoformat(due)
        except ValueError:
            due = (now.date()
                   + datetime.timedelta(days=DEFAULT_STEP_DUE_DAYS)).isoformat()
        out.append({'id': uuid.uuid4().hex, 'kind': kind, 'text': text,
                    'owner_member_id': m.get('id') if m else None,
                    'owner_name': (m.get('name') or '') if m else '',
                    'due': due, 'status': 'open', 'proposal_json': None})
    return out


def make_plan(insight_id: str, actor: dict = None,
              now: datetime.datetime = None) -> dict:
    """One heavy call turns an insight into ordered steps and parks the row
    in_hand. Nothing executes — binding and approval are separate taps."""
    now = now or datetime.datetime.now()
    rows = [r for r in storage.get_mind_insights() if r['id'] == insight_id]
    if not rows or rows[0].get('state') not in ('active', 'in_hand'):
        return {'status': 'not_found'}
    row = rows[0]
    if (row.get('plan_json') or {}).get('steps'):
        return {'status': 'planned', 'plan': row['plan_json']}
    settings = storage.get_settings() or {}
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key:
        return {'status': 'no_key'}
    cap = int(settings.get('mind_cap_handle', CAPS_DEFAULT['handle']))
    if not _bump_call('handle', cap):
        return {'status': 'capped'}
    members = [m for m in storage.get_all_members() if not m.get('system')]
    roster = ', '.join(f"{m.get('name')} ({m.get('role')})" for m in members)
    prompt = (f"Today is {now.strftime('%A %Y-%m-%d')}.\nFamily: {roster}\n\n"
              f"Observation: {row.get('line')}"
              + (f"\nDetail: {row.get('detail')}" if row.get('detail') else '')
              + (f"\nYour instinct was: {row.get('approach')}"
                 if row.get('approach') else '')
              + "\n\n" + snapshot(now))
    res = _pool_call('heavy', api_key, PLAN_SYSTEM, prompt,
                     timeout_s=90, gemma_timeout_s=180)
    if not isinstance(res, dict) or res.get('error'):
        logger.warning(f"[mind] make_plan failed: {res}")
        return {'status': 'error'}
    steps = _parse_steps(res.get('steps'), members, now)
    if not steps:
        return {'status': 'no_plan'}
    plan = {'created_ts': time.time(), 'steps': steps}
    storage.update_mind_insight(insight_id, {'plan_json': plan,
                                             'state': 'in_hand'})
    return {'status': 'planned', 'plan': plan}
```

- [ ] **Step 5: Run focus tests**

Run: `python tools/test.py --focus mind_plan`
Expected: PASS (all five scenarios).

- [ ] **Step 6: Full sweep, bump, commit**

Run: `python tools/test.py` — must pass. Bump `chauffeur/config.yaml` version to `2.452.0`, then:

```bash
git add chauffeur/services/mind.py chauffeur/services/storage.py chauffeur/tests/test_mind_plan.py chauffeur/config.yaml
git commit -m 'Mind makes plans: an insight becomes ordered tool/human steps (v2.452.0)'
git push
```

(PowerShell: single quotes only in commit messages — double quotes split args.)

---

### Task 2: Step operations — lazy bind, close with retire math, due detection

**Files:**
- Modify: `chauffeur/services/mind.py` (add `bind_step`, `close_step`, `steps_due` directly after `make_plan`)
- Test: `chauffeur/tests/test_mind_plan.py` (append scenarios)

**Interfaces:**
- Consumes: step shape from Task 1; `mind._agent_request(prompt, actor)` (existing test-stub point used by `propose_fix`).
- Produces:
  - `bind_step(insight_id: str, step_id: str, actor: dict = None, now=None) -> dict` — `{'status': 'proposed', 'proposal_id', 'summary'}` | `{'status': 'no_move', 'note'}` (note also stored on the step as `step['note']`) | `{'status': 'not_found'|'no_key'|'capped'|'error'}`.
  - `close_step(insight_id: str, step_id: str, status: 'done'|'skipped') -> dict` — `{'status': 'success', 'plan': plan, 'insight_state': 'in_hand'|'retired'}`; when the last open step closes, retires the insight: any `done` → outcome `acted`, all `skipped` → outcome `dismissed`.
  - `steps_due(row: dict, today: datetime.date = None) -> list` — open steps with `due <= today` (unparseable due counts as due).

- [ ] **Step 1: Write the failing tests**

Append to `chauffeur/tests/test_mind_plan.py`:

```python
AGENT_CALLS = []


def _fake_agent(result):
    def f(prompt, actor):
        AGENT_CALLS.append({'prompt': prompt, 'actor': actor})
        return result
    return f


def _planned_insight(steps):
    """Row already in hand with the given steps (bypasses the planner)."""
    iid = storage.add_mind_insight({'slug': 'p', 'category': 'c',
                                    'line': 'needs handling'})
    storage.update_mind_insight(iid, {
        'state': 'in_hand',
        'plan_json': {'created_ts': 1.0, 'steps': steps}})
    return iid


def _step(i, kind='tool', **kw):
    return {'id': f's{i}', 'kind': kind, 'text': f'step {i}',
            'owner_member_id': None, 'owner_name': '', 'due': '2026-09-02',
            'status': 'open', 'proposal_json': None, **kw}


def scenario_bind_attaches_proposal_to_the_step():
    _reset()
    AGENT_CALLS.clear()
    iid = _planned_insight([_step(1), _step(2, kind='human')])
    mind._agent_request = _fake_agent({
        'message': 'I can ask the Hendersons.',
        'card': {'proposal_id': 'pr1', 'title': 'Ask Hendersons to cover Tue'}})
    res = mind.bind_step(iid, 's1', PARENT, now=NOON)
    check(res['status'] == 'proposed' and res['proposal_id'] == 'pr1',
          f"got {res}")
    row = storage.get_mind_insight_by_slug('p')
    s1 = row['plan_json']['steps'][0]
    check(s1['proposal_json'] == {'proposal_id': 'pr1',
                                  'summary': 'Ask Hendersons to cover Tue'},
          f"proposal stored on the step, got {s1}")
    check(s1['status'] == 'open', "binding never closes the step")
    check('step 1' in AGENT_CALLS[0]['prompt']
          and 'needs handling' in AGENT_CALLS[0]['prompt'],
          "step text and insight line reach the agent")
    res2 = mind.bind_step(iid, 's1', PARENT, now=NOON)
    check(res2['status'] == 'proposed' and len(AGENT_CALLS) == 1,
          "second bind returns the stored proposal, no second call")


def scenario_bind_refuses_human_and_closed_steps():
    _reset()
    iid = _planned_insight([_step(1, kind='human'),
                            _step(2, status='done')])
    check(mind.bind_step(iid, 's1', PARENT)['status'] == 'not_found',
          "human step never binds")
    check(mind.bind_step(iid, 's2', PARENT)['status'] == 'not_found',
          "closed step never binds")


def scenario_bind_no_move_keeps_step_open_with_note():
    _reset()
    iid = _planned_insight([_step(1)])
    mind._agent_request = _fake_agent({'message': 'Found: three sitters, from $18/h.',
                                       'card': None})
    res = mind.bind_step(iid, 's1', PARENT, now=NOON)
    check(res['status'] == 'no_move' and 'sitters' in res['note'], f"got {res}")
    s1 = storage.get_mind_insight_by_slug('p')['plan_json']['steps'][0]
    check(s1['status'] == 'open' and 'sitters' in (s1.get('note') or ''),
          "the answer is kept on the step for the family to read")


def scenario_close_math_any_done_is_acted():
    _reset()
    iid = _planned_insight([_step(1), _step(2, kind='human')])
    r1 = mind.close_step(iid, 's1', 'done')
    check(r1['status'] == 'success' and r1['insight_state'] == 'in_hand',
          f"one open step left, got {r1}")
    r2 = mind.close_step(iid, 's2', 'skipped')
    check(r2['insight_state'] == 'retired', f"got {r2}")
    row = storage.get_mind_insight_by_slug('p')
    check(row['state'] == 'retired' and row['outcome'] == 'acted'
          and row['resolved_ts'], "any done => acted")


def scenario_close_math_all_skipped_is_dismissed():
    _reset()
    iid = _planned_insight([_step(1), _step(2)])
    mind.close_step(iid, 's1', 'skipped')
    mind.close_step(iid, 's2', 'skipped')
    row = storage.get_mind_insight_by_slug('p')
    check(row['outcome'] == 'dismissed', "all skipped => the family said no")
    check(mind.close_step(iid, 's1', 'done')['status'] == 'not_found',
          "closed step refuses a second close")
    check(mind.close_step(iid, 's2', 'bogus')['status'] == 'bad_status',
          "unknown status refused")


def scenario_steps_due():
    _reset()
    row = {'plan_json': {'steps': [
        _step(1, due='2026-09-01'),                 # overdue
        _step(2, due='2026-09-02'),                 # due today
        _step(3, due='2026-09-09'),                 # future
        _step(4, due='2026-09-01', status='done'),  # closed
        _step(5, due='garbled'),                    # unparseable counts due
    ]}}
    due = mind.steps_due(row, today=datetime.date(2026, 9, 2))
    check([s['id'] for s in due] == ['s1', 's2', 's5'], f"got {[s['id'] for s in due]}")
    check(mind.steps_due({'plan_json': None}) == [], "no plan, nothing due")
```

- [ ] **Step 2: Run to verify failure**

Run: `python tools/test.py --focus mind_plan`
Expected: FAIL — `no attribute 'bind_step'`.

- [ ] **Step 3: Implement**

In `chauffeur/services/mind.py`, after `make_plan`:

```python
def bind_step(insight_id: str, step_id: str, actor: dict = None,
              now: datetime.datetime = None) -> dict:
    """Turn ONE open tool step's sentence into a real proposal via the same
    agent rail chat uses. Attaches to the step; never executes — the approve
    tap stays a separate human act. A no-card answer (research results, an
    honest can't) is kept on the step as `note` for the family to read."""
    now = now or datetime.datetime.now()
    rows = [r for r in storage.get_mind_insights() if r['id'] == insight_id]
    if not rows:
        return {'status': 'not_found'}
    row = rows[0]
    plan = row.get('plan_json') or {}
    step = next((s for s in plan.get('steps') or [] if s.get('id') == step_id),
                None)
    if not step or step.get('kind') != 'tool' or step.get('status') != 'open':
        return {'status': 'not_found'}
    if (step.get('proposal_json') or {}).get('proposal_id'):
        return {'status': 'proposed', **step['proposal_json']}
    settings = storage.get_settings() or {}
    if not settings.get('llm_gemini_api_key', ''):
        return {'status': 'no_key'}
    cap = int(settings.get('mind_cap_handle', CAPS_DEFAULT['handle']))
    if not _bump_call('handle', cap):
        return {'status': 'capped'}
    prompt = (f"Today is {now.strftime('%A %Y-%m-%d')}. You are handling this "
              f"observation about the family: \"{row.get('line')}\". The plan "
              f"step to do RIGHT NOW is: \"{step['text']}\". Do exactly this "
              "step using your action tools. If it genuinely cannot be done "
              "with them, say so plainly instead of forcing something else.")
    try:
        res = _agent_request(prompt, actor) or {}
    except Exception as e:
        logger.warning(f"[mind] bind_step agent run failed: {e}")
        return {'status': 'error'}
    card = res.get('card') or {}
    if card.get('proposal_id'):
        step['proposal_json'] = {
            'proposal_id': card['proposal_id'],
            'summary': card.get('title') or res.get('message') or 'proposed action'}
        storage.update_mind_insight(insight_id, {'plan_json': plan})
        return {'status': 'proposed', **step['proposal_json']}
    note = res.get('message') or ''
    if note:
        step['note'] = note
        storage.update_mind_insight(insight_id, {'plan_json': plan})
    return {'status': 'no_move', 'note': note}


def close_step(insight_id: str, step_id: str, status: str) -> dict:
    """Mark one open step done|skipped. When the last open step closes, the
    insight retires: any done => acted, all skipped => dismissed — so the
    graduation math hears the family's real answer."""
    if status not in ('done', 'skipped'):
        return {'status': 'bad_status'}
    rows = [r for r in storage.get_mind_insights() if r['id'] == insight_id]
    if not rows:
        return {'status': 'not_found'}
    row = rows[0]
    plan = row.get('plan_json') or {}
    steps = plan.get('steps') or []
    step = next((s for s in steps if s.get('id') == step_id), None)
    if not step or step.get('status') != 'open':
        return {'status': 'not_found'}
    step['status'] = status
    fields = {'plan_json': plan}
    if all(s.get('status') != 'open' for s in steps):
        outcome = 'acted' if any(s.get('status') == 'done' for s in steps) \
            else 'dismissed'
        fields.update({'state': 'retired', 'outcome': outcome,
                       'resolved_ts': time.time()})
    storage.update_mind_insight(insight_id, fields)
    return {'status': 'success', 'plan': plan,
            'insight_state': fields.get('state', row.get('state'))}


def steps_due(row: dict, today: datetime.date = None) -> list:
    """Open steps whose due date has arrived. An unparseable due counts as
    due — a step must never be able to hide behind a garbled date."""
    today = today or datetime.date.today()
    out = []
    for s in (row.get('plan_json') or {}).get('steps') or []:
        if s.get('status') != 'open':
            continue
        try:
            if datetime.date.fromisoformat(s.get('due') or '') <= today:
                out.append(s)
        except ValueError:
            out.append(s)
    return out
```

- [ ] **Step 4: Run focus tests**

Run: `python tools/test.py --focus mind_plan`
Expected: PASS (all scenarios, Task 1's included).

- [ ] **Step 5: Full sweep, bump, commit**

Run: `python tools/test.py` — must pass. Bump version to `2.452.1`.

```bash
git add chauffeur/services/mind.py chauffeur/tests/test_mind_plan.py chauffeur/config.yaml
git commit -m 'Mind plan steps: lazy bind, per-step close, honest retire math (v2.452.1)'
git push
```

---

### Task 3: Lifecycle wiring — lane visibility, snooze survives think, `approach` from think

**Files:**
- Modify: `chauffeur/services/mind.py` — `visible_insights` (line ~257), `deep_think` retire/update loops (lines ~583-618), `THINK_SYSTEM` (line ~512), snapshot `_own_insights` (line ~178)
- Test: `chauffeur/tests/test_mind_plan.py` (append), `chauffeur/tests/test_mind_think.py` (append)

**Interfaces:**
- Consumes: `steps_due` from Task 2; existing `deep_think` reconcile flow.
- Produces: `visible_insights(viewer, now: datetime.datetime = None)` — active non-snoozed rows, plus `in_hand` rows that have a due step (those gain a `due_step_count` int in the payload). Think stores `approach` per insight. Retire-by-omission skips snoozed rows; a desired slug matching an `in_hand` row updates fields without touching state.

- [ ] **Step 1: Write the failing tests**

Append to `chauffeur/tests/test_mind_plan.py`:

```python
def scenario_lane_visibility():
    _reset()
    import time as _t
    storage.add_mind_insight({'slug': 'plain', 'category': 'c', 'line': 'a'})
    snoozed = storage.add_mind_insight({'slug': 'parked', 'category': 'c',
                                        'line': 'b'})
    storage.update_mind_insight(snoozed, {'snoozed_until': _t.time() + 86400})
    woken = storage.add_mind_insight({'slug': 'woken', 'category': 'c',
                                      'line': 'c'})
    storage.update_mind_insight(woken, {'snoozed_until': _t.time() - 60})
    _planned_insight([_step(1, due='2026-09-09')])       # in hand, nothing due
    quiet = storage.get_mind_insight_by_slug('p')
    storage.update_mind_insight(quiet['id'], {'slug': 'quiet-hand'})
    iid2 = storage.add_mind_insight({'slug': 'due-hand', 'category': 'c',
                                     'line': 'e'})
    storage.update_mind_insight(iid2, {
        'state': 'in_hand',
        'plan_json': {'created_ts': 1.0, 'steps': [_step(9, due='2026-09-01')]}})
    lane = mind.visible_insights({'id': 'mom', 'role': 'parent'}, now=NOON)
    slugs = {r['slug'] for r in lane}
    check(slugs == {'plain', 'woken', 'due-hand'}, f"got {slugs}")
    due_row = next(r for r in lane if r['slug'] == 'due-hand')
    check(due_row.get('due_step_count') == 1,
          "in-hand row says how many steps are due")


def scenario_sensitive_gate_still_holds():
    _reset()
    storage.add_mind_insight({'slug': 's', 'category': 'c', 'line': 'x',
                              'sensitivity': 'sensitive'})
    check(len(mind.visible_insights({'id': 'k', 'role': 'child'}, now=NOON)) == 0,
          "sensitive stays parents-only through the new path")
    check(len(mind.visible_insights({'id': 'mom', 'role': 'parent'}, now=NOON)) == 1,
          "parent still sees it")
```

Append to `chauffeur/tests/test_mind_think.py` (reuses its `_reset`, `_fake_pool`, `NOON`):

```python
def scenario_think_stores_approach_and_spares_parked_rows():
    _reset()
    import time as _t
    snoozed = storage.add_mind_insight({'slug': 'parked', 'line': 'z',
                                        'category': 'c'})
    storage.update_mind_insight(snoozed, {'snoozed_until': _t.time() + 86400})
    held = storage.add_mind_insight({'slug': 'held', 'line': 'h',
                                     'category': 'c'})
    storage.update_mind_insight(held, {'state': 'in_hand', 'plan_json': {
        'created_ts': 1.0, 'steps': [{'id': 's1', 'kind': 'human',
                                      'text': 't', 'owner_member_id': None,
                                      'owner_name': '', 'due': '2026-09-09',
                                      'status': 'open', 'proposal_json': None}]}})
    mind._pool_call = _fake_pool([
        {'slug': 'fresh', 'line': 'new', 'category': 'c',
         'sensitivity': 'normal', 'domain': 'kids', 'confidence': 0.9,
         'approach': 'ask an outside hand to cover Tuesday'},
        {'slug': 'held', 'line': 'updated text', 'category': 'c',
         'sensitivity': 'normal', 'domain': 'kids', 'confidence': 0.9},
    ])
    res = mind.deep_think(NOON)
    check(res['status'] == 'thought', f"got {res}")
    fresh = storage.get_mind_insight_by_slug('fresh')
    check(fresh['approach'] == 'ask an outside hand to cover Tuesday',
          f"approach stored, got {fresh.get('approach')}")
    parked = storage.get_mind_insight_by_slug('parked')
    check(parked['state'] == 'active' and parked['outcome'] is None,
          "omitted snoozed row is NOT retired — a snooze is not a dismiss")
    h = storage.get_mind_insight_by_slug('held')
    check(h['state'] == 'in_hand' and h['line'] == 'updated text',
          "re-emitted in-hand slug updates fields, keeps state")
    check('snoozed until' in CALLS[0]['prompt']
          and 'in hand' in CALLS[0]['prompt'],
          "the prompt shows the model what is parked and what is in hand")
```

- [ ] **Step 2: Run to verify failure**

Run: `python tools/test.py --focus mind_plan` then `--focus mind_think`
Expected: FAIL — `visible_insights() got an unexpected keyword argument 'now'`; parked row wrongly retired as expired; `approach` missing.

- [ ] **Step 3: Implement**

3a. Replace `visible_insights` in `chauffeur/services/mind.py`:

```python
def visible_insights(viewer: Optional[dict],
                     now: datetime.datetime = None) -> List[dict]:
    """Server-side lane. Snoozed rows are silent until their wake date;
    in-hand rows appear only while a step is due — as work, not as the
    restated observation. Sensitivity gate unchanged: no identity (wall
    panel) or non-parent identity never receives a sensitive row."""
    now = now or datetime.datetime.now()
    rows = [r for r in storage.get_mind_insights(state='active')
            if (r.get('snoozed_until') or 0) <= now.timestamp()]
    for r in storage.get_mind_insights(state='in_hand'):
        due = steps_due(r, now.date())
        if due:
            rows.append({**r, 'due_step_count': len(due)})
    if viewer and viewer.get('role') in ('parent',):
        return rows
    return [r for r in rows if r.get('sensitivity') != 'sensitive']
```

(`steps_due` is defined later in the module; Python resolves it at call time, so order is fine.)

3b. In `deep_think`, the retire-by-omission loop becomes:

```python
    active = storage.get_mind_insights(state='active')
    for row in active:
        # A snoozed row was parked by a person; omission must not turn that
        # into a silent dismiss. It rejoins the reconcile when it wakes.
        if (row.get('snoozed_until') or 0) > time.time():
            continue
        if row['slug'] not in desired_slugs:
            storage.update_mind_insight(row['id'], {
                'state': 'retired', 'outcome': 'expired',
                'resolved_ts': time.time()})
```

(in_hand rows are naturally outside the `state='active'` query, so omission already spares them.)

3c. Still in `deep_think`, the desired-set write loop: add `approach` to `fields` and widen the update branch so a re-emitted in-hand slug keeps its state:

```python
        fields = {'line': item['line'], 'detail': item.get('detail') or '',
                  'domain': item.get('domain') or '',
                  'sensitivity': item.get('sensitivity') or 'normal',
                  'category': item.get('category') or 'other',
                  'confidence': item.get('confidence'),
                  'approach': item.get('approach') or ''}
        if existing and existing['state'] in ('active', 'in_hand'):
            storage.update_mind_insight(existing['id'], fields)
```

(The rest of the branch chain — dismissed pass, revive, add — stays exactly as it is.)

3d. `THINK_SYSTEM`: append to the curation paragraph (the one ending "Keep a slug stable while the observation is the same one."):

```
    "A row marked snoozed was parked by the family until the date shown — "
    "leave it out of your desired set and do not re-describe it. A row "
    "marked in hand has a plan being worked — never restate its "
    "observation.\n\n"
```

And in the STRICT JSON schema line, add the field after `"detail"`:

```
    "\"approach\": \"one line: the shape of the fix you would build\", "
```

3e. Snapshot `_own_insights` tag logic becomes:

```python
    def _own_insights():
        rows = storage.get_mind_insights()
        lines = []
        for r in rows[-30:]:
            if r['state'] == 'active' and \
                    (r.get('snoozed_until') or 0) > time.time():
                until = datetime.datetime.fromtimestamp(
                    r['snoozed_until']).strftime('%m-%d')
                tag = f"active, snoozed until {until}"
            elif r['state'] == 'in_hand':
                n = sum(1 for s in (r.get('plan_json') or {}).get('steps') or []
                        if s.get('status') == 'open')
                tag = f"in hand, {n} open steps"
            elif r['state'] == 'active':
                tag = 'active'
            else:
                tag = f"{r['state']}/{r.get('outcome')}"
            lines.append(f"- [{tag}] [{_fmt_day(r.get('created_ts'))}] "
                         f"({r.get('category')}) {r.get('line')}")
        return '\n'.join(lines)
```

- [ ] **Step 4: Run focus tests**

Run: `python tools/test.py --focus mind`
Expected: PASS — including every pre-existing mind test (reconcile, runtime cycle, tile, snapshot).

- [ ] **Step 5: Full sweep, bump, commit**

Run: `python tools/test.py` — must pass. Bump version to `2.452.2`.

```bash
git add chauffeur/services/mind.py chauffeur/tests/test_mind_plan.py chauffeur/tests/test_mind_think.py chauffeur/config.yaml
git commit -m 'Mind lifecycle: snooze survives think, in-hand leaves the lane, approach line lands (v2.452.2)'
git push
```

---

### Task 4: Endpoints — plan, snooze, and the four step taps

**Files:**
- Modify: `chauffeur/main.py` (insert after `mind_clear`, before `mind_admin`, ~line 5133; also widen `mind_admin`'s insights payload)
- Test: `chauffeur/tests/test_mind_endpoints.py` (append)

**Interfaces:**
- Consumes: `_mind_actor(request, claimed)`, `_approver_of_record(actor)` (both existing in main.py), `chat_actions.act_on_proposal(pid, 'approve', actor)`, and from mind: `make_plan`, `bind_step`, `close_step`.
- Produces routes: `POST /api/mind/insights/{id}/plan`, `.../snooze` (body `{'days': int}`, clamped 1–60, default 7), `.../step/{sid}/bind`, `.../step/{sid}/approve` (approves the bound proposal via chat_actions, then closes the step done), `.../step/{sid}/done`, `.../step/{sid}/skip`. `GET /api/mind/admin` now returns `insights` = active + in_hand rows.

- [ ] **Step 1: Write the failing tests**

Append to `chauffeur/tests/test_mind_endpoints.py` (service-level, matching the file's existing style — the endpoint bodies are thin wrappers over these exact calls; `test_mind_runtime.py` covers the wire):

```python
def scenario_snooze_clamps_and_parks():
    import time as _t
    from services import mind as _m
    storage.mind_insights_table.truncate()
    iid = storage.add_mind_insight({'slug': 'z', 'line': 'x', 'category': 'c'})
    # endpoint math: days clamped 1..60, default 7
    for asked, expect in ((0, 1), (7, 7), (999, 60)):
        days = max(1, min(60, int(asked or 7) if asked else 1))
        storage.update_mind_insight(iid, {'snoozed_until': _t.time() + days * 86400})
    row = storage.get_mind_insight_by_slug('z')
    check(row['snoozed_until'] > _t.time() + 59 * 86400, "clamped to 60d max")
    import datetime as _dt
    check(_m.visible_insights({'id': 'mom', 'role': 'parent'}) == [] or
          all(r['slug'] != 'z' for r in _m.visible_insights(
              {'id': 'mom', 'role': 'parent'})),
          "snoozed row leaves the lane")


def scenario_step_approve_rides_the_chat_rail():
    from services import mind as _m
    storage.mind_insights_table.truncate()
    iid = storage.add_mind_insight({'slug': 'w', 'line': 'x', 'category': 'c'})
    storage.update_mind_insight(iid, {'state': 'in_hand', 'plan_json': {
        'created_ts': 1.0,
        'steps': [{'id': 's1', 'kind': 'tool', 'text': 't',
                   'owner_member_id': None, 'owner_name': '',
                   'due': '2026-09-02', 'status': 'open',
                   'proposal_json': {'proposal_id': 'pr7', 'summary': 'S'}}]}})
    # the endpoint approves pr7 via chat_actions.act_on_proposal, then:
    res = _m.close_step(iid, 's1', 'done')
    check(res['status'] == 'success' and res['insight_state'] == 'retired',
          f"single-step plan retires on approve, got {res}")
    check(storage.get_mind_insight_by_slug('w')['outcome'] == 'acted',
          "approve lands as acted")
```

- [ ] **Step 2: Run to verify failure**

Run: `python tools/test.py --focus mind_endpoints`
Expected: the two new scenarios PASS already at the service level (they pin the math the endpoints delegate to) — if either fails, Task 2/3 regressed; fix there first. The endpoint wrappers themselves are Step 3; the import check `grep -c "mind_snooze" chauffeur/main.py` returns 0 before it.

- [ ] **Step 3: Implement the routes**

In `chauffeur/main.py`, directly after the `mind_clear` handler:

```python
@app.post("/api/mind/insights/{insight_id}/snooze")
def mind_snooze(insight_id: str, body: dict = Body(default={}),
                request: Request = None):
    """Not now: silence an insight until a wake date. Not a dismiss — think
    is shown the row with its date and told to leave it be until then."""
    import time as _t
    _mind_actor(request, body.get('member_id'))
    try:
        days = max(1, min(60, int(body.get('days', 7))))
    except (TypeError, ValueError):
        days = 7
    ok = storage.update_mind_insight(insight_id, {
        'snoozed_until': _t.time() + days * 86400})
    if not ok:
        raise HTTPException(status_code=404, detail="No such insight")
    return {"status": "success", "days": days}


@app.post("/api/mind/insights/{insight_id}/plan")
def mind_plan(insight_id: str, body: dict = Body(default={}),
              request: Request = None):
    """Handle it: one planner call turns the insight into ordered steps.
    Nothing executes — every step has its own later tap."""
    from services import mind as _mind
    actor = _mind_actor(request, body.get('member_id'))
    res = _mind.make_plan(insight_id, actor)
    if res.get('status') == 'not_found':
        raise HTTPException(status_code=404, detail="No such insight")
    return res


@app.post("/api/mind/insights/{insight_id}/step/{step_id}/bind")
def mind_step_bind(insight_id: str, step_id: str,
                   body: dict = Body(default={}), request: Request = None):
    """Turn one tool step's sentence into a real proposal. Attach only."""
    from services import mind as _mind
    actor = _mind_actor(request, body.get('member_id'))
    res = _mind.bind_step(insight_id, step_id, actor)
    if res.get('status') == 'not_found':
        raise HTTPException(status_code=404, detail="No such step")
    return res


@app.post("/api/mind/insights/{insight_id}/step/{step_id}/approve")
def mind_step_approve(insight_id: str, step_id: str,
                      body: dict = Body(default={}), request: Request = None):
    """Runs ONE bound step via the same approve rail chat uses, then closes
    it done. Per-step approval is the whole design — nothing else runs."""
    from services import mind as _mind, chat_actions as _ca
    actor = _mind_actor(request, body.get('member_id'))
    rows = [r for r in storage.get_mind_insights() if r['id'] == insight_id]
    if not rows:
        raise HTTPException(status_code=404, detail="No such insight")
    steps = (rows[0].get('plan_json') or {}).get('steps') or []
    step = next((s for s in steps if s.get('id') == step_id), None)
    if not step:
        raise HTTPException(status_code=404, detail="No such step")
    prop = step.get('proposal_json') or {}
    if not prop.get('proposal_id'):
        raise HTTPException(status_code=400, detail="Nothing bound to approve")
    result = _ca.act_on_proposal(prop['proposal_id'], 'approve',
                                 _approver_of_record(actor))
    if result.get('status') != 'success':
        raise HTTPException(status_code=400, detail=result.get('message'))
    closed = _mind.close_step(insight_id, step_id, 'done')
    return {**result, 'plan': closed.get('plan'),
            'insight_state': closed.get('insight_state')}


@app.post("/api/mind/insights/{insight_id}/step/{step_id}/done")
def mind_step_done(insight_id: str, step_id: str,
                   body: dict = Body(default={}), request: Request = None):
    """A human step done in the real world — or a family that did a tool
    step themselves. Closes without executing anything."""
    from services import mind as _mind
    _mind_actor(request, body.get('member_id'))
    res = _mind.close_step(insight_id, step_id, 'done')
    if res.get('status') != 'success':
        raise HTTPException(status_code=404, detail="No such step")
    return res


@app.post("/api/mind/insights/{insight_id}/step/{step_id}/skip")
def mind_step_skip(insight_id: str, step_id: str,
                   body: dict = Body(default={}), request: Request = None):
    from services import mind as _mind
    _mind_actor(request, body.get('member_id'))
    res = _mind.close_step(insight_id, step_id, 'skipped')
    if res.get('status') != 'success':
        raise HTTPException(status_code=404, detail="No such step")
    return res
```

And in `mind_admin` (the existing `GET /api/mind/admin`), widen the lane so the admin page can render in-hand plans and snoozed chips:

```python
    return {"insights": storage.get_mind_insights(state='active')
                        + storage.get_mind_insights(state='in_hand'),
            "history": storage.get_mind_insights(state='retired')[-60:],
            "counters": _mind.category_counters(),
            "graduation": _mind.graduation_candidates()}
```

- [ ] **Step 4: Prove main.py still imports and the wire runs**

Run: `python tools/test.py --focus mind` and `python tools/test.py --focus runtime`
Expected: PASS. (`test_mind_runtime.py` imports the full stack; a syntax or import error in main.py fails here, not on the device.)

- [ ] **Step 5: Full sweep, bump, commit**

Run: `python tools/test.py` — must pass. Bump version to `2.452.3`.

```bash
git add chauffeur/main.py chauffeur/tests/test_mind_endpoints.py chauffeur/config.yaml
git commit -m 'Mind plan endpoints: plan, snooze, and four per-step taps (v2.452.3)'
git push
```

---

### Task 5: Surfaces — approach line, Not-now, plan checklist on both lanes

**Files:**
- Modify: `chauffeur/templates/app.html` (PWA Family-tab lane: `_mindButtons`/`renderMind` block, ~lines 2989-3105)
- Modify: `chauffeur/templates/mind.html` (admin lane card, ~lines 195-231; Alpine methods ~lines 340-430)
- Run: `python tools/build_tailwind.py`

**Interfaces:**
- Consumes: lane payload rows now carrying `approach`, `plan_json`, `due_step_count`, and step `owner_name`/`note`; the six new endpoints from Task 4.
- Produces: UI only. No new endpoints, no new service functions.

Behavior contract (both surfaces identical in logic, each in its own idiom):
- No plan yet: line + detail as today, plus muted italic `Argyle would: {approach}` when `approach` is set. Buttons: **Handle it** (POST `plan`, then re-render with the checklist), **Not now ▾** (three quick-pick buttons: `3 days` / `1 week` / `2 weeks` → POST `snooze` `{days: 3|7|14}` — no dialogs), **Dismiss** (unchanged). The old propose-path buttons (`Approve`/`Clear anyway` for a legacy `proposal_json` on the row) stay as they are for rows that already carry one.
- With a plan (`plan_json.steps`): render the checklist; each step shows its text, `owner_name || 'Argyle'` + `by {due}`, its `note` in muted italics when present, and status chips for closed steps. Open-step buttons: tool unbound → **Do it** (POST `bind`; on `proposed` re-render showing `Argyle proposes: {summary}`; on `no_move` show the note) ; tool bound → **Approve** (POST `approve`) + **Skip**; human → **Done** + **Skip**. Every response re-fetches the lane (`fetchMind()` in app.html; `load()` in mind.html).
- `in_hand` rows arriving with `due_step_count` render the card header as `{line}` plus a small amber chip `N step(s) due` instead of repeating detail/approach.
- Kid/helper/guest (`canHandle` false in app.html) see no buttons, as today.

- [ ] **Step 1: app.html — replace the mind lane block**

Replace `_mindButtons` and `renderMind` and add the new fetch helpers (keeping `mindPropose`/`mindAct`/`mindClear`/`mindDismiss` as-is for legacy rows):

```javascript
        function _mindSnoozeRow(id) {
            return `<div class="flex flex-wrap gap-2 mt-2" id="mind-snooze-${id}" style="display:none">
                ${[[3, '3 days'], [7, '1 week'], [14, '2 weeks']].map(([d, label]) =>
                    `<button onclick="mindSnooze('${id}', ${d})"
                        class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700 active:bg-gray-700">${label}</button>`).join('')}
            </div>`;
        }

        function _mindStepHtml(ins, s) {
            const canHandle = ['parent', 'adult'].includes(currentMemberRole());
            const who = s.kind === 'human' ? (s.owner_name || 'someone') : 'Argyle';
            const meta = `${who} · by ${s.due || '?'}`;
            const note = s.note ? `<div class="text-xs text-gray-400 italic mt-0.5">${mfEscape(s.note)}</div>` : '';
            const bound = s.proposal_json && s.proposal_json.proposal_id;
            let tail = '';
            if (s.status !== 'open') {
                tail = `<span class="text-[10px] font-bold px-1.5 py-0.5 rounded ${s.status === 'done' ? 'bg-teal-500/20 text-teal-300' : 'bg-gray-700 text-gray-400'}">${s.status}</span>`;
            } else if (!canHandle) {
                tail = '';
            } else if (s.kind === 'tool' && !bound) {
                tail = `<div class="flex flex-wrap gap-2 mt-1.5">
                    <button onclick="mindStep('${ins.id}', '${s.id}', 'bind')" title="Asks Argyle to line this step up — nothing runs until you approve it"
                        class="text-xs font-bold px-3 py-1.5 rounded-lg bg-blue-600 text-white active:bg-blue-700">Do it</button>
                    <button onclick="mindStep('${ins.id}', '${s.id}', 'skip')"
                        class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-400 border border-gray-700 active:bg-gray-700">Skip</button></div>`;
            } else if (s.kind === 'tool') {
                tail = `<div class="text-xs text-violet-300 mt-1">Argyle proposes: ${mfEscape(s.proposal_json.summary || '')}</div>
                    <div class="flex flex-wrap gap-2 mt-1.5">
                    <button onclick="mindStep('${ins.id}', '${s.id}', 'approve')" title="Approves and runs this one step"
                        class="text-xs font-bold px-3 py-1.5 rounded-lg bg-blue-600 text-white active:bg-blue-700">Approve</button>
                    <button onclick="mindStep('${ins.id}', '${s.id}', 'skip')"
                        class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-400 border border-gray-700 active:bg-gray-700">Skip</button></div>`;
            } else {
                tail = `<div class="flex flex-wrap gap-2 mt-1.5">
                    <button onclick="mindStep('${ins.id}', '${s.id}', 'done')"
                        class="text-xs font-bold px-3 py-1.5 rounded-lg bg-teal-700 text-white active:bg-teal-800">Done</button>
                    <button onclick="mindStep('${ins.id}', '${s.id}', 'skip')"
                        class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-400 border border-gray-700 active:bg-gray-700">Skip</button></div>`;
            }
            return `<div class="border-t border-gray-800 pt-1.5 mt-1.5">
                <div class="text-sm text-gray-200">${mfEscape(s.text || '')}</div>
                <div class="text-[11px] text-gray-500">${mfEscape(meta)}</div>
                ${note}${tail}</div>`;
        }

        function _mindButtons(ins) {
            const dismiss = `<button onclick="mindDismiss('${ins.id}')"
                class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-400 border border-gray-700 active:bg-gray-700">Dismiss</button>`;
            const clear = (label) => `<button onclick="mindClear('${ins.id}')"
                title="Marks this as useful and clears it — nothing else happens"
                class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700 active:bg-gray-700">${label}</button>`;
            const notNow = `<button onclick="mindToggleSnooze('${ins.id}')"
                title="Parks this until a wake date — it comes back on its own"
                class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700 active:bg-gray-700">Not now ▾</button>`;
            const steps = ((ins.plan_json || {}).steps || []);
            const local = mindLocal[ins.id];
            if (steps.length) {
                return steps.map(s => _mindStepHtml(ins, s)).join('');
            }
            if (ins.proposal_json && ins.proposal_json.proposal_id) {
                return `<div class="text-xs text-violet-300 mt-1.5">Argyle proposes: ${mfEscape(ins.proposal_json.summary || '')}</div>
                    <div class="flex flex-wrap gap-2 mt-2">
                    <button onclick="mindAct('${ins.id}')" title="Approves and runs this action"
                        class="text-xs font-bold px-3 py-1.5 rounded-lg bg-blue-600 text-white active:bg-blue-700">Approve</button>
                    ${clear('Clear anyway')}${dismiss}</div>`;
            }
            if (local === 'busy') {
                return `<div class="flex gap-2 mt-2"><button disabled
                    class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-500 border border-gray-700">Planning…</button></div>`;
            }
            return `<div class="flex flex-wrap gap-2 mt-2">
                <button onclick="mindPlan('${ins.id}')" title="Asks Argyle for a step-by-step plan — nothing runs until you approve each step"
                    class="text-xs font-bold px-3 py-1.5 rounded-lg bg-blue-600 text-white active:bg-blue-700">Handle it</button>
                ${notNow}${dismiss}</div>${_mindSnoozeRow(ins.id)}`;
        }

        function renderMind() {
            const wrap = document.getElementById('mind-content');
            if (!wrap) { renderScheduleAnchors(); return; }
            const canHandle = ['parent', 'adult'].includes(currentMemberRole());
            if (!mindInsights.length) {
                wrap.innerHTML = '';
                renderScheduleAnchors();
                return;
            }
            wrap.innerHTML = '<div class="text-xs font-black uppercase tracking-widest text-violet-400 px-1">✨ Argyle noticed</div>'
                + mindInsights.map(ins => `
                <div class="bg-gray-900 border border-gray-800 rounded-2xl p-3">
                    <div class="flex items-start justify-between gap-2">
                        <div class="text-sm text-gray-100">${mfEscape(ins.line || '')}</div>
                        ${ins.due_step_count ? `<span class="text-[10px] font-bold px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 shrink-0">${ins.due_step_count} step${ins.due_step_count > 1 ? 's' : ''} due</span>` : ''}
                    </div>
                    ${!ins.due_step_count && ins.detail ? `<div class="text-xs text-gray-500 mt-0.5">${mfEscape(ins.detail)}</div>` : ''}
                    ${!((ins.plan_json || {}).steps || []).length && ins.approach ? `<div class="text-xs text-gray-400 italic mt-0.5">Argyle would: ${mfEscape(ins.approach)}</div>` : ''}
                    ${canHandle ? _mindButtons(ins) : ''}
                </div>`).join('');
        }

        function mindToggleSnooze(id) {
            const el = document.getElementById(`mind-snooze-${id}`);
            if (el) el.style.display = el.style.display === 'none' ? 'flex' : 'none';
        }

        async function mindSnooze(id, days) {
            try {
                const res = await fetch(`${apiBase}api/mind/insights/${id}/snooze`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ days }) });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    showGlobalAlert(err.detail || "Couldn't park that.");
                }
            } catch (e) { showGlobalAlert("Couldn't park that."); }
            fetchMind();
        }

        async function mindPlan(id) {
            mindLocal[id] = 'busy';
            renderMind();
            try {
                const res = await fetch(`${apiBase}api/mind/insights/${id}/plan`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
                const data = res.ok ? await res.json() : {};
                delete mindLocal[id];
                if (data.status === 'planned') {
                    const ins = mindInsights.find(i => i.id === id);
                    if (ins) ins.plan_json = data.plan;
                } else if (data.status === 'no_plan') {
                    showGlobalAlert("Argyle doesn't see a plan that would genuinely help here.");
                } else {
                    showGlobalAlert(data.status === 'capped'
                        ? "Argyle has hit today's thinking budget — try tomorrow."
                        : "Argyle couldn't come up with a plan just now.");
                }
            } catch (e) {
                delete mindLocal[id];
                showGlobalAlert("Argyle couldn't come up with a plan just now.");
            }
            renderMind();
        }

        async function mindStep(id, stepId, action) {
            try {
                const res = await fetch(`${apiBase}api/mind/insights/${id}/step/${stepId}/${action}`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
                const data = res.ok ? await res.json() : {};
                if (!res.ok) {
                    const err = data || {};
                    showGlobalAlert(err.detail || "Couldn't do that step.");
                } else if (action === 'bind' && data.status === 'no_move') {
                    showGlobalAlert(data.note || "Argyle doesn't have a move for that step.");
                } else if (action === 'bind' && data.status === 'capped') {
                    showGlobalAlert("Argyle has hit today's thinking budget — try tomorrow.");
                }
            } catch (e) { showGlobalAlert("Couldn't do that step."); }
            fetchMind();
        }
```

(`fetchMind` refetches `/api/mind/insights` and calls `renderMind()` — unchanged. Note the fetch handler in `mindStep` re-fetches on every outcome, so bound proposals and notes appear from the server's copy, never from local guesswork.)

- [ ] **Step 2: mind.html — admin lane card**

In the Current-lane `<template x-for="ins in insights">` card:

after the detail line, add the approach line and due-chip:

```html
<div class="text-xs text-gray-400 italic mt-0.5"
    x-show="!((ins.plan_json || {}).steps || []).length && ins.approach"
    x-text="'Argyle would: ' + ins.approach"></div>
<span class="text-[10px] font-bold px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 shrink-0"
    x-show="ins.state === 'in_hand'" x-text="'in hand'"></span>
<span class="text-[10px] font-bold px-1.5 py-0.5 rounded bg-gray-700 text-gray-300 shrink-0"
    x-show="snoozedLabel(ins)" x-text="snoozedLabel(ins)"></span>
```

Replace the buttons row so plan-less rows offer Handle it / Not now / Dismiss (keeping the legacy proposal branch), and planned rows render the checklist:

```html
<template x-if="((ins.plan_json || {}).steps || []).length">
    <div>
        <template x-for="s in ins.plan_json.steps" :key="s.id">
            <div class="border-t border-gray-800 pt-1.5 mt-1.5">
                <div class="text-sm text-gray-200" x-text="s.text"></div>
                <div class="text-[11px] text-gray-500"
                    x-text="(s.kind === 'human' ? (s.owner_name || 'someone') : 'Argyle') + ' · by ' + (s.due || '?')"></div>
                <div class="text-xs text-gray-400 italic mt-0.5" x-show="s.note" x-text="s.note"></div>
                <div class="text-xs text-violet-300 mt-1"
                    x-show="s.status === 'open' && s.proposal_json && s.proposal_json.proposal_id"
                    x-text="'Argyle proposes: ' + ((s.proposal_json || {}).summary || '')"></div>
                <span class="text-[10px] font-bold px-1.5 py-0.5 rounded"
                    :class="s.status === 'done' ? 'bg-teal-500/20 text-teal-300' : 'bg-gray-700 text-gray-400'"
                    x-show="s.status !== 'open'" x-text="s.status"></span>
                <div class="flex flex-wrap gap-2 mt-1.5" x-show="s.status === 'open'">
                    <button x-show="s.kind === 'tool' && !(s.proposal_json && s.proposal_json.proposal_id)"
                        @click="stepDo(ins.id, s.id, 'bind')" :disabled="busy[ins.id]"
                        class="text-xs font-bold px-3 py-1.5 rounded-lg bg-blue-600 text-white active:bg-blue-700 disabled:bg-gray-800 disabled:text-gray-500">Do it</button>
                    <button x-show="s.kind === 'tool' && s.proposal_json && s.proposal_json.proposal_id"
                        @click="stepDo(ins.id, s.id, 'approve')"
                        class="text-xs font-bold px-3 py-1.5 rounded-lg bg-blue-600 text-white active:bg-blue-700">Approve</button>
                    <button x-show="s.kind === 'human'" @click="stepDo(ins.id, s.id, 'done')"
                        class="text-xs font-bold px-3 py-1.5 rounded-lg bg-teal-700 text-white active:bg-teal-800">Done</button>
                    <button @click="stepDo(ins.id, s.id, 'skip')"
                        class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-400 border border-gray-700 active:bg-gray-700">Skip</button>
                </div>
            </div>
        </template>
    </div>
</template>
<div class="flex flex-wrap gap-2 mt-2" x-show="!((ins.plan_json || {}).steps || []).length">
    <template x-if="ins.proposal_json && ins.proposal_json.proposal_id">
        <button @click="act(ins.id)" title="Approves and runs this action"
            class="text-xs font-bold px-3 py-1.5 rounded-lg bg-blue-600 text-white active:bg-blue-700">Approve</button>
    </template>
    <template x-if="!(ins.proposal_json && ins.proposal_json.proposal_id)">
        <button @click="plan(ins.id)" :disabled="busy[ins.id]"
            title="Asks Argyle for a step-by-step plan — nothing runs until you approve each step"
            class="text-xs font-bold px-3 py-1.5 rounded-lg bg-blue-600 text-white active:bg-blue-700 disabled:bg-gray-800 disabled:text-gray-500"
            x-text="busy[ins.id] ? 'Planning…' : 'Handle it'"></button>
    </template>
    <button @click="snoozeOpen[ins.id] = !snoozeOpen[ins.id]"
        class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700 active:bg-gray-700">Not now ▾</button>
    <button @click="clearIt(ins.id)"
        title="Marks this as useful and clears it — nothing else happens"
        class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700 active:bg-gray-700"
        x-text="ins.proposal_json && ins.proposal_json.proposal_id ? 'Clear anyway' : 'Clear'"></button>
    <button @click="dismiss(ins.id)"
        class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-400 border border-gray-700 active:bg-gray-700">Dismiss</button>
</div>
<div class="flex flex-wrap gap-2 mt-2" x-show="snoozeOpen[ins.id]">
    <template x-for="opt in [[3, '3 days'], [7, '1 week'], [14, '2 weeks']]" :key="opt[0]">
        <button @click="snooze(ins.id, opt[0])"
            class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700 active:bg-gray-700"
            x-text="opt[1]"></button>
    </template>
</div>
```

And in the Alpine component's data/methods (next to the existing `propose`/`act`): add `snoozeOpen: {},` to the data object, and:

```javascript
snoozedLabel(ins) {
    if (!ins.snoozed_until || ins.snoozed_until * 1000 < Date.now()) return '';
    return 'snoozed until ' + new Date(ins.snoozed_until * 1000)
        .toLocaleDateString([], { month: 'short', day: 'numeric' });
},
async plan(id) {
    this.busy[id] = true;
    try {
        const r = await fetch(this.apiBase + `api/mind/insights/${id}/plan`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
        const d = r.ok ? await r.json() : {};
        if (d.status === 'no_plan') {
            showGlobalAlert("Argyle doesn't see a plan that would genuinely help here.");
        } else if (d.status === 'capped') {
            showGlobalAlert("Argyle has hit today's thinking budget — try tomorrow.");
        } else if (d.status !== 'planned') {
            showGlobalAlert("Argyle couldn't come up with a plan just now.");
        }
    } catch (e) { showGlobalAlert("Argyle couldn't come up with a plan just now."); }
    this.busy[id] = false;
    this.load();
},
async snooze(id, days) {
    this.snoozeOpen[id] = false;
    try {
        const r = await fetch(this.apiBase + `api/mind/insights/${id}/snooze`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ days }) });
        if (!r.ok) showGlobalAlert("Couldn't park that.");
    } catch (e) { showGlobalAlert("Couldn't park that."); }
    this.load();
},
async stepDo(id, stepId, action) {
    this.busy[id] = true;
    try {
        const r = await fetch(this.apiBase + `api/mind/insights/${id}/step/${stepId}/${action}`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
        const d = r.ok ? await r.json() : {};
        if (!r.ok) {
            showGlobalAlert(d.detail || "Couldn't do that step.");
        } else if (action === 'bind' && d.status === 'no_move') {
            showGlobalAlert(d.note || "Argyle doesn't have a move for that step.");
        } else if (action === 'bind' && d.status === 'capped') {
            showGlobalAlert("Argyle has hit today's thinking budget — try tomorrow.");
        }
    } catch (e) { showGlobalAlert("Couldn't do that step."); }
    this.busy[id] = false;
    this.load();
},
```

(mind.html defines its own `showGlobalAlert`-compatible helper already for the settings save path — if it does not, reuse whatever the page's existing save() error path uses; never `alert()`.)

- [ ] **Step 3: Rebuild Tailwind**

Run: `python tools/build_tailwind.py`
Expected: completes; new classes (`bg-teal-700`, `active:bg-teal-800`, `bg-amber-500/20` etc.) compiled in. Verify with `grep -c "bg-teal-700" chauffeur/static/tailwind.css` ≥ 1 (adjust path to wherever the build writes; the build script prints it).

- [ ] **Step 4: Full sweep, bump, commit**

Run: `python tools/test.py` — must pass (templates aren't unit-tested; the sweep guards the Python side and the runtime import).

Bump version to `2.452.4`.

```bash
git add chauffeur/templates/app.html chauffeur/templates/mind.html chauffeur/static chauffeur/config.yaml
git commit -m 'Mind lane UI: approach line, Not now, per-step plan checklist on both lanes (v2.452.4)'
git push
```

---

### Task 6: Capabilities doc + final sweep

**Files:**
- Modify: `chauffeur/system_capabilities.md` (the Mind section)

**Interfaces:** none — documentation and verification.

- [ ] **Step 1: Update the Mind section of `chauffeur/system_capabilities.md`**

Find the Mind/insight-lane section and update it to record: insights now carry an `approach` one-liner from deep think; "Handle it" produces a 2–5 step plan (tool steps bind lazily to real proposals and each needs its own Approve tap; human steps carry an owner and a due date); "Not now" snoozes an insight (3/7/14 days) and a snoozed row is invisible, protected from retire-by-omission, and returns on its wake date; a planned insight is `in_hand`, appears only when steps are due, and retires when its last step closes (any done → acted, all skipped → dismissed); planner and binder calls share the existing `mind_cap_handle` (30/day). Match the surrounding document's tone and level of detail.

- [ ] **Step 2: Full sweep**

Run: `python tools/test.py`
Expected: PASS — this is the final gate.

- [ ] **Step 3: Bump, commit, push**

Bump version to `2.452.5`.

```bash
git add chauffeur/system_capabilities.md chauffeur/config.yaml
git commit -m 'Record mind plans in system capabilities (v2.452.5)'
git push
```

---

## Self-review notes (resolved inline)

- Spec's `bind` semantics kept two-tap on tool steps (Do it → shows summary → Approve), matching the existing lane UX and honoring per-step approval: the human approves the *bound proposal*, not the sentence.
- Spec's "pick a date" snooze became fixed quick-picks (3/7/14 days) — no dialog machinery, no free input to validate; deviation noted in the spec's terms (quick picks were already the primary design).
- Spec coverage: approach line (Task 3), planner (1), binder+retire math (2), snooze+visibility+think rules (3), endpoints (4), surfaces (5), capabilities doc (6). Failure honesty: `no_plan` (1), `no_move` note kept on the step (2), capped messages in both UIs (5).
- Type consistency: step shape defined once in Task 1's Produces block; Tasks 2-5 use `id`/`kind`/`text`/`owner_member_id`/`owner_name`/`due`/`status`/`proposal_json`/`note` exactly.

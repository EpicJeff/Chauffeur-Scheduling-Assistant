# Mission Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One generic agent loop (pro-model brain, paid key fenced) that composes the existing v1 tool registry over many persisted steps; writes become proposals, three thin doorways feed it.

**Architecture:** `services/missions.py` is a tick-driven engine (rides the existing 30s push loop next to `mind.tick`). Each step is one JSON LLM call on a new `'mission'` tier (pro pool, paid key, no free fallback). Read tools dispatch through `agent_tools.execute_tool`; write intents mint rows via `chat_actions.create_action_proposal` and execute only on human approve via `chat_actions.act_on_proposal`. `/missions` is the admin surface; thread button + chat tool (both stacks) are the other doorways.

**Tech Stack:** FastAPI (main.py routes), sqlite-backed TinyDB-style `storage` tables, Jinja templates + Alpine, model_pools Gemini pools, scenario-style tests under `chauffeur/tests/` (harness.py, `check()`).

**Spec:** `docs/superpowers/specs/2026-09-04-mission-engine-design.md` — read it first; it carries the locked laws (no autonomous writes, no browser actuation, paid-key fence, /missions-only surface).

## Global Constraints

- Paid key setting name is exactly `llm_gemini_paid_api_key`; it may be READ only in `services/model_pools.py`, DEFINED in `services/settings_registry.py`, and referenced in tests + templates' settings UI. Task 9's source pin enforces the read-side.
- Pro pool default exactly `["gemini-3.1-pro", "gemini-2.5-pro"]`; tier `'mission'` chains `['pro']` with NO free-pool fallback.
- `missions_enabled` defaults **False** (OFF is off: no LLM calls, no ticks). The flip is the user's act.
- Cap defaults: launch 3/day, 40 LLM steps/mission, 120 pro calls/day (uncalibrated starting values, settings-editable).
- The engine never executes a write tool. `send_direct_message` is never offered in any form. `send_drafted` / mailer stay unreachable (Task 9 pins).
- Every task ends with: full sweep NOT required per-task (focus run only), but Task 10 runs the FULL sweep before the final commit. Each commit bumps `chauffeur/config.yaml` version (patch), message ends `(vX.Y.Z)`, then push. Versions below assume you start at v2.457.0 — read config.yaml and use the next patch number if reality differs.
- Run tests from `chauffeur/tests/` (e.g. `cd chauffeur/tests && python test_missions_engine.py`); the focused sweep is `python chauffeur/tools/test.py --focus` from repo root.
- No browser dialogs anywhere in the template (`showGlobalAlert`/`promptConfirm` from control_center idiom only if needed).

## File Structure

- `chauffeur/services/model_pools.py` — modify: pro pool, mission tiers, `api_key_for_pool`.
- `chauffeur/services/storage.py` — modify: `missions` + `mission_steps` tables + helpers.
- `chauffeur/services/missions.py` — create: the engine (constants, prompt build, step, launch, tick, prune).
- `chauffeur/services/chat_actions.py` — modify: `create_action_proposal(..., extra_allowed=...)`.
- `chauffeur/services/watchers.py` — modify: mission kinds + `_mission_states` sweep.
- `chauffeur/main.py` — modify: page route, API endpoints, push-loop tick line.
- `chauffeur/services/auth.py` — modify: two RULES lines.
- `chauffeur/services/settings_registry.py` — modify: missions group.
- `chauffeur/templates/missions.html` — create: admin page.
- `chauffeur/services/agent_tools.py` — modify: `launch_mission` v1 tool.
- `chauffeur/services/agent_tools_v2.py` — modify: v2 declaration + wrapper.
- `chauffeur/services/agent_router.py` — modify: dispatch branch.
- `chauffeur/templates/threads.html` — modify: Work-this button.
- Tests: `chauffeur/tests/test_missions_pools.py`, `test_missions_engine.py`, `test_missions_endpoints.py`, `test_missions_pins.py`.

---

### Task 1: Pro pool, mission tiers, key routing

**Files:**
- Modify: `chauffeur/services/model_pools.py` (docstring, `DEFAULT_POOLS`, `TIER_CHAINS`, new helper)
- Test: `chauffeur/tests/test_missions_pools.py`

**Interfaces:**
- Consumes: existing `models_for(tier, settings)`, `_pool`.
- Produces: `DEFAULT_POOLS['pro'] == ["gemini-3.1-pro", "gemini-2.5-pro"]`; `TIER_CHAINS['mission'] == ['pro']`; `TIER_CHAINS['mission_flash'] == ['flash']`; `api_key_for_pool(pool_name: str, settings: dict) -> str`.

- [ ] **Step 1: Write the failing test**

```python
"""Pro pool exists, mission tier never leaks into free pools, key routing."""
from harness import check
from services import model_pools


def scenario_pro_pool_and_mission_tier():
    s = {}
    check(model_pools.DEFAULT_POOLS['pro'] == ["gemini-3.1-pro", "gemini-2.5-pro"],
          "pro pool defaults to 3.1-pro then 2.5-pro")
    models = model_pools.models_for('mission', s)
    check(models == ["gemini-3.1-pro", "gemini-2.5-pro"],
          f"mission tier serves ONLY the pro pool, got {models}")
    free = set()
    for t in ('interactive', 'background', 'heavy', 'vision'):
        free.update(model_pools.models_for(t, s))
    check(not free.intersection(set(models)),
          "no free tier ever serves a pro model")


def scenario_mission_flash_is_pure_flash():
    models = model_pools.models_for('mission_flash', {})
    check(all('flash' in m and 'lite' not in m for m in models),
          f"mission_flash chain is flash models only, got {models}")


def scenario_key_routing():
    s = {'llm_gemini_api_key': 'FREE', 'llm_gemini_paid_api_key': 'PAID'}
    check(model_pools.api_key_for_pool('pro', s) == 'PAID', "pro pool gets the paid key")
    for p in ('lite', 'flash', 'gemma'):
        check(model_pools.api_key_for_pool(p, s) == 'FREE', f"{p} pool gets the free key")
    check(model_pools.api_key_for_pool('pro', {'llm_gemini_api_key': 'FREE'}) == '',
          "no paid key = empty string, never a silent fall back to the free key")


def scenario_pro_pool_overridable():
    s = {'model_pool_pro': 'my-pro-model'}
    check(model_pools.models_for('mission', s) == ['my-pro-model'],
          "model_pool_pro setting overrides the default like every other pool")


if __name__ == '__main__':
    scenario_pro_pool_and_mission_tier()
    scenario_mission_flash_is_pure_flash()
    scenario_key_routing()
    scenario_pro_pool_overridable()
    print("test_missions_pools OK")
```

- [ ] **Step 2: Run it, verify it fails**

Run: `cd chauffeur/tests && python test_missions_pools.py`
Expected: KeyError `'pro'` (pool missing).

- [ ] **Step 3: Implement**

In `DEFAULT_POOLS` add:

```python
    'pro': ["gemini-3.1-pro", "gemini-2.5-pro"],
```

In `TIER_CHAINS` add (with this comment):

```python
    # Missions (services/missions.py). 'mission' is the ONLY tier that touches
    # the pro pool and it never falls back to a free pool — a mission pauses
    # rather than silently degrading. 'mission_flash' exists for benchmarking
    # the same mission on the free flash chain (pure flash: no lite/gemma, so
    # the comparison measures the model, not the fallback).
    'mission': ['pro'],
    'mission_flash': ['flash'],
```

Add the helper (below `_pool`):

```python
def api_key_for_pool(pool_name: str, settings: dict) -> str:
    """The pro pool bills the paid key; every other pool stays on the free
    key. This helper is the ONLY reader of llm_gemini_paid_api_key — the
    source-pin test in test_missions_pins.py is the fence that keeps regular
    traffic from ever spending paid money. Missing paid key returns '' so a
    caller fails loudly instead of quietly billing the free key."""
    s = settings or {}
    if pool_name == 'pro':
        return s.get('llm_gemini_paid_api_key', '') or ''
    return s.get('llm_gemini_api_key', '') or ''
```

Update the module docstring's pool list with a `- pro:` line noting paid key + mission-only.

- [ ] **Step 4: Run test, verify pass** — same command, expect `test_missions_pools OK`.

- [ ] **Step 5: Commit**

```bash
git add chauffeur/services/model_pools.py chauffeur/tests/test_missions_pools.py chauffeur/config.yaml
git commit -m 'A pro pool the free tiers cannot see (v2.457.0)'
git push
```
(Bump config.yaml `version:` to 2.457.0 first.)

---

### Task 2: Mission tables and storage helpers

**Files:**
- Modify: `chauffeur/services/storage.py` (table registration next to `mind_insights_table` ~483; helpers next to `add_mind_insight` ~2712)
- Test: extend `chauffeur/tests/test_missions_engine.py` (create file now; engine scenarios join it in Task 3)

**Interfaces:**
- Produces: `missions_table`, `mission_steps_table`; `add_mission(data) -> id`, `update_mission(id, data) -> bool`, `get_mission(id) -> dict|None`, `get_missions(status: str|list|None) -> [dict]` (newest first), `add_mission_step(mission_id, data) -> id` (auto `idx`, bumps mission `step_count` ONLY for kind `llm` — see Task 3 note; storage just auto-idxs), `get_mission_steps(mission_id) -> [dict]` (idx order), `prune_missions(before_ts) -> int` (terminal rows only).

- [ ] **Step 1: Failing test**

```python
"""Engine behavior with a scripted fake LLM. Storage scenarios first."""
from harness import check
from services import storage


def _reset():
    storage.missions_table.truncate()
    storage.mission_steps_table.truncate()


def scenario_mission_rows_round_trip():
    _reset()
    mid = storage.add_mission({'goal': 'find a magician', 'origin_kind': 'manual',
                               'created_by': 'mom', 'tier': 'mission'})
    row = storage.get_mission(mid)
    check(row and row['status'] == 'running' and row['step_count'] == 0
          and row['acknowledged_at'] is None,
          "defaults: running, zero steps, unacknowledged")
    storage.add_mission_step(mid, {'kind': 'llm', 'name': 'plan',
                                   'result_json': {'action': 'finish'}})
    storage.add_mission_step(mid, {'kind': 'note', 'name': 'done'})
    steps = storage.get_mission_steps(mid)
    check([s['idx'] for s in steps] == [0, 1], "steps auto-index in order")
    check(storage.update_mission(mid, {'status': 'done'}), "update writes")
    check(storage.get_missions(status='done')[0]['id'] == mid, "status filter")
    check(storage.get_missions(status=['done', 'blocked'])[0]['id'] == mid,
          "list filter")


def scenario_prune_spares_active_and_steps_follow():
    _reset()
    old = storage.add_mission({'goal': 'g', 'origin_kind': 'manual'})
    storage.add_mission_step(old, {'kind': 'note', 'name': 'n'})
    storage.update_mission(old, {'status': 'done', 'finished_at': 1.0})
    live = storage.add_mission({'goal': 'g2', 'origin_kind': 'manual'})
    n = storage.prune_missions(before_ts=2.0)
    check(n == 1 and storage.get_mission(live) and not storage.get_mission(old),
          "prune eats old terminal rows only")
    check(storage.get_mission_steps(old) == [], "pruned mission takes its steps")


if __name__ == '__main__':
    scenario_mission_rows_round_trip()
    scenario_prune_spares_active_and_steps_follow()
    print("test_missions_engine OK")
```

- [ ] **Step 2: Run, expect fail** — `AttributeError: missions_table`.

- [ ] **Step 3: Implement**

Next to the mind table registrations (~storage.py:483):

```python
    missions_table = db.table('missions')
    mission_steps_table = db.table('mission_steps')
```
(Mirror however `mind_noticings_table` is scoped — same block, same idiom, including any module-global assignment pattern the file uses.)

Helpers next to `add_mind_insight`:

```python
def add_mission(data: dict) -> str:
    import uuid as _uuid
    row = {'id': _uuid.uuid4().hex, 'created_at': time.time(),
           'updated_at': time.time(), 'status': 'running', 'goal': '',
           'origin_kind': 'manual', 'origin_ref': None, 'created_by': None,
           'tier': 'mission', 'summary': '', 'error': '', 'step_count': 0,
           'consec_errors': 0, 'retry_at': None, 'acknowledged_at': None,
           'finished_at': None,
           **data}
    with db_lock:
        missions_table.insert(row)
    return row['id']

def update_mission(mission_id: str, data: dict) -> bool:
    data = {**data, 'updated_at': time.time()}
    with db_lock:
        return bool(missions_table.update(data, Query().id == mission_id))

def get_mission(mission_id: str):
    with db_lock:
        rows = missions_table.search(Query().id == mission_id)
    return dict(rows[0]) if rows else None

def get_missions(status=None) -> List[dict]:
    with db_lock:
        rows = [dict(r) for r in missions_table.all()]
    if status:
        wanted = {status} if isinstance(status, str) else set(status)
        rows = [r for r in rows if r.get('status') in wanted]
    return sorted(rows, key=lambda r: r.get('created_at') or 0, reverse=True)

def add_mission_step(mission_id: str, data: dict) -> str:
    import uuid as _uuid
    with db_lock:
        idx = len(mission_steps_table.search(Query().mission_id == mission_id))
        row = {'id': _uuid.uuid4().hex, 'mission_id': mission_id, 'idx': idx,
               'ts': time.time(), 'kind': 'note', 'name': '',
               'args_json': None, 'result_json': None, **data}
        mission_steps_table.insert(row)
    return row['id']

def get_mission_steps(mission_id: str) -> List[dict]:
    with db_lock:
        rows = [dict(r) for r in
                mission_steps_table.search(Query().mission_id == mission_id)]
    return sorted(rows, key=lambda r: r.get('idx') or 0)

def prune_missions(before_ts: float) -> int:
    """Terminal missions older than the cutoff; running/waiting rows are live
    state and are NEVER pruned. Steps go with their mission."""
    terminal = ('done', 'blocked', 'dropped')
    with db_lock:
        rows = [dict(r) for r in missions_table.all()]
        doomed = [r['id'] for r in rows if r.get('status') in terminal
                  and (r.get('finished_at') or r.get('created_at') or 0) < before_ts]
        for mid in doomed:
            missions_table.remove(Query().id == mid)
            mission_steps_table.remove(Query().mission_id == mid)
    return len(doomed)
```
(Match the file's actual remove/update idiom — copy whatever `prune_findings` uses.)

- [ ] **Step 4: Run test, expect `test_missions_engine OK`.**

- [ ] **Step 5: Commit** — bump to 2.457.1, message `Missions get a table and a memory (v2.457.1)`, push.

---

### Task 3: Engine core — one step of the loop

**Files:**
- Create: `chauffeur/services/missions.py`
- Modify: `chauffeur/services/chat_actions.py:371-376` (`extra_allowed` param)
- Test: extend `chauffeur/tests/test_missions_engine.py`

**Interfaces:**
- Consumes: Task 1 (`api_key_for_pool`, tiers), Task 2 helpers, `agent_tools.execute_tool(name, args)`, `agent_tools.TOOL_HANDLERS`, `chat_actions.create_action_proposal(action_type, summary, payload, created_by_member_id, extra_allowed)`, `web.research(question)`, `threads` (`storage.get_threads`, `threads.draft_message(thread_id, intent)`).
- Produces: `missions.step(mission: dict) -> dict` (returns the fresh mission row); module hook `missions._llm` (callable `(mission, system, user, settings) -> dict`, tests replace it); `missions.READ_TOOLS`, `missions.EXCLUDED_TOOLS`, `missions.proposable_tools() -> frozenset`; `missions.CAPS_DEFAULT = {'launch': 3, 'steps': 40, 'pro_calls': 120}`.

- [ ] **Step 1: Failing tests** (append to `test_missions_engine.py`; add `from services import missions` at top)

```python
def _mk(goal='hire a magician', tier='mission'):
    return storage.add_mission({'goal': goal, 'origin_kind': 'manual',
                                'created_by': 'mom', 'tier': tier})


def _script(*responses):
    """missions._llm replacement that plays canned responses in order."""
    seq = list(responses)
    def fake(mission, system, user, settings):
        return seq.pop(0)
    return fake


def scenario_read_tool_dispatches_and_transcribes():
    _reset()
    mid = _mk()
    calls = {}
    from services import agent_tools
    orig = agent_tools.execute_tool
    agent_tools.execute_tool = lambda n, a: calls.setdefault('call', (n, a)) or {'status': 'ok'}
    missions._llm = _script(
        {'action': 'tool', 'tool': 'get_current_state', 'args': {}},
        {'action': 'finish', 'summary': 'looked'})
    try:
        missions.step(storage.get_mission(mid))
        row = missions.step(storage.get_mission(mid))
    finally:
        agent_tools.execute_tool = orig
    check(calls['call'][0] == 'get_current_state', "read tool really dispatched")
    kinds = [s['kind'] for s in storage.get_mission_steps(mid)]
    check(kinds == ['tool', 'llm'] or kinds == ['tool', 'note', 'llm'] or
          kinds[0] == 'tool', f"transcript records the tool step, got {kinds}")
    check(row['status'] == 'done' and row['summary'] == 'looked', "finish closes")


def scenario_write_tool_becomes_proposal_never_executes():
    _reset()
    mid = _mk()
    executed = {}
    from services import agent_tools
    orig = agent_tools.execute_tool
    agent_tools.execute_tool = lambda n, a: executed.setdefault(n, a) or {'status': 'ok'}
    missions._llm = _script(
        {'action': 'propose', 'tool': 'add_errand', 'args': {'name': 'pick up cake'},
         'summary': 'Add cake pickup errand', 'why': 'party needs cake'})
    try:
        missions.step(storage.get_mission(mid))
    finally:
        agent_tools.execute_tool = orig
    check(not executed, "engine executed NOTHING")
    steps = storage.get_mission_steps(mid)
    prop = [s for s in steps if s['kind'] == 'proposal']
    check(len(prop) == 1 and prop[0]['result_json'].get('proposal_id'),
          "write intent minted a real proposal row")
    from services import storage as _st
    check(storage.get_mission(mid)['status'] == 'running', "mission keeps going")


def scenario_excluded_and_unknown_tools_bounce():
    _reset()
    mid = _mk()
    missions._llm = _script(
        {'action': 'propose', 'tool': 'send_direct_message', 'args': {}},
        {'action': 'tool', 'tool': 'add_errand', 'args': {}},
        {'action': 'give_up', 'reason': 'nope'})
    missions.step(storage.get_mission(mid))
    missions.step(storage.get_mission(mid))
    row = missions.step(storage.get_mission(mid))
    notes = [s for s in storage.get_mission_steps(mid) if s['kind'] == 'note']
    check(len(notes) >= 2, "DM propose and write-as-read both bounced to notes")
    check(row['status'] == 'blocked' and row['error'] == 'nope', "give_up blocks")


def scenario_ask_user_pauses():
    _reset()
    mid = _mk()
    missions._llm = _script({'action': 'ask_user', 'question': 'What is the budget?'})
    row = missions.step(storage.get_mission(mid))
    check(row['status'] == 'waiting_user', "ask pauses the mission")
    ask = [s for s in storage.get_mission_steps(mid) if s['kind'] == 'ask']
    check(ask and ask[0]['result_json']['question'] == 'What is the budget?',
          "the question is on the transcript")


def scenario_transient_error_waits_hard_errors_block():
    _reset()
    mid = _mk()
    missions._llm = _script({'error': '429 quota', 'transient': True})
    row = missions.step(storage.get_mission(mid))
    check(row['status'] == 'waiting_retry' and row['retry_at'], "transient = pause")
    storage.update_mission(mid, {'status': 'running', 'retry_at': None})
    missions._llm = _script({'error': 'boom', 'transient': False},
                            {'error': 'boom', 'transient': False},
                            {'error': 'boom', 'transient': False})
    missions.step(storage.get_mission(mid))
    missions.step(storage.get_mission(mid))
    row = missions.step(storage.get_mission(mid))
    check(row['status'] == 'blocked' and 'boom' in row['error'],
          "three straight hard errors give up honestly")


def scenario_step_cap_blocks():
    _reset()
    mid = _mk()
    storage.update_mission(mid, {'step_count': missions.CAPS_DEFAULT['steps']})
    missions._llm = _script({'action': 'finish', 'summary': 'x'})
    row = missions.step(storage.get_mission(mid))
    check(row['status'] == 'blocked' and 'cap' in row['error'],
          "step cap ends the mission before another LLM call")


def scenario_read_tools_exist_in_registry():
    from services import agent_tools
    missing = missions.READ_TOOLS - set(agent_tools.TOOL_HANDLERS)
    check(not missing, f"READ_TOOLS all real, missing: {missing}")
    check('send_direct_message' not in missions.proposable_tools()
          and 'send_direct_message' not in missions.READ_TOOLS,
          "DMs unreachable in any form")
```
Add the new scenario calls to `__main__` before the OK print.

- [ ] **Step 2: Run, expect fail** — `ImportError` (no services.missions).

- [ ] **Step 3: Implement `chauffeur/services/missions.py`**

```python
"""Mission engine — one generic agent loop, many thin doorways.

Spec: docs/superpowers/specs/2026-09-04-mission-engine-design.md.
Laws in force here:
- The engine executes READ tools only. Every write intent becomes an
  action proposal a parent approves on /missions; approval executes on the
  same chat_actions rail every other proposal uses.
- The pro pool (paid key) is reachable only through tier 'mission'; a
  mission never falls back to a free pool — it pauses instead.
- send_direct_message is never offered in any form. Mail drafting goes
  through threads.draft_message, which cannot send.
"""
import datetime
import json
import logging
import time

from services import storage, model_pools

logger = logging.getLogger(__name__)

CAPS_DEFAULT = {'launch': 3, 'steps': 40, 'pro_calls': 120}
STEPS_PER_TICK = 3
RETRY_DELAY_S = 300
MAX_CONSEC_ERRORS = 3
RETENTION_DAYS = 120

# Default-deny read classification: a registry tool NOT named here is offered
# only in propose-wrapped form. Adding a tool to the registry later leaves it
# write-classed until someone consciously promotes it.
READ_TOOLS = frozenset({
    'get_current_state', 'get_errands', 'get_pet_status', 'get_point_balances',
    'get_family_goals', 'get_family_messages', 'list_chores',
    'list_open_findings', 'list_insights', 'list_programs',
    'get_routine_status', 'get_kid_tasks', 'get_shopping_list_items',
    'get_tonights_plate', 'get_meal_rules', 'get_occasion',
    'get_occasion_insights', 'get_occasion_gaps', 'get_run_sheet',
    'get_prep_ahead', 'search_places', 'suggest_gift_ideas',
})

# Never offered, not even propose-wrapped. DMs are private space (mind law).
EXCLUDED_TOOLS = frozenset({'send_direct_message'})


def proposable_tools() -> frozenset:
    from services import agent_tools, chat_actions
    return (frozenset(agent_tools.TOOL_HANDLERS) - READ_TOOLS - EXCLUDED_TOOLS) \
        | frozenset(chat_actions.ADMIN_ACTIONS)


def _bump_call(kind: str, cap: int) -> bool:
    """Day-keyed counter, mind's idiom; True = allowed (and counted)."""
    day = datetime.date.today().isoformat()
    key = f'mission_calls:{day}'
    counts = dict(storage.get_app_state(key) or {})
    if int(counts.get(kind, 0)) >= cap:
        return False
    counts[kind] = int(counts.get(kind, 0)) + 1
    storage.set_app_state(key, counts)
    return True


def _llm_live(mission: dict, system: str, user: str, settings: dict) -> dict:
    tier = 'mission' if mission.get('tier') != 'flash' else 'mission_flash'
    pool = 'pro' if tier == 'mission' else 'flash'
    api_key = model_pools.api_key_for_pool(pool, settings)
    if not api_key:
        return {'error': 'no api key for pool ' + pool, 'transient': False}
    return model_pools.call_pool_json(tier, api_key, system, user,
                                      settings=settings, timeout_s=120)


# Test seam: scenarios replace this with a scripted fake.
_llm = _llm_live


def _catalog() -> str:
    from services import agent_tools
    lines = []
    for name in sorted(READ_TOOLS):
        schema = agent_tools.TOOL_SCHEMAS.get(name) or {}
        props = ', '.join((schema.get('properties') or {}).keys()) or 'no args'
        lines.append(f"- READ {name}({props})")
    for name in sorted(proposable_tools()):
        from services import agent_tools as _at
        schema = _at.TOOL_SCHEMAS.get(name) or {}
        props = ', '.join((schema.get('properties') or {}).keys()) or 'payload'
        lines.append(f"- PROPOSE {name}({props})")
    return '\n'.join(lines)


def _system_prompt(now: datetime.datetime) -> str:
    return (
        f"Today is {now.strftime('%A %Y-%m-%d')}. You are Argyle working a "
        "MISSION for the family: a multi-step goal you advance one action at "
        "a time. You cannot execute changes yourself — every change you want "
        "is a PROPOSAL a parent approves later, and drafted messages are "
        "never sent by you (a person reviews and sends). Never claim "
        "something was sent, booked, or paid.\n\n"
        "Respond with EXACTLY ONE JSON object, one of:\n"
        '{"action":"tool","tool":"<READ tool>","args":{...}}\n'
        '{"action":"propose","tool":"<PROPOSE tool>","args":{...},'
        '"summary":"<one line a parent reads>","why":"<reason>"}\n'
        '{"action":"research","question":"<web question>"}\n'
        '{"action":"draft","thread_title":"<thread>","intent":"<what the '
        'message should do>"}\n'
        '{"action":"ask_user","question":"<one question>"}\n'
        '{"action":"finish","summary":"<what was achieved + what awaits '
        'approval>"}\n'
        '{"action":"give_up","reason":"<honest blocker>"}\n\n'
        "Prefer finishing with a small set of strong proposals over endless "
        "research. Available tools:\n" + _catalog()
    )


def _compact(value, limit=900):
    try:
        s = json.dumps(value) if not isinstance(value, str) else value
    except Exception:
        s = str(value)
    return s[:limit] + ('…' if len(s) > limit else '')


def _user_prompt(mission: dict) -> str:
    steps = storage.get_mission_steps(mission['id'])
    lines = [f"GOAL: {mission.get('goal')}"]
    if mission.get('origin_kind') == 'thread':
        lines.append(f"(Opened from thread {mission.get('origin_ref')})")
    lines.append("TRANSCRIPT SO FAR (oldest first):")
    for s in steps[-25:]:
        lines.append(f"[{s['idx']}] {s['kind']} {s.get('name') or ''} "
                     f"args={_compact(s.get('args_json'), 200)} "
                     f"result={_compact(s.get('result_json'))}")
    if not steps:
        lines.append("(none yet — plan your first move)")
    lines.append("Reply with your ONE next action as JSON.")
    return '\n'.join(lines)


def _close(mission_id: str, status: str, **fields) -> dict:
    fields = {'status': status, **fields}
    if status in ('done', 'blocked', 'dropped'):
        fields.setdefault('finished_at', time.time())
    storage.update_mission(mission_id, fields)
    return storage.get_mission(mission_id)


def _match_thread(title: str):
    title = (title or '').strip().lower()
    if not title:
        return None
    rows = storage.get_threads()
    exact = [t for t in rows if (t.get('title') or '').strip().lower() == title]
    if len(exact) == 1:
        return exact[0]
    sub = [t for t in rows if title in (t.get('title') or '').lower()]
    return sub[0] if len(sub) == 1 else None


def step(mission: dict) -> dict:
    """Advance ONE step. Returns the fresh mission row. All state transitions
    live here so tick() stays a scheduler and tests drive this directly."""
    mid = mission['id']
    settings = storage.get_settings() or {}
    caps = {'steps': int(settings.get('mission_step_cap', CAPS_DEFAULT['steps'])),
            'pro_calls': int(settings.get('mission_cap_pro_calls',
                                          CAPS_DEFAULT['pro_calls']))}
    if int(mission.get('step_count') or 0) >= caps['steps']:
        return _close(mid, 'blocked',
                      error=f"step cap ({caps['steps']}) reached")
    if mission.get('tier') != 'flash' and not _bump_call('pro', caps['pro_calls']):
        storage.update_mission(mid, {'status': 'waiting_retry',
                                     'retry_at': time.time() + 1800})
        return storage.get_mission(mid)

    now = datetime.datetime.now()
    res = _llm(mission, _system_prompt(now), _user_prompt(mission), settings)
    storage.update_mission(mid, {'step_count': int(mission.get('step_count') or 0) + 1})

    if not isinstance(res, dict) or res.get('error'):
        err = (res or {}).get('error') if isinstance(res, dict) else 'bad response'
        if isinstance(res, dict) and res.get('transient'):
            storage.update_mission(mid, {'status': 'waiting_retry',
                                         'retry_at': time.time() + RETRY_DELAY_S})
            return storage.get_mission(mid)
        n = int(mission.get('consec_errors') or 0) + 1
        if n >= MAX_CONSEC_ERRORS:
            return _close(mid, 'blocked', error=str(err), consec_errors=n)
        storage.update_mission(mid, {'consec_errors': n})
        storage.add_mission_step(mid, {'kind': 'note', 'name': 'llm_error',
                                       'result_json': {'error': str(err)}})
        return storage.get_mission(mid)

    storage.update_mission(mid, {'consec_errors': 0})
    action = (res.get('action') or '').strip()

    if action == 'tool':
        name = res.get('tool') or ''
        if name not in READ_TOOLS:
            storage.add_mission_step(mid, {'kind': 'note', 'name': 'refused',
                'result_json': {'note': f"{name} is not a READ tool — use "
                                        f"propose for changes"}})
            return storage.get_mission(mid)
        from services import agent_tools
        out = agent_tools.execute_tool(name, res.get('args') or {})
        storage.add_mission_step(mid, {'kind': 'tool', 'name': name,
                                       'args_json': res.get('args') or {},
                                       'result_json': out})
        return storage.get_mission(mid)

    if action == 'propose':
        name = res.get('tool') or ''
        if name in EXCLUDED_TOOLS or name not in proposable_tools():
            storage.add_mission_step(mid, {'kind': 'note', 'name': 'refused',
                'result_json': {'note': f"{name} is not proposable"}})
            return storage.get_mission(mid)
        from services import chat_actions
        summary = (res.get('summary') or res.get('why') or name).strip()
        made = chat_actions.create_action_proposal(
            name, summary, res.get('args') or {},
            created_by_member_id=mission.get('created_by'),
            extra_allowed=proposable_tools())
        storage.add_mission_step(mid, {'kind': 'proposal', 'name': name,
                                       'args_json': res.get('args') or {},
                                       'result_json': {**made,
                                                       'why': res.get('why')}})
        return storage.get_mission(mid)

    if action == 'research':
        from services import web
        out = web.research((res.get('question') or '').strip())
        storage.add_mission_step(mid, {'kind': 'tool', 'name': 'research',
                                       'args_json': {'question': res.get('question')},
                                       'result_json': out})
        return storage.get_mission(mid)

    if action == 'draft':
        thread = None
        if mission.get('origin_kind') == 'thread':
            thread = storage.get_thread(mission.get('origin_ref'))
        thread = thread or _match_thread(res.get('thread_title'))
        if not thread:
            storage.add_mission_step(mid, {'kind': 'note', 'name': 'refused',
                'result_json': {'note': 'no unambiguous thread matched — a tie '
                                        'declines, ask the user or open one via '
                                        'propose'}})
            return storage.get_mission(mid)
        from services import threads as _threads
        out = _threads.draft_message(thread['id'],
                                     intent=(res.get('intent') or '').strip())
        storage.add_mission_step(mid, {'kind': 'draft', 'name': thread.get('title'),
                                       'args_json': {'intent': res.get('intent')},
                                       'result_json': out})
        return storage.get_mission(mid)

    if action == 'ask_user':
        storage.add_mission_step(mid, {'kind': 'ask', 'name': 'question',
            'result_json': {'question': (res.get('question') or '').strip()}})
        return _close(mid, 'waiting_user')

    if action == 'finish':
        storage.add_mission_step(mid, {'kind': 'llm', 'name': 'finish',
                                       'result_json': res})
        return _close(mid, 'done', summary=(res.get('summary') or '').strip())

    if action == 'give_up':
        storage.add_mission_step(mid, {'kind': 'llm', 'name': 'give_up',
                                       'result_json': res})
        return _close(mid, 'blocked', error=(res.get('reason') or '').strip())

    storage.add_mission_step(mid, {'kind': 'note', 'name': 'unparsed',
                                   'result_json': {'got': _compact(res, 300)}})
    return storage.get_mission(mid)
```

In `chat_actions.create_action_proposal`, change the signature and gate:

```python
def create_action_proposal(action_type: str, summary: str, payload: dict,
                           created_by_member_id: str = None,
                           extra_allowed: frozenset = frozenset()) -> Dict[str, Any]:
    """Store a proposed action; return {status, message, proposal_id, card}.
    extra_allowed widens the proposable set for the mission engine ONLY —
    chat's own funnel never passes it, so chat behavior is unchanged."""
    from services import storage
    if action_type not in ADMIN_ACTIONS and action_type not in extra_allowed:
        return {"status": "error", "message": f"'{action_type}' is not a proposable action."}
```
(Rest of the function body unchanged.)

- [ ] **Step 4: Run tests** — `cd chauffeur/tests && python test_missions_engine.py`, expect OK. Also `python test_mind_endpoints.py` (chat rail untouched) — expect OK.

- [ ] **Step 5: Commit** — bump 2.457.2, message `The engine takes one honest step at a time (v2.457.2)`, push.

---

### Task 4: Launch, tick, prune — the engine's clock

**Files:**
- Modify: `chauffeur/services/missions.py`
- Test: extend `chauffeur/tests/test_missions_engine.py`

**Interfaces:**
- Produces: `missions.launch(goal, origin_kind='manual', origin_ref=None, created_by=None, tier='mission') -> {'status': 'launched'|'disabled'|'no_key'|'capped'|'empty', 'mission_id'?}`; `missions.tick(now=None) -> dict` (the push-loop entry, all gating inside).

- [ ] **Step 1: Failing tests**

```python
def _enable(extra=None):
    s = {'missions_enabled': True, 'llm_gemini_api_key': 'FREE',
         'llm_gemini_paid_api_key': 'PAID'}
    s.update(extra or {})
    storage.get_settings = lambda: s      # harness already stubs get_settings
    return s


def scenario_launch_gates():
    _reset()
    storage.get_settings = lambda: {}
    check(missions.launch('x')['status'] == 'disabled', "OFF means off")
    _enable({'llm_gemini_paid_api_key': ''})
    check(missions.launch('x')['status'] == 'no_key',
          "mission tier without a paid key refuses at launch")
    _enable()
    check(missions.launch('  ')['status'] == 'empty', "blank goal refused")
    got = missions.launch('plan the party', created_by='mom')
    check(got['status'] == 'launched' and storage.get_mission(got['mission_id']),
          "launch creates a running mission")
    storage.set_app_state(f"mission_calls:{__import__('datetime').date.today().isoformat()}",
                          {'launch': missions.CAPS_DEFAULT['launch']})
    check(missions.launch('another')['status'] == 'capped', "daily launch cap")


def scenario_tick_advances_one_mission_serially():
    _reset()
    _enable()
    storage.set_app_state(f"mission_calls:{__import__('datetime').date.today().isoformat()}", {})
    a = missions.launch('first', created_by='mom')['mission_id']
    b = missions.launch('second', created_by='mom')['mission_id']
    seen = []
    def fake(mission, system, user, settings):
        seen.append(mission['id'])
        return {'action': 'ask_user', 'question': 'q?'}
    missions._llm = fake
    missions.tick()
    check(seen and all(x == seen[0] for x in seen),
          f"one tick works ONE mission only, got {seen}")
    check(len(seen) == 1, "ask_user leaves running-state, tick stops advancing")
    other = b if seen[0] == a else a
    check(storage.get_mission(other)['status'] == 'running',
          "the queued mission waits its turn untouched")


def scenario_tick_promotes_due_retries_and_respects_disabled():
    _reset()
    storage.get_settings = lambda: {}
    check(missions.tick()['status'] == 'disabled', "tick is inert when OFF")
    _enable()
    mid = _mk()
    storage.update_mission(mid, {'status': 'waiting_retry', 'retry_at': 1.0})
    missions._llm = _script({'action': 'finish', 'summary': 'ok'})
    missions.tick()
    check(storage.get_mission(mid)['status'] == 'done',
          "a due retry re-enters the loop and can finish")
```
Add to `__main__`. Note: `_reset()` must also clear the day counter — extend it:

```python
def _reset():
    storage.missions_table.truncate()
    storage.mission_steps_table.truncate()
    import datetime as _dt
    storage.set_app_state(f"mission_calls:{_dt.date.today().isoformat()}", {})
```

- [ ] **Step 2: Run, expect fail** — `AttributeError: launch`.

- [ ] **Step 3: Implement** (append to missions.py)

```python
def launch(goal: str, origin_kind: str = 'manual', origin_ref=None,
           created_by=None, tier: str = 'mission') -> dict:
    settings = storage.get_settings() or {}
    if not settings.get('missions_enabled', False):
        return {'status': 'disabled'}
    goal = (goal or '').strip()
    if not goal:
        return {'status': 'empty'}
    if tier != 'flash' and not model_pools.api_key_for_pool('pro', settings):
        return {'status': 'no_key',
                'message': 'Missions need the paid Gemini key (Config → Missions).'}
    cap = int(settings.get('mission_cap_launch', CAPS_DEFAULT['launch']))
    if not _bump_call('launch', cap):
        return {'status': 'capped',
                'message': f"That's {cap} missions today — the cap resets tomorrow."}
    mid = storage.add_mission({'goal': goal, 'origin_kind': origin_kind,
                               'origin_ref': origin_ref, 'created_by': created_by,
                               'tier': tier})
    logger.info(f"[missions] launched {mid} ({origin_kind}): {goal[:80]}")
    return {'status': 'launched', 'mission_id': mid}


def tick(now: datetime.datetime = None) -> dict:
    """The one entry the push loop calls (mirrors mind.tick). All gating —
    enabled flag, retry promotion, one-mission-at-a-time, steps-per-tick —
    lives here so main.py stays a two-line block and tests drive this."""
    now = now or datetime.datetime.now()
    settings = storage.get_settings() or {}
    if not settings.get('missions_enabled', False):
        return {'status': 'disabled'}
    ts = now.timestamp()

    for row in storage.get_missions(status='waiting_retry'):
        if (row.get('retry_at') or 0) <= ts:
            storage.update_mission(row['id'], {'status': 'running',
                                               'retry_at': None})

    running = sorted(storage.get_missions(status='running'),
                     key=lambda r: r.get('created_at') or 0)
    out = {'status': 'ticked', 'advanced': 0}
    if running:
        mission = running[0]
        for _ in range(STEPS_PER_TICK):
            mission = step(mission)
            out['advanced'] += 1
            if mission.get('status') != 'running':
                break
    else:
        cutoff = ts - RETENTION_DAYS * 86400
        pruned = storage.prune_missions(cutoff)
        if pruned:
            out['pruned'] = pruned
    return out
```

- [ ] **Step 4: Run test file, expect OK.**

- [ ] **Step 5: Commit** — bump 2.457.3, message `The engine gets a clock: launch caps, retries, one mission at a time (v2.457.3)`, push.

---

### Task 5: Watcher findings for terminal missions

**Files:**
- Modify: `chauffeur/services/watchers.py` (SCANNED_KINDS ~392; new sweep next to `_thread_stalls` ~399; hook next to `findings += _thread_stalls(now)` ~578)
- Test: extend `chauffeur/tests/test_missions_engine.py`

**Interfaces:**
- Consumes: `storage.get_missions`, the module-local `Finding` dataclass (same one `_thread_stalls` builds).
- Produces: kinds `mission_done`, `mission_blocked`, `mission_waiting` in `SCANNED_KINDS`; `_mission_states(now) -> [Finding]`; findings stop once `acknowledged_at` is set (done/blocked) or status leaves `waiting_user`.

- [ ] **Step 1: Failing test**

```python
def scenario_mission_findings_emit_and_hush():
    _reset()
    from services import watchers
    import datetime as _dt
    now = _dt.datetime.now()
    done = _mk(); storage.update_mission(done, {'status': 'done',
                                                'summary': '2 proposals ready'})
    waiting = _mk('q'); storage.update_mission(waiting, {'status': 'waiting_user'})
    acked = _mk('a'); storage.update_mission(acked, {'status': 'done',
                                                     'acknowledged_at': 1.0})
    rows = watchers._mission_states(now)
    kinds = sorted(f.kind for f in rows)
    check(kinds == ['mission_done', 'mission_waiting'],
          f"done + waiting page, acknowledged stays quiet, got {kinds}")
    for k in ('mission_done', 'mission_blocked', 'mission_waiting'):
        check(k in watchers.SCANNED_KINDS, f"{k} is a scanned kind")
    line = next(f.line for f in rows if f.kind == 'mission_done')
    check('proposal' in line, "the done line carries the next action")
```

- [ ] **Step 2: Run, expect fail** — `AttributeError: _mission_states`.

- [ ] **Step 3: Implement**

Extend `SCANNED_KINDS` tuple with `'mission_done', 'mission_blocked', 'mission_waiting'`. Add below `_thread_stalls` (copy its `Finding(...)` field idiom exactly):

```python
def _mission_states(now: datetime.datetime):
    """A mission that stopped needing the engine and started needing a person.
    Signal policy: the next action is IN the line. done/blocked hush once a
    parent taps OK on /missions (acknowledged_at); waiting hushes when the
    answer arrives (status leaves waiting_user). Steps never page — only
    states a human must resolve."""
    from services import storage as _st
    out = []
    for m in _st.get_missions(status=['done', 'blocked', 'waiting_user']):
        status = m.get('status')
        if status in ('done', 'blocked') and m.get('acknowledged_at'):
            continue
        goal = (m.get('goal') or 'Mission')[:60]
        if status == 'done':
            kind, sev, dm = 'mission_done', 'fyi', False
            what = m.get('summary') or 'review its proposals on /missions'
            line = f"🎯 Mission done — {goal}: {what}"
        elif status == 'blocked':
            kind, sev, dm = 'mission_blocked', 'fyi', False
            line = f"🎯 Mission stuck — {goal}: {m.get('error') or 'needs a decision'}"
        else:
            kind, sev, dm = 'mission_waiting', 'decide', True
            steps = _st.get_mission_steps(m['id'])
            asks = [s for s in steps if s.get('kind') == 'ask']
            q = (asks[-1].get('result_json') or {}).get('question') if asks else ''
            line = f"🎯 Mission asks — {goal}: {q or 'answer it on /missions'}"
        out.append(Finding(key=f"{kind}:{m['id']}", line=line, kind=kind,
                           severity=sev, dm=dm,
                           subject_type='mission', subject_id=str(m['id'])))
    return out
```

Hook it where the other sweeps aggregate (next to `findings += _thread_stalls(now)`):

```python
    findings += _mission_states(now)
```

- [ ] **Step 4: Run test file, expect OK. Also run `python test_watchers.py` if it exists (Glob `chauffeur/tests/test_watch*`); expect OK.**

- [ ] **Step 5: Commit** — bump 2.457.4, message `Finished missions learn to raise a hand (v2.457.4)`, push.

---

### Task 6: Endpoints, auth rules, push-loop wiring, settings

**Files:**
- Modify: `chauffeur/main.py` (page route next to `/mind` ~1679; API block next to mind endpoints ~5085; push loop ~742)
- Modify: `chauffeur/services/auth.py` (RULES: shell line near 202, api line near 351)
- Modify: `chauffeur/services/settings_registry.py` (missions group, next to the mind block ~509)
- Test: `chauffeur/tests/test_missions_endpoints.py`

**Interfaces:**
- Consumes: `missions.launch/tick/step`, `storage` helpers, `_mind_actor(request, claimed)` (reused as-is), `_approver_of_record(actor)`, `chat_actions.act_on_proposal`, `_mind_refresh_if_dirty(result, background_tasks)`.
- Produces routes: `GET /missions` (page), `GET /api/missions/admin`, `POST /api/missions/launch` `{goal, tier?, member_id?}`, `POST /api/missions/{mid}/proposals/{pid}/act` `{act, member_id?}`, `POST /api/missions/{mid}/answer` `{text, member_id?}`, `POST /api/missions/{mid}/drop`, `POST /api/missions/{mid}/ack`.

- [ ] **Step 1: Failing test**

```python
"""Mission endpoints: role gates, launch, answer resumes, approve rides the rail."""
from harness import check
from services import storage, missions


def _reset():
    storage.missions_table.truncate()
    storage.mission_steps_table.truncate()
    storage.members_table.truncate()
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'kid', 'name': 'Lily', 'role': 'child'})
    import datetime as _dt
    storage.set_app_state(f"mission_calls:{_dt.date.today().isoformat()}", {})
    storage.get_settings = lambda: {'missions_enabled': True,
                                    'llm_gemini_api_key': 'F',
                                    'llm_gemini_paid_api_key': 'P'}


def scenario_child_cannot_launch():
    _reset()
    import main
    from fastapi import HTTPException
    try:
        main.missions_launch(body={'goal': 'x', 'member_id': 'kid'}, request=None)
        check(False, "child launch must raise")
    except HTTPException as e:
        check(e.status_code == 403, "child refused with 403")


def scenario_parent_launches_and_answers():
    _reset()
    import main
    res = main.missions_launch(body={'goal': 'plan picnic', 'member_id': 'mom'},
                               request=None)
    check(res['status'] == 'launched', "parent launches")
    mid = res['mission_id']
    storage.update_mission(mid, {'status': 'waiting_user'})
    out = main.missions_answer(mid, body={'text': 'budget is $50',
                                          'member_id': 'mom'}, request=None)
    row = storage.get_mission(mid)
    check(row['status'] == 'running', "an answer resumes the mission")
    notes = [s for s in storage.get_mission_steps(mid) if s['kind'] == 'note']
    check(any('$50' in str(s.get('result_json')) for s in notes),
          "the answer lands on the transcript")


def scenario_admin_payload_shape():
    _reset()
    import main
    mid = missions.launch('g', created_by='mom')['mission_id']
    out = main.missions_admin(request=None)
    check(out['active'][0]['id'] == mid and 'steps' in out['active'][0],
          "active missions arrive with their transcript")
    check('history' in out, "history lane present")


def scenario_ack_and_drop():
    _reset()
    import main
    mid = missions.launch('g', created_by='mom')['mission_id']
    main.missions_drop(mid, body={'member_id': 'mom'}, request=None)
    check(storage.get_mission(mid)['status'] == 'dropped', "drop drops")
    main.missions_ack(mid, body={'member_id': 'mom'}, request=None)
    check(storage.get_mission(mid)['acknowledged_at'], "ack quiets the finding")


if __name__ == '__main__':
    scenario_child_cannot_launch()
    scenario_parent_launches_and_answers()
    scenario_admin_payload_shape()
    scenario_ack_and_drop()
    print("test_missions_endpoints OK")
```

Note on identity in tests: these call endpoints with `request=None` and a
`member_id` in the body, the way `_mind_actor(request, claimed)` supports. If
`_acting_id` refuses a `None` request outright, stub `auth.identify` exactly
as `test_study_state.py`'s `scenario_endpoint_gates_and_serves` does and keep
the assertions unchanged.

- [ ] **Step 2: Run, expect fail** — `AttributeError: main.missions_launch`.

- [ ] **Step 3: Implement**

Page route (next to `/mind`):

```python
@app.get("/missions")
def missions_page(request: Request):
    return templates.TemplateResponse(request=request, name="missions.html")
```
(Template lands in Task 7; until then the route 500s in a browser — fine, tests don't render it. If the repo's `TemplateResponse` raises at import time without the file, create an empty `missions.html` stub in this task and fill it in Task 7.)

API block (next to the mind endpoints, reusing `_mind_actor` — its docstring already covers exactly this admin-surface-or-parent semantics):

```python
@app.get("/api/missions/admin")
def missions_admin(request: Request = None):
    from services import missions as _missions
    active = storage.get_missions(status=['running', 'waiting_user', 'waiting_retry'])
    for m in active:
        m['steps'] = storage.get_mission_steps(m['id'])
    return {"active": active,
            "history": storage.get_missions(status=['done', 'blocked', 'dropped'])[:60]}

@app.post("/api/missions/launch")
def missions_launch(body: dict = Body(default={}), request: Request = None):
    from services import missions as _missions
    actor = _mind_actor(request, body.get('member_id'))
    res = _missions.launch((body.get('goal') or ''),
                           origin_kind=body.get('origin_kind') or 'manual',
                           origin_ref=body.get('origin_ref'),
                           created_by=(actor or {}).get('id') if actor else body.get('member_id'),
                           tier=body.get('tier') or 'mission')
    if res.get('status') not in ('launched',):
        raise HTTPException(status_code=400, detail=res.get('message') or res['status'])
    return res

@app.post("/api/missions/{mission_id}/proposals/{proposal_id}/act")
def missions_proposal_act(mission_id: str, proposal_id: str,
                          body: dict = Body(default={}), request: Request = None,
                          background_tasks: BackgroundTasks = None):
    from services import chat_actions as _ca
    actor = _mind_actor(request, body.get('member_id'))
    act = body.get('act') or 'approve'
    if act not in ('approve', 'dismiss'):
        raise HTTPException(status_code=400, detail="act must be approve|dismiss")
    result = _ca.act_on_proposal(proposal_id, act, _approver_of_record(actor))
    if result.get('status') != 'success':
        raise HTTPException(status_code=400, detail=result.get('message'))
    _mind_refresh_if_dirty(result, background_tasks)
    storage.add_mission_step(mission_id, {'kind': 'note', 'name': f'proposal_{act}',
                                          'result_json': {'proposal_id': proposal_id}})
    return result

@app.post("/api/missions/{mission_id}/answer")
def missions_answer(mission_id: str, body: dict = Body(default={}),
                    request: Request = None):
    _mind_actor(request, body.get('member_id'))
    row = storage.get_mission(mission_id)
    if not row:
        raise HTTPException(status_code=404, detail="No such mission")
    text = (body.get('text') or '').strip()
    if not text:
        raise HTTPException(status_code=400, detail="Say something to send")
    storage.add_mission_step(mission_id, {'kind': 'note', 'name': 'user_answer',
                                          'result_json': {'text': text}})
    if row.get('status') == 'waiting_user':
        storage.update_mission(mission_id, {'status': 'running'})
    return {"status": "success"}

@app.post("/api/missions/{mission_id}/drop")
def missions_drop(mission_id: str, body: dict = Body(default={}),
                  request: Request = None):
    _mind_actor(request, body.get('member_id'))
    if not storage.get_mission(mission_id):
        raise HTTPException(status_code=404, detail="No such mission")
    import time as _t
    storage.update_mission(mission_id, {'status': 'dropped', 'finished_at': _t.time()})
    return {"status": "success"}

@app.post("/api/missions/{mission_id}/ack")
def missions_ack(mission_id: str, body: dict = Body(default={}),
                 request: Request = None):
    _mind_actor(request, body.get('member_id'))
    if not storage.get_mission(mission_id):
        raise HTTPException(status_code=404, detail="No such mission")
    import time as _t
    storage.update_mission(mission_id, {'acknowledged_at': _t.time()})
    return {"status": "success"}
```

Push loop — directly under the Mind block (~main.py:745), same shape:

```python
            # --- Missions (spec: 2026-09-04-mission-engine-design) ---
            # All gating (enabled flag, caps, retries, serialization) lives in
            # missions.tick; this block only keeps the loop alive.
            try:
                from services import missions as _missions_svc
                await asyncio.to_thread(_missions_svc.tick)
            except Exception as me:
                print(f"Missions tick error: {me}")
```

auth.py RULES — one line next to each mind line:

```python
    (ANY, '/missions', ANYONE, None),
```
```python
    # Missions: reads for any signed-in member; launching/approving/answering
    # is parent/adult work decided in the handler (`_mind_actor`, reused).
    (ANY, '/api/missions/*', SIGNED_IN, None),
```

settings_registry.py — next to the mind block:

```python
    _e('missions_enabled', 'missions', 'Missions',
       'Argyle can work multi-step missions (research, compare, draft, '
       'propose) on the paid pro model. Off means completely off — no LLM '
       'calls, no ticks.', page='missions'),
    _e('llm_gemini_paid_api_key', 'missions', 'Paid Gemini API key',
       'Billed key used ONLY by missions (the pro pool). Regular Chauffeur '
       'traffic stays on the free key.', page='missions'),
    _e('model_pool_pro', 'missions', 'Pro model pool',
       'Comma-separated pro models missions may use '
       '(default gemini-3.1-pro, gemini-2.5-pro).', page='missions'),
    _e('mission_cap_launch', 'missions', 'Daily launch cap',
       'Missions that may be started per day (default 3).', page='missions'),
    _e('mission_step_cap', 'missions', 'Steps per mission',
       'LLM calls one mission may spend before it must stop (default 40).',
       page='missions'),
    _e('mission_cap_pro_calls', 'missions', 'Daily pro-call cap',
       'Total paid-model calls per day across all missions (default 120).',
       page='missions'),
```
(Match `_e`'s real signature/anchor conventions in that file; if the group needs registering anywhere else — e.g. a groups list — mirror how 'mind' did it.)

- [ ] **Step 4: Run** `python test_missions_endpoints.py` AND `python test_missions_engine.py` AND `python test_settings_registry.py` — all OK.

- [ ] **Step 5: Commit** — bump 2.457.5, message `Missions get doors, locks, and a heartbeat (v2.457.5)`, push.

---

### Task 7: The /missions page

**Files:**
- Create: `chauffeur/templates/missions.html`
- Test: extend `chauffeur/tests/test_missions_endpoints.py` (route serves; template has no inline sends)

**Interfaces:** consumes `GET /api/missions/admin` payload from Task 6 and posts to the Task 6 endpoints. Follow `docs/ui_design_guide.md` as first reading, and mirror `templates/mind.html`'s page chrome (same head includes, tokens, nav treatment — open mind.html and copy its shell verbatim before styling sections).

- [ ] **Step 1: Failing test** (append)

```python
def scenario_page_route_serves_template():
    import main, os
    tpl = os.path.join(os.path.dirname(main.__file__), 'templates', 'missions.html')
    check(os.path.exists(tpl), "missions.html exists")
    html = open(tpl, encoding='utf-8').read()
    for needle in ('/api/missions/admin', '/api/missions/launch', 'waiting_user'):
        check(needle in html, f"page wires {needle}")
    for banned in ('alert(', 'confirm(', 'prompt('):
        check(banned not in html, f"no browser dialogs ({banned})")
```

- [ ] **Step 2: Run, expect fail** (file missing).

- [ ] **Step 3: Build the page.** Structure (Alpine, mirroring mind.html's idiom):

- Header: "Missions" + one-line law: "Argyle researches and proposes; people approve."
- **Launch card:** textarea for the goal, tier select (`Pro (paid)` default / `Flash (free, benchmark)`), Launch button → POST `/api/missions/launch`; surface non-200 detail via the page's alert idiom.
- **Active section** (per mission): goal, status chip (running / waiting_user / waiting_retry), step transcript (idx, kind badge, name, compact result — render `result_json` via `JSON.stringify` into `textContent`-safe bindings, never `innerHTML`), proposals with Approve/Dismiss buttons → `/proposals/{pid}/act`, drafts shown as blockquotes with "copy to thread" note, answer box when `waiting_user` → `/answer`, Drop button.
- **History section:** last 60 terminal rows: goal, status, summary/error, OK button (→ `/ack`) when unacknowledged.
- **Settings section:** the six Task 6 settings (enabled toggle, paid key password input, pro pool, three caps), saved via whatever settings-save endpoint mind.html's settings section uses (copy that block and swap keys). Check `res.ok` on saves (the mind page's known miss — don't repeat it).
- Poll `/api/missions/admin` every 15s while the tab is visible.

- [ ] **Step 4: Rebuild Tailwind and run tests**

```bash
python chauffeur/tools/build_tailwind.py
cd chauffeur/tests && python test_missions_endpoints.py
```
Expect OK. Load check: `python -c "import sys; sys.path.insert(0,'chauffeur'); import main"` from repo root still imports.

- [ ] **Step 5: Commit** — bump 2.457.6, message `A room where missions are launched, read, and answered (v2.457.6)`, push (include the rebuilt CSS artifact `build_tailwind.py` touches).

---

### Task 8: Doorways — thread button and chat tool in both stacks

**Files:**
- Modify: `chauffeur/templates/threads.html` (Work-this button per thread)
- Modify: `chauffeur/services/agent_tools.py` (v1 schema + handler + registry entries)
- Modify: `chauffeur/services/agent_tools_v2.py` (declaration in `get_available_tools` + wrapper)
- Modify: `chauffeur/services/agent_router.py` (dispatch branch in the actor-allowlisted elif chain ~785)
- Test: extend `chauffeur/tests/test_missions_endpoints.py`

**Interfaces:**
- Produces: v1 tool `launch_mission` `{goal: str, thread_title?: str}`; v2 wrapper `agent_tools_v2.launch_mission(goal, thread_title, actor)`; thread button posting to `/api/missions/launch` with `origin_kind='thread'`, `origin_ref=<thread id>`.

- [ ] **Step 1: Failing test**

```python
def scenario_chat_tool_wired_into_both_stacks():
    from services import agent_tools, agent_tools_v2
    check('launch_mission' in agent_tools.TOOL_SCHEMAS
          and 'launch_mission' in agent_tools.TOOL_HANDLERS, "v1 wired")
    decls = agent_tools_v2.get_available_tools()   # match the real signature
    check(any(d.get('name') == 'launch_mission' for d in decls), "v2 declared")
    # If get_available_tools takes arguments (settings/actor), pass what its
    # existing callers pass — keep the assertion, adjust only the call.
    import inspect
    src = inspect.getsource(__import__('services.agent_router', fromlist=['x']))
    check('launch_mission' in src, "router dispatches it")


def scenario_chat_launch_respects_allowlist_and_thread_origin():
    _reset()
    from services import agent_tools_v2, threads as _threads
    tid = storage.add_thread({'title': 'Pool guy', 'goal': 'get him back',
                              'kind': 'vendor', 'state': 'open'})
    res = agent_tools_v2.launch_mission('get the pool serviced', 'Pool guy',
                                        {'id': 'mom', 'role': 'parent'})
    check(res.get('status') == 'launched', f"parent launches via chat, got {res}")
    row = storage.get_mission(res['mission_id'])
    check(row['origin_kind'] == 'thread' and row['origin_ref'] == tid,
          "fuzzy thread title pins the origin")
    res2 = agent_tools_v2.launch_mission('x', None, {'id': 'kid', 'role': 'child'})
    check(res2.get('status') != 'launched', "child refused")
    res3 = agent_tools_v2.launch_mission('x', None, None)
    check(res3.get('status') != 'launched', "anonymous wall refused (allowlist)")


def scenario_threads_page_has_the_button():
    import main, os
    tpl = os.path.join(os.path.dirname(main.__file__), 'templates', 'threads.html')
    html = open(tpl, encoding='utf-8').read()
    check('/api/missions/launch' in html, "Work-this button posts a launch")
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Implement**

v1 (`agent_tools.py`) — pydantic class near the others:

```python
class LaunchMissionTool(BaseModel):
    """Start a multi-step Argyle mission (research, compare, draft, propose).
    Parent/adult only. Nothing executes without human approval."""
    goal: str = Field(description="What the mission should achieve, in one sentence.")
    thread_title: Optional[str] = Field(None, description="Existing thread this belongs to, if any (fuzzy matched).")
```

Handler near the other `handle_*`:

```python
def handle_launch_mission(args: dict) -> dict:
    from services import missions, storage as _st
    thread = None
    title = (args.get('thread_title') or '').strip()
    if title:
        thread = missions._match_thread(title)
    return missions.launch(args.get('goal') or '',
                           origin_kind='thread' if thread else 'chat',
                           origin_ref=thread['id'] if thread else None,
                           created_by=args.get('_member_id'),
                           tier='mission')
```

Registry entries in `TOOL_SCHEMAS` / `TOOL_HANDLERS`:
```python
    "launch_mission": LaunchMissionTool.model_json_schema(),
```
```python
    "launch_mission": handle_launch_mission,
```

v2 (`agent_tools_v2.py`) — wrapper near `draft_thread_message`:

```python
def launch_mission(goal: str, thread_title: str = None, actor: dict = None) -> dict:
    """Allowlist: a resolved parent/adult launches; anyone else is refused —
    /api/chat is WALL_OR_SERVICE, so an anonymous panel arrives with no actor
    and must not walk through a role blocklist."""
    if not actor or (actor.get('role') or '') not in ('parent', 'adult'):
        return {'status': 'refused',
                'message': 'Only a parent or adult can start a mission.'}
    from services import agent_tools as _v1
    return _v1.handle_launch_mission({'goal': goal, 'thread_title': thread_title,
                                      '_member_id': actor.get('id')})
```

Declaration in `get_available_tools()` (next to `draft_thread_message`'s):

```python
        {
            "name": "launch_mission",
            "description": "Starts a multi-step Argyle MISSION for a bigger goal ('plan the birthday party', 'find someone to fix the fence'): Argyle researches, compares and drafts over the next hour and brings back proposals a parent approves on the Missions page. Nothing is booked, sent or paid automatically — never promise it will be. Parent/adult only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "What the mission should achieve."},
                    "thread_title": {"type": "string", "description": "Existing thread it belongs to, if the user named one (fuzzy matched)."}
                },
                "required": ["goal"]
            }
        },
```

Router (`agent_router.py`) — add `"launch_mission"` to the allowlisted-tools tuple in the elif chain (~line 785) and a dispatch arm next to `draft_thread_message`'s (~823):

```python
                    elif func_name == "launch_mission":
                        res = _atv2.launch_mission(args.get("goal", "") or "",
                                                   args.get("thread_title"),
                                                   actor)
```
(Mirror how sibling arms feed `res` back into the reply; add a prompt-guidance line ONLY if the sibling tools have one.)

threads.html — in each open thread's action row (next to the existing draft/close controls), a button:

```html
<button @click="workThis(t)" class="...same button classes as siblings...">Work this</button>
```
with the Alpine method posting:

```javascript
async workThis(t) {
    const res = await fetch('/api/missions/launch', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        credentials: 'same-origin',
        body: JSON.stringify({goal: `Advance this thread: ${t.title} — ${t.goal || ''}`,
                              origin_kind: 'thread', origin_ref: t.id,
                              member_id: this.memberId || null})});
    const out = await res.json().catch(() => ({}));
    if (!res.ok) { showGlobalAlert(out.detail || 'Could not start the mission'); return; }
    showGlobalAlert('Mission started — watch /missions');
}
```
(Match the page's real member-id source and alert idiom — read how threads.html does its other POSTs and copy that exactly, including the ingress-safe URL prefix idiom if the page uses one.)

- [ ] **Step 4: Run** `python test_missions_endpoints.py` + `python test_agent_driver_tools.py` (registry intact) + `python chauffeur/tools/build_tailwind.py` (button classes) — all OK.

- [ ] **Step 5: Commit** — bump 2.457.7, message `Three doorways into the same engine (v2.457.7)`, push.

---

### Task 9: The fences — pins and an end-to-end runthrough

**Files:**
- Test: `chauffeur/tests/test_missions_pins.py`

**Interfaces:** consumes everything; produces the structural guarantees.

- [ ] **Step 1: Write the pin tests** (these should PASS immediately if Tasks 1–8 are honest — a failure here is a real defect, fix the source, never the pin)

```python
"""Structural fences: paid key unreachable outside the pro resolver, mailer
unreachable from missions, the engine runs end-to-end without executing."""
import os
import re
from harness import check
from services import storage, missions


SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _sources():
    for root, _dirs, files in os.walk(os.path.join(SRC, 'services')):
        for f in files:
            if f.endswith('.py'):
                yield os.path.join(root, f)


def scenario_paid_key_is_read_in_one_place():
    allowed = {'model_pools.py', 'settings_registry.py'}
    offenders = []
    for path in _sources():
        if os.path.basename(path) in allowed:
            continue
        text = open(path, encoding='utf-8').read()
        if 'llm_gemini_paid_api_key' in text:
            offenders.append(os.path.basename(path))
    check(not offenders,
          f"paid key read only via api_key_for_pool, offenders: {offenders}")
    # main.py too — endpoints must not shortcut the resolver
    text = open(os.path.join(SRC, 'main.py'), encoding='utf-8').read()
    check('llm_gemini_paid_api_key' not in text, "main.py never touches the paid key")


def scenario_missions_cannot_reach_the_mailer():
    text = open(os.path.join(SRC, 'services', 'missions.py'), encoding='utf-8').read()
    for banned in ('mailer', 'send_drafted', 'smtplib'):
        check(banned not in text, f"missions.py never references {banned}")


def scenario_mission_tier_never_serves_free_models():
    from services import model_pools
    for m in model_pools.models_for('mission', {}):
        check('pro' in m, f"mission tier serves pro models only, got {m}")


def scenario_end_to_end_runthrough_executes_nothing():
    """RUNS the loop (source-reading tests miss runtime breaks): launch →
    research → read → propose → finish → finding → approve executes exactly
    once, via the rail."""
    storage.missions_table.truncate()
    storage.mission_steps_table.truncate()
    import datetime as _dt
    storage.set_app_state(f"mission_calls:{_dt.date.today().isoformat()}", {})
    storage.get_settings = lambda: {'missions_enabled': True,
                                    'llm_gemini_api_key': 'F',
                                    'llm_gemini_paid_api_key': 'P'}
    executed = []
    from services import agent_tools, chat_actions, web
    orig_exec, orig_research = agent_tools.execute_tool, web.research
    agent_tools.execute_tool = lambda n, a: executed.append((n, a)) or {'status': 'ok', 'echo': n}
    web.research = lambda q, read_pages=6: {'status': 'ok', 'answer': 'three vendors',
                                            'facts': [], 'sources': []}
    script = [
        {'action': 'research', 'question': 'magicians near us'},
        {'action': 'tool', 'tool': 'get_current_state', 'args': {}},
        {'action': 'propose', 'tool': 'add_errand',
         'args': {'name': 'call the magician'}, 'summary': 'Call the magician',
         'why': 'top result'},
        {'action': 'finish', 'summary': '1 proposal ready'},
    ]
    missions._llm = lambda m, s, u, st: script.pop(0)
    try:
        mid = missions.launch('book party entertainment', created_by='mom')['mission_id']
        for _ in range(4):
            missions.tick()
        row = storage.get_mission(mid)
        check(row['status'] == 'done', f"mission finished, got {row['status']}")
        reads = [e for e in executed if e[0] == 'get_current_state']
        check(len(reads) == 1 and len(executed) == 1,
              f"only the read executed during the run, got {executed}")
        from services import watchers
        found = [f for f in watchers._mission_states(_dt.datetime.now())
                 if f.subject_id == str(mid)]
        check(found and found[0].kind == 'mission_done', "the finding raised")
        prop_step = [s for s in storage.get_mission_steps(mid)
                     if s['kind'] == 'proposal'][0]
        pid = prop_step['result_json']['proposal_id']
        res = chat_actions.act_on_proposal(pid, 'approve',
                                           {'id': 'mom', 'name': 'Mom', 'role': 'parent'})
        check(res.get('status') == 'success', f"approve rides the rail, got {res}")
        check(len(executed) == 2 and executed[-1][0] == 'add_errand',
              "approval executed the write exactly once")
    finally:
        agent_tools.execute_tool, web.research = orig_exec, orig_research


if __name__ == '__main__':
    scenario_paid_key_is_read_in_one_place()
    scenario_missions_cannot_reach_the_mailer()
    scenario_mission_tier_never_serves_free_models()
    scenario_end_to_end_runthrough_executes_nothing()
    print("test_missions_pins OK")
```

Note: `act_on_proposal`'s approve path for a registry action falls through to `agent_tools.TOOL_HANDLERS` inside `chat_actions._execute` — with `execute_tool` stubbed above, patch whichever layer `_execute` actually calls (read `_execute` first; if it calls handlers directly, stub `agent_tools.TOOL_HANDLERS['add_errand']` instead and count through that). Keep the assertion: zero write executions before approve, exactly one after.

- [ ] **Step 2: Run** `python test_missions_pins.py` — expect OK. Any failure = fix the SOURCE (e.g. a stray paid-key read), never loosen the pin.

- [ ] **Step 3: Commit** — bump 2.457.8, message `The fences hold: one key reader, no mailer, nothing executes unapproved (v2.457.8)`, push.

---

### Task 10: Docs, full sweep, ship

**Files:**
- Modify: `chauffeur/system_capabilities.md` (new "Missions" section; update the model-pools section with the pro pool + paid-key fence)
- Modify: `docs/superpowers/specs/2026-09-04-mission-engine-design.md` (append `missions_enabled` default-OFF line to the caps paragraph — it shipped as a flag per the mind precedent)

- [ ] **Step 1: Write the capabilities section.** Cover: what a mission is, the three doorways, the propose-approve law, the pro pool + paid key fence + caps (with setting names), the /missions surface, the enable checklist (Config → Missions → paste paid key → flip `missions_enabled`), and the flash benchmark tier.

- [ ] **Step 2: Full sweep**

```bash
python chauffeur/tools/test.py
```
Expected: all files pass (baseline was 213/213; you added 3 files → 216/216). Fix anything red before proceeding.

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m 'Chauffeur learns to take a load off: missions ship dark (v2.457.9)'
git push
```
(Bump config.yaml to 2.457.9. "Dark" is real: `missions_enabled` is OFF until the user flips it and rebuilds the add-on per the HA workflow.)

---

## Self-review notes (already applied)

- Spec coverage: pro pool/tier/key (T1), tables (T2), loop laws + proposals + draft + ask (T3), caps/launch/tick/no-fallback pause (T4), findings (T5), endpoints/auth/settings/heartbeat (T6), surface (T7), three doorways incl. both chat stacks (T8), source pins + runtime runthrough (T9), capabilities doc + dark-ship (T10). Deferred by spec (not planned): mind Handle-it doorway, occasions doorway, study furniture, auto-launch.
- Type consistency: `missions.launch` returns `{'status', 'mission_id'?}` everywhere; step kinds fixed set `llm|tool|proposal|draft|ask|note`; `_mind_actor` reused unmodified; `api_key_for_pool(pool, settings)` is the single key resolver.
- Known judgment calls an executor must NOT "fix" silently: default-deny READ_TOOLS (a missing read tool is a note-bounce, add it consciously); no free-pool fallback for tier 'mission'; `send_direct_message` excluded entirely; `missions_enabled` ships OFF.

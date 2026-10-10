# Browse missions, build 3 — the conversation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "Get the dishwasher fixed" said to Argyle opens a thread and a mission on it; every question, release and hand-off reaches the person as a DM they can answer in words; the finish lands on the thread as a note, a pre-filled next step and a DM; the thread card shows the mission's steps.

**Architecture:** One router tool, `start_mission_for`, creates the thread and the thread-origin mission and makes the thread the conversation's focus. `missions.step` DMs on `ask_user` and on `finish` (release and hand-off already do, build 2). A thread whose origin mission waits on the person exposes an `answer` option that routes to that mission, so "tell the mission yes" works against the thread focus. A finish writes a thread `note`, an `advance` with a pre-filled next action (the planner's `finish` JSON gains `next_action`), and ranks the thread tier 1 through a new reply lead. The /threads details include the shared transcript component for the thread's missions.

**Tech Stack:** as builds 1–2.

**Spec:** `docs/superpowers/specs/2026-10-10-browse-missions-design.md` §4, §5. Builds 1 and 2 precede.

## Global Constraints

- Run from `E:\repositories\Chauffeur\chauffeur` with `..\venv\Scripts\python.exe`; tests with `HA_BASE_URL` unset.
- Gate: `python tools/test.py start_mission browse missions triage situation threads agent_v2_bridge tailwind_build` plus the live test of Task 4.
- A parent or adult only (voice as the parent of record); a child via @argyle is refused; the PWA with no member is never promoted (the router's existing rule).
- Nothing is booked: every finish that touched a scheduling site says "Nothing is booked" in the note and the DM (the planner's rule plus a deterministic suffix when a `browse` step exists).
- `mission_transcript.html` is included exactly twice in `missions_page.html` (its contract test); the threads page includes it under its own scope with the same `mission` variable.
- Every commit bumps `config.yaml` (+1 per commit), message ends `(vX.Y.Z)`, push. Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Persisted prose is normal English.

## Review Focus

1. **"Get the dishwasher fixed" said twice** (voice repeats, two parents): one thread, one mission; the second call names the running one. Pinned in Task 1 (`scenario_a_running_mission_is_not_duplicated`).
2. **An answer when the mission is not waiting** ("tell the mission yes" after it already resumed): refused with the way out, nothing appended. Pinned in Task 3 (`scenario_answer_when_not_waiting_is_refused`).
3. **A finish with no `next_action`** from the planner: the thread note still lands, the advance is "Read Argyle's summary", the DM still goes. Pinned in Task 2 (`scenario_finish_without_next_action`).
4. **A thread closed by hand while its mission runs**: the mission's finish does not reopen the thread; the note lands, no advance, the DM says the thread was closed. Pinned in Task 2 (`scenario_finish_on_a_closed_thread`).
5. **A child owner's House card** with a running mission: steps visible, no release buttons, no answer box. Pinned in Task 4 (live).

---

### Task 1: `start_mission_for`

**Files:**
- Modify: `services/agent_tools_v2.py` (the tool, schema, Pydantic, `TOOL_SCHEMAS`, handler, `TOOL_HANDLERS`)
- Modify: `services/agent_router.py` (the situation-tools dispatch tuple; `TERMINAL_ACTION_TOOLS`)
- Test: `tests/test_start_mission.py` (new)

**Interfaces:**
- Produces: `agent_tools_v2.start_mission_for(goal: str, title: str = None, acting_member=None, focus_key=None) -> dict` with `thread_id`, `mission_id`, `message`; creates the thread (`threads.create(title or goal[:60], owner_member_id=actor id, goal=goal, created_by=actor id)`), launches via `missions.launch(goal, origin_kind='thread', origin_ref=thread_id, created_by=actor id)`, sets focus to the thread; dedupe: an open thread with a running/browsing/waiting mission whose title or goal contains the goal's first three words → names it, launches nothing. Terminal.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_start_mission.py
"""'Get the dishwasher fixed': one tool opens the thread and the mission and
holds the thread as focus. Spec 2026-10-10 browse missions §4."""
import time

from harness import check  # noqa: F401
from services import storage, threads, missions, triage, situations, agent_tools_v2 as tools, agent_router

MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}
KID = {'id': 'kid', 'name': 'Kate', 'role': 'child'}


def _reset():
    for t in (storage.threads_table, storage.missions_table, storage.mission_steps_table, storage.members_table,
              storage.app_state_table, storage.chat_channels_table, storage.chat_messages_table):
        t.truncate()
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True})
    storage.get_settings = lambda: {'missions_enabled': True, 'llm_gemini_paid_api_key': 'paid', 'thread_stall_days': 7}
    situations.REFRESH_DELAY_S = 0
    situations._pool_call = lambda *a, **k: {}


def scenario_opens_thread_and_mission_and_focus():
    _reset()
    res = tools.start_mission_for('get the dishwasher fixed', acting_member=MOM, focus_key='voice:1')
    check(res['status'] == 'success' and res['thread_id'] and res['mission_id'], f"opened: {res}")
    t = storage.get_thread(res['thread_id'])
    check(t['title'] == 'get the dishwasher fixed' and t['owner_member_id'] == 'mom' and t['goal'] == 'get the dishwasher fixed', f"the thread: {t}")
    m = storage.get_mission(res['mission_id'])
    check(m['origin_kind'] == 'thread' and m['origin_ref'] == res['thread_id'] and m['created_by'] == 'mom' and m['status'] == 'running', f"the mission: {m}")
    f = triage.get_focus('voice:1')
    check(f and f['kind'] == 'thread' and f['id'] == res['thread_id'], "the thread is the focus")
    check(res['message'].startswith('On it.'), f"the reply: {res['message']}")
    res = tools.start_mission_for('fix the fence', title='Back fence', acting_member=MOM, focus_key='voice:1')
    check(storage.get_thread(res['thread_id'])['title'] == 'Back fence', "a given title is used")


def scenario_a_running_mission_is_not_duplicated():
    _reset()
    first = tools.start_mission_for('get the dishwasher fixed', acting_member=MOM, focus_key='voice:1')
    again = tools.start_mission_for('get the dishwasher fixed please', acting_member=MOM, focus_key='voice:2')
    check(again['status'] == 'success' and again.get('mission_id') == first['mission_id'] and 'already' in again['message'].lower(), f"named, not duplicated: {again}")
    check(len(storage.get_missions()) == 1 and len(storage.get_threads()) == 1, "one of each")
    check(triage.get_focus('voice:2')['id'] == first['thread_id'], "the second conversation's focus is the same thread")


def scenario_gates():
    _reset()
    check(tools.start_mission_for('x', acting_member=KID)['status'] == 'error', "a child is refused")
    check(tools.start_mission_for('x', acting_member=None)['status'] == 'error', "no actor is refused")
    storage.get_settings = lambda: {'missions_enabled': False, 'thread_stall_days': 7}
    res = tools.start_mission_for('x', acting_member=MOM)
    check(res['status'] == 'error' and 'off' in res['message'].lower() and not storage.get_threads(), "missions off: no thread opened either")


def scenario_declared_dispatched_terminal():
    decl = {t['name'] for t in tools.get_available_tools()}
    check('start_mission_for' in decl and 'start_mission_for' in tools.TOOL_HANDLERS and 'start_mission_for' in tools.TOOL_SCHEMAS, "registry")
    src = open('services/agent_router.py', encoding='utf-8').read()
    check('"start_mission_for"' in src.split('TERMINAL_ACTION_TOOLS = {')[1].split('}')[0], "terminal")
    _reset()
    orig = agent_router.call_gemma_with_fallback
    n = {'i': 0}
    def fake(prompt, tools_, system):
        n['i'] += 1
        return {'tool_calls': [{'name': 'start_mission_for', 'arguments': {'goal': 'get the dishwasher fixed'}}], 'message': ''} if n['i'] == 1 else {'tool_calls': [], 'message': ''}
    agent_router.call_gemma_with_fallback = fake
    try:
        res = agent_router.process_agent_request('get the dishwasher fixed', focus_key='voice:9')
    finally:
        agent_router.call_gemma_with_fallback = orig
    check(res['message'].startswith('On it.') and storage.get_missions()[0]['created_by'] == 'mom', f"voice opens it as the parent of record: {res}")


SCENARIOS = [scenario_opens_thread_and_mission_and_focus, scenario_a_running_mission_is_not_duplicated, scenario_gates,
             scenario_declared_dispatched_terminal]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_start_mission.py`
Expected: `AttributeError: ... no attribute 'start_mission_for'`.

- [ ] **Step 3: The tool** — in `services/agent_tools_v2.py` after `read_mail`:

```python
def start_mission_for(goal: str, title: str = None, acting_member: dict = None, focus_key: str = None) -> Dict[str, Any]:
    """'Get the dishwasher fixed': open a thread and a mission on it, and
    make the thread the thing we are talking about. Parents and adults."""
    if not acting_member or acting_member.get('role') not in ('parent', 'adult'):
        return {"status": "error", "message": "Only a parent or adult can start that."}
    from services import storage, threads as _threads, missions as _missions, triage as _tri
    goal = (goal or '').strip()
    if not goal:
        return {"status": "error", "message": "Say what to get done."}
    settings = storage.get_settings() or {}
    if not settings.get('missions_enabled', False):
        return {"status": "error", "message": "Missions are off (Missions settings)."}
    # One of each: a live mission on an open thread about the same thing is named, not doubled.
    words = [w for w in goal.lower().split() if len(w) > 2][:3]
    for m in storage.get_missions(status=['running', 'browsing', 'waiting_user', 'waiting_retry']):
        if m.get('origin_kind') != 'thread':
            continue
        t = storage.get_thread(m.get('origin_ref') or '')
        hay = ((t or {}).get('title', '') + ' ' + (t or {}).get('goal', '') + ' ' + m.get('goal', '')).lower()
        if t and t.get('state') not in ('done', 'dropped') and words and all(w in hay for w in words):
            _tri.set_focus(focus_key, 'thread', t['id'], t.get('title') or '')
            return {"status": "success", "thread_id": t['id'], "mission_id": m['id'],
                    "message": f"That's already under way: \"{t.get('title')}\". I'll come back when I have something or need you."}
    tid = _threads.create(title=(title or goal)[:80], owner_member_id=acting_member['id'], goal=goal, kind='vendor',
                          created_by=acting_member['id'])
    res = _missions.launch(goal, origin_kind='thread', origin_ref=tid, created_by=acting_member['id'], tier='mission')
    if res.get('status') not in ('success', 'launched') or not res.get('mission_id'):
        return {"status": "error", "message": res.get('message') or 'could not start the mission', "thread_id": tid}
    _tri.set_focus(focus_key, 'thread', tid, (title or goal)[:80])
    return {"status": "success", "thread_id": tid, "mission_id": res['mission_id'],
            "message": "On it. I'll come back when I have something or need you."}
```

Read `missions.launch`'s return shape first (`grep -n "def launch" -A 30 services/missions.py`) and match `status`/`mission_id` keys exactly.

Schema in `get_available_tools()`:

```python
        {
            "name": "start_mission_for",
            "description": "Start getting something done that takes several steps with people or companies outside the family: 'get the dishwasher fixed', 'find someone to clean the gutters', 'sort out the permit'. Opens a thread and puts Argyle to work on it; Argyle comes back with questions and results. Nothing is booked, paid or sent without the person. Parent/adult only.",
            "parameters": {"type": "object",
                           "properties": {"goal": {"type": "string", "description": "What to get done, in the person's words."},
                                          "title": {"type": "string", "description": "A short name for the thread, if the person gave one."}},
                           "required": ["goal"]}
        },
```

Pydantic `StartMissionForTool(goal: str, title: Optional[str] = None)`, `TOOL_SCHEMAS`, `handle_start_mission_for(args)` → `start_mission_for(args.get('goal') or '', title=args.get('title'), acting_member=_registry_parent())`, `TOOL_HANDLERS`. Router: add `"start_mission_for"` to the situation-tools dispatch tuple (actor resolution, parent-of-record substitution, `focus_key` by signature) and to `TERMINAL_ACTION_TOOLS`. Add it to `PROPOSE_ONLY` nothing (it is a write).

- [ ] **Step 4: Run the tests**

Run: `..\venv\Scripts\python.exe tests\test_start_mission.py` and `..\venv\Scripts\python.exe tools\test.py agent_v2_bridge triage situation_tools`
Expected: `4/4`; related green.

- [ ] **Step 5: Commit**

```bash
git add services/agent_tools_v2.py services/agent_router.py tests/test_start_mission.py config.yaml
git commit -m "feat(missions): start_mission_for - 'get the dishwasher fixed' opens a thread and a mission and holds the thread as focus (vX.Y.Z)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

### Task 2: DMs on ask and finish; the finish lands on the thread

**Files:**
- Modify: `services/missions.py` (`_system_prompt` finish shape, `step` ask_user and finish branches, `_land_finish`)
- Modify: `services/situations.py` (`_reply_option` learns the `mission` entry; `triage.REPLY_LEADS` gains `advance:mission`)
- Modify: `services/triage.py` (`REPLY_LEADS`)
- Test: `tests/test_browse_mission.py` (append) or `tests/test_start_mission.py` (append)

**Interfaces:**
- Produces: the planner's `finish` JSON may carry `next_action` (a short imperative) and `next_action_at` (YYYY-MM-DD); `missions._land_finish(mission, res)` on a thread-origin mission appends a thread history entry `{kind: 'mission', text: summary, next_action, mission_id}`, sets the thread's `next_action`/`next_action_at` via `threads.advance` when the thread is open, and DMs "{summary} Next: {next_action}. Nothing is booked." (the last sentence only when a `browse` step exists). `ask_user` DMs the question with "Reply here or on the thread card."
- `_options_thread`: when the newest real history entry is a `mission` entry with `next_action`, the lead is `_opt('advance', next_action, {'next_action': next_action, 'next_action_at': ...}, 'mission')`; `triage.REPLY_LEADS` includes `advance:mission` → tier 1.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_start_mission.py`)

```python
SENT = []


def _dm_capture():
    SENT.clear()
    missions._post = lambda dm, argyle, body, card=None: SENT.append(body) or {'id': 'm'}


def scenario_ask_user_dms_the_question():
    _reset(); _dm_capture()
    res = tools.start_mission_for('get the dishwasher fixed', acting_member=MOM, focus_key='voice:1')
    missions._llm = lambda m, s, u, st: {'action': 'ask_user', 'question': 'Send me a photo of the label inside the door.'}
    missions.step(storage.get_mission(res['mission_id']))
    check(SENT and 'photo of the label' in SENT[-1] and 'thread card' in SENT[-1].lower(), f"the question reaches the person with the way to answer: {SENT}")


def scenario_finish_lands_on_the_thread_with_a_prefilled_next_step():
    _reset(); _dm_capture()
    res = tools.start_mission_for('get the dishwasher fixed', acting_member=MOM, focus_key='voice:1')
    mid, tid = res['mission_id'], res['thread_id']
    storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {}, 'result_json': {'outcome': 'done', 'text': 'x', 'turns': 3}})
    missions._llm = lambda m, s, u, st: {'action': 'finish', 'summary': 'Bodewell can come Tue Oct 20 8-noon; trip charge $114.95.',
                                         'next_action': 'Book Tue Oct 20, 8-noon ($114.95 trip charge)', 'next_action_at': '2026-10-17'}
    missions.step(storage.get_mission(mid))
    t = storage.get_thread(tid)
    last = [h for h in t['history'] if h['kind'] == 'mission'][-1]
    check('$114.95' in last['text'] and last['next_action'].startswith('Book Tue') and last['mission_id'] == mid, f"the note: {last}")
    check(t['next_action'].startswith('Book Tue') and t['next_action_at'] == '2026-10-17', f"the thread's next step is set: {t['next_action']}")
    check(SENT and '$114.95' in SENT[-1] and 'Nothing is booked' in SENT[-1] and 'Book Tue' in SENT[-1], f"the DM: {SENT[-1]}")
    s = situations.view('thread', tid, MOM)
    check(s['next_step']['id'] == 'advance:mission' and s['next_step']['label'].startswith('Book Tue')
          and s['next_step']['payload']['next_action'].startswith('Book Tue'), f"the card leads with the pre-filled step: {s['next_step']}")
    check(triage.tier(s) == 1, "a finished mission's thread ranks tier 1")


def scenario_finish_without_next_action():
    _reset(); _dm_capture()
    res = tools.start_mission_for('fix the fence', acting_member=MOM)
    missions._llm = lambda m, s, u, st: {'action': 'finish', 'summary': 'Two quotes found; both need a site visit.'}
    missions.step(storage.get_mission(res['mission_id']))
    t = storage.get_thread(res['thread_id'])
    check([h for h in t['history'] if h['kind'] == 'mission'] and t['next_action'] == "Read Argyle's summary", f"a default next step: {t['next_action']}")
    check(SENT and 'Two quotes' in SENT[-1] and 'Nothing is booked' not in SENT[-1], "no browse touched a site: no booking line")


def scenario_finish_on_a_closed_thread():
    _reset(); _dm_capture()
    res = tools.start_mission_for('fix the fence', acting_member=MOM)
    threads.close(res['thread_id'], 'done', who='mom')
    missions._llm = lambda m, s, u, st: {'action': 'finish', 'summary': 'Done anyway.', 'next_action': 'Call them'}
    missions.step(storage.get_mission(res['mission_id']))
    t = storage.get_thread(res['thread_id'])
    check(t['state'] == 'done' and [h for h in t['history'] if h['kind'] == 'mission'] and t.get('next_action') != 'Call them', "the note lands; the closed thread is not reopened or advanced")
    check(SENT and 'closed' in SENT[-1].lower(), f"the DM says the thread was closed: {SENT[-1]}")


SCENARIOS += [scenario_ask_user_dms_the_question, scenario_finish_lands_on_the_thread_with_a_prefilled_next_step,
              scenario_finish_without_next_action, scenario_finish_on_a_closed_thread]
```

- [ ] **Step 2: Run to verify they fail**

Run: `..\venv\Scripts\python.exe tests\test_start_mission.py`
Expected: the four FAIL (no DM on ask; no `mission` history entry).

- [ ] **Step 3: The engine** — `services/missions.py`:

In `_system_prompt`, the finish line becomes `'{"action":"finish","summary":"<what was achieved + what awaits approval>","next_action":"<the one thing the person should do next, short, imperative; optional>","next_action_at":"<YYYY-MM-DD, optional>"}\n'`.

In `step()`:

```python
    if action == 'ask_user':
        q = (res.get('question') or '').strip()
        storage.add_mission_step(mid, {'kind': 'ask', 'name': 'question', 'result_json': {'question': q}})
        row = _close(mid, 'waiting_user')
        _dm_person(mission, f"{q} (mission: {mission.get('goal')}). Reply here, or on the thread card.")
        return row

    if action == 'finish':
        storage.add_mission_step(mid, {'kind': 'llm', 'name': 'finish', 'result_json': res})
        row = _close(mid, 'done', summary=(res.get('summary') or '').strip())
        _land_finish(storage.get_mission(mid), res)
        return row
```

and the new function:

```python
def _land_finish(mission: dict, res: dict) -> None:
    """A finish reaches the thread (a `mission` history entry and a
    pre-filled next step) and the person (a DM). Nothing is booked: said
    outright whenever a browse touched a site."""
    summary = (res.get('summary') or '').strip()
    nxt = (res.get('next_action') or '').strip() or "Read Argyle's summary"
    when = res.get('next_action_at')
    touched_site = any(s.get('kind') == 'browse' for s in storage.get_mission_steps(mission['id']))
    tail = ' Nothing is booked.' if touched_site else ''
    tid = mission.get('origin_ref') if mission.get('origin_kind') == 'thread' else None
    thread = storage.get_thread(tid) if tid else None
    if thread:
        storage.append_thread_history(tid, {'kind': 'mission', 'text': summary, 'next_action': nxt,
                                            'next_action_at': when, 'mission_id': mission['id'], 'who': 'argyle'})
        if thread.get('state') not in ('done', 'dropped'):
            from services import threads as _threads
            _threads.advance(tid, nxt, next_action_at=when, who=None)
            _dm_person(mission, f"{summary} Next: {nxt}.{tail}")
        else:
            _dm_person(mission, f"{summary} (The thread \"{thread.get('title')}\" was closed, so I left it closed.){tail}")
        from services import situations as _sit
        _sit.touched('thread', tid)
    else:
        _dm_person(mission, f"{summary} Next: {nxt}.{tail}")
```

`threads.advance` appends an `advance` history entry after the `mission` entry; `_reply_option` must therefore look past an `advance` that the finish itself wrote. Simplest: write the `mission` entry AFTER `advance` (call `advance` first, then append the `mission` entry) so the newest real entry is the `mission` one. Do that.

- [ ] **Step 4: Situations and triage** — in `services/situations.py` `_reply_option`, before the `received` check:

```python
    if history and history[-1].get('kind') == 'mission' and (history[-1].get('next_action') or '').strip():
        h = history[-1]
        return _opt('advance', h['next_action'], {'next_action': h['next_action'], 'next_action_at': h.get('next_action_at')}, 'mission')
```

(keep the function's existing `received` branch after it). In `services/triage.py`: `REPLY_LEADS = ('advance:confirm', 'draft:reply', 'advance:read', 'advance:mission')`.

- [ ] **Step 5: Run the tests**

Run: `..\venv\Scripts\python.exe tests\test_start_mission.py` and `..\venv\Scripts\python.exe tools\test.py missions triage situation threads reply`
Expected: `8/8`; related green (`test_reply_reading`'s lead scenarios unchanged; a `mission` entry is a "real" history kind for the stall clock, which is right).

- [ ] **Step 6: Commit**

```bash
git add services/missions.py services/situations.py services/triage.py tests/test_start_mission.py config.yaml
git commit -m "feat(missions): a question reaches the person as a DM; a finish lands on the thread as a note and a pre-filled next step, ranks tier 1, and says nothing is booked (vX.Y.Z)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

### Task 3: Answering through the thread

**Files:**
- Modify: `services/situations.py` (`_options_thread` offers the mission's `answer`/`release` options; `_run` routes them)
- Test: `tests/test_start_mission.py`

**Interfaces:**
- Produces: a thread whose origin mission (the newest mission with `origin_ref == thread id`) is `waiting_user` leads with that mission's ask: `answer:mission:<mid>` (label = the question) or the three `release:*` options with ids `release:mission:<mid>:approve|decline|stop`; `_run` on a thread with such an option id routes to the mission (`act('mission', mid, …)`), so "tell the mission yes" through `act_on_situation` on the thread focus works, and so does the card.

- [ ] **Step 1: Write the failing tests** (append)

```python
def scenario_thread_card_carries_its_missions_question():
    _reset(); _dm_capture()
    res = tools.start_mission_for('get the dishwasher fixed', acting_member=MOM, focus_key='voice:1')
    mid, tid = res['mission_id'], res['thread_id']
    missions._llm = lambda m, s, u, st: {'action': 'ask_user', 'question': 'Which Friday works?'}
    missions.step(storage.get_mission(mid))
    s = situations.view('thread', tid, MOM)
    check(s['next_step']['verb'] == 'answer' and s['next_step']['id'] == f'answer:mission:{mid}' and 'Which Friday' in s['next_step']['label'], f"the thread leads with the mission's question: {s['next_step']}")
    check(triage.tier(s) == 0, "a thread waiting on the person's answer is tier 0")
    out = tools.act_on_situation(verb='answer', text='the 17th', acting_member=MOM, focus_key='voice:1')
    check(out['status'] == 'success' and storage.get_mission(mid)['status'] == 'running', f"'tell the mission' through the thread focus: {out}")
    last = storage.get_mission_steps(mid)[-1]
    check(last['name'] == 'user_answer' and last['result_json']['text'] == 'the 17th', "the answer is on the transcript")


def scenario_thread_card_carries_its_missions_release():
    _reset(); _dm_capture()
    res = tools.start_mission_for('get the dishwasher fixed', acting_member=MOM, focus_key='voice:1')
    mid, tid = res['mission_id'], res['thread_id']
    storage.get_settings = lambda: {'missions_enabled': True, 'llm_gemini_paid_api_key': 'paid', 'thread_stall_days': 7, 'contact_first_name': 'Jeff'}
    missions._browse_async = False
    missions._browse = lambda **kw: {'outcome': 'needs_release', 'text': 'wants first_name', 'learned': {}, 'stopped_at': 'https://bodewell.com/f',
                                     'wanted_fields': ['first_name'], 'turns': 1, 'tokens_in': 1, 'tokens_out': 1, 'seconds': 1, 'screenshots': [], 'filled': {}}
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    s = situations.view('thread', tid, MOM)
    ids = [o['id'] for o in s['options'] if o['verb'] == 'release']
    check(ids == [f'release:mission:{mid}:approve', f'release:mission:{mid}:decline', f'release:mission:{mid}:stop'], f"the thread carries the release: {ids}")
    seq = [{'outcome': 'done', 'text': 'ok', 'learned': {}, 'stopped_at': 'u', 'wanted_fields': [], 'turns': 1, 'tokens_in': 1, 'tokens_out': 1, 'seconds': 1, 'screenshots': [], 'filled': {}}]
    missions._browse = lambda **kw: seq.pop(0)
    out = situations.act('thread', tid, 'release', option_id=f'release:mission:{mid}:approve', actor=MOM)
    check(out['status'] == 'success' and storage.get_mission(mid)['status'] == 'running' and storage.get_mission(mid)['releases'], f"approve through the thread card: {out}")


def scenario_answer_when_not_waiting_is_refused():
    _reset(); _dm_capture()
    res = tools.start_mission_for('get the dishwasher fixed', acting_member=MOM, focus_key='voice:1')
    out = tools.act_on_situation(verb='answer', text='yes', acting_member=MOM, focus_key='voice:1')
    check(out['status'] == 'error' and 'not on the table' in out['message'], f"nothing to answer: {out}")
    check(not [s for s in storage.get_mission_steps(res['mission_id']) if s['name'] == 'user_answer'], "nothing appended")


SCENARIOS += [scenario_thread_card_carries_its_missions_question, scenario_thread_card_carries_its_missions_release,
              scenario_answer_when_not_waiting_is_refused]
```

- [ ] **Step 2: Run to verify they fail**

Run: `..\venv\Scripts\python.exe tests\test_start_mission.py`
Expected: the three FAIL (the thread's options carry no mission ask).

- [ ] **Step 3: Situations** — in `services/situations.py`:

```python
def _thread_mission(row: dict):
    """The newest live mission opened from this thread, or None."""
    rows = [m for m in storage.get_missions() if m.get('origin_kind') == 'thread' and m.get('origin_ref') == row.get('id')
            and m.get('status') in ('running', 'browsing', 'waiting_user', 'waiting_retry')]
    rows.sort(key=lambda m: m.get('created_at') or 0)
    return rows[-1] if rows else None
```

In `_options_thread`, before the reply lead:

```python
    m = _thread_mission(row)
    if m and m.get('status') == 'waiting_user':
        mrow = load('mission', m['id'])
        for o in _options_mission(mrow):
            if o['verb'] in ('answer', 'release'):
                out.append(_opt(o['verb'], o['label'], o['payload'], f"mission:{m['id']}" + (':' + o['id'].split(':', 1)[1] if ':' in o['id'] else '')))
```

So the ids become `answer:mission:<mid>` and `release:mission:<mid>:approve`. In `_run`, at the top:

```python
    if kind == 'thread' and verb in ('answer', 'release') and isinstance(p, dict) and p.get('_mission_id'):
        ...
```

Simpler: resolve the routing from the option id in `act()` before `_run`: after `opt` is found,

```python
    if kind == 'thread' and opt['id'].startswith(f"{verb}:mission:"):
        mid = opt['id'].split(':')[2]
        sub = ':'.join(opt['id'].split(':')[3:])
        return act('mission', mid, verb, option_id=f"{verb}:{sub}" if sub else verb, payload=payload, actor=actor)
```

(`act('mission', …)` re-derives the mission's own options, keeps every gate, bumps and refreshes the mission; then bump/refresh the thread too: `bump_rev('thread', sid); request_refresh('thread', sid)` after a success.)

Triage: a thread leading with `answer:mission:*` is waiting on the person: in `triage.tier`, for a thread, `if (next_step id or '').startswith('answer:mission:') or startswith('release:mission:'): return 0`.

- [ ] **Step 4: Run the tests**

Run: `..\venv\Scripts\python.exe tests\test_start_mission.py` and `..\venv\Scripts\python.exe tools\test.py situation triage threads missions reply`
Expected: `11/11`; related green (`test_situation_tools.scenario_parity_both_ways` unchanged: no new verb).

- [ ] **Step 5: Commit**

```bash
git add services/situations.py services/triage.py tests/test_start_mission.py config.yaml
git commit -m "feat(threads): a thread carries its mission's question or release, so 'tell the mission yes' works against the thread and the card answers it (vX.Y.Z)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

### Task 4: The thread card shows the mission's steps; the PWA House card shows the asks

**Files:**
- Modify: `templates/components/threads_page.html` (details include `components/mission_transcript.html` for the thread's missions; `releaseMission`)
- Modify: `main.py` (`GET /api/threads/{id}/missions`: the thread's missions with steps, same gate as the thread read)
- Modify: `templates/app.html` (`renderHouseThreads` `extraHtml`: the waiting question or release line with its buttons for parents/adults; nothing for a child owner)
- Test: `tests/test_browse_thread_live.py` (new)

**Interfaces:** consumes `GET /api/threads/{id}/missions` → `{missions: [{...mission, steps: [...]}]}` newest first; the card's `release`/`answer` options route through `/api/situations/thread/{id}/act` (Task 3).

- [ ] **Step 1: Write the failing live test**

```python
# tests/test_browse_thread_live.py
"""The thread card's details show the mission's steps (the shared transcript),
the release buttons work from the thread, and a child owner's House card has
the steps but no buttons."""
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='browse_thread_live_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_app import live_app
from services import storage


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def seed():
    from services import threads, missions
    storage.update_settings({'llm_gemini_api_key': '', 'missions_enabled': True, 'contact_first_name': 'Jeff'})
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent', 'color_code': '#6366f1'})
    storage.add_member({'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True, 'color_code': '#f59e0b'})
    tid = threads.create('Dishwasher repair', owner_member_id='mom', goal='get it fixed', created_by='mom')
    mid = storage.add_mission({'goal': 'get the dishwasher fixed', 'origin_kind': 'thread', 'origin_ref': tid, 'created_by': 'mom', 'tier': 'mission'})
    storage.add_mission_step(mid, {'kind': 'tool', 'name': 'search_mail', 'args_json': {'query': 'cafe'}, 'result_json': {'message': 'Found: Your Cafe order'}})
    storage.add_mission_step(mid, {'kind': 'ask', 'name': 'release', 'result_json': {'question': 'Share with bodewell.com: Jeff?', 'site': 'bodewell.com', 'fields': ['first_name'],
                                                                                     'values': {'first_name': 'Jeff'}, 'browse': {'goal': 'g', 'site': 'bodewell.com', 'start_url': 'https://bodewell.com/f'}}})
    storage.update_mission(mid, {'status': 'waiting_user'})
    kt = threads.create("Kate's science fair", owner_member_id='kid', created_by='mom')
    km = storage.add_mission({'goal': 'science fair supplies', 'origin_kind': 'thread', 'origin_ref': kt, 'created_by': 'mom', 'tier': 'mission'})
    storage.add_mission_step(km, {'kind': 'ask', 'name': 'question', 'result_json': {'question': 'Which day is it?'}})
    storage.update_mission(km, {'status': 'waiting_user'})
    missions._browse_async = False
    missions._browse = lambda **kw: {'outcome': 'done', 'text': 'ok', 'learned': {}, 'stopped_at': 'u', 'wanted_fields': [], 'turns': 1, 'tokens_in': 1, 'tokens_out': 1, 'seconds': 1, 'screenshots': [], 'filled': {}}


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        b = served.browser(color_scheme='dark')
        with b as page:
            page.set_viewport_size({'width': 1300, 'height': 900})
            page.goto(served.url('work?tab=threads'), wait_until='networkidle')
            page.wait_for_selector('#threads .situation-card', timeout=15000)
            card = page.locator('#threads .situation-card:has-text("Dishwasher repair")').first
            check(card.locator('.sit-next button').first.inner_text().startswith('Share with bodewell.com'), "the thread leads with the release")
            card.locator('xpath=following-sibling::details[1]//summary').first.click() if False else page.locator('#threads details summary').first.click()
            page.wait_for_timeout(600)
            tl = page.locator('#threads details[open]').first.inner_text()
            check('search_mail' in tl and 'Your Cafe order' in tl, f"the mission's steps are in the thread's details: {tl[:300]}")
            check('Share with bodewell.com' in tl, "the release ask is shown there too")
            card.locator('.sit-next button').first.click()
            page.wait_for_timeout(1500)
            m = [x for x in storage.get_missions() if x['goal'] == 'get the dishwasher fixed'][0]
            check(m['status'] == 'running' and m.get('releases'), f"Share from the thread card released and resumed: {m['status']}")
            check(not b.errors, f"script errors: {b.errors}")

        b = served.browser(color_scheme='dark')
        with b as page:
            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(served.url('app'), wait_until='networkidle')
            page.evaluate("localStorage.setItem('chauffeur_member_id', 'kid');")
            page.goto(served.url('app'), wait_until='networkidle')
            page.evaluate("async () => { await fetchHouseThreads(); }")
            page.wait_for_selector('#house-threads .situation-card', state='attached', timeout=15000)
            txt = page.locator('#house-threads').first.text_content()
            check('science fair' in txt and 'Which day is it?' in txt, f"the child sees the thread and Argyle's question: {txt[:200]}")
            check(page.locator('#house-threads button').count() == 0, "a child owner has no buttons")
            check(not b.errors, f"PWA script errors: {b.errors}")
    finally:
        served.stop()


if __name__ == '__main__':
    main()
    print('PASS test_browse_thread_live')
```

- [ ] **Step 2: Run to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_browse_thread_live.py`
Expected: FAIL at "the mission's steps are in the thread's details".

- [ ] **Step 3: The endpoint** — `main.py`, beside the thread endpoints:

```python
@app.get("/api/threads/{thread_id}/missions")
def thread_missions(thread_id: str, request: Request = None):
    """The missions opened from this thread, newest first, with their steps —
    the same gate as reading the thread."""
    viewer = _situation_viewer(request)
    from services import situations as _sit
    row = storage.get_thread(thread_id)
    if not row:
        raise HTTPException(status_code=404, detail="No such thread")
    if not _sit.can_see('thread', row, viewer):
        raise HTTPException(status_code=403, detail="Not yours to see")
    rows = [m for m in storage.get_missions() if m.get('origin_kind') == 'thread' and m.get('origin_ref') == thread_id]
    rows.sort(key=lambda m: -(m.get('created_at') or 0))
    for m in rows:
        m['steps'] = storage.get_mission_steps(m['id'])
    return {"missions": rows[:5]}
```

Classify it in `auth.RULES` with the thread reads.

- [ ] **Step 4: The thread page** — in `templates/components/threads_page.html`, inside the details after the history timeline:

```html
                                        <!-- The missions opened from this thread: the shared transcript, loaded on open. -->
                                        <template x-for="mission in (threadMissions[t.id] || [])" :key="mission.id">
                                            <div class="mt-2 border-t border-gray-800 pt-2">
                                                <div class="text-[11px] text-gray-500" x-text="'Mission: ' + mission.goal + ' — ' + mission.status"></div>
                                                {% include 'components/mission_transcript.html' %}
                                            </div>
                                        </template>
```

In the page script: `threadMissions: {}`, a `loadMissions(t)` that fetches `api/threads/${t.id}/missions` and stores `threadMissions[t.id] = d.missions`, called when the details open (`@toggle` on the `<details>` already sets `detailsOpen[s.id]`; call `loadMissions` there when it opens) and after any act (`load()` re-fetches for open rows). The transcript component expects `mission`, `apiBase`, `stepKindClass`, `stepArgsText`, `stepResultText`, `isLastAsk`, `releaseMission` in scope: copy `stepKindClass`/`stepArgsText`/`stepResultText` from `missions_page.html` into a shared place if they are not already shared (read both first; if the missions page defines them inline, move them to `static/mission_transcript.js` exposed as `window.MissionTranscript` and have both pages call through it, so there is one implementation). `releaseMission` on this page posts `api/missions/${m.id}/release` and then `load()`.

- [ ] **Step 5: The PWA House card** — in `templates/app.html` `renderHouseThreads`, the card's `extraHtml` already carries the note form for parents/adults. The situation card itself now draws the mission's `answer`/`release` options from the thread's options (Task 3), with `canWrite` gating the buttons, so a child owner sees the question text through the card's note/next-step label but no buttons. Confirm in the live test; if the child's card shows the question only as a button label (hidden with `canWrite=false`), add to `extraHtml` for every viewer a plain line: when `s.next_step && s.next_step.id.startsWith('answer:mission:')`, `<div class="text-xs text-amber-200 mt-1">Argyle asks: ${esc(s.next_step.label)}</div>`.

Run `..\venv\Scripts\python.exe tools\build_tailwind.py`.

- [ ] **Step 6: Run the live test and related**

Run: `..\venv\Scripts\python.exe tests\test_browse_thread_live.py` then `..\venv\Scripts\python.exe tools\test.py threads_page_live missions_page_live missions_endpoints situations_lane_live auth tailwind_build`
Expected: PASS; `test_missions_endpoints`'s "included exactly twice" contract is about `missions_page.html` only and still holds.

- [ ] **Step 7: Commit**

```bash
git add main.py services/auth.py templates/components/threads_page.html templates/app.html static/mission_transcript.js static/tailwind.css static/tailwind-app.css tests/test_browse_thread_live.py config.yaml
git commit -m "feat(threads): the thread card shows its mission's steps and answers its asks from the card; the House card shows the question (vX.Y.Z)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

### Task 5: Acceptance scenario 1 end to end, docs, memory

**Files:** `tests/test_start_mission.py` (append), `system_capabilities.md`, `docs/roadmap.md`, memory `browse-missions-arc.md`.

- [ ] **Step 1: The end-to-end scenario** (fake planner, fake runner, fake mail, stubbed vision; no network)

```python
def scenario_e2e_get_the_dishwasher_fixed():
    """Spec acceptance 1, with every outside call faked."""
    _reset(); _dm_capture()
    from services import mail_search, browse as _b
    storage.get_settings = lambda: {'missions_enabled': True, 'llm_gemini_paid_api_key': 'paid', 'llm_gemini_api_key': 'k', 'thread_stall_days': 7,
                                    'ingest_email_host': 'h', 'ingest_email_user': 'u', 'ingest_email_password': 'p',
                                    'contact_first_name': 'Jeff', 'contact_last_name': 'Wilson', 'contact_email': 'ffejnosliw@gmail.com',
                                    'contact_phone': '919-327-7497', 'contact_street': '1 Chestnut Walk', 'contact_city': 'Cary', 'contact_state': 'NC', 'contact_zip': '27519',
                                    'missions_captcha_attempts': True}
    mail_search.search = lambda q, since_days=365, limit=5, settings=None: {'status': 'success', 'hits': [{'uid': 1, 'from': 'orders@cafeappliances.com', 'date': '2021-03-14', 'subject': 'Your Cafe order', 'snippet': 'Model CDT805P2N3S1'}]}
    threads._pool_call = lambda tier, key, system, prompt, **kw: {'text': 'Serial LS758759B'}
    missions._browse_async = False
    reports = [
        {'outcome': 'needs_release', 'text': 'the form wants contact details', 'learned': {}, 'stopped_at': 'https://bodewell.com/guest-schedule-service',
         'wanted_fields': ['first_name', 'last_name', 'email', 'phone', 'street', 'city', 'state', 'zip'], 'turns': 9, 'tokens_in': 80000, 'tokens_out': 2000, 'seconds': 90, 'screenshots': [], 'filled': {}},
        {'outcome': 'captcha_failed', 'text': '3 attempts at the human-verification check failed', 'learned': {}, 'stopped_at': 'https://bodewell.com/guest-schedule-service',
         'wanted_fields': [], 'turns': 6, 'tokens_in': 50000, 'tokens_out': 1000, 'seconds': 60, 'screenshots': [], 'filled': {'first_name': 'Jeff', 'email': 'ffejnosliw@gmail.com'}},
    ]
    missions._browse = lambda **kw: reports.pop(0)
    plan = [
        {'action': 'tool', 'tool': 'search_mail', 'args': {'query': 'cafe dishwasher'}},
        {'action': 'ask_user', 'question': 'Send me a photo of the label inside the door.'},
        {'action': 'browse', 'goal': 'find appointment windows and the trip charge for a dishwasher repair', 'site': 'bodewell.com'},
        {'action': 'finish', 'summary': 'Bodewell can come Tue Oct 20, 8-noon; trip charge $114.95, parts and labor extra.',
         'next_action': 'Book Tue Oct 20, 8-noon ($114.95 trip charge)', 'next_action_at': '2026-10-17'},
    ]
    missions._llm = lambda m, s, u, st: plan.pop(0)
    # 1. voice opens it
    res = tools.start_mission_for('get the dishwasher fixed', acting_member=MOM, focus_key='voice:1')
    mid, tid = res['mission_id'], res['thread_id']
    # 2. the mail is found, the photo asked for
    missions.step(storage.get_mission(mid)); missions.step(storage.get_mission(mid))
    check(storage.get_mission(mid)['status'] == 'waiting_user' and 'photo' in SENT[-1].lower(), "asks for the photo")
    threads.add_photo(tid, b'\x89PNG', 'image/png', 'mom')
    check(storage.get_mission(mid)['status'] == 'running', "the photo answers it")
    # 3. the browse stops for the release; the parent approves from the thread
    missions.step(storage.get_mission(mid))
    check(storage.get_mission(mid)['status'] == 'waiting_user' and 'bodewell.com' in SENT[-1] and 'Jeff' in SENT[-1], "the release card")
    out = situations.act('thread', tid, 'release', option_id=f'release:mission:{mid}:approve', actor=MOM)
    check(out['status'] == 'success', f"approved: {out}")
    # 4. the resumed browse fails the CAPTCHA → hand-off
    m = storage.get_mission(mid)
    check(m['status'] == 'waiting_user' and 'bodewell.com' in SENT[-1] and 'first_name=Jeff' in SENT[-1] and 'tell me what you found' in SENT[-1].lower(), f"the hand-off: {SENT[-1]}")
    # 5. the person answers in words; the mission finishes
    out = tools.act_on_situation(verb='answer', text='Tue 20th 8-noon, $114.95 trip charge', acting_member=MOM, focus_key='voice:1')
    check(out['status'] == 'success', f"answered: {out}")
    missions.step(storage.get_mission(mid))
    m = storage.get_mission(mid)
    t = storage.get_thread(tid)
    check(m['status'] == 'done' and t['next_action'].startswith('Book Tue') and '$114.95' in SENT[-1] and 'Nothing is booked' in SENT[-1], f"finished: {m['status']} / {t['next_action']} / {SENT[-1]}")
    check(not storage.get_action_proposals() if hasattr(storage, 'get_action_proposals') else True, "nothing proposed, nothing booked")


SCENARIOS += [scenario_e2e_get_the_dishwasher_fixed]
```

Drop the last `hasattr` line if `storage` has no such accessor; the assertion that matters is the status, the next step and the DM.

- [ ] **Step 2: Run it**

Run: `..\venv\Scripts\python.exe tests\test_start_mission.py`
Expected: `12/12`. A failure here is a defect in an earlier task; fix it there.

- [ ] **Step 3: Docs and memory**

`system_capabilities.md`: bump "Current through" and add the build-3 entry in house style: `start_mission_for` (thread + mission + focus, dedupe, voice as the parent of record), DMs on ask/release/hand-off/finish, the finish's `mission` history entry and pre-filled `advance:mission` lead (tier 1), the thread's `answer:mission:*`/`release:mission:*` options routing to the mission (tier 0 while waiting), `GET /api/threads/{id}/missions`, the transcript in the thread's details and `static/mission_transcript.js` if created, the House card's question line, "Nothing is booked" on every finish that browsed, "Not device-verified". `docs/roadmap.md`: one line. Memory `browse-missions-arc.md`: all three builds shipped, versions, NOT device-verified; remote hand still a later arc.

- [ ] **Step 4: Run the gate**

Run: `..\venv\Scripts\python.exe tools\test.py start_mission browse missions triage situation threads agent_v2_bridge tailwind_build`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add tests/test_start_mission.py system_capabilities.md docs/roadmap.md config.yaml
git commit -m "docs(missions): browse missions build 3 wrap-up - the end-to-end dishwasher scenario, capabilities, roadmap (vX.Y.Z)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

## Self-review notes

- **Spec coverage (§4):** the tool and its reply (T1); the mission's reach is builds 1–2; DMs on every ask with the answer path (T2, build 2 for release/hand-off); the finish as note + pre-filled advance + DM, nothing booked (T2); triage tiers (T2, T3). §5 surfaces: the thread card's steps and buttons, the House card (T4); the acceptance scenario (T5).
- **Type consistency:** option ids `answer:mission:<mid>`, `release:mission:<mid>:<decision>` are produced in T3 and consumed by the card and T4's live test; `_land_finish` writes `kind: 'mission'` entries with `next_action` read by `_reply_option` (T2) and `triage.REPLY_LEADS`.
- **Review Focus** 1–5 pinned in T1, T3, T2 (two), T4.

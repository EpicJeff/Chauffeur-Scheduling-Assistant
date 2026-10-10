# Triage and replies — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "What needs my attention?" answers with one spoken situation held as the conversation's focus, voice acts as the parent of record, and a vendor's reply on a thread is read once, recorded on the ask ledger, and never applied.

**Architecture:** A new `services/triage.py` owns the cross-kind rank, the spoken sentence and the per-conversation focus (one app-state map keyed by conversation key). The six situation tools gain an optional reference that falls back to focus; the router hands each tool a `focus_key` and, when the caller has no identity, the household's parent of record. A new `services/replies.py` runs inside the ingest poll after `threads.match_inbound`: one Lite reading per `message_id`, stored on the history entry; `asks.record_reading` moves the ask, `_options_thread` turns the reading into the highlighted next step, one DM to the owner honours the watcher's quiet hours, and the new verb `unread` reverts a reading on the card and in conversation.

**Tech Stack:** as builds 1 and 2 (FastAPI, TinyDB-over-SQLite, Alpine + vanilla JS, precompiled Tailwind, standalone scenario test scripts, `live_app` + playwright for live tests, `model_pools.call_pool_json` for the one Lite call).

**Spec:** `docs/superpowers/specs/2026-10-10-triage-and-replies-design.md`. Sub-project 2 shipped v2.499.303–.321; its spec `docs/superpowers/specs/2026-10-09-situations-design.md` defines the situation shape, the ask ledger and the verb set this plan extends.

## Global Constraints

- Run from `E:\repositories\Chauffeur\chauffeur` with `..\venv\Scripts\python.exe`; tests with `HA_BASE_URL` unset.
- Gate for this build: `python tools/test.py triage reply situation threads email_ingest agent_v2_bridge watchers mind_endpoints tailwind_build` plus the live test of Task 11. Never the full sweep.
- Voice acts as the parent of record: the substitution happens ONLY in the router's dispatch branch for the situation tools, never inside a tool, never on `propose_only`, never in driver mode.
- A substituted actor is a room: `list_situations` and `next_situation` drop sensitive insights when the actor was substituted; `next_situation` drops them always.
- No new LLM calls on reads, ticks or sweeps. `next_situation`, focus and the unread verb make none. `replies.read` runs only inside `email_ingest._match_thread`, once per `message_id`, under `reply_cap_reads` (default 40/day).
- The closed verb set grows by exactly one verb, `unread`, declared in `situations.VERBS`, `VERB_LABELS` in `static/situations.js` and the `act_on_situation` enum, so `test_situation_tools.scenario_parity_both_ways` keeps passing.
- `tests/test_agent_v2_bridge.py` pins the registry only grows: `next_situation` is added to `TOOL_SCHEMAS` and `TOOL_HANDLERS` and `get_available_tools`; nothing is removed.
- A reading never applies anything: `asks.apply` is never called from `services/replies.py` (a source test pins it, with the DM-reader boundary: `replies.py` never names `get_channel_messages`).
- `python tools/build_tailwind.py` after any template class change; `tests/test_tailwind_build.py` must pass.
- Every commit bumps `config.yaml` (`2.499.327` onward, +1 per commit; v2.499.325 is the spec commit, v2.499.326 the plan commit), message ends `(vX.Y.Z)`, push. Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Persisted prose (code comments, docs, commit messages) is normal English.

## Review Focus

1. **A focus whose situation closed between turns** ("next" after someone else handled it on the dashboard): the FOCUS line must not be injected and ref-less tools must refuse with the way out, never act on a dead row. Pinned in Task 2 (`scenario_focus_on_a_closed_situation_is_dropped`).
2. **A voice turn with no `conversation_id`**: `next_situation` still answers and ends with the title; no focus is written under a `None` key. Pinned in Task 4 (`scenario_voice_without_a_conversation_has_no_focus`).
3. **Two live asks on the focused situation** and "she said yes": the tool refuses and names both; nothing is answered. Pinned in Task 3 (`scenario_ref_less_answer_with_two_live_asks_refuses`).
4. **A reply arriving at 23:00** (outside the watcher window): the reading and the ask state land at once; the DM is deferred and posted exactly once by the next in-window sweep; a second sweep posts nothing. Pinned in Task 8 (`scenario_dm_outside_quiet_hours_is_deferred_once`).
5. **A reading of `yes` on an ask a person already answered** (the owner tapped "said no" before the poll ran): the ask is untouched, the reading still lands on the history. Pinned in Task 7 (`scenario_reading_never_overwrites_a_human_answer`).

---

### Task 1: `services/triage.py` — rank across kinds and the spoken sentence

**Files:**
- Create: `services/triage.py`
- Modify: `services/situations.py` (`list_situations` gains `spoken`)
- Test: `tests/test_triage.py` (new)

**Interfaces:**
- Consumes: `situations.list_situations(viewer, kinds=None, include_done=False, owner=None)`, `situations.view`, `threads.is_stalled`.
- Produces:
  - `situations.list_situations(viewer, kinds=None, include_done=False, owner=None, spoken=False) -> list` — `spoken=True` drops insights with `sensitivity == 'sensitive'`.
  - `triage.triage_rank(rows: list[dict]) -> list[dict]` — tiers 0–4 as the spec's table.
  - `triage.tier(s: dict) -> int`.
  - `triage.spoken(s: dict) -> str` — one sentence, deterministic.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_triage.py
"""Sub-project 3: one rank across the four kinds, one spoken sentence, focus
held per conversation, voice as the parent of record. Spec:
docs/superpowers/specs/2026-10-10-triage-and-replies-design.md §1."""
import datetime
import time

from harness import check  # noqa: F401
from services import storage, situations, triage, threads

NOON = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}


def _reset():
    for t in (storage.asks_table, storage.findings_table, storage.mind_insights_table, storage.members_table,
              storage.cache_table, storage.app_state_table, storage.threads_table, storage.missions_table,
              storage.mission_steps_table, storage.assist_contacts_table, storage.chat_channels_table,
              storage.chat_messages_table, storage.conversations_table):
        t.truncate()
    storage.get_settings = lambda: {'calendar_ids': ['primary'], 'thread_stall_days': 7}
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True})
    situations.REFRESH_DELAY_S = 0
    situations._pool_call = lambda *a, **k: {}


def _finding(line, severity, due_in_hours, fid):
    due = (NOON + datetime.timedelta(hours=due_in_hours))
    return storage.add_finding({'identity': f'unassigned:{fid}', 'kind': 'unassigned', 'severity': severity,
                                'line': line, 'subject_type': 'event', 'subject_id': fid,
                                'due_at': due.timestamp(), 'state': 'open'})


def scenario_rank_tiers_across_four_kinds():
    _reset()
    _finding('No driver: soccer today', 'decide', 6, 'ev-soon')          # tier 0: due within 24h
    _finding('No driver: recital next week', 'decide', 24 * 6, 'ev-late')  # tier 1
    _finding('Approve the swap', 'approve', 24 * 2, 'ev-appr')             # tier 2
    _finding('FYI: bus late', 'fyi', 24 * 2, 'ev-fyi')                     # tier 4
    storage.add_mind_insight({'slug': 'i', 'line': 'Thursday is tight', 'category': 'c', 'approach': 'ask Sarah',
                              'identity': 'c:1', 'confidence': 0.8})      # tier 3
    overdue = threads.create('Pest control', owner_member_id='mom', next_action='call back',
                             next_action_at=(NOON - datetime.timedelta(days=1)).date().isoformat(), created_by='mom')  # tier 0
    quiet = threads.create('Gutters', owner_member_id='mom', created_by='mom')
    storage.update_thread(quiet, {'created_at': time.time() - 9 * 86400})                                              # tier 1 (quiet)
    mid = storage.add_mission({'goal': 'Find a sitter', 'status': 'waiting_user', 'created_by': 'mom'})                # tier 0
    rows = situations.list_situations(MOM)
    ranked = triage.triage_rank(rows)
    titles = [s['title'] for s in ranked]
    tiers = [triage.tier(s) for s in ranked]
    check(tiers == sorted(tiers), f"tiers are non-decreasing: {list(zip(titles, tiers))}")
    check(set(titles[:3]) == {'No driver: soccer today', 'Pest control', 'Find a sitter'},
          f"tier 0 is the due-today ride, the overdue thread and the waiting mission: {titles[:3]}")
    check(titles.index('No driver: recital next week') < titles.index('Approve the swap') < titles.index('Thursday is tight')
          < titles.index('FYI: bus late'), f"decide, then approve, then insight, then fyi: {titles}")
    check(titles.index('Gutters') < titles.index('Approve the swap'), "a quiet thread outranks an approve finding")


def scenario_spoken_sentence_per_kind():
    _reset()
    storage.add_assist_contact({'id': 'c1', 'name': 'Sarah', 'kinds': ['driving'], 'active': True})
    fid = _finding('No driver yet: Soccer Thu 4:00', 'decide', 30, 'ev1')
    s = situations.view('finding', fid, MOM)
    line = triage.spoken(s)
    check(line.startswith('No driver yet: Soccer Thu 4:00.') and 'Next: ' in line, f"title then next step: {line}")
    storage.update_finding(fid, {'status_note': 'Mike was asked and said no.', 'note_source': 'argyle',
                                 'note_rev': storage.get_finding(fid).get('rev') or 0})
    s = situations.view('finding', fid, MOM)
    check('Mike was asked and said no.' in triage.spoken(s), "Argyle's note is spoken when it is hers")
    storage.update_finding(fid, {'note_source': 'fallback'})
    s = situations.view('finding', fid, MOM)
    check('Mike was asked' not in triage.spoken(s), "a fallback note is never spoken as hers")
    from services import asks
    asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, 'drive Kate Thursday', 'text', 'mom', draft_mode='template')
    s = situations.view('finding', fid, MOM)
    check('asked Sarah by text' in triage.spoken(s) and 'not sent yet' in triage.spoken(s), f"the ask clause: {triage.spoken(s)}")
    tid = threads.create('Pest control', owner_member_id='mom', created_by='mom')
    s = situations.view('thread', tid, MOM)
    check(triage.spoken(s).startswith('Pest control.'), f"a thread speaks its title: {triage.spoken(s)}")
    check(triage.spoken(s).endswith('.'), "a sentence ends with a full stop")


def scenario_spoken_list_never_holds_a_sensitive_insight():
    _reset()
    storage.add_mind_insight({'slug': 'n', 'line': 'normal', 'category': 'c', 'approach': 'x', 'identity': 'c:1'})
    storage.add_mind_insight({'slug': 's', 'line': 'SECRET', 'category': 'c', 'approach': 'x', 'identity': 'c:2',
                              'sensitivity': 'sensitive'})
    plain = [s['title'] for s in situations.list_situations(MOM)]
    check('SECRET' in plain, "a parent's ordinary list holds the sensitive row")
    spoken = [s['title'] for s in situations.list_situations(MOM, spoken=True)]
    check('SECRET' not in spoken and 'normal' in spoken, f"a spoken list never does: {spoken}")


SCENARIOS = [scenario_rank_tiers_across_four_kinds, scenario_spoken_sentence_per_kind,
             scenario_spoken_list_never_holds_a_sensitive_insight]

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

- [ ] **Step 2: Run it to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_triage.py`
Expected: `ImportError: cannot import name 'triage'`.

- [ ] **Step 3: Add `spoken` to `situations.list_situations`**

In `services/situations.py`, replace the `list_situations` function:

```python
def list_situations(viewer: Optional[dict], kinds=None, include_done: bool = False,
                    owner: str = None, spoken: bool = False) -> list:
    """`owner` narrows THREADS to one member's own (the PWA House tab's
    view); the other kinds have no owner and are unaffected. `spoken` is a
    room, not a hand: a sensitive insight is never read aloud, whatever the
    viewer's role (spec 2026-10-10 §1)."""
    out = []
    for kind in (kinds or KINDS):
        for k, sid in _rows_of(kind, include_done):
            row = load(k, sid)
            if not row or not can_see(k, row, viewer):
                continue
            if owner and k == 'thread' and row.get('owner_member_id') != owner:
                continue
            if spoken and k == 'insight' and row.get('sensitivity') == 'sensitive':
                continue
            s = view(k, sid, viewer)
            if s and (include_done or s['group'] != 'done'):
                out.append(s)
    return rank(out)
```

- [ ] **Step 4: Create `services/triage.py` with the rank and the sentence**

```python
"""Triage — the one thing that needs a person, spoken, and held as the
conversation's focus. Spec: docs/superpowers/specs/2026-10-10-triage-and-replies-design.md §1.

`situations.rank` orders the lanes for the eye; `triage_rank` orders for the
ear: what somebody should hear first. Focus is one app-state map keyed by
conversation key, pruned on every write, so "handle it" after "what needs
my attention" needs no title.

Boundaries (same as situations.py): never import a DM accessor, never read
gift records. Nothing here calls a model.
"""
import datetime
import time
from typing import Optional

from services import storage, situations

FOCUS_KEY = 'triage_focus'
FOCUS_TTL_S = 24 * 3600
DAY_S = 24 * 3600


# --- rank ----------------------------------------------------------------------

def _due_ts(s: dict) -> Optional[float]:
    due = s.get('due')
    if due is None or due == '':
        return None
    if isinstance(due, (int, float)):
        return float(due)
    try:
        return datetime.datetime.fromisoformat(str(due)).timestamp()
    except (TypeError, ValueError):
        return None


def tier(s: dict, now: float = None) -> int:
    """0 overdue or due within 24h; 1 decide findings, stalled threads,
    missions with a pending proposal; 2 approve findings; 3 insights;
    4 fyi and everything else."""
    now = now or time.time()
    kind, state = s.get('kind'), s.get('state')
    due = _due_ts(s)
    if kind == 'finding':
        sev = s.get('severity')
        if sev == 'decide':
            return 0 if due is not None and due - now <= DAY_S else 1
        if sev == 'approve':
            return 2
        return 4
    if kind == 'thread':
        if due is not None and due < now:
            return 0
        return 1 if s.get('needs_attention') else 4
    if kind == 'mission':
        if state == 'waiting_user':
            return 0
        return 1 if s.get('needs_attention') else 4
    if kind == 'insight':
        return 3
    return 4


def triage_rank(rows: list, now: float = None) -> list:
    now = now or time.time()

    def key(s):
        t = tier(s, now)
        due = _due_ts(s)
        if s.get('kind') == 'insight':
            return (t, -(s.get('confidence') or 0), s.get('since') or 0)
        if s.get('kind') == 'thread' and t == 1:
            return (t, 0, s.get('since') or 0)          # stalled longest first (oldest since)
        return (t, due if due is not None else float('inf'), s.get('since') or 0)
    return sorted(rows, key=key)


# --- the sentence --------------------------------------------------------------

def _ask_clause(asks: list) -> str:
    live = [a for a in asks if a.get('state') != 'withdrawn'][-3:]
    parts = []
    for a in live:
        state = a.get('state')
        words = {'drafted': 'not sent yet', 'sent': 'waiting', 'yes': 'said yes', 'no': 'said no',
                 'expired': 'no answer'}.get(state, state or '')
        parts.append(f"asked {a.get('to_name')} by {a.get('channel')}, {words}")
    return '; '.join(parts)


def spoken(s: dict) -> str:
    """One or two sentences, built from the situation's own facts. No model."""
    title = (s.get('title') or '').strip().rstrip('.')
    out = f"{title}."
    if s.get('note_source') == 'argyle' and (s.get('status_note') or '').strip():
        note = s['status_note'].strip()
        out += f" {note}" + ('' if note.endswith(('.', '!', '?')) else '.')
    nxt = (s.get('next_step') or {}).get('label')
    if nxt:
        clause = _ask_clause(s.get('asks') or [])
        out += f" Next: {nxt}" + (f" — {clause}" if clause else '') + '.'
    return out
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `..\venv\Scripts\python.exe tests\test_triage.py`
Expected: `3/3 scenarios passed`. If `scenario_rank_tiers_across_four_kinds` fails on the mission row, check `storage.add_mission` accepts a plain dict with `goal`/`status` (see `tests/test_situations.py::scenario_thread_and_mission_views` for the shape used there and mirror it).

- [ ] **Step 6: Run the related tests**

Run: `..\venv\Scripts\python.exe tools\test.py situation`
Expected: all green (the `spoken` default is `False`, so the lanes are unchanged).

- [ ] **Step 7: Commit**

Bump `config.yaml` to `2.499.327`.

```bash
git add services/triage.py services/situations.py tests/test_triage.py config.yaml
git commit -m "feat(triage): one rank across the four kinds, the spoken sentence, and a spoken list that never holds a sensitive insight (v2.499.327)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

### Task 2: Focus — set, read, clear, cursor

**Files:**
- Modify: `services/triage.py`
- Test: `tests/test_triage.py`

**Interfaces:**
- Produces:
  - `triage.get_focus(key: str) -> Optional[dict]` — `{kind, id, title, cursor, set_at}` or None; drops (and deletes) a focus whose situation is gone, done, or snoozed.
  - `triage.set_focus(key, kind, sid, title, cursor=0) -> dict`.
  - `triage.clear_focus(key) -> None`.
  - `triage.next_for(viewer, key, skip_current=False) -> Optional[dict]` — the situation to speak, after setting focus; None when the list is exhausted or empty (focus cleared).
  - `triage.focus_live_asks(key, viewer) -> list` — the focus situation's `drafted`/`sent` asks.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_triage.py` before the `if __name__` block)

```python
def scenario_focus_set_read_and_cursor():
    _reset()
    a = threads.create('Pest control', owner_member_id='mom', next_action='call back',
                       next_action_at=(NOON - datetime.timedelta(days=1)).date().isoformat(), created_by='mom')
    b = threads.create('Gutters', owner_member_id='mom', created_by='mom')
    storage.update_thread(b, {'created_at': time.time() - 9 * 86400})
    check(triage.get_focus('conv:1') is None, "no focus to begin with")
    first = triage.next_for(MOM, 'conv:1')
    check(first and first['id'] == a, f"the overdue thread comes first: {first and first['title']}")
    f = triage.get_focus('conv:1')
    check(f and f['kind'] == 'thread' and f['id'] == a and f['cursor'] == 0, f"focus is the first one: {f}")
    second = triage.next_for(MOM, 'conv:1', skip_current=True)
    check(second and second['id'] == b, f"'next' moves down the list: {second and second['title']}")
    check(triage.get_focus('conv:1')['cursor'] == 1, "the cursor advanced")
    third = triage.next_for(MOM, 'conv:1', skip_current=True)
    check(third is None and triage.get_focus('conv:1') is None, "the end of the list clears the focus")
    check(triage.get_focus('conv:other') is None, "another conversation has its own focus")


def scenario_focus_on_a_closed_situation_is_dropped():
    _reset()
    a = threads.create('Pest control', owner_member_id='mom', next_action='call back',
                       next_action_at=(NOON - datetime.timedelta(days=1)).date().isoformat(), created_by='mom')
    triage.next_for(MOM, 'conv:1')
    threads.close(a, 'done', who='mom')
    check(triage.get_focus('conv:1') is None, "a focus whose situation closed is gone")
    fid = _finding('No driver: soccer', 'decide', 6, 'ev1')
    triage.set_focus('conv:2', 'finding', fid, 'No driver: soccer')
    storage.update_finding(fid, {'snoozed_until': time.time() + 7 * 86400})
    check(triage.get_focus('conv:2') is None, "a snoozed focus is gone too")


def scenario_focus_entries_are_pruned_after_a_day():
    _reset()
    a = threads.create('Pest control', owner_member_id='mom', created_by='mom')
    triage.set_focus('conv:old', 'thread', a, 'Pest control')
    m = dict(storage.get_app_state(triage.FOCUS_KEY) or {})
    m['conv:old']['set_at'] = time.time() - 2 * 86400
    storage.set_app_state(triage.FOCUS_KEY, m)
    triage.set_focus('conv:new', 'thread', a, 'Pest control')
    m = storage.get_app_state(triage.FOCUS_KEY) or {}
    check('conv:old' not in m and 'conv:new' in m, f"a day-old focus is pruned on the next write: {list(m)}")
    check(triage.get_focus(None) is None, "no key, no focus")
    triage.set_focus(None, 'thread', a, 'Pest control')
    check(None not in (storage.get_app_state(triage.FOCUS_KEY) or {}), "nothing is written under no key")


SCENARIOS += [scenario_focus_set_read_and_cursor, scenario_focus_on_a_closed_situation_is_dropped,
              scenario_focus_entries_are_pruned_after_a_day]
```

- [ ] **Step 2: Run to verify they fail**

Run: `..\venv\Scripts\python.exe tests\test_triage.py`
Expected: FAIL with `AttributeError: module 'services.triage' has no attribute 'get_focus'`.

- [ ] **Step 3: Add focus to `services/triage.py`** (append)

```python
# --- focus ---------------------------------------------------------------------

def _load_map() -> dict:
    return dict(storage.get_app_state(FOCUS_KEY) or {})


def _prune(m: dict, now: float) -> dict:
    return {k: v for k, v in m.items() if isinstance(v, dict) and (v.get('set_at') or 0) >= now - FOCUS_TTL_S}


def set_focus(key: Optional[str], kind: str, sid: str, title: str, cursor: int = 0) -> Optional[dict]:
    if not key:
        return None
    now = time.time()
    f = {'kind': kind, 'id': sid, 'title': title or '', 'cursor': int(cursor or 0), 'set_at': now}
    with storage.db_lock:
        m = _prune(_load_map(), now)
        m[key] = f
        storage.set_app_state(FOCUS_KEY, m)
    return f


def clear_focus(key: Optional[str]) -> None:
    if not key:
        return
    with storage.db_lock:
        m = _load_map()
        if key in m:
            del m[key]
            storage.set_app_state(FOCUS_KEY, m)


def _alive(f: dict) -> bool:
    row = situations.load(f.get('kind'), f.get('id'))
    if not row:
        return False
    if (row.get('snoozed_until') or 0) > time.time():
        return False
    opts = situations.options_for(f['kind'], row)
    return not (situations._is_done(f['kind'], row) and not situations.needs_attention(f['kind'], row, opts))


def get_focus(key: Optional[str]) -> Optional[dict]:
    """The conversation's current situation, or None. A focus whose
    situation is gone, settled or snoozed is dropped here, so a follow-up
    can never act on a dead row."""
    if not key:
        return None
    f = _load_map().get(key)
    if not f:
        return None
    if (f.get('set_at') or 0) < time.time() - FOCUS_TTL_S or not _alive(f):
        clear_focus(key)
        return None
    return f


def next_for(viewer: Optional[dict], key: Optional[str], skip_current: bool = False) -> Optional[dict]:
    """The situation to speak now. The first on the ranked list, or the one
    after the focus when `skip_current`. Sets focus and cursor; clears the
    focus and returns None when the list is exhausted."""
    ranked = triage_rank(situations.list_situations(viewer, spoken=True))
    if not ranked:
        clear_focus(key)
        return None
    idx = 0
    if skip_current:
        f = get_focus(key)
        if f:
            pos = next((i for i, s in enumerate(ranked) if s['kind'] == f['kind'] and s['id'] == f['id']), None)
            idx = (pos + 1) if pos is not None else int(f.get('cursor') or 0) + 1
    if idx >= len(ranked):
        clear_focus(key)
        return None
    s = ranked[idx]
    set_focus(key, s['kind'], s['id'], s.get('title') or '', cursor=idx)
    return s


def focus_live_asks(key: Optional[str], viewer: Optional[dict]) -> list:
    f = get_focus(key)
    if not f:
        return []
    s = situations.view(f['kind'], f['id'], viewer)
    return [a for a in (s or {}).get('asks') or [] if a.get('state') in ('drafted', 'sent')]
```

- [ ] **Step 4: Run to verify they pass**

Run: `..\venv\Scripts\python.exe tests\test_triage.py`
Expected: `6/6 scenarios passed`.

- [ ] **Step 5: Commit**

Bump `config.yaml` to `2.499.328`.

```bash
git add services/triage.py tests/test_triage.py config.yaml
git commit -m "feat(triage): focus held per conversation key, cursor for 'next', dropped when the situation settles (v2.499.328)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

### Task 3: The tools — `next_situation`, focus-aware references, the registry

**Files:**
- Modify: `services/agent_tools_v2.py` (`_resolve_situation`, the six tool functions, `get_available_tools` schemas near line 4247, the Pydantic models near line 5769, `TOOL_SCHEMAS` near line 6280, handlers near line 7453, `TOOL_HANDLERS` near line 7821)
- Modify: `services/situations.py` (`parent_of_record`)
- Test: `tests/test_triage.py`, `tests/test_situation_tools.py`

**Interfaces:**
- Consumes: `triage.get_focus/set_focus/next_for/focus_live_asks/spoken`.
- Produces:
  - `situations.parent_of_record() -> Optional[dict]` — first non-system member with role `parent`, else None.
  - `agent_tools_v2.next_situation(skip_current: bool = False, acting_member=None, focus_key=None) -> dict` with `message` (the sentence), `situation` (the view or None), `focus` (the focus dict or None).
  - `explain_situation(ref: str = '', kind=None, acting_member=None, focus_key=None)`, `act_on_situation(ref: str = '', verb: str = '', option_id=None, kind=None, text=None, next_action_at=None, acting_member=None, focus_key=None)`, `start_ask(ref: str = '', to_name='', what='', channel='', kind=None, acting_member=None, focus_key=None)`, `mark_ask_sent(ask_id: str = None, acting_member=None, focus_key=None)`, `answer_ask(ask_id: str = None, answer: str = None, acting_member=None, focus_key=None)`, `list_situations(kinds=None, limit=10, acting_member=None, spoken: bool = False)`.
  - Registry: `NextSituationTool`, `handle_next_situation`, `"next_situation"` in `TOOL_SCHEMAS`/`TOOL_HANDLERS`/`get_available_tools`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_triage.py`)

```python
from services import agent_tools_v2 as tools  # noqa: E402


def scenario_next_situation_speaks_one_and_sets_focus():
    _reset()
    a = threads.create('Pest control', owner_member_id='mom', next_action='call back',
                       next_action_at=(NOON - datetime.timedelta(days=1)).date().isoformat(), created_by='mom')
    res = tools.next_situation(acting_member=MOM, focus_key='conv:1')
    check(res['status'] == 'success' and res['message'].startswith('Pest control.') and 'Next: ' in res['message'],
          f"one sentence: {res}")
    check(triage.get_focus('conv:1')['id'] == a, "focus is set")
    res = tools.next_situation(skip_current=True, acting_member=MOM, focus_key='conv:1')
    check(res['status'] == 'success' and 'Nothing else' in res['message'], f"the end of the list says so: {res}")
    storage.threads_table.truncate()
    res = tools.next_situation(acting_member=MOM, focus_key='conv:9')
    check(res['message'] == 'Nothing needs anyone right now.', f"empty: {res}")


def scenario_ref_less_tools_use_the_focus():
    _reset()
    tid = threads.create('Deck permit', owner_member_id='mom', next_action='call', created_by='mom')
    storage.update_thread(tid, {'created_at': time.time() - 9 * 86400})
    res = tools.explain_situation(acting_member=MOM, focus_key='conv:1')
    check(res['status'] == 'error' and 'what needs your attention' in res['message'], f"no focus: the way out: {res}")
    tools.next_situation(acting_member=MOM, focus_key='conv:1')
    res = tools.explain_situation(acting_member=MOM, focus_key='conv:1')
    check(res['status'] == 'success' and res['situation']['id'] == tid, f"ref-less explain is the focus: {res}")
    res = tools.act_on_situation(verb='advance', text='email the inspector', next_action_at='2026-10-20',
                                 acting_member=MOM, focus_key='conv:1')
    check(res['status'] == 'success' and storage.get_thread(tid)['next_action'] == 'email the inspector', f"ref-less act: {res}")
    res = tools.start_ask(to_name='the inspector', what='come Friday', channel='email', acting_member=MOM, focus_key='conv:1')
    check(res['status'] == 'success' and res['ask_id'], f"ref-less ask: {res}")
    res = tools.mark_ask_sent(acting_member=MOM, focus_key='conv:1')
    check(res['status'] == 'success' and storage.get_ask(res['ask']['id'])['state'] == 'sent', f"ref-less sent: {res}")
    res = tools.answer_ask(answer='yes', acting_member=MOM, focus_key='conv:1')
    check(res['status'] == 'success' and res.get('outcome') == 'manual', f"ref-less yes: {res}")
    other = threads.create('Gutters', owner_member_id='mom', created_by='mom')
    tools.explain_situation('Gutters', acting_member=MOM, focus_key='conv:1')
    check(triage.get_focus('conv:1')['id'] == other, "naming a situation makes it the focus")


def scenario_ref_less_answer_with_two_live_asks_refuses():
    _reset()
    tid = threads.create('Deck permit', owner_member_id='mom', created_by='mom')
    triage.set_focus('conv:1', 'thread', tid, 'Deck permit')
    tools.start_ask(to_name='Sarah', what='come Friday', channel='text', acting_member=MOM, focus_key='conv:1')
    tools.start_ask(to_name='Mike', what='come Friday', channel='email', acting_member=MOM, focus_key='conv:1')
    res = tools.answer_ask(answer='yes', acting_member=MOM, focus_key='conv:1')
    check(res['status'] == 'error' and 'Sarah' in res['message'] and 'Mike' in res['message'], f"two live asks: which? {res}")
    check(all(a['state'] == 'drafted' for a in storage.get_asks(situation_kind='thread', situation_id=tid)), "nothing answered")
    res = tools.answer_ask(answer='yes', acting_member=MOM, focus_key='conv:none')
    check(res['status'] == 'error', "no focus, no ask: refused plainly")


def scenario_next_situation_is_declared_and_terminal():
    decl = {t['name']: t for t in tools.get_available_tools()}
    check('next_situation' in decl, "declared to the model")
    check('next_situation' in tools.TOOL_HANDLERS and 'next_situation' in tools.TOOL_SCHEMAS, "in the registry")
    from services import agent_router
    src = open('services/agent_router.py', encoding='utf-8').read()
    check('"next_situation"' in src.split('TERMINAL_ACTION_TOOLS = {')[1].split('}')[0], "terminal: no concluding round")
    check('next_situation' in agent_router.PROPOSE_ONLY_READS and 'list_situations' in agent_router.PROPOSE_ONLY_READS,
          "a read on the propose-only rail")
    verb_enum = decl['act_on_situation']['parameters']['properties']['verb']['enum']
    check('unread' not in verb_enum or 'unread' in situations.VERBS, "the enum never names a verb the server lacks")


SCENARIOS += [scenario_next_situation_speaks_one_and_sets_focus, scenario_ref_less_tools_use_the_focus,
              scenario_ref_less_answer_with_two_live_asks_refuses, scenario_next_situation_is_declared_and_terminal]
```

Also extend `tests/test_situation_tools.py`: change `SIX` to include the new tool, so the parity walk covers it:

```python
SIX = ('list_situations', 'explain_situation', 'act_on_situation', 'start_ask', 'mark_ask_sent', 'answer_ask',
       'next_situation')
```

- [ ] **Step 2: Run to verify they fail**

Run: `..\venv\Scripts\python.exe tests\test_triage.py`
Expected: FAIL at `scenario_next_situation_speaks_one_and_sets_focus` with `AttributeError: ... no attribute 'next_situation'`.

- [ ] **Step 3: Add `parent_of_record` to `services/situations.py`** (after `_can_write`)

```python
def parent_of_record() -> Optional[dict]:
    """Who a surface with no person acts as: the household's first parent.
    main._approver_of_record and the router's voice path both nominate this
    one member, so an ask from a satellite is asked by somebody real."""
    return next((m for m in storage.get_all_members()
                 if m.get('role') == 'parent' and not m.get('system')), None)
```

- [ ] **Step 4: Rewrite the situation tools in `services/agent_tools_v2.py`**

Replace `_resolve_situation` and the six functions (the block from `def _resolve_situation` through the end of `answer_ask`) with:

```python
NO_FOCUS = "Which one? Ask me what needs your attention first, or name it."


def _resolve_situation(ref: str, kind: str = None, viewer: dict = None, focus_key: str = None):
    """An id, a title fragment, or — with no ref — the conversation's focus.
    Naming one makes it the focus. Never guesses between candidates."""
    from services import situations as _sit, triage as _tri
    ref = (ref or '').strip()
    if not ref:
        f = _tri.get_focus(focus_key)
        if not f:
            return None, NO_FOCUS
        row = _sit.load(f['kind'], f['id'])
        if not row or not _sit.can_see(f['kind'], row, viewer):
            return None, NO_FOCUS
        return (f['kind'], f['id']), None
    found = None
    for k in ([kind] if kind in _sit.KINDS else _sit.KINDS):
        row = _sit.load(k, ref)
        if row:
            if not _sit.can_see(k, row, viewer):
                return None, "That one is not yours to see."
            found = (k, ref)
            break
    if not found:
        rows = _sit.list_situations(viewer, kinds=(kind,) if kind in _sit.KINDS else None)
        hits = [s for s in rows if ref.lower() in (s.get('title') or '').lower()]
        if len(hits) == 1:
            found = (hits[0]['kind'], hits[0]['id'])
        elif not hits:
            return None, f"Nothing open matches '{ref}'."
        else:
            names = '; '.join(h['title'] for h in hits[:5])
            return None, f"Which one: {names}?"
    row = _sit.load(found[0], found[1]) or {}
    title = {'finding': row.get('line'), 'insight': row.get('line'),
             'thread': row.get('title'), 'mission': row.get('goal')}.get(found[0]) or ''
    _tri.set_focus(focus_key, found[0], found[1], title)
    return found, None


def list_situations(kinds: str = None, limit: int = 10, acting_member: dict = None,
                    spoken: bool = False) -> Dict[str, Any]:
    from services import situations as _sit
    want = tuple(k for k in (kinds or '').split(',') if k in _sit.KINDS) or None
    rows = _sit.list_situations(acting_member, kinds=want, spoken=spoken)[:max(1, min(int(limit or 10), 30))]
    if not rows:
        return {"status": "success", "message": "Nothing needs anyone right now.", "situations": []}
    return {"status": "success", "message": _situation_lines(rows), "situations": rows}


def next_situation(skip_current: bool = False, acting_member: dict = None, focus_key: str = None) -> Dict[str, Any]:
    """The one most pressing situation as a sentence; sets the conversation's
    focus. Terminal: the message IS the spoken answer. Sensitive insights are
    never spoken (triage.next_for lists with spoken=True)."""
    from services import triage as _tri
    had = _tri.get_focus(focus_key) is not None
    s = _tri.next_for(acting_member, focus_key, skip_current=bool(skip_current))
    if s is None:
        msg = ("That's everything. Nothing else needs anyone right now." if (skip_current and had)
               else "Nothing needs anyone right now.")
        return {"status": "success", "message": msg, "situation": None, "focus": None}
    line = _tri.spoken(s)
    if not focus_key:
        # No conversation to hold the focus: end with the title so the
        # follow-up can name it.
        line += f" (Say '{s.get('title')}' to take it further.)"
    return {"status": "success", "message": line, "situation": s, "focus": _tri.get_focus(focus_key)}


def explain_situation(ref: str = '', kind: str = None, acting_member: dict = None,
                      focus_key: str = None) -> Dict[str, Any]:
    from services import situations as _sit
    found, why = _resolve_situation(ref, kind, acting_member, focus_key)
    if not found:
        return {"status": "error", "message": why}
    s = _sit.view(found[0], found[1], acting_member)
    opts = '\n'.join(f"  {i + 1}. {o['label']} [{o['verb']}, option {o['id']}]" for i, o in enumerate(s['options']))
    asks = '\n'.join(f"  - asked {a.get('to_name')} by {a.get('channel')}: {a.get('what')}: {a.get('state')}"
                     + (f" / {a['outcome']}" if a.get('outcome') else '') for a in s['asks']) or '  (none)'
    msg = (f"{s['title']}\nStatus: {s['status_note']}\nOptions:\n{opts}\nAsks so far:\n{asks}")
    return {"status": "success", "message": msg, "situation": s}


def act_on_situation(ref: str = '', verb: str = '', option_id: str = None, kind: str = None, text: str = None,
                     next_action_at: str = None, acting_member: dict = None, focus_key: str = None) -> Dict[str, Any]:
    from services import situations as _sit
    if not acting_member or acting_member.get('role') not in ('parent', 'adult'):
        return {"status": "error", "message": "Only a parent or adult can do that."}
    found, why = _resolve_situation(ref, kind, acting_member, focus_key)
    if not found:
        return {"status": "error", "message": why}
    k, sid = found
    if not option_id:
        opts = [o for o in _sit.options_for(k, _sit.load(k, sid)) if o['verb'] == verb]
        if len(opts) != 1:
            return {"status": "error",
                    "message": ("Say which option: " + '; '.join(f"{o['label']} ({o['id']})" for o in opts))
                    if opts else f"'{verb}' is not on the table for that one."}
        option_id = opts[0]['id']
    payload = {}
    if verb in ('answer', 'draft', 'research'):
        payload['text'] = text or ''
    if verb == 'advance':
        payload['next_action'] = text or ''
        payload['next_action_at'] = next_action_at
    res = _sit.act(k, sid, verb, option_id=option_id, payload=payload, actor=acting_member)
    if res.get('status') == 'refused':
        return {"status": "error", "message": res.get('message')}
    return res


def start_ask(ref: str = '', to_name: str = '', what: str = '', channel: str = '', kind: str = None,
              acting_member: dict = None, focus_key: str = None) -> Dict[str, Any]:
    from services import situations as _sit, asks as _asks
    if not acting_member or acting_member.get('role') not in ('parent', 'adult'):
        return {"status": "error", "message": "Only a parent or adult can ask."}
    found, why = _resolve_situation(ref, kind, acting_member, focus_key)
    if not found:
        return {"status": "error", "message": why}
    k, sid = found
    row = _sit.load(k, sid)
    to = {'name': to_name}
    from services import storage
    member = next((m for m in storage.get_all_members() if (m.get('name') or '').lower() == (to_name or '').lower()), None)
    contact = next((c for c in storage.get_assist_contacts() if (c.get('name') or '').lower() == (to_name or '').lower()), None)
    if member:
        to['member_id'] = member['id']
    elif contact:
        to['contact_id'] = contact['id']
    # The commitment is the SERVER's when an option binds it. A `what` the
    # model wrote that differs from the option's is a different ask: recorded
    # as written, unbound, so a yes never applies something they did not agree to.
    unlocks, bound_what = None, None
    for o in _sit.options_for(k, row):
        if o['verb'] != 'ask':
            continue
        if to.get('contact_id') and (o['payload'].get('to') or {}).get('contact_id') == to['contact_id']:
            unlocks, bound_what = o['payload'].get('unlocks'), o['payload'].get('what')
            break
        if o['id'] == 'ask:new' and unlocks is None:
            unlocks, bound_what = o['payload'].get('unlocks'), o['payload'].get('what')
    what = (what or '').strip()
    if bound_what and not what:
        what = bound_what
    elif bound_what and what != bound_what:
        unlocks = None
    if unlocks and unlocks.get('action_type') == 'assist_assignment' and to.get('contact_id'):
        unlocks = {**unlocks, 'payload': {**unlocks['payload'], 'contact_id': to['contact_id']}}
    event = _sit._cached_event(((unlocks or {}).get('payload') or {}).get('event_id')) if unlocks else None
    res = _asks.create(k, sid, to, what, channel, acting_member['id'], unlocks=unlocks, event=event)
    if res.get('status') != 'success':
        return {"status": "error", "message": res.get('message')}
    a = res['ask']
    how = {'chauffeur': f"Sent to {a['to_name']} on Chauffeur with Yes/No.",
           'email': "Here's the email. Copy it into your mail app, then tell me when it's sent:",
           'text': "Here's the text. Copy it, send it, then tell me when it's sent:",
           'in_person': "Here's what to say. Tell me once you've asked:"}[channel]
    draft = (f"Subject: {a['draft_subject']}\n\n" if a.get('draft_subject') else '') + (a.get('draft_body') or '')
    return {"status": "success", "ask_id": a['id'], "draft": draft,
            "message": f"{how}\n\n{draft}" if channel != 'chauffeur' else how}


def _focus_ask(focus_key: str, acting_member: dict):
    """The focus situation's ONE live ask, or a refusal naming the choice."""
    from services import triage as _tri
    if not _tri.get_focus(focus_key):
        return None, NO_FOCUS
    live = _tri.focus_live_asks(focus_key, acting_member)
    if len(live) == 1:
        return live[0]['id'], None
    if not live:
        return None, "Nobody has been asked about that one yet."
    names = ', or '.join(f"{a.get('to_name')} by {a.get('channel')}" for a in live)
    return None, f"Which ask: {names}?"


def mark_ask_sent(ask_id: str = None, acting_member: dict = None, focus_key: str = None) -> Dict[str, Any]:
    from services import asks as _asks
    if not ask_id:
        ask_id, why = _focus_ask(focus_key, acting_member)
        if not ask_id:
            return {"status": "error", "message": why}
    res = _asks.mark_sent(ask_id, acting_member)
    return {**res, "status": "error" if res.get('status') == 'refused' else res.get('status')}


def answer_ask(ask_id: str = None, answer: str = None, acting_member: dict = None,
               focus_key: str = None) -> Dict[str, Any]:
    from services import asks as _asks, storage
    if not ask_id:
        ask_id, why = _focus_ask(focus_key, acting_member)
        if not ask_id:
            return {"status": "error", "message": why}
    recipient = (storage.get_ask(ask_id) or {}).get('to_member_id')
    res = _asks.answer(ask_id, (answer or '').lower(), acting_member,
                       reported=(acting_member or {}).get('id') != recipient)
    return {**res, "status": "error" if res.get('status') == 'refused' else res.get('status')}
```

- [ ] **Step 5: Declare the tool to the model** in `get_available_tools()` — insert after the `list_situations` entry (near line 4253):

```python
        {
            "name": "next_situation",
            "description": "The ONE most pressing thing that needs a person, in a sentence, and it becomes the thing you are talking about: 'what needs my attention?', 'what's most urgent?', 'anything I need to deal with?'. Say skip_current for 'next', 'not that one', 'what else'. Use list_situations only for 'what's open', 'everything outstanding'.",
            "parameters": {"type": "object",
                           "properties": {"skip_current": {"type": "boolean", "description": "Move to the next one down the list."}},
                           "required": []}
        },
```

Change the `explain_situation`, `act_on_situation` and `start_ask` schemas so `ref` is no longer required and its description says what an empty ref means; change `mark_ask_sent`/`answer_ask` so `ask_id` is no longer required:

```python
        {
            "name": "explain_situation",
            "description": "The full picture of one thing that needs a person: status, every option with its id, and the asks so far. Takes an id or a title fragment ('tell me about the Thursday soccer one'); with no ref it is the one we are talking about.",
            "parameters": {"type": "object",
                           "properties": {"ref": {"type": "string", "description": "The situation's id or a fragment of its title. Leave empty for the one we are talking about."},
                                          "kind": {"type": "string", "description": "Optional: finding|insight|thread|mission."}},
                           "required": []}
        },
        {
            "name": "act_on_situation",
            "description": "Do one of a situation's options: assign a driver, approve a step, set a thread's next step, answer a mission, snooze, dismiss, take it yourself, mark it handled, or say Argyle read a reply wrong (unread). 'Handle it' / 'do that' with no name means the one we are talking about. Use start_ask to ask somebody.",
            "parameters": {"type": "object",
                           "properties": {"ref": {"type": "string", "description": "Id or title fragment; empty for the one we are talking about."},
                                          "verb": {"type": "string", "enum": ["assign", "plan", "prepare", "do", "done", "skip", "research", "draft", "advance", "answer", "close", "snooze", "dismiss", "own", "unread"]},
                                          "option_id": {"type": "string", "description": "The option id from explain_situation, when the verb has more than one."},
                                          "kind": {"type": "string"},
                                          "text": {"type": "string", "description": "For answer/draft/research: the text. For advance: the next action."},
                                          "next_action_at": {"type": "string", "description": "For advance: YYYY-MM-DD."}},
                           "required": ["verb"]}
        },
        {
            "name": "start_ask",
            "description": "Ask somebody for something about a situation, by a channel the person chose: 'text Sarah and ask her to drive Kate Thursday', 'email the inspector to come Friday', 'message Dad on Chauffeur'. With no ref it is about the one we are talking about. Returns the draft to copy (or sends it on Chauffeur).",
            "parameters": {"type": "object",
                           "properties": {"ref": {"type": "string", "description": "Empty for the one we are talking about."}, "to_name": {"type": "string"},
                                          "what": {"type": "string", "description": "The commitment being asked for, as a short phrase."},
                                          "channel": {"type": "string", "enum": ["chauffeur", "email", "text", "in_person"]},
                                          "kind": {"type": "string"}},
                           "required": ["to_name", "what", "channel"]}
        },
        {
            "name": "mark_ask_sent",
            "description": "The person says they sent the drafted text/email or asked in person ('sent it', 'I asked her'). With no ask_id it is the open ask on the one we are talking about.",
            "parameters": {"type": "object", "properties": {"ask_id": {"type": "string"}}, "required": []}
        },
        {
            "name": "answer_ask",
            "description": "Record what the person asked said ('Sarah said yes', 'Mike can't', 'she said no'), which applies the agreed change once. With no ask_id it is the open ask on the one we are talking about.",
            "parameters": {"type": "object",
                           "properties": {"ask_id": {"type": "string"}, "answer": {"type": "string", "enum": ["yes", "no"]}},
                           "required": ["answer"]}
        },
```

Note the `unread` verb in the enum: it is added to `situations.VERBS` in Task 9. Until then `scenario_parity_both_ways` in `test_situation_tools.py` will fail on the enum. To keep every commit green, add `'unread'` to `situations.VERBS` and to `VERB_LABELS` in `static/situations.js` (`'unread': 'Argyle got it wrong'`) in THIS task; `act` refuses the verb until Task 9 gives it an option (no option carries it yet, so `_refused("That option is no longer on the table…")` is what a caller gets, which is honest).

- [ ] **Step 6: Registry models, schemas and handlers**

Near line 5769, after `ListSituationsTool`:

```python
class NextSituationTool(BaseModel):
    """The one most pressing thing that needs a person, as a sentence; it becomes the thing being talked about."""
    skip_current: Optional[bool] = Field(False, description="Move to the next one down the list.")
```

Make `ref` optional on `ExplainSituationTool`, `ActOnSituationTool`, `StartAskTool` (`ref: Optional[str] = Field('', description=...)`) and `ask_id` optional on `MarkAskSentTool`, `AnswerAskTool` (`ask_id: Optional[str] = None`).

In `TOOL_SCHEMAS` (near line 6280) add `"next_situation": NextSituationTool.model_json_schema(),`.

Handlers (near line 7453): add

```python
def handle_next_situation(args: dict) -> dict:
    return next_situation(skip_current=bool(args.get('skip_current')), acting_member=_REGISTRY_READER)
```

and in `TOOL_HANDLERS` (near line 7821) add `"next_situation": handle_next_situation,`.

- [ ] **Step 7: Router sets — terminal and propose-only reads** (`services/agent_router.py`)

Add `"next_situation",` to `TERMINAL_ACTION_TOOLS` (right after `"list_open_findings",` on line 410) and add `"list_situations", "next_situation",` to `PROPOSE_ONLY_READS` (after `"list_threads", "list_programs", "program_progress",`). The dispatch branch itself is Task 4.

- [ ] **Step 8: Run the tests**

Run: `..\venv\Scripts\python.exe tests\test_triage.py` and `..\venv\Scripts\python.exe tools\test.py situation agent_v2_bridge`
Expected: `10/10 scenarios passed`; the situation tests and the bridge test green (the registry grew by one; `scenario_parity_both_ways` sees `unread` in the card, in `VERBS` and in the enum).

- [ ] **Step 9: Commit**

Bump `config.yaml` to `2.499.329`.

```bash
git add services/agent_tools_v2.py services/situations.py services/agent_router.py static/situations.js tests/test_triage.py tests/test_situation_tools.py config.yaml
git commit -m "feat(triage): next_situation tool, situation tools fall back to the conversation's focus, unread declared (v2.499.329)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

### Task 4: The router — `focus_key`, the FOCUS line, voice as the parent of record

**Files:**
- Modify: `services/agent_router.py` (`process_agent_request` signature, the prompt after the roster block near line 207, the situation-tools dispatch branch near line 800)
- Modify: `main.py` (`/api/v2/converse` near line 3850, `_run_argyle_mention` near line 15887, `/api/chat` near line 17647, `_approver_of_record` near line 5340)
- Test: `tests/test_triage.py`

**Interfaces:**
- Produces: `process_agent_request(..., propose_only=False, focus_key: Optional[str] = None)`. The situation tools receive `focus_key=` and, when the caller had no identity (and is not a driver, not propose-only), `acting_member=situations.parent_of_record()`; `list_situations` also receives `spoken=True` in that case.
- `main._approver_of_record(actor)` keeps its signature and calls `situations.parent_of_record()`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_triage.py`)

```python
from services import agent_router  # noqa: E402


def _fake_gemma(tool_call, captured=None):
    state = {'n': 0}

    def fake(prompt, tools, system_prompt):
        if captured is not None:
            captured['tools'] = [t['name'] for t in tools]
            captured['system'] = system_prompt
        state['n'] += 1
        if state['n'] == 1 and tool_call:
            return {'tool_calls': [tool_call], 'message': ''}
        # An EMPTY concluding message: the router keeps the tool's own
        # message as the reply, which is what these scenarios assert on.
        return {'tool_calls': [], 'message': ''}
    return fake


def _with_gemma(fake, fn):
    orig = agent_router.call_gemma_with_fallback
    agent_router.call_gemma_with_fallback = fake
    try:
        return fn()
    finally:
        agent_router.call_gemma_with_fallback = orig


def scenario_voice_acts_as_the_parent_of_record():
    _reset()
    storage.add_assist_contact({'id': 'c1', 'name': 'Sarah', 'kinds': ['driving'], 'active': True})
    fid = _finding('No driver yet: Soccer', 'decide', 30, 'ev1')
    start = NOON + datetime.timedelta(hours=30)
    storage.set_cached_schedule({'events': [{'id': 'ev1', 'title': 'Soccer', 'start': start.isoformat(),
                                             'end': start.isoformat()}], 'assignments': {}, 'unassigned': ['ev1']})
    call = {'name': 'next_situation', 'arguments': {}}
    res = _with_gemma(_fake_gemma(call), lambda: agent_router.process_agent_request('what needs my attention', focus_key='voice:1'))
    check(res['message'].startswith('No driver yet: Soccer.'), f"voice hears the ride with no identity: {res}")
    call = {'name': 'start_ask', 'arguments': {'to_name': 'Sarah', 'what': 'drive Kate Thursday', 'channel': 'text'}}
    res = _with_gemma(_fake_gemma(call), lambda: agent_router.process_agent_request('text Sarah and ask her', focus_key='voice:1'))
    asks = storage.get_asks(situation_kind='finding', situation_id=fid)
    check(len(asks) == 1 and asks[0]['asked_by'] == 'mom', f"the ask is the parent of record's: {asks}")
    res = _with_gemma(_fake_gemma(call), lambda: agent_router.process_agent_request('text Sarah', focus_key='voice:1', propose_only=True))
    check(len(storage.get_asks(situation_kind='finding', situation_id=fid)) == 1, "propose-only never reaches start_ask")
    kid = {'id': 'kid', 'name': 'Kate', 'role': 'child'}
    res = _with_gemma(_fake_gemma(call), lambda: agent_router.process_agent_request('text Sarah', source='family',
                                                                                     acting_member=kid, focus_key='channel:9'))
    check(len(storage.get_asks(situation_kind='finding', situation_id=fid)) == 1 and 'parent or adult' in res['message'],
          f"a child via @argyle is refused as today: {res}")


def scenario_voice_never_hears_a_sensitive_insight():
    _reset()
    storage.add_mind_insight({'slug': 's', 'line': 'SECRET', 'category': 'c', 'approach': 'x', 'identity': 'c:2',
                              'sensitivity': 'sensitive'})
    for name in ('next_situation', 'list_situations'):
        res = _with_gemma(_fake_gemma({'name': name, 'arguments': {}}),
                          lambda: agent_router.process_agent_request('what needs me', focus_key='voice:1'))
        check('SECRET' not in res['message'], f"{name} on voice never speaks a sensitive insight: {res}")
    res = _with_gemma(_fake_gemma({'name': 'list_situations', 'arguments': {}}),
                      lambda: agent_router.process_agent_request('what needs me', source='family', acting_member=MOM))
    check('SECRET' in res['message'], "a parent on her own phone still sees it in the list")


def scenario_focus_line_present_exactly_when_live():
    _reset()
    tid = threads.create('Deck permit', owner_member_id='mom', next_action='call', created_by='mom')
    cap = {}
    _with_gemma(_fake_gemma(None, cap), lambda: agent_router.process_agent_request('hi', focus_key='conv:1'))
    check('FOCUS:' not in cap['system'], "no focus, no line")
    triage.set_focus('conv:1', 'thread', tid, 'Deck permit')
    _with_gemma(_fake_gemma(None, cap), lambda: agent_router.process_agent_request('hi', focus_key='conv:1'))
    check('FOCUS: thread "Deck permit"' in cap['system'] and 'Handle it' in cap['system'], f"the line: {cap['system'][-400:]}")
    threads.close(tid, 'done', who='mom')
    _with_gemma(_fake_gemma(None, cap), lambda: agent_router.process_agent_request('hi', focus_key='conv:1'))
    check('FOCUS:' not in cap['system'], "a settled focus is not injected")


def scenario_voice_without_a_conversation_has_no_focus():
    _reset()
    threads.create('Deck permit', owner_member_id='mom', next_action='call',
                   next_action_at=(NOON - datetime.timedelta(days=1)).date().isoformat(), created_by='mom')
    res = _with_gemma(_fake_gemma({'name': 'next_situation', 'arguments': {}}),
                      lambda: agent_router.process_agent_request('what needs my attention'))
    check(res['message'].startswith('Deck permit.') and "Say 'Deck permit'" in res['message'], f"ends with the title: {res}")
    check(not storage.get_app_state(triage.FOCUS_KEY), "nothing written with no key")


SCENARIOS += [scenario_voice_acts_as_the_parent_of_record, scenario_voice_never_hears_a_sensitive_insight,
              scenario_focus_line_present_exactly_when_live, scenario_voice_without_a_conversation_has_no_focus]
```

- [ ] **Step 2: Run to verify they fail**

Run: `..\venv\Scripts\python.exe tests\test_triage.py`
Expected: FAIL with `TypeError: process_agent_request() got an unexpected keyword argument 'focus_key'`.

- [ ] **Step 3: Router signature and the FOCUS line**

Change the signature:

```python
def process_agent_request(user_prompt: str, context: Optional[Dict] = None, history: Optional[List[Dict]] = None,
                          source: str = "admin", driver_id: Optional[str] = None,
                          acting_member: Optional[Dict] = None,
                          propose_only: bool = False,
                          focus_key: Optional[str] = None) -> Dict[str, Any]:
```

Extend the docstring with one paragraph:

```
    focus_key names the conversation ("conv:<id>" for the widget, "voice:<id>"
    for HA Assist, "channel:<id>" for the Argyle DM). The situation tools hold
    the thing being talked about under it (services/triage.py); it is handed to
    them at dispatch and never shown to the model as a parameter.
```

After the roster block (right after the `except Exception as e: logger.warning(f"Could not inject family roster: {e}")` lines, before `if not driver:`), add:

```python
    # THE THING WE ARE TALKING ABOUT. After "what needs my attention" the
    # follow-ups ("handle it", "ask Sarah by text", "she said yes", "next")
    # need no title: the situation tools fall back to this focus. Only a live
    # focus is injected; triage.get_focus drops a settled one itself.
    if focus_key:
        try:
            from services import triage as _tri, situations as _sit
            _f = _tri.get_focus(focus_key)
            if _f:
                _s = _sit.view(_f['kind'], _f['id'], acting_member or _sit.parent_of_record())
                _nxt = ((_s or {}).get('next_step') or {}).get('label') or '-'
                system_prompt += (f"\nFOCUS: {_f['kind']} \"{_f.get('title')}\" — next step: {_nxt}. "
                                  "\"Handle it\", \"do that\", \"ask X by Y\", \"she said yes\", \"sent it\", "
                                  "\"next\", \"skip it\" refer to this one unless another is named: call the "
                                  "situation tools with NO ref for it.\n")
        except Exception as e:
            logger.warning(f"Could not inject focus: {e}")
```

- [ ] **Step 4: The dispatch branch** — replace the block at line 800 (`elif func_name in ("list_situations", ...)`) with:

```python
                elif func_name in ("list_situations", "next_situation", "explain_situation", "act_on_situation",
                                   "start_ask", "mark_ask_sent", "answer_ask"):
                    from services import agent_tools_v2 as _atv2, situations as _sit
                    # Same actor resolution as the thread tools below: resolved
                    # HERE at dispatch, never taken from the model. A caller with
                    # no identity (HA voice, the admin widget) acts as the parent
                    # of record — the rule the admin pages already use — and is
                    # treated as a ROOM: nothing sensitive is read out. Never on
                    # the propose-only rail, never in driver mode.
                    actor = acting_member
                    substituted = False
                    if actor is None and driver:
                        from services import storage as _st
                        actor = _st.get_member_by_driver_id(driver_id)
                    elif actor is None and not propose_only:
                        actor = _sit.parent_of_record()
                        substituted = actor is not None
                    fn = getattr(_atv2, func_name)
                    allowed = fn.__code__.co_varnames[:fn.__code__.co_argcount]
                    kwargs = {k: v for k, v in (args or {}).items()
                              if k in allowed and k not in ('acting_member', 'focus_key', 'spoken')}
                    if 'focus_key' in allowed:
                        kwargs['focus_key'] = focus_key
                    if 'spoken' in allowed:
                        kwargs['spoken'] = substituted
                    res = fn(**kwargs, acting_member=actor)
                    if isinstance(res, dict) and res.get("schedule_dirty"):
                        schedule_dirty = True
                    if res.get("message"): agent_message = res["message"]
```

- [ ] **Step 5: Entry points in `main.py`**

`/api/v2/converse` (line 3850):

```python
        res = process_agent_request(req.text, history=conv_history,
                                    focus_key=f"voice:{req.conversation_id}" if req.conversation_id else None)
```

`_run_argyle_mention` (line 15887):

```python
        res = process_agent_request(query, source="family", acting_member=sender,
                                    focus_key=f"channel:{channel.get('id')}" if channel.get('id') else None)
```

`/api/chat` (line 17647):

```python
        res = process_agent_request(payload.message, context=payload.context, history=conv_history,
                                    source=payload.source or "admin", driver_id=payload.driver_id,
                                    focus_key=f"conv:{payload.conversation_id}" if payload.conversation_id else None)
```

`_approver_of_record` (line 5358 onward): replace the body after the docstring with

```python
    if actor:
        return actor
    from services import situations as _sit
    parent = _sit.parent_of_record()
    if not parent:
        raise HTTPException(
            status_code=400,
            detail="There is no parent on record to approve this as.")
    return parent
```

- [ ] **Step 6: Run the tests**

Run: `..\venv\Scripts\python.exe tests\test_triage.py` then `..\venv\Scripts\python.exe tools\test.py agent_v2_bridge argyle_chat mind_plan chat_actions situation`
Expected: `14/14 scenarios passed`; the named related tests green. `test_mind_plan` drives `propose_only=True` through the router: the substitution must not fire there (the `elif ... not propose_only` guard).

- [ ] **Step 7: Commit**

Bump `config.yaml` to `2.499.330`.

```bash
git add services/agent_router.py main.py tests/test_triage.py config.yaml
git commit -m "feat(triage): the router carries the conversation's focus and voice acts as the parent of record, a room that never hears a sensitive insight (v2.499.330)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

### Task 5: Thread sends become ask ledger rows

**Files:**
- Modify: `services/asks.py` (`record_sent`)
- Modify: `services/threads.py` (`send_drafted` records the row; `draft_message` returns the intent it was given)
- Modify: `main.py` `/api/threads/{thread_id}/send` (passes `intent` from the body when the page has one)
- Test: `tests/test_reply_reading.py` (new)

**Interfaces:**
- Produces:
  - `asks.record_sent(kind, sid, to: dict, what: str, subject: str, body: str, asked_by: str) -> str` — writes a `sent` row with `sent_via: 'household'`, no draft call, no `unlocks`, no refresh request; returns the ask id.
  - `threads.send_drafted(thread_id, subject, body, to, who=None, intent: str = '') -> dict` — unchanged result shape; on `ok` the result also carries `ask_id`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reply_reading.py
"""A vendor's reply on a thread is read once, recorded on the ask ledger,
never applied. Spec: docs/superpowers/specs/2026-10-10-triage-and-replies-design.md §2."""
import datetime
import time

from harness import check  # noqa: F401
from services import storage, situations, threads, asks, mailer

MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}
CALLS = []


def _reset():
    CALLS.clear()
    for t in (storage.asks_table, storage.findings_table, storage.mind_insights_table, storage.members_table,
              storage.app_state_table, storage.threads_table, storage.missions_table, storage.mission_steps_table,
              storage.assist_contacts_table, storage.chat_channels_table, storage.chat_messages_table):
        t.truncate()
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k', 'thread_stall_days': 7}
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'dad', 'name': 'Dad', 'role': 'parent'})
    situations.REFRESH_DELAY_S = 0
    situations._pool_call = lambda *a, **k: {}
    mailer.send = lambda to, subject, body, settings=None: {'sent': True}
    mailer.configured = lambda *a, **k: True


def _thread(title='Pest control', email='ops@pestco.example'):
    return threads.create(title, owner_member_id='mom', counterparty_name='Pest Co',
                          counterparty_email=email, created_by='mom')


def scenario_send_records_a_sent_ask_with_no_unlocks():
    _reset()
    tid = _thread()
    res = threads.send_drafted(tid, 'Can you come Friday?', 'Hi, could you come Friday morning?',
                               'ops@pestco.example', who='mom', intent='come Friday morning')
    check(res['status'] == 'ok' and res.get('ask_id'), f"sent: {res}")
    a = storage.get_ask(res['ask_id'])
    check(a['situation_kind'] == 'thread' and a['situation_id'] == tid, "the ask belongs to the thread")
    check(a['state'] == 'sent' and a['sent_via'] == 'household' and a['channel'] == 'email', f"sent at once, by the household address: {a}")
    check(a['what'] == 'come Friday morning' and a['to_name'] == 'Pest Co' and a['unlocks'] is None, f"the commitment is the intent, unbound: {a}")
    check(a['draft_subject'] == 'Can you come Friday?' and a['asked_by'] == 'mom', "what went out is on the row")
    res2 = threads.send_drafted(tid, 'Following up', 'Any news?', 'ops@pestco.example', who='mom')
    a2 = storage.get_ask(res2['ask_id'])
    check(a2['what'] == 'Following up', "with no intent the subject is the commitment")
    s = situations.view('thread', tid, MOM)
    check(len(s['asks']) == 2 and all(x['state'] == 'sent' for x in s['asks']), "the card's ledger shows both, waiting")


def scenario_send_without_a_member_is_asked_by_the_parent_of_record():
    _reset()
    tid = _thread()
    res = threads.send_drafted(tid, 'S', 'B', 'ops@pestco.example', who=None)
    check(storage.get_ask(res['ask_id'])['asked_by'] == 'mom', "an admin-surface send is the parent of record's ask")


SCENARIOS = [scenario_send_records_a_sent_ask_with_no_unlocks, scenario_send_without_a_member_is_asked_by_the_parent_of_record]

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

Run: `..\venv\Scripts\python.exe tests\test_reply_reading.py`
Expected: FAIL with `TypeError: send_drafted() got an unexpected keyword argument 'intent'`.

- [ ] **Step 3: `asks.record_sent`** (add to `services/asks.py` after `create`)

```python
def record_sent(kind: str, sid: Optional[str], to: dict, what: str, subject: str, body: str,
                asked_by: Optional[str]) -> str:
    """A mail that already left by the household address (threads.send_drafted)
    becomes a `sent` ledger row: the reply has something to answer. No draft
    call (the words are the person's), no unlocks (nothing to apply), no
    refresh request (the send's own touch covers it)."""
    if not asked_by:
        from services import situations as _sit
        asked_by = ((_sit.parent_of_record() or {}).get('id')) or ''
    data = {'situation_kind': kind, 'situation_id': sid, 'to_name': (to or {}).get('name') or 'them',
            'to_member_id': None, 'to_contact_id': (to or {}).get('contact_id'),
            'to_email': (to or {}).get('email') or '',
            'what': (what or '').strip() or (subject or '').strip() or 'reply',
            'channel': 'email', 'asked_by': asked_by, 'unlocks': None,
            'state': 'sent', 'sent_at': time.time(), 'sent_via': 'household',
            'draft_subject': subject or '', 'draft_body': body or '', 'draft_source': 'person',
            'event_id': None, 'event_start': '', 'event_title': '', 'event_date': ''}
    return storage.add_ask(data)
```

- [ ] **Step 4: `threads.send_drafted` records the row**

Change the signature to `def send_drafted(thread_id: str, subject: str, body: str, to: str, who: str = None, intent: str = '') -> dict:` and, after the `sent` history entry and the `waiting` update (before `_sit.touched`), add:

```python
    # The mail is now a thing the counterparty can answer: a ledger row with
    # the household address as the sender (spec 2026-10-10 §2). The intent
    # the draft was asked for is the commitment; else the subject line.
    from services import asks as _asks
    ask_id = _asks.record_sent('thread', thread_id,
                               {'name': thread.get('counterparty_name') or to, 'email': to,
                                'contact_id': thread.get('contact_id')},
                               intent or subject, subject, body, who)
```

and return `{'status': 'ok', 'ask_id': ask_id}`.

In `draft_message`, add `'intent': (intent or '').strip()` to the `ok` result so the page can carry it to the send.

- [ ] **Step 5: `/api/threads/{thread_id}/send` passes the intent**

```python
    res = _threads.send_drafted(thread_id, subject, msg_body, to,
                                who=(actor or {}).get('id'), intent=body.get('intent') or '')
```

In `templates/components/threads_page.html`, find where the draft result is stored into the per-row form (search for `draft.subject` / the `/draft` fetch in the page script) and keep `intent` on the same object, then include `intent: draft.intent || ''` in the `/send` POST body. If the page's draft form has no intent field, the model's `intent` is the empty string and the subject is the commitment, which the test above covers.

- [ ] **Step 6: Run the tests**

Run: `..\venv\Scripts\python.exe tests\test_reply_reading.py` and `..\venv\Scripts\python.exe tools\test.py threads situations_refresh asks`
Expected: `2/2`; `test_situations_refresh.scenario_one_logical_mutation_one_call` still counts one call (record_sent requests no refresh); `test_threads` green.

- [ ] **Step 7: Commit**

Bump `config.yaml` to `2.499.331`.

```bash
git add services/asks.py services/threads.py main.py templates/components/threads_page.html tests/test_reply_reading.py config.yaml
git commit -m "feat(replies): a thread send becomes a sent ask on the ledger, by the household address, with nothing to apply (v2.499.331)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

### Task 6: `services/replies.py` — one reading per matched reply

**Files:**
- Create: `services/replies.py`
- Modify: `services/threads.py` (`match_inbound` takes `message_id`, dedupes by it, stores it on the entry)
- Modify: `services/storage.py` (`update_thread_history_entry`)
- Modify: `services/email_ingest.py` (`_match_thread` passes `message_id` and calls `replies.read`)
- Modify: `models/schemas.py`, `services/settings_registry.py`, `templates/components/mind_page.html` (`reply_cap_reads`)
- Test: `tests/test_reply_reading.py`

**Interfaces:**
- Produces:
  - `storage.update_thread_history_entry(thread_id: str, match: dict, fields: dict) -> bool` — updates the FIRST history entry whose keys equal `match`.
  - `threads.match_inbound(from_addr, subject='', body='', message_id: str = None) -> Optional[str]` — unchanged contract; with a `message_id` already on the thread's history it returns that thread id and appends nothing.
  - `replies.read(thread_id: str, message_id: str) -> Optional[dict]` — the reading `{answer, summary, ts, source}` or None; stores it on the entry; bumps `rev`; records the answer on the one live ask (Task 7); notifies the owner (Task 8).
  - `replies.READ_SYSTEM`, `replies.CAP_READS_DEFAULT = 40`, `replies._pool_call` (stub point).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_reply_reading.py`)

```python
from services import replies  # noqa: E402


def _fake_pool(reply):
    def f(tier, api_key, system, prompt, **kw):
        CALLS.append({'tier': tier, 'prompt': prompt, 'kw': kw})
        return reply() if callable(reply) else reply
    return f


def _reply(tid, text='Friday at 9 works for us.', mid='<m1@pestco>'):
    return threads.match_inbound('ops@pestco.example', 'Re: Can you come Friday?', text, message_id=mid)


def scenario_a_matched_reply_is_read_once_and_stored_on_the_entry():
    _reset()
    replies._pool_call = _fake_pool({'answer': 'yes', 'summary': 'Friday 9am works'})
    tid = _thread()
    threads.send_drafted(tid, 'Can you come Friday?', 'B', 'ops@pestco.example', who='mom', intent='come Friday morning')
    rev0 = storage.get_thread(tid)['rev']
    matched = _reply(tid)
    check(matched == tid, "the reply lands on the thread")
    replies.read(tid, '<m1@pestco>')
    check(len(CALLS) == 1 and CALLS[0]['tier'] == 'interactive' and CALLS[0]['kw'].get('timeout_s') == 20, f"one Lite call: {CALLS}")
    check('come Friday morning' in CALLS[0]['prompt'] and 'Pest control' in CALLS[0]['prompt'], "the prompt carries the ask and the title")
    h = storage.get_thread(tid)['history'][-1]
    check(h['kind'] == 'received' and h.get('message_id') == '<m1@pestco>', f"the entry knows its mail: {h}")
    check(h.get('reading', {}).get('answer') == 'yes' and h['reading']['summary'] == 'Friday 9am works'
          and h['reading']['source'] == 'argyle', f"the reading is on the entry: {h}")
    check(storage.get_thread(tid)['rev'] > rev0, "a reading moves the rev so the note refreshes")
    replies.read(tid, '<m1@pestco>')
    check(len(CALLS) == 1, "read once, never again")
    check(_reply(tid) == tid and len([x for x in storage.get_thread(tid)['history'] if x['kind'] == 'received']) == 1,
          "a rescan of the same mail appends nothing")


def scenario_no_key_cap_or_failure_leaves_no_reading():
    _reset()
    tid = _thread()
    threads.send_drafted(tid, 'S', 'B', 'ops@pestco.example', who='mom')
    storage.get_settings = lambda: {'thread_stall_days': 7}            # no key
    # 'info' throughout this scenario: a yes would reach asks.record_reading,
    # which Task 7 adds. The cap/failure paths are the point here.
    replies._pool_call = _fake_pool({'answer': 'info', 'summary': 'x'})
    _reply(tid, mid='<a>')
    check(replies.read(tid, '<a>') is None and not CALLS, "no key: no call, no reading")
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k', 'thread_stall_days': 7, 'reply_cap_reads': 1}
    _reply(tid, mid='<b>')
    check(replies.read(tid, '<b>') is not None and len(CALLS) == 1, "under the cap: read")
    _reply(tid, mid='<c>')
    check(replies.read(tid, '<c>') is None and len(CALLS) == 1, "over the cap: no call")
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k', 'thread_stall_days': 7}
    def boom(*a, **k):
        raise RuntimeError('timeout')
    replies._pool_call = boom
    _reply(tid, mid='<d>')
    check(replies.read(tid, '<d>') is None, "a failure is no reading, not a crash")
    replies._pool_call = _fake_pool({'answer': 'maybe-ish', 'summary': 'x'})
    _reply(tid, mid='<e>')
    r = replies.read(tid, '<e>')
    check(r and r['answer'] == 'unclear', f"an answer outside the five words is unclear: {r}")
    h = [x for x in storage.get_thread(tid)['history'] if x.get('message_id') == '<d>'][0]
    check('reading' not in h, "the failed one carries no reading")


def scenario_the_module_never_applies_and_never_reads_dms():
    src = open('services/replies.py', encoding='utf-8').read()
    for banned in ('apply(', 'get_channel_messages', 'get_gift', 'gifts_table'):
        check(banned not in src, f"replies.py never names {banned}")


SCENARIOS += [scenario_a_matched_reply_is_read_once_and_stored_on_the_entry, scenario_no_key_cap_or_failure_leaves_no_reading,
              scenario_the_module_never_applies_and_never_reads_dms]
```

- [ ] **Step 2: Run to verify they fail**

Run: `..\venv\Scripts\python.exe tests\test_reply_reading.py`
Expected: FAIL with `ImportError: cannot import name 'replies'`.

- [ ] **Step 3: `storage.update_thread_history_entry`** (add after `append_thread_history`)

```python
def update_thread_history_entry(thread_id: str, match: dict, fields: dict) -> bool:
    """Update the first history entry whose keys equal `match` (a reply is
    found by its mail's message_id). Entries have no ids of their own."""
    with db_lock:
        res = threads_table.search(Query().id == thread_id)
        if not res:
            return False
        row = dict(res[0])
        history = list(row.get('history') or [])
        for i, h in enumerate(history):
            if all(h.get(k) == v for k, v in (match or {}).items()):
                history[i] = {**h, **fields}
                threads_table.update({'history': history}, Query().id == thread_id)
                return True
    return False
```

- [ ] **Step 4: `threads.match_inbound` carries and dedupes by `message_id`**

Change the signature to `def match_inbound(from_addr: str, subject: str = '', body: str = '', message_id: str = None) -> Optional[str]:`. Add to the docstring: "A `message_id` already on an open thread's history means this mail was filed before (a rescan): that thread id is returned and nothing is appended." After `addr = ...; if not addr: return None` add:

```python
    mid = (message_id or '').strip() or None
    if mid:
        for t in storage.get_threads(include_closed=False):
            if any(h.get('message_id') == mid for h in (t.get('history') or [])):
                return t['id']
```

And include `'message_id': mid` in the `received` entry dict.

- [ ] **Step 5: Create `services/replies.py`**

```python
"""Replies — a counterparty's mail on a thread, read once. Spec:
docs/superpowers/specs/2026-10-10-triage-and-replies-design.md §2.

Runs inside the ingest poll, after `threads.match_inbound` filed the mail.
One Lite call per message_id, capped; the reading lands on the history entry;
a clear yes or no is RECORDED on the thread's one live ask and never applied
(`asks.record_reading`; `asks.apply` is never named here). The owner is told
once, inside the watcher's waking window.

Boundaries: never import a DM reader, never read gift records.
"""
import datetime
import logging
import time
from typing import Optional

from services import storage

logger = logging.getLogger(__name__)

ANSWERS = ('yes', 'no', 'question', 'info', 'unclear')
CAP_READS_DEFAULT = 40
READ_TIMEOUT_S = 20
REPLY_CHARS = 1500

READ_SYSTEM = (
    "You read ONE email reply that a family received from somebody outside "
    "the family, about one thing they asked for. Decide what the reply says "
    "about that ask: yes (they agree or will do it), no (they decline or "
    "cannot), question (they ask something back), info (news with no answer "
    "either way), unclear. Then summary: at most 20 words of what they said, "
    "plain, no advice. Return STRICT JSON: {\"answer\": \"yes|no|question|info|unclear\", "
    "\"summary\": \"...\"}. Never invent facts."
)


def _pool_call(tier, api_key, system, prompt, **kw):
    """Indirection so tests stub one attribute (situations.py precedent)."""
    from services import model_pools
    return model_pools.call_pool_json(tier, api_key, system, prompt, **kw)


def _entry(thread: dict, message_id: str) -> Optional[dict]:
    return next((h for h in (thread.get('history') or [])
                 if h.get('kind') == 'received' and h.get('message_id') == message_id), None)


def live_ask(thread_id: str) -> Optional[dict]:
    """The newest household-sent ask still waiting; None when there is none
    or more than one would be ambiguous is NOT a concern here: the newest
    sent mail is the one a reply answers."""
    rows = [a for a in storage.get_asks(situation_kind='thread', situation_id=thread_id)
            if a.get('state') in ('sent', 'drafted') and a.get('sent_via') == 'household']
    rows.sort(key=lambda a: a.get('sent_at') or a.get('asked_at') or 0)
    return rows[-1] if rows else None


def _classify(thread: dict, entry: dict, ask: Optional[dict], settings: dict) -> Optional[dict]:
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key:
        return None
    from services import situations as _sit
    cap = int(settings.get('reply_cap_reads', CAP_READS_DEFAULT))
    if not _sit._bump_call('reply', cap):
        return None
    text = (entry.get('text') or '')[:REPLY_CHARS]
    prompt = (f"Thread: {thread.get('title')}. "
              + (f"What was asked: {ask.get('what')}. " if ask else "Nothing specific was asked. ")
              + f"The reply:\n{text}")
    try:
        res = _pool_call('interactive', api_key, READ_SYSTEM, prompt, timeout_s=READ_TIMEOUT_S,
                         background=True, workflow='replies.read')
    except Exception as e:
        logger.warning(f"[replies] reading failed: {e}")
        return None
    if not isinstance(res, dict) or res.get('error'):
        return None
    answer = str(res.get('answer') or '').strip().lower()
    if answer not in ANSWERS:
        answer = 'unclear'
    summary = ' '.join(str(res.get('summary') or '').split())[:160]
    return {'answer': answer, 'summary': summary, 'ts': time.time(), 'source': 'argyle'}


def read(thread_id: str, message_id: str) -> Optional[dict]:
    """Read the reply filed as `message_id` on this thread, once. Returns the
    reading, or None when nothing was read (no key, cap, failure, already
    read, no such entry). Every path that stores a reading also records the
    answer on the live ask and notifies the owner."""
    thread = storage.get_thread(thread_id)
    if not thread or not message_id:
        return None
    entry = _entry(thread, message_id)
    if not entry or entry.get('reading'):
        return None if not entry else entry.get('reading')
    settings = storage.get_settings() or {}
    ask = live_ask(thread_id)
    reading = _classify(thread, entry, ask, settings)
    if reading is None:
        # No reading: the card's next step still names the reply (deterministic,
        # situations._options_thread) and the owner is still told.
        _notify(thread, entry, None)
        return None
    storage.update_thread_history_entry(thread_id, {'message_id': message_id}, {'reading': reading})
    from services import asks as _asks, situations as _sit
    if ask and reading['answer'] in ('yes', 'no'):
        _asks.record_reading(ask['id'], reading['answer'], message_id, summary=reading['summary'])
    _sit.bump_rev('thread', thread_id)
    _sit.request_refresh('thread', thread_id)
    _notify(thread, entry, reading)
    return reading


def _notify(thread: dict, entry: dict, reading: Optional[dict]) -> None:
    """Filled in by Task 8 (one DM to the owner, deferred through quiet hours)."""
    return None
```

- [ ] **Step 6: Wire the ingest poll** — `services/email_ingest.py` `_match_thread`:

```python
def _match_thread(msg: dict) -> None:
    """Thread matching is additive and independent of event extraction — a
    reply from a vendor can carry both a date-bound item AND be an update to
    an open thread, and neither should suppress the other. Runs once per
    email, AFTER extraction settles, so a retried email is never matched
    twice. A matched reply is then READ once (services/replies.py), under its
    own cap, inside this poll. A failure here must never break ingest."""
    try:
        from services import threads
        thread_id = threads.match_inbound(msg['from'], msg['subject'], msg['text'],
                                          message_id=msg.get('message_id'))
    except Exception as e:
        print(f"[email_ingest] thread match failed: {e}")
        return
    if not thread_id or not msg.get('message_id'):
        return
    try:
        from services import replies
        replies.read(thread_id, msg['message_id'])
    except Exception as e:
        print(f"[email_ingest] reply reading failed: {e}")
```

- [ ] **Step 7: The cap setting, three places**

`models/schemas.py` after `ask_cap_drafts`:

```python
    reply_cap_reads: Optional[int] = 40        # replies: readings of inbound thread mail per day
```

`services/settings_registry.py` after the `ask_cap_drafts` entry:

```python
    _e('reply_cap_reads', 'mind', 'Daily reply-reading cap',
       "Hard ceiling on replies Argyle reads from the family mailbox per day (default 40). Over the cap "
       "a reply is filed on its thread unread, and the card says to read it.",
       page='work?tab=mind', anchor='mind-general'),
```

`templates/components/mind_page.html`: after the "Daily ask-draft cap" tile (line 101) add the same tile for `s.reply_cap_reads` with the label "Daily reply-reading cap"; add `reply_cap_reads: 40,` to the defaults near line 298 and `reply_cap_reads: Math.max(0, parseInt(this.s.reply_cap_reads, 10) || 0),` to the save payload near line 432. Then run `..\venv\Scripts\python.exe tools\build_tailwind.py`.

- [ ] **Step 8: Run the tests**

Run: `..\venv\Scripts\python.exe tests\test_reply_reading.py` and `..\venv\Scripts\python.exe tools\test.py threads email_ingest settings_registry mind_endpoints tailwind_build`
Expected: `5/5` (the `record_reading` call in `read` is reached only on yes/no; the first scenario's `yes` will fail until Task 7 adds `asks.record_reading` — so in THIS task, make the first scenario's fake return `{'answer': 'info', 'summary': 'Friday 9am works'}` and assert `answer == 'info'`; Task 7 switches it back to `yes`). `test_email_ingest` green; the settings registry audit finds the new key on the Mind page.

- [ ] **Step 9: Commit**

Bump `config.yaml` to `2.499.332`.

```bash
git add services/replies.py services/threads.py services/storage.py services/email_ingest.py models/schemas.py services/settings_registry.py templates/components/mind_page.html static/tailwind.css tests/test_reply_reading.py config.yaml
git commit -m "feat(replies): a matched reply is read once inside the ingest poll, stored on its history entry, capped, never a crash (v2.499.332)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

(If `tools/build_tailwind.py` writes the sheet to a different path, add that path instead of `static/tailwind.css`.)

---

### Task 7: `asks.record_reading`, `asks.unread` — record, never apply; revert

**Files:**
- Modify: `services/asks.py`
- Test: `tests/test_reply_reading.py`

**Interfaces:**
- Produces:
  - `asks.record_reading(ask_id, answer: str, message_id: str, summary: str = '') -> bool` — under the lock; only an ask in `sent`/`drafted` with `sent_via == 'household'` moves; `yes` → `outcome: 'manual'`; sets `answered_by: 'argyle'`, `read_from`, `read_summary`; requests the situation refresh. Returns whether it moved.
  - `asks.unread(ask_id, actor) -> dict` — parent/adult; only `answered_by == 'argyle'`; back to `sent`, clears the answer fields, marks the history entry's reading `disputed: True`.

- [ ] **Step 1: Write the failing tests** (append; and switch Task 6's first scenario fake back to `{'answer': 'yes', 'summary': 'Friday 9am works'}` with `answer == 'yes'`)

```python
def scenario_reading_yes_records_manual_never_applies():
    _reset()
    replies._pool_call = _fake_pool({'answer': 'yes', 'summary': 'Friday 9am works'})
    tid = _thread()
    res = threads.send_drafted(tid, 'Can you come Friday?', 'B', 'ops@pestco.example', who='mom', intent='come Friday morning')
    _reply(tid)
    replies.read(tid, '<m1@pestco>')
    a = storage.get_ask(res['ask_id'])
    check(a['state'] == 'yes' and a['outcome'] == 'manual' and a['answered_by'] == 'argyle', f"recorded, apply by hand: {a}")
    check(a['read_from'] == '<m1@pestco>' and a['read_summary'] == 'Friday 9am works', "the reading is on the ask")
    check(a['applied_at'] is None, "nothing applied")


def scenario_reading_no_question_info_unclear():
    _reset()
    tid = _thread()
    for i, (answer, expect_state) in enumerate([('no', 'no'), ('question', 'sent'), ('info', 'sent'), ('unclear', 'sent')]):
        res = threads.send_drafted(tid, f'S{i}', 'B', 'ops@pestco.example', who='mom')
        replies._pool_call = _fake_pool({'answer': answer, 'summary': f'{answer} summary'})
        _reply(tid, mid=f'<r{i}>')
        replies.read(tid, f'<r{i}>')
        a = storage.get_ask(res['ask_id'])
        check(a['state'] == expect_state, f"{answer}: the ask is {a['state']}, expected {expect_state}")
        h = [x for x in storage.get_thread(tid)['history'] if x.get('message_id') == f'<r{i}>'][0]
        check(h['reading']['answer'] == answer, "the reading is on the history whatever the answer")


def scenario_reading_with_no_live_ask_lands_on_history_only():
    _reset()
    tid = _thread()
    replies._pool_call = _fake_pool({'answer': 'yes', 'summary': 'sure'})
    _reply(tid, mid='<x>')
    r = replies.read(tid, '<x>')
    check(r and r['answer'] == 'yes' and not storage.get_asks(situation_kind='thread', situation_id=tid), "no ask to answer; the reading is kept")


def scenario_reading_never_overwrites_a_human_answer():
    _reset()
    tid = _thread()
    res = threads.send_drafted(tid, 'S', 'B', 'ops@pestco.example', who='mom')
    asks.answer(res['ask_id'], 'no', MOM, reported=True)
    replies._pool_call = _fake_pool({'answer': 'yes', 'summary': 'sure'})
    _reply(tid, mid='<y>')
    replies.read(tid, '<y>')
    a = storage.get_ask(res['ask_id'])
    check(a['state'] == 'no' and a['answered_by'] == 'mom', f"the owner's no stands: {a}")
    h = [x for x in storage.get_thread(tid)['history'] if x.get('message_id') == '<y>'][0]
    check(h['reading']['answer'] == 'yes', "the reading still lands on the history")


def scenario_unread_reverts_a_reading_and_refuses_a_tap():
    _reset()
    tid = _thread()
    res = threads.send_drafted(tid, 'S', 'B', 'ops@pestco.example', who='mom')
    replies._pool_call = _fake_pool({'answer': 'yes', 'summary': 'Friday works'})
    _reply(tid, mid='<z>')
    replies.read(tid, '<z>')
    out = asks.unread(res['ask_id'], MOM)
    a = storage.get_ask(res['ask_id'])
    check(out['status'] == 'success' and a['state'] == 'sent' and a['answered_by'] is None and a['outcome'] is None
          and a['read_from'] is None, f"back to waiting: {a}")
    h = [x for x in storage.get_thread(tid)['history'] if x.get('message_id') == '<z>'][0]
    check(h['reading']['disputed'] is True and h['reading']['answer'] == 'yes', "the reading is kept, disputed")
    asks.answer(res['ask_id'], 'yes', MOM, reported=True)
    out = asks.unread(res['ask_id'], MOM)
    check(out['status'] == 'refused' and 'Mom' in out['message'], f"a human answer is not undone this way: {out}")
    check(asks.unread(res['ask_id'], {'id': 'kid', 'role': 'child'})['status'] == 'refused', "a child cannot")


SCENARIOS += [scenario_reading_yes_records_manual_never_applies, scenario_reading_no_question_info_unclear,
              scenario_reading_with_no_live_ask_lands_on_history_only, scenario_reading_never_overwrites_a_human_answer,
              scenario_unread_reverts_a_reading_and_refuses_a_tap]
```

- [ ] **Step 2: Run to verify they fail**

Run: `..\venv\Scripts\python.exe tests\test_reply_reading.py`
Expected: FAIL with `AttributeError: module 'services.asks' has no attribute 'record_reading'`.

- [ ] **Step 3: Add to `services/asks.py`** (after `answer`)

```python
def record_reading(ask_id: str, answer: str, message_id: str, summary: str = '') -> bool:
    """Argyle read a reply as a clear yes or no (services/replies.py). The
    ask records it and NOTHING is applied: a yes is `manual` ("apply by
    hand"), because a household-sent ask never carries unlocks. Only a
    waiting ask moves; a human answer already recorded stands. Not a tool,
    not an endpoint: the only caller is the reading."""
    if answer not in ('yes', 'no'):
        return False
    with storage.db_lock:
        ask = storage.get_ask(ask_id)
        if not ask or ask.get('state') not in ('sent', 'drafted') or ask.get('sent_via') != 'household':
            return False
        fields = {'state': answer, 'answered_at': time.time(), 'answered_by': 'argyle',
                  'read_from': message_id, 'read_summary': (summary or '')[:160]}
        if answer == 'yes':
            fields['outcome'] = 'manual'
        storage.update_ask(ask_id, fields)
    _touch(ask.get('situation_kind'), ask.get('situation_id'))
    return True


def unread(ask_id: str, actor: dict) -> dict:
    """"Argyle got it wrong": a reading-answered ask goes back to waiting; the
    reply and its reading stay on the history, marked disputed. A tapped or
    reported answer is never undone here (withdraw is for that)."""
    ask = storage.get_ask(ask_id)
    if not ask:
        return {'status': 'error', 'message': 'That ask is no longer here.'}
    if not _can_write(actor):
        return {'status': 'refused', 'message': 'Only a parent or adult can do that.'}
    if ask.get('answered_by') != 'argyle':
        who = (storage.get_member(ask.get('answered_by') or '') or {}).get('name') or 'somebody'
        return {'status': 'refused', 'message': f"That was answered by {who}, not read by Argyle."}
    with storage.db_lock:
        storage.update_ask(ask_id, {'state': 'sent', 'answered_at': None, 'answered_by': None,
                                    'outcome': None, 'read_from': None, 'read_summary': None})
    if ask.get('situation_kind') == 'thread' and ask.get('read_from'):
        thread = storage.get_thread(ask['situation_id']) or {}
        entry = next((h for h in thread.get('history') or [] if h.get('message_id') == ask['read_from']), None)
        if entry and entry.get('reading'):
            storage.update_thread_history_entry(ask['situation_id'], {'message_id': ask['read_from']},
                                                {'reading': {**entry['reading'], 'disputed': True}})
    _touch(ask.get('situation_kind'), ask.get('situation_id'))
    return {'status': 'success', 'message': "Noted. Back to waiting on them; read the reply yourself."}
```

- [ ] **Step 4: Run the tests**

Run: `..\venv\Scripts\python.exe tests\test_reply_reading.py` and `..\venv\Scripts\python.exe tools\test.py asks`
Expected: `10/10`; `test_asks*` green (nothing existing changes).

- [ ] **Step 5: Commit**

Bump `config.yaml` to `2.499.333`.

```bash
git add services/asks.py tests/test_reply_reading.py config.yaml
git commit -m "feat(replies): a reading records yes or no on the ask and never applies; unread puts it back to waiting (v2.499.333)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

### Task 8: One DM to the owner, through the watcher's quiet hours

**Files:**
- Modify: `services/replies.py` (`_notify`, `flush_pending_dms`)
- Modify: `services/watchers.py` (`run_watchers` calls `replies.flush_pending_dms` inside the window)
- Test: `tests/test_reply_reading.py`

**Interfaces:**
- Produces:
  - `replies.dm_line(thread, entry, reading, next_label) -> str`.
  - `replies._notify(thread, entry, reading, now=None)` — posts at once inside `[QUIET_END_HOUR, QUIET_START_HOUR)`, else marks the entry `dm_pending: True`.
  - `replies.flush_pending_dms(now=None) -> int` — posts every pending entry on open threads, clears the mark; returns how many were posted.
  - `replies._post` (stub point) wrapping `agent_tools_v2._post_chat_message`.

- [ ] **Step 1: Write the failing tests** (append)

```python
SENT = []


def _capture_post():
    def p(dm, argyle, body, card=None):
        SENT.append({'dm': dm, 'body': body})
        return {'id': f'm{len(SENT)}'}
    replies._post = p


def scenario_one_dm_to_the_owner_inside_the_window():
    _reset()
    SENT.clear(); _capture_post()
    # replies._now is the module's one clock; pin it inside the window.
    replies._now = lambda: datetime.datetime.now().replace(hour=12, minute=0)
    try:
        replies._pool_call = _fake_pool({'answer': 'yes', 'summary': 'Friday 9am works'})
        tid = _thread()
        threads.send_drafted(tid, 'S', 'B', 'ops@pestco.example', who='mom')
        _reply(tid)
        replies.read(tid, '<m1@pestco>')
        check(len(SENT) == 1, f"exactly one DM went: {SENT}")
        body = SENT[0]['body']
        check("Pest Co replied on 'Pest control'" in body and 'Friday 9am works' in body and '→' in body, f"the line: {body}")
        # storage.get_or_create_dm keys the channel by the sorted member pair.
        check('mom' in (SENT[0]['dm'].get('dm_key') or ''), f"to the owner: {SENT[0]['dm']}")
        h = storage.get_thread(tid)['history'][-1]
        check(not h.get('dm_pending'), "nothing pending")
    finally:
        replies._now = datetime.datetime.now


def scenario_dm_outside_quiet_hours_is_deferred_once():
    _reset()
    SENT.clear(); _capture_post()
    replies._pool_call = _fake_pool({'answer': 'no', 'summary': 'cannot do Friday'})
    tid = _thread()
    threads.send_drafted(tid, 'S', 'B', 'ops@pestco.example', who='mom')
    _reply(tid, mid='<late>')
    late = datetime.datetime.now().replace(hour=23, minute=0)
    thread = storage.get_thread(tid)
    entry = [x for x in thread['history'] if x.get('message_id') == '<late>'][0]
    replies._notify(thread, entry, {'answer': 'no', 'summary': 'cannot do Friday', 'ts': time.time(), 'source': 'argyle'}, now=late)
    check(not SENT, "nothing posted at 23:00")
    h = [x for x in storage.get_thread(tid)['history'] if x.get('message_id') == '<late>'][0]
    check(h.get('dm_pending') is True, "marked pending")
    morning = datetime.datetime.now().replace(hour=9, minute=0)
    n = replies.flush_pending_dms(now=morning)
    check(n == 1 and len(SENT) == 1 and 'cannot do Friday' in SENT[0]['body'], f"posted once by the morning sweep: {SENT}")
    check(replies.flush_pending_dms(now=morning) == 0 and len(SENT) == 1, "a second sweep posts nothing")
    # A pending DM on a thread that closes overnight is never sent.
    _reply(tid, mid='<late2>')
    thread = storage.get_thread(tid)
    entry = [x for x in thread['history'] if x.get('message_id') == '<late2>'][0]
    replies._notify(thread, entry, None, now=late)
    threads.close(tid, 'done', who='mom')
    check(replies.flush_pending_dms(now=morning) == 0 and len(SENT) == 1, "nothing for a closed thread")


def scenario_no_reading_still_tells_the_owner_to_read_it():
    _reset()
    SENT.clear(); _capture_post()
    storage.get_settings = lambda: {'thread_stall_days': 7}      # no key: no reading
    tid = _thread()
    threads.send_drafted(tid, 'S', 'B', 'ops@pestco.example', who='mom')
    _reply(tid, mid='<nk>', text='We can do Friday at 9.\nThanks')
    replies.read(tid, '<nk>')
    check(len(SENT) == 1 and 'read it' in SENT[0]['body'], f"'a reply came in — read it': {SENT}")


def scenario_sweep_flushes_pending_dms_inside_the_window():
    from services import watchers
    src = open('services/watchers.py', encoding='utf-8').read()
    after_gate = src.split('if not (QUIET_END_HOUR <= now.hour < QUIET_START_HOUR):')[1]
    check('flush_pending_dms' in after_gate, "run_watchers flushes pending reply DMs after the quiet-hours gate")


SCENARIOS += [scenario_one_dm_to_the_owner_inside_the_window, scenario_dm_outside_quiet_hours_is_deferred_once,
              scenario_no_reading_still_tells_the_owner_to_read_it, scenario_sweep_flushes_pending_dms_inside_the_window]
```

`replies._now()` is the one clock the module reads; `read()` passes `now=_now()` to `_notify`, so a test can pin the hour.

- [ ] **Step 2: Run to verify they fail**

Run: `..\venv\Scripts\python.exe tests\test_reply_reading.py`
Expected: FAIL with `AttributeError: module 'services.replies' has no attribute '_post'`.

- [ ] **Step 3: Replace the `_notify` stub in `services/replies.py`** and add the clock, the line and the flush:

```python
def _now() -> datetime.datetime:
    return datetime.datetime.now()


def _post(dm: dict, argyle: dict, body: str, card: dict = None) -> dict:
    from services.agent_tools_v2 import _post_chat_message
    return _post_chat_message(dm, argyle, body, card=card)


def _in_window(now: datetime.datetime) -> bool:
    from services.watchers import QUIET_END_HOUR, QUIET_START_HOUR
    return QUIET_END_HOUR <= now.hour < QUIET_START_HOUR


def dm_line(thread: dict, entry: dict, reading: Optional[dict], next_label: str = '') -> str:
    who = thread.get('counterparty_name') or (entry.get('text') or '').split(':')[0].replace('Received from ', '') or 'They'
    title = thread.get('title') or 'a thread'
    if not reading:
        return f"{who} replied on '{title}' — read it."
    line = f"{who} replied on '{title}': {reading.get('summary') or reading.get('answer')}"
    return line + (f" → {next_label}" if next_label else '') + '.'


def _recipients(thread: dict) -> list:
    owner = storage.get_member(thread.get('owner_member_id') or '') if thread.get('owner_member_id') else None
    if owner and (owner.get('status') or 'active') == 'active':
        return [owner]
    return [m for m in storage.get_all_members() if m.get('role') == 'parent' and not m.get('system')]


def _send(thread: dict, entry: dict, reading: Optional[dict]) -> bool:
    from services import situations as _sit
    s = _sit.view('thread', thread['id'], _sit.parent_of_record())
    nxt = ((s or {}).get('next_step') or {}).get('label') or ''
    body = dm_line(thread, entry, reading, nxt)
    argyle = storage.ensure_argyle_member()
    sent = False
    for m in _recipients(thread):
        try:
            _post(storage.get_or_create_dm(argyle['id'], m['id']), argyle, body)
            sent = True
        except Exception as e:
            logger.warning(f"[replies] DM to {m.get('name')} failed: {e}")
    return sent


def _notify(thread: dict, entry: dict, reading: Optional[dict], now: datetime.datetime = None) -> None:
    """One message to the owner (the parents when none), at once inside the
    watcher's waking window, else deferred to the first in-window sweep.
    Never for a closed thread."""
    if thread.get('state') in ('done', 'dropped'):
        return
    now = now or _now()
    if _in_window(now) and _send(thread, entry, reading):
        storage.update_thread_history_entry(thread['id'], {'message_id': entry.get('message_id')}, {'dm_pending': False})
        return
    storage.update_thread_history_entry(thread['id'], {'message_id': entry.get('message_id')}, {'dm_pending': True})


def flush_pending_dms(now: datetime.datetime = None) -> int:
    """Called by run_watchers inside the window: post every deferred reply
    DM on an open thread, once. A failed post keeps the mark for next time."""
    now = now or _now()
    if not _in_window(now):
        return 0
    posted = 0
    for thread in storage.get_threads(include_closed=False):
        for h in list(thread.get('history') or []):
            if h.get('kind') == 'received' and h.get('dm_pending'):
                if _send(thread, h, h.get('reading')):
                    storage.update_thread_history_entry(thread['id'], {'message_id': h.get('message_id')}, {'dm_pending': False})
                    posted += 1
    return posted
```

In `read()`, pass the clock: `_notify(thread, entry, reading, now=_now())` on both calls (the no-reading path too). Note `_notify` reads the thread row BEFORE the reading was stored only for its id/title/owner, which is fine.

- [ ] **Step 4: Hook the sweep** — in `services/watchers.py` `run_watchers`, immediately after

```python
    if not (QUIET_END_HOUR <= now.hour < QUIET_START_HOUR):
        return 0
```

add:

```python
    # Reply DMs deferred through the night (services/replies.py) go out on
    # the first in-window sweep, once each.
    try:
        from services import replies as _replies
        _replies.flush_pending_dms(now)
    except Exception as e:
        print(f"[watchers] reply DM flush failed: {e}")
```

- [ ] **Step 5: Check the DM channel's key** — `storage.get_or_create_dm` builds `dm_key = ':'.join(sorted([a, b]))`; confirm the returned channel dict carries `dm_key` (read the function). If it is stored under another name, change the one `dm_key` check in `scenario_one_dm_to_the_owner_inside_the_window` to that name.

- [ ] **Step 6: Run the tests**

Run: `..\venv\Scripts\python.exe tests\test_reply_reading.py` and `..\venv\Scripts\python.exe tools\test.py watchers`
Expected: `14/14`; `test_watchers` green (the flush is a no-op with no pending entries).

- [ ] **Step 7: Commit**

Bump `config.yaml` to `2.499.334`.

```bash
git add services/replies.py services/watchers.py tests/test_reply_reading.py config.yaml
git commit -m "feat(replies): one DM to the thread's owner per reply, deferred through quiet hours and flushed by the sweep (v2.499.334)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

### Task 9: The reading becomes the next step; the `unread` verb on the card and in conversation

**Files:**
- Modify: `services/situations.py` (`_options_thread`, `_run` for `unread`)
- Modify: `static/situations.js` (`askLine` reading text; `act` pre-fills an advance)
- Test: `tests/test_reply_reading.py`, `tests/test_situation_tools.py`

**Interfaces:**
- Consumes: `asks.unread`, the `reading` on a `received` history entry.
- Produces: `_options_thread` emits, when the newest non-drafted history entry is `received`: `advance:confirm` (yes), `draft:reply` (question), `advance:read` (info, unclear, no reading); and `unread:<ask_id>` for every ask with `answered_by == 'argyle'` in `yes`/`no`. `situations.act(..., 'unread', option_id='unread:<ask_id>')` runs `asks.unread`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_reply_reading.py`)

```python
def _next(tid):
    return situations.view('thread', tid, MOM)['next_step']


def scenario_next_step_follows_the_reading():
    _reset()
    tid = _thread()
    res = threads.send_drafted(tid, 'S', 'B', 'ops@pestco.example', who='mom')
    replies._pool_call = _fake_pool({'answer': 'yes', 'summary': 'Friday 9am works'})
    _reply(tid, mid='<1>'); replies.read(tid, '<1>')
    n = _next(tid)
    check(n['verb'] == 'advance' and n['id'] == 'advance:confirm' and n['label'] == 'Confirm with Pest Co: Friday 9am works'
          and n['payload'].get('next_action') == 'Confirm with Pest Co: Friday 9am works', f"yes → confirm: {n}")
    opts = situations.view('thread', tid, MOM)['options']
    un = [o for o in opts if o['verb'] == 'unread']
    check(len(un) == 1 and un[0]['id'] == f"unread:{res['ask_id']}" and un[0]['label'] == 'Argyle got it wrong', f"the revert is on the card: {opts}")
    out = situations.act('thread', tid, 'unread', option_id=un[0]['id'], actor=MOM)
    check(out['status'] == 'success' and storage.get_ask(res['ask_id'])['state'] == 'sent', f"unread through act: {out}")
    n = _next(tid)
    check(n['id'] == 'advance:read' and n['label'].startswith('Read their reply'), f"after unread: read it yourself: {n}")
    check(not [o for o in situations.view('thread', tid, MOM)['options'] if o['verb'] == 'unread'], "nothing left to revert")
    replies._pool_call = _fake_pool({'answer': 'question', 'summary': 'which Friday?'})
    threads.send_drafted(tid, 'S2', 'B', 'ops@pestco.example', who='mom')
    _reply(tid, mid='<2>'); replies.read(tid, '<2>')
    n = _next(tid)
    check(n['verb'] == 'draft' and n['id'] == 'draft:reply' and n['label'] == 'Reply: which Friday?'
          and n['payload'].get('text') == 'which Friday?', f"question → reply: {n}")
    replies._pool_call = _fake_pool({'answer': 'no', 'summary': 'cannot do Friday'})
    threads.send_drafted(tid, 'S3', 'B', 'ops@pestco.example', who='mom')
    _reply(tid, mid='<3>'); replies.read(tid, '<3>')
    n = _next(tid)
    check(n['id'] not in ('advance:confirm', 'draft:reply', 'advance:read'), f"no → the ordinary options: {n}")
    storage.get_settings = lambda: {'thread_stall_days': 7}
    threads.send_drafted(tid, 'S4', 'B', 'ops@pestco.example', who='mom')
    _reply(tid, mid='<4>', text='We can do Friday at 9.\nThanks, Pest Co')
    replies.read(tid, '<4>')
    n = _next(tid)
    check(n['id'] == 'advance:read' and n['label'] == 'Read their reply: We can do Friday at 9.', f"no reading → the first line: {n}")
    threads.note(tid, 'called them', who='mom')
    n = _next(tid)
    check(n['id'] != 'advance:read', f"once the person acts the ordinary options return: {n}")


SCENARIOS += [scenario_next_step_follows_the_reading]
```

- [ ] **Step 2: Run to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_reply_reading.py`
Expected: FAIL at `yes → confirm` (the next step is still "Set the next step" / "Draft a message").

- [ ] **Step 3: `_options_thread` reads the reading** — replace the function in `services/situations.py`:

```python
def _reply_option(row: dict):
    """The highlighted move after a counterparty's reply (spec 2026-10-10
    §2), while that reply is the newest real thing on the thread. Deterministic:
    the reading, when there is one, else the mail's first line."""
    history = [h for h in (row.get('history') or []) if h.get('kind') != 'drafted']
    if not history or history[-1].get('kind') != 'received':
        return None
    h = history[-1]
    who = row.get('counterparty_name') or 'them'
    reading = h.get('reading') or {}
    answer = reading.get('answer') if not reading.get('disputed') else None
    summary = (reading.get('summary') or '').strip()
    if answer == 'yes':
        label = f"Confirm with {who}: {summary}" if summary else f"Confirm with {who}"
        return _opt('advance', label, {'next_action': label}, 'confirm')
    if answer == 'no':
        return None
    if answer == 'question':
        return _opt('draft', f"Reply: {summary}" if summary else 'Reply to them', {'text': summary}, 'reply')
    body = (h.get('text') or '')
    first = next((ln.strip() for ln in body.split('\n')[2:] if ln.strip()), '') if '\n\n' in body else ''
    hint = summary or first
    label = f"Read their reply: {hint}" if hint else 'Read their reply'
    return _opt('advance', label, {'next_action': label}, 'read')


def _options_thread(row: dict) -> list:
    from services import threads as _th
    out = []
    lead = _reply_option(row)
    if lead:
        out.append(lead)
    stalled = _th.is_stalled(row)
    if stalled == 'overdue' or not row.get('next_action'):
        out.append(_opt('advance', 'Set the next step', {}))
    out.append(_opt('draft', 'Draft a message', {}))
    if stalled != 'overdue' and row.get('next_action'):
        out.append(_opt('advance', 'Change the next step', {}))
    out.append(_opt('research', 'Look something up', {}))
    from services import asks as _asks
    for a in _asks.asks_for('thread', row.get('id'), row):
        if a.get('answered_by') == 'argyle' and a.get('state') in ('yes', 'no'):
            out.append(_opt('unread', 'Argyle got it wrong', {'ask_id': a['id']}, a['id']))
    out.append(_opt('close', 'Done with it', {'state': 'done'}, 'done'))
    return out + _tail('thread', row)
```

The `received` entry's `text` is `Received from {addr}: {subject}\n\n{body}` (see `threads.match_inbound`), so the first line of the mail is the first non-empty line after the blank line.

- [ ] **Step 4: `act` runs `unread`** — in `_run`, before `if verb == 'ask':`:

```python
    if verb == 'unread':
        from services import asks as _asks
        return _asks.unread(p.get('ask_id'), actor)
```

`VERBS` already holds `'unread'` (Task 3). The `advance` branch in `_run` requires `next_action`; the pre-filled payload carries it, and `act`'s free-payload merge only overrides when the client sends a value.

- [ ] **Step 5: The card** — `static/situations.js`:

In `askLine`, replace `${esc(askState(a))}` with `${esc(a.answered_by === 'argyle' ? readLine(a) : askState(a))}` and add above `askLine`:

```javascript
  function readLine(a) {
    const base = a.state === 'yes' ? 'Argyle read their reply as yes' : 'Argyle read their reply as no';
    return a.read_summary ? `${base} — "${a.read_summary}"` : base;
  }
```

In `act`, pre-fill from the option so a reading-built advance or draft needs no retyping: change the two `promptInput` calls to

```javascript
      const text = window.promptInput ? await promptInput(ask, option.payload.next_action || option.payload.text || '') : null;
```

(keep the rest of that block as is). `VERB_LABELS` already has `'unread': 'Argyle got it wrong'` from Task 3. No Tailwind change.

- [ ] **Step 6: Run the tests**

Run: `..\venv\Scripts\python.exe tests\test_reply_reading.py` and `..\venv\Scripts\python.exe tools\test.py situation threads`
Expected: `15/15`; `test_situation_tools.scenario_parity_both_ways` green with `unread` in all three places; `test_situations` green (a thread with no `received` entry keeps its old options in the same order).

- [ ] **Step 7: Commit**

Bump `config.yaml` to `2.499.335`.

```bash
git add services/situations.py static/situations.js tests/test_reply_reading.py config.yaml
git commit -m "feat(replies): the reading is the thread's next step, and 'Argyle got it wrong' is a verb on the card and in conversation (v2.499.335)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

### Task 10: Acceptance scenarios, end to end

**Files:**
- Test: `tests/test_triage.py` (scenarios 1 and 2), `tests/test_reply_reading.py` (scenarios 3 and 4)

**Interfaces:** consumes everything above; produces nothing new. If a scenario fails, the fix belongs in the task that owns the code, with its test.

- [ ] **Step 1: Append to `tests/test_triage.py`**

```python
def scenario_e2e_voice_ask_round_trip():
    """Spec acceptance 1: voice, no identity: triage → text Sarah → sent it →
    she said yes → applied once → the finding retires by absence."""
    _reset()
    storage.add_assist_contact({'id': 'c1', 'name': 'Sarah', 'kinds': ['driving'], 'active': True})
    start = (NOON + datetime.timedelta(days=2)).replace(hour=16)
    storage.set_cached_schedule({'events': [{'id': 'ev1', 'title': 'Soccer', 'start': start.isoformat(),
                                             'end': start.isoformat()}], 'assignments': {}, 'unassigned': ['ev1']})
    fid = storage.add_finding({'identity': 'unassigned:ev1', 'kind': 'unassigned', 'severity': 'decide',
                               'line': 'No driver yet: Soccer', 'subject_type': 'event', 'subject_id': 'ev1',
                               'due_at': start.timestamp(), 'state': 'open', 'fingerprint': f"ev1|{start.timestamp()}"})
    turn = lambda call, text: _with_gemma(_fake_gemma(call), lambda: agent_router.process_agent_request(text, focus_key='voice:7'))
    res = turn({'name': 'next_situation', 'arguments': {}}, 'what needs my attention')
    check(res['message'].startswith('No driver yet: Soccer.'), f"turn 1: {res}")
    res = turn({'name': 'start_ask', 'arguments': {'to_name': 'Sarah', 'what': '', 'channel': 'text'}}, 'text Sarah and ask her')
    a = storage.get_asks(situation_kind='finding', situation_id=fid)[0]
    check(a['state'] == 'drafted' and a['asked_by'] == 'mom' and (a['unlocks'] or {}).get('action_type') == 'assist_assignment', f"turn 2: {a}")
    res = turn({'name': 'mark_ask_sent', 'arguments': {}}, 'sent it')
    check(storage.get_ask(a['id'])['state'] == 'sent', f"turn 3: {res}")
    res = turn({'name': 'answer_ask', 'arguments': {'answer': 'yes'}}, 'she said yes')
    a = storage.get_ask(a['id'])
    check(a['state'] == 'yes' and a['outcome'] == 'applied', f"turn 4: {a}")
    res = turn({'name': 'answer_ask', 'arguments': {'answer': 'yes'}}, 'she said yes')
    check(storage.get_ask(a['id'])['outcome'] == 'applied' and res['status'] != 'error', "a duplicate yes is a no-op")
    check(storage.get_ask(a['id'])['applied_at'] is not None, "applied once, stamped once")
    from services import findings as _f
    _f.reconcile([], {'unassigned'}, time.time())
    check(storage.get_finding(fid)['state'] != 'open', "absence on the next sweep retires the finding")
    check(triage.get_focus('voice:7') is None, "and the focus is gone with it")


def scenario_e2e_next_walks_the_list_without_repeating_a_closed_row():
    """Spec acceptance 2."""
    _reset()
    a = threads.create('A overdue', owner_member_id='mom', next_action='x',
                       next_action_at=(NOON - datetime.timedelta(days=1)).date().isoformat(), created_by='mom')
    b = threads.create('B quiet', owner_member_id='mom', created_by='mom')
    storage.update_thread(b, {'created_at': time.time() - 9 * 86400})
    c = threads.create('C quiet too', owner_member_id='mom', created_by='mom')
    storage.update_thread(c, {'created_at': time.time() - 10 * 86400})
    first = tools.next_situation(acting_member=MOM, focus_key='conv:3')['situation']['id']
    check(first == a, "tier 0 first")
    threads.close(b, 'done', who='mom')
    second = tools.next_situation(skip_current=True, acting_member=MOM, focus_key='conv:3')['situation']['id']
    check(second == c, f"B closed between turns is skipped: got {second}")
    res = tools.next_situation(skip_current=True, acting_member=MOM, focus_key='conv:3')
    check(res['situation'] is None, "then the list ends")


SCENARIOS += [scenario_e2e_voice_ask_round_trip, scenario_e2e_next_walks_the_list_without_repeating_a_closed_row]
```

- [ ] **Step 2: Append to `tests/test_reply_reading.py`**

```python
def scenario_e2e_thread_mail_reply_reading_and_revert():
    """Spec acceptance 3."""
    _reset()
    SENT.clear(); _capture_post()
    replies._now = lambda: datetime.datetime.now().replace(hour=12, minute=0)
    try:
        notes = []
        situations._pool_call = lambda tier, key, system, prompt, **kw: (notes.append(prompt) or {'status_note': 'They can do Friday.', 'options': []})
        tid = _thread()
        res = threads.send_drafted(tid, 'Can you come Friday?', 'B', 'ops@pestco.example', who='mom', intent='come Friday morning')
        check(storage.get_ask(res['ask_id'])['state'] == 'sent', "sent")
        replies._pool_call = _fake_pool({'answer': 'yes', 'summary': 'Friday 9am works'})
        _reply(tid); replies.read(tid, '<m1@pestco>')
        situations.flush_refreshes()
        a = storage.get_ask(res['ask_id'])
        check(a['state'] == 'yes' and a['outcome'] == 'manual', "yes, manual")
        check(_next(tid)['label'] == 'Confirm with Pest Co: Friday 9am works', "next step")
        check(len(SENT) == 1 and 'Confirm with Pest Co' in SENT[0]['body'], f"one DM naming the next step: {SENT}")
        check(storage.get_thread(tid).get('status_note') == 'They can do Friday.', "the note refreshed")
        un = [o for o in situations.view('thread', tid, MOM)['options'] if o['verb'] == 'unread'][0]
        situations.act('thread', tid, 'unread', option_id=un['id'], actor=MOM)
        check(storage.get_ask(res['ask_id'])['state'] == 'sent' and _next(tid)['id'] == 'advance:read', "reverted")
        h = [x for x in storage.get_thread(tid)['history'] if x.get('message_id') == '<m1@pestco>'][0]
        check(h['reading']['disputed'] is True, "the reading is kept as disputed")
    finally:
        replies._now = datetime.datetime.now


def scenario_e2e_capped_reply_is_filed_unread_and_not_read_twice():
    """Spec acceptance 4."""
    _reset()
    SENT.clear(); _capture_post()
    replies._now = lambda: datetime.datetime.now().replace(hour=12, minute=0)
    try:
        storage.get_settings = lambda: {'llm_gemini_api_key': 'k', 'thread_stall_days': 7, 'reply_cap_reads': 0}
        replies._pool_call = _fake_pool({'answer': 'yes', 'summary': 'x'})
        tid = _thread()
        res = threads.send_drafted(tid, 'S', 'B', 'ops@pestco.example', who='mom')
        from services import email_ingest
        msg = {'from': 'ops@pestco.example', 'subject': 'Re: S', 'text': 'Friday at 9 works.\nThanks', 'message_id': '<cap>'}
        email_ingest._match_thread(msg)
        check(not CALLS, "capped: no call")
        check(storage.get_ask(res['ask_id'])['state'] == 'sent', "the ask waits")
        check(_next(tid)['label'] == 'Read their reply: Friday at 9 works.', f"first line: {_next(tid)}")
        check(len(SENT) == 1 and 'read it' in SENT[0]['body'], "the DM says a reply came in")
        email_ingest._match_thread(msg)
        check(not CALLS and len(SENT) == 1 and len([h for h in storage.get_thread(tid)['history'] if h['kind'] == 'received']) == 1,
              "the next poll does not read or file it again")
    finally:
        replies._now = datetime.datetime.now


SCENARIOS += [scenario_e2e_thread_mail_reply_reading_and_revert, scenario_e2e_capped_reply_is_filed_unread_and_not_read_twice]
```

- [ ] **Step 3: Run both files**

Run: `..\venv\Scripts\python.exe tests\test_triage.py` and `..\venv\Scripts\python.exe tests\test_reply_reading.py`
Expected: all scenarios pass. A failure is a defect in an earlier task: fix it there (and add the pin there), not by weakening the scenario.

- [ ] **Step 4: Commit**

Bump `config.yaml` to `2.499.336`.

```bash
git add tests/test_triage.py tests/test_reply_reading.py config.yaml
git commit -m "test(triage,replies): the four acceptance scenarios end to end (v2.499.336)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

### Task 11: The reading on /threads and the PWA House card, in a real browser

**Files:**
- Modify: `templates/components/threads_page.html` (the history timeline shows the reading beside a `received` entry)
- Test: `tests/test_reply_reading_live.py` (new)

**Interfaces:** consumes the `reading` on a history entry and the `answered_by`/`read_summary` on an ask (both already in `GET /api/situations` and `GET /api/threads`).

- [ ] **Step 1: Write the failing live test**

```python
# tests/test_reply_reading_live.py
"""The reading line and 'Argyle got it wrong' on /threads, and the timeline
shows what Argyle read beside the reply."""
import datetime
import os
import sys
import tempfile
import time

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='reply_reading_live_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_app import live_app
from services import storage


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def seed():
    storage.update_settings({'llm_gemini_api_key': ''})
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent', 'color_code': '#6366f1'})
    from services import threads, mailer, replies
    mailer.send = lambda to, subject, body, settings=None: {'sent': True}
    mailer.configured = lambda *a, **k: True
    replies._post = lambda *a, **k: {'id': 'x'}
    tid = threads.create('Pest control', owner_member_id='mom', counterparty_name='Pest Co',
                         counterparty_email='ops@pestco.example', created_by='mom')
    res = threads.send_drafted(tid, 'Can you come Friday?', 'B', 'ops@pestco.example', who='mom', intent='come Friday morning')
    threads.match_inbound('ops@pestco.example', 'Re: Can you come Friday?', 'Friday at 9 works.', message_id='<m1>')
    from services import asks
    asks.record_reading(res['ask_id'], 'yes', '<m1>', summary='Friday 9am works')
    storage.update_thread_history_entry(tid, {'message_id': '<m1>'},
                                        {'reading': {'answer': 'yes', 'summary': 'Friday 9am works', 'ts': time.time(), 'source': 'argyle'}})


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        b = served.browser(color_scheme='dark')
        with b as page:
            page.goto(served.url('work?tab=threads'), wait_until='networkidle')
            page.wait_for_selector('.situation-card', timeout=15000)
            card = page.locator('.situation-card').first
            line = card.locator('[data-ask-line]').first.inner_text()
            check('Argyle read their reply as yes' in line and 'Friday 9am works' in line, f"the reading line: {line}")
            check(card.locator('button', has_text='Argyle got it wrong').count() == 1, "the revert button is on the card")
            check(card.locator('.sit-next button').first.inner_text().startswith('Confirm with Pest Co'), "the next step is the confirm")
            page.locator('.situation-card details summary').first.click()
            page.wait_for_timeout(300)
            tl = card.locator('.thread-reading').first.inner_text()
            check('yes' in tl and 'Friday 9am works' in tl, f"the timeline shows the reading: {tl}")
            card.locator('button', has_text='Argyle got it wrong').first.click()
            page.wait_for_timeout(1500)
            line = page.locator('.situation-card [data-ask-line]').first.inner_text()
            check('waiting' in line and 'Argyle read' not in line, f"after the tap, waiting again: {line}")
            check(page.locator('.situation-card .sit-next button').first.inner_text().startswith('Read their reply'), "next step: read it")
    finally:
        served.stop()


if __name__ == '__main__':
    main()
    print('PASS test_reply_reading_live')
```

Mirror the `served.stop()`/`browser()` idiom from `tests/test_threads_page_live.py` exactly if it differs from the above (read that file first).

- [ ] **Step 2: Run to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_reply_reading_live.py`
Expected: FAIL at "the timeline shows the reading" (no `.thread-reading` element yet). The first three checks pass from Task 9.

- [ ] **Step 3: The timeline** — in `templates/components/threads_page.html` inside the history `x-for` (line 131–138), after the `<span x-text="h.text"></span>` line add:

```html
                                                    <span x-show="h.reading" class="thread-reading block pl-3 text-gray-400 italic"
                                                          x-text="h.reading ? ('Argyle read it as ' + h.reading.answer + (h.reading.summary ? ' — \u201c' + h.reading.summary + '\u201d' : '') + (h.reading.disputed ? ' (disputed)' : '')) : ''"></span>
```

Run `..\venv\Scripts\python.exe tools\build_tailwind.py`.

- [ ] **Step 4: Run the live test and the related tests**

Run: `..\venv\Scripts\python.exe tests\test_reply_reading_live.py` then `..\venv\Scripts\python.exe tools\test.py threads_page_live situations_builder_live tailwind_build`
Expected: PASS; the existing page live tests green.

- [ ] **Step 5: Commit**

Bump `config.yaml` to `2.499.337`.

```bash
git add templates/components/threads_page.html static/tailwind.css tests/test_reply_reading_live.py config.yaml
git commit -m "feat(threads): the timeline shows what Argyle read beside the reply; the reading line and revert pinned in a real browser (v2.499.337)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

### Task 12: Capabilities, roadmap, memory

**Files:**
- Modify: `system_capabilities.md` (the "Current through" line and a new entry at the top, house style)
- Modify: `docs/roadmap.md` (one line under the Needs-you entry)
- Modify: `C:\Users\ffejn\.claude\projects\e--repositories-Chauffeur\memory\agentic-layer-field-feedback.md` (sub-project 3 shipped, NOT device-verified)

- [ ] **Step 1: `system_capabilities.md`** — bump "Current through v2.499.337 (2026-10-10)" and add, above the v2.499.323 entry, in the same bold-lead paragraph-plus-bullets style:

```markdown
**Triage and replies: the one thing, held in conversation; voice as the parent of record; a vendor's reply read once (v2.499.327–.337; `services/triage.py`, `services/replies.py`, `services/agent_tools_v2.py` `next_situation` + focus-aware situation tools, `services/agent_router.py` `focus_key`/FOCUS line/parent-of-record dispatch, `main.py` three entry points + `_approver_of_record`, `services/asks.py` `record_sent`/`record_reading`/`unread`, `services/threads.py` `send_drafted(intent)`/`match_inbound(message_id)`, `services/email_ingest.py` `_match_thread`, `services/situations.py` `parent_of_record`/`list_situations(spoken)`/`_reply_option`/`unread`, `services/watchers.py` flush, `static/situations.js`, `templates/components/threads_page.html`, `templates/components/mind_page.html`; spec `docs/superpowers/specs/2026-10-10-triage-and-replies-design.md`, plan `docs/superpowers/plans/2026-10-10-triage-and-replies.md`; tests `test_triage.py`, `test_reply_reading.py`, `test_reply_reading_live.py`).** Sub-project 3 of the agentic-layer plan.

- **`next_situation`.** "What needs my attention?" answers with ONE situation as a deterministic sentence (title · Argyle's note when hers · "Next: {step}" · the asks clause), terminal (no concluding LLM round). `triage.triage_rank` orders across the four kinds: tier 0 overdue or due within 24 h (decide findings by due, a thread whose next action passed, a mission waiting on an answer); 1 decide findings, stalled threads, missions with a pending proposal; 2 approve; 3 insights by confidence; 4 fyi. The lanes keep `situations.rank`.
- **Focus.** One app-state map `triage_focus` keyed `conv:<id>` (widget), `voice:<id>` (HA Assist), `channel:<id>` (Argyle DM); set by `next_situation` and by naming a situation; `get_focus` drops a settled, snoozed or day-old one. The router injects one FOCUS line when a live focus exists; `explain_situation`/`act_on_situation`/`start_ask` take no ref for it; `answer_ask`/`mark_ask_sent` take no ask id and resolve the focus situation's one live ask, refusing with names when there are two. "Next" walks the ranked list from the cursor and skips rows that closed between turns. No `conversation_id` → no focus; the sentence ends with the title.
- **Voice is the parent of record.** In the router's dispatch for the situation tools only, a caller with no identity (not driver mode, not propose-only) acts as `situations.parent_of_record()`, the member `_approver_of_record` already nominates; asks and DMs go out as that parent. A substituted actor is a room: `list_situations` and `next_situation` drop sensitive insights (`list_situations(spoken=True)`; `next_situation` always). A child via @argyle is refused as before.
- **Thread sends are ledger rows.** `send_drafted` records a `sent` ask (`sent_via: household`, `what` = the draft's intent else the subject, no `unlocks`, no draft call, no extra refresh); the card reads "Asked Pest Co by Email — waiting".
- **A reply is read once.** `match_inbound` dedupes by `message_id` and stores it on the `received` entry; `email_ingest._match_thread` then runs `replies.read`: one `interactive` call (20 s, `reply_cap_reads` default 40/day on the Mind page, counted with `_bump_call`), strict JSON `{answer: yes|no|question|info|unclear, summary ≤20 words}`, stored on the entry as `reading`, `rev` bumped so the note refreshes. A clear yes/no on the thread's newest live household ask is RECORDED (`asks.record_reading`: `answered_by: argyle`, `read_from`, `read_summary`; a yes is `outcome: manual`) and never applied; a human answer already recorded stands. No key, cap or failure: no reading, nothing invented.
- **Next step from the reading** (`_reply_option`, read time, while the reply is the newest real history entry): yes → `advance:confirm` "Confirm with {counterparty}: {summary}" pre-filled; question → `draft:reply` "Reply: {summary}"; info/unclear/none → `advance:read` "Read their reply: {summary | first line}"; no → the ordinary options. One DM to the owner (parents when none): "{counterparty} replied on '{title}': {summary} → {next step}" / "— read it."; posted at once inside the watcher window, else `dm_pending` and flushed once by the first in-window sweep; never on a closed thread.
- **Argyle got it wrong.** New verb `unread` (card button and `act_on_situation`): the reading-answered ask returns to `sent`, the reading stays on the history as `disputed`, the next step becomes "Read their reply". Refused for an answer a person gave. The /threads timeline shows "Argyle read it as …" beside the reply.
- **Not in this sub-project:** typed replies under a Chauffeur ask card, forwarded replies for personal asks, `In-Reply-To` matching, voice identity beyond the parent of record, applying anything from a reading, a proactive morning triage.
- **Not device-verified.**
```

- [ ] **Step 2: `docs/roadmap.md`** — under the Needs-you entry's "Build 2 SHIPPED" lines add:

```markdown
  Sub-project 3 SHIPPED v2.499.327–.337 (2026-10-10): "what needs my
  attention?" is one spoken situation held as the conversation's focus,
  voice acts as the parent of record, and a vendor's reply on a thread is
  read once and recorded, never applied. Spec:
  `docs/superpowers/specs/2026-10-10-triage-and-replies-design.md`.
```

- [ ] **Step 3: Memory** — in `agentic-layer-field-feedback.md`, replace the "(3) triage + replies — spec … awaiting the user's spec review, then writing-plans." clause with: "(3) triage + replies SHIPPED v2.499.327–.337 (2026-10-10), NOT device-verified; plan `docs/superpowers/plans/2026-10-10-triage-and-replies.md`. Declined for this sub-project and still open: typed replies under a Chauffeur ask card, forwarded replies for personal asks." Keep the locked decisions sentence.

- [ ] **Step 4: Run the gate once**

Run: `..\venv\Scripts\python.exe tools\test.py triage reply situation threads email_ingest agent_v2_bridge watchers mind_endpoints tailwind_build`
Expected: all green.

- [ ] **Step 5: Commit**

Bump `config.yaml` to `2.499.338`.

```bash
git add system_capabilities.md docs/roadmap.md config.yaml
git commit -m "docs(triage,replies): sub-project 3 wrap-up - capabilities entry and roadmap line (v2.499.338)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

## Self-review notes

- **Spec coverage.** §1 `next_situation` (Task 3), rank (Task 1), focus (Tasks 2–4), focus-aware tools (Task 3), voice as parent of record (Task 4), sensitive never spoken (Tasks 1, 4), prompt line only (Task 4). §2 thread sends as rows (Task 5), one reading (Task 6), record never apply (Task 7), next step (Task 9), one DM (Task 8), unread (Tasks 7, 9). §3 surfaces: voice/chat (Task 4), card (Task 9), /threads timeline (Task 11), DM (Task 8). §4 tools (Task 3). §5 budget (Task 6), failure honesty (Tasks 6, 8, 9), migration none, tests (every task), acceptance scenarios (Task 10). Parity walk extended (Task 3).
- **Type consistency.** `focus_key` is the name everywhere (router, tools, `triage`). `triage.next_for(viewer, key, skip_current)` returns a situation view; `agent_tools_v2.next_situation` wraps it. `replies.read(thread_id, message_id)`; `asks.record_reading(ask_id, answer, message_id, summary='')`; `asks.unread(ask_id, actor)`; `storage.update_thread_history_entry(thread_id, match, fields)`; `threads.send_drafted(..., intent='')` returns `ask_id`; `threads.match_inbound(..., message_id=None)`.
- **Order of green commits.** `unread` enters `VERBS`, `VERB_LABELS` and the enum together in Task 3 so the parity test never goes red; its behaviour arrives in Tasks 7 and 9. `replies.read` reaches `asks.record_reading` only on yes/no; Task 6's first scenario uses `info` until Task 7 lands.
- **Review Focus** items 1–5 are pinned in Tasks 2, 4, 3, 8 and 7 respectively.

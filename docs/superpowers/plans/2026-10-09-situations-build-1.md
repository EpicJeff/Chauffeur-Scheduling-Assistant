# Situations, build 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One `Situation` shape over findings, insights, threads and missions, with Argyle-written status notes, typed options, an `asks` ledger (channels, drafts, answers, atomic apply) that replaces `coverage_asks`, agent tools mirroring every verb, and the Needs-you lane on /mind, the PWA Family tab and the board tile.

**Architecture:** `services/situations.py` is a view-model and verb dispatcher over the four existing tables (no new situation table); rows gain `rev`, `status_note`, `next_steps`, `note_ts`, `note_rev`, `note_source`, `owner_member_id`, `owned_at`. `services/asks.py` owns the `asks` table and the claim-then-apply contract; `coverage_options` and the `storage.get_coverage_ask*` readers become adapters over it. `static/situations.js` is the one card builder every surface calls. Build 2 (threads/missions pages, PWA House threads, the DM clause) is a separate plan.

**Tech Stack:** Python 3.11 / FastAPI / TinyDB-over-SQLite storage (`storage.db_lock` RLock, schemaless rows), Gemini Flash-Lite through `services.model_pools.call_pool_json`, vanilla JS + Alpine on the pages, precompiled Tailwind (`python tools/build_tailwind.py` after any class change), standalone test scripts run from `chauffeur/` with `tests/harness.py` (`check(cond, msg)`), live tests via `tests/live_app.py` (playwright; skip when missing).

**Spec:** `docs/superpowers/specs/2026-10-09-situations-design.md` (read it first; this plan argues from it).

## Global Constraints

- Run everything from `E:\repositories\Chauffeur\chauffeur` with `..\venv\Scripts\python.exe`; run tests with `HA_BASE_URL` unset (`env -u HA_BASE_URL` in bash).
- Gate = the change's own tests + the named related tests only. Never the full sweep. The gate for this build: `tools/test.py situations asks coverage_ladder assist watchers mind findings threads missions agent_v2_bridge chat_actions needs_you`.
- Verb set is closed: `assign ask plan prepare do done skip research draft advance answer close snooze dismiss own`. Nothing else is ever executed.
- Options and `unlocks` are built server-side; a request supplies only `option_id` and free-text `payload` for `answer` / `advance`.
- Writes are parent/adult only, except `POST /api/asks/{id}/answer` from the member the ask is addressed to.
- `rev` is for the note only; writing the note never bumps `rev`. Applying a yes is judged by the action fingerprint in `unlocks`.
- Only `outcome: applied` means the promised work was done.
- Asks never send mail from the app. Threads' household-address send is untouched.
- No new LLM calls on reads, ticks or sweeps. Caps: `situation_cap_notes` 60/day, `ask_cap_drafts` 40/day.
- Dismissed is dismissed (v2.499.297): nothing here reopens a dismissed finding or insight.
- No browser dialogs: `showGlobalAlert` / `promptConfirm` / `promptInput` only.
- Every commit: bump `config.yaml` `version` (next is `2.499.301`, then +1 per commit), commit message ends `(vX.Y.Z)`, push.
- Persisted prose (code comments, docstrings, commit bodies, `system_capabilities.md`) is normal English.

## Review Focus

1. A yes on an ask whose event has since been **deleted** from the cached schedule (not moved): the fingerprint lookup finds no event → must record `outcome: stale`, never apply, never crash. Pinned in Task 5 (`scenario_yes_after_event_vanishes_is_stale`).
2. A **child** tapping Yes on a Chauffeur ask addressed to a **different** member → 403, ledger untouched. Pinned in Task 7 (`scenario_answer_gate_refuses_a_bystander`).
3. `act_on_situation` with an **option_id from a previous view** that no longer exists (a step closed meanwhile) → refused with a message, nothing executed. Pinned in Task 3 (`scenario_stale_option_id_is_refused`).
4. The Lite note call returning **options with a verb outside the set** or malformed JSON → deterministic options only, `note_source: fallback`, no exception reaching the mutator. Pinned in Task 4 (`scenario_bad_model_output_falls_back`).
5. A legacy `coverage_asks` row whose `event_id` matches a **newer occurrence's** finding → `situation_id` stays `None`, the ask still answers through the old endpoint. Pinned in Task 6 (`scenario_legacy_ask_does_not_attach_to_a_newer_occurrence`).

---

### Task 1: Storage — the `asks` table, insight-by-id, findings `in_hand`

**Files:**
- Modify: `services/storage.py` (table declarations near line 491; coverage ask functions at 3026-3053; mind insight getters near 2924)
- Modify: `services/findings.py` (`open_findings` at ~71, `reconcile` at ~84-160)
- Test: `tests/test_situations_storage.py` (new)

**Interfaces:**
- Produces: `storage.asks_table`; `storage.add_ask(data) -> str`; `storage.get_ask(ask_id) -> dict|None`; `storage.get_ask_by_legacy_id(legacy_id) -> dict|None`; `storage.update_ask(ask_id, data) -> bool`; `storage.get_asks(situation_kind=None, situation_id=None, state=None, event_id=None, to_member_id=None) -> list` (sorted by `asked_at`); `storage.get_mind_insight(insight_id) -> dict|None`; `findings.open_findings(severity=None, include_in_hand=False)`; `findings.reconcile` treats `in_hand` like `open`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_situations_storage.py
"""Storage for the situations slice: the asks ledger, insight-by-id, and a
finding in_hand that the sweep updates but never re-adds."""
import datetime
import time
from unittest import mock

from harness import check  # noqa: F401
from services import storage, findings, watchers

NOON = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)


def _reset():
    for t in (storage.asks_table, storage.findings_table, storage.chores_table,
              storage.members_table, storage.cache_table, storage.app_state_table,
              storage.chat_channels_table, storage.chat_messages_table):
        t.truncate()
    storage.get_settings = lambda: {"calendar_ids": ["primary"]}
    storage.add_member({"id": "mom", "name": "Mom", "role": "parent"})


def scenario_ask_roundtrip():
    _reset()
    aid = storage.add_ask({'situation_kind': 'finding', 'situation_id': 'f1',
                           'to_name': 'Sarah', 'what': 'drive Kate Thursday',
                           'channel': 'text', 'asked_by': 'mom', 'legacy_id': 'old1'})
    row = storage.get_ask(aid)
    check(row and row['state'] == 'drafted' and row['nudges_sent'] == 0,
          f"a new ask starts drafted with no nudges, got {row}")
    check(storage.get_ask_by_legacy_id('old1')['id'] == aid, "found by legacy id")
    check(storage.update_ask(aid, {'state': 'sent', 'sent_at': time.time()}), "update by id")
    check([a['id'] for a in storage.get_asks(situation_kind='finding', situation_id='f1')] == [aid],
          "listed by situation")
    check(storage.get_asks(state='drafted') == [], "state filter sees the update")
    check(storage.get_asks(to_member_id='nobody') == [], "member filter")


def scenario_insight_by_id():
    _reset()
    storage.mind_insights_table.truncate()
    iid = storage.add_mind_insight({'slug': 's', 'line': 'x', 'category': 'c'})
    check(storage.get_mind_insight(iid)['id'] == iid, "insight by id")
    check(storage.get_mind_insight('nope') is None, "unknown id is None")


def scenario_in_hand_finding_is_updated_never_readded():
    _reset()
    now_ts = NOON.timestamp()
    storage.set_cached_schedule({"events": [], "assignments": {}, "unassigned": []})
    storage.add_chore({"id": "c1", "title": "Mow lawn", "state": "done",
                       "done_at": now_ts - 3 * 86400, "created_at": now_ts - 9 * 86400,
                       "points": 20, "recurrence": "once", "eligible_member_ids": []})
    with mock.patch.object(watchers, '_prep_kit_findings', return_value=[]), \
         mock.patch('services.agent_tools_v2._post_chat_message',
                    side_effect=lambda ch, sender, body, card=None: {}):
        watchers.run_watchers(now=NOON)
        fid = storage.get_findings(state='open')[0]['id']
        storage.update_finding(fid, {'state': 'in_hand', 'owner_member_id': 'mom'})
        watchers.run_watchers(now=NOON + datetime.timedelta(days=1))
    rows = storage.get_findings(kind='chore_verify')
    check(len(rows) == 1 and rows[0]['state'] == 'in_hand', f"one row, still in hand: {rows}")
    check('day(s)' in rows[0]['line'], "the sentence keeps updating while in hand")
    check(findings.open_findings() == [], "open_findings hides in-hand rows by default")
    check(len(findings.open_findings(include_in_hand=True)) == 1, "…and shows them when asked")
    # Reality still closes it.
    storage.chores_table.update({'state': 'verified'}, storage.Query().id == 'c1')
    with mock.patch.object(watchers, '_prep_kit_findings', return_value=[]), \
         mock.patch('services.agent_tools_v2._post_chat_message',
                    side_effect=lambda ch, sender, body, card=None: {}):
        watchers.run_watchers(now=NOON + datetime.timedelta(days=1, hours=1))
    check(storage.get_finding(fid)['state'] == 'done', "absence closes an in-hand finding")


SCENARIOS = [scenario_ask_roundtrip, scenario_insight_by_id,
             scenario_in_hand_finding_is_updated_never_readded]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `env -u HA_BASE_URL ../venv/Scripts/python.exe tests/test_situations_storage.py`
Expected: FAIL — `AttributeError: module 'services.storage' has no attribute 'asks_table'`.

- [ ] **Step 3: Add the table and functions to storage.py**

Next to `coverage_asks_table = db.table('coverage_asks')` (line ~491) add:

```python
asks_table = db.table('asks')
```

After `update_coverage_ask` (line ~3053) add:

```python
# --- Asks: the one ledger of who was asked what, by which channel, and what
# came back (spec: docs/superpowers/specs/2026-10-09-situations-design.md §2).
# coverage_asks is read-only legacy from v2.499.301 on; see get_coverage_ask.

def add_ask(data: dict) -> str:
    import uuid as _uuid
    row = {'id': _uuid.uuid4().hex, 'asked_at': time.time(), 'state': 'drafted',
           'nudges_sent': 0, 'sent_at': None, 'answered_at': None, 'answered_by': None,
           'outcome': None, 'applied_at': None, 'unlock_error': None, **data}
    with db_lock:
        asks_table.insert(row)
    return row['id']

def get_ask(ask_id: str) -> Optional[dict]:
    if not ask_id:
        return None
    with db_lock:
        res = asks_table.search(Query().id == ask_id)
        return dict(res[0]) if res else None

def get_ask_by_legacy_id(legacy_id: str) -> Optional[dict]:
    if not legacy_id:
        return None
    with db_lock:
        res = asks_table.search(Query().legacy_id == legacy_id)
        return dict(res[0]) if res else None

def update_ask(ask_id: str, data: dict) -> bool:
    with db_lock:
        return bool(asks_table.update(data, Query().id == ask_id))

def get_asks(situation_kind: str = None, situation_id: str = None, state: str = None,
             event_id: str = None, to_member_id: str = None) -> List[dict]:
    with db_lock:
        rows = [dict(a) for a in asks_table.all()]
    if situation_kind:
        rows = [a for a in rows if a.get('situation_kind') == situation_kind]
    if situation_id:
        rows = [a for a in rows if a.get('situation_id') == situation_id]
    if state:
        rows = [a for a in rows if a.get('state') == state]
    if event_id:
        rows = [a for a in rows if str(a.get('event_id') or '') == str(event_id)]
    if to_member_id:
        rows = [a for a in rows if a.get('to_member_id') == to_member_id]
    rows.sort(key=lambda a: a.get('asked_at') or 0)
    return rows
```

After `get_mind_insight_by_identity` add:

```python
def get_mind_insight(insight_id: str) -> Optional[dict]:
    if not insight_id:
        return None
    with db_lock:
        res = mind_insights_table.search(Query().id == insight_id)
        return dict(res[0]) if res else None
```

- [ ] **Step 4: Teach findings.py about `in_hand`**

In `open_findings`:

```python
def open_findings(severity: str = None, include_in_hand: bool = False) -> list:
    rows = storage.get_findings(state='open')
    if include_in_hand:
        rows = rows + storage.get_findings(state='in_hand')
    if severity:
        rows = [r for r in rows if r.get('severity') == severity]
    order = {'decide': 0, 'approve': 1, 'fyi': 2}
    rows.sort(key=lambda r: (order.get(r.get('severity'), 3),
                             r.get('due_at') or float('inf'),
                             r.get('created_at') or 0))
    return rows
```

In `reconcile`, change the open branch condition to `if existing and existing.get('state') in ('open', 'in_hand'):` (the update block stays exactly as it is), and change the closing loop's source to:

```python
    for row in storage.get_findings(state='open') + storage.get_findings(state='in_hand'):
```

Add one line to the module docstring's rules list: `- **In hand is still open.** A finding somebody took (`in_hand`) keeps its sentence current and still closes by absence; it is never re-added and never DM'd.`

In `services/watchers.py`, the DM gate's `_dismissed` helper (added v2.499.297) becomes:

```python
    def _settled(f):
        row = storage.get_finding_by_identity(_findings.identity(f))
        return bool(row and row.get('state') in ('dismissed', 'in_hand'))
    fresh = [f for f in findings
             if f.dm and f.key not in notified and not _settled(f)]
```

- [ ] **Step 5: Run the tests**

Run: `env -u HA_BASE_URL ../venv/Scripts/python.exe tests/test_situations_storage.py`
Expected: `3/3 scenarios passed`. Then `env -u HA_BASE_URL ../venv/Scripts/python.exe tools/test.py watchers findings mind_storage` — all pass.

- [ ] **Step 6: Commit**

Bump `config.yaml` to `2.499.301`.
```bash
git add chauffeur/config.yaml chauffeur/services/storage.py chauffeur/services/findings.py chauffeur/services/watchers.py chauffeur/tests/test_situations_storage.py
git commit -m "feat(situations): asks ledger table, insight by id, findings in_hand (v2.499.301)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push origin main
```

---

### Task 2: `services/situations.py` — view, options, rank, list

**Files:**
- Create: `services/situations.py`
- Test: `tests/test_situations.py` (new)

**Interfaces:**
- Consumes: `storage.get_finding/get_mind_insight/get_thread/get_mission/get_mission_steps`, `coverage_options.ladder(ev)`, `storage.get_action_proposal`, `threads.is_stalled`, `storage.get_asks`.
- Produces:
  - `KINDS = ('finding', 'insight', 'thread', 'mission')`, `VERBS` frozenset.
  - `load(kind, sid) -> dict|None`
  - `options_for(kind, row) -> list[option]` where `option = {'id', 'label', 'verb', 'payload'}`; the first element is the highlighted next step.
  - `fallback_note(kind, row) -> str`
  - `view(kind, sid, viewer=None) -> dict|None` (the Situation shape from spec §1, plus `needs_attention: bool`, `group: 'now'|'in_hand'|'waiting'|'moving'|'done'`)
  - `rank(situations) -> list`
  - `list_situations(viewer, kinds=None, include_done=False) -> list`
  - `can_see(kind, row, viewer) -> bool`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_situations.py
"""The situation view-model: one shape over four tables, deterministic options
with a closed verb set, ranking, viewer gates, fallback notes."""
import datetime
import time

from harness import check  # noqa: F401
from models.schemas import HouseholdTask
from services import storage, situations, threads, findings

NOON = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)


def _reset():
    for t in (storage.findings_table, storage.mind_insights_table, storage.threads_table,
              storage.missions_table, storage.mission_steps_table, storage.asks_table,
              storage.members_table, storage.cache_table, storage.app_state_table,
              storage.agent_action_proposals_table, storage.assist_contacts_table,
              storage.coverage_asks_table):
        t.truncate()
    storage.get_settings = lambda: {"calendar_ids": ["primary"], "llm_gemini_api_key": ""}
    storage.add_member({"id": "mom", "name": "Mom", "role": "parent"})
    storage.add_member({"id": "dad", "name": "Dad", "role": "adult"})
    storage.add_member({"id": "kid", "name": "Kate", "role": "child", "is_child": True})
    storage.add_driver({"id": "mom", "name": "Mom", "color_code": "#fff"})


def _unassigned_event():
    soon = (NOON + datetime.timedelta(days=2)).replace(hour=16)
    storage.set_cached_schedule({
        "events": [{"id": "ev1", "title": "Soccer", "start": soon.isoformat(),
                    "end": (soon + datetime.timedelta(hours=1)).isoformat()}],
        "assignments": {}, "unassigned": ["ev1"]})
    return soon


def scenario_finding_view_has_facts_options_and_fallback_note():
    _reset()
    soon = _unassigned_event()
    fid = storage.add_finding({'identity': 'unassigned:ev1', 'kind': 'unassigned',
                               'severity': 'decide', 'line': '🚨 No driver yet: Soccer',
                               'subject_type': 'event', 'subject_id': 'ev1',
                               'due_at': soon.timestamp(), 'state': 'open',
                               'fingerprint': f"ev1|{soon.timestamp()}"})
    s = situations.view('finding', fid, viewer={'id': 'mom', 'role': 'parent'})
    check(s['kind'] == 'finding' and s['title'].startswith('🚨'), f"shape: {s}")
    check(s['state'] == 'open' and s['due'] == soon.timestamp(), "facts carried")
    check(s['note_source'] == 'fallback' and s['status_note'], "a fallback note is never empty")
    verbs = [o['verb'] for o in s['options']]
    check(verbs and set(verbs) <= situations.VERBS, f"only closed-set verbs: {verbs}")
    check(s['next_step']['id'] == s['options'][0]['id'], "next step is the first option")
    check(any(o['verb'] == 'ask' for o in s['options']), "an uncovered ride offers an ask")
    check(any(o['verb'] == 'own' for o in s['options']) and any(o['verb'] == 'dismiss' for o in s['options']),
          "own and dismiss are always there")
    check(all(o['id'] for o in s['options']) and len({o['id'] for o in s['options']}) == len(s['options']),
          "option ids are present and unique")


def scenario_finding_with_a_free_driver_offers_assign_first():
    _reset()
    soon = _unassigned_event()
    fid = storage.add_finding({'identity': 'unassigned:ev1', 'kind': 'unassigned',
                               'severity': 'approve', 'line': 'No driver yet', 'subject_type': 'event',
                               'subject_id': 'ev1', 'due_at': soon.timestamp(), 'state': 'open',
                               'fingerprint': f"ev1|{soon.timestamp()}"})
    s = situations.view('finding', fid, viewer={'id': 'mom', 'role': 'parent'})
    check(s['next_step']['verb'] == 'assign' and 'Mom' in s['next_step']['label'],
          f"a free family driver is the first move: {s['next_step']}")
    check(s['next_step']['payload'].get('driver_name') == 'Mom'
          and s['next_step']['payload'].get('event_name') == 'Soccer', "assign payload is server-built")


def scenario_insight_options_follow_the_plan_stages():
    _reset()
    iid = storage.add_mind_insight({'slug': 's', 'line': 'Tue and Thu collide', 'category': 'overload',
                                    'approach': 'ask Sarah to take Thursday', 'identity': 'overload:x',
                                    'refs': ['kate']})
    s = situations.view('insight', iid, viewer={'id': 'mom', 'role': 'parent'})
    check(s['next_step']['verb'] == 'plan' and 'ask Sarah' in s['next_step']['label'],
          f"before a plan the next step is to plan, labelled with the approach: {s['next_step']}")
    storage.update_mind_insight(iid, {'state': 'in_hand', 'plan_json': {'steps': [
        {'id': 'st1', 'kind': 'tool', 'text': 'Ask Sarah', 'status': 'open', 'proposal_json': None},
        {'id': 'st2', 'kind': 'human', 'text': 'Call the coach', 'status': 'open',
         'owner_member_id': 'mom', 'owner_name': 'Mom', 'due': '2026-10-12'},
        {'id': 'st3', 'kind': 'tool', 'text': 'Move dentist', 'status': 'open',
         'proposal_json': {'proposal_id': 'p1', 'summary': 'Move dentist'}}]}})
    s = situations.view('insight', iid, viewer={'id': 'mom', 'role': 'parent'})
    by_verb = {o['verb']: o for o in s['options']}
    check(s['next_step']['verb'] == 'prepare' and s['next_step']['payload']['step_id'] == 'st1',
          "first open tool step, unbound, is prepare")
    check('done' in by_verb and by_verb['done']['payload']['step_id'] == 'st2', "human step is done")
    check(any(o['verb'] == 'do' and o['payload']['step_id'] == 'st3' for o in s['options']), "bound step is do")
    check(sum(1 for o in s['options'] if o['verb'] == 'skip') == 3, "every open step can be skipped")
    check(s['group'] == 'in_hand', "a planned insight is in hand")


def scenario_thread_and_mission_views():
    _reset()
    tid = threads.create('Deck permit', owner_member_id='mom', next_action='call county',
                         next_action_at=(NOON - datetime.timedelta(days=3)).date().isoformat(),
                         counterparty_name='County', created_by='mom')
    s = situations.view('thread', tid, viewer={'id': 'mom', 'role': 'parent'})
    check(s['title'] == 'Deck permit' and 'County' in s['people'], f"thread facts: {s}")
    check(s['group'] == 'now', "an overdue next action needs you now")
    check('call county' in s['status_note'], "fallback note names the next action")
    check([o['verb'] for o in s['options'][:1]] == ['advance'], "overdue thread: advance is first")
    check({'draft', 'close', 'own'} <= {o['verb'] for o in s['options']}, "deterministic thread verbs present")

    mid = storage.add_mission({'goal': 'Find a plumber', 'status': 'waiting_user', 'created_by': 'mom',
                               'tier': 'flash', 'origin_kind': 'manual', 'step_count': 2})
    storage.add_mission_step(mid, {'kind': 'ask', 'name': 'ask_user', 'result_json': {'question': 'Budget?'}})
    s = situations.view('mission', mid, viewer={'id': 'mom', 'role': 'parent'})
    check(s['next_step']['verb'] == 'answer' and 'Budget?' in s['next_step']['label'], f"waiting mission asks: {s['next_step']}")
    check(s['needs_attention'] and s['group'] == 'now', "waiting_user needs attention")
    storage.update_mission(mid, {'status': 'done'})
    storage.add_mission_step(mid, {'kind': 'proposal', 'name': 'add_errand',
                                   'result_json': {'proposal_id': 'p9', 'status': 'proposed'}})
    storage.add_action_proposal({'id': 'p9', 'action_type': 'add_errand', 'summary': 'Add errand',
                                 'payload': {}, 'status': 'proposed', 'requires_admin': True})
    s = situations.view('mission', mid, viewer={'id': 'mom', 'role': 'parent'})
    check(s['needs_attention'] and s['next_step']['verb'] == 'do', "a done mission with a pending proposal still needs you")


def scenario_rank_and_viewer_gates():
    _reset()
    soon = _unassigned_event()
    f_decide = storage.add_finding({'identity': 'unassigned:ev1', 'kind': 'unassigned', 'severity': 'decide',
                                    'line': 'ride', 'subject_type': 'event', 'subject_id': 'ev1',
                                    'due_at': soon.timestamp(), 'state': 'open'})
    f_fyi = storage.add_finding({'identity': 'optional_skip:ev1', 'kind': 'optional_skip', 'severity': 'fyi',
                                 'line': 'skipped', 'subject_type': 'event', 'subject_id': 'ev1', 'state': 'open'})
    i_norm = storage.add_mind_insight({'slug': 'a', 'line': 'normal', 'category': 'c', 'confidence': 0.9,
                                       'approach': 'x', 'identity': 'c:1'})
    i_sens = storage.add_mind_insight({'slug': 'b', 'line': 'secret', 'category': 'c', 'confidence': 0.5,
                                       'approach': 'x', 'identity': 'c:2', 'sensitivity': 'sensitive'})
    rows = situations.list_situations({'id': 'mom', 'role': 'parent'}, kinds=('finding', 'insight'))
    check([r['id'] for r in rows] == [f_decide, i_norm, i_sens, f_fyi],
          f"decide, then insights by confidence, then fyi: {[r['id'] for r in rows]}")
    rows = situations.list_situations({'id': 'kid', 'role': 'child'}, kinds=('finding', 'insight'))
    check([r['id'] for r in rows] == [i_norm], f"a child sees non-sensitive insights only: {[r['id'] for r in rows]}")
    rows = situations.list_situations(None, kinds=('finding', 'insight'))
    check([r['id'] for r in rows] == [i_norm], "no viewer (a wall) is the same as a child")
    rows = situations.list_situations({'id': 'dad', 'role': 'adult'}, kinds=('finding', 'insight'))
    check(f_decide in [r['id'] for r in rows] and i_sens not in [r['id'] for r in rows],
          "an adult sees findings but not sensitive insights")


SCENARIOS = [scenario_finding_view_has_facts_options_and_fallback_note,
             scenario_finding_with_a_free_driver_offers_assign_first,
             scenario_insight_options_follow_the_plan_stages,
             scenario_thread_and_mission_views,
             scenario_rank_and_viewer_gates]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `env -u HA_BASE_URL ../venv/Scripts/python.exe tests/test_situations.py`
Expected: FAIL — `ImportError: cannot import name 'situations'`.

- [ ] **Step 3: Create `services/situations.py` (view half)**

```python
"""Situations — one shape for everything that needs a person.

Spec: docs/superpowers/specs/2026-10-09-situations-design.md. A situation is a
VIEW over a finding, insight, thread or mission row; nothing here owns a table.
Rows gain a few fields (rev, status_note, next_steps, note_ts, note_rev,
note_source, owner_member_id, owned_at) that this module alone writes.

Boundaries (same as the Mind's, enforced by tests on this file's source):
never import a DM accessor, never read gift records.
"""
import datetime
import json
import logging
import threading
import time
from typing import List, Optional

from services import storage

logger = logging.getLogger(__name__)

KINDS = ('finding', 'insight', 'thread', 'mission')
VERBS = frozenset({'assign', 'ask', 'plan', 'prepare', 'do', 'done', 'skip',
                   'research', 'draft', 'advance', 'answer', 'close', 'snooze',
                   'dismiss', 'own'})
WRITE_ROLES = ('parent', 'adult')


def _opt(verb: str, label: str, payload: dict = None, key: str = '') -> dict:
    """An option whose id is derived from what it does, so a stale id from an
    earlier view cannot be mistaken for a current one."""
    return {'id': f"{verb}:{key}" if key else verb, 'label': label,
            'verb': verb, 'payload': dict(payload or {})}


# --- loading ---------------------------------------------------------------

def load(kind: str, sid: str) -> Optional[dict]:
    if kind == 'finding':
        return storage.get_finding(sid)
    if kind == 'insight':
        return storage.get_mind_insight(sid)
    if kind == 'thread':
        return storage.get_thread(sid)
    if kind == 'mission':
        row = storage.get_mission(sid)
        if row:
            row = dict(row)
            row['steps'] = storage.get_mission_steps(sid)
        return row
    return None


def _update(kind: str, sid: str, fields: dict) -> bool:
    if kind == 'finding':
        return storage.update_finding(sid, fields)
    if kind == 'insight':
        return storage.update_mind_insight(sid, fields)
    if kind == 'thread':
        return storage.update_thread(sid, fields)
    if kind == 'mission':
        return storage.update_mission(sid, fields)
    return False


def _member_name(member_id) -> str:
    m = storage.get_member(member_id or '') if member_id else None
    return (m or {}).get('name') or ''


def _cached_event(event_id: str) -> Optional[dict]:
    sched = storage.get_cached_schedule() or {}
    return next((e for e in sched.get('events') or []
                 if str(e.get('id')) == str(event_id)), None)


def _parse(iso):
    try:
        return datetime.datetime.fromisoformat(str(iso).replace('Z', '+00:00')).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


# --- deterministic options, per kind ---------------------------------------

def _tail(kind: str, row: dict) -> list:
    """The options every kind ends with: take it, and leave it."""
    out = []
    if not row.get('owner_member_id'):
        out.append(_opt('own', "I'll handle it myself"))
    else:
        out.append(_opt('done', 'Handled'))
    if kind in ('finding', 'insight'):
        out.append(_opt('snooze', 'Not now', {'days': 7}, '7'))
        out.append(_opt('dismiss', 'Dismiss'))
    elif kind == 'thread':
        out.append(_opt('close', 'Drop it', {'state': 'dropped'}, 'dropped'))
    elif kind == 'mission':
        out.append(_opt('close', 'Drop the mission', {'state': 'dropped'}, 'dropped'))
    return out


def _options_finding(row: dict) -> list:
    out = []
    if row.get('kind') == 'unassigned' and row.get('subject_id'):
        ev = _cached_event(row['subject_id'])
        if ev:
            from services import coverage_options as _cov
            try:
                rung = _cov.ladder(ev)
            except Exception as e:
                logger.warning(f"[situations] ladder failed for {row['subject_id']}: {e}")
                rung = {}
            title = ev.get('title') or 'the ride'
            start = _parse(ev.get('start'))
            when = start.strftime('%A %I:%M %p').replace(' 0', ' ') if start else ''
            what = f"drive {title}{' ' + when if when else ''}"
            fp = f"{row['subject_id']}|{start.timestamp() if start else ''}"
            for a in rung.get('actions') or []:
                if a.get('action_type') == 'reassign_driver':
                    out.append(_opt('assign', a['label'], a['payload'], a['payload'].get('driver_name', '')))
                elif a.get('action_type') == 'ask_outside_hand' and a['payload'].get('contact_id'):
                    out.append(_opt('ask', a['label'], {
                        'to': {'name': a['payload'].get('contact_name', ''),
                               'contact_id': a['payload']['contact_id']},
                        'what': what,
                        'unlocks': {'action_type': 'assist_assignment',
                                    'payload': {'event_id': row['subject_id'],
                                                'contact_id': a['payload']['contact_id'],
                                                'event_title': title,
                                                'event_date': start.date().isoformat() if start else ''},
                                    'fingerprint': fp}}, a['payload']['contact_id']))
            # Asking somebody new is always possible, whatever the ladder said.
            out.append(_opt('ask', 'Ask someone', {
                'to': {}, 'what': what,
                'unlocks': {'action_type': 'assist_assignment',
                            'payload': {'event_id': row['subject_id'], 'event_title': title,
                                        'event_date': start.date().isoformat() if start else ''},
                            'fingerprint': fp}}, 'new'))
    elif row.get('proposal_id'):
        prop = storage.get_action_proposal(row['proposal_id'])
        if prop and prop.get('status') == 'proposed':
            out.append(_opt('do', prop.get('summary') or 'Approve', {'proposal_id': prop['id']}, prop['id']))
    return out + _tail('finding', row)


def _options_insight(row: dict) -> list:
    out = []
    steps = ((row.get('plan_json') or {}).get('steps') or [])
    if not steps:
        prop = row.get('proposal_json') or {}
        if prop.get('proposal_id'):
            out.append(_opt('do', prop.get('summary') or 'Approve', {'proposal_id': prop['proposal_id']},
                            prop['proposal_id']))
        else:
            approach = (row.get('approach') or '').strip()
            out.append(_opt('plan', f"Plan: {approach}" if approach else 'Make a plan'))
    for s in steps:
        if s.get('status') != 'open':
            continue
        bound = (s.get('proposal_json') or {}).get('proposal_id')
        if s.get('kind') == 'tool' and not bound:
            out.append(_opt('prepare', s.get('text') or 'Line it up', {'step_id': s['id']}, s['id']))
        elif s.get('kind') == 'tool':
            out.append(_opt('do', s.get('text') or 'Approve', {'step_id': s['id'], 'proposal_id': bound}, s['id']))
        else:
            out.append(_opt('done', s.get('text') or 'Done', {'step_id': s['id']}, s['id']))
    for s in steps:
        if s.get('status') == 'open':
            out.append(_opt('skip', f"Skip: {s.get('text') or ''}".strip(), {'step_id': s['id']}, s['id']))
    return out + _tail('insight', row)


def _options_thread(row: dict) -> list:
    from services import threads as _th
    out = []
    stalled = _th.is_stalled(row)
    if stalled == 'overdue' or not row.get('next_action'):
        out.append(_opt('advance', 'Set the next step', {}))
    out.append(_opt('draft', 'Draft a message', {}))
    if stalled != 'overdue' and row.get('next_action'):
        out.append(_opt('advance', 'Change the next step', {}))
    out.append(_opt('research', 'Look something up', {}))
    out.append(_opt('close', 'Done with it', {'state': 'done'}, 'done'))
    return out + _tail('thread', row)


def _options_mission(row: dict) -> list:
    out = []
    steps = row.get('steps') or []
    if row.get('status') == 'waiting_user':
        asked = next((s for s in reversed(steps) if s.get('kind') == 'ask'), None)
        q = ((asked or {}).get('result_json') or {}).get('question') or 'Argyle has a question'
        out.append(_opt('answer', q, {}))
    for s in steps:
        if s.get('kind') != 'proposal':
            continue
        pid = (s.get('result_json') or {}).get('proposal_id')
        prop = storage.get_action_proposal(pid) if pid else None
        if prop and prop.get('status') == 'proposed':
            out.append(_opt('do', prop.get('summary') or 'Approve', {'proposal_id': pid}, pid))
    return out + _tail('mission', row)


def options_for(kind: str, row: dict) -> list:
    builder = {'finding': _options_finding, 'insight': _options_insight,
               'thread': _options_thread, 'mission': _options_mission}[kind]
    opts = [o for o in builder(row) if o['verb'] in VERBS]
    # Argyle's cached suggestions ride along, already verb-checked at refresh.
    for extra in (row.get('next_steps') or []):
        if extra.get('verb') in VERBS and extra.get('id') not in {o['id'] for o in opts}:
            opts.insert(0, extra)
    return opts


# --- facts and fallback note ------------------------------------------------

def _fmt_day(ts) -> str:
    try:
        return datetime.datetime.fromtimestamp(float(ts)).strftime('%b %d')
    except (TypeError, ValueError):
        return ''


def fallback_note(kind: str, row: dict) -> str:
    if kind == 'finding':
        return row.get('line') or ''
    if kind == 'insight':
        return row.get('detail') or row.get('line') or ''
    if kind == 'thread':
        who = row.get('counterparty_name') or 'them'
        nxt = row.get('next_action') or 'no next action set'
        when = f" ({row['next_action_at']})" if row.get('next_action_at') else ''
        if row.get('state') == 'waiting':
            return f"Waiting on {who} since {_fmt_day(_last_ts(row))}; next: {nxt}{when}"
        return f"Next: {nxt}{when}"
    if kind == 'mission':
        last = (row.get('steps') or [{}])[-1]
        return f"{row.get('status')}: {last.get('name') or 'no steps yet'}"
    return ''


def _last_ts(row: dict) -> float:
    hist = row.get('history') or []
    return (hist[-1].get('ts') if hist else None) or row.get('created_at') or 0


def _since(kind: str, row: dict) -> float:
    if kind == 'thread':
        return _last_ts(row)
    if kind == 'mission':
        return row.get('updated_at') or row.get('created_at') or 0
    if kind == 'insight':
        return row.get('created_ts') or 0
    return row.get('created_at') or 0


def _people(kind: str, row: dict) -> list:
    if kind == 'finding':
        if row.get('subject_type') == 'event':
            ev = _cached_event(row.get('subject_id')) or {}
            return [c for c in (ev.get('attendee_names') or [])] or []
        return []
    if kind == 'insight':
        return [r for r in (row.get('refs') or []) if not str(r).startswith('#')]
    if kind == 'thread':
        return [n for n in (row.get('counterparty_name'), _member_name(row.get('owner_member_id'))) if n]
    if kind == 'mission':
        return [n for n in (_member_name(row.get('created_by')),) if n]
    return []


def _state(kind: str, row: dict) -> str:
    return row.get('status') if kind == 'mission' else (row.get('state') or '')


def _is_done(kind: str, row: dict) -> bool:
    st = _state(kind, row)
    if kind == 'finding':
        return st in ('done', 'dismissed', 'expired')
    if kind == 'insight':
        return st == 'retired'
    if kind == 'thread':
        return st in ('done', 'dropped')
    return st in ('done', 'blocked', 'dropped')


def needs_attention(kind: str, row: dict, opts: list) -> bool:
    """Independent of engine status: anything with a decision left is live."""
    if kind == 'mission':
        return any(o['verb'] in ('answer', 'do') for o in opts)
    if kind == 'thread':
        from services import threads as _th
        return bool(_th.is_stalled(row)) and not _is_done(kind, row)
    return not _is_done(kind, row) and not row.get('owner_member_id')


def _group(kind: str, row: dict, opts: list) -> str:
    if _is_done(kind, row) and not needs_attention(kind, row, opts):
        return 'done'
    if row.get('owner_member_id') or _state(kind, row) == 'in_hand':
        return 'in_hand'
    if needs_attention(kind, row, opts):
        return 'now'
    if kind == 'thread' and _state(kind, row) == 'waiting':
        return 'waiting'
    if kind == 'mission' and _state(kind, row) in ('running', 'waiting_retry'):
        return 'moving'
    return 'moving'


def can_see(kind: str, row: dict, viewer: Optional[dict]) -> bool:
    role = (viewer or {}).get('role')
    if kind == 'insight':
        if row.get('sensitivity') == 'sensitive':
            return role == 'parent'
        return True
    if kind == 'finding':
        return role in WRITE_ROLES
    if kind == 'thread':
        return role in WRITE_ROLES or (viewer and row.get('owner_member_id') == viewer.get('id'))
    return role in WRITE_ROLES


def view(kind: str, sid: str, viewer: Optional[dict] = None) -> Optional[dict]:
    if kind not in KINDS:
        return None
    row = load(kind, sid)
    if not row:
        return None
    opts = options_for(kind, row)
    from services import asks as _asks
    note = row.get('status_note') or ''
    source = row.get('note_source') or 'fallback'
    if not note or source != 'argyle' or (row.get('note_rev') or 0) != (row.get('rev') or 0):
        note, source = fallback_note(kind, row), 'fallback'
    title = {'finding': row.get('line'), 'insight': row.get('line'),
             'thread': row.get('title'), 'mission': row.get('goal')}[kind] or ''
    return {
        'kind': kind, 'id': sid, 'title': title,
        'state': _state(kind, row), 'since': _since(kind, row),
        'people': _people(kind, row),
        'due': row.get('due_at') if kind == 'finding' else (
            row.get('next_action_at') if kind == 'thread' else None),
        'status_note': note, 'note_source': source, 'note_ts': row.get('note_ts'),
        'next_step': opts[0] if opts else None, 'options': opts,
        'asks': _asks.asks_for(kind, sid, row),
        'needs_attention': needs_attention(kind, row, opts),
        'group': _group(kind, row, opts),
        'owner_member_id': row.get('owner_member_id'),
        'sensitivity': row.get('sensitivity') if kind == 'insight' else None,
        'severity': row.get('severity') if kind == 'finding' else None,
        'confidence': row.get('confidence') if kind == 'insight' else None,
        'rev': row.get('rev') or 0,
    }


# --- listing and ranking ---------------------------------------------------

_SEV = {'decide': 0, 'approve': 1, 'fyi': 3}


def rank(rows: list) -> list:
    """decide findings by due, then approve, then insights by confidence,
    then fyi — the order somebody would work down it."""
    def key(s):
        if s['kind'] == 'finding':
            return (_SEV.get(s.get('severity'), 3), s.get('due') or float('inf'), s['since'])
        if s['kind'] == 'insight':
            return (2, -(s.get('confidence') or 0), s['since'])
        return (2.5, s.get('due') or float('inf'), s['since'])
    return sorted(rows, key=key)


def _rows_of(kind: str, include_done: bool) -> list:
    if kind == 'finding':
        from services import findings as _f
        return [('finding', r['id']) for r in _f.open_findings(include_in_hand=True)]
    if kind == 'insight':
        from services import mind as _m
        return [('insight', r['id']) for r in _m.visible_insights({'role': 'parent'})]
    if kind == 'thread':
        return [('thread', t['id']) for t in storage.get_threads(include_closed=include_done)]
    if kind == 'mission':
        return [('mission', m['id']) for m in storage.get_missions()
                if include_done or m.get('status') not in ('dropped',)]
    return []


def list_situations(viewer: Optional[dict], kinds=None, include_done: bool = False) -> list:
    out = []
    for kind in (kinds or KINDS):
        for k, sid in _rows_of(kind, include_done):
            row = load(k, sid)
            if not row or not can_see(k, row, viewer):
                continue
            s = view(k, sid, viewer)
            if s and (include_done or s['group'] != 'done'):
                out.append(s)
    return rank(out)
```

`asks.asks_for` does not exist yet; create `services/asks.py` with only this stub so the view half imports (Task 5 replaces it):

```python
"""Asks — the ledger of who was asked what, by which channel, and what came
back. Spec §2. Filled in by the asks task; the view needs asks_for first."""
from services import storage


def asks_for(kind: str, sid: str, row: dict = None) -> list:
    rows = storage.get_asks(situation_kind=kind, situation_id=sid)
    if kind == 'finding' and row and row.get('subject_type') == 'event':
        ids = {a['id'] for a in rows}
        rows += [a for a in storage.get_asks(event_id=row.get('subject_id')) if a['id'] not in ids]
    return rows
```

- [ ] **Step 4: Run the tests until green**

Run: `env -u HA_BASE_URL ../venv/Scripts/python.exe tests/test_situations.py`
Expected: `5/5 scenarios passed`. If `_people` for an event finding fails on `attendee_names`, return `[]` for findings whose cached event has no such field — the test does not assert people on findings.

- [ ] **Step 5: Commit**

Bump `config.yaml` to `2.499.302`.
```bash
git add chauffeur/config.yaml chauffeur/services/situations.py chauffeur/services/asks.py chauffeur/tests/test_situations.py
git commit -m "feat(situations): the view-model - one shape, typed options, rank, viewer gates (v2.499.302)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push origin main
```

---

### Task 3: `situations.act` — one verb dispatcher, `own` and `done`

**Files:**
- Modify: `services/situations.py`
- Test: `tests/test_situations.py` (append scenarios)

**Interfaces:**
- Consumes: `mind.make_plan/bind_step/close_step`, `chat_actions.act_on_proposal`, `agent_tools_v2.assign_driver_to_event_fuzzy`, `threads.advance/draft_message/research/close`, `findings.resolve`, `storage.update_*`.
- Produces: `act(kind, sid, verb, option_id=None, payload=None, actor=None) -> dict` returning `{'status': 'success'|'error'|'refused'|'proposed'|'no_move'|'capped'|'planned'|'no_plan', 'message', 'schedule_dirty'?, 'draft'?, ...}`; `own(kind, sid, actor)`, `done(kind, sid, actor)`; `bump_rev(kind, sid)`.

- [ ] **Step 1: Append failing tests to `tests/test_situations.py`**

```python
def scenario_act_resolves_the_option_server_side():
    _reset()
    soon = _unassigned_event()
    fid = storage.add_finding({'identity': 'unassigned:ev1', 'kind': 'unassigned', 'severity': 'approve',
                               'line': 'No driver yet', 'subject_type': 'event', 'subject_id': 'ev1',
                               'due_at': soon.timestamp(), 'state': 'open'})
    s = situations.view('finding', fid, viewer={'id': 'mom', 'role': 'parent'})
    assign = next(o for o in s['options'] if o['verb'] == 'assign')
    res = situations.act('finding', fid, 'assign', option_id=assign['id'],
                         payload={'driver_name': 'Dad'},      # ignored: payload is server-built
                         actor={'id': 'mom', 'role': 'parent'})
    check(res['status'] == 'success' and res.get('schedule_dirty'), f"assign ran: {res}")
    ov = [o for o in storage.get_all_overrides() if str(o.get('event_id')) == 'ev1']
    check(ov and ov[0].get('driver_id') == 'mom', f"the SERVER's driver was assigned, not the client's: {ov}")


def scenario_stale_option_id_is_refused():
    _reset()
    iid = storage.add_mind_insight({'slug': 's', 'line': 'x', 'category': 'c', 'approach': 'y',
                                    'identity': 'c:1', 'state': 'in_hand', 'plan_json': {'steps': [
                                        {'id': 'st1', 'kind': 'human', 'text': 'Call', 'status': 'open'}]}})
    res = situations.act('insight', iid, 'done', option_id='done:st1', actor={'id': 'mom', 'role': 'parent'})
    check(res['status'] == 'success', f"a current option runs: {res}")
    res = situations.act('insight', iid, 'done', option_id='done:st1', actor={'id': 'mom', 'role': 'parent'})
    check(res['status'] == 'refused' and 'no longer' in res['message'],
          f"the same id a second time is stale and refused: {res}")
    res = situations.act('insight', iid, 'launch_rocket', option_id='x', actor={'id': 'mom', 'role': 'parent'})
    check(res['status'] == 'refused', "a verb outside the set is refused")


def scenario_own_is_not_done():
    _reset()
    soon = _unassigned_event()
    fid = storage.add_finding({'identity': 'unassigned:ev1', 'kind': 'unassigned', 'severity': 'decide',
                               'line': 'ride', 'subject_type': 'event', 'subject_id': 'ev1',
                               'due_at': soon.timestamp(), 'state': 'open'})
    res = situations.act('finding', fid, 'own', option_id='own', actor={'id': 'dad', 'role': 'adult'})
    row = storage.get_finding(fid)
    check(res['status'] == 'success' and row['state'] == 'in_hand' and row['owner_member_id'] == 'dad',
          f"own moves to in hand with an owner: {row}")
    s = situations.view('finding', fid, viewer={'id': 'mom', 'role': 'parent'})
    check(s['group'] == 'in_hand' and s['next_step']['verb'] == 'done', "in hand: next step is Handled")
    res = situations.act('finding', fid, 'done', option_id='done', actor={'id': 'dad', 'role': 'adult'})
    check(storage.get_finding(fid)['state'] == 'done' and storage.get_finding(fid)['resolved_by'] == 'tap',
          "done closes it the way a tap always has")


def scenario_write_gate():
    _reset()
    tid = threads.create('T', owner_member_id='mom', created_by='mom')
    res = situations.act('thread', tid, 'close', option_id='close:done', actor={'id': 'kid', 'role': 'child'})
    check(res['status'] == 'refused', "a child cannot act")
    res = situations.act('thread', tid, 'close', option_id='close:done', actor=None)
    check(res['status'] == 'refused', "no actor cannot act (the tool layer passes the admin surface's nominee)")
    res = situations.act('thread', tid, 'close', option_id='close:done', actor={'id': 'mom', 'role': 'parent'})
    check(res['status'] == 'success' and storage.get_thread(tid)['state'] == 'done', "a parent can")
    check((storage.get_thread(tid).get('rev') or 0) >= 1, "an act bumps rev")


SCENARIOS += [scenario_act_resolves_the_option_server_side, scenario_stale_option_id_is_refused,
              scenario_own_is_not_done, scenario_write_gate]
```

(Place the `SCENARIOS += [...]` line after the existing `SCENARIOS = [...]`.)

- [ ] **Step 2: Run to verify failure**

Run: `env -u HA_BASE_URL ../venv/Scripts/python.exe tests/test_situations.py`
Expected: the four new scenarios FAIL with `AttributeError: module 'services.situations' has no attribute 'act'`.

- [ ] **Step 3: Add the act half to `services/situations.py`**

Append:

```python
# --- acting ------------------------------------------------------------------

def bump_rev(kind: str, sid: str) -> int:
    """Every mutation of the row, or of one of its asks, moves the revision.
    Writing the cached note never does (see refresh)."""
    with storage.db_lock:
        row = load(kind, sid) or {}
        rev = int(row.get('rev') or 0) + 1
        _update(kind, sid, {'rev': rev})
    return rev


def _refused(msg: str) -> dict:
    return {'status': 'refused', 'message': msg}


def _can_write(actor) -> bool:
    return bool(actor) and actor.get('role') in WRITE_ROLES


def own(kind: str, sid: str, actor: dict) -> dict:
    fields = {'owner_member_id': actor['id'], 'owned_at': time.time()}
    if kind == 'finding':
        fields['state'] = 'in_hand'
    if not _update(kind, sid, fields):
        return {'status': 'error', 'message': 'That is no longer here.'}
    bump_rev(kind, sid)
    return {'status': 'success', 'message': f"{actor.get('name') or 'You'} took it."}


def done(kind: str, sid: str, actor: dict) -> dict:
    if kind == 'finding':
        from services import findings as _f
        res = _f.resolve(sid, 'tap', member_id=actor.get('id'))
    elif kind == 'insight':
        res = {'status': 'success'} if storage.update_mind_insight(sid, {
            'state': 'retired', 'outcome': 'acted', 'resolved_ts': time.time()}) else \
            {'status': 'error', 'message': 'No such insight'}
    elif kind == 'thread':
        from services import threads as _th
        res = {'status': 'success'} if _th.close(sid, 'done', who=actor.get('id')) else \
            {'status': 'error', 'message': 'No such thread'}
    else:
        res = {'status': 'success'} if storage.update_mission(sid, {
            'status': 'done', 'finished_at': time.time()}) else {'status': 'error', 'message': 'No such mission'}
    if res.get('status') == 'success':
        bump_rev(kind, sid)
        request_refresh(kind, sid)
    return res


def act(kind: str, sid: str, verb: str, option_id: str = None, payload: dict = None,
        actor: dict = None) -> dict:
    """The single implementation behind every card button and every agent
    tool. The option is re-derived from the row RIGHT NOW; an id from an
    earlier view that no longer exists is refused, nothing runs."""
    if kind not in KINDS or verb not in VERBS:
        return _refused("That is not something I can do here.")
    if not _can_write(actor):
        return _refused("Only a parent or adult can do that.")
    row = load(kind, sid)
    if not row:
        return {'status': 'error', 'message': 'That is no longer here.'}
    opts = options_for(kind, row)
    opt = next((o for o in opts if o['id'] == (option_id or verb) and o['verb'] == verb), None)
    if not opt:
        return _refused("That option is no longer on the table — the situation moved. Take another look.")
    p = dict(opt['payload'])
    free = payload or {}
    if verb in ('answer', 'advance'):
        p.update({k: v for k, v in free.items()
                  if k in ('text', 'next_action', 'next_action_at', 'note')})
    if verb == 'snooze' and isinstance(free.get('days'), int):
        p['days'] = max(1, min(60, free['days']))

    res = _run(kind, sid, verb, p, actor, row)
    if res.get('status') in ('success', 'proposed', 'planned'):
        bump_rev(kind, sid)
        request_refresh(kind, sid)
    return res


def _run(kind, sid, verb, p, actor, row) -> dict:
    if verb == 'own':
        return own(kind, sid, actor)
    if verb == 'done' and not p.get('step_id'):
        return done(kind, sid, actor)
    if verb == 'dismiss':
        if kind == 'finding':
            from services import findings as _f
            return _f.resolve(sid, 'dismiss', member_id=actor.get('id'))
        ok = storage.update_mind_insight(sid, {'state': 'retired', 'outcome': 'dismissed',
                                               'resolved_ts': time.time()})
        return {'status': 'success' if ok else 'error', 'message': 'Left it.'}
    if verb == 'snooze':
        days = int(p.get('days') or 7)
        if kind == 'insight':
            storage.update_mind_insight(sid, {'snoozed_until': time.time() + days * 86400})
        else:
            storage.update_finding(sid, {'snoozed_until': time.time() + days * 86400})
        return {'status': 'success', 'message': f"Parked for {days} days.", 'days': days}
    if verb == 'assign':
        from services.agent_tools_v2 import assign_driver_to_event_fuzzy
        res = assign_driver_to_event_fuzzy(p.get('event_name'), p.get('driver_name'), p.get('target_date'))
        if res.get('status') == 'success':
            res['schedule_dirty'] = True
        return res
    if verb == 'do':
        from services import chat_actions as _ca, mind as _mind
        res = _ca.act_on_proposal(p['proposal_id'], 'approve', actor)
        if res.get('status') == 'success' and kind == 'insight' and p.get('step_id'):
            closed = _mind.close_step(sid, p['step_id'], 'done')
            res['plan'] = closed.get('plan')
        if res.get('status') == 'success' and kind == 'insight' and not p.get('step_id'):
            storage.update_mind_insight(sid, {'state': 'retired', 'outcome': 'acted', 'resolved_ts': time.time()})
        return res
    if verb == 'plan':
        from services import mind as _mind
        return _mind.make_plan(sid, actor)
    if verb == 'prepare':
        from services import mind as _mind
        return _mind.bind_step(sid, p['step_id'], actor)
    if verb in ('done', 'skip'):
        from services import mind as _mind
        return _mind.close_step(sid, p['step_id'], 'done' if verb == 'done' else 'skipped')
    if verb == 'advance':
        from services import threads as _th
        if not (p.get('next_action') or '').strip():
            return {'status': 'error', 'message': 'Say what the next step is.'}
        ok = _th.advance(sid, p['next_action'], next_action_at=p.get('next_action_at'),
                         note=p.get('note'), who=actor.get('id'))
        return {'status': 'success' if ok else 'error', 'message': 'Next step set.'}
    if verb == 'draft':
        from services import threads as _th
        res = _th.draft_message(sid, intent=p.get('text') or '')
        return {**res, 'status': res.get('status') or 'success'}
    if verb == 'research':
        from services import threads as _th
        if not (p.get('text') or '').strip():
            return {'status': 'error', 'message': 'Say what to look up.'}
        return _th.research(sid, p['text'])
    if verb == 'answer':
        text = (p.get('text') or '').strip()
        if not text:
            return {'status': 'error', 'message': 'Say something to send.'}
        storage.add_mission_step(sid, {'kind': 'note', 'name': 'user_answer', 'result_json': {'text': text}})
        if row.get('status') == 'waiting_user':
            storage.update_mission(sid, {'status': 'running'})
        return {'status': 'success', 'message': 'Answered.'}
    if verb == 'close':
        state = p.get('state') or 'done'
        if kind == 'thread':
            from services import threads as _th
            ok = _th.close(sid, state, who=actor.get('id'))
        else:
            ok = storage.update_mission(sid, {'status': 'dropped' if state == 'dropped' else 'done',
                                              'finished_at': time.time()})
        return {'status': 'success' if ok else 'error', 'message': 'Closed.'}
    if verb == 'ask':
        # The ask flow has its own endpoint/tool (asks.create); the option only
        # carries what the ask would be. Reaching here means a client posted
        # an ask verb to /act — point it at the right door.
        return {'status': 'error', 'message': 'Start the ask with POST /api/asks.'}
    return _refused("That is not something I can do here.")


# --- refresh (filled in by the next task) ------------------------------------

def request_refresh(kind: str, sid: str) -> None:
    """Placeholder until the refresh task lands; the act path calls it."""
    return None
```

- [ ] **Step 4: Run the tests**

Run: `env -u HA_BASE_URL ../venv/Scripts/python.exe tests/test_situations.py`
Expected: `9/9 scenarios passed`. If `assign_driver_to_event_fuzzy` needs the driver's member to exist, `_reset` already adds `mom` as both member and driver.

- [ ] **Step 5: Commit**

Bump `config.yaml` to `2.499.303`.
```bash
git add chauffeur/config.yaml chauffeur/services/situations.py chauffeur/tests/test_situations.py
git commit -m "feat(situations): act - one verb dispatcher, server-bound options, own vs done (v2.499.303)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push origin main
```

---
### Task 4: `situations.refresh` — Argyle's note on state change, `rev`, coalescing

**Files:**
- Modify: `services/situations.py` (replace the `request_refresh` placeholder)
- Modify: `services/threads.py` (`advance`, `note`, `close`, `send_drafted`, `research` — one line each), `services/missions.py` (`_close` at ~182 and the end of `step()` at ~202-318), `services/findings.py` (`reconcile`, after `storage.add_finding`), `services/mind.py` (`deep_think` after `add_mind_insight` and the revive branch; `make_plan` after the plan write; `close_step`)
- Modify: `services/settings_registry.py` (two `_e(` lines after `mind_direct_categories`)
- Test: `tests/test_situations_refresh.py` (new)

**Interfaces:**
- Produces: `situations.request_refresh(kind, sid)` (coalesced, background), `situations.refresh(kind, sid) -> dict` (synchronous; `{'status': 'noted'|'fallback'|'capped'|'no_key'|'superseded'|'not_found'}`), `situations.flush_refreshes()` (tests: run everything pending now), `situations.REFRESH_DELAY_S` (module constant, default 2.0), `situations._pool_call` (indirection tests stub), `situations.held_notes_today()`.
- Settings: `situation_cap_notes` (default 60), `ask_cap_drafts` (default 40), page `work?tab=mind`, anchor `mind-general`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_situations_refresh.py
"""Argyle writes the status note on state change only: coalesced, versioned
by rev, discarded when superseded, capped, never on read, and never able
to put a verb outside the closed set on a card."""
import datetime
import time

from harness import check  # noqa: F401
from services import storage, situations, threads

CALLS = []


def _fake_pool(reply):
    def f(tier, api_key, system, prompt, **kw):
        CALLS.append({'tier': tier, 'prompt': prompt})
        return reply() if callable(reply) else reply
    return f


def _reset():
    CALLS.clear()
    for t in (storage.threads_table, storage.findings_table, storage.mind_insights_table,
              storage.missions_table, storage.mission_steps_table, storage.asks_table,
              storage.members_table, storage.app_state_table):
        t.truncate()
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k'}
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    situations.REFRESH_DELAY_S = 0


def scenario_note_is_written_on_change_not_on_read():
    _reset()
    situations._pool_call = _fake_pool({'status_note': 'Waiting on the county since Monday.',
                                        'options': [{'label': 'Call them Friday', 'verb': 'advance',
                                                     'payload': {'next_action': 'call county',
                                                                 'next_action_at': '2026-10-16'}}]})
    tid = threads.create('Deck permit', owner_member_id='mom', next_action='call', created_by='mom')
    situations.flush_refreshes()
    n = len(CALLS)
    check(n == 1, f"creating a thread wrote one note, got {n}")
    for _ in range(3):
        situations.view('thread', tid, viewer={'id': 'mom', 'role': 'parent'})
        situations.list_situations({'id': 'mom', 'role': 'parent'}, kinds=('thread',))
    check(len(CALLS) == 1, "reads never call the model")
    s = situations.view('thread', tid, viewer={'id': 'mom', 'role': 'parent'})
    check(s['status_note'] == 'Waiting on the county since Monday.' and s['note_source'] == 'argyle',
          f"the note is Argyle's: {s['status_note']} / {s['note_source']}")
    check(s['options'][0]['verb'] == 'advance' and s['options'][0]['label'] == 'Call them Friday',
          "Argyle's suggestion leads, typed")
    check(s['options'][0]['id'].startswith('advance:argyle:'), "suggested options get their own ids")


def scenario_one_logical_mutation_one_call():
    _reset()
    situations._pool_call = _fake_pool({'status_note': 'n', 'options': []})
    tid = threads.create('T', owner_member_id='mom', created_by='mom')
    situations.flush_refreshes()
    CALLS.clear()
    # send_drafted appends history AND changes state — one refresh.
    threads.send_drafted(tid, 'subj', 'body', 'a@b.c', who='mom')
    situations.flush_refreshes()
    check(len(CALLS) == 1, f"a send is one refresh, got {len(CALLS)}")


def scenario_out_of_order_result_is_discarded():
    _reset()
    tid = threads.create('T', owner_member_id='mom', created_by='mom')
    situations.flush_refreshes()
    # A slow call started at rev N; the row moves to N+1 before it returns.
    def slow():
        threads.note(tid, 'something happened', who='mom')   # bumps rev mid-call
        return {'status_note': 'OLD', 'options': []}
    situations._pool_call = _fake_pool(slow)
    res = situations.refresh('thread', tid)
    check(res['status'] == 'superseded', f"a result for an older rev is discarded: {res}")
    row = storage.get_thread(tid)
    check(row.get('status_note') != 'OLD', "the stale note never lands")


def scenario_bad_model_output_falls_back():
    _reset()
    tid = threads.create('T', owner_member_id='mom', next_action='call', created_by='mom')
    situations._pool_call = _fake_pool({'status_note': 'x', 'options': [
        {'label': 'Launch', 'verb': 'launch_rocket', 'payload': {}},
        {'label': 'Drop it', 'verb': 'close', 'payload': {'state': 'dropped'}}]})
    res = situations.refresh('thread', tid)
    check(res['status'] == 'noted', f"a note with one bad option still lands: {res}")
    s = situations.view('thread', tid, viewer={'id': 'mom', 'role': 'parent'})
    verbs = {o['verb'] for o in s['options']}
    check('launch_rocket' not in verbs and set(verbs) <= situations.VERBS, f"bad verb dropped: {verbs}")
    situations._pool_call = _fake_pool('not json at all')
    res = situations.refresh('thread', tid)
    check(res['status'] == 'fallback', f"garbage is a fallback, not an exception: {res}")
    s = situations.view('thread', tid, viewer={'id': 'mom', 'role': 'parent'})
    check(s['note_source'] == 'fallback' and 'call' in s['status_note'], "deterministic facts remain")


def scenario_cap_and_no_key():
    _reset()
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k', 'situation_cap_notes': 1}
    situations._pool_call = _fake_pool({'status_note': 'n', 'options': []})
    tid = threads.create('T', owner_member_id='mom', created_by='mom')
    check(situations.refresh('thread', tid)['status'] == 'noted', "first call allowed")
    check(situations.refresh('thread', tid)['status'] == 'capped', "second is capped")
    check(situations.held_notes_today() == 1, "capped notes are counted")
    storage.get_settings = lambda: {}
    check(situations.refresh('thread', tid)['status'] == 'no_key', "no key, no call")


def scenario_the_note_write_does_not_bump_rev():
    _reset()
    situations._pool_call = _fake_pool({'status_note': 'n', 'options': []})
    tid = threads.create('T', owner_member_id='mom', created_by='mom')
    situations.flush_refreshes()
    rev = storage.get_thread(tid).get('rev')
    situations.refresh('thread', tid)
    check(storage.get_thread(tid).get('rev') == rev, "writing the note leaves rev alone")
    check(storage.get_thread(tid).get('note_rev') == rev, "the note remembers the rev it describes")


SCENARIOS = [scenario_note_is_written_on_change_not_on_read, scenario_one_logical_mutation_one_call,
             scenario_out_of_order_result_is_discarded, scenario_bad_model_output_falls_back,
             scenario_cap_and_no_key, scenario_the_note_write_does_not_bump_rev]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
```

- [ ] **Step 2: Run to verify failure**

Run: `env -u HA_BASE_URL ../venv/Scripts/python.exe tests/test_situations_refresh.py`
Expected: FAIL — `AttributeError: module 'services.situations' has no attribute 'flush_refreshes'` (or `_pool_call`).

- [ ] **Step 3: Replace the placeholder in `services/situations.py`**

```python
# --- refresh: Argyle's note, on state change only ----------------------------

REFRESH_DELAY_S = 2.0
NOTE_TIMEOUT_S = 20
CAP_NOTES_DEFAULT = 60

NOTE_SYSTEM = (
    "You are Argyle, a family home's assistant. You are shown ONE thing that "
    "needs a person — its facts, recent history and open asks. Write "
    "status_note: one or two plain sentences on where it stands (no advice, "
    "no praise). Then options: up to 3 concrete next moves, each with a verb "
    "from this closed list and ONLY this list: advance (payload next_action, "
    "next_action_at YYYY-MM-DD), draft (payload text: what the message should "
    "say), research (payload text: the question), close (payload state "
    "done|dropped). A move names a person or a thing. Return STRICT JSON: "
    '{"status_note": "...", "options": [{"label": "...", "verb": "...", '
    '"payload": {}}]}. Never invent facts.'
)

_pending: dict = {}
_pending_lock = threading.Lock()


def _pool_call(tier, api_key, system, prompt, **kw):
    """Indirection so tests stub one attribute (mind.py precedent)."""
    from services import model_pools
    return model_pools.call_pool_json(tier, api_key, system, prompt, **kw)


def _bump_call(kind: str, cap: int) -> bool:
    day = datetime.date.today().isoformat()
    key = f'situation_calls:{day}'
    counts = dict(storage.get_app_state(key) or {})
    if int(counts.get(kind, 0)) >= cap:
        return False
    counts[kind] = int(counts.get(kind, 0)) + 1
    storage.set_app_state(key, counts)
    return True


def _count_held(kind: str):
    day = datetime.date.today().isoformat()
    key = f'situation_held:{day}'
    counts = dict(storage.get_app_state(key) or {})
    counts[kind] = int(counts.get(kind, 0)) + 1
    storage.set_app_state(key, counts)


def held_notes_today() -> int:
    day = datetime.date.today().isoformat()
    return int((storage.get_app_state(f'situation_held:{day}') or {}).get('note', 0))


def _facts(kind: str, row: dict) -> str:
    lines = [f"kind: {kind}", f"state: {_state(kind, row)}",
             f"since: {_fmt_day(_since(kind, row))}", f"people: {', '.join(_people(kind, row)) or '-'}"]
    if kind == 'thread':
        lines.append(f"title: {row.get('title')}; goal: {row.get('goal') or '-'}; "
                     f"counterparty: {row.get('counterparty_name') or '-'}; "
                     f"next: {row.get('next_action') or '-'} ({row.get('next_action_at') or 'no date'})")
        for h in (row.get('history') or [])[-10:]:
            lines.append(f"- [{h.get('kind')}] {_fmt_day(h.get('ts'))} {h.get('who') or ''}: {(h.get('text') or '')[:200]}")
    elif kind == 'mission':
        lines.append(f"goal: {row.get('goal')}; summary: {row.get('summary') or '-'}; error: {row.get('error') or '-'}")
        for s in (row.get('steps') or [])[-10:]:
            lines.append(f"- [{s.get('kind')}] {s.get('name')}: {json.dumps(s.get('result_json') or {})[:200]}")
    elif kind == 'finding':
        lines.append(f"line: {row.get('line')}; severity: {row.get('severity')}; due: {_fmt_day(row.get('due_at'))}")
    else:
        lines.append(f"line: {row.get('line')}; detail: {row.get('detail') or '-'}; approach: {row.get('approach') or '-'}")
        for s in ((row.get('plan_json') or {}).get('steps') or []):
            lines.append(f"- step [{s.get('status')}] {s.get('text')}")
    from services import asks as _asks
    for a in _asks.asks_for(kind, row['id'], row):
        lines.append(f"- ask {a.get('to_name')} by {a.get('channel')}: {a.get('what')} -> {a.get('state')}"
                     f"{(' / ' + a['outcome']) if a.get('outcome') else ''}")
    return '\n'.join(lines)


def refresh(kind: str, sid: str) -> dict:
    """One call, synchronous. Captures rev first; a result for an older rev is
    thrown away. Writing the note never bumps rev."""
    row = load(kind, sid)
    if not row:
        return {'status': 'not_found'}
    settings = storage.get_settings() or {}
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key:
        _write_fallback(kind, sid, row)
        return {'status': 'no_key'}
    cap = int(settings.get('situation_cap_notes', CAP_NOTES_DEFAULT))
    if not _bump_call('note', cap):
        _count_held('note')
        _write_fallback(kind, sid, row)
        return {'status': 'capped'}
    rev_at_start = int(row.get('rev') or 0)
    try:
        res = _pool_call('interactive', api_key, NOTE_SYSTEM, _facts(kind, row),
                         timeout_s=NOTE_TIMEOUT_S, background=True, workflow='situations.note')
    except Exception as e:
        logger.warning(f"[situations] note call failed for {kind}/{sid}: {e}")
        res = None
    if not isinstance(res, dict) or not (res.get('status_note') or '').strip():
        _write_fallback(kind, sid, row)
        return {'status': 'fallback'}
    fresh = load(kind, sid) or {}
    if int(fresh.get('rev') or 0) != rev_at_start:
        request_refresh(kind, sid)
        return {'status': 'superseded'}
    options = []
    for i, o in enumerate(res.get('options') or []):
        verb = (o or {}).get('verb')
        if verb not in ('advance', 'draft', 'research', 'close'):
            continue
        payload = dict((o.get('payload') or {}))
        if verb == 'close' and payload.get('state') not in ('done', 'dropped'):
            continue
        options.append({'id': f"{verb}:argyle:{i}", 'label': (o.get('label') or verb)[:120],
                        'verb': verb, 'payload': payload})
    _update(kind, sid, {'status_note': res['status_note'].strip()[:400], 'next_steps': options,
                        'note_ts': time.time(), 'note_rev': rev_at_start, 'note_source': 'argyle'})
    return {'status': 'noted'}


def _write_fallback(kind, sid, row):
    _update(kind, sid, {'status_note': fallback_note(kind, row), 'next_steps': [],
                        'note_ts': time.time(), 'note_rev': int(row.get('rev') or 0),
                        'note_source': 'fallback'})


def request_refresh(kind: str, sid: str) -> None:
    """Coalesced: repeat requests inside REFRESH_DELAY_S for the same row
    collapse to one call, run on a timer thread so the mutator never waits."""
    key = (kind, sid)
    with _pending_lock:
        old = _pending.pop(key, None)
        if old:
            old.cancel()
        t = threading.Timer(REFRESH_DELAY_S, _run_pending, args=(key,))
        t.daemon = True
        _pending[key] = t
        t.start()


def _run_pending(key):
    with _pending_lock:
        _pending.pop(key, None)
    try:
        refresh(*key)
    except Exception as e:
        logger.warning(f"[situations] refresh failed for {key}: {e}")


def flush_refreshes() -> int:
    """Tests only: run everything pending now, on this thread."""
    with _pending_lock:
        keys = list(_pending)
        for t in _pending.values():
            t.cancel()
        _pending.clear()
    for key in keys:
        _run_pending(key)
    return len(keys)
```

- [ ] **Step 4: Hook the mutators**

Each hook is `from services import situations as _sit; _sit.bump_rev(kind, id); _sit.request_refresh(kind, id)` placed after the write succeeds. Add a tiny helper at the bottom of `situations.py` and call it instead:

```python
def touched(kind: str, sid: str) -> None:
    """A mutator says the row moved: bump rev, ask for a note."""
    bump_rev(kind, sid)
    request_refresh(kind, sid)
```

- `services/threads.py`: in `create` after `storage.add_thread`, in `advance`, `note`, `close`, `send_drafted`, `research` immediately before their `return True` / final return: `from services import situations as _sit; _sit.touched('thread', thread_id)`.
- `services/missions.py`: in `_close(mission_id, status, **fields)` before its return, and in `launch` after `storage.add_mission`: `_sit.touched('mission', mission_id)`. In `step()`, where a `proposal` step or an `ask` step is appended (the `add_mission_step` calls for `kind: 'proposal'` and the `ask_user` branch), add `_sit.touched('mission', mid)` after the append.
- `services/findings.py`: in `reconcile`, after each `storage.add_finding(...)` call: `situations.touched('finding', new_id)` (capture the returned id). Import inside the function to avoid an import cycle.
- `services/mind.py`: in `deep_think` after `storage.add_mind_insight(fields)` and in the revive branch after the revive update; in `make_plan` after the plan is written; in `close_step` after the step closes: `_sit.touched('insight', insight_id)`.
- `main.py` `/api/missions/{id}/answer` and `/drop`: after the write, `_sit.touched('mission', mission_id)`.

- [ ] **Step 5: Register the two caps**

In `services/settings_registry.py`, after the `mind_direct_categories` entry:

```python
    _e('situation_cap_notes', 'mind', 'Daily status-note cap',
       "Hard ceiling on the one-line status notes Argyle writes when a finding, insight, "
       "thread or mission changes (default 60). Over the cap the card shows the plain facts.",
       page='work?tab=mind', anchor='mind-general'),
    _e('ask_cap_drafts', 'mind', 'Daily ask-draft cap',
       "Hard ceiling on drafted asks per day (default 40). Over the cap a template draft is used.",
       page='work?tab=mind', anchor='mind-general'),
```

Then in `templates/components/mind_page.html`, in the settings drawer's Mind general section beside the existing cap inputs, add two number inputs bound to `s.situation_cap_notes` and `s.ask_cap_drafts` with the same markup as `mind_cap_handle` (copy that input block and change the key and label), and add both keys to the page's `s` defaults (`situation_cap_notes: 60, ask_cap_drafts: 40`). `tests/test_settings_registry.py` asserts every registered key is reachable on its page; run it.

- [ ] **Step 6: Run the tests**

Run: `env -u HA_BASE_URL ../venv/Scripts/python.exe tests/test_situations_refresh.py` → `6/6`. Then `env -u HA_BASE_URL ../venv/Scripts/python.exe tools/test.py situations threads missions watchers mind settings_registry` → all pass. The existing thread/mission/mind tests stub no pool for notes, so `refresh` hits `no_key` or the real `_pool_call`; the test settings in those files have no `llm_gemini_api_key` → `no_key`, no network. If one of them sets a key, stub `situations._pool_call = lambda *a, **k: {}` in its `_reset`.

- [ ] **Step 7: Commit**

Bump `config.yaml` to `2.499.304`.
```bash
git add chauffeur/config.yaml chauffeur/services chauffeur/main.py chauffeur/templates/components/mind_page.html chauffeur/tests/test_situations_refresh.py
git commit -m "feat(situations): Argyle's status note on state change - rev, coalescing, superseded results dropped, caps (v2.499.304)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push origin main
```

---

### Task 5: `services/asks.py` — channels, drafts, the ledger, claim-then-apply

**Files:**
- Modify: `services/asks.py` (replace the stub)
- Test: `tests/test_asks.py` (new)

**Interfaces:**
- Consumes: `storage.add_ask/get_ask/update_ask/get_asks`, `storage.set_assist_assignment`, `storage.add_assist_contact`, `agent_tools_v2.assign_driver_to_event_fuzzy`, `chat_actions.act_on_proposal`, `threads.advance`, `situations.touched`, `agent_tools_v2._post_chat_message`, `storage.get_or_create_dm`, `model_pools.call_pool_json`.
- Produces:
  - `CHANNELS = ('chauffeur', 'email', 'text', 'in_person')`
  - `channels_for(to: dict) -> list[dict]` → `[{'channel', 'label', 'link': str|None}]`
  - `create(kind, sid, to, what, channel, asked_by, unlocks=None, draft_mode='model', event=None, trusted=False) -> dict` → `{'status': 'success', 'ask': row}` (the row includes `draft_subject`, `draft_body`, `link`); `trusted=True` skips the role gate for the legacy coverage adapter only
  - `draft(ask, channel, settings=None) -> dict` → `{'subject', 'body', 'source': 'argyle'|'template'}`
  - `mark_sent(ask_id, actor) -> dict`
  - `withdraw(ask_id, actor) -> dict`
  - `answer(ask_id, answer, actor, reported=False) -> dict` → on yes includes `outcome`
  - `apply(ask_id) -> dict` (idempotent; claim → effect → outcome)
  - `recover(now=None) -> int` (claims older than `CLAIM_STALE_S`)
  - `asks_for(kind, sid, row=None) -> list`
  - `fingerprint_for_event(event_id) -> str|None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_asks.py
"""The asks ledger: every channel offered, a draft for each, the three answer
gates, and a yes that is claimed then applied exactly once — through
duplicate taps, a competing sibling, a moved event, a vanished event, a
failed effect and an interrupted claim."""
import datetime
import time
from unittest import mock

from harness import check  # noqa: F401
from services import storage, asks, situations

NOON = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
CALLS = []


def _reset():
    CALLS.clear()
    for t in (storage.asks_table, storage.findings_table, storage.members_table, storage.cache_table,
              storage.app_state_table, storage.assist_contacts_table, storage.assist_assignments_table,
              storage.assist_history_table, storage.chat_channels_table, storage.chat_messages_table,
              storage.drivers_table, storage.agent_action_proposals_table, storage.threads_table):
        t.truncate()
    storage.get_settings = lambda: {'calendar_ids': ['primary'], 'llm_gemini_api_key': ''}
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'dad', 'name': 'Dad', 'role': 'adult'})
    storage.add_member({'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True})
    storage.add_member({'id': 'nan', 'name': 'Nan', 'role': 'helper'})
    storage.add_assist_contact({'id': 'c1', 'name': 'Sarah', 'phone': '555-0100', 'kinds': ['driving'], 'active': True})
    storage.add_assist_contact({'id': 'c2', 'name': 'Mike', 'kinds': ['driving'], 'active': True})
    situations.REFRESH_DELAY_S = 0
    situations._pool_call = lambda *a, **k: {}


def _event(start=None):
    start = start or (NOON + datetime.timedelta(days=2)).replace(hour=16)
    storage.set_cached_schedule({'events': [{'id': 'ev1', 'title': 'Soccer', 'start': start.isoformat(),
                                             'end': (start + datetime.timedelta(hours=1)).isoformat()}],
                                 'assignments': {}, 'unassigned': ['ev1']})
    return start


def _finding(start):
    return storage.add_finding({'identity': 'unassigned:ev1', 'kind': 'unassigned', 'severity': 'decide',
                                'line': 'No driver yet: Soccer', 'subject_type': 'event', 'subject_id': 'ev1',
                                'due_at': start.timestamp(), 'state': 'open',
                                'fingerprint': f"ev1|{start.timestamp()}"})


def _unlocks(contact_id='c1'):
    return {'action_type': 'assist_assignment',
            'payload': {'event_id': 'ev1', 'contact_id': contact_id, 'event_title': 'Soccer',
                        'event_date': (NOON + datetime.timedelta(days=2)).date().isoformat()},
            'fingerprint': asks.fingerprint_for_event('ev1')}


def scenario_every_channel_is_offered_whatever_we_know():
    _reset()
    chans = {c['channel']: c for c in asks.channels_for({'name': 'Stranger'})}
    check(set(chans) == {'email', 'text', 'in_person'}, f"an outsider with nothing known: {set(chans)}")
    check(chans['email']['link'] is None and chans['text']['link'] is None, "no links without an address")
    chans = {c['channel']: c for c in asks.channels_for({'name': 'Sarah', 'contact_id': 'c1'})}
    check(chans['text']['link'] == 'sms:555-0100', f"a known number adds the one-tap link: {chans['text']}")
    chans = {c['channel']: c for c in asks.channels_for({'name': 'Dad', 'member_id': 'dad'})}
    check('chauffeur' in chans, "a member can be asked on Chauffeur")


def scenario_a_draft_for_every_channel():
    _reset()
    start = _event()
    fid = _finding(start)
    for ch in asks.CHANNELS:
        if ch == 'chauffeur':
            continue
        res = asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, 'drive Kate to Soccer Thursday',
                          ch, 'mom', unlocks=_unlocks())
        a = res['ask']
        check(res['status'] == 'success' and a['state'] == 'drafted' and a['draft_body'], f"{ch}: drafted")
        check('Sarah' in a['draft_body'] and 'Soccer' in a['draft_body'], f"{ch}: the draft names the ask")
        check(a['draft_source'] == 'template', "no key: the template draft")
    res = asks.create('finding', fid, {'name': 'Dad', 'member_id': 'dad'}, 'drive Kate Thursday', 'chauffeur', 'mom')
    a = res['ask']
    check(a['state'] == 'sent' and a['message_id'], "a Chauffeur ask is posted and sent at once")
    msg = storage.get_chat_message(a['message_id'])
    check(msg['card']['kind'] == 'ask' and msg['card']['what'] == 'drive Kate Thursday', f"the DM carries the ask card: {msg['card']}")
    check(msg['sender_member_id'] == 'mom', "the DM is from the asker")


def scenario_the_commitment_is_fixed():
    _reset()
    start = _event(); fid = _finding(start)
    a = asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, 'drive Kate', 'text', 'mom',
                    unlocks=_unlocks())['ask']
    check(storage.update_ask(a['id'], {'draft_body': 'Hi Sarah, could you grab Kate after?'}), "wording is editable")
    check(storage.get_ask(a['id'])['what'] == 'drive Kate', "the commitment did not move")
    res = asks.withdraw(a['id'], {'id': 'mom', 'role': 'parent'})
    check(res['status'] == 'success' and storage.get_ask(a['id'])['state'] == 'withdrawn', "withdrawn")
    res = asks.answer(a['id'], 'yes', {'id': 'mom', 'role': 'parent'}, reported=True)
    check(res['status'] == 'refused', "a withdrawn ask cannot be answered")


def scenario_three_answer_gates():
    _reset()
    start = _event(); fid = _finding(start)
    a = asks.create('finding', fid, {'name': 'Nan', 'member_id': 'nan'}, 'drive Kate', 'chauffeur', 'mom')['ask']
    check(asks.answer(a['id'], 'yes', {'id': 'kid', 'role': 'child'})['status'] == 'refused', "a bystander child is refused")
    check(asks.answer(a['id'], 'yes', {'id': 'dad', 'role': 'adult'}, reported=False)['status'] == 'refused',
          "an adult who is not the recipient cannot answer AS the recipient")
    res = asks.answer(a['id'], 'yes', {'id': 'nan', 'role': 'helper'})
    check(res['status'] == 'success' and storage.get_ask(a['id'])['answered_by'] == 'nan', f"the helper answers her own ask: {res}")
    b = asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, 'drive Kate', 'text', 'mom')['ask']
    asks.mark_sent(b['id'], {'id': 'mom', 'role': 'parent'})
    check(asks.answer(b['id'], 'no', {'id': 'kid', 'role': 'child'}, reported=True)['status'] == 'refused', "a child cannot report")
    check(asks.answer(b['id'], 'no', {'id': 'dad', 'role': 'adult'}, reported=True)['status'] == 'success', "an adult can report")
    check(asks.create('finding', fid, {'name': 'X'}, 'y', 'text', 'kid')['status'] == 'refused', "a child cannot create")


def _assignment_for(event_id='ev1'):
    return storage.get_assist_assignment_map().get(event_id)


def scenario_yes_applies_exactly_once_through_duplicate_taps():
    _reset()
    start = _event(); fid = _finding(start)
    a = asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, 'drive Kate', 'text', 'mom',
                    unlocks=_unlocks())['ask']
    asks.mark_sent(a['id'], {'id': 'mom', 'role': 'parent'})
    r1 = asks.answer(a['id'], 'yes', {'id': 'mom', 'role': 'parent'}, reported=True)
    r2 = asks.answer(a['id'], 'yes', {'id': 'mom', 'role': 'parent'}, reported=True)
    check(r1['status'] == 'success' and r1['outcome'] == 'applied', f"first yes applies: {r1}")
    check(r2['status'] == 'success' and r2['outcome'] == 'applied' and r2.get('already'), f"second yes is a no-op that reports: {r2}")
    check(_assignment_for() and _assignment_for().get('contact_id') == 'c1', "one assist assignment")
    check(len(storage.get_assist_history()) == 1 if hasattr(storage, 'get_assist_history') else True, "one history row")
    row = storage.get_ask(a['id'])
    check(row['state'] == 'yes' and row['applied_at'] and row['outcome'] == 'applied', f"ledger: {row}")


def scenario_sibling_yes_is_superseded():
    _reset()
    start = _event(); fid = _finding(start)
    a = asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, 'drive Kate', 'text', 'mom', unlocks=_unlocks('c1'))['ask']
    b = asks.create('finding', fid, {'name': 'Mike', 'contact_id': 'c2'}, 'drive Kate', 'text', 'mom', unlocks=_unlocks('c2'))['ask']
    for x in (a, b):
        asks.mark_sent(x['id'], {'id': 'mom', 'role': 'parent'})
    asks.answer(a['id'], 'yes', {'id': 'mom', 'role': 'parent'}, reported=True)
    r = asks.answer(b['id'], 'yes', {'id': 'mom', 'role': 'parent'}, reported=True)
    check(r['outcome'] == 'superseded' and 'Sarah' in r['message'], f"Mike's yes is recorded, not applied: {r}")
    check(_assignment_for().get('contact_id') == 'c1', "Sarah still has it")
    check(storage.get_ask(b['id'])['state'] == 'yes', "the yes itself is kept")


def scenario_moved_event_is_stale_and_vanished_event_is_stale():
    _reset()
    start = _event(); fid = _finding(start)
    a = asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, 'drive Kate', 'text', 'mom', unlocks=_unlocks())['ask']
    asks.mark_sent(a['id'], {'id': 'mom', 'role': 'parent'})
    _event(start + datetime.timedelta(hours=2))
    r = asks.answer(a['id'], 'yes', {'id': 'mom', 'role': 'parent'}, reported=True)
    check(r['outcome'] == 'stale' and 'moved' in r['message'], f"a moved event: {r}")
    check(not _assignment_for(), "nothing applied")
    b = asks.create('finding', fid, {'name': 'Mike', 'contact_id': 'c2'}, 'drive Kate', 'text', 'mom', unlocks=_unlocks('c2'))['ask']
    asks.mark_sent(b['id'], {'id': 'mom', 'role': 'parent'})
    storage.set_cached_schedule({'events': [], 'assignments': {}, 'unassigned': []})
    r = asks.answer(b['id'], 'yes', {'id': 'mom', 'role': 'parent'}, reported=True)
    check(r['outcome'] == 'stale', f"a vanished event is stale, never a crash: {r}")


def scenario_failed_effect_and_interrupted_claim_recover():
    _reset()
    start = _event(); fid = _finding(start)
    a = asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, 'drive Kate', 'text', 'mom', unlocks=_unlocks())['ask']
    asks.mark_sent(a['id'], {'id': 'mom', 'role': 'parent'})
    with mock.patch.object(storage, 'set_assist_assignment', side_effect=RuntimeError('db away')):
        r = asks.answer(a['id'], 'yes', {'id': 'mom', 'role': 'parent'}, reported=True)
    check(r['outcome'] == 'failed' and storage.get_ask(a['id'])['unlock_error'], f"a failed effect is recorded: {r}")
    # Interrupted after the claim: outcome stuck at 'claimed'. Recovery finishes it.
    b = asks.create('finding', fid, {'name': 'Mike', 'contact_id': 'c2'}, 'drive Kate', 'text', 'mom', unlocks=_unlocks('c2'))['ask']
    asks.mark_sent(b['id'], {'id': 'mom', 'role': 'parent'})
    storage.update_ask(b['id'], {'state': 'yes', 'answered_at': time.time(), 'answered_by': 'mom',
                                 'outcome': 'claimed', 'claim_ts': time.time() - 120})
    n = asks.recover(NOON)
    row = storage.get_ask(b['id'])
    check(n == 1 and row['outcome'] == 'applied' and _assignment_for().get('contact_id') == 'c2',
          f"the interrupted claim was finished once: {row}")
    # Interrupted after yes but before the claim: a retry proceeds to claim.
    c = asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, 'drive Kate', 'text', 'mom', unlocks=_unlocks('c1'))['ask']
    asks.mark_sent(c['id'], {'id': 'mom', 'role': 'parent'})
    storage.update_ask(c['id'], {'state': 'yes', 'answered_at': time.time(), 'answered_by': 'mom', 'outcome': None})
    r = asks.answer(c['id'], 'yes', {'id': 'mom', 'role': 'parent'}, reported=True)
    check(r['outcome'] == 'superseded', f"a retry claims, and the sibling already applied: {r}")


def scenario_no_returns_the_situation_to_its_options():
    _reset()
    start = _event(); fid = _finding(start)
    a = asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, 'drive Kate', 'text', 'mom', unlocks=_unlocks())['ask']
    asks.mark_sent(a['id'], {'id': 'mom', 'role': 'parent'})
    r = asks.answer(a['id'], 'no', {'id': 'mom', 'role': 'parent'}, reported=True)
    check(r['status'] == 'success' and storage.get_ask(a['id'])['state'] == 'no', "no is recorded")
    s = situations.view('finding', fid, viewer={'id': 'mom', 'role': 'parent'})
    check(any(x['state'] == 'no' and x['to_name'] == 'Sarah' for x in s['asks']), "the card shows who said no")
    check(any(o['verb'] == 'ask' for o in s['options']), "and the options are back")


SCENARIOS = [scenario_every_channel_is_offered_whatever_we_know, scenario_a_draft_for_every_channel,
             scenario_the_commitment_is_fixed, scenario_three_answer_gates,
             scenario_yes_applies_exactly_once_through_duplicate_taps, scenario_sibling_yes_is_superseded,
             scenario_moved_event_is_stale_and_vanished_event_is_stale,
             scenario_failed_effect_and_interrupted_claim_recover,
             scenario_no_returns_the_situation_to_its_options]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
```

- [ ] **Step 2: Run to verify failure**

Run: `env -u HA_BASE_URL ../venv/Scripts/python.exe tests/test_asks.py`
Expected: FAIL — `AttributeError: module 'services.asks' has no attribute 'channels_for'`.

- [ ] **Step 3: Write `services/asks.py`**

```python
"""Asks — the one ledger of who was asked what, by which channel, and what
came back. Spec: docs/superpowers/specs/2026-10-09-situations-design.md §2.

Three facts are kept apart on purpose: the ask (a fixed commitment, `what`),
the answer (`state` yes/no, who said so), and what the app did with a yes
(`outcome`: claimed → applied | superseded | stale | failed). Only `applied`
means the promised work was done. The app never sends mail or texts for an
ask; a draft is copied and sent by the person. A Chauffeur ask is a DM from
the asker with Yes/No buttons.
"""
import datetime
import logging
import time
from typing import Optional

from services import storage

logger = logging.getLogger(__name__)

CHANNELS = ('chauffeur', 'email', 'text', 'in_person')
CLAIM_STALE_S = 60
CAP_DRAFTS_DEFAULT = 40
WRITE_ROLES = ('parent', 'adult')

DRAFT_SYSTEM = (
    "You draft a short message a parent will send THEMSELVES, in their own "
    "voice, asking somebody for one concrete thing. At most 80 words. Only "
    "the facts given (what, when, where); no invented details, no pressure, "
    "an easy out. Return STRICT JSON: {\"subject\": \"...\", \"body\": \"...\"}. "
    "For a text or in-person channel the subject is an empty string."
)


# --- who, and how to reach them ----------------------------------------------

def _resolve_to(to: dict) -> dict:
    to = dict(to or {})
    member = storage.get_member(to['member_id']) if to.get('member_id') else None
    contact = storage.get_assist_contact(to['contact_id']) if to.get('contact_id') else None
    name = to.get('name') or (member or {}).get('name') or (contact or {}).get('name') or 'them'
    return {'name': name, 'member_id': (member or {}).get('id'), 'contact_id': (contact or {}).get('id'),
            'email': (member or {}).get('email') or (contact or {}).get('email') or '',
            'phone': (contact or {}).get('phone') or '',
            'active_member': bool(member) and member.get('status', 'active') == 'active'}


def channels_for(to: dict) -> list:
    """Every channel, always; a known address only adds the one-tap link."""
    r = _resolve_to(to)
    out = []
    if r['active_member']:
        out.append({'channel': 'chauffeur', 'label': f"Message {r['name']} on Chauffeur", 'link': None})
    out.append({'channel': 'email', 'label': 'Email', 'link': f"mailto:{r['email']}" if r['email'] else None})
    out.append({'channel': 'text', 'label': 'Text', 'link': f"sms:{r['phone']}" if r['phone'] else None})
    out.append({'channel': 'in_person', 'label': 'Ask in person', 'link': None})
    return out


# --- drafting ------------------------------------------------------------------

def _pool_call(tier, api_key, system, prompt, **kw):
    from services import model_pools
    return model_pools.call_pool_json(tier, api_key, system, prompt, **kw)


def _template(ask: dict, channel: str, asker_name: str) -> dict:
    name = ask.get('to_name') or 'there'
    body = f"Hi {name} — any chance you could {ask.get('what')}? No worries if not. Thanks, {asker_name}"
    if channel == 'in_person':
        body = f"Ask {name}: could you {ask.get('what')}?"
    return {'subject': f"Could you {ask.get('what')}?" if channel == 'email' else '', 'body': body,
            'source': 'template'}


def draft(ask: dict, channel: str, settings: dict = None) -> dict:
    settings = settings if settings is not None else (storage.get_settings() or {})
    asker = (storage.get_member(ask.get('asked_by') or '') or {}).get('name') or 'us'
    fallback = _template(ask, channel, asker)
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key:
        return fallback
    from services import situations as _sit
    cap = int(settings.get('ask_cap_drafts', CAP_DRAFTS_DEFAULT))
    if not _sit._bump_call('draft', cap):
        return fallback
    prompt = (f"From: {asker}. To: {ask.get('to_name')}. Channel: {channel}. "
              f"The ask: {ask.get('what')}.")
    try:
        res = _pool_call('interactive', api_key, DRAFT_SYSTEM, prompt, timeout_s=20,
                         background=False, workflow='asks.draft')
    except Exception as e:
        logger.warning(f"[asks] draft failed: {e}")
        res = None
    if not isinstance(res, dict) or not (res.get('body') or '').strip():
        return fallback
    return {'subject': (res.get('subject') or '')[:120] if channel == 'email' else '',
            'body': res['body'].strip()[:600], 'source': 'argyle'}


# --- the ledger ----------------------------------------------------------------

def fingerprint_for_event(event_id: str) -> Optional[str]:
    """Only the facts that would invalidate an agreement to cover a ride: the
    occurrence and its start. Never rev, never a sibling ask."""
    from services.situations import _cached_event, _parse
    ev = _cached_event(event_id)
    if not ev:
        return None
    start = _parse(ev.get('start'))
    return f"{event_id}|{start.timestamp() if start else ''}"


def asks_for(kind: str, sid: str, row: dict = None) -> list:
    rows = storage.get_asks(situation_kind=kind, situation_id=sid)
    if kind == 'finding' and row and row.get('subject_type') == 'event' and row.get('subject_id'):
        ids = {a['id'] for a in rows}
        fp = row.get('fingerprint')
        for a in storage.get_asks(event_id=row['subject_id']):
            # A legacy or situation-less event ask attaches by occurrence.
            if a['id'] not in ids and (not fp or (a.get('unlocks') or {}).get('fingerprint') in (None, fp)):
                rows.append(a)
    rows.sort(key=lambda a: a.get('asked_at') or 0)
    return rows


def _can_write(actor) -> bool:
    return bool(actor) and actor.get('role') in WRITE_ROLES


def create(kind: str, sid: Optional[str], to: dict, what: str, channel: str, asked_by: str,
           unlocks: dict = None, draft_mode: str = 'model', event: dict = None,
           trusted: bool = False) -> dict:
    """Record the ask and draft it. A Chauffeur ask is posted at once (it is
    the asker speaking through Argyle); every other channel waits for the
    person to say it left. `trusted` is for the legacy coverage adapter,
    whose endpoints already gated the caller (`_needs_you_actor`)."""
    asker = storage.get_member(asked_by or '') or {'id': asked_by or '', 'role': 'parent' if trusted else ''}
    if not trusted and not _can_write(asker):
        return {'status': 'refused', 'message': 'Only a parent or adult can ask.'}
    if channel not in CHANNELS or not (what or '').strip():
        return {'status': 'error', 'message': 'Say what to ask, and how.'}
    r = _resolve_to(to)
    if channel == 'chauffeur' and not r['active_member']:
        return {'status': 'error', 'message': f"{r['name']} is not on Chauffeur — text, email or ask in person."}
    data = {'situation_kind': kind, 'situation_id': sid, 'to_name': r['name'],
            'to_member_id': r['member_id'], 'to_contact_id': r['contact_id'],
            'what': what.strip(), 'channel': channel, 'asked_by': asker['id'],
            'unlocks': unlocks, 'event_id': (unlocks or {}).get('payload', {}).get('event_id') or (event or {}).get('id'),
            'event_start': (event or {}).get('start') or '', 'event_title': (event or {}).get('title') or ''}
    ask_id = storage.add_ask(data)
    row = storage.get_ask(ask_id)
    d = draft(row, channel) if draft_mode == 'model' else _template(row, channel, asker.get('name') or 'us')
    link = next((c['link'] for c in channels_for(to) if c['channel'] == channel), None)
    storage.update_ask(ask_id, {'draft_subject': d['subject'], 'draft_body': d['body'],
                                'draft_source': d['source'], 'link': link})
    if channel == 'chauffeur':
        _post(ask_id)
    _touch(kind, sid)
    return {'status': 'success', 'ask': storage.get_ask(ask_id)}


def _touch(kind, sid):
    if kind and sid:
        from services import situations as _sit
        _sit.touched(kind, sid)


def _card(ask: dict) -> dict:
    actions = [] if ask.get('state') in ('yes', 'no', 'withdrawn', 'expired') else [
        {'label': 'Yes', 'style': 'primary', 'ask_id': ask['id'], 'act': 'yes'},
        {'label': 'No', 'style': 'default', 'ask_id': ask['id'], 'act': 'no'}]
    return {'kind': 'ask', 'ask_id': ask['id'], 'what': ask.get('what'), 'state': ask.get('state'),
            'outcome': ask.get('outcome'), 'actions': actions}


def _post(ask_id: str) -> None:
    from services.agent_tools_v2 import _post_chat_message
    ask = storage.get_ask(ask_id)
    asker = storage.get_member(ask['asked_by']) or {}
    dm = storage.get_or_create_dm(ask['asked_by'], ask['to_member_id'])
    msg = _post_chat_message(dm, asker, ask.get('draft_body') or ask['what'], card=_card(ask))
    storage.update_ask(ask_id, {'state': 'sent', 'sent_at': time.time(),
                                'message_id': (msg or {}).get('id'), 'channel_id': dm.get('id')})


def _refresh_card(ask: dict) -> None:
    """The DM's Yes/No buttons follow the ledger, not the moment they were drawn."""
    if ask.get('message_id'):
        storage.update_chat_message_card(ask['message_id'], _card(ask))


def mark_sent(ask_id: str, actor: dict) -> dict:
    ask = storage.get_ask(ask_id)
    if not ask:
        return {'status': 'error', 'message': 'That ask is no longer here.'}
    if not (_can_write(actor) or (actor or {}).get('id') == ask.get('asked_by')):
        return {'status': 'refused', 'message': 'Only a parent or adult can do that.'}
    if ask['state'] != 'drafted':
        return {'status': 'success', 'message': 'Already noted.', 'ask': ask}
    storage.update_ask(ask_id, {'state': 'sent', 'sent_at': time.time()})
    _touch(ask.get('situation_kind'), ask.get('situation_id'))
    return {'status': 'success', 'message': f"Noted — asked {ask['to_name']}.", 'ask': storage.get_ask(ask_id)}


def withdraw(ask_id: str, actor: dict) -> dict:
    ask = storage.get_ask(ask_id)
    if not ask:
        return {'status': 'error', 'message': 'That ask is no longer here.'}
    if not _can_write(actor):
        return {'status': 'refused', 'message': 'Only a parent or adult can do that.'}
    if ask['state'] in ('yes', 'no'):
        return {'status': 'refused', 'message': 'That ask was already answered.'}
    storage.update_ask(ask_id, {'state': 'withdrawn', 'answered_at': time.time()})
    _refresh_card(storage.get_ask(ask_id))
    _touch(ask.get('situation_kind'), ask.get('situation_id'))
    return {'status': 'success', 'message': 'Withdrawn.'}


def answer(ask_id: str, answer: str, actor: dict, reported: bool = False) -> dict:
    """Three gates: the recipient answers their own ask (any role); the asker
    or a parent/adult REPORTS somebody else's answer. Answering never applies
    anything by itself; applying runs under the asker (see apply)."""
    ask = storage.get_ask(ask_id)
    if not ask:
        return {'status': 'error', 'message': 'That ask is no longer here.'}
    if answer not in ('yes', 'no'):
        return {'status': 'error', 'message': "Yes or no."}
    actor_id = (actor or {}).get('id')
    if reported:
        allowed = _can_write(actor) or actor_id == ask.get('asked_by')
    else:
        allowed = bool(actor_id) and actor_id == ask.get('to_member_id')
    if not allowed:
        return {'status': 'refused', 'message': "That ask isn't yours to answer."}
    if ask['state'] in ('withdrawn', 'expired'):
        return {'status': 'refused', 'message': f"That ask was {ask['state']}."}
    if ask['state'] == 'no':
        return {'status': 'success', 'message': 'Already answered no.', 'already': True}
    if ask['state'] == 'yes' and ask.get('outcome') not in (None, 'claimed'):
        return {'status': 'success', 'outcome': ask['outcome'], 'already': True,
                'message': _outcome_message(ask)}
    if answer == 'no':
        storage.update_ask(ask_id, {'state': 'no', 'answered_at': time.time(), 'answered_by': actor_id})
        _refresh_card(storage.get_ask(ask_id))
        _touch(ask.get('situation_kind'), ask.get('situation_id'))
        return {'status': 'success', 'message': f"OK — {ask['to_name']} can't. Back to the options."}
    if ask['state'] != 'yes':
        storage.update_ask(ask_id, {'state': 'yes', 'answered_at': time.time(), 'answered_by': actor_id})
    res = apply(ask_id)
    _refresh_card(storage.get_ask(ask_id))
    _touch(ask.get('situation_kind'), ask.get('situation_id'))
    return {'status': 'success', **res}


def _outcome_message(ask: dict) -> str:
    o = ask.get('outcome')
    if o == 'applied':
        return f"✓ {ask.get('to_name')} has it."
    if o == 'superseded':
        return f"{ask.get('to_name')} also said yes — {ask.get('superseded_by_name') or 'someone'} already has it; let them know."
    if o == 'stale':
        return f"{ask.get('to_name')} said yes, but the time moved — confirm with them."
    if o == 'failed':
        return f"{ask.get('to_name')} said yes; finish by hand: {ask.get('what')}."
    return ''


def _siblings(ask: dict) -> list:
    same = []
    for a in storage.get_asks(situation_kind=ask.get('situation_kind'), situation_id=ask.get('situation_id')) \
            if ask.get('situation_id') else []:
        same.append(a)
    if ask.get('event_id'):
        ids = {a['id'] for a in same}
        same += [a for a in storage.get_asks(event_id=ask['event_id']) if a['id'] not in ids]
    return [a for a in same if a['id'] != ask['id']]


def apply(ask_id: str) -> dict:
    """Claim under the lock, run the effect outside it, record the outcome.
    Idempotent: an ask already applied returns its outcome; a claim is taken
    only when no sibling on the same need holds one."""
    with storage.db_lock:
        ask = storage.get_ask(ask_id)
        if not ask or ask.get('state') != 'yes':
            return {'outcome': None, 'message': 'Not a yes.'}
        if ask.get('outcome') in ('applied', 'superseded', 'stale', 'failed'):
            return {'outcome': ask['outcome'], 'already': True, 'message': _outcome_message(ask)}
        unlocks = ask.get('unlocks') or {}
        if not unlocks:
            storage.update_ask(ask_id, {'outcome': 'applied', 'applied_at': time.time()})
            return {'outcome': 'applied', 'message': f"✓ {ask['to_name']} said yes."}
        if unlocks.get('fingerprint') and unlocks.get('action_type') == 'assist_assignment':
            now_fp = fingerprint_for_event(unlocks['payload'].get('event_id'))
            if now_fp != unlocks['fingerprint']:
                storage.update_ask(ask_id, {'outcome': 'stale', 'applied_at': time.time()})
                return {'outcome': 'stale', 'message': _outcome_message(storage.get_ask(ask_id))}
        winner = next((s for s in _siblings(ask)
                       if s.get('state') == 'yes' and s.get('outcome') in ('claimed', 'applied')), None)
        if winner:
            storage.update_ask(ask_id, {'outcome': 'superseded', 'applied_at': time.time(),
                                        'superseded_by': winner['id'], 'superseded_by_name': winner.get('to_name')})
            return {'outcome': 'superseded', 'message': _outcome_message(storage.get_ask(ask_id))}
        storage.update_ask(ask_id, {'outcome': 'claimed', 'claim_ts': time.time()})
    try:
        _effect(storage.get_ask(ask_id))
    except Exception as e:
        logger.warning(f"[asks] effect failed for {ask_id}: {e}")
        storage.update_ask(ask_id, {'outcome': 'failed', 'unlock_error': str(e)[:300], 'applied_at': time.time()})
        return {'outcome': 'failed', 'message': _outcome_message(storage.get_ask(ask_id))}
    storage.update_ask(ask_id, {'outcome': 'applied', 'applied_at': time.time(), 'unlock_error': None})
    return {'outcome': 'applied', 'message': _outcome_message(storage.get_ask(ask_id)), 'schedule_dirty': True}


def _effect(ask: dict) -> None:
    """The promised work, keyed by the ask id so running it twice is one effect."""
    u = ask.get('unlocks') or {}
    p = dict(u.get('payload') or {})
    kind = u.get('action_type')
    asker_id = ask.get('asked_by')
    if kind == 'assist_assignment':
        contact_id = p.get('contact_id') or ask.get('to_contact_id')
        if not contact_id:
            import uuid as _uuid
            contact_id = _uuid.uuid4().hex
            storage.add_assist_contact({'id': contact_id, 'name': ask.get('to_name') or 'A friend',
                                        'kinds': ['driving'], 'active': True})
            storage.update_ask(ask['id'], {'to_contact_id': contact_id})
        storage.set_assist_assignment(p['event_id'], contact_id, note=f"ask {ask['id']}",
                                      event_date=p.get('event_date') or '', event_title=p.get('event_title') or '',
                                      actor=asker_id)
        return
    if kind == 'reassign_driver':
        from services.agent_tools_v2 import assign_driver_to_event_fuzzy
        res = assign_driver_to_event_fuzzy(p.get('event_name'), p.get('driver_name'), p.get('target_date'))
        if res.get('status') != 'success':
            raise RuntimeError(res.get('message') or 'assign failed')
        return
    if kind == 'approve_proposal':
        from services import chat_actions as _ca
        res = _ca.act_on_proposal(p['proposal_id'], 'approve', storage.get_member(asker_id))
        if res.get('status') != 'success' and 'already approved' not in (res.get('message') or ''):
            raise RuntimeError(res.get('message') or 'approve failed')
        return
    if kind == 'thread_advance':
        from services import threads as _th
        _th.advance(p['thread_id'], p.get('next_action') or ask.get('what'), next_action_at=p.get('next_action_at'),
                    note=f"{ask.get('to_name')} said yes", who=asker_id)
        return
    raise RuntimeError(f"unknown unlock {kind}")


def recover(now: datetime.datetime = None) -> int:
    """A claim older than CLAIM_STALE_S was interrupted between claim and
    completion. Finish it — the effect is idempotent — or record failed."""
    now_ts = (now or datetime.datetime.now()).timestamp()
    n = 0
    for a in storage.get_asks(state='yes'):
        if a.get('outcome') == 'claimed' and now_ts - float(a.get('claim_ts') or 0) > CLAIM_STALE_S:
            try:
                _effect(a)
                storage.update_ask(a['id'], {'outcome': 'applied', 'applied_at': time.time()})
            except Exception as e:
                storage.update_ask(a['id'], {'outcome': 'failed', 'unlock_error': str(e)[:300],
                                             'applied_at': time.time()})
            _refresh_card(storage.get_ask(a['id']))
            _touch(a.get('situation_kind'), a.get('situation_id'))
            n += 1
        elif a.get('outcome') is None:
            apply(a['id'])
            n += 1
    return n
```

Add to `services/storage.py` after `get_chat_message`:

```python
def update_chat_message_card(message_id: str, card: dict) -> bool:
    with db_lock:
        return bool(chat_messages_table.update({'card': card}, Query().id == message_id))
```

And in `services/watchers.py` `run_watchers`, right after the reconcile `try/except`, add the recovery sweep:

```python
    try:
        from services import asks as _asks
        _asks.recover(now)
    except Exception as e:
        print(f"[watchers] ask recovery failed: {e}")
```

- [ ] **Step 4: Run the tests**

Run: `env -u HA_BASE_URL ../venv/Scripts/python.exe tests/test_asks.py` → `9/9`. If `storage.get_assist_history` does not exist the scenario's guarded check passes; if `set_assist_assignment` writes history twice for the same ask note, dedupe there is NOT this task's job — note it in the report.

- [ ] **Step 5: Commit**

Bump `config.yaml` to `2.499.305`.
```bash
git add chauffeur/config.yaml chauffeur/services/asks.py chauffeur/services/storage.py chauffeur/services/watchers.py chauffeur/tests/test_asks.py
git commit -m "feat(asks): the ledger - every channel a draft, three answer gates, claim-then-apply with recovery (v2.499.305)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push origin main
```

---

### Task 6: `coverage_options` becomes adapters; `coverage_asks` migrates

**Files:**
- Modify: `services/coverage_options.py` (`ladder` waiting lookup ~line 215; `start_ask` 281-309; `answer_ask` 312-366; `due_nudges` 373-397; `nudge_body` unchanged)
- Modify: `services/storage.py` (`get_coverage_asks`, `get_coverage_ask`, `add_coverage_ask`, `update_coverage_ask` at 3026-3053 become adapters)
- Modify: `services/migrations.py` (new `migrate_coverage_asks_v2499306` + its `run_all_migrations` entry)
- Modify: `main.py` `/api/coverage/asks/{ask_id}/answer` (5249-5263) and the nudge loop near 9264 (reads unchanged; ids now `asks` ids)
- Test: `tests/test_asks_migration.py` (new); `tests/test_coverage_ladder.py` unchanged and must pass

**Interfaces:**
- `storage.get_coverage_asks(state=None, event_id=None)` returns legacy-shaped rows read from `asks` (reverse state map: `sent→waiting`, `yes→covered` when `outcome=='applied'` else `waiting`-equivalent `yes`, `no→declined`, `expired→expired`, `withdrawn→declined`); `storage.get_coverage_ask(ask_id)` resolves an `asks` id or a `legacy_id`; `add_coverage_ask` and `update_coverage_ask` raise `RuntimeError('coverage_asks is read-only since v2.499.306; use asks')`.
- `coverage_options.start_ask` → `asks.create(..., channel='text', draft_mode='template')` + `mark_sent`; returns the same `{'status','ask_id','text','message'}` shape.
- `coverage_options.answer_ask(ask_id, answer, member_id, contact_name)` → same four answers, same return shapes including `schedule_dirty`.

- [ ] **Step 1: Write the failing migration test**

```python
# tests/test_asks_migration.py
"""coverage_asks → asks: idempotent, nudges intact, legacy ids resolve, a
legacy row never attaches to a newer occurrence's finding, and the old
endpoints still answer through the adapters."""
import asyncio
import datetime
import time

from harness import check  # noqa: F401
from services import storage, asks, migrations, coverage_options as cov

NOON = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)


def _reset():
    for t in (storage.asks_table, storage.coverage_asks_table, storage.findings_table, storage.members_table,
              storage.cache_table, storage.app_state_table, storage.assist_contacts_table,
              storage.assist_assignments_table, storage.assist_history_table):
        t.truncate()
    storage.get_settings = lambda: {'calendar_ids': ['primary']}
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_assist_contact({'id': 'c1', 'name': 'Sarah', 'kinds': ['driving'], 'active': True})


def _legacy(event_id, start, state='waiting', **kw):
    row = {'id': kw.pop('id', f"old-{event_id}-{state}"), 'event_id': event_id, 'event_title': 'Soccer',
           'event_date': start.date().isoformat(), 'event_start': start.isoformat(),
           'contact_id': 'c1', 'contact_name': 'Sarah', 'asked_by': 'mom', 'state': state,
           'asked_at': time.time() - 3600, 'nudges_sent': 1, 'rearmed_at': None, **kw}
    storage.coverage_asks_table.insert(row)
    return row


def scenario_migration_is_idempotent_and_keeps_nudges():
    _reset()
    start = (NOON + datetime.timedelta(days=2)).replace(hour=16)
    storage.set_cached_schedule({'events': [{'id': 'ev1', 'title': 'Soccer', 'start': start.isoformat(),
                                             'end': start.isoformat()}], 'assignments': {}, 'unassigned': ['ev1']})
    fid = storage.add_finding({'identity': 'unassigned:ev1', 'kind': 'unassigned', 'severity': 'decide',
                               'line': 'x', 'subject_type': 'event', 'subject_id': 'ev1',
                               'due_at': start.timestamp(), 'state': 'open', 'fingerprint': f"ev1|{start.timestamp()}"})
    _legacy('ev1', start)
    _legacy('ev1', start, state='covered', id='old-cov', resolved_at=time.time())
    asyncio.run(migrations.migrate_coverage_asks_v2499306())
    asyncio.run(migrations.migrate_coverage_asks_v2499306())
    rows = storage.get_asks(event_id='ev1')
    check(len(rows) == 2, f"two rows, once: {len(rows)}")
    by_legacy = {r['legacy_id']: r for r in rows}
    w = by_legacy['old-ev1-waiting']
    check(w['state'] == 'sent' and w['nudges_sent'] == 1 and w['channel'] == 'text', f"waiting→sent with nudges: {w}")
    check(w['situation_id'] == fid and w['situation_kind'] == 'finding', "attached to the matching finding")
    check((w['unlocks'] or {}).get('action_type') == 'assist_assignment', "legacy ask can still apply")
    c = by_legacy['old-cov']
    check(c['state'] == 'yes' and c['outcome'] == 'applied', f"covered→yes/applied: {c}")


def scenario_legacy_ask_does_not_attach_to_a_newer_occurrence():
    _reset()
    old_start = (NOON - datetime.timedelta(days=7)).replace(hour=16)
    new_start = (NOON + datetime.timedelta(days=2)).replace(hour=16)
    storage.set_cached_schedule({'events': [{'id': 'ev1', 'title': 'Soccer', 'start': new_start.isoformat(),
                                             'end': new_start.isoformat()}], 'assignments': {}, 'unassigned': ['ev1']})
    storage.add_finding({'identity': 'unassigned:ev1', 'kind': 'unassigned', 'severity': 'decide', 'line': 'x',
                         'subject_type': 'event', 'subject_id': 'ev1', 'due_at': new_start.timestamp(),
                         'state': 'open', 'fingerprint': f"ev1|{new_start.timestamp()}"})
    _legacy('ev1', old_start)
    asyncio.run(migrations.migrate_coverage_asks_v2499306())
    row = storage.get_asks(event_id='ev1')[0]
    check(row['situation_id'] is None, f"an older occurrence's ask has no situation: {row['situation_id']}")
    res = cov.answer_ask('old-ev1-waiting', 'no', member_id='mom')
    check(res['status'] == 'success' and storage.get_ask(row['id'])['state'] == 'no',
          "the legacy id still answers through the adapter")


def scenario_adapters_keep_the_old_shape():
    _reset()
    start = (NOON + datetime.timedelta(days=2)).replace(hour=16)
    storage.set_cached_schedule({'events': [{'id': 'ev1', 'title': 'Soccer', 'start': start.isoformat(),
                                             'end': start.isoformat()}], 'assignments': {}, 'unassigned': ['ev1']})
    res = cov.start_ask('ev1', 'c1', asked_by='mom')
    check(res['status'] == 'success' and res['ask_id'] and 'Soccer' in res['text'], f"start_ask shape: {res}")
    legacy = storage.get_coverage_ask(res['ask_id'])
    check(legacy and legacy['state'] == 'waiting' and legacy['contact_name'] == 'Sarah', f"legacy read shape: {legacy}")
    check([a['id'] for a in storage.get_coverage_asks(state='waiting')] == [res['ask_id']], "listing maps state")
    ans = cov.answer_ask(res['ask_id'], 'covered', member_id='mom')
    check(ans['status'] == 'success' and ans.get('schedule_dirty'), f"covered applies: {ans}")
    check(storage.get_coverage_ask(res['ask_id'])['state'] == 'covered', "reads back as covered")
    cov.answer_ask(res['ask_id'], 'undo', member_id='mom')
    check(storage.get_coverage_ask(res['ask_id'])['state'] == 'waiting', "undo rearms")
    check(not storage.get_assist_assignment_map().get('ev1'), "undo cleared the assignment")
    try:
        storage.add_coverage_ask({'event_id': 'ev1'})
        check(False, "add_coverage_ask must refuse")
    except RuntimeError:
        pass


SCENARIOS = [scenario_migration_is_idempotent_and_keeps_nudges,
             scenario_legacy_ask_does_not_attach_to_a_newer_occurrence,
             scenario_adapters_keep_the_old_shape]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
```

- [ ] **Step 2: Run to verify failure**

Run: `env -u HA_BASE_URL ../venv/Scripts/python.exe tests/test_asks_migration.py`
Expected: FAIL — `AttributeError: module 'services.migrations' has no attribute 'migrate_coverage_asks_v2499306'`.

- [ ] **Step 3: The storage adapters**

Replace the four coverage functions in `services/storage.py`:

```python
# --- coverage_asks: READ-ONLY legacy since v2.499.306. The ledger is `asks`
# (services/asks.py); these readers map an asks row back to the shape the
# coverage ladder, the nudge loop and the old DM buttons were written for.

_ASK_TO_LEGACY = {'drafted': 'waiting', 'sent': 'waiting', 'no': 'declined',
                  'withdrawn': 'declined', 'expired': 'expired'}

def _legacy_ask_view(a: dict) -> dict:
    state = _ASK_TO_LEGACY.get(a.get('state'), 'waiting')
    if a.get('state') == 'yes':
        state = 'covered' if a.get('outcome') == 'applied' else 'waiting'
    return {'id': a['id'], 'event_id': a.get('event_id'), 'event_title': a.get('event_title'),
            'event_date': a.get('event_date'), 'event_start': a.get('event_start'),
            'contact_id': a.get('to_contact_id') or '', 'contact_name': a.get('to_name') or '',
            'asked_by': a.get('asked_by') or '', 'state': state,
            'asked_at': a.get('sent_at') or a.get('asked_at'), 'nudges_sent': a.get('nudges_sent') or 0,
            'rearmed_at': a.get('rearmed_at'), 'resolved_at': a.get('answered_at'),
            'resolved_by': a.get('answered_by') or '', 'legacy_id': a.get('legacy_id')}

def get_coverage_asks(state: str = None, event_id: str = None) -> List[dict]:
    rows = [_legacy_ask_view(a) for a in get_asks(event_id=event_id) if a.get('event_id')]
    if state:
        rows = [a for a in rows if a.get('state') == state]
    rows.sort(key=lambda a: a.get('asked_at') or 0)
    return rows

def get_coverage_ask(ask_id: str) -> Optional[dict]:
    a = get_ask(ask_id) or get_ask_by_legacy_id(ask_id)
    return _legacy_ask_view(a) if a else None

def add_coverage_ask(data: dict) -> str:
    raise RuntimeError('coverage_asks is read-only since v2.499.306; use asks')

def update_coverage_ask(ask_id: str, data: dict) -> bool:
    raise RuntimeError('coverage_asks is read-only since v2.499.306; use asks')
```

- [ ] **Step 4: The coverage_options adapters**

In `ladder`, replace the `waiting` lookup with `waiting = [a for a in storage.get_asks(event_id=ev_id, state='sent')]` and read `who` from `waiting[0].get('to_name')`. Replace `start_ask`, `answer_ask`, `due_nudges`:

```python
def start_ask(event_id: str, contact_id: str = None, contact_name: str = None,
              asked_by: str = None) -> dict:
    """Record that a parent is asking somebody. Returns the drafted text — the
    parent sends it themselves. Since v2.499.306 this is an adapter over
    services.asks: a text-channel ask, template-drafted (no LLM call on this
    path), sent at once."""
    from services import asks as _asks
    cache = storage.get_cached_schedule() or {}
    ev = next((e for e in (cache.get('events') or [])
               if str(e.get('id')) == str(event_id)), None)
    if not ev:
        return {'status': 'error', 'message': 'That event is not in the current schedule.'}
    contact = storage.get_assist_contact(contact_id) if contact_id else None
    name = contact_name or (contact or {}).get('name') or ''
    start = _parse(ev.get('start'))
    title = ev.get('title') or 'an event'
    when = f" {start.strftime('%A')} at {start.strftime('%I:%M %p').lstrip('0')}" if start else ''
    finding = storage.get_finding_by_identity(f"unassigned:{event_id}")
    sid = finding['id'] if finding and finding.get('fingerprint') == f"{event_id}|{start.timestamp() if start else ''}" \
        and finding.get('state') in ('open', 'in_hand') else None
    res = _asks.create('finding', sid, {'name': name, 'contact_id': contact_id}, f"take {title}{when}",
                       'text', asked_by or '', draft_mode='template', event=ev, trusted=True,
                       unlocks={'action_type': 'assist_assignment',
                                'payload': {'event_id': str(event_id), 'contact_id': contact_id or '',
                                            'event_title': title,
                                            'event_date': start.date().isoformat() if start else ''},
                                'fingerprint': _asks.fingerprint_for_event(str(event_id))})
    if res.get('status') != 'success':
        return res
    ask = res['ask']
    _asks.mark_sent(ask['id'], storage.get_member(asked_by or '') or {'id': asked_by or '', 'role': 'parent'})
    try:
        import datetime as _dt
        storage.bump_day_counter(_dt.date.today().isoformat(), 'coverage_ask')
    except Exception:
        pass
    text = draft_ask(ev, name or None)
    return {'status': 'success', 'ask_id': ask['id'], 'text': text,
            'message': f"Asked{' ' + name if name else ''} — I'll check back. "
                       f"Send this:\n\n{text}"}


def answer_ask(ask_id: str, answer: str, member_id: str = None,
               contact_name: str = None) -> dict:
    """covered | no | waiting | undo — the legacy vocabulary, over the asks
    ledger. 'covered' is a reported yes, which applies (once) the assist
    assignment that takes the event out of the solve."""
    from services import asks as _asks
    ask = storage.get_ask(ask_id) or storage.get_ask_by_legacy_id(ask_id)
    if not ask:
        return {'status': 'error', 'message': 'That ask is no longer here.'}
    actor = storage.get_member(member_id or '') or {'id': member_id, 'role': 'parent'}
    name = contact_name or ask.get('to_name') or 'They'

    if answer == 'waiting':
        storage.update_ask(ask['id'], {'nudges_sent': 0, 'rearmed_at': _now_ts()})
        return {'status': 'success', 'message': "Fine — I'll ask again later."}

    if answer == 'undo':
        if ask.get('to_contact_id') and ask.get('event_id'):
            storage.clear_assist_assignment(ask['event_id'], actor=member_id)
        storage.update_ask(ask['id'], {'state': 'sent', 'answered_at': None, 'answered_by': None,
                                       'outcome': None, 'applied_at': None, 'nudges_sent': 0,
                                       'rearmed_at': _now_ts()})
        return {'status': 'success', 'message': 'Undone — still waiting to hear.'}

    if answer == 'no':
        res = _asks.answer(ask['id'], 'no', actor, reported=True)
        if res.get('status') != 'success':
            return res
        return {'status': 'success', 'message': f"OK — {name} can't. Back to the list."}

    if answer != 'covered':
        return {'status': 'error', 'message': f"Unknown answer '{answer}'."}

    if not ask.get('to_contact_id'):
        import uuid as _uuid
        new_name = (contact_name or '').strip() or 'A friend'
        cid = _uuid.uuid4().hex
        storage.add_assist_contact({'id': cid, 'name': new_name, 'kinds': ['driving'], 'active': True})
        unlocks = dict(ask.get('unlocks') or {})
        unlocks.setdefault('payload', {})['contact_id'] = cid
        storage.update_ask(ask['id'], {'to_contact_id': cid, 'to_name': new_name, 'unlocks': unlocks})
        name = new_name
    res = _asks.answer(ask['id'], 'yes', actor, reported=True)
    if res.get('status') != 'success':
        return res
    if res.get('outcome') != 'applied':
        return {'status': 'success', 'message': res.get('message') or '', 'outcome': res.get('outcome')}
    return {'status': 'success', 'schedule_dirty': True,
            'message': f"✓ {name} has {ask.get('event_title') or 'it'}."}


def due_nudges(now=None) -> list:
    """Sent event asks whose next question is due; an ask whose event has
    passed expires here. Same cadence as before; rows are legacy-shaped so
    the push loop in main.py reads them unchanged."""
    now = now or datetime.datetime.now()
    now_ts = now.timestamp()
    out = []
    for ask in storage.get_asks(state='sent'):
        if not ask.get('event_id'):
            continue
        base = ask.get('rearmed_at') or ask.get('sent_at') or ask.get('asked_at') or 0
        sent = int(ask.get('nudges_sent') or 0)
        start = _parse(ask.get('event_start'))
        if start and start < now:
            storage.update_ask(ask['id'], {'state': 'expired', 'answered_at': now_ts})
            continue
        final_due = (start - datetime.timedelta(hours=FINAL_NUDGE_LEAD_HOURS) if start else None)
        due = False
        if sent < len(NUDGE_SCHEDULE_HOURS):
            due = now_ts - base >= NUDGE_SCHEDULE_HOURS[sent] * 3600
        elif final_due and now >= final_due and sent == len(NUDGE_SCHEDULE_HOURS):
            due = True
        if due:
            out.append(storage._legacy_ask_view(ask))
    return out
```

Where the nudge loop in `main.py` (~9264-9300) increments `nudges_sent` with `storage.update_coverage_ask`, change that one call to `storage.update_ask(ask['id'], {'nudges_sent': ...})`. `/api/coverage/asks/{ask_id}/answer` stays as it is (it calls `answer_ask`, which now resolves legacy ids). `GET /api/coverage/asks` stays (reads the adapter).

- [ ] **Step 5: The migration**

In `services/migrations.py`:

```python
async def migrate_coverage_asks_v2499306():
    """coverage_asks → asks (the one ledger, spec §2). Idempotent by legacy_id.
    event_id + event_start are the authoritative link; situation_id is set
    only when a finding exists for that exact occurrence. The old table is
    left in place, read-only, for one release of recovery."""
    from services import storage, asks as _asks
    done = 0
    with storage.db_lock:
        legacy = [dict(r) for r in storage.coverage_asks_table.all()]
    state_map = {'waiting': 'sent', 'covered': 'yes', 'declined': 'no', 'expired': 'expired'}
    for r in legacy:
        if storage.get_ask_by_legacy_id(r['id']):
            continue
        start = None
        try:
            start = datetime.datetime.fromisoformat(str(r.get('event_start') or '').replace('Z', '+00:00')).replace(tzinfo=None)
        except (TypeError, ValueError):
            pass
        fp = f"{r.get('event_id')}|{start.timestamp() if start else ''}"
        finding = storage.get_finding_by_identity(f"unassigned:{r.get('event_id')}")
        sid = finding['id'] if finding and finding.get('fingerprint') == fp else None
        state = state_map.get(r.get('state'), 'sent')
        storage.add_ask({
            'legacy_id': r['id'], 'situation_kind': 'finding', 'situation_id': sid,
            'event_id': str(r.get('event_id') or ''), 'event_start': r.get('event_start') or '',
            'event_title': r.get('event_title') or '', 'event_date': r.get('event_date') or '',
            'to_name': r.get('contact_name') or '', 'to_contact_id': r.get('contact_id') or None,
            'to_member_id': None, 'what': f"take {r.get('event_title') or 'the ride'}",
            'channel': 'text', 'asked_by': r.get('asked_by') or '',
            'asked_at': r.get('asked_at') or time.time(), 'sent_at': r.get('asked_at'),
            'state': state, 'nudges_sent': int(r.get('nudges_sent') or 0),
            'rearmed_at': r.get('rearmed_at'), 'answered_at': r.get('resolved_at'),
            'answered_by': r.get('resolved_by') or None,
            'outcome': 'applied' if state == 'yes' else None,
            'applied_at': r.get('resolved_at') if state == 'yes' else None,
            'unlocks': {'action_type': 'assist_assignment',
                        'payload': {'event_id': str(r.get('event_id') or ''), 'contact_id': r.get('contact_id') or '',
                                    'event_title': r.get('event_title') or '', 'event_date': r.get('event_date') or ''},
                        'fingerprint': fp},
            'draft_body': '', 'draft_subject': '', 'draft_source': 'template', 'link': None})
        done += 1
    if done:
        logger.info(f"v2.499.306 coverage_asks migration: {done} asks carried into the ledger")
```

Add `import datetime` at the top of `migrations.py` if missing, and to `run_all_migrations`:

```python
    try:
        await migrate_coverage_asks_v2499306()
    except Exception as e:
        logger.error(f"Error running coverage asks migration: {e}")
```

- [ ] **Step 6: Run the tests**

Run: `env -u HA_BASE_URL ../venv/Scripts/python.exe tests/test_asks_migration.py` → `3/3`; then `env -u HA_BASE_URL ../venv/Scripts/python.exe tools/test.py coverage_ladder assist asks watchers needs_you chat_actions` — all pass. `test_coverage_ladder.py` truncates `coverage_asks_table` in its `_reset`; add `storage.asks_table` to that tuple (the only permitted edit to that file).

- [ ] **Step 7: Commit**

Bump `config.yaml` to `2.499.306`.
```bash
git add chauffeur/config.yaml chauffeur/services/coverage_options.py chauffeur/services/storage.py chauffeur/services/migrations.py chauffeur/main.py chauffeur/tests/test_asks_migration.py chauffeur/tests/test_coverage_ladder.py
git commit -m "refactor(coverage): coverage_asks migrate into the asks ledger; coverage_options and the legacy readers become adapters (v2.499.306)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push origin main
```

---
### Task 7: Endpoints — situations, asks, and the ask card in chat

**Files:**
- Modify: `main.py` (new block after `/api/mind/admin`, ~line 5566; `renderCard` consumer is the PWA, Task 9)
- Modify: `templates/app.html` `renderCard` (5415-5436) and a new `answerAsk` beside `actOnProposal` (5438-5451)
- Test: `tests/test_situation_endpoints.py` (new)

**Interfaces:**
- `GET /api/situations?kinds=finding,insight&include_done=0` → `{"situations": [...]}` (viewer = `_acting_id`; any caller; filtered by `situations.can_see`)
- `GET /api/situations/{kind}/{sid}` → the situation or 404; 403 when `can_see` is false
- `POST /api/situations/{kind}/{sid}/act` body `{verb, option_id, payload, member_id}` → `situations.act(...)`; actor = `_approver_of_record(_mind_actor(request, member_id))`; `refused` → 403, `error` → 400; `schedule_dirty` → `trigger_background_refresh`
- `POST /api/asks` body `{kind, id, option_id, to: {name, member_id?, contact_id?}, what?, channel, member_id}` → when `option_id` names an `ask` option on that situation, `to`/`what`/`unlocks` come from it (the client may override `to` only when the option's `to` is empty); else a free ask with no `unlocks`. Returns `{status, ask, channels}`.
- `POST /api/asks/{id}/sent`, `POST /api/asks/{id}/withdraw` → parent/adult or asker
- `POST /api/asks/{id}/answer` body `{answer: yes|no, reported: bool, member_id}` → gate inside `asks.answer`; 403 on `refused`
- `GET /api/asks/{id}/channels` → `asks.channels_for(to)` for that ask's recipient

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_situation_endpoints.py
"""The situation and ask endpoints: viewer filtering, the three answer gates
through HTTP, server-bound options, and the ask card's buttons."""
import datetime

from harness import check  # noqa: F401
from services import storage, situations, asks, auth as _auth

NOON = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)


class _Req:
    def __init__(self, member_id=None):
        self.headers = {}
        self.query_params = {'member_id': member_id} if member_id else {}


def _reset():
    for t in (storage.asks_table, storage.findings_table, storage.mind_insights_table, storage.members_table,
              storage.cache_table, storage.app_state_table, storage.assist_contacts_table,
              storage.chat_channels_table, storage.chat_messages_table, storage.threads_table,
              storage.missions_table, storage.mission_steps_table):
        t.truncate()
    storage.get_settings = lambda: {'calendar_ids': ['primary']}
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'nan', 'name': 'Nan', 'role': 'helper'})
    storage.add_member({'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True})
    situations.REFRESH_DELAY_S = 0
    situations._pool_call = lambda *a, **k: {}
    start = (NOON + datetime.timedelta(days=2)).replace(hour=16)
    storage.set_cached_schedule({'events': [{'id': 'ev1', 'title': 'Soccer', 'start': start.isoformat(),
                                             'end': start.isoformat()}], 'assignments': {}, 'unassigned': ['ev1']})
    fid = storage.add_finding({'identity': 'unassigned:ev1', 'kind': 'unassigned', 'severity': 'decide',
                               'line': 'No driver yet', 'subject_type': 'event', 'subject_id': 'ev1',
                               'due_at': start.timestamp(), 'state': 'open', 'fingerprint': f"ev1|{start.timestamp()}"})
    iid = storage.add_mind_insight({'slug': 's', 'line': 'quiet week', 'category': 'c', 'approach': 'x', 'identity': 'c:1'})
    return fid, iid


def _as(member_id):
    """Resolve the PWA's claimed member the way _acting_id does, without HTTP."""
    _auth.acting_member = lambda h, q, claimed=None: {'id': member_id} if member_id else {}
    _auth.impersonation_refused = lambda acting: False
    _auth.identify = lambda h, q: {'tier': _auth.MEMBER if member_id else _auth.SERVICE, 'member': None}


def scenario_list_is_viewer_filtered():
    fid, iid = _reset()
    import main
    _as('mom')
    rows = main.situations_list(kinds='finding,insight', request=_Req('mom'))['situations']
    check({r['id'] for r in rows} == {fid, iid}, f"a parent sees both: {[r['id'] for r in rows]}")
    _as('kid')
    rows = main.situations_list(kinds='finding,insight', request=_Req('kid'))['situations']
    check([r['id'] for r in rows] == [iid], "a child sees the insight only")


def scenario_act_is_server_bound_and_gated():
    fid, iid = _reset()
    import main
    from fastapi import HTTPException
    _as('kid')
    try:
        main.situations_act('finding', fid, body={'verb': 'dismiss', 'option_id': 'dismiss', 'member_id': 'kid'},
                            request=_Req('kid'), background_tasks=None)
        check(False, "a child must be refused")
    except HTTPException as e:
        check(e.status_code == 403, f"403 for a child, got {e.status_code}")
    _as('mom')
    res = main.situations_act('finding', fid, body={'verb': 'dismiss', 'option_id': 'dismiss', 'member_id': 'mom'},
                              request=_Req('mom'), background_tasks=None)
    check(res['status'] == 'success' and storage.get_finding(fid)['state'] == 'dismissed', "a parent dismisses")


def scenario_ask_flow_over_http():
    fid, iid = _reset()
    import main
    from fastapi import HTTPException
    _as('mom')
    s = main.situation_get('finding', fid, request=_Req('mom'))
    opt = next(o for o in s['options'] if o['verb'] == 'ask' and o['id'] == 'ask:new')
    res = main.asks_create(body={'kind': 'finding', 'id': fid, 'option_id': opt['id'],
                                 'to': {'name': 'Nan', 'member_id': 'nan'}, 'channel': 'chauffeur', 'member_id': 'mom'},
                           request=_Req('mom'))
    a = res['ask']
    check(a['state'] == 'sent' and a['to_member_id'] == 'nan' and (a['unlocks'] or {}).get('action_type') == 'assist_assignment',
          f"an ask from an option carries the server's unlocks: {a}")
    check({c['channel'] for c in res['channels']} >= {'email', 'text', 'in_person'}, "channels come back with it")
    # The bystander child cannot answer; the recipient helper can.
    _as('kid')
    try:
        main.asks_answer(a['id'], body={'answer': 'yes', 'member_id': 'kid'}, request=_Req('kid'), background_tasks=None)
        check(False, "a bystander must be refused")
    except HTTPException as e:
        check(e.status_code == 403, "403 for a bystander")
    _as('nan')
    res = main.asks_answer(a['id'], body={'answer': 'yes', 'member_id': 'nan'}, request=_Req('nan'), background_tasks=None)
    check(res['status'] == 'success' and res['outcome'] == 'applied', f"the helper's own yes applies: {res}")
    msg = storage.get_chat_message(a['message_id'])
    check(msg['card']['state'] == 'yes' and msg['card']['actions'] == [], "the DM card followed the ledger")


def scenario_answer_gate_refuses_a_bystander():
    fid, iid = _reset()
    import main
    from fastapi import HTTPException
    _as('mom')
    res = main.asks_create(body={'kind': 'finding', 'id': fid, 'to': {'name': 'Nan', 'member_id': 'nan'},
                                 'what': 'drive Kate', 'channel': 'chauffeur', 'member_id': 'mom'}, request=_Req('mom'))
    a = res['ask']
    _as('kid')
    try:
        main.asks_answer(a['id'], body={'answer': 'no', 'member_id': 'kid'}, request=_Req('kid'), background_tasks=None)
        check(False, "refused")
    except HTTPException as e:
        check(e.status_code == 403 and storage.get_ask(a['id'])['state'] == 'sent', "refused, ledger untouched")


SCENARIOS = [scenario_list_is_viewer_filtered, scenario_act_is_server_bound_and_gated,
             scenario_ask_flow_over_http, scenario_answer_gate_refuses_a_bystander]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
```

- [ ] **Step 2: Run to verify failure**

Run: `env -u HA_BASE_URL ../venv/Scripts/python.exe tests/test_situation_endpoints.py`
Expected: FAIL — `AttributeError: module 'main' has no attribute 'situations_list'`.

- [ ] **Step 3: Add the endpoints to `main.py`** (after `/api/mind/admin`)

```python
# --- Situations: one shape for everything that needs a person --------------
# Spec: docs/superpowers/specs/2026-10-09-situations-design.md. Reads filter by
# the viewer (a wall and a child see the same thing); writes are parent/adult,
# except answering an ask addressed to you.

def _situation_viewer(request):
    viewer_id = _acting_id(request, None)
    return storage.get_member(viewer_id) if viewer_id else None


@app.get("/api/situations")
def situations_list(kinds: str = None, include_done: int = 0, request: Request = None):
    from services import situations as _sit
    want = tuple(k for k in (kinds or '').split(',') if k in _sit.KINDS) or None
    return {"situations": _sit.list_situations(_situation_viewer(request), kinds=want,
                                               include_done=bool(include_done))}


@app.get("/api/situations/{kind}/{sid}")
def situation_get(kind: str, sid: str, request: Request = None):
    from services import situations as _sit
    row = _sit.load(kind, sid)
    if not row:
        raise HTTPException(status_code=404, detail="No such situation")
    viewer = _situation_viewer(request)
    if not _sit.can_see(kind, row, viewer) and not _is_admin_surface(request):
        raise HTTPException(status_code=403, detail="Not yours to see")
    return _sit.view(kind, sid, viewer)


@app.post("/api/situations/{kind}/{sid}/act")
def situations_act(kind: str, sid: str, body: dict = Body(default={}),
                   request: Request = None, background_tasks: BackgroundTasks = None):
    from services import situations as _sit
    actor = _approver_of_record(_mind_actor(request, body.get('member_id')))
    res = _sit.act(kind, sid, body.get('verb') or '', option_id=body.get('option_id'),
                   payload=body.get('payload') or {}, actor=actor)
    if res.get('status') == 'refused':
        raise HTTPException(status_code=403, detail=res.get('message'))
    if res.get('status') == 'error':
        raise HTTPException(status_code=400, detail=res.get('message'))
    _mind_refresh_if_dirty(res, background_tasks)
    return res


@app.post("/api/asks")
def asks_create(body: dict = Body(default={}), request: Request = None):
    from services import situations as _sit, asks as _asks
    actor = _approver_of_record(_mind_actor(request, body.get('member_id')))
    kind, sid = body.get('kind'), body.get('id')
    to, what, unlocks = dict(body.get('to') or {}), (body.get('what') or '').strip(), None
    if body.get('option_id') and kind and sid:
        row = _sit.load(kind, sid)
        opt = next((o for o in _sit.options_for(kind, row or {}) if o['id'] == body['option_id']
                    and o['verb'] == 'ask'), None) if row else None
        if not opt:
            raise HTTPException(status_code=400, detail="That ask is no longer on the table")
        p = opt['payload']
        what = p.get('what') or what
        unlocks = p.get('unlocks')
        if p.get('to', {}).get('contact_id') or p.get('to', {}).get('member_id'):
            to = p['to']
        if unlocks and unlocks.get('action_type') == 'assist_assignment' and to.get('contact_id'):
            unlocks = {**unlocks, 'payload': {**unlocks['payload'], 'contact_id': to['contact_id']}}
    res = _asks.create(kind, sid, to, what, body.get('channel') or '', actor['id'], unlocks=unlocks,
                       event=_sit._cached_event((unlocks or {}).get('payload', {}).get('event_id')) if unlocks else None)
    if res.get('status') == 'refused':
        raise HTTPException(status_code=403, detail=res.get('message'))
    if res.get('status') != 'success':
        raise HTTPException(status_code=400, detail=res.get('message'))
    return {**res, 'channels': _asks.channels_for(to)}


@app.get("/api/asks/{ask_id}/channels")
def asks_channels(ask_id: str, request: Request = None):
    from services import asks as _asks
    _mind_actor(request, None)
    a = storage.get_ask(ask_id)
    if not a:
        raise HTTPException(status_code=404, detail="No such ask")
    return {"channels": _asks.channels_for({'name': a['to_name'], 'member_id': a.get('to_member_id'),
                                            'contact_id': a.get('to_contact_id')})}


def _ask_actor(request, claimed):
    """Any resolved member — the gate is inside asks.answer (the recipient of
    an ask may answer it whatever their role). Admin surfaces nominate the
    parent of record, as every other control-center write does."""
    actor_id = _acting_id(request, claimed)
    actor = storage.get_member(actor_id) if actor_id else None
    if actor:
        return actor
    if _is_admin_surface(request):
        return _approver_of_record(None)
    raise HTTPException(status_code=403, detail="Sign in first")


@app.post("/api/asks/{ask_id}/sent")
def asks_sent(ask_id: str, body: dict = Body(default={}), request: Request = None):
    from services import asks as _asks
    res = _asks.mark_sent(ask_id, _ask_actor(request, body.get('member_id')))
    if res.get('status') == 'refused':
        raise HTTPException(status_code=403, detail=res.get('message'))
    if res.get('status') != 'success':
        raise HTTPException(status_code=400, detail=res.get('message'))
    return res


@app.post("/api/asks/{ask_id}/withdraw")
def asks_withdraw(ask_id: str, body: dict = Body(default={}), request: Request = None):
    from services import asks as _asks
    res = _asks.withdraw(ask_id, _ask_actor(request, body.get('member_id')))
    if res.get('status') == 'refused':
        raise HTTPException(status_code=403, detail=res.get('message'))
    if res.get('status') != 'success':
        raise HTTPException(status_code=400, detail=res.get('message'))
    return res


@app.post("/api/asks/{ask_id}/answer")
def asks_answer(ask_id: str, body: dict = Body(default={}), request: Request = None,
                background_tasks: BackgroundTasks = None):
    from services import asks as _asks
    actor = _ask_actor(request, body.get('member_id'))
    a = storage.get_ask(ask_id)
    if not a:
        raise HTTPException(status_code=404, detail="No such ask")
    reported = bool(body.get('reported')) or (actor.get('id') != a.get('to_member_id'))
    res = _asks.answer(ask_id, body.get('answer') or '', actor, reported=reported)
    if res.get('status') == 'refused':
        raise HTTPException(status_code=403, detail=res.get('message'))
    if res.get('status') != 'success':
        raise HTTPException(status_code=400, detail=res.get('message'))
    _mind_refresh_if_dirty(res, background_tasks)
    return res
```

- [ ] **Step 4: The ask card in the PWA chat (`templates/app.html`)**

Change `renderCard`'s first line and add the ask branch:

```javascript
        function renderCard(card) {
            if (!card) return '';
            if (card.kind === 'ask') return renderAskCard(card);
            if (card.kind !== 'action_proposal') return '';
```

Add after `actOnProposal`:

```javascript
        // An ask addressed to the signed-in member: the `what` line is the
        // thing Yes/No answers; the buttons follow the ledger, not the moment
        // the message was drawn (the server rewrites the card on answer).
        function renderAskCard(card) {
            let footer;
            if ((card.actions || []).length) {
                footer = `<div class="flex gap-2 mt-2">` + card.actions.map(a =>
                    `<button onclick="answerAsk('${card.ask_id}','${a.act}')" class="px-3 py-1 rounded-lg text-xs font-semibold ${a.style === 'primary' ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-200'}">${mfEscape(a.label)}</button>`
                ).join('') + `</div>`;
            } else {
                const label = card.state === 'yes' ? (card.outcome === 'applied' ? '✓ Yes — it\'s yours' : '✓ Yes')
                            : card.state === 'no' ? 'No' : card.state === 'withdrawn' ? 'Withdrawn' : (card.state || '');
                footer = `<div class="text-xs mt-1 ${card.state === 'yes' ? 'text-green-400' : 'text-gray-500'}">${mfEscape(label)}</div>`;
            }
            return `<div class="mt-1 px-3 py-2 rounded-xl bg-gray-900 border border-gray-700">
                <div class="inline-block text-xs uppercase tracking-wide font-bold text-violet-300 bg-violet-900/40 px-2 py-0.5 rounded mb-1">Can you?</div>
                <div class="text-xs text-gray-200 font-medium">${mfEscape(card.what || '')}</div>
                ${footer}
            </div>`;
        }

        async function answerAsk(askId, act) {
            if (!selectedMemberId) return;
            try {
                const res = await fetch(`${apiBase}api/asks/${askId}/answer`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ answer: act, member_id: selectedMemberId }) });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) showGlobalAlert(data.detail || "Couldn't answer that.");
                else if (data.message) showGlobalAlert(data.message);
                await refreshThread();
            } catch (e) { showGlobalAlert("Couldn't answer that."); }
        }
```

- [ ] **Step 5: Run the tests**

Run: `env -u HA_BASE_URL ../venv/Scripts/python.exe tests/test_situation_endpoints.py` → `4/4`; then `tools/test.py mind_endpoints threads_endpoints missions_endpoints situation asks` — all pass.

- [ ] **Step 6: Commit**

Bump `config.yaml` to `2.499.307`.
```bash
git add chauffeur/config.yaml chauffeur/main.py chauffeur/templates/app.html chauffeur/tests/test_situation_endpoints.py
git commit -m "feat(situations): endpoints for situations and asks; the ask card in chat with Yes/No that follow the ledger (v2.499.307)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push origin main
```

---

### Task 8: Agent tools — six tools, dispatch, registry, parity both ways

**Files:**
- Modify: `services/agent_tools_v2.py` (functions near `list_insights` ~1350; declarations in `get_available_tools()` after `dismiss_insight` ~4094; REGISTRY: Pydantic classes near `DismissInsightTool` ~5566, `TOOL_SCHEMAS` entries near 6042, `handle_*` near 7196, `TOOL_HANDLERS` entries near 7543)
- Modify: `services/agent_router.py` (a dispatch branch next to the `list_insights`/`dismiss_insight` one at 782-799)
- Modify: `services/missions.py` `READ_TOOLS` (add `list_situations`, `explain_situation`)
- Test: `tests/test_situation_tools.py` (new); `tests/test_agent_v2_bridge.py` `V1_NAMES` unchanged (the registry grows)

**Interfaces (all in `agent_tools_v2`):**
- `list_situations(kinds: str = None, limit: int = 10, acting_member: dict = None) -> {status, message, situations}`
- `explain_situation(ref: str, kind: str = None, acting_member: dict = None) -> {status, message, situation}`
- `act_on_situation(ref: str, verb: str, option_id: str = None, kind: str = None, text: str = None, next_action_at: str = None, acting_member: dict = None) -> dict`
- `start_ask(ref: str, to_name: str, what: str, channel: str, kind: str = None, acting_member: dict = None) -> {status, message, ask_id, draft}`
- `mark_ask_sent(ask_id: str, acting_member: dict = None) -> dict`
- `answer_ask(ask_id: str, answer: str, acting_member: dict = None) -> dict`
- `_resolve_situation(ref, kind, viewer) -> (kind, sid) | (None, candidates)`: exact id, else case-insensitive substring on titles among `list_situations(viewer, include_done=False)`; one match → it; several → refuse naming them; none → refuse.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_situation_tools.py
"""Every card verb has a tool and every tool's verb renders on the card;
fuzzy resolution by title; write gates resolved at dispatch."""
import datetime
import re

from harness import check  # noqa: F401
from services import storage, situations, agent_tools_v2 as tools, threads

NOON = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)


def _reset():
    for t in (storage.asks_table, storage.findings_table, storage.mind_insights_table, storage.members_table,
              storage.cache_table, storage.app_state_table, storage.threads_table, storage.missions_table,
              storage.mission_steps_table, storage.assist_contacts_table, storage.chat_channels_table,
              storage.chat_messages_table):
        t.truncate()
    storage.get_settings = lambda: {'calendar_ids': ['primary']}
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True})
    situations.REFRESH_DELAY_S = 0
    situations._pool_call = lambda *a, **k: {}


MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}


def scenario_parity_both_ways():
    """Walk the card's verbs and the tools' verbs; they must be the same set."""
    src = open('static/situations.js', encoding='utf-8').read()
    block = re.search(r"VERB_LABELS\s*=\s*\{([^}]*)\}", src).group(1)
    card_verbs = set(re.findall(r"'([a-z_]+)':", block))
    check(card_verbs == situations.VERBS, f"the card knows every verb and nothing else: {card_verbs ^ situations.VERBS}")
    decl = {t['name'] for t in tools.get_available_tools()}
    check({'list_situations', 'explain_situation', 'act_on_situation', 'start_ask', 'mark_ask_sent', 'answer_ask'} <= decl,
          f"all six tools declared: {decl & {'list_situations','explain_situation','act_on_situation','start_ask','mark_ask_sent','answer_ask'}}")
    verb_param = next(t for t in tools.get_available_tools() if t['name'] == 'act_on_situation')['parameters']['properties']['verb']
    check(set(verb_param.get('enum') or []) == situations.VERBS - {'ask'},
          "act_on_situation's verb enum is the closed set minus ask (start_ask is ask)")
    for name in ('list_situations', 'explain_situation', 'act_on_situation', 'start_ask', 'mark_ask_sent', 'answer_ask'):
        check(name in tools.TOOL_HANDLERS and name in tools.TOOL_SCHEMAS, f"{name} is in the registry")


def scenario_fuzzy_resolve_and_ambiguity():
    _reset()
    t1 = threads.create('Deck permit with the county', owner_member_id='mom', created_by='mom')
    t2 = threads.create('Deck furniture quote', owner_member_id='mom', created_by='mom')
    res = tools.explain_situation('county', acting_member=MOM)
    check(res['status'] == 'success' and res['situation']['id'] == t1, f"one match by fragment: {res}")
    res = tools.explain_situation('deck', acting_member=MOM)
    check(res['status'] == 'error' and 'county' in res['message'] and 'furniture' in res['message'],
          f"ambiguous: names the candidates: {res}")
    res = tools.explain_situation('pool', acting_member=MOM)
    check(res['status'] == 'error', "no match is an honest error")


def scenario_act_and_ask_through_tools():
    _reset()
    tid = threads.create('Deck permit', owner_member_id='mom', next_action='call', created_by='mom')
    res = tools.act_on_situation('Deck permit', 'advance', text='email the inspector',
                                 next_action_at='2026-10-20', acting_member=MOM)
    check(res['status'] == 'success' and storage.get_thread(tid)['next_action'] == 'email the inspector', f"advance via tool: {res}")
    res = tools.act_on_situation('Deck permit', 'close', acting_member={'id': 'kid', 'role': 'child'})
    check(res['status'] in ('error', 'refused'), "a child is refused at dispatch")
    res = tools.start_ask('Deck permit', 'the inspector', 'come Friday morning', 'email', acting_member=MOM)
    check(res['status'] == 'success' and res['draft'] and res['ask_id'], f"an ask from chat returns a draft: {res}")
    check(tools.mark_ask_sent(res['ask_id'], acting_member=MOM)['status'] == 'success', "sent it")
    res2 = tools.answer_ask(res['ask_id'], 'yes', acting_member=MOM)
    check(res2['status'] == 'success' and res2.get('outcome') == 'applied', f"a free ask's yes is recorded as applied (nothing to unlock): {res2}")
    listed = tools.list_situations(kinds='thread', acting_member=MOM)
    check(listed['status'] == 'success' and 'Deck permit' in listed['message'] and 'inspector' in listed['message'],
          f"the list reads the ledger: {listed['message']}")


SCENARIOS = [scenario_parity_both_ways, scenario_fuzzy_resolve_and_ambiguity, scenario_act_and_ask_through_tools]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
```

The parity scenario reads `static/situations.js` (Task 9). Until Task 9 lands, create that file with only the verb table so this test can run:

```javascript
// static/situations.js — the one card builder (filled in by the surfaces task).
window.Situations = (function () {
  const VERB_LABELS = {
    'assign': 'Assign', 'ask': 'Ask', 'plan': 'Plan', 'prepare': 'Line it up', 'do': 'Approve',
    'done': 'Done', 'skip': 'Skip', 'research': 'Look it up', 'draft': 'Draft', 'advance': 'Next step',
    'answer': 'Answer', 'close': 'Close', 'snooze': 'Not now', 'dismiss': 'Dismiss', 'own': 'I\'ll handle it'
  };
  return { VERB_LABELS };
})();
```

- [ ] **Step 2: Run to verify failure**

Run: `env -u HA_BASE_URL ../venv/Scripts/python.exe tests/test_situation_tools.py`
Expected: FAIL — `AttributeError: module 'services.agent_tools_v2' has no attribute 'explain_situation'`.

- [ ] **Step 3: The tool functions** (in `agent_tools_v2.py`, after `dismiss_insight`)

```python
# --- Situations: the card's verbs as tools (spec §4). acting_member is
# resolved by the DISPATCH LAYER, never taken from the model. ---------------

def _situation_lines(rows: list) -> str:
    out = []
    for s in rows:
        nxt = (s.get('next_step') or {}).get('label') or '-'
        asks = '; '.join(f"asked {a.get('to_name')} by {a.get('channel')} — {a.get('state')}"
                         + (f"/{a['outcome']}" if a.get('outcome') else '')
                         for a in (s.get('asks') or []) if a.get('state') != 'withdrawn')
        out.append(f"- [{s['kind']}] {s['title']} — {s.get('status_note') or ''} → next: {nxt}"
                   + (f" ({asks})" if asks else ''))
    return '\n'.join(out)


def _resolve_situation(ref: str, kind: str = None, viewer: dict = None):
    from services import situations as _sit
    ref = (ref or '').strip()
    if not ref:
        return None, 'Say which one.'
    for k in ([kind] if kind in _sit.KINDS else _sit.KINDS):
        if _sit.load(k, ref):
            return (k, ref), None
    rows = _sit.list_situations(viewer, kinds=(kind,) if kind in _sit.KINDS else None)
    hits = [s for s in rows if ref.lower() in (s.get('title') or '').lower()]
    if len(hits) == 1:
        return (hits[0]['kind'], hits[0]['id']), None
    if not hits:
        return None, f"Nothing open matches '{ref}'."
    names = '; '.join(h['title'] for h in hits[:5])
    return None, f"Which one — {names}?"


def list_situations(kinds: str = None, limit: int = 10, acting_member: dict = None) -> Dict[str, Any]:
    from services import situations as _sit
    want = tuple(k for k in (kinds or '').split(',') if k in _sit.KINDS) or None
    rows = _sit.list_situations(acting_member, kinds=want)[:max(1, min(int(limit or 10), 30))]
    if not rows:
        return {"status": "success", "message": "Nothing needs anyone right now.", "situations": []}
    return {"status": "success", "message": _situation_lines(rows), "situations": rows}


def explain_situation(ref: str, kind: str = None, acting_member: dict = None) -> Dict[str, Any]:
    from services import situations as _sit
    found, why = _resolve_situation(ref, kind, acting_member)
    if not found:
        return {"status": "error", "message": why}
    s = _sit.view(found[0], found[1], acting_member)
    opts = '\n'.join(f"  {i + 1}. {o['label']} [{o['verb']}, option {o['id']}]" for i, o in enumerate(s['options']))
    asks = '\n'.join(f"  - asked {a.get('to_name')} by {a.get('channel')}: {a.get('what')} — {a.get('state')}"
                     + (f" / {a['outcome']}" if a.get('outcome') else '') for a in s['asks']) or '  (none)'
    msg = (f"{s['title']}\nStatus: {s['status_note']}\nOptions:\n{opts}\nAsks so far:\n{asks}")
    return {"status": "success", "message": msg, "situation": s}


def act_on_situation(ref: str, verb: str, option_id: str = None, kind: str = None, text: str = None,
                     next_action_at: str = None, acting_member: dict = None) -> Dict[str, Any]:
    from services import situations as _sit
    if not acting_member or acting_member.get('role') not in ('parent', 'adult'):
        return {"status": "error", "message": "Only a parent or adult can do that."}
    found, why = _resolve_situation(ref, kind, acting_member)
    if not found:
        return {"status": "error", "message": why}
    k, sid = found
    if not option_id:
        opts = [o for o in _sit.options_for(k, _sit.load(k, sid)) if o['verb'] == verb]
        if len(opts) != 1:
            return {"status": "error", "message": f"Say which option: " + '; '.join(f"{o['label']} ({o['id']})" for o in opts)
                    if opts else f"'{verb}' is not on the table for that one."}
        option_id = opts[0]['id']
    payload = {}
    if verb == 'answer' or verb == 'draft' or verb == 'research':
        payload['text'] = text or ''
    if verb == 'advance':
        payload['next_action'] = text or ''
        payload['next_action_at'] = next_action_at
    res = _sit.act(k, sid, verb, option_id=option_id, payload=payload, actor=acting_member)
    if res.get('status') == 'refused':
        return {"status": "error", "message": res.get('message')}
    return res


def start_ask(ref: str, to_name: str, what: str, channel: str, kind: str = None,
              acting_member: dict = None) -> Dict[str, Any]:
    from services import situations as _sit, asks as _asks
    if not acting_member or acting_member.get('role') not in ('parent', 'adult'):
        return {"status": "error", "message": "Only a parent or adult can ask."}
    found, why = _resolve_situation(ref, kind, acting_member)
    if not found:
        return {"status": "error", "message": why}
    k, sid = found
    row = _sit.load(k, sid)
    to = {'name': to_name}
    member = next((m for m in storage.get_all_members() if (m.get('name') or '').lower() == (to_name or '').lower()), None)
    contact = next((c for c in storage.get_assist_contacts() if (c.get('name') or '').lower() == (to_name or '').lower()), None)
    if member:
        to['member_id'] = member['id']
    elif contact:
        to['contact_id'] = contact['id']
    unlocks = None
    for o in _sit.options_for(k, row):
        if o['verb'] == 'ask' and (o['payload'].get('to') or {}).get('contact_id') == to.get('contact_id') and to.get('contact_id'):
            unlocks, what = o['payload'].get('unlocks'), what or o['payload'].get('what')
            break
        if o['verb'] == 'ask' and o['id'] == 'ask:new' and unlocks is None:
            unlocks, what = o['payload'].get('unlocks'), what or o['payload'].get('what')
    res = _asks.create(k, sid, to, what, channel, acting_member['id'], unlocks=unlocks,
                       event=_sit._cached_event((unlocks or {}).get('payload', {}).get('event_id')) if unlocks else None)
    if res.get('status') != 'success':
        return {"status": "error", "message": res.get('message')}
    a = res['ask']
    how = {'chauffeur': f"Sent to {a['to_name']} on Chauffeur with Yes/No.",
           'email': "Here's the email — copy it into your mail app, then tell me when it's sent:",
           'text': "Here's the text — copy it, send it, then tell me when it's sent:",
           'in_person': "Here's what to say — tell me once you've asked:"}[channel]
    draft = (f"Subject: {a['draft_subject']}\n\n" if a.get('draft_subject') else '') + (a.get('draft_body') or '')
    return {"status": "success", "ask_id": a['id'], "draft": draft,
            "message": f"{how}\n\n{draft}" if channel != 'chauffeur' else how}


def mark_ask_sent(ask_id: str, acting_member: dict = None) -> Dict[str, Any]:
    from services import asks as _asks
    res = _asks.mark_sent(ask_id, acting_member)
    return {**res, "status": "error" if res.get('status') == 'refused' else res.get('status')}


def answer_ask(ask_id: str, answer: str, acting_member: dict = None) -> Dict[str, Any]:
    from services import asks as _asks
    res = _asks.answer(ask_id, (answer or '').lower(), acting_member,
                       reported=(acting_member or {}).get('id') != (storage.get_ask(ask_id) or {}).get('to_member_id'))
    return {**res, "status": "error" if res.get('status') == 'refused' else res.get('status')}
```

- [ ] **Step 4: Declarations, dispatch, registry**

In `get_available_tools()` after the `dismiss_insight` dict:

```python
        {
            "name": "list_situations",
            "description": "What needs a person right now — uncovered rides, Argyle's observations, stalled threads, missions waiting on a decision — ranked, each with where it stands, the next step, and who has been asked so far ('what needs my attention?', 'anything I need to deal with?').",
            "parameters": {"type": "object",
                           "properties": {"kinds": {"type": "string", "description": "Optional comma list of finding,insight,thread,mission."},
                                          "limit": {"type": "integer", "description": "How many, default 10."}},
                           "required": []}
        },
        {
            "name": "explain_situation",
            "description": "The full picture of one thing that needs a person: status, every option with its id, and the asks so far. Takes an id or a title fragment ('tell me about the Thursday soccer one').",
            "parameters": {"type": "object",
                           "properties": {"ref": {"type": "string", "description": "The situation's id or a fragment of its title."},
                                          "kind": {"type": "string", "description": "Optional: finding|insight|thread|mission."}},
                           "required": ["ref"]}
        },
        {
            "name": "act_on_situation",
            "description": "Do one of a situation's options — assign a driver, approve a step, set a thread's next step, answer a mission, snooze, dismiss, take it yourself, mark it handled. Use start_ask to ask somebody.",
            "parameters": {"type": "object",
                           "properties": {"ref": {"type": "string", "description": "Id or title fragment."},
                                          "verb": {"type": "string", "enum": ["assign", "plan", "prepare", "do", "done", "skip", "research", "draft", "advance", "answer", "close", "snooze", "dismiss", "own"]},
                                          "option_id": {"type": "string", "description": "The option id from explain_situation, when the verb has more than one."},
                                          "kind": {"type": "string"},
                                          "text": {"type": "string", "description": "For answer/draft/research: the text. For advance: the next action."},
                                          "next_action_at": {"type": "string", "description": "For advance: YYYY-MM-DD."}},
                           "required": ["ref", "verb"]}
        },
        {
            "name": "start_ask",
            "description": "Ask somebody for something about a situation, by a channel the person chose: 'text Sarah and ask her to drive Kate Thursday', 'email the inspector to come Friday', 'message Dad on Chauffeur'. Returns the draft to copy (or sends it on Chauffeur).",
            "parameters": {"type": "object",
                           "properties": {"ref": {"type": "string"}, "to_name": {"type": "string"},
                                          "what": {"type": "string", "description": "The commitment being asked for, as a short phrase."},
                                          "channel": {"type": "string", "enum": ["chauffeur", "email", "text", "in_person"]},
                                          "kind": {"type": "string"}},
                           "required": ["ref", "to_name", "what", "channel"]}
        },
        {
            "name": "mark_ask_sent",
            "description": "The person says they sent the drafted text/email or asked in person.",
            "parameters": {"type": "object", "properties": {"ask_id": {"type": "string"}}, "required": ["ask_id"]}
        },
        {
            "name": "answer_ask",
            "description": "Record what the person asked said — 'Sarah said yes', 'Mike can't' — which applies the agreed change once.",
            "parameters": {"type": "object",
                           "properties": {"ask_id": {"type": "string"}, "answer": {"type": "string", "enum": ["yes", "no"]}},
                           "required": ["ask_id", "answer"]}
        },
```

In `agent_router.py`, add a branch right after the `list_insights`/`dismiss_insight` branch:

```python
                elif func_name in ("list_situations", "explain_situation", "act_on_situation",
                                   "start_ask", "mark_ask_sent", "answer_ask"):
                    from services import agent_tools_v2 as _atv2
                    actor = acting_member
                    if actor is None and driver:
                        from services import storage as _st
                        actor = _st.get_member_by_driver_id(driver_id)
                    fn = getattr(_atv2, func_name)
                    kwargs = {k: v for k, v in (args or {}).items() if k in fn.__code__.co_varnames}
                    res = fn(**kwargs, acting_member=actor)
                    if isinstance(res, dict) and res.get("schedule_dirty"):
                        schedule_dirty = True
                    if res.get("message"): agent_message = res["message"]
```

In the REGISTRY section: six Pydantic classes mirroring the declarations (`ListSituationsTool(kinds: Optional[str] = None, limit: Optional[int] = 10)`, `ExplainSituationTool(ref: str, kind: Optional[str] = None)`, `ActOnSituationTool(ref: str, verb: str, option_id: Optional[str] = None, kind: Optional[str] = None, text: Optional[str] = None, next_action_at: Optional[str] = None)`, `StartAskTool(ref, to_name, what, channel, kind: Optional[str] = None)`, `MarkAskSentTool(ask_id)`, `AnswerAskTool(ask_id, answer)`), six `TOOL_SCHEMAS` lines (`"list_situations": ListSituationsTool.model_json_schema(),` …), six handlers of the form:

```python
def handle_list_situations(args: dict) -> dict:
    # Registry path (action buttons, missions) runs in admin contexts; the
    # parent of record stands in, as the admin surface's approvals do.
    from services import storage as _s
    actor = next((m for m in _s.get_all_members() if m.get('role') == 'parent'), None)
    return list_situations(kinds=args.get('kinds'), limit=args.get('limit') or 10, acting_member=actor)
```

(each handler passes its own args through the same way), and six `TOOL_HANDLERS` lines. In `services/missions.py` add `'list_situations', 'explain_situation'` to `READ_TOOLS`.

- [ ] **Step 5: Run the tests**

Run: `env -u HA_BASE_URL ../venv/Scripts/python.exe tests/test_situation_tools.py` → `3/3`; then `tools/test.py agent_v2_bridge argyle_chat assist mind_agent_tools threads_agent_tools missions_engine situation` — all pass (the bridge test's frozen `V1_NAMES` is a subset check; growth is fine).

- [ ] **Step 6: Commit**

Bump `config.yaml` to `2.499.308`.
```bash
git add chauffeur/config.yaml chauffeur/services/agent_tools_v2.py chauffeur/services/agent_router.py chauffeur/services/missions.py chauffeur/static/situations.js chauffeur/tests/test_situation_tools.py
git commit -m "feat(agent): situation tools - list, explain, act, start_ask, mark sent, answer; parity with the card (v2.499.308)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push origin main
```

---

### Task 9: Surfaces — the card builder, the Needs-you lane on /mind, the PWA, the tile

**Files:**
- Modify: `static/situations.js` (the real builder)
- Modify: `templates/components/mind_page.html` (lane block 196-293 replaced; Alpine data + `loadAdmin` 395-440; include the script)
- Modify: `templates/app.html` (`fetchMind`/`renderMind` 3279-3401 replaced; include the script; the `#mind-content` container stays)
- Modify: `services/home_board.py` `_tile_mind` (2746-2754); `templates/components/board_tile_body.html` mind block (870-889)
- Modify: `templates/nav.html` or the base layout that loads `settings_drawer.js` through the climb prefix — add `situations.js` the same way
- Test: `tests/test_situations_lane_live.py` (new), `tests/test_mind_tile.py` (adjust the payload assertion)
- Run: `python tools/build_tailwind.py` and `tests/test_tailwind_build.py` after the markup lands

**Interfaces:**
- `window.Situations.cardHtml(s, ctx)` → HTML string; `ctx = {apiBase, canWrite: bool, memberId, readOnly: bool, onChange: fn}`
- `window.Situations.render(el, list, ctx)` → fills `el`, wires clicks via one delegated listener (`data-sit-act`, `data-sit-ask`, `data-ask-*`)
- `window.Situations.act(s, option, ctx)` → POST `/api/situations/{kind}/{id}/act`; for `advance`/`answer`/`draft`/`research` uses `promptInput` for the text
- `window.Situations.ask(s, option, ctx)` → channel row → POST `/api/asks` → draft panel (Copy, `mailto:`/`sms:` link when present, "Sent it" / "Asked them") → ledger line with "said yes / said no" for the asker
- The card DOM: `.situation-card[data-kind][data-id]`, `.sit-title`, `.sit-note[data-source]`, `.sit-next` (one primary button), `.sit-options`, `.sit-asks`, `.sit-details` (`<details>`)
- `_tile_mind(now, config=None, **_)` → `{'situations': [{'kind','id','title','status_note','next_label','severity'}]}` or `None`

- [ ] **Step 1: Write the failing live test**

```python
# tests/test_situations_lane_live.py
"""The Needs-you lane, actually drawn: one builder on /mind and the PWA
Family tab, the primary button is the next step, a finding gets its first
hand path, the wall tile is read-only. Set CHF_SHOTS=<dir> for screenshots.
Run from chauffeur/:  python tests/test_situations_lane_live.py
"""
import datetime
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='situations_lane_live_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_app import live_app
from services import storage

SHOTS = os.environ.get('CHF_SHOTS')
NOON = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + '.png'))


def seed():
    storage.update_settings({'llm_gemini_api_key': '', 'mind_enabled': True})
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent', 'color_code': '#6366f1'})
    storage.add_driver({'id': 'mom', 'name': 'Mom', 'color_code': '#6366f1'})
    start = (NOON + datetime.timedelta(days=2)).replace(hour=16)
    storage.set_cached_schedule({'events': [{'id': 'ev1', 'title': 'Soccer', 'start': start.isoformat(),
                                             'end': start.isoformat()}], 'assignments': {}, 'unassigned': ['ev1']})
    storage.add_finding({'identity': 'unassigned:ev1', 'kind': 'unassigned', 'severity': 'approve',
                         'line': '🚨 No driver yet: Soccer', 'subject_type': 'event', 'subject_id': 'ev1',
                         'due_at': start.timestamp(), 'state': 'open', 'fingerprint': f"ev1|{start.timestamp()}"})
    storage.add_mind_insight({'slug': 'q', 'line': 'A quiet week for Kate', 'category': 'c', 'approach': 'ask Kate about Thursday',
                              'identity': 'c:1', 'refs': ['kate'], 'confidence': 0.8})
    storage.add_mind_insight({'slug': 's', 'line': 'SECRET', 'category': 'c', 'approach': 'x', 'identity': 'c:2',
                              'refs': ['kate'], 'sensitivity': 'sensitive'})


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        b = served.browser(color_scheme='dark')
        with b as page:
            page.set_viewport_size({'width': 1300, 'height': 900})
            page.goto(served.url('work?tab=mind'), wait_until='networkidle')
            page.wait_for_selector('.situation-card')
            cards = page.locator('.situation-card')
            check(cards.count() == 3, f"/mind draws the parent's full lane, got {cards.count()}")
            first = cards.first
            check('Soccer' in first.locator('.sit-title').inner_text(), "the decide finding ranks first")
            nxt = first.locator('.sit-next button').first.inner_text()
            check(nxt.startswith('Assign'), f"the primary button is the next step, got {nxt!r}")
            check(first.locator('.sit-note[data-source="fallback"]').count() == 1, "no key: the fallback note is marked")
            _shot(page, 'mind-lane')
            first.locator('.sit-options button:has-text("Dismiss")').click()
            page.wait_for_timeout(600)
            check(page.locator('.situation-card').count() == 2, "a finding can be dismissed from a screen now")
            check(not b.errors, f"/mind script errors: {b.errors}")

        b = served.browser(color_scheme='dark')
        with b as page:
            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(served.url('app'), wait_until='networkidle')
            page.evaluate("() => { const t = document.querySelector('[data-tab=\"family\"]'); if (t) t.click(); }")
            page.wait_for_timeout(800)
            titles = page.locator('#mind-content .situation-card .sit-title').all_inner_texts()
            check('A quiet week for Kate' in titles and 'SECRET' not in titles,
                  f"an unsigned PWA view sees the non-sensitive insight only: {titles}")
            check(page.locator('#mind-content .sit-next button').count() == 0, "no identity, no buttons")
            _shot(page, 'pwa-lane')
            check(not b.errors, f"PWA script errors: {b.errors}")

        b = served.browser(color_scheme='dark')
        with b as page:
            page.set_viewport_size({'width': 1920, 'height': 1080})
            page.goto(served.url('home?panel=true'), wait_until='networkidle')
            page.wait_for_timeout(1200)
            tile = page.locator('[data-tile-type="mind"], .tile-mind').first
            if tile.count():
                check('A quiet week for Kate' in tile.inner_text() and 'SECRET' not in tile.inner_text(), "the tile is identity-free")
                check(tile.locator('button').count() == 0, "the wall tile is read-only")
                _shot(page, 'wall-tile')
            check(not b.errors, f"wall script errors: {b.errors}")
    finally:
        served.stop()


if __name__ == '__main__':
    main()
    print("test_situations_lane_live OK")
```

(If the board's tile markup uses a different hook than `data-tile-type`, read `templates/components/board_tile_body.html` line ~5 for the attribute the `t.type` switch is wrapped in and use that selector; the `if tile.count()` guard keeps the test honest if no mind tile is on the default board — then add one to the seed via `storage` the way `tests/test_mind_tile.py` does not need to, by setting the home board layout; see `services/home_board.py` `_default_layout` for the shape.)

- [ ] **Step 2: Run to verify failure**

Run: `env -u HA_BASE_URL ../venv/Scripts/python.exe tests/test_situations_lane_live.py`
Expected: FAIL at `page.wait_for_selector('.situation-card')` (timeout) — or SKIP if playwright is missing, in which case run the unit tests of Step 5 for the signal.

- [ ] **Step 3: The builder — `static/situations.js`**

```javascript
// static/situations.js — the one card builder for everything that needs a
// person (spec §3). Vanilla, so Alpine pages and the PWA's renderers share it.
// Markup rule: the next step is the ONE primary button; everything else is
// quiet. Read-only renders draw no buttons at all.
window.Situations = (function () {
  const VERB_LABELS = {
    'assign': 'Assign', 'ask': 'Ask', 'plan': 'Plan', 'prepare': 'Line it up', 'do': 'Approve',
    'done': 'Done', 'skip': 'Skip', 'research': 'Look it up', 'draft': 'Draft', 'advance': 'Next step',
    'answer': 'Answer', 'close': 'Close', 'snooze': 'Not now', 'dismiss': 'Dismiss', 'own': 'I\'ll handle it'
  };
  const CHANNEL_LABELS = { chauffeur: 'Chauffeur', email: 'Email', text: 'Text', in_person: 'In person' };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
  function when(ts) {
    if (!ts) return '';
    try { return new Date(ts * 1000).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' }); } catch (e) { return ''; }
  }
  function alert_(msg) { if (window.showGlobalAlert) showGlobalAlert(msg); else console.warn(msg); }

  const PRIMARY = 'text-xs font-bold px-3 py-1.5 rounded-lg bg-blue-600 text-white active:bg-blue-700';
  const QUIET = 'text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700 active:bg-gray-700';

  function askLine(a, ctx) {
    const state = a.state === 'yes' ? (a.outcome === 'applied' ? 'said yes — covering' : a.outcome === 'superseded' ? 'said yes — already covered by someone else' : a.outcome === 'stale' ? 'said yes — but the time moved, confirm' : a.outcome === 'failed' ? 'said yes — finish by hand' : 'said yes')
      : a.state === 'no' ? 'said no' : a.state === 'sent' ? 'waiting' : a.state === 'drafted' ? 'drafted, not sent' : a.state;
    const report = ctx.canWrite && !ctx.readOnly && (a.state === 'sent' || a.state === 'drafted')
      ? ` <button class="${QUIET}" data-ask-answer="yes" data-ask-id="${a.id}">said yes</button>`
        + ` <button class="${QUIET}" data-ask-answer="no" data-ask-id="${a.id}">said no</button>`
        + (a.state === 'drafted' ? ` <button class="${QUIET}" data-ask-sent="${a.id}">Sent it</button>` : '')
      : '';
    return `<div class="text-xs text-gray-400 mt-1" data-ask-line="${a.id}">Asked ${esc(a.to_name)} by ${esc(CHANNEL_LABELS[a.channel] || a.channel)} ${esc(when(a.sent_at || a.asked_at))} — ${esc(state)}${report}</div>`;
  }

  function cardHtml(s, ctx) {
    ctx = ctx || {};
    const opts = s.options || [];
    const next = s.next_step;
    const rest = opts.filter(o => !next || o.id !== next.id);
    const buttons = (ctx.canWrite && !ctx.readOnly)
      ? `<div class="sit-next mt-2">${next ? `<button class="${PRIMARY}" data-sit-act="${esc(next.id)}">${esc(next.label)}</button>` : ''}</div>
         <div class="sit-options flex flex-wrap gap-2 mt-1.5">${rest.map(o => `<button class="${QUIET}" data-sit-act="${esc(o.id)}">${esc(o.label)}</button>`).join('')}</div>`
      : '';
    const since = when(s.since);
    const meta = [s.state, since ? `since ${since}` : '', s.due ? `due ${when(typeof s.due === 'number' ? s.due : Date.parse(s.due) / 1000)}` : '', (s.people || []).join(', ')].filter(Boolean).join(' · ');
    const note = s.note_source === 'argyle'
      ? `<div class="sit-note text-xs text-gray-400 italic mt-0.5" data-source="argyle">${esc(s.status_note)}</div>`
      : `<div class="sit-note text-xs text-gray-500 mt-0.5" data-source="fallback">${esc(s.status_note)}</div>`;
    return `<div class="situation-card bg-gray-900 border border-gray-800 rounded-2xl p-3" data-kind="${esc(s.kind)}" data-id="${esc(s.id)}">
      <div class="flex items-start justify-between gap-2">
        <div class="sit-title text-sm text-gray-100">${esc(s.title)}</div>
        ${s.sensitivity === 'sensitive' ? '<span class="text-[10px] font-bold px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 shrink-0">sensitive</span>' : ''}
      </div>
      <div class="text-[11px] text-gray-600 mt-0.5">${esc(meta)}</div>
      ${note}
      ${buttons}
      <div class="sit-ask-flow mt-2" style="display:none"></div>
      <div class="sit-asks">${(s.asks || []).filter(a => a.state !== 'withdrawn').map(a => askLine(a, ctx)).join('')}</div>
      <details class="sit-details mt-1"><summary class="text-[11px] text-gray-500 cursor-pointer">details</summary><div class="sit-details-body text-xs text-gray-400 mt-1"></div></details>
    </div>`;
  }

  async function post(ctx, path, body) {
    const res = await fetch(`${ctx.apiBase || ''}${path}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(Object.assign({}, body || {}, ctx.memberId ? { member_id: ctx.memberId } : {})) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || 'That did not work.');
    return data;
  }

  async function act(s, option, ctx) {
    const payload = {};
    if (['advance', 'answer', 'draft', 'research'].includes(option.verb)) {
      const ask = { advance: 'What is the next step?', answer: 'Your answer', draft: 'What should the message say?', research: 'What should I look up?' }[option.verb];
      const text = window.promptInput ? await promptInput(ask, '') : null;
      if (!text) return;
      if (option.verb === 'advance') {
        payload.next_action = text;
        const d = window.promptInput ? await promptInput('By when? (YYYY-MM-DD, or blank)', '') : '';
        if (d) payload.next_action_at = d;
      } else payload.text = text;
    }
    try {
      const data = await post(ctx, `api/situations/${s.kind}/${s.id}/act`, { verb: option.verb, option_id: option.id, payload });
      if (data.message && option.verb !== 'own') alert_(data.message);
    } catch (e) { alert_(e.message); }
    if (ctx.onChange) ctx.onChange();
  }

  function askFlowHtml(s, option, channels) {
    const to = (option.payload.to || {}).name;
    const head = to ? `Ask ${esc(to)}: ${esc(option.payload.what)}` : `Ask someone to ${esc(option.payload.what)}`;
    const nameBox = to ? '' : `<input class="sit-ask-name w-full bg-gray-800 border border-gray-700 rounded-lg px-2 py-1 text-sm text-gray-100 mb-2" placeholder="Who?">`;
    return `<div class="text-xs text-gray-300 mb-1">${head}</div>${nameBox}
      <div class="text-[11px] text-gray-500 mb-1">How?</div>
      <div class="flex flex-wrap gap-2">${channels.map(c => `<button class="${QUIET}" data-ask-channel="${c}">${esc(CHANNEL_LABELS[c])}</button>`).join('')}
        <button class="${QUIET}" data-ask-cancel="1">Cancel</button></div>`;
  }

  function draftHtml(a, ch) {
    const text = (a.draft_subject ? `Subject: ${a.draft_subject}\n\n` : '') + (a.draft_body || '');
    const link = a.link ? `<a class="${QUIET} inline-block" href="${esc(a.link)}${ch.channel === 'email' ? `?subject=${encodeURIComponent(a.draft_subject || '')}&body=${encodeURIComponent(a.draft_body || '')}` : `?&body=${encodeURIComponent(a.draft_body || '')}`}">Open in ${esc(CHANNEL_LABELS[ch.channel])}</a>` : '';
    const sent = ch.channel === 'in_person' ? 'Asked them' : 'Sent it';
    return `<div class="text-[11px] text-gray-500 mb-1">${a.draft_source === 'argyle' ? 'Argyle drafted this — change anything' : 'A plain draft — change anything'}</div>
      <textarea class="sit-draft w-full bg-gray-800 border border-gray-700 rounded-lg px-2 py-1 text-sm text-gray-100" rows="5">${esc(text)}</textarea>
      <div class="flex flex-wrap gap-2 mt-1.5">
        <button class="${QUIET}" data-ask-copy="${a.id}">Copy</button>${link}
        <button class="${PRIMARY}" data-ask-sent="${a.id}">${sent}</button>
        <button class="${QUIET}" data-ask-withdraw="${a.id}">Never mind</button></div>`;
  }

  async function ask(s, option, ctx, card) {
    const flow = card.querySelector('.sit-ask-flow');
    const to = option.payload.to || {};
    const channels = to.member_id ? ['chauffeur', 'email', 'text', 'in_person'] : ['email', 'text', 'in_person'];
    flow.innerHTML = askFlowHtml(s, option, channels);
    flow.style.display = 'block';
    flow.onclick = async (ev) => {
      const b = ev.target.closest('button'); if (!b) return;
      if (b.dataset.askCancel) { flow.style.display = 'none'; flow.innerHTML = ''; return; }
      if (b.dataset.askChannel) {
        const name = flow.querySelector('.sit-ask-name');
        const body = { kind: s.kind, id: s.id, option_id: option.id, channel: b.dataset.askChannel,
                       to: Object.assign({}, to, name && name.value ? { name: name.value } : {}) };
        if (!body.to.name) { alert_('Who are you asking?'); return; }
        try {
          const data = await post(ctx, 'api/asks', body);
          const a = data.ask, ch = (data.channels || []).find(c => c.channel === b.dataset.askChannel) || { channel: b.dataset.askChannel };
          if (b.dataset.askChannel === 'chauffeur') { flow.style.display = 'none'; alert_(`Sent to ${a.to_name} on Chauffeur.`); if (ctx.onChange) ctx.onChange(); return; }
          a.link = ch.link; flow.innerHTML = draftHtml(a, ch);
        } catch (e) { alert_(e.message); }
        return;
      }
      if (b.dataset.askCopy) {
        const ta = flow.querySelector('.sit-draft');
        try { await navigator.clipboard.writeText(ta.value); alert_('Copied.'); } catch (e) { ta.select(); document.execCommand('copy'); alert_('Copied.'); }
        return;
      }
      if (b.dataset.askSent) { try { await post(ctx, `api/asks/${b.dataset.askSent}/sent`, {}); } catch (e) { alert_(e.message); } flow.style.display = 'none'; if (ctx.onChange) ctx.onChange(); return; }
      if (b.dataset.askWithdraw) { try { await post(ctx, `api/asks/${b.dataset.askWithdraw}/withdraw`, {}); } catch (e) { alert_(e.message); } flow.style.display = 'none'; if (ctx.onChange) ctx.onChange(); }
    };
  }

  function render(el, list, ctx) {
    ctx = ctx || {};
    el.innerHTML = (list || []).map(s => cardHtml(s, ctx)).join('');
    el.__situations = {}; (list || []).forEach(s => { el.__situations[`${s.kind}:${s.id}`] = s; });
    if (el.__sitBound) return;
    el.__sitBound = true;
    el.addEventListener('click', async (ev) => {
      const b = ev.target.closest('button'); if (!b || !el.contains(b)) return;
      const card = b.closest('.situation-card'); if (!card) return;
      const s = el.__situations[`${card.dataset.kind}:${card.dataset.id}`]; if (!s) return;
      if (b.dataset.sitAct) {
        const option = (s.options || []).find(o => o.id === b.dataset.sitAct); if (!option) return;
        if (option.verb === 'ask') return ask(s, option, ctx, card);
        return act(s, option, ctx);
      }
      if (b.dataset.askAnswer) { try { const d = await post(ctx, `api/asks/${b.dataset.askId}/answer`, { answer: b.dataset.askAnswer, reported: true }); if (d.message) alert_(d.message); } catch (e) { alert_(e.message); } if (ctx.onChange) ctx.onChange(); return; }
      if (b.dataset.askSent && !b.closest('.sit-ask-flow')) { try { await post(ctx, `api/asks/${b.dataset.askSent}/sent`, {}); } catch (e) { alert_(e.message); } if (ctx.onChange) ctx.onChange(); }
    });
  }

  return { VERB_LABELS, cardHtml, render, act, ask };
})();
```

- [ ] **Step 4: Wire the three surfaces**

**/mind** (`templates/components/mind_page.html`): replace lines 196-293 (the `✨ Current lane` block through its closing `</div>`) with:

```html
                    <div>
                        <div class="text-xs font-black uppercase tracking-widest text-violet-400 px-1 mb-2">
                            Needs you
                        </div>
                        <p class="text-xs text-gray-500 italic px-1" x-show="!situations.length">
                            Nothing needs you right now.
                        </p>
                        <div class="space-y-2" x-ref="lane"></div>
                    </div>
```

In the Alpine data add `situations: [],`; in `loadAdmin()` after `this.heldBack = …` add:

```javascript
                        try {
                            const r2 = await fetch(this.apiBase + 'api/situations?kinds=finding,insight');
                            const d2 = r2.ok ? await r2.json() : { situations: [] };
                            this.situations = d2.situations || [];
                            this.$nextTick(() => window.Situations.render(this.$refs.lane, this.situations, {
                                apiBase: this.apiBase, canWrite: true, readOnly: false,
                                onChange: () => this.loadAdmin() }));
                        } catch (e) { this.situations = []; }
```

Delete the now-unused `dismiss`, `act`, `snooze`, `plan`, `stepDo`, `clearIt`, `snoozedLabel`, `busy`, `noMove`, `snoozeOpen` members ONLY if nothing else in the file references them (grep the file; the history section uses `fmtTs` and `outcomeChipClass`, keep those). Load the script: the page bar already loads `settings_drawer.js` through the climb prefix in `templates/nav.html`; add `<script src="{{ climb }}static/situations.js"></script>` beside it (same prefix variable the drawer uses).

**PWA** (`templates/app.html`): replace `fetchMind` and `renderMind` with:

```javascript
        let mindSituations = [];
        async function fetchMind() {
            try {
                const res = await fetch(`${apiBase}api/situations?kinds=finding,insight`);
                const data = res.ok ? await res.json() : { situations: [] };
                mindSituations = data.situations || [];
            } catch (e) { mindSituations = []; }
            renderMind();
            applyViewVisibility();
        }

        function renderMind() {
            const wrap = document.getElementById('mind-content');
            if (!wrap) { renderScheduleAnchors(); return; }
            if (!mindSituations.length) { wrap.innerHTML = ''; renderScheduleAnchors(); return; }
            const canWrite = ['parent', 'adult'].includes(currentMemberRole());
            wrap.innerHTML = '<div class="text-xs font-black uppercase tracking-widest text-violet-400 px-1">Needs you</div><div id="mind-lane" class="space-y-2"></div>';
            window.Situations.render(document.getElementById('mind-lane'), mindSituations, {
                apiBase, canWrite, readOnly: false, memberId: selectedMemberId, onChange: fetchMind });
        }
```

and delete `_mindSnoozeRow`, `_mindStepHtml`, `_mindButtons`, `mindToggleSnooze`, `mindSnooze`, `mindPlan`, `mindStep`, `mindPropose`, `mindAct`, `mindDismiss`, `mindClear`, `mindLocal` (grep `app.html` for each name first; remove only what nothing else calls). Add `<script src="{{ url_for('static', path='situations.js') }}"></script>` next to where `app.html` loads its other static scripts (grep `static/pwa_` for the pattern it uses).

**Tile** (`services/home_board.py`):

```python
def _tile_mind(now, config=None, **_):
    """Needs you, identity-free (the tile always asks with no viewer, so a
    sensitive row or a finding never reaches a wall): title, Argyle's line,
    and the next step as words, never a button."""
    from services import situations as _sit
    rows = _sit.list_situations(None, kinds=('finding', 'insight'))
    if not rows:
        return None
    return {'situations': [{'kind': s['kind'], 'id': s['id'], 'title': s['title'],
                            'status_note': s['status_note'] if s['note_source'] == 'argyle' else '',
                            'next_label': (s.get('next_step') or {}).get('label') or ''} for s in rows[:6]]}
```

`templates/components/board_tile_body.html` mind block becomes:

```html
                    <template x-if="t.type === 'mind' && !t.data.empty">
                        <div class="space-y-1.5">
                            <template x-for="s in t.data.situations" :key="s.kind + s.id">
                                <div class="flex items-baseline gap-2">
                                    <span class="shrink-0 panel-dim">•</span>
                                    <div class="min-w-0">
                                        <div class="text-base panel-text truncate" x-text="s.title"></div>
                                        <div class="text-xs panel-dim truncate" x-show="s.status_note" x-text="s.status_note"></div>
                                        <div class="text-xs panel-dim truncate" x-show="s.next_label" x-text="'→ ' + s.next_label"></div>
                                    </div>
                                </div>
                            </template>
                        </div>
                    </template>
```

`tests/test_mind_tile.py`: change the payload assertion to read `t['situations']` and assert no sensitive title appears; keep `scenario_tile_registered`.

- [ ] **Step 5: Tailwind, then the tests**

Run: `../venv/Scripts/python.exe tools/build_tailwind.py && env -u HA_BASE_URL ../venv/Scripts/python.exe tests/test_tailwind_build.py`, then `env -u HA_BASE_URL ../venv/Scripts/python.exe tests/test_situations_lane_live.py` → `test_situations_lane_live OK` (with `CHF_SHOTS=…` once, and look at the three screenshots: the primary button must be the only blue button on a card). Then `tools/test.py mind_tile situation mind_endpoints household_features_live` — all pass.

- [ ] **Step 6: Commit**

Bump `config.yaml` to `2.499.309`.
```bash
git add chauffeur/config.yaml chauffeur/static chauffeur/templates chauffeur/services/home_board.py chauffeur/tests/test_situations_lane_live.py chauffeur/tests/test_mind_tile.py
git commit -m "feat(situations): the Needs-you lane - one card builder on /mind, the PWA Family tab and the board tile; findings get a hand path (v2.499.309)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push origin main
```

---

### Task 10: Acceptance scenarios end to end, docs, memory

**Files:**
- Test: `tests/test_situations_acceptance.py` (new)
- Modify: `chauffeur/system_capabilities.md` (new entry at the top, "Current through" bump), `chauffeur/docs/roadmap.md` (one line under Needs You: the tile shipped as the Needs-you lane), memory file `agentic-layer-field-feedback.md` (build 1 shipped)

- [ ] **Step 1: Write the acceptance scenarios (RED only if an earlier task cut a corner)**

```python
# tests/test_situations_acceptance.py
"""Spec §5 acceptance, end to end: text a helper → sent → yes → applied once
→ the finding retires by absence; a helper answers her own Chauffeur ask;
a done mission with a pending proposal stays actionable; the ordinary path
never goes stale; interrupted applying recovers to one assignment."""
import datetime
import time
from unittest import mock

from harness import check  # noqa: F401
from services import storage, situations, asks, watchers, findings

NOON = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}


def _reset():
    for t in (storage.asks_table, storage.findings_table, storage.mind_insights_table, storage.members_table,
              storage.cache_table, storage.app_state_table, storage.assist_contacts_table,
              storage.assist_assignments_table, storage.assist_history_table, storage.chat_channels_table,
              storage.chat_messages_table, storage.missions_table, storage.mission_steps_table,
              storage.agent_action_proposals_table, storage.drivers_table, storage.chores_table):
        t.truncate()
    storage.get_settings = lambda: {'calendar_ids': ['primary']}
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'nan', 'name': 'Nan', 'role': 'helper'})
    storage.add_assist_contact({'id': 'c1', 'name': 'Sarah', 'phone': '555', 'kinds': ['driving'], 'active': True})
    situations.REFRESH_DELAY_S = 0
    situations._pool_call = lambda *a, **k: {}
    start = (NOON + datetime.timedelta(days=2)).replace(hour=16)
    storage.set_cached_schedule({'events': [{'id': 'ev1', 'title': 'Soccer', 'start': start.isoformat(),
                                             'end': (start + datetime.timedelta(hours=1)).isoformat()}],
                                 'assignments': {}, 'unassigned': ['ev1']})
    return start


def _sweep(now):
    with mock.patch.object(watchers, '_prep_kit_findings', return_value=[]), \
         mock.patch('services.agent_tools_v2._post_chat_message', side_effect=lambda ch, sender, body, card=None: {'id': 'm'}):
        watchers.run_watchers(now=now)


def scenario_1_text_a_helper_to_retirement():
    start = _reset()
    _sweep(NOON)
    fid = storage.get_findings(state='open')[0]['id']
    s = situations.view('finding', fid, MOM)
    opt = next(o for o in s['options'] if o['verb'] == 'ask' and o['id'] == 'ask:new')
    a = asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, opt['payload']['what'], 'text', 'mom',
                    unlocks={**opt['payload']['unlocks'], 'payload': {**opt['payload']['unlocks']['payload'], 'contact_id': 'c1'}})['ask']
    check(a['draft_body'] and a['state'] == 'drafted', "drafted")
    asks.mark_sent(a['id'], MOM)
    r = asks.answer(a['id'], 'yes', MOM, reported=True)
    r2 = asks.answer(a['id'], 'yes', MOM, reported=True)
    check(r['outcome'] == 'applied' and r2.get('already'), "applied once through a duplicate tap")
    check(storage.get_assist_assignment_map().get('ev1', {}).get('contact_id') == 'c1', "one assignment")
    _sweep(NOON + datetime.timedelta(hours=1))
    check(storage.get_finding(fid)['state'] == 'done' and storage.get_finding(fid)['resolved_by'] == 'auto',
          "the covered ride retires by absence on the next sweep")


def scenario_2_helper_answers_her_own_chauffeur_ask():
    start = _reset()
    _sweep(NOON)
    fid = storage.get_findings(state='open')[0]['id']
    s = situations.view('finding', fid, MOM)
    opt = next(o for o in s['options'] if o['id'] == 'ask:new')
    a = asks.create('finding', fid, {'name': 'Nan', 'member_id': 'nan'}, opt['payload']['what'], 'chauffeur', 'mom',
                    unlocks=opt['payload']['unlocks'])['ask']
    check(a['state'] == 'sent' and a['message_id'], "posted as a DM")
    r = asks.answer(a['id'], 'yes', {'id': 'nan', 'role': 'helper'})
    check(r['status'] == 'success' and r['outcome'] == 'applied', f"her yes applies under Mom's authority: {r}")
    assigned = storage.get_assist_assignment_map().get('ev1', {})
    check(assigned.get('contact_id') and (storage.get_assist_contact(assigned['contact_id']) or {}).get('name') == 'Nan',
          "a new contact was minted for the helper and holds the ride")


def scenario_3_done_mission_with_pending_proposal_stays_actionable():
    _reset()
    mid = storage.add_mission({'goal': 'Find a plumber', 'status': 'done', 'created_by': 'mom', 'tier': 'flash',
                               'origin_kind': 'manual', 'step_count': 3, 'summary': 'Found two'})
    storage.add_action_proposal({'id': 'p1', 'action_type': 'add_errand', 'summary': 'Add: call Ace Plumbing',
                                 'payload': {'title': 'Call Ace Plumbing'}, 'status': 'proposed', 'requires_admin': True})
    storage.add_mission_step(mid, {'kind': 'proposal', 'name': 'add_errand', 'result_json': {'proposal_id': 'p1', 'status': 'proposed'}})
    rows = situations.list_situations(MOM, kinds=('mission',))
    check([r['id'] for r in rows] == [mid] and rows[0]['group'] == 'now', "a done mission with a decision left is live")
    with mock.patch('services.chat_actions._execute', return_value={'status': 'success', 'message': 'added'}):
        res = situations.act('mission', mid, 'do', option_id='do:p1', actor=MOM)
    check(res['status'] == 'success', f"approving from the card: {res}")
    rows = situations.list_situations(MOM, kinds=('mission',))
    check(rows == [], "resolved: it leaves the lane")
    check(situations.view('mission', mid, MOM)['group'] == 'done', "and reads as history")


def scenario_4_the_ordinary_path_never_goes_stale():
    start = _reset()
    _sweep(NOON)
    fid = storage.get_findings(state='open')[0]['id']
    opt = next(o for o in situations.view('finding', fid, MOM)['options'] if o['id'] == 'ask:new')
    u = opt['payload']['unlocks']
    a = asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, 'drive', 'text', 'mom',
                    unlocks={**u, 'payload': {**u['payload'], 'contact_id': 'c1'}})['ask']
    asks.mark_sent(a['id'], MOM)
    storage.add_assist_contact({'id': 'c2', 'name': 'Mike', 'kinds': ['driving'], 'active': True})
    b = asks.create('finding', fid, {'name': 'Mike', 'contact_id': 'c2'}, 'drive', 'text', 'mom',
                    unlocks={**u, 'payload': {**u['payload'], 'contact_id': 'c2'}})['ask']
    asks.mark_sent(b['id'], MOM)
    situations._pool_call = lambda *a_, **k: {'status_note': 'Two asks out.', 'options': []}
    storage.get_settings = lambda: {'calendar_ids': ['primary'], 'llm_gemini_api_key': 'k'}
    situations.refresh('finding', fid)
    r = asks.answer(a['id'], 'yes', MOM, reported=True)
    check(r['outcome'] == 'applied', f"sent, a sibling, and a note refresh did not make Sarah's yes stale: {r}")


def scenario_5_interrupted_applying_recovers_to_one_assignment():
    start = _reset()
    _sweep(NOON)
    fid = storage.get_findings(state='open')[0]['id']
    opt = next(o for o in situations.view('finding', fid, MOM)['options'] if o['id'] == 'ask:new')
    u = opt['payload']['unlocks']
    a = asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, 'drive', 'text', 'mom',
                    unlocks={**u, 'payload': {**u['payload'], 'contact_id': 'c1'}})['ask']
    asks.mark_sent(a['id'], MOM)
    # Stop after the yes, before the claim.
    storage.update_ask(a['id'], {'state': 'yes', 'answered_at': time.time(), 'answered_by': 'mom'})
    r = asks.answer(a['id'], 'yes', MOM, reported=True)
    check(r['outcome'] == 'applied', "a retry picks up from the claim")
    # Stop after the claim, before completion.
    storage.update_ask(a['id'], {'outcome': 'claimed', 'claim_ts': time.time() - 300, 'applied_at': None})
    _sweep(NOON + datetime.timedelta(minutes=10))
    row = storage.get_ask(a['id'])
    check(row['outcome'] == 'applied', f"the sweep finished the claim: {row}")
    hist = [h for h in storage.get_assist_history() if 'ask ' in (h.get('note') or '')] if hasattr(storage, 'get_assist_history') else []
    check(storage.get_assist_assignment_map().get('ev1', {}).get('contact_id') == 'c1', "exactly one assignment stands")


SCENARIOS = [scenario_1_text_a_helper_to_retirement, scenario_2_helper_answers_her_own_chauffeur_ask,
             scenario_3_done_mission_with_pending_proposal_stays_actionable,
             scenario_4_the_ordinary_path_never_goes_stale,
             scenario_5_interrupted_applying_recovers_to_one_assignment]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
```

- [ ] **Step 2: Run them**

Run: `env -u HA_BASE_URL ../venv/Scripts/python.exe tests/test_situations_acceptance.py`. Expected: `5/5`. A failure here is a defect in an earlier task — fix it THERE (its own test first), never by softening this file.

- [ ] **Step 3: The gate**

Run: `env -u HA_BASE_URL ../venv/Scripts/python.exe tools/test.py situations asks coverage_ladder assist watchers mind findings threads missions agent_v2_bridge chat_actions needs_you tailwind_build` — all files pass. Record the count.

- [ ] **Step 4: Docs**

`chauffeur/system_capabilities.md`: bump "Current through" to the final version and add one entry at the top, in the file's house style (bold lead sentence naming the version and files, then bullets), covering: the situation shape and verbs; `own` vs `done` and findings `in_hand`; Argyle's note on state change with `rev`/coalescing/caps/fallback; the asks ledger (channels always offered, drafts, three answer gates, claimed→applied with outcomes and recovery, fixed commitment, Chauffeur ask card); `coverage_asks` → `asks` with adapters and migration; the six tools; the Needs-you lane on /mind, the PWA Family tab and the tile; endpoints; what build 2 will add. `chauffeur/docs/roadmap.md`: under the Needs You arc, one line that the tile shipped as the Needs-you lane in v2.499.309. Memory `agentic-layer-field-feedback.md`: mark sub-project 2 build 1 shipped with the version range; next is build 2.

- [ ] **Step 5: Commit**

Bump `config.yaml` to `2.499.310`.
```bash
git add chauffeur/config.yaml chauffeur/system_capabilities.md chauffeur/docs/roadmap.md chauffeur/tests/test_situations_acceptance.py
git commit -m "test(situations): the five acceptance scenarios end to end; capabilities and roadmap for build 1 (v2.499.310)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push origin main
```

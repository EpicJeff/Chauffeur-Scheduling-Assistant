# The Mind Executive Loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the phase-C Mind: a three-rung agentic loop (gemma sentinel → flash-lite promoter → flash deep think) that reads whole-family state and curates an "Argyle noticed" insight lane, with feedback counters that later graduate categories toward direct delivery.

**Architecture:** New service `chauffeur/services/mind.py` owns snapshot building, the three LLM rungs, insight reconciliation, and visibility filtering; two new TinyDB-style tables (`mind_noticings`, `mind_insights`) in storage.py; one `mind.tick(now)` entry wired into `push_notification_loop`; surfaced via a board tile, a PWA Family-tab lane, and an admin Mind page; mirrored into agent_tools_v2.

**Tech Stack:** Python (FastAPI + TinyDB-style storage layer), `model_pools.call_pool_json` for all LLM calls (Gemini free tiers), Alpine.js + precompiled Tailwind templates, scenario-style test scripts run by `tools/test.py`.

**Spec:** `docs/superpowers/specs/2026-08-27-mind-executive-loop-design.md` — read it before starting any task.

## Global Constraints

- Every task's commit: bump `chauffeur/config.yaml` `version:` (Task 1 bumps MINOR and resets patch, e.g. 2.425.x → 2.426.0; every later task bumps PATCH by 1 from whatever is current), commit subject ends with `(vX.Y.Z)`, then push. Never ask permission for this.
- Full test sweep green before every code commit: from `chauffeur/` run `python tools/test.py` (parallel runner, ~80s). Never pipe its output (masks exit code). Docs-only commits skip the sweep.
- Git commits from PowerShell: NO double quotes inside `-m` arguments — use a single-quoted here-string (`@'...'@`, closing `'@` at column 0).
- Tests are scenario scripts, not pytest: import `tests/harness.py`, define `scenario_*()` functions using its `check(cond, msg)`, call them under `if __name__ == '__main__':`. Mirror `chauffeur/tests/test_assist.py`. A single file runs standalone: `python tests/test_<name>.py` from `chauffeur/`.
- LLM is ALWAYS mocked in tests (replace `model_pools.call_pool_json` attribute on the `mind` module); zero live calls.
- `mind_enabled` defaults to False everywhere. Nothing runs until the user flips it.
- DMs are never queried by any Mind code path. Gift/present records are never queried. These are structural (the code never touches those tables/fields), not filters.
- Storage convention: module-level table handle + accessor functions holding `db_lock`; copy the findings trio shape (storage.py:2632–2654).
- No browser dialogs ever (`alert`/`confirm`/`prompt`); use `showGlobalAlert`/`promptConfirm`/`promptInput` where a page includes control-center chrome.
- After ANY template class change: from `chauffeur/` run `python tools/build_tailwind.py` and commit the regenerated stylesheets (`tests/test_tailwind_build.py` fails otherwise).
- All Mind LLM calls resolve the key via `settings.get('llm_gemini_api_key', '')`; missing key = silent skip returning a status dict, never an exception.
- Never round-trip source files through PowerShell `Get-Content`/`Set-Content` (mojibake); use the Edit/Write tools.

---

### Task 1: Storage — mind tables and accessors

**Files:**
- Modify: `chauffeur/services/storage.py` (table init near line 468; accessors near the findings trio at line 2632)
- Test: `chauffeur/tests/test_mind_storage.py`

**Interfaces:**
- Produces (later tasks call these exact signatures):
  - `add_mind_noticing(data: dict) -> str`
  - `get_mind_noticings(consumed: bool = None) -> List[dict]`
  - `consume_mind_noticings(ids: List[str]) -> int`
  - `add_mind_insight(data: dict) -> str`
  - `update_mind_insight(insight_id: str, data: dict) -> bool`
  - `get_mind_insights(state: str = None) -> List[dict]`
  - `get_mind_insight_by_slug(slug: str) -> Optional[dict]`
  - `prune_mind(before_ts: float) -> int`

- [ ] **Step 1: Write the failing test**

Create `chauffeur/tests/test_mind_storage.py`:

```python
"""Mind storage: noticings queue + insights lane, findings-trio conventions."""
import time
from harness import check
from services import storage


def _reset():
    storage.mind_noticings_table.truncate()
    storage.mind_insights_table.truncate()


def scenario_noticing_roundtrip():
    _reset()
    nid = storage.add_mind_noticing({'line': 'sunscreen mentioned in chat',
                                     'source': 'chat', 'urgency': 'low',
                                     'refs': []})
    rows = storage.get_mind_noticings(consumed=False)
    check(len(rows) == 1 and rows[0]['id'] == nid,
          "an unconsumed noticing is visible")
    check(rows[0].get('consumed_at') is None, "fresh noticing is unconsumed")
    n = storage.consume_mind_noticings([nid])
    check(n == 1, "consume reports one row touched")
    check(storage.get_mind_noticings(consumed=False) == [],
          "consumed noticing leaves the unconsumed view")
    check(len(storage.get_mind_noticings(consumed=True)) == 1,
          "consumed noticing still exists for the audit trail")


def scenario_insight_lifecycle():
    _reset()
    iid = storage.add_mind_insight({'slug': 'ellie-overload', 'line': 'Six activity nights',
                                    'detail': '', 'domain': 'kids',
                                    'sensitivity': 'sensitive', 'category': 'overload',
                                    'proposal_json': None, 'confidence': 0.8})
    row = storage.get_mind_insight_by_slug('ellie-overload')
    check(row and row['id'] == iid, "insight retrievable by slug")
    check(row['state'] == 'active', "new insight defaults active")
    check(storage.update_mind_insight(iid, {'state': 'retired', 'outcome': 'dismissed',
                                            'resolved_ts': time.time()}),
          "update by id succeeds")
    check(storage.get_mind_insights(state='active') == [],
          "retired insight leaves the active view")
    check(storage.get_mind_insights(state='retired')[0]['outcome'] == 'dismissed',
          "outcome survives on the retired record")


def scenario_prune_spares_active():
    _reset()
    old = time.time() - 200 * 86400
    a = storage.add_mind_insight({'slug': 'keep-me', 'line': 'x', 'category': 'c'})
    b = storage.add_mind_insight({'slug': 'old-retired', 'line': 'y', 'category': 'c'})
    storage.update_mind_insight(a, {'created_ts': old})
    storage.update_mind_insight(b, {'state': 'retired', 'outcome': 'expired',
                                    'resolved_ts': old, 'created_ts': old})
    storage.add_mind_noticing({'line': 'stale', 'source': 'chat'})
    storage.mind_noticings_table.update({'ts': old})
    doomed = storage.prune_mind(time.time() - 120 * 86400)
    check(doomed == 2, f"prune removes old retired insight + old noticing, got {doomed}")
    check(storage.get_mind_insight_by_slug('keep-me'),
          "ACTIVE insights are never pruned regardless of age")


if __name__ == '__main__':
    scenario_noticing_roundtrip()
    scenario_insight_lifecycle()
    scenario_prune_spares_active()
    print("test_mind_storage OK")
```

- [ ] **Step 2: Run test to verify it fails**

Run (cwd `chauffeur/`): `python tests/test_mind_storage.py`
Expected: FAIL — `AttributeError: module 'services.storage' has no attribute 'mind_noticings_table'`

- [ ] **Step 3: Implement**

In `storage.py`, beside the other table handles (~line 468):

```python
mind_noticings_table = db.table('mind_noticings')
mind_insights_table = db.table('mind_insights')
```

Beside the findings trio (~line 2656), same conventions (uuid hex ids, `db_lock`, dict copies out):

```python
def add_mind_noticing(data: dict) -> str:
    import uuid as _uuid
    row = {'id': _uuid.uuid4().hex, 'ts': time.time(), 'consumed_at': None, **data}
    with db_lock:
        mind_noticings_table.insert(row)
    return row['id']

def get_mind_noticings(consumed: bool = None) -> List[dict]:
    with db_lock:
        rows = [dict(r) for r in mind_noticings_table.all()]
    if consumed is True:
        rows = [r for r in rows if r.get('consumed_at')]
    elif consumed is False:
        rows = [r for r in rows if not r.get('consumed_at')]
    rows.sort(key=lambda r: r.get('ts') or 0)
    return rows

def consume_mind_noticings(ids: List[str]) -> int:
    now = time.time()
    n = 0
    with db_lock:
        for nid in ids:
            n += len(mind_noticings_table.update({'consumed_at': now},
                                                 Query().id == nid))
    return n

def add_mind_insight(data: dict) -> str:
    import uuid as _uuid
    row = {'id': _uuid.uuid4().hex, 'created_ts': time.time(), 'state': 'active',
           'outcome': None, 'resolved_ts': None, 'sensitivity': 'normal',
           'detail': '', 'domain': '', 'proposal_json': None, 'confidence': None,
           **data}
    with db_lock:
        mind_insights_table.insert(row)
    return row['id']

def update_mind_insight(insight_id: str, data: dict) -> bool:
    with db_lock:
        return bool(mind_insights_table.update(data, Query().id == insight_id))

def get_mind_insights(state: str = None) -> List[dict]:
    with db_lock:
        rows = [dict(r) for r in mind_insights_table.all()]
    if state:
        rows = [r for r in rows if r.get('state') == state]
    rows.sort(key=lambda r: r.get('created_ts') or 0)
    return rows

def get_mind_insight_by_slug(slug: str) -> Optional[dict]:
    with db_lock:
        res = mind_insights_table.search(Query().slug == slug)
        return dict(res[0]) if res else None

def prune_mind(insights_before_ts: float, noticings_before_ts: float = None) -> int:
    """Old noticings and old RETIRED insights, each on its own clock (spec:
    noticings 14d, retired insights 120d). Active insights are live state and
    never pruned — same rule as findings."""
    if noticings_before_ts is None:
        noticings_before_ts = insights_before_ts
    doomed = 0
    with db_lock:
        for r in [dict(x) for x in mind_noticings_table.all()]:
            if (r.get('ts') or 0) < noticings_before_ts:
                mind_noticings_table.remove(Query().id == r['id'])
                doomed += 1
        for r in [dict(x) for x in mind_insights_table.all()]:
            if r.get('state') != 'active' \
                    and (r.get('resolved_ts') or r.get('created_ts') or 0) \
                    < insights_before_ts:
                mind_insights_table.remove(Query().id == r['id'])
                doomed += 1
    return doomed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python tests/test_mind_storage.py` — Expected: `test_mind_storage OK`

- [ ] **Step 5: Full sweep, bump minor version, commit**

Run `python tools/test.py`; expect green. Bump `chauffeur/config.yaml` to the next MINOR version (e.g. 2.426.0). Commit:

```
git add chauffeur/services/storage.py chauffeur/tests/test_mind_storage.py chauffeur/config.yaml
git commit -m @'
The Mind gets a memory: noticings queue and insight lane (v2.426.0)
'@
git push
```

---

### Task 2: mind.py — snapshot, hash, visibility filter

**Files:**
- Create: `chauffeur/services/mind.py`
- Test: `chauffeur/tests/test_mind_snapshot.py`

**Interfaces:**
- Consumes: Task 1 storage accessors; `storage.get_cached_schedule()`, `storage.get_family_channel()`, `storage.get_channel_messages(channel_id, after_ts)`, `findings.open_findings()`, `shopping.lists_needing_a_trip()`, cars helpers (cars.py:46–126).
- Produces:
  - `snapshot(now: datetime = None) -> str` (compact text block)
  - `snapshot_hash(text: str) -> str` (timestamps stripped before hashing)
  - `visible_insights(viewer: Optional[dict]) -> List[dict]` (server-side sensitivity gate)
  - `in_wake_window(now, settings) -> bool`
  - `_bump_call(kind: str, cap: int) -> bool` (day-keyed cap counter; False = capped)

- [ ] **Step 1: Write the failing test**

Create `chauffeur/tests/test_mind_snapshot.py`:

```python
"""Snapshot boundaries: family channel in, DMs structurally absent, gifts
structurally absent; hash ignores clock noise; sensitivity gate is server-side."""
import datetime, time, inspect
from harness import check
from services import storage, mind


def _seed_chat():
    # Family channel + one DM. The snapshot must carry the first, never the second.
    fam = storage.get_family_channel()
    if not fam:
        storage.chat_channels_table.insert({'id': 'fam1', 'kind': 'family',
                                            'member_ids': [], 'dm_key': None,
                                            'title': '', 'created_at': time.time(),
                                            'archived': False})
        fam = storage.get_family_channel()
    storage.chat_messages_table.insert({'id': 'm1', 'channel_id': fam['id'],
                                        'member_id': 'mom', 'ts': time.time(),
                                        'text': 'we are out of sunscreen'})
    dm = storage.get_or_create_dm('mom', 'dad')
    storage.chat_messages_table.insert({'id': 'm2', 'channel_id': dm['id'],
                                        'member_id': 'mom', 'ts': time.time(),
                                        'text': 'SECRET-DM-LINE'})


def scenario_family_channel_in_dms_out():
    _seed_chat()
    text = mind.snapshot(datetime.datetime.now())
    check('sunscreen' in text, "family-channel talk reaches the snapshot")
    check('SECRET-DM-LINE' not in text, "DM content never reaches the snapshot")


def scenario_dms_and_gifts_structurally_absent():
    src = inspect.getsource(mind)
    check('get_or_create_dm' not in src and 'dm_key' not in src,
          "mind.py never touches DM channel APIs — exclusion is structural")
    check('gift' not in src.lower() and 'present_' not in src.lower(),
          "mind.py never touches gift records — exclusion is structural")


def scenario_hash_stability():
    now = datetime.datetime.now()
    a = mind.snapshot_hash(mind.snapshot(now))
    b = mind.snapshot_hash(mind.snapshot(now + datetime.timedelta(seconds=90)))
    check(a == b, "90 seconds of clock drift alone does not change the hash")


def scenario_visibility_gate():
    storage.mind_insights_table.truncate()
    storage.add_mind_insight({'slug': 's1', 'line': 'normal one', 'category': 'c',
                              'sensitivity': 'normal'})
    storage.add_mind_insight({'slug': 's2', 'line': 'kid stress', 'category': 'c',
                              'sensitivity': 'sensitive'})
    check(len(mind.visible_insights(None)) == 1,
          "no viewer identity (wall panel) sees only normal")
    check(len(mind.visible_insights({'id': 'k1', 'role': 'child'})) == 1,
          "a child sees only normal")
    check(len(mind.visible_insights({'id': 'p1', 'role': 'parent'})) == 2,
          "a parent sees the full lane")


def scenario_wake_window():
    s = {'mind_wake_start': '06:00', 'mind_wake_end': '22:00'}
    check(mind.in_wake_window(datetime.datetime(2026, 8, 27, 12, 0), s), "noon is awake")
    check(not mind.in_wake_window(datetime.datetime(2026, 8, 27, 3, 0), s), "3am sleeps")


if __name__ == '__main__':
    scenario_family_channel_in_dms_out()
    scenario_dms_and_gifts_structurally_absent()
    scenario_hash_stability()
    scenario_visibility_gate()
    scenario_wake_window()
    print("test_mind_snapshot OK")
```

(Verified: `chat_channels_table` / `chat_messages_table` are the real handle names — storage.py:398–399.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/test_mind_snapshot.py` — Expected: FAIL, `ImportError: cannot import name 'mind'`

- [ ] **Step 3: Implement `chauffeur/services/mind.py`**

```python
"""The Mind: phase-C executive loop (spec: docs/superpowers/specs/
2026-08-27-mind-executive-loop-design.md).

Boundaries are structural, not filtered: this module never imports or calls
any DM accessor (family channel only) and never touches gift/present records.
Keep it that way — tests assert on this file's source."""
import datetime
import hashlib
import json
import logging
import re
import time
from typing import List, Optional

from services import storage

logger = logging.getLogger(__name__)

WAKE_START_DEFAULT = '06:00'
WAKE_END_DEFAULT = '22:00'
RETENTION_DAYS = 14          # noticings; retired insights get 120d at the prune call
MAX_INSIGHTS_DEFAULT = 7
CAPS_DEFAULT = {'think': 20, 'sentinel': 400, 'promote': 50}


def _mins(val, dflt):
    try:
        h, m = [int(x) for x in str(val or dflt).split(':')[:2]]
    except Exception:
        h, m = [int(x) for x in dflt.split(':')]
    return h * 60 + m


def in_wake_window(now: datetime.datetime, settings: dict) -> bool:
    start = _mins(settings.get('mind_wake_start'), WAKE_START_DEFAULT)
    end = _mins(settings.get('mind_wake_end'), WAKE_END_DEFAULT)
    cur = now.hour * 60 + now.minute
    if start == end:
        return True
    if start < end:
        return start <= cur < end
    return cur >= start or cur < end


def _bump_call(kind: str, cap: int) -> bool:
    """Day-keyed counter; True = allowed (and counted), False = capped."""
    day = datetime.date.today().isoformat()
    key = f'mind_calls:{day}'
    counts = dict(storage.get_app_state(key) or {})
    if int(counts.get(kind, 0)) >= cap:
        return False
    counts[kind] = int(counts.get(kind, 0)) + 1
    storage.set_app_state(key, counts)
    return True


def _fmt_ts(ts) -> str:
    try:
        return datetime.datetime.fromtimestamp(float(ts)).strftime('%a %H:%M')
    except Exception:
        return ''


def snapshot(now: datetime.datetime = None) -> str:
    """One compact text block of family state. Sections are independent:
    a provider that raises contributes nothing and never sinks the rest."""
    now = now or datetime.datetime.now()
    parts = [f"SNAPSHOT {now.strftime('%A %Y-%m-%d %H:%M')}"]

    def section(title, fn):
        try:
            body = fn()
        except Exception as e:
            logger.warning(f"[mind] snapshot section {title} failed: {e}")
            return
        if body:
            parts.append(f"## {title}\n{body}")

    def _calendar():
        sched = storage.get_cached_schedule() or {}
        horizon = (now + datetime.timedelta(days=7)).strftime('%Y-%m-%d')
        today = now.strftime('%Y-%m-%d')
        lines = []
        for e in (sched.get('events') or []):
            day = str(e.get('start_date') or e.get('date') or '')[:10]
            if today <= day <= horizon:
                lines.append(f"- {day} {e.get('start_time') or ''} "
                             f"{e.get('name') or e.get('summary') or '?'} "
                             f"[{', '.join(e.get('attendees') or [])}] "
                             f"driver: {e.get('driver') or 'unassigned'}")
        return '\n'.join(lines[:120])

    def _findings():
        from services import findings as _f
        return '\n'.join(f"- ({r.get('severity')}) {r.get('line')}"
                         for r in _f.open_findings()[:30])

    def _family_chat():
        fam = storage.get_family_channel()
        if not fam:
            return ''
        since = float(storage.get_app_state('mind_chat_snapshot_ts') or 0) \
            or (time.time() - 86400)
        msgs = storage.get_channel_messages(fam['id'], after_ts=since, limit=80)
        return '\n'.join(f"- [{_fmt_ts(m.get('ts'))}] {m.get('member_id')}: "
                         f"{m.get('text') or ''}" for m in msgs
                         if (m.get('text') or '').strip())

    def _shopping():
        from services import shopping as _shop
        lists = _shop.lists_needing_a_trip(min_items=1) or []
        return '\n'.join(f"- list {l.get('title') or l.get('id')}: "
                         f"{l.get('item_count', '?')} items waiting" for l in lists)

    def _cars():
        # Reuse the exact car-listing call run_sweep uses (cars.py:344 — read
        # the first lines of its body and call the same accessor), then
        # cars.car_levels(car) per car with telemetry.
        from services import cars as _cars
        lines = []
        for car in _cars_list():
            if _cars.has_telemetry(car):
                lv = _cars.car_levels(car) or {}
                lines.append(f"- {car.get('name')}: {lv}")
        return '\n'.join(lines)

    def _noticings():
        rows = storage.get_mind_noticings(consumed=False)
        return '\n'.join(f"- [{r.get('source')}] {r.get('line')}" for r in rows[:40])

    def _own_insights():
        rows = storage.get_mind_insights()
        lines = []
        for r in rows[-30:]:
            tag = r['state'] if r['state'] == 'active' else \
                f"{r['state']}/{r.get('outcome')}"
            lines.append(f"- [{tag}] ({r.get('category')}) {r.get('line')}")
        return '\n'.join(lines)

    section('CALENDAR NEXT 7 DAYS', _calendar)
    section('OPEN FINDINGS (already watched — do not repeat these)', _findings)
    section('FAMILY CHANNEL (spoken in the living room)', _family_chat)
    section('SHOPPING LISTS', _shopping)
    section('CARS', _cars)
    section('FRESH NOTICINGS', _noticings)
    section('YOUR OWN INSIGHTS AND HOW THE FAMILY REACTED', _own_insights)
    return '\n\n'.join(parts)


def _cars_list() -> list:
    """The family's cars, same filter cars.run_sweep uses (cars.py:350)."""
    from services import cars as _cars
    return [c for c in storage.get_all_cars()
            if not c.get('is_disabled') and _cars.has_telemetry(c)]


_TS_NOISE = re.compile(r'\b\d{1,2}:\d{2}\b')

# Only SLOW state decides "has anything changed". The Mind's own sections
# (noticings, prior insights) change on every think, and chat is consumed as
# it is read — hashing those would make the skip never fire. Chat still
# triggers thinks, but through noticings, which deep_think checks separately.
_HASH_SECTIONS = ('CALENDAR NEXT 7 DAYS', 'OPEN FINDINGS', 'SHOPPING LISTS',
                  'CARS')


def snapshot_hash(text: str) -> str:
    """Hash of the slow-state sections only, clock noise stripped."""
    keep = []
    for block in text.split('\n\n'):
        title = block.splitlines()[0].lstrip('# ').strip() if block else ''
        if any(title.startswith(s) for s in _HASH_SECTIONS):
            keep.append(block)
    return hashlib.sha256(_TS_NOISE.sub('', '\n\n'.join(keep))
                          .encode('utf-8')).hexdigest()


def visible_insights(viewer: Optional[dict]) -> List[dict]:
    """Server-side sensitivity gate. No identity (wall panel) or non-parent
    identity gets a payload that never contained sensitive rows."""
    rows = storage.get_mind_insights(state='active')
    if viewer and viewer.get('role') in ('parent', 'admin'):
        return rows
    return [r for r in rows if r.get('sensitivity') != 'sensitive']
```

Complete `_cars_list()` per its note (copy the one-line listing call from `cars.run_sweep`, drop the note + `inspect` import). If `get_cached_schedule()` event field names differ (check a cached row), adjust `_calendar` to the real keys.

- [ ] **Step 4: Run test to verify it passes**

Run: `python tests/test_mind_snapshot.py` — Expected: `test_mind_snapshot OK`

- [ ] **Step 5: Full sweep, bump patch, commit + push**

Subject: `The Mind opens its eyes: snapshot with hard walls (vX.Y.Z)`

---

### Task 3: Sentinel rung

**Files:**
- Modify: `chauffeur/services/mind.py`
- Test: `chauffeur/tests/test_mind_sentinel.py`

**Interfaces:**
- Consumes: `model_pools.call_pool_json('background', api_key, system, prompt, ...)` (model_pools.py:139); watermarks in app_state.
- Produces: `sentinel_sweep(now=None) -> dict` with status in `{'no_deltas','no_key','capped','swept','error'}`; writes `mind_noticings` rows; app_state keys `mind_chat_watermark`, `mind_event_state`, `mind_finding_keys`, `mind_shop_hash`.

- [ ] **Step 1: Write the failing test**

Create `chauffeur/tests/test_mind_sentinel.py`:

```python
"""Sentinel: coalesced deltas -> one gemma call -> noticings. No deltas, no call."""
import time
from harness import check
from services import storage, mind


CALLS = []

def _fake_pool(tier, api_key, system, prompt, **kw):
    CALLS.append({'tier': tier, 'prompt': prompt})
    return {'noticings': [{'line': 'sunscreen is out', 'source': 'chat',
                           'urgency': 'low'}]}


def _reset():
    CALLS.clear()
    storage.mind_noticings_table.truncate()
    for k in ('mind_chat_watermark', 'mind_event_state', 'mind_finding_keys',
              'mind_shop_hash'):
        storage.set_app_state(k, None)
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k', 'mind_enabled': True}
    mind._pool_call = _fake_pool


def scenario_delta_produces_noticing():
    _reset()
    fam = storage.get_family_channel()
    storage.chat_messages_table.insert({'id': 'mA', 'channel_id': fam['id'],
                                        'member_id': 'mom', 'ts': time.time(),
                                        'text': 'we are out of sunscreen'})
    res = mind.sentinel_sweep()
    check(res['status'] == 'swept', f"delta sweeps, got {res}")
    check(len(CALLS) == 1 and CALLS[0]['tier'] == 'background',
          "one background-tier call per sweep")
    rows = storage.get_mind_noticings(consumed=False)
    check(rows and rows[0]['line'] == 'sunscreen is out', "noticing stored")


def scenario_no_deltas_no_call():
    res = mind.sentinel_sweep()          # watermark advanced by prior sweep
    check(res['status'] == 'no_deltas', f"quiet house makes no LLM call, got {res}")
    check(len(CALLS) == 1, "call count unchanged")


def scenario_cap_stops_calls():
    _reset()
    day_key = f"mind_calls:{__import__('datetime').date.today().isoformat()}"
    storage.set_app_state(day_key, {'sentinel': 400})
    fam = storage.get_family_channel()
    storage.chat_messages_table.insert({'id': 'mB', 'channel_id': fam['id'],
                                        'member_id': 'mom', 'ts': time.time(),
                                        'text': 'another line'})
    res = mind.sentinel_sweep()
    check(res['status'] == 'capped' and not CALLS, "cap reached = silent skip")


if __name__ == '__main__':
    scenario_delta_produces_noticing()
    scenario_no_deltas_no_call()
    scenario_cap_stops_calls()
    print("test_mind_sentinel OK")
```

(Seed the family channel first as in Task 2's test if the harness DB starts empty.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/test_mind_sentinel.py` — Expected: FAIL, no `sentinel_sweep`.

- [ ] **Step 3: Implement in mind.py**

```python
SENTINEL_SYSTEM = (
    "You are Argyle, the quiet ear of a family's home assistant. You are shown "
    "only what CHANGED since your last look: new family-channel messages "
    "(spoken openly, as in the living room), calendar changes, new findings, "
    "shopping changes. Note anything the house should remember or act on: a "
    "need said out loud, a new conflict, something unusual. Return STRICT JSON: "
    '{"noticings": [{"line": "<one short sentence>", '
    '"source": "chat|calendar|findings|supply", "urgency": "low|high"}]} '
    "Return {\"noticings\": []} when nothing matters. Never invent facts."
)


def _pool_call(tier, api_key, system, prompt, **kw):
    """Indirection so tests stub one attribute."""
    from services import model_pools
    return model_pools.call_pool_json(tier, api_key, system, prompt, **kw)


def _gather_deltas(now: datetime.datetime) -> list:
    deltas = []

    # Chat: new family-channel messages past the watermark.
    fam = storage.get_family_channel()
    if fam:
        wm = float(storage.get_app_state('mind_chat_watermark') or 0)
        msgs = storage.get_channel_messages(fam['id'], after_ts=wm, limit=40)
        if msgs:
            storage.set_app_state('mind_chat_watermark', max(m['ts'] for m in msgs))
            for m in msgs:
                if (m.get('text') or '').strip():
                    deltas.append(f"[chat] {m.get('member_id')}: {m['text']}")

    # Calendar: id->fingerprint map diffed against the stored one.
    sched = storage.get_cached_schedule() or {}
    cur = {str(e.get('id') or e.get('name')): f"{e.get('start_date')}|"
           f"{e.get('start_time')}|{e.get('driver')}"
           for e in (sched.get('events') or [])}
    prev = dict(storage.get_app_state('mind_event_state') or {})
    if cur != prev:
        storage.set_app_state('mind_event_state', cur)
        added = [k for k in cur if k not in prev]
        gone = [k for k in prev if k not in cur]
        changed = [k for k in cur if k in prev and cur[k] != prev[k]]
        if prev:  # first run is baseline, not a delta storm
            for k in added[:10]:
                deltas.append(f"[calendar] new: {k}")
            for k in gone[:10]:
                deltas.append(f"[calendar] removed: {k}")
            for k in changed[:10]:
                deltas.append(f"[calendar] changed: {k} -> {cur[k]}")

    # Findings: new open keys.
    from services import findings as _f
    keys = sorted(r.get('key') or r.get('id') for r in _f.open_findings())
    prev_keys = list(storage.get_app_state('mind_finding_keys') or [])
    if keys != prev_keys:
        storage.set_app_state('mind_finding_keys', keys)
        for r in _f.open_findings():
            if (r.get('key') or r.get('id')) not in prev_keys and prev_keys:
                deltas.append(f"[findings] {r.get('line')}")

    # Shopping: coarse hash of list sizes.
    try:
        from services import shopping as _shop
        h = hashlib.sha256(json.dumps(
            [(l.get('id'), l.get('item_count'))
             for l in (_shop.lists_needing_a_trip(min_items=1) or [])],
            sort_keys=True).encode()).hexdigest()
        if h != storage.get_app_state('mind_shop_hash'):
            if storage.get_app_state('mind_shop_hash'):
                deltas.append("[supply] shopping lists changed")
            storage.set_app_state('mind_shop_hash', h)
    except Exception as e:
        logger.warning(f"[mind] shopping delta failed: {e}")

    return deltas


def sentinel_sweep(now: datetime.datetime = None) -> dict:
    now = now or datetime.datetime.now()
    settings = storage.get_settings() or {}
    api_key = settings.get('llm_gemini_api_key', '')
    deltas = _gather_deltas(now)      # watermarks advance even without a key
    if not deltas:
        return {'status': 'no_deltas'}
    if not api_key:
        return {'status': 'no_key'}
    cap = int(settings.get('mind_cap_sentinel', CAPS_DEFAULT['sentinel']))
    if not _bump_call('sentinel', cap):
        return {'status': 'capped'}
    res = _pool_call('background', api_key, SENTINEL_SYSTEM,
                     "CHANGES SINCE LAST LOOK:\n" + '\n'.join(deltas[:60]),
                     timeout_s=60, gemma_timeout_s=180)
    if not isinstance(res, dict) or res.get('error'):
        logger.warning(f"[mind] sentinel LLM failed: {res}")
        return {'status': 'error'}
    stored = 0
    for n in (res.get('noticings') or [])[:10]:
        line = (n.get('line') or '').strip()
        if line:
            storage.add_mind_noticing({'line': line,
                                       'source': n.get('source') or 'chat',
                                       'urgency': n.get('urgency') or 'low',
                                       'refs': []})
            stored += 1
    return {'status': 'swept', 'noticings': stored}
```

Adjust the calendar fingerprint fields to the real cached-schedule keys found in Task 2.

- [ ] **Step 4: Run test** — Expected: `test_mind_sentinel OK`

- [ ] **Step 5: Full sweep, bump patch, commit + push**

Subject: `The Mind hears the living room: sentinel rung (vX.Y.Z)`

---

### Task 4: Promoter rung

**Files:**
- Modify: `chauffeur/services/mind.py`
- Test: `chauffeur/tests/test_mind_promoter.py`

**Interfaces:**
- Consumes: unconsumed high-urgency noticings; `_pool_call('interactive', ...)` (tier chain lite→gemma — lite first is the point).
- Produces: `maybe_promote() -> dict` status in `{'nothing','no_key','capped','promoted','held','error'}`; app_state flag `mind_think_requested` (bool) read by Task 6.

- [ ] **Step 1: Write the failing test**

Create `chauffeur/tests/test_mind_promoter.py`:

```python
"""Promoter: only high-urgency unconsumed noticings, one lite call, sets flag."""
from harness import check
from services import storage, mind

CALLS = []

def _fake_pool(think_now):
    def f(tier, api_key, system, prompt, **kw):
        CALLS.append(tier)
        return {'think_now': think_now}
    return f

def _reset(urgency='high'):
    CALLS.clear()
    storage.mind_noticings_table.truncate()
    storage.set_app_state('mind_think_requested', False)
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k'}
    storage.add_mind_noticing({'line': 'x', 'source': 'chat', 'urgency': urgency})

def scenario_high_urgency_promotes():
    _reset('high')
    mind._pool_call = _fake_pool(True)
    res = mind.maybe_promote()
    check(res['status'] == 'promoted', f"got {res}")
    check(CALLS == ['interactive'], "one lite-first call")
    check(storage.get_app_state('mind_think_requested') is True, "flag set")

def scenario_low_urgency_never_calls():
    _reset('low')
    mind._pool_call = _fake_pool(True)
    res = mind.maybe_promote()
    check(res['status'] == 'nothing' and not CALLS, "low urgency waits for the hour")

def scenario_holds_when_llm_says_wait():
    _reset('high')
    mind._pool_call = _fake_pool(False)
    res = mind.maybe_promote()
    check(res['status'] == 'held', "LLM veto holds the think")
    check(storage.get_app_state('mind_think_requested') is not True, "no flag")

if __name__ == '__main__':
    scenario_high_urgency_promotes()
    scenario_low_urgency_never_calls()
    scenario_holds_when_llm_says_wait()
    print("test_mind_promoter OK")
```

- [ ] **Step 2: Run test** — Expected: FAIL, no `maybe_promote`.

- [ ] **Step 3: Implement in mind.py**

```python
PROMOTER_SYSTEM = (
    "A family home assistant noticed something and wonders whether to think "
    "hard about it NOW or wait for its next scheduled reflection (within the "
    "hour). Promote only genuinely time-relevant items. Return STRICT JSON: "
    '{"think_now": true|false}'
)


def maybe_promote() -> dict:
    urgent = [r for r in storage.get_mind_noticings(consumed=False)
              if r.get('urgency') == 'high' and not r.get('promoted_checked')]
    if not urgent:
        return {'status': 'nothing'}
    settings = storage.get_settings() or {}
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key:
        return {'status': 'no_key'}
    cap = int(settings.get('mind_cap_promote', CAPS_DEFAULT['promote']))
    if not _bump_call('promote', cap):
        return {'status': 'capped'}
    for r in urgent:
        storage.mind_noticings_table.update({'promoted_checked': True},
                                            storage.Query().id == r['id'])
    res = _pool_call('interactive', api_key, PROMOTER_SYSTEM,
                     '\n'.join(f"- {r['line']}" for r in urgent[:10]), timeout_s=30)
    if not isinstance(res, dict) or res.get('error'):
        return {'status': 'error'}
    if res.get('think_now'):
        storage.set_app_state('mind_think_requested', True)
        return {'status': 'promoted'}
    return {'status': 'held'}
```

(`storage.Query` resolves — storage.py:1 imports it at module level. If you prefer table writes to stay inside storage.py, add a small `storage.mark_mind_noticings_checked(ids)` accessor instead; either is acceptable.)

- [ ] **Step 4: Run test** — Expected: `test_mind_promoter OK`

- [ ] **Step 5: Full sweep, bump patch, commit + push**

Subject: `The Mind learns when not to wait: promoter rung (vX.Y.Z)`

---

### Task 5: Deep think and reconcile

**Files:**
- Modify: `chauffeur/services/mind.py`
- Test: `chauffeur/tests/test_mind_think.py`

**Interfaces:**
- Consumes: `snapshot()`, `snapshot_hash()`, `_pool_call('heavy', ...)`, Task 1 accessors.
- Produces: `deep_think(now=None, force=False) -> dict` status in `{'disabled','no_key','asleep','unchanged','capped','thought','error'}`; reconciles `mind_insights`; consumes noticings; advances `mind_chat_snapshot_ts`; stores `mind_last_snapshot_hash`, `mind_last_think_ts`.

- [ ] **Step 1: Write the failing test**

Create `chauffeur/tests/test_mind_think.py`:

```python
"""Deep think: reconcile new/update/retire by slug, consume noticings,
skip when nothing changed, hard cap on active insights."""
import datetime
from harness import check
from services import storage, mind

CALLS = []

def _fake_pool(insights):
    def f(tier, api_key, system, prompt, **kw):
        CALLS.append({'tier': tier, 'prompt': prompt})
        return {'insights': insights}
    return f

def _reset():
    CALLS.clear()
    storage.mind_insights_table.truncate()
    storage.mind_noticings_table.truncate()
    storage.set_app_state('mind_last_snapshot_hash', None)
    storage.set_app_state('mind_think_requested', False)
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k', 'mind_enabled': True,
                                    'mind_wake_start': '00:00', 'mind_wake_end': '00:00'}

NOON = datetime.datetime(2026, 8, 27, 12, 0)

def scenario_think_reconciles():
    _reset()
    storage.add_mind_insight({'slug': 'stays', 'line': 'old text', 'category': 'c'})
    storage.add_mind_insight({'slug': 'goes', 'line': 'done with', 'category': 'c'})
    nid = storage.add_mind_noticing({'line': 'n', 'source': 'chat'})
    mind._pool_call = _fake_pool([
        {'slug': 'stays', 'line': 'new text', 'category': 'c',
         'sensitivity': 'normal', 'domain': 'kids', 'confidence': 0.9},
        {'slug': 'fresh', 'line': 'brand new', 'category': 'overload',
         'sensitivity': 'sensitive', 'domain': 'kids', 'confidence': 0.7},
    ])
    res = mind.deep_think(NOON)
    check(res['status'] == 'thought', f"got {res}")
    check(CALLS and CALLS[0]['tier'] == 'heavy', "heavy tier")
    active = {r['slug']: r for r in storage.get_mind_insights(state='active')}
    check(set(active) == {'stays', 'fresh'}, f"reconciled to {set(active)}")
    check(active['stays']['line'] == 'new text', "kept slug updates in place")
    gone = storage.get_mind_insight_by_slug('goes')
    check(gone['state'] == 'retired' and gone['outcome'] == 'expired',
          "absent slug retires as expired")
    check(not storage.get_mind_noticings(consumed=False), "noticings consumed")

def scenario_unchanged_snapshot_skips():
    res = mind.deep_think(NOON)
    check(res['status'] == 'unchanged' and len(CALLS) == 1,
          f"identical snapshot makes no call, got {res}")

def scenario_force_overrides_hash():
    res = mind.deep_think(NOON, force=True)
    check(res['status'] == 'thought' and len(CALLS) == 2, "force thinks anyway")

def scenario_active_cap():
    _reset()
    mind._pool_call = _fake_pool([{'slug': f's{i}', 'line': 'x', 'category': 'c'}
                                  for i in range(12)])
    mind.deep_think(NOON, force=True)
    check(len(storage.get_mind_insights(state='active')) <= 7,
          "never more than mind_max_insights active")

def scenario_dismissed_insights_stay_dismissed():
    _reset()
    iid = storage.add_mind_insight({'slug': 'nagged', 'line': 'x', 'category': 'c'})
    storage.update_mind_insight(iid, {'state': 'retired', 'outcome': 'dismissed'})
    mind._pool_call = _fake_pool([{'slug': 'nagged', 'line': 'x again',
                                   'category': 'c'}])
    mind.deep_think(NOON, force=True)
    row = storage.get_mind_insight_by_slug('nagged')
    check(row['state'] == 'retired', "a dismissed slug is never resurrected")

if __name__ == '__main__':
    scenario_think_reconciles()
    scenario_unchanged_snapshot_skips()
    scenario_force_overrides_hash()
    scenario_active_cap()
    scenario_dismissed_insights_stay_dismissed()
    print("test_mind_think OK")
```

- [ ] **Step 2: Run test** — Expected: FAIL, no `deep_think`.

- [ ] **Step 3: Implement in mind.py**

```python
THINK_SYSTEM = (
    "You are Argyle, a family home's mind. Coded watchers already cover the "
    "mechanical things (the OPEN FINDINGS section) — never restate those. Your "
    "job is what only whole-picture judgment can see: cross-domain patterns, "
    "load building on one person, needs said out loud in the family channel, "
    "collisions nobody planned for, small kindnesses worth suggesting.\n\n"
    "You are shown your own previous insights and how the family reacted. A "
    "dismissed insight means they heard you and said no — do not repeat it. "
    "Curate: return the FULL DESIRED set of current insights (max {max_n}); "
    "any active slug you omit is retired. Keep a slug stable while the "
    "observation is the same one.\n\n"
    "Mark sensitivity 'sensitive' for anything about a child's emotional "
    "state, stress, health, or another member's private strain — those render "
    "to parents only.\n\n"
    "Return STRICT JSON: {{\"insights\": [{{\"slug\": \"kebab-case-stable\", "
    "\"line\": \"one plain sentence\", \"detail\": \"1-2 optional sentences\", "
    "\"domain\": \"kids|meals|cars|schedule|supply|other\", "
    "\"sensitivity\": \"normal|sensitive\", \"category\": "
    "\"reusable-pattern-slug\", \"confidence\": 0.0}}]}}. "
    "An empty list is a fine answer. Never invent facts."
)


def deep_think(now: datetime.datetime = None, force: bool = False) -> dict:
    now = now or datetime.datetime.now()
    settings = storage.get_settings() or {}
    if not settings.get('mind_enabled', False):
        return {'status': 'disabled'}
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key:
        return {'status': 'no_key'}
    if not force and not in_wake_window(now, settings):
        return {'status': 'asleep'}

    text = snapshot(now)
    h = snapshot_hash(text)
    fresh_noticings = storage.get_mind_noticings(consumed=False)
    if not force and h == storage.get_app_state('mind_last_snapshot_hash') \
            and not fresh_noticings:
        return {'status': 'unchanged'}
    cap = int(settings.get('mind_cap_think', CAPS_DEFAULT['think']))
    if not _bump_call('think', cap):
        return {'status': 'capped'}

    max_n = int(settings.get('mind_max_insights', MAX_INSIGHTS_DEFAULT))
    res = _pool_call('heavy', api_key, THINK_SYSTEM.format(max_n=max_n), text,
                     timeout_s=90, gemma_timeout_s=180)
    if not isinstance(res, dict) or res.get('error'):
        logger.warning(f"[mind] deep think failed: {res}")
        return {'status': 'error'}

    desired = [i for i in (res.get('insights') or [])
               if (i.get('slug') or '').strip() and (i.get('line') or '').strip()]
    desired = desired[:max_n]
    desired_slugs = {i['slug'] for i in desired}

    active = storage.get_mind_insights(state='active')
    for row in active:
        if row['slug'] not in desired_slugs:
            storage.update_mind_insight(row['id'], {
                'state': 'retired', 'outcome': 'expired',
                'resolved_ts': time.time()})
    retired_slugs = {r['slug'] for r in storage.get_mind_insights(state='retired')}
    for item in desired:
        existing = storage.get_mind_insight_by_slug(item['slug'])
        fields = {'line': item['line'], 'detail': item.get('detail') or '',
                  'domain': item.get('domain') or '',
                  'sensitivity': item.get('sensitivity') or 'normal',
                  'category': item.get('category') or 'other',
                  'confidence': item.get('confidence')}
        if existing and existing['state'] == 'active':
            storage.update_mind_insight(existing['id'], fields)
        elif item['slug'] not in retired_slugs:
            storage.add_mind_insight({'slug': item['slug'], **fields})
        # a retired slug is never resurrected — the family already answered

    storage.consume_mind_noticings([r['id'] for r in fresh_noticings])
    storage.set_app_state('mind_last_snapshot_hash', h)
    storage.set_app_state('mind_last_think_ts', time.time())
    storage.set_app_state('mind_chat_snapshot_ts', time.time())
    storage.set_app_state('mind_think_requested', False)
    storage.prune_mind(time.time() - 120 * 86400,
                       time.time() - RETENTION_DAYS * 86400)
    return {'status': 'thought',
            'active': len(storage.get_mind_insights(state='active'))}
```

Note the proposal field: phase C ships insights WITHOUT auto-attached proposals from the LLM (the `proposal_json` column exists; attaching validated proposals is listed in the spec as riding `propose_family_action` — Task 8's act endpoint handles the wiring when present, and the think prompt deliberately does not ask for proposals yet: an invalid `action_type` fabricated by the model would fail at `create_action_proposal` anyway. Revisit after C proves taste.)

- [ ] **Step 4: Run test** — Expected: `test_mind_think OK`

- [ ] **Step 5: Full sweep, bump patch, commit + push**

Subject: `The Mind thinks on the hour and curates what it says (vX.Y.Z)`

---

### Task 6: tick() and the push-loop wiring

**Files:**
- Modify: `chauffeur/services/mind.py`; `chauffeur/main.py` (inside `push_notification_loop`, after the presence block ending ~line 645)
- Test: `chauffeur/tests/test_mind_tick.py`

**Interfaces:**
- Consumes: Tasks 3–5 functions.
- Produces: `mind.tick(now=None) -> dict` — the ONLY function main.py calls. Owns all gating: enabled flag, sentinel cadence (`mind_sentinel_cadence_s`, default 120), think cadence (`mind_think_cadence_min`, default 60), `mind_think_requested` early think.

- [ ] **Step 1: Write the failing test**

Create `chauffeur/tests/test_mind_tick.py`:

```python
"""tick(): one entry, all gating inside. Disabled = inert. Cadences honored.
A promoted flag causes an early think."""
import datetime
from harness import check
from services import storage, mind

LOG = []

def _stub(name, result):
    def f(*a, **kw):
        LOG.append(name)
        return result
    return f

def _reset(enabled=True):
    LOG.clear()
    storage.set_app_state('mind_sentinel_last', 0)
    storage.set_app_state('mind_last_think_ts', 0)
    storage.set_app_state('mind_think_requested', False)
    storage.get_settings = lambda: {'mind_enabled': enabled,
                                    'llm_gemini_api_key': 'k'}
    mind.sentinel_sweep = _stub('sentinel', {'status': 'swept'})
    mind.maybe_promote = _stub('promote', {'status': 'nothing'})
    mind.deep_think = _stub('think', {'status': 'thought'})

NOON = datetime.datetime(2026, 8, 27, 12, 0)

def scenario_disabled_is_inert():
    _reset(enabled=False)
    res = mind.tick(NOON)
    check(res['status'] == 'disabled' and not LOG, "off means OFF")

def scenario_first_tick_runs_all():
    _reset()
    mind.tick(NOON)
    check('sentinel' in LOG and 'think' in LOG, f"cold start runs rungs, got {LOG}")

def scenario_cadence_holds():
    LOG.clear()
    storage.set_app_state('mind_sentinel_last', NOON.timestamp())
    storage.set_app_state('mind_last_think_ts', NOON.timestamp())
    mind.tick(NOON + datetime.timedelta(seconds=45))
    check(LOG == [], f"45s later nothing is due, got {LOG}")

def scenario_promoted_flag_forces_think():
    LOG.clear()
    storage.set_app_state('mind_think_requested', True)
    mind.tick(NOON + datetime.timedelta(seconds=45))
    check('think' in LOG, "promoted flag beats the hourly cadence")

if __name__ == '__main__':
    scenario_disabled_is_inert()
    scenario_first_tick_runs_all()
    scenario_cadence_holds()
    scenario_promoted_flag_forces_think()
    print("test_mind_tick OK")
```

- [ ] **Step 2: Run test** — Expected: FAIL, no `tick`.

- [ ] **Step 3: Implement `tick` in mind.py**

```python
def tick(now: datetime.datetime = None) -> dict:
    """The one entry the push loop calls. All gating lives here so main.py
    stays a two-line block and tests drive this directly."""
    now = now or datetime.datetime.now()
    settings = storage.get_settings() or {}
    if not settings.get('mind_enabled', False):
        return {'status': 'disabled'}
    out = {'status': 'ticked'}
    ts = now.timestamp()

    cadence = int(settings.get('mind_sentinel_cadence_s', 120))
    last = float(storage.get_app_state('mind_sentinel_last') or 0)
    if ts - last >= cadence:
        storage.set_app_state('mind_sentinel_last', ts)   # marker FIRST
        out['sentinel'] = sentinel_sweep(now)
        out['promote'] = maybe_promote()

    think_every = int(settings.get('mind_think_cadence_min', 60)) * 60
    last_think = float(storage.get_app_state('mind_last_think_ts') or 0)
    requested = bool(storage.get_app_state('mind_think_requested'))
    if requested or ts - last_think >= think_every:
        out['think'] = deep_think(now)
    return out
```

(`deep_think` itself sets `mind_last_think_ts` only on a real think; `asleep`/`unchanged` cost nothing, so no marker needed here — the statuses are cheap no-ops.)

- [ ] **Step 4: Wire into main.py** — after the presence block (~line 645), same shape as the watchers block (main.py:446):

```python
            # --- The Mind (phase C: docs/superpowers/specs/2026-08-27-...) ---
            # All gating (enabled flag, cadences, wake window, caps, snapshot
            # hash) lives in mind.tick; this block only keeps the loop alive.
            try:
                from services import mind as _mind
                await asyncio.to_thread(_mind.tick)
            except Exception as me:
                print(f"Mind tick error: {me}")
```

- [ ] **Step 5: Run tests** — `python tests/test_mind_tick.py` then full `python tools/test.py`. Expected: green (mind_enabled defaults False, so the wire is inert for every existing test).

- [ ] **Step 6: Bump patch, commit + push**

Subject: `The Mind wakes with the house: tick wired into the loop (vX.Y.Z)`

---

### Task 7: Settings registry entries

**Files:**
- Modify: `chauffeur/services/settings_registry.py`
- Test: `chauffeur/tests/test_mind_settings.py`

**Interfaces:**
- Produces: registry entries (page `'mind'`) for: `mind_enabled`, `mind_sentinel_cadence_s`, `mind_think_cadence_min`, `mind_wake_start`, `mind_wake_end`, `mind_max_insights`, `mind_cap_think`, `mind_cap_sentinel`, `mind_cap_promote`, `mind_direct_categories`.

- [ ] **Step 1: Write the failing test**

```python
"""Every Mind setting is registered, on the Mind page — never config."""
from harness import check
from services import settings_registry

def scenario_mind_settings_registered():
    entries = {e['key']: e for e in settings_registry.ENTRIES}
    for key in ('mind_enabled', 'mind_sentinel_cadence_s', 'mind_think_cadence_min',
                'mind_wake_start', 'mind_wake_end', 'mind_max_insights',
                'mind_cap_think', 'mind_cap_sentinel', 'mind_cap_promote',
                'mind_direct_categories'):
        check(key in entries, f"{key} registered")
        check(entries[key]['page'] == 'mind', f"{key} lives on the Mind page")

if __name__ == '__main__':
    scenario_mind_settings_registered()
    print("test_mind_settings OK")
```

(`ENTRIES` is the registry list — settings_registry.py:67.)

- [ ] **Step 2: Run test** — Expected: FAIL.

- [ ] **Step 3: Implement** — add to the registry list using the `_e()` factory (settings_registry.py:55), grouped `'mind'`, `page='mind'`:

```python
_e('mind_enabled', 'mind', 'The Mind',
   'Argyle watches whole-family state and keeps a small set of noticed '
   'insights. Off means completely off — no reads, no LLM calls.', page='mind'),
_e('mind_wake_start', 'mind', 'Wakes at',
   'The Mind only thinks between these times (default 06:00).', page='mind'),
_e('mind_wake_end', 'mind', 'Sleeps at',
   'Thinking stops here (default 22:00). Equal times = always awake.', page='mind'),
_e('mind_think_cadence_min', 'mind', 'Thinks every (minutes)',
   'How often the deep reflection runs while awake (default 60).', page='mind'),
_e('mind_sentinel_cadence_s', 'mind', 'Listens every (seconds)',
   'How often changed state is checked for noticings (default 120).', page='mind'),
_e('mind_max_insights', 'mind', 'Insights kept',
   'The most insights shown at once; the Mind curates down to this (default 7).',
   page='mind'),
_e('mind_cap_think', 'mind', 'Daily think cap',
   'Hard ceiling on deep-think LLM calls per day (default 20).', page='mind'),
_e('mind_cap_sentinel', 'mind', 'Daily listen cap',
   'Hard ceiling on sentinel LLM calls per day (default 400).', page='mind'),
_e('mind_cap_promote', 'mind', 'Daily promote cap',
   'Hard ceiling on urgency-check LLM calls per day (default 50).', page='mind'),
_e('mind_direct_categories', 'mind', 'Graduated categories',
   'Insight categories approved for direct delivery (phase B). Empty until '
   'you graduate one from the Mind page.', page='mind'),
```

- [ ] **Step 4: Run test, full sweep** — Expected: green.

- [ ] **Step 5: Bump patch, commit + push**

Subject: `The Mind gets its dials, on its own page (vX.Y.Z)`

---

### Task 8: HTTP endpoints — lane, dismiss, act

**Files:**
- Modify: `chauffeur/main.py` (beside the findings endpoints, ~line 4729)
- Test: `chauffeur/tests/test_mind_endpoints.py`

**Interfaces:**
- Consumes: `mind.visible_insights(viewer)`, `storage.update_mind_insight`, `chat_actions.act_on_proposal` (chat_actions.py:367), `_acting_id(request, claimed)` + `storage.get_member` (the `_needs_you_actor` pattern, main.py:4717).
- Produces:
  - `GET /api/mind/insights` → `{"insights": [...]}` filtered by requester identity
  - `POST /api/mind/insights/{insight_id}/dismiss` (body `{member_id}`) — parents/adults only
  - `POST /api/mind/insights/{insight_id}/act` (body `{member_id}`) — approves the attached proposal when present, then retires the insight as `acted`
  - `GET /api/mind/admin` → `{"insights", "history", "counters", "graduation"}` — parents only (graduation payload arrives in Task 11)

- [ ] **Step 1: Write the failing test** — service-level logic is already tested; this test exercises the endpoint functions directly (import them from main), mirroring how existing endpoint tests call route functions with a `None` request plus explicit `member_id`. Create `chauffeur/tests/test_mind_endpoints.py`:

```python
"""Endpoint behavior: filtered payloads, role gates, outcomes recorded."""
from harness import check
from services import storage, mind

def _reset():
    storage.mind_insights_table.truncate()
    storage.add_mind_insight({'slug': 'n1', 'line': 'normal', 'category': 'c',
                              'sensitivity': 'normal'})
    storage.add_mind_insight({'slug': 's1', 'line': 'secret', 'category': 'c',
                              'sensitivity': 'sensitive'})

def scenario_dismiss_records_outcome():
    _reset()
    row = storage.get_mind_insight_by_slug('n1')
    ok = storage.update_mind_insight(row['id'], {'state': 'retired',
                                                 'outcome': 'dismissed'})
    check(ok, "dismiss path writes retired/dismissed")

def scenario_act_records_outcome():
    _reset()
    row = storage.get_mind_insight_by_slug('n1')
    storage.update_mind_insight(row['id'], {'state': 'retired', 'outcome': 'acted'})
    check(storage.get_mind_insight_by_slug('n1')['outcome'] == 'acted',
          "act path writes retired/acted")

def scenario_lane_is_filtered():
    _reset()
    check(len(mind.visible_insights({'id': 'k', 'role': 'child'})) == 1,
          "child payload has no sensitive row")

if __name__ == '__main__':
    scenario_dismiss_records_outcome()
    scenario_act_records_outcome()
    scenario_lane_is_filtered()
    print("test_mind_endpoints OK")
```

- [ ] **Step 2: Run test** — passes already (it pins the storage contract the endpoints ride). The endpoint code itself is verified by the runtime test in Task 14.

- [ ] **Step 3: Implement endpoints in main.py**, beside the findings routes:

```python
@app.get("/api/mind/insights")
def mind_insights(request: Request = None):
    from services import mind as _mind
    viewer_id = _acting_id(request, None)
    viewer = storage.get_member(viewer_id) if viewer_id else None
    return {"insights": _mind.visible_insights(viewer)}


def _mind_actor(request, claimed):
    actor_id = _acting_id(request, claimed)
    actor = storage.get_member(actor_id) if actor_id else None
    if not actor or actor.get('role') in ('child', 'helper', 'guest'):
        raise HTTPException(status_code=403,
                            detail="Only a parent or adult can handle these")
    return actor


@app.post("/api/mind/insights/{insight_id}/dismiss")
def mind_dismiss(insight_id: str, body: dict = Body(default={}),
                 request: Request = None):
    import time as _t
    _mind_actor(request, body.get('member_id'))
    ok = storage.update_mind_insight(insight_id, {
        'state': 'retired', 'outcome': 'dismissed', 'resolved_ts': _t.time()})
    if not ok:
        raise HTTPException(status_code=404, detail="No such insight")
    return {"status": "success"}


@app.post("/api/mind/insights/{insight_id}/act")
def mind_act(insight_id: str, body: dict = Body(default={}),
             request: Request = None):
    import time as _t
    actor = _mind_actor(request, body.get('member_id'))
    rows = [r for r in storage.get_mind_insights() if r['id'] == insight_id]
    if not rows:
        raise HTTPException(status_code=404, detail="No such insight")
    row = rows[0]
    result = {"status": "success", "message": "Marked handled."}
    prop = row.get('proposal_json')
    if prop and prop.get('proposal_id'):
        from services import chat_actions as _ca
        result = _ca.act_on_proposal(prop['proposal_id'], 'approve', actor)
        if result.get('status') != 'success':
            raise HTTPException(status_code=400, detail=result.get('message'))
    storage.update_mind_insight(insight_id, {
        'state': 'retired', 'outcome': 'acted', 'resolved_ts': _t.time()})
    return result


@app.get("/api/mind/admin")
def mind_admin(request: Request = None):
    from services import mind as _mind
    _mind_actor(request, None)
    return {"insights": storage.get_mind_insights(state='active'),
            "history": storage.get_mind_insights(state='retired')[-60:],
            "counters": _mind.category_counters(),
            "graduation": _mind.graduation_candidates()}
```

`category_counters()`/`graduation_candidates()` land in Task 11; until then stub both in mind.py returning `{}` / `[]` so this endpoint imports clean:

```python
def category_counters() -> dict:
    return {}

def graduation_candidates() -> list:
    return []
```

- [ ] **Step 4: Full sweep** — Expected: green.

- [ ] **Step 5: Bump patch, commit + push**

Subject: `The Mind answers the door: lane, dismiss, act endpoints (vX.Y.Z)`

---

### Task 9: Board tile

**Files:**
- Modify: `chauffeur/services/home_board.py` (`_BUILDERS` at line 3791, `catalogue()` at 3857), `chauffeur/templates/home.html`
- Test: `chauffeur/tests/test_mind_tile.py`

**Interfaces:**
- Consumes: `mind.visible_insights(None)` — the tile builder ALWAYS passes `None` (boards have no viewer identity; the PWA lane is the identity-aware surface).
- Produces: `_tile_mind(now, config=None, **_) -> dict` returning `{'insights': [{'id','line','detail','domain'}]}`; registered as type `'mind'`.

- [ ] **Step 1: Write the failing test**

```python
"""The board tile never carries a sensitive row — boards have no identity."""
from harness import check
from services import storage, home_board
import datetime

def scenario_tile_filters_sensitive():
    storage.mind_insights_table.truncate()
    storage.add_mind_insight({'slug': 'a', 'line': 'normal', 'category': 'c',
                              'sensitivity': 'normal'})
    storage.add_mind_insight({'slug': 'b', 'line': 'secret', 'category': 'c',
                              'sensitivity': 'sensitive'})
    data = home_board._tile_mind(datetime.datetime.now())
    lines = [i['line'] for i in data['insights']]
    check(lines == ['normal'], f"sensitive absent from tile payload, got {lines}")

def scenario_tile_registered():
    check(home_board._BUILDERS.get('mind') is home_board._tile_mind,
          "tile type 'mind' registered")

if __name__ == '__main__':
    scenario_tile_filters_sensitive()
    scenario_tile_registered()
    print("test_mind_tile OK")
```

- [ ] **Step 2: Run test** — Expected: FAIL.

- [ ] **Step 3: Implement** — in home_board.py:

```python
def _tile_mind(now, config=None, **_):
    """Argyle noticed: the Mind's curated lane. Boards have no viewer, so this
    payload is built with no identity — sensitive rows are never in it."""
    from services import mind as _mind
    rows = _mind.visible_insights(None)
    return {'insights': [{'id': r['id'], 'line': r['line'],
                          'detail': r.get('detail') or '',
                          'domain': r.get('domain') or ''}
                         for r in rows]} if rows else None
```

Add `'mind': _tile_mind` to `_BUILDERS` and a catalogue entry (mirror a neighbor's `_opt()` usage; the tile has no config options, so the catalogue entry is name + description only: "Argyle noticed — things the Mind is keeping an eye on"). In `home.html`, add the render branch beside a simple list-style tile (find the findings/needs-you card markup and mirror its structure):

```html
<template x-if="tile.type === 'mind'">
    <div class="space-y-2">
        <div class="text-sm font-bold opacity-70">Argyle noticed</div>
        <template x-for="ins in tile.data.insights" :key="ins.id">
            <div class="rounded-xl px-3 py-2 bg-white/5">
                <div class="text-sm" x-text="ins.line"></div>
                <div class="text-xs opacity-60" x-show="ins.detail"
                     x-text="ins.detail"></div>
            </div>
        </template>
    </div>
</template>
```

Match the surrounding template's actual class idiom and Alpine structure (shade roles + hero-card rule are contracts; read `docs/ui_design_guide.md` first). Read the neighboring tile templates and copy their card wrapper exactly rather than inventing one.

- [ ] **Step 4: Rebuild Tailwind** — `python tools/build_tailwind.py`. Run `python tests/test_mind_tile.py`, then full sweep (includes `test_tailwind_build.py`). Expected: green.

- [ ] **Step 5: Bump patch, commit + push** (include regenerated stylesheets)

Subject: `Argyle noticed: the Mind's board tile (vX.Y.Z)`

---

### Task 10: PWA Family-tab lane

**Files:**
- Modify: `chauffeur/templates/app.html` (Family view; find the section that fetches `/api/findings` and anchor beside it)
- Test: covered by Task 14's hand-path test (template-only change; runtime harness verifies fetch + render)

**Interfaces:**
- Consumes: `GET /api/mind/insights` (identity comes from the session — the PWA is logged in), `POST /api/mind/insights/{id}/dismiss`, `POST /api/mind/insights/{id}/act`.

- [ ] **Step 1: Locate the anchor** — in app.html, find the Family view's Needs You/findings render (search for `/api/findings` or `findings` in the Alpine data). Add the insights lane directly below it, same card idiom.

- [ ] **Step 2: Implement** — markup (match the file's real class idiom; this is the shape, the neighboring cards are the law):

```html
<!-- Argyle noticed (the Mind, phase C) -->
<div x-show="mindInsights.length" class="mt-4">
    <div class="text-sm font-bold opacity-70 mb-2">Argyle noticed</div>
    <template x-for="ins in mindInsights" :key="ins.id">
        <div class="rounded-xl px-3 py-2 mb-2 bg-white/5">
            <div class="text-sm" x-text="ins.line"></div>
            <div class="text-xs opacity-60" x-show="ins.detail" x-text="ins.detail"></div>
            <div class="flex gap-2 mt-1" x-show="canHandleMind">
                <button class="text-xs font-bold opacity-80"
                        @click="mindAct(ins.id)">Handle it</button>
                <button class="text-xs opacity-60"
                        @click="mindDismiss(ins.id)">Dismiss</button>
            </div>
        </div>
    </template>
</div>
```

JS in the Family view's Alpine component (mirror how findings are fetched there):

```javascript
mindInsights: [],
canHandleMind: false,
async loadMind() {
    try {
        const r = await fetch('/api/mind/insights');
        this.mindInsights = (await r.json()).insights || [];
        this.canHandleMind = !['child', 'helper', 'guest']
            .includes(window.currentRole || '');
    } catch (e) { this.mindInsights = []; }
},
async mindDismiss(id) {
    await fetch(`/api/mind/insights/${id}/dismiss`, {method: 'POST',
        headers: {'Content-Type': 'application/json'}, body: '{}'});
    this.loadMind();
},
async mindAct(id) {
    await fetch(`/api/mind/insights/${id}/act`, {method: 'POST',
        headers: {'Content-Type': 'application/json'}, body: '{}'});
    this.loadMind();
},
```

Call `loadMind()` wherever the Family view loads its findings. Use however the template actually exposes the member role (check how the findings buttons gate themselves — `window.currentRole` above is illustrative; copy the real mechanism).

- [ ] **Step 3: Rebuild Tailwind, full sweep** — Expected: green.

- [ ] **Step 4: Bump patch, commit + push**

Subject: `The Family tab hears what Argyle noticed (vX.Y.Z)`

---

### Task 11: Graduation counters and candidates

**Files:**
- Modify: `chauffeur/services/mind.py` (replace the Task 8 stubs)
- Test: `chauffeur/tests/test_mind_graduation.py`

**Interfaces:**
- Produces: `category_counters() -> dict` (`{category: {'acted': n, 'dismissed': n, 'expired': n}}`), `graduation_candidates() -> list` (categories with ≥10 resolved AND act-rate ≥60% of acted+dismissed, not already in `mind_direct_categories`).

- [ ] **Step 1: Write the failing test**

```python
"""Graduation: >=10 resolved, act-rate >=60% of the family's actual answers
(acted vs dismissed — expired means unheard, it counts for volume only)."""
from harness import check
from services import storage, mind

def _seed(category, acted, dismissed, expired):
    for i in range(acted + dismissed + expired):
        iid = storage.add_mind_insight({'slug': f'{category}-{i}', 'line': 'x',
                                        'category': category})
        outcome = ('acted' if i < acted else
                   'dismissed' if i < acted + dismissed else 'expired')
        storage.update_mind_insight(iid, {'state': 'retired', 'outcome': outcome})

def scenario_candidate_math():
    storage.mind_insights_table.truncate()
    storage.get_settings = lambda: {'mind_direct_categories': []}
    _seed('supply-gap', acted=7, dismissed=2, expired=3)   # 12 resolved, 78% act
    _seed('overload', acted=2, dismissed=6, expired=2)     # 10 resolved, 25% act
    _seed('young', acted=3, dismissed=0, expired=0)        # only 3 resolved
    cands = mind.graduation_candidates()
    check([c['category'] for c in cands] == ['supply-gap'],
          f"only the proven category graduates, got {cands}")
    c = mind.category_counters()
    check(c['supply-gap']['acted'] == 7, "counters roll up per category")

def scenario_already_graduated_hidden():
    storage.get_settings = lambda: {'mind_direct_categories': ['supply-gap']}
    check(mind.graduation_candidates() == [],
          "a flipped category stops being proposed")

if __name__ == '__main__':
    scenario_candidate_math()
    scenario_already_graduated_hidden()
    print("test_mind_graduation OK")
```

- [ ] **Step 2: Run test** — Expected: FAIL (stubs return empty).

- [ ] **Step 3: Implement** (replace stubs):

```python
GRADUATION_MIN_RESOLVED = 10
GRADUATION_MIN_ACT_RATE = 0.60


def category_counters() -> dict:
    out = {}
    for r in storage.get_mind_insights(state='retired'):
        cat = r.get('category') or 'other'
        bucket = out.setdefault(cat, {'acted': 0, 'dismissed': 0, 'expired': 0})
        if r.get('outcome') in bucket:
            bucket[r['outcome']] += 1
    return out


def graduation_candidates() -> list:
    settings = storage.get_settings() or {}
    already = set(settings.get('mind_direct_categories') or [])
    out = []
    for cat, c in category_counters().items():
        if cat in already:
            continue
        resolved = c['acted'] + c['dismissed'] + c['expired']
        answered = c['acted'] + c['dismissed']
        if resolved >= GRADUATION_MIN_RESOLVED and answered \
                and c['acted'] / answered >= GRADUATION_MIN_ACT_RATE:
            out.append({'category': cat, 'resolved': resolved,
                        'act_rate': round(c['acted'] / answered, 2)})
    return sorted(out, key=lambda x: -x['act_rate'])
```

- [ ] **Step 4: Run test + full sweep** — Expected: green.

- [ ] **Step 5: Bump patch, commit + push**

Subject: `The Mind earns trust by category: graduation math (vX.Y.Z)`

---

### Task 12: Admin Mind page

**Files:**
- Create: `chauffeur/templates/mind.html`
- Modify: `chauffeur/main.py` (route), plus the admin nav (find where other feature pages — meals, boards — register their nav links and mirror it)
- Test: covered by full sweep + Task 14

**Interfaces:**
- Consumes: `GET /api/mind/admin`, `POST /api/settings` (merge semantics, main.py:14281), dismiss/act endpoints.

- [ ] **Step 1: Route** in main.py beside the other page routes (main.py:1576 pattern):

```python
@app.get("/mind")
def mind_page(request: Request):
    return templates.TemplateResponse(request=request, name="mind.html")
```

- [ ] **Step 2: Template** — copy the skeleton (head includes, theme tokens, chrome) of an existing small feature page; body sections, all one Alpine component fed by `/api/mind/admin`:

1. **Settings** — form fields for every Task-7 key, saving via `POST /api/settings` (merge, never replace). `mind_enabled` is the headline toggle with the spec's one-line explanation.
2. **Current lane** — full insight list INCLUDING sensitive (this page is parent-gated by the API), with dismiss/act buttons hitting the Task-8 endpoints.
3. **History** — retired insights with outcome chips (acted/dismissed/expired).
4. **Counters + graduation** — per-category table; each graduation candidate renders as a card: "`supply-gap` — 12 answered, 78% acted. Deliver these directly?" with a **Graduate** button that appends the category to `mind_direct_categories` via `POST /api/settings`, using `promptConfirm` (never `confirm()`).

- [ ] **Step 3: Rebuild Tailwind, full sweep** — Expected: green.

- [ ] **Step 4: Bump patch, commit + push**

Subject: `The Mind gets a room of its own: admin page (vX.Y.Z)`

---

### Task 13: Agent tools (both stacks reachable)

**Files:**
- Modify: `chauffeur/services/agent_tools_v2.py` (handlers near `list_open_findings` at line 1238; registration in `get_available_tools()` at line 2909)
- Test: `chauffeur/tests/test_mind_agent_tools.py`

**Interfaces:**
- Produces: tools `list_insights` and `dismiss_insight`, dispatched however `list_open_findings` is (verify the router's name→function dispatch and register identically).

- [ ] **Step 1: Write the failing test**

```python
"""Chat can read the lane; sensitivity respects the asking member's role."""
from harness import check
from services import storage, agent_tools_v2

def _seed():
    storage.mind_insights_table.truncate()
    storage.add_mind_insight({'slug': 'a', 'line': 'normal', 'category': 'c',
                              'sensitivity': 'normal'})
    storage.add_mind_insight({'slug': 'b', 'line': 'secret', 'category': 'c',
                              'sensitivity': 'sensitive'})

def scenario_list_respects_role():
    _seed()
    parent = agent_tools_v2.list_insights(member_role='parent')
    child = agent_tools_v2.list_insights(member_role='child')
    check(len(parent['insights']) == 2, "parent sees all")
    check(len(child['insights']) == 1, "child payload has no sensitive row")

def scenario_dismiss_tool():
    _seed()
    row = storage.get_mind_insight_by_slug('a')
    res = agent_tools_v2.dismiss_insight(insight_id=row['id'])
    check(res['status'] == 'success', f"got {res}")
    check(storage.get_mind_insight_by_slug('a')['outcome'] == 'dismissed',
          "outcome recorded")

def scenario_registered():
    names = [t['name'] for t in agent_tools_v2.get_available_tools()]
    check('list_insights' in names and 'dismiss_insight' in names,
          "both tools in the catalog")

if __name__ == '__main__':
    scenario_list_respects_role()
    scenario_dismiss_tool()
    scenario_registered()
    print("test_mind_agent_tools OK")
```

- [ ] **Step 2: Run test** — Expected: FAIL.

- [ ] **Step 3: Implement** — handlers beside `list_open_findings`:

```python
def list_insights(member_role: str = None) -> Dict[str, Any]:
    """Things Argyle's Mind is currently keeping an eye on."""
    from services import mind as _mind
    viewer = {'role': member_role} if member_role else None
    rows = _mind.visible_insights(viewer)
    return {"insights": [{"id": r['id'], "line": r['line'],
                          "detail": r.get('detail') or '',
                          "category": r.get('category')} for r in rows]}


def dismiss_insight(insight_id: str) -> Dict[str, Any]:
    """Dismiss one of the Mind's insights (the family said no)."""
    import time as _t
    from services import storage as _s
    ok = _s.update_mind_insight(insight_id, {'state': 'retired',
                                             'outcome': 'dismissed',
                                             'resolved_ts': _t.time()})
    return {"status": "success" if ok else "error"}
```

Register both in `get_available_tools()` (the shape at agent_tools_v2.py:2909):

```python
{
    "name": "list_insights",
    "description": "Lists what Argyle's Mind has noticed about the family "
                   "lately (the 'Argyle noticed' lane).",
    "parameters": {"type": "object", "properties": {}, "required": []}
},
{
    "name": "dismiss_insight",
    "description": "Dismisses one Mind insight by id after the user says "
                   "they don't want it.",
    "parameters": {"type": "object",
                   "properties": {"insight_id": {"type": "string"}},
                   "required": ["insight_id"]}
},
```

Check how the router injects caller identity into role-aware tools (some tools receive the acting member — mirror that so `member_role` is filled by the dispatch layer, not by the model).

- [ ] **Step 4: Run test + full sweep** — Expected: green.

- [ ] **Step 5: Bump patch, commit + push**

Subject: `Chat reads the Mind: both stacks reach the lane (vX.Y.Z)`

---

### Task 14: Runtime full-cycle test + hand path

**Files:**
- Test: `chauffeur/tests/test_mind_runtime.py`

**Interfaces:** Consumes everything above. This is the one test that RUNS the whole wire (entry points swallow exceptions; source-reading tests miss runtime breaks).

- [ ] **Step 1: Write the test**

```python
"""One real cycle: chat message -> sentinel notices -> think curates ->
tile shows it (no sensitive) -> dismiss lands the outcome. Fake LLM only."""
import datetime, time
from harness import check
from services import storage, mind, home_board

def scenario_full_cycle():
    storage.mind_insights_table.truncate()
    storage.mind_noticings_table.truncate()
    for k in ('mind_chat_watermark', 'mind_event_state', 'mind_finding_keys',
              'mind_shop_hash', 'mind_last_snapshot_hash', 'mind_sentinel_last',
              'mind_last_think_ts'):
        storage.set_app_state(k, None)
    storage.get_settings = lambda: {'mind_enabled': True,
                                    'llm_gemini_api_key': 'k',
                                    'mind_wake_start': '00:00',
                                    'mind_wake_end': '00:00'}
    fam = storage.get_family_channel()
    storage.chat_messages_table.insert({'id': 'rt1', 'channel_id': fam['id'],
                                        'member_id': 'mom', 'ts': time.time(),
                                        'text': 'we are out of sunscreen again'})

    def fake_pool(tier, api_key, system, prompt, **kw):
        if tier == 'background':
            return {'noticings': [{'line': 'sunscreen is out', 'source': 'chat',
                                   'urgency': 'low'}]}
        if tier == 'heavy':
            check('sunscreen is out' in prompt,
                  "the noticing reached the deep think prompt")
            return {'insights': [
                {'slug': 'sunscreen', 'line': 'Sunscreen keeps running out',
                 'category': 'supply-gap', 'sensitivity': 'normal',
                 'domain': 'supply', 'confidence': 0.9},
                {'slug': 'quiet-kid', 'line': 'Rough week for a kid',
                 'category': 'overload', 'sensitivity': 'sensitive',
                 'domain': 'kids', 'confidence': 0.6}]}
        raise AssertionError(f"unexpected tier {tier}")

    mind._pool_call = fake_pool
    res = mind.tick(datetime.datetime.now())
    check(res.get('think', {}).get('status') == 'thought', f"cycle ran: {res}")

    tile = home_board._tile_mind(datetime.datetime.now())
    lines = [i['line'] for i in tile['insights']]
    check('Sunscreen keeps running out' in lines, "insight reaches the board tile")
    check('Rough week for a kid' not in lines, "sensitive never reaches a board")

    # Hand path: the tile/PWA action works without chat.
    row = storage.get_mind_insight_by_slug('sunscreen')
    storage.update_mind_insight(row['id'], {'state': 'retired',
                                            'outcome': 'dismissed',
                                            'resolved_ts': time.time()})
    check(mind.category_counters()['supply-gap']['dismissed'] == 1,
          "the dismissal lands in the graduation counters")

if __name__ == '__main__':
    scenario_full_cycle()
    print("test_mind_runtime OK")
```

- [ ] **Step 2: Run it, fix whatever real wiring it exposes** — this test exists to break on integration seams (field names, import cycles, watermark logic). Fix the seams, not the test.

- [ ] **Step 3: Full sweep, bump patch, commit + push**

Subject: `One real breath: the Mind's full cycle under test (vX.Y.Z)`

---

### Task 15: Documentation closeout

**Files:**
- Modify: `chauffeur/system_capabilities.md` (new section), `chauffeur/config.yaml`

- [ ] **Step 1: Add a "The Mind (phase C)" section to system_capabilities.md** covering: what it is (three rungs + cadences + caps), what it reads (and the two never-reads: DMs, gifts), where it surfaces (tile / Family tab / admin page at `/mind`), sensitivity gating, the graduation mechanic, `mind_enabled` default off and how to flip it (Mind page), and the agent tools. Keep the document's existing voice.

- [ ] **Step 2: Bump patch, commit + push** (docs-only: sweep optional)

Subject: `system_capabilities learns about the Mind (vX.Y.Z)`

---

## Post-plan notes for the executor

- The spec's proposal-attachment (`proposal_json` + act wiring) ships dormant in phase C by design — Task 5's note explains why the think prompt doesn't request proposals yet. The column, the act endpoint, and the approval rail are all live, so enabling it later is a prompt change.
- Deviation from spec to flag at review: the sentinel watches chat, calendar, findings, and shopping-list size — car state feeds the hourly snapshot instead of the sentinel (car telemetry drifts slowly; the hourly think is fresh enough).
- After the final task the user flips `mind_enabled` on the Mind page and watches `/mind` fill. The deployment ritual (add-on rebuild, Check for updates) is the user's; remind, don't do.

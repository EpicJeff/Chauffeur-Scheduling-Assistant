# The Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A living low-poly 3D office at `/study` — the admin home where eleven furniture pieces are live readouts of what needs attention, every tap leading into the existing deep-dive pages.

**Architecture:** One read-only aggregator (`services/study.py`) reuses existing service calls per furniture piece, each section failure-isolated; one endpoint (`GET /api/study/state`) serves it role-filtered; a vendored three.js scene (`static/study.js`) maps that payload onto the room declaratively; `templates/study.html` shells the page and carries the honest fallback list for phones/no-WebGL.

**Tech Stack:** Python/FastAPI service + endpoint, scenario tests via `chauffeur/tests/harness.py` (`check()` + `scenario_*`, run by `chauffeur/tools/test.py`), three.js r150 UMD vendored (Alpine pattern), vanilla JS scene, canvas-generated textures. No Tailwind in the new page (inline CSS) — no rebuild needed.

**Spec:** `docs/superpowers/specs/2026-09-03-argyle-study-design.md`

## Global Constraints

- Run tests from the `chauffeur/` directory: `python tools/test.py --focus study` inner loop; full `python tools/test.py` before every commit. Never pipe the runner.
- Every commit bumps `chauffeur/config.yaml` and ends the message with `(vX.Y.Z)`; push after. This feature is v2.453.0 → v2.453.4. No double quotes inside commit message text.
- **The room never writes.** No POST/PUT anywhere in this feature; the aggregator calls read-only service functions exclusively.
- **A quiet room is the success state**: every section's empty/failed form is calm data (`[]`, `0`, `None` flags), never an error string in the payload.
- Sensitive insight lines pass through `mind.visible_insights(viewer)` — never re-implement the sensitivity filter.
- Child/helper/guest get 403 from both the page's API and see no Study nav entry (mirror the mind slug's treatment).
- Wall calendar counts **driver events only** from the cached schedule with `ghost_assignments` merged (a covered ride is never "unassigned") — the `family_digest.py:64` / `mind.py _calendar` pattern.
- Vendored file goes to `chauffeur/static/vendor/three.min.js` (r150 UMD, ~600KB, from `https://unpkg.com/three@0.150.1/build/three.min.js`).
- In any Alpine-free JS written here, still honor the repo rule: no `alert()`/`confirm()`/`prompt()`.

---

### Task 1: State aggregator — `services/study.py`

**Files:**
- Create: `chauffeur/services/study.py`
- Test: `chauffeur/tests/test_study_state.py`

**Interfaces:**
- Consumes (all existing, verified signatures): `mind.visible_insights(viewer)`; `storage.get_mind_insights(state='in_hand')`; `mind.steps_due(row)`; `threads.stalled(today=None)` + `storage.get_threads(include_closed=False)`; `storage.get_proposals(status='pending')`; `findings.open_findings()`; `storage.get_cached_schedule()`; `vitals.read(now)`; `storage.get_all_cars()` + `cars.has_telemetry(car)` + `cars.car_levels(car)`; `storage.get_deals(state='open')` (verify the live open-state name in storage.get_deals and use what negotiation.py uses); `storage.get_programs(state='active')` + `programs.weekday_shortfall(program)`; `storage.get_app_state(f'mind_calls:{date}')`; `web._month_count()` + settings `web_research_cap`; `storage.get_ingest_log(limit=10)`.
- Produces: `state(viewer: Optional[dict], now: datetime.datetime = None) -> dict` returning
  `{'furniture': {'board': {'pins': [...], 'strings': [...]}, 'desk': [...], 'tray': {...}, 'stickies': {...}, 'calendar': {...}, 'window': {...}, 'keys': [...], 'contracts': {...}, 'binders': [...], 'gauges': {...}}, 'generated_ts': float}`.

- [ ] **Step 1: Write the failing tests**

Create `chauffeur/tests/test_study_state.py`:

```python
"""The Study's one read: eleven furniture signals aggregated from existing
services, each section failure-isolated, sensitive rows filtered by the
same gate the mind lane uses. The room is a lens — nothing here writes."""
import datetime
from harness import check
from services import storage, study

NOON = datetime.datetime(2026, 9, 3, 12, 0)
PARENT = {'id': 'mom', 'role': 'parent'}
ADULT = {'id': 'uncle', 'role': 'adult'}


def _reset():
    storage.mind_insights_table.truncate()
    storage.get_settings = lambda: {'mind_enabled': True, 'llm_gemini_api_key': 'k'}


def scenario_board_pins_are_role_filtered():
    _reset()
    storage.add_mind_insight({'slug': 'plain', 'category': 'c', 'line': 'a plain one'})
    storage.add_mind_insight({'slug': 'secret', 'category': 'c', 'line': 'kid strain',
                              'sensitivity': 'sensitive'})
    parent_pins = {p['label'] for p in study.state(PARENT, now=NOON)
                   ['furniture']['board']['pins'] if p['kind'] == 'insight'}
    adult_pins = {p['label'] for p in study.state(ADULT, now=NOON)
                  ['furniture']['board']['pins'] if p['kind'] == 'insight'}
    check('kid strain' in parent_pins, 'parent sees the sensitive pin')
    check('kid strain' not in adult_pins and 'a plain one' in adult_pins,
          'adult board carries only non-sensitive pins')


def scenario_desk_stacks_carry_open_steps_and_due():
    _reset()
    iid = storage.add_mind_insight({'slug': 'p1', 'category': 'c', 'line': 'handled'})
    storage.update_mind_insight(iid, {'state': 'in_hand', 'plan_json': {
        'created_ts': 1.0, 'steps': [
            {'id': 's1', 'kind': 'tool', 'text': 't', 'owner_member_id': None,
             'owner_name': '', 'due': '2026-09-01', 'status': 'open', 'proposal_json': None},
            {'id': 's2', 'kind': 'human', 'text': 'h', 'owner_member_id': None,
             'owner_name': '', 'due': '2026-09-09', 'status': 'open', 'proposal_json': None},
            {'id': 's3', 'kind': 'human', 'text': 'd', 'owner_member_id': None,
             'owner_name': '', 'due': '2026-09-09', 'status': 'done', 'proposal_json': None},
        ]}})
    desk = study.state(PARENT, now=NOON)['furniture']['desk']
    check(len(desk) == 1 and desk[0]['open_steps'] == 2 and desk[0]['due'] is True,
          f'one stack, two open sheets, one overdue: {desk}')


def scenario_calendar_counts_only_uncovered_driver_events():
    _reset()
    storage.get_cached_schedule = lambda: {
        'events': [
            {'id': 'e1', 'start': '2026-09-04T17:00:00', 'title': 'practice'},
            {'id': 'e2', 'start': '2026-09-04T18:00:00', 'title': 'game'},
            {'id': 'e3', 'start': '2026-09-05T09:00:00', 'title': 'lesson'},
            {'id': 'e9', 'start': '2026-10-20T09:00:00', 'title': 'far away'},
        ],
        'assignments': {'e1': 'driver1'},
        'ghost_assignments': {'e2': 'ghost_neighbor'},
    }
    cal = study.state(PARENT, now=NOON)['furniture']['calendar']
    check(cal['days'][0]['date'] == '2026-09-03', 'week starts today')
    by_date = {d['date']: d['unassigned'] for d in cal['days']}
    check(by_date['2026-09-04'] == 0, 'assigned + ghost-covered are not holes')
    check(by_date['2026-09-05'] == 1, 'the real hole shows')
    check('2026-10-20' not in by_date and len(cal['days']) == 7, 'seven days only')


def scenario_a_raising_section_is_calm_not_fatal():
    _reset()
    orig = study._SECTIONS['stickies']
    study._SECTIONS['stickies'] = lambda now: (_ for _ in ()).throw(RuntimeError('boom'))
    try:
        out = study.state(PARENT, now=NOON)['furniture']
        check(out['stickies'] == study._CALM['stickies'],
              'raising section renders calm')
        check(out['tray'] is not None, 'other sections unaffected')
    finally:
        study._SECTIONS['stickies'] = orig


def scenario_gauges_read_without_writing():
    _reset()
    writes = []
    orig = storage.set_app_state
    storage.set_app_state = lambda *a, **k: writes.append(a)
    try:
        study.state(PARENT, now=NOON)
    finally:
        storage.set_app_state = orig
    check(not writes, f'the room never writes, got {writes}')
```

- [ ] **Step 2: Run to verify failure**

Run from `chauffeur/`: `python tests/test_study_state.py`
Expected: FAIL — `ImportError: cannot import name 'study'`.

- [ ] **Step 3: Implement `chauffeur/services/study.py`**

```python
"""The Study's one read. Eleven furniture signals, every section built in
its own try/except (a provider that raises contributes its calm form and
never sinks the room), all sources read-only. See
docs/superpowers/specs/2026-09-03-argyle-study-design.md."""
import datetime
import logging
import time
from typing import Optional

from services import storage

logger = logging.getLogger(__name__)

# The calm form of every section — what an empty, healthy household shows,
# and what a broken provider degrades to. Law 2: quiet is success.
_CALM = {
    'board': {'pins': [], 'strings': []},
    'desk': [],
    'tray': {'count': 0},
    'stickies': {'count': 0, 'worst': None},
    'calendar': {'days': []},
    'window': {'ready': False, 'worse': [], 'label': ''},
    'keys': [],
    'contracts': {'count': 0},
    'binders': [],
    'gauges': {'think': None, 'think_cap': None, 'research': None,
               'research_cap': None, 'ingest_errors': 0},
}


def _board(now, viewer):
    from services import mind, threads as _th
    pins, strings = [], []
    insights = mind.visible_insights(viewer, now=now)
    for r in insights:
        pins.append({'id': r['id'], 'kind': 'insight', 'label': r.get('line') or '',
                     'warn': False, 'bad': False, 'changed_ts': r.get('created_ts')})
    stalled = {t['id']: t.get('stall_reason') for t in (_th.stalled(today=now.date()) or [])}
    for t in storage.get_threads(include_closed=False):
        reason = stalled.get(t['id'])
        pins.append({'id': t['id'], 'kind': 'thread', 'label': t.get('title') or '',
                     'warn': bool(reason), 'bad': reason == 'overdue',
                     'changed_ts': t.get('created_at')})
    # Strings: insight pins connect to thread pins round-robin so the board
    # reads as one investigation. Real relations are a later slice; drawing
    # invented specifics would violate honesty, so strings only join pins
    # that EXIST, by index, and carry no claim beyond "same household".
    ins_ids = [p['id'] for p in pins if p['kind'] == 'insight']
    th_ids = [p['id'] for p in pins if p['kind'] == 'thread']
    for i, tid in enumerate(th_ids):
        if ins_ids:
            strings.append([ins_ids[i % len(ins_ids)], tid])
    return {'pins': pins[:14], 'strings': strings[:10]}


def _desk(now, viewer):
    from services import mind
    out = []
    for r in storage.get_mind_insights(state='in_hand'):
        steps = (r.get('plan_json') or {}).get('steps') or []
        open_steps = [s for s in steps if s.get('status') == 'open']
        if viewer is None or viewer.get('role') != 'parent':
            if r.get('sensitivity') == 'sensitive':
                continue
        out.append({'id': r['id'], 'open_steps': len(open_steps),
                    'due': bool(mind.steps_due(r, now.date())),
                    'changed_ts': r.get('created_ts')})
    return out[:6]


def _tray(now, viewer):
    return {'count': len(storage.get_proposals(status='pending') or [])}


def _stickies(now, viewer):
    from services import findings
    rows = findings.open_findings() or []
    order = {'high': 2, 'medium': 1, 'low': 0}
    worst = max(rows, key=lambda r: order.get(r.get('severity'), 0))['severity'] \
        if rows else None
    return {'count': len(rows), 'worst': worst}


def _calendar(now, viewer):
    sched = storage.get_cached_schedule() or {}
    assignments = dict(sched.get('assignments') or {})
    assignments.update(sched.get('ghost_assignments') or {})
    days = [(now.date() + datetime.timedelta(days=i)) for i in range(7)]
    counts = {d.isoformat(): 0 for d in days}
    for e in sched.get('events') or []:
        try:
            d = datetime.datetime.fromisoformat(
                str(e.get('start')).replace('Z', '+00:00')).date().isoformat()
        except (ValueError, TypeError):
            continue
        if d in counts and not assignments.get(e.get('id')):
            counts[d] += 1
    return {'days': [{'date': d.isoformat(), 'unassigned': counts[d.isoformat()]}
                     for d in days]}


def _window(now, viewer):
    from services import vitals
    res = vitals.read(now)
    worse = [r['label'] for r in (res.get('household') or []) if r.get('worse')]
    label = 'steady week' if res.get('ready') and not worse else \
        ('early days' if not res.get('ready') else 'a strained week')
    return {'ready': bool(res.get('ready')), 'worse': worse[:3], 'label': label}


def _keys(now, viewer):
    from services import cars
    out = []
    for car in storage.get_all_cars():
        if car.get('is_disabled') or not cars.has_telemetry(car):
            continue
        lv = cars.car_levels(car) or {}
        pct = lv.get('fuel_pct') if lv.get('fuel_pct') is not None else lv.get('battery_pct')
        out.append({'id': car.get('id'), 'name': car.get('name') or 'car',
                    'low': pct is not None and pct <= 25})
    return out[:4]


def _contracts(now, viewer):
    # Deals that still have people to hear from. get_deals stores state on
    # each row; anything not terminal counts as open ink on the desk.
    rows = storage.get_deals() or []
    openish = [d for d in rows if d.get('state') in ('proposed', 'asking', 'open')]
    return {'count': len(openish)}


def _binders(now, viewer):
    from services import programs
    out = []
    for p in storage.get_programs(state='active') or []:
        pulled = False
        try:
            short = programs.weekday_shortfall(p, now=now) or {}
            pulled = bool(short.get('short'))
        except Exception:
            pass
        out.append({'id': p.get('id'), 'title': p.get('title') or '',
                    'pulled': pulled})
    return out[:5]


def _gauges(now, viewer):
    from services import web
    settings = storage.get_settings() or {}
    day = now.date().isoformat()
    calls = dict(storage.get_app_state(f'mind_calls:{day}') or {})
    errors = sum(1 for r in (storage.get_ingest_log(limit=10) or [])
                 if 'error' in str(r.get('outcome') or '').lower())
    return {'think': int(calls.get('think', 0)),
            'think_cap': int(settings.get('mind_cap_think', 20)),
            'research': web._month_count(),
            'research_cap': int(settings.get('web_research_cap') or web.DEFAULT_MONTHLY_CAP),
            'ingest_errors': errors}


_SECTIONS = {'board': _board, 'desk': _desk, 'tray': _tray, 'stickies': _stickies,
             'calendar': _calendar, 'window': _window, 'keys': _keys,
             'contracts': _contracts, 'binders': _binders, 'gauges': _gauges}


def state(viewer: Optional[dict], now: datetime.datetime = None) -> dict:
    now = now or datetime.datetime.now()
    furniture = {}
    for key, fn in _SECTIONS.items():
        try:
            furniture[key] = fn(now, viewer)
        except Exception as e:
            logger.warning(f'[study] section {key} failed: {e}')
            furniture[key] = _CALM[key]
    return {'furniture': furniture, 'generated_ts': time.time()}
```

Note for the implementer: `_board`'s section functions take `(now, viewer)` uniformly, but the failure-isolation test replaces `_SECTIONS['stickies']` with a one-arg lambda — so `state()` must call sections as `fn(now, viewer)` and the test's lambda must match. Adjust the test lambda to `lambda now, viewer: ...` if you keep the two-arg signature (keep the two-arg signature; fix the test's lambda accordingly — this is the one deliberate correction the plan asks you to make while transcribing).

- [ ] **Step 4: Run focus tests**

Run: `python tests/test_study_state.py` then `python tools/test.py --focus study`
Expected: PASS (all five scenarios).

- [ ] **Step 5: Full sweep, bump, commit**

Run: `python tools/test.py` — must pass. Bump `chauffeur/config.yaml` to `2.453.0`.

```bash
git add chauffeur/services/study.py chauffeur/tests/test_study_state.py chauffeur/config.yaml
git commit -m 'The Study reads the house: one calm aggregator, eleven signals (v2.453.0)'
git push
```

---

### Task 2: Endpoint, page route, nav entry, fallback shell

**Files:**
- Modify: `chauffeur/main.py` (page route beside `/mind` ~line 1679; API beside the mind endpoints ~line 5130)
- Create: `chauffeur/templates/study.html`
- Modify: `chauffeur/templates/nav.html` (slug row beside `'mind'`, ~line 56; mirror every other place `grep -n "'mind'"` hits in nav.html)
- Test: `chauffeur/tests/test_study_state.py` (append endpoint scenarios)

**Interfaces:**
- Consumes: `study.state(viewer, now)` from Task 1; `_mind_actor(request, claimed)` (main.py, existing — parents/adults or admin surface; child/helper/guest 403).
- Produces: `GET /study` (TemplateResponse `study.html`), `GET /api/study/state` returning `study.state(...)` verbatim. `study.html` exposes `<div id="room"></div>`, `<div id="fallback"></div>`, and `window.STUDY_STATE_URL = 'api/study/state'` for Task 3/4.

- [ ] **Step 1: Write the failing endpoint tests**

Append to `chauffeur/tests/test_study_state.py`:

```python
def scenario_endpoint_gates_and_serves():
    _reset()
    storage.members_table.truncate()
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'kid', 'name': 'Lily', 'role': 'child'})
    import main
    from fastapi import HTTPException
    from services import auth as _auth
    orig = _auth.identify
    try:
        _auth.identify = lambda h, q: {'tier': _auth.SERVICE, 'member': None}
        res = main.study_state(request=None)
        check('furniture' in res and 'board' in res['furniture'],
              'admin surface gets the payload')
    finally:
        _auth.identify = orig
    # a child identity is refused by the same gate the mind endpoints use
    try:
        _auth.identify = lambda h, q: {'tier': _auth.DEVICE, 'device': {}, 'member': None}
        try:
            main.study_state(request=None)
            check(False, 'a device tier must not read the study')
        except HTTPException as e:
            check(e.status_code == 403, f'403, got {e.status_code}')
    finally:
        _auth.identify = orig


def scenario_template_carries_room_fallback_and_vendored_three():
    import os
    path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'study.html')
    src = open(path, encoding='utf-8').read()
    check('id="room"' in src and 'id="fallback"' in src,
          'both render targets present')
    check('static/vendor/three.min.js' in src, 'vendored three referenced')
    check('static/study.js' in src, 'scene script referenced')
    for banned in ('alert(', 'confirm(', 'prompt('):
        check(banned not in src, f'{banned} is banned')
```

- [ ] **Step 2: Run to verify failure**

Run: `python tests/test_study_state.py`
Expected: FAIL — `main` has no `study_state`; template missing.

- [ ] **Step 3: Implement**

3a. `chauffeur/main.py`, next to the other page routes (~line 1679):

```python
@app.get("/study")
def study_page(request: Request):
    return templates.TemplateResponse(request=request, name="study.html")
```

3b. `chauffeur/main.py`, after the mind endpoint block:

```python
@app.get("/api/study/state")
def study_state(request: Request = None):
    """The Study's one read. Same person-gate as the mind endpoints —
    parents/adults or a trusted admin surface; the payload is role-filtered
    underneath by mind.visible_insights."""
    from services import study as _study
    actor = _mind_actor(request, None)
    return _study.state(actor)
```

3c. `chauffeur/templates/nav.html`: add directly above the `'mind'` slug row:

```python
    {'slug': 'study', 'href': 'study', 'label': 'The Study', 'short': 'Study', 'match': '/study',
     'paths': ['M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6']},
```

Then `grep -n "'mind'" chauffeur/templates/nav.html chauffeur/main.py chauffeur/services/home_board.py` and mirror the study slug into every allowlist/visibility filter where 'mind' appears as a NAV slug (not the board tile registry `_tile_mind` — the Study gets no board tile in v1). The goal: Study's nav entry appears exactly where Mind's does, and nowhere else (kiosk shelves and wall panels never show it).

3d. `chauffeur/templates/study.html` (complete file):

```html
{% extends "base.html" %}
{% block title %}The Study{% endblock %}
{% block content %}
<style>
  #study-wrap { position: fixed; inset: 0; background: #120f0c; }
  #room, #room canvas { position: absolute; inset: 0; display: block; }
  #tip { position: fixed; pointer-events: none; background: rgba(24,20,15,.94);
    color: #e8dfc8; border: 1px solid #6b5a3e; border-radius: 8px; padding: 6px 10px;
    font: 13px/1.3 system-ui; opacity: 0; transition: opacity .15s; z-index: 40; max-width: 300px; }
  #chip { position: fixed; left: 50%; transform: translateX(-50%); bottom: 18px;
    background: rgba(24,20,15,.9); color: #e8dfc8; border: 1px solid #6b5a3e;
    border-radius: 10px; padding: 8px 14px; font: 14px system-ui; opacity: 0;
    transition: opacity .2s; z-index: 40; }
  #fallback { position: absolute; inset: 0; overflow-y: auto; padding: 20px;
    color: #e8dfc8; font: 15px/1.5 system-ui; display: none; }
  #fallback h1 { font-size: 18px; margin: 0 0 14px; color: #d8c9a8; }
  .frow { display: block; background: #1e1a15; border: 1px solid #3a332a;
    border-radius: 10px; padding: 10px 14px; margin-bottom: 8px; color: inherit;
    text-decoration: none; }
  .frow .sig { color: #e8b36a; font-size: 13px; }
  .frow.calm .sig { color: #8a9a7a; }
</style>
<div id="study-wrap">
  <div id="room"></div>
  <div id="fallback"><h1>The Study</h1><div id="fallback-rows"></div></div>
  <div id="tip"></div><div id="chip"></div>
</div>
<script>window.STUDY_STATE_URL = 'api/study/state';</script>
<script src="static/vendor/three.min.js?v={{ version }}"></script>
<script src="static/study.js?v={{ version }}"></script>
{% endblock %}
```

Check how sibling templates actually structure themselves first — if `mind.html` does not extend a `base.html` (it may be a standalone document with nav included), copy `mind.html`'s exact shell pattern (doctype, nav include, script placement, the `?v=` cache-bust convention if present) instead of the `{% extends %}` sketch above; keep the ids, styles, and script order verbatim.

- [ ] **Step 4: Run focus tests then the wire**

Run: `python tests/test_study_state.py` then `python tools/test.py --focus study` and `python tools/test.py --focus runtime`
Expected: PASS — main.py imports with the new routes.

- [ ] **Step 5: Full sweep, bump, commit**

Run: `python tools/test.py` — must pass. Bump to `2.453.1`.

```bash
git add chauffeur/main.py chauffeur/templates/study.html chauffeur/templates/nav.html chauffeur/tests/test_study_state.py chauffeur/config.yaml
git commit -m 'The Study opens its door: route, state endpoint, nav entry, fallback shell (v2.453.1)'
git push
```

---

### Task 3: The room — vendored three.js + static scene

**Files:**
- Create: `chauffeur/static/vendor/three.min.js` (download `https://unpkg.com/three@0.150.1/build/three.min.js`, commit as-is)
- Create: `chauffeur/static/study.js`
- Test: visual — playwright screenshot loop (below); no unit tests for scene code.

**Interfaces:**
- Consumes: `window.STUDY_STATE_URL`, `#room`/`#tip`/`#chip`/`#fallback` from Task 2; the Task 1 payload shape.
- Produces: `window.STUDY = {applyState(payload), scene, camera}` — Task 4 attaches interaction/life to these.

- [ ] **Step 1: Vendor three.js**

```bash
curl -sL -o chauffeur/static/vendor/three.min.js https://unpkg.com/three@0.150.1/build/three.min.js
```

Verify: `wc -c chauffeur/static/vendor/three.min.js` ≈ 613KB.

- [ ] **Step 2: Build the scene skeleton in `chauffeur/static/study.js`**

Structure (write this file; the spike at git history `office_scene2.js` era is reference-only — production starts clean with the punch-list fixed):

```javascript
/* The Study — a living office. Read-only lens; see the spec.
   Structure:
   1. capability gate: no WebGL or viewport < 900px -> fallback list
   2. canvas textures (wood, floor planks, cork, plaster, rug, sky day/night)
   3. geometry helpers: M(color, opts), box(), rbox() rounded-extrude, put()
   4. static room build — every live mesh registered in ZONES
   5. FURNITURE: declarative state->scene mutations
   6. applyState(payload) — the ONLY place scene reads data
*/
(function () {
  'use strict';
  const room = document.getElementById('room');
  const fallback = document.getElementById('fallback');

  function webglOk() {
    try { const c = document.createElement('canvas');
      return !!(c.getContext('webgl2') || c.getContext('webgl')); }
    catch (e) { return false; }
  }
  const useRoom = webglOk() && Math.min(innerWidth, innerHeight) >= 560 && innerWidth >= 900;

  // ---- fallback list: the same payload, ranked, honest ----
  function renderFallback(f) {
    const rows = [];
    const cal = (f.calendar.days || []).filter(d => d.unassigned > 0);
    if (cal.length) rows.push(['/dashboard', 'This week',
      cal.map(d => `${d.date}: ${d.unassigned} uncovered`).join(' · '), false]);
    (f.board.pins || []).forEach(p => rows.push(
      ['/mind', p.kind === 'insight' ? 'Argyle noticed' : 'Thread',
       p.label, !p.warn && !p.bad]));
    f.desk.forEach(d => rows.push(['/mind', 'Plan in hand',
      `${d.open_steps} open step${d.open_steps === 1 ? '' : 's'}${d.due ? ' — one due' : ''}`, !d.due]));
    if (f.tray.count) rows.push(['/intake', 'Intake', `${f.tray.count} waiting`, false]);
    if (f.stickies.count) rows.push(['/dashboard', 'Findings',
      `${f.stickies.count} open (${f.stickies.worst || 'low'})`, false]);
    f.keys.filter(k => k.low).forEach(k => rows.push(['/config#cars', 'Car', `${k.name} low`, false]));
    if (f.contracts.count) rows.push(['/dashboard', 'Deals', `${f.contracts.count} awaiting answers`, false]);
    f.binders.filter(b => b.pulled).forEach(b => rows.push(['/programs', 'Program', `${b.title} needs a look`, false]));
    if (!rows.length) rows.push(['', 'All quiet', 'Nothing needs you right now.', true]);
    document.getElementById('fallback-rows').innerHTML = rows.map(([href, kind, sig, calm]) =>
      `<a class="frow${calm ? ' calm' : ''}" ${href ? `href="${href}"` : ''}>` +
      `<strong>${kind}</strong><div class="sig"></div></a>`).join('');
    [...document.querySelectorAll('#fallback-rows .sig')].forEach((el, i) => el.textContent = rows[i][2]);
  }

  async function poll(apply) {
    try {
      const r = await fetch(window.STUDY_STATE_URL);
      if (r.ok) apply((await r.json()).furniture);
    } catch (e) { /* next poll retries; the room stays calm */ }
    setTimeout(() => poll(apply), 60000);
  }

  if (!useRoom) { fallback.style.display = 'block'; poll(renderFallback); return; }

  // ---- textures / helpers / room build / FURNITURE / applyState ----
  // (three.js scene: see acceptance criteria — this is art code, iterated
  //  against screenshots, not transcribed from the plan)
  // ... scene code ...
  window.STUDY = { applyState, scene, camera: cam };
  poll(applyState);
})();
```

The scene body is authored, not transcribed. Hard requirements it must meet:

- All eleven furniture pieces from the spec's inventory table, each mesh group registered as `ZONES[name] = {meshes, url, focus?}` with names exactly: `board, desk, tray, stickies, calendar, window, keys, contracts, binders, gauges` (plus decoration unregistered).
- `FURNITURE` is a declarative map `{sectionKey: (data, zone) => mutations}` — stack heights from `desk[i].open_steps` (one sheet mesh per open step, cap 8), amber sheet when `due`, tray sheet count (cap 6), sticky count/severity colors, calendar 7 cells red when `unassigned > 0`, window sky day/night + `label`, key tags on `low`, contract slips on `count`, binder pulled on `pulled`, gauge needles from `think/think_cap` and `research/research_cap`.
- Board pins: one pinned card per `board.pins` entry (cap 14), `warn` = yellowed + sagged rotation, `bad` = red-tinted; strings drawn as sagging tubes between the pin pairs in `board.strings`.
- **Punch list from the spike, mandatory:** corkboard frame rails positioned FROM the board's dimensions (compute, don't hardcode); monitor bezel faces the camera-side with the screen plane parallel to the bezel front; key hooks modeled as a small board + hooks + keys with readable silhouettes; chair with a rounded seat/back; color grade saturated toward the approved reference (exposure ≈ .95, warm hemisphere, cool window key light).
- Quiet room: zero pins, empty tray, no reds → the room simply looks tidy. No placeholder text anywhere in the scene.
- Perf: pixelRatio ≤ 2, one 2048 shadow map, no postprocessing, static geometry outside `applyState`.

- [ ] **Step 3: Screenshot loop (the visual test)**

Seed one insight, one in-hand plan, one stalled thread, one pending proposal locally (python shell against the dev DB, `CHAUFFEUR_DATA_DIR` pointed at `data/`), run `python -m uvicorn main:app --port 8099` from `chauffeur/`, screenshot `http://127.0.0.1:8099/study` with playwright (viewport 1440×900), and LOOK at it. Iterate until every acceptance criterion above is visibly true. Save the final screenshot to the task report. Then clear the seeded rows.

- [ ] **Step 4: Full sweep, bump, commit**

Run: `python tools/test.py` — must pass (template pin from Task 2 now finds the real files). Bump to `2.453.2`.

```bash
git add chauffeur/static/vendor/three.min.js chauffeur/static/study.js chauffeur/config.yaml
git commit -m 'The Study takes shape: vendored three, the room, eleven live signals (v2.453.2)'
git push
```

---

### Task 4: Interaction and life

**Files:**
- Modify: `chauffeur/static/study.js`
- Test: visual — extend the Task 3 screenshot loop with interaction states; plus one template-level source pin appended to `chauffeur/tests/test_study_state.py`.

**Interfaces:**
- Consumes: `ZONES`, `applyState`, `#tip`/`#chip` from Task 3.
- Produces: the finished page.

- [ ] **Step 1: Append the source pin test**

```python
def scenario_scene_honors_the_read_only_law():
    import os, re
    path = os.path.join(os.path.dirname(__file__), '..', 'static', 'study.js')
    src = open(path, encoding='utf-8').read()
    check(not re.search(r"method:\s*['\"](POST|PUT|DELETE|PATCH)", src),
          'the room never writes')
    check("localStorage" in src and 'try' in src,
          'since-you-were-here uses guarded localStorage')
```

Run: `python tests/test_study_state.py` — the localStorage half FAILS until Step 2.

- [ ] **Step 2: Implement interaction + life in `study.js`**

Requirements (authored code, same screenshot-loop verification):

- **Hover:** raycast against registered zone meshes; `#tip` shows the zone's current one-line signal (built from the latest payload, e.g. `Intake — 3 waiting`). Cursor pointer on hit.
- **Lean-in:** first click on `board` or `desk` lerps the camera to that zone's `focus` preset and shows `#chip` with the zone summary + "tap again to open"; second click navigates to the zone's `url`. Every other zone navigates on first click. Escape or clicking empty space lerps back.
- **Life:** camera idle drift + cursor parallax (damped, ±.35 units); monitor glow breathing; dust motes; steam off the mug; working clock hands from `new Date()`; stalled pins sway gently; day/night sky chosen by local hour (redraw sky texture when the day/night boundary crosses during a poll).
- **Flying paper:** every ~90s, only when `tray.count > 0` AND the board has ≥1 insight pin, a sheet animates tray → board along a bezier. Honest, not theatrical.
- **Since-you-were-here:** wrap ALL localStorage access in try/catch; key `study_last_visit`; any pin/stack whose `changed_ts` exceeds the stored value gets a soft emissive glow; 10s after first render, write the new timestamp. Absent storage → no glows, no errors.
- **Poll refresh:** `applyState` diffs against the previous payload minimally (rebuild pin/sheet groups wholesale is fine — they're tiny); no flicker of the static room.
- **Error chip:** when a poll fails, show a small fixed chip "can't reach the house right now" once (not per retry), clear it on the next success.

- [ ] **Step 3: Screenshot + interaction verification**

Re-run the Task 3 harness; capture: (a) default room, (b) leaned into the board with chip visible, (c) the fallback list at 800px width. All three into the report. Verify by eye against the spec's acceptance criteria and the punch list.

- [ ] **Step 4: Full sweep, bump, commit**

Run: `python tools/test.py` — must pass. Bump to `2.453.3`.

```bash
git add chauffeur/static/study.js chauffeur/tests/test_study_state.py chauffeur/config.yaml
git commit -m 'The Study comes alive: lean-in, tooltips, drift, the filing paper (v2.453.3)'
git push
```

---

### Task 5: Capabilities doc + final sweep

**Files:**
- Modify: `chauffeur/system_capabilities.md`

- [ ] **Step 1: Document**

Add a Study section (near the Mind section, matching the document's tone): the room as admin home at `/study`, the four laws, the furniture inventory table (copy from the spec), the state endpoint and its per-section failure isolation, role filtering via the mind's own gate, the fallback list as the phone experience, vendored three.js, and that the room never writes. Note the spec path.

- [ ] **Step 2: Full sweep, bump, commit**

Run: `python tools/test.py` — must pass. Bump to `2.453.4`.

```bash
git add chauffeur/system_capabilities.md chauffeur/config.yaml
git commit -m 'Record the Study in system capabilities (v2.453.4)'
git push
```

---

## Self-review notes (resolved inline)

- Spec coverage: laws → Task 1 (`_CALM`, read-only test) + Task 4 source pin; route/nav/fallback → Task 2; inventory/punch list/perf → Task 3; interaction/life/glow/error chip → Task 4; docs → Task 5. Board "real relations" strings deliberately shipped as honest index-joins (noted in code comment) — the spec's string semantics ("real relations") is narrowed for v1; flagged here so the reviewer sees it: v1 strings claim nothing beyond co-existence, matching the spec's honesty law over its illustration.
- Scene code is authored-not-transcribed by design; acceptance criteria + screenshot loop are the test. This is the one place the no-placeholder rule yields to art.
- Type consistency: `state(viewer, now)`; section functions `(now, viewer)`; payload keys match between Task 1 tests, Task 2 template contract, and Task 3 `FURNITURE` map.

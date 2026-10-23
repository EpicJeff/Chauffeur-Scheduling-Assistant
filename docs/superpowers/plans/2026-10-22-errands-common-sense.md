# Errands With Common Sense Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Errands get the right default with no setting (groceries ride home, no 08:00 Saturday trip from home, a passing drive with an estimated leg beats a known round trip), and every steer writes a soft preference the pass scores from then on and lists on the Errands page.

**Architecture:** A new `services/errand_prefs.py` owns the kind table, the preference store's semantics (what a steer teaches, how a row is weighted and described) and the band/weekday matching. `solver/matcher.insert_errands_globally` reads it: home-bound kinds lose the before-first and between shapes, the empty-day shape keeps human hours, a leg with no cached minutes is estimated from coordinates and surcharged instead of ranking last, and each candidate's cost carries the preference cost. Both steer writers (the PUT in `main.py`, the agent's `handle_update_errand`) call one `learn_from_steer` before they forget placements. Three parent-only routes and a Learned block on the Errands drawer make every preference visible and deletable; two optional fields on `Errand` (`kind`, `home_bound`) are the hand override.

**Tech Stack:** Python 3 / FastAPI / pydantic 2, TinyDB-shaped storage over SQLite (`services/storage.py`, app-state rows), Jinja + Alpine templates, node for template JS tests, Mapbox Matrix via `services/maps.prime_matrix_cache`, cached geocodes via `storage.get_cached_geocode`.

**Spec:** `docs/superpowers/specs/2026-10-22-errands-common-sense-design.md` (rev 1). Read it first; the plan argues from it. The shipped arc it extends: `docs/superpowers/specs/2026-10-22-errands-ride-the-route-design.md` and `tests/test_errand_routing.py`.

## Global Constraints

- Tests run from `chauffeur/` as plain scripts: `python tests/test_x.py`. Unset `HA_BASE_URL` first (`unset HA_BASE_URL` in bash). Never run the whole suite.
- Every test file isolates storage with `os.environ.setdefault("CHAUFFEUR_DATA_DIR", tempfile.mkdtemp(...))` BEFORE importing `services.storage`, and stubs `maps.prime_matrix_cache` so nothing reaches the network.
- Drive-time reads inside the pass go through the module globals `errand_leg_minutes` and `errand_leg_estimate`, looked up on the module at call time (never captured in a default argument or closure), so tests can stub them.
- `errand_leg_minutes` never returns a fallback; an estimate is never written into `travel_to_mins` / `travel_from_mins`; the pass never raises `UncachedTravelPair` and never fetches under `maps.travel_cache_only_active()`.
- Zero new settings. The kind table, the dedicated-trip hours, the 10-minute surcharge, `5 × weight` capped at 30 and the 90-day half-life are module constants in `services/errand_prefs.py`.
- Preferences are soft: they move `cost`, never filter a candidate.
- No browser dialogs: `promptConfirm`, `showGlobalAlert` only (`templates/components/control_center.html`).
- Tailwind is precompiled: after any template class change run `python tools/build_tailwind.py` from `chauffeur/`.
- Never remove anything a person can do today (tick, Reschedule, Edit, Delete, Steer, the rules, the setting, Complete on the phone, the agent's add/update/delete/get).
- Every agent capability has a hand path: `kind` and `home_bound` are in the admin editor; `get_errand_preferences` / `forget_errand_preference` are the Learned block.
- `services/auth.RULES` is first-match: the `/api/errands/preferences/*` row goes ABOVE the `/api/errands/*` row. FastAPI matches routes in declaration order too: the preference routes are declared ABOVE `@app.put("/api/errands/{doc_id}")` and `@app.delete("/api/errands/{doc_id}")`.
- Vendored Alpine stamps `:disabled="x[loop.id]"` true on first render: coerce booleans with `!!`.
- Do not bump `chauffeur/config.yaml` and do not commit from an implementer task; Claude reviews, documents, bumps and commits each task.
- PowerShell: no double quotes in commit messages; never round-trip source through `Get-Content`/`Set-Content`. Use the Bash tool or Python for file edits.

## Review Focus

Inputs the spec implies but no task's tests exercised at first draft; each now has its test in the owning task:

1. **A home-bound errand on a day whose only stops are a drop-off-and-run ride** (groceries, Saturday, Jeff drops Kate at soccer and comes back): the drop → pickup gap is a `between` shape and is NOT offered; the only candidates are the after-pickup-then-home leg and the round trip. Task 2 test `scenario_groceries_never_sit_inside_a_drop_off_and_run_ride`.
2. **A title that matches two kinds** ("pick up the prescription"): `pharmacy` wins because the table is walked in order (groceries, pharmacy, return, pickup, service) and pharmacy is checked before pickup. Task 1 test `scenario_the_kind_table_is_walked_in_order`.
3. **A steer whose errand has no cached placement** (Skip a day on an unplaced errand): the row is scoped `*`, never a crash on a missing driver. Task 4 test `scenario_a_steer_without_a_placement_is_scoped_to_everyone`.
4. **A pinned time that straddles two bands** (admin editor pin 10:00–13:00): the band containing the midpoint 11:30 is `morning` (first in order whose range holds it). Task 1 test `scenario_a_pin_that_fits_no_band_exactly_takes_its_midpoint`.
5. **Both places share cached coordinates but no cached pair** (two shops in one plaza): the estimate is `0 + 2 = 2` minutes, never `None`, and never negative. Task 3 test `scenario_an_estimate_for_the_same_spot_is_two_minutes`.

---

## File map

- Create `services/errand_prefs.py`: kind table and `errand_kind`, `is_home_bound`, bands and `band_for`, `learn_from_steer`, `effective_weight`, `preference_cost`, `describe`, the constants.
- Modify `models/schemas.py`: `ERRAND_KINDS`; `Errand.kind`, `Errand.home_bound` with validators; `ErrandRule.kind`, `ErrandRule.home_bound`; `ERRAND_ROUTING_FIELDS` grows by the two.
- Modify `services/storage.py`: `get_errand_preferences`, `upsert_errand_preference`, `delete_errand_preference`, `clear_errand_preferences` (after `get_errand_placement_notes`, `:8559`).
- Modify `solver/matcher.py`: `errand_leg_estimate`, `_prime_route_pairs`, `errand_why_text` (estimated + learned), `insert_errands_globally` (home-bound shapes, dedicated-trip bounds, estimation, surcharge, preference cost, ranking key).
- Modify `main.py`: three preference routes above `POST /api/errands` (`:18302` region); `GET /api/errands` adds `kind_inferred`; `PUT /api/errands/{doc_id}` learns before it forgets; `POST /api/errands` rule application copies `kind` / `home_bound`.
- Modify `services/auth.py`: one row above `(ANY, '/api/errands/*', SIGNED_IN, 'lists.errands')` (`:382`).
- Modify `services/agent_tools_v2.py`: `AddErrandTool` / `UpdateErrandTool` fields and handlers; `GetErrandPreferencesTool`, `ForgetErrandPreferenceTool`, handlers, registration in `ADMIN_TOOLS`, `SCHEDULE_MUTATING_ADMIN_TOOLS`, `TOOL_SCHEMAS`, `TOOL_HANDLERS`; `services/missions.READ_TOOLS` gains `get_errand_preferences`.
- Modify `templates/errands.html`: kind select + guessed chip + On the way home select in the edit modal; the Learned block included in the drawer after `errand_rules.html`.
- Create `templates/components/errand_learned.html`: the Learned block (Alpine `errandLearnedPanel()`).
- Modify `templates/components/errand_lists.html` and `templates/app.html`: `_putErrand` / `pwaSteerErrand` strip `kind_inferred` before the PUT.
- Create `tests/test_errand_common_sense.py`, `tests/test_errand_prefs_api.py`; extend `tests/test_errand_lists_render.py`.

---

### Task 1: `errand_prefs.py` — kinds, bands, store semantics, descriptions

**Files:**
- Create: `services/errand_prefs.py`
- Modify: `models/schemas.py:1672` (Errand), `:1762` (ErrandRule), `:1754` (ERRAND_ROUTING_FIELDS)
- Modify: `services/storage.py:8559` (after `get_errand_placement_notes`)
- Test: `tests/test_errand_common_sense.py` (new; the pure half)

**Interfaces:**
- Produces on `models.schemas`: `ERRAND_KINDS = ('groceries', 'pharmacy', 'return', 'pickup', 'service', 'other')`; `Errand.kind: Optional[str] = None` (validated: lower-cased, must be in `ERRAND_KINDS`, `''` → `None`); `Errand.home_bound: Optional[bool] = None`; the same two on `ErrandRule`; `ERRAND_ROUTING_FIELDS` includes `'kind'` and `'home_bound'`.
- Produces on `services.errand_prefs`:
  - `KIND_KEYWORDS: dict[str, list[str]]`, `HOME_BOUND_KINDS = frozenset({'groceries', 'pharmacy'})`
  - `STEER_BANDS = {'morning': ('08:00', '12:00'), 'midday': ('11:00', '14:00'), 'afternoon': ('14:00', '17:00'), 'evening': ('17:00', '20:00')}` (order matters)
  - `DEDICATED_START_WEEKDAY = time(9, 0)`, `DEDICATED_START_WEEKEND = time(10, 0)`, `DEDICATED_END = time(17, 0)`, `ESTIMATE_SURCHARGE_MINS = 10`, `PREF_STEP_MINS = 5`, `PREF_CAP_MINS = 30`, `PREF_MAX_WEIGHT = 6`, `PREF_HALF_LIFE_DAYS = 90`, `PREF_PRUNE_BELOW = 0.5`
  - `errand_kind(errand: dict, lists: Optional[list] = None) -> str`
  - `is_home_bound(errand: dict, kind: Optional[str] = None) -> bool`
  - `band_for(start: Optional[str], end: Optional[str]) -> Optional[str]`
  - `effective_weight(row: dict, now: Optional[float] = None) -> float`
  - `preference_cost(rows, driver_id, kind, day_date, start_dt, now=None) -> tuple[int, list[str]]`
  - `learn_from_steer(before: dict, after: dict, placement: Optional[dict] = None, now: Optional[float] = None) -> list[dict]` (rows as stored, after upsert)
  - `describe(row: dict, people: dict) -> str`
- Produces on `services.storage`: `get_errand_preferences() -> list[dict]`; `upsert_errand_preference(row: dict, now: Optional[float] = None) -> dict`; `delete_errand_preference(pref_id: str) -> bool`; `clear_errand_preferences() -> int`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_errand_common_sense.py`:

```python
"""Errands with common sense — kinds, defaults, estimates, what a steer teaches.

Spec: docs/superpowers/specs/2026-10-22-errands-common-sense-design.md
§1 (kind inference), §2 (defaults per kind), §3 (estimated legs),
§4 (the preference store, what a steer teaches, scoring).

Same grid as test_errand_routing.py: places are points, drive minutes are
Manhattan distance, a place off the grid has no cached minutes (None).
`matcher.errand_leg_estimate` is stubbed too so the estimate path is exact.

Run from chauffeur/:  python tests/test_errand_common_sense.py
"""
import datetime
import os
import sys
import tempfile
import time as _time

os.environ.setdefault("CHAUFFEUR_DATA_DIR", tempfile.mkdtemp(prefix="chauffeur_errand_cs_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import check  # noqa: E402
from models.schemas import Driver, Event  # noqa: E402
from services import errand_prefs, maps, storage  # noqa: E402
from solver import matcher  # noqa: E402

maps.prime_matrix_cache = lambda locations, ignore_age=False: None

GRID = {'Home': (0, 0), 'Soccer': (20, 0), 'Store': (10, 10), 'Work': (0, 30),
        'Pharmacy': (0, 20), 'Dentist': (30, 0), 'Shop': (-4, -4),
        'Clinic': (0, 10), 'Piano': (-30, 0), 'Lab': (-4, -20)}
# Places with coordinates but NO cached pairs: the estimate path sees them.
ESTIMATE_ONLY = {'Plaza': (12, 0), 'Gym': (24, 0)}


def _leg(a, b):
    if not a or not b:
        return None
    if a == b:
        return 0
    if a not in GRID or b not in GRID:
        return None
    (x1, y1), (x2, y2) = GRID[a], GRID[b]
    return abs(x1 - x2) + abs(y1 - y2)


def _estimate(a, b):
    pts = dict(GRID, **ESTIMATE_ONLY)
    if not a or not b or a not in pts or b not in pts:
        return None
    if a == b:
        return 2
    (x1, y1), (x2, y2) = pts[a], pts[b]
    return abs(x1 - x2) + abs(y1 - y2) + 2


matcher.errand_leg_minutes = _leg
matcher.errand_leg_estimate = _estimate

MON = datetime.date(2026, 10, 26)
DAYS = [str(MON + datetime.timedelta(days=i)) for i in range(7)]   # Mon..Sun
NOW = datetime.datetime(2026, 10, 25, 20, 0).astimezone()           # Sunday evening
SETTINGS = {'errand_dedicated_trip_mins': 25}


def _fresh():
    with storage.db_lock:
        storage.app_state_table.truncate()


def _at(day_idx, h, m=0, dur=60):
    s = datetime.datetime.combine(MON + datetime.timedelta(days=day_idx), datetime.time(h, m)).astimezone()
    return s, s + datetime.timedelta(minutes=dur)


def _ev(eid, day_idx, h, loc, title=None, m=0, dur=60, **kw):
    s, e = _at(day_idx, h, m, dur)
    return Event(id=eid, title=title or loc, start=s, end=e, location=loc,
                 calendar_ids=['c'], source_event_ids=[eid], **kw)


def _driver(did, name):
    return Driver(id=did, name=name, home_location='Home', color_code='#000')


def _errand(**over):
    base = {'id': 'er1', 'doc_id': 1, 'title': 'Costco run', 'duration_mins': 30,
            'location': 'Store', 'priority': 2, 'is_completed': False, 'status': 'pending',
            'created_at': NOW.timestamp(), 'starts_on': None, 'recurrence_rule': None,
            'window_days': 7, 'skip_dates': [], 'pinned_date': None, 'pinned_start': None,
            'pinned_end': None, 'once_driver_id': None, 'tags': [], 'kind': None,
            'home_bound': None}
    base.update(over)
    return base


def _world(events_by_day, drivers, assignments):
    out = {}
    for i, d in enumerate(DAYS):
        evs = events_by_day.get(i, [])
        out[d] = {'assignments': {e.id: assignments[e.id] for e in evs if e.id in assignments},
                  'events': evs}
    return out


def _place(base, errands, drivers, driver_events=None, settings=SETTINGS, now=NOW):
    by_date, notes = matcher.insert_errands_globally(
        base, errands, drivers, trip_metadata=[], driver_events=driver_events or {},
        now=now, settings=settings)
    rows = [(d, r) for d, rs in by_date.items() for r in rs]
    return rows, notes


def _only(rows, errand_id='er1'):
    mine = [(d, r) for d, r in rows if r['id'] == errand_id]
    check(len(mine) == 1, f"placed exactly once, got {mine}")
    return mine[0]


def _start(row):
    return datetime.datetime.fromisoformat(row['start_time']).astimezone().time()


# ---------------------------------------------------------------- §1 kinds

def scenario_the_kind_table_reads_tags_then_title_then_the_override():
    k = errand_prefs.errand_kind
    check(k(_errand(title='Costco run'), lists=[]) == 'groceries', "Costco is groceries")
    check(k(_errand(title='Weekly shop at Kroger'), lists=[]) == 'groceries', "Kroger is groceries")
    check(k(_errand(title='Pick up groceries'), lists=[]) == 'groceries', "pick up groceries is groceries, not a pickup")
    check(k(_errand(title='Walgreens'), lists=[]) == 'pharmacy', "Walgreens is a pharmacy")
    check(k(_errand(title='Return library books'), lists=[]) == 'return', "a return")
    check(k(_errand(title='Drop off the dry cleaning'), lists=[]) == 'return', "drop off is a return")
    check(k(_errand(title='Pick up the dry cleaning'), lists=[]) == 'pickup', "a pickup")
    check(k(_errand(title='Haircut'), lists=[]) == 'service', "a service")
    check(k(_errand(title='Oil change'), lists=[]) == 'service', "a service")
    check(k(_errand(title='Mystery'), lists=[]) == 'other', "nothing matched: other")
    check(k(_errand(title='Mystery', tags=['groceries']), lists=[]) == 'groceries', "a tag decides")
    check(k(_errand(title='Costco run', kind='service'), lists=[]) == 'service', "the override wins over the title")
    check(k(_errand(title='Mystery'), lists=[{'id': 'l1', 'name': 'Groceries'}]) == 'groceries',
          "a bound shopping list means groceries")
    check(k(_errand(title='Costco', tags=['pharmacy']), lists=[]) == 'pharmacy',
          "tags are read before the title")
    check(k(_errand(title='Grocer'), lists=[]) == 'other', "word boundaries: 'grocer' is not 'grocery'")


def scenario_the_kind_table_is_walked_in_order():
    check(errand_prefs.errand_kind(_errand(title='Pick up the prescription'), lists=[]) == 'pharmacy',
          "pharmacy is checked before pickup")
    check(errand_prefs.errand_kind(_errand(title='Return the Costco order'), lists=[]) == 'groceries',
          "groceries is checked before return")


def scenario_home_bound_follows_the_kind_unless_overridden():
    hb = errand_prefs.is_home_bound
    check(hb(_errand(title='Costco run'), 'groceries') is True, "groceries ride home")
    check(hb(_errand(title='CVS'), 'pharmacy') is True, "pharmacy rides home")
    check(hb(_errand(title='Haircut'), 'service') is False, "a service rides any leg")
    check(hb(_errand(title='Costco run', home_bound=False), 'groceries') is False, "False overrides")
    check(hb(_errand(title='Haircut', home_bound=True), 'service') is True, "True overrides")


def scenario_the_errand_model_validates_kind_and_home_bound():
    from models.schemas import Errand, ErrandRule, ERRAND_ROUTING_FIELDS, ERRAND_KINDS
    e = Errand(**_errand(kind='Groceries', home_bound=True))
    check(e.kind == 'groceries' and e.home_bound is True, "kind lower-cased, home_bound kept")
    check(Errand(**_errand(kind='')).kind is None, "empty kind is None")
    try:
        Errand(**_errand(kind='snacks'))
        check(False, "an unknown kind is rejected")
    except Exception:
        pass
    check('kind' in ERRAND_ROUTING_FIELDS and 'home_bound' in ERRAND_ROUTING_FIELDS,
          "both forget placements when changed")
    check(ERRAND_KINDS == ('groceries', 'pharmacy', 'return', 'pickup', 'service', 'other'), f"{ERRAND_KINDS}")
    r = ErrandRule(title='Grocery runs', keywords=['grocer'], kind='groceries', home_bound=True)
    check(r.kind == 'groceries' and r.home_bound is True, "a rule carries both")


# ---------------------------------------------------------------- §4.2 bands

def scenario_bands_match_exactly_or_by_midpoint():
    b = errand_prefs.band_for
    check(b('17:00', '20:00') == 'evening', "an exact band")
    check(b('08:00', '12:00') == 'morning', "an exact band")
    check(b('15:00', '16:00') == 'afternoon', "a window inside a band takes that band")
    check(b('19:30', None) == 'evening', "start alone is the midpoint")
    check(b(None, '09:00') == 'morning', "end alone is the midpoint")
    check(b(None, None) is None, "no pin, no band")
    check(b('06:00', '07:00') == 'morning', "before every band: morning")
    check(b('21:00', '22:00') == 'evening', "after every band: evening")


def scenario_a_pin_that_fits_no_band_exactly_takes_its_midpoint():
    check(errand_prefs.band_for('10:00', '13:00') == 'morning',
          "midpoint 11:30 is in morning (08-12) and midday (11-14); the first band in order wins")


# ---------------------------------------------------------------- §4 store

def scenario_upsert_grows_weight_and_delete_and_clear_work():
    _fresh()
    row = {'scope': 'd1', 'kind': 'groceries', 'dimension': 'weekday', 'value': '5',
           'polarity': 'avoid', 'source': 'steer'}
    a = storage.upsert_errand_preference(dict(row), now=1_000_000.0)
    check(a['id'] and a['weight'] == 1.0 and a['last_seen'] == 1_000_000.0, f"first write: {a}")
    b = storage.upsert_errand_preference(dict(row), now=1_000_100.0)
    check(b['id'] == a['id'] and b['weight'] == 2.0 and b['last_seen'] == 1_000_100.0, f"same row grows: {b}")
    for _ in range(10):
        b = storage.upsert_errand_preference(dict(row), now=1_000_200.0)
    check(b['weight'] == errand_prefs.PREF_MAX_WEIGHT, f"weight caps at {errand_prefs.PREF_MAX_WEIGHT}: {b}")
    other = storage.upsert_errand_preference(dict(row, polarity='prefer'), now=1_000_000.0)
    check(other['id'] != a['id'] and len(storage.get_errand_preferences()) == 2, "polarity is part of the key")
    check(storage.delete_errand_preference(other['id']) is True and len(storage.get_errand_preferences()) == 1, "delete one")
    check(storage.delete_errand_preference('nope') is False, "deleting a missing id is False")
    check(storage.clear_errand_preferences() == 1 and storage.get_errand_preferences() == [], "clear all")


def scenario_weight_decays_with_a_90_day_half_life_and_stale_rows_prune():
    _fresh()
    now = 2_000_000_000.0
    row = {'id': 'p1', 'scope': 'd1', 'kind': 'groceries', 'dimension': 'weekday', 'value': '5',
           'polarity': 'avoid', 'weight': 2.0, 'last_seen': now - 90 * 86400, 'source': 'steer'}
    check(abs(errand_prefs.effective_weight(row, now) - 1.0) < 1e-6, "half after 90 days")
    check(abs(errand_prefs.effective_weight(dict(row, last_seen=now), now) - 2.0) < 1e-6, "full when fresh")
    stale = dict(row, id='p2', weight=1.0, last_seen=now - 200 * 86400)   # 0.21 effective
    storage.set_app_state('errand_preferences', [row, stale])
    storage.upsert_errand_preference({'scope': '*', 'kind': 'other', 'dimension': 'driver', 'value': 'd2',
                                      'polarity': 'prefer', 'source': 'steer'}, now=now)
    ids = {r['id'] for r in storage.get_errand_preferences()}
    check('p1' in ids and 'p2' not in ids, f"a write prunes rows under {errand_prefs.PREF_PRUNE_BELOW}: {ids}")


def scenario_preference_cost_is_soft_scoped_and_clamped():
    now = NOW.timestamp()
    sat = MON + datetime.timedelta(days=5)
    start = datetime.datetime.combine(sat, datetime.time(10, 0)).astimezone()
    rows = [
        {'id': 'a', 'scope': 'd1', 'kind': 'groceries', 'dimension': 'weekday', 'value': '5',
         'polarity': 'avoid', 'weight': 2.0, 'last_seen': now, 'source': 'steer'},
        {'id': 'b', 'scope': '*', 'kind': '*', 'dimension': 'time_band', 'value': 'morning',
         'polarity': 'prefer', 'weight': 1.0, 'last_seen': now, 'source': 'steer'},
        {'id': 'c', 'scope': '*', 'kind': 'groceries', 'dimension': 'driver', 'value': 'd2',
         'polarity': 'prefer', 'weight': 1.0, 'last_seen': now, 'source': 'steer'},
        {'id': 'd', 'scope': 'd2', 'kind': 'groceries', 'dimension': 'weekday', 'value': '5',
         'polarity': 'avoid', 'weight': 6.0, 'last_seen': now, 'source': 'steer'},
    ]
    cost, hit = errand_prefs.preference_cost(rows, 'd1', 'groceries', sat, start, now)
    check(cost == 10 - 5 and sorted(hit) == ['a', 'b'], f"avoid 2×5 minus prefer 1×5, scoped to d1: {cost} {hit}")
    cost, hit = errand_prefs.preference_cost(rows, 'd2', 'groceries', sat, start, now)
    check(cost == 20 and sorted(hit) == ['b', 'c', 'd'], f"d2: avoid 6×5=30 minus prefer 5+5: {cost} {hit}")
    cost, hit = errand_prefs.preference_cost(rows, 'd1', 'service', sat, start, now)
    check(cost == -5 and hit == ['b'], f"only the any-kind band row matches a service: {cost} {hit}")
    mon_start = datetime.datetime.combine(MON, datetime.time(15, 0)).astimezone()
    cost, hit = errand_prefs.preference_cost(rows, 'd1', 'groceries', MON, mon_start, now)
    check(cost == 0 and hit == [], "Monday afternoon matches nothing")
    heavy = [dict(rows[0], id=f'h{i}', value='5') for i in range(8)]
    cost, _ = errand_prefs.preference_cost(heavy, 'd1', 'groceries', sat, start, now)
    check(cost == errand_prefs.PREF_CAP_MINS, f"clamped at {errand_prefs.PREF_CAP_MINS}: {cost}")


def scenario_describe_speaks_plainly():
    people = {'d1': 'Jeff', 'd2': 'Lorena'}
    d = errand_prefs.describe
    check(d({'scope': 'd1', 'kind': 'groceries', 'dimension': 'weekday', 'value': '5', 'polarity': 'avoid',
             'weight': 2.0}, people) == 'Jeff: groceries not on Saturdays (learned from 2 steers)', "avoid weekday")
    check(d({'scope': '*', 'kind': 'pharmacy', 'dimension': 'time_band', 'value': 'evening', 'polarity': 'prefer',
             'weight': 1.0}, people) == 'Anyone: pharmacy runs in the evening (learned from 1 steer)', "band")
    check(d({'scope': '*', 'kind': 'return', 'dimension': 'driver', 'value': 'd2', 'polarity': 'prefer',
             'weight': 3.0}, people) == 'Lorena runs returns (learned from 3 steers)', "driver")
    check(d({'scope': 'd1', 'kind': 'other', 'dimension': 'weekday', 'value': '0', 'polarity': 'prefer',
             'weight': 1.0}, people) == 'Jeff: errands on Mondays (learned from 1 steer)', "other = errands")
    check(d({'scope': 'dX', 'kind': 'service', 'dimension': 'time_band', 'value': 'midday', 'polarity': 'avoid',
             'weight': 1.4}, people) == 'Someone: appointments not at midday (learned from 1 steer)',
          "an unknown driver reads as Someone; weight rounds")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} common-sense scenarios passed")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_errand_common_sense.py`
Expected: `ImportError: cannot import name 'errand_prefs'`.

- [ ] **Step 3: Schema fields**

In `models/schemas.py`, directly above `class Errand(BaseModel):` add:

```python
ERRAND_KINDS = ('groceries', 'pharmacy', 'return', 'pickup', 'service', 'other')
```

Inside `Errand`, after `once_driver_id: Optional[str] = None`:

```python
    # Common sense (errands-common-sense §1, §5): the kind decides the default
    # shapes; both are overrides, None means "work it out".
    kind: Optional[str] = None
    home_bound: Optional[bool] = None

    @field_validator('kind')
    @classmethod
    def _kind_is_known(cls, v):
        if v in (None, ''):
            return None
        v = str(v).strip().lower()
        if v not in ERRAND_KINDS:
            raise ValueError(f"kind must be one of {', '.join(ERRAND_KINDS)}")
        return v
```

Inside `ErrandRule`, after `is_enabled: bool = True`:

```python
    kind: Optional[str] = None          # copied onto a matching new errand when it has none
    home_bound: Optional[bool] = None

    @field_validator('kind')
    @classmethod
    def _rule_kind_is_known(cls, v):
        if v in (None, ''):
            return None
        v = str(v).strip().lower()
        if v not in ERRAND_KINDS:
            raise ValueError(f"kind must be one of {', '.join(ERRAND_KINDS)}")
        return v
```

Extend `ERRAND_ROUTING_FIELDS`:

```python
ERRAND_ROUTING_FIELDS = ('location', 'duration_mins', 'tolerance_mins', 'buffer_mins',
                         'time_window_start', 'time_window_end', 'valid_days_of_week',
                         'window_days', 'starts_on', 'recurrence_rule', 'required_drivers',
                         'allowed_drivers', 'prohibited_drivers', 'required_passengers',
                         'prohibited_passengers', 'group_id', 'priority',
                         'kind', 'home_bound') + STEER_FIELDS
```

- [ ] **Step 4: The module**

Create `services/errand_prefs.py`:

```python
"""Errands with common sense: the kind table, what a steer teaches, how a
learned preference is weighted, scored and said.

Spec: docs/superpowers/specs/2026-10-22-errands-common-sense-design.md.
Everything here is a constant or a pure function except `learn_from_steer`,
which writes through storage.upsert_errand_preference. The solver pass reads
this module; nothing here reads the solver.
"""
import math
import re
import time as _time
import uuid
from datetime import time
from typing import Optional

from models.schemas import ERRAND_KINDS

KIND_KEYWORDS = {
    'groceries': ['grocery', 'groceries', 'market', 'supermarket', 'food', 'costco', "sam's", 'sams club',
                  'kroger', 'aldi', 'publix', 'meijer', 'wegmans', 'trader joe', 'whole foods', 'walmart',
                  'target run', 'h-e-b', 'heb', 'safeway', 'giant', 'harris teeter', 'fresh market'],
    'pharmacy': ['pharmacy', 'prescription', 'rx', 'walgreens', 'cvs', 'rite aid', 'meds'],
    'return': ['return', 'drop off', 'drop-off', 'dropoff', 'mail', 'ship', 'ups', 'fedex', 'post office', 'usps'],
    'pickup': ['pick up', 'pickup', 'pick-up', 'collect', 'fetch'],
    'service': ['haircut', 'barber', 'salon', 'nails', 'oil change', 'car wash', 'tires', 'vet', 'dentist',
                'doctor', 'appointment'],
}
KIND_ORDER = ('groceries', 'pharmacy', 'return', 'pickup', 'service')
HOME_BOUND_KINDS = frozenset({'groceries', 'pharmacy'})

STEER_BANDS = {
    'morning': ('08:00', '12:00'), 'midday': ('11:00', '14:00'),
    'afternoon': ('14:00', '17:00'), 'evening': ('17:00', '20:00'),
}
DEDICATED_START_WEEKDAY = time(9, 0)
DEDICATED_START_WEEKEND = time(10, 0)
DEDICATED_END = time(17, 0)
ESTIMATE_SURCHARGE_MINS = 10

PREF_STEP_MINS = 5
PREF_CAP_MINS = 30
PREF_MAX_WEIGHT = 6
PREF_HALF_LIFE_DAYS = 90
PREF_PRUNE_BELOW = 0.5

DAY_NAMES = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
KIND_LABELS = {'groceries': 'groceries', 'pharmacy': 'pharmacy runs', 'return': 'returns',
               'pickup': 'pickups', 'service': 'appointments', 'other': 'errands', '*': 'errands'}
BAND_PHRASES = {'morning': 'in the morning', 'midday': 'at midday',
                'afternoon': 'in the afternoon', 'evening': 'in the evening'}


# ------------------------------------------------------------------ kinds

def _has_phrase(text: str, phrases) -> bool:
    for p in phrases:
        if re.search(r'(?<![a-z0-9])' + re.escape(p) + r'(?![a-z0-9])', text):
            return True
    return False


def errand_kind(errand: dict, lists: Optional[list] = None) -> str:
    """§1: override, then a bound shopping list, then tags, then the title."""
    k = (errand.get('kind') or '').strip().lower()
    if k in ERRAND_KINDS:
        return k
    if lists is None:
        try:
            from services import storage
            lists = storage.find_shopping_lists_for_errand(errand)
        except Exception:
            lists = []
    if lists:
        return 'groceries'
    tags = ' '.join(str(t) for t in (errand.get('tags') or [])).lower()
    title = (errand.get('title') or '').lower()
    for kind in KIND_ORDER:
        if tags and _has_phrase(tags, KIND_KEYWORDS[kind]):
            return kind
    for kind in KIND_ORDER:
        if title and _has_phrase(title, KIND_KEYWORDS[kind]):
            return kind
    return 'other'


def is_home_bound(errand: dict, kind: Optional[str] = None) -> bool:
    hb = errand.get('home_bound')
    if hb is not None:
        return bool(hb)
    return (kind or errand_kind(errand)) in HOME_BOUND_KINDS


# ------------------------------------------------------------------ bands

def _mins(hhmm: str) -> int:
    h, m = map(int, str(hhmm).split(':')[:2])
    return h * 60 + m


def band_for(start: Optional[str], end: Optional[str]) -> Optional[str]:
    """§4.2: the band equal to the pin, else the first band holding its midpoint."""
    if not start and not end:
        return None
    for name, (b0, b1) in STEER_BANDS.items():
        if start == b0 and end == b1:
            return name
    if start and end:
        mid = (_mins(start) + _mins(end)) // 2
    else:
        mid = _mins(start or end)
    for name, (b0, b1) in STEER_BANDS.items():
        if _mins(b0) <= mid < _mins(b1):
            return name
    return 'morning' if mid < _mins(STEER_BANDS['morning'][0]) else 'evening'


def band_holds(name: str, t: time) -> bool:
    b0, b1 = STEER_BANDS[name]
    m = t.hour * 60 + t.minute
    return _mins(b0) <= m < _mins(b1)


# ------------------------------------------------------------------ weights

def effective_weight(row: dict, now: Optional[float] = None) -> float:
    now = _time.time() if now is None else now
    age_days = max(0.0, (now - float(row.get('last_seen') or now)) / 86400.0)
    return float(row.get('weight') or 0.0) * (0.5 ** (age_days / PREF_HALF_LIFE_DAYS))


def _row_matches(row: dict, driver_id, kind, day_date, start_dt) -> bool:
    if row.get('scope') not in ('*', str(driver_id)):
        return False
    if row.get('kind') not in ('*', kind):
        return False
    dim, val = row.get('dimension'), str(row.get('value'))
    if dim == 'weekday':
        return val == str(day_date.weekday())
    if dim == 'time_band':
        return val in STEER_BANDS and band_holds(val, start_dt.timetz())
    if dim == 'driver':
        return val == str(driver_id)
    return False


def preference_cost(rows, driver_id, kind, day_date, start_dt, now=None):
    """§4.3: Σ ±5×weight over matching rows, clamped to [-30, +30]."""
    total, hit = 0.0, []
    for row in rows or []:
        if not _row_matches(row, driver_id, kind, day_date, start_dt):
            continue
        w = effective_weight(row, now)
        total += (-1 if row.get('polarity') == 'prefer' else 1) * PREF_STEP_MINS * w
        hit.append(row.get('id'))
    total = max(-PREF_CAP_MINS, min(PREF_CAP_MINS, total))
    return int(round(total)), hit


# ------------------------------------------------------------------ teaching

def _iso_weekday(date_str: str) -> Optional[str]:
    try:
        from datetime import date
        return str(date.fromisoformat(str(date_str)).weekday())
    except Exception:
        return None


def learn_from_steer(before: dict, after: dict, placement: Optional[dict] = None, now=None) -> list:
    """§4.2: the rows one steer teaches, written through storage. Returns them."""
    from services import storage
    now = _time.time() if now is None else now
    kind = errand_kind(after)
    scope = ((placement or {}).get('driver') or {}).get('id') or after.get('once_driver_id') or '*'
    scope = str(scope)
    rows = []

    def row(sc, dim, val, pol):
        if val is None:
            return
        rows.append({'scope': sc, 'kind': kind, 'dimension': dim, 'value': str(val),
                     'polarity': pol, 'source': 'steer'})

    gained = [d for d in (after.get('skip_dates') or []) if d not in (before.get('skip_dates') or [])]
    for d in gained:
        row(scope, 'weekday', _iso_weekday(d), 'avoid')
    if after.get('pinned_date') and after.get('pinned_date') != before.get('pinned_date'):
        row(scope, 'weekday', _iso_weekday(after['pinned_date']), 'prefer')
    if (after.get('pinned_start') or after.get('pinned_end')) and (
            after.get('pinned_start') != before.get('pinned_start')
            or after.get('pinned_end') != before.get('pinned_end')):
        row(scope, 'time_band', band_for(after.get('pinned_start'), after.get('pinned_end')), 'prefer')
    if after.get('once_driver_id') and after.get('once_driver_id') != before.get('once_driver_id'):
        row('*', 'driver', after['once_driver_id'], 'prefer')
    return [storage.upsert_errand_preference(r, now=now) for r in rows]


# ------------------------------------------------------------------ words

def describe(row: dict, people: dict) -> str:
    scope = row.get('scope')
    who = 'Anyone' if scope == '*' else (people.get(scope) or 'Someone')
    label = KIND_LABELS.get(row.get('kind') or '*', 'errands')
    n = max(1, int(round(float(row.get('weight') or 1))))
    tail = f" (learned from {n} steer{'s' if n != 1 else ''})"
    dim, val, avoid = row.get('dimension'), str(row.get('value')), row.get('polarity') == 'avoid'
    if dim == 'weekday':
        day = DAY_NAMES[int(val)] if val.isdigit() and int(val) < 7 else val
        return f"{who}: {label} {'not ' if avoid else ''}on {day}s{tail}"
    if dim == 'time_band':
        return f"{who}: {label} {'not ' if avoid else ''}{BAND_PHRASES.get(val, val)}{tail}"
    if dim == 'driver':
        name = people.get(val) or 'Someone'
        return f"{name} {'does not run' if avoid else 'runs'} {label}{tail}"
    return f"{who}: {label}{tail}"
```

- [ ] **Step 5: Storage**

In `services/storage.py`, after `get_errand_placement_notes` (`:8559`):

```python
# --- Learned errand preferences (errands-common-sense §4.1) -------------------
# A handful of rows: what the household's steers have taught the errand pass.
# Soft weights, decayed on read by errand_prefs.effective_weight, pruned on write.

def get_errand_preferences() -> List[dict]:
    return [dict(r) for r in (get_app_state('errand_preferences', []) or [])]


def _pref_key(r: dict):
    return (str(r.get('scope')), str(r.get('kind')), str(r.get('dimension')),
            str(r.get('value')), str(r.get('polarity')))


def upsert_errand_preference(row: dict, now: float = None) -> dict:
    """Same scope+kind+dimension+value+polarity → weight +1 (capped), fresh
    last_seen; otherwise a new row at weight 1. Prunes rows whose effective
    weight has decayed under the floor. Returns the stored row."""
    import time as _t
    from services import errand_prefs
    now = _t.time() if now is None else now
    with db_lock:
        rows = [dict(r) for r in (get_app_state('errand_preferences', []) or [])]
        hit = None
        for r in rows:
            if _pref_key(r) == _pref_key(row):
                hit = r
                break
        if hit is None:
            hit = {'id': uuid.uuid4().hex, 'scope': str(row.get('scope')), 'kind': str(row.get('kind')),
                   'dimension': str(row.get('dimension')), 'value': str(row.get('value')),
                   'polarity': str(row.get('polarity')), 'weight': 1.0, 'last_seen': now,
                   'source': row.get('source') or 'steer'}
            rows.append(hit)
        else:
            hit['weight'] = float(min(errand_prefs.PREF_MAX_WEIGHT, float(hit.get('weight') or 0) + 1))
            hit['last_seen'] = now
        rows = [r for r in rows if r is hit or errand_prefs.effective_weight(r, now) >= errand_prefs.PREF_PRUNE_BELOW]
        set_app_state('errand_preferences', rows)
        return dict(hit)


def delete_errand_preference(pref_id: str) -> bool:
    with db_lock:
        rows = [dict(r) for r in (get_app_state('errand_preferences', []) or [])]
        keep = [r for r in rows if r.get('id') != pref_id]
        if len(keep) == len(rows):
            return False
        set_app_state('errand_preferences', keep)
        return True


def clear_errand_preferences() -> int:
    with db_lock:
        n = len(get_app_state('errand_preferences', []) or [])
        set_app_state('errand_preferences', [])
        return n
```

Check that `uuid` is imported at the top of `services/storage.py` (`grep -n "^import uuid" services/storage.py`); add it if not.

- [ ] **Step 6: Run the tests**

Run: `python tests/test_errand_common_sense.py`
Expected: all scenarios pass (the solver scenarios arrive in Tasks 2–5).

- [ ] **Step 7: Hand back**

Leave the diff in the working tree with a note: files touched, the test command and its last line.

---

### Task 2: Home-bound shapes and dedicated-trip hours in the pass

**Files:**
- Modify: `solver/matcher.py:2706-2905` (`insert_errands_globally`)
- Test: `tests/test_errand_common_sense.py` (add the §2 scenarios)

**Interfaces:**
- Consumes: `errand_prefs.errand_kind`, `errand_prefs.is_home_bound`, `errand_prefs.DEDICATED_START_WEEKDAY/WEEKEND`, `errand_prefs.DEDICATED_END`.
- Produces: every `scheduled_errands` row carries `"kind": <kind>`; a home-bound errand only ever has `why.kind in ('on_the_way' with leg.to == 'Home', 'from_home', 'pinned', 'unknown_travel')`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_errand_common_sense.py`, above `SCENARIOS = ...`:

```python
# ---------------------------------------------------------------- §2 defaults

def scenario_groceries_ride_home_not_to_the_appointment():
    # Jeff: Dentist (30,0) 10:00-11:00, Work (0,30) 14:00-17:00, both own events.
    # Store (10,10): on the way TO the dentist detour 20 (Home->Store 20,
    # Store->Dentist 30, Home->Dentist 30); BETWEEN dentist and work detour 0
    # (Dentist->Store 30, Store->Work 30, Dentist->Work 60); on the way HOME
    # from work detour 20 (Work->Store 30, Store->Home 20, Work->Home 30).
    # Pure cost takes the free gap at 11:00, two hours before anyone is home.
    # Groceries must take the leg home.
    jeff = _driver('d1', 'Jeff')
    dentist = _ev('dentist', 1, 10, 'Dentist', 'Dentist')
    work = _ev('work', 1, 14, 'Work', 'Work', dur=180)
    base = _world({}, [jeff], {})
    rows, notes = _place(base, [_errand(title='Costco run')], [jeff], driver_events={'d1': [dentist, work]})
    d, r = _only(rows)
    check(d == DAYS[1] and r['why']['leg'] == {'from': 'Work', 'to': 'Home'},
          f"groceries ride the leg home: {d} {r['why']}")
    check(r['why']['text'] == "on Jeff's way home from Work, +20 min", f"{r['why']['text']!r}")
    check(r['kind'] == 'groceries', f"the row says its kind: {r.get('kind')}")
    # The same geometry with home_bound=False takes the morning leg.
    rows, _ = _place(base, [_errand(title='Costco run', home_bound=False)], [jeff], driver_events={'d1': [dentist, work]})
    d, r = _only(rows)
    check(r['why']['leg'] == {'from': 'Dentist', 'to': 'Work'} and r['why']['detour_mins'] == 0,
          f"home_bound=False rides any leg, here the free gap: {r['why']}")
    # A return with the same geometry takes the free gap too.
    rows, _ = _place(base, [_errand(title='Return the lamp')], [jeff], driver_events={'d1': [dentist, work]})
    d, r = _only(rows)
    check(r['why']['leg'] == {'from': 'Dentist', 'to': 'Work'} and r['kind'] == 'return',
          f"a return rides any leg: {r['why']} {r.get('kind')}")


def scenario_groceries_never_sit_inside_a_drop_off_and_run_ride():
    # Saturday: Jeff drops Kate at Soccer 10:00-12:00 (drop-off-and-run). The
    # Store is 40 off the drop->pickup gap (Soccer->Store 20, Store->Soccer 20,
    # gap 0), 20 off the way to soccer and 20 off the way home after pickup.
    # Groceries: after the pickup, never before it.
    jeff = _driver('d1', 'Jeff')
    soccer = _ev('soccer', 5, 10, 'Soccer', 'Soccer practice', dur=120)
    base = _world({5: [soccer]}, [jeff], {'soccer': 'd1'})
    rows, _ = _place(base, [_errand(title='Costco run')], [jeff])
    d, r = _only(rows)
    check(d == DAYS[5] and r['why']['leg'] == {'from': 'Soccer practice', 'to': 'Home'}, f"after pickup: {r['why']}")
    check(datetime.datetime.fromisoformat(r['start_time']) >= soccer.end, "never before the pickup")
    rows, _ = _place(base, [_errand(title='Return the lamp')], [jeff])
    d, r = _only(rows)
    check(r['why']['leg'] == {'from': 'Home', 'to': 'Soccer practice'}, f"a return rides the first leg: {r['why']}")


def scenario_a_dedicated_trip_keeps_human_hours():
    jeff = _driver('d1', 'Jeff')
    base = _world({}, [jeff], {})
    # Window = Saturday only (one-off starting Saturday, one day).
    sat_ts = datetime.datetime.combine(MON + datetime.timedelta(days=5), datetime.time(0, 0)).astimezone().timestamp()
    rows, _ = _place(base, [_errand(title='Costco run', starts_on=sat_ts, window_days=1)], [jeff])
    d, r = _only(rows)
    check(d == DAYS[5] and _start(r) == datetime.time(10, 0), f"Saturday from home starts at 10:00, got {_start(r)}")
    tue_ts = datetime.datetime.combine(MON + datetime.timedelta(days=1), datetime.time(0, 0)).astimezone().timestamp()
    rows, _ = _place(base, [_errand(title='Costco run', starts_on=tue_ts, window_days=1)], [jeff])
    d, r = _only(rows)
    check(d == DAYS[1] and _start(r) == datetime.time(9, 0), f"a weekday from home starts at 09:00, got {_start(r)}")
    rows, _ = _place(base, [_errand(title='Costco run', starts_on=sat_ts, window_days=1,
                                    time_window_start='08:00', time_window_end='09:00')], [jeff])
    d, r = _only(rows)
    check(_start(r) == datetime.time(8, 0), f"the person's own window wins over the band: {_start(r)}")
    rows, _ = _place(base, [_errand(title='Costco run', pinned_date=DAYS[5], pinned_start='17:00', pinned_end='20:00')], [jeff])
    d, r = _only(rows)
    check(d == DAYS[5] and _start(r) == datetime.time(17, 0), f"an Evening pin places at 17:00: {d} {_start(r)}")
    # A 9-hour trip has no 09:00-17:00 fit: the ladder keeps the 09:00 start and
    # lets it run to the day's end rather than reporting no_slot or going to 08:00.
    rows, notes = _place(base, [_errand(title='Costco run', starts_on=tue_ts, window_days=1, duration_mins=540)], [jeff])
    d, r = _only(rows)
    check(_start(r) == datetime.time(9, 0) and notes == {}, f"a trip longer than the band still lands: {_start(r)} {notes}")


def scenario_a_day_someone_already_leaves_beats_a_blank_day_for_groceries():
    # Monday blank (round trip from home: Store 20 each way = 40 + 25 penalty = 65).
    # Tuesday Jeff works (Work 0,30; Work->Store 30, Store->Home 20, Work->Home 30: detour 20).
    jeff = _driver('d1', 'Jeff')
    work = _ev('work', 1, 9, 'Work', 'Work', dur=480)
    base = _world({}, [jeff], {})
    rows, _ = _place(base, [_errand(title='Costco run')], [jeff], driver_events={'d1': [work]})
    d, r = _only(rows)
    check(d == DAYS[1] and r['why']['leg'] == {'from': 'Work', 'to': 'Home'}, f"Tuesday on the way home: {d} {r['why']}")
```

- [ ] **Step 2: Run to verify they fail**

Run: `python tests/test_errand_common_sense.py`
Expected: `scenario_groceries_ride_home_not_to_the_appointment` fails (the morning leg wins today), the Saturday trip starts at 08:00.

- [ ] **Step 3: Implement**

In `solver/matcher.py`, inside `insert_errands_globally`:

(a) After `duration = ...` and before `w_start, w_end, skip, reason = errand_window(...)`:

```python
            from services import errand_prefs as _prefs
            kind = _prefs.errand_kind(errand)
            home_bound = _prefs.is_home_bound(errand, kind)
            has_window = bool(errand.get('time_window_start') or errand.get('time_window_end')
                              or errand.get('pinned_start') or errand.get('pinned_end'))
```

(b) The empty-day shape (`if not stops:` block) becomes:

```python
                    if not stops:
                        if req_pax:
                            continue
                        t = leg(home, loc) if home else None
                        start = None
                        if not has_window:
                            # §2: a dedicated trip keeps human hours when the person set
                            # nothing: the band first, then from the band's start to the
                            # day's end for a trip too long for the band.
                            ded_start = datetime.combine(
                                day_date, _prefs.DEDICATED_START_WEEKEND if day_date.weekday() >= 5
                                else _prefs.DEDICATED_START_WEEKDAY).astimezone()
                            ded_end = datetime.combine(day_date, _prefs.DEDICATED_END).astimezone()
                            start = _first_fit(ded_start, ded_end - timedelta(minutes=duration), duration, day_date, errand, now)
                            if start is None:
                                start = _first_fit(ded_start, day_end - timedelta(minutes=duration), duration, day_date, errand, now)
                        if start is None:
                            start = _first_fit(day_start, day_end - timedelta(minutes=duration), duration, day_date, errand, now)
                        if start is not None:
                            add('empty', start, [t], (t or 0) * 2, None, None, -1, t, t)
                        continue
```

(c) Gate the two non-home shapes. Two one-line edits in the existing shape code, the bodies of the three shapes stay exactly as they are:

```python
                    first, last = stops[0], stops[-1]
                    if not req_pax and not home_bound:          # was: if not req_pax:
                        th = leg(home, loc) if home else None
                        # ... the from_home_leg body, untouched
                    for i in range(len(stops) - 1):
                        if home_bound:                           # new: a home-bound errand has no between shape
                            break
                        a, b = stops[i], stops[i + 1]
                        # ... the between body, untouched
                    if not req_pax:                              # unchanged: the to_home_leg stays for every kind
                        tl = leg(last.location, loc)
                        # ... the to_home_leg body, untouched
```

(d) In the `scheduled[d_str].append({...})` dict add `"kind": kind,` after `"priority"`.

- [ ] **Step 4: Run the tests**

Run: `python tests/test_errand_common_sense.py && python tests/test_errand_routing.py`
Expected: `test_errand_common_sense.py` green. `tests/test_errand_routing.py` will go red in many places because its fixture's default title is `'Costco run'`, which is now groceries and home-bound. That file pins the route arc's any-leg semantics, so make ONE fixture change there: add `'home_bound': False, 'kind': None` to the base dict in its `_errand(**over)` helper (the common-sense file owns kind behaviour). Then re-run it. If a scenario there asserts an empty-day start of 08:00 for an errand with no window, update that assertion to the §2 hour (09:00 weekday, 10:00 weekend) and list each such change in the hand-back note; change nothing else in that file.

- [ ] **Step 5: Hand back** with the note.

---

### Task 3: Estimated legs, the surcharge, the route primer, the ranking key

**Files:**
- Modify: `solver/matcher.py:2447` (after `errand_leg_minutes`), `:2487` (after `_prime_errand_pairs`), `:2512` (`errand_why_text`), `insert_errands_globally`
- Test: `tests/test_errand_common_sense.py` (§3 scenarios)

**Interfaces:**
- Produces: `matcher.errand_leg_estimate(a, b) -> Optional[int]`; `matcher._prime_route_pairs(routes, driver_map, home_location, storage, maps, chunk=24) -> int`; `why.estimated: bool` (present and true only when a leg was estimated); `why.text` variants "about +N min (estimated)" and "a trip from home, about N min each way (estimated)"; the ranking key `(unestimable, cost, date, start, driver_id)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_errand_common_sense.py`:

```python
# ---------------------------------------------------------------- §3 estimates

def scenario_a_passing_leg_with_an_estimated_pair_beats_a_known_round_trip():
    # Tuesday Jeff drives to the Gym (24,0): an own event whose pairs are NOT
    # cached (ESTIMATE_ONLY) but estimable. Plaza (12,0) is on that line:
    # estimated detour (12+2) + (12+2) - (24+2) = 2, surcharge 10 → 12.
    # Monday blank: Home->Plaza unknown too (estimate 14 each way = 28 + 25 + 10 = 63).
    jeff = _driver('d1', 'Jeff')
    gym = _ev('gym', 1, 18, 'Gym', 'Gym')
    base = _world({}, [jeff], {})
    rows, notes = _place(base, [_errand(title='Return the lamp', location='Plaza')], [jeff], driver_events={'d1': [gym]})
    d, r = _only(rows)
    check(d == DAYS[1] and r['why']['kind'] == 'on_the_way' and r['why']['leg'] == {'from': 'Home', 'to': 'Gym'},
          f"on the way to the gym, estimated: {d} {r['why']}")
    check(r['why'].get('estimated') is True and r['why']['detour_mins'] == 2, f"{r['why']}")
    check(r['why']['text'] == "on Jeff's way to Gym, about +2 min (estimated)", f"{r['why']['text']!r}")
    check(r['travel_to_mins'] is None and r['travel_from_mins'] is None, "estimates are never stated as travel minutes")
    check(notes == {}, f"{notes}")


def scenario_a_known_leg_keeps_its_minutes_beside_an_estimated_one():
    # Store (10,10) is cached from Home (20) but not from the Gym: t1 known, t2 estimated.
    jeff = _driver('d1', 'Jeff')
    gym = _ev('gym', 1, 18, 'Gym', 'Gym')
    base = _world({}, [jeff], {})
    rows, _ = _place(base, [_errand(title='Return the lamp', location='Store')], [jeff], driver_events={'d1': [gym]})
    d, r = _only(rows)
    check(r['why'].get('estimated') is True, f"{r['why']}")
    check(r['travel_to_mins'] == 20 and r['travel_from_mins'] is None, f"known stays, estimated is None: {r}")


def scenario_a_leg_with_no_coordinates_still_ranks_last():
    jeff = _driver('d1', 'Jeff')
    nowhere = _ev('x', 1, 18, 'Nowhere', 'Nowhere')
    base = _world({}, [jeff], {})
    # Monday blank: Home->Shop known (8 each way = 16 + 25 = 41). Tuesday's leg to
    # Nowhere cannot be estimated: it loses even though its unknown detour costs 0.
    rows, _ = _place(base, [_errand(title='Return the lamp', location='Shop')], [jeff], driver_events={'d1': [nowhere]})
    d, r = _only(rows)
    check(d == DAYS[0] and r['why']['kind'] == 'from_home', f"the known trip wins over the unestimable leg: {d} {r['why']}")
    rows, _ = _place(base, [_errand(title='Return the lamp', location='Shop', starts_on=_at(1, 0)[0].timestamp(), window_days=1)],
                     [jeff], driver_events={'d1': [nowhere]})
    d, r = _only(rows)
    check(r['why']['kind'] == 'unknown_travel' and r['travel_to_mins'] is None,
          f"alone on Tuesday (a day with a stop, so no round trip) the unestimable leg is placed as unknown, as today: {r['why']}")


def scenario_a_round_trip_from_home_can_be_estimated_too():
    jeff = _driver('d1', 'Jeff')
    base = _world({}, [jeff], {})
    rows, _ = _place(base, [_errand(title='Return the lamp', location='Plaza', starts_on=_at(0, 0)[0].timestamp(), window_days=1)], [jeff])
    d, r = _only(rows)
    check(r['why']['kind'] == 'from_home' and r['why'].get('estimated') is True
          and r['why']['text'] == 'a trip from home, about 14 min each way (estimated)', f"{r['why']}")
    check(r['travel_to_mins'] is None, "never stated")


def scenario_an_estimate_for_the_same_spot_is_two_minutes():
    # The real estimator on cached coordinates (this file stubs the module's
    # errand_leg_estimate, so the real one is reached under its own name).
    with storage.db_lock:
        storage.geocode_cache_table.truncate()
        storage.geocode_cache_table.insert({'address': 'shop a', 'lat': 40.0, 'lon': -83.0})
        storage.geocode_cache_table.insert({'address': 'shop b', 'lat': 40.0, 'lon': -83.0})
        storage.geocode_cache_table.insert({'address': 'far shop', 'lat': 40.09, 'lon': -83.0})  # ~10 km north
    orig_cache_only = maps.travel_cache_only_active
    maps.travel_cache_only_active = lambda: True      # cached coordinates only, no geocoding
    try:
        est = matcher._errand_leg_estimate_impl
        check(est('Shop A', 'Shop B') == 2, f"same spot: {est('Shop A', 'Shop B')}")
        v = est('Shop A', 'Far Shop')
        check(v == 17, f"10 km × 1.5 + 2 = 17, got {v}")
        check(est('Shop A', 'Unknown Place') is None, "no coordinates: None")
    finally:
        maps.travel_cache_only_active = orig_cache_only


def scenario_the_route_primer_buys_adjacent_pairs_once_and_bounded():
    calls = []
    orig = maps.prime_matrix_cache
    orig_cache_only = maps.travel_cache_only_active
    maps.prime_matrix_cache = lambda locations, ignore_age=False: calls.append(list(locations))
    try:
        jeff = _driver('d1', 'Jeff')
        gym = _ev('gym', 1, 18, 'Gym', 'Gym')
        base = _world({}, [jeff], {})
        _place(base, [_errand(title='Return the lamp', location='Plaza'), _errand(id='er2', title='Haircut', location='Plaza')],
               [jeff], driver_events={'d1': [gym]})
        route_calls = [c for c in calls if 'Plaza' not in c]
        check(len(route_calls) == 1 and route_calls[0] == ['Home', 'Gym'],
              f"one primer for the one day whose adjacent pair is unknown, once for both errands: {route_calls}")
        calls.clear()
        maps.travel_cache_only_active = lambda: True
        _place(base, [_errand(title='Return the lamp', location='Plaza')], [jeff], driver_events={'d1': [gym]})
        check(calls == [], f"nothing under cache-only: {calls}")
    finally:
        maps.prime_matrix_cache = orig
        maps.travel_cache_only_active = orig_cache_only
```

Note for the implementer: the test reaches the real estimator as `matcher._errand_leg_estimate_impl` because `matcher.errand_leg_estimate` is stubbed module-wide by this file. Define the real function once and alias it:

```python
def _errand_leg_estimate_impl(a, b): ...
errand_leg_estimate = _errand_leg_estimate_impl
```

- [ ] **Step 2: Run to verify they fail**

Run: `python tests/test_errand_common_sense.py`
Expected: `AttributeError: module 'solver.matcher' has no attribute '_errand_leg_estimate_impl'` and the estimate scenarios place from home.

- [ ] **Step 3: Implement the estimator and the primer**

In `solver/matcher.py` after `errand_leg_minutes`:

```python
def _errand_leg_estimate_impl(a, b):
    """§3: minutes from coordinates when the pair is not cached. Cached
    geocodes only under cache-only mode, else one geocode. `round(km × 1.5) + 2`;
    None when either place has no coordinates. Never a fallback constant."""
    if not a or not b:
        return None
    a_s, b_s = str(a).strip(), str(b).strip()
    if a_s.lower() == b_s.lower():
        return 2
    import math
    from services import storage, maps

    def coords(p):
        rec = storage.get_cached_geocode(p)
        if rec:
            try:
                return float(rec['lat']), float(rec['lon'])
            except (KeyError, TypeError, ValueError):
                pass
        if maps.travel_cache_only_active():
            return None
        try:
            return maps.geocode_address(p)
        except Exception:
            return None

    ca, cb = coords(a_s), coords(b_s)
    if not ca or not cb:
        return None
    (lat1, lon1), (lat2, lon2) = ca, cb
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    h = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    km = 2 * r * math.atan2(math.sqrt(h), math.sqrt(1 - h))
    return int(round(km * 1.5)) + 2


errand_leg_estimate = _errand_leg_estimate_impl
```

After `_prime_errand_pairs`:

```python
def _prime_route_pairs(routes, driver_map, home_location, storage, maps, chunk=24):
    """§3: once per refresh, buy the adjacent pairs of every driver's day route
    (home → first, stop → next, last → home) that the cache does not know.
    Each day's list goes in chunks of at most `chunk` locations overlapping by
    one so no adjacent pair straddles a boundary. Nothing under cache-only."""
    try:
        import inspect as _inspect
        me = _inspect.getmodule(_prime_route_pairs)
        if maps.travel_cache_only_active():
            return 0
        calls = 0
        step = max(1, chunk - 1)
        for d_str, by_driver in routes.items():
            for d_id, stops in by_driver.items():
                home = getattr(driver_map.get(d_id), 'home_location', None) or home_location
                seq = ([home] if home else []) + [s.location for s in stops if s.location] + ([home] if home else [])
                seq = [p for i, p in enumerate(seq) if i == 0 or p != seq[i - 1]]
                if len(seq) < 2:
                    continue
                if all(me.errand_leg_minutes(seq[i], seq[i + 1]) is not None for i in range(len(seq) - 1)):
                    continue
                distinct = list(dict.fromkeys(seq))
                for i in range(0, max(1, len(distinct) - 1), step):
                    maps.prime_matrix_cache(distinct[i:i + chunk], ignore_age=True)
                    calls += 1
        return calls
    except Exception as ex:
        print(f"[errands] route primer failed: {ex}")
        return 0
```

- [ ] **Step 4: Wire estimation into the pass**

Inside `insert_errands_globally`:

(a) Right after `leg = lambda a, b: ...` add:

```python
    estimate = lambda a, b: me.errand_leg_estimate(a, b)   # noqa: E731

    def leg2(a, b):
        """(minutes, estimated) — cached minutes first, else an estimate, else (None, False)."""
        v = leg(a, b)
        if v is not None:
            return v, False
        e = estimate(a, b)
        return (e, True) if e is not None else (None, False)
```

(b) After the `routes = {...}` comprehension and the `places` loop, before `for errand in active:`:

```python
    _prime_route_pairs(routes, driver_map, home_location, storage, _maps)
```

(c) Replace every `leg(...)` call inside the shape blocks with `leg2(...)`, keeping both halves. Concretely:

```python
                    if not stops:
                        if req_pax:
                            continue
                        t, t_est = leg2(home, loc) if home else (None, False)
                        ...
                            add('empty', start, [(t, t_est)], (t or 0) * 2, None, None, -1, (t, t_est), (t, t_est))
                        continue

                    first, last = stops[0], stops[-1]
                    if not req_pax and not home_bound:
                        th, th_e = leg2(home, loc) if home else (None, False)
                        tf, tf_e = leg2(loc, first.location)
                        thf, thf_e = leg2(home, first.location) if home else (None, False)
                        legs = [(th, th_e), (tf, tf_e), (thf, thf_e)]
                        latest = first.start - timedelta(minutes=(tf or 0) + duration)
                        start = _first_fit(day_start, latest, duration, day_date, errand, now, latest=True)
                        if start is not None:
                            add('from_home_leg', start, legs, (th or 0) + (tf or 0) - (thf or 0), None, first, -1, (th, th_e), (tf, tf_e))
                    for i in range(len(stops) - 1):
                        if home_bound:
                            break
                        a, b = stops[i], stops[i + 1]
                        t1, t1_e = leg2(a.location, loc)
                        t2, t2_e = leg2(loc, b.location)
                        tab, tab_e = leg2(a.location, b.location)
                        legs = [(t1, t1_e), (t2, t2_e), (tab, tab_e)]
                        ...
                        add('between', start, legs, (t1 or 0) + (t2 or 0) - (tab or 0), a, b, i, (t1, t1_e), (t2, t2_e))
                    if not req_pax:
                        tl, tl_e = leg2(last.location, loc)
                        th, th_e = leg2(loc, home) if home else (None, False)
                        tlh, tlh_e = leg2(last.location, home) if home else (None, False)
                        legs = [(tl, tl_e), (th, th_e), (tlh, tlh_e)]
                        ...
                            add('to_home_leg', start, legs, (tl or 0) + (th or 0) - (tlh or 0), last, None, len(stops) - 1, (tl, tl_e), (th, th_e))
```

(d) `add` becomes:

```python
                    def add(shape, start, legs, detour, prev_stop, next_stop, insert_idx, t1, t2):
                        unknown = any(v is None for v, _ in legs)
                        estimated = (not unknown) and any(flag for _, flag in legs)
                        cost = ((0 if unknown else detour)
                                + (penalty if shape == 'empty' else 0)
                                + (_prefs.ESTIMATE_SURCHARGE_MINS if estimated else 0)
                                - group_bonus)
                        end = start + timedelta(minutes=duration)
                        if not allowed_for_slot(d_id, start, end):
                            return
                        if shape == 'from_home_leg' or shape == 'empty':
                            leg_d = {'from': 'Home', 'to': next_stop.title} if next_stop else None
                        elif shape == 'to_home_leg':
                            leg_d = {'from': prev_stop.title, 'to': 'Home'}
                        else:
                            leg_d = {'from': prev_stop.title, 'to': next_stop.title}
                        inside_ride = shape == 'between' and _same_ride(prev_stop, next_stop)
                        kind_w = 'unknown_travel' if unknown else ('from_home' if shape == 'empty' else 'inside_stop' if inside_ride else 'on_the_way')
                        if errand.get('pinned_date') and not unknown:
                            kind_w = 'pinned'
                        why = {'kind': kind_w, 'detour_mins': None if unknown else int(detour), 'driver_name': dname,
                               **({'leg': leg_d} if leg_d and shape != 'empty' else {})}
                        if estimated:
                            why['estimated'] = True
                        why['text'] = errand_why_text(why)
                        t1v, t1e = t1 if isinstance(t1, tuple) else (t1, False)
                        t2v, t2e = t2 if isinstance(t2, tuple) else (t2, False)
                        candidates.append(((1 if unknown else 0, cost, d_str, start.isoformat(), str(d_id)),
                                           dict(d_str=d_str, d_id=d_id, start=start, end=end, why=why,
                                                prev=prev_stop, next=next_stop, insert_idx=insert_idx,
                                                t1=None if (unknown or t1e) else t1v,
                                                t2=None if (unknown or t2e) else t2v,
                                                unknown=unknown)))
```

(e) `errand_why_text` learns the estimated phrasing:

```python
def errand_why_text(why):
    kind = (why or {}).get('kind')
    who = (why or {}).get('driver_name') or 'someone'
    det = int((why or {}).get('detour_mins') or 0)
    leg = (why or {}).get('leg') or {}
    est = bool((why or {}).get('estimated'))
    plus = f"about +{det} min (estimated)" if est else f"+{det} min"
    learned = ', as you steered it before' if (why or {}).get('learned') else ''
    if kind == 'unknown_travel':
        return 'drive time unknown, check the address'
    if kind == 'from_home':
        each = f"about {det // 2} min each way (estimated)" if est else f"{det // 2} min each way"
        return f"a trip from home, {each}{learned}"
    if kind == 'inside_stop':
        return f"during {leg.get('from') or 'the stop'}, {plus}{learned}"
    if kind == 'pinned':
        inner = dict(why)
        inner['kind'] = 'from_home' if not leg else ('inside_stop' if leg.get('from') == leg.get('to') else 'on_the_way')
        inner.pop('learned', None)
        return 'the day you picked, ' + errand_why_text(inner) + learned
    if leg.get('to') == 'Home':
        return f"on {who}'s way home from {leg.get('from')}, {plus}{learned}"
    return f"on {who}'s way to {leg.get('to')}, {plus}{learned}"
```

(`learned` is set in Task 5; the text already knows how to say it.)

- [ ] **Step 5: Run the tests**

Run: `python tests/test_errand_common_sense.py && python tests/test_errand_routing.py`
Expected: green. `test_errand_routing.py` scenario 4 ("unknown ranks last") must still pass: its off-grid place has no coordinates in the test DB, so it is unestimable.

- [ ] **Step 6: Hand back** with the note.

---

### Task 4: Teaching from both writers

**Files:**
- Modify: `main.py:18383-18406` (`PUT /api/errands/{doc_id}`)
- Modify: `services/agent_tools_v2.py:7816-7885` (`handle_update_errand`)
- Test: `tests/test_errand_common_sense.py` (§4.2 teaching), `tests/test_errand_prefs_api.py` (new; the writers)

**Interfaces:**
- Consumes: `errand_prefs.learn_from_steer(before, after, placement, now)`, `storage.get_all_scheduled_errand_rows()`, `STEER_FIELDS`.
- Produces: a steer through either writer leaves the §4.2 rows in `storage.get_errand_preferences()`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_errand_common_sense.py`:

```python
# ---------------------------------------------------------------- §4.2 teaching

def _placement(day_str, driver_id='d1', name='Jeff'):
    return {'id': 'er1', 'driver': {'id': driver_id, 'name': name}, 'start': f'{day_str}T16:10:00',
            'start_time': f'{day_str}T16:10:00', 'why': {'kind': 'on_the_way'}}


def scenario_each_steer_verb_teaches_its_row():
    _fresh()
    before = _errand(title='Costco run')
    sat = DAYS[5]
    learn = errand_prefs.learn_from_steer
    rows = learn(before, _errand(title='Costco run', skip_dates=[sat]), _placement(sat), now=NOW.timestamp())
    check(len(rows) == 1 and (rows[0]['scope'], rows[0]['kind'], rows[0]['dimension'], rows[0]['value'], rows[0]['polarity'])
          == ('d1', 'groceries', 'weekday', '5', 'avoid'), f"Not this day: {rows}")
    rows = learn(before, _errand(title='Costco run', pinned_date=DAYS[3]), _placement(sat), now=NOW.timestamp())
    check(len(rows) == 1 and (rows[0]['dimension'], rows[0]['value'], rows[0]['polarity']) == ('weekday', '3', 'prefer'), f"Pick a day: {rows}")
    rows = learn(before, _errand(title='Costco run', pinned_date=sat, pinned_start='17:00', pinned_end='20:00'),
                 _placement(sat), now=NOW.timestamp())
    dims = sorted((r['dimension'], r['value'], r['polarity']) for r in rows)
    check(dims == [('time_band', 'evening', 'prefer'), ('weekday', '5', 'prefer')], f"Pick a time pins the day too: {dims}")
    rows = learn(before, _errand(title='Costco run', once_driver_id='d2'), _placement(sat), now=NOW.timestamp())
    check(len(rows) == 1 and (rows[0]['scope'], rows[0]['dimension'], rows[0]['value'], rows[0]['polarity'])
          == ('*', 'driver', 'd2', 'prefer'), f"Someone else: {rows}")
    steered = _errand(title='Costco run', skip_dates=[sat], pinned_date=DAYS[3], once_driver_id='d2')
    rows = learn(steered, _errand(title='Costco run'), _placement(sat), now=NOW.timestamp())
    check(rows == [], f"Back to automatic teaches nothing: {rows}")
    rows = learn(before, _errand(title='Costco run', location='Shop'), _placement(sat), now=NOW.timestamp())
    check(rows == [], f"an edit teaches nothing: {rows}")
    # A repeat of the same steer grows the same row.
    learn(before, _errand(title='Costco run', skip_dates=[sat]), _placement(sat), now=NOW.timestamp())
    stored = [r for r in storage.get_errand_preferences() if r['dimension'] == 'weekday' and r['polarity'] == 'avoid']
    check(len(stored) == 1 and stored[0]['weight'] == 2.0, f"same row, weight 2: {stored}")


def scenario_a_steer_without_a_placement_is_scoped_to_everyone():
    _fresh()
    rows = errand_prefs.learn_from_steer(_errand(title='Costco run'), _errand(title='Costco run', skip_dates=[DAYS[2]]),
                                         None, now=NOW.timestamp())
    check(len(rows) == 1 and rows[0]['scope'] == '*' and rows[0]['value'] == '2', f"{rows}")
    rows = errand_prefs.learn_from_steer(_errand(title='Costco run'),
                                         _errand(title='Costco run', skip_dates=[DAYS[2]], once_driver_id='d2'),
                                         None, now=NOW.timestamp())
    scopes = sorted((r['scope'], r['dimension']) for r in rows)
    check(scopes == [('*', 'driver'), ('d2', 'weekday')], f"the once-driver scopes the day when there is no placement: {scopes}")
```

Create `tests/test_errand_prefs_api.py`:

```python
"""Errands with common sense — the writers, the routes, the agent, the editor fields.

Spec: docs/superpowers/specs/2026-10-22-errands-common-sense-design.md
§4.2 (both writers teach), §5 (routes, fields, agent tools).

Run from chauffeur/:  python tests/test_errand_prefs_api.py
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("CHAUFFEUR_DATA_DIR", tempfile.mkdtemp(prefix="chauffeur_errand_prefs_api_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import check  # noqa: E402
from services import storage  # noqa: E402


def _fresh():
    with storage.db_lock:
        storage.errands_table.truncate()
        storage.daily_schedules_table.truncate()
        storage.app_state_table.truncate()
        storage.drivers_table.truncate()
        storage.drivers_table.insert({'id': 'd1', 'name': 'Jeff', 'home_location': 'Home', 'color_code': '#000'})
        storage.drivers_table.insert({'id': 'd2', 'name': 'Lorena', 'home_location': 'Home', 'color_code': '#000'})


def _errand(**over):
    base = {'id': over.pop('id', 'e-' + str(time.time_ns())), 'title': 'Costco run',
            'duration_mins': 30, 'location': 'Costco', 'priority': 2,
            'is_completed': False, 'status': 'pending', 'created_at': time.time(),
            'starts_on': None, 'recurrence_rule': None, 'tags': [],
            'skip_dates': [], 'pinned_date': None, 'pinned_start': None,
            'pinned_end': None, 'once_driver_id': None, 'kind': None, 'home_bound': None}
    base.update(over)
    return base


def _row(errand_id, date_str, driver_id='d1'):
    return {'id': errand_id, 'driver': {'id': driver_id, 'name': 'Jeff'},
            'start': f'{date_str}T16:10:00', 'start_time': f'{date_str}T16:10:00',
            'end': f'{date_str}T16:40:00', 'end_time': f'{date_str}T16:40:00',
            'title': 'Costco run', 'location': 'Costco', 'kind': 'groceries',
            'why': {'kind': 'on_the_way', 'detour_mins': 6, 'driver_name': 'Jeff',
                    'leg': {'from': 'Work', 'to': 'Home'}, 'text': "on Jeff's way home from Work, +6 min"}}


def _cache_row(date_str, row):
    with storage.db_lock:
        storage.daily_schedules_table.insert({'date': date_str, 'schedule': {'scheduled_errands': [row]}})


def _client():
    from fastapi.testclient import TestClient
    import main
    main.trigger_background_refresh = lambda *a, **k: None
    return TestClient(main.app), main


def scenario_the_put_teaches_before_it_forgets():
    _fresh()
    client, main = _client()
    doc_id = storage.add_errand(_errand(id='e-put'))
    _cache_row('2026-10-31', _row('e-put', '2026-10-31'))       # a Saturday
    body = dict(storage.get_errand_by_id(doc_id))
    body.pop('doc_id', None)
    body['skip_dates'] = ['2026-10-31']
    r = client.put(f'/api/errands/{doc_id}', json=body)
    check(r.status_code == 200, f"{r.status_code} {r.text}")
    prefs = storage.get_errand_preferences()
    check(len(prefs) == 1 and (prefs[0]['scope'], prefs[0]['kind'], prefs[0]['dimension'], prefs[0]['value'], prefs[0]['polarity'])
          == ('d1', 'groceries', 'weekday', '5', 'avoid'), f"the steer taught Jeff's groceries not on Saturdays: {prefs}")
    check(storage.get_all_scheduled_errand_rows().get('e-put') is None, "and the placement was forgotten after")


def scenario_the_agent_teaches_the_same_row():
    _fresh()
    from services import agent_tools_v2 as tools
    storage.add_errand(_errand(id='e-agent'))
    _cache_row('2026-10-31', _row('e-agent', '2026-10-31'))
    out = tools.handle_update_errand({'errand_id': 'e-agent', 'skip_date': '2026-10-31'})
    check(out['status'] == 'success', f"{out}")
    prefs = storage.get_errand_preferences()
    check(len(prefs) == 1 and (prefs[0]['scope'], prefs[0]['dimension'], prefs[0]['value'], prefs[0]['polarity'])
          == ('d1', 'weekday', '5', 'avoid'), f"{prefs}")
    out = tools.handle_update_errand({'errand_id': 'e-agent', 'once_driver_id': 'd2'})
    prefs = storage.get_errand_preferences()
    check(any(p['dimension'] == 'driver' and p['value'] == 'd2' and p['scope'] == '*' for p in prefs), f"{prefs}")
    out = tools.handle_update_errand({'errand_id': 'e-agent', 'duration_mins': 45})
    check(len(storage.get_errand_preferences()) == 2, "an edit teaches nothing")
    out = tools.handle_update_errand({'errand_id': 'e-agent', 'is_completed': True})
    check(len(storage.get_errand_preferences()) == 2, "completion teaches nothing")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} errand-prefs API scenarios passed")
```

- [ ] **Step 2: Run to verify they fail**

Run: `python tests/test_errand_common_sense.py; python tests/test_errand_prefs_api.py`
Expected: the teaching scenarios in the first file PASS already (Task 1 built `learn_from_steer`); the second file fails on `len(prefs) == 1` (nothing wrote).

- [ ] **Step 3: The PUT**

In `main.py` `update_errand` (`:18383`), replace the block from `try: before = ...` to the `forget` call with:

```python
    try:
        before = Errand(**{k: v for k, v in old.items() if k != 'doc_id'}).model_dump()
    except Exception:
        before = old
    today = datetime.now().date().isoformat()
    before['skip_dates'] = [d for d in (before.get('skip_dates') or []) if d >= today]
    if not incoming.get('is_completed') and any(before.get(f) != incoming.get(f) for f in STEER_FIELDS):
        # A steer teaches (errands-common-sense §4.2), read off the placement
        # that is about to be forgotten.
        try:
            from services import errand_prefs
            errand_prefs.learn_from_steer(before, incoming, storage.get_all_scheduled_errand_rows().get(old.get('id')))
        except Exception as ex:
            print(f"[errands] learn_from_steer failed: {ex}")
    if any(before.get(f) != incoming.get(f) for f in ERRAND_ROUTING_FIELDS):
        storage.forget_errand_placements(old.get('id'))
```

Import `STEER_FIELDS` where `ERRAND_ROUTING_FIELDS` is imported in `main.py` (`grep -n "ERRAND_ROUTING_FIELDS" main.py` for the import line).

- [ ] **Step 4: The agent**

In `handle_update_errand`, replace the tail from `storage.update_errand(doc_id, clean)` with:

```python
    if any(before.get(f) != clean.get(f) for f in STEER_FIELDS):
        try:
            from services import errand_prefs
            errand_prefs.learn_from_steer(before, clean, storage.get_all_scheduled_errand_rows().get(errand['id']))
        except Exception as ex:
            print(f"[errands] learn_from_steer failed: {ex}")
    storage.update_errand(doc_id, clean)
    if any(before.get(f) != clean.get(f) for f in ERRAND_ROUTING_FIELDS):
        storage.forget_errand_placements(errand['id'])
    return {"status": "success", "message": "Errand updated."}
```

and change the function's import line to `from models.schemas import Errand, ERRAND_ROUTING_FIELDS, STEER_FIELDS`.

- [ ] **Step 5: Run**

Run: `python tests/test_errand_prefs_api.py && python tests/test_errand_routing_api.py`
Expected: green.

- [ ] **Step 6: Hand back** with the note.

---

### Task 5: Scoring in the pass

**Files:**
- Modify: `solver/matcher.py` (`insert_errands_globally`: read rows once, cost per candidate, `why.learned`)
- Test: `tests/test_errand_common_sense.py` (§4.3 scoring in the pass)

**Interfaces:**
- Consumes: `storage.get_errand_preferences()`, `errand_prefs.preference_cost(...)`.
- Produces: `why.learned: [ids]` only when a preference moved the winner's cost; `why.text` ends with ", as you steered it before" then.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_errand_common_sense.py`:

```python
# ---------------------------------------------------------------- §4.3 scoring in the pass

def scenario_a_learned_avoid_moves_the_next_cycle_softly():
    # Groceries at the Shop (-4,-4). Thursday Jeff works (Work 0,30): the leg
    # home costs Work->Shop 38 + Shop->Home 8 - Work->Home 30 = 16. Saturday
    # Jeff is at Piano (-30,0): Piano->Shop 30 + 8 - 30 = 8. Saturday is 8 better.
    # Jeff's "groceries not on Saturdays" at weight 2 adds 10: Thursday now wins.
    _fresh()
    jeff = _driver('d1', 'Jeff')
    work = _ev('work', 3, 9, 'Work', 'Work', dur=480)
    piano = _ev('piano', 5, 10, 'Piano', 'Piano')
    base = _world({}, [jeff], {})
    rows, _ = _place(base, [_errand(title='Costco run', location='Shop')], [jeff], driver_events={'d1': [work, piano]})
    d, r = _only(rows)
    check(d == DAYS[5] and r['why']['detour_mins'] == 8 and 'learned' not in r['why'],
          f"nothing learned yet: Saturday is cheaper: {d} {r['why']}")
    for _ in range(2):
        storage.upsert_errand_preference({'scope': 'd1', 'kind': 'groceries', 'dimension': 'weekday', 'value': '5',
                                          'polarity': 'avoid', 'source': 'steer'}, now=NOW.timestamp())
    rows, _ = _place(base, [_errand(title='Costco run', location='Shop')], [jeff], driver_events={'d1': [work, piano]})
    d, r = _only(rows)
    check(d == DAYS[3], f"weight 2 (+10) moves it to Thursday: {d} {r['why']}")
    check('learned' not in r['why'], "Thursday matched no row, so its why says nothing about learning")
    # Soft: Saturday at the Lab (-4,-20) is on the way home for free (Lab->Shop 16 + 8 - 24 = 0),
    # 16 better than Thursday. The +10 avoid cannot flip that.
    lab = _ev('lab', 5, 10, 'Lab', 'Lab')
    rows, _ = _place(base, [_errand(title='Costco run', location='Shop')], [jeff], driver_events={'d1': [work, lab]})
    d, r = _only(rows)
    check(d == DAYS[5] and r['why']['detour_mins'] == 0, f"an avoid never beats a 16-minute-better leg: {d} {r['why']}")


def scenario_a_learned_preference_is_said_out_loud():
    _fresh()
    jeff = _driver('d1', 'Jeff')
    work = _ev('work', 3, 9, 'Work', 'Work', dur=480)
    piano = _ev('piano', 5, 10, 'Piano', 'Piano')
    base = _world({}, [jeff], {})
    p = storage.upsert_errand_preference({'scope': 'd1', 'kind': 'groceries', 'dimension': 'weekday', 'value': '5',
                                          'polarity': 'prefer', 'source': 'steer'}, now=NOW.timestamp())
    rows, _ = _place(base, [_errand(title='Costco run', location='Shop')], [jeff], driver_events={'d1': [work, piano]})
    d, r = _only(rows)
    check(d == DAYS[5] and r['why'].get('learned') == [p['id']], f"the preferred Saturday wins and names the row: {r['why']}")
    check(r['why']['text'] == "on Jeff's way home from Piano, +8 min, as you steered it before", f"{r['why']['text']!r}")


def scenario_a_decayed_preference_barely_moves_anything():
    _fresh()
    jeff = _driver('d1', 'Jeff')
    work = _ev('work', 3, 9, 'Work', 'Work', dur=480)
    piano = _ev('piano', 5, 10, 'Piano', 'Piano')
    base = _world({}, [jeff], {})
    old = NOW.timestamp() - 270 * 86400          # three half-lives: weight 2 → 0.25 → cost +1
    storage.set_app_state('errand_preferences', [{'id': 'p', 'scope': 'd1', 'kind': 'groceries', 'dimension': 'weekday',
                                                  'value': '5', 'polarity': 'avoid', 'weight': 2.0, 'last_seen': old,
                                                  'source': 'steer'}])
    rows, _ = _place(base, [_errand(title='Costco run', location='Shop')], [jeff], driver_events={'d1': [work, piano]})
    d, r = _only(rows)
    check(d == DAYS[5], f"a stale avoid (+1) does not flip an 8-minute gap: {d}")
```

- [ ] **Step 2: Run to verify they fail**

Run: `python tests/test_errand_common_sense.py`
Expected: `scenario_a_learned_avoid_moves_the_next_cycle_softly` fails at "weight 2 moves it to Thursday".

- [ ] **Step 3: Implement**

In `insert_errands_globally`:

(a) After `all_rules = storage.get_all_rules()`:

```python
    pref_rows = storage.get_errand_preferences()
```

(b) In `add`, after `cost = (...)` compute and fold the preference cost, and record the ids:

```python
                        pref_cost, learned = _prefs.preference_cost(pref_rows, d_id, kind, day_date, start, now.timestamp())
                        cost += pref_cost
                        ...
                        if learned and pref_cost != 0:
                            why['learned'] = list(learned)
                        why['text'] = errand_why_text(why)
```

(`kind` here is the errand's kind from Task 2; the why's own kind is `kind_w`.)

- [ ] **Step 4: Run**

Run: `python tests/test_errand_common_sense.py && python tests/test_errand_routing.py`
Expected: green.

- [ ] **Step 5: Hand back** with the note.

---

### Task 6: Routes, auth, the editor fields, the rule copy, the Learned block

**Files:**
- Modify: `main.py:18262-18300` (`GET /api/errands` adds `kind_inferred`; three routes declared right after it and BEFORE `@app.post("/api/errands")`), `:18360-18380` (rule copy in `create_errand`)
- Modify: `services/auth.py:382`
- Modify: `templates/errands.html` (edit modal `:307-323` region; load `:839`; save `:889`; drawer include `:151`)
- Create: `templates/components/errand_learned.html`
- Modify: `templates/components/errand_lists.html:299`, `templates/app.html:3615` (strip `kind_inferred`)
- Test: `tests/test_errand_prefs_api.py` (routes, fields), `tests/test_errand_lists_render.py` (the block)

**Interfaces:**
- Produces: `GET /api/errands/preferences -> {"rows": [{...row, "text": str}]}`; `DELETE /api/errands/preferences/{pref_id} -> {"status": "deleted"}` or 404; `DELETE /api/errands/preferences -> {"status": "cleared", "removed": n}`; `GET /api/errands` rows carry `kind_inferred`; the Alpine component `errandLearnedPanel()` with `rows`, `loaded`, `forbidden`, `load()`, `remove(id)`, `clearAll()`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_errand_prefs_api.py`:

```python
def scenario_the_preference_routes_list_delete_and_clear_as_a_parent():
    _fresh()
    client, main = _client()
    a = storage.upsert_errand_preference({'scope': 'd1', 'kind': 'groceries', 'dimension': 'weekday', 'value': '5',
                                          'polarity': 'avoid', 'source': 'steer'}, now=time.time())
    b = storage.upsert_errand_preference({'scope': '*', 'kind': 'return', 'dimension': 'driver', 'value': 'd2',
                                          'polarity': 'prefer', 'source': 'steer'}, now=time.time())
    r = client.get('/api/errands/preferences')
    check(r.status_code == 200, f"{r.status_code} {r.text}")
    rows = r.json()['rows']
    texts = sorted(x['text'] for x in rows)
    check(texts == ['Jeff: groceries not on Saturdays (learned from 1 steer)', 'Lorena runs returns (learned from 1 steer)'], f"{texts}")
    r = client.delete(f'/api/errands/preferences/{a["id"]}')
    check(r.status_code == 200 and len(storage.get_errand_preferences()) == 1, f"{r.status_code} {r.text}")
    r = client.delete('/api/errands/preferences/nope')
    check(r.status_code == 404, f"{r.status_code}")
    r = client.delete('/api/errands/preferences')
    check(r.status_code == 200 and r.json()['removed'] == 1 and storage.get_errand_preferences() == [], f"{r.text}")
    from services import auth
    check(auth.resolve('GET', '/api/errands/preferences') == auth.PARENTS, "listing is parents only")
    check(auth.resolve('DELETE', '/api/errands/preferences/{pref_id}') == auth.PARENTS, "deleting is parents only")
    check(auth.resolve('GET', '/api/errands') != auth.PARENTS, "the errands list itself stays as it was")


def scenario_kind_and_home_bound_round_trip_and_forget_placements():
    _fresh()
    client, main = _client()
    doc_id = storage.add_errand(_errand(id='e-kind', title='Costco run'))
    _cache_row('2026-10-29', _row('e-kind', '2026-10-29'))
    r = client.get('/api/errands')
    me = next(x for x in r.json() if x['id'] == 'e-kind')
    check(me['kind'] is None and me['kind_inferred'] == 'groceries' and me['home_bound'] is None, f"{me}")
    body = {k: v for k, v in me.items() if k not in ('placement', 'unplaced', 'generation', 'shopping_lists', 'kind_inferred', 'scheduled_start')}
    body['home_bound'] = False
    r = client.put(f'/api/errands/{doc_id}', json=body)
    check(r.status_code == 200, f"{r.status_code} {r.text}")
    check(storage.get_errand_by_id(doc_id)['home_bound'] is False, "saved")
    check(storage.get_all_scheduled_errand_rows().get('e-kind') is None, "a routing field changed: placement forgotten")
    check(storage.get_errand_preferences() == [], "a flag edit teaches nothing")
    body['kind'] = 'snacks'
    r = client.put(f'/api/errands/{doc_id}', json=body)
    check(r.status_code == 422, f"an unknown kind is refused: {r.status_code}")


def scenario_a_rule_copies_kind_and_home_bound_onto_a_new_errand():
    _fresh()
    client, main = _client()
    storage.add_errand_rule({'title': 'Grocery runs', 'constraint_type': 'driver_assignment', 'keywords': ['costco'],
                             'kind': 'groceries', 'home_bound': False, 'is_enabled': True})
    r = client.post('/api/errands', json=_errand(id='e-rule', title='Costco run'))
    check(r.status_code == 200, f"{r.status_code} {r.text}")
    saved = storage.get_errand_by_id('e-rule')
    check(saved['kind'] == 'groceries' and saved['home_bound'] is False, f"{saved}")
    r = client.post('/api/errands', json=_errand(id='e-rule2', title='Costco run', home_bound=True))
    saved = storage.get_errand_by_id('e-rule2')
    check(saved['home_bound'] is True, "the errand's own value beats the rule")
```

Append to `tests/test_errand_lists_render.py` (before `SCENARIOS = ...`):

```python
def scenario_the_learned_block_is_on_the_page_and_not_on_a_card():
    page = _render_errands()
    check('errandLearnedPanel()' in page and 'id="errand-learned"' in page, "the Learned block is in the Errands drawer")
    check('Nothing learned yet' in page, "the empty state is there")
    import main
    req = types.SimpleNamespace(url=types.SimpleNamespace(path='/errands'), query_params={'panel': 'true'})
    panel = main.templates.env.get_template('errands.html').render(request=req)
    check('errandLearnedPanel()' not in panel, "a panel never draws it (the drawer draws nothing on a panel)")


def scenario_the_learned_block_lists_and_deletes_through_the_routes():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from test_moment_media_token import _function_text, _run_node
    comp = open(os.path.join(TPL, 'components', 'errand_learned.html'), encoding='utf-8').read()
    logic = _function_text(comp, 'function errandLearnedPanel()')
    got = _run_node(r"""var window = globalThis; window.chfBase = '';
var showGlobalAlert = () => {}; var promptConfirm = async () => true;
window.chfSettingsSaving = () => {}; window.chfSettingsSaved = () => true;
window.addEventListener = () => {};
""" + logic + r"""
(async () => {
  const P = errandLearnedPanel();
  const calls = [];
  const ROWS = [{id: 'a', text: 'Jeff: groceries not on Saturdays (learned from 2 steers)'}, {id: 'b', text: 'Lorena runs returns (learned from 1 steer)'}];
  globalThis.fetch = async (url, init) => {
    calls.push({url, method: (init && init.method) || 'GET'});
    if (init && init.method === 'DELETE') { if (url.endsWith('/a')) ROWS.splice(0, 1); else if (url.endsWith('preferences')) ROWS.splice(0); return {ok: true, status: 200, json: async () => ({status: 'ok'})}; }
    return {ok: true, status: 200, json: async () => ({rows: ROWS.slice()})};
  };
  await P.load();
  const n0 = P.rows.length;
  await P.remove('a');
  const n1 = P.rows.length;
  await P.clearAll();
  console.log(JSON.stringify({n0, n1, n2: P.rows.length, calls}));
})();
""")
    if got is None:
        return
    check(got['n0'] == 2 and got['n1'] == 1 and got['n2'] == 0, f"{got}")
    urls = [c['url'] for c in got['calls'] if c['method'] == 'DELETE']
    check(urls == ['api/errands/preferences/a', 'api/errands/preferences'], f"{urls}")
```

- [ ] **Step 2: Run to verify they fail**

Run: `python tests/test_errand_prefs_api.py; python tests/test_errand_lists_render.py`
Expected: 404 on `GET /api/errands/preferences`; the render test cannot find the component.

- [ ] **Step 3: Routes and auth**

In `main.py`, inside `get_errands` after `obj['generation'] = generation` add:

```python
        obj['kind_inferred'] = errand_prefs.errand_kind(obj)
```

with `from services import errand_prefs` among the top-level service imports of `main.py`. Directly after the `get_errands` function and BEFORE `@app.post("/api/errands")`:

```python
# Learned errand preferences (errands-common-sense §5). Declared above the
# {doc_id} routes so "preferences" is never parsed as a doc id.
@app.get("/api/errands/preferences")
def get_errand_preferences():
    people = {d.get('id'): d.get('name') for d in storage.get_all_drivers()}
    return {"rows": [dict(r, text=errand_prefs.describe(r, people)) for r in storage.get_errand_preferences()]}


@app.delete("/api/errands/preferences")
def clear_errand_preferences(background_tasks: BackgroundTasks):
    n = storage.clear_errand_preferences()
    background_tasks.add_task(trigger_background_refresh)
    return {"status": "cleared", "removed": n}


@app.delete("/api/errands/preferences/{pref_id}")
def delete_errand_preference(pref_id: str, background_tasks: BackgroundTasks):
    if not storage.delete_errand_preference(pref_id):
        raise HTTPException(status_code=404, detail="Preference not found")
    background_tasks.add_task(trigger_background_refresh)
    return {"status": "deleted"}
```

In `create_errand`'s rule loop, inside `if match:` BEFORE the `if ctype == 'driver_assignment':` chain:

```python
            if r.get('kind') and not errand_dict.get('kind'): errand_dict['kind'] = r['kind']
            if r.get('home_bound') is not None and errand_dict.get('home_bound') is None: errand_dict['home_bound'] = r['home_bound']
```

In `services/auth.py` insert ABOVE `(ANY, '/api/errands/*', SIGNED_IN, 'lists.errands')`:

```python
    # Learned errand preferences: what the household's steers taught the
    # pass. A parent's list, like the errand rules beside it.
    (ANY, '/api/errands/preferences/*', PARENTS, None),
```

- [ ] **Step 4: The editor**

In `templates/errands.html` edit modal, after the `edit-once-driver` block (`:319-324`), add inside the same grid:

```html
                                  <div>
                                      <label for="edit-kind" class="block text-xs font-medium text-gray-400 mb-1">Kind</label>
                                      <select id="edit-kind" class="w-full bg-gray-900 border border-gray-700 text-white rounded-lg px-3 py-2 text-sm focus:ring-1 focus:ring-blue-500 outline-none">
                                          <option value="">Automatic</option>
                                          <option value="groceries">Groceries</option>
                                          <option value="pharmacy">Pharmacy</option>
                                          <option value="return">Return / drop-off</option>
                                          <option value="pickup">Pickup</option>
                                          <option value="service">Appointment / service</option>
                                          <option value="other">Other</option>
                                      </select>
                                      <p id="edit-kind-guess" class="text-xs text-gray-500 mt-1"></p>
                                  </div>
                                  <div>
                                      <label for="edit-home-bound" class="block text-xs font-medium text-gray-400 mb-1">On the way home</label>
                                      <select id="edit-home-bound" class="w-full bg-gray-900 border border-gray-700 text-white rounded-lg px-3 py-2 text-sm focus:ring-1 focus:ring-blue-500 outline-none">
                                          <option value="">Automatic (groceries and pharmacy)</option>
                                          <option value="true">Yes, last stop before home</option>
                                          <option value="false">No, any leg</option>
                                      </select>
                                  </div>
```

In the load code after `document.getElementById('edit-pinned-end').value = ...` (`:841`):

```javascript
            document.getElementById('edit-kind').value = currentEditErrand.kind || '';
            document.getElementById('edit-kind-guess').textContent = currentEditErrand.kind
                ? '' : 'Guessed: ' + (currentEditErrand.kind_inferred || 'other');
            const hb = currentEditErrand.home_bound;
            document.getElementById('edit-home-bound').value = hb === true ? 'true' : hb === false ? 'false' : '';
```

In the save code after `errand.pinned_end = ...` (`:891`):

```javascript
            errand.kind = document.getElementById('edit-kind').value || null;
            const hbv = document.getElementById('edit-home-bound').value;
            errand.home_bound = hbv === '' ? null : hbv === 'true';
```

In `templates/components/errand_lists.html:299` and `templates/app.html:3615`, the strip line becomes:

```javascript
delete body.placement; delete body.unplaced; delete body.generation; delete body.shopping_lists; delete body.kind_inferred; delete body.scheduled_start;
```

- [ ] **Step 5: The Learned block**

Create `templates/components/errand_learned.html`:

```html
{# Learned errand preferences (errands-common-sense §5): what the household's
   steers have taught the errand pass, in plain words, each deletable. Lives in
   the Errands drawer under the rules, parent-only like them; loads when the
   drawer opens. The drawer macro draws nothing on a panel or kiosk, so a wall
   never shows it. #}
<div x-data="errandLearnedPanel()" x-init="init()" id="errand-learned" class="scroll-mt-28">
    <div class="p-4 md:p-6">
        <h2 class="text-2xl font-bold text-indigo-300 mb-2">Learned</h2>
        <p class="text-sm text-gray-500 mb-4">Every time someone steers an errand, the planner remembers a little. These
            nudge where errands land; none of them is a rule. Delete one to forget it.</p>
        <p x-show="forbidden" class="text-sm text-gray-500 italic">Learned preferences are a parent's list.</p>
        <template x-if="!forbidden">
            <div>
                <p x-show="loaded && rows.length === 0" class="text-sm text-gray-500 italic">Nothing learned yet. Steering an errand teaches this list.</p>
                <ul class="space-y-2">
                    <template x-for="row in rows" :key="row.id">
                        <li class="flex items-center justify-between gap-3 bg-gray-700/30 border border-gray-600 rounded-lg px-4 py-2">
                            <span class="text-sm text-gray-200" x-text="row.text"></span>
                            <button type="button" @click="remove(row.id)" :disabled="!!busy[row.id]"
                                class="text-xs font-semibold text-red-300 hover:text-red-200 disabled:opacity-50">Delete</button>
                        </li>
                    </template>
                </ul>
                <div class="mt-4" x-show="rows.length > 0">
                    <button type="button" @click="clearAll()"
                        class="text-xs font-semibold text-gray-400 hover:text-white border border-gray-600 rounded-lg px-3 py-1.5">Clear all</button>
                </div>
            </div>
        </template>
    </div>
</div>
<script>
    function errandLearnedPanel() {
        return {
            // Included, so it reads the shared base rather than working out its own depth (test_template_js).
            apiBase: (window.chfBase !== undefined ? window.chfBase : ''),
            rows: [],
            busy: {},
            loaded: false,
            forbidden: false,
            init() {
                window.addEventListener('chf-settings-opened', e => {
                    const t = e.detail && e.detail.tab;
                    if (t === 'errands' && !this.loaded) this.load();
                });
            },
            async load() {
                try {
                    const res = await fetch(`${this.apiBase}api/errands/preferences`);
                    if (res.status === 401 || res.status === 403) { this.forbidden = true; return; }
                    if (!res.ok) throw new Error('HTTP ' + res.status);
                    const data = await res.json();
                    this.rows = Array.isArray(data.rows) ? data.rows : [];
                    this.loaded = true;
                } catch (e) {
                    console.error('Failed to load learned preferences', e);
                }
            },
            async _send(url) {
                window.chfSettingsSaving();
                try {
                    const r = await fetch(url, { method: 'DELETE' });
                    if (!r.ok) {
                        if (!window.chfSettingsSaved(false, 'Could not forget that just now.')) showGlobalAlert('Could not forget that just now.');
                        return false;
                    }
                    window.chfSettingsSaved(true);
                    return true;
                } catch (e) {
                    if (!window.chfSettingsSaved(false, 'Could not forget that just now.')) showGlobalAlert('Could not forget that just now.');
                    return false;
                }
            },
            async remove(id) {
                this.busy = Object.assign({}, this.busy, { [id]: true });
                try {
                    if (await this._send(`${this.apiBase}api/errands/preferences/${encodeURIComponent(id)}`)) await this.load();
                } finally {
                    const b = Object.assign({}, this.busy); delete b[id]; this.busy = b;
                }
            },
            async clearAll() {
                if (!(await promptConfirm('Forget everything learned about errands?', 'The planner starts fresh. Steering teaches it again.'))) return;
                if (await this._send(`${this.apiBase}api/errands/preferences`)) await this.load();
            },
        };
    }
</script>
```

In `templates/errands.html` after `{% include 'components/errand_rules.html' %}` (`:151`):

```jinja
        {% include 'components/errand_learned.html' %}
```

Check `promptConfirm`'s signature in `templates/components/control_center.html` (`grep -n "function promptConfirm" templates/components/control_center.html`) and match its arguments.

Run `python tools/build_tailwind.py` from `chauffeur/`.

- [ ] **Step 6: Run**

Run: `python tests/test_errand_prefs_api.py && python tests/test_errand_lists_render.py && python tests/test_auth.py && python tests/test_template_js.py`
Expected: green. `test_auth.py` scenario_a classifies the three new routes through the new row.

- [ ] **Step 7: Hand back** with the note.

---

### Task 7: The agent path

**Files:**
- Modify: `services/agent_tools_v2.py:6481` (`AddErrandTool`), `:6506` (`UpdateErrandTool`), `:6540` (after `GetErrandsTool`), `:7774` (`handle_add_errand`), `:7816` (`handle_update_errand`), `:7888` (after `handle_get_errands`), `:6099` (`ADMIN_TOOLS`), `:6114` (`SCHEDULE_MUTATING_ADMIN_TOOLS`), `:7476` (`TOOL_SCHEMAS`), `:9400` (`TOOL_HANDLERS`)
- Modify: `services/missions.py:71` (`READ_TOOLS`)
- Test: `tests/test_errand_prefs_api.py`

**Interfaces:**
- Produces: `AddErrandTool.kind: str = ""`, `AddErrandTool.home_bound: Optional[bool] = None`; `UpdateErrandTool.kind: Optional[str] = None`, `UpdateErrandTool.home_bound: Optional[bool] = None`; `GetErrandPreferencesTool` (no args) → `{"status": "success", "rows": [{...row, "text"}]}`; `ForgetErrandPreferenceTool.preference_id: str` (`"all"` clears) → `{"status": "success", "message": ...}` or `{"status": "error", ...}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_errand_prefs_api.py`:

```python
def scenario_the_agent_sets_kind_and_home_bound_and_reads_and_forgets_preferences():
    _fresh()
    from services import agent_tools_v2 as tools, missions, maps
    maps.resolve_routable_location = lambda loc: loc      # never geocode in a unit test
    out = tools.handle_add_errand({'title': 'Costco run', 'duration_mins': 30, 'location': 'Costco', 'home_bound': False})
    doc_id = int(out['created'][0]['id'])
    saved = storage.get_errand_by_id(doc_id)
    check(saved['home_bound'] is False and saved.get('kind') is None, f"{saved}")
    out = tools.handle_update_errand({'errand_id': str(doc_id), 'kind': 'service', 'home_bound': True})
    check(out['status'] == 'success', f"{out}")
    saved = storage.get_errand_by_id(doc_id)
    check(saved['kind'] == 'service' and saved['home_bound'] is True, f"{saved}")
    out = tools.handle_update_errand({'errand_id': str(doc_id), 'kind': 'snacks'})
    check(out['status'] == 'error' and 'kind' in out['message'], f"{out}")
    a = storage.upsert_errand_preference({'scope': 'd1', 'kind': 'groceries', 'dimension': 'weekday', 'value': '5',
                                          'polarity': 'avoid', 'source': 'steer'}, now=time.time())
    storage.upsert_errand_preference({'scope': '*', 'kind': 'return', 'dimension': 'driver', 'value': 'd2',
                                      'polarity': 'prefer', 'source': 'steer'}, now=time.time())
    out = tools.handle_get_errand_preferences({})
    check(out['status'] == 'success' and sorted(r['text'] for r in out['rows'])
          == ['Jeff: groceries not on Saturdays (learned from 1 steer)', 'Lorena runs returns (learned from 1 steer)'], f"{out}")
    out = tools.handle_forget_errand_preference({'preference_id': a['id']})
    check(out['status'] == 'success' and len(storage.get_errand_preferences()) == 1, f"{out}")
    out = tools.handle_forget_errand_preference({'preference_id': 'nope'})
    check(out['status'] == 'error', f"{out}")
    out = tools.handle_forget_errand_preference({'preference_id': 'all'})
    check(out['status'] == 'success' and storage.get_errand_preferences() == [], f"{out}")
    for name in ('get_errand_preferences', 'forget_errand_preference'):
        check(name in tools.TOOL_HANDLERS and name in tools.TOOL_SCHEMAS and name in tools.ADMIN_TOOLS, f"{name} registered")
    check('get_errand_preferences' in missions.READ_TOOLS, "a read is a read")
    check('forget_errand_preference' in tools.SCHEDULE_MUTATING_ADMIN_TOOLS, "forgetting re-plans")
    schema = tools.TOOL_SCHEMAS['update_errand']['properties']
    check('kind' in schema and 'home_bound' in schema, "the hand path's fields are the agent's too")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python tests/test_errand_prefs_api.py`
Expected: `AttributeError: ... has no attribute 'handle_get_errand_preferences'`.

- [ ] **Step 3: Implement**

`AddErrandTool` gains, after `group_id`:

```python
    kind: str = Field(default="", description="What sort of errand: groceries, pharmacy, return, pickup, service or other. Leave empty and Chauffeur works it out from the title.")
    home_bound: Optional[bool] = Field(default=None, description="True when it must be the last stop before home (cold groceries). Leave unset to let the kind decide.")
```

`UpdateErrandTool` gains, after `clear_steer`:

```python
    kind: Optional[str] = Field(default=None, description="Optional kind: groceries, pharmacy, return, pickup, service or other.")
    home_bound: Optional[bool] = Field(default=None, description="Optional: True = last stop before home, False = any leg.")
```

After `GetErrandsTool`:

```python
class GetErrandPreferencesTool(BaseModel):
    """
    Lists what the household's steers have taught the errand planner (soft preferences, in plain words).
    """
    pass

class ForgetErrandPreferenceTool(BaseModel):
    """
    Forgets one learned errand preference, or all of them.
    """
    preference_id: str = Field(..., description="The preference id from get_errand_preferences, or 'all'.")
```

`handle_add_errand`: add to the `errand` dict

```python
        'kind': (args.get('kind') or '').strip().lower() or None,
        'home_bound': args.get('home_bound'),
```

`handle_update_errand`: after the steer block and before `if not update_data:`

```python
    if args.get('kind') is not None:
        update_data['kind'] = (args.get('kind') or '').strip().lower() or None
    if args.get('home_bound') is not None:
        update_data['home_bound'] = bool(args.get('home_bound'))
```

(the `Errand(**merged)` validation already turns a bad kind into the "That is not a valid value: kind: ..." error).

After `handle_get_errands`:

```python
def handle_get_errand_preferences(args: dict) -> dict:
    from services import storage, errand_prefs
    people = {d.get('id'): d.get('name') for d in storage.get_all_drivers()}
    rows = [dict(r, text=errand_prefs.describe(r, people)) for r in storage.get_errand_preferences()]
    return {"status": "success", "rows": rows}


def handle_forget_errand_preference(args: dict) -> dict:
    from services import storage
    pid = str(args.get('preference_id') or '').strip()
    if pid == 'all':
        n = storage.clear_errand_preferences()
        return {"status": "success", "message": f"Forgot {n} learned preference{'s' if n != 1 else ''}."}
    if not pid or not storage.delete_errand_preference(pid):
        return {"status": "error", "message": "No learned preference with that id."}
    return {"status": "success", "message": "Forgot it."}
```

Registration: add `"get_errand_preferences", "forget_errand_preference",` to `ADMIN_TOOLS` after `"get_errands",`; add `"forget_errand_preference",` to `SCHEDULE_MUTATING_ADMIN_TOOLS`; in `TOOL_SCHEMAS` add `"get_errand_preferences": GetErrandPreferencesTool.model_json_schema(), "forget_errand_preference": ForgetErrandPreferenceTool.model_json_schema(),`; in `TOOL_HANDLERS` add the two handlers. In `services/missions.py` `READ_TOOLS` add `'get_errand_preferences'` next to `'get_errands'`.

- [ ] **Step 4: Run**

Run: `python tests/test_errand_prefs_api.py && python tests/test_registry_parity.py && python tests/test_chat_actions.py`
Expected: green.

- [ ] **Step 5: Hand back** with the note.

---

### Task 8: Gate, document, ship (Claude)

**Files:**
- Modify: `system_capabilities.md` (new entry at the top), `config.yaml` (version), memory arc file.

- [ ] **Step 1: Gate**

From `chauffeur/` with `HA_BASE_URL` unset: `test_errand_common_sense.py`, `test_errand_prefs_api.py`, `test_errand_routing.py`, `test_errand_routing_api.py`, `test_errand_lists_render.py`, `test_pwa_errand_steer.py`, `test_solve_pack.py`, `test_storage.py`, `test_chat_actions.py`, `test_registry_parity.py`, `test_template_js.py`, `test_auth.py`, `test_settings_registry.py`. Pre-existing reds (`test_agent_v2_bridge.py` 3/5, `test_schedule_timeline.py`) are noted in the arc memory; confirm they fail identically on the parent commit before ignoring them.

- [ ] **Step 2: Capabilities entry**

At the top of `system_capabilities.md` (shipped-only, no NEXT): "Errands with common sense" with kinds and the table, the home-bound default, the dedicated-trip hours, estimated legs and the surcharge, the route primer, the preference store (what each steer teaches, ±5×weight, cap 30, 90-day half-life, prune), the Learned block and routes, the editor fields, the agent tools, the device steps (create "Costco run" with no fields and watch it land on a drive home with "on X's way home from Y"; Steer › Not this day on Saturday twice and watch the Learned row appear and the next week avoid Saturday; a dedicated trip on an empty Saturday lands at 10:00; the Learned block's Delete and Clear all; Argyle "what have you learned about errands").

- [ ] **Step 3: Bump, commit, push**

Per task: `(v2.499.680)` onward, `feat(errands): ...` messages, the attribution line.

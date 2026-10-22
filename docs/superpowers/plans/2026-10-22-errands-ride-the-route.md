# Errands Ride the Route Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Errands land on a leg a driver already drives (rides and the driver's own appointments), fall back to a penalised trip from home, say why they landed where they did, and can be steered per errand by hand and by Argyle.

**Architecture:** `solver/matcher.insert_errands_globally` is rewritten around a per-driver per-day route of stops, candidate slots with real time bounds, and a `(unknown, cost, date, start, driver_id)` ranking fed by a pure-cache drive-time reader; it returns placements plus notes for what it could not place. `main.py` passes the drivers' own events in, saves the notes and a refresh generation, and `/api/errands` merges a `placement`/`unplaced` onto every errand. Steering is four new one-shot fields on `Errand`, written through the existing full-record PUT by one shared sheet (Errands page and PWA) and by the repaired agent tool.

**Tech Stack:** Python 3 / FastAPI / pydantic 2 (`field_validator`), TinyDB-shaped storage over SQLite (`services/storage.py`), Jinja + Alpine templates, node for template JS tests, Mapbox Matrix via `services/maps.prime_matrix_cache`.

**Spec:** `docs/superpowers/specs/2026-10-22-errands-ride-the-route-design.md` (rev 2). Read it first; the plan argues from it.

## Global Constraints

- Tests run from `chauffeur/` as plain scripts: `python tests/test_x.py`. Unset `HA_BASE_URL` first (`unset HA_BASE_URL` in bash). Never run the whole suite.
- Every test file isolates storage with `os.environ.setdefault("CHAUFFEUR_DATA_DIR", tempfile.mkdtemp(...))` BEFORE importing `services.storage` (see `tests/harness.py`).
- No browser dialogs: `promptChoice`, `promptInput`, `showGlobalAlert` only (`templates/components/control_center.html`; the PWA has its own twins in `app.html:3551`/`:3581`).
- New settings go in `services/settings_registry.py` and the feature's own page (the Errands settings drawer), never `config.html`. `tests/test_settings_registry.py` must stay green (model coverage AND UI binding audits).
- Tailwind is precompiled: after any template class change run `python tools/build_tailwind.py` from `chauffeur/`.
- Never remove anything a person can do today (tick, Reschedule, Edit, Delete, Complete on the phone, the agent's add/delete/get).
- Every agent capability has a hand path: each steer field `UpdateErrandTool` accepts is reachable from the steer sheet or the admin errand editor.
- Vendored Alpine stamps `:disabled="x[loop.id]"` true on first render: coerce booleans with `!!`.
- `errand_leg_minutes` never returns a fallback number; unknown is `None`. The pass never raises `UncachedTravelPair` and never fetches under `maps.travel_cache_only_active()`.
- Drive-time reads inside the pass go through the module global `errand_leg_minutes` (look it up at call time, never capture it in a default argument or closure) so tests can stub it.
- Do not bump `chauffeur/config.yaml` and do not commit from an implementer task; Claude reviews, documents, bumps and commits each task.
- PowerShell: no double quotes in commit messages; never round-trip source through `Get-Content`/`Set-Content`. Use the Bash tool or Python for file edits.

## Review Focus

Inputs the spec implies but no task's tests exercised at first draft; each now has its test in the owning task:

1. **An errand whose `duration_mins` exceeds every gap on every day** (a 3-hour errand in a packed week): expected `no_slot`, never a placement that overlaps a ride. Task 2 test `scenario_a_long_errand_that_fits_nowhere_is_a_no_slot_note`.
2. **A driver own event with the SAME id as an assigned ride** (parent drives a kid to the dentist they also attend): one stop, never two, and the ride keeps its drop-off-and-run shape. Task 2 test `scenario_a_ride_the_driver_also_attends_is_one_stop`.
3. **`now` in the middle of today's only passing leg** (the pass runs at 15:30, the leg to soccer left at 15:00): the candidate's start is clamped to `now`, and if the clamp pushes it past the slot's latest start the slot is dropped, not placed in the past. Task 2 test `scenario_now_clamps_or_drops_todays_slot`.
4. **A PUT whose only change is `is_completed: true` on an already completed errand** (double tap): no second successor, no error. Task 5 test `scenario_completing_twice_mints_nothing_through_put`.
5. **`skip_date` sent to the agent for a day already in `skip_dates`**: appended once, not twice. Task 6 test `scenario_skip_date_is_idempotent`.

---

## File map

- Modify `models/schemas.py`: `Errand` gains `skip_dates`, `pinned_date`, `pinned_start`, `pinned_end`, `once_driver_id` with validators; `Settings` gains `errand_dedicated_trip_mins`.
- Modify `services/settings_registry.py`: one `_e(...)` entry.
- Modify `services/storage.py`: `get_errand_by_id`, `complete_errand`, `forget_errand_placements`, `save_errand_placement_notes`, `get_errand_placement_notes`, `get_all_scheduled_errand_rows`, `bump_schedule_generation`, `get_schedule_generation`.
- Modify `solver/matcher.py`: `errand_leg_minutes`, `errand_why_text`, `errand_window`, the rewritten `insert_errands_globally` and its helpers.
- Modify `main.py`: the errand pass call (`:21725`), notes + generation after Pass 3, `GET /api/errands` (`:18263`), `PUT /api/errands/{doc_id}` (`:18368`).
- Modify `services/agent_tools_v2.py`: `UpdateErrandTool` (`:6506`), `handle_update_errand` (`:7810`), `handle_get_errands` (`:7851`).
- Modify `templates/components/errand_lists.html`: why line, unplaced line, steered chip, Steer button, `steerErrand` sheet in `errandListsLogic`.
- Modify `templates/errands.html`: the Errands settings drawer section with the new setting; pinned fields on the edit modal.
- Modify `templates/app.html`: both projections carry `why`, the errand modal's why line and Steer button, the "Errands not placed" row.
- Create `tests/test_errand_routing.py`, `tests/test_errand_routing_api.py`, `tests/test_pwa_errand_steer.py`; extend `tests/test_errand_lists_render.py`.

---

### Task 1: Schema, settings and storage foundations

**Files:**
- Modify: `models/schemas.py:1668-1700` (Errand), `models/schemas.py:1084` (Settings, next to `propose_shopping_errands`)
- Modify: `services/settings_registry.py:241` (after the `propose_shopping_errands` entry)
- Modify: `services/storage.py:8425-8460` (errand functions) and `:7869` (scheduled errands)
- Test: `tests/test_errand_routing_api.py` (new; storage half)

**Interfaces:**
- Produces: `Errand.skip_dates: List[str]`, `Errand.pinned_date: Optional[str]`, `Errand.pinned_start: Optional[str]`, `Errand.pinned_end: Optional[str]`, `Errand.once_driver_id: Optional[str]`; `STEER_FIELDS = ('skip_dates', 'pinned_date', 'pinned_start', 'pinned_end', 'once_driver_id')` on `models.schemas`; `Settings.errand_dedicated_trip_mins: int = 25`.
- Produces: `storage.get_errand_by_id(ident) -> Optional[dict]` (uuid string or doc_id int/str; the dict carries `doc_id`); `storage.complete_errand(doc_id: int, incoming: Optional[dict] = None, now: Optional[float] = None) -> Optional[int]` (returns the successor's doc_id or None); `storage.forget_errand_placements(errand_id: str) -> int` (rows removed); `storage.save_errand_placement_notes(notes: dict) -> None`; `storage.get_errand_placement_notes() -> dict`; `storage.get_all_scheduled_errand_rows() -> dict` (`{errand_id: row}`); `storage.bump_schedule_generation() -> int`; `storage.get_schedule_generation() -> int`.

- [ ] **Step 1: Write the failing storage tests**

Create `tests/test_errand_routing_api.py`:

```python
"""Errands ride the route — storage, API and agent contract.

Spec: docs/superpowers/specs/2026-10-22-errands-ride-the-route-design.md
§3 (placement/unplaced on GET), §4.1 (fields + validators), §4.3
(completion and the recurring successor), §4.4 (a steer forgets placements),
§4.6 (the agent writes by doc_id), §5 (the setting round trip).

Run from chauffeur/:  python tests/test_errand_routing_api.py
"""
import datetime
import os
import sys
import tempfile
import time

os.environ.setdefault("CHAUFFEUR_DATA_DIR", tempfile.mkdtemp(prefix="chauffeur_errand_api_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import check  # noqa: E402
from services import storage  # noqa: E402

WEEK = 7 * 86400


def _fresh():
    with storage.db_lock:
        storage.errands_table.truncate()
        storage.daily_schedules_table.truncate()
        storage.app_state_table.truncate()


def _errand(**over):
    base = {'id': over.pop('id', 'e-' + str(time.time_ns())), 'title': 'Costco run',
            'duration_mins': 30, 'location': 'Costco', 'priority': 2,
            'is_completed': False, 'status': 'pending', 'created_at': time.time(),
            'starts_on': None, 'recurrence_rule': None, 'tags': [],
            'skip_dates': [], 'pinned_date': None, 'pinned_start': None,
            'pinned_end': None, 'once_driver_id': None}
    base.update(over)
    return base


def _row(errand_id, date_str, driver_id='d1'):
    return {'id': errand_id, 'driver': {'id': driver_id, 'name': 'Jeff'},
            'start': f'{date_str}T16:10:00', 'start_time': f'{date_str}T16:10:00',
            'end': f'{date_str}T16:40:00', 'end_time': f'{date_str}T16:40:00',
            'title': 'Costco run', 'location': 'Costco',
            'why': {'kind': 'on_the_way', 'detour_mins': 6, 'driver_name': 'Jeff',
                    'leg': {'from': 'Home', 'to': 'Soccer'},
                    'text': "on Jeff's way to Soccer, +6 min"}}


def scenario_the_errand_model_carries_steer_fields_and_validates_them():
    from models.schemas import Errand, STEER_FIELDS
    e = Errand(**_errand(skip_dates=['2026-10-27'], pinned_date='2026-10-31',
                         pinned_start='09:00', pinned_end='11:00', once_driver_id='d2'))
    check(e.skip_dates == ['2026-10-27'] and e.pinned_date == '2026-10-31'
          and e.pinned_start == '09:00' and e.once_driver_id == 'd2',
          "the four steer fields round-trip through the model")
    check(set(STEER_FIELDS) == {'skip_dates', 'pinned_date', 'pinned_start', 'pinned_end', 'once_driver_id'},
          f"STEER_FIELDS names the one-shot fields: {STEER_FIELDS}")
    for bad in ({'pinned_date': '31/10/2026'}, {'skip_dates': ['tomorrow']},
                {'pinned_start': '9am'}, {'pinned_end': '25:00'}):
        try:
            Errand(**_errand(**bad))
            check(False, f"a malformed steer value was accepted: {bad}")
        except ValueError:
            pass
    check(Errand(**_errand()).skip_dates == [], "steer fields default empty")


def scenario_the_setting_exists_with_its_default_and_bounds():
    from models.schemas import Settings
    check(Settings().errand_dedicated_trip_mins == 25, "default is 25 minutes")
    for bad in (-1, 121):
        try:
            Settings(errand_dedicated_trip_mins=bad)
            check(False, f"out-of-range penalty accepted: {bad}")
        except ValueError:
            pass
    from services import settings_registry as reg
    owner = reg.owner('errand_dedicated_trip_mins')
    check(owner and owner['page'] == 'errands' and owner['anchor'] == 'errand-settings',
          f"the registry points the setting at the Errands drawer: {owner}")


def scenario_get_errand_by_id_takes_a_uuid_or_a_doc_id():
    _fresh()
    doc_id = storage.add_errand(_errand(id='e-uuid'))
    by_uuid = storage.get_errand_by_id('e-uuid')
    by_doc = storage.get_errand_by_id(doc_id)
    by_doc_str = storage.get_errand_by_id(str(doc_id))
    check(by_uuid and by_uuid['doc_id'] == doc_id, "found by uuid, carrying doc_id")
    check(by_doc and by_doc['id'] == 'e-uuid', "found by integer doc_id")
    check(by_doc_str and by_doc_str['id'] == 'e-uuid', "found by doc_id as a string")
    check(storage.get_errand_by_id('nope') is None, "unknown ids are None, not an error")


def scenario_complete_errand_clears_steer_and_anchors_the_successor_on_the_cycle():
    _fresh()
    anchor = time.mktime(datetime.datetime(2026, 10, 5, 0, 0).timetuple())
    doc_id = storage.add_errand(_errand(id='e-weekly', recurrence_rule='weekly', starts_on=anchor,
                                        skip_dates=['2026-10-13'], pinned_date='2026-10-14',
                                        pinned_start='09:00', once_driver_id='d2'))
    succ = storage.complete_errand(doc_id, now=anchor + 8 * 86400)
    rows = {e['id']: e for e in storage.get_all_errands()}
    done = rows['e-weekly']
    check(done['is_completed'] is True and done['skip_dates'] == [] and done['pinned_date'] is None
          and done['pinned_start'] is None and done['once_driver_id'] is None,
          f"the completed row is done and its one-shot fields are cleared: {done}")
    check(succ is not None and succ != doc_id, "a weekly errand mints a successor with a new doc_id")
    new = next(e for e in rows.values() if e['doc_id'] == succ)
    check(new['id'] != 'e-weekly' and new['is_completed'] is False and new['status'] == 'pending'
          and new['last_scheduled_end'] is None, f"the successor is a fresh pending row: {new}")
    check(abs(new['starts_on'] - (anchor + WEEK)) < 1,
          f"the successor anchors on the completed cycle (anchor + 7 days), got {new['starts_on']} vs {anchor + WEEK}")
    check(new['skip_dates'] == [] and new['pinned_date'] is None and new['once_driver_id'] is None,
          "the successor inherits no steering")
    check(storage.complete_errand(doc_id, now=anchor + 9 * 86400) is None
          and len(storage.get_all_errands()) == 2, "completing twice mints nothing")
    one_off = storage.add_errand(_errand(id='e-once'))
    check(storage.complete_errand(one_off) is None and len(storage.get_all_errands()) == 3,
          "a one-off errand has no successor")


def scenario_forget_errand_placements_removes_rows_and_the_note():
    _fresh()
    storage.save_cached_daily_schedule('2026-10-27', {'scheduled_errands': [_row('e1', '2026-10-27'), _row('e2', '2026-10-27')]}, 'h')
    storage.save_cached_daily_schedule('2026-10-28', {'scheduled_errands': [_row('e1', '2026-10-28')]}, 'h')
    storage.save_errand_placement_notes({'e1': {'reason': 'no_slot', 'text': 'x', 'generation': 1},
                                         'e3': {'reason': 'no_location', 'text': 'y', 'generation': 1}})
    removed = storage.forget_errand_placements('e1')
    check(removed == 2, f"both of e1's rows went, got {removed}")
    rows = storage.get_all_scheduled_errand_rows()
    check(set(rows) == {'e2'} and rows['e2']['why']['kind'] == 'on_the_way',
          f"e2 keeps its whole row: {rows}")
    check(set(storage.get_errand_placement_notes()) == {'e3'}, "e1's note is gone, e3's stays")
    check(storage.get_all_scheduled_errands() == {'e2': '2026-10-27T16:10:00'},
          "the start-only aggregator still works for its old callers")


def scenario_the_schedule_generation_counts_up():
    _fresh()
    check(storage.get_schedule_generation() == 0, "starts at zero")
    check(storage.bump_schedule_generation() == 1 and storage.bump_schedule_generation() == 2
          and storage.get_schedule_generation() == 2, "bumps by one and reads back")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} errand routing api scenarios passed")
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_errand_routing_api.py`
Expected: FAIL in the first scenario with `ImportError: cannot import name 'STEER_FIELDS'`.

- [ ] **Step 3: Add the fields and validators to `Errand`, the setting to `Settings`**

In `models/schemas.py`, after `occasion_key` inside `class Errand` (line ~1699):

```python
    # Steering (errands-ride-the-route §4.1): one-shot, per cycle. A date is
    # ISO (YYYY-MM-DD), a time HH:MM. Cleared by storage.complete_errand.
    skip_dates: List[str] = Field(default_factory=list)
    pinned_date: Optional[str] = None
    pinned_start: Optional[str] = None
    pinned_end: Optional[str] = None
    once_driver_id: Optional[str] = None

    @field_validator('skip_dates')
    @classmethod
    def _skip_dates_are_iso(cls, v):
        import datetime as _dt
        for d in v or []:
            _dt.date.fromisoformat(str(d))
        return list(v or [])

    @field_validator('pinned_date')
    @classmethod
    def _pinned_date_is_iso(cls, v):
        import datetime as _dt
        if v in (None, ''):
            return None
        _dt.date.fromisoformat(str(v))
        return str(v)

    @field_validator('pinned_start', 'pinned_end')
    @classmethod
    def _pinned_times_are_hhmm(cls, v):
        import re as _re
        if v in (None, ''):
            return None
        if not _re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', str(v)):
            raise ValueError('time must be HH:MM')
        return str(v)
```

Add `field_validator` to the pydantic import on line 1: `from pydantic import BaseModel, ConfigDict, Field, field_validator`. Directly after the `Errand` class add:

```python
# The one-shot steer fields, named once so storage, the PUT and the agent agree.
STEER_FIELDS = ('skip_dates', 'pinned_date', 'pinned_start', 'pinned_end', 'once_driver_id')
```

In `class Settings`, right after `propose_shopping_errands` (line ~1084):

```python
    # Errands ride the route §2: how many extra minutes a passing drive may add
    # before a separate trip from home is worth it. Applied to the empty-day
    # shape only.
    errand_dedicated_trip_mins: int = Field(default=25, ge=0, le=120)
```

- [ ] **Step 4: Register the setting**

In `services/settings_registry.py`, after the `propose_shopping_errands` entry (line ~243):

```python
    _e('errand_dedicated_trip_mins', 'daily', 'Prefer errands on the way',
       'How many extra minutes a passing drive may add before a separate trip '
       'from home is worth it. Errands land on a route someone already drives '
       'unless a trip from home beats it by this much.',
       page='errands', anchor='errand-settings'),
```

- [ ] **Step 5: Add the storage helpers**

In `services/storage.py` after `delete_errand` (line ~8460):

```python
def get_errand_by_id(ident):
    """One errand by its uuid OR its document id (int or digit string). None
    when nothing matches. The agent used to look errands up by a helper that
    did not exist and then write by the uuid, which the table does not key on."""
    if ident is None:
        return None
    with db_lock:
        s = str(ident)
        for e in errands_table.all():
            if e.get('id') == s or str(e.doc_id) == s:
                doc = dict(e)
                doc['doc_id'] = e.doc_id
                return doc
    return None


def _errand_cycle_days(rule):
    return {'daily': 1, 'weekly': 7, 'monthly': 30}.get(rule or '', None)


def complete_errand(doc_id: int, incoming: dict = None, now: float = None):
    """THE completion path (spec §4.3): the PUT, the PWA tick, the page tick and
    the agent all come here. Marks the row done, clears its one-shot steer
    fields, and for a recurring errand mints the successor anchored on the
    cycle just completed with no steering. Idempotent: a completed row mints
    nothing and returns None. Returns the successor's doc_id when one is made."""
    import time as _time
    import uuid as _uuid
    from models.schemas import STEER_FIELDS
    now = now if now is not None else _time.time()
    with db_lock:
        rows = [e for e in errands_table.all() if e.doc_id == int(doc_id)]
        if not rows:
            return None
        old = dict(rows[0])
        already = bool(old.get('is_completed'))
        data = dict(old)
        if incoming:
            data.update({k: v for k, v in incoming.items() if k != 'doc_id'})
        data['is_completed'] = True
        data['status'] = 'completed'
        for f in STEER_FIELDS:
            data[f] = [] if f == 'skip_dates' else None
        mark_all_daily_schedules_dirty()
        deletion.check()
        cache_table.truncate()
        deletion.check()
        custom_schedules_table.truncate()
        deletion.check()
        errands_table.update(data, doc_ids=[int(doc_id)])
        cycle = _errand_cycle_days(data.get('recurrence_rule'))
        if already or not cycle:
            return None
        anchor = data.get('starts_on') or data.get('created_at') or now
        succ = dict(data)
        succ.pop('doc_id', None)
        succ['id'] = _uuid.uuid4().hex
        succ['is_completed'] = False
        succ['status'] = 'pending'
        succ['last_scheduled_end'] = None
        succ['created_at'] = now
        succ['starts_on'] = float(anchor) + cycle * 86400
        for f in STEER_FIELDS:
            succ[f] = [] if f == 'skip_dates' else None
        return errands_table.insert(succ)


def forget_errand_placements(errand_id: str) -> int:
    """Drop every cached placement of one errand and its note, so a steer or an
    edit cannot be held over by the already-scheduled scan (spec §4.4)."""
    removed = 0
    with db_lock:
        for daily in daily_schedules_table.all():
            sched = daily.get('schedule') or {}
            rows = sched.get('scheduled_errands') or []
            keep = [r for r in rows if r.get('id') != errand_id]
            if len(keep) != len(rows):
                removed += len(rows) - len(keep)
                sched = dict(sched)
                sched['scheduled_errands'] = keep
                deletion.check()
                daily_schedules_table.update({'schedule': sched}, doc_ids=[daily.doc_id])
        notes = dict(get_app_state('errand_placement_notes', {}) or {})
        if errand_id in notes:
            notes.pop(errand_id)
            set_app_state('errand_placement_notes', notes)
    return removed


def save_errand_placement_notes(notes: dict):
    set_app_state('errand_placement_notes', dict(notes or {}))


def get_errand_placement_notes() -> dict:
    return dict(get_app_state('errand_placement_notes', {}) or {})


def get_all_scheduled_errand_rows() -> dict:
    """Every cached placement, whole row, keyed by errand id. The older
    get_all_scheduled_errands keeps returning the start alone for its callers."""
    with db_lock:
        out = {}
        for daily in daily_schedules_table.all():
            for se in (daily.get('schedule') or {}).get('scheduled_errands', []) or []:
                out[se.get('id')] = dict(se)
        return out


def get_schedule_generation() -> int:
    return int(get_app_state('schedule_generation', 0) or 0)


def bump_schedule_generation() -> int:
    with db_lock:
        g = int(get_app_state('schedule_generation', 0) or 0) + 1
        set_app_state('schedule_generation', g)
        return g
```

`get_app_state`/`set_app_state` are defined later in the file (line ~8179); Python resolves them at call time, so the order is fine. `db_lock` is re-entrant in this module (other helpers nest it); if it is not, call `get_app_state`/`set_app_state` outside the `with` block instead.

- [ ] **Step 6: Run the tests**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_errand_routing_api.py && python tests/test_settings_registry.py && python tests/test_storage.py`
Expected: the six storage scenarios pass; `test_settings_registry` fails ONLY on the UI audit for `errand_dedicated_trip_mins` (the drawer control comes in Task 7). If the registry test's UI audit fails, note it and continue; it is Task 7's acceptance. `test_storage` passes.

- [ ] **Step 7: Hand back**

Report what changed, the three test commands and their results. Claude reviews and commits.

---

### Task 2: The routing core — legs, candidate timing, ranking, why

**Files:**
- Modify: `solver/matcher.py:2430-2841` (`insert_errands_globally` and the closures above it)
- Test: `tests/test_errand_routing.py` (new)

**Interfaces:**
- Consumes: `storage.get_cached_travel_time`, `storage.UNROUTABLE`, `matcher.requires_stay`-style attendance rule check (today's closure), `matcher.does_event_match_rule`, `get_active_home`.
- Produces: `matcher.errand_leg_minutes(a, b) -> Optional[int]`; `matcher.errand_why_text(why: dict) -> str`; `matcher.ERRAND_DAY_START = time(8, 0)`, `matcher.ERRAND_DAY_END = time(21, 0)`; `matcher.insert_errands_globally(base_schedules, errands, drivers, trip_metadata=None, driver_events=None, now=None, settings=None) -> Tuple[Dict[str, List[dict]], Dict[str, dict]]`. Each scheduled row keeps every key it has today (`id, doc_id, group_id, driver, event_type, start, end, start_time, end_time, title, location, priority, inserted_after_event_id, inserted_before_event_id, travel_to_mins, travel_from_mins`) and gains `why`. Notes are `{errand_id: {'reason': str, 'text': str}}` (Task 5 stamps `generation`).

- [ ] **Step 1: Write the failing routing tests**

Create `tests/test_errand_routing.py`:

```python
"""Errands ride the route — the solver pass, run on a grid.

Spec: docs/superpowers/specs/2026-10-22-errands-ride-the-route-design.md
§1 (legs, candidate timing), §2 (score, ties, finalization), §3 (why).

Places are points on a grid; drive minutes are Manhattan distance. A place
not on the grid has NO drive time (None), which is what an unresolved
address looks like to the pass.

Run from chauffeur/:  python tests/test_errand_routing.py
"""
import datetime
import os
import sys
import tempfile

os.environ.setdefault("CHAUFFEUR_DATA_DIR", tempfile.mkdtemp(prefix="chauffeur_errand_route_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import check  # noqa: E402
from models.schemas import Driver, Event  # noqa: E402
from solver import matcher  # noqa: E402

GRID = {'Home': (0, 0), 'Soccer': (20, 0), 'Store': (10, 10), 'Work': (0, 30),
        'Pharmacy': (0, 20), 'Piano': (-30, 0), 'Far': (80, 80), 'Shop': (-4, -4)}


def _leg(a, b):
    if not a or not b:
        return None
    if a == b:
        return 0
    if a not in GRID or b not in GRID:
        return None
    (x1, y1), (x2, y2) = GRID[a], GRID[b]
    return abs(x1 - x2) + abs(y1 - y2)


matcher.errand_leg_minutes = _leg

MON = datetime.date(2026, 10, 26)
DAYS = [str(MON + datetime.timedelta(days=i)) for i in range(7)]   # Mon..Sun
NOW = datetime.datetime(2026, 10, 25, 20, 0).astimezone()           # Sunday evening
SETTINGS = {'errand_dedicated_trip_mins': 25}


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
            'pinned_end': None, 'once_driver_id': None}
    base.update(over)
    return base


def _world(events_by_day, drivers, assignments):
    """base_schedules for DAYS: events on each day, assignments {eid: did}."""
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


def scenario_near_a_route_beats_earlier_from_home_and_did_not_before():
    # Tuesday: Jeff drives Kate to Soccer (Home 0,0 -> Soccer 20,0). The Shop
    # sits behind home at (-4,-4): the leg detour (8 + 28 - 20 = 16) equals the
    # round trip from home (16), the exact tie the old code broke by taking
    # the first slot scanned: Monday, empty, from home. New rule: the round
    # trip costs 16 + 25 = 41 and Tuesday's leg costs 16.
    jeff = _driver('d1', 'Jeff')
    soccer = _ev('soccer', 1, 16, 'Soccer', 'Soccer practice')
    base = _world({1: [soccer]}, [jeff], {'soccer': 'd1'})
    rows, _ = _place(base, [_errand(location='Shop')], [jeff], settings={'errand_dedicated_trip_mins': 0})
    d, r = _only(rows)
    check(d == DAYS[0] and r['why']['kind'] == 'from_home'
          and r['why']['text'] == 'a trip from home, 8 min each way',
          f"with no penalty the old answer stands (Monday from home): {d} {r['why']}")
    rows, notes = _place(base, [_errand(location='Shop')], [jeff])
    d, r = _only(rows)
    check(d == DAYS[1], f"lands Tuesday, got {d}")
    check(r['driver']['id'] == 'd1' and r['why']['kind'] == 'on_the_way'
          and r['why']['detour_mins'] == 16 and r['why']['leg'] == {'from': 'Home', 'to': 'Soccer practice'},
          f"on Jeff's leg to soccer: {r['why']}")
    check(r['why']['text'] == "on Jeff's way to Soccer practice, +16 min", f"text: {r['why']['text']!r}")
    check(r['inserted_before_event_id'] == 'soccer' and r['inserted_after_event_id'] is None
          and r['travel_to_mins'] == 8 and r['travel_from_mins'] == 28, f"neighbours and legs: {r}")
    end = datetime.datetime.fromisoformat(r['end_time'])
    check(end + datetime.timedelta(minutes=28) <= soccer.start, "arrives at soccer on time")
    check(notes == {}, f"nothing unplaced: {notes}")


def scenario_a_drivers_own_event_is_a_leg_not_a_window():
    # Lorena's work day Wednesday (Home 0,0 -> Work 0,30). The Pharmacy (0,20)
    # is ON that line: detour 0. It must land before work, never inside it.
    lorena = _driver('d2', 'Lorena')
    work = _ev('work', 2, 9, 'Work', 'Work', dur=8 * 60)
    base = _world({}, [lorena], {})
    rows, _ = _place(base, [_errand(location='Pharmacy')], [lorena], driver_events={'d2': [work]})
    d, r = _only(rows)
    check(d == DAYS[2] and r['why']['kind'] == 'on_the_way' and r['why']['detour_mins'] == 0
          and r['why']['leg']['to'] == 'Work', f"on her way to work: {d} {r['why']}")
    end = datetime.datetime.fromisoformat(r['end_time'])
    check(end + datetime.timedelta(minutes=10) <= work.start, "done before work starts")


def scenario_from_home_when_nothing_passes_near():
    jeff = _driver('d1', 'Jeff')
    base = _world({}, [jeff], {})                 # nobody drives anywhere this week
    rows, _ = _place(base, [_errand()], [jeff])
    d, r = _only(rows)
    check(d == DAYS[0] and r['why']['kind'] == 'from_home', f"earliest day, from home: {d} {r['why']}")
    check(r['why']['text'] == 'a trip from home, 20 min each way', f"text: {r['why']['text']!r}")
    check(datetime.datetime.fromisoformat(r['start_time']).time() == datetime.time(8, 0),
          "an empty day starts at the day's start")


def scenario_weekday_filter_applies_to_candidate_days():
    jeff = _driver('d1', 'Jeff')
    base = _world({}, [jeff], {})
    rows, _ = _place(base, [_errand(valid_days_of_week=[1])], [jeff])   # Tuesday only
    d, r = _only(rows)
    check(d == DAYS[1], f"a Tuesday-only errand lands Tuesday, not {d}")


def scenario_finalization_uses_the_winners_own_day_and_driver():
    # Winner is Monday with d1 (Soccer Monday). d2 has a Friday ride that is
    # scanned later; the old code read Friday's schedule and d2's home when it
    # wrote the row.
    jeff, lorena = _driver('d1', 'Jeff'), _driver('d2', 'Lorena')
    soccer = _ev('soccer', 0, 16, 'Soccer')
    piano = _ev('piano', 4, 16, 'Piano')
    base = _world({0: [soccer], 4: [piano]}, [jeff, lorena], {'soccer': 'd1', 'piano': 'd2'})
    rows, _ = _place(base, [_errand()], [jeff, lorena])
    d, r = _only(rows)
    check(d == DAYS[0] and r['driver']['id'] == 'd1' and r['inserted_before_event_id'] == 'soccer',
          f"Monday, Jeff, before soccer: {d} {r}")


def scenario_order_never_decides():
    jeff, lorena = _driver('d1', 'Jeff'), _driver('d2', 'Lorena')
    soccer = _ev('soccer', 1, 16, 'Soccer')
    piano = _ev('piano', 3, 16, 'Piano')
    base = _world({1: [soccer], 3: [piano]}, [jeff, lorena], {'soccer': 'd1', 'piano': 'd2'})
    a = _only(_place(base, [_errand()], [jeff, lorena])[0])
    reversed_base = dict(reversed(list(base.items())))
    b = _only(_place(reversed_base, [_errand()], [lorena, jeff])[0])
    check(a[0] == b[0] and a[1]['driver']['id'] == b[1]['driver']['id']
          and a[1]['start_time'] == b[1]['start_time'], f"same answer either way: {a} vs {b}")
    # Two identical drivers on identical legs: the lower id wins, deterministically.
    twin = _driver('d0', 'Twin')
    s2 = _ev('soccer2', 1, 16, 'Soccer')
    base2 = _world({1: [soccer, s2]}, [jeff, twin], {'soccer': 'd1', 'soccer2': 'd0'})
    c = _only(_place(base2, [_errand()], [jeff, twin])[0])
    e = _only(_place(base2, [_errand()], [twin, jeff])[0])
    check(c[1]['driver']['id'] == 'd0' == e[1]['driver']['id'], "ties go to the lower driver id")


def scenario_candidate_timing_fits_windows():
    jeff = _driver('d1', 'Jeff')
    base = _world({}, [jeff], {})
    rows, _ = _place(base, [_errand(time_window_start='10:00', time_window_end='11:00')], [jeff])
    d, r = _only(rows)
    check(datetime.datetime.fromisoformat(r['start_time']).time() == datetime.time(10, 0)
          and datetime.datetime.fromisoformat(r['end_time']).time() == datetime.time(10, 30),
          f"an empty day honours a 10-11 window: {r['start_time']}")
    morning = _ev('m', 0, 9, 'Soccer', dur=60)
    base = _world({0: [morning]}, [jeff], {'m': 'd1'})
    rows, _ = _place(base, [_errand(time_window_start='14:00', time_window_end='17:00')], [jeff])
    d, r = _only(rows)
    st = datetime.datetime.fromisoformat(r['start_time'])
    check(d == DAYS[0] and st.time() >= datetime.time(14, 0) and r['why']['kind'] == 'on_the_way',
          f"an afternoon window lands after the morning ride, on the way home: {st} {r['why']}")
    rows, notes = _place(base, [_errand(time_window_start='22:00', time_window_end='23:00')], [jeff])
    check(not rows and notes.get('er1', {}).get('reason') == 'no_slot',
          f"a window outside the day is a no_slot note: {rows} {notes}")


def scenario_a_long_errand_that_fits_nowhere_is_a_no_slot_note():
    # Jeff's OWN days are packed (work 8-14, a course 15-21, every day): own
    # events are stops, never drop-off windows (R1), so a 3-hour errand has no
    # gap anywhere and must say so rather than overlap something.
    jeff = _driver('d1', 'Jeff')
    own = [e for i in range(7) for e in (_ev(f'a{i}', i, 8, 'Work', dur=6 * 60), _ev(f'b{i}', i, 15, 'Piano', dur=6 * 60))]
    base = _world({}, [jeff], {})
    rows, notes = _place(base, [_errand(duration_mins=180)], [jeff], driver_events={'d1': own})
    check(not rows and notes['er1']['reason'] == 'no_slot', f"{rows} {notes}")


def scenario_a_ride_the_driver_also_attends_is_one_stop():
    jeff = _driver('d1', 'Jeff')
    dentist = _ev('dentist', 1, 10, 'Soccer', 'Dentist', dur=60)
    base = _world({1: [dentist]}, [jeff], {'dentist': 'd1'})
    rows, _ = _place(base, [_errand()], [jeff], driver_events={'d1': [dentist]})
    d, r = _only(rows)
    check(d == DAYS[1] and r['why']['kind'] in ('on_the_way', 'inside_stop'),
          f"one stop, placed once around it: {r['why']}")
    seen = sum(1 for dd, rr in rows if rr['id'] == 'er1')
    check(seen == 1, "never two stops for one event")


def scenario_now_clamps_or_drops_todays_slot():
    jeff = _driver('d1', 'Jeff')
    soccer = _ev('soccer', 0, 16, 'Soccer')
    base = _world({0: [soccer]}, [jeff], {'soccer': 'd1'})
    late_now = datetime.datetime.combine(MON, datetime.time(15, 50)).astimezone()
    rows, _ = _place(base, [_errand()], [jeff], now=late_now)
    d, r = _only(rows)
    check(datetime.datetime.fromisoformat(r['start_time']) >= late_now, "never placed in the past")
    check(r['why']['kind'] != 'on_the_way' or r['inserted_before_event_id'] != 'soccer',
          f"the leg to soccer is already too late (needs 20+30+20 min before 16:00): {r}")


def scenario_text_for_every_kind():
    t = matcher.errand_why_text
    check(t({'kind': 'on_the_way', 'driver_name': 'Jeff', 'detour_mins': 6, 'leg': {'from': 'Home', 'to': 'Soccer'}})
          == "on Jeff's way to Soccer, +6 min")
    check(t({'kind': 'on_the_way', 'driver_name': 'Jeff', 'detour_mins': 6, 'leg': {'from': 'Soccer', 'to': 'Home'}})
          == "on Jeff's way home from Soccer, +6 min")
    check(t({'kind': 'inside_stop', 'driver_name': 'Kate', 'detour_mins': 9, 'leg': {'from': 'Piano', 'to': 'Piano'}})
          == "during Piano, +9 min")
    check(t({'kind': 'from_home', 'driver_name': 'Jeff', 'detour_mins': 24}) == 'a trip from home, 12 min each way')
    check(t({'kind': 'pinned', 'driver_name': 'Jeff', 'detour_mins': 4, 'leg': {'from': 'Home', 'to': 'Work'}})
          == "the day you picked, on Jeff's way to Work, +4 min")
    check(t({'kind': 'unknown_travel', 'driver_name': 'Jeff'}) == 'drive time unknown, check the address')


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} errand routing scenarios passed")
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_errand_routing.py`
Expected: FAIL at the first scenario with `TypeError: insert_errands_globally() got an unexpected keyword argument 'driver_events'`.

- [ ] **Step 3: Rewrite the pass**

Replace `insert_errands_globally` in `solver/matcher.py` (from `def insert_errands_globally` at line 2430 through `return scheduled_errands_by_date` at line 2841) with the following. Keep the three closures that live inside today's function (`requires_stay`, `is_valid_time_window`, `get_pax_in_car_at_gap`) by lifting them to module level under the names below; their bodies are unchanged except where noted.

```python
# ---------------------------------------------------------------------------
# Errands ride the route (spec docs/superpowers/specs/2026-10-22-errands-ride-the-route-design.md)
# ---------------------------------------------------------------------------
ERRAND_DAY_START = time(8, 0)
ERRAND_DAY_END = time(21, 0)
ERRAND_UNPLACED_TEXT = {
    'no_location': 'needs a location before it can be planned',
    'unroutable_location': 'the address could not be routed, check it',
    'no_slot': 'no drive in its window has room for it',
    'no_driver': 'nobody who may run it has a drive in its window',
    'pinned_day_passed': 'the day you picked has passed',
    'pinned_day_not_in_range': 'the day you picked is further out than the schedule looks; it will land when that week is planned',
    'every_day_skipped': 'every day in its window is skipped',
}


def errand_leg_minutes(a, b):
    """True cached drive minutes between two places, no collapse and no guess:
    0 for the same place, None when the pair is unknown or unroutable. The
    pass reads this through the module so a test can replace it."""
    if not a or not b:
        return None
    a_s, b_s = str(a).strip(), str(b).strip()
    if a_s.lower() == b_s.lower():
        return 0
    from services import storage
    v = storage.get_cached_travel_time(a_s.lower(), b_s.lower(), ignore_age=True)
    if v is None or v == storage.UNROUTABLE:
        return None
    return int(v)


def errand_why_text(why):
    kind = (why or {}).get('kind')
    who = (why or {}).get('driver_name') or 'someone'
    det = int((why or {}).get('detour_mins') or 0)
    leg = (why or {}).get('leg') or {}
    if kind == 'unknown_travel':
        return 'drive time unknown, check the address'
    if kind == 'from_home':
        return f"a trip from home, {det // 2} min each way"
    if kind == 'inside_stop':
        return f"during {leg.get('from') or 'the stop'}, +{det} min"
    if kind == 'pinned':
        inner = dict(why)
        inner['kind'] = 'from_home' if not leg else ('inside_stop' if leg.get('from') == leg.get('to') else 'on_the_way')
        return 'the day you picked, ' + errand_why_text(inner)
    if leg.get('to') == 'Home':
        return f"on {who}'s way home from {leg.get('from')}, +{det} min"
    return f"on {who}'s way to {leg.get('to')}, +{det} min"


class _Stop:
    __slots__ = ('id', 'title', 'start', 'end', 'location', 'is_ride', 'event')

    def __init__(self, event, is_ride):
        self.id = getattr(event, 'id', None)
        self.title = getattr(event, 'title', '') or (getattr(event, 'location', '') or '')
        self.start = event.start
        self.end = event.end
        self.location = getattr(event, 'location', None)
        self.is_ride = is_ride
        self.event = event


def _errand_requires_stay(e, all_rules):
    """Today's `requires_stay` closure, unchanged: an attendance rule saying
    the driver stays makes the event no drop-off-and-run window."""
    for r_data in all_rules:
        if r_data.get('constraint_type') == 'attendance' and r_data.get('attendance_action') == 'stay':
            try:
                r_obj = Rule(**r_data)
            except Exception:
                continue
            if does_event_match_rule(e, r_obj):
                return True
    return False


def _hhmm(s):
    h, m = map(int, str(s).split(':'))
    return time(h, m)


def _driver_day_route(date_obj, d_id, day_data, driver_events):
    """Spec §1: assigned rides plus the driver's own located, timed events on
    this date, one stop per event id, sorted by start."""
    stops, seen = [], set()
    assignments = day_data.get('assignments', {}) or {}
    for e in day_data.get('events', []) or []:
        if assignments.get(e.id) != d_id:
            continue
        key = getattr(e, 'original_event_id', None) or e.id
        if key in seen:
            continue
        seen.add(key)
        stops.append(_Stop(e, True))
    for e in (driver_events or {}).get(d_id, []) or []:
        if getattr(e, 'all_day', False) or getattr(e, 'event_type', '') == 'background_trip':
            continue
        if not (getattr(e, 'location', None) or '').strip():
            continue
        if e.start.astimezone().date() != date_obj:
            continue
        key = getattr(e, 'original_event_id', None) or e.id
        if key in seen or e.id in seen:
            continue
        seen.add(key)
        stops.append(_Stop(e, False))
    stops.sort(key=lambda s: s.start)
    return stops


def errand_window(errand, today, range_dates):
    """Spec §4.2 steps 1-3. Returns (window_start, window_end, skip, reason):
    dates inclusive, `skip` a set of dates to drop, `reason` a note code when
    nothing can be placed."""
    anchor_ts = errand.get('starts_on') or errand.get('created_at', 0)
    try:
        anchor_date = datetime.fromtimestamp(anchor_ts).date()
    except Exception:
        anchor_date = today
    rule = errand.get('recurrence_rule')
    if rule == 'weekly':
        target = anchor_date + timedelta(days=7)
        w_start, w_end = target - timedelta(days=2), target + timedelta(days=2)
    elif rule == 'daily':
        w_start = w_end = anchor_date + timedelta(days=1)
    elif rule == 'monthly':
        target = anchor_date + timedelta(days=30)
        w_start, w_end = target - timedelta(days=5), target + timedelta(days=5)
    else:
        w_start = anchor_date
        w_end = (w_start + timedelta(days=int(errand['window_days']) - 1)) if errand.get('window_days') else datetime.max.date()
    pinned = errand.get('pinned_date')
    if pinned:
        try:
            p = datetime.fromisoformat(str(pinned)).date()
        except Exception:
            p = None
        if p is None or p < today:
            return None, None, set(), 'pinned_day_passed'
        if range_dates and p > max(range_dates):
            return None, None, set(), 'pinned_day_not_in_range'
        w_start = w_end = p
    elif today > w_end:
        w_start, w_end = today, datetime.max.date()
    skip = set()
    for s in errand.get('skip_dates') or []:
        try:
            d = datetime.fromisoformat(str(s)).date()
        except Exception:
            continue
        if d >= today:
            skip.add(d)
    days = [d for d in (range_dates or []) if w_start <= d <= w_end]
    if days and all(d in skip for d in days):
        return w_start, w_end, skip, 'every_day_skipped'
    return w_start, w_end, skip, None


def _first_fit(earliest, latest, duration, day_date, errand, now):
    """Spec §1 candidate timing: the earliest start inside every bound, or None."""
    lo, hi = earliest, latest
    for key in ('time_window_start', 'pinned_start'):
        if errand.get(key):
            t = datetime.combine(day_date, _hhmm(errand[key])).astimezone()
            lo = max(lo, t)
    for key in ('time_window_end', 'pinned_end'):
        if errand.get(key):
            t = datetime.combine(day_date, _hhmm(errand[key])).astimezone() - timedelta(minutes=duration)
            hi = min(hi, t)
    if now is not None:
        lo = max(lo, now)
    if lo > hi:
        return None
    return lo


def _pax_in_car(stops, gap_idx):
    """Today's get_pax_in_car_at_gap, on stops."""
    in_car = set()
    for i in range(gap_idx + 1):
        e = stops[i].event
        title = (getattr(e, 'title', '') or '').lower()
        pids = []
        if getattr(e, 'passengers', None):
            pids = [str(p.id) for p in e.passengers]
        elif getattr(e, 'passenger_ids', None):
            pids = [str(pid) for pid in e.passenger_ids]
        if title.startswith('pickup'):
            in_car.update(pids)
        elif title.startswith('dropoff'):
            for pid in pids:
                in_car.discard(pid)
    return in_car


def insert_errands_globally(base_schedules, errands, drivers, trip_metadata=None,
                            driver_events=None, now=None, settings=None):
    """Place every active errand on the leg it costs least to add to (spec §1-§3).

    Returns (scheduled_by_date, notes). Drive time comes ONLY from
    `errand_leg_minutes` looked up on this module at call time."""
    from services import storage
    import inspect as _inspect
    me = _inspect.getmodule(insert_errands_globally)
    leg = lambda a, b: me.errand_leg_minutes(a, b)   # noqa: E731  (module lookup, stubbable)

    now = now if now is not None else datetime.now().astimezone()
    today = now.date()
    settings = settings or {}
    try:
        penalty = int(settings.get('errand_dedicated_trip_mins', 25))
    except (TypeError, ValueError):
        penalty = 25
    all_rules = storage.get_all_rules()
    scheduled = {d: [] for d in base_schedules.keys()}
    notes = {}
    active = [e for e in errands if not e.get('is_completed') and e.get('status') != 'past_due']
    if not active:
        return scheduled, notes
    driver_map = {d.id: d for d in drivers if d.id != 'unassigned_ghost'}
    range_dates = sorted(datetime.strptime(d, "%Y-%m-%d").date() for d in base_schedules.keys())
    routes = {d_str: {d_id: _driver_day_route(datetime.strptime(d_str, "%Y-%m-%d").date(), d_id, day, driver_events)
                      for d_id in driver_map}
              for d_str, day in base_schedules.items()}
    active.sort(key=lambda x: (x.get('priority', 2), -x.get('duration_mins', 30)))

    for errand in active:
        eid = errand.get('id') or f"errand_{errand.get('doc_id')}"
        loc = (errand.get('location') or '').strip()
        if not loc:
            notes[eid] = {'reason': 'no_location', 'text': ERRAND_UNPLACED_TEXT['no_location']}
            continue
        # (Task 4 inserts the unroutable check and the bounded primer here.)
        duration = max(5, errand.get('duration_mins', 30) - errand.get('tolerance_mins', 0)) + errand.get('buffer_mins', 0)
        w_start, w_end, skip, reason = errand_window(errand, today, range_dates)
        if reason:
            notes[eid] = {'reason': reason, 'text': ERRAND_UNPLACED_TEXT[reason]}
            continue

        # Already placed on a cached day outside this solve? (validated against the steer)
        if _already_scheduled_elsewhere(errand, eid, w_start, w_end, skip, set(base_schedules.keys()), storage):
            continue

        req_pax = set(str(p) for p in errand.get('required_passengers', []))
        proh_pax = set(str(p) for p in errand.get('prohibited_passengers', []))
        once = errand.get('once_driver_id')
        required = [once] if once else list(errand.get('required_drivers', []))
        allowed = [] if once else list(errand.get('allowed_drivers', []))
        prohibited = list(errand.get('prohibited_drivers', []))
        group_id = errand.get('group_id')
        assignment_rules, window_cap = _errand_rules_for(errand, loc, duration, all_rules)
        if group_id is None:
            group_id = _group_from_rules(errand, loc, duration, all_rules)

        def allowed_for_slot(d_id, start, end):
            if not assignment_rules:
                return True
            test_ev = Event(id=eid, title=errand.get('title', ''), start=start, end=end, location=loc,
                            calendar_ids=[], source_event_ids=[], event_type="errand")
            for r, a_type in assignment_rules:
                if r.driver_id != d_id and a_type in ('required', 'preferred') and does_event_match_rule(test_ev, r):
                    return False
                if r.driver_id == d_id and a_type in ('unavailable', 'avoid') and does_event_match_rule(test_ev, r):
                    return False
            return True

        candidates = []
        saw_driver = False
        for day_date in range_dates:
            if day_date < w_start or day_date > w_end or day_date in skip:
                continue
            # A pin is the person's choice and wins over the standing weekdays (§4.2 step 2).
            if (not errand.get('pinned_date')) and errand.get('valid_days_of_week') \
                    and day_date.weekday() not in errand['valid_days_of_week']:
                continue
            d_str = str(day_date)
            day_start = datetime.combine(day_date, ERRAND_DAY_START).astimezone()
            day_end = datetime.combine(day_date, ERRAND_DAY_END).astimezone()
            for d_id, driver in driver_map.items():
                if required and d_id not in required:
                    continue
                if d_id in prohibited:
                    continue
                if allowed and d_id not in allowed:
                    continue
                if getattr(driver, 'is_disabled', False):
                    continue
                saw_driver = True
                default_home = getattr(driver, 'home_location', None)
                home = get_active_home(f'driver_{d_id}', day_start.timestamp(), default_home, trip_metadata) if trip_metadata else default_home
                group_bonus = 9999 if group_id and any(r.get('group_id') == group_id and (r.get('driver') or {}).get('id') == d_id
                                                       for r in scheduled[d_str]) else 0
                if home != default_home and not group_bonus:
                    continue
                stops = routes[d_str][d_id]
                dname = getattr(driver, 'name', d_id)

                def add(shape, start, legs, detour, prev_stop, next_stop, insert_idx, t1, t2):
                    unknown = any(v is None for v in legs)
                    cost = (0 if unknown else detour) + (penalty if shape == 'empty' else 0) - group_bonus
                    end = start + timedelta(minutes=duration)
                    if not allowed_for_slot(d_id, start, end):
                        return
                    if shape == 'from_home_leg' or shape == 'empty':
                        leg_d = {'from': 'Home', 'to': next_stop.title} if next_stop else None
                    elif shape == 'to_home_leg':
                        leg_d = {'from': prev_stop.title, 'to': 'Home'}
                    elif shape == 'inside':
                        leg_d = {'from': prev_stop.title, 'to': prev_stop.title}
                    else:
                        leg_d = {'from': prev_stop.title, 'to': next_stop.title}
                    kind = 'unknown_travel' if unknown else ('from_home' if shape == 'empty' else 'inside_stop' if shape == 'inside' else 'on_the_way')
                    if errand.get('pinned_date') and not unknown:
                        kind = 'pinned'
                    why = {'kind': kind, 'detour_mins': None if unknown else int(detour), 'driver_name': dname,
                           **({'leg': leg_d} if leg_d and shape != 'empty' else {})}
                    why['text'] = errand_why_text(why)
                    candidates.append(((1 if unknown else 0, cost, d_str, start.isoformat(), str(d_id)),
                                       dict(d_str=d_str, d_id=d_id, start=start, end=end, why=why,
                                            prev=prev_stop, next=next_stop, insert_idx=insert_idx,
                                            t1=None if unknown else t1, t2=None if unknown else t2,
                                            unknown=unknown)))

                if not stops:
                    if req_pax:
                        continue
                    t = leg(home, loc) if home else 0
                    start = _first_fit(day_start, day_end - timedelta(minutes=duration), duration, day_date, errand, now)
                    if start is not None:
                        add('empty', start, [t], (t or 0) * 2, None, None, -1, t, t)
                    continue

                first, last = stops[0], stops[-1]
                if not req_pax:
                    th = leg(home, loc) if home else 0
                    tf = leg(loc, first.location)
                    thf = leg(home, first.location) if home else 0
                    legs = [th, tf, thf]
                    unknown = any(v is None for v in legs)
                    latest = first.start - timedelta(minutes=(tf or 0) + duration)
                    start = _first_fit(day_start, latest, duration, day_date, errand, now)
                    if start is not None:
                        add('from_home_leg', start, legs, (th or 0) + (tf or 0) - (thf or 0), None, first, -1, th, tf)
                for i, s in enumerate(stops):
                    if s.is_ride and not _errand_requires_stay(s.event, all_rules) and not req_pax:
                        t_in = leg(s.location, loc)
                        t_out = leg(loc, s.location)
                        legs = [t_in, t_out]
                        earliest = s.start + timedelta(minutes=(t_in or 0))
                        latest = s.end - timedelta(minutes=(t_out or 0) + duration)
                        start = _first_fit(earliest, latest, duration, day_date, errand, now)
                        if start is not None:
                            add('inside', start, legs, (t_in or 0) + (t_out or 0), s, s, i, t_in, t_out)
                for i in range(len(stops) - 1):
                    a, b = stops[i], stops[i + 1]
                    t1 = leg(a.location, loc)
                    t2 = leg(loc, b.location)
                    tab = leg(a.location, b.location)
                    legs = [t1, t2, tab]
                    earliest = a.end + timedelta(minutes=(t1 or 0))
                    latest = b.start - timedelta(minutes=(t2 or 0) + duration)
                    start = _first_fit(earliest, latest, duration, day_date, errand, now)
                    if start is None:
                        continue
                    in_car = _pax_in_car(stops, i)
                    if req_pax and not req_pax.issubset(in_car):
                        continue
                    if proh_pax and not proh_pax.isdisjoint(in_car):
                        continue
                    add('between', start, legs, (t1 or 0) + (t2 or 0) - (tab or 0), a, b, i, t1, t2)
                if not req_pax:
                    tl = leg(last.location, loc)
                    th = leg(loc, home) if home else 0
                    tlh = leg(last.location, home) if home else 0
                    legs = [tl, th, tlh]
                    earliest = last.end + timedelta(minutes=(tl or 0))
                    start = _first_fit(earliest, day_end - timedelta(minutes=duration), duration, day_date, errand, now)
                    if start is not None:
                        add('to_home_leg', start, legs, (tl or 0) + (th or 0) - (tlh or 0), last, None, len(stops) - 1, tl, th)

        if not candidates:
            reason = 'no_slot' if saw_driver else 'no_driver'
            text = ERRAND_UNPLACED_TEXT[reason]
            if reason == 'no_driver' and once:
                text = f"{getattr(driver_map.get(once), 'name', once)} has no drive in its window, or may not run it"
            notes[eid] = {'reason': reason, 'text': text}
            continue

        candidates.sort(key=lambda c: c[0])
        best = candidates[0][1]
        d_str, d_id = best['d_str'], best['d_id']
        start, end = best['start'], best['end']
        ve = Event(id=f"{eid}__virtual", title=errand.get('title', ''), start=start, end=end, location=loc,
                   calendar_ids=[], source_event_ids=[], event_type="errand")
        routes[d_str][d_id].insert(int(best['insert_idx']) + 1, _Stop(ve, False))
        drv = driver_map[d_id]
        scheduled[d_str].append({
            "id": eid,
            "doc_id": errand.get('doc_id'),
            "group_id": group_id if errand.get('group_id') else errand.get('group_id'),
            "driver": drv.model_dump() if hasattr(drv, 'model_dump') else drv.dict(),
            "event_type": "errand",
            "start": start.isoformat(), "end": end.isoformat(),
            "start_time": start.isoformat(), "end_time": end.isoformat(),
            "title": errand.get('title'), "location": loc, "priority": errand.get('priority'),
            "inserted_after_event_id": best['prev'].id if best['prev'] else None,
            "inserted_before_event_id": best['next'].id if best['next'] else None,
            "travel_to_mins": best['t1'], "travel_from_mins": best['t2'],
            "why": best['why'],
        })
    return scheduled, notes


def _already_scheduled_elsewhere(errand, eid, w_start, w_end, skip, solving, storage):
    """Today's cached-day scan, validated against the steer (spec §4.4)."""
    once = errand.get('once_driver_id')
    pinned = errand.get('pinned_date')
    span = min((w_end - w_start).days if w_end != datetime.max.date() else 60, 60)
    for offset in range(span + 1):
        d = w_start + timedelta(days=offset)
        if d in skip or str(d) in solving:
            continue
        if errand.get('valid_days_of_week') and d.weekday() not in errand['valid_days_of_week']:
            continue
        if pinned and str(d) != str(pinned):
            continue
        cache = storage.get_cached_daily_schedule(str(d))
        if not cache or 'schedule' not in cache:
            continue
        for er in cache['schedule'].get('scheduled_errands', []) or []:
            if er.get('id') != eid:
                continue
            if once and (er.get('driver') or {}).get('id') != once:
                continue
            return True
    return False


def _errand_rules_for(errand, loc, duration, all_rules):
    """Today's assignment-rule collection for an errand, lifted out."""
    assignment_rules = []
    cap = None
    for r_data in all_rules:
        try:
            r = Rule(**r_data)
        except Exception:
            continue
        r_type = getattr(r, 'constraint_type', '')
        a_type = ''
        if r_type in ('required', 'preferred', 'unavailable', 'avoid'):
            a_type, r_type = r_type, 'assignment'
        if r_type == 'assignment':
            assignment_rules.append((r, a_type))
        if getattr(r, 'window_days', None):
            cap = r.window_days if cap is None else min(cap, r.window_days)
    return assignment_rules, cap


def _group_from_rules(errand, loc, duration, all_rules):
    """Today's group-rule match: a matching group rule's id becomes the group."""
    try:
        errand_dt = datetime.fromtimestamp(errand.get('starts_on') or errand.get('created_at', 0)).astimezone()
    except Exception:
        errand_dt = datetime.now().astimezone()
    dummy = Event(id=errand.get('id', 'temp'), title=errand.get('title', ''), start=errand_dt,
                  end=errand_dt + timedelta(minutes=duration), location=loc, calendar_ids=[],
                  source_event_ids=[], event_type="errand")
    for r_data in all_rules:
        try:
            r = Rule(**r_data)
        except Exception:
            continue
        if getattr(r, 'constraint_type', '') == 'group' and does_event_match_rule(dummy, r):
            return r.id
    return None
```

Notes for the implementer:
- Unroutable detection and priming are Task 4's; leave the marked comment where they go.
- `storage.get_all_rules()` is what today's function calls at its top (keep that name).
- `get_active_home` is the existing module function today's code already uses.
- The `me.errand_leg_minutes` indirection is what lets tests assign `matcher.errand_leg_minutes = stub`. Do not replace it with a direct call.
- `"group_id"` on the row: keep today's value (`errand.get('group_id')`); the rule-derived group only affects the bonus. Simplify that line to `"group_id": errand.get('group_id')`.

- [ ] **Step 4: Run the routing tests and the solve pack test**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_errand_routing.py && python tests/test_solve_pack.py`
Expected: all routing scenarios pass; `test_solve_pack` still passes (it does not touch errands).

If `scenario_now_clamps_or_drops_todays_slot` fails because `_first_fit` returns a start after `now` that still fits before soccer, re-read the numbers: Home→Store 20, Store→Soccer 20, duration 30, soccer 16:00 → latest start 15:10; `now` 15:50 → no fit → the leg is dropped and the after-last or empty shape wins. That is the asserted behaviour.

- [ ] **Step 5: Hand back**

Report the diff summary and both test outputs. Claude reviews and commits.

---

### Task 3: Steering semantics in the pass

**Files:**
- Modify: `solver/matcher.py` (the functions from Task 2; small additions only)
- Test: `tests/test_errand_routing.py` (extend)

**Interfaces:**
- Consumes: Task 2's `insert_errands_globally`, `errand_window`.
- Produces: the precedence of spec §4.2 observable through placements and notes; no new names.

- [ ] **Step 1: Add the failing precedence and steer tests**

Append to `tests/test_errand_routing.py` before `SCENARIOS`:

```python
def _week_with_soccer_tue_and_thu():
    jeff = _driver('d1', 'Jeff')
    lorena = _driver('d2', 'Lorena')
    tue = _ev('soccer_tue', 1, 16, 'Soccer')
    thu = _ev('soccer_thu', 3, 16, 'Soccer')
    work = _ev('work_sat', 5, 9, 'Work', dur=4 * 60)
    base = _world({1: [tue], 3: [thu]}, [jeff, lorena], {'soccer_tue': 'd1', 'soccer_thu': 'd1'})
    return base, [jeff, lorena], {'d2': [work]}


def scenario_steer_not_this_day_moves_to_the_next_passing_leg():
    base, drivers, own = _week_with_soccer_tue_and_thu()
    d, r = _only(_place(base, [_errand(skip_dates=[DAYS[1]])], drivers, own)[0])
    check(d == DAYS[3] and r['inserted_before_event_id'] == 'soccer_thu', f"Thursday's leg: {d} {r}")


def scenario_steer_pick_a_day_pins_and_still_prefers_a_passing_leg():
    base, drivers, own = _week_with_soccer_tue_and_thu()
    d, r = _only(_place(base, [_errand(location='Pharmacy', pinned_date=DAYS[5])], drivers, own)[0])
    check(d == DAYS[5] and r['driver']['id'] == 'd2' and r['why']['kind'] == 'pinned'
          and r['why']['text'].startswith("the day you picked, on Lorena's way to Work"), f"{d} {r['why']}")
    d, r = _only(_place(base, [_errand(pinned_date=DAYS[6])], drivers, own)[0])
    check(d == DAYS[6] and r['why']['kind'] == 'pinned' and 'a trip from home' in r['why']['text'],
          f"a pinned empty day is a from-home trip that says so: {r['why']}")


def scenario_steer_pick_a_time_on_the_pinned_day():
    base, drivers, own = _week_with_soccer_tue_and_thu()
    d, r = _only(_place(base, [_errand(pinned_date=DAYS[6], pinned_start='09:00', pinned_end='11:00')], drivers, own)[0])
    st = datetime.datetime.fromisoformat(r['start_time'])
    check(d == DAYS[6] and st.time() == datetime.time(9, 0), f"09:00 on the pinned day: {st}")
    rows, notes = _place(base, [_errand(pinned_date=DAYS[6], pinned_start='20:50', pinned_end='21:00')], drivers, own)
    check(not rows and notes['er1']['reason'] == 'no_slot', f"a 10-minute window for a 30-minute errand: {notes}")


def scenario_steer_someone_else_overrides_standing_drivers_but_not_prohibitions():
    base, drivers, own = _week_with_soccer_tue_and_thu()
    d, r = _only(_place(base, [_errand(location='Pharmacy', required_drivers=['d1'], once_driver_id='d2')], drivers, own)[0])
    check(r['driver']['id'] == 'd2' and d == DAYS[5], f"once_driver wins over required_drivers: {d} {r['driver']['id']}")
    rows, notes = _place(base, [_errand(prohibited_drivers=['d2'], once_driver_id='d2')], drivers, own)
    check(not rows and notes['er1']['reason'] == 'no_driver' and 'Lorena' in notes['er1']['text'],
          f"a prohibited once-driver is a no_driver note naming them: {notes}")


def scenario_steer_back_to_automatic_is_the_plain_answer():
    base, drivers, own = _week_with_soccer_tue_and_thu()
    plain = _only(_place(base, [_errand()], drivers, own)[0])
    cleared = _only(_place(base, [_errand(skip_dates=[], pinned_date=None, pinned_start=None,
                                           pinned_end=None, once_driver_id=None)], drivers, own)[0])
    check(plain[0] == cleared[0] == DAYS[1] and plain[1]['start_time'] == cleared[1]['start_time'],
          "empty steer fields change nothing")


def scenario_precedence_pin_beats_window_weekday_and_overdue():
    base, drivers, own = _week_with_soccer_tue_and_thu()
    old = (NOW - datetime.timedelta(days=30)).timestamp()
    d, r = _only(_place(base, [_errand(starts_on=old, window_days=3, pinned_date=DAYS[4])], drivers, own)[0])
    check(d == DAYS[4], f"a pin outside an expired window still lands on the pin: {d}")
    d, r = _only(_place(base, [_errand(valid_days_of_week=[1], pinned_date=DAYS[4])], drivers, own)[0])
    check(d == DAYS[4], f"a pin on a non-valid weekday wins: {d}")
    rows, notes = _place(base, [_errand(pinned_date=str(MON - datetime.timedelta(days=3)))], drivers, own)
    check(not rows and notes['er1']['reason'] == 'pinned_day_passed', f"{notes}")
    rows, notes = _place(base, [_errand(pinned_date=str(MON + datetime.timedelta(days=30)))], drivers, own)
    check(not rows and notes['er1']['reason'] == 'pinned_day_not_in_range', f"{notes}")
    rows, notes = _place(base, [_errand(window_days=2, skip_dates=[DAYS[0], DAYS[1]])], drivers, own)
    check(not rows and notes['er1']['reason'] == 'every_day_skipped', f"{notes}")


def scenario_past_skip_dates_are_ignored_and_a_passed_pin_stays_a_note():
    base, drivers, own = _week_with_soccer_tue_and_thu()
    yesterday = str(MON - datetime.timedelta(days=2))
    d, r = _only(_place(base, [_errand(skip_dates=[yesterday, DAYS[1]])], drivers, own)[0])
    check(d == DAYS[3], f"a stale skip date is ignored, a live one honoured: {d}")


def scenario_a_cached_row_that_contradicts_the_steer_does_not_count():
    from services import storage
    with storage.db_lock:
        storage.daily_schedules_table.truncate()
    outside = str(MON + datetime.timedelta(days=10))
    storage.save_cached_daily_schedule(outside, {'scheduled_errands': [{
        'id': 'er1', 'driver': {'id': 'd1', 'name': 'Jeff'}, 'start': f'{outside}T10:00:00',
        'start_time': f'{outside}T10:00:00', 'end': f'{outside}T10:30:00', 'end_time': f'{outside}T10:30:00'}]}, 'h')
    base, drivers, own = _week_with_soccer_tue_and_thu()
    rows, _ = _place(base, [_errand(window_days=20)], drivers, own)
    check(not [r for d, r in rows if r['id'] == 'er1'], "a valid cached placement outside the solve holds")
    rows, _ = _place(base, [_errand(window_days=20, skip_dates=[outside])], drivers, own)
    check([r for d, r in rows if r['id'] == 'er1'], "a cached row on a skipped day does not hold")
    rows, _ = _place(base, [_errand(window_days=20, once_driver_id='d2')], drivers, own)
    check([r for d, r in rows if r['id'] == 'er1'], "a cached row with the wrong driver does not hold")
    with storage.db_lock:
        storage.daily_schedules_table.truncate()
```

- [ ] **Step 2: Run to see which fail**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_errand_routing.py`
Expected: most of the new scenarios already pass on Task 2's code because the precedence lives in `errand_window` and `_first_fit`. Any that fail name the gap; fix it in `errand_window`/`insert_errands_globally` with the smallest change (the likely one: the `no_driver` text must name the once-driver, and `pinned` kind must wrap `from_home` text as "the day you picked, a trip from home, N min each way").

- [ ] **Step 3: Make them pass, run the file again**

Expected: every scenario passes.

- [ ] **Step 4: Hand back**

Report which scenarios needed code and what changed.

---

### Task 4: Drive-time reader and bounded priming

**Files:**
- Modify: `solver/matcher.py` (`insert_errands_globally`: the unroutable check and the primer call), `services/maps.py` (no change expected; the pass calls `prime_matrix_cache(locations, ignore_age=True)`)
- Test: `tests/test_errand_routing.py` (extend)

**Interfaces:**
- Consumes: `maps.prime_matrix_cache(locations: list[str], ignore_age: bool)`, `maps.travel_cache_only_active()`, `storage.get_cached_travel_time`, `storage.UNROUTABLE`.
- Produces: `matcher._prime_errand_pairs(errand_loc, places, storage, maps) -> int` (number of primer calls made); `unroutable_location` notes.

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_errand_routing.py` before `SCENARIOS`:

```python
def scenario_unknown_ranks_last_grouped_or_not_and_says_so_alone():
    jeff, lorena = _driver('d1', 'Jeff'), _driver('d2', 'Lorena')
    far = _ev('far', 1, 16, 'Far')                 # (80,80): a known but long detour
    lost = _ev('lost', 2, 16, 'Nowhere')           # not on the grid: unknown legs
    base = _world({1: [far], 2: [lost]}, [jeff, lorena], {'far': 'd1', 'lost': 'd2'})
    # The grouped unknown candidate would win on numbers alone (cost - 9999).
    base_grouped = dict(base)
    rows, _ = _place(base_grouped, [_errand(location='Store', group_id='g1'),
                                    _errand(id='er2', doc_id=2, location='Store', group_id='g1')], [jeff, lorena])
    for d, r in rows:
        check(r['why']['kind'] != 'unknown_travel', f"a known candidate exists, so unknown never wins: {d} {r['why']}")
    base_only_unknown = _world({2: [lost]}, [lorena], {'lost': 'd2'})
    rows, _ = _place(base_only_unknown, [_errand(location='Elsewhere', window_days=3)], [lorena],
                     settings={'errand_dedicated_trip_mins': 25})
    d, r = _only(rows)
    check(r['why']['kind'] == 'unknown_travel' and r['travel_to_mins'] is None and r['travel_from_mins'] is None
          and r['why']['text'] == 'drive time unknown, check the address', f"{r}")


def scenario_no_location_and_unroutable_are_reported_not_placed():
    from services import storage
    jeff = _driver('d1', 'Jeff')
    base = _world({}, [jeff], {})
    rows, notes = _place(base, [_errand(location='')], [jeff])
    check(not rows and notes['er1']['reason'] == 'no_location', f"{notes}")
    storage.set_cached_travel_time('home', 'nowhere st', storage.UNROUTABLE)
    rows, notes = _place(base, [_errand(location='Nowhere St')], [jeff])
    check(not rows and notes['er1']['reason'] == 'unroutable_location', f"{notes}")


def scenario_priming_is_one_bounded_call_per_errand_and_none_under_cache_only():
    from services import maps
    calls = []
    real_prime, real_only = maps.prime_matrix_cache, maps.travel_cache_only_active
    maps.prime_matrix_cache = lambda locs, ignore_age=False: calls.append((sorted(locs), ignore_age))
    try:
        jeff = _driver('d1', 'Jeff')
        soccer = _ev('soccer', 1, 16, 'Soccer')
        base = _world({1: [soccer]}, [jeff], {'soccer': 'd1'})
        n = matcher._prime_errand_pairs('Store', {'Home', 'Soccer', 'Nowhere'}, __import__('services.storage', fromlist=['x']), maps)
        check(n == 1 and len(calls) == 1 and calls[0][1] is True and 'Store' in calls[0][0]
              and 'Nowhere' in calls[0][0], f"one planning-cache primer call with the errand's place in it: {calls}")
        calls.clear()
        n = matcher._prime_errand_pairs('Store', {'Home', 'Soccer'}, __import__('services.storage', fromlist=['x']), maps)
        check(n == 0 and not calls, "nothing to prime when every pair is already known")
        maps.travel_cache_only_active = lambda: True
        n = matcher._prime_errand_pairs('Store', {'Home', 'Nowhere'}, __import__('services.storage', fromlist=['x']), maps)
        check(n == 0 and not calls, "no fetch under cache-only mode")
        many = {f'P{i}' for i in range(60)}
        maps.travel_cache_only_active = lambda: False
        n = matcher._prime_errand_pairs('Store', many, __import__('services.storage', fromlist=['x']), maps)
        check(n == 3 and all(len(c[0]) <= 24 for c in calls) and all('Store' in c[0] for c in calls),
              f"60 places + the errand go in chunks of at most 24, each carrying the errand's place: {[len(c[0]) for c in calls]}")
    finally:
        maps.prime_matrix_cache, maps.travel_cache_only_active = real_prime, real_only
```

Note for the implementer: these tests still run with `matcher.errand_leg_minutes` stubbed to the grid, so `_prime_errand_pairs` must decide "known" through `errand_leg_minutes` (module lookup), not through storage directly. `storage.set_cached_travel_time(origin, destination, duration_mins)` (`storage.py:1103`) is the existing writer. `errand_leg_minutes` returns `None` for a stored `UNROUTABLE`, while the unroutable CHECK in the pass reads storage's distance cache directly (that is why the test writes through storage and stubs the grid: the grid says `None` for 'Nowhere St', storage says unroutable).

- [ ] **Step 2: Run to see them fail**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_errand_routing.py`
Expected: FAIL with `AttributeError: module 'solver.matcher' has no attribute '_prime_errand_pairs'`, and `unroutable_location` is not produced.

- [ ] **Step 3: Implement**

In `solver/matcher.py` add after `errand_leg_minutes`:

```python
def _errand_location_unroutable(loc, storage):
    """True when ANY cached pair touching this place is recorded unroutable:
    a Mapbox answer that this address cannot be driven to."""
    try:
        with storage.db_lock:
            storage._init_distance_mem_cache()
            cache = storage._distance_mem_cache
    except Exception:
        return False
    key = str(loc).strip().lower()
    for (o, d), row in list(cache.items()):
        if key in (o, d) and row.get('duration_mins', row.get('minutes')) == storage.UNROUTABLE:
            return True
    return False


def _prime_errand_pairs(errand_loc, places, storage, maps, chunk=24):
    """Spec §2.1: one bounded primer per errand into the planning cache, only
    for places whose pair with the errand is unknown, in chunks of at most
    `chunk` locations each carrying the errand's place; nothing under
    cache-only mode. Returns the number of primer calls."""
    import inspect as _inspect
    me = _inspect.getmodule(_prime_errand_pairs)
    if maps.travel_cache_only_active():
        return 0
    missing = sorted(p for p in places if p and p.strip() and p != errand_loc
                     and (me.errand_leg_minutes(errand_loc, p) is None or me.errand_leg_minutes(p, errand_loc) is None))
    if not missing:
        return 0
    calls = 0
    step = max(1, chunk - 1)
    for i in range(0, len(missing), step):
        try:
            maps.prime_matrix_cache([errand_loc] + missing[i:i + step], ignore_age=True)
        except Exception as ex:   # never let a routing purchase take the refresh down
            print(f"[errands] primer failed: {ex}")
        calls += 1
    return calls
```

Check `_init_distance_mem_cache` and `_distance_mem_cache` exist in `services/storage.py` (they are used at `storage.py:1088`); if the mem cache can be empty before first use, the `_init_` call fills it.

In `insert_errands_globally`, replace the `# (Task 4 inserts the unroutable check and the bounded primer here.)` comment with:

```python
        if _errand_location_unroutable(loc, storage):
            notes[eid] = {'reason': 'unroutable_location', 'text': ERRAND_UNPLACED_TEXT['unroutable_location']}
            continue
        places = set()
        for d_str, by_driver in routes.items():
            for d_id, stops in by_driver.items():
                places.update(s.location for s in stops if s.location)
                home = getattr(driver_map[d_id], 'home_location', None)
                if home:
                    places.add(home)
        from services import maps as _maps
        _prime_errand_pairs(loc, places, storage, _maps)
```

Place this after the `no_location` check and before `duration` is computed.

- [ ] **Step 4: Run the file**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_errand_routing.py`
Expected: all scenarios pass.

- [ ] **Step 5: Hand back**

---

### Task 5: Wire the refresh and the errands API

**Files:**
- Modify: `main.py:21725` (the pass call), `main.py` after Pass 3's cache writes (~`:21810`, before `return final_data` of `_refresh_schedule_logic_impl`), `main.py:18263-18290` (`GET /api/errands`), `main.py:18368-18390` (`PUT /api/errands/{doc_id}`)
- Test: `tests/test_errand_routing_api.py` (extend)

**Interfaces:**
- Consumes: Task 1 storage helpers, Task 2's tuple return, `STEER_FIELDS`.
- Produces: `GET /api/errands` rows carry `placement: {start_time, end_time, driver: {id, name}, why}` or `unplaced: {reason, text, generation}`, and `generation: int` on every row; `PUT /api/errands/{doc_id}` forgets placements when a routing field changes and completes through `storage.complete_errand`; module constant `main.ERRAND_ROUTING_FIELDS`.

- [ ] **Step 1: Add the failing API tests**

Append to `tests/test_errand_routing_api.py` before `SCENARIOS`:

```python
def _client():
    from fastapi.testclient import TestClient
    import main
    main.trigger_background_refresh = lambda *a, **k: None   # never solve in a unit test
    return TestClient(main.app), main


def _headers():
    """No token: with no `auth_enforce` setting the guard is in audit mode
    (`services/auth.enforcing()` reads absent as False), so every route
    answers. Kept as a hook so a later enforcing fixture has one place to add
    a parent token."""
    return {}


def scenario_get_errands_carries_placement_or_unplaced_and_the_generation():
    _fresh()
    client, main = _client()
    storage.add_errand(_errand(id='e-sched'))
    storage.add_errand(_errand(id='e-lost'))
    storage.save_cached_daily_schedule('2026-10-27', {'scheduled_errands': [_row('e-sched', '2026-10-27')]}, 'h')
    storage.save_errand_placement_notes({'e-lost': {'reason': 'no_slot', 'text': 'no drive in its window has room for it', 'generation': 4}})
    storage.set_app_state('schedule_generation', 4)
    res = client.get('/api/errands', headers=_headers())
    check(res.status_code == 200, f"GET /api/errands {res.status_code}: {res.text[:200]}")
    rows = {r['id']: r for r in res.json()}
    sched = rows['e-sched']
    check(sched['placement']['why']['text'] == "on Jeff's way to Soccer, +6 min"
          and sched['placement']['driver'] == {'id': 'd1', 'name': 'Jeff'}
          and sched['placement']['start_time'] == '2026-10-27T16:10:00'
          and sched['scheduled_start'] == '2026-10-27T16:10:00' and 'unplaced' not in sched, f"{sched}")
    lost = rows['e-lost']
    check(lost['unplaced']['reason'] == 'no_slot' and 'placement' not in lost, f"{lost}")
    check(all(r['generation'] == 4 for r in rows.values()), "every row carries the generation")


def scenario_put_rejects_a_bad_date_and_a_steer_forgets_placements():
    _fresh()
    client, main = _client()
    doc_id = storage.add_errand(_errand(id='e-steer'))
    storage.save_cached_daily_schedule('2026-10-27', {'scheduled_errands': [_row('e-steer', '2026-10-27')]}, 'h')
    body = dict(storage.get_errand_by_id(doc_id))
    body['pinned_date'] = 'next tuesday'
    res = client.put(f'/api/errands/{doc_id}', json=body, headers=_headers())
    check(res.status_code == 422, f"a malformed date is refused: {res.status_code}")
    body['pinned_date'] = '2026-10-31'
    res = client.put(f'/api/errands/{doc_id}', json=body, headers=_headers())
    check(res.status_code == 200, f"{res.status_code} {res.text[:200]}")
    check(storage.get_all_scheduled_errand_rows() == {}, "the stale placement is forgotten")
    check(storage.get_errand_by_id(doc_id)['pinned_date'] == '2026-10-31', "the pin is stored")
    storage.save_cached_daily_schedule('2026-10-31', {'scheduled_errands': [_row('e-steer', '2026-10-31')]}, 'h')
    body = dict(storage.get_errand_by_id(doc_id))
    body['title'] = 'Costco run (big)'
    client.put(f'/api/errands/{doc_id}', json=body, headers=_headers())
    check(set(storage.get_all_scheduled_errand_rows()) == {'e-steer'}, "a title-only edit keeps the placement")


def scenario_completing_twice_mints_nothing_through_put():
    _fresh()
    client, main = _client()
    anchor = time.mktime(datetime.datetime(2026, 10, 5, 0, 0).timetuple())
    doc_id = storage.add_errand(_errand(id='e-wk', recurrence_rule='weekly', starts_on=anchor, once_driver_id='d2'))
    body = dict(storage.get_errand_by_id(doc_id))
    body['is_completed'] = True
    client.put(f'/api/errands/{doc_id}', json=body, headers=_headers())
    rows = storage.get_all_errands()
    check(len(rows) == 2, f"one successor: {len(rows)}")
    done = storage.get_errand_by_id(doc_id)
    check(done['is_completed'] and done['once_driver_id'] is None, "completed through complete_errand")
    succ = next(r for r in rows if r['doc_id'] != doc_id)
    check(abs(succ['starts_on'] - (anchor + WEEK)) < 1 and succ['once_driver_id'] is None, f"{succ}")
    body = dict(storage.get_errand_by_id(doc_id))
    client.put(f'/api/errands/{doc_id}', json=body, headers=_headers())
    check(len(storage.get_all_errands()) == 2, "a second completed PUT mints nothing")
```

Auth is in audit mode in the test process (no `auth_enforce` setting), so no token is needed; `_headers()` is a hook only.

- [ ] **Step 2: Run to see them fail**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_errand_routing_api.py`
Expected: `scenario_get_errands_...` fails on `KeyError: 'placement'`.

- [ ] **Step 3: Wire main.py**

At `main.py:21725` replace the pass call:

```python
    # Pass 2: Global Errand Placement (errands ride the route). The drivers'
    # own events ride along so a work day is a leg, not a blank.
    if draft:
        scheduled_errands_by_date, errand_notes = {}, {}
    else:
        scheduled_errands_by_date, errand_notes = matcher.insert_errands_globally(
            base_schedules, errands, drivers, trip_metadata=trip_metadata,
            driver_events=driver_events_map, settings=storage.get_settings())
```

After the Pass 3 loop finishes writing every day's cache (just before `return final_data`, the last statement of `_refresh_schedule_logic_impl`), add:

```python
    # Errands: what could not be placed, and a generation the steer sheet can
    # wait for. Only the routine refresh writes them — a custom-range or draft
    # solve must not clear a note that belongs to the week it did not look at.
    if not draft and start_date_str is None and end_date_str is None:
        gen = storage.bump_schedule_generation()
        for n in errand_notes.values():
            n['generation'] = gen
        storage.save_errand_placement_notes(errand_notes)
```

If `final_data` is built before that point, insert the block before the `return`. Confirm `start_date_str`/`end_date_str` are the impl's own parameters (they are, `main.py:20400`).

In `GET /api/errands` (`:18263`) replace the loop body to merge placement:

```python
    rows_by_id = storage.get_all_scheduled_errand_rows()
    notes = storage.get_errand_placement_notes()
    generation = storage.get_schedule_generation()
    today = datetime.date.today().isoformat()
    res = []
    for e in raw:
        obj = Errand(**e).model_dump()
        obj['doc_id'] = e.get('doc_id')
        obj['skip_dates'] = [d for d in (obj.get('skip_dates') or []) if d >= today]
        obj['generation'] = generation
        row = rows_by_id.get(obj['id'])
        if row:
            obj['scheduled_start'] = row.get('start') or row.get('start_time')
            drv = row.get('driver') or {}
            obj['placement'] = {'start_time': row.get('start_time') or row.get('start'),
                                'end_time': row.get('end_time') or row.get('end'),
                                'driver': {'id': drv.get('id'), 'name': drv.get('name')},
                                'why': row.get('why') or {}}
        elif obj['id'] in notes and not obj.get('is_completed'):
            obj['unplaced'] = notes[obj['id']]
        obj['shopping_lists'] = [
            {'id': l['id'], 'name': l['name'], 'open_count': open_counts.get(l['id'], 0)}
            for l in storage.find_shopping_lists_for_errand(obj)]
        res.append(obj)
    return res
```

Keep `check_past_due_errands()` and the `open_counts` block above it as they are; drop the old `errand_schedules = storage.get_all_scheduled_errands()` line.

Replace the `PUT /api/errands/{doc_id}` body (`:18369-18390`):

```python
ERRAND_ROUTING_FIELDS = ('location', 'duration_mins', 'tolerance_mins', 'buffer_mins',
                         'time_window_start', 'time_window_end', 'valid_days_of_week',
                         'window_days', 'starts_on', 'recurrence_rule', 'required_drivers',
                         'allowed_drivers', 'prohibited_drivers', 'required_passengers',
                         'prohibited_passengers', 'group_id', 'priority') + STEER_FIELDS


@app.put("/api/errands/{doc_id}")
def update_errand(doc_id: int, errand: Errand, background_tasks: BackgroundTasks):
    old = storage.get_errand_by_id(doc_id)
    if not old:
        raise HTTPException(status_code=404, detail="Errand not found")
    incoming = errand.model_dump()
    incoming.pop('doc_id', None)
    if incoming.get('is_completed') and not old.get('is_completed'):
        # THE completion path: clears the one-shot steer and mints the
        # recurring successor anchored on the cycle just completed (spec §4.3).
        storage.complete_errand(doc_id, incoming)
    elif incoming.get('is_completed') and old.get('is_completed'):
        storage.update_errand(doc_id, incoming)       # already done; nothing mints
    else:
        storage.update_errand(doc_id, incoming)
    if any(old.get(f) != incoming.get(f) for f in ERRAND_ROUTING_FIELDS):
        storage.forget_errand_placements(old.get('id'))
    background_tasks.add_task(trigger_background_refresh)
    return {"status": "updated"}
```

Import `STEER_FIELDS` with the other `models.schemas` imports at the top of `main.py`. Remove the old inline recurrence-copy code the handler had (it moved into `complete_errand`).

- [ ] **Step 4: Run the API tests and the neighbours**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_errand_routing_api.py && python tests/test_errand_lists_render.py && python tests/test_schedule_timeline.py`
Expected: all pass.

- [ ] **Step 5: Hand back**

---

### Task 6: The agent path

**Files:**
- Modify: `services/agent_tools_v2.py:6506-6527` (`UpdateErrandTool`), `:7810-7849` (`handle_update_errand`), `:7851-7854` (`handle_get_errands`)
- Test: `tests/test_errand_routing_api.py` (extend)

**Interfaces:**
- Consumes: `storage.get_errand_by_id`, `storage.complete_errand`, `storage.update_errand`, `storage.forget_errand_placements`, `storage.get_all_scheduled_errand_rows`, `storage.get_errand_placement_notes`, `storage.get_schedule_generation`.
- Produces: `UpdateErrandTool` fields `skip_date: Optional[str]`, `pinned_date: Optional[str]`, `pinned_start: Optional[str]`, `pinned_end: Optional[str]`, `once_driver_id: Optional[str]`, `clear_steer: bool = False`; `handle_get_errands` rows carry `placement`/`unplaced`/`generation` exactly as the API does.

- [ ] **Step 1: Add the failing agent tests**

Append to `tests/test_errand_routing_api.py` before `SCENARIOS`:

```python
def scenario_the_agent_updates_by_uuid_or_doc_id_and_steers():
    _fresh()
    from services import agent_tools_v2 as tools
    doc_id = storage.add_errand(_errand(id='e-agent'))
    storage.save_cached_daily_schedule('2026-10-27', {'scheduled_errands': [_row('e-agent', '2026-10-27')]}, 'h')
    out = tools.handle_update_errand({'errand_id': 'e-agent', 'skip_date': '2026-10-27'})
    check(out.get('status') == 'success', f"by uuid: {out}")
    check(storage.get_errand_by_id(doc_id)['skip_dates'] == ['2026-10-27'], "skip_date appended")
    check(storage.get_all_scheduled_errand_rows() == {}, "a steer through the agent forgets the placement")
    out = tools.handle_update_errand({'errand_id': str(doc_id), 'pinned_date': '2026-10-31',
                                      'pinned_start': '09:00', 'once_driver_id': 'd2'})
    e = storage.get_errand_by_id(doc_id)
    check(out.get('status') == 'success' and e['pinned_date'] == '2026-10-31' and e['pinned_start'] == '09:00'
          and e['once_driver_id'] == 'd2', f"by doc_id string: {out} {e}")
    out = tools.handle_update_errand({'errand_id': 'e-agent', 'pinned_date': 'friday'})
    check(out.get('status') == 'error' and 'date' in out.get('message', '').lower(), f"a bad date is refused in words: {out}")
    out = tools.handle_update_errand({'errand_id': 'e-agent', 'clear_steer': True})
    e = storage.get_errand_by_id(doc_id)
    check(e['skip_dates'] == [] and e['pinned_date'] is None and e['pinned_start'] is None and e['once_driver_id'] is None,
          f"clear_steer clears all four: {e}")
    out = tools.handle_update_errand({'errand_id': 'e-agent', 'is_completed': True})
    check(out.get('status') == 'success' and storage.get_errand_by_id(doc_id)['is_completed'], "completion works")
    check(tools.handle_update_errand({'errand_id': 'ghost'}).get('status') == 'error', "unknown id is an error result")


def scenario_skip_date_is_idempotent():
    _fresh()
    from services import agent_tools_v2 as tools
    storage.add_errand(_errand(id='e-twice'))
    tools.handle_update_errand({'errand_id': 'e-twice', 'skip_date': '2026-10-27'})
    tools.handle_update_errand({'errand_id': 'e-twice', 'skip_date': '2026-10-27'})
    check(storage.get_errand_by_id('e-twice')['skip_dates'] == ['2026-10-27'], "appended once")


def scenario_the_agent_reads_the_same_placement_the_page_does():
    _fresh()
    from services import agent_tools_v2 as tools
    storage.add_errand(_errand(id='e-read'))
    storage.save_cached_daily_schedule('2026-10-27', {'scheduled_errands': [_row('e-read', '2026-10-27')]}, 'h')
    storage.set_app_state('schedule_generation', 9)
    out = tools.handle_get_errands({})
    row = next(r for r in out['errands'] if r['id'] == 'e-read')
    check(row['placement']['why']['text'] == "on Jeff's way to Soccer, +6 min" and row['generation'] == 9, f"{row}")
    schema = tools.UpdateErrandTool.model_json_schema()['properties']
    for f in ('skip_date', 'pinned_date', 'pinned_start', 'pinned_end', 'once_driver_id', 'clear_steer'):
        check(f in schema, f"the tool declares {f}")
```

- [ ] **Step 2: Run to see them fail**

Expected: `handle_update_errand` returns `{'status': 'error', 'message': 'Errand not found.'}` or raises `AttributeError` on `storage.get_errand`.

- [ ] **Step 3: Implement**

`UpdateErrandTool` gains, after `group_id`:

```python
    skip_date: Optional[str] = Field(default=None, description="A day (YYYY-MM-DD) this errand must NOT land on; added to its skip list. 'Not Thursday.'")
    pinned_date: Optional[str] = Field(default=None, description="The one day (YYYY-MM-DD) this errand must land on this cycle. 'Put it on Saturday.'")
    pinned_start: Optional[str] = Field(default=None, description="With pinned_date: earliest HH:MM that day.")
    pinned_end: Optional[str] = Field(default=None, description="With pinned_date: latest HH:MM it may end that day.")
    once_driver_id: Optional[str] = Field(default=None, description="The driver who runs it this cycle only. 'Let Lorena do it.'")
    clear_steer: bool = Field(default=False, description="Back to automatic: clears skip dates, the pinned day and time, and the once-driver.")
```

Replace `handle_update_errand`:

```python
def handle_update_errand(args: dict) -> dict:
    from services import storage
    from models.schemas import Errand, STEER_FIELDS
    errand = storage.get_errand_by_id(args.get('errand_id'))
    if not errand:
        return {"status": "error", "message": "Errand not found."}
    doc_id = errand['doc_id']

    if args.get('is_completed'):
        storage.complete_errand(doc_id)
        return {"status": "success", "message": "Errand marked as completed and rescheduled if recurring."}

    update_data = {}
    if args.get('title'): update_data['title'] = args.get('title')
    if args.get('duration_mins'): update_data['duration_mins'] = args.get('duration_mins')
    if args.get('location'):
        from services import maps
        update_data['location'] = maps.resolve_routable_location(args.get('location'))
    if args.get('starts_on'): update_data['starts_on'] = args.get('starts_on')
    for field in ['allowed_drivers', 'required_drivers', 'prohibited_drivers',
                  'allowed_passengers', 'required_passengers', 'prohibited_passengers']:
        if args.get(field) is not None:
            update_data[field] = args.get(field)
    for field in ['time_window_start', 'time_window_end', 'group_id']:
        if args.get(field) is not None:
            update_data[field] = args.get(field) or None
    for field in ['buffer_mins', 'tolerance_mins']:
        if args.get(field) is not None:
            update_data[field] = args.get(field)

    # Steering (spec §4.6): one-shot fields, validated by the Errand model.
    if args.get('clear_steer'):
        update_data.update({'skip_dates': [], 'pinned_date': None, 'pinned_start': None,
                            'pinned_end': None, 'once_driver_id': None})
    else:
        if args.get('skip_date'):
            days = list(errand.get('skip_dates') or [])
            if args['skip_date'] not in days:
                days.append(args['skip_date'])
            update_data['skip_dates'] = days
        for field in ['pinned_date', 'pinned_start', 'pinned_end', 'once_driver_id']:
            if args.get(field) is not None:
                update_data[field] = args.get(field) or None
    if not update_data:
        return {"status": "success", "message": "Nothing to change."}
    merged = dict(errand)
    merged.pop('doc_id', None)
    merged.update(update_data)
    try:
        clean = Errand(**merged).model_dump()
    except Exception as ex:
        return {"status": "error", "message": f"That is not a valid date or time: {ex}"}
    storage.update_errand(doc_id, clean)
    if any(k in update_data for k in STEER_FIELDS + ('location', 'duration_mins', 'time_window_start',
                                                      'time_window_end', 'required_drivers', 'allowed_drivers',
                                                      'prohibited_drivers', 'starts_on')):
        storage.forget_errand_placements(errand['id'])
    return {"status": "success", "message": "Errand updated."}
```

Replace `handle_get_errands`:

```python
def handle_get_errands(args: dict) -> dict:
    """The same rows the Errands page reads, placement and all (the owning
    module rule: a number Argyle says comes from the row, never a guess)."""
    from services import storage
    rows = storage.get_all_scheduled_errand_rows()
    notes = storage.get_errand_placement_notes()
    gen = storage.get_schedule_generation()
    out = []
    for e in storage.get_all_errands():
        e = dict(e)
        e['generation'] = gen
        row = rows.get(e.get('id'))
        if row:
            drv = row.get('driver') or {}
            e['placement'] = {'start_time': row.get('start_time') or row.get('start'),
                              'end_time': row.get('end_time') or row.get('end'),
                              'driver': {'id': drv.get('id'), 'name': drv.get('name')},
                              'why': row.get('why') or {}}
        elif e.get('id') in notes and not e.get('is_completed'):
            e['unplaced'] = notes[e['id']]
        out.append(e)
    return {"status": "success", "errands": out}
```

- [ ] **Step 4: Run**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_errand_routing_api.py && python tests/test_chat_actions.py && python tests/test_agent_v2_bridge.py && python tests/test_registry_parity.py`
Expected: all pass.

- [ ] **Step 5: Hand back**

---

### Task 7: The setting's drawer control

**Files:**
- Modify: `templates/errands.html:138-140` (the Errands settings drawer)
- Test: `tests/test_settings_registry.py` (existing, must go green), `tests/test_errand_routing_api.py` (extend: round trip)

**Interfaces:**
- Consumes: `settings_section` macro (`templates/components/settings_drawer.html:61`), `chfSettingsDrawer()`.
- Produces: an element `id="errand-settings"` carrying a number input bound to `errand_dedicated_trip_mins` and saving through `/api/settings`.

- [ ] **Step 1: Add the failing round-trip test**

Append to `tests/test_errand_routing_api.py`:

```python
def scenario_the_setting_round_trips_through_the_api_and_has_a_control():
    _fresh()
    client, main = _client()
    res = client.post('/api/settings', json={'errand_dedicated_trip_mins': 40}, headers=_headers())
    check(res.status_code == 200, f"POST /api/settings {res.status_code}: {res.text[:200]}")
    check(storage.get_settings().get('errand_dedicated_trip_mins') == 40, "stored")
    res = client.post('/api/settings', json={'errand_dedicated_trip_mins': 500}, headers=_headers())
    check(res.status_code == 422, f"out of bounds refused: {res.status_code}")
    from services import settings_registry as reg
    ui = reg.audit_ui()
    missing = [m for m in ui.get('unreachable', []) if m.get('key') == 'errand_dedicated_trip_mins']
    check(not missing, f"the Errands drawer carries the control: {missing}")
```

Check `/api/settings`'s method in `main.py:19077` (it is `update_settings(settings: Settings, ...)`; confirm whether it is `@app.post` or `@app.put` and use that).

- [ ] **Step 2: Run to see it fail**

Expected: the `audit_ui` check fails (no control yet); the POST may already pass.

- [ ] **Step 3: Add the section to the drawer**

In `templates/errands.html` inside the `{% call settings_drawer('errands', 'Errands') %}` block, BEFORE the `{% include 'components/errand_rules.html' %}`:

```html
        {% call settings_section('errand-settings', 'Where errands land') %}
        <div class="bg-gray-900 rounded-xl p-4" x-data="errandRoutingSettings()" x-init="load()">
            <label class="block text-gray-400 mb-1 text-sm" for="errand-dedicated-trip-mins">Prefer errands on the way</label>
            <div class="flex items-center gap-3">
                <input id="errand-dedicated-trip-mins" type="number" min="0" max="120" step="5"
                    x-model.number="settings.errand_dedicated_trip_mins" @change="save()"
                    class="w-28 bg-gray-800 border border-gray-600 rounded-lg p-2 text-white">
                <span class="text-sm text-gray-400">extra minutes a passing drive may add before a separate trip from home is worth it</span>
            </div>
            <p class="text-xs text-gray-500 mt-2">Errands land on a drive someone already makes. A trip from home only wins when every passing drive would add more than this.</p>
        </div>
        {% endcall %}
```

And in the page's script block (near `errandListsLogic` usage), add:

```html
<script>
    function errandRoutingSettings() {
        return {
            settings: { errand_dedicated_trip_mins: 25 },
            async load() {
                try {
                    const r = await fetch('api/settings');
                    const s = r.ok ? await r.json() : {};
                    if (typeof s.errand_dedicated_trip_mins === 'number') this.settings.errand_dedicated_trip_mins = s.errand_dedicated_trip_mins;
                } catch (e) { }
            },
            async save() {
                const v = Math.max(0, Math.min(120, parseInt(this.settings.errand_dedicated_trip_mins, 10) || 0));
                this.settings.errand_dedicated_trip_mins = v;
                try {
                    const r = await fetch('api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                           body: JSON.stringify({ errand_dedicated_trip_mins: v }) });
                    if (!r.ok) showGlobalAlert('Could not save that.');
                } catch (e) { showGlobalAlert('Could not save that.'); }
            },
        };
    }
</script>
```

Match the `/api/settings` method to what `main.py` declares, and the fetch path style other scripts on `errands.html` use (`api/...` relative, as `saveEdit` does). Then run `python tools/build_tailwind.py`.

- [ ] **Step 4: Run**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_errand_routing_api.py && python tests/test_settings_registry.py && python tests/test_template_js.py`
Expected: all pass, the registry's UI audit included.

- [ ] **Step 5: Hand back**

---

### Task 8: The Errands page — why line, unplaced line, Steer sheet, editor fields

**Files:**
- Modify: `templates/components/errand_lists.html:106-140` (`errand_row`), `:204-310` (`errandListsLogic`)
- Modify: `templates/errands.html` edit modal (`:280-300` next to the time-window inputs) and `saveEdit` (`:773-810`), `populate` (`:747-760`)
- Test: `tests/test_errand_lists_render.py` (extend)

**Interfaces:**
- Consumes: `/api/errands` rows with `placement`, `unplaced`, `generation`, steer fields; `promptChoice(title, message, [{label, value}])`.
- Produces: `errandListsLogic().steerErrand(e)`, `.whyLabel(e)`, `.isSteered(e)`, `.replanning` (a `Set` of errand ids), `.steerChoices` constants `STEER_WINDOWS = {morning: ['08:00','12:00'], midday: ['11:00','14:00'], afternoon: ['14:00','17:00'], evening: ['17:00','20:00']}` on `window.ChfErrandSteer` so the PWA (Task 9) reuses them.

- [ ] **Step 1: Read the existing render test's harness**

`tests/test_errand_lists_render.py` renders `errands.html` once under jsdom (`HARNESS`, run by `_run()`), feeds `TASKS`/`ERRANDS` through a fake `fetch`, and prints ONE JSON object (`errors`, `body` text, `checkboxes`, `editButtons`, `wrote`, `cards`). Cards are built in the probe with `card('errandListCard', cfg)` and asserted on their LOGIC (no DOM). New scenarios extend that JSON and read `_run()`.

- [ ] **Step 2: Add the failing render tests**

Extend the probe's `console.log(JSON.stringify({...}))` in `HARNESS` with three more keys:

```javascript
    steerButtons: [...doc.querySelectorAll('button')].map(txt).filter(t => t === 'Steer').length,
    cardWhy: card('errandListCard', {}).whyLabel(data.errands.find(e => e.id === 'e4')),
    cardHasSteer: typeof card('errandListCard', {}).steerErrand === 'function',
```

Extend `ERRANDS` with one scheduled and one unplaced row:

```python
ERRANDS.extend([
    {'id': 'e4', 'doc_id': 4, 'title': 'Costco run', 'location': 'Costco', 'duration_mins': 30,
     'priority': 2, 'status': 'pending', 'is_completed': False, 'starts_on': 1600000000,
     'shopping_lists': [], 'scheduled_start': '2026-10-27T16:10:00', 'generation': 3,
     'skip_dates': ['2026-10-28'], 'pinned_date': None, 'pinned_start': None, 'pinned_end': None, 'once_driver_id': None,
     'placement': {'start_time': '2026-10-27T16:10:00', 'end_time': '2026-10-27T16:40:00',
                   'driver': {'id': 'd1', 'name': 'Jeff'},
                   'why': {'kind': 'on_the_way', 'detour_mins': 6, 'driver_name': 'Jeff',
                           'leg': {'from': 'Home', 'to': 'Soccer'}, 'text': "on Jeff's way to Soccer, +6 min"}}},
    {'id': 'e5', 'doc_id': 5, 'title': 'Return the router', 'location': 'Nowhere St', 'duration_mins': 20,
     'priority': 2, 'status': 'pending', 'is_completed': False, 'starts_on': 1600000000,
     'shopping_lists': [], 'generation': 3, 'skip_dates': [], 'pinned_date': None, 'pinned_start': None,
     'pinned_end': None, 'once_driver_id': None,
     'unplaced': {'reason': 'unroutable_location', 'text': 'the address could not be routed, check it', 'generation': 3}},
])


def scenario_the_page_row_says_why_and_offers_steer_the_card_only_says_why():
    got = _run()
    if got is None:
        return
    body = got['body']
    check("on Jeff's way to Soccer, +6 min" in body, "the why line is on the page row")
    check('steered' in body.lower(), "a steered errand (skip_dates set) draws its chip")
    check('could not be routed' in body, "an unplaced errand says why")
    # One scheduled errand (e4) offers Steer; the unplaced e5 is not steered and
    # not placed, so it offers Edit (the fix) and no Steer.
    check(got['steerButtons'] == 1, f"exactly one Steer button on the page: {got['steerButtons']}")
    check(got['cardWhy'] == "on Jeff's way to Soccer, +6 min", f"a card knows the why line: {got['cardWhy']!r}")
    # A card never DRAWS Steer: board_tile_body renders the macros with edit='null',
    # and the Steer template is gated on the edit expression (a markup fact).
    comp = open(os.path.join(TPL, 'components', 'errand_lists.html'), encoding='utf-8').read()
    steer_tpl = comp[comp.index('steerErrand(e)') - 400:comp.index('steerErrand(e)')]
    check('!!({{ edit }})' in steer_tpl, "the Steer button is gated on the page's edit expression")


def scenario_the_steer_sheet_writes_the_whole_record_through_put():
    """Run the logic under node: steerErrand(e4) with a stubbed promptChoice
    answering 'skip_today' sends PUT /api/errands/4 with the whole row and
    skip_dates grown by the scheduled day."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from test_moment_media_token import _function_text, _run_node
    comp = open(os.path.join(TPL, 'components', 'errand_lists.html'), encoding='utf-8').read()
    logic = _function_text(comp, 'function errandListsLogic(apiBase)')
    got = _run_node("var window = globalThis; var ERRANDS = " + json.dumps(ERRANDS) + r""";
window.ChfErrandSteer = { STEER_WINDOWS: { morning: ['08:00','12:00'], midday: ['11:00','14:00'], afternoon: ['14:00','17:00'], evening: ['17:00','20:00'] } };
var showGlobalAlert = () => {};
var setTimeout = (fn, ms) => 0;   // the replan poll never fires in the probe
""" + logic + r"""
(async () => {
  const L = errandListsLogic('');
  L.errands = ERRANDS;
  const puts = [];
  globalThis.fetch = async (url, init) => {
    if (init && init.method === 'PUT') { puts.push({url, body: JSON.parse(init.body)}); return {ok: true, json: async () => ({status: 'updated'})}; }
    return {ok: true, json: async () => ERRANDS};
  };
  globalThis.promptChoice = async (title, msg, opts) => (opts.find(o => o.value === 'skip_today') || {}).value || null;
  await L.steerErrand(ERRANDS.find(e => e.id === 'e4'));
  console.log(JSON.stringify({puts, replanning: Array.from(L.replanning)}));
})();
""")
    check(len(got['puts']) == 1 and got['puts'][0]['url'].endswith('api/errands/4'), f"{got}")
    body = got['puts'][0]['body']
    check(body['title'] == 'Costco run' and body['location'] == 'Costco' and body['duration_mins'] == 30,
          "the whole record goes back, not a steer-only fragment")
    check('placement' not in body and 'generation' not in body and 'shopping_lists' not in body,
          "read-only keys are stripped before the PUT")
    check(sorted(body['skip_dates']) == ['2026-10-27', '2026-10-28'], f"the scheduled day joins the skip list: {body['skip_dates']}")
    check('e4' in got['replanning'], "the row is marked replanning until the generation moves")
```

`_function_text` and `_run_node` come from `tests/test_moment_media_token.py` (brace-matched extraction, node run, last stdout line as JSON). The extracted `errandListsLogic` must therefore not reference page globals other than `fetch`, `promptChoice`, `showGlobalAlert`, `setTimeout`, `window` and `apiBase`.

- [ ] **Step 3: Run to see them fail**

Expected: the why line is absent; `steerErrand` undefined.

- [ ] **Step 4: Implement the component**

In `errand_row` (`errand_lists.html:106-140`) replace the scheduled span and add the why/unplaced/chip lines and the Steer button:

```html
                                    <span x-show="listShow('when') && e.placement && !e.is_completed"
                                        class="text-green-400 font-medium"
                                        x-text="'✓ ' + scheduledLabel(e) + (whyLabel(e) ? ' · ' + whyLabel(e) : '')"></span>
                                    <span x-show="listShow('when') && !e.placement && e.scheduled_start && !e.is_completed"
                                        class="text-green-400 font-medium" x-text="'✓ ' + scheduledLabel(e)"></span>
                                    <span x-show="e.unplaced && !e.is_completed" class="text-amber-400 font-medium"
                                        x-text="'⚠ ' + ((e.unplaced || {}).text || 'not placed')"></span>
                                    <span x-show="isSteered(e)" class="px-1.5 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 text-[10px] font-bold uppercase tracking-wider">steered</span>
                                    <span x-show="replanning.has(e.id)" class="text-blue-300 italic">Replanning…</span>
```

and after the Edit button template:

```html
                            <template x-if="!!({{ edit }}) && {{ interactive }} && (e.placement || isSteered(e)) && !e.is_completed">
                                <button @click="steerErrand(e)" title="Steer: not this day, pick a day or time, someone else"
                                    class="text-xs px-2 py-1 rounded bg-gray-700 hover:bg-gray-600 text-indigo-200 shrink-0">Steer</button>
                            </template>
```

(The `edit` macro argument is `'null'` for cards, so `!!(null)` keeps Steer off every card without a new argument.)

In `errandListsLogic(apiBase)` add, after `scheduledLabel`:

```javascript
            replanning: new Set(),
            whyLabel(e) { return ((e.placement || {}).why || {}).text || ''; },
            isSteered(e) {
                return !!((e.skip_dates || []).length || e.pinned_date || e.pinned_start || e.pinned_end || e.once_driver_id);
            },
            _dayChoices(days = 14) {
                const out = [];
                const d = new Date(); d.setHours(0, 0, 0, 0);
                for (let i = 0; i < days; i++) {
                    const x = new Date(d); x.setDate(d.getDate() + i);
                    const iso = `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`;
                    out.push({ value: iso, label: x.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' }) });
                }
                return out;
            },
            async _driverChoices() {
                try {
                    const r = await fetch(`${apiBase}api/drivers`);
                    const ds = r.ok ? await r.json() : [];
                    return ds.filter(d => !d.is_disabled).map(d => ({ value: d.id, label: d.name }));
                } catch (e) { return []; }
            },
            async _putErrand(id, patch) {
                let fresh = null;
                try {
                    const r = await fetch(`${apiBase}api/errands`);
                    const rows = r.ok ? await r.json() : [];
                    fresh = rows.find(x => x.id === id) || null;
                } catch (e) { }
                const er = fresh || this.errands.find(x => x.id === id);
                if (!er) return false;
                const gen = er.generation;
                const body = Object.assign({}, er, patch);
                delete body.placement; delete body.unplaced; delete body.generation; delete body.shopping_lists;
                const res = await fetch(`${apiBase}api/errands/${er.doc_id}`, {
                    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
                if (!res.ok) { showGlobalAlert('That could not be saved.'); return false; }
                this.replanning.add(id);
                this._awaitReplan(id, gen);
                await this.loadErrands();
                return true;
            },
            _awaitReplan(id, gen, tries = 20) {
                const tick = async () => {
                    await this.loadErrands();
                    const er = this.errands.find(x => x.id === id);
                    if (!er || er.generation !== gen || tries-- <= 0) {
                        this.replanning.delete(id);
                        if (er && er.generation === gen) showGlobalAlert('Still planning, check back in a minute.');
                        return;
                    }
                    setTimeout(tick, 3000);
                };
                setTimeout(tick, 3000);
            },
            async steerErrand(e) {
                const scheduledDay = e.placement ? String(e.placement.start_time).slice(0, 10) : null;
                const title = e.title;
                const msg = (e.placement && e.placement.why && e.placement.why.text) || (e.unplaced && e.unplaced.text) || '';
                const opts = [];
                if (scheduledDay) opts.push({ value: 'skip_today', label: 'Not this day' });
                opts.push({ value: 'skip_day', label: 'Skip a day…' });
                opts.push({ value: 'pin_day', label: 'Pick a day' });
                opts.push({ value: 'pin_time', label: 'Pick a time' });
                opts.push({ value: 'driver', label: 'Someone else' });
                if (this.isSteered(e)) opts.push({ value: 'auto', label: 'Back to automatic' });
                const pick = await promptChoice(title, msg, opts);
                if (!pick) return;
                const W = window.ChfErrandSteer.STEER_WINDOWS;
                if (pick === 'skip_today') {
                    const days = Array.from(new Set([...(e.skip_dates || []), scheduledDay]));
                    return this._putErrand(e.id, { skip_dates: days });
                }
                if (pick === 'skip_day') {
                    const d = await promptChoice('Skip which day?', '', this._dayChoices());
                    if (!d) return;
                    return this._putErrand(e.id, { skip_dates: Array.from(new Set([...(e.skip_dates || []), d])) });
                }
                if (pick === 'pin_day') {
                    const d = await promptChoice('Which day?', '', this._dayChoices());
                    if (!d) return;
                    return this._putErrand(e.id, { pinned_date: d });
                }
                if (pick === 'pin_time') {
                    let day = e.pinned_date || scheduledDay;
                    if (!day) {
                        day = await promptChoice('Which day?', 'Pick the day first.', this._dayChoices());
                        if (!day) return;
                    }
                    const w = await promptChoice('When that day?', '', Object.keys(W).map(k => ({ value: k, label: `${k[0].toUpperCase()}${k.slice(1)} (${W[k][0]}–${W[k][1]})` })));
                    if (!w) return;
                    return this._putErrand(e.id, { pinned_date: day, pinned_start: W[w][0], pinned_end: W[w][1] });
                }
                if (pick === 'driver') {
                    const ds = await this._driverChoices();
                    if (!ds.length) { showGlobalAlert('No drivers to choose from.'); return; }
                    const d = await promptChoice('Who runs it this time?', '', ds);
                    if (!d) return;
                    return this._putErrand(e.id, { once_driver_id: d });
                }
                if (pick === 'auto') {
                    return this._putErrand(e.id, { skip_dates: [], pinned_date: null, pinned_start: null, pinned_end: null, once_driver_id: null });
                }
            },
```

And above `errandListsLogic`:

```javascript
    window.ChfErrandSteer = window.ChfErrandSteer || {
        STEER_WINDOWS: { morning: ['08:00', '12:00'], midday: ['11:00', '14:00'],
                         afternoon: ['14:00', '17:00'], evening: ['17:00', '20:00'] },
    };
```

Confirm `api/drivers` exists (`grep -n '"/api/drivers"' main.py`); if the drivers list lives under another path, use that one.

In `templates/errands.html`'s edit modal, after the time-window inputs (`:293`), add inputs `edit-pinned-date` (type date), `edit-pinned-start`, `edit-pinned-end` (type time), `edit-once-driver` (a select filled from the same drivers list the modal already loads for required drivers; if none is loaded there, a text input of the driver id is NOT acceptable: load `api/drivers` in `openEditModal`), and a read-only list of `skip_dates` with an ✕ per date. In `populate` (`:747-760`) fill them from `currentEditErrand`; in `saveEdit` (`:803`) write them back:

```javascript
            errand.pinned_date = document.getElementById('edit-pinned-date').value || null;
            errand.pinned_start = document.getElementById('edit-pinned-start').value || null;
            errand.pinned_end = document.getElementById('edit-pinned-end').value || null;
            errand.once_driver_id = document.getElementById('edit-once-driver').value || null;
            errand.skip_dates = currentEditErrand.skip_dates || [];
```

Run `python tools/build_tailwind.py` after the markup changes.

- [ ] **Step 5: Run**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_errand_lists_render.py && python tests/test_template_js.py`
Expected: all pass.

- [ ] **Step 6: Hand back**

---

### Task 9: The PWA — why through the projections, Steer in the modal, Errands not placed

**Files:**
- Modify: `templates/app.html:9553-9568` (`scheduled_errands` → card projection), `:9861-9880` (My Day errand projection), `:10070-10090` (merge), `:9284-9300` (the modal's Complete block), `:10640` (modal markup), `buildTimeline` (`:9835`) for the "Errands not placed" row
- Test: `tests/test_pwa_errand_steer.py` (new, node-run)

**Interfaces:**
- Consumes: `/api/errands` rows (for the unplaced list), `window.ChfErrandSteer.STEER_WINDOWS` is NOT available in the PWA (errand_lists.html is not included there): copy the constant into app.html under the same name so the two stay greppable together; `promptChoice` (app.html's own), `memberToken()`, `selectedDriverId`.
- Produces: card objects from both projections carry `why` (the `placement.why` dict from the scheduled row); `openEventModal` draws `#em-why` and `#em-steer-btn`; `steerErrandFromModal(ev)` reuses the same choice flow as Task 8 (copied into app.html as `pwaSteerErrand(errandRow)`); `renderUnplacedErrands()` draws `#unplaced-errands` under today when any row from `/api/errands` has `unplaced`.

- [ ] **Step 1: Write the failing node-run test**

Create `tests/test_pwa_errand_steer.py`:

```python
"""The PWA's errand card and modal carry the placement's why and offer Steer.

Spec §4.5: both projections of a scheduled errand keep `why` through to the
card; the modal shows the why line and a Steer button under Complete's own
predicate (`ev.isErrand && selectedDriverId`); an unplaced errand is reachable
through the "Errands not placed" row. Run under node by extracting the exact
functions from app.html so a unit test cannot pass on a fixture the real
projection would have dropped.

Run from chauffeur/:  python tests/test_pwa_errand_steer.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(os.path.dirname(HERE), 'templates')
sys.path.insert(0, HERE)
from test_moment_media_token import _block_from, _function_text, _run_node, check  # noqa: E402

APP = open(os.path.join(TPL, 'app.html'), encoding='utf-8').read()

ROW = {'id': 'er1', 'title': 'Costco run', 'start_time': '2026-10-27T16:10:00', 'end_time': '2026-10-27T16:40:00',
       'location': 'Costco', 'driver': {'id': 'd1', 'name': 'Jeff'}, 'event_type': 'errand',
       'why': {'kind': 'on_the_way', 'detour_mins': 6, 'driver_name': 'Jeff',
               'leg': {'from': 'Home', 'to': 'Soccer'}, 'text': "on Jeff's way to Soccer, +6 min"}}


def scenario_both_projections_keep_why():
    fn_family = _function_text(APP, 'function buildFamilyByDate()')   # app.html:9536, the function holding the :9559 projection
    got = _run_node("var scheduleData = {scheduled_errands: [%s], events: [], assignments: {}, ghost_assignments: {}};\n" % json.dumps(ROW)
                    + "var selectedDriverId = 'd1'; var formatTime = s => String(s); var mfEscape = s => String(s);\n"
                    + "var driversData = []; var passengersData = []; var membersData = [];\n" + fn_family + r"""
var byDate = buildFamilyByDate();
var card = Object.values(byDate).flat().find(c => c.isErrand);
console.log(JSON.stringify({why: card && card.why}));
""")
    check(got and got['why'] and got['why']['text'] == "on Jeff's way to Soccer, +6 min",
          f"the agenda projection keeps why: {got}")


def scenario_the_modal_shows_why_and_steer_under_completes_predicate():
    src = APP
    check('id="em-why"' in src and 'id="em-steer-btn"' in src, "the modal has a why line and a Steer button")
    block = src[src.index("const completeBtn = document.getElementById('em-complete-btn')"):][:2500]
    check("getElementById('em-steer-btn')" in block and 'ev.isErrand && selectedDriverId' in block,
          "Steer is shown exactly where Complete is, under the same predicate")
    check('ev.why' in block or 'ev.whyText' in block, "the modal reads the card's why")


def scenario_unplaced_errands_have_a_row_and_open_the_sheet():
    src = APP
    check('id="unplaced-errands"' in src, "the Errands not placed row exists")
    check('function renderUnplacedErrands' in src and 'pwaSteerErrand(' in src,
          "it renders from /api/errands and opens the same steer flow")
    fn = _function_text(src, 'async function pwaSteerErrand(ref)')
    got = _run_node(r"""
var apiBase = ''; var puts = [];
var memberToken = () => 't'; var showGlobalAlert = () => {}; var selectedDriverId = 'd1';
var window = globalThis;
window.ChfErrandSteer = { STEER_WINDOWS: { morning: ['08:00','12:00'], midday: ['11:00','14:00'], afternoon: ['14:00','17:00'], evening: ['17:00','20:00'] } };
globalThis.fetch = async (url, init) => {
  if (init && init.method === 'PUT') { puts.push({url, body: JSON.parse(init.body)}); return {ok: true, json: async () => ({})}; }
  if (String(url).includes('api/drivers')) return {ok: true, json: async () => [{id: 'd2', name: 'Lorena'}]};
  return {ok: true, json: async () => [{id: 'er1', doc_id: 7, title: 'Costco run', location: 'Costco', duration_mins: 30,
    skip_dates: [], generation: 2, unplaced: {reason: 'no_driver', text: 'x'}}]};
};
var answers = ['driver', 'd2'];
globalThis.promptChoice = async () => answers.shift();
""" + fn + r"""
pwaSteerErrand({id: 'er1'}).then(() => console.log(JSON.stringify({puts})));
""")
    check(len(got['puts']) == 1 and got['puts'][0]['url'].endswith('api/errands/7')
          and got['puts'][0]['body']['once_driver_id'] == 'd2' and got['puts'][0]['body']['title'] == 'Costco run',
          f"Someone else writes the whole record with once_driver_id: {got}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} pwa errand steer scenarios passed")
```

`buildFamilyByDate()` (app.html:9536) is the function holding the `scheduled_errands.forEach(er => push(...))` projection. If it closes over page state the prelude does not stub yet, add the missing names to the prelude as plain stand-ins (never change the function to make the test pass). `pwaSteerErrand` must be declared exactly as `async function pwaSteerErrand(ref)` so the extraction finds it.

- [ ] **Step 2: Run to see it fail**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_pwa_errand_steer.py`
Expected: FAIL: `why` is undefined on the card.

- [ ] **Step 3: Implement**

1. Projection at `:9559`: add `why: er.why || null,` to the pushed card. Projection at `:9861-9865` (`myErrands.forEach`): the errand object is pushed whole, so `why` already rides; confirm the later `eventData = {...}` at `:9707`/`:10078` copies it: add `why: card.why || null,` and `why: ev.why || null,` respectively.
2. Modal markup (`:10584`, after `#em-time`): `<p id="em-why" class="text-sm text-indigo-300 mb-3" style="display:none"></p>`. Before `#em-complete-btn`: `<button id="em-steer-btn" class="w-full flex items-center justify-center gap-3 py-3 rounded-xl border-2 border-indigo-500/50 hover:bg-indigo-900/20 text-indigo-300 font-bold shadow-md mb-3" style="display:none">Steer this errand</button>`.
3. In the `completeBtn` block (`:9284`): set `document.getElementById('em-why')` text from `(ev.why || {}).text` and show it when non-empty (for errands only); show `#em-steer-btn` under exactly `if (ev.isErrand && selectedDriverId)` and wire `onclick = () => pwaSteerErrand({ id: ev.id }).then(() => { closeEventModal(); loadSchedule && loadSchedule(); })`.
4. Add `window.ChfErrandSteer` (same constant as Task 8) and `async function pwaSteerErrand(ref)` to app.html: it fetches `/api/errands`, finds the row by `ref.id`, builds the same option list as Task 8's `steerErrand` (Not this day when `placement`, Skip a day…, Pick a day, Pick a time, Someone else, Back to automatic when steered), uses the PWA's `promptChoice`, and PUTs the whole record with the steer patch (strip `placement`, `unplaced`, `generation`, `shopping_lists`). Copy the day-choice and driver-choice builders from Task 8 verbatim with `apiBase` prefixes.
5. `renderUnplacedErrands()`: after `buildTimeline` draws today's pane, fetch `/api/errands`, filter rows with `unplaced` and not completed, and if any, append to today's pane a block `id="unplaced-errands"` headed "Errands not placed" with one row per errand: title, `unplaced.text`, and a `<button>` "Steer" calling `pwaSteerErrand({id})` (buttons only, no anchors). Call it from the end of `buildTimeline` only when `selectedDriverId` is set (R4).
6. `python tools/build_tailwind.py`.

- [ ] **Step 4: Run**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_pwa_errand_steer.py && python tests/test_template_js.py && python tests/test_pwa_assign_other_driver.py`
Expected: all pass.

- [ ] **Step 5: Hand back**

---

### Task 10: Gate, document, ship (Claude)

**Files:**
- Modify: `chauffeur/system_capabilities.md` (new top entry), `chauffeur/config.yaml` (version), memory `errands-ride-the-route-arc.md`.

- [ ] **Step 1: Run the gate**

```
cd chauffeur && unset HA_BASE_URL
python tests/test_errand_routing.py
python tests/test_errand_routing_api.py
python tests/test_pwa_errand_steer.py
python tests/test_errand_lists_render.py
python tests/test_solve_pack.py
python tests/test_storage.py
python tests/test_chat_actions.py
python tests/test_agent_v2_bridge.py
python tests/test_registry_parity.py
python tests/test_schedule_timeline.py
python tests/test_settings_registry.py
python tests/test_template_js.py
```

Expected: every file passes.

- [ ] **Step 2: Capabilities entry**

Add a top entry in `system_capabilities.md` headed `**BUILT, NOT device-verified: errands ride the route (vX–vY; spec ..., plan ...)**` recording: legs from rides plus own events, candidate timing, the ranking, `errand_leg_minutes` never guessing, the bounded primer, `why` on every row, notes and their seven reasons, the four steer fields and their lifetime, `complete_errand` as the one completion path and the successor anchor, `forget_errand_placements`, the generation, the sheet on the Errands page and the PWA, the admin editor fields, the agent tool fields, the setting and its drawer, the two latent bugs fixed, and the device steps (rebuild; create "Costco run" with a real address; watch it land on a real drive with its why; tap Steer › Not this day on the phone; say "not Thursday for the Costco run" to Argyle; check the Errands page shows the reason for an errand with a bad address).

- [ ] **Step 3: Bump, commit, push; update the memory arc file to SHIPPED with the device steps.**

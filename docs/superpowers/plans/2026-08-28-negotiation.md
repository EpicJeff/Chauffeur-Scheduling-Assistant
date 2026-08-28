# Negotiation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a day cannot be covered, the app finds the smallest change that makes it work, names who has to agree to it, and asks them — instead of reporting a conflict.

**Architecture:** The refresh persists a **solve pack** per day (every input `matcher.solve_schedule` was given). `services/negotiation.py` replays copies of that pack with one small mutation applied per candidate — shift an event, lift one occurrence of a protected window, pin a driver onto a drive, skip an optional — keeps the candidates that cover the seed without breaking the rest of the day, ranks them by social cost, and stores the winner as a **deal** of **parts**. Each part becomes an existing `requests.py` request to the person it costs. Nothing applies until every part says yes.

**Tech Stack:** Python 3.14, FastAPI, OR-Tools CP-SAT (`solver/matcher.py`), pydantic v2 models (`models/schemas.py`), TinyDB-shaped API over SQLite (`services/storage.py`), scenario-style tests run by `python tools/test.py`.

**Spec:** `docs/superpowers/specs/2026-08-28-negotiation-design.md`

## Global Constraints

- **Every commit bumps `chauffeur/config.yaml` `version:` and ends its message with `(vX.Y.Z)`.** This arc runs `2.431.0` → `2.431.N`, one bump per task. Commit and push; never ask.
- **Run the full suite before every commit:** `cd chauffeur && python tools/test.py`. `--focus` is for the inner loop only. Never a serial loop, never piped — piping masks the exit code.
- **All work happens in `chauffeur/`.** Tests are standalone scripts in `chauffeur/tests/`, named `test_*.py`, using `from harness import check`, `scenario_*()` functions, and a `if __name__ == '__main__':` block that calls each scenario then prints `test_<name> OK`.
- **The negotiator is read-only against the world.** It never writes a schedule, never patches a calendar, never mutates the live cache. Application happens only through an accepted request.
- **The agent never asks anybody without a person tapping.** Searching and asking are separate functions behind separate endpoints.
- **Travel lookups stay inside the cache.** A candidate needing an uncached travel pair is dropped, not bought.
- **No `alert()` / `confirm()` / `prompt()`** in any template — use `showGlobalAlert` / `promptConfirm` / `promptInput`.
- **Never round-trip a source file through PowerShell `Get-Content`/`Set-Content`** — it mojibakes UTF-8.
- **Commit messages through PowerShell must not contain double quotes.** Use a bash heredoc (`git commit -F -  <<'EOF'`).
- New settings go in `services/settings_registry.py`, never `config.html`.
- After any template class change, run `python tools/build_tailwind.py`.

---

## File Structure

**Created:**
- `chauffeur/services/solve_pack.py` — persist and replay one day's solver world. Knows nothing about deals.
- `chauffeur/services/negotiation.py` — levers, search, cost, deal lifecycle. Knows nothing about how a pack is stored.
- `chauffeur/tests/test_solve_pack.py`, `test_negotiation_levers.py`, `test_negotiation_cost.py`, `test_negotiation_consent.py`, `test_negotiation_endpoints.py`, `test_negotiation_agent_tools.py`, `test_negotiation_runtime.py`

**Modified:**
- `chauffeur/solver/matcher.py` — two optional parameters on `solve_schedule` (time limit, stats out-param). No signature break.
- `chauffeur/models/schemas.py` — `Deal` model.
- `chauffeur/services/storage.py` + `services/storage_sqlite.py` — `solve_packs`, `deals`, `shift_refusals` tables and their CRUD.
- `chauffeur/main.py` — write the pack during the refresh; four endpoints.
- `chauffeur/services/watchers.py` — the uncovered finding carries a deal when one exists.
- `chauffeur/services/requests.py` — `deal_part` requests delegate to negotiation.
- `chauffeur/services/chat_actions.py` — `ask_deal` action type.
- `chauffeur/services/agent_tools_v2.py`, `agent_router.py`, `agent_tools.py` — chat tools in both stacks.
- `chauffeur/services/settings_registry.py` — five settings.
- `chauffeur/templates/dashboard.html` — **Find a way** in the override dialog.
- `chauffeur/system_capabilities.md` — the new section.

---

### Task 1: The solver reports its objective, and takes a time limit

`solve_schedule` hardcodes `max_time_in_seconds = 5.0` and returns four values, none of them the objective. Negotiation needs a shorter cap (it runs many solves) and the objective value (the tie-breaker in the cost function). Both arrive as optional parameters so the one existing caller at `main.py:16967` is untouched.

**Files:**
- Modify: `chauffeur/solver/matcher.py:468-494` (signature), `chauffeur/solver/matcher.py:1260-1263` (solve)
- Test: `chauffeur/tests/test_negotiation_matcher_stats.py`

**Interfaces:**
- Produces: `matcher.solve_schedule(..., time_limit_s: float = 5.0, stats: dict = None)`. When `stats` is a dict, the call fills it with `{'objective': float, 'status': str, 'wall_time': float}`. `status` is one of `'OPTIMAL'`, `'FEASIBLE'`, `'INFEASIBLE'`, `'UNKNOWN'`, `'MODEL_INVALID'`.

- [ ] **Step 1: Write the failing test**

Create `chauffeur/tests/test_negotiation_matcher_stats.py`:

```python
"""solve_schedule reports what it did, and can be given less time."""
import datetime

from harness import check
from models.schemas import Driver, Event
from solver import matcher

MONDAY = datetime.datetime(2026, 9, 7, 17, 0)


def _event(eid, start, title='Practice'):
    return Event(id=eid, title=title, start=start,
                 end=start + datetime.timedelta(hours=1),
                 location='Field', calendar_ids=['c1'], source_event_ids=[eid])


def _driver(did, name):
    return Driver(id=did, name=name, home_location='Home')


def scenario_stats_are_reported():
    events = [_event('e1', MONDAY)]
    drivers = [_driver('d1', 'Jeff')]
    stats = {}
    assignments, unassigned, _, _ = matcher.solve_schedule(
        events, drivers, [], stats=stats)
    check(assignments.get('e1') == 'd1', f"the one driver takes it, got {assignments}")
    check(stats.get('status') in ('OPTIMAL', 'FEASIBLE'),
          f"the status comes back, got {stats}")
    check(isinstance(stats.get('objective'), float),
          f"and so does the objective, got {stats}")


def scenario_time_limit_is_honoured():
    events = [_event('e1', MONDAY)]
    drivers = [_driver('d1', 'Jeff')]
    stats = {}
    matcher.solve_schedule(events, drivers, [], time_limit_s=0.5, stats=stats)
    check(stats.get('wall_time') is not None, f"wall time is reported, got {stats}")
    check(stats['wall_time'] < 5.0, f"and the short cap was used, got {stats}")


def scenario_stats_is_optional():
    # The existing caller passes neither parameter and must be unaffected.
    events = [_event('e1', MONDAY)]
    out = matcher.solve_schedule(events, [_driver('d1', 'Jeff')], [])
    check(len(out) == 4, f"still a four-tuple, got {len(out)}")


if __name__ == '__main__':
    scenario_stats_are_reported()
    scenario_time_limit_is_honoured()
    scenario_stats_is_optional()
    print("test_negotiation_matcher_stats OK")
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd chauffeur && python tests/test_negotiation_matcher_stats.py`
Expected: FAIL — `TypeError: solve_schedule() got an unexpected keyword argument 'stats'`

- [ ] **Step 3: Add the two parameters**

In `chauffeur/solver/matcher.py`, extend the signature (after `driver_passenger_map`, keeping every existing parameter and its order):

```python
    driver_passenger_map: Dict[str, str] = None,
    # Negotiation replays this function many times per question, so it needs a
    # shorter leash than the daily solve's five seconds. Optional and defaulted
    # to the old constant: the refresh is unchanged.
    time_limit_s: float = 5.0,
    # An out-param rather than a fifth return value, because four callers'
    # worth of tuple unpacking is not worth breaking to learn one number.
    # Filled only when a dict is passed in.
    stats: dict = None
) -> Tuple[Dict[str, str], List[str], Dict[str, str], Dict[str, str]]:
```

Replace the solve block at `matcher.py:1261-1263`:

```python
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_s)
    status = solver.Solve(model)
    if stats is not None:
        stats['status'] = solver.StatusName(status)
        stats['wall_time'] = solver.WallTime()
        # ObjectiveValue is only defined for a solved model; a model that
        # proved infeasible has no score to report and must not raise here.
        try:
            stats['objective'] = float(solver.ObjectiveValue())
        except Exception:
            stats['objective'] = 0.0
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd chauffeur && python tests/test_negotiation_matcher_stats.py`
Expected: PASS, printing `test_negotiation_matcher_stats OK`

- [ ] **Step 5: Run the full suite, then commit**

Run: `cd chauffeur && python tools/test.py`
Expected: every test passes.

Bump `chauffeur/config.yaml` to `2.431.0`, then:

```bash
git add -A && git commit -F - <<'EOF'
The solver can say what it scored, and be given less time

Negotiation replays solve_schedule many times per question, so it needs a
shorter leash than the daily solve's five seconds, and it needs the objective
value as the tie-breaker in its cost function. Both arrive as optional
parameters -- stats as an out-param rather than a fifth return value, because
breaking every caller's tuple unpacking to learn one number is not a trade
worth making. The refresh's call is untouched.

(v2.431.0)
EOF
git push
```

---

### Task 2: The solve pack — persist one day's solver world

The negotiator must replay exactly what the schedule solved. Rebuilding from storage would drift: `driver_events` (the `+50,000,000` attendance term) is built during the calendar fetch and is not in the day cache, and the rule list is assembled inside the refresh from stored rules, status-day unavailability, and protected commitments.

**Files:**
- Create: `chauffeur/services/solve_pack.py`
- Modify: `chauffeur/services/storage.py` (table + CRUD), `chauffeur/services/storage_sqlite.py` (index registry)
- Test: `chauffeur/tests/test_solve_pack.py`

**Interfaces:**
- Produces:
  - `storage.save_solve_pack(date_str: str, pack: dict) -> None`, `storage.get_solve_pack(date_str: str) -> Optional[dict]`, `storage.prune_solve_packs(before_date: str) -> int`
  - `solve_pack.build(date_str, events, drivers, rules, priority_rules, overrides, passengers, cars, driver_events, trip_metadata, driver_passenger_map, previous_assignments, load_balancing, load_balancing_metric, protected_rule_index) -> dict`
  - `solve_pack.replay(pack: dict, time_limit_s: float = 2.0) -> dict` returning `{'assignments', 'unassigned', 'true_unassigned', 'conflicts', 'objective', 'status'}`
  - `solve_pack.PACK_KEYS: tuple` — the required keys, so a stale pack is detected rather than half-read.

- [ ] **Step 1: Write the failing test**

Create `chauffeur/tests/test_solve_pack.py`:

```python
"""A day's solver world, stored and replayed.

The whole negotiation arc rests on one property: replaying a pack unmutated
reproduces the assignments that day actually got. If it does not, an input is
missing and every deal built on the pack is fiction.
"""
import datetime

from harness import check
from models.schemas import Driver, Event
from services import solve_pack, storage
from solver import matcher

MONDAY = datetime.datetime(2026, 9, 7, 17, 0)


def _event(eid, start, title='Practice'):
    return Event(id=eid, title=title, start=start,
                 end=start + datetime.timedelta(hours=1),
                 location='Field', calendar_ids=['c1'], source_event_ids=[eid])


def _driver(did, name):
    return Driver(id=did, name=name, home_location='Home')


def _world():
    events = [_event('e1', MONDAY), _event('e2', MONDAY, 'Piano')]
    drivers = [_driver('d1', 'Jeff'), _driver('d2', 'Lorena')]
    return events, drivers


def _pack(events, drivers):
    return solve_pack.build(
        '2026-09-07', events=events, drivers=drivers, rules=[],
        priority_rules=[], overrides=[], passengers=[], cars=[],
        driver_events={}, trip_metadata=[], driver_passenger_map={},
        previous_assignments={}, load_balancing=False,
        load_balancing_metric='occupied_time', protected_rule_index={})


def scenario_replay_reproduces_the_solve():
    events, drivers = _world()
    direct, _, _, _ = matcher.solve_schedule(events, drivers, [])
    out = solve_pack.replay(_pack(events, drivers))
    check(out['assignments'] == direct,
          f"replay matches a direct solve\n  direct={direct}\n  replay={out['assignments']}")
    check(isinstance(out['objective'], float), f"and reports a score, got {out}")


def scenario_roundtrip_through_storage():
    events, drivers = _world()
    pack = _pack(events, drivers)
    storage.save_solve_pack('2026-09-07', pack)
    loaded = storage.get_solve_pack('2026-09-07')
    check(loaded is not None, "the pack comes back")
    out = solve_pack.replay(loaded)
    check(out['assignments'] == solve_pack.replay(pack)['assignments'],
          "and a stored pack replays the same as the one in hand")


def scenario_saving_a_day_twice_keeps_one_row():
    events, drivers = _world()
    storage.save_solve_pack('2026-09-07', _pack(events, drivers))
    storage.save_solve_pack('2026-09-07', _pack(events, drivers))
    with storage.db_lock:
        rows = [dict(r) for r in storage.solve_packs_table.all()]
    check(len([r for r in rows if r['date'] == '2026-09-07']) == 1,
          f"one row per day, got {len(rows)}")


def scenario_an_incomplete_pack_is_refused():
    broken = dict(_pack(*_world()))
    broken.pop('driver_events')
    try:
        solve_pack.replay(broken)
    except ValueError as e:
        check('driver_events' in str(e), f"it names what is missing, got {e}")
        return
    check(False, "a pack missing an input must refuse to replay, not guess")


if __name__ == '__main__':
    scenario_replay_reproduces_the_solve()
    scenario_roundtrip_through_storage()
    scenario_saving_a_day_twice_keeps_one_row()
    scenario_an_incomplete_pack_is_refused()
    print("test_solve_pack OK")
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd chauffeur && python tests/test_solve_pack.py`
Expected: FAIL — `ImportError: cannot import name 'solve_pack' from 'services'`

- [ ] **Step 3: Add the storage table and CRUD**

In `chauffeur/services/storage.py`, beside the other table definitions (near line 465):

```python
    solve_packs_table = db.table('solve_packs')
```

And the CRUD, next to the other cache helpers:

```python
# --- Solve packs: what the solver was actually given, per day -------------
# Negotiation (docs/superpowers/specs/2026-08-28-negotiation-design.md) replays
# a day to ask what would happen if one thing changed. Rebuilding the solver's
# world from storage would drift -- driver_events is built during the calendar
# fetch and the rule list is assembled inside the refresh -- and a drifted
# replay answers a different question than the schedule did. So the refresh
# writes down what it handed the solver, and the negotiator replays that.

def save_solve_pack(date_str: str, pack: dict):
    with db_lock:
        solve_packs_table.upsert({**pack, 'date': date_str},
                                 Query().date == date_str)

def get_solve_pack(date_str: str) -> Optional[dict]:
    with db_lock:
        res = solve_packs_table.search(Query().date == date_str)
        return dict(res[0]) if res else None

def prune_solve_packs(before_date: str) -> int:
    """Yesterday's pack answers no question anybody will ask."""
    with db_lock:
        rows = [dict(r) for r in solve_packs_table.all()]
        stale = [r for r in rows if (r.get('date') or '') < before_date]
        for r in stale:
            solve_packs_table.remove(Query().date == r['date'])
        return len(stale)
```

In `chauffeur/services/storage_sqlite.py`, add to the index registry dict:

```python
    # Solve packs: written once per day per refresh, read by date when
    # somebody asks the negotiator a question. Date is the only lookup.
    "solve_packs": [["date"]],
```

- [ ] **Step 4: Write `services/solve_pack.py`**

```python
"""One day's solver world, written down so it can be asked a second question.

`matcher.solve_schedule` is a pure function, but its arguments are not: they
are assembled across 1300 lines of `_refresh_schedule_logic_impl` -- calendars
fetched, trips resolved, outside hands removed, protected commitments turned
into `unavailable` rules. Two of those inputs cannot be recovered afterwards:

- `driver_events`, a driver's own calendar, which carries the `+50,000,000`
  attendance term and in practice decides assignments on its own. It is built
  during the calendar fetch and is not in the day cache.
- the rule list, assembled from three sources that no single table holds.

So the refresh writes down what it handed the solver. The negotiator replays
THAT, which is the only way its answers describe the schedule the family
actually has rather than one that resembles it.

Nothing here mutates anything. `apply` returns a new pack; `replay` runs a
solve and returns numbers. Whoever wants to change the world does it somewhere
else, after a person has agreed.
"""
import copy
import datetime

from models.schemas import Car, Driver, Event, ManualOverride, Passenger, PriorityRule, Rule
from solver import matcher

PACK_KEYS = ('date', 'events', 'drivers', 'rules', 'priority_rules', 'overrides',
             'passengers', 'cars', 'driver_events', 'trip_metadata',
             'driver_passenger_map', 'previous_assignments', 'load_balancing',
             'load_balancing_metric', 'protected_rule_index')

# Every replay is one of many in a single question, so it gets a shorter leash
# than the daily solve's five seconds.
DEFAULT_TIME_LIMIT_S = 2.0


def _dump(obj):
    if hasattr(obj, 'model_dump'):
        return obj.model_dump(mode='json')
    if hasattr(obj, 'dict'):
        return obj.dict()
    return obj


def build(date_str, *, events, drivers, rules, priority_rules, overrides,
          passengers, cars, driver_events, trip_metadata, driver_passenger_map,
          previous_assignments, load_balancing, load_balancing_metric,
          protected_rule_index) -> dict:
    """Everything `solve_schedule` was given, as plain JSON-able data.

    `protected_rule_index` maps a protected commitment's id to its position in
    `rules`. The refresh is the only place that knows which rule came from
    which commitment -- the `Rule` object itself carries no provenance -- and
    without it the lift-a-protected-window lever cannot name what it is
    lifting.
    """
    return {
        'date': date_str,
        'events': [_dump(e) for e in events],
        'drivers': [_dump(d) for d in drivers],
        'rules': [_dump(r) for r in rules],
        'priority_rules': [_dump(p) for p in priority_rules],
        'overrides': [_dump(o) for o in overrides],
        'passengers': [_dump(p) for p in passengers],
        'cars': [_dump(c) for c in cars],
        'driver_events': {str(k): [_dump(e) for e in v]
                          for k, v in (driver_events or {}).items()},
        'trip_metadata': [_dump(t) for t in (trip_metadata or [])],
        'driver_passenger_map': dict(driver_passenger_map or {}),
        'previous_assignments': dict(previous_assignments or {}),
        'load_balancing': bool(load_balancing),
        'load_balancing_metric': load_balancing_metric or 'occupied_time',
        'protected_rule_index': dict(protected_rule_index or {}),
        'written_at': datetime.datetime.now().timestamp(),
    }


def _check(pack: dict):
    missing = [k for k in PACK_KEYS if k not in pack]
    if missing:
        raise ValueError(f"solve pack is missing {', '.join(missing)} — it was "
                         f"written by an older refresh and cannot be replayed")


def apply(pack: dict, mutations: list) -> dict:
    """A copy of the pack with the mutations applied. The original is untouched.

    Mutations are the negotiation levers, each occurrence-scoped:
        {'lever': 'shift_event',    'event_id': str, 'delta_mins': int}
        {'lever': 'lift_protected', 'commitment_id': str}
        {'lever': 'swap_drive',     'event_id': str, 'driver_id': str}
        {'lever': 'skip_optional',  'event_id': str}
    """
    out = copy.deepcopy(pack)
    for m in mutations or []:
        lever = m.get('lever')
        if lever == 'shift_event':
            delta = datetime.timedelta(minutes=int(m['delta_mins']))
            for e in out['events']:
                if str(e.get('id')) != str(m['event_id']):
                    continue
                for field in ('start', 'end'):
                    raw = e.get(field)
                    if raw:
                        e[field] = (datetime.datetime.fromisoformat(str(raw))
                                    + delta).isoformat()
        elif lever == 'lift_protected':
            idx = out['protected_rule_index'].get(str(m['commitment_id']))
            if idx is None or idx >= len(out['rules']):
                raise ValueError(f"no protected rule for commitment {m['commitment_id']}")
            out['rules'] = [r for i, r in enumerate(out['rules']) if i != idx]
            # Every later index shifts by one; keep the map honest so a second
            # lift in the same candidate does not remove the wrong rule.
            out['protected_rule_index'] = {
                k: (v - 1 if v > idx else v)
                for k, v in out['protected_rule_index'].items()
                if v != idx}
        elif lever == 'swap_drive':
            out['overrides'].append({'event_id': str(m['event_id']),
                                     'driver_id': str(m['driver_id']),
                                     'created_at': out['written_at'],
                                     'source': 'negotiation'})
        elif lever == 'skip_optional':
            out['events'] = [e for e in out['events']
                             if str(e.get('id')) != str(m['event_id'])]
        else:
            raise ValueError(f"unknown lever '{lever}'")
    return out


def replay(pack: dict, time_limit_s: float = DEFAULT_TIME_LIMIT_S) -> dict:
    """Solve this pack. Returns what happened; changes nothing."""
    _check(pack)
    events = [Event(**e) for e in pack['events']]
    drivers = [Driver(**d) for d in pack['drivers']]
    driver_events = {k: [Event(**e) for e in v]
                     for k, v in pack['driver_events'].items()}
    trips = []
    for t in pack['trip_metadata']:
        t = dict(t)
        for field in ('start', 'end'):
            if isinstance(t.get(field), str):
                t[field] = datetime.datetime.fromisoformat(t[field])
        t['entities'] = set(t.get('entities') or [])
        trips.append(t)
    stats = {}
    assignments, unassigned, lateness, cars_out = matcher.solve_schedule(
        events, drivers,
        [Rule(**r) for r in pack['rules']],
        [PriorityRule(**p) for p in pack['priority_rules']],
        overrides=[ManualOverride(**o) for o in pack['overrides']],
        previous_assignments=dict(pack['previous_assignments']),
        driver_events=driver_events,
        passengers=[Passenger(**p) for p in pack['passengers']],
        trip_metadata=trips,
        load_balancing=pack['load_balancing'],
        load_balancing_metric=pack['load_balancing_metric'],
        cars=[Car(**c) for c in pack['cars']],
        driver_passenger_map=dict(pack['driver_passenger_map']),
        time_limit_s=time_limit_s, stats=stats)
    conflicts = matcher.compute_conflicts(assignments, {}, events)
    return {'assignments': assignments, 'unassigned': list(unassigned),
            'true_unassigned': list(unassigned), 'conflicts': conflicts,
            'lateness_warnings': lateness, 'car_assignments': cars_out,
            'objective': float(stats.get('objective') or 0.0),
            'status': stats.get('status') or 'UNKNOWN'}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd chauffeur && python tests/test_solve_pack.py`
Expected: PASS, printing `test_solve_pack OK`

- [ ] **Step 6: Run the full suite, then commit**

Run: `cd chauffeur && python tools/test.py`

Bump `chauffeur/config.yaml` to `2.431.1`, then:

```bash
git add -A && git commit -F - <<'EOF'
Write down what the solver was actually given

A day's solver world, stored per day and replayable. The negotiator cannot
rebuild it from storage: driver_events is built during the calendar fetch and
carries the attendance term that decides most assignments on its own, and the
rule list is assembled inside the refresh from three sources no single table
holds. A drifted replay would answer a different question than the schedule
did, so the refresh writes down what it handed the solver.

A pack missing an input refuses to replay rather than guessing. The test that
matters: replaying a pack unmutated reproduces a direct solve exactly.

(v2.431.1)
EOF
git push
```

---

### Task 3: The refresh writes the pack

**Files:**
- Modify: `chauffeur/main.py:15848-15866` (tag protected rules), `chauffeur/main.py:16981-16995` (write the pack)
- Test: `chauffeur/tests/test_negotiation_runtime.py`

**Interfaces:**
- Consumes: `solve_pack.build`, `storage.save_solve_pack`, `storage.prune_solve_packs`
- Produces: a `solve_packs` row per solved day, whose replay equals that day's cached assignments.

- [ ] **Step 1: Write the failing test**

Create `chauffeur/tests/test_negotiation_runtime.py`:

```python
"""The refresh really writes a pack, and the pack really replays.

A source-reading test proves nothing here: the refresh swallows exceptions
per-day, so a pack write that raises would leave the schedule looking fine and
the negotiator permanently empty. This RUNS the write path.
"""
import datetime

from harness import check
from models.schemas import Driver, Event
from services import solve_pack, storage


def _event(eid, start, title='Practice'):
    return Event(id=eid, title=title, start=start,
                 end=start + datetime.timedelta(hours=1),
                 location='Field', calendar_ids=['c1'], source_event_ids=[eid])


def scenario_pack_write_survives_the_refresh_shape():
    """Build a pack from the same argument shapes the refresh passes, write it
    the way the refresh writes it, and replay it. Any signature drift between
    solve_pack.build and its caller shows up here."""
    monday = datetime.datetime(2026, 9, 7, 17, 0)
    events = [_event('e1', monday)]
    drivers = [Driver(id='d1', name='Jeff', home_location='Home')]
    pack = solve_pack.build(
        '2026-09-07', events=events, drivers=drivers, rules=[],
        priority_rules=[], overrides=[], passengers=[], cars=[],
        driver_events={'d1': []}, trip_metadata=[], driver_passenger_map={},
        previous_assignments={}, load_balancing=False,
        load_balancing_metric='occupied_time', protected_rule_index={})
    storage.save_solve_pack('2026-09-07', pack)
    out = solve_pack.replay(storage.get_solve_pack('2026-09-07'))
    check(out['assignments'].get('e1') == 'd1',
          f"the written pack solves the day, got {out['assignments']}")


def scenario_old_packs_are_pruned():
    storage.save_solve_pack('2026-09-01', solve_pack.build(
        '2026-09-01', events=[], drivers=[], rules=[], priority_rules=[],
        overrides=[], passengers=[], cars=[], driver_events={},
        trip_metadata=[], driver_passenger_map={}, previous_assignments={},
        load_balancing=False, load_balancing_metric='occupied_time',
        protected_rule_index={}))
    storage.prune_solve_packs('2026-09-07')
    check(storage.get_solve_pack('2026-09-01') is None,
          "yesterday's pack answers no question anybody will ask")


if __name__ == '__main__':
    scenario_pack_write_survives_the_refresh_shape()
    scenario_old_packs_are_pruned()
    print("test_negotiation_runtime OK")
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd chauffeur && python tests/test_negotiation_runtime.py`
Expected: PASS for the shape scenario if Task 2 landed — but FAIL on `prune_solve_packs` only if Task 2 was skipped. If both pass, this test is not yet proving the refresh writes anything; that is what Step 3 adds.

- [ ] **Step 3: Tag the protected rules in the refresh**

In `chauffeur/main.py`, the protected commitment loop at line 15851 currently appends rules without provenance. Record which index each commitment produced. Replace the loop body:

```python
    # Protected commitments (load arc A6): a standing piece of somebody's own
    # life — the run club, therapy, choir — as recurring unavailable windows.
    # The one place an adult's time is FOR something rather than an obstacle.
    #
    # The index is for negotiation: `Rule` carries no provenance, so this is
    # the only place that knows which rule came from which commitment, and
    # without it the lift-a-protected-window lever cannot name what it lifts.
    protected_rule_index = {}
    try:
        from services import stages as _stg  # noqa: F401  (import guard parity)
        for pc in storage.get_protected_commitments():
            member = storage.get_member(pc.get('member_id')) or {}
            drv = member.get('driver_id')
            if not drv or not pc.get('days_of_week'):
                continue
            protected_rule_index[str(pc.get('id'))] = len(rules)
            rules.append(Rule(driver_id=drv, constraint_type='unavailable',
                              days_of_week=list(pc['days_of_week']),
                              time_start=pc.get('time_start'),
                              time_end=pc.get('time_end')))
            logger.info(f"Protected: {pc.get('title')} -> driver {drv} "
                        f"unavailable {pc.get('days_of_week')} "
                        f"{pc.get('time_start')}-{pc.get('time_end')}")
    except Exception as _pce:
        logger.warning(f"Protected-commitment injection failed: {_pce}")
```

- [ ] **Step 4: Write the pack after each day's solve**

In `chauffeur/main.py`, immediately after the `base_schedules[date_str] = {...}` block ends (line 16995) and before `previous_assignments.update(assignments)`:

```python
        # Negotiation's solve pack: what this day's solve was actually given.
        # Written here because this is the only point where every input is in
        # hand at once. Never fatal — a family whose pack write fails still
        # gets their schedule; they just get no deals until the next refresh.
        if not draft:
            try:
                from services import solve_pack as _pack
                storage.save_solve_pack(date_str, _pack.build(
                    date_str,
                    events=daily_events_to_solve, drivers=drivers, rules=rules,
                    priority_rules=priority_rules, overrides=overrides,
                    passengers=passengers, cars=cars,
                    driver_events=driver_events_map,
                    trip_metadata=trip_metadata,
                    driver_passenger_map=driver_passenger_map,
                    previous_assignments=previous_assignments,
                    load_balancing=load_balancing,
                    load_balancing_metric=load_balancing_metric,
                    protected_rule_index=protected_rule_index))
            except Exception as _pe:
                logger.warning(f"Solve pack write failed for {date_str}: {_pe}")
```

And once per refresh, after the day loop finishes (beside `schedule_coordinator.clear_solving_dates()` at line 17092):

```python
    try:
        storage.prune_solve_packs(datetime.date.today().isoformat())
    except Exception as _ppe:
        logger.warning(f"Solve pack prune failed: {_ppe}")
```

Note `previous_assignments` is captured **before** the `.update(assignments)` on the following line — that is the value the solve was given, and the order matters for replay fidelity.

- [ ] **Step 5: Run the tests**

Run: `cd chauffeur && python tests/test_negotiation_runtime.py && python tests/test_solve_pack.py`
Expected: both PASS.

- [ ] **Step 6: Run the full suite, then commit**

Run: `cd chauffeur && python tools/test.py`

Bump `chauffeur/config.yaml` to `2.431.2`, then:

```bash
git add -A && git commit -F - <<'EOF'
The refresh hands the negotiator its world

Each solved day writes a pack, at the one point where every solver input is in
hand at once. Protected-commitment rules are tagged with the commitment that
produced them, because Rule carries no provenance and without the tag the
lift-a-protected-window lever cannot name what it is lifting.

previous_assignments is captured before the day loop updates it -- that is the
value the solve was given, and the order is the difference between a faithful
replay and a plausible one. A failed pack write is logged, never fatal: the
family still gets their schedule, they just get no deals until next refresh.

(v2.431.2)
EOF
git push
```

---

### Task 4: The levers — generating candidates

**Files:**
- Create: `chauffeur/services/negotiation.py`
- Test: `chauffeur/tests/test_negotiation_levers.py`

**Interfaces:**
- Consumes: `solve_pack.apply`, `solve_pack.replay`, `coverage_options.driver_options`, `storage.get_protected_commitments`, `storage.get_all_members`
- Produces:
  - `negotiation.candidates(pack: dict, seed_event_id: str) -> list[dict]` — each `{'mutations': [...], 'parts': [{'member_id', 'lever', 'payload', 'ask_text'}], 'give_up': int}`, ordered cheapest-first by predicted cost, before any solving.
  - `negotiation.WINDOW_MINS = 90`, `negotiation.SHIFT_STEPS = (-15, 15, -30, 30)`
  - `negotiation.GIVE_UP = {'shift_15': 1, 'shift_30': 2, 'skip_optional': 2, 'swap_drive': 3, 'lift_protected': 5}`

- [ ] **Step 1: Write the failing test**

Create `chauffeur/tests/test_negotiation_levers.py`:

```python
"""What the negotiator is allowed to propose, and what it never proposes."""
import datetime

from harness import check
from models.schemas import Driver, Event
from services import negotiation, solve_pack, storage

MONDAY = datetime.datetime(2026, 9, 7, 17, 0)


def _event(eid, start, title='Practice', mins=60, optional=False):
    ev = Event(id=eid, title=title, start=start,
               end=start + datetime.timedelta(minutes=mins),
               location='Field', calendar_ids=['c1'], source_event_ids=[eid])
    if optional:
        ev.app_config = {'is_optional': True}
    return ev


def _pack(events, drivers, rules=None, protected_index=None):
    return solve_pack.build(
        '2026-09-07', events=events, drivers=drivers, rules=rules or [],
        priority_rules=[], overrides=[], passengers=[], cars=[],
        driver_events={}, trip_metadata=[], driver_passenger_map={},
        previous_assignments={}, load_balancing=False,
        load_balancing_metric='occupied_time',
        protected_rule_index=protected_index or {})


def scenario_shift_candidates_stay_in_the_window():
    near = _event('near', MONDAY + datetime.timedelta(minutes=30), 'Piano')
    far = _event('far', MONDAY + datetime.timedelta(hours=6), 'Book club')
    pack = _pack([_event('seed', MONDAY), near, far],
                 [Driver(id='d1', name='Jeff', home_location='Home')])
    shifts = [c for c in negotiation.candidates(pack, 'seed')
              if any(m['lever'] == 'shift_event' for m in c['mutations'])]
    moved = {m['event_id'] for c in shifts for m in c['mutations']}
    check('near' in moved, f"a neighbour in the window is movable, got {moved}")
    check('far' not in moved,
          f"an event six hours away has nothing to do with this, got {moved}")


def scenario_a_skip_only_targets_an_optional():
    optional = _event('opt', MONDAY + datetime.timedelta(minutes=20),
                      'Extra practice', optional=True)
    required = _event('req', MONDAY + datetime.timedelta(minutes=25), 'Dentist')
    pack = _pack([_event('seed', MONDAY), optional, required],
                 [Driver(id='d1', name='Jeff', home_location='Home')])
    skipped = {m['event_id'] for c in negotiation.candidates(pack, 'seed')
               for m in c['mutations'] if m['lever'] == 'skip_optional'}
    check(skipped == {'opt'},
          f"only what the family already called optional, got {skipped}")


def scenario_cheap_candidates_come_first():
    pack = _pack([_event('seed', MONDAY),
                  _event('near', MONDAY + datetime.timedelta(minutes=30))],
                 [Driver(id='d1', name='Jeff', home_location='Home'),
                  Driver(id='d2', name='Lorena', home_location='Home')])
    give_ups = [c['give_up'] for c in negotiation.candidates(pack, 'seed')]
    check(give_ups == sorted(give_ups),
          f"the queue is ordered before anything is solved, got {give_ups}")


def scenario_a_refused_shift_is_never_proposed_again():
    near = _event('near', MONDAY + datetime.timedelta(minutes=30), 'Piano')
    pack = _pack([_event('seed', MONDAY), near],
                 [Driver(id='d1', name='Jeff', home_location='Home')])
    storage.add_shift_refusal('near', 'Piano')
    moved = {m['event_id'] for c in negotiation.candidates(pack, 'seed')
             for m in c['mutations'] if m['lever'] == 'shift_event'}
    check('near' not in moved,
          f"somebody already said that cannot move, got {moved}")


def scenario_every_part_names_a_person():
    pack = _pack([_event('seed', MONDAY),
                  _event('near', MONDAY + datetime.timedelta(minutes=30))],
                 [Driver(id='d1', name='Jeff', home_location='Home')])
    for c in negotiation.candidates(pack, 'seed'):
        for p in c['parts']:
            check(p.get('ask_text'), f"a part with no question is not an ask: {p}")
            check('lever' in p, f"and it knows what it is asking for: {p}")


if __name__ == '__main__':
    scenario_shift_candidates_stay_in_the_window()
    scenario_a_skip_only_targets_an_optional()
    scenario_cheap_candidates_come_first()
    scenario_a_refused_shift_is_never_proposed_again()
    scenario_every_part_names_a_person()
    print("test_negotiation_levers OK")
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd chauffeur && python tests/test_negotiation_levers.py`
Expected: FAIL — `ImportError: cannot import name 'negotiation' from 'services'`

- [ ] **Step 3: Add the refusal memory to storage**

In `chauffeur/services/storage.py`, add the table beside the others:

```python
    shift_refusals_table = db.table('shift_refusals')
```

And the CRUD:

```python
# --- Shift refusals: the movable flag, learned rather than declared -------
# The app cannot know that moving a calendar record moves the actual practice,
# and guessing wrong produces a deal that makes the family look ridiculous to a
# coach. So the ask is the gate -- and a no is remembered, per series, so the
# same question is not asked twice.

def add_shift_refusal(series_key: str, title: str = '', member_id: str = None):
    with db_lock:
        shift_refusals_table.upsert(
            {'series_key': str(series_key), 'title': title or '',
             'refused_by': member_id or '', 'refused_at': time.time()},
            Query().series_key == str(series_key))

def get_shift_refusals() -> List[dict]:
    with db_lock:
        return [dict(r) for r in shift_refusals_table.all()]

def clear_shift_refusal(series_key: str) -> bool:
    """A flag the app taught itself must be untaught by hand."""
    with db_lock:
        return bool(shift_refusals_table.remove(
            Query().series_key == str(series_key)))
```

In `chauffeur/services/storage_sqlite.py`, add to the index registry:

```python
    # Shift refusals: read whole on every negotiation, written once per no.
    "shift_refusals": [["series_key"]],
```

- [ ] **Step 4: Write the candidate generator**

Create `chauffeur/services/negotiation.py`:

```python
"""Negotiation — the smallest change that makes a day work, and who must agree.

The app has always been asked one question: *who drives?* When the answer is
nobody, `services/coverage_options.py` softens it with a ladder, but every rung
still hands the problem back to a parent.

This module asks the second question. The constraints are already in the model,
so a candidate is nothing more than the same day with one thing changed --
re-solved, and kept only if it actually works. What makes it a *negotiation*
rather than an optimisation is that every change costs a named person
something, and that person is asked.

Four levers, all occurrence-scoped, because a lever that reaches other days
would invalidate the single-day validation below:

    shift_event     move an event by a quarter or half hour
    lift_protected  give up ONE occurrence of a standing commitment
    swap_drive      take on a drive that was not yours
    skip_optional   do not go, this once

The prices in `GIVE_UP` are the design, not tuning. Lifting a protected window
is the most expensive thing the negotiator can ask for, because protected time
is the one place an adult's time is FOR something rather than an obstacle.
"""
import datetime

from services import coverage_options, solve_pack, storage

# Either side of the seed. A change further away than this is not plausibly
# about the seed, and proposing it reads as the app rummaging.
WINDOW_MINS = 90

# Ordered cheapest-first: a quarter hour is a smaller thing to ask than half.
SHIFT_STEPS = (-15, 15, -30, 30)

GIVE_UP = {'shift_15': 1, 'shift_30': 2, 'skip_optional': 2,
           'swap_drive': 3, 'lift_protected': 5}


def _dt(raw):
    try:
        return datetime.datetime.fromisoformat(str(raw)).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def _fmt(t):
    return t.strftime('%I:%M').lstrip('0') if t else ''


def series_key(ev: dict) -> str:
    """What makes this the same recurring thing across weeks. A refusal is
    remembered against the SERIES: 'the lesson cannot move' is a fact about the
    lesson, not about one Tuesday."""
    return str(ev.get('recurring_event_id') or ev.get('original_event_id')
               or ev.get('id'))


def _members_by_driver():
    return {str(m['driver_id']): m for m in storage.get_all_members()
            if m.get('driver_id')}


def _owner_of(ev: dict, pack: dict) -> str:
    """Whose event is this? The passenger's member if we can tell, else the
    parents — an event with no owner still costs somebody something, and an
    ask with no addressee is not an ask."""
    cals = set(ev.get('calendar_ids') or [])
    for p in pack.get('passengers') or []:
        if cals.intersection(set(p.get('calendar_ids') or [])):
            for m in storage.get_all_members():
                if str(m.get('passenger_id') or '') == str(p.get('id')):
                    return m['id']
    parents = [m for m in storage.get_all_members()
               if m.get('role') == 'parent' and not m.get('system')]
    return parents[0]['id'] if parents else ''


def _in_window(ev: dict, seed_start, seed_end) -> bool:
    start, end = _dt(ev.get('start')), _dt(ev.get('end'))
    if not start:
        return False
    end = end or start
    lo = seed_start - datetime.timedelta(minutes=WINDOW_MINS)
    hi = seed_end + datetime.timedelta(minutes=WINDOW_MINS)
    return start < hi and end > lo


def candidates(pack: dict, seed_event_id: str) -> list:
    """Every change worth trying for this seed, cheapest first.

    Ordering happens HERE, before anything is solved, because the budget is a
    cutoff on this list: the sweep's few solves must be spent on the most
    promising deals, not on a random sample of them.
    """
    events = {str(e.get('id')): e for e in pack.get('events') or []}
    seed = events.get(str(seed_event_id))
    if not seed:
        return []
    seed_start = _dt(seed.get('start'))
    if not seed_start:
        return []
    seed_end = _dt(seed.get('end')) or seed_start + datetime.timedelta(hours=1)

    refused = {r['series_key'] for r in storage.get_shift_refusals()}
    out = []

    # --- shift a neighbour, or the seed itself -----------------------------
    for ev in [seed] + [e for e in events.values()
                        if str(e.get('id')) != str(seed_event_id)]:
        if not _in_window(ev, seed_start, seed_end):
            continue
        if series_key(ev) in refused:
            continue
        owner = _owner_of(ev, pack)
        start = _dt(ev.get('start'))
        for delta in SHIFT_STEPS:
            cost = GIVE_UP['shift_15' if abs(delta) == 15 else 'shift_30']
            when = start + datetime.timedelta(minutes=delta)
            direction = 'later' if delta > 0 else 'earlier'
            out.append({
                'mutations': [{'lever': 'shift_event',
                               'event_id': str(ev.get('id')),
                               'delta_mins': delta}],
                'give_up': cost,
                'parts': [{'member_id': owner, 'lever': 'shift_event',
                           'payload': {'event_id': str(ev.get('id')),
                                       'series_key': series_key(ev),
                                       'title': ev.get('title') or 'that',
                                       'delta_mins': delta},
                           'ask_text': (f"Could {ev.get('title') or 'that'} move "
                                        f"{abs(delta)} minutes {direction}, to "
                                        f"{_fmt(when)}? It would cover "
                                        f"{seed.get('title') or 'the other drive'}.")}]})

    # --- skip something the family already called optional ------------------
    for ev in events.values():
        if str(ev.get('id')) == str(seed_event_id):
            continue
        if not (ev.get('app_config') or {}).get('is_optional'):
            continue
        if not _in_window(ev, seed_start, seed_end):
            continue
        owner = _owner_of(ev, pack)
        out.append({
            'mutations': [{'lever': 'skip_optional',
                           'event_id': str(ev.get('id'))}],
            'give_up': GIVE_UP['skip_optional'],
            'parts': [{'member_id': owner, 'lever': 'skip_optional',
                       'payload': {'event_id': str(ev.get('id')),
                                   'title': ev.get('title') or 'that'},
                       'ask_text': (f"Skip {ev.get('title') or 'that'} this once? "
                                    f"It would cover "
                                    f"{seed.get('title') or 'the other drive'}.")}]})

    # --- the reasons the ladder already found: swaps and protected windows --
    cache = {'events': list(events.values()),
             'assignments': dict(pack.get('previous_assignments') or {})}
    try:
        _free, blocked = coverage_options.driver_options(seed, cache)
    except Exception as e:
        print(f"[negotiation] driver options failed: {e}")
        blocked = []
    by_driver = _members_by_driver()
    for b in blocked:
        member = by_driver.get(str(b['id'])) or {}
        reason = b.get('reason') or ''
        if reason.startswith('driving '):
            # Somebody else takes the drive that is holding this driver.
            held = next((e for e in events.values()
                         if (e.get('title') or '') == reason[len('driving '):]), None)
            if not held:
                continue
            for d in pack.get('drivers') or []:
                if str(d.get('id')) == str(b['id']):
                    continue
                taker = by_driver.get(str(d.get('id'))) or {}
                if not taker or taker.get('status') in ('disabled', 'archived'):
                    continue
                out.append({
                    'mutations': [{'lever': 'swap_drive',
                                   'event_id': str(held.get('id')),
                                   'driver_id': str(d.get('id'))}],
                    'give_up': GIVE_UP['swap_drive'],
                    'parts': [{'member_id': taker['id'], 'lever': 'swap_drive',
                               'payload': {'event_id': str(held.get('id')),
                                           'driver_id': str(d.get('id')),
                                           'title': held.get('title') or 'that drive'},
                               'ask_text': (f"Could you take "
                                            f"{held.get('title') or 'that drive'}? "
                                            f"It frees {b.get('name')} for "
                                            f"{seed.get('title') or 'the other one'}.")}]})
            continue
        # A protected window. The most expensive thing here, on purpose.
        for pc in storage.get_protected_commitments(member_id=member.get('id')):
            if str(pc.get('id')) not in (pack.get('protected_rule_index') or {}):
                continue
            out.append({
                'mutations': [{'lever': 'lift_protected',
                               'commitment_id': str(pc.get('id'))}],
                'give_up': GIVE_UP['lift_protected'],
                'parts': [{'member_id': member.get('id'), 'lever': 'lift_protected',
                           'payload': {'commitment_id': str(pc.get('id')),
                                       'title': pc.get('title') or 'your time'},
                           'ask_text': (f"Could you give up "
                                        f"{pc.get('title') or 'your time'} just this "
                                        f"once? Nothing else covers "
                                        f"{seed.get('title') or 'the drive'}.")}]})

    out.sort(key=lambda c: (len({p['member_id'] for p in c['parts']}),
                            c['give_up']))
    return out
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd chauffeur && python tests/test_negotiation_levers.py`
Expected: PASS, printing `test_negotiation_levers OK`

- [ ] **Step 6: Run the full suite, then commit**

Run: `cd chauffeur && python tools/test.py`

Bump `chauffeur/config.yaml` to `2.431.3`, then:

```bash
git add -A && git commit -F - <<'EOF'
Four things the negotiator may ask for

Candidate generation: shift an event, skip an optional, swap a drive, lift one
occurrence of a protected window. All occurrence-scoped, all seeded from the
window around the uncovered event, all carrying the person who would have to
agree and the sentence they would be asked.

Lifting a protected window is priced the most expensive lever in the model.
Protected time is the one place an adult's time is FOR something rather than an
obstacle, and the negotiator should reach for it last.

Movability is learned, not declared: a refused shift is remembered against the
series, because the app cannot know that moving a calendar record moves the
actual practice. The queue is ordered before anything is solved, since the
budget is a cutoff on this list rather than a sample of it.

(v2.431.3)
EOF
git push
```

---

### Task 5: The search — solve the queue, rank the survivors

**Files:**
- Modify: `chauffeur/services/negotiation.py`
- Test: `chauffeur/tests/test_negotiation_cost.py`

**Interfaces:**
- Consumes: `negotiation.candidates`, `solve_pack.apply`, `solve_pack.replay`, `storage.get_deals`
- Produces:
  - `negotiation.search(pack: dict, seed_event_id: str, budget: int, exclude: set = None) -> list[dict]` — surviving deals, best first. Each `{'mutations', 'parts', 'cost': {'people', 'give_up', 'delta', 'fairness', 'total'}, 'line'}`.
  - `negotiation.part_key(part: dict) -> str` — `f"{member_id}:{lever}:{payload_id}"`, the identity used by `exclude`.
  - `negotiation.SWEEP_BUDGET = 8`, `negotiation.DEEP_BUDGET = 40`, `negotiation.FAIRNESS_DAYS = 14`

- [ ] **Step 1: Write the failing test**

Create `chauffeur/tests/test_negotiation_cost.py`:

```python
"""What survives, and which survivor wins."""
import datetime
import time

from harness import check
from models.schemas import Driver, Event
from services import negotiation, solve_pack, storage

MONDAY = datetime.datetime(2026, 9, 7, 17, 0)


def _event(eid, start, title='Practice', mins=60):
    return Event(id=eid, title=title, start=start,
                 end=start + datetime.timedelta(minutes=mins),
                 location='Field', calendar_ids=['c1'], source_event_ids=[eid])


def _pack(events, drivers, **kw):
    base = dict(rules=[], priority_rules=[], overrides=[], passengers=[],
                cars=[], driver_events={}, trip_metadata=[],
                driver_passenger_map={}, previous_assignments={},
                load_balancing=False, load_balancing_metric='occupied_time',
                protected_rule_index={})
    base.update(kw)
    return solve_pack.build('2026-09-07', events=events, drivers=drivers, **base)


def scenario_a_candidate_that_breaks_the_day_is_rejected():
    """Two events at the same hour, one driver. Nothing can cover both, so no
    candidate may be reported as a deal."""
    pack = _pack([_event('seed', MONDAY), _event('other', MONDAY, 'Dentist')],
                 [Driver(id='d1', name='Jeff', home_location='Home')])
    deals = negotiation.search(pack, 'seed', budget=8)
    for d in deals:
        check(d['cost']['people'] >= 1, f"a deal costs somebody something: {d}")
    # Whatever survives must leave 'other' covered too.
    for d in deals:
        out = solve_pack.replay(solve_pack.apply(pack, d['mutations']))
        check('other' not in out['unassigned'],
              f"fixing the seed by dropping another event is not a deal: {d}")


def scenario_one_person_beats_two():
    a = {'mutations': [], 'give_up': 9,
         'parts': [{'member_id': 'm1', 'lever': 'shift_event',
                    'payload': {'event_id': 'x'}, 'ask_text': 'a'}]}
    b = {'mutations': [], 'give_up': 1,
         'parts': [{'member_id': 'm1', 'lever': 'shift_event',
                    'payload': {'event_id': 'x'}, 'ask_text': 'a'},
                   {'member_id': 'm2', 'lever': 'swap_drive',
                    'payload': {'event_id': 'y'}, 'ask_text': 'b'}]}
    ranked = sorted([b, a], key=lambda c: negotiation._rank(c, objective_delta=0.0))
    check(ranked[0] is a,
          "a one-person deal beats a two-person deal even when it costs more")


def scenario_a_shift_beats_a_protected_lift():
    shift = {'mutations': [], 'give_up': negotiation.GIVE_UP['shift_15'],
             'parts': [{'member_id': 'm1', 'lever': 'shift_event',
                        'payload': {'event_id': 'x'}, 'ask_text': 'a'}]}
    lift = {'mutations': [], 'give_up': negotiation.GIVE_UP['lift_protected'],
            'parts': [{'member_id': 'm2', 'lever': 'lift_protected',
                       'payload': {'commitment_id': 'c'}, 'ask_text': 'b'}]}
    ranked = sorted([lift, shift], key=lambda c: negotiation._rank(c, 0.0))
    check(ranked[0] is shift,
          "somebody's own evening is the last thing the negotiator asks for")


def scenario_fairness_counts_recent_asks():
    storage.deals_table.truncate()
    storage.add_deal({'date': '2026-09-06', 'seed_event_id': 'old',
                      'state': 'dead',
                      'parts': [{'id': 'p1', 'member_id': 'm2',
                                 'lever': 'shift_event', 'payload': {},
                                 'ask_text': '', 'state': 'declined'}]})
    check(negotiation._fairness('m2') >= 1,
          "somebody asked recently is asked less readily")
    check(negotiation._fairness('m1') == 0, "and somebody who has not is not")


def scenario_budget_caps_the_solves():
    pack = _pack([_event('seed', MONDAY),
                  _event('n1', MONDAY + datetime.timedelta(minutes=20)),
                  _event('n2', MONDAY + datetime.timedelta(minutes=40)),
                  _event('n3', MONDAY + datetime.timedelta(minutes=60))],
                 [Driver(id='d1', name='Jeff', home_location='Home')])
    seen = []
    real = solve_pack.replay
    solve_pack.replay = lambda p, **kw: (seen.append(1), real(p, **kw))[1]
    try:
        negotiation.search(pack, 'seed', budget=3)
    finally:
        solve_pack.replay = real
    check(len(seen) <= 3, f"the budget is a ceiling, not a suggestion: {len(seen)}")


if __name__ == '__main__':
    scenario_a_candidate_that_breaks_the_day_is_rejected()
    scenario_one_person_beats_two()
    scenario_a_shift_beats_a_protected_lift()
    scenario_fairness_counts_recent_asks()
    scenario_budget_caps_the_solves()
    print("test_negotiation_cost OK")
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd chauffeur && python tests/test_negotiation_cost.py`
Expected: FAIL — `AttributeError: module 'services.negotiation' has no attribute 'search'`

- [ ] **Step 3: Add the deals table (needed by fairness)**

In `chauffeur/services/storage.py`:

```python
    deals_table = db.table('deals')
```

```python
# --- Deals: a set of parts, each one a person giving something up --------
# Parts live inside the deal row rather than in a table of their own: a part
# has no life outside its deal, and the thing every caller actually wants is
# "the deal this part belongs to".

def add_deal(data: dict) -> str:
    from models.schemas import Deal
    with db_lock:
        row = Deal(**data).model_dump()
        deals_table.insert(row)
        return row['id']

def get_deal(deal_id: str) -> Optional[dict]:
    with db_lock:
        res = deals_table.search(Query().id == deal_id)
        return dict(res[0]) if res else None

def get_deals(state: str = None, since_ts: float = None,
              seed_event_id: str = None) -> List[dict]:
    with db_lock:
        rows = [dict(d) for d in deals_table.all()]
    if state:
        rows = [d for d in rows if d.get('state') == state]
    if since_ts is not None:
        rows = [d for d in rows if (d.get('created_at') or 0) >= since_ts]
    if seed_event_id:
        rows = [d for d in rows if str(d.get('seed_event_id')) == str(seed_event_id)]
    rows.sort(key=lambda d: d.get('created_at') or 0, reverse=True)
    return rows

def update_deal(deal_id: str, data: dict) -> bool:
    with db_lock:
        return bool(deals_table.update(data, Query().id == deal_id))

def get_deal_by_part(part_id: str) -> Optional[dict]:
    with db_lock:
        for row in deals_table.all():
            for p in (row.get('parts') or []):
                if str(p.get('id')) == str(part_id):
                    return dict(row)
    return None

def update_deal_part(part_id: str, data: dict) -> bool:
    row = get_deal_by_part(part_id)
    if not row:
        return False
    parts = []
    for p in row.get('parts') or []:
        parts.append({**p, **data} if str(p.get('id')) == str(part_id) else p)
    return update_deal(row['id'], {'parts': parts})
```

In `chauffeur/models/schemas.py`, next to `Thread`:

```python
class Deal(BaseModel):
    """A set of parts that together make a broken day work.

    A part is one person giving up one concrete thing. The deal applies only
    when every part has been agreed to by the person it costs — a schedule that
    works because somebody was volunteered is not a schedule that works.
    """
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    date: str                                # YYYY-MM-DD, the day it fixes
    seed_event_id: str                       # what was uncovered
    seed_title: str = ""
    line: str = ""                           # the sentence a parent reads
    parts: List[Dict[str, Any]] = Field(default_factory=list)
    cost: Dict[str, Any] = Field(default_factory=dict)
    mutations: List[Dict[str, Any]] = Field(default_factory=list)
    # draft: found, nobody asked yet. asking: requests are out.
    # accepted: every part said yes. applied: the change was made.
    # dead: somebody declined or a person killed it. expired: too late.
    state: str = 'draft'
    created_at: float = Field(default_factory=time.time)
    applied_at: Optional[float] = None
    dead_reason: Optional[str] = None
```

In `chauffeur/services/storage_sqlite.py`:

```python
    # Deals: read by state on every sweep, and by the part a request answers.
    "deals": [["id"], ["state"], ["seed_event_id"]],
```

- [ ] **Step 4: Write the search**

Append to `chauffeur/services/negotiation.py`:

```python
# How many re-solves a question is allowed. The sweep runs unattended and must
# never be the reason a schedule refresh feels slow; the on-demand path has a
# person waiting on purpose and can afford to go further down the same queue.
SWEEP_BUDGET = 8
DEEP_BUDGET = 40

# How far back fairness looks. Long enough that "you did it last time" is
# still true, short enough that a month-old favour stops counting.
FAIRNESS_DAYS = 14

# The objective is in the millions (a base assignment reward of 1,000,000 and
# an attendance term of 50,000,000), and it is identical across candidates for
# the same event, so what is left after subtraction is routing and priority
# degradation. Scaled down and capped hard: it breaks ties, it never decides.
DELTA_SCALE = 1000.0
DELTA_CAP = 4.0


def part_key(part: dict) -> str:
    payload = part.get('payload') or {}
    subject = (payload.get('event_id') or payload.get('commitment_id') or '')
    return f"{part.get('member_id')}:{part.get('lever')}:{subject}"


def _fairness(member_id: str) -> int:
    """How many times this person has been asked to give something up lately.

    Counted from recorded deals, so it is a real count. Nothing here is
    estimated — a made-up fairness number would be worse than none.
    """
    since = datetime.datetime.now().timestamp() - FAIRNESS_DAYS * 86400
    n = 0
    for d in storage.get_deals(since_ts=since):
        for p in d.get('parts') or []:
            if str(p.get('member_id')) == str(member_id):
                n += 1
    return n


def _rank(candidate: dict, objective_delta: float):
    """The sort key. People disturbed comes first and is not tradeable."""
    people = sorted({p['member_id'] for p in candidate['parts']})
    fairness = sum(_fairness(m) for m in people)
    delta = min(max(objective_delta, 0.0) / DELTA_SCALE, DELTA_CAP)
    return (len(people), candidate['give_up'] + delta + fairness)


def _cost(candidate: dict, objective_delta: float) -> dict:
    people = sorted({p['member_id'] for p in candidate['parts']})
    fairness = sum(_fairness(m) for m in people)
    delta = min(max(objective_delta, 0.0) / DELTA_SCALE, DELTA_CAP)
    return {'people': len(people), 'give_up': candidate['give_up'],
            'delta': round(delta, 3), 'fairness': fairness,
            'total': round(candidate['give_up'] + delta + fairness, 3)}


def _line(candidate: dict, seed_title: str, when: str) -> str:
    asks = '; '.join(p['ask_text'] for p in candidate['parts'])
    return f"🤝 {seed_title} ({when}) works if — {asks}"


def search(pack: dict, seed_event_id: str, budget: int = SWEEP_BUDGET,
           exclude: set = None) -> list:
    """Solve down the candidate queue and return what actually worked.

    A candidate survives only if the seed ends up covered AND nothing else on
    the day was broken to do it. Validation is this one day, which is sound
    only because every lever is occurrence-scoped: none of them reaches another
    day's pack. If a series-level lever is ever added, this must widen with it.
    """
    exclude = set(exclude or ())
    events = {str(e.get('id')): e for e in pack.get('events') or []}
    seed = events.get(str(seed_event_id))
    if not seed:
        return []
    seed_start = _dt(seed.get('start'))
    when = seed_start.strftime('%a %I:%M %p').replace(' 0', ' ') if seed_start else ''
    seed_title = seed.get('title') or 'That drive'

    try:
        base = solve_pack.replay(pack)
    except ValueError as e:
        print(f"[negotiation] no usable pack for {pack.get('date')}: {e}")
        return []
    baseline_broken = set(base['unassigned'])
    baseline_objective = base['objective']

    out = []
    spent = 0
    for cand in candidates(pack, seed_event_id):
        if spent >= budget:
            break
        if any(part_key(p) in exclude for p in cand['parts']):
            continue
        try:
            result = solve_pack.replay(solve_pack.apply(pack, cand['mutations']))
        except Exception as e:
            print(f"[negotiation] candidate failed: {e}")
            continue
        spent += 1
        broken = set(result['unassigned'])
        if str(seed_event_id) in broken:
            continue
        # Nothing new may break. Something already broken that STAYS broken is
        # not this candidate's fault and does not disqualify it.
        if broken - baseline_broken:
            continue
        if len(result.get('conflicts') or {}) > len(base.get('conflicts') or {}):
            continue
        delta = baseline_objective - result['objective']
        out.append({'mutations': cand['mutations'], 'parts': cand['parts'],
                    'cost': _cost(cand, delta),
                    'line': _line(cand, seed_title, when),
                    'give_up': cand['give_up']})
    out.sort(key=lambda c: (c['cost']['people'], c['cost']['total']))
    return out
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd chauffeur && python tests/test_negotiation_cost.py`
Expected: PASS, printing `test_negotiation_cost OK`

- [ ] **Step 6: Run the full suite, then commit**

Run: `cd chauffeur && python tools/test.py`

Bump `chauffeur/config.yaml` to `2.431.4`, then:

```bash
git add -A && git commit -F - <<'EOF'
Solve the queue, keep what actually works

A candidate survives only if the seed ends up covered and nothing else on the
day was broken to do it. Something already broken that stays broken is not the
candidate's fault and does not disqualify it.

Ranking is two-tier. People disturbed comes first and is not tradeable against
routing: a one-person deal beats a two-person deal whatever the numbers say.
Among deals costing the same number of people, the blend is what each person
actually loses, plus a fairness count of how often they have been asked lately,
plus the objective delta scaled down and capped -- it breaks ties, it never
decides.

Validation is one day, which is sound only while every lever stays
occurrence-scoped. That is the tripwire if a fifth lever is ever added.

(v2.431.4)
EOF
git push
```

---

### Task 6: Consent — parts become requests, and nothing applies early

**Files:**
- Modify: `chauffeur/services/negotiation.py`, `chauffeur/services/requests.py:103-129`
- Test: `chauffeur/tests/test_negotiation_consent.py`

**Interfaces:**
- Consumes: `requests.create`, `storage.add_deal`, `storage.update_deal_part`, `calendar.patch_event`, `optional_events.record_decision`, `storage.add_override`, `storage.add_protected_exception`
- Produces:
  - `negotiation.propose(date_str, seed_event_id, budget) -> Optional[dict]` — searches, stores the winner as a `draft` deal, returns it. Reuses an open deal for that seed rather than re-solving.
  - `negotiation.start_asks(deal_id, actor_member_id) -> dict` — one request per part; deal goes `asking`.
  - `negotiation.accept_part(part_id, member_id) -> dict`
  - `negotiation.decline_part(part_id, member_id, reason='') -> dict`
  - `negotiation.kill(deal_id, member_id, reason='') -> dict`
  - `storage.add_protected_exception(commitment_id, date_str)`, `storage.get_protected_exceptions(commitment_id=None)`

- [ ] **Step 1: Write the failing test**

Create `chauffeur/tests/test_negotiation_consent.py`:

```python
"""Nothing happens to anybody's day until everybody has said yes."""
import datetime

from harness import check
from services import negotiation, storage

TODAY = datetime.date(2026, 9, 7).isoformat()


def _deal(parts_states=('open', 'open')):
    parts = []
    for i, st in enumerate(parts_states):
        parts.append({'id': f'p{i}', 'member_id': f'm{i}',
                      'lever': 'skip_optional',
                      'payload': {'event_id': f'e{i}', 'title': 'Extra practice'},
                      'ask_text': 'Skip it?', 'state': st, 'request_id': None})
    return storage.add_deal({'date': TODAY, 'seed_event_id': 'seed',
                             'seed_title': 'Soccer', 'line': 'a deal',
                             'parts': parts, 'state': 'asking'})


def scenario_one_yes_applies_nothing():
    applied = []
    real = negotiation._apply_part
    negotiation._apply_part = lambda part, deal: applied.append(part['id'])
    try:
        did = _deal()
        negotiation.accept_part('p0', 'm0')
        check(applied == [],
              f"a partly agreed deal changes nothing, got {applied}")
        row = storage.get_deal(did)
        check(row['state'] == 'asking', f"and stays open, got {row['state']}")
    finally:
        negotiation._apply_part = real


def scenario_the_last_yes_applies_the_whole_deal():
    applied = []
    real = negotiation._apply_part
    negotiation._apply_part = lambda part, deal: applied.append(part['id'])
    try:
        did = _deal()
        negotiation.accept_part('p0', 'm0')
        negotiation.accept_part('p1', 'm1')
        check(sorted(applied) == ['p0', 'p1'],
              f"every part is applied together, got {applied}")
        check(storage.get_deal(did)['state'] == 'applied',
              "and the deal says so")
    finally:
        negotiation._apply_part = real


def scenario_one_no_kills_the_deal():
    did = _deal()
    negotiation.decline_part('p0', 'm0', reason='in a meeting')
    row = storage.get_deal(did)
    check(row['state'] == 'dead', f"one decline ends it, got {row['state']}")
    check('meeting' in (row.get('dead_reason') or ''),
          f"and the reason travels with it, got {row.get('dead_reason')}")


def scenario_a_refused_shift_is_remembered_against_the_series():
    did = storage.add_deal({
        'date': TODAY, 'seed_event_id': 'seed', 'seed_title': 'Soccer',
        'parts': [{'id': 'px', 'member_id': 'm0', 'lever': 'shift_event',
                   'payload': {'event_id': 'e9', 'series_key': 'series-9',
                               'title': 'Piano', 'delta_mins': 15},
                   'ask_text': 'Move it?', 'state': 'open', 'request_id': None}],
        'state': 'asking'})
    negotiation.decline_part('px', 'm0', reason="the lesson can't move")
    keys = {r['series_key'] for r in storage.get_shift_refusals()}
    check('series-9' in keys, f"the app learns what cannot move, got {keys}")
    check(storage.get_deal(did)['state'] == 'dead', "and the deal is over")


def scenario_a_person_can_kill_a_deal_by_hand():
    did = _deal()
    negotiation.kill(did, 'm0', reason='not worth it')
    check(storage.get_deal(did)['state'] == 'dead', "a deal can be dropped")


if __name__ == '__main__':
    scenario_one_yes_applies_nothing()
    scenario_the_last_yes_applies_the_whole_deal()
    scenario_one_no_kills_the_deal()
    scenario_a_refused_shift_is_remembered_against_the_series()
    scenario_a_person_can_kill_a_deal_by_hand()
    print("test_negotiation_consent OK")
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd chauffeur && python tests/test_negotiation_consent.py`
Expected: FAIL — `AttributeError: module 'services.negotiation' has no attribute 'accept_part'`

- [ ] **Step 3: Add the protected-exception store**

In `chauffeur/services/storage.py`:

```python
    protected_exceptions_table = db.table('protected_exceptions')
```

```python
# --- Protected exceptions: one evening given up, not a commitment deleted --
# A negotiated lift is for ONE date. Deleting the commitment would turn a
# favour into a permanent loss of the one thing on the calendar that is a
# person's own.

def add_protected_exception(commitment_id: str, date_str: str) -> str:
    with db_lock:
        row = {'commitment_id': str(commitment_id), 'date': str(date_str),
               'created_at': time.time()}
        protected_exceptions_table.upsert(
            row, (Query().commitment_id == str(commitment_id))
                 & (Query().date == str(date_str)))
        return f"{commitment_id}:{date_str}"

def get_protected_exceptions(commitment_id: str = None) -> List[dict]:
    with db_lock:
        rows = [dict(r) for r in protected_exceptions_table.all()]
    if commitment_id:
        rows = [r for r in rows if str(r.get('commitment_id')) == str(commitment_id)]
    return rows
```

In `chauffeur/services/storage_sqlite.py`:

```python
    "protected_exceptions": [["commitment_id"], ["date"]],
```

And in `chauffeur/main.py`, the protected-commitment injection loop must honour an exception. Inside the loop, after resolving `drv`, before appending:

```python
            # A negotiated lift gives up ONE evening. The commitment survives;
            # this date does not get its unavailable rule.
            if any(str(x.get('date')) == date_str
                   for x in storage.get_protected_exceptions(pc.get('id'))):
                logger.info(f"Protected: {pc.get('title')} lifted for {date_str}")
                continue
```

> The injection loop runs once per refresh, not per day, so `date_str` is not in scope there. Move the exception check into the per-day loop instead: build `rules` as today, and inside the day loop filter the day's rule list before solving:
>
> ```python
>         # A negotiated lift gives up ONE evening (services/negotiation.py).
>         lifted = {str(x['commitment_id'])
>                   for x in storage.get_protected_exceptions()
>                   if str(x.get('date')) == date_str}
>         day_rules = rules
>         if lifted:
>             drop = {protected_rule_index[c] for c in lifted
>                     if c in protected_rule_index}
>             day_rules = [r for i, r in enumerate(rules) if i not in drop]
> ```
>
> Then pass `day_rules` to `matcher.solve_schedule` and to `solve_pack.build`, and rebuild `protected_rule_index` for the pack so its indices match `day_rules`:
>
> ```python
>         day_protected_index = {}
>         if lifted:
>             offset = 0
>             for cid, idx in protected_rule_index.items():
>                 if cid in lifted:
>                     offset += 1
>                     continue
>                 day_protected_index[cid] = idx - offset
>         else:
>             day_protected_index = dict(protected_rule_index)
> ```

- [ ] **Step 4: Write the lifecycle**

Append to `chauffeur/services/negotiation.py`:

```python
# --- The deal, and the way people agree to it ----------------------------
# Every part is agreed to by the person it costs. A schedule that works because
# somebody was volunteered is not a schedule that works, so a partly agreed
# deal changes nothing at all — not the calendar, not the overrides, nothing.


def propose(date_str: str, seed_event_id: str,
            budget: int = SWEEP_BUDGET) -> dict:
    """The best deal for this seed, stored as a draft. Nobody is asked yet.

    An open deal for the same seed is REUSED rather than re-solved: the sweep
    runs constantly, and re-searching a seed the family is already looking at
    would burn the budget re-deciding a question that is already on their
    screen.
    """
    for existing in storage.get_deals(seed_event_id=seed_event_id):
        if existing.get('state') in ('draft', 'asking'):
            return existing
    pack = storage.get_solve_pack(date_str)
    if not pack:
        return None
    found = search(pack, seed_event_id, budget=budget)
    if not found:
        return None
    best = found[0]
    events = {str(e.get('id')): e for e in pack.get('events') or []}
    seed = events.get(str(seed_event_id)) or {}
    parts = []
    for i, p in enumerate(best['parts']):
        parts.append({**p, 'id': f"{seed_event_id}-{i}-{int(datetime.datetime.now().timestamp())}",
                      'state': 'open', 'request_id': None})
    deal_id = storage.add_deal({
        'date': date_str, 'seed_event_id': str(seed_event_id),
        'seed_title': seed.get('title') or '', 'line': best['line'],
        'parts': parts, 'cost': best['cost'], 'mutations': best['mutations'],
        'state': 'draft'})
    return storage.get_deal(deal_id)


def start_asks(deal_id: str, actor_member_id: str = None) -> dict:
    """Send the asks. A person does this — never the sweep, never the model."""
    from services import requests as _req
    deal = storage.get_deal(deal_id)
    if not deal:
        return {'status': 'error', 'message': 'That deal is no longer here.'}
    if deal.get('state') != 'draft':
        return {'status': 'error',
                'message': f"That one is already {deal.get('state')}."}
    parts = []
    for p in deal.get('parts') or []:
        req = _req.create(from_member_id=actor_member_id or '',
                          body=p['ask_text'], kind='deal_part',
                          to_member_id=p['member_id'], subject_ref=p['id'],
                          subject_label=deal.get('seed_title') or 'the schedule')
        parts.append({**p, 'request_id': (req or {}).get('id')})
    storage.update_deal(deal_id, {'parts': parts, 'state': 'asking'})
    who = len({p['member_id'] for p in parts})
    return {'status': 'success', 'deal_id': deal_id,
            'message': f"Asked {who} {'person' if who == 1 else 'people'} — "
                       f"nothing changes until everyone says yes."}


def accept_part(part_id: str, member_id: str = None) -> dict:
    deal = storage.get_deal_by_part(part_id)
    if not deal:
        return {'status': 'error', 'message': 'That ask is no longer here.'}
    if deal.get('state') != 'asking':
        return {'status': 'error',
                'message': f"That deal is {deal.get('state')} — nothing to agree to."}
    storage.update_deal_part(part_id, {'state': 'accepted'})
    deal = storage.get_deal(deal['id'])
    if any(p.get('state') != 'accepted' for p in deal.get('parts') or []):
        waiting = [p['member_id'] for p in deal['parts']
                   if p.get('state') != 'accepted']
        return {'status': 'success', 'applied': False,
                'message': f"Got it — still waiting on {len(waiting)}."}
    for p in deal['parts']:
        try:
            _apply_part(p, deal)
        except Exception as e:
            print(f"[negotiation] applying {p.get('lever')} failed: {e}")
            storage.update_deal(deal['id'], {
                'state': 'dead',
                'dead_reason': f"couldn't apply the {p.get('lever')} part: {e}"})
            return {'status': 'error',
                    'message': "Everyone agreed, but I couldn't make the "
                               "change — worth a look."}
    storage.update_deal(deal['id'], {
        'state': 'applied',
        'applied_at': datetime.datetime.now().timestamp()})
    return {'status': 'success', 'applied': True, 'schedule_dirty': True,
            'message': f"✓ {deal.get('seed_title') or 'That day'} is covered."}


def decline_part(part_id: str, member_id: str = None, reason: str = '') -> dict:
    """A no ends the deal — blamelessly, and with the reason kept.

    A refused shift also teaches the app something permanent: that series
    cannot move. That is the movable flag, earned rather than declared.
    """
    deal = storage.get_deal_by_part(part_id)
    if not deal:
        return {'status': 'error', 'message': 'That ask is no longer here.'}
    part = next((p for p in deal.get('parts') or []
                 if str(p.get('id')) == str(part_id)), None)
    storage.update_deal_part(part_id, {'state': 'declined'})
    if part and part.get('lever') == 'shift_event':
        payload = part.get('payload') or {}
        if payload.get('series_key'):
            storage.add_shift_refusal(payload['series_key'],
                                      payload.get('title') or '',
                                      member_id)
    storage.update_deal(deal['id'], {
        'state': 'dead',
        'dead_reason': (reason or '').strip() or 'somebody could not'})
    return {'status': 'success', 'message': "That's fine — I'll look again."}


def kill(deal_id: str, member_id: str = None, reason: str = '') -> dict:
    deal = storage.get_deal(deal_id)
    if not deal:
        return {'status': 'error', 'message': 'That deal is no longer here.'}
    storage.update_deal(deal_id, {'state': 'dead',
                                  'dead_reason': (reason or '').strip() or 'dropped'})
    return {'status': 'success', 'message': 'Dropped it.'}


def _apply_part(part: dict, deal: dict):
    """Make the change this part promised. Called only when EVERY part is in."""
    from services import calendar as _cal, optional_events as _opt
    lever, payload = part.get('lever'), part.get('payload') or {}
    if lever == 'shift_event':
        sched = storage.get_cached_schedule() or {}
        ev = next((e for e in (sched.get('events') or [])
                   if str(e.get('id')) == str(payload.get('event_id'))), None)
        if not ev:
            raise ValueError('that event is no longer in the schedule')
        delta = datetime.timedelta(minutes=int(payload.get('delta_mins') or 0))
        body = {}
        for field, key in (('start', 'dateTime'), ('end', 'dateTime')):
            raw = _dt(ev.get(field))
            if raw:
                body[field] = {key: (raw + delta).isoformat()}
        cal_id = (ev.get('calendar_ids') or [None])[0]
        src = (ev.get('source_event_ids') or [ev.get('id')])[0]
        if not _cal.patch_event(cal_id, src, body):
            raise ValueError('the calendar refused the new time')
    elif lever == 'lift_protected':
        storage.add_protected_exception(payload.get('commitment_id'),
                                        deal.get('date'))
    elif lever == 'swap_drive':
        storage.add_override({'event_id': str(payload.get('event_id')),
                              'driver_id': str(payload.get('driver_id')),
                              'created_at': datetime.datetime.now().timestamp(),
                              'source': 'negotiation'})
    elif lever == 'skip_optional':
        sched = storage.get_cached_schedule() or {}
        ev = next((e for e in (sched.get('events') or [])
                   if str(e.get('id')) == str(payload.get('event_id'))), None)
        if not ev:
            raise ValueError('that event is no longer in the schedule')
        _opt.record_decision(ev, 'skip', decided_by=part.get('member_id'))
    else:
        raise ValueError(f"unknown lever '{lever}'")
```

- [ ] **Step 5: Wire `deal_part` into requests**

In `chauffeur/services/requests.py`, add the kind to `KINDS`:

```python
    'deal_part':    "one part of a deal that makes a day work",
```

And in `_perform` (line 111), before the `if not ref:` guard — a deal part always has a ref, and its acceptance is what performs the change:

```python
    kind, ref = req.get('kind'), req.get('subject_ref')
    if kind == 'deal_part' and ref:
        # A deal applies only when EVERY part is in, so the answer goes to the
        # deal rather than doing anything here. Saying yes to your half of a
        # deal must not move anybody's evening on its own.
        from services import negotiation
        res = negotiation.accept_part(ref, decider['id'])
        return f" {res.get('message', '')}".rstrip()
    if not ref:
        return ''
```

And in `decide`, a declined deal part must reach `decline_part`. After the `suffix = _perform(...)` line:

```python
    suffix = _perform(req, decider) if accept else ''
    if not accept and req.get('kind') == 'deal_part' and req.get('subject_ref'):
        from services import negotiation
        negotiation.decline_part(req['subject_ref'], decider_id, reason)
```

And extend the `schedule_dirty` return so an applied deal triggers a re-solve:

```python
    return {"status": "success", "message": note.split('\n')[0],
            "schedule_dirty": bool(accept and req.get('subject_ref')
                                   and req.get('kind') in ('swap_drive', 'deal_part'))}
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd chauffeur && python tests/test_negotiation_consent.py`
Expected: PASS, printing `test_negotiation_consent OK`

- [ ] **Step 7: Run the full suite, then commit**

Run: `cd chauffeur && python tools/test.py`

Bump `chauffeur/config.yaml` to `2.431.5`, then:

```bash
git add -A && git commit -F - <<'EOF'
Every part is agreed to by the person it costs

A deal fans out to one request per person whose day changes, on the rails
requests.py already has: DM, push, blameless decline with a reason. A partly
agreed deal changes nothing at all -- not the calendar, not the overrides --
because a schedule that works because somebody was volunteered is not a
schedule that works.

A lift gives up ONE evening: it writes a dated exception, never deleting the
commitment. A refused shift teaches the app that the series cannot move, which
is the movable flag earned rather than declared.

If applying fails after everyone agreed, the deal dies loudly rather than
half-applying.

(v2.431.5)
EOF
git push
```

---

### Task 7: The finding carries the deal

**Files:**
- Modify: `chauffeur/services/watchers.py:115-135`, `chauffeur/services/chat_actions.py:74-110` and `:257-294`
- Test: `chauffeur/tests/test_negotiation_watcher.py`

**Interfaces:**
- Consumes: `negotiation.propose`, `negotiation.start_asks`
- Produces: an `unassigned` finding whose line is the deal's line and whose action is `{'label': 'Ask them', 'action_type': 'ask_deal', 'payload': {'deal_id': ...}}`; `chat_actions._execute` handles `ask_deal`.

- [ ] **Step 1: Write the failing test**

Create `chauffeur/tests/test_negotiation_watcher.py`:

```python
"""The Mind brings a deal, and the ladder is still there when it cannot."""
import datetime

from harness import check
from services import chat_actions, negotiation, storage, watchers


def scenario_a_deal_replaces_the_siren():
    """When a deal exists, the finding says what would fix the day."""
    did = storage.add_deal({
        'date': datetime.date.today().isoformat(), 'seed_event_id': 'ev1',
        'seed_title': 'Soccer', 'line': '🤝 Soccer works if the piano moves',
        'parts': [{'id': 'p0', 'member_id': 'm1', 'lever': 'shift_event',
                   'payload': {'event_id': 'e2', 'series_key': 's2'},
                   'ask_text': 'Move it?', 'state': 'open', 'request_id': None}],
        'state': 'draft'})
    line, action = watchers._deal_line('ev1')
    check(line and 'works if' in line, f"the deal speaks, got {line}")
    check(action and action['action_type'] == 'ask_deal',
          f"and offers the ask, got {action}")
    check(action['payload']['deal_id'] == did, "pointing at this deal")


def scenario_no_deal_means_no_line():
    check(watchers._deal_line('nothing-here') == (None, None),
          "no deal, no claim — the coverage ladder answers instead")


def scenario_ask_deal_is_a_proposable_action():
    check('ask_deal' in chat_actions.ADMIN_ACTIONS,
          "the tap has to be able to reach something")
    check(chat_actions.ACTION_LABELS.get('ask_deal'),
          "and it needs a label a person can read")


def scenario_asking_needs_a_real_deal():
    res = chat_actions._execute('ask_deal', {'deal_id': 'nope'})
    check(res.get('status') == 'error', f"a missing deal is an error, got {res}")


if __name__ == '__main__':
    scenario_a_deal_replaces_the_siren()
    scenario_no_deal_means_no_line()
    scenario_ask_deal_is_a_proposable_action()
    scenario_asking_needs_a_real_deal()
    print("test_negotiation_watcher OK")
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd chauffeur && python tests/test_negotiation_watcher.py`
Expected: FAIL — `AttributeError: module 'services.watchers' has no attribute '_deal_line'`

- [ ] **Step 3: Add the deal line to the watcher**

In `chauffeur/services/watchers.py`, above the uncovered-event loop:

```python
# How many seeds one sweep may negotiate. The search costs real solver time,
# and a sweep that negotiated every uncovered event on a bad day would spend
# minutes deciding things nobody has read yet. One seed per sweep, most urgent
# first, and an open deal is reused rather than re-searched.
NEGOTIATE_PER_SWEEP = 1


def _deal_line(event_id: str):
    """(line, action) for an open deal on this event, or (None, None).

    Read-only: it reports a deal that already exists. Finding one is
    `_negotiate_seed`'s job, and it happens at most once per sweep.
    """
    for d in storage.get_deals(seed_event_id=str(event_id)):
        if d.get('state') not in ('draft', 'asking'):
            continue
        if d.get('state') == 'asking':
            waiting = [p for p in d.get('parts') or []
                       if p.get('state') != 'accepted']
            said_yes = len(d.get('parts') or []) - len(waiting)
            return (f"🤝 {d.get('seed_title') or 'That drive'}: "
                    f"{said_yes} of {len(d.get('parts') or [])} said yes, "
                    f"waiting on the rest.", None)
        return (d.get('line'), {'label': 'Ask them', 'action_type': 'ask_deal',
                                'payload': {'deal_id': d['id']}})
    return (None, None)


def _negotiate_seed(event_id: str, date_str: str):
    """Try to find a deal for one uncovered event. Never fatal, never chatty."""
    from services import negotiation
    if not storage.get_settings().get('negotiation_enabled', True):
        return
    try:
        negotiation.propose(date_str, str(event_id),
                            budget=int(storage.get_settings().get(
                                'negotiation_sweep_budget',
                                negotiation.SWEEP_BUDGET)))
    except Exception as e:
        print(f"[watchers] negotiation failed for {event_id}: {e}")
```

Then in the uncovered-event loop, replace the block at lines 115-135 so a deal speaks first. Immediately after `key = f"unassigned:{ev_id}:{start.date().isoformat()}"`:

```python
        key = f"unassigned:{ev_id}:{start.date().isoformat()}"
        # Before the siren: is there a deal? The Mind is supposed to arrive
        # with the answer, not with the problem.
        deal_line, deal_action = _deal_line(ev_id)
        if not deal_line and negotiated < NEGOTIATE_PER_SWEEP:
            negotiated += 1
            _negotiate_seed(ev_id, start.date().isoformat())
            deal_line, deal_action = _deal_line(ev_id)
        if deal_line:
            out.append(Finding(key=key, line=deal_line, kind='unassigned',
                               severity='approve',
                               subject_type='event', subject_id=ev_id,
                               due_at=start.timestamp(), action=deal_action))
            continue
        try:
            rung = _coverage.ladder(ev, cache, now)
        except Exception as e:
```

Initialise `negotiated = 0` beside the loop's other accumulators (next to `out = []` in the same function).

- [ ] **Step 4: Add the `ask_deal` action**

In `chauffeur/services/chat_actions.py`, add to `ADMIN_ACTIONS`:

```python
    # Negotiation: the tap that turns a found deal into real asks. The search
    # is free and automatic; the ASKING is a person's decision, always.
    "ask_deal",
```

To `ACTION_LABELS`:

```python
    "ask_deal": "Ask them",
```

And in `_execute`, beside the other coverage rungs:

```python
    if action_type == "ask_deal":
        from services import negotiation as _neg
        return _neg.start_asks(payload.get('deal_id'), payload.get('member_id'))
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd chauffeur && python tests/test_negotiation_watcher.py`
Expected: PASS, printing `test_negotiation_watcher OK`

- [ ] **Step 6: Run the full suite, then commit**

Run: `cd chauffeur && python tools/test.py`

Bump `chauffeur/config.yaml` to `2.431.6`, then:

```bash
git add -A && git commit -F - <<'EOF'
The finding arrives with the answer, not the problem

An uncovered event whose day has a deal stops saying no driver yet and starts
saying what would fix it, with one action: Ask them. The coverage ladder is
untouched and still answers whenever no deal was found -- negotiation adds a
rung above it, it does not replace it.

One seed per sweep, most urgent first, and an existing open deal is reused
rather than re-searched: a sweep that negotiated every uncovered event on a bad
day would spend minutes re-deciding questions nobody has read yet.

Once the asks are out, the line reports who has answered, because a multi-part
deal has state and no other surface holds it.

(v2.431.6)
EOF
git push
```

---

### Task 8: The hand path — endpoints and the button

**Files:**
- Modify: `chauffeur/main.py` (four endpoints, next to `/api/findings` at line 4754), `chauffeur/templates/dashboard.html:222-234` and its script block
- Test: `chauffeur/tests/test_negotiation_endpoints.py`

**Interfaces:**
- Produces:
  - `POST /api/negotiation/find` `{event_id, date}` → `{status, deal}` — runs the deep search on demand
  - `POST /api/negotiation/{deal_id}/ask` → `{status, message}`
  - `POST /api/negotiation/{deal_id}/kill` `{reason}` → `{status, message}`
  - `GET /api/negotiation/refusals` → `{refusals: [...]}`, `DELETE /api/negotiation/refusals/{series_key}` → `{status}`

- [ ] **Step 1: Write the failing test**

Create `chauffeur/tests/test_negotiation_endpoints.py`:

```python
"""Everything the agent can do, a person can do with a tap."""
import datetime

from harness import check
from fastapi.testclient import TestClient


def _client():
    import main
    return TestClient(main.app)


def scenario_the_endpoints_exist():
    import main
    paths = {r.path for r in main.app.routes}
    for p in ('/api/negotiation/find', '/api/negotiation/{deal_id}/ask',
              '/api/negotiation/{deal_id}/kill', '/api/negotiation/refusals'):
        check(p in paths, f"{p} must be reachable by hand, have {sorted(paths)[:5]}...")


def scenario_find_with_no_pack_is_honest():
    c = _client()
    r = c.post('/api/negotiation/find',
               json={'event_id': 'nope', 'date': '2026-09-07'})
    check(r.status_code == 200, f"it answers, got {r.status_code}")
    body = r.json()
    check(body.get('deal') is None,
          f"and does not invent one when there is no pack, got {body}")


def scenario_killing_a_missing_deal_is_an_error_not_a_crash():
    c = _client()
    r = c.post('/api/negotiation/nope/kill', json={'reason': 'x'})
    check(r.status_code == 200 and r.json().get('status') == 'error',
          f"got {r.status_code} {r.text[:120]}")


def scenario_a_learned_flag_can_be_untaught():
    from services import storage
    storage.add_shift_refusal('series-7', 'Piano')
    c = _client()
    listed = c.get('/api/negotiation/refusals').json()
    check(any(r['series_key'] == 'series-7' for r in listed['refusals']),
          f"a person can see what the app taught itself, got {listed}")
    c.delete('/api/negotiation/refusals/series-7')
    check(not any(r['series_key'] == 'series-7'
                  for r in storage.get_shift_refusals()),
          "and take it back")


if __name__ == '__main__':
    scenario_the_endpoints_exist()
    scenario_find_with_no_pack_is_honest()
    scenario_killing_a_missing_deal_is_an_error_not_a_crash()
    scenario_a_learned_flag_can_be_untaught()
    print("test_negotiation_endpoints OK")
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd chauffeur && python tests/test_negotiation_endpoints.py`
Expected: FAIL on the first scenario — the paths are not in `main.app.routes`.

- [ ] **Step 3: Add the endpoints**

In `chauffeur/main.py`, beside the findings endpoints (after line 4770):

```python
# --- Negotiation ---------------------------------------------------------
# The deep search, by hand. The sweep does a shallow one automatically; this is
# the version a person asks for when they are staring at a broken Tuesday and
# want every lever tried.

@app.post("/api/negotiation/find")
def negotiation_find(payload: dict, request: Request):
    from services import negotiation
    event_id = str(payload.get('event_id') or '')
    date_str = str(payload.get('date') or datetime.date.today().isoformat())
    if not event_id:
        return {"status": "error", "message": "Which event?"}
    budget = int(storage.get_settings().get('negotiation_deep_budget',
                                            negotiation.DEEP_BUDGET))
    deal = negotiation.propose(date_str, event_id, budget=budget)
    if not deal:
        return {"status": "success", "deal": None,
                "message": "Nothing I can change makes that day work."}
    return {"status": "success", "deal": deal}


@app.post("/api/negotiation/{deal_id}/ask")
def negotiation_ask(deal_id: str, request: Request):
    from services import negotiation
    member = _resolve_member_from_request(request)
    return negotiation.start_asks(deal_id, (member or {}).get('id'))


@app.post("/api/negotiation/{deal_id}/kill")
def negotiation_kill(deal_id: str, payload: dict, request: Request):
    from services import negotiation
    member = _resolve_member_from_request(request)
    return negotiation.kill(deal_id, (member or {}).get('id'),
                            reason=str(payload.get('reason') or ''))


@app.get("/api/negotiation/refusals")
def negotiation_refusals():
    """What the app taught itself cannot move."""
    return {"refusals": storage.get_shift_refusals()}


@app.delete("/api/negotiation/refusals/{series_key}")
def negotiation_clear_refusal(series_key: str):
    """A flag the app taught itself must be untaught by hand."""
    ok = storage.clear_shift_refusal(series_key)
    return {"status": "success" if ok else "error",
            "message": "It can move again." if ok else "Nothing to clear."}
```

If `_resolve_member_from_request` does not exist under that name in `main.py`, use whatever helper the neighbouring `/api/findings/{finding_id}/resolve` endpoint uses to identify the caller, and match its auth decorator/dependency exactly — these endpoints are parents-and-adults, kiosk-hidden, like the rest of the deal surface.

- [ ] **Step 4: Add the Find a way button**

In `chauffeur/templates/dashboard.html`, in the override dialog's conflicts section (near line 222-234), after `<div id="conflicts-list" class="space-y-3"></div>`:

```html
                            <button id="find-a-way-btn" type="button"
                                    class="mt-3 w-full rounded-lg bg-indigo-600 px-3 py-2 text-sm font-semibold text-white hover:bg-indigo-500">
                                Find a way
                            </button>
                            <div id="deal-result" class="mt-3 hidden text-sm text-gray-300"></div>
```

And in the script block, beside the other dialog handlers:

```javascript
        document.getElementById('find-a-way-btn')?.addEventListener('click', async () => {
            const btn = document.getElementById('find-a-way-btn');
            const out = document.getElementById('deal-result');
            btn.disabled = true;
            btn.textContent = 'Working on it…';
            try {
                const res = await fetch('/api/negotiation/find', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({event_id: currentOverrideEventId,
                                          date: currentOverrideDate})
                });
                const data = await res.json();
                out.classList.remove('hidden');
                if (!data.deal) {
                    out.textContent = data.message || 'Nothing I can change makes that day work.';
                    return;
                }
                out.innerHTML = `<p class="mb-2">${data.deal.line}</p>`;
                const ask = document.createElement('button');
                ask.type = 'button';
                ask.className = 'rounded-lg bg-emerald-600 px-3 py-2 text-sm font-semibold text-white hover:bg-emerald-500';
                ask.textContent = 'Ask them';
                ask.addEventListener('click', async () => {
                    const r = await fetch(`/api/negotiation/${data.deal.id}/ask`, {method: 'POST'});
                    const body = await r.json();
                    showGlobalAlert(body.message || 'Asked.');
                });
                out.appendChild(ask);
            } catch (e) {
                showGlobalAlert('Could not look for a deal: ' + e.message);
            } finally {
                btn.disabled = false;
                btn.textContent = 'Find a way';
            }
        });
```

Use whatever variables the dialog already holds for the open event's id and date; `currentOverrideEventId` / `currentOverrideDate` are placeholders for those existing names — read the surrounding handler and match them.

- [ ] **Step 5: Rebuild Tailwind and run the tests**

Run: `cd chauffeur && python tools/build_tailwind.py && python tests/test_negotiation_endpoints.py`
Expected: PASS, printing `test_negotiation_endpoints OK`

- [ ] **Step 6: Run the full suite, then commit**

Run: `cd chauffeur && python tools/test.py`

Bump `chauffeur/config.yaml` to `2.431.7`, then:

```bash
git add -A && git commit -F - <<'EOF'
Find a way, by hand

Four endpoints and a button in the override dialog, where the deeper question
about why a driver was refused is already answered. The sweep runs a shallow
search automatically; this is the deep one, for a person staring at a broken
Tuesday who wants every lever tried.

The learned cannot-move flags are listable and clearable: a flag the app taught
itself must be untaught by hand, or it is just a thing that silently stopped
working.

(v2.431.7)
EOF
git push
```

---

### Task 9: Both agent stacks, the settings, and the doc

**Files:**
- Modify: `chauffeur/services/agent_tools_v2.py`, `chauffeur/services/agent_router.py`, `chauffeur/services/agent_tools.py`, `chauffeur/services/settings_registry.py`, `chauffeur/system_capabilities.md`
- Test: `chauffeur/tests/test_negotiation_agent_tools.py`

**Interfaces:**
- Produces:
  - `agent_tools_v2.negotiate_day(day: str = None, event_title: str = None, acting_member: dict = None) -> dict` (read-only)
  - `agent_tools_v2.ask_deal(event_title: str, acting_member: dict = None) -> dict` (write — resolved parent/adult only)

- [ ] **Step 1: Write the failing test**

Create `chauffeur/tests/test_negotiation_agent_tools.py`:

```python
"""Argyle can look for a deal. Argyle cannot send the asks on its own."""
from harness import check
from services import agent_tools, agent_tools_v2, storage


def scenario_both_stacks_can_look():
    names = {t['name'] for t in agent_tools_v2.get_tool_declarations()}
    check('negotiate_day' in names, f"the Gemma stack has it, got {len(names)} tools")
    check('negotiate_day' in agent_tools.TOOL_SCHEMAS,
          "and so does the v1 loop")


def scenario_only_the_new_stack_can_ask():
    names = {t['name'] for t in agent_tools_v2.get_tool_declarations()}
    check('ask_deal' in names, "asking lives where identity is resolved")
    check('ask_deal' not in agent_tools.TOOL_SCHEMAS,
          "and not in the admin loop, which resolves nobody")


def scenario_asking_refuses_an_unresolved_caller():
    res = agent_tools_v2.ask_deal('Soccer', acting_member=None)
    check(res.get('status') == 'error',
          f"an anonymous wall panel may not fan out asks, got {res}")


def scenario_asking_refuses_a_child():
    res = agent_tools_v2.ask_deal('Soccer',
                                  acting_member={'id': 'k1', 'role': 'child'})
    check(res.get('status') == 'error', f"nor may a kid, got {res}")


def scenario_looking_never_asks():
    """negotiate_day must not create a single request, whatever it finds."""
    before = len(storage.get_requests(status='open'))
    agent_tools_v2.negotiate_day(day='2026-09-07',
                                 acting_member={'id': 'p1', 'role': 'parent'})
    after = len(storage.get_requests(status='open'))
    check(before == after,
          f"searching is free and silent, got {before} -> {after}")


if __name__ == '__main__':
    scenario_both_stacks_can_look()
    scenario_only_the_new_stack_can_ask()
    scenario_asking_refuses_an_unresolved_caller()
    scenario_asking_refuses_a_child()
    scenario_looking_never_asks()
    print("test_negotiation_agent_tools OK")
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd chauffeur && python tests/test_negotiation_agent_tools.py`
Expected: FAIL — `negotiate_day` is not in the declarations.

- [ ] **Step 3: Add the tools to `agent_tools_v2.py`**

Beside the thread tools (near line 1365):

```python
def negotiate_day(day: str = None, event_title: str = None,
                  acting_member: dict = None) -> dict:
    """What would make a broken day work. Read-only — it never asks anybody.

    Reads need a resolved member: this names who in the family would have to
    give something up, and that is not a sentence for an anonymous wall panel.
    """
    import datetime as _dt
    from services import negotiation, storage as _st
    if not acting_member:
        return {'status': 'error',
                'message': "I need to know who's asking before I can look at "
                           "who'd have to give something up."}
    date_str = day or _dt.date.today().isoformat()
    cache = _st.get_cached_daily_schedule(date_str) or {}
    sched = cache.get('schedule') or {}
    broken = list(sched.get('true_unassigned') or [])
    if event_title:
        wanted = event_title.strip().lower()
        events = {str(e.get('id')): e for e in (sched.get('events') or [])}
        broken = [b for b in broken
                  if wanted in (events.get(str(b), {}).get('title') or '').lower()]
    if not broken:
        return {'status': 'success',
                'message': f"Nothing on {date_str} needs a deal — it all covers."}
    budget = int(_st.get_settings().get('negotiation_deep_budget',
                                        negotiation.DEEP_BUDGET))
    deals = []
    for ev_id in broken[:3]:
        deal = negotiation.propose(date_str, str(ev_id), budget=budget)
        if deal:
            deals.append({'deal_id': deal['id'], 'line': deal['line'],
                          'people': deal.get('cost', {}).get('people')})
    if not deals:
        return {'status': 'success',
                'message': "I looked, and nothing I can change makes that day "
                           "work. It needs an outside hand or a skip."}
    lines = '\n'.join(f"• {d['line']}" for d in deals)
    return {'status': 'success', 'deals': deals,
            'message': f"Here's what would work:\n{lines}\n\nSay the word and "
                       f"I'll ask them."}


def ask_deal(event_title: str, acting_member: dict = None) -> dict:
    """Send a found deal's asks. A person's decision, never the model's.

    An ALLOWLIST, not a blocklist: /api/chat is WALL_OR_SERVICE, so an
    unresolved caller must be refused rather than walked through a role check
    with role None.
    """
    from services import negotiation, storage as _st
    if not acting_member or acting_member.get('role') not in ('parent', 'adult'):
        return {'status': 'error',
                'message': "Asking the family to rearrange their evening is a "
                           "grown-up's call — it needs a parent or an adult."}
    wanted = (event_title or '').strip().lower()
    if not wanted:
        return {'status': 'error', 'message': "Which day's deal?"}
    for d in _st.get_deals(state='draft'):
        if wanted in (d.get('seed_title') or '').lower():
            return negotiation.start_asks(d['id'], acting_member.get('id'))
    return {'status': 'error',
            'message': f"I don't have a deal waiting for '{event_title}'. "
                       f"Ask me to look for one first."}
```

And the declarations, beside the thread ones (near line 3615):

```python
        {
            "name": "negotiate_day",
            "description": "Works out what would make a broken day cover — whose event could move fifteen minutes, who could take a drive, what could be skipped ('can you make Tuesday work?', 'is there any way to cover Thursday?'). Read-only: it finds the deal, it does not ask anybody.",
            "parameters": {
                "type": "object",
                "properties": {
                    "day": {"type": "string", "description": "The date to work on, as YYYY-MM-DD. Defaults to today."},
                    "event_title": {"type": "string", "description": "Narrow to one uncovered event by title, if they named one."}
                },
                "required": []
            }
        },
        {
            "name": "ask_deal",
            "description": "Sends the asks for a deal that negotiate_day already found ('yes, ask them', 'go ahead and ask Lorena'). Parent/adult only. Nothing changes until every person asked has said yes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_title": {"type": "string", "description": "The uncovered event the deal is about, e.g. 'Soccer'."}
                },
                "required": ["event_title"]
            }
        },
```

- [ ] **Step 4: Dispatch in the router, and register the read in the v1 loop**

In `chauffeur/services/agent_router.py`, extend the threads dispatch branch's tuple and add the two handlers (the actor resolution above it is already correct and must be reused):

```python
                elif func_name in ("list_threads", "create_thread",
                                   "update_thread_action", "add_thread_note",
                                   "draft_thread_message", "close_thread",
                                   "negotiate_day", "ask_deal"):
```

and inside that branch, beside the other `elif func_name ==` arms:

```python
                    elif func_name == "negotiate_day":
                        res = _atv2.negotiate_day(day=args.get("day"),
                                                  event_title=args.get("event_title"),
                                                  acting_member=actor)
                    elif func_name == "ask_deal":
                        res = _atv2.ask_deal(args.get("event_title", "") or "",
                                             acting_member=actor)
```

In `chauffeur/services/agent_tools.py`, add the read-only tool only — the v1 loop runs in admin contexts and resolves no member, so it must not be able to fan out asks:

```python
class NegotiateDayTool(BaseModel):
    """
    Works out what would make a broken day cover — whose event could move fifteen minutes, who could take a drive, what could be skipped. Read-only: it finds the deal, it does not ask anybody.
    """
    day: Optional[str] = Field(None, description="The date to work on, as YYYY-MM-DD. Defaults to today.")
    event_title: Optional[str] = Field(None, description="Narrow to one uncovered event by title.")
```

To `TOOL_SCHEMAS`:

```python
    "negotiate_day": NegotiateDayTool.model_json_schema(),
```

And the handler:

```python
def handle_negotiate_day(args: dict) -> dict:
    # The v1 loop is admin-only, so the caller is a grown-up by construction —
    # but negotiate_day gates on a resolved member, so give it the first parent
    # rather than None. `ask_deal` is deliberately absent from this registry:
    # fanning out asks needs an identity this loop cannot produce.
    from services.agent_tools_v2 import negotiate_day
    from services import storage
    parents = [m for m in storage.get_all_members()
               if m.get('role') == 'parent' and not m.get('system')]
    return negotiate_day(day=args.get("day"),
                         event_title=args.get("event_title"),
                         acting_member=parents[0] if parents else None)
```

- [ ] **Step 5: Add the settings**

In `chauffeur/services/settings_registry.py`, after the threads block:

```python
    # --- Negotiation (the smallest change that makes a day work) ---
    _e('negotiation_enabled', 'negotiation', 'Look for deals',
       'When a day cannot be covered, work out what would fix it before saying '
       'so. Off means findings go back to reporting the conflict.', page='mind'),
    _e('negotiation_sweep_budget', 'negotiation', 'Background tries',
       'How many re-solves one background sweep may spend looking for a deal '
       '(default 8). The sweep runs unattended, so this is kept small.',
       page='mind'),
    _e('negotiation_deep_budget', 'negotiation', 'On-demand tries',
       'How many re-solves a Find a way tap may spend (default 40). Somebody '
       'is waiting on purpose, so it goes further down the same queue.',
       page='mind'),
    _e('negotiation_shift_mins', 'negotiation', 'How far a thing may move',
       'The minute steps a deal may ask an event to move, smallest first '
       '(default 15 then 30).', page='mind'),
    _e('negotiation_solve_seconds', 'negotiation', 'Seconds per try',
       'Time limit on each re-solve (default 2). The daily solve gets five; a '
       'negotiation runs many in one question.', page='mind'),
]
```

- [ ] **Step 6: Update `system_capabilities.md`**

Add a section documenting: the four levers and their friction prices, the two-tier cost, the solve pack and its fidelity property, the consent rule (partial acceptance applies nothing), the learned cannot-move flag, and the five settings. Place it after the Threads section and match the surrounding voice.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd chauffeur && python tests/test_negotiation_agent_tools.py`
Expected: PASS, printing `test_negotiation_agent_tools OK`

- [ ] **Step 8: Run the full suite, then commit**

Run: `cd chauffeur && python tools/test.py`

Bump `chauffeur/config.yaml` to `2.431.8`, then:

```bash
git add -A && git commit -F - <<'EOF'
Argyle can look for a deal, and only a person can send it

negotiate_day lands in both stacks; ask_deal lands only where identity is
resolved. The v1 admin loop gets the read and not the write, because fanning
out asks needs an actor it cannot produce.

Both gate on an allowlist rather than a blocklist: /api/chat is
WALL_OR_SERVICE, so an unresolved caller is refused instead of walking through
a role check with role None. Reads need a resolved member because a deal names
who in the family would have to give something up, and that is not a sentence
for an anonymous wall panel.

Five settings on the Mind page, and the capabilities doc says what the levers
cost and why lifting protected time is the most expensive thing it can ask for.

(v2.431.8)
EOF
git push
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| Solve pack, fidelity test | 2, 3 |
| Read-only, budget, cache-only travel | 2 (replay), 5 (budget), 4 (no maps calls made) |
| Four levers | 4 |
| Movability learned, not declared | 4 (generation skips refusals), 6 (decline records one) |
| Seeded generation, ordered queue | 4 |
| Hard filter (seed covered, nothing new broken) | 5 |
| Tier 1 people, tier 2 blend, protected priced highest | 5 |
| Deal/part object | 5 (schema), 6 (lifecycle) |
| Consent: nothing applies early, one decline kills | 6 |
| Application per lever | 6 |
| Finding is the deal's face | 7 |
| Requests carries each part | 6 |
| Chat, both stacks | 9 |
| Hand path: Find a way, kill, clear a flag | 8 |
| Settings on their own page | 9 |
| Testing list | every task; runtime test in 3, reachability in 8 |

**Note on the travel cache-only guard:** no task adds a maps interceptor, because `solve_pack.replay` calls `matcher.solve_schedule`, which reads travel times through `maps.get_travel_time_minutes` — the same cache the daily solve primed. **Task 5 must verify this by inspection during implementation:** if a shifted departure time can reach a live Matrix call, add a cache-only guard around the replay and a test that a candidate needing an uncached pair is dropped. This is the one spec requirement whose implementation is contingent on what the code does, so it is called out rather than assumed.

**Type consistency check:** `solve_pack.build/apply/replay`, `negotiation.candidates/search/part_key/propose/start_asks/accept_part/decline_part/kill/_apply_part/_rank/_cost/_fairness`, `storage.save_solve_pack/get_solve_pack/prune_solve_packs/add_deal/get_deal/get_deals/update_deal/get_deal_by_part/update_deal_part/add_shift_refusal/get_shift_refusals/clear_shift_refusal/add_protected_exception/get_protected_exceptions`, `watchers._deal_line/_negotiate_seed` — each is defined in exactly one task and used with the same name and signature everywhere after.

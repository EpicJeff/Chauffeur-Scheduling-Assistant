# Outings & the family packing tile — implementation plan (P1 + P2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The household can see, on the wall panel, every trip out of the house today with everything that has to be packed for it — grouped so two events on one trip are one packing job — and can tick items off as they pack, from any surface, with everyone seeing what is left.

**Architecture:** A new pure-computation service (`services/outings.py`) turns the solver's existing chained route edges into *outings* — one trip from home and back — and unions each outing's prep-kit items into per-kit lists with a **needed count** derived from how many people the kit applies to. A new interactive board card self-fetches that from `/api/packing/day` and writes ticks (*claims*) to a new table. The card follows the existing `chores_lanes` pattern exactly: builder returns mount config only, the card fetches its own data on the kiosk cadence.

**Tech Stack:** Python 3 + FastAPI + TinyDB/SQLite dual storage, Jinja components with vanilla Alpine on the wall, a precompiled Tailwind sheet, and the repo's own test harnesses (python scenarios, node for browser-free JS, playwright/chromium for anything geometric).

**Spec:** `docs/packing_design.md` — read it first. It carries the reasoning, the household's own decisions, and the non-goals. Where this plan and the design disagree, the design wins.

## Global Constraints

- **Run tests with `python tools/test.py`** (parallel) from `chauffeur/`. `--focus <file>` for the inner loop. Never a serial loop, never piped (piping masks the exit code). Run the full sweep before every commit.
- **Bump `config.yaml`'s `version:` on every commit**, and end the commit subject with `(vX.Y.Z)`.
- **No double quotes in commit messages** (PowerShell splits the args) — write the message to a file and `git commit -F <file>`.
- **`python tools/build_tailwind.py` after touching any template**, or `test_tailwind_build.py` fails on a stale sheet.
- **Never round-trip source through PowerShell `Get-Content`/`Set-Content`** — it mojibakes UTF-8. Use the Edit tool or Bash.
- **Never `alert()`/`confirm()`/`prompt()`** — use `showGlobalAlert` / `promptConfirm` / `promptInput`.
- **Rule 1 — hide what is not SET UP; never hide what is merely quiet.** A builder returns `None` ONLY when the feature is unconfigured; a configured-but-quiet card returns `{'empty': "an honest sentence"}`. The first version of this rule was "nothing to say, nothing drawn" and it was wrong in practice: the panel dropped to four tiles and the family could not tell empty from broken (`home_board.py:13-29`).
- **Rule 2, one data rule per card:** a card either self-fetches or rides the board payload, never both. This card **self-fetches**.
- **A tick mints critter XP and nothing else** — never points, never routine completion, never a streak.
- **Both storage backends:** every storage function must work under TinyDB and SQLite; new tables need an index entry in `services/storage_sqlite.py`.
- **Existing vocabulary is load-bearing:** `run` means a scheduled ride (`home_board.todays_runs`) and `runway` means a child's morning (`services/runway.py`). This work uses **outing** and must not overload either.

---

### Task 1: The outing — one trip out of the house

**Files:**
- Create: `chauffeur/services/outings.py`
- Test: `chauffeur/tests/test_outings.py` (create)

**Interfaces:**
- Consumes: `storage.get_cached_schedule()` → a dict carrying `events`, `assignments`, `route_edges`, `initial_edges`, `final_edges`, `car_assignments`, `cars`. Route edges are keyed `[driver_id][from_event_id]` and carry `to_event`, `travel_mins`, and — **only when the driver passes through home** — `home_waypoint`.
- Produces: `outings.outings_for(target_date, sched=None, now=None) -> list[dict]`, each
  `{'key', 'driver_id', 'event_ids': [...], 'start': iso, 'end': iso}`, sorted by `start`.
  `key` is `f"{driver_id}:{event_ids[0]}"` — stable across polls and per-day for free, because every calendar occurrence already has its own id.

- [ ] **Step 1: Write the failing test**

Create `chauffeur/tests/test_outings.py`:

```python
"""An outing: one trip out of the house, leaving home to coming back.

The app had legs and it had events and no word for the thing that spans them —
which is the unit that decides what has to be in the car. A driver took a
passenger to one event, went straight on to a second, and arrived without the
second event's gear; the solver already knew they were not stopping home, and
nothing ever said so.

The solver encodes that knowledge as an ABSENCE: a route edge carries a
`home_waypoint` when there was room to detour home, and simply omits it when
there was not. So an outing is a driver's chained events for a date, cut
wherever a home waypoint appears.

Run from chauffeur/:  python tests/test_outings.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_outings_'))

import datetime  # noqa: E402

from services import outings  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


DAY = '2026-09-08'


def _ev(eid, hh, mm=0, dur=60, title=None):
    start = datetime.datetime(2026, 9, 8, hh, mm)
    return {'id': eid, 'title': title or eid,
            'start': start.isoformat(),
            'end': (start + datetime.timedelta(minutes=dur)).isoformat()}


def _sched(events, assignments, route_edges=None):
    return {'events': events, 'assignments': assignments,
            'route_edges': route_edges or {}, 'initial_edges': {}, 'final_edges': {}}


def scenario_two_events_with_no_way_home_are_one_outing():
    """The incident, in fixture form. Soccer at 16:00, band at 17:30, and no
    room to get home in between — so it is one trip, and one packing job."""
    sched = _sched([_ev('soccer', 16), _ev('band', 17, 30)],
                   {'soccer': 'd1', 'band': 'd1'},
                   {'d1': {'soccer': {'to_event': 'band', 'travel_mins': 20}}})
    got = outings.outings_for(DAY, sched)
    check(len(got) == 1, f"two events with no way home are one outing, got {len(got)}")
    check(got[0]['event_ids'] == ['soccer', 'band'],
          f"the outing does not hold both events in order: {got[0]}")


def scenario_a_home_layover_ends_the_outing():
    """The same two events with room to go home in between are two trips —
    and two packing jobs, because making a family carry the whole day's gear
    on every trip is its own kind of wrong."""
    sched = _sched([_ev('soccer', 9), _ev('band', 17, 30)],
                   {'soccer': 'd1', 'band': 'd1'},
                   {'d1': {'soccer': {'to_event': 'band', 'travel_mins': 20,
                                      'home_waypoint': {'layover_mins': 240}}}})
    got = outings.outings_for(DAY, sched)
    check([o['event_ids'] for o in got] == [['soccer'], ['band']],
          f"a home layover did not split the day: {[o['event_ids'] for o in got]}")


def scenario_each_driver_gets_their_own_outings():
    """Two cars out at once is two outings — and at four activities a day it
    is most days. Whose car a bag belongs in is the whole question."""
    sched = _sched([_ev('soccer', 16), _ev('swim', 16, 15)],
                   {'soccer': 'd1', 'swim': 'd2'})
    got = outings.outings_for(DAY, sched)
    check(sorted(o['driver_id'] for o in got) == ['d1', 'd2'],
          f"two drivers did not produce two outings: {got}")


def scenario_outings_are_sorted_by_departure():
    got = outings.outings_for(DAY, _sched(
        [_ev('late', 18), _ev('early', 8)],
        {'late': 'd1', 'early': 'd2'}))
    check([o['event_ids'][0] for o in got] == ['early', 'late'],
          f"outings are not in departure order: {got}")


def scenario_a_day_with_nothing_has_no_outings():
    """Rule 1: nothing to say, nothing drawn."""
    check(outings.outings_for(DAY, _sched([], {})) == [], "an empty day invented an outing")


def scenario_a_ghost_driver_is_not_an_outing():
    """`ghost_` is the solver's placeholder for nobody real. Naming one on the
    wall would be inventing a person."""
    got = outings.outings_for(DAY, _sched([_ev('soccer', 16)], {'soccer': 'ghost_1'}))
    check(got == [], f"a ghost assignment became an outing: {got}")


def scenario_another_day_is_not_this_day():
    sched = _sched([_ev('soccer', 16)], {'soccer': 'd1'})
    check(outings.outings_for('2026-09-09', sched) == [],
          "an outing leaked across days")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} outing scenarios passed")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python tests/test_outings.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.outings'`.

- [ ] **Step 3: Write the service**

Create `chauffeur/services/outings.py`:

```python
"""An OUTING: one trip out of the house — leaving home, however many stops,
back home.

The app has legs and it has events. It had no word for the thing that spans
them, which is exactly the unit that decides what has to be in the car: a
driver took a passenger to one event, drove straight on to a second, and
arrived without the second event's gear.

The knowledge was already here. `solver/matcher.py` chains each driver's day
and, for every gap, works out whether there is room to detour home — a gap over
45 minutes or a wait over 15, needing a 20-minute layover to be worth taking.
When there is room it hangs a `home_waypoint` on the route edge. When there is
not, it simply omits one. **The absence is the answer**, and this module is the
first thing to read it as a statement rather than as routing arithmetic.

Pure computation over the schedule cache: no storage of its own, nothing
written, safe to call on every poll.

Vocabulary: `run` already means a scheduled ride (`home_board.todays_runs`) and
`runway` already means a child's morning (`services/runway.py`). Neither is
this. An outing is an outing.
"""
import datetime
from typing import List, Optional

from services import storage


def _parse(raw) -> Optional[datetime.datetime]:
    if not raw:
        return None
    try:
        return datetime.datetime.fromisoformat(str(raw).replace('Z', '+00:00')).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def _as_date(raw) -> Optional[datetime.date]:
    if isinstance(raw, datetime.date) and not isinstance(raw, datetime.datetime):
        return raw
    if isinstance(raw, datetime.datetime):
        return raw.date()
    dt = _parse(raw)
    return dt.date() if dt else None


def outings_for(target_date=None, sched: dict = None,
                now: datetime.datetime = None) -> List[dict]:
    """Every trip out of the house on one day, one entry per driver per trip.

    Sorted by departure, which is the order a household acts in — the same
    rule `todays_runs` states for the wall.
    """
    now = now or datetime.datetime.now()
    target = _as_date(target_date) or now.date()
    sched = sched if sched is not None else (storage.get_cached_schedule() or {})
    events = {e.get('id'): e for e in (sched.get('events') or [])}
    route_edges = sched.get('route_edges') or {}

    # A driver's events for the day, in time order. Ghost drivers are the
    # solver's "nobody real can do this" placeholder and are not people.
    by_driver = {}
    for ev_id, d_id in (sched.get('assignments') or {}).items():
        if not d_id or str(d_id).startswith('ghost_'):
            continue
        ev = events.get(ev_id)
        start = _parse((ev or {}).get('start'))
        if not ev or not start or start.date() != target:
            continue
        by_driver.setdefault(str(d_id), []).append((start, ev_id, ev))

    out = []
    for d_id, rows in by_driver.items():
        rows.sort(key=lambda r: (r[0], str(r[1])))
        edges = route_edges.get(d_id) or {}
        chain = []
        for i, (start, ev_id, ev) in enumerate(rows):
            chain.append((start, ev_id, ev))
            # Does the driver pass through home before the next one? The
            # solver says so by hanging a home_waypoint on the edge leaving
            # THIS event; an edge with none means they carried straight on.
            last = i == len(rows) - 1
            went_home = bool((edges.get(ev_id) or {}).get('home_waypoint'))
            if last or went_home:
                out.append(_outing(d_id, chain))
                chain = []
    out.sort(key=lambda o: (o['start'], o['key']))
    return out


def _outing(d_id: str, chain: list) -> dict:
    ends = [_parse(ev.get('end')) or start for start, _eid, ev in chain]
    return {
        'key': f"{d_id}:{chain[0][1]}",
        'driver_id': d_id,
        'event_ids': [eid for _s, eid, _e in chain],
        'start': chain[0][0].isoformat(),
        'end': max(ends).isoformat(),
    }
```

- [ ] **Step 4: Run it and watch it pass**

Run: `python tests/test_outings.py`
Expected: PASS, 7/7.

- [ ] **Step 5: Full sweep, bump, commit**

```bash
python tools/test.py
```
Bump `config.yaml`, commit subject: `An outing is one trip out of the house (vX.Y.Z)`.

---

### Task 2: What an outing needs packed

**Files:**
- Modify: `chauffeur/services/outings.py`
- Modify: `chauffeur/models/schemas.py` (the `PrepKit` model — add `per_person`)
- Modify: `chauffeur/templates/routines.html` (the kit editor gets the toggle)
- Test: `chauffeur/tests/test_outings.py`

**Interfaces:**
- Consumes: `prep_kits.match_kits_for_event(ev, kits, passengers)` → the enabled kits whose rule-filters match an event (each kit dict carries `name`, `items: [str]`, `passenger_ids`); `prep_kits.passenger_objs()`; `storage.get_prep_kits()`.
- Produces: `outings.packing_for(outing, sched, kits=None, passengers=None) -> list[dict]` — one entry per kit:
  `{'kit_id', 'kit': name, 'people': [member ids], 'items': [{'key', 'label', 'needed'}]}`.
  `key` is `f"{kit_id}:{item.lower()}"` — the identity a claim is filed against.

**Decision made while planning (not in the design doc):** the design requires a "one for the group" exception — the team snack does not scale with children. Items are bare strings today, so the flag lands on the **kit**: `PrepKit.per_person: bool = True`. A per-item override waits until P4 turns items into objects. A kit mixing personal and group items is split into two kits, which is what the editor is for.

- [ ] **Step 1: Write the failing test**

Append to `chauffeur/tests/test_outings.py` (before `SCENARIOS = ...`):

```python
def _kit(kid, name, items, passengers=None, per_person=True):
    return {'id': kid, 'name': name, 'items': items, 'enabled': True,
            'passenger_ids': passengers or [], 'per_person': per_person,
            'keywords': [name.split()[0].lower()]}


class _Pax:
    def __init__(self, pid, name, cal_ids=None):
        self.id, self.name = pid, name
        self.calendar_ids = cal_ids or []


def scenario_two_children_at_one_event_need_two_of_everything():
    """The silent failure this exists to stop: prep items are deduped
    case-insensitively today, so two kids at one practice get ONE water bottle
    ticked and one child goes thirsty."""
    ev = _ev('soccer', 16, title='Soccer practice')
    ev['calendar_ids'] = ['ellie', 'sam']
    sched = _sched([ev], {'soccer': 'd1'})
    out = outings.outings_for(DAY, sched)[0]
    got = outings.packing_for(out, sched,
                              kits=[_kit('k1', 'Soccer bag', ['Water bottle', 'Cleats'],
                                         passengers=['ellie', 'sam'])],
                              passengers=[_Pax('ellie', 'Ellie'), _Pax('sam', 'Sam')])
    check(len(got) == 1, f"one kit should produce one group: {got}")
    check([i['needed'] for i in got[0]['items']] == [2, 2],
          f"two children need two of each item: {got[0]['items']}")


def scenario_one_child_at_two_events_still_needs_one_bottle():
    """The kid carries it all afternoon. Needed is DISTINCT PEOPLE across the
    outing, never the sum of the events."""
    a, b = _ev('soccer', 16, title='Soccer practice'), _ev('band', 17, 30, title='Soccer social')
    a['calendar_ids'] = b['calendar_ids'] = ['ellie']
    sched = _sched([a, b], {'soccer': 'd1', 'band': 'd1'},
                   {'d1': {'soccer': {'to_event': 'band', 'travel_mins': 15}}})
    out = outings.outings_for(DAY, sched)[0]
    got = outings.packing_for(out, sched,
                              kits=[_kit('k1', 'Soccer bag', ['Water bottle'],
                                         passengers=['ellie'])],
                              passengers=[_Pax('ellie', 'Ellie')])
    check([i['needed'] for i in got[0]['items']] == [1],
          f"one child on two events still needs one bottle: {got}")


def scenario_a_group_kit_is_one_however_many_are_going():
    """The team snack, the folding chair, the cash for the fundraiser. A
    counter that is wrong about these teaches the household to ignore counters."""
    ev = _ev('soccer', 16, title='Soccer practice')
    ev['calendar_ids'] = ['ellie', 'sam']
    sched = _sched([ev], {'soccer': 'd1'})
    out = outings.outings_for(DAY, sched)[0]
    got = outings.packing_for(out, sched,
                              kits=[_kit('k2', 'Team snack', ['Orange slices'],
                                         passengers=['ellie', 'sam'], per_person=False)],
                              passengers=[_Pax('ellie', 'Ellie'), _Pax('sam', 'Sam')])
    check([i['needed'] for i in got[0]['items']] == [1],
          f"a group item is one however many are going: {got}")


def scenario_a_kit_naming_nobody_needs_one():
    ev = _ev('soccer', 16, title='Soccer practice')
    ev['calendar_ids'] = ['ellie']
    sched = _sched([ev], {'soccer': 'd1'})
    out = outings.outings_for(DAY, sched)[0]
    got = outings.packing_for(out, sched,
                              kits=[_kit('k3', 'Soccer bag', ['Ball'])],
                              passengers=[_Pax('ellie', 'Ellie')])
    check([i['needed'] for i in got[0]['items']] == [1],
          f"an unfiltered kit needs one: {got}")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python tests/test_outings.py`
Expected: FAIL — `module 'services.outings' has no attribute 'packing_for'`.

- [ ] **Step 3: Add `per_person` to the kit model**

In `chauffeur/models/schemas.py`, on `class PrepKit` (around line 481), beside `items`:

```python
    # Does each item scale with the number of people the kit covers? A soccer
    # bag does: two children need two water bottles, and a single tick against
    # "water bottle" is how one of them goes thirsty. The team snack does not.
    # Kit-level rather than per-item because an item is a bare string today; a
    # kit that mixes the two is two kits, which is what the editor is for.
    per_person: bool = True
```

- [ ] **Step 4: Write `packing_for`**

Append to `chauffeur/services/outings.py`:

```python
def packing_for(outing: dict, sched: dict = None, kits: list = None,
                passengers: list = None) -> List[dict]:
    """What one outing needs packed, grouped by kit, with a NEEDED count.

    The count is the point. Prep items are deduped case-insensitively today,
    so two children at one practice see one water bottle — which is a silent
    way to leave one child's bottle at home. Needed is the number of DISTINCT
    PEOPLE the kit covers across the whole outing: the child who needs a
    bottle at soccer and again at band is carrying it between the two and
    needs one, not two.
    """
    from services import prep_kits as _prep
    sched = sched if sched is not None else (storage.get_cached_schedule() or {})
    events = {e.get('id'): e for e in (sched.get('events') or [])}
    if kits is None:
        kits = storage.get_prep_kits()
    if passengers is None:
        passengers = _prep.passenger_objs()

    groups = {}                      # kit_id -> {'kit', 'people': set, 'items': [...]}
    for ev_id in outing.get('event_ids') or []:
        ev = events.get(ev_id)
        if not ev or ev.get('event_type') in ('errand', 'background_trip'):
            continue
        cal_ids = {str(c) for c in (ev.get('calendar_ids') or [])}
        for kit in _prep.match_kits_for_event(ev, kits, passengers):
            kid = str(kit.get('id') or kit.get('name') or '')
            g = groups.setdefault(kid, {
                'kit_id': kid, 'kit': kit.get('name') or 'Bring',
                'per_person': kit.get('per_person') is not False,
                'people': set(),
                'items': [i.strip() for i in (kit.get('items') or []) if i.strip()],
            })
            g['people'].update(_people_on(kit, cal_ids, passengers))

    out = []
    for g in groups.values():
        n = max(1, len(g['people'])) if g['per_person'] else 1
        out.append({
            'kit_id': g['kit_id'], 'kit': g['kit'],
            'people': sorted(g['people']),
            'items': [{'key': f"{g['kit_id']}:{i.lower()}", 'label': i, 'needed': n}
                      for i in g['items']],
        })
    out.sort(key=lambda g: g['kit'].lower())
    return out


def _people_on(kit: dict, cal_ids: set, passengers: list) -> set:
    """The members this kit covers who are actually on this event.

    Resolution mirrors the solver's own rule (`does_event_match_rule`): a
    passenger is named by id, by any of their calendar ids, or by name.
    """
    named = [str(p) for p in (kit.get('passenger_ids') or [])]
    if not named:
        return set()
    found = set()
    for p in passengers or []:
        pid, pname = str(getattr(p, 'id', '')), str(getattr(p, 'name', '') or '')
        p_cals = {str(c) for c in (getattr(p, 'calendar_ids', None) or [])}
        if not any(n == pid or n in p_cals or n.lower() == pname.lower() for n in named):
            continue
        if pid in cal_ids or (p_cals & cal_ids):
            found.add(pid)
    return found
```

- [ ] **Step 5: Run it and watch it pass**

Run: `python tests/test_outings.py`
Expected: PASS, 11/11.

- [ ] **Step 6: Put the toggle in the kit editor**

`chauffeur/templates/routines.html` renders the prep-kit editor (the kit rows and their filter panel start around line 376). Add a checkbox bound to the kit's `per_person`, defaulting checked, labelled **"One per person"** with the help text *"Two children at one activity need two of these. Turn off for a team snack or anything the family brings one of."* Follow the markup of the existing toggles in that panel; it posts through the same `PUT /api/prep-kits/{id}` the other fields use.

- [ ] **Step 7: Sweep, tailwind, bump, commit**

```bash
python tools/build_tailwind.py
python tools/test.py
```
Commit subject: `An outing knows how many of each thing it needs (vX.Y.Z)`.

---

### Task 3: Claims — who packed what, and the XP it pays

**Files:**
- Modify: `chauffeur/services/storage.py`
- Modify: `chauffeur/services/storage_sqlite.py` (index registration)
- Test: `chauffeur/tests/test_packing_claims.py` (create)

**Interfaces:**
- Consumes: `grant_pet_xp(member_id, delta, reason, ref_id, date_str, once)` — the existing XP ledger.
- Produces:
  - `storage.add_packing_claim(outing_key, item_key, date_str, member_id=None) -> int` (returns XP minted)
  - `storage.remove_packing_claim(outing_key, item_key, date_str, member_id=None) -> bool`
  - `storage.get_packing_claims(date_str) -> list[dict]` rows `{outing_key, item_key, member_id, date_str, ts}`

- [ ] **Step 1: Write the failing test**

Create `chauffeur/tests/test_packing_claims.py`:

```python
"""Ticking a packing item: a CLAIM, not a checkbox.

An item needs as many as there are people it covers, so the state is a count
of claims rather than a boolean. A child ticking their own kit in their own day
claims a slot with their name on it; a tap on the wall claims an anonymous one,
because the wall has no identity and inventing one to pay somebody would be a
lie with a currency attached.

What a claim pays is critter XP, and nothing else. It is not a chore (no
points), and it is not a habit (no routine, no streak) — the household's own
rule: an unpacked bag is a real problem and it is not a broken routine.

Run from chauffeur/:  python tests/test_packing_claims.py
"""
from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage

DAY = '2026-09-08'
OUT, ITEM = 'd1:soccer', 'k1:water bottle'


def _reset():
    storage.packing_claims_table.truncate()
    storage.pet_xp_ledger_table.truncate()


def test_claims_count_up_and_down():
    _reset()
    storage.add_packing_claim(OUT, ITEM, DAY)
    storage.add_packing_claim(OUT, ITEM, DAY)
    rows = [r for r in storage.get_packing_claims(DAY) if r['item_key'] == ITEM]
    check(len(rows) == 2, f"two anonymous claims are two: {rows}")
    storage.remove_packing_claim(OUT, ITEM, DAY)
    rows = [r for r in storage.get_packing_claims(DAY) if r['item_key'] == ITEM]
    check(len(rows) == 1, f"unticking removes one claim, not the lot: {rows}")


def test_a_members_claim_is_theirs_and_pays_xp_once():
    """`once=True` per (member, item, day) is the whole anti-farm story — a
    child can tick and untick a box all afternoon."""
    _reset()
    first = storage.add_packing_claim(OUT, ITEM, DAY, member_id='ellie')
    check(first > 0, f"a member's claim mints xp: {first}")
    storage.remove_packing_claim(OUT, ITEM, DAY, member_id='ellie')
    again = storage.add_packing_claim(OUT, ITEM, DAY, member_id='ellie')
    check(again == 0, f"re-ticking the same item the same day mints nothing more: {again}")
    ledger = [r for r in storage.pet_xp_ledger_table.all() if r['reason'] == 'prep']
    check(len(ledger) == 1 and ledger[0]['member_id'] == 'ellie',
          f"one prep row, paid to the packer: {ledger}")


def test_unticking_never_claws_xp_back():
    """A thing earned is never taken away — the rule the routine ledger already
    states, and a box tapped by accident must not cost a child anything."""
    _reset()
    storage.add_packing_claim(OUT, ITEM, DAY, member_id='sam')
    storage.remove_packing_claim(OUT, ITEM, DAY, member_id='sam')
    total = sum(r['delta'] for r in storage.pet_xp_ledger_table.all() if r['reason'] == 'prep')
    check(total > 0, f"unticking clawed the xp back: {total}")


def test_an_anonymous_wall_tap_pays_nobody():
    _reset()
    check(storage.add_packing_claim(OUT, ITEM, DAY) == 0,
          "an anonymous claim minted xp with nobody to pay")
    check(not storage.pet_xp_ledger_table.all(), "the wall wrote a ledger row")


def test_claims_are_per_day():
    _reset()
    storage.add_packing_claim(OUT, ITEM, DAY)
    check(storage.get_packing_claims('2026-09-09') == [],
          "yesterday's packing leaked into today")


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    for fn in TESTS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(TESTS)}/{len(TESTS)} packing-claim tests passed")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python tests/test_packing_claims.py`
Expected: FAIL — `module 'services.storage' has no attribute 'packing_claims_table'`.

- [ ] **Step 3: Add the table and its functions**

In `chauffeur/services/storage.py`, beside the other table handles (the prep ones are around line 447):

```python
packing_claims_table = db.table('packing_claims')
```

and, beside `set_prep_confirmed` (around line 6427):

```python
# A packing CLAIM: one person (or one anonymous pair of hands at the wall)
# has packed one of something for one outing on one day.
#
# A count, not a checkbox, because an item needs as many as there are people
# it covers — two children at one practice need two water bottles, and a
# single tick is how one of them goes thirsty.
#
# `member_id` is None for a tap on the wall. The wall has no identity and
# guessing one would be a lie with a currency attached: `prep_status` already
# writes a `confirmed_by` nobody ever reads, and this does not repeat it.
def add_packing_claim(outing_key: str, item_key: str, date_str: str,
                      member_id: str = None) -> int:
    """Record one claim. Returns the xp minted (0 for an anonymous tap)."""
    import time
    import uuid as _uuid
    with db_lock:
        packing_claims_table.insert({
            'id': _uuid.uuid4().hex, 'outing_key': str(outing_key),
            'item_key': str(item_key), 'date_str': str(date_str),
            'member_id': member_id, 'ts': time.time()})
    if not member_id:
        return 0
    # Packing your own bag is real work and the household wanted it to feel
    # that way — but it is not a chore somebody assigned (no points) and not a
    # habit (no routine, no streak). `once` per (member, item, day) is the
    # same anti-faucet guard routines pass, because a child can tick and untick
    # a box all afternoon.
    return grant_pet_xp(member_id, PACKING_XP, 'prep',
                        ref_id=str(item_key), date_str=str(date_str), once=True)


def remove_packing_claim(outing_key: str, item_key: str, date_str: str,
                         member_id: str = None) -> bool:
    """Drop ONE claim — the member's own if named, else any anonymous one.

    The xp is never clawed back: a thing earned is never taken away, and a box
    tapped by accident must not cost a child anything.
    """
    with db_lock:
        rows = packing_claims_table.search(
            (Query().outing_key == str(outing_key))
            & (Query().item_key == str(item_key))
            & (Query().date_str == str(date_str)))
        if member_id:
            mine = [r for r in rows if r.get('member_id') == member_id]
            rows = mine or [r for r in rows if not r.get('member_id')]
        else:
            anon = [r for r in rows if not r.get('member_id')]
            rows = anon or rows
        if not rows:
            return False
        packing_claims_table.remove(Query().id == rows[0]['id'])
        return True


def get_packing_claims(date_str: str) -> List[dict]:
    with db_lock:
        return packing_claims_table.search(Query().date_str == str(date_str))
```

Add the rate beside the other XP rates (around line 3925), so it is settable the way the others are:

```python
PACKING_XP = 2                       # one item packed; a routine item is 3
```

- [ ] **Step 4: Register the sqlite index**

In `chauffeur/services/storage_sqlite.py`, in the index map (around line 50, where `prep_status` sits):

```python
    'packing_claims': [["date_str"], ["outing_key"]],
```

- [ ] **Step 5: Run it and watch it pass**

Run: `python tests/test_packing_claims.py`
Expected: PASS, 5/5.

- [ ] **Step 6: Sweep, bump, commit**

Commit subject: `Packing a thing is a claim, and it pays a critter (vX.Y.Z)`.

---

### Task 4: The day in focus, and the endpoint behind the tile

**Files:**
- Modify: `chauffeur/services/outings.py`
- Modify: `chauffeur/main.py` (two endpoints)
- Modify: `chauffeur/services/auth.py` (RULES)
- Modify: `chauffeur/services/scope.py` (facet)
- Test: `chauffeur/tests/test_outings.py`, `chauffeur/tests/test_packing_api.py` (create)

**Interfaces:**
- Produces:
  - `outings.day_in_focus(now=None, sched=None) -> datetime.date` — today while any outing is still ahead, otherwise tomorrow.
  - `GET /api/packing/day` → `{'date', 'is_tomorrow', 'outings': [{'key','driver','driver_id','car','start','at','title','event_ids','groups': [...], 'packed', 'needed'}]}`
  - `POST /api/packing/claim` body `{outing_key, item_key, delta: 1|-1, member_id?}` → `{'ok': True, 'packed': n, 'xp': n}`

- [ ] **Step 1: Write the failing tests**

Append to `chauffeur/tests/test_outings.py`:

```python
def scenario_the_day_turns_over_when_the_last_outing_is_home():
    """The household's own rule, and it beats a clock in both directions: 19:00
    is too early on a day with a 20:30 pickup and three hours late on a day
    that ended at 15:00."""
    sched = _sched([_ev('soccer', 16, dur=60)], {'soccer': 'd1'})
    mid = datetime.datetime(2026, 9, 8, 15, 0)
    check(outings.day_in_focus(mid, sched) == datetime.date(2026, 9, 8),
          "an outing still ahead should keep the day on today")
    after = datetime.datetime(2026, 9, 8, 18, 0)
    check(outings.day_in_focus(after, sched) == datetime.date(2026, 9, 9),
          "once the last outing is home the day turns over to tomorrow")


def scenario_a_day_with_no_outings_is_already_tomorrow():
    """Nothing ahead, so nothing to wait for — and no empty-day special case."""
    quiet = datetime.datetime(2026, 9, 8, 9, 0)
    check(outings.day_in_focus(quiet, _sched([], {})) == datetime.date(2026, 9, 9),
          "a day with no outings should already be looking at tomorrow")
```

Create `chauffeur/tests/test_packing_api.py` with scenarios that call the endpoints through FastAPI's `TestClient` (follow the client construction in `chauffeur/tests/test_board_ha_tiles.py`), asserting:

```python
def scenario_the_day_endpoint_groups_by_outing():
    """Two events on one trip are ONE packing job. That grouping IS the message
    — at four activities a day, a sentence saying 'you are not stopping home'
    would fire constantly and stop being read."""
    # seed a cached schedule with the incident's shape, GET /api/packing/day,
    # assert one outing carrying both event ids and both kits' items.


def scenario_a_claim_moves_the_count_and_comes_back():
    # POST /api/packing/claim delta=+1, assert packed == 1 in the response and
    # in a fresh GET; POST delta=-1, assert it is back to 0.


def scenario_a_claim_needs_a_real_outing_and_item():
    # a garbage outing_key is refused rather than filed.
```

- [ ] **Step 2: Run them and watch them fail**

Run: `python tests/test_outings.py` then `python tests/test_packing_api.py`
Expected: FAIL — no `day_in_focus`, no `/api/packing/day` route.

- [ ] **Step 3: Add `day_in_focus`**

Append to `chauffeur/services/outings.py`:

```python
def day_in_focus(now: datetime.datetime = None, sched: dict = None) -> datetime.date:
    """The day the household is actually thinking about.

    Today while any outing is still ahead; tomorrow once the last one is home.
    A clock was the first design and it is wrong in both directions — 19:00 is
    too early on a day with a 20:30 pickup, and hours late on a day that ended
    at three. Following the day also makes two rules free: a trip in progress
    can never be hidden, and a day with no outings at all needs no special case.
    """
    now = now or datetime.datetime.now()
    today = now.date()
    for o in outings_for(today, sched, now):
        end = _parse(o.get('end'))
        if end and end > now:
            return today
    return today + datetime.timedelta(days=1)
```

- [ ] **Step 4: Add the endpoints**

In `chauffeur/main.py`, beside the other prep endpoints (`/api/prep-kits`, around line 8154):

```python
@app.get("/api/packing/day")
def packing_day(date: str = None):
    """Every trip out of the house on the day the household is thinking about,
    with what each one needs packed and how much of it is done.

    Self-fetched by the wall's packing card on the kiosk cadence — an
    interactive card cannot ride a board payload that rebuilds under the finger
    doing the ticking (rule 2).
    """
    from services import outings as _outings
    now = datetime.datetime.now()
    sched = storage.get_cached_schedule() or {}
    target = (_outings._as_date(date) if date else None) or _outings.day_in_focus(now, sched)
    claims = {}
    for row in storage.get_packing_claims(target.isoformat()):
        claims[(row.get('outing_key'), row.get('item_key'))] = \
            claims.get((row.get('outing_key'), row.get('item_key')), 0) + 1
    drivers = {str(d.get('id')): d for d in storage.get_drivers()}
    events = {e.get('id'): e for e in (sched.get('events') or [])}
    kits, pax = storage.get_prep_kits(), _prep.passenger_objs()

    out = []
    for o in _outings.outings_for(target, sched, now):
        groups = _outings.packing_for(o, sched, kits, pax)
        if not groups:
            continue                      # nothing to pack is nothing to draw
        packed = needed = 0
        for g in groups:
            for item in g['items']:
                item['packed'] = min(item['needed'],
                                     claims.get((o['key'], item['key']), 0))
                packed += item['packed']
                needed += item['needed']
        d = drivers.get(o['driver_id']) or {}
        titles = [(events.get(e) or {}).get('title') or 'Event' for e in o['event_ids']]
        out.append({**o, 'groups': groups, 'packed': packed, 'needed': needed,
                    'driver': d.get('name') or 'Driver', 'color': d.get('color'),
                    'car': _car_for(o, sched),
                    'title': ' + '.join(titles)})
    return {'date': target.isoformat(),
            'is_tomorrow': target > now.date(),
            'outings': out}


@app.post("/api/packing/claim")
def packing_claim(payload: dict = Body(...)):
    """One thing packed, or one un-packed. A count, not a checkbox."""
    from services import outings as _outings
    outing_key = str(payload.get('outing_key') or '').strip()
    item_key = str(payload.get('item_key') or '').strip()
    if not outing_key or not item_key:
        raise HTTPException(status_code=400, detail="outing_key and item_key are required")
    now = datetime.datetime.now()
    sched = storage.get_cached_schedule() or {}
    target = (_outings._as_date(payload.get('date'))
              or _outings.day_in_focus(now, sched))
    date_str = target.isoformat()
    # The outing has to be real, or a stale card files claims against a trip
    # that no longer exists and they are invisible for ever.
    live = {o['key'] for o in _outings.outings_for(target, sched, now)}
    if outing_key not in live:
        raise HTTPException(status_code=404, detail="that outing is not on this day")
    member_id = payload.get('member_id') or None
    xp = 0
    if int(payload.get('delta') or 1) >= 0:
        xp = storage.add_packing_claim(outing_key, item_key, date_str, member_id)
    else:
        storage.remove_packing_claim(outing_key, item_key, date_str, member_id)
    packed = sum(1 for r in storage.get_packing_claims(date_str)
                 if r.get('outing_key') == outing_key and r.get('item_key') == item_key)
    return {'ok': True, 'packed': packed, 'xp': xp}
```

Add the small helper beside them:

```python
def _car_for(outing: dict, sched: dict) -> str:
    """Which car this trip goes in. At four activities a day two cars are out
    at once, and a bag packed perfectly into the wrong boot loses the same
    afternoon as one left at home."""
    cars = {str(c.get('id')): c for c in (sched.get('cars') or [])}
    for ev_id in outing.get('event_ids') or []:
        cid = (sched.get('car_assignments') or {}).get(ev_id)
        if cid and str(cid) in cars:
            return cars[str(cid)].get('name') or ''
    return ''
```

- [ ] **Step 5: Declare the lane and the facet**

`chauffeur/services/auth.py`, in `RULES` beside the prep entries (around line 305):

```python
    (ANY, '/api/packing/*', WALL, 'meals.prep'),
```

WALL is `{MEMBER, PARENT, DEVICE}` — a wall panel is a DEVICE, and the wall being able to tick is the entire point of the card.

- [ ] **Step 6: Run both files and watch them pass**

Run: `python tests/test_outings.py` and `python tests/test_packing_api.py`
Expected: PASS.

- [ ] **Step 7: Sweep, bump, commit**

Commit subject: `The packing endpoint, and a day that follows the day (vX.Y.Z)`.

---

### Task 5: The family packing card

**Files:**
- Modify: `chauffeur/services/home_board.py` (catalog entry, builder, `_BUILDERS`)
- Create: `chauffeur/templates/components/packing_card.html`
- Modify: `chauffeur/templates/components/board_tile_body.html` (the branch)
- Test: `chauffeur/tests/test_packing_card.py` (create)

**Interfaces:**
- Consumes: `GET /api/packing/day`, `POST /api/packing/claim` (Task 4).
- Produces: board card type `packing`; builder `_tile_packing(now, config=None, **_)` returning mount config `{'interactive': bool, 'members': [ids]}` or `None`.

**The precedent to copy is `chores_lanes`** — an interactive card that self-fetches. Catalog entry at `home_board.py:409-431`, builder at `home_board.py:1806-1822`, registry at `home_board.py:3696`, tile-body branch at `board_tile_body.html:434-438` (`x-data="choresLanesCard(t, apiBase)" x-init="startLanes()"`).

- [ ] **Step 1: Write the failing test**

Create `chauffeur/tests/test_packing_card.py` asserting, with builders stubbed the way `tests/test_board_cards.py` does it:

```python
def scenario_a_household_with_no_kits_gets_no_card():
    """Rule 1's first half: hide what is not SET UP. No prep kits at all means
    the household has never used this, and the card vanishes the way any
    unconfigured feature's does."""


def scenario_a_quiet_day_says_so_rather_than_vanishing():
    """Rule 1's second half, and the half that was learned the hard way: never
    hide what is merely quiet. A household with kits and a day that needs
    nothing packed gets a sentence, because a card that disappears is
    indistinguishable from a card that broke."""


def scenario_the_card_carries_only_its_mount_config():
    """Rule 2: interactive depth means the card fetches its own data. The
    builder ships `interactive` and the members filter and nothing else — a
    payload rebuilding under the finger doing the ticking cannot carry counts."""


def scenario_interactive_defaults_on():
    """The card-conversion paradigm: an inert packing list is a poster. Off
    stays available for a wall that really is only a display."""
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python tests/test_packing_card.py`
Expected: FAIL — no `packing` in the catalog.

- [ ] **Step 3: Add the catalog entry**

In `chauffeur/services/home_board.py`, beside the other cards in `WIDGETS`:

```python
    {'key': 'packing', 'icon': '🎒', 'label': 'Packing',
     'heading': "Getting out of the door",
     'blurb': "Every trip out of the house today and what has to be packed "
              "for it — two events on one trip are one list.",
     'options': [
         # ON by default, the same reasoning the lanes card settled: a packing
         # list nobody can tick is a poster. Off remains for a wall that really
         # is only a display.
         _opt('interactive', 'Interactive', 'bool', True,
              help='Tick things off on the wall. Off, the card is a display.'),
         _opt('members', 'People', 'select', [], source='members', multi=True,
              help='Leave empty for the whole household.'),
     ]},
```

- [ ] **Step 4: Add the builder and register it**

```python
def _tile_packing(now, config=None, **_):
    """Today's outings and what they need packed. Interactive depth, so the
    card fetches its own list (rule 2) — this is only the mount config.

    Nothing to pack is nothing drawn (rule 1): the builder cannot know that
    without doing the work, so it does the cheap half — no prep kits at all
    means the household has never set this up.
    """
    try:
        if not storage.get_prep_kits():
            return None
        return {'interactive': _cfg_bool(config, 'interactive', True),
                'members': _cfg_ids(config, 'members')}
    except Exception as e:
        print(f"[home_board] packing card failed: {e}")
        return None
```

and in `_BUILDERS`: `'packing': _tile_packing,`.

- [ ] **Step 5: Write the card component**

Create `chauffeur/templates/components/packing_card.html` following `components/routine_lanes.html`'s shape (a Jinja macro for the markup plus a `<script>` defining the Alpine factory). The factory `packingCard(t, apiBase)` must:

- fetch `GET {apiBase}api/packing/day` on mount and every 30s (`startPacking()`), holding `outings`, `date`, `isTomorrow`;
- draw **one row per outing** in departure order — driver, car, time, title (`Soccer + swim`), and progress (`2/6`) — with the **first unfinished outing expanded** to its kit groups and items;
- draw each item as a stepper when `needed > 1` (`− n/needed +`) and a plain tick when `needed === 1`;
- post `{outing_key, item_key, delta}` to `api/packing/claim`, applying the change locally first and re-fetching on failure (the optimistic pattern at `app.html:7592-7611`), and never `alert()` — `showGlobalAlert` on failure;
- render nothing at all when `outings` is empty;
- show a **"Tomorrow"** chip when `isTomorrow`, because a card silently answering a different day is the wrong-question failure this design exists to avoid.

- [ ] **Step 6: Join the registries a card must join**

Three edits, each enforced by an existing test that will otherwise fail:

`chauffeur/services/home_board.py`, in `REQUIRED_EMPTY` (around line 3444) — a card
that can be marked "always show" needs a sentence, or requiring it draws a blank
panel instead of an explanation:

```python
    'packing': "Nothing to pack for today's outings.",
```

`chauffeur/templates/home.html`, in `PAGELESS` (around line 5234) — a type belongs
to `PAGES` or `PAGELESS` and never neither; absent from both, a tap lands on a URL
no route serves. This card is `PAGELESS` for the same reason the lanes card is: its
content *is* buttons, and an `<a href>` may not contain them.

```python
                           'chores_lanes', 'chores_rewards', 'packing',
```

Keep that literal free of comments — several tests read it as a fixed window of
characters after the name.

`chauffeur/templates/home.html` (around line 1476), beside the other component
script includes — `{% import %}` renders the macros, `{% include %}` emits the
component's `<script>` exactly once per page, and the card needs both:

```jinja
{% include 'components/packing_card.html' %}
```

- [ ] **Step 7: Add the tile-body branch**

In `chauffeur/templates/components/board_tile_body.html`, beside the `chores_lanes` branch:

```html
                    <template x-if="t.type === 'packing'">
                        <div x-data="packingCard(t, apiBase)" x-init="startPacking()">
                            {{ packing.rows() }}
                        </div>
                    </template>
```

with the matching `{% import 'components/packing_card.html' as packing %}` at the top of the file.

- [ ] **Step 8: Run the tests and watch them pass**

```bash
python tests/test_packing_card.py
python tests/test_board_instances.py    # the option sweep: catches a dead option
python tests/test_builtin_boards.py     # builder + drawing branch + interactive default
python tests/test_home_board.py         # catalog, rule 1, PAGES/PAGELESS
```
Expected: PASS. `test_home_board.py`'s blank-install sweep asserts a fresh install
draws the calendar and nothing else — the builder's `None` when no prep kits exist
is what keeps this card out of it.

- [ ] **Step 9: Tailwind, sweep, bump, commit**

Commit subject: `The family packing card (vX.Y.Z)`.

---

### Task 6: Prove it on a real wall

**Files:**
- Test: `chauffeur/tests/test_packing_card.py` (add a chromium scenario)

The design's testing section asks for this explicitly, and the failure it guards is one this repo has already been burned by: **the board rebuilds every 20 seconds, and a checklist that resets on poll is worse than no checklist.**

- [ ] **Step 1: Write the browser scenario**

The repo's convention for an interactive card is a **jsdom render test** —
`tests/test_chores_lanes_render.py` is the model: render the real template through
Jinja, load it into jsdom, run Alpine against a stubbed `fetch`, and inspect the
DOM. Copy that file's shape, including its skip-when-node-is-absent guard and its
`encoding='utf-8'` reads. It must assert the interactivity gate the same way that
file does (`interactive: false` draws no buttons at all — a hidden button still
answers `querySelector`), and that merely drawing the card POSTs nothing.

Then, in `tests/test_packing_card.py`, add the one thing jsdom cannot answer, using
`tests/test_board_card_grid.py`'s playwright harness:

- a ten-activity Saturday stays readable: one row per outing, one expanded;
- tapping `+` on an item moves its count and the outing's progress;
- **a simulated poll that returns the same data does not reset the count**;
- an item at `needed` cannot be pushed past it.

- [ ] **Step 2: Run it, watch it fail, implement, watch it pass**

Run: `python tests/test_packing_card.py`

- [ ] **Step 3: Sweep, bump, commit**

Commit subject: `A packing tick survives the board's own poll (vX.Y.Z)`.

---

### Task 7: Say what changed

**Files:**
- Modify: `chauffeur/system_capabilities.md`
- Modify: `chauffeur/docs/packing_design.md` (stamp the shipped slices)

- [ ] **Step 1: Write the capabilities entry**

In the board/cards section, in that document's own voice (prose explaining WHY, not a changelog): the outing concept and where it comes from (the solver's `home_waypoint` absence); that two events on one trip are one packing job and the grouping *is* the message; the needed-count rule and the `per_person` kit flag; claims, anonymous on the wall and named on a phone; the XP rule and the three things a tick never touches; and the day-follows-the-day turn-over.

- [ ] **Step 2: Mark P1 and P2 built in the design doc**

Add a line under each slice saying it shipped and at what version. Leave P3–P5 as they are — they get their own plan.

- [ ] **Step 3: Full sweep, bump, commit, push**

- [ ] **Step 4: Deploy and look at it**

Add-on store → *Check for updates* → rebuild → confirm the version. Then put the card on a board and check the thing the household actually asked for: a day with two events on one trip shows **one** list, and ticking on the wall sticks.

---

## Self-review

**Spec coverage.** The outing concept → Task 1. Counts, the group exception, dedupe by person → Task 2. Claims, XP, the routine boundary's "no points, no streak" → Task 3. The day-follows-the-day turn-over and the API → Task 4. The tile, density shape (rows not items), driver and car per row → Task 5. The poll-survival and ten-activity cases → Task 6.

**Deliberately not in this plan** (they are P3–P5 in the design and get their own): the kid's My Day items and their evening-bucket placement, the driver's phone list, the drive sheet becoming the outing's list with one loading confirmation, one-off items and their editors, and the `My Drives` → `My Day` rescope.

**Names.** `outings_for`, `packing_for`, `day_in_focus`, `add_packing_claim`, `remove_packing_claim`, `get_packing_claims`, `_tile_packing`, `packingCard` — each defined in the task that first uses it and spelled the same everywhere after.

**Known gap, deliberate:** no surface in P1+P2 produces a *named* claim, so the XP path ships tested but unexercised until P3 gives a child somewhere to tick. That is why Task 3 tests it directly rather than through a surface.

# The Family Day card — implementation plan (F1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The packing card becomes the wall's one answer to "what is happening today and are we ready" — every block of the day (outings, at-home events, covered rides) in one agenda-parseable card, with packing readiness woven in — and the default home board leads with it.

**Architecture:** A new pure-computation service (`services/family_day.py`) composes the shipped outing machinery with the full event feed (`sched['events']`) into time-ordered *blocks*: the event block is the atom, the outing is a container that materializes only at two or more events, covered rides return as bare blocks, all-day events become a banner. The `/api/packing/day` endpoint serves blocks; the card (key `packing`, evolved in place) draws an agenda at rest with a two-state amber pill and tap-to-expand. The default board swaps `calendar` + `drives` for this card.

**Tech Stack:** Python 3 + FastAPI, TinyDB/SQLite dual storage (no new tables), Jinja + vanilla Alpine, precompiled Tailwind, repo test harnesses (python scenarios, node/jsdom, playwright).

**Spec:** `docs/family_day_design.md` — read it first; where this plan and the design disagree, the design wins. `docs/packing_design.md` documents the shipped mechanics this builds on.

## Global Constraints

- **Run tests with `python tools/test.py`** (parallel) from `chauffeur/`; `--focus <file>` for the inner loop; never serial, never piped. Full sweep before every commit. Known unrelated flake: `test_coverage_ladder.py` `scenario_nudges_come_when_a_reply_would_exist`.
- **Bump `config.yaml`'s `version:` on every commit**, subject ends `(vX.Y.Z)`. No double quotes in commit messages — write to a file, `git commit -F`. Do not push mid-plan.
- **`python tools/build_tailwind.py` after touching any template.**
- **Never PowerShell `Get-Content`/`Set-Content` round-trips on source.**
- **Never `alert()`/`confirm()`/`prompt()`** — `showGlobalAlert` on failure.
- **The card self-fetches (rule 2)**; the builder ships mount config only.
- **A tick mints critter XP and nothing else.** Claims mechanics (`add/remove/get_packing_claim`) are shipped and MUST NOT change in this plan.
- **The solver sees nothing new.** Blocks are a read-only lens: all-day events stay out of `driver_events`, covered events stay unassigned, the card writes nothing but claims.
- **The eye-catcher has exactly two states** (amber `N to pack` / muted done) — no proximity escalation, no pulsing.
- **Deliberate rule flips this plan ships** (each un-does a shipped decision, per the design): (1) an outing with nothing to pack draws; (2) a household with no prep kits still gets the card — it is the day surface now, not a packing feature; (3) turnover follows the last block; (4) covered rides appear with their packing.
- **Existing scenario moves must be disclosed, never silent**: where this plan says a test scenario moves or changes meaning, the commit touching it is the commit that says so.

---

### Task 1: Blocks — the day as a list

**Files:**
- Create: `chauffeur/services/family_day.py`
- Test: `chauffeur/tests/test_family_day.py` (create)

**Interfaces:**
- Consumes: `outings.outings_for(target_date, sched, now)` (list of `{'key','driver_id','event_ids','start','end'}`), `outings._parse`, `outings._as_date`; the schedule cache shape `{'events','assignments','assist_assignments','assist_contacts','route_edges','final_edges'}`. Event dicts carry `id,title,start,end,all_day,event_type,canceled,optional_decision,calendar_ids` (stamped at solve time — see `main.py:15493-15502`, `services/cancellations.py:60-69`, `services/optional_events.py:62-83`).
- Produces:
  - `family_day.blocks_for(target_date=None, sched=None, now=None) -> dict` returning `{'blocks': [...], 'all_day': [titles]}`. Each block:
    - outing kind: `{'kind':'outing','key','driver_id','event_ids','start','end','events':[{'id','title','start'}]}` (outing fields verbatim from `outings_for`, plus the inner event lines)
    - event kind: `{'kind':'event','key': f"home:{event_id}", 'event_id','title','start','end','canceled': bool,'covered_by': str|None}`
    - blocks sorted by `(start, key)`.
  - `family_day.day_in_focus(now=None, sched=None) -> datetime.date` — today while any non-canceled block's end is ahead, else tomorrow. **This becomes the canonical turnover rule**; Task 2 migrates the endpoints to it and retires `outings.day_in_focus`.

- [ ] **Step 1: Write the failing test**

Create `chauffeur/tests/test_family_day.py`:

```python
"""The day as BLOCKS: the event is the atom, the outing is a container.

The wall answered "what is happening and are we ready" in four cards, and a
person had to join them in their head. The block spine is the join: driven
trips come from the outing machinery, at-home events come from the same event
feed the calendar card reads, covered rides come back from the dead (an event
Grandma drives has no household driver, so `outings_for` never saw it and its
packing vanished — a repair, not a feature), and all-day events become a
banner because they have no time to anchor a block to.

Run from chauffeur/:  python tests/test_family_day.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_famday_'))

import datetime  # noqa: E402

from services import family_day  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


DAY = '2026-09-08'


def _ev(eid, hh, mm=0, dur=60, title=None, **extra):
    start = datetime.datetime(2026, 9, 8, hh, mm)
    return {'id': eid, 'title': title or eid,
            'start': start.isoformat(),
            'end': (start + datetime.timedelta(minutes=dur)).isoformat(),
            **extra}


def _sched(events, assignments=None, route_edges=None, **extra):
    return {'events': events, 'assignments': assignments or {},
            'route_edges': route_edges or {}, 'initial_edges': {},
            'final_edges': {}, **extra}


def scenario_a_driven_event_is_an_outing_block():
    got = family_day.blocks_for(DAY, _sched([_ev('soccer', 16)], {'soccer': 'd1'}))
    check([b['kind'] for b in got['blocks']] == ['outing'],
          f"a driven event should be an outing block: {got['blocks']}")
    check(got['blocks'][0]['events'][0]['title'] == 'soccer',
          f"the outing block should carry its inner event lines: {got['blocks'][0]}")


def scenario_an_undriven_event_is_a_home_block():
    """The at-home birthday party: no assignment, still a happening."""
    got = family_day.blocks_for(DAY, _sched([_ev('party', 12, title='Birthday')]))
    b = got['blocks']
    check([x['kind'] for x in b] == ['event'], f"an undriven event is a bare block: {b}")
    check(b[0]['key'] == 'home:party', f"home blocks key as home:<event_id>: {b[0]}")


def scenario_a_covered_ride_names_its_hand():
    """Grandma driving does not mean the bag packs itself."""
    sched = _sched([_ev('swim', 15, 30)],
                   assist_assignments={'swim': 'c9'},
                   assist_contacts=[{'id': 'c9', 'name': 'Carol',
                                     'relation_label': 'Grandma'}])
    got = family_day.blocks_for(DAY, sched)
    b = got['blocks']
    check(len(b) == 1 and b[0]['covered_by'] == 'Grandma',
          f"a covered ride is a block naming its hand: {b}")


def scenario_blocks_interleave_in_time_order():
    sched = _sched([_ev('party', 12, title='Birthday'), _ev('soccer', 9)],
                   {'soccer': 'd1'})
    got = family_day.blocks_for(DAY, sched)
    check([b['kind'] for b in got['blocks']] == ['outing', 'event'],
          f"blocks interleave by start time: {got['blocks']}")


def scenario_all_day_events_are_a_banner_not_blocks():
    sched = _sched([_ev('spirit', 0, title='Spirit Week', all_day=True),
                    _ev('soccer', 16)], {'soccer': 'd1'})
    got = family_day.blocks_for(DAY, sched)
    check(got['all_day'] == ['Spirit Week'], f"all-day is a banner: {got['all_day']}")
    check(len(got['blocks']) == 1, f"all-day never becomes a block: {got['blocks']}")


def scenario_a_skipped_optional_event_is_not_a_happening():
    """The family decided not to go. Drawing it anyway would nag the decision."""
    sched = _sched([_ev('fair', 10, optional_decision='skip')])
    check(family_day.blocks_for(DAY, sched)['blocks'] == [],
          "a skip-decided event became a block")


def scenario_a_canceled_event_is_a_struck_block():
    """Canceled is drawn, not hidden — the household needs to know it fell
    through (the cancellations arc's own rule) — but it carries no items."""
    got = family_day.blocks_for(DAY, _sched([_ev('game', 14, canceled=True)]))
    b = got['blocks']
    check(len(b) == 1 and b[0]['canceled'], f"a canceled event draws, struck: {b}")


def scenario_background_trips_are_not_blocks():
    got = family_day.blocks_for(DAY, _sched(
        [_ev('bg', 8, event_type='background_trip')]))
    check(got['blocks'] == [], f"a background trip leaked into the day: {got}")


def scenario_a_driven_events_block_is_not_doubled():
    """An event inside an outing must not also appear as a home block."""
    got = family_day.blocks_for(DAY, _sched([_ev('soccer', 16)], {'soccer': 'd1'}))
    check(len(got['blocks']) == 1, f"a driven event appeared twice: {got['blocks']}")


def scenario_the_day_turns_over_when_the_last_block_ends():
    """The turnover rule, widened: a day ending with an at-home party must not
    flip to tomorrow mid-party. (Moved here from test_outings.py where it
    watched only outings — the rule now watches blocks.)"""
    sched = _sched([_ev('party', 19, dur=120, title='Birthday')])
    mid = datetime.datetime(2026, 9, 8, 20, 0)
    check(family_day.day_in_focus(mid, sched) == datetime.date(2026, 9, 8),
          "a live home block should keep the day on today")
    after = datetime.datetime(2026, 9, 8, 21, 30)
    check(family_day.day_in_focus(after, sched) == datetime.date(2026, 9, 9),
          "once the last block ends the day turns over")


def scenario_a_canceled_block_does_not_hold_the_day():
    sched = _sched([_ev('game', 20, canceled=True)])
    quiet = datetime.datetime(2026, 9, 8, 9, 0)
    check(family_day.day_in_focus(quiet, sched) == datetime.date(2026, 9, 9),
          "a canceled event held the day on today")


def scenario_an_empty_day_is_already_tomorrow():
    """(Moved from test_outings.py, same meaning, wider input.)"""
    quiet = datetime.datetime(2026, 9, 8, 9, 0)
    check(family_day.day_in_focus(quiet, _sched([])) == datetime.date(2026, 9, 9),
          "a day with no blocks should already be looking at tomorrow")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} family-day scenarios passed")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python tests/test_family_day.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.family_day'`.

- [ ] **Step 3: Write the service**

Create `chauffeur/services/family_day.py`:

```python
"""The day as BLOCKS — the one spine the wall's Family Day card draws.

The event block is the atom. The outing (services/outings.py) is a container
over driven events; at-home and covered events are bare blocks from the same
feed the calendar card reads (`sched['events']` carries everything — driven,
undriven, canceled-and-stamped, skip-decided — see main.py's solve cache
assembly). All-day events become a banner: they have no time to anchor a
block to, and they must never reach the solver.

Pure computation over the schedule cache: nothing stored, nothing written,
safe on every poll. The solver sees nothing new through this module.
"""
import datetime
from typing import List, Optional

from services import outings, storage


def blocks_for(target_date=None, sched: dict = None,
               now: datetime.datetime = None) -> dict:
    """Every block of one day, time-ordered, plus the all-day banner."""
    now = now or datetime.datetime.now()
    target = outings._as_date(target_date) or now.date()
    sched = sched if sched is not None else (storage.get_cached_schedule() or {})
    events = {e.get('id'): e for e in (sched.get('events') or [])}
    assist = sched.get('assist_assignments') or {}
    contacts = {str(c.get('id')): c
                for c in (sched.get('assist_contacts')
                          or _assist_contacts_fallback())}

    blocks = []
    all_day = []
    outing_rows = outings.outings_for(target, sched, now)
    inside_an_outing = {eid for o in outing_rows for eid in o['event_ids']}
    for o in outing_rows:
        blocks.append({'kind': 'outing', **o,
                       'events': [_line(events.get(e)) for e in o['event_ids']]})

    for ev_id, ev in events.items():
        start = outings._parse((ev or {}).get('start'))
        if not ev or not start or start.date() != target:
            continue
        if ev.get('all_day'):
            all_day.append(ev.get('title') or 'All day')
            continue
        if ev.get('event_type') == 'background_trip':
            continue
        if ev_id in inside_an_outing:
            continue
        if ev.get('optional_decision') == 'skip':
            # The family decided not to go; drawing it anyway nags a decision
            # already made (the optional-events arc's own no-daily-ping rule).
            continue
        cov = assist.get(ev_id)
        c = contacts.get(str(cov)) or {}
        end = outings._parse(ev.get('end')) or start
        blocks.append({
            'kind': 'event',
            'key': f"home:{ev_id}",
            'event_id': ev_id,
            'title': ev.get('title') or 'Event',
            'start': start.isoformat(),
            'end': end.isoformat(),
            'canceled': bool(ev.get('canceled')),
            'covered_by': ((c.get('relation_label') or c.get('name')
                            or 'Outside help') if cov else None),
        })

    blocks.sort(key=lambda b: (b['start'], b['key']))
    all_day.sort()
    return {'blocks': blocks, 'all_day': all_day}


def day_in_focus(now: datetime.datetime = None, sched: dict = None) -> datetime.date:
    """The day the household is actually thinking about.

    Today while any block is still ahead; tomorrow once the last one is done.
    This is the packing arc's day-follows-the-day rule with wider input: a day
    ending with an at-home party must not flip to tomorrow mid-party. Canceled
    blocks never hold the day — a thing that is not happening cannot be ahead.
    """
    now = now or datetime.datetime.now()
    today = now.date()
    sched = sched if sched is not None else (storage.get_cached_schedule() or {})
    for b in blocks_for(today, sched, now)['blocks']:
        if b.get('canceled'):
            continue
        end = outings._parse(b.get('end'))
        if end and end > now:
            return today
    return today + datetime.timedelta(days=1)


def _line(ev) -> dict:
    """The compact inner line an outing container shows: title and time only —
    driver and car live on the container."""
    ev = ev or {}
    return {'id': ev.get('id'), 'title': ev.get('title') or 'Event',
            'start': ev.get('start')}


def _assist_contacts_fallback() -> list:
    try:
        return storage.get_assist_contacts(include_inactive=True)
    except Exception:
        return []
```

- [ ] **Step 4: Run it and watch it pass**

Run: `python tests/test_family_day.py`
Expected: PASS, 12/12.

- [ ] **Step 5: Full sweep, bump, commit**

Run: `python tools/test.py`
Bump `config.yaml`, commit subject: `The day is a list of blocks (vX.Y.Z)`.

---

### Task 2: The endpoint serves blocks

**Files:**
- Modify: `chauffeur/main.py` (`packing_day`, `packing_claim`)
- Modify: `chauffeur/services/outings.py` (retire `day_in_focus`)
- Test: `chauffeur/tests/test_packing_api.py` (update), `chauffeur/tests/test_outings.py` (disclosed scenario removals)

**Interfaces:**
- Consumes: `family_day.blocks_for`, `family_day.day_in_focus` (Task 1); `outings.packing_for(outing, sched, kits, passengers)` (shipped — takes any dict with `event_ids`, so a home block claims items via the pseudo-outing `{'event_ids': [event_id]}`); `storage.add/remove/get_packing_claims` (shipped, untouched).
- Produces:
  - `GET /api/packing/day` → `{'date','is_tomorrow','all_day':[titles],'blocks':[...]}` where each block adds to Task 1's shape: `groups` (kit groups with per-item `packed`/`needed`), `packed`, `needed`, and for outing blocks `driver`, `driver_id`, `color`, `car`. Canceled blocks carry no groups. **Blocks with no groups still draw** — rule flip 1; the response's `outings` field is gone.
  - `POST /api/packing/claim` — accepts outing keys AND `home:<event_id>` keys; still validates `item_key` against the block's real items; still ignores payload `member_id`; still refuses `delta: 0`; **new: the server caps adds at `needed`** — an add against a full item is a no-op returning the current count (closes the racing-walls gap the final review parked).

- [ ] **Step 1: Update the API tests**

Rework `chauffeur/tests/test_packing_api.py` (keep its fixture style — direct endpoint-function calls, `_seed_incident()` seeding the cached schedule):

- `scenario_the_day_endpoint_groups_by_outing` — keep the incident fixture; assert the response's `blocks` list has ONE block of kind `outing` carrying both event ids and both kits' items (the grouping is unchanged; only the envelope moved from `outings` to `blocks`).
- `scenario_a_claim_moves_the_count_and_comes_back` — unchanged semantics; read counts through `blocks`.
- `scenario_a_claim_needs_a_real_outing_and_item`, `scenario_a_garbage_item_key_on_a_real_outing_is_refused`, `scenario_a_claimed_member_id_from_the_payload_never_reaches_the_ledger`, `scenario_delta_zero_is_refused_not_treated_as_plus_one` — unchanged.
- New `scenario_a_home_block_takes_claims_too`: seed an undriven event matching a kit; GET shows the `home:<id>` block with items; POST a claim against `outing_key='home:<id>'` + a real item key; assert packed moves.
- New `scenario_a_drive_with_nothing_to_pack_still_draws`: seed a driven event matching no kit; assert its block appears with `groups == []` and `needed == 0` (rule flip 1 — the old endpoint dropped it).
- New `scenario_the_server_caps_a_claim_at_needed`: one kit, one passenger (`needed == 1`); claim once (packed 1), claim again — assert the response still says `packed == 1` and `storage.get_packing_claims` holds exactly one row for that item.
- New `scenario_a_canceled_block_carries_no_items`: seed a canceled event matching a kit; assert its block draws with `canceled: True` and `groups == []`.

- [ ] **Step 2: Run and watch the new/changed scenarios fail**

Run: `python tests/test_packing_api.py`
Expected: FAIL — response has no `blocks`.

- [ ] **Step 3: Rework the endpoints**

In `chauffeur/main.py`, `packing_day` becomes (keep the local `import datetime` convention and the existing `_prep`/`Body`/`HTTPException` imports):

```python
@app.get("/api/packing/day")
def packing_day(date: str = None):
    """Every block of the day the household is thinking about — outings,
    at-home events, covered rides — with what each needs packed and how much
    is done. The Family Day card's feed (self-fetched, rule 2).

    A block with nothing to pack still draws: a drive is a happening whether
    or not it has cargo. That inverts the packing tile's old rule on purpose
    (docs/family_day_design.md, "What changes underneath").
    """
    import datetime
    from services import family_day as _fam
    from services import outings as _outings
    now = datetime.datetime.now()
    sched = storage.get_cached_schedule() or {}
    target = (_outings._as_date(date) if date else None) or _fam.day_in_focus(now, sched)
    day = _fam.blocks_for(target, sched, now)
    claims = {}
    for row in storage.get_packing_claims(target.isoformat()):
        k = (row.get('outing_key'), row.get('item_key'))
        claims[k] = claims.get(k, 0) + 1
    drivers = {str(d.get('id')): d for d in storage.get_all_drivers()}
    kits, pax = storage.get_prep_kits(), _prep.passenger_objs()

    out = []
    for b in day['blocks']:
        groups = [] if b.get('canceled') else _outings.packing_for(
            {'event_ids': (b['event_ids'] if b['kind'] == 'outing'
                           else [b['event_id']])}, sched, kits, pax)
        packed = needed = 0
        for g in groups:
            for item in g['items']:
                item['packed'] = min(item['needed'],
                                     claims.get((b['key'], item['key']), 0))
                packed += item['packed']
                needed += item['needed']
        row = {**b, 'groups': groups, 'packed': packed, 'needed': needed}
        if b['kind'] == 'outing':
            d = drivers.get(b['driver_id']) or {}
            row.update({'driver': d.get('name') or 'Driver',
                        'color': d.get('color_code'),
                        'car': _car_for(b, sched)})
        out.append(row)
    return {'date': target.isoformat(),
            'is_tomorrow': target > now.date(),
            'all_day': day['all_day'],
            'blocks': out}
```

`packing_claim` keeps its shape; the changed middle section:

```python
    # The block has to be real and the item has to be one of its own — a
    # stale card must not file claims into the void, and a fabricated
    # item_key must not mint XP (each distinct key is a fresh once-guard).
    day = _fam.blocks_for(target, sched, now)
    by_key = {b['key']: b for b in day['blocks']}
    block = by_key.get(outing_key)
    if block is None:
        raise HTTPException(status_code=404, detail="that block is not on this day")
    kits, pax = storage.get_prep_kits(), _prep.passenger_objs()
    groups = [] if block.get('canceled') else _outings.packing_for(
        {'event_ids': (block['event_ids'] if block['kind'] == 'outing'
                       else [block['event_id']])}, sched, kits, pax)
    needed_by_item = {i['key']: i['needed'] for g in groups for i in g['items']}
    if item_key not in needed_by_item:
        raise HTTPException(status_code=404, detail="that item is not on this block")
```

and the add path gains the cap (the remove path is unchanged):

```python
    current = sum(1 for r in storage.get_packing_claims(date_str)
                  if r.get('outing_key') == outing_key
                  and r.get('item_key') == item_key)
    xp = 0
    if delta > 0:
        # Server-side cap: two walls racing past the client's disabled button
        # must not file surplus claims that make the first untick look dead.
        if current < needed_by_item[item_key]:
            xp = storage.add_packing_claim(outing_key, item_key, date_str, None)
    else:
        storage.remove_packing_claim(outing_key, item_key, date_str, None)
```

(P3 note, keep as a comment where `None` is passed: identity comes from the session there, never the payload.)

- [ ] **Step 4: Retire `outings.day_in_focus` — a disclosed move**

Delete `day_in_focus` from `chauffeur/services/outings.py` (its rule now lives, widened, in `family_day.day_in_focus`; keeping both invites drift). In `chauffeur/tests/test_outings.py`, remove these four scenarios and ONLY these — their meaning moved to `test_family_day.py` in Task 1 (`scenario_the_day_turns_over_when_the_last_block_ends`, `scenario_an_empty_day_is_already_tomorrow`) and to the drive-home scenarios that remain:

- `scenario_the_day_turns_over_when_the_last_outing_is_home`
- `scenario_a_day_with_no_outings_is_already_tomorrow`
- `scenario_day_in_focus_stays_on_today_during_the_drive_home` → **re-add this one to `test_family_day.py`** in this task, using a driven fixture with a `final_edges` drive-home entry, asserting `family_day.day_in_focus` stays on today during the drive-home window (the widened rule must not lose the drive home).

All other `test_outings.py` scenarios (chaining, packing counts, drive-home ends) stay byte-identical. The commit message body for this task names the moved scenarios.

- [ ] **Step 5: Run and watch everything pass**

Run: `python tests/test_packing_api.py`, `python tests/test_family_day.py`, `python tests/test_outings.py`
Expected: PASS.

- [ ] **Step 6: Sweep, bump, commit**

Commit subject: `The packing endpoint serves the whole day (vX.Y.Z)`.

---

### Task 3: The card becomes Family Day

**Files:**
- Modify: `chauffeur/templates/components/packing_card.html` (reshape)
- Modify: `chauffeur/services/home_board.py` (catalog entry text, builder gating, `REQUIRED_EMPTY`)
- Test: `chauffeur/tests/test_packing_card_builder.py` (update), `chauffeur/tests/test_packing_card_render.py` (update), `chauffeur/tests/test_home_board.py` (blank-install expectation — disclosed change)

**Interfaces:**
- Consumes: `GET /api/packing/day` blocks payload, `POST /api/packing/claim` (Task 2).
- Produces: the evolved card. Key stays `packing` (instances-not-types: stored placements and config survive untouched; `normalize_instances` keys identity off `type` alone — `home_board.py:3971-4030`). Catalog label becomes **Family day**, icon `🗓️`, heading **"The family's day"**, blurb: `"Everything happening today and what has to be ready for it — trips, home, and who is driving."` Options unchanged (`interactive` default ON, `members`).

**UI design instruction:** the implementer invokes the `frontend-design:frontend-design` skill before touching the template, and applies it WITHIN the existing token layer — this card must read as the same design system, quieter and denser than before. The mockup in `docs/family_day_design.md` ("Presentation: an agenda at rest") is the target rendering.

- [ ] **Step 1: Update the builder tests**

In `chauffeur/tests/test_packing_card_builder.py`:

- `scenario_a_household_with_no_kits_gets_no_card` → **inverts, renamed** `scenario_a_household_with_no_kits_still_gets_the_day`: the builder returns mount config with no prep kits — the card is the day surface now, not a packing feature (rule flip 2; the design's "board swap" section is the authority). The docstring must say what it inverted and why.
- `scenario_a_quiet_day_says_so_rather_than_vanishing` → sentence source updates: `REQUIRED_EMPTY['packing']` becomes `"Nothing on the calendar today."` (the day-level empty state; "nothing to pack" is no longer the card's question).
- `scenario_the_card_carries_only_its_mount_config`, `scenario_interactive_defaults_on` — unchanged.
- `scenario_the_quiet_day_sentence_is_gated_on_a_resolved_empty_fetch` — retarget the pinned sentence to the new text, same gating assertions (`pkLoaded`, `!blocks.length`).

- [ ] **Step 2: Run and watch the changed ones fail**

Run: `python tests/test_packing_card_builder.py`
Expected: FAIL — builder still returns `None` without kits; old sentence.

- [ ] **Step 3: Catalog + builder + registry edits**

In `chauffeur/services/home_board.py`:

- Catalog entry (`'key': 'packing'`, ~line 436): label `'Family day'`, icon `'🗓️'`, heading `"The family's day"`, blurb per Interfaces above. Options untouched.
- Builder `_tile_packing`: remove the `get_prep_kits()` gate; it always returns `{'interactive': ..., 'members': ...}` (inside the existing try/except). Docstring: the card is the wall's day surface; the calendar is core, so there is no unconfigured state — rule 1's None is for features a household never set up, and the day is not a feature.
- `REQUIRED_EMPTY['packing']` = `"Nothing on the calendar today."`

In `chauffeur/tests/test_home_board.py`, the blank-install sweep asserts a fresh install draws the calendar and nothing else — with the builder gate gone, `packing` now also draws on a blank install. **Update that expectation to allow exactly `{'calendar', 'packing'}`** with a comment naming this plan; Task 5 swaps the default board so the fresh-install wall leads with Family Day. This is a disclosed change to a shipped invariant, named in the commit body.

- [ ] **Step 4: Reshape the card template**

`chauffeur/templates/components/packing_card.html` — the factory keeps its name (`packingCard(t, apiBase)`, `startPacking()`, 30s poll, `pkLoaded`, `pkPending`, `pkFindItem`, optimistic `pkClaim` with release-before-reconcile: all mechanics survive; item lookup now walks `blocks`). The rendering contract:

- State: `blocks`, `allDay`, `date`, `isTomorrow`, `expandedKeys` (a Set of block keys; toggled by tap; survives the poll exactly as tick state does).
- **All-day banner** first when `allDay.length` — one slim muted line joining the titles.
- **One row per block, time-ordered** (server order). Flat row for `kind === 'event'` and for outings with one inner event: time, icon (`🚗` outing / `🏠` home / `🤝` covered — covered shows `covered_by` as a quiet chip), title, driver + car chips (outings only), then the pill.
- **Container** for outings with ≥2 inner events: outer row carries time-of-first-event, `🚗`, driver + car chips, the pill; inner compact lines (title + time only) always visible, indented.
- **The pill, two states exactly**: `needed - packed > 0` → filled amber pill `N to pack` (the only saturated element on a resting row); `needed > 0 && packed === needed` → muted `✓`; `needed === 0` → nothing. Amber uses the token layer's amber, not a new color.
- **Tap a row/container** toggles its key in `expandedKeys`; expanded shows the kit groups and items — the shipped item markup (steppers when `needed > 1`, ticks at 1, disabled at 0 and at `needed`) moves inside the expansion unchanged. **No block auto-expands.**
- Canceled blocks: line-through title, no pill, not expandable.
- `interactive: false`: no claim buttons in the DOM at all (the shipped `x-if` split), rows still expandable to read.
- **Member-filter fix (parked finding, fixed here):** the `members` config filter narrows which *people's* items show — but a kit with empty `passenger_ids` covers the household and must survive any member filter. Filter logic: a group is shown when `members` is empty, OR `group.people` intersects `members`, OR `group.people` is empty.
- Quiet day: `pkLoaded && !blocks.length` → `"Nothing on the calendar today."` (same inline styling as today); Tomorrow chip when `isTomorrow` unchanged.
- Failed poll keeps prior blocks (the shipped empty-catch behavior carries over verbatim).

- [ ] **Step 5: Update the render tests**

`chauffeur/tests/test_packing_card_render.py` (jsdom, same harness):

- `scenario_the_card_draws_both_outings_as_one_row_each` → becomes `scenario_a_two_event_outing_is_a_container_with_inner_lines`: fixture with one 2-event outing block and one home block; assert the container renders both inner compact lines (titles + times present), the home block renders as a flat row, and NO items are in the DOM before any tap.
- New `scenario_the_pill_has_two_states_and_only_two`: a block with work remaining shows `2 to pack`; a done block shows the muted done mark and no amber class; a no-cargo block shows neither.
- New `scenario_a_household_kit_survives_the_member_filter`: mount config `members: ['ellie']`; fixture groups: one with `people: ['sam']` (hidden), one with `people: []` (shown).
- `scenario_interactive_draws_the_claim_controls_as_real_buttons` / `scenario_interactive_false_draws_no_claim_buttons_at_all` — retarget to the expanded state (expand first, then assert), keep the absence-not-visibility assertion and the drawn-posts-nothing assertion.
- `scenario_a_failed_poll_after_success_keeps_the_rows_standing` — retarget field name to `blocks`, otherwise identical.

- [ ] **Step 6: Run all of it, tailwind, then the board suites**

```bash
python tools/build_tailwind.py
python tests/test_packing_card_builder.py
python tests/test_packing_card_render.py
python tests/test_home_board.py
python tests/test_builtin_boards.py
python tests/test_board_instances.py
```
Expected: PASS.

- [ ] **Step 7: Sweep, bump, commit**

Commit subject: `The packing card becomes the family's day (vX.Y.Z)` — body names the two inverted scenarios and the blank-install change.

---

### Task 4: Prove the reshape on a real wall

**Files:**
- Test: `chauffeur/tests/test_packing_card.py` (update + extend)

The playwright layer re-proves what the reshape could have broken, on the shipped harness (`tests/test_board_card_grid.py` pattern; keep the skip-when-absent guards and report whether chromium actually ran).

- [ ] **Step 1: Update and extend the scenarios**

- `scenario_a_ten_activity_saturday_stays_readable` → ten blocks including one 3-event container and two home blocks: assert one top-level row per block, inner lines visible inside the container, nothing auto-expanded, no horizontal overflow.
- `scenario_tapping_plus_moves_the_item_and_the_outing_fraction` → expand a block first (tap), then tick; assert the item count, the block's pill (amber `N to pack` decrements, flips to done-state at zero remaining).
- `scenario_a_poll_racing_a_claim_does_not_reset_the_tick` — unchanged intent; fixture becomes blocks; ALSO assert the poll does not collapse an expanded block (`expandedKeys` survival is new surface).
- `scenario_a_failed_claims_reconcile_adopts_the_server_count` — field rename only.
- `scenario_an_item_at_needed_cannot_be_pushed_past_it` — unchanged intent.
- New `scenario_expanding_one_block_leaves_the_others_at_rest`: tap one container; assert its items are in the DOM and the sibling block still shows no items.

- [ ] **Step 2: Run, fix the card where a scenario exposes a real bug, watch it pass**

Run: `python tests/test_packing_card.py` (rebuild tailwind if the template changes).

- [ ] **Step 3: Sweep, bump, commit**

Commit subject: `The family day card holds up under fingers and polls (vX.Y.Z)`.

---

### Task 5: The board swap

**Files:**
- Modify: `chauffeur/services/builtin_boards.json` (the `"home"` board)
- Test: `chauffeur/tests/test_builtin_boards.py`, `chauffeur/tests/test_home_board.py` (whatever pins the home board's widget list — update expectations, disclosed)

- [ ] **Step 1: Edit the default home board**

In `builtin_boards.json`'s `"home"` widgets (`builtin_boards.json:9-107`): remove the `{"id": "calendar", ...}` and `{"id": "drives", ...}` entries; add `{"id": "family_day", "type": "packing", "config": {}}` in the position `calendar` held. Give `family_day` the span `calendar` had (check the board's `spans` map; if `drives` had its own span entry, delete it). `hero`, `kids`, and the rest stay untouched. The `calendar` and `drives` catalog entries are NOT touched — both stay placeable; the swap is configuration, and anyone can revert it in board edit mode (the design's living-with-it trial).

- [ ] **Step 2: Run the board suites, fix pinned expectations**

```bash
python tests/test_builtin_boards.py
python tests/test_home_board.py
python tests/test_board_instances.py
```
Any scenario pinning the home board's widget list updates to the new list — each named in the commit body. If the blank-install sweep from Task 3 asserted `{'calendar', 'packing'}`, it now asserts `{'packing'}` plus whatever core tiles the sweep already allowed (`calendar` left the default board; the card catalog still carries it).

- [ ] **Step 3: Sweep, tailwind (if any template moved), bump, commit**

Commit subject: `The home board leads with the family's day (vX.Y.Z)`.

---

### Task 6: Say what changed

**Files:**
- Modify: `chauffeur/system_capabilities.md`
- Modify: `chauffeur/docs/family_day_design.md` (stamp F1 shipped)
- Modify: `chauffeur/docs/packing_design.md` (one pointer line)

- [ ] **Step 1: Capabilities entry**

Rewrite the packing-card section of `system_capabilities.md` as the Family Day card, in that document's voice: the block spine and what feeds it (outings from assignments; home and covered blocks from the same stamped event feed the calendar reads; all-day as banner, never solver-visible); the container rule (≥2 events); the two-state pill; the three rule flips and why each shipped decision inverted; the server cap at `needed`; the board swap and its revert path. Add one sentence recording the known key-churn gap: a midday re-solve that changes an outing's first event changes its key and orphans that outing's claims for the day (accepted, watched, P3+ may re-key).

- [ ] **Step 2: Stamp the design docs**

`family_day_design.md`: under **F1 — the reshape**, add `Shipped vX.Y.Z–vX.Y.Z.` with the actual range. `packing_design.md`: under the P2 slice's shipped line, add: *"The tile later became the Family Day card — `docs/family_day_design.md`."*

- [ ] **Step 3: Full sweep, bump, commit, push**

This is the plan's final commit: push the whole branch of work.

- [ ] **Step 4: Deploy and look at it**

Add-on store → *Check for updates* → rebuild → confirm the version (user's act). The acceptance look: a day with a two-event trip shows one container with two inner lines and one amber pill; an at-home event with a matching kit sits in the same list; the old calendar and drives cards are gone from the home board but present in the catalog.

---

## Self-review

**Spec coverage.** Block spine + atoms/container/covered/banner → Tasks 1, 3. Agenda-at-rest presentation, pill, tap-expand, no auto-expand → Tasks 3, 4. Rule flips 1–4 → Tasks 1 (covered, turnover), 2 (no-cargo draws, endpoint), 3 (no-kits draws). Server cap (parked finding) → Task 2. Member-filter fix (parked finding) → Task 3. Board swap + revert → Task 5. Docs + key-churn sentence (parked debt) → Task 6. F2 (meals) deliberately absent — designed for, not built.

**Disclosed test moves/inversions** (the Task 6 lesson, applied): Task 2 removes three `test_outings.py` turnover scenarios whose meaning moved to `test_family_day.py`; Task 3 inverts the no-kits builder scenario and rewrites the quiet-day sentence; Task 3/5 update the blank-install sweep in two disclosed steps. Every one is named in its task and its commit body.

**Names.** `blocks_for`, `day_in_focus` (family_day), `home:<event_id>`, `expandedKeys`, catalog key `packing` (unchanged — placements survive), label `Family day`. Spelled the same in every task that touches them.

**Known gaps, deliberate:** canceled blocks draw from the stamped `canceled` field; feed-detected cancellations already stamp it (`services/cancellations.py`), so no new detection here. Per-driver grouping, idle auto-fold, and tomorrow-early remain the design's open questions — none built.

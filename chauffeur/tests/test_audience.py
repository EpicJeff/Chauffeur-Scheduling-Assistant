"""Audience enforcement on trips and occasions (family-network arc S4).

The Disney case, end to end: a trip being planned defaults to a CLOSED
audience, the wall panel is a place rather than a person and so never shows
it, and the absence is legible to exactly the people allowed to know — a
counter for a permitted viewer, no trace at all for anyone else (§7, §13 of
docs/family_network_design.md). Occasions ride the same rules, and the agent
answers a kid asking about a surprise party exactly as it would about a
party that does not exist.

Run from chauffeur/:  python tests/test_audience.py
"""
import datetime

from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)

from services import home_board, storage

PARENT = {'id': 'p', 'role': 'parent'}
CHILD = {'id': 'c', 'role': 'child'}
# The §13 combination: reach grants trips, audience still withholds — this is
# the one viewer who gets the "N trips not shown here" counter.
GRANTED_ADULT = {'id': 'a', 'role': 'adult',
                 'scope': {'overrides': {'trips.gallery': 'all'}}}

NOW = datetime.datetime.now()
TODAY = datetime.date.today()


def _mock_trips(meta_by_id):
    """One upcoming snapshot trip per metadata entry, ids t1, t2, …"""
    storage.get_cached_trips = lambda: {'trips': [
        {'id': tid, 'title': tid.upper(),
         'start': (TODAY + datetime.timedelta(days=10)).isoformat(),
         'end': (TODAY + datetime.timedelta(days=14)).isoformat()}
        for tid in meta_by_id]}
    storage.get_all_trip_metadata = lambda: []
    storage.get_cached_schedule = lambda: {}
    storage.get_trip_metadata = lambda tid: meta_by_id.get(tid)


_ORIG = (storage.get_cached_trips, storage.get_all_trip_metadata,
         storage.get_cached_schedule, storage.get_trip_metadata)


def _restore():
    (storage.get_cached_trips, storage.get_all_trip_metadata,
     storage.get_cached_schedule, storage.get_trip_metadata) = _ORIG


def scenario_a_planned_trip_never_reaches_the_wall():
    try:
        # t1 is being planned (metadata, no declared audience): CLOSED.
        # t2 has no metadata record at all: it exists only as calendar events
        # everyone already sees, so hiding its tile would be theatre.
        _mock_trips({'t1': {'pois': []}, 't2': None})
        tile = home_board._tile_trips(NOW)                    # the panel
        titles = [t['title'] for t in tile['trips']]
        check(titles == ['T2'], f"the planned trip leaked to the panel: {titles}")
        check('hidden' not in tile,
              "the panel gets NO trace — not even a count (a place, not a person)")
    finally:
        _restore()


def scenario_marking_for_the_wall_is_one_field():
    try:
        _mock_trips({'t1': {'audience': 'household'}})
        tile = home_board._tile_trips(NOW)
        check([t['title'] for t in tile['trips']] == ['T1'],
              "a trip marked for the wall appears on it")
    finally:
        _restore()


def scenario_the_counter_goes_to_exactly_who_may_know():
    try:
        _mock_trips({'t1': {'pois': []}, 't2': None})
        for_parent = home_board._tile_trips(NOW, viewer=PARENT)
        check([t['title'] for t in for_parent['trips']] == ['T1', 'T2']
              or set(t['title'] for t in for_parent['trips']) == {'T1', 'T2'},
              "parents see the surprise they are planning")
        for_granted = home_board._tile_trips(NOW, viewer=GRANTED_ADULT)
        check([t['title'] for t in for_granted['trips']] == ['T2'],
              "a facet grant is not an audience grant — both doors must agree")
        check(for_granted.get('hidden') == 1,
              "…and the absence is LEGIBLE to a viewer whose scope permits trips")
        for_child = home_board._tile_trips(NOW, viewer=CHILD)
        check('hidden' not in for_child,
              "a child gets no trace at all, not even a count")
    finally:
        _restore()


def scenario_sharing_reveals_to_that_child_only():
    try:
        _mock_trips({'t1': {'audience': 'shared', 'shared_with': ['c']}})
        seen = home_board._tile_trips(NOW, viewer=CHILD)
        check([t['title'] for t in seen['trips']] == ['T1'],
              "sharing with one child reveals it to that child")
        other = home_board._tile_trips(NOW, viewer={'id': 'c2', 'role': 'child'})
        check(not other.get('trips'),
              "…and to nobody else")
    finally:
        _restore()


def scenario_occasions_ride_the_same_rules():
    real = storage.get_occasions
    try:
        anchor = (TODAY + datetime.timedelta(days=12)).isoformat()
        storage.get_occasions = lambda include_done=False: [
            {'id': 'o1', 'title': "Ellie's surprise 8th", 'kind': 'birthday',
             'anchor_date': anchor},
            {'id': 'o2', 'title': 'Thanksgiving', 'kind': 'thanksgiving',
             'anchor_date': anchor, 'audience': 'household'},
        ]
        tile = home_board._tile_occasions(NOW)                # the panel
        titles = [o['title'] for o in tile['occasions']]
        check(titles == ['Thanksgiving'],
              f"a party being planned is a surprise by default: {titles}")
        check('hidden' not in tile, "the panel gets no count")
        for_parent = home_board._tile_occasions(NOW, viewer=PARENT)
        check(len(for_parent['occasions']) == 2, "parents see both")
    finally:
        storage.get_occasions = real


def scenario_argyle_keeps_the_secret():
    from services import agent_tools_v2 as atv2, occasions as occ
    storage.members_table.truncate()
    storage.occasions_table.truncate()
    storage.add_member({"id": "mom", "name": "Mom", "role": "parent"})
    storage.add_member({"id": "kid", "name": "Jack", "role": "child"})
    rec = occ.create("Jack's surprise party",
                     (TODAY + datetime.timedelta(days=9)).isoformat(), 'party')

    kid_view = atv2.get_occasion("surprise", acting_member=storage.get_member("kid"))
    check("don't have any occasions" in kid_view['message'],
          "a surprise the kid asks Argyle about is a party that does not exist")
    mom_view = atv2.get_occasion("surprise", acting_member=storage.get_member("mom"))
    check("surprise party" in mom_view['message'],
          "the parent planning it gets a real answer")

    storage.update_occasion(rec['id'], {'audience': 'household'})
    kid_after = atv2.get_occasion("surprise", acting_member=storage.get_member("kid"))
    check("surprise party" in kid_after['message'],
          "marked for the household, the same question gets the real answer")


SCENARIOS = [
    scenario_a_planned_trip_never_reaches_the_wall,
    scenario_marking_for_the_wall_is_one_field,
    scenario_the_counter_goes_to_exactly_who_may_know,
    scenario_sharing_reveals_to_that_child_only,
    scenario_occasions_ride_the_same_rules,
    scenario_argyle_keeps_the_secret,
]

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

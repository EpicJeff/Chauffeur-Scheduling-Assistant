"""Near stops are one outing (2026-11-02).

Spec: docs/superpowers/specs/2026-11-02-errands-near-stops-design.md.

Errands whose places are within the household setting errand_near_mins of
each other (default 5, drive time, transitive) form a cluster, for anyone,
whatever their kinds. A cluster batches as a together kind does: the
constrained errand is placed first and the others chain beside it on the
route with the one-outing bonus. Kind batching (per person) and clusters
merge into one batch group. The why says 'next to the Kroger run'.

Grid world from tests/test_errand_routing.py, extended with Bakery (11,10),
one minute from Store, and Deli (16,10), six from Store and five from Bakery.
Run from chauffeur/:  python tests/test_errand_near.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_errand_routing import (  # noqa: E402  (installs the grid legs on matcher)
    DAYS, GRID, SETTINGS, _driver, _errand, _only, _place, _world, check)
from test_errand_dedicated_gap import _ride, _t  # noqa: E402
from test_errand_habits import _habits  # noqa: E402
from models.schemas import Settings  # noqa: E402
from services import errand_prefs, settings_registry  # noqa: E402
from solver import matcher  # noqa: E402

GRID['Bakery'] = (11, 10)
GRID['Deli'] = (16, 10)
OFF = {**SETTINGS, 'errand_near_mins': 0}


def _kroger():
    return _errand(id='erA', doc_id=2, title='Kroger run', location='Store', valid_days_of_week=[5])


def _prescription(location='Bakery', **over):
    base = dict(id='erB', doc_id=3, title='Prescription', kind='pharmacy', location=location, priority=1)
    base.update(over)
    return _errand(**base)


def scenario_near_stops_are_one_outing_for_anyone():
    lorena = _driver('d2', 'Lorena')
    base = _world({}, [], {})
    _habits({})
    # Off: the free pharmacy pickup (priority 1) goes first and lands Monday
    # from home; the Kroger run lands Saturday. Two outings, no words.
    rows, notes = _place(base, [_kroger(), _prescription()], [lorena], settings=OFF)
    da, ra = _only(rows, 'erA')
    db, rb = _only(rows, 'erB')
    check(db == DAYS[0] and _t(rb) == '09:00' and da == DAYS[5] and 'near' not in rb['why'] and 'next to' not in rb['why']['text'],
          f"off is the shipped answer: B {db} {_t(rb)} {rb['why']}, A {da}")
    # Default (5): Bakery is one minute from Store. The Kroger run anchors
    # (Saturdays only is the tighter one) and the pickup chains beside it.
    rows, notes = _place(base, [_kroger(), _prescription()], [lorena])
    da, ra = _only(rows, 'erA')
    db, rb = _only(rows, 'erB')
    check(da == DAYS[5] and _t(ra) == '10:00' and ra['why']['kind'] == 'from_home'
          and 'near' not in ra['why'] and 'together' not in ra['why'], f"the anchor on its own merits: {da} {_t(ra)} {ra['why']}")
    check(db == DAYS[5] and rb['why'].get('near') == 'Kroger run' and 'together' not in rb['why'],
          f"beside the near sibling, said as near: {db} {rb['why']}")
    check('erA' in (rb['inserted_after_event_id'], rb['inserted_before_event_id']) and rb['why']['detour_mins'] == 2,
          f"on the route beside it, a two-minute detour: {rb}")
    check(rb['why']['text'].endswith(', next to the Kroger run') and '+2 min' in rb['why']['text'], f"{rb['why']['text']}")
    check(notes == {}, f"{notes}")


def scenario_the_threshold_is_the_setting():
    lorena = _driver('d2', 'Lorena')
    base = _world({}, [], {})
    _habits({})
    # Deli is six minutes from Store: not near at the default, near at 6.
    rows, _ = _place(base, [_kroger(), _prescription('Deli')], [lorena])
    db, rb = _only(rows, 'erB')
    check(db == DAYS[0] and 'near' not in rb['why'], f"six is past five: {db} {rb['why']}")
    rows, _ = _place(base, [_kroger(), _prescription('Deli')], [lorena], settings={**SETTINGS, 'errand_near_mins': 6})
    db, rb = _only(rows, 'erB')
    check(db == DAYS[5] and rb['why'].get('near') == 'Kroger run', f"six at six: {db} {rb['why']}")


def scenario_near_is_transitive():
    lorena = _driver('d2', 'Lorena')
    _habits({})
    # Deli is six from Store (not near) but five from Bakery (near): one
    # cluster of three. All land Saturday; each chained one has a near sibling.
    c = _errand(id='erC', doc_id=4, title='Dry cleaning', kind='pickup', location='Deli', priority=1)
    rows, notes = _place(_world({}, [], {}), [_kroger(), _prescription(), c], [lorena])
    days = {eid: _only(rows, eid)[0] for eid in ('erA', 'erB', 'erC')}
    check(all(d == DAYS[5] for d in days.values()), f"one outing: {days}")
    whys = {eid: _only(rows, eid)[1]['why'] for eid in ('erB', 'erC')}
    check(all(w.get('near') in ('Kroger run', 'Prescription', 'Dry cleaning') for w in whys.values()), f"{whys}")
    check(notes == {}, f"{notes}")


def scenario_near_never_crosses_a_trip_home():
    # The Kroger run is Saturday morning, home-bound. Lily's Saturday soccer
    # gives Lorena a drive home at 17:19 past the Bakery (Soccer (20,0) to
    # Bakery (11,10) is 19 on the grid). The pickup's window
    # opens at 17:00: its only Saturday candidate is that drive home, which is
    # not the Kroger outing. No near words, plain detour.
    lorena = _driver('d2', 'Lorena')
    drop, pick = _ride('soccer', 5, 16, 0, 'Soccer', 'Soccer', 60, 'lily_cal')
    base = _world({5: [drop, pick]}, [], {'soccer_dropoff': 'd2', 'soccer_pickup': 'd2'})
    _habits({})
    a = dict(_kroger(), time_window_start='09:00', time_window_end='12:00', home_bound=True)
    b = _prescription(time_window_start='17:00', time_window_end='20:00')
    rows, notes = _place(base, [a, b], [lorena])
    da, ra = _only(rows, 'erA')
    db, rb = _only(rows, 'erB')
    check(da == DAYS[5] and _t(ra) == '09:00', f"{da} {_t(ra)}")
    check(db == DAYS[5] and _t(rb) == '17:19' and 'near' not in rb['why'] and 'next to' not in rb['why']['text'],
          f"the same outing only: {_t(rb)} {rb['why']}")


def scenario_kinds_and_clusters_merge_into_one_group():
    lorena = _driver('d2', 'Lorena')
    # Lorena batches groceries. Kroger run (Store, Saturdays), Costco run
    # (Shop, far, groceries, priority 1), Prescription (Bakery, near Store).
    # One group of three: the Kroger run anchors, Costco chains as a kind
    # sibling ('with the'), the prescription as a near one ('next to the').
    _habits({'d2': {'together_kinds': ['groceries']}})
    a = _kroger()
    b = _errand(id='erB', doc_id=3, title='Costco run', location='Shop', priority=1)
    c = _prescription(**{'id': 'erC', 'doc_id': 4})
    rows, notes = _place(_world({}, [], {}), [a, b, c], [lorena])
    da, ra = _only(rows, 'erA')
    db, rb = _only(rows, 'erB')
    dc, rc = _only(rows, 'erC')
    check(da == DAYS[5] and db == DAYS[5] and dc == DAYS[5], f"one outing: {da} {db} {dc}")
    check(rb['why'].get('together') == 'Kroger run' and 'near' not in rb['why'] and ', with the Kroger run' in rb['why']['text'],
          f"the kind sibling: {rb['why']}")
    check(rc['why'].get('near') in ('Kroger run', 'Costco run') and 'together' not in rc['why'] and ', next to the ' in rc['why']['text'],
          f"the near sibling: {rc['why']}")
    check(notes == {}, f"{notes}")
    # Without the habit the far Costco run keeps the shipped order (Monday),
    # the near pair still batches.
    _habits({})
    rows, notes = _place(_world({}, [], {}), [a, b, c], [lorena])
    db, rb = _only(rows, 'erB')
    dc, rc = _only(rows, 'erC')
    check(db == DAYS[0] and 'together' not in rb['why'] and 'near' not in rb['why'], f"{db} {rb['why']}")
    check(dc == DAYS[5] and rc['why'].get('near') == 'Kroger run', f"{dc} {rc['why']}")


def scenario_the_cluster_primer_runs_once_with_every_place():
    lorena = _driver('d2', 'Lorena')
    _habits({})
    seen = []
    real = matcher._prime_errand_cluster_pairs

    def spy(places, *args, **kw):
        seen.append(sorted(places))
        return 0
    matcher._prime_errand_cluster_pairs = spy
    try:
        off_grid = _errand(id='erC', doc_id=4, title='Tailor', location='Nowhere', priority=1)
        rows, notes = _place(_world({}, [], {}), [_kroger(), _prescription(), off_grid], [lorena])
    finally:
        matcher._prime_errand_cluster_pairs = real
    check(seen == [['Bakery', 'Nowhere', 'Store']], f"once, every distinct place: {seen}")
    # The off-grid place is unknown to every pair: not near, and the pass
    # still places the near pair as one outing.
    db, rb = _only(rows, 'erB')
    check(db == DAYS[5] and rb['why'].get('near') == 'Kroger run', f"{db} {rb['why']}")
    check(notes.get('erC', {}).get('reason') in ('unknown_travel', None) and all(r['id'] != 'erC' or 'near' not in r['why'] for _, r in rows),
          f"an unknown place is never near: {notes} {[r for _, r in rows if r['id'] == 'erC']}")
    # The real primer buys nothing when the grid knows every pair, and never
    # raises when a place is unknown.
    from services import maps
    calls = []
    orig = maps.prime_matrix_cache
    maps.prime_matrix_cache = lambda locations, ignore_age=False: calls.append(sorted(locations))
    try:
        from services import storage
        n = matcher._prime_errand_cluster_pairs(['Store', 'Bakery'], storage, maps)
        check(n == 0 and calls == [], f"nothing to buy: {n} {calls}")
        n = matcher._prime_errand_cluster_pairs(['Store', 'Nowhere'], storage, maps)
        check(n == 1 and calls == [['Nowhere', 'Store']], f"one purchase for the unknown pair: {n} {calls}")
    finally:
        maps.prime_matrix_cache = orig


def scenario_the_setting_has_its_home():
    check(Settings().errand_near_mins == 5, "model default 5")
    entry = next((e for e in settings_registry.ENTRIES if e['key'] == 'errand_near_mins'), None)
    check(entry and entry['page'].startswith('errands') and entry['anchor'] == 'errand-settings',
          f"registered on the Errands drawer: {entry}")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    page = open(os.path.join(root, 'templates', 'errands.html'), encoding='utf-8').read()
    check('errand_near_mins' in page and 'errand-near-mins' in page, "the drawer carries the input")
    card = open(os.path.join(root, 'templates', 'components', 'errand_habits.html'), encoding='utf-8').read()
    check('each kind its own outing' in card, "the card says per kind")


def scenario_words():
    why = {'kind': 'on_the_way', 'driver_name': 'Lorena', 'detour_mins': 2, 'leg': {'from': 'Home', 'to': 'Kroger run'},
           'near': 'Kroger run'}
    check(matcher.errand_why_text(why) == "on Lorena's way to Kroger run, +2 min, next to the Kroger run", matcher.errand_why_text(why))
    both = dict(why, together='Kroger run')
    text = matcher.errand_why_text(both)
    check(text.endswith(', with the Kroger run') and 'next to' not in text, text)
    check(errand_prefs.describe_habits('Lorena', {'together_kinds': ['groceries']}) == ['Lorena does groceries in one outing'],
          errand_prefs.describe_habits('Lorena', {'together_kinds': ['groceries']}))
    check(errand_prefs.describe_habits('Lorena', {'together_kinds': ['groceries', 'pharmacy']})
          == ['Lorena does groceries and pharmacy runs each in one outing'],
          errand_prefs.describe_habits('Lorena', {'together_kinds': ['groceries', 'pharmacy']}))


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('scenario_'):
            print(name)
            fn()
    print("errand-near scenarios passed")

"""The record-kind registry (Projects core spec §1, Task 1).

`services/subjects.py` keeps its public functions but their per-kind branches
move behind one adapter shape, `subjects.ADAPTERS[kind] = Adapter(...)`. The
eight existing kinds behave exactly as before (the slice 1 subject tests run
unchanged as the proof); a new kind joins by registering one adapter and
nothing else.

Run from chauffeur/:  python tests/test_subject_registry.py
"""
from harness import check  # noqa: F401
from services import subjects
from test_subjects import _fresh as _fresh_subjects, MOM, KID

EIGHT = ('trip', 'occasion', 'event', 'member', 'contact', 'thread', 'program', 'list')
LINKS = {'trip': 'trip?event_id=X', 'occasion': 'occasions', 'event': 'app', 'member': 'app',
         'contact': 'drive_setup', 'thread': 'threads', 'program': 'programs', 'list': 'shopping'}


def scenario_the_eight_kinds_are_adapters_in_their_old_order():
    check(tuple(subjects.KINDS[:8]) == EIGHT, f"the same kinds in the same order: {subjects.KINDS}")
    for kind in EIGHT:
        ad = subjects.ADAPTERS.get(kind)
        check(isinstance(ad, subjects.Adapter), f"{kind} is an Adapter: {ad!r}")
        check(subjects.link(kind, 'X') == LINKS[kind], f"{kind} links as before: {subjects.link(kind, 'X')}")
    check(subjects.link('nonsense', 'X') == 'app', "an unknown kind still links to the app")
    check(list(subjects.facets('trip')) == list(subjects.FACETS['trip']), "facets read through the registry")


def scenario_existing_records_read_as_before():
    _fresh_subjects()
    occ = subjects.load('occasion', 'o1')
    check(occ and subjects.title_of('occasion', occ) == "Kate's 10th birthday", f"an occasion loads: {occ}")
    check(subjects.visible('occasion', occ, MOM) and not subjects.visible('occasion', occ, KID),
          "a parents-default occasion: a parent yes, a child no")
    check(subjects.context('occasion', 'o1', KID) is None and 'OCCASION' in (subjects.context('occasion', 'o1', MOM) or ''),
          "context only after the viewer is authorised")
    trip = subjects.load('trip', 'ev_disney')
    check(trip and subjects.spoken_safe('trip', trip) is False, "a trip with no audience is never spoken")
    found = subjects.find('trip', 'Disney World', MOM)
    check(found and found[0]['id'] == 'ev_disney', f"find works through the registry: {found}")


def scenario_a_new_kind_joins_by_registering_one_adapter():
    _fresh_subjects()
    rows = [{'id': 'w1', 'title': 'Widget plan'}]
    ad = subjects.Adapter(
        rows=lambda: rows,
        title=lambda row: row['title'],
        visible=lambda row, viewer: (viewer or {}).get('id') == 'mom',
        closed=lambda row: False,
        link=lambda sid: f'widgets?id={sid}',
        context=lambda row, viewer, spoken, facet: f"WIDGET: {row['title']}" + (f" ({facet})" if facet else ''),
        facets=['parts'],
    )
    subjects.register('widget', ad)
    try:
        check('widget' in subjects.KINDS, f"KINDS follows the registry: {subjects.KINDS}")
        row = subjects.load('widget', 'w1')
        check(row == rows[0] and subjects.title_of('widget', row) == 'Widget plan', "load and title")
        check(subjects.visible('widget', row, MOM) and not subjects.visible('widget', row, KID), "its own visibility")
        check(subjects.visible('widget', row, MOM, spoken=True) is False,
              "a kind that says nothing about speakers is never spoken (the safe default)")
        check(subjects.link('widget', 'w1') == 'widgets?id=w1', "its own link")
        check(subjects.context('widget', 'w1', MOM) == 'WIDGET: Widget plan', "its own context")
        check(subjects.context('widget', 'w1', MOM, facet='parts') == 'WIDGET: Widget plan (parts)', "with a facet it declares")
        check(subjects.context('widget', 'w1', KID) is None, "never past its visibility")
        check(list(subjects.facets('widget')) == ['parts'], "its facets")
        hit = subjects.find('widget', 'Widget plan', MOM)
        check(hit and hit[0]['id'] == 'w1', f"find reaches it: {hit}")
        top, _ = subjects.resolve('Widget plan', MOM)
        check(top and top['kind'] == 'widget', f"resolve reaches it: {top}")
    finally:
        subjects.unregister('widget')
    check('widget' not in subjects.KINDS and subjects.load('widget', 'w1') is None, "unregistering removes it cleanly")


SCENARIOS = [
    scenario_the_eight_kinds_are_adapters_in_their_old_order,
    scenario_existing_records_read_as_before,
    scenario_a_new_kind_joins_by_registering_one_adapter,
]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)

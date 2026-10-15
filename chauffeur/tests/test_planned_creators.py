"""Tools that create a trip and a list (planned missions spec §3, Trips and
Lists rows). Nothing could create either as a tool: trips are made on the
Trips page and lists on the Lists page. Each tool shares its page's code so a
mission-made trip or list is the same thing a person makes by hand.

Pinned here (Task 4):
  * `create_trip(title, location, start_date, end_date, travelers, idem)`:
    a draft trip through the same function the Trips page's
    `POST /api/trips/create` uses; returns `created: [{'kind': 'trip', 'id'}]`
    and `trip_id`; the same `idem` twice → one trip;
  * `create_list(name, audience, shared_with, idem)`: a list through the same
    function `POST /api/shopping/lists` uses, the same private-audience rules
    (the approver is added to a private list's people; a private list with
    nobody on it is refused; the default list is never private); returns
    `created: [{'kind': 'list', 'id'}]`; the same `idem` twice → one list;
  * both are registry writes declared to chat, proposable, never READ tools.

Run from chauffeur/:  python tests/test_planned_creators.py
"""
from harness import check  # noqa: F401
from services import storage, scope, missions
from services import agent_tools_v2 as tools
from test_subjects import _reset, _seed, MOM, DAD, KID


def _fresh():
    _reset()
    _seed()


def scenario_create_trip_makes_a_page_shaped_draft_once():
    _fresh()
    before = {m['event_id'] for m in storage.get_all_trip_metadata()}
    out = tools.execute_tool('create_trip', {'title': 'Disney World', 'location': 'Orlando, FL', 'start_date': '2027-01-15',
                                             'end_date': '2027-01-20', 'travelers': 4, 'idem': 'k1'}, actor=dict(MOM))
    check(out.get('status') == 'success' and out.get('trip_id'), f"made: {out}")
    tid = out['trip_id']
    check(out.get('created') == [{'kind': 'trip', 'id': tid}], f"says what it created: {out}")
    meta = storage.get_trip_metadata(tid)
    check(meta and meta.get('is_draft') and meta.get('title') == 'Disney World' and meta.get('location') == 'Orlando, FL'
          and meta.get('travelers') == 4, f"a draft trip like the page makes: {meta}")
    import datetime
    check(datetime.datetime.utcfromtimestamp(meta['mock_start_date']).date().isoformat() == '2027-01-15', "its start date")
    again = tools.execute_tool('create_trip', {'title': 'Disney World', 'location': 'Orlando, FL', 'start_date': '2027-01-15',
                                               'end_date': '2027-01-20', 'travelers': 4, 'idem': 'k1'}, actor=dict(MOM))
    check(again.get('trip_id') == tid, f"the same key returns the same trip: {again}")
    made = {m['event_id'] for m in storage.get_all_trip_metadata()} - before
    check(made == {tid}, f"exactly one trip made: {made}")
    kid = tools.execute_tool('create_trip', {'title': 'Kate trip', 'idem': 'k9'}, actor=dict(KID))
    check(kid.get('status') == 'error', f"a child asking through chat cannot create a trip: {kid}")
    import main
    from models.schemas import CreateTripRequest
    page = main.create_trip_api(CreateTripRequest(title='By hand', location='Maui', start_date='2027-06-01', end_date='2027-06-08'))
    by_hand = storage.get_trip_metadata(page['event_id'])
    check(set(by_hand) - {'idem'} == set(meta) - {'idem'}, f"the page and the tool make the same shape:\n{sorted(by_hand)}\n{sorted(meta)}")


def scenario_create_list_follows_the_lists_page_rules():
    _fresh()
    out = tools.execute_tool('create_list', {'name': 'Piano', 'idem': 'l-1'}, actor=dict(MOM))
    check(out.get('status') == 'success' and out.get('created') == [{'kind': 'list', 'id': out.get('list_id')}], f"made: {out}")
    lst = storage.get_shopping_list(out['list_id'])
    check(lst and lst['name'] == 'Piano' and (lst.get('audience') or 'household') == 'household', f"a household list: {lst}")
    again = tools.execute_tool('create_list', {'name': 'Piano', 'idem': 'l-1'}, actor=dict(MOM))
    check(again.get('list_id') == out['list_id'] and len([l for l in storage.get_shopping_lists() if l['name'] == 'Piano']) == 1,
          "the same key returns the same list")
    priv = tools.execute_tool('create_list', {'name': 'Surprise', 'audience': 'private', 'shared_with': ['dad'], 'idem': 'l-2'},
                              actor=dict(MOM))
    row = storage.get_shopping_list(priv['list_id'])
    check(row['audience'] == 'private' and set(row['shared_with']) == {'mom', 'dad'},
          f"the approver is added to a private list's people, as on the page: {row}")
    check(not scope.audience_allows(row, 'shopping_list', KID), "the child cannot see it")
    nobody = tools.execute_tool('create_list', {'name': 'Ghost', 'audience': 'private', 'shared_with': [], 'idem': 'l-3'}, actor=None)
    check(nobody.get('status') == 'error', f"a private list with nobody on it is refused: {nobody}")


def scenario_both_are_proposable_writes_declared_to_chat():
    declared = {t['name'] for t in tools.get_available_tools()}
    for name in ('create_trip', 'create_list'):
        check(name in declared and name in tools.TOOL_HANDLERS and name in tools.TOOL_SCHEMAS, f"{name} declared and registered")
        check(name in missions.proposable_tools() and name not in missions.READ_TOOLS, f"{name} is a proposable write")


SCENARIOS = [
    scenario_create_trip_makes_a_page_shaped_draft_once,
    scenario_create_list_follows_the_lists_page_rules,
    scenario_both_are_proposable_writes_declared_to_chat,
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

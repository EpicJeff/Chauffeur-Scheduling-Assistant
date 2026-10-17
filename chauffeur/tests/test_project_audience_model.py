"""Project audiences on the shared model (spec 2026-10-16-project-audiences-shared-model-design.md).

Run from chauffeur/:  python tests/test_project_audience_model.py
"""
from harness import check  # noqa: F401
from services import storage, access
from test_projects import _fresh, _make, _p
from test_subjects import MOM, DAD, AUNT, KID

HAL = {'id': 'hal', 'name': 'Hal', 'role': 'helper'}
SIB = {'id': 'sib', 'name': 'Sam', 'role': 'child', 'is_child': True}


def _seed_extra():
    for m in (HAL, SIB):
        storage.add_member(dict(m))


def _seen(project, members=(MOM, DAD, AUNT, KID, HAL, SIB)):
    project = storage.get_project(project['id'])
    return {m['id'] for m in members if _p().can_see(project, dict(m))}


def scenario_each_value():
    _fresh(); _seed_extra()
    house = _make('mom', MOM, title='Garage', audience='household')
    parents = _make('aunt', AUNT, title='Aunt plan', audience='parents')
    shared = _make('mom', MOM, title='Party', audience='shared', shared_with=['aunt'])
    private = _make('mom', MOM, title='Mine', audience='private', shared_with=['kid'])
    check(_seen(house) == {'mom', 'dad', 'aunt', 'kid', 'hal', 'sib'}, f"household: everyone {_seen(house)}")
    check(_seen(parents) == {'mom', 'dad', 'aunt'}, f"parents: the parents and the owner {_seen(parents)}")
    check(_seen(shared) == {'mom', 'dad', 'aunt'}, f"shared: parents, owner, list {_seen(shared)}")
    check(_seen(private) == {'mom', 'kid'}, f"private: exactly the list, owner added {_seen(private)}")
    for p, ok in ((house, True), (parents, False), (shared, False), (private, False)):
        check(access.project_visible(storage.get_project(p['id']), access.HOUSE) is ok, f"house reader: {p['title']}")


def scenario_child_private_defaults_and_explicit_list():
    _fresh()
    implicit = _make('kid', KID, title='Diary', audience='private')
    check(_seen(implicit) == {'kid', 'mom', 'dad'}, f"a child's private with no list: child + parents {_seen(implicit)}")
    surprise = _make('kid', KID, title='Dad surprise', audience='private', shared_with=['mom'])
    check(_seen(surprise) == {'kid', 'mom'}, f"a child's explicit list leaves Dad out {_seen(surprise)}")
    adult = _make('mom', MOM, title='Mine', audience='private')
    check(_seen(adult) == {'mom'}, "an adult's private with no list: the owner")


def scenario_normalize():
    _fresh(); _seed_extra()
    storage.update_member('hal', {'status': 'archived'})
    p = _make('mom', MOM, title='Party', audience='shared', shared_with=['aunt', 'aunt', 'ghost', 'hal'])
    check(p['shared_with'] == ['aunt'], f"filtered and de-duplicated: {p['shared_with']}")
    empty = _make('mom', MOM, title='Empty share', audience='shared', shared_with=['ghost'])
    check(empty['audience'] == 'parents' and empty['shared_with'] == [], f"empty shared becomes parents: {empty}")
    hh = _make('mom', MOM, title='House', audience='household', shared_with=['aunt'])
    check(hh['shared_with'] == [], "household clears the list")
    bad = _p().create({'title': 'x', 'goal': 'g', 'done_when': 'd', 'owner_member_id': 'mom', 'audience': 'family'}, dict(MOM))
    check(bad['status'] == 'error' and bad['message'] == 'Choose household, parents, shared or private', f"{bad}")


def scenario_body_goal_pin():
    _fresh()
    p = _make('mom', MOM, title='Reach 70 kg', audience='private')
    check(p['body_goal'] and p['shared_with'] == ['mom'], f"body goal: private to the owner {p}")
    for patch in ({'audience': 'household'}, {'audience': 'private', 'shared_with': ['mom', 'dad']}):
        res = _p().update(p['id'], patch, dict(MOM))
        check(res['status'] == 'error' and 'body goal' in res['message'], f"pin holds against {patch}: {res}")


def scenario_listed_adult_renames_but_cannot_widen():
    _fresh()
    p = _make('mom', MOM, title='Party', audience='private', shared_with=['aunt'])
    res = _p().update(p['id'], {'title': 'Party v2'}, dict(AUNT))
    check(res['status'] == 'success', f"a listed adult renames: {res}")
    for patch in ({'audience': 'household'}, {'shared_with': ['aunt', 'dad']}, {'owner_member_id': 'aunt'}):
        res = _p().update(p['id'], patch, dict(AUNT))
        check(res['status'] == 'error' and res['message'] == 'Only the owner or a parent can change who sees this project',
              f"a listed adult cannot {patch}: {res}")
    check(not _p().can_edit_audience(storage.get_project(p['id']), dict(AUNT)), "no audience edit for Aunt")
    check(_p().can_edit_audience(storage.get_project(p['id']), dict(MOM)), "the owner edits")


def scenario_two_request_escalation_refused():
    _fresh()
    p = _make('mom', MOM, title='Shared', audience='shared', shared_with=['aunt'])
    take = _p().update(p['id'], {'owner_member_id': 'aunt'}, dict(AUNT))
    widen = _p().update(p['id'], {'audience': 'household'}, dict(AUNT))
    check(take['status'] == 'error' and widen['status'] == 'error', f"no take-then-widen: {take} {widen}")
    check(storage.get_project(p['id'])['audience'] == 'shared', "still shared")


def scenario_owner_change_adds_new_owner():
    _fresh()
    p = _make('mom', MOM, title='Mine', audience='private')
    res = _p().update(p['id'], {'owner_member_id': 'dad'}, dict(MOM))
    row = storage.get_project(p['id'])
    check(res['status'] == 'success' and 'dad' in row['shared_with'], f"the new owner is listed: {row}")


def scenario_inactive_member_on_list():
    _fresh()
    p = _make('mom', MOM, title='Party', audience='private', shared_with=['aunt'])
    storage.update_member('aunt', {'status': 'disabled'})
    check('aunt' not in _seen(p, (MOM, DAD, {**AUNT, 'status': 'disabled'})), "a disabled member sees nothing")
    v = _p().view(storage.get_project(p['id']), dict(MOM))
    check(all(e['id'] != 'aunt' for e in v['shared_with']), f"a disabled member is not shown as listed: {v['shared_with']}")


def scenario_payloads():
    _fresh()
    p = _make('mom', MOM, title='Party', audience='private', shared_with=['aunt'])
    row = storage.get_project(p['id'])
    card = _p().card(row, dict(AUNT))
    check(card['can_edit_audience'] is False and card['body_goal'] is False
          and {'id': 'aunt', 'name': 'Aunt Jo'} in card['shared_with'], f"card: {card}")
    view = _p().view(row, dict(MOM))
    check(view['can_edit_audience'] is True and 'body_goal' in view, f"view: {view}")


def scenario_child_private_list_beats_parent_bypass():
    from services import threads
    _fresh()
    p = _make('kid', KID, title='Dad surprise', audience='private', shared_with=['mom'])
    tid = threads.create(title='Gift ideas', owner_member_id='kid', created_by='kid', project_id=p['id'])
    row = storage.get_thread(tid)
    check(access.record_view('thread', row, dict(DAD)) is None, "Dad, left off Kate's list, sees none of its records")
    check(access.record_view('thread', row, dict(MOM)) == access.FULL, "Mom, listed, does")
    check('dad' not in access.private_recipients('thread', row), "Dad gets no DM")


def scenario_recipients_union_and_filter():
    from services import threads
    _fresh(); _seed_extra()
    p = _make('mom', MOM, title='Mine', audience='private', shared_with=['hal'])
    tid = threads.create(title='Quotes', owner_member_id='aunt', created_by='mom', project_id=p['id'])
    got = access.private_recipients('thread', storage.get_thread(tid))
    check('aunt' in got, f"the keeper keeps their notices: {got}")
    check('hal' not in got, f"a listed helper who cannot read the thread gets nothing: {got}")
    check('mom' in got and 'dad' not in got, f"the list, not the parents: {got}")


def scenario_plan_carries_the_list():
    from services import planned
    check('shared_with' in planned.RESHAPE, "plan reshape carries the list")
    _fresh()
    shaped, err = planned._project_for_plan({'id': 'm1', 'subject_kind': None}, {
        'title': 'Party', 'goal': 'g', 'done_when': 'd', 'owner': 'mom',
        'audience': 'private', 'shared_with': ['aunt']}, dict(MOM))
    check(err is None and set((shaped or {}).get('shared_with') or []) == {'aunt', 'mom'},
          f"a proposed list survives into the approval shape: {shaped} {err}")


def scenario_patch_route_registered():
    from services import access_readers
    rows = [r for r in access_readers.READERS if r[0][1] == 'PATCH' and r[0][2] == '/api/projects/{project_id}']
    check(rows and rows[0][1] == '4.1-signed-in', f"PATCH /api/projects/{{id}} has its own row: {rows}")


if __name__ == '__main__':
    import sys
    import traceback
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith('scenario_'):
            try:
                fn()
                print('PASS', name)
            except Exception:
                failed += 1
                print('FAIL', name)
                traceback.print_exc()
    sys.exit(1 if failed else 0)

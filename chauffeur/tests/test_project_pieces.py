"""The detail page's server side (front door spec §2, slice 2, Task 1).

  * piece cards: one per piece the viewer may see, drawn by kind; missions are
    pieces too; a thread or mission card carries its situation view;
  * lanes: closed, paused, needs you (a question, a decision, a program to
    approve, a child's project with no plan), moving, waiting;
  * your work elsewhere: a keeper's missions whose project they may not see;
  * locate: where an old link lands, audience-checked;
  * creating inside a project: only into a project you may change.

Run from chauffeur/:  python tests/test_project_pieces.py
"""
from fastapi import HTTPException
from fastapi.testclient import TestClient
from unittest.mock import patch

from harness import check  # noqa: F401
from services import storage, missions, threads, auth
from test_front_door_chat import _fresh
from test_subjects import MOM, DAD, AUNT, KID
from test_subject_audience import _as


def _p():
    from services import projects
    return projects


def _bath():
    return _p().create({'title': 'Bathroom', 'goal': 'a new bathroom', 'done_when': 'tiled', 'owner_member_id': 'mom',
                        'audience': 'household'}, dict(MOM))['project']


def scenario_piece_cards_by_kind():
    _fresh()
    p = _bath()
    tid = threads.create(title='Tiler', owner_member_id='mom', goal='tile by May', created_by='mom', project_id=p['id'])
    mid = missions.launch('find three tilers', created_by='mom', project_id=p['id'])['mission_id']
    _p().add_piece(p['id'], 'list', 'l1', dict(MOM))
    cards = {c['kind']: c for c in _p().piece_cards(storage.get_project(p['id']), dict(MOM))}
    check(set(cards) == {'thread', 'mission', 'list'}, f"one card per kind: {sorted(cards)}")
    check(cards['thread']['sheet'] and cards['thread']['situation']['id'] == tid, "a thread opens in the sheet, with its situation")
    check(cards['mission']['sheet'] and cards['mission']['title'] == 'find three tilers' and cards['mission']['situation'],
          f"a mission is a piece now: {cards['mission']}")
    check(not cards['list']['sheet'] and cards['list']['link'], "a list keeps its own page")


def scenario_a_child_sees_only_their_pieces():
    _fresh()
    p = _bath()
    missions.launch('find three tilers', created_by='mom', project_id=p['id'])
    threads.create(title='Tiler', owner_member_id='mom', created_by='mom', project_id=p['id'])
    kinds = [c['kind'] for c in _p().piece_cards(storage.get_project(p['id']), dict(KID))]
    check('mission' not in kinds and 'thread' not in kinds, f"a child sees no mission or thread of the house: {kinds}")


def scenario_a_hidden_mission_is_not_a_card():
    _fresh()
    p = _bath()
    mid = missions.launch('buy the secret gift', created_by='mom', project_id=p['id'])['mission_id']
    storage.update_mission(mid, {'subject_kind': 'list', 'subject_id': 'l2', 'subject_rev': 1})   # Mom's private list
    kinds = [c['id'] for c in _p().piece_cards(storage.get_project(p['id']), dict(DAD))]
    check(mid not in kinds, "Dad never sees the mission he may not see")


def scenario_lanes():
    _fresh()
    p = _bath()
    check(_p().lane(storage.get_project(p['id']), dict(MOM)) == 'waiting', "nothing to do: waiting")
    _p().add_step(p['id'], {'title': 'Pick the tile', 'owner': 'mom'}, dict(MOM))
    check(_p().lane(storage.get_project(p['id']), dict(MOM)) == 'moving', "Mom's own next step: moving")
    check(_p().lane(storage.get_project(p['id']), dict(DAD)) == 'waiting', "for Dad it is waiting")
    _p().set_state(p['id'], 'paused', dict(MOM))
    check(_p().lane(storage.get_project(p['id']), dict(MOM)) == 'paused', "paused")
    _p().set_state(p['id'], 'done', dict(MOM))
    check(_p().lane(storage.get_project(p['id']), dict(MOM)) == 'closed', "closed")
    kid = _p().create({'title': 'Ride a bike', 'goal': 'ride', 'done_when': 'x', 'owner_member_id': 'kid'}, dict(KID))['project']
    check(_p().lane(storage.get_project(kid['id']), dict(MOM)) == 'needs_you', "a child's unplanned project needs a parent")
    check(_p().lane(storage.get_project(kid['id']), dict(KID)) == 'waiting', "the child waits for it")
    q = _bath()
    storage.add_program({'id': 'prq', 'member_id': 'mom', 'title': 'Tiling basics', 'state': 'proposed'})
    _p().adopt('program', 'prq', dict(MOM), project_id=q['id'])
    check(_p().lane(storage.get_project(q['id']), dict(MOM)) == 'needs_you', "a program to approve needs a parent")
    tid = threads.create(title='Tiler', owner_member_id='mom', created_by='mom')
    wrapper = _p().project_for('thread', tid)
    check(_p().lane(wrapper, dict(DAD)) != 'needs_you', "a thread wrapper needs no new plan from Dad")
    empty = _bath()
    check(_p().lane(storage.get_project(empty['id']), dict(DAD)) == 'waiting', "an adult's empty project is not a child's unplanned project")


def scenario_the_overview_row():
    _fresh()
    p = _bath()
    storage.add_program({'id': 'pr1', 'member_id': 'mom', 'title': 'Strength basics', 'state': 'active'})
    _p().adopt('program', 'pr1', dict(MOM), project_id=p['id'])
    import main
    rows = {r['id']: r for r in main.projects_list(request=_as('mom'))['projects']}
    row = rows[p['id']]
    check(row['lane'] == 'waiting' and row['has_program'] is True and 'card_next' in row, f"overview row: {row}")
    check(row['card_next'] != 'Needs a plan' and row['needs_plan'] is False, "a project holding a program is not empty")
    tid = threads.create(title='Tiler', owner_member_id='mom', created_by='mom')
    wrapper = _p().overview_row(_p().project_for('thread', tid), dict(DAD))
    check(wrapper['lane'] != 'needs_you' and wrapper['card_next'] != 'Needs a plan' and wrapper['needs_plan'] is False,
          f"a thread wrapper has its own work already: {wrapper}")
    kid = _p().create({'title': 'Ride a bike', 'goal': 'ride', 'done_when': 'x', 'owner_member_id': 'kid'}, dict(KID))['project']
    kid_row = _p().overview_row(storage.get_project(kid['id']), dict(MOM))
    check(kid_row['lane'] == 'needs_you' and kid_row['card_next'] == 'Needs a plan' and kid_row['needs_plan'] is True,
          f"a child's empty project still needs a plan: {kid_row}")


def scenario_overview_reuses_projections_and_skips_inactive_cards():
    _fresh()
    projects = _p()
    p = _bath()
    threads.create(title='Tiler', owner_member_id='mom', created_by='mom', project_id=p['id'])
    storage.add_program({'id': 'pr-cost', 'member_id': 'mom', 'title': 'Tiling basics', 'state': 'active'})
    projects.adopt('program', 'pr-cost', dict(MOM), project_id=p['id'])
    project = storage.get_project(p['id'])
    with patch.object(projects, 'view', wraps=projects.view) as view, \
            patch.object(projects, 'planless', wraps=projects.planless) as planless, \
            patch.object(projects, 'piece_cards', wraps=projects.piece_cards) as cards:
        row = projects.overview_row(project, dict(MOM))
        check(view.call_count == planless.call_count == cards.call_count == 1,
              f"one overview projection each: view={view.call_count}, planless={planless.call_count}, cards={cards.call_count}")
        check(row['has_program'] and not row['needs_plan'], f"the reused projection keeps its program: {row}")
    for state, expected_lane in [('paused', 'paused'), ('done', 'closed'), ('dropped', 'closed')]:
        with patch.object(projects, 'piece_cards', side_effect=AssertionError('inactive cards must not be projected')), \
                patch.object(projects, 'view', wraps=projects.view) as view, \
                patch.object(projects, 'planless', wraps=projects.planless) as planless:
            row = projects.overview_row({**project, 'state': state}, dict(MOM))
            check(row['lane'] == expected_lane and row['has_program'] and not row['needs_plan'], f"inactive overview: {row}")
            check(view.call_count == planless.call_count == 1, "inactive overview computes its view and planless once")


def scenario_http_literal_routes():
    _fresh()
    import main
    p = _bath()
    tid = threads.create(title='Tiler', owner_member_id='mom', created_by='mom', project_id=p['id'])
    headers = {'X-Member-Token': storage.create_member_token('mom')}
    settings = dict(storage.get_settings(), auth_enforce=True)
    with patch.object(storage, 'get_settings', return_value=settings):
        client = TestClient(main.app)
        check(client.get('/api/projects/elsewhere').status_code == 403, "the HTTP routes require a real member token")
        response = client.get('/api/projects/elsewhere', headers=headers)
        check(response.status_code == 200 and response.json() == {'situations': []}, f"literal elsewhere route: {response.text}")
        response = client.get(f'/api/projects/for/thread/{tid}', headers=headers)
        check(response.status_code == 200 and response.json() == {'project_id': p['id'], 'record_visible': True},
              f"literal lookup route: {response.text}")


def scenario_http_rejects_project_joins():
    _fresh()
    import main
    from services import programs_curate
    private = _p().create({'title': 'Mine', 'goal': 'x', 'done_when': 'x', 'owner_member_id': 'mom'}, dict(MOM))['project']
    headers = {'X-Member-Token': storage.create_member_token('dad')}
    settings = dict(storage.get_settings(), auth_enforce=True)
    with patch.object(storage, 'get_settings', return_value=settings), \
            patch.object(programs_curate, 'curate', side_effect=AssertionError('a denied join must not spend research')):
        client = TestClient(main.app)
        for path, body in [('/api/missions/launch', {'goal': 'find tilers', 'tier': 'flash'}),
                           ('/api/programs', {'title': 'Learn tiling'})]:
            response = client.post(path, json={**body, 'project_id': private['id']}, headers=headers)
            check(response.status_code == 403 and response.json()['detail'] == 'You cannot add to this project',
                  f"Dad cannot join Mom's private project through {path}: {response.text}")


def scenario_http_creates_program_inside_project():
    _fresh()
    import main
    from services import programs_curate
    p = _bath()
    headers = {'X-Member-Token': storage.create_member_token('mom')}
    settings = dict(storage.get_settings(), auth_enforce=True)
    with patch.object(storage, 'get_settings', return_value=settings), \
            patch.object(programs_curate, 'curate', return_value={'phases': [], 'source': {}}):
        response = TestClient(main.app).post('/api/programs', json={'title': 'Learn tiling', 'project_id': p['id']}, headers=headers)
    check(response.status_code == 200 and response.json()['status'] == 'success', f"program created over HTTP: {response.text}")
    program = storage.get_program(response.json()['id'])
    check(program['project_id'] == p['id'] and program['created_by'] == 'mom', f"the authenticated member's program joins the project: {program}")
    check(any(piece['kind'] == 'program' and piece['id'] == program['id'] for piece in storage.get_project(p['id'])['pieces']),
          "the created program is a piece of the requested project")


def scenario_your_work_elsewhere():
    _fresh()
    hidden = _p().create({'title': 'Surprise', 'goal': 'x', 'done_when': 'x', 'owner_member_id': 'mom', 'audience': 'private'}, dict(MOM))['project']
    mid = missions.launch('book the venue', created_by='aunt', project_id=hidden['id'])['mission_id']
    rows = _p().elsewhere(dict(AUNT))
    check([r['id'] for r in rows] == [mid], f"Aunt keeps her mission's row: {rows}")
    check(_p().elsewhere(dict(MOM)) == [], "Mom sees it in its project, not elsewhere")


def scenario_locate():
    _fresh()
    p = _bath()
    tid = threads.create(title='Tiler', owner_member_id='mom', created_by='mom', project_id=p['id'])
    check(_p().locate('thread', tid, dict(MOM)) == {'project_id': p['id'], 'record_visible': True}, "Mom: the project and the record")
    hidden = _p().create({'title': 'Surprise', 'goal': 'x', 'done_when': 'x', 'owner_member_id': 'mom', 'audience': 'private'}, dict(MOM))['project']
    mid = missions.launch('book the venue', created_by='aunt', project_id=hidden['id'])['mission_id']
    check(_p().locate('mission', mid, dict(AUNT)) == {'project_id': None, 'record_visible': True}, "a keeper: the record alone")
    check(_p().locate('thread', tid, dict(KID)) == {'project_id': None, 'record_visible': False}, "a child: nothing")
    check(_p().locate('thread', 'nope', dict(MOM)) == {'project_id': None, 'record_visible': False}, "a missing record: nothing")
    check(_p().locate('trip', 'x', dict(MOM)) == {'project_id': None, 'record_visible': False}, "a kind with no sheet: nothing")


def scenario_routes():
    _fresh()
    import main
    p = _bath()
    tid = threads.create(title='Tiler', owner_member_id='mom', created_by='mom', project_id=p['id'])
    check(main.projects_for_record('thread', tid, request=_as('mom'))['project_id'] == p['id'], "for route")
    check(main.project_pieces(p['id'], request=_as('mom'))['pieces'][0]['id'] == tid, "pieces route")
    check(main.projects_elsewhere(request=_as('mom')) == {'situations': []}, "elsewhere route")
    found = main.subjects_search(q='Bathroom', request=_as('mom'))['candidates']
    check(isinstance(found, list) and all(set(c) == {'kind', 'id', 'title'} for c in found), f"search answers kind, id, title only: {found}")
    check(main.subjects_search(q='  ', request=_as('mom')) == {'candidates': []}, "an empty search finds nothing")


def scenario_creating_inside_a_project():
    _fresh()
    import main
    p = _bath()
    out = main.create_thread(body={'title': 'Plumber', 'project_id': p['id']}, request=_as('mom'))
    check(storage.get_thread(out['id'])['project_id'] == p['id'], "a thread made inside the project")
    private = _p().create({'title': 'Mine', 'goal': 'x', 'done_when': 'x', 'owner_member_id': 'mom'}, dict(MOM))['project']
    try:
        main.create_thread(body={'title': 'Sneaky', 'project_id': private['id']}, request=_as('dad'))
        check(False, "Dad may not add to Mom's private project")
    except HTTPException as e:
        check(e.status_code == 403, f"refused: {e.status_code}")
    res = main.missions_launch(body={'goal': 'find three tilers', 'tier': 'flash', 'project_id': p['id']}, request=_as('mom'))
    m = storage.get_mission(res['mission_id'])
    check(m['project_id'] == p['id'] and missions.subject_of(m)[:2] == ('project', p['id']), f"launched inside it: {m}")


SCENARIOS = [scenario_piece_cards_by_kind, scenario_a_child_sees_only_their_pieces, scenario_a_hidden_mission_is_not_a_card,
             scenario_lanes, scenario_the_overview_row, scenario_your_work_elsewhere, scenario_locate, scenario_routes,
             scenario_creating_inside_a_project, scenario_overview_reuses_projections_and_skips_inactive_cards,
             scenario_http_literal_routes, scenario_http_rejects_project_joins, scenario_http_creates_program_inside_project]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            # _as replaces auth globals; restore them between scenarios so HTTP
            # scenarios authenticate real tokens regardless of scenario order.
            with patch.multiple(auth, identify=auth.identify, acting_member=auth.acting_member,
                                impersonation_refused=auth.impersonation_refused):
                fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    raise SystemExit(1 if failed else 0)

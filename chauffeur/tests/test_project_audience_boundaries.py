"""The literal household-vs-not checks that stay correct under the shared model (spec section 4):
calendar holds, spoken_safe, _sensitive, _project_in_reach, the proposed-project subject record and
_project_hold_titles. Each is exercised against a `shared` project and a child's private project
whose explicit list leaves Dad out, with a household project as the control.

Run from chauffeur/:  python tests/test_project_audience_boundaries.py
"""
import datetime

import access_fixture
from harness import check
from services import storage, projects, subjects, access, situations
from services import agent_tools_v2 as tools
import main

DAY = datetime.date(2027, 3, 8)


def _hold(project, owner, title):
    step = {'id': 'hold-' + project['id'][:8], 'title': title, 'owner': owner, 'state': 'todo', 'needs': [], 'order': 0,
            'hold': {'date': DAY.isoformat(), 'start': '17:00', 'end': '17:30'}}
    storage.update_project(project['id'], {'steps': [step]})
    return step


def _world():
    fx = access_fixture.build()
    rows = {
        'kate': (fx.projects['kate_no_dad'], 'kid', 'Kate rehearsal'),
        'shared': (fx.projects['mom_shared'], 'aunt', 'Aunt fitting'),
        'house': (fx.projects['household'], 'dad', 'Garage hour'),
    }
    steps = {key: _hold(project, owner, title) for key, (project, owner, title) in rows.items()}
    return fx, {k: v[0] for k, v in rows.items()}, steps


def _viewer(fx, col):
    return None if col == 'house' else fx.viewers[col]


def scenario_calendar_holds_say_busy_to_whoever_cannot_see_the_project():
    fx, proj, steps = _world()
    want = {
        'kate': {'mom': 'Kate rehearsal', 'kid': 'Kate rehearsal', 'dad': 'Busy', 'aunt': 'Busy', 'hal': 'Busy', 'house': 'Busy'},
        'shared': {'mom': 'Aunt fitting', 'dad': 'Aunt fitting', 'aunt': 'Aunt fitting', 'kid': 'Busy', 'hal': 'Busy', 'house': 'Busy'},
        'house': {c: 'Garage hour' for c in ('mom', 'dad', 'aunt', 'kid', 'hal', 'house')},
    }
    for col in ('mom', 'dad', 'aunt', 'kid', 'hal', 'house'):
        got = {h['project_id']: h['title'] for h in projects.calendar_holds(DAY, DAY, _viewer(fx, col))}
        for key, project in proj.items():
            check(got.get(project['id']) == want[key][col], f"calendar_holds {key} for {col}: want {want[key][col]} got {got.get(project['id'])}")
    dad_texts = str([h for h in projects.calendar_holds(DAY, DAY, fx.viewers['dad']) if h['project_id'] == proj['kate']['id']])
    check('Kate rehearsal' not in dad_texts, "Dad gets only Busy for Kate's hold")


def scenario_project_hold_titles_on_the_schedule_response():
    fx, proj, steps = _world()
    for key in ('kate', 'shared', 'house'):
        project, step = proj[key], steps[key]
        blob = {'events': [{'id': 'ev-' + key, 'title': 'Busy', 'event_type': 'project_hold',
                            'project_id': project['id'], 'step_id': step['id']}, {'id': 'plain', 'title': 'Dentist'}]}
        for col in ('mom', 'dad', 'aunt', 'kid', 'hal'):
            out = main._project_hold_titles(blob, fx.viewers[col])
            event = next(e for e in out['events'] if e['id'] == 'ev-' + key)
            sees = projects.can_see(project, fx.viewers[col]) or project['audience'] == 'household'
            check((event['title'] == step['title']) == sees, f"{key} for {col}: {event['title']}")
            if not sees:
                check('project_id' not in event and 'step_id' not in event, f"{key} for {col}: hidden ids are stripped: {event}")
        check(blob['events'][0]['title'] == 'Busy', "the cached blob itself is never rewritten")
    # And through the real route, with the cache holding only the neutral event.
    from access_shared_signals import request
    from unittest.mock import patch
    event = {'id': 'hold-ev', 'title': 'Busy', 'event_type': 'project_hold', 'project_id': proj['kate']['id'],
             'step_id': steps['kate']['id'], 'start': '2027-03-08T17:00:00', 'end': '2027-03-08T17:30:00', 'calendar_ids': []}
    storage.set_cached_schedule({'events': [event], 'assignments': {}, 'unassigned': [], 'true_unassigned': [],
                                 'calendar_metadata': {}, 'members': []})
    seen = {}
    for col in ('mom', 'kid', 'dad'):
        with patch.object(main, 'trigger_background_refresh'):
            r = request(fx, col, 'GET', '/api/schedule')
        check(r.status_code == 200, f"{col}: {r.status_code} {r.text[:200]}")
        seen[col] = 'Kate rehearsal' in r.text
    check(seen == {'mom': True, 'kid': True, 'dad': False}, f"the route says the same: {seen}")


def scenario_spoken_safe_is_household_only():
    fx, proj, steps = _world()
    for key, want in (('kate', False), ('shared', False), ('house', True)):
        row = storage.get_project(proj[key]['id'])
        check(subjects.spoken_safe('project', row) is want, f"spoken_safe {key}")
        for col in ('mom', 'dad'):
            check(bool(subjects.visible('project', row, fx.viewers[col], spoken=True)) is (want and projects.can_see(row, fx.viewers[col])),
                  f"spoken visibility {key} for {col}")


def scenario_sensitive_is_not_household():
    fx, proj, steps = _world()
    check(tools._sensitive('project', storage.get_project(proj['kate']['id'])) is True, "a child's explicit list is sensitive")
    check(tools._sensitive('project', storage.get_project(proj['shared']['id'])) is True, "shared is sensitive")
    check(tools._sensitive('project', storage.get_project(proj['house']['id'])) is False, "household is not")


def scenario_project_in_reach_follows_who_can_see_it():
    from access_channels import focus
    fx, proj, steps = _world()
    kate, shared, house = (storage.get_project(proj[k]['id']) for k in ('kate', 'shared', 'house'))
    for col, want_kate, want_shared in (('mom', True, True), ('kid', True, False), ('dad', False, True), ('aunt', False, True)):
        key = focus(fx, 'dm', col)
        check(tools._project_in_reach(kate, fx.viewers[col], False, key) is want_kate, f"kate project in {col}'s DM")
        check(tools._project_in_reach(shared, fx.viewers[col], False, key) is want_shared, f"shared project in {col}'s DM")
    family = focus(fx, 'family', 'mom')
    check(not tools._project_in_reach(kate, fx.viewers['mom'], False, family), "Kate's list never reaches the family channel (Dad and Aunt are in it)")
    check(not tools._project_in_reach(shared, fx.viewers['mom'], False, family), "nor does a shared project (the child is in it)")
    pair = focus(fx, 'mom_aunt', 'mom')
    check(tools._project_in_reach(shared, fx.viewers['mom'], False, pair), "a shared project reaches Mom and Aunt")
    check(not tools._project_in_reach(kate, fx.viewers['mom'], False, pair), "Kate's list does not (Aunt is off it)")
    for project, want in ((kate, False), (shared, False), (house, True)):
        check(tools._project_in_reach(project, access.HOUSE, True, 'conv:panel') is want, f"a room hears {project['title']}: {want}")


def scenario_proposed_project_subject_record_carries_the_list():
    fx, proj, steps = _world()
    for audience, listed, readers, hidden in (
            ('shared', ['aunt'], ('mom', 'dad', 'aunt'), ()),
            ('private', ['mom'], ('mom',), ('dad', 'aunt'))):
        mid = storage.add_mission({'goal': 'Plan ' + audience, 'created_by': 'mom', 'status': 'waiting_user'})
        storage.update_mission(mid, {'plan': {'state': 'proposed', 'rev': 1, 'stages': [], 'steps': [], 'project': {
            'title': 'Proposed', 'goal': 'g', 'done_when': 'd', 'owner': 'mom', 'audience': audience, 'shared_with': listed,
            'target_date': None}}})
        row = storage.get_mission(mid)
        records = [r for k, r in subjects.subject_records('mission', row) if k == 'proposed_project']
        check(records and records[0]['audience'] == audience and set(records[0]['shared_with']) >= set(listed),
              f"{audience}: a proposal that is not household is a subject record, with its list: {records}")
        for col in readers:
            check(access.record_view('mission', row, fx.viewers[col]) == 'full', f"{audience}: {col} reads the mission")
        for col in hidden:
            check(access.record_view('mission', row, fx.viewers[col]) is None, f"{audience}: {col} does not read the mission")


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

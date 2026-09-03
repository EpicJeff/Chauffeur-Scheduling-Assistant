"""The Study's one read: eleven furniture signals aggregated from existing
services, each section failure-isolated, sensitive rows filtered by the
same gate the mind lane uses. The room is a lens — nothing here writes."""
import datetime
from harness import check
from services import storage, study

NOON = datetime.datetime(2026, 9, 3, 12, 0)
PARENT = {'id': 'mom', 'role': 'parent'}
ADULT = {'id': 'uncle', 'role': 'adult'}


def _reset():
    storage.mind_insights_table.truncate()
    storage.get_settings = lambda: {'mind_enabled': True, 'llm_gemini_api_key': 'k'}


def scenario_board_pins_are_role_filtered():
    _reset()
    storage.add_mind_insight({'slug': 'plain', 'category': 'c', 'line': 'a plain one'})
    storage.add_mind_insight({'slug': 'secret', 'category': 'c', 'line': 'kid strain',
                              'sensitivity': 'sensitive'})
    parent_pins = {p['label'] for p in study.state(PARENT, now=NOON)
                   ['furniture']['board']['pins'] if p['kind'] == 'insight'}
    adult_pins = {p['label'] for p in study.state(ADULT, now=NOON)
                  ['furniture']['board']['pins'] if p['kind'] == 'insight'}
    check('kid strain' in parent_pins, 'parent sees the sensitive pin')
    check('kid strain' not in adult_pins and 'a plain one' in adult_pins,
          'adult board carries only non-sensitive pins')


def scenario_desk_stacks_carry_open_steps_and_due():
    _reset()
    iid = storage.add_mind_insight({'slug': 'p1', 'category': 'c', 'line': 'handled'})
    storage.update_mind_insight(iid, {'state': 'in_hand', 'plan_json': {
        'created_ts': 1.0, 'steps': [
            {'id': 's1', 'kind': 'tool', 'text': 't', 'owner_member_id': None,
             'owner_name': '', 'due': '2026-09-01', 'status': 'open', 'proposal_json': None},
            {'id': 's2', 'kind': 'human', 'text': 'h', 'owner_member_id': None,
             'owner_name': '', 'due': '2026-09-09', 'status': 'open', 'proposal_json': None},
            {'id': 's3', 'kind': 'human', 'text': 'd', 'owner_member_id': None,
             'owner_name': '', 'due': '2026-09-09', 'status': 'done', 'proposal_json': None},
        ]}})
    desk = study.state(PARENT, now=NOON)['furniture']['desk']
    check(len(desk) == 1 and desk[0]['open_steps'] == 2 and desk[0]['due'] is True,
          f'one stack, two open sheets, one overdue: {desk}')


def scenario_calendar_counts_only_uncovered_driver_events():
    """Old cache shape: no true_unassigned/unassigned id list at all, so
    _calendar falls back to the assigned/ghost-covered comparison -- which
    must still skip a display-only (all_day) event by hand, the same way
    is_display_only_event() would have kept it out of the solver."""
    _reset()
    storage.get_cached_schedule = lambda: {
        'events': [
            {'id': 'e1', 'start': '2026-09-04T17:00:00', 'title': 'practice'},
            {'id': 'e2', 'start': '2026-09-04T18:00:00', 'title': 'game'},
            {'id': 'e3', 'start': '2026-09-05T09:00:00', 'title': 'lesson'},
            {'id': 'e9', 'start': '2026-10-20T09:00:00', 'title': 'far away'},
            {'id': 'e4', 'start': '2026-09-06T00:00:00', 'title': 'No School Today',
             'all_day': True},
        ],
        'assignments': {'e1': 'driver1'},
        'ghost_assignments': {'e2': 'ghost_neighbor'},
    }
    cal = study.state(PARENT, now=NOON)['furniture']['calendar']
    check(cal['days'][0]['date'] == '2026-09-03', 'week starts today')
    by_date = {d['date']: d['unassigned'] for d in cal['days']}
    check(by_date['2026-09-04'] == 0, 'assigned + ghost-covered are not holes')
    check(by_date['2026-09-05'] == 1, 'the real hole shows')
    check(by_date['2026-09-06'] == 0,
          'an all-day event is never a driving hole, fallback path (no id list)')
    check('2026-10-20' not in by_date and len(cal['days']) == 7, 'seven days only')


def scenario_calendar_reads_the_solvers_own_unassigned_list():
    """Current cache shape: a `true_unassigned` id list is present (main.py
    ~18280-18288). _calendar must join THAT list to `events` by id rather
    than re-deriving holes from assignments -- an all-day event sits in
    `events` (the family's whole calendar) but a solver never puts one in
    daily_events_to_solve, so it can never legitimately appear in
    true_unassigned either. Reproduces the reviewer's 'No School Today'
    case: same all-day event, same otherwise-clean day, this time with the
    real cache shape a live refresh actually writes."""
    _reset()
    storage.get_cached_schedule = lambda: {
        'events': [
            {'id': 'e3', 'start': '2026-09-05T09:00:00', 'title': 'lesson'},
            {'id': 'e4', 'start': '2026-09-06T00:00:00', 'title': 'No School Today',
             'all_day': True},
        ],
        'assignments': {},
        'ghost_assignments': {},
        'true_unassigned': ['e3'],
    }
    cal = study.state(PARENT, now=NOON)['furniture']['calendar']
    by_date = {d['date']: d['unassigned'] for d in cal['days']}
    check(by_date['2026-09-05'] == 1,
          'the id the solver actually named as unassigned shows')
    check(by_date['2026-09-06'] == 0,
          'an all-day event never enters true_unassigned, so it never counts '
          'even though it sits unassigned-looking in events')


def scenario_a_raising_section_is_calm_not_fatal():
    _reset()
    orig = study._SECTIONS['stickies']
    study._SECTIONS['stickies'] = lambda now, viewer: (_ for _ in ()).throw(RuntimeError('boom'))
    try:
        out = study.state(PARENT, now=NOON)['furniture']
        check(out['stickies'] == study._CALM['stickies'],
              'raising section renders calm')
        check(out['tray'] is not None, 'other sections unaffected')
    finally:
        study._SECTIONS['stickies'] = orig


def scenario_tray_counts_proposed_proposals():
    _reset()
    # Monkeypatch get_proposals to return rows only for status='proposed'
    # since the storage helper may require heavy fields
    orig = storage.get_proposals
    def stub_get_proposals(status=None):
        if status == 'proposed':
            return [{'id': 'p1', 'status': 'proposed'}]
        elif status == 'ignored':
            return [{'id': 'p2', 'status': 'ignored'}]
        return []
    storage.get_proposals = stub_get_proposals
    try:
        tray = study.state(PARENT, now=NOON)['furniture']['tray']
        check(tray['count'] == 1, f'tray shows one proposed proposal: {tray}')
    finally:
        storage.get_proposals = orig


def scenario_gauges_read_without_writing():
    _reset()
    writes = []
    orig = storage.set_app_state
    storage.set_app_state = lambda *a, **k: writes.append(a)
    try:
        study.state(PARENT, now=NOON)
    finally:
        storage.set_app_state = orig
    check(not writes, f'the room never writes, got {writes}')


def scenario_endpoint_gates_and_serves():
    _reset()
    storage.members_table.truncate()
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'kid', 'name': 'Lily', 'role': 'child'})
    import main
    from fastapi import HTTPException
    from services import auth as _auth
    orig = _auth.identify
    try:
        _auth.identify = lambda h, q: {'tier': _auth.SERVICE, 'member': None}
        res = main.study_state(request=None)
        check('furniture' in res and 'board' in res['furniture'],
              'admin surface gets the payload')
    finally:
        _auth.identify = orig
    # a child identity is refused by the same gate the mind endpoints use
    try:
        _auth.identify = lambda h, q: {'tier': _auth.DEVICE, 'device': {}, 'member': None}
        try:
            main.study_state(request=None)
            check(False, 'a device tier must not read the study')
        except HTTPException as e:
            check(e.status_code == 403, f'403, got {e.status_code}')
    finally:
        _auth.identify = orig


def scenario_template_carries_room_fallback_and_vendored_three():
    import os
    path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'study.html')
    src = open(path, encoding='utf-8').read()
    check('id="room"' in src and 'id="fallback"' in src,
          'both render targets present')
    check('static/vendor/three.min.js' in src, 'vendored three referenced')
    check('static/study.js' in src, 'scene script referenced')
    for banned in ('alert(', 'confirm(', 'prompt('):
        check(banned not in src, f'{banned} is banned')


if __name__ == '__main__':
    scenario_board_pins_are_role_filtered()
    scenario_desk_stacks_carry_open_steps_and_due()
    scenario_calendar_counts_only_uncovered_driver_events()
    scenario_calendar_reads_the_solvers_own_unassigned_list()
    scenario_a_raising_section_is_calm_not_fatal()
    scenario_tray_counts_proposed_proposals()
    scenario_gauges_read_without_writing()
    scenario_endpoint_gates_and_serves()
    scenario_template_carries_room_fallback_and_vendored_three()
    print("test_study_state OK")

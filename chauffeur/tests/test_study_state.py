"""The Study's one read: ten furniture signals aggregated from existing
services, each section failure-isolated, sensitive rows filtered by the
same gate the mind lane uses. The room is a lens — nothing here writes."""
import datetime
import time
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


def scenario_desk_sensitivity_gate_runs_both_ways():
    """The desk does NOT ride `visible_insights` — it needs every `in_hand`
    row, not only the ones that lane would surface — so it carries its own
    inline parent-only check. A second copy of a filter is exactly the thing
    that rots quietly, and it rots in the direction that leaks, so pin both
    directions and the nobody-resolved case with it."""
    _reset()
    plain = storage.add_mind_insight({'slug': 'openplan', 'category': 'c',
                                      'line': 'a plain plan'})
    secret = storage.add_mind_insight({'slug': 'closedplan', 'category': 'c',
                                       'line': 'a delicate plan',
                                       'sensitivity': 'sensitive'})
    for iid in (plain, secret):
        storage.update_mind_insight(iid, {'state': 'in_hand', 'plan_json': {
            'created_ts': 1.0, 'steps': [
                {'id': 's1', 'kind': 'human', 'text': 't', 'owner_member_id': None,
                 'owner_name': '', 'due': None, 'status': 'open',
                 'proposal_json': None}]}})
    ids = lambda v: {d['id'] for d in study.state(v, now=NOON)['furniture']['desk']}
    check(ids(PARENT) == {plain, secret}, f'a parent sees both stacks: {ids(PARENT)}')
    check(ids(ADULT) == {plain}, f'an adult sees only the plain stack: {ids(ADULT)}')
    check(ids(None) == {plain},
          f'an admin surface with nobody resolved is not a parent either: {ids(None)}')


def scenario_key_tags_mirror_the_cars_thresholds():
    """A tag on the hook has to mean what the family is already told a low
    car means, and that is services/cars.py:288-303: battery asked FIRST
    against `car_battery_warn_pct` (30 by default), then fuel against
    `car_fuel_warn_pct` (25), both settable.

    Reading one blended percentage against a hardcoded 25 — which this did —
    hangs no tag on an EV at 28% charge while `digest_fuel_notes` is telling
    that car's driver to plug it in tonight, and hangs one on a petrol car at
    25% that nothing else in the app considers low."""
    _reset()
    from services import cars
    orig = (storage.get_all_cars, cars.car_levels, cars.has_telemetry,
            storage.get_settings)
    rows = [{'id': 'ev', 'name': 'Bolt'}, {'id': 'gas', 'name': 'CR-V'}]
    levels = {'ev': {'battery_pct': 28, 'fuel_pct': None, 'range': None},
              'gas': {'battery_pct': None, 'fuel_pct': 28, 'range': None}}
    low = lambda: {k['id']: k['low']
                   for k in study.state(PARENT, now=NOON)['furniture']['keys']}
    try:
        storage.get_all_cars = lambda: rows
        cars.has_telemetry = lambda c: True
        cars.car_levels = lambda c: levels[c['id']]

        storage.get_settings = lambda: {}
        check(low() == {'ev': True, 'gas': False},
              f'28% is low for a battery (warn 30) and fine for a tank '
              f'(warn 25): {low()}')

        storage.get_settings = lambda: {'car_battery_warn_pct': 20,
                                        'car_fuel_warn_pct': 40}
        check(low() == {'ev': False, 'gas': True},
              f'both custom warn percentages are honoured: {low()}')

        storage.get_settings = lambda: {'car_battery_warn_pct': '',
                                        'car_fuel_warn_pct': 'nonsense'}
        check(low() == {'ev': True, 'gas': False},
              f'an unusable setting falls back to the default, same as '
              f'cars._flt: {low()}')
    finally:
        (storage.get_all_cars, cars.car_levels, cars.has_telemetry,
         storage.get_settings) = orig


def scenario_glow_timestamps_are_epoch_seconds():
    """study.js's since-you-were-here glow compares `changed_ts` against a
    `Date.now() / 1000` stamp in localStorage. A section handing back
    milliseconds would light every pin on every visit, forever; an ISO
    string would light none of them, silently. Both are one keystroke away
    and neither shows up in a screenshot, so pin the unit at the boundary."""
    _reset()
    storage.add_mind_insight({'slug': 'fresh', 'category': 'c', 'line': 'new'})
    storage.add_thread({'title': 'A new loop', 'kind': 'project'})
    held = storage.add_mind_insight({'slug': 'held', 'category': 'c', 'line': 'held'})
    storage.update_mind_insight(held, {'state': 'in_hand', 'plan_json': {
        'created_ts': time.time(), 'steps': []}})
    now = time.time()
    f = study.state(PARENT, now=NOON)['furniture']
    stamps = ([p['changed_ts'] for p in f['board']['pins']]
              + [d['changed_ts'] for d in f['desk']])
    check(len(stamps) >= 3, f'an insight pin, a thread pin and a stack: {stamps}')
    for ts in stamps:
        check(isinstance(ts, (int, float)) and not isinstance(ts, bool),
              f'changed_ts is a number, not {type(ts).__name__}')
        check(ts < 1e11, f'{ts} is seconds, not milliseconds')
        check(abs(now - ts) < 10, f'{ts} is about now ({now})')


def scenario_calendar_counts_only_uncovered_driver_events():
    """Old cache shape: no true_unassigned/unassigned id list at all, so
    _calendar falls back to the assigned/ghost-covered comparison -- which
    must still skip a display-only (all_day) event by hand, the same way
    is_display_only_event() would have kept it out of the solver."""
    _reset()
    orig = storage.get_cached_schedule
    try:
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
    finally:
        storage.get_cached_schedule = orig
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
    orig = storage.get_cached_schedule
    try:
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
    finally:
        storage.get_cached_schedule = orig
    by_date = {d['date']: d['unassigned'] for d in cal['days']}
    check(by_date['2026-09-05'] == 1,
          'the id the solver actually named as unassigned shows')
    check(by_date['2026-09-06'] == 0,
          'an all-day event never enters true_unassigned, so it never counts '
          'even though it sits unassigned-looking in events')


def scenario_calendar_falls_back_to_the_unassigned_alias():
    """The middle cache shape, and the branch nothing exercised: a cache
    carrying `unassigned` but NOT `true_unassigned`. `_calendar` reads
    `true_unassigned` first and falls back to the alias (main.py writes both
    at ~18280/~18288, but an older cache written before the rename — or one
    round-tripped through anything that kept only the aliased key — has just
    the one). The alias is the SAME id list, so it must count identically,
    and must NOT drop through to the assignments diff, which would count a
    covered day as a hole."""
    _reset()
    orig = storage.get_cached_schedule
    try:
        storage.get_cached_schedule = lambda: {
            'events': [
                {'id': 'e1', 'start': '2026-09-04T17:00:00', 'title': 'practice'},
                {'id': 'e3', 'start': '2026-09-05T09:00:00', 'title': 'lesson'},
            ],
            # No assignments at all: if the alias were ignored and the
            # fallback ran, BOTH days would read as holes.
            'assignments': {},
            'ghost_assignments': {},
            'unassigned': ['e3'],
        }
        cal = study.state(PARENT, now=NOON)['furniture']['calendar']
    finally:
        storage.get_cached_schedule = orig
    by_date = {d['date']: d['unassigned'] for d in cal['days']}
    check(by_date['2026-09-05'] == 1, 'the aliased id list is read')
    check(by_date['2026-09-04'] == 0,
          'a day the alias does not name is covered — the assignments diff '
          'never ran')


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


def scenario_the_endpoint_refuses_a_signed_in_child():
    """The DEVICE-tier refusal above is the anonymous kiosk. This is the
    other half of the gate, and the half the spec names outright: a CHILD who
    is properly signed in, token and all. `_mind_actor` resolves the token to
    a member and refuses `child/helper/guest` by ROLE — a different branch
    from the tier check, and the one a family actually walks into.

    Driven through the real token path rather than a stubbed resolver: a
    stubbed `identify` would only prove that a stub returns what it was
    told."""
    _reset()
    storage.members_table.truncate()
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'kid', 'name': 'Lily', 'role': 'child'})
    import main
    from fastapi import HTTPException

    class _Req:                      # what auth.acting_member actually reads
        def __init__(self, token):
            self.headers = {'x-member-token': token}
            self.query_params = {}

    try:
        main.study_state(request=_Req(storage.create_member_token('kid')))
        check(False, 'a signed-in child must not read the study')
    except HTTPException as e:
        check(e.status_code == 403, f'403 for a child, got {e.status_code}')
    res = main.study_state(request=_Req(storage.create_member_token('mom')))
    check('furniture' in res, 'the same door opens for a signed-in parent')


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


def scenario_scene_honors_the_read_only_law():
    import os, re
    path = os.path.join(os.path.dirname(__file__), '..', 'static', 'study.js')
    src = open(path, encoding='utf-8').read()
    check(not re.search(r"method:\s*['\"](POST|PUT|DELETE|PATCH)", src),
          'the room never writes')
    check("localStorage" in src and 'try' in src,
          'since-you-were-here uses guarded localStorage')


def scenario_the_fallback_keeps_model_text_out_of_innerhtml():
    """Every row of the fallback list carries text somebody else wrote — an
    insight line, a thread title, a program title, a car name, a counterparty
    the family never chose. The list is built by joining an HTML string, so
    the one thing that must never appear inside that template is the row's
    signal; it is written afterwards through `.textContent`, which cannot
    execute anything.

    A source pin, like the read-only law above: this is a property of how the
    string is built, and there is no DOM in this process to run it in."""
    import os, re
    path = os.path.join(os.path.dirname(__file__), '..', 'static', 'study.js')
    src = open(path, encoding='utf-8').read()
    m = re.search(r"innerHTML = rows\.map\((.*?)\.join\(''\);", src, re.S)
    check(bool(m), 'the fallback still builds its rows by joining a template')
    tpl = m.group(1)
    check('${sig}' not in tpl,
          'the signal text is interpolated straight into the row HTML')
    for token in re.findall(r'\$\{\s*([A-Za-z_$][\w$]*)', tpl):
        check(token in ('calm', 'href', 'rel', 'kind'),
              f"the row template interpolates {token!r} into innerHTML — only "
              "the link and the fixed kind label may go that way")
    check(re.search(r'\.textContent\s*=\s*rows\[i\]\[2\]', src),
          'the signal is no longer assigned through textContent')


if __name__ == '__main__':
    scenario_board_pins_are_role_filtered()
    scenario_desk_stacks_carry_open_steps_and_due()
    scenario_desk_sensitivity_gate_runs_both_ways()
    scenario_key_tags_mirror_the_cars_thresholds()
    scenario_glow_timestamps_are_epoch_seconds()
    scenario_calendar_counts_only_uncovered_driver_events()
    scenario_calendar_reads_the_solvers_own_unassigned_list()
    scenario_calendar_falls_back_to_the_unassigned_alias()
    scenario_a_raising_section_is_calm_not_fatal()
    scenario_tray_counts_proposed_proposals()
    scenario_gauges_read_without_writing()
    scenario_endpoint_gates_and_serves()
    scenario_the_endpoint_refuses_a_signed_in_child()
    scenario_template_carries_room_fallback_and_vendored_three()
    scenario_scene_honors_the_read_only_law()
    scenario_the_fallback_keeps_model_text_out_of_innerhtml()
    print("test_study_state OK")

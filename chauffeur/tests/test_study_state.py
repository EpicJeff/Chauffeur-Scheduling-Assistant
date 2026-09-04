"""The Study's one read: twelve furniture signals aggregated from existing
services, each section failure-isolated, sensitive rows filtered by the
same gate the mind lane uses. The room is a lens — nothing here writes.

Since v2.455.0 each section also carries the DETAIL a leaned-in reader
gets — the plan's line, the proposal's title, the finding's sentence, the
day's events and who is driving them, the car's percentage, the deal, the
program's week. All of it rides the section's existing filters; none of it
opens a door the section did not already have."""
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


def scenario_desk_line_rides_the_same_gate_as_its_row():
    """The detail a focused desk paints is the plan's own line, and it is the
    one field on that row somebody else's words are in. It gets NO gate of its
    own: the row is dropped whole for a non-parent, so there is no sensitive
    line left for the client to leak. Assert both halves — the parent gets the
    line, and the adult gets no row at all rather than a row with the line
    blanked, which is the failure mode a second gate would produce."""
    _reset()
    plain = storage.add_mind_insight({'slug': 'open2', 'category': 'c',
                                      'line': 'Move swim to the 6pm lane'})
    secret = storage.add_mind_insight({'slug': 'closed2', 'category': 'c',
                                       'line': 'Lily has been crying at drop-off',
                                       'sensitivity': 'sensitive'})
    for iid in (plain, secret):
        storage.update_mind_insight(iid, {'state': 'in_hand', 'plan_json': {
            'created_ts': 1.0, 'steps': [
                {'id': 's1', 'kind': 'human', 'text': 't', 'owner_member_id': None,
                 'owner_name': '', 'due': None, 'status': 'open',
                 'proposal_json': None}]}})
    by_id = lambda v: {d['id']: d for d in
                       study.state(v, now=NOON)['furniture']['desk']}
    p, a = by_id(PARENT), by_id(ADULT)
    check(p[plain]['line'] == 'Move swim to the 6pm lane',
          f"a parent's stack carries the plan's line: {p[plain]}")
    check(p[secret]['line'] == 'Lily has been crying at drop-off',
          'and the sensitive one too, for a parent')
    check(secret not in a, f'the adult never receives the row: {sorted(a)}')
    check(a[plain]['line'] == 'Move swim to the 6pm lane',
          'the plain row still carries its line for an adult')


def scenario_tray_carries_the_titles_it_is_waiting_on():
    _reset()
    orig = storage.get_proposals
    rows = [{'id': f'p{i}', 'status': 'proposed', 'title': f'Notice {i}'}
            for i in range(7)]
    rows.append({'id': 'blank', 'status': 'proposed'})
    try:
        storage.get_proposals = lambda status=None: (
            rows if status in (None, 'proposed') else [])
        tray = study.state(PARENT, now=NOON)['furniture']['tray']
    finally:
        storage.get_proposals = orig
    check(tray['count'] == 8, f'the count is every waiting row: {tray["count"]}')
    check(len(tray['items']) == 5, f'five titles at most: {tray["items"]}')
    check([i['title'] for i in tray['items']] == [f'Notice {i}' for i in range(5)],
          f'and they are the `title` field, in order: {tray["items"]}')
    _reset()
    storage.get_proposals = lambda status=None: [{'id': 'x', 'status': 'proposed'}]
    try:
        t2 = study.state(PARENT, now=NOON)['furniture']['tray']
        check(t2['items'] == [{'title': ''}],
              f'a proposal with no title contributes an empty one, not a crash: {t2}')
    finally:
        storage.get_proposals = orig


def scenario_stickies_carry_their_finding_lines():
    _reset()
    from services import findings
    orig = findings.open_findings
    rows = [{'id': f'f{i}', 'line': f'thing {i}', 'severity': 'decide' if i < 2 else 'fyi'}
            for i in range(6)]
    try:
        findings.open_findings = lambda severity=None: rows
        st = study.state(PARENT, now=NOON)['furniture']['stickies']
    finally:
        findings.open_findings = orig
    check(st['count'] == 6 and st['worst'] == 'decide', f'unchanged head: {st}')
    check(len(st['items']) == 5, f'five notes at most: {st["items"]}')
    check(st['items'][0] == {'line': 'thing 0', 'severity': 'decide'},
          f'each note carries its line and its severity: {st["items"][0]}')


def scenario_calendar_days_carry_their_events_in_the_drivers_colour():
    """The focused calendar draws a real page, so each day carries what is on
    it. Colour is the ASSIGNED DRIVER's own (`color_code`), a ghost counts as
    covered, and a ride nobody is driving comes through with colour None
    rather than a made-up one. Four events ride per day and anything past
    that is COUNTED in `more` — a face that says '+1' on a day holding nine
    things would be a lie nothing could catch."""
    _reset()
    orig = (storage.get_cached_schedule, storage.get_all_drivers,
            storage.get_all_members)
    events = [{'id': f'e{i}', 'start': f'2026-09-04T{8 + i:02d}:00:00',
               'title': f'Thing {i}'} for i in range(6)]
    events.append({'id': 'ghost', 'start': '2026-09-05T09:00:00', 'title': 'Ghosted'})
    events.append({'id': 'nodriver', 'start': '2026-09-05T10:00:00', 'title': 'Nobody'})
    try:
        storage.get_cached_schedule = lambda: {
            'events': events,
            'assignments': {f'e{i}': ('mom' if i % 2 else 'dad') for i in range(6)},
            'ghost_assignments': {'ghost': 'ghost_neighbor'},
            'true_unassigned': ['nodriver']}
        storage.get_all_drivers = lambda: [
            {'id': 'mom', 'name': 'Dana', 'color_code': '#e0653b'},
            {'id': 'dad', 'name': 'Marcus', 'color_code': ''}]
        storage.get_all_members = lambda *a, **k: [
            {'id': 'm1', 'name': 'Dana', 'driver_id': 'mom', 'color_code': '#111111'},
            {'id': 'ghost_neighbor', 'name': 'Neighbour', 'color_code': '#4f9a4f'}]
        days = {d['date']: d for d in
                study.state(PARENT, now=NOON)['furniture']['calendar']['days']}
    finally:
        (storage.get_cached_schedule, storage.get_all_drivers,
         storage.get_all_members) = orig
    d4 = days['2026-09-04']
    check(len(d4['events']) == 4, f'four events ride per day at most: {d4}')
    check(d4['more'] == 2, f'and the two that did not fit are counted: {d4["more"]}')
    check([e['title'] for e in d4['events']] == [f'Thing {i}' for i in range(4)],
          f'in start order: {d4["events"]}')
    check(d4['events'][1]['color'] == '#e0653b',
          f"the driver's own colour, from the drivers table: {d4['events'][1]}")
    check(d4['events'][0]['color'] is None,
          f'a driver with no colour stored gets None, never an invented one: '
          f'{d4["events"][0]}')
    d5 = {e['title']: e for e in days['2026-09-05']['events']}
    check(d5['Ghosted']['color'] == '#4f9a4f',
          f'a ghost-covered ride is coloured by whoever covered it: {d5["Ghosted"]}')
    check(d5['Nobody']['color'] is None,
          f'and a ride nobody is driving carries no colour: {d5["Nobody"]}')
    check(days['2026-09-05']['unassigned'] == 1 and days['2026-09-04']['unassigned'] == 0,
          f'the red still comes from the solver\'s own list: {days["2026-09-05"]}')


def scenario_window_signs_respect_the_ready_gate():
    """The card on the sill says levels, which are honest from day one; what
    it must NOT do before there is a baseline is single anything out as
    WORSE, because `worse` is a comparison and there is nothing to compare
    to yet. Same gate the clouds already ride."""
    _reset()
    from services import vitals
    orig = vitals.read
    # `margin` sits THIRD in the household order on purpose: it is the only
    # row flagged worse, so whether it leads the list is exactly the gate.
    rows = [{'name': 'rest', 'label': 'rest', 'current': 0.0, 'worse': False},
            {'name': 'friction', 'label': 'friction', 'current': 3.0, 'worse': False},
            {'name': 'margin', 'label': 'margin', 'current': 38.4, 'worse': True},
            {'name': 'together', 'label': 'togetherness', 'current': 11.0, 'worse': False},
            {'name': 'ft', 'label': 'follow-through', 'current': 76.8, 'worse': False}]
    try:
        vitals.read = lambda now=None: {'ready': True, 'days': 30, 'household': rows,
                                        'people': [], 'streaks': {}}
        w = study.state(PARENT, now=NOON)['furniture']['window']
        check(w['signs'][0] == 'margin 38.4',
              f'with a baseline, the worse sign leads: {w["signs"]}')
        check(len(w['signs']) == 4,
              f'one worse plus three steady: {w["signs"]}')
        check('rest 0' in w['signs'],
              f'a whole number is not printed as 0.0: {w["signs"]}')

        vitals.read = lambda now=None: {'ready': False, 'days': 4, 'household': rows,
                                        'people': [], 'streaks': {}}
        early = study.state(PARENT, now=NOON)['furniture']['window']
        check(early['label'] == 'early days',
              f'the label still says there is no baseline yet: {early["label"]}')
        check(early['signs'] == ['rest 0', 'friction 3', 'margin 38.4'],
              f'levels are still said, in their own order and with none of '
              f'them singled out as worse: {early["signs"]}')
    finally:
        vitals.read = orig


def scenario_contracts_carry_the_deals_they_are_waiting_on():
    _reset()
    orig = storage.get_deals
    try:
        storage.get_deals = lambda *a, **k: [
            {'id': 'd1', 'state': 'draft', 'seed_title': 'Saturday swim',
             'line': 'Rosa takes swim'},
            {'id': 'd2', 'state': 'asking', 'seed_title': '',
             'line': 'The Ozturks take robotics'},
            {'id': 'd3', 'state': 'applied', 'seed_title': 'Already done'},
            {'id': 'd4', 'state': 'draft', 'seed_title': 'Third'},
            {'id': 'd5', 'state': 'draft', 'seed_title': 'Fourth'}]
        c = study.state(PARENT, now=NOON)['furniture']['contracts']
    finally:
        storage.get_deals = orig
    check(c['count'] == 4, f'draft and asking only: {c["count"]}')
    check(len(c['items']) == 3, f'three slips at most: {c["items"]}')
    check(c['items'][0]['title'] == 'Saturday swim', f'the seed event: {c["items"]}')
    check(c['items'][1]['title'] == 'The Ozturks take robotics',
          f'and the sentence when the seed had no title: {c["items"][1]}')


def scenario_binder_detail_is_honest_or_empty():
    """The spine's second line is read, never defaulted. `programs.clamp_shape`
    would happily hand back 3x25min for a program that stored neither number,
    and an invented week is worse than a short line. It also does NOT say
    'phase 2 of 4': `programs.progress` withholds the phase total on purpose
    (services/programs.py:129-137 — a count next to a total is a completion
    percentage away), so what a binder names is the phase somebody is IN."""
    _reset()
    orig = storage.get_programs
    try:
        storage.get_programs = lambda *a, **k: [
            {'id': 'p1', 'title': 'Swim', 'state': 'active',
             'shape': {'sessions_per_week': 3, 'minutes': 30},
             'phases': [{'name': 'Water feel', 'milestone_hit_at': 1.0},
                        {'name': 'Breathing'}, {'name': 'Turns'}]},
            {'id': 'p2', 'title': 'No phases', 'state': 'active',
             'shape': {'sessions_per_week': 2, 'minutes': 45}, 'phases': []},
            {'id': 'p3', 'title': 'Nothing stored', 'state': 'active',
             'shape': {}, 'phases': []},
            {'id': 'p4', 'title': 'All done', 'state': 'active',
             'shape': {'sessions_per_week': 4, 'minutes': 20},
             'phases': [{'name': 'Only one', 'milestone_hit_at': 2.0}]}]
        rows = {b['id']: b for b in study.state(PARENT, now=NOON)['furniture']['binders']}
    finally:
        storage.get_programs = orig
    check(rows['p1']['detail'] == '3x30min · Breathing',
          f'the week and the phase they are in: {rows["p1"]["detail"]!r}')
    check('/' not in rows['p1']['detail'],
          'and never a phase count over a total, which is a banned percentage')
    check(rows['p2']['detail'] == '2x45min',
          f'no phases, so nothing about phases: {rows["p2"]["detail"]!r}')
    check(rows['p3']['detail'] == '',
          f'nothing stored, nothing said — not a defaulted 3x25min: '
          f'{rows["p3"]["detail"]!r}')
    check(rows['p4']['detail'] == '4x20min',
          f'every phase hit means no phase is current: {rows["p4"]["detail"]!r}')


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

        # The tag a focused hook paints shows a number, and it has to be the
        # number the low/not-low call was actually made on — battery first,
        # exactly as above. A hybrid reading fine on both is judged on its
        # battery and SAYS battery; one whose tank is low shows the tank
        # rather than the charge nothing warned anybody about.
        rows.append({'id': 'phev', 'name': 'Pacifica'})
        rows.append({'id': 'dumb', 'name': 'The old wagon'})
        levels['phev'] = {'battery_pct': 90, 'fuel_pct': 8, 'range': None}
        levels['dumb'] = {'battery_pct': None, 'fuel_pct': None, 'range': None}
        storage.get_settings = lambda: {}
        seen = {k['id']: (k['kind'], k['pct'], k['low'])
                for k in study.state(PARENT, now=NOON)['furniture']['keys']}
        check(seen['ev'] == ('battery', 28, True), f'the low battery: {seen["ev"]}')
        check(seen['gas'] == ('fuel', 28, False),
              f'a healthy tank still reports as a tank: {seen["gas"]}')
        check(seen['phev'] == ('fuel', 8, True),
              f'the reading that made it low, not the healthy battery: '
              f'{seen["phev"]}')
        check(seen['dumb'] == (None, None, False),
              f'a car with no readings claims none: {seen["dumb"]}')
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


def scenario_monitor_clusters_are_one_per_person_sized_by_their_week():
    """Argyle's screen draws one cluster per member, sized by that person's
    next seven days. Ownership is decided the way `mind._calendar` decides
    it — members own `calendar_ids`, events carry the ids of the calendars
    they came from — and an event that names the same person through two of
    their own calendars is ONE thing in their week, not two."""
    _reset()
    orig = (storage.get_all_members, storage.get_cached_schedule)
    people = [{'id': 'mom', 'name': 'Mom', 'calendar_ids': ['mom@cal', 'work@cal']},
              {'id': 'lily', 'name': 'Lily', 'calendar_ids': ['lily@cal']},
              {'id': 'ash', 'name': 'Ash', 'calendar_ids': ['ash@cal']},
              {'id': 'ben', 'name': 'Ben'}]
    events = [
        {'id': 'a', 'start': '2026-09-04T17:00:00', 'calendar_ids': ['mom@cal']},
        {'id': 'b', 'start': '2026-09-05T09:00:00', 'calendar_ids': ['mom@cal', 'lily@cal']},
        {'id': 'c', 'start': '2026-09-06T09:00:00', 'calendar_ids': ['mom@cal', 'work@cal']},
        {'id': 'd', 'start': '2026-09-01T09:00:00', 'calendar_ids': ['lily@cal']},
        {'id': 'e', 'start': '2026-10-20T09:00:00', 'calendar_ids': ['lily@cal']},
        {'id': 'f', 'start': 'not a date at all', 'calendar_ids': ['lily@cal']},
    ]
    try:
        storage.get_all_members = lambda *a, **k: people
        storage.get_cached_schedule = lambda: {'events': events, 'true_unassigned': []}
        mon = study.state(PARENT, now=NOON)['furniture']['monitor']
        counts = {c['name']: c['count'] for c in mon['clusters']}
        check(counts == {'Ash': 0, 'Ben': 0, 'Lily': 1, 'Mom': 3},
              f'three for Mom (her two calendars on one event count once), '
              f'one for Lily, and a quiet cluster each for the other two: {counts}')
        check([c['name'] for c in mon['clusters']] == ['Ash', 'Ben', 'Lily', 'Mom'],
              'the order is by name, so a cluster does not move between polls')
        # A member with an empty week still gets a cluster: a small quiet
        # cluster is the honest drawing of a quiet week; a missing one reads
        # as a missing person.
        check(any(c['name'] == 'Ash' and c['count'] == 0 for c in mon['clusters']),
              'a person with nothing on is still on the screen')

        storage.get_all_members = lambda *a, **k: [
            {'id': f'p{i}', 'name': f'P{i:02d}', 'calendar_ids': []} for i in range(11)]
        capped = study.state(PARENT, now=NOON)['furniture']['monitor']['clusters']
        check(len(capped) == 8, f'eight clusters at most, got {len(capped)}')
        check([c['name'] for c in capped] == [f'P{i:02d}' for i in range(8)],
              'and the cap takes the first eight of the same stable order')
    finally:
        (storage.get_all_members, storage.get_cached_schedule) = orig


def scenario_map_pins_only_the_trips_still_ahead():
    """The wall map is a plan board, not a scrapbook: a trip that already
    happened loses its pin, a trip with no date yet keeps one (a plan
    without a week in it is still a plan), and exactly one pin — the
    soonest DATED one — is the upcoming one that glows."""
    _reset()
    orig = (storage.get_all_trip_metadata, storage.get_cached_schedule)
    day, now_ts = 86400.0, NOON.timestamp()
    trips = [
        {'id': 't_past', 'event_id': 'ep', 'title': 'Last summer', 'location': 'Maine',
         'mock_start_date': now_ts - 30 * day, 'audience': 'household'},
        {'id': 't_later', 'event_id': 'el', 'title': 'Ski week', 'location': 'Vermont',
         'mock_start_date': now_ts + 40 * day, 'audience': 'household'},
        {'id': 't_soon', 'event_id': 'es', 'title': 'Disney', 'location': 'Orlando',
         'mock_start_date': now_ts + 9 * day, 'audience': 'household'},
        {'id': 't_undated', 'event_id': 'eu', 'title': 'Someday', 'location': 'Japan',
         'audience': 'household'},
        {'id': 't_event', 'event_id': 'ee', 'title': 'Grandma', 'location': 'Ohio',
         'audience': 'household'},
    ]
    try:
        storage.get_all_trip_metadata = lambda: trips
        storage.get_cached_schedule = lambda: {
            'events': [{'id': 'ee', 'start': '2026-09-20T08:00:00'}],
            'true_unassigned': []}
        rows = study.state(PARENT, now=NOON)['furniture']['map']['trips']
        ids = [r['id'] for r in rows]
        check('t_past' not in ids, f'a trip that already happened is off the map: {ids}')
        check(ids == ['t_soon', 't_event', 't_later', 't_undated'],
              f'soonest first, undated last: {ids}')
        check(rows[1]['start_ts'] is not None,
              'a trip with no mock date takes the date off its linked event')
        check(rows[3]['start_ts'] is None and rows[3]['upcoming'] is False,
              'the undated pin stays, and never claims to be the next thing')
        check([r['upcoming'] for r in rows] == [True, False, False, False],
              f'exactly the soonest dated trip is upcoming: {rows}')

        storage.get_all_trip_metadata = lambda: [
            {'id': f'x{i}', 'event_id': f'e{i}', 'title': f'Trip {i}', 'location': 'away',
             'mock_start_date': now_ts + (i + 1) * day, 'audience': 'household'}
            for i in range(9)]
        capped = study.state(PARENT, now=NOON)['furniture']['map']['trips']
        check(len(capped) == 6, f'six pins at most, got {len(capped)}')
        check([r['id'] for r in capped] == [f'x{i}' for i in range(6)],
              'and the six kept are the six soonest')
    finally:
        (storage.get_all_trip_metadata, storage.get_cached_schedule) = orig


def scenario_map_holds_a_closed_trip_back_from_a_resolved_adult():
    """A trip carrying a metadata record is `parents` by default
    (`scope.AUDIENCE_DEFAULTS`) — a plan is a surprise until somebody says
    otherwise — and the Study is open to adults, not just parents. So the
    map runs the same audience gate every other trip surface runs.

    `viewer is None` is the ADMIN SURFACE, not an anonymous kiosk (see
    `main._is_admin_surface`): it is the control centre, where `/trips`
    itself already lists every trip including the ones the family wall may
    not show, so the map opens no door that surface did not already have."""
    _reset()
    orig = storage.get_all_trip_metadata
    surprise = {'id': 't_secret', 'event_id': 'e1', 'title': 'Anniversary weekend',
                'location': 'Charleston', 'mock_start_date': NOON.timestamp() + 86400,
                'audience': 'parents'}
    shared = {'id': 't_open', 'event_id': 'e2', 'title': 'Beach day',
              'location': 'Cape', 'mock_start_date': NOON.timestamp() + 172800,
              'audience': 'household'}
    try:
        storage.get_all_trip_metadata = lambda: [surprise, shared]
        seen = lambda v: {r['id'] for r in
                          study.state(v, now=NOON)['furniture']['map']['trips']}
        check(seen(PARENT) == {'t_secret', 't_open'}, f'a parent sees both: {seen(PARENT)}')
        check(seen(ADULT) == {'t_open'},
              f'a resolved adult never reads a surprise off the wall: {seen(ADULT)}')
        check(seen(None) == {'t_secret', 't_open'},
              'the admin surface sees what /trips already shows it')
    finally:
        storage.get_all_trip_metadata = orig


def scenario_every_section_carries_a_calm_form():
    """`state()` substitutes `_CALM[key]` when a section raises, so a section
    with no calm form of its own would turn one provider's bad day into a
    KeyError that empties the whole room. The two newest sections are the
    ones most likely to be added without one."""
    check(set(study._SECTIONS) <= set(study._CALM),
          f'every section has a calm form: '
          f'{set(study._SECTIONS) - set(study._CALM)} missing')
    check(study._CALM['monitor'] == {'clusters': []}, 'a calm screen has no clusters')
    check(study._CALM['map'] == {'trips': []}, 'a calm map has no pins')
    # The detail lists a focused zone paints from have to exist in the calm
    # form too, or a broken provider hands the room a section whose shape the
    # client has to guess at.
    for key, field in (('tray', 'items'), ('stickies', 'items'),
                       ('contracts', 'items'), ('window', 'signs')):
        check(study._CALM[key].get(field) == [],
              f'a calm {key} carries an empty {field}: {study._CALM[key]}')
    for key in ('monitor', 'map'):
        orig = study._SECTIONS[key]
        study._SECTIONS[key] = lambda now, viewer: (_ for _ in ()).throw(RuntimeError('boom'))
        try:
            out = study.state(PARENT, now=NOON)['furniture']
            check(out[key] == study._CALM[key],
                  f'a raising {key} renders calm, not missing')
        finally:
            study._SECTIONS[key] = orig


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
    # The map's row carries a trip title and a place name, both typed by
    # somebody. It must ride the same `rows` list as every other signal, not
    # a template of its own — that is the whole protection.
    check(re.search(r"rows\.push\(\['/trips',\s*'Trip',", src),
          'the map row joins the same rows list, so its title goes out '
          'through textContent with every other signal')
    # The detail layer paints an insight line, a thread title, a proposal
    # subject, a finding, a deal, a car name and an event title — every one
    # of them typed by somebody else. All of it goes through a canvas, which
    # cannot execute anything, so the room's ONE innerHTML stays the fallback
    # row template above and no second one is ever added beside it.
    check(len(re.findall(r'\.innerHTML\s*=', src)) == 1,
          f'study.js assigns innerHTML exactly once (the fallback rows), '
          f'found {len(re.findall(r".innerHTML", src))}')
    m2 = re.search(r'const DETAIL = \{(.*?)\n  \};', src, re.S)
    check(bool(m2), 'the DETAIL table is still one object literal')
    check('innerHTML' not in m2.group(1) and 'textContent' not in m2.group(1),
          'no zone paints its detail through the DOM')
    for zone in ('board', 'desk', 'tray', 'stickies', 'calendar', 'window',
                 'keys', 'contracts', 'binders', 'gauges', 'monitor', 'map'):
        check(re.search(r'\n    %s: \(d, z\) =>' % zone, m2.group(1)),
              f'{zone} has a detail paint of its own')


if __name__ == '__main__':
    scenario_board_pins_are_role_filtered()
    scenario_desk_stacks_carry_open_steps_and_due()
    scenario_desk_sensitivity_gate_runs_both_ways()
    scenario_desk_line_rides_the_same_gate_as_its_row()
    scenario_tray_carries_the_titles_it_is_waiting_on()
    scenario_stickies_carry_their_finding_lines()
    scenario_calendar_days_carry_their_events_in_the_drivers_colour()
    scenario_window_signs_respect_the_ready_gate()
    scenario_contracts_carry_the_deals_they_are_waiting_on()
    scenario_binder_detail_is_honest_or_empty()
    scenario_key_tags_mirror_the_cars_thresholds()
    scenario_glow_timestamps_are_epoch_seconds()
    scenario_calendar_counts_only_uncovered_driver_events()
    scenario_calendar_reads_the_solvers_own_unassigned_list()
    scenario_calendar_falls_back_to_the_unassigned_alias()
    scenario_monitor_clusters_are_one_per_person_sized_by_their_week()
    scenario_map_pins_only_the_trips_still_ahead()
    scenario_map_holds_a_closed_trip_back_from_a_resolved_adult()
    scenario_every_section_carries_a_calm_form()
    scenario_a_raising_section_is_calm_not_fatal()
    scenario_tray_counts_proposed_proposals()
    scenario_gauges_read_without_writing()
    scenario_endpoint_gates_and_serves()
    scenario_the_endpoint_refuses_a_signed_in_child()
    scenario_template_carries_room_fallback_and_vendored_three()
    scenario_scene_honors_the_read_only_law()
    scenario_the_fallback_keeps_model_text_out_of_innerhtml()
    print("test_study_state OK")

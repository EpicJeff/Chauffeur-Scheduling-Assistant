"""The retro-split: day-of attendance overrides (v2.270.0).

The household's framing, which is the spec: the systems for splitting an
event exist (hashtags, rules, the 2-hour default) but nobody pre-plans
everything — so the app provides real-time opt-in instead of a prompt in
anyone's face. Load-bearing properties pinned here:

  1. The day-of override outranks every planned signal, in both directions.
  2. Declaring "not staying" PINS both slices to the driver already on the
     event — a mid-day re-solve must not hand the afternoon to somebody
     else as a side effect of one honest declaration.
  3. Drive history survives the rename: the leg the driver just finished
     must not draw as never-driven when the schedule rebuilds.
  4. Overrides expire on their own — a Tuesday declaration must never
     quietly reshape next Tuesday's recurrence.

Run from chauffeur/:  python tests/test_attendance_override.py
"""
import datetime
import time

from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)

from services import storage

TODAY = datetime.date.today()


def _reset():
    import main  # noqa: F401
    for t in (storage.cache_table, storage.overrides_table,
              storage.drive_status_table, storage.app_state_table):
        t.truncate()
    storage.set_cached_schedule({
        "events": [{"id": "art", "title": "Art Class",
                    "location": "Studio, Cary",
                    "start": f"{TODAY.isoformat()}T16:00:00",
                    "end": f"{TODAY.isoformat()}T17:00:00"}],
        "assignments": {"art": "d1"},
        "ghost_assignments": {},
    })


def scenario_the_override_outranks_every_planned_signal():
    """Precedence: the person in the car beats the rule written last month,
    which beats the split default. And absent an override, nothing planned
    changes: stay beats split beats the 2-hour line."""
    import main
    d = main._attendance_decision
    # The day-of word is final, both directions, against everything.
    check(d('split', True, False, 600) is True,
          "a not-staying declaration beats a #stay plan on a short event")
    check(d('stay', False, True, 3 * 3600) is False,
          "a staying declaration beats a split rule on a long event")
    # No override: the planned order is untouched.
    check(d(None, True, True, 3 * 3600) is False, "stay still beats split")
    check(d(None, False, True, 600) is True, "a split plan splits")
    check(d(None, False, False, 7200) is True, "two hours is the default line")
    check(d(None, False, False, 7199) is False, "a shade under stays whole")


def scenario_a_driver_who_is_attending_is_staying():
    """Marking a driver as attending an event is a statement that they will
    be AT it, so the two-hour line -- a guess about whether anybody waits in
    a parking lot -- no longer has to be guessed. It ranks below the explicit
    split signals on purpose: one parent can be at the game while another
    drops the kid off, and "Drop off and Pick up" on the event says so."""
    import main
    d = main._attendance_decision
    check(d(None, False, False, 3 * 3600) is True,
          "the two-hour default no longer splits a long event")
    check(d(None, False, False, 3 * 3600, driver_attending=True) is False,
          "a driver marked as attending a long event still has it split")
    check(d(None, False, True, 3 * 3600, driver_attending=True) is True,
          "an explicit split no longer outranks attendance")
    check(d('split', False, False, 600, driver_attending=True) is True,
          "the day-of declaration stopped outranking attendance")
    check(d(None, True, False, 600, driver_attending=True) is False,
          "stay and attending disagree, which they cannot")


def _solve_one_day(config, hours=3):
    """Seed a household with one event and actually solve the day. Returns
    the cached schedule. The calendar is the only outside thing and it is
    stubbed; everything else is the real refresh."""
    import datetime
    import main
    from services import calendar as cal_svc
    from models.schemas import Event
    for t in ('drivers_table', 'passengers_table', 'members_table',
              'daily_schedules_table', 'custom_schedules_table',
              'settings_table', 'event_configs_table', 'rules_table',
              'overrides_table'):
        tbl = getattr(storage, t, None)
        if tbl is not None:
            tbl.truncate()
    storage.settings_table.insert({'calendar_ids': ['cal_house'],
                                   'days_to_build': 1,
                                   'home_location': '1 Home St'})
    storage.add_driver({'id': 'd1', 'name': 'Jeff', 'color_code': '#3b82f6',
                        'group': 'primary', 'priority_index': 1,
                        'calendar_ids': [], 'home_location': '1 Home St'})
    storage.add_passenger({'id': 'p1', 'name': 'Lily',
                           'calendar_ids': ['cal_lily'], 'hashtags': []})
    storage.add_member({'id': 'm1', 'name': 'Lily', 'role': 'child',
                        'passenger_id': 'p1'})
    storage.event_configs_table.insert(dict(config, google_id='gev1'))

    start = datetime.datetime.combine(TODAY, datetime.time(16, 0))
    proto = dict(id='gev1', title='Soccer practice', start=start,
                 end=start + datetime.timedelta(hours=hours),
                 location='9 Rec Center Rd', description='',
                 calendar_ids=['cal_lily'], source_event_ids=['gev1'])
    real = cal_svc.fetch_upcoming_events
    try:
        cal_svc.fetch_upcoming_events = lambda *a, **k: [Event(**proto)]
        res = main.refresh_schedule_logic(TODAY.isoformat(), TODAY.isoformat(),
                                          force_refresh=True)
    finally:
        cal_svc.fetch_upcoming_events = real
    check(not res.get('error'), "the day did not solve: %s" % res.get('error'))
    return res


def scenario_the_attended_event_gets_the_drive_not_a_phantom():
    """The bug this pins, end to end. A driver marked as attending a
    three-hour event still had it split into Dropoff/Pickup slices; the drive
    legs attached to the SLICES, and the event itself -- the block carrying
    its real name -- drew with no drive to it at all. Marking somebody as
    attending made the schedule worse than leaving it alone."""
    got = _solve_one_day({'passenger_ids': ['p1'], 'driver_ids': ['d1']})
    ids = [e['id'] if isinstance(e, dict) else e.id for e in got.get('events', [])]
    check('gev1_dropoff' not in ids and 'gev1_pickup' not in ids,
          "an event its driver is attending was still split: %s" % ids)
    check(got.get('assignments', {}).get('gev1') == 'd1',
          "the attended event is not the thing that got assigned")
    legs = (got.get('initial_edges', {}) or {}).get('d1', {})
    check('gev1' in legs and legs['gev1'].get('travel_mins', 0) > 0,
          "there is still no driving leg TO the event: %s" % legs)


def scenario_an_explicit_split_still_beats_attendance():
    """One parent at the game, another dropping the kid off. Saying "Drop off
    and Pick up" on the event is how a family says so, and attendance must
    not quietly overrule it."""
    got = _solve_one_day({'passenger_ids': ['p1'], 'driver_ids': ['d1'],
                          'driver_attendance_mode': 'dropoff_pickup'})
    ids = [e['id'] if isinstance(e, dict) else e.id for e in got.get('events', [])]
    check('gev1_dropoff' in ids and 'gev1_pickup' in ids,
          "an explicit Drop off and Pick up was overruled by attendance: %s" % ids)


def scenario_the_attendance_mode_dropdown_is_actually_read():
    """It was saved by both config editors and read by NOTHING — "Stay for
    entire event" was a control that did nothing at all. A dead control is
    worse than a missing one: the family believes they have said something."""
    ids = lambda got: [e['id'] if isinstance(e, dict) else e.id
                       for e in got.get('events', [])]
    stayed = _solve_one_day({'passenger_ids': ['p1'],
                             'driver_attendance_mode': 'stay'})
    check('gev1_dropoff' not in ids(stayed),
          "Stay for entire event still splits: %s" % ids(stayed))
    split = _solve_one_day({'passenger_ids': ['p1'],
                            'driver_attendance_mode': 'dropoff_pickup'},
                           hours=1)
    check('gev1_dropoff' in ids(split),
          "Drop off and Pick up does not split a short event: %s" % ids(split))
    plain = _solve_one_day({'passenger_ids': ['p1']}, hours=1)
    check('gev1_dropoff' not in ids(plain),
          "the scheduler's own decision changed: %s" % ids(plain))


def scenario_overrides_expire_on_their_own():
    _reset()
    storage.set_attendance_override('art', 'split')
    check(storage.get_attendance_overrides().get('art', {}).get('action') == 'split',
          "a fresh override reads back")
    rows = dict(storage.get_app_state('attendance_overrides'))
    rows['art']['ts'] = time.time() - storage._ATTENDANCE_TTL_SECS - 60
    storage.set_app_state('attendance_overrides', rows)
    check('art' not in storage.get_attendance_overrides(),
          "a two-day-old declaration is gone — today's mood must not "
          "reshape next week's recurrence")


def scenario_not_staying_pins_the_slices_and_carries_the_history():
    _reset()
    import main
    from fastapi import BackgroundTasks
    # The inbound drive already happened, with the ETA machinery's fields.
    storage.mark_drive_status('init_art', 'completed',
                              eta_ts=123.0, arrived_ts=456.0)
    main.set_event_attendance('art', main.AttendanceAction(action='split'),
                              BackgroundTasks())
    check(storage.get_attendance_overrides()['art']['action'] == 'split',
          "the declaration is stored for the next solve")
    pins = {o['event_id']: o for o in storage.get_all_overrides()}
    check(pins.get('art_dropoff', {}).get('driver_id') == 'd1'
          and pins.get('art_pickup', {}).get('driver_id') == 'd1',
          f"both slices pin to the driver already on the event: {pins}")
    check(pins['art_pickup'].get('source') == 'retro_split',
          "the pin says where it came from")
    mirrored = storage.get_drive_status('init_art_dropoff')
    check(mirrored and mirrored['status'] == 'completed'
          and mirrored.get('eta_ts') == 123.0
          and mirrored.get('arrived_ts') == 456.0,
          f"the finished drive survives the rename, fields and all: {mirrored}")
    check(storage.get_drive_status('init_art'),
          "copied, never moved — the old schedule may still be on a screen")


def scenario_staying_after_all_undoes_only_its_own_pins():
    _reset()
    import main
    from fastapi import BackgroundTasks
    # Somebody's deliberate manual override on the BASE event predates this.
    storage.add_override({'id': 'x1', 'event_id': 'art', 'driver_id': 'd2',
                          'created_at': time.time()})
    main.set_event_attendance('art', main.AttendanceAction(action='split'),
                              BackgroundTasks())
    storage.mark_drive_status('init_art_dropoff', 'completed', eta_ts=99.0)
    main.set_event_attendance('art', main.AttendanceAction(action='stay'),
                              BackgroundTasks())
    check(storage.get_attendance_overrides()['art']['action'] == 'stay',
          "the undo is stored")
    remaining = {o['event_id'] for o in storage.get_all_overrides()}
    check('art_dropoff' not in remaining and 'art_pickup' not in remaining,
          f"the slice pins are gone: {remaining}")
    check('art' in remaining,
          "the base event's manual override is NOT this endpoint's to remove")
    back = storage.get_drive_status('init_art')
    check(back and back['status'] == 'completed' and back.get('eta_ts') == 99.0,
          f"history mirrors back to the unsplit leg: {back}")


def scenario_a_ghost_driver_is_never_pinned():
    _reset()
    import main
    from fastapi import BackgroundTasks
    sched = storage.get_cached_schedule()
    sched['assignments'] = {}
    sched['ghost_assignments'] = {'art': 'ghost_1'}
    storage.set_cached_schedule(sched)
    main.set_event_attendance('art', main.AttendanceAction(action='split'),
                              BackgroundTasks())
    check(storage.get_attendance_overrides()['art']['action'] == 'split',
          "the split still happens — the solver decides who drives")
    check(not storage.get_all_overrides(),
          "a ghost is a gap, not a person; pinning one would freeze the gap")


def scenario_unknown_event_and_bad_action_refuse():
    _reset()
    import main
    from fastapi import BackgroundTasks, HTTPException
    try:
        main.set_event_attendance('nothing', main.AttendanceAction(action='split'),
                                  BackgroundTasks())
        check(False, "an event not on the schedule should 404")
    except HTTPException as e:
        check(e.status_code == 404, f"expected 404, got {e.status_code}")
    try:
        main.set_event_attendance('art', main.AttendanceAction(action='maybe'),
                                  BackgroundTasks())
        check(False, "an unknown action should 400")
    except HTTPException as e:
        check(e.status_code == 400, f"expected 400, got {e.status_code}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} attendance-override scenarios passed")


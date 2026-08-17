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


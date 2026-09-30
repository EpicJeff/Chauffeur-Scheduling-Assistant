"""One departure, one margin, every surface.

User report (2026-09-29): "The times should be the same across every surface.
If there's a 5 minute buffer being added, it should be coming from a single
unified setting that can be adjusted by the user."

There were four copies of the departure arithmetic: the PWA Drives list, the
desktop Schedule timeline, the Time-to-leave push builder in main.py, and
services/leave_by (the heroes, the drive sheet, the kid's leave-by). Three of
them added a literal 5 and one did not; the pushes and the Drives list even
disagreed about when you leave one event for the next.

Pinned here by RUNNING each path over one schedule:
  * `leave_by.stamp` puts per-leg departures on every edge the API serves;
  * the hero (`for_run`) says the same time as the stamped leg it leaves on;
  * every push fires at a stamped departure;
  * `leave_margin_mins` moves every from-home departure together and nothing
    else, and it is clamped;
  * saving a new margin marks the day caches for a re-solve (the solver's
    go-home-in-between decision uses the same margin).

Run from chauffeur/:  python tests/test_leave_margin.py
"""
import datetime

from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)

from services import leave_by, storage

TODAY = datetime.date.today()


def at(h, m=0):
    return datetime.datetime.combine(TODAY, datetime.time(h, m))


def _sched():
    """One driver's day: a first drive from home, a layover at home, a
    straight-on hop through a pickup, a direct hop, and the drive home."""
    ev = lambda i, s, e, loc: {'id': i, 'title': i, 'location': loc,
                               'start': s.isoformat(), 'end': e.isoformat()}
    return {
        'events': [ev('school', at(8), at(9), 'school'),
                   ev('swim', at(12), at(13), 'pool'),
                   ev('art', at(13, 30), at(14, 30), 'studio'),
                   ev('music', at(15), at(16), 'hall')],
        'assignments': {'school': 'd1', 'swim': 'd1', 'art': 'd1', 'music': 'd1'},
        'initial_edges': {'d1': {'school': {'to_event': 'school', 'travel_mins': 15,
                                            'buffer_before_mins': 10,
                                            'driver_home_location': 'home'}}},
        'route_edges': {'d1': {
            'school': {'to_event': 'swim', 'travel_mins': 30,
                       'home_waypoint': {'to_home_mins': 15, 'from_home_mins': 15,
                                         'layover_mins': 145,
                                         'driver_home_location': 'home'}},
            'swim': {'to_event': 'art', 'travel_mins': 18,
                     'pickup_waypoint': {'to_pickup_mins': 8, 'from_pickup_mins': 10,
                                         'pickup_location': 'friend'}},
            'art': {'to_event': 'music', 'travel_mins': 12, 'buffer_after_mins': 5},
        }},
        'final_edges': {'d1': {'music': {'from_event': 'music', 'travel_mins': 20}}},
    }


def _hhmm(dt):
    return dt.strftime('%H:%M') if isinstance(dt, datetime.datetime) else \
        datetime.datetime.fromisoformat(dt).strftime('%H:%M')


def scenario_the_margin_is_one_clamped_setting():
    check(leave_by.margin_mins({}) == 5, 'default is 5')
    check(leave_by.margin_mins({'leave_margin_mins': 12}) == 12, 'it is read')
    check(leave_by.margin_mins({'leave_margin_mins': -3}) == 0, 'never negative')
    check(leave_by.margin_mins({'leave_margin_mins': 500}) == 60, 'capped at an hour')
    check(leave_by.margin_mins({'leave_margin_mins': 'x'}) == 5, 'junk reads as default')


def scenario_every_leg_is_stamped_by_the_one_rule():
    s = leave_by.stamp(_sched(), margin=5)
    check(s['leave_margin_mins'] == 5, 'the margin rides along for the pages')
    legs = lambda kind, key: [(_hhmm(l['depart']), l['mins'])
                              for l in s[kind]['d1'][key]['legs']]
    check(legs('initial_edges', 'school') == [('07:30', 15)],
          f"8:00 − 15 drive − 10 buffer − 5 margin: {legs('initial_edges', 'school')}")
    check(legs('route_edges', 'school') == [('09:00', 15), ('11:40', 15)],
          f"home when school ends; out again at 12:00 − 15 − 5: "
          f"{legs('route_edges', 'school')}")
    check(legs('route_edges', 'swim') == [('13:00', 8), ('13:08', 10)],
          f"straight on from swim through the pickup: {legs('route_edges', 'swim')}")
    check(legs('route_edges', 'art') == [('14:35', 12)],
          f"leave art when it ends (+5 after-buffer): {legs('route_edges', 'art')}")
    check(legs('final_edges', 'music') == [('16:00', 20)],
          f"home when music ends: {legs('final_edges', 'music')}")


def scenario_the_hero_says_the_stamped_time():
    sched = leave_by.stamp(_sched(), margin=5)
    for ev_id, start, leg in (('school', at(8), sched['initial_edges']['d1']['school']['legs'][0]),
                              ('swim', at(12), sched['route_edges']['d1']['school']['legs'][1]),
                              ('art', at(13, 30), sched['route_edges']['d1']['swim']['legs'][0]),
                              ('music', at(15), sched['route_edges']['d1']['art']['legs'][0])):
        run = leave_by.for_run(sched, 'd1', ev_id, start)
        check(run and _hhmm(run['leave_at']) == _hhmm(leg['depart']),
              f"{ev_id}: hero {run and run['leave_at']} vs stamped {leg['depart']}")


def scenario_every_push_fires_at_a_stamped_time():
    import main
    from models.schemas import Event
    sched = _sched()
    stamped = leave_by.stamp(_sched(), margin=leave_by.margin_mins())
    events = {e['id']: Event(id=e['id'], title=e['title'], location=e['location'],
                             start=datetime.datetime.fromisoformat(e['start']),
                             end=datetime.datetime.fromisoformat(e['end']),
                             calendar_ids=[], source_event_ids=[e['id']])
              for e in sched['events']}
    now_ts = at(0, 1).timestamp()
    pushes = main._departure_notifications(sched, events, {'home_location': 'home'},
                                           now_ts, set())
    got = {p['notif_id']: _hhmm(datetime.datetime.fromtimestamp(p['trigger_timestamp']))
           for p in pushes}
    want = {
        'init_school': '07:30',
        'route_school_swim_1': '09:00', 'route_school_swim_2': '11:40',
        'route_swim_art_1': '13:00', 'route_swim_art_2': '13:08',
        'route_art_music': '14:35',
        'final_music': '16:00',
    }
    check(got == want, f"pushes fire at the stamped departures:\n got {got}\nwant {want}")
    stamped_times = {_hhmm(l['depart'])
                     for kind in ('initial_edges', 'route_edges', 'final_edges')
                     for e in stamped[kind]['d1'].values() for l in e['legs']}
    check(set(got.values()) <= stamped_times, 'no push time the stamp does not know')
    home_only = {p['notif_id'] for p in pushes if p.get('origin')}
    check(home_only == {'init_school', 'route_school_swim_2'},
          f"only departures from home carry a route for the traffic sweep: {home_only}")


def scenario_the_margin_moves_every_home_departure_and_nothing_else():
    five = leave_by.stamp(_sched(), margin=5)
    twelve = leave_by.stamp(_sched(), margin=12)
    pairs = lambda s: [(kind, key, i, _hhmm(l['depart']))
                       for kind in ('initial_edges', 'route_edges', 'final_edges')
                       for key, e in s[kind]['d1'].items()
                       for i, l in enumerate(e['legs'])]
    moved = [(a[:3], a[3], b[3]) for a, b in zip(pairs(five), pairs(twelve)) if a[3] != b[3]]
    check([m[0] for m in moved] == [('initial_edges', 'school', 0),
                                    ('route_edges', 'school', 1)],
          f"only the two departures from home move: {moved}")
    check(all(m[1] == '07:30' or m[1] == '11:40' for m in moved)
          and [m[2] for m in moved] == ['07:23', '11:33'],
          f"each 7 minutes earlier: {moved}")


def scenario_saving_the_margin_resolves_the_days():
    import main
    from fastapi import BackgroundTasks
    from models.schemas import Settings
    storage.update_settings({'leave_margin_mins': 5})
    storage.daily_schedules_table.truncate()
    storage.daily_schedules_table.insert({'date': TODAY.isoformat(),
                                          'events_hash': 'abc', 'schedule': {}})
    orig = main.trigger_background_refresh
    main.trigger_background_refresh = lambda *a, **k: None
    try:
        main.update_settings(Settings(leave_margin_mins=9), BackgroundTasks())
        # (harness stubs get_settings, so read what was stored)
        stored = lambda: storage.settings_table.all()[0].get('leave_margin_mins')
        check(stored() == 9, 'saved')
        check(storage.daily_schedules_table.all()[0]['events_hash'] == 'DIRTY',
              "a new margin re-solves the days (the go-home decision uses it)")
        main.update_settings(Settings(leave_margin_mins=900), BackgroundTasks())
        check(stored() == 60,
              'clamped on the way in')
    finally:
        main.trigger_background_refresh = orig


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} leave-margin scenarios passed")

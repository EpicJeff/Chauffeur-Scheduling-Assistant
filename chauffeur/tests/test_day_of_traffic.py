"""Day-of traffic (v2.165.0): static plans, re-priced on the day they run.

The static Matrix stays the solver's planning baseline (free-flow, bought
once per pair). On the day itself two scheduled buys per driving leg — a
predictive morning pass and a live refine an hour before departure — feed a
date-scoped cache that every leave-saying surface reads. Tested at the seams:

  - the cache answers only for TODAY (yesterday's rush hour must not shade
    tomorrow morning's plan)
  - the leave-by overlay moves departures EARLIER only, today only, and reads
    the cache only (a wall panel polling every 60s must never become API calls)
  - the push trigger fires early by exactly the traffic delta, never late
  - the sweep buys each leg at most twice a day, markers set BEFORE fetching,
    so the refetch storm that once burned the Matrix quota is structurally
    impossible here

Run from chauffeur/:  python tests/test_day_of_traffic.py
"""
import datetime
import os
import time

from tinydb import Query

from harness import check
from services import storage, maps, leave_by


def _reset():
    with storage.db_lock:
        storage.live_traffic_table.truncate()
    storage.set_app_state('traffic_sweep_done_v2', None)
    maps._last_sweep_ts = 0.0
    # No network in tests: an ungeocodable address falls back to the raw
    # string as its own cache key, so writes and reads still meet.
    maps.geocode_address = lambda addr: None


def scenario_the_cache_answers_only_for_today():
    _reset()
    storage.set_cached_day_of_traffic('home', 'apex gym', 28, 'refine')
    row = storage.get_cached_day_of_traffic('home', 'apex gym')
    check(row and row['duration_mins'] == 28 and row['stage'] == 'refine',
          f"a same-day row reads back, got {row}")
    with storage.db_lock:
        storage.live_traffic_table.update(
            {'timestamp': time.time() - 86400 - 3600},
            (Query().origin == 'home') & (Query().destination == 'apex gym'))
    check(storage.get_cached_day_of_traffic('home', 'apex gym') is None,
          "yesterday's rush hour never shades today — the date is part of "
          "the validity check, not an age window")


def scenario_the_overlay_moves_the_leave_time_earlier_only():
    _reset()
    real_settings = storage.get_settings
    real_drivers = storage.get_all_drivers
    storage.get_settings = lambda: {'home_location': 'home'}
    storage.get_all_drivers = lambda: []
    try:
        today = datetime.date.today()
        now = datetime.datetime.combine(today, datetime.time(12, 0))
        start = datetime.datetime.combine(today, datetime.time(17, 0))
        sched = {'initial_edges': {'d1': {'ev1': {'travel_mins': 17,
                                                  'buffer_before_mins': 5}}},
                 'events': [{'id': 'ev1', 'location': 'apex gym'}]}

        base = leave_by.for_run(sched, 'd1', 'ev1', start, live=True, now=now)
        check(base['travel_mins'] == 17 and 'traffic_delay_mins' not in base,
              f"no day-of row: the static plan stands, got {base}")

        storage.set_cached_day_of_traffic('home', 'apex gym', 28, 'morning')
        live = leave_by.for_run(sched, 'd1', 'ev1', start, live=True, now=now)
        check(live['travel_mins'] == 28 and live['traffic_delay_mins'] == 11
              and live['leave_label'] == '4:27 PM',
              f"the 5pm drive re-prices to 28 and leaves 11 min earlier, got {live}")

        static = leave_by.for_run(sched, 'd1', 'ev1', start, live=False, now=now)
        check(static['travel_mins'] == 17,
              "without the flag (the solver, another day's view) nothing moves")

        storage.set_cached_day_of_traffic('home', 'apex gym', 12, 'refine')
        light = leave_by.for_run(sched, 'd1', 'ev1', start, live=True, now=now)
        check(light['travel_mins'] == 17 and 'traffic_delay_mins' not in light,
              "light traffic never delays a departure someone may be acting on")

        storage.set_cached_day_of_traffic('home', 'apex gym', 28, 'refine')
        tomorrow = start + datetime.timedelta(days=1)
        tmrw = leave_by.for_run(sched, 'd1', 'ev1', tomorrow, live=True, now=now)
        check(tmrw['travel_mins'] == 17,
              "tomorrow's digest must not read today's rush hour — the "
              "overlay refuses other days even when asked")

        # A route edge's origin is the event the driver leaves FROM.
        sched2 = {'route_edges': {'d1': {'evA': {'to_event': 'ev2',
                                                 'travel_mins': 10}}},
                  'events': [{'id': 'evA', 'location': 'school'},
                             {'id': 'ev2', 'location': 'apex gym'}]}
        storage.set_cached_day_of_traffic('school', 'apex gym', 25, 'refine')
        chained = leave_by.for_run(sched2, 'd1', 'ev2', start, live=True, now=now)
        check(chained['travel_mins'] == 25 and chained['traffic_delay_mins'] == 15,
              f"a chained leg re-prices from its real origin, got {chained}")
    finally:
        storage.get_settings = real_settings
        storage.get_all_drivers = real_drivers


def scenario_an_offset_carrying_start_does_not_take_my_day_down():
    """Google calendar ISO stamps carry an offset, so member_day's
    `fromisoformat` hands for_run an AWARE start while the overlay's `now`
    is naive — which raised TypeError and 500'd /api/members/{id}/day for
    every kid whose first ride had one. Wall-clock convention: strip, never
    convert."""
    _reset()
    real_settings = storage.get_settings
    real_drivers = storage.get_all_drivers
    storage.get_settings = lambda: {'home_location': 'home'}
    storage.get_all_drivers = lambda: []
    try:
        today = datetime.date.today()
        now = datetime.datetime.combine(today, datetime.time(12, 0))
        tz = datetime.timezone(datetime.timedelta(hours=-4))
        aware_start = datetime.datetime.combine(
            today, datetime.time(17, 0)).replace(tzinfo=tz)
        sched = {'initial_edges': {'d1': {'ev1': {'travel_mins': 17,
                                                  'buffer_before_mins': 5}}},
                 'events': [{'id': 'ev1', 'location': 'apex gym'}]}
        storage.set_cached_day_of_traffic('home', 'apex gym', 28, 'refine')

        live = leave_by.for_run(sched, 'd1', 'ev1', aware_start,
                                live=True, now=now)
        check(live and live['travel_mins'] == 28,
              f"an aware start reads as its wall-clock time, no raise: {live}")
        check(live['leave_label'] == '4:27 PM',
              f"and the departure is the same 4:27 the naive path says: {live}")

        aware_now = now.replace(tzinfo=tz)
        both = leave_by.for_run(sched, 'd1', 'ev1', aware_start,
                                live=True, now=aware_now)
        check(both and both['travel_mins'] == 28,
              "an aware now is stripped the same way")
    finally:
        storage.get_settings = real_settings
        storage.get_all_drivers = real_drivers


def scenario_the_push_fires_early_by_the_delta():
    _reset()
    trigger = time.time() + 1800
    notif = {'trigger_timestamp': trigger, 'origin': 'home',
             'destination': 'apex gym', 'travel_static_mins': 17}
    check(maps.live_adjusted_trigger(notif) == trigger,
          "no day-of row: the planned trigger stands")
    storage.set_cached_day_of_traffic('home', 'apex gym', 28, 'refine')
    adj = maps.live_adjusted_trigger(notif)
    check(abs((trigger - adj) - 11 * 60) < 1,
          f"a +11 traffic day fires the push 11 minutes early, got {trigger - adj}s")
    storage.set_cached_day_of_traffic('home', 'apex gym', 12, 'refine')
    check(maps.live_adjusted_trigger(notif) == trigger,
          "light traffic never delays a push — earlier only")
    check(maps.live_adjusted_trigger({'trigger_timestamp': trigger}) == trigger,
          "a push with no route (end-anchored 'Drive Home') is untouched")


def scenario_the_sweep_buys_each_leg_at_most_twice_a_day():
    _reset()
    real_settings = storage.get_settings
    real_fetch = maps.fetch_traffic_minutes
    calls = []

    def fake_fetch(origin, destination, depart_at_ts=None, stage='refine'):
        calls.append((origin, destination, stage,
                      bool(depart_at_ts)))
        return 28

    # Midnight, so the morning branch is due whatever hour the suite runs at.
    # This ALSO pins the absent-vs-zero rule in run_day_of_traffic_sweep: the
    # old `or 6` ate the zero, so a household that set midnight silently got
    # six o'clock — and this scenario only passed when the suite ran after 6am.
    storage.get_settings = lambda: {'traffic_morning_hour': 0}
    maps.fetch_traffic_minutes = fake_fetch
    try:
        now = time.time()
        trigger = now + 60          # imminent: morning AND refine both due
        storage.save_pending_notifications([{
            'notif_id': 'init_ev1', 'driver_id': 'd1',
            'trigger_timestamp': trigger, 'title': 'Time to Leave!',
            'body': 'Drive to Gym', 'location': 'apex gym',
            'origin': 'home', 'destination': 'apex gym',
            'travel_static_mins': 17, 'fired': False,
        }, {
            # End-anchored pushes carry no route and must never be bought.
            'notif_id': 'final_ev1', 'driver_id': 'd1',
            'trigger_timestamp': trigger, 'title': 'Time to Leave!',
            'body': 'Drive Home', 'location': 'home', 'fired': False,
        }])
        res = maps.run_day_of_traffic_sweep(now)
        check(res.get('fetched') == 2 and len(calls) == 2,
              f"one morning buy (predictive) + one refine (live), got {calls}")
        check(calls[0][2] == 'morning' and calls[0][3] is True,
              "the morning pass asks for PREDICTIVE traffic (depart_at)")
        check(calls[1][2] == 'refine' and calls[1][3] is False,
              "the refine asks for live traffic, no depart_at")

        maps._last_sweep_ts = 0.0
        maps.run_day_of_traffic_sweep(now + 300)
        check(len(calls) == 2,
              "markers make a refetch structurally impossible — the refetch "
              "storm is what actually burned the old Matrix quota")

        maps._last_sweep_ts = 0.0
        storage.get_settings = lambda: {'traffic_live_enabled': False,
                                        'traffic_morning_hour': 0}
        storage.set_app_state('traffic_sweep_done', None)
        res = maps.run_day_of_traffic_sweep(now + 600)
        check(res.get('skipped') == 'disabled' and len(calls) == 2,
              "the kill switch stops the sweep cold")
    finally:
        storage.get_settings = real_settings
        maps.fetch_traffic_minutes = real_fetch
        storage.save_pending_notifications([])


def scenario_any_spelling_of_the_same_place_finds_the_row():
    """Caught live on day one: the sweep stored under the solver edge's
    spelling ('…Apex, NC, USA') while the overlay and the debug endpoint
    looked up with the settings spelling ('…Apex, North Carolina 27523,
    United States') — same house, different strings, every read a miss. The
    cache is coordinate-keyed now (four decimals, the same building), with
    the raw string only as an ungeocodable fallback."""
    _reset()
    home_coords = (35.780458, -78.915698)
    gym_coords = (35.687847, -78.833321)

    def fake_geocode(addr):
        a = (addr or '').lower()
        if 'chestnut' in a:
            return home_coords
        if 'williams' in a:
            return gym_coords
        return None

    maps.geocode_address = fake_geocode
    key_a = maps._traffic_cache_key('265 Chestnut Walk Drive, Apex, NC, USA')
    key_b = maps._traffic_cache_key(
        '265 Chestnut Walk Drive, Apex, North Carolina 27523, United States')
    check(key_a == key_b == '35.7805,-78.9157',
          f"two spellings of one house share a key, got {key_a} / {key_b}")
    storage.set_cached_day_of_traffic(
        key_a, maps._traffic_cache_key('2161 E Williams St, Apex, NC 27539'),
        28, 'refine')
    row = maps.get_day_of_traffic(
        '265 Chestnut Walk Drive, Apex, North Carolina 27523, United States',
        '2161 East Williams Street, Apex, North Carolina 27539, United States')
    check(row and row['duration_mins'] == 28,
          f"a row bought under one spelling reads back under another, got {row}")


def scenario_every_surface_is_wired():
    """Source contracts: the pieces that must not quietly regress."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main_src = open(os.path.join(root, 'main.py'), encoding='utf-8').read()
    check(main_src.count('travel_static_mins') >= 3,
          "push generation no longer records each leg's route + static "
          "minutes — the sweep and the early-fire both starve without them")
    check('run_day_of_traffic_sweep' in main_src
          and 'live_adjusted_trigger' in main_src,
          "the push loop must run the sweep and fire on the adjusted time")
    board = open(os.path.join(root, 'services', 'home_board.py'),
                 encoding='utf-8').read()
    check('live=True' in board, "the board's runs no longer opt into day-of times")
    hero = open(os.path.join(root, 'templates', 'components', 'hero_card.html'),
                encoding='utf-8').read()
    check(hero.count('traffic_delay_mins') >= 2,
          "both hero variants must say WHY the leave time moved (+N traffic)")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} day-of traffic scenarios passed")

"""Tests for the kid evening digest (kid-support arc K1).

Load-bearing properties: the builder reuses My Day's ride resolution (calendar
binding, split-leg collapse, per-leg drivers), prep items ride the lines,
kids with nothing are omitted entirely (nothing means nothing), an unassigned
ride never alarms the kid with a missing-driver phrase, kid quiet hours gate
all kid-facing sends, and DM delivery posts one Argyle DM per child.

Run from chauffeur/:  python tests/test_kid_digest.py
"""
import datetime
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage, family_digest

TODAY = datetime.date.today()
TOMORROW = TODAY + datetime.timedelta(days=1)


def _reset():
    import main  # noqa: F401  (route handlers reused by the builder)
    for t in (storage.members_table, storage.passengers_table, storage.cache_table,
              storage.routines_table, storage.routine_checks_table,
              storage.prep_kits_table, storage.chat_channels_table,
              storage.chat_messages_table):
        t.truncate()
    storage.get_settings = lambda: {"calendar_ids": ["primary"]}
    storage.add_member({"id": "dadm", "name": "Dad", "role": "parent", "driver_id": "d1"})
    storage.add_member({"id": "momm", "name": "Mom", "role": "parent", "driver_id": "d2"})
    storage.add_member({"id": "kid1", "name": "Addison", "role": "child",
                        "is_child": True, "passenger_id": "p1", "avatar": "🦊"})
    storage.add_member({"id": "kid2", "name": "Ben", "role": "child",
                        "is_child": True, "passenger_id": "p2"})
    with storage.db_lock:
        storage.passengers_table.insert({"id": "p1", "name": "Addison",
                                         "calendar_ids": ["cal1"], "hashtags": []})
        storage.passengers_table.insert({"id": "p2", "name": "Ben",
                                         "calendar_ids": ["cal2"], "hashtags": []})


def _seed_cache():
    day = TOMORROW.isoformat()
    storage.set_cached_schedule({
        "events": [
            {"id": "swim", "title": "Swim Practice", "start": f"{day}T08:00:00",
             "end": f"{day}T09:00:00", "calendar_ids": ["cal1"]},
            # split event: Dad drops off, Mom picks up
            {"id": "party", "title": "Birthday Party", "start": f"{day}T14:00:00",
             "end": f"{day}T16:00:00", "calendar_ids": ["cal1"]},
            {"id": "party_dropoff", "title": "Birthday Party", "start": f"{day}T14:00:00",
             "end": f"{day}T14:10:00", "calendar_ids": ["cal1"], "event_type": "dropoff"},
            {"id": "party_pickup", "title": "Birthday Party", "start": f"{day}T16:00:00",
             "end": f"{day}T16:10:00", "calendar_ids": ["cal1"], "event_type": "pickup"},
            # unassigned ride: must appear WITHOUT a driver phrase
            {"id": "piano", "title": "Piano Lesson", "start": f"{day}T17:00:00",
             "end": f"{day}T18:00:00", "calendar_ids": ["cal1"]},
        ],
        "assignments": {"swim": "d1", "party_dropoff": "d1", "party_pickup": "d2"},
        "ghost_assignments": {},
        "matched_rules": {},
        "scheduled_errands": [],
    })
    with storage.db_lock:
        storage.prep_kits_table.insert({"id": "k1", "name": "Swim Kit", "enabled": True,
                                        "keywords": ["swim"], "items": ["Goggles", "Towel"]})


def scenario_builder_rides_and_reassurance():
    _reset()
    _seed_cache()
    import main
    with mock.patch.object(family_digest, 'weather_line', return_value="☀️ 75°"):
        digest = main._build_kid_digests()
    check(digest["label"] == "Tomorrow" and digest["weather"] == "☀️ 75°",
          "default day is tomorrow with its label + weather")
    check(list(digest["kids"].keys()) == ["kid1"],
          f"Ben has nothing tomorrow -> omitted entirely, got {list(digest['kids'])}")
    k = digest["kids"]["kid1"]
    check(k["count"] == 3, f"three rides, got {k}")
    check("8:00 AM – Swim Practice — 🚗 Dad is driving you (bring: Goggles, Towel)" == k["lines"][0],
          f"ride line: time, driver reassurance, prep items — got {k['lines'][0]}")
    check("Dad takes you, Mom brings you home" in k["lines"][1],
          f"split legs with different drivers phrase both, got {k['lines'][1]}")
    check("Piano Lesson" in k["lines"][2] and "🚗" not in k["lines"][2],
          f"unassigned ride never alarms with a driver phrase, got {k['lines'][2]}")


def scenario_routine_only_kid_included():
    _reset()
    storage.set_cached_schedule({"events": [], "assignments": {}, "matched_rules": {},
                                 "scheduled_errands": []})
    storage.add_routine({"id": "rt1", "member_id": "kid2", "title": "Brush teeth",
                         "days_of_week": [], "time_of_day": None})
    import main
    with mock.patch.object(family_digest, 'weather_line', return_value=None):
        digest = main._build_kid_digests()
    check(list(digest["kids"].keys()) == ["kid2"], "routine-only kid still gets a digest")
    k = digest["kids"]["kid2"]
    check(k["lines"] == [] and k["routine_count"] == 1,
          f"no rides but the routine is visible, got {k}")


def scenario_kid_quiet_hours():
    s = {"kid_quiet_start": "20:30", "kid_quiet_end": "07:00"}
    mk = lambda h, m: datetime.datetime(2026, 8, 3, h, m)
    check(family_digest.in_kid_quiet_hours(mk(21, 0), s), "21:00 is quiet")
    check(family_digest.in_kid_quiet_hours(mk(6, 30), s), "06:30 is quiet (wraps midnight)")
    check(not family_digest.in_kid_quiet_hours(mk(7, 0), s), "07:00 ends the window")
    check(not family_digest.in_kid_quiet_hours(mk(12, 0), s), "noon is not quiet")
    check(not family_digest.in_kid_quiet_hours(mk(19, 45), s), "19:45 is before the window")
    same = {"kid_quiet_start": "08:00", "kid_quiet_end": "08:00"}
    check(not family_digest.in_kid_quiet_hours(mk(8, 0), same), "equal start/end disables")
    daytime = {"kid_quiet_start": "13:00", "kid_quiet_end": "15:00"}
    check(family_digest.in_kid_quiet_hours(mk(14, 0), daytime), "non-wrapping window works")


def scenario_dm_delivery_per_child():
    _reset()
    _seed_cache()
    import main
    from services import agent_tools_v2
    with mock.patch.object(family_digest, 'weather_line', return_value="☀️ 75°"), \
         mock.patch.object(agent_tools_v2, '_post_chat_message') as post:
        main._send_kid_digests()
    check(post.call_count == 1, "one DM per kid with content; Ben (nothing) gets none")
    channel, sender, body = post.call_args.args[:3]
    check(sender.get("id") == "argyle", "sent as Argyle")
    check(channel.get("kind") == "dm" and "kid1" in (channel.get("dm_key") or ""),
          f"posted into the kid's Argyle DM, got {channel}")
    check(body.startswith("🌙 Tomorrow, Addison!"), f"kid-tone header, got {body[:40]}")
    check("☀️ 75°" in body and "Swim Practice" in body, "weather + rides in the body")


def scenario_kiosk_endpoint_dates():
    _reset()
    _seed_cache()
    import main
    with mock.patch.object(family_digest, 'weather_line', return_value=None):
        storage.get_settings = lambda: {"calendar_ids": ["primary"],
                                        "kid_digest_cutover_time": "00:00"}
        check(main.kids_digests()["date"] == TOMORROW.isoformat(),
              "past the cutover the endpoint defaults to tomorrow")
        storage.get_settings = lambda: {"calendar_ids": ["primary"],
                                        "kid_digest_cutover_time": "23:59"}
        check(main.kids_digests()["date"] == TODAY.isoformat(),
              "before the cutover the endpoint defaults to today")
        res_today = main.kids_digests(date="today")
        check(res_today["date"] == TODAY.isoformat() and res_today["label"] == "Today",
              "?date=today builds today's board")
    try:
        main.kids_digests(date="not-a-date")
        check(False, "bad date must 400")
    except Exception as e:
        check(getattr(e, 'status_code', None) == 400, "bad date -> HTTP 400")


def scenario_kiosk_cutover_today_vs_tomorrow():
    import main
    s = {"kid_digest_cutover_time": "19:00"}
    noon = datetime.datetime.combine(TODAY, datetime.time(12, 0))
    evening = datetime.datetime.combine(TODAY, datetime.time(19, 0))
    check(main._kid_digest_default_date(now=noon, settings=s) == TODAY,
          "board shows TODAY during the day")
    check(main._kid_digest_default_date(now=evening, settings=s) == TOMORROW,
          "board flips to TOMORROW at the cutover")
    check(main._kid_digest_default_date(now=noon, settings={"kid_digest_cutover_time": "11:00"}) == TOMORROW,
          "cutover is configurable")
    check(main._kid_digest_default_date(now=noon, settings={"kid_digest_cutover_time": "junk"}) == TODAY,
          "bad setting falls back to 19:00")


def scenario_a_trip_already_under_way_does_not_keep_beginning():
    """Reported from the wall: a camp ending tomorrow announced "Camp Kesem
    begins! 🎉" to both kids.

    A background trip is cut into one event per day, and ONLY for the days
    inside the solve window — the days before it opened were never sliced at
    all. The line read the trip's shape back off those slices, so the earliest
    surviving one looked like day one, every single morning. The slice carries
    the whole trip's span now.
    """
    import main
    start = datetime.datetime.combine(TODAY - datetime.timedelta(days=3),
                                      datetime.time(10, 0))
    end = datetime.datetime.combine(TOMORROW, datetime.time(16, 0))
    ride = {'id': f'camp_slice_{TODAY.isoformat()}', 'title': 'Camp Kesem',
            'start': datetime.datetime.combine(TODAY, datetime.time(0, 0)).isoformat(),
            'end': datetime.datetime.combine(TOMORROW, datetime.time(0, 0)).isoformat(),
            'span_start': start.isoformat(), 'span_end': end.isoformat()}

    today_line = main._kid_trip_line(ride, TODAY)
    check('begins' not in today_line,
          f"a trip three days old announced itself as beginning: {today_line}")
    check('day 4 of 5' in today_line, f"wrong day count: {today_line}")
    check('Coming home' in main._kid_trip_line(ride, TOMORROW),
          "the last day is the day they come home")
    check('begins' in main._kid_trip_line(ride, start.date()),
          "the real first day still gets the fanfare")


def scenario_an_all_day_trip_does_not_come_home_a_day_late():
    """An all-day calendar event ends at midnight of the day AFTER its last
    day. Taken literally that is a trip one day too long, with a homecoming on
    a day nobody is travelling — the slices used to hide this because each was
    already clipped to its own day."""
    import main
    start = datetime.datetime.combine(TODAY, datetime.time(0, 0))
    end = datetime.datetime.combine(TODAY + datetime.timedelta(days=3),
                                    datetime.time(0, 0))
    ride = {'id': 'camp_slice_x', 'title': 'Camp Kesem',
            'start': start.isoformat(), 'end': end.isoformat(),
            'span_start': start.isoformat(), 'span_end': end.isoformat()}
    last_real_day = TODAY + datetime.timedelta(days=2)
    check('3-day' in main._kid_trip_line(ride, TODAY),
          f"got {main._kid_trip_line(ride, TODAY)}")
    check('Coming home' in main._kid_trip_line(ride, last_real_day),
          "the homecoming belongs to the last day actually away")
    check('Coming home' not in main._kid_trip_line(ride, end.date()),
          "an exclusive midnight end invented an extra day of trip")


def scenario_a_cache_with_no_span_never_announces_what_it_cannot_prove():
    """The state a running install is actually in the moment the fix ships:
    every cached slice predates `span_start`, so the code falls back to the
    scan — which is the very thing that was wrong. Shipping a fix that only
    starts working after the next schedule refresh means the family goes on
    reading the bug and being told it was fixed.

    The window is what clips, so a trip whose slices run to the edge of the
    cache cannot be shown to start or end there. "Away" is true whatever the
    real dates turn out to be; "begins!" is a claim about an edge this span
    might not have.
    """
    import main
    day = lambda n: TODAY + datetime.timedelta(days=n)  # noqa: E731

    def slice_ev(date, start_h=0):
        return {'id': f'camp_slice_{date.isoformat()}', 'title': 'Camp Kesem',
                'event_type': 'background_trip',
                'start': datetime.datetime.combine(date, datetime.time(start_h, 0)).isoformat(),
                'end': datetime.datetime.combine(date + datetime.timedelta(days=1),
                                                 datetime.time(0, 0)).isoformat()}

    # A camp that started before the window: its slices reach the first day the
    # cache holds, so the scan cannot see behind them.
    clipped = [slice_ev(TODAY), slice_ev(day(1))]
    storage.set_cached_schedule({'events': clipped})
    line = main._kid_trip_line(clipped[0], TODAY)
    check('begins' not in line, f"an unprovable span still announced a start: {line}")
    check('away' in line.lower(), f"expected an honest away line, got {line}")

    # The END is a separate question from the START, and usually the answerable
    # one: the window clips the past hard, while the far end is only clipped by
    # a trip running past it. On the last morning of camp the fact a kid wants
    # is that they are coming home — not that nobody can prove when they left.
    ending = [slice_ev(TODAY),
              {'id': 'e9', 'title': 'Practice', 'event_type': 'standard',
               'start': datetime.datetime.combine(TOMORROW, datetime.time(17, 0)).isoformat(),
               'end': datetime.datetime.combine(TOMORROW, datetime.time(18, 0)).isoformat()}]
    storage.set_cached_schedule({'events': ending})
    home = main._kid_trip_line(ending[0], TODAY)
    check('Coming home' in home,
          f"the last day of a trip has to say so, got {home}")

    # One day earlier, with the end still provable: count down to the thing
    # they are actually counting, rather than to a day number nobody knows.
    running = [slice_ev(TODAY), slice_ev(day(1)),
               {'id': 'e9', 'title': 'Practice', 'event_type': 'standard',
                'start': datetime.datetime.combine(day(2), datetime.time(17, 0)).isoformat(),
                'end': datetime.datetime.combine(day(2), datetime.time(18, 0)).isoformat()}]
    storage.set_cached_schedule({'events': running})
    mid = main._kid_trip_line(running[0], TODAY)
    check('home tomorrow' in mid, f"expected a countdown to going home, got {mid}")
    check('day' not in mid.lower(),
          f"a day count needs BOTH edges and this span has one: {mid}")

    # The same cache with a day of ordinary schedule on either side: nothing
    # was clipped, so the edges are real and the fanfare is earned.
    bounded = [{'id': 'e1', 'title': 'Practice', 'event_type': 'standard',
                'start': datetime.datetime.combine(day(-1), datetime.time(17, 0)).isoformat(),
                'end': datetime.datetime.combine(day(-1), datetime.time(18, 0)).isoformat()},
               slice_ev(TODAY, start_h=10), slice_ev(day(1)),
               {'id': 'e2', 'title': 'Practice', 'event_type': 'standard',
                'start': datetime.datetime.combine(day(3), datetime.time(17, 0)).isoformat(),
                'end': datetime.datetime.combine(day(3), datetime.time(18, 0)).isoformat()}]
    storage.set_cached_schedule({'events': bounded})
    line2 = main._kid_trip_line(bounded[1], TODAY)
    check('begins' in line2, f"a span with daylight on both sides is real: {line2}")
    storage.set_cached_schedule({'events': []})


SCENARIOS = [
    scenario_a_cache_with_no_span_never_announces_what_it_cannot_prove,
    scenario_a_trip_already_under_way_does_not_keep_beginning,
    scenario_an_all_day_trip_does_not_come_home_a_day_late,
    scenario_builder_rides_and_reassurance,
    scenario_routine_only_kid_included,
    scenario_kid_quiet_hours,
    scenario_dm_delivery_per_child,
    scenario_kiosk_endpoint_dates,
    scenario_kiosk_cutover_today_vs_tomorrow,
]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    raise SystemExit(1 if failed else 0)

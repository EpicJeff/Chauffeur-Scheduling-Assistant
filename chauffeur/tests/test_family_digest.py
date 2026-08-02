"""Tests for the weekly family digest (services/family_digest.py).

Daily snapshots capture per-driver drives/minutes and per-kid activity counts
from the (forward-looking) schedule cache; the weekly build sums snapshots
plus the durable ledgers (points, redemptions, routine checks) and posts as
Argyle. Load-bearing properties: split legs count as ONE kid activity, the
digest is None when there is nothing to report, and posting goes through the
normal family-channel message path.

Run from chauffeur/:  python tests/test_family_digest.py
"""
import datetime

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import family_digest, storage

TODAY = datetime.date.today()


def _reset():
    for t in (storage.members_table, storage.passengers_table, storage.daily_stats_table,
              storage.points_ledger_table, storage.redemptions_table,
              storage.routines_table, storage.routine_checks_table,
              storage.cache_table, storage.chat_channels_table, storage.chat_messages_table):
        t.truncate()


def scenario_record_daily_stats():
    _reset()
    day = TODAY.isoformat()
    storage.add_member({"id": "kid", "name": "Addison", "role": "child",
                        "is_child": True, "passenger_id": "p1"})
    with storage.db_lock:
        storage.passengers_table.insert({"id": "p1", "name": "Addison",
                                         "calendar_ids": ["kidcal"], "hashtags": []})
    storage.set_cached_schedule({
        "events": [
            {"id": "ev1", "title": "Soccer Practice", "start": f"{day}T16:00:00",
             "end": f"{day}T17:00:00", "calendar_ids": ["kidcal"]},
            # split legs of one event: two assignments, ONE kid activity
            {"id": "ev2_dropoff", "title": "Swim Meet", "start": f"{day}T18:00:00",
             "end": f"{day}T18:10:00", "calendar_ids": ["kidcal"], "event_type": "dropoff"},
            {"id": "ev2_pickup", "title": "Swim Meet", "start": f"{day}T19:30:00",
             "end": f"{day}T19:40:00", "calendar_ids": ["kidcal"], "event_type": "pickup"},
            {"id": "ghosted", "title": "Piano", "start": f"{day}T10:00:00",
             "end": f"{day}T11:00:00", "calendar_ids": []},
        ],
        "assignments": {"ev1": "d1", "ev2_dropoff": "d1", "ev2_pickup": "d2",
                        "ghosted": "ghost_1"},
        "matched_rules": {},
        "scheduled_errands": [
            {"title": "Groceries", "start_time": f"{day}T12:00:00", "driver": {"id": "d1"}},
        ],
    })
    row = family_digest.record_daily_stats(day)
    check(row["drivers"]["d1"] == {"drives": 3, "minutes": 70},
          f"d1: 2 event drives (60+10 min) + 1 errand, got {row['drivers'].get('d1')}")
    check(row["drivers"]["d2"]["drives"] == 1, "d2 drove the pickup leg")
    check("ghost_1" not in row["drivers"], "ghost suggestions are not real driving")
    check(row["kids"] == {"kid": 2},
          f"kid did 2 activities — split dropoff/pickup collapse to one, got {row['kids']}")
    # upsert: re-recording the same day replaces, not duplicates
    family_digest.record_daily_stats(day)
    check(len(storage.get_daily_stats([day])) == 1, "same-day re-record upserts one row")


def scenario_build_weekly_digest():
    _reset()
    import time as _t
    day = TODAY.isoformat()
    storage.add_member({"id": "kid", "name": "Addison", "role": "child", "is_child": True})
    storage.add_member({"id": "dadm", "name": "Dad", "role": "parent", "driver_id": "d1"})
    storage.upsert_daily_stats(day, {"date": day, "drivers": {"d1": {"drives": 4, "minutes": 130}},
                                     "kids": {"kid": 3}})
    prev = (TODAY - datetime.timedelta(days=2)).isoformat()
    storage.upsert_daily_stats(prev, {"date": prev, "drivers": {"d1": {"drives": 1, "minutes": 30}},
                                      "kids": {"kid": 1}})
    old = (TODAY - datetime.timedelta(days=30)).isoformat()
    storage.upsert_daily_stats(old, {"date": old, "drivers": {"d1": {"drives": 99, "minutes": 999}},
                                     "kids": {"kid": 99}})
    with storage.db_lock:
        storage.points_ledger_table.insert({"member_id": "kid", "delta": 25, "reason": "chore",
                                            "chore_title": "Dishes", "ts": _t.time()})
        storage.points_ledger_table.insert({"member_id": "kid", "delta": -10, "reason": "redeem",
                                            "ts": _t.time()})   # spends never count as chores
        storage.redemptions_table.insert({"id": "r1", "member_id": "kid", "reward_title": "Movie night",
                                          "cost": 10, "state": "approved", "decided_at": _t.time()})
    storage.add_routine({"id": "rt1", "member_id": "kid", "title": "Brush teeth",
                         "days_of_week": [], "time_of_day": None})
    storage.set_routine_check("rt1", "kid", day, True)

    text = family_digest.build_weekly_digest(end_date=TODAY)
    check(text is not None and text.startswith("📊 Family Week in Review"), "digest built with header")
    check("• Dad — 5 drives · 2h 40m" in text, f"driving sums the week's snapshots only, got: {text}")
    check("• Addison — 4 activities" in text, "kid activities summed across snapshot days")
    check("Chores — 1 verified" in text and "• Addison — +25 pts" in text,
          "chores count earns only, not spends")
    check("• Addison — Movie night" in text, "granted rewards listed")
    check("📋 Routines" in text and "• Addison — 1/" in text, "routine completion line present")
    check("\n\n🚗 Driving\n• " in text, "sections are blank-line separated with one bullet per line")


def scenario_empty_digest_is_none():
    _reset()
    check(family_digest.build_weekly_digest(end_date=TODAY) is None,
          "nothing to report -> None (no empty post)")


def scenario_post_goes_through_family_channel():
    _reset()
    from unittest import mock
    from services import agent_tools_v2
    storage.ensure_family_channel()
    day = TODAY.isoformat()
    storage.upsert_daily_stats(day, {"date": day, "drivers": {"d1": {"drives": 1, "minutes": 20}},
                                     "kids": {}})
    with mock.patch.object(agent_tools_v2, '_post_chat_message') as post:
        # post_weekly_digest re-records today from the (empty) cache — the
        # pre-seeded snapshot above would be overwritten, so seed the cache too
        storage.set_cached_schedule({"events": [], "assignments": {}, "scheduled_errands": []})
        ok = family_digest.post_weekly_digest()
        # today's re-record wiped the only snapshot -> nothing to report
        check(ok is False and post.call_count == 0,
              "send-day re-snapshot wins; empty week posts nothing")
    # now with durable (ledger) data the post fires as Argyle
    import time as _t
    storage.add_member({"id": "kid", "name": "Addison", "role": "child", "is_child": True})
    with storage.db_lock:
        storage.points_ledger_table.insert({"member_id": "kid", "delta": 5, "reason": "chore",
                                            "chore_title": "Dishes", "ts": _t.time()})
    with mock.patch.object(agent_tools_v2, '_post_chat_message') as post:
        ok = family_digest.post_weekly_digest()
        check(ok is True and post.call_count == 1, "digest posted once")
        channel, sender, body = post.call_args.args[:3]
        check(channel.get("kind") == "family", "posted to the family channel")
        check(sender.get("id") == "argyle", "posted as the Argyle system member")
        check("Family Week in Review" in body, "body is the digest text")


SCENARIOS = [
    scenario_record_daily_stats,
    scenario_build_weekly_digest,
    scenario_empty_digest_is_none,
    scenario_post_goes_through_family_channel,
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

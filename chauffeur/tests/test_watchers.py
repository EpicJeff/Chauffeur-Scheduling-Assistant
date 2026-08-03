"""Tests for the proactive parent watchers (services/watchers.py).

Load-bearing properties: findings fire once and only once (persisted dedup
markers), delivery is ONE consolidated Argyle DM per parent, quiet hours defer
without consuming findings, grace periods gate the stale-state nudges, and the
master toggle silences everything.

Run from chauffeur/:  python tests/test_watchers.py
"""
import datetime
import time
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage, watchers

NOON = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
LATE = NOON.replace(hour=23)


def _reset():
    for t in (storage.members_table, storage.cache_table, storage.chores_table,
              storage.redemptions_table, storage.errands_table,
              storage.event_proposals_table, storage.app_state_table,
              storage.chat_channels_table, storage.chat_messages_table):
        t.truncate()
    storage.get_settings = lambda: {"calendar_ids": ["primary"]}
    storage.add_member({"id": "mom", "name": "Mom", "role": "parent"})
    storage.add_member({"id": "dad", "name": "Dad", "role": "parent"})
    storage.add_member({"id": "kid", "name": "Addison", "role": "child", "is_child": True})


def _run(now=NOON):
    """run_watchers with the LLM prep-kit check neutralized and the DM post
    captured; returns (count, [posted bodies])."""
    posts = []
    with mock.patch.object(watchers, '_prep_kit_findings', return_value=[]), \
         mock.patch('services.agent_tools_v2._post_chat_message',
                    side_effect=lambda ch, sender, body, card=None:
                        posts.append((ch, sender, body)) or {}):
        n = watchers.run_watchers(now=now)
    return n, posts


def scenario_unassigned_event_fires_once():
    _reset()
    soon = (NOON + datetime.timedelta(days=1)).replace(hour=16)
    storage.set_cached_schedule({
        "events": [
            {"id": "ev1", "title": "Soccer Practice", "start": soon.isoformat(),
             "end": (soon + datetime.timedelta(hours=1)).isoformat()},
            {"id": "far", "title": "Recital", "start": (NOON + datetime.timedelta(days=10)).isoformat(),
             "end": (NOON + datetime.timedelta(days=10, hours=1)).isoformat()},
            {"id": "gone", "title": "Away Game", "start": soon.isoformat(),
             "end": soon.isoformat(), "trip_suppressed": True},
        ],
        "assignments": {},
        "unassigned": ["ev1", "far", "gone"],
    })
    n, posts = _run()
    check(n == 1, f"exactly the in-window event is a finding, got {n}")
    check(len(posts) == 2, f"one DM per parent (2 parents), got {len(posts)}")
    body = posts[0][2]
    check("Soccer Practice" in body and "No driver yet" in body, f"body names the event: {body}")
    check("Recital" not in body, "events beyond the 3-day window stay quiet")
    check("Away Game" not in body, "trip-suppressed events are not triage")
    check(posts[0][1].get("id") == "argyle", "sent as the Argyle system member")
    # second sweep: nothing new -> no post at all
    n2, posts2 = _run()
    check(n2 == 0 and posts2 == [], "same finding never notifies twice")


def scenario_stale_grace_periods():
    _reset()
    now_ts = NOON.timestamp()
    storage.set_cached_schedule({"events": [], "assignments": {}, "unassigned": []})
    # proposals: 4 days old fires, 1 day old waits
    storage.add_proposal({"id": "p_old", "title": "Book Fair", "status": "proposed",
                          "created_at": now_ts - 4 * 86400})
    storage.add_proposal({"id": "p_new", "title": "Bake Sale", "status": "proposed",
                          "created_at": now_ts - 1 * 86400})
    # chores: done 3 days ago fires; done 1h ago waits; open 8 days unclaimed fires
    storage.add_chore({"id": "c1", "title": "Mow lawn", "state": "done",
                       "done_at": now_ts - 3 * 86400, "created_at": now_ts - 9 * 86400,
                       "points": 20, "recurrence": "once", "eligible_member_ids": []})
    storage.add_chore({"id": "c2", "title": "Dishes", "state": "done",
                       "done_at": now_ts - 3600, "created_at": now_ts - 3600,
                       "points": 5, "recurrence": "once", "eligible_member_ids": []})
    storage.add_chore({"id": "c3", "title": "Garage sweep", "state": "open",
                       "created_at": now_ts - 8 * 86400,
                       "points": 5, "recurrence": "once", "eligible_member_ids": []})
    # redemption pending 3 days fires
    with storage.db_lock:
        storage.redemptions_table.insert({"id": "r1", "member_id": "kid",
                                          "reward_title": "Movie night", "state": "pending",
                                          "requested_at": now_ts - 3 * 86400})
    # past-due errand fires
    with storage.db_lock:
        storage.errands_table.insert({"id": "er1", "title": "Return library books",
                                      "status": "past_due", "is_completed": False})
        storage.errands_table.insert({"id": "er2", "title": "Groceries",
                                      "status": "pending", "is_completed": False})
    n, posts = _run()
    body = posts[0][2]
    check("Book Fair" in body and "Bake Sale" not in body, "proposal grace period is 3 days")
    check("Mow lawn" in body and "Dishes" not in body, "verify nudge waits 48h")
    check("Garage sweep" in body and "Unclaimed for a week" in body, "week-old unclaimed chores batch up")
    check("Movie night" in body and "Addison" in body, "stale reward request names the kid")
    check("library books" in body and "Groceries" not in body, "only past_due errands nudge")
    n2, posts2 = _run()
    check(n2 == 0 and posts2 == [], "all stale-state findings dedup on the second sweep")


def scenario_quiet_hours_defer_not_drop():
    _reset()
    soon = (NOON + datetime.timedelta(days=1)).replace(hour=9)
    storage.set_cached_schedule({
        "events": [{"id": "ev1", "title": "Dentist", "start": soon.isoformat(),
                    "end": (soon + datetime.timedelta(hours=1)).isoformat()}],
        "assignments": {}, "unassigned": ["ev1"],
    })
    n, posts = _run(now=LATE)
    check(n == 0 and posts == [], "23:00 sweep posts nothing")
    n2, posts2 = _run(now=NOON)
    check(n2 == 1 and len(posts2) == 2, "the finding survives to the morning sweep")


def scenario_master_toggle():
    _reset()
    storage.get_settings = lambda: {"calendar_ids": ["primary"],
                                    "proactive_watchers_enabled": False}
    soon = (NOON + datetime.timedelta(days=1)).replace(hour=9)
    storage.set_cached_schedule({
        "events": [{"id": "ev1", "title": "Dentist", "start": soon.isoformat(),
                    "end": (soon + datetime.timedelta(hours=1)).isoformat()}],
        "assignments": {}, "unassigned": ["ev1"],
    })
    n, posts = _run()
    check(n == 0 and posts == [], "toggle off silences the sweep entirely")


def scenario_prep_kit_weekly_fingerprint():
    _reset()
    storage.set_cached_schedule({
        "events": [{"id": "e1", "title": "Swim Practice", "start": NOON.isoformat(),
                    "end": NOON.isoformat()}],
        "assignments": {}, "unassigned": [],
    })
    fake_kits = [{"name": "Swim Kit", "keywords": ["swim"], "items": ["Goggles"]}]
    with mock.patch('services.prep_kits.suggest_kits', return_value=fake_kits) as sk:
        f1 = watchers._prep_kit_findings(NOON.timestamp())
        check(len(f1) == 1 and "Swim Kit" in f1[0][1], "fresh suggestion becomes a finding")
        check(sk.call_args.kwargs.get('tier') == 'background', "watcher uses the background tier")
        f2 = watchers._prep_kit_findings(NOON.timestamp() + 60)
        check(f2 == [], "interval gate: no second LLM call inside a week")
        f3 = watchers._prep_kit_findings(NOON.timestamp() + 8 * 86400)
        check(f3 == [], "already-announced kit names are fingerprinted, not repeated")


SCENARIOS = [
    scenario_unassigned_event_fires_once,
    scenario_stale_grace_periods,
    scenario_quiet_hours_defer_not_drop,
    scenario_master_toggle,
    scenario_prep_kit_weekly_fingerprint,
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

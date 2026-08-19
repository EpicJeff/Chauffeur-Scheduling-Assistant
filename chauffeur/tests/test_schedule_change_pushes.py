"""Tests for the driver Schedule Updated push horizon: pushes fire only for
TODAY and TOMORROW changes (tomorrow's lines marked), while changes beyond
tomorrow write a quiet in-app telemetry row and NO push — the daily horizon
roll used to fire a near-useless push almost every day.

Run from chauffeur/:  python tests/test_schedule_change_pushes.py
"""
import datetime
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage

TODAY = datetime.date.today()


def ev(day, hour, title="Practice", ev_id="e1"):
    start = datetime.datetime.combine(day, datetime.time(hour, 0))
    return {"id": ev_id, "title": title, "start": start.isoformat()}


def _flush(buffered):
    """Run the flush over a hand-built buffer; return (pushes, telemetry)."""
    import main
    pushes, telemetry = [], []
    with mock.patch.object(main, "_pending_assignment_changes", dict(buffered)), \
         mock.patch.object(main, "send_push",
                           lambda d_id, subs, title, body, tag, actions=None:
                               pushes.append({"driver": d_id, "title": title, "body": body})), \
         mock.patch.object(storage, "get_push_subscriptions", lambda: []), \
         mock.patch.object(storage, "add_telemetry_event",
                           lambda e: telemetry.append(e)), \
         mock.patch.object(main, "_notify_kids_driver_changes", lambda b: None):
        main.flush_assignment_notifications()
    return pushes, telemetry


def scenario_today_change_pushes_detail():
    pushes, _ = _flush({
        "e1": {"first_old": "d1", "last_new": "d2", "ev": ev(TODAY, 16, "Swim")},
    })
    check(len(pushes) == 2, f"gainer and loser each get one push, got {pushes}")
    titles = {p["title"] for p in pushes}
    check(titles == {"Schedule Updated Today"}, f"today title, got {titles}")
    gained = next(p for p in pushes if p["driver"] == "d2")
    check(gained["body"].startswith("+ Swim"), f"detailed + line, got {gained['body']}")
    check("tomorrow" not in gained["body"], "today lines carry no tomorrow marker")


def scenario_tomorrow_change_pushes_marked_detail():
    tmrw = TODAY + datetime.timedelta(days=1)
    pushes, _ = _flush({
        "e1": {"first_old": None, "last_new": "d2", "ev": ev(tmrw, 16, "Piano")},
    })
    check(len(pushes) == 1 and pushes[0]["driver"] == "d2",
          f"tomorrow gain pushes the gainer, got {pushes}")
    check(pushes[0]["title"] == "Schedule Updated Tomorrow",
          f"tomorrow-only title, got {pushes[0]['title']}")
    check("+ Piano" in pushes[0]["body"] and "tomorrow" in pushes[0]["body"],
          f"tomorrow line is detailed and marked, got {pushes[0]['body']}")


def scenario_beyond_tomorrow_is_bell_only():
    far = TODAY + datetime.timedelta(days=9)
    pushes, telemetry = _flush({
        "e1": {"first_old": "d1", "last_new": "d2", "ev": ev(far, 16)},
    })
    check(pushes == [], f"a change 9 days out must push NOTHING, got {pushes}")
    updated = [t for t in telemetry if t.get("action") == "updated"]
    check(len(updated) == 2, f"both drivers keep a quiet bell row, got {telemetry}")
    check(far.strftime("%m/%d") in updated[0]["details"],
          "the bell row names the affected date")


def scenario_mixed_push_excludes_far_dates():
    tmrw = TODAY + datetime.timedelta(days=1)
    far = TODAY + datetime.timedelta(days=20)
    pushes, telemetry = _flush({
        "a": {"first_old": None, "last_new": "d2", "ev": ev(TODAY, 8, "Drop-off", "a")},
        "b": {"first_old": None, "last_new": "d2", "ev": ev(tmrw, 16, "Piano", "b")},
        "c": {"first_old": None, "last_new": "d2", "ev": ev(far, 16, "Regionals", "c")},
    })
    check(len(pushes) == 1, f"one netted push per driver, got {pushes}")
    body = pushes[0]["body"]
    check(pushes[0]["title"] == "Schedule Updated Today" and "+ Drop-off" in body
          and "+ Piano" in body, f"today+tomorrow detailed together, got {body}")
    check("Regionals" not in body and "20" not in pushes[0]["title"],
          f"far-out change stays out of the push, got {body}")
    check(any(t.get("action") == "updated" for t in telemetry),
          "far-out change still writes the quiet bell row")


def scenario_churn_and_ghosts_stay_silent():
    pushes, telemetry = _flush({
        "same": {"first_old": "d1", "last_new": "d1", "ev": ev(TODAY, 11)},
        "ghost": {"first_old": None, "last_new": "ghost_1", "ev": ev(TODAY, 12)},
        "claimed": {"first_old": "d1", "last_new": "d2", "pwa_claimer": "d2",
                    "ev": ev(TODAY, 13)},
    })
    gained = [p for p in pushes if p["body"].startswith("+")]
    check(gained == [], f"churn/ghost/self-claim never push a gain, got {pushes}")


if __name__ == "__main__":
    import traceback
    scenarios = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]
    failed = 0
    for fn in scenarios:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(scenarios) - failed}/{len(scenarios)} scenarios passed")
    raise SystemExit(1 if failed else 0)

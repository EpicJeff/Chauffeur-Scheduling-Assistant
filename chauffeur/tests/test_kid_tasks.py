"""Tests for the kid school-task domain (kid-support arc K4a).

Load-bearing properties: CRUD + completion identity rules (a child checks
off only their own), My Day due_soon windowing (overdue included, 7-day
horizon), gentle wording (never shaming), digest task lines + inclusion for
task-only kids, and agent-tool identity scoping (kid = self only, parent =
any, helper refused).

Run from chauffeur/:  python tests/test_kid_tasks.py
"""
import datetime
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage, family_digest
from services.agent_tools_v2 import get_kid_tasks, add_kid_task, complete_kid_task

TODAY = datetime.date.today()
TOMORROW = TODAY + datetime.timedelta(days=1)


def _reset():
    import main  # noqa: F401
    for t in (storage.members_table, storage.passengers_table, storage.cache_table,
              storage.kid_tasks_table, storage.routines_table,
              storage.routine_checks_table, storage.chat_channels_table,
              storage.chat_messages_table):
        t.truncate()
    storage.get_settings = lambda: {"calendar_ids": ["primary"]}
    storage.add_member({"id": "momm", "name": "Mom", "role": "parent"})
    storage.add_member({"id": "kid1", "name": "Addison", "role": "child", "is_child": True})
    storage.add_member({"id": "kid2", "name": "Ben", "role": "child", "is_child": True})
    storage.add_member({"id": "help1", "name": "Nanny", "role": "helper"})


def _task(member_id, title, due, kind="homework", status="open"):
    import uuid
    t = {"id": uuid.uuid4().hex, "member_id": member_id, "title": title,
         "due_date": due.isoformat(), "kind": kind, "status": status,
         "source": "manual", "notes": "", "done_at": None,
         "created_at": 0, "created_by_member_id": None}
    storage.add_kid_task(t)
    return t


def scenario_due_soon_window_and_wording():
    _reset()
    import main
    _task("kid1", "Math worksheet", TOMORROW)
    _task("kid1", "Science fair", TODAY + datetime.timedelta(days=5), kind="project")
    _task("kid1", "Library book", TODAY - datetime.timedelta(days=2), kind="bring")
    _task("kid1", "Far away", TODAY + datetime.timedelta(days=20))
    _task("kid1", "Old done", TOMORROW, status="done")
    storage.set_cached_schedule({"events": [], "assignments": {}, "matched_rules": {},
                                 "scheduled_errands": []})
    day = main.member_day("kid1", TODAY.isoformat())
    labels = {t["title"]: t for t in day["due_soon"]}
    check(set(labels) == {"Math worksheet", "Science fair", "Library book"},
          f"7-day horizon + overdue, done and far-future excluded — got {set(labels)}")
    check(labels["Library book"]["overdue"] and
          labels["Library book"]["label"].startswith("still open"),
          f"overdue wording is gentle, got {labels['Library book']['label']}")
    check(labels["Math worksheet"]["label"] == "due tomorrow", "tomorrow label")
    check(day["due_soon"][0]["title"] == "Library book",
          "sorted by due date (overdue first)")


def scenario_digest_lines_and_inclusion():
    _reset()
    import main
    _task("kid1", "Math worksheet", TOMORROW)                                  # due digest day
    _task("kid1", "Spelling test", TOMORROW + datetime.timedelta(days=2), kind="test")
    _task("kid1", "Way out", TOMORROW + datetime.timedelta(days=10))
    storage.set_cached_schedule({"events": [], "assignments": {}, "matched_rules": {},
                                 "scheduled_errands": []})
    with mock.patch.object(family_digest, 'weather_line', return_value=None):
        digest = main._build_kid_digests()
    check("kid1" in digest["kids"] and "kid2" not in digest["kids"],
          "a task-only kid is included; a kid with nothing is not")
    tasks = digest["kids"]["kid1"]["tasks"]
    check(any(t == "📚 Math worksheet — due tomorrow" for t in tasks),
          f"digest-day task line, got {tasks}")
    check(any("Spelling test" in t for t in tasks) and not any("Way out" in t for t in tasks),
          "3-day window: near test in, far task out")
    # DM body carries the task lines
    from services import agent_tools_v2
    with mock.patch.object(family_digest, 'weather_line', return_value=None), \
         mock.patch.object(agent_tools_v2, '_post_chat_message') as post:
        main._send_kid_digests()
        body = post.call_args.args[2]
        check("📚 Math worksheet — due tomorrow" in body, f"DM includes tasks, got {body}")


def scenario_completion_identity_rules():
    _reset()
    import main
    t = _task("kid1", "Math worksheet", TOMORROW)
    from fastapi import HTTPException
    try:
        main.complete_kid_task_api(t["id"], main.KidTaskCompleteRequest(member_id="kid2"))
        check(False, "sibling checkoff must 403")
    except HTTPException as e:
        check(e.status_code == 403, "a child can only check off their own tasks")
    res = main.complete_kid_task_api(t["id"], main.KidTaskCompleteRequest(member_id="kid1"))
    check(res["status"] == "done", "owner checkoff works")
    res2 = main.complete_kid_task_api(t["id"], main.KidTaskCompleteRequest(member_id="momm", done=False))
    check(res2["status"] == "open", "a parent can reopen (undo)")


def scenario_agent_tool_scoping():
    _reset()
    kid = storage.get_member("kid1")
    mom = storage.get_member("momm")
    helper = storage.get_member("help1")

    res = add_kid_task("Math worksheet", TOMORROW.isoformat(), kind="homework",
                       acting_member=kid)
    check(res["status"] == "success" and "your list" in res["message"],
          f"kid adds to their own list directly, got {res}")
    res = add_kid_task("Hack", "tomorrow", member_name="Ben", acting_member=kid)
    check(res["status"] == "error" and "your own list" in res["message"],
          "a kid can't touch a sibling's list")
    res = add_kid_task("Poster board", "tomorrow", member_name="Ben", kind="bring",
                       acting_member=mom)
    check(res["status"] == "success" and "Ben's list" in res["message"],
          "a parent adds to a named kid's list")
    res = add_kid_task("Nope", "tomorrow", acting_member=helper)
    check(res["status"] == "error", "helpers are refused")
    res = add_kid_task("Ambiguous", "tomorrow", acting_member=mom)
    check(res["status"] == "error" and "Whose list" in res["message"],
          "two kids + no name -> ask, never guess")

    res = get_kid_tasks(acting_member=kid)
    check("Math worksheet" in res["message"] and "Poster board" not in res["message"],
          "kid reads only their own list")
    res = get_kid_tasks(acting_member=mom)
    check("Addison:" in res["message"] and "Ben:" in res["message"],
          f"parent with no name gets every kid's list, got {res['message']}")

    res = complete_kid_task("math", acting_member=kid)
    check(res["status"] == "success" and "✅" in res["message"], "fuzzy checkoff works")
    res = get_kid_tasks(acting_member=kid)
    check("clear" in res["message"], "done tasks leave the list")


SCENARIOS = [
    scenario_due_soon_window_and_wording,
    scenario_digest_lines_and_inclusion,
    scenario_completion_identity_rules,
    scenario_agent_tool_scoping,
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

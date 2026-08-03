"""Tests for K4b — intake filling the kid-task domain.

Load-bearing properties: a task-mode ICS feed lands assignments on the kid's
list (never a calendar), diffs patch/cancel like calendar mode, DONE tasks
are final (never patched, resurrected, or deleted), and an intake 'tasks:'
approval creates a KidTask instead of a calendar event.

Run from chauffeur/:  python tests/test_kid_task_intake.py
"""
import datetime
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage, ics_sync

TODAY = datetime.date.today()


def _reset():
    import main  # noqa: F401
    for t in (storage.members_table, storage.kid_tasks_table,
              storage.ics_feeds_table, storage.event_proposals_table):
        t.truncate()
    storage.get_settings = lambda: {"calendar_ids": ["primary"]}
    storage.add_member({"id": "kid1", "name": "Addison", "role": "child", "is_child": True})


def _feed(items):
    fid = storage.add_ics_feed({"url": "https://x/feed.ics", "name": "Canvas",
                                "calendar_id": "", "target_kind": "tasks",
                                "member_id": "kid1"})
    feed = storage.get_ics_feed(fid)
    parsed = {"name": "Canvas", "items": items}
    with mock.patch.object(ics_sync, 'fetch_and_parse', return_value=parsed), \
         mock.patch.object(ics_sync.gcal, 'insert_event') as ins:
        res = ics_sync.sync_feed(feed)
        check(ins.call_count == 0, "task mode NEVER touches Google Calendar")
    return fid, res


def _item(uid, title, due):
    return {uid: {"key": uid, "uid": uid, "title": title,
                  "start": due.isoformat(), "end": due.isoformat(),
                  "all_day": True, "location": None, "description": None,
                  "fingerprint": f"fp-{title}-{due}"}}


def scenario_task_feed_lifecycle():
    _reset()
    d3 = TODAY + datetime.timedelta(days=3)
    d5 = TODAY + datetime.timedelta(days=5)
    old = TODAY - datetime.timedelta(days=30)
    items = {**_item("a1", "Math worksheet", d3),
             **_item("a2", "Science quiz", d5),
             **_item("a0", "Ancient homework", old)}
    fid, res = _feed(items)
    tasks = storage.get_kid_tasks("kid1")
    check(res["added"] == 2 and len(tasks) == 2,
          f"future assignments become tasks, ancient ones skipped — got {res}")
    by_title = {t["title"]: t for t in tasks}
    check(by_title["Science quiz"]["kind"] == "test" and
          by_title["Math worksheet"]["kind"] == "homework", "kind heuristic")
    check(all(t["source"] == "ics" and t["source_ref"].startswith(fid + ":")
              for t in tasks), "tasks carry the feed source_ref for diffing")

    # re-sync with a due-date change + a cancellation
    feed = storage.get_ics_feed(fid)
    d4 = TODAY + datetime.timedelta(days=4)
    items2 = {**_item("a1", "Math worksheet", d4)}   # a2 vanished
    with mock.patch.object(ics_sync, 'fetch_and_parse',
                           return_value={"name": "Canvas", "items": items2}):
        res2 = ics_sync.sync_feed(feed)
    tasks = storage.get_kid_tasks("kid1")
    check(res2["updated"] == 1 and res2["removed"] == 1 and len(tasks) == 1,
          f"due-date change patches, vanished future assignment cancels — got {res2}")
    check(tasks[0]["due_date"] == d4.isoformat(), "patched due date stuck")


def scenario_done_tasks_are_final():
    _reset()
    d3 = TODAY + datetime.timedelta(days=3)
    fid, _ = _feed(_item("a1", "Math worksheet", d3))
    t = storage.get_kid_tasks("kid1")[0]
    storage.complete_kid_task(t["id"])

    feed = storage.get_ics_feed(fid)
    d6 = TODAY + datetime.timedelta(days=6)
    with mock.patch.object(ics_sync, 'fetch_and_parse',
                           return_value={"name": "Canvas", "items": _item("a1", "Math worksheet", d6)}):
        res = ics_sync.sync_feed(feed)
    done = storage.get_kid_tasks("kid1", include_done=True)[0]
    check(res["updated"] == 0 and done["status"] == "done"
          and done["due_date"] == d3.isoformat(),
          "a DONE task is never patched or resurrected")
    with mock.patch.object(ics_sync, 'fetch_and_parse',
                           return_value={"name": "Canvas", "items": {}}):
        res2 = ics_sync.sync_feed(storage.get_ics_feed(fid))
    check(res2["removed"] == 0 and
          storage.get_kid_tasks("kid1", include_done=True)[0]["status"] == "done",
          "a DONE task is never deleted by a feed cancellation")


def scenario_feed_create_validation_and_cleanup():
    _reset()
    import main
    from fastapi import HTTPException
    with mock.patch('services.ics_sync.fetch_and_parse',
                    return_value={"name": "Canvas", "items": {}}):
        try:
            main.create_ics_feed(main.IcsFeedCreate(url="https://x/f.ics", target_kind="tasks"),
                                 mock.MagicMock())
            check(False, "task feed without a child must 400")
        except HTTPException as e:
            check(e.status_code == 400, "task feeds need a child member")
    # cleanup on unsubscribe deletes only OPEN tasks
    d3 = TODAY + datetime.timedelta(days=3)
    fid, _ = _feed({**_item("a1", "Math worksheet", d3), **_item("a2", "Essay", d3)})
    tasks = storage.get_kid_tasks("kid1")
    storage.complete_kid_task(tasks[0]["id"])
    removed = ics_sync.remove_feed_events(storage.get_ics_feed(fid))
    left = storage.get_kid_tasks("kid1", include_done=True)
    check(removed == 1 and len(left) == 1 and left[0]["status"] == "done",
          "unsubscribe cleanup removes open tasks, keeps the kid's done history")


def scenario_intake_task_approval():
    _reset()
    import main
    due = (TODAY + datetime.timedelta(days=4)).isoformat()
    pid = storage.add_proposal({"title": "Send $12 for the field trip", "kind": "task",
                                "start": due, "end": due, "all_day": True,
                                "notes": "envelope to homeroom",
                                "source_from": "school@x.org", "source_subject": "Field trip"})
    res = main.approve_proposal(pid, main.ProposalApprove(calendar_id="tasks:kid1"),
                                mock.MagicMock())
    check(res["status"] == "approved" and "Addison's school list" in res["message"],
          f"task approval lands on the kid's list, got {res}")
    tasks = storage.get_kid_tasks("kid1")
    check(len(tasks) == 1 and tasks[0]["source"] == "intake"
          and tasks[0]["due_date"] == due and tasks[0]["notes"] == "envelope to homeroom",
          f"KidTask created from the proposal, got {tasks}")
    check(storage.get_proposal(pid)["status"] == "approved", "proposal resolved")
    from fastapi import HTTPException
    pid2 = storage.add_proposal({"title": "X", "kind": "task", "start": due, "end": due})
    try:
        main.approve_proposal(pid2, main.ProposalApprove(calendar_id="tasks:nobody"),
                              mock.MagicMock())
        check(False, "unknown member must 400")
    except HTTPException as e:
        check(e.status_code == 400, "task target must be a child member")


SCENARIOS = [
    scenario_task_feed_lifecycle,
    scenario_done_tasks_are_final,
    scenario_feed_create_validation_and_cleanup,
    scenario_intake_task_approval,
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

"""HTTP endpoints for threads (task 5) — the hand path onto services/threads.py.

Every write route is parent/adult work, same discipline as Mind's
`_mind_actor`: a child or helper who reaches one of these is refused rather
than quietly ignored. Reads are open to any signed-in member.

Routes are exercised by calling the FastAPI handler functions directly with
`request=None` and an explicit `member_id` in the body, the same pattern
`test_supply_deadlines.py` and `test_cancellations.py` use to test a route
without spinning up the ASGI app.

Run from chauffeur/:  python tests/test_threads_endpoints.py
"""
from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)

from fastapi import HTTPException

from services import storage


def _reset():
    for t in (storage.threads_table, storage.members_table):
        t.truncate()
    storage.add_member({"id": "mom", "name": "Mom", "role": "parent"})
    storage.add_member({"id": "kid", "name": "Lily", "role": "child"})


def _denied(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return None
    except HTTPException as e:
        return e.status_code


def scenario_create_returns_an_id():
    _reset()
    import main
    res = main.create_thread(body={"title": "Find after-school care for Lily",
                                   "owner_member_id": "mom",
                                   "member_id": "mom"}, request=None)
    check(res.get("status") == "success", f"create did not succeed: {res}")
    check(bool(res.get("id")), f"create did not return an id: {res}")
    row = storage.get_thread(res["id"])
    check(row is not None, "the thread was not actually stored")
    check(row["title"] == "Find after-school care for Lily",
          "the stored title does not match what was posted")


def scenario_note_appends_to_history():
    _reset()
    import main
    created = main.create_thread(body={"title": "Pest control renewal",
                                       "member_id": "mom"}, request=None)
    thread_id = created["id"]
    before = len(storage.get_thread(thread_id)["history"])
    res = main.note_thread(thread_id, body={"text": "Left a voicemail",
                                            "member_id": "mom"}, request=None)
    check(res.get("status") == "success", f"note did not succeed: {res}")
    history = storage.get_thread(thread_id)["history"]
    check(len(history) == before + 1,
          f"note did not append to history: {history}")
    check(history[-1]["text"] == "Left a voicemail",
          f"the appended entry does not carry the posted text: {history[-1]}")


def scenario_close_sets_state():
    _reset()
    import main
    created = main.create_thread(body={"title": "Sell the old dresser",
                                       "member_id": "mom"}, request=None)
    thread_id = created["id"]
    res = main.close_thread(thread_id, body={"state": "done", "member_id": "mom"},
                            request=None)
    check(res.get("status") == "success", f"close did not succeed: {res}")
    row = storage.get_thread(thread_id)
    check(row["state"] == "done", f"close did not set state: {row}")


def scenario_advance_updates_next_action():
    _reset()
    import main
    created = main.create_thread(body={"title": "Insurance renewal",
                                       "member_id": "mom"}, request=None)
    thread_id = created["id"]
    res = main.advance_thread(thread_id, body={"next_action": "Call the agent back",
                                               "next_action_at": "2026-09-01",
                                               "member_id": "mom"}, request=None)
    check(res.get("status") == "success", f"advance did not succeed: {res}")
    row = storage.get_thread(thread_id)
    check(row["next_action"] == "Call the agent back",
          f"advance did not update next_action: {row}")
    check(row["next_action_at"] == "2026-09-01",
          f"advance did not update next_action_at: {row}")


def scenario_listing_filters_by_owner():
    _reset()
    import main
    main.create_thread(body={"title": "Mom's thread", "owner_member_id": "mom",
                             "member_id": "mom"}, request=None)
    main.create_thread(body={"title": "Nobody's thread",
                             "member_id": "mom"}, request=None)
    res = main.list_threads(owner="mom", include_closed=False, request=None)
    titles = [t["title"] for t in res["threads"]]
    check(titles == ["Mom's thread"],
          f"listing by owner did not filter: {titles}")
    res_all = main.list_threads(owner=None, include_closed=False, request=None)
    check(len(res_all["threads"]) == 2,
          f"an unfiltered listing dropped a thread: {res_all}")


def scenario_a_child_actor_is_refused_on_write_routes():
    _reset()
    import main
    created = main.create_thread(body={"title": "Renewal", "member_id": "mom"},
                                 request=None)
    thread_id = created["id"]

    check(_denied(main.create_thread, body={"title": "X", "member_id": "kid"},
                 request=None) == 403,
          "a child could open a thread")
    check(_denied(main.note_thread, thread_id,
                 body={"text": "hi", "member_id": "kid"}, request=None) == 403,
          "a child could add a note")
    check(_denied(main.advance_thread, thread_id,
                 body={"next_action": "x", "member_id": "kid"}, request=None) == 403,
          "a child could advance a thread")
    check(_denied(main.close_thread, thread_id,
                 body={"member_id": "kid"}, request=None) == 403,
          "a child could close a thread")
    check(_denied(main.patch_thread, thread_id,
                 body={"title": "y", "member_id": "kid"}, request=None) == 403,
          "a child could patch a thread")


def scenario_unknown_thread_id_is_404_on_every_write_route():
    """note/advance/close/patch all reach into storage by id; a stale or
    typo'd id must come back as 404, not a silent no-op success."""
    _reset()
    import main
    ghost = "no-such-thread"

    check(_denied(main.note_thread, ghost,
                 body={"text": "hi", "member_id": "mom"}, request=None) == 404,
          "note on an unknown thread did not 404")
    check(_denied(main.advance_thread, ghost,
                 body={"next_action": "x", "member_id": "mom"}, request=None) == 404,
          "advance on an unknown thread did not 404")
    check(_denied(main.close_thread, ghost,
                 body={"member_id": "mom"}, request=None) == 404,
          "close on an unknown thread did not 404")
    check(_denied(main.patch_thread, ghost,
                 body={"title": "y", "member_id": "mom"}, request=None) == 404,
          "patch on an unknown thread did not 404")


def scenario_close_refuses_a_bad_state():
    """FINDING 1: `state` is an enum (open|waiting|done|dropped) that
    threads.is_stalled() and the Threads page grouping both trust. Close only
    ever moves a thread to done or dropped — anything else must be refused,
    not written."""
    _reset()
    import main
    created = main.create_thread(body={"title": "Renewal", "member_id": "mom"},
                                 request=None)
    thread_id = created["id"]

    check(_denied(main.close_thread, thread_id,
                 body={"state": "banana", "member_id": "mom"}, request=None) == 400,
          "close accepted a state outside {done, dropped}")
    row = storage.get_thread(thread_id)
    check(row["state"] == "open",
          f"a refused close must not have written anything: {row}")
    check(row.get("closed_at") is None,
          f"a refused close must not have stamped closed_at: {row}")


def scenario_patch_cannot_change_state_or_closed_at():
    """FINDING 2: state changes must go through /advance, /note and /close so
    they land in history — a PATCH that can set `state`/`closed_at` (or
    `next_action`/`next_action_at`) directly bypasses that log entirely."""
    _reset()
    import main
    created = main.create_thread(body={"title": "Renewal", "member_id": "mom"},
                                 request=None)
    thread_id = created["id"]
    before = storage.get_thread(thread_id)

    main.patch_thread(thread_id, body={"state": "done", "closed_at": 12345.0,
                                       "next_action": "sneaky",
                                       "next_action_at": "2026-01-01",
                                       "member_id": "mom"}, request=None)
    after = storage.get_thread(thread_id)
    check(after["state"] == "open",
          f"PATCH changed state directly, bypassing close(): {after}")
    check(after.get("closed_at") == before.get("closed_at"),
          f"PATCH set closed_at directly, bypassing close(): {after}")
    check(after["next_action"] == before["next_action"],
          f"PATCH changed next_action directly, bypassing advance(): {after}")
    check(after["next_action_at"] == before["next_action_at"],
          f"PATCH changed next_action_at directly, bypassing advance(): {after}")
    check(len(after["history"]) == len(before["history"]),
          "PATCH wrote no history entry, so the sneaky field change above "
          "would otherwise have been silent")


def scenario_a_closed_thread_takes_no_more_movement():
    """The page hides note/advance/send/research on a done/dropped thread;
    the API must agree with a 400, not quietly append history to a closed
    record — and /send in particular used to flip a closed thread back to
    `waiting` on success. Reopening isn't a thing: a loop that comes back
    is a new thread."""
    _reset()
    import main
    from services import mailer as _m
    created = main.create_thread(body={"title": "Old dresser", "member_id": "mom"},
                                 request=None)
    thread_id = created["id"]
    main.close_thread(thread_id, body={"state": "done", "member_id": "mom"},
                      request=None)
    before = storage.get_thread(thread_id)

    check(_denied(main.note_thread, thread_id,
                 body={"text": "hi", "member_id": "mom"}, request=None) == 400,
          "note on a closed thread did not 400")
    check(_denied(main.advance_thread, thread_id,
                 body={"next_action": "x", "member_id": "mom"}, request=None) == 400,
          "advance on a closed thread did not 400")
    check(_denied(main.research_thread, thread_id,
                 body={"question": "what now?", "member_id": "mom"},
                 request=None) == 400,
          "research on a closed thread did not 400")

    orig_send, orig_conf = _m.send, _m.configured
    try:
        _m.configured = lambda *a, **k: True
        _m.send = lambda *a, **k: {'sent': True}
        check(_denied(main.send_thread_message, thread_id,
                     body={"subject": "s", "body": "b", "to": "a@b.example",
                           "member_id": "mom"}, request=None) == 400,
              "send on a closed thread did not 400")
    finally:
        _m.send, _m.configured = orig_send, orig_conf

    after = storage.get_thread(thread_id)
    check(after["state"] == "done",
          f"a refused send must not flip a closed thread back to waiting: {after['state']}")
    check(len(after["history"]) == len(before["history"]),
          "and none of the refusals appended history")


def scenario_listing_carries_stall_reason():
    """The Threads page used to re-derive 'overdue'/'quiet' in JS, a second
    copy of services.threads.is_stalled with nothing enforcing parity. The
    fix is for GET /api/threads to be the single source of truth: every row
    carries `stall_reason` (same key services.threads.stalled() already
    uses for the nightly sweep), computed server-side, so the page can just
    read it."""
    _reset()
    import main
    overdue = main.create_thread(body={"title": "Overdue renewal", "member_id": "mom"},
                                 request=None)
    main.advance_thread(overdue["id"], body={"next_action": "Call back",
                                             "next_action_at": "2020-01-01",
                                             "member_id": "mom"}, request=None)
    fresh = main.create_thread(body={"title": "Brand new thread",
                                     "member_id": "mom"}, request=None)

    res = main.list_threads(owner=None, include_closed=False, request=None)
    rows = {t["id"]: t for t in res["threads"]}

    check(rows[overdue["id"]].get("stall_reason") == "overdue",
          f"an overdue thread did not carry stall_reason='overdue': {rows[overdue['id']]}")
    check(not rows[fresh["id"]].get("stall_reason"),
          f"a brand-new thread carried a truthy stall_reason: {rows[fresh['id']]}")


def scenario_the_admin_page_can_work_without_a_member_identity():
    """The control-center screens carry NO member token and NO claim — they
    authenticate as a trusted place, not as a person. Refusing an unresolved
    actor locked a parent out of the Threads page with 'Only a parent or adult
    can handle these' (v2.430.0). A trusted admin surface must get through; an
    enrolled wall panel in a hallway must not."""
    _reset()
    import main
    from services import auth as _auth

    orig = _auth.identify
    try:
        _auth.identify = lambda h, q: {'tier': _auth.SERVICE, 'member': None}
        res = main.create_thread(body={"title": "Fix the dishwasher not drying",
                                       "owner_member_id": "jeff"}, request=None)
        check(res.get("id"), f"the admin page can open a thread, got {res}")
        tid = res["id"]
        check(main.note_thread(tid, body={"text": "called the repair place"},
                               request=None).get("status") == "success",
              "and add a note")
        check(main.advance_thread(tid, body={"next_action": "Order the part",
                                             "next_action_at": None},
                                  request=None).get("status") == "success",
              "and advance it")
        row = storage.get_thread(tid)
        check(row["created_by"] is None,
              f"an admin write is recorded with no author, got {row['created_by']}")

        # A wall panel is a place too, but a place in a hallway anyone passes.
        _auth.identify = lambda h, q: {'tier': _auth.DEVICE, 'device': {},
                                           'member': None}
        check(_denied(main.create_thread, body={"title": "From the kiosk"},
                      request=None) == 403,
              "an enrolled panel must still be refused")

        _auth.identify = lambda h, q: {'tier': None, 'member': None}
        check(_denied(main.create_thread, body={"title": "From nowhere"},
                      request=None) == 403,
              "and so must an unauthenticated caller")
    finally:
        _auth.identify = orig


if __name__ == '__main__':
    scenario_create_returns_an_id()
    scenario_note_appends_to_history()
    scenario_close_sets_state()
    scenario_advance_updates_next_action()
    scenario_listing_filters_by_owner()
    scenario_a_child_actor_is_refused_on_write_routes()
    scenario_unknown_thread_id_is_404_on_every_write_route()
    scenario_close_refuses_a_bad_state()
    scenario_patch_cannot_change_state_or_closed_at()
    scenario_a_closed_thread_takes_no_more_movement()
    scenario_listing_carries_stall_reason()
    scenario_the_admin_page_can_work_without_a_member_identity()
    print("test_threads_endpoints OK")

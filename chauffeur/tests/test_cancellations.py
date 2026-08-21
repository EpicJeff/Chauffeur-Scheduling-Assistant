"""Event cancellations — "practice is off" as a record, a tombstone, and an
announcement, instead of a silent delete in Google Calendar.

Load-bearing properties:

  1. **Occurrence-scoped.** Cancel THIS Tuesday; next Tuesday's sibling is
     untouched. Same keying as optional decisions (instance id first, series
     id fallback, plus the date).
  2. **The record survives.** Restoring marks the row restored, never deletes
     it — the reschedule memory is the point.
  3. **The stamp is the resurrection defence.** However many times an ICS
     feed re-adds the occurrence, it re-arrives canceled.
  4. **The convention reads both ways.** A feed occurrence arriving with a
     canceled-style title becomes a cancellation automatically (league
     systems); a feed-sourced record whose title comes back clean restores
     itself. A person's manual record never auto-restores, and a person's
     deliberate restore is never re-canceled by a stale title.
  5. **Only parents/adults cancel** — by hand or through either agent stack.
  6. **The cancel push replaces the schedule-change push** — a canceled
     event losing its driver is not buffered as a "schedule updated" change.

Run from chauffeur/:  python tests/test_cancellations.py
"""
import datetime

from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR, mocks maps)

from fastapi import HTTPException

from services import storage, cancellations
from models.schemas import Event

# The Google mirror is convention-writing (title prefix + Free) exercised
# against a real API — stubbed here so the suite never leaves the machine.
# What the mirror WRITES is pinned by the title-convention scenario below.
cancellations._mirror_to_google = lambda *a, **kw: None

TOMORROW = (datetime.datetime.now() + datetime.timedelta(days=1)).replace(
    hour=16, minute=0, second=0, microsecond=0)
DATE = TOMORROW.date().isoformat()


class Req:
    def __init__(self, token=None):
        self.headers = {'x-member-token': token} if token else {}
        self.query_params = {}


def _reset():
    storage.event_cancellations_table.truncate()
    storage.cache_table.truncate()


def mk_event(gid="practice42", title="Soccer Practice", series="practiceseries"):
    return Event(id=f"cal1::{gid}", title=title, start=TOMORROW,
                 end=TOMORROW + datetime.timedelta(hours=1),
                 calendar_ids=["cal1"], source_event_ids=[f"cal1::{gid}"],
                 recurring_event_id=series)


def cached_event(gid="practice42", title="Soccer Practice"):
    return {"id": f"cal1::{gid}", "title": title,
            "source_event_ids": [f"cal1::{gid}"],
            "recurring_event_id": "practiceseries",
            "start": TOMORROW.isoformat(),
            "end": (TOMORROW + datetime.timedelta(hours=1)).isoformat()}


def scenario_the_title_convention_is_read_precisely():
    for t in ("CANCELED Practice", "CANCELLED Practice", "Canceled: Practice",
              "cancelled - Practice", "[CANCELED] Practice"):
        check(cancellations.is_canceled_title(t), f"'{t}' reads as canceled")
        check(cancellations.strip_cancel_prefix(t) == "Practice",
              f"and strips clean: '{cancellations.strip_cancel_prefix(t)}'")
    for t in ("Practice", "Discuss canceled game", "Cancellation policy mtg"):
        check(not cancellations.is_canceled_title(t),
              f"'{t}' must NOT read as canceled")


def scenario_cancel_is_occurrence_scoped_and_the_record_survives():
    _reset()
    ev = mk_event()
    res = cancellations.cancel_occurrence(ev, reason="coach is sick",
                                          canceled_by="mom")
    check(res['status'] == 'success', f"cancel writes: {res}")
    check(cancellations.cancellation_for(ev) is not None,
          "the occurrence is canceled")
    sibling = mk_event(gid="practice43")
    sibling.start = TOMORROW + datetime.timedelta(days=7)
    sibling.end = sibling.start + datetime.timedelta(hours=1)
    check(cancellations.cancellation_for(sibling) is None,
          "next week's sibling is untouched")
    res2 = cancellations.cancel_occurrence(ev)
    check(res2['status'] == 'success' and 'already' in res2['message'],
          "re-cancel is an idempotent no-op")

    res3 = cancellations.restore_occurrence(ev)
    check(res3['status'] == 'success', f"restore works: {res3}")
    check(cancellations.cancellation_for(ev) is None,
          "no longer canceled")
    rows = storage.get_event_cancellations()
    check(len(rows) == 1 and rows[0].get('restored_at')
          and rows[0].get('reason') == 'coach is sick'
          and rows[0].get('canceled_by') == 'mom',
          f"the record SURVIVES restore, reason and author intact: {rows}")


def scenario_the_stamp_defeats_the_ics_resurrection():
    _reset()
    ev = mk_event()
    cancellations.cancel_occurrence(ev, reason="field flooded")
    for _ in range(3):   # the feed re-adds it on every refresh, forever
        fresh = mk_event()
        cancellations.stamp_cancellations([fresh])
        check(fresh.canceled and fresh.cancel_reason == "field flooded",
              "the re-added occurrence comes back canceled, reason riding along")
    other = mk_event(gid="swim9", title="Swim", series=None)
    cancellations.stamp_cancellations([other])
    check(not other.canceled, "an uncanceled event is untouched")


def scenario_the_feed_convention_cancels_and_restores():
    _reset()
    ev = mk_event(title="CANCELED Soccer Practice")
    cancellations.detect_feed_cancellations([ev])
    rec = cancellations.cancellation_for(ev)
    check(rec is not None and rec.get('source') == 'feed'
          and rec.get('reason') == cancellations.FEED_REASON,
          f"a feed-titled occurrence becomes a cancellation on its own: {rec}")
    cancellations.detect_feed_cancellations([mk_event(title="CANCELED Soccer Practice")])
    check(len(storage.get_event_cancellations()) == 1,
          "the detector is idempotent — one record, however many refreshes")

    clean = mk_event()   # title back to normal: organizer un-canceled
    cancellations.detect_feed_cancellations([clean])
    rec2 = cancellations.cancellation_for(clean)
    check(rec2 is None, "a feed-sourced record restores itself when the title clears")
    check(len(storage.get_event_cancellations()) == 1
          and storage.get_event_cancellations()[0].get('restored_at'),
          "as a restore, not a deletion")


def scenario_people_outrank_stale_titles():
    _reset()
    # A manual cancel never auto-restores from title churn.
    ev = mk_event()
    cancellations.cancel_occurrence(ev, reason="we're out of town")
    cancellations.detect_feed_cancellations([mk_event()])   # clean title arrives
    check(cancellations.cancellation_for(ev) is not None,
          "a manual cancel is not undone by a clean feed title")
    # A person's deliberate restore is not re-canceled by a stale CANCELED title.
    _reset()
    prefixed = mk_event(title="CANCELED Soccer Practice")
    cancellations.detect_feed_cancellations([prefixed])
    cancellations.restore_occurrence(prefixed)
    cancellations.detect_feed_cancellations([mk_event(title="CANCELED Soccer Practice")])
    check(cancellations.cancellation_for(prefixed) is None,
          "the restored row blocks the detector from re-cancelling")


def scenario_only_parents_and_adults_cancel():
    _reset()
    import main
    storage.members_table.truncate()
    storage.add_member({"id": "mom", "name": "Mom", "role": "parent"})
    storage.add_member({"id": "emma", "name": "Emma", "role": "child"})
    toks = {m: storage.create_member_token(m) for m in ("mom", "emma")}
    storage.set_cached_schedule({"events": [cached_event()],
                                 "assignments": {}, "unassigned": []})

    def denied(fn, *a, **kw):
        try:
            fn(*a, **kw)
            return None
        except HTTPException as e:
            return e.status_code

    check(denied(main.cancel_event_api, "cal1::practice42",
                 body={"reason": "x"}, request=Req(toks['emma'])) == 403,
          "a child is refused at the endpoint")
    res = main.cancel_event_api("cal1::practice42",
                                body={"reason": "coach is sick"},
                                request=Req(toks['mom']))
    check(res.get('status') == 'success', f"a parent cancels: {res}")
    rec = storage.get_event_cancellations()[0]
    check(rec.get('canceled_by') == 'mom', "and the record names them")
    res2 = main.restore_event_api("cal1::practice42", body={},
                                  request=Req(toks['mom']))
    check(res2.get('status') == 'success', "and restores")

    from services import agent_tools_v2 as atv2
    res3 = atv2.cancel_event("soccer practice", DATE,
                             acting_member=storage.get_member('emma'))
    check(res3['status'] == 'error' and 'parent or adult' in res3['message'],
          "the agent refuses a kid out loud")
    res4 = atv2.cancel_event("soccer practice", DATE, reason="rain",
                             acting_member=storage.get_member('mom'))
    check(res4['status'] == 'success', f"and obeys a parent: {res4}")


def scenario_the_cancel_push_replaces_the_schedule_change_push():
    import main
    old = {"assignments": {"e1": "d1", "e2": "d1"},
           "events": [{"id": "e1", "start": TOMORROW.isoformat(), "title": "A"},
                      {"id": "e2", "start": TOMORROW.isoformat(), "title": "B"}]}
    new = {"assignments": {"e1": None, "e2": None},
           "events": [{"id": "e1", "start": TOMORROW.isoformat(), "title": "A",
                       "canceled": True},
                      {"id": "e2", "start": TOMORROW.isoformat(), "title": "B"}]}
    with main._pending_changes_lock:
        main._pending_assignment_changes.clear()
    main._collect_assignment_changes(old, new, [])
    with main._pending_changes_lock:
        buffered = dict(main._pending_assignment_changes)
        main._pending_assignment_changes.clear()
    check("e1" not in buffered,
          "the canceled event's lost driver is NOT a schedule-change push "
          "(the cancel push already said more)")
    check("e2" in buffered,
          "an ordinary lost assignment still is")


def scenario_both_agent_stacks_carry_the_tools():
    from services import agent_tools, agent_tools_v2
    check("cancel_event" in agent_tools.TOOL_HANDLERS
          and "restore_event" in agent_tools.TOOL_HANDLERS
          and "cancel_event" in agent_tools.TOOL_SCHEMAS,
          "the v1 stack has schema and handler")
    v2_names = {t.get("name") for t in agent_tools_v2.get_available_tools()}
    check({"cancel_event", "restore_event"} <= v2_names,
          "the chat widget's stack has them too")
    import os
    router_src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   'services', 'agent_router.py'), encoding='utf-8').read()
    check("cancel_event" in router_src and "restore_event" in router_src,
          "and the router dispatches them")


def scenario_the_hand_path_exists():
    import os
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates')
    dash = open(os.path.join(tpl, 'dashboard.html'), encoding='utf-8').read()
    check('cancelActiveEvent' in dash and '/cancel' in dash
          and 'Restore Event' in dash,
          "the dashboard event modal cancels and restores")
    app = open(os.path.join(tpl, 'app.html'), encoding='utf-8').read()
    check('em-cancel-btn' in app and 'cancelEventFromModal' in app,
          "so does the PWA event modal, for parents and adults")
    timeline = open(os.path.join(tpl, 'components', 'schedule_timeline.html'),
                    encoding='utf-8').read()
    check('ev.canceled' in timeline and 'Canceled' in timeline,
          "the timeline wears the canceled badge with the reason")


def scenario_solver_exclusion_is_wired():
    # The exclusion lives in the refresh loop beside the optional-skip filter;
    # a full solve is exercised by test_no_solver_themes. Here we pin that the
    # filter exists against the flag the stamp actually sets.
    import os, re
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'main.py'), encoding='utf-8').read()
    check(re.search(r"daily_events_to_solve\s*=\s*\[e for e in daily_events_to_solve"
                    r"\s*\n\s*if not getattr\(e, 'canceled', False\)\]", src),
          "the daily solve filters canceled occurrences out")
    check("_cx.detect_feed_cancellations(events)" in src
          and "_cx.stamp_cancellations(events)" in src,
          "and the refresh pipeline detects, then stamps, every pass")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

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
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)

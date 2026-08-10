"""Optional events (event config `is_optional`).

Standing recurring things — open gym, drop-in swim — that the family attends
when the day allows and drops without ceremony when it doesn't. Load-bearing
properties:

  1. **Free day: still driven.** The reduced reward is positive and far above
     routing-preference noise, so an optional event with no conflict is
     scheduled like anything else.
  2. **Conflict: dropped FIRST.** Losing the optional event's 100k always
     beats losing another event's 1M — whichever event carries the flag.
  3. **A skipped optional is never a siren.** The watcher says one calm
     ⏭️ line, keyed apart from the 🚨 unassigned alarm.
  4. **The hand path exists**: the flag is a checkbox on the event config
     modals (series or instance, same as Background Trip), and the timeline
     and My Day cards wear the softened voice.

Phase 2 — per-occurrence decisions (attend | skip | undecided):

  5. **'attend' promotes to full weight.** Once somebody said "she's going"
     it stopped being optional; an uncoverable attend IS a siren again.
  6. **'skip' is quiet.** Excluded from the solve upstream, nothing said.
  7. **Decisions are occurrence-scoped**, keyed by the instance's own google
     id (series id as fallback, mirroring the config lookup), expiring with
     the day. They live in their OWN table — never the event config, whose
     wholesale-replacing lookup would lose passengers on a programmatic write.
  8. **Both agent stacks** carry decide_optional_event / set_event_optional.

Run from chauffeur/:  python tests/test_optional_events.py
"""
import datetime

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR and mocks maps)

from models.schemas import Driver, Event
from services import storage, watchers
from solver import matcher

NOON = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)


def mk_driver(i):
    return Driver(id=f"d{i}", name=f"Driver {i}", color_code="#fff",
                  group="primary", priority_index=1)


def mk_event(i, start_hour, optional=False):
    day = datetime.datetime(2026, 9, 7)
    start = day.replace(hour=start_hour)
    return Event(id=f"e{i}", title=f"Event {i}", start=start,
                 end=start + datetime.timedelta(minutes=60),
                 calendar_ids=["primary"], source_event_ids=[f"e{i}"],
                 app_config={'is_optional': True} if optional else None)


def scenario_free_day_still_drives_the_optional_event():
    drivers = [mk_driver(1)]
    events = [mk_event(0, 9, optional=True), mk_event(1, 14)]
    assignments, unassigned, _, _ = matcher.solve_schedule(events, drivers, [])
    check(not unassigned and assignments.get("e0") == "d1",
          f"no conflict: the optional event is driven like any other, got {assignments}")


def scenario_conflict_drops_the_optional_event_first():
    # Two events at the same hour, one driver. Whichever one carries the flag
    # is the one let go — it is the flag, not the ordering.
    drivers = [mk_driver(1)]
    ev_opt_first = [mk_event(0, 9, optional=True), mk_event(1, 9)]
    assignments, unassigned, _, _ = matcher.solve_schedule(ev_opt_first, drivers, [])
    check(unassigned == ["e0"] and assignments.get("e1") == "d1",
          f"the optional event is dropped, the other is driven: {assignments} / {unassigned}")

    ev_opt_second = [mk_event(0, 9), mk_event(1, 9, optional=True)]
    assignments, unassigned, _, _ = matcher.solve_schedule(ev_opt_second, drivers, [])
    check(unassigned == ["e1"] and assignments.get("e0") == "d1",
          f"flag flipped, drop flips with it: {assignments} / {unassigned}")


def scenario_a_skipped_optional_is_calm_not_a_siren():
    storage.cache_table.truncate()
    soon = (NOON + datetime.timedelta(days=1)).replace(hour=16)
    storage.set_cached_schedule({
        "events": [
            {"id": "gym", "title": "Open Gym", "start": soon.isoformat(),
             "end": (soon + datetime.timedelta(hours=1)).isoformat(),
             "app_config": {"is_optional": True}},
            {"id": "practice", "title": "Soccer Practice", "start": soon.isoformat(),
             "end": (soon + datetime.timedelta(hours=1)).isoformat()},
        ],
        "assignments": {},
        "unassigned": ["gym", "practice"],
    })
    found = dict(watchers._unassigned_findings(NOON))
    gym_keys = [k for k in found if k.startswith("optional_skip:gym:")]
    check(len(gym_keys) == 1, f"the skipped optional is its own kind of finding: {found}")
    gym_msg = found[gym_keys[0]]
    check("⏭️" in gym_msg and "🚨" not in gym_msg and "optional" in gym_msg,
          f"one calm line, never the siren: {gym_msg}")
    practice_keys = [k for k in found if k.startswith("unassigned:practice:")]
    check(practice_keys and "🚨" in found[practice_keys[0]],
          f"a real coverage hole still sounds like one: {found}")


def scenario_the_hand_path_exists():
    import os
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates')
    dash = open(os.path.join(tpl, 'dashboard.html'), encoding='utf-8').read()
    cal = open(os.path.join(tpl, 'calendar.html'), encoding='utf-8').read()
    check('edit-is-optional' in dash and 'is_optional' in dash,
          "the dashboard event modal carries the checkbox and saves the flag")
    check('cal-edit-is-optional' in cal and 'is_optional' in cal,
          "so does the calendar's")
    timeline = open(os.path.join(tpl, 'components', 'schedule_timeline.html'),
                    encoding='utf-8').read()
    check('is_optional' in timeline and 'Skipped' in timeline,
          "the timeline wears the chip and the calm skipped badge")
    app = open(os.path.join(tpl, 'app.html'), encoding='utf-8').read()
    check('r.optional' in app and 'not planned today' in app,
          "a My Day card says optional-not-planned instead of needs-a-driver")


def scenario_decisions_are_occurrence_scoped_and_expire():
    storage.optional_decisions_table.truncate()
    storage.set_optional_decision("gym_instance_1", "2026-09-07", "skip")
    storage.set_optional_decision("gym_series", "2026-09-14", "attend")
    check(storage.get_optional_decision(["gym_instance_1", "gym_series"], "2026-09-07") == "skip",
          "the instance's own decision is found")
    check(storage.get_optional_decision(["gym_instance_2", "gym_series"], "2026-09-07") is None,
          "a sibling occurrence on the same date is untouched")
    check(storage.get_optional_decision(["gym_instance_3", "gym_series"], "2026-09-14") == "attend",
          "a series-keyed decision covers whichever occurrence falls on that date")
    storage.set_optional_decision("gym_instance_1", "2026-09-07", "")  # clear
    check(storage.get_optional_decision(["gym_instance_1"], "2026-09-07") is None,
          "clearing removes the row")
    storage.prune_optional_decisions("2026-09-10")
    check(storage.get_optional_decisions() and
          all(r["date"] >= "2026-09-10" for r in storage.get_optional_decisions()),
          "yesterday's decisions expire; future ones survive")
    storage.optional_decisions_table.truncate()


def scenario_attend_promotes_back_to_full_weight():
    # Two OPTIONAL events at the same hour, one driver. Undecided vs undecided
    # is a coin toss; an 'attend' on one settles it — that one is a commitment
    # again and the undecided one is dropped.
    drivers = [mk_driver(1)]
    events = [mk_event(0, 9, optional=True), mk_event(1, 9, optional=True)]
    events[0].optional_decision = 'attend'
    assignments, unassigned, _, _ = matcher.solve_schedule(events, drivers, [])
    check(assignments.get("e0") == "d1" and unassigned == ["e1"],
          f"the attended occurrence wins the driver: {assignments} / {unassigned}")


def scenario_the_watcher_sirens_for_a_promised_kid():
    storage.cache_table.truncate()
    soon = (NOON + datetime.timedelta(days=1)).replace(hour=16)
    storage.set_cached_schedule({
        "events": [
            {"id": "gym", "title": "Open Gym", "start": soon.isoformat(),
             "end": (soon + datetime.timedelta(hours=1)).isoformat(),
             "app_config": {"is_optional": True}, "optional_decision": "attend"},
        ],
        "assignments": {},
        "unassigned": ["gym"],
    })
    found = dict(watchers._unassigned_findings(NOON))
    keys = list(found)
    check(len(keys) == 1 and keys[0].startswith("unassigned:gym:")
          and "🚨" in found[keys[0]],
          f"attend-decided means somebody promised — the real alarm is back: {found}")


def scenario_the_stamp_reads_the_familys_choice():
    from services import optional_events
    storage.optional_decisions_table.truncate()
    ev = mk_event(0, 9, optional=True)
    gid = optional_events.candidate_google_ids(ev)[0]
    storage.set_optional_decision(gid, ev.start.date().isoformat(), "skip")
    optional_events.stamp_decisions([ev, mk_event(1, 10)])
    check(ev.optional_decision == "skip",
          "the optional event carries the day's decision after the stamp")
    storage.optional_decisions_table.truncate()


def scenario_deciding_by_words_finds_the_event():
    from services import optional_events
    storage.cache_table.truncate()
    storage.optional_decisions_table.truncate()
    soon = (NOON + datetime.timedelta(days=1)).replace(hour=16)
    storage.set_cached_schedule({
        "events": [
            {"id": "cal1::gyminstance42", "title": "Open Gym",
             "source_event_ids": ["cal1::gyminstance42"],
             "recurring_event_id": "gymseries",
             "start": soon.isoformat(),
             "end": (soon + datetime.timedelta(hours=1)).isoformat(),
             "app_config": {"is_optional": True}},
            {"id": "cal1::dentist", "title": "Dentist",
             "source_event_ids": ["cal1::dentist"],
             "start": soon.isoformat(),
             "end": (soon + datetime.timedelta(hours=1)).isoformat()},
        ],
        "assignments": {}, "unassigned": [],
    })
    res = optional_events.decide_by_title("open gym", soon.date().isoformat(), "skip")
    check(res.get("status") == "success", f"the agent path resolves and writes: {res}")
    check(storage.get_optional_decision(["gyminstance42"], soon.date().isoformat()) == "skip",
          "keyed by the occurrence's own google id, not the series")
    res2 = optional_events.decide_by_title("dentist", soon.date().isoformat(), "skip")
    check(res2.get("status") == "error" and "not marked optional" in res2.get("message", ""),
          f"deciding attendance on a mandatory event is refused out loud: {res2}")
    storage.optional_decisions_table.truncate()


def scenario_both_agent_stacks_carry_the_tools():
    from services import agent_tools, agent_tools_v2
    check("decide_optional_event" in agent_tools.TOOL_HANDLERS
          and "set_event_optional" in agent_tools.TOOL_HANDLERS
          and "decide_optional_event" in agent_tools.TOOL_SCHEMAS,
          "the v1 stack has schema and handler")
    v2_names = {t.get("name") for t in agent_tools_v2.get_available_tools()}
    check({"decide_optional_event", "set_event_optional"} <= v2_names,
          "the chat widget's Gemma stack (agent_router/agent_tools_v2) has them too")
    import os
    router_src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   'services', 'agent_router.py'), encoding='utf-8').read()
    check("decide_optional_event" in router_src and "set_event_optional" in router_src,
          "and the router dispatches them")


def scenario_the_decision_hand_path_exists():
    import os
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates')
    app = open(os.path.join(tpl, 'app.html'), encoding='utf-8').read()
    check('decideOptional(' in app and 'Skip today' in app and 'Going' in app,
          "My Day cards offer attend/skip/undo by hand")
    timeline = open(os.path.join(tpl, 'components', 'schedule_timeline.html'),
                    encoding='utf-8').read()
    check('optional_decision' in timeline and 'Skipped today' in timeline,
          "the timeline wears the decided states")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} optional-event scenarios passed")

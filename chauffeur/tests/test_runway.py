"""The Morning & Bedtime Runway (arc R2) — an ambient lens over routines.

Load-bearing properties:

  1. **Explicit membership.** `runway: morning|bedtime` is a flag a parent
     sets, never inferred from item text. No flagged items — no runway.
  2. **Anchored to the family's own times.** Bedtime ends at the flagged
     items' last time_of_day; morning does too UNLESS the solver has a real
     departure for this kid (leave-at / be-ready-at), which tightens it.
     That is what makes no-school mornings work.
  3. **A lens, never a writer.** Fill is read from the same checks and step
     ticks everything else writes; steps subdivide the fill; nothing here
     mints XP or touches streaks.
  4. **"Behind" is honest**: a flagged TIMED item unticked past its time +
     grace — never raw idle. Off-day dates are never behind.
  5. The window opens before the first timed item and closes after the end;
     outside it (or complete) the lane draws exactly as before.

Run from chauffeur/:  python tests/test_runway.py
"""
import datetime

from harness import check  # noqa: F401

from services import storage, runway

DAY = datetime.date(2026, 9, 9)          # a Wednesday
DATE = DAY.isoformat()


def _seed():
    storage.members_table.truncate()
    storage.routines_table.truncate()
    storage.routine_checks_table.truncate()
    storage.routine_step_checks_table.truncate()
    storage.cache_table.truncate()
    storage.add_member({"id": "tot", "name": "Tot", "role": "child"})


def _item(rid, title, time_of_day=None, rw='morning', steps=None):
    storage.add_routine({"id": rid, "member_id": "tot", "title": title,
                         "emoji": None, "time_of_day": time_of_day,
                         "days_of_week": [], "runway": rw,
                         "steps": steps or []})


def scenario_no_flags_no_runway():
    _seed()
    _item("r1", "Brush teeth", "07:10", rw=None)
    check(runway.runways_for("tot", DATE) == {},
          "an unflagged routine builds no runway — blank means blank")


def scenario_item_times_are_the_spine():
    _seed()
    _item("r1", "Get dressed", "07:00")
    _item("r2", "Breakfast", "07:20")
    _item("r3", "Shoes on", "07:45")
    now = datetime.datetime.combine(DAY, datetime.time(7, 5))
    rw = runway.runways_for("tot", DATE, now=now)['morning']
    check(rw['end_label'] == '7:45 AM' and rw['tightened_by'] is None,
          f"a no-school morning ends at the last item's own time: {rw}")
    check(rw['units_total'] == 3 and rw['units_done'] == 0
          and rw['next_up']['title'] == 'Get dressed',
          f"fill and next-up read from the items: {rw}")
    check(rw['window_active'] and not rw['behind'],
          "the window is open just after the first item's time, calmly")


def scenario_steps_subdivide_and_ticks_fill_the_rocket():
    _seed()
    _item("r1", "Pack backpack", "07:30",
          steps=[{'id': 'a', 'title': 'Folder'}, {'id': 'b', 'title': 'Snack'},
                 {'id': 'c', 'title': 'Water'}])
    _item("r2", "Shoes on", "07:45")
    now = datetime.datetime.combine(DAY, datetime.time(7, 0))
    rw = runway.runways_for("tot", DATE, now=now)['morning']
    check(rw['units_total'] == 4, f"three steps + one plain item = 4 notches: {rw}")
    storage.set_routine_step_check("r1", "tot", DATE, "a", True)
    storage.set_routine_step_check("r1", "tot", DATE, "b", True)
    rw = runway.runways_for("tot", DATE, now=now)['morning']
    check(rw['units_done'] == 2 and not rw['complete'],
          f"two step ticks advance two notches: {rw}")
    storage.set_routine_step_check("r1", "tot", DATE, "c", True)
    storage.set_routine_check("r2", "tot", DATE, True)
    rw = runway.runways_for("tot", DATE, now=now)['morning']
    check(rw['complete'] and rw['units_done'] == 4 and not rw['window_active'],
          f"complete closes the window — the lane goes back to normal: {rw}")


def scenario_behind_is_a_timed_item_past_grace_never_idle():
    _seed()
    _item("r1", "Get dressed", "07:00")
    _item("r2", "Anytime tidy", None)
    just_late = datetime.datetime.combine(DAY, datetime.time(7, 8))
    rw = runway.runways_for("tot", DATE, now=just_late)['morning']
    check(not rw['behind'], "inside grace is not behind — mid-shoe is not idle")
    late = datetime.datetime.combine(DAY, datetime.time(7, 15))
    rw = runway.runways_for("tot", DATE, now=late)['morning']
    check(rw['behind'], "past time + grace on a TIMED item is honestly behind")
    storage.set_routine_check("r1", "tot", DATE, True)
    rw = runway.runways_for("tot", DATE, now=late)['morning']
    check(not rw['behind'],
          "the untimed item can never put the runway behind on its own")
    # A different date than today is never behind and never windowed.
    other = datetime.datetime.combine(DAY + datetime.timedelta(days=1),
                                      datetime.time(7, 15))
    rw = runway.runways_for("tot", DATE, now=other)['morning']
    check(not rw['behind'] and not rw['window_active'],
          "yesterday's runway makes no live claims")


def scenario_a_real_departure_tightens_the_morning():
    _seed()
    storage.update_member("tot", {"passenger_id": "p1"})
    storage.passengers_table.truncate()
    storage.add_passenger({"id": "p1", "name": "Tot", "calendar_ids": ["cal_tot"],
                           "hashtags": []})
    _item("r1", "Shoes on", "08:30")
    start = datetime.datetime.combine(DAY, datetime.time(8, 45))
    storage.set_cached_schedule({
        "events": [{"id": "ev1", "title": "School", "start": start.isoformat(),
                    "end": (start + datetime.timedelta(hours=6)).isoformat(),
                    "location": "School St", "calendar_ids": ["cal_tot"]}],
        "assignments": {"ev1": "d1"},
        "initial_edges": {"d1": {"ev1": {"travel_mins": 20,
                                         "buffer_before_mins": 5}}},
    })
    now = datetime.datetime.combine(DAY, datetime.time(8, 0))
    rw = runway.runways_for("tot", DATE, now=now)['morning']
    # leave-at = 8:45 − 25 = 8:20, earlier than the 8:30 item time.
    check(rw['end_label'] == '8:20 AM' and rw['tightened_by'] == 'schedule',
          f"the solver's departure tightens the end: {rw}")


def scenario_bedtime_runs_on_its_own_clock():
    _seed()
    _item("b1", "Pajamas", "19:30", rw='bedtime')
    _item("b2", "Brush teeth", "19:45", rw='bedtime')
    _item("b3", "Lights out", "20:00", rw='bedtime')
    now = datetime.datetime.combine(DAY, datetime.time(19, 40))
    rws = runway.runways_for("tot", DATE, now=now)
    check('bedtime' in rws and 'morning' not in rws,
          "bedtime flags build only the bedtime runway")
    rw = rws['bedtime']
    check(rw['end_label'] == '8:00 PM' and rw['tightened_by'] is None
          and rw['window_active'],
          f"anchored to the family's own bedtime item times: {rw}")


def scenario_the_flag_round_trips_and_the_lanes_draw():
    import main
    _seed()
    item = main.create_routine(main.RoutineRequest(
        member_id="tot", title="Shoes on", time_of_day="07:45",
        runway="morning"))
    check(item['runway'] == 'morning', "the flag round-trips the API")
    try:
        main.create_routine(main.RoutineRequest(member_id="tot", title="X",
                                                runway="noon"))
        check(False, "an unknown runway kind must be refused")
    except Exception as e:
        check('runway' in str(getattr(e, 'detail', e)), "with a clear refusal")
    day = main.routines_day("tot")
    check('runways' in day, "the day payload carries the runway lens")

    import os
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates')
    lanes = open(os.path.join(tpl, 'components', 'routine_lanes.html'),
                 encoding='utf-8').read()
    check('activeRunways(' in lanes and 'runwayPct(' in lanes and '🚀' in lanes,
          "the lanes draw the vehicle during a live window")
    check("rw.behind ? 'bg-amber-500' : 'bg-emerald-500'" in lanes,
          "behind tints amber — a calm color, never a siren")
    editor = open(os.path.join(tpl, 'routines.html'), encoding='utf-8').read()
    check("editItem.runway" in editor and 'Bedtime' in editor,
          "the editor's toggle is the explicit hand path")


def scenario_the_cue_is_single_and_calm():
    """R3: the push half is a whisper. One cue per (member, kind, item, day),
    marker set FIRST (an unreachable speaker fails once, never retries into
    nagging), no cue room = no cues, global switch kills all of it."""
    _seed()
    storage.set_app_state(runway.CUE_STATE_KEY, {})
    storage.set_app_state("runway_cues_swept", 0)
    _item("r1", "Get dressed", "07:00")
    spoken = []
    import services.announce as announce_mod
    real = announce_mod.announce
    announce_mod.announce = lambda room, msg: spoken.append((room, msg)) or {'status': 'success'}
    try:
        late = datetime.datetime.combine(DAY, datetime.time(7, 20))
        check(runway.sweep_cues(now=late) == 0 and not spoken,
              "no cue room on the child means NO cues — the per-child off switch")

        storage.update_member("tot", {"runway_cue_room": "Kids Room"})
        check(runway.sweep_cues(now=late) == 1 and len(spoken) == 1,
              f"one genuinely-behind item speaks once: {spoken}")
        check(spoken[0][0] == "Kids Room" and "Get dressed" in spoken[0][1]
              and "Tot" in spoken[0][1],
              f"in the child's room, kid-worded, naming the thing: {spoken[0]}")
        for _ in range(3):
            check(runway.sweep_cues(now=late) == 0,
                  "the same stall NEVER speaks twice — repetition is the "
                  "thing being eliminated")
        check(len(spoken) == 1, f"still exactly one: {spoken}")

        # A second item stalling later is a NEW episode — one more cue.
        _item("r2", "Breakfast", "07:30")
        later = datetime.datetime.combine(DAY, datetime.time(7, 45))
        check(runway.sweep_cues(now=later) == 1 and len(spoken) == 2,
              f"a new stalled item earns its own single cue: {spoken}")

        # The global switch kills everything. (The harness pins get_settings
        # to a fixed dict, so the switch is stubbed at the read.)
        real_settings = storage.get_settings
        storage.get_settings = lambda: {"runway_cues_enabled": False}
        _item("r3", "Shoes on", "07:50")
        latest = datetime.datetime.combine(DAY, datetime.time(8, 10))
        try:
            check(runway.sweep_cues(now=latest) == 0 and len(spoken) == 2,
                  "runway_cues_enabled off silences the house")
        finally:
            storage.get_settings = real_settings

        # Inside the window but on pace: silence.
        spoken.clear()
        storage.set_app_state(runway.CUE_STATE_KEY, {})
        for rid in ("r1", "r2", "r3"):
            storage.set_routine_check(rid, "tot", DATE, True)
        check(runway.sweep_cues(now=latest) == 0 and not spoken,
              "a runway that is merely RUNNING is silent — pull, not push")
    finally:
        announce_mod.announce = real


def scenario_the_cue_marker_survives_a_dead_speaker():
    """The marker goes down BEFORE the speaker call, so a broken HA setup
    costs one failed attempt, not a retry loop."""
    _seed()
    storage.set_app_state(runway.CUE_STATE_KEY, {})
    _item("r1", "Get dressed", "07:00")
    storage.update_member("tot", {"runway_cue_room": "Kids Room"})
    import services.announce as announce_mod
    real = announce_mod.announce
    calls = []
    def boom(room, msg):
        calls.append(1)
        raise RuntimeError("HA is down")
    announce_mod.announce = boom
    try:
        late = datetime.datetime.combine(DAY, datetime.time(7, 20))
        runway.sweep_cues(now=late)
        runway.sweep_cues(now=late)
        check(len(calls) == 1,
              "the failed cue is marked fired and never retried into nagging")
    finally:
        announce_mod.announce = real


def scenario_the_cue_hand_paths_exist():
    import os
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates')
    editor = open(os.path.join(tpl, 'routines.html'), encoding='utf-8').read()
    check('setCueRoom' in editor and 'No cue room (cues off)' in editor
          and 'api/announce/rooms' in editor,
          "the per-child cue room is picked on the Routines page")
    from services import settings_registry
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'services', 'settings_registry.py'), encoding='utf-8').read()
    check('runway_cues_enabled' in src,
          "the global switch is a registered setting")


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

"""Tests for Status Protocols (Presence & Status arc P1).

Load-bearing properties: statuses are date-bound (structural staleness — a
status never lingers past its day), setting the same protocol on the same day
refreshes instead of stacking, the family's authored words are delivered
VERBATIM, kid sends respect quiet hours and SKIP (adults always hear), the
kid digest leads with the status and includes EVERY kid on a status day, the
dismissal push carries the status and fires even with no ride, and clearing
a today/tomorrow day announces the correction.

Run from chauffeur/:  python tests/test_status_protocols.py
"""
import datetime
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage, family_digest, status_protocols
from services import agent_tools_v2

TODAY = datetime.date.today()
TOMORROW = TODAY + datetime.timedelta(days=1)
NOON = datetime.datetime.combine(TODAY, datetime.time(12, 0))


def _reset():
    import main  # noqa: F401
    for t in (storage.members_table, storage.passengers_table, storage.cache_table,
              storage.routines_table, storage.routine_checks_table,
              storage.prep_kits_table, storage.chat_channels_table,
              storage.chat_messages_table, storage.status_protocols_table,
              storage.status_days_table, storage.kid_tasks_table,
              storage.app_state_table):
        t.truncate()
    storage.get_settings = lambda: {"calendar_ids": ["primary"]}
    storage.add_member({"id": "dadm", "name": "Dad", "role": "parent", "driver_id": "d1"})
    storage.add_member({"id": "momm", "name": "Mom", "role": "parent", "driver_id": "d2"})
    storage.add_member({"id": "kid1", "name": "Addison", "role": "child",
                        "is_child": True, "passenger_id": "p1"})
    storage.add_member({"id": "kid2", "name": "Ben", "role": "child",
                        "is_child": True, "passenger_id": "p2"})
    with storage.db_lock:
        storage.passengers_table.insert({"id": "p1", "name": "Addison",
                                         "calendar_ids": ["cal1"], "hashtags": []})
        storage.passengers_table.insert({"id": "p2", "name": "Ben",
                                         "calendar_ids": ["cal2"], "hashtags": []})


def _mk_protocol(**overrides):
    data = {"name": "Chemo Day", "emoji": "💙", "member_id": "momm",
            "need": "cover",
            "kid_message": "Mom's resting today. Grandma's picking you up — "
                           "she'd love a drawing.",
            "adult_message": "Pickups and dinner need covering.",
            "keywords": ["chemo"], "enabled": True}
    data.update(overrides)
    return storage.add_status_protocol(data)


def scenario_day_dedupe_and_protocol_cascade():
    _reset()
    pid = _mk_protocol()
    d1 = storage.add_status_day({"date": TODAY.isoformat(), "protocol_id": pid,
                                 "note": "", "set_by": "momm"})
    d2 = storage.add_status_day({"date": TODAY.isoformat(), "protocol_id": pid,
                                 "note": "rougher than usual", "set_by": "dadm"})
    check(d1 == d2, "same protocol + date refreshes the instance, never stacks")
    days = storage.get_status_days(start=TODAY.isoformat(), end=TODAY.isoformat())
    check(len(days) == 1 and days[0]["note"] == "rougher than usual"
          and days[0]["set_by"] == "dadm",
          f"refresh updates note + setter, got {days}")
    storage.delete_status_protocol(pid)
    check(storage.get_status_days() == [],
          "deleting a protocol cascades to its days (no orphaned blank banners)")


def scenario_date_bound_resolution():
    _reset()
    pid = _mk_protocol()
    off = _mk_protocol(name="Disabled Day", enabled=False)
    yesterday = (TODAY - datetime.timedelta(days=1)).isoformat()
    storage.add_status_day({"date": yesterday, "protocol_id": pid})
    storage.add_status_day({"date": TODAY.isoformat(), "protocol_id": pid, "note": "n"})
    storage.add_status_day({"date": TODAY.isoformat(), "protocol_id": off})
    active = status_protocols.active_statuses(TODAY.isoformat())
    check(len(active) == 1 and active[0]["name"] == "Chemo Day",
          f"today resolves only today's enabled statuses, got {active}")
    check(active[0]["member_name"] == "Mom" and active[0]["need_label"] == "Cover for them",
          f"affected member + need label resolved, got {active[0]}")
    check(status_protocols.active_statuses(TOMORROW.isoformat()) == [],
          "yesterday's status NEVER lingers into another day (structural staleness)")
    lines = status_protocols.kid_lines(TODAY.isoformat())
    check(lines == ["💙 Mom's resting today. Grandma's picking you up — "
                    "she'd love a drawing. (n)"],
          f"kid line is the family's words verbatim + note, got {lines}")


def scenario_digest_leads_with_status_and_includes_every_kid():
    _reset()
    pid = _mk_protocol()
    storage.add_status_day({"date": TOMORROW.isoformat(), "protocol_id": pid})
    day = TOMORROW.isoformat()
    storage.set_cached_schedule({
        "events": [{"id": "swim", "title": "Swim Practice", "start": f"{day}T08:00:00",
                    "end": f"{day}T09:00:00", "calendar_ids": ["cal1"]}],
        "assignments": {"swim": "d1"}, "ghost_assignments": {},
        "matched_rules": {}, "scheduled_errands": []})
    import main
    with mock.patch.object(family_digest, 'weather_line', return_value=None):
        digest = main._build_kid_digests()
    check(set(digest["kids"].keys()) == {"kid1", "kid2"},
          f"a status day includes EVERY kid — even Ben with an empty day, got {list(digest['kids'])}")
    k1 = digest["kids"]["kid1"]
    check(k1["lines"][0].startswith("💙 Mom's resting"),
          f"status line leads the digest, got {k1['lines']}")
    check(any("Swim Practice" in l for l in k1["lines"]), "rides still follow")
    check(digest["kids"]["kid2"]["lines"][0].startswith("💙"),
          "the empty-day kid still hears the message")


def scenario_dismissal_push_carries_status():
    _reset()
    pid = _mk_protocol()
    storage.add_status_day({"date": TODAY.isoformat(), "protocol_id": pid})
    day = TODAY.isoformat()
    storage.set_cached_schedule({
        "events": [{"id": "piano", "title": "Piano", "start": f"{day}T16:00:00",
                    "end": f"{day}T17:00:00", "calendar_ids": ["cal1"]}],
        "assignments": {"piano": "d1"}, "ghost_assignments": {},
        "matched_rules": {}, "scheduled_errands": []})
    import main
    kid1 = storage.get_member("kid1")
    kid1["school_hours_end"] = "15:00"
    now = datetime.datetime.combine(TODAY, datetime.time(15, 5))
    with mock.patch.object(main, '_notify_member_lanes') as lanes:
        sent = main._send_school_end_push(kid1, now=now)
    check(sent, "ride push sent")
    _, title, body = lanes.call_args.args[:3]
    check("Dad has you after school" in title and "Mom's resting" in body,
          f"status rides the SAME push as the ride (one push, not two), got {title!r} / {body!r}")
    # No ride, no bus — on a status day the push still goes out.
    kid2 = storage.get_member("kid2")
    kid2["school_hours_end"] = "15:00"
    with mock.patch.object(main, '_notify_member_lanes') as lanes:
        sent = main._send_school_end_push(kid2, now=now)
    check(sent and lanes.call_args.args[1] == "💙 About today",
          "a status day breaks the silence rule — no-ride kid still hears the message")
    # Normal day, no ride: the original silence rule stands.
    with storage.db_lock:
        storage.status_days_table.truncate()
    with mock.patch.object(main, '_notify_member_lanes') as lanes:
        sent = main._send_school_end_push(kid2, now=now)
    check(not sent and lanes.call_count == 0,
          "no status, no ride, no bus -> silence (unchanged K4c rule)")


def scenario_announce_set_audiences_and_quiet_hours():
    _reset()
    pid = _mk_protocol()
    day_id = storage.add_status_day({"date": TODAY.isoformat(), "protocol_id": pid,
                                     "set_by": "momm"})
    with mock.patch.object(agent_tools_v2, '_post_chat_message') as post:
        status_protocols.announce_set(day_id, now=NOON)
    bodies = {}
    for c in post.call_args_list:
        channel, _sender, body = c.args[:3]
        for m_id in ("kid1", "kid2", "dadm", "momm"):
            if m_id in (channel.get("dm_key") or ""):
                bodies[m_id] = body
    check(set(bodies) == {"kid1", "kid2", "dadm"},
          f"both kids + the OTHER parent hear it; the setter doesn't, got {set(bodies)}")
    check("Mom's resting today" in bodies["kid1"] and "today" in bodies["kid1"],
          f"kids get the family's words with the when, got {bodies['kid1']}")
    check("Pickups and dinner" in bodies["dadm"] and "Set by Mom" in bodies["dadm"],
          f"adults get logistics + who set it, got {bodies['dadm']}")

    # Kid quiet hours: kids SKIP (digest/My Day restate), adults still hear.
    storage.get_settings = lambda: {"calendar_ids": ["primary"],
                                    "kid_quiet_start": "20:30", "kid_quiet_end": "07:00"}
    late = datetime.datetime.combine(TODAY, datetime.time(21, 30))
    with mock.patch.object(agent_tools_v2, '_post_chat_message') as post:
        status_protocols.announce_set(day_id, now=late)
    keys = [c.args[0].get("dm_key") or "" for c in post.call_args_list]
    check(len(keys) == 1 and "dadm" in keys[0],
          f"quiet hours: kid DMs skipped, adult still sent, got {keys}")
    storage.get_settings = lambda: {"calendar_ids": ["primary"]}

    # Far-out days: kids wait for the D-1 digest; adults plan ahead now.
    far = (TODAY + datetime.timedelta(days=5)).isoformat()
    far_id = storage.add_status_day({"date": far, "protocol_id": pid, "set_by": "momm"})
    with mock.patch.object(agent_tools_v2, '_post_chat_message') as post:
        status_protocols.announce_set(far_id, now=NOON)
    keys = [c.args[0].get("dm_key") or "" for c in post.call_args_list]
    check(len(keys) == 1 and "dadm" in keys[0],
          f"5 days out: announcing to kids now just moves the dread up — adults only, got {keys}")


def scenario_announce_cleared_correction():
    _reset()
    pid = _mk_protocol()
    day_id = storage.add_status_day({"date": TODAY.isoformat(), "protocol_id": pid})
    row = storage.delete_status_day(day_id)
    with mock.patch.object(agent_tools_v2, '_post_chat_message') as post:
        status_protocols.announce_cleared(row, now=NOON)
    kid_bodies = [c.args[2] for c in post.call_args_list
                  if "kid1" in (c.args[0].get("dm_key") or "")]
    check(kid_bodies and "Change of plans" in kid_bodies[0]
          and "Chemo Day" in kid_bodies[0],
          f"cleared today -> kids hear the relief too, got {kid_bodies}")
    check(len(post.call_args_list) == 4, "correction reaches both kids and both adults")


def scenario_agent_tool_set_get_clear():
    _reset()
    _mk_protocol()
    with mock.patch.object(agent_tools_v2, '_post_chat_message'):
        r = agent_tools_v2.set_household_status("chemo", "today", note="long infusion")
    check(r["status"] == "success" and "Chemo Day" in r["message"],
          f"fuzzy protocol match + set, got {r}")
    g = agent_tools_v2.get_household_status("today")
    check("Chemo Day" in g["message"] and "Mom" in g["message"]
          and "long infusion" in g["message"],
          f"read-back includes protocol, member, note — got {g}")
    with mock.patch.object(agent_tools_v2, '_post_chat_message') as post:
        c = agent_tools_v2.set_household_status("chemo", "today", clear=True)
    check(c["status"] == "success" and "Cleared" in c["message"], f"clear works, got {c}")
    check(post.call_count > 0, "clearing announces the change of plans")
    check(status_protocols.active_statuses(TODAY.isoformat()) == [], "day removed")
    kid = storage.get_member("kid1")
    r = agent_tools_v2.set_household_status("chemo", "today", acting_member=kid)
    check(r["status"] == "error", "kids can't set the family status")
    r = agent_tools_v2.set_household_status("nonsense day", "today")
    check(r["status"] == "error" and "Chemo Day" in r["message"],
          "unknown name lists the family's day types")


def scenario_member_day_carries_status():
    _reset()
    pid = _mk_protocol()
    storage.add_status_day({"date": TODAY.isoformat(), "protocol_id": pid,
                            "set_by": "momm"})
    storage.set_cached_schedule({"events": [], "assignments": {},
                                 "matched_rules": {}, "scheduled_errands": []})
    import main
    day = main.member_day("kid1", TODAY.isoformat())
    sd = day.get("status_days") or []
    check(len(sd) == 1 and sd[0]["name"] == "Chemo Day"
          and sd[0]["set_by_name"] == "Mom",
          f"My Day payload carries the resolved status, got {sd}")
    check((main.member_day("kid1", TOMORROW.isoformat()).get("status_days") or []) == [],
          "tomorrow's My Day is clean — date-bound")


# --- P2: the calendar knows + solver needs ---

def scenario_calendar_sweep_auto_sets():
    _reset()
    pid = _mk_protocol()  # keywords: ["chemo"]
    in3 = (TODAY + datetime.timedelta(days=3)).isoformat()
    far = (TODAY + datetime.timedelta(days=30)).isoformat()
    storage.set_cached_schedule({
        "events": [
            {"id": "e1", "title": "Chemo infusion — Mom", "start": f"{in3}T09:00:00",
             "end": f"{in3}T13:00:00", "calendar_ids": ["momcal"]},
            {"id": "e2", "title": "Soccer practice", "start": f"{in3}T16:00:00",
             "end": f"{in3}T17:00:00", "calendar_ids": ["cal1"]},
            # outside the 7-day horizon: ignored
            {"id": "e3", "title": "Chemo follow-up", "start": f"{far}T09:00:00",
             "end": f"{far}T10:00:00", "calendar_ids": ["momcal"]},
            # errands never trigger
            {"id": "e4", "title": "pick up chemo prescription", "start": f"{TODAY}T10:00:00",
             "end": f"{TODAY}T10:30:00", "event_type": "errand"},
        ],
        "assignments": {}, "ghost_assignments": {}, "matched_rules": {},
        "scheduled_errands": []})
    with mock.patch.object(agent_tools_v2, '_post_chat_message') as post:
        created = status_protocols.auto_set_from_calendar(now=NOON)
    check(len(created) == 1, f"one match in horizon -> one day set, got {len(created)}")
    active = status_protocols.active_statuses(in3)
    check(len(active) == 1 and active[0]["source"] == "calendar"
          and active[0]["source_detail"] == "Chemo infusion — Mom",
          f"auto-set carries source + matched event title, got {active}")
    keys = [c.args[0].get("dm_key") or "" for c in post.call_args_list]
    check(len(keys) == 2 and all("kid" not in k for k in keys),
          f"3 days out: adults told (both — nobody set it), kids wait for D-1 digest, got {keys}")
    adult_body = post.call_args_list[0].args[2]
    check("Set from the calendar" in adult_body and "Chemo infusion" in adult_body,
          f"adults told WHICH event matched and how to undo, got {adult_body}")
    # idempotent: a second sweep sets nothing new
    with mock.patch.object(agent_tools_v2, '_post_chat_message') as post:
        check(status_protocols.auto_set_from_calendar(now=NOON) == [],
              "sweep is idempotent — existing day is never re-set or re-announced")
        check(post.call_count == 0, "no duplicate announcements")


def scenario_cleared_calendar_day_never_resets():
    _reset()
    pid = _mk_protocol()
    in2 = (TODAY + datetime.timedelta(days=2)).isoformat()
    storage.set_cached_schedule({
        "events": [{"id": "e1", "title": "chemo", "start": f"{in2}T09:00:00",
                    "end": f"{in2}T10:00:00", "calendar_ids": ["momcal"]}],
        "assignments": {}, "ghost_assignments": {}, "matched_rules": {},
        "scheduled_errands": []})
    with mock.patch.object(agent_tools_v2, '_post_chat_message'):
        created = status_protocols.auto_set_from_calendar(now=NOON)
    check(len(created) == 1, "day auto-set")
    row = storage.delete_status_day(created[0])
    check(storage.status_auto_dismissed(in2, pid), "clearing writes the tombstone")
    with mock.patch.object(agent_tools_v2, '_post_chat_message'):
        check(status_protocols.auto_set_from_calendar(now=NOON) == [],
              "a parent's dismissal is FINAL — the sweep never re-sets it")
    # a manually-cleared MANUAL day leaves no tombstone (only calendar-set days)
    manual_id = storage.add_status_day({"date": TODAY.isoformat(), "protocol_id": pid})
    storage.delete_status_day(manual_id)
    check(not storage.status_auto_dismissed(TODAY.isoformat(), pid),
          "manual days don't tombstone (setting again later is normal use)")


def scenario_solver_feed_cover_and_help_only():
    _reset()
    cover = _mk_protocol()                                   # need=cover, Mom (d2)
    space = _mk_protocol(name="Rest Evening", need="give_space")
    helpp = _mk_protocol(name="Care Day", need="help", member_id="dadm")
    nodrv = _mk_protocol(name="Grandma Day", need="cover", member_id=None)
    d1 = TODAY.isoformat()
    d2 = TOMORROW.isoformat()
    storage.add_status_day({"date": d1, "protocol_id": cover})
    storage.add_status_day({"date": d1, "protocol_id": space})
    storage.add_status_day({"date": d2, "protocol_id": helpp})
    storage.add_status_day({"date": d2, "protocol_id": nodrv})
    feed = status_protocols.unavailable_driver_dates(d1, d2)
    check(len(feed) == 2, f"cover+help feed the solver; give_space and no-driver don't, got {feed}")
    by_date = {f["date"]: f for f in feed}
    check(by_date[d1]["driver_id"] == "d2" and "Chemo Day" in by_date[d1]["label"],
          f"cover -> Mom's driver out today, got {by_date[d1]}")
    check(by_date[d2]["driver_id"] == "d1" and "Care Day" in by_date[d2]["label"],
          f"help -> the cared-for member's driver out, got {by_date[d2]}")
    # the synthetic rule shape actually bans through the matcher
    from models.schemas import Rule, Event
    import solver.matcher as matcher
    rule = Rule(driver_id="d2", constraint_type="unavailable",
                start_date=d1, end_date=d1)
    ev_today = Event(id="x", title="Anything", source_event_ids=["c::x"],
                     start=datetime.datetime.combine(TODAY, datetime.time(16, 0)),
                     end=datetime.datetime.combine(TODAY, datetime.time(17, 0)), calendar_ids=["cal1"])
    ev_tmrw = Event(id="y", title="Anything", source_event_ids=["c::y"],
                    start=datetime.datetime.combine(TOMORROW, datetime.time(16, 0)),
                    end=datetime.datetime.combine(TOMORROW, datetime.time(17, 0)), calendar_ids=["cal1"])
    check(matcher.does_event_match_rule(ev_today, rule),
          "date-only unavailable rule matches every event that day")
    check(not matcher.does_event_match_rule(ev_tmrw, rule),
          "and nothing on any other day")


def scenario_status_mutations_invalidate_schedule_cache():
    _reset()
    pid = _mk_protocol()
    storage.set_cached_schedule({"events": [], "assignments": {},
                                 "matched_rules": {}, "scheduled_errands": []})
    with storage.db_lock:
        storage.cache_table.insert({"probe": True})
        n_before = len(storage.cache_table.all())
    day_id = storage.add_status_day({"date": TODAY.isoformat(), "protocol_id": pid})
    with storage.db_lock:
        check(len(storage.cache_table.all()) == 0,
              f"setting a day truncates the schedule cache (was {n_before})")
        storage.cache_table.insert({"probe": True})
    storage.delete_status_day(day_id)
    with storage.db_lock:
        check(len(storage.cache_table.all()) == 0, "clearing a day truncates it too")


# --- P3: the trip timeline ---

def scenario_span_positions_and_call_window():
    _reset()
    pid = _mk_protocol(name="Work Trip", emoji="🧳", member_id="dadm",
                       need="cover", call_time="19:30",
                       kid_message="Dad's off to the game studio — "
                                   "he'll call every night!")
    d0 = TODAY
    d3 = TODAY + datetime.timedelta(days=3)
    storage.add_status_day({"date": d0.isoformat(), "protocol_id": pid,
                            "end_date": d3.isoformat()})
    # day 1: the full family message + soft call window
    l0 = status_protocols.kid_lines(d0.isoformat())
    check(l0[0] == "🧳 Dad's off to the game studio — he'll call every night!"
          and l0[1] == "📞 Around 7:30 PM — call with Dad",
          f"day 1: family's words + soft call window, got {l0}")
    # middle day: light count line, call window still there
    l1 = status_protocols.kid_lines((d0 + datetime.timedelta(days=1)).isoformat())
    check(l1[0] == "🧳 Work Trip — day 2 of 4" and "📞" in l1[1],
          f"middle day counts, got {l1}")
    # home day: excitement, NO call line (they're walking in the door)
    l3 = status_protocols.kid_lines(d3.isoformat())
    check(l3 == ["🏠 Dad — home day! 🎉"], f"home day is the celebration, got {l3}")
    # day after: clean (spans are date-bound too)
    check(status_protocols.kid_lines((d3 + datetime.timedelta(days=1)).isoformat()) == [],
          "day after the span is a normal day")
    # positions ride the payload for the banner
    mid = status_protocols.active_statuses((d0 + datetime.timedelta(days=1)).isoformat())[0]
    check(mid["day_pos"] == 2 and mid["day_count"] == 4 and not mid["is_home_day"],
          f"banner gets day_pos/day_count, got {mid['day_pos']}/{mid['day_count']}")


def scenario_span_announce_and_agent_span():
    _reset()
    _mk_protocol(name="Work Trip", emoji="🧳", member_id="dadm", need="cover",
                 call_time="19:30", kid_message="Dad's away for work.")
    fri = TODAY + datetime.timedelta(days=2)
    # The agent tool announces with wall-clock now — pin the kid quiet-hours
    # gate open so an evening test run doesn't skip the kid DM (real flake).
    with mock.patch.object(agent_tools_v2, '_post_chat_message') as post, \
         mock.patch('services.family_digest.in_kid_quiet_hours',
                    return_value=False):
        r = agent_tools_v2.set_household_status(
            "work trip", "today", end_date=fri.isoformat(),
            acting_member=storage.get_member("momm"))
    check(r["status"] == "success" and "through" in r["message"],
          f"agent sets a span, got {r}")
    kid_bodies = [c.args[2] for c in post.call_args_list
                  if "kid1" in (c.args[0].get("dm_key") or "")]
    check(kid_bodies and "🏠 Home" in kid_bodies[0] and "📞" in kid_bodies[0],
          f"kid heads-up carries the whole span: home day + call ritual, got {kid_bodies}")
    # backwards span rejected
    r = agent_tools_v2.set_household_status("work trip", fri.isoformat(),
                                            end_date=TODAY.isoformat())
    check(r["status"] == "error", "a span ending before it starts is refused")
    # solver feed covers every day of the span (per-date since beats can
    # vary the need day-by-day)
    feed = status_protocols.unavailable_driver_dates(TODAY.isoformat(), fri.isoformat())
    expect = [(TODAY + datetime.timedelta(days=i)).isoformat() for i in range(3)]
    check(sorted(f["date"] for f in feed) == expect
          and all(f["driver_id"] == "d1" for f in feed),
          f"every span day bans Dad's driver, got {feed}")


def scenario_sweep_collapses_trip_slices():
    _reset()
    pid = _mk_protocol(name="Work Trip", emoji="🧳", member_id="dadm",
                       need="cover", keywords=["studio summit"])
    d1 = TODAY + datetime.timedelta(days=1)
    d2 = TODAY + datetime.timedelta(days=2)
    d3 = TODAY + datetime.timedelta(days=3)
    storage.set_cached_schedule({
        "events": [
            {"id": "trip1_slice_0", "title": "Studio Summit ✈️", "event_type": "background_trip",
             "start": f"{d1}T09:00:00", "end": f"{d1}T23:59:00"},
            {"id": "trip1_slice_1", "title": "Studio Summit ✈️", "event_type": "background_trip",
             "start": f"{d2}T00:00:00", "end": f"{d2}T23:59:00"},
            {"id": "trip1_slice_2", "title": "Studio Summit ✈️", "event_type": "background_trip",
             "start": f"{d3}T00:00:00", "end": f"{d3}T18:00:00"},
        ],
        "assignments": {}, "ghost_assignments": {}, "matched_rules": {},
        "scheduled_errands": []})
    with mock.patch.object(agent_tools_v2, '_post_chat_message'):
        created = status_protocols.auto_set_from_calendar(now=NOON)
    check(len(created) == 1, f"3 cached slices -> ONE span, got {len(created)}")
    days = storage.get_status_days()
    check(days[0]["date"] == d1.isoformat() and days[0]["end_date"] == d3.isoformat(),
          f"span covers the whole trip, got {days[0]}")


def scenario_coverage_report_plan_assist():
    _reset()
    pid = _mk_protocol(name="Work Trip", emoji="🧳", member_id="momm", need="cover")
    d1 = (TODAY + datetime.timedelta(days=1)).isoformat()
    d2 = (TODAY + datetime.timedelta(days=2)).isoformat()
    storage.add_status_day({"date": d1, "protocol_id": pid, "end_date": d2})
    storage.set_cached_schedule({
        "events": [
            {"id": "swim", "title": "Swim Practice", "start": f"{d1}T15:15:00",
             "end": f"{d1}T16:00:00", "calendar_ids": ["cal1"]},
            {"id": "piano", "title": "Piano", "start": f"{d2}T16:00:00",
             "end": f"{d2}T17:00:00", "calendar_ids": ["cal1"]},
            {"id": "out", "title": "Outside the span", "start": f"{TODAY}T10:00:00",
             "end": f"{TODAY}T11:00:00", "calendar_ids": ["cal1"]},
        ],
        "assignments": {"swim": "d1"}, "ghost_assignments": {},
        "matched_rules": {}, "scheduled_errands": []})
    with mock.patch.object(agent_tools_v2, '_post_chat_message') as post:
        sent = status_protocols.send_coverage_reports(now=NOON)
    check(len(sent) == 1, f"one report per instance, got {sent}")
    keys = [c.args[0].get("dm_key") or "" for c in post.call_args_list]
    check(len(keys) == 1 and "dadm" in keys[0] and "momm" not in keys[0],
          f"report goes to the OTHER adult, never the traveler, got {keys}")
    body = post.call_args_list[0].args[2]
    check("Coverage while Mom's out" in body and "Swim Practice — Dad" in body
          and "Piano — ⚠️ needs a driver" in body and "Outside the span" not in body,
          f"resolved drivers + flagged gaps, span-scoped, got {body}")
    check("1 still need a driver" in body, f"collision count surfaces, got {body}")
    # once per instance
    with mock.patch.object(agent_tools_v2, '_post_chat_message') as post:
        check(status_protocols.send_coverage_reports(now=NOON) == [],
              "report is once per instance")
        check(post.call_count == 0, "no repeat DMs")
    # give_space days never generate one
    calm = _mk_protocol(name="Rest Evening", need="give_space")
    storage.add_status_day({"date": d1, "protocol_id": calm})
    with mock.patch.object(agent_tools_v2, '_post_chat_message') as post:
        check(status_protocols.send_coverage_reports(now=NOON) == [],
              "give_space has no coverage to report")


def scenario_coverage_waits_for_resolve():
    _reset()
    pid = _mk_protocol(need="cover")
    d1 = (TODAY + datetime.timedelta(days=1)).isoformat()
    storage.add_status_day({"date": d1, "protocol_id": pid})
    storage.set_cached_schedule({})  # caches truncated, re-solve pending
    with mock.patch.object(agent_tools_v2, '_post_chat_message') as post:
        check(status_protocols.send_coverage_reports(now=NOON) == [],
              "empty cache -> no report yet")
        check(post.call_count == 0, "nothing sent")
    # marker NOT set: the next sweep (post-solve) still reports
    storage.set_cached_schedule({
        "events": [], "assignments": {"x": "d1"}, "ghost_assignments": {},
        "matched_rules": {}, "scheduled_errands": []})
    with mock.patch.object(agent_tools_v2, '_post_chat_message'):
        check(len(status_protocols.send_coverage_reports(now=NOON)) == 1,
              "report fires once the schedule is solved again")


# --- Beat timelines: (when, who, what) relative to the event ---

CHEMO_BEATS = [
    # The arc the fixed positional model couldn't express: the event is ONE
    # day, but the family's timeline isn't — and the hard days come after.
    {"anchor": "start", "offset_days": 1, "audience": "kids", "need": "cover",
     "message": "Mom's extra tired today — this is the rest day. "
                "Quiet afternoon, and she'd love a hug when you get home."},
    {"anchor": "start", "offset_days": 1, "audience": "adults", "need": None,
     "message": "Rough day — keep her hydrated, meds at 6."},
    {"anchor": "start", "offset_days": 3, "audience": "kids", "need": "give_space",
     "message": "Mom's feeling better today — she might even want a board game."},
    {"anchor": "start", "offset_days": 1, "audience": "affected", "need": None,
     "message": "Rest day. The schedule's covered — don't even look at it. 💙"},
]


def scenario_beats_chemo_recovery_arc():
    _reset()
    pid = _mk_protocol(beats=CHEMO_BEATS)  # 1-day event, need=cover
    storage.add_status_day({"date": TODAY.isoformat(), "protocol_id": pid})
    d1 = (TODAY + datetime.timedelta(days=1)).isoformat()
    d2 = (TODAY + datetime.timedelta(days=2)).isoformat()
    d3 = (TODAY + datetime.timedelta(days=3)).isoformat()
    d4 = (TODAY + datetime.timedelta(days=4)).isoformat()
    # day 0: protocol's own words (no beat on the day itself)
    check(status_protocols.kid_lines(TODAY.isoformat())[0].startswith("💙 Mom's resting"),
          "treatment day keeps the protocol's main message")
    # day +1: the beat's words — OUTSIDE the 1-day event's own dates
    l1 = status_protocols.kid_lines(d1)
    check(l1 == ["💙 Mom's extra tired today — this is the rest day. "
                 "Quiet afternoon, and she'd love a hug when you get home."],
          f"day+1 beat reaches past the event, got {l1}")
    # day +2: no beat, outside span -> silence (never invent a line)
    check(status_protocols.kid_lines(d2) == [], "no beat on day+2 -> normal day")
    # day +3: the recovery beat
    check("board game" in status_protocols.kid_lines(d3)[0], "day+3 recovery words")
    check(status_protocols.kid_lines(d4) == [], "timeline ends when the beats do")
    # an adults-only beat day shows nothing to kids
    active_d1 = status_protocols.active_statuses(d1)[0]
    check("hydrated" in active_d1["beat_adult_message"]
          and "hydrated" not in active_d1["beat_kid_message"],
          "audiences stay separate")


def scenario_beat_need_overrides_drive_solver():
    _reset()
    pid = _mk_protocol(beats=CHEMO_BEATS)  # protocol need=cover (Mom, d2)
    storage.add_status_day({"date": TODAY.isoformat(), "protocol_id": pid})
    end = (TODAY + datetime.timedelta(days=4)).isoformat()
    feed = status_protocols.unavailable_driver_dates(TODAY.isoformat(), end)
    by_date = {f["date"]: f for f in feed}
    d1 = (TODAY + datetime.timedelta(days=1)).isoformat()
    d3 = (TODAY + datetime.timedelta(days=3)).isoformat()
    # Written before the load arc, this asserted day+3's `give_space` beat
    # FREED the driver entirely, because back then give_space emitted nothing
    # at all. A6 gave it teeth — the design doc had promised "the solver
    # protects the evening" and the code never did — so it now bans the
    # EVENING only. Whole-day on cover, 17:00-on for give_space: banning the
    # school run too would overshoot the family's own words.
    check(sorted(by_date) == [TODAY.isoformat(), d1, d3],
          f"cover on days 0 and 1, evening-only on day 3, got {sorted(by_date)}")
    for whole in (TODAY.isoformat(), d1):
        check('time_start' not in by_date[whole],
              f"{whole} is a cover day and must ban the whole day")
    check(by_date[d3].get('time_start') == '17:00'
          and by_date[d3].get('time_end') == '23:59',
          f"give_space must protect the evening only, got {by_date[d3]}")
    check('(evening)' in by_date[d3]['label'],
          f"the evening ban does not say so: {by_date[d3]['label']}")
    # inside a span, a beat can RELAX the default: 3-day cover span, day 2
    # beat says give_space -> day 2 is drivable
    _reset()
    relax = [{"anchor": "start", "offset_days": 1, "audience": "kids",
              "need": "give_space", "message": "Feeling better already."}]
    pid = _mk_protocol(name="Recovery", beats=relax)
    d_end = (TODAY + datetime.timedelta(days=2)).isoformat()
    storage.add_status_day({"date": TODAY.isoformat(), "protocol_id": pid,
                            "end_date": d_end})
    feed = status_protocols.unavailable_driver_dates(TODAY.isoformat(), d_end)
    by_date = {f["date"]: f for f in feed}
    mid = (TODAY + datetime.timedelta(days=1)).isoformat()
    check(sorted(by_date) == [TODAY.isoformat(), mid, d_end],
          f"all three days appear; the middle one relaxed, got {sorted(by_date)}")
    check(by_date[mid].get('time_start') == '17:00',
          f"the middle day's beat relaxes a cover span to evening-only, "
          f"got {by_date[mid]}")
    check('time_start' not in by_date[TODAY.isoformat()]
          and 'time_start' not in by_date[d_end],
          "the days either side of the relaxed one are still full cover")


def scenario_beat_dms_audiences_once():
    _reset()
    pid = _mk_protocol(beats=CHEMO_BEATS)
    yesterday = (TODAY - datetime.timedelta(days=1)).isoformat()
    storage.add_status_day({"date": yesterday, "protocol_id": pid})
    # today is beat day +1: adults beat + affected beat due
    with mock.patch.object(agent_tools_v2, '_post_chat_message') as post:
        sent = status_protocols.send_beat_dms(now=NOON)
    check(len(sent) == 2, f"two non-kid beats today (adults + affected), got {sent}")
    bodies = {}
    for c in post.call_args_list:
        for m_id in ("dadm", "momm", "kid1", "kid2"):
            if m_id in (c.args[0].get("dm_key") or ""):
                bodies.setdefault(m_id, []).append(c.args[2])
    check(set(bodies) == {"dadm", "momm"}, f"kid beats never DM (surfaces carry them), got {set(bodies)}")
    check(any("hydrated" in b for b in bodies["dadm"])
          and not any("hydrated" in b for b in bodies["momm"]),
          "adults beat goes to the co-parent, not the affected member")
    check(any("don't even look" in b for b in bodies["momm"]),
          "affected beat reaches the member themselves")
    with mock.patch.object(agent_tools_v2, '_post_chat_message') as post:
        check(status_protocols.send_beat_dms(now=NOON) == [], "beats DM once")
        check(post.call_count == 0, "no repeats")


def scenario_beats_backward_compat_and_banner_fields():
    _reset()
    # no beats -> P3 positional behavior byte-identical
    pid = _mk_protocol(name="Work Trip", emoji="🧳", member_id="dadm",
                       call_time="19:30")
    d2 = (TODAY + datetime.timedelta(days=2)).isoformat()
    storage.add_status_day({"date": TODAY.isoformat(), "protocol_id": pid,
                            "end_date": d2})
    mid = (TODAY + datetime.timedelta(days=1)).isoformat()
    l = status_protocols.kid_lines(mid)
    check(l[0] == "🧳 Work Trip — day 2 of 3" and "📞" in l[1],
          f"beat-less protocols keep the positional timeline, got {l}")
    # a beat on the middle day replaces the count line but keeps the call line
    storage.update_status_protocol(pid, {"beats": [
        {"anchor": "start", "offset_days": 1, "audience": "kids",
         "message": "Dad lands in Kyoto today — ask him about the trains!", "need": None}]})
    l = status_protocols.kid_lines(mid)
    check(l[0] == "🧳 Dad lands in Kyoto today — ask him about the trains!"
          and "📞" in l[1],
          f"authored beat replaces the default line, call window stays, got {l}")
    s = status_protocols.active_statuses(mid)[0]
    check(s["within_span"] and s["beat_kid_message"].startswith("Dad lands"),
          "banner payload carries within_span + beat messages")


def scenario_prep_beats_before_the_event():
    _reset()
    beats = [
        {"anchor": "start", "offset_days": -2, "audience": "adults", "need": None,
         "message": "Prep day — pack the hospital bag, lay out the meds list."},
        {"anchor": "start", "offset_days": -1, "audience": "kids", "need": None,
         "message": "Tomorrow's Mom's treatment day — tonight is movie night, "
                    "your pick."},
    ]
    pid = _mk_protocol(beats=beats)
    in2 = (TODAY + datetime.timedelta(days=2)).isoformat()
    storage.add_status_day({"date": in2, "protocol_id": pid})
    # start-2 == today: the adults' prep beat DMs today, nothing to kids
    with mock.patch.object(agent_tools_v2, '_post_chat_message') as post:
        sent = status_protocols.send_beat_dms(now=NOON)
    check(len(sent) == 1, f"prep beat fires two days BEFORE the event, got {sent}")
    keys = [c.args[0].get("dm_key") or "" for c in post.call_args_list]
    check(all("kid" not in k for k in keys) and any("dadm" in k for k in keys),
          f"prep logistics go to adults only, got {keys}")
    check(status_protocols.kid_lines(TODAY.isoformat()) == [],
          "an adults-only prep day shows kids nothing")
    # start-1: the kids' own pre-event beat rides their surfaces
    in1 = (TODAY + datetime.timedelta(days=1)).isoformat()
    l = status_protocols.kid_lines(in1)
    check(l == ["💙 Tomorrow's Mom's treatment day — tonight is movie night, "
                "your pick."],
          f"kids' before-beat lands on their surfaces, got {l}")
    # and no driver ban leaks backward: prep days are message-only
    feed = status_protocols.unavailable_driver_dates(TODAY.isoformat(), in2)
    check([f["date"] for f in feed] == [in2],
          f"only the event day itself bans the driver, got {feed}")


SCENARIOS = [
    scenario_prep_beats_before_the_event,
    scenario_day_dedupe_and_protocol_cascade,
    scenario_date_bound_resolution,
    scenario_digest_leads_with_status_and_includes_every_kid,
    scenario_dismissal_push_carries_status,
    scenario_announce_set_audiences_and_quiet_hours,
    scenario_announce_cleared_correction,
    scenario_agent_tool_set_get_clear,
    scenario_member_day_carries_status,
    scenario_calendar_sweep_auto_sets,
    scenario_cleared_calendar_day_never_resets,
    scenario_solver_feed_cover_and_help_only,
    scenario_status_mutations_invalidate_schedule_cache,
    scenario_span_positions_and_call_window,
    scenario_span_announce_and_agent_span,
    scenario_sweep_collapses_trip_slices,
    scenario_coverage_report_plan_assist,
    scenario_coverage_waits_for_resolve,
    scenario_beats_chemo_recovery_arc,
    scenario_beat_need_overrides_drive_solver,
    scenario_beat_dms_audiences_once,
    scenario_beats_backward_compat_and_banner_fields,
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

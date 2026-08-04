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


SCENARIOS = [
    scenario_day_dedupe_and_protocol_cascade,
    scenario_date_bound_resolution,
    scenario_digest_leads_with_status_and_includes_every_kid,
    scenario_dismissal_push_carries_status,
    scenario_announce_set_audiences_and_quiet_hours,
    scenario_announce_cleared_correction,
    scenario_agent_tool_set_get_clear,
    scenario_member_day_carries_status,
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

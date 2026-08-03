"""Tests for family messaging: chat storage (channels/messages/reads) and the
main.py send/fan-out logic. Same harness as test_storage.py: temp data dir,
runs once per storage backend.

Run from chauffeur/:  python tests/test_messaging.py
"""
import atexit
import os
import shutil
import sys
import tempfile
import time
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="chauffeur_messaging_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import storage  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def reset_db():
    with storage.db_lock:
        for name, val in list(vars(storage).items()):
            if name.endswith("_table"):
                val.truncate()
    storage._distance_mem_cache = None


def _member(mid, name, **kw):
    doc = {"id": mid, "name": name, "color_code": "#3b82f6", "avatar": None,
           "bio": "", "can_drive": False, "is_child": False, "driver_id": None,
           "passenger_id": None, "ha_person_entity": None, "notify_service": None,
           "media_player_entity": None, "pin": None, "created_at": time.time()}
    doc.update(kw)
    storage.add_member(doc)
    return doc


def scenario_family_channel_singleton():
    storage.ensure_family_channel()
    storage.ensure_family_channel()
    fam = storage.get_family_channel()
    check(fam and fam["kind"] == "family" and fam["member_ids"] == [],
          "family channel exists, implicit-everyone")
    check(len([c for c in storage.get_channels_for_member("anyone") if c["kind"] == "family"]) == 1,
          "exactly one family channel")


def scenario_dm_get_or_create():
    a = storage.get_or_create_dm("m2", "m1")
    b = storage.get_or_create_dm("m1", "m2")
    check(a["id"] == b["id"], "dm is order-insensitive get-or-create")
    check(a["member_ids"] == ["m1", "m2"] and a["dm_key"] == "m1:m2", "canonical pair")
    c = storage.get_or_create_dm("m1", "m3")
    check(c["id"] != a["id"], "different pair -> different channel")


def scenario_group_get_or_create():
    a = storage.get_or_create_group(["m3", "m1", "m2"])
    b = storage.get_or_create_group(["m2", "m3", "m1", "m1"])
    check(a["id"] == b["id"], "group is order/dupe-insensitive get-or-create")
    check(a["kind"] == "group" and a["member_ids"] == ["m1", "m2", "m3"]
          and a["dm_key"] == "m1:m2:m3", "canonical sorted member set")
    c = storage.get_or_create_group(["m1", "m2", "m4"])
    check(c["id"] != a["id"], "different member set -> different group")
    named = storage.get_or_create_group(["m1", "m2", "m3"], title="Parents")
    check(named["id"] == a["id"] and named["title"] == "Parents",
          "provided title refreshes the existing group's name")
    dm = storage.get_or_create_dm("m1", "m2")
    check(dm["id"] != a["id"] and dm["kind"] == "dm",
          "dm and group keys never collide (2 vs 3+ ids)")


def scenario_group_visibility():
    g = storage.get_or_create_group(["m1", "m2", "m3"])
    check(any(c["id"] == g["id"] for c in storage.get_channels_for_member("m2")),
          "group member sees the group")
    check(all(c["id"] != g["id"] for c in storage.get_channels_for_member("m4")),
          "non-member does not see the group")


def scenario_group_endpoint_validations():
    import main
    from fastapi import BackgroundTasks, HTTPException

    _member("mom", "Mom", role="parent")
    _member("dad", "Dad", role="parent")
    _member("kid", "Kid", role="child")
    _member("uber", "Hired Driver", role="helper")
    bt = BackgroundTasks()

    g = main.create_group_channel(main.GroupChannelRequest(
        member_id="mom", member_ids=["dad", "kid"], title="  Weekend plans "))
    check(sorted(g["member_ids"]) == ["dad", "kid", "mom"],
          "creator always included in the group")
    check(g["title"] == "Weekend plans", "title trimmed")

    for req, expect in [
        (main.GroupChannelRequest(member_id="mom", member_ids=["dad"]), 400),
        (main.GroupChannelRequest(member_id="mom", member_ids=["dad", "ghost"]), 404),
        (main.GroupChannelRequest(member_id="mom", member_ids=["dad", "uber"]), 403),
        (main.GroupChannelRequest(member_id="uber", member_ids=["mom", "dad"]), 403),
    ]:
        try:
            main.create_group_channel(req)
            check(False, f"expected HTTPException {expect}")
        except HTTPException as e:
            check(e.status_code == expect, f"expected {expect}, got {e.status_code}")

    # posting: members only; SSE event addressed to the member set
    main.send_message(g["id"], main.SendMessageRequest(
        sender_member_id="kid", body="pool day?"), bt)
    check(main.MESSAGE_EVENTS[-1]["recipients"] == ["dad", "kid", "mom"],
          "group SSE event addressed to the member set")
    try:
        main.send_message(g["id"], main.SendMessageRequest(
            sender_member_id="uber", body="intrude"), bt)
        check(False, "expected 403")
    except HTTPException as e:
        check(e.status_code == 403, "non-member cannot post in a group")

    # fan-out: only group members (minus sender), title includes group name
    from services import ha_api
    with mock.patch.object(main, 'send_push_to_member') as push, \
         mock.patch.object(ha_api, 'call_service'):
        main._fanout_message_notifications(g, {"sender_member_id": "mom", "body": "pool!"})
        pushed = sorted(c.args[0] for c in push.call_args_list)
        check(pushed == ["dad", "kid"], f"group fan-out to members minus sender, got {pushed}")
        check(push.call_args_list[0].args[1] == "Mom · Weekend plans",
              "group push title includes the group name")


def scenario_event_channel_lifecycle():
    ch = storage.get_or_create_event_channel("evt1", "Soccer", "2126-01-01T18:00:00")
    same = storage.get_or_create_event_channel("evt1", "Soccer (moved)", None)
    check(ch["id"] == same["id"], "event channel get-or-create by event id")
    check(same["title"] == "Soccer (moved)", "title snapshot refreshes")

    # ended long ago -> archived on the way out of the channel list
    old = storage.get_or_create_event_channel("evt-old", "Old", "2020-01-01T10:00:00")
    visible = storage.get_channels_for_member("m1")
    check(all(c["id"] != old["id"] for c in visible), "stale event thread hidden")
    check(storage.get_channel(old["id"])["archived"], "stale event thread archived")
    check(any(c["id"] == ch["id"] for c in visible), "future event thread visible")


def scenario_dm_visibility():
    dm = storage.get_or_create_dm("m1", "m2")
    check(any(c["id"] == dm["id"] for c in storage.get_channels_for_member("m1")),
          "participant sees dm")
    check(all(c["id"] != dm["id"] for c in storage.get_channels_for_member("m3")),
          "non-participant does not see dm")


def scenario_messages_order_limit_after():
    for i in range(5):
        storage.add_chat_message({"id": f"msg{i}", "channel_id": "ch1",
                                  "sender_member_id": "m1", "ts": 100.0 + i,
                                  "type": "text", "body": f"b{i}", "attachment": None})
    msgs = storage.get_channel_messages("ch1")
    check([m["id"] for m in msgs] == [f"msg{i}" for i in range(5)], "ascending by ts")
    check([m["id"] for m in storage.get_channel_messages("ch1", limit=2)] == ["msg3", "msg4"],
          "limit keeps the newest, still ascending")
    check([m["id"] for m in storage.get_channel_messages("ch1", after_ts=102.0)] == ["msg3", "msg4"],
          "after_ts filters strictly-greater")
    check(storage.get_channel_messages("other") == [], "unknown channel -> []")


def scenario_retention_cap():
    cap = storage._MESSAGES_PER_CHANNEL_CAP
    for i in range(cap + 10):
        storage.add_chat_message({"id": f"m{i}", "channel_id": "big",
                                  "sender_member_id": "m1", "ts": float(i),
                                  "type": "text", "body": "x", "attachment": None})
    msgs = storage.get_channel_messages("big", limit=0)
    check(len(msgs) == cap, f"cap enforced, got {len(msgs)}")
    check(msgs[0]["id"] == "m10", "oldest overflow trimmed first")


def scenario_unread_counts_and_reads():
    storage.ensure_family_channel()
    fam = storage.get_family_channel()
    for i in range(3):
        storage.add_chat_message({"id": f"f{i}", "channel_id": fam["id"],
                                  "sender_member_id": "m1", "ts": 100.0 + i,
                                  "type": "text", "body": "hi", "attachment": None})
    counts = storage.get_unread_counts("m2")
    check(counts.get(fam["id"]) == 3, "all unread for m2")
    check(storage.get_unread_counts("m1").get(fam["id"]) == 0,
          "sender's own messages never count as unread")
    storage.set_last_read(fam["id"], "m2", 101.0)
    check(storage.get_unread_counts("m2").get(fam["id"]) == 1, "read cursor respected")
    storage.set_last_read(fam["id"], "m2", 102.0)
    check(storage.get_unread_counts("m2").get(fam["id"]) == 0, "fully read")


def scenario_send_message_endpoint_validations():
    import main
    from fastapi import BackgroundTasks, HTTPException

    _member("m1", "Jeff")
    _member("m2", "Amy")
    _member("m3", "Ben")
    storage.ensure_family_channel()
    fam = storage.get_family_channel()
    bt = BackgroundTasks()

    msg = main.send_message(fam["id"], main.SendMessageRequest(
        sender_member_id="m1", body="  hello  "), bt)
    check(msg["body"] == "hello" and msg["channel_id"] == fam["id"], "message stored trimmed")
    check(storage.get_unread_counts("m1").get(fam["id"]) == 0,
          "sender auto-marked read")
    check(main.MESSAGE_EVENTS and main.MESSAGE_EVENTS[-1]["channel_id"] == fam["id"]
          and main.MESSAGE_EVENTS[-1]["recipients"] is None,
          "family message SSE event addressed to everyone")

    dm = storage.get_or_create_dm("m1", "m2")
    main.send_message(dm["id"], main.SendMessageRequest(
        sender_member_id="m2", body="psst"), bt)
    check(main.MESSAGE_EVENTS[-1]["recipients"] == ["m1", "m2"],
          "dm SSE event addressed to the pair")

    for bad_call, expect in [
        (lambda: main.send_message("ghost", main.SendMessageRequest(
            sender_member_id="m1", body="x"), bt), 404),
        (lambda: main.send_message(fam["id"], main.SendMessageRequest(
            sender_member_id="m1", body="   "), bt), 400),
        (lambda: main.send_message(dm["id"], main.SendMessageRequest(
            sender_member_id="m3", body="intrude"), bt), 403),
        (lambda: main.send_message(fam["id"], main.SendMessageRequest(
            sender_member_id="ghost", body="x"), bt), 404),
    ]:
        try:
            bad_call()
            check(False, f"expected HTTPException {expect}")
        except HTTPException as e:
            check(e.status_code == expect, f"expected {expect}, got {e.status_code}")


def scenario_fanout_recipients():
    import main
    from services import ha_api

    _member("m1", "Jeff")
    _member("m2", "Amy", notify_service="notify.mobile_app_amy")
    _member("m3", "Ben")
    storage.ensure_family_channel()
    fam = storage.get_family_channel()
    message = {"sender_member_id": "m1", "body": "dinner!", "ts": time.time()}

    with storage.db_lock:
        storage.settings_table.insert({"public_base_url": "https://fam.example.com"})

    with mock.patch.object(main, 'send_push_to_member') as push, \
         mock.patch.object(ha_api, 'call_service') as ha_call:
        main._fanout_message_notifications(fam, message)
        pushed = sorted(c.args[0] for c in push.call_args_list)
        check(pushed == ["m2", "m3"], f"family push to everyone but sender, got {pushed}")
        check(ha_call.call_count == 1, "HA notify only for members with notify_service")
        args, _ = ha_call.call_args
        check(args[0] == 'notify' and args[1] == 'mobile_app_amy', "notify service parsed")
        check(args[2]["data"]["url"].startswith("https://fam.example.com/app?open_channel="),
              "HA companion deep link uses public_base_url (no origin context)")
        web_push_url = push.call_args_list[0].args[3]
        check(web_push_url.startswith("/app?open_channel="),
              f"web push deep link stays RELATIVE (sw navigates on the PWA's own "
              f"origin — absolute links 404 when origins mismatch), got {web_push_url}")
        _, first_push = push.call_args_list[0].args[0], push.call_args_list[0]
        check(first_push.args[1] == "Jeff · Family", "family title includes sender")

    dm = storage.get_or_create_dm("m1", "m2")
    with mock.patch.object(main, 'send_push_to_member') as push, \
         mock.patch.object(ha_api, 'call_service'):
        main._fanout_message_notifications(dm, message)
        check([c.args[0] for c in push.call_args_list] == ["m2"],
              "dm push only to the other participant")
        check(push.call_args_list[0].args[1] == "Jeff", "dm title is the sender name")


def scenario_helper_restrictions():
    import main
    from fastapi import BackgroundTasks, HTTPException

    _member("mom", "Mom", role="parent")
    _member("kid", "Kid", role="child")
    _member("uber", "Hired Driver", role="helper")
    storage.ensure_family_channel()
    fam = storage.get_family_channel()
    bt = BackgroundTasks()

    # visibility: helper sees only their DMs — no family channel/event threads
    storage.get_or_create_event_channel("evt1", "Soccer", "2126-01-01T18:00:00")
    helper_dm = storage.get_or_create_dm("uber", "mom")
    kinds = {c["kind"] for c in storage.get_channels_for_member("uber")}
    check(kinds == {"dm"}, f"helper sees DMs only, got {kinds}")
    kid_kinds = {c["kind"] for c in storage.get_channels_for_member("kid")}
    check("family" in kid_kinds and "event" in kid_kinds, "family members unaffected")

    # dm creation: helper<->parent ok (above), helper<->child refused both ways
    for a, b in (("uber", "kid"), ("kid", "uber")):
        try:
            main.create_dm_channel(main.DmChannelRequest(member_id=a, other_member_id=b))
            check(False, "expected 403 for helper-child dm")
        except HTTPException as e:
            check(e.status_code == 403, f"helper-child dm refused ({a}->{b})")
    ok = main.create_dm_channel(main.DmChannelRequest(member_id="mom", other_member_id="uber"))
    check(ok["id"] == helper_dm["id"], "parent-helper dm allowed (get-or-create)")

    # posting: helper can post in their dm, not in the family channel
    main.send_message(helper_dm["id"], main.SendMessageRequest(
        sender_member_id="uber", body="on my way"), bt)
    try:
        main.send_message(fam["id"], main.SendMessageRequest(
            sender_member_id="uber", body="hi fam"), bt)
        check(False, "expected 403")
    except HTTPException as e:
        check(e.status_code == 403, "helper cannot post in family channel")

    # fan-out: family messages never notify helpers
    from services import ha_api
    with mock.patch.object(main, 'send_push_to_member') as push, \
         mock.patch.object(ha_api, 'call_service'):
        main._fanout_message_notifications(fam, {"sender_member_id": "mom", "body": "dinner"})
        pushed = sorted(c.args[0] for c in push.call_args_list)
        check(pushed == ["kid"], f"family fan-out excludes helpers, got {pushed}")


def scenario_empty_channels_hidden_from_list():
    import main
    _member("mom", "Mom", role="parent")
    _member("kid", "Kid", role="child")
    storage.ensure_family_channel()
    fam = storage.get_family_channel()

    # Discuss/Message get-or-create the channel on open; untouched threads
    # must not appear on anyone's list until the first message lands.
    ev = storage.get_or_create_event_channel("evt1", "Soccer", "2126-01-01T18:00:00")
    dm = storage.get_or_create_dm("kid", "mom")
    for mid in ("kid", "mom"):
        ids = {c["id"] for c in main.list_channels(mid)}
        check(fam["id"] in ids, "empty family channel still listed (the hub)")
        check(ev["id"] not in ids, f"empty event thread hidden from {mid}")
        check(dm["id"] not in ids, f"empty DM hidden from {mid}")

    storage.add_chat_message({"id": "e1", "channel_id": ev["id"], "sender_member_id": "mom",
                              "ts": time.time(), "type": "text", "body": "snacks?", "attachment": None})
    storage.add_chat_message({"id": "d1", "channel_id": dm["id"], "sender_member_id": "kid",
                              "ts": time.time(), "type": "text", "body": "hi", "attachment": None})
    for mid in ("kid", "mom"):
        ids = {c["id"] for c in main.list_channels(mid)}
        check(ev["id"] in ids and dm["id"] in ids,
              f"channels appear once the first message lands ({mid})")


SCENARIOS = [
    scenario_family_channel_singleton,
    scenario_helper_restrictions,
    scenario_dm_get_or_create,
    scenario_group_get_or_create,
    scenario_group_visibility,
    scenario_group_endpoint_validations,
    scenario_event_channel_lifecycle,
    scenario_dm_visibility,
    scenario_messages_order_limit_after,
    scenario_retention_cap,
    scenario_unread_counts_and_reads,
    scenario_send_message_endpoint_validations,
    scenario_fanout_recipients,
    scenario_empty_channels_hidden_from_list,
]

if __name__ == "__main__":
    import traceback

    if "CHAUFFEUR_STORAGE" not in os.environ:
        import subprocess
        worst = 0
        for be in ("tinydb", "sqlite"):
            env = dict(os.environ, CHAUFFEUR_STORAGE=be)
            print(f"=== backend: {be} ===")
            rc = subprocess.call([sys.executable, os.path.abspath(__file__)], env=env)
            worst = max(worst, rc)
        raise SystemExit(worst)

    backend = getattr(storage, "BACKEND", "tinydb")
    print(f"storage backend: {backend}  (data dir: {_TMP})")
    failed = 0
    for fn in SCENARIOS:
        try:
            reset_db()
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)

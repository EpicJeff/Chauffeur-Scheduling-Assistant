"""Tests for the Presence slice (docs/presence_status_design.md Slice 4):
photo-moment attachments, the reactions primitive, present/kept-away
resolution from the solved schedule, the capture prompt sweep, the
differentiated moment fan-out, and the kiosk hearth feed.

Run from chauffeur/:  python tests/test_presence.py
"""
import atexit
import datetime
import os
import shutil
import sys
import tempfile
import time
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="chauffeur_presence_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import storage, presence  # noqa: E402


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


_TINY_JPEG = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQ=="


def _family():
    """Mom drives Emma to volleyball; Dad and Grandpa are kept away; Kid2 is
    a kept-away child; a helper exists and must never hear anything."""
    _member("mom", "Mom", role="parent", driver_id="d_mom")
    _member("dad", "Dad", role="parent", driver_id="d_dad")
    _member("gramps", "Grandpa", role="adult")
    _member("emma", "Emma", role="child", is_child=True, passenger_id="p_emma")
    _member("kid2", "Sam", role="child", is_child=True, passenger_id="p_kid2")
    _member("uber", "Hired Driver", role="helper")


def _schedule(now):
    start = now - datetime.timedelta(minutes=5)
    end = now + datetime.timedelta(minutes=85)
    ev = {"id": "vb1", "title": "Emma's Volleyball", "start": start.isoformat(),
          "end": end.isoformat(), "event_type": "standard",
          "calendar_ids": ["p_emma"]}
    storage.set_cached_schedule({"events": [ev], "assignments": {"vb1": "d_mom"},
                                 "ghost_assignments": {}, "matched_rules": {}})
    return ev


def scenario_attachment_send_and_validation():
    import main
    from fastapi import BackgroundTasks, HTTPException
    _member("mom", "Mom", role="parent")
    ch = storage.get_or_create_event_channel("evA", "Soccer")
    bt = BackgroundTasks()

    m = main.send_message(ch["id"], main.SendMessageRequest(
        sender_member_id="mom", body="",
        attachment={"kind": "photo", "data_url": _TINY_JPEG, "w": 4, "h": 4}), bt)
    check(m["attachment"]["kind"] == "photo" and m["attachment"]["w"] == 4,
          "photo attachment persisted, empty body allowed")
    check(m["body"] == "", "caption-less moment keeps empty body")

    for att, code in [
        ({"kind": "video", "data_url": _TINY_JPEG}, 400),
        ({"kind": "photo", "data_url": "http://x/y.jpg"}, 400),
        ({"kind": "photo", "data_url": "data:image/jpeg;base64," + "A" * main._ATTACHMENT_MAX_CHARS}, 413),
    ]:
        try:
            main.send_message(ch["id"], main.SendMessageRequest(
                sender_member_id="mom", body="", attachment=att), bt)
            check(False, f"expected {code}")
        except HTTPException as e:
            check(e.status_code == code, f"attachment junk -> {code}, got {e.status_code}")

    try:
        main.send_message(ch["id"], main.SendMessageRequest(sender_member_id="mom", body="  "), bt)
        check(False, "expected 400")
    except HTTPException as e:
        check(e.status_code == 400, "no body and no attachment stays rejected")


def scenario_reaction_toggle_and_endpoint():
    import main
    from fastapi import HTTPException
    _member("mom", "Mom", role="parent")
    _member("dad", "Dad", role="parent")
    ch = storage.get_or_create_event_channel("evB", "Recital")
    storage.add_chat_message({"id": "msg1", "channel_id": ch["id"], "sender_member_id": "mom",
                              "ts": time.time(), "type": "text", "body": "she nailed it",
                              "attachment": None, "reactions": {}})

    m = main.react_to_message("msg1", main.ReactRequest(member_id="dad", emoji="❤️"))
    check(m["reactions"] == {"❤️": ["dad"]}, "reaction lands")
    m = main.react_to_message("msg1", main.ReactRequest(member_id="mom", emoji="❤️"))
    check(m["reactions"]["❤️"] == ["dad", "mom"], "second member joins the pile")
    m = main.react_to_message("msg1", main.ReactRequest(member_id="dad", emoji="❤️"))
    check(m["reactions"] == {"❤️": ["mom"]}, "same member re-tap toggles OFF")
    m = main.react_to_message("msg1", main.ReactRequest(member_id="mom", emoji="❤️"))
    check(m["reactions"] == {}, "empty emoji lists are pruned")

    for req, code in [
        (main.ReactRequest(member_id="dad", emoji=""), 400),
        (main.ReactRequest(member_id="dad", emoji="waytoolongstring"), 400),
        (main.ReactRequest(member_id="ghost", emoji="❤️"), 404),
    ]:
        try:
            main.react_to_message("msg1", req)
            check(False, f"expected {code}")
        except HTTPException as e:
            check(e.status_code == code, f"react validation -> {code}")
    try:
        main.react_to_message("nope", main.ReactRequest(member_id="dad", emoji="❤️"))
        check(False, "expected 404")
    except HTTPException as e:
        check(e.status_code == 404, "unknown message -> 404")


def scenario_present_and_kept_away():
    _family()
    now = datetime.datetime(2126, 3, 14, 17, 30)
    ev = _schedule(now)

    present = presence.members_at_event(ev, "vb1")
    ids = sorted(m["id"] for m in present)
    check(ids == ["emma", "mom"], f"driver + bound passenger are present, got {ids}")

    ch = storage.get_or_create_event_channel("vb1", "Emma's Volleyball")
    audience = sorted(m["id"] for m in presence.moment_push_audience(ch))
    check(audience == ["dad", "gramps"],
          f"push audience = kept-away ADULTS only (no kids/helpers/present), got {audience}")

    # Old thread whose event left the cache: all non-helper adults hear.
    old = storage.get_or_create_event_channel("gone_ev", "Last week")
    audience = sorted(m["id"] for m in presence.moment_push_audience(old))
    check(audience == ["dad", "gramps", "mom"], "cache-miss falls back to all adults")


def scenario_capture_prompt_sweep():
    _family()
    now = datetime.datetime(2126, 3, 14, 17, 30)
    _schedule(now)
    sent = []

    def send(member, title, body, path):
        sent.append((member["id"], title, body, path))

    prompted = presence.run_capture_prompts(send, now=now)
    check(prompted == ["vb1"], f"live event prompted, got {prompted}")
    check([s[0] for s in sent] == ["mom"], "prompt goes to the present ADULT only")
    check("You're at Emma's Volleyball" in sent[0][1], "prompt names the event")
    check("compose=moment" in sent[0][3] and "open_channel=" in sent[0][3],
          "deeplink arms the camera on the event thread")
    ch = storage.get_channel(sent[0][3].split("open_channel=")[1].split("&")[0])
    check(ch and ch["event_id"] == "vb1", "prompt created/targeted the event channel")

    sent.clear()
    check(presence.run_capture_prompts(send, now=now) == [] and not sent,
          "second sweep is inert (never nag)")


def scenario_capture_prompt_gates():
    _family()
    now = datetime.datetime(2126, 3, 14, 17, 30)

    # Outside the opening window: no prompt.
    ev = _schedule(now)
    late = now + datetime.timedelta(minutes=45)
    check(presence.run_capture_prompts(lambda *a: check(False, "sent"), now=late) == [],
          "no prompt outside the opening window")

    # Errands and short blips never prompt.
    for tweak in ({"event_type": "errand"},
                  {"end": (now + datetime.timedelta(minutes=10)).isoformat()}):
        e2 = dict(ev, **tweak)
        storage.set_cached_schedule({"events": [e2], "assignments": {"vb1": "d_mom"},
                                     "ghost_assignments": {}, "matched_rules": {}})
        storage.set_app_state(presence._MARKER, {})
        check(presence.run_capture_prompts(lambda *a: check(False, "sent"), now=now) == [],
              f"no prompt for {tweak}")

    # Everyone at the event (dad drives the pickup leg, gramps deleted) ->
    # no kept-away adult -> no audience -> no ask.
    storage.set_app_state(presence._MARKER, {})
    ev3 = dict(ev, calendar_ids=["p_emma", "p_kid2"])
    storage.set_cached_schedule({"events": [ev3],
                                 "assignments": {"vb1": "d_mom", "vb1_pickup": "d_dad"},
                                 "ghost_assignments": {}, "matched_rules": {}})
    storage.delete_member("gramps")
    check(presence.run_capture_prompts(lambda *a: check(False, "sent"), now=now) == [],
          "everyone there -> no kept-away adult -> no prompt")


def scenario_prompt_worthiness_gates():
    """Family feedback: no blind nudge on every 30-min event — a doctor's
    appointment must never get 'send the family a moment'."""
    _family()
    now = datetime.datetime(2126, 3, 14, 17, 30)
    today = now.date().isoformat()

    check(presence.prompt_worthiness({"title": "Emma's Volleyball"}, set(), today) == 'moment',
          "sport events are moment-worthy")
    check(presence.prompt_worthiness({"title": "School concert"}, set(), today) == 'moment',
          "performances are moment-worthy")
    check(presence.prompt_worthiness({"title": "Dr. Smith appointment"}, set(), today) == 'blocked',
          "medical events are hard-blocked")
    check(presence.prompt_worthiness({"title": "Study group"}, set(), today) == 'quiet',
          "unknown events stay organic — no ask, thread still open")

    # A status protocol's keyword marks the event as a status matter — the
    # INVERSION owns those days, never the outward capture ask.
    storage.add_status_protocol({"name": "Chemo Day", "emoji": "💙", "member_id": "mom",
                                 "need": "cover", "kid_message": "x", "adult_message": "y",
                                 "keywords": ["chemo"], "enabled": True})
    check(presence.prompt_worthiness({"title": "Chemo infusion"}, set(), today) == 'blocked',
          "medical wording hard-blocks before anything else")
    check(presence.prompt_worthiness({"title": "Mom chemo day — the big game plan"}, set(), today) == 'status',
          "protocol-keyword events are status-suppressed even with allowlist words")

    # The affected member being present suppresses too (their soccer sideline
    # day is not a performance moment).
    pid2 = storage.add_status_protocol({"name": "Rest Day", "emoji": "💤", "member_id": "gramps",
                                        "need": "help", "kid_message": "x", "adult_message": "y",
                                        "keywords": [], "enabled": True})
    storage.add_status_day({"date": today, "protocol_id": pid2, "set_by": "mom"})
    check(presence.prompt_worthiness({"title": "Emma's Volleyball"}, {"gramps"}, today) == 'status',
          "affected-member-present suppresses the outward ask")
    check(presence.prompt_worthiness({"title": "Emma's Volleyball"}, {"mom"}, today) == 'moment',
          "an unrelated present set keeps the moment prompt")

    # End-to-end: a live doctor's appointment never prompts.
    ev = {"id": "doc1", "title": "Emma's doctor appointment",
          "start": (now - datetime.timedelta(minutes=5)).isoformat(),
          "end": (now + datetime.timedelta(minutes=55)).isoformat(),
          "event_type": "standard", "calendar_ids": ["p_emma"]}
    storage.set_cached_schedule({"events": [ev], "assignments": {"doc1": "d_mom"},
                                 "ghost_assignments": {}, "matched_rules": {}})
    check(presence.run_capture_prompts(lambda *a: check(False, "sent"), now=now) == [],
          "live medical event -> no capture prompt")


def scenario_thinking_of_you_inversion():
    """The chemo example runs the other way: 'Mom is at chemo — send her
    something to let her know you're thinking of her.'"""
    _family()
    now = datetime.datetime(2126, 3, 14, 10, 0)
    today = now.date().isoformat()
    pid = storage.add_status_protocol({"name": "Chemo Day", "emoji": "💙", "member_id": "mom",
                                       "need": "cover", "kid_message": "x", "adult_message": "y",
                                       "keywords": ["chemo"], "enabled": True})
    storage.add_status_day({"date": today, "protocol_id": pid, "set_by": "dad"})
    sent = []

    def send(member, title, body, path):
        sent.append((member["id"], title, body, path))

    delivered = presence.run_thinking_of_you_prompts(send, now=now)
    got = sorted(s[0] for s in sent)
    check(got == ["dad", "emma", "gramps", "kid2"],
          f"everyone but the affected member and the helper is prompted, got {got}")
    check(all("Mom" in s[1] and "Chemo Day" in s[1] for s in sent),
          "prompt names the person and the family's own day label")
    check(all("compose=moment" in s[3] and "open_channel=" in s[3] for s in sent),
          "deeplinks arm the camera on each member's DM")
    dm_id = sent[0][3].split("open_channel=")[1].split("&")[0]
    dm = storage.get_channel(dm_id)
    check(dm and dm["kind"] == "dm" and "mom" in dm["member_ids"],
          "target is the sender's own DM WITH the affected member")

    sent.clear()
    check(presence.run_thinking_of_you_prompts(send, now=now) == [] and not sent,
          "second sweep is inert (once per member per day)")

    # Before 9am: nothing (it should land in the day, not at dawn).
    storage.set_app_state(presence._TOY_MARKER, {})
    check(presence.run_thinking_of_you_prompts(send, now=now.replace(hour=7)) == [],
          "too early -> no prompts")

    # Kid quiet hours: kids skip THIS sweep but a later one still delivers.
    storage.set_app_state(presence._TOY_MARKER, {})
    storage.patch_settings({"kid_quiet_start": "20:30", "kid_quiet_end": "07:00"})
    sent.clear()
    late = now.replace(hour=21, minute=0)
    presence.run_thinking_of_you_prompts(send, now=late)
    got = sorted(s[0] for s in sent)
    check(got == ["dad", "gramps"], f"quiet hours: adults only, got {got}")
    # give_space protocols never generate the prompt — the family said space.
    storage.patch_settings({"kid_quiet_start": "00:00", "kid_quiet_end": "00:00"})
    pid2 = storage.add_status_protocol({"name": "Space Day", "emoji": "🤫", "member_id": "dad",
                                        "need": "give_space", "kid_message": "x",
                                        "adult_message": "y", "keywords": [], "enabled": True})
    storage.add_status_day({"date": today, "protocol_id": pid2, "set_by": "mom"})
    sent.clear()
    presence.run_thinking_of_you_prompts(send, now=now)
    check(all("Space Day" not in s[1] for s in sent),
          "give_space day generates no thinking-of-you prompts")


def scenario_video_media_store_and_attachment():
    import main
    from fastapi import BackgroundTasks, HTTPException
    _member("mom", "Mom", role="parent")
    ch = storage.get_or_create_event_channel("evV", "Big Game")
    bt = BackgroundTasks()

    saved = storage.save_media_file(b"\x00\x00fake-mp4-bytes", "video/mp4")
    check(saved and saved["url"].startswith("/api/media/") and saved["mime"] == "video/mp4",
          f"media file saved with mime-derived id, got {saved}")
    check(storage.media_file_path(saved["id"]), "saved file resolves")
    check(storage.save_media_file(b"x", "application/pdf") is None,
          "unsupported mime refused")
    for junk in ("../../etc/passwd", "abc.mp4", "a" * 32 + ".exe", ""):
        check(storage.media_file_path(junk) is None, f"junk id refused: {junk!r}")

    m = main.send_message(ch["id"], main.SendMessageRequest(
        sender_member_id="mom", body="what a play!",
        attachment={"kind": "video", "url": saved["url"]}), bt)
    check(m["attachment"] == {"kind": "video", "url": saved["url"], "mime": "video/mp4"},
          "video attachment validated + normalized")
    try:
        main.send_message(ch["id"], main.SendMessageRequest(
            sender_member_id="mom", body="",
            attachment={"kind": "video", "url": "/api/media/deadbeef.mp4"}), bt)
        check(False, "expected 400")
    except HTTPException as e:
        check(e.status_code == 400, "nonexistent media url refused")

    # Retention: a moment rolling off the 500-cap deletes its clip from disk.
    path = storage.media_file_path(saved["id"])
    for i in range(storage._MESSAGES_PER_CHANNEL_CAP):
        storage.add_chat_message({"id": f"fill{i}", "channel_id": ch["id"],
                                  "sender_member_id": "mom", "ts": time.time() + i + 1,
                                  "type": "text", "body": f"m{i}", "attachment": None,
                                  "reactions": {}})
    check(storage.media_file_path(saved["id"]) is None and not os.path.exists(path),
          "pruned moment's clip removed from disk")


def scenario_moment_fanout_differentiated():
    import main
    from services import ha_api
    _family()
    now = datetime.datetime(2126, 3, 14, 17, 30)
    _schedule(now)
    ch = storage.get_or_create_event_channel("vb1", "Emma's Volleyball")

    moment = {"sender_member_id": "mom", "body": "match point!",
              "attachment": {"kind": "photo", "data_url": _TINY_JPEG}}
    with mock.patch.object(main, "send_push_to_member") as push, \
         mock.patch.object(ha_api, "call_service"):
        main._fanout_message_notifications(ch, moment)
        pushed = sorted(c.args[0] for c in push.call_args_list)
        check(pushed == ["dad", "gramps"],
              f"moment push: kept-away adults only (no kids, no present, no helper), got {pushed}")
        title = push.call_args_list[0].args[1]
        check(title.startswith("📸"), f"moment framing on the push title, got {title!r}")

    # A plain text message in the same event channel keeps the old
    # household-wide fan-out (kids included) — differentiation is moment-only.
    with mock.patch.object(main, "send_push_to_member") as push, \
         mock.patch.object(ha_api, "call_service"):
        main._fanout_message_notifications(ch, {"sender_member_id": "mom", "body": "bring snacks"})
        pushed = sorted(c.args[0] for c in push.call_args_list)
        check(pushed == ["dad", "emma", "gramps", "kid2"],
              f"text fan-out unchanged, got {pushed}")


def scenario_recent_moments_feed():
    _family()
    ch = storage.get_or_create_event_channel("vb1", "Emma's Volleyball")
    t0 = time.time()
    storage.add_chat_message({"id": "t1", "channel_id": ch["id"], "sender_member_id": "mom",
                              "ts": t0 - 30, "type": "text", "body": "warming up",
                              "attachment": None, "reactions": {}})
    storage.add_chat_message({"id": "ph1", "channel_id": ch["id"], "sender_member_id": "mom",
                              "ts": t0 - 20, "type": "text", "body": "she got a kill!",
                              "attachment": {"kind": "photo", "data_url": _TINY_JPEG},
                              "reactions": {"❤️": ["dad"]}})
    storage.add_chat_message({"id": "ph2", "channel_id": ch["id"], "sender_member_id": "mom",
                              "ts": t0 - 10, "type": "text", "body": "",
                              "attachment": {"kind": "photo", "data_url": _TINY_JPEG},
                              "reactions": {}})
    # A DM photo must never reach the hearth feed.
    dm = storage.get_or_create_dm("mom", "dad")
    storage.add_chat_message({"id": "dmp", "channel_id": dm["id"], "sender_member_id": "mom",
                              "ts": t0 - 5, "type": "text", "body": "private",
                              "attachment": {"kind": "photo", "data_url": _TINY_JPEG},
                              "reactions": {}})

    feed = presence.recent_moments(hours=1)
    check([m["id"] for m in feed] == ["ph2", "ph1"],
          f"photo moments only, newest first, event channels only, got {[m['id'] for m in feed]}")
    check(feed[1]["sender_name"] == "Mom" and feed[1]["event_title"] == "Emma's Volleyball",
          "sender + event context enriched")
    check(feed[1]["reactions"] == {"❤️": ["dad"]}, "reactions ride the feed")
    check(presence.recent_moments(hours=0.001) == [], "hours window respected")


SCENARIOS = [
    scenario_attachment_send_and_validation,
    scenario_reaction_toggle_and_endpoint,
    scenario_present_and_kept_away,
    scenario_capture_prompt_sweep,
    scenario_capture_prompt_gates,
    scenario_prompt_worthiness_gates,
    scenario_thinking_of_you_inversion,
    scenario_video_media_store_and_attachment,
    scenario_moment_fanout_differentiated,
    scenario_recent_moments_feed,
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

    failures = 0
    for fn in SCENARIOS:
        reset_db()
        try:
            fn()
            print(f"  PASS {fn.__name__}")
        except Exception:
            failures += 1
            print(f"  FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"{len(SCENARIOS) - failures}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failures else 0)

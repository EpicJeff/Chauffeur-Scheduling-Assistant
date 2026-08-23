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
    # Quiet hours EXPLICITLY DISABLED (`start == end`). Absent means the
    # household default of 21:00-08:00 (load arc A6), which silently emptied
    # the moment fan-out assertions every evening — the scenario is about who
    # a moment reaches, not about when adults are asleep.
    doc = {"id": mid, "name": name, "color_code": "#3b82f6", "avatar": None,
           "bio": "", "can_drive": False, "is_child": False, "driver_id": None,
           "passenger_id": None, "ha_person_entity": None, "notify_service": None,
           "media_player_entity": None, "pin": None, "created_at": time.time(),
           "quiet_start": "00:00", "quiet_end": "00:00"}
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
    # Photos are FILES now, not base64 inline on the message.
    check(m["attachment"]["url"].startswith("/api/media/")
          and "data_url" not in m["attachment"],
          f"photo stored in the media store, not inline, got {m['attachment']}")
    check(storage.media_file_path(m["attachment"]["url"].rsplit("/", 1)[-1]),
          "the photo file exists on disk")

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

    # Pin the no-ffmpeg path (a dev box may or may not have it on PATH).
    with mock.patch.object(storage, "_ffmpeg_path", return_value=None):
        saved = storage.save_media_file(b"\x00\x00fake-mp4-bytes", "video/mp4")
    check(saved and saved["url"].startswith("/api/media/") and saved["mime"] == "video/mp4",
          f"media file saved with mime-derived id, got {saved}")
    check(storage.media_file_path(saved["id"]), "saved file resolves")
    with mock.patch.object(storage, "_ffmpeg_path", return_value=None):
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

    # Retention: moments are FOREVER. Ordinary chatter still rolls off the
    # per-channel cap, but the moment and its clip must survive the flood.
    path = storage.media_file_path(saved["id"])
    for i in range(storage._MESSAGES_PER_CHANNEL_CAP + 50):
        storage.add_chat_message({"id": f"fill{i}", "channel_id": ch["id"],
                                  "sender_member_id": "mom", "ts": time.time() + i + 1,
                                  "type": "text", "body": f"m{i}", "attachment": None,
                                  "reactions": {}})
    kept = [x["id"] for x in storage.get_channel_messages(ch["id"], limit=0)]
    check(m["id"] in kept, "the moment survives the retention cap (forever)")
    check(storage.media_file_path(saved["id"]) and os.path.exists(path),
          "the moment's clip is never deleted from disk")
    check(len([x for x in kept if x.startswith("fill")]) < storage._MESSAGES_PER_CHANNEL_CAP + 50,
          "ordinary chatter still prunes")


def scenario_video_transcode_pipeline():
    """iPhone HEVC .mov can't play on a Chrome wall panel: with ffmpeg the
    clip normalizes to H.264 mp4 on the SAME id; the original serves while
    the transcode is pending, and failure falls back to store-as-is."""
    calls = []
    with mock.patch.object(storage, "_ffmpeg_path", return_value="/usr/bin/ffmpeg"), \
         mock.patch("threading.Thread") as thread:
        thread.side_effect = lambda target=None, args=(), daemon=None: \
            calls.append((target, args)) or mock.MagicMock()
        saved = storage.save_media_file(b"fake-hevc-mov", "video/quicktime")
    check(saved and saved["id"].endswith(".mp4") and saved["mime"] == "video/mp4",
          f"ffmpeg path promises the FINAL mp4 id up front, got {saved}")
    check(calls and calls[0][0] is storage._transcode_media,
          "transcode kicked off in the background")
    stem = saved["id"].split(".")[0]

    # Pending window: the .orig fallback serves — a just-sent moment is never 404.
    path = storage.media_file_path(saved["id"])
    check(path and path.endswith(".orig"), f"original serves while pending, got {path}")

    # Simulate ffmpeg success: swap in the mp4, original removed.
    final = storage.media_write_path(saved["id"])
    with open(final, "wb") as f:
        f.write(b"transcoded-h264")
    os.remove(storage.media_read_path(stem + ".orig"))
    path = storage.media_file_path(saved["id"])
    check(path == final, "after the swap the mp4 serves on the same id/url")

    # Failure path: _transcode_media with a broken ffmpeg renames orig into place.
    with mock.patch.object(storage, "_ffmpeg_path", return_value="/nonexistent/ffmpeg"):
        orig2 = storage.media_write_path("a" * 32 + ".orig")
        with open(orig2, "wb") as f:
            f.write(b"clip-bytes")
        storage._transcode_media("a" * 32)
    kept = storage.media_write_path("a" * 32 + ".mp4")
    check(os.path.exists(kept) and not os.path.exists(orig2),
          "failed transcode stores the original as-is — the moment is never lost")


def scenario_moment_fanout_differentiated():
    import main
    from services import ha_api
    _family()
    now = datetime.datetime(2126, 3, 14, 17, 30)
    _schedule(now)
    ch = storage.get_or_create_event_channel("vb1", "Emma's Volleyball")

    moment = {"id": "mm1", "sender_member_id": "mom", "body": "match point!",
              "attachment": {"kind": "photo", "data_url": _TINY_JPEG}}
    with mock.patch.object(main, "send_push_to_member") as push, \
         mock.patch.object(ha_api, "call_service"), \
         mock.patch.object(ha_api, "fire_event") as fire:
        main._fanout_message_notifications(ch, moment)
        pushed = sorted(c.args[0] for c in push.call_args_list)
        check(pushed == ["dad", "gramps"],
              f"moment push: kept-away adults only (no kids, no present, no helper), got {pushed}")
        title = push.call_args_list[0].args[1]
        check(title.startswith("📸"), f"moment framing on the push title, got {title!r}")
        # HA bus ping: bare "a moment happened" — no payload rides the bus.
        check(fire.call_count == 1 and fire.call_args.args == ("chauffeur_moment", {}),
              f"moment fires a payload-free HA event, got {fire.call_args}")

    # A plain text message in the same event channel keeps the old
    # household-wide fan-out (kids included) — differentiation is moment-only,
    # and text never pings the HA bus.
    with mock.patch.object(main, "send_push_to_member") as push, \
         mock.patch.object(ha_api, "call_service"), \
         mock.patch.object(ha_api, "fire_event") as fire:
        main._fanout_message_notifications(ch, {"sender_member_id": "mom", "body": "bring snacks"})
        pushed = sorted(c.args[0] for c in push.call_args_list)
        check(pushed == ["dad", "emma", "gramps", "kid2"],
              f"text fan-out unchanged, got {pushed}")
        check(fire.call_count == 0, "text messages never fire the HA moment event")

    # A moment in a private DM (thinking-of-you) must NOT hit the shared bus.
    dm = storage.get_or_create_dm("dad", "mom")
    with mock.patch.object(main, "send_push_to_member"), \
         mock.patch.object(ha_api, "call_service"), \
         mock.patch.object(ha_api, "fire_event") as fire:
        main._fanout_message_notifications(dm, {"id": "mm2", "sender_member_id": "dad",
                                                "body": "thinking of you",
                                                "attachment": {"kind": "photo", "data_url": _TINY_JPEG}})
        check(fire.call_count == 0,
              "a DM moment never fires the HA event (nothing private on a wall panel)")


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


def scenario_gallery_window_and_route():
    """The hearth pop and the gallery need DIFFERENT windows: a 5-day-old
    moment belongs in /moments but must never pop on a panel."""
    import main
    _family()
    ch = storage.get_or_create_event_channel("vb1", "Emma's Volleyball")
    t0 = time.time()
    for mid, ts in (("fresh", t0 - 60), ("old", t0 - 5 * 86400)):
        storage.add_chat_message({"id": mid, "channel_id": ch["id"], "sender_member_id": "mom",
                                  "ts": ts, "type": "text", "body": mid,
                                  "attachment": {"kind": "photo", "data_url": _TINY_JPEG},
                                  "reactions": {}})

    pop = [m["id"] for m in main.get_presence_moments(hours=12)]
    check(pop == ["fresh"], f"the pop window sees only fresh moments, got {pop}")
    gallery = [m["id"] for m in main.get_presence_moments(hours=24 * 30, limit=200)]
    check(gallery == ["fresh", "old"], f"the gallery window looks back, got {gallery}")

    # Absurd params clamp instead of erroring (caps raised for the gallery).
    capped = main.get_presence_moments(hours=99999, limit=9999)
    check(len(capped) == 2, f"out-of-range params clamp, got {len(capped)}")

    paths = {getattr(r, 'path', '') for r in main.app.routes}
    check('/moments' in paths and '/moment' in paths,
          "gallery page and single-moment popup routes both registered")


def scenario_video_posters_and_photo_files():
    """Clips get an ffmpeg poster frame so tiles are never a black box, and
    photos live in the media store like clips do."""
    import main
    from services import presence
    _member("mom", "Mom", role="parent")

    # Poster URL is DERIVED from the clip id, so clips predating posters get
    # one too; a miss self-heals by generating the frame on request.
    att = {"kind": "video", "url": "/api/media/" + "b" * 32 + ".mp4"}
    with mock.patch.object(storage, "_ffmpeg_path", return_value="/usr/bin/ffmpeg"):
        check(presence.poster_url_for(att) == "/api/media/" + "b" * 32 + ".jpg",
              f"poster derived beside the clip, got {presence.poster_url_for(att)}")
    # No ffmpeg and no poster on disk: do NOT advertise a poster URL that
    # would 404 and render as an empty tile — fall back to the clip.
    with mock.patch.object(storage, "_ffmpeg_path", return_value=None):
        check(presence.poster_url_for(att) == "",
              "no deliverable poster -> no poster URL")
        row = presence._moment_row({"id": "x", "attachment": att, "ts": 1}, {})
        check(row["poster_url"] == att["url"],
              f"row falls back to the clip itself, got {row['poster_url']}")
    check(presence.poster_url_for({"kind": "photo", "url": "/api/media/x.jpg"}) == "",
          "photos have no separate poster — they are their own thumbnail")

    # A poster request for a clip with no .jpg must NEVER fall through to the
    # raw video bytes (that used to be the .orig fallback's blast radius).
    stem = "c" * 32
    with open(storage.media_write_path(stem + ".orig"), "wb") as f:
        f.write(b"raw-video-bytes")
    with mock.patch.object(storage, "_ffmpeg_path", return_value=None):
        check(storage.media_file_path(stem + ".jpg") is None,
              "no poster + no ffmpeg -> 404, never the video bytes")
        check(storage.media_file_path(stem + ".mp4").endswith(".orig"),
              "the clip itself still falls back to the original")
    # With a poster present it serves as an image.
    with open(storage.media_write_path(stem + ".jpg"), "wb") as f:
        f.write(b"\xff\xd8jpeg")
    check(storage.media_mime(stem + ".jpg") == "image/jpeg", "poster serves as an image")

    # Photos: data URL in, file out.
    saved = storage.save_photo_data_url(_TINY_JPEG)
    check(saved and saved["url"].startswith("/api/media/") and saved["mime"] == "image/jpeg",
          f"photo filed into the media store, got {saved}")
    check(storage.media_file_path(saved["id"]), "photo file resolves")
    check(storage.save_photo_data_url("data:application/pdf;base64,AAA") is None,
          "non-image data URL refused")
    check(storage.save_photo_data_url("") is None, "empty data URL refused")

    # Legacy inline photos still render (by-message URL decodes them).
    ch = storage.get_or_create_event_channel("evL", "Old Game")
    storage.add_chat_message({"id": "legacy1", "channel_id": ch["id"], "sender_member_id": "mom",
                              "ts": time.time(), "type": "text", "body": "old",
                              "attachment": {"kind": "photo", "data_url": _TINY_JPEG},
                              "reactions": {}})
    resp = main.serve_moment_media_by_message("legacy1")
    check(getattr(resp, "media_type", "").startswith("image/"),
          "legacy inline photo still serves")
    row = presence.recent_moments(hours=1)[0]
    check(row["media_url"] == "/api/moments/legacy1/media",
          f"legacy photo falls back to the by-message URL, got {row['media_url']}")

    # The migration files legacy photos away and repoints the message.
    import asyncio as _asyncio
    from services import migrations
    _asyncio.run(migrations.migrate_inline_photos_v2620())
    moved = storage.get_chat_message("legacy1")["attachment"]
    check(moved.get("url", "").startswith("/api/media/") and "data_url" not in moved,
          f"migration filed the inline photo, got {moved}")
    check(storage.media_file_path(moved["url"].rsplit("/", 1)[-1]),
          "migrated photo's file exists")


def scenario_moment_rides_the_message_stream():
    """An open app should pop a new moment, so the SSE event carries a small
    preview — URLs only, and only for real moments."""
    import main
    from fastapi import BackgroundTasks
    _family()
    ch = storage.get_or_create_event_channel("vb1", "Emma's Volleyball")
    bt = BackgroundTasks()
    main.MESSAGE_EVENTS.clear()

    main.send_message(ch["id"], main.SendMessageRequest(
        sender_member_id="mom", body="she got a kill!",
        attachment={"kind": "photo", "data_url": _TINY_JPEG}), bt)
    ev = main.MESSAGE_EVENTS[-1]
    mo = ev.get("moment")
    check(mo, f"moment preview rides the stream event, got {ev}")
    check(mo["event_title"] == "Emma's Volleyball" and mo["sender_name"] == "Mom"
          and mo["body"] == "she got a kill!" and mo["kind"] == "photo",
          f"preview carries what the overlay renders, got {mo}")
    check(mo["media_url"].startswith("/api/") and mo["channel_id"] == ch["id"]
          and mo["sender_member_id"] == "mom",
          "preview carries URLs + identity for the client's own-moment guard")
    check("data_url" not in str(mo), "no media bytes on the stream")

    # Plain chatter must not pop anything.
    main.send_message(ch["id"], main.SendMessageRequest(
        sender_member_id="mom", body="parking is rough"), bt)
    check("moment" not in main.MESSAGE_EVENTS[-1],
          "text messages carry no moment preview")

    # Nor should a moment in a private DM (thinking-of-you stays private).
    dm = storage.get_or_create_dm("mom", "dad")
    main.send_message(dm["id"], main.SendMessageRequest(
        sender_member_id="mom", body="thinking of you",
        attachment={"kind": "photo", "data_url": _TINY_JPEG}), bt)
    check("moment" not in main.MESSAGE_EVENTS[-1],
          "DM moments never pop on the stream")


def scenario_gallery_event_grouping_and_paging():
    """The gallery groups by EVENT and pages both levels — no time limit."""
    import main
    _family()
    t0 = time.time()
    # Two events; the volleyball thread has several moments, plus one very old
    # moment that must still be reachable (forever, not 30 days).
    vb = storage.get_or_create_event_channel("vb1", "Emma's Volleyball")
    pi = storage.get_or_create_event_channel("pi1", "Piano Recital")
    for i in range(5):
        storage.add_chat_message({"id": f"vb{i}", "channel_id": vb["id"], "sender_member_id": "mom",
                                  "ts": t0 - i * 60, "type": "text", "body": f"point {i}",
                                  "attachment": {"kind": "photo", "data_url": _TINY_JPEG},
                                  "reactions": {}})
    storage.add_chat_message({"id": "vb_ancient", "channel_id": vb["id"], "sender_member_id": "dad",
                              "ts": t0 - 400 * 86400, "type": "text", "body": "last season",
                              "attachment": {"kind": "photo", "data_url": _TINY_JPEG},
                              "reactions": {}})
    storage.add_chat_message({"id": "pi0", "channel_id": pi["id"], "sender_member_id": "dad",
                              "ts": t0 - 3600, "type": "text", "body": "she nailed it",
                              "attachment": {"kind": "photo", "data_url": _TINY_JPEG},
                              "reactions": {}})
    # A text-only message must not create an event card.
    storage.add_chat_message({"id": "chat1", "channel_id": pi["id"], "sender_member_id": "mom",
                              "ts": t0, "type": "text", "body": "parking is rough",
                              "attachment": None, "reactions": {}})

    idx = main.get_moment_events()
    titles = [e["event_title"] for e in idx["items"]]
    check(titles == ["Emma's Volleyball", "Piano Recital"],
          f"one card per event, newest event first, got {titles}")
    vb_card = idx["items"][0]
    check(vb_card["count"] == 6, f"card counts ALL the event's moments, got {vb_card['count']}")
    check(vb_card["cover_url"].endswith("/media") and vb_card["cover_url"].startswith("/api/moments/"),
          f"cover is a URL, not an inline data URL, got {vb_card['cover_url'][:40]}")
    check(sorted(vb_card["sender_names"]) == ["Dad", "Mom"], "card credits everyone who posted")
    check(idx["total"] == 2 and not idx["has_more"], "index reports total + has_more")

    # Event-level paging, and the 400-day-old moment is still there.
    p1 = main.get_event_moments(channel_id=vb["id"], offset=0, limit=4)
    check(len(p1["items"]) == 4 and p1["has_more"] and p1["total"] == 6,
          f"first page of an event's moments, got {len(p1['items'])}/{p1['total']}")
    p2 = main.get_event_moments(channel_id=vb["id"], offset=4, limit=4)
    ids = [m["id"] for m in p2["items"]]
    check(not p2["has_more"] and "vb_ancient" in ids,
          f"last page completes the set incl. the ancient moment, got {ids}")
    check(all(m["media_url"] == f"/api/moments/{m['id']}/media" for m in p2["items"]),
          "every moment carries its stable media URL")

    # Index paging.
    page = main.get_moment_events(offset=0, limit=1)
    check(len(page["items"]) == 1 and page["has_more"], "index pages")

    # Media endpoint: photo decodes to real bytes, junk 404s.
    from fastapi import HTTPException
    resp = main.serve_moment_media_by_message("pi0")
    check(getattr(resp, "media_type", "").startswith("image/") and len(resp.body) > 0,
          "photo moment serves decoded image bytes")
    try:
        main.serve_moment_media_by_message("chat1")
        check(False, "expected 404")
    except HTTPException as e:
        check(e.status_code == 404, "a text message has no media")


def scenario_message_delete_and_edit():
    """Undoing a misfire. Delete is removal (a PARENT may clear a shared
    channel); edit is authorship (only ever the sender). role='adult' is
    NOT role='parent' — a grandparent or sitter has no moderation power."""
    import main
    from fastapi import BackgroundTasks, HTTPException
    _member("mom", "Mom", role="parent")
    _member("gramps", "Grandpa", role="adult")
    _member("emma", "Emma", role="child", is_child=True)
    ch = storage.get_or_create_event_channel("evD", "Tournament")
    bt = BackgroundTasks()

    def _post(mid, sender, body="hi", attachment=None):
        storage.add_chat_message({"id": mid, "channel_id": ch["id"], "sender_member_id": sender,
                                  "ts": time.time(), "type": "text", "body": body,
                                  "attachment": attachment, "reactions": {}})

    # --- delete permissions -------------------------------------------------
    _post("d_own", "emma")
    main.delete_message("d_own", main.MessageDeleteRequest(member_id="emma"))
    check(storage.get_chat_message("d_own") is None, "sender deletes their own message")

    _post("d_kid", "emma")
    main.delete_message("d_kid", main.MessageDeleteRequest(member_id="mom"))
    check(storage.get_chat_message("d_kid") is None,
          "parent clears a kid's message from a shared channel")

    _post("d_adult", "emma")
    for actor, code in [("gramps", 403), ("ghost", 404)]:
        try:
            main.delete_message("d_adult", main.MessageDeleteRequest(member_id=actor))
            check(False, f"expected {code}")
        except HTTPException as e:
            check(e.status_code == code, f"delete by {actor} -> {code}")
    check(storage.get_chat_message("d_adult") is not None,
          "a non-parent adult CANNOT delete someone else's message")
    try:
        main.delete_message("nope", main.MessageDeleteRequest(member_id="mom"))
        check(False, "expected 404")
    except HTTPException as e:
        check(e.status_code == 404, "unknown message -> 404")

    # A DM is nobody's to moderate, parent or not.
    dm = storage.get_or_create_dm("emma", "gramps")
    storage.add_chat_message({"id": "d_dm", "channel_id": dm["id"], "sender_member_id": "emma",
                              "ts": time.time(), "type": "text", "body": "secret",
                              "attachment": None, "reactions": {}})
    try:
        main.delete_message("d_dm", main.MessageDeleteRequest(member_id="mom"))
        check(False, "expected 403")
    except HTTPException as e:
        check(e.status_code == 403, "parent cannot reach into a DM")
    check(storage.get_chat_message("d_dm") is not None, "the DM message survives")

    # --- deleting a moment takes its files with it --------------------------
    with mock.patch.object(storage, "_ffmpeg_path", return_value=None):
        saved = storage.save_media_file(b"\x00\x00fake-mp4-bytes", "video/mp4")
    m = main.send_message(ch["id"], main.SendMessageRequest(
        sender_member_id="emma", body="buzzer beater",
        attachment={"kind": "video", "url": saved["url"]}), bt)
    path = storage.media_file_path(saved["id"])
    check(path and os.path.exists(path), "clip on disk before delete")
    main.delete_message(m["id"], main.MessageDeleteRequest(member_id="mom"))
    check(storage.get_chat_message(m["id"]) is None, "moment row gone")
    # Moments are EXEMPT from the retention cap, so nothing else would ever
    # collect this file — deleting the row alone would leak it forever.
    check(not os.path.exists(path), "the clip is removed from disk with it")

    # --- edit is sender-only, and marks itself ------------------------------
    _post("e_own", "emma", body="we one")
    upd = main.edit_message("e_own", main.MessageEditRequest(member_id="emma", body="we won"))
    check(upd["body"] == "we won", "sender edits their own text")
    check(upd.get("edited_ts"), "edit stamps edited_ts for the 'edited' marker")
    check(storage.get_chat_message("e_own")["body"] == "we won", "edit persisted")

    for actor, code in [("mom", 403), ("gramps", 403), ("ghost", 404)]:
        try:
            main.edit_message("e_own", main.MessageEditRequest(member_id=actor, body="nope"))
            check(False, f"expected {code}")
        except HTTPException as e:
            check(e.status_code == code, f"edit by {actor} -> {code}")
    check(storage.get_chat_message("e_own")["body"] == "we won",
          "not even a parent rewrites a kid's words")

    # Editing to blank is a delete wearing a disguise — unless an attachment
    # still carries the message, in which case it is just clearing a caption.
    try:
        main.edit_message("e_own", main.MessageEditRequest(member_id="emma", body="   "))
        check(False, "expected 400")
    except HTTPException as e:
        check(e.status_code == 400, "blanking a text-only message -> 400")
    # A fresh upload: the one above went to disk with its message.
    with mock.patch.object(storage, "_ffmpeg_path", return_value=None):
        saved2 = storage.save_media_file(b"\x00\x00another-fake-mp4", "video/mp4")
    m2 = main.send_message(ch["id"], main.SendMessageRequest(
        sender_member_id="emma", body="oops caption",
        attachment={"kind": "video", "url": saved2["url"]}), bt)
    upd = main.edit_message(m2["id"], main.MessageEditRequest(member_id="emma", body=""))
    check(upd["body"] == "" and upd["attachment"], "a caption may be cleared off a moment")


def scenario_media_root_and_sharding():
    """The archive can live off /data, and finds its files either way. The
    legacy flat location stays in the lookup forever — that is what makes
    relocating onto a network mount safe to interrupt."""
    # Sharding is derived from the id itself, which is why no stored
    # attachment URL and nothing in the database has to change.
    check(storage._shard("abcd" + "0" * 28 + ".mp4") == os.path.join("ab", "cd"),
          "shard comes from the id's own leading hex")
    check(storage._shard("abcd" + "0" * 28 + ".jpg") == os.path.join("ab", "cd"),
          "siblings share the stem, so they share the bucket")
    check(storage._shard("notahexname.mp4") == "", "non-hex names stay flat")

    _member("mom", "Mom", role="parent")
    with mock.patch.object(storage, "_ffmpeg_path", return_value=None):
        saved = storage.save_media_file(b"\x00\x00clip", "video/mp4")
    path = storage.media_file_path(saved["id"])
    check(path and os.path.exists(path), "new upload resolves")
    check(os.path.dirname(path).endswith(storage._shard(saved["id"])),
          f"new upload landed in its shard, got {path}")

    # A file sitting FLAT in the legacy root (pre-migration, or a half-moved
    # archive) must still resolve — nothing 404s while a migration runs.
    legacy_id = "b" * 32 + ".mp4"
    os.makedirs(storage._LEGACY_MEDIA_DIR, exist_ok=True)
    with open(os.path.join(storage._LEGACY_MEDIA_DIR, legacy_id), "wb") as f:
        f.write(b"legacy")
    check(storage.media_file_path(legacy_id), "flat legacy file still resolves")

    res = storage.migrate_media_layout()
    check(res["complete"], "migration reports completion")
    moved = storage.media_file_path(legacy_id)
    check(moved and os.path.dirname(moved).endswith(storage._shard(legacy_id)),
          f"migration relocated the flat file into its shard, got {moved}")
    again = storage.migrate_media_layout()
    check(again["moved"] == 0, "migration is idempotent — a second run moves nothing")

    # Deleting must find files wherever they are, sharded or not.
    storage._delete_media_for_messages(
        [{"attachment": {"url": f"/api/media/{legacy_id}"}}])
    check(storage.media_file_path(legacy_id) is None, "delete follows the shard")

    # A media_root that does not exist must be REFUSED, never created. This is
    # the typo case: a mount named LOCAL_STOARGE with media_root pointing at
    # LOCAL_STORAGE used to have the app mkdir a plain folder beside the real
    # mount, adopt it, pass every other check, and quietly write the archive
    # onto the very volume the option exists to escape.
    missing = os.path.join(tempfile.gettempdir(), "chauffeur_typo_mount_xyz")
    shutil.rmtree(missing, ignore_errors=True)
    with mock.patch.dict(os.environ, {"CHAUFFEUR_MEDIA_ROOT": missing}):
        check(storage._configured_media_root() is None,
              "a media_root that does not exist is refused")
    check(not os.path.exists(missing), "and is NOT created behind your back")

    # An existing, writable one is adopted (with a same-filesystem warning,
    # which is advisory only — it still works).
    good = tempfile.mkdtemp(prefix="chauffeur_media_root_")
    with mock.patch.dict(os.environ, {"CHAUFFEUR_MEDIA_ROOT": good}):
        check(storage._configured_media_root() == good, "an existing media_root is adopted")
    # Unwritable is refused too.
    with mock.patch.dict(os.environ, {"CHAUFFEUR_MEDIA_ROOT": good}):
        with mock.patch("builtins.open", side_effect=OSError("read-only")):
            check(storage._configured_media_root() is None,
                  "an unwritable media_root is refused, not adopted")
    shutil.rmtree(good, ignore_errors=True)

    # Changing media_root must NOT orphan what is already stored. This is the
    # renamed-share case: the old root leaves the config, and without history
    # its files stop resolving AND stop being seen by the migration — the
    # whole back catalogue vanishes while new uploads keep working.
    stranded = tempfile.mkdtemp(prefix="chauffeur_old_root_")
    orphan_id = "d" * 32 + ".mp4"
    with open(os.path.join(stranded, orphan_id), "wb") as f:
        f.write(b"stranded-clip")
    check(storage.media_file_path(orphan_id) is None,
          "a root the app has never heard of is invisible (the bug)")
    check(storage.adopt_media_root(stranded), "adopting a lost root registers it")
    check(storage.media_file_path(orphan_id), "its files resolve immediately once adopted")
    storage.migrate_media_layout()
    landed = storage.media_file_path(orphan_id)
    check(landed and os.path.normpath(landed).startswith(os.path.normpath(storage.MEDIA_DIR)),
          f"and are relocated into the active root, got {landed}")
    check(not storage.adopt_media_root(stranded), "adopting twice is a no-op")

    # A media root may be a share with other things in it. Relocating every
    # file found would rearrange someone's documents into ab/cd buckets.
    check(storage._is_media_filename("a" * 32 + ".mp4"), "our files match")
    check(storage._is_media_filename("a" * 32 + ".tmp.mp4"), "transcode working files match")
    check(storage._is_media_filename("a" * 32 + ".orig"), "pending originals match")
    for junk in ("taxes2025.pdf", "notes.txt", "IMG_4021.jpg", "a" * 31 + ".mp4"):
        check(not storage._is_media_filename(junk), f"foreign file left alone: {junk}")
    bystander = os.path.join(stranded, "taxes2025.pdf")
    with open(bystander, "wb") as f:
        f.write(b"not ours")
    storage.migrate_media_layout()
    check(os.path.exists(bystander), "a foreign file in a media root is never moved")
    shutil.rmtree(stranded, ignore_errors=True)

    # Scratch is always beside the DATABASE, never derived from the media
    # root — ffmpeg and uploads must not write onto a mount, whatever the
    # root is set to.
    check(os.path.dirname(storage.media_scratch_dir()) == os.path.dirname(storage.DB_PATH),
          f"scratch lives beside the database, got {storage.media_scratch_dir()}")


def scenario_resumable_upload():
    """Chunked upload with offset resync. A clip goes up over cellular at a
    game; the old single POST restarted from zero on any drop."""
    import main
    import asyncio
    import json
    from fastapi import HTTPException

    class _FakeRequest:
        """Minimal stand-in for Starlette's Request.stream()."""
        def __init__(self, body, pieces=2):
            n = max(1, len(body) // pieces or 1)
            self._chunks = [body[i:i + n] for i in range(0, len(body), n)] or [b'']
        async def stream(self):
            for c in self._chunks:
                yield c

    def put(uid, offset, body):
        return asyncio.run(main.put_upload_chunk(uid, offset, _FakeRequest(body)))

    # Too big is refused BEFORE any bytes move — that is the whole point of
    # declaring the size up front.
    try:
        main.init_resumable_upload(main.UploadInitRequest(
            size=main._VIDEO_MAX_BYTES + 1, mime="video/mp4"))
        check(False, "expected 413")
    except HTTPException as e:
        check(e.status_code == 413 and "limit" in e.detail,
              f"oversize refused at init with a helpful message, got {e.detail}")
    try:
        main.init_resumable_upload(main.UploadInitRequest(size=0, mime="video/mp4"))
        check(False, "expected 400")
    except HTTPException as e:
        check(e.status_code == 400, "empty upload refused at init")

    # The add-on's own volume is the real limit, not the cap: uploads and
    # transcodes work in /data, which Home Assistant shares, and running it
    # out takes HA down rather than merely failing the upload.
    with mock.patch.object(storage, "scratch_free_bytes", return_value=1024):
        try:
            main.init_resumable_upload(main.UploadInitRequest(
                size=500 * 1024 * 1024, mime="video/mp4"))
            check(False, "expected 507")
        except HTTPException as e:
            check(e.status_code == 507 and "free" in e.detail,
                  f"refused when /data lacks working space, got {e.detail}")

    payload = b"fake-mp4-bytes-" * 400
    init = main.init_resumable_upload(main.UploadInitRequest(
        size=len(payload), mime="video/mp4"))
    uid = init["upload_id"]
    check(init["received"] == 0 and init["max_bytes"] == main._VIDEO_MAX_BYTES,
          "init reports a starting offset and the cap")

    half = len(payload) // 2
    r = put(uid, 0, payload[:half])
    check(r["received"] == half, "first chunk acknowledged by byte count")

    # The drop: client thinks it is elsewhere. A 409 must carry the truth so
    # it resyncs in one round trip instead of starting over.
    try:
        put(uid, 0, payload[:half])
        check(False, "expected 409")
    except HTTPException as e:
        check(e.status_code == 409 and json.loads(e.detail)["received"] == half,
              f"offset mismatch returns the server's true offset, got {e.detail}")
    check(main.resumable_upload_status(uid)["received"] == half,
          "status endpoint reports resume point")

    # Completing early must fail rather than store a truncated clip.
    try:
        main.complete_resumable_upload(uid)
        check(False, "expected 400")
    except HTTPException as e:
        check(e.status_code == 400 and "Incomplete" in e.detail,
              "an incomplete upload cannot be completed")

    r = put(uid, half, payload[half:])
    check(r["received"] == len(payload), "resumed from the server's offset")
    with mock.patch.object(storage, "_ffmpeg_path", return_value=None):
        done = main.complete_resumable_upload(uid)
    check(done["kind"] == "video" and done["url"].startswith("/api/media/"),
          f"completed upload lands in the media store, got {done}")
    check(storage.media_file_path(done["url"].rsplit("/", 1)[-1]), "and resolves")

    # Overrunning the declared size is refused and the part discarded.
    init2 = main.init_resumable_upload(main.UploadInitRequest(size=10, mime="video/mp4"))
    try:
        put(init2["upload_id"], 0, b"x" * 50)
        check(False, "expected 413")
    except HTTPException as e:
        check(e.status_code == 413, "overrunning the declared size is refused")
    try:
        main.resumable_upload_status(init2["upload_id"])
        check(False, "expected 404")
    except HTTPException as e:
        check(e.status_code == 404, "and the abandoned part is cleaned up")

    for junk in ("../../etc/passwd", "nothex", "a" * 31):
        try:
            main.resumable_upload_status(junk)
            check(False, "expected rejection")
        except HTTPException as e:
            check(e.status_code in (400, 404), f"junk upload id refused: {junk!r}")


def scenario_unseen_moment_count():
    """The wall panel's catch-up badge. The rail is gone, so the count is
    what tells a family that moments landed while nobody was looking — and it
    counts MOMENTS (messages), never media, so one share of five photos will
    still read as one once albums land."""
    import main
    _family()
    t0 = time.time()
    vb = storage.get_or_create_event_channel("vb1", "Emma's Volleyball")
    pi = storage.get_or_create_event_channel("pi1", "Piano Recital")
    for mid, ch, ts in (("old", vb, t0 - 7200), ("new1", vb, t0 - 600),
                        ("new2", pi, t0 - 300)):
        storage.add_chat_message({"id": mid, "channel_id": ch["id"], "sender_member_id": "mom",
                                  "ts": ts, "type": "text", "body": mid,
                                  "attachment": {"kind": "photo", "data_url": _TINY_JPEG},
                                  "reactions": {}})
    # Neither a text message nor a DM photo is a moment.
    storage.add_chat_message({"id": "talk", "channel_id": vb["id"], "sender_member_id": "mom",
                              "ts": t0 - 60, "type": "text", "body": "parking",
                              "attachment": None, "reactions": {}})
    dm = storage.get_or_create_dm("mom", "dad")
    storage.add_chat_message({"id": "dmp", "channel_id": dm["id"], "sender_member_id": "mom",
                              "ts": t0 - 60, "type": "text", "body": "private",
                              "attachment": {"kind": "photo", "data_url": _TINY_JPEG},
                              "reactions": {}})

    check(presence.count_moments_since(t0 - 3600) == 2,
          f"two moments since the cutoff, got {presence.count_moments_since(t0 - 3600)}")
    check(presence.count_moments_since(t0 - 86400) == 3, "everything is newer than yesterday")
    check(presence.count_moments_since(t0) == 0, "nothing newer than now")

    body = main.get_moments_count(since=t0 - 3600)
    check(body == {"count": 2}, f"the count route answers a bare number, got {body}")
    # A panel that has never looked gets the whole window, not a seeded lie.
    check(main.get_moments_count(since=0)["count"] == 3, "since=0 counts them all")


def scenario_hearth_is_pop_only():
    """The floating rail/FAB is gone from every kiosk page; the unbidden pop
    and its one external caller (the home board's moments tile) survive."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hearth = open(os.path.join(root, 'templates', 'components', 'moments_hearth.html'),
                  encoding='utf-8').read()
    for gone in ('moments-fab', 'moments-rail', 'toggleMomentsRail', 'openHearthMoment',
                 'renderRail', 'momentsFabPulse'):
        check(gone not in hearth, f"the rail is gone: {gone} still in moments_hearth.html")
    check('showMomentOverlayKiosk' in hearth, "the unbidden pop survives")
    check('chfSetMomentsBadge' in hearth, "the poll feeds the shelf badge instead of a FAB")

    home = open(os.path.join(root, 'templates', 'home.html'), encoding='utf-8').read()
    check('showMomentOverlayKiosk' in home, "the home board tile still opens moments full screen")

    nav = open(os.path.join(root, 'templates', 'nav.html'), encoding='utf-8').read()
    check('chfSetMomentsBadge' in nav, "nav owns the badge")
    check('panel-shelf-more' in nav and 'momentsBadge' in nav,
          "the badge rolls onto More when Moments overflows the shelf")

    gallery = open(os.path.join(root, 'templates', 'components', 'moments_gallery.html'),
                   encoding='utf-8').read()
    check('chauffeur_moments_viewed_ts' in gallery and 'chfSetMomentsBadge' in gallery,
          "visiting the gallery is what clears the badge")
    check('chauffeur_moments_seen_ts' not in gallery,
          "the badge key and the pop-dedupe key must stay apart")
    check('mg-new' in gallery, "events with new moments are marked")


def scenario_attachment_items_helper():
    """One helper is the only thing that knows the album rule."""
    legacy = {"kind": "photo", "data_url": _TINY_JPEG}
    single = {"kind": "photo", "url": "/api/media/" + "a" * 32}
    album = {"kind": "photo", "url": "/api/media/" + "a" * 32,
             "items": [{"kind": "photo", "url": "/api/media/" + "a" * 32},
                       {"kind": "video", "url": "/api/media/" + "b" * 32 + ".mp4"}]}
    check(storage.attachment_items(legacy) == [legacy], "a legacy inline photo is one item")
    check(storage.attachment_items(single) == [single], "a modern single photo is one item")
    check([i["url"] for i in storage.attachment_items(album)]
          == ["/api/media/" + "a" * 32, "/api/media/" + "b" * 32 + ".mp4"],
          "an album yields its items, cover first")
    check(storage.attachment_items(None) == [], "no attachment is no media")
    check(storage.attachment_items({}) == [], "an empty attachment is no media")
    check(storage.attachment_items({"kind": "photo"}) == [],
          "an attachment with no url and no data is no media")


def scenario_album_deletion_frees_every_file():
    """THE landmine: moments never age out, so if deletion misses an album's
    non-cover files nothing else ever collects them."""
    import main
    _family()
    ch = storage.get_or_create_event_channel("vb1", "Emma's Volleyball")
    saved = [storage.save_photo_data_url(_TINY_JPEG) for _ in range(3)]
    check(all(saved), "three photos land in the media store")
    ids = [s["url"].rsplit("/", 1)[-1] for s in saved]
    check(all(storage.media_file_path(i) for i in ids), "all three exist on disk")

    storage.add_chat_message({
        "id": "alb", "channel_id": ch["id"], "sender_member_id": "mom",
        "ts": time.time(), "type": "text", "body": "first half",
        "attachment": {"kind": "photo", "url": saved[0]["url"],
                       "items": [{"kind": "photo", "url": s["url"]} for s in saved]},
        "reactions": {}})

    storage.delete_chat_message("alb")
    left = [i for i in ids if storage.media_file_path(i)]
    check(not left, f"every item's file is freed, not just the cover — left {left}")


def scenario_album_validation():
    """The one choke point every album passes through."""
    import main
    from fastapi import BackgroundTasks, HTTPException
    _member("mom", "Mom", role="parent")
    ch = storage.get_or_create_event_channel("evA", "Soccer")
    bt = BackgroundTasks()

    def photo():
        return {"kind": "photo", "data_url": _TINY_JPEG, "w": 4, "h": 4}

    # Ten is the cap and it is accepted.
    m = main.send_message(ch["id"], main.SendMessageRequest(
        sender_member_id="mom", body="first half",
        attachment={"items": [photo() for _ in range(10)]}), bt)
    att = m["attachment"]
    check(len(att["items"]) == 10, f"ten items kept, got {len(att['items'])}")
    check(att["kind"] == "photo" and att["url"] == att["items"][0]["url"],
          "the cover mirrors items[0]")
    check(all(i["url"].startswith("/api/media/") for i in att["items"]),
          "every item is persisted to the media store, none left inline")
    check(len({i["url"] for i in att["items"]}) == 10,
          "ten distinct files, not one file referenced ten times")

    # Eleven is refused, and the message says what the limit is.
    try:
        main.send_message(ch["id"], main.SendMessageRequest(
            sender_member_id="mom", body="",
            attachment={"items": [photo() for _ in range(11)]}), bt)
        check(False, "expected 400")
    except HTTPException as e:
        check(e.status_code == 400 and "10" in str(e.detail),
              f"eleventh item refused with the limit named, got {e.detail}")

    # An empty list is not an album.
    try:
        main.send_message(ch["id"], main.SendMessageRequest(
            sender_member_id="mom", body="", attachment={"items": []}), bt)
        check(False, "expected 400")
    except HTTPException as e:
        check(e.status_code == 400, "an empty album is refused")

    # A bad item raises ITS error, not a generic one.
    try:
        main.send_message(ch["id"], main.SendMessageRequest(
            sender_member_id="mom", body="",
            attachment={"items": [photo(), {"kind": "photo", "data_url": "http://x/y.jpg"}]}), bt)
        check(False, "expected 400")
    except HTTPException as e:
        check("image data URL" in str(e.detail),
              f"the failing item's own error survives, got {e.detail}")

    # One item is NOT an album — one representation of one photo.
    m = main.send_message(ch["id"], main.SendMessageRequest(
        sender_member_id="mom", body="", attachment={"items": [photo()]}), bt)
    check("items" not in m["attachment"] and m["attachment"]["kind"] == "photo",
          f"a one-item list normalizes to a plain attachment, got {m['attachment']}")

    # Albums do not nest.
    try:
        main.send_message(ch["id"], main.SendMessageRequest(
            sender_member_id="mom", body="",
            attachment={"items": [{"kind": "photo", "data_url": _TINY_JPEG,
                                   "items": [photo()]}]}), bt)
        check(False, "expected 400")
    except HTTPException as e:
        check(e.status_code == 400, "a nested album is refused")

    # A failed album cleans up newly persisted files. If item 1 is good and
    # item 2 fails, item 1's file must be freed (not left as orphan).
    import os
    import services.storage as st
    media_dir = st.MEDIA_DIR
    if media_dir and os.path.isdir(media_dir):
        # Count files before attempting the failed album
        files_before = set()
        for root, dirs, files in os.walk(media_dir):
            for f in files:
                files_before.add(os.path.join(root, f))

        try:
            main.send_message(ch["id"], main.SendMessageRequest(
                sender_member_id="mom", body="",
                attachment={"items": [photo(), {"kind": "photo", "data_url": "not-a-data-url"}]}), bt)
            check(False, "expected 400")
        except HTTPException as e:
            check(e.status_code == 400, "album with bad second item fails")

            # Count files after
            files_after = set()
            for root, dirs, files in os.walk(media_dir):
                for f in files:
                    files_after.add(os.path.join(root, f))

            # The failed album should not have left any new files
            new_files = files_after - files_before
            check(not new_files, f"failed album cleans up created files, got new {new_files}")

    # Pre-existing files are NOT deleted. Create a stored photo, then try
    # to use it in an album where a later item fails.
    good_photo = main.send_message(ch["id"], main.SendMessageRequest(
        sender_member_id="mom", body="", attachment={"items": [photo()]}), bt)
    good_url = good_photo["attachment"]["url"]
    good_id = good_url.rsplit('/', 1)[-1] if good_url.startswith('/api/media/') else None

    if good_id:
        check(storage.media_file_path(good_id), "stored photo file exists")
        try:
            main.send_message(ch["id"], main.SendMessageRequest(
                sender_member_id="mom", body="",
                attachment={"items": [
                    {"kind": "photo", "url": good_url},  # Already stored
                    {"kind": "photo", "data_url": "invalid"}  # This will fail
                ]}), bt)
            check(False, "expected 400")
        except HTTPException as e:
            check(e.status_code == 400, "album with pre-existing URL and bad item fails")
            # Verify the pre-existing file still exists
            check(storage.media_file_path(good_id),
                  "pre-existing file survives album validation failure")


def scenario_album_rides_the_wire():
    """A client must never have to reach into the raw attachment, and must
    never need a second request to learn what is in an album."""
    import main
    _family()
    ch = storage.get_or_create_event_channel("vb1", "Emma's Volleyball")
    t0 = time.time()
    a = storage.save_photo_data_url(_TINY_JPEG)
    b = storage.save_photo_data_url(_TINY_JPEG)
    storage.add_chat_message({
        "id": "alb", "channel_id": ch["id"], "sender_member_id": "mom",
        "ts": t0, "type": "text", "body": "first half",
        "attachment": {"kind": "photo", "url": a["url"],
                       "items": [{"kind": "photo", "url": a["url"]},
                                 {"kind": "photo", "url": b["url"]}]},
        "reactions": {}})
    storage.add_chat_message({
        "id": "solo", "channel_id": ch["id"], "sender_member_id": "dad",
        "ts": t0 - 60, "type": "text", "body": "",
        "attachment": {"kind": "photo", "url": a["url"]}, "reactions": {}})

    rows = {r["id"]: r for r in presence.recent_moments(hours=1)}
    alb = rows["alb"]
    check([i["media_url"] for i in alb["items"]] == [a["url"], b["url"]],
          f"items ride the row, cover first, got {alb['items']}")
    check(alb["media_url"] == a["url"] and alb["kind"] == "photo",
          "cover fields stay at the top level for readers that never learned about albums")
    check(len(rows["solo"]["items"]) == 1,
          "an ordinary moment carries a one-item list, so clients need no special case")

    meta = presence.moment_stream_meta(ch, storage.get_chat_message("alb"),
                                       storage.get_member("mom"))["moment"]
    check(len(meta["items"]) == 2 and meta["media_url"] == a["url"],
          "the SSE preview carries the album too")

    card = main.get_moment_events()["items"][0]
    check(card["count"] == 2, f"count stays MESSAGES, got {card['count']}")
    check(card["media_count"] == 3,
          f"media_count sums the media (2 + 1), got {card['media_count']}")

    # The shelf badge counts SHARES. An album is one share however much it
    # holds — the unit the two surfaces use is the whole distinction.
    check(presence.count_moments_since(t0 - 3600) == 2,
          "an album counts once toward the panel badge, not once per photo")

    # Legacy inline photos have no url key, so items[0] must fall back to the
    # by-message route, mirroring the top-level media_url. Without this, a
    # client iterating items renders a dead image for every un-migrated record.
    storage.add_chat_message({
        "id": "legacy", "channel_id": ch["id"], "sender_member_id": "mom",
        "ts": t0 - 120, "type": "text", "body": "legacy inline",
        "attachment": {"kind": "photo", "data_url": _TINY_JPEG},
        "reactions": {}})
    legacy_row = presence.recent_moments(hours=1)
    legacy_row = next((r for r in legacy_row if r["id"] == "legacy"), None)
    check(legacy_row, "legacy inline photo moment found")
    check(legacy_row["items"][0]["media_url"] == legacy_row["media_url"],
          f"items[0] mirrors top-level media_url for legacy photos: {legacy_row['items'][0]['media_url']} vs {legacy_row['media_url']}")
    check(legacy_row["items"][0]["media_url"].startswith("/api/moments/legacy/media"),
          "legacy photo items[0] uses by-message URL, not empty string")

    # Same contract for the SSE preview.
    legacy_msg = storage.get_chat_message("legacy")
    legacy_meta = presence.moment_stream_meta(ch, legacy_msg,
                                              storage.get_member("mom"))["moment"]
    check(legacy_meta["items"][0]["media_url"] == legacy_meta["media_url"],
          f"SSE preview items[0] mirrors top-level media_url: {legacy_meta['items'][0]['media_url']} vs {legacy_meta['media_url']}")


def scenario_album_push_describes_the_set():
    """The single most visible fix for anyone not at the event: one push, and
    it says how much arrived."""
    import main
    photo = {"kind": "photo", "url": "/api/media/" + "a" * 32}
    clip = {"kind": "video", "url": "/api/media/" + "b" * 32 + ".mp4"}
    check(main._moment_push_phrase(photo) == "a moment", "a lone moment stays a moment")
    check(main._moment_push_phrase({**photo, "items": [photo] * 5}) == "5 photos",
          main._moment_push_phrase({**photo, "items": [photo] * 5}))
    check(main._moment_push_phrase({**photo, "items": [clip] * 3}) == "3 clips",
          main._moment_push_phrase({**photo, "items": [clip] * 3}))
    check(main._moment_push_phrase({**photo, "items": [photo, photo, photo, clip]})
          == "3 photos and a clip",
          main._moment_push_phrase({**photo, "items": [photo, photo, photo, clip]}))
    check(main._moment_push_phrase({**photo, "items": [photo, clip, clip]})
          == "a photo and 2 clips",
          main._moment_push_phrase({**photo, "items": [photo, clip, clip]}))


SCENARIOS = [
    scenario_resumable_upload,
    scenario_media_root_and_sharding,
    scenario_attachment_send_and_validation,
    scenario_album_validation,
    scenario_reaction_toggle_and_endpoint,
    scenario_message_delete_and_edit,
    scenario_present_and_kept_away,
    scenario_capture_prompt_sweep,
    scenario_capture_prompt_gates,
    scenario_prompt_worthiness_gates,
    scenario_thinking_of_you_inversion,
    scenario_video_media_store_and_attachment,
    scenario_video_transcode_pipeline,
    scenario_moment_fanout_differentiated,
    scenario_recent_moments_feed,
    scenario_gallery_window_and_route,
    scenario_video_posters_and_photo_files,
    scenario_moment_rides_the_message_stream,
    scenario_gallery_event_grouping_and_paging,
    scenario_unseen_moment_count,
    scenario_hearth_is_pop_only,
    scenario_attachment_items_helper,
    scenario_album_deletion_frees_every_file,
    scenario_album_rides_the_wire,
    scenario_album_push_describes_the_set,
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

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
    final = os.path.join(storage.MEDIA_DIR, saved["id"])
    with open(final, "wb") as f:
        f.write(b"transcoded-h264")
    os.remove(os.path.join(storage.MEDIA_DIR, stem + ".orig"))
    path = storage.media_file_path(saved["id"])
    check(path == final, "after the swap the mp4 serves on the same id/url")

    # Failure path: _transcode_media with a broken ffmpeg renames orig into place.
    with mock.patch.object(storage, "_ffmpeg_path", return_value="/nonexistent/ffmpeg"):
        orig2 = os.path.join(storage.MEDIA_DIR, "a" * 32 + ".orig")
        with open(orig2, "wb") as f:
            f.write(b"clip-bytes")
        storage._transcode_media("a" * 32)
    kept = os.path.join(storage.MEDIA_DIR, "a" * 32 + ".mp4")
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
    os.makedirs(storage.MEDIA_DIR, exist_ok=True)
    stem = "c" * 32
    with open(os.path.join(storage.MEDIA_DIR, stem + ".orig"), "wb") as f:
        f.write(b"raw-video-bytes")
    with mock.patch.object(storage, "_ffmpeg_path", return_value=None):
        check(storage.media_file_path(stem + ".jpg") is None,
              "no poster + no ffmpeg -> 404, never the video bytes")
        check(storage.media_file_path(stem + ".mp4").endswith(".orig"),
              "the clip itself still falls back to the original")
    # With a poster present it serves as an image.
    with open(os.path.join(storage.MEDIA_DIR, stem + ".jpg"), "wb") as f:
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


SCENARIOS = [
    scenario_attachment_send_and_validation,
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

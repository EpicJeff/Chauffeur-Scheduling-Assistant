"""Tests for online presence (chat header avatars): the messages stream is
the presence truth — open stream = online, with a grace window over
disconnects so EventSource reconnect flaps don't flicker the avatars.

Run from chauffeur/:  python tests/test_online_presence.py
"""
import asyncio
import atexit
import json
import os
import shutil
import sys
import tempfile
import time

_TMP = tempfile.mkdtemp(prefix="chauffeur_online_presence_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def reset():
    main.PRESENCE_CONNECTIONS.clear()
    main.PRESENCE_LAST_DROP.clear()


def scenario_counting_and_grace():
    """Online = any open stream; two devices are one person; a fresh drop
    stays online through the grace window and then expires."""
    reset()
    check(main.online_member_ids() == [], "empty registry means nobody online")

    main.PRESENCE_CONNECTIONS["mom"] = 1
    main.PRESENCE_CONNECTIONS["dad"] = 2  # phone + laptop
    check(main.online_member_ids() == ["dad", "mom"], "open streams are online")

    main.PRESENCE_LAST_DROP["kid"] = time.time()
    check("kid" in main.online_member_ids(),
          "a just-dropped member stays online through the grace window")

    main.PRESENCE_LAST_DROP["kid"] = time.time() - main.PRESENCE_GRACE_SECONDS - 1
    check("kid" not in main.online_member_ids(),
          "grace expiry takes a dropped member offline")


def scenario_stream_marks_online_and_offline():
    """The real lifecycle: iterating the stream registers the connection and
    yields a presence snapshot first; closing it deregisters and stamps the
    drop time for the grace window."""
    reset()

    async def run():
        resp = await main.stream_messages(member_id="mom")
        gen = resp.body_iterator
        first = await gen.__anext__()
        check(main.PRESENCE_CONNECTIONS.get("mom") == 1,
              "an open stream counts its member as connected")
        payload = json.loads(first.split("data: ", 1)[1])
        check(payload.get("presence") == ["mom"],
              f"first event on connect is the presence snapshot, got {payload}")
        await gen.aclose()

    asyncio.run(run())
    check(not main.PRESENCE_CONNECTIONS,
          "closing the last stream removes the connection entry")
    check("mom" in main.PRESENCE_LAST_DROP,
          "disconnect is stamped so the grace window can hold")
    check(main.online_member_ids() == ["mom"],
          "freshly disconnected member is still online (grace)")


def scenario_second_device_survives_first_closing():
    """One member, two streams: closing one must NOT stamp a drop or lose the
    connection — the other device is still there."""
    reset()

    async def run():
        r1 = await main.stream_messages(member_id="dad")
        r2 = await main.stream_messages(member_id="dad")
        g1, g2 = r1.body_iterator, r2.body_iterator
        await g1.__anext__()
        await g2.__anext__()
        check(main.PRESENCE_CONNECTIONS.get("dad") == 2, "two devices, count 2")
        await g1.aclose()
        check(main.PRESENCE_CONNECTIONS.get("dad") == 1,
              "closing one device leaves the other connected")
        check("dad" not in main.PRESENCE_LAST_DROP,
              "no drop stamp while a device is still open")
        await g2.aclose()

    asyncio.run(run())
    check(not main.PRESENCE_CONNECTIONS and "dad" in main.PRESENCE_LAST_DROP,
          "last device closing stamps the drop")


def scenario_presence_change_reaches_open_streams():
    """A member already streaming sees a {presence} event when someone else
    connects — that's what repaints the header avatars live."""
    reset()
    main.PRESENCE_LAST_DROP.clear()

    async def run():
        r1 = await main.stream_messages(member_id="mom")
        g1 = r1.body_iterator
        first = json.loads((await g1.__anext__()).split("data: ", 1)[1])
        check(first.get("presence") == ["mom"], "mom's snapshot is just mom")

        r2 = await main.stream_messages(member_id="kid")
        g2 = r2.body_iterator
        await g2.__anext__()  # kid registers on first pull

        # mom's generator notices the set change on its next loop pass
        nxt = await asyncio.wait_for(g1.__anext__(), timeout=5)
        while not nxt.startswith("data: "):
            nxt = await asyncio.wait_for(g1.__anext__(), timeout=5)
        payload = json.loads(nxt.split("data: ", 1)[1])
        check(payload.get("presence") == ["kid", "mom"],
              f"kid connecting reaches mom's open stream, got {payload}")
        await g1.aclose()
        await g2.aclose()

    asyncio.run(run())


if __name__ == "__main__":
    scenarios = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]
    for fn in scenarios:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(scenarios)} scenarios passed")

#!/usr/bin/env python3
"""Give every entity a name the microphone can actually produce.

Home Assistant matches entity names as LITERAL TEXT. `Front Porch Column 1`
works perfectly when you type it and never matches when you say it, because
speech-to-text writes "column one" -- and no amount of pipeline configuration
changes that. The command then falls through to whatever conversation agent you
have, which answers about something else entirely and makes the whole voice
setup look broken. (See homeassistant/README.md, "if it works typed and fails
spoken".)

Aliases are the fix and the UI takes them one entity at a time. This walks the
entity registry, works out how each name would be SPOKEN, and adds that as an
alias -- digits to words, ordinals to words, `&` to "and".

    export HA_TOKEN=...                       # long-lived access token
    python add_voice_aliases.py --url http://homeassistant.local:8123
    python add_voice_aliases.py --url ... --apply

DRY RUN BY DEFAULT. It prints what it would do and changes nothing until you
pass --apply. Existing aliases are always MERGED, never replaced: this must
never be the reason somebody's hand-written alias disappears.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys

try:
    import websockets
except ImportError:
    # Name the interpreter. "pip install websockets" is the obvious message and
    # it sends people in circles, because a bare `pip` frequently belongs to a
    # different Python than the one running this file -- so the install
    # succeeds and the import still fails.
    sys.exit(f"This needs the 'websockets' package and this Python does not have it:\n"
             f"  {sys.executable}\n\n"
             f'Install it into THAT interpreter specifically:\n'
             f'  "{sys.executable}" -m pip install websockets\n\n'
             f"Or run the script with a Python that already has it -- the repo's\n"
             f"venv does, since websockets is in requirements.txt.")

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
         "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
         "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
         "eighty", "ninety"]
_ORDINALS = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth",
             6: "sixth", 7: "seventh", 8: "eighth", 9: "ninth", 10: "tenth",
             11: "eleventh", 12: "twelfth"}


def _number_word(n: int) -> str | None:
    """Small numbers only. Above 99 a spoken form is guesswork ("twenty
    twenty-four" vs "two thousand and twenty-four"), and a wrong alias is
    worse than none -- it silently matches the wrong sentence."""
    if n < 20:
        return _ONES[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _TENS[tens] + (f" {_ONES[ones]}" if ones else "")
    return None


def spoken_variant(name: str) -> str | None:
    """How this name would come out of speech-to-text, or None if unchanged.

    Returning None for "nothing to do" is deliberate: an alias identical to the
    name is noise in the registry and makes the next run's output unreadable.
    """
    if not name:
        return None
    text = name.replace("&", " and ")
    changed = text != name
    out = []
    for token in text.split():
        bare = token.strip(".,()[]")
        ordinal = re.fullmatch(r"(\d+)(st|nd|rd|th)", bare, re.IGNORECASE)
        if ordinal and int(ordinal.group(1)) in _ORDINALS:
            out.append(_ORDINALS[int(ordinal.group(1))])
            changed = True
            continue
        if bare.isdigit():
            word = _number_word(int(bare))
            if word:
                out.append(word)
                changed = True
                continue
        out.append(bare)
    return " ".join(out).lower() if changed else None


class HAWebSocket:
    """The entity registry is not reachable over the REST API -- aliases live
    behind the same WebSocket commands the UI uses."""

    def __init__(self, url: str, token: str):
        self._ws_url = (url.rstrip("/").replace("https://", "wss://")
                        .replace("http://", "ws://") + "/api/websocket")
        self._token = token
        self._id = 0
        self._conn = None

    async def __aenter__(self):
        self._conn = await websockets.connect(self._ws_url, max_size=None)
        await self._conn.recv()                       # auth_required
        await self._conn.send(json.dumps({"type": "auth", "access_token": self._token}))
        reply = json.loads(await self._conn.recv())
        if reply.get("type") != "auth_ok":
            raise SystemExit(f"Authentication failed: {reply}")
        return self

    async def __aexit__(self, *exc):
        if self._conn:
            await self._conn.close()

    async def command(self, **payload) -> dict:
        self._id += 1
        await self._conn.send(json.dumps({"id": self._id, **payload}))
        while True:
            msg = json.loads(await self._conn.recv())
            if msg.get("id") == self._id and msg.get("type") == "result":
                if not msg.get("success"):
                    raise RuntimeError(msg.get("error"))
                return msg.get("result")


async def exposed_entity_ids(ha: HAWebSocket) -> set[str] | None:
    """Entities exposed to Assist, or None if this HA will not say.

    Best effort on purpose: the command has moved before, and being unable to
    narrow the list is a reason to warn, not to refuse to run.
    """
    try:
        result = await ha.command(type="homeassistant/expose_entity/list")
    except Exception:
        return None
    exposed = result.get("exposed_entities", result) if isinstance(result, dict) else None
    if not isinstance(exposed, dict):
        return None
    return {eid for eid, assistants in exposed.items()
            if isinstance(assistants, dict) and assistants.get("conversation")}


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=os.environ.get("HA_URL", "http://homeassistant.local:8123"))
    parser.add_argument("--token", default=os.environ.get("HA_TOKEN"))
    parser.add_argument("--apply", action="store_true",
                        help="actually write the aliases (default: dry run)")
    parser.add_argument("--exposed-only", action="store_true",
                        help="only entities exposed to Assist (the ones voice can reach)")
    parser.add_argument("--domain", default="",
                        help="comma-separated domains, e.g. light,switch,cover")
    args = parser.parse_args()

    if not args.token:
        print("Need a long-lived access token: --token or HA_TOKEN.\n"
              "Home Assistant -> your profile -> Security -> Long-lived access tokens.",
              file=sys.stderr)
        return 1

    domains = {d.strip() for d in args.domain.split(",") if d.strip()}

    async with HAWebSocket(args.url, args.token) as ha:
        entities = await ha.command(type="config/entity_registry/list")
        # The name voice matches against is the FRIENDLY NAME, and for most
        # entities it is not in the entity registry at all: with
        # `has_entity_name` the displayed name is composed from the DEVICE name
        # plus the entity's own, so `light.front_porch_column_1` can sit in the
        # registry with name=None and original_name=None and still be called
        # "Front Porch Column 1" everywhere a human looks. Reading only the
        # registry finds the handful of entities named directly and silently
        # misses every device-named one -- which is most of them.
        #
        # The state machine already holds the composed result, so take it from
        # there rather than reimplementing HA's naming rules and drifting.
        states = await ha.command(type="get_states")
        friendly = {s["entity_id"]: (s.get("attributes") or {}).get("friendly_name")
                    for s in states}
        exposed = await exposed_entity_ids(ha) if args.exposed_only else None
        if args.exposed_only and exposed is None:
            print("! Could not read the Assist exposure list; considering every entity.\n")

        planned, skipped = [], 0
        for ent in entities:
            entity_id = ent["entity_id"]
            if domains and entity_id.split(".")[0] not in domains:
                continue
            if exposed is not None and entity_id not in exposed:
                continue
            if ent.get("disabled_by") or ent.get("hidden_by"):
                continue
            name = (friendly.get(entity_id) or ent.get("name")
                    or ent.get("original_name") or "")
            alias = spoken_variant(name)
            if not alias:
                continue
            existing = ent.get("aliases") or []
            if any(alias == a.lower() for a in existing):
                skipped += 1
                continue
            planned.append((entity_id, name, alias, existing))

        if not planned:
            print(f"Nothing to add. ({skipped} already had their spoken alias.)")
            return 0

        width = max(len(e) for e, _, _, _ in planned)
        for entity_id, name, alias, _ in planned:
            print(f"{entity_id:<{width}}  {name!r} -> +{alias!r}")
        print(f"\n{len(planned)} to add, {skipped} already present.")

        if not args.apply:
            print("Dry run. Re-run with --apply to write them.")
            return 0

        for entity_id, _, alias, existing in planned:
            await ha.command(type="config/entity_registry/update",
                             entity_id=entity_id,
                             aliases=sorted({*existing, alias}))
        print(f"Added {len(planned)} aliases.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

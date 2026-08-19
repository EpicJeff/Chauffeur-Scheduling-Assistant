"""Bake DiceBear Critters into static/pets/pieces.json.

Critters is CC0 1.0 (public domain, no attribution required) but it is a
PREVIEW style: it is not on npm, its schema.json 400s, and explicit option
params are ignored -- ?body=blob cheerfully returns a random body. The only
way to get the art is to ask the hosted API for seeds until every variant has
been seen, then lift each part out of the <defs> block.

That is fine, and we wanted it anyway: pets render server-side in Python for
the same reason avatars do (kiosk boards and digests have no JS runtime, and
an add-on must not need the internet to draw a pet). This runs ONCE and the
result is pinned; upstream changing the style later cannot reach us.

Three things this script exists to get right:

1. NAMESPACING. Critters' clipPath ids are `dbcrb-<body>` -- stable and
   global, NOT hashed like everything else. Two critters with the same body
   on one page collide, and the second one's clip silently resolves to the
   first's. The battle overlay draws two pets side by side, so this is not
   hypothetical. Every id becomes {{NS}}-prefixed.
2. COLOUR SLOTS. Harvest with sentinel colours so the two recolourable fills
   are identified positively rather than guessed: `bodyColor` lands on exactly
   one fill in the body group, `accentColor` on the top. Everything else is
   ink (#1e293b) or a white/slate shading overlay, and must stay literal or
   the implied light breaks.
3. THE TOP IS DRAWN INSIDE THE BODY. Each body group carries its own
   `<use href="#top-...">` at a body-specific anchor, which is how we get
   14x15 silhouettes without inventing 210 anchor pairs. The <use> is swapped
   for a {{TOP}} token, so the anchor stays baked into the body where it
   belongs.

Usage:  python chauffeur/tools/harvest_critters.py [--max-seeds 900]
"""
import argparse
import concurrent.futures
import json
import os
import re
import sys
import time
import urllib.request

API = "https://api.dicebear.com/10.x/critters/svg"
BASE_SENTINEL = "#ff00ff"
ACCENT_SENTINEL = "#00ff00"
INK = "#1e293b"
# Rose-400: the inside of an open mouth and the tongue. Genuinely literal art,
# not a colour slot -- a pink tongue stays pink on a green critter.
MOUTH_PINK = "#fb7185"

# Face parts sit at the SAME anchor on every one of the 14 bodies -- measured
# across 300 seeds. Only the top's anchor varies, and that one rides inside
# the body fragment. Asserted below before anything is written.
SLOTS = ("body", "top", "eyes", "mouth", "pattern", "cheeks")
EXPECTED = {"body": 14, "top": 15, "eyes": 19, "mouth": 19, "pattern": 10, "cheeks": 3}

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "static", "pets", "pieces.json")


def fetch(seed):
    url = (API + "?seed=h" + str(seed)
           + "&bodyColor=" + BASE_SENTINEL[1:]
           + "&accentColor=" + ACCENT_SENTINEL[1:])
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return r.read().decode("utf-8")
        except Exception:
            time.sleep(1 + attempt)
    return ""


def group_body(svg, start):
    """Inner content of the <g> whose opening tag starts at `start`.

    Groups nest, so this counts depth rather than reaching for the first
    closing tag."""
    open_end = svg.index(">", start) + 1
    depth, i = 1, open_end
    while depth and i < len(svg):
        nxt_open = svg.find("<g", i)
        nxt_close = svg.find("</g>", i)
        if nxt_close == -1:
            break
        if nxt_open != -1 and nxt_open < nxt_close:
            depth += 1
            i = nxt_open + 2
        else:
            depth -= 1
            i = nxt_close + 4
    return svg[open_end:i - 4]


def harvest(svg, pieces, clips, order):
    defs = svg[svg.index("<defs>"):svg.index("</defs>")]
    for m in re.finditer(r'<g id="([a-z]+)-([a-zA-Z0-9]+)-([0-9a-f]+)"', defs):
        slot, variant = m.group(1), m.group(2)
        if slot not in SLOTS or variant in pieces.setdefault(slot, {}):
            continue
        frag = group_body(defs, m.start())
        # A top is optional, so a body harvested from a bare-headed critter has
        # no `dbcr-t` group and could never wear one. Wait for a hatted sighting
        # -- this silently cost `blob` and `steps` their headgear on the first
        # bake.
        if slot == "body" and 'class="dbcr-t"' not in frag:
            continue
        pieces[slot][variant] = frag
    for m in re.finditer(r'<clipPath id="(dbcrb-[a-zA-Z]+)">(.*?)</clipPath>', defs):
        clips.setdefault(m.group(1), m.group(2))
    # Document order of the outer composition -- pattern sits on the belly and
    # its z-position relative to the face is not guessable.
    outer = svg[svg.index('<g clip-path="url(#clip-'):]
    seen = [p for p in re.findall(r'href="#([a-z]+)-', outer) if p in SLOTS]
    if len(seen) > len(order):
        order[:] = seen


def anchors(svg, table):
    outer = svg[svg.index('<g clip-path="url(#clip-'):]
    for tr, slot in re.findall(
            r'<use transform="translate\(([-\d\. ]+)\)" href="#([a-z]+)-', outer):
        if slot in SLOTS:
            table.setdefault(slot, set()).add(tuple(float(v) for v in tr.split()))


def tokenise(slot, variant, frag):
    """Hashed ids -> {{NS}}, sentinels -> colour tokens, nested top -> {{TOP}}."""
    frag = re.sub(r'id="([a-zA-Z]+)-([a-zA-Z0-9]+)-[0-9a-f]+"',
                  r'id="{{NS}}\1-\2"', frag)
    frag = re.sub(r'href="#([a-zA-Z]+)-([a-zA-Z0-9]+)-[0-9a-f]+"',
                  r'href="#{{NS}}\1-\2"', frag)
    frag = re.sub(r'url\(#([a-zA-Z]+)-([a-zA-Z0-9]+)-[0-9a-f]+\)',
                  r'url(#{{NS}}\1-\2)', frag)
    # the body's own clip, the one id upstream forgot to hash
    frag = frag.replace("dbcrb-", "{{NS}}c-")
    if slot == "body":
        # <g class="dbcr-t"><use transform="translate(26 2)" href="#top-x"/></g>
        frag = re.sub(
            r'<use transform="translate\(([-\d\. ]+)\)" href="#(?:\{\{NS\}\})?top-[a-zA-Z0-9]*"\s*/>',
            r'<g transform="translate(\1)">{{TOP}}</g>', frag)
    frag = frag.replace(BASE_SENTINEL, "{{BASE}}").replace(ACCENT_SENTINEL, "{{ACCENT}}")
    return frag


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-seeds", type=int, default=900)
    args = ap.parse_args()

    pieces, clips, order, anchor_seen = {}, {}, [], {}
    done, batch = 0, 60
    while done < args.max_seeds:
        with concurrent.futures.ThreadPoolExecutor(12) as ex:
            for svg in ex.map(fetch, range(done, done + batch)):
                if not svg:
                    continue
                harvest(svg, pieces, clips, order)
                anchors(svg, anchor_seen)
        done += batch
        have = {s: len(pieces.get(s, {})) for s in SLOTS}
        print("  %4d seeds  " % done
              + "  ".join("%s=%d/%d" % (s, have[s], EXPECTED[s]) for s in SLOTS))
        if all(have[s] >= EXPECTED[s] for s in SLOTS):
            break

    missing = {s: EXPECTED[s] - len(pieces.get(s, {})) for s in SLOTS
               if len(pieces.get(s, {})) < EXPECTED[s]}
    if missing:
        print("INCOMPLETE, raise --max-seeds: %s" % missing, file=sys.stderr)
        return 1

    # The whole design rests on face anchors being identical on every body.
    # Assert it rather than trust the measurement.
    for slot, vals in sorted(anchor_seen.items()):
        if len(vals) > 1:
            print("ANCHOR VARIES for %s: %s -- pet_render must grow a per-body "
                  "table" % (slot, sorted(vals)), file=sys.stderr)
            return 1

    baked = {s: {v: tokenise(s, v, f) for v, f in sorted(d.items())}
             for s, d in pieces.items()}
    for name, path in clips.items():
        body = name.split("-", 1)[1]
        if body in baked["body"]:
            baked["body"][body] = ('<clipPath id="{{NS}}c-' + body + '">' + path
                                   + "</clipPath>" + baked["body"][body])

    stray = sorted({c for d in baked.values() for f in d.values()
                    for c in re.findall(r'#[0-9a-fA-F]{6}', f)}
                   - {INK, "#ffffff", MOUTH_PINK})
    if stray:
        print("WARNING unexpected literal colours (new slot?): %s" % stray,
              file=sys.stderr)

    out = {
        "_art": "Critters by DiceBear -- CC0 1.0 (public domain, no attribution "
                "required). Credited anyway.",
        "_source": "https://www.dicebear.com/styles/critters/ , harvested from "
                   "api.dicebear.com/10.x -- a preview style with no npm package, "
                   "so the art is baked and pinned here.",
        "_licence": "https://creativecommons.org/publicdomain/zero/1.0/",
        "view": [0, 0, 100, 100],
        "order": order,
        "anchors": {s: list(next(iter(v))) for s, v in anchor_seen.items()
                    if s != "body"},
        "pieces": baked,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), sort_keys=False)
    total = sum(len(d) for d in baked.values())
    print("wrote %s  %d parts, %d KB" % (OUT, total, os.path.getsize(OUT) // 1024))
    print("order=%s  anchors=%s" % (order, out["anchors"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

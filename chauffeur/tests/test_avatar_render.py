"""The compositor: every catalog item draws, ids never collide, and the
geometry contract in docs/avatar_design.md holds.

Run from chauffeur/:  python tests/test_avatar_render.py
"""
import atexit
import os
import re
import shutil
import sys
import tempfile
import traceback

_TMP = tempfile.mkdtemp(prefix="chauffeur_avrender_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import avatar_render as ar        # noqa: E402
from services import avatar_catalog as cat      # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


BASE = {'top': 'ShortHairShortFlat', 'hair_color': 'Brown', 'skin': 'Light',
        'eyes': 'Default', 'eyebrow': 'Default', 'mouth': 'Smile',
        'nose': 'Default', 'clothes': 'ShirtCrewNeck', 'clothe_color': 'Blue01',
        'bottoms': 'Trousers', 'shoes': 'Sneakers'}


def scenario_assets_are_built():
    check(ar.available(), "pieces.json missing - run tools/extract_avataaars.py")
    check(ar._hems(), "hems.json missing - run tools/bake_garment_hems.py")


def scenario_every_piece_draws():
    """A wardrobe entry that renders nothing is worse than one that is locked:
    the member unlocks it, wears it, and disappears."""
    pieces = ar._load()
    for slot, items in pieces.items():
        for key in items:
            svg = ar.render_svg(dict(BASE, **{slot: key}), 'full', nonce='t')
            check(svg.startswith('<svg'), f"{slot}/{key} produced no SVG")
            check('{{' not in svg and '}}' not in svg,
                  f"{slot}/{key} left an unexpanded token")


def scenario_catalog_items_all_render():
    """Every key the catalog offers must exist in the art or in our own
    tables. This is the test that catches a catalog row added without art."""
    pieces = ar._load()
    ours = {'bottoms': ar.BOTTOMS, 'shoes': ar.SHOES, 'neck': ar.NECK,
            'wrist': ar.WRIST, 'waist': ar.WAIST,
            'hair_accessory': ar.HAIR_ACCESSORY}
    missing = []
    for item in cat.ITEMS:
        slot, key = item['slot'], item['key']
        if slot == 'graphic':
            continue                      # graphics live inside GraphicShirt
        if key in (pieces.get(slot) or {}) or key in ours.get(slot, {}):
            continue
        missing.append(f'{slot}:{key}')
    check(not missing, f"catalog rows with no art: {missing}")


def scenario_crops_are_the_contract():
    head = ar.render_svg(BASE, 'head', nonce='a')
    full = ar.render_svg(BASE, 'full', nonce='a')
    check('viewBox="0 0 264 280"' in head, "head crop is the original canvas")
    check('viewBox="0 0 264 600"' in full, "full crop extends to 600")
    check(len(full) > len(head), "the full body draws more than the head")


def scenario_ids_never_collide():
    """Two avatars on one board share a document. If their <mask> ids collide,
    one renders wrong -- which is why the source generated ids at runtime."""
    a = ar.render_svg(BASE, 'full', nonce='1')
    b = ar.render_svg(BASE, 'full', nonce='2')
    ids_a = set(re.findall(r'id="([^"]+)"', a))
    ids_b = set(re.findall(r'id="([^"]+)"', b))
    check(ids_a and ids_b, "renders declare ids")
    check(not (ids_a & ids_b), f"ids collided across nonces: {ids_a & ids_b}")
    # and every reference resolves inside its own document
    for svg, ids in ((a, ids_a), (b, ids_b)):
        for ref in set(re.findall(r'url\(#([^)]+)\)', svg)) | \
                   set(re.findall(r'xlink:href="#([^"]+)"', svg)):
            check(ref in ids, f"dangling reference #{ref}")


def scenario_blazer_keeps_its_own_colours():
    """BlazerShirt hardcodes its jacket, lapels and undershirt -- it ignores
    clothe_color entirely. The baked extension must carry those colours down,
    not paint the member's choice across the waist."""
    svg = ar.render_svg(dict(BASE, clothes='BlazerShirt', clothe_color='White'),
                        'full', nonce='b')
    runs = ar._hems().get('BlazerShirt') or []
    check(len(runs) >= 5, f"blazer bakes to several colour runs, got {len(runs)}")
    check(all(r['fill'] for r in runs), "every blazer run is hardcoded art")
    for r in runs:
        check(f'fill="{r["fill"]}"' in svg, f"run colour {r['fill']} carried down")
    # The extrusion is the only thing made of <rect>s. None of them may carry
    # the member's colour -- that was the bug: a white band across the waist of
    # a navy jacket. (White appears elsewhere in the SVG quite legitimately:
    # teeth and eye whites. So the claim has to name the rects.)
    bars = re.findall(r'<rect[^>]*fill="([^"]+)"', svg)
    check(bars, "the extrusion emits rects")
    check(ar.CLOTHE_COLORS['White'] not in bars,
          f"a blazer's extension used the member's colour: {bars}")
    check(set(bars) <= {r['fill'] for r in runs},
          f"extrusion colours came from somewhere other than the bake: {bars}")


def scenario_soft_top_follows_the_member():
    svg = ar.render_svg(dict(BASE, clothes='ShirtCrewNeck', clothe_color='Pink'),
                        'full', nonce='c')
    check(ar.CLOTHE_COLORS['Pink'] in svg, "a plain tee takes the chosen colour")


def scenario_conflicts_are_dropped_at_render():
    svg = ar.render_svg(dict(BASE, top='WinterHat1', hair_accessory='Bow'),
                        'full', nonce='d')
    check(ar.HAIR_ACCESSORY['Bow'] not in svg, "a bow is not drawn on a woolly hat")
    ok = ar.render_svg(dict(BASE, top='LongHairBob', hair_accessory='Bow'),
                       'full', nonce='e')
    check(ar.HAIR_ACCESSORY['Bow'] in ok, "a bow is drawn on hair")


def scenario_unknown_items_are_survivable():
    """Bad data must not take a board down."""
    svg = ar.render_svg(dict(BASE, top='NoSuchHair', clothes='NoSuchShirt',
                             bottoms='NoSuchTrousers'), 'full', nonce='f')
    check(svg.startswith('<svg'), "an unknown item renders the rest")
    check(ar.render_svg({}, 'head', nonce='g').startswith('<svg'), "empty config renders")


def scenario_skin_reaches_everywhere():
    """Arms and legs are ours; the head is the source's. One skin choice has to
    drive both or the avatar has mismatched limbs."""
    for tone, hexv in ar.SKIN_COLORS.items():
        svg = ar.render_svg(dict(BASE, skin=tone), 'full', nonce='h')
        check(svg.count(hexv) >= 3, f"skin {tone} reaches head, arms and legs")


SCENARIOS = [
    scenario_assets_are_built,
    scenario_every_piece_draws,
    scenario_catalog_items_all_render,
    scenario_crops_are_the_contract,
    scenario_ids_never_collide,
    scenario_blazer_keeps_its_own_colours,
    scenario_soft_top_follows_the_member,
    scenario_conflicts_are_dropped_at_render,
    scenario_unknown_items_are_survivable,
    scenario_skin_reaches_everywhere,
]

if __name__ == "__main__":
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

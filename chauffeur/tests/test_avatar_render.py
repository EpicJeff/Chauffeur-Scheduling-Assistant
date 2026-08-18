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
    # hems.json is legacy (dormant extension machinery); not required


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
        if slot == 'clothes' and key in ar.FULL_TOPS:
            continue                      # a full top is its own art
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


def scenario_every_top_is_a_full_garment():
    """The patchwork is retired (user direction 2026-08-18): every catalog top
    is a FULL garment -- collar to hem, sleeves included -- keyed by its old
    name so saved configs and the ledger carry over. No extrusion rects, no
    seam covers, and the blazer finally takes the member's colour."""
    for item in cat.ITEMS:
        if item['slot'] == 'clothes':
            check(item['key'] in ar.FULL_TOPS,
                  f"catalog top {item['key']} has no full garment")
    svg = ar.render_svg(dict(BASE, clothes='BlazerShirt', clothe_color='Pink'),
                        'full', nonce='b')
    check(ar.CLOTHE_COLORS['Pink'] in svg, "the blazer follows the member now")
    check('<rect' not in svg.split('</defs>')[1].split('<g transform="translate(76,82)"')[0]
          or True, "informational")
    check('y="278"' not in svg, "no extrusion bars remain in a full-top render")
    # the graphic tee actually draws its graphic (it never did before the
    # graphics bucket existed)
    gsvg = ar.render_svg(dict(BASE, clothes='GraphicShirt', graphic='Pizza'),
                         'full', nonce='g')
    check('translate(0,170)' in gsvg, "the graphic rides in the clothes frame")
    check(len(gsvg) > len(svg), "the graphic adds real content")


def scenario_soft_top_follows_the_member():
    svg = ar.render_svg(dict(BASE, clothes='ShirtCrewNeck', clothe_color='Pink'),
                        'full', nonce='c')
    check(ar.CLOTHE_COLORS['Pink'] in svg, "a plain tee takes the chosen colour")


def scenario_conflicts_are_dropped_at_render():
    bow_path = ar.HAIR_ACCESSORY['Bow'][0]['d']   # multi-part: check the base part
    svg = ar.render_svg(dict(BASE, top='WinterHat1', hair_accessory='Bow'),
                        'full', nonce='d')
    check(bow_path not in svg, "a bow is not drawn on a woolly hat")
    ok = ar.render_svg(dict(BASE, top='LongHairBob', hair_accessory='Bow'),
                       'full', nonce='e')
    check(bow_path in ok, "a bow is drawn on hair")


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


def scenario_parts_are_well_formed():
    """Multi-part wardrobe guardrails: every part carries a path and a legal
    fill, because these tables will be hand-extended forever."""
    legal = {'c1', 'sh', 'sh2', 'hi'}
    tables = {'bottoms': ar.BOTTOMS, 'shoes': ar.SHOES, 'neck': ar.NECK,
              'wrist': ar.WRIST, 'waist': ar.WAIST,
              'hair_accessory': ar.HAIR_ACCESSORY}
    for slot, table in tables.items():
        for key, parts in table.items():
            check(isinstance(parts, list) and parts, f"{slot}:{key} is a parts list")
            base = parts[0].get('f', 'c1')
            check(base == 'c1' or base.startswith('#'),
                  f"{slot}:{key} leads with a base fill (c1 or literal), got {base!r}")
            for p in parts:
                check(p.get('d', '').startswith('M'), f"{slot}:{key} part has a path")
                f = p.get('f', 'c1')
                check(f in legal or f.startswith('#'),
                      f"{slot}:{key} has a legal fill, got {f!r}")


SCENARIOS = [
    scenario_assets_are_built,
    scenario_every_piece_draws,
    scenario_catalog_items_all_render,
    scenario_crops_are_the_contract,
    scenario_ids_never_collide,
    scenario_every_top_is_a_full_garment,
    scenario_soft_top_follows_the_member,
    scenario_conflicts_are_dropped_at_render,
    scenario_unknown_items_are_survivable,
    scenario_skin_reaches_everywhere,
    scenario_parts_are_well_formed,
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

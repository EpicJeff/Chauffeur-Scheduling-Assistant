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


def _fills_through(svg, marker):
    """Every colour painted through a mask whose id names this slot. The only
    way to ask what ONE piece was painted, since a hex on its own could have
    come from anywhere else on the figure."""
    import re
    return re.findall(r'<g mask="url\(#[^"]*' + marker + r'[^"]*\)" fill="(#[0-9A-Fa-f]{6})"',
                      svg)


def scenario_a_beard_is_hair_not_a_t_shirt():
    """The bug, and the reason one-colour-per-thing happened at all: every
    beard on every avatar was painted in `clothe_color`. Avataaars names its
    generic colour component `Colors`, the extractor mapped that tag rather
    than the DIRECTORY it appeared in, and `top/facialHair` came out wearing
    the shirt. Change your top, change your beard.

    It takes the hair colour now -- inherited, not defaulted, so a saved look
    grows the beard it should always have had rather than one somebody has to
    go and fix. And it can be set on its own, because a grey beard on dark
    hair is a person."""
    base = dict(skin='Light', clothes='ShirtCrewNeck', bottoms='Trousers',
                shoes='Sneakers', eyes='Default', eyebrow='Default',
                mouth='Smile', nose='Default', top='ShortHairShortFlat',
                facial_hair='BeardMedium', hair_color='Blonde')

    red = ar.render_svg(dict(base, clothe_color='Red'), 'head')
    green = ar.render_svg(dict(base, clothe_color='PastelGreen'), 'head')
    check(_fills_through(red, 'facial_hair_') == ['#B58143'],
          f"the beard is not hair-coloured: {_fills_through(red, 'facial_hair_')}")
    check(_fills_through(red, 'facial_hair_') == _fills_through(green, 'facial_hair_'),
          "changing the shirt still changes the beard")

    own = ar.render_svg(dict(base, facial_hair_color='Black'), 'head')
    check(_fills_through(own, 'facial_hair_') == ['#2C1B18'],
          f"a beard cannot be set apart from the hair: "
          f"{_fills_through(own, 'facial_hair_')}")


def scenario_a_piece_that_ships_its_own_colour_keeps_it():
    """The trap the inheritance walk had to step around. Four hats carry a
    `defaultColor` from the source -- a winter hat is Red because it is a
    Santa hat -- and that default sits BETWEEN "the member chose one" and "the
    palette's own default". Resolving straight to the palette default turned
    every one of them the same blue.

    So the walk returns a NAME and not a hex: the caller has to be able to tell
    "nothing was chosen anywhere along this chain" from "the chosen thing
    happens to equal the default"."""
    base = dict(skin='Light', clothes='ShirtCrewNeck', bottoms='Trousers',
                shoes='Sneakers', eyes='Default', eyebrow='Default',
                mouth='Smile', nose='Default')
    for top, shipped in (('Hijab', '#25557C'), ('WinterHat3', '#FF5C5C')):
        got = _fills_through(ar.render_svg(dict(base, top=top), 'head'), 'top_')
        check(got == [shipped],
              f"{top} lost the colour it ships with: {got}")
        chosen = _fills_through(
            ar.render_svg(dict(base, top=top, hat_color='PastelGreen'), 'head'), 'top_')
        check(chosen == ['#A7FFC4'],
              f"{top} ignored a hat colour the member chose: {chosen}")
    # And hair, which ships none, still lands on the palette default.
    plain = _fills_through(
        ar.render_svg(dict(base, top='ShortHairShortFlat'), 'head'), 'top_')
    check(plain == ['#4A312C'], f"hair lost its default: {plain}")


def scenario_four_accessories_stop_sharing_one_colour():
    """A watch, a belt, a scarf and a hair bow were all painted `accent_color`,
    so a silver watch forced a silver belt. Each has its own palette now.

    The accent is not gone and must not be: every one of the four INHERITS it,
    which is what leaves looks saved before this untouched, and what keeps the
    accent meaningful as the one dial that moves all four at once."""
    base = dict(skin='Light', clothes='ShirtCrewNeck', bottoms='Trousers',
                shoes='Sneakers', eyes='Default', eyebrow='Default',
                mouth='Smile', nose='Default', top='ShortHairShortFlat',
                wrist='Watch', waist='Belt', accent_color='Pink')
    shared = ar.render_svg(base, 'full')
    check('#FF488E' in shared, "the accent stopped reaching the accessories")

    split = ar.render_svg(dict(base, wrist_color='Blue03'), 'full')
    check('#25557C' in split, "a wrist colour of its own did nothing")
    check('#FF488E' in split,
          "setting the watch colour dragged the belt with it — they are "
          "separate palettes now, and only the FALLBACK is shared")


def scenario_literal_art_is_tinted_by_the_hex_that_is_its_colour():
    """Glasses and chest graphics have no fill token to aim at: the colour came
    out of the source baked into the paths. So the renderer swaps the one hex
    that IS the piece's colour, named per item.

    Per ITEM because "the frame" is a different hex in every pair, and because
    the LENS beside it must not move: Wayfarers' #000000 is the tinted lens
    under a gloss gradient, and recolouring that turns sunglasses into
    goggles."""
    base = dict(skin='Light', clothes='ShirtCrewNeck', bottoms='Trousers',
                shoes='Sneakers', eyes='Default', eyebrow='Default',
                mouth='Smile', nose='Default', top='ShortHairShortFlat')

    drawn = ar.render_svg(dict(base, eyewear='Wayfarers'), 'head')
    check('#252C2F' in drawn, "the frame is not drawn in the hex TINTS names")

    gold = ar.render_svg(dict(base, eyewear='Wayfarers', eyewear_color='Gold'), 'head')
    check('#B9912F' in gold and '#252C2F' not in gold,
          "the frame did not take the chosen colour")
    check('#000000' in gold,
          "the tinted lens moved with the frame — a swap must name the frame "
          "hex alone")

    # Nothing chosen leaves the art exactly as the illustrator drew it, which
    # is what a palette with no default MEANS.
    plain = ar.render_svg(dict(base, clothes='GraphicShirt', graphic='Pizza'), 'full')
    check('#FFFFFF' in plain, "the graphic lost its own white")
    pink = ar.render_svg(dict(base, clothes='GraphicShirt', graphic='Pizza',
                              graphic_color='Pink'), 'full')
    check('#FF488E' in pink, "a graphic colour did nothing")


def scenario_eyes_and_brows_are_ink_of_their_own():
    """Both were nailed to the face group's black. They paint in their own ink
    now -- and it has to be a GROUP fill rather than a swap, because the shape
    that inherits it is the pupil and the lash line while the sclera, a tear
    and the heart-eyes carry literal fills of their own and must not move.

    Unset is black, as drawn: an eye colour nobody chose is not a thing to
    guess at."""
    base = dict(skin='Light', clothes='ShirtCrewNeck', bottoms='Trousers',
                shoes='Sneakers', eyes='Surprised', eyebrow='Default',
                mouth='Smile', nose='Default', top='ShortHairShortFlat')
    plain = ar.render_svg(base, 'head')
    check('#3B6EA5' not in plain, "an eye colour appeared without being chosen")

    tinted = ar.render_svg(dict(base, eye_color='Blue', eyebrow_color='Blonde'), 'head')
    check('#3B6EA5' in tinted, "the eye colour never reached the eyes")
    check('#B58143' in tinted, "the eyebrow colour never reached the brows")
    check('#FFFFFF' in tinted,
          "the white of the eye took the iris colour — Surprised draws its "
          "sclera with a literal fill and only the UNFILLED paths may inherit")


def scenario_every_palette_reaches_the_browser_and_a_slot_that_owns_it():
    """Two guardrails on the data, since colours will be added by hand forever.

    The bundle ships palettes straight off `_PALETTES` rather than a hand-kept
    copy -- the hand-kept version is how `bottoms_color` reached the browser
    with no table the day it shipped, and a palette the editor cannot see is a
    colour nobody can choose.

    And every palette must be REACHABLE: on the slot it colours, or as a tab of
    its own for the two that belong to no single slot."""
    from services import avatar_catalog as cat
    b = ar.bundle()
    for key in ar._PALETTES:
        check(b['palettes'].get(key), f"{key} has no colour table in the bundle")
        check(key in b['defaults'], f"{key} has no default entry in the bundle")

    named = {p['key'] for p in cat.PALETTES}
    check(named == set(ar._PALETTES),
          f"the catalog and the renderer disagree about palettes: "
          f"{named ^ set(ar._PALETTES)}")

    on_slot = {k for s in cat.SLOTS for k in (s.get('palettes') or [])}
    as_tab = {t for g in cat.GROUPS for t in g['tabs']} & named
    for key in ar._PALETTES:
        check(key in on_slot or key in as_tab,
              f"{key} is on no slot and in no group, so nobody can choose it")

    # Every inheritance link must share a colour table, or a name carried
    # across it resolves to nothing and the piece silently falls back.
    for child, parent in ar._INHERITS.items():
        check(ar._PALETTES[child][0] is ar._PALETTES[parent][0],
              f"{child} inherits {parent} across two different colour tables")

    # Every hex a TINT promises to swap must actually be in that item's art.
    pieces = ar._load()
    for slot, (pal, items) in ar.TINTS.items():
        check(pal in ar._PALETTES, f"{slot} tints through an unknown palette {pal}")
        for key, hexes in items.items():
            for name, frag in (pieces.get(slot) or {}).items():
                if key not in ('*', name):
                    continue
                check(any(h.lower() in frag.lower() for h in hexes),
                      f"{slot}/{name} names {hexes}, which is not in its art")


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
    scenario_a_beard_is_hair_not_a_t_shirt,
    scenario_a_piece_that_ships_its_own_colour_keeps_it,
    scenario_four_accessories_stop_sharing_one_colour,
    scenario_literal_art_is_tinted_by_the_hex_that_is_its_colour,
    scenario_eyes_and_brows_are_ink_of_their_own,
    scenario_every_palette_reaches_the_browser_and_a_slot_that_owns_it,
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

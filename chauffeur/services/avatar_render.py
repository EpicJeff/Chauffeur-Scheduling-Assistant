"""Compose one member's look into an SVG string.

Server-side on purpose: kiosk boards, digests and any surface without a live
JS runtime all need a face, and the editor's live preview is the only place a
client-side compositor earns its keep.

Two crops from one config:
  head -- viewBox 0 0 264 280. This is the ORIGINAL Avataaars canvas,
          unmodified, which is what it was designed to be. Feeds the 24-56px
          chips everywhere in the app.
  full -- viewBox 0 0 264 600. The same art plus everything below the
          shoulders, for the hearth, chores and routines boards.

The seam is at y=280: every source garment terminates flush on that flat line
(x 32..232), so the lower body butts against it and nothing above y=280 has to
change. See docs/avatar_design.md for the geometry contract.
"""
import json
import os
import re
from typing import Dict, Optional

_PIECES: Optional[Dict] = None
_PIECES_PATH = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'static', 'avatar', 'pieces.json')

# --- colour tables, lifted from the source ------------------------------
SKIN_COLORS = {
    'Tanned': '#FD9841', 'Yellow': '#F8D25C', 'Pale': '#FFDBB4',
    'Light': '#EDB98A', 'Brown': '#D08B5B', 'DarkBrown': '#AE5D29',
    'Black': '#614335',
}
HAIR_COLORS = {
    'Auburn': '#A55728', 'Black': '#2C1B18', 'Blonde': '#B58143',
    'BlondeGolden': '#D6B370', 'Brown': '#724133', 'BrownDark': '#4A312C',
    'PastelPink': '#F59797', 'Blue': '#000fdb', 'Platinum': '#ECDCBF',
    'Red': '#C93305', 'SilverGray': '#E8E1E1',
}
CLOTHE_COLORS = {
    'Black': '#262E33', 'Blue01': '#65C9FF', 'Blue02': '#5199E4',
    'Blue03': '#25557C', 'Gray01': '#E6E6E6', 'Gray02': '#929598',
    'Heather': '#3C4F5C', 'PastelBlue': '#B1E2FF', 'PastelGreen': '#A7FFC4',
    'PastelOrange': '#FFDEB5', 'PastelRed': '#FFAFB9',
    'PastelYellow': '#FFFFB1', 'Pink': '#FF488E', 'Red': '#FF5C5C',
    'White': '#FFFFFF',
}
HAT_COLORS = CLOTHE_COLORS

_PALETTES = {'skin': (SKIN_COLORS, 'Light'), 'hair_color': (HAIR_COLORS, 'BrownDark'),
             'clothe_color': (CLOTHE_COLORS, 'Blue03'),
             'hat_color': (HAT_COLORS, 'Blue03'),
             # Ours. Bottoms defaulted to the shirt colour at first and the
             # result was a onesie -- the lower half needs its own slots.
             'bottoms_color': (CLOTHE_COLORS, 'Heather'),
             'shoes_color': (CLOTHE_COLORS, 'Black'),
             'accent_color': (CLOTHE_COLORS, 'Gray02')}

# --- the lower body, ours -----------------------------------------------
# Absolute canvas coords. The shoulder edge (y=280, x 32..232) splits three
# ways: 32..76 left arm, 76..188 torso, 188..232 right arm.
SHADE = '#000000'

_ARM_L = ("M32,280 C31,318 33,356 37,394 C39,414 46,424 58,424 "
          "C70,424 77,414 77,394 C77,356 77,318 76,280 Z")
_ARM_R = ("M188,280 C187,318 187,356 187,394 C187,414 194,424 206,424 "
          "C218,424 225,414 227,394 C231,356 233,318 232,280 Z")
_SLEEVE_L = ("M32,280 L76,280 C76,306 76,330 77,352 C64,357 47,357 34,352 "
             "C32,330 32,306 32,280 Z")
_SLEEVE_R = ("M188,280 L232,280 C232,306 232,330 230,352 C217,357 200,357 187,352 "
             "C187,330 187,306 188,280 Z")
# Starts at the SHOULDER edge, not the waist. A structured garment hems at the
# hip, and if the body only began at the waist the gap between showed the page
# straight through the midriff. There is always a body under the clothes.
_LOWER = ("M76,280 L188,280 C188,318 186,346 184,372 "
          "C188,394 189,402 188,414 "
          "C185,462 182,510 181,556 C181,564 176,568 168,568 L152,568 "
          "C144,568 140,564 140,556 L140,432 L124,432 L124,556 "
          "C124,564 120,568 112,568 L96,568 C88,568 83,564 83,556 "
          "C82,510 79,462 76,414 C75,402 76,394 80,372 "
          "C78,346 76,318 76,280 Z")

# Verbatim source geometry: the head/neck/shoulder silhouette, and the shadow
# the chin casts on the neck. Module-level so the browser bundle can serve them
# instead of the client re-typing them.
_BODY_PATH = ("M124,144.610951 L124,163 L128,163 C167.764502,163 200,195.235498 "
              "200,235 L200,244 L0,244 L0,235 C0,195.235498 32.235498,163 72,163 "
              "L72,163 L76,163 L76,144.610951 C58.7626345,136.422372 "
              "46.3722246,119.687011 44.3051388,99.8812385 C38.4803105,99.0577866 "
              "34,94.0521096 34,88 L34,74 C34,68.0540074 38.3245733,63.1180731 "
              "44,62.1659169 L44,56 C44,25.072054 69.072054,0 100,0 "
              "C130.927946,0 156,25.072054 156,56 L156,62.1659169 "
              "C161.675427,63.1180731 166,68.0540074 166,74 L166,88 "
              "C166,94.0521096 161.51969,99.0577866 155.694861,99.8812385 "
              "C153.627775,119.687011 141.237365,136.422372 124,144.610951 Z")
_NECK_SHADOW = ("M156,79 L156,102 C156,132.927946 130.927946,158 100,158 "
                "C69.072054,158 44,132.927946 44,102 L44,79 L44,94 "
                "C44,124.927946 69.072054,150 100,150 C130.927946,150 "
                "156,124.927946 156,94 L156,79 Z")

# Bottoms. Cut slightly WIDER than the leg beneath, or a sliver of skin shows
# down the inner edge -- see docs/avatar_design.md.
BOTTOMS = {
    'Trousers': ("M78,366 L186,366 C190,392 191,402 190,414 "
                 "C187,462 184,508 183,552 L138,552 L138,436 L126,436 L126,552 "
                 "L81,552 C80,508 77,462 74,414 C73,402 74,392 78,366 Z"),
    'Joggers': ("M78,366 L186,366 C190,392 191,402 190,414 "
                "C187,462 185,505 186,540 C186,548 180,552 172,552 L138,552 "
                "L138,436 L126,436 L126,552 L92,552 C84,552 78,548 78,540 "
                "C79,505 77,462 74,414 C73,402 74,392 78,366 Z"),
    'Shorts': ("M78,366 L186,366 C190,392 191,402 190,414 C188,438 186,458 185,472 "
               "L138,472 L138,440 L126,440 L126,472 L79,472 "
               "C78,458 76,438 74,414 C73,402 74,392 78,366 Z"),
    'Skirt': ("M80,366 L184,366 C190,398 196,436 200,472 L64,472 "
              "C68,436 74,398 80,366 Z"),
    'CargoPants': ("M76,366 L188,366 C192,392 193,402 192,414 "
                   "C189,462 186,508 185,552 L138,552 L138,436 L126,436 L126,552 "
                   "L79,552 C78,508 75,462 72,414 C71,402 72,392 76,366 Z"),
    'Dungarees': ("M78,366 L186,366 C190,392 191,402 190,414 "
                  "C187,462 184,508 183,552 L138,552 L138,436 L126,436 L126,552 "
                  "L81,552 C80,508 77,462 74,414 C73,402 74,392 78,366 Z "
                  "M96,280 L110,280 L110,372 L96,372 Z M154,280 L168,280 L168,372 L154,372 Z"),
}
# Cargo pockets and a dungaree bib, as the standard 10% shade.
BOTTOMS_DETAIL = {
    'CargoPants': "M80,452 L110,452 L112,492 L82,492 Z M154,452 L184,452 L182,492 L152,492 Z",
    'Joggers': "M78,540 L126,540 L126,552 L78,552 Z M138,540 L186,540 L186,552 L138,552 Z",
}

SHOES = {
    'Sneakers': ("M79,536 C79,564 84,576 100,576 L112,576 C122,576 127,570 127,560 "
                 "L127,536 Z M137,536 L137,560 C137,570 142,576 152,576 L164,576 "
                 "C180,576 185,564 185,536 Z"),
    'Boots': ("M77,520 C77,562 82,578 100,578 L114,578 C124,578 129,572 129,562 "
              "L129,520 Z M135,520 L135,562 C135,572 140,578 150,578 L164,578 "
              "C182,578 187,562 187,520 Z"),
    'HighTops': ("M78,506 C78,562 83,577 100,577 L113,577 C123,577 128,571 128,561 "
                 "L128,506 Z M136,506 L136,561 C136,571 141,577 151,577 L164,577 "
                 "C181,577 186,562 186,506 Z"),
    'WellyBoots': ("M76,500 C76,564 81,580 100,580 L115,580 C125,580 130,573 130,563 "
                   "L130,500 Z M134,500 L134,563 C134,573 139,580 149,580 L164,580 "
                   "C183,580 188,564 188,500 Z"),
    'Sandals': ("M82,556 L126,556 C128,556 129,558 129,562 C129,570 124,574 114,574 "
                "L94,574 C84,574 80,568 80,562 C80,558 80,556 82,556 Z "
                "M138,556 L182,556 C184,556 184,558 184,562 C184,568 180,574 170,574 "
                "L150,574 C140,574 135,570 135,562 C135,558 136,556 138,556 Z"),
}

NECK = {
    'Chain': "M110,268 C110,290 122,300 132,300 C142,300 154,290 154,268 L148,268 C148,286 140,294 132,294 C124,294 116,286 116,268 Z",
    'Pendant': "M112,268 C112,292 124,304 132,304 C140,304 152,292 152,268 L146,268 C146,288 139,298 132,298 C125,298 118,288 118,268 Z M126,300 L138,300 L132,316 Z",
    'Scarf': "M100,262 C100,286 112,296 132,296 C152,296 164,286 164,262 L164,282 C164,300 150,308 132,308 C114,308 100,300 100,282 Z",
}
WRIST = {
    'Bracelet': "M38,392 C38,404 46,410 58,410 C70,410 77,404 77,392 L77,402 C77,414 70,420 58,420 C46,420 38,414 38,402 Z M187,392 C187,404 194,410 206,410 C218,410 226,404 226,392 L226,402 C226,414 218,420 206,420 C194,420 187,414 187,402 Z",
    'Watch': "M40,388 L76,388 L76,404 L40,404 Z M188,388 L224,388 L224,404 L188,404 Z",
    'Sweatband': "M36,376 L78,376 L78,398 L36,398 Z M186,376 L228,376 L228,398 L186,398 Z",
}
WAIST = {
    'Belt': "M76,366 L188,366 L188,382 L76,382 Z",
    'ChunkyBelt': "M74,364 L190,364 L190,388 L74,388 Z",
}
HAIR_ACCESSORY = {
    'Headband': "M74,104 C74,80 96,62 132,62 C168,62 190,80 190,104 L190,118 C190,94 168,78 132,78 C96,78 74,94 74,118 Z",
    'Bow': "M150,66 C168,52 186,52 190,66 C194,80 178,88 158,82 Z M150,66 C150,58 158,54 164,58 C170,62 168,72 160,74 Z",
    'Clips': "M86,96 L104,86 L108,94 L90,104 Z M156,86 L174,96 L170,104 L152,94 Z",
}


_HEMS: Optional[Dict] = None
_HEMS_PATH = os.path.join(os.path.dirname(_PIECES_PATH), 'hems.json')

# Structured garments stop at the hip, like the real thing. Soft ones carry on
# down to the waist and let the bottoms take over.
STRUCTURED = {'BlazerShirt', 'BlazerSweater', 'Overall'}
HEM_STRUCTURED, HEM_SOFT = 344, 372


def _load() -> Dict:
    global _PIECES
    if _PIECES is None:
        try:
            with open(_PIECES_PATH, encoding='utf-8') as f:
                _PIECES = json.load(f).get('pieces') or {}
        except (OSError, ValueError):
            _PIECES = {}
    return _PIECES


def _hems() -> Dict:
    global _HEMS
    if _HEMS is None:
        try:
            with open(_HEMS_PATH, encoding='utf-8') as f:
                _HEMS = json.load(f).get('garments') or {}
        except (OSError, ValueError):
            _HEMS = {}
    return _HEMS


def available() -> bool:
    """False when the asset bundle has not been built. Callers fall back to
    the initial/emoji avatar rather than rendering an empty box."""
    return bool(_load())


def _color(kind: str, chosen) -> str:
    table, default = _PALETTES[kind]
    return table.get(chosen or '', table.get(default, '#000000'))


def _fill_through(mask_id: str, color: str) -> str:
    """Paint a flat colour through one of the source's masks -- the mechanism
    every Avataaars piece already uses for skin, hair and clothing."""
    rect = '<rect x="0" y="0" width="264" height="280"/>'
    if not mask_id:
        return f'<g fill="{color}">{rect}</g>'
    return f'<g mask="url(#{mask_id})" fill="{color}">{rect}</g>'


_TOKEN = re.compile(r'\{\{(FILL|SLOT):([a-z_]+):?([^:}]*):?([^}]*)\}\}')


def _expand(fragment: str, ns: str, cfg: Dict, depth: int = 0) -> str:
    """Substitute the id namespace, then the FILL and SLOT tokens.

    NS goes first so the nested `{{NS}}` inside a FILL token is already a real
    id by the time the token itself is parsed."""
    if not fragment:
        return ''
    out = fragment.replace('{{NS}}', ns)

    def sub(m):
        kind, name, a, b = m.groups()
        if kind == 'FILL':
            chosen = cfg.get(name) or (b or None)
            return _fill_through(a, _color(name, chosen))
        if depth > 3:            # a piece cannot contain itself forever
            return ''
        return _piece(name, cfg, ns, depth + 1)

    return _TOKEN.sub(sub, out)


def _piece(slot: str, cfg: Dict, ns: str, depth: int = 0) -> str:
    key = cfg.get(slot)
    if not key:
        return ''
    frag = (_load().get(slot) or {}).get(key)
    if frag is None:
        return ''
    return _expand(frag, f'{ns}{slot}_', cfg, depth)


def _shade(path: str, opacity: str = '0.1') -> str:
    return f'<path d="{path}" fill="{SHADE}" fill-opacity="{opacity}"/>'


def render_svg(config: Dict, crop: str = 'head', size: Optional[int] = None,
               nonce: str = 'a') -> str:
    """One member's look. `nonce` must differ between two avatars on the same
    page or their <mask> ids collide and one renders wrong -- the reason the
    original called uniqueId() at render time."""
    from services import avatar_catalog as cat
    cfg = dict(config or {})
    for slot in cat.conflicts(cfg):
        cfg.pop(slot, None)          # a bow cannot sit on a woolly hat
    ns = f'av{nonce}_'
    pieces = _load()
    if not pieces:
        return ''

    skin = _color('skin', cfg.get('skin'))
    clothe = _color('clothe_color', cfg.get('clothe_color'))
    full = crop == 'full'
    height = 600 if full else 280

    body_mask = f'{ns}bodymask'
    head = (
        f'<g id="{ns}body" transform="translate(32,36)">'
        f'<mask id="{body_mask}" fill="white"><use xlink:href="#{ns}bodypath"/></mask>'
        f'<use fill="{skin}" xlink:href="#{ns}bodypath"/>'
        f'<path d="{_NECK_SHADOW}" fill="{SHADE}" fill-opacity="0.1" '
        f'mask="url(#{body_mask})"/></g>'
    )

    lower = ''
    if full:
        bottoms = BOTTOMS.get(cfg.get('bottoms') or '')
        detail = BOTTOMS_DETAIL.get(cfg.get('bottoms') or '')
        shoes = SHOES.get(cfg.get('shoes') or '')
        parts = [
            f'<path d="{_ARM_L}" fill="{skin}"/><path d="{_ARM_R}" fill="{skin}"/>',
            f'<path d="{_LOWER}" fill="{skin}"/>',
            # A waistband that rises ABOVE the tops' hems. Without it a blazer
            # (which hems at the hip, correctly) left a band of bare midriff
            # between itself and the trousers. Real clothes overlap.
            (f'<path d="M78,336 L186,336 C187,352 187,360 186,372 L78,372 '
             f'C77,360 77,352 78,336 Z" '
             f'fill="{_color("bottoms_color", cfg.get("bottoms_color"))}"/>'
             f'<path d="{bottoms}" '
             f'fill="{_color("bottoms_color", cfg.get("bottoms_color"))}"/>')
            if bottoms else '',
            _shade(detail, '0.16') if detail else '',
            f'<path d="{shoes}" fill="{_color("shoes_color", cfg.get("shoes_color"))}"/>'
            if shoes else '',
        ]
        lower = ''.join(p for p in parts if p)

    # The garment continuation. Every source top ends flush on y=280, so the
    # bottom edge is a list of colour runs (baked by tools/bake_garment_hems.py)
    # and extruding them straight down is exact -- which is the only way a
    # blazer's lapels and its undershirt can carry on in the right colours.
    # The extrusion is then clipped to a tapered torso so the silhouette
    # narrows even though every run is vertical.
    torso_ext = ''
    if full:
        top_key = cfg.get('clothes') or ''
        hem = HEM_STRUCTURED if top_key in STRUCTURED else HEM_SOFT
        runs = _hems().get(top_key)
        clip = f'{ns}torsoclip'
        taper = (f'M76,280 L188,280 C188,310 186,{hem - 26} 184,{hem} '
                 f'L80,{hem} C78,{hem - 26} 76,310 76,280 Z')
        if runs:
            bars = ''.join(
                f'<rect x="{r["x"]}" y="280" width="{r["w"]}" height="{hem - 280}" '
                f'fill="{r["fill"] or clothe}"/>' for r in runs)
            torso_ext = (f'<clipPath id="{clip}"><path d="{taper}"/></clipPath>'
                         f'<g clip-path="url(#{clip})">{bars}</g>')
        else:
            torso_ext = f'<path d="{taper}" fill="{clothe}"/>'
        # A structured garment needs its cut edge to read, or it looks torn off.
        if top_key in STRUCTURED:
            torso_ext += _shade(f'M78,{hem - 8} L186,{hem - 8} L184,{hem} L80,{hem} Z', '0.16')
        # Sleeves take the garment's OUTERMOST colour, not the member's clothe
        # colour: a blazer's sleeve is jacket-coloured, and BlazerShirt does not
        # use the clothe colour at all.
        left = (runs[0].get('fill') or clothe) if runs else clothe
        right = (runs[-1].get('fill') or clothe) if runs else clothe
        torso_ext += (f'<path d="{_SLEEVE_L}" fill="{left}"/>'
                      f'<path d="{_SLEEVE_R}" fill="{right}"/>')

    accent = _color('accent_color', cfg.get('accent_color'))
    extras = ''
    if full:
        for slot, table in (('waist', WAIST), ('wrist', WRIST), ('neck', NECK)):
            d = table.get(cfg.get(slot) or '')
            if d:
                extras += f'<path d="{d}" fill="{accent}"/>'
    hair_extra = HAIR_ACCESSORY.get(cfg.get('hair_accessory') or '')

    face = (f'<g id="{ns}face" transform="translate(76,82)" fill="#000000">'
            f'{_piece("mouth", cfg, ns)}{_piece("nose", cfg, ns)}'
            f'{_piece("eyes", cfg, ns)}{_piece("eyebrow", cfg, ns)}</g>')

    hair_extra_svg = (f'<path d="{hair_extra}" fill="{accent}"/>' if hair_extra else '')
    dims = f'width="{size}" ' if size else ''
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" {dims}'
        f'viewBox="0 0 264 {height}" preserveAspectRatio="xMidYMax meet" '
        f'role="img" aria-label="avatar">'
        f'<defs><path d="{_BODY_PATH}" id="{ns}bodypath"/></defs>'
        f'<g fill="none" fill-rule="evenodd" stroke="none">'
        f'{lower}{head}{torso_ext}{_piece("clothes", cfg, ns)}{extras}'
        f'{face}{_piece("top", cfg, ns)}'
        f'{hair_extra_svg}'
        f'</g></svg>'
    )


def render_for_member(member_id: str, crop: str = 'head', **kw) -> str:
    from services import storage
    return render_svg(storage.get_avatar_config(member_id), crop, **kw)


# --- the effective chip image -------------------------------------------
# Every avatar surface in the app prefers `image` (a data-URL) over emoji over
# initials. So a character reaches all of them the same way a photo does: by
# BEING the image. The decision of what a member's chip shows lives here, once,
# server-side -- not in ten templates.
#
# avatar_kind: 'photo' | 'character' | 'emoji'. Unset means: photo if they
# have one, character otherwise. A family that set photos keeps them until
# someone explicitly opts that member in -- silent replacement is the one
# thing this function exists to prevent.

_EFFECTIVE_CACHE: Dict[str, tuple] = {}


def head_data_url(config: Dict) -> str:
    """The head crop as a data-URL an <img> can eat. Each <img> is its own
    document, so a fixed nonce cannot collide with anything."""
    import base64
    svg = render_svg(config, 'head', nonce='i')
    return 'data:image/svg+xml;base64,' + base64.b64encode(svg.encode('utf-8')).decode('ascii')


def effective_image(member: Dict) -> Optional[str]:
    """What this member's avatar chip should draw, or None for emoji/initials."""
    if not member:
        return None
    kind = member.get('avatar_kind') or ('photo' if member.get('image') else 'character')
    if kind == 'photo':
        return member.get('image')
    if kind == 'emoji':
        return None
    if not available():                     # art not built: degrade to photo
        return member.get('image')
    from services import storage
    mid = member.get('id')
    cfg = storage.get_avatar_config(mid)
    key = json.dumps(cfg, sort_keys=True)
    hit = _EFFECTIVE_CACHE.get(mid)
    if hit and hit[0] == key:
        return hit[1]
    url = head_data_url(cfg)
    _EFFECTIVE_CACHE[mid] = (key, url)
    return url


def bundle() -> Dict:
    """Everything a browser needs to composite locally.

    The editor renders a grid of ~37 thumbnails that each change as the member
    changes, which is far too chatty to ask the server for. So the browser gets
    the art once (80KB gzipped) and runs the same layer stack. Only the
    assembly loop is duplicated -- every path, palette and baked hem in here is
    served from this one source, so the two can never disagree about DATA."""
    from services import avatar_catalog as cat
    return {
        'pieces': _load(),
        'hems': _hems(),
        'palettes': {'skin': SKIN_COLORS, 'hair_color': HAIR_COLORS,
                     'clothe_color': CLOTHE_COLORS, 'hat_color': HAT_COLORS,
                     'bottoms_color': CLOTHE_COLORS, 'shoes_color': CLOTHE_COLORS,
                     'accent_color': CLOTHE_COLORS},
        'defaults': {k: v[1] for k, v in _PALETTES.items()},
        'rig': {'armL': _ARM_L, 'armR': _ARM_R, 'sleeveL': _SLEEVE_L,
                'sleeveR': _SLEEVE_R, 'lower': _LOWER, 'body': _BODY_PATH,
                'neckShadow': _NECK_SHADOW, 'shade': SHADE},
        'tables': {'bottoms': BOTTOMS, 'bottomsDetail': BOTTOMS_DETAIL,
                   'shoes': SHOES, 'neck': NECK, 'wrist': WRIST,
                   'waist': WAIST, 'hair_accessory': HAIR_ACCESSORY},
        'hems_meta': {'structured': sorted(STRUCTURED),
                      'hemStructured': HEM_STRUCTURED, 'hemSoft': HEM_SOFT},
        'slots': cat.get_slots(), 'groups': cat.GROUPS,
        'palette_slots': cat.PALETTES,
    }

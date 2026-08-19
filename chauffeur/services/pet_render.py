"""Compose one pet's look into an SVG string.

Server-side for the same reason `avatar_render` is: kiosk boards, digests and
the wall panel all need to draw a critter without a live JS runtime, and a
Home Assistant add-on must not depend on reaching api.dicebear.com to show a
kid their pet. The art is baked into `static/pets/pieces.json` by
`tools/harvest_critters.py`; see that file for what the bake had to fix.

ONE CANVAS, not two. Avatars needed a head crop and a full-body crop because
the rig was a bust that we extended downward. Critters were drawn as a single
100x100 square where the body runs off the bottom edge on purpose -- that edge
IS the ground line the creature stands on. `crop` therefore selects behaviour,
not geometry: 'chip' is a static critter for a list or a card, 'battle' is the
same art with the idle-motion hooks left live for the overlay's CSS.

Two colour slots and no more: BASE paints the body, ACCENT paints whatever
grows out of its head. Everything else is ink, a white/slate shading overlay,
or the pink inside of a mouth -- all literal, because the implied light and a
pink tongue must survive recolouring.

Layer order comes from the bake (`order`), because where the belly pattern
sits relative to the face is upstream's decision, not ours.
"""
import json
import os
import re
from typing import Dict, List, Optional

_PIECES: Optional[Dict] = None
_PIECES_PATH = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'static', 'pets', 'pieces.json')

# The 300-level Tailwind pastels critters ships in. Both slots draw from the
# same table: a lilac body with mint horns is a legitimate critter, and
# splitting the palettes would only remove combinations for no reason.
BASE_COLORS = {
    'Amber': '#fcd34d', 'Apricot': '#fdba74', 'Rose': '#fda4af',
    'Blossom': '#f0abfc', 'Lilac': '#c4b5fd', 'Periwinkle': '#a5b4fc',
    'Sky': '#7dd3fc', 'Teal': '#5eead4', 'Mint': '#6ee7b9',
    'Lime': '#bef264', 'Coral': '#fca5a5', 'Stone': '#e2e8f0',
}
ACCENT_COLORS = BASE_COLORS

DEFAULTS = {
    'body': 'blob', 'top': 'nub', 'eyes': 'round', 'mouth': 'smile',
    'pattern': None, 'cheeks': None,
    'base_color': 'Sky', 'accent_color': 'Rose',
}

_SLOT_TOKENS = re.compile(r'\{\{(NS|BASE|ACCENT|TOP)\}\}')


def _load() -> Dict:
    global _PIECES
    if _PIECES is None:
        try:
            with open(_PIECES_PATH, encoding='utf-8') as f:
                _PIECES = json.load(f)
        except (OSError, ValueError):
            _PIECES = {}
    return _PIECES


def available() -> bool:
    """False when the bake has not been run. Callers fall back to an emoji
    rather than rendering an empty box."""
    return bool(_load().get('pieces'))


def parts(slot: str) -> List[str]:
    return sorted((_load().get('pieces') or {}).get(slot) or {})


def species_count() -> int:
    """body x top -- the axis a kid reads as 'what kind of creature is it'."""
    return len(parts('body')) * len(parts('top'))


def _color(table: Dict[str, str], chosen, fallback: str) -> str:
    """A palette name, a literal hex, or the default. Accepting hex keeps the
    door open for a granted one-off colour without inventing a name for it."""
    if isinstance(chosen, str):
        if chosen in table:
            return table[chosen]
        if re.fullmatch(r'#[0-9a-fA-F]{6}', chosen):
            return chosen
    return table.get(fallback, '#7dd3fc')


def _frag(slot: str, key, cfg: Dict, ns: str) -> str:
    if not key:
        return ''
    raw = ((_load().get('pieces') or {}).get(slot) or {}).get(key)
    if raw is None:
        return ''
    return _expand(raw, cfg, ns)


def _expand(raw: str, cfg: Dict, ns: str) -> str:
    base = _color(BASE_COLORS, cfg.get('base_color'), DEFAULTS['base_color'])
    accent = _color(ACCENT_COLORS, cfg.get('accent_color'), DEFAULTS['accent_color'])

    def sub(m):
        tok = m.group(1)
        if tok == 'NS':
            return ns
        if tok == 'BASE':
            return base
        if tok == 'ACCENT':
            return accent
        # {{TOP}} only ever appears inside a body, and a top never contains a
        # body, so this cannot recurse.
        return _frag('top', cfg.get('top') or DEFAULTS['top'], cfg, ns)

    return _SLOT_TOKENS.sub(sub, raw)


def render_svg(config: Optional[Dict], crop: str = 'chip',
               size: Optional[int] = None, nonce: str = 'a') -> str:
    """One pet's look.

    `nonce` MUST differ between two critters on the same page. Upstream left
    its clipPath ids unhashed (`dbcrb-tower`), the bake rewrote them as
    `{{NS}}c-tower`, and this is where that namespace actually gets its value.
    Two `tower` critters sharing a nonce is the exact collision the bake
    exists to prevent -- the battle overlay draws two pets side by side, so
    it passes 'a' and 'b'.
    """
    if not available():
        return ''
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in (config or {}).items() if v is not None})
    data = _load()
    ns = 'p%s' % re.sub(r'[^A-Za-z0-9_-]', '', str(nonce))[:12] or 'pa'
    vb = data.get('view') or [0, 0, 100, 100]
    anchors = data.get('anchors') or {}
    order = data.get('order') or ['body', 'pattern', 'cheeks', 'eyes', 'mouth']

    layers = []
    for slot in order:
        frag = _frag(slot, cfg.get(slot), cfg, ns)
        if not frag:
            continue
        at = anchors.get(slot)
        if at:
            layers.append('<g transform="translate(%s %s)">%s</g>'
                          % (_num(at[0]), _num(at[1]), frag))
        else:
            layers.append(frag)

    dim = ''
    if size:
        dim = ' width="%d" height="%d"' % (size, size)
    # The body deliberately overruns the canvas -- clipping it at the bottom
    # edge is what makes the critter stand on the ground rather than float.
    body = ('<clipPath id="%(ns)sclip"><rect x="%(x)s" y="%(y)s" '
            'width="%(w)s" height="%(h)s"/></clipPath>'
            '<g clip-path="url(#%(ns)sclip)" class="dbcr-c">%(art)s</g>') % {
        'ns': ns, 'x': _num(vb[0]), 'y': _num(vb[1]),
        'w': _num(vb[2]), 'h': _num(vb[3]), 'art': ''.join(layers)}
    # `critter`, not `pet` -- the root class lands in whatever page embeds
    # this, and `.pet` is exactly the selector a board or an overlay would
    # reach for on its own wrapper. A collision here silently repositions
    # every critter on the page.
    cls = 'critter critter-battle' if crop == 'battle' else 'critter critter-chip'
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="%s %s %s %s"%s '
            'fill="none" shape-rendering="auto" class="%s" role="img" '
            'aria-label="%s">%s</svg>'
            % (_num(vb[0]), _num(vb[1]), _num(vb[2]), _num(vb[3]), dim, cls,
               describe(cfg), body))


def _num(v) -> str:
    f = float(v)
    return str(int(f)) if f == int(f) else str(f)


def describe(config: Optional[Dict]) -> str:
    """A short label for alt text. Not a name -- the kid names the pet."""
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in (config or {}).items() if v is not None})
    top = _CAMEL.sub(r'\1 \2', str(cfg.get('top') or '')).lower()
    return ('a %s %s critter with %s'
            % (str(cfg.get('base_color') or '').lower(),
               str(cfg.get('body') or ''), top or 'no headgear'))


_CAMEL = re.compile(r'([a-z])([A-Z])')


def data_url(config: Optional[Dict], size: Optional[int] = None,
             nonce: str = 'a') -> str:
    """For an <img src> or a CSS background. Digests and email have no other
    way in."""
    import base64
    svg = render_svg(config, size=size, nonce=nonce)
    if not svg:
        return ''
    return ('data:image/svg+xml;base64,'
            + base64.b64encode(svg.encode('utf-8')).decode('ascii'))


def bundle() -> Dict:
    """Everything the editor needs to draw its choices, in one payload."""
    return {
        'slots': {s: parts(s) for s in
                  ('body', 'top', 'eyes', 'mouth', 'pattern', 'cheeks')},
        'colors': BASE_COLORS,
        'defaults': DEFAULTS,
        'species': species_count(),
        'art': _load().get('_art', ''),
        'licence': _load().get('_licence', ''),
    }

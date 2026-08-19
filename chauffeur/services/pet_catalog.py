"""What a pet can BE, as data.

The art catalogue lives in `pet_render` (it is whatever the bake produced).
This is the game side: the five elements and how they beat each other.

FIVE TYPES IN A RING, not eighteen in a table. Each element is strong against
the next and weak against the previous, which makes the whole chart provably
balanced -- no type is better than any other, so a child picking the one they
think looks coolest can never be picking wrong. It also fits in a head:

    Ember burns Leaf -> Leaf splits Stone -> Stone grounds Spark
        -> Spark boils Tide -> Tide quenches Ember -> (Ember)

No immunities. A move that does nothing is not a strategy, it is a wasted turn
and a bored kid.

Moves, NPCs and the rest of the battle catalogue arrive with the resolver in
P3; the ring is here now because P1 has to validate a chosen type and the ring
IS the definition of a type.
"""
from typing import Dict, List, Optional

# Ordered. Each entry beats the one after it, and the last beats the first --
# the order is the rule, so the ring cannot drift out of sync with a table.
TYPES: List[Dict] = [
    {'key': 'ember', 'label': 'Ember', 'glyph': '\U0001F525', 'color': '#fb7185',
     'verb': 'burns'},
    {'key': 'leaf', 'label': 'Leaf', 'glyph': '\U0001F343', 'color': '#bef264',
     'verb': 'splits'},
    {'key': 'stone', 'label': 'Stone', 'glyph': '\U0001FAA8', 'color': '#e2e8f0',
     'verb': 'grounds'},
    {'key': 'spark', 'label': 'Spark', 'glyph': '⚡', 'color': '#fcd34d',
     'verb': 'boils'},
    {'key': 'tide', 'label': 'Tide', 'glyph': '\U0001F30A', 'color': '#7dd3fc',
     'verb': 'quenches'},
]

_ORDER = [t['key'] for t in TYPES]
_BY_KEY = {t['key']: t for t in TYPES}

SUPER = 1.6
RESIST = 0.625          # 1/1.6, so a ring lap multiplies out to exactly 1
DEFAULT = _ORDER[0]


def keys() -> List[str]:
    return list(_ORDER)


def get(key: Optional[str]) -> Optional[Dict]:
    return _BY_KEY.get(key or '')


def valid(key: Optional[str]) -> bool:
    return (key or '') in _BY_KEY


def coerce(key: Optional[str]) -> str:
    """A type is never blank and never invalid -- a pet without an element
    could not be put in a fight."""
    return key if valid(key) else DEFAULT


def beats(attacker: str, defender: str) -> bool:
    if not (valid(attacker) and valid(defender)):
        return False
    return _ORDER[(_ORDER.index(attacker) + 1) % len(_ORDER)] == defender


def multiplier(attacker: str, defender: str) -> float:
    """1.6 forward round the ring, 0.625 backward, 1.0 otherwise."""
    if not (valid(attacker) and valid(defender)):
        return 1.0
    if beats(attacker, defender):
        return SUPER
    if beats(defender, attacker):
        return RESIST
    return 1.0


def matchup_text(attacker: str, defender: str) -> str:
    """For a kid reading the battle log, and for the editor's 'strong against'
    line. Says what happened in words a seven-year-old already owns."""
    a, d = get(attacker), get(defender)
    if not (a and d):
        return ''
    if beats(attacker, defender):
        return "%s %s %s -- super effective!" % (a['label'], a['verb'], d['label'])
    if beats(defender, attacker):
        return "%s %s %s -- not very effective." % (d['label'], d['verb'], a['label'])
    return ''


# --- levels ---------------------------------------------------------------
# XP IS THE MEMBER'S, AND EVERY PET THEY OWN SHARES THE LEVEL IT BUYS.
#
# The alternative -- xp banked per creature -- splits a child's effort the
# moment they own two, so the second pet arrives useless and the first one
# they liked stops growing. Sharing means a new critter is instantly as strong
# as the one beside it, which is the answer to "which one do I feed": neither,
# you feed yourself. Training points are still spent PER PET (P5), so the
# choice that matters is where the effort goes, not which animal receives it.
#
# Quadratic, so the early levels come fast and the later ones mean something:
# 20 xp to reach L2, 320 to reach L5, 1620 to reach L10. At roughly 25-80 xp a
# day from chores and routines, that is a level on day one and L10 in about a
# month -- fast enough to feel earned, slow enough to still be climbing.
LEVEL_STEP = 20
LEVEL_MAX = 50


def xp_for_level(level: int) -> int:
    """Lifetime xp needed to REACH this level. Level 1 is free."""
    level = max(1, min(int(level or 1), LEVEL_MAX))
    return LEVEL_STEP * (level - 1) ** 2


def level_for_xp(xp: int) -> int:
    xp = max(0, int(xp or 0))
    level = int((xp / LEVEL_STEP) ** 0.5) + 1
    # integer-sqrt drift at the boundaries, fixed by stepping rather than by
    # trusting a float
    while level < LEVEL_MAX and xp_for_level(level + 1) <= xp:
        level += 1
    while level > 1 and xp_for_level(level) > xp:
        level -= 1
    return min(level, LEVEL_MAX)


def level_progress(xp: int) -> Dict:
    """{level, xp, into, need, next_at, ratio} -- everything a progress bar
    needs, so no surface has to do this arithmetic itself and get it slightly
    different from the one beside it."""
    xp = max(0, int(xp or 0))
    level = level_for_xp(xp)
    at = xp_for_level(level)
    if level >= LEVEL_MAX:
        return {'level': level, 'xp': xp, 'into': 0, 'need': 0,
                'next_at': None, 'ratio': 1.0, 'max': True}
    nxt = xp_for_level(level + 1)
    span = max(1, nxt - at)
    return {'level': level, 'xp': xp, 'into': xp - at, 'need': nxt - xp,
            'next_at': nxt, 'ratio': round((xp - at) / span, 4), 'max': False}


def bundle() -> Dict:
    """What the editor needs to draw the type picker, including who each
    element beats so the picker can SHOW the ring rather than describe it."""
    return {'types': [dict(t, beats=_ORDER[(i + 1) % len(_ORDER)],
                           loses_to=_ORDER[(i - 1) % len(_ORDER)])
                      for i, t in enumerate(TYPES)],
            'super': SUPER, 'resist': RESIST, 'default': DEFAULT,
            'level_max': LEVEL_MAX, 'level_step': LEVEL_STEP}

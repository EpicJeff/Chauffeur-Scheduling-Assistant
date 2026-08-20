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
import json
import os
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


# --- the game catalogue: bodies, moves, opponents --------------------------
# Data, not code. Adding an NPC or a move is a JSON edit; the only thing this
# module supplies is the reading of it and the rules that must hold over it.

_CATALOG: Optional[Dict] = None
_CATALOG_PATH = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'static', 'pets', 'catalog.json')

# Every stat a pet has. HP is separate from the rest in the formulas, but not
# in the table -- a body's shape is all six numbers together.
STATS = ('hp', 'atk', 'def', 'spa', 'spd', 'spe')
STAT_LABELS = {'hp': 'HP', 'atk': 'Attack', 'def': 'Defense',
               'spa': 'Sp. Atk', 'spd': 'Sp. Def', 'spe': 'Speed'}

# The fallback shape, used when a body is unknown. Deliberately the flat
# average rather than anything interesting: an unrecognised body should be
# unremarkable, never accidentally the best one in the game.
_NEUTRAL = {'hp': 50, 'atk': 50, 'def': 50, 'spa': 50, 'spd': 50, 'spe': 50}


def _catalog() -> Dict:
    global _CATALOG
    if _CATALOG is None:
        try:
            with open(_CATALOG_PATH, encoding='utf-8') as f:
                _CATALOG = json.load(f)
        except (OSError, ValueError):
            _CATALOG = {}
    return _CATALOG


def base_stats(body: Optional[str]) -> Dict[str, int]:
    """What a body is GOOD at.

    Every body sums to the same total (`_stat_total` in the catalogue), so the
    14 silhouettes differ in shape and never in strength. That is rule 1 held
    at the stat table: a child who picks the cute body must not discover they
    picked the weak one."""
    row = (_catalog().get('bodies') or {}).get(body or '')
    if not row:
        return dict(_NEUTRAL)
    return {s: int(row.get(s, _NEUTRAL[s])) for s in STATS}


def stat_total() -> int:
    return int(_catalog().get('_stat_total') or sum(_NEUTRAL.values()))


def moves() -> List[Dict]:
    return list(_catalog().get('moves') or [])


def move(key: Optional[str]) -> Optional[Dict]:
    for m in moves():
        if m['key'] == key:
            return m
    return None


def moves_for_type(type_key: str) -> List[Dict]:
    return [m for m in moves() if m.get('type') == type_key]


def default_moves(type_key: str) -> List[str]:
    """The four a critter knows before anybody teaches it anything.

    Move CHOICE is a P5 sink; until then every pet walks in with its own
    element's full kit, so a battle is playable the moment the resolver
    exists. Also the floor afterwards: a pet must never arrive at a fight with
    nothing to do."""
    return [m['key'] for m in moves_for_type(coerce(type_key))][:4]


def npcs() -> List[Dict]:
    return sorted((_catalog().get('npcs') or []), key=lambda n: n.get('tier', 0))


def npc(key: Optional[str]) -> Optional[Dict]:
    if str(key or '').startswith('gen:'):
        return _gen_npc_from_key(key)
    for n in npcs():
        if n['key'] == key:
            return n
    return None


# --- generated opponents ----------------------------------------------------
# The ladder used to be the same six critters forever; now each rung is
# occupied by a GENERATED one — name, element, body, look and taunt all rolled
# fresh per roster fetch. The whole identity derives deterministically from
# the key ('gen:<tier>:<seed8hex>'), so an opponent handed to a client always
# resolves at battle time with no server state, and the tier spec (level, xp)
# stays fixed so the ladder itself never moves. Pools live in the catalogue's
# npc_gen section: adding a name or a taunt is still a JSON edit.

def _gen_spec() -> Dict:
    return _catalog().get('npc_gen') or {}


def _gen_npc_from_key(key: str) -> Optional[Dict]:
    try:
        _, tier_s, seed_s = str(key).split(':', 2)
        return gen_npc(int(tier_s), int(seed_s, 16))
    except (ValueError, AttributeError):
        return None


def gen_npc(tier: int, seed: int) -> Optional[Dict]:
    """One generated opponent, whole and reproducible from (tier, seed)."""
    import random
    from services import pet_render
    spec = _gen_spec()
    t_row = next((t for t in (spec.get('tiers') or [])
                  if int(t.get('tier', -1)) == int(tier)), None)
    if not t_row:
        return None
    rng = random.Random((int(tier) << 32) ^ (int(seed) & 0xffffffff))
    type_key = rng.choice(keys())
    names = (spec.get('names') or {}).get(type_key) or ['Rival']
    name = rng.choice(names)
    bodies = sorted((_catalog().get('bodies') or {'blob': {}}).keys())
    taunts = (spec.get('taunts') or {}).get(type_key) or ['{name} is waiting.']

    def part(slot, fallback, allow_none=False):
        pool = list(pet_render.parts(slot) or [fallback])
        if allow_none:
            pool = [None] + pool
        return rng.choice(pool)

    colors = sorted(pet_render.BASE_COLORS.keys()) or ['Sky']
    return {
        'key': 'gen:%d:%08x' % (int(tier), int(seed) & 0xffffffff),
        'name': name, 'tier': int(tier),
        'level': int(t_row['level']), 'xp': int(t_row['xp']),
        'type': type_key,
        'species': {'body': rng.choice(bodies), 'top': part('top', 'nub')},
        'look': {'eyes': part('eyes', 'round'), 'mouth': part('mouth', 'smile'),
                 'pattern': part('pattern', None, allow_none=True),
                 'base_color': rng.choice(colors),
                 'accent_color': rng.choice(colors)},
        'taunt': rng.choice(taunts).replace('{name}', name),
    }


def gen_roster() -> List[Dict]:
    """A fresh opponent per rung of the ladder, rolled now.

    Rejection-sampled lightly so a roster usually shows the full elemental
    spread (the ring is easier to learn when you can see it) and never two
    rungs wearing the same name. Falls back to the classic six when the
    catalogue has no npc_gen section — an old catalog file must not empty
    the arena."""
    import os as _os
    spec_tiers = sorted(int(t['tier']) for t in (_gen_spec().get('tiers') or []))
    if not spec_tiers:
        return npcs()
    roster, seen_types, seen_names = [], set(), set()
    for tier in spec_tiers:
        pick = None
        for _ in range(12):
            cand = gen_npc(tier, int.from_bytes(_os.urandom(4), 'big'))
            if cand is None:
                break
            if pick is None:
                pick = cand
            fresh_type = (cand['type'] not in seen_types
                          or len(seen_types) >= len(keys()))
            if fresh_type and cand['name'] not in seen_names:
                pick = cand
                break
        if pick:
            roster.append(pick)
            seen_types.add(pick['type'])
            seen_names.add(pick['name'])
    return roster or npcs()


def bundle() -> Dict:
    """What the editor needs to draw the type picker, including who each
    element beats so the picker can SHOW the ring rather than describe it."""
    return {'types': [dict(t, beats=_ORDER[(i + 1) % len(_ORDER)],
                           loses_to=_ORDER[(i - 1) % len(_ORDER)])
                      for i, t in enumerate(TYPES)],
            'super': SUPER, 'resist': RESIST, 'default': DEFAULT,
            'level_max': LEVEL_MAX, 'level_step': LEVEL_STEP,
            'stats': list(STATS), 'stat_labels': STAT_LABELS,
            'moves': moves(), 'bodies': (_catalog().get('bodies') or {}),
            'stat_total': stat_total()}

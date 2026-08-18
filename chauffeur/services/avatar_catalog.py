"""The avatar wardrobe: what slots exist, what goes in them, and what each
piece costs.

Two rules govern everything in this file, and both are load-bearing:

  1. IDENTITY IS FREE, FLEX IS EARNED. Anything a person uses to say "this is
     me" -- body, skin, hair, face, facial hair, glasses, and the cultural or
     medical pieces (hijab, turban, eyepatch) -- is `free` and unlocked from
     first login. Only decoration is `unlock`. Gating a child's own likeness
     behind chore compliance is a grade, and `due dates never grades` is
     locked.

  2. SLOTS ARE EXPENSIVE, ITEMS ARE CHEAP. A slot costs a registration
     decision and a z-order position, paid once and forever. An item inside an
     existing slot is a dozen SVG path commands. So the slot list below is
     meant to be argued over; the item lists are meant to grow without anyone
     re-opening this docstring.

Everything here is DATA. Adding wardrobe is adding rows, never code.
"""
from typing import Dict, List, Optional

# --- Slots ---------------------------------------------------------------
# `z` is paint order, low first. The rig itself (arms, lower body, head) is
# not a slot -- it is always drawn, and it sits below everything here.
#
# Two z-order constraints that are not obvious:
#   - `waist` paints ABOVE `clothes`. A belt sits at the trouser waistband
#     (y~370) and the soft-top hem falls at y=372, so a belt painted under the
#     top would be invisible on every soft top.
#   - `hair_accessory` paints ABOVE `top`, because `top` holds hair AND hats in
#     one slot (that is how the source models it). A bow over a hat is wrong,
#     so hair accessories declare a conflict with the headwear items instead.

# `focus` is the viewBox a THUMBNAIL of this slot uses. It is not decoration:
# a shoe inside a full-body thumbnail is about six pixels, and a grid of 37
# identical tiny people is not a visual library. Each slot frames the thing
# being chosen. The editor's users cannot be assumed to read, so the picture
# has to carry the whole message.
HEAD = '0 0 264 300'
TORSO = '0 150 264 260'
HIPS = '0 320 264 200'
FEET = '0 470 264 140'
ARMS = '0 330 264 140'
WAISTLINE = '0 300 264 130'

# `palettes` is the colour (or colours) that belong to THIS slot, and the
# editor draws them as a swatch strip above the slot's own grid. It exists
# because a colour is not a sibling of the thing it colours: "Belt" and "Belt
# colour" as two chips in a row of ten is a menu, whereas choosing the belt and
# then its colour in one place is dressing.
#
# It is also what makes one-colour-per-thing affordable. Every piece that can
# take a colour has its own now -- a beard is not a t-shirt, a watch is not a
# belt -- and as separate TABS that would have been sixteen chips across four
# groups. `top` carries two, because hair and hats share the slot.
SLOTS = [
    {'key': 'bottoms',        'label': 'Bottoms',    'z': 10, 'required': True,  'focus': HIPS,
     'palettes': ['bottoms_color']},
    {'key': 'shoes',          'label': 'Shoes',      'z': 20, 'required': True,  'focus': FEET,
     'palettes': ['shoes_color']},
    {'key': 'clothes',        'label': 'Top',        'z': 30, 'required': True,  'focus': TORSO,
     'palettes': ['clothe_color']},
    {'key': 'graphic',        'label': 'Graphic',    'z': 35, 'required': False, 'focus': TORSO,
     'only_with': ('clothes', 'GraphicShirt'), 'palettes': ['graphic_color']},
    {'key': 'waist',          'label': 'Belt',       'z': 40, 'required': False, 'focus': WAISTLINE,
     'palettes': ['waist_color']},
    {'key': 'wrist',          'label': 'Wrist',      'z': 45, 'required': False, 'focus': ARMS,
     'palettes': ['wrist_color']},
    {'key': 'neck',           'label': 'Neck',       'z': 50, 'required': False, 'focus': TORSO,
     'palettes': ['neck_color']},
    {'key': 'facial_hair',    'label': 'Facial hair','z': 55, 'required': False, 'focus': HEAD,
     'palettes': ['facial_hair_color']},
    {'key': 'top',            'label': 'Hair & hats','z': 60, 'required': True,  'focus': HEAD,
     'palettes': ['hair_color', 'hat_color']},
    {'key': 'hair_accessory', 'label': 'Hair extra', 'z': 65, 'required': False, 'focus': HEAD,
     'palettes': ['hair_accessory_color']},
    {'key': 'eyewear',        'label': 'Glasses',    'z': 70, 'required': False, 'focus': HEAD,
     'palettes': ['eyewear_color']},
    # Face parts are not unlockable -- they are identity, always free, and they
    # live in the catalog only so the editor can offer them.
    {'key': 'eyes',           'label': 'Eyes',       'z': 52, 'required': True,  'focus': HEAD,
     'palettes': ['eye_color']},
    {'key': 'eyebrow',        'label': 'Eyebrows',   'z': 53, 'required': True,  'focus': HEAD,
     'palettes': ['eyebrow_color']},
    # No mouth colour. A mouth is not one shape in one colour -- lips, teeth and
    # a tongue are three, and a single swatch over all of them paints the smile
    # shut. The day somebody wants lipstick it is a `TINTS` entry naming the lip
    # hex, not a group fill.
    {'key': 'mouth',          'label': 'Mouth',      'z': 51, 'required': True,  'focus': HEAD},
    {'key': 'nose',           'label': 'Nose',       'z': 54, 'required': True,  'focus': HEAD},
]

# Every palette there is, with the word for it. Two jobs: it labels the swatch
# strip a slot draws (see `palettes` above), and the ones named in a GROUP's
# tabs get a tab of their own -- which is only the two belonging to no single
# slot. Skin is the whole figure; the accent is what the four accessories
# inherit when they have no colour of their own, so it stays the one dial that
# moves all of them at once.
PALETTES = [
    {'key': 'skin',                 'label': 'Skin'},
    {'key': 'accent_color',         'label': 'Accent'},
    {'key': 'hair_color',           'label': 'Hair colour'},
    {'key': 'hat_color',            'label': 'Hat colour'},
    {'key': 'facial_hair_color',    'label': 'Beard colour'},
    {'key': 'eyebrow_color',        'label': 'Eyebrow colour'},
    {'key': 'eye_color',            'label': 'Eye colour'},
    {'key': 'eyewear_color',        'label': 'Frame colour'},
    {'key': 'clothe_color',         'label': 'Top colour'},
    {'key': 'graphic_color',        'label': 'Graphic colour'},
    {'key': 'bottoms_color',        'label': 'Bottoms colour'},
    {'key': 'shoes_color',          'label': 'Shoe colour'},
    {'key': 'neck_color',           'label': 'Neck colour'},
    {'key': 'wrist_color',          'label': 'Wrist colour'},
    {'key': 'waist_color',          'label': 'Belt colour'},
    {'key': 'hair_accessory_color', 'label': 'Hair extra colour'},
]

# Two tiers, because eleven slots in one strip is unusable and the reference
# layouts all solve it this way. Glyphs lead: the word is for whoever can read
# it, the picture is for everyone else (same compromise as kid_glyphs.html).
# The colour tabs that used to sit beside their slot are GONE from these lists
# -- the tabs, not the colours. Each moved onto the slot it belongs to as a
# swatch strip, which is what made room for one colour per thing without the
# chip rows growing to sixteen. `skin` and `accent_color` keep their tabs
# because neither belongs to a single slot.
GROUPS = [
    {'key': 'me',      'label': 'Me',      'glyph': '🧑',
     'tabs': ['skin', 'eyes', 'eyebrow', 'mouth', 'nose']},
    {'key': 'hair',    'label': 'Hair',    'glyph': '💇',
     'tabs': ['top', 'facial_hair', 'hair_accessory']},
    {'key': 'clothes', 'label': 'Clothes', 'glyph': '👕',
     'tabs': ['clothes', 'graphic', 'bottoms', 'shoes']},
    {'key': 'extras',  'label': 'Extras',  'glyph': '🕶️',
     'tabs': ['eyewear', 'neck', 'wrist', 'waist', 'accent_color']},
]

# Headwear lives in `top` alongside hair; a hair accessory cannot sit on it.
HEADWEAR = ('Hat', 'Hijab', 'Turban', 'WinterHat1', 'WinterHat2',
            'WinterHat3', 'WinterHat4')

# Tracks an unlockable can hang off. All three counters are monotonic and
# persisted -- see storage.compute_streak / get_points_earned /
# count_routine_completions. Never gate on anything re-derived from history.
TRACK_ROUTINE = 'routine_cumulative'   # total routine completions, ever
TRACK_STREAK = 'routine_streak'        # best routine streak, ever
TRACK_POINTS = 'chore_points'          # lifetime chore points earned


def _free(slot: str, keys, label=None) -> List[Dict]:
    return [{'key': k, 'slot': slot, 'label': label(k) if label else _humanise(k),
             'tier': 'free'} for k in keys]


def _unlock(slot: str, spec) -> List[Dict]:
    """spec: [(key, track, threshold), ...]"""
    return [{'key': k, 'slot': slot, 'label': _humanise(k), 'tier': 'unlock',
             'track': t, 'threshold': n} for k, t, n in spec]


def _humanise(key: str) -> str:
    import re
    s = re.sub(r'(?<!^)(?=[A-Z])', ' ', key).replace('_', ' ')
    return re.sub(r'\s+', ' ', s).strip().replace('0 1', ' 1').title()


# --- Inherited from the source art (all free: hair and faces are identity) --

_HAIR = [
    'NoHair', 'LongHairBigHair', 'LongHairBob', 'LongHairBun', 'LongHairCurly',
    'LongHairCurvy', 'LongHairDreads', 'LongHairFrida', 'LongHairFro',
    'LongHairFroBand', 'LongHairMiaWallace', 'LongHairNotTooLong',
    'LongHairShavedSides', 'LongHairStraight', 'LongHairStraight2',
    'LongHairStraightStrand', 'ShortHairDreads01', 'ShortHairDreads02',
    'ShortHairFrizzle', 'ShortHairShaggy', 'ShortHairShaggyMullet',
    'ShortHairShortCurly', 'ShortHairShortFlat', 'ShortHairShortRound',
    'ShortHairShortWaved', 'ShortHairSides', 'ShortHairTheCaesar',
    'ShortHairTheCaesarSidePart',
]
# Cultural and medical pieces are identity, not decoration. Free, always.
_IDENTITY_HEADWEAR = ['Hijab', 'Turban', 'Eyepatch']

_FACIAL_HAIR = ['Blank', 'BeardLight', 'BeardMajestic', 'BeardMedium',
                'MoustacheFancy', 'MoustacheMagnum']

# You either wear glasses or you do not. That is not a reward.
_EYEWEAR = ['Blank', 'Kurt', 'Prescription01', 'Prescription02', 'Round',
            'Sunglasses', 'Wayfarers']

_GRAPHICS = ['Skull', 'SkullOutline', 'Bat', 'Cumbia', 'Deer', 'Diamond',
             'Hola', 'Selena', 'Pizza', 'Resist', 'Bear']


# A face is not a reward. Every expression, always.
_EYES = ['Default', 'Happy', 'Wink', 'WinkWacky', 'Squint', 'Surprised', 'Side',
         'Close', 'EyeRoll', 'Hearts', 'Dizzy', 'Cry']
_EYEBROW = ['Default', 'DefaultNatural', 'RaisedExcited', 'RaisedExcitedNatural',
            'FlatNatural', 'UpDown', 'UpDownNatural', 'Angry', 'AngryNatural',
            'SadConcerned', 'SadConcernedNatural', 'FrownNatural', 'UnibrowNatural']
_MOUTH = ['Default', 'Smile', 'Twinkle', 'Serious', 'Tongue', 'Eating',
          'Grimace', 'Concerned', 'Disbelief', 'Sad', 'ScreamOpen', 'Vomit']

ITEMS: List[Dict] = (
    _free('eyes', _EYES)
    + _free('eyebrow', _EYEBROW)
    + _free('mouth', _MOUTH)
    + _free('nose', ['Default'])
    + _free('top', _HAIR + _IDENTITY_HEADWEAR)
    + _unlock('top', [
        ('Hat',        TRACK_ROUTINE, 20),
        ('WinterHat1', TRACK_ROUTINE, 60),
        ('WinterHat2', TRACK_ROUTINE, 110),
        ('WinterHat3', TRACK_STREAK,  14),
        ('WinterHat4', TRACK_STREAK,  30),
    ])
    + _free('facial_hair', _FACIAL_HAIR)
    + _free('eyewear', _EYEWEAR)
    # Everyone starts dressed: three plain tops, plain trousers, plain shoes.
    + _free('clothes', ['ShirtCrewNeck', 'ShirtScoopNeck', 'ShirtVNeck'])
    + _unlock('clothes', [
        ('Hoodie',        TRACK_ROUTINE, 15),
        ('CollarSweater', TRACK_ROUTINE, 45),
        ('GraphicShirt',  TRACK_ROUTINE, 75),
        ('Overall',       TRACK_POINTS,  50),
        ('BlazerShirt',   TRACK_POINTS,  150),
        ('BlazerSweater', TRACK_STREAK,  21),
        # the first FULL top (whole garment, no source bust underneath)
        ('ZipJacket',     TRACK_ROUTINE, 130),
    ])
    + _free('bottoms', ['Trousers'])
    + _unlock('bottoms', [
        ('Shorts',      TRACK_ROUTINE, 10),
        ('Skirt',       TRACK_ROUTINE, 10),
        ('Joggers',     TRACK_ROUTINE, 35),
        ('CargoPants',  TRACK_ROUTINE, 90),
        ('Dungarees',   TRACK_POINTS,  100),
    ])
    + _free('shoes', ['Sneakers'])
    + _unlock('shoes', [
        ('Boots',      TRACK_ROUTINE, 25),
        ('Sandals',    TRACK_ROUTINE, 55),
        ('HighTops',   TRACK_POINTS,  75),
        ('WellyBoots', TRACK_STREAK,  7),
    ])
    + _unlock('graphic', [(g, TRACK_ROUTINE, 30 + i * 20)
                          for i, g in enumerate(_GRAPHICS)])
    + _unlock('neck', [
        ('Chain',    TRACK_ROUTINE, 40),
        ('Pendant',  TRACK_POINTS,  60),
        ('Scarf',    TRACK_STREAK,  10),
    ])
    + _unlock('wrist', [
        ('Bracelet',   TRACK_ROUTINE, 20),
        ('Watch',      TRACK_POINTS,  40),
        ('Sweatband',  TRACK_STREAK,  5),
    ])
    + _unlock('waist', [
        ('Belt',        TRACK_ROUTINE, 25),
        ('ChunkyBelt',  TRACK_POINTS,  80),
    ])
    + _unlock('hair_accessory', [
        ('Headband', TRACK_ROUTINE, 15),
        ('Bow',      TRACK_ROUTINE, 50),
        ('Clips',    TRACK_STREAK,  7),
    ])
)

_BY_KEY = {}
for _i in ITEMS:
    # Keys are unique per (slot, key); the flat map is keyed on both so that
    # 'Blank' can exist in eyewear and facial_hair without colliding.
    _BY_KEY[(_i['slot'], _i['key'])] = _i

_BY_SLOT: Dict[str, List[Dict]] = {}
for _i in ITEMS:
    _BY_SLOT.setdefault(_i['slot'], []).append(_i)

_SLOT_BY_KEY = {s['key']: s for s in SLOTS}


def get_slots() -> List[Dict]:
    """Slots in paint order, low z first."""
    return sorted(SLOTS, key=lambda s: s['z'])


def get_slot(slot_key: str) -> Optional[Dict]:
    return _SLOT_BY_KEY.get(slot_key)


def items_for_slot(slot_key: str) -> List[Dict]:
    return list(_BY_SLOT.get(slot_key, []))


def get_item(slot_key: str, item_key: str) -> Optional[Dict]:
    return _BY_KEY.get((slot_key, item_key))


def free_items() -> List[Dict]:
    return [i for i in ITEMS if i['tier'] == 'free']


def unlockable_items() -> List[Dict]:
    return [i for i in ITEMS if i['tier'] == 'unlock']


def item_id(slot_key: str, item_key: str) -> str:
    """The ledger's key for one piece. Slot-qualified so two slots may share
    an item name without sharing an unlock."""
    return f'{slot_key}:{item_key}'


def split_item_id(item_id_str: str):
    slot, _, key = (item_id_str or '').partition(':')
    return slot, key


def conflicts(config: Dict) -> List[str]:
    """Slots whose chosen item cannot be drawn given the rest of the config.
    Not an error -- the renderer just skips them, the same way a real bow
    cannot sit on a woolly hat."""
    out = []
    if (config or {}).get('top') in HEADWEAR and (config or {}).get('hair_accessory'):
        out.append('hair_accessory')
    only = _SLOT_BY_KEY['graphic'].get('only_with')
    if only and (config or {}).get('graphic'):
        dep_slot, dep_val = only
        if (config or {}).get(dep_slot) != dep_val:
            out.append('graphic')
    return out

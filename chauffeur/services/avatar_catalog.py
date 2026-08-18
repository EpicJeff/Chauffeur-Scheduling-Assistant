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

SLOTS = [
    {'key': 'bottoms',        'label': 'Bottoms',    'z': 10, 'required': True,  'focus': HIPS},
    {'key': 'shoes',          'label': 'Shoes',      'z': 20, 'required': True,  'focus': FEET},
    {'key': 'clothes',        'label': 'Top',        'z': 30, 'required': True,  'focus': TORSO},
    {'key': 'graphic',        'label': 'Graphic',    'z': 35, 'required': False, 'focus': TORSO,
     'only_with': ('clothes', 'GraphicShirt')},
    {'key': 'waist',          'label': 'Belt',       'z': 40, 'required': False, 'focus': WAISTLINE},
    {'key': 'wrist',          'label': 'Wrist',      'z': 45, 'required': False, 'focus': ARMS},
    {'key': 'neck',           'label': 'Neck',       'z': 50, 'required': False, 'focus': TORSO},
    {'key': 'facial_hair',    'label': 'Facial hair','z': 55, 'required': False, 'focus': HEAD},
    {'key': 'top',            'label': 'Hair & hats','z': 60, 'required': True,  'focus': HEAD},
    {'key': 'hair_accessory', 'label': 'Hair extra', 'z': 65, 'required': False, 'focus': HEAD},
    {'key': 'eyewear',        'label': 'Glasses',    'z': 70, 'required': False, 'focus': HEAD},
    # Face parts are not unlockable -- they are identity, always free, and they
    # live in the catalog only so the editor can offer them.
    {'key': 'eyes',           'label': 'Eyes',       'z': 52, 'required': True,  'focus': HEAD},
    {'key': 'eyebrow',        'label': 'Eyebrows',   'z': 53, 'required': True,  'focus': HEAD},
    {'key': 'mouth',          'label': 'Mouth',      'z': 51, 'required': True,  'focus': HEAD},
    {'key': 'nose',           'label': 'Nose',       'z': 54, 'required': True,  'focus': HEAD},
]

# Palette slots: colour swatches rather than avatar thumbnails. They sit inside
# the group they belong to, because "hair colour" is only meaningful next to
# hair.
PALETTES = [
    {'key': 'skin',          'label': 'Skin'},
    {'key': 'hair_color',    'label': 'Hair colour'},
    {'key': 'clothe_color',  'label': 'Top colour'},
    {'key': 'bottoms_color', 'label': 'Bottoms colour'},
    {'key': 'shoes_color',   'label': 'Shoe colour'},
    {'key': 'accent_color',  'label': 'Accent'},
]

# Two tiers, because eleven slots in one strip is unusable and the reference
# layouts all solve it this way. Glyphs lead: the word is for whoever can read
# it, the picture is for everyone else (same compromise as kid_glyphs.html).
GROUPS = [
    {'key': 'me',      'label': 'Me',      'glyph': '🧑',
     'tabs': ['skin', 'eyes', 'eyebrow', 'mouth', 'nose']},
    {'key': 'hair',    'label': 'Hair',    'glyph': '💇',
     'tabs': ['top', 'hair_color', 'facial_hair', 'hair_accessory']},
    {'key': 'clothes', 'label': 'Clothes', 'glyph': '👕',
     'tabs': ['clothes', 'clothe_color', 'graphic', 'bottoms', 'bottoms_color',
              'shoes', 'shoes_color']},
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

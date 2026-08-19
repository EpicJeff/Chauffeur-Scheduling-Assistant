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
# Eyes and brows are ink, not fabric: the clothing palette's pastels on a pupil
# read as a costume lens rather than an eye colour. A short natural range, plus
# the black the art has always been drawn in.
EYE_COLORS = {
    'Black': '#000000', 'Brown': '#4A312C', 'Hazel': '#8B6B3E',
    'Amber': '#B4741A', 'Green': '#3E6B4A', 'Blue': '#3B6EA5',
    'Gray': '#5C6670',
}
# Glasses frames. Metal and shell rather than t-shirt colours, for the same
# reason -- and the pale one is here because Prescription01 IS pale-rimmed.
EYEWEAR_COLORS = {
    'Black': '#252C2F', 'Charcoal': '#2F383B', 'Slate': '#4A5A63',
    'Tortoise': '#6B4423', 'Gold': '#B9912F', 'Silver': '#B8BFC4',
    'Rose': '#C97B84', 'Sky': '#D6EAF2', 'White': '#F4F4F4',
}

# (table, default). A default of None means THE ART ALREADY HAS A COLOUR: the
# renderer leaves the drawing alone until somebody chooses, so a pair of
# Wayfarers is black because that is how it is drawn, not because a palette
# happens to start there.
_PALETTES = {'skin': (SKIN_COLORS, 'Light'), 'hair_color': (HAIR_COLORS, 'BrownDark'),
             'clothe_color': (CLOTHE_COLORS, 'Blue03'),
             'hat_color': (HAT_COLORS, 'Blue03'),
             # Ours. Bottoms defaulted to the shirt colour at first and the
             # result was a onesie -- the lower half needs its own slots.
             'bottoms_color': (CLOTHE_COLORS, 'Heather'),
             'shoes_color': (CLOTHE_COLORS, 'Black'),
             'accent_color': (CLOTHE_COLORS, 'Gray02'),
             # --- one colour per thing (see _INHERITS below) -----------------
             # A beard was painted in `clothe_color` for a year, because the
             # source names its generic colour component `Colors` and the
             # extractor mapped the tag rather than the place. Hair's palette,
             # because a beard is hair.
             'facial_hair_color': (HAIR_COLORS, 'BrownDark'),
             'eyebrow_color': (HAIR_COLORS, None),
             'eye_color': (EYE_COLORS, None),
             'eyewear_color': (EYEWEAR_COLORS, None),
             'graphic_color': (CLOTHE_COLORS, None),
             # The four accessories shared one `accent_color`, so a watch could
             # not be silver while the belt was brown. They each have their own
             # now and each falls back to the accent, which keeps every saved
             # look identical and keeps the accent meaningful as the one dial
             # that moves all four.
             'neck_color': (CLOTHE_COLORS, None),
             'wrist_color': (CLOTHE_COLORS, None),
             'waist_color': (CLOTHE_COLORS, None),
             'hair_accessory_color': (CLOTHE_COLORS, None)}

# Where a colour looks when nobody has chosen one. Walked in order, so an
# unset beard takes the member's hair colour and only falls back to the hair
# DEFAULT when they have not chosen that either.
#
# This is what makes the whole split free: every avatar saved before these
# palettes existed renders exactly as it did, because every new key inherits
# the old one it was carved out of. The single exception is the beard, which
# was wrong.
_INHERITS = {'facial_hair_color': 'hair_color',
             'neck_color': 'accent_color', 'wrist_color': 'accent_color',
             'waist_color': 'accent_color', 'hair_accessory_color': 'accent_color'}

# Literal art, recoloured by substitution. A piece whose colour is baked into
# its paths has no FILL token to aim at, so the renderer swaps the hex that IS
# the piece's colour and leaves everything else standing.
#
# Per ITEM for glasses, because "the frame" is a different hex in every pair
# and the LENS beside it must not move with it: Wayfarers' #000000 is the
# tinted lens under a gloss gradient, and recolouring that would turn a pair of
# sunglasses into a pair of goggles. `'*'` means every item in the slot.
TINTS = {
    'eyewear': ('eyewear_color', {
        'Kurt': ('#2F383B',),
        'Prescription01': ('#D6EAF2',),
        'Prescription02': ('#252C2F',),
        'Round': ('#252C2F',),
        'Sunglasses': ('#252C2F',),
        'Wayfarers': ('#252C2F',),
    }),
    'graphic': ('graphic_color', {'*': ('#FFFFFF',)}),
}

# --- the lower body, ours -----------------------------------------------
# Absolute canvas coords. The shoulder edge (y=280, x 32..232) splits three
# ways: 32..76 left arm, 76..188 torso, 188..232 right arm.
SHADE = '#000000'

# Tops start at y=278, not 280: shapes that ABUT leave an antialiasing
# hairline (invisible on dark, glowing on light pages); shapes that
# OVERLAP under the piece above them leave nothing.
_ARM_L = ("M32,278 C31,318 33,356 37,394 C39,414 46,424 58,424 "
          "C70,424 77,414 77,394 C77,356 77,318 76,278 Z")
_ARM_R = ("M188,278 C187,318 187,356 187,394 C187,414 194,424 206,424 "
          "C218,424 225,414 227,394 C231,356 233,318 232,278 Z")
_SLEEVE_L = ("M32,280 L76,280 C76,306 76,330 77,352 C64,357 47,357 34,352 "
             "C32,330 32,306 32,280 Z")
_SLEEVE_R = ("M188,280 L232,280 C232,306 232,330 230,352 C217,357 200,357 187,352 "
             "C187,330 187,306 188,280 Z")
# Starts at the SHOULDER edge, not the waist. A structured garment hems at the
# hip, and if the body only began at the waist the gap between showed the page
# straight through the midriff. There is always a body under the clothes.
_LOWER = ("M76,278 L188,278 C188,318 186,346 184,372 "
          "C188,394 189,402 188,414 "
          "C185,462 182,510 181,556 C181,564 176,568 168,568 L152,568 "
          "C144,568 138,568 132,568 C126,568 120,568 112,568 L96,568 C88,568 83,564 83,556 "
          "C82,510 79,462 76,414 C75,402 76,394 80,372 "
          "C78,346 76,318 76,278 Z")

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

# --- the wardrobe we author: MULTI-PART assets ---------------------------
# Production quality forced a format change: a watch is a strap AND a face, a
# sneaker is a shoe AND a sole, and one path with one fill can never say that.
# An item is a LIST of parts painted in order:
#   {'d': path, 'f': fill, 'o': opacity?}
#   fill 'c1'  -> the slot's own colour (bottoms_color / shoes_color / accent)
#        'sh'  -> #000 at 10% (the source's soft shading)
#        'sh2' -> #000 at 16% (the source's hard shading)
#        'hi'  -> #FFF highlight (carries its own 'o')
#        '#hex'-> literal art, never recoloured
# Depth comes from the source's own vocabulary -- flat fills shaded with
# low-opacity black, highlighted with low-opacity white. Never a gradient,
# never a stroke.

BOTTOMS = {
    'Trousers': [
        {'d': ("M78,366 L186,366 C190,392 191,402 190,414 "
               "C187,462 184,508 183,552 "
               "L81,552 C80,508 77,462 74,414 C73,402 74,392 78,366 Z"), 'f': 'c1'},
        {'d': "M78,366 L186,366 C187,371 188,375 188,379 L76,379 C76,375 77,371 78,366 Z", 'f': 'sh'},
        {'d': ("M118,379 L130,379 L130,552 L116,552 C113,500 114,440 114,379 Z "
               "M134,379 L146,379 L146,464 L134,464 Z"), 'f': 'sh', 'o': 0.06},
        {'d': "M81,544 L126,544 L126,552 L81,552 Z M138,544 L183,544 L183,552 L138,552 Z", 'f': 'sh'},
        {'d': "M130.8,450 L133.2,450 L133.2,548 L130.8,548 Z", 'f': 'sh2'},
    ],
    'Joggers': [
        {'d': ("M78,366 L186,366 C190,392 191,402 190,414 "
               "C187,462 185,505 186,540 C186,548 180,552 172,552 L92,552 C84,552 78,548 78,540 "
               "C79,505 77,462 74,414 C73,402 74,392 78,366 Z"), 'f': 'c1'},
        {'d': ("M79,534 L126,534 L126,552 L92,552 C84,552 79,548 79,540 Z "
               "M138,534 L185,534 C185,548 180,552 172,552 L138,552 Z"), 'f': 'hi', 'o': 0.8},
        {'d': ("M79,534 L130,534 L130,539 L79,539 Z M134,534 L185,534 L185,539 L134,539 Z"),
         'f': 'sh'},
        {'d': "M124,372 L127,372 L126,396 L123,396 Z M137,372 L140,372 L141,396 L138,396 Z",
         'f': 'hi', 'o': 0.9},
        {'d': "M130.8,450 L133.2,450 L133.2,548 L130.8,548 Z", 'f': 'sh2'},
        {'d': "M78,366 L186,366 C186.6,370 187,373 187.4,376 L76.6,376 C77,373 77.4,370 78,366 Z", 'f': 'sh'},
    ],
    'Shorts': [
        {'d': ("M78,366 L186,366 C190,392 191,402 190,414 C188,438 186,458 185,472 "
               "L79,472 "
               "C78,458 76,438 74,414 C73,402 74,392 78,366 Z"), 'f': 'c1'},
        {'d': "M79,462 L126,462 L126,472 L79,472 Z M138,462 L185,462 L185,472 L138,472 Z", 'f': 'sh'},
        {'d': "M130.8,458 L133.2,458 L133.2,470 L130.8,470 Z", 'f': 'sh2'},
        {'d': "M78,366 L186,366 C186.6,370 187,373 187.4,376 L76.6,376 C77,373 77.4,370 78,366 Z", 'f': 'sh'},
    ],
    'Skirt': [
        {'d': ("M80,366 L184,366 C190,398 196,436 200,472 L64,472 "
               "C68,436 74,398 80,366 Z"), 'f': 'c1'},
        {'d': "M104,380 L112,380 L106,472 L96,472 Z M152,380 L160,380 L168,472 L158,472 Z", 'f': 'sh'},
        {'d': "M65,464 L199,464 L200,472 L64,472 Z", 'f': 'sh'},
        {'d': "M80,366 L184,366 C184.8,370 185.6,374 186.4,378 L77.6,378 C78.4,374 79.2,370 80,366 Z", 'f': 'sh'},
    ],
    'CargoPants': [
        {'d': ("M76,366 L188,366 C192,392 193,402 192,414 "
               "C189,462 186,508 185,552 "
               "L79,552 C78,508 75,462 72,414 C71,402 72,392 76,366 Z"), 'f': 'c1'},
        {'d': "M82,452 L112,452 L114,492 L84,492 Z M152,452 L182,452 L180,492 L150,492 Z", 'f': 'sh'},
        {'d': "M82,452 L112,452 L112.5,462 L82.5,462 Z M152,452 L182,452 L181.5,462 L151.5,462 Z", 'f': 'sh2'},
        {'d': "M130.8,450 L133.2,450 L133.2,548 L130.8,548 Z", 'f': 'sh2'},
        {'d': "M76,366 L188,366 C188.6,370 189,373 189.4,376 L74.6,376 C75,373 75.4,370 76,366 Z", 'f': 'sh'},
    ],
    'Dungarees': [
        {'d': ("M78,366 L186,366 C190,392 191,402 190,414 "
               "C187,462 184,508 183,552 "
               "L81,552 C80,508 77,462 74,414 C73,402 74,392 78,366 Z "
               "M96,280 L110,280 L110,372 L96,372 Z M154,280 L168,280 L168,372 L154,372 Z"), 'f': 'c1'},
        {'d': "M118,380 L146,380 L144,404 L120,404 Z", 'f': 'sh'},
        {'d': "M130.8,450 L133.2,450 L133.2,548 L130.8,548 Z", 'f': 'sh2'},
        {'d': "M96,280 L100,280 L100,372 L96,372 Z M154,280 L158,280 L158,372 L154,372 Z", 'f': 'sh'},
        {'d': ("M103,364 m-4,0 a4,4 0 1,0 8,0 a4,4 0 1,0 -8,0 "
               "M161,364 m-4,0 a4,4 0 1,0 8,0 a4,4 0 1,0 -8,0"), 'f': 'hi', 'o': 0.9},
    ],
}

SHOES = {
    'Sneakers': [
        {'d': ("M79,536 C79,564 84,576 100,576 L112,576 C122,576 127,570 127,560 "
               "L127,536 Z M137,536 L137,560 C137,570 142,576 152,576 L164,576 "
               "C180,576 185,564 185,536 Z"), 'f': 'c1'},
        {'d': ("M80,566 C82,573 87,576 100,576 L112,576 C120,576 125,573 126,568 "
               "L126,562 L80,562 Z M138,562 L138,568 C139,573 144,576 152,576 "
               "L164,576 C177,576 182,573 184,566 L184,562 L138,562 Z"), 'f': '#FFFFFF'},
        {'d': "M80,558 L130,558 L130,562 L80,562 Z M134,558 L184,558 L184,562 L134,562 Z", 'f': 'sh'},
        {'d': "M79,540 L131,540 L131,545 L79,545 Z M133,540 L185,540 L185,545 L133,545 Z", 'f': 'sh', 'o': 0.06},
    ],
    'Boots': [
        {'d': ("M77,520 C77,562 82,578 100,578 L114,578 C124,578 131,572 131,562 "
               "L131,520 Z M133,520 L133,562 C135,572 140,578 150,578 L164,578 "
               "C182,578 187,562 187,520 Z"), 'f': 'c1'},
        {'d': ("M78,564 C80,574 86,578 100,578 L114,578 C122,578 129,574 130,566 "
               "L130,562 L78,562 Z M134,562 L134,566 C137,574 142,578 150,578 "
               "L164,578 C178,578 184,574 186,564 L186,562 L136,562 Z"), 'f': '#262E33'},
        {'d': "M77,534 L131,534 L131,542 L77,542 Z M133,534 L187,534 L187,542 L133,542 Z", 'f': 'sh2'},
        {'d': "M117,534 L125,534 L125,542 L117,542 Z M147,534 L155,534 L155,542 L147,542 Z", 'f': '#E6E6E6'},
    ],
    'HighTops': [
        {'d': ("M78,506 C78,562 83,577 100,577 L113,577 C123,577 128,571 128,561 "
               "L128,506 Z M136,506 L136,561 C136,571 141,577 151,577 L164,577 "
               "C181,577 186,562 186,506 Z"), 'f': 'c1'},
        {'d': ("M79,564 C81,573 87,577 100,577 L113,577 C121,577 126,574 127,567 "
               "L127,561 L79,561 Z M137,561 L137,567 C138,574 143,577 151,577 "
               "L164,577 C177,577 183,573 185,564 L185,561 L137,561 Z"), 'f': '#FFFFFF'},
        {'d': ("M84,516 L122,516 L122,521 L84,521 Z M84,528 L122,528 L122,533 L84,533 Z "
               "M142,516 L180,516 L180,521 L142,521 Z M142,528 L180,528 L180,533 L142,533 Z"),
         'f': 'hi', 'o': 0.9},
        {'d': "M78,556 L131,556 L131,561 L78,561 Z M133,556 L186,556 L186,561 L133,561 Z", 'f': 'sh'},
    ],
    'WellyBoots': [
        {'d': ("M76,500 C76,564 81,580 100,580 L115,580 C125,580 130,573 130,563 "
               "L130,500 Z M133,500 L133,563 C133,573 139,580 149,580 L164,580 "
               "C183,580 188,564 188,500 Z"), 'f': 'c1'},
        {'d': "M76,500 L131,500 L131,510 L76,510 Z M133,500 L188,500 L188,510 L133,510 Z",
         'f': 'hi', 'o': 0.35},
        {'d': ("M77,566 C79,576 85,580 100,580 L115,580 C123,580 129,576 130,568 "
               "L130,564 L77,564 Z M134,564 L134,568 C136,576 141,580 149,580 "
               "L164,580 C179,580 185,576 187,566 L187,564 L135,564 Z"), 'f': 'sh2'},
    ],
    'Sandals': [
        {'d': ("M80,562 L128,562 C128,570 123,575 113,575 L94,575 C85,575 80,570 80,564 Z "
               "M136,562 L184,562 C184,570 179,575 169,575 L150,575 C141,575 136,570 136,564 Z"),
         'f': '#D0C6AC'},
        {'d': ("M82,554 L126,554 L126,562 L82,562 Z M138,554 L182,554 L182,562 L138,562 Z "
               "M98,546 L110,546 L110,562 L98,562 Z M156,546 L168,546 L168,562 L156,562 Z"),
         'f': 'c1'},
        {'d': ("M80,570 L128,570 C127,573 125,575 121,575 L88,575 C84,575 81,573 80,570 Z "
               "M136,570 L184,570 C183,573 181,575 177,575 L144,575 C140,575 137,573 136,570 Z"),
         'f': 'sh'},
    ],
}

# --- FULL TOPS: whole garments, not extensions ----------------------------
# The better architecture (user direction 2026-08-18): instead of matching a
# new piece to the source bust's hem at y=280 -- the seam that spawned the hem
# bake, the colour probes and the seam covers -- a top WE author is one
# self-contained garment from collar to hem, sleeves included, drawn over the
# whole torso. No bake, no extrusion, nothing to match. Source garments keep
# the extension machinery; everything new goes here.
# The collar/shoulder outline is traced from the source crew-neck silhouette,
# so a full top still sits on the rig the way the source clothes do.
# The shared torso outline. `collar` is the top-edge segment between the
# shoulder points (99,199)..(166,199); each garment picks its neckline.
def _top_body(collar: str) -> str:
    return ("M166,199.3 "
            "C202.9,202.3 232,233.3 232,271 "
            "C232,306 232,330 230,352 L187,352 "
            "C187,330 187,312 187,296 L188,296 "
            "C188,330 186,352 184,372 L80,372 "
            "C78,352 76,330 76,296 L77,296 "
            "C77,312 77,330 77,352 L34,352 "
            "C32,330 32,306 32,271 "
            "C32,233.3 61.6,202.9 99,199.2 " + collar + " Z")

_CREW = ("C99,211.9 113.5,221.8 132.5,221.8 "
         "C151,221.8 166,211.9 166,199.3")
_SCOOP = ("C99,220 112,234 132.5,234 "
          "C153,234 166,220 166,199.3")
_VEE = "L132,236 L166,199.3"
_HIGH = ("C104,206 116,210 132.5,210 "
         "C149,210 161,206 166,199.3")

_CUFFS = ("M34,344 L77,344 L77,352 L34,352 Z "
          "M187,344 L230,344 L230,352 L187,352 Z")
_HEMBAND = "M80,364 L184,364 L184,372 L80,372 Z"

FULL_TOPS = {
    'ShirtCrewNeck': [
        {'d': _top_body(_CREW), 'f': 'c1'},
        {'d': ("M99,199.2 " + _CREW + " L166,206 C160,216 148,226 132.5,226 "
               "C117,226 105,216 99,206 Z"), 'f': 'sh'},
        {'d': _HEMBAND, 'f': 'sh'},
    ],
    'ShirtScoopNeck': [
        {'d': _top_body(_SCOOP), 'f': 'c1'},
        {'d': ("M99,199.2 " + _SCOOP + " L166,206 C161,226 150,238 132.5,238 "
               "C115,238 104,226 99,206 Z"), 'f': 'sh'},
        {'d': _HEMBAND, 'f': 'sh'},
    ],
    'ShirtVNeck': [
        {'d': _top_body(_VEE), 'f': 'c1'},
        {'d': "M99,199.2 L132,236 L166,199.3 L166,207 L132,244 L99,206 Z", 'f': 'sh'},
        {'d': _HEMBAND, 'f': 'sh'},
    ],
    'GraphicShirt': [
        # the graphic itself is overlaid by the renderer (translate 0,170)
        {'d': _top_body(_CREW), 'f': 'c1'},
        {'d': ("M99,199.2 " + _CREW + " L166,206 C160,216 148,226 132.5,226 "
               "C117,226 105,216 99,206 Z"), 'f': 'sh'},
        {'d': _HEMBAND, 'f': 'sh'},
    ],
    'CollarSweater': [
        {'d': _top_body(_HIGH), 'f': 'c1'},
        # rolled turtleneck collar
        {'d': ("M102,190 C102,204 115,212 132.5,212 C150,212 163,204 163,190 "
               "L163,202 C163,214 150,221 132.5,221 C115,221 102,214 102,202 Z"),
         'f': 'c1'},
        {'d': ("M102,196 C104,208 116,215 132.5,215 C149,215 161,208 163,196 "
               "L163,202 C163,214 150,221 132.5,221 C115,221 102,214 102,202 Z"),
         'f': 'sh'},
        {'d': _CUFFS, 'f': 'sh'},
        {'d': _HEMBAND, 'f': 'sh'},
    ],
    'Hoodie': [
        {'d': _top_body(_SCOOP), 'f': 'c1'},
        # the hood, resting on the shoulders
        {'d': ("M92,208 C92,232 108,246 132.5,246 C157,246 173,232 173,208 "
               "C173,196 166,190 160,192 C166,200 168,212 160,224 "
               "C152,234 143,238 132.5,238 C122,238 113,234 105,224 "
               "C97,212 99,200 105,192 C99,190 92,196 92,208 Z"), 'f': 'c1'},
        {'d': ("M92,208 C92,232 108,246 132.5,246 C157,246 173,232 173,208 "
               "L173,214 C170,236 155,250 132.5,250 C110,250 95,236 92,214 Z"),
         'f': 'sh'},
        # drawstrings
        {'d': "M122,242 L125,242 L124,282 L121,282 Z M140,242 L143,242 L144,282 L141,282 Z",
         'f': 'hi', 'o': 0.9},
        # kangaroo pocket
        {'d': ("M102,318 L162,318 C160,350 157,364 152,368 L112,368 "
               "C107,364 104,350 102,318 Z"), 'f': 'sh'},
        {'d': _HEMBAND, 'f': 'sh'},
    ],
    'Overall': [
        # a grey tee underneath; the overall itself takes the member's colour
        {'d': _top_body(_CREW), 'f': '#E6E6E6'},
        {'d': "M96,236 L168,236 L168,372 L96,372 Z", 'f': 'c1'},
        {'d': ("M96,199.2 L112,199.2 L112,252 L96,252 Z "
               "M152,199.3 L168,199.3 L168,252 L152,252 Z"), 'f': 'c1'},
        {'d': "M96,236 L168,236 L168,244 L96,244 Z", 'f': 'sh'},
        {'d': ("M104,240 m-4,0 a4,4 0 1,0 8,0 a4,4 0 1,0 -8,0 "
               "M160,240 m-4,0 a4,4 0 1,0 8,0 a4,4 0 1,0 -8,0"), 'f': 'hi', 'o': 0.9},
        {'d': "M108,300 L156,300 L156,304 L108,304 Z", 'f': 'sh'},
    ],
    'BlazerShirt': [
        # jacket in the member's colour over a white shirt, lapels a tone
        # darker -- an upgrade on the source, whose blazer ignored colour
        {'d': _top_body(_VEE), 'f': 'c1'},
        {'d': "M110,214 L154,214 L150,372 L114,372 Z", 'f': '#FFFFFF'},
        {'d': ("M99,199.2 L132,238 L112,306 L94,258 Z "
               "M166,199.3 L132,238 L152,306 L170,258 Z"), 'f': 'sh2'},
        {'d': "M155,246 L166,242 L165,252 L156,254 Z", 'f': 'hi', 'o': 0.85},
        {'d': _HEMBAND, 'f': 'sh'},
        {'d': _CUFFS, 'f': 'sh'},
    ],
    'BlazerSweater': [
        {'d': _top_body(_VEE), 'f': 'c1'},
        {'d': "M110,214 L154,214 L150,372 L114,372 Z", 'f': '#3C4F5C'},
        {'d': ("M112,214 C116,222 123,226 132,226 C141,226 148,222 152,214 "
               "L112,214 Z"), 'f': 'sh2'},
        {'d': ("M99,199.2 L132,238 L112,306 L94,258 Z "
               "M166,199.3 L132,238 L152,306 L170,258 Z"), 'f': 'sh2'},
        {'d': "M155,246 L166,242 L165,252 L156,254 Z", 'f': 'hi', 'o': 0.85},
        {'d': _HEMBAND, 'f': 'sh'},
        {'d': _CUFFS, 'f': 'sh'},
    ],
    'ZipJacket': [
        {'d': _top_body(_CREW), 'f': 'c1'},
        {'d': ("M99,199.2 " + _CREW + " L166,207 "
               "C160,219 148,227 132.5,227 C117,227 105,219 99,207 Z"), 'f': 'sh2'},
        {'d': "M130,227 L135,227 L134,372 L131,372 Z", 'f': 'hi', 'o': 0.85},
        {'d': "M129,238 L136,238 L136,252 L129,252 Z", 'f': 'sh2'},
        {'d': _CUFFS, 'f': 'sh'},
        {'d': _HEMBAND, 'f': 'sh'},
    ],
}

NECK = {
    'Chain': [
        # hangs FROM the collar seam (y~225), not mid-chest -- the debug pass
        # that placed the scarf found every neck anchor 30 units low
        {'d': ("M112,232 C112,254 121,264 132,264 C143,264 152,254 152,232 L147,232 "
               "C147,251 141,259 132,259 C123,259 117,251 117,232 Z"), 'f': 'c1'},
        {'d': "M130,261 m-2.5,0 a2.5,2.5 0 1,0 5,0 a2.5,2.5 0 1,0 -5,0", 'f': 'hi', 'o': 0.7},
    ],
    'Pendant': [
        {'d': ("M113,232 C113,256 122,267 132,267 C142,267 151,256 151,232 L146,232 "
               "C146,253 140,262 132,262 C124,262 118,253 118,232 Z"), 'f': '#929598'},
        {'d': "M132,264 L140,274 L132,286 L124,274 Z", 'f': 'c1'},
        {'d': "M132,264 L136,269 L132,275 L128,269 Z", 'f': 'hi', 'o': 0.45},
    ],
    'Scarf': [
        # a scarf wraps the NECK: a solid collar band whose top edge hugs the
        # jaw almost flat -- an earlier draft dipped the top edge to the
        # sternum and the result read as horns around a bare throat
        {'d': ("M98,196 C104,204 116,209 132,209 C148,209 160,204 166,196 "
               "L166,222 C166,240 151,250 132,250 C113,250 98,240 98,222 Z"), 'f': 'c1'},
        {'d': "M116,244 L146,244 L143,290 L120,290 Z", 'f': 'c1'},
        {'d': ("M120,282 L143,282 L143,290 L120,290 Z "
               "M128,244 L132,244 L131,282 L127,282 Z"), 'f': 'sh2'},
        {'d': ("M98,214 C102,230 114,240 132,240 C150,240 162,230 166,214 L166,222 "
               "C162,238 149,246 132,246 C115,246 102,238 98,222 Z"), 'f': 'sh'},
    ],
}
WRIST = {
    'Bracelet': [
        {'d': ("M40,396 C40,406 47,412 58,412 C69,412 76,406 76,396 L76,404 "
               "C76,412 69,418 58,418 C47,418 40,412 40,404 Z "
               "M188,396 C188,406 195,412 206,412 C217,412 224,406 224,396 L224,404 "
               "C224,412 217,418 206,418 C195,418 188,412 188,404 Z"), 'f': 'c1'},
        {'d': ("M47,408 m-2,0 a2,2 0 1,0 4,0 a2,2 0 1,0 -4,0 "
               "M58,410 m-2,0 a2,2 0 1,0 4,0 a2,2 0 1,0 -4,0 "
               "M69,408 m-2,0 a2,2 0 1,0 4,0 a2,2 0 1,0 -4,0 "
               "M195,408 m-2,0 a2,2 0 1,0 4,0 a2,2 0 1,0 -4,0 "
               "M206,410 m-2,0 a2,2 0 1,0 4,0 a2,2 0 1,0 -4,0 "
               "M217,408 m-2,0 a2,2 0 1,0 4,0 a2,2 0 1,0 -4,0"), 'f': 'hi', 'o': 0.6},
    ],
    'Watch': [
        {'d': "M42,392 L74,392 L74,406 L42,406 Z M190,392 L224,392 L224,406 L190,406 Z", 'f': 'c1'},
        {'d': ("M58,399 m-9,0 a9,9 0 1,0 18,0 a9,9 0 1,0 -18,0 "
               "M207,399 m-9,0 a9,9 0 1,0 18,0 a9,9 0 1,0 -18,0"), 'f': '#929598'},
        {'d': ("M58,399 m-6.5,0 a6.5,6.5 0 1,0 13,0 a6.5,6.5 0 1,0 -13,0 "
               "M207,399 m-6.5,0 a6.5,6.5 0 1,0 13,0 a6.5,6.5 0 1,0 -13,0"), 'f': '#FFFFFF'},
        {'d': ("M57.4,394.5 L58.6,394.5 L58.6,399.6 L57.4,399.6 Z "
               "M58,398.9 L61.5,401 L60.9,402 L57.4,399.9 Z "
               "M206.4,394.5 L207.6,394.5 L207.6,399.6 L206.4,399.6 Z "
               "M207,398.9 L210.5,401 L209.9,402 L206.4,399.9 Z"), 'f': '#262E33'},
    ],
    'Sweatband': [
        {'d': "M38,388 L78,388 L78,406 L38,406 Z M186,388 L226,388 L226,406 L186,406 Z", 'f': 'c1'},
        {'d': "M38,395 L78,395 L78,399 L38,399 Z M186,395 L226,395 L226,399 L186,399 Z",
         'f': 'hi', 'o': 0.85},
        {'d': "M38,402 L78,402 L78,406 L38,406 Z M186,402 L226,402 L226,406 L186,406 Z", 'f': 'sh'},
    ],
}
WAIST = {
    'Belt': [
        {'d': "M76,364 L188,364 L188,380 L76,380 Z", 'f': 'c1'},
        {'d': "M123,360 L141,360 L141,384 L123,384 Z", 'f': '#E6E6E6'},
        {'d': "M127,364 L137,364 L137,380 L127,380 Z", 'f': 'sh2'},
        {'d': "M76,376 L188,376 L188,380 L76,380 Z", 'f': 'sh'},
    ],
    'ChunkyBelt': [
        {'d': "M74,360 L190,360 L190,386 L74,386 Z", 'f': 'c1'},
        {'d': "M118,354 L146,354 L146,392 L118,392 Z", 'f': '#E6E6E6'},
        {'d': "M124,360 L140,360 L140,386 L124,386 Z", 'f': 'c1'},
        {'d': "M130,368 m-3,0 a3,3 0 1,0 6,0 a3,3 0 1,0 -6,0", 'f': '#E6E6E6'},
        {'d': "M74,380 L190,380 L190,386 L74,386 Z", 'f': 'sh'},
    ],
}
HAIR_ACCESSORY = {
    'Headband': [
        {'d': ("M74,104 C74,80 96,62 132,62 C168,62 190,80 190,104 L190,118 "
               "C190,94 168,78 132,78 C96,78 74,94 74,118 Z"), 'f': 'c1'},
        {'d': ("M74,112 C74,90 98,74 132,74 C166,74 190,90 190,112 L190,118 "
               "C190,94 168,78 132,78 C96,78 74,94 74,118 Z"), 'f': 'sh'},
    ],
    # Bow and clips sit ON THE HAIR, high on the skull -- the first draft put
    # them at y82-104, which the face frame (translate 76,82) makes exactly
    # eyebrow height (family-reported: "they are on the eyebrows").
    'Bow': [
        {'d': ("M158,44 C146,34 132,36 130,46 C128,56 140,64 154,60 Z "
               "M158,44 C170,32 186,34 188,44 C190,54 178,62 164,58 Z"), 'f': 'c1'},
        {'d': "M152,42 C158,38 164,38 168,42 C172,48 168,56 160,56 C154,56 150,50 152,42 Z", 'f': 'sh2'},
        {'d': "M156,56 L164,58 L158,78 L151,75 Z M164,58 L172,58 L172,76 L165,76 Z", 'f': 'c1'},
        {'d': "M151,72 L158,75 L158,78 L151,75 Z M165,73 L172,73 L172,76 L165,76 Z", 'f': 'sh'},
    ],
    'Clips': [
        {'d': ("M84,64 L106,52 C108,51 110,52 110,54 C110,55 109,56 108,57 L88,69 "
               "C86,70 84,69 84,67 Z "
               "M154,52 L176,64 C178,65 178,67 176,68 C175,69 173,69 172,68 L152,57 "
               "C150,56 150,54 152,53 Z"), 'f': 'c1'},
        {'d': ("M99,56 m-2,0 a2,2 0 1,0 4,0 a2,2 0 1,0 -4,0 "
               "M91,61 m-2,0 a2,2 0 1,0 4,0 a2,2 0 1,0 -4,0 "
               "M161,56 m-2,0 a2,2 0 1,0 4,0 a2,2 0 1,0 -4,0 "
               "M169,61 m-2,0 a2,2 0 1,0 4,0 a2,2 0 1,0 -4,0"), 'f': 'hi', 'o': 0.7},
    ],
}

# Depth on the rig itself (user feedback 2026-08-18: dead-flat reads as
# unpolished). The source shades with low-opacity black; these follow it.
#   - a soft contact shadow grounds the standing figure
#   - inner-edge shadows round the arms and legs into tubes
GROUND_SHADOW = "M132,574 m-58,0 a58,9 0 1,0 116,0 a58,9 0 1,0 -116,0"
RIG_DEPTH = [
    # inner edge of each arm
    {'d': ("M70,286 C71,318 71,352 71,386 C71,404 66,416 58,421 "
           "C68,420 77,412 77,394 C77,356 77,318 76,286 Z"), 'f': 'sh', 'o': 0.08},
    {'d': ("M188,286 C187,318 187,352 187,386 C187,404 192,416 200,421 "
           "C190,420 187,412 187,394 C187,356 187,318 188,286 Z"), 'f': 'sh', 'o': 0.08},
    # inner edge of each leg, below wherever the bottoms end
    # the leg separation is DRAWN (sh2 crease), never cut out of the
    # silhouette: a transparent gap shows the page through the figure, and on
    # a light board that read as a white slot from crotch to floor
    {'d': "M130.7,470 L133.3,470 L133.3,566 L130.7,566 Z", 'f': 'sh2'},
]
# Sleeve cuff shadows: the arm continues out of the sleeve, so the sleeve
# casts on it exactly the way the source's chin casts on the neck.
SLEEVE_SHADOW = ("M34,352 C47,357 64,357 77,352 L77,360 C64,365 47,365 34,360 Z "
                 "M187,352 C200,357 217,357 230,352 L230,360 C217,365 200,365 187,360 Z")

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


def _color(kind: str, chosen) -> Optional[str]:
    """The hex behind a palette choice.

    None when nothing is chosen and the palette has no default -- the art in
    that slot is already coloured (a lens, a chest graphic, the ink an eye is
    drawn in), so the honest answer is "leave it alone" rather than a colour
    picked by whichever swatch happens to sort first."""
    table, default = _PALETTES[kind]
    hit = table.get(chosen or '')
    if hit:
        return hit
    if default is None:
        return None
    return table.get(default, '#000000')


def _chosen(cfg: Dict, kind: str):
    """The palette VALUE in force for a slot, following `_INHERITS`, or None.

    A NAME rather than a hex, because the caller has to be able to tell "the
    member picked nothing anywhere along this chain" from "they picked the
    colour that happens to be the default" -- see `_expand`, where a source
    piece's own defaultColor sits between the two and a red winter hat depends
    on it.

    Every inheritance pair shares a colour table (a beard and hair are both
    HAIR_COLORS, the four accessories and the accent are all CLOTHE_COLORS), so
    a name carried across a link always resolves."""
    seen, at = set(), kind
    while at not in seen:
        seen.add(at)
        if cfg.get(at):
            return cfg[at]
        nxt = _INHERITS.get(at)
        if not nxt:
            break
        at = nxt
    return None


def _slot_color(cfg: Dict, kind: str) -> Optional[str]:
    """The colour a slot actually paints in.

    An unset beard takes the member's hair colour; an unset watch takes the
    accent. Only when nothing along the chain is chosen does the palette's own
    default (or None) answer -- which is what makes every avatar saved before
    these palettes existed render exactly as it did."""
    return _color(kind, _chosen(cfg, kind))


def _tint(slot: str, key: str, cfg: Dict, svg: str) -> str:
    """Recolour literal art, for a slot whose colour is baked into its paths.

    A swap rather than a fill token because these pieces came out of the source
    with the colour already in them and there is nothing to aim a mask at. Only
    the hexes named in `TINTS` move: the lens, the gloss gradient and every
    shadow stay exactly where the illustrator put them."""
    spec = TINTS.get(slot)
    if not spec or not svg:
        return svg
    palette, per_item = spec
    col = _color(palette, cfg.get(palette))
    if not col:
        return svg                      # nothing chosen: the art as drawn
    for hexcode in (per_item.get(key) or per_item.get('*') or ()):
        svg = svg.replace(f"'{hexcode}'", f"'{col}'").replace(f'"{hexcode}"', f'"{col}"')
    return svg


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
            # Precedence, and the order matters: the member's own choice, then
            # whatever this palette inherits from (hair, for a beard), THEN the
            # source piece's own defaultColor, then the palette's default.
            #
            # The third step is not decoration. Four hats ship with a colour of
            # their own -- a winter hat is Red because it is a Santa hat -- and
            # letting the palette default win over it turned every one of them
            # the same blue.
            chosen = _chosen(cfg, name) if name in _PALETTES else None
            return _fill_through(a, _color(name, chosen or (b or None)) or '#000000')
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
    return _tint(slot, key, cfg, _expand(frag, f'{ns}{slot}_', cfg, depth))


def _shade(path: str, opacity: str = '0.1') -> str:
    return f'<path d="{path}" fill="{SHADE}" fill-opacity="{opacity}"/>'


def _paint(parts, c1: str) -> str:
    """Paint a multi-part asset. `c1` is the slot's own colour; 'sh'/'sh2' are
    the source's two shading strengths; 'hi' is a white highlight carrying its
    own opacity; anything else is literal art."""
    out = []
    for p in (parts or []):
        f = p.get('f', 'c1')
        if f == 'c1':
            fill, op = c1, p.get('o')
        elif f == 'sh':
            fill, op = SHADE, p.get('o', 0.1)
        elif f == 'sh2':
            fill, op = SHADE, p.get('o', 0.16)
        elif f == 'hi':
            fill, op = '#FFFFFF', p.get('o', 0.5)
        else:
            fill, op = f, p.get('o')
        o = f' fill-opacity="{op}"' if op is not None else ''
        out.append(f'<path d="{p["d"]}" fill="{fill}"{o}/>')
    return ''.join(out)


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
        shoes = SHOES.get(cfg.get('shoes') or '')
        bot_col = _color('bottoms_color', cfg.get('bottoms_color'))
        parts = [
            # the contact shadow grounds the figure before anything stands on it
            _shade(GROUND_SHADOW, '0.14'),
            f'<path d="{_ARM_L}" fill="{skin}"/><path d="{_ARM_R}" fill="{skin}"/>',
            f'<path d="{_LOWER}" fill="{skin}"/>',
            _paint(RIG_DEPTH, skin),
            # A waistband that rises ABOVE the tops' hems. Without it a blazer
            # (which hems at the hip, correctly) left a band of bare midriff
            # between itself and the trousers. Real clothes overlap.
            (f'<path d="M78,336 L186,336 C187,352 187,360 186,372 L78,372 '
             f'C77,360 77,352 78,336 Z" fill="{bot_col}"/>'
             + _paint(bottoms, bot_col))
            if bottoms else '',
            _paint(shoes, _color('shoes_color', cfg.get('shoes_color')))
            if shoes else '',
        ]
        lower = ''.join(p for p in parts if p)

    # The garment continuation. Every source top ends flush on y=280, so the
    # bottom edge is a list of colour runs (baked by tools/bake_garment_hems.py)
    # and extruding them straight down is exact -- which is the only way a
    # blazer's lapels and its undershirt can carry on in the right colours.
    # The extrusion is then clipped to a tapered torso so the silhouette
    # narrows even though every run is vertical.
    full_top = FULL_TOPS.get(cfg.get('clothes') or '')
    torso_ext = ''
    seam_cover = ''
    if full and not full_top:
        top_key = cfg.get('clothes') or ''
        hem = HEM_STRUCTURED if top_key in STRUCTURED else HEM_SOFT
        runs = _hems().get(top_key)
        clip = f'{ns}torsoclip'
        taper = (f'M76,278 L188,278 C188,310 186,{hem - 26} 184,{hem} '
                 f'L80,{hem} C78,{hem - 26} 76,310 76,278 Z')
        if runs:
            bars = ''.join(
                f'<rect x="{r["x"]}" y="278" width="{r["w"]}" height="{hem - 278}" '
                f'fill="{r["fill"] or clothe}"/>' for r in runs)
            torso_ext = (f'<clipPath id="{clip}"><path d="{taper}"/></clipPath>'
                         f'<g clip-path="url(#{clip})">{bars}</g>')
            # The source garments' colour masks leak a hairline of #E6E6E6
            # base along their hem edge (y=280) -- invisible on dark pages,
            # glowing on light ones. A strip of the same colours painted
            # AFTER the garment hides it exactly.
            seam_cover = (f'<g clip-path="url(#{clip})">' + ''.join(
                f'<rect x="{r["x"]}" y="277" width="{r["w"]}" height="8" '
                f'fill="{r["fill"] or clothe}"/>' for r in runs) + '</g>')
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
                      f'<path d="{_SLEEVE_R}" fill="{right}"/>'
                      # the sleeve casts on the arm below it, the same way the
                      # source's chin casts on the neck
                      + _shade(SLEEVE_SHADOW, '0.1'))

    # One colour per thing. These four shared `accent_color`, so a silver
    # watch forced a silver belt; each has its own palette now and each falls
    # back to the accent, which leaves every saved look untouched and keeps
    # the accent meaningful as the one dial that moves all four at once.
    extras = ''
    if full:
        for slot, table in (('waist', WAIST), ('wrist', WRIST), ('neck', NECK)):
            item = table.get(cfg.get(slot) or '')
            if item:
                extras += _paint(item, _slot_color(cfg, f'{slot}_color'))
    hair_extra = HAIR_ACCESSORY.get(cfg.get('hair_accessory') or '')

    # Eyes and brows paint in their OWN ink, inside the black face group.
    # Nested rather than separate groups so the source's transform still
    # applies once -- and the shapes that carry a literal fill (a sclera, a
    # tear, the heart-eyes) keep it, because only the UNFILLED paths inherit.
    # That is the whole reason this can be a group colour at all: what
    # inherits is the pupil and the lash line, which is what an eye colour
    # means, and never the white of the eye.
    eye_ink = _color('eye_color', cfg.get('eye_color'))
    brow_ink = _slot_color(cfg, 'eyebrow_color')
    face = (f'<g id="{ns}face" transform="translate(76,82)" fill="#000000">'
            f'{_piece("mouth", cfg, ns)}{_piece("nose", cfg, ns)}'
            + (f'<g fill="{eye_ink}">{_piece("eyes", cfg, ns)}</g>'
               if eye_ink else _piece("eyes", cfg, ns))
            + (f'<g fill="{brow_ink}">{_piece("eyebrow", cfg, ns)}</g>'
               if brow_ink else _piece("eyebrow", cfg, ns))
            + '</g>')

    # a full top is ours: painted whole, worn in both crops, and it brings
    # its own sleeves -- the generic ones would double-draw beneath it
    if full_top:
        clothes_svg = _paint(full_top, clothe) + _shade(SLEEVE_SHADOW, '0.1')
        # chest graphics live in the clothes group's frame (translate 0,170)
        if cfg.get('clothes') == 'GraphicShirt' and cfg.get('graphic'):
            clothes_svg += (f'<g transform="translate(0,170)">'
                            f'{_piece("graphic", cfg, ns)}</g>')
    else:
        clothes_svg = _piece('clothes', cfg, ns)
    hair_extra_svg = (_paint(hair_extra, _slot_color(cfg, 'hair_accessory_color'))
                      if hair_extra else '')
    dims = f'width="{size}" ' if size else ''
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" {dims}'
        f'viewBox="0 0 264 {height}" preserveAspectRatio="xMidYMax meet" '
        f'role="img" aria-label="avatar">'
        f'<defs><path d="{_BODY_PATH}" id="{ns}bodypath"/></defs>'
        f'<g fill="none" fill-rule="evenodd" stroke="none">'
        f'{lower}{head}{torso_ext}{clothes_svg}{seam_cover}{extras}'
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

_EFFECTIVE_CACHE: Dict[tuple, tuple] = {}   # (member_id, crop) -> (cfg_key, url)


def head_data_url(config: Dict) -> str:
    """The head crop as a data-URL an <img> can eat. Each <img> is its own
    document, so a fixed nonce cannot collide with anything."""
    import base64
    svg = render_svg(config, 'head', nonce='i')
    return 'data:image/svg+xml;base64,' + base64.b64encode(svg.encode('utf-8')).decode('ascii')


def figure_data_url(config: Dict) -> str:
    """The full-body crop as a data-URL. The showcase form."""
    import base64
    svg = render_svg(config, 'full', nonce='f')
    return 'data:image/svg+xml;base64,' + base64.b64encode(svg.encode('utf-8')).decode('ascii')


# A CRITTER STANDS WITH ITS PERSON.
#
# The full crop is 264x600 with the ground shadow at y=574, so the sidekick is
# hung from that same ground line at the owner's right, overlapping their shin
# a little -- it reads as *with* them rather than as a second portrait beside
# them. Knee height on purpose: a companion, not a rival.
#
# It lives HERE, in the one function every showcase surface already calls,
# rather than being added to each of them. That is the whole reason a pet
# turns up on the hearth, both sets of lanes, the home board, the editor card
# and the PWA's My Day from a single change -- and why a household that has
# never hatched anything sees exactly what it saw before.
COMPANION_X = 132
COMPANION_SIZE = 150
COMPANION_GROUND = 582


def _companion(member_id: str) -> str:
    """The member's active critter as a nested svg, or '' for no pet, no pet
    art, or anything at all going wrong -- a figure must still draw."""
    try:
        from services import pet_render
        from services import storage
        if not pet_render.available():
            return ''
        pet = storage.get_active_pet(member_id)
        if not pet:
            return ''
        cfg = dict(pet.get('species') or {})
        cfg.update(pet.get('look') or {})
        return pet_render.embed_svg(
            cfg, COMPANION_X, COMPANION_GROUND - COMPANION_SIZE,
            COMPANION_SIZE, nonce='c%s' % (pet.get('id') or '')[:10])
    except Exception as e:
        print(f"[avatar_render] companion failed: {e}")
        return ''


def _companion_key(member_id: str) -> str:
    """What the cache has to notice. A restyled or renamed critter must
    redraw, so the pet's look is part of the figure's identity."""
    try:
        from services import storage
        pet = storage.get_active_pet(member_id)
        if not pet:
            return '-'
        return json.dumps([pet.get('id'), pet.get('species'), pet.get('look')],
                          sort_keys=True)
    except Exception:
        return '-'


def effective_figure(member: Dict) -> Optional[str]:
    """The standing character for the showcase surfaces (lanes, boards), with
    their critter beside them.

    Deliberately NOT gated by avatar_kind: the character someone built always
    draws at full size, even for a member whose CHIP is their photo -- a photo
    cannot stand in a lane, and the whole economy pays out here."""
    if not member or not available():
        return None
    import base64
    from services import storage
    mid = member.get('id')
    cfg = storage.get_avatar_config(mid)
    key = json.dumps(cfg, sort_keys=True) + '|' + _companion_key(mid)
    hit = _EFFECTIVE_CACHE.get((mid, 'full'))
    if hit and hit[0] == key:
        return hit[1]
    svg = render_svg(cfg, 'full', nonce='f')
    pet = _companion(mid)
    if pet and svg.endswith('</svg>'):
        svg = svg[:-len('</svg>')] + pet + '</svg>'
    url = ('data:image/svg+xml;base64,'
           + base64.b64encode(svg.encode('utf-8')).decode('ascii'))
    _EFFECTIVE_CACHE[(mid, 'full')] = (key, url)
    return url


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
        # One entry per palette, straight off `_PALETTES` rather than a
        # hand-kept copy: the hand-kept version is how `bottoms_color` reached
        # the browser without a table the day it shipped, and a palette the
        # editor cannot see is a colour nobody can choose.
        'palettes': {k: v[0] for k, v in _PALETTES.items()},
        # A default of null means the art is already coloured -- the browser
        # leaves it alone, exactly as `_color` does.
        'defaults': {k: v[1] for k, v in _PALETTES.items()},
        'inherits': _INHERITS,
        'tints': {slot: {'palette': pal, 'items': items}
                  for slot, (pal, items) in TINTS.items()},
        'rig': {'armL': _ARM_L, 'armR': _ARM_R, 'sleeveL': _SLEEVE_L,
                'sleeveR': _SLEEVE_R, 'lower': _LOWER, 'body': _BODY_PATH,
                'neckShadow': _NECK_SHADOW, 'shade': SHADE},
        'tables': {'bottoms': BOTTOMS, 'shoes': SHOES, 'neck': NECK,
                   'wrist': WRIST, 'waist': WAIST,
                   'hair_accessory': HAIR_ACCESSORY},
        'full_tops': FULL_TOPS,
        'rig_depth': {'ground': GROUND_SHADOW, 'parts': RIG_DEPTH,
                      'sleeveShadow': SLEEVE_SHADOW},
        'hems_meta': {'structured': sorted(STRUCTURED),
                      'hemStructured': HEM_STRUCTURED, 'hemSoft': HEM_SOFT},
        'slots': cat.get_slots(), 'groups': cat.GROUPS,
        'palette_slots': cat.PALETTES,
    }

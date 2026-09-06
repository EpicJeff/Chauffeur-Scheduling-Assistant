"""Pets: hatching, the free half, and the promises that must not bend.

What is being defended:

  * IDENTITY IS FREE (rule 1). Species, look, name and element cost nothing.
    If any of them ever grows a gate, this file fails.
  * A PET IS NEVER LOST (rule 3). Retiring frees the slot and keeps the
    record; nothing in the app deletes a creature on its own.
  * THE EARNED HALF IS NOT WRITABLE. Level, training and moves come from a
    ledger in P2/P5. An editor must never be able to hand out what a ledger
    is supposed to.
  * The type ring is balanced, because "there is no best element to pick" is
    a claim the editor makes to a child in writing.
  * The hand path exists: a pets card a person can place, and an empty slot
    that leads somewhere.

Run from chauffeur/:  python tests/test_pets.py
"""
import atexit
import os
import shutil
import sys
import re
import tempfile
import traceback

_TMP = tempfile.mkdtemp(prefix="chauffeur_pets_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import storage  # noqa: E402
from services import pet_catalog  # noqa: E402
from services import pet_render  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def reset_db():
    with storage.db_lock:
        for name, val in list(vars(storage).items()):
            if name.endswith("_table"):
                val.truncate()


def _member(mid, name="Kid", role="child", pin=None):
    storage.add_member({"id": mid, "name": name, "role": role,
                        "color_code": "#3b82f6", "is_child": role == "child"})
    if pin:
        storage.set_member_pin(mid, pin)
    return storage.get_member(mid)


# --- the ring -------------------------------------------------------------

def test_every_element_beats_one_and_loses_to_one():
    keys = pet_catalog.keys()
    check(len(keys) == 5, "the ring is five elements")
    for a in keys:
        wins = [b for b in keys if pet_catalog.beats(a, b)]
        losses = [b for b in keys if pet_catalog.beats(b, a)]
        check(len(wins) == 1, "%s beats %s -- must be exactly one" % (a, wins))
        check(len(losses) == 1, "%s loses to %s -- must be exactly one" % (a, losses))
        check(a not in wins, "%s beats itself" % a)


def test_no_element_is_better_than_another():
    """The editor tells a child there is no best pick. That has to be true."""
    keys = pet_catalog.keys()
    for a in keys:
        total = 1.0
        for b in keys:
            total *= pet_catalog.multiplier(a, b)
        check(abs(total - 1.0) < 1e-9,
              "%s has a net advantage of %.4f across the ring" % (a, total))
    check(abs(pet_catalog.SUPER * pet_catalog.RESIST - 1.0) < 1e-9,
          "super and resist must be reciprocal or a lap round the ring drifts")


def test_matchup_reads_as_words():
    txt = pet_catalog.matchup_text('ember', 'leaf')
    check('super effective' in txt and 'Ember' in txt, "bad matchup text: %r" % txt)
    check(pet_catalog.matchup_text('ember', 'ember') == '',
          "a neutral matchup should say nothing")
    check(pet_catalog.coerce('nonsense') in pet_catalog.keys(),
          "an invalid type must coerce to a real one, never stay invalid")


# --- hatching and the free half ------------------------------------------

def test_hatching_is_free_and_costs_no_points():
    reset_db()
    _member("k1", "Ada")
    before = storage.get_points_balance("k1")
    res = storage.create_pet("k1", "Rocket", {'body': 'tower', 'top': 'horns'},
                             {'eyes': 'angry', 'base_color': 'Coral'}, 'ember')
    check('pet' in res, "a first pet must be free: %s" % res)
    check(storage.get_points_balance("k1") == before,
          "hatching charged points -- identity is free (rule 1)")
    check(not res['rejected'], "a valid look was rejected: %s" % res['rejected'])


def test_every_part_and_colour_is_choosable():
    """No part is gated. If a padlock ever appears, it appears here first."""
    reset_db()
    _member("k1")
    res = storage.create_pet("k1", "A", {'body': 'tower', 'top': 'horns'}, {})
    pid = res['pet']['id']
    for slot in ('body', 'top', 'eyes', 'mouth', 'pattern', 'cheeks'):
        for key in pet_render.parts(slot):
            out = storage.update_pet(pid, {
                'species': {'body': key if slot == 'body' else 'tower',
                            'top': key if slot == 'top' else 'horns'},
                'look': {slot: key} if slot not in ('body', 'top') else {}})
            check(not out['rejected'],
                  "%s/%s was refused: %s" % (slot, key, out['rejected']))
    for c in pet_render.BASE_COLORS:
        out = storage.update_pet(pid, {'look': {'base_color': c, 'accent_color': c}})
        check(not out['rejected'], "colour %s was refused" % c)


def test_adults_may_have_a_pet_too():
    """A parent with a critter is a real opponent, and PvP is level-matched
    so it cannot be used to lean on a child."""
    reset_db()
    _member("p1", "Dad", role="parent")
    res = storage.create_pet("p1", "Bruiser")
    check('pet' in res, "a parent could not hatch: %s" % res)


def test_one_slot_until_a_second_is_earned():
    reset_db()
    _member("k1")
    storage.create_pet("k1", "First")
    second = storage.create_pet("k1", "Second")
    check(second.get('error'), "a second pet should not be free yet")
    check(storage.pet_slots("k1") == 1, "P1 ships exactly one free slot")


def test_unknown_parts_are_dropped_not_fatal():
    reset_db()
    _member("k1")
    res = storage.create_pet("k1", "Odd", {'body': 'nonesuch', 'top': 'fin'},
                             {'eyes': 'whatever', 'base_color': 'Chartreuse'})
    pet = res['pet']
    check(pet['species']['body'] in pet_render.parts('body'),
          "an unknown body must fall back, not persist")
    check(pet['species']['top'] == 'fin', "the valid half was thrown away too")
    check(len(res['rejected']) == 3, "expected three rejects: %s" % res['rejected'])


def test_a_name_is_tidied_never_lost():
    reset_db()
    _member("k1")
    pet = storage.create_pet("k1", "   Sir  Fluffy   ")['pet']
    check(pet['name'] == 'Sir Fluffy', "whitespace not tidied: %r" % pet['name'])
    long_name = storage.update_pet(pet['id'], {'name': 'x' * 200})['pet']['name']
    check(len(long_name) == storage.PET_NAME_MAX, "name not capped")
    kept = storage.update_pet(pet['id'], {'name': '   '})['pet']['name']
    check(kept, "an all-space name must fall back, never blank the creature")


# --- the earned half is not writable -------------------------------------

def test_level_training_and_moves_cannot_be_set_by_hand():
    reset_db()
    _member("k1")
    pet = storage.create_pet("k1", "Rocket")['pet']
    storage.update_pet(pet['id'], {'level': 99, 'training': {'atk': 999},
                                   'moves': ['cheat'], 'member_id': 'someone_else'})
    fresh = storage.get_pet(pet['id'])
    check(fresh['level'] == 1, "level was writable through the editor path")
    check(not fresh['training'], "training was writable through the editor path")
    check(not fresh['moves'], "moves were writable through the editor path")
    check(fresh['member_id'] == 'k1', "a pet was reassigned to another member")


# --- rule 3: never lost ---------------------------------------------------

def test_retiring_frees_the_slot_and_keeps_the_creature():
    reset_db()
    _member("k1")
    pet = storage.create_pet("k1", "Rocket")['pet']
    storage.retire_pet(pet['id'])
    check(len(storage.get_pets("k1")) == 0, "a retired pet is off the shelf")
    check(len(storage.get_pets("k1", include_retired=True)) == 1,
          "a retired pet must still exist (rule 3)")
    check('pet' in storage.create_pet("k1", "Second"),
          "retiring did not free the slot")


def test_a_retired_pet_cannot_shove_out_a_live_one():
    reset_db()
    _member("k1")
    first = storage.create_pet("k1", "First")['pet']
    storage.retire_pet(first['id'])
    storage.create_pet("k1", "Second")
    check(storage.retire_pet(first['id'], False) is None,
          "un-retiring over the slot limit must be refused, not silently allowed")
    check(storage.get_pet(first['id']) is not None, "the refusal ate the record")


def test_nothing_deletes_a_pet_on_its_own():
    """delete_pet exists so a person can say so. Nothing else may call it."""
    import subprocess
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = subprocess.run(
        [sys.executable, '-c',
         "import re,os,sys\n"
         "hits=[]\n"
         "for root,d,fs in os.walk(sys.argv[1]):\n"
         "    if 'tests' in root or '__pycache__' in root: continue\n"
         "    for f in fs:\n"
         "        if not f.endswith('.py'): continue\n"
         "        p=os.path.join(root,f)\n"
         "        for i,l in enumerate(open(p,encoding='utf-8',errors='ignore')):\n"
         "            if 'delete_pet(' in l and 'def delete_pet' not in l:\n"
         "                hits.append(p+':'+str(i+1))\n"
         "print('|'.join(hits))", here],
        capture_output=True, text=True)
    callers = [h for h in (out.stdout or '').strip().split('|') if h]
    check(len(callers) <= 1,
          "delete_pet has more than the one endpoint calling it: %s" % callers)


# --- the hand path --------------------------------------------------------

def test_the_pets_card_is_placeable_and_builds():
    from services import home_board
    keys = home_board.WIDGET_KEYS
    check('pets' in keys, "the pets card is not placeable from the board editor")
    check('pets' in home_board._BUILDERS, "the pets card has no builder")
    reset_db()
    _member("k1", "Ada")
    storage.create_pet("k1", "Rocket", {'body': 'tower', 'top': 'horns'}, {})
    import datetime
    data = home_board._BUILDERS['pets'](datetime.datetime.now(), config={})
    check(data and data['members'], "the pets tile drew nothing")
    row = [r for r in data['members'] if r['member_id'] == 'k1'][0]
    check(row['pet'] and row['pet']['svg'].startswith('<svg'),
          "the tile did not render the creature")


def test_an_empty_slot_is_still_a_door():
    """Someone who has never hatched has to be able to FIND the feature."""
    from services import home_board
    import datetime
    reset_db()
    _member("k1", "Ada")
    data = home_board._BUILDERS['pets'](datetime.datetime.now(), config={})
    check(data and any(r['pet'] is None for r in data['members']),
          "a member with no pet vanished from the card")
    off = home_board._BUILDERS['pets'](datetime.datetime.now(),
                                       config={'show_unhatched': False})
    check(off is None or not off['members'],
          "show_unhatched=False should hide a member with no creature")


def test_two_pets_on_the_card_do_not_collide():
    from services import home_board
    import datetime
    import re
    reset_db()
    _member("k1", "Ada")
    _member("k2", "Ben")
    for mid in ("k1", "k2"):
        storage.create_pet(mid, "Same", {'body': 'tower', 'top': 'horns'}, {})
    data = home_board._BUILDERS['pets'](datetime.datetime.now(), config={})
    svgs = [r['pet']['svg'] for r in data['members'] if r['pet']]
    ids = [set(re.findall(r'id="([^"]+)"', s)) for s in svgs]
    check(len(ids) == 2 and not (ids[0] & ids[1]),
          "two critters on one card share ids: %s" % (ids[0] & ids[1]))


def test_the_card_is_pageless():
    """Every tile type must be on the PAGELESS list or have a page. The pets
    card is all buttons, so it is doorless like the avatar editor."""
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'templates', 'home.html')
    src = open(p, encoding='utf-8').read()
    start = src.index('PAGELESS:')
    literal = src[start:src.index(']', start)]
    check("'pets'" in literal, "the pets card is neither pageless nor has a page")


def test_the_editor_is_mounted_where_kids_already_are():
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'templates')
    for page in ('app.html', 'home.html', 'chores.html', 'components/routines_page.html'):
        src = open(os.path.join(base, page), encoding='utf-8').read()
        check("components/pet_editor.html" in src,
              "%s can show a pet but cannot open the editor" % page)


def test_a_full_screen_editor_is_opaque_on_a_wall_panel():
    """The panel skin maps every `.bg-gray-950` surface to translucent glass
    with `!important`, so the wallpaper reads through the board. A full-screen
    editor got caught in that net: the avatar editor was see-through on a
    panel from the day it shipped, and no change to the overlay's own class
    could fix it -- the skin always won.

    `.panel-modal` is the opt-out. This guards all three halves of it: the
    token exists and has NO alpha, the rule that applies it exists, and both
    editors are actually wearing the class."""
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'templates')
    skin = open(os.path.join(base, 'panel_skin.html'), encoding='utf-8').read()
    check('--panel-modal' in skin, "the opaque modal token is gone")
    check('html[data-panel] .panel-modal' in skin,
          "the rule that beats the surface mapping is gone")
    for decl in re.findall(r'--panel-modal:\s*([^;]+);', skin):
        check('/' not in decl,
              "--panel-modal carries an alpha (%s) -- it must be opaque" % decl.strip())
    check(len(re.findall(r'--panel-modal:', skin)) >= 2,
          "the token must be defined for the light theme too, not just dark")
    for comp in ('avatar_editor.html', 'pet_editor.html'):
        src = open(os.path.join(base, 'components', comp), encoding='utf-8').read()
        check('panel-modal' in src,
              "%s lost its panel-modal class and is glass again on a wall" % comp)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failed = 0
    for t in tests:
        try:
            t()
            print("  ok   %s" % t.__name__)
        except Exception:
            failed += 1
            print("  FAIL %s" % t.__name__)
            traceback.print_exc()
    print("%d/%d passed" % (len(tests) - failed, len(tests)))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

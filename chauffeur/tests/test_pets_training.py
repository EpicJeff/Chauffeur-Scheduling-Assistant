"""Training, moves and the second slot -- what XP can and cannot buy.

The line this file guards is the one the design brief got wrong. It listed
"species unlocks" and "cosmetic parts" as XP sinks; rule 1 says identity is
free, and P1 shipped a test that every part and colour is choosable. The brief
was corrected rather than obeyed, so:

  * XP CANNOT buy any part of how a critter LOOKS. If a padlock ever appears
    on a body, a colour or an element, this fails.
  * XP CANNOT buy stat training either. Training points come with the level
    and are re-spendable for nothing, because training is the BUILD -- the
    thing level-matching deliberately preserves. Charging for it would mean
    the sibling with more XP has the better build, which is the whole thing
    this arc exists to avoid.
  * XP CAN buy breadth: moves from other elements (coverage) and a second
    critter.

Run from chauffeur/:  python tests/test_pets_training.py
"""
import atexit
import os
import shutil
import sys
import tempfile
import traceback

_TMP = tempfile.mkdtemp(prefix="chauffeur_pettrain_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import storage  # noqa: E402
from services import pet_battle  # noqa: E402
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


def _kid(mid="k1", xp=0, type_key='ember'):
    storage.add_member({"id": mid, "name": "Ada", "role": "child",
                        "color_code": "#3b82f6", "is_child": True})
    if xp:
        storage.grant_pet_xp(mid, xp, 'grant')
    return storage.create_pet(mid, "Rocket", {'body': 'wedge', 'top': 'horns'},
                              {}, type_key)['pet']


# --- what xp cannot buy ---------------------------------------------------

def test_looks_are_still_free_at_any_balance():
    """Zero XP, and every part and colour still choosable."""
    reset_db()
    pet = _kid(xp=0)
    check(storage.get_pet_xp_balance("k1") == 0, "the kid should be broke")
    for slot in ('body', 'top', 'eyes', 'mouth', 'pattern', 'cheeks'):
        for key in pet_render.parts(slot):
            out = storage.update_pet(pet['id'], {
                'species': {'body': key if slot == 'body' else 'wedge',
                            'top': key if slot == 'top' else 'horns'},
                'look': {slot: key} if slot not in ('body', 'top') else {}})
            check(not out['rejected'], "%s/%s cost something" % (slot, key))
    for c in pet_render.BASE_COLORS:
        check(not storage.update_pet(pet['id'],
                                     {'look': {'base_color': c}})['rejected'],
              "colour %s cost something" % c)
    for t in pet_catalog.keys():
        check(not storage.update_pet(pet['id'], {'type': t})['rejected'],
              "element %s cost something" % t)
    check(storage.get_pet_xp_balance("k1") == 0, "dressing up spent xp")


def test_training_is_free_and_re_spendable():
    reset_db()
    pet = _kid(xp=500)
    before = storage.get_pet_xp_balance("k1")
    for spread in ({'atk': 6}, {'spe': 6}, {'hp': 4, 'def': 2}, {}):
        storage.set_pet_training(pet['id'], spread)
    check(storage.get_pet_xp_balance("k1") == before,
          "changing a build cost xp -- only the cautious kid would experiment")


# --- training -------------------------------------------------------------

def test_training_points_arrive_with_the_level():
    reset_db()
    _kid(xp=0)
    check(storage.pet_training_budget("k1") == 0, "level 1 starts with none")
    storage.grant_pet_xp("k1", 320, 'grant')          # level 5
    check(storage.pet_level("k1") == 5, "expected level 5")
    check(storage.pet_training_budget("k1")
          == pet_battle.TRAINING_PER_LEVEL * 4,
          "budget does not track the level")


def test_over_budget_keeps_the_shape_you_asked_for():
    """Filling stats in tuple order until the budget ran out meant asking for
    999 attack got you 24 hp and no attack at all -- the child's actual intent
    thrown away because 'hp' happens to sort first."""
    reset_db()
    pet = _kid(xp=900)
    budget = storage.pet_training_budget("k1")
    res = storage.set_pet_training(pet['id'], {'atk': 999, 'spe': 500, 'hp': 500})
    t = res['pet']['training']
    check(res['scaled'], "an over-budget request should report being scaled")
    check(res['spent'] <= budget, "spent %d of %d" % (res['spent'], budget))
    check(t['atk'] > 0, "the stat actually asked for got nothing")
    check(t['atk'] >= t['spe'] >= t['hp'],
          "the shape was not preserved: %s" % t)
    check(t['def'] == t['spa'] == t['spd'] == 0,
          "points landed on stats nobody asked for: %s" % t)


def test_within_budget_is_taken_literally():
    reset_db()
    pet = _kid(xp=900)
    res = storage.set_pet_training(pet['id'], {'atk': 10, 'spe': 6})
    check(not res['scaled'], "an affordable build was scaled anyway")
    check(res['pet']['training']['atk'] == 10
          and res['pet']['training']['spe'] == 6,
          "a build inside the budget was altered: %s" % res['pet']['training'])


def test_no_single_stat_can_swallow_everything():
    reset_db()
    pet = _kid(xp=200000)                       # level 50, a big budget
    res = storage.set_pet_training(pet['id'], {'atk': 100000})
    check(res['pet']['training']['atk'] <= pet_battle.TRAINING_STAT_CAP,
          "the per-stat cap did not hold: %s" % res['pet']['training'])


def test_training_reaches_the_fight():
    reset_db()
    pet = _kid(xp=2000)
    storage.set_pet_training(pet['id'], {'spe': 40})
    fast = storage.pet_combatant_for(pet['id'])
    storage.set_pet_training(pet['id'], {'hp': 40})
    slow = storage.pet_combatant_for(pet['id'])
    check(fast['training']['spe'] > slow['training']['spe'],
          "training never reached the combatant")


# --- moves ----------------------------------------------------------------

def test_a_critter_knows_its_own_element_for_nothing():
    reset_db()
    pet = _kid(xp=0, type_key='tide')
    known = storage.pet_known_moves(pet)
    check(len(known) == 4, "expected four native moves, got %d" % len(known))
    for k in known:
        check(pet_catalog.move(k)['type'] == 'tide',
              "%s is not a tide move" % k)
    check(storage.get_pet_xp_balance("k1") == 0, "the free kit cost xp")


def test_coverage_is_the_purchase():
    reset_db()
    pet = _kid(xp=500, type_key='ember')
    before = storage.get_pet_xp_balance("k1")
    res = storage.learn_pet_move(pet['id'], 'bubblebeam')       # tide beats ember
    check('pet' in res, "could not learn a move: %s" % res)
    check(storage.get_pet_xp_balance("k1") == before - storage.PET_MOVE_COST,
          "the move did not cost what it says")
    check('bubblebeam' in storage.pet_known_moves(storage.get_pet(pet['id'])),
          "the move was not learned")
    check(storage.learn_pet_move(pet['id'], 'bubblebeam').get('error'),
          "the same move was sold twice")
    check(storage.learn_pet_move(pet['id'], 'emberfang').get('error'),
          "a native move was sold back to its owner")


def test_a_move_you_cannot_afford_is_refused_not_given():
    reset_db()
    pet = _kid(xp=10)
    res = storage.learn_pet_move(pet['id'], 'bubblebeam')
    check(res.get('error'), "a move was handed over for free")
    check(storage.get_pet_xp_balance("k1") == 10, "the balance moved anyway")


def test_only_known_moves_can_be_equipped():
    reset_db()
    pet = _kid(xp=500)
    res = storage.set_pet_moves(pet['id'], ['vinewhip', 'emberfang', 'nope'])
    check('vinewhip' in res['rejected'] and 'nope' in res['rejected'],
          "an unlearned move was equipped: %s" % res['pet']['moves'])
    check(res['pet']['moves'] == ['emberfang'], "the valid half was lost")


def test_a_critter_is_never_left_with_nothing_to_do():
    reset_db()
    pet = _kid(xp=0)
    res = storage.set_pet_moves(pet['id'], [])
    check(len(res['pet']['moves']) == 4,
          "an empty loadout was accepted: %s" % res['pet']['moves'])
    res = storage.set_pet_moves(pet['id'], ['nonsense'])
    check(len(res['pet']['moves']) == 4, "a junk loadout was accepted")


def test_equipped_moves_reach_the_fight():
    reset_db()
    pet = _kid(xp=500)
    storage.learn_pet_move(pet['id'], 'bubblebeam')
    storage.set_pet_moves(pet['id'], ['bubblebeam', 'emberfang'])
    c = storage.pet_combatant_for(pet['id'])
    check(c['moves'] == ['bubblebeam', 'emberfang'],
          "the fight used something else: %s" % c['moves'])


# --- the second slot ------------------------------------------------------

def test_the_second_critter_is_bought_not_given():
    reset_db()
    _kid(xp=100)
    check(storage.pet_slots("k1") == 1, "a second slot was free")
    check(storage.create_pet("k1", "Nope").get('error'), "a second pet slipped in")
    check(storage.buy_pet_slot("k1").get('error'), "a slot was sold on credit")
    storage.grant_pet_xp("k1", storage.PET_SLOT_COST, 'grant')
    res = storage.buy_pet_slot("k1")
    check(res.get('slots') == 2, "the slot was not granted: %s" % res)
    check('pet' in storage.create_pet("k1", "Pickle"), "the slot does not work")


def test_a_bought_slot_survives_and_does_not_cost_a_level():
    reset_db()
    _kid(xp=800)
    before = storage.pet_level("k1")
    storage.buy_pet_slot("k1")
    check(storage.pet_level("k1") == before,
          "buying a slot cost a level -- lifetime earned must drive it")
    check(storage.pet_slots("k1") == 2, "the slot did not persist")


def test_the_second_critter_arrives_at_your_own_level():
    """XP belongs to the member, so a new pet is not a weakling."""
    reset_db()
    _kid(xp=2000)
    storage.buy_pet_slot("k1")
    second = storage.create_pet("k1", "Pickle")['pet']
    check(second['level'] == storage.pet_level("k1"),
          "the second critter arrived at level %d" % second['level'])


# --- the hand paths -------------------------------------------------------

def test_the_card_shows_every_critter_and_offers_the_next():
    import datetime
    from services import home_board
    reset_db()
    _kid(xp=0)
    build = lambda: home_board._BUILDERS['pets'](datetime.datetime.now(), config={})
    kinds = lambda: [r['kind'] for r in build()['members']]
    check(kinds() == ['pet'], "unexpected rows with one pet: %s" % kinds())
    storage.grant_pet_xp("k1", storage.PET_SLOT_COST + 10, 'grant')
    check('buy' in kinds(), "an affordable slot was never offered: %s" % kinds())
    storage.buy_pet_slot("k1")
    check('empty' in kinds(), "a bought slot showed no way to fill it")
    storage.create_pet("k1", "Pickle")
    check(kinds() == ['pet', 'pet'], "two critters did not both draw: %s" % kinds())


def test_every_new_route_is_classified_and_reachable():
    from services import auth
    for method, path in (('POST', '/api/pets/slot'),
                         ('POST', '/api/pets/{pet_id}/training'),
                         ('POST', '/api/pets/{pet_id}/moves'),
                         ('POST', '/api/pets/{pet_id}/learn')):
        check(auth.resolve(method, path) is not None,
              "%s %s is unclassified" % (method, path))
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'templates', 'components')
    editor = open(os.path.join(base, 'pet_editor.html'), encoding='utf-8').read()
    for needle in ("'train'", "'moves'", 'saveTraining', 'saveMoves',
                   'learn(', 'buyPetSlot'):
        check(needle in editor, "the editor has no hand path for %s" % needle)
    card = open(os.path.join(base, 'board_tile_body.html'), encoding='utf-8').read()
    check('buyPetSlot' in card, "the card cannot buy a slot")


def run():
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
    raise SystemExit(run())

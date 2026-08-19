"""Battles as the app runs them: awards, the daily cap, and the replay.

What is being defended here, beyond the resolver's own tests:

  * A REPLAY IS REBUILT, NOT REMEMBERED. Only the seed and the two combatants
    are stored. If a stored fight ever replays differently, every battle a kid
    has ever watched quietly became a different battle.
  * THE CAP DOES NOT REFUSE THE FUN. Past the daily limit the fight still runs
    and the replay still plays; only the xp stops. Refusing a child the thing
    they built because they already played five times is a punishment.
  * Losing pays something. A child who fights and loses must not come away
    with nothing, or the only safe move is not to play.
  * Battle xp is still xp -- it never reaches the ledger that costs money.

Run from chauffeur/:  python tests/test_pet_battles_api.py
"""
import atexit
import os
import shutil
import sys
import tempfile
import traceback

_TMP = tempfile.mkdtemp(prefix="chauffeur_petbattle_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import storage  # noqa: E402
from services import pet_catalog  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def reset_db():
    with storage.db_lock:
        for name, val in list(vars(storage).items()):
            if name.endswith("_table"):
                val.truncate()


def _kid(mid="k1", xp=400):
    storage.add_member({"id": mid, "name": "Ada", "role": "child",
                        "color_code": "#3b82f6", "is_child": True})
    if xp:
        storage.grant_pet_xp(mid, xp, 'grant')
    return storage.create_pet(mid, "Rocket", {'body': 'wedge', 'top': 'horns'},
                              {'base_color': 'Coral'}, 'ember')['pet']


# --- the fight happens ----------------------------------------------------

def test_a_battle_runs_and_pays():
    reset_db()
    pet = _kid()
    before = storage.get_pet_xp_balance("k1")
    res = storage.run_pet_battle(pet['id'], 'npc:pebble', seed=7)
    check('battle' in res, "no battle came back: %s" % res)
    check(res['replay']['turns'], "the replay has no turns")
    check(res['awarded'] > 0, "the battle paid nothing")
    check(storage.get_pet_xp_balance("k1") == before + res['awarded'],
          "the award did not reach the ledger")


def test_every_opponent_can_actually_be_fought():
    reset_db()
    pet = _kid()
    for n in pet_catalog.npcs():
        res = storage.run_pet_battle(pet['id'], 'npc:%s' % n['key'], seed=3)
        check('battle' in res, "%s could not be fought: %s" % (n['key'], res))
        check(res['replay']['winner'] in ('a', 'b'),
              "%s produced no winner" % n['key'])


def test_losing_still_pays_something():
    """A child who tries and loses must not come away with nothing, or the
    only safe move is to never play."""
    reset_db()
    pet = _kid(xp=0)                        # level 1, against the last tier
    losses = 0
    for i in range(12):
        res = storage.run_pet_battle(pet['id'], 'npc:monolith', seed=i)
        if not res['battle']['won'] and not res['capped']:
            losses += 1
            check(res['awarded'] > 0,
                  "a loss paid nothing at all")
    check(losses, "expected a level 1 pet to lose to the top tier at least once")


def test_an_unknown_pet_or_opponent_is_refused_not_guessed():
    reset_db()
    pet = _kid()
    check(storage.run_pet_battle('nope', 'npc:pebble').get('error'),
          "a battle ran for a pet that does not exist")
    check(storage.run_pet_battle(pet['id'], 'npc:nobody').get('error'),
          "a battle ran against an opponent that does not exist")


# --- the replay -----------------------------------------------------------

def test_a_stored_battle_replays_identically_forever():
    reset_db()
    pet = _kid()
    res = storage.run_pet_battle(pet['id'], 'npc:fizz', seed=99)
    bid = res['battle']['id']
    for _ in range(3):
        check(storage.replay_pet_battle(bid) == res['replay'],
              "a stored battle replayed differently")


def test_only_the_seed_and_the_combatants_are_stored():
    reset_db()
    pet = _kid()
    res = storage.run_pet_battle(pet['id'], 'npc:fizz', seed=99)
    row = storage.get_pet_battle(res['battle']['id'])
    check('turns' not in row, "the frames were stored -- store the seed instead")
    check(row.get('seed') is not None and row.get('a_in') and row.get('b_in'),
          "the row cannot rebuild its own fight")
    import json
    check(len(json.dumps(row)) < 4000,
          "a battle row is %d bytes" % len(json.dumps(row)))


def test_restyling_a_pet_does_not_rewrite_an_old_fight():
    """The snapshot is the point: a kid who recolours their critter must not
    retroactively change a battle they already watched."""
    reset_db()
    pet = _kid()
    res = storage.run_pet_battle(pet['id'], 'npc:fizz', seed=5)
    storage.update_pet(pet['id'], {'species': {'body': 'blob', 'top': 'nub'},
                                   'type': 'tide'})
    check(storage.replay_pet_battle(res['battle']['id']) == res['replay'],
          "restyling the pet changed a fight that already happened")


# --- the cap --------------------------------------------------------------

def test_the_cap_stops_the_xp_and_never_the_fight():
    reset_db()
    pet = _kid()
    cap = storage.pet_pve_cap()
    for i in range(cap):
        res = storage.run_pet_battle(pet['id'], 'npc:pebble', seed=i)
        check(not res['capped'], "capped early, at battle %d of %d" % (i + 1, cap))
    after = storage.run_pet_battle(pet['id'], 'npc:pebble', seed=99)
    check(after['capped'], "the cap never engaged")
    check(after['awarded'] == 0, "a capped battle still paid %d" % after['awarded'])
    check(after['replay']['turns'], "the cap refused the fight itself")
    check(after['replay']['winner'] in ('a', 'b'),
          "a capped battle produced no result")


def test_the_cap_is_per_member_and_per_day():
    reset_db()
    pet = _kid()
    storage.add_member({"id": "k2", "name": "Ben", "role": "child",
                        "color_code": "#f43f5e", "is_child": True})
    other = storage.create_pet("k2", "Pickle")['pet']
    for i in range(storage.pet_pve_cap() + 2):
        storage.run_pet_battle(pet['id'], 'npc:pebble', seed=i)
    res = storage.run_pet_battle(other['id'], 'npc:pebble', seed=1)
    check(not res['capped'], "one child's battles used up another's allowance")


def test_a_zero_cap_is_a_household_choice_not_a_crash():
    reset_db()
    pet = _kid()
    storage.patch_settings({'pet_pve_daily_cap': 0})
    res = storage.run_pet_battle(pet['id'], 'npc:pebble', seed=1)
    check(res['capped'] and res['awarded'] == 0, "a zero cap still paid out")
    check(res['replay']['turns'], "a zero cap refused the fight")
    storage.patch_settings({'pet_pve_daily_cap': storage.PET_PVE_DAILY_CAP})


# --- the membrane, again --------------------------------------------------

def test_grinding_the_arena_cannot_print_money():
    reset_db()
    pet = _kid()
    before = storage.get_points_balance("k1")
    for i in range(30):
        storage.run_pet_battle(pet['id'], 'npc:pebble', seed=i)
    check(storage.get_points_balance("k1") == before,
          "battle winnings reached the ledger that costs a parent money")
    check(storage.get_pet_xp_balance("k1") > 0, "no xp was earned at all")


# --- the endpoints and their doors ---------------------------------------

def test_the_endpoints_answer():
    reset_db()
    import main
    pet = _kid()
    ops = main.pet_opponents_endpoint()['opponents']
    check(len(ops) >= 6, "only %d opponents offered" % len(ops))
    check(all(o['svg'].startswith('<svg') for o in ops),
          "an opponent has no picture")
    out = main.pet_battle_endpoint(
        main.PetBattleRequest(pet_id=pet['id'], opponent='npc:pebble', seed=1))
    check(out['replay']['turns'], "the endpoint returned no replay")
    hist = main.pet_battles_endpoint(member_id="k1")
    check(hist['battles'] and hist['cap'] and hist['used_today'] == 1,
          "the history is wrong: %s" % {k: v for k, v in hist.items() if k != 'battles'})
    again = main.pet_battle_replay_endpoint(out['battle']['id'])
    check(again['replay'] == out['replay'], "the replay endpoint disagrees")


def test_pvp_is_refused_until_it_is_built():
    """P6 opens this. Until a sibling can consent to a challenge, the endpoint
    must say no rather than quietly fight on their behalf."""
    reset_db()
    import main
    from fastapi import HTTPException
    pet = _kid()
    storage.add_member({"id": "k2", "name": "Ben", "role": "child",
                        "color_code": "#f43f5e", "is_child": True})
    other = storage.create_pet("k2", "Pickle")['pet']
    try:
        main.pet_battle_endpoint(
            main.PetBattleRequest(pet_id=pet['id'], opponent=other['id']))
        raise AssertionError("a sibling was dragged into a fight without consent")
    except HTTPException as e:
        check(e.status_code == 400, "wrong refusal: %s" % e.status_code)


def test_there_is_a_way_in_by_hand():
    """Every agent capability needs a hand path -- and so does every feature
    reachable only from an overlay somebody has to know exists."""
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'templates')
    for page in ('app.html', 'home.html', 'chores.html', 'routines.html'):
        src = open(os.path.join(base, page), encoding='utf-8').read()
        check("components/pet_battle.html" in src,
              "%s cannot open the arena" % page)
    card = open(os.path.join(base, 'components', 'board_tile_body.html'),
                encoding='utf-8').read()
    check('openPetBattle' in card, "the pets card has no way into a battle")
    editor = open(os.path.join(base, 'components', 'pet_editor.html'),
                  encoding='utf-8').read()
    check('openPetBattle' in editor, "the editor has no way into a battle")


def test_every_battle_route_is_classified():
    from services import auth
    for method, path in (('POST', '/api/pets/battle'),
                         ('GET', '/api/pets/opponents'),
                         ('GET', '/api/pets/battles'),
                         ('GET', '/api/pets/battles/{battle_id}'),
                         ('GET', '/api/pets/xp')):
        check(auth.resolve(method, path) is not None,
              "%s %s is unclassified" % (method, path))


def run():
    # Not `main` -- these tests import the app module of that name.
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

"""The pet XP ledger, and the membrane between it and real money.

Rule 2 is the one this file exists for: **XP is not points, and the membrane
is one-way.** Points redeem for things a parent actually buys. If the two
ledgers ever touch, two bad things happen at once -- a child starts choosing
between levelling their critter and the family movie-night pool, and battle
winnings (P6) become a way to print money out of a parent's wallet.

Also here:
  * routines finally have a sink, and ticking a box is not a faucet
  * unticking never claws anything back (rule 3)
  * level comes from LIFETIME earned, so spending cannot cost a level
  * every pet a member owns shares that level

Run from chauffeur/:  python tests/test_pets_xp.py
"""
import atexit
import os
import shutil
import sys
import tempfile
import traceback
from datetime import date, timedelta

_TMP = tempfile.mkdtemp(prefix="chauffeur_petxp_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import storage  # noqa: E402
from services import pet_catalog  # noqa: E402

TODAY = date.today().isoformat()


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def reset_db():
    with storage.db_lock:
        for name, val in list(vars(storage).items()):
            if name.endswith("_table"):
                val.truncate()


def _member(mid, name="Kid", role="child"):
    storage.add_member({"id": mid, "name": name, "role": role,
                        "color_code": "#3b82f6", "is_child": role == "child"})


def _verified_chore(cid, member_id, points=10, recurrence='once'):
    storage.add_chore({'id': cid, 'title': 'Dishes', 'points': points,
                       'recurrence': recurrence, 'state': 'open'})
    storage.claim_chore(cid, member_id)
    storage.mark_chore_done(cid, member_id)
    return storage.verify_chore(cid, 'p1')


# --- the membrane ---------------------------------------------------------

def test_a_chore_mints_both_and_neither_is_taken_from_the_other():
    reset_db()
    _member("k1"); _member("p1", "Dad", role="parent")
    res = _verified_chore('c1', 'k1', points=10)
    check(res['awarded'] == 10, "points stopped being awarded: %s" % res)
    check(res['pet_xp'] == 10, "no xp minted alongside the points: %s" % res)
    check(storage.get_points_balance("k1") == 10, "points balance is wrong")
    check(storage.get_pet_xp_balance("k1") == 10, "xp balance is wrong")


def test_spending_xp_cannot_touch_points_and_the_reverse():
    reset_db()
    _member("k1"); _member("p1", "Dad", role="parent")
    _verified_chore('c1', 'k1', points=50)
    storage.grant_pet_xp("k1", -30, 'spend', note='training')
    check(storage.get_points_balance("k1") == 50,
          "spending xp moved the points balance -- the membrane leaks")
    check(storage.get_pet_xp_balance("k1") == 20, "xp was not spent")
    # and the ledgers hold each other's rows nowhere
    xp_rows = storage.get_pet_xp_ledger("k1", limit=99)
    pt_rows = storage.get_points_ledger("k1", limit=99)
    check(len(xp_rows) == 2 and len(pt_rows) == 1,
          "rows landed in the wrong ledger: xp=%d points=%d"
          % (len(xp_rows), len(pt_rows)))


def test_battle_style_xp_never_reaches_the_points_ledger():
    """P6 pays xp for winning. If that could ever become points, grinding an
    NPC would be a way to print money out of a parent's wallet."""
    reset_db()
    _member("k1")
    before = storage.get_points_balance("k1")
    for i in range(20):
        storage.grant_pet_xp("k1", 30, 'battle', ref_id='b%d' % i)
    check(storage.get_pet_xp_balance("k1") == 600, "battle xp did not accrue")
    check(storage.get_points_balance("k1") == before,
          "battle winnings reached the real-money ledger")


# --- routines: a sink at last, and not a faucet ---------------------------

def test_a_routine_finally_buys_something():
    reset_db()
    _member("k1")
    storage.add_routine({'id': 'r1', 'member_id': 'k1', 'title': 'Teeth'})
    storage.set_routine_check('r1', 'k1', TODAY, True)
    check(storage.get_pet_xp_balance("k1") > 0,
          "a kept routine still earns nothing -- the sink is not wired up")


def test_ticking_a_box_all_afternoon_is_not_a_faucet():
    reset_db()
    _member("k1")
    storage.add_routine({'id': 'r1', 'member_id': 'k1', 'title': 'Teeth'})
    storage.add_routine({'id': 'r2', 'member_id': 'k1', 'title': 'Bed'})
    for _ in range(25):
        storage.set_routine_check('r1', 'k1', TODAY, True)
        storage.set_routine_check('r1', 'k1', TODAY, False)
    storage.set_routine_check('r1', 'k1', TODAY, True)
    rows = [e for e in storage.get_pet_xp_ledger("k1", limit=99)
            if e['reason'] == 'routine']
    check(len(rows) == 1,
          "26 taps of one box minted %d rows -- that is a faucet" % len(rows))


def test_unticking_never_claws_anything_back():
    """Rule 3. A box tapped by accident must not cost a child anything."""
    reset_db()
    _member("k1")
    storage.add_routine({'id': 'r1', 'member_id': 'k1', 'title': 'Teeth'})
    storage.set_routine_check('r1', 'k1', TODAY, True)
    earned = storage.get_pet_xp_balance("k1")
    storage.set_routine_check('r1', 'k1', TODAY, False)
    check(storage.get_pet_xp_balance("k1") == earned,
          "unticking took xp back -- nothing earned is ever taken away")


def test_a_new_day_earns_again():
    reset_db()
    _member("k1")
    storage.add_routine({'id': 'r1', 'member_id': 'k1', 'title': 'Teeth'})
    storage.set_routine_check('r1', 'k1', TODAY, True)
    first = storage.get_pet_xp_balance("k1")
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    storage.set_routine_check('r1', 'k1', yesterday, True)
    check(storage.get_pet_xp_balance("k1") > first,
          "the idempotency guard is keyed too loosely -- a second day earned nothing")


def test_the_whole_day_pays_a_bonus_once():
    reset_db()
    _member("k1")
    storage.add_routine({'id': 'r1', 'member_id': 'k1', 'title': 'Teeth'})
    storage.add_routine({'id': 'r2', 'member_id': 'k1', 'title': 'Bed'})
    storage.set_routine_check('r1', 'k1', TODAY, True)
    bonus = [e for e in storage.get_pet_xp_ledger("k1", limit=99)
             if e['reason'] == 'routine_all']
    check(not bonus, "the day bonus paid with one of two items done")
    storage.set_routine_check('r2', 'k1', TODAY, True)
    for _ in range(5):
        storage.set_routine_check('r2', 'k1', TODAY, False)
        storage.set_routine_check('r2', 'k1', TODAY, True)
    bonus = [e for e in storage.get_pet_xp_ledger("k1", limit=99)
             if e['reason'] == 'routine_all']
    check(len(bonus) == 1,
          "the full-day bonus paid %d times" % len(bonus))


def test_a_member_with_no_routines_gets_no_free_bonus():
    reset_db()
    _member("k1")
    storage.add_routine({'id': 'r1', 'member_id': 'k2', 'title': 'Someone else'})
    storage.set_routine_check('r1', 'k2', TODAY, True)
    check(storage.get_pet_xp_balance("k1") == 0,
          "xp landed on the wrong member")


# --- a recurring chore keeps paying --------------------------------------

def test_a_recurring_chore_pays_every_time_like_points_do():
    """The idempotency guard is for routines, NOT chores. A daily chore is
    real work again tomorrow, and points mint again -- xp has to match, or
    every recurring chore silently stops paying after day one."""
    reset_db()
    _member("k1"); _member("p1", "Dad", role="parent")
    first = _verified_chore('c1', 'k1', points=10, recurrence='daily')
    storage.reopen_chore('c1')
    storage.claim_chore('c1', 'k1')
    storage.mark_chore_done('c1', 'k1')
    second = storage.verify_chore('c1', 'p1')
    check(first['pet_xp'] == 10 and second['pet_xp'] == 10,
          "a recurring chore stopped paying xp: %s then %s"
          % (first['pet_xp'], second['pet_xp']))
    check(storage.get_pet_xp_balance("k1") == 20, "xp did not accrue twice")


def test_a_parent_earns_xp_even_though_they_earn_no_points():
    """Points are children-only because they cost a parent money. XP costs
    nothing -- and a parent's critter has to be able to level, or it drags
    every level-matched fight down to its own floor."""
    reset_db()
    _member("p1", "Dad", role="parent")
    _member("p2", "Mum", role="parent")
    res = _verified_chore('c1', 'p1', points=10)
    check(res['awarded'] == 0, "a parent was awarded points")
    check(res['pet_xp'] == 10, "a parent earned no pet xp: %s" % res)


# --- levels ---------------------------------------------------------------

def test_level_comes_from_lifetime_and_spending_cannot_cost_one():
    reset_db()
    _member("k1")
    storage.grant_pet_xp("k1", 500, 'grant')
    before = storage.pet_level("k1")
    check(before >= 5, "500 xp should be a few levels in, got %d" % before)
    storage.grant_pet_xp("k1", -480, 'spend')
    check(storage.pet_level("k1") == before,
          "spending xp cost a level -- lifetime earned must drive the level")
    check(storage.get_pet_xp_balance("k1") == 20, "the spend did not happen")


def test_every_pet_a_member_owns_shares_the_level():
    reset_db()
    _member("k1")
    storage.grant_pet_xp("k1", 320, 'grant')
    first = storage.create_pet("k1", "First")['pet']
    storage.retire_pet(first['id'])
    second = storage.create_pet("k1", "Second")['pet']
    check(first['level'] == second['level'] == storage.pet_level("k1"),
          "a second critter did not inherit the level its owner earned")
    check(second['level'] >= 5, "320 xp should be level 5, got %d" % second['level'])


def test_a_stored_level_can_never_drift():
    reset_db()
    _member("k1")
    pet = storage.create_pet("k1", "Rocket")['pet']
    with storage.db_lock:
        storage.pets_table.update({'level': 99}, storage.Query().id == pet['id'])
    check(storage.get_pet(pet['id'])['level'] == 1,
          "a level written straight into the table survived a read")


def test_rates_are_tunable_without_touching_code():
    reset_db()
    _member("k1"); _member("p1", "Dad", role="parent")
    storage.patch_settings({'pet_xp_per_chore_point': 2.0})
    res = _verified_chore('c1', 'k1', points=10)
    check(res['pet_xp'] == 20, "the rate setting was ignored: %s" % res)
    storage.patch_settings({'pet_xp_per_chore_point': 1.0})


def test_the_curve_is_monotonic_and_has_no_gaps():
    seen = 1
    for xp in range(0, 3000, 7):
        lvl = pet_catalog.level_for_xp(xp)
        check(lvl >= seen, "level went backwards at %d xp" % xp)
        check(lvl - seen <= 1, "level skipped a step at %d xp" % xp)
        seen = lvl
        p = pet_catalog.level_progress(xp)
        check(0.0 <= p['ratio'] <= 1.0, "ratio out of range at %d xp" % xp)
        check(p['level'] == lvl, "progress disagrees with level_for_xp")
    check(pet_catalog.level_for_xp(10 ** 9) == pet_catalog.LEVEL_MAX,
          "the level cap does not hold")


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

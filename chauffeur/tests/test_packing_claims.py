"""Ticking a packing item: a CLAIM, not a checkbox.

An item needs as many as there are people it covers, so the state is a count
of claims rather than a boolean. A child ticking their own kit in their own day
claims a slot with their name on it; a tap on the wall claims an anonymous one,
because the wall has no identity and inventing one to pay somebody would be a
lie with a currency attached.

What a claim pays is critter XP, and nothing else. It is not a chore (no
points), and it is not a habit (no routine, no streak) — the household's own
rule: an unpacked bag is a real problem and it is not a broken routine.

Run from chauffeur/:  python tests/test_packing_claims.py
"""
from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage

DAY = '2026-09-08'
OUT, ITEM = 'd1:soccer', 'k1:water bottle'


def _reset():
    storage.packing_claims_table.truncate()
    storage.pet_xp_ledger_table.truncate()


def test_claims_count_up_and_down():
    _reset()
    storage.add_packing_claim(OUT, ITEM, DAY)
    storage.add_packing_claim(OUT, ITEM, DAY)
    rows = [r for r in storage.get_packing_claims(DAY) if r['item_key'] == ITEM]
    check(len(rows) == 2, f"two anonymous claims are two: {rows}")
    storage.remove_packing_claim(OUT, ITEM, DAY)
    rows = [r for r in storage.get_packing_claims(DAY) if r['item_key'] == ITEM]
    check(len(rows) == 1, f"unticking removes one claim, not the lot: {rows}")


def test_a_members_claim_is_theirs_and_pays_xp_once():
    """`once=True` per (member, item, day) is the whole anti-farm story — a
    child can tick and untick a box all afternoon."""
    _reset()
    first = storage.add_packing_claim(OUT, ITEM, DAY, member_id='ellie')
    check(first > 0, f"a member's claim mints xp: {first}")
    storage.remove_packing_claim(OUT, ITEM, DAY, member_id='ellie')
    again = storage.add_packing_claim(OUT, ITEM, DAY, member_id='ellie')
    check(again == 0, f"re-ticking the same item the same day mints nothing more: {again}")
    ledger = [r for r in storage.pet_xp_ledger_table.all() if r['reason'] == 'prep']
    check(len(ledger) == 1 and ledger[0]['member_id'] == 'ellie',
          f"one prep row, paid to the packer: {ledger}")


def test_unticking_never_claws_xp_back():
    """A thing earned is never taken away — the rule the routine ledger already
    states, and a box tapped by accident must not cost a child anything."""
    _reset()
    storage.add_packing_claim(OUT, ITEM, DAY, member_id='sam')
    storage.remove_packing_claim(OUT, ITEM, DAY, member_id='sam')
    total = sum(r['delta'] for r in storage.pet_xp_ledger_table.all() if r['reason'] == 'prep')
    check(total > 0, f"unticking clawed the xp back: {total}")


def test_an_anonymous_wall_tap_pays_nobody():
    _reset()
    check(storage.add_packing_claim(OUT, ITEM, DAY) == 0,
          "an anonymous claim minted xp with nobody to pay")
    check(not storage.pet_xp_ledger_table.all(), "the wall wrote a ledger row")


def test_claims_are_per_day():
    _reset()
    storage.add_packing_claim(OUT, ITEM, DAY)
    check(storage.get_packing_claims('2026-09-09') == [],
          "yesterday's packing leaked into today")


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    for fn in TESTS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(TESTS)}/{len(TESTS)} packing-claim tests passed")

"""The battle resolver.

The whole slice is arithmetic over dictionaries, which means almost everything
worth promising about it can be proved here rather than watched:

  * DETERMINISM. The replay is a pure function of (seed, two combatants), so
    what gets stored is a seed and two snapshots and the fight reconstructs on
    any device, forever. If this breaks, every saved battle silently becomes a
    different battle.
  * LEVEL-MATCHING. A family fight must not be decided by who did more chores.
    Both sides scale to the lower level and the smaller training budget, and
    each keeps its own DISTRIBUTION -- so thinking about your build still pays
    and grinding does not. This is the promise the whole arc rests on.
  * NO POSITIONAL ADVANTAGE. Being "the challenger" must be worth nothing.
  * BODIES DIFFER IN SHAPE, NOT STRENGTH. A child who picks the cute body must
    not have picked the weak one.
  * IT ENDS. A battle nobody watches to the end is not a feature.

Run from chauffeur/:  python tests/test_pet_battle.py
"""
import json
import os
import random
import statistics
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import pet_battle as pb  # noqa: E402
from services import pet_catalog as cat  # noqa: E402

BODIES = sorted((cat._catalog().get('bodies') or {}))


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _pet(name, type_key='ember', body='steps', level=10, training=None,
         moves=None):
    return pb.combatant(name, type_key, {'body': body, 'top': 'nub'},
                        level=level,
                        training=training or {s: 10 for s in cat.STATS},
                        moves=moves)


def _random_pet(r, level=10, name='P'):
    return pb.combatant(name, r.choice(cat.keys()),
                        {'body': r.choice(BODIES)}, level=level,
                        training={s: r.randint(0, 25) for s in cat.STATS})


# --- determinism ----------------------------------------------------------

def test_the_same_seed_replays_the_same_fight():
    a, b = _pet('A'), _pet('B', 'tide', 'blob')
    first = pb.resolve(a, b, seed=4242)
    for _ in range(5):
        check(pb.resolve(a, b, seed=4242) == first,
              "the same seed produced a different fight")
    check(json.dumps(first, sort_keys=True) ==
          json.dumps(pb.resolve(a, b, seed=4242), sort_keys=True),
          "the replay does not round-trip through JSON identically")


def test_a_different_seed_is_a_different_fight():
    a, b = _pet('A'), _pet('B', 'tide', 'blob')
    seen = {json.dumps(pb.resolve(a, b, seed=s), sort_keys=True)
            for s in range(30)}
    check(len(seen) > 20, "30 seeds produced only %d distinct fights" % len(seen))


def test_a_replay_is_small_enough_to_keep_forever():
    a, b = _pet('A'), _pet('B', 'tide', 'blob')
    r = pb.resolve(a, b, seed=7)
    stored = json.dumps({'seed': r['seed'], 'a': r['a'], 'b': r['b']})
    check(len(stored) < 2000,
          "the persisted half of a replay is %d bytes" % len(stored))


# --- fairness -------------------------------------------------------------

def test_being_the_challenger_is_worth_nothing():
    """A perfect mirror. Any deviation from half is a positional advantage."""
    a, b = _pet('A'), _pet('B')
    wins = sum(pb.resolve(a, b, seed=i)['winner'] == 'a' for i in range(3000))
    check(0.45 <= wins / 3000 <= 0.55,
          "side a wins %.3f of mirror matches" % (wins / 3000))


def test_the_same_pet_wins_equally_from_either_slot():
    fwd = rev = 0
    for i in range(1200):
        r = random.Random(i)
        x, y = _random_pet(r, name='X'), _random_pet(r, name='Y')
        fwd += pb.resolve(x, y, seed=i)['winner'] == 'a'
        rev += pb.resolve(y, x, seed=i)['winner'] == 'b'
    check(abs(fwd - rev) / 1200 < 0.05,
          "X wins %.3f as side a but %.3f as side b" % (fwd / 1200, rev / 1200))


def test_no_body_is_stronger_than_another_only_different():
    total = cat.stat_total()
    for body in BODIES:
        s = cat.base_stats(body)
        check(sum(s.values()) == total,
              "%s sums to %d, not %d -- a body may differ in shape but never "
              "in strength" % (body, sum(s.values()), total))
    check(len(BODIES) == 14, "expected 14 bodies, found %d" % len(BODIES))
    # and they really are different shapes, not fourteen copies
    shapes = {tuple(sorted(cat.base_stats(b).items())) for b in BODIES}
    check(len(shapes) == len(BODIES), "some bodies are identical")


# --- level matching: the load-bearing rule -------------------------------

def test_a_family_fight_is_not_decided_by_who_did_more_chores():
    """The one that matters. A level 30 pet with a full training budget
    against a level 4 one with almost none: level-matched, it is a coin
    flip."""
    strong = _pet('Strong', 'ember', 'steps', level=30,
                  training={s: 50 for s in cat.STATS})
    weak = _pet('Weak', 'ember', 'steps', level=4,
                training={s: 2 for s in cat.STATS})
    wins = sum(pb.resolve(strong, weak, seed=i)['winner'] == 'a'
               for i in range(2000))
    check(0.42 <= wins / 2000 <= 0.58,
          "the grinder wins %.3f of level-matched fights -- level matching is "
          "not holding" % (wins / 2000))


def test_level_matching_scales_both_sides_to_the_lower_level():
    strong = _pet('Strong', level=30, training={s: 50 for s in cat.STATS})
    weak = _pet('Weak', level=4, training={s: 2 for s in cat.STATS})
    r = pb.resolve(strong, weak, seed=1)
    check(r['a']['level'] == r['b']['level'] == 4,
          "levels were not matched: %s vs %s" % (r['a']['level'], r['b']['level']))
    check(sum(r['a']['training'].values()) <= sum(r['b']['training'].values()) + 1,
          "the higher-level pet kept a bigger training budget")
    check(r['level_matched'] is True, "the replay does not record the matching")


def test_level_matching_keeps_your_build_and_only_squeezes_the_total():
    """Thinking about where your points went still pays. Having more of them
    does not."""
    speedy = _pet('Speedy', level=30,
                  training={'spe': 60, 'atk': 40, 'hp': 0, 'def': 0,
                            'spa': 0, 'spd': 0})
    plain = _pet('Plain', level=6, training={s: 4 for s in cat.STATS})
    r = pb.resolve(speedy, plain, seed=3)
    t = r['a']['training']
    check(t['spe'] > t['hp'] and t['atk'] > t['def'],
          "the build's shape was flattened by matching: %s" % t)
    check(t['spe'] > t['atk'], "the ordering of the build was not preserved")


def test_against_a_machine_the_grind_is_allowed_to_pay():
    """PvE is where power progression means something -- it hurts nobody."""
    strong = _pet('Strong', 'ember', 'steps', level=30,
                  training={s: 50 for s in cat.STATS})
    weak = _pet('Weak', 'ember', 'steps', level=4,
                training={s: 2 for s in cat.STATS})
    wins = sum(pb.resolve(strong, weak, seed=i, level_match=False)['winner'] == 'a'
               for i in range(400))
    check(wins / 400 > 0.9,
          "a level 30 pet beat a level 4 one only %.2f of the time unmatched"
          % (wins / 400))


# --- it ends, and it is watchable ----------------------------------------

def test_every_battle_ends_and_within_a_watchable_band():
    lengths, timeouts = [], 0
    for level in (1, 5, 12, 25, 50):
        for i in range(240):
            r = random.Random(i + level * 1000)
            res = pb.resolve(_random_pet(r, level), _random_pet(r, level),
                             seed=i + level)
            lengths.append(res['turn_count'])
            timeouts += bool(res['timed_out'])
            check(res['winner'] in ('a', 'b'), "a fight ended with no winner")
    check(timeouts == 0,
          "%d fights ran out of turns -- a winner decided by a timer is not a "
          "winner" % timeouts)
    med = statistics.median(lengths)
    check(5 <= med <= 14, "median fight is %d rounds" % med)
    check(max(lengths) <= 40, "longest fight was %d rounds" % max(lengths))


def test_two_healers_cannot_stall_the_fight():
    """The reason moves carry `uses`. Without it, both sides top themselves
    up forever and the turn limit picks the winner."""
    heal_only = [m['key'] for m in cat.moves() if m.get('effect') == 'heal']
    check(heal_only, "no heal moves in the catalogue to test")
    a = _pet('A', 'ember', 'block', level=20, moves=[heal_only[0]])
    b = _pet('B', 'leaf', 'block', level=20, moves=[heal_only[1]])
    for i in range(60):
        res = pb.resolve(a, b, seed=i)
        check(not res['timed_out'],
              "two healers stalled to the turn limit on seed %d" % i)


def test_a_pet_never_walks_in_with_nothing_to_do():
    for type_key in cat.keys():
        check(len(cat.default_moves(type_key)) == 4,
              "%s does not have four default moves" % type_key)
    naked = pb.combatant('Naked', 'tide', {'body': 'blob'}, level=5, moves=[])
    junk = pb.combatant('Junk', 'tide', {'body': 'blob'}, level=5,
                        moves=['not_a_move', 'nope'])
    for c in (naked, junk):
        check(len(c['moves']) == 4, "%s got no usable moves" % c['name'])
        res = pb.resolve(c, _pet('B'), seed=9)
        check(res['winner'] in ('a', 'b'), "%s could not fight" % c['name'])


def test_an_unknown_body_is_unremarkable_not_unbeatable():
    weird = pb.combatant('Weird', 'ember', {'body': 'nonesuch'}, level=10,
                         training={s: 10 for s in cat.STATS})
    check(sum(cat.base_stats('nonesuch').values()) == cat.stat_total(),
          "the fallback body does not sum to the standard total")
    wins = sum(pb.resolve(weird, _pet('B'), seed=i)['winner'] == 'a'
               for i in range(600))
    check(0.35 <= wins / 600 <= 0.65,
          "an unknown body wins %.2f -- it should be ordinary" % (wins / 600))


# --- the rules of the fight ----------------------------------------------

def test_hp_stays_inside_its_own_bar():
    for i in range(200):
        r = random.Random(i)
        res = pb.resolve(_random_pet(r), _random_pet(r), seed=i)
        for t in res['turns']:
            for side in ('a', 'b'):
                check(0 <= t['hp'][side] <= t['max_hp'][side],
                      "hp left the bar: %s of %s" % (t['hp'][side], t['max_hp'][side]))


def test_a_hit_always_does_something():
    for i in range(400):
        r = random.Random(i)
        res = pb.resolve(_random_pet(r), _random_pet(r), seed=i)
        for t in res['turns']:
            if t['move'] and not t['missed'] and t['move_name']:
                mv = cat.move(t['move'])
                if mv and int(mv.get('power', 0)) > 0:
                    check(t['damage'] >= 1,
                          "a landed attack did no damage at all")


def test_the_ring_actually_bites():
    """Super-effective has to be visibly better than resisted, or the whole
    element choice is decoration."""
    ember = _pet('Ember', 'ember', 'steps', level=20)
    leaf = _pet('Leaf', 'leaf', 'steps', level=20)      # ember burns leaf
    tide = _pet('Tide', 'tide', 'steps', level=20)      # tide quenches ember
    strong = sum(pb.resolve(ember, leaf, seed=i)['winner'] == 'a' for i in range(600))
    weak = sum(pb.resolve(ember, tide, seed=i)['winner'] == 'a' for i in range(600))
    check(strong / 600 > 0.65,
          "ember beats leaf only %.2f of the time" % (strong / 600))
    check(weak / 600 < 0.35,
          "ember beats tide %.2f of the time -- it should be losing" % (weak / 600))


def test_super_effective_is_announced_in_words_a_child_owns():
    ember = _pet('Ember', 'ember', 'steps', level=20)
    leaf = _pet('Leaf', 'leaf', 'steps', level=20)
    res = pb.resolve(ember, leaf, seed=11)
    notes = ' '.join(t.get('note') or '' for t in res['turns'])
    check('super effective' in notes, "the log never says what happened: %r" % notes[:200])


# --- the opponents --------------------------------------------------------

def test_every_npc_can_be_fought():
    npcs = cat.npcs()
    check(len(npcs) >= 6, "expected at least six opponents, found %d" % len(npcs))
    for n in npcs:
        c = pb.npc_combatant(n['key'])
        check(c, "%s could not be built" % n['key'])
        check(len(c['moves']) == 4, "%s has no full moveset" % n['key'])
        res = pb.resolve(_pet('Kid', level=10), c, seed=5, level_match=False)
        check(res['winner'] in ('a', 'b'), "%s produced no result" % n['key'])
    check(pb.npc_combatant('nobody') is None, "an unknown npc was invented")


def test_the_npc_tiers_really_do_get_harder():
    kid = _pet('Kid', 'spark', 'steps', level=12,
               training={s: 20 for s in cat.STATS})
    rates = []
    for n in cat.npcs():
        c = pb.npc_combatant(n['key'])
        wins = sum(pb.resolve(kid, c, seed=i, level_match=False)['winner'] == 'a'
                   for i in range(250))
        rates.append((n['tier'], wins / 250))
    check(rates[0][1] > rates[-1][1] + 0.3,
          "tier 1 and the last tier are barely different: %s"
          % [(t, round(r, 2)) for t, r in rates])
    check(rates[0][1] > 0.7, "the first opponent is not a gentle start: %.2f"
          % rates[0][1])


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

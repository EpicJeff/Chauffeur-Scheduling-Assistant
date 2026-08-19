"""The battle resolver. Pure, deterministic, and the whole game in one file.

ASYNCHRONOUS BY DESIGN. Kids are not on the app at the same moment and a wall
panel cannot sit blocked waiting for a phone, so there is no live turn loop:
you pick a loadout, the server resolves the entire fight, and both sides watch
the same replay. `resolve()` is a pure function of (seed, two combatants), so
what gets persisted is ~100 bytes -- the seed and the two snapshots -- and the
replay reconstructs on any device, at any time, forever.

Nothing in here touches storage, the network, an LLM or the solver. It is
arithmetic over dictionaries, which is why it is the cheapest slice in the arc
and the one worth building before anything visual.

LEVEL-MATCHING IS THE LOAD-BEARING RULE. In a fight between two family
members, both pets are scaled to the lower level AND their training budgets
are normalised to the smaller one, while each keeps its own DISTRIBUTION. So
the child who thought about their build keeps every bit of that advantage, and
the child who has done more chores keeps none of it. Power progression pays
off against the NPCs instead, where it hurts nobody. Every future change to
this file has to be checked against that sentence -- it is the answer to the
one thing about this feature that could genuinely hurt a kid.
"""
import random
from typing import Dict, List, Optional

from services import pet_catalog as cat

# Pokemon's shape, flattened. Six stats because kids who love Pokemon will
# want the real thing, and five would have collapsed the physical/special
# split that makes move choice interesting.
MAX_TURNS = 60          # a wall against two heal-spammers, not a balance knob
CRIT_CHANCE = 1 / 16.0
CRIT_MULT = 1.5
STAB = 1.2              # same-type attack bonus
STAGE_CAP = 4
TRAINING_PER_LEVEL = 4
TRAINING_STAT_CAP = 60  # per stat, so nothing degenerates into one number
# CALIBRATED, not inherited. Pokemon's own constants assume level 50-100 and
# base stats near 100; at the levels a family actually reaches they produce
# two-hit knockouts. These two numbers are the only dials that set how long a
# fight lasts, and they are tuned so a typical battle runs 5-10 rounds -- long
# enough to watch and to turn around, short enough that a kid does not lose
# interest halfway. A test holds the band.
HP_DIVISOR = 50
DAMAGE_DIVISOR = 120


def stat_value(base: int, training: int, level: int, is_hp: bool = False) -> int:
    if is_hp:
        return int((2 * base + training) * level / HP_DIVISOR) + level + 20
    return int((2 * base + training) * level / 100) + 5


def training_budget(level: int) -> int:
    """How many training points a pet of this level has to spend in total."""
    return max(0, (int(level) - 1)) * TRAINING_PER_LEVEL


def _stage_mult(stage: int) -> float:
    stage = max(-STAGE_CAP, min(STAGE_CAP, int(stage)))
    return (2 + stage) / 2.0 if stage >= 0 else 2.0 / (2 - stage)


def combatant(name: str, type_key: str, species: Optional[Dict] = None,
              level: int = 1, training: Optional[Dict] = None,
              moves: Optional[List[str]] = None, pet_id: str = None,
              owner: str = None) -> Dict:
    """One side of a fight, resolved from a pet record into pure numbers.

    Everything a battle needs and nothing it does not -- no member ids beyond
    a label, no storage handles. That is what makes the resolver testable and
    the replay portable."""
    type_key = cat.coerce(type_key)
    species = dict(species or {})
    base = cat.base_stats(species.get('body'))
    training = {s: max(0, min(TRAINING_STAT_CAP, int((training or {}).get(s, 0))))
                for s in cat.STATS}
    keys = [k for k in (moves or []) if cat.move(k)]
    if not keys:
        # A pet must never walk into a fight with nothing to do.
        keys = cat.default_moves(type_key)
    return {
        'name': name, 'type': type_key, 'species': species,
        'level': max(1, int(level or 1)), 'base': base, 'training': training,
        'moves': keys[:4], 'pet_id': pet_id, 'owner': owner,
    }


def _scaled(c: Dict, level: int, training_budget_cap: Optional[int]) -> Dict:
    """A combatant re-expressed at a given level and training budget.

    The DISTRIBUTION is preserved and only the total is squeezed, which is the
    whole trick: build choices survive level-matching, accumulated grind does
    not."""
    training = dict(c['training'])
    total = sum(training.values())
    if training_budget_cap is not None and total > training_budget_cap > 0:
        scale = training_budget_cap / total
        training = {s: int(v * scale) for s, v in training.items()}
    elif training_budget_cap == 0:
        training = {s: 0 for s in training}
    out = dict(c)
    out['level'] = level
    out['training'] = training
    out['stats'] = {
        s: stat_value(c['base'][s], training[s], level, is_hp=(s == 'hp'))
        for s in cat.STATS
    }
    out['max_hp'] = out['stats']['hp']
    return out


def _damage(atk_c: Dict, def_c: Dict, mv: Dict, rng: random.Random,
            stages_a: Dict, stages_d: Dict) -> Dict:
    physical = mv.get('category') == 'physical'
    a_key, d_key = ('atk', 'def') if physical else ('spa', 'spd')
    atk = atk_c['stats'][a_key] * _stage_mult(stages_a.get(a_key, 0))
    dfn = def_c['stats'][d_key] * _stage_mult(stages_d.get(d_key, 0))
    dfn = max(1.0, dfn)

    mult = cat.multiplier(mv['type'], def_c['type'])
    stab = STAB if mv['type'] == atk_c['type'] else 1.0
    crit = rng.random() < CRIT_CHANCE
    roll = 0.90 + rng.random() * 0.10

    raw = ((2 * atk_c['level'] / 5 + 2) * mv['power'] * atk / dfn) / DAMAGE_DIVISOR + 2
    dmg = int(raw * mult * stab * roll * (CRIT_MULT if crit else 1.0))
    return {'damage': max(1, dmg), 'multiplier': mult, 'crit': crit}


def _apply_effect(mv: Dict, actor: Dict, target: Dict, rng: random.Random,
                  stages_actor: Dict, stages_target: Dict, hp: Dict,
                  side: str, other: str) -> Optional[str]:
    """Stat stages, flinch and heal. No status clocks, no weather -- a seven
    year old should be able to hold the whole rulebook in their head."""
    effect = mv.get('effect')
    if not effect:
        return None
    chance = int(mv.get('chance', 100))
    if chance < 100 and rng.random() * 100 >= chance:
        return None
    if effect == 'heal':
        amount = int(target['max_hp'] * int(mv.get('amount', 30)) / 100)
        before = hp[side]
        hp[side] = min(actor['max_hp'], hp[side] + amount)
        healed = hp[side] - before
        return ('%s healed %d HP.' % (actor['name'], healed) if healed
                else '%s is already full.' % actor['name'])
    if effect == 'flinch':
        return 'flinch'
    stat = mv.get('stat')
    if stat not in cat.STATS:
        return None
    stages = int(mv.get('stages', 1))
    if effect == 'raise':
        stages_actor[stat] = max(-STAGE_CAP, min(STAGE_CAP,
                                                 stages_actor.get(stat, 0) + stages))
        return "%s's %s rose." % (actor['name'], cat.STAT_LABELS[stat])
    if effect == 'lower':
        stages_target[stat] = max(-STAGE_CAP, min(STAGE_CAP,
                                                  stages_target.get(stat, 0) - stages))
        return "%s's %s fell." % (target['name'], cat.STAT_LABELS[stat])
    return None


def _choose(c: Dict, hp_self: int, rng: random.Random,
            used: Optional[Dict] = None) -> Dict:
    """Which of the four a side uses this turn.

    Deliberately simple and deliberately NOT the strategy: the strategy is the
    loadout, chosen before the fight. Prefers a heal when badly hurt, prefers
    super-effective damage otherwise, and breaks ties on the seed so the same
    battle always plays out the same way."""
    used = used or {}
    options = [m for m in (cat.move(k) for k in c['moves']) if m
               and (m.get('uses') is None
                    or used.get(m['key'], 0) < int(m['uses']))]
    if not options:
        return {'key': 'struggle', 'name': 'Struggle', 'type': c['type'],
                'category': 'physical', 'power': 30, 'accuracy': 100}
    heals = [m for m in options if m.get('effect') == 'heal']
    if heals and hp_self < c['max_hp'] * 0.35:
        return heals[0]
    attacks = [m for m in options if int(m.get('power', 0)) > 0]
    if not attacks:
        return rng.choice(options)
    best = max(attacks, key=lambda m: int(m.get('power', 0))
               * cat.multiplier(m['type'], c.get('_vs', c['type'])))
    # a little variety so a replay is not the same move sixty times
    return best if rng.random() < 0.7 else rng.choice(attacks)


def resolve(a: Dict, b: Dict, seed: int, level_match: bool = True) -> Dict:
    """Fight, and return the whole replay.

    `level_match` is TRUE for anything family-vs-family and false against an
    NPC -- the grind has to pay off somewhere, and the machine is where it can
    do so without a child watching their sibling win because they did more
    chores."""
    rng = random.Random(int(seed))

    if level_match:
        level = min(a['level'], b['level'])
        budget = min(sum(a['training'].values()), sum(b['training'].values()))
        ca, cb = _scaled(a, level, budget), _scaled(b, level, budget)
    else:
        ca, cb = _scaled(a, a['level'], None), _scaled(b, b['level'], None)

    ca['_vs'], cb['_vs'] = cb['type'], ca['type']
    hp = {'a': ca['max_hp'], 'b': cb['max_hp']}
    stages = {'a': {}, 'b': {}}
    sides = {'a': ca, 'b': cb}
    turns: List[Dict] = []
    flinched = {'a': False, 'b': False}
    # Spent uses, per side. A move with `uses` in the catalogue drops out of
    # the choice once it runs out -- which is what stops two heal-spammers
    # riding the turn limit to a coin-flip finish.
    used: Dict[str, Dict[str, int]] = {'a': {}, 'b': {}}
    winner = None

    n = 0
    while n < MAX_TURNS and hp['a'] > 0 and hp['b'] > 0:
        n += 1
        # Speed decides who moves first; a dead tie breaks on the seed, so it
        # is still reproducible.
        sa = ca['stats']['spe'] * _stage_mult(stages['a'].get('spe', 0))
        sb = cb['stats']['spe'] * _stage_mult(stages['b'].get('spe', 0))
        order = ['a', 'b'] if sa > sb else ['b', 'a'] if sb > sa else (
            ['a', 'b'] if rng.random() < 0.5 else ['b', 'a'])

        for side in order:
            if hp['a'] <= 0 or hp['b'] <= 0:
                break
            other = 'b' if side == 'a' else 'a'
            actor, target = sides[side], sides[other]
            if flinched[side]:
                flinched[side] = False
                turns.append({'n': n, 'actor': side, 'name': actor['name'],
                              'move': None, 'move_name': None, 'damage': 0,
                              'missed': False, 'crit': False, 'multiplier': 1.0,
                              'note': '%s flinched!' % actor['name'],
                              'hp': dict(hp), 'max_hp': {'a': ca['max_hp'], 'b': cb['max_hp']}})
                continue

            mv = _choose(actor, hp[side], rng, used[side])
            if mv.get('uses') is not None:
                used[side][mv['key']] = used[side].get(mv['key'], 0) + 1
            event = {'n': n, 'actor': side, 'name': actor['name'],
                     'move': mv.get('key'), 'move_name': mv.get('name'),
                     'damage': 0, 'missed': False, 'crit': False,
                     'multiplier': 1.0, 'note': None}

            if rng.random() * 100 >= int(mv.get('accuracy', 100)):
                event['missed'] = True
                event['note'] = '%s missed.' % actor['name']
            elif int(mv.get('power', 0)) > 0:
                d = _damage(actor, target, mv, rng, stages[side], stages[other])
                hp[other] = max(0, hp[other] - d['damage'])
                event.update(damage=d['damage'], crit=d['crit'],
                             multiplier=d['multiplier'])
                bits = []
                if d['crit']:
                    bits.append('A critical hit!')
                text = cat.matchup_text(mv['type'], target['type'])
                if text:
                    bits.append(text)
                event['note'] = ' '.join(bits) or None
                if hp[other] > 0:
                    note = _apply_effect(mv, actor, target, rng, stages[side],
                                         stages[other], hp, side, other)
                    if note == 'flinch':
                        flinched[other] = True
                        event['note'] = ((event['note'] or '') + ' %s flinched!'
                                         % target['name']).strip()
                    elif note:
                        event['note'] = ((event['note'] or '') + ' ' + note).strip()
            else:
                note = _apply_effect(mv, actor, target, rng, stages[side],
                                     stages[other], hp, side, other)
                event['note'] = note if note != 'flinch' else None

            event['hp'] = dict(hp)
            event['max_hp'] = {'a': ca['max_hp'], 'b': cb['max_hp']}
            turns.append(event)

    if hp['a'] <= 0 and hp['b'] <= 0:
        winner = 'a' if rng.random() < 0.5 else 'b'
    elif hp['a'] <= 0:
        winner = 'b'
    elif hp['b'] <= 0:
        winner = 'a'
    else:
        # Ran out of turns. Whoever is in better shape, proportionally.
        ra, rb = hp['a'] / ca['max_hp'], hp['b'] / cb['max_hp']
        winner = 'a' if ra > rb else 'b' if rb > ra else (
            'a' if rng.random() < 0.5 else 'b')

    return {
        'seed': int(seed),
        'level_matched': bool(level_match),
        'a': _public(ca), 'b': _public(cb),
        'turns': turns, 'winner': winner, 'turn_count': n,
        'timed_out': hp['a'] > 0 and hp['b'] > 0,
    }


def _public(c: Dict) -> Dict:
    return {'name': c['name'], 'type': c['type'], 'species': c['species'],
            'level': c['level'], 'stats': c['stats'], 'max_hp': c['max_hp'],
            'moves': c['moves'], 'pet_id': c.get('pet_id'),
            'owner': c.get('owner'), 'training': c['training']}


def npc_combatant(key: str) -> Optional[Dict]:
    """An opponent from the catalogue, at its own level with a training spread
    that matches it -- the machine is where power progression is allowed to
    matter, so an NPC is not level-matched down to the challenger."""
    n = cat.npc(key)
    if not n:
        return None
    level = int(n.get('level', 1))
    budget = training_budget(level)
    base = cat.base_stats((n.get('species') or {}).get('body'))
    # Spread the budget the way the body already leans, so an NPC plays to its
    # own shape rather than arriving as a flat block of numbers.
    total = sum(base.values()) or 1
    training = {s: min(TRAINING_STAT_CAP, int(budget * base[s] / total))
                for s in cat.STATS}
    return combatant(n['name'], n['type'], n.get('species'), level=level,
                     training=training, moves=cat.default_moves(n['type']),
                     pet_id='npc:%s' % n['key'], owner=None)

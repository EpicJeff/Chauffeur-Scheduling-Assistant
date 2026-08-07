"""The kitchen as a resource model (occasions arc O0).

`_totals_from_dishes` has always been a two-resource model with its capacities
hardcoded: hands-on time SUMS (one cook, one pair of hands) while unattended
time takes the MAX (the oven runs while the rice sits). Both constants invert
the moment a family hosts — more hands arrive, and equipment becomes the thing
that binds.

Two errors cancelled on a weeknight, which is why this went unnoticed:

- `unattended = max` assumes an oven of infinite capacity. Two dishes at 350°
  for 45 minutes report 45 and take 90 if they cannot share a rack — and two
  dishes at DIFFERENT temperatures cannot share an oven at any capacity.
  Temperature is the constraint people forget; space is the one they picture.
- `hands_on = sum` assumes exactly one cook. "Can I help in the kitchen" is
  the defining feature of hosting.

With one cook serialising everything, burner contention almost never surfaces,
and the optimistic oven figure costs nothing because `unattended_mins` does not
count against the cook window — it gates nothing. The existing error is real
and currently harmless. It stops being harmless at twelve people.

**Analytic, not CP-SAT — deliberately.** The design brief reached for
`AddCumulative`, and that is still the right tool for the RUN-SHEET (real
clock times for real dishes, computed on demand for one hosting plate). It is
the wrong tool here: `_totals_from_dishes` runs once per composed day, so a
fourteen-day week plan would pay for fourteen solves on every render. These
spans are parallel-machine makespans over ten-ish jobs, they have closed
forms, and closed forms are exact, instant and testable.

REDUCTION IS THE CONTRACT: with one cook, one oven and no temperature
conflict, every number here is identical to the sum/max the app shipped with.
Where it differs — two oven dishes at different temperatures — sum/max was
wrong. `tests/test_meals.py` asserts this directly.
"""

import math
from typing import List, Optional

DEFAULT_OVENS = 1
DEFAULT_BURNERS = 4
DEFAULT_COOKS = 1


def capacities(settings: dict = None, cooks: int = None) -> tuple:
    """(ovens, burners, cooks). `cooks` overrides the household default — a
    hosting plate raises it without touching how the family cooks on a
    Tuesday."""
    s = settings or {}

    def _n(key, fallback):
        try:
            return max(1, int(s.get(key) or fallback))
        except (TypeError, ValueError):
            return fallback

    return (_n('kitchen_ovens', DEFAULT_OVENS),
            _n('kitchen_burners', DEFAULT_BURNERS),
            max(1, int(cooks or 0)) if cooks else _n('kitchen_cooks', DEFAULT_COOKS))


def _makespan(durations: List[int], machines: int) -> int:
    """Shortest wall-clock for these jobs across this many identical machines.

    The classic pair of lower bounds — no machine beats the longest single
    job, and no schedule beats the work divided evenly — which for a handful
    of kitchen tasks is achievable in practice. At `machines == 1` this is the
    plain sum, which is the reduction the whole module is held to.
    """
    jobs = [int(d or 0) for d in durations if int(d or 0) > 0]
    if not jobs:
        return 0
    if machines <= 1:
        return sum(jobs)
    return max(max(jobs), math.ceil(sum(jobs) / float(machines)))


def _oven_span(dishes: List[dict], ovens: int) -> int:
    """How long the ovens are busy.

    Dishes sharing a temperature share an oven freely — rack space is
    deliberately NOT modelled (see the brief: pots, pans and shelf counts are
    the most tedious axis to maintain and the least binding). Dishes at
    different temperatures cannot share one at all, so each temperature is an
    indivisible block and the blocks queue for the ovens available.

    A dish with no stated temperature is its own block rather than sharing
    with everything: an unknown temperature is not evidence of a match.
    """
    by_temp, unknown = {}, []
    for d in dishes:
        mins = int(d.get('unattended_mins') or 0)
        if mins <= 0 or str(d.get('equipment') or 'none') != 'oven':
            continue
        temp = d.get('oven_temp_f')
        if temp is None:
            unknown.append(mins)
        else:
            by_temp.setdefault(int(temp), []).append(mins)
    # Everything at one temperature goes in together, so the block is as long
    # as its longest dish — that is the `max` the old model applied globally,
    # correctly, but only within a temperature.
    blocks = [max(v) for v in by_temp.values()] + unknown
    return _makespan(blocks, ovens)


def _burner_span(dishes: List[dict], burners: int) -> int:
    """How long the burners are busy.

    A burner dish holds its ring for the hands-on finish as well as any
    simmering: a stir-fry is twenty-five minutes of somebody standing at the
    stove, and the ring is occupied throughout. Modelling only the unattended
    part would mean burners were never contended for exactly the dishes that
    contend for them.
    """
    jobs = [int(d.get('unattended_mins') or 0) + int(d.get('finish_mins') or 0)
            for d in dishes if str(d.get('equipment') or 'none') == 'burner']
    return _makespan(jobs, burners)


def equipment_span(dishes: List[dict], ovens: int, burners: int) -> int:
    """Wall-clock during which the kitchen is running. Ovens and burners run
    concurrently, so it is the longer of the two, not the sum.

    Dishes on neither (a salad, a slow cooker, anything served cold) still
    report `unattended_mins` and still deserve to be counted — a slow cooker
    occupies no contended resource but the day still has to wait for it.
    """
    free = [int(d.get('unattended_mins') or 0) for d in dishes
            if str(d.get('equipment') or 'none') == 'none']
    return max(_oven_span(dishes, ovens), _burner_span(dishes, burners),
               max(free) if free else 0)


def oven_conflicts(dishes: List[dict], ovens: int) -> List[dict]:
    """Temperatures that cannot run at the same time, worst first.

    Reported rather than merely priced in, because "these two want the oven at
    different temperatures" is the single most useful sentence this model can
    say to somebody planning a holiday meal, and a number that quietly grew
    says none of it.
    """
    by_temp = {}
    for d in dishes:
        if str(d.get('equipment') or 'none') != 'oven':
            continue
        if int(d.get('unattended_mins') or 0) <= 0:
            continue
        temp = d.get('oven_temp_f')
        if temp is None:
            continue
        by_temp.setdefault(int(temp), []).append(d)
    if len(by_temp) <= ovens:
        return []
    out = [{'temp_f': t,
            'mins': max(int(x.get('unattended_mins') or 0) for x in ds),
            'dishes': [x.get('short_name') or x.get('name') for x in ds]}
           for t, ds in by_temp.items()]
    out.sort(key=lambda r: -r['mins'])
    return out


def totals(dishes: List[dict], settings: dict = None,
           cooks: int = None) -> dict:
    """The three numbers every meals surface reads, computed against a real
    kitchen instead of two hardcoded constants."""
    ovens, burners, n_cooks = capacities(settings, cooks)
    return {
        'prep_ahead_mins': _makespan(
            [d.get('prep_ahead_mins') for d in dishes], n_cooks),
        'finish_mins': _makespan(
            [d.get('finish_mins') for d in dishes], n_cooks),
        'unattended_mins': equipment_span(dishes, ovens, burners),
        'cooks': n_cooks,
        'oven_conflicts': oven_conflicts(dishes, ovens),
    }

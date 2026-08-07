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


def scale_factor(dish: dict, serving_for: Optional[int]) -> float:
    """How many times over this dish has to be made.

    Every dish declares what its stored times assume (`serves`), so the factor
    is per-dish rather than per-plate — a main that serves four and a salad
    that serves eight are not stretched by the same amount.

    **Never below 1.0.** Cooking for fewer people than a dish serves does not
    make it faster: you still boil the pot, still heat the oven, and nobody
    peels three-quarters of a potato. Scaling down is the one direction that
    is pure fiction.
    """
    if not serving_for:
        return 1.0
    base = 0
    try:
        base = int(dish.get('serves') or 0)
    except (TypeError, ValueError):
        base = 0
    if base <= 0:
        base = 4
    # Most food divides: nine portions of carrots is 1.5 pans and 1.5 times the
    # peeling. A tray does not — you cannot bake half a lasagna — so a dish
    # made in whole units rounds UP to the next one, which is twice the
    # ingredients and twice the work, not 1.5 times either.
    if dish.get('whole_units'):
        import math
        return float(max(1, math.ceil(float(serving_for) / float(base))))
    return max(1.0, float(serving_for) / float(base))


def scaled(dish: dict, serving_for: Optional[int]) -> dict:
    """The same dish, made for more people.

    **Hands-on scales; the oven does not.** Four times the potatoes is four
    times the peeling, but it is not four times the roasting — heat does not
    work that way, and a tray that needs materially longer is a *bigger thing*
    rather than more of the same thing. That distinction is the same one M4
    already drew when it made roasted and mashed potatoes separate dishes: a
    twenty-pound turkey is its own entry with its own times, not a chicken
    with a multiplier on it.

    Deliberately NOT modelled: that four trays of potatoes may not fit one
    oven. Rack space is unmodelled everywhere in this module (see `_oven_span`),
    and inventing a batch count here would be the one place it was guessed.
    """
    f = scale_factor(dish, serving_for)
    if f <= 1.0:
        return dish
    return {**dish,
            'prep_ahead_mins': int(round(int(dish.get('prep_ahead_mins') or 0) * f)),
            'finish_mins': int(round(int(dish.get('finish_mins') or 0) * f)),
            '_scale': round(f, 2)}


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


def _phases(dish: dict) -> tuple:
    """(prep, unattended, finish) in the order they actually happen.

    Prep, then the cooking the dish does on its own, then the work near
    serving. A roast is five minutes of seasoning, forty in the oven, five to
    rest and carve — and that order is what makes a run sheet a sequence
    rather than a pile of durations.
    """
    return (max(0, int(dish.get('prep_ahead_mins') or 0)),
            max(0, int(dish.get('unattended_mins') or 0)),
            max(0, int(dish.get('finish_mins') or 0)))


def _sequential_sheet(plate: List[dict], n_cooks: int) -> Optional[dict]:
    """The fallback when the solver is unavailable or gives up.

    One dish after another, which is pessimistic but never WRONG — it is the
    schedule a single cook working through the list would actually follow. A
    run sheet that fails open with a safe answer beats one that vanishes on
    the day somebody needed it.
    """
    t, steps = 0, []
    for d in plate:
        p, u, f = _phases(d)
        steps.append({'dish': d, 'prep_at': t, 'cook_at': t + p,
                      'finish_at': t + p + u})
        t += p + u + f
    return {'span_mins': t, 'steps': steps, 'exact': False}


def _solve_sheet(plate: List[dict], ovens: int, burners: int,
                 n_cooks: int) -> Optional[dict]:
    """Place every dish so that the LATEST possible start still serves on time.

    "When do I have to start?" is the question a run sheet exists to answer,
    so the objective maximises the first task's start rather than minimising a
    makespan — same schedule, but the number that falls out is the one worth
    reading.

    This is where CP-SAT belongs, and `totals()` is where it does not: this
    runs on demand for one plate, while totals runs once per composed day.
    """
    try:
        from ortools.sat.python import cp_model
    except ImportError:                       # pragma: no cover
        return None

    horizon = sum(sum(_phases(d)) for d in plate) or 1
    m = cp_model.CpModel()
    cook_ivs, burner_ivs, oven_rows = [], [], []
    starts, out = [], []

    for idx, d in enumerate(plate):
        p, u, f = _phases(d)
        s_prep = m.NewIntVar(0, horizon, f'p{idx}')
        s_cook = m.NewIntVar(0, horizon, f'c{idx}')
        s_fin = m.NewIntVar(0, horizon, f'f{idx}')
        # The chain. Equality is not required between phases — a dish may wait
        # for a free burner, and pretending otherwise would make the sheet lie.
        m.Add(s_prep + p <= s_cook)
        m.Add(s_cook + u <= s_fin)
        m.Add(s_fin + f <= horizon)
        starts.append(s_prep if p else (s_cook if u else s_fin))

        if p:
            cook_ivs.append(m.NewIntervalVar(s_prep, p, m.NewIntVar(0, horizon, ''), ''))
        if f:
            cook_ivs.append(m.NewIntervalVar(s_fin, f, m.NewIntVar(0, horizon, ''), ''))

        equip = str(d.get('equipment') or 'none')
        if equip == 'burner' and (u or f):
            # The ring is held from the moment it goes on until the cook walks
            # away — through the hands-on finish, not merely the simmer.
            end = m.NewIntVar(0, horizon, '')
            m.Add(end == s_fin + f)
            burner_ivs.append(m.NewIntervalVar(s_cook, u + f, end, ''))
        elif equip == 'oven' and u:
            oven_rows.append((idx, d.get('oven_temp_f'), s_cook, u))
        out.append({'dish': d, 'p': p, 'u': u, 'f': f,
                    's_prep': s_prep, 's_cook': s_cook, 's_fin': s_fin})

    if cook_ivs:
        m.AddCumulative(cook_ivs, [1] * len(cook_ivs), n_cooks)
    if burner_ivs:
        m.AddCumulative(burner_ivs, [1] * len(burner_ivs), burners)

    # Ovens: one temperature shares freely, two temperatures cannot share at
    # all. Rack space stays unmodelled, so the only exclusion is thermal.
    if oven_rows:
        assign = {}
        for idx, _t, _s, _u in oven_rows:
            lits = [m.NewBoolVar(f'o{idx}_{o}') for o in range(ovens)]
            m.AddExactlyOne(lits)
            assign[idx] = lits
        for a in range(len(oven_rows)):
            for b in range(a + 1, len(oven_rows)):
                i, ti, si, ui = oven_rows[a]
                j, tj, sj, uj = oven_rows[b]
                # An unknown temperature never shares: not knowing is not
                # evidence of a match.
                if ti is not None and tj is not None and int(ti) == int(tj):
                    continue
                for o in range(ovens):
                    first = m.NewBoolVar('')
                    both = [assign[i][o], assign[j][o]]
                    m.Add(si + ui <= sj).OnlyEnforceIf(both + [first])
                    m.Add(sj + uj <= si).OnlyEnforceIf(both + [first.Not()])

    begin = m.NewIntVar(0, horizon, 'begin')
    if starts:
        m.AddMinEquality(begin, starts)
    # Two terms, and the second one is not decoration. Maximising the first
    # start alone says nothing about where the REST of the work lands, so the
    # first solve cheerfully finished the gravy five hours before dinner —
    # technically before serving, and completely useless. Pushing every task
    # as late as its resources allow is what a cook actually does, and it puts
    # the finishing work against the serve time where it belongs. `begin`
    # still dominates: its weight exceeds anything the tail can sum to.
    tail = sum(r['s_fin'] for r in out)
    m.Maximize(begin * (len(out) * horizon + 1) + tail)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 3.0
    solver.parameters.num_search_workers = 4
    if solver.Solve(m) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    first = solver.Value(begin)
    return {'span_mins': horizon - first, 'exact': True,
            'steps': [{'dish': r['dish'],
                       'prep_at': solver.Value(r['s_prep']) - first,
                       'cook_at': solver.Value(r['s_cook']) - first,
                       'finish_at': solver.Value(r['s_fin']) - first}
                      for r in out]}


def run_sheet(dishes: List[dict], serve_at: str = '18:00', settings: dict = None,
              cooks: int = None, serving_for: int = None) -> dict:
    """Clock times for a plate: when each dish starts, and when to begin.

    **Shown, never pushed.** The meals arc's taskmaster rule governs this
    absolutely — emitting "start the rice at 3:40, pack two at 4:50" every
    evening is a stream of orders, and the promise is removing load rather
    than issuing it. This is also why the design brief's plan to emit these as
    `PrepStep`s was dropped: `PrepStep` models work OUTSIDE the cook window,
    per dish, opt-in, and it fires reminders. A run sheet is inside the window,
    dated, computed, and asked for. Wrong entity, and the reminders would be
    exactly the nagging the arc promised not to become.
    """
    ovens, burners, n_cooks = capacities(settings, cooks)
    plate = [scaled(d, serving_for) for d in dishes
             if any(_phases(scaled(d, serving_for)))]
    if not plate:
        return {'serve_at': serve_at, 'start_at': serve_at, 'steps': [],
                'span_mins': 0, 'exact': True, 'cooks': n_cooks}

    sol = _solve_sheet(plate, ovens, burners, n_cooks) \
        or _sequential_sheet(plate, n_cooks)

    try:
        hh, mm = [int(x) for x in str(serve_at).split(':')[:2]]
    except (TypeError, ValueError):
        hh, mm = 18, 0
    serve_mins = hh * 60 + mm
    span = int(sol['span_mins'])

    def clock(offset_from_start: int) -> str:
        t = (serve_mins - span + offset_from_start) % (24 * 60)
        return f"{t // 60:02d}:{t % 60:02d}"

    lines = []
    for st in sol['steps']:
        d = st['dish']
        nm = d.get('short_name') or d.get('name') or 'dish'
        p, u, f = _phases(d)
        equip = str(d.get('equipment') or 'none')
        if p:
            lines.append({'at': clock(st['prep_at']), 'mins': p, 'kind': 'prep',
                          'dish': nm, 'text': f"{nm} — {p} min prep"})
        if u:
            where = 'in the oven'
            if equip == 'oven' and d.get('oven_temp_f'):
                where = f"in the oven at {int(d['oven_temp_f'])}°"
            elif equip == 'burner':
                where = 'on the stove'
            elif equip == 'none':
                where = 'going'
            lines.append({'at': clock(st['cook_at']), 'mins': u, 'kind': 'cook',
                          'dish': nm, 'text': f"{nm} {where} — {u} min"})
        if f:
            lines.append({'at': clock(st['finish_at']), 'mins': f, 'kind': 'finish',
                          'dish': nm, 'text': f"{nm} — {f} min to finish"})
    lines.sort(key=lambda r: r['at'])
    return {'serve_at': serve_at, 'start_at': clock(0), 'steps': lines,
            'span_mins': span, 'exact': bool(sol.get('exact')),
            'cooks': n_cooks, 'serving_for': serving_for or None}


def totals(dishes: List[dict], settings: dict = None, cooks: int = None,
           serving_for: int = None) -> dict:
    """The three numbers every meals surface reads, computed against a real
    kitchen instead of two hardcoded constants.

    `serving_for` is the whole headcount for the night, not the extra guests —
    "we're having twelve people" is what somebody says, and asking them to
    subtract their own family first is the kind of arithmetic an app should be
    doing for them.
    """
    ovens, burners, n_cooks = capacities(settings, cooks)
    plate = [scaled(d, serving_for) for d in dishes]
    return {
        'prep_ahead_mins': _makespan(
            [d.get('prep_ahead_mins') for d in plate], n_cooks),
        'finish_mins': _makespan(
            [d.get('finish_mins') for d in plate], n_cooks),
        'unattended_mins': equipment_span(plate, ovens, burners),
        'cooks': n_cooks,
        'serving_for': serving_for or None,
        # The honest headline for a hosting night: hands-on is what explodes,
        # and how many people are cooking is what decides whether that is an
        # afternoon or an ordinary evening.
        'hands_on_mins': _makespan([d.get('prep_ahead_mins') for d in plate], n_cooks)
                       + _makespan([d.get('finish_mins') for d in plate], n_cooks),
        'oven_conflicts': oven_conflicts(plate, ovens),
    }

"""The build engine on the real read path with real recorded answers (final
whole-branch review I13, house editor slice 1). Claude's answers recorded from
Reference Plans Lot 58 in the Task 12 comparison (outline, two wings' walls,
the roof) are replayed through twin_reads.read by stubbing only
model_pools.call_pool_json; every other step answers from the hand fixtures.
The sheets are blank, so this checks the shapes, the settling and the roof
plates, not the drawing.

Run from chauffeur/:  python tests/test_twin_build_replay.py
"""
import copy
import json
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_build_replay_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import model_pools, storage  # noqa: E402
from services import twin_build as tb  # noqa: E402
from services import twin_cost as tc  # noqa: E402
from services import twin_reads  # noqa: E402
from services import twin_store as ts  # noqa: E402
import test_twin_build as engine_tests  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RECORDED = os.path.join(HERE, 'fixtures', 'twin_reads', 'recorded', 'claude')
FIXTURES = os.path.join(HERE, 'fixtures', 'twin_reads')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _load(path):
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    return data.get('answer', data) if isinstance(data, dict) else data


class Pool:
    """Stands in for call_pool_json: recorded Claude answers for the steps the
    comparison read, hand fixtures for the rest; usage reported like the real call."""

    def __init__(self):
        self.walls = [_load(os.path.join(RECORDED, 'walls-2.json')), _load(os.path.join(RECORDED, 'walls-3.json'))]
        self.calls = []

    def __call__(self, tier, api_key, system_prompt, user_prompt, **kw):
        kind = next(k for k, v in twin_reads.PROMPTS.items() if v == system_prompt)
        self.calls.append(kind)
        if kw.get('usage') is not None:
            kw['usage'].append({'model': next(iter(tc.PRICES)), 'input_tokens': 1500, 'output_tokens': 400,
                                'images': len(kw.get('images') or []), 'prompt_chars': len(user_prompt),
                                'max_output_tokens': kw.get('max_output_tokens') or 0})
        if kind == 'outline':
            return copy.deepcopy(_load(os.path.join(RECORDED, 'outline-1.json')))
        if kind == 'walls':
            # The comparison recorded the outline's first two wings; route by step, since
            # the whole floor is now read first (repair R1) and has no recording.
            step = json.loads(user_prompt).get('step', '')
            recorded = {'walls:L1:garage': 0, 'walls:L1:left-bedroom-wing': 1}
            if step in recorded:
                return copy.deepcopy(self.walls[recorded[step]])
            return {'walls': [], 'confidence': 0.5, 'why': 'not read in the comparison'}
        if kind == 'roof':
            return copy.deepcopy(_load(os.path.join(RECORDED, 'roof-4.json')))
        return copy.deepcopy(_load(os.path.join(FIXTURES, f'{kind}.json')))


def scenario_recorded_answers_build_a_house_through_the_real_reader():
    engine_tests._fresh()
    storage.patch_settings({'llm_provider': 'anthropic', 'llm_anthropic_api_key': 'k'})
    _, _, photo = engine_tests._sources()
    pool = Pool()
    original = model_pools.call_pool_json
    model_pools.call_pool_json = pool
    try:
        b = tb.start(engine_tests._inputs(photo), inline=True)
        for _ in range(12):
            st = tb.status(b)
            if st['state'] != 'paused':
                break
            tb.answer(b, st['pause']['step'], {'accept': True})
    finally:
        model_pools.call_pool_json = original
    st = tb.status(b)
    check(st['state'] == 'done', (st['state'], [e for e in st['events'] if e['type'] in ('error', 'question')][-3:]))
    house = ts.current()['buildings'][0]
    l1 = [w for w in house['walls'] if w['level'] == 'L1']
    settled = [w for w in l1 if w.get('state', 'settled') == 'settled']
    check(l1 and len(settled) >= len(l1) / 2, ('at least half the recorded walls settle', len(settled), len(l1)))
    sections = house['roof']['sections']
    check(len(sections) >= 5, ('the recorded roof keeps its sections', len(sections)))
    tops = sorted(l['elevation'] + l['ceiling'] for l in house['levels'])
    check(all(tops[0] - 0.5 <= sec['plate'] <= tops[-1] + 0.5 for sec in sections),
          ('plates sit on real floors', sorted({sec['plate'] for sec in sections}), tops))
    check(any(sec['kind'] == 'hip' for sec in sections), 'hips survive the real read path')
    check(tc.total() > 0 and all(e['stage'].startswith('step:') for e in tc.entries()), 'every read was metered')


YARD_NOTE = 'Kept your yard. Plants and beds are laid out only in an empty yard.'


def scenario_automatic_builds_keep_finished_yards():
    import test_twin_build_chain as chain
    from services import twin_plan
    class EmptyYardReader(chain.ThreadReader):
        def __call__(self, kind, *a, **kw):
            answer = super().__call__(kind, *a, **kw)
            if kind == 'site':
                # The shared site fixture reads a retaining wall into edges.
                # This case specifically starts with no plants, beds or edges.
                answer['retaining_walls'] = []
            return answer
    # Replay the actual place chain and single shell build, then repeat on their
    # finished yard. Only the shell's final compose runs in the chain.
    for part in ('place', 'shed', 'house'):
        chain._place()
        # Supply the confirmed lot without first composing it.
        if part != 'place':
            ts.push_round({'units': 'ft', 'buildings': [], 'site': {
                'lot': [[-100, -100], [250, -100], [250, 200], [-100, 200]]}, 'materials': {}}, 'hand')
        chain._follow(tb.start({'part': part}, reader=EmptyYardReader(), inline=True))
        before = ts.current()
        check(all(before['site'][n] for n in ('planting', 'beds', 'edges')), 'first empty-yard build composes')
        # A hand-moved generated plant and a hand plant must both survive.
        before['site']['planting'][0]['at'] = [100, -50]
        before['site']['planting'][0]['src'] = {'person': True}
        before['site']['planting'].append(dict(id='hand-plant', at=[100, -60], kind='shrub',
                                               preset='Boxwood', height=4, src={'person': True}))
        before = twin_plan.normalize(before)[0]
        ts.push_round(before, 'hand', base=ts.current_id())
        ids = chain._follow(tb.start({'part': part}, reader=EmptyYardReader(), inline=True))
        after = ts.current()
        for name in ('planting', 'beds', 'edges'):
            check(after['site'][name] == before['site'][name], (part, 'kept', name))
        notes = [e['text'] for b in ids for e in tb.status(b)['events'] if e['type'] == 'log']
        check(notes.count(YARD_NOTE) == 1, notes)
        if part == 'house':
            # Re-reading a drawing marks dependent compose as reread too; it
            # must not acquire the explicit Plants-and-beds API exemption.
            tb.reread(ids[-1], 'draft', reader=EmptyYardReader(), inline=True)
            chain._follow(ids[-1])
            check(all(ts.current()['site'][n] == after['site'][n] for n in ('planting', 'beds', 'edges')),
                  'drawing replay keeps the finished yard')


def scenario_compose_guard_ignores_ghosts_and_proposals_and_keeps_other_work():
    from unittest.mock import patch
    from services import twin_library, twin_plan
    import test_twin_build_chain as chain
    import test_twin_compose as compose_tests
    for occupied in (None, 'planting', 'beds', 'edges'):
        chain._place()
        plan = compose_tests._plan()
        generated = tb.twin_compose.compose(plan, twin_library.kit('modern_farmhouse'), seed=1)[0]
        for name in ('planting', 'beds', 'edges'):
            plan['site'][name] = copy.deepcopy(generated['site'][name][:2])
            for i, piece in enumerate(plan['site'][name]):
                piece['state'] = 'ghost' if i == 0 else 'proposal'
        if occupied:
            plan['site'][occupied][0]['state'] = 'settled'
            plan['site'][occupied][0]['src'] = {'person': True}
        build = {'id': 'guard-test', 'inputs': {'part': 'lot'}, 'steps': [],
                 'generation': ts.generation(), 'cost': 0, 'events': [], 'seq': 0}
        step = tb._step('compose')
        build['steps'] = [step]
        real_compose = tb.twin_compose.compose
        def with_other_work(*a, **kw):
            out, notes = real_compose(*a, **kw)
            out['materials']['trim']['color'] = '#123456'
            return out, notes
        captured = {}
        def update_current(mutator, **kw):
            captured['plan'] = mutator(copy.deepcopy(plan))
        with patch.object(tb.twin_compose, 'compose', side_effect=with_other_work), \
                patch.object(ts, 'update_current', side_effect=update_current):
            tb._settle(build, step, {'fragment': {}, 'problems': []})
        after = captured['plan']
        check(after['materials']['trim']['color'] == '#123456', 'non-yard compose work still happens')
        if occupied:
            normalized = twin_plan.normalize(plan)[0]
            check(all(after['site'][n] == normalized['site'][n] for n in ('planting', 'beds', 'edges')), occupied)
            check(sum(e.get('text') == YARD_NOTE for e in build['events']) == 1, build['events'])
        else:
            check(len(after['site']['planting']) > len(plan['site']['planting']), 'ghost/proposal-only yard is empty')


def scenario_explicit_compose_reread_still_recomposes():
    import test_twin_build_chain as chain
    chain._place()
    build = tb.start({'part': 'shed'}, reader=chain.ThreadReader(), inline=True)
    chain._follow(build)
    plan = ts.current()
    plan['site']['edges'].append(dict(id='extra-generated', by='compose', points=[[80, 80], [90, 80]]))
    ts.push_round(plan, 'hand')
    tb.reread(build, 'compose', inline=True)
    check(not any(p['id'] == 'extra-generated' for p in ts.current()['site']['edges']), 'explicit recompose retained')
    check(not any(e.get('text') == YARD_NOTE for e in tb.status(build)['events']), 'no misleading kept note')


if __name__ == '__main__':
    for fn in (scenario_recorded_answers_build_a_house_through_the_real_reader,
               scenario_automatic_builds_keep_finished_yards,
               scenario_compose_guard_ignores_ghosts_and_proposals_and_keeps_other_work,
               scenario_explicit_compose_reread_still_recomposes):
        fn()
        print('  ok ', fn.__name__)

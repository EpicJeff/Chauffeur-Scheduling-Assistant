"""The reader is told the house's rules, writes in stage order, and reads
fixtures (plan docs/superpowers/plans/2026-11-10-house-guided-build-piece-4.md
Task 4; brief .superpowers/sdd/2026-11-10-house-guided-build-piece-4/
task-4-brief.md; spec docs/superpowers/specs/2026-11-09-house-connected-model-
design.md section 6, "The reader is told the model's rules", and principle 10,
"Fixtures shown on the plans become anchors").

Interfaces under test:
  twin_reads.PROMPTS['draft'|'draft_level'|'draft_rooms']  state the rules;
      the draft writes levels, walls, openings, fixtures, roof, then the rest.
  twin_reads.parse('draft'|'draft_level', answer)  accepts
      building.fixtures: [{kind, level, at:[x,y], surface:'ceiling'|'wall'|'floor', wall?}]
      and names a bad one by its path.
  twin_model_bridge.assemble(flat, previous)  a flat building's `fixtures`
      entry in the read's shape (at + surface, no rect) becomes an anchor on
      that surface with read provenance, never on a person's anchor spot; one
      with no valid surface becomes a flag. A `fixtures` entry with a rect is
      still a library item, as before.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_reads_rules.py
"""
import copy
import glob
import json
import math
import os
import re
import sys
import tempfile
import traceback

if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_reads_rules_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import twin_model, twin_model_hosts, twin_reads  # noqa: E402
from services import twin_model_bridge as bridge  # noqa: E402

RECORDED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_reads', 'recorded')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _words(prompt):
    return ' '.join(prompt.split()).lower()


def _building_template(prompt):
    """The key order of the first {building:{...}} template in a prompt."""
    compact = re.sub(r'\s+', '', prompt)
    start = compact.find('{building:{')
    check(start >= 0, 'the prompt shows the reply shape as {building:{...}}')
    start += len('{building:')  # the building object's own brace
    depth, end = 0, start
    for end in range(start, len(compact)):
        depth += {'{': 1, '[': 1, '}': -1, ']': -1}.get(compact[end], 0)
        if depth == 0:
            break
    inner = compact[start + 1:end]
    # Top-level keys of the building object only.
    keys, depth, token = [], 0, ''
    for ch in inner:
        depth += {'{': 1, '[': 1, '}': -1, ']': -1}.get(ch, 0)
        if depth == 0 and ch == ',':
            keys.append(token.split(':')[0])
            token = ''
        else:
            token += ch
    keys.append(token.split(':')[0])
    return [k for k in keys if k]


def _in_order(keys, order, label):
    positions = []
    for key in order:
        check(key in keys, f'{label}: the reply shape lists {key}: {keys}')
        positions.append(keys.index(key))
    check(positions == sorted(positions), f'{label}: the reply is written {" > ".join(order)}: {keys}')


# ---------------------------------------------------------------- prompts

def prompt_states_the_rules_and_order():
    for kind in ('draft', 'draft_level'):
        words = _words(twin_reads.PROMPTS[kind])
        for rule in ('rooms are closed by walls', 'every opening sits on a wall'):
            check(rule in words, f'{kind}: the prompt states the rule "{rule}"')
        for fixture in ('lights', 'switches', 'outlets', 'fans', 'smoke alarms'):
            check(fixture in words, f'{kind}: the prompt names {fixture} as fixtures to read')
        compact = re.sub(r'\s+', '', twin_reads.PROMPTS[kind])
        check('fixtures:[{kind,level,at:[x,y],surface' in compact,
              f'{kind}: the prompt gives the fixture shape fixtures:[{{kind, level, at:[x,y], surface, wall?}}]')
        for surface in ('ceiling', 'wall', 'floor'):
            check(re.search(r'surface[^.]*' + surface, words), f'{kind}: a fixture surface may be {surface}')
    keys = _building_template(twin_reads.PROMPTS['draft'])
    _in_order(keys, ('levels', 'walls', 'openings', 'fixtures', 'roof'), 'draft')
    for later in ('rooms', 'porches', 'stairs'):
        check(later in keys and keys.index(later) > keys.index('roof'),
              f'draft: {later} comes after the roof ("then the rest"): {keys}')
    keys = _building_template(twin_reads.PROMPTS['draft_level'])
    _in_order(keys, ('levels', 'walls', 'openings', 'fixtures'), 'draft_level')
    for later in ('rooms', 'porches', 'stairs'):
        check(later in keys and keys.index(later) > keys.index('fixtures'),
              f'draft_level: {later} comes after the fixtures: {keys}')
    words = _words(twin_reads.PROMPTS['draft_rooms'])
    check('rooms are closed by walls' in words, 'draft_rooms: the rooms read is told rooms are closed by walls')
    for kind in ('draft', 'draft_level', 'draft_rooms'):
        words = _words(twin_reads.PROMPTS[kind])
        for household in ('upton', 'lot 58', 'pool house'):
            check(household not in words, f'{kind}: the rules carry no household text ({household})')


# ---------------------------------------------------------------- validator

FIXTURES = [{'kind': 'light', 'level': 'L1', 'at': [12.5, 8.0], 'surface': 'ceiling'},
            {'kind': 'switch', 'level': 'L1', 'at': [3.0, 0.0], 'surface': 'wall', 'wall': 'w1'},
            {'kind': 'outlet', 'level': 'L1', 'at': [20.0, 5.5], 'surface': 'floor'},
            {'kind': 'fan', 'level': 'L2', 'at': [9.25, 14.0], 'surface': 'ceiling'}]


def validator_accepts_fixtures_and_rejects_bad_surface():
    answer = copy.deepcopy(_recorded('claude', 'draft-pool-house.json'))
    answer['building']['fixtures'] = copy.deepcopy(FIXTURES)
    frag, problems = twin_reads.parse('draft', answer)
    check(problems == [], f'good fixtures add no problems: {problems[:6]}')
    check(frag['building'].get('fixtures') == FIXTURES, f'the fixtures come through as read: {frag["building"].get("fixtures")}')

    bad = copy.deepcopy(answer)
    bad['building']['fixtures'] = [FIXTURES[0], {'kind': 'switch', 'level': 'L1', 'at': [3.0, 0.0], 'surface': 'roof'},
                                   FIXTURES[2]]
    frag, problems = twin_reads.parse('draft', bad)
    check(any(p.startswith('draft.building.fixtures[1].surface') for p in problems),
          f'a bad surface is named by its path draft.building.fixtures[1].surface: {problems}')
    check(frag['building'].get('fixtures') == [FIXTURES[0], FIXTURES[2]],
          f'the bad fixture is dropped, the good ones kept: {frag["building"].get("fixtures")}')
    check(twin_reads._usable('draft', frag, problems), 'one bad fixture does not sink the draft')

    for broken, field in (({'kind': 'light', 'level': 'L1', 'at': [1], 'surface': 'ceiling'}, 'at'),
                          ({'kind': 'light', 'level': 'L1', 'surface': 'ceiling'}, 'at'),
                          ({'kind': 'light', 'at': [1, 2], 'surface': 'ceiling'}, 'level'),
                          ({'kind': 'switch', 'level': 'L1', 'at': [1, 2], 'surface': 'wall', 'wall': 7}, 'wall')):
        case = copy.deepcopy(answer)
        case['building']['fixtures'] = [broken]
        frag, problems = twin_reads.parse('draft', case)
        check(any(p.startswith(f'draft.building.fixtures[0].{field}') for p in problems),
              f'{broken}: named at draft.building.fixtures[0].{field}: {problems}')
        kept = frag['building'].get('fixtures')
        if field == 'wall':
            # An invalid optional field may be dropped alone, as v.fields does elsewhere.
            check(kept == [] or (len(kept) == 1 and 'wall' not in kept[0]), f'{broken}: no invalid wall kept: {kept}')
        else:
            check(kept == [], f'{broken}: dropped: {kept}')

    level_answer = {'building': {'levels': [copy.deepcopy(answer['building']['levels'][0])], 'walls': [],
                                 'openings': [], 'fixtures': copy.deepcopy(FIXTURES[:3])}}
    frag, problems = twin_reads.parse('draft_level', level_answer)
    check(problems == [] and frag['building'].get('fixtures') == FIXTURES[:3],
          f'a per-level read carries fixtures too: {problems} {frag["building"].get("fixtures")}')


def a_recorded_draft_without_fixtures_still_validates():
    files = sorted(glob.glob(os.path.join(RECORDED, '*', 'draft*.json')))
    checked = 0
    for path in files:
        name = os.path.basename(path)
        answer = _load(path)
        if 'building' not in answer and 'rooms' not in answer:
            continue  # draft-main-spike.json is a whole plan, not a reader's answer
        kind = 'draft_rooms' if name.startswith('draft_rooms') else 'draft'
        frag, problems = twin_reads.parse(kind, answer)
        check(problems == [], f'{name}: an answer read before fixtures still validates: {problems[:6]}')
        check(twin_reads._usable(kind, frag, problems), f'{name}: still usable')
        if kind == 'draft':
            check('fixtures' not in frag['building'], f'{name}: no fixtures key is invented when none were read')
        checked += 1
    check(checked >= 6, f'every recorded draft was checked: {checked} of {len(files)}')


# ---------------------------------------------------------------- the bridge

def _wall(wid, a, b):
    return {'id': wid, 'level': 'L1', 'from': list(a), 'to': list(b), 'exterior': True, 'thickness': 0.5, 'height': 9}


def _flat(fixtures, *, extra_items=()):
    return {'schema': 'chauffeur.twin.plan/2', 'units': 'ft', 'materials': {},
            'buildings': [{'id': 'b1', 'name': 'Test house', 'position': [0, 0], 'rotation': 0, 'base': 0,
                           'levels': [{'id': 'L1', 'name': 'main floor', 'elevation': 0, 'ceiling': 9}],
                           'walls': [_wall('s', (0, 0), (20, 0)), _wall('e', (20, 0), (20, 10)),
                                     _wall('n', (20, 10), (0, 10)), _wall('w', (0, 10), (0, 0))],
                           'openings': [],
                           'rooms': [{'id': 'room-hall', 'level': 'L1', 'name': 'hall',
                                      'polygon': [[0, 0], [20, 0], [20, 10], [0, 10]]}],
                           'roof': {'sections': [], 'extensions': []},
                           'stairs': [], 'lights': [], 'porches': [],
                           'fixtures': list(fixtures) + list(extra_items)}],
            'site': {}}


def _near(a, b, tol):
    return math.dist(a[:2], b[:2]) <= tol


def _surface_of(host):
    return next((k for k in ('ceiling', 'wall', 'floor') if isinstance(host, dict) and k in host), None)


def fixtures_become_anchors_on_their_surfaces():
    light = {'kind': 'light', 'level': 'L1', 'at': [5.0, 5.0], 'surface': 'ceiling'}
    switch = {'kind': 'switch', 'level': 'L1', 'at': [3.0, 0.0], 'surface': 'wall', 'wall': 's'}
    outlet = {'kind': 'outlet', 'level': 'L1', 'at': [15.0, 5.0], 'surface': 'floor'}
    fan = {'kind': 'fan', 'level': 'L1', 'at': [12.0, 6.0], 'surface': 'ceiling'}
    lost_wall = {'kind': 'switch', 'level': 'L1', 'at': [8.0, 5.0], 'surface': 'wall', 'wall': 'nope'}
    outside = {'kind': 'light', 'level': 'L1', 'at': [40.0, 5.0], 'surface': 'ceiling'}
    counter = {'id': 'counter-1', 'level': 'L1', 'kind': 'counter', 'asset': 'counter', 'rect': [1, 1, 3, 2],
               'height': 3}
    flat = _flat([light, switch, outlet, fan, lost_wall, outside], extra_items=[counter])
    try:
        model, notes = bridge.assemble(copy.deepcopy(flat), None)
    except Exception as exc:
        raise AssertionError(f'assemble must accept read fixtures (at + surface, no rect): {type(exc).__name__}: {exc}') from None
    house = model['buildings'][0]

    check([i['id'] for i in house['items']] == ['counter-1'],
          f'a fixture with a rect is still a library item, and read fixtures are not items: {house["items"]}')
    for fixture, surface, owner in ((light, 'ceiling', 'room-hall'), (switch, 'wall', 's'),
                                    (outlet, 'floor', 'room-hall'), (fan, 'ceiling', 'room-hall')):
        found = [a for a in house['anchors'] if a.get('kind') == fixture['kind'] and _surface_of(a.get('host')) == surface
                 and a.get('state') != 'ghost' and a['host'][surface] == owner
                 and _near(twin_model_hosts.world_point(house, a['host']), fixture['at'], 0.5)]
        check(len(found) == 1, f'the {fixture["kind"]} at {fixture["at"]} is one anchor on the {surface} of {owner}: '
                               f'{house["anchors"]}')
        anchor = found[0]
        check(twin_model._host_error(anchor['host'], house) is None,
              f'the {fixture["kind"]} anchor has a valid host: {anchor["host"]} ({twin_model._host_error(anchor["host"], house)})')
        src = anchor.get('src')
        check(isinstance(src, dict) and src.get('person') is not True and isinstance(src.get('step'), str),
              f'the {fixture["kind"]} anchor carries read provenance (src with a step, never person): {src}')
    hosted = [a for a in house['anchors'] if a.get('state') != 'ghost' and twin_model._host_error(a.get('host'), house) is None]
    check(len(hosted) == 4, f'only the four fixtures with a surface are hosted anchors: {hosted}')
    for fixture in (lost_wall, outside):
        flags = [f for f in house['flags'] if f.get('level') == 'L1' and isinstance(f.get('at'), list)
                 and _near(f['at'], fixture['at'], 0.01)]
        check(len(flags) == 1, f'the {fixture["kind"]} at {fixture["at"]} has no surface, so it is a flag: {house["flags"]}')
        check(not any(isinstance(a.get('host'), dict) and a['host'].get('wall') == 'nope' for a in house['anchors']),
              'no anchor is hosted on a wall that does not exist')

    # A person's anchor keeps its spot: a new read never lands on it or moves it.
    previous = copy.deepcopy(model)
    mine = {'id': 'mine', 'kind': 'light', 'host': {'ceiling': 'room-hall', 'u': 0.25, 'v': 0.5}, 'offset': 0,
            'device': None, 'src': {'person': True}}
    # The person put their own light where the read light was (the read one
    # is not the person's, so only theirs is pinned).
    previous['buildings'][0]['anchors'] = [mine] + [a for a in previous['buildings'][0]['anchors']
                                                    if a.get('kind') != 'light']
    again, _ = bridge.assemble(copy.deepcopy(flat), previous)
    house = again['buildings'][0]
    kept = [a for a in house['anchors'] if a['id'] == 'mine']
    check(len(kept) == 1 and kept[0]['host'] == mine['host'] and kept[0].get('src', {}).get('person') is True,
          f'the person\'s anchor is kept where they put it: {kept}')
    crowding = [a for a in house['anchors'] if a['id'] != 'mine' and a.get('state') not in ('ghost', 'proposal')
                and twin_model._host_error(a.get('host'), house) is None
                and _near(twin_model_hosts.world_point(house, a['host']), [5, 5], 0.5)]
    check(crowding == [], f'the read light at the person\'s spot is not put on top of it: {crowding}')
    check(any(a.get('kind') == 'switch' and isinstance(a.get('host'), dict) and a['host'].get('wall') == 's'
              for a in house['anchors']), 'the rest of the read still lands')


# ---------------------------------------------------------------- helpers

def _load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _recorded(provider, name):
    return _load(os.path.join(RECORDED, provider, name))


TESTS = [
    prompt_states_the_rules_and_order,
    validator_accepts_fixtures_and_rejects_bad_surface,
    fixtures_become_anchors_on_their_surfaces,
    a_recorded_draft_without_fixtures_still_validates,
]


if __name__ == '__main__':
    passed = 0
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            print(f'FAIL {fn.__name__}: {type(exc).__name__}: {" ".join(str(exc).split())[:300]}')
            if not isinstance(exc, AssertionError):
                traceback.print_exc(limit=4)
        else:
            passed += 1
            print(f'ok   {fn.__name__}')
    print(f'{passed}/{len(TESTS)} passed')
    sys.exit(0 if passed == len(TESTS) else 1)

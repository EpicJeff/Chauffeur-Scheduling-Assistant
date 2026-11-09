"""Extra Task 7 runtime proof for rooms, failed pieces and dependent caches."""
import sys
import traceback
import json
from copy import deepcopy

from test_twin_build_draft import (
    DraftReader, _drawn_house, _house, _read_kinds, check, spike, tb, ts,
)


def test_rooms_in_feet_and_settled_context():
    _drawn_house(photos=0)
    reader = DraftReader(rooms={
        'rooms': [{'name': 'Kitchen', 'level': 'L1', 'polygon': [[1, 15], [10, 15], [10, 25], [1, 25]]}],
        'walls': [{'id': 'partition', 'level': 'L1', 'from': [10, 15], 'to': [10, 25],
                   'height': 9, 'thickness': .33, 'exterior': False}],
    })
    build = tb.start({'part': 'house'}, reader=reader, inline=True)
    check(tb.status(build)['state'] == 'done', tb.status(build)['pause'])
    call = next(c for c in reader.seen if c['kind'] == 'draft_rooms')
    settled = call['context']['settled']
    check(set(settled) == {'levels', 'walls', 'openings'}, settled.keys())
    check(len(settled['levels']) == 2 and all(w['exterior'] for w in settled['walls']), 'settled exterior frame')
    house = _house(ts.current())
    room = next(r for r in house['rooms'] if r['name'] == 'Kitchen')
    wall = next(w for w in house['walls'] if w.get('src', {}).get('step') == 'draft_rooms')
    check(room['polygon'] == reader.rooms['rooms'][0]['polygon'], room)
    check(wall['from'] == [10, 15] and wall['to'] == [10, 25], wall)
    check(room['src']['step'] == wall['src']['step'] == 'draft_rooms', (room, wall))


def test_each_geometric_failure_stays_a_ghost():
    _drawn_house(photos=0)
    answer = spike()
    answer['building']['levels'][1]['outline'] = [[200, 200], [210, 200], [210, 210], [200, 210]]
    answer['building']['roof']['sections'][0]['rect'] = [200, 200, 220, 220]
    opening = next(o for o in answer['building']['openings'] if 'wall' in o)
    opening.update(at=1000, head=100)
    build = tb.start({'part': 'house'}, reader=DraftReader(answer=answer), inline=True)
    check(tb.status(build)['state'] == 'done', tb.status(build)['pause'])
    house = _house(ts.current())
    upper = next(l for l in house['levels'] if l['id'] == 'L2')
    check(upper['state'] == 'ghost' and '2 ft' in upper['why'], upper)
    roof = next(s for s in house['roof']['sections'] if s['rect'][0] == 200)
    check(roof['state'] == 'ghost' and roof['why'] ==
          'This porch roof has no porch or columns beneath it.', roof)
    failed = next(o for o in house['openings'] if o['at'] == 1000)
    check(failed['state'] == 'ghost' and failed['why'], failed)
    # Loading the persisted plan normalizes it again; the bad opening survives.
    check(any(o['id'] == failed['id'] for o in ts.current()['buildings'][0]['openings']), 'ghost survives reload')


def test_small_upper_floor_is_a_ghost():
    _drawn_house(photos=0)
    answer = spike()
    answer['building']['levels'][1]['outline'] = [[1, 15], [2, 15], [2, 16], [1, 16]]
    build = tb.start({'part': 'house'}, reader=DraftReader(answer=answer), inline=True)
    check(tb.status(build)['state'] == 'done', tb.status(build)['pause'])
    level = next(l for l in _house(ts.current())['levels'] if l['id'] == 'L2')
    check(level['state'] == 'ghost' and 'a fifth' in level['why'], level)


def test_checks_follow_snap_and_reread_invalidates_rooms():
    _drawn_house(photos=0)
    answer = spike()
    answer['building']['walls'][0]['to'][0] -= .5
    reader = DraftReader(answer=answer)
    build = tb.start({'part': 'house'}, reader=reader, inline=True)
    check(tb.status(build)['state'] == 'done', tb.status(build)['pause'])
    check(all(w['state'] == 'settled' for w in _house(ts.current())['walls'] if w['level'] == 'L1'),
          'the half-foot gap is welded before closure checks')
    again = DraftReader()
    tb.reread(build, 'draft', reader=again, inline=True)
    check(tb.status(build)['state'] == 'done', tb.status(build)['pause'])
    check(_read_kinds(again).count('outline') == 1
          and [kind for kind in _read_kinds(again) if kind != 'outline'] == ['draft', 'roof_check', 'draft_rooms'],
          _read_kinds(again))


def test_empty_reread_cannot_settle_the_previous_building():
    _drawn_house(photos=0)
    build = tb.start({'part': 'house'}, reader=DraftReader(), inline=True)
    check(tb.status(build)['state'] == 'done', tb.status(build)['pause'])
    reader = DraftReader(answer={'building': {'levels': []}})
    tb.reread(build, 'draft', reader=reader, inline=True)
    check(tb.status(build)['state'] == 'paused', tb.status(build)['pause'])
    # A draft with no levels takes the floor-by-floor fallback. The first floor
    # read is empty as well, so the fallback stops there and the build pauses.
    check(_read_kinds(reader).count('outline') == 1
          and [kind for kind in _read_kinds(reader) if kind != 'outline'] == ['draft', 'draft_level'],
          _read_kinds(reader))
    check(next(c for c in reader.seen if c['kind'] == 'draft_level')['context']['level'] == 'L1',
          'the fallback starts with the first floor')


def test_page_level_mapping_controls_names():
    _drawn_house(photos=0)
    answer = spike()
    anchors = [{'px': [0, 0], 'at': [0, 0]}, {'px': [1, 0], 'at': [70, 0]}]
    answer['pages'] = [{'image': 0, 'level': 'L2', 'anchors': anchors},
                       {'image': 1, 'level': 'L1', 'anchors': anchors}]
    build = tb.start({'part': 'house'}, reader=DraftReader(answer=answer), inline=True)
    check(tb.status(build)['state'] == 'done', tb.status(build)['pause'])
    names = {l['id']: l['name'] for l in _house(ts.current())['levels']}
    check(names == {'L1': 'Upper floor', 'L2': 'Main floor'}, names)


def test_upper_edge_cannot_cross_a_lower_floor_recess():
    _drawn_house(photos=0)
    answer = spike()
    answer['building']['levels'][0]['outline'] = [[0, 0], [40, 0], [40, 10], [10, 10], [10, 40], [0, 40]]
    # All vertices are inside the lower floor; the diagonal crosses its recess.
    answer['building']['levels'][1]['outline'] = [[5, 5], [35, 5], [35, 8], [5, 35]]
    build = tb.start({'part': 'house'}, reader=DraftReader(answer=answer), inline=True)
    check(tb.status(build)['state'] == 'done', tb.status(build)['pause'])
    upper = next(l for l in _house(ts.current())['levels'] if l['id'] == 'L2')
    check(upper['state'] == 'ghost' and '2 ft' in upper['why'], upper)


def test_open_ends_only_and_rooms_keep_the_level():
    _drawn_house(photos=0)
    answer = spike()
    answer['building']['walls'] = [w for w in answer['building']['walls'] if w['id'] != 'u5']
    reader = DraftReader(answer=answer)
    build = tb.start({'part': 'house'}, reader=reader, inline=True)
    check(tb.status(build)['state'] == 'done', tb.status(build)['pause'])
    house = _house(ts.current())
    upper = next(l for l in house['levels'] if l['id'] == 'L2')
    check(upper['state'] == 'settled', upper)
    walls = [w for w in house['walls'] if w['level'] == 'L2' and w['exterior']]
    ghosts = [w for w in walls if w['state'] == 'ghost']
    check(len(ghosts) == 2 and all(abs(w['to'][1] - 52) < .1 or abs(w['from'][1] - 52) < .1
                                  for w in ghosts), ghosts)
    context = next(c['context']['settled'] for c in reader.seen if c['kind'] == 'draft_rooms')
    check(any(l['id'] == 'L2' for l in context['levels']), context['levels'])
    check(all(w['state'] == 'settled' for w in context['walls']), context['walls'])

    # The check's 0.1 ft closure tolerance also applies to a one-foot gap.
    # Isolate it from snap, which is allowed to weld a gap of exactly 1 ft.
    house = deepcopy(spike()['building'])
    wall = next(w for w in house['walls'] if w['id'] == 'u5')
    wall['to'][0] += 1
    tb._check_draft(house)
    check(next(l for l in house['levels'] if l['id'] == 'L2').get('state') != 'ghost', house['levels'])
    check({w['id'] for w in house['walls'] if w.get('state') == 'ghost'} == {'u5', 'u6'}, house['walls'])


def test_ghost_logs_group_reasons_and_exclude_model_notes():
    _drawn_house(photos=0)
    answer = spike()
    openings = [o for o in answer['building']['openings'] if 'wall' in o][:5]
    for opening in openings:
        opening.update(head=100)
    answer['building']['openings'] = openings
    answer['notes'] = ['L1 ceiling/plate 10 (L2 at 10.9), raw-piece-id']
    build = tb.start({'part': 'house'}, reader=DraftReader(answer=answer), inline=True)
    st = tb.status(build)
    check(st['state'] == 'done', st['pause'])
    house = _house(ts.current())
    check(len([o for o in house['openings'] if o['state'] == 'ghost']) == 5, house['openings'])
    logs = [e['text'] for e in st['events'] if e['type'] == 'log']
    # The panel groups ghost events, so the engine logs no grouped summary.
    ghost_ids = {o['id'] for o in house['openings'] if o['state'] == 'ghost'}
    ghosts = [e for e in st['events'] if e['type'] == 'ghost' and 'span or height' in e.get('why', '')]
    check(len(ghosts) == 5 and {e['piece']['id'] for e in ghosts} == ghost_ids, ghosts)
    check(not [line for line in logs if 'span or height' in line
               or (line[:1].isdigit() and 'checking' in line)], logs)
    raw_ids = [p['id'] for key in ('walls', 'openings', 'levels') for p in house[key]]
    check(not any(raw in line for line in logs for raw in [*raw_ids, 'raw-piece-id']), logs)
    state = tb._get(build)
    step = next(s for s in state['steps'] if s['id'] == 'draft')
    cached = json.loads(tb._cache_path(state, step).read_text(encoding='utf-8'))
    check(cached['fragment']['notes'] == answer['notes'],
          'model notes remain in the cached build record')


def test_roof_outline_recess_and_porch_support():
    # All corners are inside this U-shaped footprint; one edge crosses its recess.
    house = deepcopy(spike()['building'])
    house['levels'] = [dict(house['levels'][0], outline=[[0, 0], [40, 0], [40, 40],
                          [30, 40], [30, 10], [10, 10], [10, 40], [0, 40]])]
    house['porch'] = None
    house['roof']['sections'] = [dict(house['roof']['sections'][0], rect=[5, 5, 35, 15], plate=10)]
    tb._check_draft(house)
    check(house['roof']['sections'][0]['state'] == 'ghost', house['roof'])
    for support in ('polygon', 'columns', 'none', 'unrelated'):
        house = deepcopy(spike()['building'])
        section = dict(house['roof']['sections'][0], rect=[100, 100, 110, 110], plate=10)
        house['roof']['sections'] = [section]
        house['porch'] = {'polygon': [], 'columns': []}
        if support == 'polygon':
            house['porch']['polygon'] = [[100, 100], [110, 100], [110, 110], [100, 110]]
        elif support == 'columns':
            house['porch']['columns'] = [{'at': [101, 101]}, {'at': [109, 101]}]
        elif support == 'unrelated':
            house['porch']['polygon'] = [[200, 200], [210, 200], [210, 210], [200, 210]]
            house['porch']['columns'] = [{'at': [201, 201]}, {'at': [209, 201]}]
        tb._check_draft(house)
        check((section.get('state') == 'ghost') == (support in ('none', 'unrelated')), (support, section))


TESTS = (test_rooms_in_feet_and_settled_context, test_each_geometric_failure_stays_a_ghost,
         test_small_upper_floor_is_a_ghost, test_checks_follow_snap_and_reread_invalidates_rooms,
         test_empty_reread_cannot_settle_the_previous_building, test_page_level_mapping_controls_names,
         test_upper_edge_cannot_cross_a_lower_floor_recess, test_open_ends_only_and_rooms_keep_the_level,
         test_ghost_logs_group_reasons_and_exclude_model_notes, test_roof_outline_recess_and_porch_support)

if __name__ == '__main__':
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__)
            traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} passed')
    sys.exit(bool(failed))

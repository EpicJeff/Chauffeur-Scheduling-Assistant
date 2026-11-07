"""Deterministic yard composition from the kit's rules (spec
docs/superpowers/specs/2026-11-06-house-digital-twin-design.md section 8.4;
plan Task 5). Pure: no storage writes, no network.

Fixture geometry (feet): the pool house walls run x 0..31, y 0..22 (front
wall on y=0 faces the patio, which spans y -34..0); the porch is x 31..38;
the rear door (sill 0) sits at x=16.5 on y=22; the lot is x -12..140,
y -110..32, so only its right (x=140) and front (y=-110) edges are 25 ft or
more from the building.

Run from chauffeur/:  python tests/test_twin_compose.py
"""
import copy
import json
import math
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_compose_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import twin_compose as tcm  # noqa: E402
from services import twin_library as tl  # noqa: E402
from services import twin_plan as tp  # noqa: E402

_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_poolhouse.plan.json')
KIT = tl.kit('modern_farmhouse')
C = KIT['composition']
FOOTPRINT = [[-0.25, -0.25], [38.0, -0.25], [38.0, 22.25], [-0.25, 22.25]]   # walls + porch
REAR_DOOR_X = 16.5


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _plan():
    with open(_FIXTURE, encoding='utf-8') as f:
        return tp.normalize(json.load(f))[0]


def _inside(pt, poly):
    x, y = pt
    inside = False
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    t = 0 if dx == dy == 0 else max(0, min(1, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def _poly_dist(p, poly):
    return min(_seg_dist(p, poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))


def _ours(items):
    return [i for i in items if i.get('by') == 'compose']


def scenario_compose_is_deterministic():
    a, _ = tcm.compose(_plan(), KIT, seed=7)
    b, _ = tcm.compose(_plan(), KIT, seed=7)
    check(a == b, 'same plan, kit and seed give the same yard')
    c, _ = tcm.compose(_plan(), KIT, seed=8)
    check(c != a, 'another seed gives another yard')


def scenario_compose_ids_are_stable_and_tagged():
    a, _ = tcm.compose(_plan(), KIT, seed=7)
    site = a['site']
    items = _ours(site['beds']) + _ours(site['planting']) + _ours(site['edges'])
    check(items and all(str(i.get('id', '')).startswith('cmp-') for i in items), 'every compose item has a cmp- id')
    ids = [i['id'] for i in items]
    check(len(ids) == len(set(ids)), 'ids are unique')


def scenario_compose_does_not_mutate_its_input():
    p = _plan()
    before = copy.deepcopy(p)
    tcm.compose(p, KIT, seed=1)
    check(p == before, 'input untouched')


def scenario_compose_is_idempotent_and_keeps_foreign_items():
    p = _plan()
    hand = {'kind': 'tree', 'preset': 'Oak Medium', 'at': [60.0, -60.0], 'height': 35, 'seed': 99}
    p['site']['planting'].append(hand)
    once, _ = tcm.compose(p, KIT, seed=3)
    twice, _ = tcm.compose(once, KIT, seed=3)
    check(once == twice, 'composing a composed plan changes nothing')
    check(sum(1 for i in twice['site']['planting'] if i.get('by') is None and i['seed'] == 99) == 1,
          'the hand-placed tree is kept once')


def scenario_removed_and_moved_compose_items_survive_recompose():
    p, _ = tcm.compose(_plan(), KIT, seed=3)
    shrubs = [i for i in _ours(p['site']['planting']) if i['kind'] == 'shrub']
    gone, moved = shrubs[0]['id'], shrubs[1]['id']
    after = copy.deepcopy(p)
    after['site']['planting'] = [i for i in after['site']['planting'] if i.get('id') != gone]
    for i in after['site']['planting']:
        if i.get('id') == moved:
            i['at'] = [i['at'][0] + 1.5, i['at'][1]]
            new_at = i['at']
    after = tp.record_compose_overrides(p, after)
    ov = after['site']['compose_overrides']
    check(gone in ov['removed'] and ov['moved'].get(moved) == new_at, ov)
    again, _ = tcm.compose(after, KIT, seed=3)
    ids = {i.get('id'): i for i in again['site']['planting']}
    check(gone not in ids, 'a deleted compose shrub is not resurrected')
    check(ids[moved]['at'] == new_at, 'a moved compose shrub keeps its new place')


def scenario_a_move_that_lands_in_the_pool_is_not_applied():
    p, _ = tcm.compose(_plan(), KIT, seed=3)
    shrub = [i for i in _ours(p['site']['planting']) if i['kind'] == 'shrub'][0]
    target = [10.0, -20.0]                                  # inside the pool (x 2..36, y -28..-12)
    p['site']['compose_overrides'] = {'removed': [], 'moved': {shrub['id']: target}}
    again, notes = tcm.compose(p, KIT, seed=3)
    placed = {i.get('id'): i for i in again['site']['planting']}[shrub['id']]
    check(placed['at'] != target, 'a move into the pool is not applied')
    check(any(shrub['id'] in n for n in notes), f'and the person is told: {notes}')
    check(again['site']['compose_overrides']['moved'].get(shrub['id']) == target,
          'the override stays recorded, so it applies again if the pool moves away')


def scenario_beds_hug_the_walls_and_skip_doors():
    p, _ = tcm.compose(_plan(), KIT, seed=1)
    beds = _ours(p['site']['beds'])
    check(beds, 'foundation beds were made')
    depth = C['foundation_bed_depth_ft']
    rear = [b for b in beds if min(pt[1] for pt in b['polygon']) >= 22.0]
    left = [b for b in beds if max(pt[0] for pt in b['polygon']) <= 0.0]
    check(rear and left, 'beds along the rear and left walls')
    check(not [b for b in beds if max(pt[1] for pt in b['polygon']) <= 0.0], 'no bed on the patio side')
    check(not [b for b in beds if min(pt[0] for pt in b['polygon']) >= 31.0 and
               max(pt[1] for pt in b['polygon']) <= 22.25], 'no bed under the porch')
    for b in rear:
        ys = [pt[1] for pt in b['polygon']]
        check(abs(min(ys) - 22.25) < 0.01 and abs((max(ys) - min(ys)) - depth) < 0.01,
              f'rear bed starts at the wall face and is {depth} ft deep: {b["polygon"]}')
        xs = [pt[0] for pt in b['polygon']]
        check(max(xs) <= REAR_DOOR_X - C['door_clearance_ft'] + 0.01 or
              min(xs) >= REAR_DOOR_X + C['door_clearance_ft'] - 0.01,
              f'no rear bed within {C["door_clearance_ft"]} ft of the door: {xs}')
    for b in left:
        xs = [pt[0] for pt in b['polygon']]
        check(abs(max(xs) + 0.25) < 0.01 and abs((max(xs) - min(xs)) - depth) < 0.01, b['polygon'])


def scenario_shrubs_sit_in_beds_in_odd_groups():
    p, _ = tcm.compose(_plan(), KIT, seed=1)
    beds = _ours(p['site']['beds'])
    shrubs = [i for i in _ours(p['site']['planting']) if i['kind'] == 'shrub']
    check(shrubs, 'shrubs were planted')
    lo, hi = C['shrub_height_ft']
    for s in shrubs:
        check(any(_inside(s['at'], b['polygon']) for b in beds), f'shrub in a bed: {s["at"]}')
        check(lo <= s['height'] <= hi and s['preset'] in KIT['shrubs'], s)
    for b in beds:
        mine = [s for s in shrubs if _inside(s['at'], b['polygon'])]
        horiz = (max(pt[0] for pt in b['polygon']) - min(pt[0] for pt in b['polygon'])) >= \
                (max(pt[1] for pt in b['polygon']) - min(pt[1] for pt in b['polygon']))
        mine.sort(key=lambda s: s['at'][0] if horiz else s['at'][1])
        runs, last = [], None
        for s in mine:
            if s['preset'] == last:
                runs[-1] += 1
            else:
                runs.append(1)
                last = s['preset']
        for r in runs[:-1]:
            check(r in C['group_sizes'], f'group of {r} in bed {b["id"]}: {runs}')
        if mine:
            gaps = [abs((b2['at'][0] - a2['at'][0]) if horiz else (b2['at'][1] - a2['at'][1]))
                    for a2, b2 in zip(mine, mine[1:])]
            check(all(abs(g - C['shrub_spacing_ft']) < 0.01 for g in gaps), f'shrub spacing: {gaps}')


def scenario_nothing_lands_where_it_cannot():
    p, _ = tcm.compose(_plan(), KIT, seed=1)
    pool = p['site']['pool']['polygon']
    patio = p['site']['hardscape'][0]['polygon']
    for i in _ours(p['site']['planting']):
        at = i['at']
        check(not _inside(at, FOOTPRINT), f'not in the building: {at}')
        check(not _inside(at, patio), f'not on the patio: {at}')
        check(not _inside(at, pool) and _poly_dist(at, pool) >= C['pool_clearance_ft'], f'clear of the pool: {at}')
        check(_inside(at, p['site']['lot']), f'inside the lot: {at}')


def scenario_backdrop_lines_far_edges_only():
    p, _ = tcm.compose(_plan(), KIT, seed=1)
    trees = [i for i in _ours(p['site']['planting']) if i['kind'] == 'tree']
    check(trees, 'backdrop trees were planted')
    lo, hi = C['backdrop_height_ft']
    right = [t for t in trees if 140 - t['at'][0] <= 20]
    front = [t for t in trees if t['at'][1] + 110 <= 20]
    check(len(right) + len(front) == len(trees), 'every backdrop tree is along the right or front edge')
    check(not [t for t in trees if 32 - t['at'][1] < 20 and t['at'][0] < 100], 'none along the near rear edge')
    check(not [t for t in trees if t['at'][0] + 12 < 20 and t['at'][1] > -80], 'none along the near left edge')
    for t in trees:
        check(lo <= t['height'] <= hi and t['preset'] in KIT['backdrop_trees'], t)
        check(_poly_dist(t['at'], FOOTPRINT) >= C['backdrop_min_building_ft'], f'far from the building: {t["at"]}')
    offs = sorted({round(140 - t['at'][0], 2) for t in right})
    check(offs == [6.0, 6.0 + C['backdrop_row_gap_ft']], f'two rows, 6 ft and 16 ft in from the right edge: {offs}')
    for row in offs:
        ys = sorted(t['at'][1] for t in right if round(140 - t['at'][0], 2) == row)
        gaps = [b - a for a, b in zip(ys, ys[1:])]
        sp, j = C['backdrop_spacing_ft'], C['backdrop_jitter_ft']
        check(len(ys) >= 7 and all(sp - j - 0.01 <= g <= sp + j + 0.01 for g in gaps), f'row at {row}: {gaps}')


def scenario_edges_follow_the_lawn():
    p, _ = tcm.compose(_plan(), KIT, seed=1)
    edges = _ours(p['site']['edges'])
    check(edges and all(len(e['points']) >= 2 for e in edges), 'edge polylines exist')
    patio_edges = [e for e in edges if all(abs(pt[1] + 34) < 0.01 or abs(pt[0] + 4) < 0.01 or abs(pt[0] - 44) < 0.01
                                           for pt in e['points'])]
    check(patio_edges, 'the lawn edge along the patio is traced')


def scenario_rotated_building_moves_its_beds():
    # Review finding (Codex adversarial review, house editor plan Task 4):
    # composition ignored building rotation, so beds and clearances kept the
    # old footprint and planting could land inside the rendered house.
    def rot90(pt):
        return [-pt[1], pt[0]]
    # Isolate the rigid rotation: a lot far larger than the house and no fixed
    # site blockers (patio, pool, fence), so the lot's own clearance rules
    # cannot change which beds exist; the real fixture's clearances still run
    # in the planting check below.
    plain = _plan()
    plain['site'] = {'lot': [[-200, -200], [200, -200], [200, 200], [-200, 200]]}
    turned = copy.deepcopy(plain)
    turned['buildings'][0]['rotation'] = 90
    a, _ = tcm.compose(plain, KIT, seed=1)
    b, _ = tcm.compose(turned, KIT, seed=1)
    turned_footprint = [rot90(p) for p in FOOTPRINT]
    beds_a = {x['id']: x for x in a['site']['beds'] if x.get('by') == 'compose'}
    beds_b = {x['id']: x for x in b['site']['beds'] if x.get('by') == 'compose'}
    check(beds_a and set(beds_a) == set(beds_b), (sorted(beds_a), sorted(beds_b)))
    for bid, bed in beds_a.items():
        want = [rot90(p) for p in bed['polygon']]
        got = beds_b[bid]['polygon']
        check(len(want) == len(got) and all(abs(w[0] - g[0]) < 0.01 and abs(w[1] - g[1]) < 0.01
                                            for w, g in zip(want, got)), (bid, want, got))
    real = _plan()
    real['buildings'][0]['rotation'] = 90
    c, _ = tcm.compose(real, KIT, seed=1)
    for item in b['site']['planting'] + c['site']['planting']:
        if item.get('by') == 'compose':
            check(not _inside(item['at'], turned_footprint), f'planted inside the turned house: {item}')


if __name__ == '__main__':
    for fn in (scenario_rotated_building_moves_its_beds,
               scenario_compose_is_deterministic,
               scenario_compose_ids_are_stable_and_tagged,
               scenario_compose_does_not_mutate_its_input,
               scenario_compose_is_idempotent_and_keeps_foreign_items,
               scenario_removed_and_moved_compose_items_survive_recompose,
               scenario_a_move_that_lands_in_the_pool_is_not_applied,
               scenario_beds_hug_the_walls_and_skip_doors,
               scenario_shrubs_sit_in_beds_in_odd_groups,
               scenario_nothing_lands_where_it_cannot,
               scenario_backdrop_lines_far_edges_only,
               scenario_edges_follow_the_lawn):
        fn()
        print('  ok ', fn.__name__)

"""The bridge between the flat schema-2 plan and the connected model: assemble,
flatten, migration and ownership (spec docs/superpowers/specs/2026-11-09-house-
connected-model-design.md sections 4.6a and 4.7; plan docs/superpowers/plans/
2026-11-09-house-connected-model-pieces-1-2.md Task 5, Review Focus 3; brief
.superpowers/sdd/2026-11-09-house-connected-model-pieces-1-2/task-5-brief.md).

Ledger rulings that amend the brief:
- R1: migration (assemble with previous=None) adds a separator along every
  stored room polygon edge no wall covers within 1 ft; each added separator
  carries the migration flag; extra regions are allowed (named Room) and
  reported; every stored room name and id must survive.
- R2: flatten never puts proposal pieces into walls, openings or roof
  sections; they ride only in `proposals`, with the full piece.

Module under test: services/twin_model_bridge.py
  assemble(flat, previous=None) -> (model, notes)
  flatten(model) -> flat

The household fixture (tests/fixtures/twin_model/household-2026-11-09.json) is
the real house: main house 60 walls, 27 openings (3 on gables), 25 rooms all
named Room, 14 roof sections (one with dormer_of), 2 porches, 2 stairs; pool
house 13 walls, 8 openings (3 on gables), 8 rooms, 2 roof sections, 1 porch,
1 stair.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_model_bridge.py
"""
import copy
import json
import os
import sys
import tempfile
import traceback

if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_model_bridge_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import twin_plan  # noqa: E402

try:
    from services import twin_model_bridge as bridge  # noqa: E402
    _IMPORT_ERROR = None
except ImportError as exc:  # the module does not exist until Task 5 lands
    bridge = None
    _IMPORT_ERROR = exc


HOUSEHOLD = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         'fixtures', 'twin_model', 'household-2026-11-09.json')
SEPARATOR_COPY = 'I added an invisible wall here to keep the {a} and the {b} apart; check it.'
SEPARATOR_COPY_GENERIC = 'I added an invisible wall here to keep two rooms apart; check it.'
TOL = 1e-6


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _b():
    if bridge is None:
        raise _IMPORT_ERROR
    return bridge


# ---------------------------------------------------------------- helpers

def _household():
    with open(HOUSEHOLD, encoding='utf-8') as fh:
        return json.load(fh)


_MIGRATED = None


def _migrated():
    """The household migrated once (assemble with previous=None), then shared read-only."""
    global _MIGRATED
    if _MIGRATED is None:
        _MIGRATED = _b().assemble(_household(), None)
    return _MIGRATED


def _by_id(items):
    return {item['id']: item for item in items}


def _live(pieces):
    return [p for p in pieces if p.get('state') != 'proposal']


def _joints(building):
    return {j['id']: j['at'] for j in building['joints']}


def _ends(building, wall):
    joints = _joints(building)
    return joints[wall['joints'][0]], joints[wall['joints'][1]]


def _dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _near(a, b, tol=TOL):
    return _dist(a, b) <= tol


def _same_segment(a, b, p, q, tol=TOL):
    return (_near(a, p, tol) and _near(b, q, tol)) or (_near(a, q, tol) and _near(b, p, tol))


def _area(poly):
    return abs(sum(poly[i][0] * poly[i - 1][1] - poly[i - 1][0] * poly[i][1]
                   for i in range(len(poly)))) / 2


def _inside(pt, poly):
    x, y = pt
    hit = False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i - 1], poly[i]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def _share_inside(poly, other, step=0.5):
    """Fraction of a 0.5 ft grid of points inside `poly` that also lie inside `other`."""
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    total = shared = 0
    x = min(xs) + step / 2
    while x < max(xs):
        y = min(ys) + step / 2
        while y < max(ys):
            if _inside((x, y), poly):
                total += 1
                shared += _inside((x, y), other)
            y += step
        x += step
    return shared / total if total else 0.0


def _rect_poly(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _wall(wid, a, b, exterior=False, thickness=None, height=9):
    return {'id': wid, 'level': 'L1', 'from': list(a), 'to': list(b), 'exterior': exterior,
            'thickness': thickness if thickness is not None else (0.5 if exterior else 0.33),
            'height': height}


def _box_walls(east, north=10):
    return [_wall('s', (0, 0), (east, 0), True), _wall('e', (east, 0), (east, north), True),
            _wall('n', (east, north), (0, north), True), _wall('w', (0, north), (0, 0), True)]


def _flat(walls, rooms, openings=(), sections=(), lights=(), fixtures=()):
    return {'schema': 'chauffeur.twin.plan/2', 'units': 'ft', 'materials': {},
            'buildings': [{'id': 'b1', 'name': 'Test house', 'position': [0, 0], 'rotation': 0,
                           'base': 0,
                           'levels': [{'id': 'L1', 'name': 'main floor', 'elevation': 0,
                                       'ceiling': 9}],
                           'walls': list(walls), 'openings': list(openings),
                           'rooms': list(rooms),
                           'roof': {'sections': list(sections), 'extensions': []},
                           'stairs': [], 'fixtures': list(fixtures), 'lights': list(lights),
                           'porches': []}],
            'site': {}}


def _section_form(section):
    """A section's drawn form: kind, rect, plate, overhang, ridge or low side,
    every end's style, and the effective pitch of every sloped edge
    (pitches[side] or pitch), so `pitches` and `ends` compare by meaning."""
    kind = section['kind']
    pitches = section.get('pitches') or {}

    def pitch(side):
        return pitches.get(side, section.get('pitch'))

    form = {'kind': kind, 'rect': [round(v, 6) for v in section['rect']],
            'plate': round(section['plate'], 6), 'overhang': round(section.get('overhang', 1), 6)}
    if kind in ('gable', 'hip'):
        ridge = section['ridge']
        form['ridge'] = ridge
        for side in (('y0', 'y1') if ridge == 'x' else ('x0', 'x1')):
            form['pitch ' + side] = round(pitch(side), 6)
        for end in (ridge + '0', ridge + '1'):
            style = (section.get('ends') or {}).get(end, kind)
            form['end ' + end] = style
            if style in ('hip', 'clip'):
                form['pitch ' + end] = round(pitch(end), 6)
    elif kind == 'shed':
        form['low_side'] = section['low_side']
        form['pitch ' + section['low_side']] = round(pitch(section['low_side']), 6)
    return form


def _no_dropped(notes, what):
    dropped = [n for n in notes if n.startswith('Dropped')]
    check(not dropped, f'{what}: twin_plan.normalize dropped pieces: {dropped[:6]}')


# ---------------------------------------------------------------- household migration


def _expected_site():
    """The schema-2 site as normalize now returns it: since v2.499.821 a fire pit without a
    shape reads as round (twin_plan sets shape: 'round'). Nothing else may change."""
    site = copy.deepcopy(_household()['site'])
    pits = site.get('fire_pit')
    for pit in pits if isinstance(pits, list) else [pits] if pits else []:
        pit.setdefault('shape', 'round')
    return site

def test_household_migrates_and_keeps_every_room_name_and_opening():
    old = _by_id(_household()['buildings'])
    model, _notes = _migrated()
    check(model['schema'] == 'chauffeur.twin.plan/3', f"schema is {model.get('schema')}")
    check(model['units'] == 'ft', 'units must stay ft')
    new = _by_id(model['buildings'])
    check(set(new) == {'main-house', 'pool-house'}, f'buildings {sorted(new)}')
    check(len(old['main-house']['rooms']) == 25, 'fixture: the main house stores 25 rooms')
    for bid, ob in old.items():
        nb = new[bid]
        check(nb['proposals'] == [], f'{bid}: a migration has nothing to propose, got {nb["proposals"]}')
        rooms = _by_id(nb['rooms'])
        # Every stored room survives with its id, name and level, and its derived
        # region is the stored room's space (R1: separators enclose every room).
        for r in ob['rooms']:
            got = rooms.get(r['id'])
            check(got is not None, f"{bid}: stored room {r['id']} ({r['name']}) was dropped")
            check(got['name'] == r['name'], f"{bid}: room {r['id']} renamed {r['name']!r} -> {got['name']!r}")
            check(got['level'] == r['level'], f"{bid}: room {r['id']} moved level")
            check(got.get('kind') == 'room', f"{bid}: room {r['id']} kind {got.get('kind')!r}")
            ratio = _area(got['polygon']) / _area(r['polygon'])
            check(0.8 <= ratio <= 1.2,
                  f"{bid}: room {r['id']} area {_area(got['polygon']):.1f} vs stored {_area(r['polygon']):.1f}")
            share = _share_inside(got['polygon'], r['polygon'])
            check(share >= 0.8, f"{bid}: room {r['id']} region lies {share:.0%} inside its stored polygon")
        stored = {r['id'] for r in ob['rooms']}
        extra = [r for r in nb['rooms'] if r['id'] not in stored and r.get('kind') == 'room']
        check(all(r['name'] == 'Room' for r in extra),
              f"{bid}: extra regions must be named Room, got {[r['name'] for r in extra]}")
        # Every opening survives with today's fields, hosted where it was or flagged.
        walls = _by_id(_live(nb['walls']))
        roofs = {r['id'] for r in _live(nb['roofs'])}
        openings = _by_id(nb['openings'])
        old_walls = _by_id(ob['walls'])
        flagged_openings = 0
        for o in ob['openings']:
            m = openings.get(o['id'])
            check(m is not None, f"{bid}: opening {o['id']} was dropped")
            for key in ('width', 'sill', 'head', 'kind'):
                check(m.get(key) == o[key], f"{bid}: opening {o['id']} {key} {o[key]} -> {m.get(key)}")
            flagged = any(o['id'] in str(f.get('piece', '')) for f in nb['flags'])
            if 'gable' in o:
                hosted = isinstance(m.get('gable'), dict) and m['gable'].get('roof') in roofs
            else:
                hosted = False
                w = walls.get(m.get('wall'))
                if w is not None and (m['wall'] == o['wall'] or m['wall'].startswith(o['wall'] + '~')):
                    a, b = _ends(nb, w)
                    length = _dist(a, b)
                    ow = old_walls[o['wall']]
                    olen = _dist(ow['from'], ow['to'])
                    was = [ow['from'][i] + (ow['to'][i] - ow['from'][i]) * o['at'] / olen for i in (0, 1)]
                    now = [a[i] + (b[i] - a[i]) * m['at'] / length for i in (0, 1)]
                    hosted = (m['at'] - m['width'] / 2 >= -1e-6
                              and m['at'] + m['width'] / 2 <= length + 1e-6
                              and _dist(was, now) <= 1.0)
            check(hosted or flagged, f"{bid}: opening {o['id']} is neither hosted where it was nor flagged: {m}")
            flagged_openings += (not hosted) and flagged
        print(f'    {bid}: {len(ob["rooms"])} rooms in, {len(stored)} kept by id and name, '
              f'{len(extra)} extra regions; {len(nb["flags"])} flags; '
              f'{flagged_openings} openings flagged instead of hosted')
    pool = new['pool-house']
    names = {r['name'] for r in pool['rooms']}
    for name in ('Pool Lounge', 'SHWR.', 'CHANGING', 'EXERCISE', 'CLOSET'):
        check(name in names, f'pool house lost the room name {name}: {sorted(names)}')
    lounge = _by_id(pool['rooms'])['room:5d7de10ca48340ae85c407d22337c6f7']
    check(lounge.get('ha_area') == 'Pool Lounge', f"Pool Lounge lost its area: {lounge.get('ha_area')}")
    check((lounge.get('src') or {}).get('person') is True, 'Pool Lounge was a person edit and must stay one')
    check(model['site'] == _expected_site(), 'the site must carry over exactly as in schema 2')


def test_household_walls_stay_within_a_foot():
    old = _by_id(_household()['buildings'])
    flat = _b().flatten(copy.deepcopy(_migrated()[0]))
    new = _by_id(flat['buildings'])
    for bid, ob in old.items():
        flat_walls = new[bid]['walls']
        for w in ob['walls']:
            parts = [f for f in flat_walls if f['id'] == w['id'] or f['id'].startswith(w['id'] + '~')]
            check(parts, f"{bid}: wall {w['id']} is missing after migration")
            a, b = w['from'], w['to']
            length = _dist(a, b)
            d = [(b[0] - a[0]) / length, (b[1] - a[1]) / length]
            ts = []
            for part in parts:
                check(part.get('kind') == 'solid', f"{bid}: wall {part['id']} kind {part.get('kind')!r}")
                for key in ('level', 'exterior'):
                    check(part[key] == w[key], f"{bid}: wall {part['id']} {key} {w[key]} -> {part[key]}")
                for key in ('thickness', 'height'):
                    check(abs(part[key] - w[key]) <= TOL, f"{bid}: wall {part['id']} {key} {w[key]} -> {part[key]}")
                for p in (part['from'], part['to']):
                    off = abs((p[0] - a[0]) * d[1] - (p[1] - a[1]) * d[0])
                    check(off <= 1.0, f"{bid}: wall {part['id']} end {p} is {off:.2f} ft off its old line")
                    ts.append(((p[0] - a[0]) * d[0] + (p[1] - a[1]) * d[1], p))
            start, end = min(ts)[1], max(ts)[1]
            check(_dist(start, a) <= 1.0 + TOL and _dist(end, b) <= 1.0 + TOL,
                  f"{bid}: wall {w['id']} {a}->{b} became {start}->{end} across {len(parts)} part(s)")


def test_household_roofs_round_trip():
    old = _by_id(_household()['buildings'])
    model = copy.deepcopy(_migrated()[0])
    mb = _by_id(model['buildings'])
    new = _by_id(_b().flatten(copy.deepcopy(model))['buildings'])
    expect_roofs = {'main-house': 13, 'pool-house': 2}
    expect_dormers = {'main-house': 1, 'pool-house': 0}
    for bid, ob in old.items():
        check(len(_live(mb[bid]['roofs'])) == expect_roofs[bid],
              f"{bid}: {len(mb[bid]['roofs'])} roofs, expected one per non-dormer section ({expect_roofs[bid]})")
        check(len(mb[bid]['dormers']) == expect_dormers[bid],
              f"{bid}: {len(mb[bid]['dormers'])} dormers, expected {expect_dormers[bid]}")
        sections = new[bid]['roof']['sections']
        plain = [s for s in sections if not s.get('dormer_of')]
        olds = [s for s in ob['roof']['sections'] if not s.get('dormer_of')]
        check(len(plain) == len(olds), f'{bid}: {len(plain)} flattened sections for {len(olds)} old ones')
        for s in olds:
            same = [f for f in plain if all(abs(x - y) <= TOL for x, y in zip(f['rect'], s['rect']))]
            check(len(same) == 1, f"{bid}: section {s['id']} rect {s['rect']} matched {len(same)} sections")
            check(_section_form(same[0]) == _section_form(s),
                  f"{bid}: section {s['id']} came back as {_section_form(same[0])}, was {_section_form(s)}")
    # The dormer comes back via dormer_sections, as the cross gable today's generator draws.
    from services import twin_model_roofs
    old_dormer = [s for s in old['main-house']['roof']['sections'] if s.get('dormer_of')]
    check(len(old_dormer) == 1, 'fixture: the main house has one dormer_of section')
    old_dormer = old_dormer[0]
    got = [s for s in new['main-house']['roof']['sections'] if s.get('dormer_of')]
    check(len(got) == 1, f'main house: {len(got)} dormer sections after flatten, expected 1')
    got = got[0]
    dormer = mb['main-house']['dormers'][0]
    parent = _by_id(mb['main-house']['roofs'])[dormer['roof']]
    via = [s for s in twin_model_roofs.dormer_sections(dormer, parent) if s.get('dormer_of')]
    check(len(via) == 1 and _section_form(via[0]) == _section_form(got)
          and all(abs(x - y) <= TOL for x, y in zip(via[0]['dormer_of'], got['dormer_of'])),
          f'the flattened dormer section {got} is not what dormer_sections gives: {via}')
    check(all(abs(x - y) <= TOL for x, y in zip(got['dormer_of'], old_dormer['dormer_of'])),
          f"dormer_of {got['dormer_of']} != {old_dormer['dormer_of']}")
    check(got['kind'] == 'gable' and got['ridge'] == 'y', f'the dormer is a cross gable on y: {got}')
    check(abs(got['rect'][0] - 21) <= TOL and abs(got['rect'][2] - 33) <= TOL,
          f"the dormer keeps its 12 ft width from x 21 to 33: {got['rect']}")
    check(abs(got['pitch'] - 10) <= TOL and abs(got['plate'] - 20) <= TOL,
          f'the dormer keeps pitch 10 and plate 20: {got}')


def _bbox(points):
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def test_household_choice_roofs_become_person_owned():
    # Ruling R14: a roof whose area matches a roof.choices rect within 1 ft is the
    # person's; choices are not carried into schema 3. The fixture has one choice
    # (main house, rect [0, 25.33, 14.33, 44.5]) and none on the pool house.
    old = _by_id(_household()['buildings'])
    new = _by_id(copy.deepcopy(_migrated()[0])['buildings'])
    for bid, ob in old.items():
        choices = ob['roof'].get('choices') or []
        roofs = _live(new[bid]['roofs'])
        person = [r for r in roofs if (r.get('src') or {}).get('person') is True]
        check(len(person) == len(choices),
              f'{bid}: {len(person)} person-owned roofs for {len(choices)} choices')
        for c in choices:
            match = [r for r in person
                     if all(abs(a - b) <= 1.0 for a, b in zip(_bbox(r['area']), c['rect']))]
            check(len(match) == 1, f"{bid}: the choice at {c['rect']} owns {len(match)} roofs")
        check('choices' not in new[bid] and not any('choices' in r for r in new[bid]['roofs']),
              f'{bid}: choices must not be carried into schema 3')
    check(len(old['main-house']['roof']['choices']) == 1, 'fixture: the main house has one choice')


def test_household_roof_flags_become_model_flags():
    # Ruling R14: each roof.flags entry becomes a model flag with the same text at
    # its block_rect centre (main house 5 flags, pool house 1).
    old = _by_id(_household()['buildings'])
    new = _by_id(copy.deepcopy(_migrated()[0])['buildings'])
    for bid, ob in old.items():
        flags = new[bid]['flags']
        for f in ob['roof']['flags']:
            x0, y0, x1, y1 = f['block_rect']
            got = [m for m in flags if m.get('text') == f['text']]
            check(len(got) == 1, f"{bid}: roof flag {f['text']!r} appears {len(got)} times")
            check(_near(got[0]['at'], [(x0 + x1) / 2, (y0 + y1) / 2]),
                  f"{bid}: roof flag {f['text']!r} at {got[0]['at']}, expected the block centre")
    check(len(old['main-house']['roof']['flags']) == 5 and len(old['pool-house']['roof']['flags']) == 1,
          'fixture: 5 roof flags on the main house, 1 on the pool house')


def test_household_keeps_stairs_porches_and_extensions():
    old = _by_id(_household()['buildings'])
    new = _by_id(copy.deepcopy(_migrated()[0])['buildings'])
    for bid, ob in old.items():
        nb = new[bid]
        check(nb['stairs'] == ob['stairs'], f'{bid}: stairs must carry over unchanged')
        ext = _by_id(nb['extensions'])
        for e in ob['roof']['extensions']:
            got = ext.get(e['id'])
            check(got is not None, f"{bid}: roof extension {e['id']} was dropped")
            for key in ('kind', 'x0', 'x1', 'depth', 'pitch', 'eave', 'brackets', 'wall'):
                check(got.get(key) == e[key], f"{bid}: extension {e['id']} {key} {e[key]} -> {got.get(key)}")
        porch_rooms = [r for r in nb['rooms'] if r.get('kind') == 'porch']
        check(len(porch_rooms) == len(ob['porches']),
              f"{bid}: {len(porch_rooms)} porch rooms for {len(ob['porches'])} porches")
        for p in ob['porches']:
            mine = [r for r in porch_rooms if _share_inside(r['polygon'], p['polygon']) >= 0.8]
            check(len(mine) == 1, f"{bid}: porch {p['id']} has {len(mine)} porch rooms")
            ratio = _area(mine[0]['polygon']) / _area(p['polygon'])
            check(0.8 <= ratio <= 1.2, f"{bid}: porch {p['id']} room area ratio {ratio:.2f}")
            check(mine[0]['level'] == 'L1', f"{bid}: porch {p['id']} room on {mine[0]['level']}")
        detail = nb.get('porches_detail') or []
        cols = sorted((c['at'][0], c['at'][1], c['size']) for d in detail for c in d.get('columns', []))
        want = sorted((c['at'][0], c['at'][1], c['size']) for p in ob['porches'] for c in p['columns'])
        check(cols == want, f'{bid}: porch columns {cols} != {want}')
        got = sorted((bool(d.get('screened')), d.get('floor')) for d in detail)
        want = sorted((bool(p.get('screened')), p.get('floor')) for p in ob['porches'])
        check(got == want, f'{bid}: porch screened/floor {got} != {want}')


# ---------------------------------------------------------------- flatten

def test_flatten_normalizes_and_keeps_extras():
    b = _b()
    # A. The migrated household flattens to a plan normalize keeps whole.
    old = _by_id(_household()['buildings'])
    model = copy.deepcopy(_migrated()[0])
    flat = b.flatten(copy.deepcopy(model))
    check(flat['schema'] == 'chauffeur.twin.plan/2', f"flatten schema {flat.get('schema')}")
    check(flat['site'] == _expected_site(), 'flatten must give the site back unchanged')
    norm, notes = twin_plan.normalize(flat)
    _no_dropped(notes, 'household')
    fb, nbs, mb = _by_id(flat['buildings']), _by_id(norm['buildings']), _by_id(model['buildings'])
    for bid, ob in old.items():
        f, n, m = fb[bid], nbs[bid], mb[bid]
        check(len(f['openings']) == len(ob['openings']) == len(n['openings']),
              f"{bid}: openings {len(ob['openings'])} -> flat {len(f['openings'])} -> normalized {len(n['openings'])}")
        for key in ('walls', 'rooms'):
            check(len(n[key]) == len(f[key]), f'{bid}: normalize dropped {key}')
        check(len(n['roof']['sections']) == len(f['roof']['sections']), f'{bid}: normalize dropped roof sections')
        check(len(n['roof']['extensions']) == len(ob['roof']['extensions']),
              f"{bid}: roof extensions {len(ob['roof']['extensions'])} -> {len(n['roof']['extensions'])}")
        separators = [w for w in n['walls'] if w.get('kind') == 'separator']
        check(separators and len(separators) == len([w for w in _live(m['walls']) if w['kind'] == 'separator']),
              f'{bid}: separator walls must reach the flat walls with kind separator')
        for w in n['walls']:
            check(isinstance(w.get('joints'), list) and len(w['joints']) == 2,
                  f"{bid}: wall {w['id']} lost its joints")
            check(w.get('kind') in ('solid', 'separator'), f"{bid}: wall {w['id']} kind {w.get('kind')!r}")
            if w['kind'] == 'solid':
                check(isinstance(w.get('footprint'), list) and len(w['footprint']) == 4,
                      f"{bid}: solid wall {w['id']} lost its footprint")
        for r in n['rooms']:
            check(r.get('kind') in ('room', 'porch') and len(r.get('polygon') or []) >= 3,
                  f"{bid}: room {r['id']} lost its kind or polygon")
        check(n['proposals'] == m['proposals'] and n['flags'] == m['flags'],
              f'{bid}: proposals and flags must pass through flatten and normalize')
        porches = twin_plan.porches(n)
        cols = sorted((c['at'][0], c['at'][1], c['size']) for p in porches for c in p['columns'])
        want = sorted((c['at'][0], c['at'][1], c['size']) for p in ob['porches'] for c in p['columns'])
        check(len(porches) == len(ob['porches']) and cols == want,
              f'{bid}: the generator must still find the porches and their columns: {len(porches)} porches')

    # B. Lights, fixtures, faces and finishes on a small house.
    # A 20 x 10 box with one room, a light inside it, a light outside it and a counter.
    flat = _flat(_box_walls(20), [{'id': 'room-hall', 'level': 'L1', 'name': 'hall',
                                   'polygon': _rect_poly(0, 0, 20, 10)}],
                 lights=[{'id': 'light-1', 'level': 'L1', 'at': [5, 5]},
                         {'id': 'light-2', 'level': 'L1', 'at': [40, 5]}],
                 fixtures=[{'id': 'fixture-1', 'level': 'L1', 'kind': 'counter', 'asset': 'counter',
                            'rect': [1, 1, 3, 2], 'height': 3, 'rotation': 90}])
    model, _ = b.assemble(flat, None)
    mbd = model['buildings'][0]
    anchors = [a for a in mbd['anchors'] if a.get('kind') == 'light']
    check(len(anchors) == 2, f'two lights make two light anchors: {mbd["anchors"]}')
    inside = [a for a in anchors if isinstance(a.get('host'), dict) and a['host'].get('ceiling') == 'room-hall']
    check(len(inside) == 1, f'the light inside the hall sits on its ceiling: {anchors}')
    host = inside[0]['host']
    check(abs(host['u'] - 0.25) <= TOL and abs(host['v'] - 0.5) <= TOL,
          f'the light at (5, 5) in a 20 x 10 room is at u 0.25, v 0.5: {host}')
    outside = [a for a in anchors if a is not inside[0]]
    check(outside[0].get('state') == 'ghost'
          and not (isinstance(outside[0].get('host'), dict) and 'ceiling' in outside[0]['host']),
          f'a light outside every room is an unhosted ghost: {outside[0]}')
    items = mbd['items']
    check(len(items) == 1, f'the counter becomes one item: {items}')
    item = items[0]
    check(item.get('asset') == 'counter' and item.get('rotation') == 90,
          f'the item keeps its asset and rotation: {item}')
    check(isinstance(item.get('host'), dict) and item['host'].get('floor') == 'room-hall'
          and abs(item['host']['u'] - 0.1) <= TOL and abs(item['host']['v'] - 0.15) <= TOL,
          f'the counter sits on the hall floor at its centre (2, 1.5): {item.get("host")}')
    brick = {'id': 'brick', 'color': '#8a4b38'}
    oak, plaster = {'id': 'oak', 'color': '#a0522d'}, {'id': 'plaster', 'color': '#f2f2f2'}
    for w in mbd['walls']:
        if w['id'] == 's':
            w['faces'] = {'left': brick}
    for r in mbd['rooms']:
        if r['id'] == 'room-hall':
            r['floor_material'], r['ceiling_material'] = oak, plaster
    flat = b.flatten(copy.deepcopy(model))
    norm, notes = twin_plan.normalize(flat)
    _no_dropped(notes, 'small house')
    nb = norm['buildings'][0]
    south = [w for w in nb['walls'] if w['id'] == 's']
    check(len(south) == 1 and south[0].get('faces') == {'left': brick}
          and _same_segment(south[0]['from'], south[0]['to'], [0, 0], [20, 0]),
          f'the south wall keeps its place and its face: {south}')
    hall = [r for r in nb['rooms'] if r['id'] == 'room-hall']
    check(len(hall) == 1 and hall[0].get('floor_material') == oak and hall[0].get('ceiling_material') == plaster
          and hall[0].get('kind') == 'room' and abs(_area(hall[0]['polygon']) - 200) <= 1e-3,
          f'the hall keeps kind, polygon and finishes: {hall}')
    lights = [l for l in nb['lights'] if _near(l['at'], [5, 5])]
    check(len(lights) == 1 and lights[0]['level'] == 'L1',
          f'the hall light comes back from its anchor at (5, 5): {nb["lights"]}')
    check(nb.get('anchors') == mbd['anchors'], 'anchors pass through flatten as anchors')
    check(nb.get('items') == mbd['items'], 'items pass through flatten')


# ---------------------------------------------------------------- ownership (Review Focus 3)

def test_person_wall_survives_a_new_read_and_a_disagreement_is_a_proposal():
    b = _b()
    # A 30 x 10 box holding three free-standing walls: p (vertical at x 8),
    # q (horizontal at y 5 from x 15 to 25) and k (vertical at x 3).
    walls0 = _box_walls(30) + [_wall('p', (8, 2), (8, 8)), _wall('q', (15, 5), (25, 5)),
                               _wall('k', (3, 3), (3, 6))]
    hall0 = {'id': 'room-hall', 'level': 'L1', 'name': 'hall', 'polygon': _rect_poly(0, 0, 30, 10)}
    model0, _ = b.assemble(_flat(walls0, [hall0]), None)
    b0 = model0['buildings'][0]
    joints0 = _by_id(b0['joints'])
    walls = _by_id(b0['walls'])
    # The person drags p to x 9 and shortens q to end at x 22.
    for wid, moves in (('p', {(8, 2): [9, 2], (8, 8): [9, 8]}), ('q', {(25, 5): [22, 5]})):
        walls[wid]['src'] = {'person': True}
        for jid in walls[wid]['joints']:
            for was, now in moves.items():
                if _near(joints0[jid]['at'], was):
                    joints0[jid]['at'] = now
    p_joints = list(walls['p']['joints'])

    # The new read: the east wall moved to x 33, p read 0.4 ft off the person's
    # p, q read at its old length, k gone.
    walls1 = _box_walls(33) + [_wall('p', (8.6, 2), (8.6, 8)), _wall('q', (15, 5), (25, 5))]
    hall1 = {'id': 'room-hall', 'level': 'L1', 'name': 'hall', 'polygon': _rect_poly(0, 0, 33, 10)}
    model1, _ = b.assemble(_flat(walls1, [hall1]), copy.deepcopy(model0))
    b1 = model1['buildings'][0]
    live = _live(b1['walls'])
    check(sorted(w['id'] for w in live) == ['e', 'n', 'p', 'q', 's', 'w'],
          f"walls after the read: {sorted(w['id'] for w in live)} (k untouched and unread goes; no duplicate p or q)")
    by = _by_id(live)
    # The person's walls and joints keep their positions and ids.
    check(by['p']['joints'] == p_joints, f"p keeps its joints {p_joints}, got {by['p']['joints']}")
    check(_same_segment(*_ends(b1, by['p']), [9, 2], [9, 8]), f"p stays where the person put it: {_ends(b1, by['p'])}")
    check(_same_segment(*_ends(b1, by['q']), [15, 5], [22, 5]), f"q stays as the person left it: {_ends(b1, by['q'])}")
    for wid in ('p', 'q'):
        check((by[wid].get('src') or {}).get('person') is True, f'{wid} stays the person\'s')
    # Untouched walls take the new read.
    check(_same_segment(*_ends(b1, by['e']), [33, 0], [33, 10]), f"e takes the new read: {_ends(b1, by['e'])}")
    check(_same_segment(*_ends(b1, by['s']), [0, 0], [33, 0]), f"s takes the new read: {_ends(b1, by['s'])}")
    # The disagreeing q is a proposal against the person's q, never applied.
    props = b1['proposals']
    check(len(props) == 1, f'one proposal (the re-read p is within a foot and dropped): {props}')
    prop = props[0]
    check(prop.get('kind') == 'wall' and prop.get('against') == 'q', f'the proposal is a wall against q: {prop}')
    piece = prop['piece']
    check(piece.get('state') == 'proposal', f"the proposed wall is stored as state proposal: {piece}")
    if 'from' in piece and 'to' in piece:
        ends = piece['from'], piece['to']
    else:
        joints1 = _joints(b1)
        check(all(j in joints1 for j in piece.get('joints', [])),
              f'the proposal needs from/to or joints the model holds: {piece}')
        ends = joints1[piece['joints'][0]], joints1[piece['joints'][1]]
    check(_same_segment(ends[0], ends[1], [15, 5], [25, 5]), f'the proposal is the read q: {ends}')
    # R2: flatten keeps the proposal out of the drawn walls.
    flat = b.flatten(copy.deepcopy(model1))
    fb = flat['buildings'][0]
    check(sorted(w['id'] for w in fb['walls']) == ['e', 'n', 'p', 'q', 's', 'w']
          and all(w.get('state') != 'proposal' for w in fb['walls']),
          f"flatten draws only the live walls: {[(w['id'], w.get('state')) for w in fb['walls']]}")
    check(len(fb['proposals']) == 1 and fb['proposals'][0].get('kind') == 'wall',
          f"the proposal rides in proposals: {fb['proposals']}")
    _no_dropped(twin_plan.normalize(flat)[1], 'after the new read')


def test_person_opening_and_roof_survive_a_new_read():
    b = _b()
    # A 30 x 10 box with a window on the south wall and one gable roof over it.
    roof = {'id': 'roof-a', 'kind': 'gable', 'rect': [0, 0, 30, 10], 'ridge': 'x', 'pitch': 8,
            'plate': 9, 'overhang': 1}
    hall = {'id': 'room-hall', 'level': 'L1', 'name': 'hall', 'polygon': _rect_poly(0, 0, 30, 10)}
    window = {'id': 'win', 'wall': 's', 'at': 10, 'width': 3, 'sill': 3, 'head': 7, 'kind': 'window'}
    model0, _ = b.assemble(_flat(_box_walls(30), [hall], [window], [roof]), None)
    b0 = model0['buildings'][0]
    # The person slides the window to 12 and sets the roof's slopes to 6.
    win0 = _by_id(b0['openings'])['win']
    win0['at'], win0['src'] = 12, {'person': True}
    check(len(b0['roofs']) == 1, f'one section makes one roof: {b0["roofs"]}')
    roof0 = b0['roofs'][0]
    roof0['src'] = {'person': True}
    for edge in roof0['edges']:
        if edge['setting'] == 'sloped':
            edge['pitch'] = 6
    # The new read: the window 0.5 ft from the person's, the roof at pitch 10.
    window1 = dict(window, at=12.5)
    model1, _ = b.assemble(_flat(_box_walls(30), [hall], [window1], [dict(roof, pitch=10)]),
                           copy.deepcopy(model0))
    b1 = model1['buildings'][0]
    on_south = [o for o in _live(b1['openings']) if o.get('wall') == 's']
    check(len(on_south) == 1, f'one window on the south wall, not two: {on_south}')
    check(on_south[0]['id'] == 'win' and abs(on_south[0]['at'] - 12) <= TOL
          and (on_south[0].get('src') or {}).get('person') is True,
          f"the person's window stays at 12: {on_south[0]}")
    roofs = _live(b1['roofs'])
    check(len(roofs) == 1, f'one live roof, not the person\'s plus the read: {roofs}')
    kept = roofs[0]
    check(kept['id'] == roof0['id'] and (kept.get('src') or {}).get('person') is True,
          f"the person's roof stays: {kept}")
    sloped = [e for e in kept['edges'] if e['setting'] == 'sloped']
    check(len(sloped) == 2 and all(abs(e['pitch'] - 6) <= TOL for e in sloped),
          f"the person's slopes stay at 6: {kept['edges']}")


# ---------------------------------------------------------------- migration separators

def test_migration_separator_is_flagged_with_the_exact_copy():
    b = _b()
    # A 20 x 10 box with no interior wall and two stored rooms side by side.
    rooms = [{'id': 'room-k', 'level': 'L1', 'name': 'kitchen', 'polygon': _rect_poly(0, 0, 10, 10)},
             {'id': 'room-d', 'level': 'L1', 'name': 'dining room', 'polygon': _rect_poly(10, 0, 20, 10)}]
    model, _ = b.assemble(_flat(_box_walls(20), rooms), None)
    bd = model['buildings'][0]
    seps = [w for w in _live(bd['walls']) if w.get('kind') == 'separator']
    check(len(seps) == 1, f'one separator between the two rooms: {seps}')
    check(_same_segment(*_ends(bd, seps[0]), [10, 0], [10, 10]), f'the separator runs x 10: {_ends(bd, seps[0])}')
    flags = [f for f in bd['flags'] if f['text'].startswith('I added an invisible wall')]
    copies = {SEPARATOR_COPY.format(a='kitchen', b='dining room'),
              SEPARATOR_COPY.format(a='dining room', b='kitchen')}
    check(len(flags) == 1 and flags[0]['text'] in copies, f'one separator flag with the exact copy: {flags}')
    check(flags[0]['level'] == 'L1' and abs(flags[0]['at'][0] - 10) <= TOL and 0 <= flags[0]['at'][1] <= 10,
          f"the flag sits on the separator: {flags[0]}")
    by = _by_id(bd['rooms'])
    for rid, name in (('room-k', 'kitchen'), ('room-d', 'dining room')):
        check(rid in by and by[rid]['name'] == name and abs(_area(by[rid]['polygon']) - 100) <= 1e-3,
              f'{name} keeps its id, name and its 10 x 10 region: {by.get(rid)}')
    fw = [w for w in b.flatten(copy.deepcopy(model))['buildings'][0]['walls'] if w.get('kind') == 'separator']
    check(len(fw) == 1 and _same_segment(fw[0]['from'], fw[0]['to'], [10, 0], [10, 10]),
          f'flatten puts the separator in walls with kind separator: {fw}')

    # A generic room name gives the generic copy.
    rooms[1]['name'] = 'Room'
    model, _ = b.assemble(_flat(_box_walls(20), rooms), None)
    flags = [f['text'] for f in model['buildings'][0]['flags'] if f['text'].startswith('I added an invisible wall')]
    check(flags == [SEPARATOR_COPY_GENERIC], f'the generic copy when a room is named Room: {flags}')


def test_moved_person_wall_and_door_keep_identity():
    door = {'id': 'door', 'wall': 'p', 'at': 3, 'width': 2, 'sill': 0, 'head': 7, 'kind': 'door'}
    flat = _flat(_box_walls(30) + [_wall('p', (8, 2), (8, 8))], [], [door])
    previous, _ = _b().assemble(flat)
    house = previous['buildings'][0]
    wall = _by_id(house['walls'])['p']
    wall['src'] = {'person': True}
    for jid in wall['joints']:
        _by_id(house['joints'])[jid]['at'][0] = 12
    model, _ = _b().assemble(flat, previous)
    house = model['buildings'][0]
    check(sorted(w['id'] for w in house['walls']) == ['e', 'n', 'p', 's', 'w'], house['walls'])
    check(_same_segment(*_ends(house, _by_id(house['walls'])['p']), [12, 2], [12, 8]), house)
    check(house['openings'][0]['wall'] == 'p' and house['openings'][0].get('state') != 'ghost', house['openings'])
    check(len(house['proposals']) == 1 and house['proposals'][0]['piece']['id'] == 'p:proposal', house['proposals'])


def test_person_split_wall_and_opening_do_not_duplicate_on_household_read():
    previous = copy.deepcopy(_migrated()[0])
    house = _by_id(previous['buildings'])['main-house']
    # Simulate an explicit editor split, independent of whether migration splits.
    opening = next(o for o in house['openings'] if o['id'].endswith('c98aa3'))
    wall = _by_id(house['walls'])[opening['wall']]
    if '~' not in wall['id']:
        a, b = _ends(house, wall)
        cut = opening['at'] - 3
        point = [a[i] + (b[i] - a[i]) * cut / _dist(a, b) for i in (0, 1)]
        house['joints'].append({'id': 'explicit-split', 'level': wall['level'], 'at': point})
        part = copy.deepcopy(wall)
        part.update(id=wall['id'] + '~2', joints=['explicit-split', wall['joints'][1]])
        wall['joints'][1] = 'explicit-split'
        house['walls'].append(part)
        opening.update(wall=part['id'], at=3)
        wall = part
    wall['src'] = opening['src'] = {'person': True}
    model, _ = _b().assemble(_household(), previous)
    house = _by_id(model['buildings'])['main-house']
    check(len([o for o in house['openings'] if o['id'] == opening['id']]) == 1, house['openings'])
    check(len(house['openings']) == 27, house['openings'])
    check(not any(p['kind'] == 'opening' and p['against'] == opening['id'] for p in house['proposals']),
          'the same opening world position is dropped even when its host id changed')
    mine = _by_id(house['walls'])[wall['id']]
    check(mine['src']['person'], mine)
    check(not any(w is not mine and _same_segment(*_ends(house, w), *_ends(house, mine))
                  for w in house['walls']), house['walls'])


def test_flat_reads_keep_wall_identity_state_why_and_room_polygons():
    with open(os.path.join(os.path.dirname(HOUSEHOLD), '..', 'twin_reads', 'recorded',
                           'claude', 'draft-main-spike-answer.json'), encoding='utf-8') as fh:
        draft = json.load(fh)['building']
    for flat in (_household(), {'units': 'ft', 'buildings': [draft], 'site': {}}):
        original = copy.deepcopy(flat)
        wall = flat['buildings'][0]['walls'][0]
        wall.update(state='ghost', why='The read corner does not close.')
        got = _b().flatten(_b().assemble(flat)[0])
        for old, new in zip(flat['buildings'], got['buildings']):
            walls = [w for w in new['walls'] if w.get('kind') != 'separator']
            check({w['id'].split('~')[0] for w in walls} == {w['id'] for w in old['walls']}, walls)
            for original_wall in old['walls']:
                parts = [w for w in walls if w['id'].split('~')[0] == original_wall['id']]
                check(all((w.get('state'), w.get('why'), w.get('src')) ==
                          (original_wall.get('state'), original_wall.get('why'), original_wall.get('src'))
                          for w in parts), parts)
                check(abs(sum(_dist(w['from'], w['to']) for w in parts) -
                          _dist(original_wall['from'], original_wall['to'])) < 2, parts)
        # Closed household room records keep the read polygons exactly, except
        # a read polygon lying over a neighbour (final wave I1): that room shows
        # its derived region, so two floors never share a patch.
        got = _b().flatten(_b().assemble(original)[0])
        from services import twin_model
        over = []
        for old, new in zip(original['buildings'], got['buildings']):
            rooms = _by_id(new['rooms'])
            for room in old.get('rooms', []):
                lies_over = any(o['id'] != room['id'] and o['level'] == room['level']
                                and twin_model._overlap(room['polygon'], o['polygon']) > 0.5
                                for o in new['rooms'])
                if lies_over:
                    over.append(room['id'])
                    check(rooms[room['id']]['polygon'] != room['polygon'], (room, rooms.get(room['id'])))
                    continue
                check(rooms[room['id']]['polygon'] == room['polygon'], (room, rooms.get(room['id'])))
        if [b['id'] for b in original['buildings']] == ['main-house', 'pool-house']:
            # ef8bd0's read lies 22 sq ft over the closure Room (R36); once it
            # shows its region, its two L2 neighbours' reads lie over that region.
            check(sorted(over) == ['room:48bcc32861704cc6b6edc5291031c3f8',
                                   'room:70e732ca372344819e70454c92e85918',
                                   'room:ef8bd041182342b28871ad178de511a6'], over)


def test_household_window_across_an_inside_wall_stays_a_settled_window():
    """Final wave I2 / R55: the interior wall meeting d6209c inside window
    ...4198d's span stays a derived T for that wall, so migration keeps the
    window settled in its wall; no flag of any piece sits at the origin."""
    model, _ = _b().assemble(_household())
    main = next(b for b in model['buildings'] if b['id'] == 'main-house')
    window = next(o for o in main['openings'] if o['id'].endswith('4198d'))
    check(window.get('state') == 'settled' and not window.get('why'), window)
    host = next(w for w in main['walls'] if w['id'] == window['wall'])
    joints = {j['id']: j['at'] for j in main['joints']}
    length = _dist(*(joints[j] for j in host['joints']))
    check(window['at'] - window['width'] / 2 >= 0 and window['at'] + window['width'] / 2 <= length,
          ('the window fits its whole wall', window, length))
    # The meeting point is still a joint (the stem keeps it), just not one of the host's.
    a, b = (joints[j] for j in host['joints'])
    inside = [jid for jid, p in joints.items() if jid not in host['joints']
              and abs((p[0] - a[0]) * (b[1] - a[1]) - (p[1] - a[1]) * (b[0] - a[0])) / length < 0.05
              and 0 < ((p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1])) / length < length]
    check(inside, ('a T meets the window wall inside its span', host))
    for building in model['buildings']:
        for flag in building['flags']:
            check(flag.get('at') != [0, 0], flag)
            if 'place it again' in flag.get('text', ''):
                check(flag.get('level') is not None, flag)
        check(not any(o.get('state') == 'ghost' for o in building['openings']),
              [o for o in building['openings'] if o.get('state') == 'ghost'])
    # A later normalize keeps the rule: still one wall, still settled.
    from services import twin_model
    again, _ = twin_model.normalize(model)
    main2 = next(b for b in again['buildings'] if b['id'] == 'main-house')
    window2 = next(o for o in main2['openings'] if o['id'] == window['id'])
    check(window2['wall'] == window['wall'] and window2.get('state') == 'settled', window2)


def test_household_rereads_and_flat_rewrites_reuse_separators_and_flags():
    model = copy.deepcopy(_migrated()[0])
    for read in (_household(), _b().flatten(model), _household()):
        following, _ = _b().assemble(read, model)
        for old, new in zip(model['buildings'], following['buildings']):
            old_seps = {w['id'] for w in old['walls'] if w.get('kind') == 'separator'}
            check(old_seps == {w['id'] for w in new['walls'] if w.get('kind') == 'separator'}, new['walls'])
            check(old['flags'] == new['flags'], (old['flags'], new['flags']))
            rooms = _by_id(new['rooms'])
            for room in old['rooms']:
                check(rooms[room['id']]['name'] == room['name'], (room, rooms))
        model = following


def test_roof_flags_round_trip_with_block_rect_without_duplicates():
    model = copy.deepcopy(_migrated()[0])
    for _ in range(3):
        flat = _b().flatten(model)
        check(sum(len(b['roof'].get('flags', [])) for b in flat['buildings']) == 6, flat)
        for old, new in zip(_household()['buildings'], flat['buildings']):
            check(new['roof']['flags'] == old['roof']['flags'], new['roof'])
        model, _ = _b().assemble(flat, model)


def test_migration_separator_flags_group_by_level_and_exclude_porches():
    for house in _migrated()[0]['buildings']:
        separators = [w for w in house['walls'] if w.get('kind') == 'separator']
        check(all(w.get('src', {}).get('step') in ('migration', 'porch') for w in separators), separators)
        flags = [f for f in house['flags'] if f['text'].startswith('I added ')]
        for level in house['levels']:
            seps = [w for w in separators if w['level'] == level['id'] and w['src']['step'] == 'migration']
            mine = [f for f in flags if f['level'] == level['id']]
            check(len(mine) == bool(seps), (level, seps, mine))
            if len(seps) > 1:
                check(mine[0]['text'] == f"I added {len(seps)} invisible walls on the {level['name']} to keep rooms apart; check them.", mine)
            if seps:
                check(mine[0]['piece'] == seps[0]['id'], mine)
        check(not any(f.get('piece') == w['id'] for w in separators if w['src']['step'] == 'porch' for f in flags), flags)


def test_overlapping_read_roofs_and_explicit_person_window_carrier_round_trip():
    roof = {'id': 'old', 'kind': 'gable', 'rect': [0, 0, 30, 10], 'ridge': 'y',
            'pitch': 8, 'plate': 9, 'overhang': 1}
    window = {'id': 'win', 'section': 'old', 'gable': 'front', 'x': 10,
              'width': 3, 'sill': 3.1, 'head': 7, 'kind': 'window', 'src': {'person': True}}
    flat = _flat(_box_walls(30), [], [window], [roof])
    previous, _ = _b().assemble(flat)
    flat['buildings'][0]['roof']['sections'] = [dict(roof, id='new'), dict(roof, id='porch', rect=[0, 0, 10, 10])]
    flat['buildings'][0]['openings'][0]['section'] = 'new'
    model, _ = _b().assemble(flat, previous)
    got = _b().flatten(model)['buildings'][0]
    check({s['id'] for s in got['roof']['sections']} == {'new', 'porch'}, got['roof'])
    check(got['openings'][0]['section'] == 'new' and got['openings'][0].get('state') != 'ghost', got['openings'])
    check(got['openings'][0]['sill'] == 3.1 and got['openings'][0]['src']['person'], got['openings'])


def test_household_assembly_stays_under_300ms():
    import time
    flat = _household()
    times = []
    for _ in range(3):
        started = time.perf_counter()
        _b().assemble(flat)
        times.append(time.perf_counter() - started)
    elapsed = min(times)
    print(f'  household assemble: {elapsed * 1000:.1f} ms')
    check(elapsed < .3, f'household assemble took {elapsed:.3f}s')


def test_legacy_person_dormer_block_stays_one_dormer():
    model = copy.deepcopy(_migrated()[0])
    flat = _b().flatten(model)
    house = _by_id(flat['buildings'])['main-house']
    dormer = next(s for s in house['roof']['sections'] if s.get('dormer_of'))
    dormer.update(pitch=11, src={'person': True})
    model, _ = _b().assemble(flat, model)
    flat = _b().flatten(model)
    house = _by_id(flat['buildings'])['main-house']
    section = _by_id(house['roof']['sections'])[dormer['id']]
    section['block'] = section.pop('dormer_of')
    model, _ = _b().assemble(flat, model)
    house = _by_id(model['buildings'])['main-house']
    check(len(house['roofs']) == 13 and len(house['dormers']) == 1, (house['roofs'], house['dormers']))
    section = _by_id(_by_id(_b().flatten(model)['buildings'])['main-house']['roof']['sections'])[dormer['id']]
    check(section['pitch'] == 11 and section['src']['person'] and section.get('dormer_of') and 'block' not in section, section)


def test_derived_t_faces_and_stale_piece_flags():
    flat = _flat(_box_walls(20) + [_wall('p', (10, 0), (10, 10))], [])
    flat['buildings'][0]['flags'] = [{'piece': 'gone', 'at': [10, 5], 'text': 'Old wall flag.'}]
    model, _ = _b().assemble(flat)
    check(not model['buildings'][0]['flags'], model['buildings'][0]['flags'])
    house = _b().flatten(model)['buildings'][0]
    check({w['id'] for w in house['walls']} == {'s', 's~2', 'e', 'n', 'n~2', 'w', 'p'}, house['walls'])
    points = _by_id(house['walls'])['p']['footprint']
    check(abs(min(p[1] for p in points) - .25) < TOL and abs(max(p[1] for p in points) - 9.75) < TOL,
          ('the T stem butts into the through walls while their ids remain whole', points))


def test_t_splits_persist_on_migration_and_reread():
    flat = _flat(_box_walls(20) + [_wall('p', (10, 0), (10, 10))], [])
    model, _ = _b().assemble(flat)
    house = model['buildings'][0]
    expected = {w['id']: _ends(house, w) for w in house['walls']}
    check({'s~2', 'n~2'} <= expected.keys(), expected)
    for read in (flat, _b().flatten(model)):
        following, _ = _b().assemble(read, model)
        house = following['buildings'][0]
        check({w['id']: _ends(house, w) for w in house['walls']} == expected, house['walls'])
    check(all(any('~' in w['id'] for w in b['walls']) for b in _migrated()[0]['buildings']),
          'household migration must persist its T joints')


def test_proposals_have_top_level_ids():
    flat = _flat(_box_walls(30) + [_wall('p', (8, 2), (8, 8))], [])
    previous, _ = _b().assemble(flat)
    house = previous['buildings'][0]
    p = _by_id(house['walls'])['p']
    p['src'] = {'person': True}
    for jid in p['joints']:
        _by_id(house['joints'])[jid]['at'][0] = 12
    model, _ = _b().assemble(flat, previous)
    proposal = model['buildings'][0]['proposals'][0]
    check(proposal['id'] == proposal['piece']['id'] == 'p:proposal', proposal)
    del proposal['id']
    model, _ = _b().assemble(flat, model)
    check(all(p['id'] == p['piece']['id'] for p in model['buildings'][0]['proposals']), model)


def test_person_split_keeps_siblings_on_flat_and_whole_reads():
    flat = _flat([_wall('x', (0, 0), (20, 0), True)] + _box_walls(20)[1:] +
                 [_wall('p', (10, 0), (10, 10))], [])
    previous, _ = _b().assemble(flat)
    house = previous['buildings'][0]
    _by_id(house['walls'])['x~2']['src'] = {'person': True}
    for read in (_b().flatten(previous), flat):
        model, _ = _b().assemble(read, previous)
        house = model['buildings'][0]
        walls = _by_id(house['walls'])
        check(_same_segment(*_ends(house, walls['x']), [0, 0], [10, 0]), walls)
        check(_same_segment(*_ends(house, walls['x~2']), [10, 0], [20, 0]), walls)
        check(walls['x']['exterior'] and walls['x~2']['src']['person'], walls)
        check(not house['proposals'] and not any(w['kind'] == 'separator' for w in walls.values()), house)
    # A disagreeing half is proposed without swallowing the untouched sibling.
    house = previous['buildings'][0]
    for jid in _by_id(house['walls'])['x~2']['joints']:
        _by_id(house['joints'])[jid]['at'][1] = -1
    within, _ = _b().assemble(flat, previous)
    check(not within['buildings'][0]['proposals'], 'a one-foot disagreement does not propose a wall')
    for jid in _by_id(house['walls'])['x~2']['joints']:
        _by_id(house['joints'])[jid]['at'][1] = -3
    model, _ = _b().assemble(flat, previous)
    house = model['buildings'][0]
    check({'x', 'x~2'} <= _by_id(house['walls']).keys(), house['walls'])
    check(len(house['proposals']) == 1 and house['proposals'][0]['against'] == 'x~2', house['proposals'])
    check(_same_segment(house['proposals'][0]['piece']['from'], house['proposals'][0]['piece']['to'],
                        [10, 0], [20, 0]), house['proposals'])


def test_reread_rooms_follow_person_partition():
    flat = _flat(_box_walls(20) + [_wall('p', (8, 0), (8, 10))], [
        {'id': 'a', 'name': 'A', 'level': 'L1', 'polygon': _rect_poly(0, 0, 8, 10)},
        {'id': 'b', 'name': 'B', 'level': 'L1', 'polygon': _rect_poly(8, 0, 20, 10)}])
    previous, _ = _b().assemble(flat)
    house = previous['buildings'][0]
    p = _by_id(house['walls'])['p']
    p['src'] = {'person': True}
    for jid in p['joints']:
        _by_id(house['joints'])[jid]['at'][0] = 12
    model, _ = _b().assemble(flat, previous)
    house = model['buildings'][0]
    rooms = _by_id(house['rooms'])
    check(set(rooms) == {'a', 'b'}, rooms)
    check(_bbox(rooms['a']['polygon']) == [0, 0, 12, 10] and
          _bbox(rooms['b']['polygon']) == [12, 0, 20, 10], rooms)
    check(not any(w['kind'] == 'separator' for w in house['walls']), house['walls'])


def test_missing_room_polygon_is_diagnosed():
    model, notes = _b().assemble(_flat(_box_walls(20), [{'id': 'bad', 'name': 'Bad', 'level': 'L1'}]))
    check(any('bad' in n and 'polygon' in n for n in notes), notes)
    check(any(f.get('piece', {}).get('room', {}).get('id') == 'bad'
              for f in model['buildings'][0]['flags'] if isinstance(f.get('piece'), dict)), model)


def test_grouped_separator_flag_tracks_remaining_members():
    rooms = [{'id': f'r{i}', 'name': 'Room', 'level': 'L1', 'polygon': _rect_poly(i * 10, 0, (i + 1) * 10, 10)}
             for i in range(3)]
    flat = _flat(_box_walls(30), rooms)
    previous, _ = _b().assemble(flat)
    house = previous['buildings'][0]
    flag = next(f for f in house['flags'] if f['text'].startswith('I added '))
    first = flag['piece']
    first_wall = _by_id(house['walls'])[first]
    x = _ends(house, first_wall)[0][0]
    flat['buildings'][0]['walls'].append(_wall('real', (x, 0), (x, 10)))
    model, _ = _b().assemble(flat, previous)
    house = model['buildings'][0]
    seps = [w for w in house['walls'] if w['kind'] == 'separator']
    flags = [f for f in house['flags'] if f['text'].startswith('I added ')]
    check(len(seps) == len(flags) == 1 and flags[0]['piece'] == seps[0]['id'] != first, (seps, flags))
    check(flags[0]['text'] == 'I added an invisible wall here to keep two rooms apart; check it.', flags)


def test_extra_closure_room_and_detail_hosts_survive_every_path():
    from services import twin_model, twin_model_hosts
    flat = _flat(_box_walls(20) + [_wall('p', (10, 0), (10, 5))], [
        {'id': 'a', 'name': 'A', 'level': 'L1', 'polygon': _rect_poly(0, 0, 10, 10)}],
        lights=[{'id': 'lamp', 'level': 'L1', 'at': [15, 5]}],
        fixtures=[{'id': 'table', 'level': 'L1', 'kind': 'table', 'rect': [14, 2, 16, 4]}])
    model, _ = _b().assemble(flat)
    for path in ('assemble', 'normalize', 'derive', 'raw', 'flat', 'raw'):
        if path == 'normalize':
            model, _ = twin_model.normalize(model)
        elif path == 'derive':
            twin_model.derive(model['buildings'][0])
        elif path in ('raw', 'flat'):
            model, _ = _b().assemble(flat if path == 'raw' else _b().flatten(model), model)
        house = model['buildings'][0]
        rooms = _by_id(house['rooms'])
        check(set(rooms) == {'a', 'room-1'} and rooms['room-1']['name'] == 'Room', (path, rooms))
        for name, kind, point in (('anchors', 'ceiling', [15, 5]), ('items', 'floor', [15, 3])):
            piece = house[name][0]
            check(piece['host'][kind] == 'room-1' and piece.get('state') != 'ghost', (path, piece))
            check(_near(twin_model_hosts.world_point(house, piece['host'])[:2], point), (path, piece))
            check(all(p['host'][kind] in rooms for p in house[name]), (path, house[name]))


def test_cleared_separator_flags_stay_cleared_and_new_separators_get_flags():
    from services import twin_model
    flat = _flat(_box_walls(30), [
        {'id': 'k', 'name': 'Kitchen', 'level': 'L1', 'polygon': _rect_poly(0, 0, 10, 10)},
        {'id': 'd', 'name': 'Dining', 'level': 'L1', 'polygon': _rect_poly(10, 0, 30, 10)}])
    model, _ = _b().assemble(flat)
    house = model['buildings'][0]
    old_ids = {w['id'] for w in house['walls'] if w['kind'] == 'separator'}
    check(len(old_ids) == 1 and all(w.get('flagged') is True for w in house['walls']
                                  if w['id'] in old_ids), house['walls'])
    house['flags'] = [f for f in house['flags'] if not f.get('text', '').startswith('I added ')]
    model, _ = twin_model.normalize(model)
    legacy = copy.deepcopy(model)
    for wall in legacy['buildings'][0]['walls']:
        wall.pop('flagged', None)
    for read in (_b().flatten(legacy), flat):
        restored, _ = _b().assemble(read, legacy)
        check(not any(f.get('text', '').startswith('I added ') for f in restored['buildings'][0]['flags']), restored)
    for read in (_b().flatten(model), flat):
        model, _ = _b().assemble(read, model)
        house = model['buildings'][0]
        check(not any(f.get('text', '').startswith('I added ') for f in house['flags']), house['flags'])
        check({w['id'] for w in house['walls'] if w['kind'] == 'separator'} == old_ids, house['walls'])
    flat['buildings'][0]['rooms'][1]['polygon'] = _rect_poly(10, 0, 20, 10)
    flat['buildings'][0]['rooms'].append(
        {'id': 's', 'name': 'Study', 'level': 'L1', 'polygon': _rect_poly(20, 0, 30, 10)})
    model, _ = _b().assemble(flat, model)
    for read in (None, _b().flatten(model), flat):
        if read is not None:
            model, _ = _b().assemble(read, model)
        house = model['buildings'][0]
        separators = [w for w in house['walls'] if w['kind'] == 'separator']
        flags = [f for f in house['flags'] if f.get('text', '').startswith('I added ')]
        check(len(separators) == 2 and all(w.get('flagged') is True for w in separators), separators)
        check(len(flags) == 1 and flags[0]['piece'] not in old_ids, flags)
        check('invisible wall here' in flags[0]['text'] and flags[0]['at'] == [20, 5], flags)


def test_separator_flag_groups_do_not_absorb_new_members():
    flat = _flat(_box_walls(40), [
        {'id': f'r{i}', 'name': 'Room', 'level': 'L1', 'polygon': _rect_poly(i * 10, 0, (i + 1) * 10, 10)}
        for i in range(3)])
    flat['buildings'][0]['rooms'][2]['polygon'] = _rect_poly(20, 0, 40, 10)
    model, _ = _b().assemble(flat)
    original = next(f for f in model['buildings'][0]['flags'] if f.get('text', '').startswith('I added '))
    flat['buildings'][0]['rooms'].append(
        {'id': 'r3', 'name': 'Room', 'level': 'L1', 'polygon': _rect_poly(25, 0, 40, 10)})
    # Shorten the last original room so the later read needs a genuinely new boundary.
    flat['buildings'][0]['rooms'][2]['polygon'] = _rect_poly(20, 0, 25, 10)
    model, _ = _b().assemble(flat, model)
    flags = [f for f in model['buildings'][0]['flags'] if f.get('text', '').startswith('I added ')]
    check(len(flags) == 2, flags)
    check(next(f for f in flags if f['piece'] == original['piece'])['text'] ==
          'I added 2 invisible walls on the main floor to keep rooms apart; check them.', flags)
    model['buildings'][0]['flags'].remove(next(f for f in flags if f['piece'] == original['piece']))
    model, _ = _b().assemble(flat, model)
    flags = [f for f in model['buildings'][0]['flags'] if f.get('text', '').startswith('I added ')]
    check(len(flags) == 1 and flags[0]['at'] == [25, 5], flags)


def test_separator_flags_accept_a_flag_without_text():
    model, _ = _b().assemble(_flat(_box_walls(20), []))
    house = model['buildings'][0]
    house['flags'].append({'at': [5, 5], 'level': 'L1'})
    _b()._separator_flags(house)
    check(house['flags'] == [{'at': [5, 5], 'level': 'L1'}], house['flags'])
    _b().assemble(_b().flatten(model), model)
    flat = _household()
    flat['buildings'][0]['flags'] = [{'at': [5, 5], 'level': 'L1'}]
    _b().assemble(flat)


def test_ghost_rooms_never_add_or_reuse_separators():
    outline = [[0, 0], [30, 0], [30, 30], [20, 30], [20, 10], [10, 10], [10, 30], [0, 30]]
    walls = [_wall(f'edge{i}', a, b, True) for i, (a, b) in enumerate(_segments_for_test(outline))]
    rooms = [{'id': 'inside', 'name': 'Inside', 'level': 'L1', 'state': 'settled', 'polygon': _rect_poly(0, 0, 30, 10)},
             {'id': 'across', 'name': 'Across recess', 'level': 'L1', 'state': 'ghost',
              'polygon': [[5, 20], [25, 20], [15, 5]]}]
    walls += [dict(_wall('interior', (5, 10), (25, 10)), state='settled'),
              dict(_wall('outside', (5, 20), (25, 20)), state='ghost')]
    flat = _flat(walls, rooms)
    previous, _ = _b().assemble(flat)
    house = previous['buildings'][0]

    def check_rooms(house, has_ghost):
        by_id = _by_id(house['rooms'])
        check(by_id['inside']['name'] == 'Inside', by_id)
        if has_ghost:
            check(by_id['across']['name'] == 'Across recess' and by_id['across']['state'] == 'ghost', by_id)
        else:
            check('across' not in by_id, by_id)
        extras = [r for r in house['rooms'] if r['id'] not in ('inside', 'across')]
        check(len(extras) == 2 and all(r['name'] == 'Room' for r in extras), extras)
        check(all(twin_model._overlap(r['polygon'], by_id['inside']['polygon']) <= TOL
                  and _area(r['polygon']) < _area(outline) for r in extras), extras)

    from services import twin_model
    check_rooms(house, True)
    normalized = copy.deepcopy(previous)
    for path in ('normalize', 'derive', 'flat', 'raw'):
        if path == 'normalize':
            normalized, _ = twin_model.normalize(normalized)
        elif path == 'derive':
            twin_model.derive(normalized['buildings'][0])
        else:
            normalized, _ = _b().assemble(flat if path == 'raw' else _b().flatten(normalized), normalized)
        check_rooms(normalized['buildings'][0], True)
        check({r['id'] for r in normalized['buildings'][0]['rooms']} ==
              {r['id'] for r in house['rooms']}, (path, normalized))
        check(not any(isinstance(f.get('piece'), dict) and f['piece'].get('room', {}).get('id') == 'across'
                      for f in normalized['buildings'][0]['flags']), (path, normalized))
    separators = {w['id']: _ends(house, w) for w in house['walls'] if w['kind'] == 'separator'}
    check(all(a[1] == b[1] == 10 for a, b in separators.values()), separators)
    # Simulate a legacy closure around the ghost, then drop that read room.
    house['joints'] += [{'id': 'stale-a', 'level': 'L1', 'at': [5, 20]},
                        {'id': 'stale-b', 'level': 'L1', 'at': [15, 5]}]
    house['walls'].append({'id': 'stale', 'level': 'L1', 'joints': ['stale-a', 'stale-b'],
                           'kind': 'separator', 'thickness': 0, 'src': {'step': 'rooms'}})
    flat['buildings'][0]['rooms'] = rooms[:1]
    model, _ = _b().assemble(flat, previous)
    check_rooms(model['buildings'][0], False)
    house = model['buildings'][0]
    check({w['id']: _ends(house, w) for w in house['walls'] if w['kind'] == 'separator'} == separators, house)


def _segments_for_test(poly):
    return zip(poly, poly[1:] + poly[:1])


TESTS = (
    test_household_window_across_an_inside_wall_stays_a_settled_window,
    test_extra_closure_room_and_detail_hosts_survive_every_path,
    test_cleared_separator_flags_stay_cleared_and_new_separators_get_flags,
    test_separator_flag_groups_do_not_absorb_new_members,
    test_separator_flags_accept_a_flag_without_text,
    test_t_splits_persist_on_migration_and_reread,
    test_proposals_have_top_level_ids,
    test_person_split_keeps_siblings_on_flat_and_whole_reads,
    test_reread_rooms_follow_person_partition,
    test_missing_room_polygon_is_diagnosed,
    test_grouped_separator_flag_tracks_remaining_members,
    test_ghost_rooms_never_add_or_reuse_separators,
    test_household_migrates_and_keeps_every_room_name_and_opening,
    test_household_walls_stay_within_a_foot,
    test_household_roofs_round_trip,
    test_household_choice_roofs_become_person_owned,
    test_household_roof_flags_become_model_flags,
    test_household_keeps_stairs_porches_and_extensions,
    test_flatten_normalizes_and_keeps_extras,
    test_person_wall_survives_a_new_read_and_a_disagreement_is_a_proposal,
    test_person_opening_and_roof_survive_a_new_read,
    test_migration_separator_is_flagged_with_the_exact_copy,
    test_moved_person_wall_and_door_keep_identity,
    test_person_split_wall_and_opening_do_not_duplicate_on_household_read,
    test_flat_reads_keep_wall_identity_state_why_and_room_polygons,
    test_household_rereads_and_flat_rewrites_reuse_separators_and_flags,
    test_roof_flags_round_trip_with_block_rect_without_duplicates,
    test_migration_separator_flags_group_by_level_and_exclude_porches,
    test_overlapping_read_roofs_and_explicit_person_window_carrier_round_trip,
    test_household_assembly_stays_under_300ms,
    test_derived_t_faces_and_stale_piece_flags,
    test_legacy_person_dormer_block_stays_one_dormer,
)


if __name__ == '__main__':
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, type(exc).__name__, ' '.join(str(exc).split())[:500])
            if not isinstance(exc, (AssertionError, ImportError)):
                traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} passed')
    sys.exit(1 if failed else 0)

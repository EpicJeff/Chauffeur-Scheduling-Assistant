"""Rebuilds keep a person's edits; buildings read the old way migrate (plan
docs/superpowers/plans/2026-11-08-house-editor-whole-building-draft.md, Task 10;
brief .superpowers/sdd/2026-11-08-house-editor-whole-building-draft/task-10-brief.md).

- A wall the person moved comes back once on the next draft read: the read
  piece is matched by the read_geometry the wall was read with.
- A wall the person deleted stays deleted (its tombstone).
- The fit never moves a building whose position the person set
  (position_from == 'person'); that is the only fit gate.
- A rename never sets position_from, and a renamed building is still refit.
- An old-pipeline building (walls with src.step 'walls:...' or 'outline:...'
  and none from 'draft'): on its first draft settle the old first-floor
  outline is fitted onto the draft's (twin_register.fit_outline). With an RMS
  of at most 2 ft every person-added, person-moved and tombstoned piece is
  mapped through that fit before the merge; otherwise they are kept as they
  are and one log line says "Some of your changes may need moving: the new
  reading of the drawings sits differently."
- The old crop walls are replaced by the draft's, never left beside them.

The reader is a stub keyed by kind (its first argument), copied from
test_twin_build_draft.py. Old-pipeline buildings are SEEDED as a plan round
(walls carrying crop src steps and read_geometry, as the crop pipeline saved
them) rather than built through the legacy body, so their feet are exact.
Person edits go through twin_edit.save; renames through twin_edit.save and
twin_store.update_building, the two routes the editor uses.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_build_draft_rebuild.py
"""
import copy
import io
import json
import math
import os
import sys
import tempfile
import traceback

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_build_draft_rebuild_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import twin_build as tb  # noqa: E402
from services import twin_edit  # noqa: E402
from services import twin_plan  # noqa: E402
from services import twin_register as tr  # noqa: E402
from services import twin_store as ts  # noqa: E402
import test_twin_build as engine_tests  # noqa: E402
from test_twin_build import Reader, _accept_all, _pdf, check, fixture  # noqa: E402

RECORDED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_reads', 'recorded', 'claude')
SPIKE_PATH = os.path.join(RECORDED, 'draft-main-spike-answer.json')
MAY_NEED_MOVING = 'Some of your changes may need moving: the new reading of the drawings sits differently.'
W, H = 5100, 3300
FULL_CROP = {'box': [0, 0, 1, 1], 'master': [W, H]}

# A one-floor L-shaped building in feet, as the draft reads it.
L_DRAFT = [[0, 0], [40, 0], [40, 20], [20, 20], [20, 36], [0, 36]]
INTERIOR = {'i1': ([0, 12], [20, 12]), 'i2': ([28, 0], [28, 20]), 'i3': ([20, 28], [0, 28])}
# Old crop steps, as the retired pipeline wrote them.
OLD_STEPS = {'exterior': 'walls:L1:main', 'i1': 'walls:L1', 'i2': 'outline:L1', 'i3': 'walls:L1:main'}


# --- fakes and helpers (copied from test_twin_build_draft.py) -------------------

def spike():
    with open(SPIKE_PATH, encoding='utf-8') as f:
        return json.load(f)


class DraftReader(Reader):
    """test_twin_build's fake, plus the draft kinds: 'draft' answers the spike
    (or a given answer), 'draft_level' answers the same building, 'draft_rooms'
    answers nothing."""

    def __init__(self, answer=None, rooms=None, **kw):
        super().__init__(**kw)
        self.answer = spike() if answer is None else answer
        self.rooms = {'rooms': [], 'walls': []} if rooms is None else rooms
        self.seen = []

    def __call__(self, kind, images, context, *, run, step):
        self.seen.append({'kind': kind, 'step': step, 'images': len(images), 'context': copy.deepcopy(context)})
        if kind in ('draft', 'draft_level'):
            self.calls.append({'kind': kind, 'step': step, 'context': copy.deepcopy(context), 'images': len(images)})
            return copy.deepcopy(self.answer)
        if kind == 'draft_rooms':
            self.calls.append({'kind': kind, 'step': step, 'context': copy.deepcopy(context), 'images': len(images)})
            return copy.deepcopy(self.rooms)
        return super().__call__(kind, images, context, run=run, step=step)


def _house(plan, bid='house'):
    return next(b for b in plan['buildings'] if b['id'] == bid)


def _trouble(st):
    return [e for e in st['events'] if e['type'] in ('error', 'question')][-3:]


def _jpeg(colour):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (64, 48), colour).save(buf, format='JPEG')
    return buf.getvalue()


def _turn_gap(a, b):
    return abs((a - b + 180) % 360 - 180)


def _near(a, b, tol):
    return math.dist(a, b) <= tol


def _same_wall(wall, a, b, tol=0.25):
    """A wall runs a-b (either direction) within tol at both ends."""
    return ((_near(wall['from'], a, tol) and _near(wall['to'], b, tol))
            or (_near(wall['from'], b, tol) and _near(wall['to'], a, tol)))


def _walls_at(house, level, a, b, tol=1.0):
    return [w for w in house['walls'] if w['level'] == level and _same_wall(w, a, b, tol)]


def _shift(p, d):
    return [p[0] + d[0], p[1] + d[1]]


def _build(reader, limit=20):
    b = tb.start({'part': 'house'}, reader=reader, inline=True)
    st = _accept_all(b, limit)
    check(st['state'] == 'done', (st['state'], st.get('pause'), _trouble(st)))
    return b, st


# --- places --------------------------------------------------------------------

def _plot_lot():
    reg = tb._plot_registration(FULL_CROP, fixture('plot'))
    return reg, [tr.apply(reg, [u * W, v * H]) for u, v in fixture('plot')['lot']]


def _drawn_house(*, lot=False):
    """Main house drawings (Main floor, Upper floor, roof) and, on request, a
    plot page on the lot with a confirmed placement, as Task 3 confirms it."""
    engine_tests._fresh()
    sheets = ts.save_source('drawing', 'house.pdf', _pdf(3))   # legacy upload: Main house, id house
    rows = [{'source': sheets, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None, 'building': 'house'},
            {'source': sheets, 'page': 2, 'role': 'floor', 'level': 'Upper floor', 'box': None, 'building': 'house'},
            {'source': sheets, 'page': 3, 'role': 'roof', 'level': None, 'box': None, 'building': 'house'}]
    plot = None
    if lot:
        plot = ts.save_source('drawing', 'plot.pdf', _pdf(1), part='lot')
        rows.append({'source': plot, 'page': 1, 'role': 'plot', 'level': None, 'box': None, 'building': 'lot'})
    ts.set_page_roles(rows)
    if lot:
        reg, outline = _plot_lot()
        ts.set_lot({'placement': {'source': plot, 'page': 1, 'box': None, 'outline': outline,
                                  'street_edge': [1, 2], 'registration': reg, 'confirmed': True},
                    'read': None})
        ts.set_registration(plot, 1, None, reg)
    return sheets


def _footprint(target):
    """The spike's first floor, placed at target on the lot."""
    outline = next(l for l in spike()['building']['levels'] if l['id'] == 'L1')['outline']
    return [tr.to_world(target, p) for p in outline]


def _l_answer():
    """The L building as the draft reads it, in feet."""
    edges = list(zip(L_DRAFT, L_DRAFT[1:] + L_DRAFT[:1]))
    walls = [{'id': f'e{i}', 'level': 'L1', 'from': list(a), 'to': list(b),
              'height': 9, 'thickness': .5, 'exterior': True} for i, (a, b) in enumerate(edges)]
    walls += [{'id': name, 'level': 'L1', 'from': list(a), 'to': list(b),
               'height': 9, 'thickness': .33, 'exterior': False} for name, (a, b) in INTERIOR.items()]
    return {'building': {'levels': [{'id': 'L1', 'name': 'Main floor', 'elevation': 0,
                                     'ceiling': 9, 'outline': copy.deepcopy(L_DRAFT)}],
                         'walls': walls, 'openings': [], 'rooms': [],
                         'roof': {'sections': [], 'extensions': []}, 'stairs': [], 'porch': None}}


def _old_point(p, offset, scale):
    return [round(p[0] * scale + offset[0], 6), round(p[1] * scale + offset[1], 6)]


def _seed_old_pipeline(*, offset=(-3, 2), scale=1.0, without=()):
    """A Main house saved by the retired crop pipeline: its first floor is the
    L building scaled and offset from where the draft will read it, its walls
    carry crop src steps (and the read_geometry they were read with), and
    none comes from 'draft'. One floor page for the house; no lot."""
    engine_tests._fresh()
    sheets = ts.save_source('drawing', 'house.pdf', _pdf(1))   # legacy upload: Main house, id house
    ts.set_page_roles([{'source': sheets, 'page': 1, 'role': 'floor', 'level': 'Main floor',
                        'box': None, 'building': 'house'}])

    def old(p):
        return _old_point(p, offset, scale)

    def src(step):
        return {'sheet': sheets, 'page': 1, 'step': step}

    edges = list(zip(L_DRAFT, L_DRAFT[1:] + L_DRAFT[:1]))
    walls = [{'id': f'wall:old-e{i}', 'level': 'L1', 'from': old(a), 'to': old(b), 'height': 9,
              'thickness': .5, 'exterior': True, 'state': 'settled', 'src': src(OLD_STEPS['exterior']),
              'read_geometry': {'from': old(a), 'to': old(b)}} for i, (a, b) in enumerate(edges)]
    walls += [{'id': f'wall:old-{name}', 'level': 'L1', 'from': old(a), 'to': old(b), 'height': 9,
               'thickness': .33, 'exterior': False, 'state': 'settled', 'src': src(OLD_STEPS[name]),
               'read_geometry': {'from': old(a), 'to': old(b)}}
              for name, (a, b) in INTERIOR.items() if name not in without]
    level = {'id': 'L1', 'name': 'Main floor', 'elevation': 0, 'ceiling': 9,
             'outline': [old(p) for p in L_DRAFT], 'state': 'settled', 'src': src('outline:L1')}
    building = {'id': 'house', 'name': 'Main house', 'kind': 'main_house', 'position': [0, 0], 'rotation': 0,
                'levels': [level], 'walls': walls, 'openings': [], 'rooms': [], 'roof': {'sections': []}}
    plan, _ = twin_plan.normalize({'units': 'ft', 'buildings': [building], 'site': {}, 'materials': {}})
    ts.push_round(plan, 'build')
    house = _house(ts.current())
    check(all((w.get('src') or {}).get('step', '').startswith(('walls:', 'outline:')) for w in house['walls']),
          ('test setup: every seeded wall carries a crop step', [w.get('src') for w in house['walls']]))
    return sheets


def _crop_step(piece):
    return str((piece.get('src') or {}).get('step') or '').startswith(('walls:', 'outline:'))


# --- tests ---------------------------------------------------------------------

def test_person_moved_wall_not_duplicated():
    """Review Focus 5: a moved wall that the next draft read sees again at its
    old place is matched by its read_geometry and comes back once."""
    _drawn_house()
    _build(DraftReader())
    house = _house(ts.current())
    before = len(house['walls'])
    # k1, an upper-floor knee wall in the spike: moving it opens no floor.
    k1 = next(w for w in house['walls'] if w['level'] == 'L2' and not w.get('exterior')
              and _same_wall(w, [0, 25.33], [14.33, 25.33], 0.5))
    origin = (copy.deepcopy(k1['from']), copy.deepcopy(k1['to']))
    check(k1.get('read_geometry'), ('test setup: the draft saved the read geometry', k1))
    twin_edit.save({'op': 'move', 'building': 'house', 'piece': k1['id'], 'by': [0, 3]}, 'p1')
    moved = next(w for w in _house(ts.current())['walls'] if w['id'] == k1['id'])
    target = (copy.deepcopy(moved['from']), copy.deepcopy(moved['to']))
    check(_near(target[0], _shift(origin[0], [0, 3]), 0.1), ('test setup: the wall moved 3 ft', origin, target))

    for how in ('build again', 'read the drawings again'):
        if how == 'build again':
            b, _ = _build(DraftReader())
        else:
            tb.reread(b, 'draft', reader=DraftReader(), inline=True)
            st = _accept_all(b)
            check(st['state'] == 'done', (how, st['state'], st.get('pause'), _trouble(st)))
        house = _house(ts.current())
        mine = [w for w in house['walls'] if w['id'] == k1['id']]
        check(len(mine) == 1 and (mine[0].get('src') or {}).get('person'),
              (how, 'the moved wall is still the person\'s', mine))
        check(_same_wall(mine[0], *target, 0.1), (how, 'the moved wall stays where the person put it', mine[0]))
        back = _walls_at(house, 'L2', *origin)
        check(not back, (how, 'the read wall is matched to the moved one, never added back at its old place',
                         [(w['id'], w['from'], w['to'], w.get('src')) for w in back]))
        check(len(_walls_at(house, 'L2', *target)) == 1, (how, 'the moved wall comes back once'))
        check(len(house['walls']) == before, (how, 'no wall more, none fewer', before, len(house['walls'])))


def test_person_deleted_wall_stays_deleted():
    _drawn_house()
    _build(DraftReader())
    house = _house(ts.current())
    before = len(house['walls'])
    k3 = next(w for w in house['walls'] if w['level'] == 'L2' and not w.get('exterior')
              and _same_wall(w, [41, 0], [41, 19.33], 0.5))
    gone = (copy.deepcopy(k3['from']), copy.deepcopy(k3['to']))
    twin_edit.save({'op': 'delete', 'building': 'house', 'piece': k3['id']}, 'p1')
    check(len(_house(ts.current())['walls']) == before - 1, 'test setup: the wall is deleted')
    b, _ = _build(DraftReader())
    house = _house(ts.current())
    check(not _walls_at(house, 'L2', *gone), ('the deleted wall stays deleted on the next build',
                                              _walls_at(house, 'L2', *gone)))
    tb.reread(b, 'draft', reader=DraftReader(), inline=True)
    st = _accept_all(b)
    check(st['state'] == 'done', (st['state'], st.get('pause'), _trouble(st)))
    house = _house(ts.current())
    check(not _walls_at(house, 'L2', *gone), 'and on a reread of the drawings')
    check(len(house['walls']) == before - 1, (before, len(house['walls'])))


def test_person_placed_building_not_moved_by_fit():
    first = {'position': [60.0, 80.0], 'rotation': 90}
    _drawn_house(lot=True)
    ts.update_building('house', {'footprint': _footprint(first), 'footprint_from': 'plot'})
    b, _ = _build(DraftReader())
    check('fit' in [s['kind'] for s in tb.status(b)['steps']], 'test setup: the build fits the house')
    house = _house(ts.current())
    check(_near(house['position'], first['position'], 0.5) and _turn_gap(house['rotation'], 90) <= 1,
          ('test setup: the house sits on its footprint', house['position'], house['rotation']))
    twin_edit.save({'op': 'move', 'building': 'house', 'piece': 'house', 'by': [7, -4]}, 'p1')
    house = _house(ts.current())
    placed = (copy.deepcopy(house['position']), house['rotation'])
    check(house.get('position_from') == 'person', ('a move is the person placing it', house.get('position_from')))
    # The plot is read again and the footprint changes: the fit must not move it.
    ts.update_building('house', {'footprint': _footprint({'position': [150.0, 40.0], 'rotation': 0}),
                                 'footprint_from': 'plot'})
    _build(DraftReader())
    house = _house(ts.current())
    check(_near(house['position'], placed[0], 1e-6) and _turn_gap(house['rotation'], placed[1]) < 1e-6,
          ('the fit keeps the building where the person put it', placed, house['position'], house['rotation']))
    check(house.get('position_from') == 'person', house.get('position_from'))


def test_renamed_building_is_refit():
    first = {'position': [60.0, 80.0], 'rotation': 90}
    _drawn_house(lot=True)
    ts.update_building('house', {'footprint': _footprint(first), 'footprint_from': 'plot'})
    _build(DraftReader())
    house = _house(ts.current())
    check(_near(house['position'], first['position'], 0.5),
          ('test setup: the house sits on its footprint', house['position']))

    # The editor's card rename (a hand edit).
    twin_edit.save({'op': 'set', 'building': 'house', 'piece': 'house', 'field': 'name', 'value': 'Big house'}, 'p1')
    house = _house(ts.current())
    check(house['name'] == 'Big house', house['name'])
    check(house.get('position_from') != 'person', ('a rename never sets position_from', house.get('position_from')))
    second = {'position': [150.0, 40.0], 'rotation': 0}
    ts.update_building('house', {'footprint': _footprint(second), 'footprint_from': 'plot'})
    _build(DraftReader())
    house = _house(ts.current())
    check(house['name'] == 'Big house', ('the rebuild keeps the new name', house['name']))
    check(_near(house['position'], second['position'], 0.5) and _turn_gap(house['rotation'], 0) <= 1,
          ('a renamed building is still fitted onto its footprint', house['position'], house['rotation']))

    # Your place's rename (the building registry).
    ts.update_building('house', {'name': 'Biggest house'})
    house = _house(ts.current())
    check(house['name'] == 'Biggest house', house['name'])
    check(house.get('position_from') != 'person', ('a rename never sets position_from', house.get('position_from')))
    third = {'position': [-40.0, 120.0], 'rotation': 180}
    ts.update_building('house', {'footprint': _footprint(third), 'footprint_from': 'plot'})
    _build(DraftReader())
    house = _house(ts.current())
    check(_near(house['position'], third['position'], 0.5) and _turn_gap(house['rotation'], 180) <= 1,
          ('renamed in Your place, still refit', house['position'], house['rotation']))


def test_old_pipeline_edits_migrate():
    """The old first floor sits at the draft's offset by (-3, +2), turned 0:
    the fit maps old feet onto the draft by (+3, -2), and so every person
    piece moves the same way before the merge."""
    offset = (-3, 2)
    back = (-offset[0], -offset[1])
    _seed_old_pipeline(offset=offset, without=('i2',))
    old = {name: [_old_point(p, offset, 1) for p in ends] for name, ends in INTERIOR.items()}
    # Person-added: the wall the crop read missed, drawn where the drawing has it.
    twin_edit.save({'op': 'add_wall', 'building': 'house', 'level': 'L1',
                    'from': old['i2'][0], 'to': old['i2'][1]}, 'p1')
    added = next(w for w in _house(ts.current())['walls'] if (w.get('src') or {}).get('person'))
    # Person-moved: i1 slid 2 ft toward the rear.
    twin_edit.save({'op': 'move', 'building': 'house', 'piece': 'wall:old-i1', 'by': [0, 2]}, 'p1')
    # Tombstoned: i3 deleted.
    twin_edit.save({'op': 'delete', 'building': 'house', 'piece': 'wall:old-i3'}, 'p1')
    check(len(ts.tombstones()) == 1, ('test setup: one tombstone', ts.tombstones()))
    fit, rms = tr.fit_outline([_old_point(p, offset, 1) for p in L_DRAFT], L_DRAFT)
    check(rms <= 2 and _turn_gap(fit['angle'], 0) < 0.1 and _near(fit['offset'], back, 0.1),
          ('test setup: the old floor fits the draft by (+3, -2)', fit, rms))

    reader = DraftReader(answer=_l_answer())
    _, st = _build(reader)
    house = _house(ts.current())
    l1 = [w for w in house['walls'] if w['level'] == 'L1']
    walls = [(w['id'], w['from'], w['to'], (w.get('src') or {}).get('step') or 'person') for w in l1]

    # The person's wall lands on the draft's i2, and the two are one wall.
    mine = next((w for w in l1 if w['id'] == added['id']), None)
    check(mine is not None and (mine.get('src') or {}).get('person'), ('the added wall is kept as the person\'s', walls))
    check(_same_wall(mine, *INTERIOR['i2']), ('the added wall moved by the fit onto the drawing\'s wall', mine))
    check(len(_walls_at(house, 'L1', *INTERIOR['i2'])) == 1, ('one wall there, not two', walls))
    check(not _walls_at(house, 'L1', *old['i2']), ('nothing left at the old place', walls))

    # The moved wall moved by the fit too, and the draft's i1 is matched to it.
    moved = next((w for w in l1 if w['id'] == 'wall:old-i1'), None)
    check(moved is not None and (moved.get('src') or {}).get('person'), ('the moved wall is kept', walls))
    check(_same_wall(moved, *[_shift(p, [0, 2]) for p in INTERIOR['i1']]),
          ('the moved wall keeps the person\'s 2 ft, in the draft\'s feet', moved))
    check(not _walls_at(house, 'L1', *INTERIOR['i1']),
          ('the draft\'s i1 is matched by the moved wall\'s read geometry, never added again', walls))
    check(not _walls_at(house, 'L1', *[_shift(p, [0, 2]) for p in old['i1']]), ('nothing at the old place', walls))

    # The deleted wall stays deleted where the draft reads it.
    check(not _walls_at(house, 'L1', *INTERIOR['i3']), ('the tombstone moved with the fit', walls))
    check(not _walls_at(house, 'L1', *old['i3']), walls)
    check(not any(MAY_NEED_MOVING in e.get('text', '') for e in st['events'] if e['type'] == 'log'),
          'a good fit says nothing about moving changes')


def test_old_pipeline_poor_fit_keeps_and_logs():
    """The old floor is half again the draft's size: the fit is poor, so the
    person's pieces stay exactly where they were, and one line says so."""
    _seed_old_pipeline(offset=(0, 0), scale=1.5)
    fit, rms = tr.fit_outline([_old_point(p, (0, 0), 1.5) for p in L_DRAFT], L_DRAFT)
    check(rms > 2, ('test setup: the fit is poor', rms))
    added_at = ([33, 4], [33, 16])            # inside both floors, clear of every draft wall
    twin_edit.save({'op': 'add_wall', 'building': 'house', 'level': 'L1',
                    'from': added_at[0], 'to': added_at[1]}, 'p1')
    added = next(w for w in _house(ts.current())['walls'] if (w.get('src') or {}).get('person'))
    twin_edit.save({'op': 'move', 'building': 'house', 'piece': 'wall:old-i2', 'by': [3, 0]}, 'p1')
    moved_before = next(w for w in _house(ts.current())['walls'] if w['id'] == 'wall:old-i2')
    moved_at = (copy.deepcopy(moved_before['from']), copy.deepcopy(moved_before['to']))
    twin_edit.save({'op': 'delete', 'building': 'house', 'piece': 'wall:old-i3'}, 'p1')
    stones = copy.deepcopy(ts.tombstones())

    _, st = _build(DraftReader(answer=_l_answer()))
    house = _house(ts.current())
    mine = next((w for w in house['walls'] if w['id'] == added['id']), None)
    check(mine is not None and _same_wall(mine, *added_at, 0.05),
          ('the added wall is kept as it is', mine))
    moved = next((w for w in house['walls'] if w['id'] == 'wall:old-i2'), None)
    check(moved is not None and _same_wall(moved, *moved_at, 0.05), ('the moved wall is kept as it is', moved))
    check(ts.tombstones() == stones, ('the tombstones are kept as they are', ts.tombstones()))
    lines = [e['text'] for e in st['events'] if e['type'] == 'log' and MAY_NEED_MOVING in e.get('text', '')]
    check(len(lines) == 1, ('one log line says the changes may need moving',
                            lines, [e.get('text') for e in st['events'] if e['type'] == 'log'][-8:]))


def test_old_crop_walls_replaced_by_draft():
    """Task 7 review: a draft rebuild of an old-pipeline building never leaves
    the old crop walls (src.step 'walls:L1', 'walls:L1:main', 'outline:L1')
    orphaned beside the new draft walls, whether the old floor fits or not."""
    expected = len(L_DRAFT) + len(INTERIOR)
    for name, offset, scale in (('good fit', (-3, 2), 1.0), ('poor fit', (0, 0), 1.5)):
        _seed_old_pipeline(offset=offset, scale=scale)
        _build(DraftReader(answer=_l_answer()))
        house = _house(ts.current())
        l1 = [w for w in house['walls'] if w['level'] == 'L1']
        walls = [(w['id'], w['from'], w['to'], (w.get('src') or {}).get('step')) for w in l1]
        orphans = [w for w in walls if str(w[3] or '').startswith(('walls:', 'outline:'))]
        check(not orphans, (name, 'no old crop wall is left beside the draft\'s', orphans))
        check(all(w[3] == 'draft' for w in walls), (name, 'every wall is the draft\'s', walls))
        check(len(l1) == expected, (name, 'the draft\'s walls, once each', expected, len(l1), walls))
        for a, b in [*zip(L_DRAFT, L_DRAFT[1:] + L_DRAFT[:1]), *INTERIOR.values()]:
            check(len(_walls_at(house, 'L1', a, b)) == 1, (name, 'one wall on each drawn wall', a, b, walls))
        check(not any(_crop_step(l) for l in house['levels']), (name, 'the old outline is replaced too',
                                                                [l.get('src') for l in house['levels']]))


TESTS = (
    test_person_moved_wall_not_duplicated,
    test_person_deleted_wall_stays_deleted,
    test_person_placed_building_not_moved_by_fit,
    test_renamed_building_is_refit,
    test_old_pipeline_edits_migrate,
    test_old_pipeline_poor_fit_keeps_and_logs,
    test_old_crop_walls_replaced_by_draft,
)


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
    sys.exit(1 if failed else 0)

"""The draft step settles a whole building in feet (plan
docs/superpowers/plans/2026-11-08-house-editor-whole-building-draft.md, Task 7;
spec docs/superpowers/specs/2026-11-08-house-editor-whole-building-draft-design.md
sections 1, 2 and 5; controller ruling R2).

- A building part with floor pages builds as [draft, draft_rooms, finishes?,
  fit?, compose?]. The step ids equal their kinds; the labels are "Reading the
  drawings" and "Rooms". The legacy body {building, photos} and shells keep
  their steps exactly.
- The draft read sees every page of the building with role floor, roof,
  elevation or other, whole at up to 2576 px (or the person's region when one
  is cropped onto the building), then up to 4 of the building's tagged photos.
  Its context lists the pages and names the building.
- The answer is in feet and settles as is, with no registration mapping, in
  one settled event: levels, walls, openings, roof sections and the porch.
  Levels are L1..Ln by elevation and take their names from the floor pages.
- normalize, then the snap pass, then the section 5 checks. A failing piece is
  a ghost with a plain why; a first floor that fails pauses the build with
  "The drawings could not be read as one building." and Try again rereads it.
- The estimate shown before Build includes the draft and the rooms read.

The reader is a stub keyed by kind (its first argument). The draft answer is
the recorded whole-building spike answer, in feet. Sources are blank PDFs;
the image test gives each page its own paper size so every page image differs.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_build_draft.py
"""
import copy
import io
import json
import math
import os
import re
import sys
import tempfile
import traceback

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_build_draft_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import twin_build as tb  # noqa: E402
from services import twin_cost as tc  # noqa: E402
from services import twin_store as ts  # noqa: E402
import test_twin_build as engine_tests  # noqa: E402
from test_twin_build import Reader, _accept_all, _pdf, check  # noqa: E402

RECORDED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_reads', 'recorded', 'claude')
SPIKE_PATH = os.path.join(RECORDED, 'draft-main-spike-answer.json')
FULL = [0, 0, 1, 1]
FAILED_WHY = 'The drawings could not be read as one building.'
SLICE1_IDS = ['outline:L1', 'openings:L1', 'rooms:L1', 'registration:L2', 'openings:L2', 'rooms:L2',
              'roof', 'pitch', 'plot', 'site', 'finishes', 'compose']
CROP_KINDS = {'walls', 'openings', 'rooms', 'registration', 'roof', 'pitch'}
# Paper sizes in points, one per page, so every whole-page image differs.
SIZES = [(1224, 792), (1008, 792), (792, 612), (612, 792), (1224, 864), (864, 1224)]


# --- fakes and helpers ---------------------------------------------------------

def spike():
    with open(SPIKE_PATH, encoding='utf-8') as f:
        return json.load(f)


class DraftReader(Reader):
    """test_twin_build's fake, plus the draft kinds: 'draft' answers the spike
    (or a given answer), 'draft_level' answers the same building (so a later
    per-level fallback sees the same defect), 'draft_rooms' answers nothing."""

    def __init__(self, answer=None, rooms=None, **kw):
        super().__init__(**kw)
        self.answer = spike() if answer is None else answer
        self.rooms = {'rooms': [], 'walls': []} if rooms is None else rooms
        self.seen = []          # every call with its images and context, in order

    def __call__(self, kind, images, context, *, run, step):
        self.seen.append({'kind': kind, 'step': step, 'images': copy.deepcopy(images),
                          'context': copy.deepcopy(context)})
        if kind in ('draft', 'draft_level'):
            self.calls.append({'kind': kind, 'step': step, 'context': copy.deepcopy(context), 'images': len(images)})
            return copy.deepcopy(self.answer)
        if kind == 'draft_rooms':
            self.calls.append({'kind': kind, 'step': step, 'context': copy.deepcopy(context), 'images': len(images)})
            return copy.deepcopy(self.rooms)
        return super().__call__(kind, images, context, run=run, step=step)


def _kinds(b):
    return [s['kind'] for s in tb.status(b)['steps']]


def _ids(b):
    return [s['id'] for s in tb.status(b)['steps']]


def _read_kinds(reader):
    return [c['kind'] for c in reader.calls]


def _house(plan, bid='house'):
    return next(b for b in plan['buildings'] if b['id'] == bid)


def _wall_runs(walls):
    """Compare read walls across the connected model's persistent T splits."""
    runs = {}
    for wall in walls:
        if wall.get('kind') == 'separator':
            continue
        wid = wall['id'].split('~')[0]
        if wid not in runs:
            runs[wid] = copy.deepcopy(wall)
        else:
            run = runs[wid]
            check(run['to'] == wall['from'], ('split wall stays connected', wid, run, wall))
            check(run.get('state') == wall.get('state') and run.get('src') == wall.get('src'),
                  ('split wall keeps its state and source', wid, run, wall))
            run['to'] = list(wall['to'])
    return list(runs.values())


def _trouble(st):
    return [e for e in st['events'] if e['type'] in ('error', 'question')][-3:]


def _sized_pdf(sizes):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument.new()
    for w, h in sizes:
        doc.new_page(w, h)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _jpeg(colour):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (64, 48), colour).save(buf, format='JPEG')
    return buf.getvalue()


def _drawn_house(*, photos=1, roof=True):
    """Main house drawings: floor pages Main floor and Upper floor, a roof page,
    and photos tagged to the house. No lot."""
    engine_tests._fresh()
    sheets = ts.save_source('drawing', 'house.pdf', _pdf(3 if roof else 2))   # legacy upload: Main house, id house
    rows = [{'source': sheets, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None, 'building': 'house'},
            {'source': sheets, 'page': 2, 'role': 'floor', 'level': 'Upper floor', 'box': None, 'building': 'house'}]
    if roof:
        rows.append({'source': sheets, 'page': 3, 'role': 'roof', 'level': None, 'box': None, 'building': 'house'})
    ts.set_page_roles(rows)
    found = [ts.save_source('photo', f'house-{i}.jpg', _jpeg((40 * i, 90, 160)), part='house')
             for i in range(photos)]
    return sheets, found


def _classify(piece):
    """The kind of a settled piece, by its shape (ids are the engine's business)."""
    if not isinstance(piece, dict):
        return None
    if 'elevation' in piece and 'ceiling' in piece:
        return 'level'
    if 'columns' in piece or ('polygon' in piece and 'floor' in piece and 'level' not in piece):
        return 'porch'
    if 'rect' in piece:
        return 'roof'
    if 'wall' in piece and 'width' in piece:
        return 'opening'
    if 'from' in piece and 'to' in piece and 'thickness' in piece:
        return 'wall'
    return 'other'


def _bounds(points):
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def _plain(why, house):
    """A plain sentence: something said, and no raw piece id in it."""
    if not isinstance(why, str) or not why.strip():
        return False
    ids = {p['id'] for key in ('walls', 'openings', 'rooms') for p in house.get(key, []) if 'id' in p}
    ids |= {p['id'] for p in house['roof']['sections'] if 'id' in p}
    return (not re.search(r'\b(wall|opening|room|roof):', why) and not re.search(r'\b[wuk]\d+\b', why)
            and not any(i in why for i in ids))


def _spike_without_l2_wall(wall_id='u5'):
    answer = spike()
    answer['building']['walls'] = [w for w in answer['building']['walls'] if w['id'] != wall_id]
    return answer


def _spike_open_first_floor():
    """Every first-floor exterior wall shortened 2 ft at each end: no end meets
    another (gaps well past the 1 ft weld), so no L1 wall closes."""
    answer = spike()
    walls = []
    for wall in answer['building']['walls']:
        if wall['level'] != 'L1':
            walls.append(wall)
            continue
        length = math.dist(wall['from'], wall['to'])
        if length < 6:
            continue
        ux, uy = [(wall['to'][i] - wall['from'][i]) / length for i in (0, 1)]
        walls.append({**wall, 'from': [wall['from'][0] + 2 * ux, wall['from'][1] + 2 * uy],
                      'to': [wall['to'][0] - 2 * ux, wall['to'][1] - 2 * uy]})
    answer['building']['walls'] = walls
    kept = {w['id'] for w in walls}
    answer['building']['openings'] = [o for o in answer['building']['openings']
                                       if 'wall' not in o or o['wall'] in kept]   # gable openings stay
    return answer


def _spike_no_first_floor_walls():
    answer = spike()
    answer['building']['walls'] = [w for w in answer['building']['walls'] if w['level'] != 'L1']
    kept = {w['id'] for w in answer['building']['walls']}
    answer['building']['openings'] = [o for o in answer['building']['openings']
                                       if 'wall' not in o or o['wall'] in kept]   # gable openings stay
    return answer


def _block_roofs_cover(house):
    """Ruling R14 (roofs from blocks): one settled block roof over every block of the
    settled walls, tagged roof_blocks; returns (problems, block_roof_ids)."""
    from services import twin_blocks
    blocks = twin_blocks.blocks(house)
    derived = [s for s in house['roof']['sections'] if (s.get('src') or {}).get('step') == 'roof_blocks']
    problems, ids = [], set()
    for b in blocks:
        over = [s for s in derived if all(abs(a - c) <= 1 for a, c in zip(s['rect'], b['rect']))]
        if len(over) != 1 or over[0].get('state') == 'ghost':
            problems.append((b['rect'], [(s['rect'], s.get('state'), s.get('why')) for s in over]))
        ids.update(s['id'] for s in over)
    if not blocks:
        problems.append('no blocks')
    return problems, ids


# --- tests ---------------------------------------------------------------------

def test_plan_steps_draft():
    rows = [{'source': 's', 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None, 'building': 'house'},
            {'source': 's', 'page': 2, 'role': 'floor', 'level': 'Upper floor', 'box': None, 'building': 'house'},
            {'source': 's', 'page': 3, 'role': 'roof', 'level': None, 'box': None, 'building': 'house'},
            {'source': 's', 'page': 4, 'role': 'elevation', 'level': None, 'box': None, 'building': 'house'}]
    steps = tb.plan_steps(rows, ['photo-1'], [], part='house', has_lot=True, compose=True)
    check([s['id'] for s in steps] == ['draft', 'draft_rooms', 'finishes', 'fit', 'compose'],
          ('a drawn building: draft, rooms, finishes, fit, compose', [s['id'] for s in steps]))
    check([s['kind'] for s in steps] == [s['id'] for s in steps], ('each step id equals its kind', steps))
    labels = {s['id']: s['label'] for s in steps}
    check(labels['draft'] == 'Reading the drawings' and labels['draft_rooms'] == 'Rooms', labels)
    bare = tb.plan_steps(rows, [], [], part='house', has_lot=False, compose=True)
    check([s['id'] for s in bare] == ['draft', 'draft_rooms', 'compose'],
          ('no photos, no lot: no finishes, no fit', [s['id'] for s in bare]))
    quiet = tb.plan_steps(rows, ['photo-1'], [], part='house', has_lot=False, compose=False)
    check([s['id'] for s in quiet] == ['draft', 'draft_rooms', 'finishes'], [s['id'] for s in quiet])
    one = tb.plan_steps(rows[:1], [], [], part='house', has_lot=False, compose=True)
    check([s['id'] for s in one] == ['draft', 'draft_rooms', 'compose'], ('one floor page', [s['id'] for s in one]))
    retired = {s['kind'] for s in steps} & {'outline', 'registration', *CROP_KINDS}
    check(not retired, ('the crop steps are retired for drawn buildings', retired))
    # A started part build plans the same steps.
    _drawn_house(photos=1)
    b = tb.start({'part': 'house'}, reader=DraftReader(), inline=True)
    check(_ids(b)[:2] == ['draft', 'draft_rooms'] and _kinds(b)[:2] == ['draft', 'draft_rooms'], _ids(b))
    check(_ids(b) == ['draft', 'draft_rooms', 'finishes', 'compose'], _ids(b))


def test_draft_settles_all_at_once():
    _drawn_house(photos=1)
    reader = DraftReader()
    b = tb.start({'part': 'house'}, reader=reader, inline=True)
    st = _accept_all(b)
    check(st['state'] == 'done', (st['state'], st.get('pause'), _trouble(st)))
    check(_kinds(b) == ['draft', 'draft_rooms', 'finishes', 'compose'], _kinds(b))
    kinds = _read_kinds(reader)
    check(kinds.count('draft') == 1 and kinds.count('draft_rooms') == 1, ('one draft read, one rooms read', kinds))
    check(kinds.index('draft') < kinds.index('draft_rooms'), kinds)
    check(not CROP_KINDS & set(kinds), ('no crop reads for a drawn building', kinds))
    rooms_call = next(c for c in reader.seen if c['kind'] == 'draft_rooms')
    check(len(rooms_call['images']) == 2, ('the rooms read sees the two floor pages', len(rooms_call['images'])))

    settled = [e for e in st['events'] if e['type'] == 'settled' and e.get('step') == 'draft']
    check(len(settled) == 1, ('the draft settles in one event', len(settled)))
    got = {}
    for piece in settled[0]['pieces']:
        got.setdefault(_classify(piece), []).append(piece)
    counts = {k: len(v) for k, v in got.items()}
    check(len(got.get('level', [])) == 2, ('both levels settle', counts))
    check(len(got.get('wall', [])) >= 28, ('the exterior walls settle', counts))
    check(len(got.get('opening', [])) >= 18, ('the openings settle', counts))
    check(any(o.get('section') and 'gable' in o for o in settled[0]['pieces']),
          ('at least one gable opening settles with the whole draft', settled[0]['pieces']))
    main_roofs = {'main', 'cross_gable', 'left_wing', 'front_wing', 'right_block',
                  'side_wing', 'rear_gable', 'kitchen_bump'}
    # Ruling R14: the main roof now comes from the blocks; the porch roofs stay as read.
    other_rects = {tuple(s['rect']) for s in spike()['building']['roof']['sections']
                   if s['id'] not in main_roofs}
    check(len(other_rects) == 3, ('test setup: three porch roofs', other_rects))
    check(any((s.get('src') or {}).get('step') == 'roof_blocks' for s in got.get('roof', [])),
          ('the block roofs settle in the draft event', got.get('roof', [])))
    check(not any('bearing walls' in e.get('text', '') for e in st['events']
                  if e['type'] == 'log' and e.get('step') == 'draft'),
          'no bearing-wall failures for the main roof')
    check(len(got.get('porch', [])) == 1, ('the porch settles', counts))

    plan = ts.current()
    house = _house(plan)
    check((house['id'], house['name'], house.get('kind')) == ('house', 'Main house', 'main_house'),
          ('the building keeps its own identity, not the answer\'s', house['id'], house['name']))
    check(len(_wall_runs(house['walls'])) == 34, ('every wall of the draft is in the plan', len(house['walls'])))
    problems, block_ids = _block_roofs_cover(house)
    check(not problems, ('one settled block roof over every block', problems))
    read_roofs = [s for s in house['roof']['sections'] if s['id'] not in block_ids
                  and (s.get('src') or {}).get('step') != 'roof_blocks']
    check(len(read_roofs) == 3 and {tuple(s.get('read_geometry', {}).get('rect', s['rect'])) for s in read_roofs}
          == {tuple(s['rect']) for s in spike()['building']['roof']['sections'] if s['id'] not in main_roofs},
          ('the three porch roofs are in the plan as read', [s['rect'] for s in read_roofs]))
    check(len(house['openings']) >= 20, len(house['openings']))
    check(len(house['porches']) == 1 and len(house['porches'][0].get('columns') or []) == 4, house['porches'])
    check(len(house.get('stairs') or []) == 1, house.get('stairs'))
    for piece in [*_wall_runs(house['walls']), *house['openings'], *house['roof']['sections']]:
        allowed = ('draft', 'roof_blocks') if piece in house['roof']['sections'] else ('draft',)
        check((piece.get('src') or {}).get('step') in allowed, ('every piece names the draft step', piece.get('src')))
    # In feet as is: no registration mapping moved it.
    l1 = next(l for l in house['levels'] if l['id'] == 'L1')
    box = _bounds(l1['outline'])
    check(all(abs(a - b) <= 0.5 for a, b in zip(box, [0, -1, 70, 65.33])), ('L1 stays in feet', box))
    l2 = next(l for l in house['levels'] if l['id'] == 'L2')
    check(abs(l2['elevation'] - 10.9) <= 0.5, l2)
    walls = {(round(w['from'][0]), round(w['from'][1]), round(w['to'][0]), round(w['to'][1]))
             for w in _wall_runs(house['walls'])}
    check((0, 14, 23, 14) in walls and (70, 22, 70, 42) in walls, ('walls keep their feet', sorted(walls)[:6]))
    # The snap pass ran on the settle: the awning hangs from its wall.
    extensions = house['roof'].get('extensions') or []
    check(len(extensions) == 1 and extensions[0].get('wall'), ('snap attached the awning', extensions))


def test_draft_images_whole_pages_and_photos():
    engine_tests._fresh()
    sheets = ts.save_source('drawing', 'house.pdf', _sized_pdf(SIZES[:4]))
    extra = ts.save_source('drawing', 'details.pdf', _sized_pdf(SIZES[4:6]), part='house')
    ts.add_building('Shed', 'shed')
    shed_sheet = ts.save_source('drawing', 'shed.pdf', _sized_pdf([(700, 500)]), part='shed')
    region = [0.1, 0.05, 0.9, 0.95]
    rows = [{'source': sheets, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None, 'building': 'house'},
            {'source': sheets, 'page': 2, 'role': 'floor', 'level': 'Upper floor', 'box': region, 'building': 'house'},
            {'source': sheets, 'page': 3, 'role': 'roof', 'level': None, 'box': None, 'building': 'house'},
            {'source': sheets, 'page': 4, 'role': 'elevation', 'level': None, 'box': None, 'building': 'house'},
            {'source': extra, 'page': 1, 'role': 'other', 'level': None, 'box': None, 'building': 'house'},
            {'source': extra, 'page': 2, 'role': 'skip', 'level': None, 'box': None, 'building': 'house'},
            {'source': shed_sheet, 'page': 1, 'role': 'floor', 'level': 'Floor', 'box': None, 'building': 'shed'}]
    ts.set_page_roles(rows)
    house_photos = [ts.save_source('photo', f'house-{i}.jpg', _jpeg((30 * i, 120, 200)), part='house')
                    for i in range(5)]
    shed_photo = ts.save_source('photo', 'shed.jpg', _jpeg((250, 10, 10)), part='shed')
    lot_photo = ts.save_source('photo', 'yard.jpg', _jpeg((10, 250, 10)), part='lot')

    reader = DraftReader()
    tb.start({'part': 'house'}, reader=reader, inline=True)
    call = next((c for c in reader.seen if c['kind'] == 'draft'), None)
    check(call is not None, ('the draft is read', [c['kind'] for c in reader.seen]))
    images, context = call['images'], call['context']

    wanted = [r for r in rows if r['building'] == 'house' and r['role'] in ('floor', 'roof', 'elevation', 'other')]
    expected = {r['page'] if r['source'] == sheets else 10 + r['page']:
                ts.crop(r['source'], r['page'], r['box'] or FULL, max_side=2576)['b64'] for r in wanted}
    check(len(set(expected.values())) == len(wanted), 'test setup: every page image differs')
    n = len(wanted)
    check(len(images) > n, ('pages, then photos', len(images)))
    page_images = images[:n]
    check(all(i.get('mime') == 'image/png' for i in page_images), [i.get('mime') for i in page_images])
    check(sorted(i['b64'] for i in page_images) == sorted(expected.values()),
          ('every floor, roof, elevation and other page, whole at 2576 px or the person\'s region; '
           'skip pages and other buildings left out', len(page_images)))
    skipped = ts.crop(extra, 2, FULL, max_side=2576)['b64']
    shed_page = ts.crop(shed_sheet, 1, FULL, max_side=2576)['b64']
    check(skipped not in [i['b64'] for i in images] and shed_page not in [i['b64'] for i in images],
          'no skip page, no other building\'s page')

    photo_images = images[n:]
    allowed = {ts.source_images(p)[0]['b64'] for p in house_photos}
    others = {ts.source_images(p)[0]['b64'] for p in (shed_photo, lot_photo)}
    check(1 <= len(photo_images) <= 4, ('up to 4 photos after the pages', len(photo_images)))
    check(all(i['b64'] in allowed for i in photo_images), 'only photos tagged to this building')
    check(not any(i['b64'] in others for i in photo_images), 'never another part\'s photo')
    check(len({i['b64'] for i in photo_images}) == len(photo_images), 'each photo once')

    building = context.get('building') or {}
    check(building.get('name') == 'Main house' and building.get('kind') == 'main_house', building)
    pages = context.get('pages')
    check(isinstance(pages, list) and len(pages) == n, ('the context lists each page', pages))
    indexes = [p.get('image') for p in pages]
    check(all(type(i) is int for i in indexes) and len(set(indexes)) == n, indexes)
    base = min(indexes)
    check(base in (0, 1) and sorted(indexes) == list(range(base, base + n)), ('pages index the first images', indexes))
    by_b64 = {v: k for k, v in expected.items()}
    for entry in pages:
        key = by_b64.get(images[entry['image'] - base]['b64'])
        row = next(r for r in wanted if (r['page'] if r['source'] == sheets else 10 + r['page']) == key)
        check(entry.get('role') == row['role'], ('each page entry names its role', entry, row['role']))
        if row['role'] == 'floor':
            check(entry.get('level_name') == row['level'], ('a floor page carries its level name', entry))


def test_draft_levels_named_from_pages():
    _drawn_house(photos=0)
    b = tb.start({'part': 'house'}, reader=DraftReader(), inline=True)
    st = _accept_all(b)
    check(st['state'] == 'done', (st['state'], st.get('pause'), _trouble(st)))
    levels = sorted(_house(ts.current())['levels'], key=lambda l: l['elevation'])
    check([(l['id'], l['name']) for l in levels] == [('L1', 'Main floor'), ('L2', 'Upper floor')],
          ('the page level names, not the answer\'s', [(l['id'], l['name']) for l in levels]))
    # Levels listed out of order in the answer still come out L1..Ln by elevation.
    answer = spike()
    answer['building']['levels'] = list(reversed(answer['building']['levels']))
    _drawn_house(photos=0)
    b = tb.start({'part': 'house'}, reader=DraftReader(answer=answer), inline=True)
    st = _accept_all(b)
    check(st['state'] == 'done', (st['state'], st.get('pause'), _trouble(st)))
    house = _house(ts.current())
    levels = sorted(house['levels'], key=lambda l: l['elevation'])
    check([(l['id'], l['name']) for l in levels] == [('L1', 'Main floor'), ('L2', 'Upper floor')]
          and abs(levels[0]['elevation']) <= 0.5 and abs(levels[1]['elevation'] - 10.9) <= 0.5,
          [(l['id'], l['name'], l['elevation']) for l in levels])
    check(sum(w['level'] == 'L1' for w in _wall_runs(house['walls'])) == 22,
          ('the first floor keeps its walls', len(house['walls'])))


def test_open_upper_walls_become_ghost_with_why():
    _drawn_house(photos=0)
    reader = DraftReader(answer=_spike_without_l2_wall('u5'))
    b = tb.start({'part': 'house'}, reader=reader, inline=True)
    st = tb.status(b)
    check(st['state'] == 'done', ('an open upper floor never pauses', st['state'], st.get('pause'), _trouble(st)))
    house = _house(ts.current())
    l1 = [w for w in _wall_runs(house['walls']) if w['level'] == 'L1' and w.get('exterior')]
    l2 = [w for w in _wall_runs(house['walls']) if w['level'] == 'L2' and w.get('exterior')]
    check(len(l1) == 22 and all(w.get('state') == 'settled' for w in l1),
          ('the first floor closes and settles', [w.get('state') for w in l1]))
    check(len(l2) == 5, ('the open upper walls stay in the plan', len(l2)))
    check(any(w.get('state') == 'ghost' for w in l2), ('the open upper walls are ghosts', [w.get('state') for w in l2]))
    ghosts = [e for e in st['events'] if e['type'] == 'ghost' and e.get('step') == 'draft'
              and (e.get('piece') or {}).get('level') == 'L2']
    check(ghosts, ('a ghost event for the upper floor', [e for e in st['events'] if e['type'] == 'ghost'][:3]))
    check(all(_plain(e.get('why'), house) for e in ghosts), ('each ghost has a plain why', [e.get('why') for e in ghosts]))
    settled = next(e for e in st['events'] if e['type'] == 'settled' and e.get('step') == 'draft')
    ghost_ids = {w['id'] for w in l2 if w.get('state') == 'ghost'}
    check(not any(p.get('id') in ghost_ids for p in settled['pieces']), 'a ghost is never in the settled event')
    check(any(_classify(p) == 'wall' and p.get('level') == 'L1' for p in settled['pieces']), 'the rest settle')


def test_first_floor_failure_pauses():
    for name, answer in (('open first floor', _spike_open_first_floor()),
                         ('first floor without walls', _spike_no_first_floor_walls())):
        _drawn_house(photos=0)
        reader = DraftReader(answer=answer)
        b = tb.start({'part': 'house'}, reader=reader, inline=True)
        st = tb.status(b)
        check(st['state'] == 'paused', (name, st['state'], _trouble(st)))
        check(st['pause']['step'] == 'draft' and st['pause']['why'] == FAILED_WHY, (name, st['pause']))
        check('draft_rooms' not in _read_kinds(reader), (name, 'the build stops at the draft', _read_kinds(reader)))
        plan = ts.current()
        house = next((x for x in (plan or {}).get('buildings', []) if x['id'] == 'house'), None)
        settled_l1 = [w for w in (house or {}).get('walls', []) if w['level'] == 'L1' and w.get('state') == 'settled']
        check(not settled_l1, (name, 'no first-floor wall settles', len(settled_l1)))
        # The pause survives a restart, as every paused build does.
        tb._forget()
        tb.recover()
        st = tb.status(b)
        check(st['state'] == 'paused' and st['pause']['step'] == 'draft', (name, 'after a restart', st['state'], st['pause']))
        # Try again rereads the drawings.
        good = DraftReader()
        tb.reread(b, 'draft', reader=good, inline=True)
        st = _accept_all(b)
        check(st['state'] == 'done', (name, 'Try again reads it again', st['state'], st.get('pause'), _trouble(st)))
        check(_read_kinds(good).count('draft') == 1, (name, _read_kinds(good)))
        house = _house(ts.current())
        l1 = [w for w in _wall_runs(house['walls']) if w['level'] == 'L1' and w.get('exterior')]
        check(len(l1) == 22 and all(w.get('state') == 'settled' for w in l1), (name, [w.get('state') for w in l1]))


def test_legacy_body_steps_unchanged():
    engine_tests._fresh()
    _, _, photo = engine_tests._sources()
    reader = DraftReader()
    b = tb.start({'building': {'id': 'house', 'name': 'Main house'}, 'photos': [photo]}, reader=reader, inline=True)
    check(_ids(b) == SLICE1_IDS, ('the legacy body keeps slice 1\'s steps', _ids(b)))
    st = _accept_all(b)
    check(st['state'] == 'done', (st['state'], _trouble(st)))
    kinds = _read_kinds(reader)
    check(not {'draft', 'draft_level', 'draft_rooms'} & set(kinds), ('the legacy body never reads a draft', kinds))
    check('walls' in _kinds(b) and 'draft' not in _kinds(b), _kinds(b))


def test_shell_unchanged():
    engine_tests._fresh()
    shed = ts.add_building('Shed', 'shed')
    ts.update_building(shed['id'], {'footprint': [[0, 0], [10, 0], [10, 12], [0, 12]], 'footprint_from': 'typed'})
    reader = DraftReader()
    b = tb.start({'part': 'shed'}, reader=reader, inline=True)
    check(_ids(b) == ['shell', 'compose'], ('a building without drawings builds as a shell', _ids(b)))
    st = _accept_all(b)
    check(st['state'] == 'done', (st['state'], _trouble(st)))
    check(reader.calls == [], ('a shell is never read', _read_kinds(reader)))


def test_draft_cost_estimate_shown():
    _, photos = _drawn_house(photos=2)
    from fastapi.testclient import TestClient
    import main
    main.trigger_background_refresh = lambda *a, **k: None
    with TestClient(main.app) as c:
        r = c.get('/api/house/editor/sheets')
    check(r.status_code == 200, r.text[:300])
    estimates = r.json().get('estimates') or {}
    build = (estimates.get('build') or {}).get('house')
    check(isinstance(build, dict), ('the sheets carry the estimate shown before Build, per building', estimates))
    # The draft sees 3 pages and the 2 photos; the rooms read sees the 2 floor pages.
    check(build.get('draft') == tc.estimate('draft', 5), ('the estimate includes the draft read', build))
    check(build.get('draft_rooms') == tc.estimate('draft_rooms', 2), ('and the rooms read', build))
    total = build.get('total')
    check(isinstance(total, (int, float)) and total >= build['draft'] + build['draft_rooms'] - 1e-9,
          ('the total covers both', build))


def test_fallback_resume_keeps_completed_reads():
    _drawn_house(photos=0)
    building = spike()['building']

    class StoppedReader(DraftReader):
        def __call__(self, kind, images, context, *, run, step):
            if kind != 'draft_level':
                return super().__call__(kind, images, context, run=run, step=step)
            scope = context['level']
            self.calls.append({'kind': kind, 'scope': scope})
            if scope == 'roof':
                return {'building': {'roof': building['roof'],
                                     'openings': [o for o in building['openings'] if 'section' in o]}}
            walls = [w for w in building['walls'] if w['level'] == scope]
            wall_ids = {w['id'] for w in walls}
            # Independent reads commonly reuse w1, w2, ... on each floor.
            rename = {w['id']: f'w{i + 1}' for i, w in enumerate(walls)}
            partial = {'levels': [l for l in building['levels'] if l['id'] == scope],
                       'walls': [{**w, 'id': rename[w['id']]} for w in walls],
                       'openings': [{**o, 'wall': rename[o['wall']]} for o in building['openings']
                                    if o.get('wall') in wall_ids]}
            if scope == 'L1':
                partial.update(porch=building['porch'], stairs=building['stairs'])
                tb.stop(run)
            return {'building': partial}

    reader = StoppedReader(answer={'error': 'Cut off at the output limit.', 'truncated': True})
    b = tb.start({'part': 'house'}, reader=reader, inline=True)
    check(tb.status(b)['state'] == 'stopped', tb.status(b)['state'])
    check([c.get('scope') for c in reader.calls if c['kind'] == 'draft_level'] == ['L1'],
          'a stop does not start another paid read')
    tb._forget()
    tb.recover()
    tb.resume(b, reader=reader, inline=True)
    st = tb.status(b)
    check(st['state'] == 'done', ('resume continues the remaining floors', st['state'], _trouble(st)))
    check([c.get('scope') for c in reader.calls if c['kind'] == 'draft_level'] == ['L1', 'L2', 'roof'],
          'completed floors are cached across restart')
    check(_read_kinds(reader).count('draft') == 1 and _read_kinds(reader).count('outline') == 1,
          'resume reuses the whole read too')
    house = _house(ts.current())
    carriers = {w['id']: w['level'] for w in house['walls']}
    source_levels = {w['id']: w['level'] for w in building['walls']}
    for level in ('L1', 'L2'):
        got = sum(carriers.get(o.get('wall')) == level for o in house['openings'])
        expected = sum(source_levels.get(o.get('wall')) == level for o in building['openings'])
        check(got == expected, ('reused wall names keep openings on their own floor', level, got, expected))
    check(sum(e['type'] == 'log' and e.get('text') == 'The drawings were read one floor at a time.'
              for e in st['events']) == 1, 'resume does not repeat the fallback sentence')


def test_rooms_edges_stay_inside_a_concave_floor():
    _drawn_house(photos=0)
    outline = [[0, 0], [30, 0], [30, 30], [20, 30], [20, 10], [10, 10], [10, 30], [0, 30]]
    building = {'levels': [{'id': 'L1', 'name': 'Main floor', 'elevation': 0,
                            'ceiling': 9, 'outline': outline}],
                'walls': [{'id': f'edge{i}', 'level': 'L1', 'from': a, 'to': b,
                           'height': 9, 'thickness': .5, 'exterior': True}
                          for i, (a, b) in enumerate(zip(outline, outline[1:] + outline[:1]))],
                'openings': [], 'rooms': [], 'roof': {'sections': []}, 'stairs': []}
    rooms = {'rooms': [
        {'name': 'Inside', 'level': 'L1', 'polygon': [[0, 0], [30, 0], [30, 10], [0, 10]]},
        {'name': 'Across recess', 'level': 'L1', 'polygon': [[5, 20], [25, 20], [15, 5]]}],
        'walls': [{'level': 'L1', 'from': [5, y], 'to': [25, y], 'height': 9,
                   'thickness': .33, 'exterior': False} for y in (10, 20)]}
    reader = DraftReader(answer={'building': building}, rooms=rooms)
    b = tb.start({'part': 'house'}, reader=reader, inline=True)
    st = tb.status(b)
    check(st['state'] == 'done', (st['state'], _trouble(st)))
    house = _house(ts.current())
    found = {r['name']: r for r in house['rooms']}
    check(found['Inside']['state'] == 'settled', 'the outline boundary is inside')
    check(found['Across recess']['state'] == 'ghost', 'inside vertices cannot hide an edge across a recess')
    walls = [w for w in _wall_runs(house['walls']) if w.get('src', {}).get('step') == 'draft_rooms']
    check(len(walls) == 2, walls)
    check({w['from'][1]: w['state'] for w in walls} == {10: 'settled', 20: 'ghost'}, walls)
    stray_ids = {found['Across recess']['id']} | {w['id'] for w in walls if w['state'] == 'ghost'}
    check(stray_ids <= {e.get('piece', {}).get('id') for e in st['events']
                        if e['type'] == 'ghost' and e.get('step') == 'draft_rooms'}, 'strays emit ghosts')


TESTS = (
    test_plan_steps_draft,
    test_draft_settles_all_at_once,
    test_draft_images_whole_pages_and_photos,
    test_draft_levels_named_from_pages,
    test_open_upper_walls_become_ghost_with_why,
    test_first_floor_failure_pauses,
    test_legacy_body_steps_unchanged,
    test_shell_unchanged,
    test_draft_cost_estimate_shown,
    test_fallback_resume_keeps_completed_reads,
    test_rooms_edges_stay_inside_a_concave_floor,
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

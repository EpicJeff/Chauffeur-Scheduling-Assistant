"""The plot plan read in setup, its suggestions, the lot placement, photo
suggestions and cost estimates (plan .superpowers/sdd/
2026-11-07-house-editor-slice-1b-i, Task 3, with amendments A4-A6):

- read_plot reads the lot's plot page once (run place, step plot) and stores
  the read with its suggestions, registration, matrix and cost;
- a read that went stale while the reader ran is discarded (A4), and an
  answer naming an older read is refused;
- suggestions are accepted as a new building, matched to an existing one or
  dismissed; an accepted footprint fits an already built building at once
  unless a person placed it;
- confirm_placement saves the lot placement, rebuilds the registration for a
  new street edge, moves accepted footprints with the lot and refits built
  buildings whose footprint changed (A5);
- a plot page that changes role or moves off the lot clears the read;
- suggest_photos suggests parts per photo and shells, never applying them,
  and drops indices and parts it did not send (A6), also through the real
  reader with model_pools.call_pool_json stubbed;
- twin_cost.estimate prices a read before it runs.

The reader is a fake standing in for twin_reads.read unless a scenario says
it goes through the real reader. Sources are blank 17 x 11 inch PDFs
(masters 5100 x 3300 px); the plot answer is tests/fixtures/twin_reads/
plot.json (two buildings, street_edge [1, 2]).

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_place_reads.py
"""
import base64
import copy
import io
import json
import math
import os
import shutil
import sys
import tempfile
import traceback

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_place_reads_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import model_pools, storage  # noqa: E402
from services import twin_build as tb  # noqa: E402
from services import twin_cost as tc  # noqa: E402
from services import twin_place as tp  # noqa: E402
from services import twin_reads  # noqa: E402
from services import twin_register as tr  # noqa: E402
from services import twin_store as ts  # noqa: E402


class _Missing:
    """Lets each scenario fail on its own while twin_place_reads does not exist."""

    def __init__(self, exc):
        self.exc = exc

    def __getattr__(self, name):
        raise ImportError(f'services.twin_place_reads is missing ({self.exc}); wanted {name}')


try:
    from services import twin_place_reads as tpr  # noqa: E402
except ImportError as _exc:
    tpr = _Missing(_exc)


FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_reads')
OPUS = 'anthropic:claude-opus-5-5'
PRICED = next(iter(tc.PRICES))
W, H = 5100, 3300
FULL_CROP = {'box': [0, 0, 1, 1], 'master': [W, H]}
RECT40 = [[0, 0], [40, 0], [40, 30], [0, 30]]
RECT20 = [[0, 0], [20, 0], [20, 15], [0, 15]]
BOW_TIE = [[0, 0], [10, 10], [10, 0], [0, 10]]

NO_PLOT = 'Confirm a plot plan page on the lot first.'
READ_FAILED = 'The plot plan could not be read. Try again, or place the buildings by hand.'
CHANGED = 'The plot plan changed while it was being read. Read it again.'
OUT_OF_DATE = 'This plot plan read is out of date. Read it again.'
ANSWERED = 'This suggestion was already answered.'
CROSS = 'A footprint cannot cross itself.'
READ_KEYS = {'id', 'source', 'page', 'box', 'crop', 'fragment', 'registration', 'lot', 'street_edge',
             'suggestions', 'matrix', 'cost'}
SUGGESTION_KEYS = {'id', 'outline', 'outline_px', 'size_ft', 'where', 'name', 'state', 'building'}
PLACEMENT_KEYS = {'source', 'page', 'box', 'outline', 'street_edge', 'registration', 'confirmed'}
PHOTO_ANSWER = {'photos': [{'index': 0, 'parts': ['house', 'lot']}],
                'shells': [{'building': 'shed', 'storeys': 1, 'roof': 'gable', 'pitch': 7,
                            'confidence': 0.4, 'why': 'side photo'}]}


def check(cond, msg):
    # Local on purpose: tests/harness.py stubs storage.get_settings.
    if not cond:
        raise AssertionError(msg)


def expect_value_error(fn, message=None):
    try:
        fn()
    except ImportError:
        raise
    except ValueError as exc:
        if message is not None:
            check(str(exc) == message, f'expected {message!r}, got {str(exc)!r}')
        return str(exc)
    raise AssertionError(f'expected ValueError{" " + repr(message) if message else ""}')


def close(a, b, tol=1e-6):
    return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


def close_points(a, b, tol=1e-6):
    return len(a) == len(b) and all(close(p, q, tol) for p, q in zip(a, b))


def fixture(kind):
    with open(os.path.join(FIXTURES, f'{kind}.json'), encoding='utf-8') as f:
        return json.load(f)


def _fresh():
    storage.patch_settings({'house_twin': None, 'house_twin_cost': None})
    shutil.rmtree(ts.DATA_DIR, ignore_errors=True)
    tb._forget()


def _pdf(pages=1, w=1224, h=792):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(w, h)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _photo(w=64, h=48, fmt='PNG'):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (w, h), (120, 140, 160)).save(buf, format=fmt)
    return buf.getvalue()


def _area(points):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))) / 2


def _mean(points):
    return [sum(p[i] for p in points) / len(points) for i in (0, 1)]


def _bounds(points):
    return [min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points)]


def _expected_reg(crop, frag, edge=None):
    """The build's plot registration, written out independently: the street
    edge runs along +x from the origin and the lot lies at +y behind it."""
    scale = tr.from_dimension(tp.to_master(crop, frag['scale']['a']), tp.to_master(crop, frag['scale']['b']),
                              frag['scale']['feet'])
    lot = [tp.to_master(crop, p) for p in frag['lot']]
    i, j = edge or frag['street_edge']
    a, b = lot[i], lot[j]
    reg = tr.from_two_points(a, b, [0, 0], [math.dist(a, b) * scale, 0])
    edges = list(zip(lot, lot[1:] + lot[:1]))
    area2 = sum(a[0] * b[1] - b[0] * a[1] for a, b in edges)
    centre = ([sum((a[i] + b[i]) * (a[0] * b[1] - b[0] * a[1])
                   for a, b in edges) / (3 * area2) for i in (0, 1)]
              if abs(area2) >= 1e-9 else _mean(lot))
    if tr.apply(reg, centre)[1] < 0:
        reg = tr.from_two_points(b, a, [0, 0], [math.dist(a, b) * scale, 0])
    return reg


def _same_reg(a, b, tol=1e-6):
    probes = [[0, 0], [W, 0], [0, H], [W / 3, H / 2]]
    return all(close(tr.apply(a, p), tr.apply(b, p), tol) for p in probes)


def _uv(reg, world):
    px = tr.invert(reg, world)
    return [px[0] / W, px[1] / H]


def _answer_with(buildings):
    """The plot fixture with its buildings drawn where the given world outlines lie."""
    answer = fixture('plot')
    reg = _expected_reg(FULL_CROP, answer)
    answer['buildings'] = [{'name': name, 'outline': [_uv(reg, p) for p in outline]}
                           for name, outline in buildings]
    return answer


def _moved(points, dx, dy):
    return [[p[0] + dx, p[1] + dy] for p in points]


class PlotReader:
    """Stands in for twin_reads.read on the plot read; records one usage row."""

    def __init__(self, answer=None, during=None, usage=True):
        self.answer = fixture('plot') if answer is None else answer
        self.during, self.usage, self.calls = during, usage, []

    def __call__(self, kind, images, context, *, run, step):
        self.calls.append({'kind': kind, 'images': len(images), 'context': copy.deepcopy(context),
                           'run': run, 'step': step})
        if self.usage:
            tc.record(f'step:{kind}', [{'model': OPUS, 'input_tokens': 3000, 'output_tokens': 500}], run)
        if self.during is not None:
            self.during()
        return copy.deepcopy(self.answer)


class PhotoReader:
    """Stands in for twin_reads.read on the photo suggestion read."""

    def __init__(self, answer=None):
        self.answer = PHOTO_ANSWER if answer is None else answer
        self.calls = []

    def __call__(self, kind, images, context, *, run, step):
        from PIL import Image
        sizes = []
        for image in images:
            with Image.open(io.BytesIO(base64.b64decode(image['b64']))) as opened:
                sizes.append(list(opened.size))
        self.calls.append({'kind': kind, 'sizes': sizes, 'context': copy.deepcopy(context),
                           'run': run, 'step': step})
        tc.record(f'step:{kind}', [{'model': OPUS, 'input_tokens': 2000, 'output_tokens': 300}], run)
        return copy.deepcopy(self.answer)


class Pool:
    """Stands in for model_pools.call_pool_json under the real twin_reads.read."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def __call__(self, tier, api_key, system_prompt, user_prompt, **kw):
        self.calls.append({'tier': tier, 'system': system_prompt, **kw})
        if kw.get('usage') is not None:
            kw['usage'].append({'model': PRICED, 'input_tokens': 1500, 'output_tokens': 300,
                                'images': len(kw.get('images') or []), 'prompt_chars': len(user_prompt),
                                'max_output_tokens': kw.get('max_output_tokens') or 0})
        return copy.deepcopy(self.answer)

    def __enter__(self):
        self.original = model_pools.call_pool_json
        model_pools.call_pool_json = self
        return self

    def __exit__(self, *exc):
        model_pools.call_pool_json = self.original
        return False


def _plan(house_person=False):
    """A built house (L1 a 40 x 30 rectangle at the origin) and a pool house a
    person placed (src.person), both unmoved."""
    house = {'id': 'house', 'name': 'Main house', 'position': [0, 0], 'rotation': 0,
             'levels': [{'id': 'L2', 'name': 'Upper floor', 'elevation': 10, 'ceiling': 8,
                         'outline': [[0, 0], [20, 0], [20, 20], [0, 20]]},
                        {'id': 'L1', 'name': 'Main floor', 'elevation': 0, 'ceiling': 9, 'outline': RECT40}]}
    if house_person:
        house['src'] = {'person': True}
    pool = {'id': 'pool_house', 'name': 'Pool house', 'position': [0, 0], 'rotation': 0, 'src': {'person': True},
            'levels': [{'id': 'L1', 'name': 'Main floor', 'elevation': 0, 'ceiling': 9, 'outline': RECT20}]}
    return {'schema': 'chauffeur.twin.plan/2', 'units': 'ft', 'materials': {}, 'site': {},
            'buildings': [house, pool]}


def _setup(plan=None):
    """Main house with a floor page and the lot with a plot page; returns
    (house source, plot source)."""
    _fresh()
    if plan is not None:
        ts.push_round(plan, 'build')
        ts.place()      # the place migrates from the plan: house and pool_house
    house = ts.save_source('drawing', 'house.pdf', _pdf(1))           # no part: Main house
    plot = ts.save_source('drawing', 'plot.pdf', _pdf(1), part='lot')
    ts.set_page_roles([
        {'source': house, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None, 'building': 'house'},
        {'source': plot, 'page': 1, 'role': 'plot', 'level': None, 'box': None, 'building': 'lot'}])
    check(any(b['id'] == 'house' for b in ts.place()['buildings']), 'the place has Main house as house')
    return house, plot


def _lot():
    return ts.place()['lot']


def _read():
    return _lot()['read']


def _suggestion(sid):
    return next(s for s in _read()['suggestions'] if s['id'] == sid)


def _building(bid):
    return next((b for b in ts.place()['buildings'] if b['id'] == bid), None)


def _plan_building(bid):
    return next(b for b in ts.current()['buildings'] if b['id'] == bid)


def _with_role(rows, source, role):
    return [{**row, 'role': role} if row['source'] == source else row for row in rows]


def _fits(building, level_outline, footprint, tol=0.5):
    world = [tr.to_world(building, p) for p in level_outline]
    return all(min(math.dist(p, q) for q in footprint) <= tol for p in world)


# --- pure math: twin_place.plot_registration, plot_suggestions, sheet_matrix ---

def scenario_plot_math():
    frag, problems = twin_reads.parse('plot', fixture('plot'))
    check(problems == [] and frag['street_edge'] == [1, 2] and len(frag['buildings']) == 2,
          ('the fixture keeps two buildings and street_edge [1, 2]', frag, problems))
    crop = {**FULL_CROP, 'size': [2048, 1325]}
    reg = tp.plot_registration(crop, frag)
    check(_same_reg(reg, _expected_reg(crop, frag)), ('the fragment street edge', reg))
    depth = 0.35 * W * 150.2 / (0.47 * H)
    lot = [tr.apply(reg, tp.to_master(crop, p)) for p in frag['lot']]
    check(close_points(lot, [[150.2, depth], [150.2, 0], [0, 0], [0, depth]]),
          ('the street edge lies along y = 0 and the lot behind it', lot))
    check(_same_reg(tb._plot_registration(crop, frag), reg), 'the build delegates to twin_place.plot_registration')
    turned = tp.plot_registration(crop, frag, edge=[0, 1])
    check(_same_reg(turned, _expected_reg(crop, frag, [0, 1])), ('an explicit edge overrides the fragment', turned))
    lot = [tr.apply(turned, tp.to_master(crop, p)) for p in frag['lot']]
    check(close_points(lot, [[depth, 0], [0, 0], [0, 150.2], [depth, 150.2]]), lot)

    for box in ([0, 0, 1, 1], [0.1, 0.2, 0.9, 0.8]):
        cropped = {'box': box, 'master': [W, H]}
        r = tp.plot_registration(cropped, frag)
        m = tp.sheet_matrix(r, cropped)
        check(isinstance(m, list) and len(m) == 6, m)
        for u, v in ((0, 0), (1, 0), (0, 1), (0.3, 0.7), (1, 1)):
            got = [m[0] * u + m[2] * v + m[4], m[1] * u + m[3] * v + m[5]]
            check(close(got, tr.apply(r, [u * W, v * H])),
                  ('the matrix takes full-page uv to world feet', box, (u, v), got))

    items = tp.plot_suggestions(frag, crop, reg)
    check([s['id'] for s in items] == ['plot-1', 'plot-2'], items)
    for item, raw in zip(items, frag['buildings']):
        check(set(item) == SUGGESTION_KEYS, sorted(item))
        px = [tp.to_master(crop, p) for p in raw['outline']]
        world = [tr.apply(reg, p) for p in px]
        check(close_points(item['outline_px'], px) and close_points(item['outline'], world), item)
        b = _bounds(world)
        check(close(item['size_ft'], [b[2] - b[0], b[3] - b[1]], 1e-6), ('w across, d back', item['size_ft']))
        check(item['name'] == raw['name'] and item['state'] == 'open' and item['building'] is None, item)
    # The fixture's house stands near the street; its pool house at the back left.
    check('front' in items[0]['where'], items[0]['where'])
    check('left' in items[1]['where'] and 'front' not in items[1]['where'], items[1]['where'])

    placed = copy.deepcopy(frag)
    placed['buildings'] = [
        {'name': 'a', 'outline': [_uv(reg, p) for p in [[10, 10], [30, 10], [30, 30], [10, 30]]]},
        {'name': 'b', 'outline': [_uv(reg, p) for p in [[120, 10], [140, 10], [140, 30], [120, 30]]]}]
    where = [s['where'] for s in tp.plot_suggestions(placed, crop, reg)]
    check(where == ['at the front left', 'at the front right'], where)


# --- the plot read -----------------------------------------------------------

def scenario_plot_read_needs_plot_page():
    _fresh()
    house = ts.save_source('drawing', 'house.pdf', _pdf(1))
    plot = ts.save_source('drawing', 'plot.pdf', _pdf(1), part='lot')
    ts.set_page_roles([
        {'source': house, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None, 'building': 'house'},
        {'source': plot, 'page': 1, 'role': 'survey', 'level': None, 'box': None, 'building': 'lot'}])
    reader = PlotReader()
    expect_value_error(lambda: tpr.read_plot(reader=reader), NO_PLOT)
    check(reader.calls == [] and tc.entries() == [], 'nothing is read or paid for')
    check(_read() is None, _lot())


def scenario_plot_read_stores_suggestions():
    house, plot = _setup()
    reader = PlotReader()
    result = tpr.read_plot(reader=reader)
    check(isinstance(result, dict), result)
    check([(c['kind'], c['run'], c['step'], c['images']) for c in reader.calls] == [('plot', 'place', 'plot', 1)],
          ('one plot read, run place, step plot, one image', reader.calls))
    read = _read()
    check(read is not None and READ_KEYS <= set(read), sorted(read or {}))
    check(isinstance(read['id'], str) and len(read['id']) == 32 and int(read['id'], 16) >= 0, read['id'])
    check(read['source'] == plot and read['page'] == 1 and read['box'] in (None, [0, 0, 1, 1]),
          (read['source'], read['page'], read['box']))
    crop = read['crop']
    check(crop['box'] == [0, 0, 1, 1] and crop['master'] == [W, H], ('a full crop of the master', crop))
    frag = read['fragment']
    check(frag['lot'] == fixture('plot')['lot'] and frag['scale'] == fixture('plot')['scale'], frag)
    reg = read['registration']
    check(_same_reg(reg, _expected_reg(crop, fixture('plot'))), reg)
    check(read['street_edge'] == [1, 2], ('from the fixture', read['street_edge']))
    check(close_points(read['lot'], [tr.apply(reg, tp.to_master(crop, p)) for p in frag['lot']]), read['lot'])
    check(close(read['matrix'], tp.sheet_matrix(reg, crop), 1e-9), read['matrix'])
    items = read['suggestions']
    check([s['id'] for s in items] == ['plot-1', 'plot-2'] and all(s['state'] == 'open' for s in items), items)
    for item, raw in zip(items, fixture('plot')['buildings']):
        want = [tr.apply(reg, tp.to_master(crop, p)) for p in raw['outline']]
        check(close_points(item['outline'], want, 1e-6), (item['id'], item['outline'], want))
        check(item['name'] == raw['name'] and item['building'] is None, item)
    ledger = [e for e in tc.entries() if e['run'] == 'place' and e['stage'] == 'step:plot']
    check(len(ledger) == 1, tc.entries())
    check(read['cost'] > 0 and abs(read['cost'] - ledger[0]['usd']) < 1e-9, (read['cost'], ledger))
    check(ts.current() is None, 'a read changes no plan')
    check(all(b['footprint'] is None for b in ts.place()['buildings']), 'nothing is accepted by itself')


def scenario_plot_read_clears_only_an_unconfirmed_placement():
    house, plot = _setup()
    tpr.read_plot(reader=PlotReader())
    lot = _lot()
    loose = {'source': plot, 'page': 1, 'box': None, 'outline': lot['read']['lot'], 'street_edge': [1, 2],
             'registration': lot['read']['registration'], 'confirmed': False}
    ts.set_lot({**lot, 'placement': loose})
    tpr.read_plot(reader=PlotReader())
    check(_lot()['placement'] is None, ('a new read clears an unconfirmed placement', _lot()['placement']))
    tpr.confirm_placement(None, [])
    tpr.read_plot(reader=PlotReader())
    check(_lot()['placement'] and _lot()['placement']['confirmed'] is True,
          ('a confirmed placement survives a new read', _lot()['placement']))


def scenario_refused_read_costs_nothing_and_raises():
    house, plot = _setup()
    reader = PlotReader(answer={'error': 'refused'}, usage=False)
    expect_value_error(lambda: tpr.read_plot(reader=reader), READ_FAILED)
    check(len(reader.calls) == 1 and tc.entries() == [], ('one refused request, nothing paid', tc.entries()))
    check(_read() is None, ('no suggestion is recorded', _lot()))
    unusable = fixture('plot')
    del unusable['lot']
    expect_value_error(lambda: tpr.read_plot(reader=PlotReader(answer=unusable, usage=False)), READ_FAILED)
    check(_read() is None, ('an answer without a lot is unusable', _lot()))


def scenario_stale_plot_read_discarded():
    # A4: the plot page's role changes while the reader runs.
    house, plot = _setup()
    rows = ts.page_roles()
    reader = PlotReader(during=lambda: ts.set_page_roles(_with_role(rows, plot, 'survey')))
    expect_value_error(lambda: tpr.read_plot(reader=reader), CHANGED)
    check(_read() is None, ('the stale answer is discarded', _lot()))
    check(len([e for e in tc.entries() if e['run'] == 'place']) == 1, ('the cost stays in the ledger', tc.entries()))


def scenario_plot_read_discarded_after_start_over():
    # The generation guard: a start over while the reader runs.
    house, plot = _setup()
    reader = PlotReader(during=ts.start_over)
    expect_value_error(lambda: tpr.read_plot(reader=reader), CHANGED)
    check(ts.place() == tp.empty_place(), ('nothing lands in the new house', ts.place()))


# --- suggestions -------------------------------------------------------------

def scenario_accept_new_and_match_and_dismiss():
    house, plot = _setup()
    tpr.read_plot(reader=PlotReader())
    one, two = _suggestion('plot-1'), _suggestion('plot-2')
    result = tpr.answer_suggestion('plot-1', 'accept', name='Shed', kind='shed')
    check(isinstance(result, dict), result)
    shed = _building('shed')
    check(shed is not None and shed['name'] == 'Shed' and shed['kind'] == 'shed', ts.place()['buildings'])
    check(shed['footprint_from'] == 'plot' and close_points(shed['footprint'], one['outline']), shed)
    check(_suggestion('plot-1')['state'] == 'accepted' and _suggestion('plot-1')['building'] == 'shed',
          _suggestion('plot-1'))
    tpr.answer_suggestion('plot-2', 'accept', building='house')
    main = _building('house')
    check(main['footprint_from'] == 'plot' and close_points(main['footprint'], two['outline']), main)
    check(_suggestion('plot-2')['state'] == 'accepted' and _suggestion('plot-2')['building'] == 'house',
          _suggestion('plot-2'))
    check(len(ts.place()['buildings']) == 2, 'matching creates no building')
    for sid in ('plot-1', 'plot-2'):
        expect_value_error(lambda: tpr.answer_suggestion(sid, 'dismiss'), ANSWERED)
    expect_value_error(lambda: tpr.answer_suggestion('plot-9', 'dismiss'))
    expect_value_error(lambda: tpr.answer_suggestion('plot-1', 'maybe'))

    tpr.read_plot(reader=PlotReader())
    check(all(s['state'] == 'open' for s in _read()['suggestions']), 'a new read offers fresh suggestions')
    expect_value_error(lambda: tpr.answer_suggestion('plot-1', 'accept', building='nope'))
    expect_value_error(lambda: tpr.answer_suggestion('plot-1', 'accept', name='Folly', kind='castle'))
    check(_suggestion('plot-1')['state'] == 'open', 'a refused accept answers nothing')
    tpr.answer_suggestion('plot-1', 'dismiss')
    check(_suggestion('plot-1')['state'] == 'dismissed', _suggestion('plot-1'))
    check(_suggestion('plot-1')['state'] == 'dismissed', 'still dismissed when the place is read again')
    expect_value_error(lambda: tpr.answer_suggestion('plot-1', 'accept', name='Barn', kind='barn'), ANSWERED)
    check(_building('barn') is None, 'a dismissed suggestion is never accepted later')


def scenario_answer_with_old_read_refused():
    # A4: an answer names the read it was made against.
    house, plot = _setup()
    tpr.read_plot(reader=PlotReader())
    first = _read()['id']
    tpr.read_plot(reader=PlotReader())
    second = _read()['id']
    check(first != second, 'each read has its own id')
    expect_value_error(lambda: tpr.answer_suggestion('plot-1', 'dismiss', read=first), OUT_OF_DATE)
    check(_suggestion('plot-1')['state'] == 'open', 'a stale answer changes nothing')
    tpr.answer_suggestion('plot-1', 'dismiss', read=second)
    check(_suggestion('plot-1')['state'] == 'dismissed', _suggestion('plot-1'))
    tpr.answer_suggestion('plot-2', 'dismiss')
    check(_suggestion('plot-2')['state'] == 'dismissed', 'an answer without a read id still works')


def scenario_accept_fits_built_building():
    target = _moved(RECT40, 100, 50)
    answer = _answer_with([('house', target), ('pool house', _moved(RECT20, 20, 120))])
    house, plot = _setup(_plan())
    tpr.read_plot(reader=PlotReader(answer=answer))
    check(close_points(_suggestion('plot-1')['outline'], target, 1e-6), _suggestion('plot-1')['outline'])
    rounds = len(ts.rounds())
    tpr.answer_suggestion('plot-1', 'accept', building='house')
    placed = _plan_building('house')
    check(close(placed['position'], [100, 50], 0.5) and abs(placed['rotation']) < 0.5,
          ('the built house is fitted onto its footprint at once', placed['position'], placed['rotation']))
    check(len(ts.rounds()) == rounds + 1 and ts.rounds()[-1]['kind'] == 'edit', ts.rounds()[-1])
    # A person placed the pool house: its footprint is saved, the building stays.
    tpr.answer_suggestion('plot-2', 'accept', building='pool_house')
    check(close(_plan_building('pool_house')['position'], [0, 0], 1e-9), _plan_building('pool_house'))
    check(close_points(_building('pool_house')['footprint'], _moved(RECT20, 20, 120), 1e-6),
          _building('pool_house'))

    house, plot = _setup(_plan(house_person=True))
    tpr.read_plot(reader=PlotReader(answer=answer))
    tpr.answer_suggestion('plot-1', 'accept', building='house')
    placed = _plan_building('house')
    check(close(placed['position'], [0, 0], 1e-9) and placed['rotation'] == 0,
          ('a house a person placed is never moved', placed['position']))
    check(close_points(_building('house')['footprint'], target, 1e-6), 'its footprint is still saved')


# --- the lot placement -------------------------------------------------------

def scenario_confirm_placement_and_street_edge():
    house, plot = _setup()
    tpr.read_plot(reader=PlotReader())
    tpr.answer_suggestion('plot-1', 'accept', name='Shed', kind='shed')
    tpr.answer_suggestion('plot-2', 'accept', building='house')
    before = _read()
    old_reg = before['registration']
    old = {bid: _building(bid)['footprint'] for bid in ('shed', 'house')}
    result = tpr.confirm_placement([0, 1], [])
    check(isinstance(result, dict), result)
    placement = _lot()['placement']
    check(placement is not None and PLACEMENT_KEYS <= set(placement), placement)
    check(placement['confirmed'] is True and placement['source'] == plot and placement['page'] == 1
          and placement['street_edge'] == [0, 1], placement)
    new_reg = placement['registration']
    check(not _same_reg(new_reg, old_reg), 'a new street edge changes the registration')
    check(_same_reg(new_reg, _expected_reg(before['crop'], fixture('plot'), [0, 1])), new_reg)
    check(abs(_area(placement['outline']) - _area(before['lot'])) < 1e-6,
          ('the lot keeps its area', _area(placement['outline']), _area(before['lot'])))
    check(min(p[1] for p in placement['outline']) > -1e-6, ('the lot lies behind the new street', placement))
    for bid, footprint in old.items():
        want = [tr.apply(new_reg, tr.invert(old_reg, p)) for p in footprint]
        check(close_points(_building(bid)['footprint'], want, 1e-6),
              ('accepted footprints move with the lot', bid, _building(bid)['footprint'], want))
    check(ts.registration(plot, 1, None) == new_reg, ('the site read uses the saved registration',
                                                     ts.registration(plot, 1, None), new_reg))

    dragged = _moved(RECT20, 30, 40)
    tpr.confirm_placement(None, [{'building': 'shed', 'outline': dragged}])
    check(close_points(_building('shed')['footprint'], dragged, 1e-9), _building('shed'))
    check(_lot()['placement']['street_edge'] == [0, 1] and _same_reg(_lot()['placement']['registration'], new_reg),
          'no street edge keeps the registration')
    expect_value_error(lambda: tpr.confirm_placement(None, [{'building': 'shed', 'outline': BOW_TIE}]), CROSS)
    check(close_points(_building('shed')['footprint'], dragged, 1e-9), 'a refused footprint changes nothing')
    expect_value_error(lambda: tpr.confirm_placement(None, [{'building': 'nope', 'outline': RECT20}]))


def scenario_confirm_refits_built_building():
    # A5: a placement applies to buildings already built, skipping src.person.
    answer = _answer_with([('house', _moved(RECT40, 100, 50)), ('pool house', _moved(RECT20, 20, 120))])
    house, plot = _setup(_plan())
    tpr.read_plot(reader=PlotReader(answer=answer))
    tpr.answer_suggestion('plot-1', 'accept', building='house')
    tpr.answer_suggestion('plot-2', 'accept', building='pool_house')
    rounds = len(ts.rounds())
    tpr.confirm_placement([0, 1], [])
    check(len(ts.rounds()) == rounds + 1 and ts.rounds()[-1]['kind'] == 'edit',
          ('one round refits the house', ts.rounds()[rounds:]))
    footprint = _building('house')['footprint']
    placed = _plan_building('house')
    check(not close(placed['position'], [100, 50], 0.5), ('the house moved with the new street edge', placed))
    check(_fits(placed, RECT40, footprint), ('the house sits on its reprojected footprint', placed, footprint))
    check(close(_plan_building('pool_house')['position'], [0, 0], 1e-9) and _plan_building('pool_house')['rotation'] == 0,
          ('a building a person placed is skipped', _plan_building('pool_house')))

    dragged = _moved(RECT40, 60, 90)
    tpr.confirm_placement(None, [{'building': 'house', 'outline': dragged},
                                 {'building': 'pool_house', 'outline': _moved(RECT20, 5, 5)}])
    placed = _plan_building('house')
    check(_fits(placed, RECT40, dragged), ('a dragged footprint refits the house', placed))
    check(close(_plan_building('pool_house')['position'], [0, 0], 1e-9), _plan_building('pool_house'))
    check(close_points(_building('pool_house')['footprint'], _moved(RECT20, 5, 5), 1e-9), 'its footprint is saved')


def scenario_plot_read_cleared_when_page_changes():
    house, plot = _setup()
    tpr.read_plot(reader=PlotReader())
    lot = _lot()
    loose = {'source': plot, 'page': 1, 'box': None, 'outline': lot['read']['lot'], 'street_edge': [1, 2],
             'registration': lot['read']['registration'], 'confirmed': False}
    ts.set_lot({**lot, 'placement': loose})
    ts.set_page_roles(ts.page_roles())
    check(_read() is not None and _lot()['placement'] == loose, 'saving the same roles keeps the read')
    rows = ts.page_roles()
    ts.set_page_roles(_with_role(rows, plot, 'survey'))
    check(_read() is None, ('a plot page turned survey clears the read', _lot()))
    check(_lot()['placement'] is None, ('and leaves no unconfirmed placement', _lot()['placement']))

    ts.set_page_roles(rows)
    tpr.read_plot(reader=PlotReader())
    tpr.confirm_placement(None, [])
    confirmed = _lot()['placement']
    ts.set_page_roles(_with_role(rows, plot, 'survey'))
    check(_read() is None and _lot()['placement'] == confirmed,
          ('a confirmed placement stays; only the read clears', _lot()))

    ts.set_page_roles(rows)
    tpr.read_plot(reader=PlotReader())
    ts.move_page(plot, 1, 'house')
    check(_read() is None and _lot()['placement'] == confirmed,
          ('moving the plot page off the lot clears the read', _lot()))


# --- photo suggestions -------------------------------------------------------

def _photo_setup():
    _fresh()
    house = ts.save_source('drawing', 'house.pdf', _pdf(1))       # no part: Main house
    ts.set_page_roles([{'source': house, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None,
                        'building': 'house'}])
    ts.add_building('Shed', 'shed')
    return house


def scenario_photo_suggestions():
    _photo_setup()
    photo = ts.save_source('photo', 'side.png', _photo(), part='lot')
    shed_before = copy.deepcopy(_building('shed'))
    tags_before = copy.deepcopy(ts.place()['photo_tags'])
    reader = PhotoReader()
    result = tpr.suggest_photos(reader=reader)
    check(isinstance(result, dict), result)
    check(len(reader.calls) == 1 and reader.calls[0]['kind'] == 'photo_parts' and len(reader.calls[0]['sizes']) == 1,
          reader.calls)
    parts = reader.calls[0]['context']['parts']
    by_id = {p['id']: p for p in parts}
    check({'house', 'shed', 'lot'} <= set(by_id), ('every part of the place is offered', parts))
    for bid in ('house', 'shed'):
        check(set(by_id[bid]) == {'id', 'name', 'kind', 'has_drawings'}, by_id[bid])
    check(by_id['house']['has_drawings'] is True and by_id['shed']['has_drawings'] is False, parts)
    check(by_id['shed']['name'] == 'Shed' and by_id['shed']['kind'] == 'shed', by_id['shed'])
    read = ts.place()['photo_read']
    check(read['photos'][0] == {'source': photo, 'parts': ['house', 'lot']}, read['photos'])
    shell = read['shells'][0]
    check({k: shell.get(k) for k in PHOTO_ANSWER['shells'][0]} == PHOTO_ANSWER['shells'][0], read['shells'])
    check(read['cost'] > 0 and any(e['stage'] == 'step:photo_parts' for e in tc.entries()), (read, tc.entries()))
    check(_building('shed') == shed_before, ('the shed shell is never applied by itself', _building('shed')))
    check(ts.place()['photo_tags'] == tags_before, ('tags are never changed by themselves', ts.place()['photo_tags']))

    unknown = {'photos': [{'index': 0, 'parts': ['house', 'nope']}], 'shells': []}
    tpr.suggest_photos(reader=PhotoReader(unknown))
    check(ts.place()['photo_read']['photos'][0]['parts'] == ['house'], ('an unknown part is dropped',
                                                                       ts.place()['photo_read']))


def scenario_photo_suggestions_limit_and_thumbnails():
    _photo_setup()
    first = ts.save_source('photo', 'big.png', _photo(1600, 1200), part='lot')
    for i in range(12):
        ts.save_source('photo', f'p{i}.png', _photo(), part='lot')
    reader = PhotoReader({'photos': [{'index': 0, 'parts': ['lot']}], 'shells': []})
    tpr.suggest_photos(reader=reader)
    sizes = reader.calls[0]['sizes']
    check(len(sizes) == 12, ('at most 12 photos are read', len(sizes)))
    check(max(sizes[0]) == 768, ('the earliest upload comes first, cut to a 768 px thumbnail', sizes[0]))
    check(all(max(s) <= 768 for s in sizes), sizes)
    check(ts.place()['photo_read']['photos'][0]['source'] == first, ts.place()['photo_read']['photos'])


def scenario_photo_parts_parse_checks_shapes_only():
    # A6: parse keeps two arguments and checks shapes and shell ranges only.
    check('photo_parts' in twin_reads.KINDS and twin_reads.MAX_OUTPUT['photo_parts'] == 2048, twin_reads.MAX_OUTPUT)
    frag, problems = twin_reads.parse('photo_parts', fixture('photo_parts'))
    check(problems == [] and frag == fixture('photo_parts'), ('a clean answer passes through', frag, problems))
    good = {'building': 'shed', 'storeys': 1, 'roof': 'gable', 'pitch': 6, 'confidence': 0.5, 'why': ''}
    frag, problems = twin_reads.parse('photo_parts', {
        'photos': [{'index': 0, 'parts': ['house', 'lot']}, {'index': -1, 'parts': ['lot']},
                   {'index': 'x', 'parts': ['lot']}, {'index': 7, 'parts': ['anything']}],
        'shells': [good, {**good, 'building': 'barn', 'storeys': 9}, {**good, 'building': 'barn', 'roof': 'dome'},
                   {**good, 'building': 'barn', 'pitch': 30}]})
    check([p['index'] for p in frag['photos']] == [0, 7], ('shapes only: index 7 waits for the context', frag))
    check(frag['photos'][1]['parts'] == ['anything'], 'parts are checked against the context later')
    check(len(frag['shells']) == 1 and frag['shells'][0]['building'] == 'shed', frag['shells'])
    check(len(problems) >= 5, problems)


def scenario_photo_parts_unknown_index_and_part_dropped_real_reader():
    # A6: through the real twin_reads.read, with call_pool_json stubbed.
    _photo_setup()
    photo = ts.save_source('photo', 'side.png', _photo(), part='lot')
    saved = {k: storage.get_settings().get(k) for k in ('llm_provider', 'llm_gemini_paid_api_key')}
    storage.patch_settings({'llm_provider': 'gemini', 'llm_gemini_paid_api_key': 'paid-k'})
    answer = {'photos': [{'index': 0, 'parts': ['house', 'nope', 'lot']}, {'index': 3, 'parts': ['house']}],
              'shells': [{'building': 'ghost', 'storeys': 1, 'roof': 'gable', 'pitch': 6, 'confidence': 0.5,
                          'why': ''},
                         {'building': 'shed', 'storeys': 2, 'roof': 'hip', 'pitch': 5, 'confidence': 0.6,
                          'why': 'two rows of windows'}]}
    try:
        with Pool(answer) as pool:
            tpr.suggest_photos()
    finally:
        storage.patch_settings(saved)
    check(len(pool.calls) == 1 and pool.calls[0]['tier'] == 'twin' and pool.calls[0]['max_output_tokens'] == 2048
          and len(pool.calls[0]['images']) == 1, pool.calls)
    read = ts.place()['photo_read']
    check(read['photos'] == [{'source': photo, 'parts': ['house', 'lot']}],
          ('an index it did not send and a part it did not offer are dropped', read['photos']))
    check([s['building'] for s in read['shells']] == ['shed'], ('an unknown building is dropped', read['shells']))
    entry = [e for e in tc.entries() if e['stage'] == 'step:photo_parts']
    check(len(entry) == 1 and abs(read['cost'] - entry[0]['usd']) < 1e-9, (read['cost'], entry))


# --- placement regression checks --------------------------------------------

def scenario_confirm_edge_then_accept():
    _setup()
    tpr.read_plot(reader=PlotReader())
    tpr.confirm_placement([0, 1], [])
    tpr.answer_suggestion('plot-1', 'accept', name='Shed', kind='shed')

    def check_frame():
        read, placement = _read(), _lot()['placement']
        reg, crop = placement['registration'], read['crop']
        check(_same_reg(read['registration'], reg), 'read and placement share the registration')
        check(read['street_edge'] == placement['street_edge'] == [0, 1], read['street_edge'])
        check(close_points(read['lot'], placement['outline']), 'the lot shares the placement frame')
        for suggestion, raw in zip(read['suggestions'], fixture('plot')['buildings']):
            want = [tr.apply(reg, tp.to_master(crop, p)) for p in raw['outline']]
            check(close_points(suggestion['outline'], want), (suggestion, want))
        want = [tr.apply(reg, tp.to_master(crop, p)) for p in fixture('plot')['buildings'][0]['outline']]
        check(close_points(_building('shed')['footprint'], want), (_building('shed'), want))
        a, b, c, d, e, f = read['matrix']
        for u, v in ([0, 0], [1, 0], [0, 1], [.3, .7]):
            check(close([a*u + c*v + e, b*u + d*v + f], tr.apply(reg, [u*W, v*H])),
                  'the sheet matrix shares the placement frame')

    check_frame()
    # A reread on this page must keep the person's edge as well.
    tpr.read_plot(reader=PlotReader())
    check_frame()
    tpr.answer_suggestion('plot-2', 'accept', building='house')
    check(close_points(_building('house')['footprint'], _suggestion('plot-2')['outline']),
          'a suggestion accepted after rereading uses the confirmed frame')


def scenario_dragged_footprint_moves_and_refits_in_one_save():
    _, plot = _setup(_plan())
    tpr.read_plot(reader=PlotReader())
    dragged = _moved(RECT40, 60, 90)
    saved = []
    original = ts._save

    def capture(row):
        saved.append(copy.deepcopy(row))
        return original(row)

    ts._save = capture
    try:
        rounds_before = len(ts.rounds())
        tpr.confirm_placement(None, [{'building': 'house', 'outline': dragged}])
        check(_building('house')['footprint_from'] == 'plot', _building('house'))
        check(len(saved) == 1 and len(ts.rounds()) == rounds_before + 1, 'drag refit saves once in one round')
        check(_fits(_plan_building('house'), RECT40, dragged), 'the drag refits the built house')
        old_reg = _lot()['placement']['registration']
        saved.clear()
        tpr.confirm_placement([0, 1], [])
        reg = _lot()['placement']['registration']
        want = [tr.apply(reg, tr.invert(old_reg, p)) for p in dragged]
        check(close_points(_building('house')['footprint'], want), 'the dragged footprint moves with the lot')
        check(_fits(_plan_building('house'), RECT40, want), 'the built house follows its footprint')
        check(len(saved) == 1 and len(ts.rounds()) == rounds_before + 2, 'edge refit saves once in one round')
        row = saved[0]
        check(row['place'] == ts.place(), 'the round save already contains the new place')
        check(any(r['source'] == plot and r['reg'] == reg for r in row['registrations']),
              'the round save already contains the build registration')
        saved.clear()
        tpr.answer_suggestion('plot-1', 'accept', building='house')
        check(len(saved) == 1 and len(ts.rounds()) == rounds_before + 3, 'accept refit saves once in one round')
        check(saved[0]['place'] == ts.place(), 'the accept round save already contains the footprint')
    finally:
        ts._save = original


def scenario_plot_registration_preserves_fragment_edge():
    frag = fixture('plot')
    frag['street_edge'] = [0, 2]
    check(_same_reg(tp.plot_registration(FULL_CROP, frag), _expected_reg(FULL_CROP, frag)),
          'a non-adjacent fragment edge retains the legacy registration')
    expect_value_error(lambda: tp.plot_registration(FULL_CROP, frag, edge=[0, 2]),
                       'Choose two neighbouring lot corners for the street edge.')
    # A concave lot whose area centroid and vertex mean lie on opposite sides of the street.
    frag['lot'] = [[0, 0], [.2, 0], [.4, 0], [.6, 0], [.8, 0], [1, 0],
                   [1, .2], [.3, .2], [.3, 1], [0, 1]]
    frag['street_edge'] = [0, 7]
    check(_same_reg(tp.plot_registration(FULL_CROP, frag), _expected_reg(FULL_CROP, frag)),
          'the legacy area centroid decides which side holds the lot')


# --- estimates ---------------------------------------------------------------

def scenario_estimate():
    saved = storage.get_settings().get('model_pool_pro')
    try:
        storage.patch_settings({'model_pool_pro': OPUS})
        # (1500 + 1600) * 4 + 8192 * 20 = 176240 per million: $0.17624, up to the cent.
        check(abs(tc.estimate('plot', 1) - 0.18) < 1e-9, tc.estimate('plot', 1))
        check(tc.estimate('plot', 1) > 0, 'a plot read costs something')
        # (1500 + 1600 * 12) * 4 + 2048 * 20 = 123760: $0.13; one photo $0.06.
        check(abs(tc.estimate('photo_parts', 12) - 0.13) < 1e-9, tc.estimate('photo_parts', 12))
        check(abs(tc.estimate('photo_parts', 1) - 0.06) < 1e-9, tc.estimate('photo_parts', 1))
        check(tc.estimate('photo_parts', 12) > tc.estimate('photo_parts', 1), '12 photos cost more than 1')
        storage.patch_settings({'model_pool_pro': 'mystery-model'})
        # The highest rates: 3100 * 10 + 8192 * 60 = 522520: $0.53.
        check(abs(tc.estimate('plot', 1) - 0.53) < 1e-9, tc.estimate('plot', 1))
        inp, out = tc._highest_rates()
        want = math.ceil(((1500 + 1600 * 12) * inp + 2048 * out) / 1_000_000 * 100 - 1e-9) / 100
        check(abs(tc.estimate('photo_parts', 12) - want) < 1e-9, (tc.estimate('photo_parts', 12), want))
    finally:
        storage.patch_settings({'model_pool_pro': saved})


def scenario_reread_matches_confirmed_street_by_master_geometry():
    _setup(_plan())
    # A crop makes normalized image coordinates differ from master pixels.
    rows = ts.page_roles()
    next(r for r in rows if r['role'] == 'plot')['box'] = [.1, .15, .9, .85]
    ts.set_page_roles(rows)
    tpr.read_plot(reader=PlotReader())
    tpr.confirm_placement([0, 1], [])
    old = copy.deepcopy(_lot()['placement'])
    answer = fixture('plot')
    answer['lot'] = answer['lot'][1:] + answer['lot'][:1]
    answer['street_edge'] = [1, 2]  # Deliberately points at a different physical edge.
    tpr.read_plot(reader=PlotReader(answer))
    read = _read()
    got = [tp.to_master(read['crop'], answer['lot'][i]) for i in read['street_edge']]
    want = [tr.invert(old['registration'], old['outline'][i]) for i in old['street_edge']]
    check(close_points(got, want), (got, want, read['street_edge']))
    tpr.confirm_placement(None, [])
    check(_same_reg(_lot()['placement']['registration'], read['registration']), _lot())


def scenario_confirm_reprojects_on_registration_change_with_same_indices():
    _setup(_plan())
    tpr.read_plot(reader=PlotReader())
    suggestion = _read()['suggestions'][0]
    tpr.answer_suggestion(suggestion['id'], 'accept', building='house')
    tpr.confirm_placement(None, [])
    old = copy.deepcopy(_lot()['placement'])
    footprint = copy.deepcopy(_building('house')['footprint'])
    answer = fixture('plot')
    answer['scale']['feet'] *= 1.25
    tpr.read_plot(reader=PlotReader(answer))
    read = copy.deepcopy(_read())
    check(read['street_edge'] == old['street_edge'], (read, old))
    expected = [tr.apply(read['registration'], tr.invert(old['registration'], p)) for p in footprint]
    tpr.confirm_placement(read['street_edge'], [])
    check(close_points(_building('house')['footprint'], expected), (_building('house'), expected))
    house = next(b for b in ts.current()['buildings'] if b['id'] == 'house')
    outline = min(house['levels'], key=lambda l: l['elevation'])['outline']
    fit, _ = tr.fit_outline(outline, expected)
    check(close(house['position'], fit['offset']) and abs(house['rotation'] - fit['angle']) < 1e-6,
          (house['position'], house['rotation'], fit))


def scenario_confirmed_nonadjacent_fragment_edge_can_be_read_again():
    _setup()
    answer = fixture('plot')
    answer['street_edge'] = [0, 2]
    tpr.read_plot(reader=PlotReader(answer))
    tpr.confirm_placement(None, [])
    # None and an unchanged edge from the map both accept the reader's edge.
    tpr.confirm_placement([0, 2], [])
    tpr.read_plot(reader=PlotReader(answer))
    tpr.confirm_placement(_read()['street_edge'], [])
    check(_lot()['placement']['confirmed'], _lot())


def scenario_reread_with_fewer_corners_matches_or_falls_back():
    for changed_boundary in (False, True):
        _setup()
        tpr.read_plot(reader=PlotReader())
        tpr.confirm_placement([3, 0], [])
        old = copy.deepcopy(_lot()['placement'])
        answer = fixture('plot')
        answer['lot'] = [answer['lot'][i] for i in (0, 2, 3)]
        answer['street_edge'] = [0, 1]
        if changed_boundary:
            answer['lot'] = [[x + .1, y + .1] for x, y in answer['lot']]
        tpr.read_plot(reader=PlotReader(answer))
        read = _read()
        if changed_boundary:
            check(read['street_edge'] == [0, 1], read)
        else:
            got = [tp.to_master(read['crop'], answer['lot'][i]) for i in read['street_edge']]
            want = [tr.invert(old['registration'], old['outline'][i]) for i in old['street_edge']]
            check(close_points(got, want), (got, want))
        tpr.confirm_placement(None, [])
        check(_lot()['placement']['confirmed'], _lot())


def scenario_photo_drawings_hint_uses_rows_instead_of_stale_source_part():
    _setup()
    shed = ts.add_building('Shed', 'shed')['id']
    sid = next(s['id'] for s in ts.sources() if s.get('part') == 'house')
    ts.move_page(sid, 1, shed)
    mixed = ts.save_source('drawing', 'several-parts.pdf', _pdf(2), part='house')
    ts.set_page_roles([*ts.page_roles(),
                       {'source': mixed, 'page': 1, 'building': shed, 'role': 'other'},
                       {'source': mixed, 'page': 2, 'building': 'lot', 'role': 'other'}])
    check(next(s for s in ts.sources() if s['id'] == mixed)['part'] == 'house', ts.sources())
    ts.save_source('photo', 'yard.png', _photo(), part='lot')
    reader = PhotoReader({'photos': [{'index': 0, 'parts': ['lot']}], 'shells': []})
    tpr.suggest_photos(reader=reader)
    parts = {p['id']: p['has_drawings'] for p in reader.calls[0]['context']['parts']}
    check(parts['house'] is False and parts[shed] is True and parts['lot'] is True, parts)


SCENARIOS = (
    scenario_reread_with_fewer_corners_matches_or_falls_back,
    scenario_reread_matches_confirmed_street_by_master_geometry,
    scenario_confirm_reprojects_on_registration_change_with_same_indices,
    scenario_confirmed_nonadjacent_fragment_edge_can_be_read_again,
    scenario_photo_drawings_hint_uses_rows_instead_of_stale_source_part,
    scenario_confirm_edge_then_accept,
    scenario_dragged_footprint_moves_and_refits_in_one_save,
    scenario_plot_registration_preserves_fragment_edge,
    scenario_plot_math,
    scenario_plot_read_needs_plot_page,
    scenario_plot_read_stores_suggestions,
    scenario_plot_read_clears_only_an_unconfirmed_placement,
    scenario_refused_read_costs_nothing_and_raises,
    scenario_stale_plot_read_discarded,
    scenario_plot_read_discarded_after_start_over,
    scenario_accept_new_and_match_and_dismiss,
    scenario_answer_with_old_read_refused,
    scenario_accept_fits_built_building,
    scenario_confirm_placement_and_street_edge,
    scenario_confirm_refits_built_building,
    scenario_plot_read_cleared_when_page_changes,
    scenario_photo_suggestions,
    scenario_photo_suggestions_limit_and_thumbnails,
    scenario_photo_parts_parse_checks_shapes_only,
    scenario_photo_parts_unknown_index_and_part_dropped_real_reader,
    scenario_estimate,
)


if __name__ == '__main__':
    failed = []
    for fn in SCENARIOS:
        try:
            fn()
        except Exception:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__)
            traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(SCENARIOS) - len(failed)}/{len(SCENARIOS)} passed')
    sys.exit(1 if failed else 0)

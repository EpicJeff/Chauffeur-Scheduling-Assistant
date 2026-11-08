"""Builds of a part (plan .superpowers/sdd/2026-11-07-house-editor-slice-1b-i,
Task 4, with amendments A7-A9): the lot on its own, each building fitted onto
its footprint.

- start({'part': 'lot'}) with a confirmed placement for the lot's current plot
  page runs lot (no read), site and compose; without one (or with a placement
  from another page, A8) it reads the plot, pauses at lot_placement and saves
  a confirmed placement and the read into the place; with no plot page it is
  refused. A lot build never adds a building.
- start({'part': <building id>}) runs slice 1's floor, roof, pitch and
  finishes steps with that building's tagged photos, then fit when there is a
  lot, then compose. fit settles alone on a good match with the footprint and
  pauses otherwise; settling never moves a building a person placed.
- a building part's finishes land on the building (A9), each building keeping
  its own; the legacy body keeps writing plan.materials.
- a paused or crashed lot build survives a restart (A7).
- the legacy body {building, photos} keeps slice 1's exact steps.
- twin_plan.normalize keeps a plan with no buildings when it has a lot.

The reader is test_twin_build's fake, keyed by kind. Sources are blank
17 x 11 inch PDFs (masters 5100 x 3300 px); 70 ft = 0.5 of the page width.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_build_parts.py
"""
import copy
import math
import os
import sys
import tempfile
import time
import traceback

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_build_parts_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import twin_build as tb  # noqa: E402
from services import twin_plan  # noqa: E402
from services import twin_reads  # noqa: E402
from services import twin_register as tr  # noqa: E402
from services import twin_store as ts  # noqa: E402
import test_twin_build as engine_tests  # noqa: E402
from test_twin_build import DIM, Reader, _Crash, _accept_all, _jpeg, _pdf, check, close, fixture  # noqa: E402

W, H = 5100, 3300
FULL_CROP = {'box': [0, 0, 1, 1], 'master': [W, H]}
SCALE = 70.0 / (0.5 * W)
SQUARE = [[0, 0], [100, 0], [100, 100], [0, 100]]
# An L-shaped Main floor outline (crop uv): no turn of it matches itself, so a
# fit onto its turned copy has one answer.
L_UV = [[0.2, 0.1], [0.7, 0.1], [0.7, 0.4], [0.45, 0.4], [0.45, 0.8], [0.2, 0.8]]

NO_PLOT = 'Add a plot plan to the lot first.'
DISAGREE = "The drawings and the plot plan disagree about this building's shape. Check where it sits."
NO_FOOTPRINT = 'This building has no footprint on the lot yet. Drag it into place.'
NO_BUILDING = 'Twin plan must contain at least one usable building.'
SLICE1_IDS = ['outline:L1', 'openings:L1', 'rooms:L1', 'registration:L2', 'openings:L2', 'rooms:L2',
              'roof', 'pitch', 'plot', 'site', 'finishes', 'compose']


# --- fakes and helpers ---------------------------------------------------------

class PartReader(Reader):
    """test_twin_build's fake reader, with an L-shaped outline on request, a plot
    answer that names one building, and finishes coloured per building."""

    def __init__(self, *a, l_outline=False, one_plot_building=False, sidings=None, **kw):
        super().__init__(*a, **kw)
        self.l_outline = l_outline
        self.one_plot_building = one_plot_building
        self.sidings = sidings or {}

    def __call__(self, kind, images, context, *, run, step):
        if kind == 'outline' and self.l_outline:
            self.calls.append({'kind': kind, 'step': step, 'context': copy.deepcopy(context), 'images': len(images)})
            return {'dimension': DIM, 'outline': copy.deepcopy(L_UV), 'confidence': 0.8, 'why': '',
                    'wings': [{'name': 'main', 'box': [0.2, 0.1, 0.7, 0.8]}]}
        if kind == 'plot' and self.one_plot_building:
            self.calls.append({'kind': kind, 'step': step, 'context': copy.deepcopy(context), 'images': len(images)})
            answer = fixture('plot')
            answer['buildings'] = answer['buildings'][:1]
            return answer
        if kind == 'finishes' and self.sidings:
            self.calls.append({'kind': kind, 'step': step, 'context': copy.deepcopy(context), 'images': len(images)})
            bid = (context.get('building') or {}).get('id')
            return {'materials': {'siding': {'id': 'board_and_batten', 'color': self.sidings[bid]}}}
        return super().__call__(kind, images, context, run=run, step=step)


def _kinds(b):
    return [s['kind'] for s in tb.status(b)['steps']]


def _read_kinds(reader):
    return [c['kind'] for c in reader.calls]


def _house(plan, bid='house'):
    return next(b for b in plan['buildings'] if b['id'] == bid)


def _px(uv):
    return [uv[0] * W, uv[1] * H]


def _plot_reg():
    """The plot fixture's registration on a full crop, as the build computes it."""
    return tb._plot_registration(FULL_CROP, fixture('plot'))


def _plot_lot(reg):
    return [tr.apply(reg, _px(p)) for p in fixture('plot')['lot']]


def _confirm_lot(plot, page=1, box=None):
    """What a confirmed placement looks like after Task 3's confirm_placement:
    the placement record in the place and the plot page's registration."""
    reg = _plot_reg()
    placement = {'source': plot, 'page': page, 'box': box, 'outline': _plot_lot(reg),
                 'street_edge': [1, 2], 'registration': reg, 'confirmed': True}
    ts.set_lot({'placement': placement, 'read': None})
    ts.set_registration(plot, page, None, reg)
    return placement


def _l_local():
    """The L-shaped Main floor outline in building feet, as the outline step
    settles it on accept: scale from the 70 ft dimension, origin at the
    outline's lowest-left pixel, sheet y flipped."""
    pixels = [_px(p) for p in L_UV]
    ox, oy = min(p[0] for p in pixels), max(p[1] for p in pixels)
    return [[(x - ox) * SCALE, (oy - y) * SCALE] for x, y in pixels]


def _lot_only():
    """A place with only a plot drawing on the lot."""
    engine_tests._fresh()
    plot = ts.save_source('drawing', 'plot.pdf', _pdf(1), part='lot')
    ts.set_page_roles([{'source': plot, 'page': 1, 'role': 'plot', 'level': None, 'box': None, 'building': 'lot'}])
    return plot


def _house_place(*, roof=True, plot=True, photos=True):
    """Main house drawings (one floor, a roof), a plot page on the lot, one photo
    tagged to the house and one tagged to the lot."""
    engine_tests._fresh()
    sheets = ts.save_source('drawing', 'house.pdf', _pdf(2))          # legacy upload: Main house, id house
    rows = [{'source': sheets, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None, 'building': 'house'}]
    if roof:
        rows.append({'source': sheets, 'page': 2, 'role': 'roof', 'level': None, 'box': None, 'building': 'house'})
    plot_source = None
    if plot:
        plot_source = ts.save_source('drawing', 'plot.pdf', _pdf(1), part='lot')
        rows.append({'source': plot_source, 'page': 1, 'role': 'plot', 'level': None, 'box': None, 'building': 'lot'})
    ts.set_page_roles(rows)
    found = {}
    if photos:
        found['house'] = ts.save_source('photo', 'front.jpg', _jpeg(), part='house')
        found['lot'] = ts.save_source('photo', 'yard.jpg', _jpeg(), part='lot')
    return sheets, plot_source, found


def _run_to_pause(b, kind, limit=20):
    """Accept every pause until the build pauses at a step of this kind."""
    for _ in range(limit):
        st = tb.status(b)
        if st['state'] != 'paused':
            return st
        step = next(s for s in st['steps'] if s['id'] == st['pause']['step'])
        if step['kind'] == kind:
            return st
        tb.answer(b, st['pause']['step'], {'accept': True})
    raise AssertionError('too many pauses')


def _pause_kinds(b, limit=20):
    """Accept every pause to the end, returning the step kind of each pause."""
    seen = []
    for _ in range(limit):
        st = tb.status(b)
        if st['state'] != 'paused':
            return seen, st
        seen.append(next(s['kind'] for s in st['steps'] if s['id'] == st['pause']['step']))
        tb.answer(b, st['pause']['step'], {'accept': True})
    raise AssertionError('too many pauses')


def _wait(b, seconds=20):
    deadline = time.time() + seconds
    while time.time() < deadline:
        st = tb.status(b)
        if st['state'] != 'running':
            return st
        time.sleep(0.05)
    raise AssertionError('the build never left running')


def _turn_gap(a, b):
    return abs((a - b + 180) % 360 - 180)


def _expect_value_error(fn, message):
    try:
        fn()
    except ValueError as exc:
        check(str(exc) == message, (str(exc), message))
        return
    raise AssertionError(f'expected ValueError {message!r}')


# --- the lot -------------------------------------------------------------------

def scenario_lot_build_confirmed_placement():
    plot = _lot_only()
    placement = _confirm_lot(plot)
    reader = Reader()
    b = tb.start({'part': 'lot'}, reader=reader, inline=True)
    st = tb.status(b)
    check(st['state'] == 'done', (st['state'], st.get('pause'), [e for e in st['events'] if e['type'] in ('error', 'question')][-3:]))
    check(st.get('part') == 'lot' and 'next' in st and st['next'] is None, {k: st.get(k) for k in ('part', 'next')})
    check(_kinds(b) == ['lot', 'site', 'compose'], _kinds(b))
    plan = ts.current()
    check(plan['buildings'] == [], ('a lot build never adds a building', plan['buildings']))
    lot = plan['site']['lot']
    check(len(lot) == len(placement['outline']) and all(close(a, b_, 1e-6) for a, b_ in zip(lot, placement['outline'])),
          (lot, placement['outline']))
    check(_read_kinds(reader) == ['site'], ('only the yard is read', _read_kinds(reader)))
    check(reader.calls[0]['images'] == 1, ('the site read sees the plot page (A7)', reader.calls[0]['images']))
    reg = placement['registration']
    want = [tr.apply(reg, _px(p)) for p in fixture('site')['pool']['polygon']]
    got = (plan['site'].get('pool') or {}).get('polygon') or []
    check(len(got) == len(want) and all(close(a, b_, 1e-3) for a, b_ in zip(got, want)),
          ('the yard sits on the saved plot registration', got, want))


def scenario_lot_build_reads_plot_when_unconfirmed():
    plot = _lot_only()
    reader = PartReader(one_plot_building=True)
    b = tb.start({'part': 'lot'}, reader=reader, inline=True)
    st = tb.status(b)
    check(st['state'] == 'paused' and st['pause']['step'] == 'plot' and st['pause']['kind'] == 'lot_placement',
          (st['state'], st.get('pause')))
    check(st.get('part') == 'lot', st.get('part'))
    check(_kinds(b) == ['plot', 'site', 'compose'], _kinds(b))
    tb.answer(b, 'plot', {'accept': True})
    st = tb.status(b)
    check(st['state'] == 'done', (st['state'], [e for e in st['events'] if e['type'] in ('error', 'question')][-3:]))
    lot = ts.place()['lot']
    placement = lot.get('placement') or {}
    check(placement.get('confirmed') is True and placement.get('source') == plot and placement.get('page') == 1,
          ('settling the plot saves a confirmed placement', placement))
    plan = ts.current()
    check(len(placement.get('outline') or []) == len(plan['site']['lot'])
          and all(close(a, b_, 1e-6) for a, b_ in zip(placement['outline'], plan['site']['lot'])),
          (placement.get('outline'), plan['site']['lot']))
    read = lot.get('read') or {}
    check(len(read.get('suggestions') or []) == 1, ('the read and its suggestion are kept', read))
    check(plan['buildings'] == [], plan['buildings'])
    check(_read_kinds(reader) == ['plot', 'site'], _read_kinds(reader))


def scenario_lot_without_plot_page_refused():
    _house_place(plot=False, photos=False)
    _expect_value_error(lambda: tb.start({'part': 'lot'}, reader=Reader(), inline=True), NO_PLOT)


def scenario_placement_from_another_page_rereads():
    # A8: a placement is used only for the lot's current plot page.
    engine_tests._fresh()
    plot = ts.save_source('drawing', 'plots.pdf', _pdf(2), part='lot')
    ts.set_page_roles([{'source': plot, 'page': 1, 'role': 'plot', 'level': None, 'box': None, 'building': 'lot'},
                       {'source': plot, 'page': 2, 'role': 'other', 'level': None, 'box': None, 'building': 'lot'}])
    _confirm_lot(plot, page=1)
    ts.set_page_roles([{'source': plot, 'page': 1, 'role': 'other', 'level': None, 'box': None, 'building': 'lot'},
                       {'source': plot, 'page': 2, 'role': 'plot', 'level': None, 'box': None, 'building': 'lot'}])
    reader = Reader()
    b = tb.start({'part': 'lot'}, reader=reader, inline=True)
    st = tb.status(b)
    check(st['state'] == 'paused' and st['pause']['kind'] == 'lot_placement' and st['pause']['step'] == 'plot',
          (st['state'], st.get('pause')))
    first = st['steps'][0]
    check(first['kind'] == 'plot' and first['source'] == plot and first['page'] == 2, first)
    check(_read_kinds(reader) == ['plot'], _read_kinds(reader))
    # The same page with another box is another plot page too.
    engine_tests._fresh()
    plot = ts.save_source('drawing', 'plot.pdf', _pdf(1), part='lot')
    ts.set_page_roles([{'source': plot, 'page': 1, 'role': 'plot', 'level': None, 'box': [0, 0, 0.5, 1], 'building': 'lot'}])
    _confirm_lot(plot, page=1, box=None)
    reader = Reader()
    b = tb.start({'part': 'lot'}, reader=reader, inline=True)
    st = tb.status(b)
    check(st['state'] == 'paused' and st['pause']['step'] == 'plot', (st['state'], st.get('pause')))
    check(_read_kinds(reader) == ['plot'], _read_kinds(reader))


def scenario_recover_paused_lot_build():
    # A7: a lot build has no inputs.building; it survives a restart either way.
    _lot_only()
    reader = PartReader(one_plot_building=True)
    b = tb.start({'part': 'lot'}, reader=reader, inline=True)
    check(tb.status(b)['state'] == 'paused', tb.status(b)['state'])
    tb._forget()
    tb.recover()
    st = tb.status(b)
    check(st['state'] == 'paused' and st['pause']['step'] == 'plot' and st.get('part') == 'lot',
          (st['state'], st.get('pause'), st.get('part')))
    # The process-local reader is gone after a restart; the default reader answers.
    after = PartReader()
    original = twin_reads.read
    twin_reads.read = after
    try:
        tb.answer(b, 'plot', {'accept': True})
        st = _wait(b)
    finally:
        twin_reads.read = original
    check(st['state'] == 'done', (st['state'], [e for e in st['events'] if e['type'] in ('error', 'question')][-3:]))
    check(_read_kinds(after) == ['site'], ('the plot is never read again', _read_kinds(after)))
    check(ts.place()['lot']['placement']['confirmed'] is True, ts.place()['lot'])
    # A crash mid-read leaves the build running on disk; recover stops it, and
    # resume finishes it without paying for the plot again.
    _lot_only()
    reader = PartReader(one_plot_building=True, crash_at='site')
    b = tb.start({'part': 'lot'}, reader=reader, inline=True)
    try:
        tb.answer(b, 'plot', {'accept': True})
    except _Crash:
        pass
    tb._forget()
    tb.recover()
    check(tb.status(b)['state'] == 'stopped', ('recover accepts a lot build', tb.status(b)['state']))
    again = PartReader()
    tb.resume(b, reader=again, inline=True)
    st = tb.status(b)
    check(st['state'] == 'done', (st['state'], [e for e in st['events'] if e['type'] in ('error', 'question')][-3:]))
    check(_read_kinds(again) == ['site'], _read_kinds(again))


# --- a building ----------------------------------------------------------------

def scenario_building_part_steps():
    _, plot, photos = _house_place()
    _confirm_lot(plot)
    reader = Reader()
    b = tb.start({'part': 'house'}, reader=reader, inline=True)
    check(tb.status(b).get('part') == 'house', tb.status(b).get('part'))
    st = _accept_all(b)
    check(st['state'] == 'done', (st['state'], [e for e in st['events'] if e['type'] in ('error', 'question')][-3:]))
    kinds = _kinds(b)
    check(kinds == ['outline', 'walls', 'walls', 'openings', 'rooms', 'roof', 'pitch', 'finishes', 'fit', 'compose'],
          kinds)
    check('plot' not in kinds and 'site' not in kinds, kinds)
    for kind in ('pitch', 'finishes'):
        call = next(c for c in reader.calls if c['kind'] == kind)
        check(call['images'] == 1, (f'{kind} sees only the photo tagged to the house', call['images']))
    check('plot' not in _read_kinds(reader) and 'site' not in _read_kinds(reader), _read_kinds(reader))
    house = _house(ts.current())
    check(house['name'] == 'Main house' and house.get('kind') == 'main_house', house)


def scenario_fit_settles_on_matching_footprint():
    _, plot, _ = _house_place(roof=False, photos=False)
    _confirm_lot(plot)
    target = {'position': [60.0, 80.0], 'rotation': 90}
    footprint = [tr.to_world(target, p) for p in _l_local()]
    ts.update_building('house', {'footprint': footprint, 'footprint_from': 'plot'})
    b = tb.start({'part': 'house'}, reader=PartReader(l_outline=True), inline=True)
    seen, st = _pause_kinds(b)
    check(st['state'] == 'done', (st['state'], [e for e in st['events'] if e['type'] in ('error', 'question')][-3:]))
    check(seen == ['outline'], ('only the outline asks; the fit settles alone', seen))
    check('fit' in _kinds(b), _kinds(b))
    house = _house(ts.current())
    check(_turn_gap(house['rotation'], 90) <= 1, ('turned onto the footprint', house['rotation']))
    check(math.dist(house['position'], target['position']) <= 0.5, ('placed on the footprint', house['position']))


def scenario_fit_pauses_on_poor_fit_and_missing_footprint():
    _, plot, _ = _house_place(roof=False, photos=False)
    _confirm_lot(plot)
    big = [tr.to_world({'position': [60.0, 80.0], 'rotation': 0}, [2 * x, 2 * y]) for x, y in _l_local()]
    ts.update_building('house', {'footprint': big, 'footprint_from': 'plot'})
    b = tb.start({'part': 'house'}, reader=PartReader(l_outline=True), inline=True)
    st = _run_to_pause(b, 'fit')
    check(st['state'] == 'paused' and st['pause']['step'] == 'fit', (st['state'], st.get('pause')))
    pause = st['pause']
    check(pause['kind'] == 'lot_placement' and pause['why'] == DISAGREE, pause)
    check(pause['registration'] == tr.make(1), pause['registration'])
    check(isinstance(pause.get('transform'), dict) and {'position', 'rotation'} <= set(pause['transform']), pause)
    tb.answer(b, 'fit', {'transform': {'position': [12.5, 34.0], 'rotation': 30}})
    st = tb.status(b)
    check(st['state'] == 'done', (st['state'], [e for e in st['events'] if e['type'] in ('error', 'question')][-3:]))
    house = _house(ts.current())
    check(close(house['position'], [12.5, 34.0], 1e-6) and _turn_gap(house['rotation'], 30) < 1e-6,
          ('the answer places the house', house['position'], house['rotation']))
    # No footprint: the house is offered beside the other buildings.
    _, plot, _ = _house_place(roof=False, photos=False)
    _confirm_lot(plot)
    shed = {'id': 'shed', 'name': 'Shed', 'position': [0, 0], 'rotation': 0,
            'levels': [{'id': 'L1', 'name': 'Floor', 'elevation': 0, 'ceiling': 8,
                        'outline': [[0, 0], [20, 0], [20, 12], [0, 12]]}],
            'walls': [], 'openings': [], 'rooms': [], 'roof': {'sections': []}}
    ts.push_round(twin_plan.normalize({'units': 'ft', 'buildings': [shed], 'site': {}, 'materials': {}})[0], 'edit')
    b = tb.start({'part': 'house'}, reader=PartReader(l_outline=True), inline=True)
    st = _run_to_pause(b, 'fit')
    check(st['state'] == 'paused' and st['pause']['step'] == 'fit', (st['state'], st.get('pause')))
    pause = st['pause']
    check(pause['kind'] == 'lot_placement' and pause['why'] == NO_FOOTPRINT, pause)
    check(pause['registration'] == tr.make(1), pause['registration'])
    check(close(pause['transform']['position'], [30, 0], 1e-6) and pause['transform']['rotation'] == 0,
          ('beside the other buildings, as slice 1 does', pause['transform']))
    tb.answer(b, 'fit', {'accept': True})
    check(tb.status(b)['state'] == 'done', tb.status(b)['state'])
    check(close(_house(ts.current())['position'], [30, 0], 1e-6), _house(ts.current())['position'])
    check(close(_house(ts.current(), 'shed')['position'], [0, 0], 1e-9), 'the shed stays where it was')


def scenario_fit_never_moves_a_person_placed_building():
    _, plot, _ = _house_place(roof=False, photos=False)
    _confirm_lot(plot)
    b = tb.start({'part': 'house'}, reader=PartReader(l_outline=True), inline=True)
    _accept_all(b)
    check(tb.status(b)['state'] == 'done', tb.status(b)['state'])

    def place_by_hand(plan):
        house = _house(plan)
        house.update(position=[5.0, 5.0], rotation=0, src={'person': True})
        return plan

    ts.update_current(place_by_hand, kind='edit')
    footprint = [tr.to_world({'position': [60.0, 80.0], 'rotation': 90}, p) for p in _l_local()]
    ts.update_building('house', {'footprint': footprint, 'footprint_from': 'plot'})
    b = tb.start({'part': 'house'}, reader=PartReader(l_outline=True), inline=True)
    seen, st = _pause_kinds(b)
    check(st['state'] == 'done', (st['state'], [e for e in st['events'] if e['type'] in ('error', 'question')][-3:]))
    house = _house(ts.current())
    check(close(house['position'], [5.0, 5.0], 1e-9) and house['rotation'] == 0,
          ('a person placed it; the fit never moves it', house['position'], house['rotation']))


def scenario_finishes_per_building():
    # A9: each building keeps its own finishes; the plan's stay as they were.
    engine_tests._fresh()
    house_sheet = ts.save_source('drawing', 'house.pdf', _pdf(1))
    ts.add_building('Shed', 'shed')
    shed_sheet = ts.save_source('drawing', 'shed.pdf', _pdf(1), part='shed')
    ts.set_page_roles([
        {'source': house_sheet, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None, 'building': 'house'},
        {'source': shed_sheet, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None, 'building': 'shed'}])
    ts.save_source('photo', 'house.jpg', _jpeg(), part='house')
    ts.save_source('photo', 'shed.jpg', _jpeg(), part='shed')
    colours = {'house': '#112233', 'shed': '#aa0000'}
    for bid in ('house', 'shed'):
        reader = PartReader(sidings=colours)
        b = tb.start({'part': bid}, reader=reader, inline=True)
        st = _accept_all(b)
        check(st['state'] == 'done', (bid, st['state'], [e for e in st['events'] if e['type'] in ('error', 'question')][-3:]))
        kinds = _kinds(b)
        check(not {'plot', 'site', 'fit'} & set(kinds), ('no lot: no plot, site or fit', kinds))
        check([c['context']['building']['id'] for c in reader.calls if c['kind'] == 'finishes'] == [bid], reader.calls)
    plan = ts.current()
    for bid, colour in colours.items():
        siding = ((_house(plan, bid).get('materials') or {}).get('siding') or {})
        check(siding.get('color') == colour and siding.get('id') == 'board_and_batten',
              (bid, 'keeps its own siding', _house(plan, bid).get('materials')))
    check('siding' not in plan['materials'], ('a part build leaves plan.materials alone', plan['materials']))
    kept, _ = twin_plan.normalize(plan)
    check(_house(kept, 'shed')['materials']['siding']['color'] == '#aa0000', 'normalize keeps building.materials')


def scenario_legacy_body_unchanged():
    engine_tests._fresh()
    _, _, photo = engine_tests._sources()
    b = tb.start({'building': {'id': 'house', 'name': 'Main house'}, 'photos': [photo]}, reader=Reader(), inline=True)
    st = tb.status(b)
    check([s['id'] for s in st['steps']] == SLICE1_IDS, [s['id'] for s in st['steps']])
    check('next' in st and st['next'] is None, ('status carries next, None until Task 6', sorted(st)))
    seen, st = _pause_kinds(b)
    check(st['state'] == 'done', st['state'])
    check(seen == ['outline', 'registration', 'plot'], seen)
    check('fit' not in _kinds(b) and 'lot' not in _kinds(b), _kinds(b))
    plan = ts.current()
    check(plan['materials'].get('siding'), ('the legacy body still writes plan.materials', plan['materials']))
    check(not _house(plan).get('materials'), ('and no building finishes', _house(plan).get('materials')))


def scenario_zero_building_plan():
    plan, _ = twin_plan.normalize({'units': 'ft', 'buildings': [], 'site': {'lot': SQUARE}})
    check(plan['buildings'] == [] and plan['site']['lot'] == SQUARE, plan)
    _expect_value_error(lambda: twin_plan.normalize({'units': 'ft', 'buildings': [], 'site': {}}), NO_BUILDING)
    _expect_value_error(lambda: twin_plan.normalize({'units': 'ft', 'buildings': []}), NO_BUILDING)
    _expect_value_error(lambda: twin_plan.normalize({'units': 'ft', 'buildings': [],
                                                     'site': {'lot': [[0, 0], [10, 0]]}}), NO_BUILDING)


def scenario_finishes_override_only_answered_valid_roles():
    _house_place(roof=False, plot=False)

    class FinishesReader(Reader):
        def __call__(self, kind, images, context, *, run, step):
            if kind == 'finishes':
                return {'materials': {
                    'siding': {'id': 'board_and_batten', 'color': '#112233'},
                    'trim': {'id': 'not_in_the_kit', 'color': '#abcdef'},
                    'roof': {'id': 'board_and_batten', 'color': 'bad'},
                    'unknown': {'id': 'board_and_batten', 'color': '#abcdef'}}}
            return super().__call__(kind, images, context, run=run, step=step)

    b = tb.start({'part': 'house'}, reader=FinishesReader(), inline=True)
    check(_accept_all(b)['state'] == 'done', tb.status(b))
    own = _house(ts.current())['materials']
    check(own == {'siding': {'id': 'board_and_batten', 'color': '#112233'},
                  'trim': {'id': tb.twin_library.kit('modern_farmhouse')['materials']['trim']['asset'],
                           'color': tb.twin_library.kit('modern_farmhouse')['materials']['trim']['color']}}, own)

    def change_plan_finish(plan):
        plan['materials']['trim'] = {'id': 'board_and_batten', 'color': '#abcdef'}
        return plan

    ts.update_current(change_plan_finish, kind='director')
    plan = ts.current()
    merged = {**plan['materials'], **_house(plan)['materials']}
    check(merged['trim'] == own['trim'], merged)
    check(merged['siding'] == own['siding'], merged)


def scenario_lot_build_rejects_self_crossing_plot():
    _lot_only()

    class CrossingReader(Reader):
        def __call__(self, kind, images, context, *, run, step):
            if kind == 'plot':
                answer = fixture('plot')
                answer['lot'] = [[.1, .1], [.9, .9], [.1, .9], [.9, .1]]
                return answer
            return super().__call__(kind, images, context, run=run, step=step)

    b = tb.start({'part': 'lot'}, reader=CrossingReader(), inline=True)
    try:
        st = _accept_all(b)
    except ValueError as exc:
        check(str(exc) == 'The plot plan could not be read. Try again, or place the buildings by hand.', str(exc))
    else:
        check(st['state'] in ('paused', 'stopped', 'failed'), st)
        check(any(e.get('text') == 'This drawing could not be read. Check the page and try reading it again.'
                  for e in st['events']), st['events'])
    check(not (ts.place()['lot'].get('placement') or {}).get('confirmed'), ts.place()['lot'])
    check(ts.current() is None, ts.current())


def scenario_person_placed_fit_never_pauses():
    for footprint in (None, [[0, 0], [10, 0], [10, 10], [0, 10]]):
        _, plot, _ = _house_place(roof=False, photos=False)
        _confirm_lot(plot)
        b = tb.start({'part': 'house'}, reader=PartReader(l_outline=True), inline=True)
        check(_accept_all(b)['state'] == 'done', tb.status(b))

        def place_by_hand(plan):
            _house(plan).update(position=[5, 6], rotation=30, src={'person': True})
            return plan

        ts.update_current(place_by_hand, kind='edit')
        if footprint is not None:
            ts.update_building('house', {'footprint': footprint, 'footprint_from': 'plot'})
        b = tb.start({'part': 'house'}, reader=PartReader(l_outline=True), inline=True)
        seen, st = _pause_kinds(b)
        check(st['state'] == 'done' and 'fit' not in seen, (st['state'], seen))
        house = _house(ts.current())
        check(house['position'] == [5, 6] and house['rotation'] == 30, house)


def scenario_drawing_build_moved_then_deleted_wall_stays_deleted():
    from services import twin_edit
    _house_place(roof=False, plot=False, photos=False)

    def rebuild():
        b = tb.start({'part': 'house'}, reader=Reader(), inline=True)
        check(_accept_all(b)['state'] == 'done', tb.status(b))
        return _house(ts.current())

    house = rebuild()
    wall = house['walls'][0]
    original = copy.deepcopy(wall['read_geometry'])
    count = len(house['walls'])
    twin_edit.save({'op': 'move', 'building': 'house', 'piece': wall['id'], 'by': [0, -4]}, 'p1')
    house = rebuild()
    check(len(house['walls']) == count, house['walls'])
    twin_edit.save({'op': 'delete', 'building': 'house', 'piece': wall['id']}, 'p1')
    house = rebuild()
    check(len(house['walls']) == count - 1, house['walls'])
    check(not any(tb._near_geometry(tb._geometry(w, 'wall', house), original, 'wall') for w in house['walls']), house['walls'])


def scenario_part_settle_keeps_pause_time_name_and_kind():
    _house_place(roof=False, plot=False, photos=False)
    b = tb.start({'part': 'house'}, reader=Reader(), inline=True)
    check(tb.status(b)['state'] == 'paused', tb.status(b))
    ts.update_building('house', {'name': 'Farmhouse', 'kind': 'other'})
    check(_accept_all(b)['state'] == 'done', tb.status(b))
    house = _house(ts.current())
    check((house['name'], house['kind']) == ('Farmhouse', 'other'), house)


def scenario_lot_build_reuses_setup_read_and_answers():
    from services import twin_place_reads as tpr
    _lot_only()
    tpr.read_plot(reader=Reader())
    suggestions = ts.place()['lot']['read']['suggestions']
    tpr.answer_suggestion(suggestions[0]['id'], 'accept', name='Shed', kind='shed')
    tpr.answer_suggestion(suggestions[1]['id'], 'dismiss')
    stored = copy.deepcopy(ts.place()['lot']['read'])
    reader = Reader()
    b = tb.start({'part': 'lot'}, reader=reader, inline=True)
    st = tb.status(b)
    check(st['state'] == 'paused' and st['pause']['kind'] == 'lot_placement', st)
    check(reader.calls == [], ('setup read must not be repaid', reader.calls))
    check(st['pause']['registration'] == stored['registration'], st['pause'])
    # Restart with the cached setup read, then confirm it through the real answer path.
    tb._forget()
    tb.recover()
    tb.resume(b, reader=reader, inline=True)
    check(_accept_all(b)['state'] == 'done', tb.status(b))
    lot = ts.place()['lot']
    check(lot['placement']['confirmed'] and lot['read'] == stored, lot)
    check(_read_kinds(reader) == ['site'], reader.calls)


def scenario_lot_setup_read_can_still_be_explicitly_reread():
    from services import twin_place_reads as tpr
    _lot_only()
    tpr.read_plot(reader=Reader())
    original_id = ts.place()['lot']['read']['id']
    reader = Reader()
    b = tb.start({'part': 'lot'}, reader=reader, inline=True)
    check(reader.calls == [], reader.calls)
    tb.reread(b, 'plot', reader=reader, inline=True)
    check(_read_kinds(reader) == ['plot'], reader.calls)
    check(_accept_all(b)['state'] == 'done', tb.status(b))
    check(ts.place()['lot']['read']['id'] != original_id, ts.place()['lot'])


SCENARIOS = (
    scenario_lot_setup_read_can_still_be_explicitly_reread,
    scenario_part_settle_keeps_pause_time_name_and_kind,
    scenario_lot_build_reuses_setup_read_and_answers,
    scenario_drawing_build_moved_then_deleted_wall_stays_deleted,
    scenario_finishes_override_only_answered_valid_roles,
    scenario_lot_build_rejects_self_crossing_plot,
    scenario_person_placed_fit_never_pauses,
    scenario_lot_build_confirmed_placement,
    scenario_lot_build_reads_plot_when_unconfirmed,
    scenario_lot_without_plot_page_refused,
    scenario_placement_from_another_page_rereads,
    scenario_recover_paused_lot_build,
    scenario_building_part_steps,
    scenario_fit_settles_on_matching_footprint,
    scenario_fit_pauses_on_poor_fit_and_missing_footprint,
    scenario_fit_never_moves_a_person_placed_building,
    scenario_finishes_per_building,
    scenario_legacy_body_unchanged,
    scenario_zero_building_plan,
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

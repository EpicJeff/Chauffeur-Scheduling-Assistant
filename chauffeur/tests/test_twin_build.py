"""The house editor's build engine (spec docs/superpowers/specs/
2026-11-07-house-editor-design.md section 7; plan
docs/superpowers/plans/2026-11-07-house-editor-slice-1.md Task 8 and its
review amendment): steps in order, three pauses, ghosts that settle, wings
expanded after their outline, crops composed through parent boxes, resume
without repaying, checkpoints, person edits never overwritten, deletions never
resurrected, and a start over that a late worker result cannot undo.

The reader is a fake standing in for twin_reads.read; the engine re-validates
whatever a reader returns with twin_reads.parse, so the fake answers in the
real contracts' shapes. Sources are blank 17 x 11 inch PDFs (masters
5100 x 3300 px). Scale: 70 ft = 0.5 of the page width.

Run from chauffeur/:  python tests/test_twin_build.py
"""
import copy
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_build_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import storage  # noqa: E402
from services import twin_build as tb  # noqa: E402
from services import twin_cost as tc  # noqa: E402
from services import twin_edit  # noqa: E402
from services import twin_store as ts  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_reads')
DEPTH_V = 0.721212   # 65'-4" at 70 ft per 0.5 page width on a 5100 x 3300 master
L1 = [[0.2, 0.1], [0.7, 0.1], [0.7, 0.1 + DEPTH_V], [0.2, 0.1 + DEPTH_V]]
DIM = {'a': [0.2, 0.95], 'b': [0.7, 0.95], 'feet': 70.0}


def check(cond, msg):
    # Local on purpose: tests/harness.py stubs storage.get_settings.
    if not cond:
        raise AssertionError(msg)


def close(a, b, tol=1e-3):
    return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


def fixture(kind):
    with open(os.path.join(FIXTURES, f'{kind}.json'), encoding='utf-8') as f:
        return json.load(f)


def _pdf(pages, w=1224, h=792):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(w, h)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _jpeg():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (64, 48), (200, 200, 200)).save(buf, format='JPEG')
    return buf.getvalue()


class _Crash(BaseException):
    """Stands in for the add-on process dying mid-build."""


class Reader:
    """Stands in for twin_reads.read: answers each step kind in its real shape."""

    def __init__(self, wings_l2=None, walls_extra=None, checkpoint_at=None, crash_at=None, block_at=None):
        self.calls = []
        self.reverse_walls = False          # a reread that returns the same walls in another order
        self.isolated_walls_for = None      # a walls step whose walls are all tiny and unconnected
        self.plot_no_street = False
        self.outline_reads = 0
        self.shift_wings_after_first = False   # a reread draws the same wings a little differently (~0.4 ft)
        self.error_once_at = None             # a step whose first read fails (timeout)
        self.wings_l2 = wings_l2
        self.walls_extra = walls_extra or []
        self.checkpoint_at, self.crash_at, self.block_at = checkpoint_at, crash_at, block_at
        self.release = threading.Event()
        self.blocked = threading.Event()

    def __call__(self, kind, images, context, *, run, step):
        self.calls.append({'kind': kind, 'step': step, 'context': copy.deepcopy(context), 'images': len(images)})
        if step == self.crash_at:
            raise _Crash()
        if step == self.checkpoint_at:
            raise tc.CheckpointReached(10.0, 10.3)
        if step == self.block_at:
            self.blocked.set()
            self.release.wait(10)
        if step == self.error_once_at:
            self.error_once_at = None
            return {'error': 'The model did not answer in 120 s.'}
        if kind == 'outline':
            self.outline_reads += 1
            if self.shift_wings_after_first and self.outline_reads > 1:
                return {'dimension': DIM, 'outline': L1, 'confidence': 0.8, 'why': '',
                        'wings': [{'name': 'garage', 'box': [0.553, 0.5, 0.703, 0.1 + DEPTH_V]},
                                  {'name': 'main', 'box': [0.203, 0.1, 0.603, 0.1 + DEPTH_V]}]}
            return {'dimension': DIM, 'outline': L1, 'confidence': 0.8, 'why': '',
                    'wings': [{'name': 'garage', 'box': [0.55, 0.5, 0.7, 0.1 + DEPTH_V]},
                              {'name': 'main', 'box': [0.2, 0.1, 0.6, 0.1 + DEPTH_V]}]}
        if kind == 'walls':
            walls = [{'from': [0, 0], 'to': [1, 0], 'exterior': True}, {'from': [1, 0], 'to': [1, 1], 'exterior': True},
                     {'from': [1, 1], 'to': [0, 1], 'exterior': True}, {'from': [0, 1], 'to': [0, 0], 'exterior': True}]
            if step == self.isolated_walls_for:
                walls = [{'from': [0.3 + 0.1 * i, 0.5], 'to': [0.32 + 0.1 * i, 0.5], 'exterior': False}
                         for i in range(4)]
            walls = walls + copy.deepcopy(self.walls_extra)
            if self.reverse_walls:
                walls = list(reversed(walls))
            return {'walls': walls, 'confidence': 0.8, 'why': ''}
        if kind == 'plot' and self.plot_no_street:
            answer = fixture('plot')
            answer.pop('street_edge', None)
            return answer
        if kind == 'registration':
            return {'dimension': DIM, 'lower_outline': L1, 'outline': [[0.3, 0.2], [0.6, 0.2], [0.6, 0.7], [0.3, 0.7]],
                    'wings': self.wings_l2 or [{'name': 'upper', 'box': [0.3, 0.2, 0.6, 0.7]}],
                    'confidence': 0.7, 'why': 'the stamp covers a corner'}
        if kind == 'roof':
            return {'outline': [[0.19, 0.09], [0.71, 0.09], [0.71, 0.83], [0.19, 0.83]], 'confidence': 0.7,
                    'sections': [{'kind': 'hip', 'box': [0.19, 0.09, 0.71, 0.83], 'ridge': 'y', 'low_side': None}]}
        if kind == 'pitch':
            return {'pitches': [{'section': s, 'pitch': 8, 'confidence': 0.6, 'why': 'photo'}
                                for s in context.get('sections', [])] or [{'section': 'roof-1', 'pitch': 8}]}
        return fixture(kind)


def _fresh():
    storage.patch_settings({'house_twin': None, 'house_twin_cost': None})
    shutil.rmtree(ts.DATA_DIR, ignore_errors=True)
    tb._forget()


def _sources(l2_box=None):
    sheets = ts.save_source('drawing', 'lot58.pdf', _pdf(3))
    plot = ts.save_source('drawing', 'plot.pdf', _pdf(1))
    photo = ts.save_source('photo', 'front.jpg', _jpeg())
    rows = [{'source': sheets, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None},
            {'source': sheets, 'page': 2, 'role': 'floor', 'level': 'Upper floor', 'box': l2_box},
            {'source': sheets, 'page': 3, 'role': 'roof', 'level': None, 'box': None},
            {'source': plot, 'page': 1, 'role': 'plot', 'level': None, 'box': None}]
    ts.set_page_roles(rows)
    return sheets, plot, photo


def _inputs(photo):
    return {'building': {'id': 'house', 'name': 'Main house'}, 'photos': [photo]}


def _accept_all(b, limit=20):
    for _ in range(limit):
        st = tb.status(b)
        if st['state'] != 'paused':
            return st
        tb.answer(b, st['pause']['step'], {'accept': True})
    raise AssertionError('too many pauses')


def _walls(plan, level):
    return [w for w in plan['buildings'][0]['walls'] if w['level'] == level]


def scenario_main_house_step_order():
    rows = [{'source': 's', 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None, 'building': 'house'},
            {'source': 's', 'page': 2, 'role': 'floor', 'level': 'Upper floor', 'box': None, 'building': 'house'},
            {'source': 's', 'page': 3, 'role': 'roof', 'level': None, 'box': None, 'building': 'house'},
            {'source': 's', 'page': 3, 'role': 'floor', 'level': 'Bonus', 'box': [0.05, 0.2, 0.4, 0.8], 'building': 'house'}]
    steps = tb.plan_steps(rows, photos=['ph1'], plot=[{'source': 'p', 'page': 1}])
    check([s['id'] for s in steps] == ['outline:L1', 'openings:L1', 'rooms:L1', 'registration:L2', 'openings:L2',
                                       'rooms:L2', 'registration:L3', 'openings:L3', 'rooms:L3', 'roof', 'pitch',
                                       'plot', 'site', 'finishes', 'compose'], [s['id'] for s in steps])
    check([s['pause'] for s in steps if s['pause']] == ['scale_outline', 'level_registration', 'level_registration',
                                                        'lot_placement'], steps)
    check(tb.plan_steps(rows, photos=[], plot=[])[-1]['id'] == 'compose', 'no photos, no plot: still ends composed')
    ids = [s['id'] for s in tb.plan_steps(rows, photos=[], plot=[])]
    check('pitch' not in ids and 'plot' not in ids and 'finishes' not in ids, ids)


def scenario_first_pause_and_wings_expand_after_the_outline():
    _fresh()
    _, _, photo = _sources()
    reader = Reader()
    b = tb.start(_inputs(photo), reader=reader, inline=True)
    st = tb.status(b)
    check(st['state'] == 'paused' and st['pause']['kind'] == 'scale_outline' and st['pause']['step'] == 'outline:L1', st)
    check(any(e['type'] == 'ghost' for e in st['events']), 'the outline shows as a ghost before the pause')
    tb.answer(b, 'outline:L1', {'accept': True})
    ids = [s['id'] for s in tb.status(b)['steps']]
    check(ids[1:3] == ['walls:L1:garage', 'walls:L1:main'], ids)
    logs = [e['text'] for e in tb.status(b)['events'] if e['type'] == 'log']
    check("Main floor outline: 70'-0\" by 65'-4\"" in logs, logs)
    reg = ts.registration(ts.page_roles()[0]['source'], 1, 'L1')
    check(reg and abs(reg['scale'] - 70.0 / 2550) < 1e-6, reg)


def scenario_events_since_and_rounds_per_settle():
    _fresh()
    _, _, photo = _sources()
    b = tb.start(_inputs(photo), reader=Reader(), inline=True)
    first = tb.status(b)
    tb.answer(b, 'outline:L1', {'accept': True})
    later = tb.status(b, since=first['seq'])
    check(later['events'] and all(e['seq'] > first['seq'] for e in later['events']), 'since filters')
    builds = [r for r in ts.rounds() if r['kind'] == 'build']
    check(builds and all(r.get('step') and r['step']['id'] for r in builds), builds)


def scenario_full_build_finishes_with_three_pause_kinds():
    _fresh()
    _, _, photo = _sources()
    b = tb.start(_inputs(photo), reader=Reader(), inline=True)
    kinds = []
    for _ in range(10):
        st = tb.status(b)
        if st['state'] != 'paused':
            break
        kinds.append(st['pause']['kind'])
        tb.answer(b, st['pause']['step'], {'accept': True})
    st = tb.status(b)
    check(st['state'] == 'done' and any(e['type'] == 'done' for e in st['events']), st['state'])
    check(kinds == ['scale_outline', 'level_registration', 'lot_placement'], kinds)
    plan = ts.current()
    check(len(_walls(plan, 'L1')) >= 4 and len(_walls(plan, 'L2')) >= 4, 'both floors built')
    check(plan['buildings'][0]['roof']['sections'][0]['pitch'] == 8, 'pitch from the photos')
    check(plan['buildings'][0]['roof']['sections'][0]['pitch_source'] == 'photos', 'marked as estimated')
    check(not tb.running(), 'idle when done')
    check(plan['materials'] and plan['materials'].get('siding'), 'finishes from the photos')
    check(any(i.get('by') == 'compose' for i in plan['site'].get('planting') or []), 'the yard was composed')


def scenario_lot_placement_answer_moves_and_turns_the_building():
    _fresh()
    _, _, photo = _sources()
    b = tb.start(_inputs(photo), reader=Reader(), inline=True)
    for _ in range(10):
        st = tb.status(b)
        if st['state'] != 'paused':
            break
        if st['pause']['kind'] == 'lot_placement':
            tb.answer(b, st['pause']['step'], {'transform': {'position': [10, 20], 'rotation': 90}})
        else:
            tb.answer(b, st['pause']['step'], {'accept': True})
    house = ts.current()['buildings'][0]
    check(house['position'] == [10, 20] and house['rotation'] == 90, house)


def scenario_nested_wing_crop_is_composed():
    _fresh()
    _, _, photo = _sources(l2_box=[0.05, 0.2, 0.4, 0.8])
    reader = Reader(wings_l2=[{'name': 'upper', 'box': [0.5, 0.5, 1, 1]}])
    b = tb.start(_inputs(photo), reader=reader, inline=True)
    _accept_all(b)
    walls = [c for c in reader.calls if c['step'] == 'walls:L2:upper']
    check(walls and close(walls[0]['context']['box'], [0.225, 0.5, 0.4, 0.8]), walls)


def scenario_out_of_crop_read_stays_a_ghost():
    _fresh()
    _, _, photo = _sources()
    reader = Reader(walls_extra=[{'from': [0.5, 0.5], 'to': [0.52, 0.5], 'exterior': False},
                                 {'from': [0.1, 0.1], 'to': [3.0, 0.1], 'exterior': False}])
    b = tb.start(_inputs(photo), reader=reader, inline=True)
    st = _accept_all(b)
    check(st['state'] == 'done', st['state'])
    ghosts = [w for w in _walls(ts.current(), 'L1') if w.get('state') == 'ghost']
    check(ghosts and all(w.get('why') for w in ghosts), ghosts)
    check(not any(max(abs(c) for c in w['to']) > 500 for w in _walls(ts.current(), 'L1')), 'nonsense never kept')


def scenario_restart_resumes_without_repaying():
    _fresh()
    _, _, photo = _sources()
    reader = Reader(crash_at='rooms:L1')
    b = tb.start(_inputs(photo), reader=reader, inline=True)
    try:
        _accept_all(b)          # the crash comes from the first answer's continuation
    except _Crash:
        pass
    before = len(reader.calls)
    tb._forget()
    tb.recover()
    check(tb.status(b)['state'] == 'stopped', tb.status(b)['state'])
    reader.crash_at = None
    tb.resume(b, reader=reader, inline=True)
    again = [c['step'] for c in reader.calls[before:]]
    check(again and again[0] == 'rooms:L1' and 'outline:L1' not in again and 'walls:L1:main' not in again, again)


def scenario_checkpoint_stops_and_resumes():
    _fresh()
    _, _, photo = _sources()
    reader = Reader(checkpoint_at='rooms:L1')
    b = tb.start(_inputs(photo), reader=reader, inline=True)
    tb.answer(b, 'outline:L1', {'accept': True})
    st = tb.status(b)
    check(st['state'] == 'checkpoint' and any(e['type'] == 'checkpoint' for e in st['events']), st['state'])
    reader.checkpoint_at = None
    tb.resume(b, reader=reader, inline=True)
    rooms = next(s for s in tb.status(b)['steps'] if s['id'] == 'rooms:L1')
    check(rooms['status'] == 'done', rooms)


def scenario_merge_keeps_person_edits():
    _fresh()
    _, _, photo = _sources()
    reader = Reader()
    b = tb.start(_inputs(photo), reader=reader, inline=True)
    tb.answer(b, 'outline:L1', {'accept': True})
    wall = next(w for w in _walls(ts.current(), 'L1') if w.get('src', {}).get('step') == 'walls:L1:main')
    twin_edit.save({'op': 'set', 'piece': wall['id'], 'field': 'height', 'value': 11}, 'p1')
    tb.reread(b, 'walls:L1:main', reader=reader, inline=True)
    found = [w for w in _walls(ts.current(), 'L1') if w['id'] == wall['id']]
    check(found and found[0]['height'] == 11, found)


def scenario_reread_does_not_resurrect_a_deleted_wall():
    _fresh()
    _, _, photo = _sources()
    reader = Reader()
    b = tb.start(_inputs(photo), reader=reader, inline=True)
    tb.answer(b, 'outline:L1', {'accept': True})
    wall = next(w for w in _walls(ts.current(), 'L1') if w.get('src', {}).get('step') == 'walls:L1:main')
    twin_edit.save({'op': 'delete', 'piece': wall['id']}, 'p1')
    count = len(_walls(ts.current(), 'L1'))
    tb.reread(b, 'walls:L1:main', reader=reader, inline=True)
    after = _walls(ts.current(), 'L1')
    check(len(after) == count, (count, len(after)))
    check(not any(w['from'] == wall['from'] and w['to'] == wall['to'] for w in after), 'the deleted wall stays gone')


def scenario_registration_answer_moves_the_level():
    _fresh()
    sheets, _, photo = _sources()
    b = tb.start(_inputs(photo), reader=Reader(), inline=True)
    tb.answer(b, 'outline:L1', {'accept': True})
    st = tb.status(b)
    check(st['pause']['step'] == 'registration:L2', st['pause'])
    reg = dict(st['pause']['registration'])
    reg['offset'] = [reg['offset'][0] + 1.0, reg['offset'][1]]
    tb.answer(b, 'registration:L2', {'registration': reg})
    saved = ts.registration(sheets, 2, 'L2')
    check(abs(saved['offset'][0] - reg['offset'][0]) < 1e-9, saved)


def scenario_one_build_at_a_time():
    _fresh()
    _, _, photo = _sources()
    reader = Reader(block_at='outline:L1')
    b = tb.start(_inputs(photo), reader=reader, inline=False)
    check(reader.blocked.wait(10), 'worker reached the read')
    check(tb.running(), 'running')
    try:
        tb.start(_inputs(photo), reader=Reader(), inline=True)
    except ValueError as exc:
        check('already running' in str(exc), exc)
    else:
        raise AssertionError('a second build must refuse')
    reader.release.set()
    tb.stop(b)


def scenario_start_over_discards_a_late_result():
    _fresh()
    _, _, photo = _sources()
    reader = Reader(block_at='outline:L1')
    b = tb.start(_inputs(photo), reader=reader, inline=False)
    check(reader.blocked.wait(10), 'worker reached the read')
    tb.stop(b)
    ts.start_over()
    reader.release.set()
    for t in threading.enumerate():
        if t.name.startswith('twin-build-'):
            t.join(10)
    check(ts.current() is None and ts.rounds() == [], 'nothing written after start over')
    check(not os.path.exists(os.path.join(ts.DATA_DIR, 'builds', b)), 'no build state recreated')


def _run_to(b, step_id, limit=20):
    for _ in range(limit):
        st = tb.status(b)
        if st['state'] != 'paused' or st['pause']['step'] == step_id:
            return st
        tb.answer(b, st['pause']['step'], {'accept': True})
    return tb.status(b)


def _same_geometry(a, b, tol=0.1):
    return all(abs(x - y) <= tol for x, y in zip(a['from'] + a['to'], b['from'] + b['to']))


def scenario_reread_in_another_order_keeps_person_edits_without_duplicates():
    _fresh()
    _, _, photo = _sources()
    reader = Reader()
    b = tb.start(_inputs(photo), reader=reader, inline=True)
    tb.answer(b, 'outline:L1', {'accept': True})
    mine = [w for w in _walls(ts.current(), 'L1') if w.get('src', {}).get('step') == 'walls:L1:main']
    edited = mine[1]
    twin_edit.save({'op': 'set', 'piece': edited['id'], 'field': 'height', 'value': 11}, 'p1')
    reader.reverse_walls = True
    tb.reread(b, 'walls:L1:main', reader=reader, inline=True)
    after = _walls(ts.current(), 'L1')
    check(next(w for w in after if w['id'] == edited['id'])['height'] == 11, 'the person edit survives')
    for i, w in enumerate(after):
        for other in after[i + 1:]:
            flipped = {'from': other['to'], 'to': other['from']}
            check(not _same_geometry(w, other) and not _same_geometry(w, flipped), ('duplicate wall', w['id'], other['id']))
    ours = [w for w in after if w.get('src', {}).get('step') == 'walls:L1:main' or w['id'] == edited['id']]
    check(len(ours) == len(mine), 'same walls, no more, no fewer')


def scenario_outline_reread_resettles_openings_and_rooms_without_paying():
    _fresh()
    _, _, photo = _sources()
    reader = Reader()
    b = tb.start(_inputs(photo), reader=reader, inline=True)
    st = _run_to(b, 'registration:L2')
    check(st['pause']['step'] == 'registration:L2', st['pause'])
    openings_before = len(ts.current()['buildings'][0]['openings'])
    before = len(reader.calls)
    tb.reread(b, 'outline:L1', reader=reader, inline=True)
    st = _run_to(b, 'registration:L2')
    again = [c['step'] for c in reader.calls[before:]]
    check('openings:L1' not in again and 'rooms:L1' not in again, again)
    check(again.count('outline:L1') == 1, 'the reread itself pays exactly once')
    plan = ts.current()
    check(len(plan['buildings'][0]['openings']) == openings_before and openings_before > 0, 'openings re-settled')
    check(plan['buildings'][0]['rooms'], 'rooms re-settled')


def scenario_far_openings_stay_ghosts_and_a_thin_walls_step_asks():
    _fresh()
    _, _, photo = _sources()
    reader = Reader()
    reader.isolated_walls_for = 'walls:L1:main'
    b = tb.start(_inputs(photo), reader=reader, inline=True)
    _run_to(b, 'registration:L2')
    events = tb.status(b)['events']
    check(any(e['type'] == 'question' and 'wall' in e['text'].lower() for e in events), 'a thin walls step asks')
    openings = ts.current()['buildings'][0]['openings']
    ghosts = [o for o in openings if o.get('state') == 'ghost']
    check(ghosts and all(o.get('why') for o in ghosts), openings)


def scenario_plot_without_a_street_edge_pauses_instead_of_failing():
    _fresh()
    _, _, photo = _sources()
    reader = Reader()
    reader.plot_no_street = True
    b = tb.start(_inputs(photo), reader=reader, inline=True)
    st = _run_to(b, 'plot')
    check(st['state'] == 'paused' and st['pause']['kind'] == 'lot_placement', st['state'])
    check('street' in st['pause']['why'].lower(), st['pause'])


def scenario_resume_waits_for_a_stopping_read_and_keeps_its_answer():
    _fresh()
    _, _, photo = _sources()
    reader = Reader(block_at='outline:L1')
    b = tb.start(_inputs(photo), reader=reader, inline=False)
    check(reader.blocked.wait(10), 'worker reached the read')
    tb.stop(b)
    try:
        tb.resume(b, reader=reader, inline=True)
    except ValueError as exc:
        check('stopping' in str(exc).lower(), exc)
    else:
        raise AssertionError('resume must wait while a stopped read is still in flight')
    reader.release.set()
    for t in threading.enumerate():
        if t.name.startswith('twin-build-'):
            t.join(10)
    reader.block_at = None
    tb.resume(b, reader=reader, inline=True)
    check([c['step'] for c in reader.calls].count('outline:L1') == 1, 'the paid answer was kept, not read twice')
    check(tb.status(b)['pause']['kind'] == 'scale_outline', tb.status(b)['pause'])


def scenario_roles_must_be_confirmed_first():
    _fresh()
    ts.save_source('drawing', 'lot58.pdf', _pdf(1))
    photo = ts.save_source('photo', 'front.jpg', _jpeg())
    try:
        tb.start(_inputs(photo), reader=Reader(), inline=True)
    except ValueError as exc:
        check('page' in str(exc).lower(), exc)
    else:
        raise AssertionError('no confirmed page roles: nothing to build')
    sheet = next(x['id'] for x in ts.sources() if x['kind'] == 'drawing')
    ts.set_page_roles([{'source': sheet, 'page': 1, 'role': 'floor', 'level': 'Ground', 'box': None,
                        'building': 'pool_house'}])
    try:
        tb.start(_inputs(photo), reader=Reader(), inline=True)
    except ValueError as exc:
        check('page' in str(exc).lower(), exc)
    else:
        raise AssertionError('pages marked for another building do not build this one')


def scenario_registration_pause_reports_fit_quality_and_rejects_junk():
    _fresh()
    _, _, photo = _sources()
    b = tb.start(_inputs(photo), reader=Reader(), inline=True)
    tb.answer(b, 'outline:L1', {'accept': True})
    st = tb.status(b)
    check(isinstance(st['pause'].get('rms'), (int, float)), st['pause'])
    for junk in ({'registration': {'scale': 'big'}}, {'transform': 5}, {'registration': None}, {}):
        try:
            tb.answer(b, 'registration:L2', junk)
        except ValueError:
            continue
        raise AssertionError(f'junk answer accepted: {junk}')
    check(tb.status(b)['state'] == 'paused', 'still waiting for a real answer')


def scenario_replayed_walls_keep_the_crop_they_were_read_from():
    _fresh()
    _, _, photo = _sources()
    reader = Reader()
    reader.shift_wings_after_first = True
    b = tb.start(_inputs(photo), reader=reader, inline=True)
    _run_to(b, 'registration:L2')
    before = {w['id']: (w['from'], w['to']) for w in _walls(ts.current(), 'L1')}
    calls = len(reader.calls)
    tb.reread(b, 'outline:L1', reader=reader, inline=True)
    _run_to(b, 'registration:L2')
    again = [c['step'] for c in reader.calls[calls:]]
    check(not any(st.startswith('walls:L1') for st in again), again)
    after = [(w['from'], w['to']) for w in _walls(ts.current(), 'L1')]
    for wid, (a, b2) in before.items():
        check(any(all(abs(x - y) < 0.1 for x, y in zip(a + b2, f + t)) for f, t in after),
              ('a replayed wall moved', wid, a, b2))


def scenario_a_failed_read_is_retried_on_resume():
    _fresh()
    _, _, photo = _sources()
    reader = Reader()
    reader.error_once_at = 'walls:L1:main'
    b = tb.start(_inputs(photo), reader=reader, inline=True)
    tb.answer(b, 'outline:L1', {'accept': True})
    st = tb.status(b)
    check(st['state'] in ('stopped', 'failed'), st['state'])
    tb.resume(b, reader=reader, inline=True)
    steps = [c['step'] for c in reader.calls]
    check(steps.count('walls:L1:main') == 2, steps)
    walls = next(x for x in tb.status(b)['steps'] if x['id'] == 'walls:L1:main')
    check(walls['status'] == 'done', walls)


def scenario_no_new_build_while_a_stopped_read_is_in_flight():
    _fresh()
    _, _, photo = _sources()
    reader = Reader(block_at='outline:L1')
    b = tb.start(_inputs(photo), reader=reader, inline=False)
    check(reader.blocked.wait(10), 'worker reached the read')
    tb.stop(b)
    try:
        tb.start(_inputs(photo), reader=Reader(), inline=True)
    except ValueError:
        pass
    else:
        raise AssertionError('a second build must wait for the stopped read')
    reader.release.set()
    for t in threading.enumerate():
        if t.name.startswith('twin-build-'):
            t.join(10)


if __name__ == '__main__':
    for fn in (scenario_main_house_step_order,
               scenario_first_pause_and_wings_expand_after_the_outline,
               scenario_events_since_and_rounds_per_settle,
               scenario_full_build_finishes_with_three_pause_kinds,
               scenario_lot_placement_answer_moves_and_turns_the_building,
               scenario_nested_wing_crop_is_composed,
               scenario_out_of_crop_read_stays_a_ghost,
               scenario_restart_resumes_without_repaying,
               scenario_checkpoint_stops_and_resumes,
               scenario_merge_keeps_person_edits,
               scenario_reread_does_not_resurrect_a_deleted_wall,
               scenario_registration_answer_moves_the_level,
               scenario_one_build_at_a_time,
               scenario_start_over_discards_a_late_result,
               scenario_reread_in_another_order_keeps_person_edits_without_duplicates,
               scenario_outline_reread_resettles_openings_and_rooms_without_paying,
               scenario_far_openings_stay_ghosts_and_a_thin_walls_step_asks,
               scenario_plot_without_a_street_edge_pauses_instead_of_failing,
               scenario_resume_waits_for_a_stopping_read_and_keeps_its_answer,
               scenario_roles_must_be_confirmed_first,
               scenario_registration_pause_reports_fit_quality_and_rejects_junk,
               scenario_replayed_walls_keep_the_crop_they_were_read_from,
               scenario_a_failed_read_is_retried_on_resume,
               scenario_no_new_build_while_a_stopped_read_is_in_flight):
        fn()
        print('  ok ', fn.__name__)

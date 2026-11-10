"""Roof-build protections retargeted under roofs-from-photos rulings R8-R10.

The old correction and ordering tests are retired (R9): derive tests and
test_twin_build_roof_blocks.test_reads_in_order own those contracts now.
The roof_check parser regression remains for old caches.
"""
import copy
import io
import json
import os
import re
import sys
import tempfile
import time
import traceback
from unittest.mock import patch

# Always a scratch data dir (the engine harness wipes its data dir); keep one
# an importing test module already made.
if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_build_roof_check_')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import twin_build as tb  # noqa: E402
from services import twin_edit  # noqa: E402
from services import twin_store as ts  # noqa: E402
from services import twin_cost as tc, twin_reads  # noqa: E402
import test_twin_build as engine_tests  # noqa: E402
from test_twin_build import Reader, _accept_all, _pdf, check  # noqa: E402

RECORDED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_reads', 'recorded', 'claude')
NOT_CHECKED = 'The roofs could not be checked against the photos; they follow the drawings.'
ROOF_BEAT = re.compile(r'^Checking the roofs against the photos, (\d+):(\d\d) so far\.$')
NO_CORRECTIONS = {'changes': [], 'add': [], 'remove': [], 'notes': []}
DORMER = {'id': 'r_dormer', 'kind': 'gable', 'ridge': 'y', 'rect': [22.67, 13.33, 37.33, 26],
          'plate': 20, 'pitch': 12, 'overhang': 1}
CORRECTIONS = {'changes': [{'id': 'r_main', 'kind': 'hip', 'ridge': 'x'}], 'add': [copy.deepcopy(DORMER)],
               'remove': [], 'notes': ['The centre block is a hip with a front gable dormer.']}
READS = ('draft', 'draft_level', 'photo_map', 'roof_observe', 'draft_rooms')


# --- fixtures, reader and helpers ----------------------------------------------

def recorded(name):
    with open(os.path.join(RECORDED, name), encoding='utf-8') as f:
        return json.load(f)


def recorded_sections():
    return {s['id']: s for s in recorded('draft-main-house.json')['building']['roof']['sections']}


class RoofReader(Reader):
    """Answers the recorded main-house draft by kind, and the roof check with
    the given answer, or with roof_hook(run, images, context) when one is set
    (it may block, raise, or return a replacement answer)."""

    def __init__(self, roof_answer=None, roof_hook=None):
        super().__init__()
        self.draft = recorded('draft-main-house.json')
        self.roof_answer = copy.deepcopy(roof_answer)
        self.roof_hook = roof_hook
        self.kinds = []
        self.seen = []

    def __call__(self, kind, images, context, *, run, step):
        self.kinds.append(kind)
        self.seen.append({'kind': kind, 'step': step, 'images': len(images), 'context': copy.deepcopy(context)})
        if kind in ('draft', 'draft_level'):
            return copy.deepcopy(self.draft)
        if kind == 'draft_rooms':
            return {'rooms': [], 'walls': []}
        if kind == 'outline':
            return {'error': 'The model did not answer in 120 s.'}
        if kind == 'finishes':
            return {'materials': {}}
        if kind == 'photo_map':
            return {'from_side': 'front', 'blocks': [{'id': b['id'], 'sides': ['front']} for b in context['blocks']]}
        if kind == 'roof_observe':
            answer = self.roof_hook(run, images, context) if self.roof_hook else self.roof_answer
            return copy.deepcopy(answer) if answer is not None else {'blocks': {
                b['id']: {'sides': {side: {'kind': 'hidden'} for side in ('front', 'rear', 'left', 'right')}}
                for b in context['blocks']}}

        return super().__call__(kind, images, context, run=run, step=step)


def _jpeg():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (64, 48), (90, 120, 160)).save(buf, format='JPEG')
    return buf.getvalue()


def _main_house():
    """The Main house as the household set it up: two floor pages, a roof
    page and one tagged photo."""
    engine_tests._fresh()
    source = ts.save_source('drawing', 'house.pdf', _pdf(3))   # legacy upload: Main house, id house
    ts.set_page_roles([
        {'source': source, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None, 'building': 'house'},
        {'source': source, 'page': 2, 'role': 'floor', 'level': 'Second floor', 'box': None, 'building': 'house'},
        {'source': source, 'page': 3, 'role': 'roof', 'level': None, 'box': None, 'building': 'house'}])
    ts.save_source('photo', 'house.jpg', _jpeg(), part='house')
    return source


def _house():
    return next(b for b in ts.current()['buildings'] if b['id'] == 'house')


def _trouble(st):
    return [e for e in st['events'] if e['type'] in ('error', 'question')][-3:]


def _read_rect(section):
    return (section.get('read_geometry') or {}).get('rect') or section['rect']


def _at(house, rect, tol=0.05):
    """Roof sections read at rect (each coordinate within tol ft)."""
    return [s for s in house['roof']['sections']
            if all(abs(a - b) <= tol for a, b in zip(_read_rect(s), rect))]


def _roof(house):
    return sorted((s['kind'], s.get('ridge'), s.get('low_side'), [round(v, 2) for v in _read_rect(s)],
                   s.get('state')) for s in house['roof']['sections'])


def _order(reader):
    return [k for k in reader.kinds if k in READS]


def _build(reader):
    b = tb.start({'part': 'house'}, reader=reader, inline=True)
    st = _accept_all(b)
    check(st['state'] == 'done', ('the build finishes', st['state'], st.get('pause'), _trouble(st)))
    return b, st


def _roof_as_read(house, why):
    """Every recorded section is in the plan, settled, with its read kind and ridge."""
    wanted = recorded_sections()
    for sid, section in wanted.items():
        found = _at(house, section['rect'])
        check(len(found) == 1, (why, sid, 'is in the plan once', len(found), _roof(house)))
        got = found[0]
        check(got.get('state') != 'ghost', (why, sid, 'settles', got.get('why')))
        check((got['kind'], got.get('ridge'), got.get('low_side'))
              == (section['kind'], section.get('ridge'), section.get('low_side')),
              (why, sid, 'keeps the kind and ridge it was read with',
               (got['kind'], got.get('ridge'), got.get('low_side')), section))
    check(len(house['roof']['sections']) == len(wanted),
          (why, 'no section added or lost', len(house['roof']['sections']), _roof(house)))


# Background builds (copied from test_twin_build_draft_side.py).

def _events(run):
    """The build's events without the lock, safe from inside a reader call."""
    build = tb._BUILDS.get(run)
    return list(build['events']) if build else []


def _draft_settled(events):
    return [e for e in events if e['type'] == 'settled' and e.get('step') == 'draft']


def _wait(predicate, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _rest(b, timeout=60):
    """Wait until the build leaves running and its worker is no longer busy."""
    ok = _wait(lambda: tb.status(b)['state'] != 'running' and not tb._WORKERS.get(b, {}).get('busy'), timeout)
    check(ok, ('the build came to rest', tb.status(b)['state']))
    return tb.status(b)


def _finish(b, limit=20):
    for _ in range(limit):
        st = _rest(b)
        if st['state'] != 'paused':
            return st
        tb.answer(b, st['pause']['step'], {'accept': True})
    raise AssertionError('too many pauses')


def _fake_clock():
    now = [1000.0]
    saved = tb.__dict__.get('_clock', None)
    tb._clock = lambda: now[0]
    return now, saved


def _restore_clock(saved):
    if saved is None:
        tb.__dict__.pop('_clock', None)
    else:
        tb._clock = saved


# --- tests ---------------------------------------------------------------------

# R9: retired; covered by derivation and block-build ordering tests.


# R9: retired; covered by derivation and block-build ordering tests.


def test_roof_observe_heartbeat():
    _main_house()
    now, saved = _fake_clock()
    try:
        def roof_hook(run, images, context):
            # The roof observation is blocked for 20 s on the fake clock; at the 15 s
            # mark give the heartbeat a moment (real time) to go out.
            for elapsed in range(1, 21):
                now[0] += 1.0
                if elapsed == 15:
                    _wait(lambda: any(e['type'] == 'log' and ROOF_BEAT.match(e.get('text') or '')
                                      for e in _events(run)), 5)
                else:
                    time.sleep(0.005)
            return None

        reader = RoofReader(None, roof_hook=roof_hook)
        b = tb.start({'part': 'house'}, reader=reader, inline=False)
        st = _finish(b)
    finally:
        _restore_clock(saved)
    check(st['state'] == 'done', (st['state'], st.get('pause'), _trouble(st)))
    check(reader.kinds.count('roof_observe') == 1, ('test setup: the roof observation was read', reader.kinds))
    events = tb.status(b)['events']
    beats = [e for e in events if e['type'] == 'log' and ROOF_BEAT.match(e.get('text') or '')]
    logs = [e.get('text') for e in events if e['type'] == 'log']
    check(beats, ('20 s of roof observation: a heartbeat line checking photos', logs))
    times = [int(m.group(1)) * 60 + int(m.group(2)) for m in (ROOF_BEAT.match(e['text']) for e in beats)]
    check(all(15 <= t <= 21 for t in times), ('M:SS counts the roof observation so far', [e['text'] for e in beats]))
    check(all(e.get('step') == 'draft' for e in beats), ('the heartbeat belongs to the draft step', beats))
    settled = _draft_settled(events)
    check(settled and all(e['seq'] < settled[0]['seq'] for e in beats),
          ('the heartbeat runs before the draft settles', [e['seq'] for e in beats], settled[:1]))


def test_person_edited_section_left_alone():
    wanted = recorded_sections()
    _main_house()
    # A pre-block building has the old read sections; a first rebuild keeps edits.
    with patch.object(tb.twin_roof_derive, 'derive_roof', side_effect=RuntimeError('old draft')):
        b, _ = _build(RoofReader())
    mine = {}
    for sid in ('r_main', 'r_left'):
        found = _at(_house(), wanted[sid]['rect'])
        check(len(found) == 1, ('the original section settled', sid, _roof(_house())))
        twin_edit.save({'op': 'set', 'building': 'house', 'piece': found[0]['id'], 'field': 'pitch', 'value': 6}, 'p1')
        mine[sid] = found[0]['id']
    reader = RoofReader()
    tb.reread(b, 'draft', reader=reader, inline=True)
    check(tb.status(b)['state'] == 'done', tb.status(b)['state'])
    check(reader.kinds.count('roof_observe') == 1, reader.kinds)
    by_id = {s['id']: s for s in _house()['roof']['sections']}
    for sid, kind, ridge in (('r_main', 'gable', 'y'), ('r_left', 'gable', 'x')):
        piece = by_id.get(mine[sid])
        check(piece is not None, (sid, 'a person-edited section is never removed', _roof(_house())))
        check(piece['kind'] == kind and piece.get('ridge') == ridge and piece['pitch'] == 6
              and (piece.get('src') or {}).get('person'), (sid, 'a person edit never changes', piece))
        check(all(abs(a - b) <= .05 for a, b in zip(_read_rect(piece), wanted[sid]['rect'])),
              (sid, 'it keeps its place', _read_rect(piece)))
        check([s['id'] for s in _at(_house(), wanted[sid]['rect'], tol=1)] == [mine[sid]],
              (sid, 'no duplicate beside the person section', _roof(_house())))
    check(not _at(_house(), wanted['r_garage']['rect']), 'unprotected draft sections are replaced')


def test_roof_observe_failure_uses_drawings():
    def error_reply(run, images, context):
        return {'error': 'The model did not answer in 240 s.'}

    def raises(run, images, context):
        raise RuntimeError('the observation broke')

    for name, hook in (('error reply', error_reply), ('raises', raises)):
        _main_house()
        reader = RoofReader(roof_hook=hook)
        _, st = _build(reader)
        check(reader.kinds.count('roof_observe') == 1, (name, reader.kinds))
        check(st['state'] == 'done' and not _trouble(st), (name, st['state'], _trouble(st)))
        lines = [e for e in st['events'] if e['type'] == 'log' and e.get('text') == NOT_CHECKED]
        check(len(lines) == 1 and lines[0].get('step') == 'draft', (name, lines))
        check(_order(reader) == ['draft', 'photo_map', 'roof_observe', 'draft_rooms'], (name, reader.kinds))
        _roof_from_drawings(st)


def test_add_after_invalid_original_index():
    answer = {'changes': [], 'add': ['junk', copy.deepcopy(DORMER)], 'remove': []}
    before = copy.deepcopy(answer)
    fragment, problems = twin_reads.parse('roof_check', answer, {'sections': [{'id': 'r_main'}]})
    check(fragment.get('add') == [DORMER], ('a valid dormer after junk survives', fragment, problems))
    check(any(p.startswith('roof_check.add[0]:') for p in problems), problems)
    check(twin_reads._usable('roof_check', fragment, problems), ('the remaining dormer is usable', problems))
    check(answer == before, 'parsing never mutates the reply')
    # Duplicates also refer to original indices after earlier invalid entries.
    other = {**copy.deepcopy(DORMER), 'id': 'r_other'}
    answer['add'] += [copy.deepcopy(DORMER), {**DORMER, 'id': 'r_main'}, other]
    fragment, problems = twin_reads.parse('roof_check', answer, {'sections': [{'id': 'r_main'}]})
    check(fragment.get('add') == [DORMER, other], (fragment, problems))
    for i in (2, 3):
        check(any(p.startswith(f'roof_check.add[{i}]:') and 'duplicate' in p for p in problems), problems)


def test_failed_roof_observe_logs_once_across_cached_settles():
    _main_house()
    reader = RoofReader(roof_answer={'error': 'The roof observation timed out.'})
    bid, st = _build(reader)
    build = tb._BUILDS[bid]
    step = next(s for s in build['steps'] if s['kind'] == 'draft')
    for _ in range(2):
        result = json.loads(tb._cache_path(build, step).read_text(encoding='utf-8'))
        with ts.LIFECYCLE, tb._LOCK:
            tb._settle(build, step, result)
    lines = [e for e in build['events'] if e['type'] == 'log' and e.get('text') == NOT_CHECKED]
    check(len(lines) == 1, ('the same cached failure is logged once', lines))
    check(reader.kinds.count('roof_observe') == 1, 'settling a cached result never rereads')
    _roof_from_drawings(st)
    tb.reread(bid, 'draft', reader=reader, inline=True)
    check(tb.status(bid)['state'] == 'done', tb.status(bid)['state'])
    lines = [e for e in build['events'] if e['type'] == 'log' and e.get('text') == NOT_CHECKED]
    check(len(lines) == 2 and reader.kinds.count('roof_observe') == 2,
          ('a fresh read logs its own failure once', lines, reader.kinds))


def test_add_roof_when_draft_omits_roof():
    _main_house()
    reader = RoofReader()
    reader.draft['building'].pop('roof')
    bid, st = _build(reader)
    build = tb._BUILDS[bid]
    step = next(s for s in build['steps'] if s['kind'] == 'draft')
    result = json.loads(tb._cache_path(build, step).read_text(encoding='utf-8'))
    sections = result['fragment']['building']['roof']['sections']
    from services import twin_blocks
    blocks = twin_blocks.blocks(_house())
    check(len(sections) == len(blocks) > 0, ('every block gets a roof', sections, blocks))
    for block in blocks:
        found = _at(_house(), block['rect'], tol=1)
        check(len(found) == 1 and found[0]['kind'] == 'gable' and found[0].get('state') != 'ghost', found)
    emitted = [p for e in st['events'] if e['type'] == 'settled' and e.get('step') == 'draft'
               for p in e['pieces'] if p.get('src', {}).get('step') == 'roof_blocks']
    check(len(emitted) == len(blocks), ('derived roofs appear in the draft settlement event', emitted))


def test_derive_exceptions_keep_original_draft():
    _main_house()
    reader = RoofReader()
    with patch.object(tb.twin_roof_derive, 'derive_roof', side_effect=RuntimeError('derivation failed')) as derive:
        bid, st = _build(reader)
    check(derive.call_count == 1, 'the failure path ran')
    check(not _trouble(st), _trouble(st))
    text = 'The roofs could not be built from the walls; they are shown as first read.'
    check(sum(e.get('text') == text for e in st['events']) == 1, st['events'])
    check(_order(reader) == ['draft', 'photo_map', 'roof_observe', 'draft_rooms'], reader.kinds)
    _roof_as_read(_house(), 'derive exception')
    build = tb._BUILDS[bid]
    step = next(s for s in build['steps'] if s['kind'] == 'draft')
    for _ in range(2):
        result = json.loads(tb._cache_path(build, step).read_text(encoding='utf-8'))
        with ts.LIFECYCLE, tb._LOCK:
            tb._settle(build, step, result)
    check(sum(e.get('text') == text for e in build['events']) == 1, build['events'])


def test_no_photos_skips_reads_and_cost():
    engine_tests._fresh()
    source = ts.save_source('drawing', 'floors.pdf', _pdf(2))
    ts.set_page_roles([
        {'source': source, 'page': i, 'role': 'floor', 'level': name, 'box': None, 'building': 'house'}
        for i, name in ((1, 'Main floor'), (2, 'Second floor'))])
    reader = RoofReader()
    checks = []
    real = tc.require_clear

    def checkpoint():
        build = next(iter(tb._BUILDS.values()))
        stages = [e['step'] for e in build['events'] if e['type'] == 'stage']
        checks.append(stages[-1])
        return real()

    with patch.object(tc, 'require_clear', side_effect=checkpoint):
        bid, st = _build(reader)
    check(_order(reader) == ['draft', 'draft_rooms'], ('no image-less paid read', reader.kinds))
    check(checks.count('draft') == 1, ('no roof-check spend checkpoint', checks))
    step = next(s for s in st['steps'] if s['kind'] == 'draft')
    check(step['estimate'] == tc.estimate('draft', 2) + tc.estimate('outline', 1), step)
    check(not any(e.get('text') == NOT_CHECKED for e in st['events']), st['events'])
    check(tc.entries() == [], 'stub reads and a skipped roof check incur no cost')
    _roof_from_drawings(st)
    build = tb._BUILDS[bid]
    result = json.loads(tb._cache_path(build, step).read_text(encoding='utf-8'))
    check(not result['roof_blocks'].get('error') and not result.get('roof_blocks_pending'), result)
    check('roof_check' not in result and not result['roof_blocks']['maps'], result)


def _roof_from_drawings(st):
    from services import twin_blocks
    blocks = twin_blocks.blocks(_house())
    flags = next(s for s in st['steps'] if s['kind'] == 'draft')['roof_flags']
    for block in blocks:
        found = _at(_house(), block['rect'], tol=1)
        check(len(found) == 1 and found[0]['kind'] == 'gable' and found[0].get('state') != 'ghost', found)
        check(any(f['block_rect'] == block['rect'] for f in flags), ('every block flagged', block, flags))


def test_photo_map_failure_uses_drawings():
    _main_house()
    class FailedMap(RoofReader):
        def __call__(self, kind, images, context, **kwargs):
            if kind == 'photo_map':
                self.kinds.append(kind)
                return {'error': 'map failed'}
            return super().__call__(kind, images, context, **kwargs)
    reader = FailedMap()
    _, st = _build(reader)
    check(not _trouble(st) and 'roof_observe' not in reader.kinds, (reader.kinds, _trouble(st)))
    check(sum(e.get('text') == NOT_CHECKED for e in st['events']) == 1, st['events'])
    _roof_from_drawings(st)


def test_two_photo_kinds_become_conflict_before_derive():
    context = {'blocks': [{'id': 'A', 'rect': [0, 0, 20, 20]}]}
    answer = {'blocks': {'A': {'sides': {'left': [
        {'kind': 'gable_end', 'photo': 0}, {'kind': 'slope', 'photo': 1}]}}}}
    before = copy.deepcopy(answer)
    # The real reader parses once too; preserve all reports until wiring combines them.
    parsed, problems = twin_reads.parse('roof_observe', answer, context)
    check(not problems and parsed == answer, (parsed, problems))
    observations, problems = tb._roof_observations(parsed, context)
    check(not problems and observations['blocks']['A']['sides']['left']['kind'] == 'conflict', observations)
    check(answer == before, 'combining does not mutate the reply')
    _main_house()
    class ConflictReader(RoofReader):
        def __call__(self, kind, images, context, **kwargs):
            out = super().__call__(kind, images, context, **kwargs)
            if kind == 'roof_observe':
                for block in out['blocks'].values():
                    block['sides']['left'] = copy.deepcopy(answer['blocks']['A']['sides']['left'])
            return out
    real = tb.twin_roof_derive.derive_roof
    seen = []
    def derive(blocks, observations, evidence, choices):
        seen.append(copy.deepcopy(observations))
        return real(blocks, observations, evidence, choices)
    with patch.object(tb.twin_roof_derive, 'derive_roof', side_effect=derive):
        _, st = _build(ConflictReader())
    check(seen and all(b['sides']['left']['kind'] == 'conflict' for b in seen[0].values()), seen)
    check(any('looks different between photos' in f['text']
              for f in next(s for s in st['steps'] if s['kind'] == 'draft')['roof_flags']), st['steps'])


def test_photo_selection_uses_coverage():
    mapped = [{'fragment': {'from_side': 'front', 'blocks': [{'id': 'A', 'sides': ['front']}]}} for _ in range(9)]
    mapped[-1]['fragment']['blocks'] = [{'id': 'B', 'sides': ['rear', 'left']}]
    selected = tb._roof_photo_selection(mapped)
    check(len(selected) == 8 and 8 in selected and 0 in selected, selected)


def test_checkpoint_keeps_paid_photo_maps():
    _main_house()
    reader = RoofReader()
    real = tc.require_clear
    calls = []

    def checkpoint():
        calls.append(True)
        if len(calls) == 3:
            raise tc.CheckpointReached(10, 10)
        return real()

    with patch.object(tc, 'require_clear', side_effect=checkpoint):
        bid = tb.start({'part': 'house'}, reader=reader, inline=True)
    check(tb.status(bid)['state'] == 'checkpoint', tb.status(bid)['state'])
    check(_order(reader) == ['draft', 'photo_map'], reader.kinds)
    tb.resume(bid, reader=reader, inline=True)
    check(tb.status(bid)['state'] == 'done', tb.status(bid)['state'])
    check(_order(reader) == ['draft', 'photo_map', 'roof_observe', 'draft_rooms'],
          ('resuming keeps both paid replies', reader.kinds))


def test_stored_block_choices_reach_derivation():
    _main_house()
    bid, _ = _build(RoofReader())
    target = next(s for s in _house()['roof']['sections'] if s.get('block') and s.get('level') == 'L2')
    choice = {'rect': copy.deepcopy(target['block']), 'kind': 'hip', 'ridge': 'x', 'pitch': 5,
              'ends': {'x0': 'hip', 'x1': 'hip'}, 'plate': 20, 'overhang': 2}

    def choose(plan):
        next(b for b in plan['buildings'] if b['id'] == 'house')['roof']['choices'] = [choice]
        return plan

    ts.update_current(choose, kind='edit')
    reader = RoofReader()
    tb.reread(bid, 'draft', reader=reader, inline=True)
    st = tb.status(bid)
    check(st['state'] == 'done', st['state'])
    found = _at(_house(), choice['rect'], tol=1)
    check(len(found) == 1, found)
    # The flat view omits ends that match the section kind (R51), so read
    # them with the kind as the default.
    got = dict(found[0], ends=found[0].get('ends', {side: found[0]['kind'] for side in choice['ends']}))
    for field in ('kind', 'ridge', 'pitch', 'ends', 'plate', 'overhang'):
        check(got[field] == choice[field], (field, found[0], choice))
    flags = next(s for s in st['steps'] if s['kind'] == 'draft')['roof_flags']
    check(not any(f['block_rect'] == choice['rect'] for f in flags), ('person choices are never flagged', flags))


TESTS = (
    test_roof_observe_heartbeat,
    test_person_edited_section_left_alone,
    test_roof_observe_failure_uses_drawings,
    test_add_after_invalid_original_index,
    test_failed_roof_observe_logs_once_across_cached_settles,
    test_add_roof_when_draft_omits_roof,
    test_derive_exceptions_keep_original_draft,
    test_no_photos_skips_reads_and_cost,
    test_photo_map_failure_uses_drawings,
    test_two_photo_kinds_become_conflict_before_derive,
    test_photo_selection_uses_coverage,
    test_checkpoint_keeps_paid_photo_maps,
    test_stored_block_choices_reach_derivation,
)


if __name__ == '__main__':
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, type(exc).__name__, ' '.join(str(exc).split())[:400])
            if not isinstance(exc, AssertionError):
                traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} passed')
    sys.exit(1 if failed else 0)

"""The draft's roof comes from the blocks and the photos (brief
.superpowers/sdd/2026-11-08-house-editor-roofs-from-photos/task-5-brief.md;
spec docs/superpowers/specs/2026-11-08-house-editor-roofs-from-photos-design.md
sections 2, 3, 6 and 8).

In the draft step, after the draft fragment is merged (or after the per-level
fallback), the build computes blocks (services.twin_blocks), runs one
'photo_map' read per tagged photo (images: the block diagram PNG, then that
photo), then one 'roof_observe' read (images: the block diagram, then the
photos in order; context['photo_map'] keyed by zero-based photo index), builds
plan evidence from the draft's roof sections, calls
services.twin_roof_derive.derive_roof and replaces every draft roof section
that is not a porch roof and has no src.person with the derived sections.
Extensions (the awning) are kept. Each flag is logged once, plainly, and the
flags are stored on the draft step. roof_check is no longer called.
require_clear() runs before each read.

Flags on the step: step['roof_flags'] is a list of {block_rect, text, ...},
the same shape the build status exposes in Task 6 (plan Task 6 Interfaces:
roof_flags: [{block_rect, text}]).

The reader is a stub keyed by kind (built on test_twin_build's fake, as
test_twin_build_roof_check.py does): 'draft' and 'draft_level' answer the
recorded household draft (draft-main-house.json), 'draft_rooms' no rooms,
'outline' an error (the first look is disposable), 'finishes' no materials,
'photo_map' a per-photo answer chosen by which photo it is shown, and
'roof_observe' the household's round-2 observations with the third garage
corrected (tests/test_twin_roof_derive.py, test_household_truth), keyed by
the block ids the build supplies in context['blocks'] (matched to the
household blocks by rect). 'roof_check' answers no corrections, so the
current code runs through and the tests fail on the missing wiring.

Photos: front 22, right 26, left 23 and rear 20, as on the device; a pool-house
photo tagged to the main house stands in for Review Focus 2.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_build_roof_blocks.py
"""
import copy
import io
import json
import os
import re
import sys
import tempfile
import traceback
from unittest.mock import patch

# Always a scratch data dir (the engine harness wipes its data dir); keep one
# an importing test module already made.
if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_build_roof_blocks_')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import twin_build as tb  # noqa: E402
from services import twin_store as ts  # noqa: E402
from services import twin_cost as tc  # noqa: E402
from services import twin_blocks, twin_plan  # noqa: E402
import test_twin_build as engine_tests  # noqa: E402
from test_twin_build import Reader, _pdf, check  # noqa: E402
from test_twin_roof_derive import HOUSE, _house_observations  # noqa: E402

RECORDED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_reads', 'recorded', 'claude')
READS = ('draft', 'draft_level', 'photo_map', 'roof_observe', 'roof_check', 'draft_rooms')
NO_CORRECTIONS = {'changes': [], 'add': [], 'remove': [], 'notes': []}
HIDDEN = {'front': {'kind': 'hidden'}, 'rear': {'kind': 'hidden'},
          'left': {'kind': 'hidden'}, 'right': {'kind': 'hidden'}}
TOL = 1.0

# The household's blocks by the spike's letters (test_twin_roof_derive.HOUSE):
# A middle, B right upper, C left wing, D garage front, E rear right, F third garage.
TRUTH = {b['id']: b['rect'] for b in HOUSE}

# Porch roofs as read (draft-main-house.json): kept, never replaced.
PORCH_ROOFS = {'r_porch_shed': ('shed', None, 'y0', [14.33, 6.33, 37, 13.33]),
               'r_porch_gable': ('gable', 'y', None, [14.33, 6.33, 23.5, 14.33]),
               'r_screen': ('gable', 'y', None, [14.33, 50, 31, 66])}
# Draft sections that are not porch roofs and must not survive at their read rects.
REPLACED = {'r_garage': [37, 0, 59, 30], 'r_side': [57, 22, 70, 42],
            'r_rear': [43.33, 40, 59, 65.33], 'r_bkfst': [31, 48, 43.33, 59]}

COLOURS = {'front': (200, 60, 60), 'right': (60, 200, 60), 'left': (60, 60, 200),
           'rear': (200, 200, 60), 'pool': (60, 200, 200)}
HOUSE_PHOTOS = ('front', 'right', 'left', 'rear')
# What each photo shows, by the spike's block letters, left to right in the photo.
PHOTO_MAPS = {
    'front': ('front', [('C', ['front']), ('A', ['front']), ('B', ['front']), ('D', ['front', 'left']),
                        ('F', ['front'])]),
    'right': ('right', [('D', ['right']), ('F', ['right']), ('E', ['right'])]),
    'left': ('left', [('C', ['left', 'front']), ('A', ['left'])]),
    'rear': ('rear', [('E', ['rear', 'left']), ('A', ['rear']), ('C', ['rear'])]),
}


# --- fixtures, reader and helpers ----------------------------------------------

def recorded(name):
    with open(os.path.join(RECORDED, name), encoding='utf-8') as f:
        return json.load(f)


def _fixture_blocks():
    """The household's blocks from the recorded draft, as test_twin_blocks builds them."""
    plan, _ = twin_plan.normalize({'units': 'ft', 'buildings': [recorded('draft-main-house.json')['building']]})
    return twin_blocks.blocks(plan['buildings'][0])


def _near(rect, want, tol=TOL):
    return (isinstance(rect, (list, tuple)) and len(rect) == 4
            and all(abs(float(a) - float(b)) <= tol for a, b in zip(rect, want)))


def _letter(rect):
    """The spike letter of the household block at rect, or None (a sliver)."""
    best = None
    for letter, want in TRUTH.items():
        gap = max(abs(float(a) - float(b)) for a, b in zip(rect, want))
        if gap <= 1.5 and (best is None or gap < best[0]):
            best = (gap, letter)
    return best[1] if best else None


def _observations(**overrides):
    """Round-2 observations (the third garage corrected); the middle's front
    dormer carries the rough centre and width the read asks for."""
    obs = _house_observations()
    obs['A']['sides']['front'] = {'kind': 'dormer', 'centre': 30, 'width': 15}
    for letter, value in overrides.items():
        obs[letter] = value
    return obs


def _jpeg(colour):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (64, 48), colour).save(buf, format='JPEG')
    return buf.getvalue()


class BlocksReader(Reader):
    """Answers the recorded household draft by kind; photo_map by which photo
    it is shown; roof_observe with the given observations by block rect."""

    def __init__(self, labels, observations=None, trace=None):
        super().__init__()
        self.draft = recorded('draft-main-house.json')
        self.labels = labels                     # photo b64 -> label
        self.observations = _observations() if observations is None else observations
        self.trace = trace
        self.kinds = []
        self.seen = []

    def _ids(self, context):
        return {_letter(b['rect']): b['id'] for b in context.get('blocks') or []
                if isinstance(b, dict) and _letter(b.get('rect') or [0, 0, 0, 0])}

    def __call__(self, kind, images, context, *, run, step):
        self.kinds.append(kind)
        if self.trace is not None and kind != 'outline':
            self.trace.append(kind)
        self.seen.append({'kind': kind, 'step': step, 'images': len(images),
                          'mimes': [i.get('mime') for i in images],
                          'photos': [self.labels.get(i.get('b64')) for i in images],
                          'context': copy.deepcopy(context)})
        if kind in ('draft', 'draft_level'):
            return copy.deepcopy(self.draft)
        if kind == 'draft_rooms':
            return {'rooms': [], 'walls': []}
        if kind == 'outline':
            return {'error': 'The model did not answer in 120 s.'}
        if kind == 'finishes':
            return {'materials': {}}
        if kind == 'roof_check':
            return copy.deepcopy(NO_CORRECTIONS)
        if kind == 'photo_map':
            label = self.labels.get(images[-1].get('b64')) if images else None
            if label not in PHOTO_MAPS:
                return {'from_side': 'none', 'blocks': []}
            ids = self._ids(context)
            side, blocks = PHOTO_MAPS[label]
            return {'from_side': side, 'blocks': [{'id': ids[letter], 'sides': list(sides)}
                                                  for letter, sides in blocks if letter in ids]}
        if kind == 'roof_observe':
            out = {}
            for b in context.get('blocks') or []:
                letter = _letter(b['rect'])
                out[b['id']] = copy.deepcopy(self.observations.get(letter, {'sides': HIDDEN}))
            return {'blocks': out}
        return super().__call__(kind, images, context, run=run, step=step)


def _main_house(photos=HOUSE_PHOTOS):
    """The Main house as the household set it up: two floor pages, a roof page
    and the given tagged photos. Returns {photo b64: label}."""
    engine_tests._fresh()
    source = ts.save_source('drawing', 'house.pdf', _pdf(3))   # legacy upload: Main house, id house
    ts.set_page_roles([
        {'source': source, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None, 'building': 'house'},
        {'source': source, 'page': 2, 'role': 'floor', 'level': 'Second floor', 'box': None, 'building': 'house'},
        {'source': source, 'page': 3, 'role': 'roof', 'level': None, 'box': None, 'building': 'house'}])
    labels = {}
    for label in photos:
        sid = ts.save_source('photo', f'{label}.jpg', _jpeg(COLOURS[label]), part='house')
        labels[ts.source_images(sid)[0]['b64']] = label
    check(len(labels) == len(photos), ('test setup: every photo is its own image', len(labels)))
    return labels


def _house():
    return next(b for b in ts.current()['buildings'] if b['id'] == 'house')


def _trouble(st):
    return [e for e in st['events'] if e['type'] in ('error', 'question')][-3:]


def _read_rect(section):
    return (section.get('read_geometry') or {}).get('rect') or section['rect']


def _at(house, rect, tol=0.05):
    return [s for s in house['roof']['sections'] if _near(_read_rect(s), rect, tol)]


def _roof(house):
    return sorted((s['kind'], s.get('ridge'), s.get('low_side'), [round(v, 2) for v in _read_rect(s)],
                   s.get('ends'), s.get('state')) for s in house['roof']['sections'])


def _end(section, end):
    ends = section.get('ends') or {}
    return ends.get(end, 'hip' if section['kind'] == 'hip' else 'gable')


def _order(reader):
    return [k for k in reader.kinds if k in READS]


def _calls(reader, kind):
    return [c for c in reader.seen if c['kind'] == kind]


def _build(reader):
    """Inline build with no pauses expected: a flag never pauses."""
    b = tb.start({'part': 'house'}, reader=reader, inline=True)
    st = tb.status(b)
    check(st['state'] == 'done', ('the build finishes without a pause', st['state'], st.get('pause'), _trouble(st)))
    return b, st


def _draft_step(st):
    return next(s for s in st['steps'] if s['kind'] == 'draft')


def _flags(st):
    flags = _draft_step(st).get('roof_flags')
    check(isinstance(flags, list), ('the draft step stores its roof flags as step["roof_flags"]',
                                    sorted(_draft_step(st))))
    for f in flags:
        rect = f.get('block_rect') if isinstance(f, dict) else None
        check(isinstance(f, dict) and isinstance(f.get('text'), str) and isinstance(rect, (list, tuple))
              and len(rect) == 4 and all(isinstance(v, (int, float)) for v in rect),
              ('each flag is {block_rect, text}', f))
    return flags


def _flag_for(flags, rect):
    return [f for f in flags if _near(f['block_rect'], rect)]


def _plain(flags, blocks):
    ids = {b['id']: b['rect'] for b in blocks}
    for f in flags:
        text = f['text']
        check(text.strip() and text[0].isupper() and text.rstrip()[-1] in '.!?', ('a flag is a plain sentence', text))
        check('roof-' not in text and not re.search(r'\b[Bb]lock [A-Z]\b', text)
              and not re.search(r'[\[\]{}_=<>|]', text), ('a flag names no id', text))
        own = next((bid for bid, rect in ids.items() if _near(f['block_rect'], rect)), None)
        if own and own != 'A':   # 'A' is also the article
            check(not re.search(rf'\b{own}\b', text), ('a flag names no block letter', text))


def _logged_once(build_events, flags, why):
    """Each flag has its one plain line: a text is logged at least once and
    never more often than flags carry it. Returns the counts."""
    lines = [e for e in build_events if e['type'] == 'log']
    counts = {}
    for text in sorted({f['text'] for f in flags}):
        hits = [e for e in lines if e.get('text') == text]
        carried = sum(f['text'] == text for f in flags)
        check(1 <= len(hits) <= carried, (why, 'each flag is logged once', text, len(hits), carried))
        check(all(e.get('step') == 'draft' for e in hits), (why, 'the flag line belongs to the draft step', hits))
        counts[text] = len(hits)
    return counts


def _main_sections(house):
    """The one main section over each household block, by spike letter."""
    out = {}
    for letter, rect in TRUTH.items():
        found = [s for s in house['roof']['sections'] if _near(_read_rect(s), rect)]
        check(len(found) == 1, ('one roof section over the block', letter, rect, _roof(house)))
        check(found[0].get('state') != 'ghost', ('the derived section settles', letter, found[0].get('why')))
        out[letter] = found[0]
    return out


def _no_hip(house):
    for s in house['roof']['sections']:
        check(s['kind'] != 'hip' and 'hip' not in (s.get('ends') or {}).values(),
              ('there are no hips anywhere', s['kind'], s.get('ends'), _read_rect(s)))


def _map_entries(call, labels_by_photo=None):
    """roof_observe's photo_map as [(label of the photo at that index, entry)]."""
    photo_map = call['context'].get('photo_map')
    check(isinstance(photo_map, dict), ('roof_observe gets the photo map in context["photo_map"]',
                                        sorted(call['context'])))
    out = []
    for key, entry in photo_map.items():
        index = int(key)
        check(0 <= index and 1 + index < call['images'],
              ('a photo map index names a photo among roof_observe\'s images', key, call['images']))
        out.append((call['photos'][1 + index], entry))
    return out


def _check_entry(label, entry, ids):
    """The entry for the photo at that index is that photo's own answer, never another's."""
    side, blocks = PHOTO_MAPS[label]
    check(isinstance(entry, dict) and entry.get('from_side') == side,
          ('the map entry is the answer for the photo at that index', label, entry))
    check([b.get('id') for b in entry.get('blocks') or []] == [ids[l] for l, _ in blocks if l in ids],
          ('the map entry lists that photo\'s blocks in order', label, entry))


# --- tests ---------------------------------------------------------------------

def test_reads_in_order():
    labels = _main_house()
    reader = BlocksReader(labels)
    _build(reader)
    check(_order(reader) == ['draft', 'photo_map', 'photo_map', 'photo_map', 'photo_map', 'roof_observe',
                             'draft_rooms'],
          ('the reads go draft, photo_map once per photo, roof_observe, draft_rooms; no roof_check', reader.kinds))
    check('roof_check' not in reader.kinds, ('roof_check is no longer called', reader.kinds))
    blocks = _fixture_blocks()
    maps = _calls(reader, 'photo_map')
    for call in maps:
        check(call['step'] == 'draft', ('photo_map runs inside the draft step', call['step']))
        check(call['images'] == 2 and call['mimes'][0] == 'image/png' and call['photos'][1] in HOUSE_PHOTOS,
              ('photo_map sees the block diagram, then one photo', call['mimes'], call['photos']))
        given = [b.get('rect') for b in call['context'].get('blocks') or []]
        check(all(any(_near(r, b['rect']) for r in given) for b in blocks),
              ('photo_map context["blocks"] holds every block with its rect', given))
    check(sorted(c['photos'][1] for c in maps) == sorted(HOUSE_PHOTOS),
          ('each photo is mapped once', [c['photos'] for c in maps]))
    observe = _calls(reader, 'roof_observe')[0]
    check(observe['step'] == 'draft', ('roof_observe runs inside the draft step', observe['step']))
    check(observe['images'] == 1 + len(HOUSE_PHOTOS) and observe['mimes'][0] == 'image/png'
          and sorted(observe['photos'][1:]) == sorted(HOUSE_PHOTOS),
          ('roof_observe sees the block diagram, then the photos', observe['mimes'], observe['photos']))
    given = observe['context'].get('blocks') or []
    check(all(any(_near(g.get('rect'), b['rect']) for g in given) for b in blocks),
          ('roof_observe context["blocks"] holds every block', given))
    ids = {_letter(g['rect']): g['id'] for g in given if _letter(g['rect'])}
    entries = _map_entries(observe)
    check(sorted(label for label, _ in entries) == sorted(HOUSE_PHOTOS),
          ('every photo is in the map once', [label for label, _ in entries]))
    for label, entry in entries:
        _check_entry(label, entry, ids)


def test_derived_roof_replaces_draft_roof():
    labels = _main_house()
    reader = BlocksReader(labels)
    _build(reader)
    house = _house()
    _no_hip(house)
    by = _main_sections(house)
    # Middle: side gable, gable end on its left.
    check((by['A']['kind'], by['A'].get('ridge')) == ('gable', 'x') and _end(by['A'], 'x0') == 'gable',
          ('the middle is a side gable with its gable end on the left', by['A']))
    # Left wing: side gable, gable end facing left.
    check((by['C']['kind'], by['C'].get('ridge')) == ('gable', 'x') and _end(by['C'], 'x0') == 'gable',
          ('the left wing is a side gable facing left', by['C']))
    # Right upper: side gable (the draft read it as a hip).
    check((by['B']['kind'], by['B'].get('ridge')) == ('gable', 'x'), ('the right upper is a side gable', by['B']))
    # Garage wing: front-facing gable.
    check((by['D']['kind'], by['D'].get('ridge')) == ('gable', 'y') and _end(by['D'], 'y0') == 'gable',
          ('the garage wing is a front-facing gable', by['D']))
    # Third garage: gable end to the right, ridge parallel to the street.
    check((by['F']['kind'], by['F'].get('ridge')) == ('gable', 'x') and _end(by['F'], 'x1') == 'gable',
          ('the third garage has its gable end to the right, ridge along the street', by['F']))
    # The front dormer over the upper windows: centre about 30, about 15 wide.
    dormers = [s for s in house['roof']['sections'] if s['kind'] == 'gable' and s.get('ridge') == 'y'
               and abs(s['plate'] - 20) <= 0.01 and _read_rect(s)[1] <= 14.5
               and abs((_read_rect(s)[0] + _read_rect(s)[2]) / 2 - 30) <= 1]
    check(len(dormers) == 1, ('the middle has one front gable dormer at about 30 ft', _roof(house)))
    d = _read_rect(dormers[0])
    check(abs((d[2] - d[0]) - 15) <= 1 and dormers[0].get('state') != 'ghost',
          ('the dormer is about 15 ft wide and settles', d, dormers[0].get('why')))

    # Porch roofs stay as read.
    for sid, (kind, ridge, low, rect) in PORCH_ROOFS.items():
        found = _at(house, rect)
        check(len(found) == 1, ('a porch roof is kept', sid, _roof(house)))
        check((found[0]['kind'], found[0].get('ridge'), found[0].get('low_side')) == (kind, ridge, low)
              and found[0].get('state') != 'ghost', ('the porch roof keeps its read form', sid, found[0]))
    # The other draft sections are replaced, not kept beside the derived ones.
    for sid, rect in REPLACED.items():
        check(not _at(house, rect), ('a draft roof section is replaced by the derived roof', sid, _roof(house)))
    # The awning stays, on the derived garage roof.
    awnings = [e for e in house['roof'].get('extensions', []) if e.get('kind') == 'awning']
    check(len(awnings) == 1 and awnings[0].get('state') != 'ghost',
          ('the awning is kept', house['roof'].get('extensions')))
    host = next((s for s in house['roof']['sections'] if s['id'] == awnings[0].get('section')), None)
    check(host is not None, ('the awning names a roof section that exists', awnings[0], _roof(house)))
    check(host is by['D'], ('the awning sits on the derived garage roof', _read_rect(host), _read_rect(by['D'])))


def test_no_photos_no_reads():
    _main_house(photos=())
    trace = []
    real = tc.require_clear

    def counted():
        trace.append('clear')
        return real()

    reader = BlocksReader({}, trace=trace)
    with patch.object(tc, 'require_clear', side_effect=counted):
        b, st = _build(reader)
    check(_order(reader) == ['draft', 'draft_rooms'],
          ('no photos: no photo_map, no roof_observe, no roof_check', reader.kinds))
    check(trace[:4] == ['clear', 'draft', 'clear', 'draft_rooms'],
          ('nothing is checked or spent for a photo read', trace))
    step = _draft_step(st)
    check(abs(step['estimate'] - (tc.estimate('draft', 3) + tc.estimate('outline', 1))) < 0.005,
          ('the estimate is the draft and the first look only', step['estimate']))
    check(tc.entries() == [], 'no cost is recorded')

    house = _house()
    _no_hip(house)
    by = _main_sections(house)
    # The plan evidence decides the ridge: the draft section that overlaps the block most.
    for letter, ridge in (('A', 'y'), ('B', 'x'), ('C', 'x'), ('D', 'y'), ('E', 'y'), ('F', 'x')):
        check((by[letter]['kind'], by[letter].get('ridge')) == ('gable', ridge),
              ('with no photos the plan gives the ridge and every end is a gable', letter,
               by[letter]['kind'], by[letter].get('ridge')))
    flags = _flags(st)
    blocks = _fixture_blocks()
    for blk in blocks:
        check(_flag_for(flags, blk['rect']), ('every block is flagged', blk['id'], blk['rect'], flags))
    _plain(flags, blocks)
    _logged_once(st['events'], flags, 'no photos')


def test_unrelated_photo_ignored():
    labels = _main_house(photos=('front', 'pool', 'right', 'left', 'rear'))
    pool = next(b64 for b64, label in labels.items() if label == 'pool')
    reader = BlocksReader(labels)
    _build(reader)
    maps = _calls(reader, 'photo_map')
    check(sorted(c['photos'][1] for c in maps) == sorted(labels.values()),
          ('every tagged photo, the pool-house one too, gets a photo_map read', [c['photos'] for c in maps]))
    observe = _calls(reader, 'roof_observe')
    check(len(observe) == 1, ('one roof_observe read', reader.kinds))
    ids = {_letter(g['rect']): g['id'] for g in observe[0]['context'].get('blocks') or [] if _letter(g['rect'])}
    entries = _map_entries(observe[0])
    check('pool' not in [label for label, _ in entries],
          ('the photo that shows none of the blocks is left out of the map', [label for label, _ in entries]))
    check(sorted(label for label, _ in entries) == sorted(HOUSE_PHOTOS),
          ('the four house photos stay in the map', [label for label, _ in entries]))
    for label, entry in entries:
        check(entry.get('from_side') != 'none' and entry.get('blocks'),
              ('no map entry says it shows nothing', label, entry))
        _check_entry(label, entry, ids)
    check(pool in labels, 'test setup')
    # It is ignored, never mapped wrongly: the roof still comes out right.
    house = _house()
    _no_hip(house)
    by = _main_sections(house)
    check((by['A'].get('ridge'), by['F'].get('ridge'), by['D'].get('ridge')) == ('x', 'x', 'y'),
          ('the roof is derived from the house photos', _roof(house)))


def test_unseen_end_flagged_never_pauses():
    labels = _main_house()
    # The third garage: only its front slope is seen; its right end is not.
    third = {'sides': {**copy.deepcopy(HIDDEN), 'front': {'kind': 'slope'}}, 'pitch': 8,
             'slope_vs_neighbours': 'same'}
    reader = BlocksReader(labels, observations=_observations(F=third))
    bid, st = _build(reader)
    check(not _trouble(st) and st.get('pause') is None, ('a flag never pauses or asks', _trouble(st), st.get('pause')))
    house = _house()
    by = _main_sections(house)
    f = by['F']
    check((f['kind'], f.get('ridge')) == ('gable', 'x') and _end(f, 'x1') == 'gable',
          ('the unseen right end is made a gable', f['kind'], f.get('ridge'), f.get('ends')))
    flags = _flags(st)
    mine = _flag_for(flags, TRUTH['F'])
    check(mine, ('the third garage is flagged', flags))
    # The right upper's ends were never seen either.
    check(_flag_for(flags, TRUTH['B']), ('the right upper is flagged', flags))
    blocks = _fixture_blocks()
    _plain(flags, blocks)
    first = _logged_once(st['events'], flags, 'first settle')

    # Settling the cached draft again never logs a flag twice.
    build = tb._BUILDS[bid]
    step = next(s for s in build['steps'] if s['kind'] == 'draft')
    for _ in range(2):
        result = json.loads(tb._cache_path(build, step).read_text(encoding='utf-8'))
        with ts.LIFECYCLE, tb._LOCK:
            tb._settle(build, step, result)
    again = _logged_once(build['events'], flags, 'repeated settles')
    check(again == first, ('settling the cached draft again logs no flag line again', first, again))
    check(reader.kinds.count('roof_observe') == 1, ('settling a cached result never rereads', reader.kinds))


def test_estimate_and_checkpoint():
    labels = _main_house()
    trace = []
    real = tc.require_clear

    def counted():
        trace.append('clear')
        return real()

    reader = BlocksReader(labels, trace=trace)
    with patch.object(tc, 'require_clear', side_effect=counted):
        _, st = _build(reader)
    end = trace.index('draft_rooms') + 1 if 'draft_rooms' in trace else len(trace)
    check(trace[:end] == ['clear', 'draft'] + ['clear', 'photo_map'] * len(HOUSE_PHOTOS)
          + ['clear', 'roof_observe', 'clear', 'draft_rooms'],
          ('one require_clear before each read', trace[:end]))

    draft = _calls(reader, 'draft')[0]
    maps = _calls(reader, 'photo_map')
    observe = _calls(reader, 'roof_observe')
    check(len(maps) == len(HOUSE_PHOTOS) and len(observe) == 1, ('test setup: the photo reads ran', reader.kinds))
    photo_map = sum(tc.estimate('photo_map', c['images']) for c in maps)
    roof_observe = tc.estimate('roof_observe', observe[0]['images'])
    wanted = tc.estimate('draft', draft['images']) + tc.estimate('outline', 1) + photo_map + roof_observe
    step = _draft_step(st)
    check(isinstance(step.get('estimate'), (int, float)) and abs(step['estimate'] - wanted) < 0.005,
          ('the draft step estimate is draft + first look + photo_map per photo + roof_observe, no roof_check',
           step.get('estimate'), wanted))

    # The sheets estimate (main._house_editor_sheets, called directly) carries the same reads.
    import main
    build_estimate = main._house_editor_sheets()['estimates']['build']['house']
    check('roof_check' not in build_estimate, ('the build estimate drops roof_check', build_estimate))
    check(abs(build_estimate.get('photo_map', -1) - photo_map) < 0.005
          and abs(build_estimate.get('roof_observe', -1) - roof_observe) < 0.005,
          ('the build estimate has photo_map per photo and roof_observe', build_estimate, photo_map, roof_observe))
    total = (build_estimate['draft'] + build_estimate['draft_rooms'] + photo_map + roof_observe
             + tc.estimate('finishes', len(HOUSE_PHOTOS)))
    check(abs(build_estimate['total'] - total) < 0.005, ('the total adds the photo reads', build_estimate, total))


TESTS = (
    test_reads_in_order,
    test_derived_roof_replaces_draft_roof,
    test_no_photos_no_reads,
    test_unrelated_photo_ignored,
    test_unseen_end_flagged_never_pauses,
    test_estimate_and_checkpoint,
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

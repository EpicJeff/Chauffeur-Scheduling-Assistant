"""Roofs derived from what the photos show (brief
.superpowers/sdd/2026-11-08-house-editor-roofs-from-photos/task-3-brief.md,
spec docs/superpowers/specs/2026-11-08-house-editor-roofs-from-photos-design.md
sections 4, 6 and 7).

services.twin_roof_derive.derive_roof(blocks, observations, evidence, choices)
returns (sections, flags):

- blocks: [{id, rect: [x0, y0, x1, y1], storey, level, plate}] as
  services.twin_blocks.blocks() gives them (Task 1). The street is along
  y = 0, so front = y0, rear = y1, left = x0, right = x1. Ridge 'x' runs
  parallel to the street.
- observations: {block_id: {sides: {front|rear|left|right: {kind, centre?,
  width?}}, pitch?, slope_vs_neighbours?}}, kind one of gable_end,
  clipped_gable_end, dormer, slope, hidden, conflict.
- evidence (from the plan): {block_id: {ridge?, pitch?, dormers?: [{side,
  centre, width}]}}. The dormer snap target is passed here: the household's
  plan dormer position is the upper floor's wall jog, read from the recorded
  draft fixture. derive_roof takes no walls.
- choices: [{rect, kind?, ridge?, ends?, pitch?, plate?, overhang?}].
- sections: plan-schema roof sections with id 'roof-<block id>' (a dormer is
  'roof-<block id>-dormer-<n>'), src.step 'roof_blocks' and block: rect. A
  section may carry ends {x0|x1|y0|y1: gable|hip|clip} (Task 2); when absent
  a gable's ends are gables and a hip's ends are hips. A section may carry
  per-side pitches {x0|x1|y0|y1: n} (existing schema); the ridge line and the
  slopes here are computed the way twin_roof.js computes them, so ridge
  alignment may use them.
- flags: [{block, side?, text}], text a plain sentence naming where the block
  sits, never its letter or id.

Household data: the spike's blocks (scratchpad spike_roof/blocks.json) A-F,
with plates 10 (lower) and 20 (upper, L2 elevation 11 + ceiling 9). G and H
(6 ft slivers) are left out: Task 1 merges slivers narrower than 7 ft into a
neighbour. Observations are the spike's round-2 answers (identical in all
three runs apart from D's right side, taken here as the 2-of-3 hidden), with
the third garage (F, x 59-70) corrected to a right gable end. Round 2 had no
pitch or slope comparison; the photo pitches are round 1's majority, with
the middle block at 8 and 'lower'. Plan evidence is the round-3 plan read's
ridge directions.
"""
import json
import os
import re
import sys
import tempfile
import traceback

if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_roof_derive_')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, 'fixtures', 'twin_reads', 'recorded', 'claude', 'draft-main-house.json')

SIDE_END = {'left': 'x0', 'right': 'x1', 'front': 'y0', 'rear': 'y1'}
END_SIDE = {v: k for k, v in SIDE_END.items()}

# The household's blocks (spike_roof/blocks.json, letters kept as ids).
HOUSE = [
    {'id': 'A', 'rect': [14.33, 14.33, 37.33, 52], 'storey': 'upper', 'level': 'L2', 'plate': 20},   # middle
    {'id': 'B', 'rect': [37.33, 19.33, 59, 43], 'storey': 'upper', 'level': 'L2', 'plate': 20},      # right upper
    {'id': 'C', 'rect': [0, 14.33, 14.33, 54], 'storey': 'lower', 'level': 'L1', 'plate': 10},       # left wing
    {'id': 'D', 'rect': [37.33, 0, 59, 19.33], 'storey': 'lower', 'level': 'L1', 'plate': 10},       # garage front
    {'id': 'E', 'rect': [43.33, 43, 59, 65.33], 'storey': 'lower', 'level': 'L1', 'plate': 10},      # rear right
    {'id': 'F', 'rect': [59, 22, 70, 43], 'storey': 'lower', 'level': 'L1', 'plate': 10},            # third garage
]


def _sides(front='hidden', rear='hidden', left='hidden', right='hidden'):
    return {'front': {'kind': front}, 'rear': {'kind': rear},
            'left': {'kind': left}, 'right': {'kind': right}}


def _house_observations():
    """Spike round 2 (r2/runs/obs1..3.json), F's right side corrected."""
    return {
        'A': {'sides': _sides(front='dormer', rear='slope', left='gable_end'),
              'pitch': 8, 'slope_vs_neighbours': 'lower'},
        'B': {'sides': _sides(front='slope'), 'pitch': 10, 'slope_vs_neighbours': 'same'},
        'C': {'sides': _sides(front='slope', rear='slope', left='gable_end'),
              'pitch': 12, 'slope_vs_neighbours': 'same'},
        'D': {'sides': _sides(front='gable_end', left='slope'), 'pitch': 12, 'slope_vs_neighbours': 'same'},
        'E': {'sides': _sides(rear='gable_end', left='slope'), 'pitch': 10, 'slope_vs_neighbours': 'same'},
        'F': {'sides': _sides(right='gable_end'), 'pitch': 8, 'slope_vs_neighbours': 'same'},
    }


def _l2_front_jog():
    """The upper floor's front wall jog over the middle block, from the recorded draft."""
    building = json.load(open(FIXTURE, encoding='utf-8'))['building']
    outline = next(level for level in building['levels'] if level['id'] == 'L2')['outline']
    x0, y0, x1, _ = HOUSE[0]['rect']
    jogs = []
    for a, b in zip(outline, outline[1:] + outline[:1]):
        if (abs(a[1] - b[1]) < 0.01 and 0.2 < y0 - a[1] < 2.5
                and min(a[0], b[0]) >= x0 - 0.01 and max(a[0], b[0]) <= x1 + 0.01):
            jogs.append((min(a[0], b[0]), max(a[0], b[0])))
    assert jogs, 'the recorded draft has no upper-floor front jog over the middle block'
    lo, hi = max(jogs, key=lambda s: s[1] - s[0])
    return {'side': 'front', 'centre': round((lo + hi) / 2, 2), 'width': round(hi - lo, 2)}


def _house_evidence():
    """Round-3 plan read: ridge directions, plus the plan's dormer on the jog."""
    return {'A': {'ridge': 'x', 'dormers': [_l2_front_jog()]}, 'B': {'ridge': 'x'}, 'C': {'ridge': 'x'},
            'D': {'ridge': 'y'}, 'E': {'ridge': 'y'}, 'F': {'ridge': 'x'}}


def _derive(blocks, observations, evidence=None, choices=None):
    from services.twin_roof_derive import derive_roof
    result = derive_roof(blocks, observations, evidence or {}, choices or [])
    assert isinstance(result, tuple) and len(result) == 2, result
    sections, flags = result
    assert isinstance(sections, list) and isinstance(flags, list), result
    return sections, flags


def _block(id_, rect, storey='lower', plate=10):
    return {'id': id_, 'rect': list(rect), 'storey': storey, 'level': 'L1' if storey == 'lower' else 'L2',
            'plate': plate}


def _section(sections, block_id):
    found = [s for s in sections if s.get('id') == f'roof-{block_id}']
    assert len(found) == 1, f'expected one roof-{block_id}, got {[s.get("id") for s in sections]}'
    return found[0]


def _dormers(sections, block_id):
    return [s for s in sections if str(s.get('id', '')).startswith(f'roof-{block_id}-dormer-')]


def _end(section, end):
    ends = section.get('ends') or {}
    if end in ends:
        return ends[end]
    return 'hip' if section['kind'] == 'hip' else 'gable'


def _block_of(flag, blocks):
    for blk in blocks:
        if flag.get('block') in (blk['id'], f"roof-{blk['id']}") or flag.get('block') == blk['rect']:
            return blk['id']
    return None


def _side_of(flag):
    side = flag.get('side')
    return END_SIDE.get(side, side)


def _flags_for(flags, blocks, block_id):
    return [f for f in flags if _block_of(f, blocks) == block_id]


def _slope(section, end):
    return (section.get('pitches') or {}).get(end, section['pitch'])


def _eave_ends(section):
    return ('y0', 'y1') if section['ridge'] == 'x' else ('x0', 'x1')


def _effective_pitch(section):
    a, b = _eave_ends(section)
    return (_slope(section, a) + _slope(section, b)) / 2


def _ridge_line(section):
    """Where the two eave planes meet in plan, and how high, as twin_roof.js draws it."""
    x0, y0, x1, y1 = section['rect']
    a, b = _eave_ends(section)
    s0, s1 = _slope(section, a) / 12, _slope(section, b) / 12
    lo, hi = (y0, y1) if section['ridge'] == 'x' else (x0, x1)
    at = (s0 * lo + s1 * hi) / (s0 + s1)
    return at, section['plate'] + s0 * (at - lo)


def _no_hip(sections):
    for s in sections:
        assert s['kind'] != 'hip', s
        assert 'hip' not in (s.get('ends') or {}).values(), s


def _flag_texts_plain(flags, blocks):
    for f in flags:
        text = f.get('text')
        assert isinstance(text, str) and text.strip(), f
        assert text[0].isupper() and text.rstrip()[-1] in '.!?', f'not a sentence: {text!r}'
        assert 'roof-' not in text and not re.search(r'\b[Bb]lock [A-Z]\b', text), f'id in text: {text!r}'
        own = _block_of(f, blocks)
        if own and own != 'A':   # 'A' is also the article
            assert not re.search(rf'\b{own}\b', text), f'block letter in text: {text!r}'


# ---------------------------------------------------------------- tests

def test_principle_per_end():
    wide, deep = (0, 0, 30, 20), (0, 0, 20, 30)   # long side x, long side y
    blk = [_block('P', wide)]

    # Gable ends left and right: ridge x, gable ends, nothing flagged.
    sections, flags = _derive(blk, {'P': {'sides': _sides('slope', 'slope', 'gable_end', 'gable_end')}})
    s = _section(sections, 'P')
    assert (s['kind'], s['ridge']) == ('gable', 'x'), s
    assert _end(s, 'x0') == _end(s, 'x1') == 'gable', s
    assert flags == [], flags

    # Gable ends front and rear: ridge y, even on a block whose long side is x.
    sections, flags = _derive(blk, {'P': {'sides': _sides('gable_end', 'gable_end', 'slope', 'slope')}})
    s = _section(sections, 'P')
    assert (s['kind'], s['ridge']) == ('gable', 'y'), s
    assert _end(s, 'y0') == _end(s, 'y1') == 'gable', s
    assert flags == [], flags

    # All four sides slope: a hip along the long side; the plan's ridge line can turn it.
    sections, flags = _derive(blk, {'P': {'sides': _sides('slope', 'slope', 'slope', 'slope')}})
    s = _section(sections, 'P')
    assert (s['kind'], s['ridge']) == ('hip', 'x'), s
    assert flags == [], flags
    sections, _ = _derive(blk, {'P': {'sides': _sides('slope', 'slope', 'slope', 'slope')}}, {'P': {'ridge': 'y'}})
    s = _section(sections, 'P')
    assert (s['kind'], s['ridge']) == ('hip', 'y'), s

    # A clipped end: the same gable with a clip at that end.
    sections, flags = _derive(blk, {'P': {'sides': _sides('slope', 'slope', 'clipped_gable_end', 'gable_end')}})
    s = _section(sections, 'P')
    assert (s['kind'], s['ridge']) == ('gable', 'x'), s
    assert (s.get('ends') or {}).get('x0') == 'clip', s
    assert _end(s, 'x1') == 'gable', s
    assert flags == [], flags

    # An unseen end: a gable end there, and a flag on that side.
    sections, flags = _derive(blk, {'P': {'sides': _sides('slope', 'slope', 'gable_end', 'hidden')}})
    s = _section(sections, 'P')
    assert (s['kind'], s['ridge']) == ('gable', 'x'), s
    assert _end(s, 'x0') == _end(s, 'x1') == 'gable', s
    assert [_side_of(f) for f in flags] == ['right'], flags

    # Two photos disagreeing on a side (conflict) is treated like an unseen end.
    sections, flags = _derive(blk, {'P': {'sides': _sides('slope', 'slope', 'gable_end', 'conflict')}})
    s = _section(sections, 'P')
    assert (s['kind'], s['ridge']) == ('gable', 'x') and _end(s, 'x1') == 'gable', s
    assert [_side_of(f) for f in flags] == ['right'], flags

    # Front and rear slope, both ends hidden: the plan's ridge, over the long side.
    blk_deep = [_block('Q', deep)]
    sections, flags = _derive(blk_deep, {'Q': {'sides': _sides('slope', 'slope')}}, {'Q': {'ridge': 'x'}})
    s = _section(sections, 'Q')
    assert (s['kind'], s['ridge']) == ('gable', 'x'), s
    assert len(flags) == 1 and flags[0]['sides'] == ['left', 'right'], flags  # R17
    assert 'its left and right ends were not visible in the photos; I made them gables.' in flags[0]['text'], flags

    # The same with no evidence: the ridge runs along the long side, both ends flagged.
    sections, flags = _derive(blk, {'P': {'sides': _sides('slope', 'slope')}})
    s = _section(sections, 'P')
    assert (s['kind'], s['ridge']) == ('gable', 'x'), s
    assert _end(s, 'x0') == _end(s, 'x1') == 'gable', s
    assert len(flags) == 1 and flags[0]['sides'] == ['left', 'right'], flags  # R17

    # Every section is a block section in the plan schema.
    sections, _ = _derive(blk, {'P': {'sides': _sides('slope', 'slope', 'gable_end', 'gable_end'), 'pitch': 9}})
    s = _section(sections, 'P')
    assert (s.get('src') or {}).get('step') == 'roof_blocks', s
    assert s.get('block') == list(wide) and s['rect'] == list(wide), s
    assert s['plate'] == 10 and s['pitch'] == 9, s


def test_household_truth():
    sections, flags = _derive(HOUSE, _house_observations(), _house_evidence(), [])
    by = {b['id']: _section(sections, b['id']) for b in HOUSE}
    for blk in HOUSE:
        s = by[blk['id']]
        assert (s.get('src') or {}).get('step') == 'roof_blocks', s
        assert s.get('block') == blk['rect'], s
        assert all(abs(a - b) < 0.01 for a, b in zip(s['rect'], blk['rect'])), s
        assert s['plate'] == blk['plate'], s

    # There are no hips anywhere.
    _no_hip(sections)
    # Middle: side gable, gable end on its left.
    assert (by['A']['kind'], by['A']['ridge']) == ('gable', 'x'), by['A']
    assert _end(by['A'], 'x0') == 'gable', by['A']
    # Left wing: side gable, gable end facing left.
    assert (by['C']['kind'], by['C']['ridge']) == ('gable', 'x'), by['C']
    assert _end(by['C'], 'x0') == 'gable', by['C']
    # Right upper: side gable.
    assert (by['B']['kind'], by['B']['ridge']) == ('gable', 'x'), by['B']
    # Garage wing: front-facing gable.
    assert (by['D']['kind'], by['D']['ridge']) == ('gable', 'y'), by['D']
    assert _end(by['D'], 'y0') == 'gable', by['D']
    # Third garage: gable end to the right, ridge parallel to the street.
    assert (by['F']['kind'], by['F']['ridge']) == ('gable', 'x'), by['F']
    assert _end(by['F'], 'x1') == 'gable', by['F']
    # Rear right: the rear gable photo 20 shows.
    assert (by['E']['kind'], by['E']['ridge']) == ('gable', 'y'), by['E']
    assert _end(by['E'], 'y1') == 'gable', by['E']

    # The front dormer over the upper windows: centre about 30, about 15 wide.
    dormers = _dormers(sections, 'A')
    assert len(dormers) == 1, [s.get('id') for s in sections]
    d = dormers[0]
    centre, width = (d['rect'][0] + d['rect'][2]) / 2, d['rect'][2] - d['rect'][0]
    assert abs(centre - 30) <= 1 and abs(width - 15) <= 1, d
    assert (d['kind'], d['ridge']) == ('gable', 'y'), d
    assert d['plate'] == 20, d
    a_ridge_y, _ = _ridge_line(by['A'])
    assert abs(d['rect'][1] - 14.33) <= 1, f'dormer should start at the front eave: {d}'
    assert abs(d['rect'][3] - a_ridge_y) <= 1, f'dormer should run back to the main ridge {a_ridge_y}: {d}'
    assert (d.get('src') or {}).get('step') == 'roof_blocks', d

    # One long ridge line through the left wing, the middle and the right upper.
    lines = {k: _ridge_line(by[k])[0] for k in ('C', 'A', 'B')}
    assert max(lines.values()) - min(lines.values()) <= 0.5, lines
    # The middle's slope is lower than the wings'.
    pitches = {k: _effective_pitch(by[k]) for k in ('C', 'A', 'B')}
    assert pitches['A'] < pitches['C'] and pitches['A'] < pitches['B'], pitches
    for s in sections:
        for end in ('x0', 'x1', 'y0', 'y1'):
            assert 3 <= _slope(s, end) <= 14, s

    # Sides the photos showed are never flagged; the right upper's unseen ends are.
    seen = {('A', 'left'), ('A', 'front'), ('A', 'rear'), ('C', 'left'), ('C', 'front'), ('C', 'rear'),
            ('B', 'front'), ('D', 'front'), ('D', 'left'), ('E', 'rear'), ('E', 'left'), ('F', 'right')}
    for f in flags:
        assert (_block_of(f, HOUSE), _side_of(f)) not in seen, f
    assert not any('not visible' in f['text'] for f in _flags_for(flags, HOUSE, 'B')), flags  # R17
    _flag_texts_plain(flags, HOUSE)


def test_plan_never_decides_kind():
    blk = [_block('P', (0, 0, 30, 20))]
    seen = {'P': {'sides': _sides('slope', 'slope', 'gable_end', 'gable_end'), 'pitch': 10}}
    hip_like = {'P': {'ridge': 'y', 'pitch': 7, 'kind': 'hip', 'ends': {'x0': 'hip', 'x1': 'clip'},
                      'dormers': [{'side': 'front', 'centre': 15, 'width': 6}]}}
    sections, _ = _derive(blk, seen, hip_like)
    s = _section(sections, 'P')
    assert s['kind'] == 'gable', s
    assert s['ridge'] == 'x', f'the photos saw gable ends left and right: {s}'
    assert _end(s, 'x0') == _end(s, 'x1') == 'gable', s
    assert s['pitch'] == 7, f'the plan fills the pitch: {s}'

    # Clipped and gable ends seen in the photos stay as seen whatever the plan draws.
    seen = {'P': {'sides': _sides('slope', 'slope', 'clipped_gable_end', 'gable_end')}}
    sections, _ = _derive(blk, seen, {'P': {'kind': 'hip', 'ends': {'x0': 'gable', 'x1': 'hip'}}})
    s = _section(sections, 'P')
    assert s['kind'] == 'gable' and (s.get('ends') or {}).get('x0') == 'clip' and _end(s, 'x1') == 'gable', s

    # Where nothing decides it, the plan fills the ridge.
    sections, _ = _derive([_block('Q', (0, 0, 20, 30))], {'Q': {'sides': _sides('slope', 'slope')}},
                          {'Q': {'ridge': 'x', 'kind': 'hip'}})
    s = _section(sections, 'Q')
    assert (s['kind'], s['ridge']) == ('gable', 'x'), s


def test_dormer_snaps_to_plan_within_2ft():
    upper = [_block('A', HOUSE[0]['rect'], 'upper', 20)]
    jog = _l2_front_jog()
    assert abs(jog['centre'] - 30) < 0.01 and abs(jog['width'] - 14.67) < 0.02, jog

    def dormer(front, evidence):
        obs = {'A': {'sides': {'front': front, 'rear': {'kind': 'slope'}, 'left': {'kind': 'gable_end'},
                               'right': {'kind': 'gable_end'}}}}
        sections, _ = _derive(upper, obs, evidence)
        found = _dormers(sections, 'A')
        assert found, [s.get('id') for s in sections]
        return [((d['rect'][0] + d['rect'][2]) / 2, d['rect'][2] - d['rect'][0]) for d in found]

    # The photo's rough dormer is within 2 ft of the plan's: it takes the plan's place.
    got = dormer({'kind': 'dormer', 'centre': 28.5, 'width': 13}, {'A': {'dormers': [jog]}})
    assert len(got) == 1 and abs(got[0][0] - jog['centre']) <= 0.1 and abs(got[0][1] - jog['width']) <= 0.1, got
    # No position from the photo: the plan's.
    got = dormer({'kind': 'dormer'}, {'A': {'dormers': [jog]}})
    assert len(got) == 1 and abs(got[0][0] - jog['centre']) <= 0.1 and abs(got[0][1] - jog['width']) <= 0.1, got
    # Far from the plan's, or no plan dormer: the photo's own place.
    got = dormer({'kind': 'dormer', 'centre': 20, 'width': 6}, {'A': {'dormers': [jog]}})
    assert any(abs(c - 20) <= 0.1 and abs(w - 6) <= 0.1 for c, w in got), got
    got = dormer({'kind': 'dormer', 'centre': 26, 'width': 14}, {})
    assert len(got) == 1 and abs(got[0][0] - 26) <= 0.1 and abs(got[0][1] - 14) <= 0.1, got


def test_choice_wins():
    observations = _house_observations()
    evidence = _house_evidence()
    _, flags = _derive(HOUSE, observations, evidence, [])
    assert not _flags_for(flags, HOUSE, 'C'), 'R17: the left wing right end is shared with the middle'

    c_rect = [v + 0.6 for v in HOUSE[2]['rect']]   # within 1 ft
    choices = [{'rect': c_rect, 'kind': 'hip', 'ridge': 'y', 'pitch': 5, 'plate': 11, 'overhang': 2},
               {'rect': HOUSE[1]['rect'], 'kind': 'gable', 'ridge': 'y', 'ends': {'y0': 'clip', 'y1': 'gable'},
                'pitch': 6}]
    sections, flags = _derive(HOUSE, observations, evidence, choices)
    c = _section(sections, 'C')
    assert (c['kind'], c['ridge'], c['plate'], c['overhang']) == ('hip', 'y', 11, 2), c
    assert all(_slope(c, end) == 5 for end in ('x0', 'x1', 'y0', 'y1')), c
    b = _section(sections, 'B')
    assert (b['kind'], b['ridge']) == ('gable', 'y'), b
    assert (b.get('ends') or {}).get('y0') == 'clip' and _end(b, 'y1') == 'gable', b
    assert all(_slope(b, end) == 6 for end in ('x0', 'x1')), b
    assert not _flags_for(flags, HOUSE, 'C'), flags
    assert not _flags_for(flags, HOUSE, 'B'), flags
    assert c.get('block') == HOUSE[2]['rect'] and c['rect'] == HOUSE[2]['rect'], c

    # A choice more than 1 ft off matches no block.
    far = [{'rect': [v + 2 for v in HOUSE[2]['rect']], 'kind': 'hip', 'ridge': 'y', 'pitch': 5}]
    sections, flags = _derive(HOUSE, observations, evidence, far)
    c = _section(sections, 'C')
    assert (c['kind'], c['ridge']) == ('gable', 'x'), c
    assert not _flags_for(flags, HOUSE, 'C'), flags  # R17: unseen end is shared.


def test_pitch_clamp_and_order():
    blk = [_block('P', (0, 0, 30, 20))]
    sides = _sides('slope', 'slope', 'gable_end', 'gable_end')

    def pitch(photo=None, plan=None):
        obs = {'P': {'sides': sides}}
        if photo is not None:
            obs['P']['pitch'] = photo
        sections, _ = _derive(blk, obs, {'P': {'pitch': plan}} if plan is not None else {})
        s = _section(sections, 'P')
        assert all(_slope(s, end) == s['pitch'] for end in ('y0', 'y1')), s
        return s['pitch']

    assert pitch(photo=10, plan=6) == 6
    assert pitch(photo=10) == 10
    assert pitch(plan=9) == 9
    assert pitch(photo=10, plan=20) == 14
    assert pitch(photo=1) == 3
    assert pitch(photo=30) == 14
    assert pitch(photo=10, plan=1) == 3


def test_ridge_check_flags():
    def flags_for(q_plate, q_vs='same'):
        blocks = [_block('P', (0, 0, 20, 30), 'lower', 10), _block('Q', (20, 0, 40, 30), 'upper', q_plate)]
        sides = _sides('slope', 'slope', 'gable_end', 'gable_end')
        obs = {'P': {'sides': sides, 'pitch': 12, 'slope_vs_neighbours': 'same'},
               'Q': {'sides': sides, 'pitch': 12, 'slope_vs_neighbours': q_vs}}
        sections, flags = _derive(blocks, obs)
        assert abs(_ridge_line(_section(sections, 'P'))[1] - 25) < 0.01, _section(sections, 'P')
        return blocks, sections, flags

    # Q's ridge stands 10 ft above P's though the photos show them about level.
    blocks, sections, flags = flags_for(20)
    assert abs(_ridge_line(_section(sections, 'Q'))[1] - 35) < 0.01, _section(sections, 'Q')
    assert _flags_for(flags, blocks, 'Q'), flags
    _flag_texts_plain(flags, blocks)
    # 2 ft apart: nothing to flag.
    _, _, flags = flags_for(12)
    assert flags == [], flags


def test_unseen_block_flag_text():
    observations = _house_observations()
    observations['F'] = {'sides': _sides(), 'pitch': 8, 'slope_vs_neighbours': 'same'}
    evidence = _house_evidence()
    evidence.pop('F')
    sections, flags = _derive(HOUSE, observations, evidence, [])
    f = _section(sections, 'F')
    assert f['kind'] == 'gable', f
    assert all(_end(f, end) == 'gable' for end in (('x0', 'x1') if f['ridge'] == 'x' else ('y0', 'y1'))), f
    mine = _flags_for(flags, HOUSE, 'F')
    assert len(mine) == 1, f'an unseen block is flagged once: {mine}'
    text = mine[0]['text']
    assert 'right' in text.lower(), f'the flag should say where the block sits: {text!r}'
    assert not re.search(r'\bF\b', text) and 'roof-' not in text, text
    _flag_texts_plain(flags, HOUSE)

    # The same block alone, every side hidden, still gets a roof and a plain flag.
    sections, flags = _derive([_block('Z', (0, 0, 12, 20))], {'Z': {'sides': _sides()}})
    z = _section(sections, 'Z')
    assert (z['kind'], z['ridge']) == ('gable', 'y'), z
    assert len(flags) == 1, flags
    _flag_texts_plain(flags, [_block('Z', (0, 0, 12, 20))])


def test_mixed_ends_and_sliver_use_the_same_principle():
    block = _block('sliver', (0, 0, 5, 20))
    block['sliver'] = True
    sections, flags = _derive([block], {'sliver': {
        'sides': _sides('slope', 'slope', 'gable_end', 'slope'), 'pitch': 8}})
    roof = _section(sections, 'sliver')
    assert (roof['kind'], roof['ridge']) == ('gable', 'x'), roof
    assert _end(roof, 'x0') == 'gable' and _end(roof, 'x1') == 'hip', roof
    assert roof['rect'] == block['rect'] and flags == [], (roof, flags)


def test_flat_and_shed_choices_are_protected_and_inputs_unchanged():
    from copy import deepcopy
    blocks = [_block('P', (0, 0, 20, 30)), _block('Q', (20, 0, 40, 30))]
    sides = _sides('slope', 'slope', 'gable_end', 'gable_end')
    obs = {b['id']: {'sides': deepcopy(sides), 'pitch': 12, 'slope_vs_neighbours': 'same'} for b in blocks}
    for kind in ('flat', 'shed'):
        choices = [{'rect': blocks[0]['rect'], 'kind': kind, 'pitch': 5}]
        inputs = deepcopy((blocks, obs, choices))
        sections, flags = _derive(blocks, obs, choices=choices)
        roof = _section(sections, 'P')
        assert roof['kind'] == kind and 'ends' not in roof, roof
        assert roof['pitch'] == (0 if kind == 'flat' else 5), roof
        assert not _flags_for(flags, blocks, 'P'), flags
        assert (blocks, obs, choices) == inputs, 'derivation mutated its inputs'


def test_review_places_use_building_extent_and_are_distinct():
    from services.twin_roof_derive import derive_roof
    sections, flags = derive_roof(HOUSE, {}, {}, [])
    assert len(sections) == len(HOUSE), sections
    places = {b['id']: re.split(r' was|:', _flags_for(flags, HOUSE, b['id'])[0]['text'])[0]
              for b in HOUSE}
    assert len(set(places.values())) == len(HOUSE), places
    assert 'middle' in places['A'].lower(), places
    assert 'front' in places['D'].lower() and 'rear' in places['E'].lower(), places
    _flag_texts_plain(flags, HOUSE)

    # Same third and storey still need distinct, plain qualifiers.
    blocks = [_block('P', (0, 0, 100, 100)), _block('Q', (10, 10, 20, 20)),
              _block('R', (20, 10, 25, 20))]
    _, flags = derive_roof(blocks, {}, {}, [])
    names = [re.split(r' was|:', _flags_for(flags, blocks, b['id'])[0]['text'])[0] for b in blocks]
    assert len(set(names)) == len(blocks), names
    _flag_texts_plain(flags, blocks)


def test_review_ridge_choice_uses_new_observed_ends():
    from services.twin_roof_derive import derive_roof
    blocks = [_block('P', (0, 0, 30, 20))]
    observations = {'P': {'sides': _sides('slope', 'slope', 'clipped_gable_end', 'slope')}}
    sections, flags = derive_roof(blocks, observations, {}, [{'rect': blocks[0]['rect'], 'ridge': 'y'}])
    roof = _section(sections, 'P')
    assert roof['ridge'] == 'y' and roof['kind'] == 'gable', roof
    assert roof.get('ends') == {'y0': 'hip', 'y1': 'hip'}, roof
    assert 'clip' not in roof.get('ends', {}).values() and flags == [], (roof, flags)
    # Newly selected gable or unseen ends are plain gables, without an override.
    for front in ('gable_end', 'hidden'):
        observations['P']['sides'] = _sides(front, 'hidden', 'clipped_gable_end', 'gable_end')
        sections, _ = derive_roof(blocks, observations, {}, [{'rect': blocks[0]['rect'], 'ridge': 'y'}])
        assert 'ends' not in _section(sections, 'P'), sections


def test_review_person_pitch_is_clamped_before_geometry():
    from services.twin_roof_derive import derive_roof
    blocks = [_block('P', (0, 0, 30, 20))]
    for kind in ('gable', 'hip'):
        for pitch, expected in ((0, 3), (-5, 3), (25, 14)):
            choices = [{'rect': blocks[0]['rect'], 'kind': kind, 'pitch': pitch}]
            sections, flags = derive_roof(blocks, {}, {}, choices)
            roof = _section(sections, 'P')
            assert roof['pitch'] == expected and roof['pitch_source'] == 'person', roof
            assert _ridge_line(roof)[1] > roof['plate'] and flags == [], (roof, flags)


def test_review_invalid_plan_pitch_falls_back_to_photo():
    from services.twin_roof_derive import derive_roof
    blocks = [_block('P', (0, 0, 30, 20))]
    observations = {'P': {'sides': _sides('slope', 'slope', 'gable_end', 'gable_end'), 'pitch': 6}}
    for pitch in (None, 'unknown', float('nan'), float('inf'), False):
        sections, _ = derive_roof(blocks, observations, {'P': {'pitch': pitch}}, [])
        roof = _section(sections, 'P')
        assert roof['pitch'] == 6 and roof['pitch_source'] == 'photos', roof


def test_review_incompatible_row_aligns_largest_subrun_and_flags():
    from services.twin_roof_derive import derive_roof
    observations = _house_observations()
    observations['C']['pitch'] = observations['B']['pitch'] = 14
    sections, flags = derive_roof(HOUSE, observations, _house_evidence(), [])
    lines = {k: _ridge_line(_section(sections, k))[0] for k in ('C', 'A', 'B')}
    aligned = [k for k in ('C', 'B') if abs(lines[k] - lines['A']) < .01]
    assert len(aligned) == 1, lines
    left_out = ({'C', 'B'} - set(aligned)).pop()
    ridge_flags = [f for f in flags if 'could not line up' in f['text']]
    assert {f['block'] for f in ridge_flags} == {left_out}, flags
    _flag_texts_plain(flags, HOUSE)
    for section in sections:
        assert all(3 <= _slope(section, end) <= 14 for end in ('x0', 'x1', 'y0', 'y1')), section

    # A non-contiguous pair cannot win over a real two-block run.
    blocks = [_block('P', (0, 0, 10, 20)), _block('Q', (10, 10, 20, 30)),
              _block('R', (20, 20, 30, 40)), _block('S', (30, 20, 40, 40))]
    obs = {b['id']: {'sides': _sides('slope', 'slope', 'gable_end', 'gable_end'), 'pitch': 14}
           for b in blocks}
    _, flags = derive_roof(blocks, obs, {}, [])
    assert {f['block'] for f in flags if 'could not line up' in f['text']} == {'P', 'Q'}, flags


def test_review_unrepresented_gables_and_dormers_are_flagged():
    from services.twin_roof_derive import derive_roof
    blocks = [_block('P', (0, 0, 30, 20))]
    observations = {'P': {'sides': _sides('gable_end', 'slope', 'gable_end', 'slope')}}
    _, flags = derive_roof(blocks, observations, {}, [])
    assert any(f.get('side') == 'front' and 'front' in f['text'] and 'gable' in f['text'] for f in flags), flags
    _flag_texts_plain(flags, blocks)

    # Left is an end on ridge x; front is an end on ridge y.
    for ridge, side in (('x', 'left'), ('y', 'front')):
        sides = _sides('slope', 'slope', 'slope', 'slope')
        sides[side] = {'kind': 'dormer', 'centre': 10, 'width': 6}
        sections, flags = derive_roof(blocks, {'P': {'sides': sides}}, {'P': {'ridge': ridge}}, [])
        assert not _dormers(sections, 'P'), sections
        assert any(f.get('side') == side and side in f['text'] and 'dormer' in f['text'] for f in flags), flags
        _flag_texts_plain(flags, blocks)

    # Left is an eave on ridge y: keep this valid dormer rather than flagging it.
    sides = _sides('gable_end', 'gable_end', 'dormer', 'slope')
    sections, flags = derive_roof(blocks, {'P': {'sides': sides}}, {}, [])
    assert len(_dormers(sections, 'P')) == 1 and flags == [], (sections, flags)
    # A person's explicit correction suppresses contradictory-observation flags.
    _, flags = derive_roof(blocks, observations, {}, [{'rect': blocks[0]['rect'], 'ridge': 'y'}])
    assert flags == [], flags


def test_review_unseen_block_inherits_longest_adjacent_form():
    from services.twin_roof_derive import derive_roof
    blocks = [_block('P', (0, 0, 30, 20)), _block('Q', (30, 0, 40, 20)),
              _block('R', (0, 20, 30, 35))]
    observations = {'P': {'sides': _sides()},
                    'Q': {'sides': _sides('slope', 'slope', 'gable_end', 'gable_end')},
                    'R': {'sides': _sides('gable_end', 'gable_end', 'slope', 'slope')}}
    for ordered in (blocks, list(reversed(blocks))):
        sections, flags = derive_roof(ordered, observations, {'P': {'ridge': 'x'}}, [])
        roof = _section(sections, 'P')
        assert (roof['kind'], roof['ridge']) == ('gable', 'y'), roof
        assert len(_flags_for(flags, blocks, 'P')) == 1, flags
        _flag_texts_plain(flags, blocks)
    observations['R']['sides'] = _sides('slope', 'slope', 'slope', 'slope')
    sections, flags = derive_roof(blocks, observations, {'R': {'ridge': 'y'}}, [])
    roof = _section(sections, 'P')
    assert (roof['kind'], roof['ridge']) == ('hip', 'y'), roof
    assert _end(roof, 'y0') == _end(roof, 'y1') == 'hip', roof
    assert len(_flags_for(flags, blocks, 'P')) == 1, flags


def test_photo_relative_slope_overrides_contradictory_plan_pitches():
    from services.twin_roof_derive import derive_roof
    observations = _house_observations()
    evidence = _house_evidence()
    evidence['A']['pitch'] = 10
    evidence['C']['pitch'] = 8
    sections, _ = derive_roof(HOUSE, observations, evidence, [])
    by = {b['id']: _section(sections, b['id']) for b in HOUSE}
    assert by['A']['pitch_source'] == 'photos', by['A']
    assert _effective_pitch(by['A']) < min(_effective_pitch(by[k]) for k in ('B', 'C')), by
    assert by['A']['pitch'] == observations['A']['pitch'], by['A']
    # The opposite comparison obeys the same rule, with person choices still first.
    blocks = [_block('P', (0, 0, 20, 20)), _block('Q', (20, 0, 40, 20))]
    obs = {'P': {'sides': _sides('slope', 'slope', 'gable_end', 'gable_end'),
                 'pitch': 12, 'slope_vs_neighbours': 'steeper'},
           'Q': {'sides': _sides('slope', 'slope', 'gable_end', 'gable_end'), 'pitch': 6}}
    plan = {'P': {'pitch': 5}, 'Q': {'pitch': 9}}
    roofs, _ = derive_roof(blocks, obs, plan, [])
    assert roofs[0]['pitch'] == 12 and roofs[1]['pitch'] == 9, roofs
    obs['Q'].pop('pitch')
    roofs, _ = derive_roof(blocks, obs, plan, [])
    assert roofs[0]['pitch'] == 12 and roofs[1]['pitch'] == 9, roofs
    roofs, _ = derive_roof(blocks, obs, plan, [{'rect': blocks[0]['rect'], 'pitch': 4}])
    assert roofs[0]['pitch'] == 4 and roofs[0]['pitch_source'] == 'person', roofs


def test_plan_only_dormer_and_photo_plain_slope():
    from services.twin_roof_derive import derive_roof
    upper = [_block('A', HOUSE[0]['rect'], 'upper', 20)]
    evidence = {'A': {'ridge': 'x', 'pitch': 6, 'dormers': [_l2_front_jog()]}}
    sections, flags = derive_roof(upper, {}, evidence, [])
    dormers = [s for s in sections if s.get('dormer_of')]
    assert len(dormers) == 1 and dormers[0]['ridge'] == 'y', sections
    d = dormers[0]
    assert abs((d['rect'][0] + d['rect'][2]) / 2 - 30) < .1, d
    assert abs(d['rect'][2] - d['rect'][0] - 14.67) < .1, d
    assert 'block' not in d and d['dormer_of'] == upper[0]['rect'], d
    assert any('dormer' in f['text'] and 'drawings only' in f['text'] for f in flags), flags
    sections, flags = derive_roof(upper, {'A': {'sides': {'front': {'kind': 'slope'}}}}, evidence, [])
    assert len(sections) == 1, sections
    assert any('plain slope instead of the drawn dormer' in f['text'] for f in flags), flags


def test_household_flags_only_deciding_ends():
    sections, flags = _derive(HOUSE, _house_observations(), _house_evidence(), [])
    for block in HOUSE:
        section = _section(sections, block['id'])
        mine = _flags_for(flags, HOUSE, block['id'])
        assert len([f for f in mine if 'not visible in the photos' in f['text']]) <= 1, mine
        end_sides = ('left', 'right') if section['ridge'] == 'x' else ('front', 'rear')
        eaves = {'left', 'right', 'front', 'rear'} - set(end_sides)
        for flag in mine:
            assert not any(re.search(rf'\b{side}\s+(?:side|end)', flag['text']) for side in eaves), flag
            for side in flag.get('sides', [flag['side']] if 'side' in flag else []):
                assert side in end_sides, flag
                end = SIDE_END[side]
                axis, other = (0, 1) if end.startswith('x') else (1, 0)
                r = block['rect']
                edge, opposite = (axis, axis + 2) if end.endswith('0') else (axis + 2, axis)
                for neighbour in HOUSE:
                    if neighbour is block:
                        continue
                    n = neighbour['rect']
                    shared = min(r[other + 2], n[other + 2]) - max(r[other], n[other])
                    assert abs(r[edge] - n[opposite]) > .5 or shared < (r[other + 2] - r[other]) / 2, flag
    assert not any('not visible' in f['text'] for f in flags if f['block'] in ('B', 'C')), flags


def test_shared_end_half_length_and_conflict_lines():
    for ridge in ('x', 'y'):
        blocks = [_block('P', (0, 0, 30, 20)),
                  _block('Q', (30, 0, 40, 10) if ridge == 'x' else (0, 20, 15, 30))]
        sides = _sides('slope', 'slope', 'hidden', 'hidden') if ridge == 'x' else _sides('hidden', 'hidden', 'slope', 'slope')
        _, flags = _derive(blocks, {'P': {'sides': sides}}, {'P': {'ridge': ridge}})
        mine = _flags_for(flags, blocks, 'P')
        assert len(mine) == 1 and mine[0]['sides'] == (['left'] if ridge == 'x' else ['front']), mine
        blocks[1]['rect'][3 if ridge == 'x' else 2] -= .1
        _, flags = _derive(blocks, {'P': {'sides': sides}}, {'P': {'ridge': ridge}})
        mine = _flags_for(flags, blocks, 'P')
        assert len(mine) == 1 and len(mine[0]['sides']) == 2, mine
    sides = _sides('hidden', 'conflict', 'hidden', 'conflict')
    _, flags = _derive([_block('P', (0, 0, 30, 20))], {'P': {'sides': sides}})
    assert len(flags) == 1, flags
    sides['front'] = {'kind': 'slope'}
    _, flags = _derive([_block('P', (0, 0, 30, 20))], {'P': {'sides': sides}})
    assert len(flags) == 2 and flags[0]['sides'] == ['left'] and flags[1]['sides'] == ['right'], flags
    assert 'not visible' in flags[0]['text'] and 'looks different between photos' in flags[1]['text'], flags


TESTS = (
    test_household_flags_only_deciding_ends,
    test_shared_end_half_length_and_conflict_lines,
    test_plan_only_dormer_and_photo_plain_slope,
    test_photo_relative_slope_overrides_contradictory_plan_pitches,
    test_principle_per_end,
    test_household_truth,
    test_plan_never_decides_kind,
    test_dormer_snaps_to_plan_within_2ft,
    test_choice_wins,
    test_pitch_clamp_and_order,
    test_ridge_check_flags,
    test_unseen_block_flag_text,
    test_mixed_ends_and_sliver_use_the_same_principle,
    test_flat_and_shed_choices_are_protected_and_inputs_unchanged,
    test_review_places_use_building_extent_and_are_distinct,
    test_review_ridge_choice_uses_new_observed_ends,
    test_review_person_pitch_is_clamped_before_geometry,
    test_review_invalid_plan_pitch_falls_back_to_photo,
    test_review_incompatible_row_aligns_largest_subrun_and_flags,
    test_review_unrepresented_gables_and_dormers_are_flagged,
    test_review_unseen_block_inherits_longest_adjacent_form,
)


if __name__ == '__main__':
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, type(exc).__name__, ' '.join(str(exc).split())[:400])
            if not isinstance(exc, (AssertionError, ImportError)):
                traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} passed')
    sys.exit(1 if failed else 0)

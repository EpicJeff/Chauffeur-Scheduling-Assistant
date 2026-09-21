"""The Home's facade generator (spec docs/superpowers/specs/
2026-09-15-house-facade-generator-design.md).

Pure functions above the line, storage below it. The slot table and the
canonical facade are the JS side's single source of truth too: a live
test pins window.chfFacadeSlots() against slot_table()."""
import copy
import hashlib
import hmac
import json
import math
import secrets
import threading
import time
import uuid
from services.house_photo import OBSERVATION_PROMPT, validate_observations, normalize_observation_notes, reconcile_observations, structural_issues, restore_missing_upper_windows

SLOT_W = 1.85
# West to east. Mirrors house.js: FULL_HOUSE, GARAGE_BLOCK, EXT_TOP4.
# MASSING ARC 1 task 3 (spec 2026-09-16-regular-house-orbit-design.md
# section 5): the old four-face table (garage/mudroom/main/wing)
# collapses onto the two blocks task 2 built -- garage and mudroom now
# share one driveway-facing block front, and the wing merges into the
# main front now that it sits on the same street line (task 1).
FACES = [
    {'face': 'garage_block', 'x0': -18.20, 'x1': -7.15, 'z': 10.10, 'eave': 5.6, 'room': 'garage',  'roof': 'garage_block_roof'},
    {'face': 'main',         'x0': -7.15,  'x1': 14.65, 'z': 14.55, 'eave': 5.6, 'room': 'living',  'roof': 'roof_main'},
]

# The garage ROOM's own x range within the garage_block face (task 2:
# garage x -18.2..-12.6, mudroom -12.6..-7.15). Nearest-slot-boundary
# snap of -12.6 onto the 6-slot face (width 11.05/6 = 1.8417): slot 2
# ends at -12.675, nearer -12.6 than slot 3's end at -10.833, so the
# bay is slots 0-2 of the six -- not the whole face, which now also
# carries the mudroom. normalize()/worst_case() key off this constant
# instead of _face_range('garage_block') so the garage door still spans
# only its own bay (spec section 5).
GARAGE_BAY_SLOTS = (0, 2)

# VIEW-VOLUME MASKING task 4: the slot table used to carry an `owners`
# list per slot (STUDY_SLOTS / slot_owners(): which rooms' cutaway could
# take a feature built there, mirrored in house.js). The house's shell
# is masked geometrically per room now, so the table says only which
# face a slot is on and which room that face fronts.

# MASSING ARC 2 (spec 2026-09-17-house-blocks-materials-design.md
# section 2 plus the upper-span insert): the facade speaks a version-3
# BLOCK MODEL. Cladding, body, base band, depth and the ground roof are
# default per block; story_finishes and finishes override wall skins.
# `upper` owns second-story runs and their roofs; `style`
# keeps only the four roles that are not a block's own skin.
GROUND_KINDS = ('wall', 'window', 'door', 'garage_door', 'porch')
ROOF_KINDS = ('eave', 'gable', 'dormer', 'shed', 'hip_end')
WINDOW_SIZES = ('tall', 'standard', 'small')
PORCH_TYPES = ('sitting', 'stoop', 'covered')
PORCH_ROOFS = ('flat', 'gable', 'shed', 'mixed')
GARAGE_STYLES = ('carriage', 'panel', 'glass')
GARAGE_COLOURS = ('wood', 'white', 'black', 'greige', 'sage', 'slate', 'navy')
CLADDINGS = ('batten', 'lap', 'brick', 'stone', 'stucco', 'shingle')
ROOF_FORMS = ('gable', 'hip')
RIDGES = ('x', 'z')
ORIENTATIONS = ('front', 'side')
STYLE = {
    'body': ('white', 'greige', 'sage', 'slate', 'navy',
             'brick_red', 'tan', 'cream_brick', 'stone_grey', 'painted_brick'),
    'roof': ('charcoal', 'weathered', 'brown'),
    'frame': ('black', 'white'),
    'door': ('wood', 'black', 'red', 'sage'),
    'trim': ('white', 'black'),
}
PITCH_MIN, PITCH_MAX = 22.5, 35.0
BLOCK_PITCH_DEG = 22.5            # house.js BLOCK_PITCH = pi/8; features default PITCH_FAMILY 34.8
DEPTH_MAX = 6.0
DEPTH_MAX_WITH_PORCH = 2.0        # curb 8.0 - porch 4.6 - walk 1.0 = 2.4, floored (spec 2)
BASE_H_MIN, BASE_H_MAX = 0.6, 1.8
UNEXPRESSED_MAX, UNEXPRESSED_LEN = 8, 80
# Draw-budget constants, not grammar (spec 4.7). Tuned in the probe task.
MAX_DORMERS = 6
MAX_GABLES = 4
MAX_PORCH_SLOTS = 10

_GROUND_RANK = {'garage_door': 3, 'door': 2, 'window': 1}      # exclusive kinds
_ROOF_RANK = {'gable': 3, 'dormer': 2, 'shed': 2, 'hip_end': 1}


def _block(**over):
    b = {'depth': 0.0,
         'roof': {'form': 'gable', 'ridge': 'x', 'pitch_deg': BLOCK_PITCH_DEG},
         'cladding': 'batten', 'base': None, 'body': 'white'}
    b.update(over)
    return b


CANONICAL = {
    'version': 3,
    'mirror': False,
    'pitch_deg': round(math.degrees(math.atan2(2.05, 2.95)), 1),   # 34.8, PITCH_FAMILY (features)
    # Today's house expressed in the model (spec 2026-09-17 section 2):
    # main depth 0, one story, gable/x, batten, no base, body white;
    # garage the same, facing the street.
    'blocks': {'main': _block(), 'garage': _block(orientation='front')},
    'style': {'roof': 'charcoal', 'frame': 'black', 'door': 'wood', 'trim': 'white'},
    # Re-snapped for the two-face table (task 3, spec section 5): each
    # element's own world position/extent nearest-slot-snapped onto the
    # new 18-slot grid (task-3-report.md shows the `python -c`
    # derivation). Windows -4.525/-1.025/4.225 -> slots 7/9/12; door
    # 0.725 -> slot 10; the old wing windows 9.775/11.725 -> slots
    # 15/16 (unchanged numbers, now on the merged main face); porch
    # centre 0.1 width 7.0 -> slot 8 span 4 (edges -3.4/3.6 snap to the
    # slot 7/8 and 11/12 boundaries); garage door -15.4 falls inside
    # GARAGE_BAY_SLOTS, which forces it to slot 0 span 3 regardless.
    'ground': [
        {'slot': 0, 'span': 3, 'kind': 'garage_door', 'style': 'carriage', 'leaves': 1},
        {'slot': 7, 'span': 1, 'kind': 'window', 'size': 'tall', 'shutters': False, 'story': 1},
        # THE PORCH OWNS ITS ROOF (spec 2026-09-17 section 2): the old
        # free-standing gable feature at slot 8 span 4 is this instead,
        # so the roof can never disagree with the posts under it.
        {'slot': 8, 'span': 4, 'kind': 'porch', 'type': 'sitting', 'roof': 'gable'},
        {'slot': 9, 'span': 1, 'kind': 'window', 'size': 'tall', 'shutters': False, 'story': 1},
        {'slot': 10, 'span': 1, 'kind': 'door'},
        {'slot': 12, 'span': 1, 'kind': 'window', 'size': 'tall', 'shutters': False, 'story': 1},
        {'slot': 15, 'span': 1, 'kind': 'window', 'size': 'standard', 'shutters': False, 'story': 1},
        {'slot': 16, 'span': 1, 'kind': 'window', 'size': 'standard', 'shutters': False, 'story': 1},
    ],
    'roof': [
        {'slot': 0, 'span': 3, 'kind': 'gable'},
    ],
    'upper': [],
    'unexpressed': [],
}

# Which block stands behind each street face, and back again.
BLOCK_OF_FACE = {'garage_block': 'garage', 'main': 'main'}
FACE_OF_BLOCK = {'garage': 'garage_block', 'main': 'main'}


def block_face(name):
    """The street face a block fronts ('garage' -> 'garage_block')."""
    return FACE_OF_BLOCK.get(name)


def slot_table(blocks=None, upper=None):
    """Slots per street face. Blocks move faces; upper spans raise eaves."""
    blocks = blocks or CANONICAL['blocks']
    upper = CANONICAL.get('upper', []) if upper is None else upper
    upper_slots = set()
    for span in upper if isinstance(upper, list) else []:
        if not isinstance(span, dict):
            continue
        start, count = _int(span.get('slot'), -1), max(0, _int(span.get('span'), 0))
        upper_slots.update(range(start, start + count))
    out, i = [], 0
    for f in FACES:
        b = blocks.get(BLOCK_OF_FACE[f['face']]) or {}
        z = f['z'] + float(b.get('depth') or 0)
        width = f['x1'] - f['x0']
        n = max(1, int(round(width / SLOT_W)))
        w = width / n
        for k in range(n):
            x0 = f['x0'] + k * w
            out.append({'i': i, 'face': f['face'], 'x0': round(x0, 6), 'x1': round(x0 + w, 6),
                        'cx': round(x0 + w / 2, 6), 'z': round(z, 6),
                        'eave': f['eave'] * (2 if i in upper_slots else 1),
                        'room': f['room'], 'roof': f['roof']})
            i += 1
    return out


def _face_range(face):
    """Slot INDICES never move: a face's depth changes only its z."""
    idx = [s['i'] for s in slot_table() if s['face'] == face]
    return idx[0], idx[-1]


def _num(v, default):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _pick(v, allowed, default):
    return v if v in allowed else default


_FEATURE_REQUIRED = {
    'window': ('slot', 'span', 'size', 'shutters', 'story'),
    'door': ('slot', 'span'),
    'garage_door': ('slot', 'span', 'style', 'leaves'),
    'porch': ('slot', 'span', 'type', 'roof'),
    'gable': ('slot', 'span'), 'dormer': ('slot', 'span', 'window'),
    'shed': ('slot', 'span', 'window'), 'hip_end': ('slot', 'span'),
}


def validate_block_model(obj, *, _range_notes=None):
    """Structural validation of a MODEL-produced block model (spec 2026-09-17
    section 4). Returns a list of error strings; [] means valid. Never
    mutates by default and never fills a default. The private photo adapter
    may pass _range_notes to repair finite numeric ranges on its own copy;
    schema, type and missing-field errors remain fatal."""
    errs = []
    if not isinstance(obj, dict):
        return ['not an object']

    def need(d, key, kinds, path):
        if key not in d:
            errs.append(f'{path}.{key} missing'); return None
        v = d[key]
        if kinds is bool:
            ok = isinstance(v, bool)
        elif kinds is float:
            ok = isinstance(v, (int, float)) and not isinstance(v, bool)
        elif kinds is int:
            ok = isinstance(v, int) and not isinstance(v, bool)
        else:
            ok = isinstance(v, kinds)
        if not ok:
            errs.append(f'{path}.{key} wrong type'); return None
        return v

    def enum(d, key, allowed, path):
        v = need(d, key, str, path)
        if v is not None and v not in allowed:
            errs.append(f'{path}.{key}={v!r} not one of {list(allowed)}')
        return v

    def rng(d, key, lo, hi, path):
        v = need(d, key, float, path)
        if v is not None and not (lo <= v <= hi):
            finite = not isinstance(v, float) or math.isfinite(v)
            if _range_notes is not None and finite:
                clamped = min(hi, max(lo, v))
                d[key] = clamped
                _range_notes.append(f'{path}.{key} adjusted from {v} to {clamped} '
                                    f'(supported range {lo}..{hi})')
                return clamped
            errs.append(f'{path}.{key} out of range {lo}..{hi}')
        return v

    if obj.get('version') != 3:
        errs.append('version must be 3')
    need(obj, 'mirror', bool, 'house')
    rng(obj, 'pitch_deg', PITCH_MIN, PITCH_MAX, 'house')
    blocks = need(obj, 'blocks', dict, 'house')
    if blocks is not None:
        for name in ('main', 'garage'):
            b = blocks.get(name)
            if not isinstance(b, dict):
                errs.append(f'blocks.{name} missing'); continue
            p = f'blocks.{name}'
            rng(b, 'depth', 0, DEPTH_MAX, p)
            if 'stories' in b:
                errs.append(f'{p}.stories: removed in version 3, use upper[]')
            roof = need(b, 'roof', dict, p)
            if roof is not None:
                enum(roof, 'form', ROOF_FORMS, p + '.roof')
                enum(roof, 'ridge', RIDGES, p + '.roof')
                rng(roof, 'pitch_deg', PITCH_MIN, PITCH_MAX, p + '.roof')
                if 'window' in roof:
                    need(roof, 'window', bool, p + '.roof')
            enum(b, 'cladding', CLADDINGS, p)
            enum(b, 'body', STYLE['body'], p)
            if 'base' not in b:
                errs.append(f'{p}.base missing')
            elif b['base'] is not None:
                if not isinstance(b['base'], dict):
                    errs.append(f'{p}.base wrong type')
                else:
                    enum(b['base'], 'material', CLADDINGS, p + '.base')
                    rng(b['base'], 'height', BASE_H_MIN, BASE_H_MAX, p + '.base')
                    enum(b['base'], 'body', STYLE['body'], p + '.base')
            if name == 'garage':
                enum(b, 'orientation', ORIENTATIONS, p)
                if 'door_colour' in b:
                    enum(b, 'door_colour', GARAGE_COLOURS, p)
                if 'side_door' in b:
                    door = need(b, 'side_door', dict, p)
                    if door is not None:
                        enum(door, 'style', GARAGE_STYLES, p + '.side_door')
                        if 'third_bay' in door:
                            need(door, 'third_bay', bool, p + '.side_door')
                        if 'projection' in door:
                            rng(door, 'projection', 0, 3.0, p + '.side_door')
                        if 'front_setback' in door:
                            rng(door, 'front_setback', 0.6, 4.0, p + '.side_door')
                        rng(door, 'width', 2.4, 4.4, p + '.side_door')
                        rng(door, 'height', 2.4, 4.0, p + '.side_door')
                        leaves = need(door, 'leaves', int, p + '.side_door')
                        if leaves not in (1, 2):
                            errs.append(p + '.side_door.leaves must be 1 or 2')
    def validate_finish(row, path):
        if not isinstance(row, dict):
            errs.append(f'{path} not an object')
            return
        for key, allowed in (('cladding', CLADDINGS), ('body', STYLE['body'])):
            if key in row:
                enum(row, key, allowed, path)
    if 'story_finishes' in obj:
        defaults = need(obj, 'story_finishes', dict, 'house')
        for block, stories in (defaults or {}).items():
            if block not in ('main', 'garage') or not isinstance(stories, dict):
                errs.append(f'story_finishes.{block} invalid')
                continue
            for story, row in stories.items():
                if story not in ('1', '2'):
                    errs.append(f'story_finishes.{block}.{story} invalid story')
                validate_finish(row, f'story_finishes.{block}.{story}')
    if 'finishes' in obj:
        spans = need(obj, 'finishes', list, 'house')
        for i, row in enumerate(spans or []):
            path = f'finishes[{i}]'
            validate_finish(row, path)
            if not isinstance(row, dict):
                continue
            start = need(row, 'slot', int, path)
            count = need(row, 'span', int, path)
            story = need(row, 'story', int, path)
            if story not in (1, 2):
                errs.append(f'{path}.story must be 1 or 2')
            if start is not None and count is not None and not (0 <= start < len(slot_table()) and 1 <= count <= len(slot_table()) - start):
                errs.append(f'{path} outside elevation')
    upper = need(obj, 'upper', list, 'house')
    if upper is not None:
        slots = slot_table()
        for i, span in enumerate(upper):
            p = f'upper[{i}]'
            if not isinstance(span, dict):
                errs.append(f'{p} not an object'); continue
            start = need(span, 'slot', int, p)
            count = need(span, 'span', int, p)
            roof = need(span, 'roof', dict, p)
            if start is not None and not (0 <= start < len(slots)):
                errs.append(f'{p}.slot out of range 0..{len(slots) - 1}')
            if count is not None and count < 1:
                errs.append(f'{p}.span must be at least 1')
            if start is not None and count is not None and 0 <= start < len(slots):
                _, hi = _face_range(slots[start]['face'])
                if start + count - 1 > hi:
                    errs.append(f'{p}.span crosses its face boundary')
            if roof is not None:
                enum(roof, 'form', ROOF_FORMS, p + '.roof')
                enum(roof, 'ridge', RIDGES, p + '.roof')
                rng(roof, 'pitch_deg', PITCH_MIN, PITCH_MAX, p + '.roof')
                if 'window' in roof:
                    need(roof, 'window', bool, p + '.roof')
    style = need(obj, 'style', dict, 'house')
    if style is not None:
        for role in ('roof', 'frame', 'door', 'trim'):
            enum(style, role, STYLE[role], 'style')
    for layer, kinds in (('ground', GROUND_KINDS), ('roof', ROOF_KINDS)):
        items = need(obj, layer, list, 'house')
        if items is None:
            continue
        for i, e in enumerate(items):
            p = f'{layer}[{i}]'
            if not isinstance(e, dict):
                errs.append(f'{p} not an object'); continue
            kind = enum(e, 'kind', kinds, p)
            if layer == 'roof' and 'window' in e:
                need(e, 'window', bool, p)
            if kind in ('wall', 'eave'):
                continue
            for key in _FEATURE_REQUIRED.get(kind, ()):
                if key not in e:
                    errs.append(f'{p}.{key} missing')
            if kind == 'window' and 'count' in e and (type(e['count']) is not int or not 1 <= e['count'] <= 4):
                errs.append(f'{p}.count must be an integer from 1 to 4')
            if kind == 'window' and 'story' in e and e['story'] not in (1, 2):
                errs.append(f'{p}.story must be 1 or 2')
            if kind == 'porch' and e.get('roof') not in PORCH_ROOFS:
                errs.append(f'{p}.roof not one of {list(PORCH_ROOFS)}')
            if 'cladding' in e and e['cladding'] not in CLADDINGS:
                errs.append(f'{p}.cladding not one of {list(CLADDINGS)}')
    un = need(obj, 'unexpressed', list, 'house')
    if un is not None:
        if len(un) > UNEXPRESSED_MAX:
            errs.append(f'unexpressed: more than {UNEXPRESSED_MAX} entries')
        for s in un:
            if not isinstance(s, str) or len(s) > UNEXPRESSED_LEN:
                errs.append(f'unexpressed: entries are strings of at most {UNEXPRESSED_LEN}'); break
    return errs


def _entries(raw_list, kinds, notes, layer):
    """Shape each entry: known kind, int slot/span, per-kind fields."""
    out = []
    if not isinstance(raw_list, list):
        return out
    nslots = len(slot_table())
    for e in raw_list:
        if not isinstance(e, dict):
            continue
        kind = e.get('kind')
        if kind not in kinds:
            notes.append(f"dropped an unknown {layer} feature '{kind}'")
            continue
        if kind in ('wall', 'eave'):
            continue
        slot = _int(e.get('slot'), -1)
        if slot < 0 or slot >= nslots:
            notes.append(f"dropped a {kind} outside the elevation (slot {e.get('slot')!r})")
            continue
        span = max(1, _int(e.get('span'), 1))
        item = {'slot': slot, 'span': span, 'kind': kind}
        if kind == 'window':
            item['size'] = _pick(e.get('size'), WINDOW_SIZES, 'standard')
            item['shutters'] = bool(e.get('shutters', False))
            if _int(e.get('count'), 1) > 1:
                item['count'] = min(4, _int(e.get('count'), 1))
            item['story'] = 2 if _int(e.get('story'), 1) == 2 else 1
        elif kind == 'porch':
            item['type'] = _pick(e.get('type'), PORCH_TYPES, 'covered')
            item['roof'] = _pick(e.get('roof'), PORCH_ROOFS, 'flat')
            if item['roof'] == 'mixed':
                item['gable_offset'] = max(0, min(span - 1, _int(e.get('gable_offset'), 0)))
                item['gable_span'] = max(1, min(span - item['gable_offset'], _int(e.get('gable_span'), min(2, span))))
        elif kind == 'garage_door':
            item['style'] = _pick(e.get('style'), GARAGE_STYLES, 'carriage')
            item['leaves'] = 2 if _int(e.get('leaves'), 1) == 2 else 1
        elif kind in ('dormer', 'shed'):
            item['window'] = bool(e.get('window', True))
        elif kind == 'gable' and e.get('window'):
            item['window'] = True
        # a roof feature may override its parent block's cladding (spec 2)
        if layer == 'roof' and e.get('cladding') in CLADDINGS:
            item['cladding'] = e['cladding']
        out.append(item)
    return out


def _clip_to_face(item, notes, *, roof=False):
    """Clip to the physical face. Garage doors and porches also stop at the bay; windows may cross it.

    Garage and mudroom share one roof block; their room boundary does not
    constrain roof features. Upper-volume seams are handled separately.
    """
    slots = slot_table()
    face = slots[item['slot']]['face']
    lo, hi = _face_range(face)
    bay_lo, bay_hi = GARAGE_BAY_SLOTS
    if not roof and item['kind'] != 'window' and bay_lo <= item['slot'] <= bay_hi:
        hi = min(hi, bay_hi)
    end = min(item['slot'] + item['span'] - 1, hi)
    if end != item['slot'] + item['span'] - 1:
        notes.append(f"{item['kind']} at slot {item['slot']} truncated at the {face} face boundary")
    item['span'] = end - item['slot'] + 1
    return face


def _resolve_exclusive(items, rank, notes):
    """Higher rank owns its slots; lower ranks are trimmed to what is free,
    split around a winner if needed, dropped when nothing is left."""
    taken = {}
    ordered = sorted(items, key=lambda it: (-rank[it['kind']], it['slot']))
    kept = []
    for it in ordered:
        free = [s for s in range(it['slot'], it['slot'] + it['span']) if s not in taken]
        if not free:
            notes.append(f"dropped a {it['kind']} at slot {it['slot']}: its slots were taken")
            continue
        runs, run = [], [free[0]]
        for s in free[1:]:
            if s == run[-1] + 1:
                run.append(s)
            else:
                runs.append(run); run = [s]
        runs.append(run)
        if len(runs) > 1 or len(free) != it['span']:
            notes.append(f"trimmed a {it['kind']} at slot {it['slot']} around a higher feature")
        for r in runs:
            piece = dict(it); piece['slot'] = r[0]; piece['span'] = len(r)
            kept.append(piece)
            for s in r:
                taken[s] = piece['kind']
    return kept


def _upgrade_v1(raw, notes):
    """The spec 2026-09-17 section 2 mapping table. Returns a V2-shaped raw
    dict; normalize() then applies every law to it."""
    st = raw.get('style') if isinstance(raw.get('style'), dict) else {}
    clad = {'batten': 'batten', 'clapboard': 'lap'}.get(st.get('cladding'), 'batten')
    body = st.get('body', 'white')
    blocks = {'main': _block(cladding=clad, body=body),
              'garage': _block(cladding=clad, body=body, orientation='front')}
    ground = [dict(g) for g in (raw.get('ground') or []) if isinstance(g, dict)]
    roof = [dict(r) for r in (raw.get('roof') or []) if isinstance(r, dict)]
    for g in ground:
        if g.get('kind') == 'window':
            g.setdefault('shutters', False); g.setdefault('story', 1)
        if g.get('kind') == 'porch':
            g.setdefault('roof', 'flat')
    # gable-over-porch pairing: a gable covering >= half a porch's span
    # becomes that porch's roof; the feature is removed. Two porches: the
    # larger overlap wins, tie -> lower slot.
    porches = [g for g in ground if g.get('kind') == 'porch']
    kept = []
    for r in roof:
        if r.get('kind') != 'gable' or not porches:
            kept.append(r); continue
        rs, re_ = _int(r.get('slot'), -1), _int(r.get('slot'), -1) + max(1, _int(r.get('span'), 1))
        best, best_ov = None, 0
        for p in sorted(porches, key=lambda p: _int(p.get('slot'), 0)):
            ps, pe = _int(p.get('slot'), 0), _int(p.get('slot'), 0) + max(1, _int(p.get('span'), 1))
            ov = max(0, min(re_, pe) - max(rs, ps))
            if ov * 2 >= (pe - ps) and ov > best_ov:
                best, best_ov = p, ov
        if best is None:
            kept.append(r); continue
        if best.get('roof') == 'gable':
            notes.append(f"dropped a gable at slot {rs}: porch at slot {best.get('slot')} already has a gabled roof")
            continue
        best['roof'] = 'gable'
        notes.append(f"a gable at slot {rs} became the porch roof at slot {best.get('slot')}")
    return {'version': 2, 'mirror': False, 'pitch_deg': raw.get('pitch_deg'),
            'blocks': blocks, 'style': {k: st.get(k) for k in ('roof', 'frame', 'door', 'trim')},
            'ground': ground, 'roof': kept, 'unexpressed': []}


def _norm_block(name, raw, notes):
    """One block, every field clamped or defaulted (spec 2026-09-17 s2)."""
    raw = raw if isinstance(raw, dict) else {}
    b = _block(orientation='front') if name == 'garage' else _block()
    b['depth'] = round(min(DEPTH_MAX, max(0.0, _num(raw.get('depth'), 0.0))), 2)
    rr = raw.get('roof') if isinstance(raw.get('roof'), dict) else {}
    b['roof'] = {'form': _pick(rr.get('form'), ROOF_FORMS, 'gable'),
                 'ridge': _pick(rr.get('ridge'), RIDGES, 'x'),
                 'pitch_deg': round(min(PITCH_MAX, max(PITCH_MIN, _num(rr.get('pitch_deg'), BLOCK_PITCH_DEG))), 1)}
    if rr.get('window') and b['roof']['form'] == 'gable' and b['roof']['ridge'] == 'z':
        b['roof']['window'] = True
    b['cladding'] = _pick(raw.get('cladding'), CLADDINGS, 'batten')
    b['body'] = _pick(raw.get('body'), STYLE['body'], 'white')
    base = raw.get('base')
    if isinstance(base, dict):
        b['base'] = {'material': _pick(base.get('material'), CLADDINGS, 'stone'),
                     'height': round(min(BASE_H_MAX, max(BASE_H_MIN, _num(base.get('height'), 0.9))), 2),
                     'body': _pick(base.get('body'), STYLE['body'], 'stone_grey')}
    else:
        b['base'] = None
    if name == 'garage':
        b['orientation'] = _pick(raw.get('orientation'), ORIENTATIONS, 'front')
        if 'door_colour' in raw:
            b['door_colour'] = _pick(raw.get('door_colour'), GARAGE_COLOURS, 'wood')
        door = raw.get('side_door')
        if isinstance(door, dict):
            b['side_door'] = {
                'style': _pick(door.get('style'), GARAGE_STYLES, 'carriage'),
                'leaves': 2 if _int(door.get('leaves'), 1) == 2 else 1,
                'width': round(min(4.4, max(2.4, _num(door.get('width'), 3.6))), 2),
                'height': round(min(4.0, max(2.4, _num(door.get('height'), 3.0))), 2),
            }
            if 'third_bay' in door:
                b['side_door']['third_bay'] = bool(door['third_bay'])
            if 'projection' in door:
                b['side_door']['projection'] = round(min(3.0, max(0.0, _num(door['projection'], 0))), 2)
            if 'front_setback' in door:
                b['side_door']['front_setback'] = round(min(4.0, max(0.6, _num(door['front_setback'], 0.75))), 2)
    return b


def _resolve_upper_spans(spans, notes):
    """Resolve upper overlap by input order, then merge identical neighbours."""
    taken, kept = set(), []
    for span in spans:
        cells = list(range(span['slot'], span['slot'] + span['span']))
        free = [cell for cell in cells if cell not in taken]
        if not free:
            notes.append(f"dropped an upper span at slot {span['slot']}: its slots were taken")
            continue
        runs, run = [], [free[0]]
        for cell in free[1:]:
            if cell == run[-1] + 1:
                run.append(cell)
            else:
                runs.append(run); run = [cell]
        runs.append(run)
        if len(free) != len(cells) or len(runs) > 1:
            notes.append(f"trimmed an upper span at slot {span['slot']} around an earlier span")
        for cells_run in runs:
            piece = copy.deepcopy(span)
            piece['slot'], piece['span'] = cells_run[0], len(cells_run)
            kept.append(piece)
            taken.update(cells_run)
    kept.sort(key=lambda item: item['slot'])
    merged = []
    for span in kept:
        same_face = (merged and slot_table()[merged[-1]['slot']]['face'] ==
                     slot_table()[span['slot']]['face'])
        if (same_face and merged[-1]['slot'] + merged[-1]['span'] == span['slot']
                and merged[-1]['roof'] == span['roof']):
            merged[-1]['span'] += span['span']
        else:
            merged.append(span)
    return merged


def _upper_entries(raw_upper, blocks, notes):
    """Shape, face-split, resolve and merge upper spans."""
    slots, shaped = slot_table(blocks, []), []
    if not isinstance(raw_upper, list):
        return []
    for raw_span in raw_upper:
        if not isinstance(raw_span, dict):
            continue
        start = min(len(slots) - 1, max(0, _int(raw_span.get('slot'), 0)))
        end = min(len(slots), start + max(1, _int(raw_span.get('span'), 1)))
        rr = raw_span.get('roof') if isinstance(raw_span.get('roof'), dict) else None
        cursor = start
        while cursor < end:
            face = slots[cursor]['face']
            _, face_hi = _face_range(face)
            piece_end = min(end, face_hi + 1)
            block = BLOCK_OF_FACE[face]
            source = rr or blocks[block]['roof']
            roof = {'form': _pick(source.get('form'), ROOF_FORMS, blocks[block]['roof']['form']),
                    'ridge': _pick(source.get('ridge'), RIDGES, blocks[block]['roof']['ridge']),
                    'pitch_deg': round(min(PITCH_MAX, max(PITCH_MIN,
                                      _num(source.get('pitch_deg'), blocks[block]['roof']['pitch_deg']))), 1)}
            if source.get('window') and roof['form'] == 'gable' and roof['ridge'] == 'z':
                roof['window'] = True
            shaped.append({'slot': cursor, 'span': piece_end - cursor, 'roof': roof})
            if piece_end < end:
                notes.append(f'upper span at slot {start} split at the {face} face boundary')
            cursor = piece_end
    return _resolve_upper_spans(shaped, notes)


def _finish_fields(raw):
    if not isinstance(raw, dict):
        return {}
    return {key: raw[key] for key, allowed in
            (('cladding', CLADDINGS), ('body', STYLE['body'])) if raw.get(key) in allowed}


def _normalize_finishes(raw, spec, notes):
    defaults = raw.get('story_finishes', {})
    defaults = defaults if isinstance(defaults, dict) else {}
    stories = {}
    for block in ('main', 'garage'):
        values = defaults.get(block, {})
        if not isinstance(values, dict):
            continue
        entries = {str(story): _finish_fields(values.get(str(story))) for story in (1, 2)}
        entries = {k: v for k, v in entries.items() if v}
        if entries:
            stories[block] = entries
    if stories:
        spec['story_finishes'] = stories
    slots = slot_table()
    painted = {}
    raw_spans = raw.get('finishes', [])
    for row in raw_spans if isinstance(raw_spans, list) else []:
        fields = _finish_fields(row)
        if not fields:
            continue
        start = _int(row.get('slot'), -1)
        if not 0 <= start < len(slots):
            notes.append('dropped a finish outside the elevation')
            continue
        story = 2 if _int(row.get('story'), 1) == 2 else 1
        end = min(len(slots), start + max(1, _int(row.get('span'), 1)))
        for i in range(start, end):
            cell = painted.setdefault((story, i), {})
            for key, value in fields.items():
                cell.setdefault(key, value)  # first explicit value wins per property
    spans = []
    for (story, i), fields in sorted(painted.items()):
        if (spans and spans[-1]['story'] == story and
                spans[-1]['slot'] + spans[-1]['span'] == i and
                slots[spans[-1]['slot']]['face'] == slots[i]['face'] and
                _finish_fields(spans[-1]) == fields):
            spans[-1]['span'] += 1
        else:
            spans.append(dict(slot=i, span=1, story=story, **fields))
    if spans:
        spec['finishes'] = spans


def effective_finish(spec, slot, story=1):
    """Resolve each property independently: block, story, then street span."""
    face = slot_table()[slot]['face']
    block = BLOCK_OF_FACE[face]
    result = _finish_fields(spec['blocks'][block])
    result.update(spec.get('story_finishes', {}).get(block, {}).get(str(story), {}))
    for row in reversed(spec.get('finishes', [])):
        if row['story'] == story and row['slot'] <= slot < row['slot'] + row['span']:
            result.update(_finish_fields(row))
    return result


def normalize(raw):
    notes = []
    raw = raw if isinstance(raw, dict) else {}
    # A facade with no `blocks` is a version-1 one: run it through the
    # mapping table first, then apply every current law to the result.
    if 'blocks' not in raw:
        raw = _upgrade_v1(raw, notes)
    source_version = _int(raw.get('version'), 2)
    spec = {'version': 3, 'mirror': bool(raw.get('mirror', False))}
    p = _num(raw.get('pitch_deg'), CANONICAL['pitch_deg'])
    spec['pitch_deg'] = round(min(PITCH_MAX, max(PITCH_MIN, p)), 1)
    blocks_raw = raw.get('blocks') if isinstance(raw.get('blocks'), dict) else {}
    spec['blocks'] = {'main': _norm_block('main', blocks_raw.get('main'), notes),
                      'garage': _norm_block('garage', blocks_raw.get('garage'), notes)}
    raw_upper = copy.deepcopy(raw.get('upper')) if isinstance(raw.get('upper'), list) else []
    if source_version < 3:
        for block in ('garage', 'main'):
            old = blocks_raw.get(block) if isinstance(blocks_raw.get(block), dict) else {}
            if _int(old.get('stories'), 1) == 2:
                lo, hi = _face_range(FACE_OF_BLOCK[block])
                raw_upper.append({'slot': lo, 'span': hi - lo + 1,
                                  'roof': copy.deepcopy(spec['blocks'][block]['roof'])})
    spec['upper'] = _upper_entries(raw_upper, spec['blocks'], notes)
    _normalize_finishes(raw, spec, notes)
    st = raw.get('style') if isinstance(raw.get('style'), dict) else {}
    spec['style'] = {k: _pick(st.get(k), allowed, CANONICAL['style'][k])
                     for k, allowed in STYLE.items() if k != 'body'}

    ground = _entries(raw.get('ground'), GROUND_KINDS, notes, 'ground')
    roof = _entries(raw.get('roof'), ROOF_KINDS, notes, 'roof')
    slots = slot_table(spec['blocks'], spec['upper'])

    # pin openings to their room's face (spec 4.4)
    g_lo, g_hi = GARAGE_BAY_SLOTS
    m_lo, m_hi = _face_range('main')
    gds = [g for g in ground if g['kind'] == 'garage_door']
    ground = [g for g in ground if g['kind'] != 'garage_door']
    if gds:
        gd = gds[0]
        if len(gds) > 1:
            notes.append('one garage bay: extra garage doors dropped')
        if gd['slot'] != g_lo or gd['span'] != g_hi - g_lo + 1:
            notes.append('the garage door spans its own bay')
        gd['slot'], gd['span'] = g_lo, g_hi - g_lo + 1
        ground.append(gd)
    doors = [g for g in ground if g['kind'] == 'door']
    for d in doors:
        if not (m_lo <= d['slot'] <= m_hi):
            notes.append(f"front door moved onto the main face (was slot {d['slot']})")
            d['slot'] = min(max(d['slot'], m_lo), m_hi)
        d['span'] = 1
    if not doors:
        ground.append(dict(next(g for g in CANONICAL['ground'] if g['kind'] == 'door')))
        notes.append('a house needs a front door: the canonical one was added')

    # faces are hard boundaries; porch never in the driveway (spec 4.3, 4.5).
    # THE DRIVEWAY IS THE BAY, not the whole block face (ruling 2026-09-16,
    # massing arc 1 fix wave): task 3 merged the old 3-slot 'garage' face
    # and the mudroom's own face into one 6-slot garage_block, and keying
    # the rule on the face name silently widened it over the mudroom's
    # slots 3-5 -- where a porch was legal before the arc and a saved
    # facade could already carry one. Key it on GARAGE_BAY_SLOTS, exactly
    # as the garage door's own pinning above does. _clip_to_face has
    # already clamped anything starting in the bay to the bay, so a porch
    # that begins at slot 1 cannot reach the mudroom to escape this.
    kept = []
    for g in ground:
        _clip_to_face(g, notes)
        if g['kind'] == 'porch' and g_lo <= g['slot'] <= g_hi:
            notes.append('no porch in the driveway (the garage bay)')
            continue
        kept.append(g)
    ground = kept
    for r in roof:
        _clip_to_face(r, notes, roof=True)
        end = r['slot'] + r['span']
        boundaries = sorted({u['slot'] for u in spec['upper']} |
                            {u['slot'] + u['span'] for u in spec['upper']})
        seam = next((edge for edge in boundaries if r['slot'] < edge < end), None)
        if seam is not None:
            r['span'] = seam - r['slot']
            notes.append(f"trimmed a {r['kind']} at slot {r['slot']} at an upper-story seam")

    # A full-width gable end already belongs to its volume's roof. Keep
    # its opening on that roof instead of constructing a second cross-gable.
    kept = []
    for r in roof:
        owner = next((u for u in spec['upper'] if u['slot'] <= r['slot'] < u['slot'] + u['span']), None)
        if owner is None:
            face = slots[r['slot']]['face']
            lo, hi = _face_range(face)
            owner = {'slot': lo, 'span': hi - lo + 1,
                     'roof': spec['blocks'][BLOCK_OF_FACE[face]]['roof']}
        parent = owner['roof']
        if (r['kind'] == 'gable' and r['slot'] == owner['slot'] and r['span'] == owner['span']
                and parent['form'] == 'gable' and parent['ridge'] == 'z'):
            if r.get('window'):
                parent['window'] = True
            notes.append(f"removed duplicate gable at slot {r['slot']}; opening retained on existing roof end" if r.get('window')
                         else f"removed duplicate gable at slot {r['slot']}: existing roof end already supplies it")
        else:
            kept.append(r)
    roof = kept

    # a side-entry garage has no street garage door: the bay's street face
    # carries one window instead (spec 2)
    if spec['blocks']['garage']['orientation'] == 'side':
        n0 = len(ground)
        ground = [g for g in ground if g['kind'] != 'garage_door']
        if len(ground) != n0:
            notes.append('side-entry garage: the street garage door moved to the side face')
        if not any(g['kind'] == 'window' and g_lo <= g['slot'] <= g_hi for g in ground):
            ground.append({'slot': g_lo + 1, 'span': 1, 'kind': 'window', 'size': 'standard',
                           'shutters': False, 'story': 1})

    # story-2 entries only inside one upper span; overlap resolved PER story
    def block_of(item):
        return BLOCK_OF_FACE[slots[item['slot']]['face']]
    kept = []
    for g in ground:
        if g.get('story') == 2:
            whole = any(u['slot'] <= g['slot'] and
                        g['slot'] + g['span'] <= u['slot'] + u['span']
                        for u in spec['upper'])
            if not whole:
                notes.append(f"dropped a story-2 {g['kind']} at slot {g['slot']}: no upper story there")
                continue
        kept.append(g)
    ground = kept
    porches = [g for g in ground if g['kind'] == 'porch']
    s1 = [g for g in ground if g['kind'] != 'porch' and g.get('story', 1) == 1]
    s2 = [g for g in ground if g['kind'] != 'porch' and g.get('story') == 2]
    exclusive = _resolve_exclusive(s1, _GROUND_RANK, notes) + _resolve_exclusive(s2, _GROUND_RANK, notes)
    # A porch owns only its ground-level roof, not the upper roof above it.
    for pch in porches:
        if pch['roof'] != 'gable':
            continue
        n0 = len(roof)
        roof = [r for r in roof
                if not (r['kind'] == 'gable' and not any(
                            u['slot'] <= r['slot'] < u['slot'] + u['span'] for u in spec['upper'])
                        and r['slot'] < pch['slot'] + pch['span']
                        and pch['slot'] < r['slot'] + r['span'])]
        if len(roof) != n0:
            notes.append(f"dropped a gable over the gabled porch at slot {pch['slot']}")
    roof = _resolve_exclusive(roof, _ROOF_RANK, notes)

    # depth clamp: a face carrying a porch keeps the porch behind the curb
    for pch in porches:
        bname = block_of(pch)
        if spec['blocks'][bname]['depth'] > DEPTH_MAX_WITH_PORCH:
            spec['blocks'][bname]['depth'] = DEPTH_MAX_WITH_PORCH
            notes.append(f'{bname} depth clamped to {DEPTH_MAX_WITH_PORCH}: its porch must stay behind the curb')

    # budget caps, east-most first (spec 4.7)
    def cap(items, kind, limit, extra=0):
        own = sorted([i for i in items if i['kind'] == kind], key=lambda i: i['slot'])
        keep = max(0, limit - extra)
        if len(own) > keep:
            notes.append(f"kept {keep} {kind}s of {len(own)} (draw budget)")
        drop = {id(i) for i in own[keep:]}
        return [i for i in items if id(i) not in drop]
    roof = cap(roof, 'dormer', MAX_DORMERS)
    # a shed is a dormer's weight: the two share one cap (spec 2)
    roof = cap(roof, 'shed', MAX_DORMERS, extra=sum(1 for r in roof if r['kind'] == 'dormer'))
    roof = cap(roof, 'gable', MAX_GABLES)
    total = 0
    porch_keep = []
    for pch in sorted(porches, key=lambda i: i['slot']):
        if total + pch['span'] > MAX_PORCH_SLOTS:
            pch['span'] = MAX_PORCH_SLOTS - total
            notes.append('porch shortened (draw budget)')
        if pch['span'] <= 0:
            continue
        total += pch['span']
        porch_keep.append(pch)
    # porches never overlap each other; later loses
    seen = set()
    porches = []
    for pch in porch_keep:
        cells = set(range(pch['slot'], pch['slot'] + pch['span']))
        if cells & seen:
            notes.append('overlapping porches merged')
            continue
        seen |= cells
        porches.append(pch)

    for porch in porches:
        if porch.get('roof') == 'mixed':
            porch['gable_offset'] = min(porch['gable_offset'], porch['span'] - 1)
            porch['gable_span'] = min(porch['gable_span'], porch['span'] - porch['gable_offset'])
    for entry in exclusive:
        if entry['kind'] == 'window' and entry.get('count', 1) > entry['span']:
            entry['count'] = entry['span']
            notes.append(f"window group at slot {entry['slot']} reduced to {entry['count']} windows to fit its remaining span")
        if entry.get('count') == 1:
            entry.pop('count', None)
    spec['ground'] = sorted(exclusive + porches, key=lambda g: (g['slot'], g.get('story', 1), g['kind']))
    spec['roof'] = sorted(roof, key=lambda r: (r['slot'], r['kind']))
    un = raw.get('unexpressed') if isinstance(raw.get('unexpressed'), list) else []
    spec['unexpressed'] = [str(s)[:UNEXPRESSED_LEN] for s in un if isinstance(s, str) and s.strip()][:UNEXPRESSED_MAX]
    return spec, notes


def worst_case():
    """The heaviest spec the caps allow — the budget probe's input."""
    slots = slot_table()
    g_lo, g_hi = GARAGE_BAY_SLOTS
    m_lo, m_hi = _face_range('main')
    ground = [{'slot': g_lo, 'span': g_hi - g_lo + 1, 'kind': 'garage_door', 'style': 'glass', 'leaves': 2},
              {'slot': m_lo, 'span': 1, 'kind': 'door'}]
    roof = []
    dormers = 0
    for s in slots:
        if not (g_lo <= s['i'] <= g_hi) and dormers < MAX_DORMERS:
            roof.append({'slot': s['i'], 'span': 1, 'kind': 'dormer', 'window': True})
            dormers += 1
    for s in slots[g_hi + 1:]:
        if s['i'] == m_lo:
            continue
        ground.append({'slot': s['i'], 'span': 1, 'kind': 'window', 'size': 'tall',
                       'shutters': True, 'story': 1})
    ground.append({'slot': m_lo, 'span': min(MAX_PORCH_SLOTS, m_hi - m_lo + 1),
                   'kind': 'porch', 'type': 'sitting', 'roof': 'gable'})
    left = MAX_PORCH_SLOTS - (m_hi - m_lo + 1)
    if left > 0:
        ground.append({'slot': m_hi + 1, 'span': left, 'kind': 'porch', 'type': 'sitting', 'roof': 'gable'})
    # A GABLED PORCH OWNS ITS ROOF (spec 2026-09-17 section 2), so a gable
    # feature over it would be dropped and the gable cap would come in
    # short. The worst case wants both: place the four gables clear of it.
    owned = set()
    for g in ground:
        if g['kind'] == 'porch' and g.get('roof') == 'gable':
            owned |= set(range(g['slot'], g['slot'] + g['span']))
    gables = 0
    for s in slots:
        if gables >= MAX_GABLES:
            break
        if s['i'] not in {r['slot'] for r in roof} and s['i'] not in owned:
            roof.append({'slot': s['i'], 'span': 1, 'kind': 'gable'})
            gables += 1
    # The heaviest BLOCK model too: full-face upper spans on both blocks,
    # a different cladding per block plus a base band in
    # a third material (each distinct material/body pair is at least one
    # more static draw), the garage as deep as the schema allows and the
    # main at the porch's curb clamp. A SIDE garage is lighter, not
    # heavier -- it deletes the garage door -- so the orientation stays
    # front, and mirror costs nothing (one root scale).
    blocks = {
        'main': {'depth': DEPTH_MAX_WITH_PORCH,
                 'roof': {'form': 'gable', 'ridge': 'x', 'pitch_deg': PITCH_MAX},
                 'cladding': 'brick', 'body': 'brick_red',
                 'base': {'material': 'stone', 'height': BASE_H_MAX, 'body': 'stone_grey'}},
        'garage': {'depth': DEPTH_MAX, 'orientation': 'front',
                   'roof': {'form': 'gable', 'ridge': 'x', 'pitch_deg': PITCH_MAX},
                   'cladding': 'stone', 'body': 'stone_grey',
                   'base': {'material': 'brick', 'height': BASE_H_MAX, 'body': 'painted_brick'}},
    }
    upper = []
    for block in ('garage', 'main'):
        lo, hi = _face_range(FACE_OF_BLOCK[block])
        upper.append({'slot': lo, 'span': hi - lo + 1,
                      'roof': copy.deepcopy(blocks[block]['roof'])})
    ground.extend({'slot': s['i'], 'span': 1, 'kind': 'window', 'size': 'tall',
                   'shutters': True, 'story': 2} for s in slots)
    spec, _ = normalize({'version': 3, 'mirror': False, 'pitch_deg': PITCH_MAX, 'blocks': blocks,
                         'style': {'roof': 'brown', 'frame': 'white', 'door': 'red', 'trim': 'black'},
                         'ground': ground, 'roof': roof, 'upper': upper, 'unexpressed': []})
    return spec


# --- storage ---

CANONICAL_ID = 'canonical'


def _settings():
    from services import storage
    return storage.get_settings() or {}


def _write(patch):
    from services import storage
    storage.patch_settings(patch)


def _saved():
    rows = _settings().get('house_facades') or []
    return [r for r in rows if isinstance(r, dict) and r.get('id')]


def list_facades():
    """Every row's spec comes back NORMALIZED, exactly as active_bundle()
    hands one out. FINAL REVIEW (critical 1): facades saved before massing
    arc 2 are V1 rows with no `blocks`, and the editor's Blocks panel
    (facadeBlockStories, the cladding/base selects) reads
    `spec.blocks.<name>` the moment such a row is loaded -- so a raw row
    threw. Normalizing on read runs the V1 mapping table here too, which
    is the same upgrade the 3D house already gets."""
    rows = copy.deepcopy(_saved())
    for r in rows:
        r['spec'], _ = normalize(r.get('spec'))
    return [{'id': CANONICAL_ID, 'name': 'Canonical', 'readonly': True,
             'source': 'builtin', 'spec': copy.deepcopy(CANONICAL)}] + rows


def save_facade(name, spec, activate=False, source='hand', photo_token=None):
    clean, _ = normalize(spec)
    now = time.time()
    rec = {'id': uuid.uuid4().hex[:12], 'name': (str(name or '').strip() or 'My house')[:60],
           'spec': clean, 'source': source if source in ('hand', 'photo') else 'hand',
           'created_at': now, 'updated_at': now}
    if source == 'photo':
        draft = draft_for(photo_token) if photo_token else None
        if draft and draft.get('photo_trace'):
            rec['photo_trace'] = copy.deepcopy(draft['photo_trace'])
            rec['photo_trace']['saved_matches'] = ('draft' if clean == draft['spec'] else
                'revision' if clean == (draft.get('result') or {}).get('revised') else 'edited')
        else:
            rec['photo_trace_status'] = 'unavailable: photo review expired or predates diagnostics'
    patch = {'house_facades': _saved() + [rec]}
    if activate:
        patch['house_facade_active'] = rec['id']
    _write(patch)
    return rec


def update_facade(fid, name=None, spec=None):
    if fid == CANONICAL_ID:
        raise ValueError('readonly')
    rows = _saved()
    for r in rows:
        if r['id'] == fid:
            if name is not None:
                r['name'] = (str(name).strip() or r['name'])[:60]
            if spec is not None:
                clean, _ = normalize(spec)
                if r.get('photo_trace') and clean != r['spec']:
                    r['photo_trace']['saved_matches'] = 'edited'
                r['spec'] = clean
            r['updated_at'] = time.time()
            _write({'house_facades': rows})
            return r
    return None


def delete_facade(fid):
    if fid == CANONICAL_ID:
        raise ValueError('readonly')
    rows = _saved()
    keep = [r for r in rows if r['id'] != fid]
    if len(keep) == len(rows):
        return False
    patch = {'house_facades': keep}
    if _settings().get('house_facade_active') == fid:
        patch['house_facade_active'] = CANONICAL_ID
    _write(patch)
    return True


def set_active(fid):
    if fid != CANONICAL_ID and not any(r['id'] == fid for r in _saved()):
        raise KeyError(fid)
    _write({'house_facade_active': fid})
    return fid


_PHOTO_DIMENSION_GUIDANCE = (f'\nBase bands: height must be {BASE_H_MIN}..{BASE_H_MAX} scene units. '
                        'Use base: null when no base band is visible; do not use height 0.\n'
                        f'Block depth is extra depth beyond the default block, 0..{DEPTH_MAX} '
                        'scene units, not the total building depth.\n'
                        f'All roof pitches, including upper spans: {PITCH_MIN}..{PITCH_MAX} degrees.\n'
                        'Side garage door width: 2.4..4.4; height: 2.4..4.0; '
                        'front_setback: 0.6..4.0; projection: 0..3.0 scene units.\n')

PHOTO_SYSTEM = """You describe the STREET-FACING elevation of a house from one photo, as JSON only.
The house is drawn as two BLOCKS side by side on a fixed strip of {n} slots, west to east
(left to right as seen from the street):
{faces}
Slot numbers are global (0..{last}), but you report each feature's position as a FRACTION of
its own block's street width (0.0 at that block's west edge, 1.0 at its east edge) -- never a
slot number. This lets you describe the same house regardless of exactly how many slots a block
has.

MIRROR: the garage sits on the WEST (left) side by default. If the garage is on the EAST (right)
side as seen from the street, set "mirror": true. If garage side is unknown, choose the block mapping that best fits the visible
section widths and record that uncertainty. Never assume left/front simply because a door is unseen.

VIEWPOINT: report roughly where the photo was taken from relative to the house's centre --
"left", "centre" or "right".

WORKED EXAMPLE: a garage on the LEFT showing the triangular end of its roof to the street (its
ridge running front-to-back) is {{"form": "gable", "ridge": "z"}} with "orientation": "front" --
because the street sees the gable END, not the long eave side. A hip-roofed main block with two
small gables poking out of the roof toward the street is main.roof = {{"form": "hip", "ridge": "x"}}
plus two separate roof features of kind "gable", one per protrusion. A broad two-story centre with a side-to-side main ridge and a smaller front-facing gable
is ONE broad upper span with ridge x plus a separate roof gable feature. Its upper span
covers the rectangular upstairs wall, not merely the triangle. Use ridge z only when
the entire upper roof actually runs front-to-back.

Return exactly this shape (a fraction-based feature has "block"/"at"/"width" instead of "slot"/"span"):
{{"version": 3, "mirror": bool, "viewpoint": "left"|"centre"|"right",
  "pitch_deg": number between 22.5 and 35,
  "style": {{"roof": one of {roof}, "frame": one of {frame}, "door": one of {door}, "trim": one of {trim}}},
  "blocks": {{
    "main": {{"depth": number, "roof": {{"form": one of {roof_forms}, "ridge": one of {ridges}, "pitch_deg": number}},
              "cladding": one of {claddings}, "body": one of {body},
              "base": null | {{"material": one of {claddings}, "height": number, "body": one of {body}}}}},
    "garage": {{"depth": number, "roof": {{"form": one of {roof_forms}, "ridge": one of {ridges}, "pitch_deg": number}},
                "cladding": one of {claddings}, "body": one of {body},
                "base": null | {{"material": one of {claddings}, "height": number, "body": one of {body}}},
                "orientation": one of {orientations}}}}},
  "ground": [{{"block": "main"|"garage", "at": 0..1, "width": 0..1, "kind": "window", "size": one of {window_sizes}, "shutters": bool, "count": integer 1..4, "story": 1|2}}
            | {{"block","at","width","kind":"door"}}
            | {{"block","at","width","kind":"garage_door","style": one of {garage_styles}, "leaves": 1|2}}
            | {{"block","at","width","kind":"porch","type": one of {porch_types}, "roof": one of {porch_roofs}}}],
  "roof": [{{"block": "main"|"garage", "at": 0..1, "width": 0..1, "kind": one of {roof_kinds_features}, "window": bool}}],
  "upper": [{{"block": "main"|"garage", "at": 0..1, "width": 0..1,
               "roof": {{"form": one of {roof_forms}, "ridge": one of {ridges}, "pitch_deg": number}}}}],
  "story_finishes": {{"main": {{"1": {{"cladding": one of {claddings}, "body": one of {body}}}}}}},
  "finishes": [{{"block": "main"|"garage", "at": 0..1, "width": 0..1, "story": 1|2, "cladding": one of {claddings}, "body": one of {body}}}],
  "unexpressed": [up to 8 short strings naming real details the shape above cannot capture]}}
The garage may also include optional side_door: style (carriage/panel/glass), leaves (1 or 2),
width (2.4..4.4, default 3.6) and height (2.4..4.0, default 3.0), in scene units.
Optional side_door.third_bay (boolean) adds a separate single door; front_setback
(0.6..4.0, default 0.75) measures the gap from the front corner to the nearest door.
Optional side_door.projection (0..3, default 0) projects the third bay toward
the driveway with its own gable; 0 keeps it flush, 1.8 is a typical pop-out.
The garage may include door_colour: wood/white/black/greige/sage/slate/navy.
These control the garage doors independently of street openings.
Finishes are optional overrides. Omit unchanged cladding/body fields to inherit independently.
Story defaults may name main and/or garage, stories "1" and/or "2"; they wrap the block.
Finish spans affect the street-facing wall only, even behind windows or doors.
Window count is the number of adjacent framed units in ONE group. Default is 1.
Span/width reserves wall area; it does NOT multiply windows or stretch one window.
Use count=2 for a paired opening, count=3 for a tripartite group, with at least
one slot per unit. Three separate upstairs openings require THREE separate entries
with story=2, located wholly inside the matching upper span. Never omit those entries
merely because upper describes the wall. Shutters flank the outside of the group.
Material and color are DIFFERENT fields. cladding/base.material must be exactly one
of batten, lap, brick, stone, stucco, shingle. painted_brick and cream_brick are BODY
colors, never materials. White-painted brick means material="brick", body="painted_brick".
Board-and-batten means cladding="batten". Use these exact enum values in every finish.
A volume roof with form="gable", ridge="z" ALREADY supplies its street-facing gable.
Never add a full-width gable feature on top of that end. For its attic opening use
window=true on the block/upper roof object. Cross-gable features also accept window=true.
Resolve roofs[] before openings: ridge=x runs across the facade behind a projecting
cross-gable roof feature; ridge=z presents the block's own end gable. A triangle and
attic window alone do not justify an upper story. Match the observed supporting story.
If garage_side is unknown, choose the block mapping that fits visible roof volumes,
not a default front garage. Do not invent a visible garage door.
Check the observed upstairs window-group count against your story=2 entries before returning.
Rules: colours are the NEAREST palette name, never hex.
For a continuous sloping porch cover with a smaller front gable, use porch roof "mixed".
Its optional gable_offset and gable_span count slots relative to the porch start; defaults are 0 and 2.
Use roof "shed" for a porch cover with only one slope.
If the garage is not visible, describe it
as the visible wing mapped to that block; never omit it. Do not invent a street garage door.
Use the observed facade geometry to choose the mapping and report uncertainty.
Preserve every confidently visible window group; report obscured counts as uncertain. The front door goes on the main block. Anything real
about the house that this schema has no field for -- a shape, a material, a massing detail --
goes in "unexpressed" as a short phrase, never invented into a field that doesn't fit it. No prose."""


def _photo_prompt():
    faces = '\n'.join(f"- {f['face']}: slots {_face_range(f['face'])[0]}..{_face_range(f['face'])[1]}"
                      for f in FACES)
    n = len(slot_table())
    roof_kinds_features = [k for k in ROOF_KINDS if k not in ('eave',)]
    return PHOTO_SYSTEM.format(n=n, last=n - 1, faces=faces,
                               body=list(STYLE['body']), roof=list(STYLE['roof']),
                               frame=list(STYLE['frame']), door=list(STYLE['door']),
                               trim=list(STYLE['trim']), claddings=list(CLADDINGS),
                               roof_forms=list(ROOF_FORMS), ridges=list(RIDGES),
                               orientations=list(ORIENTATIONS), window_sizes=list(WINDOW_SIZES),
                               garage_styles=list(GARAGE_STYLES), porch_types=list(PORCH_TYPES),
                               porch_roofs=list(PORCH_ROOFS), roof_kinds_features=roof_kinds_features) + _PHOTO_DIMENSION_GUIDANCE


def _snap_fractions(obj, notes=None, photo_coordinates=False):
    """Pass 1 reports ground/roof features as a FRACTION of their own block's
    street width (`block`/`at`/`width`) rather than a slot number, so the
    model never has to know the slot grid. This converts each fraction entry
    to the `slot`/`span` shape validate_block_model expects, on that block's
    own face. Entries that already carry `slot` pass through untouched.

    FINAL REVIEW (important 3, same class): a `block` the schema does not
    know used to land silently on the main face. It still lands there --
    that is the only sane fallback -- but it says so in `notes`."""
    if not isinstance(obj, dict):
        return obj
    out = copy.deepcopy(obj)
    for layer in ('ground', 'roof', 'upper', 'finishes'):
        items = out.get(layer)
        if not isinstance(items, list):
            continue
        for e in items:
            if not isinstance(e, dict) or 'slot' in e or 'block' not in e:
                continue
            blk = e.get('block')
            if blk not in ('main', 'garage') and notes is not None:
                notes.append(f"feature with unknown block '{blk}' placed on the main face")
            face = 'garage_block' if blk == 'garage' else 'main'
            lo, hi = _face_range(face)
            n = hi - lo + 1
            at, width = _num(e.get('at'), 0.0), _num(e.get('width'), 1.0 / n)
            if photo_coordinates and out.get('mirror'):
                at = 1.0 - at - width
                if e.get('kind') == 'porch' and e.get('roof') == 'mixed':
                    porch_span = max(1, int(round(width * n)))
                    e['gable_offset'] = max(0, porch_span - int(e.get('gable_offset', 0)) - int(e.get('gable_span', 2)))
            slot = lo + int(round(min(0.999, max(0.0, at)) * n))
            span = max(1, int(round(width * n)))
            e['slot'] = min(max(lo, slot), hi)
            e['span'] = min(span, hi - e['slot'] + 1)
            for k in ('block', 'at', 'width'):
                e.pop(k, None)
    return out


# Photo models sometimes put a finish/color name in the material field. These
# explicit aliases preserve meaning; unknown materials still fail validation.
_PHOTO_MATERIAL_ALIASES = {
    'board and batten': ('batten', None), 'board & batten': ('batten', None),
    'board batten': ('batten', None), 'clapboard': ('lap', None),
    'lap siding': ('lap', None), 'horizontal siding': ('lap', None),
    'brick veneer': ('brick', None), 'stone veneer': ('stone', None),
    'painted brick': ('brick', 'painted_brick'), 'white brick': ('brick', 'painted_brick'),
    'cream brick': ('brick', 'cream_brick'), 'red brick': ('brick', 'brick_red'),
    'brick red': ('brick', 'brick_red'), 'stone grey': ('stone', 'stone_grey'),
    'shingles': ('shingle', None), 'cedar shingles': ('shingle', None),
    'shake': ('shingle', None), 'shakes': ('shingle', None),
}


def _repair_photo_materials(value, notes, path='house'):
    if isinstance(value, list):
        for i, row in enumerate(value):
            _repair_photo_materials(row, notes, f'{path}[{i}]')
    elif isinstance(value, dict):
        for key in ('cladding', 'material'):
            original = value.get(key)
            if not isinstance(original, str) or original in CLADDINGS:
                continue
            normalized = ' '.join(original.lower().replace('_', ' ').replace('-', ' ').split())
            alias = (normalized, None) if normalized in CLADDINGS else _PHOTO_MATERIAL_ALIASES.get(normalized)
            if alias:
                value[key] = alias[0]
                notes.append(f'{path}.{key} mapped from {original!r} to {alias[0]!r}')
                if alias[1] and value.get('body') not in STYLE['body']:
                    value['body'] = alias[1]
                    notes.append(f'{path}.body inferred as {alias[1]!r} from the material finish')
        for key, row in value.items():
            _repair_photo_materials(row, notes, f'{path}.{key}')


def _validate_photo_model(obj, notes):
    """Recover finite numeric ranges using the validator's authoritative limits.

    Work on a copy, surface every correction, and retain strict schema checks.
    """
    out = copy.deepcopy(obj)
    _repair_photo_materials(out, notes)
    return out, validate_block_model(out, _range_notes=notes)


# One bounded run per image during the draft review window. Retry reuses observations
# and cumulative request accounting; each explicit retry has a bounded allowance.
# A double click cannot start a second provider run.
PHOTO_REQUEST_CAP = 6
_PHOTO_RUNS = {}
_PHOTO_LOCK = threading.Lock()


def from_photo(image_b64, mime):
    """Observe, then configure. Drafts and cached observations expire after 15 minutes."""
    from services import model_pools
    settings = _settings()
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key:
        return None, [], 'no LLM API key configured', None
    key = _sha((mime or '') + image_b64)
    with _PHOTO_LOCK:
        now = time.time()
        for k in list(_PHOTO_RUNS):
            if not _PHOTO_RUNS[k]['pending'] and now - _PHOTO_RUNS[k]['created'] > DRAFT_TTL_S:
                del _PHOTO_RUNS[k]
        run = _PHOTO_RUNS.get(key)
        if run and run['pending']:
            return None, [], 'photo analysis already in progress', None
        if run and run.get('token') and draft_for(run['token']):
            return copy.deepcopy(run['spec']), list(run['notes']), None, run['token']
        if run is None:
            if len(_PHOTO_RUNS) >= DRAFT_MAX:
                return None, [], 'photo review cache full; retry after existing reviews expire', None
            run = {'created': now, 'attempts': [], 'observations': None, 'pending': False}
            _PHOTO_RUNS[key] = run
        run['pending'] = True
    attempts = run['attempts']
    action_start = len(attempts)

    def call(system, user, budget):
        remaining = min(budget, PHOTO_REQUEST_CAP - (len(attempts) - action_start))  # each explicit upload/resume is bounded
        if remaining <= 0:
            raise ValueError('This attempt reached its request limit. Retry this photo to resume cached analysis.')
        return model_pools.call_pool_json(
            'vision', api_key, system, user, temperature=0.1, timeout_s=90,
            settings=settings, strict_json=True, max_output_tokens=16384, thinking_level='low',
            max_models=remaining, total_timeout_s=120, workflow='house_photo', attempts=attempts,
            images=[{'mime': mime or 'image/jpeg', 'b64': image_b64}])

    try:
        if run['observations'] is None:
            observed = call(OBSERVATION_PROMPT, 'Identify the visible architecture and proportions.', 3)
            if isinstance(observed, dict) and observed.get('error'):
                raise ValueError(observed['error'])
            raw_observed = copy.deepcopy(observed)
            observed = normalize_observation_notes(observed)
            errors = validate_observations(observed)
            if errors:
                raise ValueError('invalid photo observations: ' + '; '.join(errors[:3]))
            run['raw_observations'] = raw_observed
            run['observations'] = reconcile_observations(observed)
        observed = run['observations']
        res = call(_photo_prompt() + PHOTO_COORDINATES,
                   'Build the house from these observations and the photo. Preserve the broad sections, '
                   'second stories and visible window groups. An attic gable is not an upper story.\n'
                   + json.dumps(observed, separators=(',', ':')), 3)
        if not isinstance(res, dict) or res.get('error'):
            raise ValueError(res.get('error', 'bad configuration response') if isinstance(res, dict) else 'bad response')
        raw_configuration = copy.deepcopy(res)
        res = copy.deepcopy(res)
        if observed['garage_side'] != 'unknown':
            res['mirror'] = observed['garage_side'] == 'right'
        pre = []
        snapped = _snap_fractions(res, pre, photo_coordinates=True)
        blocks = snapped.get('blocks')
        if isinstance(blocks, dict) and not isinstance(blocks.get('garage'), dict):
            blocks['garage'] = _block(orientation='front')
            pre.append('garage block missing: drawn as a plain block; review placement')
        snapped, errs = _validate_photo_model(snapped, pre)
        before_normalization = copy.deepcopy(snapped)
        if errs:
            raise ValueError('the model returned an incomplete house: ' + '; '.join(errs[:3]))
        spec, notes = normalize(snapped)
        notes += restore_missing_upper_windows(spec, observed, len(slot_table()))
        normalization_notes = list(pre + notes)
        issues = structural_issues(spec, observed, len(slot_table()))
        correction = {'initial_issues': list(issues), 'status': 'not_needed'}
        if issues and len(attempts) - action_start < PHOTO_REQUEST_CAP:
            # One bounded structural correction, sharing the upload's existing budget.
            # Failure must leave a usable draft, and never silently accept regression.
            correction['status'] = 'failed'
            try:
                repair = call(_photo_prompt() + '\nReturn ONE complete house using canonical slot/span, not fractions. '
                              'Correct the listed structural discrepancies using the original photo. '
                              'Recheck observations against visible roof planes; do not add stories for attic windows. '
                              'Keep correctly represented features unchanged.',
                              'Observations: ' + json.dumps(observed, separators=(',', ':'))
                              + '\nDiscrepancies: ' + json.dumps(issues, separators=(',', ':'))
                              + '\nNormalization changes: ' + json.dumps(normalization_notes, separators=(',', ':'))
                              + '\nDraft: ' + json.dumps(spec, separators=(',', ':')), 1)
                correction['raw_configuration'] = copy.deepcopy(repair)
                repair_notes = []
                candidate, errors = _validate_photo_model(copy.deepcopy(repair), repair_notes)
                correction['validation_errors'] = list(errors)
                if errors:
                    raise ValueError('; '.join(errors[:3]))
                candidate, clean_notes = normalize(candidate)
                repair_notes += clean_notes + restore_missing_upper_windows(candidate, observed, len(slot_table()))
                remaining = structural_issues(candidate, observed, len(slot_table()))
                correction.update(normalization_notes=repair_notes, structural_issues=remaining)
                if set(remaining) < set(issues):
                    spec, issues = candidate, remaining
                    notes += ['Automatic structural correction accepted.'] + repair_notes
                    correction['status'] = 'accepted'
                else:
                    correction['status'] = 'withheld'
                    notes.append('Automatic correction withheld: it did not reduce discrepancies without regressions.')
            except Exception as ex:
                correction['error'] = str(ex)
                notes.append('Automatic structural correction unavailable; original draft retained.')
        elif issues:
            correction['status'] = 'budget_exhausted'
            notes.append('Automatic structural correction skipped: upload request limit reached.')
        notes = pre + notes + ['Needs review: ' + x for x in issues] + observed['uncertain'] + [_requests_note(attempts)]
        if observed['garage_side'] == 'unknown':
            notes.append('Garage side is uncertain; block mapping is inferred from visible geometry.')
        token = issue_draft(spec, image_b64, mime, viewpoint=observed['viewpoint'], requests=len(attempts))
        _DRAFTS[token]['observations'] = copy.deepcopy(observed)
        _DRAFTS[token]['photo_trace'] = {
            'observations': copy.deepcopy(observed),
            'raw_observations': copy.deepcopy(run.get('raw_observations', observed)),
            'raw_configuration': raw_configuration,
            'before_normalization': before_normalization, 'normalization_notes': normalization_notes,
            'structural_issues': list(issues), 'automatic_correction': correction, 'attempts': list(attempts)}
        _DRAFTS[token]['photo_run'] = run
        run.update(spec=copy.deepcopy(spec), notes=list(notes), token=token)
        return spec, notes, None, token
    except Exception as ex:
        return None, [_requests_note(attempts)], f'could not match the photo ({ex})', None
    finally:
        with _PHOTO_LOCK:
            run['pending'] = False


PHOTO_COORDINATES = """
Coordinate contract for THIS configuration pass overrides the generic slot description:
Report block/at/width fractions, never slot/span. at is the LEFT EDGE of a feature
in that block AS SEEN IN THE PHOTO; width is its extent, not its centre or endpoint.
Do NOT reverse these fractions when mirror=true: the application does that once.
Porch gable_offset counts slots from the porch's PHOTO-LEFT edge and is reflected in code.
For mirror=false the garage block occupies the left third, main the right two thirds.
For mirror=true main occupies the left two thirds, garage the right third.
Map the observed full-facade regions into these block-local fractions. Use ONE broad
upper span for each rectangular second-story wall, with its windows on story 2.
Roof triangles alone belong in roof features, not upper spans. Keep the upper roof's
main ridge direction separate from any smaller decorative front-facing gable.
"""


def _requests_note(attempts):
    """Spec section 4's attempt budget, made true: the pipeline records the
    provider requests it actually made, per pass, in its own notes."""
    return f"{len(attempts)} model request(s): {', '.join(attempts) or 'none'}"


CRITIQUE_SYSTEM = """You compare a photo of a house with a 3D render of a draft description of it,
and improve the draft. You are given, in order: the ORIGINAL PHOTO, the RENDER of the current
draft, and the draft's own JSON (the configuration pass produces, but with "slot" and
"span" instead of fractions -- keep that shape).

Go through the comparison in this FIXED ORDER and give AT MOST EIGHT reasons, each one line,
each naming what you saw and what you changed (or that nothing needed changing):
1. Massing and roof forms -- block count, upper-span placement, and roof form/ridge/pitch.
2. Materials and base -- cladding and body colour per block, the base band.
3. Openings -- windows, doors, garage door, porch: position, size, count.
4. Colours -- style roof/frame/door/trim, and any body colour not already covered above.

Then return ONE full revised model -- never a patch, never a diff -- in the exact same shape as
the draft you were given (slot/span, not fractions). If the draft already matches the photo,
return it unchanged. Anything real about the house the schema still cannot capture belongs in
"unexpressed", not invented into a field that doesn't fit it.

Return exactly this shape: {"reasons": [string, ...up to 8], "revised": <the full block model>}
No prose outside that JSON."""


def critique(token, render_png_b64):
    """A photo + a render of the current draft -> at most eight ordered
    reasons and one revised model (never a patch). The result rides the
    token: a second submission for the same token replays it rather than
    asking the model again. The cached draft itself is never mutated.

    FINAL REVIEW (important 2): the replay check used to be check-then-act,
    so two requests landing together (a double tap, a retry on a slow
    render) both sailed past `result is None` and both paid for a vision
    call. The read-and-mark is one critical section now: the FIRST caller
    marks the entry in flight and runs; a second caller that sees the
    in-flight sentinel is told so, and the route answers 409. Only the
    mark is locked -- the 90-second model call is not."""
    from services import model_pools
    with _CRITIQUE_LOCK:
        e = draft_for(token)
        if e is None:
            return None, 'unknown or expired draft'
        if e['result'] is not None:
            if e['result'].get('pending'):
                return None, 'critique in progress'
            return e['result'], None
        e['result'] = {'pending': True}
        if e.get('photo_run') is not None:
            with _PHOTO_LOCK:
                e['photo_run']['pending'] = True
    settings = _settings()
    api_key = settings.get('llm_gemini_api_key', '')
    draft = copy.deepcopy(e['spec'])
    attempts = []
    issued_requests = e.get('requests') or 0
    result = {'draft': draft, 'revised': None, 'reasons': [],
              'unexpressed': list(draft.get('unexpressed') or []),
              'attempts': 0, 'requests_total': issued_requests}

    def finish(res_obj, retryable=False):
        if e.get('photo_run') is not None:
            with _PHOTO_LOCK:
                e['photo_run']['attempts'].extend(attempts)
                e['photo_run']['pending'] = False
        # Every exit below this point stores a real result, so an entry can
        # never stay `pending` and lock its own token out.
        res_obj['attempts'] = len(attempts)
        res_obj['requests_total'] = issued_requests + len(attempts)
        res_obj['reasons'] = list(res_obj['reasons']) + [_requests_note(attempts)]
        e['requests'] = res_obj['requests_total']
        store_result(token, None if retryable else res_obj)
        return res_obj, None

    if not api_key or not e.get('photo_b64'):
        result['reasons'] = ['no critique: ' + ('no LLM API key configured' if not api_key else 'no photo on this draft')]
        return finish(result)
    observed = e.get('observations')
    before_issues = structural_issues(draft, observed, len(slot_table()))
    try:
        res = model_pools.call_pool_json(
            'vision', api_key, _photo_prompt() + '\n' + CRITIQUE_SYSTEM + '\nUse canonical slot/span coordinates: garage slots 0..5, main 6..17. mirror reflects the whole house; increasing slots run RIGHT TO LEFT in a mirrored photo. Do not use photo fractions in the revision.',
            'Photo first, then render. Observations: ' + json.dumps(observed, separators=(',', ':')) + '\nStructural discrepancies: ' + json.dumps(before_issues, separators=(',', ':')) + '\nDraft JSON:\n' + json.dumps(draft, separators=(',', ':')),
            temperature=0.1, timeout_s=90, settings=settings, strict_json=True,
            max_output_tokens=16384, thinking_level='low', max_models=3, total_timeout_s=120, workflow='house_photo',
            attempts=attempts,
            images=[{'mime': e.get('mime') or 'image/jpeg', 'b64': e['photo_b64']},
                    {'mime': 'image/png', 'b64': render_png_b64}])
    except Exception as ex:
        result['reasons'] = [f'critique failed ({ex}); press Compare to photo to retry.']
        return finish(result, retryable=True)
    if not isinstance(res, dict) or res.get('error'):
        result['reasons'] = [f"critique failed ({(res or {}).get('error', 'bad response') if isinstance(res, dict) else 'bad response'})"]
        return finish(result, retryable=True)
    reasons = [str(r)[:160] for r in (res.get('reasons') or []) if isinstance(r, (str, dict))][:8]
    reasons = [r if isinstance(r, str) else str(r.get('reason', r)) for r in reasons]
    snap_notes = []
    trace = e.setdefault('photo_trace', {})
    trace['revision_raw'] = copy.deepcopy(res.get('revised'))
    revised, errs = _validate_photo_model(_snap_fractions(res.get('revised'), snap_notes), snap_notes)
    trace['revision_before_normalization'] = copy.deepcopy(revised)
    trace['revision_validation_errors'] = list(errs)
    if errs:
        result['reasons'] = reasons + snap_notes + ['revision rejected as incomplete: ' + '; '.join(errs[:3])]
    else:
        spec, notes = normalize(copy.deepcopy(revised))
        notes += restore_missing_upper_windows(spec, observed, len(slot_table()))
        trace['revision_normalization_notes'] = list(snap_notes + notes)
        after_issues = structural_issues(spec, observed, len(slot_table()))
        trace['revision_structural_issues'] = list(after_issues)
        if not set(after_issues).issubset(set(before_issues)):
            result['reasons'] = reasons + snap_notes + notes + ['Revision withheld: it introduces structural discrepancies.'] + after_issues
            return finish(result)
        result['revised'] = spec
        result['reasons'] = reasons + snap_notes + notes + ['Still needs review: ' + x for x in after_issues]
        result['unexpressed'] = list(spec.get('unexpressed') or [])
    return finish(result)


def active_bundle():
    fid = _settings().get('house_facade_active') or CANONICAL_ID
    rec = next((r for r in _saved() if r['id'] == fid), None)
    if rec is None:
        spec = copy.deepcopy(CANONICAL)
        return {'id': CANONICAL_ID, 'name': 'Canonical', 'spec': spec,
                'slots': slot_table(spec['blocks'], spec['upper'])}
    spec, _ = normalize(rec.get('spec'))
    # MASSING ARC 2 task 10: every bundle's slots follow ITS OWN blocks. A
    # deeper or two-storey block moves its face's z and raises its eave, and
    # house.js builds features against the table that rides the page -- so a
    # canonical table under a non-canonical spec put every window on the
    # wrong plane.
    return {'id': rec['id'], 'name': rec.get('name') or 'Saved facade', 'spec': spec,
            'slots': slot_table(spec['blocks'], spec['upper'])}


# --- drafts (spec 2026-09-17 section 4: token lifecycle) ---
# A draft is a spec this PROCESS holds for fifteen minutes under a token
# nobody can forge: /house?draft=<token> renders it, and nothing about it
# is ever stored. The token carries its own issue time and an HMAC over
# (photo, spec, issued) -- so a tampered or aged token resolves to
# nothing and the page quietly falls back to the active facade.
_DRAFT_SECRET = secrets.token_bytes(32)
_DRAFTS = {}
DRAFT_TTL_S = 900
# FINAL REVIEW (important 4): the window is fifteen minutes and every entry
# holds the photo's bytes, so an unbounded cache was a memory ceiling nobody
# set. Eight drafts is more than any one review session opens; the oldest
# goes first, and its token simply stops resolving (the page already falls
# back to the active facade, and the editor now says so out loud).
DRAFT_MAX = 8
# One critical section guards the read-and-mark in critique(); see there.
_CRITIQUE_LOCK = threading.Lock()


def _sha(s):
    return hashlib.sha256((s or '').encode('utf-8') if isinstance(s, str) else (s or b'')).hexdigest()


def _sign(photo_sha, spec_sha, issued_ms):
    return hmac.new(_DRAFT_SECRET, f'{photo_sha}|{spec_sha}|{issued_ms}'.encode(), 'sha256').hexdigest()[:32]


def _sweep(now_ms):
    for k in [k for k, v in _DRAFTS.items() if now_ms - v['issued'] > DRAFT_TTL_S * 1000]:
        _DRAFTS.pop(k, None)


def issue_draft(spec, photo=None, mime=None, viewpoint=None, requests=0):
    """A normalized spec (plus, optionally, the photo it came from) becomes
    a token /house can render. Returns the token; stores nothing on disk.
    Two drafts issued in the same millisecond must never collide: a
    same-millisecond re-issue bumps the clock rather than overwriting the
    first token's entry."""
    now_ms = int(time.time() * 1000)
    _sweep(now_ms)
    while len(_DRAFTS) >= DRAFT_MAX:
        _DRAFTS.pop(min(_DRAFTS, key=lambda k: _DRAFTS[k]['issued']), None)
    spec_sha = _sha(json.dumps(spec, sort_keys=True))
    photo_sha = _sha(photo or '')
    tok = f'{now_ms:x}.{_sign(photo_sha, spec_sha, now_ms)}'
    while tok in _DRAFTS:
        now_ms += 1
        tok = f'{now_ms:x}.{_sign(photo_sha, spec_sha, now_ms)}'
    _DRAFTS[tok] = {'spec': copy.deepcopy(spec), 'photo_b64': photo, 'mime': mime,
                    'viewpoint': viewpoint, 'issued': now_ms, 'spec_sha': spec_sha,
                    'photo_sha': photo_sha, 'result': None, 'requests': int(requests or 0)}
    return tok


def draft_for(token):
    """The draft behind a token, or None -- expired, tampered or unknown."""
    now_ms = int(time.time() * 1000)
    _sweep(now_ms)
    e = _DRAFTS.get(token or '')
    if not e:
        return None
    try:
        issued = int(token.split('.')[0], 16)
    except ValueError:
        return None
    if not hmac.compare_digest(token.split('.')[1], _sign(e['photo_sha'], e['spec_sha'], issued)):
        return None
    return e


def store_result(token, result):
    """A model's answer rides the token it was asked about."""
    e = draft_for(token)
    if e is not None:
        e['result'] = result

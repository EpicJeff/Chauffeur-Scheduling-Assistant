"""The Home's facade generator (spec docs/superpowers/specs/
2026-09-15-house-facade-generator-design.md).

Pure functions above the line, storage below it. The slot table and the
canonical facade are the JS side's single source of truth too: a live
test pins window.chfFacadeSlots() against slot_table()."""
import copy
import math
import time
import uuid

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
# section 2): the facade speaks a version-2 BLOCK MODEL. Cladding, body,
# base band, depth, stories and roof form/ridge/pitch are per BLOCK;
# `style` keeps only the four roles that are not a block's own skin.
GROUND_KINDS = ('wall', 'window', 'door', 'garage_door', 'porch')
ROOF_KINDS = ('eave', 'gable', 'dormer', 'shed', 'hip_end')
WINDOW_SIZES = ('tall', 'standard', 'small')
PORCH_TYPES = ('sitting', 'stoop', 'covered')
PORCH_ROOFS = ('flat', 'gable')
GARAGE_STYLES = ('carriage', 'panel', 'glass')
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
MAX_WINDOWS = 10
MAX_DORMERS = 6
MAX_GABLES = 4
MAX_PORCH_SLOTS = 10

_GROUND_RANK = {'garage_door': 3, 'door': 2, 'window': 1}      # exclusive kinds
_ROOF_RANK = {'gable': 3, 'dormer': 2, 'shed': 2, 'hip_end': 1}


def _block(**over):
    b = {'depth': 0.0, 'stories': 1,
         'roof': {'form': 'gable', 'ridge': 'x', 'pitch_deg': BLOCK_PITCH_DEG},
         'cladding': 'batten', 'base': None, 'body': 'white'}
    b.update(over)
    return b


CANONICAL = {
    'version': 2,
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
    'unexpressed': [],
}

# Which block stands behind each street face, and back again.
BLOCK_OF_FACE = {'garage_block': 'garage', 'main': 'main'}
FACE_OF_BLOCK = {'garage': 'garage_block', 'main': 'main'}


def block_face(name):
    """The street face a block fronts ('garage' -> 'garage_block')."""
    return FACE_OF_BLOCK.get(name)


def slot_table(blocks=None):
    """Slots per street face. `blocks` (a V2 `blocks` dict) moves each face
    by its depth and raises its eave by its stories; None = canonical."""
    blocks = blocks or CANONICAL['blocks']
    out, i = [], 0
    for f in FACES:
        b = blocks.get(BLOCK_OF_FACE[f['face']]) or {}
        z = f['z'] + float(b.get('depth') or 0)
        eave = f['eave'] * (2 if b.get('stories') == 2 else 1)
        width = f['x1'] - f['x0']
        n = max(1, int(round(width / SLOT_W)))
        w = width / n
        for k in range(n):
            x0 = f['x0'] + k * w
            out.append({'i': i, 'face': f['face'], 'x0': round(x0, 6), 'x1': round(x0 + w, 6),
                        'cx': round(x0 + w / 2, 6), 'z': round(z, 6), 'eave': eave,
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


def validate_block_model(obj):
    """Structural validation of a MODEL-produced block model (spec 2026-09-17
    section 4). Returns a list of error strings; [] means valid. Never
    mutates and never fills a default: that is normalize's job, and only
    a validated object may reach it from the photo pipeline."""
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
            errs.append(f'{path}.{key} not one of {list(allowed)}')
        return v

    def rng(d, key, lo, hi, path):
        v = need(d, key, float, path)
        if v is not None and not (lo <= v <= hi):
            errs.append(f'{path}.{key} out of range {lo}..{hi}')
        return v

    if obj.get('version') != 2:
        errs.append('version must be 2')
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
            st = need(b, 'stories', int, p)
            if st is not None and st not in (1, 2):
                errs.append(f'{p}.stories must be 1 or 2')
            roof = need(b, 'roof', dict, p)
            if roof is not None:
                enum(roof, 'form', ROOF_FORMS, p + '.roof')
                enum(roof, 'ridge', RIDGES, p + '.roof')
                rng(roof, 'pitch_deg', PITCH_MIN, PITCH_MAX, p + '.roof')
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
            if kind in ('wall', 'eave'):
                continue
            for key in _FEATURE_REQUIRED.get(kind, ()):
                if key not in e:
                    errs.append(f'{p}.{key} missing')
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
            item['story'] = 2 if _int(e.get('story'), 1) == 2 else 1
        elif kind == 'porch':
            item['type'] = _pick(e.get('type'), PORCH_TYPES, 'covered')
            item['roof'] = _pick(e.get('roof'), PORCH_ROOFS, 'flat')
        elif kind == 'garage_door':
            item['style'] = _pick(e.get('style'), GARAGE_STYLES, 'carriage')
            item['leaves'] = 2 if _int(e.get('leaves'), 1) == 2 else 1
        elif kind in ('dormer', 'shed'):
            item['window'] = bool(e.get('window', True))
        # a roof feature may override its parent block's cladding (spec 2)
        if layer == 'roof' and e.get('cladding') in CLADDINGS:
            item['cladding'] = e['cladding']
        out.append(item)
    return out


def _clip_to_face(item, notes):
    """Spans never cross a face (spec 4.3). The garage BAY is a hard
    boundary too (spec 4.4: the garage door always spans its own bay) --
    task 3 merged the old 3-slot 'garage' face into the 6-slot
    garage_block face, so without this a feature starting in the bay
    (slots 0-2) could otherwise run on into the mudroom's ordinary roof
    slots (3-5). A feature starting in the bay is clipped to the bay,
    not the whole face."""
    slots = slot_table()
    face = slots[item['slot']]['face']
    lo, hi = _face_range(face)
    bay_lo, bay_hi = GARAGE_BAY_SLOTS
    if bay_lo <= item['slot'] <= bay_hi:
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
    b['stories'] = 2 if _int(raw.get('stories'), 1) == 2 else 1
    rr = raw.get('roof') if isinstance(raw.get('roof'), dict) else {}
    b['roof'] = {'form': _pick(rr.get('form'), ROOF_FORMS, 'gable'),
                 'ridge': _pick(rr.get('ridge'), RIDGES, 'x'),
                 'pitch_deg': round(min(PITCH_MAX, max(PITCH_MIN, _num(rr.get('pitch_deg'), BLOCK_PITCH_DEG))), 1)}
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
    return b


def normalize(raw):
    notes = []
    raw = raw if isinstance(raw, dict) else {}
    # A facade with no `blocks` is a version-1 one: run it through the
    # mapping table first, then apply every V2 law to the result.
    if 'blocks' not in raw:
        raw = _upgrade_v1(raw, notes)
    spec = {'version': 2, 'mirror': bool(raw.get('mirror', False))}
    p = _num(raw.get('pitch_deg'), CANONICAL['pitch_deg'])
    spec['pitch_deg'] = round(min(PITCH_MAX, max(PITCH_MIN, p)), 1)
    blocks_raw = raw.get('blocks') if isinstance(raw.get('blocks'), dict) else {}
    spec['blocks'] = {'main': _norm_block('main', blocks_raw.get('main'), notes),
                      'garage': _norm_block('garage', blocks_raw.get('garage'), notes)}
    st = raw.get('style') if isinstance(raw.get('style'), dict) else {}
    spec['style'] = {k: _pick(st.get(k), allowed, CANONICAL['style'][k])
                     for k, allowed in STYLE.items() if k != 'body'}

    ground = _entries(raw.get('ground'), GROUND_KINDS, notes, 'ground')
    roof = _entries(raw.get('roof'), ROOF_KINDS, notes, 'roof')
    slots = slot_table(spec['blocks'])

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
        _clip_to_face(r, notes)

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

    # story-2 entries only on a two-story block; overlap resolved PER story
    def block_of(item):
        return BLOCK_OF_FACE[slots[item['slot']]['face']]
    kept = []
    for g in ground:
        if g.get('story') == 2 and spec['blocks'][block_of(g)]['stories'] != 2:
            notes.append(f"dropped a story-2 {g['kind']} at slot {g['slot']}: that block has one story")
            continue
        kept.append(g)
    ground = kept
    porches = [g for g in ground if g['kind'] == 'porch']
    s1 = [g for g in ground if g['kind'] != 'porch' and g.get('story', 1) == 1]
    s2 = [g for g in ground if g['kind'] != 'porch' and g.get('story') == 2]
    exclusive = _resolve_exclusive(s1, _GROUND_RANK, notes) + _resolve_exclusive(s2, _GROUND_RANK, notes)
    # a gabled porch owns its roof: a gable FEATURE covering it is dropped
    for pch in porches:
        if pch['roof'] != 'gable':
            continue
        n0 = len(roof)
        roof = [r for r in roof
                if not (r['kind'] == 'gable' and r['slot'] < pch['slot'] + pch['span']
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
    dormer_windows = sum(1 for r in roof if r['kind'] == 'dormer' and r['window'])
    exclusive = cap(exclusive, 'window', MAX_WINDOWS, extra=dormer_windows)
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
    windows = MAX_WINDOWS - dormers
    for s in slots[g_hi + 1:]:
        if s['i'] == m_lo or windows <= 0:
            continue
        ground.append({'slot': s['i'], 'span': 1, 'kind': 'window', 'size': 'tall',
                       'shutters': True, 'story': 1})
        windows -= 1
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
    # The heaviest BLOCK model too (spec 2026-09-17 section 2): two
    # stories on both, a different cladding per block plus a base band in
    # a third material (each distinct material/body pair is at least one
    # more static draw), the garage as deep as the schema allows and the
    # main at the porch's curb clamp. A SIDE garage is lighter, not
    # heavier -- it deletes the garage door -- so the orientation stays
    # front, and mirror costs nothing (one root scale).
    blocks = {
        'main': {'depth': DEPTH_MAX_WITH_PORCH, 'stories': 2,
                 'roof': {'form': 'gable', 'ridge': 'x', 'pitch_deg': PITCH_MAX},
                 'cladding': 'brick', 'body': 'brick_red',
                 'base': {'material': 'stone', 'height': BASE_H_MAX, 'body': 'stone_grey'}},
        'garage': {'depth': DEPTH_MAX, 'stories': 2, 'orientation': 'front',
                   'roof': {'form': 'gable', 'ridge': 'x', 'pitch_deg': PITCH_MAX},
                   'cladding': 'stone', 'body': 'stone_grey',
                   'base': {'material': 'brick', 'height': BASE_H_MAX, 'body': 'painted_brick'}},
    }
    spec, _ = normalize({'version': 2, 'mirror': False, 'pitch_deg': PITCH_MAX, 'blocks': blocks,
                         'style': {'roof': 'brown', 'frame': 'white', 'door': 'red', 'trim': 'black'},
                         'ground': ground, 'roof': roof, 'unexpressed': []})
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
    return [{'id': CANONICAL_ID, 'name': 'Canonical', 'readonly': True,
             'source': 'builtin', 'spec': copy.deepcopy(CANONICAL)}] + copy.deepcopy(_saved())


def save_facade(name, spec, activate=False, source='hand'):
    clean, _ = normalize(spec)
    now = time.time()
    rec = {'id': uuid.uuid4().hex[:12], 'name': (str(name or '').strip() or 'My house')[:60],
           'spec': clean, 'source': source if source in ('hand', 'photo') else 'hand',
           'created_at': now, 'updated_at': now}
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
                r['spec'], _ = normalize(spec)
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


PHOTO_SYSTEM = """You describe the STREET-FACING elevation of a house from one photo, as JSON only.
The house is drawn on a fixed strip of {n} slots, west to east (left to right as seen from the street):
{faces}
Slot numbers are global (0..{last}). Report only what is on the street face.
Return exactly this shape:
{{"pitch_deg": number between 22.5 and 35, "style": {{"cladding": "batten"|"clapboard", "body": one of {body}, "roof": one of {roof}, "frame": one of {frame}, "door": one of {door}, "trim": one of {trim}}},
  "ground": [{{"slot": int, "span": int, "kind": "window", "size": "tall"|"standard"|"small"}} | {{"slot","span","kind":"door"}} | {{"slot","span","kind":"garage_door","style":"carriage"|"panel"|"glass","leaves":1|2}} | {{"slot","span","kind":"porch","type":"sitting"|"stoop"|"covered"}}],
  "roof": [{{"slot": int, "span": int, "kind": "gable"|"dormer"|"hip_end", "window": bool}}]}}
Rules: colours are the NEAREST palette name, never hex. If the garage is not visible, omit it. If unsure of a count, prefer fewer windows. The front door goes on the main face. No prose."""


def _photo_prompt():
    faces = '\n'.join(f"- {f['face']}: slots {_face_range(f['face'])[0]}..{_face_range(f['face'])[1]}"
                      for f in FACES)
    n = len(slot_table())
    return PHOTO_SYSTEM.format(n=n, last=n - 1, faces=faces,
                               body=list(STYLE['body']), roof=list(STYLE['roof']),
                               frame=list(STYLE['frame']), door=list(STYLE['door']),
                               trim=list(STYLE['trim']))


def from_photo(image_b64, mime):
    """One photo -> a DRAFT facade (normalized) or an error. Never stores."""
    from services import model_pools
    settings = _settings()
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key:
        return None, [], 'no LLM API key configured'
    try:
        res = model_pools.call_pool_json(
            'vision', api_key, _photo_prompt(),
            'Describe the street-facing elevation of the house in the attached photo.',
            temperature=0.1, timeout_s=90, settings=settings, strict_json=True,
            max_output_tokens=2048,
            images=[{'mime': mime or 'image/jpeg', 'b64': image_b64}])
    except Exception as e:
        return None, [], f'could not read the photo ({e})'
    if not isinstance(res, dict):
        return None, [], 'could not read the photo (bad response)'
    if res.get('error'):
        return None, [], f"could not read the photo ({res['error']})"
    spec, notes = normalize(res)
    return spec, notes, None


def active_bundle():
    fid = _settings().get('house_facade_active') or CANONICAL_ID
    rec = next((r for r in _saved() if r['id'] == fid), None)
    if rec is None:
        return {'id': CANONICAL_ID, 'name': 'Canonical', 'spec': copy.deepcopy(CANONICAL), 'slots': slot_table()}
    spec, _ = normalize(rec.get('spec'))
    return {'id': rec['id'], 'name': rec.get('name') or 'Saved facade', 'spec': spec, 'slots': slot_table()}

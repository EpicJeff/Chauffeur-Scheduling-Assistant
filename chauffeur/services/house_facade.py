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
# West to east. Mirrors house.js: FULL_HOUSE, SWZ1, EXT_TOP4, the garage IIFE.
FACES = [
    {'face': 'garage',  'x0': -18.20, 'x1': -12.60, 'z': 10.10, 'eave': 4.7, 'room': 'garage',  'roof': 'massing_service_roof'},
    {'face': 'mudroom', 'x0': -12.60, 'x1': -7.15,  'z': 10.10, 'eave': 5.6, 'room': 'mudroom', 'roof': 'mudroom_cross_roof'},
    {'face': 'main',    'x0': -7.15,  'x1': 6.85,   'z': 14.55, 'eave': 5.6, 'room': 'living',  'roof': 'roof_main'},
    {'face': 'wing',    'x0': 6.85,   'x1': 14.65,  'z': 16.72, 'eave': 5.6, 'room': 'study',   'roof': 'massing_front_roof'},
]

GROUND_KINDS = ('wall', 'window', 'door', 'garage_door', 'porch')
ROOF_KINDS = ('eave', 'gable', 'dormer', 'hip_end')
WINDOW_SIZES = ('tall', 'standard', 'small')
PORCH_TYPES = ('sitting', 'stoop', 'covered')
GARAGE_STYLES = ('carriage', 'panel', 'glass')
STYLE = {
    'cladding': ('batten', 'clapboard'),
    'body': ('white', 'greige', 'sage', 'slate', 'navy'),
    'roof': ('charcoal', 'weathered', 'brown'),
    'frame': ('black', 'white'),
    'door': ('wood', 'black', 'red', 'sage'),
    'trim': ('white', 'black'),
}
PITCH_MIN, PITCH_MAX = 22.5, 35.0
# Draw-budget constants, not grammar (spec 4.7). Tuned in the probe task.
MAX_WINDOWS = 10
MAX_DORMERS = 6
MAX_GABLES = 4
MAX_PORCH_SLOTS = 10

_GROUND_RANK = {'garage_door': 3, 'door': 2, 'window': 1}      # exclusive kinds
_ROOF_RANK = {'gable': 3, 'dormer': 2, 'hip_end': 1}


def slot_table():
    out, i = [], 0
    for f in FACES:
        width = f['x1'] - f['x0']
        n = max(1, int(round(width / SLOT_W)))
        w = width / n
        for k in range(n):
            x0 = f['x0'] + k * w
            out.append({'i': i, 'face': f['face'], 'x0': round(x0, 6), 'x1': round(x0 + w, 6),
                        'cx': round(x0 + w / 2, 6), 'z': f['z'], 'eave': f['eave'],
                        'room': f['room'], 'roof': f['roof']})
            i += 1
    return out


def _face_range(face):
    idx = [s['i'] for s in slot_table() if s['face'] == face]
    return idx[0], idx[-1]


CANONICAL = {
    'version': 1,
    'pitch_deg': round(math.degrees(math.atan2(2.05, 2.95)), 1),   # 34.8, PITCH_FAMILY
    'style': {'cladding': 'batten', 'body': 'white', 'roof': 'charcoal',
              'frame': 'black', 'door': 'wood', 'trim': 'white'},
    'ground': [
        {'slot': 0, 'span': 3, 'kind': 'garage_door', 'style': 'carriage', 'leaves': 1},
        {'slot': 7, 'span': 1, 'kind': 'window', 'size': 'tall'},
        {'slot': 9, 'span': 4, 'kind': 'porch', 'type': 'sitting'},   # sorted by (slot, kind): porch < window
        {'slot': 9, 'span': 1, 'kind': 'window', 'size': 'tall'},
        {'slot': 10, 'span': 1, 'kind': 'door'},
        {'slot': 12, 'span': 1, 'kind': 'window', 'size': 'tall'},
        {'slot': 15, 'span': 1, 'kind': 'window', 'size': 'standard'},
        {'slot': 16, 'span': 1, 'kind': 'window', 'size': 'standard'},
    ],
    'roof': [
        {'slot': 0, 'span': 3, 'kind': 'gable'},
        {'slot': 9, 'span': 4, 'kind': 'gable'},
    ],
}


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
        elif kind == 'porch':
            item['type'] = _pick(e.get('type'), PORCH_TYPES, 'covered')
        elif kind == 'garage_door':
            item['style'] = _pick(e.get('style'), GARAGE_STYLES, 'carriage')
            item['leaves'] = 2 if _int(e.get('leaves'), 1) == 2 else 1
        elif kind == 'dormer':
            item['window'] = bool(e.get('window', True))
        out.append(item)
    return out


def _clip_to_face(item, notes):
    """Spans never cross a face (spec 4.3)."""
    slots = slot_table()
    face = slots[item['slot']]['face']
    lo, hi = _face_range(face)
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


def normalize(raw):
    notes = []
    raw = raw if isinstance(raw, dict) else {}
    slots = slot_table()
    spec = {'version': 1}
    p = _num(raw.get('pitch_deg'), CANONICAL['pitch_deg'])
    spec['pitch_deg'] = round(min(PITCH_MAX, max(PITCH_MIN, p)), 1)
    st = raw.get('style') if isinstance(raw.get('style'), dict) else {}
    spec['style'] = {k: _pick(st.get(k), allowed, CANONICAL['style'][k])
                     for k, allowed in STYLE.items()}

    ground = _entries(raw.get('ground'), GROUND_KINDS, notes, 'ground')
    roof = _entries(raw.get('roof'), ROOF_KINDS, notes, 'roof')

    # pin openings to their room's face (spec 4.4)
    g_lo, g_hi = _face_range('garage')
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

    # faces are hard boundaries; porch never in the driveway (spec 4.3, 4.5)
    kept = []
    for g in ground:
        face = _clip_to_face(g, notes)
        if g['kind'] == 'porch' and face == 'garage':
            notes.append('no porch in the driveway (garage face)')
            continue
        kept.append(g)
    ground = kept
    for r in roof:
        _clip_to_face(r, notes)

    porches = [g for g in ground if g['kind'] == 'porch']
    exclusive = _resolve_exclusive([g for g in ground if g['kind'] != 'porch'], _GROUND_RANK, notes)
    roof = _resolve_exclusive(roof, _ROOF_RANK, notes)

    # budget caps, east-most first (spec 4.7)
    def cap(items, kind, limit, extra=0):
        own = sorted([i for i in items if i['kind'] == kind], key=lambda i: i['slot'])
        keep = max(0, limit - extra)
        if len(own) > keep:
            notes.append(f"kept {keep} {kind}s of {len(own)} (draw budget)")
        drop = {id(i) for i in own[keep:]}
        return [i for i in items if id(i) not in drop]
    roof = cap(roof, 'dormer', MAX_DORMERS)
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

    ground = sorted(exclusive + porches, key=lambda g: (g['slot'], g['kind']))
    spec['ground'] = ground
    spec['roof'] = sorted(roof, key=lambda r: (r['slot'], r['kind']))
    return spec, notes


def worst_case():
    """The heaviest spec the caps allow — the budget probe's input."""
    slots = slot_table()
    g_lo, g_hi = _face_range('garage')
    m_lo, m_hi = _face_range('main')
    ground = [{'slot': g_lo, 'span': g_hi - g_lo + 1, 'kind': 'garage_door', 'style': 'glass', 'leaves': 2},
              {'slot': m_lo, 'span': 1, 'kind': 'door'}]
    roof = []
    dormers = 0
    for s in slots:
        if s['face'] != 'garage' and dormers < MAX_DORMERS:
            roof.append({'slot': s['i'], 'span': 1, 'kind': 'dormer', 'window': True})
            dormers += 1
    windows = MAX_WINDOWS - dormers
    for s in slots[g_hi + 1:]:
        if s['i'] == m_lo or windows <= 0:
            continue
        ground.append({'slot': s['i'], 'span': 1, 'kind': 'window', 'size': 'tall'})
        windows -= 1
    ground.append({'slot': m_lo, 'span': min(MAX_PORCH_SLOTS, m_hi - m_lo + 1), 'kind': 'porch', 'type': 'sitting'})
    left = MAX_PORCH_SLOTS - (m_hi - m_lo + 1)
    if left > 0:
        ground.append({'slot': m_hi + 1, 'span': left, 'kind': 'porch', 'type': 'sitting'})
    gables = 0
    for s in slots:
        if gables >= MAX_GABLES:
            break
        if s['i'] not in {r['slot'] for r in roof}:
            roof.append({'slot': s['i'], 'span': 1, 'kind': 'gable'})
            gables += 1
    spec, _ = normalize({'version': 1, 'pitch_deg': PITCH_MAX,
                         'style': {'cladding': 'clapboard', 'body': 'navy', 'roof': 'brown',
                                   'frame': 'white', 'door': 'red', 'trim': 'black'},
                         'ground': ground, 'roof': roof})
    return spec


# --- storage ---

CANONICAL_ID = 'canonical'


def _settings():
    from services import storage
    return storage.get_settings() or {}


def _write(patch):
    from services import storage
    cur = dict(storage.get_settings() or {})
    cur.update(patch)
    storage.update_settings(cur)


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
        return None, 'no LLM API key configured'
    try:
        res = model_pools.call_pool_json(
            'vision', api_key, _photo_prompt(),
            'Describe the street-facing elevation of the house in the attached photo.',
            temperature=0.1, timeout_s=90, settings=settings, strict_json=True,
            images=[{'mime': mime or 'image/jpeg', 'b64': image_b64}])
    except Exception as e:
        return None, f'could not read the photo ({e})'
    if not isinstance(res, dict):
        return None, 'could not read the photo (bad response)'
    if res.get('error'):
        return None, f"could not read the photo ({res['error']})"
    spec, _ = normalize(res)
    return spec, None


def active_bundle():
    fid = _settings().get('house_facade_active') or CANONICAL_ID
    rec = next((r for r in _saved() if r['id'] == fid), None)
    if rec is None:
        return {'id': CANONICAL_ID, 'name': 'Canonical', 'spec': copy.deepcopy(CANONICAL), 'slots': slot_table()}
    spec, _ = normalize(rec.get('spec'))
    return {'id': rec['id'], 'name': rec['name'], 'spec': spec, 'slots': slot_table()}

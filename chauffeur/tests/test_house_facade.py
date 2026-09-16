"""The facade generator's laws (spec docs/superpowers/specs/
2026-09-15-house-facade-generator-design.md sections 2 and 4). Pure:
no storage, no browser."""
import copy
import json

from harness import check
from services import house_facade as hf


def _spec(**over):
    s = copy.deepcopy(hf.CANONICAL)
    s.update(over)
    return s


def scenario_slot_table_is_derived_from_the_faces():
    slots = hf.slot_table()
    check([s['face'] for s in slots].count('garage_block') == 6, 'garage_block face: 6 slots')
    check([s['face'] for s in slots].count('main') == 12, 'main face: 12 slots')
    check(len(slots) == 18 and [s['i'] for s in slots] == list(range(18)),
          'eighteen slots, indexed west to east')
    for a, b in zip(slots, slots[1:]):
        if a['face'] == b['face']:
            check(abs(a['x1'] - b['x0']) < 1e-9, 'slots tile their face')
    for f in hf.FACES:
        own = [s for s in slots if s['face'] == f['face']]
        check(abs(own[0]['x0'] - f['x0']) < 1e-9 and abs(own[-1]['x1'] - f['x1']) < 1e-9,
              f"{f['face']} slots span exactly the face")
        widths = {round(s['x1'] - s['x0'], 5) for s in own}
        check(len(widths) == 1, f"{f['face']} slots are uniform: {widths}")
    # MASSING ARC 1 task 3: main is the merged main+wing front (-7.15..14.65,
    # 21.8 wide / 12 slots = 1.816667 each); centres computed, not guessed
    # (task-3-report.md shows the `python -c` derivation).
    main = [s for s in slots if s['face'] == 'main']
    check(abs(main[0]['cx'] - (-6.241667)) < 1e-6 and abs(main[4]['cx'] - 1.025) < 1e-6,
          f"main centres per spec section 5: {[round(s['cx'], 6) for s in main]}")


def scenario_canonical_is_normal_and_idempotent():
    spec, notes = hf.normalize(hf.CANONICAL)
    check(spec == hf.CANONICAL, f'canonical survives normalize unchanged; notes {notes}')
    check(notes == [], 'canonical raises no notes')
    again, _ = hf.normalize(spec)
    check(again == spec, 'idempotent')
    json.dumps(spec)  # serialisable


def scenario_unknown_enums_fall_to_defaults():
    raw = _spec(style={'cladding': 'stucco', 'body': 'pink', 'roof': 'x',
                       'frame': 'y', 'door': 'z', 'trim': 'w'},
                ground=[{'slot': 9, 'span': 1, 'kind': 'window', 'size': 'huge'},
                        {'slot': 10, 'span': 1, 'kind': 'porch', 'type': 'wraparound'},
                        {'slot': 11, 'span': 1, 'kind': 'skylight'}])
    spec, notes = hf.normalize(raw)
    check(spec['style'] == hf.CANONICAL['style'], f"style defaults: {spec['style']}")
    kinds = {(g['slot'], g['kind']) for g in spec['ground']}
    check((9, 'window') in kinds and (11, 'skylight') not in kinds, 'unknown kind dropped')
    win = next(g for g in spec['ground'] if g['slot'] == 9)
    check(win['size'] == 'standard', 'unknown window size -> standard')
    porch = next(g for g in spec['ground'] if g['kind'] == 'porch')
    check(porch['type'] == 'covered', 'unknown porch type -> covered')
    check(any('skylight' in n for n in notes), 'the drop is noted')


def scenario_pitch_clamps():
    check(hf.normalize(_spec(pitch_deg=50))[0]['pitch_deg'] == 35.0, 'high clamps')
    check(hf.normalize(_spec(pitch_deg=5))[0]['pitch_deg'] == 22.5, 'low clamps')
    check(hf.normalize(_spec(pitch_deg='steep'))[0]['pitch_deg'] == hf.CANONICAL['pitch_deg'],
          'garbage -> canonical')


def scenario_spans_truncate_at_face_boundaries():
    # slot 5 is garage_block's east-most (0..5 are garage_block, 6..17 main);
    # a window spanning 4 from slot 4 would cross into main.
    raw = _spec(ground=[{'slot': 10, 'span': 1, 'kind': 'door'},
                        {'slot': 4, 'span': 4, 'kind': 'window', 'size': 'small'}])
    spec, notes = hf.normalize(raw)
    win = next(g for g in spec['ground'] if g['kind'] == 'window')
    check(win['slot'] == 4 and win['span'] == 2,
          f'window truncated at the garage_block boundary: {win}')
    check(any('face' in n for n in notes), 'truncation noted')


def scenario_openings_pin_to_their_room_face():
    raw = _spec(ground=[{'slot': 2, 'span': 1, 'kind': 'door'},                       # on the garage block
                        {'slot': 8, 'span': 2, 'kind': 'garage_door', 'style': 'glass', 'leaves': 2}])
    spec, notes = hf.normalize(raw)
    door = [g for g in spec['ground'] if g['kind'] == 'door']
    gd = [g for g in spec['ground'] if g['kind'] == 'garage_door']
    slots = hf.slot_table()
    check(len(door) == 1 and slots[door[0]['slot']]['face'] == 'main', f'door moved to main: {door}')
    check(len(gd) == 1 and gd[0]['slot'] == 0 and gd[0]['span'] == 3 and gd[0]['leaves'] == 2,
          f'garage door forced onto its own bay (slots 0-2), not the whole garage_block face: {gd}')
    # no door at all -> the canonical door
    spec2, _ = hf.normalize(_spec(ground=[]))
    check(any(g['kind'] == 'door' for g in spec2['ground']), 'at least one door always')
    # any number of doors on the main face is fine
    spec3, _ = hf.normalize(_spec(ground=[{'slot': 7, 'span': 1, 'kind': 'door'},
                                          {'slot': 11, 'span': 1, 'kind': 'door'}]))
    check(sum(g['kind'] == 'door' for g in spec3['ground']) == 2, 'two doors survive')


def scenario_overlap_priority_trims_the_loser():
    raw = _spec(ground=[{'slot': 7, 'span': 5, 'kind': 'window', 'size': 'small'},
                        {'slot': 9, 'span': 1, 'kind': 'door'}])
    spec, notes = hf.normalize(raw)
    wins = sorted((g['slot'], g['span']) for g in spec['ground'] if g['kind'] == 'window')
    check(wins == [(7, 2), (10, 2)], f'window split around the door: {wins}')
    # porch is an overlay: shares with door and windows, never trims
    raw = _spec(ground=[{'slot': 7, 'span': 5, 'kind': 'porch', 'type': 'sitting'},
                        {'slot': 8, 'span': 1, 'kind': 'window', 'size': 'tall'},
                        {'slot': 9, 'span': 1, 'kind': 'door'}])
    spec, _ = hf.normalize(raw)
    kinds = sorted(g['kind'] for g in spec['ground'])
    check(kinds == ['door', 'porch', 'window'], f'porch overlays: {kinds}')
    # but never in the garage BAY (the driveway) -- slots 0-2 of the
    # merged garage_block face; see the scenario below for the mudroom
    # half of that same face, where a porch is legal.
    spec, notes = hf.normalize(_spec(ground=[{'slot': 10, 'span': 1, 'kind': 'door'},
                                             {'slot': 0, 'span': 2, 'kind': 'porch', 'type': 'stoop'}]))
    check(not any(g['kind'] == 'porch' for g in spec['ground']), 'no porch in the driveway')
    check(any('driveway' in n or 'garage' in n for n in notes), 'noted')


def scenario_porch_is_barred_from_the_bay_not_the_whole_block():
    """MASSING ARC 1 fix wave (ruling 2026-09-16, ledger "Final: Ruling"):
    the no-porch rule keys on GARAGE_BAY_SLOTS, not on the garage_block
    FACE.

    Before this arc the driveway side was a 3-slot 'garage' face and the
    mudroom had a face of its own; a porch in front of the mudroom door
    was legal and a saved facade could carry one. Task 3 merged the two
    faces into the 6-slot garage_block, and the rule -- still keyed on
    the face name -- silently widened to cover the mudroom's slots 3-5,
    dropping a porch a person had placed. The driveway is the BAY."""
    bay_lo, bay_hi = hf.GARAGE_BAY_SLOTS
    # a porch in front of the MUDROOM (slots 3-5) survives
    spec, notes = hf.normalize(_spec(ground=[{'slot': 10, 'span': 1, 'kind': 'door'},
                                             {'slot': 4, 'span': 2, 'kind': 'porch',
                                              'type': 'covered'}]))
    pch = [g for g in spec['ground'] if g['kind'] == 'porch']
    check([(p['slot'], p['span']) for p in pch] == [(4, 2)],
          f'a porch on the mudroom half of garage_block survives: {pch}')
    check(not any('driveway' in n for n in notes), f'and is not noted away: {notes}')
    # a porch in the BAY is still dropped, and still says why
    spec, notes = hf.normalize(_spec(ground=[{'slot': 10, 'span': 1, 'kind': 'door'},
                                             {'slot': 1, 'span': 1, 'kind': 'porch',
                                              'type': 'stoop'}]))
    check(not any(g['kind'] == 'porch' for g in spec['ground']),
          'a porch in the garage bay is still dropped')
    check(any('driveway' in n for n in notes), f'and still noted: {notes}')
    # the boundary itself: the first slot past the bay is legal
    spec, _ = hf.normalize(_spec(ground=[{'slot': 10, 'span': 1, 'kind': 'door'},
                                         {'slot': bay_hi + 1, 'span': 1,
                                          'kind': 'porch', 'type': 'stoop'}]))
    check(any(g['kind'] == 'porch' for g in spec['ground']),
          f'slot {bay_hi + 1} is the mudroom, not the driveway')
    # ...and the last slot of the bay is not
    spec, _ = hf.normalize(_spec(ground=[{'slot': 10, 'span': 1, 'kind': 'door'},
                                         {'slot': bay_hi, 'span': 1,
                                          'kind': 'porch', 'type': 'stoop'}]))
    check(not any(g['kind'] == 'porch' for g in spec['ground']),
          f'slot {bay_hi} is still the driveway')


def scenario_roof_priority_and_no_bans():
    raw = _spec(roof=[{'slot': 6, 'span': 4, 'kind': 'dormer', 'window': True},
                      {'slot': 8, 'span': 2, 'kind': 'gable'},
                      {'slot': 0, 'span': 3, 'kind': 'gable'}])          # garage face gable is fine
    spec, _ = hf.normalize(raw)
    d = [r for r in spec['roof'] if r['kind'] == 'dormer']
    g = sorted((r['slot'], r['span']) for r in spec['roof'] if r['kind'] == 'gable')
    check(d == [{'slot': 6, 'span': 2, 'kind': 'dormer', 'window': True}], f'dormer trimmed: {d}')
    check(g == [(0, 3), (8, 2)], f'both gables kept: {g}')


def scenario_garage_bay_is_a_hard_boundary_for_roof_too():
    # a gable starting inside the garage bay (slots 0-2 of the six-slot
    # garage_block face) must not bleed into the mudroom's ordinary roof
    # slots (3-5): the bay is a hard boundary for roof features exactly
    # as it already is for the garage door itself (spec 4.4).
    raw = _spec(roof=[{'slot': 1, 'span': 4, 'kind': 'gable'}])
    spec, notes = hf.normalize(raw)
    g = next(r for r in spec['roof'] if r['kind'] == 'gable' and r['slot'] == 1)
    check(g['span'] == 2, f'gable clipped to the garage bay, not the whole face: {g}')
    check(any('face' in n for n in notes), 'truncation noted')
    # a gable fully inside the bay is untouched
    raw2 = _spec(roof=[{'slot': 0, 'span': 3, 'kind': 'gable'}])
    spec2, notes2 = hf.normalize(raw2)
    g2 = next(r for r in spec2['roof'] if r['kind'] == 'gable')
    check(g2 == {'slot': 0, 'span': 3, 'kind': 'gable'} and notes2 == [],
          f'a gable already inside the bay is unchanged: {g2} {notes2}')


def scenario_budget_caps_drop_east_most_first():
    ground = [{'slot': i, 'span': 1, 'kind': 'window', 'size': 'tall'} for i in range(6, 14)]
    ground += [{'slot': i, 'span': 1, 'kind': 'window', 'size': 'tall'} for i in range(14, 18)]
    ground += [{'slot': i, 'span': 1, 'kind': 'window', 'size': 'tall'} for i in range(3, 6)]
    ground.append({'slot': 9, 'span': 1, 'kind': 'door'})
    spec, notes = hf.normalize(_spec(ground=ground))
    wins = [g for g in spec['ground'] if g['kind'] == 'window']
    check(len(wins) == hf.MAX_WINDOWS, f'capped at {hf.MAX_WINDOWS}: {len(wins)}')
    check(max(g['slot'] for g in wins) < 17, 'the east-most windows went first')
    check(any('window' in n for n in notes), 'noted')


def scenario_sorted_and_deduped():
    raw = _spec(ground=[{'slot': 9, 'span': 1, 'kind': 'door'},
                        {'slot': 7, 'span': 1, 'kind': 'window', 'size': 'tall'},
                        {'slot': 7, 'span': 1, 'kind': 'window', 'size': 'small'}])
    spec, _ = hf.normalize(raw)
    slots = [g['slot'] for g in spec['ground']]
    check(slots == sorted(slots) and slots.count(7) == 1, f'sorted, one entry per slot: {slots}')


def scenario_wall_and_eave_entries_are_dropped():
    raw = _spec(ground=hf.CANONICAL['ground'] + [{'slot': 3, 'span': 1, 'kind': 'wall'}],
                roof=hf.CANONICAL['roof'] + [{'slot': 3, 'span': 1, 'kind': 'eave'}])
    spec, _ = hf.normalize(raw)
    check(spec == hf.CANONICAL, 'wall/eave are the defaults and never stored')


def scenario_garbage_in_never_raises():
    for raw in (None, 3, 'x', [], {}, {'ground': 'no'}, {'ground': [None, 3, {'kind': 'door'}]},
                {'roof': [{'slot': 'a', 'span': -2, 'kind': 'gable'}]}):
        spec, _ = hf.normalize(raw)
        check(spec['version'] == 1 and any(g['kind'] == 'door' for g in spec['ground']),
              f'{raw!r} -> a valid spec')


def scenario_worst_case_is_within_caps():
    w = hf.worst_case()
    spec, notes = hf.normalize(w)
    check(spec == w, f'worst case is already normal; notes {notes}')
    wins = sum(g['kind'] == 'window' for g in spec['ground'])
    dw = sum(1 for r in spec['roof'] if r['kind'] == 'dormer' and r.get('window'))
    check(wins + dw == hf.MAX_WINDOWS, f'worst case uses every window: {wins}+{dw}')
    check(sum(r['kind'] == 'dormer' for r in spec['roof']) == hf.MAX_DORMERS, 'every dormer')
    check(sum(r['kind'] == 'gable' for r in spec['roof']) == hf.MAX_GABLES, 'every gable')
    check(sum(g['span'] for g in spec['ground'] if g['kind'] == 'porch') == hf.MAX_PORCH_SLOTS,
          'porch slots at the cap')
    gd = next(g for g in spec['ground'] if g['kind'] == 'garage_door')
    check(gd['style'] == 'glass' and gd['leaves'] == 2, 'heaviest garage door')


def _fresh():
    # harness.py replaces storage.get_settings with a constant lambda; the
    # storage laws need the real table, so read it directly.
    from services import storage
    storage.get_settings = lambda: dict((storage.settings_table.all() or [{}])[0])
    storage.update_settings({'calendar_ids': []})


def scenario_storage_laws():
    from services import storage
    _fresh()
    lst = hf.list_facades()
    check(lst[0]['id'] == 'canonical' and lst[0]['readonly'] and len(lst) == 1, 'canonical always listed first')
    check(hf.active_bundle()['id'] == 'canonical', 'canonical active by default')
    rec = hf.save_facade('Ours', hf.worst_case())
    check(rec['id'] and rec['source'] == 'hand' and rec['spec'] == hf.worst_case(), 'saved normalized')
    check(hf.active_bundle()['id'] == 'canonical', 'saving never activates unless asked')
    check(hf.set_active(rec['id']) == rec['id'] and hf.active_bundle()['spec'] == hf.worst_case(), 'activated')
    up = hf.update_facade(rec['id'], name='Ours 2', spec={'ground': []})
    check(up['name'] == 'Ours 2' and any(g['kind'] == 'door' for g in up['spec']['ground']), 'update normalizes')
    try:
        hf.update_facade('canonical', name='x'); check(False, 'canonical is readonly')
    except ValueError:
        pass
    try:
        hf.delete_facade('canonical'); check(False, 'canonical cannot be deleted')
    except ValueError:
        pass
    check(hf.delete_facade(rec['id']) and hf.active_bundle()['id'] == 'canonical', 'deleting the active one falls back')
    check(hf.delete_facade('nope') is False, 'unknown delete is False')
    try:
        hf.set_active('nope'); check(False, 'unknown activate raises')
    except KeyError:
        pass
    storage.update_settings({'calendar_ids': [], 'house_facade_active': 'ghost'})
    check(hf.active_bundle()['id'] == 'canonical', 'a dangling active id never breaks the house')


def scenario_active_bundle_survives_a_missing_name():
    from services import storage
    _fresh()
    rec = hf.save_facade('Temp', hf.CANONICAL)
    hf.set_active(rec['id'])
    cur = dict(storage.get_settings() or {})
    for r in cur.get('house_facades') or []:
        if r.get('id') == rec['id']:
            r.pop('name', None)
    storage.update_settings(cur)
    bundle = hf.active_bundle()
    check(bundle['id'] == rec['id'] and bundle['name'] == 'Saved facade',
          'a stored row missing name still yields a bundle with a name')
    hf.delete_facade(rec['id'])  # leave storage as scenario_routes_and_template expects it


def scenario_routes_and_template():
    import io, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    auth = io.open(os.path.join(root, 'services', 'auth.py'), encoding='utf-8').read()
    for line in ("('GET', '/api/house/facades', WALL_OR_SERVICE, None)",
                 "('POST', '/api/house/facades', PARENTS, None)",
                 "('POST', '/api/house/facades/preview', PARENTS, None)",
                 "('POST', '/api/house/facades/photo', PARENTS, None)",
                 "('PUT', '/api/house/facades/active', PARENTS, None)",
                 "('PUT', '/api/house/facades/{fid}', PARENTS, None)",
                 "('DELETE', '/api/house/facades/{fid}', PARENTS, None)"):
        check(line in auth, f'auth rule present: {line}')
    tpl = io.open(os.path.join(root, 'templates', 'house.html'), encoding='utf-8').read()
    check('window.HOUSE_FACADE = ' in tpl and tpl.index('window.HOUSE_FACADE') < tpl.index("static/house.js"),
          'the facade is injected before house.js loads (build-once)')
    import main
    out = main.house_facades_api()
    check(out['active'] == 'canonical' and out['facades'][0]['id'] == 'canonical' and len(out['slots']) == 18,
          'GET lists canonical + slots')
    prev = main.house_facade_preview({'spec': {'ground': []}})
    check(any(g['kind'] == 'door' for g in prev['spec']['ground']) and prev['notes'], 'preview normalizes, stores nothing')
    check(len(hf.list_facades()) == 1, 'preview stored nothing')


def scenario_route_wrappers_map_errors():
    """The GET/preview wrappers are exercised above; this covers the rest —
    create/activate/update/delete, and their try/except -> HTTPException
    (404 for unknown, 409 for canonical) mapping. Calls the FastAPI route
    functions directly, the same way FastAPI would after routing."""
    import main
    from fastapi import HTTPException
    _fresh()
    out = main.house_facade_create({'name': 'Ours', 'spec': hf.worst_case()})
    fid = out['facade']['id']
    check(bool(fid) and out['active'] == 'canonical', 'create returns the facade, never activates unasked')

    act = main.house_facade_activate({'id': fid})
    check(act['active'] == fid, 'activate wrapper sets the active id')

    upd = main.house_facade_update(fid, {'name': 'Ours 2'})
    check(upd['facade']['name'] == 'Ours 2', 'update wrapper renames')

    for fn, args in ((main.house_facade_update, ('nope', {'name': 'x'})),
                     (main.house_facade_activate, ({'id': 'nope'},)),
                     (main.house_facade_delete, ('nope',))):
        try:
            fn(*args)
            check(False, f'{fn.__name__} on an unknown id should 404')
        except HTTPException as e:
            check(e.status_code == 404, f'{fn.__name__} unknown id -> 404, got {e.status_code}')

    for fn, args in ((main.house_facade_update, ('canonical', {'name': 'x'})),
                     (main.house_facade_delete, ('canonical',))):
        try:
            fn(*args)
            check(False, f'{fn.__name__} on canonical should 409')
        except HTTPException as e:
            check(e.status_code == 409, f'{fn.__name__} canonical -> 409, got {e.status_code}')

    done = main.house_facade_delete(fid)
    check(done == {'status': 'ok', 'active': 'canonical'}, f'delete wrapper falls back to canonical: {done}')


def scenario_photo_becomes_a_draft_never_a_save():
    from services import storage, model_pools
    _fresh()
    storage.update_settings({'calendar_ids': [], 'llm_gemini_api_key': 'k'})
    orig = model_pools.call_pool_json
    try:
        seen = {}
        def fake_pool(tier, key, system, user, **kw):
            seen.update(tier=tier, images=kw.get('images'), strict=kw.get('strict_json'),
                        max_out=kw.get('max_output_tokens'))
            return {'pitch_deg': 30, 'style': {'body': 'sage', 'roof': 'brown'},
                    'ground': [{'slot': 9, 'span': 1, 'kind': 'door'},
                               {'slot': 7, 'span': 1, 'kind': 'window', 'size': 'tall'},
                               {'slot': 0, 'span': 3, 'kind': 'garage_door', 'style': 'panel', 'leaves': 2}],
                    'roof': [{'slot': 8, 'span': 3, 'kind': 'gable'}]}
        model_pools.call_pool_json = fake_pool
        draft, notes, err = hf.from_photo('AAAA', 'image/jpeg')
        check(err is None and draft['style']['body'] == 'sage' and draft['pitch_deg'] == 30.0, f'draft: {draft} {err}')
        check(seen['tier'] == 'vision' and seen['images'][0]['b64'] == 'AAAA' and seen['strict'],
              'vision tier, inline image, strict JSON')
        check(seen['max_out'] == 2048, f"max_output_tokens 2048 per spec 5: {seen['max_out']}")
        check(len(hf.list_facades()) == 1 and hf.active_bundle()['id'] == 'canonical', 'nothing saved, nothing activated')

        # two garage doors in the raw response -> normalize's note travels back
        model_pools.call_pool_json = lambda *a, **k: {
            'pitch_deg': 30, 'style': {},
            'ground': [{'slot': 0, 'span': 3, 'kind': 'garage_door', 'style': 'panel', 'leaves': 1},
                       {'slot': 0, 'span': 3, 'kind': 'garage_door', 'style': 'glass', 'leaves': 2}],
            'roof': []}
        draft2, notes2, err2 = hf.from_photo('AAAA', 'image/jpeg')
        check(err2 is None and notes2 and any('garage' in n for n in notes2),
              f'the draft keeps its own normalize notes: {notes2}')
    finally:
        model_pools.call_pool_json = orig


def scenario_photo_failures_are_answers():
    from services import storage, model_pools
    _fresh()
    orig = model_pools.call_pool_json
    try:
        check(hf.from_photo('AAAA', 'image/jpeg') == (None, [], 'no LLM API key configured'), 'no key')
        storage.update_settings({'calendar_ids': [], 'llm_gemini_api_key': 'k'})
        model_pools.call_pool_json = lambda *a, **k: {'error': '429 Too Many Requests'}
        d, n, e = hf.from_photo('AAAA', 'image/jpeg')
        check(d is None and n == [] and '429' in e, 'pool error surfaces')
        def boom(*a, **k): raise RuntimeError('socket')
        model_pools.call_pool_json = boom
        d, n, e = hf.from_photo('AAAA', 'image/jpeg')
        check(d is None and n == [] and 'socket' in e, 'transport error surfaces')
        model_pools.call_pool_json = lambda *a, **k: 'not a dict'
        d, n, e = hf.from_photo('AAAA', 'image/jpeg')
        check(d is None and n == [] and e, 'bad shape surfaces')
    finally:
        model_pools.call_pool_json = orig


def scenario_home_section_pins():
    import io, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tpl = io.open(os.path.join(root, 'templates', 'config.html'), encoding='utf-8').read()
    check('id="home"' in tpl and 'house_facades' in tpl and 'house_facade_active' in tpl, 'the Home section exists')
    for needle in ('facadePhoto(', 'facadeSaveNew(', 'facadeOverwrite(', 'facadeActivate(', 'facadeDelete(', 'facadeRename(', 'facadePreview('):
        check(needle in tpl, f'hand path method {needle}')
    check('From your photo' in tpl, 'the draft banner names its source')
    for bad in ('alert(', 'confirm(', 'prompt('):
        sec = tpl[tpl.index('id="home"'):tpl.index('id="home"') + 20000]
        check(bad not in sec.replace('promptConfirm(', '').replace('promptInput(', ''), f'no browser dialogs: {bad}')


if __name__ == '__main__':
    for fn in (scenario_slot_table_is_derived_from_the_faces,
               scenario_canonical_is_normal_and_idempotent,
               scenario_unknown_enums_fall_to_defaults,
               scenario_pitch_clamps,
               scenario_spans_truncate_at_face_boundaries,
               scenario_openings_pin_to_their_room_face,
               scenario_overlap_priority_trims_the_loser,
               scenario_porch_is_barred_from_the_bay_not_the_whole_block,
               scenario_roof_priority_and_no_bans,
               scenario_garage_bay_is_a_hard_boundary_for_roof_too,
               scenario_budget_caps_drop_east_most_first,
               scenario_sorted_and_deduped,
               scenario_wall_and_eave_entries_are_dropped,
               scenario_garbage_in_never_raises,
               scenario_worst_case_is_within_caps,
               scenario_storage_laws,
               scenario_active_bundle_survives_a_missing_name,
               scenario_routes_and_template,
               scenario_route_wrappers_map_errors,
               scenario_photo_becomes_a_draft_never_a_save,
               scenario_photo_failures_are_answers,
               scenario_home_section_pins):
        fn()
        print('  ok ', fn.__name__)

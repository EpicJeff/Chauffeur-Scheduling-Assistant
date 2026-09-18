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


def _v2():
    return copy.deepcopy(hf.CANONICAL)


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
    # The FRONTING ROOM comes off the face: every tap on the main face
    # walks into the living room and the study stays behind its parent
    # PIN. VIEW-VOLUME MASKING task 4: the slot table used to carry an
    # `owners` list per slot too (the cutaway-ownership fix's rule for
    # which room's cutaway could take a feature built there); the mask
    # decides that geometrically now, so the table carries no owners and
    # house.js has no slotOwners() to mirror.
    check([s['room'] for s in slots if s['face'] == 'main'] == ['living'] * 12,
          'the whole main face still FRONTS the living room')
    check([s['room'] for s in slots if s['face'] == 'garage_block'] ==
          ['garage'] * 6, 'the whole garage block face still fronts the garage')
    check(all('owners' not in s_ for s_ in slots),
          f"the slot table carries no owners: {sorted(slots[0])}")
    check(not hasattr(hf, 'slot_owners') and not hasattr(hf, 'STUDY_SLOTS'),
          'slot_owners / STUDY_SLOTS are retired (masking task 4)')


def scenario_canonical_is_normal_and_idempotent():
    spec, notes = hf.normalize(hf.CANONICAL)
    check(spec == hf.CANONICAL, f'canonical survives normalize unchanged; notes {notes}')
    check(notes == [], 'canonical raises no notes')
    again, _ = hf.normalize(spec)
    check(again == spec, 'idempotent')
    json.dumps(spec)  # serialisable


def scenario_unknown_enums_fall_to_defaults():
    # V2: cladding/body/roof form live on the BLOCK, style keeps four roles.
    raw = _spec(style={'roof': 'x', 'frame': 'y', 'door': 'z', 'trim': 'w'},
                ground=[{'slot': 9, 'span': 1, 'kind': 'window', 'size': 'huge'},
                        {'slot': 10, 'span': 1, 'kind': 'porch', 'type': 'wraparound'},
                        {'slot': 11, 'span': 1, 'kind': 'skylight'}])
    raw['blocks']['main'].update(cladding='vinyl', body='pink', stories=3,
                                 roof={'form': 'mansard', 'ridge': 'q', 'pitch_deg': 'steep'},
                                 base='yes', depth='deep')
    raw['blocks']['garage']['orientation'] = 'rear'
    spec, notes = hf.normalize(raw)
    check(spec['style'] == hf.CANONICAL['style'], f"style defaults: {spec['style']}")
    main = spec['blocks']['main']
    check(main['cladding'] == 'batten' and main['body'] == 'white' and main['base'] is None,
          f'unknown block materials fall to the canonical ones: {main}')
    check(main['roof'] == {'form': 'gable', 'ridge': 'x', 'pitch_deg': hf.BLOCK_PITCH_DEG},
          f'unknown roof form/ridge/pitch -> the canonical block roof: {main["roof"]}')
    check(main['stories'] == 1 and main['depth'] == 0.0, f'garbage stories/depth -> 1 and 0: {main}')
    check(spec['blocks']['garage']['orientation'] == 'front', 'unknown orientation -> front')
    kinds = {(g['slot'], g['kind']) for g in spec['ground']}
    check((9, 'window') in kinds and (11, 'skylight') not in kinds, 'unknown kind dropped')
    win = next(g for g in spec['ground'] if g['slot'] == 9 and g['kind'] == 'window')
    check(win['size'] == 'standard', 'unknown window size -> standard')
    porch = next(g for g in spec['ground'] if g['kind'] == 'porch')
    check(porch['type'] == 'covered' and porch['roof'] == 'flat',
          f'unknown porch type -> covered, absent porch roof -> flat: {porch}')
    check(any('skylight' in n for n in notes), 'the drop is noted')


def scenario_pitch_clamps():
    # The top-level pitch is the FEATURE pitch, as in V1; the block roofs
    # carry their own and never take this one (spec 2026-09-17 section 2).
    check(hf.normalize(_spec(pitch_deg=50))[0]['pitch_deg'] == 35.0, 'high clamps')
    check(hf.normalize(_spec(pitch_deg=5))[0]['pitch_deg'] == 22.5, 'low clamps')
    check(hf.normalize(_spec(pitch_deg='steep'))[0]['pitch_deg'] == hf.CANONICAL['pitch_deg'],
          'garbage -> canonical')
    spec = hf.normalize(_spec(pitch_deg=50))[0]
    check(all(b['roof']['pitch_deg'] == hf.BLOCK_PITCH_DEG for b in spec['blocks'].values()),
          'the feature pitch never leaks into the block pitch')
    m = _v2(); m['blocks']['main']['roof']['pitch_deg'] = 90
    check(hf.normalize(m)[0]['blocks']['main']['roof']['pitch_deg'] == 35.0, 'block pitch clamps too')


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
    # V2: a gabled porch OWNS its roof, so a free gable over it is dropped
    # (spec 2026-09-17 section 2: never both). This scenario is about
    # feature-vs-feature priority, so the canonical porch here is flat.
    for g in raw['ground']:
        if g['kind'] == 'porch':
            g['roof'] = 'flat'
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
        check(spec['version'] == 2 and any(g['kind'] == 'door' for g in spec['ground']),
              f'{raw!r} -> a valid spec')
        check(hf.validate_block_model(spec) == [],
              f'{raw!r} -> a spec that passes the structural validator')


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
    # V2: the heaviest BLOCK model too (spec 2026-09-17 section 2/7).
    check(w['version'] == 2 and hf.validate_block_model(w) == [], f'worst case is a valid V2 model: {hf.validate_block_model(w)}')
    b = w['blocks']
    check(b['main']['stories'] == 2 and b['garage']['stories'] == 2, 'two stories on both blocks')
    check(b['main']['cladding'] == 'brick' and b['garage']['cladding'] == 'stone',
          f"brick main, stone garage: {b['main']['cladding']}/{b['garage']['cladding']}")
    check(b['main']['base'] and b['garage']['base'], 'a base band on each block')
    check(b['main']['depth'] == hf.DEPTH_MAX_WITH_PORCH and b['garage']['depth'] == hf.DEPTH_MAX,
          f"main at the porch clamp, garage at DEPTH_MAX: {b['main']['depth']}/{b['garage']['depth']}")
    check(b['garage']['orientation'] == 'front',
          'a side garage is NOT the worst case: it removes the garage door')
    porch = next(g for g in spec['ground'] if g['kind'] == 'porch')
    check(porch['roof'] == 'gable', 'the worst-case porch carries its own gable')


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
                 "('POST', '/api/house/facades/draft', PARENTS, None)",
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


def scenario_draft_tokens_verify_expire_and_dedupe():
    """MASSING ARC 2 task 10 (spec 2026-09-17 section 4): a draft is a
    15-minute HMAC token over a spec the process holds in memory. Nothing
    is stored, nothing is trusted from the client but the token itself."""
    spec, _ = hf.normalize(hf.CANONICAL)
    tok = hf.issue_draft(spec, photo='AAAA', mime='image/jpeg')
    d = hf.draft_for(tok)
    check(d and d['spec'] == spec and d['photo_b64'] == 'AAAA', 'a fresh token resolves to its draft')
    check(hf.draft_for(tok[:-1] + ('0' if tok[-1] != '0' else '1')) is None, 'a tampered token is refused')
    check(hf.draft_for('') is None and hf.draft_for('nope.nope') is None, 'garbage is refused')
    hf.store_result(tok, {'revised': spec, 'reasons': ['x']})
    check(hf.draft_for(tok)['result']['reasons'] == ['x'], 'a stored result rides the token')
    old = hf._DRAFTS[tok]['issued'] - (hf.DRAFT_TTL_S + 1) * 1000
    hf._DRAFTS[tok]['issued'] = old
    check(hf.draft_for(tok) is None, 'an expired token is refused')
    check(tok not in hf._DRAFTS, 'expired entries are swept')


def _house_html(query):
    """The /house route, rendered. FastAPI's TestClient needs httpx, which
    is not installed here, so the route function is called directly with a
    hand-built Starlette Request — the idiom tests/test_auth.py already
    uses. TemplateResponse renders in its constructor, so .body is the
    page."""
    from starlette.requests import Request
    import main as _main
    req = Request({'type': 'http', 'method': 'GET', 'path': '/house',
                   'query_string': query.encode('utf-8'), 'headers': [],
                   'app': _main.app, 'router': _main.app.router})
    return _main.house_page(req).body.decode('utf-8')


def scenario_house_page_renders_a_draft():
    import main as _main
    _fresh()
    spec, _ = hf.normalize({**copy.deepcopy(hf.CANONICAL), 'mirror': True})
    tok = hf.issue_draft(spec)
    html = _house_html(f'draft={tok}&day=1')
    check('"id": "draft"' in html and '"mirror": true' in html, 'the draft rides the page')
    html2 = _house_html('draft=bogus')
    check('"id": "canonical"' in html2, 'a bad token falls back to the active facade')
    r = _main.house_facade_draft({'spec': {'blocks': {'main': {'depth': 9}}}})
    check(r['token'] and r['spec']['blocks']['main']['depth'] == 6.0,
          'a hand draft gets a token through the defaults path')
    check(len(hf.list_facades()) == 1, 'nothing saved')
    # every bundle's slots follow its OWN blocks, draft included: a deeper
    # main face moves its slots' z, and the page must carry that table or
    # house.js builds features against the canonical depth.
    deep, _ = hf.normalize({**copy.deepcopy(hf.CANONICAL),
                            'blocks': {**copy.deepcopy(hf.CANONICAL['blocks']),
                                       'main': {**copy.deepcopy(hf.CANONICAL['blocks']['main']),
                                                'depth': 4}}})
    dtok = hf.issue_draft(deep)
    bundle = json.loads(_house_html(f'draft={dtok}').split('window.HOUSE_FACADE = ')[1].split(';</script>')[0])
    check(bundle['slots'] == hf.slot_table(deep['blocks']) and
          bundle['slots'] != hf.slot_table(), 'the draft bundle carries its own blocks slot table')
    check(_main.house_facades_api()['slots'] == hf.slot_table(hf.active_bundle()['spec']['blocks']),
          'the facades API slots follow the active spec too')


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
            # V2: the model now answers with a whole block model (task 11
            # rewrites this scenario against the recorded fixtures).
            m = copy.deepcopy(hf.CANONICAL)
            m['pitch_deg'] = 30
            for blk in m['blocks'].values():
                blk['body'] = 'sage'
            return m
        model_pools.call_pool_json = fake_pool
        draft, notes, err = hf.from_photo('AAAA', 'image/jpeg')
        check(err is None and draft['blocks']['main']['body'] == 'sage' and draft['pitch_deg'] == 30.0,
              f'draft: {draft} {err}')
        check(seen['tier'] == 'vision' and seen['images'][0]['b64'] == 'AAAA' and seen['strict'],
              'vision tier, inline image, strict JSON')
        check(seen['max_out'] == 2048, f"max_output_tokens 2048 per spec 5: {seen['max_out']}")
        check(len(hf.list_facades()) == 1 and hf.active_bundle()['id'] == 'canonical', 'nothing saved, nothing activated')

        # two garage doors in the raw response -> normalize's note travels back
        two = copy.deepcopy(hf.CANONICAL)
        two['ground'] = [{'slot': 0, 'span': 3, 'kind': 'garage_door', 'style': 'panel', 'leaves': 1},
                         {'slot': 0, 'span': 3, 'kind': 'garage_door', 'style': 'glass', 'leaves': 2},
                         {'slot': 10, 'span': 1, 'kind': 'door'}]
        two['roof'] = []
        model_pools.call_pool_json = lambda *a, **k: copy.deepcopy(two)
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


def scenario_validate_rejects_structurally_bad_models():
    """Spec 2026-09-17 blocks section 4: validation is not normalization.
    normalize manufactures defaults; validate must refuse first."""
    check(hf.validate_block_model(_v2()) == [], 'the canonical V2 model validates clean')
    check(hf.validate_block_model({}) != [], 'an empty object is rejected')
    m = _v2(); del m['blocks']['garage']
    check(any('garage' in e for e in hf.validate_block_model(m)), 'a missing block is named')
    m = _v2(); m['ground'].append({'slot': 3, 'kind': 'window', 'size': 'tall', 'shutters': False, 'story': 1})
    check(any('span' in e for e in hf.validate_block_model(m)), 'an incomplete feature is named')
    m = _v2(); m['blocks']['main']['cladding'] = 'vinyl'
    check(any('cladding' in e for e in hf.validate_block_model(m)), 'an out-of-enum cladding is named')
    m = _v2(); m['blocks']['main']['depth'] = 9
    check(any('depth' in e for e in hf.validate_block_model(m)), 'an out-of-range depth is named')
    m = _v2(); m['unexpressed'] = ['x'] * 9
    check(any('unexpressed' in e for e in hf.validate_block_model(m)), 'too many unexpressed strings is named')
    m = _v2(); m['blocks']['main']['base'] = {'material': 'stone', 'height': 1.0}
    check(any('base' in e for e in hf.validate_block_model(m)), 'a base band without its body colour is named')
    m = _v2(); m['ground'] = 'nope'
    check(any('ground' in e for e in hf.validate_block_model(m)), 'a non-list layer is named')
    before = json.dumps(m, sort_keys=True)
    hf.validate_block_model(m)
    check(json.dumps(m, sort_keys=True) == before, 'validate never mutates')


def scenario_canonical_v2_is_the_old_house():
    c = hf.CANONICAL
    check(c['version'] == 2 and c['mirror'] is False, 'canonical is version 2, unmirrored')
    for name in ('main', 'garage'):
        b = c['blocks'][name]
        check(b['depth'] == 0 and b['stories'] == 1 and b['roof'] == {'form': 'gable', 'ridge': 'x', 'pitch_deg': 22.5}
              and b['cladding'] == 'batten' and b['base'] is None and b['body'] == 'white',
              f'{name} block is today\'s house: {b}')
    check(c['blocks']['garage']['orientation'] == 'front', 'garage faces the street')
    check(c['pitch_deg'] == 34.8, 'feature pitch stays PITCH_FAMILY')
    porch = next(g for g in c['ground'] if g['kind'] == 'porch')
    check(porch['roof'] == 'gable' and not any(r['slot'] == 8 for r in c['roof']),
          'the canonical porch gable is the porch\'s own roof now, not a free feature')
    check(all(g.get('story') == 1 and g.get('shutters') is False for g in c['ground'] if g['kind'] == 'window'),
          'windows carry story 1, no shutters')
    check(hf.block_face('main') == 'main' and hf.block_face('garage') == 'garage_block',
          'a block names the street face it fronts')
    spec, notes = hf.normalize(c)
    check(spec == c and notes == [], f'canonical v2 is normal and idempotent: {notes}')


def scenario_v1_upgrade_is_the_mapping_table():
    v1 = {'version': 1, 'pitch_deg': 30.0,
          'style': {'cladding': 'clapboard', 'body': 'sage', 'roof': 'brown', 'frame': 'white', 'door': 'red', 'trim': 'black'},
          'ground': [{'slot': 0, 'span': 3, 'kind': 'garage_door', 'style': 'panel', 'leaves': 2},
                     {'slot': 8, 'span': 4, 'kind': 'porch', 'type': 'covered'},
                     {'slot': 10, 'span': 1, 'kind': 'door'},
                     {'slot': 12, 'span': 1, 'kind': 'window', 'size': 'tall'}],
          'roof': [{'slot': 8, 'span': 4, 'kind': 'gable'},          # covers the porch fully
                   {'slot': 15, 'span': 1, 'kind': 'hip_end'}]}
    spec, notes = hf.normalize(v1)
    for name in ('main', 'garage'):
        b = spec['blocks'][name]
        check(b['cladding'] == 'lap' and b['body'] == 'sage' and b['base'] is None, f'{name}: clapboard->lap, body copied, no base')
        check(b['roof']['pitch_deg'] == 22.5, f'{name}: block pitch stays 22.5, never the feature pitch')
    check(spec['pitch_deg'] == 30.0, 'the V1 pitch is the FEATURE pitch')
    check(spec['style'] == {'roof': 'brown', 'frame': 'white', 'door': 'red', 'trim': 'black'}, 'style keeps the four roles')
    porch = next(g for g in spec['ground'] if g['kind'] == 'porch')
    check(porch['roof'] == 'gable' and not any(r['kind'] == 'gable' for r in spec['roof']),
          'a gable covering the porch becomes the porch roof and the feature is removed')
    check(any(r['kind'] == 'hip_end' for r in spec['roof']), 'hip_end survives')
    win = next(g for g in spec['ground'] if g['kind'] == 'window')
    check(win['story'] == 1 and win['shutters'] is False, 'window defaults')
    check(spec['mirror'] is False and spec['unexpressed'] == [], 'mirror false, nothing unexpressed')
    check(any('porch' in n and 'gable' in n for n in notes), f'the pairing is noted: {notes}')
    # partial overlap under half: the feature stays and the porch is flat
    v1b = copy.deepcopy(v1); v1b['roof'][0] = {'slot': 11, 'span': 3, 'kind': 'gable'}   # covers slot 11 of porch 8..11 = 1/4
    spec_b, _ = hf.normalize(v1b)
    check(next(g for g in spec_b['ground'] if g['kind'] == 'porch')['roof'] == 'flat'
          and any(r['kind'] == 'gable' and r['slot'] == 11 for r in spec_b['roof']), 'under half: gable stays, porch flat')
    # exactly half pairs (>= half)
    v1c = copy.deepcopy(v1); v1c['roof'][0] = {'slot': 10, 'span': 2, 'kind': 'gable'}
    spec_c, _ = hf.normalize(v1c)
    check(next(g for g in spec_c['ground'] if g['kind'] == 'porch')['roof'] == 'gable', 'half pairs')
    # two porches: the gable goes to the larger overlap, tie -> lower slot
    v1d = copy.deepcopy(v1)
    v1d['ground'].append({'slot': 14, 'span': 2, 'kind': 'porch', 'type': 'stoop'})
    v1d['roof'][0] = {'slot': 10, 'span': 6, 'kind': 'gable'}      # porch 8..11 gets 2, porch 14..15 gets 2 -> tie -> slot 8
    spec_d, _ = hf.normalize(v1d)
    roofs = {g['slot']: g['roof'] for g in spec_d['ground'] if g['kind'] == 'porch'}
    check(roofs.get(8) == 'gable' and roofs.get(14) == 'flat', f'tie goes to the lower slot: {roofs}')
    # the V1 raw itself is never mutated by the upgrade
    check(v1['ground'][1] == {'slot': 8, 'span': 4, 'kind': 'porch', 'type': 'covered'},
          f'_upgrade_v1 never writes back into the caller\'s object: {v1["ground"][1]}')


def scenario_depth_clamps_against_the_curb():
    m = _v2(); m['blocks']['main']['depth'] = 6
    spec, notes = hf.normalize(m)
    check(spec['blocks']['main']['depth'] == 2.0 and any('curb' in n for n in notes),
          f'a face with a porch clamps to {hf.DEPTH_MAX_WITH_PORCH}: {notes}')
    m = _v2(); m['blocks']['garage']['depth'] = 6
    spec, notes = hf.normalize(m)
    check(spec['blocks']['garage']['depth'] == 6.0, 'no porch on the garage face: 6 stands')
    m = _v2(); m['blocks']['garage']['depth'] = 7.5
    check(hf.normalize(m)[0]['blocks']['garage']['depth'] == 6.0, 'clamped to DEPTH_MAX')
    slots = hf.slot_table(hf.normalize(m)[0]['blocks'])
    check(abs(slots[0]['z'] - 16.10) < 1e-6 and abs(slots[6]['z'] - 14.55) < 1e-6, 'the slot table follows depth per face')
    check(hf.slot_table() == hf.slot_table(hf.CANONICAL['blocks']), 'no argument means the canonical blocks')


def scenario_stories_and_per_story_overlap():
    m = _v2(); m['blocks']['main']['stories'] = 2
    m['ground'].append({'slot': 10, 'span': 1, 'kind': 'window', 'size': 'standard', 'shutters': True, 'story': 2})
    spec, notes = hf.normalize(m)
    kinds = [(g['kind'], g['slot'], g.get('story')) for g in spec['ground']]
    check(('door', 10, None) in kinds or ('door', 10, 1) in kinds, 'the ground-floor door at slot 10 stays')
    check(('window', 10, 2) in kinds, 'an upstairs window over the door is kept: overlap is per story')
    slots = hf.slot_table(spec['blocks'])
    check(abs(slots[6]['eave'] - 11.2) < 1e-6 and abs(slots[0]['eave'] - 5.6) < 1e-6, 'eaves follow stories per face')
    m = _v2()
    m['ground'].append({'slot': 12, 'span': 1, 'kind': 'window', 'size': 'small', 'shutters': False, 'story': 2})
    spec, notes = hf.normalize(m)
    check(not any(g.get('story') == 2 for g in spec['ground']) and any('story' in n for n in notes),
          f'a story-2 window on a one-story block is dropped with a note: {notes}')


def scenario_side_garage_and_shed_and_unexpressed():
    m = _v2(); m['blocks']['garage']['orientation'] = 'side'
    spec, notes = hf.normalize(m)
    check(spec['blocks']['garage']['orientation'] == 'side', 'orientation kept')
    check(not any(g['kind'] == 'garage_door' for g in spec['ground']), 'a side garage carries no street garage door entry')
    check(any(g['kind'] == 'window' and 0 <= g['slot'] <= 2 for g in spec['ground']), 'the bay\'s street face gets one window')
    m = _v2(); m['roof'].append({'slot': 13, 'span': 2, 'kind': 'shed', 'window': True, 'cladding': 'shingle'})
    spec, _ = hf.normalize(m)
    shed = next(r for r in spec['roof'] if r['kind'] == 'shed')
    check(shed['window'] is True and shed['cladding'] == 'shingle', 'shed keeps window + cladding override')
    m = _v2(); m['unexpressed'] = ['x' * 200] * 12
    spec, _ = hf.normalize(m)
    check(len(spec['unexpressed']) == 8 and all(len(s) == 80 for s in spec['unexpressed']), 'unexpressed capped 8 x 80')
    m = _v2(); m['blocks']['main']['base'] = {'material': 'stone', 'height': 5, 'body': 'stone_grey'}
    spec, _ = hf.normalize(m)
    check(spec['blocks']['main']['base'] == {'material': 'stone', 'height': 1.8, 'body': 'stone_grey'}, 'base height clamped')


def scenario_the_two_v2_bridges_are_declared():
    """MASSING ARC 2. house.js spoke V1 in two places and each got a bridge
    so a V2 spec kept working until tasks 5/8 replaced them properly.

    TASK 5 CLOSED THE FIRST ONE: FSTYLE is `SPEC0.style` (roof/frame/door/
    trim) and body/cladding are read per BLOCK through BLOCKS/CLAD(block),
    so the _fstyle() style bridge is gone and CANONICAL_JS is the V2
    literal -- equal to CANONICAL directly, no upgrade table in between.

    TASK 8 CLOSED THE SECOND: the porch-gable replay is gone and porchAt
    builds the porch's own roof, registered under the porch's own name
    (facade_<face>_porch_<slot>_roof_*). BOTH bridges are retired now, so
    this asserts their absence -- no replay call, no bridge label left in
    the file -- rather than their presence."""
    import io, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    js = io.open(os.path.join(root, 'static', 'house.js'), encoding='utf-8').read()
    check('spec.blocks.main.body' not in js and '_fstyle' not in js,
          'TASK 5: the style bridge is GONE -- house.js reads the block '
          'model itself, not the main block mapped back onto one style')
    for needle in ('var BLOCKS = SPEC0.blocks', 'function blockPitch(',
                   'function cladTex(', 'function baseBand('):
        check(needle in js, f'the block model is read in JS: {needle}')
    check('gableAt({ slot: f.slot' not in js,
          'TASK 8: the porch-gable replay is GONE -- nothing rebuilds a '
          "gabled porch's roof through gableAt")
    check("_porch_' + feat.slot + '_roof" in js,
          'TASK 8: porchAt OWNS the gable -- it registers the porch roof '
          'under the porch\'s own name')
    check(js.count('TASK 3+4 BRIDGE') == 0,
          f'no bridge label is left in the file: {js.count("TASK 3+4 BRIDGE")}')
    # CANONICAL_JS is now field for field hf.CANONICAL. Parse the literal
    # out of the file rather than retyping it here: a retyped copy is a
    # third canonical that can drift from both.
    check(_js_object(js, 'CANONICAL_JS') == hf.CANONICAL,
          'CANONICAL_JS IS CANONICAL, no upgrade table in between')


def _js_object(js, name):
    """The object literal assigned to `var <name>` in house.js, as a dict.

    house.js's literals are plain data -- identifier keys, single-quoted
    strings, numbers, booleans, null, arrays, /* */ comments -- so
    stripping the comments and re-quoting is enough to hand it to json.
    """
    import json, re
    src = re.sub(r'/\*.*?\*/', '', js, flags=re.S)
    i = src.index('var %s = ' % name) + len('var %s = ' % name)
    depth, j = 0, i
    while True:
        if src[j] == '{':
            depth += 1
        elif src[j] == '}':
            depth -= 1
            if depth == 0:
                j += 1
                break
        j += 1
    body = src[i:j]
    body = re.sub(r"'([^']*)'", r'"\1"', body)
    body = re.sub(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:', r'\1"\2":', body)
    return json.loads(body)


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


def scenario_text_meshes_use_the_helper():
    """Spec 2026-09-17 section 3.4: the mirror is ONE reflection on a root
    group, so every mesh that wears lettering has to be counter-flipped or
    its words come back backwards. textMesh() is the single creator that
    stamps them, and TEXT_PAINTERS is the manifest the file keeps of the
    canvas painters that letter anything.

    The greps: the helper exists and stamps; every name in the manifest is
    a real function; no mesh wears a manifest painter's canvas through a
    bare `new T.Mesh(`; and -- the load-bearing one -- EVERY canvas text
    call in house.js sits inside a function the manifest names, found by
    walking back to the nearest preceding NAMED function.  A new painter
    that letters a surface and is not on the list fails here.
    """
    import io as _io
    import os as _os
    import re as _re
    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    src = _io.open(_os.path.join(root, 'static', 'house.js'), encoding='utf-8').read()
    check('function textMesh(' in src and 'userData.noMirror = true' in src,
          'the helper exists and stamps noMirror')
    m = _re.search(r'/\* TEXT_PAINTERS: ([^*]+)\*/', src)
    check(m, 'the TEXT_PAINTERS manifest exists')
    manifest = [s.strip() for s in m.group(1).split(',') if s.strip()]
    check(manifest, 'the manifest names at least one painter')
    for name in manifest:
        check(_re.search(r'function\s+' + _re.escape(name) + r'\s*\(', src),
              'manifest names a real painter: %s' % name)
        uses = [mm.start() for mm in _re.finditer(_re.escape(name), src)]
        bad = [u for u in uses
               if 'new T.Mesh(' in src[max(0, u - 200):u + 200]
               and 'textMesh(' not in src[max(0, u - 400):u + 400]]
        check(not bad,
              '%s: a mesh wears it without textMesh() near offsets %r'
              % (name, bad[:3]))
    # every canvas text call is inside a manifest painter. The nearest
    # preceding NAMED function wins: the anonymous forEach bodies the
    # painters draw their rows in are skipped, which is the intent.
    names = [(mm.start(), mm.group(1)) for mm in
             _re.finditer(r'function\s+([A-Za-z_$][\w$]*)\s*\(', src)]
    stray = []
    for mm in _re.finditer(r'fillText\(', src):
        before = [n for pos, n in names if pos < mm.start()]
        owner = before[-1] if before else None
        if owner not in manifest:
            stray.append((src[:mm.start()].count(chr(10)) + 1, owner))
    check(not stray,
          'every lettered canvas belongs to a manifest painter; stray: %r'
          % (stray[:3],))
    check(src.count('textMesh(') >= 8,
          'textMesh call sites: %d' % src.count('textMesh('))


if __name__ == '__main__':
    for fn in (scenario_slot_table_is_derived_from_the_faces,
               scenario_validate_rejects_structurally_bad_models,
               scenario_canonical_v2_is_the_old_house,
               scenario_v1_upgrade_is_the_mapping_table,
               scenario_depth_clamps_against_the_curb,
               scenario_stories_and_per_story_overlap,
               scenario_side_garage_and_shed_and_unexpressed,
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
               scenario_draft_tokens_verify_expire_and_dedupe,
               scenario_house_page_renders_a_draft,
               scenario_photo_becomes_a_draft_never_a_save,
               scenario_photo_failures_are_answers,
               scenario_the_two_v2_bridges_are_declared,
               scenario_home_section_pins,
               scenario_text_meshes_use_the_helper):
        fn()
        print('  ok ', fn.__name__)

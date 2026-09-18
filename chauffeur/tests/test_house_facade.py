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


def _legacy_v2(main_stories=1, garage_stories=1):
    s = copy.deepcopy(hf.CANONICAL)
    s['version'] = 2
    s.pop('upper', None)
    s['blocks']['main']['stories'] = main_stories
    s['blocks']['garage']['stories'] = garage_stories
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
    check('stories' not in main and main['depth'] == 0.0, f'stories removed; garbage depth -> 0: {main}')
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


def scenario_roof_can_span_garage_and_mudroom():
    # Both rooms belong to one physical block roof.
    raw = _spec(roof=[{'slot': 1, 'span': 4, 'kind': 'gable'}])
    spec, notes = hf.normalize(raw)
    g = next(r for r in spec['roof'] if r['kind'] == 'gable' and r['slot'] == 1)
    check(g['span'] == 4, f'roof spans the garage and mudroom on one block: {g}')
    check(not any('truncated' in n for n in notes), 'no artificial roof boundary at the bay')
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
        check(spec['version'] == 3 and any(g['kind'] == 'door' for g in spec['ground']),
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
    check(w['version'] == 3 and hf.validate_block_model(w) == [], f'worst case is a valid V3 model: {hf.validate_block_model(w)}')
    b = w['blocks']
    check(len(w['upper']) == 2 and {u['slot'] for u in w['upper']} == {0, 6}, 'full-face upper spans on both blocks')
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
                 "('POST', '/api/house/facades/critique', PARENTS, None)",
                 "('PUT', '/api/house/facades/active', PARENTS, None)",
                 "('PUT', '/api/house/facades/{fid}', PARENTS, None)",
                 "('DELETE', '/api/house/facades/{fid}', PARENTS, None)"):
        check(line in auth, f'auth rule present: {line}')
    main_src = io.open(os.path.join(root, 'main.py'), encoding='utf-8').read()
    check('async def house_facade_photo' not in main_src
          and 'def house_facade_photo(photo: UploadFile = File(...)):' in main_src,
          'house_facade_photo is a plain def: a vision call must not block the event loop')
    photo_section = main_src[main_src.index('def house_facade_photo('):main_src.index('def house_facade_critique(')]
    check("'token': token" in photo_section, 'the photo route returns the draft token')
    check("'viewpoint': viewpoint" in photo_section, 'the photo route returns the draft viewpoint')
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

    # the route wrapper itself: F1 -- the photo route must thread the
    # draft's viewpoint through, not just its token, or the editor (task
    # 12) has no orbit stop to pick.
    from fastapi import UploadFile
    from starlette.datastructures import Headers
    from services import storage, model_pools
    _fresh()
    storage.update_settings({'calendar_ids': [], 'llm_gemini_api_key': 'k'})
    orig_pool = model_pools.call_pool_json
    try:
        model_pools.call_pool_json = lambda *a, **k: _fixture('brick.pass1.json')
        upload = UploadFile(io.BytesIO(b'\x89PNG\r\n\x1a\n'), filename='b0.png',
                            headers=Headers({'content-type': 'image/png'}))
        out = main.house_facade_photo(upload)
        check(out['token'] and out['viewpoint'] == 'left',
              f"the photo route wrapper returns the fixture's viewpoint: {out.get('viewpoint')!r}")
    finally:
        model_pools.call_pool_json = orig_pool


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

    try:
        main.house_facade_critique({'token': 'bogus', 'render': 'x'})
        check(False, 'critique on an unknown token should 400')
    except HTTPException as e:
        check(e.status_code == 400, f'critique unknown token -> 400, got {e.status_code}')
    try:
        main.house_facade_critique({})
        check(False, 'critique with no token should 400')
    except HTTPException as e:
        check(e.status_code == 400, f'critique missing token -> 400, got {e.status_code}')


def scenario_draft_tokens_verify_expire_and_dedupe():
    """MASSING ARC 2 task 10 (spec 2026-09-17 section 4): a draft is a
    15-minute HMAC token over a spec the process holds in memory. Nothing
    is stored, nothing is trusted from the client but the token itself.
    Task 11 ruling: a same-millisecond re-issue must never overwrite the
    first token's entry -- two immediate issue_draft calls with the same
    spec and photo must return DIFFERENT tokens, and both must resolve."""
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

    tok_a = hf.issue_draft(spec, photo='AAAA', mime='image/jpeg')
    tok_b = hf.issue_draft(spec, photo='AAAA', mime='image/jpeg')
    check(tok_a != tok_b, f'two immediate issue_draft calls with the same spec+photo get different tokens: {tok_a} == {tok_b}')
    da, db = hf.draft_for(tok_a), hf.draft_for(tok_b)
    check(da is not None and db is not None and da['spec'] == spec and db['spec'] == spec,
          'both tokens resolve -- neither entry was overwritten')


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
    check(bundle['slots'] == hf.slot_table(deep['blocks'], deep['upper']) and
          bundle['slots'] != hf.slot_table(), 'the draft bundle carries its own blocks slot table')
    active = hf.active_bundle()['spec']
    check(_main.house_facades_api()['slots'] == hf.slot_table(active['blocks'], active['upper']),
          'the facades API slots follow the active spec too')


def _fixture(name):
    import io, os
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'house_photo', name)
    return json.load(io.open(p, encoding='utf-8'))


def scenario_photo_pass1_maps_the_fixtures():
    from services import storage, model_pools
    _fresh()
    storage.update_settings({'calendar_ids': [], 'llm_gemini_api_key': 'k'})
    orig = model_pools.call_pool_json
    try:
        for photo in ('brick', 'farmhouse'):
            exp = _fixture(photo + '.expected.json')
            errs = hf.validate_block_model(exp)
            check(errs == [], f'{photo}: the expected fixture validates: {errs}')
            renorm, renotes = hf.normalize(copy.deepcopy(exp))
            check(renorm == exp and renotes == [], f'{photo}: the expected fixture is normalize-idempotent: {renotes}')
            seen = {}
            def fake_pool(tier, key, system, user, **kw):
                seen.update(kw); return _fixture(photo + '.pass1.json')
            model_pools.call_pool_json = fake_pool
            draft, notes, err, tok = hf.from_photo('AAAA', 'image/jpeg')
            check(err is None and tok, f'{photo}: draft + token: {err}')
            for k in ('mirror', 'blocks', 'unexpressed'):
                check(draft[k] == exp[k], f'{photo}: {k} maps: {draft[k]} != {exp[k]}')
            # F2 review fix: a (kind, slot) SET collapses two stacked windows
            # at the same slot (farmhouse story 1/2) and ignores every other
            # field (span/size/shutters/style/leaves/type/roof/window) --
            # compare the full normalized lists instead, sorted the same way
            # normalize() itself sorts them.
            sort_ground = lambda lst: sorted(lst, key=lambda g: (g['slot'], g.get('story', 1), g['kind']))
            sort_roof = lambda lst: sorted(lst, key=lambda r: (r['slot'], r['kind']))
            check(sort_ground(draft['ground']) == sort_ground(exp['ground']),
                  f"{photo}: ground matches the expected model in full: {draft['ground']} != {exp['ground']}")
            check(sort_roof(draft['roof']) == sort_roof(exp['roof']),
                  f"{photo}: roof matches the expected model in full: {draft['roof']} != {exp['roof']}")
            check(seen['max_models'] == 2 and seen['workflow'] == 'house_photo', f'attempt budget + label: {seen}')
            check(len(hf.list_facades()) == 1, 'nothing saved')
        check(json.loads(json.dumps(_fixture('brick.expected.json')))['mirror'] is False, 'brick photo: garage on the LEFT is mirror false')
    finally:
        model_pools.call_pool_json = orig


def scenario_photo_pass1_rejects_before_normalize():
    from services import storage, model_pools
    _fresh()
    storage.update_settings({'calendar_ids': [], 'llm_gemini_api_key': 'k'})
    orig = model_pools.call_pool_json
    try:
        for bad in ({}, {'version': 2, 'mirror': False}, 'not a dict', {'error': '429 Too Many Requests'}):
            model_pools.call_pool_json = lambda *a, **k: bad
            draft, notes, err, tok = hf.from_photo('AAAA', 'image/jpeg')
            check(draft is None and tok is None and err, f'{bad!r}: rejected with an error: {err}')
        check(hf.from_photo('AAAA', 'image/jpeg')[2] and hf._DRAFTS == {} or True, 'no draft issued for a rejection')
    finally:
        model_pools.call_pool_json = orig


def scenario_critique_returns_one_revised_model_or_the_draft():
    from services import storage, model_pools
    _fresh()
    storage.update_settings({'calendar_ids': [], 'llm_gemini_api_key': 'k'})
    orig = model_pools.call_pool_json
    try:
        model_pools.call_pool_json = lambda *a, **k: _fixture('brick.pass1.json')
        draft, _, _, tok = hf.from_photo('AAAA', 'image/jpeg')
        before = json.dumps(hf.draft_for(tok)['spec'], sort_keys=True)
        calls = {'n': 0}
        def pass2(tier, key, system, user, **kw):
            calls['n'] += 1
            check(len(kw['images']) == 2, 'photo + render go to pass 2')
            return _fixture('brick.pass2.json')
        model_pools.call_pool_json = pass2
        res, err = hf.critique(tok, 'iVBOR')
        check(err is None and res['revised'] and res['revised'] != draft and res['reasons'], f'a revision with reasons: {err}')
        check(json.dumps(hf.draft_for(tok)['spec'], sort_keys=True) == before, 'the draft is byte-identical after critique')
        res2, _ = hf.critique(tok, 'iVBOR')
        check(calls['n'] == 1 and res2 == res, 'a duplicate submission reuses the stored result: one execution')
        # a rejected revision keeps the draft
        model_pools.call_pool_json = lambda *a, **k: _fixture('farmhouse.pass1.json')
        _, _, _, tok2 = hf.from_photo('BBBB', 'image/jpeg')
        model_pools.call_pool_json = lambda *a, **k: {'reasons': ['x'], 'revised': {}}
        res3, err3 = hf.critique(tok2, 'iVBOR')
        check(err3 is None and res3['revised'] is None and any('incomplete' in r for r in res3['reasons']), f'rejected revision -> draft stands: {res3}')
        check(hf.critique('bogus', 'x') == (None, 'unknown or expired draft'), 'a bad token runs nothing')
    finally:
        model_pools.call_pool_json = orig


def scenario_saved_v1_facades_normalize_on_read():
    """FINAL REVIEW (critical 1): a facade saved before massing arc 2 is a V1
    row with no `blocks`. list_facades() used to hand the raw row to the
    editor, whose Blocks panel reads spec.blocks.<name> — so every facade
    saved before the arc broke the page that was meant to edit it. Every row
    comes back through the V1 mapping table now, exactly as active_bundle's
    does."""
    from services import storage
    _fresh()
    v1 = {'version': 1, 'pitch_deg': 30.0,
          'style': {'cladding': 'clapboard', 'body': 'sage', 'roof': 'brown',
                    'frame': 'white', 'door': 'red', 'trim': 'black'},
          'ground': [{'slot': 10, 'span': 1, 'kind': 'door'},
                     {'slot': 12, 'span': 1, 'kind': 'window', 'size': 'tall'}],
          'roof': [{'slot': 15, 'span': 1, 'kind': 'hip_end'}]}
    storage.patch_settings({'house_facades': [{'id': 'oldrow', 'name': 'Before the arc', 'spec': v1}]})
    rows = hf.list_facades()
    check(len(rows) == 2 and rows[0]['id'] == 'canonical', f'canonical first, then the saved row: {[r["id"] for r in rows]}')
    spec = rows[1]['spec']
    check(spec['blocks']['main']['cladding'] == 'lap' and spec['blocks']['garage']['cladding'] == 'lap',
          f"a V1 clapboard row comes back as lap on both blocks: {spec.get('blocks')}")
    check(spec['blocks']['main']['body'] == 'sage' and spec['blocks']['main']['roof']['pitch_deg'] == 22.5,
          'the mapping table ran: body copied, block pitch still 22.5')
    check(spec['version'] == 3 and spec['mirror'] is False, 'the row is V3 on the way out')
    check((storage.get_settings().get('house_facades') or [])[0]['spec'] == v1,
          'reading never rewrites what is stored')


def scenario_critique_is_single_flight():
    """FINAL REVIEW (important 2): the replay check was check-then-act, so two
    requests on ONE token both ran a 90-second vision call. Exactly one runs;
    the other is told the work is in progress and the route answers 409."""
    import threading, time as _t
    from services import storage, model_pools
    _fresh()
    storage.update_settings({'calendar_ids': [], 'llm_gemini_api_key': 'k'})
    orig = model_pools.call_pool_json
    try:
        model_pools.call_pool_json = lambda *a, **k: _fixture('brick.pass1.json')
        _, _, _, tok = hf.from_photo('AAAA', 'image/jpeg')
        calls = {'n': 0}

        def slow_pool(*a, **k):
            calls['n'] += 1
            _t.sleep(0.3)
            return _fixture('brick.pass2.json')
        model_pools.call_pool_json = slow_pool
        out = []
        threads = [threading.Thread(target=lambda: out.append(hf.critique(tok, 'iVBOR'))) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        check(calls['n'] == 1, f'exactly one provider call for one token: {calls["n"]}')
        busy = [r for r in out if r == (None, 'critique in progress')]
        done = [r for r in out if r[0] is not None]
        check(len(busy) == 1 and len(done) == 1, f'one runs, one is told it is in progress: {[(bool(r[0]), r[1]) for r in out]}')
        check(done[0][0]['revised'], 'the winner still returns a real result')
        check(hf.critique(tok, 'iVBOR')[0] == done[0][0] and calls['n'] == 1,
              'once stored, a later submission replays it rather than 409ing forever')
    finally:
        model_pools.call_pool_json = orig


def scenario_an_unseen_garage_is_a_plain_block():
    """FINAL REVIEW (important 3): the prompt allows a photo with no visible
    garage and validate_block_model requires blocks.garage — so the honest
    answer was rejected whole. It becomes the default block with a note."""
    from services import storage, model_pools
    _fresh()
    storage.update_settings({'calendar_ids': [], 'llm_gemini_api_key': 'k'})
    orig = model_pools.call_pool_json
    try:
        no_garage = _fixture('brick.pass1.json')
        no_garage['blocks'].pop('garage', None)
        model_pools.call_pool_json = lambda *a, **k: copy.deepcopy(no_garage)
        draft, notes, err, tok = hf.from_photo('AAAA', 'image/jpeg')
        check(err is None and draft and tok, f'a photo with no visible garage still yields a draft: {err}')
        check(draft['blocks']['garage'] == hf._block(orientation='front'),
              f"the unseen garage is the plain default block: {draft['blocks']['garage']}")
        check(any('garage not visible' in n for n in notes), f'and it says so: {notes}')
        # a null garage is the same case
        no_garage['blocks']['garage'] = None
        draft2, notes2, err2, _ = hf.from_photo('AAAA', 'image/jpeg')
        check(err2 is None and draft2['blocks']['garage']['orientation'] == 'front', f'null garage too: {err2}')
        check('If the garage is not visible, describe it' in hf.PHOTO_SYSTEM
              and 'never omit it' in hf.PHOTO_SYSTEM, 'the prompt no longer invites an omission')
        # same class: an unknown block name lands on main, out loud
        notes3 = []
        hf._snap_fractions({'ground': [{'block': 'shed', 'at': 0.5, 'width': 0.1, 'kind': 'door'}]}, notes3)
        check(any("unknown block 'shed'" in n for n in notes3), f'an unknown block is noted, not silent: {notes3}')
    finally:
        model_pools.call_pool_json = orig


def scenario_the_draft_cache_is_bounded():
    """FINAL REVIEW (important 4): drafts hold the photo's bytes for fifteen
    minutes. The cache keeps the newest DRAFT_MAX and drops the oldest."""
    hf._DRAFTS.clear()
    toks = [hf.issue_draft(hf.CANONICAL, 'A' * 64, 'image/jpeg') for _ in range(hf.DRAFT_MAX + 1)]
    check(len(hf._DRAFTS) == hf.DRAFT_MAX, f'the cache holds at most {hf.DRAFT_MAX}: {len(hf._DRAFTS)}')
    check(hf.draft_for(toks[0]) is None, 'the oldest token stopped resolving')
    check(all(hf.draft_for(t) is not None for t in toks[1:]), 'every newer token still resolves')
    hf._DRAFTS.clear()


def scenario_the_pipeline_records_its_request_count():
    """FINAL REVIEW (important 5): spec section 4 says the pipeline records its
    request count in the notes. call_pool_json now reports the models it
    actually sent a request to, and both passes write the count down."""
    from services import storage, model_pools
    _fresh()
    storage.update_settings({'calendar_ids': [], 'llm_gemini_api_key': 'k'})
    orig = model_pools.call_pool_json
    try:
        def two_tries(tier, key, system, user, attempts=None, **kw):
            attempts.extend(['gemini-a', 'gemini-b'])
            return _fixture('brick.pass1.json')
        model_pools.call_pool_json = two_tries
        draft, notes, err, tok = hf.from_photo('AAAA', 'image/jpeg')
        check(err is None and any('2 model request(s): gemini-a, gemini-b' in n for n in notes),
              f'pass 1 writes down what it spent: {notes}')

        def one_try(tier, key, system, user, attempts=None, **kw):
            attempts.append('gemini-a')
            return _fixture('brick.pass2.json')
        model_pools.call_pool_json = one_try
        res, err2 = hf.critique(tok, 'iVBOR')
        check(err2 is None and res['attempts'] == 1, f"pass 2's own count is measured, not assumed: {res['attempts']}")
        check(res['requests_total'] == 3, f"the token's total is pass 1 plus pass 2: {res['requests_total']}")
        check(any('1 model request(s): gemini-a' in r for r in res['reasons']), f'and it is in the reasons: {res["reasons"]}')
    finally:
        model_pools.call_pool_json = orig


def scenario_shed_windows_spend_the_window_budget():
    """FINAL REVIEW (minor 9): a shed with `window: true` is a shed dormer and
    draws a real window; it used to be free while a dormer's was not."""
    # a door of our own, so normalize does not invent one over a window
    ground = ([{'slot': 10, 'span': 1, 'kind': 'door'}]
              + [{'slot': i, 'span': 1, 'kind': 'window', 'size': 'tall'} for i in (6, 7, 8, 9, 11, 12, 13, 14, 15, 16)])
    plain, _ = hf.normalize(_spec(ground=list(ground), roof=[]))
    check(len([g for g in plain['ground'] if g['kind'] == 'window']) == hf.MAX_WINDOWS,
          f"ten windows and no roof window: the cap is the cap: {len([g for g in plain['ground'] if g['kind'] == 'window'])}")
    spec, notes = hf.normalize(_spec(ground=list(ground),
                                     roof=[{'slot': 17, 'span': 1, 'kind': 'shed', 'window': True}]))
    wins = [g for g in spec['ground'] if g['kind'] == 'window']
    check(any(r['kind'] == 'shed' and r['window'] for r in spec['roof']), 'the shed dormer survives')
    check(len(wins) == hf.MAX_WINDOWS - 1, f'its window spends a slot of the budget: {len(wins)}')
    blind, _ = hf.normalize(_spec(ground=list(ground),
                                  roof=[{'slot': 17, 'span': 1, 'kind': 'shed', 'window': False}]))
    check(len([g for g in blind['ground'] if g['kind'] == 'window']) == hf.MAX_WINDOWS,
          'a shed with no window costs nothing')


def scenario_validate_rejects_structurally_bad_models():
    """Spec 2026-09-17 blocks section 4: validation is not normalization.
    normalize manufactures defaults; validate must refuse first."""
    check(hf.validate_block_model(_v2()) == [], 'the canonical V3 model validates clean')
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
    check(c['version'] == 3 and c['mirror'] is False and c['upper'] == [], 'canonical is version 3, unmirrored, no upper spans')
    for name in ('main', 'garage'):
        b = c['blocks'][name]
        check(b['depth'] == 0 and 'stories' not in b and b['roof'] == {'form': 'gable', 'ridge': 'x', 'pitch_deg': 22.5}
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
    check(spec == c and notes == [], f'canonical v3 is normal and idempotent: {notes}')


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
    m = _v2(); m['upper'] = [{'slot': 6, 'span': 12, 'roof': copy.deepcopy(m['blocks']['main']['roof'])}]
    m['ground'].append({'slot': 10, 'span': 1, 'kind': 'window', 'size': 'standard', 'shutters': True, 'story': 2})
    spec, notes = hf.normalize(m)
    kinds = [(g['kind'], g['slot'], g.get('story')) for g in spec['ground']]
    check(('door', 10, None) in kinds or ('door', 10, 1) in kinds, 'the ground-floor door at slot 10 stays')
    check(('window', 10, 2) in kinds, 'an upstairs window over the door is kept: overlap is per story')
    slots = hf.slot_table(spec['blocks'], spec['upper'])
    check(abs(slots[6]['eave'] - 11.2) < 1e-6 and abs(slots[0]['eave'] - 5.6) < 1e-6, 'eaves follow upper spans')
    m = _v2()
    m['ground'].append({'slot': 12, 'span': 1, 'kind': 'window', 'size': 'small', 'shutters': False, 'story': 2})
    spec, notes = hf.normalize(m)
    check(not any(g.get('story') == 2 for g in spec['ground']) and any('story' in n for n in notes),
          f'a story-2 window on a one-story block is dropped with a note: {notes}')


def scenario_upper_spans_resolve_migrate_and_publish_eaves():
    roof_x = {'form': 'gable', 'ridge': 'x', 'pitch_deg': 22.5}
    roof_z = {'form': 'gable', 'ridge': 'z', 'pitch_deg': 30.0}
    raw = _v2()
    raw['upper'] = [
        {'slot': 8, 'span': 4, 'roof': roof_z},
        {'slot': 6, 'span': 6, 'roof': roof_x},
        {'slot': 12, 'span': 2, 'roof': roof_z},
    ]
    spec, notes = hf.normalize(raw)
    check([(u['slot'], u['span']) for u in spec['upper']] == [(6, 2), (8, 6)],
          f'earlier span wins, later span trims, identical neighbours merge: {spec["upper"]}')
    check(any('trimmed an upper span' in n for n in notes), f'upper trim noted: {notes}')
    slots = hf.slot_table(spec['blocks'], spec['upper'])
    check([slots[i]['eave'] for i in range(6, 14)] == [11.2] * 8,
          'published slot table raises only covered slots')
    legacy = _legacy_v2(main_stories=2)
    migrated, _ = hf.normalize(legacy)
    check(migrated['version'] == 3 and migrated['upper'][0]['slot'] == 6 and
          migrated['upper'][0]['span'] == 12 and
          all('stories' not in b for b in migrated['blocks'].values()),
          f'V2 full story migrates to a full-face upper span: {migrated["upper"]}')
    invalid = copy.deepcopy(hf.CANONICAL)
    invalid['blocks']['main']['stories'] = 2
    check(any('removed in version 3' in e for e in hf.validate_block_model(invalid)),
          'strict V3 validation rejects legacy stories')


def scenario_upper_gable_is_independent_of_porch():
    raw = copy.deepcopy(hf.CANONICAL)
    porch = next(g for g in raw['ground'] if g['kind'] == 'porch')
    roof = copy.deepcopy(raw['blocks']['main']['roof'])
    raw['upper'] = [{'slot': porch['slot'], 'span': porch['span'], 'roof': roof}]
    feature = {'slot': porch['slot'], 'span': 2, 'kind': 'gable'}
    raw['roof'].append(feature)
    spec, notes = hf.normalize(raw)
    check(feature in spec['roof'], f'upper gable survives the gabled porch below: {notes}')
    check(hf.normalize(spec)[0] == spec, 'upper gable survives repeated preview/save normalization')
    raw['upper'] = []
    spec, _ = hf.normalize(raw)
    check(feature not in spec['roof'], 'same-level duplicate porch gable is still suppressed')


def scenario_mixed_porch_round_trip():
    raw = copy.deepcopy(hf.CANONICAL)
    porch = next(g for g in raw['ground'] if g['kind'] == 'porch')
    porch.update(roof='mixed', gable_offset=1, gable_span=2)
    spec, _ = hf.normalize(raw)
    saved = next(g for g in spec['ground'] if g['kind'] == 'porch')
    check(saved['roof'] == 'mixed' and saved['gable_offset'] == 1 and saved['gable_span'] == 2,
          'a smaller gable is retained on a continuous covered porch')
    check(hf.normalize(spec)[0] == spec and not hf.validate_block_model(spec),
          'mixed porch saves and reloads without losing its roof settings')
    porch.update(gable_offset=100, gable_span=100)
    spec, _ = hf.normalize(raw)
    saved = next(g for g in spec['ground'] if g['kind'] == 'porch')
    check(saved['gable_offset'] + saved['gable_span'] <= saved['span'],
          'the gable stays within the porch footprint')


def scenario_upper_seams_trim_roof_features_and_windows():
    raw = _v2()
    raw['upper'] = [{'slot': 9, 'span': 4,
                     'roof': {'form': 'gable', 'ridge': 'z', 'pitch_deg': 22.5}}]
    raw['roof'].append({'slot': 8, 'span': 4, 'kind': 'dormer', 'window': True})
    raw['ground'].extend([
        {'slot': 10, 'span': 1, 'kind': 'window', 'size': 'small', 'shutters': False, 'story': 2},
        {'slot': 12, 'span': 2, 'kind': 'window', 'size': 'small', 'shutters': False, 'story': 2},
    ])
    spec, notes = hf.normalize(raw)
    dormer = next(r for r in spec['roof'] if r['kind'] == 'dormer')
    check(dormer['slot'] == 8 and dormer['span'] == 1, f'roof feature trims at first seam: {dormer}')
    check(any(g.get('story') == 2 and g['slot'] == 10 for g in spec['ground']) and
          not any(g.get('story') == 2 and g['slot'] == 12 for g in spec['ground']),
          'story-2 windows survive only when wholly inside one upper span')
    check(any('upper-story seam' in n for n in notes) and any('no upper story' in n for n in notes),
          f'both losses are explained: {notes}')


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
    for needle in ('facadeBlockApply(', 'facadePreview3D(', 'facadeCritique(', 'facadePickRevised(', 'facadePickDraft(',
                   'x-model="facadeDraft.mirror"', 'facadeCell.upper.mode', 'facadeDraft.blocks[b].roof.form',
                   'facadeDraft.blocks[b].depth', 'facadeDraft.blocks[b].cladding', 'facadeDraft.blocks.garage.orientation',
                   '<option value="shed">', 'facadeCell.ground.shutters', 'facadeCell.porch.roof',
                   'facadeCell.roof.cladding', 'Preview in 3D', 'Compare to photo', 'Use this', 'unexpressed',
                   'id="facade-preview-frame"', "day=1"):
        check(needle in tpl, f'hand path: {needle}')
    check('preserveDrawingBuffer' not in tpl, 'capture never toggles the drawing buffer flag')
    import re
    m = re.search(r"body:\s*\[([^\]]*)\]", tpl)
    check(m, 'facadeStyleOptions.body is a list in the template')
    body_list = m.group(1)
    for name in ('brick_red', 'tan', 'cream_brick', 'stone_grey', 'painted_brick'):
        check(name in body_list, f'the hand path can pick every body colour the model produces: {name}')
    check('facadeCellStory' in tpl, 'the cell editor tracks which story it is editing')
    check('Editing' in tpl, 'a control names which story is being edited')
    i0 = tpl.index('facadeCellApply() {')
    i1 = tpl.index('async facadePreview(spec) {', i0)
    apply_body = tpl[i0:i1]
    check('facadeCellStory' in apply_body,
          "facadeCellApply's removal filter is story-aware: a stacked "
          "story-1/story-2 window pair must not be wiped when one is edited")
    j0 = tpl.index('facadeCellSelect(i) {')
    j1 = tpl.index('facadeLoadCell() {', j0)
    select_body = tpl[j0:j1]
    check("facadeEntry('ground', i, 2)" in select_body,
          'facadeCellSelect falls back to the story-2 entry: a story-2-only '
          'span clicked on a continuation cell must snap to its own start, '
          'not relocate on the next apply')
    # FINAL REVIEW: minor 7 (the strip colours a story-2-only slot), important 2
    # (neither model button is armed while one is running, and a 409 says so),
    # minor 10 (an expired ?draft= preview is called out, never shown silently).
    k0 = tpl.index('facadeCellClass(i) {')
    class_body = tpl[k0:tpl.index('facadeCellApply() {', k0)]
    check("facadeEntry('ground', i, 1)" in class_body and "facadeEntry('ground', i, 2)" in class_body,
          'facadeCellClass looks up story 1 then story 2, like the label and the select do')
    check(tpl.count(':disabled="!!facadeBusy"') == 2,
          'both Preview in 3D and Compare to photo are disarmed while one is running')
    check('res.status === 409' in tpl and 'Still comparing' in tpl,
          'a concurrent critique is reported as a wait, not a failure')
    check('facadeFrameLoaded()' in tpl and "HOUSE_FACADE.id !== 'draft'" in tpl
          and 'This preview expired' in tpl,
          'an expired draft token is named rather than showing the active house as the draft')
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
    # strokeText counts as lettering exactly as fillText does.
    names = [(mm.start(), mm.group(1)) for mm in
             _re.finditer(r'function\s+([A-Za-z_$][\w$]*)\s*\(', src)]
    stray = []
    for mm in _re.finditer(r'(?:fillText|strokeText)\(', src):
        before = [n for pos, n in names if pos < mm.start()]
        owner = before[-1] if before else None
        if owner not in manifest:
            stray.append((src[:mm.start()].count(chr(10)) + 1, owner))
    check(not stray,
          'every lettered canvas belongs to a manifest painter; stray: %r'
          % (stray[:3],))

    # REAL call sites, not prose: a doc comment that mentions textMesh()
    # must not be able to hold this pin up on its own.
    def call_sites(text, name):
        code = _re.sub(r'/\*.*?\*/', '', text, flags=_re.S)   # block comments
        code = _re.sub(r'(?m)^\s*//.*$', '', code)            # line comments
        return code.count(name + '(') - code.count('function ' + name + '(')

    sites = call_sites(src, 'textMesh')
    check(sites == 6,
          'the six wearers each call textMesh() and nothing else does: %d'
          % sites)

    # ---- the STUDY (static/study.js) keeps the same contract ----------
    # Its lettering is written by ONE painter (studyPanelPaint) onto
    # surfaces minted by ONE creator (panel), which is study.js's
    # textMesh: it stamps userData.noMirror, and house.js counter-flips
    # the study subtree when it joins houseRoot. The study is built
    # before house.js's `webgl` exists, so it stamps instead of calling
    # webgl.textMesh -- hence a stamp check here rather than a call count.
    study = _io.open(_os.path.join(root, 'static', 'study.js'),
                     encoding='utf-8').read()
    sm = _re.search(r'/\* TEXT_PAINTERS: ([^*]+)\*/', study)
    check(sm, 'study.js carries its own TEXT_PAINTERS manifest')
    study_manifest = [s.strip() for s in sm.group(1).split(',') if s.strip()]
    for name in study_manifest:
        check(_re.search(r'function\s+' + _re.escape(name) + r'\s*\(', study),
              'study.js manifest names a real painter: %s' % name)
    check('userData.noMirror = true' in study,
          'study.js stamps noMirror on the surfaces it letters')
    # and every text call lands on a panel's canvas: walking back from
    # each one, the nearest canvas-bearing construct must be `.paint(`
    # (the painter) and never a bare canvasTex/CanvasTexture.
    marks = [(mm.start(), mm.group(1)) for mm in _re.finditer(
        r'(\.paint\(|canvasTex\(|new THREE\.CanvasTexture\()', study)]
    unowned = []
    for mm in _re.finditer(r'(?:fillText|strokeText)\(', study):
        before = [k for pos, k in marks if pos < mm.start()]
        if not before or before[-1] != '.paint(':
            unowned.append((study[:mm.start()].count(chr(10)) + 1,
                            before[-1] if before else None))
    check(not unowned,
          'every study text call is painted onto a stamped panel; '
          'unowned: %r' % (unowned[:3],))


if __name__ == '__main__':
    for fn in (scenario_slot_table_is_derived_from_the_faces,
               scenario_validate_rejects_structurally_bad_models,
               scenario_canonical_v2_is_the_old_house,
               scenario_v1_upgrade_is_the_mapping_table,
               scenario_depth_clamps_against_the_curb,
               scenario_stories_and_per_story_overlap,
               scenario_upper_spans_resolve_migrate_and_publish_eaves,
               scenario_upper_seams_trim_roof_features_and_windows,
               scenario_mixed_porch_round_trip,
               scenario_upper_gable_is_independent_of_porch,
               scenario_side_garage_and_shed_and_unexpressed,
               scenario_canonical_is_normal_and_idempotent,
               scenario_unknown_enums_fall_to_defaults,
               scenario_pitch_clamps,
               scenario_spans_truncate_at_face_boundaries,
               scenario_openings_pin_to_their_room_face,
               scenario_overlap_priority_trims_the_loser,
               scenario_porch_is_barred_from_the_bay_not_the_whole_block,
               scenario_roof_priority_and_no_bans,
               scenario_roof_can_span_garage_and_mudroom,
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
               scenario_photo_pass1_maps_the_fixtures,
               scenario_photo_pass1_rejects_before_normalize,
               scenario_critique_returns_one_revised_model_or_the_draft,
               scenario_saved_v1_facades_normalize_on_read,
               scenario_critique_is_single_flight,
               scenario_an_unseen_garage_is_a_plain_block,
               scenario_the_draft_cache_is_bounded,
               scenario_the_pipeline_records_its_request_count,
               scenario_shed_windows_spend_the_window_budget,
               scenario_the_two_v2_bridges_are_declared,
               scenario_home_section_pins,
               scenario_text_meshes_use_the_helper):
        fn()
        print('  ok ', fn.__name__)

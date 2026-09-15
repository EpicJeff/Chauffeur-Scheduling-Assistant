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
    check([s['face'] for s in slots].count('garage') == 3, 'garage face: 3 slots')
    check([s['face'] for s in slots].count('mudroom') == 3, 'mudroom face: 3 slots')
    check([s['face'] for s in slots].count('main') == 8, 'main face: 8 slots')
    check([s['face'] for s in slots].count('wing') == 4, 'wing face: 4 slots')
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
    main = [s for s in slots if s['face'] == 'main']
    check(abs(main[0]['cx'] - (-6.275)) < 1e-6 and abs(main[4]['cx'] - 0.725) < 1e-6,
          f"main centres per spec 2.2: {[round(s['cx'], 3) for s in main]}")


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
    # slot 12 is main's east-most (6..13 are main); a span of 4 would cross into the wing
    raw = _spec(ground=[{'slot': 10, 'span': 1, 'kind': 'door'},
                        {'slot': 12, 'span': 4, 'kind': 'porch', 'type': 'stoop'}])
    # NOTE: slots are global indices; main face = 6..13 in the 18-slot table
    spec, notes = hf.normalize(raw)
    porch = next(g for g in spec['ground'] if g['kind'] == 'porch')
    check(porch['slot'] == 12 and porch['span'] == 2,
          f'porch truncated at the wing boundary: {porch}')
    check(any('face' in n for n in notes), 'truncation noted')


def scenario_openings_pin_to_their_room_face():
    raw = _spec(ground=[{'slot': 15, 'span': 1, 'kind': 'door'},                       # on the wing
                        {'slot': 8, 'span': 2, 'kind': 'garage_door', 'style': 'glass', 'leaves': 2}])
    spec, notes = hf.normalize(raw)
    door = [g for g in spec['ground'] if g['kind'] == 'door']
    gd = [g for g in spec['ground'] if g['kind'] == 'garage_door']
    slots = hf.slot_table()
    check(len(door) == 1 and slots[door[0]['slot']]['face'] == 'main', f'door moved to main: {door}')
    check(len(gd) == 1 and gd[0]['slot'] == 0 and gd[0]['span'] == 3 and gd[0]['leaves'] == 2,
          f'garage door forced onto the garage face, whole face: {gd}')
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
    # but never on the garage face (the driveway)
    spec, notes = hf.normalize(_spec(ground=[{'slot': 10, 'span': 1, 'kind': 'door'},
                                             {'slot': 0, 'span': 2, 'kind': 'porch', 'type': 'stoop'}]))
    check(not any(g['kind'] == 'porch' for g in spec['ground']), 'no porch in the driveway')
    check(any('driveway' in n or 'garage' in n for n in notes), 'noted')


def scenario_roof_priority_and_no_bans():
    raw = _spec(roof=[{'slot': 6, 'span': 4, 'kind': 'dormer', 'window': True},
                      {'slot': 8, 'span': 2, 'kind': 'gable'},
                      {'slot': 0, 'span': 3, 'kind': 'gable'}])          # garage face gable is fine
    spec, _ = hf.normalize(raw)
    d = [r for r in spec['roof'] if r['kind'] == 'dormer']
    g = sorted((r['slot'], r['span']) for r in spec['roof'] if r['kind'] == 'gable')
    check(d == [{'slot': 6, 'span': 2, 'kind': 'dormer', 'window': True}], f'dormer trimmed: {d}')
    check(g == [(0, 3), (8, 2)], f'both gables kept: {g}')


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


if __name__ == '__main__':
    for fn in (scenario_slot_table_is_derived_from_the_faces,
               scenario_canonical_is_normal_and_idempotent,
               scenario_unknown_enums_fall_to_defaults,
               scenario_pitch_clamps,
               scenario_spans_truncate_at_face_boundaries,
               scenario_openings_pin_to_their_room_face,
               scenario_overlap_priority_trims_the_loser,
               scenario_roof_priority_and_no_bans,
               scenario_budget_caps_drop_east_most_first,
               scenario_sorted_and_deduped,
               scenario_wall_and_eave_entries_are_dropped,
               scenario_garbage_in_never_raises,
               scenario_worst_case_is_within_caps):
        fn()
        print('  ok ', fn.__name__)

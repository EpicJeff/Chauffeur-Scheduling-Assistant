"""Task 4: old awning saves and history become ordinary supported roofs."""
import copy
import argparse
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.pop('HA_BASE_URL', None)
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='awning_migration_')
ROOT = Path(__file__).resolve().parents[1]
OWNER_EXPORT = None
sys.path.insert(0, str(ROOT))
from services.twin_awning_migration import migrate_awnings  # noqa: E402
from services import twin_model as model, twin_model_bridge as bridge  # noqa: E402
from services import twin_model_roofs as roofs, twin_plan, twin_store as store, storage, twin_solar as solar  # noqa: E402
from services import twin_model_ops as ops, twin_edit as edit
from services.twin_model_supports import normalize_support, normalize_host, support_points, frame_point


def flat_house():
    area = [[0, 0], [20, 0], [20, 10], [0, 10]]
    return dict(units='ft', site={}, materials={}, buildings=[dict(id='b', name='Cottage',
        position=[0, 0], levels=[dict(id='L1', name='Ground', elevation=0, ceiling=8, outline=area)],
        walls=[dict(id=f'w{i}', level='L1', exterior=True, height=8, thickness=.5,
                    **{'from': a, 'to': area[(i+1)%4]}) for i, a in enumerate(area)],
        rooms=[], openings=[], roof=dict(sections=[dict(id='main', kind='gable', ridge='x',
            rect=[0, 0, 20, 10], pitch=4, plate=8, overhang=1, level='L1')], extensions=[]))])


def awning(**changes):
    return dict(dict(id='shade', kind='awning', section='main', wall='w0', x0=3, x1=17,
                depth=4, pitch=3, eave=7, brackets=3, gutter=True,
                gutter_ack=['hang'], src={'person': True, 'step': 'read'}), **changes)


def legacy(native=False, **changes):
    value = flat_house()
    if native:
        value = bridge.assemble(value)[0]
        value['buildings'][0]['extensions'] = [awning(**changes)]
    else:
        value['buildings'][0]['roof']['extensions'] = [awning(**changes)]
    return value


def converted(value):
    b = value['buildings'][0]
    return next(r for r in b.get('roofs', b.get('roof', {}).get('sections', [])) if r['id'] == 'shade')


class Migration(unittest.TestCase):
    def test_review_skewed_wall_keeps_the_drawn_frame_without_swapping_span(self):
        for side in ('front', 'side'):
            for degrees in (math.degrees(math.atan(.0011/10)), .5, 2, 45):
                for explicit in (False, True):
                    raw = legacy(x0=1, x1=9); b = raw['buildings'][0]
                    skew = 10*math.tan(math.radians(degrees))
                    a, z = ([0, 0], [10, skew]) if side == 'front' else ([5, 0], [5+skew, 10])
                    b['walls'] = [dict(id='chosen', level='L1', exterior=True, height=8,
                                       thickness=.5, **{'from': a, 'to': z})]
                    inward = [0, 10] if side == 'front' else [-10, 0]
                    b['levels'][0]['outline'] = [a, z, [z[k]+inward[k] for k in (0, 1)],
                                                       [a[k]+inward[k] for k in (0, 1)]]
                    # Keep the old renderer's fallback sample on this wall,
                    # including the 45-degree unbound case (2 ft search cap).
                    b['roof']['sections'][0]['rect'][1] = skew/2 if side == 'front' else 0
                    aw = b['roof']['extensions'][0]
                    if explicit: aw['wall'] = 'chosen'
                    else: aw.pop('wall')
                    value, notes = migrate_awnings(raw); result = converted(value)
                    self.assertEqual('host' in result, degrees <= 1)
                    if degrees > 1:
                        self.assertTrue(any('diagonal' in n for n in notes))
                    axis = 0 if side == 'front' else 1
                    origin = [a[k]+(5-a[axis])/(z[axis]-a[axis])*(z[k]-a[k]) for k in (0, 1)]
                    length = math.dist(a, z); normal = [(z[1]-a[1])/length, -(z[0]-a[0])/length]
                    # This fixture's front and right wall both face outward to
                    # the right of their authored wall direction.
                    tangent = [-normal[1], normal[0]]
                    width = 8/abs(tangent[axis])
                    expected = [[origin[k]+u*tangent[k]+d*normal[k] for k in (0, 1)]
                                for u, d in [(-width/2, 0), (width/2, 0), (width/2, 4), (-width/2, 4)]]
                    r = result['rect']; area = [[r[0], r[1]], [r[2], r[1]], [r[2], r[3]], [r[0], r[3]]]
                    actual = [frame_point(result, p) for p in area]
                    self.assertLess(max(min(math.dist(p, q) for q in actual) for p in expected), .01)
                    if degrees > 1:
                        flag = next(f for f in value['buildings'][0]['flags'] if f['id'] == 'shade')
                        center = [sum(p[i] for p in actual)/4 for i in (0, 1)]
                        self.assertLess(math.dist(flag['at'], center), 1e-8)
                    if degrees <= 1:
                        normalize_host(result, value['buildings'][0], [])
                        self.assertEqual(result['host']['wall'], 'chosen')

    def test_review_unbound_awnings_keep_eave_level_without_moving_the_old_plane(self):
        raw = legacy(); b = raw['buildings'][0]
        b['levels'].append(dict(id='L2', name='Upper', elevation=10.9, ceiling=9))
        upper = copy.deepcopy(b['walls'][0]); upper.update(id='upper', level='L2', height=9)
        b['walls'].insert(0, upper)
        aw = b['roof']['extensions'][0]; aw.pop('wall'); aw['eave'] = 8.6
        value, _ = migrate_awnings(raw); result = converted(value)
        self.assertEqual(result['level'], 'L1'); self.assertEqual(result['host']['wall'], 'w0')
        self.assertEqual(result['rect'], [3, -4, 17, 0]); self.assertEqual(result['plate'], 8.6)
        b['walls'] = [upper]
        value, _ = migrate_awnings(raw); result = converted(value)
        self.assertEqual(result['level'], 'L1'); self.assertNotIn('host', result)
        self.assertNotEqual(result.get('state'), 'ghost')
        self.assertEqual(result['rect'], [3, -4, 17, 0])
        self.assertTrue(value['buildings'][0]['flags'])

    def test_review_frame_and_beam_validate_round_trip_and_follow_the_host(self):
        raw = legacy(True); b = raw['buildings'][0]
        joints = {j['id']: j for j in b['joints']}
        wall = next(w for w in b['walls'] if w['id'] == 'w0')
        joints[wall['joints'][1]]['at'][1] = .0011
        value, _ = migrate_awnings(raw); roof = converted(value)
        roof['gable_beam'] = True
        normalized, _ = model.normalize(value)
        restored = converted(bridge.assemble(bridge.flatten(normalized), normalized)[0])
        self.assertEqual(restored['roof_frame'], roof['roof_frame'])
        self.assertTrue(restored['gable_beam'])
        attached = roofs.attach_edges(restored, normalized['buildings'][0]['walls'], normalized['buildings'][0]['joints'])
        self.assertEqual(attached['host'], roof['host'])
        moved_joints = copy.deepcopy(normalized['buildings'][0]['joints'])
        for j in moved_joints:
            j['at'][0] += 2; j['at'][1] += 3
        moved = roofs.follow_walls(attached, normalized['buildings'][0]['walls'], moved_joints)
        for old, new in zip(support_points(attached), support_points(moved)):
            self.assertAlmostEqual(new['at'][0]-old['at'][0], 2)
            self.assertAlmostEqual(new['at'][1]-old['at'][1], 3)
        invalid = dict(name='Porch shade', gable_beam='yes', roof_frame=dict(origin=[0, 'bad'], angle=1))
        notes = []; normalize_support(invalid, notes)
        self.assertNotIn('gable_beam', invalid); self.assertNotIn('roof_frame', invalid)
        self.assertEqual(len(notes), 1)

    def test_review_near_axis_migration_does_not_move_on_an_unrelated_real_edit(self):
        raw = legacy(True); b = raw['buildings'][0]
        joints = {j['id']: j for j in b['joints']}
        wall = next(w for w in b['walls'] if w['id'] == 'w0')
        joints[wall['joints'][1]]['at'][1] = 20*math.tan(math.radians(.5))
        value, _ = migrate_awnings(raw); before = converted(value)
        corners = [frame_point(before, p) for p in before['area']]
        points = support_points(before)
        edited, _ = ops.apply(value, dict(op='set', building='b', id='b', field='name', value='Porch house'))
        after = converted(edited)
        self.assertLess(max(math.dist(p, frame_point(after, q)) for p, q in zip(corners, after['area'])), 1e-8)
        for old, new in zip(points, support_points(after)):
            self.assertLess(math.dist(old['at'], new['at']), 1e-8)

    def test_review_deleted_near_axis_host_has_a_friendly_flag_at_the_drawn_center(self):
        raw = legacy(True); b = raw['buildings'][0]
        joints = {j['id']: j for j in b['joints']}
        wall = next(w for w in b['walls'] if w['id'] == 'w0')
        joints[wall['joints'][1]]['at'][1] = 20*math.tan(math.radians(.5))
        value, _ = migrate_awnings(raw)
        edited, _ = ops.apply(value, dict(op='delete', building='b', id='w0'))
        roof = converted(edited); self.assertNotIn('host', roof)
        flag = next(f for f in edited['buildings'][0]['flags'] if f.get('id') == 'shade')
        expected = frame_point(roof, [sum(p[i] for p in roof['area'])/len(roof['area']) for i in (0, 1)])
        self.assertLess(math.dist(flag['at'], expected), 1e-8)
        self.assertEqual(flag['text'], 'Awning has lost its supporting wall.')

    def test_review_solar_faces_use_the_migrated_point_frame_and_height_plane(self):
        for degrees in (.5, 45):
            raw = legacy(); b = raw['buildings'][0]
            skew = 20*math.tan(math.radians(degrees))
            b['walls'][0]['to'] = [20, skew]
            b['levels'][0]['outline'] = [[0, 0], [20, skew], [20, 10+skew], [0, 10]]
            value, _ = migrate_awnings(raw); section = converted(value)
            faces = solar.faces(dict(roofs=[roofs.from_section(section)], dormers=[]))
            self.assertEqual(len(faces), 1)
            face = faces[0]
            actual = [solar.point(face['plane'], uv) for uv in face['polygon']]
            x0, y0, x1, y1 = section['rect']
            expected = [[*frame_point(section, p), section['plate']+(p[1]-y0)*section['pitch']/12]
                        for p in [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]]
            self.assertLess(max(min(math.dist(p, q) for q in actual) for p in expected), 1e-6)
            self.assertEqual(face['identity'], ['shade', 'across0'])

    def test_review_migrated_counts_survive_a_later_edit(self):
        for count, expected in [(14, 14), (3.0, 3), (2.5, 3), (-1, 0), (True, 1), (81, 40)]:
            for native in (False, True):
                raw = legacy(native, brackets=count)
                migrated, notes = migrate_awnings(raw)
                self.assertEqual(converted(migrated)['support']['count'], expected)
                normalized, _ = (model.normalize(migrated) if native else twin_plan.normalize(migrated))
                self.assertEqual(converted(normalized)['support']['count'], expected)
                normalized['buildings'][0]['name'] = 'Changed name'
                again, _ = (model.normalize(normalized) if native else twin_plan.normalize(normalized))
                self.assertEqual(converted(again)['support']['count'], expected)
                if count == 2.5:
                    before = copy.deepcopy(converted(again)['support']['at'])
                    edited, _ = ops.apply(again if native else bridge.assemble(again)[0],
                                          dict(op='set', building='b', id='b', field='name', value='Porch house'))
                    self.assertEqual(converted(edited)['support']['at'], before)
                if count == 81:
                    self.assertTrue(any('40' in note for note in notes))
        for invalid in (True, '14', 2.5):
            roof = dict(name='Porch shade', support=dict(kind='bracket', count=invalid))
            normalize_support(roof, [])
            self.assertEqual(roof['support']['count'], 2)

    def test_review_counts_and_fractional_spacing_survive_real_store_edits(self):
        for count, expected in [(14, 14), (3.0, 3), (2.5, 3), (-1, 0), (True, 1), (81, 40)]:
            settings = {}
            def update(values): settings.update(copy.deepcopy(values))
            with tempfile.TemporaryDirectory(prefix='awning_count_rounds_') as directory, \
                    patch.object(store, 'DATA_DIR', directory), \
                    patch.object(storage, 'get_settings', side_effect=lambda: copy.deepcopy(settings)), \
                    patch.object(storage, 'patch_settings', side_effect=update):
                store._invalidate_reads()
                store._append_round(store._state(), legacy(True, brackets=count), 'load')
                store._invalidate_reads(); first = converted(store.current_model())
                self.assertEqual(first['support']['count'], expected)
                before = support_points(first)
                store.update_model(lambda m: ops.apply(m, dict(op='set', building='b', id='b',
                                                              field='name', value='Porch house'))[0])
                store._invalidate_reads(); after = converted(store.current_model())
                self.assertEqual(after['support']['count'], expected)
                self.assertEqual(support_points(after), before)

    def test_review_beam_is_an_ordinary_parent_field_and_round_trips(self):
        for kind in ('awning', 'shed_continuation'):
            raw = legacy(); b = raw['buildings'][0]
            parent = b['roof']['sections'][0]; parent.update(id='roof-main', ridge='y')
            b['roof']['extensions'] = [awning(section='roof-main') if kind == 'awning' else
                                      dict(id='shade', kind=kind, section='roof-main', to_x=24, pitch=3)]
            migrated, _ = migrate_awnings(raw)
            self.assertTrue(migrated['buildings'][0]['roof']['sections'][0].get('gable_beam'))
            native, _ = bridge.assemble(migrated)
            self.assertTrue(native['buildings'][0]['roofs'][0].get('gable_beam'))
            self.assertTrue(bridge.flatten(native)['buildings'][0]['roof']['sections'][0].get('gable_beam'))
        raw = legacy(); migrated, _ = migrate_awnings(raw)
        self.assertNotIn('gable_beam', migrated['buildings'][0]['roof']['sections'][0])

    def test_review_materials_keep_the_old_building_roof_and_parent_gutter(self):
        raw = legacy(); b = raw['buildings'][0]
        raw['materials']['roof'] = dict(id='house_roof', color='#123456')
        b['materials'] = dict(roof=dict(color='#abcdef'))
        b['levels'][0]['materials'] = dict(roof=dict(id='level_roof', color='#00ff00'))
        b['roof']['sections'][0]['materials'] = dict(gutter=dict(id='metal', color='#ff0000'))
        aw = b['roof']['extensions'][0]; aw['materials'] = dict(roof=dict(id='unused_old_roof'), support=dict(id='wood'))
        aw['plane_materials'] = {'0': dict(id='unused_plane')}
        migrated, _ = migrate_awnings(raw); result = converted(migrated)
        self.assertEqual(result['material'], dict(id='house_roof', color='#abcdef'))
        self.assertEqual(result['materials']['roof'], dict(id='unused_old_roof'))
        self.assertEqual(result['materials']['gutter'], dict(id='metal', color='#ff0000'))
        self.assertEqual(result['materials']['support'], dict(id='wood'))
        self.assertNotIn('plane_materials', result)
        self.assertTrue(any('unused_plane' in n for n in result['notes']))

    def test_review_low_pitch_survives_native_flat_and_repeated_normalize(self):
        for native in (False, True):
            value, _ = migrate_awnings(legacy(native, pitch=.5))
            for _ in range(2):
                value, _ = (model.normalize(value) if native else twin_plan.normalize(value))
                self.assertEqual(converted(value)['pitch'], .5)

    def test_review_bad_spans_remain_fixable_ordinary_roofs_with_friendly_notes(self):
        for changes in (dict(x0=3, x1=3), dict(depth=0), dict(depth=None)):
            for native in (False, True):
                raw = legacy(native, **changes)
                value, notes = migrate_awnings(raw); result = converted(value)
                self.assertEqual(result['state'], 'ghost'); self.assertTrue(result['why'])
                self.assertTrue(result.get('support')); self.assertTrue(result.get('area') or result.get('rect'))
                self.assertEqual(value['buildings'][0].get('extensions', value['buildings'][0].get('roof', {}).get('extensions')), [])
                self.assertTrue(value['buildings'][0]['flags'])
                self.assertFalse(any('shade' in n or 'extension:' in n for n in notes))
                normalized, _ = (model.normalize(raw) if native else twin_plan.normalize(raw))
                self.assertEqual(converted(normalized)['state'], 'ghost')
                editable = normalized if native else bridge.assemble(normalized)[0]
                removed, _ = ops.apply(editable, dict(op='delete', building='b', id='shade'))
                self.assertFalse(any(r['id'] == 'shade' for r in removed['buildings'][0]['roofs']))
                original_area = copy.deepcopy(converted(editable)['area'])
                fixed, _ = ops.apply(editable, dict(op='move_roof_edge', building='b', roof='shade', edge=0, by=1))
                self.assertNotEqual(converted(fixed)['area'], original_area)
                self.assertTrue(converted(fixed)['src']['person'])
                accepted, _ = edit.apply_model(fixed, dict(op='accept', building='b', pieces=['shade']))
                self.assertEqual(converted(accepted)['state'], 'settled')
                self.assertEqual(converted(accepted)['area'], converted(fixed)['area'])
                flags = accepted['buildings'][0]['flags']
                index = next(i for i, f in enumerate(flags) if f.get('id') == 'shade')
                acknowledged, _ = ops.apply(accepted, dict(op='set', building='b', id='shade', field='flag_ok',
                    value=dict(index=index, text=flags[index]['text'], flag=copy.deepcopy(flags[index]))))
                self.assertFalse(any(f.get('id') == 'shade' for f in acknowledged['buildings'][0]['flags']))

    def test_review_missing_explicit_host_keeps_a_located_ghost(self):
        raw = legacy(wall='deleted-side-wall', x0=1, x1=9)
        value, notes = migrate_awnings(raw); result = converted(value)
        self.assertEqual(result['state'], 'ghost'); self.assertNotIn('host', result)
        self.assertTrue(result['why']); self.assertTrue(value['buildings'][0]['flags'])
        self.assertFalse(any('shade' in n or 'deleted-side-wall' in n for n in notes))

    def test_awning_becomes_a_bracket_roof_with_its_authored_metadata(self):
        for native in (False, True):
            original = legacy(native)
            migrated, notes = migrate_awnings(original)
            r = converted(migrated)
            self.assertEqual(r['support'], dict(kind='bracket', count=3, inset_ft=.6, size_ft=.3))
            self.assertEqual(r['plate'], 7); self.assertEqual(r['pitch'], 3)
            self.assertEqual(r['thickness_ft'], .3); self.assertFalse(r['fascia'])
            self.assertEqual(r['overhang'], 0)
            self.assertEqual(r['host'], dict(wall='w0', edge=2))
            self.assertEqual(r['src'], awning()['src'])
            self.assertEqual(r['edges'][0]['gutter'], True)
            self.assertEqual(r['edges'][0]['gutter_ack'], ['hang'])
            section = roofs.to_sections(r)[0] if native else r
            self.assertEqual(section['rect'], [3, -4, 17, 0])
            self.assertEqual(section['low_side'], 'y0')
            self.assertEqual(section['plate'] + (section['rect'][3]-section['rect'][1])*section['pitch']/12, 8)
            self.assertEqual(original, legacy(native), 'migration does not mutate its input')
            self.assertTrue(notes)

    def test_renderer_wall_selection_and_wall_direction_are_preserved(self):
        for wall, low, bounds, host in [
            ('w0', 'y0', [3, -4, 17, 0], 2), ('w1', 'x1', [20, 3, 24, 17], 3),
            ('w2', 'y1', [3, 10, 17, 14], 0), ('w3', 'x0', [-4, 3, 0, 17], 1)]:
            raw = legacy(); raw['buildings'][0]['roof']['extensions'][0]['wall'] = wall
            value, _ = migrate_awnings(raw); r = converted(value)
            self.assertEqual(r['rect'], bounds); self.assertEqual(r['low_side'], low)
            self.assertEqual(r['host'], dict(wall=wall, edge=host))
        raw = legacy(); raw['buildings'][0]['roof']['extensions'][0].pop('wall')
        value, _ = migrate_awnings(raw)
        self.assertEqual(converted(value)['host']['wall'], 'w0')

    def test_nearest_renderer_wall_and_no_outline_normal_are_preserved(self):
        raw = legacy(); b = raw['buildings'][0]
        b['roof']['extensions'][0].pop('wall')
        for wall in b['walls']:
            wall['from'] = [wall['from'][0], wall['from'][1]+1]
            wall['to'] = [wall['to'][0], wall['to'][1]+1]
        b['levels'][0].pop('outline')
        value, _ = migrate_awnings(raw)
        self.assertEqual(converted(value)['host']['wall'], 'w0')
        self.assertEqual(converted(value)['rect'], [3, -3, 17, 1])

    def test_metadata_solar_flags_and_wall_joints_remain_untouched(self):
        raw = legacy(True); b = raw['buildings'][0]
        b['solar_zones'] = [dict(id='solar', roof='main', plane=[0, 0, 8], rect=[1, 1, 2, 2])]
        b['flags'] = [dict(id='keep', kind='roof', text='Check the porch', at=[1, 1])]
        aw = b['extensions'][0]
        aw.update(name='Porch shade', materials={'roof': {'id': 'metal'}}, hidden=True, locked=True,
                  downspouts=[.25, .75], notes=['Keep this note'])
        value, _ = migrate_awnings(raw); after = value['buildings'][0]; r = converted(value)
        for key in ('solar_zones', 'walls', 'joints', 'flags'):
            self.assertEqual(after[key], b[key])
        for key in ('name', 'materials', 'hidden', 'locked', 'notes', 'src'):
            self.assertEqual(r[key], aw[key])
        self.assertEqual(r['edges'][0]['downspouts'], [.25, .75])

    def test_zero_and_absent_legacy_bracket_count_does_not_invent_support_geometry(self):
        for missing in (False, True):
            raw = legacy(); aw = raw['buildings'][0]['roof']['extensions'][0]
            aw['brackets'] = 0
            if missing:
                aw.pop('brackets')
            value, _ = migrate_awnings(raw)
            self.assertEqual(converted(value)['support']['count'], 0)
            normalized, _ = twin_plan.normalize(value)
            self.assertEqual(converted(normalized)['support']['count'], 0)

    def test_missing_wall_keeps_a_flagged_roof_and_repeat_does_not_duplicate_it(self):
        raw = legacy(); raw['buildings'][0]['walls'] = []
        value, notes = migrate_awnings(raw)
        self.assertNotIn('host', converted(value))
        self.assertEqual(converted(value)['rect'], [3, -4, 17, 0])
        flags = value['buildings'][0]['flags']
        self.assertEqual([(f['id'], f['kind']) for f in flags], [('shade', 'roof')])
        self.assertTrue(notes)
        again, second = migrate_awnings(value)
        self.assertEqual(again, value); self.assertEqual(second, [])

    def test_no_legacy_extensions_is_byte_identical(self):
        raw = flat_house(); text = json.dumps(raw)
        value, notes = migrate_awnings(raw)
        self.assertEqual(json.dumps(value), text); self.assertEqual(notes, [])
        self.assertIs(value, raw, 'an already ordinary house takes the no-op path before copying')

    def test_flat_and_native_normalizers_apply_migration_and_keep_old_house_facts(self):
        for native in (False, True):
            raw = legacy(native); b = raw['buildings'][0]
            b['flags'] = [dict(id='existing', kind='roof', text='Check this roof', at=[1, 1])]
            b['solar_zones'] = []
            before = copy.deepcopy(b)
            value, _ = (model.normalize(raw) if native else twin_plan.normalize(raw))
            self.assertEqual(converted(value)['id'], 'shade')
            after = value['buildings'][0]
            self.assertEqual(after['flags'][0], before['flags'][0])
            if native:
                self.assertEqual(after['joints'], before['joints'])
                self.assertEqual(after['roofs'][0], before['roofs'][0])
            else:
                self.assertEqual(after['walls'], before['walls'])
            value2, _ = (model.normalize(value) if native else twin_plan.normalize(value))
            self.assertEqual(json.dumps(value), json.dumps(value2))

    def test_shed_continuation_becomes_an_ordinary_shed(self):
        raw = flat_house(); b = raw['buildings'][0]
        b['roof']['extensions'] = [dict(id='shed', kind='shed_continuation', section='main',
            to_x=25, pitch=3, overhang=.5, src={'person': True})]
        value, _ = migrate_awnings(raw)
        r = next(r for r in value['buildings'][0]['roof']['sections'] if r['id'] == 'shed')
        self.assertEqual(r['kind'], 'shed'); self.assertEqual(r['low_side'], 'x1')
        self.assertNotIn('support', r)
        self.assertEqual(r['rect'], [20, 0, 25, 10])
        self.assertEqual(r['plate'], 6.75)
        self.assertEqual(value['buildings'][0]['roof']['extensions'], [])

    def test_disk_reload_and_undo_return_to_migrated_native_history(self):
        settings = {}
        def update(values): settings.update(copy.deepcopy(values))
        with tempfile.TemporaryDirectory(prefix='awning_rounds_') as directory, \
                patch.object(store, 'DATA_DIR', directory), \
                patch.object(storage, 'get_settings', side_effect=lambda: copy.deepcopy(settings)), \
                patch.object(storage, 'patch_settings', side_effect=update):
            store._invalidate_reads()
            first = store._append_round(store._state(), legacy(True), 'load')
            store._invalidate_reads(); value = store.current_model()
            original = copy.deepcopy(converted(value))
            value['buildings'][0]['roofs'][-1]['plate'] += 1
            store._append_round(store._state(), value, 'edit')
            store.revert(first)
            store._invalidate_reads(); undo = store.current_model()
            self.assertEqual(converted(undo), original)
            store._invalidate_reads(); self.assertEqual(store.current_model(), undo)

    def test_owner_export_counts_and_walled_records(self):
        if OWNER_EXPORT is None:
            self.skipTest('Optional --owner-export path not supplied.')
        raw = json.loads(OWNER_EXPORT.read_text(encoding='utf-8'))['model']
        before = sum(e.get('kind') == 'awning' for b in raw['buildings'] for e in b.get('extensions', []))
        value, _ = migrate_awnings(raw)
        after = sum(e.get('kind') == 'awning' for b in value['buildings'] for e in b.get('extensions', []))
        supports = sum(r.get('support', {}).get('kind') == 'bracket'
                       for b in value['buildings'] for r in b['roofs'])
        self.assertEqual((before, supports, after), (2, 2, 0))
        for old, new in zip(raw['buildings'], value['buildings']):
            self.assertTrue(new['roofs'][:len(old['roofs'])] == old['roofs'], 'Owner walled roof records changed.')
            self.assertTrue(new['walls'] == old['walls'], 'Owner wall records changed.')
            self.assertTrue(new['joints'] == old['joints'], 'Owner joint records changed.')
        print('OWNER_MIGRATION ' + json.dumps(dict(legacy_awnings=before, supported_roofs=supports,
                                                  remaining_extensions=after, walled_records_equal=True)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--owner-export', type=Path)
    args, remaining = parser.parse_known_args()
    OWNER_EXPORT = args.owner_export
    unittest.main(argv=[sys.argv[0], *remaining], verbosity=2)

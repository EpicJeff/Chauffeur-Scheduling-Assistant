"""Task 1 gutter contract through normalization, model ops and the editor route."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ.pop('HA_BASE_URL', None)
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='gutters_model_')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import twin_model, twin_model_bridge as bridge, twin_model_ops as ops
from services import twin_model_roofs as roofs, twin_plan


def house():
    roof = roofs.from_section(dict(id='r', kind='hip', ridge='x', pitch=6,
                                  rect=[0, 0, 40, 30], plate=10, overhang=1, level='L1'))
    b = dict(id='b', levels=[dict(id='L1', elevation=0, ceiling=10)],
             joints=[], walls=[], rooms=[], roofs=[roof], position=[0, 0])
    return twin_model.normalize(dict(units='ft', buildings=[b], site={}))[0]


def edge_op(**fields):
    return dict(op='set_roof_edge', building='b', roof='r', edge=0, **fields)


def roof_of(model):
    return model['buildings'][0]['roofs'][0]


class GutterModel(unittest.TestCase):
    def test_gutter_ack_validated_and_cleared_on_drainage_change(self):
        model, _ = ops.apply(house(), edge_op(gutter=True))
        model, _ = ops.apply(model, edge_op(gutter_ack=['hang', 'stub']))
        self.assertEqual(roof_of(model)['edges'][0]['gutter_ack'], ['hang', 'stub'])
        self.assertEqual(roof_of(twin_model.normalize(model)[0])['edges'][0]['gutter_ack'], ['hang', 'stub'])
        for bad in (True, ['unknown'], ['hang', 'hang'], [1]):
            with self.subTest(bad=bad), self.assertRaises(ops.Refused) as refused:
                ops.apply(model, edge_op(gutter_ack=bad))
            for flag in twin_plan.GUTTER_FLAGS:
                self.assertIn(flag, str(refused.exception))
        for change in ({'gutter': False}, {'downspouts': [.2]}):
            changed, _ = ops.apply(model, edge_op(**change))
            self.assertNotIn('gutter_ack', roof_of(changed)['edges'][0])
        invalid = copy.deepcopy(model)
        roof_of(invalid)['edges'][0]['gutter_ack'] = ['unknown']
        self.assertIn('Roof r: invalid area, edges or dimensions.', twin_model.normalize(invalid)[1])

    def test_gable_to_sloped_with_gutter_in_one_op(self):
        model = house()
        roof_of(model)['edges'][1]['setting'] = 'gable'
        roof_of(model)['edges'][3]['setting'] = 'gable'
        result, _ = ops.apply(model, dict(edge_op(setting='sloped', gutter=True), edge=1))
        self.assertEqual(roof_of(result)['edges'][1]['setting'], 'sloped')
        self.assertTrue(roof_of(result)['edges'][1]['gutter'])
        self.assertEqual(roof_of(model)['edges'][1]['setting'], 'gable')

    def test_shed_high_edge_cannot_gain_a_gutter(self):
        model = house()
        model['buildings'][0]['roofs'][0] = roofs.from_section(dict(
            id='r', kind='shed', low_side='y0', pitch=6, rect=[0, 0, 40, 30],
            plate=10, overhang=1, level='L1'))
        self.assertEqual(roofs.eave_edge_indices(roof_of(model)), {0})
        with self.assertRaises(ops.Refused):
            ops.apply(model, dict(edge_op(gutter=True), edge=2))
        result, _ = ops.apply(model, edge_op(gutter=True))
        self.assertTrue(roof_of(result)['edges'][0]['gutter'])

    def test_rake_reset_restores_automatic_after_reenable_and_undo(self):
        model, _ = ops.apply(house(), edge_op(gutter=True, downspouts=[.3]))
        original = copy.deepcopy(model)
        changed, undo = ops.apply(model, {'op': 'batch', 'ops': [edge_op(gutter=False, downspouts=None), edge_op(setting='gable')]})
        self.assertNotIn('downspouts', roof_of(changed)['edges'][0])
        enabled, _ = ops.apply(changed, edge_op(setting='sloped'))
        enabled, _ = ops.apply(enabled, edge_op(gutter=True))
        self.assertNotIn('downspouts', roof_of(enabled)['edges'][0])
        self.assertEqual(model, original, 'batch leaves the undo source intact')

    def test_set_roof_edge_gutter_only(self):
        original = house()
        result, _ = ops.apply(original, edge_op(gutter=True))
        self.assertTrue(roof_of(result)['edges'][0]['gutter'])
        self.assertNotIn('gutter', roof_of(original)['edges'][0])
        normalized, _ = twin_model.normalize(result)
        self.assertTrue(roof_of(normalized)['edges'][0]['gutter'])
        self.assertNotEqual(roof_of(normalized).get('state'), 'ghost')

    def test_gutter_refused_on_gable_edge(self):
        for setting in ('gable', 'clip'):
            with self.subTest(setting=setting):
                model, _ = ops.apply(house(), edge_op(setting=setting))
                saved = copy.deepcopy(model)
                with self.assertRaises(ops.Refused):
                    ops.apply(model, edge_op(gutter=True))
                self.assertEqual(model, saved)
                with self.assertRaises(ops.Refused):
                    ops.apply(house(), edge_op(setting=setting, gutter=True))
                model, _ = ops.apply(model, edge_op(gutter=False))
                self.assertFalse(roof_of(model)['edges'][0]['gutter'])

    def test_setting_change_requires_removing_gutter(self):
        model, _ = ops.apply(house(), edge_op(gutter=True, downspouts=[.2]))
        with self.assertRaises(ops.Refused):
            ops.apply(model, edge_op(setting='gable'))
        model, _ = ops.apply(model, edge_op(setting='gable', gutter=False))
        self.assertFalse(roof_of(model)['edges'][0]['gutter'])

    def test_gutter_boolean_validation(self):
        for value in (1, 0, None, 'true', [], {}):
            with self.subTest(value=value):
                with self.assertRaises(ops.Refused):
                    ops.apply(house(), edge_op(gutter=value))

    def test_downspouts_validated(self):
        for value in ([], [0, .25, 1], [0] * 8):
            model, _ = ops.apply(house(), edge_op(downspouts=value))
            self.assertEqual(roof_of(model)['edges'][0]['downspouts'], value)
        for value in ([0] * 9, [-.01], [1.01], [True], ['.5'], [None],
                      [float('nan')], [float('inf')], {}, '.5', (.2,)):
            with self.subTest(value=value):
                with self.assertRaises(ops.Refused):
                    ops.apply(house(), edge_op(downspouts=value))

    def test_reset_to_automatic(self):
        model, _ = ops.apply(house(), edge_op(downspouts=[]))
        self.assertIn('downspouts', roof_of(model)['edges'][0])
        model, _ = ops.apply(model, edge_op(downspouts=None))
        self.assertNotIn('downspouts', roof_of(model)['edges'][0])

    def test_authored_validation(self):
        for field, value in [('gutter', 1), ('downspouts', [True]),
                             ('downspouts', [0] * 9), ('downspouts', None),
                             ('downspouts', [float('nan')])]:
            with self.subTest(field=field, value=value):
                model = house()
                roof_of(model)['edges'][0][field] = value
                normalized, notes = twin_model.normalize(model)
                self.assertIn('Roof r: invalid area, edges or dimensions.', notes)
                self.assertEqual(roof_of(normalized)['edges'][0][field],
                                 roof_of(model)['edges'][0][field])
        model = house()
        roof_of(model)['edges'][0].update(setting='clip', gutter=True)
        self.assertIn('Roof r: invalid area, edges or dimensions.', twin_model.normalize(model)[1])

    def test_sections_mirror_gutters_and_downspouts(self):
        model = house()
        roof = roof_of(model)
        roof['edges'][0].update(gutter=True, downspouts=[.2, .9])
        roof['edges'][2].update(gutter=True, downspouts=[])
        section = bridge.flatten(model)['buildings'][0]['roof']['sections'][0]
        self.assertEqual(section['gutters'], {'y0': True, 'y1': True})
        self.assertEqual(section['downspouts'], {'y0': [.2, .9], 'y1': []})
        flat, notes = twin_plan.normalize(bridge.flatten(model))
        self.assertEqual(flat['buildings'][0]['roof']['sections'][0]['gutters'], section['gutters'])
        self.assertEqual(flat['buildings'][0]['roof']['sections'][0]['downspouts'], section['downspouts'])
        section['downspouts']['y0'].append(.5)
        self.assertEqual(roof['edges'][0]['downspouts'], [.2, .9])

    def test_section_mapping_uses_largest_overlap_and_no_interior_sides(self):
        roof = roof_of(house())
        roof['area'] = [[0, 0], [40, 0], [40, 15], [20, 15], [20, 30], [0, 30]]
        roof['edges'] = [dict(setting='sloped', pitch=6, gutter=True, downspouts=[i / 10])
                         for i in range(6)]
        sections = roofs.to_sections(roof)
        for section in sections:
            for side, index in section['plane_edges'].items():
                if index is None:
                    self.assertNotIn(side, section.get('gutters', {}))
                    self.assertNotIn(side, section.get('downspouts', {}))
                else:
                    self.assertIs(section['gutters'][side], True)
                    self.assertEqual(section['downspouts'][side], [index / 10])

    def test_section_validation(self):
        flat = bridge.flatten(house())
        section = flat['buildings'][0]['roof']['sections'][0]
        section['gutters'] = {'y0': True, 'x1': 1, 'inside': True, 'x0': False}
        section['downspouts'] = {'y0': [], 'x1': [True], 'inside': [.5], 'x0': [1.1]}
        cleaned, notes = twin_plan.normalize(flat)
        got = cleaned['buildings'][0]['roof']['sections'][0]
        self.assertEqual(got['gutters'], {'y0': True})
        self.assertEqual(got['downspouts'], {'y0': []})
        self.assertTrue(notes)
        for field in ('gutters', 'downspouts'):
            section[field] = []
        got = twin_plan.normalize(flat)[0]['buildings'][0]['roof']['sections'][0]
        self.assertNotIn('gutters', got)
        self.assertNotIn('downspouts', got)
        section.update(gutters={'y0': True, 'x1': True},
                       downspouts={'y0': [.5], 'x1': []},
                       plane_edges={'y0': None, 'x1': 1})
        got = twin_plan.normalize(flat)[0]['buildings'][0]['roof']['sections'][0]
        self.assertEqual(got['gutters'], {'x1': True})
        self.assertEqual(got['downspouts'], {'x1': []})
        section.update(kind='gable', ends={'x1': 'clip'}, gutters={'y0': True, 'x1': True})
        got = twin_plan.normalize(flat)[0]['buildings'][0]['roof']['sections'][0]
        self.assertNotIn('gutters', got)  # y0 is interior, x1 is a clipped rake.

    def test_from_section_round_trip(self):
        model, _ = ops.apply(house(), edge_op(gutter=True, downspouts=[.3]))
        section = roofs.to_sections(roof_of(model))[0]
        rebuilt = roofs.from_section(section)
        self.assertTrue(rebuilt['edges'][0]['gutter'])
        self.assertEqual(rebuilt['edges'][0]['downspouts'], [.3])
        self.assertNotIn('gutters', rebuilt)
        self.assertNotIn('downspouts', rebuilt)

    def test_move_edge_keeps_fractions(self):
        model, _ = ops.apply(house(), edge_op(gutter=True, downspouts=[.1, .85]))
        # Moving a neighbouring edge stretches edge 0: fractions stay authored.
        model, _ = ops.apply(model, dict(op='move_roof_edge', building='b', roof='r', edge=1, by=5))
        self.assertEqual(roof_of(model)['edges'][0]['downspouts'], [.1, .85])
        self.assertEqual(roof_of(model)['area'][1], [45, 0])

    def test_edge_data_follows_plane_materials(self):
        from services import twin_edit, twin_register
        for operation in [dict(op='move_roof_edge', roof='r', edge=0, by=2),
                          dict(op='set_roof_edge', roof='r', edge=0, setting='sloped', pitch=9),
                          dict(op='set', id='r', field='pitch', value=8),
                          dict(op='set', id='r', field='kind', value='flat'),
                          dict(op='set', id='r', field='plate', value=12),
                          dict(op='set', id='r', field='overhang', value=2),
                          dict(op='set', id='r', field='ridge', value='y'),
                          dict(op='set', id='r', field='ends', value={'x1': 'clip'}),
                          dict(op='move', piece='r', by=[2, 3]),
                          dict(op='registration', source='sheet', page=1, level='L1',
                               from_reg=twin_register.make(1), reg=twin_register.make(2)),
                          dict(op='set', piece='r', field='pitch', value=8)]:
            with self.subTest(operation=operation):
                model = house()
                roof_of(model)['plane_materials'] = {'0': {'id': 'standing_seam'}}
                roof_of(model)['edges'][0].update(gutter=True, downspouts=[.3])
                roof_of(model)['src'] = dict(sheet='sheet', page=1, step='draft')
                result, _ = twin_edit.apply_model(model, dict(building='b', **operation))
                roof = roof_of(result)
                self.assertIn('0', roof['plane_materials'])
                self.assertTrue(roof['edges'][0]['gutter'])
                self.assertEqual(roof['edges'][0]['downspouts'], [.3])

        # Legacy moves and form edits rebuild a canonical rectangle. The
        # section's plane_edges reindexes both material and drainage data.
        for operation in (dict(op='move', piece='r', by=[2, 3]),
                          dict(op='set', piece='r', field='pitch', value=8)):
            with self.subTest(reindexed=operation):
                model = house()
                roof = roof_of(model)
                roof['area'] = roof['area'][1:] + roof['area'][:1]
                roof['plane_materials'] = {'0': {'id': 'standing_seam'}}
                roof['edges'][0].update(gutter=True, downspouts=[.3])
                result, _ = twin_edit.apply_model(model, dict(building='b', **operation))
                got = roof_of(result)
                self.assertEqual(set(got['plane_materials']), {'1'})
                self.assertEqual([i for i, e in enumerate(got['edges']) if e.get('gutter')], [1])
                self.assertEqual(got['edges'][1]['downspouts'], [.3])

        # Wall graph edits keep edge indices, including split/merge of a wall
        # that carries a roof edge. There is no roof-vertex edit operation.
        from test_twin_model_ops_walls import box
        for operation in (dict(op='move_wall', wall='e', by=-2),
                          dict(op='move_joint', joint='j2', to=[12, 0]),
                          dict(op='move_joints', joints=[dict(joint='j2', to=[12, 0]),
                                                       dict(joint='j3', to=[12, 10])]),
                          dict(op='move_room', room='kitchen', by=[2, 3]),
                          dict(op='split_wall', wall='s', at=5)):
            with self.subTest(wall_operation=operation):
                roof = roof_of(house())
                roof['area'] = [[0, 0], [10, 0], [10, 10], [0, 10]]
                roof['plate'] = 9
                roof['plane_materials'] = {'0': {'id': 'standing_seam'}}
                for e, wall in zip(roof['edges'], ('s', 'e', 'n', 'w')):
                    e['wall'] = wall
                roof['edges'][0].update(gutter=True, downspouts=[.3])
                result, _ = ops.apply(box(roofs=[roof]), dict(building='B1', **operation))
                got = roof_of(result)
                self.assertIn('0', got['plane_materials'])
                self.assertTrue(got['edges'][0]['gutter'])
                self.assertEqual(got['edges'][0]['downspouts'], [.3])
                if operation['op'] == 'split_wall':
                    joint = next(j['id'] for j in result['buildings'][0]['joints'] if j['at'] == [5, 0])
                    result, _ = ops.apply(result, dict(op='delete', building='B1', id=joint))
                    got = roof_of(result)
                    self.assertIn('0', got['plane_materials'])
                    self.assertTrue(got['edges'][0]['gutter'])
                    self.assertEqual(got['edges'][0]['downspouts'], [.3])

        # Accepting a replacement uses the proposal's complete record; old
        # edge overrides are not inherited, just as old plane materials aren't.
        for keep in (False, True):
            with self.subTest(replacement_carries_data=keep):
                model = house()
                roof = roof_of(model)
                roof['plane_materials'] = {'0': {'id': 'standing_seam'}}
                roof['edges'][0].update(gutter=True, downspouts=[.3])
                replacement = copy.deepcopy(roof if keep else roof_of(house()))
                model['buildings'][0]['proposals'] = [dict(id='proposal', kind='roof',
                                                          against='r', piece=replacement)]
                result, _ = ops.apply(model, dict(op='accept_proposal', building='b', id='proposal'))
                got = roof_of(result)
                self.assertEqual('plane_materials' in got, keep)
                self.assertEqual('gutter' in got['edges'][0], keep)
                self.assertEqual('downspouts' in got['edges'][0], keep)

        # Creating a roof and deleting the old one do not transfer edge data.
        model = house()
        roof_of(model)['plane_materials'] = {'0': {'id': 'standing_seam'}}
        roof_of(model)['edges'][0].update(gutter=True, downspouts=[.3])
        model, _ = ops.apply(model, dict(op='draw_roof', building='b', area=[[50, 0], [60, 0], [60, 10], [50, 10]]))
        model, _ = ops.apply(model, dict(op='delete', building='b', id='r'))
        got = roof_of(model)
        self.assertNotIn('plane_materials', got)
        self.assertTrue(all('gutter' not in e and 'downspouts' not in e for e in got['edges']))

        for operation in (dict(op='roof_over', rooms=['kitchen']),
                          dict(op='add_porch', level='L1',
                               polygon=[[2, 0], [8, 0], [8, -6], [2, -6]], roof='shed'),
                          dict(op='add_porch', level='L1',
                               polygon=[[2, 0], [8, 0], [8, -6], [5, -6], [5, -9], [2, -9]], roof='shed')):
            with self.subTest(new_roof=operation):
                old = roof_of(house())
                old['area'] = [[0, 0], [10, 0], [10, 10], [0, 10]]
                old['plane_materials'] = {'0': {'id': 'standing_seam'}}
                old['edges'][0].update(gutter=True, downspouts=[.3])
                result, _ = ops.apply(box(roofs=[old]), dict(building='B1', **operation))
                fresh = [r for r in result['buildings'][0]['roofs'] if r['id'] != 'r']
                self.assertTrue(fresh)
                for got in fresh:
                    self.assertNotIn('plane_materials', got)
                    self.assertTrue(all('gutter' not in e and 'downspouts' not in e for e in got['edges']))

    def test_from_section_drops_unmapped_edge_data(self):
        roof = roof_of(house())
        roof['area'] = [[0, 0], [40, 0], [40, 15], [20, 15], [20, 30], [0, 30]]
        roof['edges'] = [dict(setting='sloped', pitch=6, gutter=True, downspouts=[i / 10])
                         for i in range(6)]
        roof['plane_materials'] = {str(i): {'id': 'standing_seam', 'color': f'#{i:06x}'} for i in range(6)}
        for section in roofs.to_sections(roof):
            rebuilt = roofs.from_section(section)
            mapping = section['plane_edges']
            for i, side in enumerate(('y0', 'x1', 'y1', 'x0')):
                index = mapping[side]
                self.assertEqual(str(i) in rebuilt['plane_materials'], index is not None)
                self.assertEqual('gutter' in rebuilt['edges'][i], index is not None)
                self.assertEqual('downspouts' in rebuilt['edges'][i], index is not None)
                if index is not None:
                    self.assertEqual(rebuilt['edges'][i]['downspouts'], [index / 10])

    def test_roof_form_change_refuses_a_guttered_rake(self):
        model, _ = ops.apply(house(), dict(edge_op(gutter=True), edge=1))
        with self.assertRaises(ops.Refused):
            ops.apply(model, dict(op='set', building='b', id='r', field='kind', value='gable'))

    def test_porch_and_awning_gutter_flags(self):
        model = house()
        b = model['buildings'][0]
        b['porches_detail'] = [dict(id='p', polygon=[[0, 0], [10, 0], [10, -6], [0, -6]],
                                    floor=0, columns=[])]
        b['extensions'] = [dict(id='a', kind='awning', section='r', x0=2, x1=10,
                                depth=4, eave=8, pitch=3)]
        b['joints'] = [dict(id='j0', level='L1', at=[0, 0]), dict(id='j1', level='L1', at=[40, 0])]
        b['walls'] = [dict(id='front', level='L1', joints=['j0', 'j1'],
                           height=10, thickness=.5, exterior=True)]
        model = twin_model.normalize(model)[0]
        for pid in ('p',):
            model, _ = ops.apply(model, dict(op='set', building='b', id=pid, field='gutter', value=True))
            model, _ = ops.apply(model, dict(op='set', building='b', id=pid, field='gutter_ack', value=['hang', 'stub']))
            with self.assertRaises(ops.Refused):
                ops.apply(model, dict(op='set', building='b', id=pid, field='gutter_ack', value=['unknown']))
            with self.assertRaises(ops.Refused):
                ops.apply(model, dict(op='set', building='b', id=pid, field='gutter', value=1))
        awning_op = dict(op='set_roof_edge', building='b', roof='a', edge=0)
        model, _ = ops.apply(model, dict(awning_op, gutter=True))
        model, _ = ops.apply(model, dict(awning_op, gutter_ack=['hang', 'stub']))
        for invalid in ({'gutter_ack': ['unknown']}, {'gutter': 1}):
            with self.assertRaises(ops.Refused):
                ops.apply(model, dict(awning_op, **invalid))
        b = bridge.flatten(model)['buildings'][0]
        shade = next(s for s in b['roof']['sections'] if s['id'] == 'a')
        self.assertTrue(b['porches'][0]['gutter'])
        self.assertTrue(shade['edges'][0]['gutter'])
        self.assertEqual(b['porches'][0]['gutter_ack'], ['hang', 'stub'])
        self.assertEqual(shade['edges'][0]['gutter_ack'], ['hang', 'stub'])
        roundtrip = bridge.assemble(twin_plan.normalize(dict(units='ft', buildings=[b], site={}))[0])[0]
        self.assertTrue(roundtrip['buildings'][0]['porches_detail'][0]['gutter'])
        self.assertTrue(next(r for r in roundtrip['buildings'][0]['roofs'] if r['id'] == 'a')['edges'][0]['gutter'])
        self.assertTrue(model['buildings'][0]['porches_detail'][0]['src']['person'])
        self.assertTrue(next(r for r in model['buildings'][0]['roofs'] if r['id'] == 'a')['src']['person'])
        for pid in ('p',):
            model, _ = ops.apply(model, dict(op='set', building='b', id=pid, field='gutter', value=False))
        model, _ = ops.apply(model, dict(awning_op, gutter=False))
        b = bridge.flatten(model)['buildings'][0]
        shade = next(s for s in b['roof']['sections'] if s['id'] == 'a')
        self.assertFalse(b['porches'][0]['gutter'])
        self.assertFalse(shade['edges'][0]['gutter'])
        self.assertNotIn('gutter_ack', b['porches'][0])
        self.assertNotIn('gutter_ack', shade['edges'][0])

    def test_attachment_flags_validated(self):
        model = house()
        b = model['buildings'][0]
        b['porches_detail'] = [dict(id='p', polygon=[[0, 0], [10, 0], [10, -6], [0, -6]],
                                    floor=0, columns=[], gutter='yes')]
        b['extensions'] = [dict(id='a', kind='awning', section='r', x0=2, x1=10,
                                depth=4, eave=8, pitch=3, gutter=1)]
        normalized, notes = twin_model.normalize(model)
        self.assertNotIn('gutter', normalized['buildings'][0]['porches_detail'][0])
        shade = next(r for r in normalized['buildings'][0]['roofs'] if r['id'] == 'a')
        self.assertNotIn('gutter', shade['edges'][0])
        self.assertTrue(notes)
        flat, notes = twin_plan.normalize(bridge.flatten(model))
        self.assertNotIn('gutter', flat['buildings'][0]['porches'][0])
        shade = next(r for r in flat['buildings'][0]['roof']['sections'] if r['id'] == 'a')
        self.assertNotIn('gutter', shade['edges'][0])

    def test_porch_room_gutter_uses_generator_detail(self):
        from test_twin_model_ops_walls import box
        model, _ = ops.apply(box(), dict(op='set_room_kind', building='B1', room='kitchen', kind='porch'))
        model['buildings'][0]['porches_detail'] = []
        model, _ = ops.apply(model, dict(op='set', building='B1', id='kitchen', field='gutter', value=True))
        self.assertTrue(model['buildings'][0]['porches_detail'][0]['gutter'])
        self.assertTrue(bridge.flatten(model)['buildings'][0]['porches'][0]['gutter'])

    def test_no_gutters_plan_unchanged(self):
        section = roofs.to_sections(roof_of(house()))[0]
        self.assertEqual(section, dict(id='r', kind='hip', ridge='x', pitch=6, plate=10,
                                      overhang=1, level='L1', rect=[0, 0, 40, 30], roof='r',
                                      ends={'x0': 'hip', 'x1': 'hip'},
                                      plane_edges={'y0': 0, 'x1': 1, 'y1': 2, 'x0': 3}))
        fixture = Path(__file__).parent / 'fixtures/twin_model/household-2026-11-09.json'
        model = bridge.assemble(json.loads(fixture.read_text(encoding='utf-8')))[0]
        from services.twin_model_supports import is_supported
        sections = [[copy.deepcopy(s) for s in b['roof']['sections'] if not is_supported(s)]
                    for b in bridge.flatten(model)['buildings']]
        # The fixture has no P0 roof-main, so no beam migration metadata is
        # expected: retain every field of its original walled sections.
        # Captured from HEAD's to_sections before implementing Task 1.
        digest = hashlib.sha256(json.dumps(sections, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(digest, '69517edff37d5d696f86908ec942c3edfb88b3047495fe5a86bb03ca9d6757f6')


class GutterRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from services import storage, twin_store
        import main
        cls.store = twin_store
        storage.add_member(dict(id='gutter-parent', name='Parent', role='parent'))
        cls.headers = {'X-Member-Token': storage.create_member_token('gutter-parent')}
        cls.client = TestClient(main.app)

    def load(self):
        model = house()
        if self.store.current_id() is None:
            self.store.push_round(bridge.flatten(model), 'build')
        self.store.update_model(lambda _: model, kind='build')
        return self.store.current_model()

    def post(self, op, status=200):
        response = self.client.post('/api/house/editor/op', headers=self.headers, json={'op': op})
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def test_batch_all_eaves_is_one_round(self):
        original = self.load()
        before, count = self.store.current_id(), len(self.store.rounds())
        result = self.post(dict(op='batch', ops=[dict(edge_op(gutter=True), edge=i) for i in range(4)]))
        self.assertEqual(len(self.store.rounds()), count + 1)
        self.assertTrue(all(e['gutter'] for e in roof_of(result['model'])['edges']))
        self.assertEqual(result['plan']['buildings'][0]['roof']['sections'][0]['gutters'],
                         dict(y0=True, x1=True, y1=True, x0=True))
        self.store.revert(before)
        self.assertEqual(self.store.current_model(), original)

    def test_rake_batch_undo_restores_overrides_and_reenable_is_automatic(self):
        self.load()
        original = self.post(edge_op(gutter=True, downspouts=[.3]))['model']
        before, count = self.store.current_id(), len(self.store.rounds())
        batch = dict(op='batch', ops=[edge_op(gutter=False, downspouts=None), edge_op(setting='gable')])
        self.post(batch)
        self.assertEqual(len(self.store.rounds()), count + 1)
        self.store.revert(before)
        self.assertEqual(self.store.current_model(), original)
        self.post(batch)
        self.post(edge_op(setting='sloped'))
        result = self.post(edge_op(gutter=True))['model']
        self.assertNotIn('downspouts', roof_of(result)['edges'][0])

    def test_route_override_reset_and_refusal_are_atomic(self):
        self.load()
        self.post(edge_op(gutter=True, downspouts=[.25]))
        saved, before = self.store.current_model(), self.store.current_id()
        self.post(dict(op='batch', ops=[edge_op(downspouts=[]), edge_op(gutter='true')]), 400)
        self.assertEqual(self.store.current_id(), before)
        self.assertEqual(self.store.current_model(), saved)
        result = self.post(edge_op(downspouts=None))
        self.assertNotIn('downspouts', roof_of(result['model'])['edges'][0])
        self.assertNotIn('downspouts', result['plan']['buildings'][0]['roof']['sections'][0])


if __name__ == '__main__':
    unittest.main(verbosity=2)

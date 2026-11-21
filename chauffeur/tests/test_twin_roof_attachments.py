"""Roof attachments follow through the real editor route and shared agent path."""
import copy
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='roof_attachments_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import twin_model, twin_model_ops as ops, twin_model_bridge as bridge, twin_solar as solar


def house(kind='gable', pitch=6):
    from services.twin_model_roofs import from_section
    roof = from_section(dict(id='r', name='South roof', kind=kind, pitch=pitch,
                             ridge='x', rect=[0, 0, 40, 30], plate=10, overhang=0, level='L1'))
    b = dict(id='b', position=[0, 0], rotation=0, base=0,
             levels=[dict(id='L1', elevation=0, ceiling=10)],
             joints=[], walls=[], rooms=[], roofs=[roof])
    return twin_model.normalize(dict(units='ft', buildings=[b], site={}))[0]


class RoofAttachments(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from services import storage, twin_store
        import main
        cls.store = twin_store
        storage.add_member(dict(id='roof-parent', name='Parent', role='parent'))
        cls.headers = {'X-Member-Token': storage.create_member_token('roof-parent')}
        cls.client = TestClient(main.app)

    def load(self, model):
        if self.store.current_id() is None:
            self.store.push_round(bridge.flatten(model), 'build')
        self.store.update_model(lambda _: copy.deepcopy(model), kind='build')

    def post(self, op, status=200):
        response = self.client.post('/api/house/editor/op', headers=self.headers, json={'op': op})
        self.assertEqual(response.status_code, status, f'{op}: {response.text}')
        return response.json()

    def seed(self, model=None, rect=None, **values):
        self.load(model or house())
        b = self.store.current_model()['buildings'][0]
        plane = values.pop('plane', None)
        face = next(f for f in solar.faces(b) if plane is None or list(f['plane']) == plane)
        poly = face['polygon']
        rect = rect or [min(p[0] for p in poly)+2, min(p[1] for p in poly)+2,
                        max(p[0] for p in poly)-2, max(p[1] for p in poly)-2]
        return self.post(dict(op='add_solar_zone', building=b['id'], roof=face['roof'],
                              plane=list(face['plane']), rect=rect, **values))['model']

    def face(self, b, zone):
        return max((f for f in solar.faces(b) if f['roof'] == zone['roof'] and
                    all(abs(a-c) < solar.EPS for a, c in zip(f['plane'], zone['plane']))),
                   key=lambda f: abs(solar.area(f['polygon'])))

    def margins(self, b, zone):
        p = self.face(b, zone)['polygon']; r = zone['rect']
        return [r[0]-min(q[0] for q in p), r[1]-min(q[1] for q in p),
                max(q[0] for q in p)-r[2], max(q[1] for q in p)-r[3]]

    def assertValid(self, model):
        for b in model['buildings']:
            for z in b['solar_zones']:
                self.assertIsNone(solar.error(b, z, b['solar_zones']), z)

    def test_eave_three_feet_preserves_two_foot_offsets_and_undo(self):
        m = self.seed(); before = self.store.current_id()
        count = len(self.store.rounds())
        result = self.post(dict(op='move_roof_edge', building='b', roof='r', edge=0, by=3))
        b = result['model']['buildings'][0]; z = b['solar_zones'][0]
        for d in self.margins(b, z): self.assertAlmostEqual(d, 2)
        self.assertValid(result['model'])
        self.assertEqual(len(self.store.rounds()), count+1)
        self.store.revert(before)
        self.assertEqual(self.store.current_model(), m)

    def test_pitch_overhang_plate_ridge_and_building_frame(self):
        m = self.seed()
        for field, value in [('pitch', 12), ('overhang', 2), ('plate', 14), ('ridge', 'y')]:
            result = self.post(dict(op='set', building='b', id='r', field=field, value=value))
            m = result['model']; b = m['buildings'][0]; z = b['solar_zones'][0]
            for d in self.margins(b, z): self.assertAlmostEqual(d, 2, msg=field)
            self.assertValid(m)
        zones = copy.deepcopy(m['buildings'][0]['solar_zones'])
        for op in [dict(op='move_building', to=[12, 9]), dict(op='rotate_building', degrees=30)]:
            # The building frame carries local plane coordinates rigidly.
            if op['op'] == 'rotate_building':
                op = dict(op='set', id='b', field='rotation', value=30)
            m = self.post(dict(building='b', **op))['model']
            self.assertEqual(m['buildings'][0]['solar_zones'], zones)
            self.assertValid(m)

    def test_minimum_and_missing_plane_refusals_name_zone_and_are_atomic(self):
        for orientation in ('portrait', 'landscape'):
            m = self.seed(house('flat', 0), orientation=orientation,
                          panel_width=8, panel_height=4)
            current = self.store.current_id()
            result = self.post(dict(op='move_roof_edge', building='b', roof='r', edge=1, by=-34), 400)
            self.assertIn('That leaves the solar zone on South roof too small; resize or delete it first.', result['error'])
            self.assertEqual(self.store.current_id(), current)
            self.assertEqual(self.store.current_model(), m)
        m = self.seed()
        result = self.post(dict(op='set', building='b', id='r', field='kind', value='flat'), 400)
        self.assertIn('South roof', result['error'])
        self.assertIn('its roof plane would be gone', result['error'])
        self.assertEqual(self.store.current_model(), m)

    def test_unaffected_small_zone_does_not_block_another_roof(self):
        m = house('flat', 0)
        other = copy.deepcopy(m['buildings'][0]['roofs'][0])
        other.update(id='other', area=[[60,0],[100,0],[100,30],[60,30]])
        m['buildings'][0]['roofs'].append(other)
        m = self.seed(m, rect=[2,2,3,3])
        original = copy.deepcopy(m['buildings'][0]['solar_zones'])
        changed = self.post(dict(op='set', building='b', id='other', field='plate', value=12))['model']
        self.assertEqual(changed['buildings'][0]['solar_zones'], original)

    def test_collision_shrinks_later_facing_edge_and_refuses_below_panel(self):
        self.seed(house('flat', 0), rect=[2, 2, 12, 15])
        self.post(dict(op='add_solar_zone', building='b', roof='r', plane=[0, 0, 10], rect=[20, 2, 38, 15]))
        # Both keep their opposite roof margins; expansion overlaps by two feet.
        m = self.post(dict(op='move_roof_edge', building='b', roof='r', edge=1, by=10))['model']
        a, b = m['buildings'][0]['solar_zones']
        self.assertAlmostEqual(a['rect'][2], 22)
        self.assertAlmostEqual(b['rect'][0], 22)
        self.assertValid(m)
        # A later zone with a large minimum cannot be squeezed into the remainder.
        m['buildings'][0]['solar_zones'][1].update(panel_width=32, panel_height=10, orientation='landscape')
        self.load(m); saved = self.store.current_model()
        result = self.post(dict(op='move_roof_edge', building='b', roof='r', edge=1, by=4), 400)
        self.assertIn('too small', result['error'])
        self.assertEqual(self.store.current_model(), saved)

    def test_hip_diagonals_shrink_corners_inward_when_panels_still_fit(self):
        scale = math.sqrt(1.25)
        self.seed(house('hip'), rect=[11,2*scale,29,10*scale], plane=[0,.5,10])
        m = self.post(dict(op='move_roof_edge', building='b', roof='r', edge=2, by=20))['model']
        b = m['buildings'][0]; zone = b['solar_zones'][0]
        self.assertValid(m)
        self.assertGreaterEqual(solar.capacity(zone), 1)
        # The new triangular face permits a ten-foot-wide rectangle here.
        self.assertGreaterEqual(zone['rect'][2]-zone['rect'][0], 10-1e-6)

    def test_legacy_shed_continuation_keeps_its_depth(self):
        m = house()
        m['buildings'][0]['extensions'] = [dict(id='continuation', kind='shed_continuation',
             section='r', side='x1', to_x=48, pitch=3, overhang=1, state='settled')]
        self.load(m)
        m = self.post(dict(op='move_roof_edge', building='b', roof='r', edge=1, by=3))['model']
        self.assertEqual(m['buildings'][0]['extensions'][0]['to_x'], 51)

    def test_deleted_roof_extensions_stay_as_recoverable_ghosts(self):
        from services import twin_plan
        m = house()
        m['buildings'][0]['extensions'] = [dict(id='continuation', kind='shed_continuation',
             section='r', side='x1', to_x=48, pitch=3, overhang=1, state='settled'),
             dict(id='awning', kind='awning', section='r', x0=5, x1=15, depth=4, pitch=2,eave=9,state='settled')]
        self.load(m); before=self.store.current_id()
        result = self.post(dict(op='delete', building='b', id='r'))
        for e in result['model']['buildings'][0]['extensions']:
            self.assertEqual(e['state'],'ghost')
            self.assertIn('lost its roof',e['why'])
            self.assertEqual(len(e['position']),2)
        flat = twin_plan.normalize(result['plan'])[0]
        self.assertEqual(len(flat['buildings'][0]['roof']['extensions']),2)
        self.store.revert(before)
        self.assertEqual(self.store.current_model()['buildings'][0]['extensions'],m['buildings'][0]['extensions'])

    def test_delete_cascades_source_scoped_and_one_undo_restores_both(self):
        m = self.seed()
        self.post(dict(op='set_solar_source', building='b', roof='r'))
        saved = self.store.current_model(); before = self.store.current_id(); count = len(self.store.rounds())
        result = self.post(dict(op='delete', building='b', id='r'))
        b = result['model']['buildings'][0]
        self.assertEqual(b['roofs'], [])
        self.assertEqual(b['solar_zones'], [])
        self.assertIsNone(result['model']['solar_source_roof'])
        self.assertIsNone(result['model'].get('solar_source_building'))
        self.assertIn('Deleted the roof and its solar zones.', result['words'])
        self.assertEqual(len(self.store.rounds()), count+1)
        self.store.revert(before)
        self.assertEqual(self.store.current_model(), saved)

    def test_source_delete_respects_duplicate_roof_ids_in_other_buildings(self):
        original=self.seed()
        other=copy.deepcopy(original['buildings'][0]);other['id']='other';other['solar_zones']=[]
        original['buildings'].append(other)
        for owner in ('b','other'):
            self.load(original)
            self.post(dict(op='set_solar_source',building=owner,roof='r'))
            m=self.post(dict(op='delete',building='b',id='r'))['model']
            self.assertEqual(m['solar_source_roof'],None if owner=='b' else 'r')
            self.assertEqual(m['solar_source_building'],None if owner=='b' else 'other')

    def test_agent_legacy_edit_path_uses_same_docking(self):
        from services import twin_edit
        m = self.seed()
        changed, _ = twin_edit.apply_model(m, dict(op='set', building='b', piece='r', field='pitch', value=10))
        b = changed['buildings'][0]
        for d in self.margins(b, b['solar_zones'][0]): self.assertAlmostEqual(d, 2)
        self.assertValid(changed)
        self.assertNotEqual(changed['buildings'][0]['solar_zones'][0]['plane'], m['buildings'][0]['solar_zones'][0]['plane'])

    def test_real_agent_handler_and_legacy_delete(self):
        from services.agent_tools_v2 import handle_house_design
        m = self.seed()
        response = handle_house_design(dict(action='edit', edit=dict(op='set', building='b', piece='r',
                                        field='plate', value=12)), actor=dict(id='roof-parent', role='parent'))
        self.assertEqual(response['status'], 'ok', response)
        b = self.store.current_model()['buildings'][0]
        self.assertEqual(b['solar_zones'][0]['plane'], [0, .5, 12])
        response = handle_house_design(dict(action='edit', edit=dict(op='delete', building='b', piece='r')),
                                      actor=dict(id='roof-parent', role='parent'))
        self.assertEqual(response['status'], 'ok', response)
        self.assertEqual(response['summary'], 'Deleted the roof and its solar zones.')
        self.assertEqual(self.store.current_model()['buildings'][0]['solar_zones'], [])

    def test_roof_edge_point_hosts_follow_and_refuse_off_edge(self):
        m = house()
        m = ops.apply(m, dict(op='add_item', building='b', asset='chair',
                              host=dict(roof='r', edge=0, at=30, z=0)))[0]
        self.load(m)
        result = self.post(dict(op='move_roof_edge', building='b', roof='r', edge=0, by=3))
        b = result['model']['buildings'][0]; item = b['items'][0]
        from services import twin_model_hosts as hosts
        self.assertEqual(hosts.world_point(b, item['host'])[:2], [30, -3])
        saved = self.store.current_model()
        result = self.post(dict(op='move_roof_edge', building='b', roof='r', edge=1, by=-20), 400)
        self.assertIn('off', result['error'])
        self.assertEqual(self.store.current_model(), saved)

    def test_roof_point_stays_live_on_a_short_but_usable_edge(self):
        m = ops.apply(house(), dict(op='add_item', building='b', asset='chair',
                                  host=dict(roof='r', edge=0, at=.6, z=0)))[0]
        self.load(m)
        m = self.post(dict(op='move_roof_edge', building='b', roof='r', edge=1, by=-39.2))['model']
        self.assertEqual(m['buildings'][0]['items'][0]['state'], 'settled')
        self.assertAlmostEqual(m['buildings'][0]['items'][0]['host']['at'], .6)

    def test_one_custom_panel_respects_orientation(self):
        for orientation, status in [('portrait',200),('landscape',400)]:
            self.seed(house('flat',0), orientation=orientation, panel_width=8, panel_height=4)
            result = self.post(dict(op='move_roof_edge', building='b', roof='r', edge=1, by=-30), status)
            if status == 400: self.assertIn('too small',result['error'])
            else: self.assertValid(result['model'])

    def test_dormer_width_docks_to_eave_ends(self):
        self.load(house())
        self.post(dict(op='add_dormer', building='b', roof='r', edge=0, at=20, width=8, pitch=6))
        result = self.post(dict(op='move_roof_edge', building='b', roof='r', edge=1, by=3))
        d = result['model']['buildings'][0]['dormers'][0]
        self.assertAlmostEqual(d['width'], 11)
        self.assertAlmostEqual(d['at'], 21.5)

    def test_roof_and_solar_path_anchors_project_and_refuse_off_plane(self):
        from services import twin_fixtures as fixtures
        from uuid import uuid4
        m = self.seed()
        zid = m['buildings'][0]['solar_zones'][0]['id']
        for kind, hid in [('roof', 'r'), ('solar_zone', zid)]:
            host = dict(kind=kind, id=hid, building='b')
            path = [[8, 4, 12], [12, 4, 12]]
            bindings = [dict(host=host, local=list(p)) for p in path]
            fixture = dict(id='fixture:'+str(uuid4()), shape='line', ref='absolute', path=copy.deepcopy(path), anchors=bindings)
            effect = {**copy.deepcopy(fixture), 'id':'effect:'+str(uuid4()), 'type':'waterfall'}
            m['light_fixtures'] = {'light.roof': [fixture]}; m['effect_fixtures'] = [effect]
            self.load(m)
            result = self.post(dict(op='set', building='b', id='r', field='pitch', value=12))
            for row in [result['model']['light_fixtures']['light.roof'][0], result['model']['effect_fixtures'][0]]:
                self.assertTrue(all(row['anchors']), row)
                for point, expected in zip(row['path'], [[8,4,14], [12,4,14]]):
                    self.assertLess(math.dist(point, expected), 1e-6)
            saved = self.store.current_model()
            result = self.post(dict(op='move_roof_edge', building='b', roof='r', edge=3, by=-14), 400)
            self.assertIn('off', result['error'])
            self.assertEqual(self.store.current_model(), saved)

    def test_roof_point_chooses_fragment_containing_the_point(self):
        from uuid import uuid4
        m = house('flat', 0)
        upper = copy.deepcopy(m['buildings'][0]['roofs'][0])
        upper.update(id='upper', plate=20, area=[[10,10],[20,10],[20,20],[10,20]])
        m['buildings'][0]['roofs'].append(upper)
        path = [[9.9,10.1,10],[9.8,10.2,10]]
        m['light_fixtures'] = {'light.roof': [dict(id='fixture:'+str(uuid4()), shape='line',
             ref='absolute', path=copy.deepcopy(path), anchors=[dict(host=dict(kind='roof',id='r',building='b'),
             local=list(p)) for p in path])]}
        self.load(m)
        m = self.post(dict(op='set', building='b', id='r', field='plate', value=12))['model']
        f = m['light_fixtures']['light.roof'][0]
        self.assertTrue(all(f['anchors']))
        for p, q in zip(f['path'], [[9.9,10.1,12],[9.8,10.2,12]]):
            self.assertLess(math.dist(p,q),1e-6)

    def test_whole_roof_translation_carries_path_points_and_zones(self):
        from uuid import uuid4
        m = self.seed()
        path = [[8,4,12],[12,4,12]]
        m['light_fixtures'] = {'light.roof':[dict(id='fixture:'+str(uuid4()),shape='line',ref='absolute',
            path=copy.deepcopy(path),anchors=[dict(host=dict(kind='roof',id='r',building='b'),local=list(p)) for p in path])]}
        self.load(m)
        m = self.post(dict(op='move',building='b',piece='r',by=[20,4]))['model']
        self.assertValid(m)
        f = m['light_fixtures']['light.roof'][0]
        self.assertTrue(all(f['anchors']))
        for p,q in zip(f['path'],[[28,8,12],[32,8,12]]): self.assertLess(math.dist(p,q),1e-6)

    def test_household_and_poolhouse_seeded_roofs_survive_edits(self):
        fixtures = Path(__file__).parent/'fixtures'
        for path in (fixtures/'twin_model/household-2026-11-09.json', fixtures/'twin_poolhouse.plan.json'):
            raw = json.loads(path.read_text(encoding='utf-8'))
            from services import twin_plan
            model = bridge.assemble(twin_plan.normalize(raw)[0])[0]
            self.load(model)
            seeded = 0
            for b in model['buildings']:
                used = set()
                for face in solar.faces(b):
                    if face['roof'] in used: continue
                    p = face['polygon']
                    x0, y0 = min(q[0] for q in p), min(q[1] for q in p)
                    x1, y1 = max(q[0] for q in p), max(q[1] for q in p)
                    # Try clear panel-sized rectangles throughout exposed faces.
                    for fx, fy in ((.5,.5),(.25,.5),(.75,.5),(.5,.25),(.5,.75)):
                        x, y = x0+(x1-x0)*fx, y0+(y1-y0)*fy
                        z = dict(id='candidate', roof=face['roof'], plane=list(face['plane']), rect=[x-2,y-3,x+2,y+3])
                        if solar.error(b, z) is None:
                            self.post(dict(op='add_solar_zone', building=b['id'], **{k:v for k,v in z.items() if k!='id'}))
                            used.add(face['roof']); seeded += 1; break
            self.assertGreater(seeded, 0, path.name)
            print(f'{path.name}: {seeded} seeded roof zones', flush=True)
            m = self.store.current_model()
            for b in m['buildings']:
                for rid in dict.fromkeys(z['roof'] for z in b['solar_zones']):
                    r = next(r for r in b['roofs'] if r['id']==rid)
                    operations = [dict(op='set', id=rid, field='overhang', value=r['overhang']+.25),
                                  dict(op='set', id=rid, field='plate', value=r['plate']+.25)]
                    edge = next((i for i,e in enumerate(r['edges']) if e['setting']=='sloped'), 0)
                    if r['edges'][edge].get('pitch', 0) > 0:
                        operations.append(dict(op='set_roof_edge', roof=rid, edge=edge, setting='sloped',
                                               pitch=r['edges'][edge]['pitch']+.25))
                    operations.append(dict(op='move_roof_edge', roof=rid, edge=edge, by=.25))
                    for op in operations:
                        result = self.post(dict(building=b['id'], **op))
                        self.assertValid(result['model'])


class DockGeometry(unittest.TestCase):
    def test_concave_plane_panel_can_span_clipping_seams(self):
        face=dict(polygon=[[0,0],[10,0],[10,10],[4,10],[0,6]], polygons=[
            [[0,0],[10,0],[0,6]], [[10,0],[10,6],[0,6]], [[4,6],[10,6],[10,10],[4,10]]])
        rect=solar.fit_inside(face,[0,0,10,10],dict(panel_width=6,panel_height=6))
        self.assertIsNotNone(rect)
        self.assertGreaterEqual(rect[2]-rect[0],6-1e-6)
        self.assertGreaterEqual(rect[3]-rect[1],6-1e-6)
        self.assertLessEqual(rect[3],6+1e-6)

    def test_diagonal_fit_accepts_exactly_one_panel(self):
        face = dict(polygon=[[0,0],[10,0],[0,10]])
        rect = solar.fit_inside(face, [0,0,10,10], dict(panel_width=5,panel_height=5))
        self.assertIsNotNone(rect)
        for actual, expected in zip(rect, [0,0,5,5]): self.assertAlmostEqual(actual, expected)

    def test_fallback_uses_ten_degrees_and_largest_projected_overlap(self):
        old = dict(roof='r', plane=[0,0,10], identity=['old','flat'], polygon=solar.rectangle([0,0,20,20]))
        z = dict(roof='r', plane=[0,0,10], rect=[2,2,12,12])
        near = {**old, 'identity':['new','flat'], 'plane':[0,math.tan(math.radians(9)),10]}
        small = {**near, 'polygon':solar.rectangle([0,0,3,3])}
        far = {**near, 'plane':[0,math.tan(math.radians(11)),10]}
        self.assertEqual(solar.matching_face(old,z,[small,near,far]),near)
        self.assertIsNone(solar.matching_face(old,z,[far]))

    def test_nonparallel_midpoint_docking_is_solved_together(self):
        # The two diagonal boundaries are sampled at each zone edge's midpoint.
        face = dict(polygon=[[0,0],[30,0],[20,20],[10,20]])
        offsets = solar.dock_offsets(face, [11,3,19,13])
        self.assertEqual([o['distance'] for o in offsets], [7,3,7,7])
        changed = dict(polygon=[[0,0],[36,0],[26,24],[10,24]])
        rect = solar.refit(changed, offsets)
        for a, b in zip(rect, [67/6,3,149/6,17]): self.assertAlmostEqual(a, b)
        after = solar.dock_offsets(changed, rect)
        for a, b in zip(offsets, after): self.assertAlmostEqual(a['distance'], b['distance'])


if __name__ == '__main__': unittest.main(verbosity=2)

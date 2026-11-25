"""Task 5: supported roofs use the ordinary atomic operation/save path."""
import copy
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_twin_awning_model import house, ops, model, bridge, store, storage, roofs
from services.twin_model_supports import support_points, frame_point


class AwningOps(unittest.TestCase):
    def apply(self, value, kind, **fields):
        return ops.apply(value, dict(op=kind, building='b', id='shade', **fields))[0]

    def test_set_support_changes_only_named_fields(self):
        before = house(); original = before['buildings'][0]['roofs'][0]
        value = self.apply(before, 'set_roof_support', support={'count': 0})
        r = value['buildings'][0]['roofs'][0]
        expected = copy.deepcopy(original); expected['support']['count'] = 0
        expected['support'].pop('at', None)
        self.assertEqual({k:v for k,v in r.items() if k != 'src'}, {k:v for k,v in expected.items() if k != 'src'})
        self.assertEqual(before['buildings'][0]['roofs'][0], original)
        value = self.apply(value, 'set_roof_support', support={'kind':'walls'})
        self.assertNotIn('support', value['buildings'][0]['roofs'][0])

    def test_move_roof_moves_area_frame_supports_gutter_and_panels(self):
        before = house(); b = before['buildings'][0]; r = b['roofs'][0]
        r['roof_frame'] = dict(origin=[0,0], angle=.005)
        r['edges'][2].update(gutter=True, downspouts=[.25,.75])
        face = __import__('services.twin_solar', fromlist=['docking_faces']).docking_faces(b)[0]
        # A small, valid panel zone on the exposed plane.
        from services import twin_solar
        zone = dict(id='panels', roof='shade', plane=face['plane'], rect=[2,1,5,3],
                    **copy.deepcopy(twin_solar.DEFAULTS))
        zone.update(panel_width=1, panel_height=1, setback=0, gap=0)
        b['solar_zones'] = [zone]
        before, _ = model.normalize(before)
        old = copy.deepcopy(before['buildings'][0]); value = self.apply(before,'move_roof',by=[3,2]); new=value['buildings'][0]
        a, z = old['roofs'][0], new['roofs'][0]
        self.assertEqual(z['area'], [[x+3,y+2] for x,y in a['area']])
        self.assertEqual(z['roof_frame']['origin'], [3,2])
        self.assertEqual(z['support']['at']['1'], [12,12])
        self.assertEqual(z['edges'][2], a['edges'][2])
        for p,q in zip(support_points(a),support_points(z)):
            for i,d in enumerate([3,2]): self.assertAlmostEqual(q['at'][i],p['at'][i]+d)
        self.assertTrue(new['solar_zones'])
        for building in (old, new): self.assertNotEqual(building['solar_zones'][0].get('state'), 'ghost')
        old_zone, new_zone = old['solar_zones'][0], new['solar_zones'][0]
        centre = lambda z: twin_solar.point(z['plane'], [(z['rect'][i]+z['rect'][i+2])/2 for i in (0,1)])
        for i, amount in enumerate([3,2,0]): self.assertAlmostEqual(centre(new_zone)[i], centre(old_zone)[i]+amount)
        # An unrelated edit must not snap it back to the wall.
        again=self.apply(value,'set_roof_support',fascia=True)
        self.assertEqual(again['buildings'][0]['roofs'][0]['area'],z['area'])
        self.assertEqual(twin_solar.error(new,new['solar_zones'][0],[]),None)

    def test_count_bounds_and_validation_are_shared(self):
        for count in [0,40]:
            person=self.apply(house(),'set_roof_support',support={'count':count})
            agent=ops.apply(house(),dict(op='set_roof_support',building='b',id='shade',support={'count':count}),actor='agent')[0]
            self.assertEqual(person['buildings'][0]['roofs'][0]['support'],agent['buildings'][0]['roofs'][0]['support'])
            self.assertEqual(person['buildings'][0]['roofs'][0]['support']['count'],count)
        for fields in [dict(support={'kind': 'posts'}), dict(support={'kind': []}), dict(support=None),
                       *[dict(support={'count': n}) for n in [41,-1,True,2.5,'3',None,float('inf'),float('nan')]],
                       dict(support={'size_ft': 3.5}), dict(support={'inset_ft': -1}),
                       dict(thickness_ft=0), dict(at={'0':[float('nan'),0]})]:
            for actor in ['person','agent']:
                before=house(); unchanged=copy.deepcopy(before)
                with self.assertRaises(ops.Refused):
                    ops.apply(before,dict(op='set_roof_support',building='b',id='shade',**fields),actor=actor)
                self.assertEqual(before,unchanged)
                if 'at' not in fields:
                    with self.assertRaises(ops.Refused):
                        ops.apply(before,dict(op='draw_roof',building='b',area=[[30,0],[40,0],[40,4],[30,4]],**fields),actor=actor)
        for by in [[1], [True,2], [float('nan'),0], '1,2']:
            with self.assertRaises(ops.Refused): self.apply(house(),'move_roof',by=by)

    def test_draw_edge_delete_and_agent_documentation(self):
        value=self.apply(house(),'draw_roof',area=[[30,0],[40,0],[40,6],[30,6]],support={'kind':'post','count':2},fascia=False)
        self.assertEqual(value['buildings'][0]['roofs'][-1]['support']['kind'],'post')
        value=self.apply(value,'set_roof_edge',roof='shade',edge=2,setting='sloped',pitch=3)
        value=self.apply(value,'move_roof_edge',roof='shade',edge=2,by=1)
        value=self.apply(value,'move_roof_edge',roof='shade',edge=0,by=.2,detach=True)
        self.assertNotIn('host',next(r for r in value['buildings'][0]['roofs'] if r['id']=='shade'))
        keep=copy.deepcopy(value['buildings'][0]['roofs'][-1]); value=self.apply(value,'delete')
        self.assertEqual(value['buildings'][0]['roofs'],[keep])
        source=(Path(__file__).resolve().parents[1]/'services/agent_tools_v2.py').read_text(encoding='utf-8')
        for name in ['set_roof_support','move_roof']:
            self.assertIn(name,ops.MORE_OPS); self.assertIn(name,source)

    def test_one_undo_restores_support_edit_and_move(self):
        for operation in [dict(op='set_roof_support',support={'kind':'post'},thickness_ft=.6),dict(op='move_roof',by=[2,1]),dict(op='set_roof_support',support={'kind':'walls'})]:
            settings={}
            with tempfile.TemporaryDirectory(prefix='awning_ops_') as directory, patch.object(store,'DATA_DIR',directory), patch.object(storage,'get_settings',side_effect=lambda:copy.deepcopy(settings)), patch.object(storage,'patch_settings',side_effect=lambda v:settings.update(copy.deepcopy(v))):
                from services import twin_edit
                store._invalidate_reads(); initial=house();initial['buildings'][0]['roofs'][0]['roof_frame']=dict(origin=[0,0],angle=.005)
                first=store._append_round(store._state(),initial,'load')
                twin_edit.save(dict(building='b',id='shade',**operation),'test')
                self.assertEqual(len(store._state()['rounds']),2)
                for actor in ['person','agent']:
                    with self.assertRaises(ops.Refused):
                        store.update_model(lambda value: ops.apply(value,dict(op='set_roof_support',building='b',id='shade',support={'kind':'posts'}),actor=actor)[0])
                    self.assertEqual(len(store._state()['rounds']),2,'refused edit saves no step')
                store.revert(first); store._invalidate_reads()
                self.assertEqual(store.current_model()['buildings'][0]['roofs'][0],initial['buildings'][0]['roofs'][0])

    def test_near_axis_angle_follows_then_detaches_in_place(self):
        value=house(); r=value['buildings'][0]['roofs'][0]
        value,_=ops.apply(value,dict(op='move_joint',building='b',joint='j1',to=[20,.1]))
        r=value['buildings'][0]['roofs'][0]; self.assertAlmostEqual(r['roof_frame']['angle'],math.atan2(.1,20))
        area=copy.deepcopy(r['area']); frame=copy.deepcopy(r['roof_frame'])
        value,_=ops.apply(value,dict(op='move_joint',building='b',joint='j1',to=[20,1]))
        r=value['buildings'][0]['roofs'][0]; self.assertEqual(r['area'],area); self.assertEqual(r['roof_frame'],frame); self.assertNotIn('host',r)
        self.assertTrue(value['buildings'][0]['flags'])

    def test_every_edge_keeps_other_end_and_authored_points_after_later_edit_and_reload(self):
        for side in range(4):
            for reverse in [False,True]:
                for framed in [False,True]:
                    for edge in range(4):
                        with self.subTest(side=side,reverse=reverse,framed=framed,edge=edge):
                            value=house(); b=value['buildings'][0]; r=b['roofs'][0]
                            if reverse:
                                b['walls'][side]['joints'].reverse()
                            r['host']={'wall':f'w{side}','edge':side}
                            for e in r['edges']:
                                for k in ['wall','wall_offset','wall_along_offset']:e.pop(k,None)
                            if framed:r['roof_frame']=dict(origin=[10,5],angle=.005)
                            value=model.normalize(value)[0]; r=value['buildings'][0]['roofs'][0]
                            old=copy.deepcopy(r); expected=copy.deepcopy(r['area'])
                            a,z=expected[edge],expected[(edge+1)%4]; dx,dy=z[0]-a[0],z[1]-a[1]; length=math.hypot(dx,dy)
                            delta=[dy/length*2,-dx/length*2]
                            for p in (a,z):p[:]=[p[i]+delta[i] for i in (0,1)]
                            settings={}
                            from services import twin_edit
                            with tempfile.TemporaryDirectory(prefix='awning_edge_') as directory, patch.object(store,'DATA_DIR',directory), patch.object(storage,'get_settings',side_effect=lambda:copy.deepcopy(settings)), patch.object(storage,'patch_settings',side_effect=lambda v:settings.update(copy.deepcopy(v))):
                                store._invalidate_reads();store._append_round(store._state(),value,'load')
                                twin_edit.save(dict(op='move_roof_edge',building='b',roof='shade',edge=edge,by=2),'test')
                                twin_edit.save(dict(op='set_roof_support',building='b',id='shade',fascia=True),'test')
                                moved=store.current_model();store._invalidate_reads();reloaded=store.current_model()
                            for candidate in [moved,reloaded]:
                                actual=candidate['buildings'][0]['roofs'][0]
                                self.assertEqual(actual['area'],expected)
                                self.assertEqual(actual['support']['at'],old['support']['at'])
                                for p,q in zip(actual['area'],expected):
                                    for x,y in zip(frame_point(actual,p),frame_point(old,q)):self.assertAlmostEqual(x,y)

    def test_count_reduction_keeps_points_and_point_patches_merge(self):
        value=house(); old=support_points(value['buildings'][0]['roofs'][0])
        value=self.apply(value,'set_roof_support',support={'count':2})
        self.assertEqual([p['at'] for p in support_points(value['buildings'][0]['roofs'][0])],[p['at'] for p in old[:2]])
        value=self.apply(value,'set_roof_support',at={'0':[1.123,2.456]})
        value=self.apply(value,'set_roof_support',at={'1':[5.789,6.123]})
        self.assertEqual(value['buildings'][0]['roofs'][0]['support']['at'],{'0':[1.123,2.456],'1':[5.789,6.123]})

    def test_default_sizes_and_draw_auto_host_and_resolved_flags(self):
        value=self.apply(house(),'set_roof_support',support={'kind':'cable'})
        self.assertEqual(value['buildings'][0]['roofs'][0]['support']['size_ft'],.08)
        value=self.apply(value,'set_roof_support',support={'size_ft':.42})
        value=self.apply(value,'set_roof_support',support={'kind':'post'})
        self.assertEqual(value['buildings'][0]['roofs'][0]['support']['size_ft'],.42)
        value=self.apply(house(),'draw_roof',area=[[3,-4],[17,-4],[17,0],[3,0]],support={'kind':'bracket'})
        self.assertEqual(value['buildings'][0]['roofs'][-1]['host'],dict(wall='w0',edge=2))
        value=house();value['buildings'][0]['flags']=[dict(id='shade',kind='roof',text='Awning has lost its supporting wall.',at=[0,0],level='L1')]
        value=self.apply(value,'set_roof_support',host=dict(wall='w0',edge=0))
        self.assertFalse(value['buildings'][0]['flags'])

    def test_walls_restores_wall_following_and_refused_host_keeps_old(self):
        value=house(False); r=value['buildings'][0]['roofs'][0]
        r.update(roofs.attach_edges(r,value['buildings'][0]['walls'],value['buildings'][0]['joints']))
        with self.assertRaises(ops.Refused):self.apply(value,'set_roof_support',host=None)
        value=self.apply(value,'set_roof_support',support={'kind':'bracket'})
        value=self.apply(value,'set_roof_support',host={'wall':'w0','edge':0},thickness_ft=.6,fascia=False)
        old=copy.deepcopy(value)
        for host in [dict(wall='w0',edge=1),dict(wall='missing',edge=0),dict(wall='w0',edge=True)]:
            with self.assertRaises(ops.Refused):self.apply(value,'set_roof_support',host=host)
            self.assertEqual(value,old)
        value=self.apply(value,'set_roof_support',support={'kind':'walls'})
        r=value['buildings'][0]['roofs'][0]
        for key in ['support','host','thickness_ft','fascia']:self.assertNotIn(key,r)
        self.assertTrue(all('wall_along_offset' not in e for e in r['edges']))
        self.assertEqual(sum('wall' in e for e in r['edges']),4)
        value=ops.apply(value,dict(op='move_wall',building='b',wall='w2',by=[0,2]))[0]
        self.assertEqual(max(p[1] for p in value['buildings'][0]['roofs'][0]['area']),12)

    def test_migrated_skewed_roof_turns_with_wall_and_stays_after_edit(self):
        from test_twin_awning_migration import legacy
        from services.twin_model_supports import frame_point
        raw=legacy(True); b=raw['buildings'][0]
        # Rotate the whole wall fixture a half degree, preserving its joints.
        angle=math.radians(.5); c,s=math.cos(angle),math.sin(angle)
        for j in b['joints']:
            x,y=j['at'];j['at']=[c*x-s*y,s*x+c*y]
        value,_=model.normalize(raw); b=value['buildings'][0]; roof=next(r for r in b['roofs'] if r['id']=='shade')
        oldpoint=frame_point(roof,roof['area'][0]); wall=next(w for w in b['walls'] if w['id']==roof['host']['wall'])
        start=next(j['at'] for j in b['joints'] if j['id']==wall['joints'][0]);end=next(j['at'] for j in b['joints'] if j['id']==wall['joints'][1])
        turn=math.radians(.25); c,s=math.cos(turn),math.sin(turn);x,y=[end[i]-start[i] for i in (0,1)]
        value,_=ops.apply(value,dict(op='move_joint',building=b['id'],joint=wall['joints'][1],to=[start[0]+c*x-s*y,start[1]+s*x+c*y]))
        roof=next(r for r in value['buildings'][0]['roofs'] if r['id']=='shade');newpoint=frame_point(roof,roof['area'][0]);x,y=[oldpoint[i]-start[i] for i in (0,1)]
        expected=[start[0]+c*x-s*y,start[1]+s*x+c*y]
        for a,b in zip(newpoint,expected):self.assertAlmostEqual(a,b,places=5)
        stable,_=ops.apply(value,dict(op='set_roof_support',building=value['buildings'][0]['id'],id='shade',fascia=True))
        again=next(r for r in stable['buildings'][0]['roofs'] if r['id']=='shade')
        self.assertEqual(again['area'],roof['area']);self.assertEqual(again['roof_frame'],roof['roof_frame'])

    def test_bad_shed_is_a_located_deletable_ghost(self):
        from test_twin_awning_migration import legacy
        raw=legacy(True); b=raw['buildings'][0]
        b['extensions']=[dict(id='bad-shed',kind='shed_continuation',section='main',to_x=0,pitch=3)]
        value,_=model.normalize(raw); ghost=next(r for r in value['buildings'][0]['roofs'] if r['id']=='bad-shed')
        self.assertEqual(ghost['state'],'ghost'); self.assertEqual(len(ghost['position']),2)
        self.assertIn('why',ghost);self.assertTrue(value['buildings'][0]['flags'])
        value,_=ops.apply(value,dict(op='delete',building=b['id'],id='bad-shed'))
        self.assertFalse(any(r['id']=='bad-shed' for r in value['buildings'][0]['roofs']))


if __name__=='__main__': unittest.main()

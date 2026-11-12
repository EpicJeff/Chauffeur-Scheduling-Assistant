"""Model operations and persistence for solar zones and plain wall equipment."""
import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_equipment_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import twin_model, twin_model_ops as ops, twin_model_bridge as bridge, twin_solar, twin_energy


def house():
    b = dict(id='b', position=[7, 12], rotation=30, base=2,
             levels=[dict(id='L1', elevation=0, ceiling=10)],
             joints=[dict(id='j'+str(i), level='L1', at=p) for i, p in enumerate([[0,0],[40,0],[40,30],[0,30]])],
             walls=[dict(id='w'+str(i), level='L1', joints=['j'+str(i),'j'+str((i+1)%4)],
                         kind='solid', exterior=True, height=10, thickness=.5) for i in range(4)], rooms=[],
             roofs=[dict(id='r', area=[[0,0],[40,0],[40,30],[0,30]], edges=[dict(setting='sloped',pitch=0) for _ in range(4)],
                         kind='flat', pitch=0, plate=10, overhang=0, level='L1')])
    return twin_model.normalize(dict(units='ft',buildings=[b],site={}))[0]


def edit(model, op, **kw):
    return ops.apply(model, dict(op=op, building='b', **kw))[0]


def zone(model, rect=None, **kw):
    return edit(model, 'add_solar_zone', roof='r', plane=[0,0,10], rect=rect or [0,0,20,10], **kw)


class EquipmentTests(unittest.TestCase):
    def test_zone_lifecycle_and_input_immutable(self):
        original=house(); saved=copy.deepcopy(original)
        m=zone(original); z=m['buildings'][0]['solar_zones'][0]
        self.assertEqual(original,saved)
        self.assertTrue(z['src']['person'])
        m=edit(m,'update_solar_zone',id=z['id'],rect=[1,1,21,11])
        m=edit(m,'update_solar_zone',id=z['id'],rect=[1,1,30,20],count=7,entity='sensor.zone')
        self.assertEqual(len(twin_solar.layout(m['buildings'][0]['solar_zones'][0])),7)
        m=edit(m,'delete',id=z['id'])
        self.assertEqual(m['buildings'][0]['solar_zones'],[])

    def test_exact_count_orientation_spacing_and_partial_row_centred(self):
        # Portrait = 39 in across, 65 in up: floor(241/40)*floor(121/66)=6.
        z=zone(house())['buildings'][0]['solar_zones'][0]
        self.assertEqual(len(twin_solar.layout(z)),6)
        self.assertEqual(len(twin_solar.layout({**z,'orientation':'landscape'})),9)
        self.assertEqual(len(twin_solar.layout({**z,'setback':1})),5)
        panels=twin_solar.layout({**z,'count':4})
        self.assertAlmostEqual((panels[0][0]+panels[-1][2])/2,10)
        self.assertEqual(twin_solar.layout({**z,'count':0}),[])

    def test_outside_overlap_and_move_resize_refusals_are_atomic(self):
        m=zone(house()); saved=copy.deepcopy(m); zid=m['buildings'][0]['solar_zones'][0]['id']
        for operation in [dict(op='add_solar_zone',roof='r',plane=[0,0,10],rect=[39,0,42,8]),
                          dict(op='add_solar_zone',roof='r',plane=[0,0,10],rect=[10,0,30,8]),
                          dict(op='update_solar_zone',id=zid,rect=[0,0,41,10])]:
            with self.assertRaisesRegex(ops.Refused,'roof|already'):
                ops.apply(m,dict(building='b',**operation))
            self.assertEqual(m,saved)
        m=zone(m,rect=[20,0,40,10]) # touching edges allowed
        zid=m['buildings'][0]['solar_zones'][1]['id']
        with self.assertRaisesRegex(ops.Refused,'already'):
            edit(m,'update_solar_zone',id=zid,rect=[19,0,39,10])

    def test_roof_edits_cannot_silently_strand_a_zone(self):
        m=zone(house()); saved=copy.deepcopy(m)
        for operation in [dict(op='set',id='r',field='plate',value=12),dict(op='delete',id='r')]:
            with self.assertRaisesRegex(ops.Refused,'solar zone'):
                ops.apply(m,dict(building='b',**operation))
            self.assertEqual(m,saved)
        from services import twin_edit
        with self.assertRaisesRegex(ops.Refused,'solar zone'):
            twin_edit.apply_model(m,dict(op='set',building='b',piece='r',field='plate',value=12))
        self.assertEqual(m,saved)

    def test_roof_union_occlusion_and_sloped_plane(self):
        m=house(); b=m['buildings'][0]
        b['roofs'].append({**copy.deepcopy(b['roofs'][0]),'id':'upper','plate':20,
                           'area':[[9,0],[11,0],[11,30],[9,30]]})
        with self.assertRaisesRegex(ops.Refused,'roof'):
            zone(m) # four corners fit but a higher roof cuts the middle
        b['roofs']=b['roofs'][:1];r=b['roofs'][0];r.update(kind='shed',pitch=6,low_side='y0')
        r['edges']=[dict(setting='sloped' if i==0 else 'gable',pitch=6) for i in range(4)]
        m=edit(m,'add_solar_zone',roof='r',plane=[0,.5,10],rect=[1,1,21,11])
        self.assertEqual(len(m['buildings'][0]['solar_zones']),1)

    def test_source_roundtrip_reread_and_validation(self):
        m=edit(zone(house()),'set_solar_source',roof='r')
        self.assertEqual(twin_model.normalize(m)[0]['solar_source_roof'],'r')
        flat=bridge.flatten(m); reread=bridge.flatten(house())
        preserved=bridge.assemble(reread,m)[0]
        self.assertEqual(preserved['solar_source_roof'],'r')
        self.assertEqual(preserved['buildings'][0]['solar_zones'],m['buildings'][0]['solar_zones'])
        self.assertEqual(flat['solar_source_roof'],'r')
        with self.assertRaisesRegex(ops.Refused,'roof'):
            edit(m,'set_solar_source',roof='missing')

    def test_same_roof_id_in_different_buildings_is_scoped(self):
        m=zone(house()); b=copy.deepcopy(m['buildings'][0]);b['id']='other';m['buildings'].append(b)
        m=edit(m,'set_solar_source',roof='r')
        self.assertEqual(m['solar_source_building'],'b')
        self.assertEqual(twin_model.normalize(m)[0]['solar_source_building'],'b')
        with self.assertRaisesRegex(ops.Refused,'building'):
            ops.apply(m,dict(op='set_solar_source',roof='r'))

    def test_equipment_lifecycle_and_wall_only(self):
        m=house()
        for kind in ('meter','electric_panel','charger'):
            m=edit(m,'add_equipment',kind=kind,host=dict(wall='w0',side='right',at=5,z=4))
            p=m['buildings'][0]['anchors'][-1]
            m=edit(m,'move_hosted',id=p['id'],host=dict(wall='w1',side='left',at=8,z=5))
            self.assertEqual(m['buildings'][0]['anchors'][-1]['host']['wall'],'w1')
            m=edit(m,'delete',id=p['id'])
            self.assertEqual(m['buildings'][0]['anchors'],[])
        with self.assertRaisesRegex(ops.Refused,'meter'):
            edit(m,'add_equipment',kind='unknown',host=dict(wall='w0',side='left',at=4,z=3))
        for kind in ('meter','electric_panel','charger'):
            for host in (dict(floor='room',u=.5,v=.5),dict(ground=True,at=[8,9])):
                with self.subTest(kind=kind,host=host),self.assertRaisesRegex(ops.Refused,'wall'):
                    edit(m,'add_equipment',kind=kind,host=host)

    def test_parking_floor_and_ground_defaults_rehost_and_metadata_roundtrip(self):
        m=house(); room=m['buildings'][0]['rooms'][0]['id']
        floor=dict(floor=room,u=.3,v=.4); ground=dict(ground=True,at=[45,10])
        for host in (floor,ground):
            m=edit(m,'add_equipment',kind='parking',host=host,car='family')
            p=m['buildings'][0]['anchors'][-1]
            self.assertEqual((p['width'],p['depth'],p['rotation'],p['car']),(9,18,0,'family'))
            self.assertEqual(p['host'],host)
            self.assertEqual(p['state'],'settled')
            self.assertTrue(p['src']['person'])
        floor_id,ground_id=[p['id'] for p in m['buildings'][0]['anchors']]
        m=edit(m,'move_hosted',id=floor_id,host=ground)
        m=edit(m,'move_hosted',id=ground_id,host=floor)
        for field,value in (('name','Garage bay'),('width',10),('depth',20),('rotation',45),('car','second')):
            m=edit(m,'set',id=ground_id,field=field,value=value)
        m=edit(m,'add_equipment',kind='charger',host=dict(wall='w0',side='right',at=5,z=4),
               name='Wallbox',power='sensor.wallbox_power',car='second')
        expected=copy.deepcopy(m['buildings'][0]['anchors'])
        normalized,notes=twin_model.normalize(m)
        self.assertEqual(normalized['buildings'][0]['anchors'],expected)
        self.assertFalse(any('invalid anchor' in str(note).lower() for note in notes))
        flat=bridge.flatten(m)
        self.assertEqual(flat['buildings'][0]['anchors'],expected)
        assembled=bridge.assemble(flat,m)[0]
        self.assertEqual(assembled['buildings'][0]['anchors'],expected)
        reread=bridge.assemble(bridge.flatten(house()),m)[0]
        self.assertEqual(reread['buildings'][0]['anchors'],expected)

    def test_equipment_property_and_host_refusals_are_atomic(self):
        m=house(); room=m['buildings'][0]['rooms'][0]['id']
        m=edit(m,'add_equipment',kind='charger',host=dict(wall='w0',side='right',at=5,z=4))
        charger=m['buildings'][0]['anchors'][0]['id']
        m=edit(m,'add_equipment',kind='parking',host=dict(floor=room,u=.5,v=.5))
        parking=m['buildings'][0]['anchors'][1]['id']
        for piece,field,value in ((charger,'name','Main charger'),(charger,'power','sensor.wallbox'),
                                  (charger,'car','first'),(parking,'name','Bay'),(parking,'car','second')):
            m=edit(m,'set',id=piece,field=field,value=value)
        for piece in (charger,parking):
            m=edit(m,'set',id=piece,field='car',value=None)
        m=edit(m,'set',id=charger,field='power',value=None)
        self.assertIsNone(m['buildings'][0]['anchors'][0]['power'])
        self.assertTrue(all(p['car'] is None for p in m['buildings'][0]['anchors']))
        bad=[dict(op='set',id=charger,field=field,value=value) for field,value in
             (('power','bad'),('power',7000),('name',''),('name','x'*101),('car',5),('car',''))]
        bad += [dict(op='set',id=parking,field=field,value=value) for field,value in
                (('width',0),('width',101),('width',True),('depth',-1),('depth','18'),
                 ('rotation',float('inf')),('rotation',float('nan')),('car',{}))]
        bad += [dict(op='move_hosted',id=charger,host=dict(floor=room,u=.5,v=.5)),
                dict(op='move_hosted',id=parking,host=dict(wall='w0',side='left',at=4,z=0)),
                dict(op='add_equipment',kind='parking',host=dict(ceiling=room,u=.5,v=.5)),
                dict(op='add_equipment',kind='parking',host=dict(ground=True,at=['bad',0])),
                dict(op='add_equipment',kind='parking',host=dict(floor='missing',u=.5,v=.5)),
                dict(op='add_equipment',kind='parking',host=dict(floor=room,u=2,v=.5)),
                dict(op='add_equipment',kind='parking',host='bad'),
                dict(op='add_equipment',kind='parking',host=['bad']),
                dict(op='add_equipment',kind='charger',host=dict(wall='missing',side='left',at=4,z=3))]
        saved=copy.deepcopy(m)
        for operation in bad:
            with self.subTest(operation=operation),self.assertRaises(ops.Refused):
                ops.apply(m,dict(building='b',**operation))
            self.assertEqual(m,saved)
        for piece in (charger,parking):
            m=edit(m,'delete',id=piece)
        self.assertEqual(m['buildings'][0]['anchors'],[])

    def test_editor_route_and_history_keep_equipment_and_source(self):
        from services import storage, twin_store
        from fastapi.testclient import TestClient
        import main
        storage.add_member(dict(id='equipment-parent',name='Parent',role='parent'))
        headers={'X-Member-Token':storage.create_member_token('equipment-parent')}
        twin_store.push_round(bridge.flatten(house()),'build')
        client=TestClient(main.app)
        def post(operation):
            result=client.post('/api/house/editor/op',headers=headers,json={'op':dict(building='b',**operation)})
            self.assertEqual(result.status_code,200,result.text)
            return result.json()
        before=twin_store.current_id()
        result=post(dict(op='add_solar_zone',roof='r',plane=[0,0,10],rect=[0,0,20,10]))
        zone_round=result['round']
        self.assertEqual(len(result['model']['buildings'][0]['solar_zones']),1)
        post(dict(op='set_solar_source',roof='r'))
        for kind in ('meter','electric_panel','charger'):
            post(dict(op='add_equipment',kind=kind,host=dict(wall='w0',side='right',at=5,z=4)))
        room=twin_store.current_model()['buildings'][0]['rooms'][0]['id']
        result=post(dict(op='add_equipment',kind='parking',host=dict(floor=room,u=.4,v=.5),car='family'))
        parking=result['model']['buildings'][0]['anchors'][-1]['id']
        post(dict(op='set',id=parking,field='rotation',value=90))
        post(dict(op='add_equipment',kind='parking',host=dict(ground=True,at=[45,10]),car='second'))
        equipped=twin_store.current_id()
        twin_store.revert(before)
        self.assertEqual(twin_store.current_model()['buildings'][0]['solar_zones'],[])
        twin_store.revert(equipped)
        m=twin_store.current_model()
        self.assertEqual(m['solar_source_roof'],'r')
        anchors=m['buildings'][0]['anchors']
        self.assertEqual([p['kind'] for p in anchors],['meter','electric_panel','charger','parking','parking'])
        self.assertEqual((anchors[3]['width'],anchors[3]['depth'],anchors[3]['rotation'],anchors[3]['car']),(9,18,90,'family'))
        self.assertEqual(anchors[4]['host'],dict(ground=True,at=[45,10]))
        self.assertEqual(anchors[4]['car'],'second')
        response=client.post('/api/house/editor/op',headers=headers,json={'op':dict(op='add_solar_zone',building='b',roof='r',plane=[0,0,10],rect=[1,1,20,9])})
        self.assertEqual(response.status_code,400)
        self.assertIn('already',response.json()['error'])
        before_bad=twin_store.current_id(); saved=copy.deepcopy(twin_store.current_model())
        for host in ('bad',['bad']):
            with self.subTest(host=host):
                response=client.post('/api/house/editor/op',headers=headers,
                                     json={'op':dict(op='add_equipment',building='b',kind='parking',host=host)})
                self.assertEqual(response.status_code,400,response.text)
                self.assertIn('floor or the ground',response.json()['error'])
                self.assertEqual(twin_store.current_id(),before_bad)
                self.assertEqual(twin_store.current_model(),saved)

    def test_location_mapping_validation_preserves_none_and_device_only_roles(self):
        mapping=dict(locations=dict(battery=dict(type='device',id='powerwall'),grid=dict(type='object',id='anchor:1',building='b'),house=None),
                     cars=[dict(id='c',name='Car',anchor=dict(type='device',id='charger'))])
        result=twin_energy.validate(mapping)
        self.assertEqual(result['locations'],mapping['locations'])
        self.assertEqual(result['chargers'],[dict(id='charger-c',name='Car charger',power=None,
                         anchor=mapping['cars'][0]['anchor'],car='c')])
        self.assertIsNone(result['cars'][0]['anchor'])
        self.assertIsNone(result['cars'][0]['charge_power'])
        for bad in [dict(locations=dict(battery=dict(type='object',id='x',building='b'))),
                    dict(cars=[dict(id='c',name='Car',anchor=dict(type='object',id='x'))]),dict(locations=[]),dict(locations=dict(grid=dict(type='guess',id='x')))]:
            with self.assertRaises(ValueError):twin_energy.validate(bad)


if __name__=='__main__':unittest.main(verbosity=2)

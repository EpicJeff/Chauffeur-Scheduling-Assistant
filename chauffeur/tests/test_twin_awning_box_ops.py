"""Task 7b: box choices travel through the real operation and persistence paths."""
import copy
import json
import math
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_twin_awning_model import house, model, bridge, ops, store, storage, roofs
from services import twin_edit
from services.twin_model_supports import carry_fields, normalize_support


class BoxOps(unittest.TestCase):
    def edit(self, value, **fields):
        return ops.apply(value, dict(op='set_roof_support', building='b', id='shade', **fields))[0]

    def test_patch_flat_round_trip_and_open(self):
        value = self.edit(house(), ends={'1':'closed','3':'closed'}, underside={'kind':'flat'})
        roof = value['buildings'][0]['roofs'][0]
        self.assertEqual(roof['underside'], {'kind':'flat','drop_ft':0})
        for actual in [model.normalize(value)[0], bridge.assemble(bridge.flatten(value), value)[0], json.loads(json.dumps(value))]:
            r = actual['buildings'][0]['roofs'][0]
            self.assertEqual(r['ends'], {'1':'closed','3':'closed'})
            self.assertEqual(r['underside'], roof['underside'])
        value = self.edit(value, ends={'1':'open'}, underside={'kind':'exposed'})
        self.assertEqual(value['buildings'][0]['roofs'][0]['ends'], {'3':'closed'})
        self.assertNotIn('underside', value['buildings'][0]['roofs'][0])
        value=self.edit(value,ends={'1':'closed'})
        value=ops.apply(value,dict(op='set_roof_edge',building='b',roof='shade',edge=1,setting='sloped',pitch=3))[0]
        self.assertEqual(value['buildings'][0]['roofs'][0]['ends'],{'3':'closed'})

    def test_invalid_refuses_without_step_and_one_undo(self):
        settings = {}
        with tempfile.TemporaryDirectory(prefix='box_ops_') as directory, patch.object(store,'DATA_DIR',directory), patch.object(storage,'get_settings',side_effect=lambda:copy.deepcopy(settings)), patch.object(storage,'patch_settings',side_effect=lambda v:settings.update(copy.deepcopy(v))):
            store._invalidate_reads(); initial=house(); first=store._append_round(store._state(),initial,'load')
            for fields in [dict(ends={'0':'closed'}),dict(ends={'2':'closed'}),dict(ends={'9':'closed'}),dict(ends={'1':'shut'}),dict(ends=[]),dict(underside={'kind':'rafters'}), *[dict(underside={'kind':'flat','drop_ft':n}) for n in [-1,4,True,'1',float('nan')]], dict(support={'kind':'cable','style':'arched'})]:
                for actor in ['person','agent']:
                    with self.assertRaises(ops.Refused):
                        store.update_model(lambda value:ops.apply(value,dict(op='set_roof_support',building='b',id='shade',**fields),actor=actor)[0])
                    self.assertEqual(len(store._state()['rounds']),1)
            twin_edit.save(dict(op='set_roof_support',building='b',id='shade',ends={'1':'closed'},underside={'kind':'flat','drop_ft':3}),'test')
            self.assertEqual(len(store._state()['rounds']),2)
            store._invalidate_reads();self.assertEqual(store.current_model()['buildings'][0]['roofs'][0]['ends'],{'1':'closed'})
            from services import twin_house_saves
            exported=twin_house_saves.download()
            imported=twin_house_saves._normalize(json.loads(json.dumps(exported)))[0]
            self.assertEqual(imported['buildings'][0]['roofs'][0]['ends'],{'1':'closed'})
            self.assertEqual(imported['buildings'][0]['roofs'][0]['underside'],{'kind':'flat','drop_ft':3})
            store.revert(first);store._invalidate_reads();self.assertEqual(store.current_model()['buildings'][0]['roofs'][0],initial['buildings'][0]['roofs'][0])

    def test_walls_round_trip_preserves_detached_choices(self):
        for detached in [[],[2],[1,2,3]]:
            value=house(False);r=value['buildings'][0]['roofs'][0];r.update(roofs.attach_edges(r,value['buildings'][0]['walls'],value['buildings'][0]['joints']))
            for i in detached:
                value=ops.apply(value,dict(op='move_roof_edge',building='b',roof='shade',edge=i,by=1,detach=True))[0]
            before=copy.deepcopy(value)
            self.assertEqual(self.edit(value,support={'kind':'walls'}),value)
            value=self.edit(value,support={'kind':'bracket'})
            from services import twin_plan
            value=bridge.assemble(twin_plan.normalize(bridge.flatten(value))[0])[0]
            value=self.edit(value,ends={'1':'closed'} if 1 not in detached else {},underside={'kind':'flat'})
            value=self.edit(value,support={'kind':'walls'})
            r=value['buildings'][0]['roofs'][0]
            self.assertEqual([e.get('wall') for e in r['edges']],[e.get('wall') for e in before['buildings'][0]['roofs'][0]['edges']])
            for key in ['ends','underside','wall_attachments']:self.assertNotIn(key,r)

    def test_canonical_edges_and_split_drop_only_changed_entry(self):
        source=house()['buildings'][0]['roofs'][0];source['ends']={'1':'closed','3':'closed'}
        target=copy.deepcopy(source);target['area']=source['area'][1:]+source['area'][:1];target['edges']=source['edges'][1:]+source['edges'][:1];target.pop('ends')
        carry_fields(source,target,overwrite=True)
        self.assertEqual(target['ends'],{'0':'closed','2':'closed'})
        target=copy.deepcopy(source);target['area']=[[0,0],[20,0],[20,5],[20,10],[0,10]];target['edges'].insert(2,copy.deepcopy(target['edges'][1]));target.pop('ends')
        carry_fields(source,target,overwrite=True)
        self.assertEqual(target['ends'],{'4':'closed'})

    def test_normalizer_and_draw(self):
        r=house()['buildings'][0]['roofs'][0];r.update(ends={'1':'closed','0':'closed','2':'closed'},underside={'kind':'flat','drop_ft':9})
        normalize_support(r,[]);self.assertEqual(r['ends'],{'1':'closed'});self.assertEqual(r['underside'],{'kind':'flat','drop_ft':0})
        value=ops.apply(house(),dict(op='draw_roof',building='b',area=[[30,0],[40,0],[40,4],[30,4]],pitch=0,support={'kind':'post'},ends={'1':'closed'},underside={'kind':'flat','drop_ft':1}))[0]
        self.assertEqual(value['buildings'][0]['roofs'][-1]['ends'],{'1':'closed'})
        with self.assertRaises(ops.Refused):
            ops.apply(house(),dict(op='draw_roof',building='b',area=[[0,0],[20,0],[20,10],[0,10]],pitch=0,support={'kind':'post'},ends={'0':'closed'}))

    def test_draft_choices_and_export_reload(self):
        from services import twin_build, twin_roof_derive, twin_house_saves
        from test_twin_awning_model import AwningRecord
        value=self.edit(house(),ends={'1':'closed','3':'closed'},underside={'kind':'flat','drop_ft':.8})
        original=value['buildings'][0]['roofs'][0]
        original['support']['style']='Custom_carved-style'
        old=roofs.to_sections(original)[0];incoming=roofs.to_sections(house(False)['buildings'][0]['roofs'][0])[0]
        merged=twin_build._merge_list([old],[incoming],'roof',{'openings':[]},{})[0]
        self.assertEqual(merged['ends'],old['ends']);self.assertEqual(merged['underside'],old['underside'])
        reopened=AwningRecord().stored_round_trip(value,named=True)
        self.assertEqual(reopened['buildings'][0]['roofs'][0]['ends'],original['ends'])
        self.assertEqual(reopened['buildings'][0]['roofs'][0]['support']['style'],'Custom_carved-style')
        for kind in ['flat','shed']:
            choice={**copy.deepcopy(old),'kind':kind,'low_side':'y0','pitch':0 if kind=='flat' else 3}
            sections,_=twin_roof_derive.derive_roof([dict(id='block',rect=choice['rect'],level='L1',plate=8,storey=0)],{},{},[choice])
            self.assertEqual(sections[0]['ends']['1'],'closed')
            self.assertEqual(sections[0]['underside'],old['underside'])

    def test_walls_save_is_noop_and_undo_keeps_partial_detach(self):
        for detached in [[],[2],[1,2,3]]:
            settings={};value=house(False);b=value['buildings'][0];b['roofs'][0]=roofs.attach_edges(b['roofs'][0],b['walls'],b['joints'])
            for i in detached:value=ops.apply(value,dict(op='move_roof_edge',building='b',roof='shade',edge=i,by=1,detach=True))[0]
            with tempfile.TemporaryDirectory(prefix='box_walls_') as directory, patch.object(store,'DATA_DIR',directory), patch.object(storage,'get_settings',side_effect=lambda:copy.deepcopy(settings)), patch.object(storage,'patch_settings',side_effect=lambda v:settings.update(copy.deepcopy(v))):
                store._invalidate_reads();store._append_round(store._state(),value,'load');before=store.current_model()
                twin_edit.save(dict(op='set_roof_support',building='b',id='shade',support={'kind':'walls'}),'test')
                self.assertEqual(len(store._state()['rounds']),1);self.assertEqual(store.current_model(),before)
                twin_edit.save(dict(op='set_roof_support',building='b',id='shade',support={'kind':'brace'}),'test');awning=store.current_model();prior=store._state()['current']
                twin_edit.save(dict(op='set_roof_support',building='b',id='shade',support={'kind':'walls'}),'test')
                self.assertEqual([e.get('wall') for e in store.current_model()['buildings'][0]['roofs'][0]['edges']],[e.get('wall') for e in before['buildings'][0]['roofs'][0]['edges']])
                store.revert(prior);store._invalidate_reads();self.assertEqual(store.current_model(),awning)

    def test_python_js_box_normalizers_match(self):
        cases=[]
        for supported in [False,True]:
            for underside in [{'kind':'flat'},{'kind':'flat','drop_ft':3},{'kind':'flat','drop_ft':True},{'kind':'exposed'},{'kind':'rafters'}]:
                r=house(supported)['buildings'][0]['roofs'][0];r.update(ends={'0':'closed','1':'closed','2':'closed','3':'open'},underside=underside);cases.append(r)
        expected=[]
        for r in copy.deepcopy(cases):
            normalize_support(r,[]);expected.append({k:r[k] for k in ['ends','underside'] if k in r})
        module=(Path(__file__).resolve().parents[1]/'static/twin/roof_box_contract.js').as_uri()
        driver='import {normalizeRoofBox} from '+json.dumps(module)+';let s="";for await(const c of process.stdin)s+=c;console.log(JSON.stringify(JSON.parse(s).map(r=>{normalizeRoofBox(r);return Object.fromEntries(["ends","underside"].filter(k=>k in r).map(k=>[k,r[k]]));})));'
        result=subprocess.run(['node','--input-type=module','-e',driver],input=json.dumps(cases),capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout),expected)

    def test_rotated_end_names_follow_drawn_edges(self):
        r=house()['buildings'][0]['roofs'][0]
        cases=[{**r,'roof_frame':{'origin':[4,3],'angle':angle}} for angle in [math.pi/2,math.pi,math.radians(.5)]]
        module=(Path(__file__).resolve().parents[1]/'static/twin/roof_box_contract.js').as_uri()
        driver='import {roofEndLabels} from '+json.dumps(module)+';let s="";for await(const c of process.stdin)s+=c;console.log(JSON.stringify(JSON.parse(s).map(roofEndLabels)));'
        result=subprocess.run(['node','--input-type=module','-e',driver],input=json.dumps(cases),capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),[[['1','Back end'],['3','Front end']],[['1','Left end'],['3','Right end']],[['1','Right end'],['3','Left end']]])

    def test_walls_every_form_is_noop_for_single_batch_agent_and_save(self):
        value=house(False);b=value['buildings'][0];b['roofs'][0]=roofs.attach_edges(b['roofs'][0],b['walls'],b['joints'])
        value=ops.apply(value,dict(op='move_roof_edge',building='b',roof='shade',edge=2,by=1,detach=True))[0]
        operations=[dict(op='set_roof_support',building='b',id='shade',support=s,**extra) for s,extra in [({'kind':'walls'},{}),({'kind':'walls','count':2},{}),({'kind':'walls','style':'plain'},{}),({'kind':'walls','count':99,'style':'bad style'},{'host':None,'thickness_ft':1,'ends':{'1':'closed'},'underside':{'kind':'flat'}})]]
        for actor in ['person','agent']:
            for operation in operations:
                for edit in [operation,dict(op='batch',ops=[operation]),dict(op='batch',ops=[operation,operations[0]])]:
                    with self.subTest(actor=actor,edit=edit):
                        self.assertEqual(ops.apply(value,edit,actor=actor)[0],value)
                        settings={}
                        with tempfile.TemporaryDirectory(prefix='box_noop_') as directory, patch.object(store,'DATA_DIR',directory), patch.object(storage,'get_settings',side_effect=lambda:copy.deepcopy(settings)), patch.object(storage,'patch_settings',side_effect=lambda v:settings.update(copy.deepcopy(v))):
                            store._invalidate_reads();store._append_round(store._state(),value,'load');before=store.current_model()
                            twin_edit.save(edit,actor);self.assertEqual(len(store._state()['rounds']),1);self.assertEqual(store.current_model(),before)
        direct=copy.deepcopy(value['buildings'][0]);ops._more(direct,operations[1]);self.assertEqual(direct,value['buildings'][0])
        mixed=ops.apply(value,dict(op='batch',ops=[operations[1],dict(op='set',building='b',id='b',field='name',value='New cottage')]))[0]
        self.assertEqual(mixed['buildings'][0]['name'],'New cottage')
        self.assertEqual(mixed['buildings'][0]['roofs'][0]['edges'],value['buildings'][0]['roofs'][0]['edges'])

    def test_draw_open_is_absence_without_correction(self):
        value,words=ops.apply(house(),dict(op='draw_roof',building='b',area=[[30,0],[40,0],[40,4],[30,4]],pitch=0,support={'kind':'post'},ends={'1':'open'}))
        self.assertNotIn('ends',value['buildings'][0]['roofs'][-1]);self.assertNotIn('reset invalid',words)

    def test_walls_restore_changed_orientation_keeps_drawn_outline(self):
        from services.twin_model_supports import frame_point
        value=house(False);b=value['buildings'][0];b['roofs'][0]=roofs.attach_edges(b['roofs'][0],b['walls'],b['joints'])
        value=self.edit(value,support={'kind':'bracket'})
        r=value['buildings'][0]['roofs'][0];r.pop('host',None)
        r['area']=[[0,0],[0,10],[20,10],[20,0]]
        r['roof_frame']={'origin':[5,5],'angle':math.radians(.5)}
        for e in r['edges']:
            for key in ['wall','wall_offset','wall_along_offset']:e.pop(key,None)
        drawn=[frame_point(r,p) for p in r['area']]
        result=self.edit(value,support={'kind':'walls'});actual=result['buildings'][0]['roofs'][0]
        self.assertEqual([frame_point(actual,p) for p in actual['area']],drawn)
        self.assertTrue(all('wall' not in e for e in actual['edges']))

    def test_stored_style_pattern_preserves_unknown_and_drops_malformed(self):
        for style in ['custom-style_1','bad style','', 'x'*65,5]:
            r=house()['buildings'][0]['roofs'][0];r['support']['style']=style;normalize_support(r,[])
            if style=='custom-style_1':self.assertEqual(r['support']['style'],style)
            else:self.assertNotIn('style',r['support'])


if __name__=='__main__':unittest.main()

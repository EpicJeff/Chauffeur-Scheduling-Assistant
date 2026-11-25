"""Porch post contract, exercised through the public model operations."""
import copy
import json
import os
import sys
import tempfile
import subprocess
import unittest
from pathlib import Path

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='porch_posts_')
os.environ.pop('HA_BASE_URL', None)
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from test_twin_awning_materials import patio
from services import twin_model_ops as ops, twin_model_bridge as bridge
from services import twin_plan, twin_model
from unittest.mock import patch


def household():
    flat = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    return bridge.assemble(flat)[0]


def command(kind, **kw):
    return dict(op=kind+'_porch_post', building='pool-cottage', porch='patio', **kw)


class Posts(unittest.TestCase):
    def test_fix2_real_save_fulfilled_post_delete(self):
        from test_twin_house_save_stable import MemoryHouse
        from services import twin_edit,twin_store
        members=[dict(op='move_wall',building='pool-cottage',wall='w0',by=[0,-2]),dict(op='delete',building='pool-cottage',id='patio'),command('delete',post='post:patio:0')]
        expected,_=ops.apply(patio(),dict(op='batch',ops=members))
        with MemoryHouse(patio(),persist=True):
            result=twin_edit.save(dict(op='batch',ops=members),'tester')
            self.assertEqual(result['model'],expected)
            self.assertFalse(result['model']['buildings'][0]['porches_detail'])

        model=twin_model.normalize(household())[0]
        for bid,wall,by in [('main-house','separator-70',[0,-2]),('main-house','separator-73',-2),('pool-house',None,[2,0])]:
            b=next(b for b in model['buildings'] if b['id']==bid)
            if wall is None:
                positions={j['id']:j['at'] for j in b['joints']}
                wall=next(w['id'] for w in b['walls'] if all(abs(positions[j][0]-38)<.01 for j in w['joints']))
            edge=next(w for w in b['walls'] if w['id']==wall)
            room=next(r for r in b['rooms'] if r.get('kind')=='porch' and all(j in r['joints'] for j in edge['joints']))
            members=[dict(op='move_wall',building=bid,wall=wall,by=by),dict(op='delete',building=bid,id=room['id']),dict(op='delete_porch_post',building=bid,porch=room['id'],post='post:'+room['id']+':0')]
            expected,_=ops.apply(model,dict(op='batch',ops=members))
            with MemoryHouse(model,persist=True):
                result=twin_edit.save(dict(op='batch',ops=members),'tester')
                for e in bridge.flatten(expected)['buildings']:
                    actual=next(v for v in bridge.flatten(result['model'])['buildings'] if v['id']==e['id'])
                    self.assertEqual([(r['id'],r['polygon']) for r in actual['rooms']],[(r['id'],r['polygon']) for r in e['rooms']])
                    self.assertEqual([(p['id'],p.get('columns',[])) for p in actual.get('porches',[])],[(p['id'],p.get('columns',[])) for p in e.get('porches',[])])
                self.assertFalse(any(p['id']==room['id'] for v in result['model']['buildings'] for p in v.get('porches_detail',[])))

    def test_fix2_first_delete_add_log_values_and_mint_collision(self):
        from test_twin_house_save_stable import MemoryHouse
        from services import twin_edit,twin_store,twin_porch_posts
        original=patio()
        with MemoryHouse(original,persist=True):
            start=len(twin_store.fixes())
            result=twin_edit.save(dict(op='batch',ops=[command('delete',post='post:patio:0'),command('add',at=[4,4])]),'tester')
            columns=[c for c in twin_store.fixes()[start:] if '.columns[' in c['path']]
            self.assertEqual(len(columns),2)
            deleted=next(c for c in columns if c['after'] is None)
            self.assertEqual(deleted['before'],original['buildings'][0]['porches_detail'][0]['columns'][0])
            added=next(c for c in columns if c['before'] is None)
            self.assertEqual(added['after'],result['model']['buildings'][0]['porches_detail'][0]['columns'][-1])
        b=patio()['buildings'][0];b['porches_detail'][0]['columns'][1]['id']='post:patio:0'
        snapshot=copy.deepcopy(b)
        with self.assertRaisesRegex(ops.Refused,'That post id is already in use.'):
            twin_porch_posts.mint_columns(b,b['porches_detail'][0])
        self.assertEqual(b,snapshot)

    def test_fix2_unhashable_conversion_refused(self):
        with self.assertRaises(ops.BatchRefused) as caught:
            ops.apply(patio(),dict(op='batch',ops=[dict(op='set_room_kind',building='pool-cottage',room=[],kind='porch'),command('add')]))
        self.assertEqual(caught.exception.member,0)

    def test_fix2_nonpost_batch_copies_house_once(self):
        model=twin_model.normalize(patio(),preserve_room_polygons=True)[0]
        original=ops.deepcopy;copies=[]
        def track(value):
            if value is model:copies.append(value)
            return original(value)
        with patch.object(ops,'deepcopy',side_effect=track):
            ops.apply_batch(model,dict(op='batch',ops=[dict(op='move_room',building='pool-cottage',room='patio',by=[2,0]),dict(op='move_room',building='pool-cottage',room='patio',by=[-2,0])]),_normalized=(model,[]))
        self.assertEqual(len(copies),1)

    def test_fix1_stable_refs_and_loader(self):
        model = patio()
        changed, _ = ops.apply(model, command('update', post='post:patio:0', at=[2, 3]))
        self.assertEqual([c['id'] for c in changed['buildings'][0]['porches_detail'][0]['columns']], ['post:patio:0', 'post:patio:1'])
        changed, _ = ops.apply(changed, command('delete', post='post:patio:0'))
        changed, _ = ops.apply(changed, command('add', at=[4, 4]))
        self.assertEqual([c['id'] for c in changed['buildings'][0]['porches_detail'][0]['columns']], ['post:patio:1', 'post:patio:2'])
        flat = bridge.flatten(model)
        columns = flat['buildings'][0]['porches'][0]['columns']
        columns[0].update(id='bad', size=.01); columns[1]['size'] = 4
        loaded, notes = twin_plan.normalize(flat)
        self.assertEqual([c['size'] for c in loaded['buildings'][0]['porches'][0]['columns']], [.01, 4])
        self.assertNotIn('id', loaded['buildings'][0]['porches'][0]['columns'][0])
        self.assertTrue(any('id' in n for n in notes))

    def test_fix1_batch_boundaries_and_order(self):
        model=patio(); model['buildings'][0]['porches_detail'][0].pop('columns')
        after,_=ops.apply(model,dict(op='batch',ops=[command('add',at=[1,1]),command('update',post='post:patio:0',size=.6)]))
        self.assertEqual(after['buildings'][0]['porches_detail'][0]['columns'],[dict(id='post:patio:0',at=[1,1],size=.6)])
        with self.assertRaises(ops.BatchRefused) as caught:
            ops.apply(patio(),dict(op='batch',ops=[command('add'),{**command('add'),'porch':'absent'}]))
        self.assertEqual(caught.exception.member,1)
        model=patio(); model['buildings'][0]['rooms'][0]['kind']='room'; model['buildings'][0]['porches_detail']=[]
        after,_=ops.apply(model,dict(op='batch',ops=[dict(op='set_room_kind',building='pool-cottage',room='patio',kind='porch'),command('add',at=[3,3])]))
        self.assertEqual(len(after['buildings'][0]['porches_detail'][0]['columns']),5)
        after,_=ops.apply(patio(),dict(op='batch',ops=[command('update',post='post:patio:0',at=[2,2]),dict(op='move_room',building='pool-cottage',room='patio',by=[2,3])]))
        self.assertEqual(after['buildings'][0]['porches_detail'][0]['columns'][0]['at'],[4,5])
        for at in ([1e5+1,0],[0,-1e5-1]):
            with self.assertRaisesRegex(ops.Refused,'Choose a finite post position.'):
                ops.apply(patio(),command('add',at=at))

    def test_fix1_reread_real_merge_all_household_porches(self):
        from services import twin_build
        original=twin_model.normalize(household(),preserve_room_polygons=True)[0]
        for building in original['buildings']:
            for porch in building.get('porches_detail',[]):
                for action in ('add','delete','gutter'):
                    with self.subTest(porch=porch['id'],action=action):
                        edit=dict(op=action+'_porch_post',building=building['id'],porch=porch['id'])
                        if action=='add': edit['at']=[1,1]
                        elif action=='delete': edit['post']='post:'+porch['id']+':0'
                        else: edit=dict(op='set',building=building['id'],id=porch['id'],field='gutter',value=True)
                        changed,_=ops.apply(original,edit)
                        flat=bridge.flatten(changed); house=next(b for b in flat['buildings'] if b['id']==building['id'])
                        expected=next(p for p in house['porches'] if p['id']==porch['id'])['columns']
                        incoming=copy.deepcopy(house)
                        for p in incoming['porches']:
                            p.pop('level',None); p.pop('src',None)
                            p['columns']=copy.deepcopy(next(d for d in building['porches_detail'] if d['id']==p['id'])['columns'])
                        incoming.pop('porch',None)
                        build=dict(existing=True,inputs={'building':{'id':building['id']}})
                        step=dict(id='draft',kind='draft',source='',page=1,reread=True)
                        with patch.object(twin_build,'_draft_pages',return_value=[]):
                            twin_build._merge_draft(build,step,{'building':incoming},house,tombstones=[])
                        normalized,_=twin_plan.normalize(flat)
                        rebuilt,_=bridge.assemble(normalized,changed)
                        result=next(b for b in rebuilt['buildings'] if b['id']==building['id'])['porches_detail']
                        self.assertEqual(len(result),len(building['porches_detail']))
                        self.assertEqual(next(p for p in result if p['id']==porch['id'])['columns'],expected)

    def test_fix1_follow_corner_normal_and_noop_metadata(self):
        model=patio(); b=model['buildings'][0]; p=b['porches_detail'][0]
        p['columns']=[dict(at=[.5,.5],size=.5),dict(at=[8,.5],size=.5),dict(at=[8,-5],size=.5)]
        result,_=ops.apply(model,dict(op='move_joint',building=b['id'],joint='j0',to=[2,-2]))
        columns=result['buildings'][0]['porches_detail'][0]['columns']
        self.assertEqual(columns[0]['at'],[2.5,-1.5]);self.assertEqual(columns[1]['at'],[8,-.5]);self.assertEqual(columns[2]['at'],[8,-5])
        p['columns']=[dict(at=[8,-5],size=.5)]
        result,_=ops.apply(model,dict(op='move_wall',building=b['id'],wall='w0',by=[0,-2]))
        self.assertEqual(result['buildings'][0]['porches_detail'][0],p)
        p['columns']=[dict(at=[100,100],size=.5)]
        result,_=ops.apply(model,dict(op='move_room',building=b['id'],room='patio',by=[2,3]))
        self.assertEqual(result['buildings'][0]['porches_detail'][0]['columns'][0]['at'],[102,103])

    def test_fix1_follow_no_fix_entries_and_explicit_batch(self):
        from test_twin_house_save_stable import MemoryHouse
        from services import twin_edit,twin_store
        with MemoryHouse(patio(),persist=True):
            start=len(twin_store.fixes())
            twin_edit.save(dict(op='move_room',building='pool-cottage',room='patio',by=[2,3]),'tester')
            self.assertFalse(any('.columns[' in c['path'] for c in twin_store.fixes()[start:]))
        with MemoryHouse(patio(),persist=True):
            start=len(twin_store.fixes())
            result=twin_edit.save(dict(op='batch',ops=[command('update',post='post:patio:0',at=[2,2]),dict(op='move_room',building='pool-cottage',room='patio',by=[2,3])]),'tester')
            changes=[c for c in twin_store.fixes()[start:] if '.columns[' in c['path']]
            self.assertTrue(changes)
            self.assertEqual(result['model']['buildings'][0]['porches_detail'][0]['columns'][0]['at'],[4,5])

    def test_fix1_explicit_roof_transfer_still_logs_in_move_batch(self):
        from test_twin_house_save_stable import MemoryHouse
        from services import twin_edit,twin_store
        with MemoryHouse(patio(),persist=True):
            start=len(twin_store.fixes())
            twin_edit.save(dict(op='batch',ops=[dict(op='move_posts_to_roof',building='pool-cottage',porch='patio',roof='shade'),dict(op='move_room',building='pool-cottage',room='patio',by=[2,3])]),'tester')
            columns=[c for c in twin_store.fixes()[start:] if '.columns[' in c['path']]
            self.assertEqual(len(columns),2)

    def test_fix1_diff_reserves_ids_before_content(self):
        left={'p':{'columns':[dict(at=[1,1],size=.5),dict(id='post:keep',at=[1,1],size=.5)]}}
        right={'p':{'columns':[dict(id='post:keep',at=[1,1],size=.5)]}}
        self.assertEqual(twin_plan.diff_paths(left,right),['p.columns[0]'])

    def test_fix1_id_validation_and_room_default_geometry(self):
        for value in ('post:', 'post:human readable', 'post:'+'x'*115):
            result,_=ops.apply(patio(),command('add',id=value,at=[3,3]))
            self.assertEqual(result['buildings'][0]['porches_detail'][0]['columns'][-1]['id'],value)
        for value in ('post:'+'x'*116,'nope'):
            with self.assertRaisesRegex(ops.Refused,'Choose a post id starting with post: and at most 120 characters.'):
                ops.apply(patio(),command('add',id=value))
        with self.assertRaisesRegex(ops.Refused,'That post id is already in use.'):
            ops.apply(patio(),command('add',id='post:patio:0'))
        model=patio(); stale=copy.deepcopy(model)
        stale['buildings'][0]['porches_detail'][0]['polygon']=[[100,100],[110,100],[110,110],[100,110]]
        stale['buildings'][0]['porches_detail'][0]['level']='absent'
        from services.twin_porch_posts import default_at
        self.assertEqual(default_at(stale['buildings'][0],stale['buildings'][0]['porches_detail'][0],.5), default_at(model['buildings'][0],model['buildings'][0]['porches_detail'][0],.5))

    def test_household_defaults_and_no_load_mint(self):
        model = household(); saved = copy.deepcopy(model)
        b = next(b for b in model['buildings'] if b.get('porches_detail'))
        p = b['porches_detail'][0]
        self.assertFalse(any('id' in c for c in p['columns']))
        self.assertEqual([c['size'] for c in p['columns']], [.83, 1, 1, .5])
        after, _ = ops.apply(model, dict(op='add_porch_post', building=b['id'], porch=p['id']))
        result = next(row for row in after['buildings'] if row['id'] == b['id'])['porches_detail'][0]
        self.assertEqual(result['columns'][-1]['size'], 1)
        self.assertEqual(model, saved)
        self.assertEqual(bridge.flatten(model), bridge.flatten(saved))

    def test_edit_mints_once_and_derived_ref_survives(self):
        model = patio(); original = copy.deepcopy(model)
        after, _ = ops.apply(model, command('update', post='post:patio:0', at=[-2, 4]))
        columns = after['buildings'][0]['porches_detail'][0]['columns']
        self.assertEqual([c['id'] for c in columns], ['post:patio:0','post:patio:1'])
        self.assertEqual(columns[0]['at'], [-2, 4])
        again, _ = ops.apply(after, command('update', post=columns[0]['id'], size=1))
        self.assertEqual([c['id'] for c in again['buildings'][0]['porches_detail'][0]['columns']], [c['id'] for c in columns])
        self.assertEqual(model, original)
        deleted,_ = ops.apply(after, command('delete', post='post:patio:0'))
        self.assertEqual(deleted['buildings'][0]['porches_detail'][0]['columns'][0]['id'], 'post:patio:1')
        self.assertTrue(after['buildings'][0]['porches_detail'][0]['src']['person'])
        self.assertEqual(bridge.assemble(bridge.flatten(after), after)[0]['buildings'][0]['porches_detail'][0]['columns'], columns)

    def test_add_delete_and_empty_detail(self):
        model = patio(); model['buildings'][0]['porches_detail'] = []
        added, _ = ops.apply(model, command('add', id='post:'+'a'*32))
        columns = added['buildings'][0]['porches_detail'][0]['columns']
        self.assertEqual(len(columns), 1); self.assertEqual(columns[0]['size'], .5)
        deleted, _ = ops.apply(added, command('delete', post=columns[0]['id']))
        self.assertEqual(deleted['buildings'][0]['porches_detail'][0]['columns'], [])

    def test_refusals(self):
        for kw, words in [({'size':0}, 'Choose a post size from 0.05 to 3 feet.'),
                          ({'at':[float('inf'), 0]}, 'Choose a finite post position.'),
                          ({'id':'bad'}, 'Choose a post id starting with post: and at most 120 characters.')]:
            with self.subTest(kw=kw), self.assertRaises(ops.Refused) as caught:
                ops.apply(patio(), command('add', **kw))
            self.assertEqual(str(caught.exception), words)

    def test_limits_missing_states_and_atomic_batch(self):
        cases = [command('update', post='post:patio:99', size=1),
                 command('update', post='post:patio:0'),
                 command('add', size=True), command('add', at=[1]), command('add', at=[True, 1])]
        words = ['That post is missing.', 'Choose a post position or size to change.',
                 'Choose a post size from 0.05 to 3 feet.', 'Choose a finite post position.', 'Choose a finite post position.']
        for op, sentence in zip(cases, words):
            with self.subTest(op=op), self.assertRaises(ops.Refused) as caught: ops.apply(patio(), op)
            self.assertEqual(str(caught.exception), sentence)
        model = patio(); p = model['buildings'][0]['porches_detail'][0]
        p['columns'] = [dict(at=[0, 0], size=.5) for _ in range(40)]
        with self.assertRaisesRegex(ops.Refused, '^A porch can have at most 40 posts\\.$'): ops.apply(model, command('add'))
        for state in ('ghost', 'proposal'):
            model = patio(); model['buildings'][0]['porches_detail'][0]['state'] = state
            with self.assertRaises(ops.Refused) as caught: ops.apply(model, command('add'))
            self.assertEqual(str(caught.exception), 'Choose a settled porch; ghost and proposal porches cannot edit posts.')
        model = patio(); saved = copy.deepcopy(model)
        with self.assertRaises(ops.BatchRefused): ops.apply(model, dict(op='batch', ops=[command('add'), command('add', size=9)]))
        self.assertEqual(model, saved)

    def test_batch_deletes_in_either_order_and_multiple_posts(self):
        porch = dict(op='delete', building='pool-cottage', id='patio')
        post = command('delete', post='post:patio:0')
        for members in ([porch,post], [post,porch]):
            after, _ = ops.apply(patio(), dict(op='batch', ops=members))
            self.assertFalse(after['buildings'][0]['porches_detail'])
        after, _ = ops.apply(patio(), dict(op='batch', ops=[post, command('delete', post='post:patio:1')]))
        self.assertEqual(after['buildings'][0]['porches_detail'][0]['columns'], [])
        added='post:'+'e'*32
        after,_=ops.apply(patio(),dict(op='batch',ops=[command('add',id=added),command('update',post=added,size=.6)]))
        self.assertEqual(after['buildings'][0]['porches_detail'][0]['columns'][-1]['size'],.6)

    def test_ids_unique_across_building_and_transfer(self):
        model, _ = ops.apply(patio(), command('add', at=[5,2], id='post:'+'b'*32))
        with self.assertRaisesRegex(ops.Refused, '^That post id is already in use\\.$'):
            ops.apply(model, command('add', id='post:'+'b'*32))
        moved, _ = ops.apply(model, dict(op='move_posts_to_roof', building='pool-cottage', porch='patio', roof='shade'))
        self.assertEqual(moved['buildings'][0]['roofs'][0]['support']['count'], 3)

    def test_person_and_agent_bounds_without_room_derivation(self):
        for actor in ('person','agent'):
            for size in (.05,3):
                model=patio()
                with patch.object(twin_model,'derive',wraps=twin_model.derive) as derive:
                    added,_=ops.apply(model,command('add',at=[-30,50],size=size),actor)
                    ref=added['buildings'][0]['porches_detail'][0]['columns'][-1]['id']
                    updated,_=ops.apply(added,command('update',post=ref,at=[50,-30]),actor)
                    ops.apply(updated,command('delete',post=ref),actor)
                    derive.assert_not_called()
                self.assertTrue(updated['buildings'][0]['porches_detail'][0]['src']['person'])

    def test_flat_bad_column_only_and_fingerprint(self):
        from services.twin_lighting_rev import lighting_fingerprint
        from services.twin_porch_posts import mint_columns
        model = patio(); key = lighting_fingerprint(model); flat = bridge.flatten(model)
        p = flat['buildings'][0]['porches'][0]
        p['columns'].insert(1, dict(at=[0,0],size=0))
        normalized, notes = twin_plan.normalize(flat)
        self.assertEqual(len(normalized['buildings'][0]['porches'][0]['columns']), 2)
        self.assertTrue(any('Dropped porch column 1' in n for n in notes))
        b = model['buildings'][0]; mint_columns(b, b['porches_detail'][0])
        self.assertEqual(lighting_fingerprint(model), key)
        self.assertEqual(twin_plan.diff_paths(patio(), model), [])
        source=subprocess.check_output(['git','show','main:chauffeur/services/twin_lighting_rev.py'],cwd=ROOT,text=True,encoding='utf-8')
        baseline={};exec(compile(source,'main:twin_lighting_rev.py','exec'),baseline)
        self.assertEqual(lighting_fingerprint(patio()),baseline['lighting_fingerprint'](patio()))
        fixture=household()
        self.assertEqual(lighting_fingerprint(fixture),baseline['lighting_fingerprint'](fixture))

    def test_fix_log_undo_revert_raw_building_save(self):
        from test_twin_house_save_stable import MemoryHouse, setup_plot, TestClient, main
        from services import twin_edit, twin_store
        original = patio()
        original['buildings'][0]['levels'][0]['outline'] = copy.deepcopy(original['buildings'][0]['rooms'][0]['polygon'])
        with MemoryHouse(original, persist=True) as memory:
            initial = len(twin_store.fixes())
            added = twin_edit.save(command('add', at=[5, 2]), 'tester')
            self.assertEqual(len(twin_store.fixes())-initial, 1)
            columns = added['model']['buildings'][0]['porches_detail'][0]['columns']
            rid = added['round']
            setup_plot(memory, added['model'], 'pool-cottage')
            response = TestClient(main.app).patch('/api/house/editor/place/buildings/pool-cottage', json={'name':'Cottage'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(twin_store.current_model()['buildings'][0]['porches_detail'][0]['columns'], columns)
            twin_store.revert(1)
            self.assertEqual(twin_store.current_model(), original)
            twin_store.revert(rid)
            self.assertEqual(twin_store.current_model()['buildings'][0]['porches_detail'][0]['columns'], columns)
            before = len(twin_store.fixes())
            twin_edit.save(command('delete', post=columns[0]['id']), 'tester')
            self.assertEqual(len(twin_store.fixes())-before, 1)

    def test_reread_protection_without_read_geometry(self):
        from services import twin_build
        flat = bridge.flatten(patio()); house = flat['buildings'][0]; old = house['porches'][0]
        old.update(src={'person':True, 'step':'draft'})
        incoming = copy.deepcopy(old); incoming.update(id='read',src={'step':'draft'},columns=[])
        old['polygon'] = [[x+6,y] for x,y in old['polygon']]
        result = twin_build._merge_list([old], [incoming], 'porch', house, {'existing':True}, {'id':'draft','reread':True}, tombstones=[])
        self.assertEqual(len(result), 1); self.assertEqual(result[0]['columns'], old['columns'])

    def test_draft_parser_and_export_keep_ids(self):
        from services import twin_reads
        model,_=ops.apply(patio(),command('update',post='post:patio:0',size=.5))
        flat=bridge.flatten(model); porch=flat['buildings'][0]['porches'][0]
        answer={'porches':[porch]}
        draft,notes=twin_reads.parse('draft', {'building':answer})
        self.assertEqual(draft['building']['porches'][0]['columns'], [dict(at=c['at'],size=c['size'],id=c['id']) for c in porch['columns']])
        restored=bridge.assemble(json.loads(json.dumps(flat)),model)[0]
        self.assertEqual(restored['buildings'][0]['porches_detail'][0]['columns'],porch['columns'])

    def test_first_delete_one_fix_with_correct_values(self):
        from test_twin_house_save_stable import MemoryHouse
        from services import twin_edit,twin_store
        original=patio()
        with MemoryHouse(original,persist=True):
            n=len(twin_store.fixes())
            twin_edit.save(command('delete',post='post:patio:0'),'tester')
            fixes=twin_store.fixes()[n:]
            self.assertEqual(len(fixes),1)
            self.assertEqual(fixes[0]['before'],original['buildings'][0]['porches_detail'][0]['columns'][0])
            self.assertIsNone(fixes[0]['after'])

    def test_real_house_save_export_import_and_load_keep_ids(self):
        from test_twin_house_save_stable import MemoryHouse
        from services import twin_house_saves as saves,twin_store
        model,_=ops.apply(patio(),command('update',post='post:patio:0',at=[2,2]))
        columns=model['buildings'][0]['porches_detail'][0]['columns']
        with MemoryHouse(model,persist=True):
            saved=saves.save_current('Post regression','tester')
            exported=saves.download(saved['id'])
            self.assertEqual(exported['model']['buildings'][0]['porches_detail'][0]['columns'],columns)
            imported=saves.upload(json.dumps(exported).encode(),'tester')
            saves.load(imported['save']['id'])
            self.assertEqual(twin_store.current_model()['buildings'][0]['porches_detail'][0]['columns'],columns)

    def test_describe_porch_and_post(self):
        from services import twin_store, agent_tools_v2 as agent
        flat = bridge.flatten(patio())
        with patch.object(twin_store,'current',return_value=flat):
            for ref in ('patio','post:patio:0'):
                result = agent.handle_house_design({'action':'describe','piece':ref,'building':'pool-cottage'}, {'id':'tester','role':'parent'})
                self.assertEqual(result['status'], 'ok', result)
                self.assertEqual(result['posts'], [dict(ref='post:patio:0', at=[1,1], size=2/3), dict(ref='post:patio:1', at=[15,1],size=2/3)])

    def test_follow_translation(self):
        from services.twin_porch_posts import follow_posts
        before = patio()['buildings'][0]; after = copy.deepcopy(before)
        after['rooms'][0]['polygon'] = [[x+3, y+2] for x,y in before['rooms'][0]['polygon']]
        for j in after['joints']: j['at'] = [j['at'][0]+3,j['at'][1]+2]
        follow_posts(before, after)
        self.assertEqual(after['porches_detail'][0]['columns'][0]['at'], [4,3])

    def test_follow_pulled_edge_tie_far_and_unmoved(self):
        from services.twin_porch_posts import follow_posts
        before = patio()['buildings'][0]
        before['porches_detail'][0]['columns'] = [dict(at=[8,.2],size=.5),dict(at=[.2,4],size=.5),dict(at=[1,1],size=.5),dict(at=[8,-5],size=.5)]
        after = copy.deepcopy(before); follow_posts(before, after)
        self.assertEqual(after, before)
        after['rooms'][0]['polygon'][0][1] -= 2; after['rooms'][0]['polygon'][1][1] -= 2
        for j in after['joints']:
            if j['at'][1] == 0: j['at'][1] -= 2
        follow_posts(before,after)
        self.assertEqual([c['at'] for c in after['porches_detail'][0]['columns']], [[8,-1.8],[.2,4],[1,-1],[8,-5]])

    def test_unmoved_porch_stays_byte_identical(self):
        from services.twin_porch_posts import follow_posts
        before=patio()['buildings'][0]
        second=copy.deepcopy(before['rooms'][0]);second['id']='unmoved'
        before['rooms'].append(second)
        detail=copy.deepcopy(before['porches_detail'][0]);detail['id']='unmoved';detail['extra']={'keep':[1,2,3]}
        before['porches_detail'].append(detail)
        after=copy.deepcopy(before);after['rooms'][0]['polygon']=[[x+3,y] for x,y in before['rooms'][0]['polygon']]
        follow_posts(before,after)
        self.assertEqual(json.dumps(after['porches_detail'][1]),json.dumps(detail))

    def test_public_moves_and_typed_length_follow(self):
        # Exercise the dispatch, derivation and common follow seam, rather
        # than only testing the geometry helper.
        for operation in [dict(op='move_room',room='patio',by=[2,3]),
                          dict(op='move_wall',wall='w0',by=[0,-2]),
                          dict(op='move_joint',joint='j0',to=[0,-2]),
                          dict(op='split_wall',wall='w0',at=8),
                          dict(op='move_joints',joints=[{'joint':'j1','to':[20,0]},{'joint':'j2','to':[20,8]}])]:
            model = patio(); operation['building']='pool-cottage'
            after,_=ops.apply(model,operation)
            self.assertEqual(len(after['buildings'][0]['porches_detail'][0]['columns']),2)
            if operation['op']=='move_room':
                self.assertEqual(after['buildings'][0]['porches_detail'][0]['columns'][0]['at'],[3,4])
            if operation['op']=='move_wall':
                self.assertEqual([c['at'] for c in after['buildings'][0]['porches_detail'][0]['columns']],[[1,-1],[15,-1]])
            if operation['op']=='move_joint':
                self.assertEqual([c['at'] for c in after['buildings'][0]['porches_detail'][0]['columns']],[[1,-.875],[15,.875]])
            if operation['op']=='move_joints':
                self.assertEqual([c['at'] for c in after['buildings'][0]['porches_detail'][0]['columns']],[[1,1],[15,1]])
            if operation['op']=='split_wall':
                new=next(j['id'] for j in after['buildings'][0]['joints'] if j['id'] not in {p['id'] for p in model['buildings'][0]['joints']})
                merged,_=ops.apply(after,dict(op='delete',building='pool-cottage',id=new))
                self.assertEqual(merged['buildings'][0]['porches_detail'][0]['columns'],after['buildings'][0]['porches_detail'][0]['columns'])


if __name__ == '__main__': unittest.main()

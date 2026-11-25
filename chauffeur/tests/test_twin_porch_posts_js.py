"""Runtime JS contract for posts, bake identity and local edits."""
from test_twin_porch_posts_model import ROOT, patio, bridge, unittest, household, command, ops, twin_model
import copy
import json
from twin_editor_dom import PRELUDE, run_node


class PostsJS(unittest.TestCase):
    def test_fix1_household_wall_sweep(self):
        model = twin_model.normalize(household(), preserve_room_polygons=True)[0]
        cases = []; refused = 0; max_distance = 0
        for b in model['buildings']:
            for wall in b['walls']:
                for sign in (-1, 1):
                    operation = dict(op='move_wall', building=b['id'], wall=wall['id'], by=sign)
                    try: after, _ = ops.apply(model, operation)
                    except ops.Refused:
                        refused += 1; continue
                    target = next(v for v in after['buildings'] if v['id'] == b['id'])
                    for p in b.get('porches_detail', []):
                        new = next(v for v in target['porches_detail'] if v['id'] == p['id'])
                        for c, d in zip(p.get('columns', []), new.get('columns', [])):
                            import math
                            distance = math.dist(c['at'], d['at']); max_distance = max(max_distance, distance)
                            self.assertLessEqual(distance, 1.000001, (wall['id'], sign, p['id'], c, d))
                    cases.append(dict(plan=bridge.flatten(model), operation=operation, expected=bridge.flatten(after)))
        code, out = run_node(PRELUDE+r"""
const {applyLocal}=await import(file('static/twin/editor/local_ops.js'));
for(const c of input.cases){const result=applyLocal(c.plan,c.operation);assert.ok(result,c.operation.wall);
 for(const b of c.expected.buildings) for(const p of b.porches||[]){const local=result.plan.buildings.find(v=>v.id===b.id).porches.find(v=>v.id===p.id);
 assert.equal(local.columns.length,p.columns.length);for(const [i,column] of p.columns.entries()){assert.equal(local.columns[i].id,column.id);assert.equal(local.columns[i].size,column.size);for(let axis=0;axis<2;++axis)assert.ok(Math.abs(local.columns[i].at[axis]-column.at[axis])<1e-8,JSON.stringify(c.operation)+':'+p.id+':'+JSON.stringify([local.columns[i],column]));}}}
""", dict(root=ROOT.as_posix(), cases=cases))
        self.assertEqual(code, 0, out)
        print('FIX1_WALL_SWEEP '+json.dumps(dict(accepted=len(cases), refused=refused, max_post_move=max_distance)))

    def test_fix1_real_edit_queue_household(self):
        base=twin_model.normalize(household(),preserve_room_polygons=True)[0]; cases=[]
        for b in base['buildings']:
            for p in b.get('porches_detail',[]):
                x,y=p['columns'][0]['at']; ref='post:'+p['id']+':0'
                common=dict(building=b['id'],porch=p['id'])
                sequences=[
                    [dict(op='update_porch_post',post=ref,at=[x+1,y],**common),dict(op='update_porch_post',post=ref,at=[x+1,y+1],**common)],
                    [dict(op='update_porch_post',post=ref,at=[x+1,y],**common),dict(op='update_porch_post',post=ref,at=[x+2,y],**common)],
                    [dict(op='delete_porch_post',post=ref,**common),dict(op='delete_porch_post',post='post:'+p['id']+':1',**common)],
                    [dict(op='add_porch_post',at=[x,y],**common),dict(op='update_porch_post',post='post:'+p['id']+':'+str(len(p['columns'])),at=[x+2,y+3],**common)]
                ]
                for members in sequences:
                    work=copy.deepcopy(base);answers=[]
                    for member in members:
                        work,_=ops.apply(work,member);answers.append(bridge.flatten(work))
                    cases.append(dict(plan=bridge.flatten(base),ops=members,answers=answers,building=b['id'],porch=p['id']))
        code,out=run_node(PRELUDE+r"""
const {createEditQueue}=await import(file('static/twin/editor/edit_queue.js'));
const columns=(plan,c)=>plan.buildings.find(b=>b.id===c.building).porches.find(p=>p.id===c.porch).columns;
for(const c of input.cases){let release,sent=0;const notices=[];
 const q=createEditQueue({send:async op=>{const i=sent++;assert.deepEqual(op,c.ops[i]);if(!i)await new Promise(r=>release=r);return {round:i+2,plan:c.answers[i]};},onChange:e=>notices.push(e)});
 q.base({round:1,plan:c.plan});const pending=c.ops.map(op=>q.push({op,label:op.op}));
 assert.deepEqual(columns(q.shown(),c),columns(c.answers.at(-1),c),'optimistic queue');
 release();await Promise.all(pending.map(p=>p.saved));
 assert.equal(sent,c.ops.length);assert.equal(q.pending(),0);assert.deepEqual(columns(q.shown(),c),columns(c.answers.at(-1),c));
 assert.ok(notices.every(n=>!n.dropped.length&&!n.refused.length));
}
console.log('FIX1_QUEUE '+input.cases.length+' scenarios');
""",dict(root=ROOT.as_posix(),cases=cases))
        self.assertEqual(code,0,out);print(out)

    def test_fix1_household_splits_leave_posts_and_preview_cost(self):
        model=twin_model.normalize(household(),preserve_room_polygons=True)[0];cases=[];refused=0
        for b in model['buildings']:
            positions={j['id']:j['at'] for j in b['joints']}
            for wall in b['walls']:
                import math
                operation=dict(op='split_wall',building=b['id'],wall=wall['id'],at=math.dist(*(positions[j] for j in wall['joints']))/2)
                try: after,_=ops.apply(model,operation)
                except ops.Refused: refused+=1;continue
                target=next(v for v in after['buildings'] if v['id']==b['id'])
                self.assertEqual(target.get('porches_detail',[]),b.get('porches_detail',[]))
                cases.append(dict(operation=operation,expected=bridge.flatten(after)))
        code,out=run_node(PRELUDE+r"""
const {applyLocal,moveGesture,movePreview}=await import(file('static/twin/editor/local_ops.js'));
for(const c of input.cases){const result=applyLocal(input.plan,c.operation);assert.ok(result,JSON.stringify(c.operation));
 for(const b of c.expected.buildings)for(const p of b.porches||[])assert.deepEqual(result.plan.buildings.find(v=>v.id===b.id).porches.find(v=>v.id===p.id).columns,p.columns);}
const times=[];
for(const b of input.plan.buildings)for(const room of b.rooms.filter(r=>r.kind==='porch')){
 const gesture=moveGesture(input.plan,{kind:'room',building:b.id,id:room.id});
 for(let i=0;i<10;++i)movePreview(input.plan,gesture,[1,1]);
 for(let i=0;i<100;++i){const t=performance.now(),preview=movePreview(input.plan,gesture,[1,1]);times.push(performance.now()-t);
 const before=b.porches.find(p=>p.id===room.id),after=preview.buildings.find(v=>v.id===b.id).porches.find(p=>p.id===room.id);
 for(const [i,c] of before.columns.entries())assert.ok(Math.hypot(after.columns[i].at[0]-c.at[0]-1,after.columns[i].at[1]-c.at[1]-1)<1e-8);}
}
times.sort((a,b)=>a-b);console.log('FIX1_PREVIEW '+JSON.stringify({frames:times.length,median_ms:times[Math.floor(times.length/2)],p95_ms:times[Math.floor(times.length*.95)]}));
""",dict(root=ROOT.as_posix(),plan=bridge.flatten(model),cases=cases))
        self.assertEqual(code,0,out);print('FIX1_SPLIT_SWEEP '+json.dumps(dict(accepted=len(cases),refused=refused)));print(out)

    def test_fix1_mint_settle_and_live_post_buffers(self):
        from test_twin_yard_reuse_js import PREFIX
        from test_twin_awning_golden_js import FIXTURE
        code,out=run_node(PREFIX+FIXTURE+r"""
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const {buildingKey}=await import(file('static/twin/twin_generator.js'));
const {moveGesture,movePreview}=await import(file('static/twin/editor/local_ops.js'));
const plan=input.plan,b=plan.buildings[0];b.roofs=[];b.roof.sections=[];
const host=new Element(),shell=new Element();shell.className='editor-shell';shell.append(host);
const v=await mountTwin(host,{plan,kit:kit(),tier:'high',bake:false,preserveCamera:true});while(!v.ready)await new Promise(r=>setTimeout(r,1));
const minted=structuredClone(plan);for(const p of minted.buildings[0].porches)p.columns.forEach((c,i)=>c.id=`post:${p.id}:${i}`);
assert.equal(buildingKey(plan,b,kit(),'high'),buildingKey(minted,minted.buildings[0],kit(),'high'));
const settled=await v.settle(minted);assert.equal(settled.path,'deform');
const old=v.worldBox('post:patio:0',b.id),gesture=moveGesture(minted,{kind:'room',building:b.id,id:'patio'}),preview=movePreview(minted,gesture,[2,3]);
v.rebuildLevel(b.id,'L1',preview,gesture.touched);const moved=v.worldBox('post:patio:0',b.id);
assert.ok(Math.abs(moved.min[0]-old.min[0]-2)<1e-5);assert.ok(Math.abs(moved.min[1]-old.min[1]-3)<1e-5);
const hint={walls:[],rooms:[],openings:[],anchors:[],items:[]},times=[],baseline=[];
for(let i=0;i<110;++i){let t=performance.now();v.rebuildLevel(b.id,'L1',i%2?preview:minted,hint);if(i>=10)times.push(performance.now()-t);
 t=performance.now();v.rebuildLevel(b.id,'L1',i%2?preview:minted,hint);if(i>=10)baseline.push(performance.now()-t);}
const median=a=>a.sort((x,y)=>x-y)[Math.floor(a.length/2)],cost=median(times)-median(baseline);
assert.ok(cost<2,'post buffer transport under 2 ms');console.log('FIX1_POST_BUFFER_MS '+JSON.stringify({frames:times.length,median:median(times),baseline:median(baseline),extra:cost}));
v.dispose();
""",dict(root=ROOT.as_posix(),plan=bridge.flatten(patio())))
        self.assertEqual(code,0,out);print(out)

    def test_fix1_view_ranking_skip_and_sky_cover(self):
        from test_twin_yard_reuse_js import PREFIX
        from test_twin_awning_golden_js import FIXTURE
        code,out=run_node(PREFIX+FIXTURE+r"""
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const {buildTwin}=await import(file('static/twin/twin_generator.js'));
const plan=input.plan,b=plan.buildings[0];b.roofs=[];b.roof.sections=[];
async function mount(p){const host=new Element(),shell=new Element();shell.className='editor-shell';shell.append(host);const v=await mountTwin(host,{plan:p,kit:kit(),tier:'high',bake:false,preserveCamera:true});while(!v.ready)await new Promise(r=>setTimeout(r,1));v.setPlanCamera(b.id+':L1');v.setView(b.id+':L1');return v;}
let v=await mount(plan),pixel=v.screenOfFloor(1,1,b.id+':L1'),hits=v.pickAll(...pixel);
assert.equal(hits[0].kind,'porch_post');assert.equal(hits[1].id,'patio');
assert.ok(v.pickAll(...pixel,{skip:['room']}).every(p=>p.kind!=='porch_post'&&p.kind!=='room'));
v.dispose();
const front=structuredClone(plan);front.buildings[0].walls.push({id:'in-front',level:'L1',from:[0,1],to:[2,1],height:15,thickness:.5,exterior:false,state:'settled'});
v=await mount(front);pixel=v.screenOfFloor(1,1,b.id+':L1');hits=v.pickAll(...pixel);
assert.equal(hits[0].id,'in-front');assert.equal(hits[1].kind,'porch_post');assert.equal(hits[2].id,'patio');v.dispose();
front.buildings[0].walls.at(-1).height=1;v=await mount(front);pixel=v.screenOfFloor(1,1,b.id+':L1');
assert.equal(v.pickAll(...pixel)[0]?.kind,'porch_post');assert.equal(v.pick(...pixel)?.kind,'porch_post');v.dispose();
const screened=structuredClone(plan);screened.buildings[0].walls=[];screened.buildings[0].porches[0].screened=true;screened.buildings[0].porches[0].columns=[{at:[1,0],size:.5},{at:[15,0],size:.5},{at:[8,4],size:.5}];
v=await mount(screened);v.setView('ext');v.setCameraState({position:[8*.3048,4*.3048,10*.3048],target:[8*.3048,4*.3048,-4*.3048]});
hits=v.pickAll(720,450);assert.equal(hits[0]?.id,'patio',JSON.stringify(hits));assert.equal(v.pick(720,450)?.id,'patio');v.dispose();
const far=structuredClone(plan);far.buildings[0].porches[0].columns[0].at=[100,100];
const out=buildTwin(far,kit(),'high',{viewing:true});await out.ready;
const proxy=out.pickObjects.get(b.id+':patio'),box=proxy.geometry.boundingBox;
proxy.geometry.computeBoundingBox();const values=proxy.userData.coverPositions;assert.ok(values);
for(let i=0;i<values.length;i+=3){assert.ok(values[i]>=proxy.geometry.boundingBox.min.x-1e-5&&values[i]<=proxy.geometry.boundingBox.max.x+1e-5);assert.ok(values[i+2]>=proxy.geometry.boundingBox.min.z-1e-5&&values[i+2]<=proxy.geometry.boundingBox.max.z+1e-5);}
""",dict(root=ROOT.as_posix(),plan=bridge.flatten(patio())))
        self.assertEqual(code,0,out)

    def test_household_drawn_bytes_and_keys_equal_main(self):
        from twin_porch_posts_evidence import compare
        evidence = compare(bridge.flatten(household()),measure=False)
        self.assertTrue(evidence['posts'])
        print('HOUSEHOLD_EVIDENCE '+json.dumps(evidence))

    def test_explicit_column_uvs_equal_main(self):
        from twin_porch_posts_evidence import compare
        self.assertTrue(compare(bridge.flatten(patio()),measure=False,tiers=['high']))
        legacy=bridge.flatten(patio());legacy['buildings'][0]['porches'][0]['columns'][0]['at']=[-2.33,1]
        self.assertTrue(compare(legacy,measure=False,tiers=['high']))

    def test_editable_level_keeps_batches_equal_main(self):
        from twin_porch_posts_evidence import compare
        self.assertTrue(compare(bridge.flatten(patio()),measure=False,tiers=['high'],opts={'editableLevel':'pool-cottage:L1'}))

    def test_roof_transfer_accepts_minted_ids(self):
        model,_=ops.apply(patio(),command('update',post='post:patio:0',size=2/3))
        code,out=run_node(PRELUDE+r"""
const {postRoofReason}=await import(file('static/twin/editor/posts_action.js'));
const b=input.plan.buildings[0];assert.equal(postRoofReason(b,b.porches[0],b.roofs[0]),null);
""",dict(root=ROOT.as_posix(),plan=bridge.flatten(model)))
        self.assertEqual(code,0,out)

    def test_server_local_shared_cases(self):
        cases=[]
        for members in ([command('update',post='post:patio:0',at=[-2,3],size=.8)],
                        [command('add',id='post:'+'c'*32)],
                        [command('delete',post='post:patio:0')],
                        [command('delete',post='post:patio:0'),command('delete',post='post:patio:1')],
                        [dict(op='move_room',building='pool-cottage',room='patio',by=[2,3])],
                        [dict(op='move_wall',building='pool-cottage',wall='w0',by=[0,-2])],
                        [dict(op='move_room',building='pool-cottage',room='patio',by=[2,3]),command('update',post='post:patio:0',size=.5),command('update',post='post:patio:1',at=[12,2])],
                        [command('update',post='post:patio:0',size=.5),command('update',post='post:patio:1',at=[12,2])]):
            model=patio(); operation=members[0] if len(members)==1 else dict(op='batch',ops=members)
            after,_=ops.apply(model,operation)
            cases.append(dict(plan=bridge.flatten(model), operation=operation, expected=bridge.flatten(after)))
        model=patio(); model['buildings'][0]['porches_detail']=[]
        operation=command('add',id='post:'+'d'*32)
        after,_=ops.apply(model,operation)
        cases.append(dict(plan=bridge.flatten(model),operation=operation,expected=bridge.flatten(after)))
        model=patio();model['buildings'][0]['porches_detail'][0].pop('columns')
        operation=dict(op='batch',ops=[command('add',at=[1,1]),command('update',post='post:patio:0',size=.6)])
        after,_=ops.apply(model,operation);cases.append(dict(plan=bridge.flatten(model),operation=operation,expected=bridge.flatten(after)))
        model=patio();model['buildings'][0]['rooms'][0]['kind']='room';model['buildings'][0]['porches_detail']=[]
        operation=dict(op='batch',ops=[dict(op='set_room_kind',building='pool-cottage',room='patio',kind='porch'),command('add',at=[3,3])])
        after,_=ops.apply(model,operation);cases.append(dict(plan=bridge.flatten(model),operation=operation,expected=bridge.flatten(after)))
        model=patio();operation=dict(op='batch',ops=[command('update',post='post:patio:0',at=[2,2]),dict(op='move_room',building='pool-cottage',room='patio',by=[2,3])])
        after,_=ops.apply(model,operation);cases.append(dict(plan=bridge.flatten(model),operation=operation,expected=bridge.flatten(after)))
        # Both dispatchers see the same normalized operation boundary; raw
        # server normalization also fills unrelated optional empty site lists.
        model=twin_model.normalize(household(),preserve_room_polygons=True)[0]
        b=next(b for b in model['buildings'] if b.get('porches_detail'));p=b['porches_detail'][0]
        operation=dict(op='add_porch_post',building=b['id'],porch=p['id'])
        after,_=ops.apply(model,operation)
        cases.append(dict(plan=bridge.flatten(model),operation=operation,expected=bridge.flatten(after)))
        for building in model['buildings']:
            for porch in building.get('porches_detail',[]):
                operation=dict(op='move_room',building=building['id'],room=porch['id'],by=[2,3])
                after,_=ops.apply(model,operation);cases.append(dict(plan=bridge.flatten(model),operation=operation,expected=bridge.flatten(after)))
        operation=dict(op='move_wall',building='main-house',wall='separator-70',by=[0,-2])
        after,_=ops.apply(model,operation);cases.append(dict(plan=bridge.flatten(model),operation=operation,expected=bridge.flatten(after)))
        code,out=run_node(PRELUDE+r"""
const {applyLocal}=await import(file('static/twin/editor/local_ops.js'));
const {porchPosts}=await import(file('static/twin/porch_posts.js'));
const clean=plan=>plan.buildings.flatMap(b=>porchPosts(b).map(p=>({building:b.id,id:p.id,at:p.piece.at,size:p.piece.size})));
const withoutMint=(value,context='')=>Array.isArray(value)?value.map(v=>withoutMint(v,context)):
 value&&typeof value==='object'?Object.fromEntries(Object.entries(value).filter(([k])=>!(context==='columns'&&k==='id')).map(([k,v])=>[k,withoutMint(v,k)])):value;
for(const c of input.cases){const before=structuredClone(c.plan),result=applyLocal(c.plan,c.operation);assert.ok(result);
 const actual=clean(result.plan),expected=clean(c.expected);assert.equal(actual.length,expected.length);for(const [i,p] of expected.entries()){assert.equal(actual[i].id,p.id);assert.equal(actual[i].building,p.building);assert.equal(actual[i].size,p.size);for(let a=0;a<2;++a)assert.ok(Math.abs(actual[i].at[a]-p.at[a])<1e-8,JSON.stringify(c.operation)+':'+JSON.stringify([actual[i],p]));}assert.deepEqual(c.plan,before);
 if(!c.operation.op.startsWith('move_')&&!c.operation.ops?.some(m=>m.op.startsWith('move_')||m.op==='set_room_kind'))assert.deepEqual(withoutMint(result.plan),withoutMint(c.expected));
 if(!c.operation.op.startsWith('move_'))for(const p of porchPosts(result.plan.buildings[0]).filter(p=>!c.operation.porch||p.porchId===c.operation.porch))assert.ok(p.id.startsWith('post:')&&p.id.length<=120);
}
""",dict(root=ROOT.as_posix(),cases=cases))
        self.assertEqual(code,0,out)

    def test_pieces_parent_visibility_and_proxies(self):
        from test_twin_awning_golden_js import FIXTURE
        code,out=run_node(PRELUDE+FIXTURE+r"""
const G=await import(file('static/twin/twin_generator.js'));
const {porchPosts}=await import(file('static/twin/porch_posts.js'));
const {createPieceVisibility,visibilityKind}=await import(file('static/twin/twin_visibility.js'));
const {createVisibility}=await import(file('static/twin/editor/visibility.js'));
const plan=input.plan,b=plan.buildings[0],posts=porchPosts(b);
const out=G.buildTwin(plan,kit(),'high',{viewing:true});await out.ready;
for(const p of posts){const key=b.id+':'+p.id,proxy=out.pickObjects.get(key);assert.ok(proxy);
 assert.equal(proxy.userData.kind,'porch_post');assert.equal(proxy.userData.parentPieceId,p.porchId);
 for(const object of out.pieces.get(key)){
  const owners=object.userData.snapRanges?.filter(r=>r.pieceId===p.id)||[object.userData];assert.ok(owners.length);
  for(const owner of owners){assert.equal(owner.part,'column');assert.equal(owner.parentPieceId,p.porchId);}
 }
 const hidden=createPieceVisibility();hidden.set([p.porchId],[]);assert.ok(hidden.hidden(proxy.userData));
 hidden.set([p.id],[]);assert.ok(hidden.hidden(proxy.userData));
 assert.equal(visibilityKind('porch_post'),'room');
 const lock=createVisibility({storage:null});lock.lockKind('room');
 assert.equal(lock.isPickable(proxy.userData),false,'room layer locks include posts');
 lock.unlockKind('room');lock.lock(p.porchId);
 assert.ok(lock.isLocked(proxy.userData.parentPieceId),'the porch lock owner is retained for the UI half');
}
const upper=structuredClone(plan),ub=upper.buildings[0];
ub.levels.push({id:'L2',elevation:15,ceiling:10,outline:structuredClone(ub.rooms[0].polygon)});
ub.rooms[0].level='L2';ub.porches[0].floor=15;ub.porches[0].level='L2';
for(const s of ub.roof.sections){s.plate+=15;s.level='L2';}
for(const r of ub.roofs){r.plate+=15;r.level='L2';}
const up=G.buildTwin(upper,kit(),'high',{viewing:true});await up.ready;
const proxy=up.pickObjects.get(b.id+':'+posts[0].id);assert.equal(proxy.parent.userData.levelKey,b.id+':L1');
""",dict(root=ROOT.as_posix(),plan=bridge.flatten(patio())))
        self.assertEqual(code,0,out)

    def test_local_operations(self):
        code, out = run_node(PRELUDE + r"""
const {applyLocal}=await import(file('static/twin/editor/local_ops.js'));
const {porchPosts}=await import(file('static/twin/porch_posts.js'));
const {authoredGeometry}=await import(file('static/twin/bake/geometry_key.js'));
const original=structuredClone(input.plan), key=authoredGeometry(original);
let result=applyLocal(input.plan,{op:'update_porch_post',building:'pool-cottage',porch:'patio',post:'post:patio:0',at:[2,3]});
assert.ok(result);assert.deepEqual(porchPosts(result.plan.buildings[0])[0].piece.at,[2,3]);
const minted=structuredClone(original);minted.buildings[0].porches[0].columns.forEach((c,i)=>c.id='post:'+String(i).padStart(32,'0'));
assert.equal(authoredGeometry(minted),key);
assert.deepEqual(input.plan,original);
""", {'root':ROOT.as_posix(), 'plan':bridge.flatten(patio())})
        self.assertEqual(code, 0, out)

    def test_real_view_post_wins_and_parent_hide(self):
        from test_twin_yard_reuse_js import PREFIX
        from test_twin_awning_golden_js import FIXTURE
        code,out=run_node(PREFIX+FIXTURE+r"""
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const plan=input.plan,b=plan.buildings[0];b.roof.sections=[];b.roofs=[];
const host=new Element(),shell=new Element();shell.className='editor-shell';shell.append(host);
const v=await mountTwin(host,{plan,kit:kit(),tier:'high',bake:false,preserveCamera:true});
while(!v.ready)await new Promise(r=>setTimeout(r,1));
v.setPlanCamera(b.id+':L1');v.setView(b.id+':L1');
const pixel=v.screenOfFloor(1,1,b.id+':L1');
assert.equal(v.pick(...pixel)?.id,'post:patio:0');assert.equal(v.pick(...pixel)?.parentPieceId,'patio');
assert.equal(v.pickAll(...pixel)[0]?.id,'post:patio:0');assert.equal(v.pickAll(...pixel)[0]?.parentPieceId,'patio');
v.setSelection({selected:{kind:'room',id:'patio',building:b.id,level:'L1'},room:{id:'patio',building:b.id,level:'L1',allowed:['patio'],walls:[]}});
assert.equal(v.pickAll(...pixel)[0]?.id,'post:patio:0');
v.setHiddenPieces(['patio'],[]);assert.ok(v.pickAll(...pixel).every(p=>p.kind!=='porch_post'));
v.setHiddenPieces([],[]);
v.dispose();
""",dict(root=ROOT.as_posix(),plan=bridge.flatten(patio())))
        self.assertEqual(code,0,out)


if __name__ == '__main__': unittest.main()

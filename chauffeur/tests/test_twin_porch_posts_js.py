"""Runtime JS contract for posts, bake identity and local edits."""
from test_twin_porch_posts_model import ROOT, patio, bridge, unittest, household, command, ops, twin_model
import copy
import json
from twin_editor_dom import PRELUDE, run_node


class PostsJS(unittest.TestCase):
    def test_fix2_mounted_porch_settle_equals_fresh(self):
        from test_twin_view_settle_js import PREFIX
        from test_twin_house_save_stable import MemoryHouse
        from services import twin_edit
        def saved(model, operation):
            expected,_=ops.apply(model,operation)
            with MemoryHouse(model,persist=True):
                result=twin_edit.save(operation,'tester')['model']
            for b in bridge.flatten(expected)['buildings']:
                actual=next(v for v in bridge.flatten(result)['buildings'] if v['id']==b['id'])
                self.assertEqual([(r['id'],r['polygon']) for r in actual['rooms']],[(r['id'],r['polygon']) for r in b['rooms']])
                self.assertEqual([(p['id'],p.get('columns',[])) for p in actual.get('porches',[])],[(p['id'],p.get('columns',[])) for p in b.get('porches',[])])
            return result
        model=twin_model.normalize(household())[0]; cases=[]
        for bid,wall,by in [('main-house','separator-73',-2),('main-house','separator-73',2),('pool-house',None,[2,0])]:
            b=next(b for b in model['buildings'] if b['id']==bid)
            if wall is None:
                positions={j['id']:j['at'] for j in b['joints']}
                wall=next(w['id'] for w in b['walls'] if all(abs(positions[j][0]-38)<.01 for j in w['joints']))
            operation=dict(op='move_wall',building=bid,wall=wall,by=by)
            after=saved(model,operation)
            cases.append(dict(operation=operation,after=bridge.flatten(after)))
        gutter_model=copy.deepcopy(model);b=gutter_model['buildings'][0]
        porch=next(p for p in b['porches_detail'] if p['id'].startswith('porch:0af'))
        porch['gutter']=True
        porch['columns'][0]['at']=[14.33,66]
        porch['columns'][-1]['at']=[30.67,66]
        operation=dict(op='move_wall',building=b['id'],wall='separator-73',by=-2)
        after=saved(gutter_model,operation)
        cases.append(dict(operation=operation,plan=bridge.flatten(gutter_model),after=bridge.flatten(after),postSpout=True))
        def run_mounted(driver,payload,timeout):
            import subprocess
            try:return run_node(driver,payload,timeout=timeout)
            except subprocess.TimeoutExpired as error:self.fail(str(error.stdout)+str(error.stderr))
        code,out=run_mounted(PREFIX+r"""
globalThis.generations=0;globalThis.bakeStarts=0;globalThis.yardCalls=0;globalThis.__THREE_MESH=T.Mesh;globalThis.__THREE_BOX=T.BoxGeometry;globalThis.__THREE_STD=T.MeshStandardMaterial;
const {moveGesture,movePreview}=await import(file('static/twin/editor/local_ops.js'));
const parts=(out,bid)=>{const rows={};out.root.traverse(object=>{
 if(!object.isMesh||object.layers.isEnabled(31)||!object.geometry?.attributes.position)return;
 const p=object.geometry.attributes.position,ranges=object.userData.snapRanges||[{...object.userData,start:0,count:p.count}];
 for(const r of ranges){const id=r.parentPieceId||r.pieceId;
 if(r.buildingId!==bid||!id?.startsWith('porch:'))continue;
 const part=r.part||r.bakePart||'floor',key=id+':'+part,row=rows[key]||={triangles:0,min:Infinity,max:-Infinity};
 row.triangles+=r.count/3;for(let i=r.start;i<r.start+r.count;i++){row.min=Math.min(row.min,p.getY(i));row.max=Math.max(row.max,p.getY(i));}
 }});return rows;};
for(const c of input.cases){const plan=structuredClone(c.plan||input.plan),host=new Element(),shell=new Element();shell.className='editor-shell';shell.append(host);
const v=await mountTwin(host,{plan,kit,tier:'low',bake:false});try{
 const before=globalThis.lastTwin,other=plan.buildings.find(b=>b.id!==c.operation.building).id,retained=before.buildings.get(other).model;
 const gesture=moveGesture(plan,{kind:'wall',building:c.operation.building,id:c.operation.wall}),by=Array.isArray(c.operation.by)?c.operation.by:gesture.normal.map(v=>v*c.operation.by);
 const preview=movePreview(plan,gesture,by);v.rebuildLevel(c.operation.building,gesture.piece.level,preview,gesture.touched);
 // Settle can receive exactly the plan already drawn by the last preview.
 v.rebuildLevel(c.operation.building,gesture.piece.level,c.after,gesture.touched);
const result=await v.settle(c.after,{buildingId:c.operation.building,levelId:gesture.piece.level,touched:gesture.touched});
assert.equal(result.path,'rebuild','porch must regenerate after the preview');
 const settled=globalThis.lastTwin,fresh=buildTwin(structuredClone(c.after),kit,'low',{viewing:false});await fresh.ready;
 console.log('FIX2_REUSE '+JSON.stringify({other,same:settled.buildings.get(other).model===retained,degraded:retained.degraded,rebuilt:settled.buildingsRebuilt,reused:settled.buildingsReused}));
 if(!retained.degraded)assert.ok(settled.buildings.get(other).model===retained,'reuse the other building when its assets are healthy');
 assert.deepEqual(parts(settled,c.operation.building),parts(fresh,c.operation.building),'parts triangles and heights');
 assert.deepEqual(JSON.parse(JSON.stringify(settled.gutters)),JSON.parse(JSON.stringify(fresh.gutters)),'downspouts match fresh placement');
 if(c.postSpout){const spouts=settled.gutters.spouts.filter(s=>s.mount==='post' && s.edge.porch?.startsWith('porch:0af'));assert.ok(spouts.length,'downspout mounted on followed porch post');console.log('FIX2_POST_SPOUTS '+spouts.length);}
 console.log('FIX2_SETTLE '+JSON.stringify({building:c.operation.building,by:c.operation.by,parts:parts(settled,c.operation.building)}));
 }finally{v.dispose();}}
finish();
""",dict(root=ROOT.as_posix(),plan=bridge.flatten(model),cases=cases),timeout=180)
        self.assertEqual(code,0,out);print(out)

    def test_fix2_split_then_pull_follow(self):
        base=twin_model.normalize(household(),preserve_room_polygons=True)[0]
        b=next(b for b in base['buildings'] if b['id']=='pool-house');p=b['porches_detail'][0]
        p['columns']=[dict(at=[37.67,5.5],size=.67),dict(at=[37.67,16.5],size=.67)]
        positions={j['id']:j['at'] for j in b['joints']}
        wall=next(w for w in b['walls'] if all(abs(positions[j][0]-38)<.01 for j in w['joints']))
        import math
        split,_=ops.apply(base,dict(op='split_wall',building=b['id'],wall=wall['id'],at=11))
        sb=next(v for v in split['buildings'] if v['id']==b['id']);positions={j['id']:j['at'] for j in sb['joints']}
        upper=next(w for w in sb['walls'] if all(abs(positions[j][0]-38)<.01 for j in w['joints']) and max(positions[j][1] for j in w['joints'])>21 and min(positions[j][1] for j in w['joints'])>10)
        middle=next(j for j in sb['joints'] if math.dist(j['at'],[38,11])<.01)
        cases=[]
        for operation,expected_x in [(dict(op='move_wall',building=b['id'],wall=upper['id'],by=[3,0]),[39.17,40.67]),(dict(op='move_joint',building=b['id'],joint=middle['id'],to=[41,11]),[39.17,39.17])]:
            after,_=ops.apply(split,operation);columns=next(v for v in after['buildings'] if v['id']==b['id'])['porches_detail'][0]['columns']
            for c,x in zip(columns,expected_x):self.assertAlmostEqual(c['at'][0],x)
            cases.append(dict(operation=operation,expected=bridge.flatten(after)))
        code,out=run_node(PRELUDE+r"""
const {applyLocal}=await import(file('static/twin/editor/local_ops.js'));
for(const c of input.cases){const local=applyLocal(input.plan,c.operation);assert.ok(local);const a=local.plan.buildings.find(b=>b.id==='pool-house').porches[0].columns,b=c.expected.buildings.find(b=>b.id==='pool-house').porches[0].columns;
 for(let i=0;i<a.length;i++)for(let axis=0;axis<2;axis++)assert.ok(Math.abs(a[i].at[axis]-b[i].at[axis])<1e-8,JSON.stringify([c.operation,a,b]));
 const polygon=local.plan.buildings.find(b=>b.id==='pool-house').rooms.find(r=>r.kind==='porch').polygon;assert.ok(polygon.some(p=>Math.hypot(p[0]-41,p[1]-11)<.01),'split joint stays in the preview cycle');}
""",dict(root=ROOT.as_posix(),plan=bridge.flatten(split),cases=cases))
        self.assertEqual(code,0,out)

    def test_fix2_household_split_pull_sweep(self):
        import math
        model=twin_model.normalize(household(),preserve_room_polygons=True)[0];cases=[];refused=0;accepted=0
        for b in model['buildings']:
            positions={j['id']:j['at'] for j in b['joints']}
            for wall in b['walls']:
                split_op=dict(op='split_wall',building=b['id'],wall=wall['id'],at=math.dist(*(positions[j] for j in wall['joints']))/2)
                try:split,_=ops.apply(model,split_op)
                except ops.Refused:refused+=1;continue
                sb=next(v for v in split['buildings'] if v['id']==b['id']);old_ids={w['id'] for w in b['walls']}
                halves=[w for w in sb['walls'] if w['id']==wall['id'] or w['id'] not in old_ids]
                group=dict(split=split_op,plan=bridge.flatten(split),moves=[])
                for half in halves:
                    for sign in (-1,1):
                        operation=dict(op='move_wall',building=b['id'],wall=half['id'],by=sign)
                        try:after,_=ops.apply(split,operation)
                        except ops.Refused:refused+=1;continue
                        for prior in sb.get('porches_detail',[]):
                            target=next(v for v in after['buildings'] if v['id']==b['id'])
                            post=next(p for p in target['porches_detail'] if p['id']==prior['id'])
                            for c,d in zip(prior.get('columns',[]),post.get('columns',[])):
                                self.assertLessEqual(math.dist(c['at'],d['at']),1.000001,(operation,c,d))
                        flat=bridge.flatten(after)
                        group['moves'].append(dict(operation=operation,expected=[dict(id=v['id'],porches=v.get('porches',[])) for v in flat['buildings']]))
                        accepted+=1
                cases.append(group)
        code,out=run_node(PRELUDE+r"""
const {applyLocal}=await import(file('static/twin/editor/local_ops.js'));let localSplits=0,openingDeclines=0,compared=0;
for(const c of input.cases){const split=applyLocal(input.plan,c.split);if(split)localSplits++;else{const b=input.plan.buildings.find(b=>b.id===c.split.building);assert.ok(b.openings.some(o=>o.wall===c.split.wall&&Math.abs(o.at-c.split.at)<o.width/2-1e-9));openingDeclines++;}
 for(const move of c.moves){for(const plan of [c.plan,...(split?[split.plan]:[])]){
 const serverBuilding=c.plan.buildings.find(b=>b.id===move.operation.building),target=serverBuilding.walls.find(w=>w.id===move.operation.wall),b=plan.buildings.find(b=>b.id===move.operation.building);
 const wall=b.walls.find(w=>Math.hypot(w.from[0]-target.from[0],w.from[1]-target.from[1])<.01&&Math.hypot(w.to[0]-target.to[0],w.to[1]-target.to[1])<.01);
 assert.ok(wall,JSON.stringify(move.operation));const result=applyLocal(plan,{...move.operation,wall:wall.id});assert.ok(result);compared++;
 for(const e of move.expected)for(const p of e.porches){const columns=result.plan.buildings.find(b=>b.id===e.id).porches.find(v=>v.id===p.id).columns;assert.equal(columns.length,p.columns.length);
 for(let i=0;i<columns.length;i++)for(let axis=0;axis<2;axis++)assert.ok(Math.abs(columns[i].at[axis]-p.columns[i].at[axis])<1e-8,JSON.stringify({split:c.split,move:move.operation,post:i,columns,expected:p.columns}));}
 }}}
console.log('FIX2_SPLIT_PULL_SWEEP '+JSON.stringify({splits:input.cases.length,localSplits,openingDeclines,acceptedMoves:input.accepted,refused:input.refused,localComparisons:compared}));
""",dict(root=ROOT.as_posix(),plan=bridge.flatten(model),cases=cases,accepted=accepted,refused=refused),timeout=180)
        self.assertEqual(code,0,out);print(out)

    def test_fix2_room_move_sweep_against_main(self):
        import subprocess,re
        model=twin_model.normalize(household(),preserve_room_polygons=True)[0];cases=[];refused=0;attempted=0
        for b in model['buildings']:
            operations=[]
            for w in b['walls']:
                operations.extend(dict(op='move_wall',building=b['id'],wall=w['id'],by=sign) for sign in (-1,1))
            for j in b['joints']:
                for axis in (0,1):
                    for sign in (-1,1):
                        point=list(j['at']);point[axis]+=sign
                        operations.append(dict(op='move_joint',building=b['id'],joint=j['id'],to=point))
            for r in b['rooms']:
                operations.extend(dict(op='move_room',building=b['id'],room=r['id'],by=[sign,sign]) for sign in (-1,1))
            for operation in operations:
                attempted+=1
                try:after,_=ops.apply(model,operation)
                except ops.Refused:refused+=1;continue
                flat=bridge.flatten(after)
                cases.append(dict(operation=operation,rooms=[dict(building=v['id'],rooms=[dict(id=r['id'],polygon=r['polygon']) for r in v['rooms']]) for v in flat['buildings']]))
        def source(ref):
            value=subprocess.check_output(['git','show',ref+':chauffeur/static/twin/editor/local_ops.js'],cwd=ROOT,text=True,encoding='utf-8')
            return re.sub(r"(from\s*['\"])(\.[^'\"]+)(['\"])",lambda m:m[1]+(ROOT/'static/twin/editor'/m[2]).resolve().as_uri()+m[3],value)
        code,out=run_node(PRELUDE+r"""
const {applyLocal}=await import(file('static/twin/editor/local_ops.js'));
const baseline=await import('data:text/javascript;base64,'+Buffer.from(input.mainLocal).toString('base64'));
const reviewed=await import('data:text/javascript;base64,'+Buffer.from(input.reviewedLocal).toString('base64'));
const project=(p,a,b)=>{const d=[b[0]-a[0],b[1]-a[1]],l=d[0]**2+d[1]**2,t=l?Math.max(0,Math.min(1,((p[0]-a[0])*d[0]+(p[1]-a[1])*d[1])/l)):0;return Math.hypot(p[0]-a[0]-t*d[0],p[1]-a[1]-t*d[1]);};
const shape=(a,b)=>Math.max(...[[a,b],[b,a]].flatMap(([p,q])=>p.flatMap((v,i)=>[v,[(v[0]+p[(i+1)%p.length][0])/2,(v[1]+p[(i+1)%p.length][1])/2]]).map(v=>Math.min(...q.map((w,i)=>project(v,w,q[(i+1)%q.length]))))));
let compared=0,worse=0,oldWorse=0,maxError=0;
for(const c of input.cases){const current=applyLocal(input.plan,c.operation),main=baseline.applyLocal(input.plan,c.operation),old=reviewed.applyLocal(input.plan,c.operation);assert.ok(current);assert.ok(main);
 for(const e of c.rooms){const a=current.plan.buildings.find(b=>b.id===e.building),m=main.plan.buildings.find(b=>b.id===e.building),o=old.plan.buildings.find(b=>b.id===e.building);
 for(const room of e.rooms){const local=a.rooms.find(r=>r.id===room.id),prior=m.rooms.find(r=>r.id===room.id),review=o.rooms.find(r=>r.id===room.id);if(!local||!prior)continue;
 const error=shape(local.polygon,room.polygon),mainError=shape(prior.polygon,room.polygon);compared++;maxError=Math.max(maxError,error);
 if(error>mainError+1e-8)worse++;if(shape(review.polygon,room.polygon)>mainError+1e-8)oldWorse++;
 assert.ok(error<=mainError+1e-8,JSON.stringify({op:c.operation,room:room.id,error,mainError}));}}}
console.log('FIX2_ROOM_SWEEP '+JSON.stringify({attempted:input.attempted,accepted:input.cases.length,refused:input.refused,roomComparisons:compared,worseThanMain:worse,reviewedWorseThanMain:oldWorse,maxError}));
""",dict(root=ROOT.as_posix(),plan=bridge.flatten(model),cases=cases,attempted=attempted,refused=refused,mainLocal=source('main'),reviewedLocal=source('0958de67')),timeout=180)
        self.assertEqual(code,0,out);print(out)

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
for(const c of input.cases){const result=applyLocal(input.plan,c.operation);
 if(!result){const b=input.plan.buildings.find(b=>b.id===c.operation.building);assert.ok(b.openings.some(o=>o.wall===c.operation.wall&&Math.abs(o.at-c.operation.at)<o.width/2-1e-9));continue;}
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
assert.equal(hits[0].id,'in-front');assert.equal(v.pick(...pixel)?.id,'in-front');assert.equal(hits[1].kind,'porch_post');assert.equal(hits[2].id,'patio');v.dispose();
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
const collision=structuredClone(original);collision.buildings[0].porches[0].columns[1].id='post:patio:0';const untouched=structuredClone(collision);
assert.equal(applyLocal(collision,{op:'update_porch_post',building:'pool-cottage',porch:'patio',post:'post:patio:0',size:.6}),null);assert.deepEqual(collision,untouched);
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
v.setSelection({selected:{kind:'porch_post',id:'post:patio:0',building:b.id,level:'L1'},room:{id:'patio',building:b.id,level:'L1',allowed:['post:patio:0'],walls:[]}});
assert.ok(v.pickAll(...pixel).every(p=>p.id!=='patio'),'excluded parent is not synthesized');
v.setHiddenPieces(['patio'],[]);assert.ok(v.pickAll(...pixel).every(p=>p.kind!=='porch_post'));
v.setHiddenPieces([],[]);
v.dispose();
""",dict(root=ROOT.as_posix(),plan=bridge.flatten(patio())))
        self.assertEqual(code,0,out)


if __name__ == '__main__': unittest.main()

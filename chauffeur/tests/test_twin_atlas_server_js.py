"""Execute binary transport and loadAtlas with the shared real-module Node harness."""
import sys
import test_twin_lightmap_material_js as M

DRIVER = r"""
const A = await import(file('static/twin/bake/atlas_transport.js'));
const tick = () => new Promise(resolve => setImmediate(resolve));
const until = async fn => { for (let i=0; i<2000 && !fn(); i++) await new Promise(r => setTimeout(r, 1)); assert.ok(fn(), 'async publication finished'); };
function small() {
  const root = new THREE.Group(), mesh = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshStandardMaterial({name:'wall'}));
  mesh.userData.merged = true; root.add(mesh); root.updateMatrixWorld(true); return root;
}
function dataFor(root) {
  const input = A.atlasJob(root, job.plan, job.layout);
  return {key:'abcdef0123456789', uvKey:input.uvKey, room:{pages:1, rooms:[], plan:job.plan, charts:[]},
    geometries:A.covered(root).map(m => A.geometryData(m.geometry))};
}
const options = extra => ({indexedDB:null, apply:false, ...extra});
let passed=0;
async function test(name, fn) { await fn(); passed++; console.log('  ok  '+name); }

await test('container_exact_plain_and_gzip', async () => {
  const floats = new Float32Array([999, -0, NaN, Infinity, -1.25, 999]).subarray(1,5);
  const data = {key:'1234', uvKey:'base', room:{pages:2, rooms:[{name:'Living ♥'}], plan:{nested:[1,2]}, charts:[{faces:new Uint32Array([0,70000])}]},
    geometries:[{attributes:{position:{array:floats,itemSize:2,normalized:false}, color:{array:new Uint16Array([1,65535]),itemSize:1,normalized:true}},
      index:new Uint32Array([0,70000,4294967295]), userData:{nested:[null, {type:'Float32Array',offset:8,length:4}],label:'屋'}},
      {attributes:{empty:{array:new Float32Array(0),itemSize:1,normalized:false}},index:null,userData:{flag:true}},
      {attributes:{},index:new Uint16Array([0,65535]),userData:{}}]};
  for (const compress of [false,true]) {
    const bytes = await A.encodeAtlas(data, {compress}), back = await A.decodeAtlas(bytes);
    assert.deepEqual(back,data);
    const array = back.geometries[0].attributes.position.array;
    assert.deepEqual(new Uint8Array(array.buffer),new Uint8Array(floats.buffer,floats.byteOffset,floats.byteLength));
    if(compress) assert.deepEqual([...bytes.slice(0,2)],[31,139]);
  }
  const compression = globalThis.CompressionStream; globalThis.CompressionStream = undefined;
  try { assert.deepEqual(await A.decodeAtlas(await A.encodeAtlas(data)),data); } finally { globalThis.CompressionStream = compression; }
  const aborted = new AbortController(); aborted.abort();
  await assert.rejects(A.encodeAtlas(data,{signal:aborted.signal}),/cancelled/);
  await assert.rejects(A.decodeAtlas(new Uint8Array(8),{signal:aborted.signal}),/cancelled/);
  await assert.rejects(A.decodeAtlas(new Uint8Array(8)),/Invalid atlas/);
  await assert.rejects(A.decodeAtlas((await A.encodeAtlas(data,{compress:false})).slice(0,-1)),/Invalid atlas array/);
});

await test('server_hit_then_indexeddb_hit_and_cached_desk_upload', async () => {
  const root=small(), data=dataFor(root), bytes=await A.encodeAtlas(data), idb=fakeIndexedDB(), calls=[];
  const expected = window.chfBase+'api/house/atlases/'+A.atlasJob(root,job.plan,job.layout).cacheKey;
  class NeverWorker { constructor(){throw new Error('server hit started a worker');} }
  const fetch = async (url, init={}) => { calls.push([url,init]); return init.method==='PUT' ? new Response('') : new Response(bytes); };
  const first = await M.loadAtlas(root,job.plan,job.layout,options({fetch,indexedDB:idb,Worker:NeverWorker}));
  assert.equal(first.key,data.key); assert.equal(calls.length,1); assert.equal(calls[0][0],expected);
  assert.equal(first.apply().key,data.key,'downloaded geometry is applied through the real transport');
  assert.deepEqual(A.geometryData(A.covered(root)[0].geometry),data.geometries[0]);
  const second = await M.loadAtlas(small(),job.plan,job.layout,options({fetch,indexedDB:idb,Worker:NeverWorker}));
  assert.equal(second.key,data.key);
  await until(()=>calls.length===2);
  assert.equal(calls[1][0],expected); assert.equal(calls[1][1].method,'PUT'); assert.equal(calls[1][1].chfQuietAuth,true);
  assert.deepEqual(await A.decodeAtlas(calls[1][1].body),data);
  const db=await new Promise(resolve=>{const r=idb.open('twin-lightmap-atlases',1);r.onsuccess=()=>resolve(r.result);});
  const get = key => new Promise(resolve=>{const r=db.transaction('atlases').objectStore('atlases').get(key);r.onsuccess=()=>resolve(r.result);});
  assert.equal(await get('input:'+expected.split('/').at(-1)),data.key);
  assert.deepEqual(await get(data.key),data); db.close();
});

await test('server_miss_worker_upload_and_quiet_failures', async () => {
  const root=small(),data=dataFor(root), calls=[], warnings=[]; let workers=0;
  class Worker { constructor(){workers++;} postMessage(input){assert.ok(input.cacheKey);setImmediate(()=>this.onmessage({data:structuredClone(data)}));} terminate(){} }
  const warn=console.warn;console.warn=(...args)=>warnings.push(args);
  try {
    for(const status of [403,500,500,'network']) {
      const fetch=async(url,init={})=>{calls.push(init);if(init.method!=='PUT')return new Response('',{status:404});if(status==='network')throw new Error('offline');return new Response('',{status});};
      const got=await M.loadAtlas(small(),job.plan,job.layout,options({fetch,Worker}));assert.equal(got.key,data.key);
      const n=workers;await until(()=>calls.filter(c=>c.method==='PUT').length===n); await tick();
      if(status===403)assert.equal(warnings.length,0,'forbidden publication is silent');
      assert.deepEqual(await A.decodeAtlas(calls.at(-1).body),data,'worker result is uploaded exactly');
    }
    assert.equal(workers,4); assert.equal(warnings.length,1,'publication errors reported once');
  }finally{console.warn=warn;}
});

await test('coarse_source_never_publishes_and_cannot_poison_a_fine_local_cache', async () => {
  const field=step=>{const root=small(),g=root.children[0].geometry;
    g.userData.bakeHeightfield=true;g.userData.bakeTerrainStep=step;return root;};
  const coarse=field(2),fine=field(1),idb=fakeIndexedDB(),calls=[];let workers=0;
  assert.equal(A.atlasJob(coarse,job.plan,job.layout).cacheKey,A.atlasJob(fine,job.plan,job.layout).cacheKey,
    'terrain step must not change the shared cache or bake namespace');
  class Worker {postMessage(input){workers++;const data=dataFor(input.terrainStep===2?field(2):field(1));
    setImmediate(()=>this.onmessage({data}));}terminate(){}}
  const fetch=async(url,init={})=>{calls.push(init.method||'GET');return new Response('',{status:init.method==='PUT'?200:404});};
  const run=root=>M.loadAtlas(root,job.plan,job.layout,options({indexedDB:idb,Worker,fetch}));
  const low=await run(coarse);await tick();assert.equal(workers,1);assert.ok(!calls.includes('PUT'));
  await run(field(2));await tick();assert.equal(workers,1,'Low reuses its own local copy');
  assert.ok(!calls.includes('PUT'),'a Low local hit must not publish either');
  const high=await run(fine);assert.equal(high.key,low.key,'local partition leaves the bake key alone');
  await until(()=>calls.includes('PUT'));assert.equal(workers,2,'High cannot read the Low copy');
  await run(field(2));await tick();assert.equal(workers,2,'High cannot overwrite Low local geometry');
});

await test('coarse_source_can_read_a_shared_fine_atlas_without_publishing_it', async () => {
  const root=small();Object.assign(root.children[0].geometry.userData,{bakeHeightfield:true,bakeTerrainStep:2});
  const data=dataFor(root),bytes=await A.encodeAtlas(data),idb=fakeIndexedDB(),calls=[];
  class NeverWorker {constructor(){throw new Error('shared hit must not start a worker');}}
  const fetch=async(url,init={})=>{calls.push(init.method||'GET');return new Response(bytes);};
  for(let i=0;i<2;i++)await M.loadAtlas(root,job.plan,job.layout,options({fetch,indexedDB:idb,Worker:NeverWorker}));
  await tick();assert.deepEqual(calls,['GET'],'Low may read shared geometry, but never publish');
});

await test('incompatible_or_corrupt_server_copy_falls_back_to_worker', async () => {
  const data=dataFor(small());let jobs=0;
  class Worker {postMessage(){jobs++;setImmediate(()=>this.onmessage({data:structuredClone(data)}));}terminate(){}}
  for(const bytes of [await A.encodeAtlas({...data,uvKey:'other base UV'}),new Uint8Array([1,2,3])]) {
    let uploaded=false;
    const fetch=async(url,init={})=>{if(init.method==='PUT'){uploaded=true;return new Response('');}return new Response(bytes);};
    const result=await M.loadAtlas(small(),job.plan,job.layout,options({fetch,Worker}));
    assert.equal(result.key,data.key);await until(()=>uploaded);
  }
  assert.equal(jobs,2);
});

await test('cancellation_at_idb_server_decode_worker_and_deferred_apply', async () => {
  let closed=false, opening;
  const ctrl=new AbortController();
  const pending=M.loadAtlas(small(),job.plan,job.layout,options({signal:ctrl.signal,indexedDB:{open(){return opening={};}}}));
  ctrl.abort(); await assert.rejects(pending,/cancelled/);
  opening.result={close(){closed=true;}};opening.onsuccess();await tick();assert.ok(closed);
  let fetched=false;const c=new AbortController();
  const waiting=M.loadAtlas(small(),job.plan,job.layout,options({signal:c.signal,fetch:()=>{fetched=true;return new Promise(()=>{});}}));
  await until(()=>fetched);c.abort();await assert.rejects(waiting,/cancelled/);
  const d=new AbortController();
  await assert.rejects(M.loadAtlas(small(),job.plan,job.layout,options({signal:d.signal,fetch:async()=>({ok:true,arrayBuffer:async()=>{d.abort();return new ArrayBuffer(0);}})})),/cancelled/);
  let worker;const e=new AbortController();
  class Held {constructor(){worker=this;}postMessage(){}terminate(){this.terminated=true;}}
  const working=M.loadAtlas(small(),job.plan,job.layout,options({signal:e.signal,fetch:async()=>new Response('',{status:404}),Worker:Held}));
  await until(()=>worker);e.abort();await assert.rejects(working,/cancelled/);assert.ok(worker.terminated);
  const f=new AbortController(),data=dataFor(small()),bytes=await A.encodeAtlas(data);
  const result=await M.loadAtlas(small(),job.plan,job.layout,options({signal:f.signal,fetch:async()=>new Response(bytes)}));
  f.abort();assert.throws(()=>result.apply(),/cancelled/);
});

await test('long_worker_survives_30s_and_silent_worker_is_bounded', async () => {
  const set=globalThis.setTimeout,clear=globalThis.clearTimeout,timers=new Map();let now=0,worker;
  globalThis.setTimeout=(fn,ms)=>{if(ms!==M.ATLAS_TIMEOUT_MS)return set(fn,ms);const id={};timers.set(id,{fn,at:now+ms});return id;};
  globalThis.clearTimeout=id=>{if(!timers.delete(id))clear(id);};
  const advance=ms=>{now+=ms;for(const[id,t]of timers)if(t.at<=now){timers.delete(id);t.fn();}};
  class Held {constructor(){worker=this;}postMessage(){}terminate(){this.terminated=true;}}
  const fetch=async()=>new Response('',{status:404});
  try {
    assert.equal(M.ATLAS_TIMEOUT_MS,600000);
    const abort=new AbortController();
    const result=M.loadAtlas(small(),job.plan,job.layout,options({fetch,Worker:Held,signal:abort.signal}));
    await until(()=>timers.size===1);const good=worker;advance(45000);assert.ok(!good.terminated,'legitimate layout outlives 30 seconds');
    good.onmessage({data:dataFor(small())});await result;abort.abort();assert.ok(good.terminated);assert.equal(timers.size,0);
    const silent=M.loadAtlas(small(),job.plan,job.layout,options({fetch,Worker:Held}));
    const rejected=assert.rejects(silent,/timed out after 10 minutes/);
    await until(()=>timers.size===1);advance(600000);await rejected;assert.ok(worker.terminated);assert.equal(timers.size,0);
  }finally{globalThis.setTimeout=set;globalThis.clearTimeout=clear;}
});

await test('optional_upload_403_does_not_reopen_admin_gate', async () => {
  const text=readFileSync(job.root+'/templates/nav.html','utf8');
  const start=text.indexOf('(function attachDeviceToken()'),end=text.indexOf('})();',start)+5;
  let refused=0; const old=globalThis.localStorage;
  globalThis.localStorage={getItem(){return '';}};
  window.location={origin:'http://localhost'};window.chfAdminRefused=()=>refused++;
  window.fetch=async()=>new Response('',{status:403,headers:{'X-Auth-Refusal':'parent'}});
  try {
    (0,eval)(text.slice(start,end));
    await window.fetch('../api/house/atlases/key',{method:'PUT',chfQuietAuth:true});assert.equal(refused,0);
    await window.fetch('../api/house/atlases/key',{method:'PUT'});assert.equal(refused,1,'ordinary auth gate still runs');
  } finally {globalThis.localStorage=old;}
});
console.log(`${passed}/${passed} passed`);process.exit(0);
"""

if __name__ == '__main__':
    M.DRIVER = M.DRIVER[:M.DRIVER.index('const checks = [];')] + DRIVER
    sys.exit(M.run())

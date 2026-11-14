"""Library Browse panel: online search, resolution pick, Add and the download job.

Runs the real browse.js and page.js under node with the fake DOM. The server is
faked at the page's api() seam; one test drives the real libraryApi through
fetch to prove a refused request carries its HTTP status.
"""
import sys
from pathlib import Path
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const THREE=await import('three');
THREE.TextureLoader.prototype.load=function(url,done){const t=new THREE.Texture({width:32,height:32});queueMicrotask(()=>done(t));return t;};
const {mountLibraryPage,libraryApi}=await import(file('static/twin/library_page/page.js'));
const {pickResolution}=await import(file('static/twin/library_page/browse.js'));
const clone=x=>structuredClone(x), pause=ms=>new Promise(r=>setTimeout(r,ms));
const edit=(input,type,fields)=>{Object.assign(input,fields);return fire(input,type);};
const params={tint:'#ffffff',roughness:null,metalness:null,normal_scale:1,normal_convention:'gl',ao_intensity:1,tile_ft:[4,4],rotation_deg:0,random_offset:false};
const record=(id,source='user')=>({id,name:id,source,revision:1,maps:{},params:clone(params),licence:'CC0',source_snapshot:null});
const fail=(status,detail)=>Object.assign(new Error(detail),{status});
const ROWS={
 polyhaven:[
  {source:'polyhaven',source_id:'red_brick',name:'Red Brick',thumbnail:'api/house/materials/sources/polyhaven/red_brick/thumb',resolutions:['1k','2k','4k'],source_url:'https://polyhaven.com/a/red_brick'},
  {source:'polyhaven',source_id:'big_brick',name:'Big Brick',thumbnail:'api/house/materials/sources/polyhaven/big_brick/thumb',resolutions:['4k','8k'],source_url:'https://polyhaven.com/a/big_brick'}],
 ambientcg:[
  {source:'ambientcg',source_id:'Bricks059',name:'Bricks 059',thumbnail:'api/house/materials/sources/ambientcg/Bricks059/thumb',resolutions:['1k','4k'],source_url:'https://ambientcg.com/view?id=Bricks059'}]};
// hooks: search(source,q) -> rows | throws; download(body) -> {job_id} | throws; job(n) -> job | throws
async function setup(hooks={}){
 window.chfBase='/api/hassio_ingress/tok/';window.chfAuthUrl=u=>u+'?member_token=t';
 const host=document.createElement('main');document.body.append(host);
 const calls=[],alerts=[];let library=[record('material-test'),record('brick','builtin')],polls=0;
 window.showGlobalAlert=t=>alerts.push(t);window.promptConfirm=async()=>true;
 for(const name of ['alert','confirm','prompt'])window[name]=()=>{throw Error('browser dialog');};
 const api=async(path,method='GET',body)=>{
  calls.push({path,method,body:clone(body),at:Date.now()});
  let m;
  if((m=path.match(/^materials\/sources\/(\w+)\?q=(.*)$/))){
   const q=decodeURIComponent(m[2]);
   return {results:hooks.search?await hooks.search(m[1],q):ROWS[m[1]].filter(r=>r.name.toLowerCase().includes(q.toLowerCase()))};
  }
  if(path.endsWith('/download')&&method==='POST')return hooks.download?await hooks.download(body):{job_id:'job-1'};
  if(path.startsWith('materials/jobs/')){const job=await hooks.job(++polls,path);if(job.state==='done')library.push(record(job.material_id,'polyhaven'));return job;}
  if(path==='materials'&&method==='GET')return {materials:clone(library)};
  const found=library.find(r=>path==='materials/'+encodeURIComponent(r.id));
  if(found&&method==='GET')return clone(found);
  if(method==='PATCH'){const id=path.split('/')[1];return clone(library.find(r=>r.id===id));}
  throw fail(404,'unexpected '+method+' '+path);
 };
 location.search='?material=material-test';
 const page=mountLibraryPage(host,{api});await page.ready;tick();
 const q=sel=>host.querySelector(sel);
 const searches=()=>calls.filter(c=>c.path.startsWith('materials/sources/')&&c.method==='GET'&&!c.path.endsWith('/thumb'));
 const card=key=>q(`[data-browse-result="${key}"]`);
 async function openBrowse(){await click(q('[data-action="browse"]'));await pause(5);}
 return {host,page,calls,alerts,q,searches,card,openBrowse};
}

await test('search_debounced_once',async()=>{
 const c=await setup();const panel=c.q('[data-library-browse]');
 assert.equal(panel.hidden,true,'Browse starts closed');
 await c.openBrowse();assert.equal(panel.hidden,false);
 assert.equal(c.q('[data-action="browse"]').getAttribute('aria-expanded'),'true');
 assert.deepEqual(c.searches().map(x=>x.path),['materials/sources/polyhaven?q='],'opening searches the default source once');
 const box=c.q('[data-browse-search]');
 for(const value of ['b','br','bri','brick']){await edit(box,'input',{value});await pause(60);}
 await pause(150);assert.equal(c.searches().length,1,'no search while typing');
 await pause(150);
 assert.deepEqual(c.searches().map(x=>x.path),['materials/sources/polyhaven?q=','materials/sources/polyhaven?q=brick']);
 // Results: proxied thumbnail under ingress, source + licence link, per-row resolution.
 const red=c.card('polyhaven:red_brick');assert.ok(red,'result card drawn: ');
 assert.equal(red.querySelector('img').src,'/api/hassio_ingress/tok/api/house/materials/sources/polyhaven/red_brick/thumb?member_token=t');
 const link=red.querySelector('a');assert.equal(link.href,'https://polyhaven.com/a/red_brick');
 assert.equal(link.getAttribute('target'),'_blank');assert.match(link.getAttribute('rel'),/noopener/);
 assert.match(textOf(red),/Red Brick/);assert.match(textOf(red),/Poly Haven/);assert.match(textOf(red),/CC0/);
 const res=red.querySelector('select[data-resolution]');
 assert.deepEqual(res.querySelectorAll('option').map(o=>o.value),['1k','2k','4k']);assert.equal(res.value,'2k');
 assert.equal(c.card('polyhaven:big_brick').querySelector('select[data-resolution]').value,'4k','nearest offered when 2k is missing');
 // Switching source searches at once with the same words.
 await click(c.q('[data-browse-source="ambientcg"]'));await pause(5);
 assert.equal(c.searches().at(-1).path,'materials/sources/ambientcg?q=brick');assert.equal(c.searches().length,3);
 assert.equal(c.q('[data-browse-source="ambientcg"]').getAttribute('aria-pressed'),'true');
 const acg=c.card('ambientcg:Bricks059');assert.match(textOf(acg),/ambientCG/);assert.equal(acg.querySelector('a').href,'https://ambientcg.com/view?id=Bricks059');
 assert.equal(acg.querySelector('select[data-resolution]').value,'1k');
 assert.equal(c.card('polyhaven:red_brick'),null);
 // Closing hides the panel; the Library is untouched.
 await click(c.q('[data-action="browse"]'));assert.equal(panel.hidden,true);
 assert.equal(c.q('[data-action="browse"]').getAttribute('aria-expanded'),'false');
 assert.equal(c.alerts.length,0);c.page.stop();
});

await test('stale_search_answer_is_dropped',async()=>{
 let release;const slow=new Promise(r=>{release=r;});
 const c=await setup({search:async(source,q)=>{if(q==='')await slow;return ROWS[source].filter(r=>r.name.toLowerCase().includes(q));}});
 fire(c.q('[data-action="browse"]'),'click');await pause(5);await edit(c.q('[data-browse-search]'),'input',{value:'big'});await pause(330);
 assert.ok(c.card('polyhaven:big_brick'));release();await pause(10);
 assert.equal(c.card('polyhaven:red_brick'),null,'the older empty-query answer must not overwrite');c.page.stop();
});

await test('resolution_default_is_2k_else_nearest',async()=>{
 assert.equal(pickResolution(['1k','2k','4k']),'2k');assert.equal(pickResolution(['4k','8k']),'4k');
 assert.equal(pickResolution(['1k','4k']),'1k');assert.equal(pickResolution(['8k']),'8k');assert.equal(pickResolution([]),null);
});

await test('add_polls_job_and_opens_material',async()=>{
 const seen=[];let card;
 const jobs=[{state:'queued',progress:0},{state:'running',progress:.5},{state:'done',progress:1,material_id:'red-brick-2'}];
 const c=await setup({job:async n=>{seen.push(textOf(card.querySelector('output')));return {id:'job-1',...jobs[Math.min(n,3)-1]};}});
 await c.openBrowse();card=c.card('polyhaven:red_brick');
 const res=card.querySelector('select[data-resolution]');await edit(res,'change',{value:'1k'});
 const add=card.querySelector('[data-action="add"]');const started=Date.now();
 const pending=click(add);await pause(20);
 assert.equal(add.disabled,true,'Add is disabled while the job runs');
 const post=c.calls.find(x=>x.method==='POST');
 assert.equal(post.path,'materials/sources/polyhaven/red_brick/download');assert.deepEqual(post.body,{resolution:'1k'});
 await pending;await pause(1700);
 const polls=c.calls.filter(x=>x.path.startsWith('materials/jobs/'));
 assert.equal(polls.length,3,'polls until done, then stops');assert.equal(polls[0].path,'materials/jobs/job-1');
 assert.ok(polls[0].at-started>=450,'first poll waits 500 ms');
 for(let i=1;i<polls.length;i++)assert.ok(polls[i].at-polls[i-1].at>=450,'polls every 500 ms');
 assert.match(seen[2],/50%/,'progress shown while running');assert.match(seen[1],/[Ww]aiting/);
 assert.ok(c.calls.some(x=>x.path==='materials/red-brick-2'&&x.method==='GET'),'opens the new material');
 assert.equal(c.host.querySelector('[data-material="red-brick-2"]').getAttribute('aria-pressed'),'true');
 assert.equal(c.q('output[role="status"]').textContent,'Saved');
 assert.match(textOf(card.querySelector('output')),/Added/);assert.equal(add.disabled,false);
 await pause(600);assert.equal(c.calls.filter(x=>x.path.startsWith('materials/jobs/')).length,3);
 assert.deepEqual(c.alerts,[]);c.page.stop();
});

await test('failure_reason_shown_no_dialog',async()=>{
 const c=await setup({job:async n=>n===1?{state:'running',progress:.2}:{state:'failed',progress:.2,error:'The archive is damaged.'}});
 await c.openBrowse();const card=c.card('polyhaven:red_brick'),add=card.querySelector('[data-action="add"]');
 await click(add);await pause(1150);
 assert.deepEqual(c.alerts,['The archive is damaged.']);
 assert.equal(add.disabled,false,'Add works again after a failure');
 assert.doesNotMatch(textOf(card.querySelector('output')),/Added/);
 await pause(600);assert.equal(c.calls.filter(x=>x.path.startsWith('materials/jobs/')).length,2,'stops polling');c.page.stop();
});

await test('offline_message_shown',async()=>{
 const c=await setup({search:async()=>{throw fail(503,'Online libraries are not reachable.');}});
 await c.openBrowse();
 assert.match(textOf(c.q('[data-browse-status]')),/Online libraries are not reachable\./);
 assert.equal(c.q('[data-browse-result]'),null);assert.deepEqual(c.alerts,[],'offline is said in the panel, not an alert');
 // The rest of the Library still works.
 await click(c.host.querySelector('[data-material="brick"]'));await pause(5);
 assert.equal(c.host.querySelector('[data-material="brick"]').getAttribute('aria-pressed'),'true');
 assert.ok(c.host.querySelector('[data-action="duplicate"]'));c.page.stop();
});

await test('queue_full_message_shown',async()=>{
 const c=await setup({download:async()=>{throw fail(429,'10 downloads are already waiting. Try again when some finish.');}});
 await c.openBrowse();const add=c.card('polyhaven:red_brick').querySelector('[data-action="add"]');
 await click(add);await pause(5);
 assert.deepEqual(c.alerts,['10 downloads are already waiting. Try again when some finish.']);
 assert.equal(add.disabled,false);assert.equal(c.calls.filter(x=>x.path.startsWith('materials/jobs/')).length,0);c.page.stop();
});

await test('interrupted_job_says_try_again',async()=>{
 const c=await setup({job:async()=>{throw fail(404,'No such download.');}});
 await c.openBrowse();const add=c.card('polyhaven:red_brick').querySelector('[data-action="add"]');
 await click(add);await pause(600);
 assert.equal(c.alerts.length,1);assert.match(c.alerts[0],/interrupted/i);assert.match(c.alerts[0],/[Tt]ry again/);
 assert.equal(add.disabled,false);c.page.stop();
});

await test('default_api_error_carries_status',async()=>{
 window.chfBase='/api/hassio_ingress/tok/';const urls=[];
 globalThis.fetch=async url=>{urls.push(url);return new Response(JSON.stringify({detail:'Online libraries are not reachable.'}),{status:503});};
 const error=await libraryApi('materials/sources/polyhaven?q=').then(()=>null,e=>e);
 assert.equal(urls[0],'/api/hassio_ingress/tok/api/house/materials/sources/polyhaven?q=');
 assert.equal(error.status,503);assert.equal(error.message,'Online libraries are not reachable.');
});
finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()})
    print(output)
    sys.exit(code if code is not None else 1)

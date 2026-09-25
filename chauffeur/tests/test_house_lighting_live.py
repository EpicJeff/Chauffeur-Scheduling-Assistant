"""Fixture ownership, mirroring, porch coverage and day/night lighting matrix."""
import copy
import itertools
import os
from pathlib import Path
from unittest.mock import patch
from test_house_facade_live import live_app, _seed, check
from house_probe import THREE_WRAP
from services import house_facade as hf

AUDIT = """() => {
 const scene=window.__hpScene; scene.updateMatrixWorld(true);
 const lamps=[], fixtures=[], pools=[];
 scene.traverse(o=>{
   if(o.isPointLight) {
     const p=o.getWorldPosition(new THREE.Vector3());
     let visible=true;for(let a=o;a;a=a.parent) if(!a.visible)visible=false;
     let delta=null;
     if(o.userData.fixtureId) {
       const f=scene.getObjectByProperty('uuid',o.userData.fixtureId);
       if(f) {const v=f.position.clone();if(o.userData.lightRole==='porch')v.y-=0.12;else v.z+=0.22;
         f.parent.localToWorld(v);delta=v.distanceTo(p);}
     }
     lamps.push({role:o.userData.lightRole,intensity:o.intensity,visible,delta,pos:p.toArray(),
       local:o.userData.fixtureAnchor||o.position.toArray()});
   }
   if(o.userData.exteriorFixture) fixtures.push({role:o.userData.exteriorFixture,glow:o.material.emissiveIntensity});
   if(o.userData.porchLightPool) pools.push(o.material.opacity);
 });
 return {lamps,fixtures,pools};
}"""

def scenario_lighting_matrix(smoke=False):
    served=live_app(_seed)
    if served is None:
        return
    three=Path('static/vendor/three.min.js').read_bytes()+THREE_WRAP
    source=Path('static/house.js').read_text(encoding='utf-8').replace(
        'function setNight(n) {','function setNight(n) { window.__testNight = setNight;',1)
    cases=list(itertools.product([False,True],['front','side','third'],['gable','shed','flat','mixed','stoop','none']))
    cases=[(m,g,p,'high') for m,g,p in cases]
    cases += [(m,'third','mixed',q) for m in [False,True] for q in ['medium','low']]
    if smoke: cases=[(True,'third','mixed','high'),(True,'side','gable','low')]
    # The rig follows the outdoor state now, not Date.getHours(). Keep
    # polling deterministic too, so the real sun cannot reset this matrix.
    with patch('services.kitchen_room._window', return_value={
        'calm': True, 'cond': 'clear-night', 'temp': 72, 'precip': 0,
        'night': True, 'next_sun_change': None,
    }), served.browser() as page:
        errors=[]
        page.on('pageerror',lambda e: errors.append(str(e)))
        page.route('**/three.min.js*',lambda r:r.fulfill(status=200,content_type='application/javascript',body=three))
        page.route('**/house.js*',lambda r:r.fulfill(status=200,content_type='application/javascript',body=source))
        page.route('**/api/v2/chat/stream*',lambda r:r.fulfill(status=200,body=''))
        for mirror,garage,porch,quality in cases:
            spec=copy.deepcopy(hf.CANONICAL);spec['mirror']=mirror
            if garage!='front':
                spec['blocks']['garage'].update(orientation='side',side_door={
                    'style':'glass','width':4.4,'height':3.8,'leaves':2,
                    'third_bay':garage=='third','projection':1.8 if garage=='third' else 0})
            if mirror:
                spec['blocks']['garage']['depth']=4
                spec['blocks']['main']['depth']=2
            for f in spec['ground']:
                if f['kind']=='porch':
                    f['roof']='gable' if porch=='stoop' else porch
                    f['type']='stoop' if porch=='stoop' else 'covered'
                    if porch=='mixed':f.update(gable_offset=1,gable_span=2)
            if porch=='none':spec['ground']=[f for f in spec['ground'] if f['kind']!='porch']
            if garage=='third':spec['upper']=[{'slot':0,'span':6,'roof':{'form':'gable','ridge':'z','pitch_deg':30}}]
            spec,_=hf.normalize(spec)
            label=f'{garage}-{porch}-{quality}-mirror{int(mirror)}'
            page.goto(served.url('house?editor=1&quality='+quality+'&draft='+hf.issue_draft(spec)),wait_until='domcontentloaded',timeout=60000)
            page.wait_for_function('window.__testNight && window.__hpScene && window.chfFacade()',timeout=45000)
            night=page.evaluate(AUDIT)
            exterior=[l for l in night['lamps'] if l['role']!='interior']
            if quality=='low':check(not night['lamps'],label+' low has no point-light cost')
            else:
                check(0<len(exterior)<=6,label+' exterior light budget')
                check(all(l['delta'] is not None and l['delta']<1e-4 for l in exterior),label+' lights follow real fixtures')
                check(all(abs(l['pos'][0]-l['local'][0]*(-1 if mirror else 1))<1e-4 for l in night['lamps']),label+' all pools mirror')
                check(all(not l['visible'] for l in night['lamps'] if l['role']=='interior'),label+' no interior light through sealed walls')
                check(all(l['intensity']>0 and l['visible'] for l in exterior),label+' night exterior lighting on')
            covered=porch not in ('none','stoop')
            check(bool(night['pools'])==covered,label+' porch pool matches actual cover')
            check(all(v>0 for v in night['pools']),label+' porch floor lit at night')
            check(all(f['glow']>0 for f in night['fixtures']),label+' fixtures glow at night')
            page.evaluate('window.__testNight(false)')
            day=page.evaluate(AUDIT)
            check(all(l['intensity']==0 for l in day['lamps'] if l['role']!='interior'),label+' exterior lamps off by day')
            check(all(v==0 for v in day['pools']),label+' pools off by day')
            check(all(f['glow']==0 for f in day['fixtures']),label+' fixture glow off by day')
            page.evaluate('window.__testNight(true)')
            if os.environ.get('HOUSE_SHOTS') and ((mirror and garage=='third' and porch=='mixed') or smoke):
                out=Path(os.environ['HOUSE_SHOTS']);out.mkdir(parents=True,exist_ok=True)
                page.evaluate('window.chfCapture()')
                page.screenshot(path=str(out/(label+'.png')))
            if mirror and garage=='third' and porch=='mixed' and quality=='high':
                for room in ('kitchen','living','mudroom','garage','study'):
                    page.evaluate('(room)=>window.chfHouseEnterRoom(room)',room)
                    page.wait_for_function('(room)=>window.chfHouseMode()===room',arg=room)
                    page.wait_for_function('window.chfNavProbe({settled:true})')
                    inside=page.evaluate(AUDIT)['lamps']
                    check(all(l['visible'] for l in inside if l['role']=='interior'),room+' interior lights return')
                    check(all(not l['visible'] for l in inside if l['role']!='interior'),room+' exterior pools disabled')
                    page.evaluate('window.chfHouseExit()')
                    page.wait_for_function('window.chfNavProbe({settled:true})')
                    outside=page.evaluate(AUDIT)['lamps']
                    check(all(l['visible']==(l['role']!='interior') for l in outside),room+' exterior lighting restored')
            check(not errors,f'{label}: {errors}')
            print('  ok',label,flush=True)
    print(f'Lighting matrix passed: {len(cases)} layouts, day and night',flush=True)

if __name__=='__main__':
    import sys
    scenario_lighting_matrix('--smoke' in sys.argv)

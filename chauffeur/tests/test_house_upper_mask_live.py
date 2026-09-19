"""Bounded camera-to-room masking reaches the roof and restores the exterior."""
import copy
import os
from pathlib import Path
from test_house_facade_live import live_app, _seed, check, NIGHT_LOCK_JS
from services import house_facade as hf


def scenario_bounded_upper_mask():
    def seed():
        _seed()
        from services import ha_api
        ha_api.get_states=lambda *a,**k: []
        ha_api.get_state=lambda *a,**k: None
    served=live_app(seed)
    if served is None:return
    with served.browser() as page:
        page.route('**/api/v2/chat/stream*',lambda r:r.fulfill(status=200,body=''))
        page.add_init_script(NIGHT_LOCK_JS)
        for mirror,partial in [(True,False),(False,True)]:
            spec=copy.deepcopy(hf.CANONICAL)
            spec['mirror']=mirror
            spec['blocks']['garage']['orientation']='side'
            for block in ('main','garage'):
                lo,hi=hf._face_range(hf.FACE_OF_BLOCK[block])
                if partial and block=='main':lo,hi=9,12
                spec['upper'].append({'slot':lo,'span':hi-lo+1,'roof':copy.deepcopy(spec['blocks'][block]['roof'])})
                spec['ground'] += [{'slot':i,'span':1,'kind':'window','size':'standard','story':2} for i in range(lo,hi+1,2)]
            spec,_=hf.normalize(spec)
            page.goto(served.url('house?quality=high&draft='+hf.issue_draft(spec)),wait_until='domcontentloaded',timeout=60000)
            page.wait_for_function('window.chfFacade && window.chfFacade()')
            exterior=page.evaluate('window.chfShellFabric()')
            for room in ('living','kitchen','study','garage','mudroom'):
                page.evaluate('(r)=>window.chfHouseEnterRoom(r)',room)
                page.wait_for_function('window.chfNavProbe({settled:true})')
                if os.environ.get('HOUSE_SHOTS') and room=='living':
                    out=Path(os.environ['HOUSE_SHOTS']);out.mkdir(parents=True,exist_ok=True)
                    page.screenshot(path=str(out/('upper-living-'+str(mirror)+'.png')))
                rows=page.evaluate('window.chfShellFabric()')
                block='garage' if room in ('garage','mudroom') else 'main'
                mask=page.evaluate('(r)=>window.chfRoomMask(r)',room)
                b=mask['box']
                overhead=[f for f in exterior if f['box'][1]>=b[0] and f['box'][0]<=b[1] and f['box'][5]>=b[4] and f['box'][4]<=b[5]]
                check(b[3]>=max(f['box'][3] for f in overhead),room+' bounded volume reaches all overhead shell')
                def side(pl,p):return sum(a*c for a,c in zip(pl['n'],p))-pl['d']
                def masked(p):return any(all(side(pl,p)>1e-3 for pl in m['P']) and any(side(pl,p)<-1e-3 for pl in m['W']) for m in (mask,))
                upper=[f for f in rows if '_upper_' in f['name'] or f['name'].endswith('_s2')]
                for f in upper:
                    verts=page.evaluate('(a)=>window.chfRoomShellVerts(a[0],a[1],10000)',[room,f['name']])
                    if mirror:verts=[[-v[0],v[1],v[2]] for v in verts]
                    check(not any(masked(v) for v in verts),room+' no upper remnant inside camera volume: '+f['name'])
                    check(not any(v[1]>=5.6-1e-6 and all(side(pl,v)>1e-3 for pl in mask['P']) for v in verts),room+' no upper bottom-face strip: '+f['name'])
                    center=[(f['box'][0]+f['box'][1])/2,(f['box'][2]+f['box'][3])/2,(f['box'][4]+f['box'][5])/2]
                    if f['kit'] and masked(center):
                        check(f['maskedFraction'][room]==1,room+' upper kit in bounded volume removed: '+f['name'])
                check(page.evaluate('(r)=>window.chfMaskLeak(r)',room)==0,room+' correct visibility swap')
                page.evaluate('window.chfHouseExit()')
                page.wait_for_function('window.chfNavProbe({settled:true})')
                restored=page.evaluate('window.chfShellFabric()')
                check(page.evaluate('window.chfMaskLeak(null)')==0,room+' exterior masks restored')
                prior={f['name']:f['visible'] for f in exterior}
                check(all(f['visible']==prior[f['name']] for f in restored if f['name'] in prior and ('_upper_' in f['name'] or f['name'].startswith('facade_'))),room+' exterior facade restored')
            print('PASS bounded upper mask',mirror,partial,flush=True)
    print('UPPER MASK PASS',flush=True)

if __name__=='__main__':scenario_bounded_upper_mask()

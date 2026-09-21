"""Neighborhood budget, orbit visibility, editor isolation and room navigation."""
import os
import sys
import tempfile
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parents[1]/'tools')]
os.environ.setdefault('CHAUFFEUR_DATA_DIR',tempfile.mkdtemp(prefix='neighborhood_'))
from live_app import live_app
from house_live_common import _seed, DAY_LOCK_JS
from services import ha_api
from house_probe import THREE_WRAP


def main():
    ha_api.get_states=lambda *a,**k:[]
    ha_api.get_state=lambda *a,**k:None
    served=live_app(_seed)
    if not served:raise RuntimeError('Browser unavailable')
    try:
        with served.browser() as page:
            vendor=(Path(__file__).parents[1]/'static/vendor/three.min.js').read_bytes()+THREE_WRAP
            page.route('**/static/vendor/three.min.js*',lambda r:r.fulfill(content_type='application/javascript',body=vendor))
            page.add_init_script(DAY_LOCK_JS)
            page.route('**/api/v2/chat/stream*',lambda r:r.fulfill(status=200,body=''))
            page.set_viewport_size({'width':1400,'height':1000})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            for quality in ('high','low'):
                page.goto(served.url('house')+'?quality='+quality+'&day=1')
                page.wait_for_function('window.chfNeighborhood && window.chfNeighborhood() && window.chfNavProbe({settled:true})',timeout=120000)
                stats=page.evaluate('chfNeighborhood()');print(quality,{k:v for k,v in stats.items() if k!='placements'})
                assert stats['lots']==48 and stats['nearLots']==8 and stats['farLots']==40 and stats['horizon'] and stats['nearSource']=='active-exterior' and stats['nearTemplate']['meshes']>50 and stats['batches']<=120 and stats['triangles']<2000000,stats
                budget=page.evaluate('''() => {
                  const s=window.__hpScene,r=window.__hpR,c=window.__hpCam,g=s.getObjectByName('neighborhood');
                  r.render(s,c); const withNeighbors=r.info.render.calls;
                  g.visible=false;r.render(s,c);const alone=r.info.render.calls;
                  g.visible=true;r.render(s,c);return {added:withNeighbors-alone,withNeighbors,alone};
                }''')
                print('draw calls',quality,budget)
                assert 0<=budget['added']<=240,budget
                for stop in range(8):
                    page.evaluate('(s)=>chfOrbitTo(s)',stop)
                    page.wait_for_function('chfNavProbe({settled:true})',timeout=20000)
                    assert page.evaluate('chfNeighborhood().visible')
                    if os.environ.get('HOUSE_SHOTS'):
                        out=Path(os.environ['HOUSE_SHOTS']);out.mkdir(parents=True,exist_ok=True)
                        page.screenshot(path=str(out/f'neighborhood-{quality}-{stop}.png'))
                for room in ('kitchen','garage','living'):
                    page.evaluate('(r)=>chfHouseEnterRoom(r)',room)
                    page.wait_for_function('chfNavProbe({settled:true})',timeout=20000)
                    assert not page.evaluate('chfNeighborhood().visible')
                    page.evaluate('chfHouseExit()')
                    page.wait_for_function('chfNavProbe({settled:true})',timeout=20000)
                page.locator('#house-hints button[data-room="kitchen"]').click()
                page.wait_for_function("chfHouseMode()==='kitchen' && chfNavProbe({settled:true})",timeout=20000)
                assert not page.evaluate('chfNeighborhood().visible')
                page.evaluate('chfHouseExit()')
                page.wait_for_function('chfNavProbe({settled:true})',timeout=20000)
                if quality=='high':
                    page.set_viewport_size({'width':430,'height':900})
                    if os.environ.get('HOUSE_SHOTS'):page.screenshot(path=str(out/'neighborhood-touch.png'))
                    page.set_viewport_size({'width':1400,'height':1000})
            page.goto(served.url('house')+'?quality=high&editor=1&day=1')
            page.wait_for_function('window.chfNavProbe && chfNavProbe({settled:true})',timeout=120000)
            assert page.evaluate('chfNeighborhood()') is None
            assert not errors,errors
    finally:served.stop()
    print('PASS: neighborhood render budget, orbit, rooms, and isolated editor')


if __name__=='__main__':main()

"""Mapped neighborhood: async first load, cached load, orbit and room isolation."""
import os
import json
import sys
import tempfile
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1]/'tools')]
os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='house_map_live_'))
from live_app import live_app
from house_live_common import _seed, DAY_LOCK_JS
from house_probe import THREE_WRAP
from services import ha_api, house_map


def main():
    streets = [[(-350,20),(45,20),(100,45),(135,90),(135,350)],
               [(-100,-350),(-100,20),(-100,350)],
               [(-350,-100),(-100,-100),(40,-100),(85,-65),(100,45)],
               [(-350,110),(0,110),(55,140),(135,140)]]
    layout = house_map.compile_layout(streets)
    if os.environ.get('HOUSE_MAP_REPLAY'):
        saved = json.loads(Path(os.environ['HOUSE_MAP_REPLAY']).read_text(encoding='utf-8-sig'))
        saved = saved.get('layout',saved)
        layout = house_map.compile_layout(saved['roads'])
        assert layout['roads'] == saved['roads']
        assert len(layout['lots']) > len(saved['lots'])
        print('Replay houses:',len(saved['lots']),'->',len(layout['lots']),flush=True)
    house_map.neighborhood_layout = lambda cached_only=False: {'source':'generated'} if cached_only else layout
    ha_api.get_states = lambda *a, **k: []
    ha_api.get_state = lambda *a, **k: None
    served = live_app(_seed)
    if not served:
        raise RuntimeError('Browser unavailable')
    try:
        with served.browser() as page:
            vendor = (Path(__file__).parents[1]/'static/vendor/three.min.js').read_bytes()+THREE_WRAP
            page.route('**/static/vendor/three.min.js*', lambda r: r.fulfill(content_type='application/javascript', body=vendor))
            page.add_init_script(DAY_LOCK_JS)
            page.route('**/api/v2/chat/stream*', lambda r: r.fulfill(status=200, body=''))
            page.set_viewport_size({'width':1400, 'height':1000})
            errors=[]
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(served.url('house')+'?quality='+os.environ.get('HOUSE_MAP_QUALITY','high')+'&day=1')
            page.wait_for_function("window.chfNeighborhood && chfNeighborhood() && chfNeighborhood().layoutSource==='mapbox' && chfNavProbe({settled:true})", timeout=120000)
            stats = page.evaluate('chfNeighborhood()')
            assert stats['nearDesigns'] == 8 and len(set(stats['nearGeometry'])) == 8, stats
            assert stats['triangles'] < 2000000 and stats['batches'] <= 400, stats
            assert stats['roadSegments'] == len(layout['roads']) and stats['lots'] == len(layout['lots'])
            assert [p['scale'] for p in stats['placements']] == [p['scale'] for p in layout['lots']]
            rendered_scales=page.evaluate('''() => {let values=[];__hpScene.getObjectByName('neighborhood').traverse(m=>{
              if(!m.userData.nearExterior)return;let a=m.instanceMatrix.array;
              for(let i=0;i<m.count;i++){let scale=Math.hypot(a[i*16],a[i*16+1],a[i*16+2]);if(scale>.01)values.push(Math.round(scale*100)/100);}
            });return [...new Set(values)];}''')
            assert rendered_scales and set(rendered_scales).issubset({p['scale'] for p in layout['lots'][:8]}),rendered_scales
            assert page.locator('#room canvas').count() == 1
            assert page.locator('#house-map-credit').is_visible()
            assert page.evaluate("__hpScene.getObjectByName('parcel-road').visible") is False
            assert page.evaluate("__hpScene.children.filter(g=>g.name==='neighborhood').length") == 1
            for stop in (2,4,6,0):
                page.evaluate('(s)=>chfOrbitTo(s)', stop)
                page.wait_for_function('chfNavProbe({settled:true})', timeout=20000)
            page.evaluate("chfHouseEnterRoom('kitchen')")
            page.wait_for_function('chfNavProbe({settled:true})', timeout=20000)
            assert not page.evaluate('chfNeighborhood().visible')
            page.evaluate('chfHouseExit()')
            page.wait_for_function('chfNavProbe({settled:true})', timeout=20000)
            if os.environ.get('HOUSE_SHOTS'):
                out=Path(os.environ['HOUSE_SHOTS']);out.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(out/'mapped-neighborhood-front.png'))
                page.evaluate('''() => {let c=__hpCam;c.position.set(130,160,250);c.fov=65;c.updateProjectionMatrix();c.lookAt(0,0,0);__hpR.render(__hpScene,c);}''')
                page.locator('#room canvas').screenshot(path=str(out/'mapped-neighborhood-overview.png'))
            # Warm page embeds the geometry: no new API request or second build.
            house_map.neighborhood_layout = lambda cached_only=False: layout
            calls=[]
            page.on('request',lambda r:calls.append(r.url) if '/api/house/neighborhood' in r.url else None)
            page.goto(served.url('house')+'?quality=low&day=1')
            page.wait_for_function("window.chfNeighborhood && chfNeighborhood() && chfNavProbe({settled:true})",timeout=120000)
            assert page.evaluate('chfNeighborhood().layoutSource') == 'mapbox'
            assert page.evaluate("__hpScene.getObjectByName('parcel-road').visible") is False
            assert not calls, calls
            page.goto(served.url('house')+'?quality=low&editor=1')
            page.wait_for_function('window.chfNavProbe && chfNavProbe({settled:true})',timeout=120000)
            assert page.evaluate('chfNeighborhood()') is None
            assert not page.locator('#house-map-credit').is_visible()
            assert not calls and not errors, (calls, errors)
            house_map.neighborhood_layout = lambda cached_only=False: {'source':'generated'}
            page.route('**/api/house/neighborhood', lambda r:r.fulfill(status=503, body='Unavailable'))
            page.goto(served.url('house')+'?quality=low&day=1')
            page.wait_for_function('window.chfNeighborhood && chfNeighborhood() && chfNavProbe({settled:true})', timeout=120000)
            assert page.evaluate('chfNeighborhood().layoutSource') == 'generated'
            assert page.evaluate('chfNeighborhood().lots') == 48
            assert not page.locator('#house-map-credit').is_visible()
            assert not errors, errors
            print('PASS mapped first/warm loads, 8 detailed designs, 1 canvas, orbit, room navigation, editor isolation, provider failure fallback')
    finally:
        served.stop()


if __name__ == '__main__':
    main()

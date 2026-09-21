"""Real renderer: compact window groups and centred single/double entry assemblies."""
import copy
import os
import sys
import tempfile
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
os.environ.setdefault('CHAUFFEUR_DATA_DIR',tempfile.mkdtemp(prefix='opening_groups_'))
from live_app import live_app
from house_live_common import _seed, DAY_LOCK_JS
from services import house_facade as hf, ha_api


def main():
    ha_api.get_states=lambda *a,**k:[]
    ha_api.get_state=lambda *a,**k:None
    served=live_app(_seed)
    if not served:raise RuntimeError('Browser unavailable')
    try:
        with served.browser() as page:
            page.route('**/api/v2/chat/stream*',lambda route:route.fulfill(status=200,body=''))
            page.add_init_script(DAY_LOCK_JS)
            page.set_viewport_size({'width':1400,'height':1000})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            widths={}
            for mode,count,shutters in [('single',1,False),('double',2,True),('compact',2,True)]:
                spec=copy.deepcopy(hf.CANONICAL)
                spec.update(roof=[],upper=[],mirror=False)
                spec['ground']=[{'slot':7,'span':1 if mode=='compact' else 2,'kind':'window','count':3,'size':'standard','shutters':shutters,'story':1},
                                {'slot':10,'span':3,'kind':'door','count':count},
                                {'slot':14,'span':3,'kind':'window','size':'standard','shutters':False,'story':1}]
                spec,_=hf.normalize(spec);token=hf.issue_draft(spec)
                page.goto(served.url('house')+'?draft='+token+'&angle=0&quality=high&day=1&editor=1')
                page.wait_for_function('window.chfFacade && window.chfFacade() && window.chfNavProbe({settled:true})',timeout=120000)
                rows=page.evaluate('window.chfShellFabric()')
                units=[r for r in rows if r['name'].startswith('facade_main_window_7_unit')]
                assert len(units)==3,units
                door=next(r for r in rows if r['name']=='facade_main_door_10')
                widths[mode]=door['box']
                assert not errors,errors
                if os.environ.get('HOUSE_SHOTS'):
                    out=Path(os.environ['HOUSE_SHOTS']);out.mkdir(parents=True,exist_ok=True)
                    page.screenshot(path=str(out/('opening-groups-'+mode+'.png')))
                if mode=='double':
                    page.set_viewport_size({'width':430,'height':900})
                    if os.environ.get('HOUSE_SHOTS'):page.screenshot(path=str(out/'opening-groups-touch.png'))
                    page.set_viewport_size({'width':1400,'height':1000})
            assert widths['double']!=widths['single'],widths
    finally:served.stop()
    print('PASS: grouped windows and single/double door renderer, desktop/touch')


if __name__=='__main__':main()

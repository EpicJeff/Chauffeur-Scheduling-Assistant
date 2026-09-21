"""Render grouped windows on both stories and preserve independent shell kits."""
import os
import sys
import tempfile
import copy
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
os.environ.setdefault('CHAUFFEUR_DATA_DIR',tempfile.mkdtemp(prefix='house_window_groups_'))
from live_app import live_app
from house_live_common import _seed, DAY_LOCK_JS
from services import house_facade as hf, ha_api

def main():
    ha_api.get_states=lambda *a,**k:[]
    ha_api.get_state=lambda *a,**k:None
    served=live_app(_seed)
    if not served:return
    spec=copy.deepcopy(hf.CANONICAL)
    spec['upper']=[{'slot':6,'span':8,'roof':copy.deepcopy(spec['blocks']['main']['roof'])}]
    spec['ground']=[{'slot':7,'span':3,'kind':'window','size':'tall','count':3,'shutters':True,'story':1},
                    {'slot':7,'span':3,'kind':'window','size':'tall','count':3,'shutters':True,'story':2},
                    {'slot':0,'span':2,'kind':'window','size':'standard','count':2,'shutters':True,'story':1}]
    spec,_=hf.normalize(spec)
    try:
        with served.browser() as page:
            page.set_viewport_size({'width':1400,'height':1000})
            page.add_init_script(DAY_LOCK_JS)
            page.route('**/api/v2/chat/stream*',lambda route:route.fulfill(status=200,body=''))
            for mirror in (False,True):
                spec['mirror']=mirror
                token=hf.issue_draft(spec)
                page.goto(served.url('house')+'?draft='+token+'&angle=0&quality=high&day=1&editor=1')
                page.wait_for_function('window.chfFacade && window.chfFacade() && window.chfNavProbe({settled:true})',timeout=120000)
                rows=page.evaluate('window.chfShellFabric().filter(f=>f.name.includes("_window_") && f.name.includes("_unit"))')
                assert len(rows)==8, [r['name'] for r in rows]
                assert len(set(r['name'] for r in rows))==8
                assert all(r['kit'] for r in rows)
                assert sum('_s2' in r['name'] for r in rows)==3
                if os.environ.get('HOUSE_SHOTS'):
                    out=Path(os.environ['HOUSE_SHOTS']);out.mkdir(parents=True,exist_ok=True)
                    page.screenshot(path=str(out/('window-groups-mirrored.png' if mirror else 'window-groups.png')))
    finally:served.stop()
    print('PASS: pairs/triples on both stories, unique shell kits, normal and mirrored')

if __name__=='__main__':main()

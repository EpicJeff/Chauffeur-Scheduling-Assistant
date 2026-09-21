"""High-quality render of the replayed failure, mirrored and without upper spans."""
import os
import sys
import tempfile
import json
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
os.environ.setdefault('CHAUFFEUR_DATA_DIR',tempfile.mkdtemp(prefix='house_photo_geometry_'))
from live_app import live_app
from house_live_common import _seed, DAY_LOCK_JS
from services import house_facade as hf, ha_api
from services.house_photo_compiler import compile_analysis

def main():
    ha_api.get_states=lambda *a,**k:[]
    ha_api.get_state=lambda *a,**k:None
    data=json.loads((Path(__file__).parent/'fixtures/house_photo_architecture_v1.json').read_text())
    spec,_,_=compile_analysis(data)
    served=live_app(_seed)
    if not served:raise RuntimeError('Browser test unavailable')
    try:
        with served.browser() as page:
            page.set_viewport_size({'width':1400,'height':1000})
            page.add_init_script(DAY_LOCK_JS)
            page.route('**/api/v2/chat/stream*',lambda route:route.fulfill(status=200,body=''))
            for mode in ('replay','unmirrored','no-upper'):
                if mode=='unmirrored':spec['mirror']=False
                if mode=='no-upper':spec['upper']=[];spec,_=hf.normalize(spec)
                token=hf.issue_draft(spec)
                page.goto(served.url('house')+'?draft='+token+'&angle=0&quality=high&day=1&editor=1')
                page.wait_for_function('window.chfFacade && window.chfFacade() && window.chfNavProbe({settled:true})',timeout=120000)
                rows=page.evaluate('window.chfShellFabric().map(f=>f.name)')
                assert 'facade_garage_block_gable_0_attic_window' in rows, rows
                assert any(n.startswith('facade_garage_block_gable_0') for n in rows)
                assert sum(n.startswith('facade_garage_block_window_2_unit') for n in rows)==3
                if mode!='no-upper':assert sum(n.startswith('facade_main_window_') and '_s2' in n for n in rows)==3
                if os.environ.get('HOUSE_SHOTS'):
                    out=Path(os.environ['HOUSE_SHOTS']);out.mkdir(parents=True,exist_ok=True)
                    page.screenshot(path=str(out/('compiled-architecture-'+mode+'.png')))
    finally:served.stop()
    print('PASS: compiled facade windows, cross-gable, attic window; mirrored/unmirrored/no-upper')

if __name__=='__main__':main()

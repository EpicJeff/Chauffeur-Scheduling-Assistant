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
from services.house_photo_structure import compile_structure, apply_details

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
            modes=os.environ.get('HOUSE_RENDER_MODES','replay,unmirrored,no-upper,photo8,photo10-faces,missing-annotations,photo11,staged,hip-one,gable-two').split(',')
            for mode in modes:
                if mode in ('staged','hip-one','gable-two'):
                    from test_house_photo_structure import structure, details
                    s=structure();d=details()
                    if mode!='staged':
                        v=s['volumes'][0];v.update(id='whole',at=0,width=1,stories='one' if mode=='hip-one' else 'two')
                        v['roof'].update(form='hip' if mode=='hip-one' else 'gable',ridge='parallel')
                        s.update(volumes=[v],porches=[],gables=[],dormers=[])
                        d.update(openings=[],finishes=[])
                    locked,_,_=compile_structure(s)
                    spec,_,_=apply_details(s,locked,d)
                if mode=='unmirrored':spec['mirror']=False
                if mode=='no-upper':spec['upper']=[];spec,_=hf.normalize(spec)
                if mode=='photo8':
                    spec,_,_=compile_analysis(json.loads((Path(__file__).parent/'fixtures/house_photo8_analysis.json').read_text()))
                if mode=='photo10-faces':
                    a=json.loads((Path(__file__).parent/'fixtures/house_photo10_trace.json').read_text())['review_analysis']
                    a.update(schema_version=2,coordinate_frame='house_front',observations=[])
                    for layer in ('volumes','porches','gables','dormers','openings','finishes'):
                        for row in a[layer]:
                            row['face']='right' if row.get('id')=='O11' else 'front'
                            if 'id' in row:a['observations'].append({'feature':row['id'],
                                'image':3 if row['face']=='right' else 1,'face':row['face'],
                                'box':{'x':row['at'],'y':.2,'width':row['width'],'height':.5},
                                'evidence':'Synthetic face annotation for regression; not live recognition.'})
                    spec,_,_=compile_analysis(a)
                if mode=='missing-annotations':
                    a=json.loads((Path(__file__).parent/'fixtures/house_photo_architecture_v1.json').read_text())
                    a.update(schema_version=2,coordinate_frame='house_front',observations=[])
                    for layer in ('volumes','porches','gables','dormers','openings','finishes'):
                        for row in a[layer]:row['face']='front'
                    spec,_,_=compile_analysis(a)
                if mode=='photo11':
                    spec,_,_=compile_analysis(json.loads((Path(__file__).parent/'fixtures/house_photo11_analysis.json').read_text()))
                token=hf.issue_draft(spec)
                page.goto(served.url('house')+'?draft='+token+'&angle=0&quality=high&day=1&editor=1')
                page.wait_for_function('window.chfFacade && window.chfFacade() && window.chfNavProbe({settled:true})',timeout=120000)
                rows=page.evaluate('window.chfShellFabric().map(f=>f.name)')
                assert rows, 'empty rendered shell'
                if mode not in ('photo8','photo10-faces','photo11','hip-one','gable-two'):
                    assert 'facade_garage_block_gable_0_attic_window' in rows, rows
                    assert any(n.startswith('facade_garage_block_gable_0') for n in rows)
                    assert sum(n.startswith('facade_garage_block_window_2_unit') for n in rows)==3
                    if mode!='no-upper':assert sum(n.startswith('facade_main_window_') and '_s2' in n for n in rows)==3
                if os.environ.get('HOUSE_SHOTS'):
                    out=Path(os.environ['HOUSE_SHOTS']);out.mkdir(parents=True,exist_ok=True)
                    page.screenshot(path=str(out/('compiled-architecture-'+mode+'.png')))
    finally:served.stop()
    print('PASS: compiled facade rendering: '+', '.join(modes))

if __name__=='__main__':main()

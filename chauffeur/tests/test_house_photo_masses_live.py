"""Rendered mass roofs, projections and mirrored slot agreement; no provider calls."""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
os.environ.setdefault('CHAUFFEUR_DATA_DIR',tempfile.mkdtemp(prefix='house_masses_'))
from services import house_facade as hf, ha_api
from services.house_photo_structure import compile_structure
from live_app import live_app
from house_live_common import _seed, DAY_LOCK_JS, SEED_RNG_JS


def main():
    ha_api.get_states=lambda *a,**k:[]
    ha_api.get_state=lambda *a,**k:None
    source=json.loads((Path(__file__).parent/'fixtures/house_photo_brick_structure.json').read_text())
    served=live_app(_seed)
    if not served:raise RuntimeError('Browser required for mass proof')
    try:
        with served.browser() as page:
            page.add_init_script(DAY_LOCK_JS)
            page.add_init_script(SEED_RNG_JS)
            page.route('**/api/v2/chat/stream*',lambda r:r.fulfill(status=200,body=''))
            for mode in os.environ.get('HOUSE_MASS_MODES','brick,mirrored,mixed-story,hip-two,stepped-upper').split(','):
                s=copy.deepcopy(source)
                if mode=='mirrored':s['garage_side']='right'
                if mode=='mixed-story':s['volumes'][1]['stories']='two'
                if mode=='stepped-upper':
                    s['volumes'][1]['stories']='two'
                    s['volumes'][2]['stories']='two'
                if mode=='hip-two':
                    v=s['volumes'][0];v.update(at=0,width=1,stories='two',projection='flush')
                    v['roof'].update(form='hip',ridge='parallel')
                    s.update(volumes=[v],porches=[],gables=[],dormers=[])
                spec,_,_=compile_structure(s)
                page.goto(served.url('house')+'?draft='+hf.issue_draft(spec)+'&quality=high&day=1&editor=1')
                page.wait_for_function('window.chfFacade && window.chfFacade() && window.chfNavProbe({settled:true})',timeout=120000)
                built=page.evaluate('window.chfBlockGeometry()')
                volumes=built['volumes']
                assert len(volumes)==(2 if mode=='hip-two' else 3), volumes
                assert sum(v['roof']['form']=='hip' for v in volumes)==(2 if mode=='hip-two' else 1),volumes
                assert sum(v['roof']['ridge']=='z' for v in volumes)==(0 if mode=='hip-two' else 2),volumes
                if mode=='hip-two':assert all(v['eave']>6 for v in volumes),volumes
                elif mode=='mixed-story':assert sum(v['eave']>6 for v in volumes)==1,volumes
                elif mode=='stepped-upper':assert sum(v['eave']>6 for v in volumes)==2,volumes
                else:assert all(v['eave']<6 for v in volumes),volumes
                slots=page.evaluate('window.chfFacadeSlots()')
                expected=hf.slot_table(spec['blocks'],spec['upper'],spec.get('masses'))
                for a,b in zip(slots,expected):
                    for key in ('z','eave','x0','x1'):assert abs(a[key]-b[key])<1e-5,(mode,key,a,b)
                fabric=page.evaluate('window.chfShellFabric()')
                for v in volumes:
                    prefix=v['name']+'_roof' if v['name'] not in ('garage','main') else ('garage_block_roof' if v['block']=='garage' else 'roof_main')
                    rows=[f for f in fabric if f['name'].startswith(prefix+'_')]
                    assert rows,(mode,prefix)
                    assert max(f['box'][3] for f in rows)>v['eave']+.2,(mode,prefix,'empty roof')
                if mode=='hip-two':
                    end=next((f for f in fabric if f['name']=='garage_u0_roof_end_east'),None)
                    assert end and end['box'][3]>volumes[0]['eave']+.2, 'exposed sloped hip end missing at block seam'
                elif mode!='mirrored':
                    assert any('_mass_front' in f['name'] for f in fabric), 'forward wing wall missing'
                    assert abs(volumes[-1]['south']-volumes[1]['south']-1.5)<1e-5,volumes
                if mode=='stepped-upper':
                    assert any('west_forward' in f['name'] for f in fabric), 'upper forward wing side return missing'
                if os.environ.get('HOUSE_SHOTS'):
                    out=Path(os.environ['HOUSE_SHOTS']);out.mkdir(parents=True,exist_ok=True)
                    page.screenshot(path=str(out/(mode+'.png')))
                page.evaluate("window.chfHouseEnterRoom('living')")
                page.wait_for_function('window.chfNavProbe({settled:true})')
                assert page.evaluate("window.chfMaskLeak('living')")==0
                page.evaluate('window.chfHouseExit()')
                page.wait_for_function('window.chfNavProbe({settled:true})')
                assert page.evaluate('window.chfMaskLeak(null)')==0
                print('PASS ground masses: '+mode,flush=True)
            from services import storage
            storage.add_member({'id':'mass-editor','name':'Mass Editor','role':'parent','status':'active'})
            token=storage.create_member_token('mass-editor')
            page.add_init_script('localStorage.setItem("chauffeur_member_token", '+json.dumps(token)+')')
            page.goto(served.url('config'))
            page.wait_for_function('document.body._x_dataStack && document.body._x_dataStack[0].facadeDraft')
            spec,_,_=compile_structure(source)
            page.evaluate("spec => { const s=document.body._x_dataStack[0]; s.activeTab='family'; s.facadeTask='shape'; s.facadeDraft=spec; }",spec)
            field=page.locator('#home fieldset').filter(has=page.locator('legend',has_text='Photo-matched sections'))
            field.scroll_into_view_if_needed()
            assert field.is_visible()
            with page.expect_response('**/api/house/facades/preview'):
                field.locator('select[x-model="mass.roof.ridge"]').last.select_option('x')
            page.wait_for_function("document.body._x_dataStack[0].facadeDraft.masses[1].roof.ridge === 'x'")
            edited=page.evaluate('document.body._x_dataStack[0].facadeDraft')
            assert edited['masses'][0]==spec['masses'][0]
            assert hf.normalize(edited)[0]['masses']==edited['masses']
            print('PASS ground mass editor preview and normalization',flush=True)
    finally:served.stop()


if __name__=='__main__':main()

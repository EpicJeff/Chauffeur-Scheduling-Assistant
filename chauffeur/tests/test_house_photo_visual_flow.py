"""Browser exercise of upload -> capture -> automatic critique -> editor selection."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

def main():
    template=(Path(__file__).parents[1]/'templates/config.html').read_text(encoding='utf-8')
    methods=template[template.index('async facadeFrameLoaded()'):template.index('async facadeSaveNew()')]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        page=browser.new_page()
        start=template.index('<fieldset class="home-photo">')
        form=template[start:template.index('</fieldset>',start)+len('</fieldset>')]
        page.set_content('<div x-data="photoForm()">'+form+'</div>')
        page.evaluate("""window.photoForm=()=>({facadePrimary:null,facadeExtraFiles:[null,null],
            facadeExtraViews:['unknown','unknown'],facadeBusy:'',
            facadePhoto(){window.selected={primary:this.facadePrimary.name,
                extras:this.facadeExtraFiles.map(f=>f&&f.name),views:[...this.facadeExtraViews]};}})""")
        page.add_script_tag(path=str(Path(__file__).parents[1]/'static/vendor/alpine.min.js'))
        page.get_by_role('button',name='Match photos',exact=True).wait_for()
        assert page.get_by_role('button',name='Match photos',exact=True).is_disabled()
        page.get_by_label('Primary front photo').set_input_files({'name':'front.png','mimeType':'image/png','buffer':b'front'})
        page.get_by_label('Additional photo 1',exact=True).set_input_files({'name':'side.png','mimeType':'image/png','buffer':b'side'})
        page.get_by_label('View of additional photo 1',exact=True).select_option('front-right')
        page.get_by_role('button',name='Match photos',exact=True).click()
        assert page.evaluate('window.selected')=={'primary':'front.png','extras':['side.png',None],'views':['front-right','unknown']}
        page.get_by_role('button',name='Remove',exact=True).first.click()
        page.get_by_role('button',name='Match photos',exact=True).click()
        assert page.evaluate('window.selected.extras')==[None,None]
        page.route('**/editor',lambda r:r.fulfill(content_type='text/html',body='<iframe id="facade-preview-frame"></iframe>'))
        page.route('**/house?*',lambda r:r.fulfill(content_type='text/html',body="""<script>
window.HOUSE_FACADE={id:'draft'};window.chfFacade=()=>({version:3});
window.chfNavProbe=()=>({settled:true});window.chfCapture=()=> 'render-'+new URL(location.href).searchParams.get('draft');
</script>"""))
        for success in (True,False):
            calls=[]
            def api(route):
                body=route.request.post_data
                if route.request.url.endswith('/photo'):
                    assert 'name="supplemental"' in body and 'front-right' in body,body
                    result={'draft':{'label':'original'},'token':'photo-token','viewpoint':'centre','notes':[]}
                elif route.request.url.endswith('/critique'):
                    args=json.loads(body);calls.append(args)
                    result={'result':{'revised':{'label':'reviewed'} if success else None,'reasons':['Compared image'], 'unexpressed':[]}}
                else:result={'token':'review-token','spec':{'label':'reviewed'}}
                route.fulfill(content_type='application/json',body=json.dumps(result))
            page.route('**/api/house/facades/**',api)
            page.goto('http://photo.test/editor')
            page.evaluate('window.editor={'+methods+'}; window.showGlobalAlert=msg=>{throw new Error(msg)}; null;')
            result=page.evaluate("""async()=>{
 const e=window.editor; e.apiBase='/';e.facadeBusy='';e.facadeNotes=[];
 e.facadeAngleForViewpoint=()=>0;e.facadePreview=()=>{};
 e.$nextTick=()=>new Promise(resolve=>{
   const f=document.getElementById('facade-preview-frame');
   f.onload=async()=>{await e.facadeFrameLoaded();resolve();};
   f.src='/house?draft='+e.facadePreviewToken+'&angle='+e.facadePreviewAngle;
 });
 e.facadePrimary=new File(['photo'],'house.png',{type:'image/png'});
 e.facadeExtraFiles=[new File(['side'],'side.png',{type:'image/png'}),null];
 e.facadeExtraViews=['front-right','unknown'];
 await e.facadePhoto();
 const selected=e.facadeDraft.label;
 e.facadePickDraft();
 return {selected, original:e.facadeDraft.label, busy:e.facadeBusy, renders:e.facadeRenders};
}""")
            assert len(calls)==1 and calls[0]['automatic'] is True,calls
            assert calls[0]['render']=='render-photo-token',calls
            assert result['selected']==('reviewed' if success else 'original'),result
            assert result['original']=='original' and result['busy']=='',result
            page.unroute('**/api/house/facades/**',api)
        browser.close()
    print('PASS: automatic capture/review/adoption, original selection, failure retains draft')

if __name__=='__main__':main()

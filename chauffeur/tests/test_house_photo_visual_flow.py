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
 await e.facadePhoto({target:{files:[new File(['photo'],'house.png',{type:'image/png'})],value:'upload'}});
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

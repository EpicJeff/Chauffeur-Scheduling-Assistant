"""Real browser check: critique capture waits for its own iframe document."""
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    template = (Path(__file__).parents[1] / 'templates/config.html').read_text(encoding='utf-8')
    methods = template[template.index('async facadeFrameLoaded()'):template.index('async facadeCritique()')]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.route('**/house?*', lambda route: route.fulfill(content_type='text/html', body="""
<script>
window.HOUSE_FACADE={id:'draft'};
window.chfFacade=()=>({version:3});
window.chfNavProbe=()=>({settled:true});
window.chfCapture=()=> 'render-'+new URL(location.href).searchParams.get('draft');
</script>"""))
        page.route('**/editor',lambda route:route.fulfill(content_type='text/html',body='<iframe id="facade-preview-frame"></iframe>'))
        page.goto('http://photo.test/editor')
        page.evaluate('window.editor = {' + methods + '}; window.showGlobalAlert = msg => {throw new Error(msg)}; null;')
        result = page.evaluate("""async () => {
            const frame=document.getElementById('facade-preview-frame');
            frame.onload=()=>editor.facadeFrameLoaded();
            editor.facadePreviewToken='old';
            frame.src='/house?draft=old';
            const old=await editor.facadeCaptureFrame();
            editor.facadePreviewToken='new';
            const pending=editor.facadeCaptureFrame();
            // The old frame still reports settled. It must not be captured.
            await new Promise(r=>setTimeout(r,150));
            frame.src='/house?draft=new';
            const next = await pending;
            editor.facadePreviewAngle=1;
            const turned=editor.facadeCaptureFrame();
            await new Promise(r=>setTimeout(r,150));
            frame.src='/house?draft=new&angle=1';
            return [old, next, await turned, editor.facadeLoadedAngle];
        }""")
        assert result == ['render-old','render-new','render-new',1], result
        browser.close()
    print('PASS: critique captures the requested draft, never the previous settled frame')

if __name__ == '__main__':main()

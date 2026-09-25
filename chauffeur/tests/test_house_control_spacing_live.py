"""Room controls, including their labels, must stay separate after resizing."""
import argparse
import json
from pathlib import Path
from test_house_connected_live import seed, live_app, ha_api


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--standard', action='store_true', help='Use desktop chrome instead of the wall-panel shelf')
    args = parser.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    ha_api.get_states = lambda *a, **kw: []
    ha_api.get_state = lambda *a, **kw: None
    served = live_app(seed)
    try:
        with served.browser(reduced_motion='reduce', has_touch=True) as page:
            page.set_default_timeout(20000)
            page.route('**/api/v2/chat/stream*', lambda r: r.fulfill(status=204, body=''))
            page.goto(served.url('house?compare=exterior&scene=living&light=day' + ('' if args.standard else '&panel=true')))
            page.wait_for_function('window.chfHouseMode?.()==="living"')
            results = []
            sizes = [(2531,1224),(2048,990),(1920,1080),(1400,1000),(1024,768),
                     (768,1024),(390,844),(844,390),(320,568),(701,601),(700,600),(2560,1080),
                     (568,320),(320,480),(1024,600),(700,601),(701,600),(960,540),(1366,768),(3440,1440)]
            for room in ('living','kitchen','mudroom','study','garage'):
                if room != 'living':
                    page.evaluate('(room)=>{window.chfHybridGo(room)}', room)
                    if room == 'study':
                        page.wait_for_selector('#cc-input-field:visible')
                        page.fill('#cc-input-field','1234')
                        page.click('#cc-input-ok-btn')
                    page.wait_for_function('(room)=>chfHouseMode()===room', arg=room)
                for width, height in sizes:
                    page.set_viewport_size({'width':width,'height':height})
                    page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
                    result = page.evaluate('''() => {
                        const visible = el => el.checkVisibility({checkVisibilityCSS:true,checkOpacity:true});
                        const selectors = '#hybrid-walkthrough button,.hybrid-marker,#hybrid-outside,#study-lock,'+
                            '#hybrid-shortcuts,#kitchen-shortcuts,.utility-shortcuts,#house-comparison,'+
                            '.house-fire-toggle,.house-steam-toggle,#chat-overlay-container,.garage-controls,#panel-chat-orb,#panel-shelf';
                        const controls = [...document.querySelectorAll(selectors)].filter(visible).map(el=>{
                            const parts=[el,...(el.matches('.hybrid-marker') ? el.querySelectorAll('.hybrid-marker-label,.hybrid-count') : [])].filter(visible);
                            const rects=parts.map(p=>p.getBoundingClientRect());
                            return {el,name:el.getAttribute('aria-label')||el.id||el.className,
                                left:Math.min(...rects.map(r=>r.left)),top:Math.min(...rects.map(r=>r.top)),
                                right:Math.max(...rects.map(r=>r.right)),bottom:Math.max(...rects.map(r=>r.bottom))};
                        });
                        const misplaced=[...document.querySelectorAll('#hybrid-walkthrough .walk-side')].filter(visible).filter(el=>{
                            const r=el.getBoundingClientRect();
                            return Math.abs((r.top+r.bottom)/2-innerHeight/2)>1 ||
                                (el.dataset.side==='left' ? Math.abs(r.left-8)>1 : Math.abs(innerWidth-r.right-8)>1);
                        }).map(el=>el.dataset.side);
                        const overlaps=[];
                        controls.forEach((a,i)=>controls.slice(i+1).forEach(b=>{
                            if(a.el.contains(b.el)||b.el.contains(a.el))return;
                            if(Math.min(a.right,b.right)-Math.max(a.left,b.left)>1 &&
                               Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>1)overlaps.push([a.name,b.name]);
                        }));
                        const clipped=controls.filter(r=>r.el.matches('.hybrid-marker,#hybrid-walkthrough button') &&
                            (r.left<0||r.top<0||r.right>innerWidth+.5||r.bottom>innerHeight+.5)).map(r=>r.name);
                        return {overlaps,clipped,misplaced};
                    }''')
                    result.update(room=room,width=width,height=height)
                    results.append(result)
                    if result['overlaps'] or result['clipped']:
                        page.screenshot(path=str(out/f'failure-{room}-{width}-{height}.png'))
                    assert not result['overlaps'] and not result['clipped'] and not result['misplaced'], result
                    if (width,height) in ((2531,1224),(390,844),(844,390)):
                        page.screenshot(path=str(out/f'{room}-{width}-{height}.png'))
            (out/'results.json').write_text(json.dumps(results,indent=2))
            assert not served.errors(), served.errors()
            print(f'PASS: {len(results)} room/viewport combinations; no overlapping or clipped controls')
    finally:
        served.stop()


if __name__ == '__main__':
    main()

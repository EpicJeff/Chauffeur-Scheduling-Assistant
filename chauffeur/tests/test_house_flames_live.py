"""Simulated fire frames, unlit log backgrounds, alignment, and playback lifecycle.

Run from chauffeur/: python tests/test_house_flames_live.py --out <directory>
"""
import argparse
import json
from pathlib import Path

from test_house_hybrid_live import seed, live_app, ha_api


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    out = Path(parser.parse_args().out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    ha_api.get_states = lambda *a, **kw: []
    ha_api.get_state = lambda *a, **kw: None
    served = live_app(seed)
    assert served, 'Playwright required'
    results = {}
    try:
        with served.browser(reduced_motion='no-preference', record_video_dir=str(out/'video'),
                            record_video_size={'width':1400,'height':1000}) as page:
            page.set_default_timeout(20000)
            page.route('**/api/v2/chat/stream*', lambda r:r.fulfill(status=204, body=''))
            page.route('**/api/music/favorites*', lambda r:r.fulfill(
                status=200, content_type='application/json', body='{"items":[]}'))
            page.route('**/api/house/state*', lambda r:r.fulfill(
                status=200, content_type='application/json', body='{"window":{"night":false}}'))
            page.goto(served.url('house?compare=exterior&light=day'))
            page.wait_for_function('window.chfEffectsProbe && window.chfExteriorProbe?.().ready')
            assert page.locator('#hybrid-fire').get_attribute('src') is None
            page.emulate_media(reduced_motion='reduce')
            page.goto(served.url('house?compare=exterior&scene=living&light=day'))
            page.wait_for_function('window.chfEffectsProbe && document.getElementById("hybrid-day").naturalWidth > 0')
            assert page.locator('#hybrid-fire').get_attribute('src') is None
            # Let Chromium commit the initial reduced-motion layout before
            # emulating another OS setting; otherwise it can coalesce the change.
            page.evaluate('() => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            page.emulate_media(reduced_motion='no-preference')
            try:
                page.wait_for_function('window.chfEffectsProbe?.().frames > 3')
            except Exception:
                print('BROWSER ERRORS', served.errors())
                print('VIDEO STATE', page.evaluate('''() => {const v=document.getElementById('hybrid-fire');return {
                    probe:chfEffectsProbe(),src:v.currentSrc,ready:v.readyState,network:v.networkState,error:v.error?.message,
                    frame:{...document.getElementById('hybrid-room-frame').dataset},scene:document.body.dataset.houseScene,
                    paused:v.paused,hidden:document.hidden,images:['hybrid-day','hybrid-night'].map(id=>{const i=document.getElementById(id);return [i.complete,i.naturalWidth]})}}'''))
                raise
            assert page.evaluate('chfEffectsProbe().effect') == 'simulated-fire'
            assert page.locator('#hybrid-fire').evaluate('v=>v instanceof HTMLVideoElement && v.muted && v.loop && v.playsInline')
            assert page.evaluate('typeof THREE') == 'undefined'
            assert page.locator('#hybrid-overview canvas').count() == 0

            def still():
                page.wait_for_function('!chfEffectsProbe().running')
                assert page.locator('#hybrid-fire').is_hidden()
                assert page.locator('#hybrid-fire').evaluate('v=>v.paused')
                t = page.evaluate('chfEffectsProbe().time')
                page.wait_for_timeout(180)
                assert abs(page.evaluate('chfEffectsProbe().time') - t) < .01

            for light in ('day','night'):
                page.locator('#house-compare-light').select_option(light)
                page.wait_for_function('(light)=>document.getElementById("hybrid-"+light).naturalWidth>0', arg=light)
                page.wait_for_function('chfEffectsProbe().running')
                assert f'living-logs-{light}.png' in page.locator(f'#hybrid-{light}').get_attribute('src')
                page.locator('#hybrid-effects-toggle').uncheck()
                still()
                page.screenshot(path=str(out/f'empty-{light}.png'))
                page.locator('#hybrid-effects-toggle').check()
                page.wait_for_function('chfEffectsProbe().running')
                frames = []
                for i in range(8):
                    page.wait_for_timeout(180)
                    frame = page.evaluate('''() => {
                        const v=document.getElementById('hybrid-fire');
                        const c=document.createElement('canvas'); c.width=100;c.height=75;
                        const ctx=c.getContext('2d'); ctx.drawImage(v,0,0,100,75);
                        const a=ctx.getImageData(0,0,100,75).data;
                        let lit=0, contour=[], color=0, transparent=0;
                        for(let p=0;p<a.length;p+=4) {
                            const fire=a[p]>180 && a[p]>a[p+2]*1.3;
                            if(fire) { lit++; color+=a[p+1]; }
                            if(a[p+3]<8) transparent++;
                            contour.push(fire ? '1':'0');
                        }
                        return {lit,color,transparent,contour:contour.join(''),time:v.currentTime};
                    }''')
                    assert frame['lit'] > 100, frame['lit']
                    assert frame['transparent'] > 1000, 'decoded video must have real alpha, not a black rectangle'
                    frames.append(frame)
                    if i in (0,4):
                        page.screenshot(path=str(out/f'fire-{light}-{i}.png'))
                assert len({f['contour'] for f in frames}) >= 6, 'flame shape must evolve, not just brightness'
                assert len({f['color'] for f in frames}) >= 6
                results[light] = {'distinctContours':len({f['contour'] for f in frames}),
                                  'litPixels':[f['lit'] for f in frames],
                                  'mediaTimes':[f['time'] for f in frames]}

            page.locator('#hybrid-fire').evaluate('v=>{v.currentTime=v.duration-.3}')
            page.wait_for_function('document.getElementById("hybrid-fire").currentTime < 1')
            assert page.evaluate('chfEffectsProbe().running'), 'the rendered animation must loop'

            # Projection remains registered with the unmodified room photograph.
            for width,height in ((390,844),(2560,1080),(1400,1000)):
                page.set_viewport_size({'width':width,'height':height})
                page.wait_for_function('''() => {
                    const r=document.getElementById('hybrid-fire').getBoundingClientRect();
                    const s=Math.max(innerWidth/1536,innerHeight/1024);
                    return Math.abs(r.x-(508*s+(innerWidth-1536*s)/2))<1
                        && Math.abs(r.y-(294*s+(innerHeight-1024*s)/2))<1
                        && Math.abs(r.width-200*s)<1 && Math.abs(r.height-240*s)<1;
                }''')
                page.screenshot(path=str(out/f'fire-{width}.png'))
            page.locator('#hybrid-effects-toggle').uncheck()
            still()
            page.locator('#hybrid-effects-toggle').check()
            page.wait_for_function('chfEffectsProbe().running')
            page.emulate_media(reduced_motion='reduce')
            still()
            page.emulate_media(reduced_motion='no-preference')
            page.wait_for_function('chfEffectsProbe().running')
            # Simulate the browser visibility event; prove no hidden frame work.
            page.evaluate('''Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});
                document.dispatchEvent(new Event('visibilitychange'));''')
            still()
            page.evaluate('''delete document.hidden; document.dispatchEvent(new Event('visibilitychange'));''')
            page.wait_for_function('chfEffectsProbe().running')
            start = page.evaluate('({t:performance.now(),n:chfEffectsProbe().frames})')
            page.wait_for_timeout(1000)
            end = page.evaluate('({t:performance.now(),n:chfEffectsProbe().frames})')
            assert 0 < end['n']-start['n'] <= (end['t']-start['t'])*24/1000+3
            results['framesPerSecond'] = round((end['n']-start['n'])*1000/(end['t']-start['t']),1)
            page.locator('#hybrid-hotspots [data-card="music"]').click()
            page.wait_for_selector('#hybrid-room-frame[data-phase="detail"]')
            still()
            page.keyboard.press('Escape')
            page.wait_for_selector('#hybrid-room-frame[data-phase="room"]')
            page.wait_for_function('chfEffectsProbe().running')
            page.locator('#hybrid-outside').click()
            page.wait_for_function('chfExteriorProbe().mode === "exterior"')
            still()
            # Failed media leaves the unlit logs; no synthetic fallback.
            page.route('**/fireplace-simulated.webm*', lambda r:r.fulfill(status=200, content_type='video/webm', body='invalid media'))
            page.goto(served.url('house?compare=exterior&scene=living&light=day'))
            page.wait_for_function('window.chfEffectsProbe?.().failed')
            still()
            assert page.locator('#hybrid-overview canvas').count() == 0
            assert not served.errors(), served.errors()
            video = page.video
            page.context.close()
            video.save_as(str(out/'flames.webm'))
        (out/'results.json').write_text(json.dumps(results,indent=2))
        print('PASS: simulated frames, unlit log backgrounds, lazy load, looping, projection, stop/resume and media failure')
    finally:
        served.stop()


if __name__ == '__main__':
    main()

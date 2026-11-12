"""Editor lighting Chromium scenarios, written for Claude to run; do not run in Codex.

Uses the real household model harness, a midnight clock, and GPU rendering.
TWIN_EDITOR_OUTPUT optionally receives editor-day/night/unlit.png.
"""
import os
from pathlib import Path
import statistics

import house_editor_model_harness as H

MIDNIGHT = '2026-06-22T00:00:00Z'


def setup():
    served = H.serve()
    if served is not None:
        from services import storage, twin_store
        storage.patch_settings({'home_location': 'Editor lighting fixture', 'timezone': 'Etc/UTC'})
        storage.set_cached_geocode('Editor lighting fixture', 40, 0)
        twin_store.set_front_bearing(180)
    return served


def open_editor(page, served):
    # Pin Date before mount, while preserving performance.now and real timers.
    page.add_init_script("""{
      const NativeDate=Date;
      window.Date=class extends NativeDate {
        constructor(...args){super(...(args.length ? args : ['2026-06-22T00:00:00Z']));}
        static now(){return NativeDate.parse('2026-06-22T00:00:00Z');}
      };
    }""")
    H.open_editor(page, served)
    page.evaluate('(iso) => {const v=window.__twin;v.setClock(iso);v.setView("ext");v.setCamera("front");}', MIDNIGHT)
    H.settle(page, 4)


def choose(page, mode):
    page.click(f'[data-editor-lighting="{mode}"]')
    H.settle(page, 4)
    H.check(page.locator(f'[data-editor-lighting="{mode}"]').get_attribute('aria-pressed') == 'true',
            ('chosen lighting is accessible', mode))


def mean_luminance(page):
    return page.evaluate("""() => {
      const v=window.__twin,r=v.renderer3,gl=r.getContext();v.render();
      const w=gl.drawingBufferWidth,h=gl.drawingBufferHeight,p=new Uint8Array(w*h*4);
      gl.readPixels(0,0,w,h,gl.RGBA,gl.UNSIGNED_BYTE,p);
      let sum=0,n=0;
      for(let y=Math.floor(h*.1);y<h*.9;y+=8)for(let x=Math.floor(w*.1);x<w*.9;x+=8){
        const i=(y*w+x)*4;sum+=.2126*p[i]+.7152*p[i+1]+.0722*p[i+2];n++;
      }
      return sum/n;
    }""")


def shot(page, name):
    if os.environ.get('TWIN_EDITOR_OUTPUT'):
        output = Path(os.environ['TWIN_EDITOR_OUTPUT'])
        output.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output / f'editor-{name}.png'), full_page=True)


def no_errors(served):
    errors = served.errors() if callable(served.errors) else served.errors
    H.check(not H.unexpected(errors), ('browser errors', errors))


def scenario_midnight_opens_day_and_night_is_darker():
    served = setup()
    if served is None:
        return
    with served.browser(launch_args=H.GPU_ARGS) as page:
        open_editor(page, served)
        H.check(page.evaluate('() => window.__twin.state.time') == 'day', 'editor defaults Day at midnight')
        day = mean_luminance(page)
        shot(page, 'day')
        choose(page, 'night')
        night = mean_luminance(page)
        shot(page, 'night')
        print(f'    luminance day={day:.2f}, night={night:.2f}')
        H.check(day > 50 and night < day * .7, ('Day is bright; Night darker', day, night))
        no_errors(served)


def frame_ms(page):
    # Measure completed renderer work, not vsync-limited rAF intervals. Force
    # completion once per batch so GPU time is included on the identical view.
    return page.evaluate("""async () => {
      const v=window.__twin,r=v.renderer3,gl=r.getContext();
      await r.compileAsync(v.scene,v.camera);
      for(let i=0;i<10;i++)v.render();gl.finish();
      const start=performance.now();
      for(let i=0;i<60;i++)v.render();gl.finish();
      return (performance.now()-start)/60;
    }""")


def scenario_unlit_is_bright_and_no_slower_than_day():
    served = setup()
    if served is None:
        return
    with served.browser(launch_args=H.GPU_ARGS) as page:
        open_editor(page, served)
        samples = {'day': [], 'unlit': []}
        camera = page.evaluate('() => window.__twin.cameraState()')
        for _ in range(5):
            for mode in ('day', 'unlit'):
                choose(page, mode)
                samples[mode].append(frame_ms(page))
        day, unlit = (statistics.median(samples[m]) for m in ('day', 'unlit'))
        light = mean_luminance(page)
        shot(page, 'unlit')
        print(f'    renderer ms/frame Day={day:.3f}, Unlit={unlit:.3f}; samples={samples}; luminance={light:.2f}')
        H.check(light > 50, ('Unlit is bright', light))
        H.check(unlit <= day, ('Unlit costs at most Day on the same view', day, unlit))
        after = page.evaluate('() => window.__twin.cameraState()')
        drift = max(abs(a - b) for k in ('position', 'target') for a, b in zip(after[k], camera[k]))
        H.check(drift < 0.05, ('same camera throughout (switching lighting never moves it)', camera, after))
        no_errors(served)


def scenario_second_unlit_toggle_compiles_no_programs():
    served = setup()
    if served is None:
        return
    with served.browser(launch_args=H.GPU_ARGS) as page:
        open_editor(page, served)
        page.evaluate("""() => {
          const gl=window.__twin.renderer3.getContext(),create=gl.createProgram.bind(gl);
          window.__lightingPrograms=0;
          gl.createProgram=(...args)=>{window.__lightingPrograms++;return create(...args);};
        }""")
        choose(page, 'unlit')
        frame_ms(page)
        before = page.evaluate('() => [window.__lightingPrograms,window.__twin.renderer3.info.programs.length]')
        for mode in ('day', 'unlit', 'day', 'unlit'):
            choose(page, mode)
            frame_ms(page)
            after = page.evaluate('() => [window.__lightingPrograms,window.__twin.renderer3.info.programs.length]')
            H.check(after == before, ('toggles retain cached GPU programs', mode, before, after))
        no_errors(served)


def scenario_reload_keeps_each_choice():
    served = setup()
    if served is None:
        return
    with served.browser(launch_args=H.GPU_ARGS) as page:
        open_editor(page, served)
        for mode in ('night', 'unlit', 'now', 'day'):
            choose(page, mode)
            page.reload()
            page.wait_for_function('() => window.__editor?.ready && window.__twin?.ready', timeout=90000)
            H.check(page.locator(f'[data-editor-lighting="{mode}"]').get_attribute('aria-pressed') == 'true',
                    ('reload restores device choice', mode))
            H.check(page.evaluate('() => window.__twin.state.unlit') == (mode == 'unlit'), ('reload Unlit', mode))
            H.check(page.evaluate('() => window.__twin.state.time') == ('day' if mode == 'unlit' else mode),
                    ('reload time mode', mode))
        no_errors(served)


def scenario_twin_preview_still_returns_now():
    served = setup()
    if served is None:
        return
    with served.browser(launch_args=H.GPU_ARGS) as page:
        H.signed_in(page)
        H.goto_retry(page, served.url('house/twin?tier=high&test=1'))
        page.wait_for_function('() => window.__twin?.ready', timeout=90000)
        page.evaluate('(iso) => window.__twin.setClock(iso)', MIDNIGHT)
        H.check(page.evaluate('() => window.__twin.state.time') == 'now', 'twin default remains Now')
        # Same callback as the real 120-second timer; Node checks its timing.
        for mode in ('day', 'night'):
            page.click(f'[data-time="{mode}"]')
            H.check(page.evaluate('() => window.__twin.state.time') == mode, ('preview mode', mode))
            page.evaluate('() => window.__twin.expireTimePreview()')
            H.check(page.evaluate('() => window.__twin.state.time') == 'now', 'preview timeout restores Now')
            H.check(page.locator('[data-time="now"]').get_attribute('aria-pressed') == 'true', 'Now button syncs')
        no_errors(served)


SCENARIOS = [scenario_midnight_opens_day_and_night_is_darker,
             scenario_unlit_is_bright_and_no_slower_than_day,
             scenario_second_unlit_toggle_compiles_no_programs,
             scenario_reload_keeps_each_choice,
             scenario_twin_preview_still_returns_now]

if __name__ == '__main__':
    H.run(SCENARIOS)

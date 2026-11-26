"""Chromium check for the ?grid=1 light-visibility grid debug overlay and editor bake stats.

Run from chauffeur/: python tests/test_house_twin_grid_debug_live.py
"""
from pathlib import Path
import re

import test_house_twin_bake_live as B
import test_house_twin_model_light_live as M

L, H, RL, check = B.L, B.H, B.RL, B.check

SHOT_PATH = Path(r'E:\repositories\Chauffeur-models-bake\.gemini-tmp\shots\grid_debug.png')


def _bake_in_editor_and_check_status(page, served):
    context, editor = B.other_page(page)
    try:
        B.open_editor(editor, served)
        if B.state(editor)['stale']:
            B.start_editor_bake(editor)
        st = B.wait_baked(editor)
        status_text = editor.locator('#twin-bake-controls output').text_content() or ''
        print('editor_post_bake_status:', status_text)
        check('Lighting is up to date' in status_text, ('editor says up to date', status_text))
        check(re.search(r'Grid \d+ points, \d+ KB', status_text) is not None,
              ('editor status shows grid points and KB after bake', status_text))
        return st
    finally:
        context.close()


def _setup_room_view(page):
    page.evaluate(
        "() => { const v = window.__twin; "
        "v.levels.go({building:'pool-house', floor:'L1'}, {immediate:true}); "
        "v.setTime('night'); v.setNightBrightness(0.25, {persist:false}); }"
    )
    RL.lights_mode(page)
    page.wait_for_function("() => window.__twin.bake.models?.stats().bricks >= 2", timeout=90000)
    B.only_on(page, 'light.ceiling_light', brightness=255, rgb_color=[255, 255, 255])
    M.frame_samples(page)
    H.settle(page, 3)


def scenario_grid_debug_overlay_and_budget():
    s = M.fixture()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        _bake_in_editor_and_check_status(page, s)

        # 1. Without ?grid=1: zero DOM, zero THREE.Points, zero listeners/controller.
        B.open_desk(page, s, query='tier=high&test=1')
        B.wait_baked(page)
        _, ext_off = M._wait_programs_settled(page, stable_seconds=2)
        check(ext_off, 'exterior programs settle without ?grid=1')
        _setup_room_view(page)
        snap_off, settled_off = M._wait_programs_settled(page, stable_seconds=2)
        check(settled_off, 'programs settle without ?grid=1')
        no_flag = page.evaluate("""() => {
          const v = window.__twin;
          let debugPoints = 0;
          v.scene.traverse(o => { if (o.isPoints && o.name === 'twin-grid-debug-points') debugPoints++; });
          return {
            hasController: !!v.gridDebug,
            hasDom: !!document.querySelector('#twin-grid-debug'),
            debugPoints,
            draws: v.renderer3.info.render.calls,
            programs: (v.renderer3.info.programs || []).length,
          };
        }""")
        print('without_grid_flag:', no_flag)
        check(not no_flag['hasController'], 'no gridDebug controller without ?grid=1')
        check(not no_flag['hasDom'], 'no #twin-grid-debug DOM without ?grid=1')
        check(no_flag['debugPoints'] == 0, 'no debug THREE.Points without ?grid=1')

        # 2. With ?grid=1: select appears, choosing a lamp displays points with <=1 new program.
        B.open_desk(page, s, query='tier=high&test=1&grid=1')
        B.wait_baked(page)
        _, ext_on = M._wait_programs_settled(page, stable_seconds=2)
        check(ext_on, 'exterior programs settle with ?grid=1')
        _setup_room_view(page)
        page.wait_for_function(
            "() => (document.querySelector('#twin-grid-debug select')?.options.length || 0) > 1",
            timeout=30000,
        )
        snap_before, settled_before = M._wait_programs_settled(page, stable_seconds=2)
        check(settled_before, 'programs settle with ?grid=1 before choosing a lamp')
        before = page.evaluate("""() => {
          const v = window.__twin;
          const select = document.querySelector('#twin-grid-debug select');
          return {
            programs: (v.renderer3.info.programs || []).length,
            draws: v.renderer3.info.render.calls,
            visible: !!v.gridDebug?.points?.visible,
            options: Array.from(select.options).map(o => [o.value, o.textContent]),
          };
        }""")
        check(not before['visible'], 'points are hidden before choosing a lamp')
        check(any(v == 'dev-k-ceiling' for v, _ in before['options']), ('ceiling lamp listed', before['options']))

        # Capture canvas pixel hash before selecting a lamp to prove points actually draw.
        before_canvas_sample = page.evaluate("""() => {
          const v = window.__twin, r = v.renderer3, c = r.domElement;
          const gl = r.getContext();
          const px = new Uint8Array(c.width * c.height * 4);
          v.render();
          gl.readPixels(0, 0, c.width, c.height, gl.RGBA, gl.UNSIGNED_BYTE, px);
          let sum = 0;
          for (let i = 0; i < px.length; i += 16) sum += px[i] + px[i + 1] + px[i + 2];
          return sum;
        }""")

        page.select_option('#twin-grid-debug select', 'dev-k-ceiling')
        H.settle(page, 3)

        after = page.evaluate("""() => {
          const v = window.__twin;
          const pts = v.gridDebug?.points;
          const pos = pts?.geometry?.attributes?.position;
          const col = pts?.geometry?.attributes?.color;
          let red = 0, bright = 0, dark = 0;
          if (col) {
            for (let i = 0; i < col.count; i++) {
              const r = col.getX(i), g = col.getY(i), b = col.getZ(i);
              if (r > 0.9 && g < 0.1 && b < 0.1) red++;
              else if (r > 0.5 && g > 0.5 && b > 0.5) bright++;
              else if (r < 0.05 && g < 0.05 && b < 0.05) dark++;
            }
          }
          const r3 = v.renderer3, c = r3.domElement, gl = r3.getContext();
          const px = new Uint8Array(c.width * c.height * 4);
          v.render();
          gl.readPixels(0, 0, c.width, c.height, gl.RGBA, gl.UNSIGNED_BYTE, px);
          let sum = 0;
          for (let i = 0; i < px.length; i += 16) sum += px[i] + px[i + 1] + px[i + 2];
          return {
            programs: (v.renderer3.info.programs || []).length,
            programList: (v.renderer3.info.programs || []).map(p => ({ name: p.name, key: p.cacheKey })),
            draws: v.renderer3.info.render.calls,
            visible: !!pts?.visible,
            layer31: !!pts?.layers?.isEnabled(31),
            layer0: !!pts?.layers?.isEnabled(0),
            pointCount: pos?.count || 0,
            red, bright, dark,
            canvasSum: sum,
          };
        }""")
        off_keys = {p['key']: p['name'] for p in snap_off['programs']}
        before_keys = {p['key']: p['name'] for p in snap_before['programs']}
        after_keys = {p['key']: p['name'] for p in after['programList']}
        print('with_grid_flag_before:', {k: before[k] for k in ('programs', 'draws', 'visible')})
        print('with_grid_flag_after:', {k: v for k, v in after.items() if k != 'programList'})
        print('new_programs_vs_before:', [(after_keys[k], k[:120]) for k in sorted(set(after_keys) - set(before_keys))])
        print('new_programs_vs_no_flag:', [(after_keys[k], k[:120]) for k in sorted(set(after_keys) - set(off_keys))])
        print('only_in_no_flag:', [(off_keys[k], k[:120]) for k in sorted(set(off_keys) - set(after_keys))])
        program_delta = after['programs'] - before['programs']
        program_delta_vs_no_flag = after['programs'] - no_flag['programs']
        draw_delta = after['draws'] - before['draws']
        print(f'deltas: programs_vs_before=+{program_delta} programs_vs_no_flag=+{program_delta_vs_no_flag} draws=+{draw_delta} points={after["pointCount"]}')

        check(after['visible'], 'points are visible after choosing a lamp')
        check(after['layer31'], 'points are on layer 31')
        check(after['layer0'], 'points remain drawable by the main camera')
        check(after['pointCount'] > 0, ('points geometry populated', after['pointCount']))
        check(after['bright'] > 0, ('has visible lit points', after))
        check(after['canvasSum'] != before_canvas_sample,
              ('canvas pixels changed when points became visible', before_canvas_sample, after['canvasSum']))
        check(program_delta <= 1, ('program count rises by at most 1', before['programs'], after['programs']))
        check(program_delta_vs_no_flag <= 1,
              ('program count rises by at most 1 vs no-flag baseline', no_flag['programs'], after['programs']))
        check(draw_delta <= 1, ('draw count rises by at most 1', before['draws'], after['draws']))

        # Save screenshot of the live ?grid=1 view with the lamp selected.
        SHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        page.mouse.move(10, 10)
        H.settle(page, 2)
        page.screenshot(path=str(SHOT_PATH))
        check(SHOT_PATH.exists() and SHOT_PATH.stat().st_size > 10000, ('screenshot saved', str(SHOT_PATH)))

        # Verify stop() cleans up DOM and scene points.
        cleaned = page.evaluate("""() => {
          const v = window.__twin;
          v.gridDebug.stop();
          let debugPoints = 0;
          v.scene.traverse(o => { if (o.isPoints && o.name === 'twin-grid-debug-points') debugPoints++; });
          return { hasDom: !!document.querySelector('#twin-grid-debug'), debugPoints, ctrl: v.gridDebug };
        }""")
        check(not cleaned['hasDom'] and cleaned['debugPoints'] == 0 and cleaned['ctrl'] is None, ('stop() cleaned up', cleaned))
        L.no_errors(s)


if __name__ == '__main__':
    L.run([scenario_grid_debug_overlay_and_budget])

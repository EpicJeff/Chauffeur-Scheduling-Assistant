"""Household High acceptance. Written for Claude to run; Codex must not launch Chromium.

From chauffeur/: python tests/test_house_editor_plain_selection_live.py
Screenshots and timing evidence go to PLAIN_SELECTION_REVIEW_OUTPUT or a temp folder.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import tempfile

os.environ.pop('HA_BASE_URL', None)
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='plain_selection_live_')
sys.path.insert(0, str(Path(__file__).resolve().parent))
import house_editor_model_harness as H

SHOTS = Path(os.environ.get('PLAIN_SELECTION_REVIEW_OUTPUT') or tempfile.mkdtemp(prefix='plain_selection_shots_'))


def shaders_settled(page):
    page.evaluate("""async () => {
      const v=window.__twin; await v.compileBehind?.(); await v.selectionReady;
      let last=-1, stable=0;
      for(let i=0;i<900;i++) {
        await new Promise(r=>setTimeout(r,100));
        const n=v.renderer3.info.programs.length;
        stable=n===last?stable+1:0;last=n;
        if(stable>=10 && v.ready && !v.yardSettling) return;
      }
      throw Error('shader programs did not settle in 90 seconds');
    }""")


@contextmanager
def editor():
    served = H.serve()
    assert served is not None, 'Playwright is required'
    from services import twin_store
    twin_store.start_over()
    twin_store.push_round(H.household_plan(), 'build')
    browser = served.browser(launch_args=H.GPU_ARGS)
    with browser as page:
        H.open_editor(page, served, query='tier=high&test=1')
        shaders_settled(page)
        page.evaluate("""() => {
          const v=window.__twin, original=v.rebuild.bind(v);
          window.__plainProbe={rebuilds:0,tasks:[],records:[]};
          v.rebuild=(...args)=>{window.__plainProbe.rebuilds++;return original(...args);};
          window.__plainObserver=new PerformanceObserver(list=>{
            window.__plainProbe.tasks.push(...list.getEntries().map(e=>({start:e.startTime,duration:e.duration})));
          });window.__plainObserver.observe({type:'longtask'});
        }""")
        SHOTS.mkdir(parents=True, exist_ok=True)
        yield page
        (SHOTS / 'timings.json').write_text(json.dumps(page.evaluate('window.__plainProbe'), indent=2), encoding='utf-8')
        assert not H.unexpected(browser.errors), browser.errors


def begin_measure(page):
    H.settle(page, 3)
    return page.evaluate("""() => ({start:performance.now(),rebuilds:window.__plainProbe.rebuilds,
      programs:window.__twin.renderer3.info.programs.length})""")


def end_measure(page, before, label, maximum=250, programs=True):
    # Let PerformanceObserver deliver the long task containing the UI event.
    H.settle(page, 4)
    result = page.evaluate("""({before,label}) => {
      const p=window.__plainProbe,v=window.__twin;
      const r={label,rebuilds:p.rebuilds-before.rebuilds,programs:v.renderer3.info.programs.length-before.programs,
        longest:Math.max(0,...p.tasks.filter(t=>t.start>=before.start).map(t=>t.duration))};
      p.records.push(r);return r;
    }""", dict(before=before, label=label))
    assert result['rebuilds'] == 0, result
    assert result['longest'] <= maximum, result
    if programs:
        assert result['programs'] == 0, result
    return result


def select_scene(page, bid, pid):
    # Reveal through the normal selection entrypoint before clicking the real Scene row.
    page.evaluate('([bid,pid])=>window.__editor.clickPiece(pid,bid)', [bid, pid])
    page.click('#dock-tab-scene')
    if pid in [l['id'] for l in page.evaluate('bid=>window.__twin.plan.buildings.find(b=>b.id===bid).levels', bid)]:
        row = page.locator(f'#scene-tree [data-floor="{bid}:{pid}"]')
    else:
        row = page.locator(f'#scene-tree [data-scene-id="{pid}"] [data-scene-select]')
    row.scroll_into_view_if_needed()
    row.click()
    page.wait_for_function('pid=>window.__editor.selected()?.pieceId===pid', arg=pid)


def scenario_plain_selection_focus_drag_undo():
    with editor() as page:
        rooms = page.evaluate("""() => window.__twin.plan.buildings.flatMap(b=>b.rooms
          .filter(r=>r.state!=='ghost').map(r=>({bid:b.id,id:r.id,kind:r.kind,level:r.level,polygon:r.polygon})))""")
        porch = next(r for r in rooms if r.get('kind') == 'porch')
        bid, rid, level = porch['bid'], porch['id'], porch['level']
        H.choose_floor(page, f'{bid}:{level}')
        page.evaluate('key=>window.__twin.setTopCamera(key)', f'{bid}:{level}')
        shaders_settled(page)
        # Find a clear point that the actual ray picker resolves to this porch.
        point = page.evaluate("""({bid,rid,level})=>{
          const v=window.__twin,r=v.plan.buildings.find(b=>b.id===bid).rooms.find(r=>r.id===rid);
          const xs=r.polygon.map(p=>p[0]),ys=r.polygon.map(p=>p[1]);
          for(let i=1;i<10;i++)for(let j=1;j<10;j++){
            const x=Math.min(...xs)+(Math.max(...xs)-Math.min(...xs))*i/10;
            const y=Math.min(...ys)+(Math.max(...ys)-Math.min(...ys))*j/10;
            const pixel=v.screenOfFloor(x,y,`${bid}:${level}`),hit=v.pick(...pixel);
            if(hit?.id===rid&&hit.building===bid)return pixel;
          }return null;
        }""", dict(bid=bid, rid=rid, level=level))
        assert point, 'no unobscured porch point for a real canvas click'
        before = begin_measure(page)
        H._on_canvas(page, *point)
        page.mouse.click(*point)
        page.wait_for_function('rid=>window.__editor.selected()?.pieceId===rid', arg=rid)
        end_measure(page, before, 'porch canvas click')
        assert page.evaluate('window.__twinEditor.selection().room') is None
        page.screenshot(path=str(SHOTS / 'plain-porch-click.png'))

        for row in [porch, next(r for r in rooms if r.get('kind') != 'porch'),
                    next(r for r in rooms if r['bid'] != bid), dict(bid=bid, id=level)]:
            before = begin_measure(page)
            select_scene(page, row['bid'], row['id'])
            end_measure(page, before, f"Scene {row['bid']}:{row['id']}")
            assert page.evaluate('window.__twinEditor.selection().room') is None

        select_scene(page, bid, rid)
        before = begin_measure(page)
        page.locator('#piece-card').get_by_role('button', name='Focus room', exact=True).click()
        page.evaluate('async()=>await window.__twin.selectionReady')
        end_measure(page, before, 'first focus entry', maximum=500, programs=False)
        assert page.evaluate('window.__twinEditor.selection().room') == rid
        page.screenshot(path=str(SHOTS / 'focused-porch.png'))
        shaders_settled(page)
        before = begin_measure(page)
        page.locator('#piece-card').get_by_role('button', name='Leave room', exact=True).click()
        end_measure(page, before, 'leave focus', maximum=500)
        assert page.evaluate('window.__twinEditor.selection().room') is None
        # Warm re-entry and Escape must both meet the focus gate.
        before = begin_measure(page)
        page.locator('#piece-card').get_by_role('button', name='Focus room', exact=True).click()
        page.evaluate('async()=>await window.__twin.selectionReady')
        end_measure(page, before, 'warm focus entry', maximum=500)
        before = begin_measure(page)
        page.locator('#rail-select').focus()
        page.keyboard.press('Escape')
        end_measure(page, before, 'Escape leaves focus', maximum=500)
        assert page.evaluate('window.__twinEditor.selection().room') is None

        wall = page.evaluate("""bid=>window.__twin.plan.buildings.find(b=>b.id===bid).walls
          .find(w=>w.state!=='ghost'&&w.kind!=='separator')""", bid)
        H.choose_floor(page, f"{bid}:{wall['level']}")
        select_scene(page, bid, wall['id'])
        page.evaluate('key=>window.__twin.setTopCamera(key)', f"{bid}:{wall['level']}")
        page.click('#rail-move')
        handle = page.evaluate("window.__twinEditor.handles().find(h=>h.kind==='wall')")
        assert handle, 'wall move handle missing'
        start = H.screen_of_world(page, *handle['at'], bid)
        dx, dy = wall['to'][0] - wall['from'][0], wall['to'][1] - wall['from'][1]
        length = (dx * dx + dy * dy) ** .5
        target = [handle['at'][0] - dy / length, handle['at'][1] + dx / length, handle['at'][2]]
        end = H.screen_of_world(page, *target, bid)
        H._on_canvas(page, *start)
        assert page.evaluate('window.__twinEditor.selection().room') is None
        rebuilds_before_drag = page.evaluate('window.__plainProbe.rebuilds')
        page.mouse.move(*start)
        page.mouse.down()
        page.mouse.move(*end, steps=12)
        assert page.evaluate('window.__plainProbe.rebuilds') == rebuilds_before_drag, 'preview rebuilt the house'
        assert page.evaluate('window.__twinEditor.lastDragFrameMs') is not None, 'no live drag preview'
        page.screenshot(path=str(SHOTS / 'wall-preview-without-focus.png'))
        with page.expect_response(lambda r: r.request.method == 'POST' and r.url.split('?')[0].endswith('/editor/op')) as response:
            page.mouse.up()
        assert response.value.status == 200, response.value.text()
        page.wait_for_function("!document.getElementById('rail-undo').disabled")
        with page.expect_response(lambda r: r.request.method == 'POST' and r.url.split('?')[0].endswith('/revert')) as response:
            page.keyboard.press('Control+z')
        assert response.value.status == 200, response.value.text()
        page.wait_for_function("([bid,w])=>{const p=window.__twin.plan.buildings.find(b=>b.id===bid).walls.find(p=>p.id===w.id);return JSON.stringify([p.from,p.to])===JSON.stringify([w.from,w.to]);}", arg=[bid, wall])
        page.screenshot(path=str(SHOTS / 'wall-undo-without-focus.png'))


if __name__ == '__main__':
    H.run([scenario_plain_selection_focus_drag_undo])

"""Glass/slots Chromium scenarios. Claude runs these at landing.

Run from chauffeur/: python tests/test_twin_glass_slots_live.py
Uses the real Library page, HTTP writes, image decode and WebGL preview.
"""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_glass_slots_live_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from PIL import Image, ImageDraw  # noqa: E402
from live_app import live_app  # noqa: E402

GPU_ARGS = ['--use-angle=gl', '--enable-gpu', '--ignore-gpu-blocklist']
OUTPUT = Path(os.environ['GLASS_SLOTS_OUTPUT']) if 'GLASS_SLOTS_OUTPUT' in os.environ else Path(
    tempfile.mkdtemp(prefix='chauffeur_glass_slots_shots_'))
STATE = {}
SERVED = None


def _unexpected(errors):
    return [e for e in errors if not e.startswith('Failed to load resource')]


def _seed():
    from services import storage, twin_library, twin_materials
    from test_twin_view_live import _stub_urlopen
    # Built-in catalogue thumbnails use the twin's tiny offline JPEG fixtures.
    twin_library._urlopen = _stub_urlopen
    storage.patch_settings({'auth_enforce': True})
    storage.add_member({'id': 'alpha-parent', 'name': 'Pat', 'role': 'parent', 'email': 'pat@example.com'})
    storage.set_member_password('alpha-parent', 'correct horse battery staple')
    STATE['token'] = storage.create_member_token('alpha-parent')
    for key, name in [('blend', 'Preview glass'), ('leaf', 'Leaf cutout')]:
        STATE[key] = twin_materials.create({'name': name, 'params': {'tint': '#e8f5d4'}}, 'alpha-parent')['id']
    STATE['panes'] = twin_materials.create({'name': 'House glass',
        'params': {'alpha_mode': 'blend', 'opacity': .4, 'tint': '#b9d7db'}}, 'alpha-parent')['id']
    STATE['siding'] = twin_materials.create({'name': 'Bake siding',
        'params': {'alpha_mode': 'opaque', 'tint': '#c9c4b8'}}, 'alpha-parent')['id']
    # The recorded house has a gable main roof and a separate shed porch roof.
    # Keep its rooms, openings, porch and yard for the wall-size editor screenshot.
    from services import twin_store
    plan = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    building = next(b for b in plan['buildings'] if b['id'] == 'pool-house')
    for key, kind, name, tint in [('roof_main', 'gable', 'Main roof shingles', '#635b55'),
                                   ('roof_porch', 'shed', 'Porch roof metal', '#85949b')]:
        section = next(s for s in building['roof']['sections'] if s['kind'] == kind)
        section['name'] = 'Main roof' if kind == 'gable' else 'Porch roof'
        section.pop('material', None)
        STATE[key] = section['id']
        STATE[key + '_material'] = twin_materials.create(
            {'name': name, 'params': {'tint': tint, 'roughness': .8 if kind == 'gable' else .4}},
            'alpha-parent')['id']
    twin_store.push_round(plan, 'build')


def _serve():
    global SERVED
    if SERVED is None:
        SERVED = live_app(_seed)
    return SERVED


def _settle(page):
    page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')


def _pixel(canvas):
    # Canvas screenshots work with WebGL's default preserveDrawingBuffer=false.
    image = Image.open(io.BytesIO(canvas.screenshot())).convert('RGB')
    return image.getpixel((image.width // 2, image.height // 2))


def _number(page, key, value):
    page.locator(f'[data-param="{key}"][type="range"]').evaluate('''(input, value) => {
        input.value = String(value); input.dispatchEvent(new Event('input', {bubbles: true}));
    }''', value)
    _settle(page)


def _saved(page, mid, mode, opacity=None):
    page.wait_for_function('''async ({mid, mode, opacity}) => {
        const response = await fetch(window.chfBase + 'api/house/materials/' + mid);
        if (!response.ok) return false;
        const row = await response.json();
        return row.params.alpha_mode === mode && (opacity === null || row.params.opacity === opacity);
    }''', arg={'mid': mid, 'mode': mode, 'opacity': opacity}, timeout=15000, polling=500)


def scenario_L1_library_blend_and_leaf_cutout():
    served = _serve()
    if served is None:
        raise AssertionError('Chromium is required for L1 visual verification')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with served.browser(launch_args=GPU_ARGS, color_scheme='dark') as page:
        # Match house_editor_model_harness.signed_in: a real parent session.
        page.add_init_script('''if (location.protocol.startsWith('http')) { try {
            localStorage.setItem('chauffeur_admin_token', %s);
            localStorage.setItem('chauffeur_admin_token_for', 'alpha-parent');
            localStorage.setItem('chauffeur_theme', 'dark');
        } catch (e) {} }''' % json.dumps(STATE['token']))
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(served.url('house/library?material=' + STATE['blend']))
        page.wait_for_function('() => !!window.materialLibraryPage', polling=500)
        page.evaluate('() => window.materialLibraryPage.ready')
        page.locator('[data-action="wall"]').click()
        canvas = page.locator('#material-library canvas')
        mode = page.locator('[data-param="alpha_mode"]')
        _settle(page)
        opaque = _pixel(canvas)
        mode.select_option('blend')
        opacity = page.locator('[data-param="opacity"][type="range"]')
        opacity.wait_for(state='visible')
        _number(page, 'opacity', .4)
        _saved(page, STATE['blend'], 'blend', .4)
        blended = _pixel(canvas)
        assert sum(abs(a - b) for a, b in zip(opaque, blended)) > 12, (opaque, blended)
        page.screenshot(path=str(OUTPUT / 'L1-library-blend-dark.png'), full_page=True)

        page.locator(f'[data-material="{STATE["leaf"]}"]').click()
        page.wait_for_function("() => document.querySelector('[data-field=\"name\"]')?.value === 'Leaf cutout'", polling=500)
        image = Image.new('RGBA', (64, 64), (40, 130, 60, 0))
        ImageDraw.Draw(image).ellipse((8, 6, 52, 58), fill=(40, 130, 60, 255))
        buf = io.BytesIO()
        image.save(buf, format='PNG')
        page.locator('[data-slot="base_color"] input[type="file"]').set_input_files({
            'name': 'leaf_basecolor.png', 'mimeType': 'image/png', 'buffer': buf.getvalue()})
        _saved(page, STATE['leaf'], 'cutout')
        page.wait_for_function("() => document.querySelector('[data-param=\"alpha_mode\"]')?.value === 'cutout'", polling=500)
        assert mode.input_value() == 'cutout'
        mask = page.locator('[data-slot="opacity"] img')
        mask.wait_for(state='visible')
        page.wait_for_function("() => {const img=document.querySelector('[data-slot=\"opacity\"] img'); return img?.complete && img.naturalWidth > 0;}", polling=500)
        assert 'From the base colour' in page.locator('[data-slot="opacity"]').inner_text()
        assert page.locator('[data-param="alpha_cutoff"][type="range"]').is_visible()
        page.screenshot(path=str(OUTPUT / 'L1-library-leaf-dark.png'), full_page=True)
        assert not _unexpected(errors), _unexpected(errors)
        assert not served.errors(), served.errors()


def scenario_L2_house_materials_panes_and_draw_budget():
    served = _serve()
    if served is None:
        raise AssertionError('Chromium is required for L2 visual verification')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with served.browser(launch_args=GPU_ARGS, color_scheme='dark') as page:
        page.set_viewport_size({'width': 1920, 'height': 1080})
        page.add_init_script('''if (location.protocol.startsWith('http')) { try {
            localStorage.setItem('chauffeur_admin_token', %s);
            localStorage.setItem('chauffeur_admin_token_for', 'alpha-parent');
            localStorage.setItem('chauffeur_theme', 'dark');
        } catch (e) {} }''' % json.dumps(STATE['token']))
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(served.url('house/editor?tier=low&test=1&perf=1'))
        page.wait_for_function('() => window.__editor?.ready && window.__twin?.ready', timeout=90000, polling=500)
        if page.locator('#editor-dialog #place-view').is_visible():
            page.locator('#place-close').click()
        # Use the person's navigation path, rather than the selection test hook.
        floor = page.locator('#dock-pane-scene #editor-floors [data-floor^="pool-house:"]').first
        floor.click()
        page.locator('#dock-pane-scene #editor-floors').get_by_role('button', name='All floors', exact=True).click()
        page.locator('#dock-pane-scene #editor-floors').get_by_role('button', name='Change the house', exact=True).click()
        # Since slice 4 the building card's House materials is a button that opens the centred dialog.
        page.locator('#piece-card').get_by_role('button', name='House materials', exact=True).click()
        page.locator('#editor-dialog #house-materials [data-library-slot="Panes"]').wait_for()
        page.wait_for_function('() => window.__twin?.ready', polling=500)
        page.wait_for_function('() => /\\d+ draws/.test(document.querySelector(".twin-frame-meter")?.textContent || "")', polling=500)
        before = page.evaluate('() => window.__twin.stats().drawCalls')
        slot = page.locator('#editor-dialog #house-materials [data-library-slot="Panes"]')
        page.locator('#dock-tab-library').click()
        page.locator(f'#library-entries [data-material="{STATE["panes"]}"]').click()
        slot.locator('[data-slot-use]').click()
        page.wait_for_function('''mid => {
            const v = window.__twin, b = v.plan.buildings.find(b => b.id === 'pool-house');
            if (b.materials?.pane?.id !== mid || !v.ready) return false;
            const panes = [];
            v.scene.traverse(o => {
                let parent = o; while (parent && !parent.userData.buildingId) parent = parent.parent;
                if (o.isMesh && !o.layers.isEnabled(31) && parent?.userData.buildingId === b.id && o.material?.name === 'glass') panes.push(o);
            });
            return panes.length > 0 && panes.every(o => o.material.userData.materialId === mid);
        }''', arg=STATE['panes'], polling=500)
        _settle(page)
        after = page.evaluate('() => window.__twin.stats().drawCalls')
        assert after <= before, (before, after)
        page.screenshot(path=str(OUTPUT / 'L2-house-materials-panes-dark-wall.png'), full_page=True)
        assert not _unexpected(errors), _unexpected(errors)
        assert not served.errors(), served.errors()


def scenario_L3_siding_mode_flip_drops_and_restores_finished_bake():
    """Real bake, material page, watcher rebuild and retained-page reload.

    The editor's chip is round-based ('Lights wait to re-bake'), not an alpha
    status. Assert the twin's actual unbaked state and shader bindings here.
    """
    served = _serve()
    if served is None:
        raise AssertionError('Chromium is required for L3 visual verification')
    from services import twin_store
    plan = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    building = next(b for b in plan['buildings'] if b['id'] == 'pool-house')
    building.setdefault('materials', {})['siding'] = {'id': STATE['siding']}
    # One real household building; omit distant yard pages to bound bake time.
    plan['buildings'] = [building]
    plan['site'] = {}
    twin_store.push_round(plan, 'build')
    room = next(r for r in building['rooms'] if r.get('kind') != 'porch')
    # A marker's place is on the lot; the room polygon is in the building's own frame.
    from services.twin_register import to_world
    at = to_world(building, [sum(p[i] for p in room['polygon']) / len(room['polygon']) for i in (0, 1)]) + [6]
    live = {'markers': [{'device_id': 'slot-bake-light', 'entity_id': 'light.slot_bake', 'kind': 'light',
        'placed': True, 'building': building['id'], 'level': room['level'], 'room': room['id'],
        'at': at, 'name': 'Room lamp'}], 'rooms': [], 'fixtures': []}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with served.browser(launch_args=GPU_ARGS, color_scheme='dark') as twin:
        twin.set_viewport_size({'width': 1920, 'height': 1080})
        twin.add_init_script('''if (location.protocol.startsWith('http')) { try {
            localStorage.setItem('chauffeur_admin_token', %s);
            localStorage.setItem('chauffeur_admin_token_for', 'alpha-parent');
            localStorage.setItem('chauffeur_theme', 'dark');
        } catch (e) {} }''' % json.dumps(STATE['token']))
        twin.route('**/api/house/live', lambda route: route.fulfill(json=live))
        errors = []
        twin.on('pageerror', lambda error: errors.append(str(error)))
        # Since v2.499.974 lighting bakes from the editor, by button only; the
        # viewer shows bake status and never bakes.
        twin.goto(served.url('house/editor?tier=high&test=1'))
        twin.wait_for_function('() => window.__editor?.ready && window.__twin?.ready && window.__twin.bake',
                               timeout=90000, polling=500)
        if twin.locator('#editor-dialog #place-view').is_visible():
            twin.locator('#place-close').click()
        twin.get_by_role('button', name='Bake lighting', exact=True).click(timeout=90000)
        # The editor uploads the bake; the viewer below is what holds its pages.
        twin.wait_for_function('''() => {
            const b = window.__twin.bake;
            return !b.state().baking && !b.state().error && b.fresh().includes('slot-bake-light');
        }''', timeout=900000, polling=500)
        old_key = twin.evaluate('() => window.__twin.bake.state().key')
        twin.goto(served.url('house/twin?tier=low&test=1'))
        twin.wait_for_function('() => window.__twin?.ready && window.__twin.bake?.fresh().includes("slot-bake-light") && !!window.__twin.bake.held()',
                               timeout=90000, polling=500)
        assert twin.evaluate('() => window.__twin.bake.state().key') == old_key
        twin.screenshot(path=str(OUTPUT / 'L3-finished-bake-dark-wall.png'), full_page=True)
        # The rig's page owns its context, so the Library opens in a second one.
        other = twin.context.browser.new_context(color_scheme='dark')
        library = other.new_page()
        library.add_init_script('''if (location.protocol.startsWith('http')) { try {
            localStorage.setItem('chauffeur_admin_token', %s);
            localStorage.setItem('chauffeur_admin_token_for', 'alpha-parent');
            localStorage.setItem('chauffeur_theme', 'dark');
        } catch (e) {} }''' % json.dumps(STATE['token']))
        try:
            library.on('pageerror', lambda error: errors.append(str(error)))
            library.goto(served.url('house/library?material=' + STATE['siding']))
            library.wait_for_function('() => !!window.materialLibraryPage', polling=500)
            library.evaluate('() => window.materialLibraryPage.ready')
            library.locator('[data-param="alpha_mode"]').select_option('cutout')
            _saved(library, STATE['siding'], 'cutout')
            twin.bring_to_front()
            twin.wait_for_function('''oldKey => {
                const v = window.__twin, b = v?.bake;
                if (!v?.ready || !b?.state().key || b.state().key === oldKey || b.fresh().length || b.held()) return false;
                let clean = true;
                v.scene.traverse(o => { for (const m of [].concat(o.material || []))
                    if (m.lightMap || m.userData.lmOriginalKey !== undefined) clean = false; });
                return clean && !b.state().error;
            }''', arg=old_key, timeout=90000, polling=500)
            twin.screenshot(path=str(OUTPUT / 'L3-cutout-unbaked-dark-wall.png'), full_page=True)
            library.bring_to_front()
            library.locator('[data-param="alpha_mode"]').select_option('opaque')
            _saved(library, STATE['siding'], 'opaque')
            twin.bring_to_front()
            # The layout key comes back and the stored pages mount again, but a light's own
            # key carries the material's revision (reach.js), and two saves moved it on:
            # the lamp waits for a baking desk and is never drawn from the older bake.
            twin.wait_for_function('''oldKey => {
                const b = window.__twin?.bake;
                return b?.state().key === oldKey && !b.state().error && !!b.held() && !b.fresh().length &&
                    b.state().stale.includes('slot-bake-light');
            }''', arg=old_key, timeout=90000, polling=500)
            twin.screenshot(path=str(OUTPUT / 'L3-opaque-layout-restored-dark-wall.png'), full_page=True)
        finally:
            other.close()
        assert not _unexpected(errors), _unexpected(errors)
        # No bake exists at first, so the manifest and page reads start as 404s.
        assert not _unexpected(served.errors()), _unexpected(served.errors())


def _item_editor(page, served):
    page.set_viewport_size({'width': 1920, 'height': 1080})
    page.add_init_script('''if (location.protocol.startsWith('http')) { try {
        localStorage.setItem('chauffeur_admin_token', %s);
        localStorage.setItem('chauffeur_admin_token_for', 'alpha-parent');
        localStorage.setItem('chauffeur_theme', 'dark');
    } catch (e) {} }''' % json.dumps(STATE['token']))
    page.goto(served.url('house/editor?tier=low&test=1'))
    page.wait_for_function('() => window.__editor?.ready && window.__twin?.ready', timeout=90000, polling=500)
    if page.locator('#editor-dialog #place-view').is_visible():
        page.locator('#place-close').click()


def scenario_L4_drop_on_one_window_pane_then_frame():
    """Real pointer drags hit the pane and frame independently of their wall."""
    served = _serve()
    if served is None:
        raise AssertionError('Chromium is required for L4 visual verification')
    from services import twin_store
    plan = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    twin_store.push_round(plan, 'build')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with served.browser(launch_args=GPU_ARGS, color_scheme='dark') as page:
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        _item_editor(page, served)
        chosen = page.evaluate('''() => {
            const v=window.__twin,b=v.plan.buildings.find(b=>b.id==='pool-house');
            const opening=b.openings.find(o=>o.kind==='window' && b.walls.some(w=>w.id===o.wall && w.exterior));
            if(!opening)throw Error('Fixture needs an exterior window');
            const wall=b.walls.find(w=>w.id===opening.wall),d=wall.to.map((n,i)=>n-wall.from[i]),len=Math.hypot(...d);
            const centre=wall.from.map((n,i)=>n+d[i]*opening.at/len),normal=[d[1]/len,-d[0]/len];
            const outline=b.levels.find(l=>l.id===wall.level).outline;
            const avg=[0,1].map(i=>outline.reduce((n,p)=>n+p[i],0)/outline.length);
            if(normal.reduce((n,x,i)=>n+x*(centre[i]-avg[i]),0)<0)normal.forEach((x,i)=>normal[i]=-x);
            const level=b.levels.find(l=>l.id===wall.level),z=level.elevation+(opening.sill+opening.head)/2;
            const a=(b.rotation||0)*Math.PI/180;
            const world=([x,y,z])=>[(Math.cos(a)*x-Math.sin(a)*y+b.position[0])*.3048,
                (z+(b.base||0))*.3048,-(Math.sin(a)*x+Math.cos(a)*y+b.position[1])*.3048];
            v.setCamera('front');v.setCameraState({position:world([centre[0]+normal[0]*14,centre[1]+normal[1]*14,z]),target:world([...centre,z])});
            window.__slotWindow={building:b.id,id:opening.id};
            return {building:b.id,id:opening.id,wall:wall.id,
                walls:JSON.stringify(b.walls.map(w=>w.faces||null)),
                others:JSON.stringify(b.openings.filter(o=>o.id!==opening.id).map(o=>o.materials||null))};
        }''')
        page.locator('#dock-tab-library').click()
        for part, mid in [('pane', STATE['panes']), ('window_frame', STATE['siding'])]:
            # Sample the original part's triangles, then require the real view
            # picker to identify that part before sending the pointer there.
            point = page.evaluate('''part => {
                const v=window.__twin,{building,id}=window.__slotWindow;v.scene.updateMatrixWorld(true);
                let proxy;v.scene.traverse(o=>{if(o.layers.isEnabled(31)&&o.userData.buildingId===building&&o.userData.pieceId===id)proxy=o;});
                const canvas=v.renderer3.domElement,r=canvas.getBoundingClientRect(),Vector=v.camera.position.constructor;
                for(const {object,group} of proxy.userData.partObjects||[]){
                    if(object.userData.part!==part)continue;
                    const g=object.geometry,p=g.attributes.position,idx=g.index?.array||Array.from({length:p.count},(_,i)=>i);
                    for(let i=0;i<idx.length;i+=3){
                        const q=new Vector();for(let j=0;j<3;j++)q.add(new Vector().fromBufferAttribute(p,idx[i+j]).multiplyScalar([.2,.3,.5][j]));
                        q.applyMatrix4(group.matrixWorld).project(v.camera);
                        const x=r.left+(q.x+1)*r.width/2,y=r.top+(1-q.y)*r.height/2,hit=v.pick(x,y);
                        if(hit?.pieceId===id&&hit.part===part&&canvas.contains(document.elementFromPoint(x,y)))return {x,y};
                    }
                }throw Error('No visible '+part+' target');
            }''', part)
            tile = page.locator(f'#library-entries [data-material="{mid}"]')
            tile.wait_for()
            tile.scroll_into_view_if_needed()
            box = tile.bounding_box()
            page.mouse.move(box['x'] + box['width']/2, box['y'] + box['height']/2)
            page.mouse.down()
            page.mouse.move(point['x'], point['y'], steps=16)
            page.mouse.up()
            page.wait_for_function('''({id,building,part,mid}) => {
                const v=window.__twin,b=v.plan.buildings.find(b=>b.id===building);
                if(!v.ready||b.openings.find(o=>o.id===id)?.materials?.[part]?.id!==mid)return false;
                let proxy;v.scene.traverse(o=>{if(o.layers.isEnabled(31)&&o.userData.pieceId===id&&o.userData.buildingId===building)proxy=o;});
                const own=proxy?.userData.partObjects?.filter(p=>p.object.userData.part===part)||[];
                return own.length>0&&own.every(p=>p.object.material.userData.materialId===mid);
            }''', arg={**chosen, 'part': part, 'mid': mid}, timeout=90000, polling=500)
            assert page.locator('#material-chooser').count() == 0
            assert page.evaluate('''old => {
                const b=window.__twin.plan.buildings.find(b=>b.id===old.building);
                return JSON.stringify(b.walls.map(w=>w.faces||null))===old.walls &&
                    JSON.stringify(b.openings.filter(o=>o.id!==old.id).map(o=>o.materials||null))===old.others;
            }''', chosen)
        assert page.evaluate('''({building,id,pane,frame}) => {
            const opening=window.__twin.plan.buildings.find(b=>b.id===building).openings.find(o=>o.id===id);
            return opening.materials.pane.id===pane && opening.materials.window_frame.id===frame;
        }''', {**chosen, 'pane': STATE['panes'], 'frame': STATE['siding']})
        page.screenshot(path=str(OUTPUT / 'L4-window-pane-and-frame-dark-wall.png'), full_page=True)
        assert not _unexpected(errors), _unexpected(errors)
        assert not _unexpected(served.errors()), _unexpected(served.errors())


def scenario_L5_stair_rail_pick_and_clear_returns_house_look():
    served = _serve()
    if served is None:
        raise AssertionError('Chromium is required for L5 visual verification')
    from services import twin_store
    plan = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    building = plan['buildings'][0]
    stair = building['stairs'][0]
    stair.update(style='open', rail='both')
    building.setdefault('materials', {})['stair_rail'] = {'id': STATE['siding']}
    twin_store.push_round(plan, 'build')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with served.browser(launch_args=GPU_ARGS, color_scheme='dark') as page:
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        _item_editor(page, served)
        page.evaluate('''({id,building}) => {
            const v=window.__twin;v.setView(building+':L1');v.setCamera('top');window.__editor.clickPiece(id,building);
        }''', {'id': stair['id'], 'building': building['id']})
        row = page.locator('#piece-card [data-library-slot="Rail"]')
        page.locator('#dock-tab-library').click()
        page.locator(f'#library-entries [data-material="{STATE["panes"]}"]').click()
        row.locator('[data-slot-use]').click()
        page.wait_for_function('''({id,building,mid}) => window.__twin.ready &&
            window.__twin.plan.buildings.find(b=>b.id===building).stairs.find(s=>s.id===id).materials?.stair_rail?.id===mid
        ''', arg={'id': stair['id'], 'building': building['id'], 'mid': STATE['panes']}, timeout=90000, polling=500)
        if page.locator('#dock-pane-library').is_visible():
            page.locator('#dock-tab-scene').click()
        row.locator('[data-slot-clear]').click()
        page.wait_for_function('''({id,building,mid}) => {
            const v=window.__twin,b=v.plan.buildings.find(b=>b.id===building);
            if(!v.ready||b.stairs.find(s=>s.id===id).materials?.stair_rail)return false;
            let proxy;v.scene.traverse(o=>{if(o.layers.isEnabled(31)&&o.userData.pieceId===id&&o.userData.buildingId===building)proxy=o;});
            const rails=proxy?.userData.partObjects?.filter(p=>p.object.userData.part==='stair_rail')||[];
            return rails.length>0&&rails.every(p=>p.object.material.userData.materialId===mid);
        }''', arg={'id': stair['id'], 'building': building['id'], 'mid': STATE['siding']}, timeout=90000, polling=500)
        row.get_by_text('From the building: Bake siding', exact=True).wait_for()
        page.screenshot(path=str(OUTPUT / 'L5-stair-rail-cleared-dark-wall.png'), full_page=True)
        assert not _unexpected(errors), _unexpected(errors)
        assert not _unexpected(served.errors()), _unexpected(served.errors())


def scenario_L_roof_two_materials():
    """Set two ordinary Library materials through the existing roof card row."""
    served = _serve()
    if served is None:
        raise AssertionError('Chromium is required for roof material visual verification')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with served.browser(launch_args=GPU_ARGS, color_scheme='dark') as page:
        page.set_viewport_size({'width': 1920, 'height': 1080})
        page.add_init_script('''if (location.protocol.startsWith('http')) { try {
            localStorage.setItem('chauffeur_admin_token', %s);
            localStorage.setItem('chauffeur_admin_token_for', 'alpha-parent');
            localStorage.setItem('chauffeur_theme', 'dark');
        } catch (e) {} }''' % json.dumps(STATE['token']))
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(served.url('house/editor?tier=high&test=1'))
        page.wait_for_function('() => window.__editor?.ready && window.__twinEditor && window.__twin?.ready', timeout=90000, polling=500)
        if page.locator('#editor-dialog #place-view').is_visible():
            page.locator('#place-close').click()
        for key in ['roof_main', 'roof_porch']:
            rid, mid = STATE[key], STATE[key + '_material']
            page.evaluate('(id) => window.__editor.clickPiece(id, "pool-house")', rid)
            row = page.locator('#piece-card [data-library-slot="Roof"]')
            page.locator('#dock-tab-library').click()
            page.locator(f'#library-entries [data-material="{mid}"]').click()
            row.locator('[data-slot-use]').click()
            page.wait_for_function('''({rid, mid}) => {
                const b = window.__twin.plan.buildings.find(b => b.id === 'pool-house');
                return b.roof.sections.some(s => (s.id === rid || s.roof === rid) && s.material?.id === mid);
            }''', arg={'rid': rid, 'mid': mid}, polling=500)
            # The Library tab stays open after assignment; return to Scene.
            if page.locator('#dock-pane-library').is_visible():
                page.locator('#dock-tab-scene').click()
        expected = sorted([STATE['roof_main_material'], STATE['roof_porch_material']])
        page.wait_for_function('''expected => {
            const ids = new Set();
            window.__twin.scene.traverse(o => {
                if (!o.isMesh || o.layers.isEnabled(31) || o.material?.name !== 'roof') return;
                let b = o; while (b && !b.userData.buildingId) b = b.parent;
                if (b?.userData.buildingId === 'pool-house' && o.material.userData.materialId)
                    ids.add(o.material.userData.materialId);
            });
            return JSON.stringify([...ids].sort()) === JSON.stringify(expected);
        }''', arg=expected, polling=500)
        page.evaluate('''() => {
            const view = window.__twin, b = view.plan.buildings.find(b => b.id === 'pool-house');
            const angle = (b.rotation || 0) * Math.PI / 180;
            const world = ([x,y,z]) => [
                (Math.cos(angle)*x-Math.sin(angle)*y+b.position[0])*.3048,
                (z+(b.base||0))*.3048,
                -(Math.sin(angle)*x+Math.cos(angle)*y+b.position[1])*.3048];
            view.setCamera('front');
            view.setCameraState({position:world([65,-48,46]),target:world([19,11,7])});
        }''')
        _settle(page)
        # The line names the material the person made, never its id.
        page.locator('#piece-card .editor-material-line').get_by_text('Porch roof metal, set here').wait_for()
        page.screenshot(path=str(OUTPUT / 'L-roof-two-materials-dark-wall.png'), full_page=True)
        assert not _unexpected(errors), _unexpected(errors)
        assert not served.errors(), served.errors()


if __name__ == '__main__':
    failed = 0
    scenarios = [scenario_L1_library_blend_and_leaf_cutout, scenario_L_roof_two_materials,
                 scenario_L2_house_materials_panes_and_draw_budget,
                 scenario_L3_siding_mode_flip_drops_and_restores_finished_bake,
                 scenario_L4_drop_on_one_window_pane_then_frame,
                 scenario_L5_stair_rail_pick_and_clear_returns_house_look]
    for scenario in scenarios:
        try:
            scenario()
            print('ok  ', scenario.__name__)
        except Exception:
            failed += 1
            traceback.print_exc()
            print('FAIL', scenario.__name__)
    print(f'{len(scenarios) - failed}/{len(scenarios)} passed')
    print(f'Screenshots: {OUTPUT}')
    sys.exit(bool(failed))

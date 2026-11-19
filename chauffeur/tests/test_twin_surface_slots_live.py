"""Slice 7 Chromium acceptance, WRITTEN NOT RUN by Codex.

Run from chauffeur/: python tests/test_twin_surface_slots_live.py
Claude owns the browser run. The caller disables vsync and the frame cap for
SLOTS_COST (SLOTS_CHROMIUM_ARGS accepts a JSON list of extra launch flags).
Scenarios reset scratch storage to the real household; assignments
use real Scene disclosures, Library clicks and slot controls. Only the bulk
cost fixture uses store writes. The editor never bakes (Ruling B15), so the
locality scenario uses the permitted reach/packing API fallback, not a fake
successful GPU bake. No production test hook is needed.
"""
from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
from statistics import median
import sys
import tempfile
import traceback

# Must precede every harness/service import, including indirect imports.
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_surface_slots_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_twin_library_assign_live as L
import twin_edit_measure as M
import house_editor_model_harness as H
from live_app import live_app

ROOT = Path(__file__).resolve().parents[1]
SERVED = None
TIMEOUT = L.TIMEOUT


def _gpu_args():
    extra = json.loads(os.environ.get('SLOTS_CHROMIUM_ARGS', '[]'))
    assert isinstance(extra, list) and all(isinstance(x, str) for x in extra)
    return [*H.GPU_ARGS, *extra]


def _seed(*, feature=False, many=False):
    from services import twin_materials, twin_store

    twin_store.start_over()
    M._prepare(None)
    assets = {}
    colours = [('current', 'House ochre', '#dc9c22'),
               ('selected', 'Selected blue', '#143cff'),
               ('override', 'Face magenta', '#ed167a')]
    if many:
        colours += [(f'cost{i}', f'Cost finish {i:02d}',
                     f'#{(0x217193 + i * 0x031507) & 0xffffff:06x}') for i in range(40)]
    for key, name, colour in colours:
        assets[key] = twin_materials.create({'name': 'Slice 7 ' + name, 'params': {
            'tint': colour, 'roughness': 1, 'metalness': 0, 'alpha_mode': 'opaque',
            'random_offset': False}}, H.PARENT['id'])

    def defaults(plan):
        for b in plan['buildings']:
            b.setdefault('materials', {})['siding'] = {'id': assets['current']['id']}
            for level in b['levels']:
                level.get('materials', {}).pop('siding', None)
            for wall in b['walls']:
                wall.pop('faces', None)
        if feature:
            pool = plan['site']['pool']
            if not any(f['kind'] in ('ledge', 'steps') for f in pool.get('features', [])):
                # Same store-based site fixture pattern as water/Scene live tests.
                # Inset a rectangle near the centre of this household's real pool.
                points = pool['polygon']
                cx = sum(p[0] for p in points) / len(points)
                cy = sum(p[1] for p in points) / len(points)
                pool.setdefault('features', []).append({'id': 'slots-test-ledge',
                    'kind': 'ledge', 'name': 'Surface acceptance ledge', 'depth_in': 12,
                    'polygon': [[cx-2, cy-1], [cx+2, cy-1], [cx+2, cy+1], [cx-2, cy+1]]})
        return plan

    twin_store.update_current(defaults, 'build')
    return assets


def _open(page):
    H.signed_in(page)
    page.goto(SERVED.url('house/editor?tier=low&test=1&timing=1'), timeout=TIMEOUT)
    L._wait(page, 'window.__editor?.ready === true && !!window.__twinEditor && window.__twin?.ready')
    H.settle(page, 4)
    if page.locator('#editor-dialog').is_visible():
        page.click('#editor-dialog-close')
        page.locator('#editor-dialog').wait_for(state='hidden')
    M._dismiss_alert(page)
    M._track_view_work(page)
    page.evaluate('window.__twin.controls.enableDamping = false')
    page.click('#rail-select')
    L._settled(page)


@contextmanager
def _page(**seed_options):
    global SERVED
    try:
        from playwright.sync_api import Error
    except ImportError as error:
        raise M.MeasurementSkipped('playwright not installed; surface slots checks skipped') from error
    assets = _seed(**seed_options)
    if SERVED is None:
        SERVED = live_app()
    if SERVED is None:
        raise M.MeasurementSkipped('playwright not installed; surface slots checks skipped')
    browser = SERVED.browser(launch_args=_gpu_args())
    try:
        with browser as page:
            page.set_viewport_size({'width': 1600, 'height': 1000})
            page.set_default_timeout(TIMEOUT)
            page.set_default_navigation_timeout(TIMEOUT)
            _open(page)
            yield page, assets
            assert not H.unexpected(browser.errors), browser.errors
    except Error as error:
        if "Executable doesn't exist" in str(error) or 'playwright install' in str(error):
            raise M.MeasurementSkipped('Chromium not installed; surface slots checks skipped') from error
        raise
    finally:
        if browser._pw is not None and browser._b is None:
            browser._pw.stop()


def _select_piece(page, building, piece):
    """Shared slice-6 disclosures for buildings; the same gestures for the Yard."""
    if building is not None:
        return L._select_piece(page, building, piece, None)
    page.click('#dock-tab-scene')
    host = page.locator('#scene-tree')
    parents = page.evaluate('''async id => {
        const {sceneRows}=await import(window.chfBase+'static/twin/editor/scene_tree.js');
        const row=sceneRows(window.__twin.plan).find(r=>r.id===id && r.building===null);
        if(!row)throw Error('No Yard Scene row: '+id);
        const result=[];for(let p=row.parent;p;p=p.parent)result.unshift(p.id);return result;
    }''', piece['id'])
    for pid in parents:
        parent = L._mount_row(page, host, host.locator(f'[data-scene-id="{pid}"]'))
        disclosure = parent.locator('[data-row-disclosure][aria-expanded="false"]')
        if disclosure.count():
            disclosure.click()
        assert parent.get_attribute('aria-expanded') == 'true'
    row = L._mount_row(page, host, host.locator(f'[data-scene-id="{piece["id"]}"]'))
    row.locator('[data-scene-select]').click()
    L._wait(page, 'id => window.__twinEditor.selection().id === id', piece['id'])
    L._settled(page)


def _choose(page, asset):
    L._library(page)
    L._select_asset(page, asset)


def _use(page, label, asset, host='#piece-card'):
    row = page.locator(f'{host} [data-library-slot="{label}"]')
    row.get_by_role('button', name=f'Use {asset["name"]}', exact=True).click()
    L._settled(page)
    return row


def _wall(page, bid, wid):
    b = next(b for b in L._plan(page)['buildings'] if b['id'] == bid)
    return next(w for w in b['walls'] if w['id'] == wid)


# Read actual displayed buffers, not a second generator or catalogue metadata.
# snapRanges survive material merging; groups determine the actual material for
# each triangle even if a future renderer combines multiple materials in a mesh.
SURFACE_RECORDS = r'''async ({bid=null,id=null,part=null,role=null}) => {
    const THREE=await import('three'),v=window.__twin,records=[];
    v.scene.updateMatrixWorld(true);
    const round=x=>Math.round(x*1e6)/1e6;
    v.scene.traverseVisible(mesh=>{
        if(!mesh.isMesh||mesh.layers.isEnabled(31)||mesh.isInstancedMesh)return;
        const g=mesh.geometry,p=g.attributes.position,uv=g.attributes.uv;
        const ranges=mesh.userData.snapRanges||g.userData.snapRanges||[
            {...mesh.userData,start:0,count:g.index?.count||p.count}];
        const mats=Array.isArray(mesh.material)?mesh.material:[mesh.material];
        for(const range of ranges){
            if(bid!==null&&range.buildingId!==bid||id!==null&&range.pieceId!==id
                ||part!==null&&range.bakePart!==part)continue;
            for(let n=range.start;n+2<range.start+range.count;n+=3){
                const group=g.groups.find(x=>n>=x.start&&n<x.start+x.count);
                const mat=mats[group?.materialIndex||0];
                if(!mat?.visible||role!==null&&mat.name!==role)continue;
                const indices=[0,1,2].map(k=>g.index?g.index.getX(n+k):n+k);
                const vertices=indices.map(i=>({p:new THREE.Vector3().fromBufferAttribute(p,i)
                    .applyMatrix4(mesh.matrixWorld).toArray().map(round),
                    uv:uv?[round(uv.getX(i)),round(uv.getY(i))]:null}));
                vertices.sort((a,b)=>JSON.stringify(a.p).localeCompare(JSON.stringify(b.p)));
                records.push({piece:range.pieceId,part:range.bakePart||'',role:mat.name,
                    key:JSON.stringify(vertices.map(x=>x.p)),uv:vertices.map(x=>x.uv),
                    material:mat.userData.materialId||mat.userData.bakeMaterialId||null,
                    colour:mat.color?.getHex()});
            }
        }
    });
    return records.sort((a,b)=>JSON.stringify(a).localeCompare(JSON.stringify(b)));
}'''


def _records(page, **filters):
    return page.evaluate(SURFACE_RECORDS, filters)


def _face_records(page, bid, wid, side):
    records = _records(page, bid=bid, id=wid, part=side)
    assert records, f'No rendered face triangles: {bid}/{wid}/{side}'
    return records


def _geometry(records):
    return sorted((r['key'], r['uv']) for r in records)


def _materials(records):
    return sorted((r['key'], r['material'], r['colour']) for r in records)


def scenario_wall_face_override_and_clear():
    with _page() as (page, assets):
        b, w, room = L._target(L._plan(page))
        side, points = L._wall_view(page, b, w, room)
        _choose(page, assets['selected'])
        _select_piece(page, b, w)
        row = L._slot(page, 'Outside')
        name = row.locator('[data-slot-name]')
        assert name.inner_text().startswith('House default: ')
        assert name.get_attribute('aria-disabled') == 'true'
        inherited_ink = name.evaluate('(n)=>getComputedStyle(n).color')
        page.mouse.move(10, 70)
        L._settled(page)
        before = L._pixels(page, points)
        other = 'right' if side == 'left' else 'left'
        neighbour = _face_records(page, b['id'], w['id'], other)
        _use(page, 'Outside', assets['selected'])
        assert name.get_attribute('aria-disabled') == 'false'
        assert name.evaluate('(n)=>getComputedStyle(n).color') != inherited_ink
        assert _wall(page, b['id'], w['id'])['faces'][side] == {'id': assets['selected']['id']}
        assert all(r['material'] == assets['selected']['id']
                   for r in _face_records(page, b['id'], w['id'], side))
        page.mouse.move(10, 70)
        L._settled(page)
        after = L._pixels(page, points)
        changed = [i for i, (a, z) in enumerate(zip(before, after))
                   if max(abs(x-y) for x, y in zip(a, z)) > 10]
        assert changed, (points, before, after)
        row.locator('[data-slot-clear]').click()
        L._settled(page)
        assert not _wall(page, b['id'], w['id']).get('faces', {}).get(side)
        assert name.inner_text().startswith('House default: ')
        assert name.get_attribute('aria-disabled') == 'true'
        assert name.evaluate('(n)=>getComputedStyle(n).color') == inherited_ink
        page.mouse.move(10, 70)
        L._settled(page)
        restored = L._pixels(page, points)
        assert all(max(abs(x-y) for x, y in zip(before[i], restored[i])) <= 6 for i in changed), (
            before, after, restored)
        assert _face_records(page, b['id'], w['id'], other) == neighbour
        stored = next(w0 for w0 in L._stored_building(b['id'])['walls'] if w0['id'] == w['id'])
        assert not stored.get('faces', {}).get(side)


# Roof top triangles have no per-plane material group before overrides (one
# batch can contain every plane). Map real mesh/group triangles to the retained
# envelope's authored side/edge. Only upward covering faces count, not fascia,
# underside or standing-seam sides. This still inspects the real rendered mesh.
ROOF_GROUPS = r'''async bid => {
    const THREE=await import('three'),v=window.__twin,s=v.roofSurfaces.get(bid),out={};
    if(!s)throw Error('Missing retained roof envelope: '+bid);
    v.scene.updateMatrixWorld(true);
    const triangles=Array.from(s.section,(_,i)=>({section:s.sections[s.section[i]],edge:s.edge[i],
        triangle:new THREE.Triangle(...[0,3,6].map(k=>new THREE.Vector3(...s.positions.slice(i*9+k,i*9+k+3))))}));
    v.scene.traverseVisible(mesh=>{
        if(!mesh.isMesh||mesh.layers.isEnabled(31))return;
        let domain=mesh.parent;
        while(domain&&!(domain.userData.buildingId===bid&&domain.name===bid+':roof'))domain=domain.parent;
        if(!domain)return;
        const matrix=domain.matrixWorld.clone().invert().multiply(mesh.matrixWorld),g=mesh.geometry;
        const p=g.attributes.position,mats=Array.isArray(mesh.material)?mesh.material:[mesh.material];
        for(let n=0;n+2<(g.index?.count||p.count);n+=3){
            const group=g.groups.find(x=>n>=x.start&&n<x.start+x.count),m=mats[group?.materialIndex||0];
            if(m?.name!=='roof'||!m.visible)continue;
            const points=[0,1,2].map(k=>{const q=new THREE.Vector3().fromBufferAttribute(p,g.index?g.index.getX(n+k):n+k)
                .applyMatrix4(matrix);return new THREE.Vector3(q.x,-q.z,q.y);});
            const tri=new THREE.Triangle(...points),normal=tri.getNormal(new THREE.Vector3());
            if(normal.z<.1||tri.getArea()<1e-8)continue;
            const centre=tri.getMidpoint(new THREE.Vector3());
            const hit=triangles.find(t=>t.edge>=0&&t.triangle.closestPointToPoint(centre,new THREE.Vector3()).distanceTo(centre)<1e-4);
            if(!hit)continue;
            const key=(hit.section.roof||hit.section.id)+':'+hit.edge;
            (out[key]||=[]).push({material:m.userData.materialId||m.userData.bakeMaterialId||null,
                colour:m.color?.getHex(),area:tri.getArea(),group:group?.materialIndex||0});
        }
    });return out;
}'''


def _roof_target(page):
    target = page.evaluate('''async () => {
        const {materialLines}=await import(window.chfBase+'static/twin/editor/library.js'),p=window.__twin.plan;
        for(const b of [...p.buildings].sort((a,b)=>(a.id==='pool-house'?-1:1))){
            for(const s of b.roof?.sections||[]){
                const rows=materialLines({kind:'roof',piece:s,building:b},p,{}).filter(r=>r.target.plane!==undefined);
                if(rows.length>=2 && rows.every(r=>/^(Front|Back|Left|Right) slope/.test(r.label)))
                    return {bid:b.id,id:s.id,rows:rows.map(r=>({label:r.label,target:r.target}))};
            }
        }throw Error('Household needs a named multi-plane roof');
    }''')
    plan = L._plan(page)
    b = next(b for b in plan['buildings'] if b['id'] == target['bid'])
    s = next(s for s in b['roof']['sections'] if s['id'] == target['id'])
    return b, s, target['rows']


def scenario_roof_plane_override():
    with _page() as (page, assets):
        b, roof, rows = _roof_target(page)
        # All floors keeps roofs shown; selecting a roof row must not peel it.
        page.click('#dock-tab-scene')
        page.get_by_role('button', name='All floors', exact=True).click()
        _choose(page, assets['selected'])
        _select_piece(page, b, roof)
        for row in rows:
            assert L._slot(page, row['label']).count() == 1
        before = page.evaluate(ROOF_GROUPS, b['id'])
        candidates = [r for r in rows if f'{r["target"]["roof"]}:{r["target"]["plane"]}' in before]
        assert len(candidates) >= 2, ('At least two rendered planes must be observed', before)
        chosen = candidates[0]
        key = f'{chosen["target"]["roof"]}:{chosen["target"]["plane"]}'
        assert all(t['material'] != assets['selected']['id'] for t in before[key])
        _use(page, chosen['label'], assets['selected'])
        after = page.evaluate(ROOF_GROUPS, b['id'])
        assert set(after) == set(before), (before.keys(), after.keys())
        assert after[key] and all(t['material'] == assets['selected']['id'] for t in after[key])
        for plane in before:
            assert abs(sum(t['area'] for t in after[plane])-sum(t['area'] for t in before[plane])) < 1e-3
            if plane != key:
                assert {(t['material'], t['colour']) for t in after[plane]} == {
                    (t['material'], t['colour']) for t in before[plane]}, f'Unselected plane changed: {plane}'
        plan = L._plan(page)
        owner = next(b0 for b0 in plan['buildings'] if b0['id'] == b['id'])
        authored = next(r for r in owner['roofs'] if r['id'] == chosen['target']['roof'])
        assert authored['plane_materials'][str(chosen['target']['plane'])] == {'id': assets['selected']['id']}
        stored = next(r for r in L._stored_building(b['id'])['roofs'] if r['id'] == authored['id'])
        assert stored['plane_materials'] == authored['plane_materials']


def scenario_ledge_or_steps_override():
    with _page(feature=True) as (page, assets):
        feature = next(f for f in L._plan(page)['site']['pool']['features'] if f['kind'] in ('ledge', 'steps'))
        _choose(page, assets['selected'])
        _select_piece(page, None, feature)
        _use(page, 'Interior', assets['selected'])
        actual = next(f for f in L._plan(page)['site']['pool']['features'] if f['id'] == feature['id'])
        assert actual['materials']['interior'] == {'id': assets['selected']['id']}
        rendered = _records(page, id=feature['id'], part='interior')
        assert rendered and all(r['material'] == assets['selected']['id'] for r in rendered), rendered
        from services import twin_store
        stored = next(f for f in twin_store.current()['site']['pool']['features'] if f['id'] == feature['id'])
        assert stored['materials']['interior'] == actual['materials']['interior']


def scenario_uv_offset_moves_one_face():
    with _page() as (page, _):
        b, w, room = L._target(L._plan(page))
        side, _ = L._wall_view(page, b, w, room)
        _select_piece(page, b, w)
        row = L._slot(page, 'Outside')
        other = 'right' if side == 'left' else 'left'
        before = _face_records(page, b['id'], w['id'], side)
        neighbour = _face_records(page, b['id'], w['id'], other)
        adjoining = next(x for x in b['walls'] if x['id'] != w['id']
                         and x['level'] == w['level'] and x.get('state') != 'ghost'
                         and set(x.get('joints', [])) & set(w.get('joints', [])))
        adjoining_before = _records(page, bid=b['id'], id=adjoining['id'])
        assert adjoining_before, 'Adjoining wall must have rendered geometry'
        programs = page.evaluate('window.__twin.renderer3.info.programs.length')
        row.get_by_label('Outside U offset', exact=True).fill('0.25')
        row.get_by_label('Outside U offset', exact=True).press('Tab')
        L._settled(page)
        row.get_by_label('Outside Rotation', exact=True).select_option('90')
        L._settled(page)
        ref = _wall(page, b['id'], w['id'])['faces'][side]
        assert ref['uv'] == {'u': .25, 'v': 0, 'rot': 90}, ref
        after = _face_records(page, b['id'], w['id'], side)
        assert sorted(r['key'] for r in before) == sorted(r['key'] for r in after)
        assert _geometry(before) != _geometry(after), 'Selected face UVs did not move'
        assert _materials(before) == _materials(after), 'UV controls changed the finish'
        assert _face_records(page, b['id'], w['id'], other) == neighbour
        assert _records(page, bid=b['id'], id=adjoining['id']) == adjoining_before
        assert page.evaluate('window.__twin.renderer3.info.programs.length') == programs


def scenario_house_wide_role_recolours_inheritors():
    with _page() as (page, assets):
        b, w, room = L._target(L._plan(page))
        side, _ = L._wall_view(page, b, w, room)
        _choose(page, assets['override'])
        _select_piece(page, b, w)
        _use(page, 'Outside', assets['override'])
        # Switch back to all floors before the full-building face census.
        page.click('#dock-tab-scene')
        page.get_by_role('button', name='All floors', exact=True).click()
        _select_piece(page, b, b)
        page.locator('#piece-card').get_by_role('button', name='House materials', exact=True).click()
        dialog = '#editor-dialog #house-materials'
        page.locator(f'{dialog} [data-library-slot="Siding"]').wait_for(state='visible')
        before = _records(page, bid=b['id'], role='siding')
        faces = [r for r in before if r['part'] in ('left', 'right')]
        inheritors = [r for r in faces if r['material'] == assets['current']['id']]
        overridden = [r for r in faces if r['piece'] == w['id'] and r['part'] == side]
        assert len({r['piece'] for r in inheritors}) > 1 and overridden
        # The dialog remains open and the actual dock is interactive.
        _choose(page, assets['selected'])
        assert page.locator('#editor-dialog').is_visible()
        _use(page, 'Siding', assets['selected'], dialog)
        current = next(x for x in L._plan(page)['buildings'] if x['id'] == b['id'])
        assert current['materials']['siding'] == {'id': assets['selected']['id']}
        assert L._stored_building(b['id'])['materials']['siding'] == current['materials']['siding']
        after = _records(page, bid=b['id'], role='siding')
        # Compare every observed face triangle by geometry, including all floors.
        after_by_key = {}
        for r in after:
            after_by_key.setdefault((r['piece'], r['part'], r['key']), []).append(r)
        for old in inheritors:
            rows = after_by_key.get((old['piece'], old['part'], old['key']), [])
            assert rows and all(r['material'] == assets['selected']['id']
                                and r['colour'] != old['colour'] for r in rows), old
        assert [r for r in after if r['piece'] == w['id'] and r['part'] == side] == overridden
        assert _wall(page, b['id'], w['id'])['faces'][side] == {'id': assets['override']['id']}


# Same real-household reach APIs used by runtime.materialsChanged() and the
# browser-free surface reach regression. Build viewing geometry because the
# editor's floor filter is deliberately not a bake source. No codec/worker fake,
# stored publication, or successful browser bake is claimed by this fallback.
BAKE_PREPARE = r'''async ({kit,bid,wid,side}) => {
    const base=window.chfBase,prefix=base+'static/twin/';
    const {buildTwin}=await import(prefix+'twin_generator.js');
    const {buildYard}=await import(prefix+'twin_yard.js');
    const {buildAtlas}=await import(prefix+'bake/atlas.js');
    const {bakeLayout}=await import(prefix+'bake/baker.js');
    const {materialParts}=await import(prefix+'bake/bindings.js');
    const {invalidateMaterialReach}=await import(prefix+'bake/reach.js');
    const options={room:{density:1,page:1024,gutter:2}};
    const build=async plan=>{
        const h=buildTwin(plan,kit,'low',{viewing:true});await h.ready;
        const y=await buildYard(plan,kit,'low',{viewing:true});h.root.add(y.group);h.root.updateMatrixWorld(true);
        return {h,y,atlas:buildAtlas(h.root,plan,options)};
    };
    const plan=structuredClone(window.__twin.plan),before=await build(plan);
    // Representative room lights mirror test_twin_reach_surface_slots_js.py;
    // they include remote rooms so an all-lights dirtying regression cannot pass.
    const lights=plan.buildings.flatMap(b=>b.rooms.filter(r=>r.polygon?.length).map(r=>({
        device:b.id+':'+r.id,building:b.id,level:r.level,room:r.id,
        at:[0,1].map(i=>r.polygon.reduce((s,p)=>s+p[i],0)/r.polygon.length).concat(
            (b.levels.find(l=>l.id===r.level)?.elevation||0)+5)})));
    const packed=bakeLayout(before.atlas,options,lights);
    const finish=c=>JSON.stringify([...new Set(materialParts(c).map(({mesh})=>JSON.stringify([
        mesh.material.userData.materialId||mesh.material.userData.bakeMaterialId||null,
        mesh.material.userData.materialRevision??null,mesh.material.color?.toArray()])))].sort());
    const layout=a=>JSON.stringify({pages:a.room.pages,rooms:a.room.rooms,
        charts:a.room.charts.map(c=>[c.id,c.key,c.page,c.rect,c.room,c.density])});
    const finishes=before.atlas.room.charts.map(finish);
    const targetCharts=before.atlas.room.charts.filter(c=>materialParts(c).some(({mesh,faces})=>{
        const ranges=mesh.userData.snapRanges||mesh.geometry.userData.snapRanges||[
            {...mesh.userData,start:0,count:mesh.geometry.attributes.position.count}];
        return ranges.some(r=>r.buildingId===bid&&r.pieceId===wid&&r.bakePart===side
            &&faces.some(f=>f*3>=r.start&&f*3<r.start+r.count));
    })).map(c=>c.id);
    if(!targetCharts.length)throw Error('Selected wall must own actual bake charts');
    window.__surfaceBake={before,build,lights,packed,options,finish,layout,finishes,targetCharts,
        bakeLayout,invalidateMaterialReach};
    return {key:before.atlas.key,charts:targetCharts.length,lights:lights.length};
}'''

BAKE_COMPARE = r'''async () => {
    const s=window.__surfaceBake,after=await s.build(structuredClone(window.__twin.plan));
    const changed=after.atlas.room.charts.filter((c,i)=>s.finish(c)!==s.finishes[i]).map(c=>c.id);
    const invalidated=s.invalidateMaterialReach(after.atlas.room);
    const packed=s.bakeLayout(after.atlas,s.options,s.lights,s.packed.ownership,s.packed.entries);
    const dirty=s.lights.filter(l=>s.packed.entries[l.device]?.key!==packed.entries[l.device]?.key).map(l=>l.device);
    const expected=s.packed.lights.filter(l=>l.receivingCharts.some(id=>changed.includes(id))).map(l=>l.device);
    const pages=[...new Set(dirty.flatMap(id=>packed.entries[id]?.pages||[]))];
    const result={key:after.atlas.key,sameLayout:s.layout(after.atlas)===s.layout(s.before.atlas),
        target:s.targetCharts,changed,invalidated,dirty,expected,pages,total:s.lights.length};
    // Detached resources have no displayed lifetime and no bake controller.
    const {releaseBakeSource}=await import(window.chfBase+'static/twin/bake/source.js');
    for(const built of [s.before,after]){
        releaseBakeSource(built.h.root);
        built.h.effects?.dispose?.();
        built.h.root.traverse(o=>{if(o.geometry)o.geometry.dispose();});
        // Material/texture caches are shared with the live editor; leave them
        // to its normal disposal rather than invalidating its active assets.
        built.h.root.clear();
    }
    delete window.__surfaceBake;return result;
}'''


def scenario_one_wall_rebakes_locally():
    with _page() as (page, assets):
        b, w, room = L._target(L._plan(page))
        side, _ = L._wall_view(page, b, w, room)
        _choose(page, assets['selected'])
        _select_piece(page, b, w)
        # The harness opens the editor, which never mounts a bake controller.
        assert page.evaluate('!window.__twin.bake'), 'Revisit fallback if editor baking is introduced'
        kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
        kit['manifest'] = page.evaluate('window.twinManifest || {}')
        page.set_default_timeout(600000)  # Real household atlas/packing can take minutes.
        before = page.evaluate(BAKE_PREPARE, {'kit': kit, 'bid': b['id'], 'wid': w['id'], 'side': side})
        pages = []
        page.on('request', lambda r: pages.append((r.method, r.url))
                if '/api/house/bakes/' in r.url and r.url.split('?')[0].endswith('.png') else None)
        _use(page, 'Outside', assets['selected'])
        result = page.evaluate(BAKE_COMPARE)
        assert result['key'] == before['key'] and result['sameLayout'], result
        assert result['changed'] and set(result['changed']) <= set(result['target']), result
        assert result['invalidated'], result
        assert sorted(result['dirty']) == sorted(result['expected']), result
        assert 0 < len(result['dirty']) < result['total'], result
        assert result['pages'], result
        assert not pages, ('Editor must not request bake pages', pages)
        print('SLOTS_LOCAL_BAKE ' + json.dumps({'mode': 'editor-reach-api-fallback',
            'atlas_key': result['key'], 'changed_charts': len(result['changed']),
            'dirty_lights': len(result['dirty']), 'total_lights': result['total'],
            'dirty_pages': result['pages'], 'pages_requested_after_change': len(pages)}))


FRAME_SAMPLE = r'''async frames => {
    const v=window.__twin,times=[],calls=[];
    // twin_view owns a continuous renderer.setAnimationLoop. Observe its
    // frames without submitting an extra scene render per measured frame.
    for(let i=0;i<12;i++)await new Promise(requestAnimationFrame);
    let previous=performance.now();
    for(let i=0;i<frames;i++){
        await new Promise(requestAnimationFrame);
        const now=performance.now();times.push(now-previous);previous=now;
        calls.push(v.renderer3.info.render.calls);
    }
    return {times,calls,programs:v.renderer3.info.programs.length,tier:v.tier};
}'''


def _bulk_targets(page):
    """40 different slots, spread across walls, floors and authored roof edges."""
    return page.evaluate('''async () => {
        const {materialLines}=await import(window.chfBase+'static/twin/editor/library.js');
        const p=window.__twin.plan,walls=[],floors=[],roofs=[],seen=new Set();
        for(const b of p.buildings){
            for(const w of b.walls.filter(w=>w.state!=='ghost'))walls.push({bid:b.id,wall:w.id,side:'left'});
            for(const r of b.rooms.filter(r=>r.state!=='ghost'&&r.kind!=='porch'))floors.push({bid:b.id,room:r.id});
            for(const s of b.roof?.sections||[])for(const row of materialLines({kind:'roof',piece:s,building:b},p,{})){
                const t=row.target,key=JSON.stringify([b.id,t]);
                if(t.plane===undefined||seen.has(key))continue;seen.add(key);roofs.push({bid:b.id,roof:t.roof,plane:t.plane});
            }
        }
        if(walls.length<20||floors.length<10||roofs.length<10)throw Error('Household needs 20 walls, 10 floors and 10 roof planes');
        return [...walls.slice(0,20),...floors.slice(0,10),...roofs.slice(0,10)];
    }''')


def scenario_many_overrides_low_tier_measure():
    with _page(many=True) as (page, assets):
        from services import twin_store

        page.click('#dock-tab-scene')
        page.get_by_role('button', name='All floors', exact=True).click()
        page.mouse.move(10, 70)
        L._settled(page)
        camera = page.evaluate('window.__twin.cameraState()')
        targets = _bulk_targets(page)
        assert len(targets) == 40 and len({assets[f'cost{i}']['id'] for i in range(40)}) == 40
        original = copy.deepcopy(twin_store.current_model())
        baseline = page.evaluate(FRAME_SAMPLE, 90)

        def overrides(plan):
            for i, target in enumerate(targets):
                b = next(b for b in plan['buildings'] if b['id'] == target['bid'])
                ref = {'id': assets[f'cost{i}']['id']}
                if 'wall' in target:
                    w = next(w for w in b['walls'] if w['id'] == target['wall'])
                    w.setdefault('faces', {})[target['side']] = ref
                elif 'room' in target:
                    next(r for r in b['rooms'] if r['id'] == target['room'])['floor_material'] = ref
                else:
                    roof = next(r for r in b['roofs'] if r['id'] == target['roof'])
                    roof.setdefault('plane_materials', {})[str(target['plane'])] = ref
            return plan

        # Roof plane refs belong to the connected model. A flat drawing write
        # reassembles roofs from roof.sections and can discard a canonical edit.
        twin_store.update_model(overrides, 'edit')
        # _open navigates/signs in and closes the shell dialog, just as on first load.
        _open(page)
        page.click('#dock-tab-scene')
        page.get_by_role('button', name='All floors', exact=True).click()
        page.evaluate('state => window.__twin.setCameraState(state)', camera)
        page.mouse.move(10, 70)
        L._settled(page)
        plan = L._plan(page)
        for i, target in enumerate(targets):
            b = next(b for b in plan['buildings'] if b['id'] == target['bid'])
            if 'wall' in target:
                ref = next(w for w in b['walls'] if w['id'] == target['wall'])['faces'][target['side']]
            elif 'room' in target:
                ref = next(r for r in b['rooms'] if r['id'] == target['room'])['floor_material']
            else:
                ref = next(r for r in b['roofs'] if r['id'] == target['roof'])['plane_materials'][str(target['plane'])]
            assert ref == {'id': assets[f'cost{i}']['id']}
        drawn_ids = page.evaluate('''() => {
            const ids=new Set();window.__twin.scene.traverse(o=>{
                for(const m of o.material?[].concat(o.material):[])if(m.userData.materialId)ids.add(m.userData.materialId);
            });return [...ids];
        }''')
        assert {assets[f'cost{i}']['id'] for i in range(40)} <= set(drawn_ids), 'An override never reached a render material'
        measured = page.evaluate(FRAME_SAMPLE, 90)
        assert baseline['tier'] == measured['tier'] == 'low'
        assert len(baseline['times']) == len(measured['times']) == 90
        assert min(baseline['calls']) > 0 and min(measured['calls']) > 0
        print('SLOTS_COST ' + json.dumps({'tier': 'low', 'overrides': 40, 'frames': 90,
            'without': {'median_frame_ms': median(baseline['times']), 'draw_calls': median(baseline['calls'])},
            'with': {'median_frame_ms': median(measured['times']), 'draw_calls': median(measured['calls'])},
            'delta_ms': median(measured['times'])-median(baseline['times']),
            'launch_args': _gpu_args(),
            'vsync_and_frame_cap': 'caller must disable both before interpreting'}))
        twin_store.update_model(lambda _: copy.deepcopy(original), 'edit')


def main():
    scenarios = [scenario_wall_face_override_and_clear, scenario_roof_plane_override,
                 scenario_ledge_or_steps_override, scenario_uv_offset_moves_one_face,
                 scenario_house_wide_role_recolours_inheritors, scenario_one_wall_rebakes_locally,
                 scenario_many_overrides_low_tier_measure]
    passed = failed = 0
    try:
        for scenario in scenarios:
            try:
                scenario()
            except M.MeasurementSkipped as error:
                print('  skip ', error)
                print(f'{passed}/{len(scenarios)} passed; remaining scenarios skipped')
                return int(failed > 0)
            except Exception:
                failed += 1
                traceback.print_exc(limit=8)
                print('FAIL', scenario.__name__)
            else:
                passed += 1
                print('ok  ', scenario.__name__)
        print(f'{passed}/{len(scenarios)} passed')
        return int(failed > 0)
    finally:
        if SERVED is not None:
            SERVED.stop()


if __name__ == '__main__':
    sys.exit(main())

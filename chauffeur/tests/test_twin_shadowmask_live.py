"""The baked lights as a shadowmask, on the desktop GPU (real Chromium, real shaders).

The user, 2026-11-14, on the pool house gable at night: "The quality in the close compare
shot is still pretty rough" (mottled blotches, streaks along battens, muddy falloff). The bake
used to store irradiance (falloff x N.L x visibility, 8 bits, at the chart's density); now a
page stores only visibility, and the material lights each pixel through three's own RE_Direct
with the live light's colour, so it matches the live PointLight.

These checks run the real bake pass (bake/bake_pass.js renderPage) and the real material
patches (bake/lightmap_material.js patchLightmaps, patchWindowGlow) on bare scenes in the twin
page: a 12 x 8 ft wall at z = 0 facing +z, charted at 8 texels/ft on a 256 page, and a point
lamp in front of it. The twin page only provides the import map.

  visibility_is_a_fraction_of_the_lamp     every stored texel is in 0..255; an open wall reads
                                           fully lit without specks; a box casts an umbra and
                                           a soft penumbra
  baked_light_matches_the_live_light       a baked wall (metalness .5, roughness .6) matches the
                                           same wall under the live PointLight pixel by pixel:
                                           diffuse by metalness, specular, falloff (no mottling)
  a_normal_map_turns_toward_the_lamp       a normal map tilted toward +x brightens under a lamp
                                           on the +x side and darkens under one on the -x side
  brightness_and_colour_need_no_rebake     the tint halves the light and colours it; no new
                                           program and no material version change
  a_batten_front_shades_by_its_own_normal  a proxy turned 20 degrees from the wall (as a batten
                                           front within the 25 degree facing rule) reading the
                                           wall's texels is lit by its own normal
  an_unbaked_light_adds_nothing            a zero tint (the light is not fresh, so live lights
                                           draw it) adds nothing, even with a room fill
  the_fill_stops_at_the_reach              a texel past the light's reach stays dark
  a_fully_mapped_material_still_links      map, normal, roughness, metalness and AO maps, an
                                           environment, the sun's shadow and two shadowed point
                                           lights, plus three baked banks: the program links
                                           and draws (ANGLE allows 16 fragment samplers)
  room_mode_and_window_glow_compile        the room-mode material and the window glow link and
                                           draw light

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_shadowmask_live.py
"""
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import house_twin_live_harness as L  # noqa: E402

SCENE = r"""
async () => {
  const THREE = await import('three'), B = window.chfBase;
  const P = await import(B + 'static/twin/bake/bake_pass.js');
  const M = await import(B + 'static/twin/bake/lightmap_material.js');
  const FT = .3048, SIZE = 256, DENSITY = 8, W = 12, H = 8, RECT = { x: 2, y: 2, w: W * DENSITY, h: H * DENSITY };
  const CANDELA = 40, REACH = 30 * FT;
  const renderer = new THREE.WebGLRenderer({ antialias: false });
  renderer.setSize(64, 64); renderer.toneMapping = THREE.NoToneMapping;
  const out = {};
  const plane = (w, h, transform, uv, room = 0) => {
    const g = new THREE.PlaneGeometry(w * FT, h * FT).toNonIndexed(); transform(g);
    g.setAttribute('uv3', new THREE.Float32BufferAttribute(Array.from({ length: g.attributes.position.count }, (_, i) => uv(
      new THREE.Vector3().fromBufferAttribute(g.attributes.position, i))).flat(), 2));
    g.setAttribute('lmRoom', new THREE.Float32BufferAttribute(new Float32Array(g.attributes.position.count).fill(room), 1));
    return g;
  };
  const wallUV = p => [(RECT.x + p.x / FT * DENSITY) / SIZE, (RECT.y + p.y / FT * DENSITY) / SIZE];
  const wallGeometry = (room = 0) => plane(W, H, g => g.translate(W * FT / 2, H * FT / 2, 0), wallUV, room);
  const lamp = at => ({ device: 'lamp', absolute: true, at: [at[0], -at[2], at[1]], range: 30 });
  async function bake(at, blockers = []) {
    const scene = new THREE.Scene(), wall = new THREE.Mesh(wallGeometry(), new THREE.MeshStandardMaterial({ name: 'siding' }));
    wall.userData.merged = true; scene.add(wall);
    for (const b of blockers) { b.userData.merged = true; scene.add(b); }
    scene.updateMatrixWorld(true);
    const chart = { id: 0, mesh: wall, faces: [0, 1], rect: RECT, page: 0, room: 0, outdoor: false };
    const bytes = await P.renderPage({ scene, plan: {} }, renderer, [chart], SIZE, lamp(at), { room: { page: SIZE } }, { room: { charts: [chart] } });
    const vis = [];
    for (let y = RECT.y; y < RECT.y + RECT.h; y++) for (let x = RECT.x; x < RECT.x + RECT.w; x++) vis.push(bytes[(y * SIZE + x) * 4]);
    return { bytes, vis };
  }
  // --- visibility ---
  const open = await bake([6, 4, 4]);
  const box = new THREE.Mesh(new THREE.BoxGeometry(1 * FT, 1 * FT, 1 * FT), new THREE.MeshStandardMaterial({ name: 'siding' }));
  box.position.set(6 * FT, 4 * FT, 1.5 * FT);
  const shaded = await bake([6, 4, 4], [box]);
  out.visibility = { openMin: Math.min(...open.vis), openBelow250: open.vis.filter(v => v < 250).length, count: open.vis.length,
    allBytes: open.vis.every(v => v >= 0 && v <= 255),
    umbra: shaded.vis.filter(v => v === 0).length, penumbra: shaded.vis.filter(v => v > 10 && v < 245).length, lit: shaded.vis.filter(v => v === 255).length };
  // --- the pages and uniforms of a chart-mode wall ---
  const pageOf = bytes => {
    const page = new THREE.DataArrayTexture(new Uint8Array(SIZE * SIZE * 4), SIZE, SIZE, 1);
    for (let i = 0; i < SIZE * SIZE; i++) page.image.data[i * 4] = bytes[i * 4];
    page.format = THREE.RGBAFormat; page.minFilter = page.magFilter = THREE.LinearFilter; page.generateMipmaps = false; page.needsUpdate = true;
    return page;
  };
  const page = pageOf(open.bytes);
  const chartUniforms = (banks = 1) => M.chartLightmapUniforms(1, { banks: Array.from({ length: banks }, () => ({ charts: [{ id: 0, page: 0, rect: RECT, sourceRegion: RECT }] })),
    slots: { lamp: { assignments: [{ chart: 0, bank: 0, channel: 0 }] } } }, [{ device: 'lamp' }], SIZE, Array.from({ length: banks }, () => [0]));
  const uniforms = chartUniforms();
  const source = at => new THREE.Vector3(at[0] * FT, at[1] * FT, at[2] * FT);
  M.setLightTint(uniforms, 0, 0, [255, 255, 255], 1);
  const target = new THREE.WebGLRenderTarget(48, 32, { type: THREE.FloatType });
  const view = (meshes, camera, lights = []) => {
    const scene = new THREE.Scene(); for (const m of [].concat(meshes, lights)) scene.add(m);
    renderer.setRenderTarget(target); renderer.setClearColor(0, 0); renderer.clear();
    renderer.render(scene, camera); const px = new Float32Array(48 * 32 * 4); renderer.readRenderTargetPixels(target, 0, 0, 48, 32, px);
    renderer.setRenderTarget(null); return px;
  };
  const front = new THREE.OrthographicCamera(0, W * FT, H * FT, 0, .1, 10); front.position.set(0, 0, 5); front.updateMatrixWorld(true);
  const patched = (extra, u = uniforms, pages = [page]) => { const m = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 1, metalness: 0, ...extra }); M.patchLightmaps([m], { banks: pages }, u); return m; };
  const livePoint = at => { const l = new THREE.PointLight(0xffffff, CANDELA, REACH, 2); l.position.copy(source(at)); return l; };
  const centre = (j, i) => (j * 48 + i) * 4;
  // --- parity with the live light ---
  const metal = { roughness: .6, metalness: .5, color: 0xc8a070 };
  const baked = new THREE.Mesh(wallGeometry(), patched(metal)), plain = new THREE.Mesh(wallGeometry(), new THREE.MeshStandardMaterial(metal));
  M.setLightSource(uniforms, 0, 0, source([6, 4, 4]), REACH);
  const bakedPx = view(baked, front), livePx = view(plain, front, [livePoint([6, 4, 4])]);
  const ratios = [];
  for (let j = 2; j < 30; j++) for (let i = 2; i < 46; i++) for (let c = 0; c < 3; c++) {
    const live = livePx[centre(j, i) + c]; if (live > 1e-3) ratios.push(bakedPx[centre(j, i) + c] / live);
  }
  const mean = ratios.reduce((a, b) => a + b, 0) / ratios.length;
  out.parity = { mean, std: Math.sqrt(ratios.reduce((a, b) => a + (b - mean) ** 2, 0) / ratios.length), min: Math.min(...ratios), max: Math.max(...ratios), n: ratios.length };
  // --- brightness and colour ---
  const flat = patched(), wall = new THREE.Mesh(wallGeometry(), flat);
  const full = view(wall, front);
  const programs = renderer.info.programs.length, version = flat.version;
  M.setLightTint(uniforms, 0, 0, [255, 255, 255], .5); const half = view(wall, front);
  M.setLightTint(uniforms, 0, 0, [255, 0, 0], 1); const red = view(wall, front);
  M.setChartFill(uniforms, 0, 0, 1, 0, .5);
  M.setLightTint(uniforms, 0, 0, [255, 255, 255], 0); const off = view(wall, front);
  out.tint = { full: full[centre(16, 24)], half: half[centre(16, 24)], redR: red[centre(16, 24)], redG: red[centre(16, 24) + 1],
    off: Math.max(...off.filter((v, i) => i % 4 < 3)), programs: [programs, renderer.info.programs.length], versions: [version, flat.version] };
  // --- the fill stops at the reach: a 4 ft lamp at x = 1 ft, fill only ---
  M.setLightTint(uniforms, 0, 0, [255, 255, 255], 1);
  const blind = pageOf(new Uint8Array(SIZE * SIZE * 4));                    // nothing seen: the fill alone
  const fillOnly = new THREE.Mesh(wallGeometry(), patched({}, uniforms, [blind]));
  M.setLightSource(uniforms, 0, 0, source([1, 4, .5]), 4 * FT);
  const fillPx = view(fillOnly, front), near = [], far = [];
  for (let i = 0; i < 48; i++) { const x = (i + .5) / 48 * W; (x < 2.5 ? near : x > 5.5 ? far : []).push(fillPx[centre(16, i)]); }
  out.fill = { near: Math.min(...near), far: Math.max(...far) };
  M.setChartFill(uniforms, 0, 0, 1, 0, 0);
  // --- normal map: a constant tangent-space normal leaning 30 degrees toward +x (u) ---
  const tilt = new THREE.DataTexture(new Uint8Array([Math.round((.5 + .5 * .5) * 255), 128, Math.round((.5 + .5 * .866) * 255), 255]), 1, 1);
  tilt.needsUpdate = true;
  const bumpy = new THREE.Mesh(wallGeometry(), patched({ normalMap: tilt }));
  const at = side => { M.setLightSource(uniforms, 0, 0, source([side, 4, 2]), REACH); return [view(wall, front)[centre(16, 24)], view(bumpy, front)[centre(16, 24)]]; };
  out.normalMap = { east: at(11), west: at(1) };
  // --- a batten front: 0.09 ft proud at x = 3..3.5 ft, turned 20 degrees toward +x ---
  const turn = 20 * Math.PI / 180, own = new THREE.Vector3(Math.sin(turn), 0, Math.cos(turn));
  const frontUV = p => wallUV(new THREE.Vector3(p.x, p.y, 0));
  const batten = new THREE.Mesh(plane(.5, H, g => { g.rotateY(turn); g.translate(3.25 * FT, H * FT / 2, .09 * FT); }, frontUV), patched());
  const battenPlain = new THREE.Mesh(batten.geometry, new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 1, metalness: 0 }));
  const look = new THREE.OrthographicCamera(-.3 * FT, .3 * FT, H * FT, 0, .1, 10);
  look.position.set(3.25 * FT + own.x * 2, 0, .09 * FT + own.z * 2); look.lookAt(3.25 * FT, 0, .09 * FT); look.updateMatrixWorld(true);
  M.setLightSource(uniforms, 0, 0, source([11, 4, 2]), REACH);
  const proxyPx = view(batten, look), livePx2 = view(battenPlain, look, [livePoint([11, 4, 2])]);
  const p = new THREE.Vector3(3.25 * FT, H * FT / 2, .09 * FT), l = source([11, 4, 2]).sub(p).normalize();
  out.proxy = { got: proxyPx[centre(16, 24)], live: livePx2[centre(16, 24)], ownCos: own.dot(l), wallCos: l.z };
  // --- a fully mapped material with every shadow the house can cast ---
  const tex = (r, g, b) => { const t = new THREE.DataTexture(new Uint8Array([r, g, b, 255]), 1, 1); t.needsUpdate = true; return t; };
  const pmrem = new THREE.PMREMGenerator(renderer), env = pmrem.fromScene(new THREE.Scene()).texture;
  const three = chartUniforms(3), banks3 = [page, pageOf(open.bytes), pageOf(open.bytes)];
  M.setLightTint(three, 0, 0, [255, 255, 255], 1); M.setLightSource(three, 0, 0, source([6, 4, 4]), REACH);
  const heavy = patched({ map: tex(200, 180, 160), normalMap: tex(128, 128, 255), roughnessMap: tex(0, 150, 0), metalnessMap: tex(0, 0, 40),
    aoMap: tex(230, 230, 230), envMap: env, envMapIntensity: .2 }, three, banks3);
  const heavyWall = new THREE.Mesh(wallGeometry(), heavy); heavyWall.receiveShadow = true;
  heavyWall.geometry.setAttribute('uv1', heavyWall.geometry.attributes.uv);
  renderer.shadowMap.enabled = true;
  const sun = new THREE.DirectionalLight(0xffffff, .2); sun.position.set(2, 4, 6); sun.castShadow = true;
  const points = [livePoint([2, 6, 3]), livePoint([10, 6, 3])].map(x => { x.intensity = 1; x.castShadow = true; return x; });
  const caster = new THREE.Mesh(new THREE.BoxGeometry(.3, .3, .3), new THREE.MeshStandardMaterial()); caster.position.set(1.8, 1.2, .6); caster.castShadow = true;
  const gl = renderer.getContext(), heavyPx = view([heavyWall, caster], front, [sun, ...points]);
  const linked = m => { const prog = renderer.properties.get(m).currentProgram; return !!prog && gl.getProgramParameter(prog.program, gl.LINK_STATUS) && (!prog.diagnostics || prog.diagnostics.runnable); };
  out.heavy = { linked: linked(heavy), lit: heavyPx[centre(16, 24)], samplers: gl.getParameter(gl.MAX_TEXTURE_IMAGE_UNITS) };
  // The production typed pool, including parked area slots and their LTC samplers.
  const {createRealLights} = await import(B + 'static/twin/live/real_lights.js');
  const poolScene = new THREE.Scene(), rig = createRealLights({scene:poolScene,tier:'high'});
  rig.show(true);
  const poolLights = poolScene.children.filter(o=>o.isLight), areas = poolLights.filter(o=>o.isRectAreaLight);
  const poolPx = view([heavyWall,caster], front, [sun,...poolLights]);
  rig.warm(()=>view([heavyWall,caster],front,[sun,...poolLights]));
  const programKeys = () => renderer.info.programs.map(p=>p.cacheKey).sort();
  const keysBefore = programKeys();
  const candidate = (device,shape,at,extra={}) => ({device,at,position:new THREE.Vector3(at[0]*FT,at[2]*FT,-at[1]*FT),distance:REACH,intensity:1,rgb:[255,255,255],
    emitter:{shape,at,normal:[0,-1,0],size_ft:[2,1],cd:40,luminance:20,output_lm_share:503,aim:[6,0,4],cone_deg:60,softness:.3,...extra}});
  rig.update([candidate('point','point',[6,-4,4]),candidate('spot','spot',[6,-4,4]),candidate('area','area',[6,-4,4])],[0,0,0]);
  view([heavyWall,caster],front,[sun,...poolLights]);const keysOn=programKeys();
  rig.update([candidate('spot','spot',[6,-4,4])],[0,0,0]);view([heavyWall,caster],front,[sun,...poolLights]);
  const keysSpot = programKeys();
  rig.update([], [0,0,0]);view([heavyWall,caster],front,[sun,...poolLights]);
  const samplerTypes = new Set([gl.SAMPLER_2D,gl.SAMPLER_CUBE,gl.SAMPLER_2D_ARRAY,gl.SAMPLER_2D_SHADOW,gl.SAMPLER_CUBE_SHADOW]);
  const program = renderer.properties.get(heavy).currentProgram.program;
  let samplerCount=0;
  for(let i=0;i<gl.getProgramParameter(program,gl.ACTIVE_UNIFORMS);i++){
    const u=gl.getActiveUniform(program,i);if(samplerTypes.has(u.type))samplerCount+=u.size;
  }
  out.typedPool = {areas:areas.length,linked:linked(heavy),lit:poolPx[centre(16,24)],samplerCount,stable:JSON.stringify(keysBefore)===JSON.stringify(keysOn)&&JSON.stringify(keysOn)===JSON.stringify(keysSpot)&&JSON.stringify(keysSpot)===JSON.stringify(programKeys())};
  rig.stop();
  renderer.shadowMap.enabled = false;
  // RectAreaLights do not set three's punctual-light multiscatter term. The
  // baked term must still match a live point when only areas are present.
  const area = new THREE.RectAreaLight(0xffffff,20,FT,FT);area.position.copy(source([6,4,4]));
  const areaLive = view(plain,front,[area,livePoint([6,4,4])]);
  M.setLightSource(uniforms,0,0,source([6,4,4]),REACH);
  const areaBaked = view(baked,front,[area]);
  out.areaOnly={baked:areaBaked[centre(16,24)],live:areaLive[centre(16,24)]};
  // --- room mode and window glow ---
  const roomU = M.lightmapUniforms(2, 4);
  const roomMat = patched({}, roomU, [page, pageOf(open.bytes)]);
  M.setLightTint(roomU, 1, 0, [255, 255, 255], 1); M.setLightSource(roomU, 1, 0, source([6, 4, 4]), REACH);
  const roomPx = view(new THREE.Mesh(wallGeometry(1), roomMat), front);
  const glass = new THREE.MeshStandardMaterial({ color: 0x000000, roughness: 1 }), glowGeo = wallGeometry();
  glowGeo.setAttribute('glowRoom', glowGeo.attributes.lmRoom); glowGeo.setAttribute('glowUV', glowGeo.attributes.uv3);
  M.setLightSource(uniforms, 0, 0, source([6, 4, 4]), REACH);
  M.patchWindowGlow(glass, { banks: [page] }, uniforms);
  const glowPx = view(new THREE.Mesh(glowGeo, glass), front);
  out.modes = { room: { linked: linked(roomMat), lit: roomPx[centre(16, 24)] }, glow: { linked: linked(glass), lit: glowPx[centre(16, 24)] } };
  renderer.dispose();
  return out;
}
"""


def run():
    served = L.serve()
    L.reset()
    failures = []
    errors = []
    with served.browser(launch_args=L.GPU_ARGS) as page:
        page.set_viewport_size({'width': 1200, 'height': 800})
        page.on('console', lambda m: errors.append(m.text[:400]) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
        L.H.signed_in(page)
        L.open_twin(page, served, query='tier=high&test=1')
        result = page.evaluate(SCENE)
    print('MEASURED', json.dumps(result))
    v, par, t, n, p, f, h, m = (result[k] for k in ('visibility', 'parity', 'tint', 'normalMap', 'proxy', 'fill', 'heavy', 'modes'))

    def check(name, fn):
        try:
            fn()
            print('  ok   ' + name)
        except AssertionError as error:
            failures.append(name)
            print('  FAIL ' + name + ' ' + str(error)[:600])
            traceback.print_exc(limit=1)

    def visibility():
        assert v['allBytes'], 'every stored texel is a visibility byte'
        assert v['openBelow250'] <= v['count'] * .005, f'an open wall reads fully seen, no specks: {v}'
        assert v['umbra'] > 50 and v['penumbra'] > 20 and v['lit'] > v['count'] / 2, f'a box casts an umbra and a soft edge: {v}'

    def parity():
        assert par['n'] > 1000, par
        assert abs(par['mean'] - 1) < .02 and par['min'] > .97 and par['max'] < 1.03, f'the baked wall is the live wall: {par}'

    def normal_map():
        assert n['east'][1] > n['east'][0] * 1.1, f'tilted toward +x: brighter under the east lamp {n}'
        assert n['west'][1] < n['west'][0] * .9, f'and darker under the west one {n}'

    def tint():
        assert abs(t['half'] / t['full'] - .5) < .01, f'brightness halves the light: {t}'
        assert t['redR'] > 0 and t['redG'] == 0, f'and colour colours it: {t}'
        assert t['programs'][0] == t['programs'][1] and t['versions'][0] == t['versions'][1], f'with no new program: {t}'

    def proxy():
        assert abs(p['got'] / p['live'] - 1) < .03, f'a batten front is lit as the live light lights it, by its own normal: {p}'
        assert abs(p['ownCos'] / p['wallCos'] - 1) > .2, f'which differs from the wall\'s: {p}'

    def unbaked():
        assert t['off'] == 0, f'a zero tint adds nothing, even with a fill: {t}'

    def fill():
        assert f['near'] > 0, f'within reach the fill shows: {f}'
        assert f['far'] == 0, f'past the reach a texel stays dark: {f}'

    def heavy():
        assert not errors, errors[:3]
        assert h['linked'] and h['lit'] > 0, f'the fully mapped, fully shadowed material links and draws: {h}'

    def modes():
        assert m['room']['linked'] and m['room']['lit'] > 0, f'room mode links and draws its light: {m}'
        assert m['glow']['linked'] and m['glow']['lit'] > 0, f'the window glow links and glows: {m}'

    def typed_pool():
        pool = result['typedPool']
        assert pool['areas'] == 8, pool
        assert pool['linked'] and pool['lit'] > 0, pool
        assert pool['samplerCount'] <= 16, pool
        assert pool['stable'], f'render, toggle, render preserves program keys: {pool}'

    def area_only():
        a = result['areaOnly']
        assert a['live'] > 0 and abs(a['baked'] / a['live'] - 1) < .02, a

    for name, fn in (('visibility_is_a_fraction_of_the_lamp', visibility), ('baked_light_matches_the_live_light', parity),
                     ('a_normal_map_turns_toward_the_lamp', normal_map), ('brightness_and_colour_need_no_rebake', tint),
                     ('a_batten_front_shades_by_its_own_normal', proxy), ('an_unbaked_light_adds_nothing', unbaked),
                     ('the_fill_stops_at_the_reach', fill), ('a_fully_mapped_material_still_links', heavy),
                     ('room_mode_and_window_glow_compile', modes), ('program_keys_stable_when_lights_switch', typed_pool),
                     ('area_only_multiscatter_matches_live', area_only)):
        check(name, fn)
    print(f'{11 - len(failures)}/11 passed')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(run())

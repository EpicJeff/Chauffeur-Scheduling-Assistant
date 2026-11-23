"""Chromium GPU tests for the placed-model lighting shader patch (model_light_material.js).

Tests real WebGL2 compilation, rendering, sampler census, clone safety, slab-1 odd-slot
decoding, rect representative-point clamping, zero-distance NaN safety, and parity
against unpatched MeshStandardMaterial using Task 6's createModelLightTextures.

Run from chauffeur/: python tests/test_twin_model_light_live.py
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
  const { createModelLightTextures, BRICK_BYTES, BRICK_TEX_WIDTH, BRICK_TEX_HEIGHT, BRICK_SIZE } = await import(B + 'static/twin/bake/model_bricks.js');
  const { patchModelLighting } = await import(B + 'static/twin/bake/model_light_material.js');

  const renderer = new THREE.WebGLRenderer({ antialias: false });
  renderer.setSize(64, 64);
  renderer.toneMapping = THREE.NoToneMapping;
  const gl = renderer.getContext();

  const target = new THREE.WebGLRenderTarget(32, 32, { type: THREE.FloatType });
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 20);
  camera.position.set(0, 0, 5);
  camera.lookAt(0, 0, 0);
  camera.updateMatrixWorld(true);

  const renderCenterLum = (meshes, lights = [], cam = camera) => {
    const scene = new THREE.Scene();
    for (const m of meshes) scene.add(m);
    for (const l of lights) scene.add(l);
    renderer.setRenderTarget(target);
    renderer.setClearColor(0x000000, 1);
    renderer.clear();
    renderer.render(scene, cam);
    const px = new Float32Array(32 * 32 * 4);
    renderer.readRenderTargetPixels(target, 0, 0, 32, 32, px);
    renderer.setRenderTarget(null);
    const i = (16 * 32 + 16) * 4;
    const r = px[i], g = px[i + 1], b = px[i + 2];
    return { r, g, b, lum: 0.2126 * r + 0.7152 * g + 0.0722 * b };
  };

  const inspectProgram = mat => {
    const progObj = renderer.properties.get(mat).currentProgram;
    const prog = progObj?.program;
    const linked = !!prog && gl.getProgramParameter(prog, gl.LINK_STATUS) && (!progObj.diagnostics || progObj.diagnostics.runnable);
    const samplerTypes = new Set([
      gl.SAMPLER_2D, gl.SAMPLER_CUBE, gl.SAMPLER_2D_ARRAY, gl.SAMPLER_3D,
      gl.SAMPLER_2D_SHADOW, gl.SAMPLER_CUBE_SHADOW,
    ]);
    const active = gl.getProgramParameter(prog, gl.ACTIVE_UNIFORMS);
    const samplers = [];
    let uniformCount = 0;
    for (let i = 0; i < active; i++) {
      const u = gl.getActiveUniform(prog, i);
      uniformCount += u.size;
      if (samplerTypes.has(u.type)) samplers.push({ name: u.name, type: u.type, size: u.size });
    }
    let mvDeclCount = 0;
    for (const sh of gl.getAttachedShaders(prog) || []) {
      if (gl.getShaderParameter(sh, gl.SHADER_TYPE) === gl.FRAGMENT_SHADER) {
        const src = gl.getShaderSource(sh) || '';
        mvDeclCount = (src.match(/uniform\s+highp\s+sampler3D\s+mvBricks\s*;/g) || []).length;
      }
    }
    return {
      linked,
      cacheKey: progObj?.cacheKey,
      mvDeclCount,
      samplers,
      samplerCount: samplers.reduce((s, x) => s + x.size, 0),
      uniformCount,
    };
  };

  const setBrickAttr = (geo, value) => {
    const n = geo.attributes.position.count;
    geo.setAttribute('mvBrick', new THREE.BufferAttribute(new Float32Array(n).fill(value), 1));
    return geo;
  };

  // Build model light textures: 8 emitters, 6 bricks
  const tex = createModelLightTextures({ maxBricks: 6, maxEmitters: 8 });
  const shared = {
    mvBricks: { value: tex.bricks },
    mvLamps: { value: tex.lamps },
    mvSize: { value: tex.mvSize },
  };

  // Emitter 0: point lamp at (0, 0, 2.5) facing box front face at z = 0.5
  const pointRec = {
    id: 'light.p0#0', device: 'light.p0', index: 0, column: 0, row: 0, shape: 0,
    position: new THREE.Vector3(0, 0, 2.5), range: 10.0,
    axis: new THREE.Vector3(0, 0, -1), cosOuter: -1, cosInner: -1,
    halfSize: [0, 0], rotation: new THREE.Quaternion(), outputScale: 40,
  };
  tex.writeEmitter(0, pointRec);
  tex.setTint(0, new THREE.Color(1, 1, 1));
  for (let e = 1; e < 8; e++) {
    tex.writeEmitter(e, {
      ...pointRec, id: `light.p${e}#0`, device: `light.p${e}`, row: e,
      position: new THREE.Vector3((e - 4) * 0.2, 0, 2.5),
      outputScale: e === 5 ? 40 : 5,
    });
    tex.setTint(e, new THREE.Color(1, 1, 1));
  }

  const visFull = new Uint8Array(BRICK_BYTES).fill(254);
  const visZero = new Uint8Array(BRICK_BYTES).fill(0);
  // Brick data where ONLY slot 5 (slab 1: x=5..9, channel 1) is 254 and all other slots are 0
  const visSlot5Only = new Uint8Array(BRICK_BYTES);
  for (let iz = 0; iz < BRICK_SIZE; iz++) {
    for (let iy = 0; iy < BRICK_SIZE; iy++) {
      for (let ix = 0; ix < BRICK_SIZE; ix++) {
        const off = ((iz * BRICK_TEX_HEIGHT + iy) * BRICK_TEX_WIDTH + (5 + ix)) * 4 + 1;
        visSlot5Only[off] = 254;
      }
    }
  }

  const unitBox = new THREE.Box3(new THREE.Vector3(-0.5, -0.5, -0.5), new THREE.Vector3(0.5, 0.5, 0.5));
  // Brick 0 (mvBrick = 1): emitter 0 visibility = 254
  tex.writeBrick(0, visFull, [0], new THREE.Color(0, 0, 0), unitBox, [1.0]);
  // Brick 1 (mvBrick = 2): emitter 0 visibility = 0
  tex.writeBrick(1, visZero, [0], new THREE.Color(0, 0, 0), unitBox, [1.0]);
  // Brick 2 (mvBrick = 3): 8 emitters, all visible
  tex.writeBrick(2, visFull, [0, 1, 2, 3, 4, 5, 6, 7], new THREE.Color(0, 0, 0), unitBox);
  // Brick 3 (mvBrick = 4): emitter 0 visibility = 254 with folded scale = 2.0 and room fill
  tex.writeBrick(3, visFull, [0], new THREE.Color(0.2, 0.2, 0.2), unitBox, [2.0]);
  // Brick 4 (mvBrick = 5): 6 emitters [0..5], ONLY slot 5 has visibility 254 (slab 1, odd slot)
  tex.writeBrick(4, visSlot5Only, [0, 1, 2, 3, 4, 5], new THREE.Color(0, 0, 0), unitBox);

  const matParams = { color: 0xffffff, roughness: 0.7, metalness: 0.1 };
  const unpatchedMat = new THREE.MeshStandardMaterial(matParams);
  const patchedMat = new THREE.MeshStandardMaterial(matParams);
  patchModelLighting(patchedMat, shared);
  const keyOnce = patchedMat.customProgramCacheKey();
  patchModelLighting(patchedMat, shared);
  const keyTwice = patchedMat.customProgramCacheKey();

  const ambient = new THREE.AmbientLight(0xffffff, 0.08);
  const boxAGeo = setBrickAttr(new THREE.BoxGeometry(1, 1, 1), 1);
  const boxBGeo = setBrickAttr(new THREE.BoxGeometry(1, 1, 1), 2);
  const box8Geo = setBrickAttr(new THREE.BoxGeometry(1, 1, 1), 3);
  const boxFoldGeo = setBrickAttr(new THREE.BoxGeometry(1, 1, 1), 4);
  const boxSlot5Geo = setBrickAttr(new THREE.BoxGeometry(1, 1, 1), 5);
  const boxNoAttrGeo = new THREE.BoxGeometry(1, 1, 1);
  const boxZeroGeo = setBrickAttr(new THREE.BoxGeometry(1, 1, 1), 0);

  const boxA = new THREE.Mesh(boxAGeo, patchedMat);
  const boxB = new THREE.Mesh(boxBGeo, patchedMat);
  const box8 = new THREE.Mesh(box8Geo, patchedMat);
  const boxFold = new THREE.Mesh(boxFoldGeo, patchedMat);
  const boxSlot5 = new THREE.Mesh(boxSlot5Geo, patchedMat);
  const boxNoAttr = new THREE.Mesh(boxNoAttrGeo, patchedMat);
  const boxZero = new THREE.Mesh(boxZeroGeo, patchedMat);
  const boxRef = new THREE.Mesh(boxNoAttrGeo, unpatchedMat);

  // 1. Brick lights and shadows
  const refPx = renderCenterLum([boxRef], [ambient]);
  const aPx = renderCenterLum([boxA], [ambient]);
  const programsAfter1 = renderer.info.programs.length;
  const cacheKey1 = renderer.properties.get(patchedMat).currentProgram?.cacheKey;
  const bPx = renderCenterLum([boxB], [ambient]);
  const foldPx = renderCenterLum([boxFold], [ambient]);

  // 2. Count 8 uses same program as count 1
  const eightPx = renderCenterLum([box8], [ambient]);
  const programsAfter8 = renderer.info.programs.length;
  const cacheKey8 = renderer.properties.get(patchedMat).currentProgram?.cacheKey;

  // 3. Slot 5 only visible (proves slab 1 textureLod + odd-slot decode)
  // Turn emitter 5 red-only so we also confirm emitter 5's own row was decoded (not 0..4!)
  tex.setTint(5, new THREE.Color(1, 0, 0));
  const slot5Px = renderCenterLum([boxSlot5], [ambient]);
  tex.setTint(5, new THREE.Color(1, 1, 1));

  // 4. Zero-distance NaN safety: emitter placed right on the box front face (0, 0, 0.5)
  tex.writeEmitter(0, { ...pointRec, position: new THREE.Vector3(0, 0, 0.5) });
  tex.setTint(0, new THREE.Color(1, 1, 1));
  const zeroDistPx = renderCenterLum([boxA], [ambient]);
  tex.writeEmitter(0, pointRec);
  tex.setTint(0, new THREE.Color(1, 1, 1));

  // 5. No mvBrick attribute and mvBrick = 0 match unpatched
  const noAttrPx = renderCenterLum([boxNoAttr], [ambient]);
  const zeroAttrPx = renderCenterLum([boxZero], [ambient]);

  // 6. Setting tint to 0 makes Box A match unpatched within 1%
  tex.setTint(0, new THREE.Color(0, 0, 0));
  const aOffPx = renderCenterLum([boxA], [ambient]);
  const foldFillOnlyPx = renderCenterLum([boxFold], [ambient]);
  tex.setTint(0, new THREE.Color(1, 1, 1));

  // 7. Spot cone forward vs away
  const spotRec = {
    ...pointRec, id: 'light.spot#0', shape: 1,
    axis: new THREE.Vector3(0, 0, -1), cosOuter: Math.cos(30 * Math.PI / 180), cosInner: Math.cos(15 * Math.PI / 180),
  };
  tex.writeEmitter(0, spotRec);
  tex.setTint(0, new THREE.Color(1, 1, 1));
  const spotLitPx = renderCenterLum([boxA], [ambient]);
  tex.writeEmitter(0, { ...spotRec, axis: new THREE.Vector3(0, 0, 1) });
  const spotAwayPx = renderCenterLum([boxA], [ambient]);

  // 8. Rect representative-point clamp test:
  // Wide rect (halfW = 1.5 m) centred at (0, 0, 1.5) facing (0, 0, -1).
  // Sample box at x = 1.5 (front face at (1.5, 0, 0.5), directly in front of the rect's right edge).
  // Compare against a point emitter of the exact same outputScale at the rect's centre (0, 0, 1.5).
  const edgeCam = new THREE.OrthographicCamera(0.5, 2.5, 1, -1, 0.1, 20);
  edgeCam.position.set(0, 0, 5);
  edgeCam.updateMatrixWorld(true);
  const edgeBox = new THREE.Box3(new THREE.Vector3(1.0, -0.5, -0.5), new THREE.Vector3(2.0, 0.5, 0.5));
  tex.writeBrick(5, visFull, [0], new THREE.Color(0, 0, 0), edgeBox, [1.0]);
  const edgeBoxGeo = setBrickAttr(new THREE.BoxGeometry(1, 1, 1), 6);
  const edgeMesh = new THREE.Mesh(edgeBoxGeo, patchedMat);
  edgeMesh.position.set(1.5, 0, 0);
  edgeMesh.updateMatrixWorld(true);

  const rectEdgeRec = {
    ...pointRec, id: 'light.rect#0', shape: 2,
    position: new THREE.Vector3(0, 0, 1.5),
    halfSize: [1.5, 0.05], rotation: new THREE.Quaternion(), outputScale: 40,
  };
  tex.writeEmitter(0, rectEdgeRec);
  tex.setTint(0, new THREE.Color(1, 1, 1));
  const rectEdgePx = renderCenterLum([edgeMesh], [ambient], edgeCam);
  // Same outputScale as a point at the rect centre (0, 0, 1.5)
  tex.writeEmitter(0, { ...pointRec, position: new THREE.Vector3(0, 0, 1.5), outputScale: 40 });
  tex.setTint(0, new THREE.Color(1, 1, 1));
  const pointCenterPx = renderCenterLum([edgeMesh], [ambient], edgeCam);

  // Restore point emitter
  tex.writeEmitter(0, pointRec);
  tex.setTint(0, new THREE.Color(1, 1, 1));

  // 9. Clone safety (reflection_probes.js / twin_generator.js pattern):
  // Clone patchedMat, copy onBeforeCompile & customProgramCacheKey, then patch the clone.
  // Also clone with an extra hook (distinct program key), then patch it.
  const cloneSame = patchedMat.clone();
  cloneSame.onBeforeCompile = patchedMat.onBeforeCompile;
  cloneSame.customProgramCacheKey = patchedMat.customProgramCacheKey;
  patchModelLighting(cloneSame, shared);

  const cloneExtra = patchedMat.clone();
  cloneExtra.onBeforeCompile = patchedMat.onBeforeCompile;
  cloneExtra.customProgramCacheKey = patchedMat.customProgramCacheKey;
  const prevHook = cloneExtra.onBeforeCompile;
  const prevKey = cloneExtra.customProgramCacheKey.bind(cloneExtra);
  cloneExtra.onBeforeCompile = function (shader, r) {
    prevHook.call(this, shader, r);
    shader.fragmentShader = '// extra-clone-hook\n' + shader.fragmentShader;
  };
  cloneExtra.customProgramCacheKey = () => prevKey() + '|extra-hook';
  patchModelLighting(cloneExtra, shared);

  const cloneSameMesh = new THREE.Mesh(boxAGeo, cloneSame);
  const cloneExtraMesh = new THREE.Mesh(boxAGeo, cloneExtra);
  const origLitPx = renderCenterLum([boxA], [ambient]);
  const cloneSamePx = renderCenterLum([cloneSameMesh], [ambient]);
  const cloneExtraPx = renderCenterLum([cloneExtraMesh], [ambient]);
  const origProgInfo = inspectProgram(patchedMat);
  const cloneSameProgInfo = inspectProgram(cloneSame);
  const cloneExtraProgInfo = inspectProgram(cloneExtra);

  // 10. Sampler census: genuinely unpatched non-model mesh rendered in the SAME scene as a patched model mesh
  const nonModelMat = new THREE.MeshStandardMaterial({ color: 0xdddddd, roughness: 0.4, metalness: 0.2 });
  const nonModelMesh = new THREE.Mesh(boxNoAttrGeo, nonModelMat);
  nonModelMesh.position.set(-0.6, 0, -1.5);
  nonModelMesh.frustumCulled = false;
  renderCenterLum([boxA, nonModelMesh], [ambient]);
  const nonModelCensus = inspectProgram(nonModelMat);
  const patchedCensus = inspectProgram(patchedMat);
  const unpatchedCensus = inspectProgram(unpatchedMat);
  const nonModelHasOwnProgram = renderer.properties.get(nonModelMat).currentProgram !== renderer.properties.get(patchedMat).currentProgram;

  // Heavy PBR model material (albedo, normal, roughness, metalness, ao, env)
  const dt = (r, g, b) => { const t = new THREE.DataTexture(new Uint8Array([r, g, b, 255]), 1, 1); t.needsUpdate = true; return t; };
  const pmrem = new THREE.PMREMGenerator(renderer);
  const env = pmrem.fromScene(new THREE.Scene()).texture;
  const heavyUnpatched = new THREE.MeshStandardMaterial({
    map: dt(200, 180, 160), normalMap: dt(128, 128, 255), roughnessMap: dt(0, 150, 0),
    metalnessMap: dt(0, 0, 40), aoMap: dt(230, 230, 230), envMap: env,
  });
  const heavyPatched = heavyUnpatched.clone();
  patchModelLighting(heavyPatched, shared);
  const heavyGeo = setBrickAttr(new THREE.BoxGeometry(1, 1, 1), 1);
  heavyGeo.setAttribute('uv1', heavyGeo.attributes.uv);
  renderCenterLum([new THREE.Mesh(heavyGeo, heavyUnpatched)], [ambient]);
  renderCenterLum([new THREE.Mesh(heavyGeo, heavyPatched)], [ambient]);
  const heavyUnpatchedCensus = inspectProgram(heavyUnpatched);
  const heavyPatchedCensus = inspectProgram(heavyPatched);

  const glErr = gl.getError();

  for (const g of [boxAGeo, boxBGeo, box8Geo, boxFoldGeo, boxSlot5Geo, boxNoAttrGeo, boxZeroGeo, edgeBoxGeo, heavyGeo]) g.dispose();
  for (const m of [unpatchedMat, patchedMat, cloneSame, cloneExtra, nonModelMat, heavyUnpatched, heavyPatched]) m.dispose();
  pmrem.dispose();
  env.dispose();
  tex.dispose();
  target.dispose();
  renderer.dispose();

  return {
    glErr,
    keyOnce,
    keyTwice,
    refLum: refPx.lum,
    aLum: aPx.lum,
    bLum: bPx.lum,
    aOffLum: aOffPx.lum,
    foldLum: foldPx.lum,
    foldFillOnlyLum: foldFillOnlyPx.lum,
    eightLum: eightPx.lum,
    slot5Px,
    zeroDistFinite: Number.isFinite(zeroDistPx.lum) && Number.isFinite(zeroDistPx.r),
    noAttrLum: noAttrPx.lum,
    zeroAttrLum: zeroAttrPx.lum,
    spotLitLum: spotLitPx.lum,
    spotAwayLum: spotAwayPx.lum,
    rectEdgeLum: rectEdgePx.lum,
    pointCenterLum: pointCenterPx.lum,
    origLitLum: origLitPx.lum,
    cloneSameLum: cloneSamePx.lum,
    cloneExtraLum: cloneExtraPx.lum,
    origProgInfo,
    cloneSameProgInfo,
    cloneExtraProgInfo,
    programsAfter1,
    programsAfter8,
    sameProgramKey: cacheKey1 === cacheKey8,
    unpatchedCensus,
    patchedCensus,
    nonModelCensus,
    nonModelHasOwnProgram,
    heavyUnpatchedCensus,
    heavyPatchedCensus,
  };
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

    def check(name, fn):
        try:
            fn()
            print('  ok   ' + name)
        except AssertionError as error:
            failures.append(name)
            print('  FAIL ' + name + ' ' + str(error)[:600])
            traceback.print_exc(limit=1)

    def test_brick_lights_and_shadows():
        assert not errors, f'console errors: {errors[:3]}'
        assert result['glErr'] == 0, f'GL error: {result["glErr"]}'
        assert result['aLum'] >= 5.0 * result['bLum'], f'box A should be >=5x brighter than shadowed box B: {result}'
        assert abs(result['aOffLum'] - result['refLum']) <= max(1e-4, 0.01 * result['refLum']), (
            f'tint 0 should match unpatched within 1%: {result}'
        )
        assert result['foldLum'] > result['aLum'] * 1.5, f'folded 2x scale + fill should brighten box: {result}'
        assert result['foldFillOnlyLum'] > result['refLum'] * 1.5, f'room fill adds indirect light: {result}'
        assert result['spotLitLum'] > result['spotAwayLum'] * 5.0, f'spot cone lights forward, not backward: {result}'
        assert result['zeroDistFinite'], 'zero distance to emitter must not produce NaN'

    def test_slot_5_and_rect_clamp():
        s5 = result['slot5Px']
        # Emitter 5 has red-only tint (1, 0, 0), slots 0..4 have visibility 0
        assert s5['r'] > result['refLum'] * 20.0, f'slot 5 (slab 1, odd slot) lights red channel strongly: {s5}'
        assert abs(s5['g'] - result['refLum']) <= max(1e-4, 0.02 * result['refLum']), (
            f'slot 5 red-only tint leaves green at ambient (no bleed from slots 0..4): {s5} vs ref {result["refLum"]}'
        )
        # Rect edge clamping: fragment directly in front of wide rect edge is much brighter than centre point
        assert result['rectEdgeLum'] > result['pointCenterLum'] * 2.0, (
            f'wide rect edge clamp ({result["rectEdgeLum"]}) must be >2x centre point ({result["pointCenterLum"]})'
        )

    def test_clone_safety():
        o = result['origProgInfo']
        cs = result['cloneSameProgInfo']
        ce = result['cloneExtraProgInfo']
        assert o['linked'] and cs['linked'] and ce['linked'], f'orig and clones link cleanly: {o} {cs} {ce}'
        assert o['mvDeclCount'] == 1 and cs['mvDeclCount'] == 1 and ce['mvDeclCount'] == 1, (
            f'exactly one mvBricks injection each: {o["mvDeclCount"]}, {cs["mvDeclCount"]}, {ce["mvDeclCount"]}'
        )
        assert o['cacheKey'] != ce['cacheKey'], (
            f'distinct hooks must produce distinct program keys: {o["cacheKey"]} vs {ce["cacheKey"]}'
        )
        tol = max(1e-4, 0.01 * result['origLitLum'])
        assert abs(result['cloneSameLum'] - result['origLitLum']) <= tol, 'cloneSame renders same lit luminance'
        assert abs(result['cloneExtraLum'] - result['origLitLum']) <= tol, 'cloneExtra renders same lit luminance'

    def test_no_brick_matches_unpatched():
        tol = max(1e-4, 0.01 * result['refLum'])
        assert abs(result['noAttrLum'] - result['refLum']) <= tol, f'missing mvBrick attr matches unpatched: {result}'
        assert abs(result['zeroAttrLum'] - result['refLum']) <= tol, f'mvBrick=0 matches unpatched: {result}'

    def test_one_program_for_counts_1_and_8():
        assert result['programsAfter1'] == result['programsAfter8'], f'no extra program for 8 emitters: {result}'
        assert result['sameProgramKey'], 'same program cache key for 1 and 8 emitters'
        assert result['keyOnce'].endswith('|mv-1') and result['keyOnce'] == result['keyTwice'], (
            f'idempotent cache key suffix |mv-1: {result["keyOnce"]} vs {result["keyTwice"]}'
        )
        assert result['eightLum'] > result['aLum'], '8-emitter brick sums all 8 emitters'

    def test_sampler_census():
        u = result['unpatchedCensus']
        p = result['patchedCensus']
        nm = result['nonModelCensus']
        hu = result['heavyUnpatchedCensus']
        hp = result['heavyPatchedCensus']
        assert p['linked'] and nm['linked'] and hp['linked'], f'programs linked: {p} {nm} {hp}'
        assert result['nonModelHasOwnProgram'], 'non-model mesh uses its own genuinely unpatched program in same scene'
        assert p['samplerCount'] == nm['samplerCount'] + 2, f'patched gains exactly 2 samplers over non-model: {nm} -> {p}'
        assert nm['samplerCount'] == u['samplerCount'], f'non-model gains 0 samplers: {u} vs {nm}'
        assert nm['mvDeclCount'] == 0, f'non-model program has zero mv injection: {nm}'
        names = {s['name'] for s in p['samplers']}
        assert 'mvBricks' in names and 'mvLamps' in names, f'mvBricks and mvLamps bound: {p["samplers"]}'
        assert hp['samplerCount'] == hu['samplerCount'] + 2, f'heavy PBR gains exactly 2 samplers: {hu} -> {hp}'
        assert hp['samplerCount'] <= 16, f'heavy PBR stays within 16 texture units: {hp}'

    for name, fn in (
        ('test_brick_lights_and_shadows', test_brick_lights_and_shadows),
        ('test_slot_5_and_rect_clamp', test_slot_5_and_rect_clamp),
        ('test_clone_safety', test_clone_safety),
        ('test_no_brick_matches_unpatched', test_no_brick_matches_unpatched),
        ('test_one_program_for_counts_1_and_8', test_one_program_for_counts_1_and_8),
        ('test_sampler_census', test_sampler_census),
    ):
        check(name, fn)
    print(f'{6 - len(failures)}/6 passed')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(run())

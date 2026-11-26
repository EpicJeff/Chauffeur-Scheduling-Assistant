"""Node CPU tests for light-visibility grid layout, inside-solid mask, and chunk codec.

Run from chauffeur/: python tests/test_twin_grid_layout_js.py
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from test_twin_ground_js import PREFIX, ROOT

DRIVER = PREFIX + r"""
import { gunzipSync } from 'node:zlib';
import { randomFillSync } from 'node:crypto';

const THREE = await import(three);
const { FT } = await import(file('static/twin/twin_light_math.js'));
const { groundAt } = await import(file('static/twin/twin_ground.js'));
const { buildOccluderBVH } = await import(file('static/twin/live/cone_occluder.js'));
const { gridLayout, gridPoints, pointsInRange, insideMask, maskGridIndices, GRID_MASK_SLICE_MS } = await import(file('static/twin/bake/grid_layout.js'));
const { encodeGridChunk, decodeGridChunk, MAX_CHUNK_BYTES } = await import(file('static/twin/bake/grid_chunk.js'));

const near = (a, b, eps = 1e-4, msg = '') =>
  assert.ok(Math.abs(a - b) <= eps, `${msg}: expected ${b}, got ${a}`);

function basePlan() {
  const rect = [[0, 0], [10, 0], [10, 12], [0, 12]];
  return {
    generatorVersion: 'test',
    materials: {},
    buildings: [{
      id: 'house',
      position: [0, 0],
      rotation: 0,
      base: 0,
      levels: [{ id: 'L1', elevation: 0, ceiling: 9, outline: rect }],
      walls: [],
      rooms: [{ id: 'living', level: 'L1', polygon: rect }],
      openings: [],
      roof: { sections: [] },
      items: [{ id: 'sofa', asset: 'sofa-1', at: [5, 5, 0], rotation: 0 }],
    }],
    site: {
      lot: [[-20, -20], [40, -20], [40, 40], [-20, 40]],
      terraces: [],
      furniture: [{ id: 'chair', asset: 'chair-1', at: [20, 20], rotation: 0 }],
    },
  };
}

// 1. test_room_grid_dims
{
  const plan = basePlan();
  const lamp = { source: { x: 5 * FT, y: 8 * FT, z: -6 * FT }, range: 15 * FT, outdoor: false };
  const layout = gridLayout(plan, [lamp]);
  assert.equal(layout.blocks.filter(b=>b.kind==='room').length, 1, 'one room block');
  const b = layout.blocks[0];
  assert.equal(b.kind, 'room');
  assert.equal(b.atlasRoom, 0);
  assert.equal(b.building, 'house');
  assert.equal(b.level, 'L1');
  assert.equal(b.first, 0);
  near(b.spacing, FT, 1e-6, 'indoor spacing is 1 ft');
  assert.deepEqual(b.dims, [10, 12, 9], '10 x 12 x 9 room dims');
  assert.equal(layout.count, 10 * 12 * 9 + 30 * 30 * 5);

  const pts = gridPoints(layout);
  assert.equal(pts.length, layout.count * 3);
  const v = new THREE.Vector3();
  const [nx, ny, nz] = b.dims;
  for (let iz = 0; iz < nz; iz++) {
    for (let iy = 0; iy < ny; iy++) {
      for (let ix = 0; ix < nx; ix++) {
        const idx = b.first + (iz * ny + iy) * nx + ix;
        const wx = pts[idx * 3], wy = pts[idx * 3 + 1], wz = pts[idx * 3 + 2];
        near(wx, (ix + 0.5) * FT, 1e-5, `x at (${ix},${iy},${iz})`);
        near(wy, (iz + 0.5) * FT, 1e-5, `y at (${ix},${iy},${iz})`);
        near(wz, -(iy + 0.5) * FT, 1e-5, `z at (${ix},${iy},${iz})`);
        v.set(wx, wy, wz).applyMatrix4(b.toLocal);
        near(v.x, ix + 0.5, 1e-4, 'toLocal x');
        near(v.y, iy + 0.5, 1e-4, 'toLocal y');
        near(v.z, iz + 0.5, 1e-4, 'toLocal z');
      }
    }
  }

  // Rotated & translated building with non-zero base
  const rotPlan = basePlan();
  rotPlan.buildings[0].position = [10, 4];
  rotPlan.buildings[0].rotation = 90;
  rotPlan.buildings[0].base = 2;
  // Local (5, 6, 8) rotated 90 deg CCW -> (-6, 5) + (10, 4) = (4, 9), height = 10
  const rotLamp = { source: { x: 4 * FT, y: 10 * FT, z: -9 * FT }, range: 15 * FT, outdoor: false };
  const rotLayout = gridLayout(rotPlan, [rotLamp]);
  assert.equal(rotLayout.blocks.filter(b=>b.kind==='room').length, 1);
  assert.deepEqual(rotLayout.blocks[0].dims, [10, 12, 9]);
  const rotPts = gridPoints(rotLayout);
  // Local (0.5, 0.5, 0.5) -> rotated (-0.5, 0.5) + (10, 4) = (9.5, 4.5), y = 2.5
  near(rotPts[0], 9.5 * FT, 1e-4, 'rotated x0');
  near(rotPts[1], 2.5 * FT, 1e-4, 'rotated y0');
  near(rotPts[2], -4.5 * FT, 1e-4, 'rotated z0');
  v.set(rotPts[0], rotPts[1], rotPts[2]).applyMatrix4(rotLayout.blocks[0].toLocal);
  near(v.x, 0.5, 1e-4, 'rotated toLocal x');
  near(v.y, 0.5, 1e-4, 'rotated toLocal y');
  near(v.z, 0.5, 1e-4, 'rotated toLocal z');
  console.log('Passed: test_room_grid_dims');
}

// 2. test_every_room_has_a_block
{
  const plan = basePlan();
  plan.buildings[0].rooms.push({
    id: 'far_room',
    level: 'L1',
    polygon: [[50, 0], [60, 0], [60, 10], [50, 10]],
  });
  const lamp = { source: { x: 5 * FT, y: 5 * FT, z: -6 * FT }, range: 15 * FT, outdoor: false };
  const layout = gridLayout(plan, [lamp]);
  assert.equal(layout.blocks.filter(b=>b.kind==='room').length, 2, 'every room gets a block');
  assert.equal(layout.blocks[0].atlasRoom, 0);

  const empty = gridLayout(plan, []);
  assert.equal(empty.blocks.length, 3, 'rooms and whole lot exist with no lamps');
  assert.equal(empty.hash, layout.hash);
  assert.equal(empty.count, layout.count);
  console.log('Passed: test_every_room_has_a_block');
}

// 3. test_yard_grid_follows_ground
{
  const plan = basePlan();
  plan.buildings = [];
  plan.site.lot = [[0, 0], [30, 0], [30, 30], [0, 30]];
  plan.site.terraces = [{
    id: 'slope_pad',
    polygon: [[14, 0], [30, 0], [30, 30], [14, 30]],
    height: -4,
    blend: 12,
    edges: [0, 1, 2, 3].map(() => ({ edge: 'slope' })),
  }];
  const yLamp = { source: { x: 12 * FT, y: 4 * FT, z: -15 * FT }, range: 12 * FT, outdoor: true };
  const layout = gridLayout(plan, [yLamp]);
  const yardBlocks = layout.blocks.filter(b => b.kind === 'yard');
  assert.equal(yardBlocks.length, 1, 'one whole-lot yard block');
  assert.deepEqual(yardBlocks[0].dims, [15,15,5]);
  assert.equal(gridLayout(plan, []).hash, layout.hash, 'yard does not depend on lamps');
  const yb = yardBlocks[0];
  near(yb.spacing, 2 * FT, 1e-6, 'yard spacing is 2 ft');
  const [nx, ny, nz] = yb.dims;
  assert.equal(nz, 5, 'yard has 5 vertical layers (1, 3, 5, 7, 9 ft)');
  assert.ok(yb.ground instanceof Float32Array, 'yard block has Float32Array ground');
  assert.equal(yb.ground.length, nx * ny);

  const pts = gridPoints(layout);
  let minG = Infinity, maxG = -Infinity;
  const expectedFt = [1, 3, 5, 7, 9];
  for (let iy = 0; iy < ny; iy++) {
    for (let ix = 0; ix < nx; ix++) {
      const gM = yb.ground[iy * nx + ix];
      if (gM < minG) minG = gM;
      if (gM > maxG) maxG = gM;
      for (let iz = 0; iz < nz; iz++) {
        const idx = yb.first + (iz * ny + iy) * nx + ix;
        const wx = pts[idx * 3], wy = pts[idx * 3 + 1], wz = pts[idx * 3 + 2];
        const lx = wx / FT, ly = -wz / FT;
        const groundFt = groundAt(plan, lx, ly);
        near(gM, groundFt * FT, 1e-4, 'ground array matches groundAt');
        near(wy / FT - groundFt, expectedFt[iz], 1e-4, `yard height above ground at iz=${iz}`);
      }
    }
  }
  assert.ok(maxG - minG > 1 * FT, `sloped lot actually slopes across yard grid (${minG}..${maxG})`);

  // Verify pointsInRange matches brute-force distance check
  const inRange = pointsInRange(layout, pts, yLamp.source, yLamp.range);
  assert.ok(inRange instanceof Uint32Array);
  const brute = [];
  for (let i = 0; i < layout.count; i++) {
    const dx = pts[i * 3] - yLamp.source.x;
    const dy = pts[i * 3 + 1] - yLamp.source.y;
    const dz = pts[i * 3 + 2] - yLamp.source.z;
    if (dx * dx + dy * dy + dz * dz < yLamp.range * yLamp.range) brute.push(i);
  }
  assert.deepEqual([...inRange], brute, 'pointsInRange matches brute force');
  console.log('Passed: test_yard_grid_follows_ground');
}

// 4. test_layout_hash_stable
{
  const planA = basePlan();
  const planB = structuredClone(planA);
  // Move placed building item and site furniture
  planB.buildings[0].items[0].at = [8, 9, 0];
  planB.site.furniture[0].at = [25, 10];
  const lamps = [
    { source: { x: 5 * FT, y: 8 * FT, z: -6 * FT }, range: 15 * FT, outdoor: false },
    { source: { x: 25 * FT, y: 6 * FT, z: -25 * FT }, range: 12 * FT, outdoor: true },
  ];
  const layoutA = gridLayout(planA, lamps);
  const layoutA2 = gridLayout(planA, [...lamps].reverse());
  const layoutB = gridLayout(planB, lamps);
  assert.equal(typeof layoutA.hash, 'string');
  assert.ok(layoutA.hash.length >= 16);
  assert.equal(layoutA.hash, layoutA2.hash, 'same input (even reordered lamps) gives same hash');
  assert.equal(layoutA.hash, layoutB.hash, 'moving placed items does not change layout hash');
  assert.equal(layoutA.hash, gridLayout(planA, []).hash, 'removing every lamp preserves layout');
  assert.equal(layoutA.hash, gridLayout(planA, [{source:{x:500,y:1,z:500},range:1,outdoor:true}]).hash, 'moving lamps and changing reach preserves layout');

  const planC = structuredClone(planA);
  planC.buildings[0].rooms[0].polygon = [[0, 0], [11, 0], [11, 12], [0, 12]];
  const layoutC = gridLayout(planC, lamps);
  assert.notEqual(layoutA.hash, layoutC.hash, 'changing room polygon changes layout hash');
  console.log('Passed: test_layout_hash_stable');
}

// 5. test_inside_mask
{
  // Room A: 10 x 12 x 9 ft with an L-shaped cutout, solid walls + a closed 1 m box inside.
  // Room B: 3 x 3 x 9 ft closet surrounded by solid walls, floor and ceiling.
  const lPoly = [[0, 0], [10, 0], [10, 6], [6, 6], [6, 12], [0, 12]];
  const closetPoly = [[12, 0], [15, 0], [15, 3], [12, 3]];
  const plan = {
    generatorVersion: 'test',
    materials: {},
    buildings: [{
      id: 'house',
      position: [0, 0],
      rotation: 0,
      base: 0,
      levels: [{ id: 'L1', elevation: 0, ceiling: 9 }],
      walls: [],
      rooms: [
        { id: 'main', level: 'L1', polygon: lPoly },
        { id: 'closet', level: 'L1', polygon: closetPoly },
      ],
    }],
    site: { lot: [[-5, -5], [25, -5], [25, 25], [-5, 25]] },
  };
  const lamps = [
    { source: { x: 3 * FT, y: 5 * FT, z: -3 * FT }, range: 20 * FT, outdoor: false },
    { source: { x: 13.5 * FT, y: 5 * FT, z: -1.5 * FT }, range: 10 * FT, outdoor: false },
  ];
  const layout = gridLayout(plan, lamps);
  assert.equal(layout.blocks.filter(b=>b.kind==='room').length, 2);
  const pts = gridPoints(layout);

  const meshes = [];
  const addBox = (cx, cy, cz, sx, sy, sz) => {
    const m = new THREE.Mesh(new THREE.BoxGeometry(sx, sy, sz), new THREE.MeshStandardMaterial());
    m.position.set(cx, cy, cz);
    m.updateMatrixWorld(true);
    meshes.push(m);
  };
  // Closed 1 m x 1 m x 1 m solid box centered at world (2.5*FT, 2.5*FT, -2.5*FT)
  // Grid point (2, 2, 2) is at exact centre (2.5*FT, 2.5*FT, -2.5*FT) -> MUST be 1
  addBox(2.5 * FT, 2.5 * FT, -2.5 * FT, 1.0, 1.0, 1.0);

  // Build thick solid enclosure around the 3 x 3 ft closet: x in [12, 15] ft, y in [0, 3] ft, z in [0, 9] ft
  const t = 0.5 * FT;
  const cx = 13.5 * FT, cy = 4.5 * FT, cz = -1.5 * FT;
  addBox(12 * FT - t / 2, cy, cz, t, 9 * FT, 3 * FT + 2 * t); // west wall
  addBox(15 * FT + t / 2, cy, cz, t, 9 * FT, 3 * FT + 2 * t); // east wall
  addBox(cx, cy, 0 * FT + t / 2, 3 * FT, 9 * FT, t);           // south wall (plan y=0 -> z=0)
  addBox(cx, cy, -3 * FT - t / 2, 3 * FT, 9 * FT, t);          // north wall (plan y=3 -> z=-3)
  addBox(cx, -t / 2, cz, 3 * FT + 2 * t, t, 3 * FT + 2 * t);   // floor slab
  addBox(cx, 9 * FT + t / 2, cz, 3 * FT + 2 * t, t, 3 * FT + 2 * t); // ceiling slab

  const bvh = buildOccluderBVH(meshes, null, {facing:true});
  const mask = insideMask(pts, bvh, layout);
  assert.ok(mask instanceof Uint8Array);
  assert.equal(mask.length, layout.count);

  const mainBlock = layout.blocks[0];
  const closetBlock = layout.blocks[1];
  const idxOf = (blk, ix, iy, iz) => blk.first + (iz * blk.dims[1] + iy) * blk.dims[0] + ix;

  // The 1 m cube centre has no back hit within .5 m after tilt: valid, but fully occluded.
  assert.equal(mask[idxOf(mainBlock, 2, 2, 2)], 0, '1 m cube centre is valid under the near-hit rule');
  for (const dir of [[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,1],[0,0,-1]]) {
    const source = new THREE.Vector3(...dir).multiplyScalar(2).add(new THREE.Vector3(2.5*FT,2.5*FT,-2.5*FT));
    const centre = new THREE.Vector3().fromArray(pts,idxOf(mainBlock,2,2,2)*3), toLamp=source.sub(centre), distance=toLamp.length();toLamp.normalize();
    const visibility=bvh.castRay(centre.x,centre.y,centre.z,toLamp.x,toLamp.y,toLamp.z,1e-4,distance)<distance?0:254;
    assert.equal(visibility,0,'cube body blocks every exterior lamp direction');
  }
  // Open room air (e.g., ix=8, iy=2, iz=4 -> x=8.5 ft, y=2.5 ft, z=4.5 ft) -> valid (0)
  assert.equal(mask[idxOf(mainBlock, 8, 2, 4)], 0, 'point in open room air is 0');
  // Outside the L polygon (e.g., ix=8, iy=9, iz=4 -> x=8.5 ft, y=9.5 ft is in the cutout) -> invalid (1)
  assert.equal(mask[idxOf(mainBlock, 8, 9, 4)], 1, 'point outside L room polygon is 1');
  // Inside the 3 x 3 ft closet with walls -> ALL interior points must be 0
  for (let iz = 0; iz < closetBlock.dims[2]; iz++) {
    for (let iy = 0; iy < closetBlock.dims[1]; iy++) {
      for (let ix = 0; ix < closetBlock.dims[0]; ix++) {
        assert.equal(mask[idxOf(closetBlock, ix, iy, iz)], 0,
          `closet point (${ix},${iy},${iz}) inside 3x3 ft walled closet is 0`);
      }
    }
  }
  const subset = new Uint32Array([idxOf(mainBlock,2,2,2), idxOf(mainBlock,8,2,4), idxOf(mainBlock,8,9,4), idxOf(closetBlock,1,1,4)]);
  assert.deepEqual([...insideMask(pts,bvh,layout,subset)], [...subset].map(i=>mask[i]), 'subset matches full facing and polygon mask');
  const cache = new Uint8Array(layout.count);
  let casts = 0, yields = 0;
  const counted = {triCount:bvh.triCount,castRayFacing(...args){casts++;return bvh.castRayFacing(...args);}};
  const measured = await maskGridIndices(pts,counted,layout,subset,cache,async()=>{yields++;});
  assert.ok(yields>0); assert.ok(measured.maskMs>0); assert.equal(measured.maskPoints,subset.length);
  for(const i of subset) assert.equal(cache[i],mask[i]+1);
  assert.equal(cache.filter(v=>v!==0).length,subset.length,'unrelated points remain unknown');
  const before = casts;
  assert.equal((await maskGridIndices(pts,counted,layout,subset,cache,async()=>{throw Error('cached points must not yield');})).maskPoints,0);
  assert.equal(casts,before,'overlapping lights reuse facing results');
  const all = Uint32Array.from({length:layout.count},(_,i)=>i), cancelledCache = new Uint8Array(layout.count);
  let slices=0, beforeCancel=0;
  await assert.rejects(maskGridIndices(pts,bvh,layout,all,cancelledCache,async()=>{if(++slices===2){beforeCancel=cancelledCache.filter(v=>v!==0).length;throw Error('cancelled');}}),/cancelled/);
  assert.ok(beforeCancel>0&&beforeCancel<all.length,'first time-budgeted slice classifies only part of the mask');
  assert.equal(cancelledCache.filter(v=>v!==0).length,beforeCancel,'cancellation stops before any second-slice work');
  console.log('Passed: test_inside_mask');
}


// Nearest facing is opt-in; ordinary cone distances stay identical. Material
// groups, BackSide and mirrored transforms all retain rendered facing.
{
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(2,2,2), new THREE.MeshStandardMaterial());
  mesh.updateMatrixWorld(true);
  const old = buildOccluderBVH([mesh]), signed = buildOccluderBVH([mesh], null, {facing:true});
  assert.equal(old.castRayFacing, undefined);
  for (let n=0;n<100;n++) {
    const origin = new THREE.Vector3(Math.sin(n)*3, Math.cos(n*.7)*3, Math.sin(n*.3)*3);
    const dir = origin.clone().negate().normalize();
    const args=[...origin.toArray(),...dir.toArray(),1e-4,100];
    assert.equal(old.castRay(...args),signed.castRay(...args));
    assert.equal(Math.abs(signed.castRayFacing(...args)),old.castRay(...args));
  }
  assert.ok(signed.castRayFacing(0,0,0,1,0,0,1e-4,100)<0);
  for(const side of [THREE.FrontSide,THREE.BackSide,THREE.DoubleSide]) {
    mesh.material.side=side;mesh.scale.x=-1;mesh.updateMatrixWorld(true);
    const b=buildOccluderBVH([mesh],null,{facing:true});
    assert.equal(b.castRayFacing(0,0,0,1,0,0,1e-4,100)<0,side!==THREE.BackSide);
  }
  mesh.scale.x=1;mesh.material=Array.from({length:6},()=>new THREE.MeshStandardMaterial({side:THREE.BackSide}));mesh.updateMatrixWorld(true);
  assert.ok(buildOccluderBVH([mesh],null,{facing:true}).castRayFacing(0,0,0,1,0,0,1e-4,100)>0);

  let determinants=0;const determinant=mesh.matrixWorld.determinant.bind(mesh.matrixWorld);
  mesh.matrixWorld.determinant=()=>{determinants++;return determinant();};
  buildOccluderBVH([mesh],null,{facing:true});assert.equal(determinants,1,'one determinant per mesh');
  const empty=buildOccluderBVH([],null,{facing:true});assert.equal(empty.castRayFacing(0,0,0,1,0,0,1e-4,10),10);
  // Wall body, floor slab, and column: thin geometry still has >=3 back hits.
  const layout=gridLayout({buildings:[{id:'b',levels:[{id:'l',ceiling:10}],rooms:[{id:'r',level:'l',polygon:[[0,0],[10,0],[10,10],[0,10]]}]}]});
  const p=new THREE.Vector3(.5*FT,.5*FT,-.5*FT);
  for(const size of [[.1,5,5],[.15,5,5],[5,.15,5],[5,5,.15],[.4,5,.4],[.8,.8,.8]]) {
    const m=new THREE.Mesh(new THREE.BoxGeometry(...size),new THREE.MeshStandardMaterial());m.position.copy(p);m.updateMatrixWorld(true);
    const b=buildOccluderBVH([m],null,{facing:true});
    assert.equal(insideMask(new Float32Array(p.toArray()),b,layout,new Uint32Array([0]))[0],1);
  }
  for(const side of [THREE.FrontSide,THREE.BackSide]) {
    const floor=new THREE.Mesh(new THREE.PlaneGeometry(20,20).rotateX(-Math.PI/2),new THREE.MeshStandardMaterial({side}));
    floor.position.y=2;floor.updateMatrixWorld(true);
    const b=buildOccluderBVH([floor],null,{facing:true});
    assert.equal(insideMask(new Float32Array(p.toArray()),b,layout,new Uint32Array([0]))[0],0,'open single plane cannot invalidate air');
    assert.deepEqual(insideMask(gridPoints(layout),b,layout),insideMask(gridPoints(layout),b,layout),'deterministic');
  }
  console.log('Passed: test_nearest_facing_and_legacy_occlusion');
}

// Geometry-only memory and desktop facing measurements (no GPU claims).
{
  const household = JSON.parse(readFileSync(new URL(file('tests/fixtures/twin_model/household-2026-11-09.json')), 'utf8'));
  const lot200 = {buildings:[],site:{lot:[[0,0],[200,0],[200,200],[0,200]]}};
  for(const [name,plan] of [['household',household],['lot200',lot200]]) {
    const layout=gridLayout(plan), points=gridPoints(layout);
    const groundBytes=layout.blocks.reduce((n,b)=>n+(b.ground?.byteLength||0),0);
    console.log(`       ${name}: ${layout.count} points, xyz Float32 ${points.byteLength} bytes, ground Float32 ${groundBytes} bytes`);
    if(name==='lot200'){assert.equal(layout.count,50000);assert.equal(points.byteLength,600000);continue;}
    const {buildTwin}=await import(file('static/twin/twin_generator.js'));
    const {collectStaticOccluders}=await import(file('static/twin/live/cone_occluder.js'));
    const {atlasMesh}=await import(file('static/twin/bake/atlas.js'));
    const out=buildTwin(plan,kit,'high');await out.ready;out.root.updateMatrixWorld(true);
    const bvh=buildOccluderBVH(collectStaticOccluders(out.root).filter(o=>atlasMesh(o)&&o.material.name!=='glass'&&!o.geometry?.userData.bakeHeightfield), null, {facing:true});
    const cache=new Uint8Array(layout.count);
    const blocks=layout.blocks.filter(b=>b.kind==='room').sort((a,b)=>b.dims.reduce((x,y)=>x*y,1)-a.dims.reduce((x,y)=>x*y,1)).slice(0,3);
    // Exercise the real unclamped fallback, never setImmediate disguised as a scheduler.
    const scheduler=globalThis.scheduler, NativeChannel=globalThis.MessageChannel;
    let channels=0, posts=0, closes=0;
    delete globalThis.scheduler;
    globalThis.MessageChannel=class extends NativeChannel {
      constructor(){super();channels++;
        const post=this.port2.postMessage.bind(this.port2);
        this.port2.postMessage=(...args)=>{posts++;return post(...args);};
        for(const port of [this.port1,this.port2]){
          const close=port.close.bind(port);port.close=()=>{closes++;return close();};
        }
      }
    };
    try {
      for(const [n,b] of blocks.entries()) {
        const centre=b.first+Math.floor(b.dims.reduce((x,y)=>x*y,1)/2), source=new THREE.Vector3().fromArray(points,centre*3);
        const indices=pointsInRange(layout,points,source,6);
        const beforePosts=posts, beforeChannels=channels, beforeCloses=closes;
        let checkpoints=0;
        const wallStart=performance.now();
        const m=await maskGridIndices(points,bvh,layout,indices,cache,async()=>{checkpoints++;});
        const wallMs=performance.now()-wallStart, yields=posts-beforePosts;
        assert.equal(globalThis.scheduler,undefined,'scheduler absent during household measurement');
        assert.equal(channels-beforeChannels,1,'one real MessageChannel reused for the light');
        assert.equal(closes-beforeCloses,2,'both channel ports close after masking');
        assert.equal(yields,m.maskYields,'every yield posts through MessageChannel');
        assert.equal(checkpoints,m.maskSlices,'one checkpoint per slice');
        assert.ok(yields>0&&yields<m.maskPoints/4,'task round trips are a small fraction of unknown points');
        if(n===0) assert.equal(indices.length,26416,'same household light as round 1');
        console.log(`       household mask ${n}: ${bvh.triCount} triangles, ${indices.length} in range, ${m.maskPoints} newly masked, budget=${GRID_MASK_SLICE_MS} ms, CPU ${m.maskMs.toFixed(2)} ms, longest ${m.maskMaxMs.toFixed(2)} ms, wall ${wallMs.toFixed(2)} ms, MessageChannel yields ${yields} (${(100*yields/m.maskPoints).toFixed(2)}%), checkpoints ${checkpoints}`);
      }
      // Cheap polygon rejects are batched too, rather than scheduling one task each.
      const rejectLayout=gridLayout({buildings:[],site:{lot:[[0,0],[200,0],[0,200]]}});
      const rejects=Uint32Array.from({length:rejectLayout.count},(_,i)=>i);
      const beforePosts=posts;
      const cheap=await maskGridIndices(gridPoints(rejectLayout),null,rejectLayout,rejects,new Uint8Array(rejectLayout.count),async()=>{});
      assert.ok(posts-beforePosts<rejectLayout.count/100,'cheap polygon checks do not yield per point');
      assert.equal(closes,channels*2,'no live channel ports remain');
      console.log(`       cheap polygon mask: ${cheap.maskPoints} points, MessageChannel yields ${posts-beforePosts}`);
    } finally {
      globalThis.MessageChannel=NativeChannel;
      if(scheduler===undefined)delete globalThis.scheduler;else globalThis.scheduler=scheduler;
    }
  }
  console.log('Passed: test_layout_memory_and_mask_slices');
}


// The normalized household and its yard reproduce the 922/4620 Kitchen
// parity failure. Every in-polygon Kitchen cell is open air in this fixture.
{
 const job=JSON.parse(readFileSync(process.argv[2]));
 const {buildTwin}=await import(file('static/twin/twin_generator.js'));
 const {buildYard}=await import(file('static/twin/twin_yard.js'));
 const {buildAtlas,atlasMesh}=await import(file('static/twin/bake/atlas.js'));
 const {collectStaticOccluders}=await import(file('static/twin/live/cone_occluder.js'));
 const {cellInBlock}=await import(file('static/twin/bake/grid_layout.js'));
 const plan=job.householdPlan,out=buildTwin(plan,job.householdKit,'high');await out.ready;
 const yard=await buildYard(plan,{materials:{}},'high',{viewing:true});(out.groups.site||out.root).add(yard.group);await yard.ready;out.root.updateMatrixWorld(true);
 const atlas=buildAtlas(out.root,plan,{room:{density:1,page:256,gutter:2}}),root=atlas.sourceRoot||out.root;root.updateMatrixWorld(true);
 const meshes=collectStaticOccluders(root,{plan,groups:out.groups}).filter(o=>atlasMesh(o)&&o.material.name!=='glass'&&!o.geometry?.userData.bakeHeightfield);
 const bvh=buildOccluderBVH(meshes,null,{facing:true}),layout=gridLayout(plan),points=gridPoints(layout),mask=insideMask(points,bvh,layout);
 const b=layout.blocks.find(b=>b.id==='pool-house:room:5d7de10ca48340ae85c407d22337c6f7');let checked=0;
 for(let cell=0;cell<b.dims.reduce((a,v)=>a*v,1);cell++)if(cellInBlock(layout,b,cell)){assert.equal(mask[b.first+cell],0,'Kitchen air remains valid');checked++;}
 assert.equal(checked,4620);assert.deepEqual(insideMask(points,bvh,layout),mask,'household deterministic');

 const attic=layout.blocks.find(b=>b.id==='main-house:room:16d975d5056e4f74810ed1e0cdaf716f');
 const tri=new THREE.Triangle(),closest=new THREE.Vector3(),point=new THREE.Vector3();
 const soups=meshes.map(m=>{
  const g=m.geometry,p=g.attributes.position,idx=g.index,xyz=new Float32Array((idx?idx.count:p.count)*3);
  const v=new THREE.Vector3();for(let i=0;i<xyz.length/3;i++){v.fromBufferAttribute(p,idx?idx.getX(i):i).applyMatrix4(m.matrixWorld);xyz.set(v.toArray(),i*3);}
  return {xyz,box:new THREE.Box3().setFromObject(m)};
 });
 function nearSurface(point){
  for(const {xyz,box} of soups){if(box.distanceToPoint(point)>.1)continue;
   for(let i=0;i+8<xyz.length;i+=9){tri.a.fromArray(xyz,i);tri.b.fromArray(xyz,i+3);tri.c.fromArray(xyz,i+6);tri.closestPointToPoint(point,closest);if(closest.distanceTo(point)<=.1)return true;}
  }return false;
 }
 let invalid=0,openInvalid=0,openDead=0;
 const [nx,ny,nz]=attic.dims;
 for(let cell=0;cell<nx*ny*nz;cell++)if(cellInBlock(layout,attic,cell)&&mask[attic.first+cell]){
  invalid++;point.fromArray(points,(attic.first+cell)*3);if(!nearSurface(point))openInvalid++;
 }
 for(let z=0;z<nz-1;z++)for(let y=0;y<ny-1;y++)for(let x=0;x<nx-1;x++){
  const cells=[];for(let dz=0;dz<2;dz++)for(let dy=0;dy<2;dy++)for(let dx=0;dx<2;dx++)cells.push(((z+dz)*ny+y+dy)*nx+x+dx);
  if(!cells.every(c=>cellInBlock(layout,attic,c)&&mask[attic.first+c]))continue;
  point.set(0,0,0);for(const c of cells)point.add(new THREE.Vector3().fromArray(points,(attic.first+c)*3));point.multiplyScalar(1/8);
  if(!nearSurface(point))openDead++;
 }
 assert.equal(invalid,52);assert.equal(openInvalid,0,'attic has no invalid air >10 cm from any triangle');
 assert.equal(openDead,0,'attic has no fully invalid open-air trilinear stencil');
 console.log('Passed: test_household_attic_no_open_invalid_points_or_stencils');
 console.log('Passed: test_household_kitchen_open_air_zero_invalid');
}

// 6. test_chunk_roundtrip
{
  const original = {
    layoutHash: 'a1b2c3d4e5f60718293a4b5c6d7e8f90',
    device: 'light.living_cans',
    emitters: 3,
    indices: new Uint32Array([0, 5, 42, 1024, 65537]),
    values: new Uint8Array([
      254, 128, 0,
      255, 255, 255,
      10, 200, 127,
      0, 0, 254,
      1, 2, 253,
    ]),
  };
  const encoded = await encodeGridChunk(original);
  assert.ok(encoded instanceof Uint8Array, 'encoded is Uint8Array');
  assert.equal(encoded[0], 0x1f, 'gzip magic byte 0');
  assert.equal(encoded[1], 0x8b, 'gzip magic byte 1');
  const raw = gunzipSync(encoded);
  assert.equal(Buffer.from(raw.subarray(0, 4)).toString('ascii'), 'MVG1', 'MVG1 magic inside gzip');

  const decoded = await decodeGridChunk(encoded);
  assert.equal(decoded.layoutHash, original.layoutHash);
  assert.equal(decoded.device, original.device);
  assert.equal(decoded.emitters, original.emitters);
  assert.ok(decoded.indices instanceof Uint32Array);
  assert.ok(decoded.values instanceof Uint8Array);
  assert.deepEqual([...decoded.indices], [...original.indices]);
  assert.deepEqual([...decoded.values], [...original.values]);

  // Empty chunk roundtrip
  const emptyOrig = {
    layoutHash: '0'.repeat(32),
    device: 'light.empty',
    emitters: 1,
    indices: new Uint32Array(0),
    values: new Uint8Array(0),
  };
  const emptyDec = await decodeGridChunk(await encodeGridChunk(emptyOrig));
  assert.equal(emptyDec.indices.length, 0);
  assert.equal(emptyDec.values.length, 0);
  assert.equal(emptyDec.device, 'light.empty');

  // Corrupt magic rejects
  await assert.rejects(() => decodeGridChunk(new Uint8Array([0, 1, 2, 3, 4, 5, 6, 7])), /Invalid|MVG1|chunk/i);

  // Over-cap (8 MiB) compressed upload rejects on encode and decode
  assert.equal(MAX_CHUNK_BYTES, 8 * 1024 * 1024, 'MAX_CHUNK_BYTES is 8 MiB');
  const overCount = 1_100_000;
  const overIndices = new Uint32Array(overCount);
  for (let i = 0; i < overCount; i++) overIndices[i] = i;
  const overValues = randomFillSync(new Uint8Array(overCount * 8)); // ~8.8 MB incompressible -> > 8 MiB gzipped
  await assert.rejects(
    () => encodeGridChunk({
      layoutHash: original.layoutHash,
      device: 'light.over_cap',
      emitters: 8,
      indices: overIndices,
      values: overValues,
    }),
    /size limit/i,
    'encodeGridChunk rejects compressed chunk over 8 MiB',
  );
  await assert.rejects(
    () => decodeGridChunk(new Uint8Array(MAX_CHUNK_BYTES + 1)),
    /size limit/i,
    'decodeGridChunk rejects input over 8 MiB',
  );
  console.log('Passed: test_chunk_roundtrip');
}
"""


def run():
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    import test_twin_baker_js as B
    B.household_pool_house()
    household_plan = B.twin_store.current()
    household_kit = {**B.tl.kit('modern_farmhouse'), 'manifest': {}}
    with tempfile.TemporaryDirectory(prefix='chauffeur_grid_layout_') as directory:
        driver, data = Path(directory) / 'driver.mjs', Path(directory) / 'input.json'
        driver.write_text(DRIVER, encoding='utf-8')
        data.write_text(json.dumps({'root': ROOT.as_posix(), 'flat': {}, 'kit': kit, 'householdPlan': household_plan, 'householdKit': household_kit}), encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(driver), str(data)], capture_output=True,
                                text=True, timeout=120)
        print(result.stdout, end='')
        if result.returncode:
            raise AssertionError(result.stderr)


if __name__ == '__main__':
    run()

import * as THREE from 'three';
import { groundAt, buildingFootprint } from './twin_ground.js';
import { allPorches } from './twin_generator.js';
import { pathSurfacePolygons } from './path_shapes.js';
import { firePitOutline } from './fire_pits.js';
import { TIERS } from './twin_tiers.js';
import { manifest } from './twin_library.js';
import { doorwaySteps } from './twin_stairs.js';
import { buildPadEdge } from './pad_edge_geometry.js';
import { retainingWallGeometry } from './twin_retaining_wall.js';

// Project the actual pad-edge solids rather than guessing a stair run from the
// pad height. The builder accounts for lower layered ground and tread noses.
function footprint(points) {
  points.sort((a,b)=>a[0]-b[0] || a[1]-b[1]);
  const cross=(a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
  const half=list=>{const h=[];for(const p of list){while(h.length>1&&cross(h.at(-2),h.at(-1),p)<=0)h.pop();h.push(p);}return h.slice(0,-1);};
  return [...half(points),...half([...points].reverse())];
}

// Materials have stable identities, but the household manifest has no vegetation
// taxonomy. Fail closed for unknown/user materials, including gravel and mulch.
// A plain lawn role (including a tint-only override) remains grass.
export function grassLawn(kit) {
  const ref = kit.materials?.lawn || {}, id = ref.id || ref.asset;
  return !id || ['lawn', 'grass', 'leafy_grass'].includes(id)
    || manifest(kit)[id]?.source_id === 'leafy_grass';
}

export function grassCovers(plan, outline = p => p) {
  const site = plan.site || {}, covers = [];
  const add = (polygon, margin = .4) => { if (polygon?.length >= 3) covers.push({polygon, margin}); };
  for (const b of plan.buildings || []) {
    const a = (b.rotation || 0) * Math.PI / 180, c = Math.cos(a), s = Math.sin(a), pos = b.position || [0, 0];
    const world = poly => poly?.map(([x, y]) => [pos[0] + x*c - y*s, pos[1] + x*s + y*c]);
    add(world(outline(buildingFootprint(b))));
    for (const p of allPorches(b)) add(world(outline(p.polygon)));
    for (const r of b.rooms || []) if (r.kind === 'porch') add(world(outline(r.polygon)));
    for (const s of b.stairs || []) {
      const dx=s.to[0]-s.from[0], dy=s.to[1]-s.from[1], length=Math.hypot(dx,dy);
      if (!length) continue;
      const x=-dy/length*s.width/2, y=dx/length*s.width/2;
      add(world([s.from.map((v,i)=>v+[x,y][i]),s.to.map((v,i)=>v+[x,y][i]),
        s.to.map((v,i)=>v-[x,y][i]),s.from.map((v,i)=>v-[x,y][i])]));
    }
    for (const opening of b.openings || []) for (const step of doorwaySteps(b,opening)) add(world(step.polygon));
  }
  // Pads are deliberately clear, including ones that currently use a lawn look:
  // they are independently authored ground surfaces, not the lot's lawn.
  for (const p of [...(site.terraces || []), ...(site.beds || [])]) add(p.polygon);
  for (const pad of site.terraces || []) for (let i=0;i<pad.polygon.length;i++) {
    if (pad.edges?.[i]?.edge !== 'sharp') continue;
    const points=[];
    const project=(g,part)=>{
      if (part !== 'rail') {const a=g.attributes.position;for(let j=0;j<a.count;j++)points.push([a.getX(j),-a.getZ(j)]);}
      g.dispose();
    };
    if (pad.edges[i].wall) project(retainingWallGeometry(plan,pad,i),'wall');
    buildPadEdge(plan,pad,i,project);
    if (points.length) add(footprint(points));
  }
  for (const h of site.hardscape || []) {
    if (h.kind === 'path') for (const p of pathSurfacePolygons(h)) add(p, h.edging === 'curb' ? .9 : .4);
    else add(h.polygon);
  }
  const pool = site.pool;
  add(pool?.polygon, Math.max(0, pool?.coping ?? 1) + .4);
  for (const f of pool?.features || []) if (f.kind === 'spa') add(f.polygon, Math.max(0, pool.coping ?? 1) + .4);
  const pits = Array.isArray(site.fire_pit) ? site.fire_pit : site.fire_pit ? [site.fire_pit] : [];
  for (const f of pits) add(firePitOutline(f));
  // An edge polygon draws only a narrow closed strip, never its entire interior.
  for (const e of site.edges || []) if (e.polygon?.length >= 3)
    for (const p of pathSurfacePolygons({points:[...e.polygon, e.polygon[0]], width:.5})) add(p);
  return covers;
}

// Scalar prepared polygons avoid allocating vectors/edge arrays per candidate.
function prepared(polygon, margin) {
  const xs = polygon.map(p => p[0]), ys = polygon.map(p => p[1]);
  const rectangle = polygon.length === 4 && polygon.every((p,i) => {
    const q=polygon[(i+1)%4];return p[0]===q[0] || p[1]===q[1];
  });
  return {polygon, margin, rectangle, x0:Math.min(...xs)-margin, x1:Math.max(...xs)+margin,
    y0:Math.min(...ys)-margin, y1:Math.max(...ys)+margin};
}
function contains(p, x, y, border = true) {
  if (x < p.x0 || x > p.x1 || y < p.y0 || y > p.y1) return false;
  if (p.rectangle && border) return true;
  let inside = false;
  for (let i = 0, j = p.polygon.length-1; i < p.polygon.length; j = i++) {
    const a = p.polygon[j], b = p.polygon[i], dx = b[0]-a[0], dy = b[1]-a[1];
    if (border && p.margin) {
      const t = Math.max(0, Math.min(1, ((x-a[0])*dx+(y-a[1])*dy)/(dx*dx+dy*dy || 1)));
      if ((x-a[0]-t*dx)**2+(y-a[1]-t*dy)**2 < p.margin*p.margin) return true;
    }
    if ((a[1]>y)!==(b[1]>y) && x < dx*(y-a[1])/dy+a[0]) inside = !inside;
  }
  return inside;
}
const hash = n => { n = Math.imul(n ^ n >>> 16, 0x21f0aaad); n = Math.imul(n ^ n >>> 15, 0x735a2d97); return ((n ^ n >>> 15) >>> 0) / 4294967296; };

// The clump is modelled for this grid spacing (plan feet); a coarser tier's grid
// spreads and widens its clumps to match, so the cover stays even.
const BLADES = 5, CLUMP_SPACING = .28;
function bladeGeometry() {
  const positions = [], normals = [], shape = [], indices = [];
  // Five bent, two-segment blades per clump, 25 vertices / 15 triangles. The
  // blades stand spread over the clump's whole grid cell and lean different ways,
  // so the field reads as an even lawn rather than as rows of separate tufts.
  for (let b = 0; b < BLADES; b++) {
    const a = b * 2.39996, c = Math.cos(a), s = Math.sin(a), start = positions.length/3;
    const reach = .13*Math.sqrt((b+.5)/BLADES), ox = Math.cos(a+1.1)*reach, oz = Math.sin(a+1.1)*reach;
    for (const [t, width] of [[0,.02],[.55,.016],[1,0]]) {
      const lean = .1*t*t;
      for (let side = 0; side < (width ? 2 : 1); side++) {
        const x = side ? width : -width;
        positions.push(ox+c*x+s*lean, t*(.29+b*.0175), oz-s*x+c*lean);
        // Up-biased normals suppress the alternating bright/dark card faces.
        const n = new THREE.Vector3(s*.32, .95, c*.32).normalize(); normals.push(...n.toArray());
        shape.push(t, b/BLADES);
      }
    }
    indices.push(start,start+1,start+2, start+1,start+3,start+2, start+2,start+3,start+4);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(positions,3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(normals,3));
  g.setAttribute('grassShape', new THREE.Float32BufferAttribute(shape,2));
  g.setIndex(indices); g.userData.bakeExcluded = true;
  return g;
}

export function grassReplace(shader, stage, anchor, replacement) {
  if (!shader[stage].includes(anchor)) throw new Error('Grass shader missing anchor: ' + anchor);
  shader[stage] = shader[stage].replace(anchor, replacement);
}
const VARYING = 'varying vec4 vGrass; varying vec3 vGrassUv;\n';
export function grassMaterial(source) {
  const material = new THREE.MeshStandardMaterial({name:'yard blades', side:THREE.DoubleSide, roughness:.9});
  const uniforms = {grassTime:{value:0}, grassTint:{value:source.color}, grassMap:{value:null},
    grassHasMap:{value:0}, grassUvMatrix:{value:new THREE.Matrix3()}};
  const sync = () => {
    uniforms.grassMap.value = source.map; uniforms.grassHasMap.value = source.map ? 1 : 0;
    if (source.map) { source.map.updateMatrix(); uniforms.grassUvMatrix.value.copy(source.map.matrix); }
  };
  sync(); source.addEventListener('materialparamschange', sync);
  // Kit textures resolve asynchronously without materialparamschange.
  let disposed = false;
  Promise.resolve(source.userData.ready).then(() => { if (!disposed) sync(); });
  material.addEventListener('dispose', () => { disposed = true; source.removeEventListener('materialparamschange', sync); });
  const compile = (shader, unlit = false) => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = VARYING + 'attribute vec2 grassShape; uniform float grassTime; uniform mat3 grassUvMatrix;\n' + shader.vertexShader;
    grassReplace(shader, 'vertexShader', '#include <begin_vertex>', `#include <begin_vertex>
vec3 grassRoot = instanceMatrix[3].xyz;
vec3 grassWorld = (modelMatrix * vec4(grassRoot, 1.0)).xyz;
float grassDistance = distance(cameraPosition, grassWorld);
float grassSeed = fract(sin(dot(grassRoot.xz, vec2(12.9898,78.233))) * 43758.5453);
// The whole house is usually on screen from 30 m or more, so the field stays
// complete that far; beyond it clumps thin out, grow to hold the cover, and
// their colour settles onto the lawn's own so sub-pixel blades do not sparkle.
float grassKeep = mix(1.0, .2, smoothstep(30.0, 120.0, grassDistance));
float grassScale = smoothstep(grassSeed-.045, grassSeed+.045, grassKeep);
transformed.xz *= 1.0 + 1.2*smoothstep(25.0, 110.0, grassDistance);
// A fixed seed threshold shrinks each clump over its own distance interval.
transformed *= grassScale;
float gust = sin(grassRoot.x*.11 + grassRoot.z*.07 + grassTime*.8)
  + .4*sin(grassRoot.z*.23 - grassRoot.x*.09 - grassTime*.57);
// Convert the world-directed wind into the instance's local yaw frame.
vec2 wind = vec2(.043, .027) * gust * grassShape.x*grassShape.x * grassScale;
transformed.xz += vec2(dot(instanceMatrix[0].xz, wind), dot(instanceMatrix[2].xz, wind)) / dot(instanceMatrix[0].xz, instanceMatrix[0].xz);
vGrass = vec4(grassShape, grassSeed, .5+.5*sin(grassRoot.x*.037+sin(grassRoot.z*.041)*2.0));
vGrassUv = vec3((grassUvMatrix * vec3(grassRoot.x, grassRoot.z, 1.0)).xy, .8*smoothstep(35.0, 110.0, grassDistance));`);
    shader.fragmentShader = VARYING + 'uniform vec3 grassTint; uniform sampler2D grassMap; uniform float grassHasMap;\n' + shader.fragmentShader;
    grassReplace(shader, 'fragmentShader', '#include <color_fragment>', `#include <color_fragment>
vec3 lawn = grassTint;
if (grassHasMap > .5) lawn *= texture2D(grassMap, vGrassUv.xy).rgb;
// "patch" is a reserved word in GLSL ES 3.
vec3 lawnPatch = mix(vec3(.90,1.0,.84), vec3(1.10,1.02,.82), vGrass.w);
vec3 lawnBlade = mix(vec3(.88,1.0,.90), vec3(1.12,1.04,.80), fract(vGrass.z*7.0+vGrass.y*3.3));
// Shaded at the root, lit and a little yellow at the tip: the tips sit above the
// lawn colour under them, which is what gives the field its depth.
vec3 lawnTip = mix(vec3(.55), vec3(1.42,1.36,1.0), vGrass.x);
diffuseColor.rgb *= lawn * mix(lawnPatch * lawnBlade * lawnTip, vec3(1.0), vGrassUv.z);`);
    grassReplace(shader, 'fragmentShader', '#include <normal_fragment_begin>',
      '#include <normal_fragment_begin>\nnormal *= gl_FrontFacing ? 1.0 : -1.0;');
    if (!unlit) grassReplace(shader, 'fragmentShader', '#include <roughnessmap_fragment>',
      '#include <roughnessmap_fragment>\nroughnessFactor = mix(.96, .53, vGrass.x);');
  };
  material.onBeforeCompile = shader => compile(shader);
  material.customProgramCacheKey = () => 'yard-grass-1';
  const unlitHook = {hook:shader => compile(shader,true), key:() => 'yard-grass-1|matcap'};
  const attach = target => {
    Object.defineProperty(target.userData,'grassUniforms',{value:uniforms});
    Object.defineProperty(target.userData,'unlitHook',{value:unlitHook});
  };
  attach(material);
  const clone = material.clone;
  material.clone = function() {
    const target = clone.call(this); target.onBeforeCompile = this.onBeforeCompile;
    target.customProgramCacheKey = this.customProgramCacheKey; target.clone = this.clone; attach(target); return target;
  };
  return material;
}

export function buildGrass(plan, kit, tier, source, fringeCount = 0) {
  const budget = Math.max(0,TIERS[tier].lawnBlades-fringeCount), polygon = plan.site?.lot;
  let clock;
  const result = {tier, instances:0, draws:0, regions:0, animated:false, mesh:null,
    update(seconds) { if (this.animated) clock.value = seconds; }};
  if (!budget || !grassLawn(kit) || !polygon?.length) return result;
  const lot = prepared(polygon,.4), covers = grassCovers(plan).map(p => prepared(p.polygon,p.margin));
  // Grid spacing depends only on lot geometry and tier, never on its obstacles.
  // Thus a moving feature reveals the exact cells it used to cover.
  const w = lot.x1-lot.x0, h = lot.y1-lot.y0;
  const spacing = Math.max(TIERS[tier].lawnSpacing, Math.sqrt(w*h/budget));
  const nx = Math.min(budget,Math.max(1,Math.floor(w/spacing)));
  const ny = Math.min(Math.floor(budget/nx),Math.max(1,Math.floor(h/spacing)));
  const spread = Math.max(1,Math.min(2,Math.sqrt(w*h/(nx*ny))/CLUMP_SPACING));
  // A small spatial lookup keeps many distant garden/path polygons out of the
  // hot loop. It is build-only and introduces no extra meshes or frame work.
  const bins = Array.from({length:256},()=>[]);
  for (const p of covers) {
    const bx0=Math.max(0,Math.floor((p.x0-lot.x0)*16/w)), bx1=Math.min(15,Math.floor((p.x1-lot.x0)*16/w));
    const by0=Math.max(0,Math.floor((p.y0-lot.y0)*16/h)), by1=Math.min(15,Math.floor((p.y1-lot.y0)*16/h));
    for(let bx=bx0;bx<=bx1;bx++)for(let by=by0;by<=by1;by++)bins[bx*16+by].push(p);
  }
  let seed = 0;
  for (const p of polygon) for (const n of p) seed = (Math.imul(seed,31)+Math.round(n*100))|0;
  const matrices = new Float32Array(nx*ny*16), pads = (plan.site.terraces || []).map(p => prepared(p.polygon,p.blend ?? 6));
  let count = 0, low = 0, high = 0;
  for (let ix = 0; ix < nx; ix++) for (let iy = 0; iy < ny; iy++) {
    const id = (Math.imul(ix,73856093)^Math.imul(iy,19349663)^seed)|0;
    const r = hash(id), s = hash(id+1);
    const x = lot.x0+(ix+.2+.6*r)*w/nx, y = lot.y0+(iy+.2+.6*s)*h/ny;
    if (!lot.rectangle && !contains(lot,x,y,false)) continue;
    // Keep roots and their maximum lean/gust clear of the lot boundary too.
    let edge = Math.min(x-lot.x0, lot.x1-x, y-lot.y0, lot.y1-y)-.4;
    if (!lot.rectangle) for (let i=0,j=polygon.length-1;i<polygon.length;j=i++) {
      const a=polygon[j],b=polygon[i],dx=b[0]-a[0],dy=b[1]-a[1];
      const t=Math.max(0,Math.min(1,((x-a[0])*dx+(y-a[1])*dy)/(dx*dx+dy*dy||1)));
      edge=Math.min(edge,Math.hypot(x-a[0]-t*dx,y-a[1]-t*dy));
      if (edge < .4) break;
    }
    if (edge < .4) continue;
    const nearby=bins[Math.min(15,Math.floor((x-lot.x0)*16/w))*16+Math.min(15,Math.floor((y-lot.y0)*16/h))];
    let covered=false;
    for (const p of nearby) if (contains(p,x,y)) {covered=true;break;}
    if (covered) continue;
    const height = pads.some(p => x>=p.x0&&x<=p.x1&&y>=p.y0&&y<=p.y1) ? groundAt(plan,x,y) : 0;
    // The lawn goes on past the lot as bare ground, so the blades shorten over
    // the last few feet rather than stopping as a wall.
    const rim = Math.min(1,(edge-.4)/4), short = .35+.65*rim*rim*(3-2*rim);
    const a = r*Math.PI*2, c = Math.cos(a)*spread, sn = Math.sin(a)*spread, scale = (.68+.42*s)*short, k = count++*16;
    matrices[k]=c; matrices[k+2]=-sn; matrices[k+5]=scale; matrices[k+8]=sn; matrices[k+10]=c;
    matrices[k+12]=x; matrices[k+13]=height-.04; matrices[k+14]=-y; matrices[k+15]=1;
    low=Math.min(low,height); high=Math.max(high,height);
  }
  if (!count) return result;
  const geometry = bladeGeometry(), material = grassMaterial(source);
  clock = material.userData.grassUniforms.grassTime;
  const mesh = new THREE.InstancedMesh(geometry,material,0);
  // Constructor's identity-matrix fill and per-instance Object3D.compose would
  // otherwise double the placement work. Upload the packed buffer directly.
  mesh.instanceMatrix = new THREE.InstancedBufferAttribute(matrices.subarray(0,count*16),16); mesh.count=count;
  mesh.receiveShadow=true; mesh.castShadow=false; mesh.raycast=()=>{};
  // At a cube's 256 px a blade is far below a texel; the lawn under it already
  // carries the colour, so a capture skips the field's millions of triangles.
  mesh.userData.noOcclusion=true; mesh.userData.yardGrass=true; mesh.userData.reflectionExclude=true;
  mesh.boundingBox=new THREE.Box3(new THREE.Vector3(lot.x0-.3,low-.1,-lot.y1-.3),new THREE.Vector3(lot.x1+.3,high+.7,-lot.y0+.3));
  mesh.boundingSphere=mesh.boundingBox.getBoundingSphere(new THREE.Sphere());
  return Object.assign(result,{instances:count,draws:1,regions:1,animated:true,mesh});
}

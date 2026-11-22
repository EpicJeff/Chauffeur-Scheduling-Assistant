import * as THREE from 'three';
import { windVector } from './sky/wind.js';
import { groundAt, buildingFootprint } from './twin_ground.js';
import { allPorches } from './twin_generator.js';
import { pathBoundaries, pathSurfacePolygons } from './path_shapes.js';
import { paverSettings } from './paver_layout.js';
import { yardPaverLayout } from './paver_path.js';
import { firePitOutline } from './fire_pits.js';
import { TIERS } from './twin_tiers.js';
import { manifest } from './twin_library.js';
import { materialGrass } from './material_rules.js';
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

// An empty lawn role (including a tint-only override) remains grass.
export function grassLawn(kit) {
  const ref = kit.materials?.lawn || {}, id = ref.id || ref.asset;
  return !id || materialGrass(manifest(kit)[id], id);
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
  // Pads are the lawn at another height. Only beds and pad-edge solids clear it.
  for (const p of site.beds || []) add(p.polygon);
  for (const pad of site.terraces || []) for (let i=0;i<pad.polygon.length;i++) {
    if (pad.edges?.[i]?.edge !== 'sharp') continue;
    const points=[];
    const project=(g,part)=>{
      if (part !== 'rail') {const a=g.attributes.position;for(let j=0;j<a.count;j++)points.push([a.getX(j),-a.getZ(j)]);}
      g.dispose();
    };
    if (pad.edges[i].wall) project(retainingWallGeometry(plan,pad,i),'wall');
    buildPadEdge(plan,pad,i,project);
    // The pad no longer clears its high side for us. A wall or a stair stands
    // up out of the lawn, so its margin grows with a coarser tier's wider clump
    // (`reach`) and a blade never comes out through a face, in still air or gust.
    if (points.length) covers.push({polygon: footprint(points), margin: .4, reach: true});
  }
  for (const h of site.hardscape || []) {
    if (h.kind === 'path') {
      const layout = paverSettings(h)?.joint === 'grass' ? yardPaverLayout(h) : null;
      if (layout) {
        for (const p of layout.pavers) covers.push({polygon:p.polygon, margin:0, paver:true});
        if (h.edging === 'curb') {
          const inner=pathBoundaries(h), outer=pathBoundaries(h,(h.width ?? 3)/2+.5);
          for (const side of ['left','right']) for (let i=1;i<inner[side].length;i++)
            add([inner[side][i-1],inner[side][i],outer[side][i],outer[side][i-1]]);
        }
      }
      else for (const p of pathSurfacePolygons(h)) add(p, h.edging === 'curb' ? .9 : .4);
    }
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
  return {polygon, margin, marginSq: margin*margin, rectangle, x0:Math.min(...xs)-margin, x1:Math.max(...xs)+margin,
    y0:Math.min(...ys)-margin, y1:Math.max(...ys)+margin};
}
function contains(p, x, y, border = true) {
  if (x < p.x0 || x > p.x1 || y < p.y0 || y > p.y1) return false;
  if (p.rectangle && border) return true;
  let inside = false;
  const poly = p.polygon, len = poly.length, checkMargin = border && p.margin > 0, mSq = p.marginSq;
  for (let i = 0, j = len-1; i < len; j = i++) {
    const a = poly[j], b = poly[i], dx = b[0]-a[0], dy = b[1]-a[1];
    if (checkMargin) {
      const t = Math.max(0, Math.min(1, ((x-a[0])*dx+(y-a[1])*dy)/(dx*dx+dy*dy || 1)));
      const qx = x-a[0]-t*dx, qy = y-a[1]-t*dy;
      if (qx*qx+qy*qy < mSq) return true;
    }
    if ((a[1]>y)!==(b[1]>y) && x < dx*(y-a[1])/dy+a[0]) inside = !inside;
  }
  return inside;
}
const hash = n => { n = Math.imul(n ^ n >>> 16, 0x21f0aaad); n = Math.imul(n ^ n >>> 15, 0x735a2d97); return ((n ^ n >>> 15) >>> 0) / 4294967296; };

// The clump is modelled for this grid spacing (plan feet); a coarser tier's grid
// spreads and widens its clumps to match, so the cover stays even.
const BLADES = 5, CLUMP_SPACING = .28;
// Bound the bent ribbons, not just their root offsets, for squeezed joints.
const JOINT_REACH = .36;
// Feet a lawn root keeps from a paver's edge.
export const PAVER_ROOT_MARGIN = .04;
// Feet of shortening lawn past the lot line, and the open-share sample per side.
const SKIRT = 4, SAMPLES = 96;
// Performance budget (owner house, High, default zoomed-out orbit): <1M main
// pass lawn triangles (was 2.73M), full density within 30 m, <=32 tile draws.
// Live owner-house measurement remains the landing gate; never lower near density.
export const GRASS_TILE_TARGET = 32, GRASS_TILE_MIN_METRES = 8;
export const GRASS_MAIN_TRIANGLE_BUDGET = 1_000_000, GRASS_TRIANGLES_PER_CLUMP = 15;
export const GRASS_FADE_MARGIN = .045, GRASS_SEED_MARGIN = .002;
// Density by distance. A High clump sits about 6 cm from its neighbours, under two
// pixels at 50 m on a 1440p screen: full density there buys nothing. Clumps stay
// complete to 12 m, thin to 15% by 60 m, and the survivors widen by 1/sqrt(keep) so
// the cover holds. The shader reads the same constants (grassMaterial).
export const GRASS_FULL_METRES = 12, GRASS_THIN_METRES = 60, GRASS_FAR_KEEP = .15, GRASS_MAX_WIDEN = 2.6;
const FT = .3048;

// Match the shader's local-root hash with float32 intermediates. The extra
// seed margin keeps the CPU prefix conservative across small sin differences.
const FROUND = Math.fround, SEED_X = FROUND(12.9898), SEED_Z = FROUND(78.233), SEED_M = FROUND(43758.5453);
export function grassSeed(x,z) {
  const n=FROUND(FROUND(Math.sin(FROUND(FROUND(FROUND(x)*SEED_X)+FROUND(FROUND(z)*SEED_Z))))*SEED_M);
  return n-Math.floor(n);
}
export function grassKeep(distance) {
  const t=Math.max(0,Math.min(1,(distance-GRASS_FULL_METRES)/(GRASS_THIN_METRES-GRASS_FULL_METRES)));
  return 1+(GRASS_FAR_KEEP-1)*t*t*(3-2*t);
}
export function grassCountForDistance(seeds,distance) {
  const limit=grassKeep(distance)+GRASS_FADE_MARGIN+GRASS_SEED_MARGIN;
  let lo=0,hi=seeds.length;
  while(lo<hi){const mid=(lo+hi)>>>1;if(seeds[mid]<limit)lo=mid+1;else hi=mid;}
  return lo;
}
// Input and tile size are in plan feet. Keep local roots unchanged: their hash,
// wind, texture mapping and seasonal patches must survive repartitioning.
export function splitGrassTiles(matrices,lotArea) {
  const count=matrices.length/16;
  if(!count)return [];
  let x0=Infinity,x1=-Infinity,z0=Infinity,z1=-Infinity;
  const seeds=new Float32Array(count);
  for(let i=0;i<count;i++){
    const x=matrices[i*16+12],z=matrices[i*16+14];
    if(x<x0)x0=x;if(x>x1)x1=x;if(z<z0)z0=z;if(z>z1)z1=z;
    seeds[i]=grassSeed(x,z);
  }
  let size=Math.max(GRASS_TILE_MIN_METRES/FT,Math.sqrt(lotArea/GRASS_TILE_TARGET));
  // Include the skirt and narrow/rotated lots in the draw budget too.
  while((Math.floor((x1-x0)/size)+1)*(Math.floor((z1-z0)/size)+1)>GRASS_TILE_TARGET)size*=1.05;
  // Positive float32 bit order equals numeric order. Two radix passes avoid
  // O(n log n) comparator sorting on a 200k-clump High-tier build.
  const bits=new Uint32Array(seeds.buffer),buckets=new Uint32Array(65536);
  let order=new Uint32Array(count),scratch=new Uint32Array(count);
  for(let i=0;i<count;i++)order[i]=i;
  for(const shift of [0,16]){
    buckets.fill(0);
    for(let i=0;i<count;i++)buckets[(bits[order[i]]>>>shift)&65535]++;
    let offset=0;for(let i=0;i<buckets.length;i++){const n=buckets[i];buckets[i]=offset;offset+=n;}
    for(let i=0;i<count;i++){const index=order[i];scratch[buckets[(bits[index]>>>shift)&65535]++]=index;}
    [order,scratch]=[scratch,order];
  }
  const invSize=1/size,nz=Math.floor((z1-z0)*invSize)+1,nx=Math.floor((x1-x0)*invSize)+1;
  const ids=new Uint16Array(count),sizes=new Uint32Array(nx*nz);
  for(let i=0;i<count;i++){
    const key=Math.floor((matrices[i*16+12]-x0)*invSize)*nz+Math.floor((matrices[i*16+14]-z0)*invSize);
    ids[i]=key;sizes[key]++;
  }
  const bins=Array.from(sizes,n=>new Uint32Array(n));sizes.fill(0);
  for(let j=0;j<count;j++){const i=order[j],key=ids[i];bins[key][sizes[key]++]=i;}
  return bins.filter(indices=>indices.length).map(indices=>{
    const values=new Float32Array(indices.length);
    for(let i=0;i<indices.length;i++)values[i]=seeds[indices[i]];
    return {indices,seeds:values};
  });
}

function bladeGeometry() {
  const positions = [], normals = [], shape = [], indices = [];
  // Five bent, two-segment blades per clump, 25 vertices / 15 triangles. The
  // blades stand spread over the clump's whole grid cell and lean different ways,
  // so the field reads as an even lawn rather than as rows of separate tufts.
  // Broad ribbons (about an inch at the root) that overlap and close the canopy,
  // as a real lawn does; needles left the ground showing between them
  // (user's comparison with their TwinMotion lawn, 2026-11-17).
  for (let b = 0; b < BLADES; b++) {
    const a = b * 2.39996, c = Math.cos(a), s = Math.sin(a), start = positions.length/3;
    const reach = .13*Math.sqrt((b+.5)/BLADES), ox = Math.cos(a+1.1)*reach, oz = Math.sin(a+1.1)*reach;
    for (const [t, width] of [[0,.046],[.6,.038],[1,0]]) {
      const lean = (.1+.08*((b*3)%BLADES)/BLADES)*t*t;
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

// three multiplies vColor by instanceColor; the grass tiles use that attribute as data
// (exposure, seed, joint), never as a tint. Fail loudly if three renames the line.
function withoutInstanceColor() {
  const line = 'vColor.rgb *= instanceColor.rgb;';
  if (!THREE.ShaderChunk.color_vertex.includes(line)) throw new Error('Grass shader anchor missing: ' + line);
  return THREE.ShaderChunk.color_vertex.replace(line, '');
}
export function grassReplace(shader, stage, anchor, replacement) {
  if (!shader[stage].includes(anchor)) throw new Error('Grass shader missing anchor: ' + anchor);
  shader[stage] = shader[stage].replace(anchor, replacement);
}
const VARYING = 'varying vec4 vGrass; varying vec3 vGrassUv;\n';
export function grassMaterial(source) {
  const material = new THREE.MeshStandardMaterial({name:'yard blades', side:THREE.DoubleSide, roughness:.9});
  material.userData.seasonLawn=true;
  const uniforms = {grassTime:{value:0}, grassWind:{value:new THREE.Vector2(.18,0)}, grassTint:{value:source.color}, grassMap:{value:null},
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
    shader.vertexShader = VARYING + 'attribute vec2 grassShape; uniform float grassTime; uniform vec2 grassWind; uniform mat3 grassUvMatrix;\n' + shader.vertexShader;
    // InstancedMesh owns instanceColor, unlike geometry attributes. Use its blue
    // channel for the joint flag so every tile shares the SAME blade geometry.
    grassReplace(shader,'vertexShader','#include <color_vertex>',
      withoutInstanceColor());
    grassReplace(shader, 'vertexShader', '#include <begin_vertex>', `#include <begin_vertex>
float grassJoint = 1.0-instanceColor.b;
vec3 grassRoot = instanceMatrix[3].xyz;
vec3 grassWorld = (modelMatrix * vec4(grassRoot, 1.0)).xyz;
float grassDistance = distance(cameraPosition, grassWorld);
// The CPU's seed (instanceColor.g), so the tile counts and the shader agree exactly.
float grassSeed = instanceColor.g;
// The whole house is usually on screen from 30 m or more, so the field stays
// complete that far; beyond it clumps thin out, grow to hold the cover, and
// their colour settles onto the lawn's own so sub-pixel blades do not sparkle.
float grassKeep = mix(1.0, ${GRASS_FAR_KEEP.toFixed(3)}, smoothstep(${GRASS_FULL_METRES.toFixed(1)}, ${GRASS_THIN_METRES.toFixed(1)}, grassDistance));
float grassScale = smoothstep(grassSeed-.045, grassSeed+.045, grassKeep);
transformed.xz *= 1.0 + (min(${GRASS_MAX_WIDEN.toFixed(1)}, inversesqrt(grassKeep)) - 1.0)*(1.0-grassJoint);
// A fixed seed threshold shrinks each clump over its own distance interval.
transformed *= grassScale;
float gust = sin(grassRoot.x*.11 + grassRoot.z*.07 + grassTime*.8)
  + .4*sin(grassRoot.z*.23 - grassRoot.x*.09 - grassTime*.57);
// Convert the world-directed wind into the instance's local yaw frame.
vec2 wind = grassWind * .28 * gust * grassShape.x*grassShape.x * grassScale*(1.0-grassJoint);
transformed.xz += vec2(dot(instanceMatrix[0].xz, wind), dot(instanceMatrix[2].xz, wind)) / max(dot(instanceMatrix[0].xz, instanceMatrix[0].xz),1e-6);
vGrass = vec4(grassShape, grassSeed, .5+.5*sin(grassRoot.x*.037+sin(grassRoot.z*.041)*2.0));
vGrassUv = vec3((grassUvMatrix * vec3(grassRoot.x, grassRoot.z, 1.0)).xy, .8*smoothstep(${GRASS_FULL_METRES.toFixed(1)}, ${GRASS_THIN_METRES.toFixed(1)}, grassDistance));`);
    shader.fragmentShader = VARYING + 'uniform vec3 grassTint; uniform sampler2D grassMap; uniform float grassHasMap;\n' + shader.fragmentShader;
    grassReplace(shader, 'fragmentShader', '#include <color_fragment>', `#include <color_fragment>
vec3 lawn = grassTint;
if (grassHasMap > .5) lawn *= texture2D(grassMap, vGrassUv.xy).rgb;
// "patch" is a reserved word in GLSL ES 3.
vec3 lawnPatch = mix(vec3(.90,1.0,.84), vec3(1.10,1.02,.82), vGrass.w);
vec3 lawnBlade = mix(vec3(.88,1.0,.90), vec3(1.12,1.04,.80), fract(vGrass.z*7.0+vGrass.y*3.3));
// Shaded at the root, lit and a little yellow at the tip: the tips sit above the
// lawn colour under them, which is what gives the field its depth.
// The canopy shades its own floor: deep at the root, so what shows between the
// tips reads as more grass, not as ground.
vec3 lawnTip = mix(vec3(.3), vec3(1.42,1.36,1.0), smoothstep(0.0, 1.0, vGrass.x));
diffuseColor.rgb *= lawn * mix(lawnPatch * lawnBlade * lawnTip, vec3(1.0), vGrassUv.z);`);
    grassReplace(shader, 'fragmentShader', '#include <normal_fragment_begin>',
      '#include <normal_fragment_begin>\nnormal *= gl_FrontFacing ? 1.0 : -1.0;');
    if (!unlit) grassReplace(shader, 'fragmentShader', '#include <roughnessmap_fragment>',
      '#include <roughnessmap_fragment>\nroughnessFactor = mix(.96, .53, vGrass.x);');
  };
  material.onBeforeCompile = shader => compile(shader);
  material.customProgramCacheKey = () => 'yard-grass-tiles-4';
  const unlitHook = {hook:shader => compile(shader,true), key:() => 'yard-grass-tiles-4|matcap'};
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

export function jointClumps(plan, spread, budget = TIERS.max.lawnBlades, raw = grassCovers(plan)) {
  const lot = plan.site?.lot;
  const paths = (plan.site?.hardscape || []).filter(h => h.kind === 'path' && paverSettings(h)?.joint === 'grass');
  if (!lot?.length || !budget || !paths.length) return new Float32Array();
  const boundary = prepared(lot,0), covers = raw.map(p => ({...prepared(p.polygon,p.margin), paver:p.paver}));
  // A local lookup bounds the work even for thousands of stones on a long path.
  const bins = new Map(), wide = [], size = Math.max(2, spread*JOINT_REACH*2);
  for (const p of covers) {
    const x0=Math.floor((p.x0-JOINT_REACH*spread)/size), x1=Math.floor((p.x1+JOINT_REACH*spread)/size);
    const y0=Math.floor((p.y0-JOINT_REACH*spread)/size), y1=Math.floor((p.y1+JOINT_REACH*spread)/size);
    if ((x1-x0+1)*(y1-y0+1)>256) { wide.push(p); continue; }
    for (let x=x0;x<=x1;x++) for (let y=y0;y<=y1;y++) {
      const k=x+','+y;if(!bins.has(k))bins.set(k,[]);bins.get(k).push(p);
    }
  }
  const matrices = [];
  for (const h of paths) {
    const layout = yardPaverLayout(h);
    if (!layout || layout.jointWidth < .5/12) continue;
    for (const [a,b] of layout.joints) {
      const dx=b[0]-a[0], dy=b[1]-a[1], length=Math.hypot(dx,dy), ux=dx/length, uy=dy/length;
      for (let d=.075;d<length;d+=.15) {
        if (matrices.length/16 >= budget) return new Float32Array(matrices);
        const x=a[0]+ux*d, y=a[1]+uy*d;
        if (!contains(boundary,x,y,false)) continue;
        const nearby=[...(bins.get(Math.floor(x/size)+','+Math.floor(y/size)) || []), ...wide];
        if (nearby.some(p=>contains(p,x,y))) continue;
        let clearance=layout.jointWidth/2;
        for (const p of nearby) if (p.paver) for (let i=0;i<p.polygon.length;i++) {
          const v=p.polygon[i],w=p.polygon[(i+1)%p.polygon.length],ex=w[0]-v[0],ey=w[1]-v[1];
          const t=Math.max(0,Math.min(1,((x-v[0])*ex+(y-v[1])*ey)/(ex*ex+ey*ey||1)));
          clearance=Math.min(clearance,Math.hypot(x-v[0]-t*ex,y-v[1]-t*ey));
        }
        const across=Math.min(spread,clearance/JOINT_REACH);
        let along=spread;
        if (across < .001) continue;
        // Preserve length along straight joints. At fanned corners shorten only
        // until the clump's rectangle clears every neighbouring convex stone.
        const clear = p => p.polygon.some((v,i) => {
          const w=p.polygon[(i+1)%p.polygon.length], ex=w[0]-v[0], ey=w[1]-v[1], len=Math.hypot(ex,ey);
          const outside=(ey*(x-v[0])-ex*(y-v[1]))/len;
          const reach=JOINT_REACH*(Math.abs(ey*uy+ex*ux)*across+Math.abs(ey*ux-ex*uy)*along)/len;
          return outside >= reach-1e-8;
        });
        while (along >= .001 && nearby.some(p=>p.paver&&!clear(p))) along *= .5;
        if (along < .001) continue;
        // Local x runs across the joint, z along it; the same five-blade clump.
        matrices.push(-uy*across,0,-ux*across,0, 0,.6,0,0, ux*along,0,-uy*along,0,
          x,groundAt(plan,x,y)-.04,-y,1);
      }
    }
  }
  return new Float32Array(matrices);
}

export function buildGrass(plan, kit, tier, source, fringeCount = 0) {
  const budget = Math.max(0,TIERS[tier].lawnBlades-fringeCount), polygon = plan.site?.lot;
  let clock,wind;
  const growsGrass = grassLawn(kit);
  const worldBox=new THREE.Box3(),cameraPosition=new THREE.Vector3();
  const result = {tier, growsGrass, instances:0, jointInstances:0, draws:0, regions:0, animated:false, mesh:null,tiles:[],
    update(seconds,weather,bearing,camera) { if (this.animated) {
      clock.value = seconds;
      if(weather)wind.value.set(...windVector(weather,bearing,{grass:true}));
      if(camera){
        camera.getWorldPosition(cameraPosition);
        this.mesh.updateWorldMatrix(true,true);
        for(const tile of this.tiles){
          worldBox.copy(tile.boundingBox).applyMatrix4(tile.matrixWorld);
          tile.count=grassCountForDistance(tile.userData.grassSeeds,worldBox.distanceToPoint(cameraPosition));
        }
      }
    } }};
  if (!budget || !growsGrass || !polygon?.length) return result;
  // The field runs to the lot line and a skirt past it, so a fence standing on
  // or just outside the line stands in grass (user, 2026-11-17).
  const lot = prepared(polygon,SKIRT), raw = grassCovers(plan);
  const w = lot.x1-lot.x0, h = lot.y1-lot.y0, X0 = lot.x0+SKIRT, X1 = lot.x1-SKIRT, Y0 = lot.y0+SKIRT, Y1 = lot.y1-SKIRT;
  // A small spatial lookup keeps many distant garden/path polygons out of the
  // hot loop. It is build-only and introduces no extra meshes or frame work.
  const bins = Array.from({length:256},()=>[]);
  const bin = covers => {
    for (const list of bins) list.length = 0;
    for (const p of covers) {
      const bx0=Math.max(0,Math.floor((p.x0-lot.x0)*16/w)), bx1=Math.min(15,Math.floor((p.x1-lot.x0)*16/w));
      const by0=Math.max(0,Math.floor((p.y0-lot.y0)*16/h)), by1=Math.min(15,Math.floor((p.y1-lot.y0)*16/h));
      for(let bx=bx0;bx<=bx1;bx++)for(let by=by0;by<=by1;by++)bins[bx*16+by].push(p);
    }
  };
  const invW = 16 / w, invH = 16 / h;
  // Share of full blade height a root at this point grows to; 0 where none grows.
  const grows = (x,y) => {
    let rim = 1;
    if (lot.rectangle ? x<X0||x>X1||y<Y0||y>Y1 : !contains(lot,x,y,false)) {
      let d = SKIRT;
      if (lot.rectangle) d = Math.hypot(Math.max(X0-x,0,x-X1),Math.max(Y0-y,0,y-Y1));
      else for (let i=0,j=polygon.length-1;i<polygon.length;j=i++) {
        const a=polygon[j],b=polygon[i],dx=b[0]-a[0],dy=b[1]-a[1];
        const t=Math.max(0,Math.min(1,((x-a[0])*dx+(y-a[1])*dy)/(dx*dx+dy*dy||1)));
        d=Math.min(d,Math.hypot(x-a[0]-t*dx,y-a[1]-t*dy));
      }
      if (d >= SKIRT) return 0;
      rim = 1-d/SKIRT;
    }
    const bx = Math.floor((x-lot.x0)*invW), by = Math.floor((y-lot.y0)*invH);
    const nearby=bins[(bx<15?bx:15)*16+(by<15?by:15)];
    for (let i=0;i<nearby.length;i++) if (contains(nearby[i],x,y)) return 0;
    // The ground goes on past the skirt bare, so the blades shorten across it
    // rather than stopping as a wall.
    return rim === 1 ? 1 : .35+.65*rim*rim*(3-2*rim);
  };
  // The budget is what grows, not the lot's bounding box: a coarse sample finds
  // the open share, rounded up to sixteenths so that moving a feature within the
  // lawn keeps the grid, and so reveals the exact cells it used to cover.
  bin(raw.map(p => prepared(p.polygon,p.margin)));
  let open = 0;
  for (let ix = 0; ix < SAMPLES; ix++) for (let iy = 0; iy < SAMPLES; iy++)
    if (grows(lot.x0+(ix+.5)*w/SAMPLES, lot.y0+(iy+.5)*h/SAMPLES)) open++;
  const share = Math.min(1,Math.ceil((open/(SAMPLES*SAMPLES)+.02)*16)/16), cells = Math.floor(budget/share);
  const spacing = Math.max(TIERS[tier].lawnSpacing, Math.sqrt(w*h/cells));
  const nx = Math.min(cells,Math.max(1,Math.floor(w/spacing)));
  const ny = Math.min(Math.floor(cells/nx),Math.max(1,Math.floor(h/spacing)));
  const spread = Math.max(1,Math.min(2,Math.sqrt(w*h/(nx*ny))/CLUMP_SPACING));
  // Lawn grows right up to a paver and leans over its edge, as real grass does
  // (owner, 2026-11-18: "no border"); only the roots stay off the stone.
  const fieldCovers = raw.map(p => prepared(p.polygon,p.margin+(p.paver ? PAVER_ROOT_MARGIN : p.reach ? .24*(spread-1) : 0)));
  bin(fieldCovers);
  const joints = jointClumps(plan,spread,budget,raw), jointCount = joints.length/16, fieldBudget = budget-jointCount;
  let seed = 0;
  for (const p of polygon) for (const n of p) seed = (Math.imul(seed,31)+Math.round(n*100))|0;
  const matrices = new Float32Array((Math.min(nx*ny,fieldBudget)+jointCount)*16);
  const pads = (plan.site.terraces || []).map(p => {
    const prep = prepared(p.polygon, p.blend ?? 6);
    return { ...prep, height: p.height, rx0: prep.x0 + prep.margin, rx1: prep.x1 - prep.margin,
      ry0: prep.y0 + prep.margin, ry1: prep.y1 - prep.margin };
  });
  const padCount = pads.length, singleRectPad = padCount === 1 && pads[0].rectangle ? pads[0] : null;
  const stepX = w / nx, stepY = h / ny;
  let count = 0;
  for (let ix = 0; ix < nx && count < fieldBudget; ix++) for (let iy = 0; iy < ny && count < fieldBudget; iy++) {
    const id = (Math.imul(ix,73856093)^Math.imul(iy,19349663)^seed)|0;
    const r = hash(id), s = hash(id+1);
    const x = lot.x0+(ix+.2+.6*r)*stepX, y = lot.y0+(iy+.2+.6*s)*stepY;
    const short = grows(x,y);
    if (!short) continue;
    let height = 0;
    if (singleRectPad) {
      if (x>=singleRectPad.x0&&x<=singleRectPad.x1&&y>=singleRectPad.y0&&y<=singleRectPad.y1) {
        height = x>=singleRectPad.rx0&&x<=singleRectPad.rx1&&y>=singleRectPad.ry0&&y<=singleRectPad.ry1
          ? singleRectPad.height : groundAt(plan,x,y);
      }
    } else if (padCount) {
      for (let pi=0;pi<padCount;pi++) {
        const p=pads[pi];
        if (x>=p.x0&&x<=p.x1&&y>=p.y0&&y<=p.y1) { height = groundAt(plan,x,y); break; }
      }
    }
    const a = r*Math.PI*2, c = Math.cos(a)*spread, sn = Math.sin(a)*spread, scale = (.68+.42*s)*short, k = count++*16;
    matrices[k]=c; matrices[k+2]=-sn; matrices[k+5]=scale; matrices[k+8]=sn; matrices[k+10]=c;
    matrices[k+12]=x; matrices[k+13]=height-.04; matrices[k+14]=-y; matrices[k+15]=1;
  }
  const fieldCount = count;
  matrices.set(joints,count*16); count += jointCount;
  if (!count) return result;
  const geometry = bladeGeometry(), material = grassMaterial(source);
  clock = material.userData.grassUniforms.grassTime;
  wind = material.userData.grassUniforms.grassWind;
  const mesh = new THREE.Group();mesh.name='lawn tiles';mesh.userData.yardGrass=true;
  mesh.userData.noOcclusion=true;mesh.userData.reflectionExclude=true;
  const tiles=splitGrassTiles(matrices.subarray(0,count*16),w*h).map(({indices,seeds})=>{
    const tile=new THREE.InstancedMesh(geometry,material,0),packed=new Float32Array(indices.length*16),flags=new Float32Array(indices.length*3);
    let x0=Infinity,x1=-Infinity,y0=Infinity,y1=-Infinity,z0=Infinity,z1=-Infinity;
    for(let j=0;j<indices.length;j++){
      const i=indices[j],s=i*16,d=j*16;
      packed[d]=matrices[s];packed[d+2]=matrices[s+2];packed[d+5]=matrices[s+5];
      packed[d+8]=matrices[s+8];packed[d+10]=matrices[s+10];
      const x=matrices[s+12],y=matrices[s+13],z=matrices[s+14];
      packed[d+12]=x;packed[d+13]=y;packed[d+14]=z;packed[d+15]=matrices[s+15];
      flags[j*3]=1;flags[j*3+1]=seeds[j];flags[j*3+2]=i<fieldCount?1:0;
      if(x<x0)x0=x;if(x>x1)x1=x;if(y<y0)y0=y;if(y>y1)y1=y;if(z<z0)z0=z;if(z>z1)z1=z;
    }
    tile.instanceMatrix=new THREE.InstancedBufferAttribute(packed,16);tile.count=indices.length;
    tile.instanceColor=new THREE.InstancedBufferAttribute(flags,3);
    tile.receiveShadow=true;tile.castShadow=false;tile.raycast=()=>{};tile.frustumCulled=true;
    // Keep blades out of probe/mirror captures and the AO normal prepass.
    tile.userData.noOcclusion=true;tile.userData.yardGrass=true;tile.userData.reflectionExclude=true;
    // Red stores sky exposure, green the seed, blue 1-joint. Both belong to the mesh,
    // allowing all tiles to keep a single geometry even after weather sampling.
    tile.userData.weatherInstanceColor=true;
    tile.userData.grassSeeds=seeds;
    // Compute once over ALL roots while packing, never over the current count.
    // Unlike still-geometry bounds this includes the shader envelope: <=.31 ft
    // blade reach * 2 spread * 2.6 widening + .28 * 1.4 gust < 2.2 ft;
    // blade height <=.36 * 1.1 < .4 ft (use .7 for a conservative headroom).
    tile.boundingBox=new THREE.Box3(new THREE.Vector3(x0-2.2,y0-.1,z0-2.2),new THREE.Vector3(x1+2.2,y1+.7,z1+2.2));
    tile.boundingSphere=tile.boundingBox.getBoundingSphere(new THREE.Sphere());
    mesh.add(tile);return tile;
  });
  return Object.assign(result,{instances:count,jointInstances:jointCount,draws:tiles.length,regions:1,animated:true,mesh,tiles,spread});
}

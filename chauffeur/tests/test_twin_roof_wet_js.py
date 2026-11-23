"""Wet roof pools, winding release-event rivulets, moving water film, staged drying, porosity and dielectric film: real r187 assembly and live sliced GLSL."""
import subprocess
import sys
from pathlib import Path

from test_twin_weather_surface_js import PREFIX
from twin_editor_dom import run_node

ROOT = Path(__file__).resolve().parents[1]


def main_weather_source():
    try:
        return subprocess.check_output(
            ['git', 'show', '7a23b5f1:chauffeur/static/twin/sky/weather_surface.js'],
            cwd=ROOT, encoding='utf-8', stderr=subprocess.DEVNULL,
        )
    except Exception:
        return None


DRIVER = PREFIX + r"""
const {installWeatherSurface,WEATHER_GLSL}=await import(file('static/twin/sky/weather_surface.js'));
const {createRoofWater}=await import(file('static/twin/sky/roof_water.js'));
// Capture THREE.ShaderChunk after haze & cloud-shadow install, before weather_surface ever installs.
const BEFORE_WEATHER=(()=>{
 const s=new THREE.Scene(),h=installStageHaze(s,{}),c=installCloudShadow(s,{uniforms:createCloudUniforms()});
 h.dispose();c.dispose();return {...THREE.ShaderChunk};
})();
const close=(a,b,eps=1e-6)=>assert.ok(Math.abs(a-b)<=eps,`${a} != ${b}`);
const mix=(a,b,t)=>typeof a==='object'?(a.w!==undefined?{x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t,z:a.z+(b.z-a.z)*t,w:a.w+(b.w-a.w)*t}:a.z!==undefined?{x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t,z:a.z+(b.z-a.z)*t}:{x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t}):a+(b-a)*t;
const clamp=(v,a,b)=>typeof v==='object'?(v.w!==undefined?{x:clamp(v.x,a,b),y:clamp(v.y,a,b),z:clamp(v.z,a,b),w:clamp(v.w,a,b)}:v.z!==undefined?{x:clamp(v.x,a,b),y:clamp(v.y,a,b),z:clamp(v.z,a,b)}:{x:clamp(v.x,a,b),y:clamp(v.y,a,b)}):Math.max(a,Math.min(b,v));
const smoothstep=(a,b,v)=>{const t=clamp((v-a)/(b-a),0,1);return t*t*(3-2*t);};
const step=(a,v)=>v<a?0:1;
const fract=x=>typeof x==='object'?(x.w!==undefined?{x:fract(x.x),y:fract(x.y),z:fract(x.z),w:fract(x.w)}:x.z!==undefined?{x:fract(x.x),y:fract(x.y),z:fract(x.z)}:{x:fract(x.x),y:fract(x.y)}):x-Math.floor(x);
const v2=(x,y=x)=>({x,y}),v3=(x,y=x,z=x)=>({x,y,z}),v4=(x,y=x,z=x,w=x)=>({x,y,z,w});
const add=(a,b)=>typeof b==='number'?(a.w!==undefined?v4(a.x+b,a.y+b,a.z+b,a.w+b):a.z!==undefined?v3(a.x+b,a.y+b,a.z+b):v2(a.x+b,a.y+b)):typeof a==='number'?add(b,a):(a.w!==undefined?v4(a.x+b.x,a.y+b.y,a.z+b.z,a.w+b.w):a.z!==undefined?v3(a.x+b.x,a.y+b.y,a.z+b.z):v2(a.x+b.x,a.y+b.y));
const sub=(a,b)=>typeof b==='number'?(a.w!==undefined?v4(a.x-b,a.y-b,a.z-b,a.w-b):a.z!==undefined?v3(a.x-b,a.y-b,a.z-b):v2(a.x-b,a.y-b)):typeof a==='number'?(b.w!==undefined?v4(a-b.x,a-b.y,a-b.z,a-b.w):b.z!==undefined?v3(a-b.x,a-b.y,a-b.z):v2(a-b.x,a-b.y)):(a.w!==undefined?v4(a.x-b.x,a.y-b.y,a.z-b.z,a.w-b.w):a.z!==undefined?v3(a.x-b.x,a.y-b.y,a.z-b.z):v2(a.x-b.x,a.y-b.y));
const mul=(a,b)=>typeof b==='number'?(a.w!==undefined?v4(a.x*b,a.y*b,a.z*b,a.w*b):a.z!==undefined?v3(a.x*b,a.y*b,a.z*b):v2(a.x*b,a.y*b)):typeof a==='number'?mul(b,a):(a.w!==undefined?v4(a.x*b.x,a.y*b.y,a.z*b.z,a.w*b.w):a.z!==undefined?v3(a.x*b.x,a.y*b.y,a.z*b.z):v2(a.x*b.x,a.y*b.y));
const absV=a=>typeof a==='object'?(a.w!==undefined?v4(Math.abs(a.x),Math.abs(a.y),Math.abs(a.z),Math.abs(a.w)):a.z!==undefined?v3(Math.abs(a.x),Math.abs(a.y),Math.abs(a.z)):v2(Math.abs(a.x),Math.abs(a.y))):Math.abs(a);
const floorV=a=>typeof a==='object'?(a.w!==undefined?v4(Math.floor(a.x),Math.floor(a.y),Math.floor(a.z),Math.floor(a.w)):a.z!==undefined?v3(Math.floor(a.x),Math.floor(a.y),Math.floor(a.z)):v2(Math.floor(a.x),Math.floor(a.y))):Math.floor(a);
const dot=(a,b)=>a.w!==undefined?a.x*b.x+a.y*b.y+a.z*b.z+a.w*b.w:a.z!==undefined?a.x*b.x+a.y*b.y+a.z*b.z:a.x*b.x+a.y*b.y;
const len=a=>a.z!==undefined?Math.hypot(a.x,a.y,a.z):Math.hypot(a.x,a.y);
const norm=a=>{const l=len(a)||1;return mul(a,1/l);};
const refl=(I,N)=>{const d=2*dot(N,I);return sub(I,mul(N,d));};
const neg=a=>mul(a,-1);

// Check balanced braces and no duplicate declarations within any GLSL block scope.
function checkGlslScopes(source,label){
 const text=source.replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/[^\n]*/g,'');
 const stack=[new Set()];
 for(const raw of text.split('\n')){
  const line=raw.trim();
  if(!line||line.startsWith('#'))continue;
  for(const ch of line){
   if(ch==='{')stack.push(new Set());
   else if(ch==='}'){assert.ok(stack.length>1,label+' unbalanced }');stack.pop();}
  }
  const m=line.match(/^(?:float|int|bool|vec[234]|mat[234])\s+([A-Za-z_]\w*)\s*(?:=|;)/);
  if(m&&!line.includes('(')&&stack.length>1){
   const scope=stack.at(-1);
   assert.ok(!scope.has(m[1]),`${label}: duplicate declaration of ${m[1]}`);
   scope.add(m[1]);
  }
 }
 assert.equal(stack.length,1,label+' unbalanced {');
}

function braceBlock(src,fromIndex){
 const start=src.indexOf('{',fromIndex);
 assert.ok(start>=0,'opening brace found');
 let depth=0;
 for(let i=start;i<src.length;i++){
  if(src[i]==='{')depth++;
  else if(src[i]==='}'){depth--;if(depth===0)return src.slice(fromIndex,i+1);}
 }
 throw new Error('unbalanced brace block');
}

// Build live JS evaluators directly from the installed WEATHER_GLSL and the real
// preprocessed THREE.ShaderChunk.normal_fragment_maps (no hand-retyped APPLY).
function buildEvaluators(){
 const installed=installWeatherSurface(new THREE.Scene());installed.dispose();
 const roofGlsl=preprocess('#define WEATHER_SURFACE_ROOF\n'+WEATHER_GLSL);
 const body=(type,name)=>{
  const m=roofGlsl.match(new RegExp(type+' '+name+'\\([^)]*\\) \\{([\\s\\S]*?)\\n\\}'));
  assert.ok(m,name+' found in roof GLSL');return m[1];
 };
 const scalar=name=>{
  const m=roofGlsl.match(new RegExp('float '+name+'\\(([^)]*)\\) \\{([\\s\\S]*?)\\n\\}'));
  assert.ok(m,name);
  return new Function('mix','clamp','smoothstep','max','min','abs','sin','step',
   `return (${m[1].replace(/float /g,'')})=>{${m[2].replace(/\bfloat\b/g,'let')}}`)(mix,clamp,smoothstep,Math.max,Math.min,Math.abs,Math.sin,step);
 };
 const ringHash=new Function('p','fract',body('vec3','weatherRingHash')
  .replace('vec3 q=fract(vec3(p.x,p.y,p.x)*vec3(.1031,.1030,.0973));','let q={x:fract(p.x*.1031),y:fract(p.y*.1030),z:fract(p.x*.0973)};')
  .replace('q+=dot(q,q.yxz+33.33);','const d=q.x*(q.y+33.33)+q.y*(q.x+33.33)+q.z*(q.z+33.33);q={x:q.x+d,y:q.y+d,z:q.z+d};')
  .replace('return fract((q.xxy+q.yzz)*q.zyx);','return {x:fract((q.x+q.y)*q.z),y:fract((q.x+q.z)*q.y),z:fract((q.y+q.z)*q.x)};'));
 const hash=p=>ringHash(p,fract);
 const dropRadius=scalar('weatherDropRadius'),dropDensity=scalar('weatherDropDensity'),spotFn=scalar('weatherSpot'),dropTone=scalar('weatherDropTone');
 const dropCell=new Function('id','cellSize','up','weatherRingHash','weatherDropRadius','weatherDropDensity','fract',body('vec4','weatherDropCell')
  .replace('vec3 random=','let random=').replace('float radius=','let radius=')
  .replace('vec2 centre=vec2(radius)+random.xy*(1.0-2.0*radius);','let centre={x:radius+random.x*(1-2*radius),y:radius+random.y*(1-2*radius)};')
  .replace('float arrival=','let arrival=')
  .replace('vec4(centre,radius,fract(random.y*19.19)>weatherDropDensity(up)?2.0:arrival)','({x:centre.x,y:centre.y,z:radius,w:fract(random.y*19.19)>weatherDropDensity(up)?2.0:arrival})'));
 const cell=(id,size,up)=>dropCell(id,size,up,hash,dropRadius,dropDensity,fract);

 // Translate live weatherRoofRivulets directly from WEATHER_GLSL.
 const rivBody=body('vec3','weatherRoofRivulets')
  .replace(/\/\/[^\n]*/g,'')
  .replace('vec2 wr=min(vec2(wet,flow)*vec2(1.8,2.2),1.0);','let wr=v2(min(wet*1.8,1),min(flow*2.2,1));')
  .replace('for(int k=0;k<rows;k++)','for(let k=0;k<rows;k++)')
  .replace('float(k)','k')
  .replace('vec2 wp=fract(max(0.0,dyM)*vec2(.50+.50*h.x,1.10+.90*h.y))-.5;','let wp=sub(fract(mul(max(0,dyM),v2(.5+.5*h.x,1.1+.9*h.y))),.5);')
  .replace('dot(wp*(.5-abs(wp)),h.xy*vec2(1.15,.65)-vec2(.575,.325))','dot(mul(wp,sub(.5,absV(wp))),sub(mul(v2(h.x,h.y),v2(1.15,.65)),v2(.575,.325)))')
  .replace('vec2 hd=vec2(rx,dyM-headY)*32.0;','let hd=mul(v2(rx,dyM-headY),32.0);')
  .replace('vec4 seg=clamp(vec4(dyM-tailY,headY-dyM,dyM,dyM-tailY+1.54)*vec4(4.5,22.0,12.5,.65),0.0,1.0);','let seg=clamp(mul(v4(dyM-tailY,headY-dyM,dyM,dyM-tailY+1.54),v4(4.5,22,12.5,.65)),0,1);')
  .replace('slope+=vec2(lensN,0.0)+hd*(hDome*2.1);','slope=add(slope,add(v2(lensN,0),mul(hd,hDome*2.1)));')
  .replace('return vec3(slope*(vis*wr.x),mix(avgCov,min(cov,1.0)*wr.x,vis));','const _s=mul(slope,vis*wr.x);return v3(_s.x,_s.y,mix(avgCov,min(cov,1)*wr.x,vis));')
  .replace(/vec3\(([^)]+)\)/g,'v3($1)')
  .replace(/vec2\(([^)]+)\)/g,'v2($1)')
  .replace(/\b(?:float|int|vec2|vec3) (?=\w+=)/g,'let ');
 const rivRaw=new Function('uv','wet','flow','phase','vis','trail',
  'v2','v3','v4','add','sub','mul','dot','absV','abs','floor','fract','mix','clamp','min','max','step','weatherRingHash',rivBody);
 const rivulets=(uv,wet,flow,phase,vis,trail=flow>0?1:wet*.65)=>rivRaw(
  uv,wet,flow,phase,vis,trail,v2,v3,v4,add,sub,mul,dot,absV,Math.abs,Math.floor,fract,mix,clamp,Math.min,Math.max,step,hash);

 // Translate live weatherRoofGrad directly from WEATHER_GLSL.
 const gradBody=body('vec2','weatherRoofGrad')
  .replace(/\/\/[^\n]*/g,'')
  .replace('vec2 i=floor(p),f=fract(p);','let i=floorV(p),f=fract(p);')
  .replace('vec2 du=f*(1.0-f);','let du=mul(f,sub(1,f));')
  .replace('vec4 x=fract(i.x*.1031+vec4(0.0,.1031,0.0,.1031));','let x=fract(add(i.x*.1031,v4(0,.1031,0,.1031)));')
  .replace('vec4 y=fract(i.y*.1030+vec4(0.0,0.0,.1030,.1030));','let y=fract(add(i.y*.1030,v4(0,0,.1030,.1030)));')
  .replace('vec4 q=x*19.3+(y*31.7+11.1);','let q=add(mul(x,19.3),add(mul(y,31.7),11.1));')
  .replace('vec4 h=fract(q*q);','let h=fract(mul(q,q));')
  .replace('return du*vec2(mix(h.y-h.x,h.w-h.z,f.y),mix(h.z-h.x,h.w-h.y,f.x));','return mul(du,v2(mix(h.y-h.x,h.w-h.z,f.y),mix(h.z-h.x,h.w-h.y,f.x)));');
 const gradRaw=new Function('p','v2','v4','add','sub','mul','floorV','fract','mix',gradBody);
 const roofGrad=p=>gradRaw(p,v2,v4,add,sub,mul,floorV,fract,mix);

 // Translate live weatherRoofFilm directly from WEATHER_GLSL.
 const filmBody=body('vec2','weatherRoofFilm')
  .replace(/\/\/[^\n]*/g,'')
  .replace('vec3 lw=abs(fract(uv.x*vec3(.53,-.37,.29)+uv.y*vec3(.19,.27,-.17)-phase*vec3(2.0,3.0,1.0))*2.0-1.0);',
   'let lw=absV(sub(mul(fract(sub(add(mul(uv.x,v3(.53,-.37,.29)),mul(uv.y,v3(.19,.27,-.17))),mul(phase,v3(2,3,1)))),2),1));')
  .replace('vec4 lm=vec4(.72,.57,.53,.69)+lane*vec4(.56,.44,.77,1.01);','let lm=add(v4(.72,.57,.53,.69),mul(lane,v4(.56,.44,.77,1.01)));')
  .replace('for(int k=0;k<steps;k++)','for(let k=0;k<steps;k++)')
  .replace('float(k)','k')
  .replace('vec4 par=vec4(26.0,48.0,.56,.52)+lay*vec4(21.0,32.0,-.10,-.14);','let par=add(v4(26,48,.56,.52),mul(lay,v4(21,32,-.10,-.14)));')
  .replace('vec2 g=weatherRoofGrad(vec2(uv.x+ay*sk,ay)*par.x+vec2(fk*13.7,fk*29.3));','let g=weatherRoofGrad(add(mul(v2(uv.x+ay*sk,ay),par.x),v2(fk*13.7,fk*29.3)));')
  .replace('slope+=vec2(g.x,g.y+g.x*sk)*w;','slope=add(slope,mul(v2(g.x,g.y+g.x*sk),w));')
  .replace('vec2 ip=vec2(uv.x+uv.y*.43,uv.y)*11.76;','let ip=mul(v2(uv.x+uv.y*.43,uv.y),11.76);')
  .replace('float rq=dot(fract(floor(ip)*vec2(.1031,.1030)),vec2(19.3,31.7));','let rq=dot(fract(mul(floorV(ip),v2(.1031,.1030))),v2(19.3,31.7));')
  .replace('vec2 rh=fract(rq*(rq+vec2(11.1,28.4)));','let rh=fract(mul(rq,add(rq,v2(11.1,28.4))));')
  .replace('vec2 d=fract(ip)-vec2(.26+.48*rh.x,.16+.26*rh.y+age*lm.y);','let d=sub(fract(ip),v2(.26+.48*rh.x,.16+.26*rh.y+age*lm.y));')
  .replace('vec2 re=max(vec2(0.0),vec2(1.0-s*s,1.0-age*2.5));','let re=v2(Math.max(0,1-s*s),Math.max(0,1-age*2.5));')
  .replace('slope+=d*(s*re.x*re.y*ringW);','slope=add(slope,mul(d,s*re.x*re.y*ringW));')
  .replace('return slope*(lm.zw*film);','return mul(slope,mul(v2(lm.z,lm.w),film));')
  .replace(/vec3\(([^)]+)\)/g,'v3($1)')
  .replace(/vec2\(([^)]+)\)/g,'v2($1)')
  .replace(/\b(?:float|int|vec2|vec3|vec4) (?=\w+=)/g,'let ');
 const filmRaw=new Function('uv','film','rate','phase','px',
  'v2','v3','v4','add','sub','mul','dot','absV','abs','floorV','floor','fract','clamp','weatherRoofGrad',filmBody);
 const roofFilm=(uv,film,rate,phase,px=0.005)=>filmRaw(
  uv,film,rate,phase,px,v2,v3,v4,add,sub,mul,dot,absV,Math.abs,floorV,Math.floor,fract,clamp,roofGrad);

 // Translate live weatherRoofBeads directly from WEATHER_GLSL.
 const beadBody=body('vec3','weatherRoofBeads')
  .replace(/\/\/[^\n]*/g,'')
  .replace('vec2 p=uv*14.7059;','let p=mul(uv,14.7059);')
  .replace('vec3 h=weatherRingHash(floor(p));','let h=weatherRingHash(floorV(p));')
  .replace('vec2 q=(fract(p)-h.xy)/radius+h.xy*2.0-1.0;','let q=sub(add(mul(sub(fract(p),v2(h.x,h.y)),1/radius),mul(v2(h.x,h.y),2)),1);')
  .replace('return vec3(q*(dome*1.20*mask*vis),mix(avgCov,clamp(dome*3.2,0.0,1.0)*mask,vis));','const _s=mul(q,dome*1.2*mask*vis);return v3(_s.x,_s.y,mix(avgCov,clamp(dome*3.2,0,1)*mask,vis));')
  .replace(/\bfloat (?=\w+=)/g,'let ');
 const beadRaw=new Function('uv','wet','flow','phase','vis','keep',
  'v2','v3','add','sub','mul','dot','floorV','floor','fract','min','max','clamp','mix','step','weatherRingHash',beadBody);
 const beads=(uv,wet,flow,phase,vis,keep)=>beadRaw(
  uv,wet,flow,phase,vis,keep,v2,v3,add,sub,mul,dot,floorV,Math.floor,fract,Math.min,Math.max,clamp,mix,step,hash);

 // Non-roof weatherDrops evaluator for roof-vs-solid comparison at wet=1.
 const dropLayerBody=body('float','weatherDropLayer')
  .replace('vec2 p=world/cellSize,id=floor(p);','let p=v2(world.x/cellSize,world.y/cellSize),id=v2(Math.floor(p.x),Math.floor(p.y));')
  .replace('vec2 local=fract(p)-spot.xy;','let local=sub(v2(fract(p.x),fract(p.y)),spot);')
  .replace('vec2 direction=local/max(d,.001);','let direction=mul(local,1/max(d,.001));')
  .replace(/\b(?:float|vec4) (?=\w+=)/g,'let ');
 const dropLayerRaw=new Function('world','wet','dx','dy','cellSize','up','weatherDropCell','weatherSpot','weatherDropTone','sub','mul','v2','fract','length','dot','max','abs','smoothstep','mix',dropLayerBody);
 const dropLayer=(world,wet,dx,dy,size,up)=>dropLayerRaw(world,wet,dx,dy,size,up,cell,spotFn,dropTone,sub,mul,v2,fract,len,dot,Math.max,Math.abs,smoothstep,mix);
 const dropsRaw=new Function('world','wet','dx','dy','up','smoothstep','abs','v2','add','weatherDropLayer',body('float','weatherDrops')
  .replace('vec2 stretch=vec2(1.0,1.0-.35*vertical);','let stretch=v2(1,1-.35*vertical);')
  .replace('world*=stretch;dx*=stretch;dy*=stretch;','world=v2(world.x*stretch.x,world.y*stretch.y);dx=v2(dx.x*stretch.x,dx.y*stretch.y);dy=v2(dy.x*stretch.x,dy.y*stretch.y);')
  .replace('mat2 rotation=mat2(.8,.6,-.6,.8);','const rotation=p=>v2(.8*p.x-.6*p.y,.6*p.x+.8*p.y);')
  .replace('rotation*world+vec2(1.731,4.913)','add(rotation(world),v2(1.731,4.913))')
  .replaceAll('rotation*dx','rotation(dx)').replaceAll('rotation*dy','rotation(dy)').replace(/\bfloat (?=\w+=)/g,'let '));
 const solidDrops=(world,wet,dx,dy,up)=>dropsRaw(world,wet,dx,dy,up,smoothstep,Math.abs,v2,add,dropLayer);

 const wHash=p=>fract(Math.sin(p.x*127.1+p.y*311.7)*43758.5453);
 const wNoise=p=>{const ix=Math.floor(p.x),iy=Math.floor(p.y),fx=fract(p.x),fy=fract(p.y),u=fx*fx*(3-2*fx),v=fy*fy*(3-2*fy);
  return mix(mix(wHash(v2(ix,iy)),wHash(v2(ix+1,iy)),u),mix(wHash(v2(ix,iy+1)),wHash(v2(ix+1,iy+1)),u),v);};
 const wEdge=p=>wNoise(mul(p,.35))*.67+wNoise(add(mul(p,.7),v2(19.1,7.7)))*.33;

 const scalarNames=[...roofGlsl.matchAll(/float (weather\w+)\(([^)]*)\) \{/g)]
  .filter(m=>!m[2].includes('vec')).map(m=>m[1]);
 const scalarFns=Object.fromEntries(scalarNames.map(n=>[n,scalar(n)]));

 // Slice the REAL preprocessed roof APPLY block from THREE.ShaderChunk.normal_fragment_maps.
 const roofPre=preprocess('#define STANDARD\n#define WEATHER_SURFACE_ACTIVE\n#define WEATHER_SURFACE_ROOF\n'+THREE.ShaderChunk.normal_fragment_maps);
 const roofIfStart=roofPre.indexOf('if(vWeatherOpen>0.0&&weatherSurface.x');
 assert.ok(roofIfStart>=0,'live roof APPLY block found');
 let roofApplySrc=braceBlock(roofPre,roofIfStart);
 roofApplySrc=roofApplySrc
  .replace(/\/\/[^\n]*/g,'')
  .replaceAll('vWeatherWorld.xz','v2(vWeatherWorld.x,vWeatherWorld.z)')
  .replaceAll('vWeatherWorld.zy','v2(vWeatherWorld.z,vWeatherWorld.y)')
  .replaceAll('vWeatherWorld.xy','v2(vWeatherWorld.x,vWeatherWorld.y)')
  .replaceAll('weatherWorldDx.xz','v2(weatherWorldDx.x,weatherWorldDx.z)')
  .replaceAll('weatherWorldDx.zy','v2(weatherWorldDx.z,weatherWorldDx.y)')
  .replaceAll('weatherWorldDx.xy','v2(weatherWorldDx.x,weatherWorldDx.y)')
  .replaceAll('weatherWorldDy.xz','v2(weatherWorldDy.x,weatherWorldDy.z)')
  .replaceAll('weatherWorldDy.zy','v2(weatherWorldDy.z,weatherWorldDy.y)')
  .replaceAll('weatherWorldDy.xy','v2(weatherWorldDy.x,weatherWorldDy.y)')
  .replaceAll('weatherFace.xz','v2(weatherFace.x,weatherFace.z)')
  .replace('v2(weatherFace.x,weatherFace.z)/roofSlopeSin','mul(v2(weatherFace.x,weatherFace.z),1/roofSlopeSin)')
  .replace('vec2 roofVis=clamp((vec2(.048,.075)-roofPx)*vec2(34.0,22.2),0.0,1.0);',
   'let roofVis=clamp(mul(sub(v2(.048,.075),roofPx),v2(34,22.2)),0,1);')
  .replace('weatherRoofRivulets(roofUv,roofWetRaw,roofFlow,roofPhase,roofVis.x,roofTrail)*(roofSlopeMask*roofRivWeight)',
   'mul(weatherRoofRivulets(roofUv,roofWetRaw,roofFlow,roofPhase,roofVis.x,roofTrail),roofSlopeMask*roofRivWeight)')
  .replace('vec2 roofSlope=roofRiv.xy*(1.0-.65*roofBeadWash)+roofFilmSlope;',
   'let roofSlope=add(mul(v2(roofRiv.x,roofRiv.y),1-.65*roofBeadWash),roofFilmSlope);')
  .replace('roofNormalOff=roofAcrossDir*roofSlope.x+roofDownDir*roofSlope.y;',
   'roofNormalOff=add(mul(roofAcrossDir,roofSlope.x),mul(roofDownDir,roofSlope.y));_roofAcrossDir=roofAcrossDir;_roofDownDir=roofDownDir;_roofRiv=roofRiv;_roofFilmSlope=roofFilmSlope;')
  .replace('roofNormalOff.xz+=roofBead.xy*roofBeadKeep;',
   'roofNormalOff=add(roofNormalOff,mul(v3(roofBead.x,0,roofBead.y),roofBeadKeep));_roofBead=roofBead;')
  .replaceAll('diffuseColor.rgb *= ','diffuseColor.rgb = mul(diffuseColor.rgb, ')
  .replace(/(diffuseColor\.rgb = mul\(diffuseColor\.rgb, [^;]+);/g,'$1);')
  .replace('vec3(.2126,.7152,.0722)','v3(.2126,.7152,.0722)')
  .replace('vec3(.85,.87,.9)','v3(.85,.87,.9)')
  .replace('vec3(0.0,0.0,0.0)','v3(0,0,0)')
  .replace('vec2(0.0,0.0)','v2(0,0)')
  .replace('vec2(0.0)','v2(0,0)')
  .replace('mat3(viewMatrix)*(roofNormalOff*(1.0-weatherS))','mul(roofNormalOff,1-weatherS)')
  .replace('normal+mul(','add(normal,mul(')
  .replace(/(vec3 weatherNormal=add\(normal,mul\([^;]+);/,'$1);')
  .replace('weatherNormal/max(length(weatherNormal),.0001)','mul(weatherNormal,1/max(length(weatherNormal),.0001))')
  .replace('reflect(-roofViewDir,normal)','reflect(neg(roofViewDir),normal)')
  .replace(/vec3\(([^)]+)\)/g,'v3($1)')
  .replace(/vec2\(([^)]+)\)/g,'v2($1)')
  .replace(/\b(?:float|bool|vec2|vec3) (?=\w+\s*=)/g,'let ');

 const roofApplyFn=new Function(
  'weatherSurface','weatherRoof','vWeatherWorld','vWeatherOpen','weatherWorldDx','weatherWorldDy','nonPerturbedNormal','normal','vViewPosition','diffuseColor','roughnessFactor','metalnessFactor','viewMatrix',
  'inverseTransformDirection','v2','v3','add','sub','mul','dot','length','sqrt','normalize','reflect','neg','mix','clamp','smoothstep','abs','min','max','floor','fract',
  'weatherNoise','weatherEdge','weatherRipple','weatherRoofRivulets','weatherRoofFilm','weatherRoofBeads',...scalarNames,
  `let weatherHorizonDamp=1.0;
   let _roofAcrossDir=null,_roofDownDir=null,_roofRiv=v3(0,0,0),_roofFilmSlope=v2(0,0),_roofBead=v3(0,0,0),_roofWaterCov=0,_roofCoatWeight=0,_roofReflected=v3(0,1,0);
   ${roofApplySrc.replace('weatherHorizonDamp=mix(1.0,roofHorizon*roofSheen,roofWetNoSnow);',
    'weatherHorizonDamp=mix(1.0,roofHorizon*roofSheen,roofWetNoSnow);_roofWaterCov=roofWaterCov;_roofCoatWeight=roofCoatWeight;_roofReflected=roofReflected;')}
   return {color:diffuseColor.rgb,roughness:roughnessFactor,metalness:metalnessFactor,normal,horizonDamp:weatherHorizonDamp,
    acrossDir:_roofAcrossDir,downDir:_roofDownDir,riv:_roofRiv,filmSlope:_roofFilmSlope,bead:_roofBead,waterCov:_roofWaterCov,coatWeight:_roofCoatWeight,reflY:_roofReflected.y};`
 );

 function evalRoofApply({world,face,dxWorld=v3(0.003,0,0),dyWorld=v3(0,0,0.003),wet=0,snow=0,puddles=0,rate=0,phase=0,open=1,roughness=0.45,metalness=0.45,albedo=0.04,viewDir=v3(0,0.45,0.89),mapNormal=null,roofVec=null}){
  const rgb=typeof albedo==='number'?v3(albedo,albedo,albedo):v3(albedo[0],albedo[1],albedo[2]);
  const w4={x:wet,y:snow,z:puddles,w:Math.round(rate*255)+(phase>0?Math.min(phase,1-1/32768):0)};
  let r4=roofVec;
  if(!r4){
   const rw=createRoofWater().update({precip:rate>0?'rain':'none',rate,wetness:wet},0);
   const trail=rw.flow>0?1:rw.wet*.65;
   r4={x:rw.wet,y:rw.flow,z:rw.film,w:trail};
  }
  const n0=norm(face),nMap=mapNormal?norm(mapNormal):n0;
  return roofApplyFn(
   w4,r4,world,open,dxWorld,dyWorld,n0,nMap,viewDir,{rgb},roughness,metalness,null,
   (d)=>norm(d),v2,v3,add,sub,mul,dot,len,Math.sqrt,norm,refl,neg,mix,clamp,smoothstep,Math.abs,Math.min,Math.max,Math.floor,fract,
   wNoise,wEdge,()=>v2(0,0),rivulets,roofFilm,beads,...scalarNames.map(n=>scalarFns[n]),
  );
 }

 // Slice the REAL preprocessed solid APPLY block for bright-metal vs painted-metal checks.
 const solidPre=preprocess('#define STANDARD\n#define WEATHER_SURFACE_ACTIVE\n'+THREE.ShaderChunk.normal_fragment_maps);
 const solidSliceStart=solidPre.indexOf('float weatherFilmValue=');
 const solidSliceEnd=solidPre.indexOf('float weatherRingWeight=');
 assert.ok(solidSliceStart>=0&&solidSliceEnd>solidSliceStart,'live solid APPLY slice found');
 const solidBody=solidPre.slice(solidSliceStart,solidSliceEnd)
  .replace(/\/\/[^\n]*/g,'')
  .replace(/#[^\n]*/g,'')
  .replaceAll('vWeatherWorld.xz','v2(vWeatherWorld.x,vWeatherWorld.z)')
  .replace('weatherPlane*vec2(12.0,.7)','mul(weatherPlane,v2(12,.7))')
  .replace('dot(diffuseColor.rgb,vec3(.2126,.7152,.0722))','dot(diffuseColor.rgb,v3(.2126,.7152,.0722))')
  .replace('diffuseColor.rgb *= ','diffuseColor.rgb = mul(diffuseColor.rgb, ')
  .replace(/(diffuseColor\.rgb = mul\(diffuseColor\.rgb, [^;]+);/,'$1);')
  .replace('vec3(.85,.87,.9)','v3(.85,.87,.9)')
  .replace(/\b(?:float|bool) (?=\w+\s*=)/g,'let ');
 const solidApplyFn=new Function(
  'weatherSurface','vWeatherWorld','vWeatherOpen','weatherUp','weatherDrop','weatherPlane','diffuseColor','roughnessFactor','metalnessFactor',
  'v2','v3','mul','dot','mix','clamp','smoothstep','abs','max','weatherNoise','weatherEdge',...scalarNames,
  `let weatherMetal=metalnessFactor,weatherWet=weatherExposure(weatherSurface.x,vWeatherOpen);
   ${solidBody}
   return {color:diffuseColor.rgb,roughness:roughnessFactor,metalness:metalnessFactor,waterFilmCov:weatherWaterFilmCov};`
 );
 function evalSolidApply({albedo=0.4,metalness=0.6,roughness=0.45,wet=1,snow=0,puddles=0,open=1,up=1}){
  const rgb=typeof albedo==='number'?v3(albedo,albedo,albedo):v3(albedo[0],albedo[1],albedo[2]);
  return solidApplyFn(
   {x:wet,y:snow,z:puddles,w:0},v3(1.2,0.5,2.3),open,up,0,v2(1.2,2.3),{rgb},roughness,metalness,
   v2,v3,mul,dot,mix,clamp,smoothstep,Math.abs,Math.max,wNoise,wEdge,...scalarNames.map(n=>scalarFns[n]),
  );
 }

 // Also build live weatherRipple evaluator to prove 64 s clock matches 4 s clock identically.
 const rippleBody=body('vec2','weatherRipple')
  .replace('vec3 fromEye=vWeatherWorld-cameraPosition;','let fromEye={x:0,y:0,z:8};')
  .replace('vec2 cell=floor(world/.6),slope=vec2(0.0);','let cell=v2(Math.floor(world.x/.6),Math.floor(world.y/.6)),slope=v2(0,0);')
  .replace('vec2 midCell=floor(world/.6-.5);','let midCell=v2(Math.floor(world.x/.6-.5),Math.floor(world.y/.6-.5));')
  .replace('vec2 dx=weatherWorldDx.xz,dy=weatherWorldDy.xz;','let dx=v2(.005,0),dy=v2(0,.005);')
  .replace('int y=impact/width,x=impact-y*width;','let y=Math.trunc(impact/width),x=impact-y*width;')
  .replace('midCell+vec2(float(x),float(y))','v2(midCell.x+x,midCell.y+y)')
  .replace('cell+vec2(float(x-1),float(y-1))','v2(cell.x+x-1,cell.y+y-1)')
  .replace('vec2 centre=(id+random.yz)*.6;','let centre=v2((id.x+random.y)*.6,(id.y+random.z)*.6);')
  .replace('vec2 delta=world-centre;','let delta=sub(world,centre);')
  .replace('vec2 direction=delta/max(d,.001);','let direction=mul(delta,1/max(d,.001));')
  .replace('slope+=direction*band*fade*visible*strength*1.414214*support*farFade*(mid?1.0:nearFade);','let amp=band*fade*visible*strength*1.414214*support*farFade*(mid?1:nearFade);slope.x+=direction.x*amp;slope.y+=direction.y*amp;')
  .replaceAll('vec2(0.0)','v2(0,0)').replace(/\b(?:float|vec2|vec3|int|bool) (?=\w+=)/g,'let ');
 const rippleAt=(w4,world)=>new Function('world','weatherSurface','v2','sub','mul','dot','floor','fract','int','length','abs','max','smoothstep','weatherRingCount','weatherRingHash','weatherRingStrength','weatherRingSupport','weatherRingBand',rippleBody)(
  world,w4,v2,sub,mul,(a,b)=>dot(a,b)+(a.z??0)*(b.z??0),Math.floor,fract,Math.trunc,len,Math.abs,Math.max,smoothstep,scalarFns.weatherRingCount,hash,scalarFns.weatherRingStrength,scalarFns.weatherRingSupport,
  (d,age)=>Math.exp(-Math.abs(d-age*.46)*28.0)*Math.sin((d-age*.46)*48.0)
 );

 return {rivulets,roofFilm,beads,solidDrops,evalRoofApply,evalSolidApply,hash,rippleAt,
  porosityFn:scalarFns.weatherPorosity,darkenWetFn:scalarFns.weatherDarkenWet,
  wetRoughFn:scalarFns.weatherWetRoughness,waterFilmFn:scalarFns.weatherWaterFilm,
  wetScale:scalarFns.weatherWetScale,roughFn:scalarFns.weatherRoughness};
}

await test('roof programs assemble across all lit material kinds, add exactly +1 weatherRoof vector on roofs only, delete weatherRoofSheetWaves, and stay well within 224/16',()=>{
 const renderer=new Renderer(),scene=new THREE.Scene();
 renderer.toneMapping=THREE.ACESFilmicToneMapping;
 renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFShadowMap;
 scene.environment=new THREE.Texture();
 const haze=installStageHaze(scene,{}),shadow=installCloudShadow(scene,{uniforms:createCloudUniforms()}),layer=installWeatherSurface(scene);
 const stressLights=makeLights();
 stressLights.directional=[{},{}];stressLights.directionalShadowMap=[{}];
 stressLights.point=Array.from({length:4},()=>({}));stressLights.pointShadowMap=[{},{}];
 stressLights.spot=[{},{}];stressLights.spotShadowMap=[{},{}];
 stressLights.rectArea=[{}];stressLights.hemi=[{}];
 const cache=programs(renderer);
 const cases=[
  ['roof Standard',new THREE.MeshStandardMaterial({name:'roof',metalness:.45,roughness:.45})],
  ['roof Physical',new THREE.MeshPhysicalMaterial({name:'roof',metalness:.45,roughness:.45})],
  ['roof Lambert',new THREE.MeshLambertMaterial({name:'roof'})],
  ['roof Phong',new THREE.MeshPhongMaterial({name:'roof'})],
  ['roof Toon',new THREE.MeshToonMaterial({name:'roof'})],
  ['roof role mapped',Object.assign(new THREE.MeshStandardMaterial({name:'standing_seam',map:new THREE.Texture(),normalMap:new THREE.Texture(),roughnessMap:new THREE.Texture(),aoMap:new THREE.Texture()}),{userData:{materialRole:'roof'}})],
 ];
 const roofBaked=new THREE.MeshStandardMaterial({name:'roof',metalness:.45,roughness:.45,map:new THREE.Texture(),normalMap:new THREE.Texture(),roughnessMap:new THREE.Texture(),aoMap:new THREE.Texture()});
 patchLightmaps([roofBaked],{banks:Array.from({length:2},()=>new THREE.DataArrayTexture(new Uint8Array(64),4,4,1))},lightmapUniforms(1,8,{fixtures:true}));
 cases.push(['roof baked 2-bank 8-lamp stress',roofBaked]);
 const budgets=[];
 for(const [label,mat] of cases){
  const o=new THREE.Mesh(new THREE.BoxGeometry(),mat);o.receiveShadow=true;scene.add(o);
  haze.prepare();shadow.prepare();layer.prepare();
  const src=programSource(renderer,cache,scene,o,stressLights);
  assert.ok(!src[2].includes('#include'),label+' expanded all includes');
  const f=preprocess(src[2]);
  checkGlslScopes(f,label);
  assert.ok(f.includes('uniform vec4 weatherRoof;'),label+' declares weatherRoof');
  assert.ok(!f.includes('weatherRoofSheetWaves'),label+' deleted weatherRoofSheetWaves');
  if(mat.isMeshStandardMaterial||mat.isMeshPhongMaterial){
   assert.ok(f.includes('weatherRoofRivulets(')&&f.includes('weatherRoofFilm(')&&f.includes('weatherRoofBeads('),label+' uses roof rivulets, moving water film and beads');
  }
  assert.ok(!f.includes('weatherPuddle(weatherUp'),label+' excludes puddles');
  const b=uniformBudget(src[2]);
  assert.ok(b.vectors<=224,`${label} vectors ${b.vectors} > 224`);
  assert.ok(b.samplers.length<=16,`${label} samplers ${b.samplers.length} > 16`);
  budgets.push({label,vectors:b.vectors,samplers:b.samplers.length});
 }
 assert.equal(budgets[0].vectors,183,'roof Standard stress vectors (+1 for weatherRoof)');
 assert.equal(budgets[5].vectors,189,'roof mapped stress vectors (+1 for weatherRoof)');
 assert.equal(budgets[6].vectors,192,'roof baked 2-bank 8-lamp stress vectors (+1 for weatherRoof)');
 console.log('ROOF_BUDGETS',JSON.stringify(budgets));
 layer.dispose();shadow.dispose();haze.dispose();
});

await test('non-roof programs compile without roof code or weatherRoof; water/sheet/submerged/effect match 7a23b5f1 except the 64 s clock literal',async()=>{
 const assembleSet=(installFn)=>{
  const renderer=new Renderer(),scene=new THREE.Scene();
  renderer.toneMapping=THREE.ACESFilmicToneMapping;scene.environment=new THREE.Texture();
  const haze=installStageHaze(scene,{}),shadow=installCloudShadow(scene,{uniforms:createCloudUniforms()}),layer=installFn(scene);
  const lights=makeLights();lights.directional=[{},{}];lights.hemi=[{}];
  const cache=programs(renderer);
  const items=[
   ['solid',new THREE.MeshStandardMaterial({name:'siding'}),'weather-surface-solid-1',false],
   ['lawn',new THREE.MeshStandardMaterial({name:'lawn'}),'weather-surface-lawn-1',false],
   ['grass',grassMaterial(new THREE.MeshStandardMaterial()),'weather-surface-lawn-1',true],
   ['water',surfaceMaterial(new THREE.MeshPhysicalMaterial()).material,'weather-surface-water-1',false],
   ['sheet',sheetMaterial(),'weather-surface-water-1',false],
   ['submerged',underwaterMaterial(new THREE.MeshStandardMaterial(),{height:0}).material,'weather-surface-submerged-1',false],
   ['effect',waterMaterial(),'weather-surface-effect-1',false],
  ];
  const out={};
  for(const [label,mat,expectedTag,inst] of items){
   const o=inst?new THREE.InstancedMesh(new THREE.BoxGeometry(),mat,1):new THREE.Mesh(new THREE.BoxGeometry(),mat);
   scene.add(o);haze.prepare();shadow.prepare();layer.prepare();
   const src=programSource(renderer,cache,scene,o,lights);
   const b=uniformBudget(src[2]);
   assert.ok(!src.shader.uniforms.weatherRoof,`${label} must not bind weatherRoof uniform`);
   out[label]={expectedTag,customKey:mat.customProgramCacheKey(),key:src.key,vsPre:preprocess(src[1]),fsPre:preprocess(src[2]),vectors:b.vectors,samplers:b.samplers.length};
  }
  layer.dispose();shadow.dispose();haze.dispose();
  return out;
 };

 const branch=assembleSet(installWeatherSurface);
 for(const [label,row] of Object.entries(branch)){
  assert.ok(row.key.includes(row.expectedTag),`${label} key retains ${row.expectedTag}`);
  checkGlslScopes(row.fsPre,label);
  for(const forbidden of ['weatherRoof','weatherRoofRivulets','weatherRoofFilm','weatherRoofSheetWaves','weatherRoofBeads','roofAcrossDir','roofDownDir','roofNormalOff']){
   assert.ok(!row.fsPre.includes(forbidden),`${label} preprocessed source must not contain ${forbidden}`);
  }
  if(['water','sheet','submerged','effect'].includes(label)){
   for(const forbidden of ['weatherPorosity','weatherDarkenWet','weatherWetRoughness','weatherWaterFilm']){
    assert.ok(!row.fsPre.includes(forbidden),`${label} water/submerged/effect must not include porosity/film helpers`);
   }
  }else{
   assert.ok(row.fsPre.includes('weatherPorosity(')&&row.fsPre.includes('weatherDarkenWet(')&&row.fsPre.includes('weatherWaterFilm('),`${label} uses shared porosity and dielectric film model`);
  }
  assert.ok(row.vectors<=224&&row.samplers<=16,label+' within budget');
 }

 if(input.mainSource){
  const withBranch={...THREE.ShaderChunk};
  try{
   Object.assign(THREE.ShaderChunk,BEFORE_WEATHER);
   const mainSrc=input.mainSource.replace("'./stage_haze.js'",JSON.stringify(file('static/twin/sky/stage_haze.js')));
   const mainMod=await import('data:text/javascript;base64,'+Buffer.from(mainSrc).toString('base64'));
   const main=assembleSet(mainMod.installWeatherSurface);
   const normClock=s=>s.replace('float clock=fract(weatherSurface.w)*64.0;','float clock=fract(weatherSurface.w)*4.0;');
   for(const label of Object.keys(branch)){
    assert.equal(branch[label].customKey,main[label].customKey,`${label} customProgramCacheKey matches main`);
    assert.equal(branch[label].vsPre,main[label].vsPre,`${label} vertex shader matches main byte-for-byte`);
    assert.equal(branch[label].vectors,main[label].vectors,`${label} uniform vectors match main`);
    assert.equal(branch[label].samplers,main[label].samplers,`${label} sampler count matches main`);
    if(['water','sheet','submerged','effect'].includes(label)){
     assert.equal(normClock(branch[label].fsPre),main[label].fsPre,`${label} fragment shader matches 7a23b5f1 except the 64 s clock multiplier`);
    }
   }
  }finally{
   Object.assign(THREE.ShaderChunk,withBranch);
  }
 }
});

const ev=buildEvaluators();

await test('64 s rain clock keeps puddle/pool ripple output identical to 4 s clock and preserves float32 rate precision',()=>{
 const layer=installWeatherSurface(new THREE.Scene());
 for(const sec of [0,0.37,1.9,3.99,4.0,7.13,19.4,32.0,63.95,64.0,127.8,259.25]){
  layer.update({wetness:1,puddles:1,rate:1,precip:'rain'},sec);
  const wNew=layer.uniforms.weatherSurface.value.w;
  const f32=Math.fround(wNew);
  assert.equal(Math.floor(f32),255,`float32 precision guard at sec=${sec}`);
  const age64=fract(fract(wNew)*64*3+0.317);
  const age4=fract(((sec%4+4)%4)*3+0.317);
  const diff=Math.min(Math.abs(age64-age4),1-Math.abs(age64-age4));
  assert.ok(diff<1e-6,`ripple phase identical at sec=${sec}: ${age64} vs ${age4}`);
  for(const pt of [v2(0.2,0.3),v2(1.1,0.8),v2(-0.7,1.4)]){
   const s64=ev.rippleAt({w:wNew},pt);
   const s4=ev.rippleAt({w:255+(((sec%4+4)%4)/64)},pt);
   close(s64.x,s4.x,1e-5);close(s64.y,s4.y,1e-5);
  }
 }
 layer.dispose();
});

await test('dry roof (wetness 0) matches dry output identically even while raining; snow cover wins over full wetness',()=>{
 const face=v3(0,Math.cos(0.4),Math.sin(0.4));
 const dx=v3(0.004,0,0),dy=v3(0,-0.002,0.003);
 for(const rate of [0,0.4,1])for(const phase of [0,0.37,0.89]){
  for(let i=0;i<25;i++){
   const world=v3(i*0.13-1.5,3.5-i*0.04,i*0.11);
   const r=ev.evalRoofApply({world,face,dxWorld:dx,dyWorld:dy,wet:0,snow:0,rate,phase,roughness:0.45,metalness:0.45,albedo:0.04});
   close(r.color.x,0.04);close(r.roughness,0.45);close(r.metalness,0.45);
   close(r.horizonDamp,1.0);
   close(r.normal.x,face.x);close(r.normal.y,face.y);close(r.normal.z,face.z);
  }
 }
 // Metal roof dried via roof drying ladder (weatherRoof=0) matches dry output even when ground weatherSurface.x=0.8.
 for(let i=0;i<15;i++){
  const world=v3(i*0.19,3.5,i*0.17);
  const dryMetal=ev.evalRoofApply({world,face,dxWorld:dx,dyWorld:dy,wet:0.8,snow:0,rate:0,phase:0.3,roughness:0.45,metalness:0.45,albedo:0.04,roofVec:{x:0,y:0,z:0,w:0}});
  close(dryMetal.color.x,0.04);close(dryMetal.roughness,0.45);close(dryMetal.metalness,0.45);
  close(dryMetal.horizonDamp,1.0);
  close(dryMetal.normal.x,face.x);close(dryMetal.normal.y,face.y);close(dryMetal.normal.z,face.z);
 }
 // Porous shingles retain darkening from ground wetness after metal roof has dried.
 const dampShingle=ev.evalRoofApply({world:v3(1.1,3.5,1.3),face,dxWorld:dx,dyWorld:dy,wet:0.8,snow:0,rate:0,phase:0.3,roughness:0.88,metalness:0.0,albedo:0.30,roofVec:{x:0,y:0,z:0,w:0}});
 assert.ok(dampShingle.color.x<0.24,`porous shingle retains darkening from ground wetness (${dampShingle.color.x.toFixed(3)})`);
 // Snow wins over full wetness.
 for(let i=0;i<25;i++){
  const world=v3(i*0.17,4.0,i*0.09);
  const s=ev.evalRoofApply({world,face,dxWorld:dx,dyWorld:dy,wet:1,snow:1,rate:1,phase:0.5,roughness:0.45,metalness:0.45,albedo:0.04});
  close(s.color.x,0.85,1e-5);close(s.color.y,0.87,1e-5);close(s.color.z,0.90,1e-5);
  close(s.roughness,0.7);close(s.metalness,0.0);
  close(s.horizonDamp,1.0);
  close(s.normal.x,face.x);close(s.normal.y,face.y);close(s.normal.z,face.z);
 }
});

await test('moving water film: no periodic banding along slope, moves downhill over time, random 2D distortion, spatial lane variation, advected drop rings, and seamless 64 s wrap',()=>{
 // 1. Sample down the slope at 4 mm steps over 2.4 m (600 samples) across several x tracks:
 // verify NO periodic wave banding (low autocorrelation past the ~4 cm micro-feature scale,
 // non-regular sign-run lengths, and balanced 2D across/down slopes — not horizontal roll-wave stripes).
 let maxPeriodicCorr=0,sumAcross=0,sumDown=0;
 const runLengths=[];
 for(const x of [0.17,0.83,1.59]){
  const ys=[];
  for(let i=0;i<600;i++){
   const s=ev.roofFilm(v2(x,i*0.004),1.0,1.0,0.23,0.005);
   ys.push(s.y);sumAcross+=Math.abs(s.x);sumDown+=Math.abs(s.y);
  }
  const mean=ys.reduce((a,b)=>a+b,0)/ys.length;
  const varY=ys.reduce((a,v)=>a+(v-mean)*(v-mean),0)/ys.length;
  assert.ok(varY>1e-4,`film has active micro-ripple slope variance (${varY.toFixed(5)})`);
  // Autocorrelation at lags 6 cm .. 60 cm (where periodic 10-30 cm roll waves would peak > 0.4).
  for(let lag=15;lag<=150;lag++){
   let cov=0;
   for(let i=0;i<ys.length-lag;i++)cov+=(ys[i]-mean)*(ys[i+lag]-mean);
   const r=Math.abs(cov/((ys.length-lag)*varY));
   if(r>maxPeriodicCorr)maxPeriodicCorr=r;
  }
  // Measure sign-run lengths: irregular random micro-ripples have high variance in run lengths.
  let cur=1;
  for(let i=1;i<ys.length;i++){
   if(Math.sign(ys[i])===Math.sign(ys[i-1]))cur++;
   else{runLengths.push(cur*0.004);cur=1;}
  }
 }
 const meanRun=runLengths.reduce((a,b)=>a+b,0)/runLengths.length;
 const stdRun=Math.sqrt(runLengths.reduce((a,v)=>a+(v-meanRun)*(v-meanRun),0)/runLengths.length);
 assert.ok(maxPeriodicCorr<0.32,`no periodic banding along slope (max autocorr at 6-60 cm = ${maxPeriodicCorr.toFixed(3)})`);
 assert.ok(stdRun/meanRun>0.50,`irregular sign-run lengths (CV=${(stdRun/meanRun).toFixed(2)}, mean=${(meanRun*100).toFixed(2)}cm)`);
 const aspect=sumDown/sumAcross;
 assert.ok(aspect>0.8&&aspect<2.0,`balanced 2D micro-ripple distortion, not 1D roll-wave bands (down/across=${aspect.toFixed(2)})`);

 // 2. Film moves strictly downhill (+uv.y) over time.
 let errDown=0,errUp=0,errStatic=0;
 const dPhase=0.0005,dtSec=dPhase*64,shiftM=0.50*dtSec;
 for(let i=0;i<300;i++){
  const p=v2((i%20)*0.07+0.3,Math.floor(i/20)*0.07+0.2);
  const a=ev.roofFilm(p,1.0,0.0,0.31,0.005);
  const bDown=ev.roofFilm(v2(p.x,p.y+shiftM),1.0,0.0,0.31+dPhase,0.005);
  const bUp=ev.roofFilm(v2(p.x,p.y-shiftM),1.0,0.0,0.31+dPhase,0.005);
  const bStat=ev.roofFilm(p,1.0,0.0,0.31+dPhase,0.005);
  errDown+=Math.hypot(bDown.x-a.x,bDown.y-a.y);
  errUp+=Math.hypot(bUp.x-a.x,bUp.y-a.y);
  errStatic+=Math.hypot(bStat.x-a.x,bStat.y-a.y);
 }
 assert.ok(errDown<errUp*0.65&&errDown<errStatic*0.75,`film moves downhill over time (down=${errDown.toFixed(2)} < stat=${errStatic.toFixed(2)} < up=${errUp.toFixed(2)})`);

 // 3. Two-phase cross-fade continuity across cycle resets (no pop at phase = k/48, k/80, k/112).
 let maxJump=0;
 for(const resetPh of [0,1/48,0.5/48,1/80,1/112,0.5]){
  for(let i=0;i<30;i++){
   const p=v2(i*0.09,i*0.13);
   const before=ev.roofFilm(p,1.0,0.0,fract(resetPh-1e-6+1),0.005);
   const after=ev.roofFilm(p,1.0,0.0,fract(resetPh+1e-6),0.005);
   maxJump=Math.max(maxJump,Math.hypot(after.x-before.x,after.y-before.y));
  }
 }
 assert.ok(maxJump<0.01,`two-phase flow cross-fade has zero reset pop (maxJump=${maxJump.toFixed(5)})`);

 // 4. Large-scale (metres) spatial variation across roof patches.
 const patchRms=[];
 for(let px=0;px<4;px++)for(let py=0;py<4;py++){
  let sq=0;
  for(let i=0;i<40;i++){
   const p=v2(px*1.1+(i%8)*0.04,py*1.3+Math.floor(i/8)*0.04);
   const s=ev.roofFilm(p,1.0,0.0,0.4,0.005);
   sq+=s.x*s.x+s.y*s.y;
  }
  patchRms.push(Math.sqrt(sq/40));
 }
 assert.ok(Math.max(...patchRms)>Math.min(...patchRms)*1.35,`metre-scale variation modulates film strength (${Math.min(...patchRms).toFixed(3)}..${Math.max(...patchRms).toFixed(3)})`);

 // 5. Advected tiny drop-impact rings contribute when rate > 0.
 let ringDiff=0;
 for(let i=0;i<400;i++){
  const p=v2((i%20)*0.021,Math.floor(i/20)*0.021);
  const noRing=ev.roofFilm(p,1.0,0.0,0.37,0.005);
  const withRing=ev.roofFilm(p,1.0,1.0,0.37,0.005);
  ringDiff+=Math.hypot(withRing.x-noRing.x,withRing.y-noRing.y);
 }
 assert.ok(ringDiff>1.0,`advected drop-impact rings feed into film when raining (diff=${ringDiff.toFixed(2)})`);

 // 6. Low amplitude keeps roof normal map dominant (RMS tilt well under 0.15).
 let sqAll=0,maxAmp=0;
 for(let i=0;i<500;i++){
  const p=v2((i%25)*0.05,Math.floor(i/25)*0.05);
  const s=ev.roofFilm(p,1.0,1.0,0.29,0.005);
  const m=Math.hypot(s.x,s.y);sqAll+=m*m;if(m>maxAmp)maxAmp=m;
 }
 const rmsAmp=Math.sqrt(sqAll/500);
 assert.ok(rmsAmp>0.02&&rmsAmp<0.16,`film amplitude subtle and lively (rms=${rmsAmp.toFixed(4)}, max=${maxAmp.toFixed(4)})`);

 // 7. Seamless 64 s clock wrap across rivulets, film and beads.
 let wrapErr=0;
 for(let i=0;i<120;i++){
  const p=v2((i%20)*0.11,Math.floor(i/20)*0.37);
  const r0=ev.rivulets(p,0.9,0.4,0,1,1),r1=ev.rivulets(p,0.9,0.4,1,1,1);
  const f0=ev.roofFilm(p,1.0,1.0,0,0.005),f1=ev.roofFilm(p,1.0,1.0,1,0.005);
  const b0=ev.beads(p,0.9,0.4,0,1,1),b1=ev.beads(p,0.9,0.4,1,1,1);
  wrapErr=Math.max(wrapErr,Math.abs(r1.x-r0.x),Math.abs(r1.y-r0.y),Math.abs(r1.z-r0.z),
   Math.abs(f1.x-f0.x),Math.abs(f1.y-f0.y),Math.abs(b1.x-b0.x),Math.abs(b1.y-b0.y),Math.abs(b1.z-b0.z));
 }
 assert.ok(wrapErr<1e-5,`64-second clock wrap is seamless (${wrapErr})`);
 console.log('FILM_METRICS',JSON.stringify({maxPeriodicCorr:+maxPeriodicCorr.toFixed(3),aspect:+aspect.toFixed(2),rmsAmp:+rmsAmp.toFixed(4),errDown:+errDown.toFixed(2),errUp:+errUp.toFixed(2)}));
});

await test('streams start at scattered 2D positions (no fixed column lattice), have finite length with pool->stretch->detach lifecycle, and zero periodic normal banding',()=>{
 for(const azDeg of [0,35,120,245,357.6])for(const pitchRatio of [4/12,6/12,10/12]){
  const az=azDeg*Math.PI/180,pitch=Math.atan(pitchRatio);
  const face=v3(Math.sin(pitch)*Math.cos(az),Math.cos(pitch),Math.sin(pitch)*Math.sin(az));
  const out=ev.evalRoofApply({world:v3(2,4,-3),face,dxWorld:v3(0.003,0,0),dyWorld:v3(0,0,0.003),wet:1,rate:0.4,phase:0.2});
  close(len(out.acrossDir),1,1e-5);close(len(out.downDir),1,1e-5);
  close(dot(out.acrossDir,face),0,1e-5);close(dot(out.downDir,face),0,1e-5);
  close(dot(out.acrossDir,out.downDir),0,1e-5);
  assert.ok(out.downDir.y<-0.1,'downDir points strictly downhill');
  close(out.acrossDir.y,0,1e-5);
 }
 const bins30=Array(10).fill(0),bins44=Array(10).fill(0);
 for(let row=-30;row<30;row++)for(let ix=-10;ix<10;ix++){
  const h=ev.hash(v2(ix,row));
  const shift=fract(row*0.381966);
  const u0=(ix+0.24+0.52*h.x-shift)*0.30;
  bins30[Math.floor(fract(u0/0.30)*10)]++;
  bins44[Math.floor(fract(u0/0.44)*10)]++;
 }
 const mean=1200/10;
 assert.ok(bins30.every(n=>Math.abs(n-mean)<mean*0.25),`origins spread uniformly across 0.30m period (${JSON.stringify(bins30)})`);
 assert.ok(bins44.every(n=>Math.abs(n-mean)<mean*0.25),`origins spread uniformly across 0.44m period (${JSON.stringify(bins44)})`);

 const row=1,ix=2,h=ev.hash(v2(ix,row));
 const shift=fract(row*0.381966);
 const u0=(ix+0.24+0.52*h.x-shift)*0.30;
 const v0=(row+0.03+0.94*h.y)*2.4;
 const hz6=h.z*6.0,h2=fract(hz6),cycles=5+Math.floor(hz6);
 const pathAt=dy=>{
  const py=Math.max(0,dy);
  const wx=fract(py*(0.50+0.50*h.x))-0.5,wy=fract(py*(1.10+0.90*h.y))-0.5;
  return u0+wx*(0.5-Math.abs(wx))*(h.x*1.15-0.575)+wy*(0.5-Math.abs(wy))*(h.y*0.65-0.325);
 };
 const phaseForTau=targetTau=>fract((targetTau-h2+10)/cycles);
 const pPool=phaseForTau(0.16);
 assert.ok(ev.rivulets(v2(u0,v0),0.9,0.4,pPool,1,1).z>0.4,'swelling pool present at origin before release');
 assert.ok(ev.rivulets(v2(pathAt(0.6),v0+0.6),0.9,0.4,pPool,1,1).z<0.05,'no stream downhill before release');

 const pRun=phaseForTau(0.86);
 const runT=clamp((0.86-0.22)*1.28205,0,1),headY=runT*2.35;
 const streamLen=(0.75+0.95*h2)*(0.85+0.55*Math.min(0.4*2.2,1));
 const tailY=Math.max(0,headY-streamLen);
 const midY=(tailY+headY)*0.5;
 const midCenter=ev.rivulets(v2(pathAt(midY),v0+midY),0.9,0.4,pRun,1,1);
 const midRight=ev.rivulets(v2(pathAt(midY)+0.012,v0+midY),0.9,0.4,pRun,1,1);
 const midLeft=ev.rivulets(v2(pathAt(midY)-0.012,v0+midY),0.9,0.4,pRun,1,1);
 assert.ok(midCenter.z>0.7,`active stream body has strong coverage (${midCenter.z.toFixed(3)})`);
 assert.ok(ev.rivulets(v2(pathAt(headY+0.15),v0+headY+0.15),0.9,0.4,pRun,1,1).z<0.05,'stream terminates cleanly ahead of head');
 assert.ok(midRight.x>0.4&&midLeft.x<-0.4,`raised lens normal tilts strongly outward (L=${midLeft.x.toFixed(3)}, R=${midRight.x.toFixed(3)})`);

 let signFlipsY=0,prevSignY=0;
 const yStart=tailY+0.25,yEnd=headY-0.12;
 for(let i=0;i<=40;i++){
  const dy=yStart+(yEnd-yStart)*(i/40);
  const sample=ev.rivulets(v2(pathAt(dy)+0.011,v0+dy),0.9,0.4,pRun,1,1);
  const sy=Math.abs(sample.y)>0.01?Math.sign(sample.y):0;
  if(sy!==0&&prevSignY!==0&&sy!==prevSignY)signFlipsY++;
  if(sy!==0)prevSignY=sy;
 }
 assert.equal(signFlipsY,0,`zero periodic normal banding along stream body (flips=${signFlipsY})`);
});

await test('rain levels and drying ladder: light has zero film, steady moderate film, heavy full film; rate=0 with flow>0 keeps streams running, flow=0 freezes, trails fade before beads',()=>{
 const face=v3(0,0.894,0.447),dx=v3(0.005,0,0),dy=v3(0,0,0.005);

 // 1. Rate=0 with flow>0 (early post-rain drain): clock STILL runs so in-flight streams move and finish!
 let drainMotion=0;
 for(let i=0;i<160;i++){
  const world=v3((i%16)*0.13,4.0,Math.floor(i/16)*0.23);
  const a=ev.evalRoofApply({world,face,dxWorld:dx,dyWorld:dy,wet:0.98,rate:0,phase:0.10,roofVec:{x:0.98,y:0.45,z:0.10,w:0.95}});
  const b=ev.evalRoofApply({world,face,dxWorld:dx,dyWorld:dy,wet:0.98,rate:0,phase:0.25,roofVec:{x:0.98,y:0.45,z:0.10,w:0.95}});
  drainMotion+=Math.abs(b.riv.z-a.riv.z)+Math.hypot(b.normal.x-a.normal.x,b.normal.y-a.normal.y);
 }
 assert.ok(drainMotion>1.5,`rate=0 with flow>0 keeps streams moving to finish (${drainMotion.toFixed(2)})`);

 // 2. Flow=0 (after runoff finishes / static beads): strictly ZERO time dependence!
 let stopDiff=0,stopFilm=0,cov20m=0,cov30m=0,trail20m=0,trailStatic=0;
 for(let i=0;i<400;i++){
  const world=v3((i%40)*0.025,4.0,Math.floor(i/40)*0.23);
  const s0=ev.evalRoofApply({world,face,dxWorld:dx,dyWorld:dy,wet:0.8,rate:0,phase:0.05,roofVec:{x:0.8,y:0,z:0,w:0.5}});
  const s1=ev.evalRoofApply({world,face,dxWorld:dx,dyWorld:dy,wet:0.8,rate:0,phase:0.73,roofVec:{x:0.8,y:0,z:0,w:0.5}});
  const d20=ev.evalRoofApply({world,face,dxWorld:dx,dyWorld:dy,wet:0.9,rate:0,phase:0.05,roofVec:{x:0.5,y:0,z:0,w:0}});
  const d30=ev.evalRoofApply({world,face,dxWorld:dx,dyWorld:dy,wet:0.85,rate:0,phase:0.05,roofVec:{x:0.16,y:0,z:0,w:0}});
  stopDiff+=Math.abs(s1.riv.z-s0.riv.z)+Math.abs(s1.bead.z-s0.bead.z)+Math.abs(s1.normal.x-s0.normal.x)+Math.abs(s1.normal.y-s0.normal.y)+Math.abs(s1.roughness-s0.roughness);
  stopFilm+=Math.hypot(s0.filmSlope.x,s0.filmSlope.y);
  trailStatic+=s0.riv.z;trail20m+=d20.riv.z;
  cov20m+=d20.bead.z;cov30m+=d30.bead.z;
 }
 assert.equal(stopDiff,0,'flow=0 has strictly zero time dependence');
 assert.equal(stopFilm,0,'flow=0 has zero film');
 assert.equal(trail20m,0,'damp trails are gone at dry20m (trail=0)');
 assert.ok(trailStatic>0.15,`static damp trails exist when trail>0 (${trailStatic.toFixed(3)})`);
 assert.ok(cov20m>cov30m*2.0&&cov20m>5,'beads thin and shrink from 20m to 30m');

 // 3. Rain-level progression across light -> steady -> hard.
 const statsAt=(rate,wet,phase=0.3)=>{
  let rivCov=0,beadCov=0,waterCov=0,filmMag=0,rough=0;
  const N=300;
  for(let i=0;i<N;i++){
   const world=v3((i%20)*0.09,4.0,Math.floor(i/20)*0.17);
   const f=ev.evalRoofApply({world,face,dxWorld:dx,dyWorld:dy,wet,rate,phase});
   rivCov+=f.riv.z;beadCov+=f.bead.z;waterCov+=f.waterCov;
   filmMag+=Math.hypot(f.filmSlope.x,f.filmSlope.y);rough+=f.roughness;
  }
  return {rivCov:rivCov/N,beadCov:beadCov/N,waterCov:waterCov/N,filmMag:filmMag/N,rough:rough/N};
 };
 const light=statsAt(0.12,0.55),steady=statsAt(0.40,0.90),hard=statsAt(1.0,1.0);
 assert.ok(steady.rivCov>light.rivCov*1.5,`steady rain has more active streams than light (${steady.rivCov.toFixed(4)} vs ${light.rivCov.toFixed(4)})`);
 assert.ok(light.beadCov>0.015&&steady.beadCov>light.beadCov*1.5,`beads grow larger from light to steady rain (${light.beadCov.toFixed(4)} -> ${steady.beadCov.toFixed(4)})`);
 assert.ok(hard.beadCov<steady.beadCov*0.20,`hard rain washes out beads (${hard.beadCov.toFixed(4)} vs ${steady.beadCov.toFixed(4)})`);
 assert.equal(light.filmMag,0,'light rain has zero film');
 assert.ok(steady.filmMag>0.01&&steady.filmMag<hard.filmMag*0.6,`steady rain has moderate film between rivulets (${steady.filmMag.toFixed(4)} vs hard ${hard.filmMag.toFixed(4)})`);
 assert.ok(hard.waterCov>0.75&&hard.rough<0.07,`hard rain covers roof in moving film (cov=${hard.waterCov.toFixed(3)}, rough=${hard.rough.toFixed(4)})`);
 assert.ok(hard.filmMag>0.04,`hard rain produces active moving water film (mag=${hard.filmMag.toFixed(4)})`);
 console.log('RAIN_LEVELS',JSON.stringify({light,steady,hard}));
});

await test('bright bare metals keep metalness and diffuse when wet; dark painted roofs still get untinted dielectric film; light roofs stay bounded',()=>{
 const conduitDry=ev.evalSolidApply({albedo:0.415,metalness:0.60,roughness:0.45,wet:0});
 const conduitWet=ev.evalSolidApply({albedo:0.415,metalness:0.60,roughness:0.45,wet:1});
 close(conduitWet.metalness,0.60,1e-4);
 const conduitDiffDry=conduitDry.color.x*(1-conduitDry.metalness);
 const conduitDiffWet=conduitWet.color.x*(1-conduitWet.metalness);
 assert.ok(Math.abs(conduitDiffWet-conduitDiffDry)<0.01,`galvanized conduit keeps diffuse (${conduitDiffDry.toFixed(3)} -> ${conduitDiffWet.toFixed(3)})`);
 close(ev.evalSolidApply({albedo:0.38,metalness:0.65,roughness:0.45,wet:1}).metalness,0.65,1e-4);
 close(ev.evalSolidApply({albedo:0.35,metalness:0.85,roughness:0.35,wet:1}).metalness,0.85,1e-4);

 const face=v3(0,0.894,0.447);
 const brightMetalRoof=ev.evalRoofApply({world:v3(1.1,4,1.3),face,wet:1,rate:0,roughness:0.35,metalness:0.65,albedo:0.42});
 close(brightMetalRoof.metalness,0.65,1e-4);
 assert.ok(brightMetalRoof.horizonDamp<=1.01,`bright metal roof is not sheen-boosted (${brightMetalRoof.horizonDamp.toFixed(3)})`);

 const darkBronze=[0.042,0.027,0.020];
 const darkRoof=ev.evalRoofApply({world:v3(1.1,4,1.3),face,wet:1,rate:1,phase:0.3,roughness:0.45,metalness:0.45,albedo:darkBronze});
 assert.ok(darkRoof.metalness<0.05,`dark painted metal roof drops metalness under water film (0.45 -> ${darkRoof.metalness.toFixed(4)})`);
 const f0Dry=darkBronze.map(c=>mix(0.04,c,0.45));
 const f0Wet=darkBronze.map(c=>mix(0.04,c,darkRoof.metalness));
 const chroma=rgb=>Math.max(...rgb)-Math.min(...rgb);
 const luma=rgb=>rgb[0]*0.2126+rgb[1]*0.7152+rgb[2]*0.0722;
 assert.ok(chroma(f0Wet)<chroma(f0Dry)*0.15,'wet dark metal roof specular F0 is untinted (near-grey)');
 assert.ok(luma(f0Wet)>luma(f0Dry)*1.10,'wet dark metal roof dielectric F0 is brighter than tinted F0');

 for(const [name,albedo,roughness] of [['white membrane',0.82,0.28],['glazed tile',0.48,0.18],['light stucco roof',0.55,0.35]]){
  for(const viewDir of [v3(0,0.45,0.89),v3(0,0.08,0.997),v3(0,0.85,0.52)]){
   const lightRoof=ev.evalRoofApply({world:v3(0.7,4,1.1),face,wet:1,rate:0,roughness,metalness:0.0,albedo,viewDir});
   assert.ok(lightRoof.horizonDamp<=1.01,`${name} residual wetness under bright sky stays bounded (${lightRoof.horizonDamp.toFixed(3)})`);
   close(lightRoof.coatWeight,0,1e-5);
  }
 }
 assert.ok(ev.evalSolidApply({albedo:0.04,metalness:0.45,roughness:0.45,wet:1}).metalness<0.05,'dark painted solid trim gets dielectric film');
 close(ev.evalSolidApply({albedo:0.415,metalness:0.60,roughness:0.45,wet:1,snow:1}).metalness,0,1e-4);
});

await test('shared porosity: ordering, darkening, gloss, porous shingle vs metal roof',()=>{
 const pMetal=ev.porosityFn(1.0,0.45),pTile=ev.porosityFn(0.0,0.45),pMetalRoof=ev.porosityFn(0.45,0.45),pConcrete=ev.porosityFn(0.0,0.85),pShingle=ev.porosityFn(0.0,0.90);
 assert.ok(pMetal<pTile&&pTile<pConcrete,'porosity ordering: metal < semi-smooth tile < rough concrete');
 assert.ok(pMetalRoof<0.15&&pConcrete>=0.99&&pShingle>=0.99,'painted metal low porosity, concrete/shingles high');
 const face=v3(0,0.894,0.447),dx=v3(0.002,0,0),dy=v3(0,0,0.002);
 let metalRiv=0,shingleRiv=0,metalFilm=0,shingleFilm=0,metalBead=0,shingleBead=0,metalRough=0,shingleRough=0,shingleDark=0,metalDark=0,metalEffSum=0;
 for(let i=0;i<240;i++){
  const world=v3((i%24)*0.07,4.0,Math.floor(i/24)*0.11);
  const rm=ev.evalRoofApply({world,face,dxWorld:dx,dyWorld:dy,wet:0.9,rate:0.4,phase:0.3,roughness:0.45,metalness:0.45,albedo:0.06});
  const rs=ev.evalRoofApply({world,face,dxWorld:dx,dyWorld:dy,wet:0.9,rate:0.4,phase:0.3,roughness:0.88,metalness:0.0,albedo:0.30});
  const rmH=ev.evalRoofApply({world,face,dxWorld:dx,dyWorld:dy,wet:1.0,rate:1.0,phase:0.3,roughness:0.45,metalness:0.45,albedo:0.06});
  const rsH=ev.evalRoofApply({world,face,dxWorld:dx,dyWorld:dy,wet:1.0,rate:1.0,phase:0.3,roughness:0.88,metalness:0.0,albedo:0.30});
  metalRiv+=rm.riv.z;shingleRiv+=rs.riv.z;
  metalFilm+=Math.hypot(rmH.filmSlope.x,rmH.filmSlope.y);shingleFilm+=Math.hypot(rsH.filmSlope.x,rsH.filmSlope.y);
  metalBead+=rm.bead.z;shingleBead+=rs.bead.z;
  metalRough+=rm.roughness;shingleRough+=rs.roughness;
  metalDark+=1-rm.color.x/0.06;shingleDark+=1-rs.color.x/0.30;
  metalEffSum+=rm.metalness;
 }
 assert.ok(metalEffSum/240<0.05,`wet dark metal roof effective metalness drops (${(metalEffSum/240).toFixed(4)})`);
 assert.ok(shingleRiv<metalRiv*0.25,`rivulets much fainter on porous shingles (${shingleRiv.toFixed(2)} vs ${metalRiv.toFixed(2)})`);
 assert.ok(shingleFilm<metalFilm*0.20,`water film much fainter on porous shingles (${shingleFilm.toFixed(2)} vs ${metalFilm.toFixed(2)})`);
 assert.equal(shingleBead,0,'beads soak into porous shingle roof');
 assert.ok(metalBead>5,'beads remain on impervious metal roof');
 assert.ok(shingleRough/240>0.32&&metalRough/240<0.15,`porous roof keeps soft sheen (${(shingleRough/240).toFixed(3)}) vs glossy metal (${(metalRough/240).toFixed(3)})`);
 assert.ok(shingleDark/240>metalDark/240*2,'porous shingle roof darkens significantly more than metal roof');
 console.log('POROSITY_ROOF',JSON.stringify({metalEff:+(metalEffSum/240).toFixed(4),metalRough:+(metalRough/240).toFixed(3),shingleRough:+(shingleRough/240).toFixed(3),metalRiv:+metalRiv.toFixed(2),shingleRiv:+shingleRiv.toFixed(2)}));
});

await test('beads stay at wetness=1 on roofs only, embossed normal map does not inject fake runnels, and near-flat roofs have zero basis jump',()=>{
 const dx=v2(0.001,0),dy=v2(0,0.001);
 let roofBeadCov=0,roofBeadSlope=0,solidDropSum=0,hits=0;
 const face=v3(0,0.894,0.447);
 for(let i=0;i<600;i++){
  const u=(i%30)*0.043,v=Math.floor(i/30)*0.047;
  const b=ev.beads(v2(u,v),1,0.4,0.3,1,1);
  roofBeadCov+=b.z;roofBeadSlope+=Math.hypot(b.x,b.y);
  if(b.z>0.5)hits++;
  solidDropSum+=ev.solidDrops(v2(u,v),1,dx,dy,face.y);
 }
 assert.equal(solidDropSum,0,'non-roof surfaces still remove drop stains at wetness=1');
 assert.ok(hits>30&&roofBeadCov/600>0.04,`beads remain present on roofs at wetness=1 steady rain (hits=${hits}, avg=${(roofBeadCov/600).toFixed(4)})`);
 assert.ok(roofBeadSlope/600>0.01,'beads perturb normals as raised domes');

 const flatPan=ev.evalRoofApply({world:v3(0.11,4,0.3),face,dxWorld:v3(0.01,0,0),dyWorld:v3(0,0,0.01),wet:1,rate:0.4,phase:0.2,roughness:0.88,metalness:0.0,albedo:0.25});
 const embossed=ev.evalRoofApply({world:v3(0.11,4,0.3),face,mapNormal:v3(0.35,0.85,0.39),dxWorld:v3(0.01,0,0),dyWorld:v3(0,0,0.01),wet:1,rate:0.4,phase:0.2,roughness:0.88,metalness:0.0,albedo:0.25});
 close(embossed.roughness,flatPan.roughness,1e-6);

 const flat=ev.evalRoofApply({world:v3(1.2,4,2.3),face:v3(0,1,0),dxWorld:v3(0.001,0,0),dyWorld:v3(0,0,0.001),wet:1,rate:1,phase:0.5});
 assert.ok([flat.roughness,flat.color.x,flat.horizonDamp,flat.normal.x,flat.normal.y,flat.normal.z].every(Number.isFinite),'flat roof stays finite');
 close(flat.riv.z,0);close(flat.filmSlope.x,0);close(flat.filmSlope.y,0);
 for(const azDeg of [0,90,180,270]){
  const az=azDeg*Math.PI/180;
  let prev=null,prevS=0;
  for(const s of [0,0.0005,0.0009,0.0011,0.002,0.01,0.019,0.021,0.025]){
   const f=v3(s*Math.cos(az),Math.sqrt(1-s*s),s*Math.sin(az));
   const cur=ev.evalRoofApply({world:v3(1.23,4,2.37),face:f,dxWorld:v3(0.003,0,0),dyWorld:v3(0,0,0.003),wet:1,rate:1,phase:0.3});
   assert.ok([cur.roughness,cur.horizonDamp,cur.normal.x,cur.normal.y,cur.normal.z].every(Number.isFinite));
   if(prev){
    const ds=s-prevS;
    if(s<=0.019)close(cur.roughness,prev.roughness,1e-5);
    const dh=Math.abs(cur.horizonDamp-prev.horizonDamp),dn=len(sub(cur.normal,prev.normal));
    const slopeLimit=s<=0.019?3.0:10.0;
    assert.ok(dh<20.0*ds+1e-3,`continuous near-flat horizonDamp at az=${azDeg} s=${s} (dh=${dh.toFixed(4)} ds=${ds})`);
    assert.ok(dn<slopeLimit*ds+1e-3,`continuous near-flat normal at az=${azDeg} s=${s} (dn=${dn.toFixed(4)} ds=${ds})`);
   }
   prev=cur;prevS=s;
  }
 }
});

await test('detail stays sharp at 1-1.5 cm/px mid distance and fades cleanly to constant average with zero normal shimmer at overview footprints',()=>{
 const sampleStats=(px)=>{
  const visRiv=clamp((0.048-px)*34.0,0,1),visBead=clamp((0.075-px)*22.2,0,1);
  const rivC=[],beadC=[];let rivSlope=0,beadSlope=0,filmSlope=0;
  for(let i=0;i<400;i++){
   const p=v2((i%40)*0.097,Math.floor(i/40)*0.173);
   const r=ev.rivulets(p,0.9,0.4,0.4,visRiv,1);
   const b=ev.beads(p,0.9,0.4,0.4,visBead,1);
   const f=ev.roofFilm(p,1.0,1.0,0.4,px);
   rivC.push(r.z);beadC.push(b.z);
   rivSlope+=Math.hypot(r.x,r.y);beadSlope+=Math.hypot(b.x,b.y);filmSlope+=Math.hypot(f.x,f.y);
  }
  const stat=arr=>{const m=arr.reduce((s,v)=>s+v,0)/arr.length;const v=arr.reduce((s,x)=>s+(x-m)*(x-m),0)/arr.length;return {mean:m,std:Math.sqrt(v)};};
  return {riv:stat(rivC),bead:stat(beadC),rivSlope:rivSlope/400,beadSlope:beadSlope/400,filmSlope:filmSlope/400};
 };
 const near=sampleStats(0.003),mid1cm=sampleStats(0.010),mid15cm=sampleStats(0.015),far=sampleStats(0.08);
 console.log('LOD_FILTER',JSON.stringify({near,mid1cm,mid15cm,far}));
 assert.ok(near.riv.std>0.06&&near.rivSlope>0.002,'near rivulets have strong contrast and lens tilt');
 assert.ok(near.bead.std>0.12&&near.beadSlope>0.01,'near beads have strong contrast and dome tilt');
 assert.ok(near.filmSlope>0.04,'near film has active micro-ripple distortion');
 assert.ok(mid1cm.riv.std>0.06&&mid1cm.rivSlope>0.002,'1 cm/px close-view rivulets retain full contrast');
 assert.ok(mid15cm.riv.std>0.06&&mid15cm.rivSlope>0.002,'1.5 cm/px upper-roof rivulets retain full contrast');
 assert.ok(mid1cm.filmSlope>0.025,'1 cm/px close-view film stays lively');
 assert.ok(far.riv.std<1e-6&&far.rivSlope<1e-6,'overview rivulets filter to exact constant average with zero normal shimmer');
 assert.ok(far.bead.std<1e-6&&far.beadSlope<1e-6,'overview beads filter to exact constant average with zero normal shimmer');
 assert.ok(far.filmSlope<1e-6,'overview water film filters cleanly to zero normal shimmer');
 assert.ok(far.riv.mean>0.01&&far.riv.mean<0.12,'overview rivulet average stays in calm coverage range');
 assert.ok(far.bead.mean>0.04&&far.bead.mean<0.20,'overview bead average stays in realistic coverage range');
});

finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'mainSource': main_weather_source()}, timeout=180)
    print(output)
    sys.exit(code)

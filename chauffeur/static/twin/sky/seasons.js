import * as THREE from 'three';
import { bindEnvironmentMaterial, frameObjects } from './stage_haze.js';

const finite = v => typeof v === 'number' && Number.isFinite(v);
const clamp = v => finite(v) ? Math.max(0, Math.min(1, v)) : 0;
const smooth = v => { v = clamp(v); return v*v*(3-2*v); };
const latitude = v => finite(v) && Math.abs(v)<=90 ? v : 40;

// Day numbers in a non-leap northern-equivalent year. In the south the
// starting dates shift six months; the transitions still last 21/14 days.
export function phenologyDates(lat=40) {
  const offset=(Math.abs(latitude(lat))-30)*1.5;
  const spring=Math.round(Math.max(60,Math.min(140,80+offset)));
  const autumn=Math.round(Math.max(240,Math.min(320,300-offset)));
  return {spring,autumn,drop:autumn+21,bare:autumn+35};
}
function phenologyCalendar(date,lat,dates) {
  const year=date.getUTCFullYear(),day=Date.UTC(year,date.getUTCMonth(),date.getUTCDate())/86400000;
  const anchor=(day,year)=>{
    const start=new Date(Date.UTC(2001,0,day));
    return Date.UTC(year,(start.getUTCMonth()+(lat<0?6:0))%12,start.getUTCDate())/86400000;
  };
  let spring=anchor(dates.spring,year),autumn=anchor(dates.autumn,year);
  // The leafy southern summer crosses New Year. Absolute civil day numbers
  // keep transitions exactly 21/14 days, including one spanning February 29.
  if(autumn<spring){
    if(day<spring)spring=anchor(dates.spring,year-1);
    else autumn=anchor(dates.autumn,year+1);
  }
  return {day,spring,autumn,drop:autumn+21,bare:autumn+35};
}
export function calendarDormancy(date,lat=40,grassType='cool') {
  lat=latitude(lat);
  if(Math.abs(lat)<23.5)return 0;
  const month=(date.getUTCMonth()+(lat<0?6:0))%12;
  if(grassType!=='warm')return month===0?.3:0;
  const start=Math.abs(lat)<35?10:Math.abs(lat)<50?9:8;
  const end=Math.abs(lat)<35?1:Math.abs(lat)<50?3:4;
  return month>=start||month<=end?1:0;
}
export function seasonState(date=new Date(),lat=40,ground={}, {neutral=false,preview=null}={}) {
  lat=latitude(lat);if(!Number.isFinite(+date))date=new Date();
  const dates=phenologyDates(lat),calendar=phenologyCalendar(date,lat,dates),{day}=calendar;
  const grassType=ground.lawn?.grass_type==='warm'?'warm':'cool';
  let presence=day<calendar.spring||day>=calendar.bare?0:day<calendar.spring+21?smooth((day-calendar.spring)/21)
    :day<calendar.drop?1:1-smooth((day-calendar.drop)/14);
  let autumn=smooth((day-calendar.autumn)/21),spring=presence>0&&day<calendar.spring+21?1-presence:0;
  const history=ground.lawn?.source==='history'&&!ground.source?.stale;
  let dormancy=finite(ground.lawn?.dormancy)&&(ground.lawn.source==='calendar'||!ground.source?.stale)?clamp(ground.lawn.dormancy):calendarDormancy(date,lat,grassType);
  if(neutral){presence=1;autumn=0;spring=0;dormancy=0;}
  if(preview==='spring'){presence=.5;autumn=0;spring=.5;dormancy=0;}
  if(preview==='summer'){presence=1;autumn=0;spring=0;dormancy=0;}
  if(preview==='autumn'){presence=1;autumn=.85;spring=0;dormancy=0;}
  if(preview==='winter'){presence=0;autumn=1;spring=0;dormancy=grassType==='warm'?1:.3;}
  return {presence,autumn,spring,dormancy,grassType,source:history?'history':'calendar',
    avgTempC:finite(ground.season?.avg_temp_c)?ground.season.avg_temp_c:null,
    historyDays:finite(ground.season?.history_days)?Math.max(0,ground.season.history_days):0,
    latitude:lat,dates,preview,neutral:neutral&&!preview};
}

const previewNames=['spring','summer','autumn','winter'];
export function createSeasonPreview(onChange,{setTimer=setTimeout,clearTimer=clearTimeout}={}) {
  let value=null,timer=null,deadline=null;
  const clear=()=>{clearTimer(timer);timer=null;deadline=null;};
  const set=name=>{
    if(name!==null&&!previewNames.includes(name))return;
    clear();value=name;
    if(value){deadline=Date.now()+120000;timer=setTimer(()=>set(null),120000);}
    onChange();
  };
  return {set,get:()=>value,get deadline(){return deadline;},stop(){clear();value=null;}};
}

export const PRESET_SEASONS=Object.freeze({
  'Ash Small':'deciduous','Ash Medium':'deciduous','Ash Large':'deciduous',
  'Aspen Small':'deciduous','Aspen Medium':'deciduous','Aspen Large':'deciduous',
  'Bush 1':'deciduous','Bush 2':'deciduous','Bush 3':'deciduous',
  'Oak Small':'deciduous','Oak Medium':'deciduous','Oak Large':'deciduous',
  'Pine Small':'evergreen','Pine Medium':'evergreen','Pine Large':'evergreen','Trellis':'deciduous',
});
export function plantSeason(preset,kind='tree') {
  // A known evergreen kind also tags an otherwise generic shrub preset.
  if(/\b(pine|spruce|fir|juniper|boxwood|holly)\b/i.test(kind))return 'evergreen';
  return PRESET_SEASONS[preset] || (/\b(pine|spruce|fir|juniper|boxwood|holly)\b/i.test(preset)?'evergreen':'deciduous');
}
export function seasonHash(value) {
  let n=2166136261;
  for(const c of String(value))n=Math.imul(n^c.charCodeAt(0),16777619);
  n=Math.imul(n^n>>>16,0x21f0aaad);n=Math.imul(n^n>>>15,0x735a2d97);
  return ((n^n>>>15)>>>0)/4294967296;
}

// Only explicit vegetation materials bind these snippets. No shared chunks,
// samplers, defines, or season-dependent program keys.
export const LAWN_GLSL=`
uniform float seasonDormancy;
varying vec2 vSeasonWorld;
float seasonPatch(vec2 world, int firstCorner) {
  vec2 point=world/1.8,cell=floor(point),blend=fract(point);
  blend=blend*blend*(3.0-2.0*blend);
  // The caller guarantees firstCorner == 0, through its dormancy range gates.
  // Give FXC a runtime loop start instead of four explicit sine hashes.
  vec4 noise=vec4(0.0);
  for(int corner=firstCorner;corner<4;corner++) {
    vec2 offset=vec2(float(corner-(corner/2)*2),float(corner/2));
    float value=fract(sin(dot(cell+offset,vec2(12.9898,78.233)))*43758.5453);
    noise+=vec4(equal(ivec4(0,1,2,3),ivec4(corner)))*value;
  }
  return mix(mix(noise.x,noise.y,blend.x),mix(noise.z,noise.w,blend.x),blend.y);
}
float seasonDry(float dormancy, float threshold) {
  return smoothstep(threshold*.84,threshold*.84+.16,clamp(dormancy,0.0,1.0));
}
vec3 seasonLawn(vec3 green) {
  if(seasonDormancy<=0.0) return green;
  float luminance=max(dot(green,vec3(.2126,.7152,.0722)),0.0);
  vec3 straw=vec3(.42,.34,.2)*(luminance/.3469);
  if(seasonDormancy>=1.0) return straw;
  return mix(green,straw,seasonDry(seasonDormancy,seasonPatch(vSeasonWorld,int(seasonDormancy))));
}
`;
const foliagePatch=shader=>{
  shader.vertexShader='attribute vec2 seasonLeaf; varying vec2 vSeasonLeaf;\n'+shader.vertexShader;
  shader.vertexShader=shader.vertexShader.replace('#include <begin_vertex>','#include <begin_vertex>\nvSeasonLeaf=seasonLeaf;');
  shader.fragmentShader='uniform vec3 seasonFoliage; varying vec2 vSeasonLeaf;\n'+shader.fragmentShader;
  shader.fragmentShader=shader.fragmentShader.replace('#include <alphatest_fragment>',`#include <alphatest_fragment>
if(vSeasonLeaf.x>=seasonFoliage.x)discard;`);
  shader.fragmentShader=shader.fragmentShader.replace('#include <color_fragment>',`#include <color_fragment>
float leafLuminance=max(dot(diffuseColor.rgb,vec3(.2126,.7152,.0722)),0.0);
vec3 leafAutumn=vSeasonLeaf.y<.5?mix(vec3(.9,.62,.045),vec3(.9,.24,.025),vSeasonLeaf.y*2.0)
 :mix(vec3(.9,.24,.025),vec3(.65,.045,.018),(vSeasonLeaf.y-.5)*2.0);
leafAutumn*=leafLuminance/max(dot(leafAutumn,vec3(.2126,.7152,.0722)),.0001);
diffuseColor.rgb=mix(diffuseColor.rgb,leafAutumn,seasonFoliage.y);
diffuseColor.rgb*=mix(vec3(1.0),vec3(1.12,1.18,.85),seasonFoliage.z);`);
};
const lawnPatch=blades=>shader=>{
  shader.vertexShader='varying vec2 vSeasonWorld;\n'+shader.vertexShader;
  // Root coordinates for blades keep every clump on the same patch as its
  // supporting lawn and the grass in paver joints, in metres on every tier.
  shader.vertexShader=shader.vertexShader.replace('#include <project_vertex>',`${blades?'vSeasonWorld=grassWorld.xz;':`vec4 seasonWorld=vec4(transformed,1.0);
#ifdef USE_INSTANCING
seasonWorld=instanceMatrix*seasonWorld;
#endif
vSeasonWorld=(modelMatrix*seasonWorld).xz;`}
#include <project_vertex>`);
  shader.fragmentShader=LAWN_GLSL+shader.fragmentShader;
  shader.fragmentShader=shader.fragmentShader.replace('#include <alphamap_fragment>','#include <alphamap_fragment>\ndiffuseColor.rgb=seasonLawn(diffuseColor.rgb);');
};

export function installSeasons(scene) {
  const uniforms={seasonFoliage:{value:new THREE.Vector3(1,0,0)},seasonDormancy:{value:0}};
  const foliage={seasonFoliage:uniforms.seasonFoliage},lawn={seasonDormancy:uniforms.seasonDormancy};
  const lawnSurface=lawnPatch(false),lawnBlades=lawnPatch(true);
  function prepare(root) {
    for(const object of frameObjects(root ?? scene,{fresh:root !== undefined})){
      for(const material of [].concat(object.material||[])){
        if(material.userData.seasonFoliage){
          bindEnvironmentMaterial(material,'season-foliage-1',foliage,foliagePatch);
          // Three builds shadow programs from independent materials. Install
          // their leaf test once too, rather than leaving a summer shadow.
          if(object.castShadow&&!object.customDepthMaterial){
            const options={map:material.map,alphaMap:material.alphaMap,alphaTest:material.alphaTest,side:material.side};
            const depth=new THREE.MeshDepthMaterial({...options,depthPacking:THREE.RGBADepthPacking});
            const distance=new THREE.MeshDistanceMaterial(options);
            object.customDepthMaterial=depth;object.customDistanceMaterial=distance;
            // Plant materials can outlive many seed/appearance rebuilds in
            // the yard cache. Retiring geometry must release its shadow pair
            // immediately, without waiting for that shared material to retire.
            const geometry=object.geometry;
            const release=()=>{
              material.removeEventListener('dispose',release);geometry.removeEventListener('dispose',release);
              depth.dispose();distance.dispose();
            };
            material.addEventListener('dispose',release);geometry.addEventListener('dispose',release);
          }
          for(const shadow of [object.customDepthMaterial,object.customDistanceMaterial])
            if(shadow)bindEnvironmentMaterial(shadow,'season-foliage-1',foliage,foliagePatch);
        }
        if(material.userData.seasonLawn)bindEnvironmentMaterial(material,'season-lawn-1',lawn,material.userData.grassUniforms?lawnBlades:lawnSurface);
      }
    }
  }
  return {uniforms,prepare,update(state){
    uniforms.seasonFoliage.value.set(clamp(state.presence),clamp(state.autumn),clamp(state.spring));
    uniforms.seasonDormancy.value=clamp(state.dormancy);prepare();
  },dispose(){}};
}

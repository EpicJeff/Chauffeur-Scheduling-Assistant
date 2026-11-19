import * as THREE from 'three';
import { modelDirection } from './look.js';
import { bindEnvironmentMaterial } from './stage_haze.js';

// Model x/z direction and a bounded 0..1 strength. No wind means a small grass
// breeze only; editor neutral suppresses even that. All consumers use m/s.
export function windVector(weather, frontBearing=180, {grass=false}={}) {
  if(weather?.neutral)return [0,0];
  const speed=Number.isFinite(weather?.windMps)?Math.max(0,weather.windMps):0;
  const strength=grass && weather?.windMissing ? .18 : Math.min(1,speed/15);
  const [x,,z]=modelDirection((weather?.windToDeg ?? 90)*Math.PI/180,0,frontBearing);
  return [x*strength,z*strength];
}

// Only generated EZ-Tree programs. Low-tier cards and imported models stay
// still. Bind once; time, weather, rebuild and viewing clones share uniforms.
export function installPlantWind(scene,{tier='high'}={}) {
  const uniforms={plantWind:{value:new THREE.Vector3()}};
  const patch=leaf=>shader=>{
    Object.assign(shader.uniforms,uniforms);
    shader.vertexShader='uniform vec3 plantWind;\n'+(leaf?'':'attribute float plantBranch;\n')+shader.vertexShader;
    shader.vertexShader=shader.vertexShader.replace('#include <begin_vertex>',`#include <begin_vertex>
// The woody mesh's generated trunk mask stays fixed. Branch displacement
// is .15% of height, leaves .8%, bounded by the 15 m/s full-strength wind.
float plantHeight=max(position.y,0.0);
float plantWeight=${leaf?'1.0':'plantBranch'};
float plantWave=sin(plantWind.z*.8+position.y*.7)+.35*sin(plantWind.z*1.3+position.x*.9);
vec2 plantWorldWind=plantWind.xy;
// Inverse model yaw/scale, including the yard's feet-to-metres transform.
vec2 plantX=modelMatrix[0].xz,plantZ=modelMatrix[2].xz;
transformed.xz+=vec2(dot(plantX,plantWorldWind)/max(dot(plantX,plantX),1e-6),
 dot(plantZ,plantWorldWind)/max(dot(plantZ,plantZ),1e-6))*plantHeight*length(modelMatrix[1].xyz)*${leaf?'.008':'.0015'}*plantWeight*plantWave;`);
  };
  const leafPatch=patch(true),branchPatch=patch(false);
  function prepare(root=scene) {
    if(tier==='low')return;
    root.traverse(object=>{
      for(const material of [].concat(object.material || [])){
        if(!material.userData.plantWind)continue;
        bindEnvironmentMaterial(material,'plant-wind-'+material.userData.plantWind+'-1',uniforms,material.userData.plantWind==='leaves'?leafPatch:branchPatch);
      }
    });
  }
  return {prepare,uniforms,update(seconds,weather,bearing){
    const [x,z]=windVector(weather,bearing);uniforms.plantWind.value.set(x,z,Number.isFinite(seconds)?seconds:0);prepare();
  },dispose(){}};
}

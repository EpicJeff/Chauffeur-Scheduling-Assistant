import * as THREE from 'three';

const RAD = Math.PI / 180;
const clamp = x => Math.max(0, Math.min(1, x));
const smooth = x => { x = clamp(x); return x*x*(3-2*x); };
export function discDiameterDeg(kind, altitudeDeg, moonDistanceKm = 384400) {
  const base = kind === 'moon' ? 2.2 * 384400 / Math.max(1, moonDistanceKm) : 2;
  return base * (1 + .6 * (1 - smooth(altitudeDeg / 30)));
}

const vertexShader = `
uniform vec3 direction, right, up;
uniform float radius, flatten;
varying vec2 disc;
varying float altitude;
void main() {
  disc=position.xy;
  vec3 ray=direction+radius*(right*disc.x+up*disc.y*flatten);
  altitude=ray.y;
  // Re-centre for EACH drawing camera, including the oblique mirror and probes.
  vec3 world=cameraPosition+40.0*ray;
  gl_Position=projectionMatrix*viewMatrix*vec4(world,1.0);
  // Sky never covers distant house/yard geometry, regardless of the 40m shell.
  gl_Position.z=gl_Position.w*0.999999;
}`;
const fragmentShader = `
uniform sampler2D moonMap;
uniform vec3 extinction, lightDirection;
uniform float kind, strength, enabled;
varying vec2 disc;
varying float altitude;
float held(float v) { return v>=0.0 ? min(v,4096.0) : 0.0; }
void main() {
  float r2=dot(disc,disc);
  // Derivatives need the whole fragment quad, including neighbours outside the
  // limb. Keep both edge coverage and the mipmapped lookup ahead of discards.
  float width=max(0.5*fwidth(r2),0.0001);
  float edge=1.0-smoothstep(1.0-width,1.0+width,r2);
  float z=sqrt(max(0.0,1.0-r2));
  vec3 normal=vec3(disc,z)/max(length(vec3(disc,z)),1e-6), result;
  if(kind<0.5) {
    // Solar limb darkening, scene-linear HDR; the circular mask precedes bloom.
    result=vec3(16.0*(0.4+0.6*z));
  } else {
    // The LROC equirectangular map is centred on the near-side meridian.
    vec2 uv=vec2(0.5+atan(normal.x,max(normal.z,1e-6))/6.28318531,
      0.5+asin(clamp(normal.y,-1.0,1.0))/3.14159265);
    vec3 albedo=texture2D(moonMap,uv).rgb;
    // True world sunlight projected onto this visible hemisphere: both waxing
    // and waning, including the tilt, follow the sun rather than a phase decal.
    float lit=max(0.0,dot(normal,lightDirection));
    // The moon is thousands of times brighter than the night sky around it; a
    // gain of 3 left it a faint smudge on the panel (Claude, Chromium check).
    // 48 reads as a bright, still-textured disc at the night exposure.
    result=albedo*48.0*(0.025+0.975*lit);
  }
  if(edge<=0.0 || altitude<0.0) discard;
  result*=extinction*strength;
  gl_FragColor=vec4(held(result.r),held(result.g),held(result.b),edge*enabled);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}`;

export function createBodies({moonMap} = {}) {
  const fallback = moonMap ? null : new THREE.DataTexture(new Uint8Array([128,128,128,255]),1,1);
  if (fallback) fallback.needsUpdate = true;
  const object = new THREE.Group(); object.name = 'sky-bodies';
  // A 25% gutter prevents the quad from clipping the outward half of coverage,
  // including the small lunar disc drawn into the low-tier sky cube.
  const geometry = new THREE.PlaneGeometry(2.5,2.5);
  for (const [i,kind] of ['sun','moon'].entries()) {
    const uniforms = {direction:{value:new THREE.Vector3(0,1,0)},right:{value:new THREE.Vector3(1,0,0)},
      up:{value:new THREE.Vector3(0,0,1)},radius:{value:.02},flatten:{value:1},
      moonMap:{value:moonMap || fallback},extinction:{value:new THREE.Vector3(1,1,1)},
      lightDirection:{value:new THREE.Vector3(0,0,1)},kind:{value:i},strength:{value:0},enabled:{value:1}};
    const material = new THREE.ShaderMaterial({uniforms,vertexShader,fragmentShader,
      transparent:true,depthTest:true,depthWrite:false,side:THREE.DoubleSide});
    const mesh = new THREE.Mesh(geometry,material); mesh.name = 'sky-'+kind;
    mesh.frustumCulled = false; mesh.castShadow = false; mesh.renderOrder = -90+i;
    object.add(mesh);
  }
  function update({sunDir=[0,1,0],moonDir=[0,-1,0],moonDistanceKm=384400,
    sunAltDeg,moonAltDeg,transmittance=()=>[1,1,1],overcast=0} = {}) {
    const sun = new THREE.Vector3().fromArray(sunDir.isVector3 ? sunDir.toArray() : sunDir).normalize();
    for (const [i,dir] of [sunDir,moonDir].entries()) {
      const u=object.children[i].material.uniforms, d=u.direction.value;
      d.fromArray(dir.isVector3 ? dir.toArray() : dir).normalize();
      const normal=d.clone().negate();
      u.right.value.crossVectors(Math.abs(d.y)>.999 ? new THREE.Vector3(0,0,1) : new THREE.Vector3(0,1,0),normal).normalize();
      u.up.value.crossVectors(normal,u.right.value).normalize();
      const alt=(i ? moonAltDeg : sunAltDeg) ?? Math.asin(Math.max(-1,Math.min(1,d.y)))/RAD;
      u.radius.value=Math.tan(discDiameterDeg(i?'moon':'sun',alt,moonDistanceKm)*RAD/2);
      u.flatten.value=1-.15*(1-smooth(alt/30));
      // An enlarged disc can still have its upper rim above the horizon after
      // its centre sets. Its visible rim keeps the grazing-path extinction.
      u.extinction.value.fromArray(transmittance([d.x,Math.max(0,d.y),d.z]));
      u.strength.value=i ? 1-clamp(overcast) : 1-.75*clamp(overcast);
      const light=sun.clone().addScaledVector(d,-moonDistanceKm/149598000).normalize();
      u.lightDirection.value.set(light.dot(u.right.value),light.dot(u.up.value),light.dot(normal));
    }
  }
  return {object,update,
    setMap(map) { for (const mesh of object.children) mesh.material.uniforms.moonMap.value=map; },
    setEnabled(on) { for (const mesh of object.children) mesh.material.uniforms.enabled.value=on?1:0; },
    dispose() { geometry.dispose();object.children.forEach(m=>m.material.dispose());fallback?.dispose(); }};
}

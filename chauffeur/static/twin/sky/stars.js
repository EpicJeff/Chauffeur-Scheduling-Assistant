import * as THREE from 'three';

const clamp=x=>Math.max(0,Math.min(1,x));
const smooth=x=>{x=clamp(x);return x*x*(3-2*x);};
// East/up/south, before the house bearing rotates north into the model frame.
export function starDirection(ra,dec,siderealTime,latitudeRad) {
  const h=siderealTime-ra, c=Math.cos(dec), s=Math.sin(dec), p=latitudeRad;
  return [-c*Math.sin(h),s*Math.sin(p)+c*Math.cos(h)*Math.cos(p),
    c*Math.cos(h)*Math.sin(p)-s*Math.cos(p)];
}
function colour(kelvin) {
  // Blackbody temperature approximation in sRGB, then convert to scene-linear.
  const t=Math.max(10,Math.min(400,kelvin/100));
  const r=t<=66?255:329.698727*Math.pow(Math.max(t-60,1e-6),-.13320476);
  const g=t<=66?99.470802*Math.log(Math.max(t,1e-6))-161.119568:288.12217*Math.pow(Math.max(t-60,1e-6),-.07551485);
  const b=t>=66?255:t<=19?0:138.517731*Math.log(Math.max(t-10,1e-6))-305.044793;
  return new THREE.Color().setRGB(clamp(r/255),clamp(g/255),clamp(b/255),THREE.SRGBColorSpace).toArray();
}
function geometryFor(catalogue) {
  const stars=catalogue?.stars || [], positions=[],coordinates=[],corners=[],colours=[],magnitudes=[],indices=[];
  stars.forEach(([ra,dec,mag,kelvin],i)=>{
    const rgb=colour(kelvin);
    for (const [x,y] of [[-1,-1],[1,-1],[1,1],[-1,1]]) {
      positions.push(0,0,0);coordinates.push(ra,dec);corners.push(x,y);colours.push(...rgb);magnitudes.push(mag);
    }
    const n=i*4;indices.push(n,n+1,n+2,n,n+2,n+3);
  });
  const g=new THREE.BufferGeometry();
  for (const [key,values,size] of [['position',positions,3],['equatorial',coordinates,2],['corner',corners,2],['starColor',colours,3],['magnitude',magnitudes,1]])
    g.setAttribute(key,new THREE.Float32BufferAttribute(values,size));
  g.setIndex(indices);return g;
}
const vertexShader=`
attribute vec2 equatorial, corner;
attribute vec3 starColor;
attribute float magnitude;
uniform float siderealTime, latitudeRad, bearing;
varying vec2 disc;
varying vec3 colour;
varying float intensity, altitude, phase;
void main() {
  float h=siderealTime-equatorial.x, c=cos(equatorial.y), s=sin(equatorial.y);
  vec3 d=vec3(-c*sin(h),s*sin(latitudeRad)+c*cos(h)*cos(latitudeRad),c*cos(h)*sin(latitudeRad)-s*cos(latitudeRad));
  d=vec3(cos(bearing)*d.x-sin(bearing)*d.z,d.y,sin(bearing)*d.x+cos(bearing)*d.z);
  vec3 normal=-d, reference=abs(d.y)>0.999 ? vec3(0.0,0.0,1.0) : vec3(0.0,1.0,0.0);
  vec3 right=cross(reference,normal);right/=max(length(right),1e-6);
  vec3 up=cross(normal,right);
  // Angular radius 0.025..0.085 degrees; brighter stars are also larger.
  float size=mix(0.00043633,0.00148353,clamp((6.0-magnitude)/7.5,0.0,1.0));
  vec3 world=cameraPosition+60.0*(d+size*(right*corner.x+up*corner.y));
  gl_Position=projectionMatrix*viewMatrix*vec4(world,1.0);gl_Position.z=gl_Position.w*0.9999995;
  disc=corner;colour=starColor;altitude=d.y;phase=equatorial.x*157.0+equatorial.y*113.0;
  intensity=8.0*pow(max(10.0,1e-6),clamp(-0.4*magnitude,-4.0,2.0));
}`;
const fragmentShader=`
uniform float opacity, enabled, twinkleTime;
varying vec2 disc;
varying vec3 colour;
varying float intensity, altitude, phase;
float held(float v) { return v>=0.0 ? min(v,4096.0) : 0.0; }
void main() {
  float r2=dot(disc,disc);if(r2>=1.0 || altitude<=0.0) discard;
  float twinkle=1.0+0.08*(1.0-smoothstep(0.0,0.34202014,altitude))*sin(twinkleTime*2.1+phase);
  vec3 result=colour*intensity*twinkle*opacity*enabled;
  // Additive light with a soft circular footprint, never a square point sprite.
  float edge=pow(max(0.0,1.0-r2),2.0)*smoothstep(0.0,0.02,altitude);
  gl_FragColor=vec4(held(result.r),held(result.g),held(result.b),edge);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}`;

export function createStars(catalogue) {
  const uniforms={siderealTime:{value:0},latitudeRad:{value:0},bearing:{value:0},opacity:{value:0},enabled:{value:1},twinkleTime:{value:0}};
  const material=new THREE.ShaderMaterial({uniforms,vertexShader,fragmentShader,transparent:true,
    blending:THREE.AdditiveBlending,depthTest:true,depthWrite:false,side:THREE.DoubleSide});
  const object=new THREE.Mesh(geometryFor(catalogue),material);object.name='sky-stars';
  object.frustumCulled=false;object.castShadow=false;object.renderOrder=-100;
  return {object,
    update({siderealTime=0,latitudeRad=0,sunAltDeg=0,moonFraction=0,overcast=0,frontBearingDeg=180}={}) {
      uniforms.siderealTime.value=siderealTime;uniforms.latitudeRad.value=latitudeRad;
      uniforms.bearing.value=(180-frontBearingDeg)*Math.PI/180;
      uniforms.opacity.value=smooth((-sunAltDeg-4)/8)*(1-.7*clamp(moonFraction))*(1-clamp(overcast));
    },
    frame(seconds) { uniforms.twinkleTime.value=seconds%4096; },
    setCatalogue(next) { const old=object.geometry;object.geometry=geometryFor(next);old.dispose(); },
    setEnabled(on) { uniforms.enabled.value=on?1:0; },
    dispose() { object.geometry.dispose();material.dispose(); }};
}

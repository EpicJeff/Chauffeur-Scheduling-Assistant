import * as THREE from 'three';

// Procedural water, one shader for every water effect. kind: 0 fountain jet
// (a solid core, then a skirt of falling strands that break into drops),
// 1 bubbler column, 2 falling sheet, 3 splash ring and landing foam, 4 the apron
// of broken foam that drifts out from a bubbler's foot.
export function waterMaterial(kind = 0) {
  return new THREE.ShaderMaterial({ transparent: true, depthWrite: false,
    side: THREE.DoubleSide, forceSinglePass: true, toneMapped: false,
    uniforms: { time: {value: 0}, strength: {value: 1}, opacity: {value: 1}, kind: {value: kind}, flow: {value: 1}, span: {value: 1}, light: {value: 1} },
    vertexShader: `uniform float time; uniform float kind; uniform float flow;
      attribute vec3 outward; varying vec2 vUv; varying vec3 vNormal; varying vec3 vView; varying float vPart;
      void main() {
        vUv=uv; vec3 p=position; vPart=0.;
        if(kind>1.5 && kind<2.5) p+=outward*flow*(1.-exp(-uv.y*6.));
        else if(kind<.5) {
          // The fountain marks its skirt in the spare outward channel.
          vPart=outward.y;
          float swell=1.+.025*sin(uv.y*18.-time*3.)*sin(uv.x*37.69911+time);
          p.xz*=swell;
        } else if(kind<1.5) {
          // Lumps of froth climb the column; the tip sways and pulses. Whole turns of
          // uv.x keep the seam closed.
          float h=1.-uv.y, a=uv.x*6.28318;
          float lump=.5*sin(a*3.+h*11.-time*6.)+.3*sin(a*5.-h*19.+time*8.3)+.2*sin(a*2.+h*29.-time*11.);
          p.xz*=1.+lump*(.1+.2*h);
          p.xz+=vec2(sin(time*2.3+h*3.),cos(time*1.7+h*2.))*.16*h*h;
          p.y*=1.-.05*h*h*(.5+.5*sin(time*9.));
        }
        vec4 mv=modelViewMatrix*vec4(p,1.); vView=-mv.xyz;
        vNormal=normalize(normalMatrix*normal);
        gl_Position=projectionMatrix*mv;
      }`,
    fragmentShader: `uniform float time; uniform float strength; uniform float opacity; uniform float kind; uniform float span; uniform float light;
      varying vec2 vUv; varying vec3 vNormal; varying vec3 vView; varying float vPart;
      float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
      // Value noise that repeats every period cells in x, so a lathe has no seam.
      float noise(vec2 p,float period){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);
        float a=mod(i.x,period),b=mod(i.x+1.,period);
        return mix(mix(hash(vec2(a,i.y)),hash(vec2(b,i.y)),f.x),mix(hash(vec2(a,i.y+1.)),hash(vec2(b,i.y+1.)),f.x),f.y);}
      void main(){
        vec2 uv=vUv; vec3 color; float alpha;
        float fres=pow(1.-abs(dot(normalize(vNormal),normalize(vView))),2.);
        vec3 deep=vec3(.2,.55,.7), pale=vec3(.74,.9,1.), white=vec3(.96,.99,1.);
        if(kind>3.5){
          // Foam thick at the foot, breaking into patches that thin as they drift out.
          float n=noise(vec2(uv.x*20.,uv.y*5.-time*.8),20.);
          float fine=noise(vec2(uv.x*60.,uv.y*13.-time*1.5),60.);
          float foam=smoothstep(.3+.3*uv.y,.56+.26*uv.y,n*.6+fine*.4);
          alpha=max(foam*.92*(1.-smoothstep(.55,1.,uv.y)),(1.-smoothstep(0.,.3,uv.y))*(.55+.35*fine));
          color=mix(vec3(.74,.9,.96),vec3(1.),foam);
        } else if(kind>2.5){
          float n=noise(vec2(uv.x*64.,uv.y*12.-time*2.8),64.);
          float fine=noise(vec2(uv.x*192.,uv.y*28.-time*5.6),192.);
          float foam=smoothstep(.53,.86,n*.6+fine*.4);
          float rings=.5+.5*sin(uv.y*36.-time*4.+n*2.);
          alpha=(.22+.6*foam)*rings*sin(uv.y*3.14159);
          color=mix(vec3(.53,.84,.9),vec3(1.),foam);
        } else if(kind>1.5){
          // A sheet: glassy at the lip, long streaks that whiten as the water falls.
          float x=uv.x*span;
          float n=noise(vec2(x*6.,uv.y*2.2-time*1.7),4096.);
          float fine=noise(vec2(x*23.,uv.y*7.-time*3.4),4096.);
          float streak=n*.62+fine*.38, air=smoothstep(.04,.9,uv.y);
          float froth=smoothstep(.5-.28*air,.82-.22*air,streak);
          color=mix(deep,pale,.35+fres*.4);
          color=mix(color,white,clamp(froth*(.3+.7*air),0.,1.));
          // A weak flow tears into ribbons instead of fading as one pane.
          float ribbons=smoothstep(.34,.52,n-uv.y*.12);
          alpha=(.46+.42*froth+fres*.1)*mix(ribbons,1.,smoothstep(.15,.75,strength));
          alpha*=smoothstep(0.,.08,x)*(1.-smoothstep(span-.08,span,x));
        } else if(kind>.5){
          // A column of air and water: white froth with cool shade in the hollows, a
          // ragged tip, and a foot that stays solid where it boils over.
          float h=1.-uv.y;
          float n=noise(vec2(uv.x*24.,h*18.-time*7.),24.);
          float fine=noise(vec2(uv.x*72.,h*50.-time*12.),72.);
          float froth=n*.55+fine*.45;
          color=mix(vec3(.72,.84,.93),white,smoothstep(.26,.52,froth));
          color=mix(color,pale,fres*.12);
          alpha=(.9+.08*froth)*(.75+.25*strength);
          alpha*=mix(1.,smoothstep(.3,.56,froth),smoothstep(.8,1.,h));
        } else if(vPart<.5){
          // The rising jet: aerated, nearly opaque.
          float n=noise(vec2(uv.x*8.,uv.y*7.-time*6.),8.);
          color=mix(pale,white,.45+.55*n);
          alpha=.78+.18*n;
        } else {
          // The fall: strands off the crown, thinning and breaking into drops.
          float cells=uv.x*24.;
          float sway=noise(vec2(cells,uv.y*3.-time*1.8),24.);
          float strand=pow(.5+.5*cos(6.28318*(cells+(sway-.5)*.7)),1.6+uv.y*5.);
          float drops=noise(vec2(uv.x*48.,uv.y*uv.y*24.-time*7.),48.);
          float broken=mix(1.,smoothstep(.36,.68,drops),smoothstep(.12,.75,uv.y));
          color=mix(pale,white,clamp(strand*.7+.2,0.,1.));
          alpha=strand*broken*(.95-.3*uv.y)*(.6+.4*strength);
          alpha=max(alpha,(1.-smoothstep(0.,.14,uv.y))*.82);
        }
        // Unlit water takes the scene's light level, so it does not glow at night.
        gl_FragColor=vec4(color*light,clamp(alpha*opacity,0.,.95));
      }` });
}

export function effectMesh(geometry, material) {
  geometry.userData.bakeExcluded = true;
  if (!geometry.getAttribute('outward')) geometry.setAttribute('outward', new THREE.Float32BufferAttribute(new Float32Array(geometry.getAttribute('position').count * 3), 3));
  const mesh = new THREE.Mesh(geometry, material);
  mesh.userData.effectFixture = true; mesh.castShadow = false; mesh.receiveShadow = false;
  return mesh;
}

export function splashRing(kind = 3, inner = .55) {
  const geometry = new THREE.RingGeometry(inner, 1, 64, 4).rotateX(-Math.PI / 2);
  // RingGeometry's stock UV is planar; radial UV makes the traveling rings circular.
  const p = geometry.attributes.position, uv = geometry.attributes.uv;
  for (let i = 0; i < p.count; i++) uv.setXY(i, (Math.atan2(p.getZ(i), p.getX(i)) / Math.PI + 1) / 2, (Math.hypot(p.getX(i), p.getZ(i)) - inner) / (1 - inner));
  return effectMesh(geometry, waterMaterial(kind));
}

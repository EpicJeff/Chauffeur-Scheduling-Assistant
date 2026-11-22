import * as THREE from 'three';

// One indexed, instanced mesh per shape. Everything below is built once; the
// GPU animates each slot from its birth, yaw, scale and lifetime (metres/seconds).
export const SPLASH_VARIANTS=['crown','jet','scatter'];
export function splashGeometry(variant,tier,lod=0) {
  const g=new THREE.InstancedBufferGeometry(),positions=[],normals=[],pieces=[],indices=[];
  const low=tier==='low',far=lod===1,drops=far?(low?4:8):(low?8:16),scatter=far?(low?3:4):(low?4:6);
  function append(source,part,angle=0,seed=0) {
    const offset=positions.length/3,p=source.attributes.position,n=source.attributes.normal;
    for(let i=0;i<p.count;i++){
      positions.push(p.getX(i),p.getY(i),p.getZ(i));normals.push(n.getX(i),n.getY(i),n.getZ(i));
      pieces.push(part,angle,seed);
    }
    for(const index of source.index.array)indices.push(offset+index);
    source.dispose();
  }
  // Analytic sphere impostors retain round silhouettes and smooth water
  // normals with two triangles, rather than faceted 16-80 triangle beads.
  function bead(){
    const q=new THREE.BufferGeometry();
    q.setAttribute('position',new THREE.Float32BufferAttribute([-1,-1,0,1,-1,0,1,1,0,-1,1,0],3));
    q.setAttribute('normal',new THREE.Float32BufferAttribute([0,0,1,0,0,1,0,0,1,0,0,1],3));
    q.setIndex([0,1,2,0,2,3]);return q;
  }
  if(variant==='crown'){
    // Keep the close rim's 96/64 samples and all four height bands. Lower bands
    // need fewer angular samples: their ligament displacement falls as t^3.
    const counts=far?(low?[8,16]:[12,24]):low?[8,8,16,32,64]:[24,32,64,96,96];
    let previous=0,previousCount=0;
    for(let row=0;row<counts.length;row++){
      const count=counts[row],offset=positions.length/3,t=row/(counts.length-1);
      for(let i=0;i<count;i++){
        const a=i*Math.PI*2/count,c=Math.cos(a),sn=Math.sin(a);
        positions.push(c,t,sn);normals.push(c,0,sn);pieces.push(0,0,0);
      }
      if(row){
        let i=0,j=0;
        while(i<previousCount||j<count){
          const a=previous+i%previousCount,b=offset+j%count;
          if((i+1)/previousCount<=(j+1)/count){indices.push(a,b,previous+(i+1)%previousCount);i++;}
          else {indices.push(a,b,offset+(j+1)%count);j++;}
        }
      }
      previous=offset;previousCount=count;
    }
    for(let i=0;i<drops;i++)append(bead(),1,i,(i*.618034)%1);
  }else if(variant==='jet'){
    append(new THREE.CylinderGeometry(.5,1,1,far?4:low?6:8,far?1:low?2:3,true).translate(0,.5,0),2);
    append(bead(),3);
  }else{
    for(let i=0;i<scatter;i++)append(bead(),4,i*Math.PI*2/scatter,(i*.618034)%1);
  }
  g.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));
  g.setAttribute('normal',new THREE.Float32BufferAttribute(normals,3));
  g.setAttribute('splashPiece',new THREE.Float32BufferAttribute(pieces,3));
  g.setIndex(indices);g.instanceCount=0;
  g.userData.variant=variant;g.userData.lod=lod;g.userData.droplets=variant==='crown'?drops:variant==='scatter'?scatter:1;
  return g;
}

// Projected silhouette diameter for CPU LOD selection; no vectors allocated.
export function splashProjectedPixels(depth,scale,projectionY,height,orthographic=false) {
  return .058*scale*Math.abs(projectionY)*height*.5/(orthographic?1:Math.max(.03,depth));
}
const distanceGLSL=`
float splashDistanceWeight(float pixels) {
  return 1.0-smoothstep(4.0,24.0,pixels);
}
float splashDistanceCoverage(float pixels, float feature, float light) {
  return splashDistanceWeight(pixels)*feature*.65*clamp(light*2.0,0.0,1.0);
}
float splashDistanceBrightness(float pixels, float sunShare, float highlight) {
  return splashDistanceWeight(pixels)*mix(.85,.2+.8*highlight,sunShare);
}
`;

export const splashVertex=`
attribute vec3 splashPosition,splashNormal,splashPiece;
attribute float splashBorn,splashWater;
attribute vec3 splashShape; // yaw, size jitter, lifetime
uniform sampler2D precipCover;uniform vec4 precipCoverBounds;uniform float precipCutaway;
uniform float splashTime,splashBeadCount;uniform vec2 precipViewport;
varying float splashAge,splashLife,splashThickness,splashBead,splashPixels,splashFeature;
varying vec2 particleUv;varying vec3 particleWorld,splashWorldNormal;
${distanceGLSL}
bool precipitationCovered(vec3 world) {
  vec2 uv=(world.xz-precipCoverBounds.xy)/max(precipCoverBounds.zw-precipCoverBounds.xy,vec2(.0001));
  if(any(lessThan(uv,vec2(0.0)))||any(greaterThanEqual(uv,vec2(1.0))))return false;
  return texture2D(precipCover,uv).r>-9999.0;
}
bool splashVisible(float age,float depth) {
  return age>=0.0&&age<=0.3&&depth>=.03;
}
// A yaw-derived seed varies the topology without rebuilding geometry.
float splashRimCount(float seed) {
  return 10.0+floor(fract(seed*7.137)*7.0);
}
float splashRimJitter(float point, float seed) {
  return fract(sin(point*127.1+seed*311.7)*43758.5453);
}
float splashRimAngle(float point, float count, float seed) {
  return (point+.28*(splashRimJitter(point,seed)-.5))*6.283185/count;
}
float splashRimHeight(float point, float seed) {
  return .72+.56*splashRimJitter(point+31.0,seed);
}
void main(){
  splashAge=splashTime-splashBorn;splashLife=splashShape.z;particleUv=vec2(0.0);
  vec4 eye=viewMatrix*vec4(splashPosition,1.0);
  if(!splashVisible(splashAge,-eye.z)){gl_Position=vec4(2.0,2.0,2.0,1.0);return;}
  if(splashAge>splashLife||precipCutaway>.5&&precipitationCovered(splashPosition)){
    gl_Position=vec4(2.0,2.0,2.0,1.0);return;
  }
  // Reject the whole shape before deformation (16 cm bounds include every
  // ballistic bead). Small distant beads do not pay fragment/specular cost.
  vec4 clip=projectionMatrix*eye;
  vec2 margin=.16*vec2(projectionMatrix[0][0],projectionMatrix[1][1]);
  if(any(greaterThan(abs(clip.xy),vec2(clip.w)+margin))){gl_Position=vec4(2.0,2.0,2.0,1.0);return;}
  float phase=splashAge/max(splashLife,.001);
  float grow=smoothstep(0.0,.22,phase),collapse=smoothstep(.45,1.0,phase);
  float size=splashShape.y,part=splashPiece.x,angle=splashPiece.y,seed=splashPiece.z;
  vec3 p=position,n=normal;splashBead=0.0;splashFeature=0.0;float beadRadius=0.0;
  float pixelScale=abs(projectionMatrix[1][1])*precipViewport.y*.5/(projectionMatrix[3][3]>.5?1.0:max(.03,-eye.z));
  splashPixels=.03*size*pixelScale;
  float instanceSeed=splashShape.x/6.283185;
  float points=splashRimCount(instanceSeed);
  float sheetHeight=mix(.010,.014,splashWater)*grow*(1.0-.85*collapse);
  float ligament=mix(.008,.011,splashWater)*grow*(1.0-.85*collapse);
  if(part<.5){
    float t=position.y,a=atan(position.z,position.x);
    float point=floor(a*points/6.283185+.5);
    point=mod(point+points,points);
    float tipAngle=splashRimAngle(point,points,instanceSeed);
    float wave=pow(max(0.0,.5+.5*cos((a-tipAngle)*points)),6.0);
    float rim=ligament*splashRimHeight(point,instanceSeed)*wave;
    float r=.009+.020*t*grow;
    p=vec3(position.x*r,t*(sheetHeight+rim*t*t),position.z*r);
    n=normalize(vec3(position.x*max(sheetHeight,.00001),-.020*max(grow,.001),position.z*max(sheetHeight,.00001)));
    // The rim ligaments are optically much thinner than the sheet base.
    splashThickness=mix(.00065,.00007,t*t);splashFeature=t*t*t*t;
  }else if(part<1.5||part>3.5){
    bool crown=part<1.5;
    float point=crown&&splashBeadCount<points?floor(angle*points/splashBeadCount):angle;
    if(crown&&point>=points){gl_Position=vec4(2.0,2.0,2.0,1.0);return;}
    float a=crown?splashRimAngle(point,points,instanceSeed):angle;
    float jitter=splashRimJitter(point,instanceSeed);
    float flight=max(0.0,splashAge-(crown?.28:0.0)*splashLife);
    float speed=mix(crown?.12:.25,crown?.28:.48,jitter);
    float r=(crown?.009+.020*grow:.004)+flight*mix(.08,.22,jitter);
    float h=crown?(mix(.010,.014,splashWater)+mix(.008,.011,splashWater)*splashRimHeight(point,instanceSeed))*grow:.002;
    h+=speed*flight-4.905*flight*flight;
    float bead=mix(.0012,.0026,seed)*(1.0-smoothstep(.65,1.0,phase));
    p=vec3(cos(a)*r,max(bead,h),sin(a)*r);beadRadius=bead;
    splashThickness=bead*2.0;splashBead=1.0;splashFeature=1.0;
  }else{
    float h=.030*sin(min(1.0,phase)*3.141593);
    float radius=.0030*grow*(1.0-.85*collapse);
    if(part<2.5){
      float t=position.y,neck=mix(1.0,.16,t*t);
      p=vec3(position.x*radius*neck,t*h,position.z*radius*neck);
      n=normalize(vec3(normal.x,2.0*radius*t/max(h,.001),normal.z));
      splashThickness=2.0*radius*neck;splashFeature=t*t*t*t;
    }else {
      float bead=.0026*grow*(1.0-.8*collapse);
      p=vec3(.001*sin(phase*5.0),h,0.0);beadRadius=bead;
      splashThickness=bead*2.0;splashBead=1.0;splashFeature=1.0;
    }
  }
  // Random yaw in a stable tangent frame follows sloped hardscape/roofs.
  vec3 up=normalize(splashNormal),tangent=normalize(cross(abs(up.y)<.99?vec3(0.0,1.0,0.0):vec3(0.0,0.0,1.0),up));
  vec3 side=cross(up,tangent);
  float c=cos(splashShape.x),s=sin(splashShape.x);
  mat3 basis=mat3(tangent*c+side*s,up,side*c-tangent*s);
  particleWorld=splashPosition+basis*p*size;
  if(splashBead>.5){
    // A short 1-2px spherical fleck survives subpixel physical beads. The
    // close silhouette uses its physical radius and the same sphere normal.
    beadRadius=max(beadRadius,.8*splashDistanceWeight(splashPixels)/max(size*pixelScale,.0001));
    vec3 right=vec3(viewMatrix[0][0],viewMatrix[1][0],viewMatrix[2][0]);
    vec3 cameraUp=vec3(viewMatrix[0][1],viewMatrix[1][1],viewMatrix[2][1]);
    particleWorld+=(right*position.x+cameraUp*position.y)*beadRadius*size;
    particleUv=position.xy;
  }
  splashWorldNormal=normalize(basis*n);
  splashThickness*=size;
  gl_Position=projectionMatrix*viewMatrix*vec4(particleWorld,1.0);
}`;

// Same clear-water interface as effects/water_surface.js: a dielectric rim,
// narrow sun lobe and sky reflection. No mirror pass or house-material patch.
export const splashFragment=`
uniform samplerCube splashEnvironment;
uniform float splashEnvironmentGain,splashSunVisibility;
uniform vec3 touchLight,splashSunDirection,splashSunColour;
varying float splashAge,splashLife,splashThickness,splashBead,splashPixels,splashFeature;
varying vec3 splashWorldNormal;
${distanceGLSL}
float splashFresnel(float cosine) {
  return .02+.98*pow(1.0-clamp(cosine,0.0,1.0),5.0);
}
float splashSpecular(vec3 n,vec3 v,vec3 l) {
  vec3 halfVector=v+l;
  vec3 h=halfVector/max(length(halfVector),.0001);
  return splashFresnel(max(dot(v,h),0.0))*pow(max(dot(n,h),0.0),768.0)*122.55*max(dot(n,l),0.0);
}
// No diffuse white: coverage is only the dielectric reflection, absorption
// and a small dark refractive edge. Returning straight colour with this
// coverage keeps repeated faces clear instead of adding a pale body per layer.
float splashCoverage(float cosine, float thickness, float bead) {
  float f=splashFresnel(cosine);
  float absorption=1.0-exp(-thickness*24.0/max(cosine,.15));
  return clamp(f+absorption*(1.0-f)+bead*.12*pow(1.0-cosine,2.0),0.0,.94);
}
float splashGlintCoverage(float specular, float sunPeak, float environmentPeak, float fresnel) {
  return 1.0-exp(-1.5*(specular*sunPeak+max(0.0,environmentPeak-1.0)*fresnel));
}
float splashCloseSun(float specular, float visibility, float coverage, float sunPeak, float pixels) {
  // Every splash's direct sun lobe follows the same sun-disc visibility as lit
  // wet surfaces; resolved sheets (>24 px) also keep the wet-deck HDR cap.
  float close=smoothstep(24.0,28.0,pixels);
  float cap=min(.25,1.0/max(sunPeak,.0001))*coverage;
  return mix(specular,min(specular,cap),close)*visibility;
}
float splashCloseEnergy(float energy, float pixels) {
  return mix(energy,min(energy,1.0),smoothstep(24.0,28.0,pixels));
}
vec3 splashTransmittedColour(vec3 environment, float thickness, float cosine) {
  float path=thickness/max(cosine,.15);
  // Thin rain sheets are neutral. Only centimetres of water acquire a very
  // slight blue-green absorption; the illumination supplies its own colour.
  vec3 absorption=mix(vec3(18.0),vec3(18.0,17.5,17.0),smoothstep(.01,.08,thickness));
  return environment*exp(-absorption*path)*.065;
}
void main(){
  vec3 v=normalize(cameraPosition-particleWorld),n=normalize(splashWorldNormal);
  float beadEdge=1.0;
  if(splashBead>.5){
    float r2=dot(particleUv,particleUv),edgeWidth=max(fwidth(r2),.02);
    if(r2>=1.0)discard;
    beadEdge=1.0-smoothstep(1.0-edgeWidth,1.0,r2);
    vec3 right=vec3(viewMatrix[0][0],viewMatrix[1][0],viewMatrix[2][0]);
    vec3 up=vec3(viewMatrix[0][1],viewMatrix[1][1],viewMatrix[2][1]);
    vec3 back=vec3(viewMatrix[0][2],viewMatrix[1][2],viewMatrix[2][2]);
    n=normalize(right*particleUv.x+up*particleUv.y+back*sqrt(max(0.0,1.0-r2)));
  }
  if(dot(n,v)<0.0)n=-n;
  float cosine=clamp(dot(n,v),0.0,1.0),fresnel=splashFresnel(dot(n,v));
  // r187's fixed PMREM is a cube with roughness mips. Explicit LOD zero
  // preserves tiny environmental glints even on a curved subpixel bead.
  vec3 reflection=textureLod(splashEnvironment,reflect(-v,n),0.0).rgb*splashEnvironmentGain;
  float specular=splashSpecular(n,v,normalize(splashSunDirection));
  float cover=splashCoverage(cosine,splashThickness,splashBead);
  float sunPeak=max(splashSunColour.r,max(splashSunColour.g,splashSunColour.b));
  float directSpecular=splashCloseSun(specular,splashSunVisibility,cover,sunPeak,splashPixels);
  float glint=splashGlintCoverage(directSpecular,sunPeak,max(reflection.r,max(reflection.g,reflection.b)),fresnel);
  cover=mix(cover,.98,glint);
  vec3 dark=splashTransmittedColour(reflection,splashThickness,cosine)*touchLight;
  vec3 light=reflection*fresnel+dark*max(0.0,cover-fresnel)+splashSunColour*directSpecular;
  float irradiance=dot(touchLight,vec3(.2126,.7152,.0722));
  float sun=dot(splashSunColour,vec3(.2126,.7152,.0722))*splashSunVisibility;
  float sunShare=sun/max(sun+irradiance,.0001);
  float bounce=splashDistanceCoverage(splashPixels,splashFeature,irradiance);
  float pulse=sin(3.141593*clamp(splashAge/max(splashLife,.001),0.0,1.0));
  bounce*=pulse;
  // Broad soft overcast flecks, narrower sunlit glints. No constant emissive
  // colour: both the fleck and its coverage dim with scene irradiance.
  vec3 sky=mix(vec3(dot(reflection,vec3(.2126,.7152,.0722))),reflection,.2);
  vec3 fleck=(touchLight*.7+sky*.3)*splashDistanceBrightness(splashPixels,sunShare,clamp(specular,0.0,1.0));
  light+=fleck*bounce;cover=max(cover,bounce);
  float fade=(1.0-smoothstep(.65,1.0,splashAge/max(splashLife,.001)))*precipitationFade(.03,.06,0.0);
  float alpha=cover*fade*beadEdge;
  if(alpha<.001)discard;
  vec3 colour=precipSafe(light/max(cover,.001));
  colour=vec3(splashCloseEnergy(colour.r,splashPixels),splashCloseEnergy(colour.g,splashPixels),splashCloseEnergy(colour.b,splashPixels));
  gl_FragColor=vec4(colour,clamp(alpha,0.0,1.0));
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}`;

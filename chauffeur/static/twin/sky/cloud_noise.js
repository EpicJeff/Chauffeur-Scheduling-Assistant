// Periodic gradient Perlin and cellular F1 Worley. Integer hashing, no random()
// and no duplicated border voxels: RepeatWrapping interpolates across the seam.
const mod = (x, n) => ((x % n) + n) % n;
const clamp = x => Math.max(0, Math.min(1, x));
const fade = x => x*x*x*(x*(x*6-15)+10);
const mix = (a,b,t) => a+(b-a)*t;
const gradients = [[1,1,0],[-1,1,0],[1,-1,0],[-1,-1,0],[1,0,1],[-1,0,1],
  [1,0,-1],[-1,0,-1],[0,1,1],[0,-1,1],[0,1,-1],[0,-1,-1]];
function hash(x,y,z,seed) {
  let h = Math.imul(x,374761393) ^ Math.imul(y,668265263) ^ Math.imul(z,2147483647) ^ seed;
  h = Math.imul(h ^ (h >>> 13),1274126177);
  return (h ^ (h >>> 16)) >>> 0;
}
const grids = new Map();
function grid(period,seed) {
  if (!Number.isInteger(period) || period<1 || period>64) throw new RangeError('Cloud noise period must be 1..64');
  const key=period+':'+seed;
  if (grids.has(key)) return grids.get(key);
  const points=new Float32Array(period**3*3), vectors=new Float32Array(period**3*3);
  for (let z=0;z<period;z++) for (let y=0;y<period;y++) for (let x=0;x<period;x++) {
    const i=((z*period+y)*period+x)*3, g=gradients[hash(x,y,z,seed)%12];
    for (let a=0;a<3;a++) {
      points[i+a]=hash(x,y,z,seed+1013*(a+1))/4294967296;
      vectors[i+a]=g[a]*Math.SQRT1_2;
    }
  }
  const mask=period-1;
  const index=(period & mask)===0
    ? (x,y,z)=>(((z & mask)*period+(y & mask))*period+(x & mask))*3
    : (x,y,z)=>((mod(z,period)*period+mod(y,period))*period+mod(x,period))*3;
  const result={points,vectors,index};grids.set(key,result);return result;
}
function perlinSampler(period,seed) {
  const {vectors,index}=grid(period,seed);
  return (x,y,z)=>{
    const ix=Math.floor(x),iy=Math.floor(y),iz=Math.floor(z), fx=x-ix,fy=y-iy,fz=z-iz;
    const dot=(dx,dy,dz)=>{const i=index(ix+dx,iy+dy,iz+dz);
      return vectors[i]*(fx-dx)+vectors[i+1]*(fy-dy)+vectors[i+2]*(fz-dz);};
    const u=fade(fx),v=fade(fy),w=fade(fz);
    return mix(mix(mix(dot(0,0,0),dot(1,0,0),u),mix(dot(0,1,0),dot(1,1,0),u),v),
      mix(mix(dot(0,0,1),dot(1,0,1),u),mix(dot(0,1,1),dot(1,1,1),u),v),w);
  };
}
function worleySampler(period,seed) {
  const {points,index}=grid(period,seed);
  const order=[0,-1,1];
  return (x,y,z)=>{
    const ix=Math.floor(x),iy=Math.floor(y),iz=Math.floor(z), fx=x-ix,fy=y-iy,fz=z-iz;
    const bx=[0,fx*fx,(1-fx)*(1-fx)],by=[0,fy*fy,(1-fy)*(1-fy)],bz=[0,fz*fz,(1-fz)*(1-fz)];
    let nearest=3;
    // Visit this cell first, then reject neighbours whose AABB cannot improve
    // F1. The exact same field costs far fewer feature-point distance tests.
    for (let zi=0;zi<3;zi++) for (let yi=0;yi<3;yi++) for (let xi=0;xi<3;xi++) {
      if(bx[xi]+by[yi]+bz[zi]>=nearest) continue;
      const dx=order[xi],dy=order[yi],dz=order[zi];
      const i=index(ix+dx,iy+dy,iz+dz), a=dx+points[i]-fx,b=dy+points[i+1]-fy,c=dz+points[i+2]-fz;
      nearest=Math.min(nearest,a*a+b*b+c*c);
    }
    return clamp(Math.sqrt(Math.max(0,nearest)));
  };
}
// Coordinates are in cells. Both functions repeat after `period` on all axes.
export function perlin3(x,y,z,period=4,seed=17) { return perlinSampler(period,seed)(x,y,z); }
export function worley3(x,y,z,period=4,seed=29) { return worleySampler(period,seed)(x,y,z); }

export function generateNoiseVolume(size,{detail=false}={}) {
  if (!Number.isInteger(size) || size<2 || size>128) throw new RangeError('Cloud texture size must be 2..128');
  const data=new Uint8Array(size**3*4), frequencies=[4,8,16];
  const worley=frequencies.map(f=>worleySampler(f,detail?71:29));
  const perlin=frequencies.map(f=>perlinSampler(f,17));
  for (let z=0;z<size;z++) for (let y=0;y<size;y++) for (let x=0;x<size;x++) {
    // Texel centres, matching the GPU's normalized linear sampling convention.
    const u=(x+.5)/size,v=(y+.5)/size,w=(z+.5)/size, cells=[];
    for (let o=0;o<3;o++) {const f=frequencies[o];cells.push(1-worley[o](u*f,v*f,w*f));}
    const cellular=cells[0]*.625+cells[1]*.25+cells[2]*.125;
    let shape=cellular;
    if (!detail) {
      let gradient=0;
      for (let o=0;o<3;o++) {const f=frequencies[o];gradient+=perlin[o](u*f,v*f,w*f)*[.625,.25,.125][o];}
      const p=clamp(.5+gradient);
      // Dilate the smooth gradient field with cellular lobes, preserving wisps.
      shape=clamp((p+1-cellular)/Math.max(2-cellular,1e-6));
    }
    const i=((z*size+y)*size+x)*4;
    data[i]=Math.round(shape*255);
    for (let c=0;c<3;c++) data[i+c+1]=Math.round(cells[c]*255);
  }
  return data;
}

// CPU reference for texture(sampler3D, uv), including periodic edge filtering.
export function sampleVolume({data,width,height=width,depth=width},uv) {
  const sizes=[width,height,depth], p=uv.map((v,i)=>mod(v,1)*sizes[i]-.5), lo=p.map(Math.floor), f=p.map((v,i)=>v-lo[i]);
  const result=[0,0,0,0];
  for (let z=0;z<2;z++) for (let y=0;y<2;y++) for (let x=0;x<2;x++) {
    const weight=(x?f[0]:1-f[0])*(y?f[1]:1-f[1])*(z?f[2]:1-f[2]);
    const i=((mod(lo[2]+z,depth)*height+mod(lo[1]+y,height))*width+mod(lo[0]+x,width))*4;
    for (let c=0;c<4;c++) result[c]+=data[i+c]/255*weight;
  }
  return result;
}

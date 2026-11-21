"""Run tiled grass, conservative density and the mounted moving-camera hook in Node."""
import sys
from pathlib import Path

from test_twin_untouched_house_js import COMMON
from twin_editor_dom import run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = COMMON + r"""
const B=await import(file('static/twin/yard_grass.js'));
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const {disposeObject}=await import(file('static/twin/twin_library.js'));
const FT=.3048,source=new THREE.MeshStandardMaterial();
const plan={buildings:[],site:{lot:square(0,0,40/FT,60/FT)}};
await test('split_covers_each_instance_once_and_is_bounded',()=>{
 const matrices=new Float32Array(10000*16);
 for(let i=0;i<10000;i++){matrices[i*16+12]=(i%100)*40/FT/100;matrices[i*16+14]=-Math.floor(i/100)*60/FT/100;}
 const tiles=B.splitGrassTiles(matrices,40*60/FT**2);
 assert.ok(tiles.length>1&&tiles.length<=32);
 const indices=tiles.flatMap(t=>Array.from(t.indices)).sort((a,b)=>a-b);
 assert.deepEqual(indices,Array.from({length:10000},(_,i)=>i));
 for(const t of tiles)for(let i=1;i<t.seeds.length;i++)assert.ok(t.seeds[i]>=t.seeds[i-1]);
});
await test('counts_are_full_near_quarter_far_monotone_and_conservative',()=>{
 const seeds=Array.from({length:10001},(_,i)=>i/10001);
 assert.equal(B.grassCountForDistance(seeds,0),seeds.length);
 const far=B.grassCountForDistance(seeds,200)/seeds.length;assert.ok(far>=B.GRASS_FAR_KEEP&&far<=B.GRASS_FAR_KEEP+.06,far);
 let last=seeds.length;
 for(let d=0;d<=200;d++){
  const count=B.grassCountForDistance(seeds,d);assert.ok(count<=last);last=count;
  for(let i=0;i<seeds.length;i+=7)for(const offset of [0,1,20,100]){
   // Include even partially faded blades, beyond the requested fully drawn set.
   if(seeds[i]<B.grassKeep(d+offset)+.045)assert.ok(i<count,`${d} ${i}`);
  }
 }
 assert.equal(B.grassKeep(B.GRASS_FULL_METRES),1);assert.ok(Math.abs(B.grassKeep(B.GRASS_THIN_METRES)-B.GRASS_FAR_KEEP)<1e-12);
 const f=Math.fround,x=f(12.345),z=f(-98.765);
 const value=f(f(Math.sin(f(f(x*f(12.9898))+f(z*f(78.233)))))*f(43758.5453));
 assert.equal(B.grassSeed(x,z),value-Math.floor(value));
});
await test('real_tiles_share_resources_bound_roots_cull_and_restore_after_moving',()=>{
 const grass=B.buildGrass(plan,kit(),'high',source),group=grass.mesh;
 assert.ok(group.isGroup);assert.equal(grass.draws,grass.tiles.length);assert.ok(grass.draws<=32);
 assert.equal(grass.tiles.reduce((n,t)=>n+t.count,0),grass.instances);
 group.scale.setScalar(FT);group.position.set(3,2,-5);group.rotation.y=.4;group.updateMatrixWorld(true);
 const camera=new THREE.PerspectiveCamera();camera.position.set(0,200,0);
 for(const tile of grass.tiles){
  assert.equal(tile.geometry,grass.tiles[0].geometry);assert.equal(tile.material,grass.tiles[0].material);
  assert.equal(tile.frustumCulled,true);assert.equal(tile.receiveShadow,true);assert.equal(tile.castShadow,false);
  const a=tile.instanceMatrix.array;
  for(let i=0;i<tile.count;i++){
   const root=new THREE.Vector3(a[i*16+12],a[i*16+13],a[i*16+14]);
   assert.ok(tile.boundingBox.containsPoint(root));assert.ok(tile.boundingSphere.containsPoint(root));
  }
 }
 grass.update(10,null,180,camera);
 const far=grass.tiles.reduce((n,t)=>n+t.count,0);assert.ok(far<grass.instances*.26);assert.ok(far*B.GRASS_TRIANGLES_PER_CLUMP<B.GRASS_MAIN_TRIANGLE_BUDGET);
 for(const y of [40,70,100,150]){
  camera.position.set(15,y,-20);grass.update(10,null,180,camera);
  for(const t of grass.tiles){const a=t.instanceMatrix.array,root=new THREE.Vector3();
   for(let i=0;i<t.instanceMatrix.count;i++){
    root.fromArray(a,i*16+12).applyMatrix4(t.matrixWorld);
    const seed=B.grassSeed(a[i*16+12],a[i*16+14]),keep=B.grassKeep(root.distanceTo(camera.position));
    assert.equal(seed,t.userData.grassSeeds[i]);
    if(seed<keep+.045)assert.ok(i<t.count,'every nonzero shader clump is submitted');
   }
  }
 }
 const tile=grass.tiles[0],root=new THREE.Vector3().fromArray(tile.instanceMatrix.array,12).applyMatrix4(tile.matrixWorld);
 camera.position.copy(root);grass.update(11,null,180,camera);assert.equal(tile.count,tile.instanceMatrix.count);
 const frustum=new THREE.Frustum().setFromProjectionMatrix(new THREE.Matrix4().multiplyMatrices(camera.projectionMatrix,camera.matrixWorldInverse));
 camera.position.set(0,200,0);camera.lookAt(0,400,0);camera.updateMatrixWorld();
 frustum.setFromProjectionMatrix(new THREE.Matrix4().multiplyMatrices(camera.projectionMatrix,camera.matrixWorldInverse));
 assert.ok(grass.tiles.every(t=>!frustum.intersectsObject(t)),'off-screen lawn is culled');
 disposeObject(group);
});
await test('mounted_render_updates_counts_for_viewer_and_editor',async()=>{
 for(const editor of [false,true]){
  location.search='?test=1';const host=new Element();
  if(editor){const shell=new Element();shell.className='editor-shell';shell.append(host);}
  const v=await mountTwin(host,{plan,kit:kit(),tier:'medium',bake:false});
  try{
   const grass=v.scene.getObjectByName('yard').userData.grass;
   v.setCameraState({position:[0,200,0],target:[0,0,0]});v.render();
   const far=grass.tiles.reduce((n,t)=>n+t.count,0);assert.ok(far<grass.instances*.26,JSON.stringify({far,total:grass.instances,camera:v.cameraState()}));
   v.setCameraState({position:[10,5,-10],target:[10,0,-10]});v.render();
   assert.ok(grass.tiles.reduce((n,t)=>n+t.count,0)>far);
  }finally{v.dispose();}
 }
});
await test('weather_exposure_preserves_one_geometry_and_every_instance_through_lod',async()=>{
 const {writeWeatherOpen}=await import(file('static/twin/sky/sky_cover.js'));
 const {installWeatherSurface}=await import(file('static/twin/sky/weather_surface.js'));
 const grass=B.buildGrass(plan,kit(),'medium',source),group=grass.mesh;
 group.scale.setScalar(FT);const camera=new THREE.PerspectiveCamera();camera.position.set(0,200,0);grass.update(1,null,180,camera);
 const cover={key:'test',staticKey:'test',staticOpen:(x,y,z)=>x>20?1:0,slabOpen:()=>1};
 writeWeatherOpen(group,cover);
 for(const t of grass.tiles){
  assert.equal(t.geometry,grass.tiles[0].geometry,'weather may not clone tile geometry');
  for(let i=0;i<t.instanceMatrix.count;i++)assert.equal(t.instanceColor.getX(i),t.instanceMatrix.array[i*16+12]*FT>20?1:0);
 }
 const scene=new THREE.Scene();scene.add(group);const weather=installWeatherSurface(scene);weather.prepare();
 const shader={uniforms:{},vertexShader:THREE.ShaderLib.standard.vertexShader,fragmentShader:THREE.ShaderLib.standard.fragmentShader};
 grass.tiles[0].material.onBeforeCompile(shader,{});
 assert.ok(shader.vertexShader.includes('vWeatherOpen=instanceColor.r;'));
 assert.ok(!shader.vertexShader.includes('vColor.rgb *= instanceColor.rgb;'),'joint/exposure channels never tint grass');
 weather.dispose();disposeObject(group);
});
await test('hidden_pad_grass_stays_hidden_when_the_camera_increases_tile_count',async()=>{
 const {createPieceVisibility}=await import(file('static/twin/twin_visibility.js'));
 const grass=B.buildGrass(plan,kit(),'medium',source),camera=new THREE.PerspectiveCamera();grass.mesh.scale.setScalar(FT);
 camera.position.set(0,200,0);grass.update(1,null,180,camera);
 for(const t of grass.tiles)t.userData.instancePiece=()=>({kind:'pad',pieceId:'pad'});
 const visibility=createPieceVisibility();visibility.set(['pad'],[]);visibility.apply(grass.mesh);
 camera.position.set(10,5,-10);grass.update(2,null,180,camera);visibility.enforce(grass.mesh);
 for(const t of grass.tiles)for(let i=0;i<t.count;i++)assert.equal(t.instanceMatrix.array[i*16+5],0);
 visibility.restore();for(const t of grass.tiles)for(let i=0;i<t.instanceMatrix.count;i++)assert.ok(t.instanceMatrix.array[i*16+5]>0);
 disposeObject(grass.mesh);
});
finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()}, timeout=180)
    print(output)
    sys.exit(code or 0)

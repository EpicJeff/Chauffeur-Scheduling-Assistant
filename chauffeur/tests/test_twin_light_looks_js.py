"""Execute the shared colour resolver, line pool, glow and live updates in Node."""
import sys
import test_twin_real_lights_js as harness

BASE = harness.DRIVER
DRIVER = BASE[:BASE.index("check('lights_mode_never")] + r"""
const C = await import(file('static/twin/live/light_colours.js'));
const {emission, resolveEmitters} = await import(file('static/twin/live/emitters.js'));
const {linePieces, createFixtureGlow} = await import(file('static/twin/live/fixture_glow.js'));
const {markerOnColor} = await import(file('static/twin/palette.js'));
const look = {colour:[0,80,255],effects:{caribbean:[[255,0,0],[0,0,255]],party:[[0,255,0]]}};
check('palette_precedence_normalization_linear_average_and_single_stop',()=>{
  const a = {effect:' Caribbean ',rgb_color:[0,255,0]};
  assert.deepEqual(C.resolveLightColour(a,look),{rgb:[188,0,188],palette:[[255,0,0],[0,0,255]]});
  assert.deepEqual(R.lightColor(a,look),[188,0,188]);
  assert.deepEqual(C.resolveLightColour({effect:'PARTY'},look),{rgb:[0,255,0]});
  assert.deepEqual(C.resolveLightColour({effect:'different',rgb_color:[1,2,3]},look),{rgb:[1,2,3]});
  assert.deepEqual(C.resolveLightColour({},look),{rgb:[0,80,255]});
  for(const attrs of [{rgb_color:[3,4,5]},{hs_color:[120,100]},{xy_color:[.3,.3]},{effect:'Blue'},{color_temp_kelvin:2700},{color_temp:300}])
    assert.deepEqual(R.lightColor(attrs,look),R.lightColor(attrs),'automatic source wins over fixed');
  for(const domain of ['switch','input_boolean','fan']) assert.deepEqual(emission({state:'on'},domain,look).rgb,look.colour);
  assert.deepEqual(emission({state:'paused'},'media_player',look),emission({state:'paused'},'media_player'));
  assert.equal(markerOnColor('light',{attributes:a},look),'#bc00bc');
  assert.equal(markerOnColor('switch',{},look),'#0050ff');
});
check('malformed_looks_never_throw_or_change_automatic_colour',()=>{
  for(const bad of [null,[],false,'red',{colour:[1,2]},{colour:[1,2,3,4]},{colour:['1',2,3]},
    {colour:[NaN,2,3]},{colour:[256,2,3]},{colour:[1.5,2,3]}, {effects:{caribbean:[[1,2,3]]*5}},
    {effects:{caribbean:Array(5).fill([1,2,3])}},{effects:{caribbean:[[NaN,0,0]]}},
    {effects:{caribbean:'red'}},{effects:{caribbean:[[1,2]]}},{effects:{caribbean:[Array(3)]}},
    {effects:{caribbean:Array(2)}},{effects:[]},{effects:null},{unknown:1}]) {
    assert.deepEqual(C.resolveLightColour({effect:'caribbean'},bad),{rgb:[255,241,201]});
    assert.deepEqual(R.lightColor({rgb_color:[5,6,7]},bad),[5,6,7]);
  }
  assert.deepEqual(R.lightColor(),[255,241,201]);
  assert.deepEqual(R.lightColor({effect:'Deep Blue'}),[0,0,255]);
});
check('line_glow_keeps_every_corner_and_allocates_colours_only_for_palettes',()=>{
  const scene=new THREE.Scene(), tube=new THREE.TubeGeometry(new THREE.LineCurve3(new THREE.Vector3(),new THREE.Vector3(1,0,0)),1,.01,8,false);
  const sphere=new THREE.SphereGeometry(.01,8,4), tubeVertices=tube.attributes.position.count, sphereVertices=sphere.attributes.position.count;
  for(const path of [[[0,0,4],[4,0,4],[4,4,4]],[[0,0,4],[4,0,4],[4,8,4]],
    [[0,0,4],[8,0,4],[8,8,4]],[[0,0,4],[6,0,4],[6,6,4]],[[0,0,4],[4,0,4],[4,4,4],[8,4,4],[8,8,4]]]) {
    const emitter={shape:'line',fixture_id:'rope',path,width_in:1,facing:'down'}, pieces=linePieces(emitter);
    const glow=createFixtureGlow(scene,emitter), geometry=glow.mesh.geometry;
    const segments=pieces.reduce((n,p)=>n+p.path.slice(1).filter((v,i)=>!v.equals(p.path[i])).length,0);
    assert.equal((geometry.attributes.position.count-segments*tubeVertices)/sphereVertices,path.length-2,JSON.stringify(path));
    assert.equal(geometry.getAttribute('color'),undefined);
    glow.update([20,30,40],1,true);glow.update([50,60,70],1,true);
    assert.equal(geometry.getAttribute('color'),undefined,'ordinary glows never upload a colour buffer');
    const palette=[[255,0,0],[0,0,255]];glow.update([188,0,188],1,true,palette);
    const colors=geometry.getAttribute('color');assert.ok(colors);
    let offset=0;
    for(const piece of pieces) {
      const count=piece.path.slice(1).reduce((n,v,i)=>n+(!v.equals(piece.path[i])?tubeVertices:0)+(i<piece.path.length-2?sphereVertices:0),0);
      const expected=C.paletteColour(palette,piece.t);
      for(let i=offset;i<offset+count;i++) assert.deepEqual(new THREE.Color().fromBufferAttribute(colors,i).convertLinearToSRGB().toArray().map(v=>Math.round(v*255)),expected);
      offset+=count;
    }
    assert.equal(offset,colors.count);glow.stop();
  }
  tube.dispose();sphere.dispose();assert.equal(scene.children.length,0);
});
check('line_centres_sample_the_whole_bent_run_and_point_uses_average',()=>{
  const plan={buildings:[],site:{}}, line={id:'rope',shape:'line',ref:'absolute',path:[[0,0,4],[4,0,4],[4,8,4]],width_in:1,facing:'down'};
  const layout={markers:[],light_fixtures:{'light.pool':[line,{id:'bulb',shape:'point',ref:'absolute',at:[0,0,4]}]}};
  const states={'light.pool':{state:'on',attributes:{effect:'Caribbean',rgb_color:[0,255,0]}}};
  const resolved=resolveEmitters(layout,states,plan,{looks:{'light.pool':look}}), pieces=linePieces(resolved[0]);
  assert.equal(pieces.length,3);assert.deepEqual(pieces.map(p=>p.t),[1/6,1/2,5/6]);
  const scene=new THREE.Scene(), rig=R.createRealLights({scene,tier:'max'});rig.show(true);
  const candidates=resolved.map(e=>({device:e.fixture_id,emitter:e,position:new THREE.Vector3(...e.position),at:e.at||e.path[0],rgb:e.rgb,palette:e.palette,intensity:1,distance:10}));
  rig.update(candidates,[0,0,0]);
  const colours=[];scene.traverse(o=>{if(o.isRectAreaLight&&o.intensity>0)colours.push([o.position.x,o.position.z,o.color.clone().convertLinearToSRGB().toArray().map(v=>Math.round(v*255))]);});
  colours.sort((a,b)=>a[0]-b[0]||b[1]-a[1]);
  assert.deepEqual(colours.map(p=>p[2]),pieces.map(p=>C.paletteColour(look.effects.caribbean,p.t)));
  assert.ok(colours[0][2][0]>colours[0][2][2]);assert.ok(colours.at(-1)[2][2]>colours.at(-1)[2][0]);
  assert.deepEqual(colours[1][2],[188,0,188]);
  let point;scene.traverse(o=>{if(o.isPointLight&&o.intensity>0)point=o;});
  assert.deepEqual(point.color.clone().convertLinearToSRGB().toArray().map(v=>Math.round(v*255)),[188,0,188]);
  const glow=createFixtureGlow(scene,resolved[0]);glow.update(resolved[0].rgb,1,true,resolved[0].palette);
  assert.equal(glow.mesh.material.vertexColors,true);
  const colors=glow.mesh.geometry.attributes.color;
  const first=new THREE.Color().fromBufferAttribute(colors,0).convertLinearToSRGB().toArray().map(v=>Math.round(v*255));
  const last=new THREE.Color().fromBufferAttribute(colors,colors.count-1).convertLinearToSRGB().toArray().map(v=>Math.round(v*255));
  assert.deepEqual(first,colours[0][2]);assert.deepEqual(last,colours.at(-1)[2]);
  const cleared=resolveEmitters(layout,states,plan);assert.deepEqual(cleared[0].rgb,[0,255,0]);assert.equal(cleared[0].palette,undefined);
  rig.update(candidates.map((row,i)=>({...row,emitter:cleared[i],rgb:cleared[i].rgb,palette:undefined})),[0,0,0]);
  scene.traverse(o=>{if(o.isLight&&o.intensity>0)assert.deepEqual(o.color.clone().convertLinearToSRGB().toArray().map(v=>Math.round(v*255)),[0,255,0]);});
  glow.update(cleared[0].rgb,1,true);assert.equal(glow.mesh.material.vertexColors,false);
  glow.stop();rig.stop();assert.equal(scene.children.length,0);
});
check('mounted_save_updates_bulb_marker_bake_and_clear_without_another_read',async()=>{
  states=initialStates();states['light.a1'].attributes={effect:'Caribbean',rgb_color:[0,255,0]};
  const customLayout={...layout,can_edit_house:true}, calls=[], requests=[];
  const view=makeView('low'), baked=[];view.bake={fresh:()=>['a1'],light:(...args)=>baked.push(args)};
  const live=await mountLive(view,{api:async(path,init)=>{
    requests.push(path);
    if(path==='api/house/twin/light-looks') {
      if(!init?.method)return {ok:true,json:async()=>({'light.a1':look})};
      const body=JSON.parse(init.body);calls.push(body);return {ok:true,json:async()=>({look:body.look||{}})};
    }
    return {ok:true,json:async()=>path==='api/house/live'?customLayout:{states,reachable:true}};
  }});
  try {
    live.setMode('lights');assert.deepEqual(row(live,'a1').rgb,[188,0,188]);
    assert.deepEqual(bulb(view,'a1')[0].material.color.clone().convertLinearToSRGB().toArray().map(v=>Math.round(v*255)),[188,0,188]);
    assert.ok(baked.some(args=>args[0]==='a1'&&args[1][0]===188));
    assert.equal(live.marker('a1').color,'#bc00bc');
    assert.ok(await live.lightLooks.save('light.a1',null));assert.deepEqual(row(live,'a1').rgb,[0,255,0]);
    assert.equal(live.marker('a1').color,'#00ff00');assert.deepEqual(calls,[{entity_id:'light.a1',look:null}]);
    assert.equal(requests.filter(p=>p==='api/house/twin/light-looks').length,2,'one mount fetch and one save');
  } finally {live.stop();}
});
""" + BASE[BASE.index('let passed = 0;'):]

if __name__ == '__main__':
    harness.DRIVER = DRIVER
    sys.exit(1 if harness.run() else 0)

"""Real renderPage: a placed model shadows the floor; a lamp shade keeps light."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import house_twin_live_harness as L

SCENE = r"""
async () => {
 const THREE=await import('three'),B=window.chfBase;
 const {renderPage}=await import(B+'static/twin/bake/bake_pass.js');
 const SIZE=128,RECT={x:2,y:2,w:120,h:120},FT=.3048;
 const renderer=new THREE.WebGLRenderer({antialias:false});renderer.setSize(32,32);
 const floor=new THREE.Mesh(new THREE.PlaneGeometry(6,6).toNonIndexed().rotateX(-Math.PI/2),
  new THREE.MeshStandardMaterial({name:'floor'}));floor.userData.merged=true;
 const pos=floor.geometry.attributes.position;
 floor.geometry.setAttribute('uv3',new THREE.Float32BufferAttribute(Array.from({length:pos.count},(_,i)=>[
  (RECT.x+(pos.getX(i)+3)/6*RECT.w)/SIZE,(RECT.y+(3-pos.getZ(i))/6*RECT.h)/SIZE]).flat(),2));
 const chart={id:0,mesh:floor,faces:[0,1],rect:RECT,page:0,room:0,outdoor:false};
 const scene=new THREE.Scene();scene.add(floor);
 const plan={site:{furniture:[{id:'box',kind:'chair',at:[0,0]}]}};
 const lamp={device:'lamp',absolute:true,at:[0,0,2/FT],range:6/FT};
 const models=new THREE.Group();let ready=false,waits=0;
 const view={scene,plan,bake:{modelReady:async()=>{await Promise.resolve();ready=true;waits++;},
  modelRoot:()=>ready?models:null}};
 const bake=()=>renderPage(view,renderer,[chart],SIZE,lamp,{room:{page:SIZE}},{room:{charts:[chart]}});
 const sample=(bytes,x,z)=>{const u=RECT.x+Math.floor((x+3)/6*RECT.w),v=RECT.y+Math.floor((3-z)/6*RECT.h);
  return bytes[(v*SIZE+u)*4];};
 const baseline=await bake();
 const box=new THREE.Mesh(new THREE.BoxGeometry(.5,.5,.5).toNonIndexed().translate(0,.75,0),
  new THREE.MeshStandardMaterial());box.geometry.userData.bakeExcluded=true;box.userData.merged=true;
 box.userData.snapRanges=[{start:0,count:36,kind:'furniture',pieceId:'box'}];models.add(box);
 ready=false;const shaded=await bake();
 box.geometry.dispose();box.geometry=new THREE.BoxGeometry(.5,.5,.5).toNonIndexed().translate(0,2,0);
 box.geometry.userData.bakeExcluded=true;
 const enclosed=await bake();
 const result={under:sample(shaded,0,0),away:sample(shaded,1.5,0),open:sample(baseline,0,0),waits,
  enclosed:[sample(enclosed,0,0),sample(enclosed,1.5,0)],baseline:[sample(baseline,0,0),sample(baseline,1.5,0)]};
 renderer.dispose();return result;
}
"""


def test_model_shadows_floor_and_shade_keeps_light(result):
    assert result['open'] > 240 and result['away'] > 240, result
    assert result['under'] < .5 * result['away'], result
    assert all(got >= .9 * base for got, base in zip(result['enclosed'], result['baseline'])), result
    assert result['waits'] == 3, 'each page waits for its physical model source'


def run():
    served = L.serve()
    L.reset()
    errors = []
    with served.browser(launch_args=L.GPU_ARGS) as page:
        page.on('console', lambda m: errors.append(m.text[:400]) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
        L.H.signed_in(page)
        L.open_twin(page, served, query='tier=high&test=1')
        result = page.evaluate(SCENE)
    print('MEASURED', json.dumps(result))
    assert not errors, errors[:3]
    test_model_shadows_floor_and_shade_keeps_light(result)
    print('Passed: test_model_shadows_floor_and_shade_keeps_light\n1/1 passed')
    return 0


if __name__ == '__main__':
    sys.exit(run())

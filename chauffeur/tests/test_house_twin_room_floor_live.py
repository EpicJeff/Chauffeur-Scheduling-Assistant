"""Browser acceptance for Claude. Written only; NOT run by Codex."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import house_editor_model_harness as H


def fixture(_):
    outline = [[0, 0], [20, 0], [20, 10], [0, 10]]
    walls = [{'id': f'w{i}', 'level': 'L1', 'from': p, 'to': outline[(i+1) % 4],
              'height': 10, 'thickness': .5, 'exterior': True} for i, p in enumerate(outline)]
    walls.append({'id': 'shared', 'level': 'L1', 'from': [10, 0], 'to': [10, 10],
                  'height': 10, 'thickness': .5, 'exterior': False})
    return {'schema': 'chauffeur.twin.plan/2', 'units': 'ft', 'materials': {},
            'site': {'lot': [[-20, -20], [40, -20], [40, 30], [-20, 30]]}, 'buildings': [{
                'id': 'b', 'name': 'House', 'base': 2, 'position': [0, 0], 'rotation': 0,
                'foundation': {'mode': 'fixed', 'offset_ft': 0, 'thickness_ft': 1},
                'levels': [{'id': 'L1', 'name': 'Main floor', 'elevation': 0, 'ceiling': 10}],
                'rooms': [{'id': 'living', 'name': 'Living room', 'level': 'L1', 'polygon': [[0, 0], [10, 0], [10, 10], [0, 10]]},
                          {'id': 'garage', 'name': 'Garage', 'level': 'L1', 'polygon': [[10, 0], [20, 0], [20, 10], [10, 10]]}],
                'walls': walls, 'openings': [{'id': 'garage-door', 'kind': 'garage', 'wall': 'w1', 'at': 5, 'width': 6, 'sill': 0, 'head': 7}],
                'roof': {'sections': []}, 'lights': [], 'fixtures': [], 'stairs': []}]}


def scenario_garage_floor_door_and_undo():
    served = H.serve(mutate=fixture)
    if served is None:
        return
    with served.browser(launch_args=H.GPU_ARGS) as page:
        H.open_editor(page, served)
        page.evaluate("()=>{window.__twin.bake?.stop();window.__editor.clickPiece('garage','b');}")
        shelf = page.locator('#piece-card')
        shelf.get_by_label('Floor height (relative to this floor)', exact=False).fill('-2')
        shelf.get_by_label('Floor height (relative to this floor)', exact=False).press('Enter')
        page.wait_for_function("()=>window.__twin.ready&&window.__twin.plan.buildings[0].rooms.find(r=>r.id==='garage').floor_offset_ft===-2")
        def geometry():
            return page.evaluate("""async()=>{
              const T=await import('three'),v=window.__twin,meshes=[];v.scene.updateMatrixWorld(true);
              v.groups.levels['b:L1'].traverse(o=>{if(o.isMesh&&o.material.name==='floor'&&!o.layers.isEnabled(31))meshes.push(o);});
              const hit=x=>new T.Raycaster(new T.Vector3(x*.3048,30,-5*.3048),new T.Vector3(0,-1,0)).intersectObjects(meshes,false)[0].point.y/.3048;
              let bottom=Infinity;v.groups.levels['b:L1'].traverse(o=>{if(!o.isMesh||o.material.name!=='window_frame')return;
                const p=o.geometry.attributes.position;for(let i=0;i<p.count;i++){const q=new T.Vector3().fromBufferAttribute(p,i).applyMatrix4(o.matrixWorld);
                  if(Math.abs(q.x/.3048-20)<.6)bottom=Math.min(bottom,q.y/.3048);}});
              return {garage:hit(15),living:hit(5),door:bottom};
            }""")
        got = geometry()
        H.check(abs(got['garage']) < .02 and abs(got['living']-2) < .02, ('garage meets grade; living remains raised', got))
        H.check(abs(got['door']+.08) < .02, ('garage door frame reaches the floor', got))
        page.click('#rail-undo')
        page.wait_for_function("()=>window.__twin.ready&&window.__twin.plan.buildings[0].rooms.find(r=>r.id==='garage').floor_offset_ft===0")
        H.check(abs(geometry()['garage']-2) < .02, 'undo restores the raised garage slab')
        page.click('#rail-redo')
        page.wait_for_function("()=>window.__twin.ready&&window.__twin.plan.buildings[0].rooms.find(r=>r.id==='garage').floor_offset_ft===-2")
        H.check(abs(geometry()['garage']) < .02, 'redo returns the garage to grade')


if __name__ == '__main__':
    H.run([scenario_garage_floor_door_and_undo])

"""Browser acceptance for Claude. Written only; NOT run by Codex."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import house_editor_model_harness as H
from test_house_twin_room_floor_live import fixture as house_fixture


def fixture(_):
    plan = house_fixture(None)
    building = plan['buildings'][0]
    building['porches'] = [{'id': 'porch', 'name': 'Front porch', 'floor': 0,
                           'polygon': [[0, -6], [10, -6], [10, 0], [0, 0]],
                           'columns': [{'at': [.5, -5.5], 'size': .5}, {'at': [9.5, -5.5], 'size': .5}]}]
    return plan


def scenario_solid_stone_and_undo():
    served = H.serve(mutate=fixture)
    if served is None:
        return
    with served.browser(launch_args=H.GPU_ARGS) as page:
        H.open_editor(page, served)
        page.evaluate("()=>{window.__twin.bake?.stop();window.__editor.clickPiece('porch','b');}")
        shelf = page.locator('#piece-card')
        # Finishes are shared material slots now (v2.499.835); Posts hides the solid base slot.
        H.check(not shelf.locator('[data-material-slot="Solid base"]').is_visible(), 'posts hides solid fields')
        shelf.get_by_label('Foundation', exact=True).select_option('solid')
        page.wait_for_function("()=>window.__twin.ready&&window.__twin.plan.buildings[0].porches[0].foundation.type==='solid'")
        H.check(shelf.locator('[data-material-slot="Solid base"]').is_visible(), 'solid shows its base material slot (default stone)')

        def geometry():
            return page.evaluate("""async()=>{
              const T=await import('three'),v=window.__twin;v.scene.updateMatrixWorld(true);
              const meshes=[];v.groups.levels['b:L1'].traverse(o=>{
                if(o.isMesh&&!o.layers.isEnabled(31))meshes.push(o);
              });
              const ray=(x,z,role)=>new T.Raycaster(new T.Vector3(x*.3048,z*.3048,9*.3048),new T.Vector3(0,0,-1))
                .intersectObjects(meshes.filter(o=>o.material.name===role),false)[0];
              const base=ray(5,1,'base'),post=ray(.5,4,'trim');
              return {stone:!!base,edge:base?-base.point.z/.3048:null,roofPost:!!post};
            }""")

        got = geometry()
        H.check(got['stone'] and abs(got['edge']-(-6+1/12)) < .02, ('stone base reaches ground and is inset one inch', got))
        H.check(got['roofPost'], ('roof posts remain', got))
        # Switching to Solid is one undo step.
        page.click('#rail-undo')
        page.wait_for_function("()=>window.__twin.ready&&window.__twin.plan.buildings[0].porches[0].foundation.type==='posts'")
        H.check(not geometry()['stone'] and geometry()['roofPost'], 'undo restores posts and keeps roof supports')
        page.click('#rail-redo')
        page.wait_for_function("()=>window.__twin.ready&&window.__twin.plan.buildings[0].porches[0].foundation.type==='solid'")
        H.check(geometry()['stone'], 'redo restores the stone base')


if __name__ == '__main__':
    H.run([scenario_solid_stone_and_undo])

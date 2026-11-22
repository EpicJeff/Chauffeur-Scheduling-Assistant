"""All manual-editor regressions in production's non-drawing metadata mode."""
import sys
import test_twin_bake_editor_js as E
import test_twin_bake_runtime_js as R
DRIVER=E.DRIVER.replace('display: extra.display !== false', "display: extra.mode !== 'manual'").replace(
    "const ready = desk => until(()=>!!desk.controller.packing(),'manual controller ready');",
    "const ready = async desk => {await until(()=>/^Lighting /.test(outputOf(desk)?.textContent),'metadata ready');assert.equal(desk.controller.packing(),null,'no atlas preparation before a press');assert.equal(desk.controller.held(),null,'the editor allocates no page arrays');};")
# Round three defers the new geometry key to the press and reports saved-round
# edits conservatively. The original drawing/manual harness still checks keys.
DRIVER=DRIVER.replace("assert.notEqual(next.controller.state().key,oldKey);", "assert.equal(next.controller.packing(),null);assert.equal(next.controller.state().key,oldKey);")
DRIVER=DRIVER.replace("{mode:'manual',plan,poll:50,host:new Node('div')}","{mode:'manual',plan,view:{round:43},poll:50,host:new Node('div')}").replace(
    "assert.equal(outputOf(next).textContent,'Lighting out of date: 4 lights');", "assert.equal(outputOf(next).textContent,'Lighting out of date since your edits');")
DRIVER=DRIVER.replace('const oldKey=desk.controller.state().key;', 'let oldKey=desk.controller.state().key;').replace(
    'if(!stopped&&Object.keys(desk.server.manifests.get(oldKey)', 'oldKey ||= desk.controller.state().key;\n   if(!stopped&&Object.keys(desk.server.manifests.get(oldKey)')
DRIVER=DRIVER.replace('assert.equal(desk.renderer.log.renders,0);assert.equal(desk.server.writes().length,0);',
    "assert.equal(desk.renderer.log.renders,0);assert.equal(desk.server.writes().length,0);assert.equal(desk.controller.packing(),null);assert.equal(outputOf(desk).textContent,'Lighting is up to date');",1)
if __name__ == '__main__':
    R.DRIVER=DRIVER
    sys.exit(R.run())

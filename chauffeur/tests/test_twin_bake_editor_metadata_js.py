"""All manual-editor regressions in production's non-drawing metadata mode."""
import sys
import test_twin_bake_editor_js as E
import test_twin_bake_runtime_js as R
DRIVER=E.DRIVER.replace('display: extra.display !== false', "display: extra.mode !== 'manual'").replace(
    "const ready = desk => until(()=>!!desk.controller.packing(),'manual controller ready');",
    "const ready = async desk => {await until(()=>desk.controller.state().key && /^Lighting /.test(outputOf(desk)?.textContent),'metadata ready');assert.equal(desk.controller.held(),null,'the editor allocates no page arrays');};")
if __name__ == '__main__':
    R.DRIVER=DRIVER
    sys.exit(R.run())

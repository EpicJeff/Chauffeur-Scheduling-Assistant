"""Save/history bake gates through the real editor boot and edit queue."""
from pathlib import Path
import re
import sys
from twin_live_node_rig import run
from test_twin_edit_queue_editor_js import DRIVER, STUBS, ROOT
STUBS=STUBS.replace('export const mountTwin=async()=>globalThis.editorView;',
    'export const mountTwin=async(host,options)=>{globalThis.bakeOptions=options.bake;globalThis.bakeSync=[];globalThis.editorView.bake={syncBlocked(){globalThis.bakeSync.push(options.bake.blocked());}};return globalThis.editorView;};').replace(
    'export const createTimeline=()=>({sync(){},preview:()=>null,now:async()=>{}});',
    'export const createTimeline=options=>(globalThis.timelineOptions=options,{sync(){},preview:()=>null,now:async()=>{}});').replace(
    'dismiss(){}});','dismiss(){},resume(){}});')
DRIVER=DRIVER.replace('await until(()=>writes.length===1);',
    "await until(()=>writes.length===1);assert.equal(bakeOptions.blocked(),'Saving edits; bake when they land');assert.ok(bakeSync.includes('Saving edits; bake when they land'));ok('bake gate follows the actual saving queue');").replace(
    "assert.ok(Number.isFinite(window.__twinEditTiming.at(-1).settle));",
    "assert.ok(Number.isFinite(window.__twinEditTiming.at(-1).settle));assert.equal(bakeOptions.blocked(),'');assert.equal(editorView.round,rounds.at(-1).id);timelineOptions.onPreview(true);assert.equal(bakeOptions.blocked(),'Back to now to bake');assert.ok(bakeSync.includes('Back to now to bake'));timelineOptions.onPreview(false);assert.equal(bakeOptions.blocked(),'');ok('history preview blocks baking immediately and Back to now clears it');")
if __name__ == '__main__':
    ids=sorted(set(re.findall(r'id="([\w-]+)"',(ROOT/'templates/house_editor.html').read_text(encoding='utf-8'))) | {'piece-card','rail-undo','rail-redo','rail-add-effect','editor-save-state'})
    ids += ['rail-'+name for name in ['move','rotate','scale','draw-room','draw-wall','split-room','add-door','add-window','add-anchor','add-level','delete','roof'] if 'rail-'+name not in ids]
    sys.exit(bool(run(DRIVER,{'stubs':STUBS,'ids':ids,'case':'kept_release_draws_once'},timeout=45)))

"""Finishes per building in the generator (plan .superpowers/sdd/
2026-11-07-house-editor-slice-1b-i, Task 4, amendment A9): buildTwin builds
each building's material map from plan.materials overlaid by that building's
own materials, so two buildings with different wall finishes each show their
own, and a role the building does not set keeps the plan's.

Runs static/twin/twin_generator.js under node with the vendored three
(static/vendor/three-r187) resolved for the bare 'three' imports through a
module resolve hook. The kit is the real modern_farmhouse kit with an empty
manifest, so every material is a plain coloured one and nothing is fetched.
Skips (rather than fails) when node is unavailable.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_materials_js.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_materials_js_'))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from services import twin_library as tl  # noqa: E402

TWIN = os.path.join(ROOT, 'static', 'twin')
VENDOR = os.path.join(ROOT, 'static', 'vendor', 'three-r187')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


DRIVER = r"""
import { registerHooks } from 'node:module';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
const job = JSON.parse(process.argv[2]);
registerHooks({
  resolve(spec, ctx, next) {
    if (spec === 'three') return { url: pathToFileURL(path.join(job.vendor, 'three.module.js')).href, shortCircuit: true };
    if (spec.startsWith('three/addons/')) return { url: pathToFileURL(path.join(job.vendor, 'addons', spec.slice('three/addons/'.length))).href, shortCircuit: true };
    return next(spec, ctx);
  },
  load(url, ctx, next) {
    if (url.startsWith('file:') && url.endsWith('.js')) return { ...next(url, { ...ctx, format: 'module' }), format: 'module' };
    return next(url, ctx);
  },
});
globalThis.window = globalThis.window || {};
const gen = await import(pathToFileURL(path.join(job.twin, 'twin_generator.js')).href);
const out = gen.buildTwin(job.plan, job.kit, 'low');
// Building id -> material role -> colours used by that building's meshes.
const seen = {};
// Piece keys are `${building id}:${piece id}`; merging may clear userData.
for (const [key, objects] of out.pieces) for (const o of objects) {
  const m = o.material, bid = key.slice(0, key.indexOf(':'));
  if (!m || !m.name || !m.color || !bid) continue;
  ((seen[bid] = seen[bid] || {})[m.name] = seen[bid][m.name] || new Set()).add('#' + m.color.getHexString());
}
console.log(JSON.stringify(Object.fromEntries(Object.entries(seen).map(
  ([bid, roles]) => [bid, Object.fromEntries(Object.entries(roles).map(([role, set]) => [role, [...set].sort()]))]))));
"""


def _node():
    return shutil.which('node')


def _building(bid, x0, materials=None):
    outline = [[0, 0], [20, 0], [20, 15], [0, 15]]
    walls = [{'id': f'{bid}-wall-{i}', 'level': 'L1', 'from': a, 'to': b, 'height': 9, 'thickness': 0.5,
              'exterior': True, 'state': 'settled'}
             for i, (a, b) in enumerate(zip(outline, outline[1:] + outline[:1]))]
    building = {'id': bid, 'name': bid, 'position': [x0, 0], 'rotation': 0,
                'levels': [{'id': 'L1', 'name': 'Main floor', 'elevation': 0, 'ceiling': 9, 'outline': outline}],
                'walls': walls, 'openings': [], 'rooms': [], 'roof': {'sections': []}}
    if materials is not None:
        building['materials'] = materials
    return building


def build(plan):
    d = tempfile.mkdtemp(prefix='twin_materials_js_')
    try:
        with open(os.path.join(d, 'driver.mjs'), 'w', encoding='utf-8') as f:
            f.write(DRIVER)
        job = {'vendor': VENDOR, 'twin': TWIN, 'plan': plan, 'kit': {**tl.kit('modern_farmhouse'), 'manifest': {}}}
        result = subprocess.run(['node', os.path.join(d, 'driver.mjs'), json.dumps(job)],
                                capture_output=True, text=True, timeout=120)
        check(result.returncode == 0, result.stderr[-3000:])
        return json.loads(result.stdout.strip().splitlines()[-1])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def scenario_plan_finishes_alone_reach_every_building():
    # Today's behaviour, kept: with no building finishes every building uses the plan's.
    plan = {'units': 'ft', 'materials': {'siding': {'id': 'board_and_batten', 'color': '#112233'}},
            'buildings': [_building('house', 0), _building('shed', 40)], 'site': {}}
    seen = build(plan)
    check(seen['house']['siding'] == ['#112233'] and seen['shed']['siding'] == ['#112233'], seen)


def scenario_building_finishes_overlay_the_plan_per_building():
    plan = {'units': 'ft',
            'materials': {'siding': {'id': 'board_and_batten', 'color': '#112233'},
                          'floor': {'id': 'wood_floor', 'color': '#445566'}},
            'buildings': [_building('house', 0),
                          _building('shed', 40, {'siding': {'id': 'board_and_batten', 'color': '#aa0000'}})],
            'site': {}}
    seen = build(plan)
    check(seen['house']['siding'] == ['#112233'], ('the house keeps the plan siding', seen['house']))
    check(seen['shed']['siding'] == ['#aa0000'], ('the shed shows its own siding', seen['shed']))
    check(seen['house']['floor'] == ['#445566'] and seen['shed']['floor'] == ['#445566'],
          ('a role the shed does not set keeps the plan finish', seen))


SCENARIOS = (
    scenario_plan_finishes_alone_reach_every_building,
    scenario_building_finishes_overlay_the_plan_per_building,
)


if __name__ == '__main__':
    if not _node():
        print('  skip  node is not available')
        sys.exit(0)
    failed = []
    for fn in SCENARIOS:
        try:
            fn()
        except Exception:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__)
            traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(SCENARIOS) - len(failed)}/{len(SCENARIOS)} passed')
    sys.exit(1 if failed else 0)

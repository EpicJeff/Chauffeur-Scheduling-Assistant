"""Yard trees are generated once, with the same result as EZ-Tree's loadPreset path.

EZ-Tree's loadPreset() generates the whole tree, and the yard then set the saved seed and
generated it again, so every plant was built twice (found 2026-11-13, about half of the
yard build). Runs the real vendored EZ-Tree under Node.
"""
from pathlib import Path
import sys
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
PREFIX = '\n'.join(line for line in PRELUDE.splitlines() if "if (spec === './twin_yard.js')" not in line)
PREFIX = PREFIX.replace("if (spec === 'three')", """if (spec === '@dgreenheck/ez-tree') return {url: file('static/vendor/ez-tree/ez-tree.es.js'), shortCircuit: true};
  if (spec === 'three')""")

DRIVER = PREFIX + r"""
const EZ = await import('@dgreenheck/ez-tree');
const {presetTree} = await import(file('static/twin/twin_yard.js'));
let generations = 0;
const generate = EZ.Tree.prototype.generate;
EZ.Tree.prototype.generate = function (...args) { generations++; return generate.apply(this, args); };
const positions = tree => { const out = []; tree.traverse(o => { if (o.geometry?.attributes?.position) out.push(Array.from(o.geometry.attributes.position.array)); }); return out; };
const presets = Object.keys(EZ.TreePreset);
assert.ok(presets.length > 3, 'the vendored preset table is exported');
let checked = 0;
for (const preset of presets.slice(0, 4)) for (const seed of [1, 7]) {
  generations = 0;
  const old = new EZ.Tree(); old.loadPreset(preset); old.options.seed = seed; old.generate();
  assert.equal(generations, 2, `${preset}: the old path generated twice`);
  generations = 0;
  const once = presetTree(preset, seed);
  assert.equal(generations, 1, `${preset}: generated once`);
  assert.equal(once.options.seed, seed);
  assert.deepEqual(positions(once), positions(old), `${preset} seed ${seed}: identical geometry`);
  checked++;
}
console.log(`ok   ${checked} preset/seed pairs generate once with identical geometry`);
"""


def main():
    code, out = run_node(DRIVER, {'root': str(ROOT)}, timeout=300)
    print(out.strip())
    if code is None:
        return 0
    if code != 0:
        print('FAIL tree generation')
        return 1
    print('1/1 passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())

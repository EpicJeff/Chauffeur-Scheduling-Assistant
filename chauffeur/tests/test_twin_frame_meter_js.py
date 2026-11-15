"""The frame meter (?perf=1) runs in node against a small DOM double: numbers, render scale, software warning."""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

SCRIPT = r"""
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const node = tag => ({ tag, style: {}, children: [], listeners: {}, textContent: '', removed: false,
  append(...kids) { this.children.push(...kids); }, appendChild(kid) { this.children.push(kid); return kid; },
  addEventListener(name, fn) { this.listeners[name] = fn; }, remove() { this.removed = true; } });
globalThis.document = { createElement: node };
const { mountFrameMeter } = await import(pathToFileURL(process.argv[2]).href);
let passed = 0;
const check = (name, fn) => { fn(); ++passed; console.log('  ok  ', name); };
const mount = gpu => {
  const host = node('div'), ratios = [];
  const renderer3 = { domElement: { width: 1920, height: 1080 }, setPixelRatio: r => ratios.push(r) };
  const meter = mountFrameMeter(host, { renderer3, gpu, tier: 'low', pixelRatio: 1,
    stats: () => ({ drawCalls: 812, triangles: 240000 }) });
  const [text, button] = host.children[0].children;
  return { host, ratios, meter, text, button, box: host.children[0] };
};

check('reports_frame_time_script_time_draws_and_size', () => {
  const m = mount('ANGLE (Broadcom, V3D 7.1)');
  const start = performance.now();
  // 20 frames, 50 ms apart, 30 ms of script each, one 200 ms hitch in the last half-second window.
  let now = start;
  for (let i = 0; i < 20; ++i) { now += i === 17 ? 200 : 50; m.meter.frame(now, 30); }
  const lines = m.text.textContent.split('\n');
  assert.match(lines[0], /fps/); assert.match(lines[0], /worst 200/);
  assert.equal(lines[1], 'script 30.0 ms a frame');
  assert.equal(lines[2], '812 draws   240000 triangles');
  assert.equal(lines[3], '1920 x 1080 px   tier low');
  assert.equal(lines[4], 'ANGLE (Broadcom, V3D 7.1)');
  assert.equal(lines.length, 5, 'no software warning on a real GPU');
});

check('render_scale_cycles_and_stop_restores_it', () => {
  const m = mount('gpu');
  assert.match(m.button.textContent, /100%/);
  m.button.listeners.click(); assert.match(m.button.textContent, /75%/);
  m.button.listeners.click(); assert.match(m.button.textContent, /50%/);
  m.button.listeners.click(); assert.match(m.button.textContent, /100%/);
  assert.deepEqual(m.ratios, [.75, .5, 1]);
  m.meter.stop();
  assert.equal(m.box.removed, true); assert.equal(m.ratios.at(-1), 1);
});

check('software_renderer_is_called_out', () => {
  const m = mount('Google SwiftShader');
  let now = performance.now();
  for (let i = 0; i < 12; ++i) { now += 60; m.meter.frame(now, 1); }
  assert.match(m.text.textContent, /SOFTWARE RENDERING/);
});
console.log(`${passed}/3 passed`);
"""


def main():
    with tempfile.TemporaryDirectory() as tmp:
        script = os.path.join(tmp, 'meter.mjs')
        with open(script, 'w', encoding='utf-8') as f:
            f.write(SCRIPT)
        r = subprocess.run(['node', script, os.path.join(ROOT, 'static', 'twin', 'frame_meter.js')],
                           capture_output=True, text=True, encoding='utf-8')
    print(r.stdout + r.stderr)
    sys.exit(0 if r.returncode == 0 and '3/3 passed' in r.stdout else 1)


if __name__ == '__main__':
    main()

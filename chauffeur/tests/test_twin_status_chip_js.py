"""One chip says who is waiting and what it costs (plan
docs/superpowers/plans/2026-11-10-house-guided-build-piece-4.md, Task 6;
brief .superpowers/sdd/2026-11-10-house-guided-build-piece-4/task-6-brief.md;
Global Constraints: the words Working and Waiting on you, `$x.xx so far`,
`about $x.xx`, two decimals; Stop visible whenever a build is running).

Runs the REAL static/twin/editor/status_chip.js under node with a small DOM
double (createElement, textContent, innerHTML for plain markup, hidden,
classList, attributes, append/replaceChildren, querySelector by tag, #id,
.class and [attr]). Interface under test:

    createStatusChip(host) -> {update({state, pause, cost, estimate})}

`state` is the build state ('running', 'paused', 'checkpoint', 'done',
'stopped', 'failed') or null with no build; `pause` the build's pause (or
null); `cost` the household's ledger total in dollars (a number, from
/api/house/editor/state cost.total); `estimate` the running build's remaining
estimate in dollars (a number, or null). What the chip SAYS is its visible
text: text under host, skipping any node that is hidden (the hidden property
or attribute, or style.display 'none'). The Stop button is a visible button
under host whose text is `Stop`; document.getElementById('editor-stop')
answers the page's existing Stop button (hidden, not yet in the chip), so a
chip may adopt it or draw its own.

Tests:
  chip_words_follow_state
  spend_and_estimate_format

Run from chauffeur/:  python tests/test_twin_status_chip_js.py
"""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

DRIVER = r"""
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const root = process.argv[2], which = process.argv[3];
const VOID = new Set(['br', 'hr', 'img', 'input', 'meta', 'link', 'wbr']);
const decode = s => s.replace(/&nbsp;/g, ' ').replace(/&middot;/g, '·').replace(/&lt;/g, '<')
  .replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&#(\d+);/g, (_, n) => String.fromCharCode(+n))
  .replace(/&amp;/g, '&');
class ClassList {
  constructor(node) { this.node = node; }
  get list() { return String(this.node.className || '').split(/\s+/).filter(Boolean); }
  add(...names) { this.node.className = [...new Set([...this.list, ...names])].join(' '); }
  remove(...names) { this.node.className = this.list.filter(n => !names.includes(n)).join(' '); }
  contains(name) { return this.list.includes(name); }
  toggle(name, force) { const on = force === undefined ? !this.contains(name) : !!force; on ? this.add(name) : this.remove(name); return on; }
}
class Node extends EventTarget {
  constructor(tag = 'div') {
    super(); this.tagName = tag.toUpperCase(); this.nodeName = this.tagName; this.children = []; this.childNodes = this.children;
    this.parentElement = null; this.parentNode = null; this._text = ''; this.attributes = {}; this.style = {}; this.dataset = {};
    this.className = ''; this.classList = new ClassList(this); this.hidden = false; this.disabled = false; this.id = '';
  }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
  set textContent(v) { for (const c of this.children) { c.parentElement = null; c.parentNode = null; } this.children.length = 0; this._text = String(v ?? ''); }
  get innerText() { return this.textContent; }
  set innerText(v) { this.textContent = v; }
  get firstChild() { return this.children[0] || null; }
  get firstElementChild() { return this.children[0] || null; }
  get isConnected() { return true; }
  set innerHTML(html) { this.textContent = ''; parseInto(this, String(html ?? '')); }
  get innerHTML() { return this.textContent; }
  setAttribute(k, v) {
    this.attributes[k] = String(v);
    if (k === 'id') this.id = String(v); else if (k === 'class') this.className = String(v); else if (k === 'hidden') this.hidden = true;
    else if (k === 'disabled') this.disabled = true; else if (k.startsWith('data-')) this.dataset[k.slice(5).replace(/-(\w)/g, (_, c) => c.toUpperCase())] = String(v);
  }
  getAttribute(k) { if (k === 'id') return this.id || null; if (k === 'class') return this.className || null; if (k === 'hidden') return this.hidden ? '' : null; return k in this.attributes ? this.attributes[k] : null; }
  hasAttribute(k) { return this.getAttribute(k) !== null; }
  removeAttribute(k) { delete this.attributes[k]; if (k === 'hidden') this.hidden = false; if (k === 'disabled') this.disabled = false; if (k === 'class') this.className = ''; }
  toggleAttribute(k, force) { const on = force === undefined ? !this.hasAttribute(k) : !!force; on ? this.setAttribute(k, '') : this.removeAttribute(k); return on; }
  _adopt(n) { if (typeof n === 'string') { const t = new Node('#text'); t._text = n; n = t; } if (n.parentElement) n.remove(); n.parentElement = this; n.parentNode = this; return n; }
  append(...nodes) { for (const n of nodes) this.children.push(this._adopt(n)); }
  appendChild(n) { this.append(n); return n; }
  prepend(...nodes) { this.children.unshift(...nodes.map(n => this._adopt(n))); }
  insertBefore(n, ref) { const i = ref ? this.children.indexOf(ref) : -1; const a = this._adopt(n); i < 0 ? this.children.push(a) : this.children.splice(this.children.indexOf(ref), 0, a); return n; }
  replaceChildren(...nodes) { this.textContent = ''; this.append(...nodes); }
  remove() { const p = this.parentElement; if (p) { const i = p.children.indexOf(this); if (i >= 0) p.children.splice(i, 1); } this.parentElement = null; this.parentNode = null; }
  removeChild(n) { n.remove(); return n; }
  before(...nodes) { const p = this.parentElement; if (!p) return; for (const n of nodes) p.insertBefore(n, this); }
  after(...nodes) { const p = this.parentElement; if (!p) return; const i = p.children.indexOf(this); const adopted = nodes.map(n => p._adopt(n)); p.children.splice(i + 1, 0, ...adopted); }
  replaceWith(...nodes) { this.before(...nodes); this.remove(); }
  contains(n) { for (let p = n; p; p = p.parentElement) if (p === this) return true; return false; }
  closest(sel) { for (let p = this; p; p = p.parentElement) if (matches(p, sel)) return p; return null; }
  matches(sel) { return matches(this, sel); }
  descendants() { return this.children.flatMap(c => [c, ...c.descendants()]); }
  querySelectorAll(sel) { const parts = sel.split(',').map(s => s.trim()); return this.descendants().filter(n => parts.some(s => matchesPath(n, s, this))); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  getBoundingClientRect() { return {left: 0, top: 0, right: 80, bottom: 30, width: 80, height: 30}; }
  focus() {} blur() {} click() { this.dispatchEvent(new Event('click')); }
}
function matches(n, sel) {
  if (n.tagName === '#TEXT') return false;
  const m = sel.match(/^([a-zA-Z0-9-]*)((?:[#.][\w-]+|\[[^\]]+\])*)$/);
  if (!m) return false;
  if (m[1] && n.tagName !== m[1].toUpperCase()) return false;
  for (const part of m[2].match(/[#.][\w-]+|\[[^\]]+\]/g) || []) {
    if (part[0] === '#' && n.id !== part.slice(1)) return false;
    if (part[0] === '.' && !n.classList.contains(part.slice(1))) return false;
    if (part[0] === '[') {
      const [k, v] = part.slice(1, -1).split('=');
      const got = n.getAttribute(k);
      if (got === null) return false;
      if (v !== undefined && got !== v.replace(/^["']|["']$/g, '')) return false;
    }
  }
  return true;
}
function matchesPath(n, sel, scope) {
  const steps = sel.split(/\s+/).filter(s => s !== '>');
  if (!matches(n, steps.at(-1))) return false;
  let p = n.parentElement;
  for (let i = steps.length - 2; i >= 0; i--) {
    while (p && p !== scope.parentElement && !matches(p, steps[i])) p = p.parentElement;
    if (!p) return false;
    p = p.parentElement;
  }
  return true;
}
function parseInto(parent, html) {
  const stack = [parent];
  const re = /<\/([a-zA-Z0-9-]+)\s*>|<([a-zA-Z0-9-]+)((?:\s+[^\s=>\/]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?)*)\s*(\/?)>|([^<]+)/g;
  let m;
  while ((m = re.exec(html))) {
    const top = stack.at(-1);
    if (m[1]) { if (stack.length > 1) stack.pop(); continue; }
    if (m[5] !== undefined) { if (m[5].length) top.append(decode(m[5])); continue; }
    const node = document.createElement(m[2]);
    const attrs = /([^\s=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g;
    let a;
    while ((a = attrs.exec(m[3] || ''))) node.setAttribute(a[1], decode(a[2] ?? a[3] ?? a[4] ?? ''));
    top.append(node);
    if (!m[4] && !VOID.has(m[2].toLowerCase())) stack.push(node);
  }
}
const ids = new Map();
const existingStop = new Node('button');
existingStop.setAttribute('id', 'editor-stop'); existingStop.setAttribute('aria-label', 'Stop build');
existingStop.textContent = 'Stop'; existingStop.hidden = true;
ids.set('editor-stop', existingStop);
globalThis.document = {
  createElement: tag => new Node(tag),
  createTextNode: text => { const t = new Node('#text'); t._text = String(text); return t; },
  createDocumentFragment: () => new Node('#fragment'),
  getElementById: id => ids.get(id) || null,
  querySelector: sel => (sel === '#editor-stop' ? existingStop : null),
  querySelectorAll: () => [],
  addEventListener() {}, removeEventListener() {},
  hidden: false,
};
globalThis.window = {document: globalThis.document, addEventListener() {}, removeEventListener() {},
  showGlobalAlert() {}, promptConfirm: async () => false, chfBase: '/'};
globalThis.requestAnimationFrame = fn => setTimeout(fn, 0);
const top = new Node('header'); top.setAttribute('id', 'editor-top');
const host = new Node('div'); host.setAttribute('id', 'editor-chip'); top.append(host);
let mod;
try { mod = await import(pathToFileURL(root + '/static/twin/editor/status_chip.js').href); }
catch (error) { console.log('FAIL ' + which + ': static/twin/editor/status_chip.js does not load: ' + error.message.split('\n')[0]); process.exit(1); }
assert.equal(typeof mod.createStatusChip, 'function', 'status_chip.js exports createStatusChip');
const chip = mod.createStatusChip(host);
assert.equal(typeof chip?.update, 'function', 'createStatusChip(host).update');
const shownIn = (n, scope) => { for (let p = n; p && p !== scope.parentElement; p = p.parentElement) if (p.hidden || p.style.display === 'none') return false; return true; };
const said = () => {
  const walk = n => (n.hidden || n.style.display === 'none') ? '' : n._text + n.children.map(walk).join('');
  return walk(host).replace(/\s+/g, ' ').trim();
};
const stops = () => [host, ...host.descendants()].filter(n => n.tagName === 'BUTTON' && n.textContent.trim() === 'Stop' && shownIn(n, host));
const say = async args => { await chip.update(args); await new Promise(r => setTimeout(r, 5)); return said(); };

if (which === 'chip_words_follow_state') {
  let text = await say({state: 'running', pause: null, cost: 1.5, estimate: 2});
  assert.match(text, /\bWorking\b/, 'a running step says Working: ' + text);
  assert.doesNotMatch(text, /Waiting on you/, 'Working only: ' + text);
  assert.equal(stops().length, 1, 'the Stop button sits in the chip, visible, while Working');
  text = await say({state: 'paused', pause: {kind: 'draft', step: 'draft'}, cost: 1.5, estimate: 2});
  assert.match(text, /Waiting on you/, 'a pause waiting on the person says Waiting on you: ' + text);
  assert.doesNotMatch(text, /\bWorking\b/, 'never both words: ' + text);
  text = await say({state: 'checkpoint', pause: null, cost: 10.2, estimate: 2});
  assert.match(text, /Waiting on you/, 'a spending checkpoint says Waiting on you: ' + text);
  assert.doesNotMatch(text, /\bWorking\b/, 'never both words: ' + text);
  text = await say({state: 'running', pause: null, cost: 1.5, estimate: 2});
  assert.match(text, /\bWorking\b/, 'back to Working when the build runs again: ' + text);
  assert.equal(stops().length, 1, 'Stop is back in the chip');
  for (const state of ['done', null]) {
    text = await say({state, pause: null, cost: 1.5, estimate: null});
    assert.doesNotMatch(text, /\bWorking\b|Waiting on you/, `nothing else: a ${state} build says neither word: ` + text);
    assert.equal(stops().length, 0, `no Stop when no build is running (${state})`);
    assert.match(text, /\$1\.50 so far/, 'the spend stays in view with no build: ' + text);
  }
  console.log('  ok chip_words_follow_state');
} else {
  let text = await say({state: 'running', pause: null, cost: 1.234, estimate: 0.5});
  assert.match(text, /\$1\.23 so far/, 'spend shows as $x.xx so far: ' + text);
  assert.match(text, /about \$0\.50/, 'the estimate shows as about $x.xx: ' + text);
  text = await say({state: 'running', pause: null, cost: 0, estimate: 4.291});
  assert.match(text, /\$0\.00 so far/, 'nothing spent yet still reads $0.00 so far: ' + text);
  assert.match(text, /about \$4\.29/, text);
  text = await say({state: 'running', pause: null, cost: 12.3456, estimate: 7});
  assert.match(text, /\$12\.35 so far/, 'two decimals, rounded: ' + text);
  assert.match(text, /about \$7\.00/, 'two decimals on a whole estimate: ' + text);
  assert.equal((text.match(/so far/g) || []).length, 1, 'one spend figure: ' + text);
  assert.equal((text.match(/about \$/g) || []).length, 1, 'one estimate: ' + text);
  text = await say({state: 'done', pause: null, cost: 3.1, estimate: null});
  assert.match(text, /\$3\.10 so far/, text);
  assert.doesNotMatch(text, /about/, 'no estimate without one: ' + text);
  assert.doesNotMatch(text, /NaN|undefined|null/, text);
  console.log('  ok spend_and_estimate_format');
}
process.exit(0);
"""

TESTS = ['chip_words_follow_state', 'spend_and_estimate_format']


def run():
    if not shutil.which('node'):
        print('SKIP node is unavailable')
        return
    failed = []
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.mjs', prefix='chauffeur_status_chip_',
                                     delete=False) as f:
        f.write(DRIVER)
        path = Path(f.name)
    try:
        for name in TESTS:
            try:
                result = subprocess.run([shutil.which('node'), str(path), ROOT.as_posix(), name],
                                        capture_output=True, text=True, timeout=60)
            except subprocess.TimeoutExpired:
                failed.append(name)
                print(f'  FAIL {name} timed out')
                continue
            print(result.stdout, end='')
            if result.returncode:
                failed.append(name)
                if 'FAIL' not in result.stdout:
                    lines = [line for line in result.stderr.strip().splitlines() if line.strip()]
                    print(f'  FAIL {name}', ' '.join(lines[:6])[:600])
    finally:
        path.unlink(missing_ok=True)
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} passed')
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    run()

"""Rebuilding a Properties card keeps the scroll offset and the focused control (owner report 2026-11-19).

Run from chauffeur/: python tests/test_twin_keep_place_js.py
"""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = r"""
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';

// A tiny DOM: enough for scroll clamping, contains, querySelectorAll by tag and focus.
class Node {
  constructor(tag, attrs = {}, text = '') { this.tagName = tag.toUpperCase(); this.attrs = { ...attrs }; this.children = []; this.parentElement = null; this.ownText = text; this.style = {}; }
  append(...nodes) { for (const n of nodes) { n.parentElement = this; this.children.push(n); } }
  replaceChildren() { for (const n of this.children) n.parentElement = null; this.children = []; for (let n = this.parentElement; n; n = n.parentElement) n.relayout?.(); }
  get textContent() { return this.ownText + this.children.map(c => c.textContent).join(''); }
  hasAttribute(name) { return name in this.attrs; }
  getAttribute(name) { return name in this.attrs ? this.attrs[name] : null; }
  contains(node) { for (let n = node; n; n = n.parentElement) if (n === this) return true; return false; }
  closest(selector) { const tag = selector.toUpperCase(); for (let n = this; n; n = n.parentElement) if (n.tagName === tag) return n; return null; }
  querySelectorAll(tag) { const out = []; const walk = n => { for (const c of n.children) { if (c.tagName === tag.toUpperCase()) out.push(c); walk(c); } }; walk(this); return out; }
  focus() { globalThis.document.activeElement = this; }
}
class Scroller extends Node {
  constructor() { super('div'); this.clientHeight = 300; this._top = 0; }
  get scrollHeight() { const count = n => n.children.reduce((s, c) => s + 1 + count(c), 0); return count(this) * 40; }
  get scrollTop() { return this._top; }
  set scrollTop(v) { this._top = Math.max(0, Math.min(v, Math.max(0, this.scrollHeight - this.clientHeight))); }
  relayout() { this.scrollTop = this._top; } // a browser clamps the offset when the content shrinks
}
globalThis.document = { activeElement: null };
globalThis.getComputedStyle = node => ({ overflowY: node instanceof Scroller ? 'auto' : 'visible', overflow: '' });
let frames = [];
globalThis.requestAnimationFrame = fn => frames.push(fn);

const { keepPlace } = await import(pathToFileURL(process.argv[2]).href);

function build(card, extra) {
  for (let i = 0; i < 20; i++) {
    const label = new Node('label', {}, `Field ${i}`); const input = new Node('input', { 'data-field': `f${i}` }); label.append(input); card.append(label);
  }
  if (extra) card.append(new Node('select', { 'aria-label': 'Edge type' }));
}
const scroller = new Scroller(), card = new Node('section'); scroller.append(card); build(card, true);
scroller.scrollTop = 500;
const focused = card.querySelectorAll('input')[14]; focused.focus();

// Without keepPlace, emptying the card clamps the scroll box to the top.
const bare = new Scroller(), bareCard = new Node('section'); bare.append(bareCard); build(bareCard, true); bare.scrollTop = 500;
bareCard.replaceChildren(); build(bareCard, false);
assert.equal(bare.scrollTop, 0, 'the bug: a rebuild returns to the top');

keepPlace(card, () => { card.replaceChildren(); build(card, false); });
assert.equal(scroller.scrollTop, 500, 'same selection keeps the scroll offset');
const now = globalThis.document.activeElement;
assert.equal(now.getAttribute('data-field'), 'f14', 'focus returns to the same control');
assert.ok(card.contains(now));
frames.splice(0).forEach(fn => fn());
assert.equal(scroller.scrollTop, 500, 'the late restore keeps the place');

// Content that shrinks below the old offset clamps instead of overshooting.
keepPlace(card, () => { card.replaceChildren(); card.append(new Node('p')); });
assert.ok(scroller.scrollTop <= Math.max(0, scroller.scrollHeight - scroller.clientHeight));
console.log('  ok a rebuilt card keeps its scroll offset and focus; short content clamps');
"""


def main():
    module = ROOT / 'static' / 'twin' / 'editor' / 'keep_place.js'
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / 'keep_place_test.mjs'
        script.write_text(SCRIPT, encoding='utf-8')
        result = subprocess.run(['node', str(script), str(module)], capture_output=True, text=True, timeout=120)
    print(result.stdout, end='')
    if result.returncode:
        raise AssertionError(result.stderr)
    print('1/1 passed')


if __name__ == '__main__':
    main()

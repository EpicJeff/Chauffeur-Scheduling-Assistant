// Rebuilding a Properties card empties it for a moment, and an empty scroll box
// clamps to the top. When the same thing stays selected, put the person back
// where they were: the same scroll offset and the same focused control.

function scrollParent(node) {
  for (let current = node?.parentElement; current; current = current.parentElement) {
    const style = globalThis.getComputedStyle?.(current);
    if (style && /(auto|scroll)/.test(`${style.overflowY} ${style.overflow}`)) return current;
  }
  return null;
}

const KEY_ATTRS = ['id', 'aria-label', 'name', 'data-field', 'data-slot-use', 'data-slot-swatch', 'data-slot-clear', 'data-slot-reset', 'data-slot-uv', 'data-slot-tint'];

function focusKey(node, host) {
  const attrs = KEY_ATTRS.filter(name => node.hasAttribute?.(name)).map(name => [name, node.getAttribute(name)]);
  const label = node.closest?.('label')?.textContent?.trim() || '';
  const text = attrs.length || label ? '' : (node.textContent || '').trim();
  const twins = [...host.querySelectorAll(node.tagName)].filter(other => sameKey(other, attrs, label, text));
  return { tag: node.tagName, attrs, label, text, index: Math.max(0, twins.indexOf(node)) };
}

function sameKey(node, attrs, label, text) {
  if (!attrs.every(([name, value]) => node.getAttribute?.(name) === value)) return false;
  if (label && (node.closest?.('label')?.textContent?.trim() || '') !== label) return false;
  return !text || (node.textContent || '').trim() === text;
}

function findByKey(host, key) {
  const matches = [...host.querySelectorAll(key.tag)].filter(node => sameKey(node, key.attrs, key.label, key.text));
  return matches[key.index] || matches[0] || null;
}

export function keepPlace(node, rebuild) {
  const scroller = scrollParent(node);
  const top = scroller ? scroller.scrollTop : null;
  const active = globalThis.document?.activeElement;
  const key = active && active !== node && node.contains(active) ? focusKey(active, node) : null;
  const result = rebuild();
  const restore = () => {
    if (scroller && top !== null) scroller.scrollTop = Math.max(0, Math.min(top, scroller.scrollHeight - scroller.clientHeight));
    const now = globalThis.document?.activeElement;
    if (key && !(now && node.contains(now))) findByKey(node, key)?.focus?.({ preventScroll: true });
  };
  restore();
  // Rows that fill in a frame later (slot metadata, late sections) can change the height again.
  globalThis.requestAnimationFrame?.(restore);
  return result;
}

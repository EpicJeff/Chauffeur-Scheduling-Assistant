import { report } from './api.js';

let nextLabel = 0;
// Library uses pointer capture for touch and mouse drags. Deliver the same
// asset to a row without making the Library selection the drag payload.
export function slotDragTarget(node) {
  const row = node?.closest?.('[data-library-slot]');
  return row?.dataset.librarySlot !== undefined ? row : null;
}
export function sendSlotDrag(row, phase, entry) {
  row?.dispatchEvent(new CustomEvent('chf-library-slot-drag', { detail: { phase, entry } }));
}

// A DOM component only. The owner keeps the domain operation and undo step.
export function createSlotRow({ label, subject = `${label.toLowerCase()} material`, accepts, current, apply, clear, reset, tint, library }) {
  const element = document.createElement('section'), row = document.createElement('div');
  element.dataset.librarySlot = label; row.className = 'editor-material-line editor-slot-line'; element.append(row);
  const controller = new AbortController(), { signal } = controller;
  let busy = false, disposed = false;
  const listen = (node, type, fn) => node.addEventListener(type, fn, { signal });
  const button = (text, host, key) => {
    const node = document.createElement('button'); node.type = 'button'; node.textContent = text;
    if (key) node.dataset[key] = ''; host.append(node); return node;
  };
  const swatch = button('', row, 'slotSwatch'); swatch.className = 'editor-material-swatch editor-slot-swatch';
  swatch.setAttribute('aria-label', `Show the ${subject} in the Library`);
  const words = document.createElement('div'), caption = document.createElement('span'), name = document.createElement('p');
  caption.textContent = label; caption.id = `editor-slot-label-${++nextLabel}`; caption.dataset.slotLabel = '';
  name.dataset.slotName = ''; words.append(caption, name); row.append(words);
  const actions = document.createElement('div'); actions.className = 'editor-material-actions'; row.append(actions);
  const use = button('Use selected', actions, 'slotUse'), remove = button('Clear', actions, 'slotClear');
  use.setAttribute('aria-describedby', caption.id); remove.setAttribute('aria-label', `Clear the ${subject}`);
  async function run(fn) {
    if (busy || disposed) return;
    busy = true; refresh();
    try { await fn(); } catch (error) { report(error); }
    finally { busy = false; if (!disposed) refresh(); }
  }
  listen(use, 'click', () => {
    const entry = library.selected(); if (entry && accepts(entry)) return run(() => apply(entry));
  });
  listen(remove, 'click', () => run(clear));
  listen(swatch, 'click', async () => {
    const entry = current();
    if (entry?.id) try { await library.reveal(entry.kind || 'material', entry.id); } catch (error) { report(error); }
  });
  const resetButton = reset && button(reset.label, actions, 'slotReset');
  if (resetButton) listen(resetButton, 'click', () => run(reset.run));
  let tintInput, tintClear;
  if (tint) {
    const tintLabel = document.createElement('label'); tintLabel.textContent = 'Override tint';
    tintInput = document.createElement('input'); tintInput.type = 'color'; tintInput.setAttribute('aria-label', `${label} override tint`);
    tintLabel.append(tintInput); row.insertBefore(tintLabel, words);
    listen(tintInput, 'change', () => { const value = tintInput.value; return run(() => tint.set(value)); });
    if (tint.clear) { tintClear = button('Clear override', actions); listen(tintClear, 'click', () => run(tint.clear)); }
  }
  listen(element, 'chf-library-slot-drag', event => {
    const { phase, entry } = event.detail;
    const valid = !!entry && accepts(entry) && !busy && !disposed;
    element.classList.toggle('editor-slot-dragover', phase === 'over' && valid);
    if (phase === 'drop' && valid) return run(() => apply(entry));
  });
  function refresh() {
    const entry = current(), selected = library.selected(), valid = !!selected && accepts(selected);
    name.textContent = entry?.name || 'Default'; swatch.disabled = busy || !entry?.id;
    swatch.classList.toggle('editor-slot-empty', !entry?.id);
    swatch.replaceChildren(); swatch.style.backgroundColor = entry?.color || '';
    if (entry?.thumb) { const image = document.createElement('img'); image.src = entry.thumb; image.alt = ''; swatch.append(image); }
    use.disabled = busy || !valid; use.textContent = valid ? `Use ${selected.name}` : 'Use selected';
    use.setAttribute('aria-label', use.textContent);
    remove.disabled = busy;
    if (resetButton) resetButton.disabled = busy;
    if (tintInput) {
      tintInput.value = typeof tint.value === 'function' ? tint.value() : tint.value;
      tintInput.disabled = busy;
      if (tintClear) tintClear.disabled = busy;
    }
  }
  const unsubscribe = library.onSelect(refresh);
  refresh();
  return { element, refresh, dispose() { disposed = true; unsubscribe(); controller.abort(); element.classList.remove('editor-slot-dragover'); } };
}

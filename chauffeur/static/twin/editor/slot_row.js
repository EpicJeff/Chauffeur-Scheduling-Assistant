import { report } from './api.js';

let nextLabel = 0;
export const idleLibrary = { selected: () => null, onSelect: () => () => {}, reveal: async () => {} };
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
export function createSlotRow({ label, subject = `${label.toLowerCase()} material`, accepts, current, detail, inherited, apply, clear, reset, tint, offset, library, materialSurface, readOnly = false }) {
  const element = document.createElement('section'), row = document.createElement('div');
  element.dataset.librarySlot = label; row.className = 'editor-material-line editor-slot-line'; element.append(row);
  const controller = new AbortController(), { signal } = controller;
  let busy = false, disposed = false;
  const locked = () => typeof readOnly === 'function' ? readOnly() : readOnly;
  const listen = (node, type, fn) => node.addEventListener(type, fn, { signal });
  if (materialSurface) listen(element, 'contextmenu', event => {
    if (!library.materialMenu) return;
    event.preventDefault(); event.stopPropagation(); library.materialMenu(event, materialSurface());
  });
  const button = (text, host, key) => {
    const node = document.createElement('button'); node.type = 'button'; node.textContent = text;
    if (key) node.dataset[key] = ''; host.append(node); return node;
  };
  const swatch = locked() ? document.createElement('span') : button('', row, 'slotSwatch');
  if (locked()) { swatch.dataset.slotSwatch = ''; row.append(swatch); }
  swatch.className = 'editor-material-swatch editor-slot-swatch';
  swatch.setAttribute('aria-label', `Show the ${subject} in the Library`);
  const words = document.createElement('div'), caption = document.createElement('span'), name = document.createElement('p');
  caption.textContent = label; caption.id = `editor-slot-label-${++nextLabel}`; caption.dataset.slotLabel = '';
  name.dataset.slotName = ''; words.append(caption, name); row.append(words);
  const actions = document.createElement('div'); actions.className = 'editor-material-actions'; row.append(actions);
  const clearFn = typeof clear === 'function' ? clear : clear?.run;
  const clearEnabled = typeof clear === 'function' ? null : clear?.enabled;
  const use = button('Use selected', actions, 'slotUse');
  let remove = null;
  if (clearFn) {
    remove = document.createElement('button'); remove.type = 'button'; remove.textContent = 'Clear';
    remove.dataset.slotClear = '';
    if (!clearEnabled) actions.append(remove);
  }
  use.setAttribute('aria-describedby', caption.id); remove?.setAttribute('aria-label', `Clear the ${subject}`);
  async function run(fn) {
    if (busy || disposed || locked()) return;
    busy = true; refresh();
    try { await fn(); } catch (error) { report(error); }
    finally { busy = false; if (!disposed) refresh(); }
  }
  listen(use, 'click', () => {
    const entry = library.selected(); if (entry && accepts(entry)) return run(() => apply(entry));
  });
  let clearFocused = false;
  if (remove) listen(remove, 'click', () => {
    clearFocused = document.activeElement === remove;
    return run(clearFn);
  });
  listen(swatch, 'click', async () => {
    const entry = current();
    if (entry?.id) try { await library.reveal(entry.kind || 'material', entry.id); } catch (error) { report(error); }
  });
  const resetButton = reset && button(reset.label, actions, 'slotReset');
  if (resetButton) listen(resetButton, 'click', () => run(reset.run));
  let tintInput, tintClear, tintMixed;
  if (tint) {
    const tintLabel = document.createElement('label'); tintLabel.textContent = 'Override tint';
    tintInput = document.createElement('input'); tintInput.type = 'color'; tintInput.setAttribute('aria-label', `${label} override tint`);
    tintLabel.append(tintInput); row.insertBefore(tintLabel, words);
    if (tint.mixed) { tintMixed = document.createElement('span'); tintMixed.textContent = 'Mixed'; tintLabel.append(tintMixed); }
    listen(tintInput, 'change', () => { const value = tintInput.value; return run(() => tint.set(value)); });
    if (tint.clear) { tintClear = button('Clear override', actions); listen(tintClear, 'click', () => run(tint.clear)); }
  }
  let offsetControls, uInput, vInput, rotationInput, offsetReset;
  if (offset) {
    offsetControls = document.createElement('div'); offsetControls.className = 'editor-slot-offset';
    const field = (text, tag, key) => {
      const labelNode = document.createElement('label'); labelNode.textContent = text;
      const input = document.createElement(tag); input.dataset[key] = '';
      input.setAttribute('aria-label', `${label} ${text}`); labelNode.append(input); offsetControls.append(labelNode); return input;
    };
    uInput = field('U offset', 'input', 'slotU'); vInput = field('V offset', 'input', 'slotV');
    for (const input of [uInput, vInput]) { input.type = 'number'; input.step = '.05'; }
    rotationInput = field('Rotation', 'select', 'slotRotation');
    for (const value of [0, 90, 180, 270]) {
      const option = document.createElement('option'); option.value = String(value); option.textContent = `${value}°`; rotationInput.append(option);
    }
    const change = event => {
      if (offset.setField) {
        const key = event.target === uInput ? 'u' : event.target === vInput ? 'v' : 'rot';
        const text = event.target.value, value = Number(text);
        if (!text.trim() || !Number.isFinite(value) || key === 'rot' && ![0, 90, 180, 270].includes(value)) {
          report(new Error('Use finite U and V offsets and a quarter-turn rotation.')); refresh(); return;
        }
        return run(() => offset.setField(key, key === 'rot' ? value : Number(((value % 1 + 1) % 1).toFixed(10)) % 1));
      }
      const u = Number(uInput.value), v = Number(vInput.value), rot = Number(rotationInput.value);
      if (!uInput.value.trim() || !vInput.value.trim() || !Number.isFinite(u) || !Number.isFinite(v) || ![0, 90, 180, 270].includes(rot)) {
        report(new Error('Use finite U and V offsets and a quarter-turn rotation.')); refresh(); return;
      }
      // Round floating-point nudge noise; 1 and negative nudges wrap before posting.
      const wrap = value => Number(((value % 1 + 1) % 1).toFixed(10)) % 1;
      return run(() => offset.set({ u: wrap(u), v: wrap(v), rot }));
    };
    for (const input of [uInput, vInput, rotationInput]) listen(input, 'change', change);
    offsetReset = button('Reset offset', offsetControls, 'slotOffsetReset');
    offsetReset.setAttribute('aria-label', `${label} Reset offset`);
    listen(offsetReset, 'click', () => run(offset.clear)); element.append(offsetControls);
  }
  listen(element, 'chf-library-slot-drag', event => {
    const { phase, entry } = event.detail;
    const valid = !!entry && accepts(entry) && !busy && !disposed && !locked();
    element.classList.toggle('editor-slot-dragover', phase === 'over' && valid);
    if (phase === 'drop' && valid) return run(() => apply(entry));
  });
  function refresh() {
    const entry = current(), selected = library.selected(), valid = !!selected && accepts(selected);
    // `detail` keeps what the old material line said about where the material comes from
    // ("Oak, set here", "Siding, from the building", "House look").
    name.textContent = detail?.() || entry?.name || 'Default'; swatch.disabled = busy || !entry?.id;
    name.setAttribute('aria-disabled', String(!!inherited?.()));
    swatch.classList.toggle('editor-slot-empty', !entry?.id);
    swatch.replaceChildren(); swatch.style.backgroundColor = entry?.color || '';
    if (entry?.thumb) { const image = document.createElement('img'); image.src = entry.thumb; image.alt = ''; swatch.append(image); }
    use.disabled = busy || locked() || !valid; use.textContent = valid ? `Use ${selected.name}` : 'Use selected';
    use.setAttribute('aria-label', use.textContent);
    if (remove) {
      if (clearEnabled) {
        const showClear = !!clearEnabled();
        if (showClear && !remove.parentElement) (use.after ? use.after(remove) : actions.append(remove));
        else if (!showClear && remove.parentElement) {
          const hadFocus = document.activeElement === remove || clearFocused;
          clearFocused = false;
          remove.remove();
          if (hadFocus) use.focus?.();
        } else if (!busy) clearFocused = false;
      }
      remove.disabled = busy || locked();
    }
    if (resetButton) resetButton.disabled = busy || locked();
    if (tintInput) {
      tintInput.value = typeof tint.value === 'function' ? tint.value() : tint.value;
      tintInput.parentElement.hidden = !!tint.enabled && !tint.enabled();
      tintInput.disabled = busy || locked() || tintInput.parentElement.hidden;
      if (tintMixed) tintMixed.hidden = !tint.mixed();
      if (tintClear) {
        tintClear.disabled = busy || locked();
        tintClear.hidden = tintInput.parentElement.hidden || !!tint.hasOverride && !tint.hasOverride();
      }
    }
    if (offsetControls) {
      const value = offset.effective?.() || offset.value() || { u: 0, v: 0, rot: 0 };
      uInput.value = String(value.u); vInput.value = String(value.v); rotationInput.value = String(value.rot);
      for (const [key, input] of [['u', uInput], ['v', vInput], ['rot', rotationInput]]) {
        if (!offset.mixed?.(key)) continue;
        if (input === rotationInput) {
          if (!input.querySelector('[data-slot-mixed]')) {
            const option = document.createElement('option'); option.dataset.slotMixed = ''; option.value = ''; option.textContent = 'Mixed'; input.append(option);
          }
        } else { input.type = 'text'; input.placeholder = 'Mixed'; }
        input.value = '';
      }
      for (const input of [uInput, vInput, rotationInput]) input.disabled = busy || locked();
      offsetReset.disabled = busy || locked() || !offset.value();
    }
  }
  const unsubscribe = library.onSelect(refresh);
  refresh();
  if (locked()) {
    // Read-only Properties retain their swatch and name, without edit controls.
    actions.remove(); tintInput?.parentElement.remove(); offsetControls?.remove();
  }
  return { element, refresh, dispose() { disposed = true; unsubscribe(); controller.abort(); element.classList.remove('editor-slot-dragover'); } };
}

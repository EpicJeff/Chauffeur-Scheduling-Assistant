import { feetInches, parseLength } from './cards.js';

// Remains a readout until the first value key; pointer moves never replace entry.
export function createTypedValue(host) {
  const input = document.createElement('input'); input.type = 'text'; input.className = 'editor-typed-value';
  input.setAttribute('aria-label', 'Drag value'); input.autocomplete = 'off'; input.spellcheck = false; input.tabIndex = -1;
  input.hidden = true; input.readOnly = true; host.append(input);
  let kind = null, entry = false, previousFocus = null;
  function value() {
    if (!entry) return null;
    try {
      if (kind === 'length') return parseLength(input.value);
      return /^-?(?:\d+(?:\.\d*)?|\.\d+)$/.test(input.value.trim()) && Number.isFinite(Number(input.value)) ? Number(input.value) : null;
    } catch { return null; }
  }
  function show(nextKind, live, clientXY) {
    kind = nextKind; input.hidden = false;
    if (!entry) input.value = kind === 'length' ? feetInches(live).replace("'-", "' ")
      : kind === 'angle' ? `${Math.round(live)}°` : live.toFixed(2);
    if (clientXY) { input.style.left = `${clientXY[0] + 18}px`; input.style.top = `${clientXY[1] + 18}px`; }
  }
  function key(event) {
    if (input.hidden || event.ctrlKey || event.metaKey || event.altKey) return null;
    if (event.key === 'Escape') return 'cancel';
    if (event.key === 'Enter') return value() === null ? (entry ? 'typing' : null) : 'commit';
    if (!/^[\d.\-'\"]$/.test(event.key) && event.key !== 'Backspace') return null;
    if (!entry) {
      entry = true; input.value = ''; input.readOnly = false; previousFocus = document.activeElement;
      input.focus?.({ preventScroll: true });
    }
    // Honour a selection made with the mouse or keyboard while entering a value.
    const start = input.selectionStart ?? input.value.length, end = input.selectionEnd ?? start;
    const from = event.key === 'Backspace' && start === end ? Math.max(0, start - 1) : start;
    const text = event.key === 'Backspace' ? '' : event.key;
    input.value = input.value.slice(0, from) + text + input.value.slice(end);
    input.setSelectionRange?.(from + text.length, from + text.length);
    return 'typing';
  }
  function hide() {
    const focused = document.activeElement === input;
    input.hidden = true; input.readOnly = true; entry = false; kind = null;
    if (focused) { input.blur?.(); previousFocus?.focus?.({ preventScroll: true }); }
    previousFocus = null;
  }
  return { show, key, value, editing: () => entry, hide };
}

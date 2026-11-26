import { report } from './api.js';

// Canvas and dock rows supply existing actions; this module owns presentation,
// keyboard navigation and dismissal only. One menu can be visible at a time.
let active = null;
export function createContextMenu({ items, signal, label = 'Actions' }) {
  let host = document.getElementById('editor-context-menu'), opener = null, target, position, trail = [];
  if (!host) {
    host = document.createElement('div'); host.id = 'editor-context-menu'; host.hidden = true;
    document.querySelector('.editor-shell').append(host);
  }
  host.setAttribute('role', 'menu'); host.setAttribute('aria-label', 'Actions');
  if (!active) host.hidden = true;
  const lifecycle = new AbortController();
  const listen = (node, type, fn, options = {}) => node.addEventListener(type, fn, { ...options, signal: lifecycle.signal });
  listen(host, 'keydown', event => {
    if ((event.ctrlKey || event.metaKey) && !event.altKey && ['c', 'x', 'v', 'd'].includes(event.key.toLowerCase())) {
      close(false); return; // The editor's shared shortcut handler owns these.
    }
    event.stopPropagation();
  });
  function close(restoreFocus = true) {
    if (active !== menu) return;
    host.hidden = true; host.replaceChildren(); active = null;
    if (restoreFocus && opener?.isConnected) opener.focus();
  }
  function draw(actions, title, focusLabel) {
    host.replaceChildren(); host.setAttribute('aria-label', title);
    if (trail.length) actions = [{ label: 'Back', run: back, back: true }, ...actions];
    for (const action of actions) {
      const button = document.createElement('button'); button.type = 'button'; button.textContent = action.label;
      button.setAttribute('role', 'menuitem'); button.disabled = !!action.disabled;
      if (action.reason) { button.title = action.reason; button.setAttribute('aria-description', action.reason); }
      if (action.children) {
        button.setAttribute('aria-haspopup', 'menu');
        button.dataset.submenu = '';
      }
      button.addEventListener('click', () => {
        if (action.disabled) return;
        if (action.back) { back(); return; }
        if (action.children) {
          trail.push({ actions, title, focusLabel: action.label });
          draw(action.children, action.label); return;
        }
        close(false);
        try { Promise.resolve(action.run(target)).catch(report); } catch (error) { report(error); }
      }); host.append(button);
    }
    host.hidden = false;
    const [x, y] = position;
    const box = host.getBoundingClientRect();
    host.style.left = `${Math.max(8, Math.min(x, window.innerWidth - box.width - 8))}px`;
    host.style.top = `${Math.max(8, Math.min(y, window.innerHeight - box.height - 8))}px`;
    const buttons = [...host.querySelectorAll('button')].filter(button => !button.disabled);
    (buttons.find(button => button.textContent === focusLabel) || buttons.find(button => button.textContent !== 'Back') || buttons[0])?.focus();
  }
  function back() {
    const previous = trail.pop();
    if (previous) draw(previous.actions.filter(action => !action.back), previous.title, previous.focusLabel);
  }
  function open(clientXY, nextTarget) {
    active?.close(false);
    const actions = items(nextTarget).filter(Boolean);
    if (!actions.length) return;
    opener = document.activeElement; active = menu; target = nextTarget; trail = [];
    position = Array.isArray(clientXY) ? clientXY : [clientXY.clientX, clientXY.clientY];
    draw(actions, label);
  }
  // Window capture outranks dialog and gesture capture on document.
  listen(window, 'keydown', event => {
    if (active !== menu || event.defaultPrevented) return;
    if (event.key === 'Escape' || event.key === 'Tab') {
      event.preventDefault(); event.stopImmediatePropagation(); close(); return;
    }
    if (event.key === 'ArrowLeft' && trail.length) {
      event.preventDefault(); event.stopImmediatePropagation(); back(); return;
    }
    if (event.key === 'ArrowRight' && document.activeElement?.hasAttribute('data-submenu')) {
      event.preventDefault(); event.stopImmediatePropagation(); document.activeElement.click(); return;
    }
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault(); event.stopImmediatePropagation();
    const buttons = [...host.querySelectorAll('button')].filter(b => !b.disabled), at = buttons.indexOf(document.activeElement);
    const index = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1
      : (at + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
    buttons[index]?.focus();
  }, { capture: true });
  listen(window, 'pointerdown', event => { if (active === menu && !host.contains(event.target)) close(false); }, { capture: true });
  listen(window, 'resize', () => close(false));
  listen(document, 'scroll', () => close(false), { capture: true });
  signal?.addEventListener('abort', () => { close(false); lifecycle.abort(); }, { once: true });
  const menu = { open, close }; return menu;
}

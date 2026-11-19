// One editor-only host. Content is adopted and returned intact, including drafts
// and listeners. Install before tools so Escape never reaches their capture handlers.
const el = id => document.getElementById(id);
let current = null, installed = null, returnFocus = null, inert = [];
const sharedPrompt = () => document.querySelector('#cc-confirm-modal:not(.hidden), #cc-input-modal:not(.hidden), #cc-choice-modal:not(.hidden), #cc-alert-modal:not(.hidden)');
const visible = node => {
  const folded = node?.closest('details:not([open])');
  return node?.isConnected && !node.closest('[hidden]') && (!folded || folded.querySelector('summary') === node);
};

export function closeDialog(id, { restoreFocus = true } = {}) {
  if (!current || id && current.node.id !== id) return;
  const previous = current; current = null;
  previous.node.hidden = true;
  previous.parent.insertBefore(previous.node, previous.next?.parentElement === previous.parent ? previous.next : null);
  const host = el('editor-dialog'); host.hidden = true; host.removeAttribute('role');
  for (const [node, value] of inert) node.inert = value;
  inert = [];
  previous.onClose?.();
  if (restoreFocus) {
    const target = visible(returnFocus) ? returnFocus : el('editor-menu')?.querySelector('summary');
    target?.focus();
  }
  returnFocus = null;
}

export function openDialog(id, { title, onClose } = {}) {
  const node = el(id), host = el('editor-dialog');
  if (!node || !host) throw new Error(`Missing editor dialog: ${id}`);
  if (current?.node === node) { el('editor-dialog-title').textContent = title || ''; return; }
  // A replacement returns focus to the original opener, not into the old dialog.
  const focus = current ? returnFocus : document.activeElement;
  closeDialog(undefined, { restoreFocus: false });
  returnFocus = focus;
  current = { node, parent: node.parentElement, next: node.nextSibling, onClose };
  el('editor-dialog-body').append(node); node.hidden = false;
  el('editor-dialog-title').textContent = title || '';
  host.setAttribute('role', 'dialog'); host.dataset.content = id; host.hidden = false;
  const shell = host.parentElement;
  inert = [...shell.children].filter(child => child !== host && child.id !== 'editor-context-menu').map(child => [child, child.inert]);
  inert.forEach(([child]) => { child.inert = true; });
  el('editor-dialog-close').focus();
}

export function mountDialogs({ signal } = {}) {
  installed?.abort(); installed = new AbortController();
  const controller = installed;
  const listen = (node, type, fn, options = {}) => node.addEventListener(type, fn, { ...options, signal: controller.signal });
  listen(el('editor-dialog-close'), 'click', () => closeDialog());
  // Controls keep their own keyboard behavior; editor shortcuts in document
  // bubble must never act on the scene behind a modal.
  listen(el('editor-dialog'), 'keydown', event => event.stopPropagation());
  listen(document, 'keydown', event => {
    if (!current || sharedPrompt() || event.defaultPrevented) return;
    if (event.key === 'Escape') {
      event.preventDefault(); event.stopImmediatePropagation(); closeDialog(); return;
    }
    if (event.key !== 'Tab') return;
    const buttons = [...el('editor-dialog').querySelectorAll('button, input, select, textarea, a[href], summary, [tabindex]')]
      .filter(node => !node.disabled && node.tabIndex !== -1 && visible(node));
    const first = buttons[0], last = buttons.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }, { capture: true });
  signal?.addEventListener('abort', () => { closeDialog(undefined, { restoreFocus: false }); controller.abort(); }, { once: true });
  return { openDialog, closeDialog, current: () => current?.node.id || null };
}

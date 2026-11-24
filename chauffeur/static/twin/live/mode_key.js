import { svgIcon } from './glance_icons.js';

export const LEGEND_STORAGE_KEY = 'chauffeur.twin.legend.v1';

// One key for every viewer, including the read-only wall panel. Mode providers
// own the meaning and colours; this builder only lays out their structured data.
export function mountModeKey(strip, {getSections, storage} = {}) {
  const events = new AbortController(), options = {signal: events.signal};
  const button = document.createElement('button');
  button.id = 'twin-mode-key-button'; button.type = 'button'; button.textContent = '?';
  button.setAttribute('aria-label', 'Legend'); button.setAttribute('aria-haspopup', 'dialog');
  button.setAttribute('aria-controls', 'twin-mode-key'); button.title = 'Legend';
  const card = document.createElement('div'); card.id = 'twin-mode-key'; card.hidden = true;
  card.setAttribute('role', 'dialog'); card.setAttribute('aria-label', 'Legend');
  strip.append(button); strip.parentElement.append(card);
  let open = false;
  try {
    if (storage === undefined) storage = window.localStorage;
    open = storage?.getItem(LEGEND_STORAGE_KEY) === 'true';
  } catch { /* Private browsing still has a working key. */ }
  const sections = new Map();
  function position() {
    if (card.hidden) return;
    const rect = strip.getBoundingClientRect();
    const width = card.getBoundingClientRect().width || 220;
    const top = rect.bottom + 8;
    card.style.left = `${Math.max(8, Math.min(window.innerWidth - width - 8, (rect.left + rect.right - width) / 2))}px`;
    card.style.top = `${top}px`;
    const glance = document.getElementById('twin-glance-home');
    const glanceRect = glance?.getBoundingClientRect();
    const bottom = glanceRect?.height ? Math.min(window.innerHeight, glanceRect.top) : window.innerHeight;
    card.style.setProperty('--twin-key-space', `${Math.max(0, bottom - top - 12)}px`);
  }
  function show(value, persist = true) {
    open = value && !button.hidden;
    card.hidden = !open; button.setAttribute('aria-expanded', String(open));
    if (persist) try { storage?.setItem(LEGEND_STORAGE_KEY, String(open)); } catch { /* Storage is optional. */ }
    position();
  }
  function close() { show(false); }
  button.addEventListener('click', () => show(!open), options);
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || !open) return;
    event.preventDefault(); close(); button.focus();
  }, options);
  document.addEventListener('click', event => {
    if (open && !strip.contains(event.target) && !card.contains(event.target)) close();
  }, {...options, capture: true});
  // Node test rigs mount live modes without a window event target.
  globalThis.window?.addEventListener?.('resize', position, options);
  const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(position) : null;
  observer?.observe(strip);
  const glance = document.getElementById('twin-glance-home');
  if (glance) observer?.observe(glance);
  function update() {
    const rows = (getSections?.() || []).filter(({key}) =>
      key && (key.items?.length || key.note || key.status || key.content?.length));
    const active = new Set(rows.map(row => row.id));
    for (const [id, section] of sections) if (!active.has(id)) { section.node.remove(); sections.delete(id); }
    for (const {id, icon, name, key} of rows) {
      let section = sections.get(id);
      if (!section) {
        const node = document.createElement('section'); node.dataset.modeKey = id;
        sections.set(id, section = {node});
      }
      const signature = JSON.stringify([icon, name, key.items, key.note, key.status]);
      const content = key.content || [];
      if (signature !== section.signature || content.length !== section.content?.length || content.some((node, i) => node !== section.content[i])) {
        const header = document.createElement('h2');
        if (icon) header.append(svgIcon(icon, 'currentColor', 'key-' + id));
        header.append(document.createTextNode(name));
        const nodes = [header];
        for (const {swatch, label} of key.items || []) {
          const row = document.createElement('div'), chip = document.createElement('span');
          row.className = 'twin-key-row'; chip.className = 'twin-key-swatch'; chip.setAttribute('aria-hidden', 'true');
          if (swatch === 'cone') { chip.dataset.keyCone = ''; chip.textContent = '◁'; }
          else chip.style.backgroundColor = swatch;
          row.append(chip, document.createTextNode(label)); nodes.push(row);
        }
        if (key.status) {
          const status = document.createElement('p'); status.className = 'twin-key-status'; status.textContent = key.status; nodes.push(status);
        }
        if (key.note) {
          const note = document.createElement('p'); note.className = 'twin-key-note'; note.textContent = key.note; nodes.push(note);
        }
        // Adopt the original controls so their listeners and expanded state survive.
        const scroll = card.scrollTop, focused = document.activeElement;
        section.node.replaceChildren(...nodes, ...content);
        if (focused && section.node.contains(focused) && document.activeElement !== focused) focused.focus({preventScroll: true});
        card.scrollTop = scroll;
        section.signature = signature; section.content = [...content];
      }
      // Keep strip order without detaching sections already in the right place.
      const index = rows.findIndex(row => row.id === id);
      if (card.children[index] !== section.node) card.insertBefore(section.node, card.children[index] || null);
    }
    button.hidden = !rows.length;
    show(rows.length ? open : false, !rows.length && open);
  }
  update();
  return {update, close, button, card,
    stop() { events.abort(); observer?.disconnect(); card.remove(); button.remove(); sections.clear(); }};
}

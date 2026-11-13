import { materialName, readLibraryCatalog } from './material_catalog.js';
import { report as reportError } from './api.js';

// A DOM component only: the owner supplies one onChange -> one domain op/history step.
export function materialSlot({ label, value = null, defaultLabel, defaultColor = '#b8b0a4',
  quickPicks = [], kit = {}, onChange, readOnly = false, report = reportError,
  loadMaterials = async () => (await readLibraryCatalog()).materials }) {
  const root = document.createElement('section'), row = document.createElement('div');
  row.className = 'editor-material-line'; root.dataset.materialSlot = label;
  const words = document.createElement('div'), caption = document.createElement('span'), text = document.createElement('p');
  const swatch = document.createElement('i'); swatch.className = 'editor-material-swatch'; swatch.setAttribute('aria-hidden', 'true');
  caption.textContent = label; words.append(caption, text); row.append(swatch, words); root.append(row);
  const locked = () => typeof readOnly === 'function' ? readOnly() : readOnly;
  let current = value, entries = [], chooser = null, busy = false, loading = false;
  const name = ref => entries.find(e => e.id === ref.id)?.name || materialName(kit.materials?.[ref.id]?.asset || ref.id);
  const color = ref => ref?.color || entries.find(e => e.id === ref?.id)?.color || kit.materials?.[ref?.id]?.color
    || Object.values(kit.materials || {}).find(r => r.asset === ref?.id)?.color || '#b8b0a4';
  const draw = () => {
    text.textContent = current ? name(current) : `Default: ${defaultLabel}`;
    swatch.style.backgroundColor = current ? color(current) : defaultColor;
  };
  async function save(next) {
    if (locked() || busy || JSON.stringify(current) === JSON.stringify(next)) return;
    busy = true;
    try { await onChange(next); current = next; chooser?.remove(); chooser = null; draw(); }
    catch (error) { report(error); }
    finally { busy = false; }
  }
  if (!locked()) {
    const actions = document.createElement('div'); actions.className = 'editor-material-actions';
    const change = document.createElement('button'); change.type = 'button'; change.textContent = 'Change';
    change.setAttribute('aria-label', `Change the ${label.toLowerCase()} material`); actions.append(change); row.append(actions);
    change.addEventListener('click', async () => {
      if (locked() || busy || loading) return;
      if (chooser) { chooser.remove(); chooser = null; return; }
      loading = true;
      try {
        entries = await loadMaterials();
        if (locked()) return;
        draw(); chooser = document.createElement('div'); chooser.className = 'editor-material-options';
        chooser.setAttribute('role', 'group'); chooser.setAttribute('aria-label', `Choose ${label.toLowerCase()} material`);
        const button = (title, action) => {
          const node = document.createElement('button'); node.type = 'button'; node.textContent = title;
          node.addEventListener('click', action); chooser.append(node); return node;
        };
        button('Use default', () => save(null));
        const ordered = [...quickPicks, ...entries].filter((ref, i, all) => all.findIndex(r => r.id === ref.id && r.color === ref.color) === i);
        for (const entry of ordered) {
          const ref = { id: entry.id, ...(entry.color ? { color: entry.color } : {}) };
          const pick = button(entry.name || name(ref), () => save(ref)); pick.dataset.material = entry.id;
          const chip = document.createElement('i'); chip.className = 'editor-material-swatch';
          chip.style.backgroundColor = color(entry); chip.setAttribute('aria-hidden', 'true'); pick.prepend(chip);
        }
        if (current) {
          const tintLabel = document.createElement('label'); tintLabel.textContent = 'Tint';
          const tint = document.createElement('input'); tint.type = 'color'; tint.value = color(current);
          tint.setAttribute('aria-label', `${label} tint`); tint.addEventListener('change', () => save({ id: current.id, color: tint.value }));
          tintLabel.append(tint); chooser.append(tintLabel);
        }
        button('Cancel', () => { chooser.remove(); chooser = null; });
        root.append(chooser); chooser.querySelector('button')?.focus();
      } catch (error) { report(error); }
      finally { loading = false; }
    });
  }
  draw(); return root;
}

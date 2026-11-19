import { materialName, describeMaterial, readLibraryCatalog } from './material_catalog.js';
import { report as reportError } from './api.js';
import { createSlotRow, idleLibrary } from './slot_row.js';

let catalogueRead;
// Properties can contain many slots; their initial metadata shares one read.
const loadCatalogue = () => catalogueRead ||= readLibraryCatalog().then(c => c.materials).finally(() => { catalogueRead = null; });

// The owner still supplies one onChange -> one domain op/history step.
export function materialSlot({ label, value = null, defaultLabel, defaultColor = '#b8b0a4',
  quickPicks = [], kit = {}, onChange, readOnly = false, report = reportError,
  library = idleLibrary, ownSlot = () => {}, loadMaterials = loadCatalogue }) {
  let current = value, entries = [], disposed = false;
  const locked = () => typeof readOnly === 'function' ? readOnly() : readOnly;
  const metadata = ref => entries.find(entry => entry.id === ref?.id);
  const name = ref => metadata(ref)?.name || materialName(kit.materials?.[ref.id]?.asset || ref.id);
  const color = ref => ref?.color || metadata(ref)?.color || describeMaterial(ref, kit)?.color || kit.materials?.[ref?.id]?.color
    || Object.values(kit.materials || {}).find(r => r.asset === ref?.id)?.color || '#b8b0a4';
  async function save(next) {
    if (disposed || locked() || JSON.stringify(current) === JSON.stringify(next)) return;
    try { await onChange(next); if (!disposed) { current = next; row.refresh(); } }
    catch (error) { report(error); }
  }
  const row = createSlotRow({ label, library, readOnly: locked,
    accepts: entry => !locked() && entry.kind === 'material',
    current: () => current ? { id: current.id, name: name(current), color: color(current),
      thumb: metadata(current)?.thumbnail_url || metadata(current)?.thumb || describeMaterial(current, kit)?.thumb }
      : { name: `Default: ${defaultLabel}`, color: defaultColor },
    apply: entry => {
      if (!metadata(entry)) entries.push(entry);
      return save({ id: entry.id });
    }, clear: () => save(null),
    tint: { enabled: () => !!current, hasOverride: () => !!current?.color, value: () => color(current),
      set: tint => current && save({ id: current.id, color: tint }), clear: () => current && save({ id: current.id }) } });
  row.element.dataset.materialSlot = label;
  const update = event => {
    if (!disposed && event.detail?.materials) { entries = event.detail.materials; row.refresh(); }
  };
  if (library !== idleLibrary) document.addEventListener('chf-material-catalogue', update);
  const dispose = row.dispose;
  row.dispose = () => { disposed = true; document.removeEventListener('chf-material-catalogue', update); dispose(); };
  ownSlot(row);
  if (library !== idleLibrary || loadMaterials !== loadCatalogue) Promise.resolve().then(loadMaterials).then(materials => {
    if (!disposed) { entries = materials || []; row.refresh(); }
  }).catch(error => { if (!disposed) report(error); });
  return row.element;
}

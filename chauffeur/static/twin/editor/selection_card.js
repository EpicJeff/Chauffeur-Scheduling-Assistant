import { findPiece } from './piece_operations.js';
import { siteShapeLabels } from '../objects.js';
import { createSlotRow, idleLibrary } from './slot_row.js';
import { selectionFields } from './selection_fields.js';
import { drawOpeningModelSlot } from './object_shelf.js';
import { objectOperation } from '../objects.js';
import { pieceMaterialSlots, materialsInSelection, replacementOperations, selectUsingMaterial } from './selection_materials.js';
import { createContextMenu } from './context_menu.js';
import { materialName } from './material_catalog.js';

const noun = {
  planting: ['tree', 'trees'], furniture: ['object', 'objects'], opening: ['opening', 'openings'],
  light_fixture: ['light', 'lights'], effect_fixture: ['effect', 'effects'],
  beds: ['planting bed', 'planting beds'], edges: ['planting edge', 'planting edges'], yard_rooms: ['yard room', 'yard rooms'],
  steps: ['pool steps', 'pool steps'], terraces: ['pad', 'pads'], roof: ['roof', 'roofs'], stair: ['stair', 'stairs'],
};
const fixed = new Set(['room', 'floor', 'roof', 'roof_plane', 'pool', 'building', 'dormer', 'ledge', 'steps', 'spa']);
export const selectionSubject = refs => [...new Set(refs.map(ref => ref.kind))].sort().join('|');
export function selectionCardLayout(plan, refs, options) {
  return JSON.stringify([refs, options.canEdit(), selectionSummary(plan, refs),
    selectionFields(plan, refs, options).map(({ key, value, choices, mixed }) => [key, value, choices, mixed]),
    refs.map(ref => pieceMaterialSlots(plan, ref, options.getKit()).map(({ key, ref, resolved, current }) => [key, ref, resolved, current])),
    refs.map(ref => findPiece(plan, ref.pieceId, ref.buildingId)?.piece.model)]);
}

export function selectionSummary(plan, refs) {
  const groups = new Map();
  for (const ref of refs) {
    const record = findPiece(plan, ref.pieceId, ref.buildingId);
    const kind = ref.kind === 'opening' ? record?.piece.kind || ref.kind : ref.kind;
    if (!groups.has(kind)) groups.set(kind, { kind, refs: [], fixed: fixed.has(kind) });
    groups.get(kind).refs.push(ref);
  }
  return [...groups.values()].map(group => {
    const count = group.refs.length;
    const label = noun[group.kind]?.[count === 1 ? 0 : 1]
      || (siteShapeLabels[group.kind] ? siteShapeLabels[group.kind].toLowerCase() : group.kind.replaceAll('_', ' ')) + (count === 1 ? '' : 's');
    return { ...group, count, label, text: `${count} ${label}${group.fixed ? ' (moves with its building)' : ''}` };
  });
}

function button(text, action, host) {
  const node = document.createElement('button'); node.type = 'button'; node.textContent = text;
  node.addEventListener('click', action); host.append(node); return node;
}

// Both Properties and a surface's context menu offer the very same scope choices.
export function materialSelectionActions({ material, refs, selectionStore, getPlan, getKit = () => ({}), view, visibility }) {
  const choose = limit => selectionStore.set(selectUsingMaterial(getPlan(), material.id,
    { refs, limit, view, visibility, kit: getKit() }));
  return [
    { label: `Select all using ${material.name}`, run: () => choose('all') },
    ...(refs.some(ref => ref.buildingId) ? [{ label: `Select all using ${material.name} in these buildings`, run: () => choose('buildings') }] : []),
    { label: `Select all using ${material.name} in the yard`, run: () => choose('yard') },
  ];
}

// A shared builder for single-piece and set Properties. Library owns reveal and
// selection; the existing edit queue owns saves, refusal reporting and history.
export function drawMaterialsList(host, { refs, getPlan, getKit = () => ({}), library = idleLibrary,
  selectionStore, applyBatch, canEdit, ownSlot, queue = work => work(), onSaved = () => {},
  view, visibility, report, createMenu = createContextMenu, loadNames }) {
  const entries = materialsInSelection(getPlan(), refs, getKit());
  if (!entries.length) return;
  const section = document.createElement('section'); section.setAttribute('aria-label', 'Materials in selection');
  const heading = document.createElement('h4'); heading.textContent = 'Materials in selection'; section.append(heading); host.append(section);
  const lifecycle = new AbortController();
  loadNames?.(() => { if (!lifecycle.signal.aborted) onSaved(); });
  document.addEventListener('chf-material-catalogue', () => {
    if (entries.some(entry => entry.name !== materialName(entry.id))) onSaved();
  }, { signal: lifecycle.signal });
  const menu = createMenu({ signal: lifecycle.signal, items: entry => materialSelectionActions({ material: entry, refs, selectionStore, getPlan, getKit, view, visibility }) });
  ownSlot({ refresh() {}, dispose: () => { menu.close(false); lifecycle.abort(); } });
  for (const entry of entries) {
    const row = createSlotRow({ label: `${entry.name} × ${entry.count} ${entry.count === 1 ? 'surface' : 'surfaces'}`,
      subject: entry.name, library, readOnly: () => !canEdit(), current: () => entry.current,
      detail: () => entry.name, accepts: selected => selected.kind === 'material',
      apply: selected => queue(async () => {
        if (!canEdit()) return;
        const ops = replacementOperations(getPlan(), refs, entry.id, selected, getKit());
        if (ops.length) await applyBatch(ops);
        onSaved();
      }) });
    const use = row.element.querySelector('[data-slot-use]');
    const refresh = row.refresh;
    row.refresh = () => { refresh(); if (use) use.title = library.selected()?.kind === 'material' ? '' : 'Select a material in the Library first.'; };
    const unsubscribe = library.onSelect(row.refresh); row.refresh();
    const dispose = row.dispose; row.dispose = () => { unsubscribe(); dispose(); };
    let actions = row.element.querySelector('.editor-material-actions');
    if (!actions) { actions = document.createElement('div'); actions.className = 'editor-material-actions'; row.element.append(actions); }
    button('Select all using it', event => menu.open(event, entry), actions);
    const reveal = button('Show in Library', () => Promise.resolve(library.reveal('material', entry.id)).catch(report), actions);
    reveal.setAttribute('aria-label', `Show ${entry.name} in Library`);
    reveal.disabled = !entry.current.id;
    if (reveal.disabled) reveal.title = 'This slot uses a colour rather than a Library material.';
    row.element.addEventListener('contextmenu', event => { event.preventDefault(); event.stopPropagation(); menu.open(event, entry); });
    ownSlot(row); section.append(row.element);
  }
}

export function drawSelectionCard(host, options) {
  const { refs, getPlan, getKit = () => ({}), selectionStore, canEdit, library = idleLibrary,
    ownSlot, applyBatch, queue, report, onSaved, removeSelection, visibility, getModel, getFieldLabels } = options;
  const summary = selectionSummary(getPlan(), refs);
  const runQueue = queue || (work => work());
  const heading = document.createElement('h3'); heading.textContent = 'Selected pieces'; host.append(heading);
  button('Close', () => selectionStore.clear(), host).setAttribute('aria-label', 'Close piece card');
  const line = document.createElement('div'); line.dataset.selectionSummary = ''; host.append(line);
  function narrow(group, remove = false) {
    const ids = new Set(group.refs.map(ref => `${ref.buildingId || ''}:${ref.pieceId}`));
    if (remove) selectionStore.set(selectionStore.members().filter(ref => !ids.has(`${ref.buildingId || ''}:${ref.pieceId}`)));
    else if (selectionStore.kinds().get(group.refs[0].kind)?.length === group.count) selectionStore.narrow(group.refs[0].kind);
    else selectionStore.set(group.refs);
  }
  summary.forEach((group, index) => {
    if (index) line.append(' · ');
    button(group.text, event => narrow(group, event.ctrlKey || event.metaKey), line);
  });
  drawMaterialsList(host, options);
  if (selectionStore.kinds().size > 1) {
    for (const group of summary) button(`Narrow to ${group.label} (${group.count})`, () => narrow(group), host);
  } else {
    for (const field of selectionFields(getPlan(), refs, { getModel, getFieldLabels })) {
      const label = document.createElement('label'); label.textContent = field.label;
      const input = document.createElement(field.type === 'select' ? 'select' : 'input');
      input.dataset.field = field.key; input.setAttribute('aria-label', field.label); input.disabled = !canEdit();
      if (field.type === 'select') {
        const choices = field.choices;
        if (field.mixed) { const option = document.createElement('option'); option.value = ''; option.textContent = 'Mixed'; input.append(option); }
        for (const choice of choices || []) {
          const option = document.createElement('option'); option.value = String(choice.value ?? choice); option.textContent = choice.label ?? choice; input.append(option);
        }
        input.value = field.mixed ? '' : String(field.value ?? '');
      } else if (field.type === 'checkbox') {
        input.type = 'checkbox'; input.checked = !!field.value; input.indeterminate = field.mixed;
        if (field.mixed) { const mixed = document.createElement('span'); mixed.textContent = 'Mixed'; mixed.dataset.fieldMixed = ''; label.append(mixed); }
      }
      else { input.type = field.mixed ? 'text' : field.type || 'text'; input.value = field.mixed ? '' : field.format(field.value); input.placeholder = field.mixed ? 'Mixed' : ''; }
      let submitted = null;
      const save = () => {
        if (!canEdit() || (field.mixed && field.type !== 'checkbox' && !input.value.trim())) return;
        const typed = field.type === 'checkbox' ? input.checked : input.value;
        if (typed === submitted) return;
        try {
          const value = field.parse(typed);
          submitted = typed;
          Promise.resolve(runQueue(async () => {
            if (!canEdit()) return;
            const fresh = selectionFields(getPlan(), refs, { getModel, getFieldLabels }).find(candidate => candidate.key === field.key);
            if (!fresh) throw new Error('These pieces no longer share this field.');
            const ops = await fresh.operations(value);
            if (canEdit() && ops.length) await applyBatch(ops);
          })).catch(report).finally(() => { submitted = null; onSaved(); });
        } catch (error) { report(error); }
      };
      input.addEventListener('change', save);
      input.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); save(); } });
      label.append(input); host.append(label);
    }
    const allSlots = refs.map(ref => pieceMaterialSlots(getPlan(), ref, getKit()));
    for (const slot of allSlots[0] || []) {
      const members = allSlots.map(slots => slots.find(candidate => candidate.key === slot.key));
      if (members.some(member => !member)) continue;
      const mixed = members.some(member => JSON.stringify(member.resolved) !== JSON.stringify(slot.resolved));
      const save = change => runQueue(async () => {
        if (!canEdit()) return;
        const current = refs.map(ref => pieceMaterialSlots(getPlan(), ref, getKit()).find(candidate => candidate.key === slot.key));
        if (current.some(member => !member)) throw new Error('These pieces no longer share this slot.');
        const ops = current.flatMap(member => {
          const next = change(member);
          return JSON.stringify(member.ref || null) === JSON.stringify(next || null) ? [] : [member.operation(next)];
        });
        if (ops.length) await applyBatch(ops); onSaved();
      });
      const patch = changes => save(member => {
        const ref = { ...member.ref, ...changes };
        Object.keys(ref).forEach(key => { if (ref[key] === undefined) delete ref[key]; });
        return Object.keys(ref).length ? ref : null;
      });
      const row = createSlotRow({ label: slot.label, library, readOnly: () => !canEdit(),
        current: () => mixed ? { name: 'Mixed' } : slot.current, detail: () => mixed ? 'Mixed' : slot.current.name,
        accepts: entry => entry.kind === 'material', apply: entry => save(() => ({ id: entry.id })),
        clear: { enabled: () => members.some(member => !!member.ref), run: () => save(() => null) },
        tint: { mixed: () => members.some(member => member.resolved?.color !== slot.resolved?.color), value: () => slot.resolved?.color || slot.current.color || '#b8b0a4', hasOverride: () => members.some(member => !!member.ref?.color),
          set: color => patch({ color }), clear: () => patch({ color: undefined }) },
        offset: { mixed: key => members.some(member => (member.resolved?.uv?.[key] ?? 0) !== (slot.resolved?.uv?.[key] ?? 0)),
          setField: (key, value) => save(member => ({ ...member.ref, uv: { u: 0, v: 0, rot: 0, ...member.resolved?.uv, [key]: value } })),
          value: () => members.find(member => member.ref?.uv)?.ref.uv, effective: () => slot.resolved?.uv,
          set: uv => patch({ uv }), clear: () => patch({ uv: undefined }) } });
      ownSlot(row); host.append(row.element);
    }
    if (refs.every(ref => ref.kind === 'opening')) {
      const records = refs.map(ref => findPiece(getPlan(), ref.pieceId, ref.buildingId));
      if (records.every(record => record && (record.piece.kind === 'window') === (records[0].piece.kind === 'window'))) {
        drawOpeningModelSlot(host, records[0], { records, library, ownSlot, canEdit, queue: runQueue, report,
          assign: id => runQueue(async () => {
            if (!canEdit()) return;
            const current = refs.map(ref => findPiece(getPlan(), ref.pieceId, ref.buildingId));
            if (current.some(record => !record)) throw new Error('A selected opening no longer exists.');
            const ops = current.filter(record => (record.piece.model || null) !== id).map(record => objectOperation(record, { model: id }));
            if (ops.length) await applyBatch(ops); onSaved();
          }) });
      }
    }
  }
  const actions = document.createElement('div'); actions.className = 'editor-material-actions'; host.append(actions);
  button('Delete', () => Promise.resolve(removeSelection()).catch(report), actions).disabled = !canEdit();
  if (visibility) {
    button('Hide', () => visibility.setMembers(refs, { hidden: true }), actions);
    button('Lock', () => visibility.setMembers(refs, { locked: true }), actions);
  }
}

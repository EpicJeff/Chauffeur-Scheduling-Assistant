import { findPiece, createPieceLookup } from './piece_operations.js';
import { canTransform, groupRecord } from './group_transform.js';
import { siteShapeLabels } from '../objects.js';
import { createSlotRow, idleLibrary } from './slot_row.js';
import { selectionFields } from './selection_fields.js';
import { drawOpeningModelSlot } from './object_shelf.js';
import { objectOperation } from '../objects.js';
import { pieceMaterialSlots, sharedMaterialRows, materialsInSelection, replacementOperations, selectUsingMaterial } from './selection_materials.js';
import { createContextMenu } from './context_menu.js';
import { materialName } from './material_catalog.js';
import { drawMoveToButton } from './move_to_action.js';

const noun = {
  planting: ['plant', 'plants'], furniture: ['object', 'objects'], opening: ['opening', 'openings'],
  light_fixture: ['light', 'lights'], effect_fixture: ['effect', 'effects'],
  beds: ['planting bed', 'planting beds'], edges: ['planting edge', 'planting edges'], yard_rooms: ['yard room', 'yard rooms'],
  steps: ['pool steps', 'pool steps'], terraces: ['pad', 'pads'], roof: ['roof', 'roofs'], stair: ['stair', 'stairs'],
  garage: ['garage door', 'garage doors'], slider: ['slider', 'sliders'], bifold: ['folding door', 'folding doors'],
  passage: ['open passage', 'open passages'], item: ['item', 'items'], anchor: ['anchor', 'anchors'],
  roof_plane: ['roof slope', 'roof slopes'], solar_zone: ['solar zone', 'solar zones'],
  hardscape: ['path', 'paths'], fire_pit: ['fire pit', 'fire pits'], level: ['floor', 'floors'],
  ledge: ['pool ledge', 'pool ledges'], spa: ['spa', 'spas'], device: ['device', 'devices'],
  porch_post: ['post', 'posts'],
};
const kinds = refs => [...new Set(refs.map(ref => ref.kind || 'piece'))].sort().join('|');
export const selectionSubject = refs => refs.length === 1 ? JSON.stringify([refs[0].buildingId, refs[0].pieceId]) : kinds(refs);
export const sameSelectionSubject = (before, after) => before.length && after.length &&
  (before.length > 1 || after.length > 1 ? kinds(before) === kinds(after) : selectionSubject(before) === selectionSubject(after));
export function selectionCardLayout(plan, refs, options) {
  const lookup = createPieceLookup(plan), kit = options.getKit();
  const fields = selectionFields(plan, refs, { ...options, lookup });
  const allSlots = refs.map(ref => pieceMaterialSlots(plan, ref, kit, lookup));
  return { fields, allSlots, summary: selectionSummary(plan, refs, lookup),
    materials: materialsInSelection(plan, refs, kit, allSlots),
    sharedSlots: sharedMaterialRows(plan, refs, kit, allSlots, lookup),
    records: refs.map(ref => lookup(ref.pieceId, ref.buildingId)),
    structure: JSON.stringify([kinds(refs), fields.map(({key, type, choices}) => [key, type, choices])]) };
}

export function selectionSummary(plan, refs, lookup = (id, bid) => findPiece(plan, id, bid)) {
  const groups = new Map();
  for (const ref of refs) {
    const record = lookup(ref.pieceId, ref.buildingId);
    const kind = (ref.kind === 'opening' ? record?.piece.kind || ref.kind : ref.kind || record?.kind) || 'piece';
    const fixed = !canTransform(groupRecord(plan, ref), 'move');
    const key = `${kind}:${fixed}`;
    if (!groups.has(key)) groups.set(key, { kind, refs: [], fixed });
    groups.get(key).refs.push(ref);
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
  const choose = limit => {
    const matches = selectUsingMaterial(getPlan(), material.id, { refs, limit, view, visibility, kit: getKit() });
    if (matches.length) selectionStore.set(matches);
    else {
      const status = document.getElementById('editor-status');
      if (status) status.textContent = `Nothing ${limit === 'yard' ? 'in the yard' : limit === 'buildings' ? 'in these buildings' : 'in the house or yard'} uses ${material.name}`;
    }
  };
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
  view, visibility, report, createMenu = createContextMenu, loadNames, onNamesChanged = onSaved, entries = materialsInSelection(getPlan(), refs, getKit()) }) {
  if (!entries.length) return;
  const section = document.createElement('section'); section.setAttribute('aria-label', 'Materials in selection');
  const heading = document.createElement('h4'); heading.textContent = 'Materials in selection'; section.append(heading); host.append(section);
  const lifecycle = new AbortController();
  loadNames?.(() => { if (!lifecycle.signal.aborted) onNamesChanged(); });
  document.addEventListener('chf-material-catalogue', () => {
    if (entries.some(entry => entry.name !== materialName(entry.id))) onNamesChanged();
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
    button('Select all using it', event => {
      const rect = event.currentTarget.getBoundingClientRect();
      menu.open(!event.clientX && !event.clientY ? [rect.left, rect.bottom] : event, entry);
    }, actions);
    const reveal = button('Show in Library', () => Promise.resolve(library.reveal('material', entry.id)).catch(report), actions);
    reveal.setAttribute('aria-label', `Show ${entry.name} in Library`);
    reveal.disabled = !entry.current.id;
    if (reveal.disabled) reveal.title = 'This slot uses a colour rather than a Library material.';
    row.element.addEventListener('contextmenu', event => { event.preventDefault(); event.stopPropagation(); menu.open(event, entry); });
    ownSlot(row); section.append(row.element);
  }
}

export function drawSelectionCard(host, options) {
  let { refs } = options;
  const { getPlan, getKit = () => ({}), selectionStore, canEdit, library = idleLibrary,
    ownSlot, applyBatch, queue, report, onSaved, removeSelection, visibility, getModel, getFieldLabels } = options;
  let data = options.prepared || selectionCardLayout(getPlan(), refs, options);
  const runQueue = queue || (work => work());
  const heading = document.createElement('h3'); heading.textContent = 'Selected pieces'; host.append(heading);
  button('Close', () => selectionStore.clear(), host).setAttribute('aria-label', 'Close piece card');
  const line = document.createElement('div'); line.dataset.selectionSummary = ''; host.append(line);
  const materialsHost = document.createElement('div'), fieldHost = document.createElement('div'), slotHost = document.createElement('div');
  host.append(materialsHost, fieldHost, slotHost);
  const fieldStates = new Map(), materialRows = [];
  const ownMaterial = row => materialRows.push(row);
  const disposeMaterials = () => { for (const row of materialRows.splice(0)) row.dispose(); };
  ownSlot({ refresh() {}, dispose: disposeMaterials });
  function narrow(group, remove = false) {
    const ids = new Set(group.refs.map(ref => `${ref.buildingId || ''}:${ref.pieceId}`));
    if (remove) selectionStore.set(selectionStore.members().filter(ref => !ids.has(`${ref.buildingId || ''}:${ref.pieceId}`)));
    else if (selectionStore.kinds().get(group.refs[0].kind)?.length === group.count) selectionStore.narrow(group.refs[0].kind);
    else selectionStore.set(group.refs);
  }
  const raw = input => input.type === 'checkbox' ? input.checked : input.value;
  function refreshField(state, field) {
    state.field = field;
    const { input } = state;
    if (!state.queued && document.activeElement !== input && (state.baseline === undefined || raw(input) === state.baseline)) {
      if (field.type === 'select') {
        input.replaceChildren();
        if (field.mixed) { const option = document.createElement('option'); option.value = ''; option.textContent = 'Mixed'; input.append(option); }
        for (const choice of field.choices || []) {
          const option = document.createElement('option'); option.value = String(choice.value ?? choice); option.textContent = choice.label ?? choice; input.append(option);
        }
        input.value = field.mixed ? '' : String(field.value ?? '');
      } else if (field.type === 'checkbox') {
        input.type = 'checkbox'; input.checked = !!field.value; input.indeterminate = field.mixed;
        state.mixed.hidden = !field.mixed;
      } else {
        input.type = field.mixed ? 'text' : field.type || 'text';
        input.value = field.mixed ? '' : field.format(field.value); input.placeholder = field.mixed ? 'Mixed' : '';
      }
      state.baseline = raw(input);
    }
    input.disabled = !canEdit();
  }
  for (const field of data.fields) {
    const label = document.createElement('label'); label.textContent = field.label;
    const input = document.createElement(field.type === 'select' ? 'select' : 'input');
    input.dataset.field = field.key; input.setAttribute('aria-label', field.label);
    const state = { input, field, baseline: undefined, queued: false, submitted: null };
    if (field.type === 'checkbox') { state.mixed = document.createElement('span'); state.mixed.textContent = 'Mixed'; state.mixed.dataset.fieldMixed = ''; label.append(state.mixed); }
    refreshField(state, field); fieldStates.set(field.key, state);
    const save = () => {
      const field = state.field, typed = raw(input);
      if (!canEdit() || typed === state.submitted || (field.mixed && field.type !== 'checkbox' && !input.value.trim())) return;
      try {
        const value = field.parse(typed);
        state.submitted = typed; state.queued = true;
        // Capture the owners at submission; later selection additions are a new edit.
        const owners = refs;
        Promise.resolve(runQueue(async () => {
          if (!canEdit()) return;
          const fresh = selectionFields(getPlan(), owners, { getModel, getFieldLabels }).find(candidate => candidate.key === field.key);
          if (!fresh) throw new Error('These pieces no longer share this field.');
          const ops = await fresh.operations(value);
          if (canEdit() && ops.length) await applyBatch(ops);
          // Mark only the submitted text clean; typing during this save stays dirty.
          if (raw(input) === typed) state.baseline = typed;
        })).catch(report).finally(() => { state.submitted = null; state.queued = false; onSaved(); });
      } catch (error) { report(error); }
    };
    input.addEventListener('change', save);
    input.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); save(); } });
    label.append(input); fieldHost.append(label);
  }
  function renderMaterials() {
    const owners = refs;
    disposeMaterials(); materialsHost.replaceChildren(); slotHost.replaceChildren(); line.replaceChildren();
    data.summary.forEach((group, index) => {
      if (index) line.append(' \u00b7 ');
      button(group.text, event => narrow(group, event.ctrlKey || event.metaKey), line);
    });
    drawMaterialsList(materialsHost, { ...options, refs, entries: data.materials, ownSlot: ownMaterial });
    if (selectionStore.kinds().size > 1) {
      for (const group of data.summary) button(`Narrow to ${group.label} (${group.count})`, () => narrow(group), slotHost);
      return;
    }
    for (const shared of data.sharedSlots) {
      const slot = shared.matches[0].slot, members = shared.matches.map(match => match.slot);
      const mixed = members.some(member => JSON.stringify(member.resolved) !== JSON.stringify(slot.resolved));
      const save = change => runQueue(async () => {
        if (!canEdit()) return;
        const current = sharedMaterialRows(getPlan(), owners, getKit()).find(row => row.key === shared.key)?.matches.map(match => match.slot);
        if (!current?.length) throw new Error('These pieces no longer share this slot.');
        const seenOps = new Set();
        const ops = current.flatMap(member => {
          const next = change(member);
          if (JSON.stringify(member.ref || null) === JSON.stringify(next || null)) return [];
          const op = member.operation(next), opKey = JSON.stringify(op);
          if (seenOps.has(opKey)) return [];
          seenOps.add(opKey);
          return [op];
        });
        if (ops.length) await applyBatch(ops); onSaved();
      });
      const patch = changes => save(member => {
        const ref = { ...member.ref, ...changes };
        Object.keys(ref).forEach(key => { if (ref[key] === undefined) delete ref[key]; });
        return Object.keys(ref).length ? ref : null;
      });
      const row = createSlotRow({ label: shared.label, library, readOnly: () => !canEdit(),
        materialSurface: () => ({ ...shared.matches[0].owner, slot: shared.matches[0].slot.key }),
        current: () => mixed ? { name: 'Mixed' } : slot.current, detail: () => mixed ? 'Mixed' : slot.current.name,
        accepts: entry => entry.kind === 'material', apply: entry => save(() => ({ id: entry.id })),
        clear: { enabled: () => members.some(member => !!member.ref), run: () => save(() => null) },
        tint: { mixed: () => members.some(member => member.resolved?.color !== slot.resolved?.color), value: () => slot.resolved?.color || slot.current.color || '#b8b0a4', hasOverride: () => members.some(member => !!member.ref?.color),
          set: color => patch({ color }), clear: () => patch({ color: undefined }) },
        offset: { mixed: key => members.some(member => (member.resolved?.uv?.[key] ?? 0) !== (slot.resolved?.uv?.[key] ?? 0)),
          setField: (key, value) => save(member => ({ ...member.ref, uv: { u: 0, v: 0, rot: 0, ...member.resolved?.uv, [key]: value } })),
          value: () => members.find(member => member.ref?.uv)?.ref.uv, effective: () => slot.resolved?.uv,
          set: uv => patch({ uv }), clear: () => patch({ uv: undefined }) } });
      ownMaterial(row); slotHost.append(row.element);
    }
    if (refs.every(ref => ref.kind === 'opening')) {
      const records = data.records;
      if (records.every(record => record && (record.piece.kind === 'window') === (records[0].piece.kind === 'window'))) {
        drawOpeningModelSlot(slotHost, records[0], { records, library, ownSlot: ownMaterial, canEdit, queue: runQueue, report,
          assign: id => runQueue(async () => {
            if (!canEdit()) return;
            const current = owners.map(ref => findPiece(getPlan(), ref.pieceId, ref.buildingId));
            if (current.some(record => !record)) throw new Error('A selected opening no longer exists.');
            const ops = current.filter(record => (record.piece.model || null) !== id).map(record => objectOperation(record, { model: id }));
            if (ops.length) await applyBatch(ops); onSaved();
          }) });
      }
    }
  }
  const actions = document.createElement('div'); actions.className = 'editor-material-actions'; host.append(actions);
  const moveTo = drawMoveToButton(actions, { ...options, getRefs: () => refs });
  const remove = button('Delete', () => Promise.resolve(removeSelection()).catch(report), actions);
  if (visibility) {
    button('Hide', () => visibility.setMembers(refs, { hidden: true }), actions);
    button('Lock', () => visibility.setMembers(refs, { locked: true }), actions);
  }
  renderMaterials(); remove.disabled = !canEdit();
  function refresh() {
    moveTo?.refresh();
    for (const field of data.fields) refreshField(fieldStates.get(field.key), field);
    remove.disabled = !canEdit();
  }
  return { structure: data.structure, refresh, update(prepared, members) {
    data = prepared; refs = members;
    refresh(); renderMaterials();
  } };
}

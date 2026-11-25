import { findPiece, deleteOperation } from './piece_operations.js';
export { findPiece } from './piece_operations.js';
import { drawObjectShelf, isObject } from './object_shelf.js';
import { solarLayout } from '../twin_solar.js';
import { isSupported } from '../roof_supports.js';
import { roofSupportShelf } from './roof_support_shelf.js';
import { roofArea, roofEdges } from '../roof_box_contract.js';
import { contains } from '../twin_generator.js';
import { materialLines } from './library.js';
import { createSlotRow, idleLibrary } from './slot_row.js';
import { keepPlace } from './keep_place.js';
import { drawSelectionCard, drawMaterialsList, sameSelectionSubject, selectionCardLayout } from './selection_card.js';
import { feetInches, parseLength } from './selection_fields.js';
export { feetInches, parseLength } from './selection_fields.js';
import { createEquipmentShelf } from './equipment_shelf.js';
import { foundationShelf } from './foundation_shelf.js';
import { houseMaterialsShelf } from './house_materials.js';
import { porchFoundationShelf, porchShelfOnGrade } from './porch_foundation_shelf.js';
import { stairShelf } from './stair_shelf.js';
import { siteShapeKinds, siteShapeLabels } from '../objects.js';
import { drawSiteShapeShelf, yardRoomFeatures } from './site_shape_shelf.js';
import { propertyPath } from './dock.js';
import { drawPorchPostShelf, drawPorchPostFooter, drawPorchPostsSection, porchPostTitle } from './porch_post_shelf.js';
import { drawMoveToButton } from './move_to_action.js';
import { gutterSnapshot, eaveEdges, edgeOperation, downspoutValues, addDownspout, gutterLocation, isExact, entryFraction, placedFraction, nearestFreeCandidate, roundAt, sameDownspoutEntry, isMergedEntry } from './gutter_controls.js';

const report = error => {
  if (!error.shown && !error.cancelled) window.showGlobalAlert(error.message || 'Could not save this change.');
};

// Ordinary fields follow twin_edit.EDITABLE. Length is derived and saves by
// moving the second joint; it is never sent as a legacy set-field edit.
const fields = {
  wall: ['length', 'height', 'thickness', 'exterior'], opening: ['width', 'sill', 'head', 'kind', 'panels', 'at'],
  room: ['name', 'kind', 'floor_offset_ft'], roof: ['kind', 'pitch', 'plate', 'overhang', 'ridge', 'low_side', 'ends'],
  building: ['name', 'position', 'rotation', 'base'], level: ['name', 'elevation', 'ceiling'],
  // Hosted pieces save through model ops (twin_model_ops: set, move_hosted).
  anchor: ['offset'], item: ['rotation', 'scale', 'offset'],
};
const lengths = new Set(['length', 'height', 'thickness', 'width', 'sill', 'head', 'at', 'plate', 'overhang', 'base', 'elevation', 'ceiling', 'offset', 'floor_offset_ft']);
const labels = { low_side: 'Low side', at: 'Distance along the wall', ridge: 'Ridge',
  sill: 'Height above floor', head: 'Top of opening', plate: 'Wall height under the roof', base: 'Height above ground', elevation: 'Height above ground',
  offset: 'Distance from surface', floor_offset_ft: 'Floor height (relative to this floor)' };
const hostedLabels = { rotation: 'Turn', scale: 'Size' };
const units = { pitch: 'in 12', rotation: '°', scale: '%' };
export function createCards({ getPlan, getModel = () => null, getKit = () => ({}), getLabel, getSelection = () => ({}), getFieldLabels = () => ({}), edit, op, addDormer, ask, canEdit, select, library = idleLibrary, haLink, preview, onDrawFeature, splitWall, loadMaterialNames = null, dock, openHouseMaterials, removeSelection, selectionStore, applyBatch = ops => op({ op: 'batch', ops }), visibility, view, chooseDestination, focusRoom, leaveRoom }) {
  let namesAsked = false, namesRead = null;
  function loadNames(onReady) {
    if (!loadMaterialNames) return;
    if (!namesAsked) {
      namesAsked = true;
      namesRead = Promise.resolve(loadMaterialNames()).finally(() => { namesRead = null; });
    }
    namesRead?.then(onReady, () => { namesAsked = false; });
  }
  const host = document.getElementById('piece-card');
  let selection = null, pending = Promise.resolve(), inputs = new Map(), headingNode = null, acceptButton = null, pitchNote = null, layout = null;
  let edgeIndex = null, edgePlan = null, cardMembers = [], setCard = null, setCache = null;
  let haSection = null;
  const slots = [];
  const ownSlot = row => slots.push(row);
  const disposeSlots = () => { for (const row of slots.splice(0)) row.dispose(); };
  const equipmentShelf = createEquipmentShelf({ canEdit, queue, op, report, parseLength, feetInches, onSaved: () => draw() });
  const endNames = { x0: 'Left end', x1: 'Right end', y0: 'Front end', y1: 'Back end' };
  const fieldValue = (piece, field) => field === 'length' ? Math.hypot(...piece.to.map((v, i) => v - piece.from[i]))
    : field.startsWith('ends.') ? (piece.ends?.[field.slice(5)] ?? piece.kind) : piece[field];
  const title = record => {
    const { kind, piece, building } = record;
    if (kind === 'porch_post') return porchPostTitle(record);
    const name = kind==='solar_zone'?'Solar zone':kind==='anchor' && ['meter','electric_panel','charger','parking'].includes(piece.kind)?(piece.name || ({meter:'Meter',electric_panel:'Electric panel',charger:'Charger',parking:'Parking spot'}[piece.kind])):kind === 'opening' ? (piece.kind === 'window' ? 'Window' : 'Door')
      : piece.name || piece.preset || siteShapeLabels[kind] || (kind === 'roof' ? isSupported(piece) ? 'Awning' : 'Roof section' : kind[0].toUpperCase() + kind.slice(1));
    if (!['wall', 'opening'].includes(kind)) return name;
    const wall = kind === 'wall' ? piece : building.walls.find(w => w.id === (piece.wall || piece.host?.wall));
    const room = building.rooms?.find(r => r.id === getSelection().room);
    if (!wall || !room?.polygon?.length) return name;
    const [a, b] = [wall.from, wall.to], length = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if (!length) return name;
    let nx = (b[1] - a[1]) / length, ny = -(b[0] - a[0]) / length;
    const x = (a[0] + b[0]) / 2 + .25 * nx, y = (a[1] + b[1]) / 2 + .25 * ny;
    if (contains(room.polygon, [x, y])) { nx = -nx; ny = -ny; }
    const angle = (building.rotation || 0) * Math.PI / 180;
    const east = Math.cos(angle) * nx - Math.sin(angle) * ny, north = Math.sin(angle) * nx + Math.cos(angle) * ny;
    const direction = Math.abs(east) >= Math.abs(north) ? east > 0 ? 'east' : 'west' : north > 0 ? 'north' : 'south';
    const wallName = `${room.name || 'Room'}, ${direction} wall`;
    return kind === 'wall' ? wallName : `${name}, ${(room.name || 'Room').toLowerCase()} ${direction} wall`;
  };
  const display = (field, value, kind) => kind && hostedLabels[field]
    ? String(field === 'scale' ? Math.round((value ?? 1) * 100) : Math.round((value ?? 0) * 100) / 100)
    : lengths.has(field) ? feetInches(value || 0)
      : field === 'position' ? (value || [0, 0]).map(feetInches).join(', ') : String(value ?? '');
  const hosted = kind => kind === 'anchor' || kind === 'item';
  const raw = input => input.type === 'checkbox' ? input.checked : input.value;
  const roofFlags = record => record?.kind === 'roof' && record.piece.block && !record.piece.dormer_of
    ? (record.building.roof.flags || []).filter(flag => flag.block_rect?.length === 4
      && flag.block_rect.every((v, i) => Math.abs(v - record.piece.block[i]) <= 1)) : [];
  // The Home Assistant section redraws only when what it shows changes, and
  // never pulls a pick-list out from under a person (ha_link.js draw).
  function drawHaSection(record) {
    if (haSection) haLink.draw(haSection, record);
  }
  // A field that shows or hides other fields rebuilds the card: keep the person's place.
  function draw(next = selection) {
    const members = selectionStore?.members() || (next ? [next] : []);
    const resolved = members.map(ref => ref.kind ? ref : { ...ref, kind: findPiece(getPlan(), ref.pieceId, ref.buildingId)?.kind });
    const same = sameSelectionSubject(cardMembers, resolved);
    cardMembers = resolved;
    return same ? keepPlace(host, () => drawCard(next)) : drawCard(next);
  }
  function drawCard(next = selection) {
    const members = selectionStore?.members() || (next ? [next] : []);
    const materialOptions = refs => ({ refs, getPlan, getLabel, getModel, getKit, getFieldLabels, selectionStore, applyBatch, chooseDestination, canEdit, library, ownSlot, queue, report, view, visibility, loadNames, onSaved: () => { if (refs.length === 1) layout = null; draw(); }, onNamesChanged: () => { setCache = null; if (refs.length === 1) layout = null; draw(); } });
    if (members.length > 1) {
      // Polls reuse the prepared rows. Values changing in a new plan do not
      // change the field structure or replace inputs with unsaved text.
      const plan = getPlan(), key = JSON.stringify(members), editable = canEdit();
      if (setCache?.plan === plan && setCache.key === key && setCache.editable === editable) { selection = next; setCard?.refresh(); return; }
      const prepared = selectionCardLayout(plan, members, { getModel, getFieldLabels, getKit, canEdit });
      setCache = { plan, key, editable };
      selection = next;
      if (setCard && setCard.structure === prepared.structure) { setCard.update(prepared, members); return; }
      host.dispatchEvent(new Event('fixturecardrelease'));
      layout = prepared.structure; edgeIndex = null; disposeSlots(); host.replaceChildren(); inputs = new Map(); haSection = null;
      host.hidden = false;
      dock?.properties.render(host, { crumbs: ['Selected pieces'], reveal: false });
      setCard = drawSelectionCard(host, { ...materialOptions(members), prepared, removeSelection });
      return;
    }
    setCard = null; setCache = null;
    if (!next && host.dataset.fixtureCard) return;
    if (next || host.dataset.stairDraft) host.dispatchEvent(new Event('fixturecardrelease'));
    // The two-click add tool temporarily owns the same card surface. Polling
    // selection/HA while no piece is selected must leave its fields in place.
    if (!next && host.dataset.stairDraft) {
      host.querySelectorAll('input, select').forEach(input => { input.disabled = !canEdit(); });
      return;
    }
    if (next?.pieceId !== selection?.pieceId || next?.buildingId !== selection?.buildingId) edgeIndex = null;
    const record = next && findPiece(getPlan(), next.pieceId, next.buildingId);
    if (record?.kind === 'proposal') { host.hidden = true; dock?.properties.clear(host); return; }
    if (record) dock?.properties.render(host, { ...propertyPath(record, getSelection(), select),
      reveal: next?.pieceId !== selection?.pieceId || next?.buildingId !== selection?.buildingId });
    else dock?.properties.clear(host);
    const authoredRoof = record?.kind === 'roof' && record.building.roofs?.find(r => r.id === (record.piece.roof || record.piece.id));
    const roof = authoredRoof && {...authoredRoof, area:roofArea(authoredRoof), edges:roofEdges(authoredRoof)};
    if (roof && edgeIndex !== null) { drawEdge(next, record, roof); return; }
    const materials = record ? materialLines(record, getPlan(), getKit()) : [];
    // One catalogue read per session names household materials on the lines.
    if ((materials.length && canEdit() || record?.kind === 'building') && loadMaterialNames && !namesAsked) {
      loadNames(() => { layout = null; draw(); });
    }
    const flags = roofFlags(record);
    const roomFeatures = record?.kind === 'yard_rooms' ? yardRoomFeatures(getPlan(), record.piece) : [];
    const isPorch = record?.kind === 'porch' || record?.kind === 'room' && record.piece.kind === 'porch';
    const porchLayout = isPorch
      ? JSON.stringify([record.piece.foundation, record.kind === 'room' ? porchShelfOnGrade(getPlan(), record.building, record.piece) : null, canEdit()])
      : '';
    const garageLayout = record?.kind === 'opening' && record.piece.kind === 'garage'
      ? JSON.stringify([record.building.devices, haLink?.state()?.devices?.map(d => [d.device_id, d.kind, d.entity_id])]) : '';
    const nextLayout = JSON.stringify([getSelection().room, members.map(ref => ref.slots), roomFeatures, record?.kind === 'yard_rooms' ? !!haLink?.state()?.available : null, record?.kind === 'building' ? `building:${JSON.stringify([record.piece.foundation, record.piece.materials, getPlan().materials, canEdit()])}` : record?.kind === 'roof' ? `${record.piece.kind}:${record.piece.ridge}:${JSON.stringify(flags)}` : ['solar_zone', 'stair'].includes(record?.kind)?JSON.stringify([record.piece, canEdit()]):record?.kind==='anchor'?`${record.kind}:${record.piece.kind}`:record?.kind, materials, canEdit(), record && siteShapeKinds.includes(record.kind) ? [record.piece, canEdit()] : record && (isObject(record) || record.kind === 'opening') ? record.piece : null,
      roof && [roof.edges, roof.support, roof.host, roof.thickness_ft, roof.fascia, roof.plate, roof.area, roof.roof_frame, roof.ends, roof.underside, record.building.walls], record && [record.piece.gutter, record.building?.porches?.map(p => [p.id, p.gutter])]]);
    host.hidden = !record;
    // Object properties participate in the layout signature. A completed Size
    // save must not detach Turn while the person is typing the next edit.
    const editingItem = record?.kind === 'item' && [...inputs.values()].some(({ input, baseline, queued }) =>
      document.activeElement === input || queued || raw(input) !== baseline);
    if (record && (layout === nextLayout + porchLayout + garageLayout || editingItem) && selection?.pieceId === next.pieceId && selection?.buildingId === next.buildingId) {
      headingNode.textContent = title(record);
      if (pitchNote) pitchNote.hidden = record.piece.pitch_source !== 'photos';
      if (acceptButton) acceptButton.hidden = record.piece.state !== 'ghost' && !flags.length;
      host.querySelectorAll('button').forEach(b => { if (b.closest('[data-library-slot]')) return; b.disabled = b.dataset.gutterDisabled !== undefined || b.dataset.fixtureLocked !== undefined || b.dataset.postDisabled !== undefined || !canEdit() && b.dataset.fixtureBrowse === undefined && b.dataset.selectPorch === undefined && b.dataset.selectionFocus === undefined && b.getAttribute('aria-label') !== 'Close piece card'; });
      // A save or poll refreshes clean values without replacing anyone's input.
      for (const [field, state] of inputs) {
        const { input } = state;
        if (document.activeElement !== input && raw(input) === state.baseline && !state.queued) {
          if (field === 'exterior') input.checked = !!record.piece[field];
          else input.value = display(field, fieldValue(record.piece, field), hosted(record.kind) && record.kind);
          state.baseline = raw(input);
        }
        input.disabled = !canEdit() || field === 'length' && !record.piece.joints?.[1];
      }
      slots.forEach(row => row.refresh());
      drawHaSection(record);
      if (kindIsEquipment(record)) equipmentShelf.refresh(record);
      return;
    }
    selection = next; layout = nextLayout + porchLayout + garageLayout; disposeSlots(); host.replaceChildren(); inputs = new Map(); acceptButton = null; pitchNote = null;
    haSection = null;
    if (!record) return;
    const { piece, kind, building } = record;
    const heading = headingNode = document.createElement('h3'); heading.textContent = title(record);
    const close = button('Close', () => select(null)); close.setAttribute('aria-label', 'Close piece card');
    host.append(heading, close);
    if (kind === 'wall' && piece.state !== 'ghost' && splitWall) host.append(button('Split wall', () => splitWall(record)));
    if (kind === 'stair') stairShelf(host, piece, building, { canEdit, report,
      change: (field, value) => queue(async () => {
        if (!canEdit()) return;
        await op({ op: 'update_stair', building: building.id, id: piece.id, [field]: value });
        layout = null; draw();
      }) });
    if (kind === 'porch_post') drawPorchPostShelf(host, record, { getPlan, canEdit, queue, op, report, ownSlot, onSaved: () => draw() });
    if (selectionStore) drawMaterialsList(host, materialOptions(members));
    for (const material of materials) {
      const save = ref => queue(async () => {
        if (!canEdit()) return;
        await op({ op:'set_material', building:building.id, target:material.target, material:ref });
        material.setRef(ref);
      });
      const patch = change => {
        const next = { ...material.ref, ...change };
        for (const key of Object.keys(next)) if (next[key] === undefined) delete next[key];
        return save(Object.keys(next).length ? next : null);
      };
      const row = createSlotRow({ label: material.label, library, readOnly: () => !canEdit(),
        materialSurface: () => ({ ...material.surface, target: material.target }),
        current: () => material.current, detail: () => material.text, inherited: () => material.inherited,
        accepts: entry => entry.kind === 'material',
        // Clear only where something is set here; an inherited slot has nothing to clear.
        apply: entry => save({id:entry.id}), clear: { enabled: () => material.clear, run: () => save(null) },
        tint: { value:() => material.current?.color || '#b8b0a4', hasOverride:() => !!material.ref?.color,
          set:color => patch({color}), clear:() => patch({color:undefined}) },
        offset: { value:() => material.ref?.uv, effective:() => material.resolved.uv,
          set:uv => patch({uv}), clear:() => patch({uv:undefined}) },
        reset: material.reset ? { label: material.reset.label,
          run: () => queue(() => canEdit() && op({ op: 'set_material', building: building.id, target: material.reset.target, material: null })) } : null });
      ownSlot(row); host.append(row.element);
    }
    if (kind === 'porch_post') drawPorchPostFooter(host, record, { select });
    if (kind === 'roof') {
      pitchNote = document.createElement('p'); pitchNote.textContent = 'Estimated from photos';
      pitchNote.hidden = piece.pitch_source !== 'photos'; host.append(pitchNote);
      for (const flag of flags) {
        const note = document.createElement('p'); note.textContent = flag.text; host.append(note);
      }
      if (roof && op) {
        const change = operation => queue(async () => {
          if (!canEdit()) return;
          await op({ building: building.id, id: roof.id, ...operation });
          layout = null; draw();
        });
        roofSupportShelf(host, roof, building, { canEdit, report,
          save: fields => change({ op: 'set_roof_support', ...fields }),
          move: by => change({ op: 'move_roof', by }),
          setPlate: value => change({ op: 'set', field: 'plate', value }) });
        const allGutters = enabled => queue(async () => {
          if (!canEdit()) return;
          const b = getPlan().buildings.find(b => b.id === building.id), current = b?.roofs?.find(r => r.id === roof.id);
          const r = current && {...current, edges:roofEdges(current)};
          if (!r) return;
          const edges = enabled ? eaveEdges(b, r).filter(i => !r.edges[i].gutter) : r.edges.flatMap((e, i) => e.gutter ? [i] : []);
          if (edges.length) await op({ op: 'batch', ops: edges.map(i => edgeOperation(b.id, r.id, i, { gutter: enabled })) });
          layout = null; draw();
        });
        const enable = button('Gutters on all eaves', () => allGutters(true)), remove = button('Remove all gutters', () => allGutters(false));
        if (!eaveEdges(building, roof).some(i => !roof.edges[i].gutter)) { enable.disabled = true; enable.dataset.gutterDisabled = ''; }
        if (!roof.edges.some(e => e.gutter)) { remove.disabled = true; remove.dataset.gutterDisabled = ''; }
        host.append(enable, remove);
        roof.edges.forEach((edge, index) => host.append(button(`Edge ${index + 1}: ${edge.setting === 'clip' ? 'Clipped' : edge.setting === 'gable' ? 'Gable' : 'Sloped'}`, () => {
          edgeIndex = index; layout = null; draw();
        })));
        if (addDormer) host.append(button('Add dormer', addDormer));
      }
    }
    if(kind==='roof' || kind==='solar_zone'){
      host.append(button('Solar ribbon starts here',()=>op({op:'set_solar_source',building:building.id,roof:kind==='solar_zone'?piece.roof:piece.roof || piece.id})));
    }
    if(kind==='solar_zone'){
      const total=document.createElement('p');total.textContent=`${solarLayout(piece).length} panels`;host.append(total);
      const saveZone=change=>{pending=pending.then(()=>op({op:'update_solar_zone',building:building.id,id:piece.id,...change})).catch(report);return pending;};
      for(const [field,text] of [['rect','Zone rectangle (u, v, u2, v2 in feet)'],['panel_width','Panel width'],['panel_height','Panel height'],['orientation','Orientation'],['gap','Gap'],['setback','Setback'],['count','Panel count (empty fills zone)'],['entity','Production sensor (optional)']]){
        const label=document.createElement('label');label.textContent=text;
        const input=document.createElement(field==='orientation'?'select':'input');
        if(field==='orientation')for(const value of ['portrait','landscape']){const option=document.createElement('option');option.value=value;option.textContent=value;input.append(option);}
        else input.type='text';
        input.value=field==='rect'?piece.rect.join(', '):['panel_width','panel_height','gap','setback'].includes(field)?feetInches(piece[field]):piece[field] ?? '';
        input.disabled=!canEdit();input.setAttribute('aria-label',text);
        input.addEventListener('change',()=>{if(!canEdit())return;try{
          const value=field==='rect'?input.value.split(',').map(parseLength):['panel_width','panel_height','gap','setback'].includes(field)?parseLength(input.value):field==='count'?(input.value.trim()?Number(input.value):null):input.value || null;
          saveZone({[field]:value}).then(()=>{layout=null;draw();});
        }catch(error){report(error);}});label.append(input);host.append(label);
      }
    }
    drawPorchPostsSection(host, record, { getPlan, canEdit, queue, op, applyBatch, report, ownSlot, select, visibility, onSaved: () => draw() });
    if (kindIsEquipment(record)) equipmentShelf.draw(host, record);
    if (kind === 'building') {
      foundationShelf(host, piece, { library, ownSlot, getPlan, getKit, canEdit, queue, op, report, preview });
      if (openHouseMaterials) host.append(button('House materials', () => openHouseMaterials(piece.id)));
      else houseMaterialsShelf(host, piece, { library, ownSlot, getPlan, getKit, canEdit, op: operation => queue(() => canEdit() && op(operation)), report });
    }
    if (focusRoom && ['room', 'porch', 'level'].includes(kind)) {
      const focused = getSelection().room === piece.id;
      const focus = button(focused ? 'Leave room' : 'Focus room', () => focused ? leaveRoom?.()
        : focusRoom({ kind, id: piece.id, building: building.id, level: kind === 'level' ? piece.id : piece.level }));
      focus.dataset.selectionFocus = ''; focus.disabled = false; host.append(focus);
    }
    if (kind === 'room' && piece.kind === 'porch') porchFoundationShelf(host, piece, building,
      { library, ownSlot, getPlan, getKit, canEdit, queue, op, report, onSaved: () => draw() });
    if (kind === 'porch' || kind === 'room' && piece.kind === 'porch') {
      const detail = kind === 'room' ? building.porches?.find(p => p.id === piece.id) || piece : piece;
      gutterToggle(!!detail.gutter, value => queue(async () => {
        if (!canEdit()) return;
        await op({ op: 'set', building: building.id, id: piece.id, field: 'gutter', value });
        layout = null; draw();
      }));
    }
    if (isObject(record) || kind === 'opening') drawObjectShelf(host, record, { library, ownSlot, canEdit, queue, op, report,
      getRecord: () => findPiece(getPlan(), piece.id, building?.id), devices: haLink?.state()?.devices || [] });
    if (siteShapeKinds.includes(kind) || record.poolId) {
      for (const feature of roomFeatures) {
        const button = document.createElement('button'); button.type = 'button';
        button.disabled = !canEdit();
        button.textContent = `Edit ${piece.feature?.feature ? 'Spa' : feature.piece.name || siteShapeLabels[feature.kind]} materials`;
        button.addEventListener('click', () => {
          const next = {pieceId: feature.piece.id, buildingId: null}; select(next); draw(next);
        });
        host.append(button);
      }
      drawSiteShapeShelf(host, record, { library, ownSlot, canEdit, queue, op, report, getPlan, getKit, onDrawFeature,
        haAvailable: !!haLink?.state()?.available,
        onMakeRoom: () => {
          const room = getPlan().site?.yard_rooms?.at(-1);
          if (room) { select({ pieceId: room.id, buildingId: null }); layout = null; draw({ pieceId: room.id, buildingId: null });
            host.querySelector('input[aria-label="Name"]')?.focus(); host.querySelector('input[aria-label="Name"]')?.select(); }
        },
        getRecord: () => findPiece(getPlan(), piece.id, null), onSaved: () => { layout = null; draw(); } });
      const note = document.createElement('p'); note.textContent = 'Drag the move handle or use the arrow keys (one foot).'; host.append(note);
      for (const [axis, text] of ['Move east (ft)', 'Move north (ft)'].entries()) {
        const label = document.createElement('label'); label.textContent = text;
        const input = document.createElement('input'); input.type = 'number'; input.step = 'any'; input.value = '0';
        input.disabled = !canEdit(); input.setAttribute('aria-label', text); label.append(input); host.append(label);
        input.addEventListener('change', () => {
          if (!canEdit() || !input.value.trim()) return;
          const amount = Number(input.value);
          if (!Number.isFinite(amount)) { report(new Error('Use a finite number of feet.')); return; }
          queue(() => canEdit() && op({ op: 'move_site_item', list: kind, index: record.index, by: axis ? [0, amount] : [amount, 0] })).catch(report);
        });
      }
    }
    const form = document.createElement('form'); form.addEventListener('submit', event => event.preventDefault()); host.append(form);
    const more = document.createElement('details'), summary = document.createElement('summary'); summary.textContent = 'More'; more.append(summary);
    const cardFields = (kind === 'roof' && roof && !piece.rect ? []
      : fields[kind === 'dormer' && piece.rect ? 'roof' : kind] || []).flatMap(field => field !== 'ends' ? [field]
      : ['gable', 'hip'].includes(piece.kind) ? [`ends.${piece.ridge}0`, `ends.${piece.ridge}1`] : []);
    for (const field of cardFields.filter(field => !(kind === 'roof' && isSupported(roof || piece) && field === 'plate'))) {
      const end = field.startsWith('ends.') ? field.slice(5) : null;
      const label = document.createElement('label'); label.textContent = kind === 'room' && field === 'kind' ? 'Type' : end ? endNames[end]
        : field === 'base' && kind === 'building' ? 'Fixed base above lot datum'
          : hosted(kind) && hostedLabels[field] || getFieldLabels()[field] || labels[field] || field[0].toUpperCase() + field.slice(1);
      let input;
      const choices = field === 'kind' ? (kind === 'room' ? ['room', 'porch'] : ['roof', 'dormer'].includes(kind) ? ['hip', 'gable', 'shed', 'flat'] : ['window', 'door', 'slider', 'bifold', 'passage', 'garage'])
        : end ? ['gable', 'hip', 'clip'] : field === 'ridge' ? ['x', 'y'] : field === 'low_side' ? ['x0', 'x1', 'y0', 'y1'] : null;
      if (choices) {
        input = document.createElement('select');
        choices.forEach(value => {
          const option = document.createElement('option'); option.value = value;
          option.textContent = ({ room: 'Room', porch: 'Porch', x: 'Left to right', y: 'Front to back', x0: 'Left', x1: 'Right', y0: 'Front', y1: 'Back',
            hip: 'Hip', gable: 'Gable', clip: 'Clipped gable', shed: 'One slope', flat: 'Flat', window: 'Window', door: 'Door', slider: 'Sliding door',
            bifold: 'Folding door', passage: 'Open passage', garage: 'Garage door' })[value];
          input.append(option);
        });
      } else { input = document.createElement('input'); input.type = field === 'exterior' ? 'checkbox' : 'text'; }
      const initial = fieldValue(piece, field);
      if (kind === 'room' && field === 'kind') input.setAttribute('aria-label', 'Type');
      input.value = display(field, initial, hosted(kind) && kind);
      if (field === 'exterior') input.checked = !!initial;
      input.disabled = !canEdit() || field === 'length' && !piece.joints?.[1];
      const state = { input, baseline: raw(input), queued: 0, lastQueued: undefined };
      inputs.set(field, state);
      const save = () => {
        if (!canEdit()) return;
        const typed = raw(input);
        if (typed === (state.queued ? state.lastQueued : state.baseline)) return;
        try {
          let value = field === 'exterior' ? input.checked : lengths.has(field) ? parseLength(input.value)
            : field === 'position' ? input.value.split(',').map(parseLength)
              : ['pitch', 'rotation', 'panels', 'scale'].includes(field) ? Number(input.value.replace(/[°%]/g, '')) : input.value;
          if (['pitch', 'rotation', 'panels', 'scale'].includes(field) && (!input.value.trim() || !Number.isFinite(value)))
            throw new Error('Use a finite number.');
          if (field === 'scale') value /= 100;
          if (field === 'panels' && (!Number.isInteger(value) || value < 1)) throw new Error('Use a whole number of panels, at least 1.');
          if (field === 'position' && value.length !== 2) throw new Error('Use two distances, separated by a comma.');
          if (field === 'length' && (!(value > 0) || !piece.joints?.[1])) throw new Error('Use a positive length for a wall with two ends.');
          ++state.queued; state.lastQueued = typed;
          pending = pending.then(async () => {
            const current = findPiece(getPlan(), piece.id, building.id)?.piece;
            const savedField = end ? 'ends' : field;
            const savedValue = end ? { ...current?.ends, [end]: value } : value;
            if (current && field === 'length') {
              const d = current.to.map((v, i) => v - current.from[i]), length = Math.hypot(...d);
              if (!(length > 0)) throw new Error('The wall needs two different ends.');
              if (Math.abs(length - value) > 1e-8) await op({ op: 'move_joint', building: building.id, joint: current.joints[1],
                to: current.from.map((v, i) => v + d[i] * value / length) });
            } else if (current && kind === 'room' && field === 'kind') {
              if ((current.kind || 'room') !== value)
                await op({ op: 'set_room_kind', building: building.id, room: piece.id, kind: value });
            } else if (current && hosted(kind)) {
              if (JSON.stringify(current[field] ?? (field === 'scale' ? 1 : 0)) !== JSON.stringify(value))
                await op(field === 'offset' ? { op: 'move_hosted', building: building.id, id: piece.id, offset: value }
                  : { op: 'set', building: building.id, id: piece.id, field, value });
            } else if (current && JSON.stringify(current[savedField]) !== JSON.stringify(savedValue))
              await edit({ op: 'set', building: building.id, piece: piece.id, field: savedField, value: savedValue });
            state.baseline = typed;
          }).catch(report).finally(() => {
            --state.queued;
            if (selection?.pieceId === piece.id && selection?.buildingId === building.id) draw();
          });
        } catch (error) { report(error); }
      };
      input.addEventListener('change', save);
      input.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); save(); } });
      label.append(input);
      if (field === 'floor_offset_ft') for (const [text, delta] of [['Down 0.5 ft', -.5], ['Up 0.5 ft', .5]]) {
        const nudge = button(text, () => queue(async () => {
          if (!canEdit()) return;
          const current = findPiece(getPlan(), piece.id, building.id)?.piece;
          if (current) await op({ op: 'set', building: building.id, id: piece.id, field,
            value: (current.floor_offset_ft || 0) + delta });
          draw();
        }));
        nudge.type = 'button'; label.append(nudge);
      }
      if (field === 'pitch' || hosted(kind) && units[field]) { const unit = document.createElement('span'); unit.textContent = units[field]; label.append(unit); }
      (['ridge', 'low_side'].includes(field) ? more : form).append(label);
    }
    if (more.children.length > 1) form.append(more);
    if (haLink && ['room', 'yard_rooms', 'building', 'anchor'].includes(kind) && !['meter','electric_panel','charger','parking'].includes(piece.kind)) {
      haSection = document.createElement('section'); host.append(haSection); drawHaSection(record);
    }
    host.append(button('Ask Argyle about this', () => ask(selection)));
    if (piece.state === 'ghost' || flags.length) {
      acceptButton = button('Looks right', async () => { await pending; await edit({ op: 'accept', building: building.id, pieces: [piece.id] }); draw(); });
      host.append(acceptButton);
    }
    const actions = document.createElement('div'); actions.className = 'editor-material-actions editor-card-row';
    const moveTo = selectionStore && drawMoveToButton(actions, { ...materialOptions(members), getRefs: () => members });
    if (moveTo) { actions.append(button('Delete', remove)); host.append(actions); }
    else host.append(button('Delete', remove));
  }
  async function remove() {
    const setRemoval = removeSelection?.();
    if (setRemoval) return setRemoval;
    const record = selection && findPiece(getPlan(), selection.pieceId, selection.buildingId);
    if (!record) return;
    const { kind, piece, building } = record;
      if (!canEdit()) return;
      const count = kind === 'yard_rooms' ? (getPlan().site?.devices || []).filter(d => d.host?.yard_room === piece.id).length : 0;
      const askTitle = kind === 'porch_post' ? 'Delete this post?' : `Delete ${getLabel(selection)}?`;
      const askBody = kind === 'yard_rooms'
        ? `${count} device${count === 1 ? '' : 's'} will be unplaced and remain in Home Assistant. Undo restores the room and its placements.`
        : kind === 'porch_post' ? 'Undo restores the post.'
          : 'Attached doors or windows may also be removed. The timeline keeps the earlier house.';
      const deleted = selection;
      if (!await window.promptConfirm(askTitle, askBody, 'Delete', 'Cancel')) return;
      await pending;
      const operation = deleteOperation(getPlan(), deleted, getModel?.());
      await (operation.piece || !op ? edit : op)(operation);
      select(kind === 'porch_post' ? { pieceId: record.porchId, buildingId: building.id, fallbackFrom: [deleted] } : null);

  }
  function drawEdge(next, record, roof) {
    const edge = roof.edges[edgeIndex];
    if (!edge) { edgeIndex = null; layout = null; draw(next); return; }
    const signature = `edge:${edgeIndex}:${JSON.stringify([roof.edges, roof.area, record.building.roof?.sections])}:${canEdit()}`;
    const active = document.activeElement;
    if (selection?.pieceId === next.pieceId && selection?.buildingId === next.buildingId && canEdit()
      && host.contains?.(active) && active?.matches?.('input') && active.dataset.edgeBaseline !== undefined
      && String(active.value) !== active.dataset.edgeBaseline) return;
    selection = next; host.hidden = false;
    dock?.properties.render(host, { crumbs: [...propertyPath(record, getSelection(), select).crumbs, `Edge ${edgeIndex + 1}`], reveal: layout !== signature,
      back: () => { edgeIndex = null; layout = null; draw(); } });
    if (layout === signature && edgePlan === getPlan()) return;
    edgePlan = getPlan(); layout = signature; disposeSlots(); host.replaceChildren(); inputs = new Map();
    const heading = document.createElement('h3'); heading.textContent = `Roof edge ${edgeIndex + 1}`;
    host.append(heading, button('Back to roof', () => { edgeIndex = null; layout = null; draw(); }));
    const index = edgeIndex, building = record.building.id;
    const save = change => {
      if (!canEdit()) return;
      pending = pending.then(async () => {
        if (!canEdit()) return;
        const planNow = getPlan();
        const resolved = typeof change === 'function' ? change(planNow) : change;
        if (!resolved) return;
        const current = planNow.buildings.find(b => b.id === building)?.roofs.find(r => r.id === roof.id);
        const operation = fields => edgeOperation(building, roof.id, index, fields);
        if (current?.edges?.[index]?.gutter && ['gable', 'clip'].includes(resolved.setting)) {
          if (!await window.promptConfirm('Remove this gutter?', "Changing this edge removes its gutter and its downspout overrides.", 'Remove and change', 'Cancel')) return;
          if (!canEdit()) return;
          return op({ op: 'batch', ops: [operation({ gutter: false, downspouts: null }), operation(resolved)] });
        }
        // Pitch-only writes still include the current setting for the op contract.
        return op(operation('pitch' in resolved ? { setting: current?.edges?.[index]?.setting || edge.setting, ...resolved } : resolved));
      }).catch(report).finally(() => { layout = null; draw(); });
      return pending;
    };
    for (const [setting, label] of [['sloped', 'Sloped'], ['gable', 'Gable'], ['clip', 'Clipped']]) {
      const choice = button(label, () => save({ setting }));
      choice.setAttribute('aria-pressed', String(edge.setting === setting)); host.append(choice);
    }
    if (eaveEdges(record.building, roof).includes(index)) gutterToggle(!!edge.gutter, gutter => save({ gutter }));
    if (edge.gutter) {
      const snapshot = gutterSnapshot(getPlan());
      const runs = snapshot.runs.filter(r => r.building === building && r.segments.some(s => s.roof === roof.id && s.edge === index));
      for (const run of runs) {
        const note = document.createElement('p'); note.textContent = gutterLocation(getPlan(), building, { roof: roof.id, edge: index }); note.dataset.gutterRun = run.id; host.append(note);
      }
      const values = downspoutValues(getPlan(), building, roof.id, index, snapshot);
      const add = button('Add downspout', () => save(planNow => {
        const next = addDownspout(planNow, building, roof.id, index);
        return next ? { downspouts: next } : null;
      }));
      const next = addDownspout(getPlan(), building, roof.id, index, snapshot);
      add.disabled = !canEdit() || !next;
      if (!next) add.title = values.length >= 8 ? 'At most 8 downspouts per edge.' : 'No open space at least 1 ft from existing downspouts on this edge.';
      host.append(add, button('Reset to automatic', () => save({ downspouts: null })));
      // Numeric hand path also exposes overrides that placement has merged.
      const drawnLength = values.length;
      values.forEach((entry, i) => {
        const fraction = entryFraction(entry), exact = isExact(entry);
        const captured = exact ? { at: entry.at } : entry;
        const resolveRow = next => next.length === drawnLength ? (i < next.length ? i : -1)
          : next.findIndex(v => sameDownspoutEntry(v, captured));
        const row = document.createElement('div');
        row.className = 'editor-downspout-row';
        row.dataset.downspoutRow = String(i);
        row.dataset.downspoutKind = exact ? 'exact' : 'corner';
        if (i === values.length - 1) row.dataset.downspoutLast = '';
        const label = document.createElement('label'); label.textContent = `Downspout ${i + 1} fraction`;
        const input = document.createElement('input'); input.type = 'number'; input.min = '0'; input.max = '1'; input.step = 'any';
        input.value = fraction; input.dataset.edgeBaseline = String(fraction); input.disabled = !canEdit(); input.setAttribute('aria-label', label.textContent);
        input.addEventListener('change', () => {
          const value = Number(input.value);
          if (!input.value.trim() || !Number.isFinite(value) || value < 0 || value > 1) { report(new Error('Choose a fraction from 0 to 1.')); return; }
          input.dataset.edgeBaseline = String(input.value);
          save(planNow => {
            const next = downspoutValues(planNow, building, roof.id, index);
            const idx = resolveRow(next);
            if (idx < 0) return null;
            next[idx] = isExact(next[idx]) ? { at: roundAt(value) } : value;
            return { downspouts: next };
          });
        });
        label.append(input); row.append(label);
        if (exact) {
          const placedNote = document.createElement('p');
          placedNote.className = 'editor-downspout-note';
          placedNote.textContent = 'Placed by hand';
          row.append(placedNote);
        }
        const actions = document.createElement('div');
        actions.className = 'editor-material-actions editor-card-row';
        const snapTarget = exact ? nearestFreeCandidate(getPlan(), building, roof.id, index, fraction, i, snapshot) : null;
        const merged = !exact && isMergedEntry(getPlan(), building, roof.id, index, i, entry, snapshot);
        const convert = exact
          ? button('Snap to a corner', () => save(planNow => {
            const next = downspoutValues(planNow, building, roof.id, index);
            const idx = resolveRow(next);
            if (idx < 0) return null;
            const target = nearestFreeCandidate(planNow, building, roof.id, index, entryFraction(next[idx]), idx);
            if (target === null) return null;
            next[idx] = target;
            return { downspouts: next };
          }))
          : button('Keep exactly here', () => save(planNow => {
            const next = downspoutValues(planNow, building, roof.id, index);
            const idx = resolveRow(next);
            if (idx < 0 || isMergedEntry(planNow, building, roof.id, index, idx, next[idx])) return null;
            next[idx] = { at: roundAt(placedFraction(planNow, building, roof.id, index, idx, next[idx])) };
            return { downspouts: next };
          }));
        convert.setAttribute('aria-label', `${exact ? 'Snap to a corner' : 'Keep exactly here'} for downspout ${i + 1}`);
        if (exact) {
          convert.disabled = !canEdit() || snapTarget === null;
          if (snapTarget === null) convert.title = 'No free corner on this edge.';
        } else if (merged) {
          convert.disabled = true;
          convert.title = 'This downspout shares an outlet with another one.';
        }
        const removeBtn = button(`Remove downspout ${i + 1}`, () => save(planNow => {
          const next = downspoutValues(planNow, building, roof.id, index);
          const idx = resolveRow(next);
          if (idx < 0) return null;
          next.splice(idx, 1);
          return { downspouts: next };
        }));
        removeBtn.setAttribute('aria-label', `Remove downspout ${i + 1}`);
        actions.append(convert, removeBtn);
        row.append(actions); host.append(row);
      });
    }
    const label = document.createElement('label'); label.textContent = 'Pitch';
    const input = document.createElement('input'); input.type = 'number'; input.min = '0'; input.max = '24'; input.step = 'any';
    input.setAttribute('aria-label', 'Pitch'); input.value = edge.pitch ?? roof.pitch ?? 6; input.dataset.edgeBaseline = String(input.value); input.disabled = !canEdit();
    let baseline = String(input.value);
    const savePitch = () => {
      if (String(input.value) === baseline) return;
      const pitch = Number(input.value);
      if (!input.value.trim() || !Number.isFinite(pitch) || pitch < 0 || pitch > 24) {
        report(new Error('Choose a pitch from 0 to 24 in 12.')); return;
      }
      baseline = String(input.value); input.dataset.edgeBaseline = baseline; save({ pitch });
    };
    input.addEventListener('change', savePitch);
    input.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); savePitch(); } });
    label.append(input); const unit = document.createElement('span'); unit.textContent = 'in 12'; label.append(unit); host.append(label);
  }
  function button(text, action) {
    const node = document.createElement('button'); node.type = 'button'; node.textContent = text;
    node.disabled = !canEdit();
    node.addEventListener('click', () => Promise.resolve().then(action).catch(report)); return node;
  }
  function gutterToggle(value, save) {
    const label = document.createElement('label'); label.textContent = 'Gutter';
    const input = document.createElement('input'); input.type = 'checkbox'; input.checked = value;
    input.disabled = !canEdit(); input.setAttribute('aria-label', 'Gutter');
    input.addEventListener('change', () => { if (canEdit()) Promise.resolve(save(input.checked)).catch(report); });
    label.append(input); host.append(label);
  }
  function kindIsEquipment(record) { return record.kind === 'anchor' && ['charger', 'parking'].includes(record.piece.kind); }
  // A change from outside the fields (the area pick, Use, a device placement)
  // waits behind any field save still running, as Delete does, rather than
  // being refused while the house finishes that save.
  function queue(work) {
    const run = pending.then(() => work());
    pending = run.catch(() => {});
    return run;
  }
  return { draw, queue, remove, loadNames, dispose: disposeSlots, showRoofEdge(handle) {
    const next = { pieceId: handle.id, buildingId: handle.building };
    selection = next; edgeIndex = handle.edge; layout = null; draw(next);
  } };
}

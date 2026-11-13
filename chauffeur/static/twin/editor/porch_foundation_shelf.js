import { porchFoundation, porchOnGrade } from '../twin_porch_foundation.js';
import { materialSlot } from './material_slot.js';

export function porchShelfOnGrade(plan, building, room) {
  const detail = [...(building.porches || []), ...(building.porches_detail || []), building.porch].find(p => p?.id === room.id);
  const level = building.levels.find(l => l.id === room.level);
  return porchOnGrade(plan, building, room, (detail?.floor ?? level?.elevation ?? 0) + (room.floor_offset_ft || 0));
}

// Labels/fields and save queue follow foundation_shelf; finishes use the shared slot.
export function porchFoundationShelf(host, room, building, { getPlan, getKit = () => ({}), canEdit, queue, op, report, onSaved }) {
  const value = porchFoundation(room.foundation), section = document.createElement('section'); host.append(section);
  const controls = new Map(), rows = new Map(), slots = new Map();
  const save = (key, changed, material = false) => queue(async () => {
    if (!canEdit()) return;
    const current = getPlan().buildings.find(b => b.id === building.id)?.rooms.find(r => r.id === room.id);
    if (!current) throw new Error('That porch is missing.');
    const foundation = porchFoundation(current.foundation);
    const before = material ? foundation.materials[key] : foundation[key];
    if (JSON.stringify(before) === JSON.stringify(changed)) return;
    if (material) foundation.materials[key] = changed; else foundation[key] = changed;
    // Canonical writes discard the legacy enum once it has been read.
    delete foundation.material;
    await op({ op: 'set_porch_foundation', building: building.id, id: room.id, foundation });
    onSaved();
  });
  const visibility = () => {
    const type = controls.get('type').value;
    for (const key of ['post_in', 'post_shape', 'spacing_ft']) rows.get(key).hidden = type === 'solid';
    rows.get('skirt').hidden = type !== 'enclosed';
    for (const [key, node] of slots) node.hidden = key === 'solid' ? type !== 'solid' : key === 'skirt' ? type !== 'enclosed' : type === 'solid';
  };
  for (const [key, title, options, range] of [
    ['type', 'Foundation', ['posts', 'enclosed', 'solid']],
    ['post_in', 'Post width (in)', null, [4, 16, .5]],
    ['post_shape', 'Post shape', ['square', 'round']],
    ['spacing_ft', 'Post spacing (ft)', null, [4, 12, .5]],
    ['skirt', 'Skirt', ['lattice', 'panel']],
    ['lip_in', 'Floor overhang (in)', null, [0, 4, .25]]]) {
    const label = document.createElement('label'); label.textContent = title;
    const input = document.createElement(options ? 'select' : 'input');
    if (options) for (const choice of options) {
      const option = document.createElement('option'); option.value = choice; option.textContent = choice[0].toUpperCase() + choice.slice(1); input.append(option);
    } else { input.type = 'number'; [input.min, input.max, input.step] = range.map(String); }
    input.value = String(value[key]); input.setAttribute('aria-label', title); input.disabled = !canEdit();
    controls.set(key, input); rows.set(key, label); label.append(input); section.append(label);
    input.addEventListener('change', () => {
      visibility(); if (!canEdit()) return;
      if (!options && (!input.value.trim() || !Number.isFinite(Number(input.value)) || Number(input.value) < range[0] || Number(input.value) > range[1])) {
        report(new Error(`Choose ${title.toLowerCase()} from ${range[0]} to ${range[1]}.`)); return;
      }
      save(key, options ? input.value : Number(input.value)).catch(report);
    });
  }
  const drawSkirt = () => {
    const lattice = controls.get('skirt').value === 'lattice';
    slots.get('skirt')?.remove();
    addSlot('skirt', 'Skirt', lattice ? 'trim' : 'siding'); visibility();
  };
  function addSlot(key, label, role) {
    const ref = getKit().materials?.[role];
    const node = materialSlot({ label, value: value.materials[key], defaultLabel: role === 'base' ? 'Stone' : role[0].toUpperCase() + role.slice(1),
      defaultColor: ref?.color, kit: getKit(), readOnly: () => !canEdit(), onChange: changed => save(key, changed, true), report });
    section.append(node); slots.set(key, node);
  }
  addSlot('posts', 'Posts and beam', 'trim'); addSlot('skirt', 'Skirt', value.skirt === 'panel' ? 'siding' : 'trim'); addSlot('solid', 'Solid base', 'base');
  controls.get('skirt').addEventListener('change', drawSkirt);
  if (porchShelfOnGrade(getPlan(), building, room)) {
    const note = document.createElement('p'); note.textContent = 'Slab on grade: the floor is within 9 inches of the ground at every corner, so there is no room for posts.'; section.append(note);
  }
  visibility();
}

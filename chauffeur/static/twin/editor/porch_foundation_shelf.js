// Reuse the building foundation shelf's plain labels and card save queue.
export function porchFoundationShelf(host, room, building, { getPlan, canEdit, queue, op, report, onSaved }) {
  const value = { type: 'posts', material: 'stone', lip_in: 1, ...room.foundation };
  const section = document.createElement('section'); host.append(section);
  const controls = new Map(), rows = new Map();
  const visibility = () => { for (const key of ['material', 'lip_in']) rows.get(key).hidden = controls.get('type').value !== 'solid'; };
  for (const [key, title, options] of [['type', 'Foundation', ['posts', 'solid']],
    ['material', 'Foundation material', ['stone', 'brick', 'concrete']], ['lip_in', 'Floor overhang (in)', null]]) {
    const label = document.createElement('label'); label.textContent = title;
    const input = document.createElement(options ? 'select' : 'input');
    if (options) for (const choice of options) {
      const option = document.createElement('option'); option.value = choice; option.textContent = choice[0].toUpperCase() + choice.slice(1); input.append(option);
    } else { input.type = 'number'; input.min = '0'; input.max = '4'; input.step = '.25'; }
    input.value = String(value[key]); input.setAttribute('aria-label', title); input.disabled = !canEdit();
    controls.set(key, input); rows.set(key, label); label.append(input); section.append(label);
    input.addEventListener('change', () => {
      visibility(); if (!canEdit()) return;
      const lip = controls.get('lip_in').value;
      if (key === 'lip_in' && (!lip.trim() || !Number.isFinite(Number(lip)) || Number(lip) < 0 || Number(lip) > 4)) {
        report(new Error('Choose a porch foundation lip from 0 to 4 inches.')); return;
      }
      const changed = key === 'lip_in' ? Number(input.value) : input.value;
      queue(async () => {
        if (!canEdit()) return;
        const current = getPlan().buildings.find(b => b.id === building.id)?.rooms.find(r => r.id === room.id);
        if (!current) throw new Error('That porch is missing.');
        if ((current.foundation?.[key] ?? value[key]) === changed) return;
        await op({ op: 'set_porch_foundation', building: building.id, id: room.id,
          foundation: { ...value, ...current.foundation, [key]: changed } });
        onSaved();
      }).catch(report);
    });
  }
  visibility();
}

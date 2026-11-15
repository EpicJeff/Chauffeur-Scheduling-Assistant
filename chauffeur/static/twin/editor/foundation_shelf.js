import { materialSlot } from './material_slot.js';

// Same labels/fields and card queue as the equipment property shelf.
export function foundationShelf(host, building, { getPlan, getKit = () => ({}), canEdit, queue, op, report, preview }) {
  const section = document.createElement('section'), heading = document.createElement('h4'); heading.textContent = 'Foundation'; section.append(heading); host.append(section);
  const value = { mode: 'fixed', offset_ft: 0, thickness_ft: 1, ...building.foundation };
  const inputs = new Map(); let timer = null;
  const current = () => structuredClone(getPlan().buildings.find(b => b.id === building.id)?.foundation || value);
  const read = () => ({ ...current(), ...Object.fromEntries([...inputs].map(([key, input]) => [key, key === 'mode' ? input.value : Number(input.value)])) });
  const valid = () => [...inputs].every(([key, input]) => key === 'mode' || input.value.trim() && Number.isFinite(Number(input.value)) && Number(input.value) >= (key === 'thickness_ft' ? 0 : -50) && Number(input.value) <= 50);
  for (const [key, title] of [['mode', 'Foundation mode'], ['offset_ft', 'Offset (ft)'], ['thickness_ft', 'Thickness (ft)']]) {
    const label = document.createElement('label'); label.textContent = title;
    const input = document.createElement(key === 'mode' ? 'select' : 'input');
    if (key === 'mode') for (const mode of ['fixed', 'auto']) {
      const option = document.createElement('option'); option.value = mode; option.textContent = mode === 'auto' ? 'Auto' : 'Fixed'; input.append(option);
    } else { input.type = 'number'; input.step = '.5'; input.min = key === 'thickness_ft' ? '0' : '-50'; input.max = '50'; }
    input.value = String(value[key]); input.setAttribute('aria-label', title); input.disabled = !canEdit(); inputs.set(key, input);
    input.addEventListener('input', () => {
      clearTimeout(timer);
      if (valid() && canEdit() && preview) timer = setTimeout(() => {
        if (!section.isConnected || !canEdit()) return;
        const plan = structuredClone(getPlan()), b = plan.buildings.find(b => b.id === building.id);
        b.foundation = read(); preview(plan).catch(report);
      }, 180);
    });
    input.addEventListener('change', () => {
      clearTimeout(timer); if (!canEdit()) return;
      if (!valid()) { report(new Error('Use an offset from -50 to 50 feet and thickness from 0 to 50 feet.')); return; }
      const fields = Object.fromEntries([...inputs].map(([key, input]) => [key, key === 'mode' ? input.value : Number(input.value)]));
      queue(() => {
        if (!canEdit()) return;
        return op({ op: 'set_foundation', building: building.id, foundation: { ...current(), ...fields } });
      }).catch(error => {
        report(error); preview?.(getPlan()).catch(report);
      });
    });
    label.append(input); section.append(label);
  }
  section.append(materialSlot({ label: 'Slab', value: value.materials?.slab, defaultLabel: 'Concrete',
    defaultColor: getKit().materials?.patio_concrete?.color, kit: getKit(), readOnly: () => !canEdit(), report,
    onChange: changed => queue(async () => {
      if (!canEdit()) return;
      const foundation = current();
      if (JSON.stringify(foundation.materials?.slab || null) === JSON.stringify(changed)) return;
      if (changed) foundation.materials = { ...foundation.materials, slab: changed };
      else {
        delete foundation.materials?.slab;
        if (foundation.materials && !Object.keys(foundation.materials).length) delete foundation.materials;
      }
      await op({ op: 'set_foundation', building: building.id, foundation });
    }) }));
  const note = document.createElement('p'); note.textContent = 'Auto follows the highest ground under the footprint plus offset. Fixed uses the saved base. Thickness is the minimum slab depth.'; section.append(note);
}

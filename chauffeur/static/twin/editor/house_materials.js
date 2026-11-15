import { KINDS, PANEL_ROLES } from '../surface_kinds.js';
import { materialSlot } from './material_slot.js';

// A building's selection card uses the same sections and shared slot control
// as foundationShelf; material editing remains on the Library page.
export function houseMaterialsShelf(host, building, { getPlan, getKit = () => ({}), canEdit, op, report }) {
  const section = document.createElement('section'), title = document.createElement('h4');
  title.textContent = 'House materials'; section.append(title); host.append(section);
  const editable = () => typeof canEdit === 'function' ? canEdit() : !!canEdit;
  const labels = { siding: 'Siding', interior_wall: 'Interior walls', floor: 'Floors', porch_ceiling: 'Porch ceiling' };
  const rows = [...PANEL_ROLES.map(kind => ({ kind, label: labels[kind], scope: 'building', fallback: { role: kind } })), ...KINDS];
  const groups = [
    ['Walls and floors', [...PANEL_ROLES, 'base']],
    ['Trim', ['trim', 'fascia']],
    ['Openings', ['casing', 'window_frame', 'pane', 'door']],
    ['Porch and stairs', ['column', 'screen', 'stair_tread', 'stair_rail']],
    ['Roof and ceilings', ['soffit', 'ceiling', 'roof']],
    ['Fixtures', ['cabinet', 'counter', 'shower_tile', 'shower_glass']],
    ['Yard', ['lawn', 'water']],
  ];
  const kit = getKit();
  for (const [label, kinds] of groups) {
    const group = document.createElement('section'), heading = document.createElement('h4');
    heading.textContent = label; group.append(heading); section.append(group);
    for (const row of rows.filter(r => kinds.includes(r.kind))) {
      const { kind, fallback } = row, site = row.scope === 'site';
      const value = (site ? getPlan().materials : building.materials)?.[kind];
      const parent = rows.find(r => r.kind === fallback.role)?.label || labels[fallback.role];
      const defaultLabel = fallback.builtin ? `Built-in ${fallback.builtin}`
        : fallback.role && fallback.role !== kind ? `Follows ${parent}` : 'House look';
      group.append(materialSlot({ label: row.label, value, defaultLabel, defaultColor: kit.materials?.[fallback.role || kind]?.color,
        kit, readOnly: () => !editable(), report,
        onChange: slot => {
          if (!editable()) return;
          return op({ op: 'set_material', building: building.id,
            target: site ? { site: true, role: kind } : { building: building.id, role: kind }, material: slot });
        } }));
    }
  }
}

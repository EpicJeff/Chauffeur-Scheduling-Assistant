import { KINDS, PANEL_ROLES } from '../surface_kinds.js';
import { materialSlot } from './material_slot.js';
import { request } from './api.js';
import { surfaceDescription } from './material_catalog.js';
import { resolveSurfaceMaterial } from '../surface_material.js';

export const YARD_ROLES = [
  ['paving', 'Paving'], ['mulch', 'Mulch'], ['patio_concrete', 'Patio concrete'], ['fence', 'Fence'],
  ['pool_interior', 'Pool interior'], ['pool_waterline', 'Pool waterline'], ['pool_coping', 'Pool coping'],
].map(([kind, label]) => ({ kind, label, scope:'site', fallback:{role:kind} }));

function grassChoice(host, { editable, ownSlot, report, settingsRequest }) {
  const row = document.createElement('label'), select = document.createElement('select');
  row.textContent = 'Lawn grass type'; select.name = 'lawn_grass_type'; select.setAttribute('name', 'lawn_grass_type');
  for (const [value, text] of [['cool', 'Cool-season (fescue, bluegrass, rye)'],
    ['warm', 'Warm-season (Bermuda, zoysia, St. Augustine)']]) {
    const option = document.createElement('option'); option.value = value; option.textContent = text; select.append(option);
  }
  const status = document.createElement('p'); status.setAttribute('role', 'status');
  row.append(select); host.append(row, status);
  let disposed = false, ready = false, busy = false, saved = 'cool';
  const events = new AbortController();
  const controls = () => { select.disabled = disposed || !ready || busy || !editable(); };
  ownSlot?.({ dispose() { disposed = true; events.abort(); controls(); } });
  controls();
  settingsRequest('weather-state', 'GET', undefined, 'twin').then(body => {
    if (disposed) return;
    saved = body.lawn?.grass_type === 'warm' ? 'warm' : 'cool'; select.value = saved; ready = true; controls();
  }).catch(error => { if (!disposed) { status.textContent = 'Could not load lawn grass type.'; report?.(error); } });
  select.addEventListener('change', async () => {
    if (disposed || !ready || busy || !editable()) return;
    busy = true; controls(); status.textContent = 'Saving…';
    try {
      await settingsRequest('weather-sources', 'PUT', { lawn_grass_type: select.value }, 'twin');
      if (disposed) return;
      saved = select.value; status.textContent = 'Saved';
    } catch (error) {
      if (!disposed) { select.value = saved; status.textContent = 'Could not save lawn grass type.'; report?.(error); }
    } finally { busy = false; controls(); }
  }, { signal: events.signal });
}

// A building's selection card uses the same sections and shared slot control
// as foundationShelf; material editing remains on the Library page.
export function houseMaterialsShelf(host, building, { getPlan, getKit = () => ({}), library, ownSlot, canEdit, op, report, settingsRequest = request }) {
  const section = document.createElement('section'), title = document.createElement('h4');
  title.textContent = 'House materials'; section.append(title); host.append(section);
  const editable = () => typeof canEdit === 'function' ? canEdit() : !!canEdit;
  const labels = { siding: 'Siding', interior_wall: 'Interior walls', floor: 'Floors', porch_ceiling: 'Porch ceiling' };
  const rows = [...PANEL_ROLES.map(kind => ({ kind, label: labels[kind], scope: 'building', fallback: { role: kind } })), ...KINDS, ...YARD_ROLES];
  const groups = [
    ['Walls and floors', [...PANEL_ROLES, 'base']],
    ['Trim', ['trim', 'fascia']],
    ['Openings', ['casing', 'window_frame', 'pane', 'door', 'garage_door']],
    ['Porch and stairs', ['column', 'screen', 'stair_tread', 'stair_rail']],
    ['Roof and ceilings', ['soffit', 'ceiling', 'roof']],
    ['Fixtures', ['cabinet', 'counter', 'shower_tile', 'shower_glass']],
    ['Yard', ['lawn', 'water', ...YARD_ROLES.map(row => row.kind)]],
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
      group.append(materialSlot({ library, ownSlot, label: row.label, value, defaultLabel, defaultColor: kit.materials?.[fallback.role || kind]?.color,
        kit, readOnly: () => !editable(), report,
        resolve: ref => {
          const plan = getPlan(), current = plan.buildings?.find(b => b.id === building.id) || building;
          // The dialog edits this very role: clearing it must skip its saved value.
          const owner = site ? null : {...current, materials:{...current.materials, [kind]:null}};
          const parentPlan = site ? {...plan, materials:{...plan.materials, [kind]:null}} : plan;
          const parentRole = kind === 'pool_coping' ? 'paving' : fallback.role;
          return surfaceDescription(parentPlan, {role:kind, ref, building:owner,
            fallback:parentRole && parentRole !== kind ? resolveSurfaceMaterial(plan, {role:parentRole, building:site ? null : current, kit}) : null,
            defaultRef:{id:fallback.builtin || fallback.look || kind} }, kit);
        },
        onChange: slot => {
          if (!editable()) return;
          return op({ op: 'set_material', building: building.id,
            target: site ? { site: true, role: kind } : { building: building.id, role: kind }, material: slot });
        } }));
      if (kind === 'lawn') grassChoice(group, { editable, ownSlot, report, settingsRequest });
    }
  }
}

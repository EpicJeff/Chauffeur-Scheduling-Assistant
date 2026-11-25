import { SUPPORT_KINDS, isSupported, supportPoints, roofPoint } from '../roof_supports.js';
import { parseLength } from './selection_fields.js';
import { SUPPORT_STYLES, normalizeRoofBox, roofEndLabels } from '../roof_box_contract.js';

const sizes = { bracket: .3, corbel: .5, brace: .45, cable: .08, post: .5 };
const precise = value => `${Number(value.toFixed(10))} ft`;

// Same geometric choices as the operation: one facing edge per settled wall.
export function roofHostChoices(roof, building) {
  const area = roof.area, sign = area.reduce((n, p, i) => { const q = area[(i+1)%area.length]; return n+p[0]*q[1]-p[1]*q[0]; }, 0) > 0 ? 1 : -1;
  const joints = new Map((building.joints || []).map(j => [j.id, j.at]));
  const candidates = (building.walls || []).flatMap((wall, wi) => {
    if (wall.level !== roof.level || wall.state === 'ghost' || wall.kind === 'separator' || wall.exterior === false) return [];
    const a = wall.from || joints.get(wall.joints?.[0]), b = wall.to || joints.get(wall.joints?.[1]);
    if (!a || !b) return [];
    const length = Math.hypot(...b.map((v, i) => v-a[i])); if (!length) return [];
    const tangent = b.map((v, i) => (v-a[i])/length), pairs = [];
    area.forEach((p, edge) => {
      const q0 = area[(edge+1)%area.length], axis = Math.abs(p[0]-q0[0]) < 1e-8 ? 0 : 1;
      const dx = Math.abs(b[0]-a[0]), dy = Math.abs(b[1]-a[1]), tolerance = Math.tan(Math.PI/180);
      const wallAxis = dx <= dy*tolerance+1e-8 ? 0 : dy <= dx*tolerance+1e-8 ? 1 : null;
      if (wallAxis !== axis) return;
      p = roofPoint(roof, p); const q = roofPoint(roof, area[(edge+1)%area.length]);
      const span = Math.hypot(...q.map((v, i) => v-p[i])); if (!span) return;
      const u = q.map((v, i) => (v-p[i])/span), normal = [sign*u[1], -sign*u[0]];
      if (Math.abs(u[0]*tangent[0]+u[1]*tangent[1]) < Math.cos(Math.PI/180)-1e-8) return;
      const distances = [a,b].map(v => v.reduce((n,x,i) => n+(x-p[i])*normal[i],0));
      const along = [a,b].map(v => v.reduce((n,x,i) => n+(x-p[i])*u[i],0));
      if (Math.max(...distances) < -1e-8 || Math.min(span,Math.max(...along))-Math.max(0,Math.min(...along)) <= 1e-8) return;
      pairs.push({ distance: Math.abs((distances[0]+distances[1])/2), edge });
    });
    pairs.sort((a,b) => a.distance-b.distance || a.edge-b.edge);
    return pairs.length ? [{ ...pairs[0], wall: wall.id, label: wall.name || `Wall ${wi+1}` }] : [];
  }).sort((a,b) => a.distance-b.distance || a.wall.localeCompare(b.wall)).slice(0,8);
  if (roof.host && !candidates.some(w => w.wall === roof.host.wall && w.edge === roof.host.edge)) {
    const wall = (building.walls || []).find(w => w.id === roof.host.wall);
    candidates.push({...roof.host, label: wall?.name || 'Current host wall'});
  }
  return candidates;
}

export function roofSupportShelf(host, roof, building, { canEdit, save, move, setPlate, report }) {
  roof = normalizeRoofBox({...roof});
  const field = (text, value, change, { choices, number, check, length, validate } = {}) => {
    const label = document.createElement('label'); label.textContent = text;
    const input = document.createElement(choices ? 'select' : 'input');
    if (choices) for (const [value, text] of choices) {
      const option = document.createElement('option'); option.value = value; option.textContent = text; input.append(option);
    }
    else input.type = check ? 'checkbox' : number ? 'number' : 'text';
    const display = length ? precise(value) : String(value);
    input.value = display; if (check) input.checked = !!value;
    const error = document.createElement('small'); error.setAttribute('role', 'status');
    input.disabled = !!(!canEdit()); input.setAttribute('aria-label', text);
    const fail = e => { error.textContent = e.message; input.setAttribute('aria-invalid','true'); report(Object.assign(e, { shown: true })); };
    input.addEventListener('change', () => {
      if (!canEdit()) return;
      error.textContent = ''; input.setAttribute('aria-invalid','false');
      if (!check && !choices && !input.value.trim()) { input.value = display; return; }
      try {
        const next = check ? !!input.checked : length ? parseLength(input.value) : number ? Number(input.value) : input.value;
        if (validate) validate(next);
        if (next === value || !check && input.value === display) return;
        Promise.resolve(change(next)).catch(fail);
      } catch (e) { fail(e); }
    });
    label.append(input, error); host.append(label); return input;
  };
  const bounded = (lo, hi, text) => value => { if (!Number.isFinite(value) || value < lo || value > hi) throw new Error(`${text} must be from ${lo} to ${hi} ft.`); };
  field('Support kind', roof.support?.kind || 'walls', kind => save({ support: { kind } }),
    { choices: SUPPORT_KINDS.map(kind => [kind, ({ walls: 'Walls', bracket: 'Straight brackets', corbel: 'Corbels', brace: 'Braces', cable: 'Cables', post: 'Posts' })[kind]]) });
  if (isSupported(roof)) {
    const s = roof.support;
    const count = field('Support count', s.count ?? 2, count => save({ support: { count } }), { number: true,
      validate: n => { if (!Number.isInteger(n) || n < 0 || n > 40) throw new Error('Support count must be a whole number from 0 to 40.'); } });
    count.min = '0'; count.max = '40'; count.step = '1';
    for (const [key, label, fallback, lo, hi] of [['inset_ft', 'Support inset', .6, 0, 6], ['size_ft', 'Support size', sizes[s.kind], .05, 3]])
      field(label, s[key] ?? fallback, value => save({ support: { [key]: value } }), { length: true, validate: bounded(lo, hi, label) });
    const styles = SUPPORT_STYLES[s.kind] || [];
    if (styles.length) {
      const known = styles.some(([value]) => value === s.style);
      const choices = s.style && !known ? [['', 'Choose a style'], ...styles] : styles;
      field('Support style', known ? s.style : s.style ? '' : styles[0][0], style => style && save({support:{style}}), {choices});
    }
    const ends = roofEndLabels(roof);
    if (ends.length) {
      const heading=document.createElement('h4');heading.textContent='Ends';host.append(heading);
      const values=ends.map(([i])=>roof.ends?.[i] || 'open'), uniform=values.every(v=>v===values[0])?values[0]:'';
      field('All ends', uniform, value => value && save({ends:Object.fromEntries(ends.map(([i])=>[i,value]))}), {choices:[...(uniform?[]:[['','Mixed']]),['open','Open'],['closed','Closed']]});
      for (const [i,label] of ends) field(label, roof.ends?.[i] || 'open', value=>save({ends:{[i]:value}}), {choices:[['open','Open'],['closed','Closed']]});
    }
    field('Ceiling underneath', roof.underside?.kind === 'flat' ? 'flat' : 'exposed', kind=>save({underside:{kind}}), {choices:[['exposed','None'],['flat','Flat']]});
    if (roof.underside?.kind === 'flat') field('Drop below the roof edge (ft)', roof.underside.drop_ft, drop_ft=>save({underside:{kind:'flat',drop_ft}}), {number:true,validate:bounded(0,3,'Drop')});
    field('Thickness', roof.thickness_ft ?? .25, thickness_ft => save({ thickness_ft }), { length: true, validate: bounded(.05, 2, 'Thickness') });
    field('Fascia', roof.fascia !== false, fascia => save({ fascia }), { check: true });
    field('Host wall', roof.host ? JSON.stringify([roof.host.wall,roof.host.edge]) : '', value => {
      const [wall, edge] = value ? JSON.parse(value) : [];
      return save({ host: value ? { wall, edge } : null });
    }, { choices: [['', 'None'], ...roofHostChoices(roof, building).map(w => [JSON.stringify([w.wall,w.edge]), w.label])] });
    for (const [i, point] of supportPoints(roof).entries()) {
      const shown = point.at.map(precise);
      field(`Support ${i + 1} position (x, y)`, shown.join(', '), text => {
        const parts = text.split(',');
        const at = parts.map((s, k) => s.trim() === shown[k] ? point.at[k] : parseLength(s));
        if (at.length !== 2 || !at.every(Number.isFinite)) throw new Error('Use two distances, separated by a comma.');
        if (at.every((v,k) => v === point.at[k])) return;
        return save({ at: { [i]: at } });
      });
    }
    const reset = document.createElement('button'); reset.type = 'button'; reset.textContent = 'Reset support positions'; reset.disabled = !!(!canEdit());
    reset.addEventListener('click', () => { if (canEdit() && Object.keys(s.at || {}).length) save({ at: {} }).catch(report); }); host.append(reset);
  }
  if (isSupported(roof) || !roof.rect) field('Roof height', roof.plate, setPlate, { length: true,
    validate: value => { if (!Number.isFinite(value) || value <= 0) throw new Error('Roof height must be above zero.'); } });
  for (const [axis, label] of ['Move along building X (ft)', 'Move along building Y (ft)'].entries())
    field(label, 0, value => value && move(axis ? [0, value] : [value, 0]), { number: true,
      validate: value => { if (!Number.isFinite(value)) throw new Error('Use a finite distance.'); } });
}

import { allPorches } from '../twin_generator.js';
import { isSupported, roofPoint } from '../roof_supports.js';
import { roofBounds } from '../twin_roof.js';

// Same strip integration and threshold as twin_model._overlap; the shared
// eligibility case table exercises both languages, including concave outlines.
function overlapArea(a, b) {
  const bounds = p => [Math.min(...p.map(v=>v[0])),Math.min(...p.map(v=>v[1])),Math.max(...p.map(v=>v[0])),Math.max(...p.map(v=>v[1]))];
  const ab=bounds(a), bb=bounds(b), lo=Math.max(ab[0],bb[0]), hi=Math.min(ab[2],bb[2]);
  if (hi<=lo || Math.min(ab[3],bb[3])<=Math.max(ab[1],bb[1])) return 0;
  const edges=[a,b].map(poly=>poly.map((p,i)=>[p,poly[(i+1)%poly.length]]));
  const cuts=new Set([lo,hi,...[...a,...b].map(p=>p[0]).filter(x=>lo<x && x<hi)]);
  const cross=(v,w)=>v[0]*w[1]-v[1]*w[0], delta=(p,q)=>p.map((v,i)=>v-q[i]);
  for (const [p,q] of edges[0]) for (const [r,s] of edges[1]) {
    const v=delta(q,p), w=delta(s,r), d=delta(r,p), den=cross(v,w);
    if (Math.abs(den)<=1e-9) continue;
    const t=cross(d,w)/den, u=cross(d,v)/den, x=p[0]+t*v[0];
    if (0<t && t<1 && 0<u && u<1 && lo<x && x<hi) cuts.add(x);
  }
  const ordered=[...cuts].sort((x,y)=>x-y); let area=0;
  for (let i=1;i<ordered.length;i++) {
    const x=(ordered[i-1]+ordered[i])/2;
    const intervals=edges.map(boundary=> {
      const ys=boundary.filter(([p,q])=>Math.min(p[0],q[0])<x && x<Math.max(p[0],q[0]))
        .map(([p,q])=>p[1]+(x-p[0])*(q[1]-p[1])/(q[0]-p[0])).sort((p,q)=>p-q);
      return ys.filter((_,j)=>j%2===0).map((v,j)=>[v,ys[2*j+1]]);
    });
    for (const [p,q] of intervals[0]) for (const [r,s] of intervals[1]) area+=(ordered[i]-ordered[i-1])*Math.max(0,Math.min(q,s)-Math.max(p,r));
  }
  return area;
}

function coversColumn(roof, sections, at) {
  const [x,y]=roofPoint(roof,at,true);
  return sections.some(section=> {
    const r=roofBounds({...section,roof_frame:null});
    return Math.hypot(Math.max(r[0]-x,0,x-r[2]),Math.max(r[1]-y,0,y-r[3]))<=.05+1e-8;
  });
}

export function postRoofReason(building, porch, roof) {
  if (['ghost','proposal'].includes(porch?.state)) return 'Choose a settled porch; ghost and proposal porches cannot move posts.';
  if (roof && ['ghost','proposal'].includes(roof.state)) return 'Choose a settled roof; ghost and proposal roofs cannot receive posts.';
  if (!porch?.columns?.length) return 'This porch has no columns to move.';
  const level=porch.level || building.rooms?.find(r=>r.id===porch.id)?.level;
  const area=roof && (roof.area || [[roof.rect[0],roof.rect[1]],[roof.rect[2],roof.rect[1]],[roof.rect[2],roof.rect[3]],[roof.rect[0],roof.rect[3]]]);
  if (!roof || roof.level!==level || overlapArea(porch.polygon,area.map(p=>roofPoint(roof,p)))<=1e-8) return 'No roof overlaps this porch on its floor.';
  if (isSupported(roof)) return 'This roof already has supports.';
  const sections=roof.rect ? [roof] : (building.roof?.sections || []).filter(s=>(s.roof || s.id)===roof.id);
  if (!sections.length || sections.some(s=>s.kind!=='shed')) return 'Choose a shed roof; this walled roof is not a shed.';
  const columns=porch.columns, size=columns[0].size;
  if (columns.length>40 || size<.05 || size>3 || columns.some(c=>Math.abs(c.size-size)>1e-8)) return 'The roof needs at most 40 columns of the same size, from 0.05 to 3 feet.';
  if (columns.some(c=>!coversColumn(roof,sections,c.at))) return 'A column centre is outside the roof perimeter (including overhang; tolerance 0.05 ft).';
  return null;
}

export function postRoofChoices(building, porchId) {
  const porch=allPorches(building).find(p=>p.id===porchId);
  const candidates=building.roofs?.length ? building.roofs : building.roof?.sections || [];
  return candidates.filter(roof=>postRoofReason(building,porch,roof)===null)
    .filter((roof,i,rows)=>rows.findIndex(r=>(r.roof || r.id)===(roof.roof || roof.id))===i);
}

export function drawPostsAction(host, record, { getPlan, canEdit, queue, op, report, ownSlot, onSaved }) {
  if (!(record.kind === 'porch' || record.kind === 'room' && record.piece.kind === 'porch')) return null;
  const current = () => getPlan().buildings.find(b => b.id === record.building.id);
  const choices = () => current() ? postRoofChoices(current(), record.piece.id) : [];
  const row = document.createElement('div'); row.className = 'editor-material-actions editor-card-row';
  host.append(row);
  let signature, button;
  const refresh = () => {
    const roofs = choices(), key = JSON.stringify([roofs.map(r => [r.roof || r.id, r.name]), canEdit()]);
    if (key === signature) return;
    signature = key; row.replaceChildren(); button = null; row.hidden = !roofs.length;
    if (!roofs.length) return;
    let select;
    if (roofs.length > 1) {
      select = document.createElement('select'); select.setAttribute('aria-label', 'Roof for the posts');
      for (const roof of roofs) {
        const option = document.createElement('option'); option.value = roof.roof || roof.id;
        option.textContent = roof.name || `Roof ${roof.roof || roof.id}`; select.append(option);
      }
      select.value = roofs[0].roof || roofs[0].id; select.disabled = !canEdit(); row.append(select);
    }
    button = document.createElement('button'); button.type = 'button'; button.textContent = 'Move posts to the roof'; button.disabled = !canEdit();
    button.addEventListener('click', () => Promise.resolve(queue(async () => {
      if (!canEdit()) return;
      const id = select?.value || roofs[0].roof || roofs[0].id;
      if (!choices().some(r => (r.roof || r.id) === id)) return;
      if (!await window.promptConfirm('Move posts to the roof?', 'Before: the porch owns the posts. After: the posts move to the roof; the porch floor stays; the roof stops shaping walls and gables under it.', 'Move posts', 'Cancel')) return;
      if (!canEdit() || !choices().some(r => (r.roof || r.id) === id)) return;
      await op({op:'move_posts_to_roof', building:record.building.id, porch:record.piece.id, roof:id});
      onSaved?.();
    })).catch(report));
    row.append(button);
  };
  refresh();
  ownSlot?.({refresh, dispose: () => row.remove()});
  return button;
}

// Stored box choices, shared by editor consumers; geometry stays with the renderer.
import { roofPoint } from './roof_supports.js';
export const SUPPORT_STYLES = {bracket: [['plain','Straight']], corbel: [['scroll','Scroll'],['plain','Stepped']], brace: [['plain','Straight'],['arched','Arched']], cable: [], post: []};

export function allowedEndIndices(roof) {
  const sides = ['y0','x1','y1','x0'];
  const edges = roof.edges || sides.map(side => ({setting: roof.kind === 'flat' || roof.kind === 'shed' && side === roof.low_side || ['gable','hip'].includes(roof.kind) && side[0] !== roof.ridge ? 'sloped' : roof.ends?.[side] || 'gable', pitch: roof.pitch || 0}));
  // Decision: a flat awning allows closed ends on every non-host edge.
  return edges.flatMap((e,i) => i !== roof.host?.edge && (['gable','clip'].includes(e.setting) || (e.pitch ?? roof.pitch ?? 0) === 0) ? [String(i)] : []);
}

export function normalizeRoofBox(roof) {
  const supported = !!roof.support?.kind && roof.support.kind !== 'walls';
  const legacy = Object.fromEntries(Object.entries(roof.ends || {}).filter(([k]) => roof.rect && ['x0','x1','y0','y1'].includes(k)));
  const allowed = allowedEndIndices(roof);
  const ends = {...legacy, ...Object.fromEntries(Object.entries(roof.ends || {}).filter(([k,v]) => supported && allowed.includes(k) && v === 'closed'))};
  if (Object.keys(ends).length) roof.ends = ends; else delete roof.ends;
  if (supported && roof.underside?.kind === 'flat') {
    const drop = roof.underside.drop_ft ?? 0;
    roof.underside = {kind:'flat',drop_ft:typeof drop === 'number' && Number.isFinite(drop) && drop >= 0 && drop <= 3 ? drop : 0};
  } else delete roof.underside;
  return roof;
}

export function roofEndLabels(roof) {
  const area = roof.area || [[roof.rect[0],roof.rect[1]],[roof.rect[2],roof.rect[1]],[roof.rect[2],roof.rect[3]],[roof.rect[0],roof.rect[3]]];
  const sign = area.reduce((n,p,i) => { const q=area[(i+1)%area.length];return n+p[0]*q[1]-p[1]*q[0]; },0) > 0 ? 1 : -1;
  return allowedEndIndices(roof).map(index => {
    const i=Number(index),p=roofPoint(roof,area[i]),q=roofPoint(roof,area[(i+1)%area.length]);
    const dx=sign*(q[1]-p[1]),dy=-sign*(q[0]-p[0]);
    // Name the nearest building axis; exact diagonal ties use front/back.
    return [index, Math.abs(dx)>Math.abs(dy) ? dx>0?'Right':'Left' : dy>0?'Back':'Front'];
  }).map(([i,label],_,all) => [i,all.filter(([,v])=>v===label).length>1?`${label} end ${Number(i)+1}`:`${label} end`]);
}

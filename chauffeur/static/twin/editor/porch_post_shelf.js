import { allPorches } from '../gutter_presence.js';
import { POST_SIZE, postRef, findPost } from '../porch_posts.js';
import { drawPostsAction, postRoofDisabledReason } from './posts_action.js';
import { parseLength } from './selection_fields.js';
import { snapValue } from './snap.js';

export { postRoofDisabledReason };

const EPS = 1e-8;
const SNAP_REACH_FT = 0.5;
const POS_LIMIT_FT = 1e5;
const SIZE_REFUSAL = `Choose a post size from ${POST_SIZE.min} to ${POST_SIZE.max} feet.`;
const POS_REFUSAL = 'Choose a finite post position.';
const fmt = value => String(Number(Number(value).toFixed(4)));

export function porchName(building, porch) {
  const room = building?.rooms?.find(r => r.id === porch?.id);
  return room?.name || porch?.name || 'Porch';
}

export function porchPostTitle(record) {
  return `Post ${record.index + 1} \u00b7 ${porchName(record.building, record.porch)}`;
}

// Compute inset polygon edges, inset corners and other posts' alignment lines
// once per drag gesture so pointermove work stays O(edges + posts) with no allocations.
export function buildPostSnapTargets(porch, index, size = POST_SIZE.fallback) {
  const half = (Number.isFinite(size) ? size : POST_SIZE.fallback) / 2;
  const poly = Array.isArray(porch?.polygon) && porch.polygon.length >= 3 ? porch.polygon : [];
  const corners = [], edges = [];
  if (poly.length >= 3) {
    let area2 = 0;
    for (let i = 0; i < poly.length; i++) {
      const p = poly[i], q = poly[(i + 1) % poly.length];
      area2 += p[0] * q[1] - q[0] * p[1];
    }
    const sign = area2 >= 0 ? 1 : -1;
    const rawEdges = [];
    for (let i = 0; i < poly.length; i++) {
      const a = poly[i], b = poly[(i + 1) % poly.length];
      const dx = b[0] - a[0], dy = b[1] - a[1], len = Math.hypot(dx, dy);
      if (len < EPS) continue;
      const u = [dx / len, dy / len];
      const n = [-sign * dy / len, sign * dx / len];
      rawEdges.push({ a, b, u, n, aIn: [a[0] + n[0] * half, a[1] + n[1] * half], bIn: [b[0] + n[0] * half, b[1] + n[1] * half] });
    }
    const m = rawEdges.length;
    for (let i = 0; i < m; i++) {
      const prev = rawEdges[(i - 1 + m) % m], curr = rawEdges[i];
      const den = prev.u[0] * curr.u[1] - prev.u[1] * curr.u[0];
      let corner = null;
      if (Math.abs(den) > 1e-6) {
        const rx = curr.aIn[0] - prev.aIn[0], ry = curr.aIn[1] - prev.aIn[1];
        const t = (rx * curr.u[1] - ry * curr.u[0]) / den;
        const cand = [prev.aIn[0] + t * prev.u[0], prev.aIn[1] + t * prev.u[1]];
        if (Math.hypot(cand[0] - curr.a[0], cand[1] - curr.a[1]) <= Math.max(half * 4, 1)) corner = cand;
      }
      if (!corner) {
        const nx = prev.n[0] + curr.n[0], ny = prev.n[1] + curr.n[1], nlen = Math.hypot(nx, ny);
        corner = nlen > 1e-6 ? [curr.a[0] + nx / nlen * half, curr.a[1] + ny / nlen * half] : [...curr.aIn];
      }
      corners.push(corner);
    }
    for (let i = 0; i < corners.length; i++) {
      const a = corners[i], b = corners[(i + 1) % corners.length];
      const dx = b[0] - a[0], dy = b[1] - a[1], len2 = dx * dx + dy * dy;
      if (len2 < EPS * EPS) continue;
      edges.push({ a, b, dx, dy, len2, len: Math.sqrt(len2) });
    }
  }
  const postXs = [], postYs = [];
  const pushUnique = (list, val) => {
    if (!Number.isFinite(val)) return;
    if (!list.some(v => Math.abs(v - val) < 1e-6)) list.push(val);
  };
  (porch?.columns || []).forEach((col, i) => {
    if (i === index || !Array.isArray(col?.at) || col.at.length < 2) return;
    pushUnique(postXs, col.at[0]);
    pushUnique(postYs, col.at[1]);
  });
  return { corners, edges, postXs, postYs };
}

export function snapPostPoint(raw, targets, free = false, reach = SNAP_REACH_FT) {
  if (free || !targets) return { point: [raw[0], raw[1]], target: 'free' };
  const [rx, ry] = raw;
  // 1. Inset corners (highest priority).
  let bestCorner = null, bestCornerDist = reach + 1e-9;
  for (const c of targets.corners || []) {
    const d = Math.hypot(c[0] - rx, c[1] - ry);
    if (d <= bestCornerDist) { bestCornerDist = d; bestCorner = c; }
  }
  if (bestCorner) return { point: [bestCorner[0], bestCorner[1]], target: 'corner' };

  // 2. Inset outline edges (intersected with other posts' lines, else grid along edge).
  let bestEdge = null, bestEdgeDist = reach + 1e-9, bestProj = null;
  for (const e of targets.edges || []) {
    const t = Math.max(0, Math.min(1, ((rx - e.a[0]) * e.dx + (ry - e.a[1]) * e.dy) / e.len2));
    const px = e.a[0] + t * e.dx, py = e.a[1] + t * e.dy;
    const d = Math.hypot(px - rx, py - ry);
    if (d <= bestEdgeDist) { bestEdgeDist = d; bestEdge = e; bestProj = [px, py]; }
  }
  if (bestEdge) {
    let bestHit = null, bestHitDist = reach + 1e-9;
    if (Math.abs(bestEdge.dx) > 1e-6) {
      for (const px of targets.postXs || []) {
        const t = (px - bestEdge.a[0]) / bestEdge.dx;
        if (t < -1e-6 || t > 1 + 1e-6) continue;
        const clamped = Math.max(0, Math.min(1, t));
        const cand = [bestEdge.a[0] + clamped * bestEdge.dx, bestEdge.a[1] + clamped * bestEdge.dy];
        const d = Math.hypot(cand[0] - rx, cand[1] - ry);
        if (d <= bestHitDist) { bestHitDist = d; bestHit = cand; }
      }
    }
    if (Math.abs(bestEdge.dy) > 1e-6) {
      for (const py of targets.postYs || []) {
        const t = (py - bestEdge.a[1]) / bestEdge.dy;
        if (t < -1e-6 || t > 1 + 1e-6) continue;
        const clamped = Math.max(0, Math.min(1, t));
        const cand = [bestEdge.a[0] + clamped * bestEdge.dx, bestEdge.a[1] + clamped * bestEdge.dy];
        const d = Math.hypot(cand[0] - rx, cand[1] - ry);
        if (d <= bestHitDist) { bestHitDist = d; bestHit = cand; }
      }
    }
    if (bestHit) return { point: bestHit, target: 'edge_post' };
    if (Math.abs(bestEdge.dy) < 1e-6) {
      const lo = Math.min(bestEdge.a[0], bestEdge.b[0]), hi = Math.max(bestEdge.a[0], bestEdge.b[0]);
      const sx = Math.max(lo, Math.min(hi, snapValue('move', rx, false)));
      return { point: [sx, bestEdge.a[1]], target: 'edge' };
    }
    if (Math.abs(bestEdge.dx) < 1e-6) {
      const lo = Math.min(bestEdge.a[1], bestEdge.b[1]), hi = Math.max(bestEdge.a[1], bestEdge.b[1]);
      const sy = Math.max(lo, Math.min(hi, snapValue('move', ry, false)));
      return { point: [bestEdge.a[0], sy], target: 'edge' };
    }
    return { point: bestProj, target: 'edge' };
  }

  // 3. Other posts' X and Y alignment lines.
  let snapX = null, bestDx = reach + 1e-9;
  for (const x of targets.postXs || []) {
    const d = Math.abs(x - rx);
    if (d <= bestDx) { bestDx = d; snapX = x; }
  }
  let snapY = null, bestDy = reach + 1e-9;
  for (const y of targets.postYs || []) {
    const d = Math.abs(y - ry);
    if (d <= bestDy) { bestDy = d; snapY = y; }
  }
  if (snapX !== null || snapY !== null) {
    return {
      point: [snapX !== null ? snapX : snapValue('move', rx, false), snapY !== null ? snapY : snapValue('move', ry, false)],
      target: 'post_line',
    };
  }

  // 4. Grid.
  return { point: [snapValue('move', rx, false), snapValue('move', ry, false)], target: 'grid' };
}

function parsePostNumber(text, { min = -Infinity, max = Infinity, message }) {
  const trimmed = String(text ?? '').trim();
  if (!trimmed) throw new Error(message);
  let value;
  try { value = parseLength(trimmed); } catch { throw new Error(message); }
  if (!Number.isFinite(value) || value < min || value > max) throw new Error(message);
  return value;
}

function currentPost(plan, buildingId, postId) {
  const b = plan?.buildings?.find(x => x.id === buildingId);
  return b ? findPost(b, postId) : null;
}

// Single-post Properties fields (Position X, Position Y, Size) with in-place refresh.
export function drawPorchPostShelf(host, record, { getPlan, canEdit, queue, op, report, ownSlot, onSaved }) {
  if (record?.kind !== 'porch_post') return null;
  const section = document.createElement('section');
  section.setAttribute('aria-label', 'Post');
  section.dataset.porchPostFields = '';
  host.append(section);

  const buildingId = record.building.id, postId = record.piece.id;
  const states = new Map();

  function addField(key, labelText, getValue, parse, buildChange) {
    const label = document.createElement('label'); label.textContent = labelText;
    const input = document.createElement('input');
    input.type = 'text';
    input.value = fmt(getValue(record));
    input.disabled = !canEdit();
    input.setAttribute('aria-label', labelText);
    const error = document.createElement('small'); error.setAttribute('role', 'status');
    label.append(input, error); section.append(label);
    const state = { input, error, baseline: input.value, queued: 0, getValue };
    states.set(key, state);
    const fail = err => {
      error.textContent = err.message;
      input.setAttribute('aria-invalid', 'true');
      report(Object.assign(err, { shown: true }));
    };
    const save = () => {
      if (!canEdit()) return;
      error.textContent = ''; input.setAttribute('aria-invalid', 'false');
      if (input.value === state.baseline && !state.queued) return;
      let parsed;
      try { parsed = parse(input.value); } catch (err) { fail(err); return; }
      const submitted = input.value;
      ++state.queued;
      Promise.resolve(queue(async () => {
        if (!canEdit()) return;
        const fresh = currentPost(getPlan(), buildingId, postId);
        if (!fresh) throw new Error('That post is missing.');
        const change = buildChange(fresh, parsed);
        if (!change) { if (input.value === submitted) state.baseline = submitted; return; }
        await op({ op: 'update_porch_post', building: buildingId, porch: fresh.porchId, post: fresh.id, ...change });
        if (input.value === submitted) state.baseline = submitted;
        onSaved?.();
      })).catch(fail).finally(() => { --state.queued; });
    };
    input.addEventListener('change', save);
    input.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); save(); } });
  }

  addField('x', 'Position X (ft)', r => r.piece.at[0],
    text => parsePostNumber(text, { min: -POS_LIMIT_FT, max: POS_LIMIT_FT, message: POS_REFUSAL }),
    (fresh, x) => Math.abs(fresh.piece.at[0] - x) > EPS ? { at: [x, fresh.piece.at[1]] } : null);
  addField('y', 'Position Y (ft)', r => r.piece.at[1],
    text => parsePostNumber(text, { min: -POS_LIMIT_FT, max: POS_LIMIT_FT, message: POS_REFUSAL }),
    (fresh, y) => Math.abs(fresh.piece.at[1] - y) > EPS ? { at: [fresh.piece.at[0], y] } : null);
  addField('size', 'Size (ft)', r => r.piece.size ?? POST_SIZE.fallback,
    text => parsePostNumber(text, { min: POST_SIZE.min, max: POST_SIZE.max, message: SIZE_REFUSAL }),
    (fresh, size) => Math.abs((fresh.piece.size ?? POST_SIZE.fallback) - size) > EPS ? { size } : null);

  const refresh = () => {
    const fresh = currentPost(getPlan(), buildingId, postId);
    for (const state of states.values()) {
      state.input.disabled = !canEdit();
      if (fresh && document.activeElement !== state.input && state.input.value === state.baseline && !state.queued) {
        state.input.value = fmt(state.getValue(fresh));
        state.baseline = state.input.value;
      }
    }
  };
  ownSlot?.({ refresh, dispose: () => section.remove() });
  return { section, refresh };
}

// Appended right after the porch's Columns material row on a porch_post card.
export function drawPorchPostFooter(host, record, { select }) {
  if (record?.kind !== 'porch_post') return;
  const note = document.createElement('p');
  note.className = 'editor-downspout-note';
  note.dataset.postMaterialNote = '';
  note.textContent = 'Applies to all posts of this porch.';
  host.append(note);
  const go = document.createElement('button');
  go.type = 'button';
  go.dataset.selectPorch = '';
  go.textContent = 'Select the porch';
  go.addEventListener('click', () => select({ pieceId: record.porchId, buildingId: record.building.id }));
  host.append(go);
}

// Porch card's "Posts" section: count, Add post, Size for all posts, and Move posts to the roof.
export function drawPorchPostsSection(host, record, { getPlan, canEdit, queue, op, applyBatch, report, ownSlot, select, visibility, onSaved }) {
  if (!(record?.kind === 'porch' || record?.kind === 'room' && record.piece.kind === 'porch')) return null;
  const buildingId = record.building.id, porchId = record.piece.id;
  const currentColumns = () => {
    const b = getPlan().buildings.find(x => x.id === buildingId) || record.building;
    return allPorches(b).find(p => p.id === porchId)?.columns || [];
  };

  const section = document.createElement('section');
  section.setAttribute('aria-label', 'Posts');
  section.dataset.porchPosts = '';
  const heading = document.createElement('h4'); heading.textContent = 'Posts';
  const summary = document.createElement('p');
  summary.dataset.porchPostsCount = '';
  section.append(heading, summary);

  const add = document.createElement('button');
  add.type = 'button';
  add.textContent = 'Add post';
  add.addEventListener('click', () => Promise.resolve(queue(async () => {
    if (!canEdit()) return;
    const bNow = getPlan().buildings.find(b => b.id === buildingId);
    const pNow = bNow && allPorches(bNow).find(p => p.id === porchId);
    const beforeCount = pNow?.columns?.length || 0;
    if (beforeCount >= POST_SIZE.limit) return;
    await op({ op: 'add_porch_post', building: buildingId, porch: porchId });
    const bAfter = getPlan().buildings.find(b => b.id === buildingId);
    const pAfter = bAfter && allPorches(bAfter).find(p => p.id === porchId);
    const afterCols = pAfter?.columns || [];
    if (afterCols.length > beforeCount) {
      const newId = postRef(pAfter, afterCols.length - 1);
      visibility?.show?.(newId);
      visibility?.unlock?.(newId);
      select({ pieceId: newId, buildingId });
    } else {
      onSaved?.();
    }
  })).catch(report));
  section.append(add);

  const label = document.createElement('label'); label.textContent = 'Size for all posts';
  const input = document.createElement('input');
  input.type = 'text';
  input.setAttribute('aria-label', 'Size for all posts');
  const error = document.createElement('small'); error.setAttribute('role', 'status');
  label.append(input, error); section.append(label);
  let baseline = '', uniform = true, queued = 0;
  const fail = err => {
    error.textContent = err.message;
    input.setAttribute('aria-invalid', 'true');
    report(Object.assign(err, { shown: true }));
  };
  const saveAll = () => {
    if (!canEdit()) return;
    error.textContent = ''; input.setAttribute('aria-invalid', 'false');
    if (!input.value.trim()) {
      if (!uniform) return;
      fail(new Error(SIZE_REFUSAL));
      return;
    }
    if (uniform && input.value === baseline && !queued) return;
    let size;
    try { size = parsePostNumber(input.value, { min: POST_SIZE.min, max: POST_SIZE.max, message: SIZE_REFUSAL }); }
    catch (err) { fail(err); return; }
    const submitted = input.value;
    ++queued;
    Promise.resolve(queue(async () => {
      if (!canEdit()) return;
      const bNow = getPlan().buildings.find(b => b.id === buildingId);
      const pNow = bNow && allPorches(bNow).find(p => p.id === porchId);
      if (!pNow?.columns?.length) return;
      const ops = [];
      for (let i = 0; i < pNow.columns.length; i++) {
        if (Math.abs((pNow.columns[i].size ?? POST_SIZE.fallback) - size) > EPS) {
          ops.push({ op: 'update_porch_post', building: buildingId, porch: porchId, post: postRef(pNow, i), size });
        }
      }
      if (ops.length) await applyBatch(ops);
      if (input.value === submitted) baseline = submitted;
      onSaved?.();
    })).catch(fail).finally(() => { --queued; });
  };
  input.addEventListener('change', saveAll);
  input.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); saveAll(); } });

  const refresh = () => {
    const columns = currentColumns(), count = columns.length;
    summary.textContent = `${count} ${count === 1 ? 'post' : 'posts'}`;
    const atLimit = count >= POST_SIZE.limit;
    add.disabled = !canEdit() || atLimit;
    if (atLimit) { add.dataset.postDisabled = ''; add.title = `A porch can have at most ${POST_SIZE.limit} posts.`; }
    else { delete add.dataset.postDisabled; add.removeAttribute('title'); }
    label.hidden = count === 0;
    input.disabled = !canEdit();
    if (count > 0) {
      const firstSize = columns[0].size ?? POST_SIZE.fallback;
      uniform = columns.every(c => Math.abs((c.size ?? POST_SIZE.fallback) - firstSize) <= EPS);
      if (document.activeElement !== input && input.value === baseline && !queued) {
        input.value = uniform ? fmt(firstSize) : '';
        input.placeholder = uniform ? '' : 'Mixed';
        baseline = input.value;
      }
    }
  };
  refresh();
  drawPostsAction(section, record, { getPlan, canEdit, queue, op, report, ownSlot, onSaved });
  ownSlot?.({ refresh, dispose: () => section.remove() });

  host.append(section);
  return section;
}

import * as THREE from 'three';
import { FT, polygon } from '../twin_generator.js';
import { groundAt } from '../twin_ground.js';
import { hostPoint } from '../twin_hosts.js';
import { findPiece } from './cards.js';
import { report } from './api.js';
import { pieceGhostGeometry, ghostGroup } from './ghost_geometry.js';

// Review geometry belongs to the editor, never to the flattened building.
export function createFlags({ view, getModel, getPlan, tools, panel, op, canEdit, signal, onInteract, managed = false, onReview }) {
  const canvas = view.renderer3.domElement, host = canvas.parentElement;
  const layer = document.createElement('div'); layer.className = 'editor-flag-markers'; host.append(layer);
  const card = document.createElement('aside'); card.id = 'review-card'; card.hidden = true;
  card.setAttribute('aria-label', 'Check this piece'); document.getElementById('piece-card').after(card);
  const shell = card.closest('.editor-shell'), root = new THREE.Group(); view.scene.add(root);
  const raycaster = new THREE.Raycaster();
  let rows = [], proposals = [], current = null, proposal = null, highlighted = [];
  let signature = '', highlightSignature = '', busy = false, lastSelection = '', frame;
  let highlight = new THREE.Group(); highlight.name = 'editor-flag-highlight'; root.add(highlight);
  const selectionKey = () => { const { kind, id, building, room } = tools.selection(); return JSON.stringify([kind, id, building, room]); };
  const building = id => getModel()?.buildings?.find(b => b.id === id);
  // A roof check names its roof block by its rectangle (block_rect); the roof standing on that
  // block carries the same rectangle as `block`, and its plate is the check's height.
  const roofOf = (b, flag) => Array.isArray(flag?.block_rect) ? (b?.roofs || []).find(r => Array.isArray(r.block)
    && r.block.length === 4 && r.block.every((v, i) => Math.abs(v - flag.block_rect[i]) < 1e-6)) : null;
  // The height a check stands at: its floor, else its roof's plate, else the ground.
  const flagZ = (b, flag) => b?.levels?.find(l => l.id === flag.level)?.elevation
    ?? roofOf(b, flag)?.plate ?? b?.roofs?.find(r => r.id === flag.piece)?.plate ?? 0;
  function world(b, point) {
    const a = (b.rotation || 0) * Math.PI / 180, [x, y, z = 0] = point, p = b.position || [0, 0];
    return new THREE.Vector3((Math.cos(a) * x - Math.sin(a) * y + p[0]) * FT,
      (z + (b.base || 0) + groundAt(getPlan(), ...p)) * FT,
      -(Math.sin(a) * x + Math.cos(a) * y + p[1]) * FT);
  }
  function clearGeometry(group) {
    group.traverse(object => { object.geometry?.dispose();
      for (const material of [].concat(object.material || [])) material.dispose(); });
    group.clear();
  }
  function button(text, action) {
    const node = document.createElement('button'); node.type = 'button'; node.textContent = text;
    node.disabled = busy || !canEdit();
    node.addEventListener('click', () => Promise.resolve().then(action).catch(report), { signal });
    return node;
  }
  function drawCard() {
    if (managed) { card.hidden = true; return; }
    card.replaceChildren(); card.hidden = !current && !proposal;
    shell.toggleAttribute('data-reviewing', !card.hidden);
    if (card.hidden) return;
    const heading = document.createElement('h3'); heading.textContent = proposal ? 'Proposed change' : 'Check this piece';
    const close = button('Close', () => { if (proposal) tools.select(null); closeReview(); }); close.setAttribute('aria-label', 'Close check');
    const text = document.createElement('p');
    text.textContent = proposal ? 'A new reading suggests this change to your piece. Your version stays until you choose Use this.' : current.flag.text;
    card.append(heading, close, text);
    if (proposal) {
      const row = proposal;
      card.append(button('Use this', () => save({ op: 'accept_proposal', building: row.building, id: row.id })),
        button('Dismiss', () => save({ op: 'dismiss_proposal', building: row.building, id: row.id })));
    } else {
      const row = current;
      card.append(button('Looks right', () => save({ op: 'set', building: row.building, field: 'flag_ok',
        value: { index: row.index, text: row.flag.text, flag: row.flag } })), button('Fix it', () => {
        selectFlag(row); closeReview();
      }));
    }
  }
  function closeReview() {
    current = proposal = null; drawHighlight(); drawCard();
  }
  async function save(operation) {
    if (!canEdit() || busy) return;
    busy = true; drawCard();
    try { await op(operation); tools.select(null); closeReview(); }
    finally { busy = false; refresh(); drawCard(); }
  }
  function selectFlag(row) {
    onInteract?.();
    const b = building(row.building), flag = row.flag;
    const roof = roofOf(b, flag);
    const id = typeof flag.piece === 'string' ? flag.piece : roof?.id;
    const piece = id ? findPiece(getPlan(), id, b.id) : null;
    const level = flag.level || (roof ? null : piece?.piece.level);
    if (level) tools.chooseFloor(`${b.id}:${level}`);
    tools.select(null);
    if (piece) tools.select({ id, building: b.id });
    const elevation = b.levels.find(l => l.id === level)?.elevation ?? flagZ(b, flag);
    const target = world(b, [...flag.at, elevation]);
    view.camera.position.add(target.clone().sub(view.controls.target));
    view.controls.target.copy(target);
    if (roof && Array.isArray(flag.block_rect) && view.camera.isPerspectiveCamera) {
      // Frame the roof block: come close enough that it reads, never back away.
      const [x0, y0, x1, y1] = flag.block_rect, span = Math.max(6, Math.hypot(x1 - x0, y1 - y0) * FT);
      const away = view.camera.position.clone().sub(target), reach = span * 2.4;
      if (away.length() > reach) view.camera.position.copy(target).add(away.setLength(reach));
    }
    view.controls.update(); view.camera.updateMatrixWorld(true);
    lastSelection = selectionKey();
  }
  function showFlag(row) {
    if (!canEdit() || busy) return;
    current = row; proposal = null; selectFlag(row); drawHighlight(); drawCard();
  }
  function walk() {
    refresh();
    const index = current ? rows.findIndex(row => row.building === current.building && row.index === current.index) : -1;
    if (rows.length) showFlag(rows[(index + 1) % rows.length]);
  }
  function dashed(points) {
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),
      new THREE.LineDashedMaterial({ color: '#52ccff', dashSize: .15, gapSize: .08, depthTest: false }));
    line.computeLineDistances(); line.renderOrder = 12; highlight.add(line);
  }
  // The thing in question, outlined: grouped separator walls, or a roof check's roof area at its plate.
  function drawHighlight() {
    const b = current && building(current.building), flag = current?.flag;
    const members = flag?.separators;
    const walls = b && (members || /invisible walls?/.test(flag.text)) ? b.walls.filter(w =>
      members ? members.some(id => w.id === id || w.id.startsWith(id + '~'))
        : w.kind === 'separator' && w.level === flag.level && w.src?.step === 'migration') : [];
    const roof = b && roofOf(b, flag), rect = b && Array.isArray(flag?.block_rect) ? flag.block_rect : null;
    highlighted = [...walls.map(w => w.id), ...(roof ? [roof.id] : [])];
    const next = JSON.stringify([b?.id, walls, rect, roof?.plate, b?.joints, b?.position, b?.rotation, b?.base]);
    if (next === highlightSignature) return;
    highlightSignature = next; clearGeometry(highlight);
    if (!b) return;
    const joints = new Map(b.joints.map(j => [j.id, j.at]));
    for (const wall of walls) {
      const z = (b.levels.find(l => l.id === wall.level)?.elevation || 0) + .06;
      dashed(wall.joints.map(id => world(b, [...joints.get(id), z])));
    }
    if (rect?.length === 4) {
      const [x0, y0, x1, y1] = rect, z = flagZ(b, flag) + .06, area = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
      dashed([...area, area[0]].map(p => world(b, [...p, z])));
      // A soft fill over the roof block, so the area reads even where the marker covers its middle.
      const fill = new THREE.Mesh(polygon(area, z), new THREE.MeshBasicMaterial({ color: '#52ccff', transparent: true,
        opacity: .28, depthTest: false, depthWrite: false, side: THREE.DoubleSide }));
      fill.scale.setScalar(FT); fill.rotation.y = (b.rotation || 0) * Math.PI / 180;
      fill.position.copy(world(b, [0, 0, 0])); fill.renderOrder = 11; highlight.add(fill);
    }
  }
  function ghostGeometry(b, row) {
    const flat = getPlan()?.buildings.find(p => p.id === b.id);
    const joints = new Map(b.joints.map(j => [j.id, j.at]));
    return pieceGhostGeometry(row.kind, row.piece, {
      level: id => b.levels.find(l => l.id === id),
      wall: id => flat?.walls.find(w => w.id === id),
      joint: id => joints.get(id),
      host: (host, offset) => flat ? hostPoint(flat, host, offset) : null,
    });
  }
  function refresh() {
    const model = getModel(), next = JSON.stringify(model);
    if (next !== signature) {
      signature = next;
      rows = (model?.buildings || []).flatMap(b => (b.flags || []).map((flag, index) => ({ building: b.id, index, flag })));
      if (current) current = rows.find(row => row.building === current.building && row.index === current.index
        && JSON.stringify(row.flag) === JSON.stringify(current.flag)) || null;
      layer.replaceChildren();
      for (const row of rows) {
        // A marker only shows where a check is; the count walks them. It never
        // takes a click, so a marker over a building cannot block picking it.
        const node = document.createElement('div'); node.className = 'editor-pin-dot editor-flag-marker';
        node.textContent = '!'; node.setAttribute('aria-hidden', 'true'); row.node = node; layer.append(node);
      }
      for (const row of proposals) { clearGeometry(row.group); root.remove(row.group); }
      proposals = [];
      for (const b of model?.buildings || []) for (const entry of b.proposals || []) {
        const row = { ...entry, building: b.id, id: entry.id || entry.piece.id };
        const geometry = ghostGeometry(b, row); if (!geometry) continue;
        const { group, mesh } = ghostGroup(geometry);
        group.scale.setScalar(FT); group.rotation.y = (b.rotation || 0) * Math.PI / 180;
        group.position.copy(world(b, [0, 0, 0]));
        root.add(group);
        proposals.push({ ...row, group, mesh });
      }
      if (proposal) proposal = proposals.find(row => row.building === proposal.building && row.id === proposal.id) || null;
      if (!managed) panel.checks(rows.length, walk);
      drawHighlight(); drawCard();
    }
  }
  function visible(bid, level) {
    const group = view.groups?.levels[`${bid}:${level}`];
    return !group || group.visible;
  }
  function pick(x, y) {
    if (!canEdit()) return null;
    const rect = canvas.getBoundingClientRect();
    if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) return null;
    view.camera.updateMatrixWorld(true); root.updateMatrixWorld(true);
    raycaster.setFromCamera(new THREE.Vector2((x - rect.left) / rect.width * 2 - 1, 1 - (y - rect.top) / rect.height * 2), view.camera);
    const hit = raycaster.intersectObjects(proposals.filter(row => row.group.visible).map(row => row.mesh), false)[0];
    if (!hit) return null;
    // Like the check markers, review ghosts take priority over the live
    // piece's coarse pick proxy (a stair proxy can enclose empty space).
    const row = proposals.find(p => p.mesh === hit.object);
    return { kind: 'proposal', id: row.id, building: row.building, level: row.piece.level };
  }
  function tick() {
    const key = selectionKey();
    if (key !== lastSelection) {
      lastSelection = key;
      const selected = tools.selection();
      proposal = proposals.find(row => selected.kind === 'proposal' && row.id === selected.id && row.building === selected.building) || null;
      if (managed && proposal) onReview?.({ kind: 'proposal', building: proposal.building, id: proposal.id });
      current = null; drawHighlight(); drawCard();
    }
    const rect = canvas.getBoundingClientRect(); view.camera.updateMatrixWorld(true);
    for (const row of rows) {
      const b = building(row.building), level = b.levels.find(l => l.id === row.flag.level);
      const point = world(b, [...row.flag.at, flagZ(b, row.flag)]).project(view.camera);
      row.node.hidden = !visible(b.id, level?.id) || point.z < -1 || point.z > 1 || Math.abs(point.x) > 1 || Math.abs(point.y) > 1;
      row.node.style.left = `${rect.left + (point.x + 1) * rect.width / 2}px`;
      row.node.style.top = `${rect.top + (1 - point.y) * rect.height / 2}px`;
      // The check being shown stands out from every other marker.
      const shown = !!current && current.building === row.building && current.index === row.index;
      const look = `editor-pin-dot editor-flag-marker${shown ? ' editor-flag-marker-current' : ''}`;
      if (row.node.className !== look) row.node.className = look;
    }
    for (const row of proposals) row.group.visible = visible(row.building, row.piece.level);
    highlight.visible = !!current && visible(current.building, current.flag.level);
    card.querySelectorAll('button').forEach(node => { node.disabled = busy || !canEdit(); });
    frame = requestAnimationFrame(tick);
  }
  signal.addEventListener('abort', () => {
    cancelAnimationFrame(frame); clearGeometry(root); root.removeFromParent(); layer.remove(); card.remove();
    shell?.removeAttribute('data-reviewing');
  }, { once: true });
  frame = requestAnimationFrame(tick);
  return { refresh, pick, dismiss: closeReview,
    review(item) {
      refresh();
      if (item?.kind === 'flag') {
        const row = rows.find(r => r.building === item.building && r.index === item.index);
        if (row) showFlag(row);
      } else if (item?.kind === 'proposal') {
        current = null; proposal = proposals.find(r => r.building === item.building && r.id === item.id);
        if (proposal) {
          const b = building(proposal.building), piece = proposal.piece;
          const at = piece.from || piece.area?.[0] || piece.position || [0, 0];
          selectFlag({ building: b.id, flag: { piece: proposal.against, level: piece.level, at } });
        }
        drawHighlight(); drawCard();
      } else closeReview();
    },
    flags: () => ({ count: rows.length, markers: rows.map(row => ({ building: row.building, index: row.index, at: [...row.flag.at] })),
      current: current && { building: current.building, index: current.index, text: current.flag.text, piece: current.flag.piece }, highlighted: [...highlighted] }),
    proposals: () => proposals.map(({ building, id, kind, against }) => ({ building, id, kind, against })),
  };
}

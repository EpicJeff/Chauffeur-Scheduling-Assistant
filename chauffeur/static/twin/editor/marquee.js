export const MARQUEE_THRESHOLD_PX = 4;

function isCandidatePickable(candidate, visibility, view) {
  if (!candidate) return false;
  if (visibility?.isPickable && visibility.isPickable(candidate) === false) return false;
  if (view?.isPiecePickable && view.isPiecePickable(candidate) === false) return false;
  if (view?.isPieceHidden?.(candidate)) return false;
  return true;
}

const refKey = ref => JSON.stringify([ref.buildingId ?? null, ref.pieceId]);

// Marquee box selection (Ruling 2): starts on empty space with the Select tool
// after 4 px of movement; draws on the existing #editor-drag-outline overlay;
// on release tests projected rendered bounds (whole-inside rule) via
// view.selectionBounds() without raycasting.
export function createMarquee({ view, selection, visibility, getPlan, isEmpty = null } = {}) {
  const canvas = view?.renderer3?.domElement || null;
  let press = null, overlay = null;

  function drawOverlay(x0, y0, x1, y1) {
    overlay ||= document.getElementById('editor-drag-outline');
    overlay?.setAttribute('points', `${x0},${y0} ${x1},${y0} ${x1},${y1} ${x0},${y1}`);
  }

  function hideOverlay() {
    overlay?.setAttribute('points', '');
    overlay = null;
  }

  function releasePress() {
    if (!press) return null;
    const g = press;
    press = null;
    if (view?.controls) view.controls.enabled = g.controlsEnabled;
    if (g.pointerId !== null && canvas?.hasPointerCapture?.(g.pointerId)) {
      canvas.releasePointerCapture(g.pointerId);
    }
    hideOverlay();
    return g;
  }

  function matchRect(rect) {
    const plan = getPlan?.() || {};
    const floor = view?.selectionFloor?.() || view?.state?.view || 'ext';
    const restrictFloor = floor && floor !== 'ext' && floor !== 'house';
    const rows = view?.selectionBounds?.() || [];
    const matched = [];
    for (const item of rows) {
      if (item.buildingId && restrictFloor && `${item.buildingId}:${item.level}` !== floor) continue;
      if (item.buildingId && (visibility?.isHidden?.(item.buildingId) || visibility?.isLocked?.(item.buildingId))) continue;
      if (!isCandidatePickable(item, visibility, view)) continue;
      const b = item.bounds;
      if (!b || b.left < rect.left || b.right > rect.right || b.top < rect.top || b.bottom > rect.bottom) continue;
      const ref = { kind: item.kind, pieceId: item.pieceId };
      if (item.buildingId != null) ref.buildingId = item.buildingId;
      if (item.level != null) ref.level = item.level;
      if (item.entity_id !== undefined) ref.entity_id = item.entity_id;
      if (item.poolId !== undefined) ref.poolId = item.poolId;
      if (item.porchId !== undefined || item.parentPieceId !== undefined) ref.porchId = item.porchId ?? item.parentPieceId;
      matched.push(ref);
    }
    return matched;
  }

  function pointerDown(event, { fromPiece = false } = {}) {
    // A piece hands off on pointermove, whose button is -1 in browsers.
    if (!event || event.pointerType === 'touch' || (!fromPiece && event.button !== undefined && event.button !== 0)) return false;
    if (press) cancel();
    if (!fromPiece && typeof isEmpty === 'function' && !isEmpty(event)) return false;
    press = {
      x: event.clientX,
      y: event.clientY,
      curX: event.clientX,
      curY: event.clientY,
      pointerId: event.pointerId ?? null,
      add: !!(event.ctrlKey || event.metaKey),
      remove: !!event.altKey,
      active: fromPiece,
      controlsEnabled: view?.controls?.enabled ?? true,
    };
    if (view?.controls) view.controls.enabled = false;
    if (fromPiece) drawOverlay(event.clientX, event.clientY, event.clientX, event.clientY);
    if (press.pointerId !== null && canvas?.setPointerCapture) {
      try { canvas.setPointerCapture(press.pointerId); } catch { /* Detached canvas in unit test. */ }
    }
    return true;
  }

  function pointerMove(event) {
    if (!press || !event) return false;
    if (press.pointerId !== null && event.pointerId !== undefined && event.pointerId !== press.pointerId) return false;
    press.curX = event.clientX;
    press.curY = event.clientY;
    if (!press.active) {
      if (Math.hypot(event.clientX - press.x, event.clientY - press.y) < MARQUEE_THRESHOLD_PX) return true;
      press.active = true;
    }
    drawOverlay(press.x, press.y, event.clientX, event.clientY);
    return true;
  }

  function pointerUp(event) {
    if (!press) return false;
    if (press.pointerId !== null && event?.pointerId !== undefined && event.pointerId !== press.pointerId) return false;
    const g = releasePress();
    const endX = event?.clientX ?? g.curX ?? g.x;
    const endY = event?.clientY ?? g.curY ?? g.y;
    const wasActive = g.active || Math.hypot(endX - g.x, endY - g.y) >= MARQUEE_THRESHOLD_PX;
    if (!wasActive) return false;
    const rect = {
      left: Math.min(g.x, endX),
      right: Math.max(g.x, endX),
      top: Math.min(g.y, endY),
      bottom: Math.max(g.y, endY),
    };
    const matched = matchRect(rect);
    const remove = !!(event?.altKey || g.remove);
    const add = !remove && !!(event?.ctrlKey || event?.metaKey || g.add);
    if (remove) {
      const drop = new Set(matched.map(refKey));
      selection?.set?.((selection.members?.() || []).filter(ref => !drop.has(refKey(ref))));
    } else if (add) {
      selection?.set?.([...(selection.members?.() || []), ...matched]);
    } else {
      selection?.set?.(matched);
    }
    return true;
  }

  function cancel() {
    const g = releasePress();
    return !!g?.active;
  }

  return {
    pointerDown,
    pointerMove,
    pointerUp,
    cancel,
    active: () => !!press?.active,
    dispose() { releasePress(); },
  };
}

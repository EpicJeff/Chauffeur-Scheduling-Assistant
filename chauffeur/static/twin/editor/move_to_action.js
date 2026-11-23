import { moveTargets, moveOps } from './move_to.js';
import { findPiece } from './piece_operations.js';
import { createContextMenu } from './context_menu.js';

// Card and canvas/Scene menus share destinations, refusal wording and the save
// path. Capture the owners when the menu opens; compute against the queued plan.
export function moveToAction({ refs, getPlan, getLabel, applyBatch, selectionStore, canEdit,
  chooseDestination, queue = work => work() }) {
  if (!refs.some(ref => ['item', 'furniture'].includes(ref.kind))) return null;
  const owners = refs.map(ref => ({ ...ref }));
  const targets = moveTargets(getPlan(), owners);
  if (!targets.length) return null;
  const children = targets.map(target => ({ label: target.label,
    disabled: target.disabled || !canEdit(), reason: target.reason,
    run: () => queue(async () => {
      if (!canEdit() || target.disabled) return;
      const plan = getPlan(), result = moveOps(plan, owners, target.key);
      if (result.refused) {
        const reasons = result.refused.map(({ ref, reason }) => {
          const piece = findPiece(plan, ref.pieceId, ref.buildingId)?.piece;
          return `${getLabel?.(ref) || piece?.name || piece?.preset || piece?.asset || ref.pieceId}: ${reason}`;
        });
        window.showGlobalAlert(`Could not move the selected pieces. ${reasons.join(' ')}`);
        return;
      }
      if (!result.ops.length) return;
      await applyBatch(result.ops, { label: `Move to ${target.label}` });
      // Choosing a floor selects that floor. Restore the moved owners afterwards.
      await chooseDestination(target.key);
      selectionStore.set(result.selection);
    }),
  }));
  return { label: 'Move to', children, disabled: children.every(child => child.disabled),
    reason: targets.every(target => target.disabled) ? targets[0].reason : undefined };
}

export function drawMoveToButton(host, options) {
  const action = () => moveToAction({ ...options, refs: options.getRefs() });
  if (!action()) return null;
  const lifecycle = new AbortController();
  const menu = createContextMenu({ signal: lifecycle.signal, label: 'Move to', items: () => action()?.children || [] });
  const button = document.createElement('button'); button.type = 'button'; button.textContent = 'Move to';
  button.setAttribute('aria-haspopup', 'menu');
  button.addEventListener('click', event => {
    const rect = button.getBoundingClientRect();
    menu.open(!event.clientX && !event.clientY ? [rect.left, rect.bottom] : event);
  });
  host.append(button);
  const row = { refresh() {
    const current = action();
    button.hidden = !current; button.disabled = !current || current.disabled;
    button.title = current?.reason || '';
    if (current?.reason) button.setAttribute('aria-description', current.reason);
    else button.removeAttribute('aria-description');
  }, dispose() { lifecycle.abort(); } };
  row.refresh(); options.ownSlot(row);
  return row;
}

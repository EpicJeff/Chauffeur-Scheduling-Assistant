import { kindOf } from '../kinds.js';
import { element, title, controlShape } from './shared.js';

export const deviceControlShape = (row, state, getEntityState) => JSON.stringify([
  kindOf(row).id, row.offered, row.accessories, controlShape(state),
  row.accessories?.map(a => controlShape(getEntityState(a.entity_id))),
]);

// Keep the primary dial intact. Its siblings use compact panel controls in the
// side card, and the very same rows below the primary in the room panel.
export function deviceControls(options) {
  const {row, surface = 'panel', compact = false, getEntityState = () => null} = options;
  const kind = kindOf(row);
  const control = (surface === 'ring' ? kind.ring || kind.panel : kind.panel)(options);
  if (compact || !row.accessories?.length) return control;
  // Keep camera error overlays confined to the still, as before.
  const primary = kind.id === 'camera' ? element('div') : control;
  if (primary !== control) {
    primary.className = 'twin-device-actions'; primary.append(control);
    primary.update = control.update; primary.stop = control.stop;
  }
  const list = element('div'); list.className = 'twin-accessories';
  let more = null;
  const widgets = row.accessories.map((accessory, index) => {
    if (index === 4) {
      more = element('details'); more.append(element('summary', 'More controls'));
      list.append(more);
    }
    const node = element('div'); node.className = 'twin-accessory';
    node.setAttribute('data-accessory', accessory.entity_id);
    const status = element('p'); node.append(status);
    const state = () => getEntityState(accessory.entity_id);
    const actions = accessory.offered ? kindOf(accessory).panel({...options, row: accessory,
      state: state(), surface: 'panel', getState: state}) : null;
    if (actions) node.append(actions);
    (more || list).append(node);
    return {update() {
      const next = state();
      status.textContent = `${accessory.name}: ${title(next?.state || 'unavailable')}`;
      actions?.update?.(next);
    }, stop() { actions?.stop?.(); }};
  });
  if (surface === 'ring' && primary.classList.contains('twin-light-controls')) {
    if (!primary.side) {
      primary.side = element('div'); primary.side.className = 'twin-ring-side';
      primary.append(primary.side);
    }
    primary.side.append(list);
  } else {
    primary.style.flexDirection = 'column'; primary.style.alignItems = 'stretch';
    primary.append(list);
  }
  const update = primary.update, stop = primary.stop;
  primary.update = state => { update?.(state); widgets.forEach(w => w.update()); };
  primary.stop = () => { stop?.(); widgets.forEach(w => w.stop()); };
  primary.update(options.state);
  return primary;
}

import { base } from '../../twin_library.js';
import { controls, element, title } from './shared.js';

const PHONE = 'Open this camera on your phone to see it.';
const UNAVAILABLE = 'Camera unavailable';
// A frame every 2 s after the last one answered; one that has not answered in this
// long has failed (review M2).
const EVERY_MS = 2000, FRAME_MS = 8000;

// The identity chfAuthUrl would put on an img's URL, carried in headers instead, so no
// token reaches the server's access log (review L5): the person when signed in on this
// page, otherwise the panel (nav's fetch wrapper adds its device token; an empty header
// keeps it off a person's request, as chfAuthUrl sends one or the other).
function identity() {
  let person = '';
  try { person = window.chfPersonToken?.() || ''; } catch { person = ''; }
  return person ? {'X-Member-Token': person, 'X-Device-Token': ''} : {};
}

// Both the marker and the room use these same labelled switches and the shared
// control sender. The frame's permission never lends permission to its siblings.
export function cameraControls(options) {
  const {row, compact = false, getEntityState = () => null} = options;
  const frame = cameraStill(options);
  if (compact || !row.accessories?.length) return frame;
  const root = element('div'); root.className = 'twin-device-actions'; root.append(frame);
  // The ring side card's vertical stack, keeping the frame above its switches.
  root.style.flexDirection = 'column'; root.style.alignItems = 'stretch';
  const widgets = row.accessories.map(accessory => {
    const state = () => getEntityState(accessory.entity_id);
    if (!accessory.offered) {
      // Read-only accessories say their state, with no inactive verbs.
      const node = element('p'); node.setAttribute('data-accessory', accessory.entity_id);
      node.update = next => { node.textContent = `${accessory.name}: ${title(next?.state || 'unavailable')}`; };
      root.append(node); return {node, state};
    }
    const c = controls({...options, row: accessory, state: state(), surface: 'panel', getState: state});
    c.root.setAttribute('data-accessory', accessory.entity_id);
    if (accessory.entity_id.startsWith('button.')) {
      c.button('press', accessory.name, 'press');
    } else {
      const service = accessory.entity_id.startsWith('siren.')
        ? s => s?.state === 'on' ? 'turn_off' : 'turn_on' : 'toggle';
      c.toggle('accessory', accessory.name, s => s?.state === 'on', service, {}, accessory.name);
    }
    c.finish();
    root.append(c.root); return {node: c.root, state};
  });
  root.update = state => { frame.update?.(state); widgets.forEach(w => w.node.update?.(w.state())); };
  root.stop = () => { frame.stop?.(); widgets.forEach(w => w.node.stop?.()); };
  root.update(options.state); return root;
}

function cameraStill({row, compact = false}) {
  const root = element('div'); root.className = 'twin-device-actions';
  root.update = () => {};
  if (compact) return root;
  const message = element('p'); message.setAttribute('role', 'status'); root.append(message);
  if (!row.offered) {
    message.textContent = 'This camera is not available here.'; return root;
  }
  const img = element('img'); img.setAttribute('data-ring-part', 'still'); img.alt = row.name;
  img.className = 'twin-camera-still'; root.append(img);
  let stopped = false, timer = null, shown = null, request = null;
  const url = base() + 'api/house/camera/' + encodeURIComponent(row.entity_id);
  const say = text => { message.textContent = text; root.toggleAttribute('data-missing', !!text); };
  const show = frame => {
    const previous = shown;
    shown = URL.createObjectURL(frame); img.src = shown;
    if (previous) URL.revokeObjectURL?.(previous);
  };
  // One frame at a time: the next is asked for 2 s after this one answered (or failed),
  // never while it is pending, so a slow camera never stacks requests on the server.
  // The answer says what happened: a refusal by the household's grid (C6: identify
  // first, which a frame cannot do) says why and stops asking; anything else is a
  // camera unavailable for now, and the refresh keeps trying.
  async function refresh() {
    timer = null;
    if (stopped) return;
    const controller = new AbortController();
    const limit = setTimeout(() => controller.abort(), FRAME_MS);
    request = controller;
    let refused = null;
    try {
      const response = await fetch(url + '?t=' + Date.now(), {cache: 'no-store', credentials: 'same-origin',
        headers: identity(), signal: controller.signal});
      if (response.ok) {
        const frame = await response.blob();
        if (!stopped) { show(frame); say(''); }
      } else if (response.status === 403) {
        const detail = (await response.json().catch(() => ({}))).detail;
        refused = typeof detail === 'string' && detail ? detail : PHONE;
      } else if (!stopped) say(UNAVAILABLE);
    } catch { if (!stopped) say(UNAVAILABLE); }
    finally { clearTimeout(limit); if (request === controller) request = null; }
    if (stopped) return;
    if (refused) { say(refused); return; }
    timer = setTimeout(refresh, EVERY_MS);
  }
  void refresh();
  root.stop = () => {
    stopped = true; clearTimeout(timer); timer = null; request?.abort(); request = null;
    if (shown) { URL.revokeObjectURL?.(shown); shown = null; }
  };
  return root;
}

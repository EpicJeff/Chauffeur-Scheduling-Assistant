import { base } from '../../twin_library.js';
import { element } from './shared.js';

const PHONE = 'Open this camera on your phone to see it.';
const UNAVAILABLE = 'Camera unavailable';

export function cameraControls({row, compact = false}) {
  const root = element('div'); root.className = 'twin-device-actions';
  root.update = () => {};
  if (compact) return root;
  const message = element('p'); message.setAttribute('role', 'status'); root.append(message);
  if (!row.offered) {
    message.textContent = 'This camera is not available here.'; return root;
  }
  const img = element('img'); img.setAttribute('data-ring-part', 'still'); img.alt = row.name;
  img.className = 'twin-camera-still'; root.append(img);
  let stopped = false, timer = null, shown = null, asked = 0;
  const url = base() + 'api/house/camera/' + encodeURIComponent(row.entity_id);
  const signed = path => window.chfAuthUrl ? window.chfAuthUrl(path) : path;
  const say = text => { message.textContent = text; root.toggleAttribute('data-missing', !!text); };
  // A frame read by hand (below) is shown from memory; the next refresh lets it go.
  const forget = () => { if (shown) { URL.revokeObjectURL?.(shown); shown = null; } };
  const refresh = (fresh = true) => {
    if (stopped) return;
    img.src = signed(url + (fresh ? '?t=' + Date.now() : ''));
    forget();
  };
  // An img's error cannot tell a refusal from a missing frame, so the route is asked once more
  // and its answer read: a refusal by the household's grid (C6: identify first, which an img
  // cannot do) sends the person to their phone and stops asking; anything else is a camera
  // that is unavailable for now, and the refresh keeps trying.
  img.addEventListener('error', async () => {
    if (stopped) return;
    const mine = ++asked;
    let status = 0, detail = '', frame = null;
    try {
      const response = await fetch(signed(url + '?t=' + Date.now()), {cache: 'no-store', credentials: 'same-origin'});
      status = response.status;
      if (response.ok) frame = await response.blob();
      else detail = (await response.json().catch(() => ({}))).detail;
    } catch { /* unreachable: the camera is unavailable */ }
    if (stopped || mine !== asked) return;
    if (status === 403) {
      clearInterval(timer); timer = null;
      say(typeof detail === 'string' && detail ? detail : PHONE);
    } else if (frame && URL.createObjectURL) {
      forget(); shown = URL.createObjectURL(frame); img.src = shown;
    } else say(UNAVAILABLE);
  });
  img.addEventListener('load', () => { say(''); });
  refresh(false); timer = setInterval(refresh, 2000);
  root.stop = () => { stopped = true; clearInterval(timer); forget(); };
  return root;
}

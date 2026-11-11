import { base } from '../../twin_library.js';
import { element } from './shared.js';

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
  let stopped = false, timer = null;
  const url = base() + 'api/house/camera/' + encodeURIComponent(row.entity_id);
  const refresh = (fresh = true) => {
    if (stopped) return;
    const path = url + (fresh ? '?t=' + Date.now() : '');
    img.src = window.chfAuthUrl ? window.chfAuthUrl(path) : path;
  };
  img.addEventListener('error', () => {
    // An image cannot carry the identify/PIN flow (C6). Keep a useful phone path;
    // subsequent refreshes also let a transient HA outage recover without reopening.
    message.textContent = 'Open this camera on your phone to see it.';
  });
  img.addEventListener('load', () => { message.textContent = ''; });
  refresh(false); timer = setInterval(refresh, 2000);
  root.stop = () => { stopped = true; clearInterval(timer); };
  return root;
}

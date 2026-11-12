import { glanceValue, humanise } from './glance.js';
import { svgIcon } from './glance_icons.js';

export function weatherConditionIcon(condition) {
  return ({sunny: 'sun', 'clear-night': 'moon', partlycloudy: 'cloud-sun', cloudy: 'cloud',
    rainy: 'cloud-rain', pouring: 'cloud-rain-wind', snowy: 'cloud-snow', 'snowy-rainy': 'cloud-snow',
    fog: 'cloud-fog', windy: 'wind', 'windy-variant': 'wind', lightning: 'cloud-lightning',
    'lightning-rainy': 'cloud-lightning', hail: 'cloud-drizzle', exceptional: 'cloud'})[condition] || 'cloud';
}
export function renderIdleWeather(host, states, entity, stale = false) {
  // Same selection as home_board.current_conditions (the photo screensaver):
  // the household setting wins; otherwise the first weather entity, never a forecast.
  const weather = Object.keys(states).filter(id => id.startsWith('weather.'));
  const name = id => (states[id]?.attributes?.friendly_name || id).toLowerCase();
  weather.sort((a, b) => name(a) < name(b) ? -1 : name(a) > name(b) ? 1 : 0);
  const id = entity || weather[0], row = states[id];
  const key = JSON.stringify([id, row, stale]);
  if (host.dataset.weather === key) return;
  host.dataset.weather = key; host.replaceChildren();
  host.hidden = !row || stale || ['unavailable', 'unknown', ''].includes(row.state);
  if (host.hidden) return;
  const reading = document.createElement('div'); reading.className = 'twin-weather-reading';
  const value = document.createElement('strong'); value.textContent = glanceValue(id, row, false, states);
  reading.append(svgIcon(weatherConditionIcon(row.state), row.state === 'sunny' ? '#facc62' : '#d1d9e6'), value);
  const condition = document.createElement('small'); condition.textContent = humanise(row.state); condition.dataset.weatherCondition = '';
  host.append(reading, condition);
}

// The orbit changes camera matrices directly, without OrbitControls change events.
// These are presentation frames: the baker's human-idle clock stays untouched.
export function mountIdle(view, glance, {enabled = false, timeout = 60000,
  api = path => fetch(window.chfBase + path), clock = window.chfGlanceClock,
  hero = window.HeroCard, now = () => performance.now()} = {}) {
  const root = document.getElementById('twin-idle'), card = document.getElementById('twin-idle-clock');
  const home = document.getElementById('twin-glance-home'), nextHost = document.getElementById('twin-idle-next');
  const halt = new AbortController();
  window._chfTwinIdleEnabled = enabled;
  let active = false, saved = null, offset = null, previousEnabled = true, start = 0, timer = null;
  let next = null, fetched = 0, lastSecond = -1, busy = false, stopped = false, weatherEntity = null;
  const arm = () => { clearTimeout(timer); if (enabled && !document.hidden && !stopped) timer = setTimeout(enter, timeout); };
  async function fetchHero() {
    if (busy || stopped) return;
    busy = true; fetched = Date.now();
    try {
      const r = await api('api/home_board');
      if (r.ok) { const h = (await r.json()).hero; next = h && !h.all_done ? h.next : null; }
    } catch { /* No board or HA is a valid idle face. */ }
    finally { busy = false; }
  }
  function enter() {
    if (!enabled || active || stopped || !view.ready || document.hidden) { arm(); return; }
    saved = view.saveView(); previousEnabled = view.controls.enabled;
    active = true; window._chfTwinIdleActive = true;
    view.controls.enabled = false; view.live?.closeRoom();
    view.setTime('now');
    view.setView('ext'); view.setCamera('front');
    offset = view.camera.position.clone().sub(view.controls.target); start = now();
    root.hidden = false; glance.move(card); document.documentElement.setAttribute('data-twin-idle', '');
    fetchHero(); frame(now());
  }
  function wake() {
    if (!active) return;
    active = false; window._chfTwinIdleActive = false;
    root.hidden = true; document.documentElement.removeAttribute('data-twin-idle'); glance.move(home);
    view.restoreView(saved); view.setTime(saved.state.time); view.controls.enabled = previousEnabled; saved = null;
    document.querySelectorAll('[data-view], [data-camera]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.view ? b.dataset.view === view.state.view : b.dataset.camera === view.state.camera)));
  }
  function frame(at) {
    if (!active) return;
    const angle = (at - start) * .000018, c = Math.cos(angle), s = Math.sin(angle);
    view.camera.position.set(view.controls.target.x + offset.x * c - offset.z * s,
      view.controls.target.y + offset.y, view.controls.target.z + offset.x * s + offset.z * c);
    view.camera.lookAt(view.controls.target);
    const second = Math.floor(Date.now() / 1000);
    if (second !== lastSecond) {
      lastSecond = second; clock?.(card);
      renderIdleWeather(document.getElementById('twin-idle-weather'), view.live?.peek() || {}, weatherEntity, view.live?.stale());
      const show = next && (!next.end || Date.now() < new Date(next.end).getTime());
      nextHost.hidden = !show;
      if (show && hero) nextHost.innerHTML = hero.html(next, {compact: true});
      if (Date.now() - fetched > 180000) fetchHero();
    }
  }
  function activity(event) {
    const waking = active;
    wake(); arm();
    // The waking gesture restores the view; it must not also actuate a device
    // or start an OrbitControls drag on the newly restored camera.
    if (waking) { event.preventDefault(); event.stopImmediatePropagation(); }
  }
  for (const name of ['pointerdown', 'pointermove', 'touchstart', 'keydown', 'wheel'])
    window.addEventListener(name, activity, {capture: true, passive: false, signal: halt.signal});
  document.addEventListener('visibilitychange', () => { wake(); arm(); }, {signal: halt.signal});
  arm();
  return {frame, active: () => active, wake,
    configure(value, entity = weatherEntity) { weatherEntity = entity; if (enabled === value) return; enabled = value; window._chfTwinIdleEnabled = enabled; if (!enabled) wake(); arm(); },
    stop() { stopped = true; wake(); window._chfTwinIdleEnabled = false; clearTimeout(timer); halt.abort(); },
  };
}

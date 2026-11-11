const element = (tag, text) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  return node;
};
const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
const COLOURS = [['Red', [255, 0, 0]], ['Amber', [255, 191, 0]], ['Green', [0, 255, 0]],
  ['Blue', [0, 0, 255]], ['Purple', [128, 0, 255]]];
const SVG = 'http://www.w3.org/2000/svg';
function hueSat(attrs) {
  if (Array.isArray(attrs.hs_color)) return [...attrs.hs_color];
  const rgb = (attrs.rgb_color || [255, 255, 255]).map(v => v / 255);
  const [r, g, b] = rgb, max = Math.max(...rgb), delta = max - Math.min(...rgb);
  const hue = !delta ? 0 : max === r ? ((g - b) / delta + 6) % 6 : max === g ? (b - r) / delta + 2 : (r - g) / delta + 4;
  return [hue * 60, max ? delta / max * 100 : 0];
}

// Both surfaces use these capabilities, values and service calls. Only their handles differ:
// arcs around the marker, native ranges in the room's expanded row.
export function lightControls({row, state, control, compact = false, surface = 'panel', getState}) {
  const ring = surface === 'ring', actions = element('div'); actions.className = 'twin-device-actions';
  if (!ring && (!row.offered || compact)) return actions;
  if (ring) actions.className += ' twin-light-controls';
  let confirmed = state, disposed = false;
  const updates = [], stops = [];
  const attrs = state?.attributes || {}, modes = attrs.supported_color_modes;
  const light = row.kind === 'light';
  const dimmable = light && (Array.isArray(modes) ? modes.some(mode => mode !== 'onoff') : true);
  const temperature = light && modes?.includes('color_temp');
  const colour = light && modes?.some(mode => ['hs', 'rgb', 'xy', 'rgbw', 'rgbww'].includes(mode));
  const part = (node, name) => { if (ring) node.setAttribute('data-ring-part', name); return node; };
  const update = next => { confirmed = next; for (const fn of updates) fn(); };
  async function send(service, data = {}) {
    if (disposed || !row.offered) return false;
    return control(row.entity_id, service, data);
  }
  const button = (label, service, data = {}) => {
    const node = element('button', label); node.type = 'button'; node.disabled = !row.offered;
    node.addEventListener('click', async () => {
      if (node.disabled || disposed || !row.offered) return;
      node.disabled = true;
      try { await send(service, data); }
      finally {
        node.disabled = !row.offered;
        if (getState && !disposed) update(getState());
      }
    });
    actions.append(node); return node;
  };
  const toggle = part(button(state?.state === 'on' ? 'On' : 'Off', 'toggle'), 'center');
  toggle.setAttribute('role', 'switch'); toggle.setAttribute('aria-label', row.name);
  updates.push(() => {
    toggle.textContent = confirmed?.state === 'on' ? 'On' : 'Off';
    toggle.setAttribute('aria-checked', String(confirmed?.state === 'on'));
  });

  function slider(name, label, min, max, step, valueOf, serviceKey, lower = false) {
    let node, readout, progress, handle, dragging = null, timer = null, editing = false, sending = false;
    if (ring) {
      const svg = document.createElementNS(SVG, 'svg'); svg.setAttribute('viewBox', '0 0 280 280');
      svg.setAttribute('class', 'twin-light-arc');
      node = document.createElementNS(SVG, 'path');
      node.setAttribute('d', lower ? 'M 50 140 A 90 90 0 0 0 230 140' : 'M 50 140 A 90 90 0 0 1 230 140');
      node.setAttribute('role', 'slider'); node.setAttribute('tabindex', row.offered ? '0' : '-1');
      node.setAttribute('aria-disabled', String(!row.offered));
      node.setAttribute('aria-valuemin', String(min)); node.setAttribute('aria-valuemax', String(max));
      progress = document.createElementNS(SVG, 'path'); progress.setAttribute('d', node.getAttribute('d'));
      progress.setAttribute('pathLength', '100'); progress.setAttribute('class', 'twin-light-progress');
      handle = document.createElementNS(SVG, 'circle'); handle.setAttribute('r', '8'); handle.setAttribute('class', 'twin-light-handle');
      svg.append(node, progress, handle); actions.append(svg); part(node, name);
      readout = element('output'); readout.className = `twin-light-value twin-light-${name}`; actions.append(readout);
    } else {
      const wrap = element('label', label); node = element('input');
      node.type = 'range'; node.min = String(min); node.max = String(max); node.step = String(step);
      node.disabled = !row.offered; wrap.append(node); actions.append(wrap);
    }
    node.setAttribute('aria-label', `${row.name} ${name}`);
    const show = value => {
      node.value = String(value);
      if (ring) {
        node.setAttribute('aria-valuenow', String(value));
        node.setAttribute('aria-valuetext', `${value}${name === 'brightness' ? '%' : ' K'}`);
        const ratio = max > min ? (value - min) / (max - min) : 0, angle = ratio * Math.PI;
        progress.setAttribute('stroke-dasharray', `${ratio * 100} 100`);
        handle.setAttribute('cx', String(140 - Math.cos(angle) * 90));
        handle.setAttribute('cy', String(140 + (lower ? 1 : -1) * Math.sin(angle) * 90));
        readout.textContent = `${label} ${value}${name === 'brightness' ? '%' : ' K'}`;
      }
    };
    const restore = () => { if (!editing && !sending) show(valueOf(confirmed?.attributes || {})); };
    updates.push(restore);
    async function commit() {
      clearTimeout(timer); timer = null;
      if (disposed || !row.offered) return;
      const chosen = Number(node.value); sending = true; editing = false;
      node.disabled = true;
      try {
        const ok = await send('turn_on', {[serviceKey]: chosen});
        if (getState) confirmed = getState();
        else if (ok) confirmed = {...confirmed, attributes: {...confirmed?.attributes,
          [name === 'brightness' ? 'brightness' : 'color_temp_kelvin']: name === 'brightness' ? chosen * 255 / 100 : chosen}};
      } finally { sending = false; node.disabled = !row.offered; if (!disposed) restore(); }
    }
    const schedule = () => { clearTimeout(timer); timer = setTimeout(() => { void commit(); }, 200); };
    const choose = value => {
      if (disposed || !row.offered || sending) return;
      editing = true; clearTimeout(timer);
      show(clamp(Math.round(value / step) * step, min, max));
    };
    if (ring) {
      node.addEventListener('keydown', event => {
        if (!row.offered || sending) return;
        const value = Number(node.value), keys = {ArrowUp: value + step, ArrowRight: value + step,
          ArrowDown: value - step, ArrowLeft: value - step, Home: min, End: max,
          PageUp: value + step * 10, PageDown: value - step * 10};
        if (!(event.key in keys)) return;
        event.preventDefault(); choose(keys[event.key]); schedule();
      });
      const move = event => {
        const bounds = actions.getBoundingClientRect();
        const x = event.clientX - bounds.left - 140, y = event.clientY - bounds.top - 140;
        const angle = Math.atan2(Math.max(0, lower ? y : -y), -x);
        choose(min + angle / Math.PI * (max - min));
      };
      node.addEventListener('pointerdown', event => {
        if (!row.offered || sending || event.button > 0) return;
        event.preventDefault(); dragging = event.pointerId; node.setPointerCapture?.(dragging); move(event);
      });
      node.addEventListener('pointermove', event => { if (event.pointerId === dragging) move(event); });
      node.addEventListener('pointerup', event => {
        if (event.pointerId !== dragging) return;
        move(event); node.releasePointerCapture?.(dragging); dragging = null; schedule();
      });
      node.addEventListener('pointercancel', () => {
        dragging = null; editing = false; clearTimeout(timer); restore();
      });
    } else {
      node.addEventListener('input', () => { choose(Number(node.value)); });
      node.addEventListener('change', () => { if (row.offered) void commit(); });
    }
    stops.push(() => clearTimeout(timer));
  }
  if (dimmable) slider('brightness', 'Brightness', 0, 100, 1,
    a => Math.round((a.brightness ?? 0) / 255 * 100), 'brightness_pct');
  if (temperature) {
    const min = attrs.min_color_temp_kelvin || (attrs.max_mireds ? Math.round(1e6 / attrs.max_mireds) : 2000);
    const max = attrs.max_color_temp_kelvin || (attrs.min_mireds ? Math.round(1e6 / attrs.min_mireds) : 6500);
    slider('temperature', 'Temperature', min, max, 1,
      a => clamp(a.color_temp_kelvin ?? (a.color_temp ? Math.round(1e6 / a.color_temp) : min), min, max), 'color_temp_kelvin', true);
  }
  if (colour) {
    const swatches = part(element('div'), 'swatches'); swatches.className = 'twin-light-swatches';
    for (const [name, rgb] of COLOURS) {
      const node = button(name, 'turn_on', {rgb_color: rgb}); node.setAttribute('aria-label', name);
      node.style.background = `rgb(${rgb.join(',')})`; swatches.append(node);
    }
    actions.append(swatches);
    const label = element('div', 'Colour'), wheel = part(element('div'), 'wheel');
    wheel.className = 'twin-colour-wheel'; wheel.setAttribute('role', 'slider');
    wheel.setAttribute('tabindex', row.offered ? '0' : '-1'); wheel.setAttribute('aria-disabled', String(!row.offered));
    wheel.setAttribute('aria-label', `${row.name} colour`); wheel.setAttribute('aria-valuemin', '0'); wheel.setAttribute('aria-valuemax', '360');
    wheel.setAttribute('aria-description', 'Arrow keys choose hue. Hold Shift to choose saturation.');
    const dot = element('span'); dot.setAttribute('aria-hidden', 'true'); wheel.append(dot);
    let hs = hueSat(attrs), dragging = null, timer = null, choosing = false, sending = false;
    const show = () => {
      const angle = hs[0] * Math.PI / 180, radius = hs[1] * .44;
      dot.style.left = `${50 + Math.sin(angle) * radius}%`; dot.style.top = `${50 - Math.cos(angle) * radius}%`;
      wheel.setAttribute('aria-valuenow', String(Math.round(hs[0])));
      wheel.setAttribute('aria-valuetext', `${Math.round(hs[0])} degrees, ${Math.round(hs[1])}% saturation`);
    };
    const restore = () => { if (!choosing && !sending) { hs = hueSat(confirmed?.attributes || {}); show(); } };
    async function commitColour() {
      if (disposed || !row.offered) return;
      choosing = false; sending = true;
      try { await send('turn_on', {hs_color: hs.map(Math.round)}); }
      finally { sending = false; if (getState) confirmed = getState(); if (!disposed) restore(); }
    }
    const schedule = () => { clearTimeout(timer); timer = setTimeout(() => { void commitColour(); }, 200); };
    const move = event => {
      const rect = wheel.getBoundingClientRect(), radius = Math.max(1, rect.width / 2);
      const x = event.clientX - rect.left - radius, y = event.clientY - rect.top - rect.height / 2;
      hs = [(Math.atan2(x, -y) * 180 / Math.PI + 360) % 360, clamp(Math.hypot(x, y) / radius * 100, 0, 100)];
      choosing = true; clearTimeout(timer); show();
    };
    wheel.addEventListener('pointerdown', event => {
      if (!row.offered || sending || event.button > 0) return;
      event.preventDefault(); dragging = event.pointerId; wheel.setPointerCapture?.(dragging); move(event);
    });
    wheel.addEventListener('pointermove', event => { if (event.pointerId === dragging) move(event); });
    wheel.addEventListener('pointerup', event => {
      if (event.pointerId !== dragging) return;
      move(event); wheel.releasePointerCapture?.(dragging); dragging = null; schedule();
    });
    wheel.addEventListener('pointercancel', () => { dragging = null; choosing = false; clearTimeout(timer); restore(); });
    wheel.addEventListener('keydown', event => {
      if (!row.offered || sending || !['ArrowUp', 'ArrowRight', 'ArrowDown', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault(); choosing = true;
      const i = event.shiftKey ? 1 : 0, max = i ? 100 : 360;
      hs[i] = event.key === 'Home' ? 0 : event.key === 'End' ? max :
        clamp(hs[i] + (['ArrowUp', 'ArrowRight'].includes(event.key) ? 1 : -1), 0, max);
      show(); schedule();
    });
    updates.push(restore); stops.push(() => clearTimeout(timer));
    label.className = 'twin-light-wheel'; label.append(wheel); actions.append(label);
  }
  if (light && attrs.effect_list?.length) {
    const effects = part(element('div'), 'effects'); effects.className = 'twin-light-effects';
    for (const effect of attrs.effect_list) {
      const node = button(effect, 'turn_on', {effect}); effects.append(node);
      updates.push(() => node.setAttribute('aria-pressed', String(confirmed?.attributes?.effect === effect)));
    }
    actions.append(effects);
  }
  actions.update = update;
  actions.stop = () => { disposed = true; for (const stop of stops) stop(); };
  update(state);
  return actions;
}

import { controls, element, glyph, clamp, figure, title, known, holdsRange, SVG } from './shared.js';

// HA's thermostat card at the marker: one 270-degree arc open at the bottom, a handle for the
// setpoint (two for heat_cool), the arc filled in the mode's colour, a dot at the current
// temperature, and in the middle what the system is doing, the setpoint large and the room's
// temperature under it; minus and plus sit in the arc's opening. The dial, its 44 px arc and
// its handles are the light ring's (controls/light.js); modes, fan and presets are the side card.
const SWEEP = 270, START = 135, R = 90;
const at = t => {
  const angle = (START + SWEEP * clamp(t, 0, 1)) * Math.PI / 180;
  return [140 + R * Math.cos(angle), 140 + R * Math.sin(angle)];
};
const TRACK = (() => {
  const [[x0, y0], [x1, y1]] = [at(0), at(1)].map(p => p.map(v => v.toFixed(2)));
  return `M ${x0} ${y0} A ${R} ${R} 0 1 1 ${x1} ${y1}`;
})();
let gradients = 0;

export function climateControls(options) {
  const c = controls(options), a = c.attrs;
  const min = Number(a.min_temp ?? 0), max = Number(a.max_temp ?? 100), step = Number(a.target_temp_step) || 1;
  const range = holdsRange(options.state);
  const single = !range && (c.has(1) || Number.isFinite(a.temperature));
  if (!c.ring) return panel(c, options, {min, max, step, range, single});

  const root = c.root, enabled = c.enabled;
  root.classList.add('twin-dial-thermostat');
  const svg = document.createElementNS(SVG, 'svg'); svg.setAttribute('viewBox', '0 0 280 280');
  svg.setAttribute('class', 'twin-light-arc twin-thermostat-arc');
  const track = document.createElementNS(SVG, 'path'); track.setAttribute('d', TRACK);
  track.setAttribute('class', 'twin-thermostat-track'); track.setAttribute('aria-hidden', 'true');
  const fill = document.createElementNS(SVG, 'path'); fill.setAttribute('d', TRACK);
  fill.setAttribute('pathLength', '100'); fill.setAttribute('class', 'twin-light-progress');
  // Warm at the low end to cool at the high end, the light ring's kelvin colours.
  const id = `twin-thermostat-${++gradients}`, defs = document.createElementNS(SVG, 'defs');
  const gradient = document.createElementNS(SVG, 'linearGradient');
  gradient.setAttribute('id', id); gradient.setAttribute('gradientUnits', 'userSpaceOnUse');
  for (const [key, value] of [['x1', '28'], ['y1', '0'], ['x2', '252'], ['y2', '0']]) gradient.setAttribute(key, value);
  for (const [offset, colour] of [['0', '#ff9d3c'], ['1', '#7fb0ff']]) {
    const stop = document.createElementNS(SVG, 'stop');
    stop.setAttribute('offset', offset); stop.setAttribute('stop-color', colour); gradient.append(stop);
  }
  defs.append(gradient);
  const now = document.createElementNS(SVG, 'circle'); now.setAttribute('r', '4'); now.setAttribute('class', 'twin-thermostat-now');
  svg.append(defs, track, fill, now); root.append(svg);

  const centre = element('div'); centre.className = 'twin-thermostat-centre'; root.append(centre);
  const action = c.part(element('p'), 'action'); action.className = 'twin-thermostat-action';
  const big = element('div'); big.className = 'twin-thermostat-target';
  const current = c.part(element('p'), 'current'); current.className = 'twin-thermostat-current';
  centre.append(action, big, current);

  const steps = [];
  // One handle per setpoint: each is a slider (keys move it), the track takes the finger.
  const handles = [];
  function handle(name, label, valueOf, dataOf) {
    const node = document.createElementNS(SVG, 'circle'); node.setAttribute('r', '8');
    node.setAttribute('class', 'twin-light-handle twin-thermostat-handle'); c.part(node, name);
    node.setAttribute('role', 'slider'); node.setAttribute('tabindex', enabled ? '0' : '-1');
    node.setAttribute('aria-disabled', String(!enabled)); node.setAttribute('aria-label', `${options.row.name} ${label}`);
    node.setAttribute('aria-valuemin', String(min)); node.setAttribute('aria-valuemax', String(max));
    svg.append(node);
    const readout = range ? element('button') : element('output');
    if (range) {
      readout.type = 'button'; readout.disabled = !enabled; 
      readout.addEventListener('click', () => { if (enabled) select(h); });
    }
    big.append(readout);
    const h = {name, node, readout, valueOf, dataOf, value: null, editing: false, sending: 0, timer: null};
    handles.push(h); return h;
  }
  if (range) {
    handle('target-low', 'Low', s => s?.attributes?.target_temp_low,
      (v, s) => ({target_temp_low: Math.min(v, s.attributes.target_temp_high), target_temp_high: s.attributes.target_temp_high}));
    handle('target-high', 'High', s => s?.attributes?.target_temp_high,
      (v, s) => ({target_temp_low: s.attributes.target_temp_low, target_temp_high: Math.max(v, s.attributes.target_temp_low)}));
  } else if (single) handle('target', 'Target', s => s?.attributes?.temperature, v => ({temperature: v}));
  let chosen = handles[0] || null;
  function select(h) {
    chosen = h;
    for (const other of handles) if (range) other.readout.setAttribute('aria-pressed', String(other === h));
  }
  if (chosen) select(chosen);

  const off = () => c.confirmed()?.state === 'off';
  const snap = value => clamp(Number((min + Math.round((value - min) / step) * step).toFixed(3)), min, max);
  const ratio = value => max > min ? (value - min) / (max - min) : 0;
  function paint() {
    const s = c.confirmed(), isOff = off(), mode = s?.state;
    for (const h of handles) {
      const value = clamp(Number(h.value) || 0, min, max), [x, y] = at(ratio(value));
      h.node.setAttribute('aria-valuenow', String(value)); h.node.setAttribute('aria-valuetext', `${figure(value)}°`);
      h.node.setAttribute('cx', x.toFixed(2)); h.node.setAttribute('cy', y.toFixed(2));
      h.node.style.visibility = isOff || !known(h.value) ? 'hidden' : 'visible';
      h.readout.textContent = known(h.value) ? `${figure(value)}°` : '—';
      if (range) h.readout.setAttribute('aria-label', `${h.name === 'target-low' ? 'Low' : 'High'} ${h.readout.textContent}`);
      h.readout.hidden = isOff;
    }
    // Off reads as Off, the way HA's card shows it; the setpoint stays where it was.
    big.toggleAttribute('data-off', isOff);
    let offText = big.querySelector('.twin-thermostat-off');
    if (isOff && !offText) { offText = element('span', 'Off'); offText.className = 'twin-thermostat-off'; big.append(offText); }
    if (!isOff) offText?.remove();
    root.toggleAttribute('data-off', isOff);
    // The fill: up to the setpoint when heating, from it when cooling, between the two for a range.
    let from = 0, to = 0, colour = '#e3d3ab';
    if (!isOff && handles.length && handles.every(h => known(h.value))) {
      const [lo, hi] = handles.map(h => ratio(clamp(Number(h.value), min, max)));
      if (range) { from = lo; to = hi; colour = `url(#${id})`; }
      else if (mode === 'cool') { from = lo; to = 1; colour = '#7fb0ff'; }
      else if (['heat', 'auto', 'heat_cool'].includes(mode)) { from = 0; to = lo; colour = mode === 'heat' ? '#ff9d3c' : '#e3d3ab'; }
      else { from = 0; to = lo; }
    }
    fill.setAttribute('stroke-dasharray', `${(to - from) * 100} 100`);
    fill.setAttribute('stroke-dashoffset', String(-from * 100));
    fill.style.stroke = colour; fill.style.visibility = to - from > 0 ? 'visible' : 'hidden';
    const room = Number(s?.attributes?.current_temperature);
    if (Number.isFinite(room) && room >= min && room <= max) {
      const [x, y] = at(ratio(room)); now.setAttribute('cx', x.toFixed(2)); now.setAttribute('cy', y.toFixed(2));
      now.style.visibility = 'visible';
    } else now.style.visibility = 'hidden';
    // Off says Off once, in the middle; otherwise what the system is doing now.
    action.textContent = isOff ? '' : title(s?.attributes?.hvac_action || mode || 'unavailable');
    current.textContent = Number.isFinite(room) ? `Currently ${figure(room)}°` : 'Currently —';
    for (const node of steps) node.disabled = !enabled || isOff || !chosen;
  }
  function restore() {
    for (const h of handles) if (!h.editing && !h.sending) h.value = h.valueOf(c.confirmed());
    paint();
  }
  // A handle takes a new drag while its last value is being sent (Ruling C10): live.control
  // sends the newest once the first has answered.
  function choose(h, value) {
    if (!enabled || c.disposed() || off()) return;
    // A range never crosses: the low handle stops at the high one and the other way round.
    const other = handles.find(o => o !== h);
    if (other && known(other.value))
      value = h.name === 'target-low' ? Math.min(value, Number(other.value)) : Math.max(value, Number(other.value));
    h.editing = true; clearTimeout(h.timer); h.value = snap(value); select(h); paint();
  }
  async function commit(h) {
    clearTimeout(h.timer); h.timer = null;
    if (!enabled || c.disposed() || !h.editing) return;
    const value = Number(h.value); h.editing = false; h.sending++;
    try { await c.send('set_temperature', h.dataOf(value, c.confirmed())); }
    finally { h.sending--; if (!c.disposed()) restore(); }
  }
  const schedule = (h, wait = 200) => { clearTimeout(h.timer); h.timer = setTimeout(() => { void commit(h); }, wait); };
  for (const h of handles) {
    h.node.addEventListener('keydown', event => {
      if (!enabled) return;
      const value = Number(h.value), keys = {ArrowUp: value + step, ArrowRight: value + step,
        ArrowDown: value - step, ArrowLeft: value - step, Home: min, End: max,
        PageUp: value + 10 * step, PageDown: value - 10 * step};
      if (!(event.key in keys)) return;
      event.preventDefault(); choose(h, keys[event.key]); schedule(h);
    });
    c.onStop(() => clearTimeout(h.timer));
  }
  // The finger's angle around the dial's centre picks the value; in the opening at the bottom
  // it holds at the nearer end. A range moves whichever handle is nearer where the finger lands.
  const valueAt = event => {
    const box = svg.getBoundingClientRect(), bounds = root.getBoundingClientRect();
    const cx = box.width ? box.left + box.width / 2 : bounds.left + 140;
    const cy = box.width ? box.top + box.height / 2 : bounds.top + 140;
    const degrees = Math.atan2(event.clientY - cy, event.clientX - cx) * 180 / Math.PI;
    const along = ((degrees - START) % 360 + 360) % 360;
    const t = along <= SWEEP ? along / SWEEP : along < SWEEP + (360 - SWEEP) / 2 ? 1 : 0;
    return min + t * (max - min);
  };
  let dragging = null, held = null;
  track.addEventListener('pointerdown', event => {
    if (!enabled || event.button > 0 || off() || !handles.length) return;
    const value = valueAt(event);
    const candidates = handles.filter(h => known(h.value) || handles.length === 1);
    if (!candidates.length) return;
    held = candidates.reduce((best, h) => Math.abs(Number(h.value) - value) < Math.abs(Number(best.value) - value) ? h : best);
    event.preventDefault(); dragging = event.pointerId; track.setPointerCapture?.(dragging); choose(held, value);
  });
  track.addEventListener('pointermove', event => { if (dragging === event.pointerId && held) choose(held, valueAt(event)); });
  track.addEventListener('pointerup', event => {
    if (dragging !== event.pointerId || !held) return;
    choose(held, valueAt(event)); track.releasePointerCapture?.(dragging); dragging = null; schedule(held); held = null;
  });
  track.addEventListener('pointercancel', () => {
    if (held) { held.editing = false; clearTimeout(held.timer); }
    dragging = null; held = null; restore();
  });

  // Minus and plus in the arc's opening: a step of the chosen setpoint each, sent once the
  // taps stop (a little longer than a drag's pause, so a run of taps is one call).
  const stepsRow = element('div'); stepsRow.className = 'twin-thermostat-steps';
  for (const [name, label, icon, delta] of [['step-down', 'Lower', 'minus', -step], ['step-up', 'Raise', 'plus', step]]) {
    const node = c.part(element('button'), name); node.type = 'button'; node.disabled = !enabled;
    node.className = 'twin-ring-round'; node.setAttribute('aria-label', label); node.append(glyph(icon));
    node.addEventListener('click', () => {
      if (!enabled || node.disabled || !chosen || !known(chosen.value)) return;
      choose(chosen, Number(chosen.value) + delta); schedule(chosen, 800);
    });
    steps.push(node); stepsRow.append(node);
  }
  if (handles.length) root.append(stepsRow);

  c.watch(() => restore());
  c.chips('modes', 'Mode', a.hvac_modes, s => s?.state, 'set_hvac_mode', 'hvac_mode');
  if (c.has(8)) c.chips('fan-modes', 'Fan', a.fan_modes, s => s?.attributes?.fan_mode, 'set_fan_mode', 'fan_mode');
  if (c.has(16)) c.chips('presets', 'Preset', a.preset_modes, s => s?.attributes?.preset_mode, 'set_preset_mode', 'preset_mode');
  return c.finish();
}

// The room's row: native ranges with the same values and calls, Lower and Raise beside a
// single setpoint, then the room's temperature, what the system is doing, and the chips.
function panel(c, options, {min, max, step, range, single}) {
  const a = c.attrs;
  if (range) {
    c.slider('target-low', 'Low', min, max, step, s => s?.attributes?.target_temp_low, 'set_temperature',
      (v, s) => ({target_temp_low: Math.min(v, s.attributes.target_temp_high), target_temp_high: s.attributes.target_temp_high}));
    c.slider('target-high', 'High', min, max, step, s => s?.attributes?.target_temp_high, 'set_temperature',
      (v, s) => ({target_temp_low: s.attributes.target_temp_low, target_temp_high: Math.max(v, s.attributes.target_temp_low)}), true);
  } else if (single) {
    c.slider('target', 'Target', min, max, step, s => s?.attributes?.temperature, 'set_temperature', v => ({temperature: v}));
    if (!options.compact) {
      for (const [label, delta] of [['Lower', -step], ['Raise', step]]) {
        const node = c.button(label.toLowerCase(), label, 'set_temperature', s => {
          const value = Number((s.attributes.temperature + delta).toFixed(3));
          return value >= min && value <= max ? {temperature: value} : null;
        }, c.root);
        c.watch(s => { node.disabled = !options.row.offered || !Number.isFinite(s?.attributes?.temperature)
          || s.attributes.temperature + delta < min || s.attributes.temperature + delta > max; });
      }
    }
  }
  c.text('current', s => `Current ${s?.attributes?.current_temperature ?? '—'}`, c.root);
  c.text('action', s => s?.attributes?.hvac_action || 'idle', c.root);
  c.chips('modes', 'Mode', a.hvac_modes, s => s?.state, 'set_hvac_mode', 'hvac_mode');
  if (c.has(8)) c.chips('fan-modes', 'Fan', a.fan_modes, s => s?.attributes?.fan_mode, 'set_fan_mode', 'fan_mode');
  if (c.has(16)) c.chips('presets', 'Preset', a.preset_modes, s => s?.attributes?.preset_mode, 'set_preset_mode', 'preset_mode');
  return c.finish();
}

import { confirmUnsafe } from '../kinds.js';

export const element = (tag, text) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  return node;
};
export const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
const normal = value => String(value ?? '').toLowerCase().replace(/[\s_-]+/g, '');
// HA's own values in sentence case: heat_cool reads "Heat cool", armed_away "Armed away".
export const title = value => String(value ?? '').replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase());
// A number as a person reads it: no trailing zeros, at most one decimal (a 0.5 step shows 29.5).
export const figure = value => String(Number(Number(value).toFixed(1)));
export const SVG = 'http://www.w3.org/2000/svg';
// The two arcs stop 20 degrees short of the horizontal on each side, so their round ends never
// touch and a finger at the side of the ring lands on one arc, not both.
const GAP = Math.PI / 9;
let gradients = 0;
const point = (t, lower) => {
  const phi = Math.PI - GAP - t * (Math.PI - 2 * GAP);
  return [140 + 90 * Math.cos(phi), 140 + (lower ? 1 : -1) * 90 * Math.sin(phi)];
};
const arcPath = lower => {
  const [[x0, y0], [x1, y1]] = [point(0, lower), point(1, lower)].map(p => p.map(v => v.toFixed(2)));
  return `M ${x0} ${y0} A 90 90 0 0 ${lower ? 0 : 1} ${x1} ${y1}`;
};

// The ring's small glyphs (24 px viewBox, a 2 px white stroke like the marker icons).
const GLYPHS = {
  up: 'M6 15l6-6 6 6', down: 'M6 9l6 6 6-6', stop: 'M7 7h10v10H7z',
  play: 'M8 5v14l11-7z', pause: 'M8 5v14M16 5v14', previous: 'M18 6v12l-9-6zM6 6v12', next: 'M6 6v12l9-6zM18 6v12',
  minus: 'M6 12h12', plus: 'M6 12h12M12 6v12',
};
export function glyph(name) {
  const svg = document.createElementNS(SVG, 'svg'); svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true'); svg.setAttribute('class', 'twin-ring-glyph');
  svg.setAttribute('data-glyph', name);
  const path = document.createElementNS(SVG, 'path'); path.setAttribute('d', GLYPHS[name]);
  svg.append(path); return svg;
}

// A setpoint HA has not given (null) is missing, never 0.
export const known = value => value != null && value !== '' && Number.isFinite(Number(value));
// A thermostat holds a range whenever HA gives it one and no single setpoint, as HA's own
// card decides, whatever the mode is called (heat_cool, auto: review L4).
export const holdsRange = state => {
  const a = state?.attributes || {};
  return !!(Number(a.supported_features) & 2) && known(a.target_temp_low) && known(a.target_temp_high) && !known(a.temperature);
};

// Only a capability change rebuilds the controls. Confirmed values update in place, keeping
// a drag, a question or a hosted card alive across state pushes.
export function controlShape(state) {
  const attrs = state?.attributes || {};
  return JSON.stringify([holdsRange(state), ...[
    'supported_features', 'supported_color_modes', 'effect_list', 'hvac_modes', 'fan_modes',
    'preset_modes', 'available_modes', 'operation_list', 'source_list', 'code_format', 'code_arm_required',
    'min_temp', 'max_temp', 'target_temp_step', 'percentage_step', 'min_humidity', 'max_humidity',
    'min_color_temp_kelvin', 'max_color_temp_kelvin', 'min_mireds', 'max_mireds',
  ].map(key => attrs[key])]);
}

// The light builder's dial (controls/light.js): a 280 px disc, 44 px arcs that stop short of
// the horizontal and fill to their value, the on/off in the centre, and a side card for the
// discrete choices. A kind with no arc keeps the disc and puts its state and its verbs in it
// (the plain dial). Panels use native ranges with the same values and service calls.
export function controls({row, state, control, compact = false, surface = 'panel', getState}) {
  const ring = surface === 'ring', root = element('div'); root.className = 'twin-device-actions';
  const side = ring ? element('div') : root;
  if (ring) { root.className += ' twin-light-controls'; side.className = 'twin-ring-side'; }
  let confirmed = state, disposed = false, arcs = 0;
  const updates = [], stops = [], attrs = state?.attributes || {};
  const enabled = row.offered && !compact;
  const part = (node, name) => { node.setAttribute('data-ring-part', name); return node; };
  const update = next => { confirmed = next; for (const fn of updates) fn(); };
  async function send(service, data = {}) {
    if (!enabled || disposed) return false;
    if (!control.confirmsUnsafe && !await confirmUnsafe(row.name, service, row, data, confirmed)) return false;
    const ok = await control(row.entity_id, service, data);
    if (getState && !disposed) update(getState());
    return ok;
  }
  // Places in the dial: the centre row of round buttons, the stack of a plain dial (its state,
  // then its verbs as pills), and the line under the centre. In a room row every place is the row.
  const places = {};
  function place(name) {
    if (!ring) return root;
    if (!places[name]) {
      places[name] = element('div'); places[name].className = `twin-dial-${name}`;
      // A plain dial's verbs sit in its stack, under the state.
      (name === 'pills' ? place('stack') : root).append(places[name]);
    }
    return places[name];
  }
  function button(name, label, service, data = {}, parent = side, icon = null) {
    const node = part(element('button', label), name); node.type = 'button'; node.disabled = !enabled;
    if (ring && icon) {
      node.textContent = ''; node.append(glyph(icon)); node.setAttribute('aria-label', label);
      node.classList.add('twin-ring-round');
    }
    node.addEventListener('click', async () => {
      if (!enabled || disposed || node.disabled) return;
      node.disabled = true;
      try {
        const body = typeof data === 'function' ? await data(confirmed) : data;
        if (body !== null) await send(typeof service === 'function' ? service(confirmed) : service, body);
      } finally { node.disabled = !enabled; if (!disposed) update(confirmed); }
    });
    parent.append(node); return node;
  }
  // `aria` names the control for a screen reader when the visible label is not enough.
  function toggle(name, label, on, service, data = {}, aria = `${row.name} ${label}`) {
    const node = button(name, label, service, data, ring && name === 'center' ? root : side);
    node.setAttribute('role', 'switch'); node.setAttribute('aria-label', aria);
    updates.push(() => {
      node.setAttribute('aria-checked', String(!!on(confirmed)));
      node.textContent = name === 'center' ? (on(confirmed) ? 'On' : 'Off') : label;
    });
    if (name !== 'center') {
      const wrap = element('label', label); wrap.append(node); side.append(wrap);
    }
    return node;
  }
  // A line of text: in the side card, or at a named place in the dial ('stack', 'below').
  function text(name, valueOf, where = side) {
    const parent = typeof where === 'string' ? place(where) : where;
    const node = part(element('p'), name); parent.append(node);
    updates.push(() => { node.textContent = valueOf(confirmed); }); return node;
  }
  function chips(name, label, values, current, service, key) {
    if (!values?.length) return;
    const caption = element('p', label); caption.className = 'twin-ring-caption'; side.append(caption);
    const group = part(element('div'), name); group.className = 'twin-light-effects'; side.append(group);
    for (const value of values) {
      const node = button(name + '-choice', title(value), service, {[key]: value}, group);
      updates.push(() => node.setAttribute('aria-pressed', String(normal(current(confirmed)) === normal(value))));
    }
  }
  // An arc at the marker (a native range in a room row). `look` shapes the light's arcs:
  // `stroke` paints the track (the kelvin gradient), `fill(state)` colours the filled part
  // or, false, draws none; `idle(state)` hides the handle and the value while the setting
  // does not apply (a colour light has no temperature); `caption: false` shows the value
  // alone. A new drag is taken while the last value is still being sent (Ruling C10):
  // live.control sends the newest once the first has answered.
  function slider(name, label, min, max, step, valueOf, service, dataOf, lower = false, unit = '',
    {stroke = null, fill = () => '', idle = () => false, caption: named = true, aria = `${row.name} ${label}`} = {}) {
    let node, svg, handle, progress, output, dragging = null, editing = false, sending = 0, timer = null;
    min = Number(min); max = Number(max); step = Number(step) > 0 ? Number(step) : 1;
    if (ring) {
      arcs++; root.classList.add('twin-dial-arcs');
      svg = document.createElementNS(SVG, 'svg'); svg.setAttribute('viewBox', '0 0 280 280');
      svg.setAttribute('class', `twin-light-arc twin-light-arc-${name}`);
      node = document.createElementNS(SVG, 'path'); node.setAttribute('d', arcPath(lower));
      if (stroke) {
        const id = `twin-arc-${name}-${++gradients}`, defs = document.createElementNS(SVG, 'defs');
        const gradient = document.createElementNS(SVG, 'linearGradient');
        gradient.setAttribute('id', id); gradient.setAttribute('gradientUnits', 'userSpaceOnUse');
        for (const [key, value] of [['x1', '28'], ['y1', '0'], ['x2', '252'], ['y2', '0']]) gradient.setAttribute(key, value);
        for (const [offset, colour] of stroke) {
          const stop = document.createElementNS(SVG, 'stop');
          stop.setAttribute('offset', offset); stop.setAttribute('stop-color', colour); gradient.append(stop);
        }
        defs.append(gradient); svg.append(defs); node.style.stroke = `url(#${id})`;
      }
      node.setAttribute('role', 'slider'); node.setAttribute('tabindex', enabled ? '0' : '-1');
      node.setAttribute('aria-disabled', String(!enabled));
      node.setAttribute('aria-valuemin', String(min)); node.setAttribute('aria-valuemax', String(max));
      progress = document.createElementNS(SVG, 'path'); progress.setAttribute('d', arcPath(lower));
      progress.setAttribute('pathLength', '100'); progress.setAttribute('class', 'twin-light-progress');
      handle = document.createElementNS(SVG, 'circle'); handle.setAttribute('class', 'twin-light-handle'); handle.setAttribute('r', '8');
      svg.append(node, progress, handle); root.append(svg);
      // The value where the light ring shows its brightness, named in the caption's ink.
      output = element('output');
      const where = `twin-light-value twin-light-${lower ? 'temperature' : 'brightness'}`;
      if (named) {
        const readout = element('div'); readout.className = `${where} twin-dial-readout`;
        const caption = element('span', label); caption.className = 'twin-ring-caption';
        readout.append(caption, output); root.append(readout);
      } else { output.className = where; root.append(output); }
    } else {
      const wrap = element('label', label); node = element('input'); node.type = 'range';
      node.min = String(min); node.max = String(max); node.step = String(step); node.disabled = !enabled;
      wrap.append(node); root.append(wrap);
    }
    part(node, name); node.setAttribute('aria-label', aria);
    const show = (value, quiet = false) => {
      value = clamp(Number(value) || 0, min, max); node.value = String(value);
      if (ring) {
        node.setAttribute('aria-valuenow', String(value)); node.setAttribute('aria-valuetext', `${figure(value)}${unit}`);
        const ratio = max > min ? (value - min) / (max - min) : 0, [x, y] = point(ratio, lower);
        progress.setAttribute('stroke-dasharray', `${ratio * 100} 100`);
        // A zero-length dash still draws its round cap: an empty arc draws no fill at all.
        progress.style.visibility = fill && ratio > 0 ? 'visible' : 'hidden';
        if (fill) progress.style.stroke = fill(confirmed) || '';
        handle.setAttribute('cx', x.toFixed(2)); handle.setAttribute('cy', y.toFixed(2));
        handle.style.visibility = quiet ? 'hidden' : 'visible';
        output.textContent = quiet ? '' : `${figure(value)}${unit}`;
      }
    };
    const restore = () => { if (!editing && !sending) show(valueOf(confirmed), idle(confirmed)); };
    updates.push(restore);
    async function commit() {
      clearTimeout(timer); timer = null;
      if (!enabled || disposed) return;
      const value = Number(node.value); editing = false; sending++;
      try { await send(service, dataOf(value, confirmed)); }
      finally { sending--; if (!disposed) restore(); }
    }
    const choose = value => {
      if (!enabled || disposed) return;
      editing = true; clearTimeout(timer);
      show(clamp(Number((min + Math.round((value - min) / step) * step).toFixed(3)), min, max));
    };
    const schedule = () => { clearTimeout(timer); timer = setTimeout(() => { void commit(); }, 200); };
    if (ring) {
      node.addEventListener('keydown', event => {
        if (!enabled) return;
        const value = Number(node.value), keys = {ArrowUp: value + step, ArrowRight: value + step,
          ArrowDown: value - step, ArrowLeft: value - step, Home: min, End: max,
          PageUp: value + 10 * step, PageDown: value - 10 * step};
        if (!(event.key in keys)) return;
        event.preventDefault(); choose(keys[event.key]); schedule();
      });
      const move = event => {
        const box = svg.getBoundingClientRect(), bounds = root.getBoundingClientRect();
        const cx = box.width ? box.left + box.width / 2 : bounds.left + 140;
        const cy = box.width ? box.top + box.height / 2 : bounds.top + 140;
        const angle = Math.atan2(Math.max(0, lower ? event.clientY - cy : cy - event.clientY), cx - event.clientX);
        choose(min + clamp((angle - GAP) / (Math.PI - 2 * GAP), 0, 1) * (max - min));
      };
      node.addEventListener('pointerdown', event => {
        if (!enabled || event.button > 0) return;
        event.preventDefault(); dragging = event.pointerId; node.setPointerCapture?.(dragging); move(event);
      });
      node.addEventListener('pointermove', event => { if (dragging === event.pointerId) move(event); });
      node.addEventListener('pointerup', event => {
        if (dragging !== event.pointerId) return;
        move(event); node.releasePointerCapture?.(dragging); dragging = null; schedule();
      });
      node.addEventListener('pointercancel', () => { dragging = null; editing = false; clearTimeout(timer); restore(); });
    } else {
      node.addEventListener('input', () => choose(Number(node.value)));
      node.addEventListener('change', () => { if (enabled) void commit(); });
    }
    stops.push(() => clearTimeout(timer));
    return node;
  }
  return {root, side, attrs, ring, enabled, part, button, toggle, text, chips, slider, place, send,
    confirmed: () => confirmed, disposed: () => disposed,
    watch: fn => updates.push(() => fn(confirmed)),
    onStop: fn => stops.push(fn),
    has: bit => !!(Number(attrs.supported_features) & bit),
    finish() {
      if (!ring && (!row.offered || compact)) root.replaceChildren();
      if (ring) {
        // A dial with no arc and no centre switch is a plain dial: its stack sits in the middle.
        if (!arcs && !root.querySelector('[data-ring-part="center"]')) root.classList.add('twin-dial-plain');
        // Read-only, a plain dial says the state and offers no dead verbs.
        if (!row.offered) places.pills?.remove();
        if (side.childNodes.length) { root.append(side); root.side = side; }
      }
      root.update = update; root.stop = () => { disposed = true; stops.forEach(stop => stop()); };
      update(state); return root;
    }};
}

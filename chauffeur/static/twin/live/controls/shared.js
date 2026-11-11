import { confirmUnsafe } from '../kinds.js';

export const element = (tag, text) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  return node;
};
const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
const normal = value => String(value ?? '').toLowerCase().replace(/[\s_-]+/g, '');
const title = value => String(value).replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
const SVG = 'http://www.w3.org/2000/svg', GAP = Math.PI / 9;
const point = (t, lower) => {
  const phi = Math.PI - GAP - t * (Math.PI - 2 * GAP);
  return [140 + 90 * Math.cos(phi), 140 + (lower ? 1 : -1) * 90 * Math.sin(phi)];
};

// Only a capability change rebuilds the controls. Confirmed values update in place, keeping
// a drag, a question or a hosted card alive across state pushes.
export function controlShape(state) {
  const attrs = state?.attributes || {};
  return JSON.stringify([state?.state === 'heat_cool', ...[
    'supported_features', 'supported_color_modes', 'effect_list', 'hvac_modes', 'fan_modes',
    'preset_modes', 'available_modes', 'operation_list', 'source_list', 'code_format', 'code_arm_required',
    'min_temp', 'max_temp', 'target_temp_step', 'percentage_step', 'min_humidity', 'max_humidity',
    'min_color_temp_kelvin', 'max_color_temp_kelvin', 'min_mireds', 'max_mireds',
  ].map(key => attrs[key])]);
}

// The light builder's dial, 44px arcs, angular gestures and side card, shared by the
// remaining kinds. Panels use native ranges with the same values and service calls.
export function controls({row, state, control, compact = false, surface = 'panel', getState}) {
  const ring = surface === 'ring', root = element('div'); root.className = 'twin-device-actions';
  const side = ring ? element('div') : root, summary = ring ? element('div') : root;
  if (ring) {
    root.className += ' twin-light-controls'; side.className = 'twin-ring-side';
    summary.className = 'twin-control-summary'; root.append(summary);
  }
  let confirmed = state, disposed = false;
  const updates = [], stops = [], attrs = state?.attributes || {};
  const enabled = row.offered && !compact;
  const part = (node, name) => { node.setAttribute('data-ring-part', name); return node; };
  const update = next => { confirmed = next; for (const fn of updates) fn(); };
  async function send(service, data = {}) {
    if (!enabled || disposed) return false;
    if (!control.confirmsUnsafe && !await confirmUnsafe(row.name, service, row)) return false;
    const ok = await control(row.entity_id, service, data);
    if (getState && !disposed) update(getState());
    return ok;
  }
  function button(name, label, service, data = {}, parent = side) {
    const node = part(element('button', label), name); node.type = 'button'; node.disabled = !enabled;
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
  function toggle(name, label, on, service, data = {}) {
    const node = button(name, label, service, data, ring && name === 'center' ? root : side);
    node.setAttribute('role', 'switch'); node.setAttribute('aria-label', `${row.name} ${label}`);
    updates.push(() => {
      node.setAttribute('aria-checked', String(!!on(confirmed)));
      node.textContent = name === 'center' ? (on(confirmed) ? 'On' : 'Off') : label;
    });
    if (name !== 'center') {
      const wrap = element('label', label); wrap.append(node); side.append(wrap);
    }
    return node;
  }
  function text(name, valueOf, central = false) {
    const node = part(element('p'), name); (central ? summary : side).append(node);
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
  function slider(name, label, min, max, step, valueOf, service, dataOf, lower = false, unit = '') {
    let node, svg, handle, output, dragging = null, editing = false, sending = false, timer = null;
    min = Number(min); max = Number(max); step = Number(step) > 0 ? Number(step) : 1;
    if (ring) {
      svg = document.createElementNS(SVG, 'svg'); svg.setAttribute('viewBox', '0 0 280 280');
      svg.setAttribute('class', 'twin-light-arc');
      node = document.createElementNS(SVG, 'path');
      const [[x0, y0], [x1, y1]] = [point(0, lower), point(1, lower)];
      node.setAttribute('d', `M ${x0} ${y0} A 90 90 0 0 ${lower ? 0 : 1} ${x1} ${y1}`);
      node.setAttribute('role', 'slider'); node.setAttribute('tabindex', enabled ? '0' : '-1');
      node.setAttribute('aria-disabled', String(!enabled));
      node.setAttribute('aria-valuemin', String(min)); node.setAttribute('aria-valuemax', String(max));
      handle = document.createElementNS(SVG, 'circle'); handle.setAttribute('class', 'twin-light-handle'); handle.setAttribute('r', '8');
      svg.append(node, handle); root.append(svg);
      output = element('output'); output.className = `twin-light-value twin-light-${lower ? 'temperature' : 'brightness'}`;
      root.append(output);
    } else {
      const wrap = element('label', label); node = element('input'); node.type = 'range';
      node.min = String(min); node.max = String(max); node.step = String(step); node.disabled = !enabled;
      wrap.append(node); root.append(wrap);
    }
    part(node, name); node.setAttribute('aria-label', `${row.name} ${label}`);
    const show = value => {
      value = clamp(Number(value) || 0, min, max); node.value = String(value);
      if (ring) {
        node.setAttribute('aria-valuenow', String(value)); node.setAttribute('aria-valuetext', `${value}${unit}`);
        const [x, y] = point(max > min ? (value - min) / (max - min) : 0, lower);
        handle.setAttribute('cx', x.toFixed(2)); handle.setAttribute('cy', y.toFixed(2));
        output.textContent = `${label} ${value}${unit}`;
      }
    };
    const restore = () => { if (!editing && !sending) show(valueOf(confirmed)); };
    updates.push(restore);
    async function commit() {
      clearTimeout(timer); timer = null;
      if (!enabled || disposed || sending) return;
      const value = Number(node.value); editing = false; sending = true;
      try { await send(service, dataOf(value, confirmed)); }
      finally { sending = false; if (!disposed) restore(); }
    }
    const choose = value => {
      if (!enabled || disposed || sending) return;
      editing = true; clearTimeout(timer);
      show(clamp(Number((min + Math.round((value - min) / step) * step).toFixed(3)), min, max));
    };
    const schedule = () => { clearTimeout(timer); timer = setTimeout(() => { void commit(); }, 200); };
    if (ring) {
      node.addEventListener('keydown', event => {
        if (!enabled || sending) return;
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
        if (!enabled || sending || event.button > 0) return;
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
  return {root, attrs, part, button, toggle, text, chips, slider,
    watch: fn => updates.push(() => fn(confirmed)),
    has: bit => !!(Number(attrs.supported_features) & bit),
    finish() {
      if (!ring && (!row.offered || compact)) root.replaceChildren();
      if (ring && side.childNodes.length) { root.append(side); root.side = side; }
      root.update = update; root.stop = () => { disposed = true; stops.forEach(stop => stop()); };
      update(state); return root;
    }};
}

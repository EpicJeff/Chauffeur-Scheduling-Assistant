import { controls, element, clamp } from './shared.js';
import { resolveLightColour, effectPalette, effectRgb, hsRgb } from '../light_colours.js';

const COLOURS = [['Red', [255, 0, 0]], ['Amber', [255, 191, 0]], ['Green', [0, 255, 0]],
  ['Blue', [0, 0, 255]], ['Purple', [128, 0, 255]]];
// Warm on the left to cool on the right, the way the kelvin scale reads.
const KELVIN = [['0', '#ff9d3c'], ['.45', '#ffe4c2'], ['1', '#cfe0ff']];
// The brightness arc fills in the light's own confirmed colour while it is on.
const lightColour = (s, look, domain) => s?.state === 'on'
  ? `rgb(${resolveLightColour(s.attributes, look, domain).rgb.join(',')})` : '';
function hueSat(attrs) {
  if (Array.isArray(attrs.hs_color)) return [...attrs.hs_color];
  const rgb = (attrs.rgb_color || [255, 255, 255]).map(v => v / 255);
  const [r, g, b] = rgb, max = Math.max(...rgb), delta = max - Math.min(...rgb);
  const hue = !delta ? 0 : max === r ? ((g - b) / delta + 6) % 6 : max === g ? (b - r) / delta + 2 : (r - g) / delta + 4;
  return [hue * 60, max ? delta / max * 100 : 0];
}

// Lights, switches and outlets on the shared dial (controls/shared.js, review L9): its
// arcs, its centre switch, its side card. Only what a light alone has lives here: the
// kelvin arc's colours, the fill in the light's colour, the swatches and the wheel.
// Both surfaces use these capabilities, values and service calls; only their handles
// differ (arcs around the marker, native ranges in the room's expanded row).
export function lightControls(options) {
  const c = controls(options), {row} = options, attrs = c.attrs, modes = attrs.supported_color_modes;
  editorLifecycle(c);
  const light = row.kind === 'light';
  const dimmable = light && (Array.isArray(modes) ? modes.some(mode => mode !== 'onoff') : true);
  const temperature = light && modes?.includes('color_temp');
  const colour = light && modes?.some(mode => ['hs', 'rgb', 'xy', 'rgbw', 'rgbww'].includes(mode));
  // The light's own names, as the room row and the ring have always read them.
  c.toggle('center', 'Power', s => s?.state === 'on', 'toggle', {}, row.name);
  if (dimmable) c.slider('brightness', 'Brightness', 0, 100, 1,
    s => Math.round((s?.attributes?.brightness ?? 0) / 255 * 100), 'turn_on', v => ({brightness_pct: v}), false, '%',
    {fill: s => lightColour(s, options.lightLooks?.get(row.entity_id), row.entity_id.split('.')[0]), caption: false, aria: `${row.name} brightness`});
  if (temperature) {
    const min = attrs.min_color_temp_kelvin || (attrs.max_mireds ? Math.round(1e6 / attrs.max_mireds) : 2000);
    const max = attrs.max_color_temp_kelvin || (attrs.min_mireds ? Math.round(1e6 / attrs.min_mireds) : 6500);
    c.slider('temperature', 'Temperature', min, max, 1, s => {
      const a = s?.attributes || {};
      return clamp(a.color_temp_kelvin ?? (a.color_temp ? Math.round(1e6 / a.color_temp) : min), min, max);
    }, 'turn_on', v => ({color_temp_kelvin: v}), true, ' K', {
      stroke: KELVIN, fill: false, caption: false, aria: `${row.name} temperature`,
      // A light showing a colour has no temperature: no handle, no value.
      idle: s => { const a = s?.attributes || {}; return a.color_temp_kelvin == null && !a.color_temp && !!a.color_mode && a.color_mode !== 'color_temp'; },
    });
  }
  // At the marker, colour and effects sit in the side card (the host places it on whichever
  // side has room); in the room's row they follow the ranges.
  if (colour) {
    if (c.ring) { const caption = element('p', 'Colour'); caption.className = 'twin-ring-caption'; c.side.append(caption); }
    const swatches = c.part(element('div'), 'swatches'); swatches.className = 'twin-light-swatches';
    c.side.append(swatches);
    for (const [name, rgb] of COLOURS) {
      const node = c.button('swatch', name, 'turn_on', {rgb_color: rgb}, swatches);
      node.setAttribute('aria-label', name); node.style.background = `rgb(${rgb.join(',')})`;
    }
    wheel(c, options);
  }
  if (light && attrs.effect_list?.length) {
    if (c.enabled) c.chips('effects', 'Effects', attrs.effect_list, s => s?.attributes?.effect, 'turn_on', 'effect',
      (node, effect, group) => effectDot(c, options, node, effect, group));
    else {
      const assigned = attrs.effect_list.filter(effect => effectPalette(effect, options.lightLooks?.get(row.entity_id)));
      if (assigned.length) {
        const group = c.chipGroup('effects', 'Effects', true);
        for (const effect of assigned) {
          const item = c.part(element('span', effect), 'effect-look-preview'); group.append(item);
          effectDot(c, options, item, effect, group);
        }
      }
    }
  }
  if (!colour) twinFixedColour(c, options);
  return c.finish();
}

// The colour wheel: hue by angle, saturation by distance from the centre; one call once the
// finger rests. Like an arc, it takes a new choice while the last one is being sent (C10).
function wheel(c, {row}, {parent = c.side, initial = c.attrs, read = () => c.confirmed()?.attributes || {},
  choose = hs => c.send('turn_on', {hs_color: hs.map(Math.round)}), name = 'wheel',
  caption = c.ring ? undefined : 'Colour', aria = `${row.name} colour`, enabled = () => c.enabled} = {}) {
  const label = element('div', caption), node = c.part(element('div'), name);
  node.className = 'twin-colour-wheel'; node.setAttribute('role', 'slider');
  node.setAttribute('tabindex', enabled() ? '0' : '-1'); node.setAttribute('aria-disabled', String(!enabled()));
  node.setAttribute('aria-label', aria); node.setAttribute('aria-valuemin', '0'); node.setAttribute('aria-valuemax', '360');
  node.setAttribute('aria-description', 'Arrow keys choose hue. Hold Shift to choose saturation.');
  const dot = element('span'); dot.setAttribute('aria-hidden', 'true'); node.append(dot);
  let hs = hueSat(initial), dragging = null, timer = null, choosing = false, sending = 0;
  const show = () => {
    const angle = hs[0] * Math.PI / 180, radius = hs[1] * .44;
    dot.style.left = `${50 + Math.sin(angle) * radius}%`; dot.style.top = `${50 - Math.cos(angle) * radius}%`;
    node.setAttribute('aria-valuenow', String(Math.round(hs[0])));
    node.setAttribute('aria-valuetext', `${Math.round(hs[0])} degrees, ${Math.round(hs[1])}% saturation`);
  };
  const restore = () => { if (!choosing && !sending) { hs = hueSat(read()); show(); } };
  async function commit() {
    if (!enabled() || c.disposed()) return;
    choosing = false; sending++;
    try { await choose(hs.map(Math.round)); }
    finally { sending--; if (!c.disposed()) restore(); }
  }
  const schedule = () => { clearTimeout(timer); timer = setTimeout(() => { void commit(); }, 200); };
  const move = event => {
    const rect = node.getBoundingClientRect(), radius = Math.max(1, rect.width / 2);
    const x = event.clientX - rect.left - radius, y = event.clientY - rect.top - rect.height / 2;
    hs = [(Math.atan2(x, -y) * 180 / Math.PI + 360) % 360, clamp(Math.hypot(x, y) / radius * 100, 0, 100)];
    choosing = true; clearTimeout(timer); show();
  };
  node.addEventListener('pointerdown', event => {
    if (!enabled() || event.button > 0) return;
    event.preventDefault(); dragging = event.pointerId; node.setPointerCapture?.(dragging); move(event);
  });
  node.addEventListener('pointermove', event => { if (event.pointerId === dragging) move(event); });
  node.addEventListener('pointerup', event => {
    if (event.pointerId !== dragging) return;
    move(event); node.releasePointerCapture?.(dragging); dragging = null; schedule();
  });
  node.addEventListener('pointercancel', () => { dragging = null; choosing = false; clearTimeout(timer); restore(); });
  node.addEventListener('keydown', event => {
    if (!enabled() || !['ArrowUp', 'ArrowRight', 'ArrowDown', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault(); choosing = true;
    const i = event.shiftKey ? 1 : 0, max = i ? 100 : 360;
    hs[i] = event.key === 'Home' ? 0 : event.key === 'End' ? max :
      clamp(hs[i] + (['ArrowUp', 'ArrowRight'].includes(event.key) ? 1 : -1), 0, max);
    show(); schedule();
  });
  c.watch(restore); c.onStop(() => clearTimeout(timer));
  label.className = 'twin-light-wheel'; label.append(node); parent.append(label);
  node.flush = async () => { clearTimeout(timer); if (choosing) await commit(); };
  node.stop = () => { clearTimeout(timer); dragging = null; };
  show(); return node;
}

// Effect service chips keep their original handlers. The adjacent dot edits only the twin.
function effectDot(c, options, node, effect, group) {
  const {lightLooks, row} = options, editable = canEdit(c, options);
  const dot = c.part(element(editable ? 'button' : 'span'), editable ? 'effect-look-edit' : 'effect-look-dot');
  const preview = editable ? element('span') : dot; preview.className = 'twin-look-dot';
  if (editable) { preview.setAttribute('aria-hidden', 'true'); dot.append(preview); }
  const paint = () => {
    const palette = effectPalette(effect, lightLooks?.get(row.entity_id)) || (effectRgb(effect) ? [effectRgb(effect)] : []);
    const background = palette.length > 1 ? `linear-gradient(90deg, ${palette.map(rgb => `rgb(${rgb.join(',')})`).join(',')})`
      : palette.length ? `rgb(${palette[0].join(',')})` : 'transparent';
    if (background !== painted) { preview.style.background = background; painted = background; }
    dot.setAttribute('aria-label', `${editable ? 'Edit' : 'Preview'} ${effect} colour in the twin${palette.length ? '' : ', automatic colour unknown'}`);
  };
  let painted;
  if (editable) dot.className = 'twin-look-edit';
  if (editable) {
    dot.type = 'button'; dot.title = 'Edit colour in the twin';
    dot.addEventListener('click', () => lookEditor(c, options, effect, dot));
    const chip = element('span'); chip.className = 'twin-look-chip';
    node.remove(); chip.append(node, dot); group.append(chip);
  } else { dot.setAttribute('aria-hidden', 'true'); node.prepend(dot); }
  c.watch(paint); paint();
}
const canEdit = (c, options) => !!options.lightLooks?.canEdit && !!options.row.offered && !options.compact;
function editorLifecycle(c) {
  if (c.stopLookEditor) return;
  c.stopLookEditor = () => c.closeLookEditor?.(false);
  c.onStop(c.stopLookEditor);
}
export function twinFixedColour(c, options) {
  const domain = options.row.entity_id?.split('.')[0];
  if (!['light', 'switch', 'input_boolean', 'fan'].includes(domain) || !canEdit(c, options)) return;
  editorLifecycle(c);
  const button = c.part(element('button', 'Colour in the twin (display only)'), 'fixed-look-edit'); button.type = 'button';
  button.addEventListener('click', () => lookEditor(c, options, null, button)); c.side.append(button);
}
function lookEditor(c, options, effect, opener) {
  if (!canEdit(c, options) || c.disposed()) return;
  // One editor per control, inside its existing side card.
  c.closeLookEditor?.();
  const {row, lightLooks} = options, entity = row.entity_id, key = effect?.trim().toLowerCase();
  const old = lightLooks.get(entity), automatic = resolveLightColour(c.confirmed()?.attributes, old, entity.split('.')[0]).rgb;
  let stops = effect ? effectPalette(effect, old) || [effectRgb(effect) || automatic] : [old?.colour || automatic];
  stops = stops.map(rgb => [...rgb]);
  let wheels = [], saving = false, editing = false, closed = false;
  const editor = c.part(element('fieldset'), 'look-editor'); editor.className = 'twin-look-editor';
  const legend = element('legend', effect ? `${effect}: colour in the twin` : 'Colour in the twin');
  const note = element('p', 'Display only. This does not change the real light.'); note.className = 'twin-ring-caption';
  const list = element('div'), actions = element('div'); actions.className = 'twin-light-effects';
  const makeButton = (name, label, fn) => {
    const button = c.part(element('button', label), name); button.type = 'button'; button.addEventListener('click', fn); return button;
  };
  const close = (focus = true) => { closed = true; wheels.forEach(w => w.stop()); editor.remove(); if (focus) opener.focus?.(); };
  c.closeLookEditor = close;
  async function save(clear = false) {
    if (saving || editing || closed) return;
    editing = true;
    for (const w of wheels) await w.flush();
    saving = true; editor.disabled = true;
    const look = structuredClone(lightLooks.get(entity) || {});
    if (effect) {
      look.effects ||= {};
      if (clear) delete look.effects[key]; else look.effects = {...look.effects, [key]: stops.map(rgb => [...rgb])};
      if (!Object.keys(look.effects).length) delete look.effects;
    } else if (clear) delete look.colour; else look.colour = [...stops[0]];
    try { if (await lightLooks.save(entity, Object.keys(look).length ? look : null)) close(); }
    finally { saving = false; editing = false; editor.disabled = false; }
  }
  const add = makeButton('look-add', 'Add a stop', async () => {
    if (saving || editing || closed || stops.length >= 4) return;
    editing = true;
    try { for (const w of wheels) await w.flush(); if (!closed) { stops.push([...stops.at(-1)]); render(); } }
    finally { editing = false; }
  });
  const clear = makeButton('look-clear', 'Clear (automatic)', () => { void save(true); });
  const done = makeButton('look-done', 'Done', () => { void save(); });
  const cancel = makeButton('look-cancel', 'Cancel', close);
  function render() {
    wheels.forEach(w => w.stop()); wheels = []; list.replaceChildren();
    stops.forEach((rgb, i) => {
      const slot = element('div'); slot.className = 'twin-look-stop'; list.append(slot);
      const context = {...c, disposed: () => closed || c.disposed(), watch: () => {}, onStop: () => {}};
      wheels.push(wheel(context, options, {parent: slot, initial: {rgb_color: rgb}, read: () => ({rgb_color: stops[i]}),
        choose: hs => { stops[i] = hsRgb(hs); }, enabled: () => !saving && !closed,
        name: 'look-wheel', caption: `Stop ${i + 1}`, aria: `${row.name} twin colour stop ${i + 1}`}));
      if (effect && stops.length > 1) slot.append(makeButton('look-remove', `Remove stop ${i + 1}`, async () => {
        if (saving || editing || closed) return;
        editing = true;
        try { for (const w of wheels) await w.flush(); if (!closed) { stops.splice(i, 1); render(); } }
        finally { editing = false; }
      }));
    });
    add.disabled = stops.length >= 4;
  }
  if (effect) actions.append(add);
  actions.append(clear, done, cancel); editor.append(legend, note, list, actions); c.side.append(editor); render(); wheels[0]?.focus?.();
}

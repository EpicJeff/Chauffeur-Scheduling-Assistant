import { controls, element, clamp } from './shared.js';
import { twinText } from '../../palette.js';

const COLOURS = [['Red', [255, 0, 0]], ['Amber', [255, 191, 0]], ['Green', [0, 255, 0]],
  ['Blue', [0, 0, 255]], ['Purple', [128, 0, 255]]];
// Warm on the left to cool on the right, the way the kelvin scale reads.
const KELVIN = [['0', '#ff9d3c'], ['.45', '#ffe4c2'], ['1', '#cfe0ff']];
// The brightness arc fills in the light's own confirmed colour while it is on.
const lightColour = s => s?.state === 'on' && Array.isArray(s.attributes?.rgb_color)
  ? `color-mix(in srgb, rgb(${s.attributes.rgb_color.map(Number).join(',')}) 80%, ${twinText})` : '';
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
  const light = row.kind === 'light';
  const dimmable = light && (Array.isArray(modes) ? modes.some(mode => mode !== 'onoff') : true);
  const temperature = light && modes?.includes('color_temp');
  const colour = light && modes?.some(mode => ['hs', 'rgb', 'xy', 'rgbw', 'rgbww'].includes(mode));
  // The light's own names, as the room row and the ring have always read them.
  c.toggle('center', 'Power', s => s?.state === 'on', 'toggle', {}, row.name);
  if (dimmable) c.slider('brightness', 'Brightness', 0, 100, 1,
    s => Math.round((s?.attributes?.brightness ?? 0) / 255 * 100), 'turn_on', v => ({brightness_pct: v}), false, '%',
    {fill: lightColour, caption: false, aria: `${row.name} brightness`});
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
  if (light && attrs.effect_list?.length)
    c.chips('effects', 'Effects', attrs.effect_list, s => s?.attributes?.effect, 'turn_on', 'effect');
  return c.finish();
}

// The colour wheel: hue by angle, saturation by distance from the centre; one call once the
// finger rests. Like an arc, it takes a new choice while the last one is being sent (C10).
function wheel(c, {row}) {
  const label = element('div', c.ring ? undefined : 'Colour'), node = c.part(element('div'), 'wheel');
  node.className = 'twin-colour-wheel'; node.setAttribute('role', 'slider');
  node.setAttribute('tabindex', c.enabled ? '0' : '-1'); node.setAttribute('aria-disabled', String(!c.enabled));
  node.setAttribute('aria-label', `${row.name} colour`); node.setAttribute('aria-valuemin', '0'); node.setAttribute('aria-valuemax', '360');
  node.setAttribute('aria-description', 'Arrow keys choose hue. Hold Shift to choose saturation.');
  const dot = element('span'); dot.setAttribute('aria-hidden', 'true'); node.append(dot);
  let hs = hueSat(c.attrs), dragging = null, timer = null, choosing = false, sending = 0;
  const show = () => {
    const angle = hs[0] * Math.PI / 180, radius = hs[1] * .44;
    dot.style.left = `${50 + Math.sin(angle) * radius}%`; dot.style.top = `${50 - Math.cos(angle) * radius}%`;
    node.setAttribute('aria-valuenow', String(Math.round(hs[0])));
    node.setAttribute('aria-valuetext', `${Math.round(hs[0])} degrees, ${Math.round(hs[1])}% saturation`);
  };
  const restore = () => { if (!choosing && !sending) { hs = hueSat(c.confirmed()?.attributes || {}); show(); } };
  async function commit() {
    if (!c.enabled || c.disposed()) return;
    choosing = false; sending++;
    try { await c.send('turn_on', {hs_color: hs.map(Math.round)}); }
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
    if (!c.enabled || event.button > 0) return;
    event.preventDefault(); dragging = event.pointerId; node.setPointerCapture?.(dragging); move(event);
  });
  node.addEventListener('pointermove', event => { if (event.pointerId === dragging) move(event); });
  node.addEventListener('pointerup', event => {
    if (event.pointerId !== dragging) return;
    move(event); node.releasePointerCapture?.(dragging); dragging = null; schedule();
  });
  node.addEventListener('pointercancel', () => { dragging = null; choosing = false; clearTimeout(timer); restore(); });
  node.addEventListener('keydown', event => {
    if (!c.enabled || !['ArrowUp', 'ArrowRight', 'ArrowDown', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault(); choosing = true;
    const i = event.shiftKey ? 1 : 0, max = i ? 100 : 360;
    hs[i] = event.key === 'Home' ? 0 : event.key === 'End' ? max :
      clamp(hs[i] + (['ArrowUp', 'ArrowRight'].includes(event.key) ? 1 : -1), 0, max);
    show(); schedule();
  });
  c.watch(restore); c.onStop(() => clearTimeout(timer));
  label.className = 'twin-light-wheel'; label.append(node); c.side.append(label);
}

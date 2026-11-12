// Shared twin chrome and device-state colours. The two pages mirror these on :root;
// test_twin_palette_js.py keeps the canvas and CSS palettes in agreement.
export const twinGlass = 'rgba(17,19,24,.62)';
export const twinGlassStrong = 'rgba(17,19,24,.82)';
export const twinBorder = 'rgba(255,255,255,.08)';
export const twinText = '#f4f5f7';
export const twinTextDim = '#a3a9b6';
export const twinSelected = '#f4f5f7';
export const twinSelectedText = '#111318';
export const twinHover = 'rgba(255,255,255,.08)';
export const twinMarkerOff = 'rgba(17,19,24,.78)';
export const twinMarkerRing = 'rgba(255,255,255,.22)';
export const twinMarkerUnavailable = 'rgba(17,19,24,.5)';
export const twinMarkerUnavailableText = '#6b7280';
export const twinAttention = '#f59e0b';
export const twinAttentionRing = '#fde68a';
export const twinLight = '#facc15';
export const twinCyan = '#22d3ee';
export const twinHeat = '#fb923c';
export const twinCool = '#60a5fa';
export const twinAuto = '#a78bfa';
export const twinOpen = '#34d399';
export const twinDevice = '#e5e7eb';
export const twinWarmWhite = '#ffd89a';
export const twinDry = '#2dd4bf';
export const twinDanger = '#f87171';

const hex = rgb => '#' + rgb.map(v => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, '0')).join('');

// Standard black-body approximation in sRGB, independent of the lamp's brightness.
export function kelvinColor(kelvin) {
  const t = Math.max(1000, Math.min(40000, kelvin)) / 100;
  return hex([t <= 66 ? 255 : 329.698727446 * (t - 60) ** -.1332047592,
    t <= 66 ? 99.4708025861 * Math.log(t) - 161.1195681661 : 288.1221695283 * (t - 60) ** -.0755148492,
    t >= 66 ? 255 : t <= 19 ? 0 : 138.5177312231 * Math.log(t - 10) - 305.0447927307]);
}

export function climateModeColor(mode) {
  return {heat: twinHeat, cool: twinCool, heat_cool: twinAuto, auto: twinAuto,
    dry: twinDry, fan_only: twinDry}[mode] || twinText;
}

export function markerOnColor(kind, state = {}) {
  const attrs = state?.attributes || {}, value = state?.state;
  if (kind === 'light') {
    if (Array.isArray(attrs.rgb_color) && attrs.rgb_color.length === 3 && attrs.rgb_color.every(Number.isFinite))
      return hex(attrs.rgb_color);
    const kelvin = Number(attrs.color_temp_kelvin) > 0 ? Number(attrs.color_temp_kelvin)
      : Number(attrs.color_temp) > 0 ? 1e6 / Number(attrs.color_temp) : null;
    return kelvin && Number.isFinite(kelvin) ? kelvinColor(kelvin) : twinWarmWhite;
  }
  if (kind === 'climate') return climateModeColor(value || attrs.hvac_mode);
  if (kind === 'lock') return value === 'jammed' ? twinDanger : value === 'locked' ? twinOpen : twinAttention;
  if (kind === 'alarm' || kind === 'alarm_control_panel')
    return value === 'triggered' ? twinDanger : value?.startsWith('armed_') ? twinOpen : twinAttention;
  if (kind === 'garage') return twinAttention;
  if (kind === 'blinds' || kind === 'cover') return twinDevice;
  return twinText;
}

// Choose palette ink by the luminance of an opaque state-colour disc.
export function markerInk(color) {
  const rgb = color.slice(1).match(/../g).map(v => {
    const c = parseInt(v, 16) / 255;
    return c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4;
  });
  const luminance = rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
  return luminance > .179 ? twinSelectedText : twinText;
}

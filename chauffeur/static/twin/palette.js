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

const onColors = {light: twinLight, switch: twinCyan, outlet: twinCyan, fan: twinCyan,
  media: twinAuto, cover: twinOpen, blinds: twinOpen, garage: twinOpen};

export function markerOnColor(kind, state = {}) {
  if (kind !== 'climate') return onColors[kind] || twinDevice;
  const action = state?.attributes?.hvac_action;
  if (action === 'heating') return twinHeat;
  if (action === 'cooling') return twinCool;
  const mode = state?.state || state?.attributes?.hvac_mode;
  return mode === 'cool' ? twinCool : ['heat_cool', 'auto'].includes(mode) ? twinAuto : twinHeat;
}

// Choose palette ink by the luminance of an opaque kind-colour disc.
export function markerInk(color) {
  const rgb = color.slice(1).match(/../g).map(v => {
    const c = parseInt(v, 16) / 255;
    return c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4;
  });
  const luminance = rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
  return luminance > .179 ? twinSelectedText : twinText;
}

// Renderer settings and deterministic selection, shared by the page and embeds.
export const TIERS = {
  low: { pixelRatio: 1, antialias: false, shadows: false, shadowSize: 0, plantCards: true, edgeGrass: false },
  high: { pixelRatio: Math.min(globalThis.devicePixelRatio || 1, 2), antialias: true, shadows: true, shadowSize: 4096, plantCards: false, edgeGrass: true },
};

export function rendererName(gl) {
  const ext = gl?.getExtension('WEBGL_debug_renderer_info');
  return ext ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) || '') : '';
}

export function pickTier(search, gl) {
  const forced = search.get('tier');
  if (forced === 'low' || forced === 'high') return forced;
  return /videocore|v3d/i.test(rendererName(gl)) || (globalThis.navigator?.hardwareConcurrency || 8) <= 4 ? 'low' : 'high';
}

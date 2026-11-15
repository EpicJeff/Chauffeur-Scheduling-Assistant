// Renderer settings and deterministic selection, shared by the page and embeds.
export const TIERS = {
  low: { bakedRects: 2, pixelRatio: 1, antialias: false, shadows: false, shadowSize: 0, plantCards: true, edgeGrass: false, realLights: {point: 4, spot: 1, area: 2, shadows: 0} },
  medium: { bakedRects: 4, pixelRatio: 1, antialias: true, shadows: true, shadowSize: 2048, plantCards: true, edgeGrass: false, realLights: {point: 8, spot: 2, area: 4, shadows: 1} },
  // Fully mapped + DFG + environment + 3 bake banks + LTC + sun leaves one lamp shadow on 16-sampler GPUs.
  high: { bakedRects: 8, pixelRatio: Math.min(globalThis.devicePixelRatio || 1, 2), antialias: true, shadows: true, shadowSize: 4096, plantCards: false, edgeGrass: true, realLights: {point: 12, spot: 4, area: 8, shadows: 1} },
  max: { bakedRects: 16, pixelRatio: Math.min(globalThis.devicePixelRatio || 1, 2), antialias: true, shadows: true, shadowSize: 4096, plantCards: false, edgeGrass: true, realLights: {point: 16, spot: 6, area: 12, shadows: 1} },
};

export function rendererName(gl) {
  const ext = gl?.getExtension('WEBGL_debug_renderer_info');
  return ext ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) || '') : '';
}

export function pickTier(search, gl) {
  const forced = search.get('tier');
  if (Object.hasOwn(TIERS, forced)) return forced;
  return /videocore|v3d/i.test(rendererName(gl)) || (globalThis.navigator?.hardwareConcurrency || 8) <= 4 ? 'low' : 'high';
}

import { resolveSurfaceMaterial } from './surface_material.js';

// The card and renderer describe the same receiving surface. Posts keep column
// inheritance; all other supports follow building trim, then house trim.
export function supportMaterialSurface(plan, building, roof, kit = {}) {
  const post = roof.support?.kind === 'post';
  const trim = resolveSurfaceMaterial(plan, { role: 'trim', building, kit });
  return { role: post ? 'column' : 'support', building, level: post ? roof.level : null,
    ref: roof.materials?.support, fallback: trim, kit };
}

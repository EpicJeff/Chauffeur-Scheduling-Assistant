import { resolveSurfaceMaterial } from './surface_material.js';

// One receiving descriptor for the roof card and the ceiling renderer.
export function undersideMaterialSurface(plan, building, roof, kit = {}) {
  const porchCeiling = resolveSurfaceMaterial(plan, {role:'porch_ceiling', building, kit});
  const soffit = resolveSurfaceMaterial(plan, {role:'soffit', building, fallback:porchCeiling, kit});
  return {role:'underside', building, level:null, ref:roof.materials?.underside, fallback:soffit, kit};
}

// Streaming geometry identity, shared by atlas and local reach keys.
// Authored geometry also invalidates bakes when render-only objects/terrain
// change. Device placement belongs to each light's key, never the atlas.
const renderMetadata = new Set(['tier', 'lod', 'lods', 'src', 'name', 'label', 'notes', 'plane_edges']);
const finishes = new Set(['materials', 'material', 'plane_materials', 'floor_material', 'ceiling_material', 'wall_material', 'tint']);
// Keep geometry records intact; only authored finish slots leave the bake domain.
// In particular an opening's model/asset, a pad's edge kind and every placement
// remain geometry. Empty material maps and absent maps have the same meaning.
export function withoutSurfaceMaterials(value) {
  if (Array.isArray(value)) return value.map(withoutSurfaceMaterials);
  if (!value || typeof value !== 'object') return value;
  const wall = value.from !== undefined && value.to !== undefined && value.level !== undefined;
  return Object.fromEntries(Object.entries(value).filter(([k]) => !finishes.has(k) && !(wall && k === 'faces'))
    .map(([k, v]) => [k, withoutSurfaceMaterials(v)]));
}
export function authoredGeometry(plan) {
  plan = withoutSurfaceMaterials(plan);
  const canonical = value => {
    if (Array.isArray(value)) return value.map(canonical);
    if (!value || typeof value !== 'object') return value;
    // flatten() mirrors person-owned active roof sections into legacy choices.
    // Assigning a finish can grow that UI list without changing any surface.
    return Object.fromEntries(Object.keys(value).sort().filter(k => !renderMetadata.has(k) &&
      !(k === 'choices' && Array.isArray(value.sections)))
      .map(k => [k, canonical(value[k])]));
  };
  const fields = ['id', 'position', 'rotation', 'base', 'foundation', 'materials', 'levels',
    'walls', 'openings', 'rooms', 'roof', 'porch', 'porches', 'stairs', 'items', 'solar_zones'];
  const siteFields = ['lot', 'terraces', 'pool', 'fire_pit', 'hardscape', 'beds', 'fence', 'planting', 'furniture', 'edges'];
  return JSON.stringify(canonical({ generatorVersion: plan.generatorVersion, materials: plan.materials,
    site: plan.site && Object.fromEntries(siteFields.filter(k => k in plan.site).map(k => [k, plan.site[k]])),
    buildings: plan.buildings?.map(b => Object.fromEntries(fields.filter(k => k in b).map(k => [k, b[k]]))) }));
}

const encoder=new TextEncoder();
export function fingerprint() {
  let a=0x811c9dc5,b=0x9e3779b9,c=0x85ebca6b,d=0xc2b2ae35;
  return {
    add(value) {
      // Chart keys and numeric JSON are ASCII. Avoid a short-lived encoded
      // buffer for every chart contribution; keep UTF-8 for arbitrary text.
      if (typeof value==='string' && /^[\x00-\x7f]*$/.test(value)) {
        for (let i=0;i<value.length;i++) {
          const x=value.charCodeAt(i);
          a=Math.imul(a^x,0x01000193); b=Math.imul(b^x,0x01000195);
          c=Math.imul(c^x,0x01000197); d=Math.imul(d^x,0x01000199);
        }
        return;
      }
      const bytes=typeof value==='string' ? encoder.encode(value) : new Uint8Array(value.buffer,value.byteOffset,value.byteLength);
      for (let i=0;i<bytes.length;i++) {
        const x=bytes[i];
        a=Math.imul(a^x,0x01000193); b=Math.imul(b^x,0x01000195);
        c=Math.imul(c^x,0x01000197); d=Math.imul(d^x,0x01000199);
      }
    },
    key:()=>[a,b,c,d].map(x=>(x>>>0).toString(16).padStart(8,'0')).join(''),
  };
}

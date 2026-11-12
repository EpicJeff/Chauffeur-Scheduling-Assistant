import * as THREE from 'three';

const FT = .3048;
export const schema = () => window.twinObjectSchema;
export const objectKind = (piece, collection) => piece.object_kind || (collection === 'planting' || ['tree', 'shrub'].includes(piece.kind) ? 'plant' : 'furniture');
export function propertyFields(piece, collection) {
  const s = schema();
  return { ...s.common, ...s.kinds[objectKind(piece, collection)] };
}
export const propertyValue = (piece, field, collection) => piece[field] ?? propertyFields(piece, collection)[field]?.default;
export const objectShown = (piece, editor) => (piece.visible_in || ['viewer', 'editor']).includes(editor ? 'editor' : 'viewer');

// glTF is metres, Y up. A wrapper preserves authored transforms and places the
// origin at bottom-centre without changing the model's physical size.
export function normaliseModel(source) {
  source.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(source);
  if (box.isEmpty()) throw new Error('The model has no visible geometry.');
  const centre = box.getCenter(new THREE.Vector3());
  const group = new THREE.Group();
  source.position.sub(new THREE.Vector3(centre.x, box.min.y, centre.z));
  group.add(source); group.updateMatrixWorld(true);
  return group;
}

export function suggestKind(size) {
  const [width, height, depth] = size.map(n => n / FT);
  if (depth < .5 && height > width && height >= 6.5 && height <= 8) return 'door';
  if (depth < .5) return 'window';
  return 'furniture';
}

export function modelBudget(root, { resizeTextures = true } = {}) {
  let triangles = 0;
  const textures = new Set();
  root.traverse(o => {
    if (o.isMesh) triangles += (o.geometry.index?.count || o.geometry.attributes.position?.count || 0) / 3 * (o.isInstancedMesh ? o.count : 1);
    for (const material of o.material ? [].concat(o.material) : [])
      for (const texture of Object.values(material)) if (texture?.isTexture) textures.add(texture);
  });
  if (triangles > 300000) throw new Error('This model exceeds 300,000 triangles. Simplify it before importing.');
  if (resizeTextures) for (const texture of textures) {
    const image = texture.image, width = image?.width, height = image?.height;
    if (!(Math.max(width, height) > 2048)) continue;
    const canvas = document.createElement('canvas'), ratio = 2048 / Math.max(width, height);
    canvas.width = Math.max(1, Math.round(width * ratio)); canvas.height = Math.max(1, Math.round(height * ratio));
    canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
    texture.image = canvas; texture.needsUpdate = true;
  }
  return { triangles, warning: triangles > 100000 ? 'Large model: over 100,000 triangles.' : null };
}

// Dimensions are plan feet. Model dimensions are metres; after fitting the
// geometry is in feet, like every other builder in twin_generator.
export function fitOpening(model, width, height, thickness) {
  model = normaliseModel(model);
  const box = new THREE.Box3().setFromObject(model), size = box.getSize(new THREE.Vector3());
  if (!(size.x > 0 && size.y > 0)) throw new Error('The opening model needs width and height.');
  const sx = width / size.x, sy = height / size.y;
  const sz = Math.min(sx, sy, thickness / Math.max(.00001, size.z));
  const wrapper = new THREE.Group(); wrapper.scale.set(sx, sy, sz); wrapper.add(model);
  return wrapper;
}

// Shared by the editor, viewer, yard and opening builders. Clone material
// instances before multiplying colour: changing one chair never tints another.
export function applyObject(model, piece, { units = 1 / FT, id = piece.id, rotate = true } = {}) {
  const axes = piece.scale_axes || [1, 1, 1], scale = piece.scale ?? 1;
  model.scale.multiply(new THREE.Vector3(axes[0] * scale * units, axes[1] * scale * units, axes[2] * scale * units));
  if (rotate) model.rotation.set(THREE.MathUtils.degToRad(piece.pitch || 0), THREE.MathUtils.degToRad(piece.rotation || 0), THREE.MathUtils.degToRad(piece.roll || 0), 'YXZ');
  const copies = new Map();
  model.traverse(o => {
    if (!o.isMesh) return;
    o.castShadow = piece.casts_shadow ?? true;
    const copy = source => {
      if (!piece.tint && piece.casts_shadow !== false && piece.object_kind !== 'lamp') return source;
      if (!copies.has(source)) {
        const material = source.clone();
        material.userData.castsShadow = piece.casts_shadow ?? true;
        if (piece.tint && material.color) material.color.multiply(new THREE.Color(piece.tint));
        if (piece.object_kind === 'lamp' && material.emissive) {
          material.emissive.set(piece.emissive_color || '#ffd89a');
          material.emissiveIntensity = piece.light_entity ? 0 : piece.emissive ? 1 : 0;
          material.userData.objectLight = { id, entity: piece.light_entity, on: !!piece.emissive, color: piece.emissive_color || '#ffd89a' };
        }
        copies.set(source, material);
      }
      return copies.get(source);
    };
    if (o.material) o.material = Array.isArray(o.material) ? o.material.map(copy) : copy(o.material);
  });
  return model;
}

export function objectOperation(record, properties) {
  return { op: 'set_object', ...(record.building ? { building: record.building.id, id: record.piece.id }
    : { list: record.kind, index: record.index }), properties };
}

export function transformObject(piece, action, reverse = false) {
  if (action === 'rotate') return { rotation: ((piece.rotation || 0) + (reverse ? -15 : 15) + 360) % 360 };
  return { scale: Math.max(.05, Math.min(20, (piece.scale ?? 1) * (reverse ? 1 / 1.1 : 1.1))) };
}

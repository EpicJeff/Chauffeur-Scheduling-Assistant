import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { twinGlass, twinText } from './palette.js';
import { LUCIDE } from '../vendor/lucide/icons.js';

const FT = .3048;
export const siteShapeLabels = { beds: 'Planting bed', hardscape: 'Path / hardscape', edges: 'Edge planting', pool: 'Pool', fire_pit: 'Fire pit', fence: 'Fence' };
export const siteShapeKinds = Object.keys(siteShapeLabels);
export const sitePoints = piece => piece.polygon || piece.points || piece.polyline || (piece.at ? [piece.at] : []);
export const sitePieces = value => Array.isArray(value) ? value : value ? [value] : [];
export function siteRecords(plan) {
  return ['planting', 'furniture', ...siteShapeKinds].flatMap(kind => {
    const value = plan?.site?.[kind], pieces = sitePieces(value);
    return pieces.map((piece, index) => ({ kind, index, building: null, piece: { ...piece, id: piece.id || `${kind}:${index}` } }));
  });
}
export const siteRecord = (plan, id) => siteRecords(plan).find(record => record.piece.id === id);
export const schema = () => window.twinObjectSchema;
export const objectKind = (piece, collection) => piece.object_kind || (collection === 'planting' || ['tree', 'shrub'].includes(piece.kind) ? 'plant' : 'furniture');
export function propertyFields(piece, collection) {
  const s = schema();
  return { ...s.common, ...s.kinds[objectKind(piece, collection)] };
}
export const propertyValue = (piece, field, collection) => piece[field] ?? propertyFields(piece, collection)[field]?.default;
export const objectShown = (piece, editor) => (piece.visible_in || ['viewer', 'editor']).includes(editor ? 'editor' : 'viewer');
export const objectMaterialKey = (piece, id) => JSON.stringify([piece.tint, piece.casts_shadow,
  piece.object_kind === 'lamp' ? [id, piece.emissive, piece.emissive_color, piece.light_entity] : null]);

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
  if (triangles > 1000000) throw new Error('This model exceeds 1,000,000 triangles. Simplify it before importing.');
  if (resizeTextures) for (const texture of textures) {
    const image = texture.image, width = image?.width, height = image?.height;
    if (!(Math.max(width, height) > 2048)) continue;
    const canvas = document.createElement('canvas'), ratio = 2048 / Math.max(width, height);
    canvas.width = Math.max(1, Math.round(width * ratio)); canvas.height = Math.max(1, Math.round(height * ratio));
    canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
    texture.image = canvas; texture.needsUpdate = true;
  }
  return { triangles, heavy: triangles > 300000,
    warning: triangles > 300000 ? `Heavy model: ${Math.round(triangles / 1000)}k triangles. It shows in full on the High setting; the wall panel shows a simple stand-in.`
      : triangles > 100000 ? 'Large model: over 100,000 triangles.' : null };
}

// Preserve physical material extensions except transmission, which would add
// a scene pre-pass. Reuse the converted instance across all matching meshes.
export function singlePassMaterial(material) {
  if (!(material.transmission > 0)) return material;
  const out = new THREE.MeshStandardMaterial();
  THREE.MeshStandardMaterial.prototype.copy.call(out, material);
  out.transparent = true;
  out.opacity = Math.max(.05, (material.opacity ?? 1) * (1 - material.transmission));
  out.depthWrite = false;
  return out;
}

export function mergeByMaterial(source) {
  source.updateMatrixWorld(true);
  const groups = new Map(), originals = new Set(), meshes = [];
  source.traverse(mesh => {
    // Animated/deformed geometry must retain its hierarchy and skin bindings.
    if (!mesh.isMesh || mesh.isSkinnedMesh || mesh.instanceColor || mesh.morphTexture || Object.keys(mesh.geometry.morphAttributes).length) return;
    if (!mesh.geometry.attributes.position) return;
    for (let p = mesh; p; p = p.parent) if (!p.visible) return;
    meshes.push(mesh); originals.add(mesh.geometry);
    const geo = mesh.geometry.index ? mesh.geometry.toNonIndexed() : mesh.geometry.clone();
    if (!geo.attributes.normal) geo.computeVertexNormals();
    const materials = [].concat(mesh.material);
    const ranges = Array.isArray(mesh.material) ? geo.groups : [{ start: 0, count: geo.attributes.position.count, materialIndex: 0 }];
    for (let instance = 0; instance < (mesh.isInstancedMesh ? mesh.count : 1); ++instance) {
      const matrix = mesh.matrixWorld.clone();
      if (mesh.isInstancedMesh) { const local = new THREE.Matrix4(); mesh.getMatrixAt(instance, local); matrix.multiply(local); }
      for (const range of ranges) {
        const start = Math.max(range.start, geo.drawRange.start), end = Math.min(range.start + range.count, geo.drawRange.start + geo.drawRange.count, geo.attributes.position.count);
        const material = materials[range.materialIndex];
        if (!material || end <= start) continue;
        const part = new THREE.BufferGeometry();
        for (const [key, attr] of Object.entries(geo.attributes)) {
          const values = new Float32Array((end - start) * attr.itemSize);
          for (let i = start; i < end; ++i) for (let c = 0; c < attr.itemSize; ++c) values[(i - start) * attr.itemSize + c] = attr.getComponent(i, c);
          part.setAttribute(key, new THREE.BufferAttribute(values, attr.itemSize));
        }
        part.applyMatrix4(matrix);
        // Mirroring changes winding. Restore it after baking the transform.
        if (matrix.determinant() < 0) for (const attr of Object.values(part.attributes)) {
          for (let i = 0; i + 2 < attr.count; i += 3) for (let c = 0; c < attr.itemSize; ++c) {
            const v = attr.getComponent(i, c); attr.setComponent(i, c, attr.getComponent(i + 2, c)); attr.setComponent(i + 2, c, v);
          }
        }
        if (!groups.has(material)) groups.set(material, []);
        groups.get(material).push(part);
      }
    }
    geo.dispose();
  });
  const result = new THREE.Group();
  result.add(source);
  for (const [material, parts] of groups) {
    const attributes = new Map();
    parts.forEach(part => Object.entries(part.attributes).forEach(([key, attr]) => attributes.set(key, Math.max(attributes.get(key) || 0, attr.itemSize))));
    // glTF can omit an optional attribute on some primitives of one material.
    for (const part of parts) for (const [key, size] of attributes) if (part.attributes[key]?.itemSize !== size) {
      const old = part.attributes[key];
      const values = new Float32Array(part.attributes.position.count * size);
      if (key === 'color') values.fill(1);
      if (key === 'tangent') for (let i = 0; i < values.length; i += size) { values[i] = 1; values[i + 3] = 1; }
      if (old) for (let i = 0; i < old.count; ++i) for (let c = 0; c < old.itemSize; ++c) values[i * size + c] = old.getComponent(i, c);
      part.setAttribute(key, new THREE.BufferAttribute(values, size));
    }
    const geometry = mergeGeometries(parts);
    if (!geometry) throw new Error('Could not merge the model geometry.');
    const mesh = new THREE.Mesh(geometry, material); mesh.castShadow = mesh.receiveShadow = true; result.add(mesh);
    parts.forEach(part => part.dispose());
  }
  // Keep non-mesh descendants and their transforms in the original hierarchy.
  for (const mesh of meshes) {
    const replacement = new THREE.Group(); THREE.Object3D.prototype.copy.call(replacement, mesh, false);
    if (mesh.children.length) replacement.add(...mesh.children);
    mesh.parent?.add(replacement); mesh.removeFromParent();
  }
  const retained = new Set(); source.traverse(o => { if (o.geometry) retained.add(o.geometry); });
  originals.forEach(g => { if (!retained.has(g)) g.dispose(); });
  return result;
}

export function heavyStandIn(size, kind) {
  const group = new THREE.Group(); group.userData.heavyStandIn = true;
  const rgb = twinGlass.match(/[\d.]+/g).map(Number);
  const material = new THREE.MeshStandardMaterial({ color: new THREE.Color().setRGB(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, THREE.SRGBColorSpace), transparent: true, opacity: rgb[3], depthWrite: false });
  const box = new THREE.Mesh(new THREE.BoxGeometry(...size.map(n => Math.max(.001, n))), material);
  box.position.y = size[1] / 2; group.add(box);
  if (kind === 'car') {
    const canvas = document.createElement('canvas'); canvas.width = canvas.height = 192;
    const ctx = canvas.getContext('2d'); ctx.scale(8, 8); ctx.strokeStyle = twinText; ctx.lineWidth = 1.5; ctx.lineCap = ctx.lineJoin = 'round';
    for (const [tag, a] of LUCIDE.car) {
      if (tag === 'path' && typeof Path2D === 'function') ctx.stroke(new Path2D(a.d));
      if (tag === 'circle') { ctx.beginPath(); ctx.arc(Number(a.cx), Number(a.cy), Number(a.r), 0, Math.PI * 2); ctx.stroke(); }
    }
    const texture = new THREE.CanvasTexture(canvas); texture.colorSpace = THREE.SRGBColorSpace;
    const glyph = new THREE.Mesh(new THREE.PlaneGeometry(Math.max(size[0], .1), Math.max(size[0], .1)), new THREE.MeshStandardMaterial({ map: texture, transparent: true, side: THREE.DoubleSide, depthWrite: false }));
    glyph.rotation.x = -Math.PI / 2; glyph.position.y = size[1] + .01; group.add(glyph);
  }
  return group;
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

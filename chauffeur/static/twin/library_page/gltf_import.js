import { Color, LoadingManager, LoaderUtils, Texture } from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

// A .glb or .gltf is untrusted: sizes are capped, URIs resolve only to the
// person's own chosen files or inline data (never the network), nothing is
// evaluated, and names stay text. Images are passed through as their original
// bytes; the server decodes, caps and re-encodes every map it accepts.
export const MAX_MODEL_BYTES = 256 * 1024 * 1024;
export const MAX_IMAGE_BYTES = 40 * 1024 * 1024; // The server's per-image cap.
const MODEL = /\.(glb|gltf)$/i;
const LABELS = { base_color: 'Base colour', normal: 'Normal', orm: 'ORM', roughness: 'Roughness', metalness: 'Metalness', ao: 'AO' };
const MB = bytes => `${Math.round(bytes / 1024 / 1024)} MB`;
const MISSING = 'blob:chf-gltf-missing';
// The import stops after the materials load: geometry is never decoded.
const MATERIALS_READ = { materialsRead: true };

function fileName(uri) {
  const last = String(uri).split(/[?#]/)[0].split(/[\\/]/).pop();
  try { return decodeURIComponent(last); } catch { return last; }
}

// The folder-relative path a URI names, for telling same-named files apart.
function uriPath(uri) {
  let path = String(uri).split(/[?#]/)[0];
  try { path = decodeURIComponent(path); } catch { /* Keep the raw text. */ }
  return path.replace(/\\/g, '/').replace(/^(\.\/)+/, '').toLowerCase();
}

function kind(head) {
  const text = String.fromCharCode(...head.slice(0, 12));
  if (head[0] === 0x89 && text.slice(1, 4) === 'PNG') return 'image/png';
  if (head[0] === 0xff && head[1] === 0xd8 && head[2] === 0xff) return 'image/jpeg';
  if (text.slice(0, 4) === 'RIFF' && text.slice(8, 12) === 'WEBP') return 'image/webp';
  return null;
}

const clamp = (value, low, high, fallback) => Number.isFinite(value) ? Math.min(high, Math.max(low, value)) : fallback;
const round = value => Math.round(value * 1e4) / 1e4;

/**
 * Read every material in a .glb, or a .gltf with its sibling .bin and texture
 * files, into Library terms: [{name, maps: {slot: Blob}, params, problems}].
 * A map that cannot be read is left out and named in `problems`.
 */
export async function readGltfMaterials(files, { maxModelBytes = MAX_MODEL_BYTES, maxImageBytes = MAX_IMAGE_BYTES } = {}) {
  files = Array.from(files || []);
  const models = files.filter(file => MODEL.test(file.name || ''));
  if (!models.length) throw new Error('Choose a .glb or .gltf file.');
  if (models.length > 1) throw new Error('Choose one .glb or .gltf file at a time, with its textures.');
  const [model] = models;
  if (model.size > maxModelBytes) throw new Error(`${model.name} is larger than ${MB(maxModelBytes)}.`);
  if (files.reduce((sum, file) => sum + file.size, 0) > maxModelBytes)
    throw new Error(`The chosen files are larger than ${MB(maxModelBytes)} together.`);
  // A file name the import cannot resolve to exactly one file is a problem,
  // never a guess: two chosen files with one name, or two paths in the model
  // (a/rough.png, b/rough.png) that both end in that name.
  const siblings = new Map(), clash = new Map();
  for (const file of files) {
    if (file === model) continue;
    const name = file.name.toLowerCase();
    if (siblings.has(name)) clash.set(name, `two chosen files are named ${file.name}`);
    siblings.set(name, file);
  }
  const owned = new Map();
  const manager = new LoadingManager();
  // Sibling textures and buffers resolve to the person's chosen files only.
  manager.setURLModifier(url => {
    if (/^data:/i.test(url) || owned.has(url)) return url;
    const name = fileName(url), file = siblings.get(name.toLowerCase());
    if (!file || clash.has(name.toLowerCase())) return MISSING;
    for (const [known, sibling] of owned) if (sibling === file) return known;
    const objectUrl = URL.createObjectURL(file); owned.set(objectUrl, file); return objectUrl;
  });
  const images = new Map();
  async function imageBlob(parser, index) {
    const image = parser.json.images?.[index];
    if (!image) throw new Error('the image is not in the file');
    let blob;
    if (image.bufferView !== undefined) {
      blob = new Blob([await parser.getDependency('bufferView', image.bufferView)]);
    } else if (typeof image.uri === 'string') {
      const conflict = clash.get(fileName(image.uri).toLowerCase());
      if (conflict) throw new Error(`${conflict}, so the import cannot tell which is which`);
      const url = manager.resolveURL(LoaderUtils.resolveURL(image.uri, ''));
      if (url === MISSING) throw new Error(`${fileName(image.uri)} is missing; choose it with the model`);
      if (owned.has(url)) blob = owned.get(url);
      else blob = await (await fetch(url)).blob(); // An inline data: URI.
    } else throw new Error('the image has no data');
    if (blob.size > maxImageBytes) throw new Error(`the image is larger than ${MB(maxImageBytes)}`);
    const type = kind(new Uint8Array(await blob.slice(0, 12).arrayBuffer()));
    if (!type) throw new Error('the image is not a PNG, JPEG or WebP');
    return new Blob([blob], { type });
  }
  let materials = [], parser;
  const loader = new GLTFLoader(manager);
  // Draco only compresses geometry, which this import never decodes.
  loader.setDRACOLoader({ preload() { return this; } });
  // First in line, so no texture is ever decoded: each texture records its
  // image source and the image's own bytes become the map.
  loader.pluginCallbacks.unshift(gltf => {
    const paths = new Map();
    for (const ref of [...(gltf.json.images || []), ...(gltf.json.buffers || [])]) {
      if (typeof ref.uri !== 'string' || /^data:/i.test(ref.uri)) continue;
      const name = fileName(ref.uri).toLowerCase();
      if (!paths.has(name)) paths.set(name, new Set());
      paths.get(name).add(uriPath(ref.uri));
    }
    for (const [name, found] of paths) if (found.size > 1) clash.set(name, `${[...found].join(' and ')} share a file name`);
    return {
      name: 'CHF_material_import',
      loadTexture(textureIndex) {
        const def = gltf.json.textures?.[textureIndex] || {}, ext = def.extensions || {};
        const source = def.source ?? ext.EXT_texture_webp?.source ?? ext.EXT_texture_avif?.source ?? ext.KHR_texture_basisu?.source;
        if (source !== undefined && !images.has(source)) {
          const read = imageBlob(gltf, source); read.catch(() => {}); images.set(source, read);
        }
        const texture = new Texture(); texture.userData.gltfImage = source; return Promise.resolve(texture);
      },
      async beforeRoot() { parser = gltf; materials = await gltf.getDependencies('material'); throw MATERIALS_READ; },
    };
  });
  try {
    await loader.parseAsync(await model.arrayBuffer(), '').catch(error => { if (error !== MATERIALS_READ) throw error; });
  } catch (error) {
    throw new Error(`${model.name} could not be read: ${error?.message || error}`);
  } finally {
    // Every image is read before the sibling URLs are released.
    await Promise.allSettled(images.values());
    owned.forEach((file, url) => URL.revokeObjectURL(url));
  }
  return Promise.all(materials.map(async (material, index) => {
    const def = parser.json.materials[index] || {}, maps = {}, problems = [];
    const imageOf = texture => texture?.userData?.gltfImage;
    const take = async (slots, image) => {
      if (image === undefined || !images.has(image)) return;
      try { const blob = await images.get(image); slots.forEach(slot => { maps[slot] = blob; }); }
      catch (error) {
        const uri = parser.json.images?.[image]?.uri;
        const named = uri && !/^data:/i.test(uri) ? ` (${fileName(uri)})` : '';
        problems.push(`${slots.map(slot => LABELS[slot]).join(' and ')}${named}: ${error.message}`);
      }
    };
    const rm = imageOf(material.roughnessMap), ao = imageOf(material.aoMap);
    await take(['base_color'], imageOf(material.map));
    await take(['normal'], imageOf(material.normalMap));
    // glTF packs roughness in G and metalness in B. Only an occlusion texture
    // in the same image makes R the AO, so only then is it a packed ORM; else
    // the image fills both single slots (three reads G and B) and R stays unused.
    if (rm !== undefined && rm === ao) await take(['orm'], rm);
    else { await take(['roughness', 'metalness'], rm); await take(['ao'], ao); }
    const pbr = def.pbrMetallicRoughness || {};
    // The Library has one UV set and its own tiling: say what did not carry over.
    for (const [info, slots] of [[pbr.baseColorTexture, ['base_color']], [def.normalTexture, ['normal']],
      [pbr.metallicRoughnessTexture, maps.orm ? ['orm'] : ['roughness', 'metalness']], [def.occlusionTexture, maps.orm ? [] : ['ao']]]) {
      if (!info || !slots.some(slot => maps[slot])) continue;
      const label = slots.map(slot => LABELS[slot]).join(' and ');
      if (info.extensions?.KHR_texture_transform) problems.push(`${label}: its texture transform (offset, scale or rotation) was not imported; set the tile size and rotation here.`);
      if (info.texCoord > 0) problems.push(`${label}: it uses a second UV set; the Library maps it onto the first.`);
    }
    // A factor of 1 over an imported map is Auto, so the material is not
    // drawn as flat chrome before its map loads or on the low tier.
    const packed = !!(maps.orm || maps.roughness);
    const factor = value => { const out = round(clamp(value, 0, 2, 1)); return packed && out === 1 ? null : out; };
    const unlit = !!def.extensions?.KHR_materials_unlit;
    const color = material.color instanceof Color ? material.color : new Color(1, 1, 1);
    const normalScale = material.normalScale ? Math.abs(material.normalScale.x) : 1;
    const name = String(material.name || def.name || '').replace(/[\u0000-\u001f\u007f]/g, ' ').trim().slice(0, 120);
    return {
      name: name || `${model.name.replace(MODEL, '')} material ${index + 1}`,
      maps,
      params: {
        alpha_mode: def.alphaMode === 'MASK' ? 'cutout' : def.alphaMode === 'BLEND' ? 'blend' : 'opaque',
        ...(def.alphaMode === 'MASK' ? { alpha_cutoff: round(clamp(def.alphaCutoff, .01, 1, .5)) } : {}),
        ...(def.alphaMode === 'BLEND' ? { opacity: round(clamp(pbr.baseColorFactor?.[3], 0, 1, 1)) } : {}),
        tint: '#' + color.getHexString(),
        // An unlit material (three's MeshBasicMaterial) has no factors of its own.
        roughness: factor(material.roughness ?? pbr.roughnessFactor ?? 1),
        metalness: unlit ? 0 : factor(material.metalness ?? pbr.metallicFactor ?? 1),
        normal_scale: round(clamp(normalScale, 0, 4, 1)),
        normal_convention: 'gl',
        ao_intensity: round(clamp(material.aoMapIntensity ?? 1, 0, 2, 1)),
      },
      problems,
    };
  }));
}

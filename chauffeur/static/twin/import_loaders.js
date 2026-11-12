import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { ColladaLoader } from 'three/addons/loaders/ColladaLoader.js';
import { KMZLoader } from 'three/addons/loaders/KMZLoader.js';
import { unzipSync, zipSync, strToU8, strFromU8 } from 'three/addons/libs/fflate.module.js';

const refusal = () => new Error('Imported models must use their included resources.');

function xml(text) {
  if (/<!DOCTYPE|<!ENTITY/i.test(text)) throw refusal();
  const doc = new DOMParser().parseFromString(text, 'application/xml');
  if (doc.getElementsByTagName('parsererror').length) throw new Error('The model XML is invalid.');
  return doc;
}

function resource(name, raw, files) {
  const uri = decodeURIComponent(raw.trim());
  if (!uri || /^[a-z][a-z\d+.-]*:|^[\\/]|[\\?#]/i.test(uri)) throw refusal();
  const parts = name.split('/').slice(0, -1);
  for (const part of uri.split('/')) {
    if (part === '..') { if (!parts.length) throw refusal(); parts.pop(); }
    else if (part && part !== '.') parts.push(part);
  }
  const path = parts.join('/');
  if (!Object.hasOwn(files, path)) throw refusal();
  return path;
}

function images(doc) {
  return [...doc.getElementsByTagName('library_images')].flatMap(library =>
    [...library.getElementsByTagName('image')].map(image => {
      const source = image.getElementsByTagName('init_from')[0];
      if (!source) throw refusal();
      return source;
    }));
}

class IncludedColladaLoader extends ColladaLoader {
  constructor(manager, name, files) { super(manager); this.modelName = name; this.files = files; }
  parse(text, path) {
    const doc = xml(text);
    for (const source of images(doc)) resource(this.modelName, source.textContent, this.files);
    return super.parse(text, path);
  }
}

class IncludedKMZLoader extends KMZLoader {
  constructor(manager) { super(manager); this.objectURLs = []; }
  parse(data) {
    const files = unzipSync(new Uint8Array(data));
    const models = Object.keys(files).filter(name => /\.(dae|gltf|glb)$/i.test(name));
    if (models.length !== 1 || !/\.dae$/i.test(models[0])) throw new Error('A KMZ must contain exactly one Collada model.');
    const name = models[0], doc = xml(strFromU8(files[name]));
    if (files['doc.kml']) {
      const href = xml(strFromU8(files['doc.kml'])).querySelector('Placemark Model Link href');
      if (!href || resource('doc.kml', href.textContent, files) !== name) throw refusal();
    }
    // The vendored KMZLoader uses a private manager and suffix-matches image
    // names. Supply exact, validated archive resources as owned blob URLs.
    // This also handles ../ textures beside a nested .dae without ambiguity.
    for (const source of images(doc)) {
      const path = resource(name, source.textContent, files);
      const url = URL.createObjectURL(new Blob([files[path]]));
      this.objectURLs.push(url);
      // Collada selects TGALoader from the filename before resolving the URL.
      source.textContent = url + (path.toLowerCase().endsWith('.tga') ? '#.tga' : '');
    }
    // Keep the real KMZ parser, without recompressing a second copy of textures.
    const packed = zipSync({
      [name]: strToU8(new XMLSerializer().serializeToString(doc)),
      'doc.kml': strToU8(`<kml><Placemark><Model><Link><href>${name.replaceAll('&', '&amp;').replaceAll('<', '&lt;')}</href></Link></Model></Placemark></kml>`),
    }, { level: 0 });
    return super.parse(packed.buffer);
  }
  release() { this.objectURLs.forEach(url => URL.revokeObjectURL(url)); this.objectURLs.length = 0; }
}

export function modelLoader(name, manager, files) {
  if (/\.dae$/i.test(name)) return new IncludedColladaLoader(manager, name, files);
  if (/\.kmz$/i.test(name)) return new IncludedKMZLoader(manager);
  return new GLTFLoader(manager);
}

// Collada returns its scene before TextureLoader/TGALoader finish. Wait before
// cloning, downscaling and making the thumbnail, including KMZ's private manager.
export async function colladaTexturesReady(scene) {
  const textures = new Set();
  scene.traverse(o => {
    for (const m of o.material ? [].concat(o.material) : [])
      for (const value of Object.values(m)) if (value?.isTexture) textures.add(value);
  });
  const end = Date.now() + 15000;
  while ([...textures].some(t => !t.version || !t.image?.width || !t.image?.height)) {
    if (Date.now() >= end) throw new Error('Could not load the included model textures.');
    await new Promise(resolve => setTimeout(resolve, 25));
  }
}

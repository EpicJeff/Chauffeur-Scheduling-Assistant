import * as THREE from 'three';

const appearance = ['name', 'map', 'alphaMap', 'alphaTest', 'transparent', 'opacity', 'side', 'depthTest', 'depthWrite',
  'colorWrite', 'vertexColors', 'flatShading', 'polygonOffset', 'polygonOffsetFactor', 'polygonOffsetUnits',
  'blending', 'premultipliedAlpha', 'alphaToCoverage', 'visible', 'wireframe'];

// A tiny neutral studio sphere, shared by all replacement materials in a view.
// No downloaded asset, scene lights, lightmaps, environment or shadow sampling.
function studioMatcap() {
  const size = 64, pixels = new Uint8Array(size * size * 4);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const nx = 2 * (x + .5) / size - 1, ny = 2 * (y + .5) / size - 1;
    const nz = Math.sqrt(Math.max(0, 1 - nx * nx - ny * ny));
    const value = Math.round(255 * Math.min(1, .58 + .42 * Math.max(0, -.35 * nx + .6 * ny + .72 * nz)));
    const i = (y * size + x) * 4;
    pixels[i] = pixels[i + 1] = pixels[i + 2] = value; pixels[i + 3] = 255;
  }
  const texture = new THREE.DataTexture(pixels, size, size);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.magFilter = texture.minFilter = THREE.LinearFilter;
  texture.needsUpdate = true;
  return texture;
}

export function createUnlit() {
  const swapped = new Map(), cache = new Map();
  let matcap;
  function replacement(source) {
    // Basic materials (sheet, markers, build previews and handles) already ignore lights.
    if (!source.isMeshStandardMaterial && !source.isMeshPhongMaterial && !source.isMeshLambertMaterial) return source;
    let record = cache.get(source);
    if (!record) {
      matcap ||= studioMatcap();
      const material = new THREE.MeshMatcapMaterial({ matcap });
      const dispose = () => { material.dispose(); source.removeEventListener('dispose', dispose); cache.delete(source); };
      source.addEventListener('dispose', dispose);
      record = { material, dispose }; cache.set(source, record);
    }
    const target = record.material;
    for (const key of appearance) {
      if (target[key] !== source[key]) { target[key] = source[key]; target.needsUpdate = true; }
    }
    target.color.copy(source.color);
    return target;
  }
  return {
    apply(root) {
      // Shared source materials are refreshed once per frame, even on a yard
      // with many instances. Late textures and edited colours still propagate.
      const refreshed = new Map();
      const sync = source => {
        if (!refreshed.has(source)) refreshed.set(source, replacement(source));
        return refreshed.get(source);
      };
      root?.traverse(object => {
        if (!object.isMesh || !object.material) return;
        const previous = swapped.get(object);
        if (previous && object.material === previous.next) {
          if (Array.isArray(previous.source)) previous.source.forEach(sync);
          else sync(previous.source);
          return;
        }
        const source = object.material;
        const next = Array.isArray(source) ? source.map(sync) : sync(source);
        swapped.set(object, { source, next, cast: previous?.cast ?? object.castShadow, receive: previous?.receive ?? object.receiveShadow });
        object.material = next; object.castShadow = object.receiveShadow = false;
      });
    },
    // Suspend before selection/floor styling or model disposal. Their owners
    // must always clone/dispose their own originals, never cached replacements.
    restore() {
      for (const [object, record] of swapped) {
        if (object.material === record.next) object.material = record.source;
        object.castShadow = record.cast; object.receiveShadow = record.receive;
      }
      swapped.clear();
    },
    dispose() {
      this.restore();
      for (const record of [...cache.values()]) record.dispose();
      matcap?.dispose();
    },
  };
}

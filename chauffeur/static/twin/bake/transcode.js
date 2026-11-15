// Worker-safe: do not import page materials or import-map-only modules here.
import * as THREE from '../../vendor/three-r187/three.module.js';

export function transcodePage(module, bytes, format) {
  const names = new Map([[THREE.RED_RGTC1_Format, 'cTFBC4_R'], [THREE.RED_GREEN_RGTC2_Format, 'cTFBC5_RG'],
    [THREE.R11_EAC_Format, 'cTFETC2_EAC_R11'], [THREE.RG11_EAC_Format, 'cTFETC2_EAC_RG11'], [THREE.RGBAFormat, 'cTFRGBA32']]);
  const fmt = module.transcoder_texture_format[names.get(format)]?.value;
  const k = new module.KTX2File(new Uint8Array(bytes));
  try {
    if (fmt === undefined || !k.isValid() || !k.startTranscoding()) throw new Error('Invalid compressed lightmap.');
    const width = k.getWidth(), height = k.getHeight(), mipmaps = [];
    for (let level = 0; level < k.getLevels(); level++) {
      const data = new Uint8Array(k.getImageTranscodedSizeInBytes(level, 0, 0, fmt));
      if (!k.transcodeImage(data, level, 0, 0, fmt, 0, -1, -1)) throw new Error('Could not transcode the lightmap.');
      mipmaps.push({ data, width: Math.max(1, width >> level), height: Math.max(1, height >> level) });
    }
    return { width, height, format, mipmaps };
  } finally { k.close(); k.delete(); }
}

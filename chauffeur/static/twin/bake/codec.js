export function encodePage(module, { width, height, channels }) {
  const px = new Uint8Array(width * height * 4);
  for (let i = 0; i < width * height; i++) {
    px[4 * i] = channels[0][i]; px[4 * i + 1] = channels[1]?.[i] || 0; px[4 * i + 3] = 255;
  }
  const e = new module.BasisEncoder();
  try {
    e.setCreateKTX2File(true); e.setKTX2UASTCSupercompression(true); e.setUASTC(true);
    e.setPackUASTCFlags(0); e.setPerceptual(false); e.setMipSRGB(false);
    e.setKTX2SRGBTransferFunc(false); e.setMipGen(true);
    if (channels.length > 1) { e.setSwizzle(0, 0, 0, 1); e.setForceAlpha(true); }
    else e.setCheckForAlpha(false);
    e.setSliceSourceImage(0, px, width, height, false);
    const bytes = new Uint8Array(width * height * 8 + 65536), n = e.encode(bytes);
    if (!n) throw new Error('Could not encode the lightmap.');
    return bytes.slice(0, n);
  } finally { e.delete(); }
}

export function decodePage(module, bytes) {
  const k = new module.KTX2File(new Uint8Array(bytes));
  try {
    if (!k.isValid() || !k.startTranscoding()) throw new Error('Invalid lightmap.');
    const width = k.getWidth(), height = k.getHeight(), fmt = module.transcoder_texture_format.cTFRGBA32.value;
    const rgba = new Uint8Array(k.getImageTranscodedSizeInBytes(0, 0, 0, fmt));
    if (!k.transcodeImage(rgba, 0, 0, 0, fmt, 0, -1, -1)) throw new Error('Could not decode the lightmap.');
    const channels = [new Uint8Array(width * height), new Uint8Array(width * height)];
    for (let i = 0; i < width * height; i++) { channels[0][i] = rgba[4 * i]; channels[1][i] = rgba[4 * i + 3]; }
    return { width, height, channels };
  } finally { k.close(); k.delete(); }
}


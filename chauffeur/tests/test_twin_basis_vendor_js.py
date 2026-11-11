"""Vendored Basis Universal + KTX2Loader for compressed house lightmaps
(plan .superpowers/sdd/2026-11-10-house-baked-lights, Task 0; rulings B4/B5).

A lightmap page is 1 channel (sky) or 2 channels (two room lights, each its
own channel). It ships as KTX2 (Basis UASTC) and is transcoded at load to a
1-/2-channel GPU format: BC4/BC5 on desktop GPUs, EAC R11/RG11 on the Pi.
Packed lights must never bleed into each other.

Runs the REAL vendored wasm under node:
  * the encoder (static/vendor/basis-universal) encodes 64x64 synthetic pages
    to UASTC KTX2 with mipmaps;
  * three r187's transcoder (static/vendor/three-r187/addons/libs/basis)
    transcodes them to BC5, EAC RG11, BC4, EAC R11 and RGBA32;
  * the blocks are decoded here (BC4/BC5 and EAC decoders in the driver) and
    compared with the source channels.

Basis v1.50 ignores transcodeImage's channel0/channel1 for UASTC: BC5/RG11
always take R and A. So a two-light page is encoded with setSwizzle(0,0,0,1)
(source R,G -> RGB = light 0, A = light 1); scenario_unswizzled_rg_loses_light_1
pins that behaviour so nobody hands RG straight to the encoder.

Also: the vendored files match the hashes in VENDORED.md, KTX2Loader's import
graph resolves through the repo's `three` / `three/addons/` import map, and
the add-on serves .wasm as application/wasm.

Skips the node scenarios when node is unavailable.
Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_basis_vendor_js.py
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_basis_vendor_'))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

VENDOR = os.path.join(ROOT, 'static', 'vendor')
THREE = os.path.join(VENDOR, 'three-r187')
ADDONS = os.path.join(THREE, 'addons')
ENCODER = os.path.join(VENDOR, 'basis-universal')
TRANSCODER = os.path.join(ADDONS, 'libs', 'basis')
VENDORED_MD = os.path.join(ENCODER, 'VENDORED.md')

KTX2_MAGIC = 'ab4b5458203230bb0d0a1a0a'  # «KTX 20»\r\n\x1a\n


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _node():
    return shutil.which('node')


DRIVER = r"""
const fs = require('fs');
const path = require('path');
const job = JSON.parse(process.argv[2]);
const W = 64, H = 64;

const EAC_TABLES = [
  [-3, -6, -9, -15, 2, 5, 8, 14], [-3, -7, -10, -13, 2, 6, 9, 12],
  [-2, -5, -8, -13, 1, 4, 7, 12], [-2, -4, -6, -13, 1, 3, 5, 12],
  [-3, -6, -8, -12, 2, 5, 7, 11], [-3, -7, -9, -11, 2, 6, 8, 10],
  [-4, -7, -8, -11, 3, 6, 7, 10], [-3, -5, -8, -11, 2, 4, 7, 10],
  [-2, -6, -8, -10, 1, 5, 7, 9], [-2, -5, -8, -10, 1, 4, 7, 9],
  [-2, -4, -8, -10, 1, 3, 7, 9], [-2, -5, -7, -10, 1, 4, 6, 9],
  [-3, -4, -7, -10, 2, 3, 6, 9], [-1, -2, -3, -10, 0, 1, 2, 9],
  [-4, -6, -8, -9, 3, 5, 7, 8], [-3, -5, -7, -9, 2, 4, 6, 8],
];

// BC4: two endpoints, 16 x 3-bit indices little-endian, row-major texels.
function bc4Block(b, o, out, bx, by) {
  const r0 = b[o], r1 = b[o + 1];
  const p = [r0, r1];
  if (r0 > r1) for (let k = 2; k < 8; k++) p.push(Math.round(((8 - k) * r0 + (k - 1) * r1) / 7));
  else { for (let k = 2; k < 6; k++) p.push(Math.round(((6 - k) * r0 + (k - 1) * r1) / 5)); p.push(0, 255); }
  let bits = 0;
  for (let i = 5; i >= 0; i--) bits = bits * 256 + b[o + 2 + i];
  for (let i = 0; i < 16; i++) {
    const idx = Math.floor(bits / 2 ** (3 * i)) % 8;
    out[(by * 4 + (i >> 2)) * W + bx * 4 + (i & 3)] = p[idx];
  }
}

// EAC R11 (unsigned): base, multiplier, table; 16 x 3-bit indices big-endian,
// texels down the columns. Expanded to 11 bits, reported as 8 bits.
function eacBlock(b, o, out, bx, by) {
  const base = b[o], mult = b[o + 1] >> 4, tab = EAC_TABLES[b[o + 1] & 15];
  let bits = 0;
  for (let i = 0; i < 6; i++) bits = bits * 256 + b[o + 2 + i];
  for (let j = 0; j < 16; j++) {
    const mod = tab[Math.floor(bits / 2 ** (45 - 3 * j)) % 8];
    let v = mult ? base * 8 + 4 + mod * mult * 8 : base * 8 + 4 + mod;
    v = Math.max(0, Math.min(2047, v));
    out[(by * 4 + (j & 3)) * W + bx * 4 + (j >> 2)] = Math.round(v * 255 / 2047);
  }
}

function decode(bytes, kind, channels) {
  const outs = [];
  for (let c = 0; c < channels; c++) outs.push(new Uint8Array(W * H));
  const bw = W / 4, stride = 8 * channels;
  for (let by = 0; by < H / 4; by++) for (let bx = 0; bx < bw; bx++) {
    const o = (by * bw + bx) * stride;
    for (let c = 0; c < channels; c++) (kind === 'bc' ? bc4Block : eacBlock)(bytes, o + 8 * c, outs[c], bx, by);
  }
  return outs;
}

// Synthetic pages: r = light 0 (or sky), g = light 1.
function page(name) {
  const r = new Uint8Array(W * H), g = new Uint8Array(W * H);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const i = y * W + x;
    if (name === 'two_lights') {
      // falloffs from opposite corners, each with its own shadow edge
      const d0 = Math.hypot(x - 8, y - 10), d1 = Math.hypot(x - 52, y - 50);
      r[i] = Math.round(Math.min(255, 12000 / (16 + d0 * d0) + 20) * (x > 40 && y < 30 ? 0.3 : 1));
      g[i] = Math.round(Math.min(255, 15000 / (20 + d1 * d1) + 10) * (y > 20 && x < 24 ? 0.25 : 1));
    } else if (name === 'r_only') {
      r[i] = Math.round(128 + 110 * Math.sin(x * 0.7) * Math.cos(y * 0.45));
      g[i] = 100;
    } else if (name === 'g_only') {
      r[i] = 100;
      g[i] = Math.round(128 + 110 * Math.sin(y * 0.7) * Math.cos(x * 0.45));
    } else if (name === 'sky') {
      r[i] = Math.round(Math.min(255, 30 + x * 3 + (y > 32 ? 40 : 0)));
    }
  }
  return { r, g };
}

function stats(src, got) {
  let max = 0, sum = 0, lo = 255, hi = 0;
  for (let i = 0; i < src.length; i++) {
    const d = Math.abs(src[i] - got[i]); max = Math.max(max, d); sum += d;
    lo = Math.min(lo, got[i]); hi = Math.max(hi, got[i]);
  }
  return { max, mean: +(sum / src.length).toFixed(3), range: hi - lo };
}

(async () => {
  const quiet = { print() {}, printErr() {} };
  const E = await require(path.join(job.encoder, 'basis_encoder.js'))({ ...quiet, wasmBinary: fs.readFileSync(path.join(job.encoder, 'basis_encoder.wasm')) });
  const T = await require(path.join(job.transcoder, 'basis_transcoder.js'))({ ...quiet, wasmBinary: fs.readFileSync(path.join(job.transcoder, 'basis_transcoder.wasm')) });
  E.initializeBasis(); T.initializeBasis();
  const F = T.transcoder_texture_format;
  const res = { ktx2Support: !!T.transcoderSupportsKTX2(), formats: {}, cases: {} };
  for (const k of ['cTFBC4_R', 'cTFBC5_RG', 'cTFETC2_EAC_R11', 'cTFETC2_EAC_RG11', 'cTFRGBA32']) res.formats[k] = F[k] ? F[k].value : null;

  // layout 'swz': source R,G -> swizzle to RGB = R, A = G (the two-light encoding)
  // layout 'rg' : source R,G handed straight in (what NOT to do)
  // layout 'r1' : source R only, G = B = 0 (the sky encoding)
  function encode(p, layout) {
    const px = new Uint8Array(W * H * 4);
    for (let i = 0; i < W * H; i++) {
      px[4 * i] = p.r[i]; px[4 * i + 1] = layout === 'r1' ? 0 : p.g[i]; px[4 * i + 2] = 0; px[4 * i + 3] = 255;
    }
    const e = new E.BasisEncoder();
    e.setCreateKTX2File(true); e.setKTX2UASTCSupercompression(false); e.setUASTC(true);
    e.setPerceptual(false); e.setMipSRGB(false); e.setKTX2SRGBTransferFunc(false); e.setMipGen(true);
    if (layout === 'swz') { e.setSwizzle(0, 0, 0, 1); e.setForceAlpha(true); }
    else e.setCheckForAlpha(false);
    e.setSliceSourceImage(0, px, W, H, false);
    const out = new Uint8Array(1 << 20);
    const n = e.encode(out); e.delete();
    return out.slice(0, n);
  }

  function transcode(ktx, fmt) {
    const k = new T.KTX2File(ktx);
    const info = { valid: !!k.isValid(), uastc: !!k.isUASTC(), w: k.getWidth(), h: k.getHeight(), levels: k.getLevels() };
    info.started = !!k.startTranscoding();
    const size = k.getImageTranscodedSizeInBytes(0, 0, 0, fmt);
    const dst = new Uint8Array(size);
    info.ok = !!k.transcodeImage(dst, 0, 0, 0, fmt, 0, -1, -1);
    info.size = size;
    info.mipsOk = true;
    for (let l = 1; l < info.levels; l++) {
      const s = k.getImageTranscodedSizeInBytes(l, 0, 0, fmt);
      if (!k.transcodeImage(new Uint8Array(s), l, 0, 0, fmt, 0, -1, -1)) info.mipsOk = false;
    }
    k.close(); k.delete();
    return { info, dst };
  }

  for (const name of job.cases) {
    const [pageName, layout] = name.split(':');
    const p = page(pageName);
    const ktx = encode(p, layout);
    const out = { bytes: ktx.length, magic: Buffer.from(ktx.slice(0, 12)).toString('hex'), targets: {} };
    const targets = layout === 'r1'
      ? [['bc4', F.cTFBC4_R.value, 'bc', 1], ['r11', F.cTFETC2_EAC_R11.value, 'eac', 1]]
      : [['bc5', F.cTFBC5_RG.value, 'bc', 2], ['rg11', F.cTFETC2_EAC_RG11.value, 'eac', 2]];
    for (const [tname, fmt, kind, ch] of targets) {
      const { info, dst } = transcode(ktx, fmt);
      const t = { ...info };
      if (info.ok) {
        const dec = decode(dst, kind, ch);
        t.r = stats(p.r, dec[0]);
        if (ch === 2) t.g = stats(p.g, dec[1]);
      }
      out.targets[tname] = t;
    }
    // uncompressed fallback source: RGBA32 straight from UASTC (light 1 is in A when swizzled)
    const ref = transcode(ktx, F.cTFRGBA32.value);
    if (ref.info.ok) {
      const rr = new Uint8Array(W * H), gg = new Uint8Array(W * H);
      for (let i = 0; i < W * H; i++) { rr[i] = ref.dst[4 * i]; gg[i] = ref.dst[4 * i + (layout === 'swz' ? 3 : 1)]; }
      out.targets.rgba32 = { ok: true, size: ref.info.size, r: stats(p.r, rr), g: layout === 'r1' ? null : stats(p.g, gg) };
    }
    res.cases[name] = out;
  }
  process.stdout.write(JSON.stringify(res));
})().catch(e => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
"""

IMPORT_DRIVER = r"""
import { registerHooks } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import fs from 'node:fs';
import path from 'node:path';
const job = JSON.parse(process.argv[2]);
registerHooks({
  resolve(spec, ctx, next) {
    if (spec === 'three') return { url: pathToFileURL(path.join(job.three, 'three.module.js')).href, shortCircuit: true };
    if (spec.startsWith('three/addons/')) return { url: pathToFileURL(path.join(job.three, 'addons', spec.slice('three/addons/'.length))).href, shortCircuit: true };
    return next(spec, ctx);
  },
});
const mod = await import('three/addons/loaders/KTX2Loader.js');
const L = mod.KTX2Loader;
const loaderUrl = pathToFileURL(path.join(job.three, 'addons', 'loaders', 'KTX2Loader.js')).href;
const wasm = fileURLToPath(new URL('../libs/basis/basis_transcoder.wasm', loaderUrl));
const js = fileURLToPath(new URL('../libs/basis/basis_transcoder.js', loaderUrl));
process.stdout.write(JSON.stringify({
  isClass: typeof L === 'function',
  bc4: L.TranscoderFormat.BC4, bc5: L.TranscoderFormat.BC5,
  wasmExists: fs.existsSync(wasm), jsExists: fs.existsSync(js),
}));
"""

_RESULT = {}


def _run_cases():
    if 'cases' in _RESULT:
        return _RESULT['cases']
    d = tempfile.mkdtemp(prefix='twin_basis_driver_')
    script = os.path.join(d, 'driver.cjs')
    with open(script, 'w', encoding='utf-8') as f:
        f.write(DRIVER)
    job = {'encoder': ENCODER, 'transcoder': TRANSCODER,
           'cases': ['two_lights:swz', 'r_only:swz', 'g_only:swz', 'two_lights:rg', 'sky:r1']}
    p = subprocess.run([_node(), script, json.dumps(job)], capture_output=True, text=True, timeout=180)
    check(p.returncode == 0, f'node driver failed: {p.stderr[-2000:]}')
    _RESULT['cases'] = json.loads(p.stdout)
    return _RESULT['cases']


def _target(case, target):
    t = _run_cases()['cases'][case]['targets'][target]
    check(t.get('ok'), f'{case} -> {target}: transcode failed {t}')
    return t


# ---- static checks -------------------------------------------------------

def _vendored_rows():
    rows = []
    with open(VENDORED_MD, encoding='utf-8') as f:
        text = f.read()
    section = None
    for line in text.splitlines():
        m = re.match(r'\| file \(under ([\w./-]+)/\)', line)
        if m:
            section = m.group(1)
            continue
        m = re.match(r'\|\s*([\w./-]+)\s*\|\s*(\d+)\s*\|\s*([0-9a-f]{64})\s*\|', line)
        if m and section:
            rows.append((os.path.join(VENDOR, section, m.group(1)), int(m.group(2)), m.group(3)))
    return rows


def scenario_vendored_files_match_their_recorded_hashes():
    rows = _vendored_rows()
    check(len(rows) == 10, f'VENDORED.md should list 10 files, found {len(rows)}')
    for path, size, digest in rows:
        check(os.path.isfile(path), f'missing vendored file {path}')
        with open(path, 'rb') as f:
            data = f.read()
        if not path.endswith('.wasm'):
            data = data.replace(b'\r\n', b'\n')  # a Windows checkout may add CRs
        check(len(data) == size, f'{path}: {len(data)} bytes, recorded {size}')
        check(hashlib.sha256(data).hexdigest() == digest, f'{path}: sha256 differs from VENDORED.md')


def scenario_licences_ship_with_the_code():
    for path, needle in ((os.path.join(ENCODER, 'LICENSE'), 'Apache License'),
                         (os.path.join(TRANSCODER, 'LICENSE'), 'Apache License'),
                         (os.path.join(THREE, 'LICENSE'), 'MIT License')):
        check(os.path.isfile(path), f'missing licence {path}')
        with open(path, encoding='utf-8') as f:
            check(needle in f.read(), f'{path} is not the expected licence')


def scenario_wasm_is_served_as_application_wasm():
    from fastapi.testclient import TestClient
    import main
    c = TestClient(main.app)
    for url in ('/static/vendor/three-r187/addons/libs/basis/basis_transcoder.wasm',
                '/static/vendor/basis-universal/basis_encoder.wasm'):
        r = c.get(url)
        check(r.status_code == 200, f'{url}: {r.status_code}')
        check(r.headers.get('content-type', '').split(';')[0] == 'application/wasm',
              f'{url}: content-type {r.headers.get("content-type")!r}')
        check(r.content[:4] == b'\x00asm', f'{url}: not a wasm module')


# ---- node scenarios ------------------------------------------------------

def scenario_ktx2loader_resolves_through_the_import_map():
    d = tempfile.mkdtemp(prefix='twin_basis_import_')
    script = os.path.join(d, 'import.mjs')
    with open(script, 'w', encoding='utf-8') as f:
        f.write(IMPORT_DRIVER)
    p = subprocess.run([_node(), script, json.dumps({'three': THREE})], capture_output=True, text=True, timeout=60)
    check(p.returncode == 0, f'KTX2Loader import failed: {p.stderr[-2000:]}')
    got = json.loads(p.stdout)
    check(got['isClass'], 'KTX2Loader is not exported as a class')
    check(got['bc4'] == 4 and got['bc5'] == 5, f'TranscoderFormat ids differ: {got}')
    check(got['wasmExists'] and got['jsExists'], f'loader cannot find its transcoder next to it: {got}')


def scenario_encoder_writes_uastc_ktx2_with_mips():
    res = _run_cases()
    check(res['ktx2Support'], 'transcoder build lacks KTX2 support')
    check(res['formats'] == {'cTFBC4_R': 4, 'cTFBC5_RG': 5, 'cTFETC2_EAC_R11': 20,
                             'cTFETC2_EAC_RG11': 21, 'cTFRGBA32': 13}, f'format ids: {res["formats"]}')
    for name, case in res['cases'].items():
        check(case['magic'] == KTX2_MAGIC, f'{name}: not a KTX2 file ({case["magic"]})')
        for tname, t in case['targets'].items():
            if tname == 'rgba32':
                continue
            check(t['valid'] and t['uastc'], f'{name}/{tname}: not valid UASTC {t}')
            check((t['w'], t['h'], t['levels']) == (64, 64, 7), f'{name}/{tname}: dims/levels {t}')


def scenario_two_lights_transcode_to_bc5_and_rg11():
    for target in ('bc5', 'rg11'):
        t = _target('two_lights:swz', target)
        check(t['size'] == 16 * 16 * 16, f'{target}: {t["size"]} bytes for 64x64 (16 B/block expected)')
        check(t['mipsOk'], f'{target}: a mip level failed to transcode')
        for ch in ('r', 'g'):
            s = t[ch]
            check(s['mean'] <= 1.5 and s['max'] <= 24, f'{target} light {ch}: error {s}')
            check(s['range'] >= 200, f'{target} light {ch}: lost its range {s}')


def scenario_packed_lights_stay_independent():
    # a pattern in one light leaves the other exactly flat (it was 100 everywhere)
    for case, busy, flat in (('r_only:swz', 'r', 'g'), ('g_only:swz', 'g', 'r')):
        for target in ('bc5', 'rg11'):
            t = _target(case, target)
            check(t[flat]['range'] <= 2 and t[flat]['max'] <= 2,
                  f'{case}/{target}: light {flat} picked up light {busy}: {t[flat]}')
            check(t[busy]['range'] >= 200 and t[busy]['mean'] <= 8,
                  f'{case}/{target}: light {busy} lost its pattern: {t[busy]}')


def scenario_one_channel_page_transcodes_to_bc4_and_r11():
    for target in ('bc4', 'r11'):
        t = _target('sky:r1', target)
        check(t['size'] == 16 * 16 * 8, f'{target}: {t["size"]} bytes for 64x64 (8 B/block expected)')
        check(t['mipsOk'], f'{target}: a mip level failed to transcode')
        check(t['r']['mean'] <= 1.0 and t['r']['max'] <= 8, f'{target}: error {t["r"]}')


def scenario_rgba32_fallback_reads_r_and_a():
    t = _target('two_lights:swz', 'rgba32')
    check(t['size'] == 64 * 64 * 4, f'rgba32 size {t["size"]}')
    check(t['r']['max'] <= 8 and t['g']['max'] <= 8, f'rgba32 (R, A) error {t}')
    t = _target('sky:r1', 'rgba32')
    check(t['r']['max'] <= 8, f'rgba32 sky error {t}')


def scenario_unswizzled_rg_loses_light_1():
    # Basis v1.50 transcodes UASTC -> BC5/RG11 from R and A, whatever channel
    # arguments are passed. Light 1 left in G arrives as flat alpha. If this
    # starts failing, the transcoder honours channels now: revisit the layout.
    for target in ('bc5', 'rg11'):
        t = _target('two_lights:rg', target)
        check(t['g']['range'] == 0, f'{target}: G unexpectedly carried through {t["g"]}')


STATIC = (
    scenario_vendored_files_match_their_recorded_hashes,
    scenario_licences_ship_with_the_code,
    scenario_wasm_is_served_as_application_wasm,
)
NODE = (
    scenario_ktx2loader_resolves_through_the_import_map,
    scenario_encoder_writes_uastc_ktx2_with_mips,
    scenario_two_lights_transcode_to_bc5_and_rg11,
    scenario_packed_lights_stay_independent,
    scenario_one_channel_page_transcodes_to_bc4_and_r11,
    scenario_rgba32_fallback_reads_r_and_a,
    scenario_unswizzled_rg_loses_light_1,
)


if __name__ == '__main__':
    scenarios = list(STATIC)
    if _node():
        scenarios += list(NODE)
    else:
        print('  skip  node is not available: the encode/transcode scenarios did not run')
    failed = []
    for fn in scenarios:
        try:
            fn()
        except Exception:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__)
            traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(scenarios) - len(failed)}/{len(scenarios)} passed')
    sys.exit(1 if failed else 0)

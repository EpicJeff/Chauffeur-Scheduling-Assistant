# Basis Universal + KTX2Loader (compressed house lightmaps)

Vendored 2026-11-10 for the baked room lights (plan
`.superpowers/sdd/2026-11-10-house-baked-lights`, rulings B4/B5). Files are
byte-for-byte copies of upstream; `tests/test_twin_basis_vendor_js.py` checks
the hashes below (text files compared with LF line endings).

## three.js r187 addons (MIT, `three-r187/LICENSE`)

Source: https://github.com/mrdoob/three.js tag `r187` (commit
7e89746a687bb88271253698fa108b1dd59825d0), path `examples/jsm/`, fetched from
`https://raw.githubusercontent.com/mrdoob/three.js/r187/examples/jsm/<path>`.
Placed under `static/vendor/three-r187/addons/` with the same relative layout,
so the import map's `three/addons/` prefix and the files' own relative imports
resolve unchanged.

| file (under three-r187/addons/) | bytes | sha256 |
|---|---|---|
| loaders/KTX2Loader.js | 37513 | 468143c5e5e6a3103eb262963c80a19c0e1a6490df4b6cdf383420b59c450942 |
| utils/WorkerPool.js | 3110 | 5ac7095fd566bc9ae48376055fd66edf27cb9ebbf9e1269dc206bfd4933ae9eb |
| math/ColorSpaces.js | 4290 | cc35c01c793cd17ccded7bc8142abffd3ce0d60dd6de8d5d216983bd05aee262 |
| libs/ktx-parse.module.js | 19932 | f40c491f6c44dde511268121f778a0050e73b1a15fd844c1ae2c78c73213eafc |
| libs/zstddec.module.js | 39754 | 5cbf818e842628a4464e748594a6deae18ceddda3c2f541e7b3a0ff5fc7611e2 |
| libs/basis/basis_transcoder.js | 57529 | 8478b5b6d6b74e7d3082b89f6417321d8d1dc0307f2b30d4484bb11b441696a1 |
| libs/basis/basis_transcoder.wasm | 527333 | 6cf17dc889352c42e9acf8897107978d127005fe3386c36a0e3845e27967630a |

`ktx-parse` and `zstddec` are Don McCurdy's MIT-licensed modules as three.js
redistributes them. The transcoder pair is Basis Universal v1.50
(Apache-2.0, copy at `libs/basis/LICENSE`): it is byte-identical to
BinomialLLC/basis_universal `webgl/transcoder/build/` at tag `v1_50_0_2`.

## Basis Universal encoder v1.50 (Apache-2.0, `LICENSE` here)

Source: https://github.com/BinomialLLC/basis_universal tag `v1_50_0_2`
(commit b76a431c6a39c07fe8bb2edf1cbf44781150ed6b), path
`webgl/encoder/build/`, fetched from
`https://raw.githubusercontent.com/BinomialLLC/basis_universal/v1_50_0_2/webgl/encoder/build/<file>`.
Same release as the transcoder above, so encoder and transcoder agree.

| file (under basis-universal/) | bytes | sha256 |
|---|---|---|
| basis_encoder.js | 112986 | 2c0aa2a648b6fc6006e116074a1dd075d6aaf1adb34d4bfd9818acd79e96537e |
| basis_encoder.wasm | 1735264 | dea2778b6d1705b4fdf12053e94cda0ac1cc4340a7e06911778a003ba785808a |
| LICENSE | 11357 | c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4 |

## Channel layout (v1.50 behaviour, tested)

v1.50's UASTC transcoder ignores the `channel0`/`channel1` arguments of
`KTX2File.transcodeImage`: BC5 and EAC RG11 always take **R and A**, BC4 and
EAC R11 take **R**. A two-light page is therefore encoded with
`setSwizzle(0, 0, 0, 1)` + `setForceAlpha(true)` (source R = light 0, source G =
light 1 becomes RGB = light 0, A = light 1); after transcoding the GPU texture
reads light 0 in `.r` and light 1 in `.g`. An uncompressed fallback built from
`cTFRGBA32` must read R and A. A one-channel (sky) page needs no swizzle.

`KTX2Loader` itself only chooses RGBA targets (ASTC, BC7, ETC2, BC1/3, PVRTC,
ETC1, RGBA32) for Basis files, so the BC4/BC5/EAC path calls the transcoder
directly.

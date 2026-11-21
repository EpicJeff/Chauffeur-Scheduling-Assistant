# three.js r187 (vendored)

Source: npm package `three@0.187.0` (https://registry.npmjs.org/three/-/three-0.187.0.tgz),
tarball integrity `sha512` verified against the registry's published value on 2026-11-12.
`addons/loaders/GLTFLoader.js` is byte-identical to the tarball's copy, confirming one release.

Files under `addons/` are copied unchanged from `package/examples/jsm/`.

Added 2026-11-12 for Collada (.dae) and KMZ model import (sha256, first 16 hex):

| File | sha256 |
| --- | --- |
| addons/loaders/ColladaLoader.js | 539406f55a8b7aaa |
| addons/loaders/collada/ColladaComposer.js | eb262d262790a59d |
| addons/loaders/collada/ColladaParser.js | d9532ab17f1d9e29 |
| addons/loaders/TGALoader.js | 034c95f0a27380ec |
| addons/loaders/KMZLoader.js | 81abc97533bff5b1 |
| addons/libs/fflate.module.js | 4ab9828cf361a800 |

Added 2026-11-12 for level-of-detail export (same verified tarball):

| File | sha256 |
| --- | --- |
| addons/exporters/GLTFExporter.js | 569793baeba62bae |

Added 2026-11-17 for screen-space sky occlusion and bloom (same tarball, sha512 re-verified against the registry that day):

| File | sha256 |
| --- | --- |
| addons/postprocessing/EffectComposer.js | 4e079a5886152d7e |
| addons/postprocessing/Pass.js | 444b409c235ead98 |
| addons/postprocessing/RenderPass.js | 817f6c3cdcd0fd41 |
| addons/postprocessing/ShaderPass.js | e2500a5913b26bbf |
| addons/postprocessing/MaskPass.js | 7cd08eee9d5d6f55 |
| addons/postprocessing/GTAOPass.js | 78f278563029f53a |
| addons/postprocessing/OutputPass.js | 02e4a261af34de71 |
| addons/postprocessing/UnrealBloomPass.js | ba8f2fcadfa65883 |
| addons/shaders/CopyShader.js | a33057d5ac91c433 |
| addons/shaders/GTAOShader.js | f7663d7726e884ce |
| addons/shaders/PoissonDenoiseShader.js | b07ccfcdcd74f83c |
| addons/shaders/OutputShader.js | 353479f77a8d7e26 |
| addons/shaders/LuminosityHighPassShader.js | 5044f780b6e6cf86 |
| addons/math/SimplexNoise.js | 4b1455617135e6b4 |

## Local patch to `three.module.js` (2026-11-20)

`three.module.js` is no longer byte-identical to the tarball. One change, in
`WebGLRenderer.render`, where a finished render pops its render state: the
texture-unit counter handed back to the caller is the one the popped (nested)
render saved at its own start. r187 handed back the count the outer render had
at its start. A render nested inside `setProgram` (three regenerating a
reflection probe's PMREM for the material being set up) therefore restarted
that material's samplers after the previous frame's last material: on the
owner's 16-unit GPU (ANGLE D3D11) the pool water asked for units 17 to 21 and
those textures never bound. Search for `Chauffeur patch` to find it.
Guarded by `tests/test_twin_texture_units_live.py`. Reapply on any three upgrade
unless upstream has fixed it.

License: MIT (see LICENSE). fflate is MIT.

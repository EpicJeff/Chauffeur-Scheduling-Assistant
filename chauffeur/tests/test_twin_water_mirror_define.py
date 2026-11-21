"""The pool mirror's own branch must compile against the vendored three.

From v2.499.917 to .927 the water shader tested ENVMAP_TYPE_CUBE_UV, a name
three r187 no longer defines (it says ENVMAP_TYPE_PMREM), so the steady mirror
share never compiled and a sunlit pool mirrored almost nothing. This pins the
define the water branch tests to the one three's getIBLRadiance tests.

Run from chauffeur/: python tests/test_twin_water_mirror_define.py
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
THREE = ROOT / 'static/vendor/three-r187/three.module.js'
WATER = ROOT / 'static/twin/effects/water_surface.js'


def _three_ibl_define():
    text = THREE.read_text(encoding='utf-8')
    body = text[text.index('vec3 getIBLRadiance('):]
    match = re.search(r'#ifdef (ENVMAP_TYPE_\w+)', body[:600])
    assert match, 'three getIBLRadiance no longer tests an ENVMAP_TYPE define'
    return match.group(1)


def test_water_mirror_branch_tests_the_define_three_sets():
    define = _three_ibl_define()
    water = WATER.read_text(encoding='utf-8')
    line = next(l for l in water.splitlines() if l.startswith('#if') and 'USE_ENVMAP' in l and 'ENVMAP_TYPE' in l)
    assert f'defined( {define} )' in line, (define, line)


def test_mirror_share_uses_the_tuned_power():
    water = WATER.read_text(encoding='utf-8')
    power = float(re.search(r'export const WATER_MIRROR_POWER = ([\d.]+);', water).group(1))
    assert 2 <= power < 5, power
    assert 'pow(max(0.0, 1.0 - abs(dot(waterSteady, waterView))), ${WATER_MIRROR_POWER.toFixed(1)})' in water
    # Head-on the water still mirrors only two percent; at a standing eye
    # height over a pool (about 60 degrees off the normal) it mirrors much more
    # than Schlick's five gives.
    head_on = .02 + .98 * (1 - 1) ** power
    standing = .02 + .98 * (1 - .5) ** power
    assert abs(head_on - .02) < 1e-9
    assert standing > 2.5 * (.02 + .98 * .5 ** 5)


if __name__ == '__main__':
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print('ok  ', name)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print('FAIL', name, exc)
    print(f'{2 - failed}/2 passed')
    sys.exit(1 if failed else 0)

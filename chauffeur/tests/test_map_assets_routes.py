"""The two server-side pieces the vector map needs.

1. `.mjs` must be served as JavaScript. Browsers refuse to run a module with
   any other MIME type, and Python's mimetypes table does not reliably know
   `.mjs` — so the map would be blank on exactly the platforms that lack it.
2. Glyph ranges we did not vendor are answered with a valid EMPTY glyph set,
   so a street name in another script draws without those characters instead
   of failing the whole tile it sits on.

TestClient needs httpx, which is not installed here, so the endpoint function
is called directly (the tests/test_packing_api.py pattern).

Run from chauffeur/:  python tests/test_map_assets_routes.py
"""
import mimetypes
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_map_assets_'))

import main  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from services import auth  # noqa: E402

GLYPHS = os.path.join(main.STATIC_DIR, 'vendor', 'map-style', 'glyphs')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def scenario_mjs_is_javascript():
    check(mimetypes.guess_type('maplibre-gl.mjs')[0] == 'text/javascript',
          f".mjs guessed as {mimetypes.guess_type('maplibre-gl.mjs')[0]!r}")


def scenario_a_vendored_range_is_served_as_is():
    r = main.map_glyphs('noto_sans_regular', '0-255')
    with open(os.path.join(GLYPHS, 'noto_sans_regular', '0-255.pbf'), 'rb') as f:
        check(r.body == f.read(), 'vendored range must be served byte for byte')
    check(r.media_type == 'application/x-protobuf', r.media_type)
    check('max-age' in r.headers.get('cache-control', ''), 'glyphs must be cacheable')


def scenario_a_missing_range_is_a_valid_empty_glyph_set():
    r = main.map_glyphs('noto_sans_bold', '1536-1791')
    expected = (b'\x0a\x1b'                       # glyphs.stacks, length 27
                b'\x0a\x0enoto_sans_bold'         # fontstack.name
                b'\x12\x091536-1791')             # fontstack.range
    check(r.body == expected, f'empty glyph set wrong: {r.body!r}')
    check(main._empty_glyphs('noto_sans_bold', '1536-1791') == expected, 'helper disagrees')


def scenario_unknown_stacks_and_bad_ranges_are_refused():
    for stack, rng in (('arial', '0-255'), ('noto_sans_regular', 'abc'),
                       ('../secrets', '0-255'), ('noto_sans_regular', '0-255/../x')):
        try:
            main.map_glyphs(stack, rng)
        except HTTPException as e:
            check(e.status_code == 400, f'{stack}/{rng}: {e.status_code}')
        else:
            raise AssertionError(f'{stack}/{rng} should be refused')


def scenario_the_route_is_public_and_registered_before_the_mount():
    template = '/static/vendor/map-style/glyphs/{fontstack}/{glyph_range}.pbf'
    check(auth.resolve('GET', template) == auth.ANYONE, 'glyph route must be ANYONE')
    paths = [getattr(r, 'path', None) for r in main.app.routes]
    check(template in paths, 'glyph route not registered')
    check(paths.index(template) < paths.index('/static'),
          'glyph route must be registered before the /static mount or the mount swallows it')


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith('scenario_')]

if __name__ == '__main__':
    for fn in SCENARIOS:
        fn()
        print(f'  ok  {fn.__name__}')
    print(f'\n{len(SCENARIOS)}/{len(SCENARIOS)} map asset route scenarios passed')

"""The vendored vector-map assets are what the family map expects.

The map is drawn from files committed under static/vendor/ (tools/vendor_assets.py
writes them). A re-vendor that renamed a file, dropped a glyph range or picked up
a style that references a font stack we did not ship would fail only in a
browser, on the wall, as a blank or label-less map. These pins catch it here.

Run from chauffeur/:  python tests/test_map_vendor.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import vendor_assets as va  # noqa: E402

VENDOR = os.path.join(HERE, 'static', 'vendor')
LIB = os.path.join(VENDOR, 'maplibre')
STYLE = os.path.join(VENDOR, 'map-style')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def read(path, mode='r'):
    with open(path, mode, **({} if 'b' in mode else {'encoding': 'utf-8'})) as f:
        return f.read()


def scenario_maplibre_is_the_pinned_v6_module_with_its_worker_beside_it():
    head = read(os.path.join(LIB, 'maplibre-gl.mjs'))[:400]
    check(f'v{va.MAPLIBRE}' in head, f'maplibre-gl.mjs is not v{va.MAPLIBRE}: {head[:200]!r}')
    # The module finds its worker beside itself via import.meta.url.
    check(os.path.getsize(os.path.join(LIB, 'maplibre-gl-worker.mjs')) > 100_000,
          'maplibre-gl-worker.mjs missing or truncated')
    check(os.path.getsize(os.path.join(LIB, 'maplibre-gl.css')) > 10_000, 'maplibre-gl.css missing')


def scenario_the_plugin_is_the_umd_build_reading_globals():
    src = read(os.path.join(LIB, 'leaflet-maplibre-gl.js'))
    check('global.maplibregl' in src and 'global.L' in src,
          'leaflet-maplibre-gl.js must be the UMD build that reads window.L and window.maplibregl')
    check('L.maplibreGL = maplibreGL' in src, 'the plugin must register L.maplibreGL')


def scenario_styles_are_stored_unmodified_and_reference_only_what_we_ship():
    shipped_sprites = {n.rsplit('.', 1)[0].replace('@2x', '') for n in va.MAP_SPRITES}
    for name in va.MAP_STYLES:
        style = json.loads(read(os.path.join(STYLE, f'{name}.json')))
        src = style['sources']['versatiles-shortbread']
        # Unmodified: the rewrite to OSMF happens in the browser, not here.
        check(src['type'] == 'vector' and src['tiles'][0].startswith('https://tiles.versatiles.org/'),
              f'{name}.json was modified on disk; the rewrite belongs in family_map_core.html')
        stacks = set()
        for layer in style['layers']:
            font = layer.get('layout', {}).get('text-font')
            if isinstance(font, list):
                stacks.add(','.join(font))
        check(stacks <= set(va.MAP_FONTSTACKS),
              f'{name}.json uses font stacks we do not ship: {stacks - set(va.MAP_FONTSTACKS)}')
        ids = {s['url'].rsplit('/', 1)[-1] for s in style['sprite']}
        check(ids <= shipped_sprites, f'{name}.json uses sprites we do not ship: {ids - shipped_sprites}')


def scenario_every_shipped_stack_has_every_range():
    for stack in va.MAP_FONTSTACKS:
        for rng in va.MAP_GLYPH_RANGES:
            path = os.path.join(STYLE, 'glyphs', stack, f'{rng}.pbf')
            check(os.path.isfile(path) and os.path.getsize(path) > 1000, f'missing glyphs {stack}/{rng}')
    for name in va.MAP_SPRITES:
        check(os.path.isfile(os.path.join(STYLE, 'sprites', name)), f'missing sprite {name}')


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith('scenario_')]

if __name__ == '__main__':
    for fn in SCENARIOS:
        fn()
        print(f'  ok  {fn.__name__}')
    print(f'\n{len(SCENARIOS)}/{len(SCENARIOS)} map vendor scenarios passed')

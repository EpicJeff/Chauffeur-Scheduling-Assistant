"""The family map, drawn in a real browser: vector when it can be, raster when not.

All tile hosts are stubbed, so this never touches OpenStreetMap: OSMF's
TileJSON and an empty .mvt for the vector path, a 1x1 PNG for the raster
path, and VersaTiles' own tile host recorded and refused (the style rewrite
must have pointed MapLibre away from it).

Run from chauffeur/:  python tests/test_family_map_live.py
"""
import base64
import json
import os
import re
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_family_map_live_'))

from live_app import live_app  # noqa: E402
from services import storage, ha_api  # noqa: E402

TILEJSON = {'tilejson': '3.0.0', 'minzoom': 0, 'maxzoom': 14,
            'tiles': ['https://vector.openstreetmap.org/shortbread_v1/{z}/{x}/{y}.mvt']}
PNG_1X1 = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')
STATES = {
    'person.ana': {'entity_id': 'person.ana', 'state': 'not_home',
                   'last_updated': '2026-10-08T12:00:00+00:00',
                   'attributes': {'latitude': 35.80, 'longitude': -78.64}},
    'person.ben': {'entity_id': 'person.ben', 'state': 'school',
                   'last_updated': '2026-10-08T12:00:00+00:00',
                   'attributes': {'latitude': 35.83, 'longitude': -78.60}},
    'zone.home': {'entity_id': 'zone.home', 'state': '0',
                  'attributes': {'latitude': 35.81, 'longitude': -78.62}},
}


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def seed():
    for mid, name, ent in (('m1', 'Ana', 'person.ana'), ('m2', 'Ben', 'person.ben')):
        storage.add_member({'id': mid, 'name': name, 'color_code': '#3b82f6', 'avatar': None,
                            'bio': '', 'can_drive': False, 'is_child': False, 'driver_id': None,
                            'passenger_id': None, 'ha_person_entity': ent, 'notify_service': None,
                            'media_player_entity': None, 'pin': None, 'created_at': time.time()})
    ha_api.get_state = lambda e, *a, **kw: STATES.get(e)
    ha_api.get_states = lambda *a, **kw: list(STATES.values())


class Tiles:
    """Stubs every tile host on a page and records what was asked for."""
    def __init__(self, page):
        self.tilejson, self.mvt, self.raster, self.versatiles = [], [], [], []
        page.route('https://vector.openstreetmap.org/**', self._osmf)
        page.route('https://tile.openstreetmap.org/**', self._raster)
        page.route('https://tiles.versatiles.org/**', self._versatiles)

    def _osmf(self, route):
        url = route.request.url
        if url.endswith('tilejson.json'):
            self.tilejson.append(url)
            route.fulfill(status=200, content_type='application/json', body=json.dumps(TILEJSON),
                          headers={'Access-Control-Allow-Origin': '*'})
        else:
            self.mvt.append(url)
            route.fulfill(status=200, content_type='application/x-protobuf', body=b'',
                          headers={'Access-Control-Allow-Origin': '*'})

    def _raster(self, route):
        self.raster.append(route.request.url)
        route.fulfill(status=200, content_type='image/png', body=PNG_1X1)

    def _versatiles(self, route):
        self.versatiles.append(route.request.url)
        route.abort()


def has_webgl2(page):
    return page.evaluate("!!document.createElement('canvas').getContext('webgl2')")


def open_map(page, served):
    page.goto(served.url('map'))
    page.wait_for_function("typeof _fmInstance !== 'undefined' && _fmInstance && _fmInstance.base")
    page.wait_for_selector('#family-map .leaflet-marker-icon')


def scenario_vector_map_on_the_map_page(served):
    with served.browser() as page:
        tiles = Tiles(page)
        page.goto(served.url('map'))
        if not has_webgl2(page):
            print('  skip  this chromium has no WebGL2 — vector scenarios not run')
            return False
        open_map(page, served)
        page.wait_for_function("_fmInstance.base === 'vector'")
        check(page.locator('#family-map.fm-vector canvas.maplibregl-canvas').count() == 1,
              'one MapLibre canvas inside the map container')
        check(page.locator('#family-map .leaflet-marker-icon').count() == 2, 'both members pinned')
        page.locator('#family-map .leaflet-marker-icon').first.click()
        page.wait_for_selector('#family-map .leaflet-popup-content')
        page.wait_for_function("_fmInstance.baseLayer.getMaplibreMap().isStyleLoaded()")
        check(tiles.tilejson, 'MapLibre must resolve tiles from the OSMF TileJSON')
        check(not tiles.versatiles, f'the style rewrite missed: {tiles.versatiles[:2]}')
        check(not tiles.raster, 'no raster tiles when vector works')
        # /map is an admin page (html.dark), so it is a dark map.
        check(page.evaluate("_fmInstance.theme") == 'dark', 'admin page should resolve dark')
        check(page.evaluate("_fmInstance.baseLayer.getMaplibreMap().getStyle().name")
              == 'versatiles-colorful-dark', 'dark should load the eclipse style')
        check(page.locator('#family-map .leaflet-control-attribution').inner_text().find('OpenStreetMap') >= 0,
              'OSM credit visible')
        check(page.locator('#family-map .maplibregl-ctrl-attrib').count() == 0,
              "MapLibre's own attribution must be off (credit shown once)")
        check(not served.errors(), served.errors())
    return True


def scenario_theme_follows_the_page_and_the_last_flip_wins(served):
    with served.browser() as page:
        Tiles(page)
        open_map(page, served)
        page.wait_for_function("_fmInstance.base === 'vector'")
        page.evaluate("document.documentElement.setAttribute('data-theme', 'light')")
        page.wait_for_function(
            "_fmInstance.baseLayer.getMaplibreMap().getStyle().name === 'versatiles-colorful'")
        check(page.locator('#family-map .leaflet-marker-icon').count() == 2, 'markers survive a restyle')
        # Rapid flips: dark, light, dark before any style lands -> ends dark.
        page.evaluate("""() => { const r = document.documentElement;
            r.setAttribute('data-theme', 'dark'); r.setAttribute('data-theme', 'light');
            r.setAttribute('data-theme', 'dark'); }""")
        page.wait_for_function("_fmInstance.theme === 'dark'")
        page.wait_for_timeout(800)
        check(page.evaluate("_fmInstance.baseLayer.getMaplibreMap().getStyle().name")
              == 'versatiles-colorful-dark', 'the last flip must win')
        check(page.evaluate("document.getElementById('family-map').classList.contains('fm-dark')"),
              'dark vector map carries fm-dark')
        check(not served.errors(), served.errors())


def scenario_resolver_and_asset_base(served):
    with served.browser() as page:
        Tiles(page)
        page.goto(served.url('map'))
        page.wait_for_function("window.FamilyMap && FamilyMap.mapTheme")
        got = page.evaluate("""() => { const r = document.documentElement, out = [];
            r.setAttribute('data-panel-theme', 'light'); out.push(FamilyMap.mapTheme());
            r.setAttribute('data-panel-theme', 'dark'); out.push(FamilyMap.mapTheme());
            r.removeAttribute('data-panel-theme');
            r.setAttribute('data-theme', 'light'); out.push(FamilyMap.mapTheme());
            r.removeAttribute('data-theme'); out.push(FamilyMap.mapTheme());
            return out; }""")
        check(got == ['light', 'dark', 'light', 'dark'], f'resolver order wrong: {got}')
        # Review Focus 1: a two-deep route climbs with apiBase, and ingress is
        # never climbed out of.
        got = page.evaluate("""() => [
            FamilyMap.assetBase('../', 'http://h/board/kitchen'),
            FamilyMap.assetBase('', 'http://h/api/hassio_ingress/tok/map'),
            FamilyMap.assetBase('../', 'http://h/api/hassio_ingress/tok/board/kitchen'),
            FamilyMap.assetBase('')]""")
        check(got[0] == 'http://h/static/vendor/map-style/', f'board route: {got[0]}')
        check(got[1] == 'http://h/api/hassio_ingress/tok/static/vendor/map-style/', f'ingress: {got[1]}')
        check(got[2] == 'http://h/api/hassio_ingress/tok/static/vendor/map-style/',
              f'board under ingress: {got[2]}')
        check(got[3] == served.url('static/vendor/map-style/'), f'this page: {got[3]}')
        style = page.evaluate("""() => FamilyMap.rewriteStyle({sources: {s: {type: 'vector',
                tiles: ['https://tiles.versatiles.org/tiles/osm/{z}/{x}/{y}']}},
                sprite: [{id: 'base', url: 'https://tiles.versatiles.org/assets/sprites/base'}],
                glyphs: 'https://tiles.versatiles.org/assets/glyphs/{fontstack}/{range}.pbf',
                layers: []}, 'http://h/x/static/vendor/map-style/')""")
        check(style['sources']['s'] == {'type': 'vector',
              'url': 'https://vector.openstreetmap.org/shortbread_v1/tilejson.json'}, style['sources'])
        check(style['glyphs'] == 'http://h/x/static/vendor/map-style/glyphs/{fontstack}/{range}.pbf',
              style['glyphs'])
        check(style['sprite'] == [{'id': 'base', 'url': 'http://h/x/static/vendor/map-style/sprites/base'}],
              style['sprite'])


def scenario_raster_when_there_is_no_webgl2(served):
    with served.browser() as page:
        tiles = Tiles(page)
        page.add_init_script("""const real = HTMLCanvasElement.prototype.getContext;
            HTMLCanvasElement.prototype.getContext = function (kind, ...a) {
                if (/webgl/.test(kind)) return null; return real.call(this, kind, ...a); };""")
        open_map(page, served)
        check(page.evaluate("_fmInstance.base") == 'raster', 'no WebGL2 means raster')
        check(page.evaluate("typeof maplibregl") == 'undefined', 'MapLibre is never even loaded')
        check(page.locator('#family-map.fm-raster').count() == 1, 'container marked fm-raster')
        page.wait_for_function("document.querySelectorAll('#family-map .leaflet-tile-loaded').length > 0")
        check(tiles.raster and not tiles.tilejson, 'raster tiles only')
        check(page.locator('#family-map .leaflet-marker-icon').count() == 2, 'markers on raster')
        check(not served.errors(), served.errors())


def scenario_context_loss_drops_to_raster_and_keeps_the_pins(served):
    with served.browser() as page:
        tiles = Tiles(page)
        open_map(page, served)
        page.wait_for_function("_fmInstance.base === 'vector'")
        page.evaluate("""_fmInstance.baseLayer.getMaplibreMap().getCanvas()
            .getContext('webgl2').getExtension('WEBGL_lose_context').loseContext()""")
        page.wait_for_function("_fmInstance.base === 'raster'", timeout=10000)
        check(page.locator('#family-map.fm-raster').count() == 1, 'container flipped to fm-raster')
        check(page.locator('#family-map canvas.maplibregl-canvas').count() == 0, 'vector layer removed')
        check(page.locator('#family-map .leaflet-marker-icon').count() == 2, 'pins survive the swap')
        page.wait_for_function("document.querySelectorAll('#family-map .leaflet-tile-loaded').length > 0")
        check(tiles.raster, 'raster tiles requested after the swap')


def scenario_destroy_mid_load_and_a_second_map(served):
    with served.browser() as page:
        Tiles(page)
        open_map(page, served)
        page.wait_for_function("_fmInstance.base === 'vector'")
        # Review Focus 3 + 4: a map torn down while loading, and a second live
        # map sharing the memoised loader.
        page.evaluate("""async () => {
            for (const id of ['fm-a', 'fm-b']) {
                const d = document.createElement('div'); d.id = id;
                d.style.cssText = 'width:300px;height:200px'; document.body.appendChild(d); }
            window._fmA = FamilyMap.create(document.getElementById('fm-a'), {interactive: false});
            window._fmB = FamilyMap.create(document.getElementById('fm-b'), {interactive: true});
            _fmA.ensure(); _fmA.destroy();
            await _fmB.ensure();
            return true; }""")
        page.wait_for_function("window._fmB.base === 'vector'")
        page.wait_for_timeout(1500)
        check(page.locator('#fm-a canvas').count() == 0, 'destroyed map left a canvas behind')
        check(page.evaluate("window._fmA.base") is None, 'destroyed map must not come back')
        check(page.evaluate("_fmB.map.dragging.enabled()") is True, 'interactive map drags')
        check(page.evaluate("_fmInstance.base") == 'vector', 'the first map is still vector')
        check(not served.errors(), served.errors())


if __name__ == '__main__':
    served = live_app(seed)
    if served is None:
        sys.exit(0)
    try:
        if scenario_vector_map_on_the_map_page(served):
            print('  ok  scenario_vector_map_on_the_map_page')
            for fn in (scenario_theme_follows_the_page_and_the_last_flip_wins,
                       scenario_context_loss_drops_to_raster_and_keeps_the_pins,
                       scenario_destroy_mid_load_and_a_second_map):
                fn(served)
                print(f'  ok  {fn.__name__}')
        for fn in (scenario_resolver_and_asset_base, scenario_raster_when_there_is_no_webgl2):
            fn(served)
            print(f'  ok  {fn.__name__}')
    finally:
        served.stop()
    print('\nfamily map live scenarios passed')

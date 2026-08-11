"""The front end is precompiled now, and this is what stops it drifting.

Every page used to load `https://cdn.tailwindcss.com` — Tailwind's COMPILER,
not a stylesheet. It built the CSS in the browser on every page load and then
watched the whole document for class changes so it could rebuild. The wall
panel's shelf is made of ordinary links, so every tap paid for all of it again,
which is most of why a Raspberry Pi 5 took seconds to answer one.

The trade is that a precompiled stylesheet only knows the classes that existed
when it was built. Add a class to a template, forget `tools/build_tailwind.py`,
and the page still renders — just without that style, on the kitchen wall,
where nobody is looking at a console. So the build stamps a hash of everything
it read into the top of each stylesheet and this recomputes it.

A red test here means one thing: run the build.

    cd chauffeur && python tools/build_tailwind.py

Run from chauffeur/:  python tests/test_tailwind_build.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(ROOT, 'templates')
STATIC = os.path.join(ROOT, 'static')
sys.path.insert(0, os.path.join(ROOT, 'tools'))

import build_tailwind  # noqa: E402

BUILT = ['tailwind.css', 'tailwind-app.css']

TEMPLATES = sorted(
    os.path.join(base, f)
    for base, _, files in os.walk(TPL)
    for f in files if f.endswith('.html')
)


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def scenario_the_stylesheets_are_built_and_not_stale():
    """The whole point. If a template changed and nobody rebuilt, the classes
    it added exist in the markup and nowhere in the CSS."""
    expected = build_tailwind.content_hash()
    for name in BUILT:
        path = os.path.join(STATIC, name)
        check(os.path.isfile(path), f"static/{name} is missing — run "
                                    f"tools/build_tailwind.py")
        stamped = build_tailwind.stamped_hash(path)
        check(stamped is not None,
              f"static/{name} carries no content-hash stamp, so nothing can "
              f"tell whether it matches the templates it was built from")
        check(stamped == expected,
              f"static/{name} is STALE. A template, a tailwind config or the "
              f"pinned Tailwind version changed since it was built, so any "
              f"class added in that change does nothing on the page. Fix:\n"
              f"    cd chauffeur && python tools/build_tailwind.py")


def scenario_the_stylesheets_are_not_empty():
    """A build that silently produced nothing would also match its own hash."""
    for name in BUILT:
        size = os.path.getsize(os.path.join(STATIC, name))
        check(size > 20_000,
              f"static/{name} is {size} bytes — that is not a Tailwind build, "
              f"it is a build that scanned nothing")


def scenario_no_page_loads_the_tailwind_compiler_any_more():
    """The regression this whole change exists to prevent. One template
    reintroducing the Play CDN puts the compiler, the 400 KB download and the
    document-wide MutationObserver back on that page."""
    for path in TEMPLATES:
        src = open(path, encoding='utf-8').read()
        check('cdn.tailwindcss.com' not in src,
              f"{os.path.basename(path)} loads the Tailwind Play CDN again. "
              f"That is a CSS compiler running in the browser on every page "
              f"load — use static/tailwind.css (or tailwind-app.css) instead.")


def scenario_nothing_is_fetched_from_a_cdn_at_all():
    """A panel on a wall should not need the internet to draw itself, and a
    page that waits on four hosts before it paints is slow even when they are
    all up. Everything is vendored into static/vendor by tools/vendor_assets.py.

    Two exemptions, both real:
      - Mapbox and the map tile servers are network SERVICES, not libraries.
        A map without the internet is a blank square whatever we vendor.
      - sendspin-js is a dynamic ESM import in the music widget, used only for
        'play on this phone', which is a phone feature and not a panel one.
    """
    allowed = ('api.mapbox.com/styles', 'api.mapbox.com/geocoding',
               'api.mapbox.com/search', 'api.mapbox.com/directions',
               'api.mapbox.com/optimized-trips', 'api.mapbox.com/isochrone',
               'tile.openstreetmap', 'basemaps.cartocdn', 'sendspin')
    hosts = ('cdn.jsdelivr.net', 'unpkg.com', 'fonts.googleapis.com',
             'fonts.gstatic.com', 'api.mapbox.com/mapbox-gl-js')
    for path in TEMPLATES:
        for i, line in enumerate(open(path, encoding='utf-8'), 1):
            if any(a in line for a in allowed):
                continue
            for host in hosts:
                check(host not in line,
                      f"{os.path.basename(path)}:{i} still fetches from "
                      f"{host}. Vendor it: tools/vendor_assets.py")


def scenario_the_vendored_assets_are_actually_there():
    """The templates point at these by path. A missing one is a blank page, a
    dead map or a page in Times New Roman."""
    for rel in ('vendor/alpine.min.js', 'vendor/alpine-collapse.min.js',
                'vendor/fullcalendar.global.min.js', 'vendor/mapbox-gl.js',
                'vendor/mapbox-gl.css', 'vendor/leaflet/leaflet.js',
                'vendor/leaflet/leaflet.css',
                'vendor/leaflet/images/marker-icon.png',
                'vendor/fonts/inter/inter.css',
                'vendor/fonts/emoji/emoji.css'):
        check(os.path.isfile(os.path.join(STATIC, rel)),
              f"static/{rel} is missing — run tools/vendor_assets.py")


def scenario_the_emoji_font_does_not_shadow_the_one_on_a_phone():
    """Android's own emoji font is called "Noto Color Emoji", and an
    @font-face beats a system font of the same name. Ship ours under that name
    and every phone in the house downloads a megabyte of emoji it already has.
    It is renamed on the way in, and sits LAST in the stacks so a device with
    its own emoji font never reaches it."""
    css = open(os.path.join(STATIC, 'vendor/fonts/emoji/emoji.css'),
               encoding='utf-8').read()
    check("font-family: 'Chauffeur Emoji'" in css,
          "the vendored emoji font kept Google's family name, which shadows "
          "the one already on every Android phone")
    skin = open(os.path.join(TPL, 'panel_skin.html'), encoding='utf-8').read()
    check('"Chauffeur Emoji"' in skin,
          "the font stacks do not name the vendored emoji family, so the Pi "
          "is back to tofu boxes")
    for platform_family in ('"Apple Color Emoji"', '"Segoe UI Emoji"'):
        check(skin.index(platform_family) < skin.index('"Chauffeur Emoji"'),
              f"{platform_family} no longer comes before the vendored font, "
              f"so a device with its own emoji font downloads ours anyway")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} tailwind-build scenarios passed")

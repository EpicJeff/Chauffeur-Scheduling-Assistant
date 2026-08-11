"""Pull every third-party front-end asset into `static/vendor/`, once.

WHY THIS EXISTS

The wall panel is a Raspberry Pi 5 on a kitchen wall, and it was taking whole
seconds to answer a tap. Part of that was CSS (see panel_skin.html), and part
of it was this: every page in the app fetched Tailwind, Alpine, Inter, Leaflet,
Mapbox GL, FullCalendar and an emoji font from four different CDNs, on every
single navigation. The shelf is made of ordinary links, so walking from DRIVES
to CHORES is a full page load that re-pays all of it.

Running this script is not part of serving the app. The files it writes are
COMMITTED, and `static/vendor/` is what the templates point at. Re-run it only
to bump a pinned version below, then commit the result.

    python tools/vendor_assets.py

Fonts are the fiddly part. Google Fonts' css2 endpoint serves a different
stylesheet per User-Agent — ask as a modern Chrome and you get woff2 sliced by
`unicode-range`, which is what we want. The script downloads each slice, then
rewrites the stylesheet to point at the local copies.

The emoji font is renamed on the way in, deliberately. Google's family is
"Noto Color Emoji", which is ALSO the name of the font already installed on
every Android phone in the house — and an `@font-face` beats a system font of
the same name, so shipping it under its own name would make every phone
download a megabyte of emoji it already has. It becomes "Chauffeur Emoji" here
and goes LAST in the font stacks, after Apple's and Microsoft's, so only a
device with no emoji font of its own (which is exactly Raspberry Pi OS) ever
loads it.
"""
import os
import re
import shutil
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(os.path.dirname(HERE), 'static', 'vendor')

# A modern desktop Chrome. Google Fonts branches on this: an older UA gets ttf
# instead of woff2, which is roughly double the bytes for the same glyphs.
CHROME_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
             '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')

# Pinned, all of them. Two of these were on floating `3.x.x` CDN URLs, which
# means the panel was silently taking a new Alpine whenever unpkg rolled one.
SCRIPTS = [
    ('https://unpkg.com/alpinejs@3.16.1/dist/cdn.min.js', 'alpine.min.js'),
    ('https://unpkg.com/@alpinejs/collapse@3.16.1/dist/cdn.min.js', 'alpine-collapse.min.js'),
    ('https://cdn.jsdelivr.net/npm/fullcalendar@6.1.15/index.global.min.js', 'fullcalendar.global.min.js'),
    ('https://api.mapbox.com/mapbox-gl-js/v2.14.1/mapbox-gl.js', 'mapbox-gl.js'),
    ('https://api.mapbox.com/mapbox-gl-js/v2.14.1/mapbox-gl.css', 'mapbox-gl.css'),
    ('https://unpkg.com/leaflet@1.9.4/dist/leaflet.js', 'leaflet/leaflet.js'),
    ('https://unpkg.com/leaflet@1.9.4/dist/leaflet.css', 'leaflet/leaflet.css'),
]

# Leaflet's stylesheet points at these with a relative `images/` path, so they
# have to sit next to it or the zoom control and the marker come out blank.
LEAFLET_IMAGES = ['layers.png', 'layers-2x.png', 'marker-icon.png',
                  'marker-icon-2x.png', 'marker-shadow.png']

FONTS = [
    # (css2 url, output stylesheet, family rename or None)
    ('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap',
     'inter.css', None),
    ('https://fonts.googleapis.com/css2?family=Noto+Color+Emoji&display=swap',
     'emoji.css', ('Noto Color Emoji', 'Chauffeur Emoji')),
]


def fetch(url, ua=CHROME_UA):
    req = urllib.request.Request(url, headers={'User-Agent': ua})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def write(rel, data):
    path = os.path.join(VENDOR, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)
    print(f'  {rel:<44} {len(data) / 1024:8.1f} KB')
    return path


def vendor_font(url, out_name, rename):
    """Download a Google Fonts stylesheet and every woff2 it references."""
    css = fetch(url).decode('utf-8')
    subdir = os.path.splitext(out_name)[0]

    seen = {}
    for font_url in sorted(set(re.findall(r'url\((https://[^)]+)\)', css))):
        name = font_url.rsplit('/', 1)[-1]
        # Google's filenames are unique per slice, but not per family, so the
        # family name goes in front to keep two fonts from colliding.
        local = f'fonts/{subdir}/{name}'
        if font_url not in seen:
            write(local, fetch(font_url))
            seen[font_url] = local
        css = css.replace(font_url, os.path.basename(local))

    # Slices live beside the stylesheet, so a bare filename resolves.
    css = css.replace('url(', 'url(./')
    css = css.replace('url(./"', 'url("./')  # in case a quoted form appears
    if rename:
        css = css.replace(f"'{rename[0]}'", f"'{rename[1]}'")
        css = css.replace(f'"{rename[0]}"', f'"{rename[1]}"')
    write(f'fonts/{subdir}/{out_name}', css.encode('utf-8'))


def main():
    if os.path.isdir(VENDOR):
        shutil.rmtree(VENDOR)
    os.makedirs(VENDOR, exist_ok=True)

    print('scripts and stylesheets')
    for url, rel in SCRIPTS:
        write(rel, fetch(url))

    print('leaflet images')
    for name in LEAFLET_IMAGES:
        write(f'leaflet/images/{name}',
              fetch(f'https://unpkg.com/leaflet@1.9.4/dist/images/{name}'))

    print('fonts')
    for url, out_name, rename in FONTS:
        vendor_font(url, out_name, rename)

    total = sum(os.path.getsize(os.path.join(root, f))
                for root, _, files in os.walk(VENDOR) for f in files)
    print(f'\nstatic/vendor/ is {total / 1024 / 1024:.2f} MB')


if __name__ == '__main__':
    sys.exit(main())

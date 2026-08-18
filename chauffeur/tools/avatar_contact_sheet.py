"""The wardrobe on review: every authored asset, worn, in context.

    python tools/avatar_contact_sheet.py [-o sheet.png]

Game-art QA reviews assets IN CONTEXT, not in isolation: on different skins,
with different tops, at the scale they actually render. This draws one grid --
a row per authored item, columns varying skin/colour/outfit -- plus a scale
strip of full figures at lane size. Every wardrobe addition should get a pass
through this sheet before it ships; docs/avatar_design.md calls it the review
gate for new art.

Needs playwright (dev machines have it; the add-on does not, which is fine --
this never runs at serve time).
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      os.path.join(os.environ.get('TEMP', '/tmp'), 'chauffeur_sheet'))
os.makedirs(os.environ['CHAUFFEUR_DATA_DIR'], exist_ok=True)

BASE = {'top': 'ShortHairShortFlat', 'hair_color': 'Brown',
        'eyes': 'Default', 'eyebrow': 'Default', 'mouth': 'Smile',
        'nose': 'Default', 'clothes': 'ShirtCrewNeck', 'clothe_color': 'Blue01',
        'bottoms': 'Trousers', 'bottoms_color': 'Heather', 'shoes': 'Sneakers'}

# Columns: (label, config overrides). Chosen to catch the classic failures --
# an accent invisible on its own colour, a white part lost on a white garment,
# a dark part lost on dark skin.
VARIANTS = [
    ('light',  {'skin': 'Light'}),
    ('dark',   {'skin': 'DarkBrown', 'clothe_color': 'PastelYellow'}),
    ('white',  {'skin': 'Brown', 'clothe_color': 'White',
                'bottoms_color': 'White', 'shoes_color': 'White',
                'accent_color': 'White'}),
    ('black',  {'skin': 'Pale', 'clothe_color': 'Black',
                'bottoms_color': 'Black', 'shoes_color': 'Black',
                'accent_color': 'Black'}),
    ('hoodie', {'skin': 'Tanned', 'clothes': 'Hoodie', 'clothe_color': 'PastelRed',
                'accent_color': 'Pink'}),
    ('blazer', {'skin': 'Light', 'clothes': 'BlazerShirt', 'accent_color': 'Red'}),
]


def build_html():
    from services import avatar_render as ar
    from services import avatar_catalog as cat

    seq = [0]

    def tile(cfg, focus, w):
        # unique nonce per tile: these SVGs share ONE document, and shared
        # mask ids are exactly the collision the renderer exists to prevent
        seq[0] += 1
        svg = ar.render_svg(cfg, 'full', nonce=f'cs{seq[0]}')
        svg = svg.replace('viewBox="0 0 264 600"', f'viewBox="{focus}"', 1)
        return f'<div style="width:{w}px;height:{w}px" class="tile">{svg}</div>'

    rows = []
    tables = {'bottoms': ar.BOTTOMS, 'shoes': ar.SHOES, 'neck': ar.NECK,
              'wrist': ar.WRIST, 'waist': ar.WAIST,
              'hair_accessory': ar.HAIR_ACCESSORY}
    for slot, table in tables.items():
        focus = (cat.get_slot(slot) or {}).get('focus', '0 0 264 600')
        for key in table:
            cells = ''
            for label, over in VARIANTS:
                cfg = dict(BASE, **over)
                cfg[slot] = key
                cells += tile(cfg, focus, 110)
            rows.append(f'<div class="row"><div class="lbl">{slot}<br><b>{key}</b></div>{cells}</div>')

    # the scale strip: whole figures at the size a lane actually draws them
    strip = ''
    for label, over in VARIANTS:
        cfg = dict(BASE, **over, waist='Belt', wrist='Watch', neck='Scarf')
        seq[0] += 1
        svg = ar.render_svg(cfg, 'full', nonce=f'cs{seq[0]}')
        strip += f'<div style="height:150px" class="tile">{svg}</div>'

    heads = ''.join(f'<div class="hd">{label}</div>' for label, _ in VARIANTS)
    return f'''<!doctype html><html><head><meta charset="utf-8"><style>
        body {{ background:#1c2431; color:#cbd5e1; font:12px system-ui; margin:16px; }}
        .row {{ display:flex; gap:8px; align-items:center; margin-bottom:8px; }}
        .lbl {{ width:120px; text-align:right; padding-right:6px; color:#94a3b8; }}
        .hd  {{ width:110px; text-align:center; font-weight:700; }}
        .tile {{ background:#2a3446; border-radius:10px; }}
        .tile svg {{ width:100%; height:100%; display:block; }}
        h2 {{ font-size:14px; margin:18px 0 8px 126px; }}
    </style></head><body>
    <div class="row"><div class="lbl"></div>{heads}</div>
    {''.join(rows)}
    <h2>at lane scale, fully dressed</h2>
    <div class="row"><div class="lbl">150px</div>{strip}</div>
    </body></html>'''


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-o', '--out', default=os.path.join(
        os.environ.get('TEMP', '.'), 'avatar_contact_sheet.png'))
    args = ap.parse_args()
    html_path = os.path.splitext(args.out)[0] + '.html'
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(build_html())
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={'width': 900, 'height': 600},
                              device_scale_factor=2)
        await pg.goto('file:///' + html_path.replace('\\', '/'))
        await pg.wait_for_timeout(500)
        await pg.screenshot(path=args.out, full_page=True)
        await b.close()
    print('wrote', args.out)


if __name__ == '__main__':
    asyncio.run(main())

"""Work out how to continue each garment below y=280, by looking at it.

    python tools/bake_garment_hems.py

Most tops reach the bottom edge as one flat colour, so one shape continues
them. Blazers do not: `BlazerShirt` arrives as five colour runs -- jacket,
lapel, the shirt underneath in the MEMBER'S chosen colour, lapel, jacket. A
single flat extension paints a stripe of the wrong colour across the waist.

Rather than hand-authoring an extension per garment (and again for every
garment ever added), we measure. Every source top terminates on flat horizontal
segments, so the bottom edge IS a list of colour runs and a vertical extrusion
of those runs is exact.

The trick that makes it robust: render each garment TWICE with different clothe
colours. Runs whose colour changes between the two are painted through the
colour mask and must follow the member's choice; runs that stay put are
hardcoded art. No hand-annotation, and it keeps working for garments added
later.
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROBE_A, PROBE_B = 'Red', 'Blue03'      # two clothe colours that cannot collide
SAMPLE_Y = 279                          # the last row of the original canvas
MIN_RUN = 2                             # ignore antialiasing specks

_PAGE = """
<body><canvas id=c width=264 height=280></canvas><script>
window.sample = (svg) => new Promise((res, rej) => {
  const img = new Image();
  img.onload = () => {
    const ctx = document.getElementById('c').getContext('2d', {willReadFrequently:true});
    ctx.clearRect(0,0,264,280);
    ctx.drawImage(img,0,0,264,280);
    res(Array.from(ctx.getImageData(0,%d,264,1).data));
  };
  img.onerror = rej;
  img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
});
</script></body>
""" % SAMPLE_Y


def _runs(px):
    """[(x_start, x_end_exclusive, '#rrggbb')] across the sampled row."""
    out = []
    for x in range(264):
        r, g, b, a = px[x * 4:x * 4 + 4]
        col = None if a < 128 else '#%02x%02x%02x' % (r, g, b)
        if out and out[-1][2] == col:
            out[-1][1] = x + 1
        else:
            out.append([x, x + 1, col])
    kept = [r for r in out if r[2] and (r[1] - r[0]) >= MIN_RUN]
    if not kept:
        return kept
    # Antialiased edges produce 1px runs we drop -- but a dropped run leaves a
    # GAP, and a gap in the extrusion shows the background straight through the
    # waist. Tile the survivors so they meet, and pin the ends to the shoulder
    # edge (x 32..232) that every garment shares.
    for i in range(len(kept) - 1):
        kept[i][1] = kept[i + 1][0]
    kept[0][0] = min(kept[0][0], 32)
    kept[-1][1] = max(kept[-1][1], 232)
    return kept


async def main():
    from services import avatar_render as ar
    from playwright.async_api import async_playwright

    pieces = ar._load()
    garments = sorted((pieces.get('clothes') or {}))
    if not garments:
        raise SystemExit('no pieces.json -- run tools/extract_avataaars.py first')

    baked = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(_PAGE)
        for key in garments:
            probes = []
            for colour in (PROBE_A, PROBE_B):
                svg = ar.render_svg({'clothes': key, 'clothe_color': colour,
                                     'skin': 'Light'}, crop='head', nonce='bake')
                probes.append(_runs(await page.evaluate('window.sample', svg)))
            a, b = probes
            if len(a) != len(b):
                print(f'  ! {key}: probe mismatch ({len(a)} vs {len(b)} runs), skipped')
                continue
            runs = []
            for (x0, x1, ca), (_, _, cb) in zip(a, b):
                runs.append({'x': x0, 'w': x1 - x0,
                             # colour that moved with the probe -> member's choice
                             'fill': None if ca != cb else ca})
            baked[key] = runs
            shape = ''.join('C' if r['fill'] is None else '#' for r in runs)
            print(f'  {key:16s} {len(runs)} runs  {shape}')
        await browser.close()

    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'static', 'avatar', 'hems.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump({'_note': 'baked by tools/bake_garment_hems.py; C=member colour',
                   'sample_y': SAMPLE_Y, 'garments': baked}, f,
                  separators=(',', ':'), sort_keys=True)
    print(f'wrote {len(baked)} garments -> {out}')


if __name__ == '__main__':
    asyncio.run(main())

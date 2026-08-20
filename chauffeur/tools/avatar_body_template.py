"""The rig, drawn, with every anchor line on it -- the file you hand an artist.

    python tools/avatar_body_template.py [-o OUTDIR]

Writes two files:

  avatar_template.svg      The tracing file. Its viewBox is EXACTLY
                           `0 0 264 600`, the renderer's own canvas, so a path
                           drawn on this template pastes into the wardrobe
                           tables verbatim -- no transform, no rescale, no
                           offset. That exactness is the whole point, and it is
                           why the guide labels are bare numbers crammed into
                           the 30 units of margin either side of the arms
                           rather than readable words in a generous gutter.
  avatar_authoring_brief.html
                           The handout. The same template with the labels spelt
                           out, the fill vocabulary, the rules the contact sheet
                           taught, a worked example, and reference figures.

Geometry is IMPORTED from services.avatar_render, never retyped, so the
template cannot drift from the rig it claims to describe.

Needs nothing but the repo -- unlike tools/avatar_contact_sheet.py, this one
runs anywhere.
"""
import argparse
import html
import os
import pprint
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import avatar_render as ar    # noqa: E402
from services import avatar_catalog as cat  # noqa: E402

# --- what the guides say -------------------------------------------------
# (y, weight, label). `weight` 1 is a primary line -- something a piece
# actually registers to; 2 is context. Every number here is read off the art in
# avatar_render.py or recorded in docs/avatar_design.md; none is invented.
H_LINES = [
    (199, 1, 'top shoulder / full-top collar'),
    (222, 2, 'crew neckline'),
    (225, 1, 'COLLAR SEAM'),
    (232, 1, 'necklaces hang from here'),
    (236, 2, 'v-neck depth'),
    (278, 2, 'arms + lower body start (overlap)'),
    (280, 1, 'SHOULDER EDGE  x32..232'),
    (336, 2, 'waistband overlap top'),
    (ar.HEM_STRUCTURED, 1, 'structured hem (blazer)'),
    (352, 2, 'generic sleeve hem'),
    (366, 1, 'bottoms waistband top'),
    (ar.HEM_SOFT, 1, 'soft hem / hips widest'),
    (414, 2, 'hip -> leg'),
    (424, 1, 'arms end (hands)'),
    (470, 2, 'leg crease starts'),
    (472, 2, 'shorts + skirt hem'),
    (536, 2, 'shoe top (sneaker)'),
    (552, 1, 'trouser hem'),
    (568, 1, 'legs end'),
    (576, 1, 'FLOOR -- feet stand here'),
]
# A zone reads better as a band than as two lines.
H_BANDS = [(364, 380, 'waistband'), (392, 406, 'wrist')]
V_LINES = [
    (32, 'outer arm'),
    (76, 'arm | torso'),
    (132, 'centre'),
    (188, 'torso | arm'),
    (232, 'outer arm'),
]

# The annotated canvas is the true 264x600 plus gutters: a wide one on the left
# for the anchor names (the longest is 34 characters, and a label that runs out
# of gutter runs across the figure instead), and on the right two columns --
# slot-frame keys at x=270, zone names at x=350, because a frame label and a
# band label landed on each other at the wrist.
ANNOT = (-172, -12, 620, 664)
FRAME_LABEL_X, BAND_LABEL_X = 270, 350

GUIDE = '#E0218A'
BAND = '#5B8DEF'
FRAME = '#0FA36B'
SKIN = '#E3D5C3'


def _rig() -> str:
    """The undressed figure, in the renderer's own paths."""
    return (
        '<g id="rig">'
        + ar._shade(ar.GROUND_SHADOW, '0.10')
        + f'<path d="{ar._ARM_L}" fill="{SKIN}"/><path d="{ar._ARM_R}" fill="{SKIN}"/>'
        + f'<path d="{ar._LOWER}" fill="{SKIN}"/>'
        + ar._paint(ar.RIG_DEPTH, SKIN)
        + '<g transform="translate(32,36)">'
        + f'<path d="{ar._BODY_PATH}" fill="{SKIN}"/>'
        + f'<path d="{ar._NECK_SHADOW}" fill="#000000" fill-opacity="0.1"/>'
        + '</g></g>'
    )


def _envelope() -> str:
    """The silhouette a FULL TOP traces -- collar to hem, sleeves included.
    Dashed, because a top is drawn TO this outline, not inside it."""
    return (f'<g id="garment-envelope" fill="none" stroke="{BAND}" stroke-width="1" '
            f'stroke-dasharray="5 4" opacity="0.85">'
            f'<path d="{ar._top_body(ar._CREW)}"/></g>')


def _frames(annotated: bool) -> str:
    """Each slot's `focus` viewBox -- the crop the editor thumbnails it in. A
    piece that falls outside its own frame is invisible in the picker.

    Deduped by focus, not listed per slot: eleven slots share six crops, and
    labelling each one separately stacked four words on the same baseline."""
    face = ('eyes', 'eyebrow', 'mouth', 'nose')
    seen = {}
    for slot in cat.SLOTS:
        focus = slot.get('focus')
        if focus and slot['key'] not in face:
            seen.setdefault(focus, []).append(slot['key'])
    out = []
    for focus, keys in seen.items():
        x, y, w, h = (float(n) for n in focus.split())
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}"/>')
        if not annotated:
            continue
        # Centred on the frame, never on its top edge. `waist` crops y300..430
        # and a label on the edge printed the word up at the armpit, which reads
        # as "the waist is here" rather than "this box is the waist crop".
        # The range is spelt out for the same reason: a crop is an extent.
        lines = keys + [f'y{y:.0f}..{y + h:.0f}']
        top = (y + h / 2) - (len(lines) - 1) * 5
        for i, text in enumerate(lines):
            dim = ' opacity="0.75"' if i == len(lines) - 1 else ''
            out.append(f'<text x="{FRAME_LABEL_X}" y="{top + i * 10:.1f}" font-size="9" '
                       f'fill="{FRAME}" stroke="none"{dim}>{text}</text>')
        # a tick at each end of the extent, so the centred label cannot be read
        # as pointing at one line
        out.append(f'<path d="M{x + w},{y} l4,0 M{x + w},{y + h} l4,0" '
                   f'stroke-dasharray="none" opacity="0.9"/>')
    return (f'<g id="slot-frames" fill="none" stroke="{FRAME}" stroke-width="0.8" '
            f'stroke-dasharray="2 5" opacity="0.7">{"".join(out)}</g>')


def _guides(annotated: bool) -> str:
    """Horizontal anchors, vertical splits, and the two zones.

    Compact mode labels with the bare y value in the margin outside the arms
    (x 0..30 is always empty); annotated mode spends a wider viewBox on words."""
    # Rules stop at the true canvas edge in both modes; the gutters are for
    # words, not for more line.
    lo, hi = (ANNOT[0], 264) if annotated else (0, 264)
    g = [f'<g id="guides" stroke="{GUIDE}" fill="none">']
    for y0, y1, name in H_BANDS:
        g.append(f'<rect x="{lo}" y="{y0}" width="{hi - lo}" height="{y1 - y0}" '
                 f'fill="{BAND}" fill-opacity="0.13" stroke="none"/>')
        if annotated:
            g.append(f'<text x="{BAND_LABEL_X}" y="{y1 - 4}" font-size="9" fill="{BAND}" '
                     f'stroke="none">{name} {y0}-{y1}</text>')
    for y, weight, name in H_LINES:
        primary = weight == 1
        dash = '' if primary else ' stroke-dasharray="3 4"'
        g.append(f'<line x1="{lo}" y1="{y}" x2="{hi}" y2="{y}" '
                 f'stroke-width="{0.8 if primary else 0.4}" '
                 f'opacity="{0.85 if primary else 0.4}"{dash}/>')

    # Labels, both modes, are a collision problem: a neckline cluster puts four
    # lines inside 14 units and a 9px label is 10 tall, so placing each label on
    # its own line just overwrites it.
    if annotated:
        # Cluster the near-coincident lines and stack the cluster's labels as
        # one block. Each label carries its own y, so the block does not need a
        # leader line back to the rule -- the number IS the reference.
        clusters: list = []
        for row in H_LINES:
            if clusters and row[0] - clusters[-1][-1][0] < 12:
                clusters[-1].append(row)
            else:
                clusters.append([row])
        for group in clusters:
            mid = sum(r[0] for r in group) / len(group)
            top = mid - (len(group) - 1) * 5
            for i, (y, weight, name) in enumerate(group):
                g.append(f'<text x="{lo + 2}" y="{top + i * 10 - 2.5:.1f}" font-size="9" '
                         f'fill="{GUIDE}" stroke="none" '
                         f'opacity="{1 if weight == 1 else 0.65}">'
                         f'{y}  {html.escape(name)}</text>')
    else:
        # Bare numbers, alternating gutters. The arms never reach x=30 or come
        # back before x=234, so both margins are always empty.
        last = -99.0
        left = True
        for y, weight, _name in H_LINES:
            if weight != 1:
                continue
            left = True if y - last >= 10 else not left
            last = y
            pos = ('2', 'start') if left else ('262', 'end')
            g.append(f'<text x="{pos[0]}" y="{y - 1.5}" font-size="8" fill="{GUIDE}" '
                     f'stroke="none" text-anchor="{pos[1]}" '
                     f'font-family="monospace">{y}</text>')
    for i, (x, name) in enumerate(V_LINES):
        centre = x == 132
        dash = '' if centre else ' stroke-dasharray="3 4"'
        g.append(f'<line x1="{x}" y1="140" x2="{x}" y2="600" stroke-width="0.5" '
                 f'opacity="{0.7 if centre else 0.45}"{dash}/>')
        if annotated:
            # staggered rows: "arm | torso" and "torso | arm" are wide enough to
            # touch their neighbours on one baseline
            g.append(f'<text x="{x}" y="136" font-size="9" fill="{GUIDE}" '
                     f'stroke="none" text-anchor="middle">{x}</text>'
                     f'<text x="{x}" y="{620 + (i % 2) * 11}" font-size="8" fill="{GUIDE}" '
                     f'stroke="none" text-anchor="middle" opacity="0.7">'
                     f'{html.escape(name)}</text>')
    g.append('</g>')
    return ''.join(g)


# Read by whoever opens the tracing file on its own, with no brief next to it.
# Every vector editor preserves an XML comment, and most show <title>.
HEADER = """
  Chauffeur avatar -- body template.

  Draw in THESE units. The viewBox is the renderer's exact canvas, so a path
  traced here pastes straight into the wardrobe with no transform or rescale.
  Do not resize, re-origin, or move the artwork.

  Layers, all of which are guides and ALL of which you delete before sending
  work back -- only your own paths should survive:
    rig               the body, for registration. Never redrawn, never shipped.
    garment-envelope  blue dashes: the silhouette a full top traces.
    slot-frames       green dashes: each slot's thumbnail crop in the editor.
                      A piece outside its own frame is invisible in the picker.
    guides            pink: y anchors, numbered in the margins. Solid is
                      load-bearing, dashed is context. Blue bands are zones.

  Flat fills only -- no strokes, no gradients, no transforms, no clip paths.
  See avatar_authoring_brief.html for the fill tokens and the rules.
"""


def template_svg(annotated: bool = False, width: int = 264, height: int = 600) -> str:
    """`annotated` widens the viewBox to fit words. The tracing file is NEVER
    annotated: its viewBox has to stay the renderer's exact canvas."""
    box = ' '.join(str(n) for n in ANNOT) if annotated else '0 0 264 600'
    # In annotated mode the true canvas is no longer the viewBox, so say where
    # it is; in the tracing file the viewBox IS the edge and a line on top of
    # it would only be one more thing to delete.
    edge = (f'<rect x="0" y="0" width="264" height="600" fill="none" '
            f'stroke="{GUIDE}" stroke-width="0.8" opacity="0.5"/>') if annotated else ''
    # The brief inlines the annotated copy into a page that has already said all
    # this, so the header rides on the tracing file only.
    head = '' if annotated else (
        f'<!--{HEADER}-->'
        f'<title>Chauffeur avatar body template -- 264x600, draw in these units</title>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{box}" '
        f'width="{width}" height="{height}" preserveAspectRatio="xMidYMid meet">'
        f'{head}'
        f'<rect x="{ANNOT[0]}" y="{ANNOT[1]}" width="{ANNOT[2]}" '
        f'height="{ANNOT[3]}" fill="#FFFFFF"/>'
        f'{_rig()}{_envelope()}{_frames(annotated)}{_guides(annotated)}{edge}'
        f'</svg>'
    )


# --- the handout ---------------------------------------------------------
TOKENS = [
    ('c1', "the slot's own colour -- whatever the member picked", '#5199E4'),
    ('sh', "#000 at 10%. The source's soft shading.", '#E5E5E5'),
    ('sh2', "#000 at 16%. The source's hard shading -- creases, seams.", '#D8D8D8'),
    ('hi', "#FFF highlight. Carries its own 'o' (opacity).", '#FFFFFF'),
    ('#hex', 'literal art, never recoloured -- a white sole, a black lens.', '#262E33'),
]

RULES = [
    ('Shapes OVERLAP, never abut.',
     'Two shapes that meet exactly leave an antialiasing hairline -- invisible '
     'on a dark board, glowing on a light one. Tuck the lower shape under the '
     'one above it. This is why the arms start at y=278 and not y=280.'),
    ('A garment OVERHANGS the limb it covers.',
     'Trouser legs drawn to the same width as the skin legs leave a sliver of '
     'skin down the inner edge. Cut garment silhouettes slightly wider than the '
     'body beneath them.'),
    ('Separation is DRAWN, never cut.',
     'The gap between the legs is an sh2 crease painted on solid fabric. A real '
     'transparent gap shows the page straight through the figure -- on a light '
     'board that reads as a white slot from crotch to floor.'),
    ('No gradients. No strokes.',
     'Depth is flat fill plus low-opacity black plus low-opacity white, in that '
     'vocabulary only. Flatten everything to filled paths before sending it.'),
    ('One path with one fill is the quality ceiling.',
     'A watch is a strap AND a case AND a dial. A sneaker is an upper AND a sole '
     'AND a lace line. Build an item as an ordered list of parts.'),
    ('The far limb (viewer-right arm) is one shade darker.',
     'Whole silhouette, painted over its sleeve. The cheapest depth cue in every '
     'polished flat reference, and the rig already does it.'),
    ('It has to read at lane scale.',
     'These figures draw about 150px tall on a board, and the head crop draws at '
     '24-56px. Detail finer than roughly 4 units of the 264-wide canvas '
     'disappears.'),
]

WORN = {'top': 'ShortHairShortFlat', 'hair_color': 'Brown', 'eyes': 'Default',
        'eyebrow': 'Default', 'mouth': 'Smile', 'nose': 'Default',
        'clothes': 'ShirtCrewNeck', 'clothe_color': 'Blue01', 'skin': 'Light',
        'bottoms': 'Trousers', 'bottoms_color': 'Heather', 'shoes': 'Sneakers',
        'waist': 'Belt', 'wrist': 'Watch'}


def brief_html() -> str:
    example = pprint.pformat(ar.BOTTOMS['Trousers'], width=76, sort_dicts=False)
    worn = ar.render_svg(WORN, 'full', nonce='bw')
    bare = ar.render_svg(dict(WORN, clothes='ShirtCrewNeck', clothe_color='Gray01',
                              bottoms='', shoes='', waist='', wrist=''),
                         'full', nonce='bb')
    tokens = ''.join(
        f'<tr><td><code>{html.escape(k)}</code></td>'
        f'<td><span class="sw" style="background:{c}"></span></td>'
        f'<td>{html.escape(d)}</td></tr>' for k, d, c in TOKENS)
    rules = ''.join(f'<li><b>{html.escape(t)}</b><br>{html.escape(b)}</li>'
                    for t, b in RULES)
    slots = ''.join(
        f'<tr><td><code>{s["key"]}</code></td><td>{html.escape(s["label"])}</td>'
        f'<td><code>{s.get("focus", "-")}</code></td>'
        f'<td><code>{", ".join(s.get("palettes") or []) or "-"}</code></td></tr>'
        for s in cat.SLOTS if s.get('focus'))
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Chauffeur avatars -- authoring brief</title><style>
 body {{ font:14px/1.55 system-ui,sans-serif; color:#1d2430; background:#f6f7f9;
        margin:0 auto; max-width:1060px; padding:32px 24px 80px; }}
 h1 {{ font-size:26px; margin:0 0 4px; }}
 h2 {{ font-size:17px; margin:36px 0 10px; border-bottom:2px solid #e0218a;
       padding-bottom:5px; }}
 .lede {{ color:#5a6472; margin:0 0 8px; }}
 .cols {{ display:flex; gap:26px; align-items:flex-start; flex-wrap:wrap; }}
 .plate {{ background:#fff; border:1px solid #dde1e7; border-radius:12px; padding:10px; }}
 .plate svg {{ display:block; }}
 .fig {{ background:#2a3446; border-radius:12px; padding:10px; }}
 .fig svg {{ height:300px; display:block; }}
 table {{ border-collapse:collapse; width:100%; margin:6px 0 4px; background:#fff; }}
 td,th {{ border:1px solid #dde1e7; padding:6px 9px; text-align:left;
          vertical-align:top; }}
 th {{ background:#eef1f5; }}
 code {{ background:#eef1f5; padding:1px 5px; border-radius:4px; font-size:12.5px; }}
 pre {{ background:#1d2430; color:#e6edf3; padding:14px; border-radius:10px;
        overflow-x:auto; font-size:12px; line-height:1.5; }}
 ol li, ul li {{ margin-bottom:9px; }}
 .sw {{ display:inline-block; width:22px; height:14px; border-radius:3px;
        border:1px solid #aab; }}
 .key {{ font-size:12.5px; color:#5a6472; }}
 .key b {{ color:#e0218a; }} .key i {{ color:#5b8def; font-style:normal; }}
 .key u {{ color:#0fa36b; text-decoration:none; }}
</style></head><body>
<h1>Avatar wardrobe &mdash; authoring brief</h1>
<p class="lede">Everything on this page is generated from the live renderer
(<code>services/avatar_render.py</code>), so it cannot drift from the figure it
describes. Regenerate with <code>python tools/avatar_body_template.py</code>.</p>

<h2>1. The canvas</h2>
<div class="cols">
  <div class="plate">{template_svg(True, 620, 664)}</div>
  <div style="flex:1;min-width:270px">
    <p>The full-body canvas is <code>viewBox="0 0 264 600"</code>. Draw in those
    units and nothing else &mdash; no transform, no group offset, no rescale.</p>
    <p class="key"><b>Pink</b> lines are anchors: y values a piece registers to.
    Solid pink is load-bearing, dashed is context.<br>
    <i>Blue band</i> is a zone (waistband, wrist). <i>Blue dashes</i> are the
    silhouette a full top traces, collar to hem.<br>
    <u>Green dashes</u> are each slot's <code>focus</code> crop &mdash; the frame
    the editor thumbnails that slot in. A piece drawn outside its own frame is
    invisible in the picker.</p>
    <p>The head crop is the same art at <code>viewBox="0 0 264 280"</code>:
    unmodified Avataaars, which is what it was designed to be. Anything drawn
    above y=280 shows up in every 24&ndash;56px chip in the app, so it has to
    survive that size.</p>
    <p><b>Trace against <code>avatar_template.svg</code></b>, not against this
    picture. That file's viewBox is the exact renderer canvas, so coordinates
    come out ready to paste; this one is widened to fit the words.</p>
  </div>
</div>

<h2>2. The rules</h2>
<ol>{rules}</ol>

<h2>3. What a piece IS</h2>
<p>An ordered list of parts, painted first to last:
<code>{{'d': &lt;path&gt;, 'f': &lt;fill&gt;, 'o': &lt;opacity, optional&gt;}}</code>.
Fills are tokens rather than hex &mdash; that is what lets one drawing serve
fifteen colours:</p>
<table><tr><th><code>f</code></th><th></th><th>means</th></tr>{tokens}</table>
<p>Worked example, <code>BOTTOMS['Trousers']</code>: the fabric, a waistband
shade, two soft inner-leg creases, hem shadows, and one hard centre crease.</p>
<pre>{html.escape(example)}</pre>

<h2>4. The slots</h2>
<table><tr><th>key</th><th>label</th><th>focus crop</th><th>colour</th></tr>
{slots}</table>
<p>Adding an item to an existing slot is data: a new key in the matching dict in
<code>services/avatar_render.py</code> (<code>BOTTOMS</code>, <code>SHOES</code>,
<code>FULL_TOPS</code>, <code>NECK</code>, <code>WRIST</code>, <code>WAIST</code>,
<code>HAIR_ACCESSORY</code>) plus a catalog row in
<code>services/avatar_catalog.py</code>. New <em>slots</em> are a design decision
and cost a z-order argument; new <em>items</em> are cheap, which is the whole
point of having paid the registration cost up front.</p>

<h2>5. Reference</h2>
<div class="cols">
  <div class="fig">{bare}</div>
  <div class="fig">{worn}</div>
  <div style="flex:1;min-width:230px">
    <p>Left: the rig in a plain crew neck, nothing else on. Right: the same
    figure wearing <code>Trousers</code>, <code>Sneakers</code>,
    <code>Belt</code> and <code>Watch</code> &mdash; how authored pieces sit once
    they are in.</p>
    <p>Before anything ships it goes through the review gate,
    <code>python tools/avatar_contact_sheet.py</code>: every authored item worn
    across six variants &mdash; light skin, dark skin, white-on-white,
    black-on-black, under a hoodie, under a blazer &mdash; plus a strip at real
    lane scale. White-on-white and black-on-black are where pieces die.</p>
  </div>
</div>

<h2>6. Sending work back</h2>
<ul>
<li>Flatten to filled paths. No strokes, no gradients, no transforms, no nested
    groups, no clip paths.</li>
<li>Absolute coordinates in the 264&times;600 space. Do not let the editor
    re-origin the artwork to its own bounding box on export.</li>
<li>Send the part list: each path's <code>d</code>, plus which fill token it
    takes, in paint order.</li>
<li>Name the slot, and give the item a key in <code>CamelCase</code>
    (<code>CargoPants</code>, <code>HighTops</code>).</li>
</ul>
</body></html>'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-o', '--out', default='.', help='output directory')
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    for name, body in (('avatar_template.svg', template_svg(False)),
                       ('avatar_authoring_brief.html', brief_html())):
        path = os.path.join(args.out, name)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(body)
        print('wrote', path)


if __name__ == '__main__':
    main()

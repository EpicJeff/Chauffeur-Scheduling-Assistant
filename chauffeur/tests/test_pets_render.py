"""The baked critter art and the compositor that draws it.

The rules being defended here, in order of how badly they bite:

  * Two critters on one page must not share an id. Upstream ships unhashed
    clipPath ids; the bake rewrites them and `nonce` is what makes the rewrite
    mean something. The battle overlay draws two pets side by side, so a
    collision is not a hypothetical -- it is the first screen we ship.
  * Every one of the 210 body x top silhouettes must render with its headgear
    attached. The first bake quietly lost the top on two bodies because it
    harvested them from bare-headed critters.
  * Recolouring must move the body and the top and nothing else. The shading
    is white/slate overlays and the inside of a mouth is pink; both have to
    survive a green critter.

Run from chauffeur/:  python tests/test_pets_render.py
"""
import os
import re
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import pet_render as pr  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def test_bake_is_present():
    check(pr.available(), "bake missing -- run tools/harvest_critters.py")
    counts = {s: len(pr.parts(s)) for s in
              ('body', 'top', 'eyes', 'mouth', 'pattern', 'cheeks')}
    check(counts == {'body': 14, 'top': 15, 'eyes': 19, 'mouth': 19,
                     'pattern': 10, 'cheeks': 3},
          "part counts drifted from the harvest: %s" % counts)
    check(pr.species_count() == 210, "expected 210 silhouettes")
    b = pr.bundle()
    check('CC0' in b['licence'] or 'publicdomain' in b['licence'],
          "the licence must travel with the art")


def test_every_silhouette_renders_with_its_headgear():
    """210 combinations, and every one of them keeps its top."""
    missing = []
    for body in pr.parts('body'):
        for top in pr.parts('top'):
            svg = pr.render_svg({'body': body, 'top': top})
            # the top's own colour slot only exists inside a top fragment, so
            # its presence is proof the headgear actually composed in
            if pr.ACCENT_COLORS[pr.DEFAULTS['accent_color']] not in svg:
                missing.append('%s+%s' % (body, top))
    check(not missing, "top did not compose onto: %s" % missing[:8])


def test_every_part_renders_and_leaves_no_tokens():
    for slot in ('body', 'top', 'eyes', 'mouth', 'pattern', 'cheeks'):
        for key in pr.parts(slot):
            svg = pr.render_svg({slot: key})
            check(svg.startswith('<svg') and svg.endswith('</svg>'),
                  "%s/%s produced no svg" % (slot, key))
            check('{{' not in svg,
                  "%s/%s left an unexpanded token" % (slot, key))
            check('dbcrb-' not in svg,
                  "%s/%s leaked an upstream clip id" % (slot, key))


def test_two_pets_on_one_page_do_not_collide():
    """The battle overlay case: same body, two critters, one document."""
    a = pr.render_svg({'body': 'tower', 'top': 'horns'}, nonce='a')
    b = pr.render_svg({'body': 'tower', 'top': 'horns'}, nonce='b')
    ids_a = set(re.findall(r'id="([^"]+)"', a))
    ids_b = set(re.findall(r'id="([^"]+)"', b))
    check(ids_a and ids_b, "no ids at all -- the clip vanished")
    check(not (ids_a & ids_b),
          "duplicate ids across two pets: %s" % sorted(ids_a & ids_b))
    # and every reference must resolve inside its OWN svg
    for svg, ids in ((a, ids_a), (b, ids_b)):
        for ref in re.findall(r'url\(#([^)]+)\)', svg) + re.findall(r'href="#([^"]+)"', svg):
            check(ref in ids, "dangling reference #%s" % ref)


def test_recolour_moves_body_and_top_only():
    cfg = {'body': 'tower', 'top': 'horns', 'mouth': 'grin',
           'base_color': 'Lime', 'accent_color': 'Blossom'}
    svg = pr.render_svg(cfg)
    check(pr.BASE_COLORS['Lime'] in svg, "base colour not applied")
    check(pr.ACCENT_COLORS['Blossom'] in svg, "accent colour not applied")
    check('#fb7185' in svg, "a grin's pink mouth must survive recolouring")
    check('#1e293b' in svg and '#ffffff' in svg,
          "ink and highlight overlays must stay literal")
    other = pr.render_svg(dict(cfg, base_color='Sky'))
    check(other != svg, "changing the palette changed nothing")


def test_literal_hex_is_accepted():
    svg = pr.render_svg({'body': 'dome', 'base_color': '#123456'})
    check('#123456' in svg, "a granted one-off colour should pass through")


def test_unknown_keys_degrade_quietly():
    svg = pr.render_svg({'body': 'nonesuch', 'top': 'alsonot',
                         'eyes': 'round'})
    check(svg.startswith('<svg'), "an unknown body should not crash the render")
    check('{{' not in svg, "a dropped body must not leave its token behind")
    check(pr.render_svg(None).startswith('<svg'), "None config should render a default")
    check(pr.render_svg({}).startswith('<svg'), "empty config should render a default")


def test_optional_slots_are_optional():
    bare = pr.render_svg({'body': 'round', 'pattern': None, 'cheeks': None})
    dressed = pr.render_svg({'body': 'round', 'pattern': 'stripes',
                             'cheeks': 'freckles'})
    check(len(dressed) > len(bare), "pattern and cheeks added nothing")
    check(bare.startswith('<svg'), "a plain critter is a valid critter")


def test_crops_and_sizing():
    chip = pr.render_svg({'body': 'peak'}, crop='chip', size=48)
    battle = pr.render_svg({'body': 'peak'}, crop='battle')
    check('width="48" height="48"' in chip, "size not honoured")
    check('viewBox="0 0 100 100"' in chip and 'viewBox="0 0 100 100"' in battle,
          "one canvas, both crops")
    check('critter-chip' in chip and 'critter-battle' in battle,
          "crop must be addressable from CSS")
    # `.pet` is what a host page names its own wrapper; the root class must
    # not squat on it
    check(not re.search(r'class="[^"]*pet', chip),
          "root class must not collide with a host page's .pet rule")
    check('dbcr-c' in battle, "the idle-motion hook must survive to the overlay")


def test_data_url():
    import base64
    url = pr.data_url({'body': 'wedge', 'top': 'crown'})
    check(url.startswith('data:image/svg+xml;base64,'), "bad data url prefix")
    raw = base64.b64decode(url.split(',', 1)[1]).decode('utf-8')
    check(raw.startswith('<svg'), "data url did not round-trip")


def test_alt_text_says_something():
    label = pr.describe({'body': 'squat', 'top': 'earsPointy',
                         'base_color': 'Mint'})
    check('mint' in label and 'squat' in label and 'ears pointy' in label,
          "alt text should describe the critter: %r" % label)


def test_the_browser_compositor_draws_the_same_creature():
    """The editor composes critters in JS so a thumbnail grid does not have to
    ask the server 80 times. Two compositors reading one bake may disagree
    about code; they must never disagree about art -- otherwise the preview a
    child taps 'Hatch' on is not the creature they get.

    Skipped, loudly, where node is unavailable."""
    import json
    import shutil
    import subprocess
    import tempfile
    if not shutil.which('node'):
        print("       (skipped: no node)")
        return
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(here, 'templates', 'components', 'pet_editor.html'),
               encoding='utf-8').read()
    i = src.index('window.petCompose')
    fn = src[i:src.index('\n};', i) + 3]
    data = pr._load()
    bundle = {'pieces': data['pieces'], 'anchors': data['anchors'],
              'order': data['order'], 'view': data['view'],
              'colors': pr.BASE_COLORS, 'defaults': pr.DEFAULTS}
    cases = [
        {'body': 'tower', 'top': 'horns', 'eyes': 'angry', 'mouth': 'teeth',
         'pattern': 'stripes', 'cheeks': None, 'base_color': 'Coral',
         'accent_color': 'Amber'},
        {'body': 'blob', 'top': 'nub', 'eyes': 'round', 'mouth': 'smile',
         'pattern': None, 'cheeks': 'blush', 'base_color': 'Sky',
         'accent_color': 'Rose'},
        # a literal hex and every optional slot filled
        {'body': 'squat', 'top': 'antennae', 'eyes': 'wink', 'mouth': 'tongue',
         'pattern': 'dots', 'cheeks': 'freckles', 'base_color': '#123456',
         'accent_color': 'Lime'},
    ]
    js = ("const window = {};\n%s\nconsole.log(JSON.stringify(%s.map("
          "c => window.petCompose(%s, c, 'px'))));"
          % (fn, json.dumps(cases), json.dumps(bundle)))
    path = os.path.join(tempfile.mkdtemp(), 'compose.js')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(js)
    out = subprocess.run(['node', path], capture_output=True, text=True)
    check(out.returncode == 0, "the browser compositor threw: %s" % out.stderr[:400])
    art = lambda s: re.search(r'<clipPath.*</svg>', s, re.S).group(0)
    for cfg, client in zip(cases, json.loads(out.stdout)):
        server = pr.render_svg(cfg, nonce='x')
        check(art(server) == art(client),
              "compositors disagree on %s/%s" % (cfg['body'], cfg['top']))


def test_the_editor_lists_part_keys_not_part_art():
    """The bundle carries the art twice over: `slots` is {slot: [key, ...]}
    and `pieces` is {slot: {key: svg}}. The editor's thumbnail grid must walk
    the KEYS.

    Walking `pieces` instead does not throw -- x-for over an object iterates
    its values, so every raw SVG fragment gets used as a part name AND as an
    id namespace, and the grid renders unpainted bodies with no headgear and
    half-substituted tokens baked into the ids. It shipped that way for
    exactly one screenshot. This drives the real getter, so the two can never
    be swapped again silently.

    Skipped, loudly, where node is unavailable."""
    import json
    import shutil
    import subprocess
    import tempfile
    if not shutil.which('node'):
        print("       (skipped: no node)")
        return
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(here, 'templates', 'components', 'pet_editor.html'),
               encoding='utf-8').read()
    i = src.index('function petEditorPanel')
    panel = src[i:src.index('\n}\n', i) + 2]
    data = pr._load()
    bundle = {'pieces': data['pieces'],
              'slots': {s: pr.parts(s) for s in
                        ('body', 'top', 'eyes', 'mouth', 'pattern', 'cheeks')},
              'colors': pr.BASE_COLORS, 'defaults': pr.DEFAULTS}
    js = ("const window = {};\n%s\n"
          "const p = petEditorPanel(); p.bundle = %s;\n"
          "const out = {};\n"
          "for (const slot of ['body','top','eyes','mouth','pattern','cheeks']) {\n"
          "  const v = p.parts[slot];\n"
          "  out[slot] = Array.isArray(v) ? v : ('NOT-AN-ARRAY:' + typeof v);\n"
          "}\nconsole.log(JSON.stringify(out));"
          % (panel, json.dumps(bundle)))
    path = os.path.join(tempfile.mkdtemp(), 'panel.js')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(js)
    res = subprocess.run(['node', path], capture_output=True, text=True)
    check(res.returncode == 0, "the editor panel threw: %s" % res.stderr[:400])
    got = json.loads(res.stdout)
    for slot, keys in got.items():
        check(isinstance(keys, list),
              "editor's parts['%s'] is %s -- it must be a list of keys" % (slot, keys))
        check(keys == pr.parts(slot),
              "editor's parts['%s'] does not match the bake" % slot)
        for k in keys:
            check('<' not in k,
                  "editor's parts['%s'] holds SVG art, not a key: %r" % (slot, k[:40]))


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failed = 0
    for t in tests:
        try:
            t()
            print("  ok   %s" % t.__name__)
        except Exception:
            failed += 1
            print("  FAIL %s" % t.__name__)
            traceback.print_exc()
    print("%d/%d passed" % (len(tests) - failed, len(tests)))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

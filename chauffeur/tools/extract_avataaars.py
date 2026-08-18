"""Turn the Avataaars React components into plain SVG fragments we own.

    python tools/extract_avataaars.py <path-to-avataaars-checkout> [-o out.json]

Source: https://github.com/fangpenlin/avataaars (MIT port of Pablo Stanley's
Avataaars, which is free for personal and commercial use). We take the ART and
write our own compositor -- see services/avatar_render.py.

The components are machine-generated from Sketch, so they are regular enough to
convert textually. Two things have to be handled rather than copied:

  IDS. The originals call lodash `uniqueId()` at render time, because two
  avatars on one page would otherwise collide on a shared <mask> id and one
  would render wrong. We keep that property by emitting a `{{NS}}` token in
  every id and reference; the renderer substitutes a per-render nonce.

  COMPOSITION. Child components (<HairColor>, <Colors>, <FacialHair> ...) are
  where colour and other slots get injected. They become explicit tokens the
  renderer expands, so composition stays ours rather than React's.
"""
import argparse
import json
import os
import re
import sys

# JSX writes SVG attributes in camelCase; SVG wants them hyphenated.
ATTR_MAP = {
    'className': 'class', 'fillRule': 'fill-rule', 'fillOpacity': 'fill-opacity',
    'strokeWidth': 'stroke-width', 'strokeLinecap': 'stroke-linecap',
    'strokeLinejoin': 'stroke-linejoin', 'strokeOpacity': 'stroke-opacity',
    'strokeDasharray': 'stroke-dasharray', 'clipPath': 'clip-path',
    'clipRule': 'clip-rule', 'stopColor': 'stop-color',
    'stopOpacity': 'stop-opacity', 'textAnchor': 'text-anchor',
    'fontFamily': 'font-family', 'fontSize': 'font-size',
    'fontWeight': 'font-weight', 'letterSpacing': 'letter-spacing',
    'filterUnits': 'filterUnits', 'maskUnits': 'maskUnits',
    'gradientUnits': 'gradientUnits', 'patternUnits': 'patternUnits',
    'maskContentUnits': 'maskContentUnits',
    'colorInterpolationFilters': 'color-interpolation-filters',
    'floodColor': 'flood-color', 'floodOpacity': 'flood-opacity',
    'stdDeviation': 'stdDeviation', 'xlinkHref': 'xlink:href',
    'dominantBaseline': 'dominant-baseline', 'baseFrequency': 'baseFrequency',
    'numOctaves': 'numOctaves', 'spreadMethod': 'spreadMethod',
    'xChannelSelector': 'xChannelSelector', 'yChannelSelector': 'yChannelSelector',
    'markerWidth': 'markerWidth', 'markerHeight': 'markerHeight',
}

# Child component -> the token the renderer expands. `mask` means "paint a
# colour through this mask"; `slot` means "draw whatever the member chose".
CHILD_FILL = {
    'HairColor': 'hair_color', 'HatColor': 'hat_color',
    'Colors': 'clothe_color', 'Skin': 'skin',
}

# `Colors` is the source's ONE generic colour component, so the same tag means
# the shirt under `clothes` and the beard under `top/facialHair`. Mapped by tag
# alone, every beard came out the colour of the wearer's t-shirt. The colour a
# piece takes is a property of WHERE it is, so the directory gets the last word.
DIR_FILL = {'top/facialHair': {'Colors': 'facial_hair_color'}}
CHILD_SLOT = {
    'FacialHair': 'facial_hair', 'Accessories': 'eyewear', 'Graphics': 'graphic',
}

# Where each source directory lands in our slot model.
SOURCES = [
    ('top', 'top', ('HairColor', 'HatColor', 'index')),
    ('top/facialHair', 'facial_hair', ('Colors', 'index')),
    ('top/accessories', 'eyewear', ('index',)),
    ('clothes', 'clothes', ('Colors', 'Graphics', 'index')),
    ('face/eyes', 'eyes', ('index',)),
    ('face/eyebrow', 'eyebrow', ('index',)),
    ('face/mouth', 'mouth', ('index',)),
    ('face/nose', 'nose', ('index',)),
]


def _render_body(src: str, path: str) -> str:
    """Everything between `return (` in render() and its closing paren."""
    i = src.find('render ()')
    if i < 0:
        i = src.find('render()')
    if i < 0:
        raise ValueError(f'{path}: no render()')
    if 'return (' not in src[i:]:
        return ''   # a Blank piece renders nothing, and that is a real choice
    j = src.index('return (', i) + len('return (')
    depth = 1
    k = j
    while k < len(src) and depth:
        if src[k] == '(':
            depth += 1
        elif src[k] == ')':
            depth -= 1
        k += 1
    return src[j:k - 1].strip()


def _convert(body: str, path: str, source_dir: str = '') -> str:
    # --- id references, before generic attribute handling -------------------
    body = re.sub(r"xlinkHref=\{'#' \+ (\w+)\}", r'xlink:href="#{{NS}}\1"', body)
    body = re.sub(r"xlinkHref=\{`#\$\{(\w+)\}`\}", r'xlink:href="#{{NS}}\1"', body)
    body = re.sub(r"(\w+)=\{'url\(#' \+ (\w+) \+ '\)'\}", r'\1="url(#{{NS}}\2)"', body)
    body = re.sub(r"(\w+)=\{`url\(#\$\{(\w+)\}\)`\}", r'\1="url(#{{NS}}\2)"', body)
    body = re.sub(r"id=\{(\w+)\}", r'id="{{NS}}\1"', body)

    # --- child components become tokens ------------------------------------
    # Attributes come in any order and some carry a defaultColor, so parse the
    # tag rather than pattern-matching one spelling of it.
    def _child(m):
        tag, attrs = m.group(1), m.group(2)
        if tag in CHILD_SLOT:
            return '{{SLOT:%s}}' % CHILD_SLOT[tag]
        mask = re.search(r'maskID=\{(\w+)\}', attrs)
        dflt = re.search(r"defaultColor='([^']*)'", attrs)
        return '{{FILL:%s:%s:%s}}' % (
            (DIR_FILL.get(source_dir) or {}).get(tag) or CHILD_FILL[tag],
            '{{NS}}' + mask.group(1) if mask else '',
            dflt.group(1) if dflt else '')

    known = '|'.join(list(CHILD_FILL) + list(CHILD_SLOT))
    body = re.sub(r'<(' + known + r')\b([^>]*?)/>', _child, body, flags=re.S)
    # <Top><Accessories /></Top>-style wrappers just pass their children on
    body = re.sub(r'<(' + known + r')\b([^>]*?)>(.*?)</\1>',
                  lambda m: _child(m) if m.group(1) in CHILD_SLOT else m.group(3),
                  body, flags=re.S)

    # --- attribute names ----------------------------------------------------
    for jsx, svg in ATTR_MAP.items():
        body = re.sub(r'\b' + jsx + r'=', svg + '=', body)

    # --- leftovers ----------------------------------------------------------
    # Every `top` piece renders {this.props.children} where glasses go: the
    # source composes <Top><Accessories/></Top>, so eyewear draws INSIDE the
    # hair, under a fringe. Keep that -- it is why the glasses look right.
    body = body.replace('{this.props.children}', '{{SLOT:eyewear}}')
    body = re.sub(r'\{/\*.*?\*/\}', '', body, flags=re.S)      # JSX comments
    body = re.sub(r"style=\{\{\s*(\w+):\s*'([^']*)'\s*\}\}",
                  lambda m: 'style="%s:%s"' % (
                      re.sub(r'(?<!^)(?=[A-Z])', '-', m.group(1)).lower(),
                      m.group(2)), body)                         # style objects
    body = re.sub(r"=\{'([^']*)'\}", r'="\1"', body)            # ={'literal'}
    body = re.sub(r'=\{(\d+(?:\.\d+)?)\}', r'="\1"', body)      # ={42}
    # Sketch layer names ride along as literal ids ('Top', 'Squint',
    # 'Clothing/Hoodie'). Nothing references them, and two avatars on one page
    # would both declare them -- duplicate ids in one document. Drop them; the
    # generated {{NS}} ids are the only ones that carry meaning.
    body = re.sub(r"\sid='(?!\{\{NS\}\})[^']*'", '', body)
    body = re.sub(r'\sid="(?!\{\{NS\}\})[^"]*"', '', body)
    body = re.sub(r'\s+', ' ', body).strip()

    leftover = re.search(r'=\{[^}]*\}', body)
    if leftover:
        raise ValueError(f'{path}: unconverted JSX expression {leftover.group(0)!r}')
    # Any surviving `{expr}` that is not one of our own tokens is a piece of
    # React we failed to notice, and it would ship as literal text in the SVG.
    stray = re.search(r'\{(?!\{)[^}]*\}(?!\})', body.replace('{{', '\x01').replace('}}', '\x02'))
    if stray:
        raise ValueError(f'{path}: stray JSX expression {stray.group(0)!r}')
    if re.search(r'<[A-Z]\w*', body):
        raise ValueError(f'{path}: unconverted component {re.search(chr(60) + "[A-Z]" + chr(92) + "w*", body).group(0)!r}')
    return body


def _extract_graphics(path: str) -> dict:
    """Graphics.tsx holds all eleven chest graphics as classes in ONE file --
    which is why the per-file pass skipped them, and why the catalog spent a
    while selling unlockables that drew nothing. Coordinates are relative to
    the clothes group; the renderer wraps them in translate(0,170)."""
    import re as _re
    src = open(path, encoding='utf-8').read()
    out = {}
    # segment per class: some classes destructure ids between render() and
    # return(, so reuse _render_body per chunk instead of one big regex
    for chunk in src.split('export class ')[1:]:
        m = _re.search(r"optionValue = '(\w+)'", chunk)
        if not m:
            continue
        name = m.group(1)
        raw = _render_body(chunk, f'Graphics/{name}')
        if not raw:
            continue
        raw = _re.sub(r'\s*mask=\{`url\(#\$\{this\.props\.maskID\}\)`\}', '', raw)
        raw = _re.sub(r'\s*mask=\{`url\(#\$\{mask1\}\)`\}', '', raw)
        out[name] = _convert(raw, f'Graphics/{name}', 'clothes/Graphics')
    return out


def extract(root: str) -> dict:
    base = os.path.join(root, 'src', 'avatar')
    if not os.path.isdir(base):
        raise SystemExit(f'not an avataaars checkout: {root}')
    out = {}
    for rel, slot, skip in SOURCES:
        d = os.path.join(base, *rel.split('/'))
        if not os.path.isdir(d):
            print(f'  ! missing {rel}', file=sys.stderr)
            continue
        bucket = out.setdefault(slot, {})
        for fn in sorted(os.listdir(d)):
            if not fn.endswith('.tsx'):
                continue
            key = fn[:-4]
            if key in skip:
                continue
            src = open(os.path.join(d, fn), encoding='utf-8').read()
            if 'render' not in src:
                continue
            try:
                bucket[key] = _convert(_render_body(src, fn), f'{rel}/{fn}', rel)
            except ValueError as e:
                print(f'  ! {e}', file=sys.stderr)
        print(f'  {slot:12s} {len(bucket):3d} pieces')
    gfx = os.path.join(base, 'clothes', 'Graphics.tsx')
    if os.path.exists(gfx):
        out['graphic'] = _extract_graphics(gfx)
        print(f"  {'graphic':12s} {len(out['graphic']):3d} pieces")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('source', help='path to a fangpenlin/avataaars checkout')
    ap.add_argument('-o', '--out', default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'static', 'avatar', 'pieces.json'))
    args = ap.parse_args()
    pieces = extract(args.source)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump({'_source': 'https://github.com/fangpenlin/avataaars',
                   '_art': 'Avataaars by Pablo Stanley - free for personal and commercial use',
                   'pieces': pieces}, f, separators=(',', ':'), sort_keys=True)
    total = sum(len(v) for v in pieces.values())
    print(f'wrote {total} pieces -> {args.out} ({os.path.getsize(args.out)//1024} KB)')


if __name__ == '__main__':
    main()

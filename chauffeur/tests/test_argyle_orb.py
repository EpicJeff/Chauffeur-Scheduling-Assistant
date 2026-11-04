"""The Argyle orb is one component: one stylesheet, one factory, the wall and
the phone both use it (PWA reimagined, slice 0).

Run from chauffeur/:  python tests/test_argyle_orb.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from harness import check  # noqa: E402

GRADIENT = 'radial-gradient(120% 120% at 30% 25%, #a78bfa 0%, #6366f1 45%, #2563eb 100%)'
GLYPH = 'M13 10V3L4 14h7v7l9-11h-7z'


def read(rel):
    path = os.path.join(ROOT, *rel.split('/'))
    if not os.path.exists(path):
        return ''
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def rule(css, selector):
    """The declarations of the first `selector {` block, or '' when absent."""
    key = selector + ' {'
    if key not in css:
        return ''
    block = css[css.index(key) + len(key):]
    return block[:block.index('}')]


def scenario_the_orb_look_lives_in_one_stylesheet():
    """The wall painted its own orb in ha_theme.html; the phone needs the same
    look. One stylesheet holds the look, the wall keeps only its position."""
    css = read('static/argyle_orb.css')
    check(css, 'static/argyle_orb.css is missing')
    look = rule(css, '.argyle-orb')
    check(GRADIENT in look, 'the orb gradient is not the wall gradient')
    check('rgb(255 255 255 / 0.22)' in look, 'the orb border is not the wall border')
    check('0 6px 22px rgb(79 70 229 / .45)' in look and '0 0 0 6px rgb(99 102 241 / .12)' in look,
          'the orb shadow is not the wall shadow')
    check('var(--argyle-orb-size, 3.25rem)' in look, 'the orb size is not a variable with the wall default')
    check('border-radius' in look and '999px' in look, 'the orb is not round')
    check('@keyframes argyle-orb-breathe' in css, 'the breathe animation is gone')
    check('prefers-reduced-motion: no-preference' in css, 'the breathe animation ignores reduced motion')
    hidden = rule(css, '.argyle-orb-hidden')
    check('opacity: 0' in hidden or 'opacity:0' in hidden, 'the hidden state does not fade')
    check('visibility: hidden' in hidden or 'visibility:hidden' in hidden, 'the hidden state stays tappable')
    check('var(--argyle-orb-base-transform, translate(0))' in hidden and 'scale(0.72)' in hidden,
          'the hidden state does not compose the base transform with the shrink (none + scale is not a transform list)')

    theme = read('templates/ha_theme.html')
    orb = rule(theme, '#panel-chat-orb')
    check(orb, 'the wall lost its orb rule')
    check('radial-gradient' not in orb and 'box-shadow' not in orb and 'border-radius' not in orb,
          'the wall still paints its own orb')
    check('left: 50%' in orb and 'translateX(-50%)' in orb, 'the wall lost its centring')
    check('--argyle-orb-base-transform: translateX(-50%)' in orb,
          'the wall does not hand its centring to the shared hidden state')
    check('argyle-orb-breathe' not in theme, 'the wall still owns a breathe animation')
    check("'static/argyle_orb.css'|ver" in read('templates/nav.html'),
          'the wall does not load the shared look')


def scenario_the_factory_builds_the_button():
    """One script builds the button, so the wall and the phone cannot drift
    on the glyph or the aria label shape."""
    js = read('static/argyle_orb.js')
    check(js, 'static/argyle_orb.js is missing')
    check('window.ArgyleOrb' in js, 'the factory is not exported on window')
    check('glyph' in js and 'create' in js, 'the factory lacks glyph() or create()')
    check(GLYPH in js, 'the glyph path is not the wall glyph')
    check("'button'" in js or '"button"' in js, 'the factory does not set type=button')
    check('aria-label' in js or 'ariaLabel' in js, 'the factory does not label the button')
    check('argyle-orb' in js, 'the factory does not stamp the shared class')

    cc = read('templates/components/control_center.html')
    check('ArgyleOrb.create(' in cc, 'the wall does not build its orb through the factory')
    check("id: 'panel-chat-orb'" in cc, 'the wall orb lost its id')
    check("orb.innerHTML = '<svg" not in cc, 'the wall still hand-draws the glyph')
    check("'static/argyle_orb.js'|ver" in cc or "'static/argyle_orb.js'|ver" in read('templates/nav.html'),
          'the wall does not load the factory')


def scenario_the_factory_runs_in_node():
    """The factory is plain script with no DOM at load time, so a minimal
    document stub is enough to prove create() returns the right element."""
    import shutil
    import subprocess
    import tempfile
    node = shutil.which('node')
    if not node:
        print('  skip  node is not installed')
        return
    js = read('static/argyle_orb.js')
    check(js, 'static/argyle_orb.js is missing')
    stub = """
const els = [];
global.window = global;
global.document = { createElement(tag) {
  const e = { tagName: tag.toUpperCase(), attrs: {}, classList: { add(c) { e.className = ((e.className || '') + ' ' + c).trim(); } },
    setAttribute(k, v) { e.attrs[k] = String(v); }, getAttribute(k) { return e.attrs[k]; } };
  Object.defineProperty(e, 'id', { set(v) { e.attrs.id = v; }, get() { return e.attrs.id; } });
  Object.defineProperty(e, 'type', { set(v) { e.attrs.type = v; }, get() { return e.attrs.type; } });
  els.push(e); return e; } };
"""
    tail = """
const b = window.ArgyleOrb.create({ id: 'tab-argyle', label: 'Ask Argyle' });
console.log(JSON.stringify({ tag: b.tagName, id: b.id || b.attrs.id, type: b.type || b.attrs.type,
  cls: b.className, label: b.attrs['aria-label'] || b.ariaLabel, html: b.innerHTML || '',
  glyph: window.ArgyleOrb.glyph() }));
"""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'orb.js')
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(stub + js + tail)
        out = subprocess.run([node, path], capture_output=True, text=True)
    check(out.returncode == 0, 'the factory threw: ' + out.stderr.strip()[-400:])
    import json
    got = json.loads(out.stdout.strip().splitlines()[-1])
    check(got['tag'] == 'BUTTON', 'create() did not return a button')
    check(got['id'] == 'tab-argyle', 'create() ignored the id')
    check(got['type'] == 'button', 'create() did not set type=button')
    check('argyle-orb' in (got['cls'] or '').split(), 'create() did not stamp .argyle-orb')
    check(got['label'] == 'Ask Argyle', 'create() ignored the label')
    check(GLYPH in got['html'], 'create() did not draw the glyph')
    check('<svg' in got['glyph'] and GLYPH in got['glyph'], 'glyph() is not the SVG markup')


def scenario_the_phone_bar_ends_with_the_orb():
    """The adult tab bar's last slot is the orb, built from the same assets
    the wall loads, in an evenly spaced row of equal slots."""
    app = read('templates/app.html')
    check('id="tab-argyle"' in app, 'the phone has no orb button')
    check(app.index('id="tab-more"') < app.index('id="tab-argyle"'), 'the orb is not after the More tab')
    check('class="argyle-orb"' in app[app.index('id="tab-argyle"') - 200:app.index('id="tab-argyle"') + 200],
          'the phone orb does not wear the shared class')
    check("'static/argyle_orb.css'|ver" in app and "'static/argyle_orb.js'|ver" in app,
          'the phone does not load the shared orb assets')
    css = read('static/pwa_shell.css')
    check('justify-content: space-between' in css, 'the tab bar is not an evenly spaced row')
    check('#tab-argyle' in css, 'the tab bar has no slot rule for the orb')
    check('[data-audience="child"] #tab-argyle' in css, 'kid bars are not kept clear of the orb')
    js = read('static/pwa_shell.js')
    check('function pwaOrbAllowed' in js and "scopeOf('chat.agent')" in js,
          'the orb does not read the chat.agent facet')
    check('alert(' not in js.replace('showGlobalAlert(', ''), 'a browser dialog crept into the shell')
    # Slice 2: the orb's tap/hold is a gesture bound by the shell, not an
    # inline onclick; it opens the overlay (static/pwa_argyle.js). The DM
    # opener survives as the overlay hint's path to Messages.
    tag_start = app.rindex('<', 0, app.index('id="tab-argyle"'))
    tag = app[tag_start:app.index('>', app.index('id="tab-argyle"')) + 1]
    check('onclick="pwaOpenArgyle()"' not in tag and 'onclick=' not in tag,
          'the orb still opens the DM from an inline onclick: ' + tag)
    check("'static/pwa_argyle.js'|ver" in app, 'the phone does not load the Argyle overlay')
    check('function pwaOpenArgyle' in js, 'the overlay hint has no path to the Messages thread')
    check('function pwaArgyleBindOrb' in js, 'the orb has no tap/hold gesture binding')
    for name, src in (('templates/app.html', app), ('static/pwa_shell.js', js)):
        check('toggleKioskChat' not in src, name + ' still carries the Ask Argyle popup (toggleKioskChat)')
        check('kiosk-chat-popup' not in src, name + ' still carries #kiosk-chat-popup')
    overlay = read('static/pwa_argyle.js')
    check(overlay, 'static/pwa_argyle.js is missing')
    check('window.PwaArgyle' in overlay, 'the overlay module does not export window.PwaArgyle')


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('scenario_') and callable(fn):
            fn()
            print('  ok  ' + name)

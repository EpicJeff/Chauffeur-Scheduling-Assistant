"""Every moment media URL carries the token, checked by RUNNING the builders.

Found 2026-10-22, two weeks after the auth flip: moments showed in no PWA
chat, on no hearth and in no gallery. `/api/media/*` and
`/api/moments/*/media` are wall-tier routes, and an `<img>` or `<video>` can
carry no header, so the token has to ride the query string — which is what
`chfAuthUrl` does, and what `momentPosterSrc` already did one function below
the builder that did not. The source-reading picture test in
test_template_js.py looks for the LITERAL `api/media/` and never saw these:
they build from `att.url`, a value. So this test extracts each builder and
runs it under node against a stubbed `chfAuthUrl`.

The same class on the wall: HA area-card photographs. The server rewrites
them to `api/ha/image64/...` (wall tier), the host hands them to
`hass.hassUrl`, and the hourly freshness tick rebuilt the URL by splitting on
`?` — which would have thrown away any token the first fix added.

Run from chauffeur/:  python tests/test_moment_media_token.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TPL = os.path.join(ROOT, 'templates')
STATIC = os.path.join(ROOT, 'static')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _read(*parts):
    return open(os.path.join(*parts), encoding='utf-8').read()


def _block_from(src, start):
    """The `{...}` body that begins at the first brace after `start`."""
    i = src.index('{', start)
    depth = 0
    for j in range(i, len(src)):
        if src[j] == '{':
            depth += 1
        elif src[j] == '}':
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    raise AssertionError("unbalanced braces")


def _function_text(src, header):
    """`header` through the end of its body."""
    start = src.index(header)
    return header + _block_from(src, start + len(header))


STUB = r"""
var apiBase = 'base/';
var rlApiBase = apiBase;
var window = globalThis;
window.memberToken = function () { return 'tok-1'; };
window.chfAuthUrl = function (url) {
  return url + (url.indexOf('?') >= 0 ? '&' : '?') + 'member_token=tok-1';
};
"""


def _run_node(script):
    node = shutil.which('node')
    if not node:
        return None
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False,
                                     encoding='utf-8') as f:
        f.write(script)
        path = f.name
    try:
        res = subprocess.run([node, path], capture_output=True, text=True,
                             timeout=30)
    finally:
        os.unlink(path)
    check(res.returncode == 0, f"node failed:\n{res.stderr[-1500:]}")
    return json.loads(res.stdout.strip().splitlines()[-1])


def _assert_tokened(got, where):
    check('member_token=tok-1' in (got['photo'] or ''),
          f"{where}: a photo url built without the token: {got['photo']!r}")
    check(got['photo'].startswith('base/api/media/p1'),
          f"{where}: the photo url lost its base or id: {got['photo']!r}")
    check('member_token=tok-1' in (got['clip'] or ''),
          f"{where}: a clip url built without the token: {got['clip']!r}")
    check(got['data'] == 'data:image/png;base64,AAAA',
          f"{where}: an inline data url must pass through untouched: {got['data']!r}")
    check(got['empty'] == '', f"{where}: nothing in gives nothing out: {got['empty']!r}")


def scenario_the_pwa_chat_builder_carries_the_token():
    """`momentMediaSrc` in app.html draws every photo and clip in a thread,
    the lightbox and the attach preview."""
    src = _read(TPL, 'app.html')
    fn = _function_text(src, 'function momentMediaSrc(att)')
    got = _run_node(STUB + fn + r"""
console.log(JSON.stringify({
  photo: momentMediaSrc({ kind: 'photo', url: '/api/media/p1.jpg' }),
  clip: momentMediaSrc({ kind: 'video', url: '/api/media/c1.mp4' }),
  data: momentMediaSrc({ kind: 'photo', data_url: 'data:image/png;base64,AAAA' }),
  empty: momentMediaSrc(null),
}));
""")
    if got is None:
        print("  skip  node is not installed")
        return
    _assert_tokened(got, 'app.html momentMediaSrc')


def scenario_the_hearth_builder_carries_the_token():
    """`mediaUrl` in moments_hearth.html: the full-screen pop on every kiosk
    page and in the PWA."""
    src = _read(TPL, 'components', 'moments_hearth.html')
    fn = _function_text(src, 'function mediaUrl(m, which)')
    got = _run_node(STUB + fn + r"""
console.log(JSON.stringify({
  photo: mediaUrl({ media_url: '/api/media/p1.jpg' }),
  clip: mediaUrl({ attachment: { url: '/api/media/c1.mp4' } }),
  poster: mediaUrl({ media_url: '/api/media/c1.mp4', poster_url: '/api/media/c1.jpg' }, 'poster'),
  data: mediaUrl({ attachment: { data_url: 'data:image/png;base64,AAAA' } }),
  empty: mediaUrl({}),
}));
""")
    if got is None:
        print("  skip  node is not installed")
        return
    _assert_tokened(got, 'moments_hearth.html mediaUrl')
    check('member_token=tok-1' in got['poster'] and 'c1.jpg' in got['poster'],
          f"the poster url lost the token: {got['poster']!r}")


def scenario_the_gallery_builder_carries_the_token():
    """`url` in moments_gallery.html: every thumbnail and the opened item."""
    src = _read(TPL, 'components', 'moments_gallery.html')
    m = re.search(r'const url = (.*?);\n', src)
    check(m, "the gallery's url helper moved")
    got = _run_node(STUB + "var opts = { apiBase: 'base/' };\nconst url = " + m.group(1) + r""";
console.log(JSON.stringify({
  photo: url('/api/media/p1.jpg'),
  clip: url('/api/media/c1.mp4'),
  data: 'data:image/png;base64,AAAA',
  // A missing poster keeps its old shape (the base alone): the thumbnail's
  // onerror fallback to the full media depends on that request FAILING.
  empty: url('').startsWith('base/') ? '' : url(''),
}));
""")
    if got is None:
        print("  skip  node is not installed")
        return
    _assert_tokened(got, 'moments_gallery.html url')


def scenario_the_kitchen_overlay_builder_carries_the_token():
    """`momentSrc` in kitchen_overlay.js, the Kitchen board's collage."""
    src = _read(STATIC, 'kitchen_overlay.js')
    start = src.index('momentSrc: function (m)')
    body = _block_from(src, start)
    got = _run_node(STUB + "var base = 'base/';\nvar momentSrc = function (m) " + body + r""";
console.log(JSON.stringify({
  photo: momentSrc({ media_url: '/api/media/p1.jpg' }),
  clip: momentSrc({ attachment: { url: '/api/media/c1.mp4' } }),
  data: momentSrc({ attachment: { data_url: 'data:image/png;base64,AAAA' } }),
  empty: momentSrc({}),
}));
""")
    if got is None:
        print("  skip  node is not installed")
        return
    _assert_tokened(got, 'kitchen_overlay.js momentSrc')


PIC64 = 'api/ha/image64/L2FwaS9pbWFnZS9zZXJ2ZS9hYmMvNTEyeDUxMg'


def scenario_an_area_photograph_carries_the_panels_token_and_keeps_it_hourly():
    """The hosted area card runs its picture through `hass.hassUrl`, which
    prefixed the base and nothing else; the hourly tick then split on `?`.
    Both halves run here: the URL the card would draw, and the URL after one
    tick of the freshness timer."""
    sys.path.insert(0, HERE)
    import test_ha_card_host_runtime as host
    probe = host.BUILTIN_PROBE
    probe = probe.replace(
        "globalThis.setInterval = function () { return 0; };",
        "var ticks = [];\nglobalThis.setInterval = function (fn) { ticks.push(fn); return 0; };")
    probe = probe.replace(
        "window.customElements = {",
        "window.chfAuthUrl = function (url) {\n"
        "  return url + (url.indexOf('?') >= 0 ? '&' : '?') + 'device_token=dev-abc';\n"
        "};\nwindow.customElements = {")
    probe = probe.replace("picture: 'api/ha/image?p=1'", f"picture: '{PIC64}'")
    probe = probe.replace(
        "console.log(JSON.stringify({\n    mounted: ok,",
        "var area0 = hass.areas && hass.areas.study;\n"
        "var pic0 = (area0 && hass.hassUrl) ? hass.hassUrl(area0.picture) : null;\n"
        "ticks.forEach(function (fn) { fn(); });\n"
        "var area1 = hass.areas && hass.areas.study;\n"
        "var pic1 = (area1 && hass.hassUrl) ? hass.hassUrl(area1.picture) : null;\n"
        "console.log(JSON.stringify({\n    pic0: pic0, pic1: pic1,\n    mounted: ok,")
    for needle in ("var ticks = [];", "window.chfAuthUrl", PIC64, "var area0"):
        check(needle in probe, f"the host probe no longer has the seam this test splices at: {needle}")
    got = host._run(probe)
    if got is None:
        print("  skip  node is not installed")
        return
    check(got['pic0'] and got['pic0'].startswith(PIC64)
          and 'device_token=dev-abc' in got['pic0'],
          f"the area photograph carries no token: {got['pic0']!r}")
    check(got['pic1'] and got['pic1'].startswith(PIC64)
          and 'device_token=dev-abc' in got['pic1'] and 'v=' in got['pic1']
          and got['pic1'].count('device_token=') == 1,
          f"after one freshness tick the token is gone or doubled: {got['pic1']!r}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} moment media token scenarios passed")

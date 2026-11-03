"""The adult shell's time-of-day sky, checked by RUNNING `pwaSky` under node.

PWA reimagined slice 0, Task 3: `pwaSky(hour, dark)` in static/pwa_shell.js
returns the three gradient stops `{top, mid, bottom}` the shell writes to
`--pwa-sky-top/-mid/-bottom`. Four bands (morning 05-11, afternoon 12-16,
evening 17-20, night 21-04); the light morning is the approved mockup;
every stop reads against the shell's ink at WCAG AA in both themes; the dark
sky is the deep version of the same band. `pwaSky.contrast(a, b)` is the
WCAG ratio the shell uses.

The luminance this test asserts on is computed HERE, in the node script,
with the WCAG sRGB formula, so the dark-is-deep check never trusts the
implementation's own maths; the implementation's `pwaSky.contrast` is used
for the AA check and cross-checked against the same formula.

Run from chauffeur/:  python tests/test_pwa_sky.py
"""
import json
import os
import re
import shutil
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATIC = os.path.join(ROOT, 'static')

LIGHT_INK = '#1f1d2b'
DARK_INK = '#f3f2f7'
STOPS = ('top', 'mid', 'bottom')
BANDS = {'morning': range(5, 12), 'afternoon': range(12, 17),
         'evening': range(17, 21), 'night': list(range(21, 24)) + list(range(0, 5))}


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _read(*parts):
    return open(os.path.join(*parts), encoding='utf-8').read()


# --- extraction --------------------------------------------------------------
# pwa_shell.js keeps every top-level statement at column 0 and indents
# everything inside one, so a top-level chunk runs from one column-0 line to
# the next. Each chunk is named by what it declares (`function X`,
# `const/let/var X =`) or what it hangs a property on (`X.contrast = ...`,
# `Object.assign(X, ...)`). The test takes `pwaSky` and `pwaProfilePalette`
# plus whatever top-level helpers and tables they reference, so a band table
# or a shared luminance helper the builder factors out comes along, and
# nothing that touches the page does.

_IDENT = r'[A-Za-z_$][\w$]*'


def _chunks(src):
    chunks, cur = [], []
    for line in src.split('\n'):
        starts = bool(line) and not line[0].isspace() and line[0] not in '})]'
        if starts and cur:
            chunks.append('\n'.join(cur))
            cur = []
        cur.append(line)
    if cur:
        chunks.append('\n'.join(cur))
    return chunks


def _chunk_names(chunk):
    first = chunk.split('\n', 1)[0]
    m = re.match(r'(?:async\s+)?function\s*\*?\s*(' + _IDENT + r')\s*\(', first)
    if m:
        return {m.group(1)}
    if re.match(r'(?:const|let|var)\s', first):
        return set(re.findall(r'(?:\b(?:const|let|var)\s+|,\s*)(' + _IDENT + r')\s*=(?![=>])', first))
    m = re.match(r'Object\.assign\(\s*(' + _IDENT + r')\b', first)
    if m:
        return {m.group(1)}
    m = re.match(r'(' + _IDENT + r')\.[\w$.]+\s*=(?!=)', first)
    if m and m.group(1) not in ('window', 'globalThis', 'document', 'self'):
        return {m.group(1)}
    return set()


def _sky_source():
    src = _read(STATIC, 'pwa_shell.js')
    chunks = [(c, _chunk_names(c)) for c in _chunks(src)]
    defined = set().union(*(names for _, names in chunks))
    check('pwaSky' in defined,
          "static/pwa_shell.js defines no pwaSky(hour, dark): the time-of-day sky is not built")
    check('pwaProfilePalette' in defined, "pwaProfilePalette left static/pwa_shell.js")
    want, grew = {'pwaSky', 'pwaProfilePalette'}, True
    while grew:
        grew = False
        for chunk, names in chunks:
            if names & want:
                for name in defined - want:
                    if re.search(r'(?<![\w$.])' + re.escape(name) + r'(?![\w$])', chunk):
                        want.add(name)
                        grew = True
    return '\n'.join(chunk for chunk, names in chunks if names & want)


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


# No `document`, no `window`: the sky is a pure function of the hour and the
# theme, and the node global scope defines neither.
PROBE = r"""
const LIGHT_INK = %(light)s, DARK_INK = %(dark)s, STOPS = ['top', 'mid', 'bottom'];
function wcagLuminance(hex) {
  let h = String(hex || '').trim().replace(/^#/, '');
  if (/^[0-9a-f]{3}$/i.test(h)) h = h.split('').map(c => c + c).join('');
  if (!/^[0-9a-f]{6}$/i.test(h)) return null;
  const ch = [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16) / 255)
    .map(c => c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
  return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
}
function wcagContrast(a, b) {
  const la = wcagLuminance(a), lb = wcagLuminance(b);
  if (la === null || lb === null) return null;
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}
const out = {error: null, document_defined: typeof document !== 'undefined',
             window_defined: typeof window !== 'undefined', light: [], dark: []};
try {
  if (typeof pwaSky !== 'function') throw new Error('pwaSky is not a function');
  if (typeof pwaSky.contrast !== 'function') throw new Error('pwaSky.contrast is not a function');
  out.morning = pwaSky(8, false);
  for (const [mode, dark, ink] of [['light', false, LIGHT_INK], ['dark', true, DARK_INK]]) {
    for (let h = 0; h < 24; h++) {
      const sky = pwaSky(h, dark);
      const row = {sky, contrast: {}, own_contrast: {}, luminance: {}};
      for (const s of STOPS) {
        row.contrast[s] = pwaSky.contrast(sky[s], ink);
        row.own_contrast[s] = wcagContrast(sky[s], ink);
        row.luminance[s] = wcagLuminance(sky[s]);
      }
      row.luminance_top = row.luminance.top;
      out[mode].push(row);
    }
  }
} catch (e) {
  out.error = String((e && e.stack) || e);
}
console.log(JSON.stringify(out));
"""

_CACHE = {}


def _sky():
    """The node run, once per process. None when node is not installed; a
    missing `pwaSky` fails in `_sky_source` before node is even looked for."""
    if 'out' not in _CACHE:
        source = _sky_source()
        _CACHE['out'] = _run_node(source + '\n' + PROBE % {
            'light': json.dumps(LIGHT_INK), 'dark': json.dumps(DARK_INK)})
    return _CACHE['out']


def _ran():
    out = _sky()
    if out is None:
        print("  skip  node is not installed")
        return None
    check(out['error'] is None, f"pwaSky threw under node:\n{out['error']}")
    return out


def scenario_sky_is_pure():
    """Calling pwaSky never reaches for the page: node defines no
    `document`, so a single touch throws."""
    out = _sky()
    if out is None:
        print("  skip  node is not installed")
        return
    check(not out['document_defined'], "the probe leaked a document global")
    check(out['error'] is None or 'document' not in out['error'],
          f"pwaSky touched document:\n{out['error']}")
    check(out['error'] is None, f"pwaSky threw under node:\n{out['error']}")


def scenario_morning_is_the_mockup():
    out = _ran()
    if out is None:
        return
    check(out['morning'] == {'top': '#fff0e6', 'mid': '#f6eef7', 'bottom': '#eef0fb'},
          f"pwaSky(8, false) is not spec mockup A: {out['morning']!r}")


def scenario_every_hour_reads_against_the_ink():
    out = _ran()
    if out is None:
        return
    for mode, ink in (('light', LIGHT_INK), ('dark', DARK_INK)):
        for hour in range(24):
            row = out[mode][hour]
            for stop in STOPS:
                check(isinstance(row['sky'].get(stop), str) and row['luminance'][stop] is not None,
                      f"{mode} {hour:02d}:00 {stop} is not a hex colour: {row['sky']!r}")
                got = row['contrast'][stop]
                check(isinstance(got, (int, float)) and got >= 4.5,
                      f"{mode} {hour:02d}:00 {stop} {row['sky'][stop]} against {ink} is {got!r}, under 4.5")
                own = row['own_contrast'][stop]
                check(abs(got - own) <= 0.01,
                      f"pwaSky.contrast({row['sky'][stop]}, {ink}) = {got!r} but WCAG says {own:.3f}")


def scenario_dark_is_the_deep_version():
    out = _ran()
    if out is None:
        return
    for hour in range(24):
        row = out['dark'][hour]
        lum = row['luminance_top']
        check(lum is not None and lum < 0.08,
              f"dark {hour:02d}:00 top {row['sky'].get('top')!r} has luminance {lum!r}, not under 0.08")


def scenario_four_bands_only():
    out = _ran()
    if out is None:
        return
    skies = {json.dumps(out['light'][h]['sky'], sort_keys=True) for h in range(24)}
    check(len(skies) == 4, f"the light sky has {len(skies)} looks across the day, not 4: {sorted(skies)}")


def scenario_bands_change_at_the_plan_hours():
    """Morning 05-11, afternoon 12-16, evening 17-20, night 21-04."""
    out = _ran()
    if out is None:
        return
    looks = {}
    for band, hours in BANDS.items():
        seen = {json.dumps(out['light'][h]['sky'], sort_keys=True) for h in hours}
        check(len(seen) == 1, f"the {band} hours {list(hours)} do not share one sky: {sorted(seen)}")
        looks[band] = seen.pop()
    check(len(set(looks.values())) == 4, f"two bands share a sky: {looks}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} pwa sky scenarios passed")

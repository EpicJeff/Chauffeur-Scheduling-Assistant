"""Every template's inline JavaScript actually parses.

Written after a one-character bug reached the wall: an apostrophe inside a
single-quoted string (`'Replace Argyle's token'`) ended `configApp()`'s script
early, and the config page came up as a row of tabs with **nothing underneath
them** — because when the component fails to initialise, every `x-show`
evaluates falsey and Alpine hides the entire page rather than saying anything.

That is the failure mode worth defending against, and it is not specific to
that one quote:

  * It is SILENT. No Python raised, no test failed, the server returned 200,
    and the page was blank. The console had the error; nobody was looking at
    the console.
  * It is TOTAL. One bad character does not break one control, it takes out
    every control that component draws.
  * It is easy to reintroduce, because this project writes a lot of JavaScript
    inside Jinja, where the editor gives no syntax help at all.

So: parse every inline `<script>` in every template with node, having first
substituted the Jinja away. Skips templates when node is unavailable, the same
way the render tests do.

Run from chauffeur/:  python tests/test_template_js.py
"""
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'templates')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# `{{ ... }}` becomes a literal, `{% ... %}` disappears. Both substitutions are
# deliberately dumb: the point is to check the JAVASCRIPT's shape, not to
# render the template, and a placeholder that parses is all that needs to be
# true of the Jinja.
def _strip_jinja(src: str) -> str:
    src = re.sub(r'\{\{.*?\}\}', 'null', src, flags=re.S)
    src = re.sub(r'\{%.*?%\}', '', src, flags=re.S)
    return src


def _inline_scripts(path: str):
    body = open(path, encoding='utf-8').read()
    # Only scripts with a body; `<script src=...>` has nothing to parse.
    return [_strip_jinja(m) for m in
            re.findall(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', body, re.S)
            if m.strip()]


def scenario_every_inline_script_parses():
    node = shutil.which('node')
    if not node:
        print("  skip  node unavailable — inline scripts were not parsed")
        return
    broken = []
    tmp = tempfile.mkdtemp(prefix='chauffeur_tpljs_')
    for path in sorted(glob.glob(os.path.join(TPL, '**', '*.html'), recursive=True)):
        name = os.path.relpath(path, TPL)
        for i, src in enumerate(_inline_scripts(path)):
            f = os.path.join(tmp, f"{name.replace(os.sep, '_')}.{i}.js")
            with open(f, 'w', encoding='utf-8') as fh:
                fh.write(src)
            res = subprocess.run([node, '--check', f], capture_output=True,
                                 text=True, timeout=60)
            if res.returncode != 0:
                first = (res.stderr or '').strip().splitlines()
                detail = next((ln for ln in first if 'Error' in ln), first[-1] if first else '?')
                broken.append(f"{name} (script #{i + 1}): {detail}")
    check(not broken,
          "inline JavaScript that does not parse — the page will render as an "
          "empty shell with no error anywhere a person will look:\n  "
          + "\n  ".join(broken))


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} template-js scenarios passed")

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



# Alpine's own magics and globals: `$store.x`, `window.y`, `Math.round` are
# roots that are never component state, so they are not evidence of anything.
_NOT_STATE = {
    'window', 'document', 'location', 'localStorage', 'sessionStorage',
    'navigator', 'console', 'Math', 'JSON', 'Object', 'Array', 'String',
    'Number', 'Boolean', 'Date', 'this', 'e', 'event', 'crypto',
}


def scenario_every_x_model_root_is_defined_somewhere():
    """`x-model="settings.smtp_host"` where nothing defines `settings`.

    The other half of the blank-page failure, and the half a parser cannot
    see: the script was perfectly valid, the binding simply named state that
    did not exist. Alpine throws `ReferenceError: settings is not defined` on
    every affected control — into the console, where nobody is looking — and
    the panel renders as nothing.

    Deliberately loose: it asks only whether the root identifier appears
    ANYWHERE in the template and its includes, not whether it is in scope.
    A tighter check would need to model Alpine's component tree, and the bug
    worth catching is the invented name rather than the misplaced one."""
    import re as _re
    import tpl_source
    broken = []
    for path in sorted(glob.glob(os.path.join(TPL, '*.html'))):
        name = os.path.basename(path)
        try:
            full = tpl_source.read(name)
        except Exception:
            full = open(path, encoding='utf-8').read()
        roots = set(_re.findall(r'x-model(?:\.\w+)*="\s*([A-Za-z_$][\w$]*)\s*\.', full))
        # Names introduced by `x-for` are scope, not state — `entry` in
        # `x-for="(entry, i) in rows"` is defined by Alpine and appears
        # nowhere in the script, which is correct and must not be flagged.
        scoped = set(_re.findall(r'x-for="\s*\(?\s*([A-Za-z_$][\w$]*)', full))
        for root in sorted(roots - _NOT_STATE - scoped):
            # Defined as component state (`root: {`), a declaration, or an
            # assignment — any of which means somebody meant it to exist.
            if _re.search(r'(?:^|[\s{,])' + _re.escape(root) + r'\s*[:=]', full, _re.M):
                continue
            broken.append(f"{name}: x-model binds `{root}.…` but nothing defines `{root}`")
    check(not broken,
          "Alpine bindings naming state that does not exist — every control "
          "using them renders as nothing, with the error only in the console:"
          "\n  " + "\n  ".join(broken))


def scenario_a_cloaked_element_is_hidden_by_something_the_page_actually_has():
    """The third member of the blank-page family, and the worst so far.

    `x-cloak` hides nothing on its own. It needs a `[x-cloak] { display: none }`
    rule from the page AND Alpine to take the attribute off afterwards — and a
    shared component included by nav.html cannot assume either. Six admin pages
    (Schedule, Calendar, Trips, Map, Moments, the trip pages) run no Alpine and
    define no cloak rule, so S6's pairing overlay — `fixed inset-0 z-[9500]
    bg-black` — painted over all of them permanently. A black screen with only
    Home Assistant's chrome around it, no error, HTTP 200.

    So: any page that ends up with a cloaked element must ALSO end up with a
    rule that hides one. Checked on the ASSEMBLED page, includes and all,
    because the element and the rule usually live in different files.
    """
    import re as _re
    import tpl_source
    broken = []
    for path in sorted(glob.glob(os.path.join(TPL, '*.html'))):
        name = os.path.basename(path)
        try:
            full = tpl_source.read(name)
        except Exception:
            full = open(path, encoding='utf-8').read()
        if 'x-cloak' not in full:
            continue
        # The rule as a CSS selector, not the attribute: `[x-cloak]` followed
        # by a declaration block is what actually hides anything.
        if _re.search(r'\[x-cloak\][^{]*\{[^}]*display\s*:\s*none', full):
            continue
        broken.append(name)
    check(not broken,
          "pages carrying x-cloak with no rule that hides it — every cloaked "
          "element draws, and a full-screen one is a blank page:\n  "
          + "\n  ".join(broken))


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} template-js scenarios passed")

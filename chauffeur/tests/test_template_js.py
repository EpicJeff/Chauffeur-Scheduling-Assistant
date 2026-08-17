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


def scenario_an_id_in_a_url_comes_from_something_that_has_one():
    """The fifth blank-page-family bug, and this one shipped a dead button.

    `sendInvite(member)` read `member.id` and was handed `memberEdit` — an
    object `startEditMember` builds field by field, deliberately WITHOUT an id,
    because the id has a home of its own in `editMemberId`. So every invite the
    app ever sent went to `api/members/undefined/invite` and came back "Member
    not found". Valid JavaScript, valid Alpine, 404 from a real route.

    The generic form: a fetch URL interpolating `<name>.id` where `<name>` is
    an Alpine state object this template never puts an `id` on. `x-for` scope
    names and function parameters are excluded — those come from somewhere this
    check cannot see, and flagging them would make the test noise.
    """
    import re as _re
    import tpl_source

    # `name(params) {` — filtered against the keywords that also match.
    FN = _re.compile(r'\b([A-Za-z_$][\w$]*)\s*\(([^)\n]*)\)\s*\{')
    KEYWORDS = {'if', 'for', 'while', 'switch', 'catch', 'function', 'return'}

    broken = []
    for path in sorted(glob.glob(os.path.join(TPL, '*.html'))):
        name = os.path.basename(path)
        try:
            full = tpl_source.read(name)
        except Exception:
            full = open(path, encoding='utf-8').read()

        # Which functions address a request with `<param>.id`, and via which
        # parameter position.
        addressed = {}
        for m in FN.finditer(full):
            fn, sig = m.group(1), m.group(2)
            if fn in KEYWORDS or not sig.strip():
                continue
            params = [p.strip().split('=')[0].strip() for p in sig.split(',')]
            body = _block_from(full, full.index('{', m.end() - 1))
            for i, param in enumerate(params):
                if not param or not _re.match(r'^[A-Za-z_$][\w$]*$', param):
                    continue
                if _re.search(r'`[^`]*\$\{\s*' + _re.escape(param)
                              + r'\.id\s*\}[^`]*`', body):
                    addressed.setdefault(fn, set()).add(i)

        # Which of those are called from the MARKUP with a bare state object.
        for fn, positions in addressed.items():
            for call in _re.finditer(r'"\s*' + _re.escape(fn) + r'\(([^)"]*)\)',
                                     full):
                args = [a.strip() for a in call.group(1).split(',')]
                for pos in positions:
                    if pos >= len(args):
                        continue
                    arg = args[pos]
                    if not _re.match(r'^[A-Za-z_$][\w$]*$', arg or ''):
                        continue
                    literal = _state_literal(full, arg)
                    if not literal:
                        continue          # not component state; out of scope
                    if _re.search(r'[\{,]\s*id\s*:', literal):
                        continue          # the literal declares an id
                    if _re.search(_re.escape(arg) + r'\.id\s*=', full):
                        continue          # something assigns one later
                    if _re.search(_re.escape(arg) + r'\s*=\s*\{[^}]*\bid\b',
                                  full, _re.S):
                        continue          # rebuilt wholesale with an id
                    broken.append(
                        f"{name}: {fn}() addresses a request with `.id` and the "
                        f"markup hands it `{arg}`, which never has one")
    check(not broken,
          "a request addressed with an id that does not exist — the route is "
          "real, the object is real, and the call 404s:\n  "
          + "\n  ".join(sorted(set(broken))))


def _block_from(src, start):
    """The brace-matched block beginning at `start`. These bodies are long and
    nested, so counting braces beats any regex."""
    depth = 0
    for i in range(start, len(src)):
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    return src[start:]


def _state_literal(src, name):
    """The object literal `name:` is initialised to as component state, or ''.
    Anything else — a loop variable, a local — returns '' and is left alone."""
    import re as _re
    m = _re.search(r'(?:^|[\s{,])' + _re.escape(name) + r'\s*:\s*\{', src, _re.M)
    return _block_from(src, src.index('{', m.start())) if m else ''


def scenario_a_shared_component_never_works_out_its_own_path_depth():
    """`/board/{slug}` is TWO path segments and every other page route is one.

    Fifty-one places in this repo computed their own base with
    `pathname.endsWith('/') ? '../' : ''`, which is right for /home and
    /chores and wrong for every custom board — so on a board the emoji font,
    the panel profile, both SSE streams, the moments hearth and Leaflet
    itself all asked for `/board/api/...` and `/board/static/...` and 404'd,
    each failing quietly in its own way. v2.207.0 fixed this once in
    home.html's head and wrote down the rule; the rule could not hold while
    the formula lived in fifty-one copies.

    So: `ha_theme.html` computes `window.chfBase` in the first script of
    every page's head, and SHARED COMPONENTS read it. Page templates may
    still work out their own — they know their own depth, and are only ever
    served at it — but a component is included by pages at several depths
    and by the board, so it cannot know.
    """
    import re as _re
    NAIVE = _re.compile(r"endsWith\('/'\)\s*\?\s*'\.\./'\s*:\s*''")
    theme = open(os.path.join(TPL, 'ha_theme.html'), encoding='utf-8').read()
    check('window.chfBase' in theme,
          "ha_theme.html no longer defines window.chfBase — every shared "
          "component that reads it now computes an empty base")
    check('board' in theme[theme.index('window.chfBase'):][:600],
          "window.chfBase stopped counting the /board/{slug} level, which is "
          "the entire reason it exists")
    # The set is computed from what is actually INCLUDED, not from what lives
    # in components/. That distinction is not pedantry: `nav.html` sits at the
    # top level, is included by every page in the app, and was therefore the
    # one file this rule most needed to cover — it kept `api/panel/profile`
    # and `api/stream` pointed at /board/... for a whole release after the
    # components were converted, because the first version of this test
    # globbed a directory instead of asking who gets included.
    included = set(_re.findall(r"\{%[-\s]*include\s+'([^']+)'", ''.join(
        open(p, encoding='utf-8').read()
        for p in glob.glob(os.path.join(TPL, '**', '*.html'), recursive=True))))
    check(any(f == 'nav.html' for f in included),
          "nav.html is no longer included anywhere — if the layout changed, "
          "this test's reach changed with it and needs rechecking")
    offenders = []
    for rel in sorted(included):
        path = os.path.join(TPL, rel.replace('/', os.sep))
        if rel == 'ha_theme.html' or not os.path.exists(path):
            continue          # the one file that DEFINES the climb
        if NAIVE.search(open(path, encoding='utf-8').read()):
            offenders.append(rel)
    check(not offenders,
          "included templates computing their own path depth — they are "
          "included at several depths AND on /board/{slug}, so they must "
          "read window.chfBase instead:\n  " + "\n  ".join(offenders))


def scenario_x_show_does_not_guard_x_text_on_the_same_element():
    """The blank-page family's newest member, and its third sighting.

    `x-show` only toggles DISPLAY — the sibling `x-text` still evaluates, on
    every render, whether or not the element is visible. So this:

        <span x-show="pairFound && pairFound.context"
              x-text="'(from ' + pairFound.context.from + ')'">

    throws `Cannot read properties of null` continuously while `pairFound` is
    null, which is its resting state — and ONE Alpine expression error takes
    the whole component's bindings down with it, which is how a config tab
    renders as nothing. config.html already documents this trap on its HA
    status line; it was reintroduced on the pairing box regardless, which is
    what makes it a test rather than a fix.

    The rule: if an element's `x-show` has to test a root for existence
    before dereferencing it, its own `x-text` must carry the same guard.
    """
    import re as _re
    TAG = _re.compile(r'<[a-zA-Z][^>]*x-(?:show|text)=[^>]*>', _re.S)
    broken = []
    for path in sorted(glob.glob(os.path.join(TPL, '**', '*.html'), recursive=True)):
        name = os.path.relpath(path, TPL)
        src = open(path, encoding='utf-8').read()
        for tag in TAG.findall(src):
            show = _re.search(r'x-show="([^"]*)"', tag)
            text = _re.search(r'x-text="([^"]*)"', tag)
            if not show or not text:
                continue
            show_expr, text_expr = show.group(1), text.group(1)
            # Only the shape that actually bites: x-show guarding a root
            # (`foo && foo.bar`) whose sub-property x-text then reads.
            for root in set(_re.findall(r'([A-Za-z_$][\w$]*)\s*&&', show_expr)):
                if not _re.search(_re.escape(root) + r'\s*\.\s*\w+\s*\.', text_expr):
                    continue          # not dereferencing two levels deep
                # A guard of its own — a ternary or its own && chain — is
                # exactly the fix, so an expression carrying one is fine.
                if '?' in text_expr or '&&' in text_expr:
                    continue
                broken.append(f"{name}: x-show guards `{root}` but x-text "
                              f"dereferences it unguarded — {text_expr[:60]}")
    check(not broken,
          "x-show does not stop x-text evaluating, so these throw whenever "
          "the guarded value is null — and one Alpine error blanks the whole "
          "component:\n  " + "\n  ".join(broken))


def scenario_a_page_carrying_alpine_components_loads_alpine():
    """The sixth member of the blank-page family, S8's edition.

    Every page includes nav, nav includes the pairing overlay, and the
    overlay is an Alpine component — but seven pages loaded no Alpine, so on
    them `chfRequestPairing` was never defined and a refused kiosk could
    never draw its pairing code. Worse: the S4 sign-in gate on the dashboard
    was INERT from the day it shipped for the same reason, so at the flip the
    dashboard would have 401'd forever with no way to sign in.

    The rule, checked on the ASSEMBLED page because the component and the
    script tag live in different files: markup that binds `x-data` needs
    Alpine loaded, full stop.
    """
    import tpl_source
    broken = []
    for path in sorted(glob.glob(os.path.join(TPL, '*.html'))):
        name = os.path.basename(path)
        try:
            full = tpl_source.read(name)
        except Exception:
            full = open(path, encoding='utf-8').read()
        if 'x-data=' in full and 'alpine.min.js' not in full:
            broken.append(name)
    check(not broken,
          "pages carrying Alpine components with no Alpine to run them — "
          "every such component renders as nothing (a refused screen cannot "
          "even show its pairing code):\n  " + "\n  ".join(broken))


def scenario_a_stream_carries_the_token_on_its_query_string():
    """Auth arc S8. The fetch wrappers attach the token as a header — but
    EventSource can set no headers at all, so an SSE connection opened with a
    bare URL is ANONYMOUS, forever, no matter who is signed in on the page.
    Dark today; at the flip every such stream dies with a 401 and the page
    quietly stops updating, which is the worst kind of breakage: everything
    still draws, nothing moves.

    So every `new EventSource(` in every template must run its URL through
    `chfAuthUrl` (nav.html and app.html each carry one), which puts
    member_token/device_token on the query string — the one place identify()
    can read it for this class of caller. Checked loosely (the helper within
    shouting distance of the constructor) so a URL built a line earlier still
    counts.
    """
    import re as _re
    broken = []
    for path in sorted(glob.glob(os.path.join(TPL, '**', '*.html'), recursive=True)):
        name = os.path.relpath(path, TPL)
        src = open(path, encoding='utf-8').read()
        for m in _re.finditer(r'new EventSource\(', src):
            span = src[max(0, m.start() - 500):m.end() + 200]
            if 'chfAuthUrl' not in span:
                broken.append(f"{name} at offset {m.start()}")
    check(not broken,
          "EventSource opened without chfAuthUrl — the stream is anonymous "
          "and dies at the S8 flip:\n  " + "\n  ".join(broken))
    # The two headerless channels in music_logic.js, pinned the same way: the
    # artwork proxy is an <img src> and the screen player is a WebSocket.
    ml = open(os.path.join(os.path.dirname(TPL), 'static', 'music_logic.js'),
              encoding='utf-8').read()
    check("authUrl(base(opts) + 'api/ha/image64/'" in ml,
          "the artwork proxy url no longer carries the token — panel covers "
          "404 at the flip")
    check("authUrl(base(opts) + 'api/sendspin/ws')" in ml,
          "the screen-player WebSocket no longer carries the token — no panel "
          "can be a Music Assistant player after the flip")


def scenario_every_script_and_stylesheet_carries_a_version():
    """The fourth blank-page failure, and the one that outlives a deploy.

    A wall panel that has been up for a week runs the JavaScript it cached the
    day it booted. Nothing under /static carried a version, so a shipped change
    to `music_logic.js` reached the household as `MusicLogic.deviceId is not a
    function` — this week's page calling into last week's module, with the fix
    already on the box and nothing on the server to show for it.

    `|ver` stamps mtime+size, so an asset re-downloads exactly when it changes
    and a release does not re-pull mapbox and the fonts onto every panel.
    """
    import re as _re
    # The WHOLE attribute value, so the `|ver` that follows the extension is
    # inside what gets inspected rather than trimmed off by the pattern.
    ref = _re.compile(r'(?:src|href)="([^"]*static/[^"]*\.(?:js|css)[^"]*)"')
    bare = []
    for path in sorted(glob.glob(os.path.join(TPL, '**', '*.html'), recursive=True)):
        src = open(path, encoding='utf-8').read()
        for url in ref.findall(src):
            if '|ver }}' not in url:
                bare.append(f"{os.path.relpath(path, TPL)}: {url}")
    check(not bare,
          "static assets served with no version — a panel keeps the cached "
          "copy across a deploy and the page calls into code that is no "
          "longer there:\n  " + "\n  ".join(bare))
    # The filter has to exist, or every one of those references renders as a
    # Jinja error and takes the whole page with it.
    src = open(os.path.join(os.path.dirname(TPL), 'main.py'), encoding='utf-8').read()
    check("templates.env.filters['ver']" in src,
          "templates call |ver but nothing registers the filter")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} template-js scenarios passed")

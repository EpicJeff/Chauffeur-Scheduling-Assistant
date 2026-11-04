"""Shared helpers for the node tests that RUN the adult PWA's pure functions.

Lifted from tests/test_pwa_sky.py (slice 0) so the slice 1 tests
(test_pwa_next_thing.py, test_pwa_brief_sentence.py, test_pwa_needs_you.py)
extract and run functions the same way:

- a static file keeps every top-level statement at column 0 and indents
  everything inside one, so a top-level chunk runs from one column-0 line to
  the next;
- each chunk is named by what it declares (`function X`, `const/let/var X =`)
  or what it hangs a property on (`X.y = ...`, `Object.assign(X, ...)`);
- `pure_source` takes the named functions plus the transitive closure of the
  top-level names they reference, so a helper or table the builder factors
  out comes along, and nothing that touches the page does;
- `run_node` runs the script with NO `document` and NO `window` and returns
  the last stdout line parsed as JSON, or None when node is not installed.

A function the file does not define FAILS (AssertionError), never skips.
Not a test file itself: it has no scenarios and no __main__ runner.
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
TEMPLATES = os.path.join(ROOT, 'templates')

_IDENT = r'[A-Za-z_$][\w$]*'


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def read(*parts):
    return open(os.path.join(*parts), encoding='utf-8').read()


def chunks(src):
    out, cur = [], []
    for line in src.split('\n'):
        starts = bool(line) and not line[0].isspace() and line[0] not in '})]'
        if starts and cur:
            out.append('\n'.join(cur))
            cur = []
        cur.append(line)
    if cur:
        out.append('\n'.join(cur))
    return out


def chunk_names(chunk):
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


def pure_source(filename, wanted):
    """The top-level chunks of static/<filename> that define `wanted` and
    everything they reference at top level. Fails, naming the first missing
    function, when the file is absent or does not define one of them."""
    path = os.path.join(STATIC, filename)
    check(os.path.exists(path),
          f"static/{filename} defines no {wanted[0]}: static/{filename} does not exist yet")
    src = read(path)
    parsed = [(c, chunk_names(c)) for c in chunks(src)]
    defined = set().union(*(names for _, names in parsed)) if parsed else set()
    for name in wanted:
        check(name in defined, f"static/{filename} defines no {name}")
    want, grew = set(wanted), True
    while grew:
        grew = False
        for chunk, names in parsed:
            if names & want:
                for name in defined - want:
                    if re.search(r'(?<![\w$.])' + re.escape(name) + r'(?![\w$])', chunk):
                        want.add(name)
                        grew = True
    return '\n'.join(chunk for chunk, names in parsed if names & want)


def clock_source():
    """The shared clock (static/pwa_clock.js: pwaClock, pwaClockSuffix) as a
    node prefix for the tests of the files that call it, or '' while the
    file does not exist yet, so those tests keep failing on their own
    expectations rather than on a missing module."""
    if not os.path.exists(os.path.join(STATIC, 'pwa_clock.js')):
        return ''
    return pure_source('pwa_clock.js', ['pwaClock', 'pwaClockSuffix', 'pwaNumberWord', 'pwaLocalDay', 'pwaWeekday']) + '\n'


def run_node(script):
    node = shutil.which('node')
    if not node:
        return None
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False,
                                     encoding='utf-8') as f:
        f.write(script)
        path = f.name
    try:
        res = subprocess.run([node, path], capture_output=True, text=True,
                             encoding='utf-8', timeout=30)
    finally:
        os.unlink(path)
    check(res.returncode == 0, f"node failed:\n{res.stderr[-1500:]}")
    return json.loads(res.stdout.strip().splitlines()[-1])


def function_body(src, name):
    """The text of one function declaration, from `function NAME(` to its
    matching closing brace. Braces inside strings, template literals and
    comments are skipped well enough for this codebase's builders; `${`
    inside a template literal opens a nested expression that is scanned as
    code until its own `}`."""
    m = re.search(r'(?m)^[ \t]*(?:async\s+)?function\s+' + re.escape(name) + r'\s*\(', src)
    check(m, f"{name}() must exist")
    i = _params_end(src, m.end() - 1)
    stack = ['{']           # code braces and template-literal frames
    i += 1
    n = len(src)
    while i < n and stack:
        c = src[i]
        top = stack[-1]
        if top == '`':
            if c == '\\':
                i += 2
                continue
            if c == '`':
                stack.pop()
            elif c == '$' and i + 1 < n and src[i + 1] == '{':
                stack.append('${')
                i += 1
            i += 1
            continue
        # code context
        if c in '\'"':
            j = i + 1
            while j < n and src[j] != c and src[j] != '\n':
                j += 2 if src[j] == '\\' else 1
            i = j + 1
            continue
        if c == '/' and i + 1 < n and src[i + 1] == '/':
            j = src.find('\n', i)
            i = n if j < 0 else j
            continue
        if c == '/' and i + 1 < n and src[i + 1] == '*':
            j = src.find('*/', i + 2)
            i = n if j < 0 else j + 2
            continue
        if c == '/' and _regex_can_start(src, i):
            j, in_class = i + 1, False
            while j < n and src[j] != '\n':
                if src[j] == '\\':
                    j += 2
                    continue
                if src[j] == '[':
                    in_class = True
                elif src[j] == ']':
                    in_class = False
                elif src[j] == '/' and not in_class:
                    break
                j += 1
            i = j + 1
            continue
        if c == '`':
            stack.append('`')
        elif c == '{':
            stack.append('{')
        elif c == '}':
            stack.pop()
        i += 1
    check(not stack, f"{name}() has no matching closing brace")
    return src[m.start():i]


def _regex_can_start(src, i):
    """A `/` at i opens a regex literal when the previous non-space
    character cannot end an operand."""
    j = i - 1
    while j >= 0 and src[j] in ' \t\r\n':
        j -= 1
    return j < 0 or src[j] in '(,=:[!&|?{};+-*%<>~^'


def _params_end(src, open_paren):
    """Index of the `{` that opens the body, after the parameter list that
    starts at `open_paren` (default values may hold parens and strings)."""
    depth, i, n = 0, open_paren, len(src)
    while i < n:
        c = src[i]
        if c in '\'"`':
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == '\\' else 1
            i = j + 1
            continue
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return src.index('{', i)
        i += 1
    raise AssertionError("unterminated parameter list")

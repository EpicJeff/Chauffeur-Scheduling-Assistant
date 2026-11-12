"""Every module the 3D house and its editor import is versioned in the page's import map.

A module missing from the map loads by its bare URL, so a browser that cached the
old copy keeps it after an update. When that stale copy lacks an export the new
code imports, the whole page fails to load ("The house preview could not load.",
v2.499.795: twin_roof.js and twin_ground.js were missing). Clean test browsers
never see it, so this walks the real import graph from each page's entry modules
and checks every module against the map the template writes.

Run: python tests/test_twin_import_maps.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATIC = os.path.join(ROOT, 'static')
IMPORT = re.compile(r"""(?:\bfrom\s*|\bimport\s*\(\s*|\bimport\s+)['"](\.{1,2}/[^'"]+\.js)['"]""")
WORKER = re.compile(r"""new\s+URL\(\s*['"](\.{1,2}/[^'"]+\.js)['"]\s*,\s*import\.meta\.url""")


def graph(entries):
    seen, stack = set(), [os.path.normpath(os.path.join(STATIC, e)) for e in entries]
    while stack:
        path = stack.pop()
        if path in seen:
            continue
        if not os.path.exists(path):
            raise AssertionError(f'an import points at a missing file: {os.path.relpath(path, STATIC)}')
        seen.add(path)
        source = open(path, encoding='utf-8').read()
        for rel in IMPORT.findall(source) + WORKER.findall(source):
            stack.append(os.path.normpath(os.path.join(os.path.dirname(path), rel)))
    return {os.path.relpath(p, STATIC).replace(os.sep, '/') for p in seen}


def mapped(template):
    """Every static/... .js path the template versions: literal entries and for-loops."""
    text = open(os.path.join(ROOT, 'templates', template), encoding='utf-8').read()
    paths = set(re.findall(r"'static/([A-Za-z0-9_./-]+\.js)'\s*\|\s*ver", text))
    for names, prefix in re.findall(
            r"\{%\s*for name in \[([^\]]*)\]\s*%\}.*?\('static/([A-Za-z0-9_./-]*)'\s*~\s*name\s*~\s*'\.js'\)",
            text, re.S):
        for name in re.findall(r"'([^']+)'", names):
            paths.add(f'{prefix}{name}.js')
    return paths


def check_page(template, entries):
    needed = graph(entries)
    have = mapped(template)
    # three and its addons are mapped by bare specifier ('three'), not by path.
    missing = sorted(p for p in needed if p not in have and not p.startswith('vendor/three'))
    assert not missing, f'{template}: modules imported but not versioned in the import map: {missing}'
    return len(needed)


def test_house_twin_page():
    return check_page('house_twin.html', ['twin/twin_view.js'])


def test_house_editor_page():
    text = open(os.path.join(ROOT, 'templates', 'house_editor.html'), encoding='utf-8').read()
    entries = sorted(set(re.findall(r"import\(window\.chfBase \+ \{\{ '(static/twin/[A-Za-z0-9_./-]+\.js)'", text)))
    entries = [e[len('static/'):] for e in entries] or ['twin/editor/editor.js']
    return check_page('house_editor.html', entries + ['twin/editor/editor.js'])


if __name__ == '__main__':
    tests = [test_house_twin_page, test_house_editor_page]
    passed = 0
    for fn in tests:
        try:
            n = fn()
            passed += 1
            print(f'  ok   {fn.__name__} ({n} modules)')
        except AssertionError as exc:
            print(f'  FAIL {fn.__name__}: {exc}')
    print(f'{passed}/{len(tests)} import-map checks passed')
    sys.exit(0 if passed == len(tests) else 1)

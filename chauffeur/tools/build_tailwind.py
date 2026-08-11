"""Compile Tailwind to two static stylesheets, so the browser never has to.

WHY THIS EXISTS

Every page in this app used to load `https://cdn.tailwindcss.com`. That URL is
not a stylesheet — it is Tailwind's COMPILER, ~400 KB of JavaScript that builds
the CSS in the browser on page load and then installs a document-wide
MutationObserver so it can rebuild whenever a class attribute changes. Alpine
changes class attributes constantly.

On a laptop you never notice. On the Raspberry Pi 5 running the wall panel you
notice a great deal, because the panel shelf is made of ordinary links: every
tap is a full page load that re-downloads the compiler, re-compiles the
stylesheet against a 90-340 KB document, and then keeps paying for the observer
for as long as you stay on the page. Tailwind's own docs say the Play CDN is
not for production. It had been in production here for the life of the project.

WHAT IT WRITES

    static/tailwind.css      every page except the driver app
    static/tailwind-app.css  templates/app.html (the theme-token palette)

Two files because the driver app's palette is `rgb(var(--c-*) / <alpha-value>)`
pointing into theme.css, and a page that does not load theme.css would render
every colour as an unresolved variable. See tools/tailwind/*.config.js.

THE STALENESS PROBLEM, AND THE GUARD

A precompiled stylesheet only contains the classes that existed when it was
built. Add `rounded-3xl` to a template, forget to rebuild, and it silently does
nothing — the worst kind of bug, because the page still renders. So each output
carries a hash of everything it was built from:

    /* chauffeur-tailwind-content-hash: <sha256> */

and tests/test_tailwind_build.py recomputes that hash from the templates on
disk and fails if it has moved. A forgotten rebuild is then a red test, not a
missing style on the kitchen wall.

    RUN THIS whenever you change a class in a template:
        cd chauffeur && python tools/build_tailwind.py
"""
import hashlib
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)          # chauffeur/
TPL = os.path.join(ROOT, 'templates')
STATIC = os.path.join(ROOT, 'static')
CONF = os.path.join(HERE, 'tailwind')

# Pinned. An unpinned `tailwindcss@3` would let a patch release change the
# committed CSS under a hash that says nothing moved.
TAILWIND = 'tailwindcss@3.4.17'

HASH_PREFIX = '/* chauffeur-tailwind-content-hash: '

BUILDS = [
    ('tailwind.base.config.js', 'tailwind.css'),
    ('tailwind.app.config.js', 'tailwind-app.css'),
]


def content_hash():
    """Everything a build's output depends on, in a stable order.

    The templates (what gets scanned), the configs and the input stylesheet
    (how it gets scanned), and the pinned Tailwind version (what does the
    scanning). Miss any one of those and the guard passes over a real change.
    """
    h = hashlib.sha256()
    h.update(TAILWIND.encode('utf-8'))
    paths = []
    for base, _, files in os.walk(TPL):
        for f in files:
            if f.endswith('.html'):
                paths.append(os.path.join(base, f))
    for f in ('input.css', 'tailwind.base.config.js', 'tailwind.app.config.js'):
        paths.append(os.path.join(CONF, f))
    for path in sorted(paths, key=lambda p: os.path.relpath(p, ROOT).replace('\\', '/')):
        h.update(os.path.relpath(path, ROOT).replace('\\', '/').encode('utf-8'))
        with open(path, 'rb') as fh:
            # Line endings normalised, and separators too. This repo has
            # `* text=auto` with core.autocrlf on, so the same commit is CRLF
            # in a Windows working tree and LF in the add-on's Linux container.
            # Hash the bytes as committed or a fresh checkout fails the
            # staleness guard for a change nobody made.
            h.update(fh.read().replace(b'\r\n', b'\n'))
    return h.hexdigest()


def stamped_hash(css_path):
    """The hash a built stylesheet claims, or None if it carries no stamp."""
    try:
        with open(css_path, encoding='utf-8') as f:
            first = f.readline()
    except OSError:
        return None
    if not first.startswith(HASH_PREFIX):
        return None
    return first[len(HASH_PREFIX):].split(' ')[0].strip()


def main():
    npx = shutil.which('npx') or shutil.which('npx.cmd')
    if not npx:
        print('npx not found. Install Node (https://nodejs.org) and re-run.',
              file=sys.stderr)
        return 1

    digest = content_hash()
    for config, out_name in BUILDS:
        out = os.path.join(STATIC, out_name)
        print(f'building {out_name} ...')
        # `--cwd` is not a Tailwind flag; the content globs in the configs are
        # relative to the process cwd, so it has to be chauffeur/.
        proc = subprocess.run(
            [npx, '--yes', TAILWIND,
             '--config', os.path.join(CONF, config),
             '--input', os.path.join(CONF, 'input.css'),
             '--output', out,
             '--minify'],
            cwd=ROOT, capture_output=True, text=True)
        if proc.returncode != 0:
            sys.stderr.write(proc.stdout + proc.stderr)
            return proc.returncode

        with open(out, encoding='utf-8') as f:
            css = f.read()
        # Stamped AFTER minification: cssnano is allowed to drop comments, and
        # a guard that the minifier can delete is not a guard.
        with open(out, 'w', encoding='utf-8', newline='\n') as f:
            f.write(f'{HASH_PREFIX}{digest} */\n{css}')
        print(f'  {out_name:<20} {len(css) / 1024:8.1f} KB')

    print(f'\ncontent hash {digest[:16]}...')
    return 0


if __name__ == '__main__':
    sys.exit(main())

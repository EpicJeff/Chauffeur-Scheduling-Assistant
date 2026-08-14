"""Run the test suite without waiting twelve minutes for it.

The suite is 97 standalone scripts and it took **712 seconds** run one after
another, which is long enough that the habit becomes "skip it and see". Run
concurrently it takes **79 seconds** on twelve cores, for exactly the same
coverage — the files are independent processes and each one already isolates
itself with its own `mkdtemp` data dir, so there was never a reason to queue
them.

So the answer is mostly just: stop running them in a line.

    python tools/test.py                 every test, in parallel   (~80s)
    python tools/test.py --focus         only what your changes touch (~5-20s)
    python tools/test.py board card      only tests matching those words
    python tools/test.py --slow          full run, plus the timing table

`--focus` reads `git diff` and picks the tests that mention what changed. It is
a way to get an answer in seconds while you are still working, NOT a substitute
for the full run — it says so, every time, because a selection heuristic is
only ever a guess about what a change can reach. Run the whole thing before you
commit; it costs a minute and change.
"""
import glob
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(HERE, 'tests')


def all_tests():
    return sorted(glob.glob(os.path.join(TESTS, 'test_*.py')))


def changed_files():
    """What git says you have touched — staged, unstaged and untracked."""
    out = set()
    for cmd in (['git', 'diff', '--name-only'],
                ['git', 'diff', '--cached', '--name-only'],
                ['git', 'ls-files', '--others', '--exclude-standard']):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               cwd=os.path.dirname(HERE))
            out.update(x for x in r.stdout.split('\n') if x.strip())
        except OSError:
            pass
    return sorted(out)


def _tokens(path):
    """The words a test would use to talk about this file.

    `services/home_board.py` -> {'home_board', 'home', 'board'}. Derived from
    the path rather than looked up in a table, because a hand-maintained map of
    file->tests is a map that goes stale silently, and a stale map does not
    fail — it just quietly stops running something.
    """
    stem = os.path.basename(path)
    stem = re.sub(r'\.(py|html|json|css|yaml)$', '', stem)
    parts = {stem} | set(p for p in stem.split('_') if len(p) > 3)
    return {p.lower() for p in parts}


def focused(changed):
    """Tests that mention what changed, by name or in their source."""
    picked, why = set(), {}
    tests = all_tests()
    for path in changed:
        rel = path.replace('\\', '/')
        # A changed test runs itself, obviously.
        if '/tests/test_' in rel:
            f = os.path.join(TESTS, os.path.basename(rel))
            if os.path.exists(f):
                picked.add(f)
                why.setdefault(f, set()).add('changed')
            continue
        toks = _tokens(rel)
        needle = os.path.basename(rel)
        for t in tests:
            name = os.path.basename(t)[5:-3].lower()   # test_<this>.py
            hit = None
            if toks & ({name} | set(name.split('_'))):
                hit = 'name'
            else:
                try:
                    with open(t, encoding='utf-8') as fh:
                        src = fh.read()
                except OSError:
                    continue
                # The bare stem, on a word boundary — which is how a test
                # actually refers to a module: `from services import solver`,
                # `solver.solve(...)`. Matching only quoted strings missed
                # every import in the file and quietly returned NOTHING for
                # changes to core modules, which is the worst answer a
                # selector can give.
                stem = re.sub(r'\.(py|html|json|css|yaml)$', '',
                              os.path.basename(rel))
                if needle in src or re.search(rf'\b{re.escape(stem)}\b', src):
                    hit = 'mentions'
            if hit:
                picked.add(t)
                why.setdefault(t, set()).add(f'{hit}:{os.path.basename(rel)}')
    return sorted(picked), why


def run(files, show_slow=False):
    def one(f):
        t0 = time.time()
        p = subprocess.run([sys.executable, f], capture_output=True, text=True,
                           cwd=HERE)
        return f, time.time() - t0, p.returncode, (p.stdout + p.stderr)

    t0 = time.time()
    workers = max(2, (os.cpu_count() or 4))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        rows = list(ex.map(one, files))
    wall = time.time() - t0

    bad = [r for r in rows if r[2] != 0]
    for f, secs, rc, out in sorted(bad, key=lambda r: r[0]):
        print(f'\n{"=" * 70}\nFAIL  {os.path.basename(f)}  ({secs:.0f}s)')
        tail = [ln for ln in out.rstrip().split('\n') if ln.strip()][-12:]
        print('\n'.join('    ' + ln for ln in tail))

    if show_slow:
        print(f'\n{"=" * 70}\nslowest:')
        for f, secs, rc, _ in sorted(rows, key=lambda r: -r[1])[:15]:
            print(f'  {secs:6.1f}s  {os.path.basename(f)}')

    serial = sum(r[1] for r in rows)
    print(f'\n{len(files) - len(bad)}/{len(files)} files passed in {wall:.0f}s '
          f'({serial:.0f}s of work across {workers} workers)')
    return 1 if bad else 0


def main(argv):
    args = [a for a in argv if not a.startswith('-')]
    flags = {a for a in argv if a.startswith('-')}

    if '--focus' in flags:
        changed = changed_files()
        files, why = focused(changed)
        if not files:
            print('nothing changed that maps to a test — run the full sweep')
            return 0
        print(f'{len(changed)} changed file(s) -> {len(files)} test file(s):')
        for f in files:
            print(f'  {os.path.basename(f):<38} {sorted(why[f])[0]}')
        rc = run(files, '--slow' in flags)
        print(f'\n  ^ this is {len(files)} of {len(all_tests())} files. A '
              f'selection heuristic is a guess about what a change can reach;\n'
              f'    run `python tools/test.py` before you commit.')
        return rc

    files = all_tests()
    if args:
        files = [f for f in files if any(a.lower() in os.path.basename(f).lower()
                                         for a in args)]
        if not files:
            print(f'no test files match {args}')
            return 1
    return run(files, '--slow' in flags)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

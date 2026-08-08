"""The Drives timeline is ONE renderer, shared by the page and the wall board.

`renderSchedule` lived in dashboard.html. The board's drives tile drew a
smaller timeline of its own for one version and the family's report was the
obvious one — *"does not look quite the same as the actual page: timeline is
different, event chips are different"*. So it moved to
`components/schedule_timeline.html` and both surfaces call it.

Moving a function that size between templates has two failure modes, and both
are silent until a browser opens the page:

1. **A duplicate declaration takes the WHOLE page down.** The component
   declares the state the timeline draws from (`currentData`, the edge maps,
   `isReadOnly`). Classic scripts share one global scope, so a `let` left
   behind in dashboard.html is a SyntaxError that aborts that entire script —
   no schedule, no buttons, nothing. Jinja renders it happily.
2. **The board tile fetching `/api/schedule`.** That endpoint SAVES a combined
   range cache and kicks a background refresh; a wall panel polling it every
   minute would keep the solver warm forever for a display nobody is looking
   at. The tile is fed from the board payload instead — rule 3 of the home
   board, in the one place it is easiest to break.

Run from chauffeur/:  python tests/test_schedule_timeline.py
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'templates')

# Everything the component now declares at page scope. A second declaration of
# any of these on the same page is fatal.
OWNED = ['isKiosk', 'isReadOnly', 'currentData', 'currentEventsMap',
         'currentStartDate', 'currentEndDate', 'initialEdges', 'finalEdges',
         'localSolvingDates']

# The pages that include it. Both draw the same timeline; nothing else should
# have to.
PAGES = ['dashboard.html', 'home.html']


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _render(name):
    """The REAL Jinja environment: nav.html asks the server for the shelf order
    (`shelf_order`, registered as a global in main), and a stand-in would
    render a different page than the app serves."""
    import main
    req = types.SimpleNamespace(url=types.SimpleNamespace(path='/' + name),
                                query_params={})
    return main.templates.env.get_template(name).render(request=req)


def _scripts(html):
    blocks = re.findall(r'<script>(.*?)</script>', html, re.S)
    return '\n;\n'.join(b for b in blocks if 'tailwind' not in b[:80])


def scenario_the_renderer_exists_once_per_page():
    """Two definitions is the thing being fixed. One definition in a file
    nobody includes is the same bug with the other sign."""
    comp = open(os.path.join(TPL, 'components/schedule_timeline.html'),
                encoding='utf-8').read()
    check(comp.count('function renderSchedule(') == 1,
          "the component must define the renderer exactly once")
    for page in PAGES:
        html = _render(page)
        js = _scripts(html)
        check(js.count('function renderSchedule(') == 1,
              f"{page} sees {js.count('function renderSchedule(')} renderers")
        check('components/schedule_timeline.html' in open(
            os.path.join(TPL, page), encoding='utf-8').read(),
            f"{page} draws a timeline without including the shared one")


def scenario_nothing_redeclares_what_the_component_owns():
    """Failure mode 1. A `let` left behind in dashboard.html is a SyntaxError
    that aborts the page's entire script — and Jinja renders it happily, so
    only parsing the result finds it (which the scenario below does).

    This one names the culprit instead: the state belongs to the component, and
    a page that declares it again has taken ownership back. Checked against the
    page TEMPLATES rather than the render, because an unrelated include may
    legitimately use the same name inside a function of its own — nav.html has
    its own `isKiosk` in a DOMContentLoaded handler, and that is fine."""
    comp = open(os.path.join(TPL, 'components/schedule_timeline.html'),
                encoding='utf-8').read()
    for name in OWNED:
        n = len(re.findall(r'(?:const|let|var)\s+' + name + r'\b', comp))
        check(n == 1, f"the component declares `{name}` {n} times")
    for page in PAGES:
        src = open(os.path.join(TPL, page), encoding='utf-8').read()
        for name in OWNED:
            check(not re.search(r'(?:const|let|var)\s+' + name + r'\b', src),
                  f"{page} declares `{name}` again — the component owns it, and "
                  "a second top-level declaration takes the whole page down")


def scenario_every_page_that_includes_it_still_parses():
    """The cheapest possible check on a 1300-line move, and the one that would
    have caught a mangled brace."""
    node = shutil.which('node')
    if not node:
        print("  skip  node not installed — the pages were not parsed")
        return
    for page in PAGES:
        js = _scripts(_render(page))
        path = os.path.join(tempfile.gettempdir(), 'chauffeur_' + page + '.js')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(js)
        proc = subprocess.run([node, '--check', path], capture_output=True, text=True)
        check(proc.returncode == 0, f"{page} no longer parses:\n{proc.stderr[:1500]}")


def scenario_a_caller_can_declare_itself_read_only():
    """The AI options modal has passed `isReadOnly: true` since it was written
    and the option was never destructured — it was read-only only because the
    page it lives on usually is. The board's tile is the first caller for which
    that is not true, and a wall panel must not drag an event onto another
    driver by being leaned against."""
    comp = open(os.path.join(TPL, 'components/schedule_timeline.html'),
                encoding='utf-8').read()
    check('options.isReadOnly !== undefined' in comp,
          "the renderer ignores the caller's read-only flag again")
    body = comp[comp.index('function renderSchedule('):]
    guard = body.index('options.isReadOnly !== undefined')
    check(not re.search(r'(?<![\w$.])isReadOnly(?![\w$])', body[guard + 200:]),
          "a bare `isReadOnly` survives past the guard, so part of the timeline "
          "is still reading the PAGE's flag rather than the caller's")

    home = open(os.path.join(TPL, 'home.html'), encoding='utf-8').read()
    check('isReadOnly: true' in home,
          "the board tile no longer asks for a read-only timeline")


def scenario_the_board_never_asks_the_schedule_endpoint():
    """Failure mode 2. `GET /api/schedule` writes a cache and schedules a
    background refresh; the board is fed from its own payload instead."""
    # A string literal, not the word: the reason it must not happen is written
    # in a comment two lines from the code that would do it.
    fetches = re.compile(r"""['"`]\.?/?api/schedule""")
    home = open(os.path.join(TPL, 'home.html'), encoding='utf-8').read()
    check(not fetches.search(home),
          "the home board fetches the schedule endpoint — which writes a cache "
          "and kicks a background refresh, on a display nobody is looking at")
    comp = open(os.path.join(TPL, 'components/schedule_timeline.html'),
                encoding='utf-8').read()
    check(not fetches.search(comp),
          "the timeline fetches its own data — it is a renderer, and the two "
          "surfaces that use it get their schedule very differently")

    from services import home_board
    src = open(os.path.join(os.path.dirname(TPL), 'services', 'home_board.py'),
               encoding='utf-8').read()
    check('def _schedule_slice(' in src,
          "the slice the timeline draws from has to be built server-side, from "
          "the cache the board already holds")
    check(hasattr(home_board, '_schedule_slice'), "and be importable")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} schedule-timeline scenarios passed")

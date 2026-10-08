"""The settings drawer, rendered (settings-drawer arc, slice 1).

Pages are rendered by calling their route function with a hand-built
Starlette Request — TestClient needs httpx, which is not installed here
(the test_house_facade idiom). A rendered page is what a browser gets, so
these pins see the macro's wall guard and the nav's page bar for real.

Run from chauffeur/:  python tests/test_settings_drawer.py
"""
import asyncio
import inspect
import os
import re
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='settings_drawer_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _render(path, query=''):
    from starlette.requests import Request
    import main
    route = next(r for r in main.app.routes
                 if getattr(r, 'path', None) == path and 'GET' in (getattr(r, 'methods', None) or ()))
    req = Request({'type': 'http', 'method': 'GET', 'path': path,
                   'query_string': query.encode('utf-8'), 'headers': [],
                   'app': main.app, 'router': main.app.router})
    out = route.endpoint(req)
    if inspect.isawaitable(out):
        out = asyncio.run(out)
    return out.body.decode('utf-8')


def scenario_every_admin_page_draws_the_bar():
    """Grouped pages show their tabs; ungrouped ones show their name."""
    for path, key in (('/work', 'mind'), ('/trips', 'trips'), ('/map', 'map'),
                      ('/config', 'config'), ('/settings', 'settings')):
        html = _render(path)
        check('id="page-tabs"' in html, f'{path} draws no page bar')
        check(f'data-bar-key="{key}"' in html, f'{path} bar key is not {key}')
        check('id="page-settings-gear"' in html, f'{path} has no gear button to show')
    check('page-bar-name' in _render('/trips') and '>Trips<' in _render('/trips'),
          'an ungrouped page does not name itself on the bar')


def scenario_walls_get_no_bar_no_gear_no_drawer():
    for path in ('/work', '/trips'):
        for q in ('kiosk=true', 'panel=true', 'tabs=threads'):
            html = _render(path, q)
            check('id="page-tabs"' not in html, f'{path}?{q} draws the page bar')
            check('id="page-settings-gear"' not in html, f'{path}?{q} draws the gear')
            check('data-settings-for' not in html, f'{path}?{q} draws a settings drawer')


def scenario_threads_settings_live_in_a_drawer():
    html = _render('/work', 'tab=threads')
    m = re.search(r'data-settings-for="threads"', html)
    check(m, 'the Threads drawer is missing')
    i = html.index('id="threadStallDays"')
    check(i > m.start(), 'the stall-days input sits outside the Threads drawer')
    check('saveStallDays()' in html, 'the stall-days input lost its save')


def scenario_the_drawer_script_loads_everywhere():
    """The save helpers are called by page code on walls too (they return
    false and the page falls back to its alert), so the script loads even
    where no drawer is drawn."""
    for path, q in (('/work', ''), ('/work', 'kiosk=true'), ('/map', '')):
        check('static/settings_drawer.js' in _render(path, q),
              f'{path}?{q} does not load settings_drawer.js')


def scenario_growing_up_lives_on_config_people():
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates')
    cfg = open(os.path.join(base, 'config.html'), encoding='utf-8').read()
    rh = open(os.path.join(base, 'rhythms.html'), encoding='utf-8').read()
    check("include 'components/growing_up.html'" in cfg, 'Config does not include Growing up')
    check('id="growing-up"' in cfg, 'Config has no #growing-up anchor')
    check('growing_up.html' not in rh, 'Rhythms still carries Growing up')
    from services import settings_registry as reg
    e = reg.BY_KEY['stage_cutoffs']
    check((e['page'], e['anchor']) == ('config', 'growing-up'), f'stage_cutoffs points at {e}')
    # A redirect has no page body, so assert on the response itself.
    import main
    from starlette.requests import Request
    route = next(r for r in main.app.routes if getattr(r, 'path', None) == '/rhythms')
    req = Request({'type': 'http', 'method': 'GET', 'path': '/rhythms',
                   'query_string': b'tab=growing-up', 'headers': [],
                   'app': main.app, 'router': main.app.router})
    resp = route.endpoint(req)
    check(resp.status_code in (302, 303, 307) and resp.headers['location'].endswith('config#growing-up'),
          f'rhythms?tab=growing-up does not forward to Config: {resp.status_code} {resp.headers.get("location")}')


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith('scenario_')]

if __name__ == '__main__':
    for fn in SCENARIOS:
        fn()
        print(f'  ok  {fn.__name__}')
    print(f'\n{len(SCENARIOS)}/{len(SCENARIOS)} settings drawer scenarios passed')

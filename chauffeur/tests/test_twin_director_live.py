"""The art director loop and the parent tools sheet in real Chromium
(spec docs/superpowers/specs/2026-11-06-house-digital-twin-design.md
sections 8.2, 8.4, 8.6; plan Task 8). The critique route is intercepted
in the browser, so no model is called; the page, the view and the store
are real.

Tools sheet DOM contract (house_twin.html):
  #twin-tools-toggle      opens the parent tools sheet
  #twin-run-director      starts a director run (cameras front/porch/rear/top)
  #twin-director-log      the latest critique text and the running cost
  #twin-rounds            the rounds list; each row carries data-round-id and a [data-revert] button
  #twin-plan-editor       textarea holding the current plan JSON
  #twin-plan-reason       the reason field a hand save requires
  #twin-plan-save         saves through PUT api/house/twin/plan

Run from chauffeur/:  python tests/test_twin_director_live.py
"""
import copy
import json
import os
import sys
import tempfile
import time

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_director_live_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from live_app import live_app  # noqa: E402
from test_twin_view_live import GPU_ARGS, _seed  # noqa: E402

SERVED = None
PLAN = {}


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _serve():
    global SERVED
    if SERVED is None:
        SERVED = live_app(lambda: PLAN.setdefault('plan', _seed()))
    return SERVED


def _unexpected(errors):
    return [e for e in errors if not e.startswith('Failed to load resource')]


def _open(page, s):
    page.goto(s.url('house/twin?tier=low'))
    page.wait_for_function('window.__twin && window.__twin.ready === true', timeout=60000)
    page.evaluate('''() => { window.__rebuilds = 0; const r = window.__twin.rebuild.bind(window.__twin);
                             window.__twin.rebuild = (p) => { window.__rebuilds++; return r(p); }; }''')
    page.click('#twin-tools-toggle')


def _plan_with_extra_shrub(n):
    p = copy.deepcopy(PLAN['plan'])
    for i in range(n):
        p['site']['planting'].append({'kind': 'shrub', 'preset': 'Bush 2', 'at': [-3.0, 2.0 + i * 3.5],
                                      'height': 3.5, 'seed': 500 + i})
    return p


def scenario_director_loop_rebuilds_and_stops_when_done():
    s = _serve()
    if s is None:
        return
    posts = []

    def handle(route):
        body = json.loads(route.request.post_data or '{}')
        posts.append(body)
        n = len(posts)
        result = {'round': 100 + n, 'critique': f'Round {n}: layer the rear bed.', 'done': n >= 3,
                  'plan': _plan_with_extra_shrub(n), 'cost': 0.12 * n, 'stale': False, 'notes': []}
        route.fulfill(status=200, content_type='application/json', body=json.dumps({'result': result}))
    with s.browser(launch_args=GPU_ARGS) as page:
        page.route('**/api/house/twin/critique', handle)
        _open(page, s)
        page.click('#twin-run-director')
        page.wait_for_function('() => document.querySelector("#twin-director-log").textContent.includes("Round 3")',
                               timeout=120000)
        time.sleep(1.0)
        check(len(posts) == 3, f'three rounds posted, then it stopped on done: {len(posts)}')
        check(all(set(p.get('cameras', [])) == {'front', 'porch', 'rear', 'top'} and len(p.get('renders', [])) == 4
                  for p in posts), 'each round sends four labelled renders')
        check(all(isinstance(p.get('base'), int) and p.get('run') == posts[0]['run'] for p in posts),
              'one run id, and a base round on every post')
        check(page.evaluate('() => window.__rebuilds') == 3, 'the scene is rebuilt from each round')
        log = page.inner_text('#twin-director-log')
        check('0.36' in log or '$0.36' in log, f'the running cost is shown: {log}')
    check(not _unexpected(s.errors()), s.errors())


def scenario_checkpoint_asks_with_promptconfirm_not_a_browser_dialog():
    s = _serve()
    if s is None:
        return
    posts, acks, dialogs = [], [], []

    def critique(route):
        posts.append(1)
        if len(posts) == 1:
            route.fulfill(status=409, content_type='application/json',
                          body=json.dumps({'detail': {'checkpoint': 10.0, 'total': 10.4, 'run': 'x'}}))
        else:
            result = {'round': 200, 'critique': 'Fine now.', 'done': True, 'plan': PLAN['plan'],
                      'cost': 0.1, 'stale': False, 'notes': []}
            route.fulfill(status=200, content_type='application/json', body=json.dumps({'result': result}))

    def ack(route):
        acks.append(json.loads(route.request.post_data or '{}'))
        route.fulfill(status=200, content_type='application/json', body=json.dumps({'total': 10.4, 'blocking': None}))
    with s.browser(launch_args=GPU_ARGS) as page:
        page.on('dialog', lambda d: (dialogs.append(d.type), d.dismiss()))
        page.route('**/api/house/twin/critique', critique)
        page.route('**/api/house/twin/cost/ack', ack)
        _open(page, s)
        page.click('#twin-run-director')
        page.wait_for_selector('#cc-confirm-modal:not(.hidden)', timeout=60000)
        check('10' in page.inner_text('#cc-confirm-message') or '10' in page.inner_text('#cc-confirm-title'),
              'the confirm names the checkpoint')
        page.click('#cc-confirm-actions button:not(#cc-confirm-cancel-btn)')
        page.wait_for_function('() => document.querySelector("#twin-director-log").textContent.includes("Fine now")',
                               timeout=60000)
        check(acks == [{'checkpoint': 10.0}], acks)
        check(len(posts) == 2, 'the round is retried after the acknowledgement')
        check(dialogs == [], f'no browser dialogs: {dialogs}')


def scenario_stopping_at_a_checkpoint_spends_nothing_more():
    s = _serve()
    if s is None:
        return
    posts, acks = [], []
    with s.browser(launch_args=GPU_ARGS) as page:
        page.route('**/api/house/twin/critique', lambda r: (posts.append(1), r.fulfill(
            status=409, content_type='application/json',
            body=json.dumps({'detail': {'checkpoint': 25.0, 'total': 25.2, 'run': 'y'}}))))
        page.route('**/api/house/twin/cost/ack', lambda r: (acks.append(1), r.fulfill(status=200, body='{}')))
        _open(page, s)
        page.click('#twin-run-director')
        page.wait_for_selector('#cc-confirm-modal:not(.hidden)', timeout=60000)
        page.click('#cc-confirm-cancel-btn')
        time.sleep(1.5)
        check(len(posts) == 1 and acks == [], 'Stop means no acknowledgement and no further round')


def scenario_hand_edit_requires_a_reason_and_logs_fixes():
    s = _serve()
    if s is None:
        return
    puts = []
    with s.browser(launch_args=GPU_ARGS) as page:
        page.on('request', lambda r: r.method == 'PUT' and '/api/house/twin/plan' in r.url and puts.append(r.post_data))
        _open(page, s)
        plan = json.loads(page.input_value('#twin-plan-editor'))
        plan['materials']['trim']['color'] = '#f0f0f0'
        page.fill('#twin-plan-editor', json.dumps(plan))
        page.fill('#twin-plan-reason', '')
        page.click('#twin-plan-save')
        time.sleep(0.8)
        check(puts == [], 'no save without a reason')
        check(page.is_visible('#cc-alert-modal'), 'the person is told why (showGlobalAlert)')
        page.evaluate('() => window.closeGlobalAlert && window.closeGlobalAlert()')
        page.fill('#twin-plan-reason', 'trim is a warmer white')
        page.click('#twin-plan-save')
        page.wait_for_function('() => document.querySelectorAll("#twin-rounds [data-round-id]").length >= 2', timeout=30000)
        body = json.loads(puts[-1])
        check(body['reason'] == 'trim is a warmer white' and isinstance(body.get('base'), int), body.keys())
    from services import twin_store
    fixes = twin_store.fixes()
    check(any(f['path'] == 'materials.trim.color' and f['reason'] == 'trim is a warmer white' for f in fixes), fixes)


def scenario_revert_from_the_rounds_list():
    s = _serve()
    if s is None:
        return
    from services import twin_store
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        first = page.get_attribute('#twin-rounds [data-round-id]', 'data-round-id')
        page.click(f'#twin-rounds [data-round-id="{first}"] [data-revert]')
        page.wait_for_function(
            '() => [...document.querySelectorAll("#twin-rounds [data-round-id]")].some(r => /revert/i.test(r.textContent))',
            timeout=30000)
    check(twin_store.rounds()[-1]['kind'] == 'revert', twin_store.rounds()[-1])


if __name__ == '__main__':
    for fn in (scenario_director_loop_rebuilds_and_stops_when_done,
               scenario_checkpoint_asks_with_promptconfirm_not_a_browser_dialog,
               scenario_stopping_at_a_checkpoint_spends_nothing_more,
               scenario_hand_edit_requires_a_reason_and_logs_fixes,
               scenario_revert_from_the_rounds_list):
        fn()
        print('  ok ', fn.__name__)

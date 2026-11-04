"""The server's household to-do list reaches the adult phone (PWA reimagined
slice 3, Task 3), and threads move their host from Household to Plan's Family
pane.

Route half: real app through TestClient with enforcement ON, a member token per
role. /api/household-tasks/* is SIGNED_IN under facet lists.household_tasks
(services/auth.py). A parent and a household adult list, add and complete (the
row leaves the open list); a helper and a keeping_up adult (preset has the
facet NONE) get 403 on GET. These pass today: the routes exist.

Source half (must FAIL until the phone builds it), on templates/app.html:
  * fetchHouseholdTasks reads api/household-tasks;
  * completeHouseholdTask POSTs .../complete;
  * addHouseholdTask POSTs api/household-tasks;
  * paneSectionsHtml emits id="house-threads" after id="mind-container", and
    the Household container (#chores-container) no longer holds it.

Not harness.check: this file patches storage.get_settings per call.

Run from chauffeur/ (HA_BASE_URL unset):  python tests/test_household_tasks_phone.py
"""
import atexit
import datetime
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'chauffeur'))
sys.path.insert(0, str(ROOT / 'chauffeur' / 'tests'))
DATA = tempfile.mkdtemp(prefix='chauffeur_household_tasks_phone_')
os.environ['CHAUFFEUR_DATA_DIR'] = DATA
os.environ.pop('HA_BASE_URL', None)
atexit.register(lambda: shutil.rmtree(DATA, ignore_errors=True))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from services import storage  # noqa: E402

client = TestClient(main.app)
APP_HTML = (ROOT / 'chauffeur' / 'templates' / 'app.html').read_text(encoding='utf-8')
TUNNEL = {'cf-connecting-ip': '203.0.113.7'}
ENFORCED = {'auth_enforce': True, 'service_local_grace': False}
TODAY = datetime.date.today().isoformat()
_TOKENS = {}


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _token(member_id, role, scope=None):
    if member_id not in _TOKENS:
        row = {'id': member_id, 'name': member_id.title(), 'role': role}
        if scope:
            row['scope'] = scope
        storage.add_member(row)
        _TOKENS[member_id] = storage.create_member_token(member_id)
    return _TOKENS[member_id]


def _call(method, path, token, **kw):
    with mock.patch('services.storage.get_settings', return_value=ENFORCED):
        return client.request(method, path, headers={**TUNNEL, 'X-Member-Token': token}, **kw)


def _round_trip(token, title):
    r = _call('GET', '/api/household-tasks', token)
    check(r.status_code == 200, f"{title}: list refused {r.status_code} {r.text[:200]}")
    check(isinstance(r.json(), list), f"{title}: list is not an array: {r.text[:200]}")
    r = _call('POST', '/api/household-tasks', token, json={'title': title, 'due_date': TODAY})
    check(r.status_code == 200, f"{title}: add refused {r.status_code} {r.text[:200]}")
    tid = r.json().get('id')
    check(tid, f"{title}: add returned no id: {r.text[:200]}")
    rows = _call('GET', '/api/household-tasks', token).json()
    mine = [t for t in rows if t['id'] == tid]
    check(len(mine) == 1 and mine[0]['title'] == title, f"{title}: the new task is not in the open list: {rows!r}")
    check(mine[0]['due_today'] is True and mine[0]['past_due'] is False,
          f"{title}: due_today/past_due flags wrong: {mine[0]!r}")
    r = _call('POST', f'/api/household-tasks/{tid}/complete', token, json={})
    check(r.status_code == 200, f"{title}: complete refused {r.status_code} {r.text[:200]}")
    rows = _call('GET', '/api/household-tasks', token).json()
    check(all(t['id'] != tid for t in rows), f"{title}: a completed task is still in the open list")


def scenario_parent_lists_adds_completes():
    _round_trip(_token('ht_parent', 'parent'), 'Parent bins')


def scenario_household_adult_lists_adds_completes():
    _round_trip(_token('ht_adult', 'adult'), 'Adult plumber')


def scenario_helper_is_refused():
    tok = _token('ht_helper', 'helper')
    r = _call('GET', '/api/household-tasks', tok)
    check(r.status_code == 403, f"a helper must get 403 on the household list, got {r.status_code} {r.text[:200]}")


def scenario_keeping_up_adult_is_refused():
    tok = _token('ht_keeper', 'adult', scope={'preset': 'keeping_up'})
    r = _call('GET', '/api/household-tasks', tok)
    check(r.status_code == 403,
          f"a keeping_up adult (lists.household_tasks none) must get 403, got {r.status_code} {r.text[:200]}")


def _function_body(name, source=APP_HTML):
    m = re.search(r'(?:async\s+)?function\s+' + re.escape(name) + r'\s*\(', source)
    check(m, f"templates/app.html has no function {name}")
    nxt = re.search(r'\n\s{8}(?:async\s+)?function\s+\w+\s*\(', source[m.end():])
    return source[m.start(): m.end() + (nxt.start() if nxt else 6000)]


def scenario_phone_fetches_household_tasks():
    body = _function_body('fetchHouseholdTasks')
    check(re.search(r'api/household-tasks', body), "fetchHouseholdTasks does not read api/household-tasks")
    done = _function_body('completeHouseholdTask')
    check(re.search(r'api/household-tasks/[^\n]*/complete|household-tasks/[\'"`]?\s*\+[^\n]*complete|/complete', done)
          and re.search(r'POST', done),
          "completeHouseholdTask does not POST to .../complete")
    add = _function_body('addHouseholdTask')
    check(re.search(r'api/household-tasks', add) and re.search(r'POST', add),
          "addHouseholdTask does not POST to api/household-tasks")
    check('householdTasksData' in APP_HTML and 'renderHouseholdTasks' in APP_HTML,
          "householdTasksData / renderHouseholdTasks are not defined in app.html")


def scenario_family_pane_hosts_house_threads():
    body = _function_body('paneSectionsHtml')
    mind = body.find('id="mind-container"')
    threads = body.find('id="house-threads"')
    check(mind >= 0, "paneSectionsHtml lost id=\"mind-container\"")
    check(threads >= 0, "paneSectionsHtml does not emit id=\"house-threads\" (threads still live on the Household tab)")
    check(threads > mind, "id=\"house-threads\" must come AFTER id=\"mind-container\" in the Family pane")
    start = APP_HTML.index('<div id="chores-container"')
    end = APP_HTML.index('{% include \'components/pwa_shell.html\' %}', start)
    check('id="house-threads"' not in APP_HTML[start:end],
          "the Household container (#chores-container) still holds id=\"house-threads\"")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {e}")
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} household tasks phone scenarios passed")
    sys.exit(1 if failed else 0)

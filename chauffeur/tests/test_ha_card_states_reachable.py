"""api/ha/card/states says when it is serving a stale copy (piece 3 of
docs/superpowers/plans/2026-11-10-house-ha-link-piece-3.md; Task 6 review C1;
Ruling Q13 in .superpowers/sdd/2026-11-10-house-ha-link-piece-3/progress.md).

The defect. ha_api.get_states serves the last cached list when the real
GET /states fails ("Serves the stale copy if HA is temporarily unreachable").
So once Home Assistant has answered even once since the add-on started,
card/states answers 200 with the OLD, non-empty states when HA goes away, and
the 3D house's markers (static/twin/live/live.js poll) read them as fresh: no
dim, and a tap is sent to a house that is not there.

Ruling Q13: ha_api records whether the last real /states fetch failed;
api/ha/card/states adds `reachable: false` whenever it is serving a stale or
empty copy because the fetch failed. Other callers keep the stale copy.

This file patches ha_api._request (the HTTP call), never get_states, so the
real cache path runs end to end through the real route (TestClient, auth
enforcement ON, as a wall panel: the route's tier is WALL).

What it assumes of the fix:
- The body stays {'states': {...}} and gains 'reachable': False when the last
  real /states fetch failed (warm cache served stale, or cold cache served
  empty). After a successful fetch 'reachable' is True or absent (never False).
- A fresh=0 poll whose cache is older than its ttl makes a real fetch, so it
  reports the same way as fresh=1.
- ha_api.get_states() itself still answers the stale list (the map, the board
  and every other caller keep working through an HA blip).

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_ha_card_states_reachable.py
"""
import os
import sys
import tempfile
import traceback
from unittest.mock import patch

if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_card_states_reachable_')
os.environ.pop('HA_BASE_URL', None)
os.environ.pop('SUPERVISOR_TOKEN', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import ha_api, storage  # noqa: E402

STATES = '/api/ha/card/states'
_real_settings = storage.get_settings


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


class FakeHttp:
    """Stands in for ha_api._request: GET /states answers `rows` while up, None (a failed
    request, exactly what the real _request returns on a timeout or an HTTP error) while down."""

    def __init__(self):
        self.up = True
        self.rows = [{'entity_id': 'light.kitchen', 'state': 'on', 'attributes': {'friendly_name': 'Kitchen'}},
                     {'entity_id': 'lock.back_door', 'state': 'locked', 'attributes': {}}]
        self.fetches = []

    def __call__(self, method, path, json_body=None, params=None, timeout=None):
        self.fetches.append((method, path))
        if not self.up:
            return None
        if method == 'GET' and path == '/states':
            return [dict(row, attributes=dict(row['attributes'])) for row in self.rows]
        return None


class Ctx:
    def __enter__(self):
        from fastapi.testclient import TestClient
        import main
        self.http = FakeHttp()
        self.cache = dict(ha_api._states_cache)
        ha_api._states_cache.update(ts=0.0, data=None)
        self.patches = [patch.object(ha_api, '_request', self.http),
                        patch.object(storage, 'get_settings',
                                     side_effect=lambda: {**_real_settings(), 'auth_enforce': True})]
        for p in self.patches:
            p.start()
        self.panel = {'X-Device-Token': storage.enrol_device_token('panel-states', 'Kitchen panel', by_member=None)}
        self.client = TestClient(main.app)
        return self

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()
        ha_api._states_cache.clear()
        ha_api._states_cache.update(self.cache)

    def states(self, fresh=1):
        r = self.client.get(f'{STATES}?fresh={fresh}', headers=self.panel)
        check(r.status_code == 200, ('card/states answers 200 to a wall panel', r.status_code, r.text[:300]))
        return r.json()

    def age_cache(self, seconds=60):
        """The cached copy is older than any ttl, so the next fresh=0 read makes a real fetch."""
        ha_api._states_cache['ts'] -= seconds


def _fresh(body, why):
    check(body.get('reachable') is not False, (why, 'a successful fetch is not reported unreachable', body))


def _stale(body, why):
    check(body.get('reachable') is False, (why, 'the fetch failed, so the answer must say reachable: false', body))


# ---------------------------------------------------------------- scenarios

def scenario_warm_cache_then_ha_fails_answers_reachable_false_with_stale_states():
    with Ctx() as c:
        body = c.states(fresh=1)
        check(set(body.get('states', {})) == {'light.kitchen', 'lock.back_door'}, ('HA answered', body))
        _fresh(body, 'HA up')
        check(('GET', '/states') in c.http.fetches, ('the real get_states made the fetch', c.http.fetches))

        # Home Assistant stops answering. The real cache still holds the first answer.
        c.http.up = False
        n = len(c.http.fetches)
        body = c.states(fresh=1)
        check(len(c.http.fetches) > n, ('fresh=1 tried Home Assistant again', c.http.fetches[n:]))
        check(body.get('states', {}).get('light.kitchen', {}).get('state') == 'on',
              ('the stale copy is still served (the hosted cards keep what they knew)', body))
        _stale(body, 'warm cache, fresh=1, HA down')

        # The 10 s poll asks fresh=0; once the cached copy is past its ttl it fetches and fails too.
        c.age_cache()
        body = c.states(fresh=0)
        check(body.get('states', {}).get('lock.back_door', {}).get('state') == 'locked',
              ('fresh=0 still serves the stale copy', body))
        _stale(body, 'warm cache, fresh=0 past ttl, HA down')

        # Other callers keep the stale copy (Ruling Q13).
        rows = ha_api.get_states(ttl=0)
        check({r['entity_id'] for r in rows} == {'light.kitchen', 'lock.back_door'},
              ('ha_api.get_states still answers the stale list to every other caller', rows))


def scenario_recovery_answers_reachable_again():
    with Ctx() as c:
        _fresh(c.states(fresh=1), 'HA up')
        c.http.up = False
        _stale(c.states(fresh=1), 'HA down')

        # It comes back with a change: the next real fetch is fresh and says so.
        c.http.up = True
        c.http.rows[0]['state'] = 'off'
        body = c.states(fresh=1)
        check(body.get('states', {}).get('light.kitchen', {}).get('state') == 'off', ('the new answer', body))
        _fresh(body, 'HA back, fresh=1')
        c.age_cache()
        body = c.states(fresh=0)
        _fresh(body, 'HA back, fresh=0 past ttl')

        # Down again, then back again: the flag follows the LAST real fetch, not the first.
        c.http.up = False
        _stale(c.states(fresh=1), 'HA down a second time')
        c.http.up = True
        _fresh(c.states(fresh=1), 'HA back a second time')


def scenario_cold_cache_ha_down_answers_empty_and_unreachable():
    with Ctx() as c:
        c.http.up = False
        body = c.states(fresh=1)
        check(body.get('states') == {}, ('nothing was ever read: empty states', body))
        _stale(body, 'cold cache, HA down')


SCENARIOS = [
    scenario_warm_cache_then_ha_fails_answers_reachable_false_with_stale_states,
    scenario_recovery_answers_reachable_again,
    scenario_cold_cache_ha_down_answers_empty_and_unreachable,
]


if __name__ == '__main__':
    failed = []
    for fn in SCENARIOS:
        try:
            fn()
        except Exception as exc:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, type(exc).__name__, ' '.join(str(exc).split())[:600])
            if not isinstance(exc, AssertionError):
                traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(SCENARIOS) - len(failed)}/{len(SCENARIOS)} passed')
    sys.exit(1 if failed else 0)

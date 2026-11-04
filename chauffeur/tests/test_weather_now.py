"""GET /api/weather/now: the conditions the wall already reads, for the phone.

PWA reimagined slice 1, task 1. My Day's greeting shows the weather right now,
and the wall's home board already reads it (services/home_board.build, the
temp_now / condition / condition_emoji fields). The read is lifted into
`home_board.current_conditions(settings=None)` so the board and the new route
say the same thing, and the route answers `null` when there is no Home
Assistant -- weather is garnish and never an error.

Pinned here, against the real app through TestClient:
  * no weather entity and no HA -> 200 with null;
  * a state with no forecast -> rounded temperature, condition, the digest's
    emoji, line None;
  * a forecast for today -> line is exactly family_digest.weather_line(today);
  * build() still emits the same three fields, now from the helper;
  * the route is WALL tier: a member token and a device token both get 200,
    no token gets 401 once enforcement is on.

Not harness.check: importing harness replaces storage.get_settings with a
fixed dict, and this file patches get_settings itself per scenario.

Run from chauffeur/ (HA_BASE_URL unset):  python tests/test_weather_now.py
"""
import atexit
import datetime
import os
from pathlib import Path
import shutil
import sys
import tempfile
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'chauffeur'))
sys.path.insert(0, str(ROOT / 'chauffeur' / 'tests'))
DATA = tempfile.mkdtemp(prefix='chauffeur_weather_now_')
os.environ['CHAUFFEUR_DATA_DIR'] = DATA
os.environ.pop('HA_BASE_URL', None)
atexit.register(lambda: shutil.rmtree(DATA, ignore_errors=True))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from services import family_digest, home_board, storage  # noqa: E402

client = TestClient(main.app)

ENTITY = 'weather.home'
DEVICE_TOKEN = 'weather-now-wall-token'
TODAY = datetime.date.today()


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _settings(**extra):
    base = {'weather_entity': ENTITY}
    base.update(extra)
    return base


def _mocks(settings, state=None, entities=None, forecast=None):
    """The four seams the conditions read touches. Returns a list of patchers
    to enter together."""
    return [
        mock.patch('services.storage.get_settings', return_value=settings),
        mock.patch('services.ha_api.get_entities', return_value=entities or []),
        mock.patch('services.ha_api.get_state', return_value=state),
        mock.patch('services.ha_api.get_weather_forecast', return_value=forecast or []),
    ]


class _Patched:
    def __init__(self, patchers):
        self.patchers = patchers

    def __enter__(self):
        for p in self.patchers:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self.patchers):
            p.stop()
        return False


def _patched(settings, **kw):
    return _Patched(_mocks(settings, **kw))


CLOUDY = {'state': 'cloudy', 'attributes': {'temperature': 71.4}}
TODAY_FORECAST = [{'datetime': f'{TODAY.isoformat()}T12:00:00', 'condition': 'rainy',
                   'temperature': 78, 'templow': 61, 'precipitation_probability': 60}]


# --- scenarios ----------------------------------------------------------------

def scenario_no_ha_is_null():
    """No entity configured and HA has no weather entities: nothing to say,
    and saying nothing is a 200 with null, never an error."""
    with _patched({'weather_entity': ''}, state=None, entities=[], forecast=[]):
        check(home_board.current_conditions() is None,
              "no entity and no HA must give None from the helper")
        r = client.get('/api/weather/now')
        check(r.status_code == 200, f"no HA must still answer 200, got {r.status_code}: {r.text[:200]}")
        check(r.json() is None, f"no HA must answer null, got {r.json()!r}")


def scenario_state_without_forecast():
    """A state read with no forecast: the temperature now, rounded, the
    condition, the digest's own emoji for it, and no line."""
    expected = {'temp_now': 71, 'condition': 'cloudy',
                'emoji': family_digest._WEATHER_EMOJI['cloudy'], 'line': None}
    with _patched(_settings(), state=CLOUDY, forecast=[]):
        got = home_board.current_conditions()
        check(got == expected, f"helper returned {got!r}, expected {expected!r}")
        r = client.get('/api/weather/now')
        check(r.status_code == 200, f"GET /api/weather/now -> {r.status_code}: {r.text[:200]}")
        check(r.json() == expected, f"route returned {r.json()!r}, expected {expected!r}")


def scenario_line_is_todays_forecast():
    """The line is the digest's own sentence for today, not a second wording."""
    with _patched(_settings(), state=CLOUDY, forecast=TODAY_FORECAST):
        want = family_digest.weather_line(TODAY)
        check(want, "the fixture forecast must give the digest a line (fixture is wrong)")
        got = home_board.current_conditions()
        check(got is not None and got.get('line') == want,
              f"helper line {None if got is None else got.get('line')!r} != weather_line(today) {want!r}")
        r = client.get('/api/weather/now')
        check(r.status_code == 200, f"GET /api/weather/now -> {r.status_code}: {r.text[:200]}")
        body = r.json() or {}
        check(body.get('line') == want, f"route line {body.get('line')!r} != {want!r}")
        check(body.get('temp_now') == 71 and body.get('condition') == 'cloudy',
              f"the forecast must not replace the state read: {body!r}")


def scenario_build_still_says_the_same():
    """The wall's board and the phone's greeting read one helper, so they can
    never disagree about the weather."""
    with _patched(_settings(), state=CLOUDY, forecast=TODAY_FORECAST):
        home_board.invalidate_cache()
        helper = home_board.current_conditions()
        check(helper is not None, "helper returned None for a real state read")
        data = home_board.build(requested=None, page=None, kid_digest_fn=lambda: {})
        check(data.get('temp_now') == helper['temp_now'],
              f"board temp_now {data.get('temp_now')!r} != helper {helper['temp_now']!r}")
        check(data.get('condition') == helper['condition'],
              f"board condition {data.get('condition')!r} != helper {helper['condition']!r}")
        check(data.get('condition_emoji') == helper['emoji'],
              f"board condition_emoji {data.get('condition_emoji')!r} != helper {helper['emoji']!r}")
        home_board.invalidate_cache()


def scenario_wall_tier_serves_a_member_and_a_device():
    """/api/weather/* is WALL: a signed-in member and an enrolled panel both
    read it; an anonymous caller off the tunnel is refused with 401."""
    if not storage.get_member('wx_adult'):
        storage.add_member({'id': 'wx_adult', 'name': 'Alex', 'role': 'adult'})
    member_token = storage.create_member_token('wx_adult')
    if not storage.get_device_by_token(DEVICE_TOKEN):
        storage.trusted_devices_table.insert({'device_id': 'wx-wall', 'device_token': DEVICE_TOKEN,
                                              'label': 'Kitchen wall', 'kind': 'panel'})
    # Enforcement on, and the local-origin grace off, so an anonymous caller
    # is really anonymous; the tunnel header makes it the public internet.
    enforced = _settings(auth_enforce=True, service_local_grace=False)
    tunnel = {'cf-connecting-ip': '203.0.113.7'}
    with _patched(enforced, state=CLOUDY, forecast=[]):
        r = client.get('/api/weather/now', headers={**tunnel, 'X-Member-Token': member_token})
        check(r.status_code == 200, f"a member token was refused: {r.status_code} {r.text[:200]}")
        check((r.json() or {}).get('condition') == 'cloudy', f"member got {r.text[:200]}")
        r = client.get('/api/weather/now', headers={**tunnel, 'X-Device-Token': DEVICE_TOKEN})
        check(r.status_code == 200, f"a device token was refused: {r.status_code} {r.text[:200]}")
        check((r.json() or {}).get('condition') == 'cloudy', f"device got {r.text[:200]}")
        r = client.get('/api/weather/now', headers=tunnel)
        check(r.status_code == 401, f"no token must be 401 under enforcement, got {r.status_code}")


SCENARIOS = [
    scenario_no_ha_is_null,
    scenario_state_without_forecast,
    scenario_line_is_todays_forecast,
    scenario_build_still_says_the_same,
    scenario_wall_tier_serves_a_member_and_a_device,
]


if __name__ == '__main__':
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)} scenarios passed")

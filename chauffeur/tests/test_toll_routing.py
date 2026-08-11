"""Toll policy (v2.166.0): whether a household drives toll roads is a fact
about the household, not about the road network.

Mapbox defaults to tolls-allowed, which priced an Apex practice run over the
NC-540 toll road — 17 minutes quoted for a drive the family makes in 20 on
free roads. Tested at the seams:

  - `exclude=toll` rides every driving request when the setting is on
    (day-of traffic, route geometry, the pairwise Directions tier) and
    never on non-driving profiles
  - the Matrix tier is skipped entirely under the policy — the Matrix API
    cannot express the exclusion, and a toll-priced matrix answer is wrong,
    not merely imprecise
  - flipping the policy burns every cached duration (static, day-of,
    geometry, sweep markers) — the static cache is deliberately immortal,
    so this is the only way the new policy ever takes effect

Run from chauffeur/:  python tests/test_toll_routing.py
"""
import os
import types

from harness import check
from services import storage, maps


class _Resp:
    status_code = 200

    def json(self):
        return {'routes': [{'duration': 1020, 'distance': 12000,
                            'geometry': {'type': 'LineString', 'coordinates': []}}]}


def _rig(avoid: bool):
    """Point maps at a recording fake for one scenario."""
    calls = []
    real = {
        'opt': maps.get_map_option, 'key': maps.get_mapbox_api_key,
        'geo': maps.geocode_address, 'usage': maps.check_usage_limits_and_spikes,
        'req': maps.requests,
    }
    maps.get_map_option = lambda k, d=None: avoid if k == 'routing_avoid_tolls' else d
    maps.get_mapbox_api_key = lambda: 'test-key'
    maps.geocode_address = lambda addr: (35.78, -78.91) if 'home' in addr.lower() else (35.68, -78.83)
    maps.check_usage_limits_and_spikes = lambda *a, **kw: True
    maps.requests = types.SimpleNamespace(
        get=lambda url, params=None, timeout=None:
            (calls.append({'url': url, 'params': dict(params or {})}), _Resp())[1])
    return calls, real


def _unrig(real):
    maps.get_map_option = real['opt']
    maps.get_mapbox_api_key = real['key']
    maps.geocode_address = real['geo']
    maps.check_usage_limits_and_spikes = real['usage']
    maps.requests = real['req']


def scenario_the_toll_policy_rides_every_driving_request():
    calls, real = _rig(avoid=True)
    try:
        maps.fetch_traffic_minutes('home', 'the gym')
        check(calls and calls[-1]['params'].get('exclude') == 'toll',
              f"day-of traffic must respect the toll policy, got {calls[-1] if calls else None}")
        maps.get_route_geometry('home', 'the gym', profile='driving')
        check(calls[-1]['params'].get('exclude') == 'toll',
              "route geometry must respect the toll policy")
        maps.get_route_geometry('home', 'the gym', profile='walking')
        check('exclude' not in calls[-1]['params'],
              "exclude=toll is not a walking parameter — sending it 400s the request")
    finally:
        _unrig(real)

    calls, real = _rig(avoid=False)
    try:
        maps.fetch_traffic_minutes('home', 'the gym2')
        check(calls and 'exclude' not in calls[-1]['params'],
              "with the policy off, requests stay exactly as they were")
    finally:
        _unrig(real)


def scenario_flipping_the_policy_burns_every_cached_minute():
    storage.set_cached_travel_time('home', 'the gym', 17)
    storage.set_cached_day_of_traffic('35.7800,-78.9100', '35.6800,-78.8300', 28, 'refine')
    storage.set_app_state('traffic_sweep_done_v2', {'date': 'x', 'done': {'a': True}})
    storage.clear_route_caches()
    check(storage.get_cached_travel_time('home', 'the gym', ignore_age=True) is None,
          "the immortal static cache must burn on a policy flip")
    check(storage.get_cached_day_of_traffic('35.7800,-78.9100', '35.6800,-78.8300') is None,
          "day-of rows priced under the old policy must go with it")
    check(storage.get_app_state('traffic_sweep_done_v2') is None,
          "and the sweep markers, so today re-prices under the new policy")


def scenario_the_wiring_cannot_quietly_regress():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    maps_src = open(os.path.join(root, 'services', 'maps.py'), encoding='utf-8').read()
    check('not avoid_tolls and check_usage_limits_and_spikes' in maps_src,
          "the Matrix tier must be skipped under the toll policy — it cannot "
          "express exclude=toll, and a toll-priced matrix answer is wrong")
    check(maps_src.count("params[\"exclude\"] = \"toll\"") >= 3
          or maps_src.count("params['exclude'] = 'toll'")
          + maps_src.count('params["exclude"] = "toll"') >= 3,
          "all three driving request sites must carry the exclusion")
    main_src = open(os.path.join(root, 'main.py'), encoding='utf-8').read()
    check('routing_avoid_tolls' in main_src and 'clear_route_caches' in main_src,
          "a settings flip must burn the caches, or the new policy never "
          "takes effect against an immortal static cache")


def scenario_the_settings_reach_the_model_and_the_page():
    """Reported: "I don't see the setting on the settings page." The registry
    is a catalog, not a renderer — a setting is only real once it is (1) a
    field on the Settings model (the save endpoint DROPS unknown keys
    silently — the partial-save lesson) and (2) wired on the config page:
    declared, loaded, saved, and rendered."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    schemas_src = open(os.path.join(root, 'models', 'schemas.py'),
                       encoding='utf-8').read()
    for key in ('traffic_live_enabled', 'traffic_morning_hour',
                'routing_avoid_tolls'):
        check(key in schemas_src,
              f"{key} is not a Settings field — the save endpoint silently "
              "drops keys the model does not carry")
    config = open(os.path.join(root, 'templates', 'config.html'),
                  encoding='utf-8').read()
    for prop in ('trafficLiveEnabled', 'trafficMorningHour', 'routingAvoidTolls'):
        check(config.count(prop) >= 4,
              f"{prop} must be declared, loaded, saved AND rendered on the "
              f"config page — found only {config.count(prop)} mentions")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} toll-routing scenarios passed")

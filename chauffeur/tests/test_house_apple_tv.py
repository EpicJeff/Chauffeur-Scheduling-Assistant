"""Argyle opens apps on an Apple TV too (2026-11-10).

The user: "I was also told there is no tool to open an app on an Apple TV. If
that is possible to do, we should add that tool." It is possible: Home
Assistant's Apple TV integration publishes a media_player whose source_list is
the installed apps ("Disney+", "ESPN", "FOX NOW", ...), and
media_player.select_source with one of those names launches it. Live 2026-11-10:
media_player.living_room_apple_tv (platform apple_tv) lists ABC, AMC, App Store,
Arlo, Bravo, DIRECTV, Disney+, ESPN, FaceTime, Fitness, FOX NOW, Fubo, ...

house(action='app') learns a second kind of TV, through the SAME entry point
(services.house.open_app), the same exposure check and the same control rulebook:
  - an Apple TV is a media_player from the apple_tv platform with a source_list;
    `find` lists its apps like an Android TV's;
  - the spoken app is matched against the source_list (the names HA lists are
    the only names it accepts);
  - an Apple TV that is off gets media_player.turn_on first, then
    media_player.select_source {entity_id, source};
  - the TV is read back (app_name / source): "Living Room Apple TV is on
    Disney+." or, when it has not reported the switch, says so honestly;
  - unknown app: an error naming what that TV lists, nothing sent; offline TV:
    "... is offline right now".
Android TVs behave exactly as before (tests/test_house_tool.py stays green).

Run from chauffeur/:  python tests/test_house_apple_tv.py
"""
import unittest

import test_house_tool as base           # isolates CHAUFFEUR_DATA_DIR, fixtures
from services import ha_api, house

ATV = 'media_player.living_room_apple_tv'
ATV_APPS = ['ABC', 'AMC', 'App\xa0Store', 'Arlo', 'Bravo', 'DIRECTV', 'Disney+', 'ESPN', 'FaceTime',
            'Fitness', 'FOX NOW', 'Fubo', 'Max', 'Music', 'Netflix', 'YouTube']
HOMEPOD = 'media_player.kitchen_homepod'


class AppleTvApps(unittest.TestCase):
    def setUp(self):
        base.HouseToolTests.setUp(self)
        self.addCleanup(base.HouseToolTests.tearDown, self)
        self.atv_reports = True
        self.states.append({'entity_id': ATV, 'state': 'idle', 'last_changed': '2026-11-10T09:00:00+00:00',
                            'attributes': {'friendly_name': 'Living Room Apple TV', 'source_list': list(ATV_APPS),
                                           'app_id': 'com.apple.TVWatchList', 'app_name': 'TV',
                                           'supported_features': 450487}})
        registry = base.REGISTRY + [
            {'entity_id': ATV, 'name': None, 'original_name': 'Living Room Apple TV', 'aliases': [],
             'area_id': 'living_room', 'device_id': 'dev_apple_tv', 'hidden_by': None, 'disabled_by': None,
             'platform': 'apple_tv'}]
        # A HomePod is apple_tv platform too, but it has no app list: never a TV.
        self.states.append({'entity_id': HOMEPOD, 'state': 'unavailable', 'last_changed': '2026-11-10T09:00:00+00:00',
                            'attributes': {'friendly_name': 'Kitchen HomePod'}})
        registry.append({'entity_id': HOMEPOD, 'name': None, 'original_name': 'Kitchen HomePod', 'aliases': [],
                         'area_id': None, 'device_id': 'dev_homepod', 'hidden_by': None, 'disabled_by': None,
                         'platform': 'apple_tv'})
        exposed = {**base.EXPOSED, ATV: True}
        services = {**base.SERVICES, 'media_player': {'turn_off', 'turn_on', 'select_source'}}
        inner = ha_api.call_service
        tests = self

        def call_service(domain, service, data=None, return_response=False, timeout=None):
            result = inner(domain, service, data, return_response, timeout)
            eid = (data or {}).get('entity_id')
            for s in tests.states:
                if s['entity_id'] != eid or eid != ATV:
                    continue
                if (domain, service) == ('media_player', 'turn_on'):
                    s['state'] = 'idle'
                if (domain, service) == ('media_player', 'select_source') and tests.atv_reports:
                    s['state'] = 'playing'
                    s['attributes']['app_name'] = data['source']
                    s['attributes']['source'] = data['source']
            return result
        self.orig.setdefault((ha_api, 'get_entity_registry'), ha_api.get_entity_registry)
        ha_api.get_entity_registry = lambda ttl=300: registry
        ha_api.get_exposed = lambda ttl=60: dict(exposed)
        ha_api.has_service = lambda d, s: s in services.get(d, set())
        ha_api.call_service = call_service

    def atv(self):
        return next(s for s in self.states if s['entity_id'] == ATV)

    def open(self, app, query='living room apple tv', **kw):
        return self.run_tool(action='app', query=query, app=app, **kw)

    run_tool = base.HouseToolTests.run_tool

    def test_find_lists_the_apple_tv_apps(self):
        rows = {c['entity_id']: c for c in self.run_tool(action='find', query='living room apple tv')['candidates']}
        self.assertEqual(rows[ATV]['apps'], ATV_APPS)

    def test_apple_tv_opens_an_app_by_its_listed_name(self):
        res = self.open('disney plus')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls, [('media_player', 'select_source', {'entity_id': ATV, 'source': 'Disney+'})])
        self.assertEqual(res['entity_id'], ATV)
        self.assertEqual(res['app'], 'Disney+')
        self.assertTrue(res['landed'])
        self.assertEqual(res['message'], 'Living Room Apple TV is on Disney+.')

    def test_spoken_forms_match_the_listed_names(self):
        for spoken, listed in (('espn', 'ESPN'), ('Fox Now', 'FOX NOW'), ('the app store', 'App\xa0Store'),
                               ('netflix', 'Netflix')):
            self.calls.clear()
            res = self.open(spoken)
            self.assertEqual(res['status'], 'success', (spoken, res))
            self.assertEqual(self.calls[-1], ('media_player', 'select_source', {'entity_id': ATV, 'source': listed}))

    def test_known_app_nicknames_land_on_the_listed_name(self):
        for spoken, listed in (('hbo max', 'Max'), ('apple music', 'Music')):
            self.calls.clear()
            res = self.open(spoken)
            self.assertEqual(res['status'], 'success', (spoken, res))
            self.assertEqual(self.calls[-1], ('media_player', 'select_source', {'entity_id': ATV, 'source': listed}))

    def test_a_homepod_is_never_a_tv(self):
        res = self.open('ESPN', query='kitchen homepod')
        self.assertEqual(res['status'], 'error')
        self.assertNotIn('offline', res['message'])
        self.assertNotIn('Kitchen HomePod', res['message'].split('TVs that can open apps:')[-1])
        self.assertEqual(self.calls, [])

    def test_an_apple_tv_that_is_off_is_woken_first(self):
        self.atv()['state'] = 'off'
        res = self.open('ESPN')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls, [('media_player', 'turn_on', {'entity_id': ATV}),
                                      ('media_player', 'select_source', {'entity_id': ATV, 'source': 'ESPN'})])

    def test_unknown_app_names_what_the_apple_tv_lists_and_sends_nothing(self):
        res = self.open('Crunchyroll')
        self.assertEqual(res['status'], 'error')
        self.assertIn('Living Room Apple TV', res['message'])
        self.assertIn('Disney+', res['message'])
        self.assertEqual(self.calls, [])

    def test_offline_apple_tv(self):
        self.atv()['state'] = 'unavailable'
        res = self.open('ESPN')
        self.assertEqual(res['status'], 'error')
        self.assertIn('offline', res['message'])
        self.assertEqual(self.calls, [])

    def test_honest_when_the_apple_tv_does_not_report_the_switch(self):
        self.atv_reports = False
        res = self.open('ESPN')
        self.assertEqual(res['status'], 'success')
        self.assertFalse(res['landed'])
        self.assertIn('has not reported', res['message'])

    def test_unexposed_apple_tv_is_refused(self):
        ha_api.get_exposed = lambda ttl=60: {**base.EXPOSED, ATV: False}
        res = self.open('ESPN')
        self.assertEqual(res['status'], 'refused')
        self.assertEqual(self.calls, [])

    def test_android_tv_path_unchanged(self):
        res = self.run_tool(action='app', query='office tv', app='netflix',
                            acting_member={'id': 'm_lily', 'role': 'child'})
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls[0][:2], ('remote', 'turn_on'))


if __name__ == '__main__':
    unittest.main(verbosity=2)

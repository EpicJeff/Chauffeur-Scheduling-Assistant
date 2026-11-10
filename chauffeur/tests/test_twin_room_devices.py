"""Task 7's area membership and rendered navigation, through the real app.

Reuse the Task 3 fake HA and model fixtures without changing their tests.
Run from chauffeur/ with HA_BASE_URL unset.
"""
from html.parser import HTMLParser
import sys
import traceback
from urllib.parse import parse_qs, urljoin, urlparse

import test_twin_ha_routes as H


def test_devices_follow_area_while_markers_keep_placement():
    H.seed(anchors=[H.ceiling_anchor()])
    with H.Ctx() as c:
        c.ha.move_device('dev-k-light', 'patio')
        body = c.client.get(H.LIVE, headers=c.panel).json()
        device = next(d for d in body['devices'] if d['device_id'] == 'dev-k-light')
        assert device['area_id'] == 'patio'
        assert H.marker_for(body, 'dev-k-light')['room'] == 'kitchen'
        assert device['offered'] is True


def test_devices_include_unspotted_and_obey_grid_without_ha():
    H.seed()
    with H.Ctx() as c:
        body = c.client.get(H.LIVE, headers=c.panel).json()
        by_id = {d['device_id']: d for d in body['devices']}
        assert 'dev-patio-light' in by_id  # its area has no room/auto spot
        assert H.marker_for(body, 'dev-patio-light') is None
        assert by_id['dev-back-lock']['offered'] is False
        for marker in body['markers']:
            assert marker['offered'] == by_id[marker['device_id']]['offered']
        rules = H.cr.default_rules({})
        rules['enabled'] = False
        c.extra = {'ha_control': rules}
        assert all(not d['offered'] for d in c.client.get(H.LIVE, headers=c.mum).json()['devices'])
    with H.Ctx(available=False) as c:
        assert c.client.get(H.LIVE, headers=c.panel).json()['devices'] == []


def test_two_rooms_share_the_same_area_devices():
    H.seed(kitchen_area='kitchen', dining_area='kitchen')
    with H.Ctx() as c:
        body = c.client.get(H.LIVE, headers=c.panel).json()
        rooms = {r['room']: r for r in body['rooms']}
        devices = lambda room: {d['device_id'] for d in body['devices'] if d['area_id'] == room['area_id']}
        assert devices(rooms['kitchen']) == devices(rooms['dining']) == {'dev-k-light', 'dev-k-lamp', 'dev-back-lock'}
        assert rooms['kitchen']['lights'] == rooms['dining']['lights']


class Elements(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.ids = {}
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if 'id' in data:
            self.ids[data['id']] = (tag, data)
        if tag == 'html':
            self.html = data


def test_rendered_house_link_keeps_wall_flags_and_twin_keeps_shelf():
    H.seed()
    with H.Ctx() as c:
        response = c.client.get('/house?panel=true&kiosk=true', headers=c.panel)
        assert response.status_code == 200, response.text[:300]
        page = Elements(response.text)
        tag, link = page.ids['house-twin-link']
        assert tag == 'a'
        target = urlparse(urljoin('https://example.test/api/hassio_ingress/test/house', link['href']))
        assert target.path == '/api/hassio_ingress/test/house/twin'
        assert parse_qs(target.query) == {'panel': ['true'], 'kiosk': ['true']}
        response = c.client.get('/house/twin?panel=true&kiosk=true', headers=c.panel)
        assert response.status_code == 200, response.text[:300]
        page = Elements(response.text)
        assert 'data-twin-wall' in page.html
        assert 'twin-edit' not in page.ids
        assert 'panel-shelf' in page.ids


TESTS = [value for name, value in sorted(globals().items()) if name.startswith('test_')]
if __name__ == '__main__':
    passed = 0
    for test in TESTS:
        try:
            test()
            passed += 1
            print('ok  ', test.__name__)
        except Exception:
            print('FAIL', test.__name__)
            traceback.print_exc(limit=4)
    print(f'{passed}/{len(TESTS)} passed')
    sys.exit(0 if passed == len(TESTS) else 1)

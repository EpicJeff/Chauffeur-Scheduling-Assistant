"""Exercise pairing, verification and phone recovery through the served Settings UI."""
import os
import tempfile
import time
import uuid

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_voice_live_')
from harness import check
from live_app import live_app
from services import storage, voice_identity as voice


def seed():
    storage.get_settings = lambda: {'service_token': 'voice-test-service', 'auth_enforce': False,
                                    'missions_enabled': False, 'calendar_ids': [], 'ha_base_url': ''}
    storage.add_member({'id': 'parent', 'name': 'Jeff', 'role': 'parent'})
    storage.set_member_pin('parent', '1234')
    global TOKEN
    TOKEN = storage.create_member_token('parent')
    voice.configure(False, [{'ha_instance_id': 'ha', 'satellite_id': 'assist_satellite.kitchen',
                             'device_id': 'device', 'label': 'Kitchen', 'enabled': True}])


def metadata():
    return {'ha_instance_id': 'ha', 'satellite_id': 'assist_satellite.kitchen', 'device_id': 'device',
            'observed_at': time.time(), 'request_id': uuid.uuid4().hex}


def main():
    served = live_app(seed)
    check(served is not None, 'Playwright is required for the voice Settings check.')
    shots = tempfile.mkdtemp(prefix='chauffeur_voice_ui_')
    try:
        with served.browser() as page:
            # Chat streams are unrelated to this check; do not leave an idle
            # SSE response inside middleware while closing the test browser.
            page.route('**/*stream*', lambda route: route.fulfill(status=200,
                       content_type='text/event-stream', body='data: test\n\n'))
            page.add_init_script("localStorage.setItem('chauffeur_admin_token', " + repr(TOKEN) + ");"
                                 "localStorage.setItem('chauffeur_admin_token_for', 'parent');")
            page.goto(served.url('config#voice-identity'), wait_until='domcontentloaded')
            page.locator('#voice-identity > summary').click()
            page.wait_for_function("() => Alpine.$data(document.body).voiceState.satellites.length === 1")
            controls = page.locator('#voice-identity input[type=checkbox]')
            check(not controls.nth(0).is_checked(), 'Identity starts off.')
            controls.nth(0).check()
            page.wait_for_function("() => Alpine.$data(document.body).voiceState.enabled")
            check(not controls.nth(1).is_checked(), 'Approvals stay off until device acceptance.')

            def speak(text):
                response = page.request.post(served.url('api/v2/converse'), headers={'X-Service-Token': 'voice-test-service'},
                                             data={'text': text, 'voice': metadata()})
                check(response.ok, f'Voice endpoint failed: {response.status}')
                return response.json()

            speak("It's Jeff")
            speak('My PIN is 1234')
            page.get_by_role('button', name='Refresh voice status', exact=True).click()
            page.wait_for_function("() => Alpine.$data(document.body).voiceState.satellites[0].level === 'verified'")
            for name, viewport in [('desktop', {'width': 1400, 'height': 1000}), ('phone', {'width': 390, 'height': 844})]:
                page.set_viewport_size(viewport)
                page.locator('#voice-identity').scroll_into_view_if_needed()
                page.screenshot(path=os.path.join(shots, name + '.png'))
                check(page.get_by_role('button', name='Revoke session', exact=True).is_visible(), 'Recovery must be visible.')
                box = page.get_by_role('button', name='Revoke session', exact=True).bounding_box()
                check(box['height'] >= 44, 'Recovery needs a touch-sized button.')
            page.get_by_role('button', name='Revoke session', exact=True).click()
            page.wait_for_function("() => Alpine.$data(document.body).voiceState.satellites[0].level === 'unknown'")
            speak("It's Jeff")
            for _ in range(3): speak('My PIN is 4321')
            page.get_by_role('button', name='Refresh voice status', exact=True).click()
            page.wait_for_function("() => Alpine.$data(document.body).voiceState.satellites[0].locked")
            page.get_by_role('button', name='Clear voice lock', exact=True).click()
            page.wait_for_function("() => !Alpine.$data(document.body).voiceState.satellites[0].locked")
            check(not voice.admin_state()['locked_members'], 'Phone recovery clears the relevant member lock too.')
        errors = [e for e in served.errors() if 'Alpine' in e or 'TypeError' in e or 'SyntaxError' in e]
        check(not errors, f'Voice Settings runtime errors: {errors}')
        print('PASS: served Settings pairing, verification, revoke and lock recovery on desktop/phone.')
        print('Screenshots:', shots)
    finally:
        served.stop()


if __name__ == '__main__':
    main()

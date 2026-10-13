"""Served phone enrollment, activation, recognition and deletion; fake inference."""
import os
import tempfile
import time
import uuid

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_recognition_live_')
from harness import check
from live_app import live_app
from services import storage, voice_identity as voice, voice_fingerprint as fp

MODEL_READY = False


def seed():
    storage.get_settings = lambda: {'service_token': 'voice-test-service', 'auth_enforce': False,
                                    'missions_enabled': False, 'calendar_ids': [], 'ha_base_url': ''}
    storage.add_member({'id': 'parent', 'name': 'Jeff', 'role': 'parent'})
    global TOKEN
    TOKEN = storage.create_member_token('parent')
    voice.configure(False, [{'ha_instance_id': 'ha', 'satellite_id': 'assist_satellite.kitchen',
                             'device_id': 'device', 'label': 'Kitchen', 'enabled': True}])
    fp.model_ready = lambda: MODEL_READY
    def prepare():
        global MODEL_READY
        MODEL_READY = True
        return fp.status()
    fp.prepare_model = prepare
    fp.extract = lambda audio, metadata: ([float(i == (1 if audio == b'other speaker' else 0)) for i in range(256)], 6)
    from services import agent_router
    def answer(text, **kwargs):
        member = kwargs['voice_context'].member()
        return {'message': 'Your name is ' + (member.get('name') if member else 'unknown') + '.'}
    agent_router.process_agent_request = answer


def main():
    served = live_app(seed)
    check(served is not None, 'Playwright is required.')
    shots = tempfile.mkdtemp(prefix='chauffeur_recognition_ui_')
    try:
        with served.browser() as page:
            page.route('**/*stream*', lambda route: route.fulfill(status=200,
                       content_type='text/event-stream', body='data: test\n\n'))
            page.add_init_script("localStorage.setItem('chauffeur_admin_token', " + repr(TOKEN) + ");"
                                 "localStorage.setItem('chauffeur_admin_token_for', 'parent');")
            page.goto(served.url('config#voice-identity'), wait_until='domcontentloaded')
            page.locator('#voice-identity > summary').click()
            page.wait_for_function("() => Alpine.$data(document.body).voiceState.satellites.length === 1")
            section = page.locator('#voice-identity')
            section.get_by_label('Enable voice identity on the selected satellites').check()
            page.wait_for_function("() => Alpine.$data(document.body).voiceState.enabled")
            section.get_by_role('button', name='Prepare local voice model (27 MB)', exact=True).click()
            page.wait_for_function("() => Alpine.$data(document.body).voiceRecognition.model_ready")
            section.get_by_label('Family member to enroll').select_option('parent')
            section.get_by_label('The selected person agrees', exact=False).check()
            section.get_by_role('button', name='Enroll voice on this satellite', exact=True).click()
            page.wait_for_function("() => Alpine.$data(document.body).voiceRecognition.enrollments.length === 1")

            def speak(text, other=False):
                request_id = uuid.uuid4().hex
                metadata = {'ha_instance_id': 'ha', 'satellite_id': 'assist_satellite.kitchen',
                            'device_id': 'device', 'observed_at': time.time(), 'request_id': request_id,
                            'utterance_id': request_id, 'run_id': uuid.uuid4().hex}
                import json
                observation = page.request.post(served.url('api/voice/audio'),
                    headers={'X-Service-Token': 'voice-test-service', 'X-Voice-Metadata': json.dumps(metadata)},
                    data=b'other speaker' if other else b'consented setup speech')
                check(observation.ok, f'Observation failed: {observation.status}')
                metadata.update(observation.json())
                response = page.request.post(served.url('api/v2/converse'),
                    headers={'X-Service-Token': 'voice-test-service'}, data={'text': text, 'voice': metadata})
                check(response.ok, f'Conversation failed: {response.status}')
                return response.json()['response']['speech']['plain']['speech']

            for index, phrase in enumerate(fp.PROMPTS):
                check(section.get_by_text(phrase, exact=True).is_visible(), 'Show the current setup phrase.')
                reply = speak(phrase)
                check('accepted' in reply or 'saved' in reply, 'Accept a correlated setup sample.')
                section.get_by_role('button', name='Refresh voice status', exact=True).click()
                page.wait_for_function("step => {const e=Alpine.$data(document.body).voiceRecognition.enrollments; return step === 6 ? e.length === 0 : e[0]?.step === step}", arg=index + 2)
                if index == 0:
                    for name, viewport in [('desktop', {'width': 1400, 'height': 1000}), ('phone', {'width': 390, 'height': 844})]:
                        page.set_viewport_size(viewport)
                        section.get_by_text(fp.PROMPTS[1], exact=True).scroll_into_view_if_needed()
                        page.screenshot(path=os.path.join(shots, name + '.png'))
            check(not section.get_by_label('Allow PIN-verified release and booking approvals').is_checked(), 'Recognition does not enable approvals.')
            section.get_by_label('Recognize enrolled voices here and check for speaker changes').check()
            page.wait_for_function("() => Alpine.$data(document.body).voiceState.satellites[0].recognition_enabled")
            check(speak('Who am I?') == 'Hi Jeff. Your name is Jeff.', 'Automatic naming without a spoken name/PIN.')
            check(speak('Who am I?', other=True) == 'Your name is unknown.', 'A new speaker loses the old lens.')
            section.get_by_role('button', name='Delete voice samples', exact=True).click()
            page.wait_for_function("() => Alpine.$data(document.body).voiceRecognition.profiles.length === 0")
            check(speak('Who am I?') == 'Your name is unknown.', 'Deleting enrollment removes automatic recognition.')
        errors = [e for e in served.errors() if 'Alpine' in e or 'TypeError' in e or 'SyntaxError' in e]
        check(not errors, f'Voice setup runtime errors: {errors}')
        print('PASS: served enrollment, activation, automatic naming, speaker change and deletion; fixture inference.')
        print('Screenshots:', shots)
    finally:
        served.stop()


if __name__ == '__main__':
    main()

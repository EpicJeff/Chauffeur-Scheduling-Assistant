"""Served phone UI with fixture mic/provider/audio; not iPhone acceptance."""
import io
import os
import tempfile
import wave

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_phone_voice_live_')
from harness import check
from live_app import live_app
from services import storage, app_voice_audio as audio, agent_router, agent_tools_v2


def seed():
    import main
    storage.get_settings = lambda: {'auth_enforce': False, 'calendar_ids': [], 'missions_enabled': False,
                                    'ha_base_url': '', 'llm_gemini_api_key': ''}
    storage.add_member({'id': 'parent', 'name': 'Jeff', 'role': 'parent', 'color_code': '#6366f1'})
    global TOKEN
    TOKEN = storage.create_member_token('parent')
    storage.ensure_argyle_member()
    storage.set_cached_schedule({'events': [{'id': 'soccer', 'title': 'Soccer', 'start': '2026-10-13T16:00:00'}]})
    main._fanout_message_notifications = lambda *a, **kw: None
    texts = iter(['Calendar please', 'PRIVATE points please', 'My PIN is 1234', 'Calendar please'])
    audio.transcribe = lambda *a: next(texts)
    global SPOKEN
    SPOKEN = []
    def speak(text):
        SPOKEN.append(text)
        return b'fixture-audio', 'audio/wav'
    audio.speak = speak
    def model(prompt, tools, system):
        if 'PRIVATE' in prompt:
            return {'tool_calls': [{'name': 'get_point_balances', 'arguments': {}}]}
        if 'TOOL EXECUTION SCRATCHPAD' in system:
            return {'message': 'Soccer is at four. Anything else?'}
        return {'tool_calls': [{'name': 'get_calendar_events', 'arguments': {'start_date': '2026-10-13', 'end_date': '2026-10-13'}}]}
    agent_router.call_gemma_with_fallback = model
    agent_tools_v2.get_point_balances = lambda: {'status': 'success', 'message': 'PRIVATE balance is 17.'}


MOCKS = """
window.micStops = 0;
window.denyMic = false;
window.denyPlayback = false;
Object.defineProperty(navigator, 'mediaDevices', {configurable: true, value: {
    getUserMedia: async () => {
        if (window.denyMic) throw new DOMException('Denied', 'NotAllowedError');
        return {getTracks: () => [{stop: () => window.micStops++, addEventListener: () => {}}]};
    }
}});
window.MediaRecorder = class {
    static isTypeSupported() { return true; }
    constructor(stream, options) { this.state = 'inactive'; this.mimeType = options.mimeType; }
    start() { this.state = 'recording'; }
    stop() {
        this.state = 'inactive';
        setTimeout(() => {
            this.ondataavailable?.({data: new Blob(['fixture-recording'], {type: this.mimeType})});
            this.onstop?.();
        }, 0);
    }
};
window.Audio = class {
    async play() {
        if (window.denyPlayback) throw new DOMException('Gesture needed', 'NotAllowedError');
        this.onplaying?.();
        setTimeout(() => this.onended?.(), 100);
    }
    pause() {}
};
window.SpeechRecognition = class {
    start() {
        const result = [{transcript: 'Calendar please'}]; result.isFinal = true;
        setTimeout(() => this.onresult?.({results: [result]}), 150);
    }
    stop() {}
    abort() {}
};
"""


def main():
    served = live_app(seed)
    check(served is not None, 'Playwright is required for the phone voice check.')
    shots = tempfile.mkdtemp(prefix='chauffeur_phone_voice_ui_')
    try:
        browser = served.browser()
        with browser as page:
            page.set_viewport_size({'width': 390, 'height': 844})
            page.add_init_script(MOCKS)
            page.add_init_script("localStorage.setItem('chauffeur_member_id', 'parent');"
                                 "localStorage.setItem('chauffeur_member_token_for', 'parent');"
                                 "localStorage.setItem('chauffeur_member_token', " + repr(TOKEN) + ");")
            page.route('**/*stream*', lambda route: route.fulfill(status=200,
                       content_type='text/event-stream', body='data: test\n\n'))
            page.goto(served.url('app'), wait_until='domcontentloaded')
            page.wait_for_function('() => !!window.ChauffeurPhoneVoice')
            page.evaluate('ChauffeurPhoneVoice.start()')
            page.wait_for_function("() => ChauffeurPhoneVoice.state === 'listening'")
            done = page.get_by_role('button', name='Done', exact=True)
            check(done.is_visible(), 'Recording exposes Done on the phone.')
            page.screenshot(path=os.path.join(shots, 'listening.png'))
            done.click()
            page.wait_for_function("() => ChauffeurPhoneVoice.response?.reply.includes('Soccer')")
            page.get_by_text('Soccer is at four. Anything else?', exact=True).wait_for()
            page.get_by_role('button', name='Tap to reply', exact=True).wait_for()
            check(SPOKEN[-1].startswith('Soccer'), 'Shared answer uses household TTS.')
            page.screenshot(path=os.path.join(shots, 'reply.png'))

            page.get_by_role('button', name='Tap to reply', exact=True).click()
            page.wait_for_function("() => ChauffeurPhoneVoice.state === 'listening'")
            done.click()
            page.wait_for_function("() => ChauffeurPhoneVoice.response?.reply.includes('PRIVATE')")
            page.get_by_text('PRIVATE balance is 17.', exact=True).wait_for()
            page.wait_for_function("() => ChauffeurPhoneVoice.state === 'idle'")
            check(SPOKEN[-1] == 'I put that on your screen.', 'Private answer stays display-only.')

            page.evaluate('window.denyMic = true; ChauffeurPhoneVoice.start()')
            page.get_by_text('Microphone access was denied. Allow it in Settings or use text.', exact=True).wait_for()
            page.evaluate('window.denyMic = false; window.denyPlayback = true; ChauffeurPhoneVoice.start()')
            page.wait_for_function("() => ChauffeurPhoneVoice.state === 'listening'")
            done.click()
            page.get_by_role('button', name='Play reply', exact=True).wait_for()
            check('1234' not in page.locator('#phone-voice-panel').inner_text(), 'Credential never renders in voice UI.')
            page.evaluate('window.denyPlayback = false')
            page.get_by_role('button', name='Play reply', exact=True).click()
            page.wait_for_function("() => ChauffeurPhoneVoice.state === 'idle'")

            page.evaluate('ChauffeurPhoneVoice.start()')
            page.wait_for_function("() => ChauffeurPhoneVoice.state === 'listening'")
            page.get_by_role('button', name='Stop', exact=True).click()
            page.wait_for_function("() => !ChauffeurPhoneVoice.stream && !ChauffeurPhoneVoice.recorder")
            check(page.evaluate('micStops') >= 4, 'Finished/stopped microphones release tracks.')
            page.goto(served.url('app?voice_probe=browser'), wait_until='domcontentloaded')
            page.wait_for_function('() => !!window.ChauffeurPhoneVoice')
            page.evaluate('ChauffeurPhoneVoice.start()')
            page.wait_for_function("() => ChauffeurPhoneVoice.response?.reply.includes('Soccer')")
            check(page.locator('#phone-voice-transcript').inner_text() == 'Calendar please',
                  'Disposable browser comparison uses the same sanitized transcript/dispatch path.')
            check(not browser.errors, 'Served UI has no JavaScript errors: ' + str(browser.errors))
        print('PASS: served phone mic, transcript/text/speech, private projection, PIN withholding, denial, replay and stop; fixtures only.')
        print('Screenshots:', shots)
    finally:
        served.stop()


if __name__ == '__main__':
    main()

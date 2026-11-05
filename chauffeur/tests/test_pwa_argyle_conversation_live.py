"""Phone Argyle: tap to talk, then keep talking (2026-11-04, approved in chat).

The orb is tap-only: a tap opens the overlay and starts listening at once (no
hold-to-talk). The overlay bar is [mic] [Or type...] [send]. A turn ends by
itself when the speaker pauses (PAUSE_MS of quiet after speech), or when the
mic button is tapped while listening (send now). After Argyle's answer has
played, the mic reopens; NO_SPEECH_MS with no speech closes it, so does a
sign-off, tapping the type box, closing the overlay, or the household switch
being off. Keyboard activation of the orb opens it ready to type. The Argyle
chat in Messages shares the voice client, so it pauses and continues too.

Fixtures: the real server and its phone-voice routes; transcription, the model
and speech are stubbed in-process. In the page, getUserMedia, MediaRecorder,
Audio and AudioContext are fakes; the fake analyser reports window.micLevel as
the waveform amplitude, so the test speaks by raising it and pauses by
dropping it. The client must read loudness through an AnalyserNode
(getFloatTimeDomainData) and expose PAUSE_MS / NO_SPEECH_MS on
ChauffeurPhoneVoice so the test can shorten them.

Run from chauffeur/ with HA_BASE_URL unset:
    python tests/test_pwa_argyle_conversation_live.py
"""
import os
import tempfile

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_pwa_argyle_conversation_')
from harness import check
from live_app import live_app
from services import storage, app_voice_audio as audio

HEARD = []          # what transcription returns next, in order
ANSWERS = []        # what Argyle answers next, in order
CALLS = {'transcribe': 0, 'model': 0}
SWITCH = {'voice_conversation_mode': True}


def seed():
    import main
    storage.get_settings = lambda: {'auth_enforce': False, 'calendar_ids': [], 'missions_enabled': False,
                                    'ha_base_url': '', 'llm_gemini_api_key': '', **SWITCH}
    storage.add_member({'id': 'parent', 'name': 'Jeff', 'role': 'parent', 'color_code': '#6366f1'})
    global TOKEN
    TOKEN = storage.create_member_token('parent')
    storage.ensure_argyle_member()
    main._fanout_message_notifications = lambda *a, **kw: None

    def transcribe(*a, **kw):
        CALLS['transcribe'] += 1
        return HEARD.pop(0) if HEARD else 'Calendar please'
    audio.transcribe = transcribe
    audio.speak = lambda text: (b'fixture-audio', 'audio/wav')

    def worker(channel, member, text):
        CALLS['model'] += 1
        return {'message': ANSWERS.pop(0) if ANSWERS else 'Soccer is at four.'}
    main._run_argyle_mention = worker


MOCKS = """
window.micLevel = 0;
window.micOpen = 0;
window.micStops = 0;
Object.defineProperty(navigator, 'mediaDevices', {configurable: true, value: {
    getUserMedia: async () => {
        window.micOpen++;
        return {getTracks: () => [{stop: () => window.micStops++, addEventListener: () => {}}],
                getAudioTracks: () => []};
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
    async play() { this.onplaying?.(); setTimeout(() => this.onended?.(), 150); }
    pause() {}
};
class FakeAnalyser {
    constructor() { this.fftSize = 2048; }
    get frequencyBinCount() { return this.fftSize / 2; }
    connect() {}
    disconnect() {}
    getFloatTimeDomainData(buf) {
        const level = window.audioSuspended ? 0 : window.micLevel;   // a suspended context hears nothing
        for (let i = 0; i < buf.length; i++) buf[i] = (i % 2 ? 1 : -1) * level;
    }
    getByteTimeDomainData(buf) {
        for (let i = 0; i < buf.length; i++) buf[i] = 128 + Math.round((i % 2 ? 1 : -1) * window.micLevel * 127);
    }
}
window.audioContexts = 0;
window.audioSuspended = false;     // Safari: a context made without a tap may stay suspended
window.AudioContext = window.webkitAudioContext = class {
    constructor() { window.audioContexts++; this.state = window.audioSuspended ? 'suspended' : 'running'; this.sampleRate = 48000; }
    createMediaStreamSource() { return {connect() {}, disconnect() {}}; }
    createAnalyser() { return new FakeAnalyser(); }
    resume() { if (!window.audioSuspended) this.state = 'running'; return Promise.resolve(); }
    close() { this.state = 'closed'; return Promise.resolve(); }
};
"""

STATE = "() => window.ChauffeurPhoneVoice && ChauffeurPhoneVoice.state"


def main():
    served = live_app(seed)
    check(served is not None, 'Playwright is required.')
    shots = tempfile.mkdtemp(prefix='chauffeur_pwa_argyle_conversation_shots_')
    counts = {'start': 0, 'audio': 0}
    try:
        browser = served.browser()
        with browser as page:
            page.set_viewport_size({'width': 390, 'height': 844})
            page.add_init_script(MOCKS)
            page.add_init_script("localStorage.setItem('chauffeur_member_id', 'parent');"
                                 "localStorage.setItem('chauffeur_member_token_for', 'parent');"
                                 "localStorage.setItem('chauffeur_member_token', " + repr(TOKEN) + ");"
                                 "localStorage.setItem('chauffeur_view', 'myday');")
            page.route('**/*stream*', lambda route: route.fulfill(status=200,
                       content_type='text/event-stream', body='data: test\n\n'))

            def count(request):
                url = request.url.split('?')[0]
                if url.endswith('/api/app-voice/start'):
                    counts['start'] += 1
                elif '/api/app-voice/' in url and url.endswith('/audio'):
                    counts['audio'] += 1
            page.on('request', count)
            page.goto(served.url('app'), wait_until='domcontentloaded')
            if page.locator('#pin-modal-skip').is_visible():
                page.locator('#pin-modal-skip').click()
            page.wait_for_function("() => !!window.ChauffeurPhoneVoice && !!window.PwaArgyle")
            page.locator('#tab-argyle').wait_for(state='visible')
            page.evaluate("ChauffeurPhoneVoice.PAUSE_MS = 300; ChauffeurPhoneVoice.NO_SPEECH_MS = 1500;")
            overlay = page.locator('#pwa-argyle-overlay')
            mic = page.locator('#pwa-argyle-overlay .pwa-argyle-bar .pwa-argyle-mic')

            def state():
                return page.evaluate(STATE)

            def wait_state(name, timeout=6000):
                page.wait_for_function("name => window.ChauffeurPhoneVoice && ChauffeurPhoneVoice.state === name",
                                       arg=name, timeout=timeout)

            def speak(ms=400):
                page.evaluate('window.micLevel = 0.3')
                page.wait_for_timeout(ms)
                page.evaluate('window.micLevel = 0')

            def close():
                # Escape walks history back; let that land before the next open,
                # or its popstate closes the overlay that opens next.
                page.keyboard.press('Escape')
                overlay.wait_for(state='hidden')
                page.wait_for_function("() => !(history.state && history.state.pwaOverlay === 'argyle')")
                page.wait_for_timeout(200)

            def released():
                return page.evaluate("() => !ChauffeurPhoneVoice.stream && !ChauffeurPhoneVoice.recorder")

            # 1. A tap opens the overlay listening; the keyboard stays down.
            page.locator('#tab-argyle').click()
            overlay.wait_for(state='visible')
            wait_state('listening')
            check(overlay.get_attribute('data-state') == 'listening', 'the overlay shows Listening')
            check(not page.evaluate("document.activeElement && document.activeElement.matches('.pwa-argyle-input')"),
                  'a tap that listens must not raise the keyboard')
            check(mic.count() == 1 and mic.is_visible(), 'the overlay bar has a mic button')
            bar = page.evaluate("""() => [...document.querySelectorAll('#pwa-argyle-overlay .pwa-argyle-bar > *')]
                                   .map(n => n.classList.contains('pwa-argyle-mic') ? 'mic'
                                        : n.classList.contains('pwa-argyle-input') ? 'input'
                                        : n.classList.contains('pwa-argyle-send') ? 'send' : n.tagName)""")
            check(bar == ['mic', 'input', 'send'], f'the bar reads [mic] [Or type] [send]: {bar}')
            page.screenshot(path=os.path.join(shots, 'listening.png'))

            # 2. A pause ends the turn with no Done; the answer plays; the mic reopens.
            starts = counts['start']
            speak()
            page.locator('#pwa-argyle-overlay .pwa-argyle-reply-body').get_by_text('Soccer is at four.').wait_for(timeout=8000)
            check(CALLS['transcribe'] == 1 and counts['audio'] == 1, f'the pause sent one recording: {CALLS}, {counts}')
            wait_state('listening', 8000)
            check(counts['start'] == starts + 1, f'the mic reopened as a new turn: {counts}')
            page.screenshot(path=os.path.join(shots, 'reply-and-listening.png'))

            # 3. Nothing said for NO_SPEECH_MS closes it; nothing is uploaded; the overlay stays.
            audio_before = counts['audio']
            wait_state('idle', 5000)
            check(released(), 'silence released the microphone')
            check(counts['audio'] == audio_before, 'silence uploaded a recording')
            check(overlay.is_visible(), 'silence closed the overlay; it should only stop listening')
            status = page.locator('#pwa-argyle-overlay .pwa-argyle-status').inner_text().lower()
            check('hold' not in status, f'no hold instructions remain: {status!r}')

            # 4. The mic button starts listening again; a sign-off answers and closes.
            mic.click()
            wait_state('listening')
            HEARD.append("That's all for now.")
            ANSWERS.append('Alright, talk soon.')
            speak()
            page.locator('#pwa-argyle-overlay .pwa-argyle-reply-body').get_by_text('Alright, talk soon.').wait_for(timeout=8000)
            starts = counts['start']
            wait_state('idle', 6000)
            page.wait_for_timeout(600)
            check(state() == 'idle' and counts['start'] == starts, f'a sign-off kept listening: {state()}, {counts}')
            check(released(), 'the sign-off released the microphone')

            # 5. Tapping the mic while listening sends at once, without a pause.
            mic.click()
            wait_state('listening')
            page.evaluate('window.micLevel = 0.3')
            page.wait_for_timeout(300)
            transcribed = CALLS['transcribe']
            mic.click()
            page.locator('#pwa-argyle-overlay .pwa-argyle-reply-body').get_by_text('Soccer is at four.').wait_for(timeout=8000)
            check(CALLS['transcribe'] == transcribed + 1, 'the mic tap did not send the turn')
            page.evaluate('window.micLevel = 0')
            wait_state('listening', 8000)

            # 6. Tapping the type box stops voice and raises the keyboard.
            page.locator('#pwa-argyle-overlay .pwa-argyle-input').click()
            wait_state('idle')
            check(released(), 'typing left the microphone open')
            check(page.evaluate("document.activeElement && document.activeElement.matches('.pwa-argyle-input')"),
                  'the type box did not take focus')

            # 7. Closing the overlay ends everything.
            mic.click()
            wait_state('listening')
            close()
            wait_state('idle')
            check(released(), 'closing the overlay left the microphone open')

            # 8. A long press is just a tap: it opens once, listening; no selection menu to latch onto.
            opened = page.evaluate("""async () => {
                let opens = 0; const real = PwaArgyle.open;
                PwaArgyle.open = (...a) => { opens++; return real(...a); };
                const orb = document.getElementById('tab-argyle');
                const r = orb.getBoundingClientRect();
                const at = {bubbles: true, clientX: r.x + r.width / 2, clientY: r.y + r.height / 2,
                            pointerId: 7, isPrimary: true, pointerType: 'touch'};
                orb.dispatchEvent(new PointerEvent('pointerdown', at));
                await new Promise(res => setTimeout(res, 700));
                orb.dispatchEvent(new PointerEvent('pointerup', at));
                orb.dispatchEvent(new MouseEvent('click', {bubbles: true, detail: 1, clientX: at.clientX, clientY: at.clientY}));
                await new Promise(res => setTimeout(res, 300));
                PwaArgyle.open = real;
                return opens;
            }""")
            overlay.wait_for(state='visible')
            check(opened == 1, f'a long press opened the overlay {opened} times')
            wait_state('listening')
            styles = page.evaluate("""() => ['#tab-argyle', '#pwa-argyle-overlay .pwa-argyle-mic'].map(s => {
                const c = getComputedStyle(document.querySelector(s));
                return c.userSelect || c.webkitUserSelect; })""")
            check(styles == ['none', 'none'], f'the orb and mic must not start a text selection: {styles}')
            close()

            # 9. Keyboard activation opens ready to type, not listening.
            page.locator('#tab-argyle').focus()
            page.keyboard.press('Enter')
            overlay.wait_for(state='visible')
            page.wait_for_timeout(500)
            check(state() == 'idle', f'Enter on the orb started listening: {state()}')
            check(page.evaluate("document.activeElement && document.activeElement.matches('.pwa-argyle-input')"),
                  'Enter on the orb did not focus the type box')

            # 10. Household switch off: the answer does not reopen the mic.
            SWITCH['voice_conversation_mode'] = False
            mic.click()
            wait_state('listening')
            speak()
            page.locator('#pwa-argyle-overlay .pwa-argyle-reply-body').get_by_text('Soccer is at four.').wait_for(timeout=8000)
            starts = counts['start']
            wait_state('idle', 6000)
            page.wait_for_timeout(600)
            check(state() == 'idle' and counts['start'] == starts, 'the switch was off but the mic reopened')
            SWITCH['voice_conversation_mode'] = True
            close()

            # 11. The Argyle chat in Messages pauses and continues through the same client.
            page.evaluate('ChauffeurPhoneVoice.start()')
            wait_state('listening')
            speak()
            page.wait_for_function("() => ChauffeurPhoneVoice.response?.reply === 'Soccer is at four.'", timeout=8000)
            wait_state('listening', 8000)
            page.evaluate('ChauffeurPhoneVoice.stop(false)')
            wait_state('idle')
            page.evaluate("setView('myday')")
            page.locator('#tab-argyle').wait_for(state='visible')

            # 12. One audio context, unlocked by the tap, serves the whole conversation:
            #     follow-up turns get no tap, and Safari will not start a new context then.
            page.locator('#tab-argyle').click()
            overlay.wait_for(state='visible')
            wait_state('listening')
            made = page.evaluate('window.audioContexts')
            speak()
            page.locator('#pwa-argyle-overlay .pwa-argyle-reply-body').get_by_text('Soccer is at four.').wait_for(timeout=8000)
            wait_state('listening', 8000)
            speak()
            page.wait_for_function("() => ChauffeurPhoneVoice.state === 'thinking' || ChauffeurPhoneVoice.state === 'speaking'",
                                   timeout=4000)
            wait_state('listening', 8000)
            check(page.evaluate('window.audioContexts') == made,
                  f"follow-up turns made new audio contexts: {page.evaluate('window.audioContexts')} vs {made}")
            close()

            # 13. Silence that cannot be measured is not silence: with the context
            #     stuck suspended, listening never times out; Done still sends.
            page.evaluate("window.audioSuspended = true; window.audioContexts = 0;")
            page.evaluate("ChauffeurPhoneVoice.releaseAudioContext && ChauffeurPhoneVoice.releaseAudioContext()")
            page.locator('#tab-argyle').click()
            overlay.wait_for(state='visible')
            wait_state('listening')
            page.wait_for_timeout(2200)    # past NO_SPEECH_MS (1500)
            check(state() == 'listening', f'a suspended context ended the turn as silence: {state()}')
            transcribed = CALLS['transcribe']
            mic.click()
            page.locator('#pwa-argyle-overlay .pwa-argyle-reply-body').get_by_text('Soccer is at four.').wait_for(timeout=8000)
            check(CALLS['transcribe'] == transcribed + 1, 'Done did not send while the context was suspended')
            page.evaluate("window.audioSuspended = false")
            close()

            errors = [e for e in browser.errors if 'favicon' not in e]
            check(not errors, f'JavaScript errors: {errors}')
        print('PASS: tap listens, pause sends, answer reopens the mic, silence/sign-off/type box/close/switch end it, '
              'long press is a tap, Enter types, Messages continues; fixtures only.')
        print('Screenshots:', shots)
    finally:
        served.stop()


if __name__ == '__main__':
    main()

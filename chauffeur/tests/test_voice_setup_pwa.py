"""static/app_voice.js's voice-setup client, actually run under node (plan Task 6).

What a person does on the phone: Start posts the enrollment, Record then Done
uploads one answer with the step token the server issued, an accepted answer
advances "1 of 5" to "2 of 5" and takes the new token, a retry keeps the step,
and done shows the finish buttons with the recorder released.

Run from chauffeur/:  python tests/test_voice_setup_pwa.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


SCRIPT = r'''
const fs = require('fs'), vm = require('vm'), assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[2], 'utf8');
const els = {};
const element = id => els[id] || (els[id] = {
  id, textContent: '', disabled: false, hidden: false, open: false, style: {display: ''},
  classList: {_c: new Set(), add(c) { this._c.add(c); }, remove(c) { this._c.delete(c); },
              toggle(c, on) { on === undefined ? (this._c.has(c) ? this._c.delete(c) : this._c.add(c)) : (on ? this._c.add(c) : this._c.delete(c)); },
              contains(c) { return this._c.has(c); }},
  setAttribute() {}, getAttribute() { return null; }, addEventListener() {}, appendChild() {},
  showModal() { this.open = true; }, close() { this.open = false; },
  querySelector() { return null; },
});
const calls = [];
let replies = [];
let recorders = [];
class MediaRecorder {
  constructor(stream, opts) { this.stream = stream; this.mimeType = opts.mimeType; this.state = 'inactive'; recorders.push(this); }
  static isTypeSupported(t) { return t === 'audio/webm'; }
  start() { this.state = 'recording'; }
  stop() { this.state = 'inactive'; this.onstop && this.onstop(); }
}
class Audio { constructor(src) { this.src = src; } play() { setTimeout(() => this.onended && this.onended(), 0); return Promise.resolve(); } pause() {} }
class Blob { constructor(parts, opts) { this.type = opts.type; this.size = 1; } }
const ctx = {
  console, setTimeout, clearTimeout, setInterval, clearInterval, Promise, JSON, Error, URL: {createObjectURL: () => 'blob:x', revokeObjectURL() {}},
  performance: {now: () => 0}, crypto: {randomUUID: () => 'req-1'},
  MediaRecorder, Audio, Blob, AbortController: class { abort() {} },
  navigator: {mediaDevices: {getUserMedia: async () => ({getTracks: () => [{stop() {}, addEventListener() {}}]})}},
  document: {getElementById: element, hidden: false, addEventListener() {}, createElement: () => element('tmp' + Math.random())},
  memberToken: () => 'tok', showGlobalAlert: m => calls.push(['alert', m]), promptConfirm: async () => true,
  isSecureContext: true, self: 1, top: 1, location: {search: ''}, URLSearchParams,
  fetch: async (url, opts) => {
    calls.push([url, opts]);
    const reply = replies.shift() || {ok: true, body: {}};
    return {ok: reply.ok !== false, status: reply.status || 200, headers: {get: () => 'audio/mpeg'},
            json: async () => reply.body, blob: async () => new Blob([], {type: 'audio/mpeg'})};
  },
};
ctx.window = ctx; ctx.self = ctx; ctx.top = ctx; ctx.addEventListener = () => {}; ctx.removeEventListener = () => {};
vm.runInNewContext(source, ctx);
const S = ctx.ChauffeurVoiceSetup;
assert.ok(S, 'ChauffeurVoiceSetup is not exported');

(async () => {
  replies = [{body: {enrollment_id: 'e1', step: 1, total: 5, question: 'Tell me about your day so far, for about ten seconds.', token: 't1'}}];
  await S.open();
  await S.start();
  const start = calls.find(c => String(c[0]).endsWith('api/app-voice/enroll') && c[1].method === 'POST');
  assert.ok(start, 'Start did not post the enrollment');
  assert.equal(start[1].headers['X-Member-Token'], 'tok');
  assert.equal(S.state.token, 't1');
  assert.equal(element('pwa-voice-setup-step').textContent, '1 of 5');
  assert.ok(element('pwa-voice-setup-question').textContent.includes('your day'));
  // The question is fetched as speech and played before Record is enabled.
  assert.ok(calls.some(c => String(c[0]).includes('api/app-voice/enroll/e1/speech')), 'the question was not read aloud');
  await new Promise(r => setTimeout(r, 5));
  assert.equal(element('pwa-voice-setup-record').disabled, false, 'Record stayed disabled after playback');

  // Record, then Done: one upload with the step token.
  replies = [{body: {status: 'accepted', message: 'Got it.', step: 2, question: 'What is coming up for the family this week?', token: 't2'}}];
  await S.record();
  assert.equal(recorders.length, 1, 'no recorder was started');
  recorders[0].ondataavailable({data: {size: 10}});
  await S.done();
  await new Promise(r => setTimeout(r, 5));
  const upload = calls.find(c => String(c[0]).includes('api/app-voice/enroll/e1/audio'));
  assert.ok(upload, 'Done did not upload the answer');
  assert.equal(upload[1].headers['X-Voice-Step-Token'], 't1', 'the upload did not carry the step token');
  assert.equal(S.state.token, 't2'); assert.equal(S.state.step, 2);
  assert.equal(element('pwa-voice-setup-step').textContent, '2 of 5');
  assert.ok(element('pwa-voice-setup-question').textContent.includes('this week'));

  // A retry keeps the step and the new token the server returned.
  replies = [{body: {status: 'retry', message: 'A little longer, please.', step: 2, question: 'What is coming up for the family this week?', token: 't2b'}}];
  await S.record(); recorders[1].ondataavailable({data: {size: 10}}); await S.done();
  await new Promise(r => setTimeout(r, 5));
  assert.equal(S.state.step, 2); assert.equal(S.state.token, 't2b');
  assert.ok(element('pwa-voice-setup-status').textContent.includes('longer'));

  // Done: finish buttons shown, recorder released.
  replies = [{body: {status: 'done', message: 'Saved. Your speakers will each check it the first time.', step: 5}}];
  await S.record(); recorders[2].ondataavailable({data: {size: 10}}); await S.done();
  await new Promise(r => setTimeout(r, 5));
  assert.equal(S.state.phase, 'finished');
  assert.equal(element('pwa-voice-setup-finish').hidden, false, 'the finish buttons are hidden after done');
  assert.equal(S.recorder, null, 'the recorder was not released');
  // A child start sends the parent's PIN to the server and never shows it.
  replies = [{body: {enrollment_id: 'e2', step: 1, total: 5, question: 'q', token: 'c1'}}];
  await S.start('p1', '1234');
  const childStart = calls.filter(c => String(c[0]).endsWith('api/app-voice/enroll') && c[1].method === 'POST').pop();
  assert.deepEqual(JSON.parse(childStart[1].body), {parent_id: 'p1', parent_pin: '1234'});
  assert.ok(!JSON.stringify(Object.values(els).map(e => e.textContent)).includes('1234'), 'the PIN reached the screen');
  console.log('OK');
})().catch(e => { console.error(e); process.exit(1); });
'''


def scenario_the_phone_setup_client_walks_five_answers():
    node = shutil.which('node')
    if not node:
        print("  skip  node is not installed")
        return
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as fh:
        fh.write(SCRIPT)
        path = fh.name
    try:
        out = subprocess.run([node, path, os.path.join(STATIC, 'app_voice.js')], capture_output=True, text=True,
                             encoding='utf-8', errors='replace', timeout=60)
        check(out.returncode == 0 and 'OK' in out.stdout, f"voice setup client: {out.stderr[-1200:]}")
    finally:
        os.unlink(path)


def scenario_the_profile_sheet_offers_voice_setup():
    src = open(os.path.join(STATIC, 'pwa_shell.js'), encoding='utf-8').read()
    check("'Set up my voice'" in src or '"Set up my voice"' in src, 'the profile sheet has no Set up my voice')
    check('ChauffeurVoiceSetup' in src, 'the profile sheet does not open the setup client')
    check('Delete my voice' in src, 'the profile sheet has no Delete my voice')
    tpl = os.path.join(os.path.dirname(STATIC), 'templates', 'components', 'pwa_shell.html')
    html = open(tpl, encoding='utf-8').read()
    for id_ in ('pwa-voice-setup', 'pwa-voice-setup-step', 'pwa-voice-setup-question', 'pwa-voice-setup-record',
                'pwa-voice-setup-done', 'pwa-voice-setup-finish', 'pwa-voice-setup-status'):
        check(f'id="{id_}"' in html, f'the setup dialog lacks #{id_}')


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} voice setup client scenarios passed")

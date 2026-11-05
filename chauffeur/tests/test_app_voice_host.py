"""The phone's voice turn takes a host (PWA reimagined slice 2, task 2), run
in a real DOM.

Pinned shapes (static/app_voice.js sets window.ChauffeurPhoneVoice):
  * `ChauffeurPhoneVoice.start({ host })` with
    `host = { status(label, state), transcript(text), reply(text, meta),
    channelId(), isOpen() }` runs the turn in host mode: no
    `setView('messages')`, no `openChannel`; `status()` goes to
    `host.status(label, state)`; the recognized transcript goes to
    `host.transcript`; the `/run` reply goes to `host.reply(reply, meta)`;
    `valid()` holds while `host.isOpen()` (the `activeChannelId` check is
    skipped); `dispatch` skips `refreshThread()` when `currentView !==
    'messages'`; the `channel_id` posted to `/api/app-voice/start` is
    `host.channelId()`.
  * `done()` and `stop()` work in host mode; `stop()` cancels the server turn
    and ends with `host.status('', 'idle')`; the host is cleared after it.
  * Without a host nothing changes (thread mode: setView + openChannel,
    `#phone-voice-status` written).
  * Microphone startup regressions: 'listening' reaches the host only once the
    MediaRecorder has started ('starting' before it); `done()` before then
    (a premature Done call) ends the turn with a /cancel and a label
    saying to tap the microphone again, and the late microphone never records; `stop()`
    from 'starting' clears the host as it does from 'listening'.

The harness drives the HA recorder path, never the browser probe: the page URL
carries no `voice_probe=browser`, `window.SpeechRecognition` is undefined, and
a fake MediaRecorder (isTypeSupported -> true) emits one 1200-byte audio/webm
Blob then `onstop` when stopped. jsdom has no `isSecureContext`, so the
harness defines it true; `pretendToBeVisual` keeps `document.hidden` false.

Run from chauffeur/ with HA_BASE_URL unset:  python tests/test_app_voice_host.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_app_voice_host_'))

SCRATCH = tempfile.mkdtemp(prefix='chauffeur_app_voice_host_run_')
VOICE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'app_voice.js')

TRANSCRIPT = 'Can Grandma take Kate Thursday?'
REPLY = 'Grandma Ruth is free Thursday at 5:10.'


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


HARNESS = r"""
const fs = require('fs');
const { JSDOM, VirtualConsole } = require('jsdom');
const [,, voicePath] = process.argv;
const src = fs.readFileSync(voicePath, 'utf8');
const sleep = ms => new Promise(r => setTimeout(r, ms));
const TRANSCRIPT = 'Can Grandma take Kate Thursday?';
const REPLY = 'Grandma Ruth is free Thursday at 5:10.';
const THREAD_DOM = '<div id="phone-voice-panel" class="hidden">'
  + '<span id="phone-voice-status"></span><span id="phone-voice-transcript"></span>'
  + '<button id="phone-voice-done" class="hidden"></button><button id="phone-voice-stop" class="hidden"></button>'
  + '<button id="phone-voice-play" class="hidden"></button><button id="phone-voice-reply" class="hidden"></button>'
  + '</div><button id="phone-voice-mic"></button>';

const unhandled = [];
process.on('unhandledRejection', e => unhandled.push(String(e && e.stack || e)));

async function waitFor(pred, ms) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { if (pred()) return true; await sleep(10); }
  return pred();
}

function fresh({ threadDom = false, isOpen = () => true, deferGum = false,
                 analyser = false, continuation = false, playback = 'ended', speech = false } = {}) {
  const errors = [];
  const vc = new VirtualConsole();
  vc.on('jsdomError', e => errors.push(String(e && e.message || e)));
  const html = '<!doctype html><html><body>' + (threadDom ? THREAD_DOM : '') + '</body></html>';
  const dom = new JSDOM(html, { url: 'https://localhost/app', runScripts: 'outside-only',
    pretendToBeVisual: true, virtualConsole: vc });
  const w = dom.window;
  const log = { setView: [], openChannel: [], refreshThread: 0, alerts: [], fetches: [], gum: 0,
    recorder: [], host: [], trace: [], statusTextAtListening: null };
  Object.defineProperty(w, 'isSecureContext', { value: true, configurable: true });
  w.memberToken = () => 'tok';
  w.currentView = 'myday';
  w.activeChannelId = null;
  w.selectedMemberId = 'parent';
  w.apiBase = '';
  w.setView = v => { log.setView.push(v); w.currentView = v; };
  w.openChannel = async (id, channel) => { log.openChannel.push(id); w.activeChannelId = id; };
  w.refreshThread = async () => { log.refreshThread++; };
  w.showGlobalAlert = m => { log.alerts.push(String(m)); };
  w.SpeechRecognition = undefined;
  w.webkitSpeechRecognition = undefined;
  log.micLevel = 0; log.trackStops = 0; log.contextCloses = 0; log.playing = false; log.overlap = false;
  if (analyser) w.AudioContext = class {
    constructor() { this.state = 'running'; log.contextCreates = (log.contextCreates || 0) + 1; }
    createMediaStreamSource() { return {connect() {}, disconnect() {}}; }
    createAnalyser() { return {fftSize: 2048, disconnect() {},
      getFloatTimeDomainData(buf) { buf.fill(log.micLevel); }}; }
    resume() { return Promise.resolve(); }
    close() { this.state = 'closed'; log.contextCloses++; return Promise.resolve(); }
  };
  const track = { stop() { log.trackStops++; }, addEventListener() {} };
  const stream = { getTracks: () => [track] };
  // deferGum: getUserMedia stays pending until the case calls releaseGum(),
  // the window a real phone spends on the permission prompt / mic warm-up.
  let gumRelease = null;
  const gumGate = deferGum ? new Promise(r => { gumRelease = r; }) : null;
  const releaseGum = () => { if (gumRelease) gumRelease(); };
  Object.defineProperty(w.navigator, 'mediaDevices', { configurable: true,
    value: { getUserMedia: async () => { log.gum++; if (log.playing) log.overlap = true;
      if (gumGate) await gumGate; return stream; } } });
  w.MediaRecorder = class {
    constructor(s, opts) {
      this.stream = s; this.mimeType = (opts && opts.mimeType) || 'audio/webm'; this.state = 'inactive';
      this.ondataavailable = null; this.onstop = null; this.onerror = null; log.recorder.push('new');
    }
    static isTypeSupported() { return true; }
    start() { this.state = 'recording'; log.recorder.push('start'); }
    stop() {
      if (this.state === 'inactive') return;
      this.state = 'inactive'; log.recorder.push('stop');
      setTimeout(() => {
        if (this.ondataavailable) this.ondataavailable({ data: new w.Blob([new Uint8Array(1200)], { type: 'audio/webm' }) });
        if (this.onstop) this.onstop();
      }, 0);
    }
  };
  w.Audio = class {
    constructor(s) { this._src = s; this.onplaying = null; this.onended = null; this.onerror = null; }
    set src(v) { this._src = v; } get src() { return this._src; }
    pause() { log.playing = false; }
    play() {
      if (playback === 'reject') return Promise.reject(new Error('Playback denied'));
      setTimeout(() => {
        log.playing = true;
        if (this.onplaying) this.onplaying();
        if (playback !== 'manual') setTimeout(() => {
          log.playing = false;
          if (this.onended) this.onended();
        }, 20);
      }, 20);
      return Promise.resolve();
    }
  };
  w.URL.createObjectURL = () => 'blob:voice';
  w.URL.revokeObjectURL = () => {};
  const answers = {
    start: { request_id: 'r1', channel: { id: 'dm_argyle', member_ids: ['parent', 'argyle'] } },
    audio: { transcript: TRANSCRIPT },
    text: { transcript: TRANSCRIPT },
    run: { reply: REPLY, speech, speech_safe: !!speech, continue_conversation: continuation,
      channel_id: 'dm_argyle', request_id: 'r1' },
    cancel: { status: 'stopped' },
  };
  w.fetch = async (url, opts = {}) => {
    const u = String(url);
    const m = u.match(/api\/app-voice\/(.+)$/);
    const parts = (m ? m[1] : u).split('/');
    const kind = parts.length === 1 ? parts[0] : parts[parts.length - 1];
    let body = null;
    if (typeof opts.body === 'string') { try { body = JSON.parse(opts.body); } catch (_) { body = opts.body; } }
    log.fetches.push({ url: u, kind, method: opts.method || 'GET', body, t: Date.now() });
    const blob = async () => new w.Blob(['x'], { type: 'audio/mpeg' });
    if (kind === 'speech') return { ok: true, status: 200, json: async () => ({}), blob };
    const answer = answers[kind];
    if (!answer) return { ok: false, status: 404, json: async () => ({ detail: 'unscripted ' + u }), blob };
    return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(answer)), blob };
  };
  const host = {
    status(label, state) {
      log.host.push(['status', label === undefined ? null : label, state === undefined ? null : state]);
      log.trace.push({ state: state === undefined ? null : state, recording: log.recorder.includes('start') });
    },
    transcript(t) { log.host.push(['transcript', t]); },
    reply(t, meta) { log.host.push(['reply', t, meta === undefined ? null : JSON.parse(JSON.stringify(meta))]); },
    channelId() { return 'dm_argyle'; },
    isOpen() { return !!isOpen(); },
  };
  w.eval(src);
  if (!w.ChauffeurPhoneVoice) throw new Error('static/app_voice.js loaded but window.ChauffeurPhoneVoice is undefined');
  return { w, dom, log, host, errors, releaseGum };
}

const recording = log => log.recorder.includes('start');
const hostSaw = (log, state) => log.host.some(c => c[0] === 'status' && c[2] === state);
const kinds = log => log.fetches.map(f => f.kind);
const startBody = log => (log.fetches.find(f => f.kind === 'start') || {}).body || null;

function summary(env, extra) {
  const { log, errors } = env;
  return Object.assign({ setView: log.setView, openChannel: log.openChannel, refreshThread: log.refreshThread,
    alerts: log.alerts, fetchKinds: kinds(log), gum: log.gum, recorder: log.recorder, host: log.host,
    startBody: startBody(log), errors }, extra || {});
}

const CASES = {
  async host_mode_never_switches_views() {
    const env = fresh();
    env.w.ChauffeurPhoneVoice.start({ host: env.host });
    await waitFor(() => recording(env.log) || env.log.setView.length || env.log.fetches.length > 1, 2000);
    await sleep(100);
    const r = summary(env);
    env.w.ChauffeurPhoneVoice.stop(false);
    return r;
  },
  async transcript_and_reply_reach_the_host() {
    const env = fresh();
    const v = env.w.ChauffeurPhoneVoice;
    v.start({ host: env.host });
    await waitFor(() => recording(env.log), 2000);
    await sleep(30);
    const stateBeforeDone = v.state;
    v.done();
    await waitFor(() => {
      const st = env.log.host.filter(c => c[0] === 'status');
      return env.log.host.some(c => c[0] === 'reply') && st.length && st[st.length - 1][2] === 'idle';
    }, 3000);
    await sleep(150);
    return summary(env, { stateBeforeDone, currentView: env.w.currentView });
  },
  async stop_clears_the_host() {
    const env = fresh();
    const v = env.w.ChauffeurPhoneVoice;
    v.start({ host: env.host });
    await waitFor(() => recording(env.log), 2000);
    await sleep(30);
    const cancelsBefore = kinds(env.log).filter(k => k === 'cancel').length;
    v.stop();
    await sleep(50);
    const hostAfterStop = env.log.host.slice();
    v.status('x', 'listening');
    await sleep(20);
    const hostAfterLaterStatus = env.log.host.slice();
    return summary(env, { cancelsBefore, hostAfterStop, hostAfterLaterStatus });
  },
  async valid_holds_while_host_open() {
    const env = fresh({ isOpen: () => true });
    env.w.ChauffeurPhoneVoice.start({ host: env.host });
    await waitFor(() => recording(env.log), 2000);
    await sleep(800);   // a few watcher ticks
    return summary(env, { activeChannelId: env.w.activeChannelId, state: env.w.ChauffeurPhoneVoice.state,
      cancels: kinds(env.log).filter(k => k === 'cancel').length });
  },
  async closing_the_host_stops_the_turn() {
    let open = true;
    const env = fresh({ isOpen: () => open });
    env.w.ChauffeurPhoneVoice.start({ host: env.host });
    await waitFor(() => recording(env.log), 2000);
    await sleep(30);
    const cancelsBeforeClose = kinds(env.log).filter(k => k === 'cancel').length;
    const wasRecording = recording(env.log);
    const t0 = Date.now();
    open = false;
    await waitFor(() => env.log.fetches.some(f => f.kind === 'cancel' && f.t >= t0), 1500);
    const c = env.log.fetches.find(f => f.kind === 'cancel' && f.t >= t0);
    return summary(env, { cancelsBeforeClose, wasRecording, cancelAfterMs: c ? c.t - t0 : null,
      state: env.w.ChauffeurPhoneVoice.state });
  },
  async thread_mode_unchanged() {
    const env = fresh({ threadDom: true });
    const v = env.w.ChauffeurPhoneVoice;
    const d = env.w.document;
    v.start();
    await waitFor(() => recording(env.log), 2000);
    await sleep(30);
    const statusAtListening = d.getElementById('phone-voice-status').textContent;
    const doneShown = !d.getElementById('phone-voice-done').classList.contains('hidden');
    v.done();
    await waitFor(() => env.log.refreshThread > 0 && v.state === 'idle', 3000);
    await sleep(100);
    return summary(env, { statusAtListening, doneShown,
      transcriptText: d.getElementById('phone-voice-transcript').textContent,
      statusAtEnd: d.getElementById('phone-voice-status').textContent, state: v.state });
  },
  async listening_only_once_recording() {
    const env = fresh({ deferGum: true });
    const v = env.w.ChauffeurPhoneVoice;
    v.start({ host: env.host });
    await waitFor(() => env.log.gum > 0, 2000);
    await sleep(100);   // getUserMedia is still pending: the mic is not open
    const hostBeforeMic = env.log.host.slice();
    const stateBeforeMic = v.state;
    const recorderBeforeMic = env.log.recorder.slice();
    env.releaseGum();
    await waitFor(() => recording(env.log) && hostSaw(env.log, 'listening'), 2000);
    await sleep(30);
    const r = summary(env, { hostBeforeMic, stateBeforeMic, recorderBeforeMic, trace: env.log.trace.slice() });
    v.stop(false);
    return r;
  },
  async early_release_cancels_the_turn() {
    const env = fresh({ deferGum: true });
    const v = env.w.ChauffeurPhoneVoice;
    v.start({ host: env.host });
    await waitFor(() => env.log.gum > 0, 2000);
    await sleep(30);   // the turn exists (start answered); the mic is still pending
    const stateAtRelease = v.state;
    const cancelsBefore = kinds(env.log).filter(k => k === 'cancel').length;
    const t0 = Date.now();
    v.done();          // Done was called before Listening… appeared
    await waitFor(() => env.log.fetches.some(f => f.kind === 'cancel' && f.t >= t0), 900);
    const c = env.log.fetches.find(f => f.kind === 'cancel' && f.t >= t0);
    const hostAfterDone = env.log.host.slice();
    env.releaseGum();  // the mic arrives late; it must not start recording
    await sleep(300);
    const r = summary(env, { stateAtRelease, cancelsBefore, cancelAfterMs: c ? c.t - t0 : null,
      hostAfterDone, stateAtEnd: v.state });
    v.stop(false);
    return r;
  },
  async cancel_during_start_ends_the_turn() {
    const env = fresh({ deferGum: true });
    const v = env.w.ChauffeurPhoneVoice;
    v.start({ host: env.host });
    await waitFor(() => env.log.gum > 0, 2000);
    await sleep(30);
    const stateAtStop = v.state;
    const cancelsBefore = kinds(env.log).filter(k => k === 'cancel').length;
    v.stop(false);
    await sleep(50);
    const hostAfterStop = env.log.host.slice();
    env.releaseGum();
    await sleep(100);
    v.status('x', 'listening');
    await sleep(20);
    const hostAfterLaterStatus = env.log.host.slice();
    return summary(env, { stateAtStop, cancelsBefore, hostAfterStop, hostAfterLaterStatus });
  },
  async pause_sends_and_silence_does_not() {
    const env = fresh({analyser: true});
    const v = env.w.ChauffeurPhoneVoice;
    v.PAUSE_MS = 100; v.NO_SPEECH_MS = 300;
    await v.start({host: env.host});
    await waitFor(() => v.state === 'idle', 1200);
    const silent = {state: v.state, uploaded: kinds(env.log).includes('audio'),
      released: !v.stream && !v.recorder && !v.audioContext && !v.silenceTimer,
      cancelled: kinds(env.log).includes('cancel'), closed: env.log.contextCloses};
    await v.start({host: env.host});
    env.log.micLevel = v.SPEECH_RMS * 2;
    await sleep(150);
    env.log.micLevel = 0;
    await waitFor(() => v.response && v.state === 'idle', 1500);
    const r = summary(env, {silent, uploads: kinds(env.log).filter(k => k === 'audio').length,
      state: v.state, closed: env.log.contextCloses, stops: env.log.trackStops});
    v.stop(false); return r;
  },
  async continuation_waits_for_playback() {
    const env = fresh({analyser: true, continuation: true, speech: 'The answer.', playback: 'manual'});
    const v = env.w.ChauffeurPhoneVoice;
    await v.start({host: env.host}); v.done();
    await waitFor(() => v.state === 'speaking', 1500);
    const context = v.audioContext;
    const during = {state: v.state, starts: kinds(env.log).filter(k => k === 'start').length,
      released: !v.stream && !v.recorder && !v.source && !v.analyser, contextHeld: !!context};
    env.log.playing = false; v.audio.onended();
    await waitFor(() => v.state === 'listening', 1500);
    const r = summary(env, {during, state: v.state, overlap: env.log.overlap,
      starts: kinds(env.log).filter(k => k === 'start').length, hostPreserved: v.host === env.host,
      responsePreserved: v.response?.reply === REPLY, contextReused: context === v.audioContext,
      contextCreates: env.log.contextCreates});
    v.stop(false); return r;
  },
  async continuation_after_playback_failure_and_display_only() {
    const results = [];
    for (const speech of ['The answer.', false]) {
      const env = fresh({continuation: true, speech, playback: 'reject'});
      const v = env.w.ChauffeurPhoneVoice;
      await v.start({host: env.host}); v.done();
      await waitFor(() => kinds(env.log).filter(k => k === 'start').length === 2 && v.state === 'listening', 1500);
      results.push(summary(env, {state: v.state, starts: kinds(env.log).filter(k => k === 'start').length,
        hostPreserved: v.host === env.host}));
      v.stop(false);
    }
    return {results};
  },
  async messages_continues_and_visibility_stops() {
    const env = fresh({threadDom: true, analyser: true, continuation: true, speech: 'The answer.'});
    const v = env.w.ChauffeurPhoneVoice;
    await v.start(); v.done();
    await waitFor(() => kinds(env.log).filter(k => k === 'start').length === 2 && v.state === 'listening', 1500);
    const continued = {state: v.state, starts: kinds(env.log).filter(k => k === 'start').length};
    Object.defineProperty(env.w.document, 'hidden', {configurable: true, value: true});
    env.w.document.dispatchEvent(new env.w.Event('visibilitychange'));
    await sleep(100);
    return summary(env, {continued, state: v.state,
      released: !v.stream && !v.recorder && !v.audioContext && !v.audio && !v.silenceTimer});
  },
};

(async () => {
  const out = {};
  for (const [name, fn] of Object.entries(CASES)) {
    try { out[name] = await fn(); }
    catch (e) { out[name] = { error: String(e && e.stack || e) }; }
  }
  out.__unhandled = unhandled;
  process.stdout.write(JSON.stringify(out) + '\n');
  process.exit(0);
})();
"""

_RESULT = {}


def _run():
    if 'data' in _RESULT:
        return _RESULT['data']
    node = shutil.which('node')
    if not node:
        print('  skip  node is not installed — the voice turn was not run')
        _RESULT['data'] = None
        return None
    have = subprocess.run([node, '-e', "require.resolve('jsdom')"], capture_output=True, text=True, cwd=SCRATCH)
    if have.returncode != 0:
        print('  skip  jsdom not resolvable')
        _RESULT['data'] = None
        return None
    harness = os.path.join(SCRATCH, 'harness.js')
    with open(harness, 'w', encoding='utf-8') as f:
        f.write(HARNESS)
    proc = subprocess.run([node, harness, VOICE], capture_output=True, text=True, encoding='utf-8',
                          errors='replace', cwd=SCRATCH, timeout=120)
    check(proc.returncode == 0, f"the harness threw:\n{proc.stderr[-2000:]}")
    _RESULT['data'] = json.loads(proc.stdout.strip().splitlines()[-1])
    return _RESULT['data']


def _case(name):
    got = _run()
    if got is None:
        return None
    r = got[name]
    check('error' not in r, f"{name}: {r.get('error')}")
    check(not r.get('errors'), f"{name}: the page logged errors: {r.get('errors')}")
    check(not got.get('__unhandled'), f"unhandled rejections: {got.get('__unhandled')}")
    return r


def _statuses(r):
    return [c for c in r['host'] if c[0] == 'status']


def scenario_host_mode_never_switches_views():
    r = _case('host_mode_never_switches_views')
    if r is None:
        return
    check(r['startBody'] is not None, f"the turn posted /api/app-voice/start: {r['fetchKinds']}")
    check(r['setView'] == [], f"host mode never calls setView: {r['setView']}")
    check(r['openChannel'] == [], f"host mode never calls openChannel: {r['openChannel']}")
    check(any(c[2] == 'listening' for c in _statuses(r)),
          f"host.status(label, 'listening') was called: host calls {r['host']}")
    check(r['startBody'].get('channel_id') == 'dm_argyle',
          f"the start POST's channel_id is host.channelId(): {r['startBody']}")
    check(r['alerts'] == [], f"no alert in host mode: {r['alerts']}")


def scenario_transcript_and_reply_reach_the_host():
    r = _case('transcript_and_reply_reach_the_host')
    if r is None:
        return
    check(r['stateBeforeDone'] == 'listening', f"the turn reached listening before done(): {r['stateBeforeDone']!r} {r['fetchKinds']}")
    check('audio' in r['fetchKinds'] and 'run' in r['fetchKinds'],
          f"done() sent the recording and ran the turn: {r['fetchKinds']}")
    check(['transcript', TRANSCRIPT] in r['host'], f"host.transcript got the recognized text: host calls {r['host']}")
    replies = [c for c in r['host'] if c[0] == 'reply']
    check(len(replies) == 1 and replies[0][1] == REPLY, f"host.reply got the /run reply once: host calls {r['host']}")
    meta = replies[0][2]
    check(isinstance(meta, dict) and meta.get('continue_conversation') is False and 'speech_safe' in meta,
          f"host.reply's meta carries continue_conversation and speech_safe: {meta}")
    check(r['refreshThread'] == 0, f"refreshThread is skipped when currentView is {r['currentView']!r}: {r['refreshThread']} calls")
    check(r['setView'] == [] and r['openChannel'] == [], f"no view switch on the way: {r['setView']} {r['openChannel']}")
    st = [c[2] for c in _statuses(r)]
    check('thinking' in st, f"host.status saw 'thinking': {st}")
    check(st and st[-1] == 'idle', f"the host's last status state is 'idle': {st}")
    i_think = st.index('thinking')
    check('idle' in st[i_think:], f"'idle' follows 'thinking': {st}")


def scenario_stop_clears_the_host():
    r = _case('stop_clears_the_host')
    if r is None:
        return
    check(r['cancelsBefore'] == 0, f"no cancel before stop(): {r['fetchKinds']}")
    check('cancel' in r['fetchKinds'], f"stop() cancels the server turn: {r['fetchKinds']}")
    after = r['hostAfterStop']
    check(after, f"the host heard from the turn at all: {after}")
    check(after[-1] == ['status', '', 'idle'], f"stop() ends with host.status('', 'idle'): last host call {after[-1] if after else None}; all {after}")
    check(r['hostAfterLaterStatus'] == after,
          f"a status() after stop writes nothing to the host: {r['hostAfterLaterStatus'][len(after):]}")


def scenario_valid_holds_while_host_open():
    r = _case('valid_holds_while_host_open')
    if r is None:
        return
    check(r['openChannel'] == [] and r['activeChannelId'] is None,
          f"activeChannelId stays null in host mode: openChannel {r['openChannel']} activeChannelId {r['activeChannelId']!r}")
    check(any(c[2] == 'listening' for c in _statuses(r)), f"the host saw listening: host calls {r['host']}")
    check(r['gum'] == 1 and 'start' in r['recorder'], f"the turn proceeded to the microphone: gum {r['gum']} recorder {r['recorder']}")
    check(r['cancels'] == 0, f"the watcher kept the turn while host.isOpen() is true: {r['fetchKinds']}")
    check(r['state'] == 'listening', f"still listening after several watcher ticks: {r['state']!r}")


def scenario_closing_the_host_stops_the_turn():
    r = _case('closing_the_host_stops_the_turn')
    if r is None:
        return
    check(r['wasRecording'], f"the turn was recording before the host closed: {r['recorder']}")
    check(r['cancelsBeforeClose'] == 0, f"no cancel while the host was open: {r['fetchKinds']}")
    check(r['cancelAfterMs'] is not None, f"host.isOpen() false stops the turn (a /cancel): {r['fetchKinds']}")
    check(r['cancelAfterMs'] <= 900, f"the watcher stopped it within ~600 ms: {r['cancelAfterMs']} ms")
    check(r['state'] == 'idle', f"the turn is idle after the watcher stopped it: {r['state']!r}")


def scenario_thread_mode_unchanged():
    r = _case('thread_mode_unchanged')
    if r is None:
        return
    check(r['setView'] == ['messages'], f"thread mode calls setView('messages'): {r['setView']}")
    check(r['openChannel'] == ['dm_argyle'], f"thread mode opens the turn's channel: {r['openChannel']}")
    check(r['startBody'] is not None and r['startBody'].get('channel_id') is None,
          f"no thread channel open -> channel_id null as today: {r['startBody']}")
    check(r['statusAtListening'] == 'Listening — press Done when you finish.',
          f"#phone-voice-status is written: {r['statusAtListening']!r}")
    check(r['doneShown'], "#phone-voice-done shows while listening")
    check(r['transcriptText'] == TRANSCRIPT, f"#phone-voice-transcript carries the text: {r['transcriptText']!r}")
    check(r['refreshThread'] == 1, f"dispatch refreshes the thread in thread mode: {r['refreshThread']}")
    check(r['state'] == 'idle', f"the turn ends idle after the reply plays: {r['state']!r} {r['statusAtEnd']!r}")


def scenario_listening_only_once_recording():
    """'listening' tells the host the mic is open (the overlay's wave, the
    orb's release meaning send); it must not arrive while getUserMedia is
    still pending. Before that the host may hear 'starting'."""
    r = _case('listening_only_once_recording')
    if r is None:
        return
    check(r['gum'] == 1, f"the turn asked for the microphone: gum {r['gum']} {r['fetchKinds']}")
    check(r['recorderBeforeMic'] == [] or 'start' not in r['recorderBeforeMic'],
          f"no recorder started before getUserMedia resolved: {r['recorderBeforeMic']}")
    before = [c[2] for c in r['hostBeforeMic'] if c[0] == 'status']
    check('listening' not in before,
          f"the host heard 'listening' before the microphone opened (getUserMedia still pending): {r['hostBeforeMic']}")
    check(r['stateBeforeMic'] != 'listening',
          f"ChauffeurPhoneVoice.state is 'listening' before the microphone opened: {r['stateBeforeMic']!r}")
    check('start' in r['recorder'], f"the recorder started once getUserMedia resolved: {r['recorder']}")
    listening = [t for t in r['trace'] if t['state'] == 'listening']
    check(listening, f"the host heard 'listening' once recording: host calls {r['host']}")
    check(all(t['recording'] for t in listening),
          f"every 'listening' reached the host only after MediaRecorder.start(): trace {r['trace']}")


def scenario_early_release_cancels_the_turn():
    """Calling Done before Listening appears cancels safely; the late
    microphone never records and the recovery label requires no hold."""
    r = _case('early_release_cancels_the_turn')
    if r is None:
        return
    check(r['gum'] == 1, f"the turn reached the microphone request: gum {r['gum']} {r['fetchKinds']}")
    check(r['cancelsBefore'] == 0, f"no cancel before the early release: {r['fetchKinds']}")
    check(r['cancelAfterMs'] is not None,
          f"done() before the mic opened cancels the server turn (/api/app-voice/<id>/cancel): {r['fetchKinds']} state at release {r['stateAtRelease']!r}")
    check(r['cancelAfterMs'] <= 900, f"the cancel went out within 900 ms: {r['cancelAfterMs']} ms")
    st = _statuses(r)
    check(st, f"the host heard from the turn at all: {r['host']}")
    label, state = st[-1][1] or '', st[-1][2]
    check(state == 'error' or (state == 'idle' and label.strip()),
          f"the host's last status is an error (or idle with a label), not a live turn: {st[-1]}; all {st}")
    check('tap the microphone' in label.lower() and 'hold' not in label.lower(),
          f"the host's last label tells the person to tap the microphone again: {label!r}")
    check('start' not in r['recorder'], f"the late microphone never started a recorder: {r['recorder']}")
    check('audio' not in r['fetchKinds'], f"no audio was posted after an early release: {r['fetchKinds']}")
    check(r['stateAtEnd'] == 'idle', f"the turn is idle after the early release: {r['stateAtEnd']!r}")


def scenario_cancel_during_start_ends_the_turn():
    """stop(false) while the mic is still starting (the overlay closed during
    startup) cancels the server turn and clears the host, as from listening."""
    r = _case('cancel_during_start_ends_the_turn')
    if r is None:
        return
    check(r['stateAtStop'] in ('starting', 'listening'),
          f"the turn was mid-start when stopped: {r['stateAtStop']!r}")
    check(r['cancelsBefore'] == 0, f"no cancel before stop(): {r['fetchKinds']}")
    check('cancel' in r['fetchKinds'], f"stop() during start cancels the server turn: {r['fetchKinds']}")
    after = r['hostAfterStop']
    check(after, f"the host heard from the turn at all: {after}")
    check(after[-1] == ['status', '', 'idle'],
          f"stop() ends with host.status('', 'idle'): last host call {after[-1] if after else None}; all {after}")
    check(r['hostAfterLaterStatus'] == after,
          f"nothing reaches the host after stop (late mic, later status): {r['hostAfterLaterStatus'][len(after):]}")
    check('start' not in r['recorder'], f"the late microphone never started a recorder: {r['recorder']}")
    check('audio' not in r['fetchKinds'], f"no audio was posted after stop: {r['fetchKinds']}")


def scenario_pause_sends_and_silence_does_not():
    r = _case('pause_sends_and_silence_does_not')
    if r is None:
        return
    check(r['silent'] == {'state': 'idle', 'uploaded': False, 'released': True, 'cancelled': True, 'closed': 1},
          f"no speech cancels without uploading and closes Web Audio: {r['silent']}")
    check(r['uploads'] == 1 and r['state'] == 'idle', f"a pause after speech sends exactly once: {r}")
    check(r['closed'] == 2 and r['stops'] == 2, f"both captures release their context and tracks: {r}")


def scenario_continuation_waits_for_playback():
    r = _case('continuation_waits_for_playback')
    if r is None:
        return
    check(r['during'] == {'state': 'speaking', 'starts': 1, 'released': True, 'contextHeld': True},
          f"the microphone stays closed until playback ends: {r['during']}")
    check(r['state'] == 'listening' and r['starts'] == 2 and not r['overlap'],
          f"playback ending starts exactly one fresh turn with no recording overlap: {r}")
    check(r['hostPreserved'] and r['responsePreserved'], 'the next turn keeps its host and displayed reply')
    check(r['contextReused'] and r['contextCreates'] == 1, 'follow-up turns reuse the unlocked context')


def scenario_continuation_after_playback_failure_and_display_only():
    r = _case('continuation_after_playback_failure_and_display_only')
    if r is None:
        return
    for item in r['results']:
        check(not item['errors'] and item['state'] == 'listening' and item['starts'] == 2 and item['hostPreserved'],
              f"failed speech and display-only replies both continue through the same host: {item}")
    check('speech' in r['results'][0]['fetchKinds'], 'the failed-playback case attempts speech')
    check('speech' not in r['results'][1]['fetchKinds'], 'a response without speech continues once displayed')


def scenario_messages_continues_and_visibility_stops():
    r = _case('messages_continues_and_visibility_stops')
    if r is None:
        return
    check(r['continued'] == {'state': 'listening', 'starts': 2}, f"Messages automatically continues: {r}")
    check(r['state'] == 'idle' and r['released'], f"leaving the app releases capture and playback: {r}")


SCENARIOS = [
    scenario_host_mode_never_switches_views,
    scenario_transcript_and_reply_reach_the_host,
    scenario_stop_clears_the_host,
    scenario_valid_holds_while_host_open,
    scenario_closing_the_host_stops_the_turn,
    scenario_thread_mode_unchanged,
    scenario_listening_only_once_recording,
    scenario_early_release_cancels_the_turn,
    scenario_cancel_during_start_ends_the_turn,
    scenario_pause_sends_and_silence_does_not,
    scenario_continuation_waits_for_playback,
    scenario_continuation_after_playback_failure_and_display_only,
    scenario_messages_continues_and_visibility_stops,
]

if __name__ == "__main__":
    failed = 0
    for fn in SCENARIOS:
        name = fn.__name__.replace('scenario_', '')
        try:
            fn()
            print(f"  ok  {name}")
        except Exception as e:
            failed += 1
            print(f"  FAIL  {name}: {e}")
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)

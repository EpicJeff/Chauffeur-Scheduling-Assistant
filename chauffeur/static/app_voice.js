/* Foreground personal Argyle voice. HA recorder path; disposable browser probe.
 * No wake word, biometric enrollment, or private answer sent to browser TTS. */
(() => {
    'use strict';
    const el = id => document.getElementById('phone-voice-' + id);
    const voice = {
        generation: 0, turn: null, stream: null, recorder: null, recognition: null,
        audio: null, audioUrl: null, timer: null, watcher: null, controller: null,
        state: 'idle', token: '', response: null, submitRecording: false,
        timings: [], started: 0, ended: 0, anchor: '',
        visibility() {
            const channel = typeof threadChannel === 'undefined' ? null : threadChannel;
            if (el('mic')) el('mic').style.display = channel?.kind === 'dm'
                && channel.member_ids?.includes('argyle') ? 'block' : 'none';
        },
        status(label, state = 'idle') {
            this.state = state;
            if (state === 'idle') { clearInterval(this.watcher); this.watcher = null; }
            el('panel')?.classList.remove('hidden');
            if (el('status')) el('status').textContent = label;
            el('done')?.classList.toggle('hidden', state !== 'listening');
            el('stop')?.classList.toggle('hidden', !['listening', 'thinking', 'speaking', 'starting'].includes(state));
            el('play')?.classList.add('hidden');
            el('reply')?.classList.add('hidden');
            if (el('mic')) {
                el('mic').disabled = state === 'starting';
                el('mic').setAttribute('aria-label', state === 'listening' ? 'Recording; press Done to send' : 'Talk to Argyle');
            }
        },
        url(suffix) { return (typeof apiBase === 'undefined' ? '' : apiBase) + 'api/app-voice/' + suffix; },
        valid(generation) {
            return generation === this.generation && !document.hidden && this.token === memberToken()
                && (!this.turn || typeof activeChannelId === 'undefined' || activeChannelId === this.turn.channel.id);
        },
        async json(suffix, body, signal) {
            const res = await fetch(this.url(suffix), {
                method: 'POST', headers: {'Content-Type': 'application/json', 'X-Member-Token': this.token},
                body: JSON.stringify(body || {}), signal
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || 'Voice could not finish. Try again or use text.');
            return data;
        },
        releaseCapture() {
            clearTimeout(this.timer); this.timer = null;
            const r = this.recorder; this.recorder = null;
            if (r && r.state !== 'inactive') { try { r.stop(); } catch (_) {} }
            const recognition = this.recognition; this.recognition = null;
            if (recognition) { try { recognition.abort(); } catch (_) {} }
            if (this.stream) this.stream.getTracks().forEach(t => t.stop());
            this.stream = null;
        },
        releaseAudio() {
            if (this.audio) {
                this.audio.pause(); this.audio.onended = null;
                this.audio.onplaying = null; this.audio.onerror = null; this.audio.src = '';
            }
            this.audio = null;
            if (this.audioUrl) URL.revokeObjectURL(this.audioUrl);
            this.audioUrl = null;
        },
        cancelServer(turn, token) {
            if (!turn) return;
            fetch(this.url(turn.request_id + '/cancel'), {method: 'POST', keepalive: true,
                headers: {'X-Member-Token': token}}).catch(() => {});
        },
        stop(show = true) {
            const active = this.state !== 'idle' || this.stream || this.audio;
            this.generation++;
            clearInterval(this.watcher); this.watcher = null;
            this.submitRecording = false;
            this.controller?.abort(); this.controller = null;
            this.releaseCapture(); this.releaseAudio();
            this.cancelServer(this.turn, this.token);
            this.turn = null; this.response = null;
            if (show && active) this.status('Stopped. Completed actions remain in your conversation.');
            else if (!show) { this.state = 'idle'; el('panel')?.classList.add('hidden'); }
        },
        async start() {
            this.stop(false);
            if (!memberToken()) {
                showGlobalAlert('Sign in on your personal device to talk to Argyle.'); return;
            }
            if (!window.isSecureContext || window.self !== window.top) {
                showGlobalAlert('Open the secure Chauffeur app outside Home Assistant ingress for voice.'); return;
            }
            this.token = memberToken();
            const generation = this.generation;
            const credential = this.token;
            const requestId = crypto.randomUUID ? crypto.randomUUID()
                : Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, '0')).join('');
            const ownChannel = typeof threadChannel !== 'undefined' && threadChannel?.kind === 'dm'
                && threadChannel.member_ids?.includes('argyle') ? threadChannel.id : null;
            this.status('Starting microphone…', 'starting');
            this.started = performance.now();
            this.ended = 0; this.anchor = 'recording ended / Done';
            if (el('transcript')) el('transcript').textContent = '';
            try {
                // Do not abort this request: a late start response must revoke
                // the exact turn it created after local cancellation.
                const turn = await this.json('start', {request_id: requestId, channel_id: ownChannel});
                if (!this.valid(generation)) { this.cancelServer(turn, credential); return; }
                this.turn = turn;
                const popup = document.getElementById('kiosk-chat-popup');
                if (popup) { popup.classList.add('hidden'); popup.classList.remove('flex'); }
                setView('messages');
                await openChannel(turn.channel.id, turn.channel);
                if (!this.valid(generation)) { this.cancelServer(turn, credential); return; }
                this.status('Listening — press Done when you finish.', 'listening');
                const browserProbe = new URLSearchParams(location.search).get('voice_probe') === 'browser';
                if (browserProbe) this.browser(generation);
                else await this.capture(generation);
            } catch (error) {
                if (generation !== this.generation) return;
                this.releaseCapture(); this.cancelServer(this.turn, credential);
                if (!this.turn && document.getElementById('thread-view')?.style.display !== 'flex')
                    showGlobalAlert(error.message || 'Voice could not start. You can still type.');
                this.status(error.name === 'NotAllowedError' ? 'Microphone access was denied. Allow it in Settings or use text.'
                    : (error.message || 'Microphone unavailable. You can still type.'));
            }
        },
        watch(generation) {
            this.watcher = setInterval(() => {
                if (!this.valid(generation)) this.stop(false);
            }, 300);
        },
        async capture(generation) {
            if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder || !MediaRecorder.isTypeSupported)
                throw new Error('Voice recording is unavailable on this browser. You can still type.');
            const stream = await navigator.mediaDevices.getUserMedia({audio: true});
            if (!this.valid(generation)) { stream.getTracks().forEach(t => t.stop()); return; }
            this.stream = stream;
            stream.getTracks().forEach(t => t.addEventListener('ended', () => {
                if (this.stream === stream) { this.stop(); this.status('Microphone interrupted. Tap to resume.'); }
            }));
            const format = ['audio/mp4', 'audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus']
                .find(type => MediaRecorder.isTypeSupported(type));
            if (!format) throw new Error('This microphone recording format is unavailable. You can still type.');
            const recorder = new MediaRecorder(stream, {mimeType: format});
            this.recorder = recorder;
            const chunks = [];
            let size = 0;
            recorder.ondataavailable = event => {
                size += event.data.size;
                if (size > 5000000) { this.stop(); this.status('Recording exceeded its limit. Try a shorter request.'); }
                else if (event.data.size) chunks.push(event.data);
            };
            recorder.onerror = () => { this.stop(); this.status('Recording failed. Tap to try again or use text.'); };
            recorder.onstop = () => {
                const submit = this.submitRecording && this.valid(generation);
                this.submitRecording = false;
                this.recorder = null;
                this.releaseCapture();
                if (submit) this.recognize(new Blob(chunks, {type: recorder.mimeType || format}), generation);
                chunks.length = 0;
            };
            recorder.start(250);
            this.watch(generation);
            this.timer = setTimeout(() => this.done(), 14500);
        },
        browser(generation) {
            const Recognizer = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!Recognizer) throw new Error('Browser recognition is unavailable. Remove voice_probe=browser to test household speech.');
            const recognition = new Recognizer();
            this.recognition = recognition;
            recognition.continuous = false; recognition.interimResults = false;
            recognition.lang = document.documentElement.lang || 'en-US';
            let final = false;
            recognition.onspeechend = () => {
                if (this.valid(generation)) {
                    this.ended = performance.now(); this.anchor = 'recognizer speech-end event';
                }
            };
            recognition.onresult = async event => {
                if (final || !this.valid(generation)) return;
                final = true;
                if (!this.ended) {
                    this.ended = performance.now(); this.anchor = 'recognition result; speech-end unobserved';
                }
                this.releaseCapture();
                try {
                    const text = Array.from(event.results).filter(r => r.isFinal).map(r => r[0].transcript).join(' ');
                    const data = await this.json(this.turn.request_id + '/text', {text});
                    if (this.valid(generation)) await this.dispatch(data.transcript, generation);
                } catch (error) { if (this.valid(generation)) this.status(error.message); }
            };
            recognition.onerror = () => {
                if (!final && this.valid(generation)) { this.releaseCapture(); this.status('Browser recognition failed. Tap to retry or use text.'); }
            };
            recognition.onend = () => {
                if (!final && this.valid(generation)) { this.releaseCapture(); this.status('No speech result. Tap to retry or use text.'); }
            };
            recognition.start();
            this.watch(generation);
            this.timer = setTimeout(() => this.done(), 15000);
        },
        done() {
            if (this.state !== 'listening') return;
            this.ended = performance.now();
            if (this.recognition) { this.recognition.stop(); this.status('Recognizing speech…', 'thinking'); }
            else if (this.recorder && this.recorder.state !== 'inactive') {
                this.submitRecording = true;
                this.recorder.stop();
                this.status('Recognizing speech…', 'thinking');
            }
        },
        async recognize(blob, generation) {
            this.controller = new AbortController();
            const timeout = setTimeout(() => this.controller?.abort(), 15000);
            try {
                const res = await fetch(this.url(this.turn.request_id + '/audio'), {method: 'POST',
                    headers: {'Content-Type': blob.type, 'X-Member-Token': this.token}, body: blob,
                    signal: this.controller.signal});
                const data = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(data.detail || 'Speech recognition failed. Try again or use text.');
                clearTimeout(timeout);
                if (this.valid(generation)) await this.dispatch(data.transcript, generation);
            } catch (error) {
                if (this.valid(generation)) {
                    this.cancelServer(this.turn, this.token);
                    this.status(error.name === 'AbortError' ? 'Recognition took too long. Tap to try again or use text.' : error.message);
                }
            } finally { clearTimeout(timeout); }
        },
        async dispatch(transcript, generation) {
            if (el('transcript')) el('transcript').textContent = transcript;
            const timing = {capture: new URLSearchParams(location.search).get('voice_probe') === 'browser' ? 'browser' : 'ha',
                anchor: this.anchor,
                transcript_ms: Math.round(performance.now() - this.ended)};
            this.status('Thinking…', 'thinking');
            this.controller = new AbortController();
            const data = await this.json(this.turn.request_id + '/run', {}, this.controller.signal);
            if (!this.valid(generation)) return;
            timing.text_ms = Math.round(performance.now() - this.ended);
            this.response = data;
            await refreshThread();
            if (!this.valid(generation)) return;
            this.status('Reply ready. Preparing speech…', 'thinking');
            await this.play(timing);
        },
        async play(timing) {
            if (!this.turn || !this.response) return;
            const generation = this.generation;
            this.releaseAudio();
            try {
                this.controller = new AbortController();
                const res = await fetch(this.url(this.turn.request_id + '/speech'), {method: 'POST',
                    headers: {'X-Member-Token': this.token}, signal: this.controller.signal});
                if (!res.ok) throw new Error('Speech unavailable. Your answer is on screen.');
                const blob = await res.blob();
                if (!this.valid(generation)) return;
                this.audioUrl = URL.createObjectURL(blob);
                this.audio = new Audio(this.audioUrl);
                this.audio.onplaying = () => {
                    if (!this.valid(generation)) return;
                    if (timing) {
                        timing.first_audio_ms = Math.round(performance.now() - this.ended);
                        this.timings.push(timing); this.timings = this.timings.slice(-20);
                    }
                    this.status('Speaking…', 'speaking');
                };
                this.audio.onended = () => {
                    if (!this.valid(generation)) return;
                    this.releaseAudio();
                    this.status(this.response?.continue_conversation ? 'Tap to reply.' : 'Tap the microphone for another request.');
                    if (this.response?.continue_conversation) el('reply')?.classList.remove('hidden');
                };
                this.audio.onerror = () => {
                    if (!this.valid(generation)) return;
                    this.releaseAudio();
                    this.status('Audio playback failed. Your answer is on screen.');
                    el('play')?.classList.remove('hidden');
                    if (this.response?.continue_conversation) el('reply')?.classList.remove('hidden');
                };
                await this.audio.play();
            } catch (_) {
                if (this.valid(generation)) {
                    this.releaseAudio();
                    this.status('Your answer is on screen. Tap Play reply to hear it.');
                    el('play')?.classList.remove('hidden');
                    if (this.response?.continue_conversation) el('reply')?.classList.remove('hidden');
                }
            }
        }
    };
    window.ChauffeurPhoneVoice = voice;
    document.addEventListener('visibilitychange', () => { if (document.hidden) voice.stop(false); });
    window.addEventListener('pagehide', () => voice.stop(false));
    window.addEventListener('storage', event => { if ((event.key || '').includes('member_token')) voice.stop(false); });
    voice.visibility();
})();

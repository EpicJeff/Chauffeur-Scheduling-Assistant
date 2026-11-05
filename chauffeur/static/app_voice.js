/* Foreground personal Argyle voice. HA recorder path; disposable browser probe.
 * No wake word, biometric enrollment, or private answer sent to browser TTS. */
(() => {
    'use strict';
    const el = id => document.getElementById('phone-voice-' + id);
    const voice = {
        generation: 0, turn: null, stream: null, recorder: null, recognition: null,
        audio: null, audioUrl: null, timer: null, watcher: null, controller: null,
        state: 'idle', token: '', response: null, submitRecording: false,
        timings: [], started: 0, ended: 0, anchor: '', host: null,
        PAUSE_MS: 1200, NO_SPEECH_MS: 8000, SPEECH_RMS: 0.02,
        audioContext: null, analyser: null, source: null, silenceTimer: null,
        unlockAudio() {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (!AudioContext) return;
            try {
                // Call in the gesture, before ensuring a DM or starting a turn.
                if (!this.audioContext || this.audioContext.state === 'closed') this.audioContext = new AudioContext();
                if (this.audioContext.state !== 'running') this.audioContext.resume?.()?.catch(() => {});
            } catch (_) { /* Done and the recording cap work without Web Audio. */ }
        },
        releaseAudioContext() {
            const context = this.audioContext; this.audioContext = null;
            try { context?.close()?.catch(() => {}); } catch (_) {}
        },
        visibility() {
            const channel = typeof threadChannel === 'undefined' ? null : threadChannel;
            if (el('mic')) el('mic').style.display = channel?.kind === 'dm'
                && channel.member_ids?.includes('argyle') ? 'inline-flex' : 'none';
        },
        status(label, state = 'idle') {
            this.state = state;
            if (state === 'idle') {
                clearInterval(this.watcher); this.watcher = null;
                this.releaseAudioContext();
            }
            if (this.host) { this.host.status(label, state); return; }
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
        fail(label, host = this.host) {
            this.releaseAudioContext();
            if (host) {
                this.generation++;
                this.state = 'idle';
                clearInterval(this.watcher); this.watcher = null;
                host.status(label, 'error');
                this.host = null;
            } else this.status(label);
        },
        url(suffix) { return (typeof apiBase === 'undefined' ? '' : apiBase) + 'api/app-voice/' + suffix; },
        valid(generation) {
            return generation === this.generation && !document.hidden && this.token === memberToken()
                && (this.host ? this.host.isOpen()
                    : (!this.turn || typeof activeChannelId === 'undefined' || activeChannelId === this.turn.channel.id));
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
            clearInterval(this.silenceTimer); this.silenceTimer = null;
            try { this.source?.disconnect(); this.analyser?.disconnect(); } catch (_) {}
            this.source = null; this.analyser = null;
            const r = this.recorder; this.recorder = null;
            if (r && r.state !== 'inactive') { try { r.stop(); } catch (_) {} }
            const recognition = this.recognition; this.recognition = null;
            if (recognition) { try { recognition.abort(); } catch (_) {} }
            const stream = this.stream; this.stream = null;
            if (stream) stream.getTracks().forEach(t => t.stop());
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
        stop(show = true, {continuing = false} = {}) {
            const active = this.state !== 'idle' || this.stream || this.audio;
            this.generation++;
            clearInterval(this.watcher); this.watcher = null;
            this.submitRecording = false;
            this.controller?.abort(); this.controller = null;
            this.releaseCapture(); this.releaseAudio();
            if (!continuing) this.releaseAudioContext();
            this.cancelServer(this.turn, this.token);
            this.turn = null; this.response = null;
            if (this.host) {
                this.state = 'idle';
                this.host.status('', 'idle');
                this.host = null;
                return;
            }
            if (show && active) this.status('Stopped. Completed actions remain in your conversation.');
            else if (!show) { this.state = 'idle'; el('panel')?.classList.add('hidden'); }
        },
        async start(opts = {}) {
            const response = opts.continuing ? this.response : null;
            // Turn cleanup must keep the context the gesture just unlocked,
            // including when the next turn has no user gesture of its own.
            this.stop(false, {continuing: true});
            this.response = response;
            if (!memberToken()) {
                this.releaseAudioContext();
                opts.host?.status('', 'idle');
                showGlobalAlert('Sign in on your personal device to talk to Argyle.'); return;
            }
            if (!window.isSecureContext || window.self !== window.top) {
                this.releaseAudioContext();
                opts.host?.status('', 'idle');
                showGlobalAlert('Open the secure Chauffeur app outside Home Assistant ingress for voice.'); return;
            }
            if (!opts.continuing && (!this.audioContext || this.audioContext.state === 'closed')) this.unlockAudio();
            this.host = opts.host || null;
            this.token = memberToken();
            const generation = this.generation;
            const credential = this.token;
            const requestId = crypto.randomUUID ? crypto.randomUUID()
                : Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, '0')).join('');
            const ownChannel = this.host ? this.host.channelId()
                : (typeof threadChannel !== 'undefined' && threadChannel?.kind === 'dm'
                    && threadChannel.member_ids?.includes('argyle') ? threadChannel.id : null);
            this.status('Starting microphone…', 'starting');
            this.started = performance.now();
            this.ended = 0; this.anchor = 'recording ended / Done';
            if (!this.host && el('transcript')) el('transcript').textContent = '';
            try {
                // Do not abort this request: a late start response must revoke
                // the exact turn it created after local cancellation.
                const turn = await this.json('start', {request_id: requestId, channel_id: ownChannel});
                if (!this.valid(generation)) { this.cancelServer(turn, credential); return; }
                this.turn = turn;
                if (!this.host) {
                    setView('messages');
                    await openChannel(turn.channel.id, turn.channel);
                }
                if (!this.valid(generation)) { this.cancelServer(turn, credential); return; }
                const browserProbe = new URLSearchParams(location.search).get('voice_probe') === 'browser';
                if (browserProbe) this.browser(generation);
                else await this.capture(generation);
            } catch (error) {
                if (generation !== this.generation) return;
                this.releaseCapture(); this.cancelServer(this.turn, credential);
                if (!this.host && !this.turn && document.getElementById('thread-view')?.style.display !== 'flex')
                    showGlobalAlert(error.message || 'Voice could not start. You can still type.');
                this.fail(error.name === 'NotAllowedError' ? 'Microphone access was denied. Allow it in Settings or use text.'
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
                if (this.stream === stream) {
                    const host = this.host;
                    this.stop(); this.fail('Microphone interrupted. Tap to resume.', host);
                }
            }));
            const format = ['audio/mp4', 'audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus']
                .find(type => MediaRecorder.isTypeSupported(type));
            if (!format) throw new Error('This microphone recording format is unavailable. You can still type.');
            const recorder = new MediaRecorder(stream, {mimeType: format});
            this.recorder = recorder;
            const chunks = [];
            let size = 0;
            recorder.ondataavailable = event => {
                if (!this.valid(generation) || this.recorder !== recorder) return;
                size += event.data.size;
                if (size > 5000000) {
                    const host = this.host;
                    this.stop(); this.fail('Recording exceeded its limit. Try a shorter request.', host);
                }
                else if (event.data.size) chunks.push(event.data);
            };
            recorder.onerror = () => {
                if (!this.valid(generation) || this.recorder !== recorder) return;
                const host = this.host;
                this.stop(); this.fail('Recording failed. Tap to try again or use text.', host);
            };
            recorder.onstop = () => {
                if (this.recorder !== recorder) { chunks.length = 0; return; }
                const submit = this.submitRecording && this.valid(generation);
                this.submitRecording = false;
                this.recorder = null;
                this.releaseCapture();
                if (submit) this.recognize(new Blob(chunks, {type: recorder.mimeType || format}), generation);
                chunks.length = 0;
            };
            recorder.start(250);
            this.status('Listening — press Done when you finish.', 'listening');
            this.watch(generation);
            this.timer = setTimeout(() => this.done(), 14500);
            this.detectSpeech(stream, generation);
        },
        detectSpeech(stream, generation) {
            const context = this.audioContext;
            if (!context || context.state === 'closed') return;
            try {
                this.source = context.createMediaStreamSource(stream);
                this.analyser = context.createAnalyser();
                this.source.connect(this.analyser);
                const buf = new Float32Array(this.analyser.fftSize);
                let opened = performance.now();
                let lastSpeech = null;
                if (context.state !== 'running') context.resume?.()?.catch(() => {});
                this.silenceTimer = setInterval(() => {
                    if (!this.valid(generation) || this.state !== 'listening' || this.stream !== stream) return;
                    if (context.state !== 'running') {
                        // A suspended analyser cannot distinguish speech from
                        // silence. Give it a fresh window when audio resumes.
                        opened = performance.now(); lastSpeech = null;
                        return;
                    }
                    this.analyser.getFloatTimeDomainData(buf);
                    const rms = Math.sqrt(buf.reduce((sum, value) => sum + value * value, 0) / buf.length);
                    const now = performance.now();
                    if (rms > this.SPEECH_RMS) lastSpeech = now;
                    else if (lastSpeech !== null && now - lastSpeech >= this.PAUSE_MS) this.done();
                    else if (lastSpeech === null && now - opened >= this.NO_SPEECH_MS) this.stop(false);
                }, 50);
            } catch (_) {
                // Web Audio is optional; Done and the recording cap still work.
                try { this.source?.disconnect(); this.analyser?.disconnect(); } catch (_) {}
                this.source = null; this.analyser = null;
            }
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
                } catch (error) { if (this.valid(generation)) this.fail(error.message); }
            };
            recognition.onerror = () => {
                if (!final && this.valid(generation)) { this.releaseCapture(); this.fail('Browser recognition failed. Tap to retry or use text.'); }
            };
            recognition.onend = () => {
                if (!final && this.valid(generation)) { this.releaseCapture(); this.fail('No speech result. Tap to retry or use text.'); }
            };
            recognition.start();
            this.status('Listening — press Done when you finish.', 'listening');
            this.watch(generation);
            this.timer = setTimeout(() => this.done(), 15000);
        },
        done() {
            if (this.state === 'starting') {
                const host = this.host;
                this.stop(false);
                this.fail('Microphone was still starting. Tap the microphone to try again, or type.', host);
                return;
            }
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
                    this.fail(error.name === 'AbortError' ? 'Recognition took too long. Tap to try again or use text.' : error.message);
                }
            } finally { clearTimeout(timeout); }
        },
        async dispatch(transcript, generation) {
            if (this.host) this.host.transcript(transcript);
            else if (el('transcript')) el('transcript').textContent = transcript;
            const timing = {capture: new URLSearchParams(location.search).get('voice_probe') === 'browser' ? 'browser' : 'ha',
                anchor: this.anchor,
                transcript_ms: Math.round(performance.now() - this.ended)};
            this.status('Thinking…', 'thinking');
            this.controller = new AbortController();
            const data = await this.json(this.turn.request_id + '/run', {}, this.controller.signal);
            if (!this.valid(generation)) return;
            timing.text_ms = Math.round(performance.now() - this.ended);
            this.response = data;
            if (this.host) this.host.reply(data.reply, {
                continue_conversation: data.continue_conversation, speech_safe: data.speech_safe
            });
            if (currentView === 'messages') await refreshThread();
            if (!this.valid(generation)) return;
            if (!data.speech) {
                if (this.continueConversation(generation)) return;
                this.status('Your answer is on screen. Tap the microphone for another request.');
                this.host = null;
                return;
            }
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
                    if (this.continueConversation(generation)) return;
                    this.status('Tap the microphone for another request.');
                    if (this.host) { this.host = null; return; }
                    if (this.response?.continue_conversation) el('reply')?.classList.remove('hidden');
                };
                this.audio.onerror = () => {
                    if (!this.valid(generation)) return;
                    this.releaseAudio();
                    if (this.continueConversation(generation)) return;
                    const hosted = !!this.host;
                    this.fail('Audio playback failed. Your answer is on screen.');
                    if (hosted) return;
                    el('play')?.classList.remove('hidden');
                    if (this.response?.continue_conversation) el('reply')?.classList.remove('hidden');
                };
                await this.audio.play();
            } catch (_) {
                if (this.valid(generation)) {
                    this.releaseAudio();
                    if (this.continueConversation(generation)) return;
                    const hosted = !!this.host;
                    this.fail(hosted ? 'Your answer is on screen. Speech is unavailable.'
                        : 'Your answer is on screen. Tap Play reply to hear it.');
                    if (hosted) return;
                    el('play')?.classList.remove('hidden');
                    if (this.response?.continue_conversation) el('reply')?.classList.remove('hidden');
                }
            }
        },
        continueConversation(generation) {
            if (!this.valid(generation) || !this.response?.continue_conversation) return false;
            this.start({host: this.host, continuing: true});
            return true;
        }
    };
    window.ChauffeurPhoneVoice = voice;

    // ── Set up my voice (spec 2026-10-13, Phone flow). Five answers through the
    // same recorder, each uploaded with the step token the server issued;
    // never transcribed, never the agent. The question is read aloud by the
    // household's Argyle voice before Record is enabled, so playback is never
    // in a sample. A child's screen sends a parent's PIN once, at Start.
    const setupEl = id => document.getElementById('pwa-voice-setup' + (id ? '-' + id : ''));
    const setup = {
        state: {enrollmentId: null, token: '', step: 0, total: 5, question: '', phase: 'idle', message: ''},
        token: '', stream: null, recorder: null, audio: null, audioUrl: null, timer: null, chunks: [], submit: false,
        url(suffix) { return (typeof apiBase === 'undefined' ? '' : apiBase) + 'api/app-voice/' + suffix; },
        headers(extra) { return Object.assign({'X-Member-Token': this.token}, extra || {}); },
        text(id, value) { const node = setupEl(id); if (node) node.textContent = value; },
        show(id, on) { const node = setupEl(id); if (node) node.hidden = !on; },
        render() {
            const s = this.state;
            this.show('intro', s.phase === 'intro');
            this.show('stage', s.phase === 'question' || s.phase === 'recording' || s.phase === 'sending');
            this.show('finish', s.phase === 'finished');
            this.text('step', s.step ? `${s.step} of ${s.total}` : '');
            this.text('question', s.question || '');
            this.text('status', s.message || '');
            const record = setupEl('record');
            if (record) record.disabled = s.phase !== 'question';
            this.show('done', s.phase === 'recording');
        },
        async open() {
            this.token = typeof memberToken === 'function' ? memberToken() : '';
            this.state = {enrollmentId: null, token: '', step: 0, total: 5, question: '', phase: 'intro', message: ''};
            this.render();
            const dialog = setupEl('');
            if (dialog && !dialog.open && dialog.showModal) dialog.showModal();
        },
        async start(parentId, parentPin) {
            if (!this.token) { showGlobalAlert('Sign in on your personal device first.'); return; }
            if (typeof isSecureContext !== 'undefined' && !isSecureContext) {
                showGlobalAlert('Open the secure Chauffeur app for voice setup.'); return;
            }
            this.state.message = 'Starting…'; this.render();
            try {
                const res = await fetch(this.url('enroll'), {method: 'POST',
                    headers: this.headers({'Content-Type': 'application/json'}),
                    body: JSON.stringify(parentId ? {parent_id: parentId, parent_pin: parentPin} : {})});
                const data = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(data.detail || 'Voice setup could not start.');
                this.take(data);
            } catch (error) {
                this.state.phase = 'intro'; this.state.message = error.message; this.render();
                return;
            }
            this.state.phase = 'question'; this.render();
            await this.speak();
        },
        take(data) {
            const s = this.state;
            if (data.enrollment_id) s.enrollmentId = data.enrollment_id;
            if (data.token) s.token = data.token;
            if (data.step) s.step = data.step;
            if (data.total) s.total = data.total;
            if (data.question) s.question = data.question;
            s.message = data.message || '';
        },
        async speak() {
            this.releaseAudio();
            const record = setupEl('record');
            if (record) record.disabled = true;
            const finish = () => { this.releaseAudio(); if (this.state.phase === 'question') this.render(); };
            try {
                const res = await fetch(this.url('enroll/' + this.state.enrollmentId + '/speech'), {headers: this.headers()});
                if (!res.ok) throw new Error('no speech');
                const blob = await res.blob();
                this.audioUrl = URL.createObjectURL(blob);
                this.audio = new Audio(this.audioUrl);
                this.audio.onended = finish; this.audio.onerror = finish;
                await this.audio.play();
            } catch (_) { finish(); }   // the question is on screen either way
        },
        releaseAudio() {
            if (this.audio) { try { this.audio.pause(); } catch (_) {} this.audio.onended = null; this.audio.onerror = null; }
            this.audio = null;
            if (this.audioUrl) URL.revokeObjectURL(this.audioUrl);
            this.audioUrl = null;
        },
        releaseCapture() {
            clearTimeout(this.timer); this.timer = null;
            const r = this.recorder; this.recorder = null;
            if (r && r.state !== 'inactive') { try { r.stop(); } catch (_) {} }
            if (this.stream) this.stream.getTracks().forEach(t => t.stop());
            this.stream = null;
        },
        async record() {
            if (this.state.phase !== 'question') return;
            if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined' || !MediaRecorder.isTypeSupported) {
                this.state.message = 'Voice recording is unavailable on this browser.'; this.render(); return;
            }
            try {
                const stream = await navigator.mediaDevices.getUserMedia({audio: true});
                this.stream = stream;
                const format = ['audio/mp4', 'audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus']
                    .find(type => MediaRecorder.isTypeSupported(type));
                if (!format) throw new Error('This recording format is unavailable.');
                const recorder = new MediaRecorder(stream, {mimeType: format});
                this.recorder = recorder; this.chunks = []; this.submit = false;
                recorder.ondataavailable = event => { if (event.data && event.data.size) this.chunks.push(event.data); };
                recorder.onerror = () => { this.releaseCapture(); this.state.phase = 'question'; this.state.message = 'Recording failed. Try again.'; this.render(); };
                recorder.onstop = () => {
                    const send = this.submit; this.submit = false;
                    const blob = new Blob(this.chunks, {type: recorder.mimeType || format});
                    this.chunks = [];
                    this.recorder = null; this.releaseCapture();
                    if (send) this.upload(blob); else { this.state.phase = 'question'; this.render(); }
                };
                recorder.start(250);
                this.state.phase = 'recording'; this.state.message = 'Listening — press Done when you finish.'; this.render();
                this.timer = setTimeout(() => this.done(), 14500);
            } catch (error) {
                this.releaseCapture();
                this.state.message = error.name === 'NotAllowedError' ? 'Microphone access was denied. Allow it in Settings.'
                    : (error.message || 'Microphone unavailable.');
                this.state.phase = 'question'; this.render();
            }
        },
        async done() {
            if (!this.recorder) return;
            this.submit = true;
            this.state.phase = 'sending'; this.state.message = 'Checking that sample…'; this.render();
            this.recorder.stop();
        },
        async upload(blob) {
            try {
                const res = await fetch(this.url('enroll/' + this.state.enrollmentId + '/audio'), {method: 'POST',
                    headers: this.headers({'Content-Type': blob.type, 'X-Voice-Step-Token': this.state.token}), body: blob});
                const data = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(data.detail || 'That sample could not be checked.');
                this.take(data);
                if (data.status === 'done') { this.state.phase = 'finished'; this.render(); return; }
                if (data.status === 'ended') { this.state.phase = 'intro'; this.render(); return; }
                this.state.phase = 'question'; this.render();
                await this.speak();
            } catch (error) {
                this.state.phase = 'question'; this.state.message = error.message; this.render();
            }
        },
        async cancel() {
            this.releaseCapture(); this.releaseAudio();
            if (this.state.enrollmentId && this.state.phase !== 'finished' && this.state.phase !== 'intro') {
                fetch(this.url('enroll'), {method: 'DELETE', headers: this.headers(), keepalive: true}).catch(() => {});
            }
            this.state.phase = 'idle'; this.render();
            const dialog = setupEl('');
            if (dialog && dialog.open && dialog.close) dialog.close();
        },
        async deleteVoice() {
            const ok = typeof promptConfirm === 'function'
                ? await promptConfirm('Delete my voice?', 'Removes your voice from every speaker. You can set it up again later.', 'Delete', 'Keep')
                : false;
            if (!ok) return;
            const res = await fetch(this.url('profile'), {method: 'DELETE', headers: this.headers()});
            showGlobalAlert(res.ok ? 'Your voice was deleted.' : 'Could not delete your voice.');
        },
    };
    window.ChauffeurVoiceSetup = setup;
    document.addEventListener('visibilitychange', () => { if (document.hidden) voice.stop(false); });
    window.addEventListener('pagehide', () => voice.stop(false));
    window.addEventListener('storage', event => { if ((event.key || '').includes('member_token')) voice.stop(false); });
    voice.visibility();
})();

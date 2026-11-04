/* Argyle over the current screen; Messages remains the conversation record. */
const PWA_ARGYLE_HOLD_MS = 350;
function pwaArgyleGesture() {
    let started = 0;
    return {
        state: 'idle',
        down(t) { started = t; this.state = 'down'; },
        tick(t) {
            if (this.state !== 'down' || t - started < PWA_ARGYLE_HOLD_MS) return null;
            this.state = 'holding';
            return 'hold-start';
        },
        up(t) {
            if (this.state === 'idle') return null;
            const held = this.state === 'holding' || t - started >= PWA_ARGYLE_HOLD_MS;
            this.state = 'idle';
            return held ? 'hold-end' : 'tap';
        },
        cancel() { this.state = 'idle'; }
    };
}
function pwaArgyleNewestReply(messages, afterId, argyleId) {
    const after = afterId == null ? -1 : messages.findIndex(m => m.id === afterId);
    // A bounded read may no longer contain our anchor. Never show an older reply.
    if (afterId != null && after < 0) return null;
    for (let i = messages.length - 1; i > after; i--) {
        if (messages[i].sender_member_id === argyleId && messages[i].id !== afterId) return messages[i];
    }
    return null;
}
(() => {
    'use strict';
    const ARGYLE_ID = 'argyle';
    const channels = new Map();
    let overlay, opened = false, member = null, id = null, epoch = 0, turn = 0;
    let state = 'idle', pwaArgyleAfterId = null, replyId = null, replyCard = null, timer = null;
    let refused = false, voiceLive = false, sending = false, streamPending = false;
    let openedAt = 0, restoreOrbFocus = false, talkPending = false;
    const q = selector => overlay.querySelector('.pwa-argyle-' + selector);
    const live = generation => opened && generation === epoch && member === selectedMemberId;
    const fab = () => { if (typeof updateAgentFab === 'function') updateAgentFab(); };
    function clearReply() {
        q('reply').hidden = true;
        q('reply-body').textContent = '';
        q('reply-card').innerHTML = '';
        replyId = null;
        replyCard = null;
    }
    function setState(name, text) {
        if (!overlay) return;
        state = name;
        overlay.dataset.state = name;
        q('status').textContent = text === undefined
            ? ({idle: '', starting: 'Starting microphone…', thinking: 'Thinking…', listening: 'Listening…', speaking: 'Speaking…', error: 'Could not reach Argyle'}[name] || '')
            : text;
        q('wave').hidden = name !== 'listening';
    }
    function build() {
        if (overlay) return;
        overlay = document.createElement('div');
        overlay.id = 'pwa-argyle-overlay';
        overlay.className = 'pwa-argyle';
        overlay.hidden = true;
        overlay.innerHTML = '<div class="pwa-argyle-dim"></div><div class="pwa-argyle-glow"></div>'
            + '<div class="pwa-argyle-ask"><div class="pwa-argyle-wave" hidden aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i></div>'
            + '<div class="pwa-argyle-you"></div><div class="pwa-argyle-reply" hidden>'
            + '<div class="pwa-argyle-reply-body"></div><div class="pwa-argyle-reply-card"></div></div>'
            + '<div class="pwa-argyle-status" role="status"></div>'
            + '<form class="pwa-argyle-bar"><input class="pwa-argyle-input" placeholder="Or type…" aria-label="Ask Argyle" autocomplete="off">'
            + '<button class="pwa-argyle-send argyle-orb" type="submit" aria-label="Send to Argyle">'
            + (typeof ArgyleOrb !== 'undefined' ? ArgyleOrb.glyph() : '') + '</button></form>'
            + '<div class="pwa-argyle-hint">Swipe down to dismiss · <button type="button" class="pwa-argyle-to-messages">full conversation in Messages</button></div></div>';
        document.body.appendChild(overlay);
        q('dim').addEventListener('click', () => {
            if (performance.now() - openedAt >= 400) close('dim');
        });
        overlay.addEventListener('click', event => {
            if (!event.target.closest('.pwa-argyle-reply-card')) return;
            const generation = epoch, request = turn;
            setTimeout(() => { if (live(generation) && request === turn) pull(); }, 400);
        });
        q('bar').addEventListener('submit', event => {
            event.preventDefault();
            send(q('input').value);
        });
        q('to-messages').addEventListener('click', async () => {
            const owner = member;
            // Let our Back finish before setView clears any underlying pushed screen.
            const walked = history.state?.pwaOverlay === 'argyle';
            const back = walked ? new Promise(resolve => {
                const finish = () => { window.removeEventListener('popstate', finish); clearTimeout(timeout); resolve(); };
                const timeout = setTimeout(finish, 300);
                window.addEventListener('popstate', finish);
            }) : Promise.resolve();
            close('messages');
            await back;
            if (owner !== selectedMemberId) return;
            pwaOpenArgyle();
        });
        let touchY = null;
        q('ask').addEventListener('touchstart', event => { touchY = event.touches[0]?.clientY ?? null; }, {passive: true});
        q('ask').addEventListener('touchcancel', () => { touchY = null; });
        q('ask').addEventListener('touchend', event => {
            const end = event.changedTouches[0]?.clientY;
            if (touchY !== null && end - touchY >= 60) close('swipe');
            touchY = null;
        }, {passive: true});
        document.addEventListener('keydown', event => {
            if (opened && event.key === 'Escape' && !event.defaultPrevented
                    && !document.querySelector('.pwa-prompt-overlay')) {
                event.preventDefault(); close('escape');
            }
        });
        window.addEventListener('popstate', event => {
            if (opened && event.state?.pwaOverlay !== 'argyle') close('back');
        });
    }
    async function ensureDm(owner = selectedMemberId) {
        if (!channels.has(owner)) {
            const request = (async () => {
                const res = await fetch(apiBase + 'api/channels/dm', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({member_id: owner, other_member_id: ARGYLE_ID})
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok || !data.id) {
                    const error = new Error(data.detail || "Argyle isn't available for this account.");
                    error.refused = res.status >= 400 && res.status < 500;
                    throw error;
                }
                return data;
            })();
            channels.set(owner, request);
            request.catch(() => { if (channels.get(owner) === request) channels.delete(owner); });
        }
        return channels.get(owner);
    }
    async function ensureChannel() {
        const owner = selectedMemberId, generation = epoch;
        if (refused && owner === member) return null;
        try {
            const channel = await ensureDm(owner);
            if (live(generation)) id = channel.id;
            return channel.id;
        } catch (error) {
            if (live(generation)) {
                refused = !!error.refused;
                setState('error', refused ? error.message : 'Could not reach Argyle');
                q('status').classList.toggle('is-refused', refused);
                q('bar').hidden = refused;
            }
            return null;
        }
    }
    async function open({mode = 'type', keyboard = false} = {}) {
        if (opened) return;
        build();
        opened = true; epoch++; turn++;
        openedAt = performance.now();
        restoreOrbFocus = keyboard || document.activeElement?.id === 'tab-argyle';
        talkPending = mode === 'talk';
        const generation = epoch;
        member = selectedMemberId; id = null; refused = false;
        pwaArgyleAfterId = null; sending = false; streamPending = false;
        clearReply(); q('you').textContent = ''; q('input').value = '';
        q('input').placeholder = 'Or type…'; q('bar').hidden = false;
        q('status').classList.remove('is-refused');
        setState(talkPending ? 'starting' : 'idle');
        overlay.hidden = false;
        document.documentElement.dataset.pwaArgyle = '1';
        history.pushState({pwaOverlay: 'argyle'}, '');
        if (mode === 'type') q('input').focus();
        fab();
        const channel = await ensureChannel();
        if (!live(generation)) return;
        if (!channel) {
            talkPending = false;
            return;
        }
        if (!talkPending) return;
        if (!window.ChauffeurPhoneVoice) { talkPending = false; return; }
        const request = turn;
        voiceLive = true;
        async function anchorVoice(text) {
            try {
                const res = await fetch(apiBase + 'api/channels/' + channel + '/messages?limit=20');
                if (!res.ok) return;
                const messages = await res.json();
                if (!live(generation) || request !== turn) return;
                const after = messages.findIndex(message => message.id === pwaArgyleAfterId);
                // The transcript read can finish after the reply was posted. Anchor
                // to our words in that case, so host.reply can still pull its card.
                const newest = text === undefined ? messages[messages.length - 1]
                    : messages.slice(after + 1).reverse().find(message =>
                        message.sender_member_id === member && message.body === text);
                if (newest) pwaArgyleAfterId = newest.id;
            } catch (_) { /* Voice can continue; pulls stay gated until its reply. */ }
        }
        await anchorVoice();
        if (!live(generation) || request !== turn) return;
        if (!talkPending) { voiceLive = false; return; }
        talkPending = false;
        const host = {
            status(label, name) {
                if (!live(generation)) return;
                if (name === 'idle') {
                    voiceLive = false;
                    setState('idle');
                    if (!q('you').textContent) q('input').focus();
                } else if (name === 'error') {
                    voiceLive = false;
                    setState('error', label);
                } else setState(name);
            },
            transcript(text) {
                if (!live(generation)) return;
                q('you').textContent = text;
                anchorVoice(text);
            },
            reply(text, meta) {
                if (!live(generation)) return;
                clearReply();
                q('reply-body').textContent = text;
                q('reply').hidden = false;
                pull({voiceReply: true});
                if (meta?.continue_conversation) {
                    q('input').placeholder = 'Tap to reply…';
                    q('input').focus();
                }
            },
            channelId: () => channel,
            isOpen: () => live(generation)
        };
        await window.ChauffeurPhoneVoice.start({host});
        if (window.ChauffeurPhoneVoice.state === 'idle') voiceLive = false;
    }
    function done() {
        if (!opened) return;
        if (talkPending) {
            // The DM is still being ensured; no voice turn exists to stop yet.
            talkPending = false;
            if (state === 'starting') setState('error', 'Keep holding until Listening… appears, or type.');
            return;
        }
        window.ChauffeurPhoneVoice?.done();
    }
    function close(reason, {keepHistory = false} = {}) {
        if (!opened) return;
        opened = false; epoch++; turn++;
        clearTimeout(timer); timer = null;
        if (voiceLive && typeof ChauffeurPhoneVoice !== 'undefined') ChauffeurPhoneVoice.stop(false);
        voiceLive = false; talkPending = false; sending = false; streamPending = false;
        overlay.hidden = true;
        delete document.documentElement.dataset.pwaArgyle;
        q('you').textContent = ''; clearReply(); setState('idle');
        if (!keepHistory && reason !== 'back' && history.state?.pwaOverlay === 'argyle') history.back();
        fab();
        if (restoreOrbFocus) document.getElementById('tab-argyle')?.focus();
        restoreOrbFocus = false;
    }
    async function send(text) {
        const body = String(text || '').trim();
        if (!opened || refused || !body || sending) return;
        const generation = epoch, request = ++turn;
        const channel = id || await ensureChannel();
        if (!channel || !live(generation) || request !== turn) return;
        if (voiceLive && typeof ChauffeurPhoneVoice !== 'undefined') ChauffeurPhoneVoice.stop(false);
        voiceLive = false; talkPending = false;
        sending = true;
        q('you').textContent = body; q('input').value = '';
        clearReply(); clearTimeout(timer); setState('thinking');
        try {
            const res = await fetch(apiBase + 'api/channels/' + channel + '/messages', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({sender_member_id: member, body})
            });
            if (!res.ok) {
                const data = await res.json().catch(() => ({}));
                const error = new Error('send failed');
                error.detail = data.detail;
                throw error;
            }
            const message = await res.json();
            if (!live(generation) || request !== turn) return;
            pwaArgyleAfterId = message.id;
            timer = setTimeout(() => {
                if (live(generation) && request === turn && state === 'thinking')
                    setState('error', 'Still thinking — the reply will land in Messages.');
            }, 45000);
        } catch (error) {
            if (live(generation) && request === turn) {
                streamPending = false;
                setState('error', error.detail || 'Could not reach Argyle');
            }
        } finally {
            if (live(generation) && request === turn) {
                sending = false;
                if (streamPending) { streamPending = false; pull(); }
            }
        }
    }
    async function pull({voiceReply = false} = {}) {
        if (!opened || !id || refused) return;
        const voicePending = () => !voiceReply && voiceLive && ['starting', 'listening', 'thinking'].includes(state);
        if (voicePending()) return;
        if (sending) { streamPending = true; return; }
        const generation = epoch, request = turn, channel = id;
        try {
            const res = await fetch(apiBase + 'api/channels/' + channel + '/messages?limit=20');
            if (!res.ok) throw new Error('read failed');
            const messages = await res.json();
            if (!live(generation) || request !== turn) return;
            if (voicePending()) return;
            const message = pwaArgyleNewestReply(messages, pwaArgyleAfterId, ARGYLE_ID);
            if (!message) return;
            const card = JSON.stringify(message.card);
            if (message.id === replyId && card === replyCard) return;
            q('reply-body').textContent = message.body || '';
            q('reply-card').innerHTML = message.card && typeof renderCard === 'function' ? renderCard(message.card) : '';
            q('reply').hidden = false;
            replyId = message.id;
            replyCard = card;
            clearTimeout(timer); timer = null;
            if (state !== 'speaking') setState('idle');
        } catch (_) {
            if (live(generation) && request === turn) setState('error', 'Could not reach Argyle');
        }
    }
    window.PwaArgyle = {open, close, done, isOpen: () => opened, channelId: () => id,
        ensureDm, ensureChannel, send, pull, onStream(channel) { if (opened && channel === id) return pull(); }, setState};
})();

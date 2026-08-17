/* Music Assistant, as logic — no markup, no element ids, no assumptions
 * about what is drawing.
 *
 * There are two music surfaces in this app and they look nothing alike: the
 * PWA's widget is a phone control in fixed dark colours, and the board's card
 * is read and pressed from across a kitchen in whatever theme the wall is
 * wearing. What they share is not a drawing, it is everything underneath —
 * which players exist, how to reach one, and the artwork rules, which are the
 * part nobody should ever have to re-derive:
 *
 *   * Music Assistant serves cover art over plain http:// from its LAN image
 *     proxy. On an https page that is mixed content, and iOS Safari blocks it
 *     SILENTLY — no error, no broken-image icon, just nothing. So anything
 *     not already https goes through the add-on's own image proxy.
 *   * Home Assistant's `entity_picture` is frequently a RELATIVE path, which
 *     would resolve against whatever origin the panel is on rather than HA's.
 *     Same proxy, same reason.
 *
 * Both surfaces call `MusicLogic.artwork()` and get that for free.
 *
 * The LOCAL PLAYER is here too, and the first cut of this file was wrong to
 * leave it out. The reasoning then was that a handset being a Music Assistant
 * endpoint is a phone concern and a wall panel is only a speaker's remote —
 * which is false about the actual object: a kitchen tablet has speakers, and
 * a music screen you cannot play music ON is a remote control for other
 * rooms. So the lifecycle (socket, reconnect, unlock, the MA-exposure step)
 * lives here once, parameterised by IDENTITY, and each surface supplies its
 * own: a phone is a person ("Lily's phone"), a panel is a place ("Kitchen
 * screen"). Everything above that — how it is drawn, how it is announced —
 * stays with the surface.
 */
(function () {
    'use strict';

    // Every surface that uses this lives at a different depth: /app, /home,
    // /board/<slug>. A bare 'api/...' from the last one resolves to
    // /board/api/... and 404s, so callers pass the base the page already
    // computed for its other links.
    function base(opts) {
        return (opts && opts.apiBase) || '';
    }

    async function json(url, init) {
        const res = await fetch(url, init);
        if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            const err = new Error(body.detail || ('HTTP ' + res.status));
            err.status = res.status;
            throw err;
        }
        return res.json();
    }

    // Auth arc S8: the two channels a fetch wrapper can never reach — the
    // artwork proxy is drawn as a bare <img src>, and a browser WebSocket can
    // set no headers. For those the token rides the QUERY STRING, which
    // identify() reads for exactly this class of caller. Member first: a
    // signed-in person outranks the furniture, and the server prefers the
    // device tier when both arrive.
    function authUrl(url) {
        try {
            if (typeof localStorage === 'undefined') return url;
            const t = localStorage.getItem('chauffeur_member_token');
            const d = localStorage.getItem('chauffeur_device_token');
            const q = t ? 'member_token=' + encodeURIComponent(t)
                        : (d ? 'device_token=' + encodeURIComponent(d) : '');
            if (!q) return url;
            return url + (url.indexOf('?') >= 0 ? '&' : '?') + q;
        } catch (e) { return url; }
    }

    const TYPE_ICON = {
        track: '🎵', album: '💿', artist: '🎤', playlist: '📻', radio: '📡',
    };

    /** Two names are the same name if Music Assistant and Home Assistant could
     *  have produced both from one string. MA→HA naming differs by version on
     *  apostrophes, case and punctuation, so all of it goes. */
    function normName(s) {
        return String(s || '').toLowerCase().replace(/[^a-z0-9]/g, '');
    }

    const MusicLogic = {
        TYPE_ICON,

        /** This browser, named once and never rotated.
         *
         * The SAME slot the auth shells mint `X-Device-Id` into, deliberately:
         * a panel a parent has already paired HAS an identity, and a second
         * one minted here would mean the trusted-device list and the Music
         * Assistant player list disagreed about which screen this is.
         */
        deviceId() {
            let id = null;
            try { id = localStorage.getItem('chauffeur_device_id'); } catch (e) { }
            if (!id) {
                id = (crypto.randomUUID ? crypto.randomUUID()
                      : String(Date.now()) + Math.random().toString(16).slice(2));
                try { localStorage.setItem('chauffeur_device_id', id); } catch (e) { }
            }
            return id;
        },

        /** Four characters of it — enough to tell two panels apart in a Music
         *  Assistant list, short enough to read off a wall. */
        deviceTag() {
            return MusicLogic.deviceId().replace(/[^a-z0-9]/gi, '').slice(-4).toLowerCase();
        },

        /** Why a browser on THIS page may fail to stay a player, or ''.
         *
         * A page served over plain http is not a "secure context", and the
         * Opus decoder sendspin-js wants is unavailable in one — the library
         * says so ("[Opus] Running in insecure context, falling back to
         * FLAC/PCM") and then Music Assistant hangs up on the client hello.
         * From the room that looks like a player that connects and dies once a
         * second forever, with the cause visible only in a console a wall
         * panel does not have.
         *
         * Not a BLOCK: some setups may negotiate the fallback happily, and
         * refusing to try would remove a working feature to prevent a possible
         * one. It is the sentence to show once it does fail.
         */
        contextWarning() {
            if (typeof window === 'undefined') return '';
            if (window.isSecureContext !== false) return '';
            // NAMES THE ORIGIN, and says nothing about how the page was
            // reached. The first draft advised "reach Chauffeur through Home
            // Assistant" and the household read it while doing exactly that:
            // ingress inherits Home Assistant's own scheme, so an HA served
            // over http hands out insecure pages no matter which door you use.
            // Advice that describes a route rather than a requirement sends
            // somebody to check the place they are already standing.
            return `this page is on http (${location.host}), which the browser `
                 + 'treats as insecure and so withholds the Opus decoder — '
                 + 'Music Assistant then hangs up. It needs an https address; '
                 + 'through ingress that means Home Assistant\'s own URL has '
                 + 'to be https';
        },

        /** What a parent named THIS device, or null. `named` is false for the
         *  labels the pairing flow hands out when nobody typed one — "Wall
         *  panel" is not an identity, it is two of them. */
        async thisDevice(opts) {
            try {
                return await json(base(opts) + 'api/account/this-device',
                                  { headers: { 'X-Device-Id': MusicLogic.deviceId() } });
            } catch (e) {
                return null;
            }
        },

        /** Proxy anything that is not already an absolute https URL. */
        artwork(url, opts) {
            if (!url || typeof url !== 'string') return null;
            if (url.startsWith('https://')) return url;
            const b64 = btoa(url).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
            return authUrl(base(opts) + 'api/ha/image64/' + b64);
        },

        /** The cover's RAW URL — what a snapshot stores. Never proxied here:
         *  the proxy path is relative to a page depth, and a shelf row is
         *  drawn from every depth there is. */
        rawImageOf(item) {
            const img = item.image || item.image_url
                || (item.metadata && item.metadata.images && item.metadata.images[0]
                    && item.metadata.images[0].path);
            return (typeof img === 'string' && img.startsWith('http')) ? img : null;
        },

        /** The cover for a search/favourite row, or null when it has none. */
        imageOf(item, opts) {
            const img = MusicLogic.rawImageOf(item);
            return img ? MusicLogic.artwork(img, opts) : null;
        },

        /** "Artist · Album", the artist alone, or a playlist's owner. A row
         *  from a personal shelf carries its subtitle pre-rendered — it was
         *  snapshotted at the tap and has no artists array to rebuild from. */
        subtitleOf(item) {
            if (item.subtitle) return item.subtitle;
            const artists = (item.artists || []).map(a => a.name).join(', ');
            const album = item.album && item.album.name;
            if (artists && album) return artists + ' · ' + album;
            if (artists) return artists;
            return item.owner || '';
        },

        /** A row as the personal shelf stores it: what was drawn, frozen.
         *  The image is the RAW URL — rendering proxies it per page. */
        snapshot(item) {
            return {
                uri: item.uri,
                media_type: item.media_type || null,
                name: item.name || '',
                image: MusicLogic.rawImageOf(item),
                subtitle: MusicLogic.subtitleOf(item),
            };
        },

        /** {favorites, recent} for one member — the personal shelf. */
        async myShelf(memberId, opts) {
            try {
                return await json(base(opts) + 'api/music/my?member_id='
                                  + encodeURIComponent(memberId));
            } catch (e) {
                return { favorites: [], recent: [] };
            }
        },

        async addFavorite(memberId, item, opts) {
            return json(base(opts) + 'api/music/my/favorites', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ member_id: memberId,
                                       item: MusicLogic.snapshot(item) }),
            });
        },

        async removeFavorite(memberId, uri, opts) {
            return json(base(opts) + 'api/music/my/favorites?member_id='
                + encodeURIComponent(memberId) + '&uri=' + encodeURIComponent(uri),
                { method: 'DELETE' });
        },

        /** A glyph for a speaker, from its device class or failing that its
         *  name — HA fills device_class in for barely any media players. */
        playerIcon(p) {
            if (!p) return '🔊';
            if (p.device_class === 'tv') return '📺';
            if (p.device_class === 'receiver') return '🎚️';
            if (p.device_class === 'speaker') return '🔊';
            const n = ((p.entity_id || '') + ' ' + (p.name || '')).toLowerCase();
            if (/\btv\b|television|shield|roku|apple_tv|appletv/.test(n)) return '📺';
            if (/echo|alexa|nest|home_mini|homepod|sonos|speaker/.test(n)) return '🔊';
            if (/group|everywhere|all\b/.test(n)) return '🏠';
            return '🔊';
        },

        /** Music Assistant's players (the endpoint falls back to every media
         *  player when this house has no MA). Never throws: a surface polling
         *  every ten seconds should go quiet on a blip, not paint an error.
         *
         * `all` drops the MA-only filter. The picker wants the filtered list —
         * an HA instance accumulates dozens of TVs MA cannot play to. Finding
         * our OWN entity wants the unfiltered one, and that distinction is the
         * bug this parameter exists for: the filter keeps only entities
         * carrying `mass_player_type`, so a Sendspin player that Music
         * Assistant exposes WITHOUT that attribute is invisible to the search
         * for it — and the card then reports the one-time exposure step as
         * undone, on a player that is exposed, registered and playable from
         * Music Assistant itself.
         */
        async players(opts, all) {
            try {
                return await json(base(opts) + 'api/ha/media_players'
                                  + (all ? '?ma_only=false' : ''));
            } catch (e) {
                return null;
            }
        },

        /** Our own entity, searched for in the FULL player list. Every caller
         *  that wants "which of these is me" should use this rather than
         *  `players()`, or it is searching a list its answer can be filtered
         *  out of. */
        async findLocalEntity(local, opts) {
            if (!local) return null;
            const all = await MusicLogic.players(opts, true);
            return { entity: local.entityIn(all || []), players: all || [] };
        },

        /** play | pause | next | previous | volume_set. */
        async command(entityId, command, extra, opts) {
            if (!entityId) return false;
            try {
                await fetch(base(opts) + 'api/ha/media_players/'
                    + encodeURIComponent(entityId) + '/command', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(Object.assign({ command }, extra || {})),
                });
                return true;
            } catch (e) {
                return false;
            }
        },

        /** What a group of results is called over its section. */
        GROUP_LABEL: {
            track: 'Songs', album: 'Albums', playlist: 'Playlists',
            artist: 'Artists', radio: 'Radio', audiobook: 'Audiobooks',
            podcast: 'Podcasts',
        },

        /** Grouped search. Throws with the server's own message — a search
         *  that failed has something to say, unlike a poll that missed.
         *
         * `params`: {types: ['track',...], limit, libraryOnly, provider}.
         * Returns {source, groups: [{type, items}], providers, total} — the
         * groups exactly as Music Assistant answered them. The old shape of
         * this function flattened the groups into one interleaved list of
         * five-per-type, which threw away the half of MA's answer the family
         * actually missed.
         */
        async search(q, params, opts) {
            const p = params || {};
            let url = base(opts) + 'api/music/search?q=' + encodeURIComponent(q)
                + '&limit=' + (p.limit || 20);
            if (p.types && p.types.length) url += '&media_type=' + p.types.join(',');
            if (p.libraryOnly) url += '&library_only=true';
            if (p.provider) url += '&provider=' + encodeURIComponent(p.provider);
            return json(url);
        },

        /** The grouped response as one flat list, for a surface that wants a
         *  single column anyway. */
        flatten(data) {
            return (data.groups || []).flatMap(g =>
                g.items.map(item => Object.assign({}, item,
                    { media_type: item.media_type || g.type })));
        },

        async favorites(mediaType, limit, opts) {
            try {
                const data = await json(base(opts) + 'api/music/favorites?media_type='
                    + mediaType + '&limit=' + limit);
                return data.items || data[mediaType + 's'] || [];
            } catch (e) {
                return [];
            }
        },

        /** The sentinel a picker uses for "play it here". Not an entity id —
         *  the local player has none until Music Assistant has registered it
         *  and been told to expose it to Home Assistant. */
        LOCAL: '__local__',

        /** Load sendspin-js, once, on demand.
         *
         * NOT vendored into static/vendor/ like Alpine and Leaflet, and the
         * reason is worth keeping: jsDelivr's `+esm` bundle carries two lazy
         * `import("/npm/opus-encdec@...")` calls with ROOT-RELATIVE paths, so
         * a copy served from our own origin would resolve them against this
         * app and 404 exactly when a browser without native Opus needed the
         * fallback decoder. Vendoring it properly means vendoring that too
         * and rewriting the paths. Until then this is deliberately lazy:
         * loaded when a surface actually offers a local player, so a wall
         * panel showing the Drives board never pays for it.
         */
        async loadSendspin() {
            if (window.SendspinPlayer) return window.SendspinPlayer;
            if (!MusicLogic._sendspin) {
                MusicLogic._sendspin = import(
                    'https://cdn.jsdelivr.net/npm/@sendspin/sendspin-js@3.2.1/+esm')
                    .then(mod => {
                        window.SendspinPlayer = mod.SendspinPlayer || mod.default;
                        return window.SendspinPlayer;
                    })
                    .catch(e => {
                        console.warn('sendspin-js failed to load', e);
                        MusicLogic._sendspin = null;   // a later tap may retry
                        return null;
                    });
            }
            return MusicLogic._sendspin;
        },

        /** This browser as a real Music Assistant player.
         *
         * `identity` is the whole difference between the two surfaces:
         *   {name}  what Music Assistant calls it. A phone is a person, a
         *           panel is a place — and the name is also how the HA entity
         *           is found again later, so it must be stable.
         *   {key}   the localStorage slot holding this player's id, so the
         *           SAME screen or handset comes back as the SAME player
         *           rather than littering MA with one entry per reload. It
         *           must NOT be derived from the name — a name can change
         *           (a room renamed, a device label arriving a moment after
         *           the board did) and a key that moved with it would orphan
         *           the registration in Music Assistant every time.
         *   {legacyKeys}
         *           slots earlier versions wrote. Adopted rather than
         *           ignored: minting a fresh id would leave the player this
         *           screen is ALREADY exposed as sitting dead in the list.
         *
         * Callbacks rather than DOM: `onState` fires on every state change,
         * `onNotice` carries the sentences a human needs to see. The surface
         * decides whether that is a toast, an alert or a line on a card.
         */
        localPlayer(identity, opts) {
            const self = {
                player: null, active: false, connecting: false, state: null,
                retries: 0, reconnectTimer: null, everConnected: false,
                // How the last socket ended, ALWAYS recorded. A wall panel has
                // no devtools, and "1006 after 0.4s, six times" is the entire
                // diagnosis of a player that will not stay up.
                lastClose: null, stableTimer: null, connectedAt: 0,
                // Set by `entityIn` when more than one player answers to our
                // name — the state that used to be silently resolved by
                // picking whichever came first.
                ambiguous: false,
            };
            // Long enough that a socket which is going to be closed upstream
            // has already been. Under it, a connection is not yet a success.
            const STABLE_MS = 20000;
            const notice = (msg) => {
                console.warn('[local-player]', msg);
                if (opts && opts.onNotice) opts.onNotice(msg);
            };
            const changed = () => { if (opts && opts.onState) opts.onState(self); };

            /** Why the last socket ended, as a phrase or ''. */
            self.closeReason = function () {
                const c = self.lastClose;
                if (!c) return '';
                return `closed ${c.code}${c.reason ? ': ' + c.reason : ''}`
                     + ` after ${c.heldSeconds}s`;
            };

            function scheduleReconnect() {
                if (self.reconnectTimer) return;
                if (self.retries >= 6) {
                    // A handshake that never completes will not start
                    // completing on the seventh try, so this says what would
                    // have to change rather than inviting another tap.
                    if (self.blockedHost) {
                        notice(`${identity.name} gave up: ${self.blockedHost} `
                            + `will not carry a WebSocket. Chauffeur needs one `
                            + `to send audio to this screen.`);
                        return;
                    }
                    const why = self.closeReason();
                    const ctx = MusicLogic.contextWarning();
                    notice(`${identity.name} keeps losing its connection`
                           + (why ? ` (${why})` : '')
                           + (ctx ? ` — ${ctx}` : ' — select it again to retry')
                           + '.');
                    return;
                }
                const delay = Math.min(15000, 1500 * Math.pow(2, self.retries));
                self.retries += 1;
                self.reconnectTimer = setTimeout(() => {
                    self.reconnectTimer = null;
                    if (!self.player && !self.connecting
                        && document.visibilityState === 'visible') self.start();
                }, delay);
            }

            /** This player's id, adopting whatever an older version stored.
             *  Written back to the current slot so the migration happens once
             *  rather than on every connect. */
            function readId() {
                const keys = [identity.key].concat(identity.legacyKeys || []);
                for (const k of keys) {
                    let v = null;
                    try { v = k && localStorage.getItem(k); } catch (e) { }
                    if (!v) continue;
                    if (k !== identity.key) {
                        try { localStorage.setItem(identity.key, v); } catch (e) { }
                    }
                    return v;
                }
                return null;
            }

            self.start = async function () {
                if (self.player || self.connecting) return;
                const Player = await MusicLogic.loadSendspin();
                if (!Player) {
                    notice('The player library could not be loaded — check the '
                           + 'network and try again.');
                    return;
                }
                self.connecting = true;
                changed();
                try {
                    let pid = readId();
                    if (!pid) {
                        pid = 'chauffeur-' + (crypto.randomUUID
                            ? crypto.randomUUID()
                            : Math.random().toString(36).slice(2));
                        try { localStorage.setItem(identity.key, pid); } catch (e) { }
                    }
                    // Kept on the instance: this id, not the display name, is
                    // what identifies this browser to Music Assistant, and it
                    // is how `entityIn` finds our own entity again after a
                    // rename. Set before connecting so a failure still leaves
                    // something to diagnose with.
                    self.playerId = pid;
                    const wsTarget = new URL(authUrl(base(opts) + 'api/sendspin/ws'),
                                             location.href);
                    // Named separately because a failure has to be able to say
                    // WHICH host would not carry the connection — on a wall
                    // panel that host is the entire difference between "the
                    // LAN address works and the tunnel does not" and a mystery.
                    const wsHost = wsTarget.host;
                    const wsUrl = wsTarget.href.replace(/^http/, 'ws');
                    const socket = new WebSocket(wsUrl);
                    socket.binaryType = 'arraybuffer';
                    // Did the HANDSHAKE ever complete? The whole difference
                    // between "Music Assistant said no" and "nothing in front
                    // of Chauffeur would carry a WebSocket at all", and until
                    // this flag existed both looked identical from the card.
                    let opened = false;
                    socket.addEventListener('open', () => { opened = true; });
                    socket.addEventListener('close', (e) => {
                        // Recorded whether or not we were up, and whether or
                        // not anybody is told: the interesting close is the
                        // one that carries no reason and happens in under a
                        // second, which is the only trace a flapping player
                        // leaves behind.
                        self.lastClose = {
                            code: e.code, reason: e.reason || '',
                            heldSeconds: self.connectedAt
                                ? Math.round((Date.now() - self.connectedAt) / 100) / 10
                                : 0,
                        };
                        if (self.stableTimer) {
                            clearTimeout(self.stableTimer);
                            self.stableTimer = null;
                        }
                        if (!self.active) {
                            // NEVER CAME UP, and this used to return in
                            // silence — which is why both surfaces showed
                            // sendspin-js's "Adopted WebSocket closed before
                            // opening", a sentence that names the symptom and
                            // none of the causes. There are two, and they need
                            // different sentences because they need different
                            // people to fix them.
                            if (e.reason) {
                                // The relay accepted us and then said why:
                                // Music Assistant could not be found or
                                // reached. A Chauffeur-side answer.
                                notice(`${identity.name}: ${e.reason}`);
                            } else if (!opened) {
                                // The handshake never completed, so nothing in
                                // Chauffeur ever ran. Something BETWEEN the
                                // browser and the add-on refused to upgrade
                                // the connection — a tunnel or reverse proxy
                                // that carries ordinary requests perfectly
                                // well and drops WebSockets, which is the
                                // default on more of them than it should be.
                                self.blockedHost = wsHost;
                                notice(`${identity.name} could not open its `
                                    + `audio connection to ${wsHost} — the `
                                    + `WebSocket was refused before it opened. `
                                    + `Whatever sits in front of Chauffeur `
                                    + `(a tunnel, a reverse proxy) has to pass `
                                    + `WebSocket upgrades for a screen or a `
                                    + `phone to play music.`);
                            }
                            return;
                        }
                        self.active = false;
                        self.player = null;
                        // Quietly self-heal; only bother anybody when it is
                        // hopeless (the relay refused, so `reason` is set) —
                        // or when the shape of the failure is one a reconnect
                        // cannot fix, which is the next branch.
                        const ctx = MusicLogic.contextWarning();
                        if (e.reason) {
                            notice(`${identity.name} disconnected: ${e.reason}`);
                        } else if (opened && ctx && !self.warnedContext
                                   && self.lastClose.heldSeconds < 20) {
                            // Connected, negotiated, gone inside a second, no
                            // reason given: that is Music Assistant hanging up
                            // on a client hello it did not like, and on an
                            // insecure page the reason it did not like it is
                            // sitting right there. Said ONCE — the reconnect
                            // is still worth attempting, but silently retrying
                            // something that cannot succeed is what made this
                            // a mystery.
                            //
                            // GATED ON `opened`, and that gate is the whole
                            // lesson of the day it shipped. sendspin-js's
                            // `connect()` resolves without waiting for the
                            // socket, so a handshake the SERVER had already
                            // 500'd still set `active` — and this branch then
                            // blamed an insecure page for a failure that never
                            // reached the codec. A page can be insecure and
                            // that can be beside the point; only a connection
                            // that actually opened has an opinion worth
                            // printing about what closed it.
                            self.warnedContext = true;
                            notice(`${identity.name} keeps dropping — ${ctx}.`);
                        }
                        changed();
                        scheduleReconnect();
                    });
                    const player = new Player({
                        playerId: pid,
                        clientName: identity.name,
                        baseUrl: location.origin,
                        webSocket: socket,
                        correctionMode: 'quality-local',
                        onStateChange: (state) => { self.state = state; changed(); },
                    });
                    // unlock() needs the user gesture that selected this, and
                    // on a wall panel that gesture is the whole reason audio
                    // is allowed to start at all.
                    if (typeof player.unlock === 'function') {
                        try { await player.unlock(); } catch (e) { /* reconnects have no gesture */ }
                    }
                    if (typeof player.connect === 'function') await player.connect();
                    self.player = player;
                    self.active = true;
                    self.connectedAt = Date.now();
                    if (!self.everConnected) {
                        self.everConnected = true;
                        notice(`${identity.name} is now a Music Assistant player 🎉`);
                    }
                    // NOT `retries = 0` here, which is what it used to be. A
                    // socket that opens and dies 200ms later is not a success,
                    // and counting it as one resets the backoff to 1.5 seconds
                    // — so a player something upstream keeps closing sits in a
                    // connect/die/connect loop forever, which on the wall reads
                    // as "(connecting…)" flickering once a second. The counter
                    // clears only once the connection has HELD, so a flap now
                    // backs off like the failure it is and then says so.
                    if (self.stableTimer) clearTimeout(self.stableTimer);
                    self.stableTimer = setTimeout(() => {
                        self.stableTimer = null;
                        self.retries = 0;
                    }, STABLE_MS);
                } catch (e) {
                    self.player = null;
                    self.active = false;
                    if (self.retries === 0) {
                        notice(`${identity.name} failed: ` + (e && e.message ? e.message : e));
                    }
                    scheduleReconnect();
                } finally {
                    self.connecting = false;
                    changed();
                }
            };

            self.stop = function () {
                if (self.reconnectTimer) {
                    clearTimeout(self.reconnectTimer);
                    self.reconnectTimer = null;
                }
                if (self.stableTimer) {
                    clearTimeout(self.stableTimer);
                    self.stableTimer = null;
                }
                self.connectedAt = 0;
                self.retries = 0;
                const p = self.player;
                self.player = null;
                self.active = false;
                self.state = null;
                if (p) {
                    try { if (typeof p.disconnect === 'function') p.disconnect(); } catch (e) { }
                }
                changed();
            };

            /** sendspin-js onStateChange carries {isPlaying, volume, muted,
             *  playerState, serverState, groupState} (dist/types.d.ts v3.2.1). */
            self.isPlaying = function () {
                const s = self.state || {};
                if (typeof s.isPlaying === 'boolean') return s.isPlaying;
                return (s.groupState && s.groupState.playback_state) === 'playing';
            };

            /** Title/artist/album/artwork as this module's own shape, so a
             *  surface can draw a local player exactly like a remote one. */
            self.nowPlaying = function () {
                const md = ((self.state || {}).serverState || {}).metadata || {};
                const artist = md.artist || '';
                return {
                    media_title: md.title || '',
                    // `md.artist` alone would print the string "undefined"
                    // under the title of anything Music Assistant sends
                    // without one — a radio stream, most of the time.
                    media_artist: artist + (md.album ? (artist ? ' · ' : '') + md.album : ''),
                    entity_picture: md.artwork_url || null,
                    volume_level: (typeof (self.state || {}).volume === 'number')
                        ? ((self.state.volume > 1) ? self.state.volume / 100 : self.state.volume)
                        : null,
                };
            };

            self.command = function (command, extra) {
                const p = self.player;
                if (!p) {
                    notice(`${identity.name} is reconnecting — try again in a second.`);
                    if (!self.connecting) self.start();
                    return false;
                }
                try {
                    if (command === 'volume_set' && typeof p.setVolume === 'function') {
                        p.setVolume(Math.round(((extra && extra.volume) || 0) * 100));
                    } else if (typeof p.sendCommand === 'function') {
                        p.sendCommand(command);
                    }
                    return true;
                } catch (e) {
                    notice('Command failed: ' + e.message);
                    return false;
                }
            };

            /** Our own Home Assistant entity, once Music Assistant has been
             *  told to expose this player — or null.
             *
             * Two tiers, and the first one exists because the second was
             * quietly wrong. The NAME match was the only rule at first: MA
             * exposes the player as a media_player named after `clientName`,
             * normalised to letters and digits because MA→HA naming differs by
             * version on apostrophes, case and punctuation. But a player is a
             * thing you can RENAME in Music Assistant, and the moment somebody
             * does, the name match fails forever and the card insists the
             * one-time exposure step has not been done — while pointing at a
             * name that no longer exists.
             *
             * So the id comes first: whatever `mass_*` attribute MA stamps its
             * own player id into, our registered `playerId` is in there
             * verbatim, and that survives any rename. The name match stays as
             * the fallback for versions that expose no such attribute.
             */
            self.entityIn = function (players) {
                const list = players || [];
                self.ambiguous = false;
                if (self.playerId) {
                    const byId = list.find(p => Object.values(p.mass || {})
                        .some(v => typeof v === 'string' && v === self.playerId));
                    if (byId) return byId;
                }
                const want = normName(identity.name);
                if (!want) return null;
                const nameOf = p => normName(p.name)
                    || normName((p.entity_id || '').replace('media_player.', ''));
                // ONE match or none — never "the first of several", which is
                // what `find` used to do. Home Assistant deduplicates the
                // entity_id and not the friendly name, so a house with two
                // panels both called "Chauffeur screen" had two entities whose
                // names normalise identically (and, via the loose tier below,
                // `chauffeurscreen2` matching `chauffeurscreen` as well). This
                // screen then bound to the OTHER room's player: its heart
                // hearted whatever that room was playing, and the picker hid
                // the wrong row as its own twin. Two answers is not an answer.
                const exact = list.filter(p => nameOf(p) === want);
                if (exact.length === 1) return exact[0];
                if (!exact.length) {
                    // Kept, because MA versions differ on what they append —
                    // but held to the same rule.
                    const loose = list.filter(p => {
                        const got = nameOf(p);
                        return got && (got.includes(want) || want.includes(got));
                    });
                    if (loose.length === 1) return loose[0];
                    self.ambiguous = loose.length > 1;
                    return null;
                }
                self.ambiguous = true;
                return null;
            };

            /** Players wearing our name that are NOT us — `mine` being whatever
             *  `entityIn` resolved, passed in rather than recomputed so this
             *  cannot disagree with the caller about which one we are.
             *
             * Two screens registered under one name is not a crash. It is a
             * speaker list nobody can choose from, and the only surface in a
             * position to notice is one of the screens itself. */
            self.clashesIn = function (players, mine) {
                const want = normName(identity.name);
                if (!want) return [];
                return (players || [])
                    .filter(p => normName(p.name) === want)
                    .filter(p => !mine || p.entity_id !== mine.entity_id);
            };

            // iOS suspends the socket when the page backgrounds, and a wall
            // panel's browser may do the same on a screen blank. Resume on the
            // way back rather than waiting for somebody to notice it is dead.
            document.addEventListener('visibilitychange', () => {
                if (document.visibilityState === 'visible' && self.wanted
                    && !self.player && !self.connecting) {
                    self.retries = 0;
                    self.start();
                }
            });
            window.addEventListener('pagehide', () => self.stop());

            return self;
        },

        /** `extra`: {enqueue: 'add'|'next'|..., radioMode: true}. Play-now is
         *  the everything-omitted case. Throws with the server's sentence on
         *  a refusal — radio mode refuses on providers that cannot do it,
         *  and "nothing happened" is the one wrong way to deliver that. */
        /** What is playing on one player, as a row every heart can act on.
         *  Null on a miss — the heart hides rather than lying. */
        async nowPlayingItem(entityId, opts) {
            try {
                return await json(base(opts) + 'api/music/now?entity_id='
                                  + encodeURIComponent(entityId));
            } catch (e) {
                return null;
            }
        },

        /** A real MA favourite — the shared house pile. Throws with the
         *  server's sentence. */
        async houseFavorite(uri, opts) {
            return json(base(opts) + 'api/music/house/favorites', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ uri }),
            });
        },

        async houseUnfavorite(uri, mediaType, opts) {
            return json(base(opts) + 'api/music/house/favorites?uri='
                + encodeURIComponent(uri)
                + (mediaType ? '&media_type=' + encodeURIComponent(mediaType) : ''),
                { method: 'DELETE' });
        },

        /** MA's own shelves for the house view. {available: false} hides
         *  them — the HA bridge has no recommendations to offer. */
        async shelves(opts) {
            try {
                return await json(base(opts) + 'api/music/shelves');
            } catch (e) {
                return { available: false, recently_played: [], recommendations: [] };
            }
        },

        /** The playlists a track can be added to; [] hides the verb. */
        async editablePlaylists(opts) {
            try {
                return await json(base(opts) + 'api/music/playlists/editable');
            } catch (e) {
                return [];
            }
        },

        /** Throws with the server's sentence. */
        async addToPlaylist(playlistId, uri, opts) {
            return json(base(opts) + 'api/music/playlists/add', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ playlist_id: playlistId, uri }),
            });
        },

        /** Create (optionally seeded with one track). Throws on refusal. */
        async createPlaylist(name, uri, opts) {
            return json(base(opts) + 'api/music/playlists/create', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, uri: uri || null }),
            });
        },

        /** The queue as rows: {source, can_edit, items: [{id, index, name,
         *  subtitle, image, current}]}. Null on a miss — a queue panel
         *  should go quiet on a blip, not paint an error. */
        async queue(entityId, opts) {
            try {
                return await json(base(opts) + 'api/music/queue?entity_id='
                                  + encodeURIComponent(entityId));
            } catch (e) {
                return null;
            }
        },

        /** play_index | move_up | move_down | remove | clear. Throws with
         *  the server's sentence — an edit that failed has something to say
         *  ("needs the Music Assistant token"), unlike a poll. */
        async queueCommand(entityId, action, extra, opts) {
            return json(base(opts) + 'api/music/queue/command', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(Object.assign(
                    { entity_id: entityId, action }, extra || {})),
            });
        },

        async play(entityId, uri, mediaType, opts, extra) {
            if (!entityId || !uri) return false;
            const body = { entity_id: entityId, media_id: uri, media_type: mediaType };
            if (extra && extra.enqueue) body.enqueue = extra.enqueue;
            if (extra && extra.radioMode) body.radio_mode = true;
            if (extra && extra.memberId && extra.item) {
                body.member_id = extra.memberId;
                body.item = MusicLogic.snapshot(extra.item);
            }
            await json(base(opts) + 'api/music/play', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            return true;
        },
    };

    window.MusicLogic = MusicLogic;
})();

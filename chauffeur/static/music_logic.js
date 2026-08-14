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

    const TYPE_ICON = {
        track: '🎵', album: '💿', artist: '🎤', playlist: '📻', radio: '📡',
    };

    const MusicLogic = {
        TYPE_ICON,

        /** Proxy anything that is not already an absolute https URL. */
        artwork(url, opts) {
            if (!url || typeof url !== 'string') return null;
            if (url.startsWith('https://')) return url;
            const b64 = btoa(url).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
            return base(opts) + 'api/ha/image64/' + b64;
        },

        /** The cover for a search/favourite row, or null when it has none. */
        imageOf(item, opts) {
            const img = item.image || item.image_url
                || (item.metadata && item.metadata.images && item.metadata.images[0]
                    && item.metadata.images[0].path);
            return (typeof img === 'string' && img.startsWith('http'))
                ? MusicLogic.artwork(img, opts) : null;
        },

        /** "Artist · Album", the artist alone, or a playlist's owner. */
        subtitleOf(item) {
            const artists = (item.artists || []).map(a => a.name).join(', ');
            const album = item.album && item.album.name;
            if (artists && album) return artists + ' · ' + album;
            if (artists) return artists;
            return item.owner || '';
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

        /** Throws with the server's own message — a search that failed has
         *  something to say, unlike a poll that missed. */
        async search(q, limit, opts) {
            return json(base(opts) + 'api/music/search?q=' + encodeURIComponent(q)
                + '&limit=' + (limit || 8));
        },

        /** Search results as one flat list, in the page's own order. */
        flatten(data) {
            const out = [];
            [['tracks', 'track'], ['albums', 'album'], ['playlists', 'playlist'],
             ['artists', 'artist'], ['radio', 'radio']].forEach(([key, type]) => {
                (data[key] || []).slice(0, 5).forEach(item => {
                    out.push(Object.assign({}, item, { media_type: item.media_type || type }));
                });
            });
            return out;
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
         *           rather than littering MA with one entry per reload.
         *
         * Callbacks rather than DOM: `onState` fires on every state change,
         * `onNotice` carries the sentences a human needs to see. The surface
         * decides whether that is a toast, an alert or a line on a card.
         */
        localPlayer(identity, opts) {
            const self = {
                player: null, active: false, connecting: false, state: null,
                retries: 0, reconnectTimer: null, everConnected: false,
            };
            const notice = (msg) => {
                console.warn('[local-player]', msg);
                if (opts && opts.onNotice) opts.onNotice(msg);
            };
            const changed = () => { if (opts && opts.onState) opts.onState(self); };

            function scheduleReconnect() {
                if (self.reconnectTimer) return;
                if (self.retries >= 6) {
                    notice(`${identity.name} lost its connection — select it again to retry.`);
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
                    let pid = localStorage.getItem(identity.key);
                    if (!pid) {
                        pid = 'chauffeur-' + (crypto.randomUUID
                            ? crypto.randomUUID()
                            : Math.random().toString(36).slice(2));
                        localStorage.setItem(identity.key, pid);
                    }
                    // Kept on the instance: this id, not the display name, is
                    // what identifies this browser to Music Assistant, and it
                    // is how `entityIn` finds our own entity again after a
                    // rename. Set before connecting so a failure still leaves
                    // something to diagnose with.
                    self.playerId = pid;
                    const wsUrl = new URL(base(opts) + 'api/sendspin/ws', location.href)
                        .href.replace(/^http/, 'ws');
                    const socket = new WebSocket(wsUrl);
                    socket.binaryType = 'arraybuffer';
                    socket.addEventListener('close', (e) => {
                        if (!self.active) return;
                        self.active = false;
                        self.player = null;
                        // Quietly self-heal; only bother anybody when it is
                        // hopeless (the relay refused, so `reason` is set).
                        if (e.reason) notice(`${identity.name} disconnected: ${e.reason}`);
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
                    if (!self.everConnected) {
                        self.everConnected = true;
                        notice(`${identity.name} is now a Music Assistant player 🎉`);
                    }
                    self.retries = 0;
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
                if (self.playerId) {
                    const byId = list.find(p => Object.values(p.mass || {})
                        .some(v => typeof v === 'string' && v === self.playerId));
                    if (byId) return byId;
                }
                const norm = s => String(s || '').toLowerCase().replace(/[^a-z0-9]/g, '');
                const want = norm(identity.name);
                if (!want) return null;
                return list.find(p => {
                    const got = norm(p.name) || norm((p.entity_id || '').replace('media_player.', ''));
                    return got === want || got.includes(want) || want.includes(got);
                }) || null;
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

        async play(entityId, uri, mediaType, opts) {
            if (!entityId || !uri) return false;
            try {
                await fetch(base(opts) + 'api/music/play', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        entity_id: entityId, media_id: uri, media_type: mediaType,
                    }),
                });
                return true;
            } catch (e) {
                return false;
            }
        },
    };

    window.MusicLogic = MusicLogic;
})();

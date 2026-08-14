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
 * Both surfaces call `MusicLogic.artwork()` and get that for free. The one
 * thing deliberately NOT here is the Sendspin phone player: a handset being a
 * Music Assistant endpoint is a phone concern, a wall panel is a speaker's
 * remote, and hoisting it would put a WebSocket and an audio pipeline into
 * every kiosk that shows a play button.
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
         *  every ten seconds should go quiet on a blip, not paint an error. */
        async players(opts) {
            try {
                return await json(base(opts) + 'api/ha/media_players');
            } catch (e) {
                return null;
            }
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

/* Hosting a real Home Assistant card outside Home Assistant.
 *
 * The server half of this lives in services/ha_cards.py and its docstring
 * explains what can and cannot be hosted. This half is the environment a card
 * wakes up in: the elements it renders into, the `hass` object it reads, and
 * the CSS custom properties that decide what it looks like.
 *
 * That last one is why this is worth doing at all rather than framing HA's own
 * page. A Home Assistant theme is nothing but a set of CSS variables, and
 * custom properties cross shadow boundaries. Set them on the tile and a card
 * that never heard of Chauffeur draws itself in Chauffeur's colours, in light
 * mode and dark, with no cooperation from its author.
 *
 * Deliberately framework-free and global rather than a module: it is loaded by
 * the same plain <script> tag as everything else on this page, and the board is
 * Alpine, which has no build step to hang an import off.
 */
(function () {
    'use strict';

    if (window.ChauffeurHaCards) return;      // one host per page

    // ── The variables an HA theme sets.
    //
    // Mapped from the panel's own tokens, so the card follows the wall through
    // dark, light, and the sun-follows-sunset setting without knowing any of
    // that happened. The right-hand sides are read at mount time from the live
    // computed style, which is what makes the theme switch free.
    //
    // `--ha-card-background: transparent` and no shadow are on purpose: the
    // card is already inside a Chauffeur tile with its own surface, and a card
    // drawing a second card behind it is the visual seam that gives away an
    // embed. The card keeps its shape; the tile keeps the surface.
    var THEME = {
        '--primary-color': '--panel-accent',
        '--accent-color': '--panel-accent',
        '--primary-text-color': '--panel-fg',
        '--secondary-text-color': '--panel-dim',
        '--text-primary-color': '--panel-fg',
        '--disabled-text-color': '--panel-dim',
        '--divider-color': '--panel-line',
        '--state-icon-color': '--panel-fg',
        '--paper-item-icon-color': '--panel-fg',
        '--card-background-color': 'transparent',
        '--ha-card-background': 'transparent',
        '--secondary-background-color': 'transparent',
    };
    var THEME_FIXED = {
        '--ha-card-border-width': '0',
        '--ha-card-box-shadow': 'none',
        '--ha-card-border-radius': '0',
        '--mdc-icon-size': '24px',
        // Semantic colours a card picks for meaning (a flow that is exporting,
        // a battery that is charging). These are the one place we do NOT defer
        // to panel tokens: green means the same thing on every wall, and
        // repainting it in the accent colour would erase what the card is
        // saying. Contrast-picked for both themes.
        '--success-color': '#22c55e',
        '--warning-color': '#f59e0b',
        '--error-color': '#ef4444',
        '--info-color': '#38bdf8',
    };

    // ── The element library a card assumes exists.
    //
    // Cards render <ha-card> and <ha-icon> without importing them, because
    // inside HA's frontend they are simply defined. Defining them here is what
    // makes an unmodified card bundle work, and defining them OURSELVES is
    // what makes it look like this app.
    function define(name, ctor) {
        if (!window.customElements.get(name)) window.customElements.define(name, ctor);
    }

    function defineShims() {
        define('ha-card', class extends HTMLElement {
            static get observedAttributes() { return ['header']; }
            connectedCallback() { this._render(); }
            attributeChangedCallback() { this._render(); }
            _render() {
                if (!this.shadowRoot) {
                    this.attachShadow({ mode: 'open' });
                    this.shadowRoot.innerHTML =
                        '<style>' +
                        ':host{display:block;background:var(--ha-card-background,transparent);' +
                        'border-radius:var(--ha-card-border-radius,0);color:var(--primary-text-color);' +
                        'box-shadow:var(--ha-card-box-shadow,none);width:100%;height:100%;}' +
                        '.h{font-weight:800;font-size:1rem;padding:0 0 .5rem;color:var(--primary-text-color);}' +
                        '</style><div class="h" hidden></div><slot></slot>';
                }
                var h = this.shadowRoot.querySelector('.h');
                var text = this.getAttribute('header') || '';
                h.textContent = text;
                h.hidden = !text;
            }
        });

        // The icons come from Home Assistant's own MDI chunks, through our
        // proxy — see ha_cards.mdi_path. An icon that cannot be resolved
        // renders NOTHING rather than the literal string `mdi:foo`, which is
        // the rule the existing HA tile already settled.
        define('ha-icon', class extends HTMLElement {
            static get observedAttributes() { return ['icon']; }
            connectedCallback() { this._render(); }
            attributeChangedCallback() { this._render(); }
            _render() {
                if (!this.shadowRoot) {
                    this.attachShadow({ mode: 'open' });
                    this.shadowRoot.innerHTML =
                        '<style>:host{display:inline-flex;align-items:center;justify-content:center;' +
                        'width:var(--mdc-icon-size,24px);height:var(--mdc-icon-size,24px);}' +
                        'svg{width:100%;height:100%;fill:currentColor;}</style><span></span>';
                }
                var slot = this.shadowRoot.querySelector('span');
                var name = this.getAttribute('icon') || '';
                if (!name) { slot.innerHTML = ''; return; }
                iconPath(name).then(function (d) {
                    slot.innerHTML = d
                        ? '<svg viewBox="0 0 24 24"><path d="' + d + '"></path></svg>'
                        : '';
                });
            }
        });

        // The icon for an ENTITY rather than for a name. HA's own frontend
        // works out which glyph a state deserves — an open door, a charging
        // battery — and cards that show entities reach for this rather than
        // for `ha-icon`. Mushroom uses it 23 times, so without it every
        // mushroom card on the board draws its text and no icon at all.
        //
        // The lookup is the same table the native cards use, which is the
        // point: one icon system for the board, not two that disagree.
        define('ha-state-icon', class extends HTMLElement {
            static get observedAttributes() { return ['icon']; }
            set stateObj(v) { this._state = v; this._render(); }
            get stateObj() { return this._state; }
            set hass(v) { /* the state object is what this needs */ }
            connectedCallback() { this._render(); }
            attributeChangedCallback() { this._render(); }
            _render() {
                if (!this.shadowRoot) {
                    this.attachShadow({ mode: 'open' });
                    this.shadowRoot.innerHTML =
                        '<style>:host{display:inline-flex;align-items:center;' +
                        'justify-content:center;width:var(--mdc-icon-size,24px);' +
                        'height:var(--mdc-icon-size,24px);}' +
                        'svg{width:100%;height:100%;fill:currentColor;}</style><span></span>';
                }
                var slot = this.shadowRoot.querySelector('span');
                var st = this._state || {};
                var attrs = st.attributes || {};
                var name = this.getAttribute('icon') || attrs.icon
                    || domainIcon(String(st.entity_id || ''), attrs, st.state);
                if (!name) { slot.innerHTML = ''; return; }
                iconPath(name).then(function (d) {
                    slot.innerHTML = d
                        ? '<svg viewBox="0 0 24 24"><path d="' + d + '"></path></svg>'
                        : '';
                });
            }
        });

        // Same picture, path data supplied directly as a property. Cards that
        // bundle their own icons use this one and never touch the network.
        define('ha-svg-icon', class extends HTMLElement {
            set path(v) { this._path = v; this._render(); }
            get path() { return this._path; }
            connectedCallback() { this._render(); }
            _render() {
                if (!this.shadowRoot) {
                    this.attachShadow({ mode: 'open' });
                    this.shadowRoot.innerHTML =
                        '<style>:host{display:inline-flex;width:var(--mdc-icon-size,24px);' +
                        'height:var(--mdc-icon-size,24px);}svg{width:100%;height:100%;fill:currentColor;}' +
                        '</style><span></span>';
                }
                this.shadowRoot.querySelector('span').innerHTML = this._path
                    ? '<svg viewBox="0 0 24 24"><path d="' + this._path + '"></path></svg>' : '';
            }
        });

        // A card's own error state, which is a thing we must NOT swallow: a
        // card saying "entity not found" is the card working correctly and the
        // household needing to fix a name.
        define('hui-warning', class extends HTMLElement {
            connectedCallback() {
                if (this.shadowRoot) return;
                this.attachShadow({ mode: 'open' });
                this.shadowRoot.innerHTML =
                    '<style>:host{display:block;color:var(--warning-color);font-size:.85rem;' +
                    'padding:.35rem 0;}</style><slot></slot>';
            }
        });

        define('ha-alert', class extends HTMLElement {
            connectedCallback() {
                if (this.shadowRoot) return;
                this.attachShadow({ mode: 'open' });
                this.shadowRoot.innerHTML =
                    '<style>:host{display:block;color:var(--warning-color);font-size:.85rem;}' +
                    '</style><slot></slot>';
            }
        });

        // Decoration with no meaning off a touch surface, and a button that is
        // just a button. Defined so the card's layout does not collapse around
        // an unknown (therefore inline, therefore differently sized) element.
        define('ha-ripple', class extends HTMLElement { });
        define('ha-icon-button', class extends HTMLElement {
            connectedCallback() {
                this.style.display = 'inline-flex';
                this.style.cursor = 'pointer';
            }
        });

        // Cards ask for this to build sub-cards (a card inside a card). We do
        // not host that, and the honest answer is a rejected promise the card
        // can catch — a helpers object that returns broken elements would fail
        // later and further away.
        if (!window.loadCardHelpers) {
            window.loadCardHelpers = function () {
                return Promise.reject(new Error(
                    "Chauffeur hosts one card at a time; nested cards need Home Assistant."));
            };
        }
    }

    // A per-domain glyph, so an entity with no icon of its own still draws
    // something. Deliberately SHORT: the server's table
    // (ha_card_convert._icon_for) is the real one, and it is the one that runs
    // for every entity a native card shows. This exists only for hosted cards,
    // which hand us a state object rather than an icon name.
    var DOMAIN_ICON = {
        light: 'mdi:lightbulb', switch: 'mdi:toggle-switch', fan: 'mdi:fan',
        lock: 'mdi:lock', cover: 'mdi:window-shutter', climate: 'mdi:thermostat',
        sensor: 'mdi:eye', binary_sensor: 'mdi:checkbox-marked-circle',
        person: 'mdi:account', media_player: 'mdi:speaker', camera: 'mdi:camera',
        input_boolean: 'mdi:toggle-switch-outline', vacuum: 'mdi:robot-vacuum',
        scene: 'mdi:palette', script: 'mdi:script-text', automation: 'mdi:robot',
    };
    function domainIcon(entityId, attrs, state) {
        var domain = String(entityId).split('.')[0];
        if (domain === 'lock') {
            return String(state).toLowerCase() === 'unlocked'
                ? 'mdi:lock-open' : 'mdi:lock';
        }
        return DOMAIN_ICON[domain] || 'mdi:eye';
    }

    // What `on` MEANS for a binary sensor, per device class. Same table as the
    // server's, and the duplication is the point: `hass.states` carries raw
    // states because cards branch on them, so only the DISPLAY is translated.
    var BINARY_STATE = {
        motion: ['Detected', 'Clear'], occupancy: ['Detected', 'Clear'],
        presence: ['Home', 'Away'], moisture: ['Wet', 'Dry'],
        door: ['Open', 'Closed'], garage_door: ['Open', 'Closed'],
        window: ['Open', 'Closed'], opening: ['Open', 'Closed'],
        smoke: ['Detected', 'Clear'], gas: ['Detected', 'Clear'],
        problem: ['Problem', 'OK'], safety: ['Unsafe', 'Safe'],
        connectivity: ['Connected', 'Disconnected'],
        battery: ['Low', 'Normal'], running: ['Running', 'Not running'],
        lock: ['Unlocked', 'Locked'], tamper: ['Detected', 'Clear'],
        plug: ['Plugged in', 'Unplugged'], sound: ['Detected', 'Clear'],
        vibration: ['Detected', 'Clear'], update: ['Available', 'Up-to-date'],
    };
    var SAYABLE = ['on', 'off', 'open', 'closed', 'locked', 'unlocked', 'home',
        'idle', 'jammed', 'opening', 'closing', 'locking', 'unlocking',
        'unavailable', 'unknown'];
    function stateLabel(stateObj) {
        var raw = String((stateObj && stateObj.state) ?? '');
        if (!raw) return '';
        var attrs = (stateObj && stateObj.attributes) || {};
        var low = raw.toLowerCase();
        var domain = String(stateObj.entity_id || '').split('.')[0];
        if (domain === 'binary_sensor') {
            var pair = BINARY_STATE[String(attrs.device_class || '').toLowerCase()];
            if (pair) return low === 'on' ? pair[0] : (low === 'off' ? pair[1] : raw);
        }
        if (low === 'not_home') return 'Away';
        if (SAYABLE.indexOf(low) >= 0) {
            return low.charAt(0).toUpperCase() + low.slice(1);
        }
        return raw;
    }

    // ── Icons, resolved once per name for the life of the page.
    var iconCache = {};
    function iconPath(name) {
        if (iconCache[name] !== undefined) return Promise.resolve(iconCache[name]);
        var clean = String(name).replace(/^mdi:/, '');
        if (!/^[a-z0-9-]+$/.test(clean)) { iconCache[name] = null; return Promise.resolve(null); }
        return fetch(API.base + 'api/ha/card/mdi/' + clean)
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (j) {
                iconCache[name] = (j && j.path) || null;
                return iconCache[name];
            })
            .catch(function () { iconCache[name] = null; return null; });
    }

    // ── The card's own JavaScript, fetched through our proxy so it arrives on
    // this origin. Once per URL per page, however many tiles want it.
    var loading = {};
    function loadResource(url, type) {
        if (loading[url]) return loading[url];
        loading[url] = new Promise(function (resolve, reject) {
            var el = document.createElement('script');
            el.src = API.base + 'api/ha/card/resource?url=' + encodeURIComponent(url);
            // The declared type matters: a bundle written as a classic script
            // with top-level `var` globals behaves differently in module scope.
            // HA tells us which it registered, and we believe it.
            if (type !== 'js') el.type = 'module';
            el.onload = function () { resolve(true); };
            el.onerror = function () {
                // WITH THE PATH. A script tag's error event carries nothing —
                // no status, no body — so the only thing this can usefully add
                // is where it looked, and that is exactly what the next person
                // debugging it needs in their hand.
                reject(new Error("Home Assistant would not hand over " + url));
            };
            document.head.appendChild(el);
        });
        return loading[url];
    }

    // ── `hass`.
    //
    // Rebuilt on every board poll rather than mutated, because a Lit card
    // decides whether to re-render by comparing the old object with the new
    // one. Mutating in place is how an embedded card goes quietly stale.
    // The board's shared pool: the whole house, attached to the payload once
    // when a board hosts any custom card, so a card that DISCOVERS its
    // devices by walking `hass.states` finds them without anyone having to
    // know which parts of the house it walks. Set by the board before each
    // sync; empty on pages that never set it.
    var statesPool = {};

    function setStates(pool) { statesPool = pool || {}; }

    function makeHass(spec) {
        // Named states win over the pool: they carry the same rows, and if
        // the two ever disagree the per-card slice is the one `missing` was
        // computed against.
        var states = {};
        var k;
        for (k in statesPool) states[k] = statesPool[k];
        for (k in (spec.states || {})) states[k] = (spec.states || {})[k];
        return {
            states: states,
            // hui-image wipes its loaded photograph on any hass update
            // where `hass.connected` is falsy — HA's "connection lost, stop
            // showing stale frames" behaviour. This hass is rebuilt fresh on
            // every board poll, so an absent flag read as "disconnected
            // twenty times a minute": the photo survived until the first
            // poll and then blanked forever (a cached img never refires
            // `load` for an unchanged src, and in ratio mode the visible
            // pixels are the background that only `load` repopulates).
            connected: true,
            // Enough of the shape that a card reading these does not throw.
            // Empty-string localize is HA's own behaviour for an unknown key,
            // and cards written against it use `|| fallback`.
            localize: function () { return ''; },
            // The state as a person would say it. A mushroom lock card asks for
            // this and prints whatever comes back, so returning the raw state
            // put a lower-case `unlocked` on the wall where Home Assistant says
            // `Unlocked`.
            //
            // The table is a small duplicate of the server's
            // (ha_card_convert._state_label) and has to be: `hass.states` must
            // carry the RAW state, because a card branches on `'on'` and
            // `'unlocked'` to decide what to draw. Only the DISPLAY is pretty,
            // and only through this function.
            formatEntityState: function (stateObj) { return stateLabel(stateObj); },
            formatEntityAttributeValue: function (stateObj, attr) {
                return String(((stateObj || {}).attributes || {})[attr] ?? '');
            },
            formatEntityAttributeName: function (stateObj, attr) { return String(attr); },
            language: 'en',
            locale: { language: 'en', number_format: 'language', time_format: 'language' },
            // Mushroom reads `hass.translationMetadata.translations[language]`
            // while working out which language to format in, and reads it
            // OUTSIDE a try — so an absent one threw mid-render and the card
            // left an empty box on the wall. Nothing about that failure said
            // which field was missing, which is the argument for filling in
            // the whole shape rather than the parts a card is known to touch.
            translationMetadata: {
                fragments: [],
                translations: { en: { nativeName: 'English', isRTL: false } },
            },
            // Read as `hass.services[domain]` by the editors when they
            // decide which controls an entity's domain offers. Empty means
            // "offer nothing extra"; ABSENT meant a throw.
            services: {},
            themes: { darkMode: spec.dark !== false, theme: 'default', themes: {} },
            config: {
                unit_system: { temperature: '°F', length: 'mi', mass: 'lb',
                    volume: 'gal', pressure: 'psi', wind_speed: 'mph',
                    accumulated_precipitation: 'in' },
                language: 'en', country: null, currency: 'USD',
                time_zone: 'local', components: [], state: 'RUNNING',
                version: 'chauffeur',
            },
            // The entity/device/area REGISTRIES, which are a websocket away and
            // not something the board ships. Empty objects rather than absent:
            // a card indexing into an empty map gets undefined and falls back,
            // and a card indexing into `undefined` throws.
            entities: {},
            devices: {},
            areas: {},
            // Cards build absolute URLs with this (a camera still, an icon).
            // Root-relative is right under ingress and right standalone.
            hassUrl: function (path) { return String(path || ''); },
            user: { name: 'Panel', is_admin: false, is_owner: false },
            // A card that wants live statistics is asking for a websocket we
            // are not holding open. Rejecting is what lets it fall back or say
            // so; a promise that never settles would leave a spinner up.
            connection: {
                subscribeMessage: function () {
                    return Promise.reject(new Error('no websocket in the panel'));
                },
                subscribeEvents: function () {
                    return Promise.resolve(function () { });
                },
                addEventListener: function () { },
                removeEventListener: function () { },
            },
            callWS: function () {
                return Promise.reject(new Error('no websocket in the panel'));
            },
            callService: function (domain, service, data) {
                if (!spec.interactive) {
                    return Promise.reject(new Error('this tile is read-only'));
                }
                return fetch(API.base + 'api/ha/card/service', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ domain: domain, service: service, data: data || {} }),
                }).then(function (r) {
                    if (!r.ok) throw new Error('Home Assistant refused that');
                    return {};
                });
            },
        };
    }

    var API = { base: '' };

    // ── Mounting.
    //
    // One live card per tile id. Re-mounting on every poll would throw away a
    // card's internal animation state twenty times a minute, so a mount that
    // is already showing the right card in the right container is UPDATED —
    // only its `hass` changes — and rebuilt only when the tile's config or its
    // container actually changed.
    var mounted = {};

    function themeFrom(container) {
        var probe = getComputedStyle(container);
        var out = {};
        Object.keys(THEME).forEach(function (k) {
            var src = THEME[k];
            out[k] = src.indexOf('--') === 0 ? (probe.getPropertyValue(src) || '').trim() : src;
            if (!out[k]) delete out[k];
        });
        Object.keys(THEME_FIXED).forEach(function (k) { out[k] = THEME_FIXED[k]; });
        return out;
    }

    function fail(container, message) {
        container.textContent = '';
        var p = document.createElement('div');
        p.className = 'ha-card-host-error';
        p.textContent = message;
        container.appendChild(p);
    }

    // ── Cards whose layout is a function of their own width.
    //
    // Not a niche case: tesla-style-solar-power-card computes
    // `pxRate = getBoundingClientRect().width / 100` inside render() and sizes
    // every bubble, line and gap from it. A card like that measures ONCE per
    // render, and a Lit card only re-renders when a property changes — which
    // here means when the board next polls, up to a minute later. So a card
    // mounted before its cell has settled, or sitting in a tile somebody has
    // just resized, draws its whole diagram against a width that is no longer
    // true and every element lands slightly wrong.
    //
    // Re-assigning `hass` is the smallest thing that makes it re-render, and
    // re-rendering is what makes it re-measure.
    function watchWidth(held) {
        if (!window.ResizeObserver || held.observer) return;
        var last = held.container.clientWidth;
        held.observer = new ResizeObserver(function () {
            var now = held.container.clientWidth;
            // Whole pixels only. Sub-pixel jitter from a scrollbar appearing
            // would otherwise re-render every card on the board continuously.
            if (Math.abs(now - last) < 1) return;
            last = now;
            clearTimeout(held.resizeTimer);
            held.resizeTimer = setTimeout(function () {
                try {
                    held.el.hass = held.builtin ? buildBuiltinHass(held.spec)
                                                : makeHass(held.spec);
                } catch (e) { /* gone */ }
            }, 120);
        });
        held.observer.observe(held.container);
    }

    // A board poll re-renders the tile tree, and Alpine's x-html hands every
    // host a NEW cell — with the old one, and the live card inside it, gone.
    // Rebuilding the card there restarted its animations and, for the hosted
    // built-ins, painted the converter fallback for a frame first: the wall
    // flashed the imitation on every poll. The card is not stale — only its
    // cell is — so an unchanged card is MOVED into the new cell instead.
    // syncCards runs in the same task as the re-render ($nextTick, before
    // paint), so the move is invisible.
    function adopt(live, container, spec, buildHass) {
        live.spec = spec;
        if (live.container !== container) {
            // The new cell is bare: it needs the same theme dress the
            // original mount gave the old one, or the moved card keeps its
            // shape and loses its colours.
            if (live.builtin) {
                container.classList.add('ha-builtin-theme');
                container.classList.toggle('ha-dark', spec.dark !== false);
            }
            var theme = themeFrom(container);
            Object.keys(theme).forEach(function (k) {
                container.style.setProperty(k, theme[k]);
            });
            container.textContent = '';
            container.appendChild(live.el);
            live.container = container;
            if (live.observer) { live.observer.disconnect(); live.observer = null; }
            watchWidth(live);
        }
        try { live.el.hass = buildHass(spec); } catch (e) { /* mid-teardown */ }
        return Promise.resolve(true);
    }

    function mount(container, spec) {
        if (!container || !spec) return Promise.resolve(false);
        API.base = spec.apiBase || '';
        defineShims();

        var signature = JSON.stringify([spec.tag, spec.resource, spec.config]);
        var live = mounted[spec.id];
        if (live && live.signature === signature && !live.builtin && live.el) {
            return adopt(live, container, spec, makeHass);
        }

        var theme = themeFrom(container);
        Object.keys(theme).forEach(function (k) { container.style.setProperty(k, theme[k]); });

        return loadResource(spec.resource, spec.resourceType).then(function () {
            // A bundle can load and still not define what we asked for —
            // wrong file, or a card that needs frontend internals and threw on
            // the way up. whenDefined would wait forever, so it races a clock.
            return Promise.race([
                window.customElements.whenDefined(spec.tag),
                new Promise(function (_, reject) {
                    setTimeout(function () {
                        reject(new Error('`' + spec.tag + '` never appeared. That file may ' +
                            'define a different card, or need Home Assistant\'s own frontend.'));
                    }, 8000);
                }),
            ]);
        }).then(function () {
            var el = document.createElement(spec.tag);
            // setConfig is where a card validates the YAML, and its complaint
            // is the most useful sentence in this whole flow — it is written
            // for the person who wrote the config. Pass it straight through.
            try {
                el.setConfig(JSON.parse(JSON.stringify(spec.config)));
            } catch (e) {
                throw new Error('The card rejected its config: ' + (e && e.message || e));
            }
            el.hass = makeHass(spec);
            el.style.display = 'block';
            container.textContent = '';
            container.appendChild(el);
            var held = { el: el, container: container, signature: signature, spec: spec };
            mounted[spec.id] = held;
            watchWidth(held);
            return true;
        }).catch(function (e) {
            delete mounted[spec.id];
            fail(container, (e && e.message) || 'That card would not load.');
            return false;
        });
    }

    // ── Which cards this household actually has.
    //
    // There is no server-side answer to this and there cannot be: a file's name
    // does not tell you which elements it defines — `mushroom.js` defines about
    // thirty. What every card bundle DOES do, by a convention as old as custom
    // cards, is push itself onto `window.customCards` as it loads:
    //
    //     window.customCards.push({type, name, description, preview})
    //
    // which is the registry Home Assistant's own card picker reads. So the way
    // to find out is to load them and look, and that is all this does.
    //
    // Loading every bundle is not free — it is the cost of opening the picker,
    // once per page — so it happens on demand rather than at board load.
    function discover(resources, apiBase) {
        API.base = apiBase || '';
        defineShims();
        window.customCards = window.customCards || [];
        var loads = (resources || []).map(function (r) {
            // A bundle that will not load must not take the picker with it:
            // one broken resource would otherwise hide every card the
            // household has.
            return loadResource(r.url, r.type).catch(function () { return false; });
        });
        return Promise.all(loads).then(function () {
            var seen = {}, out = [];
            (window.customCards || []).forEach(function (c) {
                if (!c || !c.type || seen[c.type]) return;
                seen[c.type] = true;
                out.push({ type: c.type, name: c.name || c.type,
                           description: c.description || '' });
            });
            out.sort(function (a, b) { return a.name.localeCompare(b.name); });
            return out;
        });
    }

    // ── A card's OWN visual editor.
    //
    // Every card worth configuring ships one, in the bundle we already fetch:
    //
    //     static async getConfigElement()
    //
    // The editor is an ordinary Lit element that takes `hass` and
    // `setConfig(config)` and fires `config-changed` with the new config. What
    // stopped this working was never the editor — it was `ha-form` and the
    // pickers it renders, which live in HA's frontend. static/ha_form.js is
    // those, so this is now mostly plumbing.
    //
    // `onChange` is called with the card's own idea of its config, which is the
    // thing worth having: a card validates, fills in defaults and normalises
    // shorthand on its way through, so what comes back is better than what a
    // form would have assembled from the fields alone.
    function mountEditor(container, spec, onChange) {
        if (!spec || !spec.tag) return Promise.resolve(false);
        API.base = spec.apiBase || '';
        defineShims();

        return ensureForm().then(function () {
            return loadResource(spec.resource, spec.resourceType);
        }).then(function () {
            return Promise.race([
                window.customElements.whenDefined(spec.tag),
                new Promise(function (_, reject) {
                    setTimeout(function () {
                        reject(new Error('`' + spec.tag + '` never appeared.'));
                    }, 8000);
                }),
            ]);
        }).then(function () {
            var ctor = window.customElements.get(spec.tag);
            if (!ctor || typeof ctor.getConfigElement !== 'function') {
                // NAMED, not blank. Plenty of cards ship without an editor and
                // are configured by hand in Home Assistant too — that is a fact
                // about the card, not a failure here, and the YAML box below is
                // still the way to configure it.
                throw new Error('This card has no visual editor of its own. '
                    + 'Its YAML is the way to configure it.');
            }
            return ctor.getConfigElement();
        }).then(function (el) {
            if (!el) throw new Error('That card would not open its editor.');
            el.hass = makeHass(spec);
            try {
                el.setConfig(JSON.parse(JSON.stringify(spec.config || {})));
            } catch (e) {
                // A card refusing its own config in the EDITOR is the useful
                // case: it is the sentence that says which line is wrong.
                throw new Error('The card rejected its config: ' + (e && e.message || e));
            }
            el.addEventListener('config-changed', function (e) {
                if (e && e.detail && e.detail.config) onChange(e.detail.config);
            });
            container.textContent = '';
            container.appendChild(el);
            return true;
        }).catch(function (e) {
            fail(container, (e && e.message) || 'That editor would not load.');
            return false;
        });
    }

    function unmount(id) {
        var live = mounted[id];
        if (!live) return;
        try { live.el.remove(); } catch (e) { /* already gone with its tile */ }
        delete mounted[id];
    }

    // ── Hosting HA's OWN built-in cards.
    //
    // Everything above runs a CUSTOM card — a file HA merely serves. The
    // built-ins have no file; they live inside HA's frontend bundle. The
    // server (services/ha_frontend.py) reads that bundle once per HA release:
    // the entrypoint patched into a loader that boots nothing, the chunk set
    // the lovelace panel loads, and HA's own card table. This half drives it:
    // load the runtime, load the chunks, require the card modules, and the
    // real hui-* elements define themselves — HA's pixels, HA's controls,
    // HA's resize behaviour, none of it reimplemented here.
    //
    // Every step can refuse (no HA, an extraction miss on some future
    // release, a type this HA does not ship). Refusal is CHEAP by design:
    // the board draws the converter's fallback into every host cell first,
    // and a builtin mount that never happens simply leaves it standing.
    var builtin = {
        boot: null, ready: false, map: {}, chunks: [], eager: [],
        reg: { entities: {}, devices: {}, areas: {}, config: {} },
        ctxInstalled: false,
    };

    function waitFor(test, ms) {
        return new Promise(function (resolve) {
            var t0 = Date.now();
            (function poll() {
                if (test()) return resolve(true);
                if (Date.now() - t0 > ms) return resolve(false);
                setTimeout(poll, 100);
            })();
        });
    }

    function bootBuiltin(apiBase) {
        if (builtin.boot) return builtin.boot;
        if (apiBase) API.base = apiBase;
        builtin.boot = fetch(API.base + 'api/ha/frontend/bundle')
            .then(function (r) { return r.ok ? r.json() : { ok: false }; })
            .then(function (b) {
                if (!b.ok) throw new Error(b.error || 'no bundle from the server');
                builtin.map = b.cards || {};
                builtin.chunks = b.chunks || [];
                builtin.eager = b.eager_modules || [];
                builtin.reg = {
                    entities: b.entities || {}, devices: b.devices || {},
                    areas: b.areas || {}, config: b.config || {},
                };
                builtin.i18n = b.i18n || {};
                if ((b.config || {}).version) {
                    NO_WS.haVersion = b.config.version;
                }
                loadUiStrings();          // no await: labels catch up
                // Registry pictures arrive proxy-relative. hui-image runs
                // EVERY src through hass.hassUrl, which strips one leading
                // slash and prepends the api base — so the stored value must
                // be root-absolute for that arithmetic to land, on a direct
                // origin and under ingress alike. (The first cut prepended
                // the base here TOO, and hassUrl doubled it into a path one
                // directory too high: no photographs on any route.)
                Object.keys(builtin.reg.areas).forEach(function (k) {
                    var a = builtin.reg.areas[k];
                    if (a.picture && !/^(https?:)?\//.test(a.picture)) {
                        a.picture = '/' + a.picture;
                    }
                });
                // And an hourly freshness tick. hui-image latches a failed
                // load — one blipped fetch (a tunnel hiccup on a wall that
                // runs for days) is a photograph gone until something makes
                // the image PROPERTY change. A version suffix that moves
                // once an hour is that something: the next hass refresh
                // re-resolves, re-fetches, and a transient failure stops
                // being forever.
                builtin.picTick = setInterval(function () {
                    Object.keys(builtin.reg.areas).forEach(function (k) {
                        var a = builtin.reg.areas[k];
                        if (a.picture) {
                            a.picture = a.picture.split('?')[0]
                                + '?v=' + Math.floor(Date.now() / 3600000);
                        }
                    });
                }, 3600000);
                installContextProvider();
                // HA's default tokens, class-scoped to host cells. Without
                // them the real cards draw geometry with no stroke — every
                // state colour and slider track is a theme variable the app
                // shell would have set.
                var css = document.createElement('link');
                css.rel = 'stylesheet';
                css.href = API.base + 'api/ha/frontend/theme/' + b.version + '.css';
                document.head.appendChild(css);
                var s = document.createElement('script');
                s.type = 'module';
                s.src = API.base + b.runtime;
                document.head.appendChild(s);
                return waitFor(function () { return window.__haWpr; }, 15000);
            })
            .then(function (up) {
                if (!up) throw new Error('the borrowed runtime never appeared');
                var o = window.__haWpr;
                return Promise.all(builtin.chunks.map(function (c) { return o.e(c); }));
            })
            .then(function () {
                // Each eager module on its own: one card of a release failing
                // to define must not take the other twelve with it.
                var o = window.__haWpr;
                return Promise.all(builtin.eager.map(function (m) {
                    return Promise.resolve().then(function () { return o(m); })
                        .catch(function (e) {
                            console.warn('[ha_card_host] eager module ' + m + ':',
                                e && e.message);
                        });
                }));
            })
            .then(function () {
                // `hui-image` — the element the AREA card renders its
                // photograph through — is not in any eager card's import
                // graph; inside HA the view machinery pulls it in. Its
                // chunk sat REGISTERED in the lovelace set while the module
                // never executed, so the card rendered an unknown element:
                // properties landed as expandos, no shadow root, no
                // request, nothing in the console. The picture-entity card
                // imports it by definition, so requiring that one lazy
                // entry defines it for everybody — release-proof, because
                // the map is HA's own.
                var row = builtin.map['picture-entity'];
                if (!row) return;
                var o = window.__haWpr;
                return Promise.all((row.chunks || []).map(function (c) {
                    return o.e(c);
                })).then(function () { return o(row.module); })
                    .catch(function (e) {
                        console.warn('[ha_card_host] picture-entity preload:',
                            e && e.message);
                    });
            })
            .then(function () { builtin.ready = true; return true; })
            .catch(function (e) {
                console.warn('[ha_card_host] builtin cards unavailable:',
                    e && e.message);
                builtin.ready = false;
                return false;
            });
        return builtin.boot;
    }

    // ── The app-shell contexts.
    //
    // Inside HA, deep components (the climate dial, the big number) do not
    // read `hass` — they consume lit contexts the <home-assistant> element
    // provides. A lit context request is an ordinary composed DOM event and
    // HA's keys are the plain strings its createContext calls pass, so one
    // document-level listener stands in for the whole shell.
    var LOCALE = {
        language: 'en', number_format: 'language', time_format: 'language',
        date_format: 'language', first_weekday: 'language', time_zone: 'local',
    };

    var GENERIC_TAILS = { label: 1, name: 1, title: 1, value: 1,
                          header: 1, description: 1 };

    function humanize(key) {
        var parts = String(key || '').split('.');
        var last = parts.pop();
        // `...types.climate-hvac-modes.label` should read "climate hvac
        // modes", not "label" -- the tail is the field, the segment before
        // it is the subject.
        if (GENERIC_TAILS[last] && parts.length) last = parts.pop();
        return last.replace(/[-_]/g, ' ');
    }

    // -- The REAL ui.* strings.
    //
    // Every label the editors show is a `ui.*` key resolved against HA's
    // fingerprinted translation files -- a humanizer can only echo key
    // tails, which is how a feature row came to be called "label". The
    // files are static and unauthenticated; the fingerprints ride the
    // bundle. Fetched once, flattened, substituted the way HA's own
    // localize does; anything not found falls back to the humanizer.
    var uiStrings = null;                 // flat { 'ui.a.b': 'text' }

    function flattenInto(out, prefix, node) {
        Object.keys(node || {}).forEach(function (k) {
            var v = node[k];
            var path = prefix ? prefix + '.' + k : k;
            if (v && typeof v === 'object') flattenInto(out, path, v);
            else out[path] = String(v);
        });
    }

    function loadUiStrings() {
        var i18n = builtin.i18n || {};
        if (!i18n.hash || uiStrings) return Promise.resolve();
        var flat = {};
        uiStrings = flat;                 // one attempt per page
        // The base file plus the fragments the cards and their editors
        // read from. The rest of the app's fragments are pages we are not
        // hosting.
        var want = [''].concat((i18n.fragments || []).filter(function (f) {
            return f === 'lovelace' || f === 'config';
        }));
        return Promise.all(want.map(function (frag) {
            var path = (frag ? frag + '/' : '') + 'en-' + i18n.hash + '.json';
            return fetch(API.base + 'static/translations/' + path)
                .then(function (r) { return r.ok ? r.json() : {}; })
                .then(function (data) { flattenInto(flat, '', data); })
                .catch(function () { });
        }));
    }

    function localize(key) {
        var text = uiStrings && uiStrings[key];
        if (text == null) return humanize(key);
        // localize('key', {name: x}) and the older ('key', 'name', x) both
        // appear in card code; substitute either shape.
        var args = arguments;
        if (args.length === 2 && args[1] && typeof args[1] === 'object') {
            Object.keys(args[1]).forEach(function (k) {
                text = text.split('{' + k + '}').join(String(args[1][k]));
            });
        } else {
            for (var i = 1; i + 1 < args.length; i += 2) {
                text = text.split('{' + args[i] + '}').join(String(args[i + 1]));
            }
        }
        return text;
    }

    // The i18n shape the REAL editors consume (the cards read localize off
    // hass; the editors reach for the whole machine). Backend translations
    // resolve to the same humanizer — a mode reading "heat cool" instead of
    // a localized string is the accepted cost of not booting HA's app.
    function builtinI18n() {
        return {
            language: 'en', locale: LOCALE, localize: localize,
            translations: {}, resources: { en: {} },
            translationMetadata: {
                fragments: [],
                translations: { en: { nativeName: 'English', isRTL: false } },
            },
            // Read as `hass.services[domain]` by the editors when they
            // decide which controls an entity's domain offers. Empty means
            // "offer nothing extra"; ABSENT meant a throw.
            services: {},
            loadBackendTranslation: loadBackendTranslation,
            loadFragmentTranslation: function () {
                return Promise.resolve(localize);
            },
        };
    }

    // Backend categories (entity names by translation key, `title`
    // strings) come over the proxied websocket lane and MERGE into the
    // same flat map the ui strings live in -- one localize, every source.
    var backendLoaded = {};
    function loadBackendTranslation(category, integration) {
        var key = String(category || '') + '/' + String(integration || '');
        if (!backendLoaded[key]) {
            backendLoaded[key] = fetch(API.base
                + 'api/ha/frontend/translations?category='
                + encodeURIComponent(category || 'title')
                + (integration ? '&integration='
                    + encodeURIComponent(integration) : ''))
                .then(function (r) { return r.ok ? r.json() : {}; })
                .then(function (data) {
                    if (uiStrings) {
                        flattenInto(uiStrings, '', (data || {}).resources || {});
                    }
                })
                .catch(function () { });
        }
        return backendLoaded[key].then(function () { return localize; });
    }

    // The two websocket message types the borrowed code sends that have a
    // REST answer here. Everything else stays refused -- a promise that
    // never settles is a spinner forever.
    function wsBridge(msg) {
        if (!msg || !msg.type) return null;
        // A camera card asking what stream flavours the frontend can have:
        // none — HLS and WebRTC negotiate over the websocket. Answering
        // (rather than rejecting) steers ha-camera-stream to its still/MJPEG
        // branch, which the /api/camera_proxy lanes serve.
        if (msg.type === 'camera/capabilities') {
            return Promise.resolve({ frontend_stream_types: [] });
        }
        if (msg.type === 'frontend/get_icons') {
            return fetch(API.base + 'api/ha/frontend/icons?category='
                + encodeURIComponent(msg.category || '')
                + (msg.integration ? '&integration='
                    + encodeURIComponent(msg.integration) : ''))
                .then(function (r) {
                    if (!r.ok) throw new Error('icons unavailable');
                    return r.json();
                });
        }
        if (msg.type === 'frontend/get_translations') {
            return fetch(API.base + 'api/ha/frontend/translations?category='
                + encodeURIComponent(msg.category || '')
                + '&language=' + encodeURIComponent(msg.language || 'en')
                + (msg.integration ? '&integration='
                    + encodeURIComponent(msg.integration) : '')
                + (msg.config_flow ? '&config_flow=1' : ''))
                .then(function (r) {
                    if (!r.ok) throw new Error('translations unavailable');
                    return r.json();
                });
        }
        return null;
    }

    function haConfig() {
        var cfg = builtin.reg.config || {};
        return {
            components: cfg.components || ['history', 'recorder'],
            unit_system: cfg.unit_system && cfg.unit_system.temperature
                ? cfg.unit_system
                : { temperature: '°F', length: 'mi', mass: 'lb', volume: 'gal',
                    pressure: 'psi', wind_speed: 'mph',
                    accumulated_precipitation: 'in', area: 'ft²' },
            time_zone: cfg.time_zone || 'local',
            version: cfg.version || '',
            latitude: cfg.latitude, longitude: cfg.longitude,
            state: 'RUNNING',
        };
    }

    function displayPrecision(stateObj) {
        var reg = builtin.reg.entities[(stateObj || {}).entity_id] || {};
        return reg.display_precision == null ? null : reg.display_precision;
    }

    // The state, as Intl parts — HA's cards pick the unit part out to
    // typeset it small, so the SHAPE matters as much as the text.
    function formatStateToParts(stateObj, stateOverride) {
        var raw = stateOverride != null ? stateOverride : (stateObj || {}).state;
        var n = Number(raw);
        var parts;
        if (raw !== '' && raw != null && isFinite(n)) {
            var digits = displayPrecision(stateObj);
            parts = new Intl.NumberFormat(undefined, {
                maximumFractionDigits: digits == null ? 2 : digits,
                minimumFractionDigits: digits == null ? 0 : digits,
            }).formatToParts(n);
        } else {
            parts = [{ type: 'literal', value: stateLabel(stateObj) }];
        }
        var unit = ((stateObj || {}).attributes || {}).unit_of_measurement;
        if (unit) {
            parts = parts.concat([{ type: 'literal', value: ' ' },
                                  { type: 'unit', value: unit }]);
        }
        return parts;
    }

    function builtinFormatters() {
        return {
            formatEntityState: function (stateObj, state) {
                return formatStateToParts(stateObj, state)
                    .map(function (p) { return p.value; }).join('')
                    .replace(/ $/, '');
            },
            formatEntityStateToParts: formatStateToParts,
            formatEntityAttributeValue: function (stateObj, attr) {
                var v = ((stateObj || {}).attributes || {})[attr];
                return v == null ? '' : humanize(String(v));
            },
            formatEntityAttributeName: function (stateObj, attr) {
                return humanize(String(attr));
            },
            formatEntityName: function (stateObj) {
                var reg = builtin.reg.entities[(stateObj || {}).entity_id] || {};
                return reg.name
                    || ((stateObj || {}).attributes || {}).friendly_name
                    || (stateObj || {}).entity_id || '';
            },
        };
    }

    // The connection nobody is holding open, as one shared stub: rejecting
    // subscriptions is what lets a consumer fall back or say so — a promise
    // that never settles is a spinner forever.
    var NO_WS = {
        // The icon-resolution code checks `connection.haVersion` before it
        // even asks -- an absent version reads as "too old", and every
        // domain and attribute icon silently skips. Refreshed from the
        // bundle's config at boot.
        haVersion: '2026.1.0',
        subscribeMessage: function () {
            return Promise.reject(new Error('no websocket in the panel'));
        },
        subscribeEvents: function () {
            return Promise.resolve(function () { });
        },
        sendMessagePromise: function (msg) {
            return wsBridge(msg)
                || Promise.reject(new Error('no websocket in the panel'));
        },
        addEventListener: function () { },
        removeEventListener: function () { },
    };

    function builtinContextValue(key) {
        switch (key) {
            case 'hassFormatters': return builtinFormatters();
            case 'hassConfig': return { config: haConfig() };
            // The registries, in the wrapped shape the pickers' row builders
            // read (`registries.entities[id]`). Leaving this unanswered left
            // the consumer's property undefined and the first row build threw
            // — which is why the entity picker never drew.
            case 'hassRegistries':
                return { entities: builtin.reg.entities,
                         devices: builtin.reg.devices,
                         areas: builtin.reg.areas,
                         floors: {}, labels: {} };
            case 'connection': return NO_WS;
            case 'hassConnection':
                return { connection: NO_WS, connected: true };
            case 'hassApi':
                return { callApi: NO_WS.sendMessagePromise,
                         callWS: NO_WS.sendMessagePromise,
                         sendMessagePromise: NO_WS.sendMessagePromise };
            case 'config': return haConfig();
            case 'states': return statesPool;
            case 'entities': return builtin.reg.entities;
            // The picker's richer registry view. Fed the plain registry:
            // fields it wants beyond ours read as absent, which the picker
            // treats as "no extra detail" — the failure mode when the
            // context itself was unanswered was a throw.
            case 'extendedEntities': return builtin.reg.entities;
            case 'devices': return builtin.reg.devices;
            case 'areas': return builtin.reg.areas;
            case 'floors': return {};
            case 'labels': return {};
            case 'services': return {};
            case 'configEntries': return {};
            case 'manifests': return {};
            case 'related':
                // Answered NULL on purpose: the consumers guard on falsy
                // ("no related-items index here") and walk fields of any
                // truthy value — an empty stand-in object threw deeper.
                return null;
            case 'panels': return {};
            case 'themes':
                return { darkMode: document.documentElement
                    .getAttribute('data-panel-theme') !== 'light',
                    theme: 'default', themes: {} };
            case 'selectedTheme': return null;
            case 'user':
                return { name: 'Panel', is_admin: true, id: 'panel' };
            case 'locale': return LOCALE;
            case 'localize': return localize;
            case 'hassInternationalization':
                return builtinI18n();
            case 'narrowViewport': return false;
            case 'hassUi': {
                // Consumers read `_ui?.themes.darkMode` — the optional
                // chain guards the CONTEXT, not the field, so the value
                // must carry a themes object or the select boxes throw.
                var dark = document.documentElement
                    .getAttribute('data-panel-theme') !== 'light';
                return { darkMode: dark,
                         themes: { darkMode: dark, theme: 'default',
                                   themes: {} } };
            }
        }
        return undefined;
    }

    function installContextProvider() {
        if (builtin.ctxInstalled) return;
        builtin.ctxInstalled = true;
        document.addEventListener('context-request', function (e) {
            var value = builtinContextValue(e.context);
            if (value === undefined) return;
            e.stopPropagation();
            try { e.callback(value, function () { }); } catch (err) { /* consumer gone */ }
        });
    }

    // The custom-card hass, upgraded to what the real cards read. Same
    // states merge, same gated callService; the formatters, the registries
    // and the one API route (the sensor card's history line) are the parts
    // a built-in reaches for that a custom card never did.
    function buildBuiltinHass(spec) {
        var hass = makeHass(spec);
        var fmt = builtinFormatters();
        hass.entities = builtin.reg.entities;
        hass.devices = builtin.reg.devices;
        hass.areas = builtin.reg.areas;
        hass.floors = {};
        hass.formatEntityState = fmt.formatEntityState;
        hass.formatEntityStateToParts = fmt.formatEntityStateToParts;
        hass.formatEntityAttributeValue = fmt.formatEntityAttributeValue;
        hass.formatEntityAttributeName = fmt.formatEntityAttributeName;
        hass.formatEntityName = fmt.formatEntityName;
        hass.localize = localize;
        hass.locale = LOCALE;
        hass.config = haConfig();
        hass.loadBackendTranslation = loadBackendTranslation;
        hass.loadFragmentTranslation = function () {
            return Promise.resolve(localize);
        };
        hass.callWS = function (msg) {
            return wsBridge(msg)
                || Promise.reject(new Error('no websocket in the panel'));
        };
        hass.hassUrl = function (p) {
            return API.base + String(p || '').replace(/^\//, '');
        };
        // hass.callApi, for exactly ONE request shape: the sensor card's
        // history line. A general proxy would be an authenticated hole into
        // HA; this recognises `history/period/<start>?...filter_entity_id=X`
        // and routes it to the server's bounded, cached reader.
        hass.callApi = function (method, path) {
            var m = /^history\/period\/([^?]*)\?/.exec(String(path || ''));
            var eid = /filter_entity_id=([a-z_]+\.[a-z0-9_]+)/
                .exec(String(path || ''));
            if (String(method).toUpperCase() === 'GET' && m && eid) {
                var hours = 24;
                var start = new Date(decodeURIComponent(m[1]));
                if (!isNaN(start)) {
                    hours = Math.max(1, Math.min(168,
                        Math.ceil((Date.now() - start.getTime()) / 3600000)));
                }
                return fetch(API.base + 'api/ha/frontend/history?entity_id='
                    + eid[1] + '&hours=' + hours)
                    .then(function (r) {
                        if (!r.ok) throw new Error('history unavailable');
                        return r.json();
                    });
            }
            return Promise.reject(new Error('no api in the panel'));
        };
        // The same history, on the OTHER pipe. Today's cards subscribe to
        // `history/stream` and draw whatever arrives; the panel has no
        // websocket, so the one message HA would have opened with — the
        // backlog — is built from the same bounded endpoint and delivered
        // once. No live tail, matching the board's own poll-not-push rule.
        var base = hass.connection;
        hass.connection = {
            haVersion: (builtin.reg.config || {}).version || NO_WS.haVersion,
            sendMessagePromise: NO_WS.sendMessagePromise,
            subscribeMessage: function (callback, message) {
                var msg = message || {};
                if (msg.type !== 'history/stream'
                        || !(msg.entity_ids || []).length) {
                    return base.subscribeMessage
                        ? base.subscribeMessage(callback, message)
                        : Promise.reject(new Error('no websocket in the panel'));
                }
                var start = new Date(msg.start_time || 0);
                var hours = isNaN(start) ? 24 : Math.max(1, Math.min(168,
                    Math.ceil((Date.now() - start.getTime()) / 3600000)));
                var jobs = msg.entity_ids.map(function (eid) {
                    return fetch(API.base + 'api/ha/frontend/history?entity_id='
                        + eid + '&hours=' + hours)
                        .then(function (r) { return r.ok ? r.json() : []; })
                        .then(function (series) {
                            var pts = ((series || [])[0] || []).map(function (p) {
                                return { s: p.state,
                                         lu: new Date(p.last_changed).getTime() / 1000 };
                            }).filter(function (p) { return isFinite(p.lu); });
                            return [eid, pts];
                        })
                        .catch(function () { return [eid, []]; });
                });
                return Promise.all(jobs).then(function (pairs) {
                    var states = {};
                    pairs.forEach(function (p) { states[p[0]] = p[1]; });
                    try {
                        callback({ states: states,
                                   start_time: start.getTime() / 1000,
                                   end_time: Date.now() / 1000 });
                    } catch (e) { /* consumer re-rendering */ }
                    return function () { };
                });
            },
            subscribeEvents: base.subscribeEvents,
            addEventListener: base.addEventListener,
            removeEventListener: base.removeEventListener,
        };
        return hass;
    }

    function mountBuiltin(container, spec) {
        if (!container || !spec || !spec.type) return Promise.resolve(false);
        API.base = spec.apiBase || API.base;
        return bootBuiltin(spec.apiBase).then(function (ok) {
            if (!ok) return false;
            var type = String(spec.type);
            var tag = 'hui-' + type + '-card';
            var signature = JSON.stringify(['builtin', type, spec.config]);
            var live = mounted[spec.id];
            if (live && live.builtin && live.signature === signature && live.el) {
                return adopt(live, container, spec, buildBuiltinHass);
            }
            var need = Promise.resolve();
            if (!window.customElements.get(tag)) {
                var row = builtin.map[type];
                if (row) {
                    var o = window.__haWpr;
                    need = Promise.all((row.chunks || []).map(function (c) {
                        return o.e(c);
                    })).then(function () { return o(row.module); });
                }
            }
            return need.then(function () {
                if (!window.customElements.get(tag)) {
                    throw new Error(tag + ' is not in this Home Assistant release');
                }
                // HA's defaults by class, the panel's brand by inline var —
                // inline wins wherever both speak.
                container.classList.add('ha-builtin-theme');
                container.classList.toggle('ha-dark', spec.dark !== false);
                var theme = themeFrom(container);
                Object.keys(theme).forEach(function (k) {
                    container.style.setProperty(k, theme[k]);
                });
                var el = document.createElement(tag);
                el.setConfig(JSON.parse(JSON.stringify(spec.config || {})));
                el.hass = buildBuiltinHass(spec);
                el.style.display = 'block';
                container.textContent = '';
                container.appendChild(el);
                var held = { el: el, container: container,
                             signature: signature, spec: spec, builtin: true };
                mounted[spec.id] = held;
                watchWidth(held);
                return true;
            });
        }).catch(function (e) {
            // The fallback drawing is still in the cell; leaving it there IS
            // the error handling. The console line is for the person asking
            // why a card looks like the converter's version.
            console.warn('[ha_card_host] builtin ' + spec.type + ':',
                e && e.message);
            return false;
        });
    }

    // ── Which form layer a page gets.
    //
    // Editors — ours and every custom card's — are built out of `ha-form`
    // and the selector elements. Two implementations exist: HA's real ones
    // (in the borrowed runtime's chunks) and static/ha_form.js's shims. The
    // registry takes each tag once, so the page must PICK, and the pick is
    // the same rule as everywhere else in this file: the real thing where
    // the runtime works, the shim where it does not. The real form stack is
    // not loaded by booting alone (editor chunks are lazy), so it is pulled
    // through the first defined card's own getConfigElement — the same road
    // a real editor would take — and the element it returns is discarded.
    function ensureForm() {
        if (window.customElements.get('ha-form')) return Promise.resolve(true);
        var viaRuntime = Promise.resolve(false);
        if (builtin.ready && window.__haWpr) {
            var ctor = null;
            ['entities', 'thermostat', 'tile', 'sensor'].some(function (t) {
                var c = window.customElements.get('hui-' + t + '-card');
                if (c && typeof c.getConfigElement === 'function') {
                    ctor = c;
                    return true;
                }
                return false;
            });
            if (ctor) {
                viaRuntime = Promise.resolve()
                    .then(function () { return ctor.getConfigElement(); })
                    .then(function () {
                        return !!window.customElements.get('ha-form');
                    })
                    .catch(function () { return false; });
            }
        }
        return viaRuntime.then(function (real) {
            if (real) return true;
            if (window.ChauffeurHaForm) window.ChauffeurHaForm.ensure();
            return !!window.customElements.get('ha-form');
        });
    }

    // ── The REAL editor for a built-in card, off the borrowed runtime.
    //
    // Every hui-* card ships `static getConfigElement()`, and the element it
    // returns is HA's own editor — for a thermostat that includes the whole
    // features UI, for an area card the real display-type choices. This is
    // what "the options" should have been all along: our declared ha-form
    // schemas could only ever offer the fields somebody re-typed here, and a
    // field the form does not know about is a field that silently does not
    // exist. The schemas stay as the fallback for walls the runtime cannot
    // reach.
    function mountBuiltinEditor(container, spec, onChange) {
        if (!container || !spec || !spec.type) return Promise.resolve(false);
        API.base = spec.apiBase || API.base;
        return bootBuiltin(spec.apiBase).then(function (ok) {
            if (!ok) return false;
            var type = String(spec.type);
            var tag = 'hui-' + type + '-card';
            var need = Promise.resolve();
            if (!window.customElements.get(tag)) {
                var row = builtin.map[type];
                if (!row) return false;
                var o = window.__haWpr;
                need = Promise.all((row.chunks || []).map(function (c) {
                    return o.e(c);
                })).then(function () { return o(row.module); });
            }
            return need.then(function () {
                var ctor = window.customElements.get(tag);
                if (!ctor || typeof ctor.getConfigElement !== 'function') {
                    return false;
                }
                return Promise.resolve(ctor.getConfigElement()).then(function (el) {
                    if (!el) return false;
                    container.classList.add('ha-builtin-theme');
                    container.classList.toggle('ha-dark', spec.dark !== false);
                    var theme = themeFrom(container);
                    Object.keys(theme).forEach(function (k) {
                        container.style.setProperty(k, theme[k]);
                    });
                    el.hass = buildBuiltinHass(spec);
                    el.setConfig(JSON.parse(JSON.stringify(spec.config || {})));
                    el.addEventListener('config-changed', function (e) {
                        e.stopPropagation();
                        if (e && e.detail && e.detail.config) {
                            onChange(e.detail.config);
                        }
                    });
                    container.textContent = '';
                    container.appendChild(el);
                    return true;
                });
            });
        }).catch(function (e) {
            // False, not a broken form: the caller still holds the declared
            // schema and renders that instead.
            console.warn('[ha_card_host] builtin editor ' + spec.type + ':',
                e && e.message);
            return false;
        });
    }

    window.ChauffeurHaCards = {
        mount: mount,
        mountBuiltin: mountBuiltin,
        mountBuiltinEditor: mountBuiltinEditor,
        ensureForm: ensureForm,
        bootBuiltin: bootBuiltin,
        setStates: setStates,
        mountEditor: mountEditor,
        discover: discover,
        unmount: unmount,
        // Exposed for the runtime test, which checks the mapping without a
        // browser: these are contracts (a card reads `--primary-text-color`,
        // not `--panel-fg`) and a silent rename would repaint every hosted
        // card in the wrong colour with nothing failing anywhere.
        _theme: THEME,
        _themeFixed: THEME_FIXED,
        _makeHass: makeHass,
    };
})();

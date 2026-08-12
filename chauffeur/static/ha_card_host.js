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
    function makeHass(spec) {
        return {
            states: spec.states || {},
            // Enough of the shape that a card reading these does not throw.
            // Empty-string localize is HA's own behaviour for an unknown key,
            // and cards written against it use `|| fallback`.
            localize: function () { return ''; },
            formatEntityState: function (stateObj) { return (stateObj && stateObj.state) || ''; },
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
                try { held.el.hass = makeHass(held.spec); } catch (e) { /* gone */ }
            }, 120);
        });
        held.observer.observe(held.container);
    }

    function mount(container, spec) {
        if (!container || !spec) return Promise.resolve(false);
        API.base = spec.apiBase || '';
        defineShims();

        var signature = JSON.stringify([spec.tag, spec.resource, spec.config]);
        var live = mounted[spec.id];
        if (live && live.container === container && live.signature === signature) {
            live.el.hass = makeHass(spec);           // the cheap path: new states
            return Promise.resolve(true);
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

    function unmount(id) {
        var live = mounted[id];
        if (!live) return;
        try { live.el.remove(); } catch (e) { /* already gone with its tile */ }
        delete mounted[id];
    }

    window.ChauffeurHaCards = {
        mount: mount,
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

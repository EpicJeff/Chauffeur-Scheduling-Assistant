/* Home Assistant's form layer, rebuilt.
 *
 * This exists because of one line in every custom card worth configuring:
 *
 *     static async getConfigElement() { return document.createElement('…-editor'); }
 *
 * A card ships its own visual editor, in the same bundle we already fetch and
 * run. That editor is not a mystery — it is a Lit element that takes `hass` and
 * `setConfig(config)` and fires `config-changed`. The reason it could not be
 * hosted was never the editor itself; it was what the editor is BUILT OUT OF.
 *
 * Almost every one of them renders `<ha-form>` with a schema of Home Assistant
 * SELECTORS — `{name: 'entity', selector: {entity: {domain: 'light'}}}` — and
 * `ha-form` lives in HA's frontend bundle. So that is what this file is: the
 * form, the selectors, and the two pickers editors reach for directly.
 *
 * The bet is that a selector schema is a DECLARATION, the same way a built-in
 * card's config is. It says "an entity of this domain", not "draw this widget",
 * so a renderer that honours the declaration is a real implementation rather
 * than an impersonation — and it draws in the panel's own vocabulary, which is
 * the same payoff converting built-in cards had.
 *
 * The rule that keeps this honest: an UNKNOWN selector renders as an editable
 * JSON field, never as nothing. A form that silently drops the one option
 * somebody came to change is worse than a form that shows them the raw value.
 */
(function () {
    'use strict';

    if (window.ChauffeurHaForm) return;

    // Fed by the page (the board editor knows the household's entities from
    // /api/home_board/ha_options). Kept here rather than passed through every
    // element because `ha-entity-picker` is created by somebody else's code
    // three levels deep in a shadow root, and has no other way to be told.
    var ENTITIES = [];       // [{value: entity_id, label}]
    var AREAS = [];          // [{value: area_id, label}]

    function labelFor(entityId) {
        for (var i = 0; i < ENTITIES.length; i++) {
            if (ENTITIES[i].value === entityId) return ENTITIES[i].label;
        }
        return entityId;
    }

    function esc(s) {
        return String(s === null || s === undefined ? '' : s)
            .replace(/[&<>"']/g, function (c) {
                return { '&': '&amp;', '<': '&lt;', '>': '&gt;',
                         '"': '&quot;', "'": '&#39;' }[c];
            });
    }

    function define(name, ctor) {
        if (!window.customElements.get(name)) window.customElements.define(name, ctor);
    }

    // Every editor field looks the same because they are the same KIND of
    // thing. The styles are inlined per shadow root rather than shared, which
    // costs a few hundred bytes per element and buys not caring what page this
    // is mounted on.
    var FIELD_CSS =
        ':host{display:block;}' +
        'label{display:block;font-size:.7rem;font-weight:700;text-transform:uppercase;' +
        'letter-spacing:.05em;color:var(--secondary-text-color,#888);margin-bottom:.15rem;}' +
        'input,select,textarea{width:100%;box-sizing:border-box;' +
        'background:var(--card-background-color,rgba(255,255,255,.06));' +
        'border:1px solid var(--divider-color,rgba(255,255,255,.15));border-radius:6px;' +
        'padding:.35rem .5rem;font:inherit;font-size:.85rem;' +
        'color:var(--primary-text-color,inherit);}' +
        'input:focus,select:focus,textarea:focus{outline:2px solid var(--primary-color,#38bdf8);' +
        'outline-offset:-1px;}' +
        'textarea{min-height:4.5rem;font-family:ui-monospace,Menlo,Consolas,monospace;}' +
        '.row{display:flex;align-items:center;gap:.5rem;}' +
        '.helper{font-size:.7rem;color:var(--secondary-text-color,#888);margin-top:.15rem;}' +
        '.chips{display:flex;flex-wrap:wrap;gap:.3rem;}' +
        '.chip{font-size:.75rem;border-radius:999px;padding:.15rem .6rem;cursor:pointer;' +
        'border:1px solid var(--divider-color,rgba(255,255,255,.15));' +
        'background:var(--card-background-color,rgba(255,255,255,.06));' +
        'color:var(--primary-text-color,inherit);}' +
        '.chip[aria-pressed="true"]{background:var(--primary-color,#38bdf8);color:#04121c;}';

    // ── One selector, drawn.
    //
    // `ha-selector` is a real element in HA's frontend and editors do use it
    // directly, so it is defined rather than merely used internally.
    var SelectorEl = class extends HTMLElement {
        set selector(v) { this._sel = v; this._render(); }
        get selector() { return this._sel; }
        set value(v) { this._value = v; this._render(); }
        get value() { return this._value; }
        set label(v) { this._label = v; this._render(); }
        set helper(v) { this._helper = v; this._render(); }
        set hass(v) { this._hass = v; }
        set required(v) { this._required = v; }
        connectedCallback() { this._render(); }

        _emit(value) {
            this._value = value;
            this.dispatchEvent(new CustomEvent('value-changed', {
                detail: { value: value }, bubbles: true, composed: true,
            }));
        }

        _render() {
            if (!this.isConnected) return;
            if (!this.shadowRoot) {
                this.attachShadow({ mode: 'open' });
                this.shadowRoot.innerHTML = '<style>' + FIELD_CSS + '</style><div class="w"></div>';
            }
            var box = this.shadowRoot.querySelector('.w');
            var sel = this._sel || {};
            var kind = Object.keys(sel)[0] || 'text';
            var cfg = sel[kind] || {};
            var v = this._value;
            var self = this;
            box.innerHTML = '';

            if (this._label) {
                var lab = document.createElement('label');
                lab.textContent = this._label;
                box.appendChild(lab);
            }

            var el;
            if (kind === 'boolean') {
                el = document.createElement('input');
                el.type = 'checkbox';
                el.checked = !!v;
                el.style.width = 'auto';
                el.addEventListener('change', function () { self._emit(el.checked); });
            } else if (kind === 'number') {
                el = document.createElement('input');
                el.type = 'number';
                if (cfg.min !== undefined) el.min = cfg.min;
                if (cfg.max !== undefined) el.max = cfg.max;
                if (cfg.step !== undefined) el.step = cfg.step;
                el.value = (v === undefined || v === null) ? '' : v;
                el.addEventListener('change', function () {
                    // An emptied number field means "unset", not zero — the
                    // difference between a card falling back to its own default
                    // and a card being told the answer is 0.
                    self._emit(el.value === '' ? undefined : Number(el.value));
                });
            } else if (kind === 'select') {
                var options = (cfg.options || []).map(function (o) {
                    return (typeof o === 'string') ? { value: o, label: o } : o;
                });
                if (cfg.multiple) {
                    el = document.createElement('div');
                    el.className = 'chips';
                    var chosen = Array.isArray(v) ? v.slice() : [];
                    options.forEach(function (o) {
                        var b = document.createElement('button');
                        b.type = 'button';
                        b.className = 'chip';
                        b.textContent = o.label;
                        b.setAttribute('aria-pressed', chosen.indexOf(o.value) >= 0);
                        b.addEventListener('click', function () {
                            var at = chosen.indexOf(o.value);
                            if (at >= 0) chosen.splice(at, 1); else chosen.push(o.value);
                            self._emit(chosen.slice());
                        });
                        el.appendChild(b);
                    });
                } else {
                    el = document.createElement('select');
                    // The blank option is not decoration: "leave it to the
                    // card" has to stay reachable after something is picked.
                    var blank = document.createElement('option');
                    blank.value = '';
                    blank.textContent = '—';
                    el.appendChild(blank);
                    options.forEach(function (o) {
                        var opt = document.createElement('option');
                        opt.value = o.value;
                        opt.textContent = o.label;
                        if (o.value === v) opt.selected = true;
                        el.appendChild(opt);
                    });
                    el.addEventListener('change', function () {
                        self._emit(el.value === '' ? undefined : el.value);
                    });
                }
            } else if (kind === 'entity') {
                el = document.createElement('ha-entity-picker');
                el.domains = cfg.domain
                    ? (Array.isArray(cfg.domain) ? cfg.domain : [cfg.domain]) : null;
                el.value = v || '';
                el.addEventListener('value-changed', function (e) {
                    e.stopPropagation();
                    self._emit(e.detail.value || undefined);
                });
            } else if (kind === 'icon') {
                el = document.createElement('ha-icon-picker');
                el.value = v || '';
                el.addEventListener('value-changed', function (e) {
                    e.stopPropagation();
                    self._emit(e.detail.value || undefined);
                });
            } else if (kind === 'area') {
                el = document.createElement('select');
                var none = document.createElement('option');
                none.value = ''; none.textContent = '—';
                el.appendChild(none);
                AREAS.forEach(function (a) {
                    var o = document.createElement('option');
                    o.value = a.value; o.textContent = a.label;
                    if (a.value === v) o.selected = true;
                    el.appendChild(o);
                });
                el.addEventListener('change', function () {
                    self._emit(el.value === '' ? undefined : el.value);
                });
            } else if (kind === 'color_rgb') {
                el = document.createElement('input');
                el.type = 'color';
                el.value = Array.isArray(v)
                    ? '#' + v.map(function (n) {
                        return ('0' + Number(n).toString(16)).slice(-2);
                    }).join('') : (v || '#ffffff');
                el.addEventListener('change', function () {
                    var hex = el.value.replace('#', '');
                    self._emit([parseInt(hex.slice(0, 2), 16),
                                parseInt(hex.slice(2, 4), 16),
                                parseInt(hex.slice(4, 6), 16)]);
                });
            } else if (kind === 'text' && cfg.multiline) {
                el = document.createElement('textarea');
                el.value = v || '';
                el.addEventListener('change', function () {
                    self._emit(el.value || undefined);
                });
            } else if (kind === 'text' || kind === 'theme' || kind === 'attribute'
                       || kind === 'template') {
                el = document.createElement('input');
                el.type = 'text';
                el.value = v || '';
                el.addEventListener('change', function () {
                    self._emit(el.value || undefined);
                });
            } else {
                // UNKNOWN, and shown rather than dropped. `ui_action`,
                // `target`, `device`, a selector invented next release — a form
                // that silently omits the one option somebody came to change is
                // worse than one that shows them the raw value and lets them
                // edit it.
                el = document.createElement('textarea');
                el.value = (v === undefined) ? '' : JSON.stringify(v, null, 1);
                el.addEventListener('change', function () {
                    if (!el.value.trim()) return self._emit(undefined);
                    try { self._emit(JSON.parse(el.value)); }
                    catch (err) { self._emit(el.value); }
                });
                var note = document.createElement('div');
                note.className = 'helper';
                note.textContent = 'No editor for a ' + kind + ' option yet — this is its raw value.';
                box.appendChild(el);
                box.appendChild(note);
                el = null;
            }
            if (el) box.appendChild(el);

            if (this._helper) {
                var h = document.createElement('div');
                h.className = 'helper';
                h.textContent = this._helper;
                box.appendChild(h);
            }
        }
    };

    // ── The form: a schema in, a config out.
    function defineAll() {
        define('ha-selector', SelectorEl);

        define('ha-form', class extends HTMLElement {
            set schema(v) { this._schema = v; this._render(); }
            get schema() { return this._schema; }
            set data(v) { this._data = v || {}; this._render(); }
            get data() { return this._data; }
            set hass(v) { this._hass = v; }
            get hass() { return this._hass; }
            set computeLabel(fn) { this._label = fn; this._render(); }
            set computeHelper(fn) { this._helper = fn; this._render(); }
            set computeError(fn) { this._error = fn; }
            set disabled(v) { }
            connectedCallback() { this._render(); }

            _emit(name, value) {
                var next = Object.assign({}, this._data || {});
                if (value === undefined) delete next[name];
                else next[name] = value;
                this._data = next;
                // `value-changed` carrying the WHOLE object, which is what HA's
                // own ha-form does — a card editor listens once and rebuilds its
                // config from it rather than tracking fields.
                this.dispatchEvent(new CustomEvent('value-changed', {
                    detail: { value: next }, bubbles: true, composed: true,
                }));
            }

            _label_for(item) {
                if (this._label) {
                    try {
                        var t = this._label(item);
                        if (t) return t;
                    } catch (e) { /* an editor's own labeller, not ours */ }
                }
                return String(item.name || '').replace(/_/g, ' ')
                    .replace(/^./, function (c) { return c.toUpperCase(); });
            }

            _helper_for(item) {
                if (!this._helper) return '';
                try { return this._helper(item) || ''; } catch (e) { return ''; }
            }

            _render() {
                if (!this.isConnected) return;
                if (!this.shadowRoot) {
                    this.attachShadow({ mode: 'open' });
                    this.shadowRoot.innerHTML =
                        '<style>' + FIELD_CSS +
                        ':host{display:block;}.f{display:flex;flex-direction:column;gap:.6rem;}' +
                        '.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));gap:.6rem;}' +
                        'details{border:1px solid var(--divider-color,rgba(255,255,255,.15));' +
                        'border-radius:8px;padding:.4rem .55rem;}' +
                        'summary{cursor:pointer;font-size:.78rem;font-weight:700;}' +
                        'details .f{margin-top:.5rem;}' +
                        '</style><div class="f"></div>';
                }
                var box = this.shadowRoot.querySelector('.f');
                box.innerHTML = '';
                this._draw(box, this._schema || [], this._data || {});
            }

            _draw(into, schema, data) {
                var self = this;
                (schema || []).forEach(function (item) {
                    if (!item || !item.name && !item.type) return;
                    // `grid` and `expandable` are LAYOUT, not values: they hold
                    // a nested schema over the same data object. Missing that
                    // is how a form silently loses half its fields.
                    if (item.type === 'grid') {
                        var g = document.createElement('div');
                        g.className = 'grid';
                        self._draw(g, item.schema, data);
                        into.appendChild(g);
                        return;
                    }
                    if (item.type === 'expandable') {
                        var d = document.createElement('details');
                        var s = document.createElement('summary');
                        s.textContent = item.title || self._label_for(item);
                        d.appendChild(s);
                        var inner = document.createElement('div');
                        inner.className = 'f';
                        self._draw(inner, item.schema, data);
                        d.appendChild(inner);
                        into.appendChild(d);
                        return;
                    }
                    var field = document.createElement('ha-selector');
                    field.hass = self._hass;
                    // An item may carry `selector`, or the older shorthand of a
                    // bare `type` — both appear in cards in the wild.
                    field.selector = item.selector
                        || (item.type ? _shorthand(item) : { text: {} });
                    field.label = self._label_for(item);
                    field.helper = self._helper_for(item);
                    field.value = data[item.name];
                    field.addEventListener('value-changed', function (e) {
                        e.stopPropagation();
                        self._emit(item.name, e.detail.value);
                    });
                    into.appendChild(field);
                });
            }
        });

        // ── The two pickers editors reach for directly.
        define('ha-entity-picker', class extends HTMLElement {
            set value(v) { this._value = v; this._render(); }
            get value() { return this._value; }
            set domains(v) { this._domains = v; this._render(); }
            set includeDomains(v) { this._domains = v; this._render(); }
            set hass(v) { this._hass = v; }
            set label(v) { this._label = v; this._render(); }
            connectedCallback() { this._render(); }
            _render() {
                if (!this.isConnected) return;
                if (!this.shadowRoot) {
                    this.attachShadow({ mode: 'open' });
                    this.shadowRoot.innerHTML =
                        '<style>' + FIELD_CSS + '</style><input type="text"><datalist></datalist>';
                    var input = this.shadowRoot.querySelector('input');
                    var self = this;
                    input.addEventListener('change', function () {
                        self._value = input.value.trim();
                        self.dispatchEvent(new CustomEvent('value-changed', {
                            detail: { value: self._value },
                            bubbles: true, composed: true,
                        }));
                    });
                }
                var input = this.shadowRoot.querySelector('input');
                var list = this.shadowRoot.querySelector('datalist');
                if (!list.id) {
                    list.id = 'ep' + Math.round(performance.now() * 1000) % 1e9;
                    input.setAttribute('list', list.id);
                }
                input.value = this._value || '';
                input.placeholder = (this._domains && this._domains.length)
                    ? this._domains[0] + '.…' : 'sensor.…';
                // A DATALIST rather than a dropdown, for the reason the tile
                // options already settled: an ordinary Home Assistant has
                // thousands of entities and a list of them all is not a picker.
                var want = this._domains;
                list.innerHTML = '';
                ENTITIES.filter(function (e) {
                    if (!want || !want.length) return true;
                    return want.indexOf(String(e.value).split('.')[0]) >= 0;
                }).slice(0, 400).forEach(function (e) {
                    var o = document.createElement('option');
                    o.value = e.value;
                    o.textContent = e.label;
                    list.appendChild(o);
                });
            }
        });

        define('ha-icon-picker', class extends HTMLElement {
            set value(v) { this._value = v; this._render(); }
            get value() { return this._value; }
            set hass(v) { }
            set label(v) { }
            connectedCallback() { this._render(); }
            _render() {
                if (!this.isConnected) return;
                if (!this.shadowRoot) {
                    this.attachShadow({ mode: 'open' });
                    this.shadowRoot.innerHTML =
                        '<style>' + FIELD_CSS +
                        '.row ha-icon{color:var(--primary-text-color,inherit);}</style>' +
                        '<div class="row"><input type="text" placeholder="mdi:lightbulb">' +
                        '<ha-icon></ha-icon></div>';
                    var input = this.shadowRoot.querySelector('input');
                    var self = this;
                    input.addEventListener('change', function () {
                        self._value = input.value.trim();
                        self._render();
                        self.dispatchEvent(new CustomEvent('value-changed', {
                            detail: { value: self._value },
                            bubbles: true, composed: true,
                        }));
                    });
                }
                this.shadowRoot.querySelector('input').value = this._value || '';
                // The preview is the whole point of an icon picker: `mdi:` names
                // are unguessable, and seeing the glyph is how you know you
                // typed the right one.
                this.shadowRoot.querySelector('ha-icon')
                    .setAttribute('icon', this._value || '');
            }
        });
    }

    // The older shorthand some cards still use: `{name, type: 'boolean'}`
    // instead of `{name, selector: {boolean: {}}}`.
    function _shorthand(item) {
        var t = item.type;
        if (t === 'boolean') return { boolean: {} };
        if (t === 'integer' || t === 'float') {
            return { number: { min: item.valueMin, max: item.valueMax } };
        }
        if (t === 'select') {
            return { select: { options: item.options || [] } };
        }
        if (t === 'multi_select') {
            return { select: { multiple: true,
                options: Object.keys(item.options || {}).map(function (k) {
                    return { value: k, label: item.options[k] };
                }) } };
        }
        return { text: {} };
    }

    // NOT defined at parse time any more, and this is load-bearing: every
    // one of these tags is ALSO defined by Home Assistant's own frontend,
    // which the board now borrows for the built-in cards (ha_card_host
    // bootBuiltin). A registry takes each name once — when the shims went
    // first, HA's chunks threw mid-evaluation and every module sharing those
    // chunks died with them: cards mounted, but their feature rows, their
    // hui-image and the real pickers were casualties. Reported from the wall
    // as "features and area images don't show". The shims now define only
    // when asked — which the host does exactly when the borrowed runtime is
    // not there to do it better.

    window.ChauffeurHaForm = {
        // The shim elements, on demand. Idempotent (define skips existing),
        // safe after the runtime too — its patched prelude ignores duplicate
        // defines — but the design is to not need that net: real elements
        // where the runtime works, these where it does not.
        ensure: defineAll,
        // Fed by the page once the household's entities are known. Called
        // again whenever they change; every picker reads the live array.
        setEntities: function (rows) { ENTITIES = rows || []; },
        setAreas: function (rows) { AREAS = rows || []; },
        entities: function () { return ENTITIES; },
        labelFor: labelFor,
        _esc: esc,
    };
})();

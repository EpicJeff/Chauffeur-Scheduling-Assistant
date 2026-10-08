/* The settings drawer's behaviour (settings-drawer arc).

   Loaded by nav.html on every page, before Alpine starts (Alpine is
   deferred), so `chfSettingsDrawer` exists when Alpine walks the tree and
   the save helpers exist for page code everywhere — on a wall they simply
   report that no drawer showed the mark, and the page falls back to its
   own alert. */
(function () {
    'use strict';

    function keysOf(el) {
        return ((el && el.getAttribute('data-settings-for')) || '').split(/\s+/).filter(Boolean);
    }
    function drawerFor(tab) {
        if (!tab) return null;
        return document.querySelector('[data-settings-for~="' + CSS.escape(tab) + '"]');
    }
    function activeTab() {
        return typeof window.chfPageTab === 'function' ? window.chfPageTab() : null;
    }
    function anyOpen() {
        return !!document.querySelector('[data-settings-for][data-open]');
    }
    // A global prompt (control_center.html, z-[400]) open above the drawer
    // owns Escape; the drawer under it stays put.
    function promptOpen() {
        return !!document.querySelector(
            '#cc-confirm-modal:not(.hidden), #cc-alert-modal:not(.hidden),' +
            ' #cc-input-modal:not(.hidden), #cc-choice-modal:not(.hidden)');
    }

    window.chfOpenSettings = function (tab, anchor) {
        window.dispatchEvent(new CustomEvent('chf-settings-open',
            { detail: { tab: tab || activeTab(), anchor: anchor || null } }));
    };
    window.chfCloseSettings = function () {
        window.dispatchEvent(new CustomEvent('chf-settings-close'));
    };
    window.chfSettingsSaving = function () {
        window.dispatchEvent(new CustomEvent('chf-settings-status', { detail: { state: 'saving' } }));
        return anyOpen();
    };
    window.chfSettingsSaved = function (ok, message) {
        window.dispatchEvent(new CustomEvent('chf-settings-status',
            { detail: { state: ok ? 'saved' : 'error', message: message || '' } }));
        return anyOpen();
    };

    window.chfSettingsDrawer = function () {
        return {
            drawerOpen: false,
            drawerTab: null,
            drawerState: '',
            drawerMsg: '',
            _drawerTimer: null,
            _drawerKeepOff: null,

            drawerOpenFor(detail) {
                const d = detail || {};
                if (!keysOf(this.$root).includes(d.tab)) {
                    // One drawer at a time.
                    if (this.drawerOpen) this.drawerClose();
                    return;
                }
                this.drawerOpen = true;
                this.drawerTab = d.tab;
                this.drawerState = '';
                this.drawerMsg = '';
                this.$nextTick(() => {
                    const panel = this.$refs.drawerPanel;
                    const target = d.anchor ? document.getElementById(d.anchor) : null;
                    this.drawerKeepStop();
                    if (target && this.$root.contains(target)) {
                        target.scrollIntoView({ block: 'start' });
                        this.drawerKeep(panel, target);
                    } else if (panel) panel.scrollTop = 0;
                    if (panel) panel.focus({ preventScroll: true });
                    window.dispatchEvent(new CustomEvent('chf-settings-opened', { detail: { tab: d.tab, anchor: d.anchor || null } }));
                });
            },
            // Sections fill in as a page's loads land, pushing the anchor a
            // link named down the panel. For ~1.5s keep the reader on it,
            // until they act for themselves (or the drawer closes).
            drawerKeep(panel, target) {
                if (!panel) return;
                const stop = () => this.drawerKeepStop();
                const events = ['wheel', 'touchstart', 'pointerdown', 'keydown'];
                events.forEach(n => panel.addEventListener(n, stop, { passive: true }));
                const started = Date.now();
                let ro = null;
                const settle = () => {
                    if (Date.now() - started > 1500) { stop(); return; }
                    if (Math.abs(target.getBoundingClientRect().top - panel.getBoundingClientRect().top) > 60)
                        target.scrollIntoView({ block: 'start' });
                };
                const timer = setInterval(settle, 120);
                if (window.ResizeObserver && panel.firstElementChild) {
                    ro = new ResizeObserver(settle);
                    ro.observe(panel.firstElementChild.nextElementSibling || panel.firstElementChild);
                }
                this._drawerKeepOff = () => {
                    clearInterval(timer);
                    if (ro) ro.disconnect();
                    events.forEach(n => panel.removeEventListener(n, stop));
                    this._drawerKeepOff = null;
                };
            },
            drawerKeepStop() {
                if (this._drawerKeepOff) this._drawerKeepOff();
            },
            drawerClose() {
                if (!this.drawerOpen) return;
                this.drawerOpen = false;
                this.drawerKeepStop();
                const tab = this.drawerTab;
                // A hash that pointed in here would reopen it on reload.
                try {
                    const id = decodeURIComponent((location.hash || '').slice(1)).split('?')[0];
                    const el = id ? document.getElementById(id) : null;
                    if (el && this.$root.contains(el))
                        history.replaceState(history.state, '', location.pathname + location.search);
                } catch (e) { }
                window.dispatchEvent(new CustomEvent('chf-settings-closed', { detail: { tab } }));
                const gear = document.getElementById('page-settings-gear');
                if (gear && !gear.classList.contains('hidden')) gear.focus({ preventScroll: true });
            },
            drawerEscape() {
                if (this.drawerOpen && !promptOpen()) this.drawerClose();
            },
            drawerJump(id) {
                const el = document.getElementById(id);
                if (el) el.scrollIntoView({ block: 'start', behavior: 'smooth' });
            },
            drawerStatus(detail) {
                if (!this.drawerOpen) return;
                const d = detail || {};
                clearTimeout(this._drawerTimer);
                this.drawerState = d.state || '';
                this.drawerMsg = d.message || '';
                if (d.state === 'saved')
                    this._drawerTimer = setTimeout(() => { this.drawerState = ''; }, 2500);
                if (d.state === 'saving')
                    this._drawerTimer = setTimeout(() => {
                        if (this.drawerState === 'saving') this.drawerState = '';
                    }, 15000);
            },
            drawerStatusText() {
                if (this.drawerState === 'saving') return 'Saving…';
                if (this.drawerState === 'saved') return 'Saved ✓';
                if (this.drawerState === 'error') return this.drawerMsg || 'Could not save that just now.';
                return '';
            },
        };
    };

    // The page bar's in-page tab links (nav.html). A hidden tab block hides
    // everything in it, a drawer included, so the tab opens first.
    function switchTab(tab) {
        const link = document.querySelector('#page-tabs a[data-inpage-tab="' + tab + '"]');
        if (link && !link.classList.contains('bg-blue-600')) link.click();
    }
    function syncGear() {
        const gear = document.getElementById('page-settings-gear');
        if (gear) gear.classList.toggle('hidden', !drawerFor(activeTab()));
    }
    // One path for every deep link (it replaces the per-page openers that
    // rhythms.html and school.html carried): an anchor in a tab opens the
    // tab; an anchor in a drawer opens the drawer at it; `?settings=open`
    // opens the active tab's drawer at the top (the forwards from retired
    // settings tabs land here).
    function openFromAddress() {
        let handled = false;
        let id = '';
        try { id = decodeURIComponent((location.hash || '').slice(1)).split('?')[0]; } catch (e) { }
        const el = id ? document.getElementById(id) : null;
        if (el) {
            const block = el.closest('[data-page-tab]');
            if (block) switchTab(block.getAttribute('data-page-tab'));
            const drawer = el.closest('[data-settings-for]');
            if (drawer) {
                const keys = keysOf(drawer);
                const act = activeTab();
                window.chfOpenSettings(keys.includes(act) ? act : keys[0], id);
                handled = true;
            } else if (block) {
                setTimeout(() => el.scrollIntoView({ block: 'start' }), 50);
            }
        }
        const q = new URLSearchParams(location.search);
        if (q.get('settings') === 'open') {
            q.delete('settings');
            const qs = q.toString();
            try { history.replaceState(history.state, '', location.pathname + (qs ? '?' + qs : '') + location.hash); } catch (e) { }
            if (!handled && drawerFor(activeTab())) window.chfOpenSettings(activeTab());
        }
    }

    let booted = false;
    function boot() {
        if (booted) return;
        booted = true;
        syncGear();
        openFromAddress();
    }
    document.addEventListener('alpine:initialized', boot);
    window.addEventListener('load', boot);
    window.addEventListener('hashchange', openFromAddress);
    window.addEventListener('chf-page-tab', syncGear);
    document.addEventListener('click', ev => {
        if (ev.target.closest && ev.target.closest('#page-settings-gear')) {
            ev.preventDefault();
            window.chfOpenSettings(activeTab());
        }
    });
})();

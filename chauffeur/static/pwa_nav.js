/* Pushed-screen chrome; the tab views still own their data and actions. */
(function () {
    if (window.PwaNav) return;

    const screens = [];
    const pendingPushes = [];
    let pendingWalk = 0;
    let finishWalk = null;
    const depth = () => screens.length;
    const current = () => screens.length ? screens[screens.length - 1].screen : null;

    if (window.history.state && typeof window.history.state.pwaDepth === 'number'
        && window.history.state.pwaDepth > 0 && depth() === 0) {
        window.history.replaceState({...window.history.state, pwaDepth:0, pwaScreen:null}, '');
    }

    function sync() {
        const host = document.getElementById('pwa-stack');
        if (host) host.hidden = depth() === 0;
        if (depth()) document.documentElement.dataset.pwaStack = String(depth());
        else delete document.documentElement.dataset.pwaStack;
        const covered = document.querySelector(typeof PWA_NAV_COVERED_ROOT === 'string' ? PWA_NAV_COVERED_ROOT : '#pwa-covered');
        if (covered) {
            covered.toggleAttribute('inert', depth() > 0);
            if (depth()) covered.setAttribute('aria-hidden', 'true');
            else covered.removeAttribute('aria-hidden');
        }
    }

    function restoreFocus(opener) {
        const visible = element => {
            if (!element?.isConnected || element.closest('[hidden], [inert]')) return false;
            for (let node = element; node; node = node.parentElement) {
                const style = window.getComputedStyle(node);
                if (style.display === 'none' || style.visibility === 'hidden') return false;
            }
            return true;
        };
        const view = typeof currentView !== 'undefined' ? currentView : '';
        const tab = document.getElementById('tab-' + view) || document.querySelector('#pwa-tab-bar [aria-current="page"]');
        if (visible(opener)) opener.focus({preventScroll:true});
        else if (visible(tab)) tab.focus({preventScroll:true});
    }

    function push(screen) {
        const host = document.getElementById('pwa-stack');
        if (!host) return;
        const opener = document.activeElement;

        if (depth() === 0) {
            const s = window.history.state;
            // Null already denotes the root; deep-link handlers may leave {}.
            if (s !== null && typeof (s && s.pwaDepth) !== 'number') {
                window.history.replaceState(Object.assign({}, s || {}, { pwaDepth: 0 }), '');
            }
        }

        const parentTitle = current() ? current().title
            : document.querySelector('#pwa-tab-bar [aria-current="page"] > span')?.textContent?.trim() || 'Back';
        const section = document.createElement('section');
        section.className = 'pwa-screen';
        section.dataset.screen = screen.id;
        const header = document.createElement('header');
        const back = document.createElement('button');
        back.type = 'button';
        back.className = 'pwa-back';
        back.setAttribute('aria-label', 'Back to ' + parentTitle);
        back.textContent = '‹ ' + parentTitle;
        back.addEventListener('click', () => pop());
        const title = document.createElement('h1');
        title.textContent = screen.title;
        title.setAttribute('tabindex', '-1');
        header.append(back, title);
        const body = document.createElement('div');
        body.className = 'pwa-screen-body';
        section.append(header, body);
        screen.render?.(body);
        host.append(section);
        const entry = { screen, section, opener, state: { pwaScreen: screen.id, pwaDepth: depth() + 1 } };
        screens.push(entry);
        sync();
        title.focus({preventScroll:true});
        if (pendingWalk) pendingPushes.push(entry);
        else window.history.pushState(entry.state, '');
    }

    function removeScreen({ restore = true } = {}) {
        const entry = screens.pop();
        if (!entry) return;
        if (pendingPushes[pendingPushes.length - 1] === entry) pendingPushes.pop();
        entry.section.remove();
        sync();
        try {
            entry.screen.onPop?.();
        } catch (error) {
            console.error('PwaNav onPop failed', error);
        }
        if (restore) restoreFocus(entry.opener);
    }

    function startWalk(count) {
        // Serialize additional pops/clears against the traversal already in flight.
        finishWalk = () => {
            pendingWalk -= count;
            if (pendingWalk) {
                startWalk(pendingWalk);
                return;
            }
            finishWalk = null;
            for (const entry of pendingPushes.splice(0)) {
                window.history.pushState(entry.state, '');
            }
        };
        window.history.go(-count);
    }

    function walkBack(count) {
        if (!count) return;
        pendingWalk += count;
        if (!finishWalk) startWalk(count);
    }

    function pop() {
        if (!depth()) return;
        // A screen queued during a walk has no history entry to undo yet.
        const queued = pendingPushes[pendingPushes.length - 1] === screens[screens.length - 1];
        walkBack(queued ? 0 : 1);
        removeScreen();
    }

    function clear({ extra = 0, restoreFocus = true } = {}) {
        walkBack(depth() - pendingPushes.length + extra);
        while (depth()) removeScreen({restore:restoreFocus});
    }

    window.addEventListener('popstate', event => {
        if (pendingWalk) {
            // The DOM was updated synchronously by pop()/clear().
            finishWalk();
            return;
        }
        if (!depth()) return;
        // Other surfaces (for example Moments) own their own history state.
        if (event.state !== null && typeof event.state?.pwaDepth !== 'number') return;
        const target = event.state?.pwaDepth || 0;
        while (depth() && depth() > target) removeScreen();
    });

    window.PwaNav = { push, pop, clear, depth, current };
})();

/* Pushed-screen chrome; the tab views still own their data and actions. */
(function () {
    if (window.PwaNav) return;

    const screens = [];
    const pendingPushes = [];
    let pendingWalk = 0;
    let finishWalk = null;
    const depth = () => screens.length;
    const current = () => screens.length ? screens[screens.length - 1].screen : null;

    function sync() {
        const host = document.getElementById('pwa-stack');
        if (host) host.hidden = depth() === 0;
        if (depth()) document.documentElement.dataset.pwaStack = String(depth());
        else delete document.documentElement.dataset.pwaStack;
    }

    function push(screen) {
        const host = document.getElementById('pwa-stack');
        if (!host) return;

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
        header.append(back, title);
        const body = document.createElement('div');
        body.className = 'pwa-screen-body';
        section.append(header, body);
        screen.render?.(body);
        host.append(section);
        const entry = { screen, section, state: { pwaScreen: screen.id, pwaDepth: depth() + 1 } };
        screens.push(entry);
        sync();
        if (pendingWalk) pendingPushes.push(entry);
        else window.history.pushState(entry.state, '');
    }

    function removeScreen() {
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

    function clear() {
        walkBack(depth() - pendingPushes.length);
        while (depth()) removeScreen();
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

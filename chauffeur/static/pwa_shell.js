/* Presentation adapter only. Existing views still own data and actions. */
function pwaIsAdult() {
    return !!selectedMemberId && currentMemberRole() !== 'child';
}

function pwaSyncShell() {
    const adult = pwaIsAdult();
    document.documentElement.dataset.audience = adult ? 'adult' : 'child';
    document.documentElement.dataset.pwaView = currentView;
    const labels = {drives: adult ? 'Today' : 'My Day', myday: adult ? 'Today' : 'My Day',
        family: adult ? 'Plan' : 'Family', chores: adult ? 'Household' : 'House'};
    Object.entries(labels).forEach(([id, label]) => {
        document.querySelector(`#tab-${id} > span`).textContent = label;
    });
    // Keep keyboard/reading order aligned with the visual tab order.
    const household = document.getElementById('tab-chores');
    const afterHousehold = document.getElementById(adult ? 'tab-messages' : 'tab-map');
    if (household.nextElementSibling !== afterHousehold)
        afterHousehold.before(household);
    const more = document.getElementById('tab-more');
    more.style.display = adult ? 'flex' : 'none';
    document.getElementById('pwa-identity').setAttribute('aria-label', adult ? 'Your profile and preferences' : 'Edit your avatar');
    document.getElementById('pwa-more-container').hidden = !adult || currentView !== 'more';
    document.querySelectorAll('#pwa-tab-bar > button').forEach(button => {
        const name = button.id.slice(4);
        const active = name === currentView || (adult && name === 'more' && ['map', 'music'].includes(currentView));
        if (active) button.setAttribute('aria-current', 'page');
        else button.removeAttribute('aria-current');
    });
    if (adult && currentView === 'more') pwaRenderDirectory();
}

function pwaAllowed(view) {
    // Inline display is set by applyRoleTabs, including the async list grant.
    const tab = document.getElementById(`tab-${view}`);
    return !!tab && tab.style.display !== 'none';
}

function pwaFeatures() {
    const items = [];
    const route = (id, title, description, view) => {
        if (pwaAllowed(view)) items.push({id, title, description, run: () => setView(view)});
    };
    route('map', 'Family map', 'Find shared locations and driving progress', 'map');
    route('music', 'Music', 'Favorites and household listening', 'music');
    route('household', 'Household', 'Tasks, shared lists and household threads', 'chores');
    route('moments', 'Messages & moments', 'Conversations and shared family updates', 'messages');
    if (pwaAllowed('drives') || pwaAllowed('myday')) {
        items.push({id: 'programs', title: 'My programs', description: 'Practice and learning in your day', run: () => {
            setView(pwaAllowed('drives') ? 'drives' : 'myday');
            if (currentView === 'drives') {
                activeDateIndex = Math.max(0, currentDates.indexOf(todayStr()));
                const days = document.getElementById('days-container');
                days.scrollLeft = activeDateIndex * days.clientWidth;
                updateHeaderDate();
                paneJump('today-container');
            }
        }});
    }
    items.push({id: 'assistant', title: 'Ask Argyle', description: 'Help with your family plans', run: () => toggleKioskChat()},
        {id: 'critter', title: 'My critter', description: 'Visit and customize your companion', run: () => openPetEditor(selectedMemberId)},
        {id: 'profile', title: 'Profile & appearance', description: 'Avatar, theme, notifications and sign out', run: pwaOpenProfile});
    return items;
}

function pwaFeatureButton(item) {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'pwa-feature'; button.dataset.feature = item.id;
    const title = document.createElement('span'); title.textContent = item.title;
    const detail = document.createElement('small'); detail.textContent = item.description;
    button.append(title, detail); button.onclick = item.run;
    return button;
}

function pwaRenderDirectory() {
    const query = document.getElementById('pwa-feature-search').value.trim().toLocaleLowerCase();
    const items = pwaFeatures().filter(item => `${item.title} ${item.description}`.toLocaleLowerCase().includes(query));
    document.getElementById('pwa-feature-list').replaceChildren(...items.map(pwaFeatureButton));
    document.getElementById('pwa-search-empty').hidden = items.length > 0;
}

function pwaSearch() {
    setView('more');
    document.getElementById('pwa-feature-search').focus();
}

function pwaOpenProfile() {
    const dialog = document.getElementById('pwa-profile');
    const action = (id, title, description, run, keepOpen = false) => ({id, title, description, run: () => {
        if (!keepOpen) dialog.close();
        run();
    }});
    const items = [
        action('avatar', 'Your avatar', 'Edit your photo or character', () => openAvatarEditor(selectedMemberId)),
        action('critter', 'My critter', 'Visit your companion', () => openPetEditor(selectedMemberId)),
        action('theme', 'Appearance', `Theme: ${themePref()}. Change between device, light and dark.`, () => {
            cycleTheme();
            const button = dialog.querySelector('[data-feature="theme"] small');
            button.textContent = `Theme: ${themePref()}. Change between device, light and dark.`;
        }, true),
        action('refresh', 'Refresh', 'Get the latest schedule', () => fetchSchedule(true)),
    ];
    if (!document.getElementById('btn-push').classList.contains('hidden'))
        items.push(action('push', 'Enable notifications', 'Receive family updates on this device', enableNotifications));
    items.push(action('switch', 'Switch person / sign out', 'Return to the family member picker', clearDriver));
    document.getElementById('pwa-profile-actions').replaceChildren(...items.map(pwaFeatureButton));
    if (!dialog.open) dialog.showModal();
}

function pwaRefreshOverview() {
    document.querySelectorAll('.pwa-overview').forEach(node => node.remove());
    if (!pwaIsAdult() || currentView !== 'drives') return;
    const pane = document.getElementById(`pane-${currentDates.indexOf(todayStr())}`);
    if (!pane) return;
    // Read the rows already calculated by the scheduler: departure buffers,
    // delays, completion and in-progress state have one owner.
    const row = pane.querySelector('.pwa-leg-row[data-next="active"]')
        || pane.querySelector('.pwa-leg-row[data-next="upcoming"]');
    if (!row) return;
    const card = row.children[1];
    const host = document.createElement('section'); host.className = 'pwa-overview';
    const next = document.createElement('div'); next.className = 'pwa-next';
    const label = document.createElement('p'); label.textContent = row.dataset.next === 'active' ? 'CURRENT DRIVE' : 'NEXT DRIVE';
    const time = document.createElement('h2'); time.textContent = card.children[0].textContent;
    const title = document.createElement('div'); title.textContent = card.children[1].textContent;
    const button = document.createElement('button'); button.textContent = 'View drive';
    button.onclick = () => row.click();
    next.append(label, time, title, button); host.append(next); pane.prepend(host);
}

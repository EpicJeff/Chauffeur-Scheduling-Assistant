/* Presentation adapter only. Existing views still own data and actions. */
let pwaChoresOwner = null, pwaRequestsOwner = null;
let pwaHouseSection = 'tasks', pwaDatesExpanded = false;
function pwaIsAdult() {
    return !!selectedMemberId && currentMemberRole() !== 'child';
}

function pwaSyncShell() {
    const adult = pwaIsAdult();
    document.documentElement.dataset.audience = adult ? 'adult' : 'child';
    document.documentElement.dataset.pwaView = currentView;
    if (pwaSyncShell.member !== selectedMemberId) {
        pwaSyncShell.member = selectedMemberId;
        pwaHouseSection = 'tasks';
        pwaDatesExpanded = false;
        document.querySelector('.pwa-conversation-search input').value = '';
    }
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
    pwaPageHeading();
    if (adult) pwaRenderHouseTabs();
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
                const program = document.getElementById(`pane-${activeDateIndex}`)?.querySelector('[data-myday-program]');
                if (program) program.scrollIntoView({block:'start', behavior:'smooth'});
                else paneJump('today-container');
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
    const copy = document.createElement('div'); copy.append(title, detail);
    const glyph = document.createElement('span'); glyph.className = 'pwa-feature-icon';
    glyph.innerHTML = pwaIcon(item.id);
    button.append(glyph, copy); button.onclick = item.run;
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
    document.querySelectorAll('.pwa-promoted').forEach(node => node.classList.remove('pwa-promoted'));
    if (!pwaIsAdult()) return;
    if (currentView === 'family') {
        document.querySelectorAll('#days-container > div').forEach(pane => {
            const events = pane.querySelector('#pane-events');
            if (!events) return;
            for (const id of ['proposals-container','mind-container']) {
                const section = pane.querySelector('#'+id);
                if (section) pane.append(section);
            }
        });
        return;
    }
    if (currentView !== 'drives') return;
    document.querySelectorAll('#days-container > div').forEach(pane => {
        const schedule = pane.querySelector('#pane-drives');
        if (schedule && !pane.querySelector('.pwa-section-title')) {
            const title = document.createElement('div'); title.className = 'pwa-section-title';
            const text = document.createElement('h3'); text.textContent = 'Your schedule'; title.append(text);
            if (pwaAllowed('family')) {
                const link = document.createElement('button'); link.textContent = 'Family plan →'; link.onclick = () => setView('family'); title.append(link);
            }
            schedule.before(title);
        }
        // Family status, replies and untimed updates remain reachable after
        // the chronological schedule instead of preceding the next action.
        const updates = pane.querySelector('#today-container');
        if (updates) pane.append(updates);
    });
    const pane = document.getElementById(`pane-${currentDates.indexOf(todayStr())}`);
    if (!pane) return;
    // Read the rows already calculated by the scheduler: departure buffers,
    // delays, completion and in-progress state have one owner.
    const row = pane.querySelector('.pwa-leg-row[data-next="active"]')
        || pane.querySelector('.pwa-leg-row[data-next="upcoming"]');
    const host = document.createElement('section'); host.className = 'pwa-overview';
    if (row) {
    const next = document.createElement('div'); next.className = 'pwa-next';
    const label = document.createElement('p'); label.textContent = row.dataset.next === 'active' ? 'CURRENT DRIVE' : 'NEXT DEPARTURE';
    const time = document.createElement('h2'); time.textContent = row.dataset.timeLabel;
    const title = document.createElement('div'); title.textContent = row.dataset.title;
    title.className = 'pwa-muted';
    const meta = document.createElement('div'); meta.className = 'pwa-next-meta';
    meta.textContent = row.dataset.meta;
    const button = document.createElement('button'); button.textContent = 'View drive';
    button.onclick = () => row.querySelector('.pwa-row-main').click();
    next.append(label, time, title, meta, button); host.append(next);
    row.classList.add('pwa-promoted');
    }
    const attention = pwaAttention();
    if (attention.total) {
        const button = document.createElement('button'); button.className = 'pwa-attention';
        button.innerHTML = `<span class="pwa-attention-count">${attention.total}</span><span><strong>Needs your review</strong><small>${mfEscape(attention.description)}</small></span>${pwaIcon('arrow')}`;
        button.onclick = pwaOpenAttention; host.append(button);
    }
    if (host.children.length) pane.prepend(host);
    pwaPageHeading();
}

function pwaIcon(name) {
    const paths = {
        drives: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
        family: '<rect x="4" y="5" width="16" height="16" rx="2"/><path d="M8 3v4m8-4v4M4 11h16m-12 4h3m2 0h3"/>',
        household: '<path d="m3 11 9-8 9 8M5 10v11h5v-7h4v7h5V10"/>',
        moments: '<path d="M4 4h16v13H9l-5 4V4Z"/><path d="M8 8h8M8 12h6"/>',
        map: '<path d="m3 5 6-2 6 2 6-2v16l-6 2-6-2-6 2V5Zm6-2v16m6-14v16"/>',
        music: '<path d="M9 18V5l11-2v13M9 8l11-2"/><ellipse cx="6" cy="18" rx="3" ry="2"/><ellipse cx="17" cy="16" rx="3" ry="2"/>',
        critter: '<path d="M5 10V5l5 3h4l5-3v5c4 11-18 11-14 0Z"/><path d="M9 12h.01M15 12h.01M10 16h4"/>',
        programs: '<path d="M12 5v16M3 3c4 0 6 0 9 2 3-2 5-2 9-2v16c-4 0-6 0-9 2-3-2-5-2-9-2V3Z"/>',
        profile: '<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',
        arrow: '<path d="m9 5 7 7-7 7"/>',
        assistant: '<path d="m12 2 3 7 7 3-7 3-3 7-3-7-7-3 7-3 3-7Z"/>',
    };
    return `<svg class="pwa-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.profile}</svg>`;
}

function pwaPageHeading() {
    const host = document.getElementById('pwa-page-heading');
    if (!host) return;
    const adult = pwaIsAdult();
    const date = currentDates[activeDateIndex] || todayStr();
    const isToday = date === todayStr();
    const formatted = new Date(date + 'T12:00:00').toLocaleDateString(undefined, {weekday:'long', month:'long', day:'numeric'});
    const hour = new Date().getHours();
    const names = {
        drives: [isToday ? `Your ${hour < 12 ? 'morning' : hour < 17 ? 'afternoon' : 'evening'}` : 'Your day', isToday ? 'Your drives and commitments, in one place.' : formatted],
        family: ['Family plan', 'Everyone’s day, with the details that matter.'],
        myday: ['Your day', 'Your commitments, with room to plan ahead.'],
        chores: ['Household', 'The work, the lists, and who’s doing what.'],
        messages: ['Messages', 'Your conversations and family updates.'],
    };
    host.hidden = !adult || !names[currentView];
    if (!host.hidden) {
        const [title, sub] = names[currentView];
        const html = `<div><h2>${mfEscape(title)}</h2><p>${mfEscape(sub)}</p></div>${currentView === 'drives' ? '<button class="pwa-date-toggle" onclick="pwaToggleDates()" aria-label="Choose schedule day">'+pwaIcon('family')+'</button>' : ''}`;
        const signature = currentView + title + sub;
        if (host.dataset.signature !== signature) { host.innerHTML = html; host.dataset.signature = signature; }
        host.querySelector('button')?.setAttribute('aria-expanded', String(pwaDatesExpanded));
    }
    document.documentElement.dataset.pwaDates = pwaDatesExpanded ? 'open' : 'closed';
    if (adult) {
        document.getElementById('date-subtitle').textContent = formatted;
        const tab = document.querySelector('#tab-drives svg');
        if (!tab.dataset.original) tab.dataset.original = tab.innerHTML;
        if (!tab.dataset.adult) { tab.innerHTML = pwaIcon('drives').match(/<svg[^>]*>(.*)<\/svg>/)[1]; tab.setAttribute('fill', 'none'); tab.setAttribute('stroke', 'currentColor'); tab.setAttribute('stroke-width', '1.6'); tab.dataset.adult = '1'; }
    } else {
        const tab = document.querySelector('#tab-drives svg');
        if (tab.dataset.adult) { tab.innerHTML = tab.dataset.original; tab.setAttribute('fill', 'currentColor'); tab.removeAttribute('stroke'); delete tab.dataset.adult; }
    }
    let strip = document.getElementById('pwa-date-strip');
    if (!strip) { strip = document.createElement('div'); strip.id = 'pwa-date-strip'; document.getElementById('day-nav').append(strip); }
    strip.hidden = !adult || !['drives','family'].includes(currentView);
    if (!strip.hidden) {
        const signature = currentDates.join() + ':' + activeDateIndex;
        if (strip.dataset.signature !== signature) {
            strip.dataset.signature = signature;
            strip.innerHTML = currentDates.map((day, index) => {
                const d = new Date(day+'T12:00:00');
                return `<button onclick="pwaSelectDay(${index})" aria-label="${mfEscape(d.toLocaleDateString(undefined,{weekday:'long',month:'long',day:'numeric'}))}" aria-pressed="${index === activeDateIndex}"><span>${mfEscape(d.toLocaleDateString(undefined,{weekday:'short'}))}</span><b>${d.getDate()}</b></button>`;
            }).join('');
            const selected = strip.children[activeDateIndex];
            if (selected) strip.scrollLeft = selected.offsetLeft - strip.offsetLeft - strip.clientWidth / 2 + selected.clientWidth / 2;
        }
    }
}

function pwaToggleDates() { pwaDatesExpanded = !pwaDatesExpanded; pwaPageHeading(); }
function pwaSelectDay(index) {
    activeDateIndex = index;
    const days = document.getElementById('days-container');
    days.scrollLeft = index * days.clientWidth;
    updateHeaderDate();
}

// Render the adult row at the existing scheduler seam, keeping all actions
// and time calculations owned by app.html. No duplicated routing decisions.
function pwaAgendaRow({time, title, meta = '', extras = '', action = '', state = '', attrs = '', cls = ''}) {
    return `<div class="pwa-agenda-row ${cls}" ${attrs}>
        <time>${mfEscape(time)}${state ? `<small>${mfEscape(state)}</small>` : ''}</time>
        <div class="pwa-row-copy">${action ? `<button class="pwa-row-main" onclick="${mfEscape(action)}"><span>${mfEscape(title)}</span></button>` : `<h3>${mfEscape(title)}</h3>`}
        ${meta ? `<div class="pwa-row-meta">${meta}</div>` : ''}${extras}</div></div>`;
}

function pwaDriveRow(d) {
    const timeLabel = d.isInProgress ? 'En route' : `${d.colorTheme === 'blue' ? 'Leave at' : 'Arrive by'} ${d.timeStr}`;
    const next = d.isCompleted ? 'completed' : d.isInProgress ? 'active' : d.isPast ? 'past' : 'upcoming';
    const meta = `${formatDuration(d.mins)} drive${d.delayMins > 3 ? ` · ${d.delayMins}m traffic delay` : ''}`;
    const attrs = `data-next="${next}" data-time-label="${mfEscape(timeLabel)}" data-title="${mfEscape(d.title)}" data-meta="${mfEscape(meta)}"`;
    return pwaAgendaRow({time:d.timeStr, title:d.title,
        meta: d.subtitleHtml + `<span>${mfEscape(meta)}</span>`,
        extras:d.lateMins > 0 ? `<p class="pwa-warning">Arriving ${d.lateMins}m late</p>` : '',
        action:d.isCompleted ? '' : `openActionSheet(${d.actionArgs})`,
        state:d.isCompleted ? 'Completed' : d.isInProgress ? 'Driving' : d.isPast ? 'Past' : (d.colorTheme === 'blue' ? 'Leave' : 'Arrive'),
        attrs, cls:'pwa-leg-row'});
}

function pwaEventRow(event, start, past, badges, extras) {
    const key = encodeURIComponent(JSON.stringify(event)).replace(/'/g, "\\'");
    const allDay = event.timeStr === 'All Day';
    const end = !allDay && event.end && new Date(event.end) > new Date(start) ? `<span>Until ${mfEscape(formatTime(event.end))}</span>` : '';
    return pwaAgendaRow({time:allDay ? 'All day' : formatTime(start), title:event.title,
        meta: badges + (event.location ? `<span>${mfEscape(event.location.split(',')[0])}</span>` : '') + end,
        extras, action:`openEventModal('${key}')`, state:past ? 'Past' : '', cls:'pwa-event-row'});
}

function pwaAttention() {
    const jobs = pwaChoresOwner === selectedMemberId && currentMemberRole() === 'parent' && pwaAllowed('chores') && !houseRevealListsOnly ? houseChoresAttention() : 0;
    const requests = pwaRequestsOwner === selectedMemberId ? (myRequests.waiting_on_me || []).length : 0;
    return {jobs, requests, total:jobs + requests,
        description:[jobs ? `${jobs} household ${jobs === 1 ? 'review' : 'reviews'}` : '', requests ? `${requests} ${requests === 1 ? 'request' : 'requests'}` : ''].filter(Boolean).join(' · ')};
}

function pwaOpenAttention() {
    const dialog = document.getElementById('pwa-attention-dialog');
    const body = document.getElementById('pwa-attention-body');
    body.replaceChildren();
    const attention = pwaAttention();
    if (attention.jobs) body.append(pwaFeatureButton({id:'household', title:'Household reviews', description:`${attention.jobs} waiting for you`, run:() => {
        dialog.close(); pwaHouseSection = 'reviews'; setView('chores'); pwaRenderHouseTabs();
    }}));
    if (attention.requests) {
        const requests = document.createElement('div'); requests.className = 'pwa-review-requests'; requests.innerHTML = renderRequests();
        requests.addEventListener('click', event => { if (event.target.closest('button')) dialog.close(); }, true);
        body.append(requests);
    }
    if (!attention.total) body.textContent = 'Nothing waiting for your review.';
    dialog.showModal();
}

function pwaRenderHouseTabs() {
    if (!pwaIsAdult()) return;
    const tabs = houseRevealListsOnly ? [['lists','Lists']] : [['tasks','Tasks'],['lists','Lists']];
    if (!houseRevealListsOnly && currentMemberRole() === 'parent') tabs.push(['reviews','Reviews']);
    if (houseThreads.length && !houseRevealListsOnly) tabs.push(['threads','Threads']);
    if (!tabs.some(([id]) => id === pwaHouseSection)) pwaHouseSection = tabs[0][0];
    const root = document.getElementById('chores-container'); root.dataset.section = pwaHouseSection;
    const count = pwaChoresOwner === selectedMemberId ? houseChoresAttention() : 0;
    const wrap = document.getElementById('house-anchors');
    const html = `<div class="pwa-section-tabs" aria-label="Household sections">${tabs.map(([id,label]) => `<button onclick="pwaSelectHouse('${id}')" aria-pressed="${id === pwaHouseSection}">${label}${id === 'reviews' && count ? ` (${count})` : ''}</button>`).join('')}</div>`;
    if (wrap.innerHTML !== html) {
        const hadFocus = wrap.contains(document.activeElement);
        wrap.innerHTML = html;
        if (hadFocus) wrap.querySelector('[aria-pressed="true"]').focus();
    }
}
function pwaSelectHouse(section) { pwaHouseSection = section; pwaRenderHouseTabs(); }
function pwaFilterConversations(query) {
    document.querySelectorAll('#channel-list > button').forEach(button => {
        button.hidden = pwaIsAdult() && !button.textContent.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
    });
}

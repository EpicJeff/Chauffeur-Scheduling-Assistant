/* Presentation adapter only. Existing views still own data and actions. */
let pwaChoresOwner = null, pwaRequestsOwner = null;
let pwaHouseSection = 'tasks', pwaDatesExpanded = false;
let pwaArgyleOpening = false;
function pwaIsAdult() {
    return !!selectedMemberId && currentMemberRole() !== 'child';
}
function pwaOrderTabs(order) {
    order = [...order, 'argyle'];
    const bar = document.getElementById('pwa-tab-bar');
    const actual = [...bar.children].map(button => button.id.slice(4)).filter(id => order.includes(id));
    if (actual.join() !== order.join()) order.forEach(id => bar.append(document.getElementById('tab-' + id)));
}
function pwaOrbAllowed() {
    return pwaIsAdult() && scopeOf('chat.agent') !== 'none';
}
async function pwaOpenArgyle() {
    if (!pwaOrbAllowed() || pwaArgyleOpening) return;
    window.PwaArgyle?.close('messages');
    pwaArgyleOpening = true;
    let ch;
    try {
        if (window.PwaArgyle?.ensureDm) ch = await window.PwaArgyle.ensureDm(selectedMemberId);
        else {
            const res = await fetch(`${apiBase}api/channels/dm`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ member_id: selectedMemberId, other_member_id: 'argyle' })
            });
            if (!res.ok) throw new Error('dm refused');
            ch = await res.json();
        }
        if (!ch?.id) throw new Error('no channel');
    } catch (e) {
        showGlobalAlert('Could not open Argyle');
        return;
    } finally {
        pwaArgyleOpening = false;
    }
    setView('messages');
    openChannel(ch.id, ch);
}

function pwaArgyleBindOrb() {
    const orb = document.getElementById('tab-argyle');
    if (!orb || pwaArgyleBindOrb.bound) return;
    if (typeof pwaArgyleGesture !== 'function') return;
    pwaArgyleBindOrb.bound = true;
    const g = pwaArgyleGesture();
    let timer = null, pointer = null, handledAt = -Infinity;
    const clear = () => { clearTimeout(timer); timer = null; };
    const hold = () => {
        if (g.tick(performance.now()) === 'hold-start') window.PwaArgyle.open({mode: 'talk'});
    };
    orb.addEventListener('pointerdown', event => {
        if (!pwaOrbAllowed() || pointer !== null || event.isPrimary === false || event.button > 0) return;
        pointer = event.pointerId;
        g.down(performance.now());
        // Keep the release on the orb even after the overlay hides it.
        // Synthetic pointer events have no active pointer to capture.
        try { orb.setPointerCapture(event.pointerId); } catch (_) { }
        timer = setTimeout(hold, PWA_ARGYLE_HOLD_MS);
    });
    orb.addEventListener('pointerup', event => {
        if (pointer !== event.pointerId) return;
        handledAt = performance.now();
        clear();
        // A busy event loop can deliver release before the hold timer.
        hold();
        const action = g.up(performance.now());
        pointer = null;
        if (action === 'tap') window.PwaArgyle.open({mode: 'type'});
        else if (action === 'hold-end') window.PwaArgyle.done();
    });
    const cancel = () => {
        if (pointer === null) return;
        handledAt = performance.now();
        clear();
        if (g.state === 'holding') window.PwaArgyle.done();
        g.cancel(); pointer = null;
    };
    orb.addEventListener('pointercancel', cancel);
    orb.addEventListener('pointerleave', cancel);
    orb.addEventListener('contextmenu', event => event.preventDefault());
    orb.addEventListener('click', event => {
        event.preventDefault(); event.stopPropagation();
        if (pwaOrbAllowed() && (event.detail === 0 || performance.now() - handledAt >= 700))
            window.PwaArgyle.open({mode: 'type', keyboard: event.detail === 0});
    });
    orb.addEventListener('keydown', event => {
        if (pwaOrbAllowed() && (event.key === 'Enter' || event.key === ' ')) {
            event.preventDefault();
            handledAt = performance.now();
            window.PwaArgyle.open({mode: 'type', keyboard: true});
        }
    });
}

// One profile palette for every audience. Keep the chosen hue, adjusting
// accent brightness only as needed for text/buttons on both theme surfaces.
function pwaRelativeLuminance(color) {
    let hex = Array.isArray(color) ? null : color.replace(/^#/, '');
    if (hex && hex.length === 3) hex = [...hex].map(c => c + c).join('');
    const rgb = Array.isArray(color) ? color : [0,2,4].map(i => parseInt(hex.slice(i,i+2),16));
    return rgb.map(v => v/255).map(v => v <= .04045 ? v/12.92 : ((v+.055)/1.055)**2.4)
        .reduce((sum,v,i) => sum + v*[.2126,.7152,.0722][i],0);
}
function pwaProfilePalette(color, dark) {
    let hex = /^#[0-9a-f]{3}(?:[0-9a-f]{3})?$/i.test(color || '') ? color.slice(1) : '3b82f6';
    if (hex.length === 3) hex = [...hex].map(c => c + c).join('');
    const rgb = [0,2,4].map(i => parseInt(hex.slice(i,i+2),16));
    const mix = (a,b,t) => a.map((v,i) => Math.round(v*(1-t)+b[i]*t));
    const luminance = pwaRelativeLuminance;
    const contrast = (a,b) => (Math.max(luminance(a),luminance(b))+.05)/(Math.min(luminance(a),luminance(b))+.05);
    const tint = (base, amount) => mix(base,rgb,amount);
    const bases = dark
        ? [[248,250,252],[241,245,249],[222,229,238],[205,215,227],[185,195,209],[185,195,209],[115,130,149],[72,86,103],[53,65,80],[28,34,42],[18,23,30]]
        : [[18,25,33],[24,31,39],[40,49,59],[57,68,79],[80,91,104],[80,91,104],[158,170,184],[204,213,224],[220,227,236],[255,255,255],[255,255,255]];
    const shades = [50,100,200,300,400,500,600,700,800,900,950];
    const palette = Object.fromEntries(shades.map((shade,i) => [shade,tint(bases[i],shade === 900 ? (dark ? .10 : 0) : shade === 950 ? (dark ? .08 : .045) : .12)]));
    const wash = dark ? tint([32,38,46],.24) : tint([255,255,255],.13);
    const start = dark ? mix(rgb,[255,255,255],.55) : rgb;
    let accent = start;
    for (let step = 0; step <= 100; step++) {
        accent = mix(start,dark ? [255,255,255] : [0,0,0],step/100);
        if ([wash,palette[900],palette[950]].every(bg => contrast(accent,bg) >= 4.5)) break;
    }
    return {...Object.fromEntries(Object.entries(palette).map(([shade,value]) => ['gray-'+shade,value.join(' ')])),
        accent:`rgb(${accent.join(' ')})`, wash:`rgb(${wash.join(' ')})`};
}

// The sky follows the clock; the person's hue remains the accent.
const pwaSkyBands = {
    morning: {
        light: { top: '#fff0e6', mid: '#f6eef7', bottom: '#eef0fb' },
        dark: { top: '#30242b', mid: '#272536', bottom: '#202839' }
    },
    afternoon: {
        light: { top: '#fff4e8', mid: '#f1f2fa', bottom: '#e6effb' },
        dark: { top: '#2d2a2c', mid: '#242c3a', bottom: '#222c3e' }
    },
    evening: {
        light: { top: '#fbe7df', mid: '#f0e7f4', bottom: '#e5eaf9' },
        dark: { top: '#39252d', mid: '#302638', bottom: '#232b40' }
    },
    night: {
        light: { top: '#eee6ee', mid: '#e5e7f3', bottom: '#dce5f6' },
        dark: { top: '#25212e', mid: '#202333', bottom: '#192539' }
    }
};
function pwaSky(hour, dark) {
    const band = hour >= 5 && hour < 12 ? 'morning'
        : hour >= 12 && hour < 17 ? 'afternoon'
        : hour >= 17 && hour < 21 ? 'evening' : 'night';
    return Object.assign({}, pwaSkyBands[band][dark ? 'dark' : 'light']);
}
pwaSky.contrast = function (hexA, hexB) {
    const a = pwaRelativeLuminance(hexA), b = pwaRelativeLuminance(hexB);
    return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
};
function pwaSyncSky() {
    const root = document.documentElement;
    const sky = pwaSky(new Date().getHours(), root.dataset.theme === 'dark');
    for (const [stop, color] of Object.entries(sky)) root.style.setProperty('--pwa-sky-' + stop, color);
}
window.pwaSyncSky = pwaSyncSky;
if (!window.pwaSkyVisibilityBound) {
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') pwaSyncSky();
    });
    window.pwaSkyVisibilityBound = true;
}
function pwaSyncProfileColors() {
    const root = document.documentElement;
    const member = membersData.find(m => m.id === selectedMemberId);
    if (!member) { delete root.dataset.profileColor; pwaSyncProfileColors.color = null; return; }
    const color = member.color_code || '#3b82f6';
    if (pwaSyncProfileColors.color !== color) {
        pwaSyncProfileColors.color = color;
        for (const theme of ['light','dark']) for (const [name,value] of Object.entries(pwaProfilePalette(color,theme === 'dark')))
            root.style.setProperty(`--profile-${theme}-${name}`,value);
    }
    root.dataset.profileColor = color;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = `rgb(${getComputedStyle(root).getPropertyValue('--c-gray-900').trim()})`;
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
    const labels = {drives: adult ? 'Today' : 'My Day', myday: 'My Day',
        family: adult ? 'Plan' : 'Family', chores: adult ? 'Household' : 'House', messages:'Messages', more:'More'};
    Object.entries(labels).forEach(([id, label]) => {
        document.querySelector(`#tab-${id} > span`).textContent = label;
    });
    const orb = document.getElementById('tab-argyle');
    orb.hidden = !pwaOrbAllowed();
    if (!orb.firstElementChild && window.ArgyleOrb) orb.innerHTML = ArgyleOrb.glyph();
    pwaArgyleBindOrb();
    // Keep keyboard/reading order aligned with the visual tab order.
    if (adult) pwaOrderTabs(['myday','drives','family','chores','messages','map','music','more']);
    const more = document.getElementById('tab-more');
    more.style.display = adult ? 'flex' : 'none';
    document.getElementById('pwa-identity').setAttribute('aria-label', 'Your profile and preferences');
    document.getElementById('pwa-more-container').hidden = !adult || currentView !== 'more';
    document.querySelectorAll('#pwa-tab-bar > button').forEach(button => {
        const name = button.id.slice(4);
        const active = name === currentView || (adult && name === 'more' && ['map', 'music', 'library', 'projects'].includes(currentView));
        if (active) button.setAttribute('aria-current', 'page');
        else button.removeAttribute('aria-current');
    });
    if (adult) document.getElementById('pwa-more-title').textContent = 'More from Chauffeur';
    if (adult && currentView === 'more') pwaRenderDirectory();
    pwaPageHeading();
    if (adult) {
        document.getElementById('tab-kidplan')?.style.setProperty('display','none');
        pwaRenderHouseTabs();
    }
    pwaChildSync();
    pwaSyncProfileColors();
    pwaSyncSky();
}

function pwaAllowed(view) {
    // Projects has no tab (one-list spec §5): More is its only door, open to
    // every signed-in member but a helper or a guest (applyRoleTabs' rule).
    if (view === 'projects') return !!selectedMemberId && !['helper', 'guest'].includes(currentMemberRole());
    // Inline display is set by applyRoleTabs, including the async list grant.
    const tab = document.getElementById(`tab-${view}`);
    return !!tab && tab.style.display !== 'none';
}

function pwaFeatures() {
    const items = [];
    const route = (id, title, description, view) => {
        if (pwaAllowed(view)) items.push({id, title, description, run: () => setView(view)});
    };
    if (pwaChildStage() && selectedDriverId && kidCan('can_drive')) route('drives', 'My drives', 'Your driving responsibilities', 'drives');
    // Explorer reaches the same view from More, with no extra tab.
    if (pwaChildStage() === 'explorer' || (pwaChildStage() !== 'sprout' && pwaAllowed('projects')))
        items.push({id: 'projects', title: 'Projects', description: 'Your goals, steps and linked records', run: () => setView('projects')});
    // The program library: the household's programs, each run in a project.
    if (pwaChildStage() !== 'sprout' && (pwaChildStage() === 'explorer' || pwaAllowed('projects')))
        items.push({id: 'library', title: 'Library', description: 'The household’s programs and who is running them', run: () => setView('library')});
    route('map', 'Family map', 'Find shared locations and driving progress', 'map');
    route('music', 'Music', 'Favorites and household listening', 'music');
    const rewards = chfFeatureOn('rewards');
    route('household', pwaChildStage() ? (rewards ? 'Tasks & rewards' : 'Tasks & points') : 'Household',
        rewards ? 'Tasks, rewards and shared lists' : 'Tasks, points and shared lists', 'chores');
    route('moments', 'Messages & moments', 'Conversations and shared family updates', 'messages');
    if (pwaAllowed('drives') || pwaAllowed('myday')) {
        items.push({id: 'programs', title: 'My programs', description: 'Practice and learning in your day', run: () => {
            setView(pwaChildStage() ? 'myday' : pwaAllowed('drives') ? 'drives' : 'myday');
            if (pwaChildStage()) pwaChildScrollPrograms();
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
    // Critters switched off: the editor and arena were never included, and
    // their doors go with them (services/household_features.py).
    const critters = typeof openPetEditor === 'function';
    if (critters && pwaChildStage() && membersData.find(m => m.id === selectedMemberId)?.pet_name)
        items.push({id:'critter', title:'Critter battle', description:'Play with your companion', run:()=>openPetBattle(selectedMemberId)});
    // School (K4d): a child's own assignments; a parent picks which child.
    // Helpers have no school-list reach, so no door.
    if (typeof pwaSchoolOpen === 'function' && (pwaChildStage()
            || (['parent', 'adult'].includes(currentMemberRole()) && pwaSchoolChildren().length)))
        items.push({id: 'school', title: 'School', description: pwaChildStage()
            ? 'Assignments, classes and what is due' : 'Each child’s assignments, tests and what is due',
            run: () => pwaSchoolOpen()});
    if (critters) items.push({id: 'critter', title: 'My critter', description: 'Visit and customize your companion', run: () => openPetEditor(selectedMemberId)});
    items.push({id: 'profile', title: 'Profile & appearance', description: 'Avatar, theme, notifications and sign out', run: pwaOpenProfile});
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
        ...(typeof openPetEditor === 'function'
            ? [action('critter', 'My critter', 'Visit your companion', () => openPetEditor(selectedMemberId))] : []),
        action('theme', 'Appearance', `Theme: ${themePref()}. Change between device, light and dark.`, () => {
            cycleTheme();
            const button = dialog.querySelector('[data-feature="theme"] small');
            button.textContent = `Theme: ${themePref()}. Change between device, light and dark.`;
        }, true),
        action('refresh', 'Refresh', 'Get the latest schedule', () => fetchSchedule(true)),
    ];
    if (!document.getElementById('btn-push').classList.contains('hidden'))
        items.push(action('push', 'Enable notifications', 'Receive family updates on this device', enableNotifications));
    if (window.ChauffeurVoiceSetup) {
        // Set up my voice (spec 2026-10-13). Enrollment, re-enrollment and
        // deletion are the member's own acts here; turning recognition on
        // is a parent's, per speaker, by voice or in Config.
        items.push(action('voice', 'Set up my voice', 'Answer five short questions so your speakers can recognise you', () => ChauffeurVoiceSetup.open()));
        items.push(action('voice-delete', 'Delete my voice', 'Remove your voice template from every speaker', () => ChauffeurVoiceSetup.deleteVoice()));
    }
    items.push(action('switch', 'Switch person / sign out', 'Return to the family member picker', clearDriver));
    document.getElementById('pwa-profile-actions').replaceChildren(...items.map(pwaFeatureButton));
    if (!dialog.open) dialog.showModal();
}

async function pwaStartVoiceSetup() {
    // A child's screen asks for a parent's PIN once; it goes to the server and
    // never onto the screen. The server resolves which parent by id.
    const me = typeof members !== 'undefined' ? members.find(m => m.id === selectedMemberId) : null;
    if (me && me.role === 'child') {
        const parents = members.filter(m => m.role === 'parent');
        if (!parents.length) { showGlobalAlert('A parent needs to set up their account first.'); return; }
        const parent = parents[0];
        const entry = await promptForPin(`${parent.name}, enter your PIN`, `To set up ${me.name}'s voice`);
        if (entry.action !== 'ok' || !entry.value) return;
        return ChauffeurVoiceSetup.start(parent.id, entry.value);
    }
    return ChauffeurVoiceSetup.start();
}

function pwaRefreshOverview() {
    document.querySelectorAll('.pwa-overview').forEach(node => node.remove());
    document.querySelectorAll('.pwa-promoted').forEach(node => node.classList.remove('pwa-promoted'));
    if (pwaIsAdult() && currentView === 'myday') return;
    if (!pwaIsAdult() && !(pwaChildStage() && selectedDriverId && kidCan('can_drive') && currentView === 'drives')) return;
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
            if (pwaChildStage() ? kidHorizonDays() > 0 : pwaAllowed('family')) {
                const link = document.createElement('button');
                link.textContent = pwaChildStage() ? 'My plan →' : 'Family plan →';
                link.onclick = () => pwaChildStage() ? pwaChildOpenPlan() : setView('family'); title.append(link);
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
    if (pwaChildStage()) pwaChildSync();
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
        projects: '<path d="M4 5h16v14H4zM8 9h8M8 13h5"/>',
        programs: '<path d="M12 5v16M3 3c4 0 6 0 9 2 3-2 5-2 9-2v16c-4 0-6 0-9 2-3-2-5-2-9-2V3Z"/>',
        library: '<path d="M4 4h4v16H4zM10 4h4v16h-4zM16 5l3.5-1 3 15.5-3.5 1z"/>',
        profile: '<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',
        theme: '<path d="M20.5 13a8.5 8.5 0 0 1-9.5-9.5A8.5 8.5 0 1 0 20.5 13Z"/>',
        refresh: '<path d="M20 4v6h-6M4 20v-6h6M20 10a8 8 0 0 0-14-5M4 14a8 8 0 0 0 14 5"/>',
        push: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',
        switch: '<path d="M10 4H4v16h6M9 12h12m-4-4 4 4-4 4"/>',
        arrow: '<path d="m9 5 7 7-7 7"/>',
        assistant: '<path d="m12 2 3 7 7 3-7 3-3 7-3-7-7-3 7-3 3-7Z"/>',
        school: '<path d="m2 9 10-5 10 5-10 5L2 9Z"/><path d="M6 11v5c3 2 9 2 12 0v-5M22 9v6"/>',
    };
    return `<svg class="pwa-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.profile}</svg>`;
}

function pwaPageHeading() {
    const host = document.getElementById('pwa-page-heading');
    if (!host) return;
    const adult = pwaIsAdult();
    if (adult && currentView === 'myday') {
        host.hidden = true;
        host.innerHTML = '';
        delete host.dataset.signature;
        const strip = document.getElementById('pwa-date-strip');
        if (strip) strip.hidden = true;
        return;
    }
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
    if (!currentDates[index]) return;
    activeDateIndex = index;
    const days = document.getElementById('days-container');
    days.scrollLeft = index * days.clientWidth;
    if (pwaIsAdult() && currentView === 'myday') {
        mydayOffset = Math.round((new Date(currentDates[index] + 'T12:00:00') - new Date(todayStr() + 'T12:00:00')) / 86400000);
        updateMyDayLabel();
        return pwaRenderBrief();
    }
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
    const end = new Date(d.end).getTime();
    const state = d.isCompleted ? 'completed' : d.isInProgress ? 'active'
        : (Number.isFinite(end) ? end < Date.now() : d.isPast) ? 'past' : 'upcoming';
    const meta = `${formatDuration(d.mins)} drive${d.delayMins > 3 ? ` · ${d.delayMins}m traffic delay` : ''}`;
    const primary = d.isCompleted ? '' : `openActionSheet(${d.actionArgs})`;
    const secondary = d.eventKey ? `openEventModal(${JSON.stringify(d.eventKey)})` : '';
    const attrs = `data-kind="drive" data-start="${mfEscape(d.start || '')}" data-end="${mfEscape(d.end || '')}" data-place="${mfEscape(d.location || '')}" data-state="${state}" data-primary="${mfEscape(primary)}" data-secondary="${mfEscape(secondary)}" data-leg-id="${mfEscape(d.legId || '')}" data-event-id="${mfEscape(d.eventId || '')}" data-late="${mfEscape(d.lateMins || 0)}" data-next="${next}" data-time-label="${mfEscape(timeLabel)}" data-title="${mfEscape(d.title)}" data-meta="${mfEscape(meta)}"`;
    return pwaAgendaRow({time:d.timeStr, title:d.title,
        meta: d.subtitleHtml + `<span>${mfEscape(meta)}</span>`,
        extras:d.lateMins > 0 ? `<p class="pwa-warning">Arriving ${d.lateMins}m late</p>` : '',
        action:primary,
        state:d.isCompleted ? 'Completed' : d.isInProgress ? 'Driving' : d.isPast ? 'Past' : (d.colorTheme === 'blue' ? 'Leave' : 'Arrive'),
        attrs, cls:'pwa-leg-row'});
}

function pwaEventRow(event, start, past, badges, extras) {
    const key = encodeURIComponent(JSON.stringify(event)).replace(/'/g, "\\'");
    const allDay = event.timeStr === 'All Day' || !!event.all_day;
    const end = !allDay && event.end && new Date(event.end) > new Date(start) ? `<span>Until ${mfEscape(formatTime(event.end))}</span>` : '';
    const attrs = `data-kind="event" data-all-day="${allDay ? '1' : '0'}" data-start="${mfEscape(pwaLocalIso(start))}" data-end="${mfEscape(pwaLocalIso(event.end || start))}" data-title="${mfEscape(event.title)}" data-place="${mfEscape(event.location || '')}" data-meta="${mfEscape(end ? 'Until ' + formatTime(event.end) : '')}" data-state="${past ? 'past' : 'upcoming'}" data-primary="${mfEscape(`openEventModal('${key}')`)}" data-leg-id="" data-event-id="${mfEscape(event.id || '')}"`;
    return pwaAgendaRow({time:allDay ? 'All day' : formatTime(start), title:event.title,
        meta: badges + (event.location ? `<span>${mfEscape(event.location.split(',')[0])}</span>` : '') + end,
        extras, action:`openEventModal('${key}')`, state:past ? 'Past' : '', attrs, cls:'pwa-event-row'});
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
        button.hidden = !button.textContent.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
    });
}

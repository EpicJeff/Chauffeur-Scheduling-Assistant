/* Child presentation. Server capabilities, existing endpoints and actions own
   permissions, progress and scheduling; this file only arranges that data. */
let pwaChildPlan = false, pwaChildDay = null, pwaChildTaskSection = 'tasks';
function pwaChildStage() {
    if (!selectedMemberId || currentMemberRole() !== 'child') return '';
    const stage = kidCaps().stage;
    return ['sprout', 'explorer', 'navigator', 'copilot'].includes(stage) ? stage : 'explorer';
}
function pwaChildSync() {
    const root = document.documentElement, stage = pwaChildStage();
    if (!stage) {
        delete root.dataset.childStage; delete root.dataset.childPlan;
        pwaChildSync.member = null; pwaChildPlan = false; pwaChildDay = null;
        document.getElementById('pwa-child-detail').close();
        return;
    }
    if (pwaChildSync.member !== selectedMemberId) {
        pwaChildSync.member = selectedMemberId;
        pwaChildPlan = false; pwaChildDay = null; pwaChildTaskSection = 'tasks';
        document.getElementById('pwa-child-detail').close();
    }
    root.dataset.childStage = stage;
    root.dataset.childPlan = String(pwaChildPlan);
    if (['messages','drives'].includes(currentView)) {
        const heading = document.getElementById('pwa-page-heading');
        heading.hidden = false;
        heading.innerHTML = `<div><h2>${currentView === 'drives' ? 'Your drives' : stage === 'sprout' ? 'Your family' : 'Messages'}</h2><p>${currentView === 'drives' ? 'Your driving responsibilities.' : 'Your conversations and family updates.'}</p></div>`;
        delete heading.dataset.signature;
    }
    const labels = {myday:'Today', chores:stage === 'sprout' ? 'My things' : 'Tasks',
        messages:stage === 'sprout' ? 'Family' : 'Messages', more:stage === 'sprout' ? 'My things' : 'More'};
    for (const [id, label] of Object.entries(labels)) document.querySelector(`#tab-${id} > span`).textContent = label;
    let plan = document.getElementById('tab-kidplan');
    if (!plan) {
        plan = document.createElement('button'); plan.id = 'tab-kidplan'; plan.type = 'button';
        plan.className = document.getElementById('tab-myday').className;
        plan.innerHTML = pwaIcon('family') + '<span>Plan</span>';
        plan.onclick = pwaChildOpenPlan;
        document.getElementById('tab-myday').after(plan);
    }
    plan.style.display = ['navigator', 'copilot'].includes(stage) && kidHorizonDays() > 0 ? 'flex' : 'none';
    const order = stage === 'sprout' ? ['myday','kidplan','chores','more','messages','drives','family','map','music']
        : ['myday', 'kidplan', 'chores', 'messages', 'more', 'drives', 'family', 'map', 'music'];
    pwaOrderTabs(order);
    document.getElementById('tab-more').style.display = 'flex';
    document.getElementById('pwa-more-container').hidden = currentView !== 'more';
    document.getElementById('pwa-more-title').textContent = stage === 'sprout' ? 'My things' : 'More for you';
    for (const id of order) {
        const active = id === 'kidplan' ? currentView === 'myday' && pwaChildPlan
            : id === 'myday' ? currentView === 'myday' && !pwaChildPlan
            : id === 'more' ? ['more', 'map', 'music', 'drives'].includes(currentView) : id === currentView;
        document.getElementById('tab-' + id).toggleAttribute('aria-current', active);
        if (active) document.getElementById('tab-' + id).setAttribute('aria-current', 'page');
    }
    if (currentView === 'more') pwaRenderDirectory();
    pwaChildHouseTabs();
}
async function pwaChildScrollPrograms() {
    await renderMyDay();
    document.querySelector('#myday-content [data-myday-program], #myday-content .child-programs')?.scrollIntoView({block:'start', behavior:'smooth'});
}
function pwaChildOpenPlan() {
    if (!pwaChildStage() || kidHorizonDays() <= 0) return;
    setView('myday'); pwaChildPlan = true; mydayOffset = 0;
    pwaSyncShell(); renderMyDay();
}
async function pwaChildChooseDate(offset) {
    mydayOffset = Math.max(0, Math.min(kidHorizonDays(), offset));
    await renderMyDay();
    document.querySelector('.child-dates [aria-pressed="true"]')?.focus({preventScroll:true});
}
function pwaChildDates() {
    return `<nav class="child-dates" aria-label="Your plan dates">${Array.from({length:kidHorizonDays() + 1}, (_, i) => {
        const d = new Date(_mydayLocalDate(i) + 'T12:00:00');
        return `<button onclick="pwaChildChooseDate(${i})" aria-pressed="${i === mydayOffset}"><span>${i === 0 ? 'Today' : d.toLocaleDateString(undefined,{weekday:'short'})}</span><b>${d.getDate()}</b></button>`;
    }).join('')}</nav>`;
}
function pwaChildCompanion(member) {
    const src = member.pet_id ? petFaceSrc(member.pet_id).replaceAll('&amp;', '&') : member.figure;
    return src ? `<button class="child-companion" onclick="${member.pet_id ? 'openPetEditor' : 'openAvatarEditor'}(selectedMemberId)" aria-label="${member.pet_id ? 'Visit your critter' : 'Edit your character'}"><img src="${mfEscape(src)}" alt=""></button>`
        : `<button class="child-companion child-egg" onclick="openPetEditor(selectedMemberId)" aria-label="Hatch a critter">${pwaIcon('critter')}</button>`;
}
function pwaChildRoutineRow(item, index, interactive) {
    return `<div class="child-task-row ${item.checked ? 'child-done' : ''}"><label>
        <input aria-label="${mfEscape(item.title)}" type="checkbox" ${item.checked ? 'checked' : ''} ${interactive ? '' : 'disabled'} onchange="pwaChildCheck(${index},this.checked,this)">
        <span>${mfEscape(item.title)}${item.time_of_day ? `<small>${formatClock(item.time_of_day)}</small>` : ''}</span></label>
        <button class="child-task-details" onclick="pwaChildRoutineDetail(${index})" aria-label="Details: ${mfEscape(item.title)}">${pwaIcon('arrow')}</button></div>`;
}
function pwaChildCheck(index, checked, control = null) {
    const day = pwaChildDay;
    if (!day || day.owner !== selectedMemberId || day.offset !== 0) return;
    const item = day.items[index];
    if (checked && item.steps?.length) {
        if (control) control.checked = false;
        pwaChildRoutineDetail(index); return;
    }
    toggleRoutine(item.id, checked);
}
function pwaChildDialog(title, html) {
    const dialog = document.getElementById('pwa-child-detail');
    document.getElementById('pwa-child-detail-title').textContent = title;
    document.getElementById('pwa-child-detail-body').innerHTML = html;
    // Navigation/actions use existing owners. Close the detail before opening
    // a map, conversation or nested prompt; form controls stay in the sheet.
    dialog.querySelector('#pwa-child-detail-body').onclick = event => {
        if (event.target.closest('button') && !event.target.closest('[data-stay]')) dialog.close();
    };
    if (!dialog.open) dialog.showModal();
}
function pwaChildRoutineDetail(index) {
    const day = pwaChildDay;
    if (!day || day.owner !== selectedMemberId) return;
    const item = day.items[index], interactive = day.offset === 0;
    pwaChildDialog(item.title, `<div class="child-task-art ${item.image_id ? 'child-task-photo' : ''}">${item.image_id ? `<img src="${apiBase}api/media/${encodeURIComponent(item.image_id)}" alt="">` : kidGlyph(item)}</div>
        ${item.description ? `<p>${mfEscape(item.description)}</p>` : ''}
        ${item.steps?.length && !item.checked ? kidStepRows(item, interactive) : interactive ? `<button class="child-primary" onclick="pwaChildCheck(${index},${!item.checked})">${item.checked ? 'Mark not done' : pwaChildStage() === 'sprout' ? 'I did it!' : 'Mark done'}</button>` : '<p>This is a preview of your routine.</p>'}`);
}
function pwaChildRideDetail(index) {
    const day = pwaChildDay;
    if (!day || day.owner !== selectedMemberId) return;
    pwaChildDialog('Your plan', renderMyDayCard(day.rides[index]) + (day.offset === 0 && kidCan('can_request') ? '<button class="child-primary" onclick="askForSomething()">Ask for a change</button>' : ''));
}
function pwaChildRenderDay({data, routineData, programItems, balance, jobs = [], offset, date}) {
    const stage = pwaChildStage(), young = ['sprout','explorer'].includes(stage);
    const member = membersData.find(m => m.id === selectedMemberId) || {};
    const items = routineData?.items || [], rides = data.rides || [];
    pwaChildDay = {owner:selectedMemberId, items, rides, offset};
    const interactive = offset === 0, plan = pwaChildPlan;
    const dateLabel = new Date(date + 'T12:00:00').toLocaleDateString(undefined,{weekday:'long', month:'long', day:'numeric'});
    const heading = plan ? 'Your plan' : stage === 'sprout' ? `Hi, ${(member.name || '').split(' ')[0]}!`
        : stage === 'explorer' ? `Hey, ${(member.name || '').split(' ')[0]}!` : stage === 'copilot' ? 'Today, on your terms.' : 'Your day';
    let html = `<header class="child-greeting"><div><h1>${mfEscape(heading)}</h1><p>${plan ? mfEscape(dateLabel) : stage === 'sprout' ? 'One little step at a time.' : stage === 'explorer' ? 'A little progress, every day.' : mfEscape(dateLabel)}</p></div>${young && !plan ? pwaChildCompanion(member) : ''}</header>`;
    if (plan) html += pwaChildDates();
    html += renderStatusBanner(data.status_days, date);
    const upcoming = rides.map((r,i) => ({r,i})).filter(({r}) => r.status !== 'completed' && !(r.optional && r.optional_decision !== 'attend') && (!interactive || new Date(r.end || r.start).getTime() >= Date.now())).sort((a,b) => new Date(a.r.start)-new Date(b.r.start));
    const next = upcoming[0];
    if (next) {
        const leg = next.r.legs?.filter(l => l.status !== 'completed' && (!interactive || new Date(l.end || l.start).getTime() >= Date.now())).sort((a,b)=>new Date(a.start)-new Date(b.start))[0];
        const driver = leg ? leg.driver : next.r.driver, time = leg?.start || next.r.start;
        const person = `<span class="child-person">${driver ? avatarInner(driver, mfEscape((driver.name || '?').charAt(0))) : pwaIcon('family')}</span>`;
        html += young ? `<button class="child-pickup child-pickup-compact" onclick="pwaChildRideDetail(${next.i})" aria-label="View pickup details">${person}<div><h2>${driver ? mfEscape(driver.name) + (leg?.type === 'pickup' ? ' picks you up at ' : ' takes you at ') : 'Coming up at '}${formatTime(time)}</h2><p>${mfEscape(next.r.title)}${!driver ? ' · Driver not assigned yet' : ''}</p></div>${pwaIcon('arrow')}</button>`
            : `<section class="child-pickup">${person}<div><span class="child-eyebrow">${leg?.type === 'pickup' ? 'Your ride home' : 'Coming up'}</span><h2>${driver ? mfEscape(driver.name) + ' · ' : ''}${formatTime(time)}${leg?.type === 'pickup' ? ' pickup' : ''}</h2><p>${mfEscape(next.r.title)}${!driver ? ' · Driver not assigned yet' : ''}</p>
            <div class="child-actions"><button onclick="pwaChildRideDetail(${next.i})">${stage === 'sprout' ? 'Who takes me?' : 'View details'}</button>${interactive && kidCan('can_request') ? '<button onclick="askForSomething()">Ask for a change</button>' : ''}</div></div></section>`;
    } else if (data.launch) {
        html += `<section class="child-pickup"><div><span class="child-eyebrow">Getting ready</span><h2>Leave by ${formatTime(data.launch.leave_at)}</h2><p>${mfEscape(data.launch.title || '')}${data.launch.driver ? ' · with ' + mfEscape(data.launch.driver.name) : ''}</p></div></section>`;
    }
    if (selectedDriverId && kidCan('can_drive') && pwaAllowed('drives')) html += `<button class="child-drive-link" onclick="setView('drives')">${pwaIcon('drives')} Your driving schedule ${pwaIcon('arrow')}</button>`;
    const done = items.filter(i => i.checked).length;
    // Lead with the current time bucket, retaining overdue and completed work
    // under "All of today's routine" so an unfinished morning cannot crowd out pickup.
    const now = new Date(), minute = now.getHours()*60 + now.getMinutes();
    const bucket = value => value < 720 ? 0 : value < 1020 ? 1 : 2;
    const current = items.map((item,index)=>({item,index})).filter(({item})=>!item.checked).sort((a,b)=>{
        const rank = item => !item.time_of_day ? 0 : bucket(Number(item.time_of_day.slice(0,2))*60 + Number(item.time_of_day.slice(3))) === bucket(minute) ? 0 : item.time_of_day > `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}` ? 1 : 2;
        return rank(a.item)-rank(b.item);
    });
    if (items.length) {
        if (stage === 'sprout' && !plan) {
            const nextTask = current[0];
            html += `<section class="child-step"><p class="child-progress">${done} of ${items.length} done · One little step</p>`;
            if (nextTask) {
                const item = nextTask.item;
                html += `<div class="child-task-art">${item.image_id ? `<img src="${apiBase}api/media/${encodeURIComponent(item.image_id)}" alt="">` : kidGlyph(item)}</div><h2>${mfEscape(item.title)}</h2><button class="child-primary" onclick="pwaChildCheck(${nextTask.index},true)">${item.steps?.length ? 'Let’s do it' : 'I did it! ✓'}</button>`;
            } else html += '<h2>You did your routine!</h2><p>Time for something else.</p>';
            html += '</section><div class="child-shortcuts">';
            if (current[1]) html += `<button onclick="pwaChildRoutineDetail(${current[1].index})">${kidGlyph(current[1].item)}<span>Then: ${mfEscape(current[1].item.title)}</span></button>`;
            html += `<button onclick="setView('messages')">${pwaIcon('household')}<span>My grown-ups</span></button></div>`;
        } else {
            html += `<section class="child-priorities"><span class="child-eyebrow">${stage === 'explorer' ? 'Now' : 'Your priorities'}</span><h2>${stage === 'explorer' ? 'Make room for your day.' : 'Focus on these'}</h2><p class="child-progress">${done} of ${items.length} done</p>${(plan ? items.map((item,index)=>({item,index})) : current.slice(0,3)).map(({item,index})=>pwaChildRoutineRow(item,index,interactive)).join('')}${!current.length ? '<p>Your routine is complete.</p>' : ''}</section>`;
        }
        if (!plan) html += `<details class="child-all-routine"><summary>All of today’s routine</summary>${items.map((item,i)=>pwaChildRoutineRow(item,i,interactive)).join('')}</details>`;
    } else if (stage === 'sprout' && !plan) html += '<section class="child-step"><h2>A little room to play.</h2><p>No routine steps today.</p><button class="child-primary" onclick="setView(\'messages\')">My grown-ups</button></section>';
    if (!young && jobs.length && pwaAllowed('chores')) html += `<section class="child-jobs"><h2>Your household tasks</h2>${jobs.slice(0,2).map(job=>`<button class="child-agenda-row" onclick="setView('chores')"><span><strong>${mfEscape(job.title)}</strong><small>${job.state === 'done' ? 'Waiting for approval' : 'Assigned to you'}</small></span>${pwaIcon('arrow')}</button>`).join('')}</section>`;
    html += renderDueSoonSection(data.due_soon);
    const timeline = rides.map((r,i)=>({min:new Date(r.start).getHours()*60+new Date(r.start).getMinutes(),html:`<button class="child-agenda-row" onclick="pwaChildRideDetail(${i})"><time>${formatTime(r.start)}</time><span><strong>${mfEscape(r.title)}</strong><small>${mfEscape(r.location || '')}${r.status === 'completed' ? ' · Done' : ''}</small></span>${pwaIcon('arrow')}</button>`})).concat(programItems.timed).sort((a,b)=>a.min-b.min);
    html += `<section class="child-agenda"><div class="child-section-heading"><h2>${plan ? 'On this day' : stage === 'explorer' ? 'Coming up' : 'Your schedule'}</h2>${!plan && kidHorizonDays() > 0 ? `<button onclick="pwaChildOpenPlan()">${stage === 'explorer' ? 'See my week' : 'My plan'} →</button>` : ''}</div>${timeline.map(x=>x.html).join('') || '<p class="pwa-empty">No rides scheduled for this day.</p>'}</section>`;
    if (programItems.rest) html += `<section class="child-programs"><h2>My programs</h2>${programItems.rest}</section>`;
    if (interactive) {
        html += renderRequests();
        if (kidCan('can_request') && !next) html += '<button class="child-secondary" onclick="askForSomething()">Ask for something</button>';
        if (balance !== null && kidCan('show_points') && pwaAllowed('chores')) html += `<button class="child-rewards-link" onclick="pwaChildOpenRewards()">${balance} points · Your rewards ${pwaIcon('arrow')}</button>`;
    }
    return html;
}
function pwaChildOpenRewards() { setView('chores'); pwaChildTaskSection = 'rewards'; pwaChildHouseTabs(); }
function pwaChildHouseTabs() {
    const stage = pwaChildStage(); if (!stage) return;
    const tabs = houseRevealListsOnly ? [['lists','Lists']] : [['tasks',stage === 'sprout' ? 'My jobs' : 'Tasks'],['rewards','Rewards'],['lists','Lists']];
    if (houseThreads.length && !houseRevealListsOnly) tabs.push(['threads','Threads']);
    if (!tabs.some(([id])=>id === pwaChildTaskSection)) pwaChildTaskSection = tabs[0][0];
    document.getElementById('chores-container').dataset.childSection = pwaChildTaskSection;
    const title = stage === 'sprout' ? 'My things' : 'Your tasks';
    const html = `<header class="child-page-heading"><h1>${title}</h1><p>${stage === 'sprout' ? 'Little jobs. Things you love.' : 'One thing at a time.'}</p></header><div class="child-section-tabs" aria-label="Task sections">${tabs.map(([id,label])=>`<button aria-pressed="${id === pwaChildTaskSection}" onclick="pwaChildSelectTasks('${id}')">${label}</button>`).join('')}</div>${stage === 'sprout' ? `<div class="child-shortcuts"><button onclick="setView('more')">${pwaIcon('critter')}<span>Critter, music & more</span></button><button onclick="setView('myday')">${pwaIcon('drives')}<span>My routine</span></button></div>` : ''}`;
    const host = document.getElementById('house-anchors');
    if (host.innerHTML !== html) host.innerHTML = html;
}
function pwaChildSelectTasks(section) {
    pwaChildTaskSection = section; pwaChildHouseTabs();
    document.querySelector('.child-section-tabs [aria-pressed="true"]')?.focus({preventScroll:true});
}

// The day rows are the source for both the brief and the next-thing hero.
const PWA_DAY_KIND_ORDER = ['drive', 'ride', 'event', 'session', 'routine', 'task'];

function pwaLocalIso(value) {
    if (!value) return '';
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return '';
    const pad = n => String(n).padStart(2, '0');
    return `${pwaLocalDay(date)}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function pwaBriefTime(value, opts = {}) {
    return pwaClockSuffix(value, opts);
}

function pwaNextThing(rows, now) {
    const clock = new Date(now).getTime();
    const candidates = (rows || []).filter(row => {
        const start = new Date(row.start).getTime();
        const end = new Date(row.end).getTime();
        return !row.allDay && Number.isFinite(start) && Number.isFinite(end) && end >= clock
            && !['completed', 'done', 'past'].includes(row.state);
    });
    candidates.sort((a, b) => {
        const underwayA = new Date(a.start).getTime() <= clock;
        const underwayB = new Date(b.start).getTime() <= clock;
        return Number(underwayB) - Number(underwayA)
            || new Date(a.start) - new Date(b.start)
            || PWA_DAY_KIND_ORDER.indexOf(a.kind) - PWA_DAY_KIND_ORDER.indexOf(b.kind);
    });
    return candidates[0] || null;
}

function pwaRowsFromDom(container) {
    if (!container) return [];
    return Array.from(container.querySelectorAll('[data-kind]')).filter(element => PWA_DAY_KIND_ORDER.includes(element.dataset.kind)).map(element => {
        const d = element.dataset;
        return {kind:d.kind, start:d.start, end:d.end, title:d.title || '', place:d.place || '',
            meta:d.meta || '', state:d.state || '', primary:d.primary || '', secondary:d.secondary || '',
            legId:d.legId || '', eventId:d.eventId || '', late:Number(d.late) || 0, allDay:d.allDay === '1' || d.allDay === 'true'};
    });
}

function pwaHeroNext(row, now, opts = {}) {
    if (!row) return null;
    const drive = row.kind === 'drive';
    const duration = /\b(?:(\d+)\s*h(?:ours?)?\s*)?(?:(\d+(?:\.\d+)?)\s*m(?:in(?:s|utes)?)?\s*)?drive\b/i.exec(row.meta || '');
    const labels = {ride:'Details', event:'Details', session:'Open the session', routine:'Done', task:'Open'};
    const start = new Date(row.start), end = new Date(row.end), clock = new Date(now);
    return {start:row.start, end:row.end, title:row.title, location:row.place, kind:row.kind,
        leave_at:drive ? row.start : null, leave_label:drive ? `Leave at ${pwaBriefTime(row.start, opts)}` : null,
        travel_mins:drive && duration && (duration[1] || duration[2]) ? Number(duration[1] || 0) * 60 + Number(duration[2] || 0) : null, driver:row.driver || null,
        live:start <= clock && clock <= end, minutes_until:Math.max(0, Math.ceil((start - clock) / 60000)),
        actions:drive ? [{label:'Start drive', run:row.primary}, {label:'Ask for cover', run:row.secondary}]
            : row.primary ? [{label:row.kind === 'ride' && /^openEventThread\(/.test(row.primary) ? 'Discuss' : labels[row.kind] || 'Open', run:row.primary}] : []};
}

function pwaGreeting(hour, name) {
    return {word:hour >= 5 && hour < 12 ? 'Good morning' : hour >= 12 && hour < 17 ? 'Good afternoon' : 'Good evening',
        first:String(name || '').trim().split(/\s+/)[0] || 'there'};
}

function pwaBriefFacts({rows = [], needs = []}, opts = {}) {
    const drives = rows.filter(row => row.kind === 'drive').sort((a, b) => new Date(a.start) - new Date(b.start));
    const byEnd = rows.filter(row => Number.isFinite(new Date(row.end).getTime()))
        .sort((a, b) => new Date(b.end) - new Date(a.end));
    const unusual = [];
    for (const card of needs) {
        let text = '';
        if (card.kind === 'needs_driver') {
            const title = card.title.replace(/ needs a driver$/, '');
            const day = card.deadline ? new Date(card.deadline).toLocaleDateString('en-US', {weekday:'long'}) : '';
            text = `${title}${day ? ' ' + day : ''} still needs a driver.`;
        } else if (card.kind === 'status') {
            const split = card.title.indexOf(': ');
            text = split < 0 ? `${card.title} today.`
                : `${card.title.slice(split + 2)} for ${card.title.slice(0, split)} today.`;
        } else if (card.kind === 'review') {
            text = card.id?.startsWith('review:pool:') ? `${card.title} and ready to grant.`
                : card.id?.startsWith('review:redemption:') ? `${card.title}, waiting on your yes.`
                : `${card.title} and is waiting on your OK.`;
        } else if (card.kind === 'request') {
            text = `${card.title.split(' asks:')[0]} asked you for something.`;
        } else if (card.kind === 'proposal') {
            text = `${card.title} ${/^(1|One) proposed event$/.test(card.title) ? 'is' : 'are'} waiting.`;
        } else if (card.kind === 'household_task') {
            text = `${card.title} is ${card.why === 'overdue' ? 'overdue' : 'due today'}.`;
        }
        if (text) unusual.push({kind:card.kind, text, rank:card.rank});
    }
    for (const row of drives) {
        if (Number(row.late) > 0) unusual.push({kind:'late',
            text:`You're running ${Number(row.late)} min late to ${row.title}.`, rank:1});
    }
    return {drives:drives.length, rides:rows.filter(row => row.kind === 'ride').length,
        sessions:rows.filter(row => row.kind === 'session').length, firstDrive:drives[0] || null,
        lastEnd:byEnd[0] || null, unusual};
}

function pwaBriefNumber(count) {
    return pwaNumberWord(count);
}

function pwaBriefSentence(facts, opts = {}) {
    let sentence = 'Nothing on the road today';
    if (facts.drives) {
        sentence = `${pwaBriefNumber(facts.drives)} ${facts.drives === 1 ? 'drive' : 'drives'} today`;
        if (facts.rides) sentence += ` and ${pwaBriefNumber(facts.rides)} ${facts.rides === 1 ? 'ride' : 'rides'}`;
        sentence = sentence[0].toUpperCase() + sentence.slice(1);
    } else if (facts.rides) {
        sentence = `${pwaBriefNumber(facts.rides)} ${facts.rides === 1 ? 'ride' : 'rides'} today`;
        sentence = sentence[0].toUpperCase() + sentence.slice(1);
    }
    sentence += '.';
    const top = (facts.unusual || []).filter(item => item.text).slice().sort((a, b) => a.rank - b.rank)[0];
    if (top) sentence += ' ' + top.text.trim().replace(/[.!?]+$/, '') + '.';
    return sentence;
}

function pwaNeedDate(value) {
    if (value == null || value === '') return null;
    const date = new Date(typeof value === 'number' && Math.abs(value) < 1e12 ? value * 1000
        : /^\d{4}-\d{2}-\d{2}$/.test(String(value)) ? value + 'T23:59:00' : value);
    return Number.isFinite(date.getTime()) ? date : null;
}

const PWA_NEED_ICONS = {finding:'🔎', insight:'💡', thread:'🧵', mission:'🎯', project:'📋', program:'🎯'};

function pwaNeedsYou(inputs, now, opts = {}) {
    const cards = [], clock = new Date(now);
    const list = value => Array.isArray(value) ? value : [];
    const add = (id, kind, icon, title, why, deadline, rank, open) =>
        cards.push({id, kind, icon, title, why, deadline:pwaNeedDate(deadline), rank, open});
    for (const request of list(inputs.requests)) {
        const body = String(request.body || '');
        add(`request:${request.id}`, 'request', '🙋', `${request.from_name} asks: ${body.slice(0, 60)}${body.length > 60 ? '…' : ''}`,
            'waiting on your answer', null, 2, {fn:'pwaOpenNeedRequests'});
    }
    if (inputs.role === 'parent' && inputs.canReview) {
        const reviews = inputs.reviews || {};
        for (const chore of list(reviews.chores)) {
            if (chore.state !== 'done') continue;
            add(`review:chore:${chore.id}`, 'review', '🧹', `${chore.claimed_by_name} finished ${chore.title}`,
                `${chore.points} points waiting on your yes`, null, 3, {screen:'chores', segment:'check', view:'chores', section:'reviews'});
        }
        for (const redemption of list(reviews.redemptions)) {
            if (redemption.state && redemption.state !== 'pending') continue;
            add(`review:redemption:${redemption.id}`, 'review', '🎁', `${redemption.member_name} wants ${redemption.reward_title}`,
                `${redemption.cost} points`, null, 3, {screen:'rewards', view:'chores', section:'reviews'});
        }
        for (const pool of list(reviews.pools)) {
            if (!pool.funded) continue;
            add(`review:pool:${pool.id}`, 'review', '🎁', `${pool.title} is funded`, 'ready to grant', null, 3,
                {screen:'rewards', view:'chores', section:'reviews'});
        }
    }
    if (inputs.canAssign) {
        const horizon = new Date(clock);
        horizon.setDate(horizon.getDate() + 7);
        const seen = new Set();
        for (const event of list(inputs.unassigned).slice().sort((a, b) => new Date(a.start) - new Date(b.start))) {
            const start = pwaNeedDate(event.start);
            if (!start || start < clock || start > horizon || event.canceled || event.cancelled
                || ['canceled', 'cancelled'].includes(event.status)) continue;
            const base = String(event.id).replace(/_(dropoff|pickup)$/, '');
            if (seen.has(base)) continue;
            seen.add(base);
            const key = event.key || encodeURIComponent(JSON.stringify({...event, timeStr:pwaBriefTime(event.start, opts)}));
            const reason = event.isConflict ? event.conflictReason || 'every driver is blocked' : 'nobody yet';
            add(`needs_driver:${event.id}`, 'needs_driver', '🚗', `${event.title} needs a driver`,
                `${start.toLocaleDateString('en-US', {weekday:'long'})} ${pwaBriefTime(start, opts)} · ${reason}`, start, 1,
                {fn:'openEventModal', args:[key]});
        }
    }
    const seenTasks = new Set();
    for (const task of list(inputs.householdTasks)) {
        if (!task.past_due && !task.due_today) continue;
        add(`household_task:${task.id}`, 'household_task', '☑️', task.title, task.past_due ? 'overdue' : 'due today',
            task.due_date ? task.due_date + 'T00:00:00' : null, 2, {screen:'tasks'});
    }
    for (const [tasks, overdue] of [[list(inputs.dueSoon), false], [list(inputs.stillOpen), true]]) {
        for (const task of tasks) {
            if (seenTasks.has(task.id)) continue;
            seenTasks.add(task.id);
            add(`task:${task.id}`, 'task', '📚', task.title, overdue || task.overdue ? 'overdue' : `due ${task.label}`,
                task.due_date, 4, {fn:'openKidTaskDetail', args:[task.id]});
        }
    }
    const proposals = list(inputs.proposals);
    if (inputs.role === 'parent' && proposals.length) {
        const starts = proposals.map(p => pwaNeedDate(p.start)).filter(Boolean).sort((a, b) => a - b);
        const source = proposals[0].source_from || proposals[0].source_subject;
        add('proposal:all', 'proposal', '📥', `${proposals.length} proposed ${proposals.length === 1 ? 'event' : 'events'}`, source ? `from ${source}` : '',
            starts[0], 3, {view:'family', anchor:'proposals-container'});
    }
    for (const situation of list(inputs.situations)) {
        if (situation.group !== 'now') continue;
        add(`situation:${situation.kind}:${situation.id}`, 'situation', situation.icon || PWA_NEED_ICONS[situation.kind] || '✨',
            situation.title, situation.next_move || '', situation.due_at, 2, {view:'family', anchor:'mind-container'});
    }
    for (const thread of list(inputs.threads)) {
        if (thread.group !== 'now') continue;
        add(`thread:${thread.id}`, 'thread', '🧵', thread.title, thread.next_move || '', thread.due_at, 2,
            {view:'family', anchor:'house-threads'});
    }
    for (const status of list(inputs.statusDays)) {
        add(`status:${status.id}`, 'status', status.emoji || '💙', [status.person_name || status.member_name, status.status_name].filter(Boolean).join(': '),
            status.line || status.adult_message || status.need_label || 'tap to change', null, 1, {fn:'pwaOpenStatusSheet'});
    }
    return cards.sort((a, b) => {
        if (a.deadline && b.deadline) return a.deadline - b.deadline || a.rank - b.rank || a.title.localeCompare(b.title);
        return Number(!!b.deadline) - Number(!!a.deadline) || a.rank - b.rank || a.title.localeCompare(b.title);
    });
}

function pwaConflictOf(diagnosticsForEvent) {
    const reasons = Object.values(diagnosticsForEvent || {});
    if (!reasons.length || !reasons.every(r => r && r.type !== 'optimization')) return null;
    const texts = [...new Set(reasons.map(r => r.text).filter(Boolean))];
    return {conflictReason:texts.length === 1 ? texts[0] : null};
}

function pwaNeedsYouInputs() {
    const list = value => Array.isArray(value) ? value : [];
    const role = typeof currentMemberRole === 'function' ? currentMemberRole() : '';
    const memberDay = typeof window !== 'undefined' && window.pwaMemberDay || {};
    const schedule = typeof scheduleData !== 'undefined' && scheduleData || {};
    const requests = typeof myRequests !== 'undefined' && myRequests || {};
    const chores = list(typeof choresData !== 'undefined' ? choresData : null);
    const redemptions = list(typeof redemptionsData !== 'undefined' ? redemptionsData : null);
    const rewards = list(typeof rewardsData !== 'undefined' ? rewardsData : null);
    const situations = list(typeof mindSituations !== 'undefined' ? mindSituations : null);
    const threads = list(typeof houseThreads !== 'undefined' ? houseThreads : null);
    const unassigned = list(schedule.true_unassigned || schedule.unassigned).map(event =>
        typeof event === 'object' ? event : list(schedule.events).find(e => e.id === event)).filter(Boolean);
    const conflicts = new Map();
    for (const event of unassigned) {
        const base = String(event.id).replace(/_(dropoff|pickup)$/, '');
        const leg = pwaConflictOf((schedule.diagnostics || {})[event.id]);
        const previous = conflicts.get(base);
        const isConflict = previous ? previous.isConflict && !!leg : !!leg;
        conflicts.set(base, {isConflict,
            conflictReason:isConflict ? previous?.conflictReason || leg?.conflictReason || null : null});
    }
    return {role, requests:list(requests.waiting_on_me).map(r => ({...r, from_name:r.from_name || r.from})),
        reviews:{chores:chores.filter(c => c.state === 'done'),
            redemptions:redemptions.filter(r => !r.state || r.state === 'pending'),
            pools:rewards.filter(r => r.pooled && r.pool && r.pool.funded).map(r => ({...r, funded:r.pool.funded}))},
        dueSoon:list(memberDay.due_soon), stillOpen:list(memberDay.still_open), statusDays:list(memberDay.status_days).map(s => ({...s,
            person_name:s.person_name || s.member_name, status_name:s.status_name || s.name,
            line:s.line || s.adult_message || s.need_label || 'tap to change'})),
        proposals:list(typeof proposalsData !== 'undefined' ? proposalsData : null),
        householdTasks:list(typeof householdTasksAllowed === 'function' && householdTasksAllowed()
            && typeof householdTasksData !== 'undefined' ? householdTasksData : null)
            .filter(t => t.past_due || t.due_today),
        threads:threads.filter(s => s.kind === 'thread' && s.group === 'now').map(s => ({...s,
            next_move:s.next_move || (s.next_step && (s.next_step.title || s.next_step.label)) || s.status_note || '',
            due_at:s.due_at == null ? s.due : s.due_at})),
        situations:situations.filter(s => s.group === 'now').map(s => ({...s,
            next_move:s.next_move || (s.next_step && (s.next_step.title || s.next_step.label)) || s.status_note || '',
            due_at:s.due_at == null ? s.due : s.due_at})),
        unassigned:unassigned.map(event => ({...event, ...conflicts.get(String(event.id).replace(/_(dropoff|pickup)$/, ''))})),
        canReview:role === 'parent' && typeof pwaAllowed === 'function' && pwaAllowed('chores')
            && !(typeof houseRevealListsOnly !== 'undefined' && houseRevealListsOnly),
        canAssign:role === 'parent' || role === 'adult'};
}

function pwaOpenNeed(card) {
    const open = card && card.open;
    if (!open) return;
    if (open.anchor && typeof pwaPlanSuppressAutoScroll === 'function') pwaPlanSuppressAutoScroll();
    if (open.screen) {
        const opened = typeof window !== 'undefined' && typeof window.pwaOpenHouseScreen === 'function'
            && window.pwaOpenHouseScreen(open.screen, open.segment);
        if (!opened && typeof setView === 'function') setView('chores');
        return; // screen is canonical; view/section remain for older consumers.
    }
    if (open.view && typeof setView === 'function') {
        setView(open.view);
        if (open.section && typeof pwaSelectHouse === 'function') pwaSelectHouse(open.section);
        if (open.anchor && typeof document !== 'undefined') document.getElementById(open.anchor)?.scrollIntoView();
    }
    if (open.fn && typeof window !== 'undefined' && typeof window[open.fn] === 'function') window[open.fn](...(open.args || []));
}

// The passenger and child renderers share this assembly; the brief also
// merges these ride nodes with the scheduler's driver rows.
function myDayTimelineHtml(data, programItems) {
    const rideMin = r => { const d = new Date(r.start);
        return isNaN(d) ? 0 : d.getHours() * 60 + d.getMinutes(); };
    return (data.rides || []).map(r => ({min:rideMin(r), html:renderMyDayCard(r)}))
        .concat(programItems.timed).sort((a, b) => a.min - b.min).map(x => x.html).join('');
}

let pwaWeather = null, pwaWeatherAt = 0, pwaWeatherLoad = null;
let pwaBriefRequest = 0, pwaBriefBuilding = false, pwaBriefLoadingDate = '';
let pwaBriefScheduleLoad = null;
let pwaBriefCache = null, pwaBriefLoadingMember = '';

async function pwaBriefWeather() {
    if (pwaWeatherAt && Date.now() - pwaWeatherAt < 600000) return pwaWeather;
    if (!pwaWeatherLoad) pwaWeatherLoad = (async () => {
        try {
            const r = await fetch(`${apiBase}api/weather/now`);
            const w = r.ok ? await r.json() : null;
            pwaWeather = w && !['unavailable', 'unknown'].includes(w.condition)
                && (w.temp_now != null || w.condition) ? w : null;
        } catch (e) { pwaWeather = null; }
        pwaWeatherAt = Date.now();
        return pwaWeather;
    })().finally(() => { pwaWeatherLoad = null; });
    return pwaWeatherLoad;
}

function pwaPencilOptions() {
    const options = [];
    if (['parent', 'adult'].includes(currentMemberRole()) && mydayOffset >= 0) options.push('status');
    if (kidCan('can_request')) options.push('ask');
    if (pwaIsAdult() && mydayOffset === 0) options.push('day');
    return options;
}

function pwaBriefDateHeader(dateStr) {
    const date = new Date(dateStr + 'T12:00:00').toLocaleDateString(undefined,
        {weekday:'long', month:'long', day:'numeric'});
    return `<div class="pwa-brief-date"><span>${mfEscape(date)}</span>${pwaPencilOptions().length
        ? '<button type="button" class="pwa-brief-pencil" aria-label="What\'s on my day" onclick="pwaOpenPencil()">✎</button>' : ''}</div>`;
}

function pwaBriefHeader(dateStr) {
    const me = membersData.find(m => m.id === selectedMemberId) || {};
    const greet = pwaGreeting(new Date().getHours(), me.name);
    return `${pwaBriefDateHeader(dateStr)}
        <div class="pwa-brief-hello"><h2 class="pwa-brief-greet">${greet.word.split(' ').map(mfEscape).join('<br>')},<span>${mfEscape(greet.first)}</span></h2><div data-brief-weather></div></div>`;
}

function pwaBriefTimelineBuilt(scrollTop) {
    if (pwaBriefBuilding) return;
    const date = currentDates[activeDateIndex];
    if (!date || (pwaBriefLoadingDate && pwaBriefLoadingMember === selectedMemberId
        && pwaBriefLoadingDate !== date)) return;
    mydayOffset = Math.round((new Date(date + 'T12:00:00') - new Date(todayStr() + 'T12:00:00')) / 86400000);
    updateMyDayLabel();
    if (pwaBriefCache?.member === selectedMemberId && pwaBriefCache.dateStr === date
        && document.querySelector('#myday-content .pwa-brief-schedule')) {
        pwaPaintBrief(pwaBriefCache, false, scrollTop, true);
        return;
    }
    if (!pwaBriefLoadingDate) void pwaRenderBrief();
}

async function pwaBriefSelectDate(dateStr) {
    if (!dateStr) return;
    mydayOffset = Math.round((new Date(dateStr + 'T12:00:00') - new Date(todayStr() + 'T12:00:00')) / 86400000);
    let index = currentDates.indexOf(dateStr);
    if (index < 0 && currentDates.length && (selectedDriverId || isKeepingUpAdult())) {
        // Extend at the same edges as the drives pane. Paging a brief must
        // never replace Plan's anchor with the newly selected date.
        pwaBriefBuilding = true;
        try {
            while (!currentDates.includes(dateStr)) {
                const count = currentDates.length;
                await fetchMoreDays(dateStr < currentDates[0] ? 'prev' : 'next');
                if (currentDates.length === count) break;
            }
        } finally { pwaBriefBuilding = false; }
        index = currentDates.indexOf(dateStr);
    }
    if (index >= 0) return pwaSelectDay(index);
    updateMyDayLabel();
    return pwaRenderBrief();
}

async function pwaRenderBrief(force = false) {
    if (currentView !== 'myday' || !pwaIsAdult()) return;
    const wrap = document.getElementById('myday-content');
    if (!wrap || !selectedMemberId) return;
    const member = selectedMemberId, offset = mydayOffset, dateStr = _mydayLocalDate(offset);
    updateMyDayLabel();
    if (pwaBriefCache?.member === member) {
        const dateHeader = wrap.querySelector('.pwa-brief-date');
        if (dateHeader) dateHeader.outerHTML = pwaBriefDateHeader(dateStr);
    }
    if (pwaBriefCache?.member === member && pwaBriefCache.dateStr === dateStr
        && wrap.querySelector('.pwa-brief-schedule')) {
        // Repair an adopted pane removed by Plan before the quiet reads start.
        pwaPaintBrief(pwaBriefCache);
        if (!force) return;
    }
    if (!force && pwaBriefLoadingDate === dateStr && pwaBriefLoadingMember === member) return;
    const request = ++pwaBriefRequest;
    pwaBriefLoadingDate = dateStr;
    pwaBriefLoadingMember = member;
    const current = () => request === pwaBriefRequest && member === selectedMemberId
        && offset === mydayOffset && currentView === 'myday' && pwaIsAdult();
    // Refresh in the background while this member's existing brief stays
    // usable. A new identity must never inherit the previous member's day.
    if (pwaBriefCache?.member !== member || !wrap.querySelector('.pwa-brief-schedule')) {
        wrap.innerHTML = `<div class="pwa-brief">${pwaBriefHeader(dateStr)}<p class="pwa-brief-loading" role="status">Loading your day…</p></div>`;
        window.pwaNeedCards = [];
    }
    try {
        const read = async url => {
            const r = await fetch(url);
            if (!r.ok) throw new Error('Could not load your day.');
            return r.json();
        };
        const day = read(`${apiBase}api/members/${member}/day?date=${dateStr}`);
        const routines = read(`${apiBase}api/routines/day?member_id=${member}&date=${dateStr}`);
        // Observe the day promise immediately, even if a secondary builder
        // fails first. All reads settle before the hero or pile can paint.
        const parts = offset === 0 ? buildPracticeParts({brief:true, day}) : buildDatedPracticeParts(dateStr);
        if (!scheduleData && !pwaBriefScheduleLoad) pwaBriefScheduleLoad = fetchSchedule()
            .finally(() => { pwaBriefScheduleLoad = null; });
        const results = await Promise.allSettled([day, routines, parts, pwaBriefWeather(),
            fetchRequests(), fetchChores(), fetchProposals({summaryOnly:true}), fetchMind(), pwaBriefScheduleLoad,
            selectedDriverId && offset === 0 ? read(`${apiBase}api/errands`) : [],
            householdTasksAllowed() ? fetchHouseholdTasks() : null, fetchHouseThreads()]);
        if (!current()) return;
        if (results[0].status !== 'fulfilled') throw new Error('Could not load your day.');
        const data = results[0].value || {};
        window.pwaMemberDay = data;
        const routineData = results[1].status === 'fulfilled' ? results[1].value : null;
        const programParts = results[2].status === 'fulfilled' ? results[2].value : {list:[], commitmentsById:{}};
        if (offset !== 0) datedTimelineDays.set(`${member}:${dateStr}`, {...programParts,
            status:renderStatusBanner(data.status_days, dateStr), builtAt:Date.now()});
        // Rebuild the original panes for the selected date before moving any
        // nodes. The dated wrapper and rail IDs travel with the active list.
        const scrollTop = document.getElementById('myday-container').scrollTop;
        pwaBriefBuilding = true;
        try {
            if (currentDates.includes(dateStr)) activeDateIndex = currentDates.indexOf(dateStr);
            timelineInitialized = true;
            buildTimeline();
        } finally { pwaBriefBuilding = false; }
        if (!current()) return;
        updateMyDayLabel();
        pwaBriefCache = {member, dateStr, data, routineData, programParts,
            weather:results[3].status === 'fulfilled' ? results[3].value : null,
            errands:results[9].status === 'fulfilled' ? (results[9].value || []).filter(e => !e.is_completed && e.unplaced) : []};
        pwaPaintBrief(pwaBriefCache, true, scrollTop, true);
        if (mydaySlideDir && !matchMedia('(prefers-reduced-motion: reduce)').matches)
            wrap.animate([{transform:`translateX(${mydaySlideDir * 24}px)`, opacity:.2}, {transform:'translateX(0)', opacity:1}], {duration:180, easing:'ease-out'});
        mydaySlideDir = 0;
    } catch (e) {
        if (current()) {
            const message = '<div class="pwa-brief-error" role="status">Could not load your day. <button type="button" onclick="pwaRenderBrief(true)">Try again</button></div>';
            wrap.querySelector('.pwa-brief-error')?.remove();
            const loading = wrap.querySelector('.pwa-brief-loading');
            if (loading) loading.outerHTML = message;
            else wrap.querySelector('.pwa-brief').insertAdjacentHTML('beforeend', message);
        }
    } finally {
        if (request === pwaBriefRequest) { pwaBriefLoadingDate = ''; pwaBriefLoadingMember = ''; }
    }
}

// A schedule rebuild already has fresh scheduler rows. Adopt those rows and
// repaint the clock-dependent summary from the last payloads, without reads
// or a loading screen. Paired buildTimeline/renderMyDay callers share this path.
function pwaPaintBrief(cache, full = false, savedScrollTop, timelineBuilt = false) {
    if (currentView !== 'myday' || !pwaIsAdult()) return;
    const {data, routineData, programParts, dateStr, weather} = cache;
    const wrap = document.getElementById('myday-content');
    const scroller = document.getElementById('myday-container');
    const scrollTop = savedScrollTop ?? scroller.scrollTop;
    const brief = full ? document.createElement('div') : wrap.querySelector('.pwa-brief');
    if (full) {
        brief.className = 'pwa-brief';
        brief.innerHTML = pwaBriefHeader(dateStr);
    }
    window.pwaMemberDay = data;
    const index = currentDates.indexOf(dateStr);
    const pane = index >= 0 ? document.getElementById(`pane-${index}`) : null;
    // An off-tab rebuild removes the adopted pane and may replace it with
    // Plan's family rows. Rebuild in My Day's mode before adopting again;
    // callers that just built the timeline already have the right rows.
    if (!timelineBuilt && (selectedDriverId || isKeepingUpAdult())
        && (activeDateIndex !== index || pane?.dataset.pwaBriefPane !== dateStr || !brief.contains(pane))) {
        pwaBriefBuilding = true;
        try {
            if (index >= 0) activeDateIndex = index;
            timelineInitialized = true;
            buildTimeline();
        } finally { pwaBriefBuilding = false; }
        updateMyDayLabel();
    }
    const section = pwaBriefDaySection(data, routineData, myDayProgramItems(programParts, dateStr), dateStr);
    const previous = brief.querySelector('.pwa-brief-schedule');
    if (previous) previous.replaceWith(section);
    else brief.append(section);
    const clockOpts = {use24h:typeof use24h !== 'undefined' && use24h};
    window.pwaNeedCards = pwaNeedsYou(pwaNeedsYouInputs(), new Date(), clockOpts);
    brief.querySelector('.pwa-brief-needs')?.remove();
    const rows = pwaRowsFromDom(section.querySelector('.pwa-brief-day'));
    const sentence = brief.querySelector('.pwa-brief-sentence') || document.createElement('p');
    sentence.className = 'pwa-brief-sentence';
    sentence.textContent = pwaBriefSentence(pwaBriefFacts({rows, needs:window.pwaNeedCards,
        role:currentMemberRole(), isDriver:!!selectedDriverId}, clockOpts), clockOpts);
    brief.querySelector('.pwa-brief-loading')?.remove();
    if (full && weather) brief.querySelector('[data-brief-weather]').outerHTML = `<div class="pwa-brief-weather">
        <div class="pwa-weather-icon">${mfEscape(weather.emoji || '')}</div>
        ${weather.temp_now == null ? '' : `<div class="pwa-weather-temp">${mfEscape(String(Math.round(weather.temp_now)))}°</div>`}
        <div class="pwa-weather-line">${mfEscape(weather.line || weather.condition || '')}</div></div>`;
    if (dateStr === todayStr()) brief.insertBefore(sentence, brief.querySelector('.pwa-brief-needs') || section);
    else sentence.remove();
    brief.querySelector('.pwa-hero')?.remove();
    const heroRows = isKeepingUpAdult() ? rows.filter(row => ['ride', 'session', 'routine', 'task'].includes(row.kind)) : rows;
    const clock = new Date(), row = mydayOffset === 0 ? pwaNextThing(heroRows, clock) : null;
    if (row) {
        const next = pwaHeroNext(row, clock, clockOpts);
        if (row.kind === 'drive' && row.state === 'active') next.live = true;
        next.meta = row.meta;
        if (data.launch && row.kind === 'ride' && row.eventId === String((data.rides || [])[0]?.id))
            next.meta = [next.meta, `Leave by ${formatTime(data.launch.leave_at)}${data.launch.driver ? ' with ' + data.launch.driver.name : ''}`].filter(Boolean).join(' · ');
        const original = Array.from(section.querySelectorAll('.pwa-leg-row')).find(el => el.dataset.legId === row.legId);
        if (row.kind === 'drive' && original) next.leave_label = original.dataset.timeLabel;
        sentence.insertAdjacentHTML('afterend', HeroCard.html(next, {phone:true, now:clock}));
    }
    if (window.pwaNeedCards.length) {
        section.insertAdjacentHTML('beforebegin', `<section class="pwa-brief-needs"><h3>Needs you <span class="pwa-count">${window.pwaNeedCards.length}</span></h3>
            ${window.pwaNeedCards.map((card, i) => `<button type="button" class="pwa-need" onclick="pwaOpenNeed(window.pwaNeedCards[${i}])">
                <span class="pwa-need-icon">${mfEscape(card.icon)}</span><span class="pwa-need-copy"><span class="pwa-need-title">${mfEscape(card.title)}</span>
                <span class="pwa-need-why">${mfEscape(card.why)}</span></span><span class="pwa-need-chevron" aria-hidden="true">›</span></button>`).join('')}
            ${kidCan('can_request') ? '<button type="button" class="pwa-brief-ask" onclick="askForSomething()">🙋 Ask for something…</button>' : ''}</section>`);
    }
    if (full) wrap.replaceChildren(brief);
    pwaRefreshBriefSheet();
    scroller.scrollTop = scrollTop;
}

function pwaBriefDaySection(data, routineData, programItems, dateStr) {
    const section = document.createElement('section'); section.className = 'pwa-brief-schedule';
    const index = currentDates.indexOf(dateStr);
    const pane = (index >= 0 && document.getElementById(`pane-${index}`)) || document.createElement('div');
    const fromTimeline = !!selectedDriverId || isKeepingUpAdult();
    const railId = isKeepingUpAdult() ? 'pane-events' : 'pane-drives';
    const rail = document.createElement('div'); rail.id = railId; rail.className = 'pwa-brief-day';
    const items = fromTimeline ? Array.from(pane.querySelectorAll('.pwa-agenda-row, .pwa-program-row, [data-kind="session"]'))
        .filter(el => {
            if (el.parentElement.closest('.pwa-program-row')) return false;
            const row = el.dataset.kind ? el : el.querySelector('[data-kind]');
            return row?.dataset.kind !== 'session' || !!row.dataset.start;
        }) : [];
    // Sessions can be bare rows on an otherwise empty driver day. Untimed
    // programs stay after the chronology with their original disclosure.
    const holder = document.createElement('div');
    const familyPrograms = isKeepingUpAdult() ? {timed:programItems.timed.filter(item => {
        const temp = document.createElement('div'); temp.innerHTML = item.html;
        const id = temp.firstElementChild?.dataset.mydayProgram;
        return !items.some(el => el.dataset.programId === id || el.dataset.mydayProgram === id);
    }), rest:''} : {timed:[], rest:''};
    holder.innerHTML = myDayTimelineHtml(data, fromTimeline ? familyPrograms : programItems);
    if (data.launch && mydayOffset === 0) {
        const ride = Array.from(holder.children).find(el => el.dataset.eventId === String((data.rides || [])[0]?.id));
        if (ride) ride.insertAdjacentHTML('beforeend', `<p class="pwa-row-meta">Leave by ${mfEscape(formatTime(data.launch.leave_at))}${data.launch.driver ? ' with ' + mfEscape(data.launch.driver.name) : ''}</p>`);
    }
    items.push(...holder.children);
    const routines = document.createElement('div'); routines.innerHTML = renderRoutineSection(routineData, mydayOffset);
    items.push(...routines.querySelectorAll('[data-kind="routine"]'));
    const start = el => new Date((el.dataset.kind ? el : el.querySelector('[data-kind]'))?.dataset.start).getTime();
    items.sort((a, b) => (Number.isFinite(start(a)) ? start(a) : Infinity) - (Number.isFinite(start(b)) ? start(b) : Infinity));
    rail.append(...items);
    const due = document.createElement('div'); due.className = 'pwa-brief-due';
    due.innerHTML = renderDueSoonSection(data.due_soon, data.still_open);
    rail.append(...due.children);
    if (routines.firstElementChild?.firstElementChild) {
        const summary = routines.firstElementChild.firstElementChild;
        summary.classList.add('pwa-brief-routine-summary'); rail.append(summary);
    }
    const rest = document.createElement('div'); rest.innerHTML = programItems.rest;
    rail.append(...rest.children);
    const rows = pwaRowsFromDom(rail), timed = rows.filter(r => r.start && r.kind !== 'task');
    const starts = timed.map(r => new Date(r.start).getTime()).filter(Number.isFinite);
    const ends = timed.map(r => new Date(r.end).getTime()).filter(Number.isFinite);
    const heading = document.createElement('h3');
    heading.textContent = `Your day${rows.length ? ` · ${rows.length} ${rows.length === 1 ? 'thing' : 'things'}` : ''}${starts.length && ends.length
        ? ` · ${formatTime(new Date(Math.min(...starts)).toISOString())} – ${formatTime(new Date(Math.max(...ends)).toISOString())}` : ''}`;
    section.append(heading);
    pane.replaceChildren(); pane.className = 'pwa-brief-pane'; pane.dataset.pwaBriefPane = dateStr;
    // Dated status controls remain in their dated wrapper, as on Plan.
    if (dateStr !== todayStr()) pane.insertAdjacentHTML('beforeend', renderStatusBanner(data.status_days, dateStr));
    pane.append(rail); section.append(pane);
    if (!rows.length) rail.textContent = 'Nothing scheduled';
    if (rows.length) {
        rail.classList.add('pwa-brief-fade');
        rail.classList.toggle('is-collapsed', mydayOffset === 0 && localStorage.getItem('chauffeur_myday_day_open') !== '1');
        const toggle = document.createElement('button'); toggle.type = 'button'; toggle.className = 'pwa-brief-expand';
        toggle.textContent = rail.classList.contains('is-collapsed') ? 'Show the whole day ⌄' : 'Show less ⌃';
        toggle.onclick = pwaToggleDay; section.append(toggle);
    }
    if ((Array.isArray(myRequests?.mine) ? myRequests.mine : []).length) section.insertAdjacentHTML('beforeend', '<button type="button" class="pwa-brief-ask" onclick="pwaOpenNeedRequests()">Requests and replies</button>');
    if (selectedDriverId && mydayOffset === 0 && pwaBriefCache?.errands.length) section.insertAdjacentHTML('beforeend', '<button type="button" class="pwa-brief-ask" onclick="pwaOpenUnplacedErrands()">Errands not placed</button>');
    return section;
}

function pwaToggleDay() {
    const day = document.querySelector('#myday-content .pwa-brief-day');
    if (!day) return;
    const open = day.classList.contains('is-collapsed');
    day.classList.toggle('is-collapsed', !open);
    localStorage.setItem('chauffeur_myday_day_open', open ? '1' : '0');
    document.querySelector('#myday-content .pwa-brief-expand').textContent = open ? 'Show less ⌃' : 'Show the whole day ⌄';
}

const pwaBriefSheetHtml = new WeakMap();

function pwaBriefSheet(title, body, kind) {
    return _pwaModal(`<h2>${mfEscape(title)}</h2><div data-brief-sheet-body>${body}</div><button type="button" data-close>Close</button>`, (overlay, close) => {
        overlay.dataset.briefSheet = kind;
        pwaBriefSheetHtml.set(overlay, body);
        overlay.querySelector('[data-close]').onclick = close;
        overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
    });
}

function pwaOpenStatusSheet() {
    pwaBriefSheet('Family status', renderStatusBanner((window.pwaMemberDay || {}).status_days, _mydayLocalDate(mydayOffset)), 'status');
}

function pwaOpenNeedRequests() {
    pwaBriefSheet('Requests and replies', renderRequests(), 'requests');
}

function pwaRefreshBriefSheet() {
    document.querySelectorAll('[data-brief-sheet]').forEach(overlay => {
        const kind = overlay.dataset.briefSheet;
        if (kind !== 'status' && kind !== 'requests') return;
        const body = kind === 'status'
            ? renderStatusBanner((window.pwaMemberDay || {}).status_days, _mydayLocalDate(mydayOffset))
            : renderRequests();
        if (kind === 'requests' && !body) { overlay.remove(); return; }
        // Compare builder output, not the DOM a chooser or armed clear edited.
        if (pwaBriefSheetHtml.get(overlay) !== body) {
            overlay.querySelector('[data-brief-sheet-body]').innerHTML = body;
            pwaBriefSheetHtml.set(overlay, body);
        }
    });
}

function pwaOpenPencil() {
    const options = pwaPencilOptions();
    if (!options.length) return;
    const body = options.map(option => option === 'status'
        ? `<div class="pwa-pencil-status"><span>Family status</span>${renderStatusBanner([], _mydayLocalDate(mydayOffset))}</div>`
        : option === 'ask' ? '<button type="button" data-brief-ask>Ask for something</button>'
        : `<label class="pwa-pencil-toggle"><span>Show the whole day by default</span><input type="checkbox" data-brief-default ${localStorage.getItem('chauffeur_myday_day_open') === '1' ? 'checked' : ''}></label>`).join('');
    const sheet = pwaBriefSheet('My Day', body, 'pencil');
    sheet.querySelector('[data-brief-ask]')?.addEventListener('click', () => { sheet.remove(); askForSomething(); });
    sheet.querySelector('[data-brief-default]')?.addEventListener('change', e => {
        localStorage.setItem('chauffeur_myday_day_open', e.target.checked ? '1' : '0');
        void pwaRenderBrief();
    });
}

async function pwaOpenUnplacedErrands() {
    const sheet = pwaBriefSheet('Errands not placed', '<p>Loading…</p>', 'errands');
    await renderUnplacedErrands(pwaBriefCache?.errands);
    const block = document.querySelector('#myday-content #unplaced-errands');
    const body = sheet.querySelector('[data-brief-sheet-body]');
    body.replaceChildren();
    if (block) body.append(block);
    else sheet.remove();
}

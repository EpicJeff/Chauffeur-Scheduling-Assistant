// Household summaries use only the owning modules' fetched rows.
function pwaDayLabel(isoDate, today) {
    const iso = String(isoDate).slice(0, 10);
    const days = (Date.parse(iso + 'T00:00:00Z') - Date.parse(String(today).slice(0, 10) + 'T00:00:00Z')) / 86400000;
    return new Date(iso + 'T12:00:00').toLocaleDateString('en-US', days >= 0 && days <= 6
        ? {weekday:'long'} : {month:'short', day:'numeric'});
}

function pwaHouseholdCards(inputs) {
    const list = value => Array.isArray(value) ? value : [];
    const today = inputs.today;
    const dayNumber = iso => Date.parse(String(iso).slice(0, 10) + 'T00:00:00Z') / 86400000;
    const daysAway = iso => dayNumber(iso) - dayNumber(today);
    const time = iso => pwaClock(iso, {use24h:inputs.use24h});
    const card = (id, icon, title) => ({id, icon, title, line:'', pills:[], faces:[], progress:null, score:0, open:{screen:id},
        lead:{reviews:0, overdueTitle:null, shopDay:null, windowProgram:null, windowTime:null}});
    const pill = (text, tone = 'plain') => ({text, tone});
    const review = inputs.role === 'parent' && inputs.canReview;
    const chores = card('chores', '🧹', 'Chores');
    const choreRows = list(inputs.chores);
    const open = choreRows.filter(c => c.state === 'open');
    const claimed = choreRows.filter(c => c.state === 'claimed');
    const done = choreRows.filter(c => c.state === 'done');
    const claims = new Map();
    for (const c of claimed) {
        const name = c.claimed_by_name || list(inputs.members).find(m => m.id === c.claimed_by)?.name || 'Someone';
        const key = c.claimed_by || name;
        const claim = claims.get(key) || {name, mine:!!c.claimed_by && c.claimed_by === inputs.meId, count:0};
        claim.count++;
        claims.set(key, claim);
    }
    chores.line = [`${open.length} open`, ...Array.from(claims.values(), c => `${c.mine ? 'you have' : c.name + ' has'} ${c.count} claimed`),
        ...(review && done.length ? [`${done.length} done waiting on you`] : [])].join(' · ');
    if (review && done.length) chores.pills.push(pill(`${done.length} to check`, 'hot'));
    chores.pills.push(...choreRows.filter(c => ['open', 'claimed'].includes(c.state)).slice(0, 2)
        .map(c => pill(`${c.title} · ${c.state === 'open' ? 'open' : c.claimed_by_name || 'claimed'}`)));
    chores.faces = [...new Set(claimed.map(c => c.claimed_by).filter(Boolean))];
    chores.score = review ? 3 * done.length + open.length : open.filter(c => {
        const ids = list(c.eligible_member_ids);
        return !ids.length || ids.includes(inputs.meId);
    }).length;
    chores.lead.reviews = review ? done.length : 0;

    const rewardsOn = inputs.rewardsOn !== false;
    const rewards = card('rewards', rewardsOn ? '🎁' : '⭐', rewardsOn ? 'Rewards' : 'Points');
    const pending = review && rewardsOn ? list(inputs.redemptions).filter(r => !r.state || r.state === 'pending') : [];
    const pools = rewardsOn ? list(inputs.rewards) : [];
    const funded = pools.filter(p => p.funded);
    const goal = funded[0] || pools[0];
    if (!rewardsOn) {
        rewards.line = list(inputs.balances).slice(0, 3).map(b => `${b.name} ${b.balance} pts`).join(' · ') || 'No points yet';
    } else if (pending.length) {
        const r = pending[0];
        rewards.line = `${r.member_name} asked for ${r.reward_title} · ${r.cost} pts`;
        rewards.pills.push(pill(`${pending.length} ${pending.length === 1 ? 'request' : 'requests'}`, 'hot'));
    } else if (goal) {
        rewards.line = goal.funded ? `Family goal: ${goal.title} funded` : `${goal.title} ${goal.pct}%`;
    } else rewards.line = 'No rewards yet';
    if (goal) rewards.progress = Math.max(0, Math.min(1, Number(goal.pct || 0) / 100));
    rewards.pills.push(...list(inputs.balances).slice(0, 2).map(b => pill(`${b.name} ${b.balance} pts`)));
    rewards.score = 3 * pending.length + 2 * funded.length;
    rewards.lead.reviews = pending.length;

    const tasks = card('tasks', '☑️', 'Tasks');
    const taskRows = list(inputs.householdTasks).filter(t => t.status !== 'done' && (!t.state || t.state === 'open'))
        .slice().sort((a, b) => String(a.due_date || '9999').localeCompare(String(b.due_date || '9999')));
    const overdue = taskRows.filter(t => t.past_due);
    const dueToday = taskRows.filter(t => !t.past_due && t.due_today);
    const week = taskRows.filter(t => !t.past_due && t.due_date && daysAway(t.due_date) >= 0 && daysAway(t.due_date) <= 6);
    tasks.line = week.length ? `${week.length} due this week` : taskRows.length ? `${taskRows.length} open` : 'Nothing on the list';
    if (overdue.length) {
        tasks.lead.overdueTitle = overdue[0].title;
        tasks.line += ` · ${overdue[0].title} is overdue`;
        tasks.pills.push(pill(`${overdue.length} overdue`, 'hot'));
    }
    const nextTask = taskRows.find(t => !t.past_due && t.due_date);
    if (nextTask) tasks.pills.push(pill(`${nextTask.title} · ${pwaDayLabel(nextTask.due_date, today)}`));
    tasks.score = 3 * overdue.length + 2 * dueToday.length + week.filter(t => !t.due_today).length;

    const lists = card('lists', '🛒', 'Lists');
    const listRows = list(inputs.lists);
    lists.line = listRows.slice(0, 3).map(l => `${l.name} ${l.open_count || 0}`).join(' · ') || 'No lists shared with you yet';
    const nextRun = (inputs.runs || {}).next;
    const runDays = nextRun ? daysAway(nextRun) : NaN;
    lists.lead.shopDay = runDays === 0 ? 'today' : runDays === 1 ? 'tomorrow' : null;
    if (runDays >= 0 && runDays < 7) lists.pills.push(pill(`Shop day ${runDays === 0 ? 'today' : runDays === 1 ? 'tomorrow' : pwaDayLabel(nextRun, today)}`, 'hot'));
    lists.pills.push(pill(`${listRows.length} ${listRows.length === 1 ? 'list' : 'lists'}`));
    lists.score = runDays === 0 || runDays === 1 ? 2 : Number(listRows.some(l => l.open_count > 0));

    const projects = card('projects', '📋', 'Projects & programs');
    const active = list(inputs.projects).filter(p => p.state === 'active').slice()
        .sort((a, b) => Number(b.lane === 'needs_you') - Number(a.lane === 'needs_you'));
    const programs = list(inputs.programs).filter(p => ['active', 'paused'].includes(p.state));
    projects.line = active.map(p => p.title).concat(programs.map(p => p.unit_n != null && p.total_units != null
        ? `${p.title} (lesson ${p.unit_n} of ${p.total_units})` : p.title)).slice(0, 3).join(' · ') || 'Nothing running';
    const windows = programs.map(p => {
        const w = inputs.nextWindowFor?.(p.id);
        return {program:p, start:w && (w.start || (w.date + 'T' + w.time_start))};
    }).filter(p => Number.isFinite(Date.parse(p.start)))
        .sort((a, b) => new Date(a.start) - new Date(b.start));
    if (windows.length) {
        const next = windows[0];
        if (daysAway(next.start) === 0) {
            projects.lead.windowProgram = next.program.title;
            projects.lead.windowTime = time(next.start);
        }
        projects.pills.push(pill(`${next.program.title} · ${pwaDayLabel(next.start, today)} ${time(next.start)}`, 'hot'));
    }
    projects.pills.push(pill(`${active.length + programs.length} running`));
    projects.faces = [...new Set(active.map(p => p.owner_member_id).concat(programs.map(p => p.member_id)).filter(Boolean))];
    projects.score = 3 * active.filter(p => p.lane === 'needs_you').length
        + Number(windows.some(p => daysAway(p.start) === 0));
    return [chores, rewards, tasks, lists, projects]
        .filter(c => !inputs.listsOnly || c.id === 'lists')
        .filter(c => inputs.facets?.[c.id] !== 'none'
            || (c.id === 'lists' && (inputs.listsOnly || listRows.length > 0)))
        .sort((a, b) => b.score - a.score);
}

function pwaHouseholdLead(cards) {
    if (!cards.some(c => c.score > 0)) return 'All quiet in the house.';
    let count = 0, shop = '', overdue = '', program = '';
    for (const c of cards) {
        const lead = c.lead || {};
        count += Number(lead.reviews) || 0;
        if (lead.shopDay) shop = `Shop day is ${lead.shopDay}.`;
        if (lead.overdueTitle) overdue = `${lead.overdueTitle} is overdue.`;
        if (lead.windowProgram && lead.windowTime) program = `${lead.windowProgram} is at ${lead.windowTime}.`;
    }
    const words = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine'];
    const yes = count ? `${words[count] || count} ${count === 1 ? 'thing wants' : 'things want'} your yes.` : '';
    return [yes, shop || overdue || program].filter(Boolean).join(' ') || 'Nothing needs your yes.';
}

// The household reads are separate from My Day's viewer-filtered programs.
let pwaHouseBalances = [], pwaHouseProjects = [], pwaHousePrograms = [], pwaHouseWindows = [];
let pwaHouseRuns = {}, pwaHouseCommitments = {}, pwaHouseActive = null;

function pwaHouseholdInputs() {
    const role = currentMemberRole();
    const ownChores = pwaChoresOwner === selectedMemberId;
    return {role, canReview:role === 'parent', listsOnly:!!houseRevealListsOnly, rewardsOn:chfFeatureOn('rewards'),
        facets:{chores:scopeOf('chores.board'), rewards:scopeOf('rewards'),
            tasks:scopeOf('lists.household_tasks'), lists:scopeOf('lists.shopping'), projects:'all'},
        chores:ownChores ? choresData : [], balances:ownChores ? pwaHouseBalances : [],
        rewards:(ownChores ? rewardsData : []).filter(r => r.pooled && r.pool).map(r => ({id:r.id, title:r.title,
            pct:Math.max(0, Math.min(100, Math.round(100 * r.pool.pledged / (r.pool.cost || 1)))), funded:!!r.pool.funded})),
        redemptions:ownChores ? redemptionsData : [], householdTasks:householdTasksData.filter(t => t.status !== 'done'),
        lists:houseLists, runs:pwaHouseRuns, projects:pwaHouseProjects, programs:pwaHousePrograms,
        nextWindowFor:id => upcomingWindows(id, pwaHouseWindows)[0] || null,
        members:membersData, meId:selectedMemberId, today:todayStr(),
        use24h:typeof use24h !== 'undefined' && use24h};
}

// The directory and record links use the same door the Household draws.
function pwaHouseHasProjects() {
    if (!pwaAllowed('projects') || !pwaAllowed('chores') || houseRevealListsOnly) return false;
    if (currentMemberRole() === 'child')
        return ['explorer', 'navigator', 'copilot'].includes(pwaChildStage());
    return pwaHouseholdCards(pwaHouseholdInputs()).some(c => c.id === 'projects');
}

// Both Household hosts borrow this one island from its original position.
let pwaProjectsAdoption = null;
function pwaRestoreProjectsNode() {
    const adoption = pwaProjectsAdoption;
    if (!adoption) return;
    pwaProjectsAdoption = null;
    const restore = () => adoption.home.replaceWith(adoption.node);
    if (window.Alpine) Alpine.mutateDom(restore); else restore();
    adoption.node.style.display = adoption.display;
}
function pwaAdoptProjectsNode(host) {
    pwaRestoreProjectsNode();
    const node = document.getElementById('projects-container');
    const adoption = {node, home:document.createComment('projects home'), display:node.style.display,
        member:selectedMemberId, audience:pwaChildStage() || currentMemberRole()};
    node.before(adoption.home);
    const move = () => host.append(node);
    if (window.Alpine) Alpine.mutateDom(move); else move();
    node.style.display = 'flex';
    pwaProjectsAdoption = adoption;
    return () => { if (pwaProjectsAdoption === adoption) pwaRestoreProjectsNode(); };
}
function pwaSyncProjectsNode() {
    if (!pwaProjectsAdoption || (pwaProjectsAdoption.member === selectedMemberId
            && pwaProjectsAdoption.audience === (pwaChildStage() || currentMemberRole())
            && currentView === 'chores' && pwaHouseHasProjects())) return;
    if (pwaHouseActive?.id === 'projects') {
        pwaHouseActive.clearing = true;
        PwaNav.clear({restoreFocus:false});
    }
    pwaRestoreProjectsNode();
}

async function pwaReadHousehold(path) {
    try { const r = await fetch(apiBase + path); return r.ok ? await r.json() : null; }
    catch (e) { return null; }
}

async function pwaRefreshHousePrograms() {
    if (houseRevealListsOnly) {
        pwaHousePrograms = []; pwaHouseWindows = []; pwaHouseCommitments = {};
        pwaRenderHousehold();
        return;
    }
    const owner = selectedMemberId;
    const [data, windows, rows] = await Promise.all([
        pwaReadHousehold('api/programs'), fetchPracticeWindows(), fetchMyCommitments()
    ]);
    if (owner !== selectedMemberId) return;
    pwaHousePrograms = (data?.programs || []).filter(p => ['active', 'paused'].includes(p.state));
    pwaHouseWindows = windows;
    pwaHouseCommitments = Object.fromEntries(rows.map(c => [c.id, c]));
    pwaRenderHousehold();
}

async function pwaFetchHousehold() {
    const owner = selectedMemberId;
    const refresh = () => { if (owner === selectedMemberId) pwaRenderHousehold(); };
    const reads = [fetchHouseLists()];
    reads.push(
        pwaReadHousehold('api/shopping/runs').then(d => {
            if (owner !== selectedMemberId) return;
            pwaHouseRuns = d?.runs || {}; refresh();
        }));
    if (!houseRevealListsOnly) reads.push(
        fetchChores(), fetchHouseholdTasks(),
        pwaReadHousehold('api/projects').then(d => {
            if (owner !== selectedMemberId) return;
            pwaHouseProjects = d?.projects || []; refresh();
        }),
        pwaRefreshHousePrograms());
    await Promise.allSettled(reads);
    refresh();
}

function pwaRenderHousehold() {
    if (!pwaIsAdult() || !pwaAllowed('chores') || currentView !== 'chores') return;
    const host = document.getElementById('house-cards');
    if (!host) return;
    // The household may refresh after a tab change; only its own paint owns this store.
    practiceWindows = pwaHouseWindows;
    const cards = pwaHouseholdCards(pwaHouseholdInputs());
    const root = document.getElementById('chores-container');
    root.dataset.house = 'cards';
    if (!pwaHouseActive) root.dataset.section = 'cards';
    document.getElementById('house-anchors').replaceChildren();
    const focusedCard = document.activeElement?.dataset.card;
    const html = `<h1 class="pwa-house-title">Household</h1><p class="pwa-house-lead">${mfEscape(pwaHouseholdLead(cards))}</p>`
        + cards.map(c => `<button type="button" class="pwa-house-card" data-card="${c.id}">
            <span class="pwa-house-icon" aria-hidden="true">${c.icon}</span><span class="pwa-house-copy">
            <span class="pwa-house-t1">${mfEscape(c.title)}<span aria-hidden="true">›</span></span>
            <span class="pwa-house-t2">${mfEscape(c.line)}</span>
            <span class="pwa-house-pills">${c.pills.map(p => `<span class="pwa-pill ${p.tone}">${mfEscape(p.text)}</span>`).join('')}</span>
            <span class="pwa-house-faces">${c.faces.map(id => presenceCircle(membersData.find(m => m.id === id) || {id, name:'?'}, 'w-6 h-6 text-xs', '', 'span')).join('')}</span>
            ${typeof c.progress === 'number' ? `<span class="pwa-house-bar"><i style="width:${c.progress * 100}%"></i></span>` : ''}
            </span></button>`).join('');
    if (host._pwaHouseHtml !== html) {
        host.innerHTML = html;
        host._pwaHouseHtml = html;
        host.querySelectorAll('[data-card]').forEach(b => { b.onclick = () => pwaOpenHouseScreen(b.dataset.card); });
        if (focusedCard) Array.from(host.querySelectorAll('[data-card]')).find(b => b.dataset.card === focusedCard)?.focus({preventScroll:true});
    }
    pwaRefreshHouseScreen(cards);
}

function pwaHouseSegments(id) {
    if (id === 'projects') return [['projects','Projects'], ['programs','Programs']];
    if (id !== 'chores') return [];
    const count = choresToCheck().length;
    return [['mine','Mine'], ['open','Open'], ...(currentMemberRole() === 'parent'
        ? [['check', 'To check' + (count ? ` · ${count}` : '')]] : [])];
}

function pwaRefreshHouseScreen(cards) {
    const active = pwaHouseActive;
    if (!active) return;
    const card = cards.find(c => c.id === active.id);
    active.body.querySelector('.pwa-house-lead').textContent = pwaHouseholdLead(card ? [card] : []);
    const segments = pwaHouseSegments(active.id);
    active.body.querySelectorAll('.pwa-seg-item').forEach(b => {
        b.textContent = segments.find(s => s[0] === b.dataset.segment)?.[1] || '';
    });
    if (active.programsHost) {
        practiceWindows = pwaHouseWindows;
        active.programsHost.innerHTML = renderProgramsSection(pwaHousePrograms, pwaHouseCommitments, {title:'Programs'})
            || '<p class="pwa-empty">Nothing running yet.</p>';
    }
}

// Move the actual builder node, retaining its listeners and Alpine state.
function pwaAdoptHouseNode(id, host, returns) {
    const node = document.getElementById(id);
    if (id === 'projects-container') {
        returns.push(pwaAdoptProjectsNode(host));
        return node;
    }
    const home = document.createComment('household adoption');
    node.before(home);
    host.append(node);
    returns.push(() => { home.replaceWith(node); });
    return node;
}

function pwaOpenHouseScreen(id, segment) {
    const grantedList = id === 'lists' && houseLists.some(l => l.id === houseActiveListId);
    if (!pwaIsAdult() || (!pwaAllowed('chores') && !grantedList) || !window.PwaNav) return false;
    const titles = {chores:'Chores', rewards:chfFeatureOn('rewards') ? 'Rewards' : 'Points', tasks:'Tasks', lists:'Lists', projects:'Projects & programs'};
    if (!titles[id] || (!grantedList && !pwaHouseholdCards(pwaHouseholdInputs()).some(c => c.id === id))) return false;
    if (currentView !== 'chores') setView('chores');
    if (pwaHouseActive?.id === id) { if (segment) pwaHouseSegment(id, segment); return true; }
    // A deep link from an adopted project list replaces that household door.
    if (pwaHouseActive) {
        pwaHouseActive.clearing = true;
        PwaNav.clear({restoreFocus:false});
    }
    const returns = [];
    const owner = selectedMemberId;
    const openerCard = document.activeElement?.dataset.card;
    let screenState;
    PwaNav.push({id:'house-' + id, title:titles[id], render(body) {
        pwaHouseActive = screenState = {id, body, returns};
        body.dataset.houseScreen = id;
        body.innerHTML = '<p class="pwa-house-lead"></p>';
        const segments = pwaHouseSegments(id);
        if (segments.length) {
            const seg = document.createElement('div');
            seg.className = 'pwa-seg'; seg.setAttribute('role', 'group'); seg.setAttribute('aria-label', titles[id] + ' sections');
            for (const [value, label] of segments) {
                const button = document.createElement('button');
                button.type = 'button'; button.className = 'pwa-seg-item'; button.dataset.segment = value;
                button.textContent = label; button.onclick = () => pwaHouseSegment(id, value); seg.append(button);
            }
            body.append(seg);
        }
        if (id === 'chores' || id === 'rewards') {
            const node = pwaAdoptHouseNode('chores-content', body, returns);
            node.dataset.houseScreen = id;
            returns.push(() => { delete node.dataset.houseScreen; });
        } else if (id === 'lists') pwaAdoptHouseNode('house-lists', body, returns);
        else if (id === 'tasks') {
            const host = document.createElement('div'); body.append(host); renderHouseholdTasks(host);
            returns.push(() => { if (householdTasksHost === host) householdTasksHost = null; });
        } else if (id === 'projects') {
            pwaAdoptHouseNode('projects-container', body, returns);
            const host = document.createElement('div'); host.dataset.housePrograms = '';
            body.append(host); pwaHouseActive.programsHost = host;
            window.dispatchEvent(new CustomEvent('chf-projects-open'));
        }
        if (id === 'chores' && !segments.some(s => s[0] === segment)) {
            segment = choresMine().length ? 'mine'
                : choresAvailable().length ? 'open'
                : currentMemberRole() === 'parent' ? 'check' : 'mine';
        }
        if (id === 'projects' && !segments.some(s => s[0] === segment)) segment = pwaHouseProjects.length ? 'projects'
            : pwaHousePrograms.length ? 'programs' : 'projects';
        pwaHouseSegment(id, segment || id);
        pwaRefreshHouseScreen(pwaHouseholdCards(pwaHouseholdInputs()));
    }, onPop() {
        pwaHouseActive = null;
        returns.forEach(restore => {
            try { restore(); }
            catch (error) { console.error('Household restore failed', error); }
        });
        document.getElementById('chores-container').dataset.section = 'cards';
        pwaRenderHousehold();
        if (!screenState.clearing) queueMicrotask(() => {
            if (currentView !== 'chores' || pwaHouseActive || owner !== selectedMemberId) return;
            // PwaNav's original opener may have been replaced during a write.
            if (openerCard) Array.from(document.querySelectorAll('#house-cards [data-card]'))
                .find(b => b.dataset.card === openerCard)?.focus({preventScroll:true});
            if (id === 'projects') void pwaFetchHousehold();
        });
    }});
    return true;
}

function pwaHouseSegment(id, segment) {
    const active = pwaHouseActive;
    if (!active || active.id !== id) return;
    const segments = pwaHouseSegments(id);
    if (segments.length && !segments.some(s => s[0] === segment)) return;
    active.body.dataset.houseSegment = segment;
    active.body.querySelectorAll('.pwa-seg-item').forEach(b => {
        const on = b.dataset.segment === segment;
        b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on));
    });
    document.getElementById('chores-container').dataset.section = id === 'chores' ? segment === 'check' ? 'reviews' : 'tasks'
        : id === 'projects' ? 'projects' : id;
}

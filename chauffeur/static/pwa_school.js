// School view (kid-support arc K4d): a child's assignments as an agenda or a
// month, the detail a school feed carries (class, teacher's description and
// links, due time, the link back to Canvas), and the place the family names
// a feed's cryptic course codes. Opened from the Due Soon card's "See all"
// and from More -> School. One sheet for a kid and for a parent: the parent
// picks which child first, everything else is the same.
//
// Loaded by app.html after its inline script; reads its globals (apiBase,
// selectedMemberId, membersData, mfEscape, formatClock, completeKidTask,
// clearPastKidTasks, _pwaModal, promptInput, promptChoice, showGlobalAlert).
// Uses the PWA's gray vocabulary (remapped by the theme token layer) rather
// than agenda_row.html's dark-only .agenda-day, which the app does not load.

let pwaSchool = null;   // {owner, tasks, classes, mode, month, day}
const pwaSchoolTasks = {};  // id -> task, for detail sheets opened from any row

const SCHOOL_EMOJI = {homework: '📚', test: '📝', project: '📐', bring: '🎒', other: '📌'};
const SCHOOL_PALETTE = [['#6366f1', 'Indigo'], ['#14b8a6', 'Teal'], ['#f59e0b', 'Amber'],
    ['#ec4899', 'Pink'], ['#22c55e', 'Green'], ['#3b82f6', 'Blue'], ['#ef4444', 'Red'],
    ['#a855f7', 'Purple'], ['#84cc16', 'Lime'], ['#06b6d4', 'Cyan']];

function schoolColor(c) {
    return /^#[0-9a-fA-F]{6}$/.test(c || '') ? c : '#6366f1';
}

function schoolLocalDate(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function schoolDayHeading(iso) {
    const today = new Date(); today.setHours(12, 0, 0, 0);
    const d = new Date(iso + 'T12:00:00');
    const diff = Math.round((d - today) / 86400000);
    if (diff === 0) return 'Today';
    if (diff === 1) return 'Tomorrow';
    return d.toLocaleDateString(undefined, {weekday: 'short', month: 'short', day: 'numeric'});
}

// Class chip + due time: the metadata line every school row carries.
function schoolTaskMeta(t) {
    const bits = [];
    // A raw course code is noise on a row; the color bar already says which
    // class, and the name appears once somebody gives it one.
    if (t.course_name && t.course_named) bits.push(`<span class="text-xs font-bold px-1.5 py-0.5 rounded bg-gray-700 text-gray-300 truncate max-w-[10rem]">${mfEscape(t.course_name)}</span>`);
    if (t.due_time) bits.push(`<span class="text-xs font-semibold text-gray-400">by ${mfEscape(formatClock(t.due_time))}</span>`);
    if (t.description || (t.links || []).length) bits.push('<span class="text-xs font-semibold text-gray-400" aria-label="Has details">📎</span>');
    return bits.length ? `<span class="flex items-center gap-1.5 min-w-0">${bits.join('')}</span>` : '';
}

function schoolLinkify(text) {
    return mfEscape(text).replace(/https?:\/\/[^\s<]+/g,
        u => `<a href="${u}" target="_blank" rel="noopener noreferrer" class="text-indigo-300 underline break-all">${u}</a>`);
}

function schoolRemember(t) { pwaSchoolTasks[t.id] = t; return t; }

// One task's whole story, from any row that has its id.
function openKidTaskDetail(id) {
    const t = pwaSchoolTasks[id];
    if (!t) return;
    const color = schoolColor(t.course_color);
    const due = t.due_date ? schoolDayHeading(t.due_date) + (t.due_time ? ` · by ${formatClock(t.due_time)}` : '') : '';
    const links = (t.links || []).map(l => `
        <a href="${mfEscape(l.url)}" target="_blank" rel="noopener noreferrer"
            class="flex items-center gap-2 rounded-lg px-2.5 py-1.5 bg-gray-800 text-sm font-bold text-indigo-200 break-all">🔗 ${mfEscape(l.text || l.url)}</a>`).join('');
    const done = t.status === 'done';
    const overlay = _pwaModal(`
        <div class="flex items-start gap-2 mb-1">
            <span class="w-1 self-stretch rounded" style="background:${color}"></span>
            <div class="min-w-0">
                <div class="text-gray-100 font-bold text-lg leading-snug">${SCHOOL_EMOJI[t.kind] || '📌'} ${mfEscape(t.title)}</div>
                <div class="text-xs font-semibold text-gray-400">${t.course_id
                    // The class is tappable: a bare course code is the one
                    // thing on this sheet a family can fix in place.
                    ? `<span role="button" tabindex="0" data-rename class="cursor-pointer underline text-indigo-300">${mfEscape(t.course_named ? t.course_name : `${t.course_name || t.course_label || 'Class'} · Name this class`)}</span>`
                    : mfEscape(t.course_name || '')}${t.course_name && due ? ' · ' : ''}${mfEscape(due)}</div>
            </div>
        </div>
        <div class="max-h-[50vh] overflow-y-auto my-3 flex flex-col gap-2">
            ${t.description ? `<div class="text-sm text-gray-300 leading-snug whitespace-pre-line">${schoolLinkify(t.description)}</div>`
                            : '<p class="text-xs text-gray-500 italic">No description from the teacher.</p>'}
            ${t.notes ? `<div class="text-sm text-gray-300 whitespace-pre-line">${mfEscape(t.notes)}</div>` : ''}
            ${links ? `<div class="flex flex-col gap-1.5">${links}</div>` : ''}
        </div>
        <div class="flex gap-2 justify-end flex-wrap">
            ${t.url ? `<a href="${mfEscape(t.url)}" target="_blank" rel="noopener noreferrer" class="px-4 py-2 rounded-xl bg-gray-800 border border-gray-700 text-gray-200 text-sm font-bold">Open in school site</a>` : ''}
            <button data-close class="px-4 py-2 rounded-xl bg-gray-800 border border-gray-700 text-gray-200 text-sm font-bold">Close</button>
            <button data-yes class="px-4 py-2 rounded-xl bg-green-600 text-white text-sm font-bold">${done ? 'Mark not done' : 'Check off'}</button>
        </div>`, (overlay, close) => {
        overlay.querySelector('[data-close]').onclick = close;
        const rename = overlay.querySelector('[data-rename]');
        if (rename) {
            rename.onclick = () => { close(); schoolNameClass(t.course_id, t.course_label, t.course_named ? t.course_name : ''); };
            rename.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); rename.click(); } };
        }
        overlay.querySelector('[data-yes]').onclick = async () => {
            close();
            await completeKidTask(t.id, !done);
            t.status = done ? 'open' : 'done';
            if (pwaSchool) pwaSchoolLoad();
        };
        overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
    });
    return overlay;
}

function pwaSchoolChildren() {
    return (membersData || []).filter(m => m.role === 'child' && !m.system && m.status !== 'archived');
}

async function pwaSchoolOpen(ownerId) {
    let owner = ownerId;
    if (!owner) {
        const me = (membersData || []).find(m => m.id === selectedMemberId);
        if (me && me.role === 'child') owner = me.id;
        else {
            const kids = pwaSchoolChildren();
            if (!kids.length) return showGlobalAlert('No children in the family yet.');
            owner = kids.length === 1 ? kids[0].id
                : await promptChoice('Whose school list?', '', kids.map(k => ({label: k.name, value: k.id})));
            if (!owner) return;
        }
    }
    const now = new Date();
    pwaSchool = {owner, tasks: [], classes: [], mode: 'agenda', hidden: schoolLoadHidden(owner), pillKeys: [],
                 month: new Date(now.getFullYear(), now.getMonth(), 1), day: schoolLocalDate(now)};
    document.getElementById('pwa-school-overlay')?.remove();
    const overlay = document.createElement('div');
    overlay.id = 'pwa-school-overlay';
    overlay.className = 'pwa-sheet-overlay fixed inset-0 z-[400] bg-black/70 flex items-end sm:items-center justify-center p-4';
    overlay.innerHTML = `<div class="pwa-sheet w-full max-w-sm bg-gray-900 border border-gray-700 rounded-2xl shadow-2xl p-5 max-h-[85dvh] overflow-y-auto" role="dialog" aria-label="School"><div id="pwa-school-body"><p class="text-xs text-gray-500 italic">Loading…</p></div></div>`;
    overlay.addEventListener('click', e => { if (e.target === overlay) pwaSchoolClose(); });
    document.body.appendChild(overlay);
    await pwaSchoolLoad();
}

function pwaSchoolClose() {
    document.getElementById('pwa-school-overlay')?.remove();
    pwaSchool = null;
    if (typeof refreshTodaySurfaces === 'function') refreshTodaySurfaces();
}

async function pwaSchoolLoad() {
    if (!pwaSchool) return;
    const owner = pwaSchool.owner;
    try {
        const [tr, cr] = await Promise.all([
            fetch(`${apiBase}api/kid-tasks?member_id=${encodeURIComponent(owner)}`),
            fetch(`${apiBase}api/kid-tasks/classes?member_id=${encodeURIComponent(owner)}`)]);
        if (!tr.ok) throw new Error();
        if (!pwaSchool || pwaSchool.owner !== owner) return;
        pwaSchool.tasks = (await tr.json()).map(schoolRemember);
        pwaSchool.classes = cr.ok ? await cr.json() : [];
    } catch (e) {
        const body = document.getElementById('pwa-school-body');
        if (body) body.innerHTML = '<p class="text-xs text-gray-500 italic">Could not load the school list.</p>';
        return;
    }
    pwaSchoolRender();
}

function pwaSchoolRow(t) {
    const done = t.status === 'done';
    return `
        <div class="rounded-lg bg-gray-800 px-2.5 py-1.5 flex items-center gap-2" style="border-left:4px solid ${schoolColor(t.course_color)}">
            <input type="checkbox" ${done ? 'checked' : ''} aria-label="${mfEscape(t.title)}"
                onchange="pwaSchoolCheck('${t.id}', this.checked)" class="w-6 h-6 rounded-lg accent-indigo-500 shrink-0">
            <div role="button" tabindex="0" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click()}" onclick="openKidTaskDetail('${t.id}')" class="flex-1 min-w-0 text-left flex flex-col gap-0.5 cursor-pointer">
                <span class="text-[15px] font-bold text-gray-100 truncate ${done ? 'line-through' : ''}">${SCHOOL_EMOJI[t.kind] || '📌'} ${mfEscape(t.title)}</span>
                ${schoolTaskMeta(t)}
            </div>
        </div>`;
}

async function pwaSchoolCheck(id, done) {
    await completeKidTask(id, done);
    const t = pwaSchoolTasks[id];
    if (t) t.status = done ? 'done' : 'open';
}

function pwaSchoolGroup(tasks) {
    const days = {};
    tasks.forEach(t => { (days[t.due_date] = days[t.due_date] || []).push(t); });
    return Object.keys(days).sort().map(d => `
        <div class="rounded-xl border border-gray-800 p-3 flex flex-col gap-2">
            <div class="text-sm font-bold text-gray-300">${mfEscape(schoolDayHeading(d))}</div>
            ${days[d].map(pwaSchoolRow).join('')}
        </div>`).join('');
}

function pwaSchoolAgenda(open, today) {
    const ahead = open.filter(t => t.due_date >= today);
    const late = open.filter(t => t.due_date < today).reverse();
    return `
        ${ahead.length ? `<div class="flex flex-col gap-2">${pwaSchoolGroup(ahead)}</div>`
                       : '<p class="text-xs text-gray-500 italic">Nothing coming up.</p>'}
        ${late.length ? `
        <details class="mt-3">
            <summary class="flex items-center justify-between cursor-pointer select-none py-1">
                <span class="text-xs font-bold text-gray-400">🗂 Still open from earlier</span>
                <span class="text-xs text-gray-500 font-bold">${late.length}</span>
            </summary>
            <div class="flex flex-col gap-2 mt-2">${late.map(pwaSchoolRow).join('')}</div>
            <button type="button" onclick="pwaSchoolClearPast(${late.length})"
                class="mt-2 w-full text-xs font-bold text-gray-300 bg-gray-800 rounded-lg py-2 active:opacity-70">Clear all ${late.length}</button>
        </details>` : ''}`;
}

async function pwaSchoolClearPast(n) {
    if (!pwaSchool) return;
    const s = pwaSchool;
    if (!s.hidden.size) {
        await clearPastKidTasks(s.owner, n);
        return pwaSchoolLoad();
    }
    // A class filter is on: "Clear all" means all the ones on screen, never
    // the hidden classes' items the server's date-only clear would also take.
    const today = schoolLocalDate(new Date());
    const late = s.tasks.filter(t => t.status !== 'done' && t.due_date < today
                                     && !s.hidden.has(t.course_key || ''));
    const ok = await promptConfirm(`Check off ${late.length} older item${late.length === 1 ? '' : 's'}?`,
        'Only the classes you are showing. Use this when they were already handed in.', 'Check off');
    if (!ok) return;
    for (const t of late) {
        try {
            await fetch(`${apiBase}api/kid-tasks/${t.id}/complete`, {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({member_id: selectedMemberId, done: true})});
        } catch (e) { /* one failure must not stop the rest */ }
    }
    showGlobalAlert('Cleared ✅');
    pwaSchoolLoad();
}

function pwaSchoolMonth(open) {
    const s = pwaSchool, first = s.month;
    const label = first.toLocaleDateString(undefined, {month: 'long', year: 'numeric'});
    const byDay = {};
    open.forEach(t => { (byDay[t.due_date] = byDay[t.due_date] || []).push(t); });
    const lead = first.getDay();
    const daysIn = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
    const today = schoolLocalDate(new Date());
    const heads = Array.from({length: 7}, (_, i) =>
        new Date(2023, 0, 1 + i).toLocaleDateString(undefined, {weekday: 'narrow'}));
    let cells = heads.map(h => `<div class="text-xs font-bold text-gray-500 text-center">${h}</div>`).join('');
    for (let i = 0; i < lead; i++) cells += '<div></div>';
    for (let d = 1; d <= daysIn; d++) {
        const iso = schoolLocalDate(new Date(first.getFullYear(), first.getMonth(), d));
        const items = byDay[iso] || [];
        // Tests and projects show their emoji: the ones a family plans around.
        const big = items.find(t => t.kind === 'test' || t.kind === 'project');
        const dots = items.slice(0, 4).map(t => `<span class="w-1.5 h-1.5 rounded-full" style="background:${schoolColor(t.course_color)}"></span>`).join('');
        const sel = iso === s.day;
        cells += `<div role="button" tabindex="0" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click()}" onclick="pwaSchoolPickDay('${iso}')" aria-pressed="${sel}" data-day="${iso}"
            class="cursor-pointer rounded-lg py-1 flex flex-col items-center gap-0.5 min-h-[2.75rem] ${sel ? 'bg-indigo-600/40 border border-indigo-400' : iso === today ? 'border border-gray-600' : 'bg-gray-800/40'}">
            <span class="text-xs font-bold ${iso < today ? 'text-gray-500' : 'text-gray-200'}">${d}</span>
            ${big ? `<span class="text-xs leading-none">${SCHOOL_EMOJI[big.kind]}</span>` : `<span class="flex gap-0.5">${dots}</span>`}
        </div>`;
    }
    const picked = byDay[s.day] || [];
    return `
        <div class="flex items-center justify-between mb-2">
            <button type="button" onclick="pwaSchoolShiftMonth(-1)" class="px-3 py-1 rounded-lg bg-gray-800 text-gray-300 font-bold" aria-label="Previous month">‹</button>
            <span class="text-sm font-bold text-gray-200">${mfEscape(label)}</span>
            <button type="button" onclick="pwaSchoolShiftMonth(1)" class="px-3 py-1 rounded-lg bg-gray-800 text-gray-300 font-bold" aria-label="Next month">›</button>
        </div>
        <div class="grid grid-cols-7 gap-1">${cells}</div>
        <div class="rounded-xl border border-gray-800 p-3 flex flex-col gap-2 mt-3">
            <div class="text-sm font-bold text-gray-300">${mfEscape(schoolDayHeading(s.day))}</div>
            ${picked.length ? picked.map(pwaSchoolRow).join('') : '<p class="text-xs text-gray-500 italic">Nothing due this day.</p>'}
        </div>`;
}

function pwaSchoolPickDay(iso) { if (pwaSchool) { pwaSchool.day = iso; pwaSchoolRender(); } }
function pwaSchoolShiftMonth(n) {
    if (!pwaSchool) return;
    const m = pwaSchool.month;
    pwaSchool.month = new Date(m.getFullYear(), m.getMonth() + n, 1);
    pwaSchoolRender();
}
function pwaSchoolMode(mode) { if (pwaSchool) { pwaSchool.mode = mode; pwaSchoolRender(); } }

function pwaSchoolClasses() {
    const cls = pwaSchool.classes;
    if (!cls.length) return '';
    const unnamed = cls.some(c => !c.name && !c.canvas_name && /\d/.test(c.display || '') && (c.display || '').includes('.'));
    return `
        <details class="mt-4" ${unnamed ? 'open' : ''}>
            <summary class="text-xs font-black uppercase tracking-widest text-gray-500 cursor-pointer select-none py-1">Classes</summary>
            ${unnamed ? '<p class="text-xs text-gray-400 mb-2">Give your classes names so they read nicely everywhere.</p>' : ''}
            ${['parent', 'adult'].includes(currentMemberRole()) ? `<div role="button" tabindex="0" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click()}" onclick="pwaSchoolCanvasToken()"
                class="cursor-pointer mb-2 text-center text-xs font-bold text-gray-300 bg-gray-800 rounded-lg py-2">Get names from Canvas</div>` : ''}
            <div class="flex flex-col gap-1.5">
            ${cls.map(c => `
                <div class="rounded-lg bg-gray-800 px-2.5 py-1.5 flex items-center gap-2">
                    <div role="button" tabindex="0" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click()}" onclick="pwaSchoolColorClass('${c.id}')" aria-label="Change color"
                        class="cursor-pointer w-6 h-6 rounded-full shrink-0 border border-gray-600" style="background:${schoolColor(c.color)}"></div>
                    <div role="button" tabindex="0" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click()}" onclick="pwaSchoolRenameClass('${c.id}')" aria-label="Rename class" class="cursor-pointer flex-1 min-w-0 text-left">
                        <span class="block text-sm font-bold text-gray-100 truncate">${mfEscape(c.display)}</span>
                        ${c.name && c.label && c.label !== c.name ? `<span class="block text-xs font-semibold text-gray-400 truncate">${mfEscape(c.label)}</span>` : ''}
                    </div>
                    <span class="text-xs font-bold px-1.5 py-0.5 rounded bg-gray-700 text-gray-300">${c.open_count}</span>
                </div>`).join('')}
            </div>
        </details>`;
}

async function pwaSchoolUpdateClass(id, body) {
    try {
        const r = await fetch(`${apiBase}api/kid-tasks/classes/${id}`, {
            method: 'PUT', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({...body, member_id: selectedMemberId})});
        if (!r.ok) throw new Error();
    } catch (e) { return showGlobalAlert('Could not save the class'); }
    pwaSchoolLoad();
}

async function pwaSchoolRenameClass(id) {
    const c = (pwaSchool?.classes || []).find(x => x.id === id);
    if (!c) return;
    schoolNameClass(id, c.label, c.name || '', c.canvas_name);
}

// Name a class from anywhere a class shows (the Classes list, a task's
// detail sheet). Clearing the name falls back to Canvas's, then the code.
async function schoolNameClass(id, label, current, canvasName) {
    const hint = [label ? `The feed calls it ${label}.` : '',
                  canvasName ? `Canvas calls it ${canvasName}.` : ''].filter(Boolean).join(' ');
    const name = await promptInput('Name this class', hint,
        {value: current || '', placeholder: canvasName || 'Science', okText: 'Save'});
    if (name === null) return;
    try {
        const r = await fetch(`${apiBase}api/kid-tasks/classes/${id}`, {
            method: 'PUT', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name, member_id: selectedMemberId})});
        if (!r.ok) throw new Error();
    } catch (e) { return showGlobalAlert('Could not save the class'); }
    if (pwaSchool) pwaSchoolLoad();
    else if (typeof refreshTodaySurfaces === 'function') refreshTodaySurfaces();
}

// Canvas's own course names (K4d): a parent pastes an access token made in
// the child's Canvas account; the server keeps it write-only and fetches the
// names. Parents only: the feed routes are.
async function pwaSchoolCanvasToken() {
    if (!pwaSchool) return;
    let feeds = [];
    try {
        const r = await fetch(`${apiBase}api/ics_feeds`);
        if (r.ok) feeds = (await r.json()).filter(f => f.target_kind === 'tasks' && f.member_id === pwaSchool.owner);
    } catch (e) { /* handled below */ }
    if (!feeds.length) return showGlobalAlert('No school feed for this child.');
    const feed = feeds[0];
    const token = await promptInput('Class names from Canvas',
        'Signed in to Canvas as your child: Account → Settings → New Access Token. Paste it here. '
        + 'Chauffeur only reads the course list with it, never shows it again, and sends it nowhere but your school’s Canvas.'
        + (feed.canvas_token_set ? ' Leave empty to remove the saved one.' : ''),
        {placeholder: 'Canvas access token', okText: 'Save'});
    if (token === null) return;
    try {
        const r = await fetch(`${apiBase}api/ics_feeds/${feed.id}/canvas-token`, {
            method: 'PUT', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({token: token.trim()})});
        const d = await r.json().catch(() => ({}));
        if (!r.ok) return showGlobalAlert(d.detail || 'Could not save the token');
        showGlobalAlert(d.status === 'cleared' ? 'Canvas token removed'
            : (d.status || '').startsWith('error') ? d.status.replace(/^error: /, '')
            : `Named ${d.named} class${d.named === 1 ? '' : 'es'} from Canvas`);
    } catch (e) { return showGlobalAlert('Could not reach Chauffeur'); }
    pwaSchoolLoad();
}

async function pwaSchoolColorClass(id) {
    const color = await promptChoice('Class color', '', SCHOOL_PALETTE.map(([v, l]) => ({label: l, value: v})));
    if (color) pwaSchoolUpdateClass(id, {color});
}

// Class pills (the calendar legend's people pills, for classes): tap one to
// hide that class's items in both Agenda and Month. Remembered per child on
// THIS device -- a parent filtering out homeroom must not change what the
// child or the other parent sees. '' stands for items with no class.
function schoolHiddenKey(owner) { return `chauffeur_school_hidden_${owner}`; }

function schoolLoadHidden(owner) {
    try { return new Set(JSON.parse(localStorage.getItem(schoolHiddenKey(owner)) || '[]')); }
    catch (e) { return new Set(); }
}

function schoolSaveHidden() {
    if (!pwaSchool) return;
    try { localStorage.setItem(schoolHiddenKey(pwaSchool.owner), JSON.stringify([...pwaSchool.hidden])); }
    catch (e) { /* private mode: the filter just lasts this visit */ }
}

function pwaSchoolPills(open) {
    const s = pwaSchool;
    const byKey = new Map(s.classes.map(c => [c.key, c]));
    const keys = [];
    open.forEach(t => { const k = t.course_key || ''; if (!keys.includes(k)) keys.push(k); });
    // Hidden classes keep their pill even when the filter emptied them out,
    // or there would be no way to switch them back on.
    s.hidden.forEach(k => { if (!keys.includes(k) && (k === '' || byKey.has(k))) keys.push(k); });
    if (keys.length < 2) { s.pillKeys = []; return ''; }
    keys.sort((a, b) => (a === '') - (b === '')
        || (s.classes.findIndex(c => c.key === a) - s.classes.findIndex(c => c.key === b)));
    s.pillKeys = keys;
    const pills = keys.map((k, i) => {
        const c = byKey.get(k);
        const color = k ? schoolColor(c?.color) : '#64748b';
        const label = k ? (c?.display || k) : 'No class';
        const off = s.hidden.has(k);
        const style = off
            ? `background:color-mix(in srgb, ${color} 12%, transparent);border-color:${color};color:${color}`
            : `background:${color};border-color:transparent;color:#fff`;
        return `<span role="button" tabindex="0" aria-pressed="${!off}" data-pill="${i}"
            onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click()}"
            onclick="pwaSchoolTogglePill(${i})"
            class="cursor-pointer px-3 py-1.5 rounded-full text-xs font-bold border max-w-[12rem] truncate ${off ? 'opacity-80' : ''}"
            style="${style}">${mfEscape(label)}</span>`;
    }).join('');
    const reset = s.hidden.size ? `<span role="button" tabindex="0" onclick="pwaSchoolShowAll()"
        onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click()}"
        class="cursor-pointer px-3 py-1.5 rounded-full text-xs font-bold text-gray-300 border border-gray-600">Show all</span>` : '';
    return `<div class="flex flex-wrap gap-1.5 mb-3" aria-label="Filter by class">${pills}${reset}</div>`;
}

function pwaSchoolTogglePill(i) {
    if (!pwaSchool) return;
    const k = pwaSchool.pillKeys[i];
    if (k === undefined) return;
    if (pwaSchool.hidden.has(k)) pwaSchool.hidden.delete(k); else pwaSchool.hidden.add(k);
    schoolSaveHidden();
    pwaSchoolRender();
}

function pwaSchoolShowAll() {
    if (!pwaSchool) return;
    pwaSchool.hidden.clear();
    schoolSaveHidden();
    pwaSchoolRender();
}

function pwaSchoolRender() {
    const body = document.getElementById('pwa-school-body');
    if (!body || !pwaSchool) return;
    const s = pwaSchool;
    const who = (membersData || []).find(m => m.id === s.owner);
    const mine = s.owner === selectedMemberId;
    const today = schoolLocalDate(new Date());
    // Past-due is the child's own business (K4: overdue is never a parent
    // dashboard, and the feed has no submission state, so most of it was
    // handed in anyway). A parent's view starts at today, in both modes.
    const open = s.tasks.filter(t => t.status !== 'done' && (mine || t.due_date >= today));
    const pills = pwaSchoolPills(open);
    const shown = open.filter(t => !s.hidden.has(t.course_key || ''));
    // A segmented control, not two sheet buttons: the sheet's boxed button
    // treatment would draw both halves alike and hide which one is on.
    const tab = (mode, label) => `<div role="button" tabindex="0" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click()}" onclick="pwaSchoolMode('${mode}')" aria-pressed="${s.mode === mode}"
        class="cursor-pointer flex-1 text-center py-2 rounded-lg text-sm font-bold ${s.mode === mode ? 'bg-gray-700 text-gray-100' : 'text-gray-400'}">${label}</div>`;
    body.innerHTML = `
        <div class="flex items-center justify-between mb-3">
            <div class="text-gray-100 font-bold text-lg">${mine ? 'School' : mfEscape((who?.name || '') + '’s school list')}</div>
            <button type="button" onclick="pwaSchoolClose()" class="pwa-sheet-close text-gray-400 text-xl px-2" aria-label="Close">&#215;</button>
        </div>
        <div class="flex gap-1 bg-gray-800 rounded-xl p-1 mb-3">${tab('agenda', 'Agenda')}${tab('month', 'Month')}</div>
        ${pills}
        ${s.mode === 'month' ? pwaSchoolMonth(shown) : pwaSchoolAgenda(shown, today)}
        ${pwaSchoolClasses()}`;
}

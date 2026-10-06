// School view (kid-support arc K4d): a child's assignments as an agenda or a
// month, the detail a school feed carries (class, teacher's description and
// links, due time, the link back to Canvas), and the place the family names
// a feed's cryptic course codes. Opened from the Due Soon card's "See all"
// and from More -> School. One sheet for a kid and for a parent: the parent
// picks which child first, everything else is the same.
//
// Loaded by app.html after its inline script; reads its globals (apiBase,
// selectedMemberId, membersData, mfEscape, formatClock, completeKidTask,
// clearPastKidTasks, _pwaModal, promptInput, promptChoice, promptConfirm,
// showGlobalAlert, currentMemberRole, refreshTodaySurfaces).
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
// Tests and projects are the things a family plans around (K4d): they get
// their own tag, a heavier row, the Heads-up strip and their own filter.
// Homework and info items stay quiet. One saturated element per row (the
// tag), per the design guide.
const SCHOOL_BIG = ['test', 'project'];
const SCHOOL_KINDS = [['test', 'Test or quiz'], ['project', 'Project'], ['homework', 'Homework'],
    ['bring', 'Something to bring'], ['other', 'Other / info']];

function schoolIsBig(t) { return SCHOOL_BIG.includes(t.kind); }

function schoolDaysUntil(iso) {
    const today = new Date(); today.setHours(12, 0, 0, 0);
    return Math.round((new Date(iso + 'T12:00:00') - today) / 86400000);
}

function schoolCountdown(iso) {
    const n = schoolDaysUntil(iso);
    return n < 0 ? 'past' : n === 0 ? 'today' : n === 1 ? 'tomorrow' : `${n} days`;
}

function schoolBigTag(t) {
    if (!schoolIsBig(t) || !t.due_date) return '';
    const tint = t.kind === 'test' ? 'bg-amber-500/20 text-amber-300' : 'bg-teal-500/20 text-teal-300';
    return `<span class="text-xs font-bold px-1.5 py-0.5 rounded uppercase tracking-wide shrink-0 ${tint}">${t.kind === 'test' ? 'Test' : 'Project'} · ${schoolCountdown(t.due_date)}</span>`;
}

// The top of the Due Soon card: tests and projects in the coming week, with
// a countdown, so a quiz never hides among worksheets. They stay in the
// list below too; nothing moves.
function schoolHeadsUp(tasks) {
    const big = (tasks || []).filter(t => schoolIsBig(t) && schoolDaysUntil(t.due_date) >= 0)
        .sort((a, b) => a.due_date.localeCompare(b.due_date));
    if (!big.length) return '';
    return `<div class="mb-2 rounded-lg bg-gray-800 px-3 py-2 flex flex-col gap-1.5" data-heads-up>
        <span class="text-xs font-bold text-gray-400">Heads-up</span>
        ${big.map(t => { schoolRemember(t); return `
        <div role="button" tabindex="0" onclick="openKidTaskDetail('${t.id}')"
            onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click()}"
            class="cursor-pointer flex items-center gap-2 min-w-0">
            <span class="w-1 self-stretch rounded" style="background:${schoolColor(t.course_color)}"></span>
            <span class="flex-1 min-w-0 truncate text-sm font-bold text-gray-100">${SCHOOL_EMOJI[t.kind] || '📌'} ${mfEscape(t.title)}${t.course_named && t.course_name ? ` <span class="text-gray-400 font-semibold">· ${mfEscape(t.course_name)}</span>` : ''}</span>
            ${schoolBigTag(t)}
        </div>`; }).join('')}
    </div>`;
}

async function schoolSetKind(id, current) {
    const kind = await promptChoice('What kind of item is this?', 'Tests and projects stand out everywhere.',
        SCHOOL_KINDS.map(([v, l]) => ({label: (v === current ? '✓ ' : '') + l, value: v})));
    if (!kind || kind === current) return;
    try {
        const r = await fetch(`${apiBase}api/kid-tasks/${id}/kind`, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({kind, member_id: selectedMemberId})});
        if (!r.ok) throw new Error();
    } catch (e) { return showGlobalAlert('Could not change it'); }
    const t = pwaSchoolTasks[id];
    if (t) t.kind = kind;
    if (pwaSchool) pwaSchoolLoad();
    else if (typeof refreshTodaySurfaces === 'function') refreshTodaySurfaces();
}

function schoolTaskMeta(t) {
    const bits = [];
    const tag = schoolBigTag(t);
    if (tag) bits.push(tag);
    // A raw course code is noise on a row; the color bar already says which
    // class, and the name appears once somebody gives it one.
    if (t.course_name && t.course_named) bits.push(`<span class="text-xs font-bold px-1.5 py-0.5 rounded bg-gray-700 text-gray-300 truncate max-w-[10rem]">${mfEscape(t.course_name)}</span>`);
    if (t.due_time) bits.push(`<span class="text-xs font-semibold text-gray-400">by ${mfEscape(formatClock(t.due_time))}</span>`);
    if (t.description || t.notes || (t.links || []).length) bits.push('<span class="text-xs font-semibold text-gray-400" aria-label="Has details">📎</span>');
    return bits.length ? `<span class="flex flex-wrap items-center gap-1.5 min-w-0">${bits.join('')}</span>` : '';
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
    const canWrite = schoolCanWrite(t.member_id);
    const feed = schoolIsFeedTask(t);
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
        <div class="text-xs font-semibold text-gray-400 mt-1">Type: <span role="button" tabindex="0" data-kind
            class="cursor-pointer underline text-indigo-300">${mfEscape((SCHOOL_KINDS.find(([v]) => v === t.kind) || [, 'Other / info'])[1])}</span></div>
        <div class="max-h-[50vh] overflow-y-auto my-3 flex flex-col gap-2">
            ${t.description ? `<div class="text-sm text-gray-300 leading-snug whitespace-pre-line">${schoolLinkify(t.description)}</div>`
                            : '<p class="text-xs text-gray-500 italic">No description from the teacher.</p>'}
            ${t.notes ? `<div class="text-sm text-gray-300 whitespace-pre-line">${mfEscape(t.notes)}</div>` : ''}
            ${links ? `<div class="flex flex-col gap-1.5">${links}</div>` : ''}
            ${canWrite && feed ? '<p class="text-xs text-gray-500 italic">From the school feed — when it is done, check it off.</p>' : ''}
        </div>
        <div class="flex gap-2 justify-end flex-wrap">
            ${canWrite ? '<button data-edit class="px-4 py-2 rounded-xl bg-gray-800 border border-gray-700 text-gray-200 text-sm font-bold">Edit</button>' : ''}
            ${canWrite && !feed ? '<button data-delete class="px-4 py-2 rounded-xl bg-gray-800 border border-gray-700 text-gray-200 text-sm font-bold">Delete</button>' : ''}
            ${t.url ? `<a href="${mfEscape(t.url)}" target="_blank" rel="noopener noreferrer" class="px-4 py-2 rounded-xl bg-gray-800 border border-gray-700 text-gray-200 text-sm font-bold">Open in school site</a>` : ''}
            <button data-close class="px-4 py-2 rounded-xl bg-gray-800 border border-gray-700 text-gray-200 text-sm font-bold">Close</button>
            <button data-yes class="px-4 py-2 rounded-xl bg-green-600 text-white text-sm font-bold">${done ? 'Mark not done' : 'Check off'}</button>
        </div>`, (overlay, close) => {
        overlay.querySelector('[data-close]').onclick = close;
        const editEl = overlay.querySelector('[data-edit]');
        if (editEl) editEl.onclick = () => { close(); schoolTaskForm(t.member_id, t); };
        const delEl = overlay.querySelector('[data-delete]');
        if (delEl) delEl.onclick = () => { close(); schoolTaskDelete(t); };
        const kindEl = overlay.querySelector('[data-kind]');
        kindEl.onclick = () => { close(); schoolSetKind(t.id, t.kind); };
        kindEl.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); kindEl.click(); } };
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
                 bigOnly: schoolLoadBigOnly(owner),
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
        <div class="rounded-lg bg-gray-800 px-2.5 py-1.5 flex items-center gap-2" style="border-left:${schoolIsBig(t) ? 7 : 4}px solid ${schoolColor(t.course_color)}">
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

function schoolLoadBigOnly(owner) {
    try { return localStorage.getItem(`chauffeur_school_big_${owner}`) === '1'; } catch (e) { return false; }
}

function pwaSchoolToggleBig() {
    if (!pwaSchool) return;
    pwaSchool.bigOnly = !pwaSchool.bigOnly;
    try { localStorage.setItem(`chauffeur_school_big_${pwaSchool.owner}`, pwaSchool.bigOnly ? '1' : '0'); }
    catch (e) { /* lasts this visit */ }
    pwaSchoolRender();
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
    const anyBig = open.some(schoolIsBig);
    // The Tests & projects pill leads the row, apart from the class pills: a
    // KIND filter that combines with them ("Science tests only").
    const big = (anyBig || s.bigOnly) ? `<span role="button" tabindex="0" aria-pressed="${s.bigOnly}" data-big-pill
        onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click()}"
        onclick="pwaSchoolToggleBig()"
        class="cursor-pointer px-3 py-1.5 rounded-full text-xs font-bold border ${s.bigOnly ? 'bg-amber-500/20 text-amber-300 border-amber-400' : 'text-gray-300 border-gray-600'}">${s.bigOnly ? '✓ ' : ''}Tests & projects</span>` : '';
    if (keys.length < 2) {
        s.pillKeys = [];
        return big ? `<div class="flex flex-wrap gap-1.5 mb-3" aria-label="Filter">${big}</div>` : '';
    }
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
    return `<div class="flex flex-wrap gap-1.5 mb-3" aria-label="Filter by class">${big}${pills}${reset}</div>`;
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
    const shown = open.filter(t => !s.hidden.has(t.course_key || '') && (!s.bigOnly || schoolIsBig(t)));
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
        <div class="flex gap-2 mb-3">
            ${schoolCanWrite(s.owner) ? `<div role="button" tabindex="0" onclick="pwaSchoolAdd()" data-add-task
                onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click()}"
                class="cursor-pointer flex-1 text-center text-sm font-bold text-gray-200 bg-gray-800 rounded-lg py-2">+ Add task</div>` : ''}
            <div role="button" tabindex="0" onclick="pwaPlannerSnap()" data-planner-snap
                onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click()}"
                class="cursor-pointer flex-1 text-center text-sm font-bold text-gray-200 bg-gray-800 rounded-lg py-2">📷 Snap your planner</div>
        </div>
        ${pills}
        ${s.mode === 'month' ? pwaSchoolMonth(shown) : pwaSchoolAgenda(shown, today)}
        ${pwaSchoolClasses()}`;
}


// --- Adding, editing and deleting by hand (v2.499.252) ---------------------
// The child, on their own list, and a parent or adult looking at a child's
// list. Everybody else sees the list but not these doors (the server says
// the same: another child, a helper or a guest is refused). A task the
// school feed brought in keeps the school's title, date and class -- the
// next sync would put them back -- so those are shown but locked, and it
// cannot be deleted (checking it off is the gesture that sticks).
const SCHOOL_FIELD = 'w-full bg-gray-950 border border-gray-700 rounded-xl p-3 text-gray-100 text-[16px] focus:outline-none focus:border-blue-500 disabled:opacity-60';

function schoolCanWrite(owner) {
    return owner === selectedMemberId || ['parent', 'adult'].includes(currentMemberRole());
}

function schoolIsFeedTask(t) { return !!t && t.source === 'ics'; }

function schoolTomorrow() {
    const d = new Date(); d.setDate(d.getDate() + 1);
    return schoolLocalDate(d);
}

async function schoolClassesFor(owner) {
    if (pwaSchool && pwaSchool.owner === owner) return pwaSchool.classes || [];
    try {
        const r = await fetch(`${apiBase}api/kid-tasks/classes?member_id=${encodeURIComponent(owner)}`);
        return r.ok ? await r.json() : [];
    } catch (e) { return []; }
}

// One form for add and edit: `t` absent means a new task on `owner`'s list.
async function schoolTaskForm(owner, t) {
    const feed = schoolIsFeedTask(t);
    const lock = feed ? 'disabled' : '';
    const classes = await schoolClassesFor(owner);
    const kind = t ? t.kind : 'homework';
    const cls = t ? (t.course_key || '') : '';
    const overlay = _pwaModal(`
        <div class="text-gray-100 font-bold text-lg mb-1">${t ? 'Edit task' : 'Add a task'}</div>
        ${feed ? `<div class="text-gray-400 text-sm mb-3 leading-snug" data-feed-note>From the school feed: the title, date and class follow the school’s copy. The type and notes are yours.</div>` : '<div class="mb-3"></div>'}
        <div class="flex flex-col gap-2.5">
            <label class="flex flex-col gap-1"><span class="text-xs font-semibold text-gray-400">What</span>
                <input type="text" data-f-title maxlength="140" placeholder="Read chapter 4" ${lock} class="${SCHOOL_FIELD}"></label>
            <div class="flex gap-2">
                <label class="flex-1 flex flex-col gap-1 min-w-0"><span class="text-xs font-semibold text-gray-400">Due</span>
                    <input type="date" data-f-date ${lock} class="${SCHOOL_FIELD}"></label>
                <label class="flex-1 flex flex-col gap-1 min-w-0"><span class="text-xs font-semibold text-gray-400">By (optional)</span>
                    <input type="time" data-f-time ${lock} class="${SCHOOL_FIELD}"></label>
            </div>
            ${classes.length || cls ? `<label class="flex flex-col gap-1"><span class="text-xs font-semibold text-gray-400">Class</span>
                <select data-f-class ${lock} class="${SCHOOL_FIELD}">
                    <option value="">No class</option>
                    ${classes.map(c => `<option value="${mfEscape(c.key)}">${mfEscape(c.display || c.key)}</option>`).join('')}
                </select></label>` : ''}
            <label class="flex flex-col gap-1"><span class="text-xs font-semibold text-gray-400">Type</span>
                <select data-f-kind class="${SCHOOL_FIELD}">
                    ${SCHOOL_KINDS.map(([v, l]) => `<option value="${v}">${mfEscape(l)}</option>`).join('')}
                </select></label>
            <label class="flex flex-col gap-1"><span class="text-xs font-semibold text-gray-400">Notes (optional)</span>
                <textarea data-f-notes rows="2" class="${SCHOOL_FIELD} resize-none"></textarea></label>
        </div>
        <div class="flex gap-2 justify-end mt-4">
            <button data-no class="px-4 py-2 rounded-xl bg-gray-800 border border-gray-700 text-gray-200 text-sm font-bold">Cancel</button>
            <button data-yes class="px-4 py-2 rounded-xl bg-green-600 text-white text-sm font-bold">${t ? 'Save' : 'Add'}</button>
        </div>`, (overlay, close) => {
        overlay.querySelector('[data-no]').onclick = close;
        overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
        overlay.querySelector('[data-yes]').onclick = () => schoolTaskSave(owner, t, overlay, close);
    });
    // .value, never the attribute: titles and notes carry quotes.
    const q = s => overlay.querySelector(s);
    q('[data-f-title]').value = t ? (t.title || '') : '';
    q('[data-f-date]').value = t ? (t.due_date || '') : schoolTomorrow();
    q('[data-f-time]').value = t ? (t.due_time || '') : '';
    if (q('[data-f-class]')) q('[data-f-class]').value = cls;
    q('[data-f-kind]').value = SCHOOL_KINDS.some(([v]) => v === kind) ? kind : 'other';
    q('[data-f-notes]').value = t ? (t.notes || '') : '';
    if (!feed) q('[data-f-title]').focus();
    return overlay;
}

async function schoolTaskSave(owner, t, overlay, close) {
    const q = s => overlay.querySelector(s);
    const body = {
        member_id: owner, actor_id: selectedMemberId,
        title: q('[data-f-title]').value.trim(),
        due_date: q('[data-f-date]').value,
        due_time: q('[data-f-time]').value || null,
        course_key: q('[data-f-class]') ? (q('[data-f-class]').value || null) : (t ? t.course_key || null : null),
        kind: q('[data-f-kind]').value,
        notes: q('[data-f-notes]').value.trim(),
    };
    if (!body.title) return showGlobalAlert('Say what it is first.');
    if (!body.due_date) return showGlobalAlert('Pick the day it is due.');
    try {
        const r = await fetch(t ? `${apiBase}api/kid-tasks/${t.id}` : `${apiBase}api/kid-tasks`, {
            method: t ? 'PUT' : 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body)});
        const d = await r.json().catch(() => ({}));
        if (!r.ok) return showGlobalAlert(d.detail || 'Could not save it');
        schoolRemember(d);
    } catch (e) { return showGlobalAlert('Could not reach Chauffeur'); }
    close();
    if (pwaSchool) pwaSchoolLoad();
    else if (typeof refreshTodaySurfaces === 'function') refreshTodaySurfaces();
}

function pwaSchoolAdd() {
    if (!pwaSchool || !schoolCanWrite(pwaSchool.owner)) return;
    schoolTaskForm(pwaSchool.owner, null);
}

async function schoolTaskDelete(t) {
    const ok = await promptConfirm('Delete this task?', t.title, 'Delete', 'Keep');
    if (!ok) return;
    try {
        const r = await fetch(`${apiBase}api/kid-tasks/${t.id}?member_id=${encodeURIComponent(selectedMemberId || '')}`,
            {method: 'DELETE'});
        const d = await r.json().catch(() => ({}));
        if (!r.ok) return showGlobalAlert(d.detail || 'Could not delete it');
    } catch (e) { return showGlobalAlert('Could not reach Chauffeur'); }
    delete pwaSchoolTasks[t.id];
    if (pwaSchool) pwaSchoolLoad();
    else if (typeof refreshTodaySurfaces === 'function') refreshTodaySurfaces();
}

// --- Planner photo (K4d) ---------------------------------------------------
// A page of the paper planner -> proposed changes, reviewed before anything
// is saved. Any planner layout: the server's instructions describe none.
let pwaPlanner = null;   // {owner, page_dates, rows}

function pwaPlannerSnap() {
    if (!pwaSchool) return;
    const input = document.createElement('input');
    input.type = 'file'; input.accept = 'image/*';
    input.onchange = () => { if (input.files && input.files[0]) pwaPlannerUpload(input.files[0]); };
    input.click();
}

async function pwaPlannerUpload(file) {
    const owner = pwaSchool?.owner;
    if (!owner) return;
    showGlobalAlert('Reading your planner…');
    let data;
    try {
        const fd = new FormData();
        fd.append('photo', file);
        fd.append('owner_id', owner);
        fd.append('member_id', selectedMemberId || '');
        const r = await fetch(`${apiBase}api/kid-tasks/planner-photo`, {method: 'POST', body: fd});
        data = await r.json().catch(() => ({}));
        if (!r.ok || data.error) return showGlobalAlert(data.error || data.detail || 'Could not read that photo');
    } catch (e) { return showGlobalAlert('Could not read that photo'); }
    if (!(data.rows || []).length) return showGlobalAlert('Nothing on that page to add.');
    pwaPlanner = {owner, page_dates: data.page_dates, rows: data.rows.map((r, i) => ({...r, i,
        keep: r.action === 'new' || r.action === 'note',
        title: r.subject && !r.text.toLowerCase().includes(r.subject.toLowerCase()) ? `${r.subject}: ${r.text}` : r.text}))};
    pwaPlannerReview();
}

function schoolShortDate(iso) {
    return iso ? new Date(iso + 'T12:00:00').toLocaleDateString(undefined, {weekday: 'short', month: 'short', day: 'numeric'}) : '';
}

function pwaPlannerReview() {
    const P = pwaPlanner;
    if (!P) return;
    document.getElementById('pwa-planner-overlay')?.remove();
    const add = P.rows.filter(r => r.action === 'new' || r.action === 'needs_date');
    const notes = P.rows.filter(r => r.action === 'note');
    const same = P.rows.filter(r => r.action === 'already');
    const box = r => `<input type="checkbox" ${r.keep ? 'checked' : ''} data-keep="${r.i}" aria-label="Keep"
        class="w-6 h-6 rounded-lg accent-indigo-500 shrink-0 mt-1">`;
    const addRow = r => `
        <div class="rounded-lg bg-gray-800 px-2.5 py-2 flex items-start gap-2">
            ${box(r)}
            <div class="flex-1 min-w-0 flex flex-col gap-1.5">
                <input type="text" data-title="${r.i}" value="${mfEscape(r.title)}" aria-label="What"
                    class="w-full rounded-lg px-2 py-1 text-sm font-bold">
                <div class="flex flex-wrap items-center gap-1.5">
                    <input type="date" data-date="${r.i}" value="${r.date || ''}" aria-label="Due"
                        class="rounded-lg px-2 py-1 text-sm">
                    <span class="text-xs font-semibold text-gray-400">${SCHOOL_EMOJI[r.kind] || '📌'}${r.course_name ? ' · ' + mfEscape(r.course_name) : ''}</span>
                </div>
                ${r.details ? `<span class="text-xs text-gray-300">📒 ${mfEscape(r.details)}</span>` : ''}
                ${r.action === 'needs_date' && !r.date ? `<span class="text-xs text-amber-300" data-date-hint="${r.i}">Pick the day it is due</span>` : ''}
            </div>
        </div>`;
    const noteRow = r => `
        <div class="rounded-lg bg-gray-800 px-2.5 py-2 flex items-start gap-2">
            ${box(r)}
            <div class="flex-1 min-w-0">
                <div class="text-sm font-bold text-gray-100">${mfEscape(r.match.title)}</div>
                <div class="text-xs font-semibold text-gray-400">${mfEscape([r.match.course_name, schoolShortDate(r.match.due_date)].filter(Boolean).join(' · '))}</div>
                <div class="text-xs text-gray-300 mt-1">📒 ${mfEscape(r.note)}</div>
                ${r.conflict ? `<div class="text-xs text-amber-300 mt-1">Your planner says ${mfEscape(schoolShortDate(r.date))}; the school list says ${mfEscape(schoolShortDate(r.match.due_date))}</div>` : ''}
            </div>
        </div>`;
    const overlay = document.createElement('div');
    overlay.id = 'pwa-planner-overlay';
    overlay.className = 'pwa-sheet-overlay fixed inset-0 z-[400] bg-black/70 flex items-end sm:items-center justify-center p-4';
    overlay.innerHTML = `<div class="pwa-sheet w-full max-w-sm bg-gray-900 border border-gray-700 rounded-2xl shadow-2xl p-5 max-h-[85dvh] overflow-y-auto" role="dialog" aria-label="From your planner">
        <div class="text-gray-100 font-bold text-lg">From your planner</div>
        ${P.page_dates ? `<div class="text-xs font-semibold text-gray-400 mb-2">Read as ${mfEscape(P.page_dates)}</div>` : '<div class="mb-2"></div>'}
        ${add.length ? `<div class="text-xs font-black uppercase tracking-widest text-gray-500 mt-2 mb-1">Add to the list</div>
            <div class="flex flex-col gap-1.5">${add.map(addRow).join('')}</div>` : ''}
        ${notes.length ? `<div class="text-xs font-black uppercase tracking-widest text-gray-500 mt-3 mb-1">Add a note</div>
            <div class="flex flex-col gap-1.5">${notes.map(noteRow).join('')}</div>` : ''}
        ${same.length ? `<div class="text-xs font-black uppercase tracking-widest text-gray-500 mt-3 mb-1">Already on the list</div>
            <div class="flex flex-col gap-1">${same.map(r => `<div class="text-sm text-gray-400 px-1">✓ ${mfEscape(r.match.title)}${r.match.course_name ? ' · ' + mfEscape(r.match.course_name) : ''}</div>`).join('')}</div>` : ''}
        <div class="flex gap-2 justify-end mt-4">
            <button data-no class="px-4 py-2 rounded-xl bg-gray-800 border border-gray-700 text-gray-200 text-sm font-bold">Cancel</button>
            <button data-yes class="px-4 py-2 rounded-xl bg-green-600 text-white text-sm font-bold">Save</button>
        </div></div>`;
    document.body.appendChild(overlay);
    const close = () => { overlay.remove(); pwaPlanner = null; };
    overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
    overlay.querySelector('[data-no]').onclick = close;
    overlay.querySelectorAll('[data-keep]').forEach(cb => { cb.onchange = () => { P.rows[+cb.dataset.keep].keep = cb.checked; }; });
    overlay.querySelectorAll('[data-title]').forEach(el => { el.oninput = () => { P.rows[+el.dataset.title].title = el.value; }; });
    overlay.querySelectorAll('[data-date]').forEach(el => { el.onchange = () => {
        const r = P.rows[+el.dataset.date];
        r.date = el.value || null;
        overlay.querySelector(`[data-date-hint="${r.i}"]`)?.toggleAttribute('hidden', !!r.date);
        if (r.date && !r.keep) { r.keep = true; overlay.querySelector(`[data-keep="${r.i}"]`).checked = true; }
    }; });
    overlay.querySelector('[data-yes]').onclick = () => pwaPlannerSave(close);
}

async function pwaPlannerSave(close) {
    const P = pwaPlanner;
    if (!P) return;
    const rows = P.rows.filter(r => r.keep).map(r => r.action === 'note'
        ? {action: 'note', task_id: r.match.id, note: r.note}
        : {action: 'new', title: r.title, due_date: r.date, kind: r.kind,
           course_key: r.course_key || null, note: r.details || ''})
        .filter(r => r.action === 'note' || (r.title && r.due_date));
    const missing = P.rows.filter(r => r.keep && r.action !== 'note' && !r.date).length;
    if (missing) return showGlobalAlert(`Pick a day for ${missing} item${missing === 1 ? '' : 's'}, or untick ${missing === 1 ? 'it' : 'them'}.`);
    try {
        const r = await fetch(`${apiBase}api/kid-tasks/planner-apply`, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({owner_id: P.owner, member_id: selectedMemberId, rows})});
        const d = await r.json().catch(() => ({}));
        if (!r.ok) return showGlobalAlert(d.detail || 'Could not save');
        close();
        const bits = [d.added ? `${d.added} added` : '', d.noted ? `${d.noted} note${d.noted === 1 ? '' : 's'}` : ''].filter(Boolean);
        showGlobalAlert(bits.length ? `From your planner: ${bits.join(', ')} ✅` : 'Nothing new to save');
    } catch (e) { return showGlobalAlert('Could not save'); }
    if (pwaSchool) pwaSchoolLoad();
}

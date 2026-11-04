// Pure words for the adult drive screen, from the sheet and its day row.
function pwaDriveView(sheet, ctx = {}) {
    const row = ctx.row || {};
    const place = sheet ? sheet.destination?.label || ctx.legTitle || ctx.destination || ''
        : ctx.destination || ctx.legTitle || row.place || '';
    if (!sheet) return {leave:null, stops:[{place}], arrival:{place, eta:'', sub:''}, cover:false, late:false};

    const arrive = pwaClock(sheet.arrive_by?.arrive_at, ctx)
        || String(sheet.arrive_by?.short_label || '').replace(/^Arrive\s+/i, '').trim()
        || pwaClock(row.end, ctx);
    const duration = /\b(?:(\d+)\s*h(?:ours?)?\s*)?(?:(\d+(?:\.\d+)?)\s*m(?:in(?:s|utes)?)?\s*)?drive\b/i.exec(row.meta || '');
    const minutesDrive = duration && (duration[1] || duration[2])
        ? Number(duration[1] || 0) * 60 + Number(duration[2] || 0) : null;
    const etaMs = sheet.eta_ts != null && Number.isFinite(sheet.eta_ts) ? sheet.eta_ts * 1000 : NaN;
    const arrivalMs = Number.isFinite(etaMs) ? etaMs : new Date(row.end).getTime();
    const arriveByMs = new Date(sheet.arrive_by?.arrive_at).getTime();
    const late = Number.isFinite(arrivalMs) && Number.isFinite(arriveByMs) && arrivalMs > arriveByMs;
    const arriveBy = sheet.arrive_by && arrive ? `${late ? '⚠ ' : ''}Arrive by ${arrive}` : '';
    const car = sheet.car || {};
    const carLine = [car.name, Number.isFinite(car.range) ? `${Math.round(car.range)} ${car.range_unit || 'mi'} range` : ''].filter(Boolean).join(', ');
    const leaveTime = pwaClock(row.start, ctx);
    const leave = leaveTime ? {time:leaveTime, sub:[
        minutesDrive !== null ? `${minutesDrive} min drive` : '', arrive ? `${late ? '⚠ ' : ''}arrive ${arrive}` : '',
        carLine, car.warn ? `⚠ ${car.warn}` : ''
    ].filter(Boolean).join(' · ')} : null;

    const passengers = sheet.passengers || [];
    const firstName = passenger => String(passenger.name || '').trim().split(/\s+/)[0];
    const names = passengers.map(firstName).filter(Boolean).join(', ');
    const aboard = passengers.filter(passenger => passenger.aboard === true);
    const aboardNames = aboard.map(firstName).filter(Boolean).join(', ');
    const items = (sheet.prep?.items || []).filter(Boolean).join(', ');
    const address = String(sheet.destination?.address || '').trim();
    const reason = sheet.arrive_by?.reason || '';
    const stops = [
        {place:ctx.origin || 'Home', sub:[names ? `Pick up ${names}` : '', items].filter(Boolean).join(' · '),
            done:aboard.length > 0},
        {place, sub:[arrive ? `${late ? '⚠ ' : ''}Arrive by ${arrive}` : '', reason, address].filter(Boolean).join(' · '), done:false}
    ];

    const minutes = ctx.now == null ? NaN : Math.round((etaMs - new Date(ctx.now).getTime()) / 60000);
    const arrival = {place, eta:pwaClock(etaMs, ctx) || sheet.eta_label || '', arriveBy,
        detail:[reason, address].filter(Boolean).join(' · '), sub:[
        Number.isFinite(minutes) ? minutes <= 0 ? 'arriving now' : `${minutes} min` : '', aboardNames ? `${aboardNames} aboard` : ''
    ].filter(Boolean).join(' · ')};
    if (car.warn) arrival.car = [carLine, `⚠ ${car.warn}`].filter(Boolean).join(' · ');
    return {leave, stops, arrival, cover:row.kind === 'drive' && sheet.status !== 'in_progress', late};
}

// Adopt the existing sheet, like the Messages thread. Keep a reference:
// PwaNav detaches its section before calling onPop.
function pwaDriveOpen() {
    if (!window.PwaNav) return;
    const content = document.getElementById('action-sheet-content');
    pwaDriveOpen.node = content;
    if (!pwaDriveOpen.buttons) pwaDriveOpen.buttons = new Map(
        Array.from(content.querySelectorAll('button[id]')).map(button => [button.id, button.innerHTML]));
    pwaDrivePlaceChecks();
    const title = routeContext.legTitle || 'Your drive';
    if (window.PwaNav.current()?.id === 'drive') {
        window.PwaNav.current().title = title;
        content.closest('.pwa-screen').querySelector('h1').textContent = title;
        content.closest('.pwa-screen').scrollTop = 0;
    } else {
        window.PwaNav.push({id:'drive', title,
            render(body) { body.append(content); },
            onPop() { pwaDriveRestore(); }});
    }
    content.classList.remove('translate-y-full');
    pwaRenderDriveCards();
}

function pwaDriveRestore() {
    const ownsLane = !!driveLiveContext?.legId && driveLiveContext.legId === routeContext?.legId;
    const keepLive = ownsLane && pwaDriveOpen.clearing
        && (driveSheetData?.status === 'in_progress'
            || (scheduleData?.in_progress_drives || []).includes(routeContext.legId))
        && !(scheduleData?.completed_drives || []).includes(routeContext.legId);
    const content = pwaDriveOpen.node || document.getElementById('action-sheet-content');
    const sheet = document.getElementById('action-sheet');
    // Return first, so all cleanup can resolve the same ids as before.
    sheet.append(content);
    const before = document.getElementById('sheet-state-1');
    content.insertBefore(document.getElementById('drive-roll'), before);
    content.insertBefore(document.getElementById('drive-prep'), before);
    if (keepLive) rememberDriveSheet();
    else {
        if (ownsLane || !driveLiveContext) stopDriveLive(true);
        forgetDriveSheet(routeContext?.legId);
    }
    sheet.classList.add('hidden', 'opacity-0');
    sheet.style.display = 'none';
    content.classList.add('translate-y-full');
    for (const [id, html] of pwaDriveOpen.buttons || []) {
        const button = document.getElementById(id);
        if (button) { button.disabled = false; button.innerHTML = html; }
    }
    routeContext = null;
    driveSheetData = null;
    pwaDriveOpen.node = null;
}

function pwaDrivePlaceChecks() {
    if (!pwaIsAdult() || !window.PwaNav) return;
    const road = !document.getElementById('sheet-state-2').classList.contains('hidden');
    const button = document.getElementById(road ? 'btn-arrived' : 'btn-start-drive');
    button.before(document.getElementById('drive-roll'), document.getElementById('drive-prep'));
}

function pwaDriveContextRow() {
    const legId = routeContext?.legId;
    return legId ? pwaRowsFromDom(document).find(row => row.kind === 'drive' && row.legId === legId) || null : null;
}

function pwaRenderDriveCards() {
    if (!pwaIsAdult() || !routeContext) return;
    const row = pwaDriveContextRow();
    const view = pwaDriveView(driveSheetData, {...routeContext, row, now:new Date(), use24h:!!use24h});
    const leave = document.getElementById('drive-leave-card');
    leave.hidden = !view.leave;
    leave.classList.toggle('pwa-drive-late', view.late);
    leave.innerHTML = view.leave ? `<div class="k">Leave at</div>
        <div class="pwa-drive-time">${mfEscape(view.leave.time)}</div>
        <div class="pwa-drive-sub">${mfEscape(view.leave.sub)}</div>` : '';
    document.querySelector('.pwa-drive-stops').innerHTML = view.stops.map(stop =>
        `<div class="pwa-drive-stop${stop.done ? ' done' : ''}"><span class="pwa-drive-dot" aria-hidden="true"></span>
        <div><div class="pwa-drive-place">${mfEscape(stop.place)}</div>
        <div class="pwa-drive-sub">${mfEscape(stop.sub || '')}</div></div></div>`).join('');
    document.getElementById('drive-arrival-card').innerHTML = `<div class="k">On the way · ${mfEscape(view.arrival.place)}</div>
        <div class="pwa-drive-eta">${mfEscape(view.arrival.eta)}</div>
        <div class="pwa-drive-sub">${mfEscape(view.arrival.sub)}</div>
        ${view.arrival.arriveBy ? `<div class="pwa-drive-arrive-by${view.late ? ' pwa-drive-late' : ''}">${mfEscape(view.arrival.arriveBy)}</div>` : ''}
        ${view.arrival.detail ? `<div class="pwa-drive-sub">${mfEscape(view.arrival.detail)}</div>` : ''}
        ${view.arrival.car ? `<div class="pwa-drive-arrive-by pwa-drive-late">${mfEscape(view.arrival.car)}</div>` : ''}`;
    document.getElementById('btn-drive-cover').classList.toggle('hidden', !view.cover || !row?.secondary);
}

function pwaDriveCover() {
    const row = pwaDriveContextRow();
    if (row?.secondary) new Function(row.secondary)();
}

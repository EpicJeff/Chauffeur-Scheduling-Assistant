// Pure data for the Plan tab; departures come only from the stamped legs.
function pwaPlanDay(value) {
    return pwaLocalDay(value);
}

function pwaPlanGeometry(rows, opts = {}) {
    const hourPx = opts.hourPx ?? 66;
    const clock = new Date(opts.now);
    const day = new Date(opts.date + 'T00:00:00');
    if (!Number.isFinite(day.getTime()) || pwaPlanDay(day) !== opts.date)
        return {hours:[], blocks:[], strips:[], allDay:[], now:null};
    // Use wall-clock minutes even across a daylight-saving change.
    const dayNumber = date => Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / 86400000;
    const minutes = date => (dayNumber(date) - dayNumber(day)) * 1440
        + date.getHours() * 60 + date.getMinutes() + date.getSeconds() / 60;
    const allDay = [], timed = [];
    for (const row of rows || []) {
        if (row.allDay) {
            allDay.push(row);
            continue;
        }
        if (row.start == null || row.start === '' || row.end == null || row.end === '') continue;
        const start = new Date(row.start), end = new Date(row.end);
        if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || end < start) continue;
        if (minutes(end) < 0 || minutes(start) >= 1440) continue;
        timed.push({row, start:Math.max(0, minutes(start)), end:Math.min(1440, minutes(end)), endTime:end.getTime()});
    }
    const strips = (opts.strips || []).flatMap(strip => {
        const item = strip;
        if (item.start == null || item.end == null) return [];
        const start = new Date(item.start), end = new Date(item.end);
        if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || end < start
            || minutes(end) < 0 || minutes(start) >= 1440) return [];
        return [{strip, start:Math.max(0, minutes(start)), end:Math.min(1440, minutes(end))}];
    });
    const rangeItems = timed.concat(strips);
    for (const item of rangeItems) item.drawnEnd = Math.min(1440, Math.max(item.end, item.start + 22 * 60 / hourPx));
    const rangeStart = Math.max(0, Math.min(8, ...rangeItems.map(item => Math.floor(item.start / 60) - 1)));
    const rangeEnd = Math.min(24, Math.max(19, ...rangeItems.map(item => Math.ceil(item.end / 60) + 1)));
    const hours = [];
    for (let h = rangeStart; h < rangeEnd; h++) {
        const time = new Date(2000, 0, 1, h);
        hours.push({h, label:opts.use24h ? pwaClock(time, opts) : pwaClockSuffix(time, opts).replace(':00', '')});
    }

    // Blocks and leave strips share lanes over their actual drawn extents.
    let group = [], laneEnds = [], groupEnd = -Infinity;
    const finishGroup = () => {
        for (const item of group) item.lanes = laneEnds.length;
        group = [];
        laneEnds = [];
        groupEnd = -Infinity;
    };
    for (const item of rangeItems.slice().sort((a, b) => a.start - b.start || a.drawnEnd - b.drawnEnd)) {
        if (item.start >= groupEnd) finishGroup();
        let lane = laneEnds.findIndex(end => end <= item.start);
        if (lane < 0) lane = laneEnds.length;
        laneEnds[lane] = item.drawnEnd;
        item.lane = lane;
        group.push(item);
        groupEnd = Math.max(groupEnd, item.drawnEnd);
    }
    finishGroup();
    const placement = item => ({
        top:(item.start - rangeStart * 60) * hourPx / 60,
        height:(item.drawnEnd - item.start) * hourPx / 60, lane:item.lane, lanes:item.lanes});
    return {hours, blocks:timed.map(item => ({row:item.row, ...placement(item),
        color:item.row.color, dim:item.endTime < clock.getTime()})),
        strips:strips.map(item => ({...item.strip, ...placement(item)})), allDay,
        now:pwaPlanDay(clock) === opts.date && minutes(clock) >= rangeStart * 60 && minutes(clock) <= rangeEnd * 60
            ? {top:(minutes(clock) - rangeStart * 60) * hourPx / 60} : null};
}

function pwaLeaveStrips(sched = {}, dateStr, opts = {}) {
    if (opts.keepingUp) return [];
    const drivers = opts.drivers || sched.drivers || [];
    const passengers = opts.passengers || sched.passengers || [];
    const events = [...(opts.events || sched.events || []), ...(sched.scheduled_errands || [])];
    const first = name => String(name || '').trim().split(/\s+/)[0];
    const strips = [];
    for (const mapName of ['initial_edges', 'route_edges', 'final_edges']) {
        for (const [driverId, byEvent] of Object.entries(sched[mapName] || {})) {
            if (driverId.startsWith('ghost_')) continue;
            const driver = drivers.find(d => d.id === driverId) || {};
            for (const [fromEventId, edge] of Object.entries(byEvent || {})) {
                let departure = null;
                const finish = () => {
                    if (!departure || pwaPlanDay(departure.start) !== dateStr) return;
                    const {start, end, eventId, subject, origin, destination} = departure;
                    const who = first(driver.name) || 'a driver';
                    strips.push({start, end, driverId, eventId, color:driver.color_code || null,
                        label:`🚗 Leave ${pwaClock(start, opts)} · ${who} ${origin === 'event' && destination === 'home' ? 'heads home' : 'drives ' + subject}`});
                };
                for (const leg of edge?.legs || []) {
                    if (!leg.depart) continue;
                    const start = new Date(leg.depart).getTime(), mins = Number(leg.mins);
                    if (!Number.isFinite(start) || !Number.isFinite(mins) || mins < 0) continue;
                    if (['pickup', 'dropoff'].includes(leg.from)) {
                        if (departure) {
                            departure.end = start + mins * 60000;
                            departure.destination = leg.to;
                        }
                        continue;
                    }
                    if (!['home', 'event'].includes(leg.from)) continue;
                    finish();
                    // On a home layover the first leg leaves the old event;
                    // the outbound leg carries the next event's passengers.
                    const eventId = mapName === 'route_edges' && leg.to !== 'home'
                        ? edge.to_event || fromEventId : fromEventId;
                    const event = events.find(e => e.id === eventId)
                        || events.find(e => e.id === eventId.replace(/_(dropoff|pickup)$/, '')) || {};
                    const names = passengers.filter(p => (p.calendar_ids || []).some(id => (event.calendar_ids || []).includes(id)))
                        .map(p => first(p.name)).filter(Boolean);
                    const subject = names.length ? names.join(' and ') : event.title || 'a drive';
                    departure = {start, end:start + mins * 60000, eventId, subject, origin:leg.from, destination:leg.to};
                }
                finish();
            }
        }
    }
    return strips.sort((a, b) => a.start - b.start);
}

function pwaPlanLead(rows = [], strips = [], date, now) {
    const prefix = `${date === pwaPlanDay(now) ? 'Today' : pwaWeekday(date)} is `;
    const events = rows.filter(row => !row.allDay && row.kind !== 'drive').length;
    const drives = strips.length;
    const parts = [];
    if (drives) parts.push(`${pwaNumberWord(drives)} ${drives === 1 ? 'drive' : 'drives'}`);
    if (events) parts.push(`${pwaNumberWord(events)} ${events === 1 ? 'event' : 'events'}`);
    if (!parts.length) {
        const count = rows.filter(row => row.allDay).length;
        if (count) parts.push(`${pwaNumberWord(count)} all-day ${count === 1 ? 'thing' : 'things'}`);
    }
    return prefix + (parts.join(' and ') || 'quiet') + '.';
}

function pwaWeekStrip(dates, opts = {}) {
    const weather = new Map((opts.weather || []).map(day => [day.date, day.emoji]));
    return (dates || []).map(date => {
        const day = new Date(date + 'T12:00:00');
        return {date, letter:pwaWeekday(date)[0], day:String(day.getDate()),
            today:date === opts.today, selected:date === opts.selected, emoji:weather.get(date) || null,
            count:opts.counts?.[date] || 0, proposed:!!opts.proposalDates?.has(date)};
    });
}

function pwaPeopleChips(members, sched = {}) {
    const chips = [{id:'everyone', name:'Everyone', color:null, cal:[], driverId:null}];
    for (const member of members || []) {
        if (!['parent', 'adult', 'child'].includes(member.role) || (member.status && member.status !== 'active')) continue;
        const full = String(member.name || '').trim(), name = full.split(/\s+/)[0];
        const passenger = (sched.passengers || []).find(p => p.id === member.passenger_id);
        const cal = new Set(passenger?.calendar_ids || []);
        for (const [id, meta] of Object.entries(sched.calendar_metadata || {})) {
            const summary = String(meta?.summary || '').trim().toLowerCase();
            if (summary && summary !== 'family' && [full.toLowerCase(), name.toLowerCase()].includes(summary)) cal.add(id);
        }
        chips.push({id:member.id, name, color:member.color_code, cal:[...cal], driverId:member.driver_id || null});
    }
    return chips;
}

function pwaPlanFilter(rows, chip, chips) {
    if (!chip || chip === 'everyone' || chip.id === 'everyone') return rows;
    const claimedCalendars = new Set((chips || []).flatMap(person => person.cal || []));
    const claimedDrivers = new Set((chips || []).map(person => person.driverId).filter(Boolean));
    return (rows || []).filter(row => {
        const cal = row.cal || [], drivers = row.drivers || [];
        const unresolved = chips ? !cal.some(id => claimedCalendars.has(id)) && !drivers.some(id => claimedDrivers.has(id))
            : !cal.length && !drivers.length;
        return unresolved || cal.some(id => (chip.cal || []).includes(id))
            || (!!chip.driverId && drivers.includes(chip.driverId));
    });
}

let pwaPlanChip = 'everyone';
let pwaPlanForecast = {start:'', at:0, rows:[], load:null};
let pwaPlanTick = null;
let pwaPlanAutoScroll = false;
let pwaPlanAutoScrollSuppressed = false;
let pwaPlanScrollGeneration = 0;

function pwaPlanSuppressAutoScroll() {
    pwaPlanAutoScroll = false;
    pwaPlanAutoScrollSuppressed = true;
    pwaPlanScrollGeneration++;
}

function pwaPlanSync() {
    if (pwaIsAdult() && currentView === 'family') {
        if (pwaPlanTick === null) {
            pwaPlanAutoScroll = !pwaPlanAutoScrollSuppressed;
            pwaPlanTick = setInterval(() => { if (!document.hidden) pwaRefreshPlan(); }, 60000);
        }
    } else {
        if (pwaPlanTick !== null) clearInterval(pwaPlanTick);
        pwaPlanTick = null;
        pwaPlanAutoScroll = false;
    }
    pwaPlanAutoScrollSuppressed = false;
}

function pwaRefreshPlan() {
    if (!pwaIsAdult() || currentView !== 'family') return;
    document.querySelectorAll('#days-container > [id^="pane-"]').forEach(pwaRenderPlanDay);
    pwaRenderPlan();
}

function pwaPlanScrollToNow() {
    if (!pwaPlanAutoScroll || !pwaIsAdult() || currentView !== 'family') return;
    if (currentDates[activeDateIndex] !== todayStr()) { pwaPlanAutoScroll = false; return; }
    const pane = document.getElementById(`pane-${activeDateIndex}`);
    const target = pane?.querySelector('.pwa-now') || pane?.querySelector('.pwa-ev:not(.dim)');
    pwaPlanAutoScroll = false;
    if (!target) return;
    const generation = pwaPlanScrollGeneration;
    requestAnimationFrame(() => {
        if (generation !== pwaPlanScrollGeneration || !pane.isConnected || currentView !== 'family'
            || currentDates[activeDateIndex] !== todayStr()) return;
        pane.scrollTop = Math.max(0, pane.scrollTop + target.getBoundingClientRect().top - pane.getBoundingClientRect().top - 32);
    });
}

function pwaPlanWindow() {
    const from = Math.max(0, Math.min(activeDateIndex - 3, currentDates.length - 7));
    return {from, dates:currentDates.slice(from, from + 7)};
}

function pwaPlanProposalDate(proposal) {
    // The intake editor's date field already reflects local time and edits.
    if (/^\d{4}-\d{2}-\d{2}$/.test(String(proposal._date || ''))) return proposal._date;
    const start = String(proposal.start || '');
    if (!/^\d{4}-\d{2}-\d{2}(?:T|$)/.test(start)) return '';
    return proposal.all_day ? start.slice(0, 10) : pwaLocalDay(start);
}

function pwaPlanRows(pane) {
    const host = pane?.querySelector('.pwa-plan-rows');
    if (!host) return [];
    const elements = [...host.querySelectorAll('[data-kind]')].filter(el => PWA_DAY_KIND_ORDER.includes(el.dataset.kind));
    const ids = value => String(value || '').split(',').map(id => id.trim()).filter(Boolean);
    return pwaRowsFromDom(host).map((row, i) => ({...row, color:elements[i].dataset.color || '#3B82F6',
        cal:ids(elements[i].dataset.cal), drivers:ids(elements[i].dataset.drivers)}));
}

function pwaPlanStrips(date) {
    const sched = scheduleData || {};
    return pwaLeaveStrips(sched, date, {drivers:sched.drivers || driversData, passengers:sched.passengers,
        events:sched.events, calendar_metadata:sched.calendar_metadata, use24h, keepingUp:isKeepingUpAdult()});
}

async function pwaPlanWeather() {
    const start = pwaPlanWindow().dates[0];
    if (!start) return [];
    if (pwaPlanForecast.start === start && pwaPlanForecast.at && Date.now() - pwaPlanForecast.at < 600000)
        return pwaPlanForecast.rows;
    if (pwaPlanForecast.start === start && pwaPlanForecast.load) return pwaPlanForecast.load;
    const cache = {start, at:0, rows:[], load:null};
    pwaPlanForecast = cache;
    cache.load = (async () => {
        try {
            const res = await fetch(`${apiBase}api/weather/daily?days=7&start=${encodeURIComponent(start)}`);
            const rows = res.ok ? await res.json() : [];
            cache.rows = Array.isArray(rows) ? rows : [];
        } catch (e) { cache.rows = []; }
        cache.at = Date.now();
        cache.load = null;
        if (pwaPlanForecast === cache) pwaRenderPlan();
        return cache.rows;
    })();
    return cache.load;
}

function pwaRenderPlan() {
    if (!pwaIsAdult() || currentView !== 'family') return;
    const head = document.getElementById('plan-head');
    if (!head || !currentDates.length) return;
    const date = currentDates[activeDateIndex], now = new Date();
    const {from, dates} = pwaPlanWindow();
    const chips = pwaPeopleChips(membersData, scheduleData || {});
    if (!chips.some(chip => chip.id === pwaPlanChip)) pwaPlanChip = 'everyone';
    const counts = Object.fromEntries(dates.map((date, i) => [date,
        pwaPlanRows(document.getElementById(`pane-${from + i}`)).filter(row => !row.allDay && row.kind !== 'drive').length]));
    const week = pwaWeekStrip(dates, {counts,
        weather:pwaPlanForecast.start === dates[0] ? pwaPlanForecast.rows : [],
        proposalDates:new Set((proposalsData || []).map(pwaPlanProposalDate).filter(Boolean)),
        today:todayStr(), selected:date});
    const rows = pwaPlanRows(document.getElementById(`pane-${activeDateIndex}`));
    const peopleScroll = head.querySelector('.pwa-people')?.scrollLeft || 0;
    const focused = head.contains(document.activeElement) ? document.activeElement : null;
    const focusedChip = focused?.dataset.chip, focusedDay = focused?.dataset.i;
    const focusedToday = focused?.classList.contains('pwa-plan-today');
    const dayLabel = day => `${pwaWeekday(day.date)}, ${new Date(day.date + 'T12:00:00').toLocaleDateString('en-US', {month:'long', day:'numeric'})}, ${day.count ? day.count + (day.count === 1 ? ' event' : ' events') : 'no events'}${day.proposed ? ', proposed' : ''}`;
    head.innerHTML = `<h1 class="pwa-plan-title">Plan${date === todayStr() ? '' : ' <button type="button" class="pwa-plan-today" onclick="pwaPlanToday()">Today</button>'}</h1>
        <p class="pwa-plan-lead">${mfEscape(pwaPlanLead(rows, pwaPlanStrips(date), date, now))}</p>
        <div class="pwa-people" aria-label="Filter the plan by person">${chips.map(chip => `<button type="button" class="pwa-pp${chip.id === pwaPlanChip ? ' on' : ''}" data-chip="${mfEscape(chip.id)}" aria-pressed="${chip.id === pwaPlanChip}" onclick="${mfEscape(`pwaPlanSelectChip(${JSON.stringify(chip.id)})`)}"><i aria-hidden="true" style="background:${mfEscape(chip.color || 'var(--pwa-accent)')}"></i>${mfEscape(chip.name)}</button>`).join('')}</div>
        <div class="pwa-week" aria-label="Plan days">${week.map((day, i) => `<button type="button" class="pwa-week-day${day.selected ? ' on' : ''}" data-i="${from + i}" aria-pressed="${day.selected}" aria-label="${mfEscape(dayLabel(day))}" onclick="pwaSelectDay(${from + i})">${mfEscape(day.letter)}<b>${mfEscape(day.day)}</b>${day.emoji ? `<span class="w">${mfEscape(day.emoji)}</span>` : ''}${day.count ? `<span class="cnt">${day.count}</span>` : ''}${day.proposed ? '<span class="proposed" aria-label="Proposed event"></span>' : ''}</button>`).join('')}</div>`;
    head.querySelector('.pwa-people').scrollLeft = peopleScroll;
    if (focused) {
        const replacement = focusedChip != null ? [...head.querySelectorAll('[data-chip]')].find(el => el.dataset.chip === focusedChip)
            : focusedDay != null ? [...head.querySelectorAll('[data-i]')].find(el => el.dataset.i === focusedDay)
            : focusedToday ? head.querySelector('.pwa-plan-today') : null;
        (replacement || head.querySelector('.pwa-week-day[aria-pressed="true"]'))?.focus({preventScroll:true});
    }
    pwaPlanScrollToNow();
    void pwaPlanWeather();
}

function pwaRenderPlanDay(pane) {
    if (!pwaIsAdult() || currentView !== 'family' || !pane
        || pane.parentElement !== document.getElementById('days-container') || !/^pane-\d+$/.test(pane.id)) return;
    const events = pane.querySelector('#pane-events');
    if (!events || !events.querySelector('.pwa-plan-rows')) return;
    const date = currentDates[Number(pane.id.replace('pane-', ''))];
    const rows = pwaPlanRows(pane), chips = pwaPeopleChips(membersData, scheduleData || {});
    const chip = chips.find(c => c.id === pwaPlanChip);
    const strips = pwaPlanStrips(date);
    const now = new Date(), opts = {date, now, hourPx:66, use24h, strips};
    const geometry = pwaPlanGeometry(pwaPlanFilter(rows, chip, chips), opts);
    events.querySelectorAll('.pwa-plan-allday, .pwa-tl').forEach(el => el.remove());
    const band = document.createElement('div'); band.className = 'pwa-plan-allday';
    // Execute only the handler emitted by the owning row builder, like HeroCard.
    const action = (row, cls) => {
        const button = document.createElement('button'); button.type = 'button'; button.className = cls;
        button.onclick = () => { if (row.primary) new Function(row.primary)(); };
        return button;
    };
    for (const row of geometry.allDay) {
        const button = action(row, 'pwa-band-item'); button.textContent = row.title; band.append(button);
    }
    const timeline = document.createElement('div'); timeline.className = 'pwa-tl';
    const track = document.createElement('div'); track.className = 'pwa-plan-track';
    for (const hour of geometry.hours) {
        const line = document.createElement('div'); line.className = 'pwa-hr'; line.dataset.h = hour.h;
        const label = document.createElement('span'); label.textContent = hour.label; line.append(label); track.append(line);
    }
    for (const block of geometry.blocks) {
        const row = block.row, button = action(row, 'pwa-ev' + (block.dim ? ' dim' : ''));
        button.style.top = block.top + 'px'; button.style.height = block.height + 'px';
        button.style.left = `calc(${block.lane} / ${block.lanes} * 100%)`;
        button.style.width = `calc(100% / ${block.lanes} - 4px)`;
        button.style.background = block.color;
        const channels = button.style.backgroundColor.match(/[\d.]+/g)?.slice(0, 3).map(Number) || [];
        const luminance = rgb => rgb.map(c => c / 255).map(c => c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4)
            .reduce((sum, c, i) => sum + c * [.2126, .7152, .0722][i], 0);
        const lightness = luminance(channels);
        button.dataset.ink = channels.length === 3 && (lightness + .05) / (luminance([31, 29, 43]) + .05) > 1.05 / (lightness + .05)
            ? 'dark' : 'light';
        button.setAttribute('aria-label', `${row.title} ${pwaClockSuffix(row.start, opts)} – ${pwaClockSuffix(row.end, opts)}`);
        const title = document.createElement('span'); title.textContent = row.title;
        const meta = document.createElement('small'); meta.textContent = row.meta.split(' · ')[0];
        button.append(title, meta); track.append(button);
    }
    for (const strip of geometry.strips) {
        const line = document.createElement('div'); line.className = 'pwa-leave';
        line.style.top = strip.top + 'px'; line.style.height = strip.height + 'px';
        line.style.left = `calc(${strip.lane} / ${strip.lanes} * 100%)`;
        line.style.width = `calc(100% / ${strip.lanes} - 4px)`;
        line.style.setProperty('--pwa-driver-color', strip.color || 'var(--pwa-accent)');
        line.title = strip.label; line.setAttribute('aria-label', strip.label);
        line.textContent = strip.label; track.append(line);
    }
    if (geometry.now) {
        const line = document.createElement('div'); line.className = 'pwa-now'; line.style.top = geometry.now.top + 'px';
        const label = document.createElement('span'); label.textContent = pwaClock(now, opts); line.append(label); track.append(line);
    }
    timeline.append(track); events.append(band, timeline);
}

function pwaPlanSelectChip(id) {
    pwaPlanChip = id;
    document.querySelectorAll('#days-container > [id^="pane-"]').forEach(pwaRenderPlanDay);
    pwaRenderPlan();
}

function pwaPlanToday() {
    reanchorIfDayChanged();
    if (!currentDates.includes(todayStr())) buildTimeline();
    pwaPlanAutoScroll = true;
    pwaSelectDay(currentDates.indexOf(todayStr()));
}

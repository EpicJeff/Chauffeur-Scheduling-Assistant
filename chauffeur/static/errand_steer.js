// One steering flow for the Errands page and My Day; hosts own writes and refreshes.
(function () {
    const STEER_WINDOWS = {
        morning: ['08:00', '12:00'], midday: ['11:00', '14:00'],
        afternoon: ['14:00', '17:00'], evening: ['17:00', '20:00'],
    };

    function dayChoices(days = 14) {
        const out = [];
        const d = new Date(); d.setHours(0, 0, 0, 0);
        for (let i = 0; i < days; i++) {
            const x = new Date(d); x.setDate(d.getDate() + i);
            const iso = `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`;
            out.push({ value: iso, label: x.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' }) });
        }
        return out;
    }

    function windowChoices() {
        return Object.keys(STEER_WINDOWS).map(k => ({ value: k,
            label: `${k[0].toUpperCase()}${k.slice(1)} (${STEER_WINDOWS[k][0]}–${STEER_WINDOWS[k][1]})` }));
    }

    async function steer(row, host) {
        const e = row;
        const scheduledDay = e.placement ? String(e.placement.start_time).slice(0, 10) : null;
        const msg = (e.placement && e.placement.why && e.placement.why.text) || (e.unplaced && e.unplaced.text) || '';
        const opts = [];
        if (scheduledDay) opts.push({ value: 'skip_today', label: 'Not this day' });
        opts.push({ value: 'skip_day', label: 'Skip a day…' });
        opts.push({ value: 'pin_day', label: 'Pick a day' });
        opts.push({ value: 'pin_time', label: 'Pick a time' });
        opts.push({ value: 'driver', label: 'Someone else' });
        if ((e.skip_dates || []).length || e.pinned_date || e.pinned_start || e.pinned_end || e.once_driver_id) {
            opts.push({ value: 'auto', label: 'Back to automatic' });
        }
        const pick = await host.promptChoice(e.title, msg, opts);
        if (!pick) return;
        if (pick === 'skip_today' || pick === 'skip_day') {
            const day = pick === 'skip_today' ? scheduledDay : await host.promptChoice('Skip which day?', '', dayChoices());
            if (!day) return;
            const patch = { skip_dates: Array.from(new Set([...(e.skip_dates || []), day])) };
            if (day === e.pinned_date) Object.assign(patch, { pinned_date: null, pinned_start: null, pinned_end: null });
            return host.putErrand(e.id, patch);
        }
        if (pick === 'pin_day') {
            const day = await host.promptChoice('Which day?', '', dayChoices());
            if (!day) return;
            return host.putErrand(e.id, { pinned_date: day });
        }
        if (pick === 'pin_time') {
            const today = dayChoices(1)[0].value;
            let day = e.pinned_date && e.pinned_date >= today ? e.pinned_date : scheduledDay;
            if (!day || day < today) {
                day = await host.promptChoice('Which day?', 'Pick the day first.', dayChoices());
                if (!day) return;
            }
            const w = await host.promptChoice('When that day?', '', windowChoices());
            if (!w) return;
            return host.putErrand(e.id, { pinned_date: day, pinned_start: STEER_WINDOWS[w][0], pinned_end: STEER_WINDOWS[w][1] });
        }
        if (pick === 'driver') {
            const ds = (await host.fetchDrivers()).filter(d => !d.is_disabled).map(d => ({ value: d.id, label: d.name }));
            if (!ds.length) { host.showGlobalAlert('No drivers to choose from.'); return; }
            const d = await host.promptChoice('Who runs it this time?', '', ds);
            if (!d) return;
            return host.putErrand(e.id, { once_driver_id: d });
        }
        if (pick === 'auto') {
            return host.putErrand(e.id, { skip_dates: [], pinned_date: null, pinned_start: null, pinned_end: null, once_driver_id: null });
        }
    }

    window.ChfErrandSteer = { STEER_WINDOWS, dayChoices, windowChoices, steer };
})();

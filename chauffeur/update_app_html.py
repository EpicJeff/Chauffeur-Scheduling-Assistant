import os

filepath = r'e:\repositories\Chauffeur\chauffeur\templates\app.html'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add myErrands to byDate
my_events_orig = '''            const byDate = {};
            myEvents.forEach(ev => {'''

my_events_new = '''            const byDate = {};
            const myErrands = (scheduleData.scheduled_errands || []).filter(e => e.driver && e.driver.id === dId);
            myErrands.forEach(ev => {
                let currDate = new Date(ev.start);
                const year = currDate.getFullYear();
                const month = String(currDate.getMonth() + 1).padStart(2, '0');
                const day = String(currDate.getDate()).padStart(2, '0');
                const dStr = `${year}-${month}-${day}`;
                if (!byDate[dStr]) byDate[dStr] = [];
                byDate[dStr].push(ev);
            });

            myEvents.forEach(ev => {'''

content = content.replace(my_events_orig, my_events_new)

# 2. Add errand rendering early exit in evs.forEach loop
ev_render_orig = '''                    // --- Initial Edge ---'''
ev_render_new = '''                    if (ev.event_type === 'errand') {
                        const isPast = new Date(ev.end) < new Date();
                        html += `
                        <div class="flex items-start mb-6 relative z-10 group cursor-pointer ${isPast ? 'opacity-60' : ''}" onclick="markErrandCompleted('${ev.id}')">
                            <div class="w-10 h-10 rounded-full bg-gray-800 border-4 border-gray-950 flex items-center justify-center shrink-0 shadow-md text-gray-400">
                                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
                            </div>
                            <div class="ml-4 flex-1 bg-gray-800 border border-gray-700 rounded-xl p-4 shadow-sm active:bg-gray-700 transition-colors">
                                <div class="text-sm font-bold text-yellow-500 mb-1 uppercase tracking-wider">Errand • ${formatTime(ev.start)}</div>
                                <div class="text-white font-bold text-lg leading-tight mb-2">${ev.title}</div>
                                <div class="text-sm text-gray-500 flex items-start gap-1"><svg class="w-4 h-4 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z"></path></svg><span class="break-words line-clamp-2">${ev.location}</span></div>
                            </div>
                        </div>`;
                        return;
                    }

                    // --- Initial Edge ---'''

content = content.replace(ev_render_orig, ev_render_new)

# 3. Add markErrandCompleted function
mark_errand_completed_func = '''        async function markErrandCompleted(id) {
            if (!confirm('Mark this errand as completed?')) return;
            try {
                // We need to fetch the existing errand first
                const res = await fetch(`${apiBase}api/errands`);
                if (!res.ok) return;
                const errands = await res.json();
                const errand = errands.find(e => e.id === id);
                if (!errand) return;
                
                errand.is_completed = true;
                
                await fetch(`${apiBase}api/errands/${errand.doc_id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(errand)
                });
                fetchSchedule(true);
            } catch (err) {
                console.error(err);
                alert("Failed to complete errand");
            }
        }
        
        async function checkNotificationStatus()'''

content = content.replace('        async function checkNotificationStatus()', mark_errand_completed_func)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

print("app.html updated successfully")

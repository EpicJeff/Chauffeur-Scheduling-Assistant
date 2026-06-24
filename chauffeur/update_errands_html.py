import os

filepath = r'e:\repositories\Chauffeur\chauffeur\templates\errands.html'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. HTML Replacements
html_orig_list = '<div id="errands-list" class="flex flex-col gap-3">'
html_new_list = '''            <div id="past-due-section" class="hidden mb-6">
                <div class="mb-4 flex items-center gap-4">
                    <div class="h-px bg-red-900/50 flex-1"></div>
                    <h3 class="text-sm font-semibold text-red-500 uppercase tracking-widest flex items-center gap-1">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                        Past Due
                    </h3>
                    <div class="h-px bg-red-900/50 flex-1"></div>
                </div>
                <div id="past-due-errands-list" class="flex flex-col gap-3">
                    <!-- Dynamically populated -->
                </div>
            </div>
            
            <div id="errands-list" class="flex flex-col gap-3">'''

content = content.replace(html_orig_list, html_new_list)

html_orig_edit = '''                        <div>
                            <label class="block text-sm font-medium text-gray-400 mb-1">Duration (mins)</label>
                            <input type="number" id="edit-duration" class="w-full bg-gray-900 border border-gray-700 text-white rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all">
                        </div>
                    </div>'''
html_new_edit = '''                        <div>
                            <label class="block text-sm font-medium text-gray-400 mb-1">Duration (mins)</label>
                            <input type="number" id="edit-duration" class="w-full bg-gray-900 border border-gray-700 text-white rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all">
                        </div>
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-400 mb-1">Recurrence</label>
                        <select id="edit-recurrence" class="w-full bg-gray-900 border border-gray-700 text-white rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none appearance-none">
                            <option value="">None</option>
                            <option value="daily">Daily</option>
                            <option value="weekly">Weekly</option>
                            <option value="monthly">Monthly</option>
                        </select>
                    </div>'''

content = content.replace(html_orig_edit, html_new_edit)

# 2. JavaScript Replacements

js_orig_render = '''        function renderErrands() {
            const listEl = document.getElementById('errands-list');
            const completedEl = document.getElementById('completed-errands-list');
            
            listEl.innerHTML = '';
            completedEl.innerHTML = '';'''

js_new_render = '''        function renderErrands() {
            const listEl = document.getElementById('errands-list');
            const completedEl = document.getElementById('completed-errands-list');
            const pastDueEl = document.getElementById('past-due-errands-list');
            const pastDueSection = document.getElementById('past-due-section');
            
            listEl.innerHTML = '';
            completedEl.innerHTML = '';
            if (pastDueEl) pastDueEl.innerHTML = '';'''

content = content.replace(js_orig_render, js_new_render)

js_orig_append = '''                if (errand.is_completed) {
                    completedEl.appendChild(el);
                } else {
                    listEl.appendChild(el);
                }
            });'''

js_new_append = '''                if (errand.is_completed) {
                    completedEl.appendChild(el);
                } else if (errand.status === 'past_due' && pastDueEl) {
                    // Add reschedule button wrapper to past due items
                    const wrapper = document.createElement('div');
                    wrapper.className = "flex flex-col gap-2";
                    wrapper.appendChild(el);
                    
                    const controls = document.createElement('div');
                    controls.className = "flex justify-end gap-2 px-2";
                    controls.innerHTML = `
                        <button onclick="rescheduleErrand('${errand.id}')" class="text-xs bg-gray-700 hover:bg-gray-600 px-3 py-1.5 rounded text-white transition-colors">Reschedule</button>
                    `;
                    wrapper.appendChild(controls);
                    
                    pastDueEl.appendChild(wrapper);
                } else {
                    listEl.appendChild(el);
                }
            });
            
            if (pastDueEl && pastDueEl.children.length > 0) {
                pastDueSection.classList.remove('hidden');
            } else if (pastDueSection) {
                pastDueSection.classList.add('hidden');
            }'''

content = content.replace(js_orig_append, js_new_append)

js_orig_add = '''            return {
                title: title.trim(),
                duration_mins,
                priority,
                location,
                is_completed: false
            };
        }'''

js_new_add = '''            return {
                title: title.trim(),
                duration_mins,
                priority,
                location,
                is_completed: false,
                status: 'pending',
                recurrence_rule: null
            };
        }
        
        async function rescheduleErrand(id) {
            const errand = errands.find(e => e.id === id);
            if (!errand) return;
            errand.status = 'pending';
            errand.last_scheduled_end = null;
            
            try {
                await fetch(`/api/errands/${errand.doc_id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(errand)
                });
                fetchErrands();
            } catch (err) {
                console.error(err);
            }
        }'''

content = content.replace(js_orig_add, js_new_add)

js_orig_open = '''            document.getElementById('edit-priority').value = errand.priority || 2;
            document.getElementById('edit-duration').value = errand.duration_mins || 30;
            
            document.getElementById('edit-modal').classList.remove('hidden');'''

js_new_open = '''            document.getElementById('edit-priority').value = errand.priority || 2;
            document.getElementById('edit-duration').value = errand.duration_mins || 30;
            document.getElementById('edit-recurrence').value = errand.recurrence_rule || '';
            
            document.getElementById('edit-modal').classList.remove('hidden');'''

content = content.replace(js_orig_open, js_new_open)

js_orig_save = '''            errand.priority = parseInt(document.getElementById('edit-priority').value);
            errand.duration_mins = parseInt(document.getElementById('edit-duration').value);

            closeEditModal();'''

js_new_save = '''            errand.priority = parseInt(document.getElementById('edit-priority').value);
            errand.duration_mins = parseInt(document.getElementById('edit-duration').value);
            errand.recurrence_rule = document.getElementById('edit-recurrence').value || null;

            closeEditModal();'''

content = content.replace(js_orig_save, js_new_save)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

print("errands.html updated successfully")

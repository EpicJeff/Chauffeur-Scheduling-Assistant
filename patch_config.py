import os

content = open('chauffeur/templates/config.html', 'r').read()

r1 = '''                                <template x-if="rule.constraint_type === 'tolerance'">
                                    <span class="bg-gray-800 px-2 py-1 rounded text-orange-300 italic" x-text="'Tolerance: ' + rule.tolerance_mins + 'm'"></span>
                                </template>'''
s1 = '''                                <template x-if="rule.constraint_type === 'tolerance'">
                                    <span class="bg-gray-800 px-2 py-1 rounded text-orange-300 italic" x-text="'Tolerance: ' + rule.tolerance_mins + 'm'"></span>
                                </template>
                                <template x-if="rule.constraint_type === 'buffer'">
                                    <span class="bg-gray-800 px-2 py-1 rounded text-blue-300 italic" x-text="'Buffer: ' + (rule.buffer_before_mins || 0) + 'm before, ' + (rule.buffer_after_mins || 0) + 'm after'"></span>
                                </template>'''
content = content.replace(r1, s1)

r2 = '''                            <option value="group">Group Events</option>
                        </select>
                    </div>
                    <div class="w-full lg:w-32" x-show="newRule.constraint_type === 'tolerance'">
                        <label class="block text-gray-400 mb-1 text-sm">Tolerance (mins)</label>
                        <input type="number" x-model.number="newRule.tolerance_mins" min="0" class="w-full bg-gray-900 border border-gray-600 rounded p-3 text-white">
                    </div>'''
s2 = '''                            <option value="group">Group Events</option>
                            <option value="buffer">Buffer Time</option>
                        </select>
                    </div>
                    <div class="w-full lg:w-32" x-show="newRule.constraint_type === 'tolerance'">
                        <label class="block text-gray-400 mb-1 text-sm">Tolerance (mins)</label>
                        <input type="number" x-model.number="newRule.tolerance_mins" min="0" class="w-full bg-gray-900 border border-gray-600 rounded p-3 text-white">
                    </div>
                    <div class="w-full lg:w-32" x-show="newRule.constraint_type === 'buffer'">
                        <label class="block text-gray-400 mb-1 text-sm">Buffer Before (m)</label>
                        <input type="number" x-model.number="newRule.buffer_before_mins" min="0" class="w-full bg-gray-900 border border-gray-600 rounded p-3 text-white">
                    </div>
                    <div class="w-full lg:w-32" x-show="newRule.constraint_type === 'buffer'">
                        <label class="block text-gray-400 mb-1 text-sm">Buffer After (m)</label>
                        <input type="number" x-model.number="newRule.buffer_after_mins" min="0" class="w-full bg-gray-900 border border-gray-600 rounded p-3 text-white">
                    </div>'''
content = content.replace(r2, s2)

r3 = '''                newRule: { driver_id: '', constraint_type: 'required', keywords: [], passenger_ids: [], days_of_week: [], time_start: '', time_end: '', location: '', filter_sets: [] },'''
s3 = '''                newRule: { driver_id: '', constraint_type: 'required', keywords: [], passenger_ids: [], days_of_week: [], time_start: '', time_end: '', location: '', filter_sets: [], buffer_before_mins: 0, buffer_after_mins: 0 },'''
content = content.replace(r3, s3)

r4 = '''                        tolerance_mins: rule.tolerance_mins || 0,
                        grouping_period: rule.grouping_period || 'daily',
                        keywords: [...(rule.keywords || [])], '''
s4 = '''                        tolerance_mins: rule.tolerance_mins || 0,
                        buffer_before_mins: rule.buffer_before_mins || 0,
                        buffer_after_mins: rule.buffer_after_mins || 0,
                        grouping_period: rule.grouping_period || 'daily',
                        keywords: [...(rule.keywords || [])], '''
content = content.replace(r4, s4)

r5 = '''                    this.newRule = { driver_id: '', constraint_type: 'required', duplicate_action: 'schedule_one', tolerance_mins: 0, grouping_period: 'daily', keywords: [], passenger_ids: [], days_of_week: [], time_start: '', time_end: '', location: '', filter_sets: [] };'''
s5 = '''                    this.newRule = { driver_id: '', constraint_type: 'required', duplicate_action: 'schedule_one', tolerance_mins: 0, buffer_before_mins: 0, buffer_after_mins: 0, grouping_period: 'daily', keywords: [], passenger_ids: [], days_of_week: [], time_start: '', time_end: '', location: '', filter_sets: [] };'''
content = content.replace(r5, s5)

open('chauffeur/templates/config.html', 'w').write(content)

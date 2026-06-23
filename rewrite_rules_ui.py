import re

with open("e:/repositories/Chauffeur/chauffeur/templates/config.html", "r", encoding="utf-8") as f:
    html = f.read()

# 1. Add subTab state and sub-tab navigation
rules_tab_start = r'<div x-show="activeTab === \'rules\'" x-cloak x-transition.opacity class="space-y-10">'
rules_tab_replacement = """<div x-show="activeTab === 'rules'" x-cloak x-transition.opacity class="space-y-10" x-data="{ subTab: 'event' }">
                    <div class="flex space-x-4 mb-2 border-b border-gray-700 pb-2">
                        <button @click="subTab = 'event'" :class="subTab === 'event' ? 'text-blue-400 border-b-2 border-blue-400' : 'text-gray-400 hover:text-gray-300'" class="pb-2 font-bold text-lg transition-colors">Event Rules</button>
                        <button @click="subTab = 'priority'" :class="subTab === 'priority' ? 'text-blue-400 border-b-2 border-blue-400' : 'text-gray-400 hover:text-gray-300'" class="pb-2 font-bold text-lg transition-colors">Priority Rules</button>
                    </div>

                    <div x-show="subTab === 'event'" class="space-y-10">"""
html = html.replace(rules_tab_start, rules_tab_replacement)

# 2. Extract Editor and move it to top of Event Rules
editor_start = r'<div class="bg-gray-700/30 p-6 rounded-xl border border-gray-600 border-dashed space-y-4">'
editor_end = r'<!-- Priority Rules -->'

# We need to find the rule editor block
m = re.search(r'(<div class="bg-gray-700/30 p-6 rounded-xl border border-gray-600 border-dashed space-y-4">[\s\S]*?)<!-- Priority Rules -->', html)
if m:
    editor_block = m.group(1)
    html = html.replace(editor_block, "")
    
    # insert editor_block right under <div x-show="subTab === 'event'" class="space-y-10">
    # actually, under <p class="text-gray-400 mb-6">...</p>
    insert_point = r'<p class="text-gray-400 mb-6">Define required, preferred, or unavailable drivers for specific events.</p>'
    html = html.replace(insert_point, insert_point + "\n\n" + editor_block)

# 3. Extract Priority Editor and move it to top of Priority Rules
p_editor_start = r'<div class="bg-gray-700/30 p-6 rounded-xl border border-gray-600 border-dashed space-y-4" x-show="editPriorityRuleId || newPriorityRule.weight_modifier">'
# Wait, priority editor is at the very end. Let's find it.
m = re.search(r'(<div class="bg-gray-700/30 p-6 rounded-xl border border-gray-600 border-dashed space-y-4" x-show="editPriorityRuleId[^>]*>[\s\S]*?</div>\s*</div>\s*</div>)', html)
if m:
    p_editor_block = m.group(1)
    # Actually wait, the last few closing divs belong to priority rules and the main rules tab.
    # We should be careful. Let's do it manually.

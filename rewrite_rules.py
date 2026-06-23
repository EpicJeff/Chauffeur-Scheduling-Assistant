import re

with open("e:/repositories/Chauffeur/chauffeur/templates/config.html", "r", encoding="utf-8") as f:
    html = f.read()

# 1. Add subTab state and navigation
start_tag = r'<div x-show="activeTab === \'rules\'" x-cloak x-transition.opacity class="space-y-10">'
replacement = """<div x-show="activeTab === 'rules'" x-cloak x-transition.opacity class="space-y-10" x-data="{ subTab: 'event' }">
                    <div class="flex space-x-4 mb-2 border-b border-gray-700 pb-2">
                        <button @click="subTab = 'event'" :class="subTab === 'event' ? 'text-blue-400 border-b-2 border-blue-400' : 'text-gray-400 hover:text-gray-300'" class="pb-2 font-bold text-lg transition-colors">Event Rules</button>
                        <button @click="subTab = 'priority'" :class="subTab === 'priority' ? 'text-blue-400 border-b-2 border-blue-400' : 'text-gray-400 hover:text-gray-300'" class="pb-2 font-bold text-lg transition-colors">Priority Rules</button>
                    </div>

                    <div x-show="subTab === 'event'" class="space-y-10">"""

html = html.replace(start_tag, replacement)

# 2. Extract Event Rule Editor
# We'll use regex to find the rule editor block. It starts with the div containing 'Create Routing Rule'
editor_match = re.search(r'(<div class="bg-gray-700/30 p-6 rounded-xl border border-gray-600 border-dashed space-y-4">\s*<h3 class="text-xl font-bold text-white mb-2"\s*x-text="editRuleId \? \'Edit Rule\' : \'Create Routing Rule\'"></h3>.*?</div>\s*</div>\s*</div>)', html, re.DOTALL)
if editor_match:
    editor_block = editor_match.group(1)
    # Remove from original position
    html = html.replace(editor_block, '')
    
    # Insert it right before the manual routing rules list
    target_pos = r'<h3\s*class="text-lg font-bold text-gray-300 mb-2 uppercase tracking-wide">Manual Routing Rules</h3>'
    html = re.sub(target_pos, editor_block + "\n\n" + r'<h3 class="text-lg font-bold text-gray-300 mb-2 uppercase tracking-wide mt-10">Manual Routing Rules</h3>', html, count=1)

# 3. Extract Priority Rule Editor
p_editor_match = re.search(r'(<div class="bg-gray-700/30 p-6 rounded-xl border border-gray-600 border-dashed space-y-4" x-show="editPriorityRuleId \|\| newPriorityRule.weight_modifier">.*?</div>\s*</div>\s*</div>)', html, re.DOTALL)
if p_editor_match:
    p_editor_block = p_editor_match.group(1)
    # Remove from original
    html = html.replace(p_editor_block, '')
    
    # Insert right before priority rules list
    p_target_pos = r'<h3 class="text-lg font-bold text-gray-300 mb-2 uppercase tracking-wide">Manual Event Priorities</h3>'
    html = re.sub(p_target_pos, p_editor_block + "\n\n" + r'<h3 class="text-lg font-bold text-gray-300 mb-2 uppercase tracking-wide mt-10">Manual Event Priorities</h3>', html, count=1)

# 4. Wrap the priority section in a closing div for Event Rules and a subTab for Priority Rules
p_section_start = r'<div class="bg-gray-800 p-8 rounded-2xl shadow-2xl border border-gray-700 mt-10">'
p_replacement = """</div> <!-- End Event Rules -->
                    <div x-show="subTab === 'priority'" class="space-y-10">
                        <div class="bg-gray-800 p-8 rounded-2xl shadow-2xl border border-gray-700 mt-10">"""
html = html.replace(p_section_start, p_replacement)

# End the Priority Rules subTab at the very end of the main Rules tab
main_tab_end = r'<!-- Map/Geography -->'
# We need to insert a closing div before Map/Geography
html = html.replace(main_tab_end, "</div> <!-- End Priority Rules -->\n\n                <!-- Map/Geography -->")

with open("e:/repositories/Chauffeur/chauffeur/templates/config.html", "w", encoding="utf-8") as f:
    f.write(html)
print("Rewrite script completed!")

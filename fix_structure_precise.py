with open("chauffeur/templates/config.html", "r", encoding="utf-8") as f:
    lines = f.readlines()

def find_line(text, start=0):
    for i in range(start, len(lines)):
        if text in lines[i]:
            return i
    return -1

# 1. Add Tabs
rules_start = find_line('x-show="activeTab === \'rules\'"')
if rules_start != -1:
    lines[rules_start] = lines[rules_start].replace(
        'x-show="activeTab === \'rules\'" x-cloak x-transition.opacity class="space-y-10"',
        'x-show="activeTab === \'rules\'" x-cloak x-transition.opacity class="space-y-10" x-data="{ subTab: \'event\' }"\n                    <div class="flex space-x-4 mb-2 border-b border-gray-700 pb-2">\n                        <button @click="subTab = \'event\'" :class="subTab === \'event\' ? \'text-blue-400 border-b-2 border-blue-400\' : \'text-gray-400 hover:text-gray-300\'" class="pb-2 font-bold text-lg transition-colors">Event Rules</button>\n                        <button @click="subTab = \'priority\'" :class="subTab === \'priority\' ? \'text-blue-400 border-b-2 border-blue-400\' : \'text-gray-400 hover:text-gray-300\'" class="pb-2 font-bold text-lg transition-colors">Priority Rules</button>\n                    </div>'
    )

# 2. Add x-show="subTab === 'event'" to event rules container
event_cont_start = find_line('<div class="bg-gray-800 p-8 rounded-2xl shadow-2xl border border-gray-700">', rules_start)
if event_cont_start != -1:
    lines[event_cont_start] = lines[event_cont_start].replace('<div class="bg-gray-800', '<div x-show="subTab === \'event\'" class="bg-gray-800')

# 3. Add x-show="subTab === 'priority'" to priority rules container
priority_cont_start = find_line('<!-- Priority Rules -->')
if priority_cont_start != -1:
    p_div = find_line('<div class="bg-gray-800 p-8 rounded-2xl shadow-2xl border border-gray-700 mt-10">', priority_cont_start)
    if p_div != -1:
        lines[p_div] = lines[p_div].replace('<div class="bg-gray-800', '<div x-show="subTab === \'priority\'" class="bg-gray-800')

# Extract Event Editor
editor_start = find_line('x-text="editRuleId ? \'Edit Rule\' : \'Create Routing Rule\'"')
# The editor starts 2 lines before this
if editor_start != -1:
    editor_div_start = editor_start - 2
    # It ends exactly before "<!-- Priority Rules -->"
    editor_div_end = priority_cont_start - 1
    
    editor_content = lines[editor_div_start:editor_div_end]
    # Remove it
    for i in range(editor_div_start, editor_div_end):
        lines[i] = ""
        
    # Insert it before "Manual Routing Rules"
    manual_rules = find_line('Manual Routing Rules')
    if manual_rules != -1:
        lines[manual_rules] = "".join(editor_content) + "\n" + lines[manual_rules].replace('mb-2', 'mb-2 mt-10')

# Extract Priority Editor
p_editor_start = find_line('x-show="editPriorityRuleId || newPriorityRule.weight_modifier"')
if p_editor_start != -1:
    # Look for the end of the priority editor. The next section is Themes!
    themes_start = find_line('<!-- Themes -->')
    if themes_start != -1:
        # The editor ends 2 lines before themes
        p_editor_end = themes_start - 2
        
        p_editor_content = lines[p_editor_start:p_editor_end]
        for i in range(p_editor_start, p_editor_end):
            lines[i] = ""
            
        manual_p_rules = find_line('Manual Event Priorities')
        if manual_p_rules != -1:
            lines[manual_p_rules] = "".join(p_editor_content) + "\n" + lines[manual_p_rules].replace('mb-2', 'mb-2 mt-10')

with open("chauffeur/templates/config.html", "w", encoding="utf-8") as f:
    f.writelines(lines)
print("Structural fixes applied precisely")

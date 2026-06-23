with open("chauffeur/templates/config_fixed.html", "r", encoding="utf-8") as f:
    lines = f.readlines()

def get_routing_form_bounds(lines):
    start = -1
    for i, l in enumerate(lines):
        if "'Create Routing Rule'" in l:
            for j in range(i, -1, -1):
                if '<div class="bg-gray-700/30' in lines[j]:
                    start = j
                    break
            break
            
    for i in range(start, len(lines)):
        if '@click="cancelEditRule()"' in lines[i]:
            for j in range(i, len(lines)):
                if lines[j].strip() == '</div>':
                    if lines[j+1].strip() == '</div>':
                        return start, j+2
    return -1, -1

def get_priority_form_bounds(lines):
    start = -1
    for i, l in enumerate(lines):
        if "'Create Event Priority'" in l:
            for j in range(i, -1, -1):
                if '<div class="bg-gray-700/30' in lines[j]:
                    start = j
                    break
            break
            
    for i in range(start, len(lines)):
        if '@click="cancelEditPriorityRule()"' in lines[i]:
            for j in range(i, len(lines)):
                if lines[j].strip() == '</div>':
                    if lines[j+1].strip() == '</div>':
                        return start, j+2
    return -1, -1

r_s, r_e = get_routing_form_bounds(lines)
p_s, p_e = get_priority_form_bounds(lines)

routing_form = lines[r_s:r_e]
priority_form = lines[p_s:p_e]

# Delete forms from bottom to top
del lines[p_s:p_e]
del lines[r_s:r_e]

# 1. Add Priority x-show
priority_container_idx = -1
for i, l in enumerate(lines):
    if 'Event Priorities</h2>' in l:
        for j in range(i, -1, -1):
            if '<div class="bg-gray-800' in lines[j]:
                priority_container_idx = j
                break
        break
lines[priority_container_idx] = lines[priority_container_idx].replace('<div class="', '<div x-show="rulesSubTab === \'priority\'" x-cloak x-transition.opacity class="')

# 2. Add Routing x-show
routing_container_idx = -1
for i, l in enumerate(lines):
    if 'Routing Rules</h2>' in l:
        for j in range(i, -1, -1):
            if '<div class="bg-gray-800' in lines[j]:
                routing_container_idx = j
                break
        break
lines[routing_container_idx] = lines[routing_container_idx].replace('<div class="', '<div x-show="rulesSubTab === \'routing\'" x-transition.opacity class="')

# 3. Add rulesSubTab state
rules_tab_idx = -1
for i, l in enumerate(lines):
    if "activeTab === 'rules'" in l:
        for j in range(i, i+5):
            if 'class="space-y-10"' in lines[j]:
                lines[j] = lines[j].replace('class="space-y-10"', 'class="space-y-10" x-data="{ rulesSubTab: \'routing\' }"')
                rules_tab_idx = j
                break
        break

# 4. Insert Sub-Tab Buttons
tabs_html = """                        <div class="flex space-x-4 mb-6 border-b border-gray-700 pb-2">
                            <button @click="rulesSubTab = 'routing'" :class="rulesSubTab === 'routing' ? 'text-blue-400 border-b-2 border-blue-400' : 'text-gray-400 hover:text-gray-200'" class="pb-2 font-bold px-4 text-xl">Routing Rules</button>
                            <button @click="rulesSubTab = 'priority'" :class="rulesSubTab === 'priority' ? 'text-blue-400 border-b-2 border-blue-400' : 'text-gray-400 hover:text-gray-200'" class="pb-2 font-bold px-4 text-xl">Priority Rules</button>
                        </div>\n"""
lines.insert(routing_container_idx + 1, tabs_html)

# 5. Insert Priority Form BEFORE the list container
priority_list_idx = -1
for i, l in enumerate(lines):
    if '<template x-for="rule in priorityRules.filter' in l:
        for j in range(i, -1, -1):
            if '<div class="space-y-4 mb-8">' in lines[j]:
                priority_list_idx = j
                break
        break
lines = lines[:priority_list_idx] + priority_form + lines[priority_list_idx:]

# 6. Insert Routing Form BEFORE the list container
routing_list_idx = -1
for i, l in enumerate(lines):
    if '<template x-for="rule in rules.filter' in l:
        for j in range(i, -1, -1):
            if '<div class="space-y-4 mb-8">' in lines[j]:
                routing_list_idx = j
                break
        break
lines = lines[:routing_list_idx] + routing_form + lines[routing_list_idx:]

with open("chauffeur/templates/config_new.html", "w", encoding="utf-8") as f:
    f.write("".join(lines))
    
print("Rewrite complete.")


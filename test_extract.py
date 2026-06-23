from html.parser import HTMLParser

class ExtractParser(HTMLParser):
    def __init__(self, target_start_line):
        super().__init__()
        self.target_start_line = target_start_line
        self.stack = []
        self.void_elements = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
        self.target_depth = None
        self.start_pos = None
        self.end_pos = None
        self.current_line = 1

    def handle_starttag(self, tag, attrs):
        if tag not in self.void_elements:
            self.stack.append(tag)
        
        # When we reach the target line, record the depth
        if self.target_depth is None and self.getpos()[0] >= self.target_start_line:
            if tag == 'div':
                self.target_depth = len(self.stack)
                self.start_pos = self.getpos()

    def handle_endtag(self, tag):
        if tag in self.void_elements:
            return
            
        if self.stack and self.stack[-1] == tag:
            if self.target_depth is not None and len(self.stack) == self.target_depth:
                if self.end_pos is None:
                    self.end_pos = self.getpos()
            self.stack.pop()

with open("chauffeur/templates/config.html", "r", encoding="utf-8") as f:
    html = f.read()

lines = html.split("\n")
routing_line = -1
priority_line = -1

for i, line in enumerate(lines):
    if "'Create Routing Rule'" in line:
        for j in range(i, -1, -1):
            if '<div class="bg-gray-700/30' in lines[j]:
                routing_line = j + 1
                break
    if "'Create Event Priority'" in line:
        for j in range(i, -1, -1):
            if '<div class="bg-gray-700/30' in lines[j]:
                priority_line = j + 1
                break

parser1 = ExtractParser(routing_line)
parser1.feed(html)

parser2 = ExtractParser(priority_line)
parser2.feed(html)

print("Routing bounds:", routing_line, parser1.end_pos[0])
print("Priority bounds:", priority_line, parser2.end_pos[0])

# Extract the forms
# HTMLParser is 1-indexed, Python lists are 0-indexed.
r_start = routing_line - 1
r_end = parser1.end_pos[0] # exclusive because the `</div>` line is fully the end
routing_form = lines[r_start:r_end]

p_start = priority_line - 1
p_end = parser2.end_pos[0]
priority_form = lines[p_start:p_end]

# Delete forms from original lines (from bottom to top to preserve indices)
del lines[p_start:p_end]
del lines[r_start:r_end]

# Find insertions
# 1. Rules Tab x-data
rules_tab_line = -1
for i, line in enumerate(lines):
    if "activeTab === 'rules'" in line:
        rules_tab_line = i
        break
lines[rules_tab_line] = lines[rules_tab_line].replace('class="space-y-10"', 'class="space-y-10" x-data="{ rulesSubTab: \'routing\' }"')

# 2. Sub-tab Buttons
tabs_html = """                        <div class="flex space-x-4 mb-6 border-b border-gray-700 pb-2">
                            <button @click="rulesSubTab = 'routing'" :class="rulesSubTab === 'routing' ? 'text-blue-400 border-b-2 border-blue-400' : 'text-gray-400 hover:text-gray-200'" class="pb-2 font-bold px-4 text-xl">Routing Rules</button>
                            <button @click="rulesSubTab = 'priority'" :class="rulesSubTab === 'priority' ? 'text-blue-400 border-b-2 border-blue-400' : 'text-gray-400 hover:text-gray-200'" class="pb-2 font-bold px-4 text-xl">Priority Rules</button>
                        </div>"""
rules_container_line = -1
for i in range(rules_tab_line, len(lines)):
    if '<div class="bg-gray-800 p-8 rounded-2xl shadow-2xl border border-gray-700">' in lines[i]:
        rules_container_line = i
        break

lines.insert(rules_container_line, tabs_html)
rules_container_line += 1 # shift down

# 3. Add x-show to routing container
lines[rules_container_line] = lines[rules_container_line].replace('<div class="', '<div x-show="rulesSubTab === \'routing\'" class="')

# 4. Insert routing form before Manual Routing Rules
routing_list_line = -1
for i in range(rules_container_line, len(lines)):
    if "Manual Routing Rules" in lines[i]:
        for j in range(i, -1, -1):
            if '<div class="space-y-4 mb-8">' in lines[j]:
                routing_list_line = j
                break
        break

lines = lines[:routing_list_line] + routing_form + lines[routing_list_line:]

# 5. Add x-show to Priority Container
priority_container_line = -1
for i in range(routing_list_line, len(lines)):
    if '<div class="bg-gray-800 p-8 rounded-2xl shadow-2xl border border-gray-700 mt-10">' in lines[i]:
        priority_container_line = i
        break

lines[priority_container_line] = lines[priority_container_line].replace('<div class="', '<div x-show="rulesSubTab === \'priority\'" class="')

# 6. Insert priority form before Manual Event Priorities
priority_list_line = -1
for i in range(priority_container_line, len(lines)):
    if "Manual Event Priorities" in lines[i]:
        for j in range(i, -1, -1):
            if '<div class="space-y-4 mb-8">' in lines[j]:
                priority_list_line = j
                break
        break

lines = lines[:priority_list_line] + priority_form + lines[priority_list_line:]

with open("chauffeur/templates/config_new.html", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("Done!")

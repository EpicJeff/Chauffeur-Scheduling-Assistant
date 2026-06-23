with open("chauffeur/templates/config.html", "r", encoding="utf-8") as f:
    html = f.read()

# EXTRACT ROUTING FORM
# The routing form starts at <div class="bg-gray-700/30 p-6 rounded-xl border border-gray-600 border-dashed space-y-4">
# and ends with its closing </div>. Wait, it contains many divs.
# I'll just use the `check_html_strict.py`'s parser to find the matching closing div!
from html.parser import HTMLParser

class FormExtractor(HTMLParser):
    def __init__(self, search_for):
        super().__init__()
        self.stack = []
        self.void_elements = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
        self.search_for = search_for
        self.start_pos = None
        self.end_pos = None
        self.target_depth = None
        self.found = False

    def handle_starttag(self, tag, attrs):
        if tag not in self.void_elements:
            self.stack.append((tag, self.getpos()))
            
        attr_dict = dict(attrs)
        if not self.found and tag == 'div' and attr_dict.get('class') == 'bg-gray-700/30 p-6 rounded-xl border border-gray-600 border-dashed space-y-4':
            # Need to verify if it contains the right title
            pass # We'll just use string matching to find the start index

    def handle_endtag(self, tag):
        if tag in self.void_elements:
            return
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()

# Let's just use string find for the start index, and then parse forward to find the matching </div>
import sys

def get_matching_div(html, start_idx):
    depth = 0
    i = start_idx
    while i < len(html):
        if html[i:i+4] == '<div':
            depth += 1
            i += 4
        elif html[i:i+6] == '</div>':
            depth -= 1
            if depth == 0:
                return i + 6
            i += 6
        else:
            i += 1
    return -1

# Find Routing Form
routing_title_idx = html.find("'Create Routing Rule'")
routing_start = html.rfind('<div class="bg-gray-700/30 p-6 rounded-xl border border-gray-600 border-dashed space-y-4">', 0, routing_title_idx)
routing_end = get_matching_div(html, routing_start)
routing_form = html[routing_start:routing_end]
print(f"Routing Form extracted: {len(routing_form)} bytes")

# Find Priority Form
priority_title_idx = html.find("'Create Priority Rule'")
priority_start = html.rfind('<div class="bg-gray-700/30 p-6 rounded-xl border border-gray-600 border-dashed space-y-4">', routing_end, priority_title_idx)
priority_end = get_matching_div(html, priority_start)
priority_form = html[priority_start:priority_end]
print(f"Priority Form extracted: {len(priority_form)} bytes")

# Remove both forms from the html (replace from back to front to preserve indices)
html = html[:priority_start] + html[priority_end:]
html = html[:routing_start] + html[routing_end:]

# Now INSERT the tabs logic
# 1. Update the Rules tab container
rules_tab_start = html.find('<div x-show="activeTab === \'rules\'"')
rules_tab_end_tag = html.find('>', rules_tab_start)
html = html[:rules_tab_end_tag] + ' x-data="{ rulesSubTab: \'routing\' }"' + html[rules_tab_end_tag:]

# 2. Insert the sub-tabs buttons right after
tabs_html = """
                      <div class="flex space-x-4 mb-6 border-b border-gray-700 pb-2">
                          <button @click="rulesSubTab = 'routing'" :class="rulesSubTab === 'routing' ? 'text-blue-400 border-b-2 border-blue-400' : 'text-gray-400 hover:text-gray-200'" class="pb-2 font-bold px-4 text-xl">Routing Rules</button>
                          <button @click="rulesSubTab = 'priority'" :class="rulesSubTab === 'priority' ? 'text-blue-400 border-b-2 border-blue-400' : 'text-gray-400 hover:text-gray-200'" class="pb-2 font-bold px-4 text-xl">Priority Rules</button>
                      </div>
"""
rules_container_idx = html.find('<div class="bg-gray-800 p-8 rounded-2xl shadow-2xl border border-gray-700">', rules_tab_start)
html = html[:rules_container_idx] + tabs_html + html[rules_container_idx:]

# 3. Add x-show to routing rules container
rules_container_idx = html.find('<div class="bg-gray-800 p-8 rounded-2xl shadow-2xl border border-gray-700">', rules_tab_start)
html = html[:rules_container_idx+4] + ' x-show="rulesSubTab === \'routing\'"' + html[rules_container_idx+4:]

# 4. Add x-show to priority rules container
priority_container_idx = html.find('<div class="bg-gray-800 p-8 rounded-2xl shadow-2xl border border-gray-700 mt-10">', rules_tab_start)
html = html[:priority_container_idx+4] + ' x-show="rulesSubTab === \'priority\'"' + html[priority_container_idx+4:]

# 5. Insert Routing Form
# Right before `<div class="space-y-4 mb-8">` inside the Routing Rules container
routing_list_start = html.find('<div class="space-y-4 mb-8">', rules_container_idx)
html = html[:routing_list_start] + routing_form + "\n" + html[routing_list_start:]

# 6. Insert Priority Form
# Right before `<div class="space-y-4 mb-8">` inside the Priority Rules container
# Wait, let's find the space-y-4 inside the Priority Rules container
# Re-evaluate priority_container_idx because string length changed
priority_container_idx = html.find('<div x-show="rulesSubTab === \'priority\'" class="bg-gray-800 p-8 rounded-2xl shadow-2xl border border-gray-700 mt-10">', rules_tab_start)
priority_list_start = html.find('<div class="space-y-4 mb-8">', priority_container_idx)
html = html[:priority_list_start] + priority_form + "\n" + html[priority_list_start:]

with open("chauffeur/templates/config_new.html", "w", encoding="utf-8") as f:
    f.write(html)

print("Done. Saved to config_new.html")

import re

with open("chauffeur/templates/config.html", "r", encoding="utf-8") as f:
    html = f.read()

# 1. Add Tabs
html = html.replace("""<!-- Rules -->
                <div x-show="activeTab === 'rules'" x-cloak x-transition.opacity class="space-y-10">""",
"""<!-- Rules -->
                <div x-show="activeTab === 'rules'" x-cloak x-transition.opacity class="space-y-10" x-data="{ subTab: 'event' }">
                    <div class="flex space-x-4 mb-2 border-b border-gray-700 pb-2">
                        <button @click="subTab = 'event'" :class="subTab === 'event' ? 'text-blue-400 border-b-2 border-blue-400' : 'text-gray-400 hover:text-gray-300'" class="pb-2 font-bold text-lg transition-colors">Event Rules</button>
                        <button @click="subTab = 'priority'" :class="subTab === 'priority' ? 'text-blue-400 border-b-2 border-blue-400' : 'text-gray-400 hover:text-gray-300'" class="pb-2 font-bold text-lg transition-colors">Priority Rules</button>
                    </div>""")

html = html.replace("""<div class="bg-gray-800 p-8 rounded-2xl shadow-2xl border border-gray-700">
                            <div class="flex justify-between items-center mb-6">
                                <h2 class="text-3xl font-bold text-blue-300">Routing Rules</h2>""",
"""<div x-show="subTab === 'event'" class="bg-gray-800 p-8 rounded-2xl shadow-2xl border border-gray-700">
                            <div class="flex justify-between items-center mb-6">
                                <h2 class="text-3xl font-bold text-blue-300">Routing Rules</h2>""")

html = html.replace("""<!-- Priority Rules -->
                    <div class="bg-gray-800 p-8 rounded-2xl shadow-2xl border border-gray-700 mt-10">""",
"""<!-- Priority Rules -->
                    <div x-show="subTab === 'priority'" class="bg-gray-800 p-8 rounded-2xl shadow-2xl border border-gray-700 mt-10">""")

# 2. Extract Event Rule Editor
# Use re.DOTALL to find the editor. But careful! The editor contains "Create Routing Rule" and ends right before "<!-- Priority Rules -->"
match = re.search(r'(<div class="bg-gray-700/30 p-6 rounded-xl border border-gray-600 border-dashed space-y-4">\s*<h3 class="text-xl font-bold text-white mb-2"\s*x-text="editRuleId \? \'Edit Rule\' : \'Create Routing Rule\'"></h3>.*?</div>\s*</div>\s*</div>)', html, re.DOTALL)
if match:
    editor = match.group(1)
    # Extract the editor from where it is
    html = html.replace(editor, '')
    
    # Place it right before "Manual Routing Rules"
    target = '<h3 class="text-lg font-bold text-gray-300 mb-2 uppercase tracking-wide">Manual Routing Rules</h3>'
    replacement = editor + "\n\n                            " + '<h3 class="text-lg font-bold text-gray-300 mb-2 uppercase tracking-wide mt-10">Manual Routing Rules</h3>'
    html = html.replace(target, replacement)

# 3. Extract Priority Rule Editor
p_match = re.search(r'(<div class="bg-gray-700/30 p-6 rounded-xl border border-gray-600 border-dashed space-y-4" x-show="editPriorityRuleId \|\| newPriorityRule\.weight_modifier">.*?</div>\s*</div>\s*</div>)', html, re.DOTALL)
if p_match:
    p_editor = p_match.group(1)
    # Ensure this match doesn't contain "<!-- Themes -->" or something crazy
    if "<!-- Themes -->" in p_editor:
        print("ERROR: regex consumed themes!")
    else:
        html = html.replace(p_editor, '')
        p_target = '<h3 class="text-lg font-bold text-gray-300 mb-2 uppercase tracking-wide">Manual Event Priorities</h3>'
        p_repl = p_editor + "\n\n                        " + '<h3 class="text-lg font-bold text-gray-300 mb-2 uppercase tracking-wide mt-10">Manual Event Priorities</h3>'
        html = html.replace(p_target, p_repl)

# 4. Add x-data="{ expanded: false }" and chevron
rule_cards = re.findall(r'(<div class="bg-gray-900[^>]*p-5 rounded-xl flex flex-col md:flex-row justify-between md:items-center shadow-sm transition-opacity"[^>]*>)', html)
for card in set(rule_cards):
    if 'x-data' not in card:
        html = html.replace(card, card.replace('class="', 'x-data="{ expanded: false }" class="', 1))

summary_target = r'(<div class="text-sm space-y-2 flex-1">\s*<div class="flex flex-wrap items-center gap-2">)'
expand_btn = r"""\1
    <button @click="expanded = !expanded" class="text-gray-400 hover:text-white bg-gray-800 rounded-full p-1 transition-colors mr-2">
        <svg class="w-4 h-4 transform transition-transform duration-200" :class="expanded ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path></svg>
    </button>"""
html = re.sub(summary_target, expand_btn, html)

# Wrap filters in x-show
html = re.sub(r'(<div class="text-gray-400 flex flex-wrap gap-2 items-center">)', r'<div x-show="expanded" x-transition class="mt-2">\1', html)

# Close the wrapper
closing_target = r'(x-text="\'Time: \' \+ \(rule\.time_start \|\| \'Any\'\) \+ \' to \' \+ \(rule\.time_end \|\| \'Any\'\)"></span>\s*</template>\s*</div>)'
html = re.sub(closing_target, r'\1\n</div>', html)

with open("chauffeur/templates/config.html", "w", encoding="utf-8") as f:
    f.write(html)
print("Structural logic applied successfully")

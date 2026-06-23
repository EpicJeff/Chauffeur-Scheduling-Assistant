import re

with open("e:/repositories/Chauffeur/chauffeur/templates/config.html", "r", encoding="utf-8") as f:
    html = f.read()

# 1. Add x-data="{ expanded: false }" to rule cards
rule_container_pattern = r'(<div class="bg-gray-900[^>]*p-5 rounded-xl flex flex-col md:flex-row justify-between md:items-center shadow-sm transition-opacity"[^>]*>)'
def add_x_data(match):
    tag = match.group(1)
    if 'x-data' not in tag:
        return tag.replace('class="', 'x-data="{ expanded: false }" class="', 1)
    return tag

html = re.sub(rule_container_pattern, add_x_data, html)

# 2. Add chevron button
summary_pattern = r'(<div class="text-sm space-y-2 flex-1">\s*<div class="flex flex-wrap items-center gap-2">)'
expand_button = """
    <button @click="expanded = !expanded" class="text-gray-400 hover:text-white bg-gray-800 rounded-full p-1 transition-colors mr-2">
        <svg class="w-4 h-4 transform transition-transform duration-200" :class="expanded ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path></svg>
    </button>
"""
html = re.sub(summary_pattern, r'\1' + expand_button, html)

# 3. Add x-show to the filter container
filter_pattern = r'(<div class="text-gray-400 flex flex-wrap gap-2 items-center">)'
html = re.sub(filter_pattern, r'<div x-show="expanded" x-transition class="mt-2">\1', html)

# 4. Close the x-show div
# The container ends with:
#                                                     <template x-if="rule.time_start || rule.time_end">
#                                                         <span class="bg-gray-800 px-2 py-1 rounded text-cyan-300"
#                                                             x-text="'Time: ' + (rule.time_start || 'Any') + ' to ' + (rule.time_end || 'Any')"></span>
#                                                     </template>
#                                                 </div>
# We need to insert a `</div>` right after this `</div>`.

closing_pattern = r'(x-text="\'Time: \' \+ \(rule\.time_start \|\| \'Any\'\) \+ \' to \' \+ \(rule\.time_end \|\| \'Any\'\)"></span>\s*</template>\s*</div>)'
html = re.sub(closing_pattern, r'\1\n</div>', html)

with open("e:/repositories/Chauffeur/chauffeur/templates/config.html", "w", encoding="utf-8") as f:
    f.write(html)
print("Rewrite script completed!")

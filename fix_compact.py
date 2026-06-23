with open("chauffeur/templates/config.html", "r", encoding="utf-8") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if '<div class="bg-gray-900 border border-gray-700 p-5 rounded-xl flex flex-col md:flex-row justify-between md:items-center shadow-sm transition-opacity"' in line:
        if 'x-data' not in line:
            lines[i] = line.replace('class="', 'x-data="{ expanded: false }" class="', 1)

    if '<div class="text-sm space-y-2 flex-1">' in line:
        # The next line should be `<div class="flex flex-wrap items-center gap-2">`
        if '<div class="flex flex-wrap items-center gap-2">' in lines[i+1]:
            expand_btn = """<button @click="expanded = !expanded" class="text-gray-400 hover:text-white bg-gray-800 rounded-full p-1 transition-colors mr-2">
        <svg class="w-4 h-4 transform transition-transform duration-200" :class="expanded ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path></svg>
    </button>\n"""
            lines[i+1] = lines[i+1].replace('<div class="flex flex-wrap items-center gap-2">', '<div class="flex flex-wrap items-center gap-2">\n' + expand_btn)

    if '<div class="text-gray-400 flex flex-wrap gap-2 items-center">' in line:
        lines[i] = line.replace('<div class="text-gray-400 flex flex-wrap gap-2 items-center">', '<div x-show="expanded" x-transition class="mt-2 text-gray-400 flex flex-wrap gap-2 items-center">')

    # Close the x-show wrapper right after the time template ends.
    if 'x-text="\'Time: \' + (rule.time_start || \'Any\') + \' to \' + (rule.time_end || \'Any\')"></span>' in line:
        # This is line i. The template ends at i+1. The div ends at i+2.
        # We need to insert an extra `</div>` at i+3.
        # But wait, there are 4 types of lists!
        # Let's just do it dynamically.
        pass

# Since the layout of the time span is identical for all 4 lists:
for i in range(len(lines)):
    if 'x-text="\'Time: \' + (rule.time_start || \'Any\') + \' to \' + (rule.time_end || \'Any\')"></span>' in lines[i]:
        # we will add a </div> after the next </div>
        # look ahead for the second </div>
        div_count = 0
        for j in range(i+1, i+10):
            if '</div>' in lines[j]:
                div_count += 1
                if div_count == 2:
                    lines[j] = lines[j].replace('</div>', '</div>\n</div>', 1)
                    break

with open("chauffeur/templates/config.html", "w", encoding="utf-8") as f:
    f.writelines(lines)
print("Compact cards logic applied")

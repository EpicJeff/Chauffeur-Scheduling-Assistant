import re
html = open('e:/repositories/Chauffeur/chauffeur/templates/dashboard.html', encoding='utf-8').read()
old = """<div class="flex-1 min-w-[200px] bg-gray-900 rounded-lg overflow-hidden shadow-xl border border-gray-700 flex flex-col" ${dropAttr}>"""
new = """<div id="col-${c_id}" class="flex-1 min-w-[200px] bg-gray-900 rounded-lg overflow-hidden shadow-xl border border-gray-700 flex flex-col" ${dropAttr}>"""
html = html.replace(old, new)
open('e:/repositories/Chauffeur/chauffeur/templates/dashboard.html', 'w', encoding='utf-8').write(html)
print("Replaced column ID!")

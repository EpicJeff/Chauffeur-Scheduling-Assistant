import re
html = open('e:/repositories/Chauffeur/chauffeur/templates/components/control_center.html', encoding='utf-8').read()

old = "const targetContainer = targetCol.querySelector('.relative.flex-1');"
new = "const targetContainer = targetCol.querySelector('.relative.w-full.overflow-hidden');"

html = html.replace(old, new)
open('e:/repositories/Chauffeur/chauffeur/templates/components/control_center.html', 'w', encoding='utf-8').write(html)
print("Fixed querySelector!")

import re
html = open('e:/repositories/Chauffeur/chauffeur/templates/dashboard.html', encoding='utf-8').read()
matches = [m.start() for m in re.finditer(r'<div[^>]*draggable="true"', html)]
for m in matches:
    print(html[m:m+150])

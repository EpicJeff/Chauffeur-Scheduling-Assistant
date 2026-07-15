import re
html = open('e:/repositories/Chauffeur/chauffeur/templates/dashboard.html', encoding='utf-8').read()
matches = [m.start() for m in re.finditer(r'<div draggable="true"', html)]
for i in matches:
    print(html[i:i+150])

import re
html = open('e:/repositories/Chauffeur/chauffeur/templates/dashboard.html', encoding='utf-8').read()
matches = [m.start() for m in re.finditer(r'<div[^>]*onclick="openEventModal', html)]
for m in matches:
    print(html[m-50:m+200])
    print("-----------------------------------")

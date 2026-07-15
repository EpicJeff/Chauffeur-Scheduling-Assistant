html = open('e:/repositories/Chauffeur/chauffeur/templates/dashboard.html', encoding='utf-8').read()
old = 'onclick="openEventModal(\'${ev.id}\')"'
new = 'id="event-${ev.id}" onclick="openEventModal(\'${ev.id}\')"'
html = html.replace(old, new)
open('e:/repositories/Chauffeur/chauffeur/templates/dashboard.html', 'w', encoding='utf-8').write(html)
print("Replaced!")

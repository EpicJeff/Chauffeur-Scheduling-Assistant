import re

html = open('e:/repositories/Chauffeur/chauffeur/templates/dashboard.html', encoding='utf-8').read()

# Replace draggable event card
html, count = re.subn(r'<div draggable="true" ondragstart="drag\(event, \'\$\{ev\.id\}\', \'\$\{c_id\}\'\)" onclick="openEventModal\(\'\$\{ev\.id\}\'\)"',
               r'<div id="event-${ev.id}" draggable="true" ondragstart="drag(event, \'${ev.id}\', \'${c_id}\')" onclick="openEventModal(\'${ev.id}\')"',
               html)
print(f"Replaced main event cards: {count}")

# Replace unassigned draggable event card (if any)
html, count2 = re.subn(r'<div draggable="true" ondragstart="drag\(event, \'\$\{ev\.id\}\', \'unassigned\'\)"',
               r'<div id="event-${ev.id}" draggable="true" ondragstart="drag(event, \'${ev.id}\', \'unassigned\')"',
               html)
print(f"Replaced unassigned main event cards: {count2}")

# Replace inbox event card
html, count3 = re.subn(r'<div onclick="openEventModal\(\'\$\{ev\.id\}\'\)" class="bg-gray-800 border border-red-500/50',
               r'<div id="event-${ev.id}" onclick="openEventModal(\'${ev.id}\')" class="bg-gray-800 border border-red-500/50',
               html)
print(f"Replaced inbox cards: {count3}")

open('e:/repositories/Chauffeur/chauffeur/templates/dashboard.html', 'w', encoding='utf-8').write(html)

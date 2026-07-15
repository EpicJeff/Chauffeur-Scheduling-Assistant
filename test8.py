import re
html = open('e:/repositories/Chauffeur/chauffeur/templates/dashboard.html', encoding='utf-8').read()
old = """<div draggable="true" ondragstart="drag(event, '${ev.id}', '${c_id}')" onclick="openEventModal('${ev.id}')" """
new = """<div id="event-${ev.id}" draggable="true" ondragstart="drag(event, '${ev.id}', '${c_id}')" onclick="openEventModal('${ev.id}')" """
html = html.replace(old, new)
open('e:/repositories/Chauffeur/chauffeur/templates/dashboard.html', 'w', encoding='utf-8').write(html)
print("Replaced main event cards!")

old_inbox = """<div onclick="openEventModal('${ev.id}')" class="bg-gray-800 border border-red-500/50"""
new_inbox = """<div id="event-${ev.id}" onclick="openEventModal('${ev.id}')" class="bg-gray-800 border border-red-500/50"""
html = html.replace(old_inbox, new_inbox)
open('e:/repositories/Chauffeur/chauffeur/templates/dashboard.html', 'w', encoding='utf-8').write(html)
print("Replaced inbox event cards!")

html = open('e:/repositories/Chauffeur/chauffeur/templates/dashboard.html', encoding='utf-8').read()
old = '<div draggable="true" ondragstart="drag(event, \\\'${ev.id}\\\''
new = '<div id="event-${ev.id}" draggable="true" ondragstart="drag(event, \\\'${ev.id}\\\''
html = html.replace(old, new)

# And also for the unassigned events list if they have it
old2 = '<div draggable="true" ondragstart="drag(event, \\\'${ev.id}\\\', \\\'unassigned\\\')"'
new2 = '<div id="event-${ev.id}" draggable="true" ondragstart="drag(event, \\\'${ev.id}\\\', \\\'unassigned\\\')"'
html = html.replace(old2, new2)

open('e:/repositories/Chauffeur/chauffeur/templates/dashboard.html', 'w', encoding='utf-8').write(html)
print("Replaced!")

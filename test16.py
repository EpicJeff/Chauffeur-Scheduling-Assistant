import re

html = open('e:/repositories/Chauffeur/chauffeur/templates/dashboard.html', encoding='utf-8').read()

# For normal events
html, count = re.subn(r'<div \$\{dragAttr\} \$\{clickAttr\} title="\$\{ev\.title\}"',
               r'<div id="event-${ev.id}" ${dragAttr} ${clickAttr} title="${ev.title}"',
               html)
print(f"Replaced normal event cards: {count}")

# Let's also check background_trips just in case
html, count2 = re.subn(r'<div title="\$\{ev\.title\}" onclick="window\.location\.href=\'trip\?event_id=\$\{ev\.id\}\'"',
               r'<div id="event-${ev.id}" title="${ev.title}" onclick="window.location.href=\'trip?event_id=${ev.id}\'"',
               html)
print(f"Replaced background_trip cards: {count2}")

# Let's check errands just in case
html, count3 = re.subn(r'<div title="\$\{ev\.title\}"\s*class="absolute rounded-lg overflow-hidden bg-amber-900',
               r'<div id="event-${ev.id}" title="${ev.title}"\n                                     class="absolute rounded-lg overflow-hidden bg-amber-900',
               html)
print(f"Replaced errand cards: {count3}")

open('e:/repositories/Chauffeur/chauffeur/templates/dashboard.html', 'w', encoding='utf-8').write(html)

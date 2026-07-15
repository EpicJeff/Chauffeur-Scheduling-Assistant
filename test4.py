html = open('e:/repositories/Chauffeur/chauffeur/templates/dashboard.html', encoding='utf-8').read()
for m in __import__('re').finditer(r'onclick="openEventModal\((.*?)\)"', html):
    idx = m.start()
    print("MATCH:", html[max(0, idx-100):idx+200])

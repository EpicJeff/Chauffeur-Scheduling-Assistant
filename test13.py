html = open('e:/repositories/Chauffeur/chauffeur/templates/dashboard.html', encoding='utf-8').read()
idx = html.find('id="col-')
print(html[idx:idx+800])

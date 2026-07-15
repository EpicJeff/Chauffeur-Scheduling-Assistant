import re
content = open('e:/repositories/Chauffeur/chauffeur/templates/dashboard.html', encoding='utf-8').read()
res = re.search(r'(let eventHtml.*?)<div id=.event-\$\{ev\.id\}.{0,2000}', content, re.DOTALL)
print(res.group(0) if res else 'None')

html = open('e:/repositories/Chauffeur/chauffeur/main.py', encoding='utf-8').read()
lines = html.split('\n')
open('e:/repositories/Chauffeur/chauffeur/api_route.txt', 'w', encoding='utf-8').write('\n'.join(lines[2110:2185]))

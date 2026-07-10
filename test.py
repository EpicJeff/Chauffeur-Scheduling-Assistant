import json
with open('chauffeur/data/db.json', 'r', encoding='utf-8') as f:
    db = json.load(f)
c = db.get('conversations', {}).get('1', {})
for m in c.get('messages', []):
    print(str(m)[:200])

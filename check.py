import json
with open('e:/repositories/Chauffeur/chauffeur/data/db.json', 'r') as f:
    data = json.load(f)
print(list(data.keys()))

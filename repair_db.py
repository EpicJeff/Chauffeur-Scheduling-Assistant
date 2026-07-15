import json

db_path = 'e:/repositories/Chauffeur/chauffeur/data/db.json'
with open(db_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Let's find the valid JSON prefix
valid_json = None
for i in range(len(content), 0, -1):
    try:
        valid_json = json.loads(content[:i])
        break
    except Exception:
        pass

if valid_json:
    with open(db_path, 'w', encoding='utf-8') as f:
        json.dump(valid_json, f, indent=4)
    print("Repaired db.json!")
else:
    print("Could not repair db.json!")

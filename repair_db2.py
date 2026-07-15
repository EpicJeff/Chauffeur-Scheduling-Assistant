import json

db_path = 'e:/repositories/Chauffeur/chauffeur/data/db.json'
with open(db_path, 'r', encoding='utf-8') as f:
    content = f.read()

try:
    # Truncate at the extra data index
    valid_json = json.loads(content[:3518542])
    with open(db_path, 'w', encoding='utf-8') as f:
        json.dump(valid_json, f, indent=4)
    print("Repaired db.json using truncation!")
except Exception as e:
    print("Truncation failed:", e)

import json
with open('chauffeur/data/db.json', 'r', encoding='utf-8') as f:
    data = f.read()
try:
    json.loads(data)
    print('Valid JSON!')
except json.JSONDecodeError as e:
    print(f'Error at {e.pos}')
    valid_data = data[:e.pos]
    with open('chauffeur/data/db.json', 'w', encoding='utf-8') as f:
        f.write(valid_data)
    print('Fixed!')

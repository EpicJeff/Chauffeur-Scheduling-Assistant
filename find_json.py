import json

with open('chauffeur/data/db.json', 'r', encoding='utf-8') as f:
    db = json.load(f)

def find_key(d, target, path=''):
    if isinstance(d, dict):
        if target in d:
            print(f'Found at: {path}.{target}')
        for k,v in d.items():
            find_key(v, target, f'{path}.{k}')
    elif isinstance(d, list):
        for i, v in enumerate(d):
            find_key(v, target, f'{path}[{i}]')

find_key(db, 'trip_metadata')

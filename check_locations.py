from tinydb import TinyDB
import json
db = TinyDB('chauffeur/data/db.json')
for e in db.table('events').all():
    title = e.get('title', '')
    if 'Little Dribblers' in title or 'Shooting fundamentals' in title:
        print(f"{title}: {e.get('location')}")

from tinydb import TinyDB
import json
db = TinyDB('chauffeur/data/db.json')
for e in db.table('events').all():
    print(f"{e.get('title')}: {e.get('location')}")

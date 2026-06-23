from tinydb import TinyDB
db = TinyDB('e:\\repositories\\Chauffeur\\chauffeur\\data\\db.json')
rules = db.table('rules').all()
for r in rules:
    print(r)

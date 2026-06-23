from tinydb import TinyDB
db = TinyDB('e:\\repositories\\Chauffeur\\chauffeur\\data\\db.json')
t = db.table('distance_cache').all()
if t:
    import time
    print(t[0])
    print('Age in mins:', (time.time() - t[0]['timestamp']) / 60)

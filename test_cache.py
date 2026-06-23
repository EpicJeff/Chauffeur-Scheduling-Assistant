from tinydb import TinyDB
db = TinyDB('e:\\repositories\\Chauffeur\\chauffeur\\data\\db.json')
print('Num distance caches:', len(db.table('distance_cache').all()))
print('Num geocode caches:', len(db.table('geocode_cache').all()))

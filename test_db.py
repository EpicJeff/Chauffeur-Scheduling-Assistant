import sys
sys.path.append('e:/repositories/Chauffeur/chauffeur')
from services import storage
events = storage.get_all_events()
for e in events:
    print(e.get('title'), '=>', e.get('location'))

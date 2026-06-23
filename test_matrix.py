import sys
import os
sys.path.append(os.path.abspath('e:\\repositories\\Chauffeur\\chauffeur'))
import services.maps as maps
from tinydb import TinyDB
# Mock storage get_settings
maps.storage.get_settings = lambda: {'disable_mapbox': True, 'disable_mapbox_matrix': True}
coords = [[-122.084, 37.422], [-122.083, 37.421]]
names = ["A", "B"]
res = maps.fetch_matrix_chunk([0, 1], [0, 1], coords, names)
print("RESULT:", res)

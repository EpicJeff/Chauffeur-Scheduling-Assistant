"""Old-format Node fixtures cross the same Python migration boundary as saves."""
from services.twin_model_bridge import assemble, flatten


def migrated_awning_house(main_gutters=True):
    polygon = [[0, 0], [30, 0], [30, 20], [0, 20]]
    b = {'id': 'b', 'position': [0, 0], 'base': 0, 'rotation': 0,
         'levels': [{'id': 'L1', 'name': 'Ground', 'elevation': 0, 'ceiling': 10, 'outline': polygon}],
         'rooms': [], 'openings': [], 'stairs': [],
         'walls': [{'id': f'w{i}', 'from': a, 'to': polygon[(i+1) % 4], 'exterior': True,
                    'height': 10, 'thickness': .5, 'level': 'L1'} for i, a in enumerate(polygon)],
         'roof': {'sections': [{'id': 'r', 'kind': 'gable', 'ridge': 'x', 'pitch': 6,
                               'plate': 10, 'overhang': 1, 'level': 'L1', 'rect': [0, 0, 30, 20],
                               'gutters': {'y0': main_gutters, 'y1': main_gutters}}],
                  'extensions': [{'id': 'aw', 'kind': 'awning', 'section': 'r', 'wall': 'w0',
                                  'x0': 5, 'x1': 15, 'depth': 3, 'eave': 8, 'pitch': 3, 'gutter': True}]}}
    return flatten(assemble({'units': 'ft', 'buildings': [b], 'site': {}})[0])

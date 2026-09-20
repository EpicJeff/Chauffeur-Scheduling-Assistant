import copy
from services import house_facade as hf

OBSERVATIONS = {'viewpoint': 'centre', 'garage_side': 'unknown',
                'sections': [{'at': 0, 'width': 1, 'description': 'Facade'}],
                'upper': [], 'porches': [], 'gables': [], 'materials': [], 'uncertain': []}


def photo_response(system, response):
    if system == hf.OBSERVATION_PROMPT:
        return {**copy.deepcopy(OBSERVATIONS), 'viewpoint': response.get('viewpoint', 'centre') if isinstance(response, dict) else 'centre'}
    result = copy.deepcopy(response)
    if isinstance(result, dict) and result.get('mirror'):
        for key in ('ground', 'roof', 'upper', 'finishes'):
            for row in result.get(key, []):
                if 'at' in row and 'width' in row:
                    row['at'] = 1 - row['at'] - row['width']
    return result

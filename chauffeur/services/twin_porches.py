"""Porch foundation validation shared by flat reads and connected operations."""
from copy import deepcopy
import math

DEFAULT = {'type': 'posts', 'material': 'stone', 'lip_in': 1}


def foundation_error(value):
    if not isinstance(value, dict) or value.get('type') not in ('posts', 'solid'):
        return 'Choose Posts or Solid for the porch foundation.'
    value.setdefault('material', DEFAULT['material'])
    value.setdefault('lip_in', DEFAULT['lip_in'])
    if value['material'] not in ('stone', 'brick', 'concrete'):
        return 'Choose Stone, Brick or Concrete for the porch foundation.'
    lip = value['lip_in']
    if type(lip) not in (int, float) or not math.isfinite(lip) or not 0 <= lip <= 4:
        return 'Choose a porch foundation lip from 0 to 4 inches.'
    return None


def normalize_foundation(porch, notes):
    value = porch.setdefault('foundation', deepcopy(DEFAULT))
    error = foundation_error(value)
    if error:
        porch['foundation'] = deepcopy(DEFAULT)
        notes.append('Defaulted invalid porch foundation: ' + error)

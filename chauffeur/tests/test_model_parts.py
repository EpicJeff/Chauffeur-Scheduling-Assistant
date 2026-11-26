"""Models mode contract, server side: part keys, resolution and validators."""
from pathlib import Path
import os
import sys
import unittest

os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import twin_model_parts as mp

PARTS = [{'key': 'Wood', 'has_uv': True}, {'key': 'Bare', 'has_uv': False}]
LIB = {'oak', 'walnut'}


class ModelParts(unittest.TestCase):
    def test_part_keys(self):
        self.assertEqual(mp.part_keys(['Wood', None, 'Wood', '', 'Metal', 'Wood']),
                         ['Wood', 'unnamed', 'Wood~2', 'unnamed~2', 'Metal', 'Wood~3'])

    def test_resolution_order(self):
        wood = PARTS[0]
        self.assertEqual(mp.resolve_part(wood, {'Wood': {'material': 'oak', 'texture': 'model', 'tiles': 3}}, {}),
                         {'source': 'model', 'material': 'oak', 'texture': 'model', 'tiles': 3})
        self.assertEqual(mp.resolve_part(wood, {'Wood': {'material': 'oak'}}, {'Wood': {'material': 'original'}}),
                         {'source': 'copy', 'material': None, 'texture': 'real', 'tiles': 1})
        self.assertEqual(mp.resolve_part(PARTS[1], {'Bare': {'material': 'oak', 'texture': 'model'}})['texture'], 'real')

    def test_lod_percent(self):
        self.assertEqual(mp.validate_lod_percent([60, 25, 5]), [60, 25, 5])
        for bad in ([100, 30, 40], [0, 0, 0], [101, 25, 5], [100, 25], [100, 25.5, 5], 'x'):
            with self.assertRaises(ValueError, msg=bad):
                mp.validate_lod_percent(bad)

    def test_fix(self):
        self.assertEqual(mp.validate_fix({'height_m': 0.8, 'turn': 90}), {'turn': 90, 'height_m': 0.8})
        for bad in ({'height_m': 1, 'width_m': 1}, {'turn': 45}, {'height_m': 0}, {'height_m': 31}, {'depth_m': 1}):
            with self.assertRaises(ValueError, msg=bad):
                mp.validate_fix(bad)

    def test_model_materials(self):
        ok = mp.validate_model_materials({'Wood': {'material': 'oak', 'texture': 'model', 'tiles': 2}}, PARTS, LIB, per_copy=False)
        self.assertEqual(ok, {'Wood': {'material': 'oak', 'texture': 'model', 'tiles': 2}})
        self.assertEqual(mp.validate_model_materials({'Wood': {'material': 'original'}}, PARTS, LIB, per_copy=True),
                         {'Wood': {'material': 'original'}})
        bad = [
            ({'Wood': {'material': 'oak', 'texture': 'real', 'tiles': 2}}, False),   # tiles with real
            ({'Wood': {'material': 'original'}}, False),                             # original at model level
            ({'Nope': {'material': 'oak'}}, True),                                   # unknown part
            ({'Wood': {'material': 'pine'}}, True),                                  # unknown material
            ({'Bare': {'material': 'oak', 'texture': 'model'}}, True),               # model's own without uv
            ({'Wood': {'material': 'oak', 'tiles': 0}}, True),
        ]
        for value, per_copy in bad:
            with self.assertRaises(ValueError, msg=value):
                mp.validate_model_materials(value, PARTS, LIB, per_copy=per_copy)


if __name__ == '__main__':
    unittest.main()

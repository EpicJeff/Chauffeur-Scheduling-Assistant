"""Ground mass preservation, from a non-household live response and varied roofs."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import harness
from services import house_facade as hf
from services import house_photo_structure as hs

BRICK = json.loads((Path(__file__).parent/'fixtures/house_photo_brick_structure.json').read_text())
DETAILS = {'openings':[], 'finishes':[], 'palette':{k:'unknown' for k in ('roof','frame','door','trim')}, 'limitations':[]}


class GroundMassTests(unittest.TestCase):
    def test_live_brick_roof_and_forward_wing_survive_compilation(self):
        before = copy.deepcopy(BRICK)
        spec, notes, trace = hs.compile_structure(BRICK)
        self.assertEqual(spec['upper'], [])
        self.assertEqual([(m['slot'],m['span'],m['roof']['form'],m['roof']['ridge'],m['depth'])
                          for m in spec['masses']], [(6,6,'hip','x',0.),(12,6,'gable','z',1.5)])
        self.assertFalse(any('cannot be represented independently' in n for n in notes))
        self.assertEqual((spec, notes, trace), hs.compile_structure(copy.deepcopy(BRICK)))
        self.assertEqual(BRICK, before)
        self.assertEqual(hf.normalize(spec)[0], spec)
        self.assertEqual(hf.validate_block_model(spec), [])
        slots = hf.slot_table(spec['blocks'], spec['upper'], spec['masses'])
        self.assertAlmostEqual(slots[12]['z']-slots[6]['z'], 1.5)

    def test_mirrored_mixed_stories_and_different_roofs(self):
        for mirror in (False, True):
            for form in ('hip', 'gable'):
                s = copy.deepcopy(BRICK)
                s.update(porches=[],gables=[],garage_side='right' if mirror else 'left')
                s['volumes'][1]['stories']='two'
                s['volumes'][2]['roof'].update(form=form,ridge='parallel')
                spec, _, _ = hs.compile_structure(s)
                self.assertEqual(spec['mirror'], mirror)
                self.assertTrue(spec['masses'])
                self.assertTrue(spec['upper'])
                self.assertEqual(hf.validate_block_model(spec), [])
                final, _, _ = hs.apply_details(s, spec, DETAILS)
                self.assertEqual(hs.geometry(spec), hs.geometry(final))

    def test_detail_lock_rejects_changed_mass_roof_or_depth(self):
        spec, _, _ = hs.compile_structure(BRICK)
        original = hs.compile_analysis
        for field in ('depth', 'ridge'):
            def drift(*args, **kwargs):
                final, notes, trace = original(*args, **kwargs)
                if field == 'depth': final['masses'][-1]['depth'] += .5
                else: final['masses'][-1]['roof']['ridge']='x'
                return final, notes, trace
            with patch.object(hs,'compile_analysis',side_effect=drift):
                with self.assertRaisesRegex(ValueError,'locked architecture'):
                    hs.apply_details(BRICK,spec,DETAILS)

    def test_legacy_specs_do_not_acquire_ground_masses(self):
        legacy, _ = hf.normalize(copy.deepcopy(hf.CANONICAL))
        self.assertNotIn('masses',legacy)
        self.assertEqual(hf.normalize(legacy)[0],legacy)

    def test_mass_overlap_validation_and_normalization(self):
        spec, _, _ = hs.compile_structure(BRICK)
        spec['masses'].append(copy.deepcopy(spec['masses'][0]))
        self.assertTrue(any('overlaps' in error for error in hf.validate_block_model(spec)))
        clean, notes = hf.normalize(spec)
        self.assertEqual(len(clean['masses']),2)
        self.assertTrue(any('overlap' in note for note in notes))
        self.assertEqual(hf.normalize(clean)[0],clean)

    def test_partial_overlap_keeps_the_later_roof_on_its_remaining_cells(self):
        spec, _, _ = hs.compile_structure(BRICK)
        spec['masses'][0]['span']=8
        clean, _ = hf.normalize(spec)
        self.assertEqual([(m['slot'],m['span'],m['roof']['form']) for m in clean['masses']],
                         [(6,8,'hip'),(14,4,'gable')])

    def test_porch_depth_clamp_keeps_garage_masses_valid_and_idempotent(self):
        spec=copy.deepcopy(hf.CANONICAL)
        spec['blocks']['garage']['depth']=5
        spec['masses']=[{'slot':0,'span':3,'depth':5,'roof':copy.deepcopy(spec['blocks']['garage']['roof'])},
                        {'slot':3,'span':3,'depth':5,'roof':{'form':'hip','ridge':'x','pitch_deg':30}}]
        spec['ground'].append({'slot':3,'span':2,'kind':'porch','roof':'shed','type':'covered'})
        clean,_=hf.normalize(spec)
        self.assertEqual(hf.validate_block_model(clean),[])
        self.assertEqual(hf.normalize(clean)[0],clean)


if __name__ == '__main__': unittest.main()

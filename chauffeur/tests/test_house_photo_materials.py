import copy
import unittest
import harness
from services import house_facade as hf

class PhotoMaterials(unittest.TestCase):
    def test_aliases_at_all_finish_locations(self):
        raw=copy.deepcopy(hf.CANONICAL)
        for name in ('main','garage'):
            raw['blocks'][name]['base']={'material':'painted_brick','height':1,'body':'painted_brick'}
        raw['blocks']['main']['cladding']='Board-and-Batten'
        raw['finishes']=[{'slot':7,'span':2,'story':1,'cladding':'cream_brick'}]
        raw['story_finishes']={'main':{'2':{'cladding':'lap siding'}}}
        raw['roof']=[{'slot':0,'span':3,'kind':'gable','cladding':'WHITE BRICK'}]
        before=copy.deepcopy(raw)
        self.assertTrue(hf.validate_block_model(raw))
        notes=[]
        clean,errors=hf._validate_photo_model(raw,notes)
        self.assertEqual(errors,[])
        self.assertEqual(raw,before)
        self.assertEqual(clean['blocks']['main']['base']['material'],'brick')
        self.assertEqual(clean['blocks']['garage']['base']['material'],'brick')
        self.assertEqual(clean['blocks']['main']['cladding'],'batten')
        self.assertEqual(clean['finishes'][0]['cladding'],'brick')
        self.assertEqual(clean['finishes'][0]['body'],'cream_brick')
        self.assertEqual(clean['story_finishes']['main']['2']['cladding'],'lap')
        self.assertEqual(clean['roof'][0]['cladding'],'brick')
        self.assertTrue(notes)

    def test_explicit_color_preserved_unknown_stays_invalid(self):
        raw=copy.deepcopy(hf.CANONICAL)
        raw['blocks']['main'].update(cladding='painted_brick',body='navy')
        clean,errors=hf._validate_photo_model(raw,[])
        self.assertEqual(errors,[])
        self.assertEqual(clean['blocks']['main']['body'],'navy')
        raw['blocks']['main']['cladding']='titanium foam'
        _,errors=hf._validate_photo_model(raw,[])
        self.assertTrue(any('titanium foam' in e for e in errors))
        raw['blocks']['main']['cladding']=None
        self.assertTrue(hf._validate_photo_model(raw,[])[1])

if __name__=='__main__':unittest.main()

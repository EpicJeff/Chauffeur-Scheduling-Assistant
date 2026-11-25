"""Task 4 fix I6/M9: cached old answers merge as roofs using settled context."""
from contextlib import ExitStack
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.pop('HA_BASE_URL', None)
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='awning_cached_draft_')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services import twin_build as build, twin_reads as reads
from services.twin_model_supports import is_supported
from test_twin_awning_readers import building, old_extension


def old_fragment(house=None, *, parent=True, walls=True):
    house = deepcopy(house or building())
    house['roof']['sections'] = [s for s in house['roof']['sections'] if not is_supported(s)] if parent else []
    house['roof']['extensions'] = [old_extension()]
    if not walls:
        house.pop('walls', None)
    return {'building': house, 'pages': []}


def record():
    step = build._step('draft')
    return {'id': 'a' * 32, 'generation': 0, 'state': 'stopped', 'existing': True,
            'inputs': {'building': {'id': 'b'}, 'photos': [], 'compose': False},
            'steps': [step], 'events': [], 'seq': 0, 'pause': None, 'cost': 0}, step


class CachedAwningDraft(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(build.twin_store, 'page_roles', return_value=[]))
        self.stack.enter_context(patch.object(build.twin_store, 'tombstones', return_value=[]))
        self.stack.enter_context(patch.object(build.twin_store, 'generation', return_value=0))

    def merge(self, house, fragment, tombstones=None):
        run, step = record()
        build._merge_draft(run, step, fragment, house, tombstones=tombstones or [], notes=[])

    def assert_one(self, house, expected_id='shade', expected_rect=None):
        self.assertFalse(house['roof'].get('extensions'), 'merge consumes the obsolete record before identity matching')
        supported = [s for s in house['roof']['sections'] if is_supported(s)]
        self.assertEqual(len(supported), 1)
        self.assertEqual(supported[0]['id'], expected_id)
        self.assertEqual(supported[0]['rect'], expected_rect or [3, -4, 17, 0])
        self.assertEqual(supported[0]['host']['wall'], 'front')
        return supported[0]

    def test_real_merge_then_second_merge_keep_one_existing_roof(self):
        house = building()
        fragment = old_fragment()
        before = deepcopy(fragment)
        self.merge(house, fragment)
        self.assert_one(house)
        self.merge(house, fragment)
        self.assert_one(house)
        self.assertEqual(fragment, before, 'cached historical answers stay unchanged')

    def test_roof_tombstone_prevents_cached_extension_resurrection(self):
        house = building()
        shade = next(s for s in house['roof']['sections'] if is_supported(s))
        stone = {'id': shade['id'], 'kind': 'roof', 'level': 'L1', 'building': 'b',
                 'src': {'sheet': '', 'page': 1}, 'geometry': build._geometry(shade, 'roof', house)}
        house['roof']['sections'].remove(shade)
        self.merge(house, old_fragment(), [stone])
        self.assertFalse(house['roof'].get('extensions'))
        self.assertFalse(any(is_supported(s) for s in house['roof']['sections']), 'deleted roof remains deleted')

    def test_missing_fragment_parent_and_walls_use_settled_house_placement(self):
        house = building()
        for wall in house['walls']:
            wall['from'] = [wall['from'][0], wall['from'][1] + 40]
            wall['to'] = [wall['to'][0], wall['to'][1] + 40]
        for section in house['roof']['sections']:
            section['rect'][1] += 40
            section['rect'][3] += 40
        fragment = old_fragment(house, parent=False, walls=False)
        self.merge(house, fragment)
        self.assert_one(house, expected_rect=[3, 36, 17, 40])
        self.assertTrue(any(s['id'] == 'main' for s in house['roof']['sections']), 'context parent is not retired by an absent reread')

    def test_missing_fragment_parent_uses_settled_parent_even_without_any_walls(self):
        house = building()
        house['walls'] = []
        for section in house['roof']['sections']:
            section.pop('host', None)
            section['rect'][1] += 40
            section['rect'][3] += 40
        self.merge(house, old_fragment(house, parent=False, walls=False))
        self.assertFalse(house['roof'].get('extensions'))
        supported = [s for s in house['roof']['sections'] if is_supported(s)]
        self.assertEqual([(s['id'], s['rect']) for s in supported], [('shade', [3, 36, 17, 40])])
        self.assertNotIn('host', supported[0])
        self.assertTrue(any(f.get('kind') == 'roof' and f.get('id') == 'shade' for f in house.get('flags', [])))

    def test_roof_only_cached_draft_keeps_side_placement_after_wall_retirement(self):
        house = building()
        for wall in house['walls']:
            wall['from'] = [wall['from'][0], wall['from'][1] + 40]
            wall['to'] = [wall['to'][0], wall['to'][1] + 40]
            wall['src'] = {'step': 'draft'}
        house['roof']['sections'][0]['rect'] = [0, 40, 20, 50]
        shade = house['roof']['sections'][1]
        shade.update(rect=[20, 43, 24, 47], low_side='x1', host={'wall': 'w1', 'edge': 3})
        fragment = old_fragment(house, parent=False, walls=False)
        fragment['building']['roof']['extensions'][0].update(wall='w1', x0=43, x1=47)
        self.merge(house, fragment)
        self.assertEqual(house['walls'], [], 'existing draft retirement rules remain unchanged')
        supported = [s for s in house['roof']['sections'] if is_supported(s)]
        self.assertEqual([(s['id'], s['rect']) for s in supported], [('shade', [20, 43, 24, 47])])
        self.assertNotIn('host', supported[0], 'retired wall cannot remain a host')
        self.assertTrue(any(f.get('kind') == 'roof' and f.get('id') == 'shade' for f in house.get('flags', [])))

    def test_live_reader_defers_conversion_until_context_is_complete(self):
        fragment = old_fragment(parent=False, walls=False)
        result = reads._migrate_read_fragment(deepcopy(fragment), {'building': 'b', 'settled': {}})
        self.assertEqual(result, fragment, 'an incomplete answer must not freeze an awning at a guessed origin')

    def test_no_legacy_attachment_keeps_existing_draft_flag_behavior(self):
        house = building()
        house['roof']['sections'] = house['roof']['sections'][:1]
        fragment = {'building': deepcopy(house), 'pages': []}
        fragment['building']['flags'] = [{'id': 'main', 'kind': 'roof', 'text': 'Provider annotation'}]
        self.merge(house, fragment)
        self.assertNotIn('flags', house, 'migration must not change a no-awning draft')

    def test_live_context_parent_is_not_consumed_before_its_field_patch_can_merge(self):
        fragment = old_fragment(parent=False, walls=False)
        self.assertEqual(reads._migrate_read_fragment(deepcopy(fragment), {'building': building()}), fragment)

    def test_context_parent_keeps_its_ordinary_gable_beam_field(self):
        house = building()
        house['roof']['sections'][0].update(id='roof-main', ridge='y')
        fragment = old_fragment(house, parent=False, walls=False)
        fragment['building']['roof']['extensions'][0]['section'] = 'roof-main'
        self.merge(house, fragment)
        parent = next(s for s in house['roof']['sections'] if s['id'] == 'roof-main')
        self.assertIs(parent.get('gable_beam'), True)
        self.assert_one(house)

    def test_cached_answer_does_not_overwrite_a_persons_parent_trim_choice(self):
        house = building()
        house['roof']['sections'][0].update(id='roof-main', ridge='y', gable_beam=False, src={'person': True})
        fragment = old_fragment(house, parent=False, walls=False)
        fragment['building']['roof']['extensions'][0]['section'] = 'roof-main'
        self.merge(house, fragment)
        self.assertIs(next(s for s in house['roof']['sections'] if s['id'] == 'roof-main')['gable_beam'], False)

    def test_incoming_wall_ids_pair_to_the_settled_host(self):
        house = building()
        fragment = old_fragment()
        fragment['building']['walls'][0]['id'] = 'cached-front'
        fragment['building']['roof']['extensions'][0]['wall'] = 'cached-front'
        self.merge(house, fragment)
        self.assert_one(house)

    def test_plan_material_context_keeps_the_legacy_building_finish(self):
        house = building()
        run, step = record()
        material = {'id': 'slate', 'color': '#123456'}
        build._merge_draft(run, step, old_fragment(), house, tombstones=[], notes=[], materials={'roof': material})
        self.assertEqual(self.assert_one(house)['material'], material)

    def test_live_legacy_answer_waits_for_root_and_building_material_context(self):
        for building_finish in (None, {'id': 'building-roof', 'color': '#334455'}):
            with self.subTest(building_finish=building_finish):
                house = building()
                if building_finish:
                    house['materials'] = {'roof': building_finish}
                house['levels'][0]['materials'] = {'roof': {'id': 'level-roof', 'color': '#ff0000'}}
                fragment = old_fragment(house)
                fragment['building']['roof']['extensions'][0]['materials'] = {'roof': {'id': 'unused-own', 'color': '#00ff00'}}
                before = deepcopy(fragment)
                deferred = reads._migrate_read_fragment(fragment, {'building': {'id': 'b'}})
                self.assertEqual(deferred, before, 'live read cannot freeze an unknown legacy finish')
                run, step = record()
                root_finish = {'id': 'house-roof', 'color': '#112233'}
                build._merge_draft(run, step, deferred, house, tombstones=[], notes=[], materials={'roof': root_finish})
                self.assertEqual(self.assert_one(house)['material'], building_finish or root_finish)

    def test_resume_consumes_old_step_cache_without_reader_and_does_not_duplicate(self):
        house = building()
        run, step = record()
        path = build._cache_path(run, step)
        build._atomic(path, {'fragment': old_fragment(), 'problems': []})
        cache_bytes = path.read_bytes()
        reader = self.stack.enter_context(patch.object(reads, 'read', side_effect=AssertionError('cached reply must not be bought again')))
        self.stack.enter_context(patch.object(build, '_spend'))
        self.stack.enter_context(patch.object(build, '_reset_stream'))
        self.stack.enter_context(patch.object(build, '_frame', return_value={}))
        self.stack.enter_context(patch.object(build, '_chain', return_value=None))
        def settle(run, step, result):
            build._merge_draft(run, step, result['fragment'], house, tombstones=[], notes=[])
        self.stack.enter_context(patch.object(build, '_settle', side_effect=settle))
        build._BUILDS[run['id']] = run
        self.addCleanup(build._forget)
        out = build.resume(run['id'], reader=reader, inline=True)
        self.assertEqual(out['state'], 'done', out)
        reader.assert_not_called()
        self.assert_one(house)
        self.assertEqual(path.read_bytes(), cache_bytes, 'reading an old cache does not rewrite its historical answer')
        self.merge(house, old_fragment())
        self.assert_one(house)


if __name__ == '__main__':
    unittest.main()

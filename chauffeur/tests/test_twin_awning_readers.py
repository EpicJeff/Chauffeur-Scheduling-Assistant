"""Task 4: new reads use ordinary roofs; old answers remain replayable."""
from contextlib import ExitStack, nullcontext
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.pop('HA_BASE_URL', None)
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='awning_reader_data_')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services import twin_reads as reads, twin_draft as draft
from services import twin_model_bridge as bridge, twin_model_roofs as roofs


def awning():
    return {'id': 'shade', 'name': 'Window shade', 'kind': 'shed', 'rect': [3, -4, 17, 0],
            'level': 'L1', 'low_side': 'y0', 'pitch': 3, 'plate': 9, 'overhang': 0,
            'support': {'kind': 'bracket', 'count': 3, 'inset_ft': .6, 'size_ft': .3},
            'host': {'wall': 'front', 'edge': 2}, 'thickness_ft': .3, 'fascia': False,
            'edges': [{'overhang_ft': 0}, {}, {}, {}], 'gutters': {'y0': True},
            'downspouts': {'y0': [0, 1]}}


def building():
    outline = [[0, 0], [20, 0], [20, 10], [0, 10]]
    return {'id': 'b', 'name': 'Cottage', 'position': [0, 0], 'rotation': 0, 'base': 0,
            'levels': [{'id': 'L1', 'name': 'Ground', 'elevation': 0, 'ceiling': 10, 'outline': outline}],
            'walls': [{'id': 'front' if i == 0 else f'w{i}', 'level': 'L1', 'from': a,
                       'to': outline[(i+1) % 4], 'height': 10, 'thickness': .5, 'exterior': True}
                      for i, a in enumerate(outline)],
            'openings': [], 'rooms': [], 'stairs': [],
            'roof': {'sections': [{'id': 'main', 'kind': 'gable', 'ridge': 'x', 'rect': [0, 0, 20, 10],
                                   'plate': 10, 'pitch': 6, 'overhang': 1}, awning()], 'extensions': []}}


def old_extension():
    return {'id': 'shade', 'kind': 'awning', 'section': 'main', 'wall': 'front',
            'x0': 3, 'x1': 17, 'depth': 4, 'pitch': 3, 'eave': 9, 'brackets': 3, 'gutter': True}


class AwningReaders(unittest.TestCase):
    def assert_section(self, section):
        expected = awning()
        for key in ('level', 'support', 'host', 'thickness_ft', 'fascia', 'edges', 'gutters', 'downspouts'):
            self.assertEqual(section.get(key), expected[key], key)

    def patches(self, stack):
        stack.enter_context(patch.object(reads.storage, 'get_settings', return_value={}))
        stack.enter_context(patch.object(reads.model_pools, 'credentials', return_value=('gemini-4-argon', 'fixture-key')))
        stack.enter_context(patch.object(reads.twin_cost, 'require_clear'))
        stack.enter_context(patch.object(reads.twin_cost, 'record'))

    def test_parse_supported_section_keeps_ordinary_roof_fields(self):
        answer = {'building': {'roof': {'sections': [awning()], 'extensions': []}}, 'pages': []}
        before = deepcopy(answer)
        fragment, problems = reads.parse('draft_level', answer)
        self.assertEqual(problems, [])
        self.assert_section(fragment['building']['roof']['sections'][0])
        self.assertEqual(answer, before)

    def test_read_entrypoint_carries_supported_section(self):
        answer = {'building': {'roof': {'sections': [awning()], 'extensions': []}}, 'pages': []}
        with ExitStack() as stack:
            self.patches(stack)
            call = stack.enter_context(patch.object(reads.model_pools, 'call_pool_json', return_value=deepcopy(answer)))
            out = reads.read('draft_level', [], {'level': 'roof'}, run='fixture', step='roof')
        self.assertNotIn('error', out)
        self.assert_section(out['building']['roof']['sections'][0])
        self.assertIn('support', call.call_args.args[2])
        self.assertNotIn('kind:"awning"', call.call_args.args[2])

    def test_read_keeps_zero_support_count_for_a_cantilever(self):
        section = awning()
        section['support']['count'] = 0
        answer = {'building': {'roof': {'sections': [section]}}, 'pages': []}
        with ExitStack() as stack:
            self.patches(stack)
            call = stack.enter_context(patch.object(reads.model_pools, 'call_pool_json', return_value=answer))
            out = reads.read('draft_level', [], {'level': 'roof'}, run='fixture', step='roof')
        self.assertNotIn('error', out)
        self.assertEqual(out['building']['roof']['sections'][0]['support']['count'], 0)
        self.assertIn('0..40', call.call_args.args[2])
        self.assertIn('cantilever', call.call_args.args[2])

    def test_stream_entrypoint_carries_supported_section(self):
        from services import llm_stream
        answer = {'building': {'roof': {'sections': [awning()], 'extensions': []}}, 'pages': []}
        cancel = SimpleNamespace(cancelled=False, usage={'complete': True, 'dispatched': False}, produced_chars=0)
        with ExitStack() as stack:
            self.patches(stack)
            stack.enter_context(patch.object(reads.llm_budget, 'request_scope', return_value=nullcontext()))
            stack.enter_context(patch.object(llm_stream, 'stream_json', return_value=iter([json.dumps(answer)])))
            out = reads.read_stream('draft_level', {'level': 'roof'}, [], cancel=cancel, on_text=lambda s: None,
                                    run='fixture', step='roof')
        self.assertNotIn('error', out)
        self.assert_section(out['building']['roof']['sections'][0])

    def test_legacy_parse_stays_replayable_but_read_returns_roof(self):
        b = building()
        b['roof']['sections'] = b['roof']['sections'][:1]
        b['roof']['extensions'] = [old_extension()]
        answer = {'building': b, 'pages': []}
        parsed, problems = reads.parse('draft', answer)
        self.assertEqual(problems, [])
        self.assertEqual(parsed['building']['roof']['extensions'][0]['id'], 'shade')
        with ExitStack() as stack:
            self.patches(stack)
            stack.enter_context(patch.object(reads.model_pools, 'call_pool_json', return_value=deepcopy(answer)))
            out = reads.read('draft', [], {'building': b, 'materials': {}}, run='fixture', step='draft')
        self.assertNotIn('error', out)
        self.assertFalse(out['building']['roof'].get('extensions'))
        shade = next(s for s in out['building']['roof']['sections'] if s['id'] == 'shade')
        self.assertEqual(shade['support']['kind'], 'bracket')
        self.assertEqual(shade['support']['count'], 3)

    def test_roof_only_legacy_read_uses_settled_host_without_leaking_it(self):
        b = building()
        for level in b['levels']:
            level['id'], level['elevation'] = 'L2', 10
        for wall in b['walls']:
            wall['level'] = 'L2'
        main = b['roof']['sections'][0]
        main['level'] = 'L2'
        answer = {'building': {'roof': {'sections': [main], 'extensions': [old_extension()]}}, 'pages': []}
        context = {'building': b, 'materials': {}, 'level': 'roof',
                   'settled': {'levels': b['levels'], 'walls': b['walls']}}
        with ExitStack() as stack:
            self.patches(stack)
            stack.enter_context(patch.object(reads.model_pools, 'call_pool_json', return_value=deepcopy(answer)))
            out = reads.read('draft_level', [], context, run='fixture', step='roof')
        self.assertNotIn('error', out)
        roof = next(s for s in out['building']['roof']['sections'] if s['id'] == 'shade')
        self.assertEqual(roof['level'], 'L2')
        self.assertEqual(roof['host'], {'wall': 'front', 'edge': 2})
        self.assertNotIn('levels', out['building'])
        self.assertNotIn('walls', out['building'])

    def test_draft_entrypoint_publishes_supported_roof_schema(self):
        b = building()
        captures = []
        with tempfile.TemporaryDirectory(prefix='awning_draft_') as temp, ExitStack() as stack:
            self.patches(stack)
            stack.enter_context(patch.object(draft.twin_store, 'DATA_DIR', temp))
            stack.enter_context(patch.object(draft.twin_store, 'generation', return_value=0))
            stack.enter_context(patch.object(draft.twin_store, 'current_id', return_value=None))
            stack.enter_context(patch.object(draft.twin_store, 'push_round', side_effect=lambda plan, *a, **k: captures.append(deepcopy(plan)) or 'saved'))
            stack.enter_context(patch.object(draft.twin_store, 'rounds', return_value=[{'id': 'saved', 'stale': False}]))
            stack.enter_context(patch.object(draft, '_images', return_value={'building': [], 'finishes': [], 'site': []}))
            stack.enter_context(patch.object(draft, '_area_names', return_value=[]))
            stack.enter_context(patch.object(draft.twin_cost, 'entries', return_value=[]))
            stack.enter_context(patch.object(draft.twin_compose, 'compose', side_effect=lambda plan, *a, **k: (plan, [])))
            call = stack.enter_context(patch.object(draft.model_pools, 'call_pool_json', return_value={'buildings': [b]}))
            out, notes, error = draft.draft([], [], None, run='awning-fixture')
        self.assertIsNone(error, (error, notes))
        self.assertTrue(captures)
        self.assertFalse(captures[0]['buildings'][0]['roof'].get('extensions'))
        shade = next(s for s in out['plan']['buildings'][0]['roof']['sections'] if s['id'] == 'shade')
        self.assertEqual(shade['support']['kind'], 'bracket')
        self.assertIn('"support"', call.call_args.args[2])
        self.assertNotIn('"kind":"awning"', call.call_args.args[2])
        self.assertNotIn('"kind":"shed_continuation"', call.call_args.args[2])

    def test_flatten_migrates_raw_native_extension_without_mutating_input(self):
        b = building()
        b['roof']['sections'] = b['roof']['sections'][:1]
        model, _ = bridge.assemble({'units': 'ft', 'buildings': [b]})
        model['buildings'][0]['extensions'] = [old_extension()]
        before = deepcopy(model)
        flat = bridge.flatten(model)
        self.assertEqual(model, before)
        self.assertFalse(flat['buildings'][0]['roof'].get('extensions'))
        shade = next(s for s in flat['buildings'][0]['roof']['sections'] if s['id'] == 'shade')
        self.assertEqual(shade['support']['kind'], 'bracket')


if __name__ == '__main__':
    unittest.main()

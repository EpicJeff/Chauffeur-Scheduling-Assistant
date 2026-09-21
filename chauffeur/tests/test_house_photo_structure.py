"""Contract/geometry tests, not a benchmark of live photo recognition."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import harness
from services import house_facade as hf, model_pools
from services.house_photo_structure import (CHECKS, LAYERS, structure_schema, detail_schema,
    compile_structure, apply_details, geometry, STRUCTURE_PROMPT)

DATA = json.loads((Path(__file__).parent / 'fixtures/house_photo_architecture_v1.json').read_text())


def structure():
    return {k: copy.deepcopy(DATA[k]) for k in ('viewpoint', 'garage_side', *LAYERS, 'limitations')} | {
        'schema_version': 3, 'garage_entry': 'side'}


def details():
    return {k: copy.deepcopy(DATA[k]) for k in ('openings', 'finishes', 'palette', 'limitations')}


def review(s):
    return {'structure': copy.deepcopy(s), 'reasons': ['Compared full wall heights and roof planes.'],
            'checks': {k: 'matched' for k in CHECKS}}


class StructureTests(unittest.TestCase):
    def setUp(self):
        hf._PHOTO_RUNS.clear()
        hf._DRAFTS.clear()

    def test_contracts_separate_architecture_from_detail(self):
        props = structure_schema()['properties']
        self.assertFalse({'openings', 'finishes', 'palette', 'observations'} & set(props))
        self.assertFalse(set(LAYERS) & set(detail_schema()['properties']))
        self.assertLess(len(json.dumps(structure_schema())), 6500)
        self.assertEqual(model_pools.TIER_CHAINS['house_photo'], ['flash'])

    def test_details_preserve_every_structural_field(self):
        s = structure(); original = copy.deepcopy(s)
        locked, _, _ = compile_structure(s)
        revised, _, _ = apply_details(s, locked, details())
        self.assertEqual(geometry(locked), geometry(revised))
        self.assertEqual(s, original)
        self.assertEqual(len(revised['upper']), 1)
        self.assertEqual(sum(g.get('story') == 2 for g in revised['ground']), 3)
        self.assertEqual(hf.validate_block_model(revised), [])
        for field in LAYERS:
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'only openings'):
                apply_details(s, locked, details() | {field: []})

    def test_varied_architecture_matrix_and_mirrors(self):
        # Deliberately general synthetic inputs: test compilation, not recognition.
        for stories in ('one', 'two'):
            for form in ('gable', 'hip'):
                for ridge in ('parallel', 'perpendicular'):
                    for side in ('left', 'right', 'unknown'):
                        with self.subTest(stories=stories, form=form, ridge=ridge, side=side):
                            s = structure()
                            v = copy.deepcopy(s['volumes'][0])
                            v.update(id='whole', at=0, width=1, stories=stories)
                            v['roof'].update(form=form, ridge=ridge)
                            s.update(volumes=[v], porches=[], gables=[], dormers=[], garage_side=side)
                            locked, _, _ = compile_structure(s)
                            d = details(); d.update(openings=[], finishes=[])
                            revised, _, _ = apply_details(s, locked, d)
                            self.assertEqual(geometry(locked), geometry(revised))
                            self.assertEqual(bool(revised['upper']), stories == 'two')
                            self.assertEqual(revised['blocks']['main']['roof']['form'], form)
                            self.assertEqual(revised['blocks']['main']['roof']['ridge'], 'x' if ridge == 'parallel' else 'z')
                            self.assertEqual(hf.validate_block_model(revised), [])

    def test_door_cannot_change_unknown_garage_mapping(self):
        s = structure(); s.update(porches=[], gables=[], garage_side='unknown')
        locked, _, _ = compile_structure(s)
        d = details(); d['openings'] = [DATA['openings'][1]]
        revised, _, _ = apply_details(s, locked, d)
        self.assertEqual(geometry(locked), geometry(revised))

    def test_bad_owners_do_not_mutate_reviewed_structure(self):
        s = structure(); locked, _, _ = compile_structure(s); before = copy.deepcopy(locked)
        d = details(); d['openings'][0]['owner'] = 'imaginary'
        with self.assertRaises(ValueError): apply_details(s, locked, d)
        self.assertEqual(locked, before)

    def test_saved_failures_retain_declared_architecture_without_boxes(self):
        from services.house_photo_compiler import compile_analysis
        folder=Path(__file__).parent/'fixtures'
        for name in ('house_photo8_analysis.json','house_photo10_trace.json','house_photo11_analysis.json'):
            raw=json.loads((folder/name).read_text())
            if name.endswith('_trace.json'): raw=raw['review_analysis']
            _, _, trace=compile_analysis(raw)
            a=trace['prepared_analysis']
            s={k:copy.deepcopy(a[k]) for k in ('viewpoint','garage_side',*LAYERS,'limitations')}
            s.update(schema_version=3,garage_entry='side')
            with self.subTest(name=name):
                spec, _, compiled=compile_structure(s)
                self.assertEqual(compiled['prepared_analysis']['volumes'],a['volumes'])
                self.assertEqual(compiled['prepared_analysis']['porches'],a['porches'])
                self.assertEqual(hf.validate_block_model(spec),[])
                self.assertNotIn('observations',s)

    def test_three_stage_flow_caches_and_accounts_requests(self):
        s = structure(); replies = iter([s, review(s), details()])
        def provider(*args, **kw):
            self.assertEqual(args[0], 'house_photo')
            kw['attempts'].append('mock-flash')
            return copy.deepcopy(next(replies))
        with patch.object(hf, '_settings', return_value={'llm_gemini_api_key':'offline'}), patch(
                'services.model_pools.call_pool_json', side_effect=provider) as api:
            spec, _, error, token = hf.from_photo('primary', 'image/png', [{'mime':'image/png','b64':'side','view':'right'}])
            self.assertIsNone(error)
            self.assertEqual(api.call_args.args[2], STRUCTURE_PROMPT)
            result, error = hf.critique(token, 'render', automatic=True)
            self.assertIsNone(error)
            self.assertIsNotNone(result['revised'])
            self.assertEqual(result['requests_total'], 3)
            self.assertEqual(len(api.call_args_list[1].kwargs['images']), 3)
            self.assertEqual(len(api.call_args_list[2].kwargs['images']), 2)
            hf.critique(token, 'render', automatic=True)
            self.assertEqual(api.call_count, 3)
            self.assertEqual(hf.from_photo('primary','image/png',[{'mime':'image/png','b64':'side','view':'right'}])[3],token)
            self.assertEqual(api.call_count, 3)
        trace = hf._DRAFTS[token]['photo_trace']
        self.assertEqual([x['name'] for a in trace['request_actions'] for x in a['stages']],
                         ['structure', 'structural_review', 'details'])
        self.assertTrue(trace['detail_geometry_preserved'])
        self.assertEqual(geometry(spec), geometry(result['revised']))

    def test_detail_failure_resumes_without_reanalyzing_structure(self):
        s = structure(); changed = copy.deepcopy(s)
        changed['volumes'][1]['roof']['pitch'] = 'steep'
        replies = iter([s, review(changed), {'error':'503 unavailable'}, details()])
        def provider(*args, **kw):
            kw['attempts'].append('mock-flash')
            return copy.deepcopy(next(replies))
        with patch.object(hf, '_settings', return_value={'llm_gemini_api_key':'offline'}), patch(
                'services.model_pools.call_pool_json', side_effect=provider) as api:
            _, _, _, token = hf.from_photo('retry', 'image/png')
            result, _ = hf.critique(token, 'render', automatic=True)
            self.assertEqual(result['revised']['upper'][0]['roof']['pitch_deg'], 35)
            self.assertIsNone(hf._DRAFTS[token]['result'])
            result, _ = hf.critique(token, 'render', automatic=True)
            self.assertEqual(api.call_count, 4)
            self.assertEqual(result['requests_total'], 4)
            self.assertEqual(result['revised']['upper'][0]['roof']['pitch_deg'], 35)
            self.assertIn('Fill only openings', api.call_args.args[2])

    def test_uncertainty_does_not_erase_features(self):
        s=structure(); r=review(s); r['checks']['roof_planes']='uncertain'
        r['structure']['porches']=[]; r['structure']['gables']=[g for g in s['gables'] if g['owner']!='porch']
        with patch.object(hf, '_settings', return_value={'llm_gemini_api_key':'offline'}), patch(
                'services.model_pools.call_pool_json', side_effect=[s,r,details()]):
            spec, _, _, token=hf.from_photo('uncertain','image/png')
            result, _=hf.critique(token,'render',automatic=True)
            self.assertEqual(geometry(spec),geometry(result['revised']))
            self.assertTrue(any(g['kind']=='window' for g in result['revised']['ground']))

    def test_review_failure_retains_structure_and_does_not_request_details(self):
        s=structure()
        with patch.object(hf, '_settings', return_value={'llm_gemini_api_key':'offline'}), patch(
                'services.model_pools.call_pool_json', side_effect=[s,{'error':'timeout'}]) as api:
            spec, _, _, token=hf.from_photo('review-timeout','image/png')
            result, _=hf.critique(token,'render',automatic=True)
            self.assertIsNone(result['revised'])
            self.assertEqual(hf._DRAFTS[token]['spec'],spec)
            self.assertIsNone(hf._DRAFTS[token]['result'])
            self.assertEqual(api.call_count,2)


if __name__ == '__main__': unittest.main()

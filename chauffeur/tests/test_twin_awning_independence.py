"""Task 3: supported roofs do not participate in the house's wall decisions."""
import copy
from contextlib import ExitStack
import inspect
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.pop('HA_BASE_URL', None)
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='awning_independence_')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import twin_joints as joints, twin_roof_issues as issues  # noqa: E402
from services import twin_build as build, twin_model_bridge as bridge  # noqa: E402
from services import twin_model_roofs as roofs, twin_solar as solar  # noqa: E402


def section(pid='main', rect=(0, 0, 20, 10), plate=8, supported=False):
    value = dict(id=pid, kind='gable', ridge='x', rect=list(rect), plate=plate,
                 pitch=4, overhang=1, state='settled', level='L1', src={'step': 'read'})
    if supported:
        value['support'] = {'kind': 'post', 'count': 2}
    return value


def flat_house(sections=()):
    area = [[0, 0], [20, 0], [20, 10], [0, 10]]
    return dict(id='b', name='Cottage', levels=[dict(id='L1', elevation=0, ceiling=8,
                outline=copy.deepcopy(area))], walls=[dict(id=f'w{i}', level='L1',
                exterior=True, kind='solid', height=8, thickness=.5, state='settled',
                **{'from': a, 'to': b}) for i, (a, b) in enumerate(zip(area, area[1:] + area[:1]))],
                openings=[], rooms=[], roof=dict(sections=copy.deepcopy(list(sections)), extensions=[]),
                porches=[], stairs=[])


def native_roof(value):
    return roofs.from_section(copy.deepcopy(value))


class Independence(unittest.TestCase):
    def roof_block_read(self, house, draft=None):
        """Run the real derivation orchestration; stub only I/O and roof inference."""
        draft = copy.deepcopy(house if draft is None else draft)
        result = dict(context={'building': {}}, fragment={'building': draft})
        block = dict(id='block', rect=[0, 0, 20, 10], level='L1', plate=8)
        captured = {}
        def derive(blocks, observations, evidence, choices):
            captured.update(evidence=copy.deepcopy(evidence), choices=copy.deepcopy(choices))
            return [section('derived')], []
        with ExitStack() as stack:
            for name, value in [('_cache_result', result), ('_base', {}), ('_house', house),
                                ('_migrate_crop_draft', None), ('_merge_draft', None)]:
                stack.enter_context(patch.object(build, name, return_value=value))
            stack.enter_context(patch.object(build.twin_store, 'current', return_value={}))
            stack.enter_context(patch.object(build.twin_blocks, 'blocks', return_value=[block]))
            stack.enter_context(patch.object(build.twin_roof_derive, 'derive_roof', side_effect=derive))
            build._read_roof_blocks({'inputs': {'photos': []}}, {}, None, None, result)
        self.assertNotIn('derive_error', result['roof_blocks'])
        return draft, captured

    def test_joint_snap_does_not_move_or_level_supported_roofs(self):
        main = section()
        shade = section('shade', (.3, .3, 20.3, 10.3), 8.4, True)
        before = flat_house([main]); mixed = flat_house([main, shade])
        expected_notes = joints.snap(before)
        untouched = copy.deepcopy(mixed['roof']['sections'][1])
        self.assertEqual(joints.snap(mixed), expected_notes)
        self.assertEqual(mixed['roof']['sections'][0], before['roof']['sections'][0])
        self.assertEqual(mixed['roof']['sections'][1], untouched)

    def test_joint_report_does_not_warn_about_or_hide_gaps_with_supported_roofs(self):
        far = section('main', (30, 0, 50, 10))
        shade = section('shade', (25, -5, 55, 15), 8, True)
        self.assertTrue(joints.report(flat_house([far])))
        self.assertEqual(joints.report(flat_house([far, shade])), joints.report(flat_house([far])))
        self.assertEqual(joints.report(flat_house([shade])), joints.report(flat_house()))

    def test_roof_issues_ignore_supported_roofs_above_and_below_storeys(self):
        house = flat_house()
        upper = dict(id='L2', name='Upper', elevation=10, ceiling=8,
                     outline=copy.deepcopy(house['levels'][0]['outline']))
        house['levels'].append(upper)
        house['walls'].extend([dict(copy.deepcopy(w), id='u' + w['id'], level='L2')
                               for w in house['walls'][:]])
        expected = issues.roof_issues(house)
        for height in (8, 22):
            house['roof']['sections'] = [section('shade', plate=height, supported=True)]
            self.assertEqual(issues.roof_issues(house), expected)

    def test_draft_check_keeps_free_standing_supported_roof_settled(self):
        shade = section('shade', (30, 0, 50, 10), 21, True)
        house = flat_house([shade])
        build._check_draft(house)
        self.assertEqual(house['roof']['sections'], [shade])

    def test_reread_overlap_does_not_turn_either_roof_group_into_a_proposal(self):
        for pinned_supported, incoming_supported in ((True, False), (False, True)):
            with self.subTest(pinned_supported=pinned_supported):
                old = native_roof(section('person', supported=pinned_supported))
                old['src'] = {'person': True}
                incoming = section('read', plate=9, supported=incoming_supported)
                target = dict(levels=[dict(id='L1', elevation=0, ceiling=8)],
                              walls=[], joints=[], proposals=[], flags=[])
                bridge._roofs(target, {'sections': [incoming]}, {'roofs': [old]}, [], [])
                self.assertEqual(target['proposals'], [])
                self.assertEqual({r['id'] for r in target['roofs']}, {'person', 'read'})

    def test_supported_roof_level_is_stored_not_inferred_from_plate(self):
        levels = [dict(id='L1', elevation=0, ceiling=8), dict(id='L2', elevation=10, ceiling=8)]
        for stored in ('L1', 'L2', None):
            value = section('shade', plate=18, supported=True)
            if stored is None:
                value.pop('level')
            else:
                value['level'] = stored
            target = dict(levels=levels, walls=[], joints=[], proposals=[], flags=[])
            bridge._roofs(target, {'sections': [value]}, {}, [], [])
            self.assertEqual(target['roofs'][0]['level'], stored or 'L1')
        value.pop('level', None)
        old = native_roof(dict(value, level='L2'))
        target = dict(levels=levels, walls=[], joints=[], proposals=[], flags=[])
        bridge._roofs(target, {'sections': [value]}, {'roofs': [old]}, [], [])
        self.assertEqual(target['roofs'][0]['level'], 'L2')

    def test_reread_choices_and_legacy_merge_do_not_cross_roof_groups(self):
        main = section('main')
        shade = section('shade', supported=True)
        target = dict(levels=[dict(id='L1', elevation=0, ceiling=8)], walls=[], joints=[],
                      proposals=[], flags=[])
        choice = dict(copy.deepcopy(main), pitch=9, src={'person': True})
        bridge._roofs(target, {'sections': [shade], 'choices': [choice]}, {}, [], [])
        self.assertEqual(target['roofs'][0]['pitch'], shade['pitch'])
        self.assertNotIn('person', target['roofs'][0]['src'])
        house = flat_house([shade])
        merged = build._merge_list([shade], [main], 'roof', house, {})
        self.assertEqual({r['id'] for r in merged}, {'main', 'shade'})
        same = dict(copy.deepcopy(shade), pitch=7)
        merged = build._merge_list([shade], [same], 'roof', house, {})
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['pitch'], 7)

    def test_generated_supported_reread_reuses_its_geometric_carrier(self):
        old = section('shade', supported=True)
        old['src'] = {'step': 'draft'}
        old.update(support={'kind': 'post', 'count': 3, 'size_ft': .7, 'at': {'0': [1, 2]}},
                   thickness_ft=.4, fascia=False, edges=[{'overhang_ft': 0}, {}, {}, {}])
        incoming = dict(copy.deepcopy(old), id='new-read-id', pitch=7)
        incoming.update(support={'kind': 'brace', 'count': 1}, thickness_ft=.2, fascia=True)
        incoming['edges'] = [{}, {}, {}, {}]
        merged = build._merge_list([old], [incoming], 'roof', flat_house([old]), {},
                                  {'id': 'draft', 'reread': True})
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['id'], 'shade')
        self.assertEqual(merged[0]['pitch'], 7)
        self.assertEqual(merged[0]['support'], old['support'])
        self.assertEqual(merged[0]['thickness_ft'], .4)
        self.assertFalse(merged[0]['fascia'])
        self.assertEqual(merged[0]['edges'][0]['overhang_ft'], 0)

    def test_walled_reread_does_not_remove_generated_supported_roofs(self):
        old = section('shade', supported=True)
        old['src'] = {'step': 'draft'}
        incoming = section('new-walled-read', plate=9)
        incoming['src'] = {'step': 'draft'}
        merged = build._merge_list([old], [incoming], 'roof', flat_house([old]), {},
                                  {'id': 'draft', 'reread': True})
        self.assertEqual({r['id'] for r in merged}, {'shade', 'new-walled-read'})
        self.assertEqual(next(r for r in merged if r['id'] == 'shade'), old)

    def test_authoritative_supported_reread_prunes_moved_and_removed_generated_roofs(self):
        for incoming in ([], [section('moved', (2, 0, 22, 10), supported=True)]):
            with self.subTest(incoming=bool(incoming)):
                old = section('shade', supported=True); old['src'] = {'step': 'roof-read'}
                merged = build._merge_list([old], incoming, 'roof', flat_house([old]), {},
                                          {'id': 'roof-read', 'kind': 'roof', 'reread': True})
                self.assertEqual(len(merged), len(incoming))
                self.assertNotIn('shade', {r['id'] for r in merged})
        old['src']['person'] = True
        merged = build._merge_list([old], [], 'roof', flat_house([old]), {},
                                  {'id': 'roof-read', 'kind': 'roof', 'reread': True})
        self.assertEqual(merged, [old], 'person-touched support remains protected')

    def test_draft_block_replacement_does_not_consume_lapping_supported_roofs(self):
        for old_supported, incoming_supported in ((True, False), (False, True)):
            old = section('old', (19.5, 0, 25, 10), supported=old_supported)
            old['src'] = {'step': 'earlier-roof'}
            house = flat_house([old]); house['levels'][0]['name'] = 'Ground'
            incoming = section('read', supported=incoming_supported)
            incoming['block'] = list(incoming['rect'])
            draft = flat_house([incoming]); draft['levels'][0]['name'] = 'Ground'
            with patch.object(build, '_draft_pages', return_value=[]):
                build._merge_draft({'inputs': {}}, dict(id='draft', kind='draft', source='', page=1),
                                   {'building': draft}, house)
            self.assertIn(old, house['roof']['sections'])
            self.assertEqual(len(house['roof']['sections']), 2)

    def test_block_choices_ignore_supported_choices(self):
        house = flat_house([section()])
        house['roof']['choices'] = [dict(section('choice', supported=True), src={'person': True})]
        _, read = self.roof_block_read(house)
        self.assertEqual(read['choices'], [])

    def test_block_protection_does_not_let_supported_person_roof_replace_walled_block(self):
        shade = section('shade', supported=True)
        shade.update(src={'person': True}, block=[0, 0, 20, 10])
        draft, read = self.roof_block_read(flat_house([shade]), flat_house([section('read-main')]))
        self.assertEqual(read['choices'], [])
        self.assertEqual([s['id'] for s in draft['roof']['sections']], ['derived'])

    def test_block_protected_sources_do_not_replace_generated_support_with_walled_roof(self):
        main = section('person-main'); main.update(src={'person': True}, block=[0, 0, 20, 10])
        shade = section('read-shade', supported=True)
        draft, _ = self.roof_block_read(flat_house([main]), flat_house([shade]))
        found = next((s for s in draft['roof']['sections'] if s['id'] == 'read-shade'), None)
        self.assertEqual(found, shade)

    def test_block_failed_sources_ignore_supported_source_and_supported_failure(self):
        for supported_source in (False, True):
            failed = section('failed', supported=not supported_source); failed['state'] = 'ghost'
            source = section('read', supported=supported_source)
            draft, _ = self.roof_block_read(flat_house([failed]), flat_house([source]))
            found = next((s for s in draft['roof']['sections'] if s['id'] == 'read'), None)
            if supported_source:
                self.assertEqual(found, source)
            else:
                self.assertIsNone(found, 'a supported failure cannot retain a stale walled carrier')

    def test_block_cross_gable_evidence_ignores_supported_cross_roof(self):
        main = section('main'); shade = section('shade', (2, 0, 6, 5), 8.2, True)
        shade['ridge'] = 'y'
        _, read = self.roof_block_read(flat_house([main, shade]))
        self.assertEqual(read['evidence']['block']['dormers'], [])

    def test_joint_report_bounds_ignore_supported_roofs_without_walls_or_outlines(self):
        main = section('main', (30, 0, 50, 10))
        before = flat_house([main]); before['walls'] = []; before['levels'] = []
        mixed = copy.deepcopy(before)
        mixed['roof']['sections'].append(section('shade', (-100, -100, 100, 100), supported=True))
        self.assertTrue(joints.report(before))
        self.assertEqual(joints.report(mixed), joints.report(before))

    def test_solar_exposed_face_uses_each_physical_edge_overhang(self):
        value = section('shade', supported=True); value.update(kind='flat', pitch=0)
        value['edges'] = [{'overhang_ft': v} for v in (0, 2, 3, .5)]
        r = native_roof(value)
        face = solar.faces({'roofs': [r]})[0]
        xy = [solar.point(face['plane'], uv)[:2] for uv in face['polygon']]
        self.assertEqual([min(p[i] for p in xy) for i in (0, 1)] +
                         [max(p[i] for p in xy) for i in (0, 1)], [-.5, 0, 22, 13])

    def test_orphan_dormer_does_not_acquire_a_supported_parent_by_bounds(self):
        for supported in (False, True):
            main = section('zmain'); shade = section('ashade', supported=True)
            dormer = section('dormer', (0, 2, 5, 6), 9, supported)
            dormer['dormer_of'] = main['rect']
            target = dict(levels=[dict(id='L1', elevation=0, ceiling=8)], walls=[], joints=[],
                          proposals=[], flags=[])
            bridge._roofs(target, {'sections': [shade, main, dormer]}, {}, [], [])
            self.assertEqual(target['dormers'][0]['roof'], 'ashade' if supported else 'zmain')

    def test_roof_prompt_where_words_ignore_supported_roofs(self):
        main = section('main'); side = section('side', (30, 0, 50, 10))
        def context(house):
            with patch.object(build.twin_store, 'current', return_value={'buildings': []}), \
                    patch.object(build, '_base', return_value={}), patch.object(build, '_house', return_value=house):
                return build._images_context({'inputs': {'photos': []}},
                    dict(kind='pitch', level='L1', box=None))[1]['sections']
        baseline = flat_house([main, side]); mixed = flat_house([main, section('shade', (-100, 0, 10, 10), supported=True), side])
        self.assertEqual(context(mixed), context(baseline))

    def test_named_independence_filters_are_killed_by_in_memory_mutations(self):
        # Compile one function at a time in its own module's globals. No file
        # changes and no alternate production modules are written to disk.
        rows = [
            ('block_evidence', build, '_read_roof_blocks',
             's for s in sections if not is_supported(s) and not porch_roof(s)',
             's for s in sections if not porch_roof(s)',
             'test_roof_block_reread_keeps_supported_roofs_out_of_evidence_and_choices'),
            ('block_choices', build, '_read_roof_blocks',
             "[c for c in twin_plan._roof_entries(house['roof'], 'choices') if not is_supported(c)]",
             "[c for c in twin_plan._roof_entries(house['roof'], 'choices')]",
             'test_block_choices_ignore_supported_choices'),
            ('block_protected', build, '_read_roof_blocks',
             "if s.get('src', {}).get('person') and not is_supported(s)]",
             "if s.get('src', {}).get('person')]",
             'test_block_protection_does_not_let_supported_person_roof_replace_walled_block'),
            ('block_protected_sources', build, '_read_roof_blocks',
             'protected_sources = [s for s in sections if not is_supported(s) and any(',
             'protected_sources = [s for s in sections if any(',
             'test_block_protected_sources_do_not_replace_generated_support_with_walled_roof'),
            ('block_failed_source', build, '_read_roof_blocks',
             'failed_sources = [s for s in sections if not is_supported(s) and any(',
             'failed_sources = [s for s in sections if any(',
             'test_block_failed_sources_ignore_supported_source_and_supported_failure'),
            ('block_failed_target', build, '_read_roof_blocks',
             "not is_supported(p) and p.get('state') == 'ghost' and _near_geometry(",
             "p.get('state') == 'ghost' and _near_geometry(",
             'test_block_failed_sources_ignore_supported_source_and_supported_failure'),
            ('block_cross_gable', build, '_read_roof_blocks',
             "section is not source and not is_supported(section) and section.get('kind') == 'gable'",
             "section is not source and section.get('kind') == 'gable'",
             'test_block_cross_gable_evidence_ignores_supported_cross_roof'),
            ('joint_bounds', joints, '_bounds',
             'if not is_supported(s) for i in (0, 2)', 'for i in (0, 2)',
             'test_joint_report_bounds_ignore_supported_roofs_without_walls_or_outlines'),
            ('solar_edge_overhang', solar, '_cached_faces',
             "edges[i].get('overhang_ft', h) if i < len(edges) else h", 'h',
             'test_solar_exposed_face_uses_each_physical_edge_overhang'),
            ('draft_replaced_source', build, '_merge_draft',
             "not s.get('src', {}).get('person') and not is_supported(s)",
             "not s.get('src', {}).get('person')",
             'test_draft_block_replacement_does_not_consume_lapping_supported_roofs'),
            ('draft_replaced_target', build, '_merge_draft',
             "not is_supported(t) and t.get('block')", "t.get('block')",
             'test_draft_block_replacement_does_not_consume_lapping_supported_roofs'),
            ('reread_prune', build, '_merge_list',
             '(keep_supports and is_supported(p))', "(kind == 'roof' and is_supported(p))",
             'test_authoritative_supported_reread_prunes_moved_and_removed_generated_roofs'),
            ('orphan_dormer', bridge, '_roofs',
             "for r in building['roofs'] if is_supported(r) == is_supported(section)]",
             "for r in building['roofs']]",
             'test_orphan_dormer_does_not_acquire_a_supported_parent_by_bounds'),
            ('prompt_sections', build, '_images_context',
             "sections = [s for s in house['roof']['sections'] if not is_supported(s)]",
             "sections = house['roof']['sections']",
             'test_roof_prompt_where_words_ignore_supported_roofs'),
        ]
        for label, module, name, before, after, method in rows:
            with self.subTest(mutation=label):
                original = getattr(module, name)
                source = inspect.getsource(original)
                self.assertEqual(source.count(before), 1, 'mutation anchor must be unique')
                source = source.replace(before, after).replace(f'def {name}(', 'def _awning_mutation(', 1)
                function = inspect.unwrap(original)
                namespace = function.__globals__
                exec(compile(source, function.__code__.co_filename, 'exec'), namespace)
                mutant = namespace.pop('_awning_mutation')
                outcome = unittest.TestResult()
                with patch.object(module, name, mutant):
                    Independence(method).run(outcome)
                self.assertFalse(outcome.errors, outcome.errors)
                self.assertTrue(outcome.failures, f'{label} survived its regression proof')
                print('PYTHON_MUTATION ' + json.dumps(dict(fix=label, killed=True, exit=1,
                    test_fail_names=[case.id() for case, _ in outcome.failures],
                    failure_output=''.join(f'FAIL: {case.id()}\n{trace}\n' for case, trace in outcome.failures)
                        + f'FAILED (failures={len(outcome.failures)})\n')))

    def test_solar_faces_and_saves_use_each_supported_roofs_own_envelope(self):
        main = native_roof(section())
        baseline = solar.faces({'roofs': [main]})
        for height in (4, 18):
            shade = native_roof(section('shade', plate=height, supported=True))
            own = solar.faces({'roofs': [shade]})
            mixed = {'roofs': [main, shade]}
            actual = solar.faces(mixed)
            self.assertEqual([f for f in actual if f['roof'] == 'main'], baseline)
            expected = [{**f, 'section': 1} for f in own]
            self.assertEqual([f for f in actual if f['roof'] == 'shade'], expected)
            for face in (baseline[0], own[0]):
                xy = [solar.point(face['plane'], p)[:2] for p in face['polygon']]
                centre = [sum(p[i] for p in xy) / len(xy) for i in (0, 1)]
                uv = solar.project(face['plane'], centre)
                zone = dict(roof=face['roof'], plane=face['plane'],
                            rect=[uv[0]-.2, uv[1]-.2, uv[0]+.2, uv[1]+.2])
                self.assertIsNone(solar.error(mixed, zone))

    def test_roof_block_reread_keeps_supported_roofs_out_of_evidence_and_choices(self):
        main = section('main', plate=8)
        main['pitch'] = 6
        shade = section('shade', (-1, -1, 21, 11), plate=9, supported=True)
        shade['ridge'] = 'y'; shade['pitch'] = 2
        shade['src'] = {'person': True}
        shade['block'] = list(main['rect'])
        house = flat_house([shade, main])
        draft = copy.deepcopy(house)
        result = dict(context={'building': {}}, fragment={'building': draft})
        block = dict(id='block', rect=main['rect'], level='L1', plate=8)
        captured = {}
        def derive(blocks, observations, evidence, choices):
            captured.update(evidence=copy.deepcopy(evidence), choices=copy.deepcopy(choices))
            return [dict(copy.deepcopy(main), id='derived')], []
        with ExitStack() as stack:
            for name, return_value in [('_cache_result', result), ('_base', {}), ('_house', house),
                                       ('_migrate_crop_draft', None), ('_merge_draft', None)]:
                stack.enter_context(patch.object(build, name, return_value=return_value))
            stack.enter_context(patch.object(build.twin_store, 'current', return_value={}))
            stack.enter_context(patch.object(build.twin_blocks, 'blocks', return_value=[block]))
            stack.enter_context(patch.object(build.twin_roof_derive, 'derive_roof', side_effect=derive))
            build._read_roof_blocks({'inputs': {'photos': []}}, {}, None, None, result)
        self.assertNotIn('derive_error', result['roof_blocks'])
        self.assertEqual(captured['evidence']['block']['pitch'], 6)
        self.assertEqual(captured['choices'], [])
        self.assertEqual([s for s in draft['roof']['sections'] if s['id'] == 'shade'], [shade])
        self.assertIn('derived', [s['id'] for s in draft['roof']['sections']])


if __name__ == '__main__':
    unittest.main(verbosity=2)

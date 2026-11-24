"""Task 2: optional supported-roof records survive every persistence boundary."""
import copy
import json
import math
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.pop('HA_BASE_URL', None)
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='twin_awning_model_')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Deliberately import first: RED must be the absent Task 2 module.
from services.twin_model_supports import (  # noqa: E402
    SUPPORT_KINDS, is_supported, normalize_support, support_points)
from services import twin_model as model, twin_model_roofs as roofs  # noqa: E402
from services import twin_model_bridge as bridge, twin_model_ops as ops  # noqa: E402
from services import twin_plan, twin_edit, twin_build, twin_store as store, storage  # noqa: E402

FIELDS = ('support', 'host', 'thickness_ft', 'fascia')
AREA = [[0, 0], [20, 0], [20, 10], [0, 10]]


def roof(supported=True):
    r = dict(id='shade', name='Terrace roof', area=copy.deepcopy(AREA), level='L1',
             kind='gable', ridge='x', plate=8, pitch=4, overhang=1,
             block=[0, 0, 20, 10], src={'sheet': '', 'page': 0, 'step': 'read'},
             edges=[dict(setting=s, pitch=4) for s in ('sloped', 'gable', 'sloped', 'gable')])
    if supported:
        r.update(support=dict(kind='bracket', count=3, inset_ft=.4, spacing_ft=5,
                              size_ft=.3, style='plain-1', at={'1': [9, 10]}),
                 host={'wall': 'w0', 'edge': 0}, thickness_ft=.25, fascia=False)
        r['edges'][0]['overhang_ft'] = 0
        r['edges'][2]['overhang_ft'] = 2.5
    return r


def house(supported=True):
    b = dict(id='b', name='Cottage', position=[0, 0], base=0,
             levels=[dict(id='L1', name='Ground', elevation=0, ceiling=8)],
             joints=[dict(id=f'j{i}', level='L1', at=p) for i, p in enumerate(copy.deepcopy(AREA))],
             walls=[dict(id=f'w{i}', level='L1', joints=[f'j{i}', f'j{(i+1)%4}'],
                         exterior=True, kind='solid', height=8, thickness=.5) for i in range(4)],
             rooms=[], roofs=[roof(supported)], openings=[], anchors=[], items=[], dormers=[],
             extensions=[], stairs=[], proposals=[], flags=[])
    return model.normalize(dict(schema=model.SCHEMA, units='ft', materials={}, buildings=[b], site={}))[0]


def parity_cases():
    cases = []
    for kind in SUPPORT_KINDS[1:]:
        r = roof(); r['support'] = dict(kind=kind, count=2)
        cases.append((kind + '_hosted', r))
    for name, changes in [
        ('one', dict(count=1)), ('twelve', dict(count=12)),
        ('inset_clamped', dict(count=3, inset_ft=6)),
        ('overrides', dict(count=3, at={'0': [1, 9], '2': [18, 11]})),
    ]:
        r = roof(); r['support'] = dict(kind='post', **changes); cases.append((name, r))
        if name == 'inset_clamped':
            r['area'] = [[0, 0], [4, 0], [4, 10], [0, 10]]
    r = roof(); r.pop('host'); r['support'] = dict(kind='brace', count=3)
    cases.append(('unhosted_ridge_x', r))
    r = roof(); r.pop('host'); r['ridge'] = 'y'
    r['edges'] = [dict(setting=s, pitch=6) for s in ('gable', 'sloped', 'gable', 'sloped')]
    cases.append(('unhosted_ridge_y', r))
    r = roof(); r['area'] = [[0, 0], [8, 0], [8, 4], [20, 4], [20, 10], [0, 10]]
    r['edges'] = [dict(setting='sloped', pitch=4) for _ in r['area']]
    r['support'] = dict(kind='post', count=4, inset_ft=.6)
    cases.append(('concave_outer_edge_spans_sections', r))
    return cases


class AwningRecord(unittest.TestCase):
    def assert_fields(self, actual, expected):
        for field in FIELDS:
            self.assertEqual(actual.get(field), expected.get(field), field)

    def stored_round_trip(self, m, *, named=False):
        settings = {}
        def update(values):
            settings.update(copy.deepcopy(values))
        with tempfile.TemporaryDirectory(prefix='awning_store_') as directory, \
                patch.object(store, 'DATA_DIR', directory), \
                patch.object(storage, 'get_settings', side_effect=lambda: copy.deepcopy(settings)), \
                patch.object(storage, 'patch_settings', side_effect=update):
            store._invalidate_reads()
            store._append_round(store._state(), m, 'load')
            store._invalidate_reads()
            if named:
                from services import twin_house_saves
                saved = twin_house_saves.save_current('Host validation', None)
                twin_house_saves.load(saved['id'])
                store._invalidate_reads()
            reopened = store.current_model()
            # Force a real disk reload, not the read-through object cache.
            store._invalidate_reads()
            self.assertEqual(reopened, store.current_model())
            return reopened

    def test_support_fields_round_trip(self):
        m = house(); original = m['buildings'][0]['roofs'][0]
        section = roofs.to_sections(original)[0]
        self.assert_fields(section, original)
        self.assert_fields(roofs.from_section(section), original)
        flat = bridge.flatten(m)
        self.assert_fields(flat['buildings'][0]['roof']['sections'][0], original)
        rebuilt, _ = bridge.assemble(flat, previous=m)
        self.assert_fields(rebuilt['buildings'][0]['roofs'][0], original)
        copied = copy.deepcopy(rebuilt)
        copied['buildings'][0]['roofs'][0]['support']['at']['1'][0] += 1
        self.assert_fields(rebuilt['buildings'][0]['roofs'][0], original)
        self.assert_fields(self.stored_round_trip(m)['buildings'][0]['roofs'][0], original)

    def test_invalid_support_is_coerced_with_one_named_note(self):
        for value in ([], 'post', 2, None, {'kind': 'unknown'}):
            r = roof(); r['support'] = value; notes = []
            normalize_support(r, notes)
            self.assertNotIn('support', r); self.assertEqual(len(notes), 1)
            self.assertIn('Terrace roof', notes[0])
        r = roof(); r['support'].update(count=True, inset_ft=-2, spacing_ft=50,
                                       size_ft=99, style='bad style', at={'9': [0, 0]})
        r.update(thickness_ft=-1, fascia='yes'); r['edges'][0]['overhang_ft'] = -1
        notes = []; normalize_support(r, notes)
        self.assertEqual(r['support']['count'], 2)
        self.assertEqual(r['support']['size_ft'], .3)
        self.assertEqual(r['support']['inset_ft'], .6)
        self.assertNotIn('spacing_ft', r['support']); self.assertNotIn('style', r['support'])
        self.assertNotIn('at', r['support'])
        self.assertEqual(r['thickness_ft'], .3); self.assertIs(r['fascia'], True)
        self.assertEqual(r['edges'][0]['overhang_ft'], 1)
        self.assertEqual(len(notes), 1)
        r['support'] = {'kind': 'walls'}; normalize_support(r, [])
        self.assertNotIn('support', r)

    def test_walled_roof_has_no_new_fields_and_save_is_stable(self):
        m = house(False)
        first = self.stored_round_trip(m)
        second = self.stored_round_trip(first)
        self.assertEqual(json.dumps(first), json.dumps(second))
        r = second['buildings'][0]['roofs'][0]
        for field in FIELDS: self.assertNotIn(field, r)
        self.assertTrue(all('overhang_ft' not in e for e in r['edges']))

    def test_edge_overhang_and_unknown_metadata_survive_sections(self):
        r = roof(); r['edges'][2]['future_edge_field'] = {'value': 7}
        section = roofs.to_sections(r)[0]
        back = roofs.from_section(section)
        self.assertEqual(back['edges'][0]['overhang_ft'], 0)
        self.assertEqual(back['edges'][2]['overhang_ft'], 2.5)
        self.assertEqual(back['edges'][2]['future_edge_field'], {'value': 7})
        self.assertNotIn('overhang_ft', back['edges'][1])
        direct = copy.deepcopy(section)
        direct.pop('gutters', None)
        direct['edges'][0]['gutter'] = True
        self.assertIs(roofs.from_section(direct)['edges'][0].get('gutter'), True)
        m = house(); m['buildings'][0]['roofs'][0] = r
        saved = self.stored_round_trip(m)
        flat = bridge.flatten(saved)
        self.assertEqual(flat['buildings'][0]['roof']['sections'][0]['edges'][2]['overhang_ft'], 2.5)
        # Keep the existing gutter rules, including gable refusal.
        m['buildings'][0]['roofs'][0]['edges'][1]['gutter'] = True
        invalid, notes = model.normalize(m)
        self.assertTrue(any('invalid area, edges or dimensions' in note for note in notes))
        self.assertTrue(invalid['buildings'][0]['roofs'][0]['edges'][1]['gutter'])

    def test_dormer_inherits_parent_support(self):
        parent = roof(); d = dict(id='d', roof='shade', edge=0, at=10, width=4, pitch=4)
        section = roofs.dormer_sections(d, parent)[0]
        self.assertEqual(section['support'], parent['support'])
        section['support']['count'] = 1
        self.assertEqual(parent['support']['count'], 3)

    def test_deleted_host_wall_keeps_roof_and_flag_is_idempotent(self):
        m = house(); m['buildings'][0]['walls'] = [w for w in m['buildings'][0]['walls'] if w['id'] != 'w0']
        first, _ = model.normalize(m); b = first['buildings'][0]
        self.assertEqual(len(b['roofs']), 1); self.assertNotIn('host', b['roofs'][0])
        flags = [f for f in b['flags'] if f.get('kind') == 'roof' and f.get('id') == 'shade']
        self.assertEqual(len(flags), 1); self.assertIn('Terrace roof', flags[0]['text'])
        again, _ = model.normalize(first)
        self.assertEqual([f for f in again['buildings'][0]['flags'] if f.get('kind') == 'roof'], flags)
        # Exercise the real deletion path as well.
        changed, _ = ops.apply(house(), dict(op='delete', building='b', id='w0'))
        self.assertNotIn('host', changed['buildings'][0]['roofs'][0])
        self.assertTrue(any(f.get('id') == 'shade' for f in changed['buildings'][0]['flags']))

    def test_host_validation_and_whole_roof_follow(self):
        m = house(); b = m['buildings'][0]
        attached = roofs.attach_edges(b['roofs'][0], b['walls'], b['joints'])
        self.assertEqual(attached['host'], dict(wall='w0', edge=0))
        points = copy.deepcopy(b['joints'])
        for j in points[:2]: j['at'][1] += 2
        moved = roofs.follow_walls(attached, b['walls'], points)
        self.assertEqual(moved['area'], [[x, y+2] for x, y in AREA])
        self.assertEqual(moved['support']['at']['1'], [9, 12])
        op_moved, _ = ops.apply(m, dict(op='move_wall', building='b', wall='w0', by=[0, 2]))
        self.assertEqual(op_moved['buildings'][0]['roofs'][0]['area'], moved['area'])
        translated, _ = ops.apply(m, dict(op='move_wall', building='b', wall='w0', by=[2, 2]))
        self.assertEqual(translated['buildings'][0]['roofs'][0]['area'], [[x+2, y+2] for x, y in AREA])
        self.assertEqual(translated['buildings'][0]['roofs'][0]['support']['at']['1'], [11, 12])
        detached = roof(); detached.pop('host'); detached['area'] = [[x, y+30] for x, y in AREA]
        self.assertNotIn('host', roofs.attach_edges(detached, b['walls'], b['joints']))
        detached['edges'][0]['wall'] = 'w0'
        self.assertEqual(roofs.attach_edges(detached, b['walls'], b['joints'])['host'], dict(wall='w0', edge=0))
        diagonal = house(); diagonal['buildings'][0]['joints'][1]['at'][1] = 1
        normalized, notes = model.normalize(diagonal)
        self.assertNotIn('host', normalized['buildings'][0]['roofs'][0]); self.assertTrue(notes)
        for host in ({'wall': 'w0', 'edge': 1}, {'wall': 'w0', 'edge': 99}, 'bad'):
            r = roof(); r['host'] = host; raw = house(); raw['buildings'][0]['roofs'][0] = r
            normalized, notes = model.normalize(raw)
            self.assertNotIn('host', normalized['buildings'][0]['roofs'][0]); self.assertTrue(notes)

    def test_bridge_person_choices_and_generated_reread_keep_fields(self):
        for person in (False, True):
            m = house(); b = m['buildings'][0]; b['roofs'][0]['src']['person'] = person
            before = copy.deepcopy(b['roofs'][0]); flat = bridge.flatten(m)
            if person:
                choice = flat['buildings'][0]['roof']['choices'][0]
                self.assert_fields(choice, before)
                self.assertEqual(choice['edges'][0]['overhang_ft'], 0)
            else:
                section = flat['buildings'][0]['roof']['sections'][0]
                for field in FIELDS: section.pop(field, None)
                section.pop('edges', None); section['rect'][2] += 1
            new, _ = bridge.assemble(flat, previous=m)
            self.assert_fields(new['buildings'][0]['roofs'][0], before)
            self.assertEqual(new['buildings'][0]['roofs'][0]['edges'][0]['overhang_ft'], 0)

    def test_accept_proposal_and_existing_edits_keep_fields(self):
        m = house(); b = m['buildings'][0]; before = copy.deepcopy(b['roofs'][0])
        proposed = roof(False); proposed['id'] = 'proposal-roof'; proposed['plate'] = 9
        proposed['support'] = {'kind': 'post', 'count': 2}
        b['proposals'] = [dict(id='p', kind='roof', against='shade', piece=proposed)]
        accepted, _ = ops.apply(m, dict(op='accept_proposal', building='b', id='p'))
        self.assert_fields(accepted['buildings'][0]['roofs'][0], before)
        self.assertEqual(accepted['buildings'][0]['roofs'][0]['edges'][0]['overhang_ft'], 0)
        for edit in (dict(op='set', building='b', id='shade', field='pitch', value=5),
                     dict(op='set_roof_edge', building='b', roof='shade', edge=0, setting='sloped', pitch=5)):
            changed, _ = ops.apply(house(), edit)
            self.assert_fields(changed['buildings'][0]['roofs'][0], before)
        edited, _ = twin_edit.apply(house(), dict(op='set', building='b', id='shade', field='pitch', value=5))
        self.assert_fields(edited['buildings'][0]['roofs'][0], before)
        legacy, _ = twin_edit.apply(house(), dict(op='set', building='b', piece='shade', field='pitch', value=5))
        self.assert_fields(legacy['buildings'][0]['roofs'][0], before)
        self.assertEqual(legacy['buildings'][0]['roofs'][0]['edges'][0]['overhang_ft'], 0)

    def test_explicit_person_choice_replaces_old_edge_override(self):
        m = house(); m['buildings'][0]['roofs'][0]['src'] = {'person': True}
        flat = bridge.flatten(m)
        flat['buildings'][0]['roof']['choices'][0]['edges'][0]['overhang_ft'] = 3
        changed, _ = bridge.assemble(flat, previous=m)
        self.assertEqual(changed['buildings'][0]['roofs'][0]['edges'][0]['overhang_ft'], 3)

    def test_clockwise_host_and_overhang_keep_their_physical_edges(self):
        m = house(); r = m['buildings'][0]['roofs'][0]
        r['area'] = [[0, 0], [0, 10], [20, 10], [20, 0]]
        r['edges'] = [dict(setting=s, pitch=4) for s in ('gable', 'sloped', 'gable', 'sloped')]
        r['edges'][0]['overhang_ft'] = 1.5
        r['host'] = {'wall': 'w3', 'edge': 0}
        m = model.normalize(m)[0]; r = m['buildings'][0]['roofs'][0]
        section = roofs.to_sections(r)[0]
        self.assertEqual(section['host'], {'wall': 'w3', 'edge': 3})
        canonical = roofs.from_section(section)
        self.assertEqual(canonical['edges'][3]['overhang_ft'], 1.5)
        self.assertEqual(canonical['edges'][3]['wall_along_offset'], 0)
        rebuilt, _ = bridge.assemble(bridge.flatten(m), previous=m)
        self.assertEqual(rebuilt['buildings'][0]['roofs'][0]['host'], {'wall': 'w3', 'edge': 3})
        rebuilt, _ = ops.apply(rebuilt, dict(op='move_wall', building='b', wall='w3', by=[-2, 1]))
        self.assertEqual(rebuilt['buildings'][0]['roofs'][0]['area'], [[x-2, y+1] for x, y in AREA])

    def test_invalid_attachment_cache_is_reset_with_a_note(self):
        m = house(); r = m['buildings'][0]['roofs'][0]
        r['edges'][0]['wall_along_offset'] = []
        normalized, notes = model.normalize(m)
        self.assertEqual(normalized['buildings'][0]['roofs'][0]['edges'][0]['wall_along_offset'], 0)
        self.assertTrue(any('Terrace roof' in note for note in notes))

    def test_native_edits_keep_physical_edge_records_for_both_windings_and_all_starts(self):
        for clockwise in (False, True):
            outline = copy.deepcopy(AREA if not clockwise else [AREA[0], *reversed(AREA[1:])])
            for start in range(4):
                area = outline[start:] + outline[:start]
                m = house(); r = m['buildings'][0]['roofs'][0]
                r['area'] = area; r['edges'] = []
                for a, b in roofs._segments(area):
                    physical = next(i for i, (c, d) in enumerate(roofs._segments(AREA))
                                    if {tuple(a), tuple(b)} == {tuple(c), tuple(d)})
                    axis = 1 if a[1] == b[1] else 0
                    r['edges'].append(dict(setting='sloped' if physical % 2 == 0 else 'gable',
                        pitch=4, wall=f'w{physical}', wall_offset=0 if physical == 0 else physical / 8,
                        wall_along_offset=a[1-axis] - AREA[physical][1-axis], overhang_ft=physical))
                host = next(i for i, edge in enumerate(r['edges']) if edge['wall'] == 'w0')
                r['host'] = dict(wall='w0', edge=host)
                m = model.normalize(m)[0]; before = copy.deepcopy(m['buildings'][0]['roofs'][0])
                edited_index = (host + 1) % 4
                actions = [dict(op='set', id='shade', field='pitch', value=5),
                           dict(op='set_roof_edge', roof='shade', edge=host, setting='sloped', pitch=5),
                           dict(op='move_roof_edge', roof='shade', edge=edited_index, by=.5)]
                for action in actions:
                    with self.subTest(clockwise=clockwise, start=start, op=action['op']):
                        changed, _ = ops.apply(m, dict(action, building='b'))
                        after = changed['buildings'][0]['roofs'][0]
                        self.assertEqual(after['host'], before['host'])
                        for i, (old, new) in enumerate(zip(before['edges'], after['edges'])):
                            for key in ('wall', 'wall_along_offset', 'overhang_ft'):
                                self.assertEqual(new.get(key), old.get(key), (i, key))
                            offset = old['wall_offset']
                            if action['op'] == 'move_roof_edge' and i == edited_index:
                                a, b = roofs._segments(before['area'])[i]
                                sign = -1 if clockwise else 1
                                axis_delta = sign * ((b[1]-a[1]) if a[0] == b[0] else -(b[0]-a[0]))
                                offset += .5 * axis_delta / math.dist(a, b)
                            self.assertEqual(new['wall_offset'], offset, (i, 'wall_offset'))

    def test_hosts_must_be_on_the_roof_level_in_normalize_load_attach_and_follow(self):
        m = house(); b = m['buildings'][0]; r = b['roofs'][0]
        self.assertEqual(roofs.attach_edges(r, b['walls'], b['joints'])['host'], r['host'])
        b['levels'].append(dict(id='L2', name='Upper', elevation=10, ceiling=8))
        upper = dict(copy.deepcopy(b['walls'][0]), id='uw0', level='L2', joints=['uj0', 'uj1'])
        b['walls'].append(upper)
        b['joints'].extend([dict(id='uj0', level='L2', at=[0, 5]),
                            dict(id='uj1', level='L2', at=[20, 5])])
        r['host'] = dict(wall='uw0', edge=0)
        r['edges'][0].update(wall='uw0', wall_offset=0, wall_along_offset=0)
        for route in ('normalize', 'load', 'follow', 'attach'):
            with self.subTest(route=route):
                if route == 'normalize':
                    result, notes = model.normalize(m)
                    actual = result['buildings'][0]['roofs'][0]
                    self.assertTrue(any('Terrace roof' in note for note in notes))
                    self.assertFalse(any(f.get('kind') == 'roof' for f in result['buildings'][0]['flags']))
                elif route == 'load':
                    actual = self.stored_round_trip(m, named=True)['buildings'][0]['roofs'][0]
                else:
                    # No same-level candidates: even an explicitly named upper wall is invalid.
                    actual = getattr(roofs, route + '_walls' if route == 'follow' else 'attach_edges')(
                        r, [upper], b['joints'])
                self.assertNotIn('host', actual)
                self.assertEqual(actual['area'], AREA)
        moved, _ = ops.apply(m, dict(op='move_wall', building='b', wall='uw0', by=[0, 2]))
        self.assertNotIn('host', moved['buildings'][0]['roofs'][0])
        self.assertEqual(moved['buildings'][0]['roofs'][0]['area'], AREA)

    def test_concave_porch_shed_rebuild_keeps_support_fields_on_every_part(self):
        m = house(); original_more = ops._more; authored = []
        def add_record_fields(building, operation, *args, **kwargs):
            result = original_more(building, operation, *args, **kwargs)
            if operation['op'] == 'roof_over':
                r = building['roofs'][-1]
                r.update(support=copy.deepcopy(roof()['support']), thickness_ft=.25, fascia=False,
                         host=dict(wall='w0', edge=len(r['area'])-1))
                for i, edge in enumerate(r['edges']):
                    edge['overhang_ft'] = i / 2
                authored.append(copy.deepcopy(r))
            return result
        polygon = [[0, 0], [0, -10], [8, -10], [8, -6], [20, -6], [20, 0]]
        with patch.object(ops, '_more', side_effect=add_record_fields):
            changed, _ = ops.apply(m, dict(op='add_porch', building='b', level='L1',
                polygon=polygon, host_wall='w0', roof='shed'))
        parts = [r for r in changed['buildings'][0]['roofs'] if r['id'] != 'shade']
        self.assertGreater(len(parts), 1)
        sections = roofs.to_sections(authored[0])
        self.assertEqual(len(parts), len(sections))
        for part in parts:
            self.assertEqual(part['support'], authored[0]['support'])
            self.assertEqual(part['thickness_ft'], .25); self.assertIs(part['fascia'], False)
            self.assertEqual(part['host']['wall'], 'w0')
            section = next(s for s in sections if s['rect'] == list(model._bounds(part['area'])))
            self.assertEqual([e.get('overhang_ft') for e in part['edges']],
                             [e.get('overhang_ft') for e in section['edges']])

    def test_deleted_host_flag_uses_roof_id_after_rename(self):
        m = house(); b = m['buildings'][0]
        b['walls'] = [w for w in b['walls'] if w['id'] != 'w0']
        first, _ = model.normalize(m)
        r = first['buildings'][0]['roofs'][0]
        r['name'] = 'Renamed roof'; r['host'] = dict(wall='w0', edge=0)
        again, _ = model.normalize(first)
        flags = [f for f in again['buildings'][0]['flags'] if f.get('id') == 'shade' and f.get('kind') == 'roof']
        self.assertEqual(len(flags), 1)
        self.assertNotIn('host', again['buildings'][0]['roofs'][0])

    def test_new_proposal_support_values_are_normalized_before_following(self):
        m = house(False)
        proposed = roof(False)
        proposed.update(support={'kind': 'post', 'count': 99, 'size_ft': 10, 'at': False},
                        host={'wall': 'w0', 'edge': 0})
        m['buildings'][0]['proposals'] = [dict(id='p', kind='roof', against='shade', piece=proposed)]
        accepted, words = ops.apply(m, dict(op='accept_proposal', building='b', id='p'))
        self.assertEqual(accepted['buildings'][0]['roofs'][0]['support'],
                         dict(kind='post', count=2, inset_ft=.6, size_ft=.5))
        self.assertIn('Terrace roof', words)

    def test_build_merge_and_legacy_choice_keep_fields(self):
        old = roofs.to_sections(roof())[0]
        incoming = roofs.to_sections(roof(False))[0]; incoming['rect'][2] += .5
        merged = twin_build._merge_list([old], [incoming], 'roof', {'openings': []}, {})[0]
        self.assert_fields(merged, old)
        self.assertEqual(merged['edges'][0]['overhang_ft'], 0)
        old['src']['person'] = True; b = {'roof': {'sections': [old], 'extensions': []}}
        self.assertTrue(twin_edit._choose_roof(b, old))
        self.assert_fields(b['roof']['choices'][0], old)

    def test_flat_normalization_and_choice_application_keep_fields(self):
        flat = bridge.flatten(house()); b = flat['buildings'][0]
        bad = b['roof']['sections'][0]; bad['support']['count'] = 100
        normalized, notes = twin_plan.normalize(flat)
        s = normalized['buildings'][0]['roof']['sections'][0]
        self.assertEqual(s['support']['count'], 2); self.assertTrue(notes)
        from services import twin_roof_derive
        choice = {k: copy.deepcopy(s[k]) for k in (*FIELDS, 'edges', 'kind', 'ridge', 'pitch', 'plate', 'overhang') if k in s}
        choice['rect'] = [0, 0, 20, 10]
        blocks = [dict(id='block', rect=choice['rect'], level='L1', plate=8, storey=0)]
        derived, _ = twin_roof_derive.derive_roof(blocks, {}, {}, [choice])
        self.assert_fields(derived[0], s)
        self.assertEqual(derived[0]['edges'][0]['overhang_ft'], 0)

    def test_random_supports_are_safe_and_idempotent(self):
        rng = random.Random(12491)
        values = [None, True, 'bad', [], {}, -1, 0, 2, 12, 20, float('nan'), float('inf')]
        for i in range(100):
            r = roof(); r['support'] = {key: copy.deepcopy(rng.choice(values)) for key in
                ('kind', 'count', 'inset_ft', 'spacing_ft', 'size_ft', 'style', 'at')}
            if i % 2 == 0:
                r['support'] = dict(kind=rng.choice(SUPPORT_KINDS[1:]), count=rng.randint(1, 12),
                                    inset_ft=rng.uniform(0, 6), size_ft=rng.uniform(.05, 3),
                                    at={'0': [rng.uniform(-10, 10), 3]})
            raw = house(); raw['buildings'][0]['roofs'][0] = copy.deepcopy(r)
            normalized, _ = model.normalize(raw)
            twice, _ = model.normalize(normalized)
            self.assertEqual(normalized, twice, f'full model case {i}')
            normalize_support(r, [])
            first = copy.deepcopy(r); notes = []; normalize_support(r, notes)
            self.assertEqual(first, r, f'case {i}'); self.assertEqual(notes, [])

    def test_old_awning_save_still_reopens_unchanged(self):
        m = house(False)
        awning = dict(id='old-awning', kind='awning', section='shade', x0=2, x1=8,
                      depth=3, pitch=3, eave=7, brackets=2)
        m['buildings'][0]['extensions'] = [awning]
        reopened = self.stored_round_trip(m)
        self.assertEqual(reopened['buildings'][0]['extensions'], [awning])
        flat = bridge.flatten(reopened)
        self.assertEqual(flat['buildings'][0]['roof']['extensions'], [awning])
        rebuilt, _ = bridge.assemble(flat, previous=reopened)
        self.assertEqual(rebuilt['buildings'][0]['extensions'], [awning])

    def test_parity_with_js_twelve_cases_and_expected_positions(self):
        cases = parity_cases(); self.assertEqual(len(cases), 12)
        partitioned = roofs.to_sections(cases[-1][1])
        self.assertGreater(len(partitioned), 1)
        self.assertGreater(sum(s['plane_edges']['y1'] == 4 for s in partitioned), 1)
        module = (ROOT / 'static/twin/roof_supports.js').as_uri()
        driver = f"import {{supportPoints}} from {json.dumps(module)};" + r"""
import {readFileSync} from 'node:fs';
console.log(JSON.stringify(JSON.parse(readFileSync(0,'utf8')).map(supportPoints)));
"""
        self.assertIsNotNone(shutil.which('node'), 'Node is required')
        result = subprocess.run(['node', '--input-type=module', '-e', driver],
            input=json.dumps([r for _, r in cases]), capture_output=True, text=True, check=True)
        actual = json.loads(result.stdout)
        expected = [support_points(r) for _, r in cases]
        for (name, _), js, py in zip(cases, actual, expected):
            self.assertEqual(js, py, name)
            print('PARITY ' + name + ' ' + json.dumps(py))
        for actual, u, at in zip(expected[0], [.6, 19.4], [[19.4, 10], [.6, 10]]):
            self.assertEqual(actual['edge'], 2)
            self.assertAlmostEqual(actual['u'], u, places=12)
            for a, b in zip(actual['at'], at): self.assertAlmostEqual(a, b, places=12)
        self.assertEqual(expected[10][0]['edge'], 1)
        self.assertEqual(expected[11][0]['edge'], 4)
        self.assertEqual([p['u'] for p in expected[7]], [2, 2, 2])
        self.assertFalse(is_supported({'support': {'kind': 'walls'}}))
        self.assertEqual(support_points(roof(False)), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)

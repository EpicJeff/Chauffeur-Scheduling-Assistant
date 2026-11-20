"""Hand porches through the real op route, persistence, history and build bridge."""
from copy import deepcopy
import os
import json
from pathlib import Path
import sys
import tempfile

os.environ.pop('HA_BASE_URL', None)
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_add_porch_')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_twin_model_ops_more import _house, _b, _client, _people, _enforced
from services import storage, twin_store as ts, twin_model_bridge as bridge, twin_porches, twin_model_ops as ops, twin_model_roofs as roofs

POLYGON = [[2, 0], [10, 0], [10, -6], [2, -6]]


def seed(model=None):
    storage.patch_settings({'house_twin': None, 'house_twin_cost': None})
    ts.push_round(bridge.flatten(model or _house()), 'build')


def post(client, operation, status=200):
    response = client.post('/api/house/editor/op', headers=_people()['parent'], json={'op': operation})
    assert response.status_code == status, response.text
    return response.json()


def add(client, roof='shed', **kwargs):
    return post(client, dict(op='add_porch', building='B1', level='L1', polygon=POLYGON, roof=roof, **kwargs))


def run():
    client = _client()
    with _enforced():
        for roof_kind, pitch in [('shed', 3), ('gable', 6), ('none', None)]:
            seed(); before = ts.current_model(); count = len(ts.rounds()); base = ts.current_id()
            result = add(client, roof_kind, host_wall='s1')
            assert result['words'].startswith('Added the porch.'), result['words']
            assert len(ts.rounds()) == count + 1
            building = _b(result['model'])
            room = next(r for r in building['rooms'] if r['kind'] == 'porch')
            detail = next(p for p in building['porches_detail'] if p['id'] == room['id'])
            assert room['name'] == 'Porch' and room['level'] == 'L1'
            assert room['foundation'] == twin_porches.DEFAULT
            assert detail['screened'] is False and detail['columns']
            assert all(c['shape'] == 'square' and c['size'] == .5 for c in detail['columns'])
            assert detail['polygon'] == room['polygon'] and detail['floor'] == 0
            # Feed the same polygon/detail through the real build bridge, then
            # compare every domain field; identity/provenance belongs to its author.
            flat = bridge.flatten(before)
            _b(flat)['porches'] = [deepcopy(detail)]
            built = _b(bridge.assemble(flat)[0])
            build_room = next(r for r in built['rooms'] if r['id'] == room['id'])
            for key in ('id', 'kind', 'name', 'level', 'polygon', 'foundation', 'state'):
                assert room[key] == build_room[key], (key, room, build_room)
            assert detail == next(p for p in built['porches_detail'] if p['id'] == room['id'])
            old_points = ops._positions(_b(before)); points = ops._positions(building)
            for wall in building['walls']:
                if wall['kind'] == 'solid':
                    a, b = (points[j] for j in wall['joints'])
                    assert any(ops._collinear_overlap(a, b, *(old_points[j] for j in old['joints']))
                               for old in _b(before)['walls'] if old['kind'] == 'solid')
            roofs = [r for r in building['roofs'] if r['id'] not in {r['id'] for r in _b(before)['roofs']}]
            assert len(roofs) == (0 if roof_kind == 'none' else 1)
            if roofs:
                roof = roofs[0]
                assert roof['pitch'] == pitch and roof['overhang'] == 1
                assert abs(sum(abs(p[0]) for p in roof['area']) - sum(abs(p[0]) for p in room['polygon'])) < 1e-8
                section = next(r for r in _b(result['plan'])['roof']['sections'] if r['roof'] == roof['id'])
                assert section['kind'] == roof_kind
                assert section.get('low_side') == 'y0' if roof_kind == 'shed' else section['ridge'] == 'y'
                assert section['rect'] == [2, -6, 10, 0]
            saved = ts.current_model()
            # Save/load uses the same public path a person uses in Houses.
            response = client.post('/api/house/editor/houses', headers=_people()['parent'], json={'name': 'Hand porch'})
            assert response.status_code == 200, response.text
            save_id = response.json()['save']['id']
            ts.revert(base)
            assert ts.current_model() == before, 'one undo removes the porch and its roof'
            loaded = client.post(f'/api/house/editor/houses/{save_id}/load', headers=_people()['parent'])
            assert loaded.status_code == 200, loaded.text
            assert ts.current_model() == saved
            print('  ok', roof_kind, 'build parity, roof, one history step, undo and named save/load')

        seed(); before = ts.current_model(); count = len(ts.rounds())
        for polygon, words in [
            ([[30, 0], [38, 0], [38, -6], [30, -6]], 'Draw the porch against an outside wall.'),
            ([[2, 0], [5, 0], [5, -6], [2, -6]], 'A porch needs at least 4 by 4 feet.'),
            ([[2, 0], [10, 0], [10, 6], [2, 6]], 'That overlaps a room on this floor.'),
            ([[12, 2], [12, 8], [18, 8], [18, 2]], 'Draw the porch against an outside wall.'),
        ]:
            error = post(client, dict(op='add_porch', building='B1', level='L1', polygon=polygon, roof='shed'), 400)
            assert error['error'] == words, error
            assert ts.current_model() == before and len(ts.rounds()) == count
        for extra in ({'roof': 'hip'}, {'host_wall': 'mid'}, {'level': 'missing'}):
            operation = dict(op='add_porch', building='B1', level='L1', polygon=POLYGON, roof='shed')
            operation.update(extra); post(client, operation, 400)
            assert ts.current_model() == before
        print('  ok refusals are atomic and use the required words')

        seed()
        concave = [[2, 0], [10, 0], [10, -6], [6, -6], [6, -3], [2, -3]]
        result = post(client, dict(op='add_porch', building='B1', level='L1', polygon=concave, roof='shed'))
        sections = _b(result['plan'])['roof']['sections']
        assert len(sections) == 2 and all(s['kind'] == 'shed' and s['low_side'] == 'y0' and s['pitch'] == 3 for s in sections), sections
        assert len({s['plate'] - s['pitch'] / 12 * s['rect'][1] for s in sections}) == 1, 'the concave shed must stay on one continuous plane'
        seed()
        angled = [[2, 0], [10, 0], [12, -6], [2, -6]]
        result = post(client, dict(op='add_porch', building='B1', level='L1', polygon=angled, roof='none'))
        assert next(r for r in _b(result['model'])['rooms'] if r['kind'] == 'porch')['polygon'] == angled
        assert not _b(result['model'])['roofs']
        seed()
        post(client, dict(op='add_wall', building='B1', level='L1', **{'from': [6, 0], 'to': [6, -6]}))
        before = ts.current_model(); count = len(ts.rounds())
        post(client, dict(op='add_porch', building='B1', level='L1', polygon=POLYGON, roof='shed'), 400)
        assert ts.current_model() == before and len(ts.rounds()) == count
        print('  ok concave shed, angled unroofed porch and atomic refusal of a divided footprint')

        seed(); rid = _b(ts.current_model())['rooms'][0]['id']
        post(client, dict(op='roof_over', building='B1', rooms=[rid], pitch=6))
        post(client, dict(op='set_material', building='B1', target={'room': rid, 'surface': 'floor'}, material={'id': 'wood_planks'}))
        original = ts.current_model()
        for kind, words in [('porch', 'Made this room a porch.'), ('room', 'Made this porch a room.')]:
            count = len(ts.rounds())
            result = post(client, dict(op='set_room_kind', building='B1', room=rid, kind=kind))
            assert result['words'].startswith(words), result['words']
            assert len(ts.rounds()) == count + 1
            building = _b(result['model']); room = next(r for r in building['rooms'] if r['id'] == rid)
            assert room['kind'] == kind
            assert building['walls'] == _b(original)['walls'] and building['roofs'] == _b(original)['roofs']
            if kind == 'porch':
                assert room['foundation'] == twin_porches.DEFAULT
                post(client, dict(op='set_material', building='B1', target={'porch': rid, 'part': 'column'}, material={'id': 'trim'}))
                custom = deepcopy(twin_porches.DEFAULT); custom['post_in'] = 10
                post(client, dict(op='set_porch_foundation', building='B1', id=rid, foundation=custom))
                again = post(client, dict(op='set_room_kind', building='B1', room=rid, kind='porch'))
                assert next(r for r in _b(again['model'])['rooms'] if r['id'] == rid)['foundation'] == custom
            else:
                assert 'foundation' not in room
                assert not any(p['id'] == rid for p in building['porches_detail'])
                assert room.get('porch_materials') == {'column': {'id': 'trim'}}, 'Type must keep the porch material overrides'
                expected = deepcopy(next(r for r in _b(original)['rooms'] if r['id'] == rid))
                expected['porch_materials'] = {'column': {'id': 'trim'}}
                for key in ('src',): expected.pop(key, None)
                actual = deepcopy(room); actual.pop('src', None)
                assert actual == expected
        post(client, dict(op='set_room_kind', building='B1', room=rid, kind='deck'), 400)
        restored = post(client, dict(op='set_room_kind', building='B1', room=rid, kind='porch'))
        detail = next(p for p in _b(restored['model'])['porches_detail'] if p['id'] == rid)
        assert detail['materials'] == {'column': {'id': 'trim'}}
        print('  ok Type both ways preserves the room, walls, roof and existing porch choices')

        household = bridge.assemble(json.loads((Path(__file__).parent / 'fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8')))[0]
        seed(household)
        before = ts.current_model(); base = ts.current_id(); count = len(ts.rounds())
        building = next(b for b in before['buildings'] if any(r['kind'] == 'porch' for r in b['rooms']))
        rid = next(r['id'] for r in building['rooms'] if r['kind'] == 'porch')
        result = post(client, dict(op='delete', building=building['id'], id=rid))
        after = next(b for b in result['model']['buildings'] if b['id'] == building['id'])
        assert result['words'].startswith('Deleted the porch.')
        assert not any(r['id'] == rid for r in after['rooms'])
        assert not any(p['id'] == rid for name in ('porches_detail', 'porches') for p in after.get(name, []))
        assert not after.get('porch') or after['porch'].get('id') != rid
        assert after['roofs'] == building['roofs']
        assert len(ts.rounds()) == count + 1
        ts.revert(base); assert ts.current_model() == before
        # A legacy leftover must remain until a person deletes it, and all
        # aliases for it must disappear in that one operation.
        seed()
        orphan = dict(id='orphan-porch', polygon=deepcopy(POLYGON), floor=0, level='L1', columns=[{'at': [2, -6], 'size': .5}])
        def leftover(model):
            b = _b(model)
            b['porches_detail'] = [deepcopy(orphan)]
            b['porches'] = [deepcopy(orphan)]
            b['porch'] = deepcopy(orphan)
            return model
        ts.update_model(leftover)
        before = ts.current_model(); base = ts.current_id()
        assert _b(before)['porches_detail'], 'no automatic load-time cleanup'
        result = post(client, dict(op='delete', building='B1', id='orphan-porch'))
        after = _b(result['model'])
        assert result['words'].startswith('Deleted the porch.')
        assert not after['porches_detail'] and not after.get('porches') and not after.get('porch')
        assert after['rooms'] == _b(before)['rooms'] and after['walls'] == _b(before)['walls']
        ts.revert(base); assert ts.current_model() == before
        print('  ok household porch deletion and legacy orphan cleanup are complete, explicit and undoable')


if __name__ == '__main__':
    try:
        run()
    finally:
        storage.db.close()

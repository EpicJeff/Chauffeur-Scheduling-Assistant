"""Per-item material edits, load repair, bridge and deletion protection."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop('HA_BASE_URL', None)
(ROOT / '.tmp-c').mkdir(exist_ok=True)
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(dir=ROOT / '.tmp-c', prefix='item-slots-')
from services import twin_model_bridge as bridge, twin_model_ops as ops, twin_model, twin_plan
from services import twin_materials as materials
from services.twin_surface_kinds import ITEM_PARTS

SLOT = {'id': 'red_brick_03'}
COLLECTIONS = {'opening': 'openings', 'porch': 'porches_detail', 'stair': 'stairs', 'item': 'items'}


def fixture():
    raw = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    model = bridge.assemble(raw)[0]
    b = model['buildings'][0]
    b['items'].append({'id': 'kitchen', 'kind': 'counter', 'name': 'Kitchen', 'level': 'L1',
                       'host': {'kind': 'floor', 'room': b['rooms'][0]['id'], 'u': 3, 'v': 3},
                       'rect': [1, 37, 5, 39], 'height': 3, 'position': [3, 38]})
    model['site']['pool'] = {'id': 'pool', 'polygon': [[0, 0], [30, 0], [30, 20], [0, 20]],
        'features': [{'id': 'spa', 'kind': 'spa', 'polygon': [[0, 0], [6, 0], [6, 6], [0, 6]]}]}
    return model


def targets(model):
    b = model['buildings'][0]
    return [(kind, collection, b[collection][0]['id']) for kind, collection in COLLECTIONS.items()]


def edit(model, target, slot=SLOT):
    return ops.apply(model, {'op': 'set_material', 'building': model['buildings'][0]['id'],
                             'target': target, 'material': slot})[0]


def refused(model, target, slot=SLOT):
    before = copy.deepcopy(model)
    try:
        edit(model, target, slot)
    except ops.Refused as exc:
        assert str(exc)
        assert model == before
        return str(exc)
    raise AssertionError(f'Accepted {target}')


def test_set_material_writes_each_item_target():
    model = fixture()
    for kind, collection, pid in targets(model):
        for part in ITEM_PARTS['fixture' if kind == 'item' else kind]:
            changed = edit(model, {kind: pid, 'part': part})
            piece = changed['buildings'][0][collection][0]
            assert piece['materials'] == {part: SLOT}, (kind, part, piece)
            cleared = edit(changed, {kind: pid, 'part': part}, None)
            assert 'materials' not in cleared['buildings'][0][collection][0]


def test_wrong_part_or_unknown_item_is_refused():
    model = fixture()
    for kind, collection, pid in targets(model):
        assert refused(model, {kind: pid, 'part': 'bogus'}) == 'Choose a surface for the material.'
        refused(model, {kind: 'missing', 'part': ITEM_PARTS['fixture' if kind == 'item' else kind][0]})
    refused(model, {'opening': targets(model)[0][2], 'part': 'cabinet'})
    refused(model, {'stair': targets(model)[2][2], 'part': 'pane'})


def test_clearing_one_part_keeps_its_neighbours():
    model = fixture()
    pid = targets(model)[0][2]
    changed = edit(model, {'opening': pid, 'part': 'pane'})
    changed = edit(changed, {'opening': pid, 'part': 'casing'}, {'id': 'painted_trim'})
    cleared = edit(changed, {'opening': pid, 'part': 'pane'}, None)
    assert cleared['buildings'][0]['openings'][0]['materials'] == {'casing': {'id': 'painted_trim'}}


def test_unknown_material_id_is_refused():
    model = fixture()
    for kind, _, pid in targets(model):
        refused(model, {kind: pid, 'part': ITEM_PARTS['fixture' if kind == 'item' else kind][0]}, {'id': 'missing'})


def test_builtin_id_is_accepted():
    model = fixture()
    slot = {'id': 'glass', 'color': '#88aacc'}
    changed = edit(model, {'opening': targets(model)[0][2], 'part': 'pane'}, slot)
    assert changed['buildings'][0]['openings'][0]['materials']['pane'] == slot


def test_hand_drawn_porch_room_gets_its_material_detail():
    model = fixture()
    b = model['buildings'][0]
    porch = next(r for r in b['rooms'] if r.get('kind') == 'porch')
    b['porches_detail'] = [p for p in b['porches_detail'] if p['id'] != porch['id']]
    changed = edit(model, {'porch': porch['id'], 'part': 'column'})
    flat = bridge.flatten(changed)
    assert next(p for p in flat['buildings'][0]['porches'] if p['id'] == porch['id'])['materials']['column'] == SLOT


def test_flatten_carries_item_materials():
    model = fixture()
    for kind, _, pid in targets(model):
        model = edit(model, {kind: pid, 'part': ITEM_PARTS['fixture' if kind == 'item' else kind][0]})
    flat = bridge.flatten(model)['buildings'][0]
    for collection in ('openings', 'porches', 'stairs', 'fixtures'):
        assert flat[collection][0]['materials'], collection


def test_load_resets_unknown_ids_in_every_new_slot():
    model = fixture()
    for kind, collection, _ in targets(model):
        parts = ITEM_PARTS['fixture' if kind == 'item' else kind]
        model['buildings'][0][collection][0]['materials'] = {parts[0]: {'id': 'missing'}, parts[1]: SLOT}
    pool = model['site']['pool']
    for piece in (pool, pool['features'][0]):
        piece['materials'] = {'water': {'id': 'missing'}, 'coping': SLOT}
    repaired, notes = twin_model.normalize(model)
    assert len([n for n in notes if 'material' in n.lower()]) == 6, notes
    for _, collection, _ in targets(repaired):
        assert list(repaired['buildings'][0][collection][0]['materials'].values()) == [SLOT]
    for piece in (repaired['site']['pool'], repaired['site']['pool']['features'][0]):
        assert piece['materials'] == {'coping': SLOT}
    flat, notes = twin_plan.normalize(bridge.flatten(model))
    for collection in ('openings', 'porches', 'stairs', 'fixtures'):
        assert list(flat['buildings'][0][collection][0]['materials'].values()) == [SLOT]


def test_pool_and_spa_water_slot_validate():
    model = fixture()
    for op in ({'op': 'update_site_shape', 'list': 'pool', 'id': 'pool'},
               {'op': 'update_pool_feature', 'id': 'spa'}):
        changed, _ = ops.apply(model, {**op, 'materials': {'water': SLOT}})
        pool = changed['site']['pool']
        assert (pool if op['op'] == 'update_site_shape' else pool['features'][0])['materials']['water'] == SLOT
        try:
            ops.apply(model, {**op, 'materials': {'water': {'id': 'missing'}}})
        except ops.Refused:
            pass
        else:
            raise AssertionError('Accepted missing water material')


def test_delete_refusal_names_new_surfaces():
    from test_twin_materials import Ctx, seed, create
    seed()
    with Ctx() as c:
        mid = create(c)['id']
        model = fixture()
        for kind, collection, pid in targets(model):
            part = {'opening': 'pane', 'porch': 'screen', 'stair': 'stair_rail', 'item': 'cabinet'}[kind]
            model['buildings'][0][collection][0].update(name=kind.title(), materials={part: {'id': mid}})
        model['site']['pool']['materials'] = {'water': {'id': mid}}
        model['site']['pool']['features'][0]['materials'] = {'water': {'id': mid}}
        model['buildings'][0]['openings'][1].update(name='Opening', materials={'pane': {'id': mid}})
        with patch.object(materials.twin_store, 'current_model', return_value=model):
            response = c.client.delete('/api/house/materials/' + mid, headers=c.mum)
            assert response.status_code == 400, response.text
            for label in ('Opening panes (2)', 'Stair stair rails', 'Item cabinets', 'Pool water', 'Spa water', '(1)'):
                assert label in response.text, response.text
        with patch.object(materials.twin_store, 'current_model', return_value={}), \
             patch.object(materials.twin_store, 'rounds', return_value=[{'id': 'historic'}]), \
             patch.object(materials, '_read', return_value=model):
            assert materials.uses(mid)['history'] is True


def test_existing_targets_unchanged():
    model = fixture()
    b = model['buildings'][0]
    for target, collection, field in [({'wall': b['walls'][0]['id'], 'side': 'left'}, 'walls', 'faces'),
        ({'room': b['rooms'][0]['id'], 'surface': 'floor'}, 'rooms', 'floor_material'),
        ({'roof': b['roofs'][0]['id']}, 'roofs', 'material'),
        ({'level': b['levels'][0]['id'], 'role': 'pane'}, 'levels', 'materials')]:
        assert edit(model, target)['buildings'][0][collection][0][field]
    assert edit(model, {'building': b['id'], 'role': 'pane'})['buildings'][0]['materials']['pane'] == SLOT


if __name__ == '__main__':
    tests = [f for name, f in list(globals().items()) if name.startswith('test_')]
    for test in tests:
        test()
        print('PASS', test.__name__)
    print(f'{len(tests)} passed')

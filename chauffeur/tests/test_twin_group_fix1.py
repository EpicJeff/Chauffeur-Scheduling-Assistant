"""Review regressions through production group operations and authenticated HTTP."""
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT.parent / '.tmp-group-fix1'
SCRATCH.mkdir(exist_ok=True, mode=0o777)
tempfile.tempdir = str(SCRATCH)
DATA = SCRATCH / 'data'
DATA.mkdir(exist_ok=True, mode=0o777)
os.environ['CHAUFFEUR_DATA_DIR'] = str(DATA)
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(ROOT))

from test_twin_model import building, box_joints, box_walls, room, rect, model
from test_twin_server_speed import house, ts, OP
from twin_editor_dom import PRELUDE, run_node
from services import twin_model, twin_model_bridge as bridge, twin_model_hosts as hosts
from services import twin_fixtures as lights, twin_effect_fixtures as effects

ENTITY = 'light.landscape'
DRIVER = r"""
const {groupTransform,transformOperations,deleteOperations}=await import(file('static/twin/editor/group_transform.js'));
const {deleteOperation}=await import(file('static/twin/editor/piece_operations.js'));
const {applyLocal}=await import(file('static/twin/editor/local_ops.js'));
const {hostPoint}=await import(file('static/twin/twin_hosts.js'));
const {pointAnchor}=await import(file('static/twin/editor/point_snap.js'));
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-7,`${a} != ${b}`);
const plan=input.plan;
let ops;
if(input.action==='delete'){
  ops=deleteOperations(plan,input.refs,input.model);
  for(const ref of input.refs){const single=deleteOperation(plan,ref,input.model);assert.ok(ops.some(op=>JSON.stringify(op)===JSON.stringify(single)),'single and group share delete operation');}
  assert.ok(ops.some(op=>op.op==='delete'&&op.piece===input.legacy),'legacy deletion path retained');
}else{
  ops=transformOperations(groupTransform(plan,input.refs,'move'),{by:[.5,0]});
  const next=applyLocal(plan,{op:'batch',ops}).plan, b=next.buildings[0];
  for(const [id,want] of Object.entries(input.positions||{})){
    const piece=b.items.find(p=>p.id===id)||b.openings.find(p=>p.id===id);
    const point=hostPoint(b,piece.host||piece,piece.offset||0);
    near(point[0],want[0]);near(point[1],want[1]);
  }
  for(const f of input.fixtures||[]){
    const op=ops.find(op=>op.id===f.id);assert.ok(op);
    if(f.snap){assert.ok(op.change.snap);for(const k of ['from','to']){near(op.change.snap.edge[k][0],f.snap.edge[k][0]+.5);near(op.change.snap.edge[k][1],f.snap.edge[k][1]);}}
    if(f.anchors)for(let i=0;i<f.anchors.length;i++){
      const target=[f.path[i][0]+.5,...f.path[i].slice(1)];
      const expected=pointAnchor(next,f.anchors[i].host,target);
      assert.ok(op.change.anchors[i],'rigid wall retains point binding');
      assert.deepEqual(op.change.anchors[i],expected,'binding is authored against moved geometry');
    }
    for(let i=0;i<f.path.length;i++)near(op.change.path[i][0],f.path[i][0]+.5);
  }
}
console.log('OPERATIONS '+JSON.stringify(ops));
"""


def generate(plan, refs, **values):
    code, output = run_node(PRELUDE + DRIVER, {
        'root': ROOT.as_posix(), 'plan': plan, 'refs': refs, **values})
    assert code == 0, output
    return json.loads(next(line.removeprefix('OPERATIONS ') for line in output.splitlines()
                           if line.startswith('OPERATIONS ')))


def ref(kind, id, bid='house'):
    return {'kind': kind, 'pieceId': id, **({'buildingId': bid} if bid else {})}


def geometry():
    b = building(box_joints(20, 30), box_walls(), [room('room-1', 'Room', rect(0, 0, 20, 30))])
    b['id'] = 'house'
    for wall in b['walls']:
        wall['height'] = 9
    b['items'] = [
        {'id': 'floor-prop', 'asset': 'chair', 'host': {'floor': 'room-1', 'u': .5, 'v': .5}},
        {'id': 'ceiling-prop', 'asset': 'lamp', 'host': {'ceiling': 'room-1', 'u': .5, 'v': .5}},
        {'id': 'wall-prop', 'asset': 'picture', 'host': {'wall': 'b', 'at': 5, 'z': 3, 'side': 'left'}},
    ]
    b['openings'] = [{'id': 'window', 'wall': 'b', 'kind': 'window', 'at': 10,
                      'width': 2, 'sill': 3, 'head': 7}]
    result, notes = twin_model.normalize(model(b))
    assert not notes, notes
    return result


def post(c, ops):
    before = len(ts.rounds())
    response = c.client.post(OP, headers=c.mum, json={'op': {'op': 'batch', 'ops': ops}})
    assert response.status_code == 200, response.text
    assert len(ts.rounds()) == before + 1
    return ts.current_model()


def assert_positions(saved, expected):
    b = saved['buildings'][0]
    for id, want in expected.items():
        piece = next(p for p in b['items'] + b['openings'] if p['id'] == id)
        point = hosts.world_point(b, piece.get('host', piece), piece.get('offset', 0))
        assert math.dist(point[:2], want) < 1e-7, (id, point, want)


def test_hosted_pieces_use_the_moved_room_and_adjacent_wall():
    for whole_room in (True, False):
        with house() as c:
            ts.update_model(lambda _: geometry())
            source = ts.current_model()
            walls = [ref('wall', id) for id in (('b', 'r', 't', 'l') if whole_room else ('l',))]
            ids = ('floor-prop', 'ceiling-prop') if whole_room else ('wall-prop', 'window')
            expected = {id: ([10.5, 15] if whole_room else [5.5 if id == 'wall-prop' else 10.5, .25 if id == 'wall-prop' else 0]) for id in ids}
            refs = walls + [ref('opening' if id == 'window' else 'item', id) for id in ids]
            ops = generate(bridge.flatten(source), refs, positions=expected)
            assert_positions(post(c, ops), expected)


def fixture(shape='line', effect=False, **values):
    return {'id': ('effect:' if effect else 'fixture:') + str(uuid4()), 'shape': shape,
            'ref': 'absolute', **({'type': 'waterfall'} if effect else {}), **values}


def test_line_fixture_bindings_survive_rigid_selected_wall_move():
    with house() as c:
        source = geometry()
        host = {'kind': 'wall', 'id': 'b', 'building': 'house'}
        a, z = lights._host_edges(source, host)[0]
        snapped = lights.validate(fixture(path=[a, z], snap={
            'host': {'kind': 'wall', 'id': 'b'}, 'edge': {'from': a[:2], 'to': z[:2]}, 't0': 0, 't1': 1}))
        path = [[3, 0, 9], [7, 0, 9]]
        frame = lights._anchor_frame(source, host)
        assert frame is not None
        anchors = [{'host': host, 'local': lights._anchor_transform(p, frame[1], inverse=True)} for p in path]
        anchored = lights.validate(fixture(path=path, anchors=anchors, offset_ft=1))
        effect = effects.validate(fixture(effect=True, path=path, anchors=anchors, offset_ft=1))
        source['light_fixtures'] = {ENTITY: [snapped, anchored]}
        source['effect_fixtures'] = [effect]
        ts.update_model(lambda _: source)
        source = ts.current_model()
        fixtures = source['light_fixtures'][ENTITY] + source['effect_fixtures']
        refs = [ref('wall', id) for id in ('b', 'r', 't', 'l')]
        refs += [ref('light_fixture', f['id'], None) for f in source['light_fixtures'][ENTITY]]
        refs += [ref('effect_fixture', effect['id'], None)]
        ops = generate(bridge.flatten(source), refs, fixtures=fixtures)
        saved = post(c, ops)
        rows = saved['light_fixtures'][ENTITY] + saved['effect_fixtures']
        for before, after in zip(fixtures, rows):
            assert not after.get('detached'), after
            for old, new in zip(before['path'], after['path']):
                assert math.dist([old[0]+.5, *old[1:]], new) < 1e-7, (old, new)
            if 'snap' in before:
                expected = next(op['change']['snap'] for op in ops if op.get('id') == before['id'])
                assert after.get('snap') == expected, (after, expected)
            if 'anchors' in before:
                expected = next(op['change']['anchors'] for op in ops if op.get('id') == before['id'])
                assert after.get('anchors') == expected, after
                for old_anchor, new_anchor, point in zip(before['anchors'], after['anchors'], after['path']):
                    assert new_anchor is not None and new_anchor['host'] == old_anchor['host'], after
                    frame = lights._anchor_frame(saved, new_anchor['host'])
                    resolved = lights._anchor_transform(new_anchor['local'], frame[1])
                    assert math.dist(point, resolved) < 1e-7, (point, resolved)

        def bound_rows(current):
            return [f for f in current['light_fixtures'][ENTITY] + current['effect_fixtures'] if 'anchors' in f]

        def check_offsets_and_bindings(current, shift):
            for f in bound_rows(current):
                assert f['offset_ft'] == 1 and all(f['anchors']), f
                for original, point, anchor in zip(path, f['path'], f['anchors']):
                    assert math.dist([original[0]+shift, original[1], 9], point) < 1e-7, f
                    frame = lights._anchor_frame(current, anchor['host'])
                    resolved = lights._anchor_transform(anchor['local'], frame[1])
                    assert math.dist(resolved, point) < 1e-7, (point, resolved)

        check_offsets_and_bindings(saved, .5)
        moved = post(c, [{'op': 'move_building', 'building': 'house', 'to': [.5, 0]}])
        check_offsets_and_bindings(moved, 1)
        for previous, current in zip(bound_rows(saved), bound_rows(moved)):
            assert previous['anchors'] == current['anchors'], 'later rigid host transport keeps bindings'
        fixtures = moved['light_fixtures'][ENTITY] + moved['effect_fixtures']
        repeated = generate(bridge.flatten(moved), refs, fixtures=fixtures)
        check_offsets_and_bindings(post(c, repeated), 1.5)


def test_group_delete_uses_the_single_legacy_builder_for_building_and_rect_roof():
    for kind, id in (('building', 'house'), ('roof', 'roof-1')):
        with house() as c:
            plan = json.loads((ROOT / 'tests/fixtures/twin_edit_house.plan.json').read_text(encoding='utf8'))
            plan['site']['planting'] = [{'id': 'delete-tree', 'asset': 'tree', 'at': [50, 50]}]
            ts.push_round(plan, 'build')
            current = ts.current_model()
            ops = generate(bridge.flatten(current), [ref(kind, id), ref('planting', 'delete-tree', None)],
                           action='delete', model=current if kind == 'building' else None, legacy=id)
            saved = post(c, ops)
            assert not saved['site']['planting']
            if kind == 'building':
                assert not saved['buildings']
            else:
                assert all(p['id'] != id for b in saved['buildings'] for p in b['roofs'])


if __name__ == '__main__':
    import traceback
    tests = [value for key, value in globals().items() if key.startswith('test_') and callable(value)]
    failed = 0
    for test in tests:
        try:
            test()
            print('PASS', test.__name__)
        except Exception:
            failed += 1
            traceback.print_exc()
    print(f'{len(tests)-failed}/{len(tests)} passed')
    sys.exit(bool(failed))

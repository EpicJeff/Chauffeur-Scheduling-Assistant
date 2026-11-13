"""Real HTTP and persisted history checks; all data is isolated by the HA fixture."""
import base64
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import traceback
from unittest.mock import patch

from test_twin_ha_routes import Ctx, seed, ts
from services import auth, storage, twin_house_saves as saves
from PIL import Image

URL = '/api/house/editor/houses'


def call(c, method, suffix='', **kwargs):
    result = c.client.request(method, URL + suffix, headers=c.mum, **kwargs)
    assert result.status_code == 200, (result.status_code, result.text)
    return result


def save(c, name='Before experiments', **kwargs):
    return call(c, 'POST', json={'name': name, **kwargs}).json()['save']


def move(x):
    def mutate(model):
        model['buildings'][0]['position'][0] = x
        return model
    ts.update_model(mutate)


def test_save_list_metadata_and_atomic_file():
    seed()
    ts.set_front_bearing(73)
    with Ctx() as c:
        model, state, rounds = ts.current_model(), ts.house_state(ts._place_state()), len(ts.rounds())
        image = io.BytesIO(); Image.new('RGB', (240, 160), '#123456').save(image, 'PNG')
        picture = 'data:image/png;base64,' + base64.b64encode(image.getvalue()).decode()
        first = save(c, thumbnail=picture)
        second = save(c, 'Later')
        rows = call(c, 'GET').json()['saves']
        assert [r['id'] for r in rows] == [second['id'], first['id']]
        assert first['name'] == 'Before experiments' and first['created_by'] == 'mum'
        assert first['summary'] == {'building_count': 1, 'room_count': 2}
        assert first['thumbnail'] == picture and first['created_at']
        path = saves._path(first['id'])
        assert first['size'] == path.stat().st_size and not list(path.parent.glob('*.tmp'))
        document = json.loads(path.read_text(encoding='utf-8'))
        assert document['model'] == model and document['state'] == state
        assert not {'rounds', 'fixes', 'tombstones', 'generation', 'perf'} & document['state'].keys()
        assert len(ts.rounds()) == rounds


def test_load_one_round_undo_and_redo_restore_model_and_place():
    seed(); ts.set_front_bearing(45)
    with Ctx() as c:
        original = ts.current_model(); original_place = ts.place()
        saved = save(c)
        move(444); ts.set_front_bearing(270)
        ts.add_building('Experiment shed', 'shed')
        before_model, before_place = ts.current_model(), ts.place()
        before_id, count = ts.current_id(), len(ts.rounds())
        response = call(c, 'POST', f'/{saved["id"]}/load').json()
        assert len(ts.rounds()) == count + 1 and ts.current_id() == response['round']
        assert ts.current_model() == original and ts.place() == original_place
        assert ts.rounds()[-1]['kind'] == 'load' and ts.rounds()[-1]['note'] == 'Loaded "Before experiments"'
        undo = c.client.post('/api/house/twin/revert', headers=c.mum, json={'round': before_id})
        assert undo.status_code == 200, undo.text
        assert ts.current_model() == before_model and ts.place() == before_place
        redo = c.client.post('/api/house/twin/revert', headers=c.mum, json={'round': response['round']})
        assert redo.status_code == 200 and ts.current_model() == original and ts.place() == original_place
        assert len(call(c, 'GET').json()['saves']) == 1


def test_rename_delete_and_filename():
    seed()
    with Ctx() as c:
        saved = save(c)
        renamed = call(c, 'PATCH', f'/{saved["id"]}', json={'name': '  A / new house 🏠  '}).json()['save']
        assert renamed['name'] == 'A / new house 🏠'
        assert renamed['created_at'] == saved['created_at'] and renamed['id'] == saved['id']
        result = call(c, 'GET', f'/{saved["id"]}/download')
        assert 'attachment;' in result.headers['content-disposition']
        assert '.chauffeur-house.json' in result.headers['content-disposition']
        assert result.json()['name'] == renamed['name']
        model = ts.current_model()
        call(c, 'DELETE', f'/{saved["id"]}')
        assert call(c, 'GET').json()['saves'] == [] and ts.current_model() == model
        assert c.client.post(URL + f'/{saved["id"]}/load', headers=c.mum).status_code == 400


def test_download_upload_load_round_trip_and_source_references():
    seed(); ts.set_front_bearing(135)
    image = io.BytesIO(); Image.new('RGB', (8, 8)).save(image, 'PNG')
    source = ts.save_source('photo', 'front.png', image.getvalue(), part='house')
    with Ctx() as c:
        original, state = ts.current_model(), ts.house_state(ts._place_state())
        document = call(c, 'GET', '/current/download').json()
        assert document['format'] == 'chauffeur-house' and document['format_version'] == 1
        assert document['model'] == original and document['state'] == state
        assert document['state']['sources'][0]['id'] == source
        count = len(ts.rounds())
        result = call(c, 'POST', '/upload', files={'file': ('house.chauffeur-house.json', json.dumps(document), 'application/json')}).json()
        assert result['save']['created_by'] == 'mum' and len(ts.rounds()) == count
        assert ts.current_model() == original  # upload never loads
        move(999); ts.set_front_bearing(33)
        call(c, 'POST', f'/{result["save"]["id"]}/load')
        assert ts.current_model() == original and ts.house_state(ts._place_state()) == state


def test_bad_oversized_and_unsupported_uploads_do_not_mutate():
    seed()
    with Ctx() as c:
        document = call(c, 'GET', '/current/download').json()
        invalid = [b'not json', b'[]', b'{}', json.dumps({**document, 'format_version': 99}).encode(),
                   json.dumps({**document, 'model': {'schema': 'unknown'}}).encode(),
                   json.dumps({**document, 'state': {'place': []}}).encode(),
                   json.dumps({**document, 'model': {**document['model'], 'units': 'm'}}).encode()]
        bad_placement = deepcopy(document)
        bad_placement['state']['place']['lot']['placement'] = {'confirmed': True}
        invalid.append(json.dumps(bad_placement).encode())
        invalid.append(b'{"format":NaN}')
        for body in invalid:
            result = c.client.post(URL + '/upload', headers=c.mum, files={'file': ('bad.json', body)})
            assert result.status_code == 400 and result.json()['detail'], result.text
        result = c.client.post(URL + '/upload', headers=c.mum, files={'file': ('huge.json', b' ' * (saves.MAX_BYTES + 1))})
        assert result.status_code == 413 and '20 MB' in result.text
        assert call(c, 'GET').json()['saves'] == [] and ts.current_model() == document['model']


def test_lot_sheet_registration_photo_suggestions_and_legacy_bridge():
    from services import twin_model_bridge, twin_place_reads, twin_register
    seed()
    sid = 'a' * 32
    row = ts._place_state()
    row['sources'] = [{'id': sid, 'kind': 'drawing', 'filename': 'plot.pdf', 'pages': 1, 'mime': 'application/pdf', 'part': 'lot'}]
    row['page_roles'] = [{'source': sid, 'page': 1, 'box': None, 'role': 'plot', 'building': 'lot', 'level': None}]
    reg = twin_register.make(.1)
    row['registrations'] = [{'source': sid, 'page': 1, 'level': None, 'reg': reg}]
    fragment = json.loads((Path(__file__).parent / 'fixtures/twin_reads/plot.json').read_text(encoding='utf-8'))
    read = twin_place_reads.plot_read_record({'source': sid, 'page': 1, 'box': None},
                                           {'box': [0, 0, 1, 1], 'master': [5100, 3300]}, fragment)
    row['place']['lot'].update(read=read, front_bearing_deg=93, placement={
        'source': sid, 'page': 1, 'box': None, 'outline': read['lot'],
        'street_edge': read['street_edge'], 'registration': read['registration'], 'confirmed': True})
    row['place']['photo_read'] = {'photos': [], 'shells': [], 'cost': .05}
    storage.patch_settings({'house_twin': row})
    with Ctx() as c:
        document = call(c, 'GET', '/current/download').json()
        document['model'] = twin_model_bridge.flatten(document['model'])
        result = call(c, 'POST', '/upload', files={'file': ('legacy.json', json.dumps(document))}).json()
        assert saves.download(result['save']['id'])['model']['schema'].endswith('/3')
        ts.set_front_bearing(12)
        call(c, 'POST', f'/{result["save"]["id"]}/load')
        assert ts.house_state(ts._place_state()) == document['state']


def test_names_thumbnail_and_ids_are_validated():
    seed()
    with Ctx() as c:
        for title in ('', ' ', 'x' * 81, None, 1):
            assert c.client.post(URL, headers=c.mum, json={'name': title}).status_code == 400
        for thumbnail in ('data:image/svg+xml,<svg>', 'data:image/png;base64,broken', 'x' * (saves.MAX_THUMBNAIL_BYTES * 2)):
            assert c.client.post(URL, headers=c.mum, json={'name': 'Bad thumbnail', 'thumbnail': thumbnail}).status_code == 400
        assert c.client.delete(URL + '/invalid-id', headers=c.mum).status_code == 400
        assert not call(c, 'GET').json()['saves']


def test_all_routes_are_parent_only():
    seed()
    with Ctx() as c:
        sid = save(c)['id']
        routes = [('GET', ''), ('POST', ''), ('POST', '/upload'), ('GET', '/current/download'),
                  ('GET', f'/{sid}/download'), ('POST', f'/{sid}/load'), ('PATCH', f'/{sid}'), ('DELETE', f'/{sid}')]
        for method, suffix in routes:
            assert auth.resolve(method, URL + suffix) == auth.PARENTS
            for headers in (c.kid, c.panel, c.visitor):
                result = c.client.request(method, URL + suffix, headers=headers, json={'name': 'No'})
                assert result.status_code == 403, (method, suffix, result.text)


def test_invalid_model_fields_reset_with_notes_on_load_and_upload():
    seed()
    with Ctx() as c:
        saved = save(c)
        document = saves.download(saved['id'])
        document['model']['ha_display'] = {'devices': {'d1': {'show_as': 'sideways'}}}
        document['model']['buildings'][0]['rotation'] = 'bad'
        ts.atomic_json(saves._path(saved['id']), document)
        response = call(c, 'POST', f'/{saved["id"]}/load').json()
        assert any('rotation' in note for note in response['notes'])
        assert any('display' in note for note in response['notes'])
        assert ts.current_model()['buildings'][0]['rotation'] == 0
        response = call(c, 'POST', '/upload', files={'file': ('old.json', json.dumps(document))}).json()
        assert response['notes']
        assert saves.download(response['save']['id'])['model'] == ts.current_model()


def test_running_build_refused_and_saves_survive_start_over():
    seed()
    with Ctx() as c:
        saved = save(c); count = len(ts.rounds())
        with patch.object(ts, 'build_running', return_value=True):
            response = c.client.post(URL + f'/{saved["id"]}/load', headers=c.mum)
            assert response.status_code == 409, response.text
        assert len(ts.rounds()) == count
        ts.start_over()
        assert len(call(c, 'GET').json()['saves']) == 1
        call(c, 'POST', f'/{saved["id"]}/load')
        assert ts.current_model() and len(ts.rounds()) == 1


def test_failed_publication_leaves_current_house_and_no_partial_save():
    seed()
    with Ctx() as c:
        model = ts.current_model(); count = len(ts.rounds())
        with patch('services.twin_store.os.replace', side_effect=OSError('disk unavailable')):
            try:
                saves.save_current('Failed', 'mum')
                raise AssertionError('write should fail')
            except OSError:
                pass
        assert not call(c, 'GET').json()['saves']
        assert not list((Path(ts.DATA_DIR) / 'houses').glob('*.tmp'))
        saved = save(c)
        with patch.object(ts, '_save', side_effect=OSError('settings unavailable')):
            try:
                saves.load(saved['id'])
                raise AssertionError('load should fail')
            except OSError:
                pass
        assert ts.current_model() == model and len(ts.rounds()) == count


def test_ordinary_undo_keeps_later_photo_and_sheet_roles():
    import pypdfium2 as pdfium
    from services import twin_register
    seed()
    move(111)
    target = ts.current_id()
    image = io.BytesIO(); Image.new('RGB', (8, 8)).save(image, 'PNG')
    photo = ts.save_source('photo', 'later.png', image.getvalue(), part='house')
    pdf = pdfium.PdfDocument.new()
    try:
        pdf.new_page(72, 72)
        data = io.BytesIO(); pdf.save(data)
        drawing = ts.save_source('drawing', 'later-plot.pdf', data.getvalue(), part='lot')
    finally:
        pdf.close()
    ts.set_page_roles([{'source': drawing, 'page': 1, 'building': 'lot', 'role': 'plot'}])
    ts.set_registration(drawing, 1, None, twin_register.make(.1))
    sources, roles, registrations = ts.sources(), ts.page_roles(), ts.registrations()
    assert {s['id'] for s in sources} == {photo, drawing}
    move(222)
    with Ctx() as c:
        result = c.client.post('/api/house/twin/revert', headers=c.mum, json={'round': target})
        assert result.status_code == 200, result.text
        assert ts.current_model()['buildings'][0]['position'][0] == 111
        assert ts.sources() == sources and ts.page_roles() == roles
        assert ts.registrations() == registrations


def test_ordinary_edits_write_no_state_companion():
    seed()
    with patch.object(ts, 'atomic_json', wraps=ts.atomic_json) as write_state:
        for x in (111, 222, 333):
            move(x)
        write_state.assert_not_called()
    assert not list((Path(ts.DATA_DIR) / 'rounds').glob('*.state.json'))


def test_ordinary_undo_ignores_existing_companion_without_crossing_load():
    seed(); move(111)
    target = ts.current_id()
    ts.atomic_json(ts.round_state_path(target), ts.house_state(ts._place_state()))
    ts.set_front_bearing(235)
    ts.add_building('Later shed', 'shed')
    before = ts.place()
    move(222)
    with Ctx() as c:
        _revert(c, target)
        assert ts.place() == before


def _load_boundary(c):
    ts.set_front_bearing(45)
    saved = save(c)
    loaded_model, loaded_place = ts.current_model(), ts.place()
    move(111)
    first_edit = ts.current_id()
    move(222)
    ts.set_front_bearing(270)
    ts.add_building('Experiment shed', 'shed')
    before_id, before_model, before_place = ts.current_id(), ts.current_model(), ts.place()
    result = call(c, 'POST', f'/{saved["id"]}/load').json()
    assert {p.name for p in (Path(ts.DATA_DIR) / 'rounds').glob('*.state.json')} == {
        f'{before_id}.state.json', f'{result["round"]}.state.json'}
    return first_edit, before_id, before_model, before_place, result['round'], loaded_model, loaded_place


def _revert(c, target):
    result = c.client.post('/api/house/twin/revert', headers=c.mum, json={'round': target})
    assert result.status_code == 200, result.text
    return result.json()['round']


def test_undo_past_load_restores_pre_load_place():
    seed()
    with Ctx() as c:
        _, before_id, before_model, before_place, _, _, _ = _load_boundary(c)
        _revert(c, before_id)
        assert ts.current_model() == before_model
        assert ts.place()['lot'] == before_place['lot']
        assert ts.place()['buildings'] == before_place['buildings']


def test_redo_onto_load_restores_loaded_place():
    seed()
    with Ctx() as c:
        _, before_id, _, before_place, load_id, loaded_model, loaded_place = _load_boundary(c)
        _revert(c, before_id)
        assert ts.place() == before_place
        _revert(c, load_id)
        assert ts.current_model() == loaded_model
        assert ts.place()['lot'] == loaded_place['lot']
        assert ts.place()['buildings'] == loaded_place['buildings']
        assert {p.name for p in (Path(ts.DATA_DIR) / 'rounds').glob('*.state.json')} == {
            f'{before_id}.state.json', f'{load_id}.state.json'}


def test_undo_two_steps_back_past_load():
    seed()
    with Ctx() as c:
        first_edit, _, _, before_place, _, _, _ = _load_boundary(c)
        assert not ts.round_state_path(first_edit).exists()
        _revert(c, first_edit)
        assert ts.current_model()['buildings'][0]['position'][0] == 111
        assert ts.place() == before_place


def test_ordinary_undo_after_undoing_load_keeps_new_place_changes():
    seed()
    with Ctx() as c:
        first_edit, before_id, _, _, _, _, _ = _load_boundary(c)
        _revert(c, before_id)
        ts.set_front_bearing(123)
        ts.add_building('Added after Undo', 'shed')
        before = ts.place()
        _revert(c, first_edit)
        assert ts.place() == before


def test_crossing_load_without_any_companion_falls_back_to_registry():
    seed()
    with Ctx() as c:
        first_edit, _, _, _, _, _, _ = _load_boundary(c)
        ts.set_front_bearing(123)
        before = ts.place()
        with patch.object(ts, 'round_state_path', side_effect=lambda rid: Path(ts.DATA_DIR) / 'missing' / f'{rid}.json'):
            _revert(c, first_edit)
        assert ts.place() == before


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    passed = 0
    for test in tests:
        try:
            test(); passed += 1; print('ok  ', test.__name__)
        except Exception:
            print('FAIL', test.__name__); traceback.print_exc(limit=7)
    print(f'{passed}/{len(tests)} passed')
    sys.exit(passed != len(tests))

"""Real edits, persisted files and HTTP session lifecycle, always on isolated data."""
import base64
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='twin_history_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_twin_ha_routes import Ctx
from test_twin_edit import house
from services import storage, twin_store as ts, twin_edit, twin_history, twin_house_saves as saves
from services import twin_draft, twin_director, twin_cost
from PIL import Image

URL = '/api/house/editor/session'


def seed(count=1, *, cleaned=True):
    ts.DATA_DIR = str(Path(tempfile.mkdtemp(prefix='history_store_')) / 'twin')
    storage.patch_settings({'house_twin': None})
    ts.push_round(house(), 'build')
    row = ts._place_state()
    # Old installations have no marker; create their real on-disk rounds.
    model = ts.current_model()
    for rid in range(2, count + 1):
        ts.atomic_json(Path(ts.DATA_DIR) / 'rounds' / f'{rid}.json', model)
        row['rounds'].append({**row['rounds'][0], 'id': rid})
    row['current'] = count
    if cleaned:
        row['history_cleaned'] = True
    else:
        row.pop('history_cleaned', None)
    ts._save(row)


def edit(i):
    opening = next(o for o in ts.current()['buildings'][0]['openings'] if o['id'] == 'opening-1')
    return twin_edit.save({'op': 'set', 'piece': 'opening-1', 'field': 'width',
                           'value': 4 if opening['width'] == 3 else 3}, 'mum')


def session(c):
    result = c.client.post(URL, headers=c.mum)
    assert result.status_code == 200, result.text
    return result.json()


def test_sixty_real_edits_prune_files_and_allow_kept_undo():
    seed()
    kept_model = None
    for i in range(60):
        result = edit(i)
        if i == 20:
            kept_id, kept_model = result['round'], ts.current_model()
    current = ts.current_model()
    assert [r['id'] for r in ts.rounds()] == list(range(12, 62))
    assert ts.current_id() == 61 and ts.current_model() == current
    root = Path(ts.DATA_DIR) / 'rounds'
    assert sorted(int(p.stem) for p in root.glob('*.json')) == list(range(12, 62))
    retained_dir, retained_row = ts.DATA_DIR, ts._state()
    seed()
    control = ts._state(); control['history_cleaned'] = False; ts._save(control)
    for i in range(60):
        edit(i)
    assert len(ts.rounds()) == 61 and ts.current_model() == current, 'Pruning preserves the unbounded edit result'
    ts.DATA_DIR = retained_dir; ts._save(retained_row)
    ts.revert(kept_id)
    assert ts.current_model() == kept_model and ts.current_id() == 62
    try:
        ts.revert(1)
    except KeyError:
        pass
    else:
        raise AssertionError('A dropped round must refuse undo')


def test_load_anchor_survives_then_is_replaced_and_unlinks_companions():
    seed()
    ts.set_front_bearing(45)
    saved = saves.save_current('Original', 'mum')
    ts.set_front_bearing(270)
    for i in range(20):
        edit(i)
    before_load = ts.current_id()
    before_model, before_place = ts.current_model(), ts.place()
    load = saves.load(saved['id'])['round']
    for i in range(49):
        edit(i)
    # The pre-load companion has just left the window and remains its anchor.
    assert before_load in {r['id'] for r in ts.rounds()}
    assert ts.round_state_path(before_load).exists()
    ts.revert(before_load)
    assert ts.place() == before_place and ts.current_model() == before_model
    ts.revert(load)
    assert ts.place()['lot']['front_bearing_deg'] == 45
    for i in range(51):
        edit(i)
    assert not ts.round_state_path(before_load).exists()
    assert not (Path(ts.DATA_DIR) / 'rounds' / f'{before_load}.json').exists()
    assert ts.round_state_path(load).exists()


def test_pruned_runs_stay_finished_and_director_cap_refuses_before_credentials():
    seed()
    run = 'finished-run'
    root = Path(ts.DATA_DIR) / 'runs' / run
    root.mkdir(parents=True)
    ts.atomic_json(root / 'run.json', {'inputs': {'drawings': []}})
    ts.push_round(ts.current(), 'draft', run=run)
    for _ in range(twin_cost.ROUND_CAP):
        ts.push_round(ts.current(), 'director', run=run)
    for i in range(51):
        edit(i)
    assert not any(r.get('run') == run for r in ts.rounds())
    assert twin_draft._unfinished_run({'drawings': []}) is None
    image = io.BytesIO()
    Image.new('RGB', (2, 2)).save(image, 'PNG')
    with patch.object(twin_director.model_pools, 'credentials', side_effect=AssertionError('No model credentials')):
        result = twin_director.critique(run, [base64.b64encode(image.getvalue()).decode()], ['Front'])
    assert result == (None, 'round cap reached'), result
    ts.start_over()
    assert ts.director_round_count(run) == 0 and not ts.draft_finished(run)


def test_fixes_migrate_keep_pruned_rows_rollback_refusals_and_clear():
    seed()
    legacy = {'round': 1, 'path': 'old', 'reason': 'Before JSONL'}
    row = ts._state(); row['fixes'] = [legacy]; ts._save(row)
    edit(0)
    assert ts._state()['fixes'] == [] and ts.fixes()[0] == legacy
    first = deepcopy(ts.fixes())
    for i in range(60):
        edit(i)
    assert ts.fixes()[:len(first)] == first
    assert not any(r['id'] == 2 for r in ts.rounds())
    before, current = ts.fixes(), ts.current_id()
    with patch.object(ts, '_save', side_effect=OSError('Settings failed')):
        try:
            edit(1)
        except OSError:
            pass
        else:
            raise AssertionError('Save must refuse')
    assert ts.fixes() == before and ts.current_id() == current
    oldest = ts.rounds()[0]['id']
    assert (Path(ts.DATA_DIR) / 'rounds' / f'{oldest}.json').exists(), 'Failed settings save never unlinks old rounds'
    try:
        twin_edit.save({'op': 'set', 'piece': 'missing', 'field': 'width', 'value': 5}, 'mum')
    except ValueError:
        pass
    assert ts.fixes() == before
    ts.start_over()
    assert ts.fixes() == [] and not (Path(ts.DATA_DIR) / 'fixes.jsonl').exists()


def test_cleanup_real_route_saves_before_removing_300_rounds_once_without_ha():
    seed(300, cleaned=False)
    before = ts.current_model()
    row = ts._state(); row['fixes'] = [{'round': 1, 'reason': 'Legacy'}]; ts._save(row)
    with Ctx(available=False) as c:
        for headers in (c.kid, c.visitor, c.panel):
            assert c.client.post(URL, headers=headers).status_code == 403
        result = session(c)
        assert result['cleaned'] == 250 and result['saved']['name'].startswith('Before cleanup ')
        assert result['saved']['auto'] is False
        assert saves.download(result['saved']['id'])['model'] == before
        assert len(ts.rounds()) == 50 and ts.current_model() == before
        assert len(list((Path(ts.DATA_DIR) / 'rounds').glob('*.json'))) == 50
        assert ts.fixes() == [{'round': 1, 'reason': 'Legacy'}]
        assert session(c) == {'cleaned': 0, 'saved': None}
        assert len(saves.list_saves()) == 1
        assert c.client.get('/api/house/twin/rounds/1', headers=c.mum).status_code == 404


def test_failed_cleanup_save_leaves_history_and_fixes_intact_even_on_next_edit():
    seed(300, cleaned=False)
    before = ts.rounds()
    with Ctx(available=False) as c, patch.object(saves, 'save_current', side_effect=OSError('Disk full')):
        assert c.client.post(URL, headers=c.mum).status_code == 500
    assert ts.rounds() == before and not ts._state()['history_cleaned']
    edit(0)
    assert len(ts.rounds()) == 301
    assert (Path(ts.DATA_DIR) / 'rounds' / '1.json').exists()


def test_session_auto_saves_compare_models_and_keep_ten_automatic_and_named():
    seed()
    named = saves.save_current('Keep me', 'mum')
    with Ctx(available=False) as c:
        assert session(c)['saved'] is None
        # Different round, identical model: ids are not the comparison.
        ts.revert(ts.current_id())
        assert session(c)['saved'] is None
        autos = []
        for i in range(11):
            edit(i)
            result = session(c)
            autos.append(result['saved']['id'])
            assert result['saved']['auto'] is True
            assert saves.download(autos[-1])['auto'] is True
        remaining = saves.list_saves()
        assert len(remaining) == 11
        assert {s['id'] for s in remaining} == {named['id'], *autos[1:]}
        assert not saves._path(autos[0]).exists()


def test_small_and_empty_houses_mark_cleaned_without_cleanup_copy():
    seed(50, cleaned=False)
    row = storage.get_settings()['house_twin']; row['history_cleaned'] = False; ts._save(row)
    with Ctx(available=False) as c:
        result = session(c)
        assert result['cleaned'] == 0 and result['saved']['auto']
        assert not any(s['name'].startswith('Before cleanup') for s in saves.list_saves())
        assert ts._state()['history_cleaned']
        ts.start_over()
        assert session(c) == {'cleaned': 0, 'saved': None}


def test_settings_size_stays_bounded_from_60_to_200_real_edits():
    seed()
    for i in range(200):
        edit(i)
        if i == 59:
            size60 = len(json.dumps(storage.get_settings()['house_twin']))
    size200 = len(json.dumps(storage.get_settings()['house_twin']))
    assert size200 < size60 * 1.15, (size60, size200)
    assert len(ts.rounds()) == 50 and ts._state()['fixes'] == []
    print(f'  settings bytes: 60 edits={size60}, 200 edits={size200}')


def test_unlink_failure_does_not_refuse_published_edit_and_current_is_protected():
    seed(50)
    original = Path.unlink
    def unlink(path, *args, **kwargs):
        if path == Path(ts.DATA_DIR) / 'rounds' / '1.json':
            raise OSError('File busy')
        return original(path, *args, **kwargs)
    with patch.object(Path, 'unlink', unlink):
        edit(0)
    assert ts.current_id() == 51 and len(ts.rounds()) == 50
    # Paid stale results can append without changing the current house.
    row = ts._state(); row['current'] = 2; ts._save(row)
    for _ in range(52):
        ts.push_round(ts.current(), 'director', base=1)
    assert ts.current_id() == 2 and any(r['id'] == 2 for r in ts.rounds())
    assert ts.rounds()[-1]['id'] == 103


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    passed = 0
    for test in tests:
        try:
            test(); passed += 1; print('ok  ', test.__name__, flush=True)
        except Exception:
            print('FAIL', test.__name__, flush=True); traceback.print_exc(limit=7)
    print(f'{passed}/{len(tests)} passed')
    sys.exit(passed != len(tests))

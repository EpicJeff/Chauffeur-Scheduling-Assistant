"""The place registry for the house editor (plan .superpowers/sdd/
2026-11-07-house-editor-slice-1b-i, Task 1): buildings of any kind and the
lot, page roles that fit each part, documents and photos per part, the
migration from slice 1, and the rules for renaming and removing a building.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_place.py
"""
import io
import math
import os
import shutil
import sys
import tempfile
import traceback

# Forced, never setdefault: these scenarios wipe house_twin and the twin files.
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_place_')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import storage  # noqa: E402
from services import twin_plan  # noqa: E402
from services import twin_store as ts  # noqa: E402
from services import twin_edit  # noqa: E402
from services import twin_place as tp  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_edit_house.plan.json')

SAME_PART = 'That page role does not fit this part of your place.'


def check(cond, msg):
    # Local on purpose: tests/harness.py stubs storage.get_settings.
    if not cond:
        raise AssertionError(msg)


def expect_value_error(fn, message=None, starts=None):
    try:
        fn()
    except ValueError as exc:
        text = str(exc)
        if message is not None:
            check(text == message, f'expected {message!r}, got {text!r}')
        if starts is not None:
            check(text.startswith(starts), f'expected a message starting {starts!r}, got {text!r}')
        return text
    raise AssertionError(f'expected ValueError{" " + repr(message) if message else ""}')


def _fresh():
    storage.patch_settings({'house_twin': None, 'house_twin_cost': None})
    shutil.rmtree(ts.DATA_DIR, ignore_errors=True)


def _pdf(pages=2, w=612, h=396):
    """A blank PDF built with PIL, one white raster per page (8.5 x 5.5 inches)."""
    from PIL import Image
    images = [Image.new('RGB', (w, h), 'white') for _ in range(pages)]
    buf = io.BytesIO()
    images[0].save(buf, format='PDF', save_all=True, append_images=images[1:], resolution=72)
    return buf.getvalue()


def _png(w=64, h=48):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (w, h), (120, 140, 160)).save(buf, format='PNG')
    return buf.getvalue()


def _house_plan():
    import json
    with open(FIXTURE, encoding='utf-8') as f:
        return twin_plan.normalize(json.load(f))[0]


def _buildings():
    return [(b['id'], b['name'], b['kind']) for b in ts.place()['buildings']]


def _building(bid):
    return next((b for b in ts.place()['buildings'] if b['id'] == bid), None)


def _source(sid):
    return next(s for s in ts.sources() if s['id'] == sid)


def _points(points):
    return [[p[0], p[1]] for p in points]


def _close(a, b, tol=1e-6):
    return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


# --- scenarios -------------------------------------------------------------

def scenario_kinds_and_shell_defaults_pinned():
    # The interface values the plan fixes; later tasks and the UI read them.
    check(list(tp.KINDS.items()) == [
        ('main_house', 'Main house'), ('garage', 'Garage'), ('adu', 'ADU or guest house'),
        ('pool_house', 'Pool house'), ('shed', 'Shed'), ('greenhouse', 'Greenhouse'),
        ('barn', 'Barn'), ('studio', 'Studio or office'), ('workshop', 'Workshop'),
        ('other', 'Other')], tp.KINDS)
    check(tp.SHELL_DEFAULT == {'storeys': 1, 'wall_height': 8, 'roof': 'gable', 'pitch': 6,
                               'door_side': 'front'}, tp.SHELL_DEFAULT)
    check(tp.KIND_SHELL == {
        'main_house': {'storeys': 2, 'wall_height': 9}, 'garage': {'wall_height': 9},
        'adu': {'wall_height': 9}, 'pool_house': {'wall_height': 9},
        'greenhouse': {'wall_height': 7, 'pitch': 8}, 'barn': {'wall_height': 12, 'pitch': 8},
        'studio': {'wall_height': 9}, 'workshop': {'wall_height': 10}}, tp.KIND_SHELL)
    check(tuple(tp.BUILDING_ROLES) == ('floor', 'roof', 'elevation', 'other', 'skip'), tp.BUILDING_ROLES)
    check(tuple(tp.LOT_ROLES) == ('plot', 'survey', 'landscape', 'other', 'skip'), tp.LOT_ROLES)
    check(tp.LOT == 'lot', tp.LOT)
    check(tp.shell_for('main_house') == {'storeys': 2, 'wall_height': 9, 'roof': 'gable', 'pitch': 6,
                                         'door_side': 'front'}, tp.shell_for('main_house'))
    check(tp.shell_for('barn') == {**tp.SHELL_DEFAULT, 'wall_height': 12, 'pitch': 8}, tp.shell_for('barn'))
    check(tp.shell_for('shed') == tp.SHELL_DEFAULT, tp.shell_for('shed'))
    # new_id
    check(tp.new_id('Detached garage', set()) == 'detached-garage', tp.new_id('Detached garage', set()))
    check(tp.new_id('Detached garage', {'detached-garage'}) == 'detached-garage-2', 'second takes -2')
    check(tp.new_id('Detached garage', {'detached-garage', 'detached-garage-2'}) == 'detached-garage-3',
          'third takes -3')
    check(tp.new_id('', set()) == 'building', 'empty name')
    check(tp.new_id('!!!', set()) == 'building', 'name without letters or digits')
    check(tp.new_id('Lot', set()) != 'lot' and tp.new_id('lot', set()) != 'lot', 'never lot')
    check(len(tp.new_id('x' * 100, set())) <= 40, 'at most 40 characters')
    check(tp.empty_place() == {'buildings': [], 'lot': {'placement': None, 'read': None}, 'photo_tags': {}},
          tp.empty_place())
    # to_master is the math crop_to_master delegates to.
    crop = {'box': [0.25, 0.25, 0.5, 0.5], 'master': [5100, 3300]}
    check(_close(tp.to_master(crop, [0.5, 0.5]), [1912.5, 1237.5]), tp.to_master(crop, [0.5, 0.5]))
    check(_close(ts.crop_to_master(crop, [1, 1]), tp.to_master(crop, [1, 1])), 'the store delegates')


def scenario_empty_place():
    _fresh()
    check(ts.place() == tp.empty_place(), ts.place())


def scenario_add_building_ids_and_names():
    _fresh()
    garage = ts.add_building('Detached garage', 'garage')
    check(garage['id'] == 'detached-garage', garage)
    check(garage['name'] == 'Detached garage' and garage['kind'] == 'garage', garage)
    check(set(garage) >= {'id', 'name', 'kind', 'footprint', 'footprint_from', 'shell', 'shell_from'}, garage)
    check(garage['footprint'] is None and garage['shell'] == tp.shell_for('garage'), garage)
    expect_value_error(lambda: ts.add_building('Detached Garage', 'garage'),
                       'There is already a building called Detached Garage.')
    lot_named = ts.add_building('Lot', 'other')
    check(lot_named['id'] != 'lot', lot_named)
    expect_value_error(lambda: ts.add_building('Treehouse', 'treehouse'), starts='Choose a kind')
    shed = ts.add_building('Shed', 'shed')
    check(shed['shell'] == tp.shell_for('shed') == tp.SHELL_DEFAULT, shed)
    check([b[0] for b in _buildings()] == ['detached-garage', lot_named['id'], 'shed'], _buildings())


def scenario_upload_to_part():
    _fresh()
    ts.add_building('Detached garage', 'garage')
    sid = ts.save_source('drawing', 'g.pdf', _pdf(), part='detached-garage')
    check(_source(sid)['part'] == 'detached-garage', _source(sid))
    pid = ts.save_source('photo', 'yard.png', _png(), part='lot')
    check(_source(pid)['part'] == 'lot', _source(pid))
    check(ts.photos_for('lot') == [pid], ts.photos_for('lot'))
    check(ts.place()['photo_tags'].get(pid) == ['lot'], ts.place()['photo_tags'])
    check(pid not in ts.photos_for('detached-garage'), 'tagged only with its part')
    before = len(ts.sources())
    expect_value_error(lambda: ts.save_source('photo', 'x.png', _png(), part='nope'))
    expect_value_error(lambda: ts.save_source('drawing', 'x.pdf', _pdf(pages=1), part='nope'))
    check(len(ts.sources()) == before, 'a refused upload saves nothing')


def scenario_roles_per_part():
    _fresh()
    ts.add_building('Detached garage', 'garage')
    sid = ts.save_source('drawing', 'g.pdf', _pdf(), part='detached-garage')
    ts.set_page_roles([{'source': sid, 'page': 1, 'role': 'plot', 'level': None, 'box': None,
                        'building': 'lot'}])
    check([(r['building'], r['role']) for r in ts.page_roles()] == [('lot', 'plot')], ts.page_roles())
    expect_value_error(lambda: ts.set_page_roles([
        {'source': sid, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None, 'building': 'lot'}]),
        SAME_PART)
    expect_value_error(lambda: ts.set_page_roles([
        {'source': sid, 'page': 2, 'role': 'survey', 'level': None, 'box': None,
         'building': 'detached-garage'}]), SAME_PART)
    expect_value_error(lambda: ts.set_page_roles([
        {'source': sid, 'page': 2, 'role': 'floor', 'level': 'Main floor', 'box': None, 'building': 'nope'}]))
    check([(r['building'], r['role']) for r in ts.page_roles()] == [('lot', 'plot')],
          'a refused write changes nothing')
    # Legacy rows carry no building.
    check('house' not in [b[0] for b in _buildings()], 'no Main house yet')
    ts.set_page_roles([
        {'source': sid, 'page': 1, 'role': 'plot', 'level': None, 'box': None},
        {'source': sid, 'page': 2, 'role': 'floor', 'level': 'Main floor', 'box': None}])
    rows = ts.page_roles()
    check([(r['page'], r['role'], r['building']) for r in rows] == [(1, 'plot', 'lot'), (2, 'floor', 'house')],
          rows)
    check(('house', 'Main house', 'main_house') in _buildings(), _buildings())
    check(_building('house')['shell'] == tp.shell_for('main_house'), _building('house'))
    ts.set_page_roles([{'source': sid, 'page': 2, 'role': 'roof', 'level': None, 'box': None}])
    check([b[0] for b in _buildings()].count('house') == 1, 'Main house is added once')


def scenario_move_page_resets_incompatible_role():
    _fresh()
    ts.add_building('Detached garage', 'garage')
    ts.add_building('Studio', 'studio')
    sid = ts.save_source('drawing', 'g.pdf', _pdf(), part='detached-garage')
    left, right = [0.0, 0.0, 0.5, 1.0], [0.5, 0.0, 1.0, 1.0]
    ts.set_page_roles([
        {'source': sid, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None,
         'building': 'detached-garage'},
        {'source': sid, 'page': 2, 'role': 'roof', 'level': None, 'box': left, 'building': 'detached-garage'},
        {'source': sid, 'page': 2, 'role': 'floor', 'level': 'Loft', 'box': right,
         'building': 'detached-garage'}])
    moved = ts.move_page(sid, 1, 'lot')
    check(len(moved) == 1, moved)
    check(moved[0]['building'] == 'lot' and moved[0]['role'] == 'other' and moved[0]['level'] is None, moved)
    saved = [r for r in ts.page_roles() if r['page'] == 1]
    check(len(saved) == 1 and saved[0]['building'] == 'lot' and saved[0]['role'] == 'other'
          and saved[0]['level'] is None, saved)
    moved = ts.move_page(sid, 2, 'studio')
    check(len(moved) == 2 and all(r['building'] == 'studio' for r in moved), moved)
    saved = sorted((r for r in ts.page_roles() if r['page'] == 2), key=lambda r: r['box'][0])
    check(len(saved) == 2 and all(r['building'] == 'studio' for r in saved), 'every region moves together')
    check(saved[0]['role'] == 'roof' and saved[0]['box'] == left, saved[0])
    check(saved[1]['role'] == 'floor' and saved[1]['level'] == 'Loft' and saved[1]['box'] == right, saved[1])
    expect_value_error(lambda: ts.move_page(sid, 2, 'nope'))


def scenario_photo_tags():
    _fresh()
    ts.add_building('Detached garage', 'garage')
    pid = ts.save_source('photo', 'yard.png', _png(), part='lot')
    ts.set_photo_tags(pid, ['lot', 'detached-garage'])
    check(pid in ts.photos_for('detached-garage'), ts.photos_for('detached-garage'))
    check(pid in ts.photos_for('lot'), ts.photos_for('lot'))
    ts.set_photo_tags(pid, [])
    check(pid in ts.photos_for('lot'), 'an untagged photo counts as the lot')
    check(pid not in ts.photos_for('detached-garage'), 'the garage tag is gone')
    expect_value_error(lambda: ts.set_photo_tags(pid, ['nope']))
    check(pid not in ts.photos_for('detached-garage'), 'a refused write changes nothing')


def scenario_migration_from_slice_1():
    _fresh()
    drawing = {'id': 'd1', 'kind': 'drawing', 'filename': 'lot58.pdf', 'pages': 3,
               'mime': 'application/pdf', 'total_pages': 3}
    photo = {'id': 'p1', 'kind': 'photo', 'filename': 'front.jpg', 'pages': 1, 'mime': 'image/jpeg'}
    storage.patch_settings({'house_twin': {
        'current': None, 'generation': 0, 'rounds': [], 'fixes': [], 'registrations': [], 'tombstones': [],
        'sources': [drawing, photo],
        'page_roles': [
            {'source': 'd1', 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None, 'building': 'house'},
            {'source': 'd1', 'page': 2, 'role': 'floor', 'level': 'Ground', 'box': None,
             'building': 'pool_house'},
            {'source': 'd1', 'page': 3, 'role': 'plot', 'level': None, 'box': None, 'building': 'house'}]}})
    check('place' not in storage.get_settings()['house_twin'], 'the slice 1 state has no place')
    first = ts.place()
    check([(b['id'], b['name'], b['kind']) for b in first['buildings']]
          == [('house', 'Main house', 'main_house'), ('pool_house', 'Pool house', 'pool_house')],
          first['buildings'])
    for b in first['buildings']:
        check(b['shell'] == tp.shell_for(b['kind']) and b['footprint'] is None, b)
    plot = [r for r in ts.page_roles() if r['role'] == 'plot']
    check(len(plot) == 1 and plot[0]['building'] == 'lot', plot)
    floors = sorted((r['page'], r['building']) for r in ts.page_roles() if r['role'] == 'floor')
    check(floors == [(1, 'house'), (2, 'pool_house')], floors)
    check(first['photo_tags'] == {'p1': ['house', 'pool_house', 'lot']}, first['photo_tags'])
    check('place' in storage.get_settings()['house_twin'], 'the migrated place is saved')
    second = ts.place()
    check(second == first, 'a second read returns the same place')
    # Prove the second read is the saved place, not a fresh migration.
    row = storage.get_settings()['house_twin']
    row['place']['photo_tags']['p1'] = ['lot']
    storage.patch_settings({'house_twin': row})
    check(ts.place()['photo_tags'] == {'p1': ['lot']}, 'no second migration')
    # place() returns a deep copy.
    copy = ts.place()
    copy['buildings'].clear()
    check(len(ts.place()['buildings']) == 2, 'mutating the result changes nothing saved')


def scenario_rename_built_building_updates_plan():
    _fresh()
    ts.push_round(_house_plan(), 'build')
    check(ts.current()['buildings'][0]['id'] == 'house', 'the fixture builds house')
    rounds_before = len(ts.rounds())
    record = ts.update_building('house', {'name': 'Farmhouse'})
    check(record['id'] == 'house' and record['name'] == 'Farmhouse', record)
    plan_building = ts.current()['buildings'][0]
    check(plan_building['name'] == 'Farmhouse' and plan_building['id'] == 'house', plan_building)
    check(len(ts.rounds()) == rounds_before + 1, 'the rename publishes one round')
    last = ts.rounds()[-1]
    check(last['kind'] == 'edit' and last['note'] == 'Renamed Main house to Farmhouse', last)
    check(_building('house')['name'] == 'Farmhouse', _building('house'))
    twin_edit.save({'op': 'set', 'building': 'house', 'piece': 'house', 'field': 'name', 'value': 'Home'}, 'p1')
    check(ts.current()['buildings'][0]['name'] == 'Home', 'the plan takes the name')
    check(_building('house')['name'] == 'Home', ts.place()['buildings'])
    check([b[0] for b in _buildings()] == ['house'], 'the id never changes')


def scenario_remove_building_rules():
    _fresh()
    ts.push_round(_house_plan(), 'build')
    ts.add_building('Detached garage', 'garage')
    ts.add_building('Shed', 'shed')
    check([b[0] for b in _buildings()] == ['house', 'detached-garage', 'shed'], _buildings())
    sid = ts.save_source('drawing', 'g.pdf', _pdf(), part='detached-garage')
    ts.set_page_roles([{'source': sid, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None,
                        'building': 'detached-garage'}])
    expect_value_error(lambda: ts.remove_building('detached-garage'),
                       'Move or remove this building\'s pages first.')
    expect_value_error(lambda: ts.remove_building('house'),
                       'This building is part of the house. Delete it from the house first.')
    check([b[0] for b in _buildings()] == ['house', 'detached-garage', 'shed'], 'refusals change nothing')
    only_shed = ts.save_source('photo', 'shed.png', _png(), part='shed')
    shared = ts.save_source('photo', 'yard.png', _png(), part='shed')
    ts.set_photo_tags(shared, ['shed', 'lot'])
    check(only_shed in ts.photos_for('shed') and only_shed not in ts.photos_for('lot'), 'tagged shed only')
    ts.remove_building('shed')
    check([b[0] for b in _buildings()] == ['house', 'detached-garage'], _buildings())
    tags = ts.place()['photo_tags']
    check(all('shed' not in parts for parts in tags.values()), tags)
    check(tags.get(shared) == ['lot'], tags)
    check(only_shed in ts.photos_for('lot'), 'a photo left with no tag belongs to the lot')
    check(shared in ts.photos_for('lot'), ts.photos_for('lot'))


def scenario_start_over_empties_place():
    _fresh()
    ts.add_building('Detached garage', 'garage')
    ts.save_source('photo', 'yard.png', _png(), part='lot')
    check(ts.place() != tp.empty_place(), 'the place has content before')
    ts.start_over()
    check(ts.place() == tp.empty_place(), ts.place())


def scenario_footprint_and_shell_checks():
    _fresh()
    ts.add_building('Shed', 'shed')
    expect_value_error(lambda: ts.update_building('shed', {'footprint': [[0, 0], [10, 10], [10, 0], [0, 10]]}),
                       'A footprint cannot cross itself.')
    expect_value_error(lambda: ts.update_building('shed', {'shell': {'storeys': 0}}))
    check(_building('shed')['shell'] == tp.SHELL_DEFAULT and _building('shed')['footprint'] is None,
          'refusals change nothing')
    flat = ts.update_building('shed', {'shell': {'roof': 'flat'}})
    check(flat['shell']['roof'] == 'flat' and flat['shell']['pitch'] == 0, flat['shell'])
    check(flat['shell']['wall_height'] == tp.SHELL_DEFAULT['wall_height'], 'a partial shell merges')
    check(flat['shell_from'] == 'person', flat)
    check(_building('shed')['shell']['pitch'] == 0, 'saved')
    rect = [[0, 0], [10, 0], [10, 12], [0, 12]]
    typed = ts.update_building('shed', {'footprint': rect, 'footprint_from': 'typed'})
    check(_points(typed['footprint']) == rect and typed['footprint_from'] == 'typed', typed)
    saved = _building('shed')
    check(_points(saved['footprint']) == rect and saved['footprint_from'] == 'typed', saved)
    # The pure checks behind update_building.
    check(_points(tp.check_footprint(rect)) == rect, 'a rectangle passes')
    for bad in ([[0, 0], [10, 0]], [[0, 0], [1, 0], [1, 1], [0, 1]], [[0, 0], [3000, 0], [3000, 10], [0, 10]],
                [[0, 0], [math.nan, 0], [10, 10]], [[i, i % 2] for i in range(65)]):
        expect_value_error(lambda bad=bad: tp.check_footprint(bad))
    check(tp.check_shell({**tp.SHELL_DEFAULT, 'roof': 'flat', 'pitch': 6})['pitch'] == 0, 'flat forces 0')
    for bad in ({'storeys': 5}, {'wall_height': 5}, {'wall_height': 21}, {'roof': 'dome'},
                {'pitch': 25}, {'door_side': 'up'}):
        expect_value_error(lambda bad=bad: tp.check_shell({**tp.SHELL_DEFAULT, **bad}))


def scenario_legacy_drawing_goes_to_house():
    # Controller ruling R3: a legacy upload with no part goes to house and adds Main house.
    _fresh()
    check(ts.place() == tp.empty_place(), 'empty before')
    sid = ts.save_source('drawing', 'old.pdf', _pdf())
    check(_source(sid)['part'] == 'house', _source(sid))
    check(_buildings() == [('house', 'Main house', 'main_house')], _buildings())
    again = ts.save_source('drawing', 'older.pdf', _pdf(pages=1))
    check(_source(again)['part'] == 'house', _source(again))
    check(_buildings() == [('house', 'Main house', 'main_house')], 'Main house is added once')
    ts.add_building('Detached garage', 'garage')
    pid = ts.save_source('photo', 'front.png', _png())
    check(set(ts.place()['photo_tags'].get(pid) or []) == {'house', 'detached-garage', 'lot'},
          ts.place()['photo_tags'])
    check(pid in ts.photos_for('house') and pid in ts.photos_for('detached-garage') and pid in ts.photos_for('lot'),
          'a legacy photo is tagged with every building and the lot')


SCENARIOS = (
    scenario_kinds_and_shell_defaults_pinned,
    scenario_empty_place,
    scenario_add_building_ids_and_names,
    scenario_upload_to_part,
    scenario_roles_per_part,
    scenario_move_page_resets_incompatible_role,
    scenario_photo_tags,
    scenario_migration_from_slice_1,
    scenario_rename_built_building_updates_plan,
    scenario_remove_building_rules,
    scenario_start_over_empties_place,
    scenario_footprint_and_shell_checks,
    scenario_legacy_drawing_goes_to_house,
)


if __name__ == '__main__':
    failed = []
    for fn in SCENARIOS:
        try:
            fn()
        except Exception:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__)
            traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(SCENARIOS) - len(failed)}/{len(SCENARIOS)} passed')
    sys.exit(1 if failed else 0)

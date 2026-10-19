"""Executable cutover edges beyond the immutable library model contract."""
import datetime as dt
import traceback
from unittest.mock import patch

from harness import check
from program_fixture import add_run, loaded
from services import access, home_board, house_programs, library, model_pools, program_lessons, programs, storage
from fastapi.testclient import TestClient
import main

MON = dt.date(2026, 10, 19)


def fresh():
    for table in ('members', 'programs', 'library_programs', 'program_lessons', 'protected_commitments',
                  'app_state', 'projects', 'threads', 'missions', 'deletions'):
        getattr(storage, table + '_table').truncate()
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'kid', 'name': 'Kate', 'role': 'child'})
    return add_run({'title': 'Piano', 'member_id': 'kid', 'state': 'active', 'starting_point': 'Private beginner',
                    'baseline': {'start_date': MON.isoformat()},
                    'phases': [{'name': 'Basics', 'weeks': 2,
                                'units': [{'title': 'Scales', 'sessions': 4}, {'title': 'Songs', 'sessions': 2}],
                                'rotation': [{'label': 'Empty', 'steps': []},
                                             {'label': 'Up', 'steps': ['Scale up']},
                                             {'label': 'Down', 'steps': ['Scale down']}]}]})


def http(method, path, **kwargs):
    with patch.object(storage, 'get_settings', return_value={'auth_enforce': True}):
        return TestClient(main.app).request(method, path,
            headers={'X-Member-Token': storage.create_member_token('mom')}, **kwargs)


def scenario_date_rotation_includes_same_day_rank_and_filters_empty_variants():
    rid = fresh()
    legacy = {'member_id': 'kid', 'baseline': {'start_date': MON.isoformat()},
              'shape': {'slots': [{'day': 0, 'time_start': '17:00'}]},
              'phases': [{'name': 'Legacy', 'rotation': [None, {}, {'label': 'Kept', 'steps': ['Legacy steps']}]}]}
    check(programs.lesson_for(legacy, MON)['steps'] == ['Legacy steps'], 'legacy rotation keeps its defensive entry filter')
    row = loaded(rid)
    check([v['label'] for v in row['lessons'][0]['variants']] == ['Up', 'Down'], 'empty rotations are filtered at intake')
    cids = []
    for n, (day, start) in enumerate(((0, '17:00'), (0, '18:00'), (2, '17:00'))):
        cid = f'rotation-{n}'
        storage.add_protected_commitment({'id': cid, 'member_id': 'kid', 'title': 'Piano', 'active': True,
            'days_of_week': [day], 'time_start': start, 'time_end': start[:2] + ':20'})
        cids.append(cid)
    storage.update_program(rid, {'emissions': {'commitment_ids': cids}})
    windows = programs.practice_windows(MON, MON + dt.timedelta(days=2), viewer=access.HOUSE)
    check([w['variant_label'] for w in windows] == ['Up', 'Down', 'Up'], 'same-day windows take chronological turns')
    for w, rank in zip(windows, (0, 1, 0)):
        one = programs.lesson_for(storage.get_program(rid), dt.date.fromisoformat(w['date']), slot_rank=rank)
        check((w['lesson_id'], w['variant_label'], w['steps']) ==
              (one['lesson_id'], one['variant_label'], one['steps']), 'window and projection use one rule')
    programs.log_session(rid)
    after = programs.practice_windows(MON, MON + dt.timedelta(days=2), viewer=access.HOUSE)
    check([(w['lesson_id'], w['variant_label'], w['steps']) for w in after] ==
          [(w['lesson_id'], w['variant_label'], w['steps']) for w in windows], 'logging does not redeal variants')
    storage.update_protected_commitment(cids[1], {'active': False})
    wednesday = programs.lesson_for(storage.get_program(rid), MON + dt.timedelta(days=2))
    check(wednesday['variant_label'] == 'Down', 'inactive reservations do not count in the date deal')


def scenario_named_routes_generation_wait_and_unresolved_reads():
    rid = fresh()
    row = loaded(rid)
    lid, first = row['library_id'], row['lessons'][0]['id']
    slot = {'lesson_id': first, 'variant_label': 'Down'}
    storage.upsert_program_lesson(rid, slot, {'scenes': [{'type': 'say', 'text': 'Opened scale beat.'}]})
    check(http('GET', f'/api/programs/{rid}/lesson').json() == {'lesson': None}, 'an unnamed legacy slot never aliases a named script')
    programs.step_bookmark(rid, 'next')
    main._lesson_help_at.clear()
    prompts = []
    def answer(*args, **kwargs):
        prompts.append(args[3])
        return {'answer': 'Go slowly.', 'scenes': [{'type': 'say', 'text': 'Scale practice.'}]}
    with patch.object(model_pools, 'call_pool_json', side_effect=answer):
        response = http('POST', f'/api/programs/{rid}/lesson-help', json={**slot, 'scene_idx': 0})
        check(response.status_code == 200 and 'Opened scale beat.' in prompts[-1], 'help keeps the opened lesson after Next')
        storage.delete_program_lesson(rid, slot)
        stale = {**slot, 'program_id': rid, 'steps': ['Stale words'], 'unit_body': 'Stale body', 'date': MON.isoformat()}
        check(program_lessons.generate_for(storage.get_program(rid), stale, {}, {}), 'named generation runs')
        check('Private beginner' in prompts[-1] and 'Scale down' in prompts[-1] and 'Stale words' not in prompts[-1],
              'generation resolves that named variant fresh, with this run private input')
    response = http('POST', '/api/lessons/wait', json={**slot, 'program_id': rid, 'room': 'Kitchen',
                    'text': 'Come back to the keys.', 'minutes': 5})
    check(response.status_code == 200, 'named wait armed')
    entry = storage.get_app_state(program_lessons.WAIT_STATE_KEY)[0]
    check(all(entry[k] == v for k, v in {**slot, 'program_id': rid}.items()), 'wait preserves all three identity fields')
    moved = {'lesson_id': 'missing', 'variant_label': ''}
    for method, tail in [('GET', 'lesson'), ('PUT', 'lesson'), ('DELETE', 'lesson'), ('GET', 'lesson-scenes'),
                         ('POST', 'lesson-help'), ('POST', 'session')]:
        data = {'params': moved} if method in ('GET', 'DELETE') else {'json': {**moved, 'scenes': [{'type': 'say', 'text': 'Hi.'}]}}
        response = http(method, f'/api/programs/{rid}/{tail}', **data)
        check(response.status_code == 409 and programs.MOVED_LESSON in response.text, f'{method} {tail}: moved identity is 409')
    response = http('POST', '/api/lessons/wait', json={**moved, 'program_id': rid, 'room': 'Kitchen', 'text': 'Hello.', 'minutes': 5})
    check(response.status_code == 409, 'moved wait is refused too')
    other = library.from_curated('Recorder', {}, {'phases': [{'name': 'Notes', 'steps': ['Play']}]}, 'mom')
    other_id = storage.add_library_program(other)
    # Both rows already exist before the digest; only the run binding changes.
    home_board._ACCESS_DIGEST.clear()
    before = home_board._access_input_digest()
    check(programs.rebind(rid, other_id, storage.get_member('mom'))['status'] == 'success', 'run rebinds')
    check(home_board._access_input_digest() != before, 'rebind invalidates a warm board')
    storage.delete_library_program(other_id)
    neutral = house_programs.session(rid, dt.datetime.combine(MON, dt.time(17)), viewer=access.HOUSE)
    check(neutral['title'] == 'Busy' and not neutral['member_name'] and not neutral['steps'],
          'unresolved house practice has only neutral time, no name or curriculum words')
    check(not programs.celebrations(viewer=access.HOUSE)['practiced'], 'unresolved runs supply no celebration words')
    check(not program_lessons.due_wait_announces(now_ts=entry['fire_ts']), 'unresolved wait supplies no spoken words')
    check(not loaded(rid)['phases'] and loaded(rid)['unresolved'], 'unresolved remains a run')


def scenario_a_removal_between_route_admission_and_storage_is_still_409():
    rid = fresh()
    slot = {'lesson_id': loaded(rid)['lessons'][0]['id'], 'variant_label': 'Down'}
    for method, tail in [('GET', 'lesson'), ('PUT', 'lesson'), ('GET', 'lesson-scenes'), ('POST', 'lesson-help')]:
        main._lesson_help_at.clear()
        with patch.object(storage, 'get_program_lesson', side_effect=ValueError(programs.MOVED_LESSON)):
            data = {'params': slot} if method == 'GET' else {'json': {**slot, 'scenes': [{'type': 'say', 'text': 'Hi.'}]}}
            response = http(method, f'/api/programs/{rid}/{tail}', **data)
        check(response.status_code == 409 and programs.MOVED_LESSON in response.text, f'{method} {tail}: storage recheck is 409')
    for method, name in [('PUT', 'upsert_program_lesson'), ('DELETE', 'delete_program_lesson')]:
        with patch.object(storage, name, side_effect=ValueError(programs.MOVED_LESSON)):
            data = {'params': slot} if method == 'DELETE' else {'json': {**slot, 'scenes': [{'type': 'say', 'text': 'Hi.'}]}}
            response = http(method, f'/api/programs/{rid}/lesson', **data)
        check(response.status_code == 409 and programs.MOVED_LESSON in response.text, f'{method}: final storage recheck is 409')


if __name__ == '__main__':
    failures = 0
    for fn in (scenario_date_rotation_includes_same_day_rank_and_filters_empty_variants,
               scenario_named_routes_generation_wait_and_unresolved_reads,
               scenario_a_removal_between_route_admission_and_storage_is_still_409):
        try:
            fn()
            print('PASS', fn.__name__)
        except Exception:
            failures += 1
            traceback.print_exc()
    raise SystemExit(bool(failures))

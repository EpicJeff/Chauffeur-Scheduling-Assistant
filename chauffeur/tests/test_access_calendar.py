"""Calendar access, read-time narrowing and provenance (spec 4.7, 10.3)."""
import datetime as dt
import json
import traceback
from unittest.mock import patch

from harness import check
import access_fixture
from services import access, storage, programs, migrations, family_digest
from test_subjects import MOM

DAY = dt.date(2026, 10, 16)
NOW = dt.datetime(2026, 10, 16, 17, 0)


def seed(fx, key='R3'):
    storage.protected_commitments_table.truncate()
    pid = fx.ids[key]
    cid = 'calendar-' + key
    storage.add_protected_commitment({
        'id': cid, 'member_id': 'kid', 'title': fx.title(key),
        'days_of_week': [DAY.weekday()], 'time_start': '17:00', 'time_end': '17:30',
        'active': True, 'source': {'kind': 'program', 'id': pid}})
    storage.update_program(pid, {
        'phases': [{'name': fx.secret(key), 'weeks': 2, 'steps': [fx.secret(key)],
                    'milestone': fx.secret(key), 'units': [{'n': 1, 'title': fx.secret(key)}]}],
        'baseline': {'start_date': DAY.isoformat()},
        'emissions': {'commitment_ids': [cid], 'event_ids': []}})
    event = {
        'id': f'practice-{pid}-2026-10-16-17:00', 'title': fx.title(key),
        'description': fx.secret(key), 'event_type': 'practice',
        'start': '2026-10-16T17:00:00', 'end': '2026-10-16T17:30:00',
        'all_day': False, 'calendar_ids': ['kid'],
        'practice': {'program_id': pid, 'member_id': 'kid', 'color': '#123456',
                     'date': DAY.isoformat(), 'time_start': '17:00', 'time_end': '17:30',
                     'unit_title': fx.secret(key), 'steps': [fx.secret(key)],
                     'milestone': fx.secret(key)}}
    storage.set_cached_schedule({'events': [event], 'assignments': {}, 'unassigned': [],
                                 'true_unassigned': [], 'calendar_metadata': {}, 'members': []})
    return event, cid


def scenario_cache_narrowing_takes_effect_at_read():
    fx = access_fixture.build()
    event, _ = seed(fx, 'R5p')
    raw = storage.get_cached_schedule()
    storage.update_project(fx.projects['household']['id'], {'audience': 'private'})
    out = access.schedule_view(raw, access.HOUSE)
    text = json.dumps(out)
    check(fx.secret('R5p') not in text and fx.title('R5p') not in text
          and fx.ids['R5p'] not in text, 'narrowed at read: ' + text)
    check(out['events'][0]['practice']['color'] == '#123456', 'colour kept')
    check(set(out['events'][0]['practice']) == set(access.NEUTRAL_PRACTICE_KEYS), 'only structure')
    check(fx.secret('R5p') in json.dumps(access.schedule_view(raw, fx.viewers['dad'])), 'owner reads words')
    check(storage.get_cached_schedule() == raw and raw['events'][0] == event, 'cache stays whole')
    storage.update_project(fx.projects['household']['id'], {'audience': 'household'})
    check(fx.secret('R5p') in json.dumps(access.schedule_view(raw, access.HOUSE)), 'widening restores words')


def scenario_no_target_event_is_written():
    access_fixture.build()
    with patch('services.calendar.create_event', return_value='ev-new') as create:
        pid = storage.add_program({'title': 'T', 'member_id': 'mom', 'state': 'proposed',
                                   'shape': {'minutes': 25},
                                   'baseline': {'target_date': '2027-01-01'}})
        result = programs.approve(pid, 'mom', slots=[{'day': 4, 'time_start': '17:00'}])
    check(result.get('status') == 'success', str(result))
    check(not create.called, 'no calendar event for a target date')
    row = storage.get_program(pid)
    check(row['baseline']['target_date'] == '2027-01-01', 'target itself retained')
    check(programs.footprint(row).get('event') is None, 'no target event in footprint')
    for cid in row['emissions']['commitment_ids']:
        check(storage.get_protected_commitment(cid)['source'] == {'kind': 'program', 'id': pid}, 'new provenance')


def scenario_migration_deletes_old_target_events():
    access_fixture.build()
    pid = storage.add_program({'title': 'T', 'member_id': 'mom', 'state': 'active',
                               'baseline': {'target_date': '2027-01-01', 'target_event_id': 'ev-old'},
                               'emissions': {'event_ids': ['ev-old', 'other'], 'commitment_ids': []}})
    with patch('services.calendar.delete_event', return_value=True) as delete:
        migrations.migrate_remove_target_events_v2499()
        migrations.migrate_remove_target_events_v2499()
    row = storage.get_program(pid)
    check(delete.call_count == 1 and delete.call_args.args[-1] == 'ev-old', str(delete.call_args_list))
    check(not row['baseline'].get('target_event_id') and row['emissions']['event_ids'] == ['other'], str(row))
    check(row['baseline']['target_date'] == '2027-01-01', 'date retained by migration')


def scenario_failed_target_deletion_is_retryable():
    access_fixture.build()
    pid = storage.add_program({'member_id': 'mom', 'title': 'T',
                               'baseline': {'target_date': '2027-01-01', 'target_event_id': 'retry-me'},
                               'emissions': {'event_ids': ['retry-me']}})
    with patch('services.calendar.delete_event', return_value=False):
        migrations.migrate_remove_target_events_v2499()
    check(storage.get_program(pid)['baseline']['target_event_id'] == 'retry-me', 'failed delete stays retryable')
    storage.set_cached_schedule({'events': [{'id': 'retry-me', 'title': 'T'}]})
    with patch('services.calendar.delete_event', return_value=True):
        migrations.migrate_remove_target_events_v2499()
    check(not storage.get_program(pid)['baseline'].get('target_event_id'), 'retry clears provenance')
    check(not storage.get_cached_schedule(), 'deleted external copy cannot survive in the served cache')


def scenario_commitment_sources_backfilled():
    fx = access_fixture.build()
    _, cid = seed(fx)
    storage.update_protected_commitment(cid, {'source': None})
    migrations.migrate_commitment_sources_v2499()
    migrations.migrate_commitment_sources_v2499()
    check(storage.get_protected_commitment(cid)['source'] == {'kind': 'program', 'id': fx.ids['R3']}, 'source set')


def scenario_due_push_is_recipient_safe():
    fx = access_fixture.build()
    seed(fx)
    storage.update_member('kid', {'driver_id': 'hal-driver'})
    storage.update_member('hal', {'driver_id': 'hal-driver'})
    windows = programs.due_practice_pushes(NOW)
    check(windows, 'a due window really reaches the push entry point')
    text = json.dumps(windows)
    check(fx.secret('R3') not in text and fx.title('R3') not in text, 'Hal sees no program words: ' + text)
    check(windows[0]['title'] == 'Practice time', 'neutral practice push')
    check(fx.ids['R3'] not in text, 'push tag does not disclose the program id')


def scenario_private_window_has_only_busy_structure_and_keeps_color():
    fx = access_fixture.build()
    seed(fx)
    storage.update_member('kid', {'color_code': '#123456'})
    window = programs.practice_windows(DAY, DAY, viewer=fx.viewers['aunt'])[0]
    check(set(window) == set(access.NEUTRAL_PRACTICE_KEYS) | {'id', 'title'}, str(window))
    check(window['title'] == 'Busy' and window['color'] == '#123456', str(window))
    check(window['id'].startswith('busy-') and fx.ids['R3'] not in window['id'], 'hashed neutral id')
    owned = programs.practice_windows(DAY, DAY, viewer=fx.viewers['kid'])[0]
    check(owned['title'] == fx.title('R3') and owned['steps'] == [fx.secret('R3')], str(owned))


def scenario_shared_practice_still_uses_the_shared_screen_union():
    fx = access_fixture.build()
    _, cid = seed(fx, 'R5p')
    storage.update_program(fx.ids['R5p'], {'member_id': 'mom'})
    storage.update_protected_commitment(cid, {'member_id': 'mom'})
    from services import house_programs, house_attention
    window = house_programs.session(fx.ids['R5p'], NOW, viewer=fx.viewers['kid'])
    check(window and window['title'] == fx.title('R5p'), 'a child keeps household practice words on shared screens')
    check(house_attention._programs(NOW, viewer=fx.viewers['kid'])['available'] == 1, 'shared count keeps the window')


def scenario_subject_title_matching_cannot_reveal_private_practice():
    fx = access_fixture.build()
    event, _ = seed(fx)
    from services import subjects
    for col in ('house', 'aunt', 'hal'):
        out = subjects.find('event', fx.title('R3'), fx.viewers[col])
        check(not out, f'{col}: private practice named by subject matching: {out}')
    check(subjects.find('event', fx.title('R3'), fx.viewers['kid']), 'the child still matches their own practice')


def scenario_authorized_private_packing_keeps_its_hand_path():
    fx = access_fixture.build()
    event, _ = seed(fx)
    storage.prep_kits_table.truncate()
    storage.add_prep_kit({'id': 'practice-kit', 'name': 'Bring', 'keywords': [fx.title('R3')],
                          'items': ['Bottle'], 'per_person': False, 'enabled': True})
    from access_shared_signals import request
    response = request(fx, 'mom', 'GET', '/api/packing/day?date=2026-10-16')
    check(response.status_code == 200, response.text)
    block = next(b for b in response.json()['blocks'] if b.get('event_id') == event['id'])
    check(block['needed'] == 1, str(block))
    item = block['groups'][0]['items'][0]
    response = request(fx, 'mom', 'POST', '/api/packing/claim', json={
        'outing_key': block['key'], 'item_key': item['key'], 'date': DAY.isoformat(), 'delta': 1})
    check(response.status_code == 200, 'the visible private block is still packable: ' + response.text)


def scenario_briefing_never_calls_display_only_time_uncovered():
    fx = access_fixture.build()
    event, _ = seed(fx)
    hold = {'id': 'hold', 'title': 'Busy', 'event_type': 'project_hold',
            'start': event['start'], 'end': event['end']}
    storage.set_cached_schedule({'events': [event, hold], 'unassigned': [event['id'], 'hold']})
    out = family_digest.build_household_briefing(DAY)
    check(fx.title('R3') not in json.dumps(out), str(out))
    check('nobody yet' not in json.dumps(out).lower() and 'busy' not in json.dumps(out).lower(), str(out))


SCENARIOS = [v for k, v in list(globals().items()) if k.startswith('scenario_')]
if __name__ == '__main__':
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print('PASS', fn.__name__)
        except Exception:
            failed += 1
            print('FAIL', fn.__name__)
            traceback.print_exc()
    raise SystemExit(bool(failed))

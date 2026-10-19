"""Calendar access, read-time narrowing and provenance (spec 4.7, 10.3)."""
import datetime as dt
import json
import traceback
from unittest.mock import patch

from program_fixture import add_run
from harness import check
import access_fixture
from services import access, storage, programs, migrations, family_digest
from test_subjects import MOM

DAY = dt.date(2026, 10, 16)
NOW = dt.datetime(2026, 10, 16, 17, 0)


def seed(fx, key='R3'):
    storage.protected_commitments_table.truncate()
    pid = fx.ids[key]
    member = storage.get_program(pid)['member_id']
    cid = 'calendar-' + key
    storage.add_protected_commitment({
        'id': cid, 'member_id': member, 'title': fx.title(key),
        'days_of_week': [DAY.weekday()], 'time_start': '17:00', 'time_end': '17:30',
        'active': True, 'source': {'kind': 'program', 'id': pid}})
    curriculum = storage.get_library_program(fx.library[key])
    storage.update_library_program(fx.library[key], {
        'phases': [{**p, 'name': fx.secret(key), 'weeks': 2, 'steps': [fx.secret(key)],
                    'milestone': fx.secret(key)} for p in curriculum['phases']],
        'lessons': [{**l, 'title': fx.secret(key), 'steps': [fx.secret(key)]} for l in curriculum['lessons']]})
    storage.update_program(pid, {
        'baseline': {'start_date': DAY.isoformat()},
        'emissions': {'commitment_ids': [cid], 'event_ids': []}})
    event = {
        'id': f'practice-{pid}-2026-10-16-17:00', 'title': fx.title(key),
        'description': fx.secret(key), 'event_type': 'practice',
        'start': '2026-10-16T17:00:00', 'end': '2026-10-16T17:30:00',
        'all_day': False, 'calendar_ids': [member],
        'practice': {'program_id': pid, 'member_id': member, 'color': '#123456',
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
        pid = add_run({'title': 'T', 'member_id': 'mom', 'state': 'proposed',
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
    pid = add_run({'title': 'T', 'member_id': 'mom', 'state': 'active',
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
    pid = add_run({'member_id': 'mom', 'title': 'T',
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


def scenario_due_push_hides_title_from_unlisted_dad_driver():
    fx = access_fixture.build()
    seed(fx)
    storage.update_member('kid', {'driver_id': 'dad-driver'})
    storage.update_member('dad', {'driver_id': 'dad-driver'})
    windows = programs.due_practice_pushes(NOW)
    check(windows and windows[0]['title'] == 'Practice time', str(windows))
    check(fx.title('R3') not in json.dumps(windows) and fx.secret('R3') not in json.dumps(windows),
          'Dad is off Mom private list, so receives no practice words')


def scenario_program_lookups_are_once_per_call():
    fx = access_fixture.build()
    _, cid = seed(fx)
    for n in range(2):
        storage.add_protected_commitment(dict(storage.get_protected_commitment(cid), id=f'other-{n}'))
    with patch.object(storage, 'get_program', wraps=storage.get_program) as load:
        windows = programs.practice_windows(DAY, DAY + dt.timedelta(days=21))
    check(len(windows) >= 4 and load.call_count == 1, f'{len(windows)} windows: {load.call_args_list}')
    from access_shared_signals import request
    with patch.object(storage, 'get_program', wraps=storage.get_program) as load:
        response = request(fx, 'aunt', 'GET', '/api/commitments')
    check(response.status_code == 200 and len(response.json()) == 3, response.text)
    check(load.call_count == 1, str(load.call_args_list))
    check(all(row['title'] == 'Busy' for row in response.json()), response.text)
    # A fresh call must re-read current access rather than retaining cached visibility.
    storage.update_project(fx.projects['mom_private']['id'], {'audience': 'household'})
    response = request(fx, 'aunt', 'GET', '/api/commitments')
    check(all(row['title'] == fx.title('R3') for row in response.json()), response.text)


def scenario_deleted_target_404_and_410_clear_ids():
    from types import SimpleNamespace
    from services import calendar
    for status in (404, 410):
        access_fixture.build()
        pid = add_run({'member_id': 'mom', 'title': 'T',
            'baseline': {'target_date': '2027-01-01', 'target_event_id': 'gone'},
            'emissions': {'event_ids': ['gone', 'unproven']}})
        exc = RuntimeError('already gone')
        exc.resp = SimpleNamespace(status=status)
        # Run the actual calendar deletion path, with only Google's transport mocked.
        with patch.object(calendar, 'get_calendar_service') as service:
            service.return_value.events.return_value.delete.return_value.execute.side_effect = exc
            migrations.migrate_remove_target_events_v2499()
            migrations.migrate_remove_target_events_v2499()
            check(service.call_count == 1, 'already-gone deletion is not retried')
        row = storage.get_program(pid)
        check('target_event_id' not in row['baseline'] and row['emissions']['event_ids'] == ['unproven'], str(row))
        check(row['baseline']['target_date'] == '2027-01-01', 'date stays fixed')
        # The migration also accepts adapters that propagate the HTTP exception.
        storage.update_program(pid, {'baseline': {'target_event_id': 'gone'}})
        with patch.object(calendar, 'delete_event', side_effect=exc):
            migrations.migrate_remove_target_events_v2499()
        check('target_event_id' not in storage.get_program(pid)['baseline'], 'raised gone also cleared')


def scenario_day_and_outings_view_only_once():
    fx = access_fixture.build()
    event, _ = seed(fx)
    from services import family_day, outings
    storage.add_prep_kit({'id': 'count-kit', 'name': 'Bring', 'keywords': [fx.title('R3')],
                         'items': ['Bottle'], 'per_person': False, 'enabled': True})
    raw = storage.get_cached_schedule()
    for call in (
        lambda: family_day.blocks_for(DAY, raw, NOW, viewer=fx.viewers['mom']),
        lambda: family_day.day_in_focus(NOW, raw, viewer=fx.viewers['mom']),
        lambda: outings.outings_for(DAY, raw, NOW, viewer=fx.viewers['mom']),
        lambda: outings.packing_for({'event_ids': [event['id']]}, raw, viewer=fx.viewers['mom']),
    ):
        with patch.object(access, 'schedule_view', wraps=access.schedule_view) as view:
            result = call()
        check(result is not None and view.call_count == 1, str(view.call_args_list))


def scenario_empty_blob_falls_back_for_riders_and_presence():
    access_fixture.build()
    from services import drive_sheet, presence
    storage.update_member('kid', {'passenger_id': 'kid-passenger'})
    storage.update_member('dad', {'driver_id': 'dad-driver'})
    event = {'id': 'ride', 'title': 'Soccer', 'calendar_ids': [],
             'start': NOW.isoformat(), 'end': (NOW + dt.timedelta(hours=1)).isoformat()}
    storage.set_cached_schedule({'events': [event], 'assignments': {'ride': 'dad-driver'},
        'matched_rules': {'ride': [{'passenger_ids': ['kid-passenger']}]}})
    for blob in (None, {}):
        riders = drive_sheet.ride_members_for_event(event, 'ride', blob)
        check('kid' in {m['id'] for m in riders}, str(riders))
        audience = drive_sheet._message_audience('init_ride_1', blob)
        check('kid' in {m['id'] for m in audience}, str(audience))
        present = presence.members_at_event(event, 'ride', blob)
        check({'dad', 'kid'} <= {m['id'] for m in present}, str(present))
        audience = presence.moment_push_audience({'event_id': 'ride'}, blob)
        check('mom' in {m['id'] for m in audience} and 'dad' not in {m['id'] for m in audience}, str(audience))


def scenario_calendar_uses_the_conversation_viewer():
    fx = access_fixture.build()
    seed(fx)
    storage.update_program(fx.ids['R3'], {'member_id': 'mom'})
    own = storage.get_cached_schedule()
    own['events'][0]['practice']['member_id'] = 'mom'
    storage.set_cached_schedule(own)
    from services import agent_tools_v2 as tools, agent_router
    storage.ensure_argyle_member()
    dm = storage.get_or_create_dm('mom', 'argyle')
    storage.ensure_family_channel()
    family = storage.get_family_channel()
    args = {'start_date': DAY.isoformat(), 'end_date': DAY.isoformat()}
    for focus, title in [('channel:' + dm['id'], fx.title('R3')),
                         ('channel:' + family['id'], 'Busy'), ('voice:test', 'Busy'),
                         ('conv:admin-test', fx.title('R3'))]:
        result = tools.execute_tool('get_calendar_events', args, actor=fx.viewers['mom'], focus_key=focus)
        check(result.get('status') == 'success' and result['events'][0]['title'] == title, str(result))
        token = tools._calendar_viewer.set(tools.calendar_viewer(fx.viewers['mom'], focus))
        try:
            event, error = tools._find_event_fuzzy(title, DAY.isoformat())
            check(not error and event['title'] == title, str((event, error)))
        finally:
            tools._calendar_viewer.reset(token)
        replies = [{'tool_calls': [{'name': 'get_calendar_events', 'arguments': args}]}, {'message': 'Done.'}]
        viewed = []
        def read_calendar(*a, **kw):
            result = tools.get_calendar_events(*a, **kw)
            viewed.append(result)
            return result
        with patch.object(agent_router, 'call_gemma_with_fallback', side_effect=replies), \
                patch.object(agent_router, 'get_calendar_events', side_effect=read_calendar):
            agent_router.process_agent_request("what's on today?", acting_member=fx.viewers['mom'], focus_key=focus)
        check(len(viewed) == 1 and viewed[0]['events'][0]['title'] == title, str(viewed))
        check(tools._calendar_viewer.get() == access.HOUSE, 'viewer context reset after call')


def scenario_voice_today_speaks_neutral_practice():
    import uuid
    import main
    from starlette.requests import Request
    from services import app_voice, agent_router
    fx = access_fixture.build()
    seed(fx)
    token = storage.create_member_token('mom')
    turn = app_voice.begin(storage.get_member('mom'), token, uuid.uuid4().hex)
    turn.text("what's on today?")
    args = {'start_date': DAY.isoformat(), 'end_date': DAY.isoformat()}
    replies = [{'tool_calls': [{'name': 'get_calendar_events', 'arguments': args}]},
               {'message': 'Busy is at five today.'}]
    request = Request({'type': 'http', 'method': 'POST', 'path': '/', 'query_string': b'',
                       'headers': [(b'x-member-token', token.encode())]})
    with patch.object(agent_router, 'call_gemma_with_fallback', side_effect=replies), \
            patch.object(main, '_fanout_message_notifications'):
        result = main.phone_voice_run(turn.id, request)
    check(result['speech_safe'] and result['speech'] == 'Busy is at five today.', str(result))
    check(fx.title('R3') not in json.dumps(result), str(result))


def scenario_closed_programs_migrate_target_and_commitment_source():
    for state in ('done', 'dropped'):
        fx = access_fixture.build()
        _, cid = seed(fx)
        storage.update_protected_commitment(cid, {'source': None})
        storage.update_program(fx.ids['R3'], {'state': state,
            'baseline': {'target_date': '2027-01-01', 'target_event_id': 'closed-target'},
            'emissions': {'event_ids': ['closed-target'], 'commitment_ids': [cid]}})
        with patch('services.calendar.delete_event', return_value=True) as delete:
            migrations.migrate_remove_target_events_v2499()
            migrations.migrate_commitment_sources_v2499()
        row = storage.get_program(fx.ids['R3'])
        check(delete.call_count == 1 and delete.call_args.args[-1] == 'closed-target', state)
        check(not row['baseline'].get('target_event_id') and not row['emissions']['event_ids'], str(row))
        check(storage.get_protected_commitment(cid)['source']['id'] == row['id'], state + ' backfill')


def scenario_sibling_household_practice_stays_titled():
    from access_shared_signals import request
    from services import home_board, family_day
    import main
    fx = access_fixture.build()
    event, _ = seed(fx, 'R5s')
    check(not access.record_visible('program', storage.get_program(fx.ids['R5s']), fx.viewers['kid']),
          'fixture really fails the sibling scope base')
    for path in ('/api/schedule', '/api/packing/day?date=2026-10-16',
                 '/api/practice-windows?start_date=2026-10-16&end_date=2026-10-16'):
        with patch.object(main, 'trigger_background_refresh'):
            response = request(fx, 'kid', 'GET', path)
        check(response.status_code == 200 and fx.title('R5s') in response.text, path + ': ' + response.text)
    raw = storage.get_cached_schedule()
    for viewer in (access.HOUSE, fx.viewers['kid']):
        check(access.schedule_view(raw, viewer)['events'][0] == event, 'calendar keeps complete sibling practice')
        check(access.shared_schedule_view(raw, viewer)['events'][0] == event, 'wall union agrees')
        day = home_board.day_schedule(DAY, raw, viewer=viewer)
        check(fx.title('R5s') in json.dumps(day), 'member day schedule retains title')
        check(fx.title('R5s') in json.dumps(family_day.blocks_for(DAY, raw, NOW, viewer=viewer)),
              'family day retains title')
    # The member-day route deliberately omits practice cards, but must consume
    # the same titled schedule; no unrelated day payload expansion here.
    consumed = []
    real_cached_schedule = access.cached_schedule
    def consume_schedule(viewer=access.HOUSE):
        result = real_cached_schedule(viewer)
        consumed.append((viewer, result))
        return result
    with patch.object(access, 'cached_schedule', side_effect=consume_schedule) as consume:
        response = request(fx, 'kid', 'GET', '/api/members/kid/day?date=2026-10-16')
    check(response.status_code == 200 and consume.called, response.text)
    check(any(viewer.get('id') == 'kid' and fx.title('R5s') in json.dumps(blob)
              for viewer, blob in consumed), 'member day actually consumes Kate\'s titled sibling practice')


def scenario_legacy_commitment_projection_and_orphan_writes():
    from access_shared_signals import request
    from services import watchers
    import main
    fx = access_fixture.build()
    _, cid = seed(fx)
    storage.update_protected_commitment(cid, {'source': None})
    row = storage.get_protected_commitment(cid)
    check(access.commitment_view(row, access.HOUSE)['title'] == 'Busy', 'legacy emitter fallback is central')
    check(access.commitment_view(row, fx.viewers['dad'])['title'] == 'Busy', 'unlisted parent gets neutral legacy title')
    with patch.object(access, 'commitment_view', wraps=access.commitment_view) as project:
        watchers._commitment_findings(NOW)
    check(project.called, 'watcher really uses the shared commitment projection')
    storage.update_protected_commitment(cid, {'source': {'kind': 'program', 'id': 'gone-program'}})
    storage.update_program(fx.ids['R3'], {'emissions': {}})
    response = request(fx, 'dad', 'GET', '/api/commitments')
    check(response.status_code == 200 and all(word not in response.text for word in
          (fx.title('R3'), cid, 'Busy')), 'orphan commitment is absent without title, id or Busy')
    with patch.object(main, 'trigger_background_refresh'):
        response = request(fx, 'dad', 'PATCH', '/api/commitments/' + cid, json={'title': 'Edited orphan'})
        check(response.status_code == 200 and storage.get_protected_commitment(cid)['title'] == 'Edited orphan', response.text)
        response = request(fx, 'dad', 'DELETE', '/api/commitments/' + cid)
    check(response.status_code == 200 and storage.get_protected_commitment(cid) is None, response.text)


def scenario_a_childs_private_list_hides_practice_from_the_parent_it_leaves_out():
    """R15 is Kate's own program in her private project whose explicit list is [Kate, Mom]
    (project audiences spec §1): the parent-of-child-keeper bypass yields to the list, so Dad
    sees a Busy block, gets a neutral push as her driver, and finds nothing by title."""
    fx = access_fixture.build()
    event, cid = seed(fx, 'R15')
    storage.update_member('kid', {'color_code': '#123456'})
    for col in ('dad', 'aunt'):
        window = programs.practice_windows(DAY, DAY, viewer=fx.viewers[col])[0]
        check(set(window) == set(access.NEUTRAL_PRACTICE_KEYS) | {'id', 'title'}, f'{col}: {window}')
        check(window['title'] == 'Busy' and window['color'] == '#123456', f'{col}: {window}')
        check(window['id'].startswith('busy-') and fx.ids['R15'] not in window['id'], f'{col}: hashed neutral id')
    for col in ('mom', 'kid'):
        owned = programs.practice_windows(DAY, DAY, viewer=fx.viewers[col])[0]
        check(owned['title'] == fx.title('R15') and owned['steps'] == [fx.secret('R15')], f'{col}: {owned}')
    view = access.commitment_view(storage.get_protected_commitment(cid), fx.viewers['dad'])
    check(view['title'] == 'Busy', f"Dad's commitment is neutral: {view}")
    from services import subjects
    check(not subjects.find('event', fx.title('R15'), fx.viewers['dad']), 'Dad cannot find her practice by title')
    check(subjects.find('event', fx.title('R15'), fx.viewers['kid']), 'the child still matches their own practice')


def scenario_a_driver_left_off_a_childs_list_gets_a_neutral_push():
    fx = access_fixture.build()
    seed(fx, 'R15')
    storage.update_member('kid', {'driver_id': 'dad-driver'})
    storage.update_member('dad', {'driver_id': 'dad-driver'})
    windows = programs.due_practice_pushes(NOW)
    check(windows, 'a due window really reaches the push entry point')
    text = json.dumps(windows)
    check(fx.secret('R15') not in text and fx.title('R15') not in text, 'Dad sees no program words: ' + text)
    check(windows[0]['title'] == 'Practice time', 'neutral practice push')
    check(fx.ids['R15'] not in text, 'push tag does not disclose the program id')


def scenario_moms_private_list_hides_kates_program_practice_from_dad():
    fx = access_fixture.build()
    event, cid = seed(fx, 'R17')
    for col in ('mom', 'kid', 'dad', 'aunt', 'house'):
        windows = programs.practice_windows(DAY, DAY, viewer=fx.viewers[col])
        check(windows and (fx.secret('R17') in json.dumps(windows)) == (col in ('mom', 'kid')),
              f'R17 practice words for {col}: {windows}')
        view = access.commitment_view(storage.get_protected_commitment(cid), fx.viewers[col])
        check(view['title'] == (fx.title('R17') if col in ('mom', 'kid') else 'Busy'),
              f'R17 commitment for {col}: {view}')


def scenario_coverage_options_returns_404_for_a_gone_practice():
    from access_shared_signals import request
    fx = access_fixture.build()
    event, _ = seed(fx)
    storage.update_program(fx.ids['R3'], {'deleting': 'coverage-delete'})
    response = request(fx, 'mom', 'GET', '/api/coverage/' + event['id'] + '/options')
    check(response.status_code == 404 and fx.title('R3') not in response.text, response.text)


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

"""Runtime probes for every calendar reader (access spec 4.7)."""
import json
import datetime as dt
import importlib
from contextlib import ExitStack
from unittest.mock import patch

from harness import check
from test_access_calendar import seed, DAY, NOW
from services import access, access_readers, storage, programs
from access_shared_signals import request
import main


def text(out):
    return json.dumps(out, default=str)


def run(fx, key, col, rid):
    if key not in ('R3', 'R5p') or col == 'pat':
        return 'skip'  # no other program rows in this fixture; disabled credentials rejected by auth
    if rid[0] == 'reader':
        if col != 'house':
            return 'skip'  # these consumers are HOUSE; signed-in reads are exercised through HTTP
        return reader_probe(fx, key, rid[-1])
    ev, cid = seed(fx, key)
    path = rid[-1]
    if rid[0] == 'route':
        if path == '/api/schedule':
            with patch.object(main, 'trigger_background_refresh'):
                response = request(fx, col, 'GET', path)
        elif path in ('/api/practice-windows', '/api/packing/day'):
            query = '?start_date=2026-10-16&end_date=2026-10-16' if 'practice' in path else '?date=2026-10-16'
            response = request(fx, col, 'GET', path + query)
        elif path == '/api/commitments' and rid[1] == 'GET':
            response = request(fx, col, 'GET', path)
            if col == 'house' and response.status_code != 200:
                check(response.status_code in (401, 403), response.text)
                return 'skip'  # existing endpoint role gate
        else:
            return other_route(fx, key, col, rid, ev, cid)
        if col in ('kid', 'hal', 'house') and response.status_code in (401, 403):
            check(fx.secret(key) not in response.text, 'existing scope gate reveals nothing')
            return 'skip'
        check(response.status_code == 200, response.text)
        out = response.json()
        check('error' not in out if isinstance(out, dict) else True, text(out))
        want = col in ('mom', 'dad', 'kid') if key == 'R3' else col in ('mom', 'dad', 'aunt', 'kid', 'house')
        # Packing includes the same complete event on the day spine.
        check((fx.title(key) in text(out)) == want, f'{rid} {key} {col}: {text(out)[:1800]}')
        if not want:
            check(fx.secret(key) not in text(out), 'no lesson words without a title')
        return 'skip'  # assertions include exact payload/HTTP shape, not only title classification


def other_route(fx, key, col, rid, ev, cid):
    method, path = rid[1:]
    path = path.replace('{member_id}', 'kid').replace('{commitment_id}', cid)
    captures = []
    with ExitStack() as stack:
        stack.enter_context(patch.object(main, 'trigger_background_refresh'))
        from services import prep_kits, ha_api
        stack.enter_context(patch.object(prep_kits, 'suggest_kits',
                                         side_effect=lambda titles: captures.extend(titles) or []))
        stack.enter_context(patch.object(ha_api, 'get_state', return_value=None))
        body = {}
        if path == '/api/commitments' and method == 'POST':
            body = {'id': 'hand-created-' + col, 'title': 'Hand-created time', 'member_id': 'mom',
                    'days_of_week': [4], 'time_start': '19:00', 'time_end': '19:30'}
        elif method == 'PATCH':
            body = {'title': 'Changed by hand'}
        elif path == '/api/overrides/check':
            body = {'event_id': ev['id'], 'driver_id': 'driver-mom'}
        query = '?date=2026-10-16' if path.endswith(('/day', '/plan')) else ''
        response = request(fx, col, method, path + query,
                           **({'json': body} if method in ('POST', 'PATCH') else {}))
    if col in ('house', 'kid', 'hal', 'aunt') and response.status_code in (401, 403):
        return 'skip'  # preserve pre-existing route/scope gates
    if method in ('PATCH', 'DELETE'):
        want = col in ('mom', 'dad', 'kid') if key == 'R3' else col in ('mom', 'dad', 'aunt', 'kid')
        check(response.status_code == (200 if want else 404), response.text)
        if not want:
            check(storage.get_protected_commitment(cid)['title'] == fx.title(key), 'refused edit is inert')
        return 'skip'
    check(response.status_code == 200, f'{rid}: {response.text}')
    payload = response.json()
    check(not (isinstance(payload, dict) and 'error' in payload), str(payload))
    # Some readers have no matching rows (triage ignores practice); a missing
    # title is valid there. No hidden words may reach JSON or an LLM prompt.
    if key == 'R3' and col not in ('mom', 'dad', 'kid'):
        check(fx.title(key) not in text((payload, captures)) and fx.secret(key) not in text((payload, captures)),
              f'{rid} {col}: {text((payload, captures))}')
    return 'skip'


def reader_probe(fx, key, fullname):
    ev, cid = seed(fx, key)
    module_name, name = fullname.rsplit('.', 1)
    module = main if module_name == 'main' else importlib.import_module(module_name)
    fn = getattr(module, name)
    raw = storage.get_cached_schedule()
    eid = ev['id']
    leg = 'init_' + eid
    delivered = []
    def capture(*args, **kwargs):
        delivered.append((args, kwargs))
        return {'id': 'captured', 'status': 'success'}
    # Give the consumer real work. Private practices are display-only in the
    # real solver, but an old cache containing an assignment must still be safe.
    storage.update_member('mom', {'driver_id': 'driver-mom'})
    raw['assignments'] = {eid: 'driver-mom'}
    raw['initial_edges'] = {'driver-mom': {eid: {'travel_mins': 10}}}
    raw['route_edges'] = {'driver-mom': {'source': {'to_event': eid}}}
    storage.set_cached_schedule(raw)
    with ExitStack() as stack:
        view = stack.enter_context(patch.object(access, 'schedule_view', wraps=access.schedule_view))
        record = stack.enter_context(patch.object(access, 'record_visible', wraps=access.record_visible))
        from services import ha_api, model_pools, family_digest, drive_arrival, agent_tools_v2
        stack.enter_context(patch.object(ha_api, 'get_state', return_value=None))
        stack.enter_context(patch.object(main, '_notify_member_lanes', side_effect=capture))
        stack.enter_context(patch.object(agent_tools_v2, '_post_chat_message', side_effect=capture))
        stack.enter_context(patch.object(family_digest, 'in_kid_quiet_hours', return_value=False))
        stack.enter_context(patch.object(storage, 'get_in_progress_drives', return_value=[leg]))
        stack.enter_context(patch.object(storage, 'get_drive_status', return_value={'status': 'in_progress', 'eta_ts': NOW.timestamp()-600}))
        stack.enter_context(patch.object(storage, 'get_drive_status_rows', return_value=[{
            'leg_id': leg, 'status': 'in_progress', 'eta_ts': NOW.timestamp()-600}]))
        stack.enter_context(patch.object(storage, 'mark_drive_status'))
        if module_name.endswith('agent_tools_v2'):
            query = 'Busy' if key == 'R3' else fx.title(key)
            if name == 'get_calendar_events': out = fn(DAY.isoformat(), DAY.isoformat())
            elif name == '_driver_events_for_date': out = fn('driver-mom', DAY)
            elif name == '_find_event_fuzzy': out = fn(query, DAY.isoformat())
            elif name == 'cover_with_assist': out = fn('no match', target_date=DAY.isoformat(), clear=True)
            elif name == 'get_assist_coverage':
                stack.enter_context(patch.object(storage, 'get_assist_assignment_map', return_value={eid: 'outside'}))
                out = fn(DAY.isoformat())
            else: raise AssertionError(fullname)
        elif module_name.endswith('family_day'):
            if name == 'blocks_for': out = fn(DAY, raw, NOW)
            elif name == '_raw_blocks': out = fn(DAY, raw, NOW)
            else: out = fn(NOW, raw)
        elif module_name.endswith('family_digest'): out = fn(DAY)
        elif module_name.endswith('programs'):
            if name == 'due_practice_pushes':
                storage.update_member('kid', {'driver_id': 'hal-driver'})
                storage.update_member('hal', {'driver_id': 'hal-driver'})
            out = fn(NOW) if name == 'due_practice_pushes' else fn(DAY, DAY)
        elif module_name.endswith('cancellations'): out = fn(ev, '', False)
        elif module_name.endswith('coverage_options'):
            if name == '_protected_window': out = fn('kid', NOW)
            elif name == 'ladder': out = fn(ev, raw, NOW)
            else: out = fn(eid, contact_name='A friend', asked_by='mom')
        elif module_name.endswith('drive_arrival'):
            if name == '_route_leg_context': out = fn('route_source_' + eid, raw)
            elif name == 'run_nudges': out = fn(NOW.timestamp(), capture)
            elif name == 'check_arrivals': out = fn(NOW.timestamp())
            elif name == 'eta_for_start': out = fn(leg, NOW.timestamp())
            else: out = fn(leg, lat=35, lng=-78, accuracy=10, now_ts=NOW.timestamp())
        elif module_name.endswith('drive_sheet'):
            if name == 'ride_members_for_event': out = fn(ev, eid, raw)
            elif name == '_message_audience': out = fn(leg, raw)
            elif name == 'sheet': out = fn(leg, NOW)
            else: out = fn(leg, 'on_my_way', fx.viewers['mom'])
        elif module_name.endswith('negotiation'):
            if name == 'candidates': out = fn(raw, eid, raw['assignments'])
            elif name == '_cached_event': out = fn(eid)
            else: out = fn({'lever': 'skip_optional', 'payload': {'event_id': eid}})
        elif module_name.endswith('occasions'): out = fn() if name == '_sched' else fn(NOW)
        elif module_name.endswith('outings'):
            out = fn(DAY, raw, NOW) if name == 'outings_for' else fn({'event_ids': [eid]}, raw)
        elif module_name.endswith('presence'):
            if name == 'members_at_event': out = fn(ev, eid, raw)
            elif name == 'moment_push_audience': out = fn({'event_id': eid, 'member_ids': ['mom', 'dad']}, raw)
            else: out = fn(capture, NOW)
        elif module_name.endswith('runway'): out = fn(fx.viewers['kid'], DAY.isoformat())
        elif module_name.endswith('situations'): out = fn(eid)
        elif module_name.endswith('status_protocols'):
            stack.enter_context(patch.object(storage, 'get_all_status_protocols', return_value=[{
                'id': 'probe-protocol', 'member_id': 'mom', 'keywords': ['unmatched-keyword']}]))
            out = fn(NOW)
        elif module_name.endswith('subjects'): out = fn(ev, access.HOUSE, False, None)
        elif module_name.endswith('meals'): out = fn(DAY.isoformat(), sched=raw)
        elif module_name.endswith('email_ingest'):
            storage.event_proposals_table.truncate()
            stack.enter_context(patch.object(model_pools, 'credentials', return_value=('test', 'key')))
            # Dedupe annotation and prompt are both visible outputs. Exercise
            # the actual entry points, not a standalone sanitizer.
            def duplicate(p, existing, events):
                capture(events)
                if not events:
                    return None
                return {'title': events[0]['title'], 'start': events[0]['start'],
                        'id': events[0]['id'], 'source': 'calendar', 'rule': 'same-time'}
            matcher = stack.enter_context(patch.object(module, '_is_duplicate', side_effect=duplicate))
            item = {'kind': 'event', 'title': 'School flyer', 'date': DAY.isoformat(),
                    'start_time': '17:00', 'confidence': 0.9}
            if name == 'run_photo_ingest':
                stack.enter_context(patch.object(model_pools, 'call_pool_json', side_effect=lambda *a, **kw: capture(a) and {'items': [item]}))
                out = fn('AA==', 'image/png')
            else:
                stack.enter_context(patch.object(module, 'fetch_new_messages', return_value=([
                    {'uid': '1', 'from': 'school@example.org', 'subject': 'A flyer', 'text': 'School flyer'}], None)))
                stack.enter_context(patch.object(module, 'extract_items', side_effect=lambda *a, **kw: capture(kw) and [item]))
                stack.enter_context(patch.object(module, 'mark_handled'))
                stack.enter_context(patch.object(module, '_match_thread'))
                out = fn()
            proposals = storage.get_proposals()
            check(matcher.called and proposals, 'the real duplicate-annotation path ran')
            check(proposals[0]['duplicate_of'] == ('Busy' if key == 'R3' else fx.title(key)), str(proposals))
            delivered.append(proposals)
        elif module_name == 'main':
            if name == '_assist_event_context': out = fn(eid)
            elif name == 'flush_assignment_notifications':
                stack.enter_context(patch.object(main, 'send_push', side_effect=capture))
                main._pending_assignment_changes[eid] = {
                    'first_old': None, 'last_new': 'driver-mom', 'ev': ev}
                out = fn()
            elif name == '_notify_kids_driver_changes':
                out = fn({eid: {'first_old': 'old', 'last_new': 'driver-mom', 'ev': ev}}, NOW-dt.timedelta(hours=1))
            elif name == '_notify_ride_eta_update': out = fn(eid, leg, NOW)
            else: out = fn(eid, NOW, leg)
        else: raise AssertionError('no runtime call for ' + fullname)
        if name not in ('_protected_window',):
            check(view.called or (module_name.endswith('programs') and record.called),
                  fullname + ' did not reach the calendar access boundary')
    if key == 'R3':
        check(fx.title(key) not in text((out, delivered)) and fx.secret(key) not in text((out, delivered)),
              fullname + ': ' + text((out, delivered))[:2000])
    return 'skip'


def register(probe):
    for rid, cls, _, _ in access_readers.READERS:
        if cls == '4.7-calendar':
            probe(rid)(lambda fx, key, col, rid=rid: run(fx, key, col, rid))

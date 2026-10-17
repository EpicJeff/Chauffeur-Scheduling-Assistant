"""Runtime probes for access rule §§4.6 and 4.8; expectations are spec §7."""
import datetime as dt
import json
from contextlib import ExitStack
from unittest.mock import patch

from fastapi.testclient import TestClient
from harness import check
import access_fixture
from test_access_core import TABLE, COLS, KIND, load as load_pair
from services import access, access_readers, storage
from services import house_programs, house_attention, house_room, kitchen_room, study
from services import programs, home_board, findings, mind, watchers, replies, missions, planned
import main

NOW = dt.datetime(2026, 10, 16, 12)


def load(fx, key):
    return load_pair(fx, key)[1]


def fresh():
    storage.findings_table.truncate()
    storage.mind_insights_table.truncate()
    storage.protected_commitments_table.truncate()
    return access_fixture.build()


def text(value):
    return json.dumps(value, default=str, ensure_ascii=False)


def seen(value, fx, key):
    return _observed(text(value), fx, key) is not None


def allowed(key, col, shared=False):
    return _expect('4.6-shared-screen' if shared else '4.8-signals', key, col) is not None


def seed(fx):
    storage.findings_table.truncate()
    events = []
    for key in ('R3', 'R5p'):
        storage.update_program(fx.ids[key], {
            'shape': {'phases': [{'name': fx.secret(key), 'weeks': 1,
                                  'milestone': fx.secret(key), 'steps': [fx.secret(key)]}]},
            'sessions': [{'ts': NOW.timestamp()}]})
        events.append({'id': 'practice-' + fx.ids[key], 'title': fx.title(key),
                       'description': fx.secret(key), 'start': '2026-10-16T17:00:00',
                       'end': '2026-10-16T18:00:00', 'event_type': 'practice',
                       'calendar_ids': ['kid-cal'],
                       'practice': {'program_id': fx.ids[key], 'member_id': 'kid',
                                    'phase_name': fx.secret(key), 'unit_body': fx.secret(key)}})
    storage.set_cached_schedule({'events': events, 'assignments': {}, 'unassigned': []})


def request(fx, col, method, path, **kw):
    headers = ({'X-Device-Token': storage.enrol_device_token('task810-panel', 'Panel')}
               if col == 'house' else
               {'X-Member-Token': storage.create_member_token(fx.viewers[col]['id'])})
    with patch.object(storage, 'get_settings', return_value={**storage.get_settings(), 'auth_enforce': True}):
        return TestClient(main.app).request(method, path, headers=headers, **kw)


def shared_probe(fx, key, col, rid):
    seed(fx)
    viewer = fx.viewers[col]
    name = rid[-1].rsplit('.', 1)[-1]
    want = allowed(key, col, True)
    if rid[0] == 'route':
        if col == 'pat':
            return 'skip'  # disabled tokens are rejected by auth, not a shared-screen identity
        path = rid[-1].replace('{program_id}', fx.ids[key])
        if path == '/api/study/state' and col in ('house', 'kid', 'hal'):
            response = request(fx, col, rid[1], path)
            check(response.status_code in (401, 403), response.text)
            return 'skip'  # authentication precedes §4.6
        from services import model_pools
        with patch.object(model_pools, 'call_pool_json', return_value={}), patch.object(storage, 'get_program_lesson', return_value={
                'scenes': [{'say': fx.title(key) + ' ' + fx.secret(key)}], 'origin': 'generated'}):
            response = request(fx, col, rid[1], path, **({'json': {}} if rid[1] == 'POST' else {}))
        if '{program_id}' in rid[-1]:
            check(response.status_code != 404 if want else response.status_code == 404,
                  f'{rid} {key} {col}: {response.status_code} {response.text}')
            if not want:
                check(not seen(response.text, fx, key), 'hidden route has no words')
            elif rid[1] == 'GET':
                check(seen(response.text, fx, key), 'allowed shared session/scenes retain words')
            return 'skip'
        out = response.text
    elif name == 'objects':
        out = house_programs.objects(viewer=viewer)
    elif name == 'session':
        out = house_programs.session(fx.ids[key], NOW, viewer=viewer)
    elif name == '_programs':
        windows = [{'program_id': fx.ids[key], 'title': fx.title(key)}]
        with patch.object(programs, '_practice_windows', return_value=windows):
            out = house_attention._programs(NOW, viewer=viewer)
        check(out['available'] == int(want), f'attention {key} {col}: {out}')
        return 'skip'
    elif name == '_tile_programs':
        with patch.object(storage, 'get_programs', return_value=[load(fx, key)]):
            out = home_board._tile_programs(NOW, viewer=viewer)
        check(bool(out) == want, f'program mount {key} {col}: {out}')
        return 'skip'
    elif name == 'celebrations':
        out = programs.celebrations(NOW, viewer=viewer)
        # Only the first milestone is featured, but recent practice lists both.
    elif name in ('_board', '_binders', '_calendar', '_map', '_monitor') and 'study' in rid[-1]:
        out = getattr(study, name)(NOW, viewer=viewer)
        if name in ('_calendar', '_map', '_monitor'):
            check(fx.secret(key) not in text(out) if not want else True, text(out))
            return 'skip'  # these projections count events / show trip pins, not pieces
    elif name == '_today_events':
        out = kitchen_room._today_events(NOW, viewer=viewer)
    elif name == '_mudroom':
        out = house_room._mudroom(NOW, viewer=viewer)
        check(not seen(out, fx, key) if not want else True, text(out))
        return 'skip'
    elif name == '_trip_rows':
        out = home_board._trip_rows(NOW, viewer=viewer)
        check(not seen(out, fx, key), 'practice must not become a trip')
        return 'skip'
    elif name == 'day_schedule':
        out = home_board.day_schedule(NOW.date(), viewer=viewer)
    elif name == 'todays_runs':
        out = home_board.todays_runs(NOW.date(), now=NOW, viewer=viewer)
        check(not seen(out, fx, key), 'unassigned practice is not a drive')
        return 'skip'
    elif name == '_tile_calendar':
        out = home_board._tile_calendar(NOW, config={'view': 'list'}, viewer=viewer)
    elif name == '_tile_drives':
        out = home_board._tile_drives(NOW, [], viewer=viewer)
        check(not seen(out, fx, key), text(out))
        return 'skip'
    elif name == '_tile_mind':
        storage.add_finding({'subject_type': KIND[key], 'subject_id': fx.ids[key],
                            'line': fx.title(key) + ' ' + fx.secret(key), 'state': 'open'})
        out = home_board._tile_mind(NOW, viewer=viewer)
        # Identity-free screens show insights only. People get HOUSE union own.
        check(seen(out, fx, key) == (col != 'house' and col != 'pat' and want), text(out))
        return 'skip'
    elif name == 'build':
        home_board._CACHE.clear()
        out = home_board.build(json.dumps([{'id': 'probe', 'type': 'calendar',
                                          'config': {'view': 'list'}}]), now=NOW, viewer=viewer)
        check(not seen(out, fx, key) if not want else True, text(out))
        return 'skip'
    else:
        raise AssertionError(f'unhandled shared reader {rid}')
    check(seen(out, fx, key) == want, f'{rid} {key} {col}: want {want}: {text(out)[:1600]}')
    if not want:
        check(fx.secret(key) not in text(out), 'no secret without title either')
    if KIND[key] == 'thread' and _expect('4.6-shared-screen', key, col) == access.KEEPER:
        check(_observed(text(out), fx, key) == access.KEEPER, 'keeper keeps title, never cached note words')
    return 'skip'


def signal_probe(fx, key, col, rid):
    # Delivery and collector policy use their own §7 expectations, rather than
    # pretending a collector has a signed-in viewer.
    name = rid[-1].rsplit('.', 1)[-1]
    if name not in ('open_findings', '/api/findings', '/api/findings/{finding_id}/resolve',
                    'list_open_findings', 'snapshot', '_threads', '_calendar', '_gather_deltas'):
        if key == 'R1' and col == 'mom':
            delivery_contract(name)
        elif KIND[key] == 'mission' and col == 'mom' and name in ('_dm_person', '_ask', '_land_finish'):
            delivery_contract(name)
        elif KIND[key] == 'program' and key == 'R3' and col == 'mom':
            delivery_contract(name)
        return 'skip'
    seed(fx)
    fid = storage.add_finding({'subject_type': KIND[key], 'subject_id': fx.ids[key],
                               'line': fx.title(key) + ' ' + fx.secret(key),
                               'state': 'open', 'severity': 'decide'})
    viewer = fx.viewers[col]
    want = allowed(key, col)
    if rid[0] == 'route':
        response = request(fx, col, rid[1], rid[-1].replace('{finding_id}', fid),
                           **({'json': {'act': 'dismiss'}} if rid[1] == 'POST' else {}))
        if col in ('house', 'kid', 'hal', 'pat'):
            check(response.status_code in (401, 403), response.text)
            return 'skip'
        if rid[1] == 'POST':
            check(response.status_code == (200 if want else 404), response.text)
            storage.update_finding(fid, {'state': 'open'})
            return 'skip'
        out = response.text
    elif name == 'open_findings':
        out = findings.open_findings(viewer=viewer)
    elif name == 'list_open_findings':
        from services import agent_tools_v2 as tools
        out = tools.list_open_findings(acting_member=viewer)
    else:
        want = allowed(key, 'house')
        if name == '_gather_deltas':
            storage.set_app_state('mind_finding_keys', ['baseline'])
            out = mind._gather_deltas(NOW)
        else:
            out = mind.snapshot(NOW)  # _threads and _calendar are nested snapshot sections
    check(seen(out, fx, key) == want, f'{rid} {key} {col}: {text(out)[:1600]}')
    storage.update_finding(fid, {'state': 'done'})
    return 'skip'


def captures(stack):
    sent = []
    def post(dm, argyle, body, card=None, **kw):
        sent.append((dm.get('members') or dm.get('member_ids') or [], body, card))
        return {'id': 'captured'}
    stack.enter_context(patch.object(storage, 'get_or_create_dm',
                                    side_effect=lambda a, b: {'id': b, 'members': [b]}))
    for module, name in ((replies, '_post'), (missions, '_post')):
        stack.enter_context(patch.object(module, name, side_effect=post))
    from services import agent_tools_v2
    stack.enter_context(patch.object(agent_tools_v2, '_post_chat_message', side_effect=post))
    return sent


def delivery_contract(name):
    fx = fresh()
    seed(fx)
    with ExitStack() as stack:
        sent = captures(stack)
        stack.enter_context(patch.object(programs, 'maybe_rebaseline', return_value=None))
        if name != '_prep_kit_findings':
            stack.enter_context(patch.object(watchers, '_prep_kit_findings', return_value=[]))
        if name in ('_dm_person', '_ask', '_land_finish'):
            if name == '_ask':
                planned._ask(fx.ids['R2'], 'question', fx.secret('R2'))
            elif name == '_land_finish':
                missions._land_finish(storage.get_mission(fx.ids['R2']), {'summary': fx.secret('R2')})
            else:
                missions._dm_person(storage.get_mission(fx.ids['R2']), fx.secret('R2'))
            check(all('pat' not in s[0] for s in sent), 'disabled parent never receives')
            for ids, body, card in sent:
                if 'aunt' in ids:
                    check(fx.secret('R2') not in text((body, card)), 'keeper DM carries no transcript')
            storage.update_mission(fx.ids['R2'], {'created_by': ''})
            sent.clear()
            missions._dm_person(storage.get_mission(fx.ids['R2']), 'creatorless')
            check([s[0] for s in sent] == [['mom']], f'creatorless: {sent}')
        elif name in ('_recipients', 'read', 'flush_pending_dms'):
            storage.append_thread_history(fx.ids['R1'], {'kind': 'received', 'message_id': 'm',
                                                       'text': fx.secret('R1'), 'dm_pending': True})
            if name == '_recipients':
                check([m['id'] for m in replies._recipients(load(fx, 'R1'))] == ['aunt'], 'private reply')
            elif name == 'read':
                storage.append_thread_history(fx.ids['R1'], {'kind': 'received', 'message_id': 'new',
                                                           'text': fx.secret('R1')})
                with patch.object(replies, '_now', return_value=NOW):
                    replies.read(fx.ids['R1'], 'new')
                check([s[0] for s in sent] == [['aunt']], f'reply read: {sent}')
            else:
                replies.flush_pending_dms(NOW)
                check([s[0] for s in sent] == [['aunt']], f'reply flush: {sent}')
            check(all(fx.secret('R1') not in text((body, card)) for ids, body, card in sent if ids == ['aunt']),
                  'keeper reply DM has no next action or reply words')
        elif name in ('_thread_stalls', '_mission_states', '_program_findings', 'run_watchers',
                      '_post_action_cards', '_heads_up_line'):
            if name == '_heads_up_line':
                private = findings.make('private-line', fx.title('R1') + ' ' + fx.secret('R1'),
                                        subject_type='thread', subject_id=fx.ids['R1'])
                check(not watchers._heads_up_line(private, access.HOUSE), 'no unstored private line to HOUSE')
                check(seen(watchers._heads_up_line(private, fx.viewers['aunt']), fx, 'R1'), 'private line to keeper')
            if name == '_post_action_cards':
                from services import chat_actions
                private = findings.make('private-card', fx.title('R3'), subject_type='program', subject_id=fx.ids['R3'],
                                        action={'label': fx.secret('R3'), 'action_type': 'reshape_program',
                                                'payload': {'program_id': fx.ids['R3']}})
                with patch.object(chat_actions, 'create_action_proposal', return_value={'status': 'refused'}) as create:
                    watchers._post_action_cards({'id': 'dm'}, storage.ensure_argyle_member(), [private], fx.viewers['aunt'])
                    check(not create.called, 'hidden watcher action never becomes a card')
                    watchers._post_action_cards({'id': 'dm'}, storage.ensure_argyle_member(), [private], fx.viewers['dad'])
                    check(create.call_count == 1, 'parent of child keeper retains the watcher hand path')
            fs = watchers._thread_stalls(NOW)
            check(not any(f.subject_id == fx.ids['R1'] for f in fs), 'restricted stall has no household Finding')
            check(any(f.subject_id == fx.ids['R6'] for f in fs), 'I3 subject-only keeps household path')
            check(any(f.subject_id == fx.ids['R8'] for f in fs), 'I3 parents subject keeps household path')
            if name == '_mission_states':
                check(not any(f.subject_id == fx.ids['R2'] for f in watchers._mission_states(NOW)), 'private mission')
            if name == '_program_findings':
                with patch.object(programs, 'orphaned_emissions', return_value=['gone']), \
                        patch.object(programs, 'forget_emissions'):
                    check(not any(f.subject_id == fx.ids['R3'] for f in watchers._program_findings(NOW)), 'private drift')
            if name in ('run_watchers', '_post_action_cards', '_heads_up_line', '_thread_stalls'):
                sent.clear()
                watchers.run_watchers(NOW)
                r1 = [s for s in sent if seen(s, fx, 'R1')]
                check(r1 and all(s[0] == ['aunt'] for s in r1), f'R1 private page: {r1}')
                check(all('pat' not in s[0] for s in sent), 'Pat never paged')
                storage.update_thread(fx.ids['R1'], {'next_action_at': '2026-10-15'})
                sent.clear()
                watchers.run_watchers(NOW + dt.timedelta(hours=1))
                check(not any(seen(s, fx, 'R1') for s in sent), 'quiet private stall dropped')
                r4 = [s for s in sent if seen(s, fx, 'R4')]
                check(not r4, 'notified R4 dedupes on the second sweep')
        elif name in ('_commitment_findings', '_prep_kit_findings', '_unassigned_findings',
                      'build_household_briefing'):
            if name == '_prep_kit_findings':
                from services import prep_kits
                prompts = []
                with patch.object(prep_kits, 'suggest_kits', side_effect=lambda titles, **kw: prompts.extend(titles) or []):
                    watchers._prep_kit_findings(NOW.timestamp())
                check(fx.title('R3') not in text(prompts), 'prep prompt has no private title')
            elif name == 'build_household_briefing':
                from services import family_digest
                out = family_digest.build_household_briefing(NOW.date())
                check(not seen(out, fx, 'R3'), 'briefing has no private title')
            else:
                cache = storage.get_cached_schedule()
                cache['unassigned'] = [e['id'] for e in cache['events']]
                storage.add_protected_commitment({
                    'id': 'secret-commitment', 'title': fx.title('R3') + ' ' + fx.secret('R3'),
                    'member_id': 'mom', 'days_of_week': [NOW.weekday()],
                    'time_start': '16:00', 'time_end': '19:00', 'needs_coverage': True,
                    'source': {'kind': 'program', 'id': fx.ids['R3']}})
                # A normal drive overlapping the private emitted commitment
                # checks both the event words and commitment words.
                cache['events'].append({'id': 'drive', 'title': 'Public drive',
                                        'start': '2026-10-16T17:30:00'})
                cache['unassigned'].append('drive')
                storage.set_cached_schedule(cache)
                with patch.object(watchers, '_negotiate_seed'), patch.object(watchers, '_deal_line', return_value=(None, None)), \
                        patch.object(watchers._coverage, 'ladder', return_value=None):
                    out = getattr(watchers, name)(NOW)
                check(out, 'calendar collector actually produced findings')
                check(not seen(out, fx, 'R3'), 'calendar finding no private words')
        else:
            raise AssertionError(f'unhandled signal reader {name}')


def register(probe, expect, observed):
    global _expect, _observed
    _expect, _observed = expect, observed
    for rid, cls, kinds, _ in access_readers.READERS:
        if cls not in ('4.6-shared-screen', '4.8-signals'):
            continue
        def run(fx, key, col, rid=rid, cls=cls):
            if cls == '4.6-shared-screen':
                if KIND[key] != 'program' and not ('study' in rid[-1] and KIND[key] == 'thread') and not rid[-1].endswith('_tile_mind'):
                    return 'skip'  # reader has no source of this kind
                # These probes read the same fixture; only findings are reset
                # by seed(). Delivery contracts below build their own fixture.
                fx = current_fixture()
                return shared_probe(fx, key, col, rid)
            fx = current_fixture()
            return signal_probe(fx, key, col, rid)
        probe(rid)(run)


_fixture = None


def current_fixture():
    global _fixture
    if _fixture is None or storage.get_program(_fixture.ids['R3']) is None:
        _fixture = fresh()
    return _fixture


@patch.object(home_board, 'ACCESS_DIGEST_SECONDS', 0)  # isolate digest input coverage from its memo window
def shared_contracts():
    digest_memo_window()
    round1_shared_contracts()
    fx = fresh()
    seed(fx)
    for col in ('house', 'mom', 'dad', 'aunt', 'kid'):
        out = house_programs.objects(viewer=fx.viewers[col])
        check(seen(out, fx, 'R3') == (col in ('mom', 'dad', 'kid')), 'I4 private practice')
        check(seen(out, fx, 'R5p'), 'I4 signed-in child keeps household practice')
    # Pre-narrowing cache, warm board cache, and current viewer union (I4).
    raw = storage.get_cached_schedule()
    pid = fx.projects['mom_private']['id']
    storage.update_project(pid, {'audience': 'household'})
    home_board._CACHE.clear()
    config = json.dumps([{'id': 'calendar-proof', 'type': 'calendar', 'config': {'view': 'list'}}])
    before = home_board.build(config, now=NOW)
    check(seen(before, fx, 'R3'), 'household practice is titled before narrowing')
    storage.update_project(pid, {'audience': 'private'})
    after = home_board.build(config, now=NOW)
    check(not seen(after, fx, 'R3'), 'warm board cache respects audience narrowing')
    check(seen(home_board.build(config, now=NOW, viewer=fx.viewers['kid']), fx, 'R3'), 'I4 Kate retains title')
    check(storage.get_cached_schedule() == raw, 'redaction never rewrites cached words')
    event = next(e for e in home_board.day_schedule(NOW.date())['events'] if e['title'] == 'Busy')
    check(set(event) == {'id', 'title', 'description', 'start', 'end', 'all_day', 'event_type', 'calendar_ids', 'practice'},
          'Task 9 neutral copy has exactly the declared fields')
    check(set(event['practice']) == {'member_id', 'color', 'date', 'time_start', 'time_end'}, 'neutral practice has no lesson fields')


def signal_contracts():
    round1_signal_contracts()
    for name in ('_dm_person', '_thread_stalls', '_mission_states', '_program_findings',
                 'read', 'flush_pending_dms', '_prep_kit_findings'):
        delivery_contract(name)
    fx = fresh()
    storage.add_mind_insight({'state': 'active', 'line': 'sensitive-secret', 'sensitivity': 'sensitive'})
    from services import situations
    for viewer in (access.HOUSE, access.HOUSE_PARENT):
        check('sensitive-secret' not in text(mind.visible_insights(viewer)), 'idless sensitive insight')
        check('sensitive-secret' not in text(situations.list_situations(viewer, kinds=('insight',))), 'idless insight list')
    check('sensitive-secret' in text(situations.list_situations(fx.viewers['mom'], kinds=('insight',))),
          'a signed-in parent retains sensitive insights')
    # M3: no recipient leaves notification time untouched, on repeated sweeps.
    fx = fresh()
    storage.update_thread(fx.ids['R1'], {'owner_member_id': ''})
    key = 'thread_stall:' + fx.ids['R1']
    old = (NOW - dt.timedelta(days=1)).timestamp()
    storage.set_app_state('watcher_notified', {key: old})
    with ExitStack() as stack:
        sent = captures(stack)
        stack.enter_context(patch.object(watchers, '_prep_kit_findings', return_value=[]))
        stack.enter_context(patch.object(programs, 'maybe_rebaseline', return_value=None))
        for hour in (0, 1):
            watchers.run_watchers(NOW + dt.timedelta(hours=hour))
            check(storage.get_app_state('watcher_notified')[key] == old, 'M3 timestamp ages normally')
        markers = storage.get_app_state('watcher_notified')
        markers.pop(key)
        storage.set_app_state('watcher_notified', markers)
        watchers.run_watchers(NOW + dt.timedelta(hours=2))
        check(key not in storage.get_app_state('watcher_notified'), 'M3 no phantom successful delivery')
        check(not any(seen(s, fx, 'R1') for s in sent), 'M3 nobody receives ownerless private stall')
    # Pre-existing findings are read with today's audience, including history
    # and the actual registry tool (its row is in §4.3).
    fx = fresh()
    fid = storage.add_finding({'subject_type': 'thread', 'subject_id': fx.ids['R1'],
                               'line': fx.title('R1') + ' ' + fx.secret('R1'), 'state': 'done'})
    from services import agent_tools_v2
    for col in ('mom', 'dad', 'aunt'):
        response = request(fx, col, 'GET', '/api/findings?state=done')
        check(seen(response.text, fx, 'R1') == (col in ('mom', 'aunt')), 'historical source audience')
    storage.update_finding(fid, {'state': 'open'})
    for col in ('mom', 'dad', 'aunt', 'house'):
        check(seen(agent_tools_v2.list_open_findings(acting_member=fx.viewers[col]), fx, 'R1') ==
              (col in ('mom', 'aunt')), 'registry finding derives source audience, including keeper')
    # Real DM storage path, with only notification fan-out stubbed.
    fx = fresh()
    storage.chat_messages_table.truncate()
    with patch.object(main, '_push_message_event'), patch.object(main, '_fanout_message_notifications'), \
            patch.object(watchers, '_prep_kit_findings', return_value=[]), \
            patch.object(programs, 'maybe_rebaseline', return_value=None):
        watchers.run_watchers(NOW)
    argyle = storage.ensure_argyle_member()
    for col in ('mom', 'dad', 'aunt', 'pat'):
        dm = storage.get_or_create_dm(argyle['id'], fx.viewers[col]['id'])
        messages = storage.get_channel_messages(dm['id'])
        check(seen(messages, fx, 'R1') == (col == 'aunt'), 'R1 stored privately only for Aunt')
        check(seen(messages, fx, 'R4') == (col in ('mom', 'dad')), 'R4 stored for both active parents')
        if col == 'aunt':
            check(all(fx.secret(key) not in text(messages) for key in ('R1', 'R2')),
                  'stored keeper DMs contain no next-action or question words')
        if col == 'pat':
            check(not messages, 'disabled Pat has no stored DM')
    # An old calendar watermark cannot re-say a private title on removal,
    # including when the raw practice has already left the schedule cache.
    fx = fresh()
    seed(fx)
    storage.set_app_state('mind_event_state', {
        'practice-' + fx.ids['R3'] + '-2026-10-16-17:00': {
            'title': fx.title('R3') + ' ' + fx.secret('R3'),
            'fp': '2026-10-16T17:00:00|2026-10-16T18:00:00|None'}})
    storage.set_cached_schedule({'events': []})
    check(not seen(mind._gather_deltas(NOW), fx, 'R3'), 'removed private practice watermark stays silent')


@patch.object(home_board, 'ACCESS_DIGEST_SECONDS', 0)  # every input still participates when refreshed
def round1_shared_contracts():
    fx = fresh()
    for kind in ('occasion_gap', 'care_gap'):
        storage.add_finding({'kind': kind, 'line': kind + '-finding-secret', 'state': 'open'})
    storage.add_mind_insight({'state': 'active', 'line': 'wall-insight', 'sensitivity': 'normal'})
    wall = home_board._tile_mind(NOW, viewer=access.HOUSE)
    check('wall-insight' in text(wall), 'anonymous wall retains insights')
    check('finding-secret' not in text(wall), 'anonymous wall never shows occasion/care findings')
    kate = home_board._tile_mind(NOW, viewer=fx.viewers['kid'])
    check({(s['kind'], s['id']) for s in wall['situations']} <=
          {(s['kind'], s['id']) for s in kate['situations']}, 'Kate never sees less than wall')
    check('occasion_gap-finding-secret' in text(kate) and 'care_gap-finding-secret' in text(kate),
          'signed-in Kate retains HOUSE findings')

    seed(fx)
    config = json.dumps([{'id': 'cache-proof', 'type': 'calendar', 'config': {'view': 'list'}}])
    home_board._CACHE.clear()
    before = home_board.build(config, now=NOW, viewer=fx.viewers['mom'])
    keys = set(home_board._CACHE)
    storage.update_member('mom', {'last_seen_at': NOW.timestamp(), 'presence': 'away'})
    viewer = storage.get_member('mom')
    after = home_board.build(config, now=NOW, viewer=viewer)
    check(set(home_board._CACHE) == keys and after is before, 'member heartbeat/presence preserves cache key')
    storage.update_project(fx.projects['mom_private']['id'], {'audience': 'household'})
    home_board.build(config, now=NOW, viewer=viewer)
    check(set(home_board._CACHE) != keys, 'project audience changes cache key')

    # Each access input must invalidate a warm board independently. Restore
    # the original value to prove ordinary builds still reuse their entry.
    def changes_key(label, row, update, field, value):
        home_board._CACHE.clear()
        before = home_board.build(config, now=NOW, viewer=viewer)
        keys = set(home_board._CACHE)
        try:
            update(row['id'], {field: value})
            after = home_board.build(config, now=NOW, viewer=viewer)
            check(set(home_board._CACHE) != keys and after is not before,
                  label + ' changes cache key')
        finally:
            update(row['id'], {field: row.get(field)})
        check(home_board.build(config, now=NOW, viewer=viewer) is before,
              label + ' restored key reuses cached board')

    changes_key('project owner', storage.get_project(fx.projects['mom_private']['id']),
                storage.update_project, 'owner_member_id', 'aunt')
    member = storage.get_member('mom')
    for field in ('is_child', 'system'):
        changes_key('member ' + field, member, storage.update_member, field, True)
    for kind, row, update in (
            ('thread', storage.get_thread(fx.ids['R5t']), storage.update_thread),
            ('mission', storage.get_mission(fx.ids['R9b']), storage.update_mission),
            ('program', storage.get_program(fx.ids['R5p']), storage.update_program)):
        for field, value in (('subject_kind', 'occasion'), ('subject_id', 'occ-parents'),
                             ('subject_history', [{'kind': 'occasion', 'id': 'occ-parents'}])):
            changes_key(kind + ' ' + field, row, update, field, value)


def round1_signal_contracts():
    from services import agent_tools_v2, situations, chat_actions
    fx = fresh()
    f = findings.make('thread_stall:' + fx.ids['R1'], fx.title('R1') + ' ' + fx.secret('R1'),
                      kind='thread_stall', subject_type='thread', subject_id=fx.ids['R1'])
    fid = storage.add_finding({'identity': findings.identity(f), 'kind': f.kind, 'state': 'open',
                               'subject_type': 'thread', 'subject_id': fx.ids['R1'], 'line': f.line,
                               'created_at': NOW.timestamp(), 'last_seen_at': NOW.timestamp() - 100})
    original = storage.get_finding(fid)
    with ExitStack() as stack:
        sent = captures(stack)
        stack.enter_context(patch.object(watchers, '_prep_kit_findings', return_value=[]))
        stack.enter_context(patch.object(programs, 'maybe_rebaseline', return_value=None))
        for due in ('2020-01-01', '2026-10-15'):  # paging and quiet restricted stalls
            storage.update_thread(fx.ids['R1'], {'next_action_at': due})
            watchers.run_watchers(NOW)
            check(storage.get_finding(fid) == original, 'restricted signal is seen without updating old row')
            counts = findings.month_counts(NOW.timestamp() - 1, viewer=fx.viewers['mom'])
            check(counts['still_open'] >= 1 and counts['cleared_themselves'] == 0, 'restricted stall is never counted cleared')
        check(any(seen(s, fx, 'R1') for s in sent), 'real sweep delivered restricted stall')
        for ids, body, card in sent:
            if ids == ['aunt']:
                check(fx.secret('R1') not in text((body, card)) and fx.secret('R2') not in text((body, card)),
                      'Aunt watcher DM has no next action or question')
    check(any(r['id'] == fid for r in findings.open_findings(viewer=fx.viewers['mom'])), 'old finding remains readable')

    fx = fresh()
    for key in ('R1', 'R2'):
        fid = storage.add_finding({'identity': 'keeper-' + key, 'kind': 'thread_stall' if key == 'R1' else 'mission_waiting',
                                  'subject_type': KIND[key], 'subject_id': fx.ids[key],
                                  'line': fx.title(key) + ' ' + fx.secret(key), 'state': 'open', 'severity': 'decide',
                                  'status_note': fx.secret(key), 'note_source': 'argyle', 'note_rev': 0, 'rev': 0,
                                  'next_action': fx.secret(key), 'goal': fx.secret(key), 'question': fx.secret(key),
                                  'sit_owner_member_id': 'aunt', 'sit_owned_at': NOW.timestamp()})
        for surface in (agent_tools_v2.list_open_findings(acting_member=fx.viewers['aunt']),
                        request(fx, 'aunt', 'GET', '/api/findings').json(),
                        study._stickies(NOW, fx.viewers['aunt']),
                        situations.view('finding', fid, fx.viewers['aunt'])):
            check(seen(surface, fx, key), 'keeper finding stays present')
            check(fx.secret(key) not in text(surface), 'keeper finding surface contains only neutral words')
        check(situations.view('finding', fid, fx.viewers['aunt'])['owner_member_id'] == 'aunt',
              'keeper projection preserves finding ownership metadata')
        private = findings.make('keeper-' + key, fx.title(key) + ' ' + fx.secret(key),
                                subject_type=KIND[key], subject_id=fx.ids[key])
        check(fx.secret(key) not in watchers._heads_up_line(private, fx.viewers['aunt']), 'keeper heads-up neutral')
        with patch.object(situations, 'view', side_effect=RuntimeError('render failed')):
            check(fx.secret(key) not in watchers._heads_up_line(private, fx.viewers['aunt']), 'keeper fallback stays neutral')
        with patch.object(access, 'record_view', side_effect=RuntimeError('projection failed')):
            check(fx.secret(key) not in watchers._heads_up_line(private, fx.viewers['aunt']), 'failed source projection never leaks raw line')
        storage.update_finding(fid, {'state': 'done'})
        check(fx.secret(key) not in request(fx, 'aunt', 'GET', '/api/findings?state=done').text, 'historical keeper projection')

    fx = fresh()
    private = findings.make('child-card', fx.title('R3'), subject_type='program', subject_id=fx.ids['R3'],
                            action={'action_type': 'reshape_program', 'label': 'Reshape', 'payload': {'program_id': fx.ids['R3']}})
    with ExitStack() as stack:
        sent = captures(stack)
        stack.enter_context(patch.object(watchers, 'collect_findings', return_value=([private], [])))
        stack.enter_context(patch.object(watchers, '_prep_kit_findings', return_value=[]))
        create = stack.enter_context(patch.object(chat_actions, 'create_action_proposal', return_value={'status': 'refused'}))
        watchers.run_watchers(NOW)
        check(any(ids == ['kid'] and seen(body, fx, 'R3') for ids, body, card in sent), 'child keeper gets line')
        check(create.call_count == 2, 'only two parents receive action proposals')
        create.reset_mock()
        watchers._post_action_cards({'id': 'kid'}, storage.ensure_argyle_member(), [private], fx.viewers['kid'])
        check(not create.called, 'child keeper never gets approve card')

    fx = fresh()
    storage.update_thread(fx.ids['R1'], {'owner_member_id': ''})
    old_ts = (NOW - dt.timedelta(days=watchers.NOTIFIED_RETENTION_DAYS + 1)).timestamp()
    for mid, ts in [('old', old_ts), ('recent', NOW.timestamp())]:
        storage.append_thread_history(fx.ids['R1'], {'kind': 'received', 'message_id': mid, 'text': fx.secret('R1'),
                                                    'ts': ts, 'dm_pending': True})
    with ExitStack() as stack:
        sent = captures(stack)
        check(replies.flush_pending_dms(NOW) == 0 and not sent, 'no recipient receives reply')
    history = {h['message_id']: h for h in load(fx, 'R1')['history'] if h.get('message_id') in ('old', 'recent')}
    check(not history['old']['dm_pending'] and history['recent']['dm_pending'], 'recipientless replies age out without refreshing timestamp')
    check(history['old']['ts'] == old_ts, 'reply age remains original')

    fx = fresh()
    storage.add_mind_insight({'state': 'dismissed', 'line': 'sensitive-reaction-history', 'sensitivity': 'sensitive', 'outcome': 'not_useful'})
    storage.add_mind_insight({'state': 'active', 'line': 'sensitive-active-history', 'sensitivity': 'sensitive'})
    check('sensitive-reaction-history' in mind.snapshot(NOW), 'Mind remembers sensitive reactions')
    check('sensitive-active-history' not in text(mind.visible_insights(access.HOUSE)), 'wall still excludes sensitive insights')


def digest_memo_window():
    fx = fresh()
    seed(fx)
    pid = fx.projects['mom_private']['id']
    storage.update_project(pid, {'audience': 'household'})
    home_board.invalidate_cache()
    config = json.dumps([{'id': 'digest-window', 'type': 'calendar', 'config': {'view': 'list'}}])
    with ExitStack() as stack:
        stack.enter_context(patch.object(home_board, 'ACCESS_DIGEST_SECONDS', 3))
        clock = stack.enter_context(patch.object(home_board.time, 'monotonic', return_value=100.0))
        reads = [stack.enter_context(patch.object(storage, name, wraps=getattr(storage, name)))
                 for name in ('get_projects', 'get_all_members', 'get_programs', 'get_threads', 'get_missions')]
        first = home_board.build(config, now=NOW)
        check(seen(first, fx, 'R3'), 'fixture starts titled on the wall')
        counts = [r.call_count for r in reads]
        check(all(counts), 'real board digest reads every access input family')
        check(home_board.build(config, now=NOW) is first, 'warm board reused')
        check([r.call_count for r in reads] == counts, 'warm build performs no access table scans')
        storage.update_project(pid, {'audience': 'private'})
        clock.return_value = 102.0
        check(home_board.build(config, now=NOW) is first, 'memo is deliberately bounded to a few seconds')
        clock.return_value = 103.1
        after = home_board.build(config, now=NOW)
        check(after is not first and not seen(after, fx, 'R3'), 'first build after memo window narrows warm board')
        check(all(r.call_count > n for r, n in zip(reads, counts)), 'digest inputs refresh after the window')
        # Force the interleaving after the timestamp is read, before a warm
        # digest is returned. This runs the real board and invalidation paths.
        invalidations = []
        class InvalidateOnAge:
            def __rsub__(self, stamp):
                invalidations.append(True)
                home_board.invalidate_cache()
                return 0.0
        home_board._ACCESS_DIGEST['at'] = InvalidateOnAge()
        raced = home_board.build(config, now=NOW)
        check(invalidations == [True], 'invalidation ran during memo age check')
        check(raced is not after and not seen(raced, fx, 'R3'),
              'invalidation during memo read rebuilds the board without leaking private words')
        check('digest' not in home_board._ACCESS_DIGEST, 'invalidation leaves no shared digest memo')
        home_board.build(config, now=NOW)
        check('digest' in home_board._ACCESS_DIGEST, 'next build refreshes the invalidated digest')
    home_board.invalidate_cache()


if __name__ == '__main__':
    import test_access_matrix as matrix
    import traceback
    failed = 0
    for fn in (matrix.shared_signals.round1_shared_contracts, matrix.shared_signals.round1_signal_contracts,
               matrix.shared_signals.digest_memo_window):
        try:
            fn()
            print('PASS', fn.__name__)
        except Exception:
            failed += 1
            print('FAIL', fn.__name__)
            traceback.print_exc()
    raise SystemExit(bool(failed))

"""Task 5: real tool, triage and router calls in DMs and shared channels.

The oracle is the approved table, not conversation_view. Downstream writes
are mocked only after the tool's lookup/authorization; no model or mail runs.
"""
import json
from contextlib import ExitStack
from unittest.mock import patch

import access_fixture
from harness import check
from test_access_core import TABLE, COLS, KIND, load
from services import access, access_readers, storage, situations, subjects, triage
from services import agent_tools_v2 as tools, agent_router, missions, threads, programs

F, K = 'full', 'keeper'
EXPECT_CHANNEL = {
    'dm': TABLE,
    'family': {k: None for k in ('R1', 'R2', 'R3', 'R4', 'R7', 'R10', 'R11')},
    'mom_aunt': {'R1': K, 'R2': K, 'R3': None, 'R4': None},
}


def focus(fx, context, col):
    if context == 'dm':
        if col == 'house':
            return 'conv:house'
        argyle = storage.ensure_argyle_member()
        channel = storage.get_or_create_dm(argyle['id'], fx.viewers[col]['id'])
    elif context == 'family':
        storage.ensure_family_channel()
        channel = storage.get_family_channel()
    else:
        channel = storage.get_or_create_group(['mom', 'aunt'], 'Mom and Aunt')
    return 'channel:' + channel['id']


def want_view(fx, rkey, col, context, key):
    if context == 'dm':
        return TABLE[rkey][COLS.index(col)]
    kind, row = load(fx, rkey)
    if rkey in EXPECT_CHANNEL[context]:
        return EXPECT_CHANNEL[context][rkey]
    if access.restricted(access.home_project(row)):
        return None
    return F if situations._legacy_channel_visible(kind, row, subjects.channel_humans(key)) else None


def observe(out, fx, rkey):
    from test_access_matrix import observed
    return observed(json.dumps(out, default=str), fx, rkey)


def capture_router(viewer, key, calls=None):
    captured = []
    replies = ([{'message': '', 'tool_calls': calls}] if calls else [])
    def fake(prompt, tools_, system_prompt):
        captured.append((prompt or '') + '\n' + (system_prompt or ''))
        return replies.pop(0) if replies else {'message': 'ok', 'tool_calls': []}
    with patch.object(agent_router, 'call_gemma_with_fallback', side_effect=fake):
        out = agent_router.process_agent_request('What is next?', source='family', acting_member=viewer, focus_key=key)
    check(captured, 'router must actually reach the model boundary')
    return '\n'.join(captured), out


KINDS = {
    '_match_thread': ('thread',), '_match_program': ('program',),
    'list_threads': ('thread',), 'list_programs': ('program',),
    'program_progress': ('program',), 'log_program_session': ('program',),
    'propose_program': ('program',), 'create_thread': ('thread',),
    'add_thread_note': ('thread',), 'draft_thread_message': ('thread',),
    'update_thread_action': ('thread',), 'close_thread': ('thread',),
    'start_mission_for': ('thread', 'mission'), 'launch_mission': ('thread',),
}


def run_one(name, fx, rkey, col, context):
    kind, row = load(fx, rkey)
    if kind not in KINDS.get(name, ('thread', 'mission', 'program')):
        return
    key = focus(fx, context, col)
    viewer = fx.viewers[col]
    want = want_view(fx, rkey, col, context, key)
    kwargs = dict(acting_member=viewer, focus_key=key)
    title, sid = fx.title(rkey), row['id']
    label = f'{name} {context} {rkey} {col}'
    # Tools that operate on a project may not disclose a keeper's home project.
    if name in ('get_project', 'set_project_state', 'set_step_state'):
        project = storage.get_project(row['project_id'])
        humans = subjects.channel_humans(key)
        allowed = access.project_visible(project, viewer) and (context == 'dm' or all(
            access.project_visible(project, h) for h in humans))
        if name == 'get_project':
            out = tools.get_project(project['id'], **kwargs)
            got = observe(out, fx, rkey)
            check(got == (K if allowed and want else None), f'{label}: {got}: {out}')
        else:
            with patch.object(programs, 'pause'):
                out = (tools.set_project_state(project['id'], 'paused', **kwargs) if name == 'set_project_state'
                       else tools.set_step_state(project['id'], 'absent-step', 'done', **kwargs))
            check(fx.secret(rkey) not in json.dumps(out), f'{label}: leaked response')
        return
    if name in ('create_thread', 'propose_program'):
        # Creation has no existing piece to read: probe the supplied home and
        # duplicate-id path, rather than pretending it is a list operation.
        if name == 'create_thread':
            storage.update_thread(sid, {'idem': 'channel-probe'})
            out = tools.create_thread('Fresh title', idem='channel-probe', project_id=row['project_id'], **kwargs)
            if want is None:
                check(out.get('id') != sid, f'{label}: hidden idem result')
        else:
            with patch('services.programs_curate.curate', return_value={'phases': [], 'source': {'origin': 'none'}}):
                out = tools.propose_program('Learn piano', project_id=row['project_id'], **kwargs)
        check(fx.secret(rkey) not in json.dumps(out), f'{label}: creation leaked old words')
        return
    if name in ('update_thread_action', 'close_thread', 'add_thread_note', 'draft_thread_message',
                'log_program_session', 'act_on_situation', 'start_ask', 'mark_ask_sent', 'answer_ask'):
        # Assert that hidden records never reach the downstream effect. Visible
        # writes retain their pre-existing role gates.
        role_ok = viewer.get('role') in ('parent', 'adult') and col != 'pat'
        if name == 'log_program_session':
            role_ok = role_ok or viewer.get('id') == row.get('member_id')
        role_ok = role_ok and col != 'house'
        if name in ('act_on_situation', 'start_ask'):
            role_ok = viewer.get('role') in ('parent', 'adult') and col != 'pat'
        from services import asks
        if name == 'act_on_situation' and kind == 'mission':
            storage.update_mission(sid, {'status': 'running'})
        target, fn = {
            'update_thread_action': (threads, 'advance'), 'close_thread': (threads, 'close'),
            'add_thread_note': (threads, 'note'), 'draft_thread_message': (threads, 'draft_message'),
            'log_program_session': (programs, 'log_session'), 'act_on_situation': (situations, 'act'),
            'start_ask': (asks, 'create'), 'mark_ask_sent': (asks, 'mark_sent'), 'answer_ask': (asks, 'answer'),
        }[name]
        aid = storage.add_ask({'situation_kind': kind, 'situation_id': sid, 'asked_by': 'mom',
                              'to_name': 'Someone', 'what': fx.secret(rkey), 'channel': 'text'})
        with patch.object(target, fn, return_value={'status': 'error', 'message': 'effect'}) as effect:
            if name == 'update_thread_action': out = tools.update_thread_action(title, 'Next', **kwargs)
            elif name == 'close_thread': out = tools.close_thread(title, state='done', **kwargs)
            elif name == 'add_thread_note': out = tools.add_thread_note(title, text='Note', **kwargs)
            elif name == 'draft_thread_message': out = tools.draft_thread_message(title, **kwargs)
            elif name == 'log_program_session': out = tools.log_program_session(title, **kwargs)
            elif name == 'act_on_situation': out = tools.act_on_situation(sid, kind=kind, verb='answer' if kind == 'mission' else 'close', option_id='answer:steer' if kind == 'mission' else 'close:done', **kwargs)
            elif name == 'start_ask': out = tools.start_ask(sid, kind=kind, to_name='Someone', what='Help', channel='text', **kwargs)
            elif name == 'mark_ask_sent': out = tools.mark_ask_sent(aid, **kwargs)
            else: out = tools.answer_ask(aid, 'yes', **kwargs)
        if name in ('mark_ask_sent', 'answer_ask'):
            role_ok = True  # the downstream function owns its actor gate
        expected = bool(want and role_ok)
        target_id = aid if name in ('mark_ask_sent', 'answer_ask') else sid
        called_for_target = effect.called and target_id in effect.call_args.args[:2]
        check(bool(called_for_target) == expected, f'{label}: target effect {called_for_target}, expected {expected}: {out}')
        check(want is not None or observe(out, fx, rkey) is None, f'{label}: hidden title echoed: {out}')
        return
    if name == 'launch_mission':
        with patch.object(missions, 'launch', return_value={'status': 'launched'}) as effect:
            out = tools.launch_mission('Help with the work', thread_title=title, **kwargs)
        if viewer.get('role') in ('parent', 'adult') and col not in ('pat', 'house'):
            check(effect.called, f'{label}: plain fallback must launch')
            origin = effect.call_args.kwargs.get('origin_ref')
            check(origin == sid if want else origin != sid, f'{label}: wrong origin')
        check(want is not None or observe(out, fx, rkey) is None, f'{label}: hidden launch words')
        return
    if name == 'start_mission_for':
        if kind == 'thread':
            mid = storage.add_mission({'goal': 'unique work request', 'status': 'running', 'created_by': 'mom',
                                       'origin_kind': 'thread', 'origin_ref': sid, 'project_id': row['project_id']})
        else:
            tid = fx.ids['R5t']
            storage.update_mission(sid, {'origin_kind': 'thread', 'origin_ref': tid, 'goal': 'unique work request'})
            mid = sid
        with patch.object(missions, 'launch', return_value={'status': 'launched', 'mission_id': 'new'}) as effect:
            out = tools.start_mission_for('unique work request', **kwargs)
        if want is None:
            check(out.get('mission_id') != mid and observe(out, fx, rkey) is None, f'{label}: hidden dedupe {out}')
        return
    if name == 'list_open_findings':
        from services import findings
        with patch.object(findings, 'open_findings', return_value=[{'id': 'f', 'severity': 'decide',
                     'line': title + ' ' + fx.secret(rkey), 'subject_type': kind, 'subject_id': sid}]):
            out = tools.list_open_findings(**kwargs)
        # Tasks 8+10 I2: a keeper keeps a neutral finding, without source words.
        if want == K and kind in ('thread', 'mission'):
            message = out.get('message', '')
            check(message in ('Needs a decision: ' + title,
                              'Needs a decision: Argyle needs a parent on ' + title),
                  f'{label}: keeper finding must be neutral: {out}')
            check(all(words not in json.dumps(out, default=str)
                      for words in (fx.secret(rkey), 'next_action', 'question')),
                  f'{label}: keeper finding reveals source words: {out}')
        want = F if want == F or kind == 'program' and want else K if want == K else None
    elif name == 'find_in_chauffeur':
        out = tools.find_in_chauffeur(title, kind=kind, **kwargs)
        # Candidate cards carry metadata; keeper context must never carry words.
        want = K if want else None
    elif name == 'process_agent_request':
        triage.set_focus(key, kind, sid, 'STALE SECRET TITLE')
        out, _ = capture_router(viewer, key)
        check('STALE SECRET TITLE' not in out, f'{label}: cached focus title used')
        if want == K:
            check('ABOUT:' not in out, f'{label}: keeper ABOUT')
        want = K if want else None  # FOCUS may contain a safe next-step label
    elif name == 'get_focus':
        triage.set_focus(key, kind, sid, title)
        out = triage.get_focus(key, viewer=viewer)
        want = K if want else None
    elif name == 'focus_live_asks':
        storage.add_ask({'situation_kind': kind, 'situation_id': sid, 'asked_by': 'mom',
                         'to_name': 'Someone', 'what': fx.secret(rkey), 'channel': 'text', 'state': 'sent'})
        triage.set_focus(key, kind, sid, title)
        out = triage.focus_live_asks(key, viewer)
        want = F if want == F else None
    elif name in ('next_for', 'next_situation'):
        # Filter AFTER real enumeration/projection. Mocking get_threads also
        # changes get_thread's subject lookup and would erase nested subjects.
        rank = triage.triage_rank
        with patch.object(triage, 'triage_rank', side_effect=lambda rows: rank([
                s for s in rows if s['kind'] == kind and s['id'] == sid])):
            out = triage.next_for(viewer, key) if name == 'next_for' else tools.next_situation(**kwargs)
    elif name in ('_match_thread', '_match_program'):
        out = getattr(tools, name)(title, viewer, key)
        # Matchers return raw rows only to internal callers, after gating.
        want = F if want else None
    elif name == 'list_threads': out = tools.list_threads(**kwargs)
    elif name == 'list_programs':
        # Existing list/progress reports phase words, not starting_point.
        storage.update_program(sid, {'phases': [{'name': fx.secret(rkey), 'units': []}]})
        out = tools.list_programs(**kwargs)
    elif name == 'program_progress':
        storage.update_program(sid, {'phases': [{'name': fx.secret(rkey), 'units': []}]})
        out = tools.program_progress(title, **kwargs)
    elif name == 'list_situations': out = tools.list_situations(kinds=kind, limit=30, **kwargs)
    elif name == '_conversation_situations':
        out = tools._conversation_situations(viewer, key, kinds=(kind,))
    elif name == 'explain_situation': out = tools.explain_situation(sid, kind=kind, **kwargs)
    else:
        raise AssertionError('Unimplemented probe: ' + name)
    got = observe(out, fx, rkey)
    if kind == 'program' and want == K and name not in ('find_in_chauffeur', 'get_focus', 'process_agent_request'):
        want = F
    if name in ('find_in_chauffeur', 'process_agent_request') and got == F and want == K:
        check(want_view(fx, rkey, col, context, key) == F or kind == 'program', f'{label}: keeper words')
        got = K
    check(got == want, f'{label}: want {want}, got {got}: {out}')


def register(probe):
    for rid, cls, kinds, _ in access_readers.READERS:
        if cls != '4.3-channel':
            continue
        name = rid[-1].rsplit('.', 1)[-1]
        def run(fx, rkey, col, name=name):
            for context in ('dm', 'family', 'mom_aunt'):
                if context == 'family' and col != 'mom' or context == 'mom_aunt' and col not in ('mom', 'aunt'):
                    continue
                run_one(name, access_fixture.build(), rkey, col, context)
            return 'skip'  # each context has already asserted its own oracle
        probe(rid)(run)


def B1_household_piece_readable_by_engine():
    fx = access_fixture.build()
    check(observe(tools.list_threads(acting_member=access.HOUSE), fx, 'R5t') == F, 'B1: HOUSE household thread')


def B2_channel_program_rule():
    fx = access_fixture.build()
    storage.update_program(fx.ids['R5p'], {'member_id': 'mom'})
    out = tools.list_programs(acting_member=fx.viewers['mom'], focus_key=focus(fx, 'family', 'mom'))
    check(fx.title('R5p') in json.dumps(out), 'B2: family keeps unrestricted program')


def I2_keeper_own_dm():
    fx = access_fixture.build()
    out = tools.list_programs(acting_member=fx.viewers['kid'], focus_key=focus(fx, 'dm', 'kid'))
    check(fx.title('R3') in json.dumps(out), 'I2: Kate sees her own program')
    out = tools.list_threads(acting_member=fx.viewers['aunt'], focus_key=focus(fx, 'dm', 'aunt'))
    check(observe(out, fx, 'R1') == K, 'I2: Aunt keeper thread')


def M5_unmatched_launch_falls_back():
    fx = access_fixture.build()
    out = tools.launch_mission('Help with an errand', thread_title=fx.title('R1'),
                               acting_member=fx.viewers['dad'], focus_key=focus(fx, 'dm', 'dad'))
    mid = out.get('mission_id')
    check(mid, f'M5: must launch: {out}')
    row = storage.get_mission(mid)
    check(not row.get('origin_ref'), 'M5: plain mission, no hidden thread')
    check(fx.title('R1') not in json.dumps([out, row, storage.get_mission_steps(mid)]), 'M5: no seeded hidden title')


def dm_speaker_record_view():
    """Controller ruling: only the channel's sole human gets their own view."""
    fx = access_fixture.build()
    key = focus(fx, 'dm', 'aunt')
    humans = subjects.channel_humans(key)
    check(humans and [h['id'] for h in humans] == ['aunt'], 'DM humans must remain explicit')
    kind, row = load(fx, 'R1')
    check(access.conversation_view(kind, row, fx.viewers['aunt'], key) == K, 'own DM keeper')
    check(access.conversation_view(kind, row, fx.viewers['mom'], key) == K,
          'another speaker must not bypass the channel recipient projection')
    check(access.conversation_view(kind, row, access.HOUSE, key) == K, 'id-less caller uses channel projection')
    for rkey in ('R6', 'R7'):
        kind, row = load(fx, rkey)
        key = focus(fx, 'dm', 'kid')
        check(access.conversation_view(kind, row, fx.viewers['kid'], key) == (F if rkey == 'R6' else K),
              'own DM uses record_view for subject-bound rows')


def keeper_draft_prompt():
    fx = access_fixture.build()
    key = focus(fx, 'mom_aunt', 'mom')
    prompts = []
    def draft(pool, api_key, system, prompt, **kwargs):
        prompts.append(prompt)
        return {'subject': 'Follow up', 'body': 'Please call.'}
    with patch.object(threads, '_pool_call', side_effect=draft):
        for col in ('mom', 'aunt'):
            out = tools.draft_thread_message(fx.title('R1'), acting_member=fx.viewers[col], focus_key=key)
            check(out['status'] == 'success', f'keeper may draft: {out}')
    check(len(prompts) == 2 and all(fx.secret('R1') not in p for p in prompts),
          'draft model must receive the common keeper projection')


def router_dispatch_context():
    fx = access_fixture.build()
    # R13 otherwise also matches the fragment 'Title R1'. This case exercises
    # an unmatched launch, not a legitimate match to a different visible row.
    storage.update_thread(fx.ids['R13'], {'title': 'Unrelated wrapper'})
    with patch.object(missions, 'launch', return_value={'status': 'launched', 'mission_id': 'new'}) as launch:
        capture_router(fx.viewers['mom'], focus(fx, 'family', 'mom'), [
            {'name': 'launch_mission', 'arguments': {'goal': 'Help', 'thread_title': fx.title('R1')}}])
    check(launch.called and launch.call_args.kwargs.get('origin_ref') is None,
          f'router must pass channel focus to launch title matching: {launch.call_args}')
    for name, args in (('list_threads', {}), ('list_programs', {}), ('list_situations', {}),
                       ('get_project', {'project_id': fx.projects['household']['id']})):
        prompt, out = capture_router(access.HOUSE, 'conv:panel', [{'name': name, 'arguments': args}])
        check(observe([prompt, out], fx, 'R1') is None and observe([prompt, out], fx, 'R4') is None,
              f'{name}: identity-free dispatch must not borrow parent identity')
        check('error' not in json.dumps(out).lower(), f'{name}: identity-free read must execute: {out}')
        visible_key = 'R5p' if name == 'list_programs' else 'R5t'
        check(observe([prompt, out], fx, visible_key) is not None,
              f'{name}: the actual tool result must include the household piece')


def panel_write_dispatch():
    """Real router/tool writes cannot borrow Mom's private records or identity."""
    from services import projects, asks
    cases = ['act_on_situation', 'start_ask', 'mark_ask_sent', 'answer_ask',
             'start_mission_for', 'start_project', 'add_project_step', 'add_to_project',
             'set_project_state', 'set_step_state']
    errors = []
    for name in cases:
        fx = access_fixture.build()
        private = fx.projects['mom_private']['id']
        step = projects.add_step(private, {'title': 'Private step'}, fx.viewers['mom'])['step']
        aid = storage.add_ask({'situation_kind': 'thread', 'situation_id': fx.ids['R1'],
                              'asked_by': 'mom', 'to_name': 'Someone', 'what': 'Please help',
                              'channel': 'text'})
        triage.set_focus('conv:panel', 'thread', fx.ids['R1'], fx.title('R1'))
        args = {
            'act_on_situation': {'ref': 'Title R', 'verb': 'close'},
            'start_ask': {'ref': fx.ids['R1'], 'to_name': 'Someone', 'what': 'Please help', 'channel': 'text'},
            'mark_ask_sent': {'ask_id': aid}, 'answer_ask': {'ask_id': aid, 'answer': 'yes'},
            'start_mission_for': {'goal': 'Find available appointments'},
            'start_project': {'goal': 'Learn a new language'},
            'add_project_step': {'project_id': private, 'title': 'New step'},
            'add_to_project': {'project_id': private, 'kind': 'list', 'id': 'absent'},
            'set_project_state': {'project_id': private, 'state': 'paused'},
            'set_step_state': {'project_id': private, 'step_id': step['id'], 'state': 'done'},
        }[name]
        def snapshot():
            return [load(fx, r)[1] for r in ('R1', 'R2', 'R4')] + [
                storage.get_mission_steps(fx.ids['R2']), storage.get_project(private),
                storage.get_ask(aid)]
        before = snapshot()
        with patch.object(missions, 'launch', return_value={'status': 'launched', 'mission_id': 'new'}) as launch, \
             patch.object(asks, 'draft', return_value={'subject': '', 'body': 'Please help', 'source': 'template'}):
            prompt, out = capture_router(access.HOUSE, 'conv:panel', [{'name': name, 'arguments': args}])
        if any(observe([prompt, out], fx, r) is not None for r in ('R1', 'R2', 'R4')):
            errors.append(f'{name}: hidden title in router output')
        if snapshot() != before:
            errors.append(f'{name}: changed a hidden record, project, or ask')
        if launch.called and launch.call_args.kwargs.get('origin_ref') in (fx.ids['R1'], fx.ids['R4']):
            errors.append(f'{name}: launched on a hidden thread')
        if name == 'start_project' and launch.called:
            project = storage.get_project(launch.call_args.kwargs['project_id'])
            check(project['owner_member_id'] == situations.parent_of_record()['id']
                  and project['audience'] == 'household', 'panel project follows the Follow-up B ruling')
    # Direct-id writes must also be gated, and a household write still works.
    for rkey in ('R1', 'R2', 'R4', 'R5t'):
        fx = access_fixture.build()
        kind, row = load(fx, rkey)
        capture_router(access.HOUSE, 'conv:panel', [{'name': 'act_on_situation', 'arguments': {
            'ref': row['id'], 'kind': kind, 'verb': 'close',
            'option_id': 'close:done' if kind == 'thread' else 'close:dropped'}}])
        after = load(fx, rkey)[1]
        if rkey == 'R5t':
            check(after['state'] == 'done', 'panel must retain household writes')
        elif after != row:
            errors.append(f'act_on_situation: direct-id write landed on {rkey}')
    check(not errors, '\n'.join(errors))


def panel_sensitive_insights():
    """An identity-free writer is a room, even when dispatch sets spoken=False."""
    from services import asks
    fx = access_fixture.build()
    storage.mind_insights_table.truncate()
    ids = [storage.add_mind_insight({'slug': slug, 'line': title, 'category': 'c',
                                   'approach': 'Ask someone', 'identity': 'c:' + slug,
                                   'sensitivity': 'sensitive'})
           for slug, title in (('s', 'SECRET thing'), ('t', 'SECRET other'))]
    normal = storage.add_mind_insight({'slug': 'normal', 'line': 'Household reminder',
                                      'category': 'c', 'sensitivity': 'normal'})
    titles = [storage.get_mind_insight(sid)['line'] for sid in ids]
    errors = []
    for viewer in (access.HOUSE, access.HOUSE_PARENT, {'role': 'parent'}):
        out = tools.list_situations(kinds='insight', acting_member=viewer, focus_key='conv:panel')
        if any(title in json.dumps(out) for title in titles):
            errors.append(f'room list exposed sensitive titles: {viewer}')
        check('Household reminder' in json.dumps(out), 'room must retain normal insights')

    def snapshot():
        return [storage.get_mind_insight(sid) for sid in ids], storage.asks_table.all()

    calls = [('list_situations', {'kinds': 'insight'}),
             ('explain_situation', {'ref': ids[0], 'kind': 'insight'})]
    for ref in ('SECRET', titles[0], ids[0], ''):
        calls.extend([
            ('act_on_situation', {'ref': ref, 'kind': 'insight', 'verb': 'dismiss'}),
            ('start_ask', {'ref': ref, 'kind': 'insight', 'to_name': 'Mom',
                           'what': 'Please help', 'channel': 'text'}),
        ])
    calls.append(('start_mission_for', {'goal': 'Find available appointments'}))
    for name, args in calls:
        before = snapshot()
        triage.set_focus('conv:panel', 'insight', ids[0], titles[0])
        with patch.object(asks, 'draft', return_value={'subject': '', 'body': 'Please help', 'source': 'template'}), \
             patch.object(missions, 'launch', return_value={'status': 'launched', 'mission_id': 'new'}):
            prompt, out = capture_router(access.HOUSE, 'conv:panel', [{'name': name, 'arguments': args}])
        # The model's own arguments are echoed into its next prompt. They
        # are inputs, not disclosure; still check every tool result and FOCUS.
        prompt = prompt.replace(f'Tool Call: {name}({json.dumps(args)})', '')
        if any(title in json.dumps([prompt, out]) for title in titles):
            errors.append(f'{name} ({args.get("ref", "focus")}): sensitive title in router output')
        if snapshot() != before:
            errors.append(f'{name} ({args.get("ref", "focus")}): changed a sensitive insight or ask')
    check(not errors, '\n'.join(errors))

    # The room rule belongs to Argyle, not the engine's parent-only reads.
    check(situations.view('insight', ids[0], access.HOUSE_PARENT)['title'] == titles[0],
          'internal parent-only situation reads must retain sensitive insight contents')
    out = tools.explain_situation(ids[0], kind='insight', acting_member=fx.viewers['mom'])
    check(out['status'] == 'success' and titles[0] in out['message'], 'a parent still reads sensitive insights')
    out = tools.act_on_situation(ids[0], kind='insight', verb='dismiss', acting_member=fx.viewers['mom'])
    check(out['status'] == 'success' and storage.get_mind_insight(ids[0])['state'] == 'retired',
          'a parent still dismisses sensitive insights')
    capture_router(access.HOUSE, 'conv:panel', [{'name': 'act_on_situation', 'arguments': {
        'ref': normal, 'kind': 'insight', 'verb': 'dismiss'}}])
    check(storage.get_mind_insight(normal)['state'] == 'retired', 'panel retains normal insight writes')


def conversation_mission_history():
    """Apply the terminal cap after visibility, before rendering; keep live rows."""
    fx = access_fixture.build()
    hidden = storage.get_mission(fx.ids['R2'])
    visible = storage.get_mission(fx.ids['R9b'])
    rows = [dict(hidden, status='done'), dict(visible, id='dropped', status='dropped'),
            dict(visible, id='done', status='done'), dict(visible, id='blocked', status='blocked'),
            dict(visible, id='older', status='done'), dict(visible, id='live', status='running')]
    rendered = []
    def render(kind, row, *args):
        rendered.append(row['id'])
        return {'id': row['id'], 'group': 'now'}
    with patch.object(storage, 'get_missions', return_value=rows), \
         patch.object(situations, 'MISSION_HISTORY_CAP', 2), \
         patch.object(tools, '_render_at', side_effect=render), \
         patch.object(situations, 'rank', side_effect=lambda rows: rows):
        tools._conversation_situations(access.HOUSE, 'conv:panel', kinds=('mission',))
    check(rendered == ['done', 'blocked', 'live'], f'mission history policy: {rendered}')


def panel_start_project():
    """A panel can start household work without reading the parent's private work."""
    from services import projects
    fx = access_fixture.build()
    goal = 'Repair the garage roof'
    private = fx.projects['mom_private']
    storage.update_project(private['id'], {'title': 'SECRET garage project', 'goal': goal})
    for focused_kind, focused_id in (('project', private['id']), ('thread', fx.ids['R1'])):
        triage.set_focus('conv:panel', focused_kind, focused_id, 'SECRET panel focus')
        before = {p['id'] for p in storage.get_projects()}
        prompt, out = capture_router(access.HOUSE, 'conv:panel', [{'name': 'start_project', 'arguments': {
            'goal': goal, 'subject_kind': 'thread', 'subject_id': fx.ids['R1'],
            'for_member_name': 'Kate'}}])
        new = [p for p in storage.get_projects() if p['id'] not in before]
        check(len(new) == 1, f'panel creates a project instead of deduping or continuing private work: {out}')
        project = new[0]
        check(project['owner_member_id'] == situations.parent_of_record()['id']
              and project['audience'] == 'household', f'panel ownership and audience: {project}')
        planning = projects._work_missions(project)
        check(len(planning) == 1 and missions.subject_of(planning[0])[:2] == ('project', project['id']),
              'panel planning binds only its new household project, never the private subject')
        check(not any(p['kind'] == 'thread' and p['id'] == fx.ids['R1'] for p in project['pieces']),
              'no private subject attached as a piece')
        check('SECRET' not in prompt + json.dumps(out) and fx.title('R1') not in json.dumps(out),
              'private focus, dedupe candidate and subject words stay out of the room')
        # Give the next iteration a different goal so household dedupe cannot mask creation.
        goal = 'Replace the garage door'
        storage.update_project(private['id'], {'goal': goal})


def project_tools_channel_contract():
    """Exercise the registered project rows with no piece-kind matrix cells."""
    fx = access_fixture.build()
    private = fx.projects['mom_private']['id']
    household = fx.projects['household']['id']
    key = focus(fx, 'family', 'mom')
    kwargs = dict(acting_member=fx.viewers['mom'], focus_key=key)
    out = tools.list_projects(**kwargs)
    check('Mom private' not in json.dumps(out) and 'Household' in json.dumps(out), 'project channel list')
    out = tools.add_project_step(private, 'Hidden step', **kwargs)
    check(out['status'] != 'success', 'private project step refused in family')
    out = tools.add_project_step(household, 'Visible step', **kwargs)
    check(out['status'] == 'success', f'household step available: {out}')
    for kind in ('thread', 'mission', 'program'):
        out = tools.add_to_project(household, kind, 'absent', **kwargs)
        check(out['status'] == 'error', 'removed add-existing kinds remain unavailable')
    with patch.object(missions, 'launch', return_value={'status': 'launched', 'mission_id': 'new'}):
        out = tools.start_project('Learn a unique language', acting_member=fx.viewers['mom'],
                                  focus_key=focus(fx, 'dm', 'mom'))
    check(out['status'] == 'success', f'own DM can start a project: {out}')


def finder_filters_before_matching():
    fx = access_fixture.build()
    key = focus(fx, 'family', 'kid')
    out = tools.find_in_chauffeur(fx.title('R5t'), kind='thread', acting_member=fx.viewers['kid'], focus_key=key)
    check(observe(out, fx, 'R5t') is not None, 'legacy shared thread is searchable when a child speaks')
    # A hidden exact match must not crowd out the visible substring match.
    storage.update_thread(fx.ids['R1'], {'title': 'Pest renewal'})
    storage.update_thread(fx.ids['R5t'], {'title': 'Pest renewal follow up'})
    out = tools.find_in_chauffeur('Pest renewal', kind='thread', acting_member=fx.viewers['mom'], focus_key=key)
    check([c['id'] for c in out['candidates']] == [fx.ids['R5t']] and out['context'],
          f'channel filtering precedes winner selection: {out}')


def registry_and_ask_payloads():
    fx = access_fixture.build()
    for name in ('list_threads', 'list_programs', 'list_situations', 'list_projects'):
        out = tools.execute_tool(name, {})
        check(out.get('status') == 'success', f'registry {name}: {out}')
        for rkey in ('R1', 'R2', 'R3', 'R4', 'R7', 'R11'):
            check(observe(out, fx, rkey) is None, f'registry {name}: leaked {rkey}')
    for out in (tools.list_projects(), tools.get_project(fx.projects['household']['id'])):
        check(out['status'] == 'success' and 'Household' in json.dumps(out), 'id-less project reads use HOUSE')
    key = focus(fx, 'mom_aunt', 'mom')
    out = tools.execute_tool('explain_situation', {'ref': fx.ids['R2'], 'kind': 'mission'},
                             actor=fx.viewers['mom'], focus_key=key)
    check(observe(out, fx, 'R2') == K, f'registry must forward actor and focus: {out}')
    aid = storage.add_ask({'situation_kind': 'thread', 'situation_id': fx.ids['R1'], 'asked_by': 'mom',
                          'to_name': fx.secret('R1'), 'what': fx.secret('R1'), 'channel': 'text'})
    out = tools.mark_ask_sent(aid, acting_member=fx.viewers['mom'], focus_key=key)
    check(out['status'] == 'success' and fx.secret('R1') not in json.dumps(out), 'keeper sent response')
    out = tools.answer_ask(aid, 'yes', acting_member=fx.viewers['mom'], focus_key=key)
    check(out['status'] == 'success' and fx.secret('R1') not in json.dumps(out), 'keeper answer response')
    for name, extra in [('add_thread_note', {'text': 'Note'}), ('draft_thread_message', {})]:
        out = getattr(tools, name)(thread_id=fx.ids['R1'], acting_member=fx.viewers['dad'],
                                  focus_key=focus(fx, 'dm', 'dad'), **extra)
        check(out['status'] == 'error' and observe(out, fx, 'R1') is None, f'{name} hidden id')
    from services import asks
    with patch.object(tools, '_post_chat_message', return_value={'id': 'sent-test'}) as post, \
         patch.object(asks, 'draft', return_value={'subject': '', 'body': 'Please help', 'source': 'template'}):
        out = tools.execute_tool('start_ask', {'ref': fx.ids['R5t'], 'kind': 'thread',
                                 'to_name': 'Mom', 'what': 'Please help', 'channel': 'chauffeur'})
    check(out['status'] == 'success' and post.called, f'HOUSE_PARENT registry ask: {out}')
    channel, sender = post.call_args.args[:2]
    check(sender['id'] == 'argyle' and set(channel['member_ids']) == {'argyle', 'mom'},
          'an identity-free registry ask posts as Argyle, never an invented parent')


def panel_household_ask_and_mission_writes():
    """Production HOUSE actor reaches the real ask lifecycle and launch."""
    fx = access_fixture.build()
    key = 'conv:panel'
    tid = fx.ids['R5t']
    before = {a['id'] for a in storage.asks_table.all()}
    from services import asks
    with patch.object(asks, '_pool_call', return_value={}):  # external drafting model only
        capture_router(access.HOUSE, key, [{'name': 'start_ask', 'arguments': {
            'ref': tid, 'kind': 'thread', 'to_name': 'Mom', 'what': 'Please call the shop', 'channel': 'text'}}])
    created = [a for a in storage.asks_table.all() if a['id'] not in before]
    check(len(created) == 1 and created[0]['state'] == 'drafted', 'panel creates real household ask')
    aid = created[0]['id']
    capture_router(access.HOUSE, key, [{'name': 'mark_ask_sent', 'arguments': {'ask_id': aid}}])
    check(storage.get_ask(aid)['state'] == 'sent', 'panel marks it sent')
    capture_router(access.HOUSE, key, [{'name': 'answer_ask', 'arguments': {'ask_id': aid, 'answer': 'no'}}])
    check(storage.get_ask(aid)['state'] == 'no', 'panel reports the answer')
    before = {m['id'] for m in storage.get_missions()}
    triage.set_focus(key, 'thread', tid, fx.title('R5t'))
    capture_router(access.HOUSE, key, [{'name': 'start_mission_for', 'arguments': {
        'goal': 'Find a shop with appointments'}}])
    created = [m for m in storage.get_missions() if m['id'] not in before]
    check(len(created) == 1 and created[0]['origin_ref'] == tid, 'panel launches on real household thread')


def router_insight_identity_and_panel_dismissal():
    fx = access_fixture.build()
    storage.mind_insights_table.truncate()
    sensitive = storage.add_mind_insight({'slug': 'private', 'line': 'Sensitive parent insight',
        'state': 'active', 'sensitivity': 'sensitive'})
    normal = storage.add_mind_insight({'slug': 'normal', 'line': 'Normal household insight',
        'state': 'active', 'sensitivity': 'normal'})
    parent = tools.list_insights(acting_member=fx.viewers['mom'])
    check('Sensitive parent insight' in json.dumps(parent), 'resolved id reaches Mind gate')
    for viewer, allowed in ((fx.viewers['mom'], True), (access.HOUSE, False), (access.HOUSE_PARENT, False)):
        out = tools.execute_tool('list_insights', {}, actor=viewer)
        check(('Sensitive parent insight' in json.dumps(out)) == allowed,
              'registry forwards resolved insight identity without inventing a parent')
    check('Sensitive parent insight' in json.dumps(tools.execute_tool('list_insights', {}, actor=fx.viewers['mom'])),
          'registry forwards the resolved identity too')
    for viewer, key, allowed in ((fx.viewers['mom'], focus(fx, 'dm', 'mom'), True),
                                  (access.HOUSE, 'conv:panel', False),
                                  (access.HOUSE_PARENT, 'conv:panel', False)):
        prompt, out = capture_router(viewer, key, [{'name': 'list_insights', 'arguments': {}}])
        check(('Sensitive parent insight' in prompt + json.dumps(out)) == allowed,
              'router insight sensitivity follows the resolved person')
    capture_router(access.HOUSE, 'conv:panel', [{'name': 'dismiss_insight', 'arguments': {'insight_id': sensitive}}])
    check(storage.get_mind_insight(sensitive)['state'] == 'active', 'panel cannot dismiss sensitive insight')
    capture_router(access.HOUSE, 'conv:panel', [{'name': 'dismiss_insight', 'arguments': {'insight_id': normal}}])
    check(storage.get_mind_insight(normal)['state'] == 'retired', 'panel dismisses normal insight')


def extra_contracts():
    errors = []
    for fn in (B1_household_piece_readable_by_engine, B2_channel_program_rule, I2_keeper_own_dm,
               M5_unmatched_launch_falls_back, dm_speaker_record_view, keeper_draft_prompt,
               router_dispatch_context, project_tools_channel_contract, finder_filters_before_matching,
               registry_and_ask_payloads, panel_write_dispatch, panel_sensitive_insights,
               conversation_mission_history, panel_start_project,
               panel_household_ask_and_mission_writes, router_insight_identity_and_panel_dismissal):
        try:
            fn()
            print('PASS', fn.__name__)
        except Exception as exc:
            errors.append(f'{fn.__name__}: {exc}')
    check(not errors, '\n'.join(errors))


if __name__ == '__main__':
    extra_contracts()

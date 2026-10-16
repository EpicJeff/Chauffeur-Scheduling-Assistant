"""Review follow-up regressions: execute approval, tools, cards and HTTP routes.
Run from chauffeur/: python tests/test_access_followup_a.py
"""
import datetime
import traceback
from unittest.mock import patch

from harness import check
import access_fixture
from access_signed_in import request
from services import access, storage, projects, planned, missions, programs, situations
from services import agent_tools_v2 as tools
import main


def scenario_a1_approval_respects_subject_home():
    for kind, key in [('thread', 'R5t'), ('mission', 'R9b'), ('program', 'R5p'), ('occasion', 'occ-parents')]:
        for native in (False, True):
            fx = access_fixture.build()
            pid = fx.projects['mom_private']['id']
            sid = fx.ids.get(key, key)
            if native and kind in projects.PIECE_HOME_KINDS:
                getattr(storage, 'update_' + kind)(sid, {'project_id': pid})
            mid = fx.ids['R9a']
            storage.update_mission(mid, {'origin_kind': 'manual', 'origin_ref': None, 'subject_kind': kind, 'subject_id': sid,
                'plan': {'rev': 1, 'state': 'proposed', 'stages': [], 'steps': []}})
            # Remove existing native entries to exercise approval's insertion itself.
            storage.update_project(pid, {'pieces': []})
            before = access.KINDS[kind].load(sid) if kind in access.KINDS else None
            out = planned.approve_plan(mid, 1, fx.viewers['mom'])
            check(out['status'] == 'success', str(out))
            linked = any(p['kind'] == kind and p['id'] == sid for p in storage.get_project(pid)['pieces'])
            check(linked == (native or kind not in projects.PIECE_HOME_KINDS),
                  f'{kind} native={native}: inappropriate earlier-subject link={linked}')
            if before:
                check(access.KINDS[kind].load(sid) == before, 'subject home and content unchanged')


def scenario_a2_home_subject_dedupe():
    # Missions are not registered subjects; thread/program are the home-kind
    # subjects accepted by the real front door.
    for kind, key in [('thread', 'R5t'), ('program', 'R5p')]:
        fx = access_fixture.build()
        sid = fx.ids[key]
        out = tools.start_project('Arrange a tutor', acting_member=fx.viewers['mom'], subject_kind=kind, subject_id=sid)
        check(out['status'] == 'success' and out['mission_id'], str(out))
        pid = out['project_id']
        check(not any(p['kind'] == kind and p['id'] == sid for p in storage.get_project(pid)['pieces']),
              'no cross-project home link')
        again = tools.start_project('Please arrange a tutor', acting_member=fx.viewers['mom'], subject_kind=kind, subject_id=sid)
        check(again.get('project_id') == pid and 'already under way' in again.get('message', ''), f'{kind}: {again}')
        check(missions.subject_of(storage.get_mission(out['mission_id']))[:2] == (kind, sid), 'planning retains the named subject')
        # Approval changes the mission subject to its project; dedupe must still work.
        storage.update_mission(out['mission_id'], {'plan': {'rev': 1, 'state': 'proposed', 'stages': [], 'steps': []}})
        check(planned.approve_plan(out['mission_id'], 1, fx.viewers['mom'])['status'] == 'success', 'approved')
        again = tools.start_project('Arrange a tutor', acting_member=fx.viewers['mom'], subject_kind=kind, subject_id=sid)
        check(again.get('project_id') == pid, f'approved subject dedupe: {again}')
        # Native membership is enough, even with no pieces and no planning mission.
        home = access.KINDS[kind].load(sid)['project_id']
        storage.update_project(home, {'goal': 'Practice violin', 'owner_member_id': 'mom', 'pieces': []})
        again = tools.start_project('Practice violin', acting_member=fx.viewers['mom'], subject_kind=kind, subject_id=sid)
        check(again.get('project_id') == home, f'native subject dedupe: {again}')
        other_sid = fx.ids['R4' if kind == 'thread' else 'R3']
        other = tools.start_project('Arrange a tutor', acting_member=fx.viewers['mom'], subject_kind=kind, subject_id=other_sid)
        check(other.get('project_id') != pid and other.get('mission_id'), 'same goal with a different subject stays distinct')


def _ask(fx, recipient):
    return storage.add_ask({'situation_kind': 'thread', 'situation_id': fx.ids['R5t'],
        'asked_by': 'dad', 'to_member_id': recipient, 'to_name': recipient or 'Someone',
        'what': 'Can you help?', 'state': 'sent', 'channel': 'text'})


def scenario_b1_recipient_answers_without_piece_access():
    for col in ('hal', 'kid'):
        for answer in ('yes', 'no'):
            fx = access_fixture.build()
            aid = _ask(fx, col)
            r = request(fx, col, 'POST', f'/api/asks/{aid}/answer', json={'answer': answer})
            check(r.status_code == 200 and r.json()['status'] == 'success', f'{col} {answer}: {r.status_code} {r.text}')
            ask = storage.get_ask(aid)
            check(ask['state'] == answer and ask['answered_by'] == col, 'real answer persisted')
        for suffix, body in [('answer', {'answer': 'yes', 'reported': True}), ('sent', {}), ('withdraw', {})]:
            aid = _ask(fx, col)
            r = request(fx, col, 'POST', f'/api/asks/{aid}/{suffix}', json=body)
            check(r.status_code == 404, f'{suffix} retains gate: {r.status_code} {r.text}')
        aid = _ask(fx, 'mom')
        r = request(fx, col, 'POST', f'/api/asks/{aid}/answer', json={'answer': 'yes'})
        check(r.status_code == 404, 'another recipient retains the piece gate')
        r = request(fx, col, 'POST', f'/api/asks/{aid}/answer', json={'answer': 'yes', 'member_id': 'mom'})
        check(r.status_code == 403, 'body impersonation refused at identity resolution')


def _option_verb(o):
    if o['id'] == 'answer:steer':
        return 'steer'
    if o['id'] == 'close:dropped':
        return 'drop'
    return o['verb']


def scenario_b2_keeper_card_and_actions_agree():
    fx = access_fixture.build()
    mid, aunt = fx.ids['R2'], fx.viewers['aunt']
    storage.update_mission(mid, {'status': 'running'})
    row = situations.load('mission', mid)
    actable = {v for v in ('ack', 'delete', 'steer', 'drop', 'own', 'subject', 'answer', 'approve_plan', 'run_stage')
               if access.record_actable('mission', row, aunt, v)}
    check(actable == {'ack', 'delete', 'steer', 'drop', 'own'}, f'keeper verbs: {actable}')
    available = {_option_verb(o) for o in situations.options_for('mission', row)}
    card = request(fx, 'aunt', 'GET', f'/api/situations/mission/{mid}')
    shown = {_option_verb(o) for o in card.json()['options']}
    check(shown == available & actable == {'steer', 'drop', 'own'}, f'shown={shown}, actable={actable}')
    check(fx.secret('R2') not in card.text, 'no hidden words on keeper card')
    storage.update_mission(mid, {'status': 'waiting_user', 'plan': {'state': 'proposed', 'rev': 1, 'stages': []}})
    storage.add_mission_step(mid, {'kind': 'ask', 'name': 'plan', 'result_json': {'question': fx.secret('R2')}})
    available = {_option_verb(o) for o in situations.options_for('mission', situations.load('mission', mid))}
    card = request(fx, 'aunt', 'GET', f'/api/situations/mission/{mid}')
    shown = {_option_verb(o) for o in card.json()['options']}
    check(shown == available & actable == {'steer', 'drop', 'own'} and fx.secret('R2') not in card.text,
          f'plan keeper card offers exactly permitted options: {shown}')
    for verb, oid in [('own', 'own'), ('close', 'close:dropped')]:
        r = request(fx, 'aunt', 'POST', f'/api/situations/mission/{mid}/act', json={'verb': verb, 'option_id': oid})
        check(r.status_code == 200 and r.json()['status'] == 'success', f'{oid}: {r.status_code} {r.text}')
        if verb == 'own':
            card = request(fx, 'aunt', 'GET', f'/api/situations/mission/{mid}')
            check({_option_verb(o) for o in card.json()['options']} == {'steer', 'drop'}, 'owned card omits refused Handled and redundant own')
    row = storage.get_mission(mid)
    check(row['status'] == 'dropped' and row['sit_owner_member_id'] == 'aunt', 'real own and drop persisted')
    fx = access_fixture.build()
    r = request(fx, 'aunt', 'POST', f"/api/missions/{fx.ids['R2']}/drop", json={})
    check(r.status_code == 200 and storage.get_mission(fx.ids['R2'])['status'] == 'dropped', f'direct drop: {r.text}')


def scenario_b3_mixed_state_is_an_answer_not_steer():
    fx = access_fixture.build()
    mid = fx.ids['R2']
    storage.update_mission(mid, {'plan': {'state': 'approved', 'stages': [
        {'id': 'work', 'kind': 'work', 'state': 'running', 'title': 'Hidden work', 'snapshot': 1}]}})
    # A running work stage adds answer:steer even while a plain question waits.
    check(any(o['id'] == 'answer:steer' for o in situations.options_for('mission', storage.get_mission(mid))), 'mixed state reproduced')
    before = storage.get_mission_steps(mid)
    for path, body in [(f'/api/missions/{mid}/answer', {'text': 'Keep going'}),
                       (f'/api/situations/mission/{mid}/act', {'verb': 'answer', 'option_id': 'answer:steer', 'payload': {'text': 'Keep going'}})]:
        r = request(fx, 'aunt', 'POST', path, json=body)
        check(r.status_code == 404 and storage.get_mission_steps(mid) == before,
              f'keeper cannot answer hidden question: {r.status_code} {r.text}')
    for name in ('plan', 'stage', 'stage_check'):
        storage.add_mission_step(mid, {'kind': 'ask', 'name': name, 'result_json': {}})
        r = request(fx, 'aunt', 'POST', f'/api/missions/{mid}/answer', json={'text': 'Try another way'})
        check(r.status_code == 200 and storage.get_mission_steps(mid)[-1]['name'] == 'user_steer', f'{name}: {r.text}')
    r = request(fx, 'aunt', 'POST', f'/api/situations/mission/{mid}/act',
                json={'verb': 'subject', 'option_id': 'subject', 'payload': {'kind': 'member', 'id': 'mom'}})
    check(r.status_code == 404, 'keeper retarget stays refused')
    storage.add_mission_step(mid, {'kind': 'ask', 'name': 'question', 'result_json': {}})
    r = request(fx, 'mom', 'POST', f'/api/missions/{mid}/answer', json={'text': 'The answer'})
    check(r.status_code == 200 and storage.get_mission_steps(mid)[-1]['name'] == 'user_answer', 'full viewer may still answer')


def scenario_b4_proposal_missing_shape():
    fx = access_fixture.build()
    pid = storage.add_action_proposal({'action_type': 'skip_occurrence', 'payload': {}, 'summary': fx.secret('R2'),
        'status': 'proposed', 'origin_kind': 'mission', 'origin_id': fx.ids['R2']})
    for prop in (pid, 'missing'):
        r = request(fx, 'dad', 'POST', f'/api/action-proposals/{prop}/act', json={'act': 'approve', 'member_id': 'dad'})
        check(r.status_code == 200 and r.json() == {'status': 'error', 'message': 'That action is no longer available.'},
              f'missing shape: {r.status_code} {r.text}')
    check(storage.get_action_proposal(pid)['status'] == 'proposed', 'hidden proposal unchanged')


def scenario_b5_internal_due_asks_remain_raw():
    fx = access_fixture.build()
    pid = fx.ids['R3']
    pc = storage.add_protected_commitment({'id': 'followup-practice', 'member_id': 'kid', 'days_of_week': [3], 'time_start': '17:00', 'time_end': '17:20'})
    storage.update_program(pid, {'emissions': {'commitment_ids': [pc]}})
    row, now = storage.get_program(pid), datetime.datetime(2026, 10, 16, 12)
    with patch('services.family_digest.in_member_quiet_hours', return_value=False):
        raw = programs.due_asks_for(row, now)
        check(raw and any(a['program']['id'] == pid for a in programs.due_session_asks(now)), 'internal callers retain private program asks')
        check(programs.due_asks_for(row, now, viewer=access.HOUSE) == [], 'explicit HOUSE remains filtered')
        check(programs.due_asks_for(row, now, viewer=fx.viewers['aunt']) == [], 'explicit hidden viewer filtered')
        check(programs.due_asks_for(row, now, viewer=fx.viewers['kid']) == raw, 'owner keeps the ask')


def scenario_b6_identity_free_project_writes_have_no_parent():
    fx = access_fixture.build()
    pid = fx.projects['mom_private']['id']
    from fastapi import HTTPException
    for fn, args in [(main.project_plan, (pid,)), (main.project_step_cancel, (pid, 'missing', {'outcome': 'stop'})),
                     (main.project_step_hold, (pid, 'missing', {}))]:
        try:
            fn(*args, request=None)
        except HTTPException as exc:
            check(exc.status_code == 404, f'{fn.__name__}: {exc.status_code}')
        else:
            raise AssertionError(f'{fn.__name__} used parent stand-in')


SCENARIOS = [v for k, v in list(globals().items()) if k.startswith('scenario_')]
if __name__ == '__main__':
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print('PASS', fn.__name__, flush=True)
        except Exception:
            failed += 1
            print('FAIL', fn.__name__, flush=True)
            traceback.print_exc()
    raise SystemExit(bool(failed))

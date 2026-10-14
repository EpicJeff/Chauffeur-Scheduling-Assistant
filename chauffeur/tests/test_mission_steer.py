"""Steering a mission that is in progress (2026-10-14: "it found a local
company but I want the official manufacturer service").

Rules pinned here:

  * `missions.answer(mission_id, text, actor)` is the ONE door for free text
    into a mission: a pending question gets `user_answer` and the mission
    runs on (as before); a mission that is running, browsing or waiting to
    retry gets `user_steer` and keeps its status; a tap-only ask (release,
    submit, verify) still refuses free text; an ended mission refuses;
  * a live browse stops at its next turn when a steer lands: the runner is
    handed `should_stop`, the steer is flagged in app_state while the mission
    is `browsing`, the fake runner returns outcome `steered` and the mission
    goes back to the planner (`running`), the flag consumed;
  * the planner's next prompt LEADS with the steer ("THE PERSON SAID,
    MID-MISSION"), above the transcript, until a real step follows it;
  * the thread and mission cards offer `answer` ("Tell it something") while
    the mission is live, not only while it waits, and `situations.act` routes
    it through `missions.answer`; the DM card is NOT drawn for a steer option
    (only a pending ask makes a card);
  * the Missions page endpoint takes the same door.

Run from chauffeur/:  python tests/test_mission_steer.py
"""
import inspect
from datetime import date

from harness import check  # noqa: F401
from services import storage, missions, situations

MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}
KID = {'id': 'kid', 'name': 'Kate', 'role': 'child'}
SENT = []


def _reset():
    for t in (storage.missions_table, storage.mission_steps_table, storage.members_table, storage.app_state_table,
              storage.chat_channels_table, storage.chat_messages_table, storage.threads_table):
        t.truncate()
    storage.add_member(dict(MOM))
    storage.add_member(dict(KID))
    storage.get_settings = lambda: {'missions_enabled': True, 'llm_gemini_paid_api_key': 'paid', 'llm_gemini_api_key': 'k',
                                    'contact_first_name': 'Jeff', 'contact_email': 'ffejnosliw@gmail.com', 'contact_zip': '27519',
                                    'missions_submit_enabled': True}
    storage.set_app_state(f"mission_calls:{date.today().isoformat()}", {})
    situations.REFRESH_DELAY_S = 0
    situations._pool_call = lambda *a, **k: {}
    SENT.clear()
    missions._post = lambda dm, argyle, body, card=None: SENT.append(body) or {'id': 'm'}
    missions._browse_async = False


def _report(outcome, **kw):
    base = {'outcome': outcome, 'text': kw.pop('text', outcome), 'learned': {}, 'stopped_at': 'https://sears.com/repair',
            'wanted_fields': [], 'turns': 3, 'tokens_in': 100, 'tokens_out': 10, 'seconds': 5.0, 'screenshots': [], 'filled': {}}
    return {**base, **kw}


def _mission(status='running'):
    mid = storage.add_mission({'goal': 'schedule service for the microwave', 'origin_kind': 'manual', 'created_by': 'mom', 'tier': 'mission'})
    if status != 'running':
        storage.update_mission(mid, {'status': status})
    return mid


def _steps(mid, name=None):
    rows = storage.get_mission_steps(mid)
    return [s for s in rows if s.get('name') == name] if name else rows


def scenario_a_running_mission_takes_a_steer_and_keeps_running():
    _reset()
    mid = _mission('running')
    res = missions.answer(mid, 'use the official manufacturer service, not a local company', MOM)
    check(res['status'] == 'success', f"a parent steers a running mission: {res}")
    steer = _steps(mid, 'user_steer')
    check(len(steer) == 1 and steer[0]['kind'] == 'note' and 'manufacturer' in steer[0]['result_json']['text'], f"the steer is on the transcript: {steer}")
    check(storage.get_mission(mid)['status'] == 'running', "status untouched")
    check(not _steps(mid, 'user_answer'), "a steer is not an answer to a question")
    check(not storage.get_app_state(f'mission_steer:{mid}'), "no runner flag when nothing is browsing")
    # The planner's next prompt leads with it.
    prompt = missions._user_prompt(storage.get_mission(mid))
    head = prompt.split('TRANSCRIPT SO FAR')[0]
    check('MID-MISSION' in head and 'manufacturer' in head, f"the steer leads the prompt, above the transcript:\n{prompt[:400]}")


def scenario_a_pending_question_still_gets_an_answer():
    _reset()
    mid = _mission('running')
    missions._llm = lambda m, s, u, st: {'action': 'ask_user', 'question': 'Which brand is the microwave?'}
    missions.step(storage.get_mission(mid))
    check(storage.get_mission(mid)['status'] == 'waiting_user', "waiting on the question")
    res = missions.answer(mid, 'Samsung', MOM)
    check(res['status'] == 'success' and storage.get_mission(mid)['status'] == 'running', f"the answer runs it on: {res}")
    check(_steps(mid, 'user_answer') and not _steps(mid, 'user_steer'), "a question's answer is user_answer, as before")


def scenario_tap_only_asks_and_ended_missions_refuse_free_text():
    _reset()
    mid = _mission('running')
    missions._browse = lambda **kw: _report('needs_release', wanted_fields=['first_name', 'email'])
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'sears.com'}
    missions.step(storage.get_mission(mid))
    check(missions.tap_only_ask_pending(mid), "a release is pending")
    res = missions.answer(mid, 'use the manufacturer', MOM)
    check(res['status'] == 'error' and 'buttons' in res['message'], f"a tap-only ask refuses words: {res}")
    check(not _steps(mid, 'user_steer') and not _steps(mid, 'user_answer'), "nothing appended")
    done = _mission('done')
    res = missions.answer(done, 'anything', MOM)
    check(res['status'] == 'error', f"an ended mission cannot hear: {res}")
    res = missions.answer(_mission('running'), 'anything', KID)
    check(res['status'] in ('refused', 'error'), f"a child cannot steer: {res}")


def scenario_a_browse_stops_at_its_next_turn_when_steered():
    _reset()
    mid = _mission('running')
    seen = {}

    def fake_runner(**kw):
        # The runner is handed should_stop and asks it between turns.
        check(callable(kw.get('should_stop')), f"the runner gets should_stop: {list(kw)}")
        seen['before'] = kw['should_stop']()
        # The person steers while the browse is on turn 1.
        res = missions.answer(mid, 'wrong company: use the official manufacturer', MOM)
        check(res['status'] == 'success', f"steer during a browse: {res}")
        why = kw['should_stop']()
        seen['why'] = why
        check(why and 'manufacturer' in why, f"turn 2 sees the steer: {why}")
        check(not kw['should_stop'](), "the flag is consumed once read")
        return _report('steered', text=why)

    missions._browse = fake_runner
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'find a repair slot', 'site': 'sears.com'}
    row = missions.step(storage.get_mission(mid))
    check(seen.get('before') is None, "no steer before anyone said anything")
    b = [s for s in storage.get_mission_steps(mid) if s['kind'] == 'browse'][0]
    check(b['result_json']['outcome'] == 'steered', f"the browse step records the stop: {b['result_json']['outcome']}")
    check(row['status'] == 'running', f"back to the planner, not waiting: {row['status']}")
    check(not storage.get_app_state(f'mission_steer:{mid}'), "flag gone")
    prompt = missions._user_prompt(storage.get_mission(mid))
    check('MID-MISSION' in prompt.split('TRANSCRIPT SO FAR')[0], "the planner's next prompt leads with the steer")
    # Once a real step follows, the header stops repeating it.
    storage.add_mission_step(mid, {'kind': 'tool', 'name': 'search_places', 'args_json': {}, 'result_json': {}})
    prompt = missions._user_prompt(storage.get_mission(mid))
    check('MID-MISSION' not in prompt.split('TRANSCRIPT SO FAR')[0], "acted on, the steer lives in the transcript only")


def scenario_the_real_runner_accepts_should_stop():
    from services import browse
    params = inspect.signature(browse.run).parameters
    check('should_stop' in params, f"browse.run takes should_stop: {list(params)}")


def scenario_cards_offer_tell_it_while_live_and_act_routes_it():
    _reset()
    mid = _mission('running')
    opts = situations.options_for('mission', situations.load('mission', mid))
    tell = [o for o in opts if o['verb'] == 'answer']
    check(len(tell) == 1 and tell[0]['payload'].get('ask') == 'steer' and tell[0]['id'] == 'answer:steer', f"a live mission offers answer as a steer: {opts}")
    check(missions.ask_card(storage.get_mission(mid)) is None, "a steer option never makes a DM card")
    res = situations.act('mission', mid, 'answer', option_id=tell[0]['id'], payload={'text': 'the manufacturer, please'}, actor=MOM)
    check(res['status'] == 'success' and _steps(mid, 'user_steer'), f"act routes through missions.answer: {res}")
    # The thread card forwards it too.
    tid = storage.add_thread({'title': 'Microwave repair', 'kind': 'vendor', 'state': 'open', 'owner_member_id': 'mom', 'created_by': 'mom'})
    storage.update_mission(mid, {'origin_kind': 'thread', 'origin_ref': tid})
    topts = situations.options_for('thread', situations.load('thread', tid))
    fwd = [o for o in topts if o['id'] == f'answer:mission:{mid}:steer']
    check(fwd, f"the thread card carries the steer option: {[o['id'] for o in topts]}")
    check(topts[0]['id'] != fwd[0]['id'], f"a steer never leads the thread card (a question would): {[o['id'] for o in topts]}")
    from services import triage
    tview = situations.view('thread', tid, MOM)
    check(triage.tier(tview) != 0, f"a running mission's thread is not 'waiting on the person': tier {triage.tier(tview)} lead {tview.get('next_step')}")
    res = situations.act('thread', tid, 'answer', option_id=fwd[0]['id'], payload={'text': 'and only authorised techs'}, actor=MOM)
    check(res['status'] == 'success' and len(_steps(mid, 'user_steer')) == 2, f"through the thread: {res}")
    # Browsing: the option stays and the flag is raised for the runner.
    storage.update_mission(mid, {'status': 'browsing'})
    opts = situations.options_for('mission', situations.load('mission', mid))
    check(any(o['verb'] == 'answer' for o in opts), "offered while browsing")
    res = situations.act('mission', mid, 'answer', option_id='answer:steer', payload={'text': 'stop, wrong site'}, actor=MOM)
    check(res['status'] == 'success' and (storage.get_app_state(f'mission_steer:{mid}') or {}).get('text') == 'stop, wrong site',
          f"a steer during a browse raises the runner flag: {res} {storage.get_app_state(f'mission_steer:{mid}')}")


def scenario_the_missions_page_endpoint_steers_too():
    _reset()
    import main
    from services import auth as _auth
    from types import SimpleNamespace
    _auth.acting_member = lambda h, q, claimed=None: {'id': 'mom'}
    _auth.impersonation_refused = lambda acting: False
    _auth.identify = lambda h, q: {'tier': _auth.MEMBER, 'member': None}
    mid = _mission('running')
    req = SimpleNamespace(headers={}, query_params={'member_id': 'mom'})
    res = main.missions_answer(mid, body={'text': 'use the manufacturer', 'member_id': 'mom'}, request=req)
    check(res['status'] == 'success' and _steps(mid, 'user_steer'), f"the page's box steers a running mission: {res}")


SCENARIOS = [
    scenario_a_running_mission_takes_a_steer_and_keeps_running,
    scenario_a_pending_question_still_gets_an_answer,
    scenario_tap_only_asks_and_ended_missions_refuse_free_text,
    scenario_a_browse_stops_at_its_next_turn_when_steered,
    scenario_the_real_runner_accepts_should_stop,
    scenario_cards_offer_tell_it_while_live_and_act_routes_it,
    scenario_the_missions_page_endpoint_steers_too,
]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)

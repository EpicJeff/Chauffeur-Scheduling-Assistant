"""browse as a mission action: the report is a step; outcomes map to running,
a release ask, or a hand-off ask; the tick reclaims a lost browse; the
person is told. A fake runner; no browser. Spec 2026-10-10 §2."""
import time
from datetime import date

from harness import check  # noqa: F401
from services import storage, missions, situations

SENT = []


def _reset():
    for t in (storage.missions_table, storage.mission_steps_table, storage.members_table, storage.app_state_table,
              storage.chat_channels_table, storage.chat_messages_table, storage.threads_table):
        t.truncate()
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.get_settings = lambda: {'missions_enabled': True, 'llm_gemini_paid_api_key': 'paid', 'llm_gemini_api_key': 'k',
                                    'contact_first_name': 'Jeff', 'contact_email': 'ffejnosliw@gmail.com', 'contact_zip': '27519'}
    storage.set_app_state(f"mission_calls:{date.today().isoformat()}", {})
    situations.REFRESH_DELAY_S = 0
    situations._pool_call = lambda *a, **k: {}
    SENT.clear()
    missions._post = lambda dm, argyle, body, card=None: SENT.append(body) or {'id': 'm'}
    missions._browse_async = False          # run the runner inline in tests


def _report(outcome, **kw):
    base = {'outcome': outcome, 'text': kw.pop('text', outcome), 'learned': {}, 'stopped_at': 'https://bodewell.com/guest-schedule-service',
            'wanted_fields': [], 'turns': 7, 'tokens_in': 1000, 'tokens_out': 50, 'seconds': 30.0, 'screenshots': [], 'filled': {}}
    return {**base, **kw}


def _mission():
    return storage.add_mission({'goal': 'get the dishwasher fixed', 'origin_kind': 'manual', 'created_by': 'mom', 'tier': 'mission'})


def scenario_browse_action_runs_the_runner_and_transcribes():
    _reset()
    calls = []
    missions._browse = lambda **kw: calls.append(kw) or _report('done', text='Earliest Tue 8-noon. Trip $114.95', learned={'fee': '$114.95'})
    mid = _mission()
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'find appointment windows and the trip charge', 'site': 'bodewell.com'}
    row = missions.step(storage.get_mission(mid))
    check(row['status'] == 'running', f"after a done browse the planner runs on: {row['status']}")
    steps = storage.get_mission_steps(mid)
    b = [s for s in steps if s['kind'] == 'browse'][0]
    check(b['args_json']['site'] == 'bodewell.com' and b['result_json']['outcome'] == 'done' and '$114.95' in b['result_json']['text'], f"the step: {b}")
    check(calls and calls[0]['site'] == 'bodewell.com' and calls[0]['released'] == {} and 'consent' in calls[0], f"the runner got the goal, site, no release: {calls[0]}")
    counts = storage.get_app_state(f"mission_calls:{date.today().isoformat()}") or {}
    check(counts.get('browse_turns') == 7, f"turns counted against the day: {counts}")
    check(not SENT, "a done browse tells nobody; the planner decides")


def scenario_needs_release_pauses_with_the_values_and_tells_the_person():
    _reset()
    missions._browse = lambda **kw: _report('needs_release', wanted_fields=['first_name', 'email', 'zip'])
    mid = _mission()
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    row = missions.step(storage.get_mission(mid))
    check(row['status'] == 'waiting_user', "the mission waits")
    ask = storage.get_mission_steps(mid)[-1]
    check(ask['kind'] == 'ask' and ask['name'] == 'release' and ask['result_json']['site'] == 'bodewell.com'
          and ask['result_json']['fields'] == ['first_name', 'email', 'zip']
          and ask['result_json']['values'] == {'first_name': 'Jeff', 'email': 'ffejnosliw@gmail.com', 'zip': '27519'}, f"the release ask: {ask}")
    check(ask['result_json']['browse']['goal'] == 'g' and ask['result_json']['browse']['start_url'].startswith('https://bodewell.com'), "the pending browse rides on the ask")
    check(SENT and 'bodewell.com' in SENT[0] and 'Jeff' in SENT[0] and 'ffejnosliw@gmail.com' in SENT[0], f"the DM shows the exact values: {SENT}")
    s = situations.view('mission', mid, {'id': 'mom', 'role': 'parent'})
    check(s['next_step']['verb'] == 'release' and s['next_step']['id'] == 'release:approve', f"the card's next step is the approval: {s['next_step']}")
    check([o['id'] for o in s['options'] if o['verb'] == 'release'] == ['release:approve', 'release:decline', 'release:stop'], "approve, not these, stop")


def scenario_captcha_and_payment_hand_off():
    for outcome, text in (('captcha_failed', '3 attempts at the human-verification check failed'), ('blocked', 'this part needs a payment card; do it yourself here')):
        _reset()
        missions._browse = lambda **kw: _report(outcome, text=text, filled={'first_name': 'Jeff'})
        mid = _mission()
        missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
        row = missions.step(storage.get_mission(mid))
        check(row['status'] == 'waiting_user', f"{outcome}: hand-off waits on the person")
        ask = storage.get_mission_steps(mid)[-1]
        check(ask['kind'] == 'ask' and ask['name'] == 'handoff' and 'bodewell.com' in ask['result_json']['url']
              and ask['result_json']['filled'] == {'first_name': 'Jeff'} and 'question' in ask['result_json'], f"the hand-off ask: {ask}")
        check(SENT and 'bodewell.com' in SENT[0] and 'Jeff' in SENT[0] and 'tell me what you found' in SENT[0].lower(), f"the DM: {SENT}")
        s = situations.view('mission', mid, {'id': 'mom', 'role': 'parent'})
        check(s['next_step']['verb'] == 'answer', "the card asks for the answer")


def scenario_left_the_site_and_refusals_are_notes_the_planner_reads():
    _reset()
    for outcome in ('refused', 'capped', 'error'):
        missions._browse = lambda **kw: _report(outcome, text='x')
        mid = _mission()
        missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
        row = missions.step(storage.get_mission(mid))
        check(row['status'] == 'running' and not SENT, f"{outcome}: the planner reads it, nobody is paged")


def scenario_browse_cap_refuses_before_running():
    _reset()
    storage.set_app_state(f"mission_calls:{date.today().isoformat()}", {'browse_turns': 400})
    ran = []
    missions._browse = lambda **kw: ran.append(1) or _report('done')
    mid = _mission()
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    last = storage.get_mission_steps(mid)[-1]
    check(not ran and last['kind'] == 'note' and 'cap' in (last['result_json'].get('note') or ''), f"the day's cap refuses the run: {last}")


def scenario_a_lost_browse_is_reclaimed_by_the_tick():
    _reset()
    mid = _mission()
    sid = storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {'goal': 'g', 'site': 'bodewell.com'}, 'result_json': None})
    storage.update_mission(mid, {'status': 'browsing'})
    missions.tick()
    check(storage.get_mission(mid)['status'] == 'browsing', "a fresh browse is left alone")
    storage.mission_steps_table.update({'ts': time.time() - missions.BROWSE_LOST_S - 5}, storage.Query().id == sid)
    missions.tick()
    row = storage.get_mission(mid)
    check(row['status'] == 'running', f"an old browse with no result is reclaimed: {row['status']}")
    # The same tick then advances the reclaimed mission, so the note is not
    # necessarily the last step: it must be on the transcript.
    notes = [st for st in storage.get_mission_steps(mid) if st['kind'] == 'note' and 'lost' in ((st.get('result_json') or {}).get('note') or '')]
    check(len(notes) == 1, "and the loss is on the transcript")


def scenario_browsing_mission_is_moving_not_done():
    _reset()
    mid = _mission()
    storage.update_mission(mid, {'status': 'browsing'})
    s = situations.view('mission', mid, {'id': 'mom', 'role': 'parent'})
    check(s['group'] == 'moving' and not s['needs_attention'], f"browsing is moving: {s['group']}")


def scenario_shots_route_is_classified():
    from services import auth
    check(auth.resolve('GET', '/api/missions/x/shots/turn_01.png') == auth.resolve('GET', '/api/missions/x'), "the shot is gated like the transcript")


def scenario_release_approved_resumes_with_the_values_once():
    _reset()
    runs = []
    seq = [_report('needs_release', wanted_fields=['first_name', 'email']), _report('done', text='Tue 8-noon')]
    missions._browse = lambda **kw: runs.append(kw) or seq.pop(0)
    mid = _mission()
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    res = situations.act('mission', mid, 'release', option_id='release:approve', actor={'id': 'mom', 'role': 'parent'})
    check(res['status'] == 'success', f"approve through the card: {res}")
    row = storage.get_mission(mid)
    check(row['status'] == 'running' and row['releases'][0]['site'] == 'bodewell.com' and row['releases'][0]['fields'] == ['first_name', 'email']
          and row['releases'][0]['approved_by'] == 'mom', f"recorded: {row.get('releases')}")
    check(len(runs) == 2 and runs[1]['released'] == {'first_name': 'Jeff', 'email': 'ffejnosliw@gmail.com'} and runs[1]['start_url'].startswith('https://bodewell.com'),
          f"the browse resumed where it stopped with the released values: {runs[1]}")
    # The same site again in this mission: no second ask.
    seq.append(_report('needs_release', wanted_fields=['first_name']))
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g2', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    check(runs[-1]['released'] == {'first_name': 'Jeff', 'email': 'ffejnosliw@gmail.com'}, "released values ride every later browse of that site")


def scenario_release_approved_twice_resumes_once():
    _reset()
    runs = []
    seq = [_report('needs_release', wanted_fields=['zip']), _report('done')]
    missions._browse = lambda **kw: runs.append(kw) or seq.pop(0)
    mid = _mission()
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    a = missions.release(mid, 'approve', {'id': 'mom', 'role': 'parent'})
    b = missions.release(mid, 'approve', {'id': 'mom', 'role': 'parent'})
    check(a['status'] == 'success' and b.get('already') and len(runs) == 2, f"a second approve is a no-op: {b} runs={len(runs)}")


def scenario_release_declined_hands_off_and_stop_blocks():
    _reset()
    missions._browse = lambda **kw: _report('needs_release', wanted_fields=['email'])
    mid = _mission()
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    res = situations.act('mission', mid, 'release', option_id='release:decline', actor={'id': 'mom', 'role': 'parent'})
    last = storage.get_mission_steps(mid)[-1]
    check(res['status'] == 'success' and last['kind'] == 'ask' and last['name'] == 'handoff' and storage.get_mission(mid)['status'] == 'waiting_user', f"decline hands off: {last}")
    _reset()
    missions._browse = lambda **kw: _report('needs_release', wanted_fields=['email'])
    mid = _mission()
    missions.step(storage.get_mission(mid))
    missions.release(mid, 'stop', {'id': 'mom', 'role': 'parent'})
    check(storage.get_mission(mid)['status'] == 'blocked' and 'kept' in (storage.get_mission(mid).get('error') or ''), "stop blocks the mission honestly")
    check(missions.release(mid, 'approve', {'id': 'kid', 'role': 'child'})['status'] == 'refused', "a child cannot release")


def scenario_release_verb_is_in_the_closed_set_everywhere():
    import re
    from services import agent_tools_v2 as tools
    check('release' in situations.VERBS, "the verb")
    src = open('static/situations.js', encoding='utf-8').read()
    check("'release'" in re.search(r"VERB_LABELS\s*=\s*\{([^}]*)\}", src).group(1), "the card label")
    enum = next(t for t in tools.get_available_tools() if t['name'] == 'act_on_situation')['parameters']['properties']['verb']['enum']
    check('release' in enum, "the tool enum")


SCENARIOS = [scenario_browse_action_runs_the_runner_and_transcribes, scenario_needs_release_pauses_with_the_values_and_tells_the_person,
             scenario_captcha_and_payment_hand_off, scenario_left_the_site_and_refusals_are_notes_the_planner_reads,
             scenario_browse_cap_refuses_before_running, scenario_a_lost_browse_is_reclaimed_by_the_tick,
             scenario_browsing_mission_is_moving_not_done, scenario_shots_route_is_classified,
             scenario_release_approved_resumes_with_the_values_once, scenario_release_approved_twice_resumes_once,
             scenario_release_declined_hands_off_and_stop_blocks, scenario_release_verb_is_in_the_closed_set_everywhere]

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

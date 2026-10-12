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
                                    'contact_first_name': 'Jeff', 'contact_email': 'ffejnosliw@gmail.com', 'contact_zip': '27519',
                                    'missions_submit_enabled': True}
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
    check(s['next_step']['verb'] == 'release' and s['next_step']['id'] == f"release:{ask['id']}:approve", f"the card's next step is the approval: {s['next_step']}")
    check([o['id'] for o in s['options'] if o['verb'] == 'release'] == [f"release:{ask['id']}:approve", f"release:{ask['id']}:decline", f"release:{ask['id']}:stop"], "approve, not these, stop")


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
    ask_id = storage.get_mission_steps(mid)[-1]['id']
    res = situations.act('mission', mid, 'release', option_id=f'release:{ask_id}:approve', actor={'id': 'mom', 'role': 'parent'})
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
    ask_id = storage.get_mission_steps(mid)[-1]['id']
    a = missions.release(mid, 'approve', {'id': 'mom', 'role': 'parent'}, ask_id=ask_id)
    b = missions.release(mid, 'approve', {'id': 'mom', 'role': 'parent'}, ask_id=ask_id)
    check(a['status'] == 'success' and b.get('already') and len(runs) == 2, f"a second approve is a no-op: {b} runs={len(runs)}")


def scenario_release_declined_hands_off_and_stop_blocks():
    _reset()
    missions._browse = lambda **kw: _report('needs_release', wanted_fields=['email'])
    mid = _mission()
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    ask_id = storage.get_mission_steps(mid)[-1]['id']
    res = situations.act('mission', mid, 'release', option_id=f'release:{ask_id}:decline', actor={'id': 'mom', 'role': 'parent'})
    last =storage.get_mission_steps(mid)[-1]
    check(res['status'] == 'success' and last['kind'] == 'ask' and last['name'] == 'handoff' and storage.get_mission(mid)['status'] == 'waiting_user', f"decline hands off: {last}")
    _reset()
    missions._browse = lambda **kw: _report('needs_release', wanted_fields=['email'])
    mid = _mission()
    missions.step(storage.get_mission(mid))
    ask_id = storage.get_mission_steps(mid)[-1]['id']
    missions.release(mid, 'stop', {'id': 'mom', 'role': 'parent'}, ask_id=ask_id)
    check(storage.get_mission(mid)['status'] == 'blocked' and 'kept' in (storage.get_mission(mid).get('error') or ''), "stop blocks the mission honestly")
    check(missions.release(mid, 'approve', {'id': 'kid', 'role': 'child'}, ask_id=ask_id)['status'] == 'refused', "a child cannot release")


def scenario_release_verb_is_in_the_closed_set_everywhere():
    import re
    from services import agent_tools_v2 as tools
    check('release' in situations.VERBS, "the verb")
    src = open('static/situations.js', encoding='utf-8').read()
    check("'release'" in re.search(r"VERB_LABELS\s*=\s*\{([^}]*)\}", src).group(1), "the card label")
    enum = next(t for t in tools.get_available_tools() if t['name'] == 'act_on_situation')['parameters']['properties']['verb']['enum']
    check('release' in enum, "the tool enum")


def scenario_a_browse_that_returns_after_the_mission_moved_on_changes_nothing():
    """Review fix 2: the thread's report lands on the step, but a mission that
    was dropped (or reclaimed) meanwhile keeps its status."""
    _reset()
    mid = _mission()
    sid = storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {'goal': 'g', 'site': 'bodewell.com'}, 'result_json': None})
    storage.update_mission(mid, {'status': 'dropped', 'finished_at': time.time()})
    missions.finish_browse(mid, sid, _report('needs_release', wanted_fields=['email']))
    row = storage.get_mission(mid)
    check(row['status'] == 'dropped', f"a dropped mission stays dropped: {row['status']}")
    steps = storage.get_mission_steps(mid)
    check(steps[0]['result_json']['outcome'] == 'needs_release', "the report is still on the step")
    check(not [st for st in steps if st['kind'] == 'ask'] and not SENT, "no release ask, no DM")


def scenario_missing_card_fields_are_asked_for_not_handed_off():
    """2026-10-11: with an empty card the mission must ASK for the details,
    not hand the page over. A release ask names what is missing and where to
    fill it; Share with the card still empty keeps waiting; Share after the
    card is filled resumes with the values."""
    _reset()
    storage.get_settings = lambda: {'missions_enabled': True, 'llm_gemini_paid_api_key': 'paid', 'llm_gemini_api_key': 'k'}
    runs = []
    seq = [_report('needs_release', wanted_fields=['zip', 'city']), _report('done')]
    missions._browse = lambda **kw: runs.append(kw) or seq.pop(0)
    mid = _mission()
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    row = missions.step(storage.get_mission(mid))
    ask = storage.get_mission_steps(mid)[-1]
    check(row['status'] == 'waiting_user' and ask['kind'] == 'ask' and ask['name'] == 'release' and ask['result_json']['missing'] == ['zip', 'city']
          and 'zip' in ask['result_json']['question'] and 'contact card' in ask['result_json']['question'].lower(),
          f"an empty card is a question naming the fields and the card: {ask['result_json']['question']}")
    check(SENT and 'zip' in SENT[-1] and 'contact card' in SENT[-1].lower(), f"the DM asks the same: {SENT}")
    s_ = situations.view('mission', mid, {'id': 'mom', 'role': 'parent'})
    check(s_['next_step']['verb'] == 'release' and 'zip' in s_['next_step']['label'], f"the card leads with it: {s_['next_step']}")
    res = missions.release(mid, 'approve', {'id': 'mom', 'role': 'parent'}, ask_id=ask['id'])
    check(res['status'] == 'success' and not res.get('already') and 'zip' in res['message'] and storage.get_mission(mid)['status'] == 'waiting_user' and len(runs) == 1,
          f"Share with the card still empty keeps waiting and says what to fill: {res}")
    storage.get_settings = lambda: {'missions_enabled': True, 'llm_gemini_paid_api_key': 'paid', 'llm_gemini_api_key': 'k',
                                    'contact_zip': '27519', 'contact_city': 'Cary'}
    res = missions.release(mid, 'approve', {'id': 'mom', 'role': 'parent'}, ask_id=ask['id'])
    check(res['status'] == 'success' and len(runs) == 2 and runs[1]['released'] == {'zip': '27519', 'city': 'Cary'}, f"filled, then Share: the browse resumes with the values: {runs[-1] if runs else None}")
    _reset()
    missions._browse = lambda **kw: _report('needs_release', wanted_fields=['email', 'preferred'])
    mid = _mission()
    missions.step(storage.get_mission(mid))
    ask = storage.get_mission_steps(mid)[-1]
    check(ask['name'] == 'release' and 'preferred' in ask['result_json']['question'] and 'preferred' in SENT[0],
          f"a release ask names the field the card lacks: {ask['result_json']['question']}")


def scenario_the_planner_may_resume_a_browse_where_it_stopped():
    _reset()
    runs = []
    missions._browse = lambda **kw: runs.append(kw) or _report('done')
    mid = _mission()
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com', 'start_url': 'https://www.bodewell.com/service-area/x/cary'}
    missions.step(storage.get_mission(mid))
    check(runs and runs[0]['start_url'] == 'https://www.bodewell.com/service-area/x/cary', f"start_url rides through: {runs}")
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com', 'start_url': 'https://elsewhere.example/x'}
    missions.step(storage.get_mission(mid))
    check(runs[-1]['start_url'] != 'https://elsewhere.example/x' and (runs[-1]['start_url'] or '').startswith(('https://bodewell.com', 'https://www.bodewell.com')) or runs[-1]['start_url'] is None,
          f"a start_url off the site is ignored (the site's remembered page or nothing): {runs[-1]['start_url']}")
    src = missions._system_prompt(__import__('datetime').datetime.now(), {})
    check('start_url' in src and 'resume' in src.lower() and 'found the site' in src.lower(), "the planner is told how to resume and not to finish with 'I found the site'")


def scenario_approve_reads_the_card_as_it_is_now_and_decline_names_the_card():
    """Review fix 7 (spec §1: Not these opens the card to fix): a parent who
    fixes the card before tapping Share releases the corrected value; a decline
    tells them where the card is."""
    _reset()
    runs = []
    seq = [_report('needs_release', wanted_fields=['email']), _report('done')]
    missions._browse = lambda **kw: runs.append(kw) or seq.pop(0)
    mid = _mission()
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    storage.get_settings = lambda: {'missions_enabled': True, 'llm_gemini_paid_api_key': 'paid', 'llm_gemini_api_key': 'k',
                                    'contact_first_name': 'Jeff', 'contact_email': 'fixed@example.com', 'contact_zip': '27519'}
    missions.release(mid, 'approve', {'id': 'mom', 'role': 'parent'}, ask_id=storage.get_mission_steps(mid)[-1]['id'])
    check(runs[-1]['released'] == {'email': 'fixed@example.com'}, f"the corrected card value is what goes out: {runs[-1]['released']}")
    _reset()
    missions._browse = lambda **kw: _report('needs_release', wanted_fields=['email'])
    mid = _mission()
    missions.step(storage.get_mission(mid))
    res = missions.release(mid, 'decline', {'id': 'mom', 'role': 'parent'}, ask_id=storage.get_mission_steps(mid)[-1]['id'])
    check('contact card' in res['message'].lower() and 'contact card' in SENT[-1].lower(), f"decline names the card: {res} {SENT[-1]}")


def scenario_the_planner_sees_the_browse_outcome_first_and_never_the_ledger():
    _reset()
    missions._browse = lambda **kw: _report('capped', text='x' * 2000, learned={'fee': '$114.95'}, stopped_at='https://www.bodewell.com/guest',
                                            turns_log=[{'turn': i, 'action': 'scroll down', 'url': 'u', 'model_ms': 1, 'act_ms': 1} for i in range(40)])
    mid = _mission()
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    prompt = missions._user_prompt(storage.get_mission(mid))
    line = next(ln for ln in prompt.split('\n') if 'browse' in ln and 'result=' in ln)
    check('"outcome": "capped"' in line and '$114.95' in line and 'bodewell.com/guest' in line, f"outcome, learned and stopped_at are in the planner's view: {line[:300]}")
    check('turns_log' not in line and 'scroll down' not in line, "the ledger is for people, not the planner")


def scenario_a_pricing_goal_is_not_finished_without_a_browse():
    """2026-10-11: seeded with the thread's earlier "Call 844-… to get pricing",
    the planner finished in one step, zero tools: "requires a phone call, I
    cannot make phone calls". A goal about pricing, availability or scheduling
    is not finished until this mission has browsed the site (once refused,
    then the planner is free)."""
    _reset()
    runs = []
    missions._browse = lambda **kw: runs.append(kw) or _report('done', text='Earliest Tue 8-noon; trip charge $114.95')
    mid = storage.add_mission({'goal': 'Get pricing and schedule service for the GE Cafe dishwasher', 'origin_kind': 'manual', 'created_by': 'mom', 'tier': 'mission'})
    plan = [{'action': 'finish', 'summary': 'Bodewell requires a phone call to provide pricing. I cannot make phone calls.', 'next_action': 'Call 844-988-4066'},
            {'action': 'browse', 'goal': 'get slots and the fee', 'site': 'bodewell.com'},
            {'action': 'finish', 'summary': 'Tue 8-noon; $114.95', 'next_action': 'Book Tue'}]
    missions._llm = lambda m, s, u, st: plan.pop(0)
    row = missions.step(storage.get_mission(mid))
    last = storage.get_mission_steps(mid)[-1]
    check(row['status'] == 'running' and last['kind'] == 'note' and last['name'] == 'finish_refused' and 'browse' in last['result_json']['note'].lower(),
          f"the early finish is refused with the reason: {row['status']} {last}")
    row = missions.step(storage.get_mission(mid))
    check(runs and row['status'] == 'running', "then it browses")
    row = missions.step(storage.get_mission(mid))
    check(row['status'] == 'done' and '$114.95' in row['summary'], f"a finish after the browse stands: {row['status']} {row.get('summary')}")
    # A goal that is not about a site's prices or slots finishes freely.
    _reset()
    mid = storage.add_mission({'goal': 'find out when the library closes on Sundays', 'origin_kind': 'manual', 'created_by': 'mom', 'tier': 'mission'})
    missions._llm = lambda m, s, u, st: {'action': 'finish', 'summary': 'It closes at 5.'}
    check(missions.step(storage.get_mission(mid))['status'] == 'done', "a plain question finishes")
    # The refusal happens once: a planner that insists without a browse is not looped forever.
    _reset()
    mid = storage.add_mission({'goal': 'get a quote for gutter cleaning', 'origin_kind': 'manual', 'created_by': 'mom', 'tier': 'mission'})
    missions._llm = lambda m, s, u, st: {'action': 'finish', 'summary': 'They only quote by phone.', 'next_action': 'Call them'}
    missions.step(storage.get_mission(mid))
    check(missions.step(storage.get_mission(mid))['status'] == 'done', "the second insistence is allowed")


def scenario_the_planner_is_told_history_is_not_fact_and_to_start_deep():
    src = missions._system_prompt(__import__('datetime').datetime.now(), {})
    check('phone' in src.lower() and 'browse' in src.lower() and ('history' in src.lower() or 'earlier' in src.lower()),
          "earlier thread notes (a 'call them' next step) are to be verified by a browse, never repeated")
    check('deepest' in src.lower() or 'scheduling page' in src.lower(), "a browse starts at the deepest relevant URL already known")


def scenario_the_handoff_reads_cleanly():
    """The hand-off pasted the whole report, LEARNED: and WALL: lines included,
    into the question. One clean sentence, then what was filled."""
    _reset()
    missions._browse = lambda **kw: _report('captcha_failed', filled={'first_name': 'Jeff', 'email': 'ffejnosliw@gmail.com'},
                                            text='The form ("What is your contact information?") was filled with the provided details. The form ends with an '
                                                 "'I'm not a robot' reCAPTCHA verification required before proceeding via NEXT: SELECT APPLIANCE.\n\n"
                                                 'LEARNED: availability=unknown; pricing=unknown\nWALL: captcha')
    mid = _mission()
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    q = storage.get_mission_steps(mid)[-1]['result_json']['question']
    check('LEARNED' not in q and 'WALL' not in q and 'unknown' not in q, f"no report lines in the question: {q}")
    check(q.startswith('I got as far as https://bodewell.com') and 'Filled so far: first_name=Jeff, email=ffejnosliw@gmail.com' in q
          and 'reCAPTCHA' in q and q.endswith('Finish it on your phone and tell me what you found.'), f"the shape: {q}")
    check(len(q) < 520, f"short enough to read on a phone: {len(q)}")


def scenario_the_site_remembers_its_deepest_page():
    """The first browse spent eight turns finding Bodewell's guest form; the
    resumed one started there. The mission engine remembers, per site, the
    deepest page a browse reached (where it stopped for a release, a wall or
    a finish on that site) and starts the next browse of that site there when
    the planner gives no start_url."""
    _reset()
    runs = []
    missions._browse = lambda **kw: runs.append(kw) or _report('needs_release', wanted_fields=['first_name'],
                                                                stopped_at='https://www.bodewell.com/guest-schedule-service')
    mid = _mission()
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    check(runs[0]['start_url'] is None, "nothing known yet: the front door")
    mid2 = _mission()
    missions.step(storage.get_mission(mid2))
    check(runs[1]['start_url'] == 'https://www.bodewell.com/guest-schedule-service', f"the next mission on that site starts at the form: {runs[1]['start_url']}")
    missions._browse = lambda **kw: runs.append(kw) or _report('done', stopped_at='https://www.bodewell.com/about-our-services')
    mid3 = _mission()
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com', 'start_url': 'https://www.bodewell.com/x'}
    missions.step(storage.get_mission(mid3))
    check(runs[2]['start_url'] == 'https://www.bodewell.com/x', "the planner's own start_url wins over memory")
    missions._browse = lambda **kw: runs.append(kw) or _report('blocked', text='left the site: https://elsewhere.example/', stopped_at='https://elsewhere.example/')
    mid4 = _mission()
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid4))
    check(runs[3]['start_url'] == 'https://www.bodewell.com/guest-schedule-service', "a page off the site is never remembered for it")


def _submit_report(**kw):
    rec = {'button': 'Book appointment', 'url': 'https://www.bodewell.com/schedule', 'intent': 'book the Tuesday slot',
           'state': {'fields': {'notes': ''}, 'selected': ['Tue, Oct 20 8AM-12PM'], 'text': 'Trip charge $114.95 Tue, Oct 20 8AM-12PM', 'text_sha': 'a' * 64, 'prices': ['$114.95']},
           'display': 'Trip charge $114.95 Tue, Oct 20 8AM-12PM', 'facts': {'slot': 'Tue, Oct 20 8AM-12PM', 'price': '$114.95'}}
    return _report('needs_submit', text='Book appointment', submit={**rec, **kw.pop('submit', {})}, filled={'first_name': 'Jeff'}, **kw)


def _browse_to_submit(mid):
    missions._browse = lambda **kw: _submit_report()
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'book the Tuesday slot', 'site': 'bodewell.com'}
    return missions.step(storage.get_mission(mid))


def _press(kw):
    """What the runner does before its one press: on_attempt authorizes and
    mints the attempt note. The engine never invents an attempt itself."""
    ok = kw['on_attempt']({'ask_id': kw['approved']['ask_id'], 'button': kw['approved']['button'], 'url': kw['start_url'],
                           'state': kw['approved']['state'], 'pressed_at': 1.0, 'outcome': None, 'text': ''})
    assert ok is True, f"on_attempt refused the press: {ok}"

def scenario_needs_submit_becomes_an_ask_the_person_can_read():
    _reset()
    mid = _mission()
    row = _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    rj = ask['result_json']
    check(row['status'] == 'waiting_user' and ask['kind'] == 'ask' and ask['name'] == 'submit', f"the submit ask: {ask}")
    check(rj['question'] == "Book at bodewell.com: Tue, Oct 20 8AM-12PM, $114.95 (button 'Book appointment')?", f"the question: {rj['question']}")
    check(rj['verb'] == 'book' and rj['button'] == 'Book appointment' and rj['state']['selected'] == ['Tue, Oct 20 8AM-12PM'] and rj['filled'] == {'first_name': 'Jeff'}
          and rj['browse']['start_url'] == 'https://www.bodewell.com/schedule' and rj['browse']['site'] == 'bodewell.com' and rj['changed'] == [], f"the shape: {rj}")
    check(SENT and rj['question'] in SENT[-1] and SENT[-1].endswith("Tap the booking question on the Missions page or the thread card to approve it, or I'll finish it myself / Stop there."), f"the DM: {SENT}")
    check(missions.submit_question('x.com', 'submit', {}, 'Send application') == "Submit at x.com with the button 'Send application'?", "no facts: the button alone")
    check(missions._submit_verb({'button': 'Reserve'}, 'get it fixed') == 'book' and missions._submit_verb({'button': 'Send application'}, 'apply for the permit') == 'submit', "the verb")


def scenario_approve_needs_the_ask_id_and_resumes_with_the_record():
    _reset()
    mid = _mission()
    _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    runs = []
    missions._browse = lambda **kw: runs.append(kw) or _press(kw) or _report('submitted', text='CONFIRMED: 12345', attempt={**kw['approved'], 'pressed_at': 1.0, 'outcome': 'confirmed', 'text': 'Confirmation number 12345'})
    res = missions.submit(mid, 'approve', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, ask_id='stale')
    check(res['status'] == 'success' and res.get('moved') and not runs and storage.get_mission(mid)['status'] == 'waiting_user', f"a stale id moves nothing: {res}")
    res = missions.submit(mid, 'approve', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, ask_id=None)
    check(res.get('moved') and not runs, "no id is refused, not defaulted")
    check(missions.submit(mid, 'approve', {'id': 'kid', 'role': 'child'}, ask_id=ask['id'])['status'] == 'refused', "a child cannot approve")
    res = missions.submit(mid, 'approve', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, ask_id=ask['id'])
    check(res['status'] == 'success' and len(runs) == 1, f"approve with the right id resumes: {res}")
    kw = runs[0]
    check(kw['approved']['button'] == 'Book appointment' and kw['approved']['ask_id'] == ask['id'] and kw['start_url'] == 'https://www.bodewell.com/schedule'
          and callable(kw['on_attempt']), f"the runner got the record, the ask id, the page and on_attempt: {list(kw)}")
    steps = storage.get_mission_steps(mid)
    bstep = [s for s in steps if s['kind'] == 'browse'][-1]
    check(bstep['args_json']['approved_ask_id'] == ask['id'], "the browse step carries the approval")
    check([s['name'] for s in steps if s['kind'] == 'note' and s['name'] in ('submit_approved', 'submitted')] == ['submit_approved', 'submitted'], f"the notes: {[s['name'] for s in steps]}")
    check(storage.get_mission(mid)['status'] == 'running', "after a confirmed press the planner runs on")
    res = missions.submit(mid, 'approve', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, ask_id=ask['id'])
    check(res.get('already') or res.get('moved'), f"a second tap is a no-op: {res}")


def scenario_decline_hands_off_and_stop_reads_the_attempts():
    _reset()
    mid = _mission()
    _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    res = missions.submit(mid, 'decline', {'id': 'mom', 'role': 'parent'}, ask_id=ask['id'])
    last = storage.get_mission_steps(mid)[-1]
    check(res['status'] == 'success' and last['kind'] == 'ask' and last['name'] == 'handoff' and "did not press 'Book appointment'" in last['result_json']['question']
          and storage.get_mission(mid)['status'] == 'waiting_user', f"decline hands off: {last['result_json']['question']}")
    _reset()
    mid = _mission()
    _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    missions.submit(mid, 'stop', {'id': 'mom', 'role': 'parent'}, ask_id=ask['id'])
    check(storage.get_mission(mid)['status'] == 'blocked' and 'did not book' in storage.get_mission(mid)['error'], "stop with no attempt: did not book")
    _reset()
    mid = _mission()
    # (An unknown attempt already on the mission when a browse finishes is asked about first:
    # the live finish raises a verify ask, final review I1. So the attempt lands after the submit ask.)
    _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    storage.add_mission_step(mid, {'kind': 'note', 'name': 'submit_attempt', 'result_json': {'ask_id': 'a1', 'browse_step_id': 'b1', 'button': 'Book appointment', 'url': 'https://www.bodewell.com/s',
                                                                                          'state': {}, 'pressed_at': 1.0, 'outcome': 'unknown', 'text': ''}})
    missions.submit(mid, 'stop', {'id': 'mom', 'role': 'parent'}, ask_id=ask['id'])
    err = storage.get_mission(mid)['error']
    check('may have gone through' in err and 'did not book' not in err, f"stop over an unresolved attempt warns: {err}")


def scenario_on_attempt_authorizes_under_the_lock():
    _reset()
    mid = _mission()
    _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    captured = {}
    missions._browse = lambda **kw: captured.update(kw) or _report('error', text='boom')      # keep the step live; we call on_attempt by hand
    # Drive start_browse ourselves so the mission stays `browsing` while we probe on_attempt.
    rec_ask = ask['result_json']
    sid = storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {'goal': 'g', 'site': 'bodewell.com', 'approved_ask_id': ask['id'], 'approval_spent': False}, 'result_json': None})
    storage.update_mission(mid, {'status': 'browsing'})
    on_attempt = missions._on_attempt_for(mid, sid)
    rec = {'ask_id': ask['id'], 'button': 'Book appointment', 'url': 'https://www.bodewell.com/schedule', 'state': rec_ask['state'], 'pressed_at': 2.0, 'outcome': None, 'text': ''}
    check(on_attempt(rec) is True, "the first call authorizes")
    notes = missions.attempts_for(mid)
    check(len(notes) == 1 and notes[0]['outcome'] is None and notes[0]['browse_step_id'] == sid and notes[0]['ask_id'] == ask['id'], f"the attempt note: {notes}")
    bstep = [s for s in storage.get_mission_steps(mid) if s['id'] == sid][0]
    check(bstep['args_json']['approval_spent'] is True, "the approval is spent")
    check(on_attempt(rec) is False, "a second call is refused (spent)")
    # A fresh step with a fresh approval but an unresolved attempt on the mission: refused.
    sid2 = storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {'goal': 'g', 'site': 'bodewell.com', 'approved_ask_id': 'a9', 'approval_spent': False}, 'result_json': None})
    check(missions._on_attempt_for(mid, sid2)({**rec, 'ask_id': 'a9'}) is False, "an unresolved attempt bars the mission")
    storage.update_mission_step(notes[0]['step_id'], {'result_json': {**notes[0], 'outcome': 'rejected'}})
    check(missions._on_attempt_for(mid, sid)({**rec}) is False, "an older step than the newest browse is refused")
    check(missions._on_attempt_for(mid, sid2)({**rec, 'ask_id': 'wrong'}) is False, "a different ask id is refused")
    check(missions._on_attempt_for(mid, sid2)({**rec, 'ask_id': 'a9'}) is True, "with the attempt resolved, the newest step and its id authorize")
    # Each check alone (review: three of the four were unpinned): every other condition holds.
    for a in missions.attempts_for(mid):
        storage.update_mission_step(a['step_id'], {'result_json': {**a, 'outcome': 'rejected'}})
    check(missions._on_attempt_for(mid, sid2)({**rec, 'ask_id': 'a9'}) is False, "(b) the newest step, browsing, id matches, all resolved, but SPENT: refused")
    sid_old = storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {'goal': 'g', 'site': 'bodewell.com', 'approved_ask_id': 'a11', 'approval_spent': False}, 'result_json': None})
    # The newer step carries the same unspent approval, so only the newest-step check can refuse.
    storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {'goal': 'g', 'site': 'bodewell.com', 'approved_ask_id': 'a11', 'approval_spent': False}, 'result_json': None})
    check(missions._on_attempt_for(mid, sid_old)({**rec, 'ask_id': 'a11'}) is False, "(a) unspent, id matches, all resolved, browsing, but an OLDER step: refused")
    sid_new = storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {'goal': 'g', 'site': 'bodewell.com'}, 'result_json': None})
    check(missions._on_attempt_for(mid, sid_new)({**rec, 'ask_id': None}) is False, "(c) the newest step was never approved: a None ask id is not a match")
    check(len([a for a in missions.attempts_for(mid) if a['outcome'] is None]) == 0, "and none of the refusals wrote an attempt")
    storage.update_mission(mid, {'status': 'running'})
    sid3 = storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {'goal': 'g', 'site': 'bodewell.com', 'approved_ask_id': 'a10', 'approval_spent': False}, 'result_json': None})
    for a in missions.attempts_for(mid):
        storage.update_mission_step(a['step_id'], {'result_json': {**a, 'outcome': 'rejected'}})
    check(missions._on_attempt_for(mid, sid3)({**rec, 'ask_id': 'a10'}) is False, "a mission that is not browsing (reclaimed, cancelled) refuses")


def scenario_a_late_worker_presses_nothing_after_a_reclaim():
    """The worker ran inline up to on_attempt; the tick reclaimed the mission meanwhile."""
    _reset()
    mid = _mission()
    sid = storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {'goal': 'g', 'site': 'bodewell.com', 'approved_ask_id': 'a1', 'approval_spent': False}, 'result_json': None})
    storage.update_mission(mid, {'status': 'browsing'})
    storage.mission_steps_table.update({'ts': time.time() - missions.BROWSE_LOST_S - 5}, storage.Query().id == sid)
    missions.tick()
    check(storage.get_mission(mid)['status'] == 'running', "reclaimed (no attempt yet: running, as before)")
    on_attempt = missions._on_attempt_for(mid, sid)
    check(on_attempt({'ask_id': 'a1', 'button': 'Book appointment', 'url': 'u', 'state': {}, 'pressed_at': 1.0, 'outcome': None, 'text': ''}) is False, "the late worker is refused")
    check(not missions.attempts_for(mid), "and wrote no attempt")


def scenario_outcomes_after_the_press_write_the_attempt_first():
    for outcome, att, want_status, want_note in (('submitted', 'confirmed', 'running', 'submitted'), ('submit_rejected', 'rejected', 'running', 'submit_rejected'),
                                                 ('submit_unknown', 'unknown', 'waiting_user', 'verify')):
        _reset()
        mid = _mission()
        _browse_to_submit(mid)
        ask = storage.get_mission_steps(mid)[-1]
        missions._browse = lambda **kw: _press(kw) or _report(outcome, text=f'{att}: x', attempt={**kw['approved'], 'pressed_at': 1.0, 'outcome': att, 'text': 'Confirmation number 12345' if att == 'confirmed' else 'x'})
        missions.submit(mid, 'approve', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, ask_id=ask['id'])
        notes = missions.attempts_for(mid)
        check(len(notes) == 1 and notes[0]['outcome'] == att, f"{outcome}: the attempt note resolved {att}: {notes}")
        steps = storage.get_mission_steps(mid)
        last = steps[-1]
        check(storage.get_mission(mid)['status'] == want_status and last['name'] == want_note, f"{outcome}: status {storage.get_mission(mid)['status']} last {last['kind']}/{last['name']}")
        if outcome == 'submitted':
            check(last['result_json']['confirmation'] == '12345' and 'Tue, Oct 20 8AM-12PM' in last['result_json']['facts'].values(), f"the submitted note: {last['result_json']}")
        if outcome == 'submit_unknown':
            rj = last['result_json']
            check(last['kind'] == 'ask' and rj['attempt_step_id'] == notes[0]['step_id'] and rj['question'].startswith("I pressed 'Book appointment' at https://www.bodewell.com/schedule and could not read")
                  and not rj['payment'] and SENT[-1].startswith("I pressed"), f"the verify ask: {rj}")
            # The card's verify options (verify:<ask_id>:confirmed ...) are situations.py's: pinned by Task 6's
            # scenario_submit_and_verify_options_carry_the_ask_id_and_route_from_the_thread.


def scenario_an_unresolved_attempt_forces_the_verify_whatever_the_report_says():
    for outcome, text in (('error', 'boom after the press'), ('capped', 'stopped after 40 turns'), ('blocked', 'payment (card field): this part needs a payment card')):
        _reset()
        mid = _mission()
        _browse_to_submit(mid)
        ask = storage.get_mission_steps(mid)[-1]

        def fake(**kw):
            # The worker pressed (on_attempt wrote the note) and then raised or hit a wall: no attempt in the report, or one with no outcome.
            kw['on_attempt']({'ask_id': kw['approved']['ask_id'], 'button': 'Book appointment', 'url': kw['start_url'], 'state': kw['approved']['state'], 'pressed_at': 1.0, 'outcome': None, 'text': ''})
            return _report(outcome, text=text, attempt=None if outcome == 'error' else {**kw['approved'], 'pressed_at': 1.0, 'outcome': 'unknown' if outcome == 'blocked' else None, 'text': ''})
        missions._browse = fake
        missions.submit(mid, 'approve', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, ask_id=ask['id'])
        notes = missions.attempts_for(mid)
        last = storage.get_mission_steps(mid)[-1]
        check(notes[0]['outcome'] == 'unknown' and last['kind'] == 'ask' and last['name'] == 'verify' and storage.get_mission(mid)['status'] == 'waiting_user',
              f"{outcome}: attempt unknown, verify ask, waiting: {notes[0]['outcome']} {last['name']} {storage.get_mission(mid)['status']}")
        if outcome == 'blocked':
            check(last['result_json']['payment'] is True and 'asked for payment' in last['result_json']['question'] and 'finish it on your phone' not in last['result_json']['question'].lower(),
                  f"payment after the press asks to verify, not to finish: {last['result_json']['question']}")


def scenario_verify_resolves_the_attempt_by_tap():
    _reset()
    mid = _mission()
    _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    missions._browse = lambda **kw: _press(kw) or _report('submit_unknown', text='UNKNOWN', attempt={**kw['approved'], 'pressed_at': 1.0, 'outcome': 'unknown', 'text': 'spinner'})
    missions.submit(mid, 'approve', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, ask_id=ask['id'])
    vask = storage.get_mission_steps(mid)[-1]
    res = missions.verify(mid, 'stale', 'confirmed', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, detail='12345')
    check(res.get('moved') and missions.attempts_for(mid)[0]['outcome'] == 'unknown', f"a stale verify card resolves nothing: {res}")
    res = missions.verify(mid, vask['id'], 'unsure', {'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    check(res['status'] == 'success' and storage.get_mission(mid)['status'] == 'waiting_user' and missions.attempts_for(mid)[0]['outcome'] == 'unknown', "unsure keeps waiting")
    res = missions.verify(mid, vask['id'], 'confirmed', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, detail='confirmation 12345')
    a = missions.attempts_for(mid)[0]
    check(res['status'] == 'success' and a['outcome'] == 'confirmed' and a['resolved_by'] == {'id': 'mom', 'name': 'Mom'} and a['detail'] == 'confirmation 12345' and a['resolved_at'] > 0, f"confirmed by hand: {a}")
    last = storage.get_mission_steps(mid)[-1]
    check(last['name'] == 'submitted' and last['result_json']['by_hand'] and storage.get_mission(mid)['status'] == 'running', f"a submitted note by hand, running: {last}")
    # Failed clears the bar; a fresh approve is still required.
    _reset()
    mid = _mission()
    _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    missions._browse = lambda **kw: _press(kw) or _report('submit_unknown', text='UNKNOWN', attempt={**kw['approved'], 'pressed_at': 1.0, 'outcome': 'unknown', 'text': ''})
    missions.submit(mid, 'approve', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, ask_id=ask['id'])
    vask = storage.get_mission_steps(mid)[-1]
    missions.verify(mid, vask['id'], 'failed', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, detail='nothing in my email')
    check(missions.attempts_for(mid)[0]['outcome'] == 'failed' and storage.get_mission_steps(mid)[-1]['name'] == 'submit_failed' and storage.get_mission(mid)['status'] == 'running', "failed: resolved, running")
    sid = storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {'goal': 'g', 'site': 'bodewell.com', 'approved_ask_id': 'fresh', 'approval_spent': False}, 'result_json': None})
    storage.update_mission(mid, {'status': 'browsing'})
    check(missions._on_attempt_for(mid, sid)({'ask_id': 'fresh', 'button': 'B', 'url': 'u', 'state': {}, 'pressed_at': 1.0, 'outcome': None, 'text': ''}) is True, "a verified failure admits a fresh approved attempt")
    check(missions.verify(mid, vask['id'], 'confirmed', {'id': 'kid', 'role': 'child'})['status'] == 'refused', "a child cannot verify")


def scenario_a_late_report_never_overwrites_a_parents_answer_and_only_the_live_browse_moves_the_mission():
    _reset()
    mid = _mission()
    _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    missions._browse = lambda **kw: _press(kw) or _report('submit_unknown', text='UNKNOWN', attempt={**kw['approved'], 'pressed_at': 1.0, 'outcome': 'unknown', 'text': ''})
    missions.submit(mid, 'approve', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, ask_id=ask['id'])
    old_browse = [s for s in storage.get_mission_steps(mid) if s['kind'] == 'browse'][-1]
    vask = storage.get_mission_steps(mid)[-1]
    missions.verify(mid, vask['id'], 'confirmed', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, detail='12345')
    # A newer browse starts and is live.
    sid2 = storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {'goal': 'g2', 'site': 'bodewell.com'}, 'result_json': None})
    storage.update_mission(mid, {'status': 'browsing'})
    # The old worker returns late, saying unknown again.
    a0 = missions.attempts_for(mid)[0]
    missions.finish_browse(mid, old_browse['id'], _report('submit_unknown', text='late', attempt={'ask_id': ask['id'], 'button': 'Book appointment', 'url': 'u', 'state': {}, 'pressed_at': 1.0, 'outcome': 'unknown', 'text': 'late worker'}))
    a1 = missions.attempts_for(mid)[0]
    check(a1['outcome'] == 'confirmed' and a1['resolved_by'] == a0['resolved_by'] and a1['late_reports'] == [{'outcome': 'unknown', 'text': 'late worker', 'ts': a1['late_reports'][0]['ts']}],
          f"the parent's answer stands; the late report is appended: {a1}")
    steps = storage.get_mission_steps(mid)
    check(any(s['name'] == 'late_evidence' for s in steps) and storage.get_mission(mid)['status'] == 'browsing'
          and [s for s in steps if s['id'] == sid2][0]['result_json'] is None, "a late_evidence note; the newer browse untouched; status unchanged")
    check([s for s in steps if s['id'] == old_browse['id']][0]['result_json']['text'] == 'late', "the late report is on its own step")
    check(not [s for s in steps if s['kind'] == 'ask' and s['idx'] > vask['idx']], "no new ask from a late report")


def scenario_the_reclaim_marks_a_pending_attempt_unknown_and_verifies():
    _reset()
    mid = _mission()
    sid = storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {'goal': 'g', 'site': 'bodewell.com', 'approved_ask_id': 'a1', 'approval_spent': True}, 'result_json': None})
    storage.add_mission_step(mid, {'kind': 'note', 'name': 'submit_attempt', 'result_json': {'ask_id': 'a1', 'browse_step_id': sid, 'button': 'Book appointment', 'url': 'https://www.bodewell.com/s',
                                                                                          'state': {}, 'pressed_at': time.time(), 'outcome': None, 'text': ''}})
    storage.update_mission(mid, {'status': 'browsing'})
    storage.mission_steps_table.update({'ts': time.time() - missions.BROWSE_LOST_S - 5}, storage.Query().id == sid)
    missions.tick()
    check(storage.get_mission(mid)['status'] == 'waiting_user' and missions.attempts_for(mid)[0]['outcome'] == 'unknown'
          and storage.get_mission_steps(mid)[-1]['name'] == 'verify', f"a dead worker's attempt: unknown, verify, never running: {storage.get_mission(mid)['status']}")


def scenario_an_unasked_attempt_is_recorded_after_the_fact():
    _reset()
    mid = _mission()
    missions._browse = lambda **kw: _report('submit_unknown', text="confirmation page after an ungated press of 'Go'",
                                            attempt={'ask_id': None, 'button': 'Go', 'url': 'https://www.bodewell.com/x', 'state': {}, 'pressed_at': 1.0, 'outcome': 'unknown', 'text': 'Thank you', 'unasked': True})
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    a = missions.attempts_for(mid)
    last = storage.get_mission_steps(mid)[-1]
    check(len(a) == 1 and a[0]['unasked'] and a[0]['outcome'] == 'unknown' and a[0]['ask_id'] is None and last['name'] == 'verify' and last['result_json']['attempt_step_id'] == a[0]['step_id'],
          f"the unasked attempt and its verify ask: {a} {last['name']}")


def scenario_an_unasked_press_after_continued_is_verified_beside_the_approved_attempt():
    """Review fix (Task 5, I2): the runner keeps the CONTINUED attempt in
    `attempt` and puts a later unasked press in `attempts_extra`; both reach
    the transcript and the verify ask names the unasked press."""
    _reset()
    mid = _mission()
    _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]

    def fake(**kw):
        _press(kw)
        return _report('submit_unknown', text="confirmation page after an ungated press of 'Go'",
                       attempt={**kw['approved'], 'pressed_at': 1.0, 'outcome': 'continued', 'text': 'the next step of the form'},
                       attempts_extra=[{'ask_id': None, 'button': 'Go', 'url': 'https://www.bodewell.com/x', 'state': {}, 'pressed_at': 2.0,
                                        'outcome': 'unknown', 'text': 'Thank you', 'unasked': True}])
    missions._browse = fake
    missions.submit(mid, 'approve', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, ask_id=ask['id'])
    atts = missions.attempts_for(mid)
    approved = [a for a in atts if a.get('ask_id') == ask['id']]
    unasked = [a for a in atts if a.get('unasked')]
    last = storage.get_mission_steps(mid)[-1]
    check(len(atts) == 2 and len(approved) == 1 and approved[0]['outcome'] == 'continued' and len(unasked) == 1 and unasked[0]['outcome'] == 'unknown',
          f"the approved attempt resolves continued, the unasked one is on record unknown: {atts}")
    check(last['kind'] == 'ask' and last['name'] == 'verify' and last['result_json']['button'] == 'Go' and last['result_json']['attempt_step_id'] == unasked[0]['step_id']
          and storage.get_mission(mid)['status'] == 'waiting_user', f"the verify ask names the unasked press: {last['name']} {last.get('result_json')}")

def scenario_a_press_with_no_attempt_is_never_a_booking_and_the_decisions_are_claimed():
    """Review fixes (Task 5, minors 4-6): only on_attempt mints an attempt, so a
    'submitted' with none on record is checked by the person, never booked; a
    capped approve says so; decline and stop are claimed under the lock."""
    _reset()
    mid = _mission()
    _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    missions._browse = lambda **kw: _report('submitted', text='CONFIRMED: 12345', attempt={**kw['approved'], 'pressed_at': 1.0, 'outcome': 'confirmed', 'text': 'Confirmation number 12345'})
    missions.submit(mid, 'approve', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, ask_id=ask['id'])
    steps = storage.get_mission_steps(mid)
    last = steps[-1]
    check(not any(s['name'] == 'submitted' for s in steps) and not missions.attempts_for(mid) and last['kind'] == 'ask' and last['name'] == 'handoff'
          and 'not counting' in last['result_json']['question'] and storage.get_mission(mid)['status'] == 'waiting_user',
          f"a submitted with no attempt on record is a question, not a booking: {last['name']} {last.get('result_json')}")
    _reset()
    mid = _mission()
    _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    storage.set_app_state(f"mission_calls:{date.today().isoformat()}", {'browse_turns': 400})
    ran = []
    missions._browse = lambda **kw: ran.append(1) or _report('done')
    res = missions.submit(mid, 'approve', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, ask_id=ask['id'])
    last = storage.get_mission_steps(mid)[-1]
    check(not ran and 'cap' in res['message'] and 'now' not in res['message'] and storage.get_mission(mid)['status'] == 'running'
          and last['name'] == 'refused', f"a capped approve says so: {res} {last['name']}")
    _reset()
    mid = _mission()
    _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    a = missions.submit(mid, 'decline', {'id': 'mom', 'role': 'parent'}, ask_id=ask['id'])
    b = missions.submit(mid, 'decline', {'id': 'mom', 'role': 'parent'}, ask_id=ask['id'])
    check(a['status'] == 'success' and not a.get('already') and b.get('already')
          and len([s for s in storage.get_mission_steps(mid) if s['name'] == 'handoff']) == 1, f"a second decline is already: {a} {b}")
    _reset()
    mid = _mission()
    _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    ran = []
    missions._browse = lambda **kw: ran.append(1) or _report('done')
    missions.submit(mid, 'stop', {'id': 'mom', 'role': 'parent'}, ask_id=ask['id'])
    b = missions.submit(mid, 'approve', {'id': 'mom', 'role': 'parent'}, ask_id=ask['id'])
    check(b.get('already') and not ran and storage.get_mission(mid)['status'] == 'blocked', f"an approve after a stop is already, nothing runs: {b}")

def scenario_the_finish_says_booked_and_the_planner_knows_the_rules():
    _reset()
    from services import threads
    tid = threads.create('Dishwasher repair', owner_member_id='mom', goal='get it fixed', created_by='mom')
    mid = storage.add_mission({'goal': 'book the dishwasher repair', 'origin_kind': 'thread', 'origin_ref': tid, 'created_by': 'mom', 'tier': 'mission'})
    storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {}, 'result_json': {'outcome': 'submitted', 'text': 'x', 'turns': 3}})
    storage.add_mission_step(mid, {'kind': 'note', 'name': 'submit_attempt', 'result_json': {'ask_id': 'a1', 'browse_step_id': 'b', 'button': 'Book appointment', 'url': 'u', 'state': {},
                                                                                          'pressed_at': 1.0, 'outcome': 'confirmed', 'text': 'Confirmation number 12345'}})
    storage.add_mission_step(mid, {'kind': 'note', 'name': 'submitted', 'result_json': {'verb': 'book', 'facts': {'slot': 'Tue, Oct 20 8AM-12PM', 'price': '$114.95'}, 'confirmation': '12345', 'text': 'Confirmation number 12345'}})
    missions._llm = lambda m, s, u, st: {'action': 'finish', 'summary': 'Booked Bodewell for Tuesday.', 'next_action': 'Be home Tue Oct 20 8-12', 'next_action_at': '2026-10-20'}
    missions.step(storage.get_mission(mid))
    t = storage.get_thread(tid)
    last = [h for h in t['history'] if h['kind'] == 'mission'][-1]
    check('Booked: Tue, Oct 20 8AM-12PM, $114.95, confirmation 12345' in SENT[-1] and 'Nothing is booked' not in SENT[-1], f"the DM: {SENT[-1]}")
    check('Booked:' in last['text'] and t['next_action_at'] == '2026-10-20', f"the thread note and the appointment as the next step: {last} {t['next_action_at']}")
    src = missions._system_prompt(__import__('datetime').datetime.now(), {'missions_submit_enabled': True})
    check('submit_attempt' in src and 'never press again' in src.lower() and 'ask the person' in src.lower(), "the planner's attempt rule")
    check('book' in missions._system_prompt(__import__('datetime').datetime.now(), {'missions_submit_enabled': False}).lower()
          and 'booking is off' in missions._system_prompt(__import__('datetime').datetime.now(), {'missions_submit_enabled': False}).lower(), "the planner is told when booking is off")
    # A re-ask leads with the change and is a new ask id.
    _reset()
    mid = _mission()
    _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    missions._browse = lambda **kw: _submit_report(changed=['selected: Thu, Oct 22 8AM-12PM (approved: Tue, Oct 20 8AM-12PM)', 'text: changed'],
                                                   submit={'state': {'fields': {}, 'selected': ['Thu, Oct 22 8AM-12PM'], 'text': 't', 'text_sha': 'b' * 64, 'prices': ['$114.95']}})
    missions.submit(mid, 'approve', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, ask_id=ask['id'])
    ask2 = storage.get_mission_steps(mid)[-1]
    check(ask2['kind'] == 'ask' and ask2['name'] == 'submit' and ask2['id'] != ask['id'] and ask2['result_json']['question'].startswith('The page changed: selected Thu, Oct 22 8AM-12PM (approved: Tue, Oct 20 8AM-12PM). Book at bodewell.com:'),
          f"the re-ask: {ask2['result_json']['question']}")
    check(missions.submit(mid, 'approve', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, ask_id=ask['id']).get('moved'), "the spent id answers nothing")


def scenario_submit_and_verify_options_carry_the_ask_id_and_route_from_the_thread():
    _reset()
    from services import threads
    tid = threads.create('Dishwasher repair', owner_member_id='mom', goal='get it fixed', created_by='mom')
    mid = storage.add_mission({'goal': 'book the dishwasher repair', 'origin_kind': 'thread', 'origin_ref': tid, 'created_by': 'mom', 'tier': 'mission'})
    _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    s = situations.view('mission', mid, {'id': 'mom', 'role': 'parent'})
    ids = [o['id'] for o in s['options'] if o['verb'] == 'submit']
    check(ids == [f"submit:{ask['id']}:approve", f"submit:{ask['id']}:decline", f"submit:{ask['id']}:stop"], f"the mission's options: {ids}")
    check(s['next_step']['label'].startswith('Book at bodewell.com') and "(button 'Book appointment')" in s['next_step']['label'] and s['needs_attention'],
          f"the lead reads the whole question, never a blind 'Book it': {s['next_step']}")
    t = situations.view('thread', tid, {'id': 'mom', 'role': 'parent'})
    tids = [o['id'] for o in t['options'] if o['verb'] == 'submit']
    check(tids[0] == f"submit:mission:{mid}:{ask['id']}:approve", f"the thread routes with the id: {tids}")
    res = situations.act('thread', tid, 'submit', option_id=f"submit:mission:{mid}:stale:approve", actor={'id': 'mom', 'role': 'parent'})
    check(res['status'] == 'refused' and storage.get_mission(mid)['status'] == 'waiting_user', f"a stale option is not on the table: {res}")
    runs = []

    def _unknown(**kw):
        runs.append(kw)
        _press(kw)
        return _report('submit_unknown', text='UNKNOWN', attempt={**kw['approved'], 'pressed_at': 1.0, 'outcome': 'unknown', 'text': ''})
    missions._browse = _unknown
    res = situations.act('thread', tid, 'submit', option_id=tids[0], actor={'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    check(res['status'] == 'success' and len(runs) == 1 and runs[0]['approved']['ask_id'] == ask['id'], f"Book it from the thread resumes with the ask id: {res}")
    vask = storage.get_mission_steps(mid)[-1]
    s = situations.view('mission', mid, {'id': 'mom', 'role': 'parent'})
    vids = [o['id'] for o in s['options'] if o['verb'] == 'verify']
    check(vids == [f"verify:{vask['id']}:confirmed", f"verify:{vask['id']}:failed", f"verify:{vask['id']}:unsure"] and s['next_step']['label'] == 'It went through', f"the verify options: {vids} {s['next_step']}")
    res = situations.act('mission', mid, 'verify', option_id=vids[0], payload={'text': 'confirmation 777'}, actor={'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    a = missions.attempts_for(mid)[0]
    check(res['status'] == 'success' and a['outcome'] == 'confirmed' and a['detail'] == 'confirmation 777', f"the detail rides the payload text: {a}")
    from services import triage
    _reset()
    mid = _mission()
    _browse_to_submit(mid)
    check(triage.tier(situations.view('mission', mid, {'id': 'mom', 'role': 'parent'})) == 0, "a submit ask ranks tier 0")


def scenario_submit_and_verify_verbs_are_tap_only_everywhere():
    import re
    from services import agent_tools_v2 as tools
    for v in ('submit', 'verify'):
        check(v in situations.VERBS, f"the verb {v}")
        src = open('static/situations.js', encoding='utf-8').read()
        check(f"'{v}'" in re.search(r"VERB_LABELS\s*=\s*\{([^}]*)\}", src).group(1), f"the card label for {v}")
        res = tools.act_on_situation(ref='x', verb=v, acting_member={'id': 'mom', 'role': 'parent'})
        check(res['status'] == 'error' and 'tap' in res['message'].lower(), f"the chat tool refuses {v}: {res}")
    enum = next(t for t in tools.get_available_tools() if t['name'] == 'act_on_situation')['parameters']['properties']['verb']['enum']
    check('submit' not in enum and 'verify' not in enum, "the new tap-only verbs are not offered to the model (release stays listed; its handler refuses, pinned elsewhere)")


def scenario_release_options_carry_the_ask_id():
    _reset()
    missions._browse = lambda **kw: _report('needs_release', wanted_fields=['email'])
    mid = _mission()
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    ask = storage.get_mission_steps(mid)[-1]
    s = situations.view('mission', mid, {'id': 'mom', 'role': 'parent'})
    check([o['id'] for o in s['options'] if o['verb'] == 'release'] == [f"release:{ask['id']}:approve", f"release:{ask['id']}:decline", f"release:{ask['id']}:stop"], "release ids carry the ask")
    res = missions.release(mid, 'approve', {'id': 'mom', 'role': 'parent'}, ask_id=None)
    check(res.get('moved') and storage.get_mission(mid)['status'] == 'waiting_user', f"no ask id: refused, not defaulted: {res}")
    res = missions.release(mid, 'approve', {'id': 'mom', 'role': 'parent'}, ask_id='old')
    check(res.get('moved'), "a stale id moves nothing")

def scenario_submit_and_verify_routes_are_classified_like_release():
    from services import auth
    for path in ('/api/missions/x/submit', '/api/missions/x/verify'):
        check(auth.resolve('POST', path) == auth.resolve('POST', '/api/missions/x/release'), f"{path} is gated like release")


MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}
UNASKED = {'ask_id': None, 'button': 'Grab it', 'url': 'https://www.bodewell.com/x', 'state': {}, 'pressed_at': 1.0, 'outcome': 'unknown',
           'text': 'Thank you for your booking', 'unasked': True}


def scenario_a_late_unasked_attempt_is_asked_about_never_orphaned():
    """Final review I1, route 1: a late report carrying an unasked press on a
    mission that moved on. The attempt bars every later press, so the parent
    is asked; an ended mission keeps its status and its verify is answerable."""
    _reset()
    mid = _mission()
    sid = storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {'goal': 'g', 'site': 'bodewell.com'}, 'result_json': None})
    storage.update_mission(mid, {'status': 'running'})            # reclaimed: not live
    missions.finish_browse(mid, sid, _report('submit_unknown', text='late', attempt=dict(UNASKED)))
    a = missions.attempts_for(mid)
    last = storage.get_mission_steps(mid)[-1]
    check(len(a) == 1 and a[0]['outcome'] == 'unknown' and last['kind'] == 'ask' and last['name'] == 'verify' and last['result_json']['attempt_step_id'] == a[0]['step_id']
          and storage.get_mission(mid)['status'] == 'waiting_user' and SENT and "I pressed 'Grab it'" in SENT[-1],
          f"a late unasked attempt on a running mission: verify ask, waiting, DM: {last['name']} {storage.get_mission(mid)['status']} {SENT}")
    # On a mission that already ended: the verify ask and the DM, the status kept, and the card still answers.
    _reset()
    mid = _mission()
    sid = storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {'goal': 'g', 'site': 'bodewell.com'}, 'result_json': None})
    storage.update_mission(mid, {'status': 'done', 'finished_at': time.time()})
    missions.finish_browse(mid, sid, _report('submit_unknown', text='late', attempt=dict(UNASKED)))
    last = storage.get_mission_steps(mid)[-1]
    check(last['kind'] == 'ask' and last['name'] == 'verify' and storage.get_mission(mid)['status'] == 'done'
          and SENT and 'may have happened' in SENT[-1], f"an ended mission: verify ask + DM, status stays done: {last['name']} {storage.get_mission(mid)['status']} {SENT}")
    s = situations.view('mission', mid, MOM)
    vids = [o['id'] for o in s['options'] if o['verb'] == 'verify']
    check(vids == [f"verify:{last['id']}:confirmed", f"verify:{last['id']}:failed", f"verify:{last['id']}:unsure"] and s['needs_attention'],
          f"the ended mission's verify card is offered: {vids}")
    res = missions.verify(mid, last['id'], 'confirmed', MOM, detail='confirmation 777')
    a = missions.attempts_for(mid)[0]
    check(res['status'] == 'success' and a['outcome'] == 'confirmed' and a['resolved_by']['id'] == 'mom' and storage.get_mission(mid)['status'] == 'done',
          f"resolved by tap, the mission stays done: {res} {a['outcome']} {storage.get_mission(mid)['status']}")
    check(missions.verify(mid, last['id'], 'failed', MOM).get('already') and missions.attempts_for(mid)[0]['outcome'] == 'confirmed', "a second tap is already")
    check(not [o for o in situations.view('mission', mid, MOM)['options'] if o['verb'] == 'verify'], "once answered, the ended mission offers no verify")


def scenario_the_live_finish_asks_about_every_unknown_attempt_on_the_mission():
    """Final review I1: the live finish looks at the whole mission, not only its own step."""
    _reset()
    mid = _mission()
    storage.add_mission_step(mid, {'kind': 'note', 'name': 'submit_attempt', 'result_json': {**UNASKED, 'browse_step_id': 'older'}})
    missions._browse = lambda **kw: _report('done', text='nothing more')
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    last = storage.get_mission_steps(mid)[-1]
    check(last['name'] == 'verify' and last['result_json']['attempt_step_id'] == missions.attempts_for(mid)[0]['step_id'] and storage.get_mission(mid)['status'] == 'waiting_user',
          f"an older step's unknown attempt is asked about: {last['name']} {storage.get_mission(mid)['status']}")
    # Two unknown attempts: answering one asks about the other, never runs on past it.
    _reset()
    mid = _mission()
    storage.add_mission_step(mid, {'kind': 'note', 'name': 'submit_attempt', 'result_json': {**UNASKED, 'browse_step_id': 'b1', 'button': 'First'}})
    storage.add_mission_step(mid, {'kind': 'note', 'name': 'submit_attempt', 'result_json': {**UNASKED, 'browse_step_id': 'b2', 'button': 'Second'}})
    missions.step(storage.get_mission(mid))
    v1 = storage.get_mission_steps(mid)[-1]
    res = missions.verify(mid, v1['id'], 'failed', MOM)
    asks = [s for s in storage.get_mission_steps(mid) if s['kind'] == 'ask' and s['name'] == 'verify']
    check(len(asks) == 2 and asks[0]['result_json']['button'] == 'Second' and asks[1]['result_json']['button'] == 'First'
          and storage.get_mission(mid)['status'] == 'waiting_user' and 'One more press' in res['message'],
          f"the other unknown attempt is asked next: {[a['result_json']['button'] for a in asks]} {storage.get_mission(mid)['status']} {res}")


def scenario_free_text_never_answers_a_tap_ask():
    """Final review I1, route 2: the free-text answer path moved a waiting
    mission to running and buried the submit or verify ask under the next one."""
    _reset()
    mid = _mission()
    _browse_to_submit(mid)
    check(missions.tap_only_ask_pending(mid), "a pending submit is tap-only")
    res = situations.act('mission', mid, 'answer', payload={'text': 'x'}, actor=MOM)
    check(res['status'] in ('error', 'refused') and storage.get_mission(mid)['status'] == 'waiting_user', f"act refuses an answer to a submit ask: {res}")
    res = situations._run('mission', mid, 'answer', {'text': 'x'}, MOM, situations.load('mission', mid))
    check(res == {'status': 'error', 'message': 'Answer that one with its buttons.'} and storage.get_mission(mid)['status'] == 'waiting_user'
          and not [s for s in storage.get_mission_steps(mid) if s['name'] == 'user_answer'], f"the answer verb itself refuses: {res}")
    src = open('main.py', encoding='utf-8').read()
    route = src[src.index('def missions_answer'):src.index('def delete_mission_route')]
    check('tap_only_ask_pending' in route and 'Answer that one with its buttons.' in route, "POST /answer refuses the same way")
    # A plain question still takes free text.
    _reset()
    missions._browse = lambda **kw: _report('captcha_failed', text='3 attempts failed')
    mid = _mission()
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    check(not missions.tap_only_ask_pending(mid), "a hand-off takes free text")


def scenario_resolving_attempts_holds_the_lock():
    """Final review I3: the attempt notes are rewritten under db_lock, the
    lock a parent's verify tap takes."""
    import threading

    class Spy:
        def __init__(self):
            self.inner, self.depth = threading.RLock(), 0

        def __enter__(self):
            self.inner.acquire()
            self.depth += 1

        def __exit__(self, *a):
            self.depth -= 1
            self.inner.release()
    _reset()
    mid = _mission()
    sid = storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {}, 'result_json': None})
    storage.add_mission_step(mid, {'kind': 'note', 'name': 'submit_attempt', 'result_json': {'ask_id': 'a1', 'browse_step_id': sid, 'button': 'B', 'url': 'u', 'state': {},
                                                                                          'pressed_at': 1.0, 'outcome': None, 'text': ''}})
    spy, held = Spy(), []
    orig_lock, orig_write = storage.db_lock, missions._write_attempt
    storage.db_lock = spy
    missions._write_attempt = lambda step_id, data: held.append(spy.depth > 0) or orig_write(step_id, data)
    try:
        missions._resolve_attempts(mid, sid, {'attempt': {'ask_id': 'a1', 'outcome': 'rejected', 'text': 'taken'}}, True)
    finally:
        storage.db_lock, missions._write_attempt = orig_lock, orig_write
    check(held and all(held), f"every attempt write ran under db_lock: {held}")


def scenario_a_re_ask_names_every_change_and_the_price():
    """Final review I5: a re-ask leads with every change (not only the first),
    and a record whose facts carry no amount shows the page's own price."""
    _reset()
    mid = _mission()
    _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    missions._browse = lambda **kw: _submit_report(changed=['selected: Thu, Oct 22 8AM-12PM (approved: Tue, Oct 20 8AM-12PM)',
                                                            'prices: $124.95 appears; $114.95 does not', 'text: changed'],
                                                   submit={'facts': {}, 'state': {'fields': {}, 'selected': ['Thu, Oct 22 8AM-12PM'], 'text': 't', 'text_sha': 'b' * 64, 'prices': ['$124.95']}})
    missions.submit(mid, 'approve', MOM, ask_id=ask['id'])
    q = storage.get_mission_steps(mid)[-1]['result_json']['question']
    check(q.startswith('The page changed: selected Thu, Oct 22 8AM-12PM (approved: Tue, Oct 20 8AM-12PM); prices $124.95 appears; $114.95 does not. Book at bodewell.com:')
          and 'text changed' not in q and '$124.95 (button' in q, f"both changes lead, the new price is in the question: {q}")
    _reset()
    mid = _mission()
    missions._browse = lambda **kw: _submit_report(submit={'facts': {}})
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'book the Tuesday slot', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    q = storage.get_mission_steps(mid)[-1]['result_json']['question']
    check('$114.95' in q and q == "Book at bodewell.com: $114.95 (button 'Book appointment')?", f"no facts: the page's price is in the question: {q}")
    tpl = open('templates/components/mission_transcript.html', encoding='utf-8').read()
    check('submit-changed' in tpl and '.changed' in tpl, "the transcript's submit block lists the changed lines")


def scenario_the_switch_off_offers_no_approve():
    """Final review M2: with booking switched off the card offers no approve
    (finishing it by hand and stopping stay) and an approve re-runs nothing."""
    _reset()
    mid = _mission()
    _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    settings = storage.get_settings()
    storage.get_settings = lambda: {**settings, 'missions_submit_enabled': False}
    ids = [o['id'] for o in situations.view('mission', mid, MOM)['options'] if o['verb'] == 'submit']
    check(ids == [f"submit:{ask['id']}:decline", f"submit:{ask['id']}:stop"], f"no approve while booking is off: {ids}")
    ran = []
    missions._browse = lambda **kw: ran.append(1) or _report('done')
    res = missions.submit(mid, 'approve', MOM, ask_id=ask['id'])
    check(res == {'status': 'success', 'message': 'Booking is switched off (Missions → Browser).'} and not ran and storage.get_mission(mid)['status'] == 'waiting_user',
          f"approve answers switched off and runs nothing: {res}")


def scenario_the_reclaim_waits_past_the_runners_clock():
    from services import browse
    check(missions.BROWSE_LOST_S == 900 and missions.BROWSE_LOST_S > browse.DEFAULT_CAPS['seconds'],
          f"a live worker (600 s clock) is never reclaimed mid-run: {missions.BROWSE_LOST_S}")


SCENARIOS = [scenario_browse_action_runs_the_runner_and_transcribes, scenario_needs_release_pauses_with_the_values_and_tells_the_person,
             scenario_captcha_and_payment_hand_off, scenario_left_the_site_and_refusals_are_notes_the_planner_reads,
             scenario_browse_cap_refuses_before_running, scenario_a_lost_browse_is_reclaimed_by_the_tick,
             scenario_browsing_mission_is_moving_not_done, scenario_shots_route_is_classified,
             scenario_release_approved_resumes_with_the_values_once, scenario_release_approved_twice_resumes_once,
             scenario_release_declined_hands_off_and_stop_blocks, scenario_release_verb_is_in_the_closed_set_everywhere,
             scenario_a_browse_that_returns_after_the_mission_moved_on_changes_nothing, scenario_missing_card_fields_are_asked_for_not_handed_off,
             scenario_the_planner_may_resume_a_browse_where_it_stopped, scenario_the_planner_sees_the_browse_outcome_first_and_never_the_ledger,
             scenario_a_pricing_goal_is_not_finished_without_a_browse, scenario_the_planner_is_told_history_is_not_fact_and_to_start_deep,
             scenario_the_handoff_reads_cleanly, scenario_the_site_remembers_its_deepest_page,
             scenario_approve_reads_the_card_as_it_is_now_and_decline_names_the_card,
             scenario_needs_submit_becomes_an_ask_the_person_can_read,
             scenario_approve_needs_the_ask_id_and_resumes_with_the_record,
             scenario_decline_hands_off_and_stop_reads_the_attempts,
             scenario_on_attempt_authorizes_under_the_lock,
             scenario_a_late_worker_presses_nothing_after_a_reclaim,
             scenario_outcomes_after_the_press_write_the_attempt_first,
             scenario_an_unresolved_attempt_forces_the_verify_whatever_the_report_says,
             scenario_verify_resolves_the_attempt_by_tap,
             scenario_a_late_report_never_overwrites_a_parents_answer_and_only_the_live_browse_moves_the_mission,
             scenario_the_reclaim_marks_a_pending_attempt_unknown_and_verifies,
             scenario_an_unasked_attempt_is_recorded_after_the_fact,
             scenario_the_finish_says_booked_and_the_planner_knows_the_rules,
             scenario_an_unasked_press_after_continued_is_verified_beside_the_approved_attempt,
             scenario_a_press_with_no_attempt_is_never_a_booking_and_the_decisions_are_claimed,
             scenario_submit_and_verify_options_carry_the_ask_id_and_route_from_the_thread,
             scenario_submit_and_verify_verbs_are_tap_only_everywhere,
             scenario_release_options_carry_the_ask_id,
             scenario_submit_and_verify_routes_are_classified_like_release,
             scenario_a_late_unasked_attempt_is_asked_about_never_orphaned,
             scenario_the_live_finish_asks_about_every_unknown_attempt_on_the_mission,
             scenario_free_text_never_answers_a_tap_ask, scenario_resolving_attempts_holds_the_lock,
             scenario_a_re_ask_names_every_change_and_the_price, scenario_the_switch_off_offers_no_approve,
             scenario_the_reclaim_waits_past_the_runners_clock]

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

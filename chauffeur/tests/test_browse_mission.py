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
    res = missions.release(mid, 'approve', {'id': 'mom', 'role': 'parent'})
    check(res['status'] == 'success' and not res.get('already') and 'zip' in res['message'] and storage.get_mission(mid)['status'] == 'waiting_user' and len(runs) == 1,
          f"Share with the card still empty keeps waiting and says what to fill: {res}")
    storage.get_settings = lambda: {'missions_enabled': True, 'llm_gemini_paid_api_key': 'paid', 'llm_gemini_api_key': 'k',
                                    'contact_zip': '27519', 'contact_city': 'Cary'}
    res = missions.release(mid, 'approve', {'id': 'mom', 'role': 'parent'})
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
    missions.release(mid, 'approve', {'id': 'mom', 'role': 'parent'})
    check(runs[-1]['released'] == {'email': 'fixed@example.com'}, f"the corrected card value is what goes out: {runs[-1]['released']}")
    _reset()
    missions._browse = lambda **kw: _report('needs_release', wanted_fields=['email'])
    mid = _mission()
    missions.step(storage.get_mission(mid))
    res = missions.release(mid, 'decline', {'id': 'mom', 'role': 'parent'})
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
             scenario_approve_reads_the_card_as_it_is_now_and_decline_names_the_card]

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

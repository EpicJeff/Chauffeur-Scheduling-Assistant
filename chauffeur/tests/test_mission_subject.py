"""The planner and Argyle stand inside a subject (spec 2026-10-14 §2).

Pinned here:

Task 4 (scenarios A):
  * `find_in_chauffeur(query, kind, facet, acting_member, spoken)` finds and,
    on a clear winner, reads (context); an empty query is an error, a tie
    reads nothing and offers both;
  * the planner may call it as a READ; it runs as the mission's FINDER (the
    creator, else the parent of record); what is STORED on the transcript is
    only the candidates any adult could see (the others are counted as
    withheld) and never the context; the model gets the full result once, in
    the next prompt only;
  * the `subject` action binds: a manual mission its own fields, a thread
    mission its THREAD (only when unbound); refused for a record the finder
    may not see, a missing record, or an already-bound thread;
  * every step's system prompt carries a fresh ABOUT block for a bound mission
    (an edit between two steps shows), read as the finder; a subject the
    finder may not see reads "not readable here" and nothing of it; ABOUT is
    never stored.

Task 5 appends scenarios B (start_mission_for, focus reuse, dedupe).

Run from chauffeur/:  python tests/test_mission_subject.py
"""
from datetime import date

from harness import check  # noqa: F401
from services import storage, missions, situations
from services import agent_tools_v2 as tools
from test_subjects import _reset, _seed, MOM, DAD, AUNT, KID

PROMPTS = []


def _fresh():
    _reset()
    _seed()
    for t in (storage.chat_channels_table, storage.chat_messages_table):
        t.truncate()
    settings = {'missions_enabled': True, 'llm_gemini_paid_api_key': 'paid', 'llm_gemini_api_key': 'k', 'calendar_ids': ['primary']}
    storage.get_settings = lambda: dict(settings)
    storage.set_app_state(f"mission_calls:{date.today().isoformat()}", {})
    situations.REFRESH_DELAY_S = 0
    situations._pool_call = lambda *a, **k: {}
    missions._post = lambda dm, argyle, body, card=None: {'id': 'm'}
    missions._browse_async = False
    PROMPTS.clear()


def _plan(*actions):
    """Script the planner: each step returns the next action and records the prompts it was given."""
    queue = list(actions)

    def fake(mission, system, user, settings):
        PROMPTS.append({'system': system, 'user': user})
        return queue.pop(0) if queue else {'action': 'ask_user', 'question': 'anything else?'}
    missions._llm = fake


def _mission(created_by='mom', origin=None, **fields):
    mid = storage.add_mission({'goal': 'book dining for the Disney trip', 'origin_kind': 'thread' if origin else 'manual',
                               'origin_ref': origin, 'created_by': created_by, 'tier': 'mission'})
    if fields:
        storage.update_mission(mid, fields)
    return mid


def _step(mid):
    return missions.step(storage.get_mission(mid))


def _steps(mid, name=None):
    rows = storage.get_mission_steps(mid)
    return [s for s in rows if s.get('name') == name] if name else rows


# --- Task 4 ------------------------------------------------------------------

def scenario_find_in_chauffeur_finds_and_reads_a_clear_winner():
    _fresh()
    res = tools.find_in_chauffeur('Disney World', acting_member=MOM)
    check(res['status'] == 'success' and res['candidates'][0]['id'] == 'ev_disney', f"found: {res}")
    check(res['context'] and 'TRIP: Disney World' in res['context'], f"and read: {res['context']}")
    dining = tools.find_in_chauffeur('Disney World', facet='dining', acting_member=MOM)
    check("Chef Mickey's" in dining['context'] and 'Magic Kingdom' not in dining['context'], "a facet reads one part")
    tie = tools.find_in_chauffeur('Disney', acting_member=MOM)
    check(tie['context'] is None and {'ev_disney', 'th1'} <= {c['id'] for c in tie['candidates']}, f"a tie reads nothing: {tie}")
    check(tools.find_in_chauffeur('', acting_member=MOM)['status'] == 'error', "an empty query is an error")
    check(tools.find_in_chauffeur("Kate's", acting_member=KID)['candidates'] == [], "a child finds nothing parents-only")
    only_trips = tools.find_in_chauffeur('Disney', kind='trip', acting_member=MOM)
    check(only_trips['candidates'][0]['id'] == 'ev_disney' and only_trips['context'], "kind narrows to one kind and wins")
    check('find_in_chauffeur' in tools.TOOL_HANDLERS and 'find_in_chauffeur' in tools.TOOL_SCHEMAS
          and any(t['name'] == 'find_in_chauffeur' for t in tools.get_available_tools()), "registered")


def scenario_the_planner_reads_once_and_stores_only_what_any_adult_could_see():
    _fresh()
    check('find_in_chauffeur' in missions.READ_TOOLS, "a READ tool for the planner")
    mid = _mission(created_by='mom')
    _plan({'action': 'tool', 'tool': 'find_in_chauffeur', 'args': {'query': 'Disney World'}},
          {'action': 'tool', 'tool': 'find_in_chauffeur', 'args': {'query': 'Hawaii'}},
          {'action': 'ask_user', 'question': 'which night?'})
    _step(mid)
    stored = _steps(mid, 'find_in_chauffeur')[0]['result_json']
    check(not stored.get('context'), f"the context is never stored: {stored}")
    check(stored.get('candidates') == [] and stored.get('withheld') == 1,
          f"the parents-only trip is not named on a transcript adults can read, only counted: {stored}")
    check('Disney' not in repr(stored), f"not in the stored message either: {stored}")
    _step(mid)
    check("Chef Mickey's" in PROMPTS[1]['user'] and 'ev_disney' in PROMPTS[1]['user'],
          f"the model got the full result (context and id) in the very next prompt:\n{PROMPTS[1]['user'][-800:]}")
    stored2 = _steps(mid, 'find_in_chauffeur')[1]['result_json']
    check([c['id'] for c in stored2.get('candidates') or []] == ['ev_hawaii'], f"a household trip is stored by name: {stored2}")
    _step(mid)
    check("Chef Mickey's" not in PROMPTS[2]['user'], "and only once: the step after does not carry it")
    _plan({'action': 'tool', 'tool': 'find_in_chauffeur', 'args': {'query': ''}})
    row = _step(mid)
    last = _steps(mid)[-1]
    check(row['status'] in ('running', 'waiting_user') and (last.get('result_json') or {}).get('status') == 'error',
          f"an empty query is an error step, never a crash or a bind: {last}")


def scenario_the_subject_action_binds_the_right_row():
    _fresh()
    mid = _mission(created_by='mom')
    _plan({'action': 'subject', 'kind': 'trip', 'id': 'ev_disney'})
    _step(mid)
    m = storage.get_mission(mid)
    check(m['subject_kind'] == 'trip' and m['subject_id'] == 'ev_disney' and m['subject_rev'] == 1, f"a manual mission binds itself: {m}")
    note = _steps(mid, 'subject')
    check(note and note[0]['kind'] == 'note' and note[0]['result_json'].get('title') == 'Disney World', f"noted: {note}")
    tmid = _mission(created_by='mom', origin='th1')
    _plan({'action': 'subject', 'kind': 'trip', 'id': 'ev_disney'})
    _step(tmid)
    t = storage.get_thread('th1')
    check(t['subject_kind'] == 'trip' and t['subject_id'] == 'ev_disney', f"a thread mission binds its thread: {t}")
    check(storage.get_mission(tmid).get('subject_kind') is None, "never its own fields")
    _plan({'action': 'subject', 'kind': 'trip', 'id': 'ev_hawaii'})
    _step(tmid)
    check(storage.get_thread('th1')['subject_id'] == 'ev_disney' and _steps(tmid, 'refused'),
          "an already-bound thread is not rebound by the planner (a person changes it)")
    _plan({'action': 'subject', 'kind': 'trip', 'id': 'nope'})
    nmid = _mission(created_by='mom')
    _step(nmid)
    check(storage.get_mission(nmid).get('subject_kind') is None and _steps(nmid, 'refused'), "a missing record is refused")
    amid = _mission(created_by='aunt')
    _plan({'action': 'subject', 'kind': 'occasion', 'id': 'o1'})
    _step(amid)
    check(storage.get_mission(amid).get('subject_kind') is None and _steps(amid, 'refused'),
          "a record the finder (the adult who started it) may not see is refused")


def scenario_every_step_leads_with_fresh_about():
    _fresh()
    mid = _mission(created_by='mom', subject_kind='trip', subject_id='ev_disney', subject_rev=1)
    _plan({'action': 'tool', 'tool': 'get_occasion', 'args': {}}, {'action': 'ask_user', 'question': 'ok?'})
    _step(mid)
    first = PROMPTS[0]['system']
    check('ABOUT: trip "Disney World"' in first and "Chef Mickey's" in first, f"ABOUT heads the step:\n{first[:600]}")
    check('subject' in first and 'find_in_chauffeur' in first, "the planner is told how to find and bind")
    with storage.db_lock:
        row = storage.trip_metadata_table.all()[0]
        pois = [dict(p, name='Chef Minnie') if p['id'] == 'p2' else p for p in row['pois']]
        storage.trip_metadata_table.update({'pois': pois}, storage.Query().event_id == 'ev_disney')
    _step(mid)
    check('Chef Minnie' in PROMPTS[1]['system'] and "Chef Mickey's" not in PROMPTS[1]['system'],
          "an edit between two steps shows at the next step")
    blob = repr(storage.get_mission_steps(mid))
    check('ABOUT:' not in blob, "ABOUT is never stored on the transcript")
    plain = _mission(created_by='mom')
    _plan({'action': 'ask_user', 'question': 'ok?'})
    _step(plain)
    check('ABOUT:' not in PROMPTS[-1]['system'], "an unbound mission carries no ABOUT")


def scenario_about_is_withheld_when_the_finder_may_not_see():
    _fresh()
    mid = _mission(created_by='dad', subject_kind='list', subject_id='l2', subject_rev=1)
    _plan({'action': 'ask_user', 'question': 'ok?'})
    _step(mid)
    s = PROMPTS[0]['system']
    check('not readable here' in s and 'Kate gifts' not in s,
          f"dad started it; a parent's hand linked it to mom's private list; the planner reads nothing of it:\n{s[:500]}")



# --- Task 5: start_mission_for, focus reuse, dedupe, the chat prompt ----------

from services import triage


def _thread(title, owner='mom', **subject):
    tid = storage.add_thread({'title': title, 'kind': 'project', 'state': 'open', 'owner_member_id': owner, 'created_by': owner})
    if subject:
        storage.update_thread(tid, subject)
    return tid


def scenario_start_mission_for_writes_the_subject_on_the_thread():
    _fresh()
    res = tools.start_mission_for('book dining for the Disney trip', acting_member=MOM, focus_key='conv:1',
                                  subject_kind='trip', subject_id='ev_disney')
    check(res['status'] == 'success', f"started: {res}")
    t = storage.get_thread(res['thread_id'])
    check(t['subject_kind'] == 'trip' and t['subject_id'] == 'ev_disney' and t['subject_rev'] == 1, f"the thread is bound: {t}")
    check(missions.subject_of(storage.get_mission(res['mission_id'])) == ('trip', 'ev_disney', 1), "the mission reads it")
    bad = tools.start_mission_for('fix the fence', acting_member=MOM, focus_key='conv:2', subject_kind='trip', subject_id='nope')
    check(bad['status'] == 'success' and storage.get_thread(bad['thread_id']).get('subject_kind') is None,
          f"a subject that does not exist is dropped, the mission still starts: {bad}")
    hidden = tools.start_mission_for('order the cake', acting_member=AUNT, focus_key='conv:3', subject_kind='occasion', subject_id='o1')
    check(hidden['status'] == 'success' and storage.get_thread(hidden['thread_id']).get('subject_kind') is None,
          "a subject the asker may not see is dropped, never bound")
    schema = next(t for t in tools.get_available_tools() if t['name'] == 'start_mission_for')['parameters']['properties']
    check('subject_kind' in schema and 'subject_id' in schema, f"the tool takes the pair: {list(schema)}")


def scenario_a_focus_thread_is_reused_only_on_a_compatible_subject():
    _fresh()
    plain = _thread('Trip planning')
    triage.set_focus('conv:1', 'thread', plain, 'Trip planning')
    res = tools.start_mission_for('book dining for the Disney trip', acting_member=MOM, focus_key='conv:1',
                                  subject_kind='trip', subject_id='ev_disney')
    check(res['thread_id'] == plain and storage.get_thread(plain)['subject_id'] == 'ev_disney',
          f"an unbound focus thread is reused and bound: {res}")
    hawaii = _thread('Hawaii stuff', subject_kind='trip', subject_id='ev_hawaii', subject_rev=1)
    triage.set_focus('conv:2', 'thread', hawaii, 'Hawaii stuff')
    res = tools.start_mission_for('book dining for the Disney trip again', acting_member=MOM, focus_key='conv:2',
                                  subject_kind='trip', subject_id='ev_disney')
    check(res['thread_id'] != hawaii and storage.get_thread(hawaii)['subject_id'] == 'ev_hawaii',
          f"a focus thread about another trip is left alone; a new thread opens: {res}")
    check(storage.get_thread(res['thread_id'])['subject_id'] == 'ev_disney', "and the new one is about Disney")
    same = _thread('Disney extras', subject_kind='trip', subject_id='ev_disney', subject_rev=1)
    triage.set_focus('conv:3', 'thread', same, 'Disney extras')
    res = tools.start_mission_for('find character breakfasts', acting_member=MOM, focus_key='conv:3',
                                  subject_kind='trip', subject_id='ev_disney')
    check(res['thread_id'] == same, f"a focus thread about the same trip is reused: {res}")


def scenario_dedupe_needs_the_same_subject_and_the_same_intent():
    _fresh()
    first = tools.start_mission_for('book flights for Disney', acting_member=MOM, focus_key='conv:1',
                                    subject_kind='trip', subject_id='ev_disney')
    other = tools.start_mission_for('book dining for Disney', acting_member=MOM, focus_key='conv:2',
                                    subject_kind='trip', subject_id='ev_disney')
    check(other['status'] == 'success' and other['mission_id'] != first['mission_id'] and 'already' not in other['message'].lower(),
          f"flights and dining on one trip are two pieces of work: {other}")
    again = tools.start_mission_for('book flights to Disney World', acting_member=MOM, focus_key='conv:3',
                                    subject_kind='trip', subject_id='ev_disney')
    check(again['mission_id'] == first['mission_id'] and 'already' in again['message'].lower(),
          f"the same intent on the same trip is the one already under way: {again}")
    hawaii = tools.start_mission_for('book flights for Hawaii', acting_member=MOM, focus_key='conv:4',
                                     subject_kind='trip', subject_id='ev_hawaii')
    check(hawaii['mission_id'] != first['mission_id'], "the same intent on another trip is new work")


def scenario_the_chat_prompt_carries_about_for_a_bound_focus_thread():
    _fresh()
    from services import agent_router
    tid = _thread('Disney dining', subject_kind='trip', subject_id='ev_disney', subject_rev=1)
    triage.set_focus('conv:9', 'thread', tid, 'Disney dining')
    captured = []
    orig = agent_router.call_gemma_with_fallback
    agent_router.call_gemma_with_fallback = lambda prompt, tools_, system_prompt: captured.append(system_prompt) or {'message': 'ok', 'tool_calls': []}
    try:
        agent_router.process_agent_request('what is left to book', source='admin', acting_member=MOM, focus_key='conv:9')
        check(captured and 'ABOUT: trip "Disney World"' in captured[-1] and "Chef Mickey's" in captured[-1],
              f"the focus thread's subject heads the chat:\n{(captured or [''])[-1][-1500:]}")
        check('find_in_chauffeur' in captured[-1] and 'subject_kind' in captured[-1],
              "and Argyle is told to resolve before starting a mission")
        agent_router.process_agent_request('what is left to book', source='admin', acting_member=AUNT, focus_key='conv:9')
        check('Disney World' not in captured[-1], "an adult the trip's audience excludes reads nothing of it")
        plain = _thread('Plain thread')
        triage.set_focus('conv:8', 'thread', plain, 'Plain thread')
        agent_router.process_agent_request('next?', source='admin', acting_member=MOM, focus_key='conv:8')
        check('ABOUT:' not in captured[-1], "an unbound focus thread carries no ABOUT")
    finally:
        agent_router.call_gemma_with_fallback = orig


SCENARIOS = [
    scenario_find_in_chauffeur_finds_and_reads_a_clear_winner,
    scenario_the_planner_reads_once_and_stores_only_what_any_adult_could_see,
    scenario_the_subject_action_binds_the_right_row,
    scenario_every_step_leads_with_fresh_about,
    scenario_about_is_withheld_when_the_finder_may_not_see,
    scenario_start_mission_for_writes_the_subject_on_the_thread,
    scenario_a_focus_thread_is_reused_only_on_a_compatible_subject,
    scenario_dedupe_needs_the_same_subject_and_the_same_intent,
    scenario_the_chat_prompt_carries_about_for_a_bound_focus_thread,
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

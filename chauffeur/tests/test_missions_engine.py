"""Engine behavior with a scripted fake LLM. Storage scenarios first."""
import time
from datetime import date

from harness import check
from services import storage
from services import missions


def _reset():
    storage.missions_table.truncate()
    storage.mission_steps_table.truncate()
    storage.set_app_state(f"mission_calls:{date.today().isoformat()}", {})


def scenario_mission_rows_round_trip():
    _reset()
    mid = storage.add_mission({'goal': 'find a magician', 'origin_kind': 'manual',
                               'created_by': 'mom', 'tier': 'mission'})
    row = storage.get_mission(mid)
    check(row and row['status'] == 'running' and row['step_count'] == 0
          and row['acknowledged_at'] is None,
          "defaults: running, zero steps, unacknowledged")
    storage.add_mission_step(mid, {'kind': 'llm', 'name': 'plan',
                                   'result_json': {'action': 'finish'}})
    storage.add_mission_step(mid, {'kind': 'note', 'name': 'done'})
    steps = storage.get_mission_steps(mid)
    check([s['idx'] for s in steps] == [0, 1], "steps auto-index in order")
    check(storage.update_mission(mid, {'status': 'done'}), "update writes")
    check(storage.get_missions(status='done')[0]['id'] == mid, "status filter")
    check(storage.get_missions(status=['done', 'blocked'])[0]['id'] == mid,
          "list filter")


def scenario_prune_spares_active_and_steps_follow():
    _reset()
    old = storage.add_mission({'goal': 'g', 'origin_kind': 'manual'})
    storage.add_mission_step(old, {'kind': 'note', 'name': 'n'})
    storage.update_mission(old, {'status': 'done', 'finished_at': 1.0})
    live = storage.add_mission({'goal': 'g2', 'origin_kind': 'manual'})
    n = storage.prune_missions(before_ts=2.0)
    check(n == 1 and storage.get_mission(live) and not storage.get_mission(old),
          "prune eats old terminal rows only")
    check(storage.get_mission_steps(old) == [], "pruned mission takes its steps")


def _mk(goal='hire a magician', tier='mission'):
    return storage.add_mission({'goal': goal, 'origin_kind': 'manual',
                                'created_by': 'mom', 'tier': tier})


def _script(*responses):
    """missions._llm replacement that plays canned responses in order."""
    seq = list(responses)
    def fake(mission, system, user, settings):
        return seq.pop(0)
    return fake


def scenario_read_tool_dispatches_and_transcribes():
    _reset()
    mid = _mk()
    calls = {}
    from services import agent_tools
    orig = agent_tools.execute_tool
    agent_tools.execute_tool = lambda n, a: calls.setdefault('call', (n, a)) or {'status': 'ok'}
    missions._llm = _script(
        {'action': 'tool', 'tool': 'get_current_state', 'args': {}},
        {'action': 'finish', 'summary': 'looked'})
    try:
        missions.step(storage.get_mission(mid))
        row = missions.step(storage.get_mission(mid))
    finally:
        agent_tools.execute_tool = orig
    check(calls['call'][0] == 'get_current_state', "read tool really dispatched")
    kinds = [s['kind'] for s in storage.get_mission_steps(mid)]
    check(kinds == ['tool', 'llm'] or kinds == ['tool', 'note', 'llm'] or
          kinds[0] == 'tool', f"transcript records the tool step, got {kinds}")
    check(row['status'] == 'done' and row['summary'] == 'looked', "finish closes")


def scenario_write_tool_becomes_proposal_never_executes():
    _reset()
    mid = _mk()
    executed = {}
    from services import agent_tools
    orig = agent_tools.execute_tool
    agent_tools.execute_tool = lambda n, a: executed.setdefault(n, a) or {'status': 'ok'}
    missions._llm = _script(
        {'action': 'propose', 'tool': 'add_errand', 'args': {'name': 'pick up cake'},
         'summary': 'Add cake pickup errand', 'why': 'party needs cake'})
    try:
        missions.step(storage.get_mission(mid))
    finally:
        agent_tools.execute_tool = orig
    check(not executed, "engine executed NOTHING")
    steps = storage.get_mission_steps(mid)
    prop = [s for s in steps if s['kind'] == 'proposal']
    check(len(prop) == 1 and prop[0]['result_json'].get('proposal_id'),
          "write intent minted a real proposal row")
    from services import storage as _st
    check(storage.get_mission(mid)['status'] == 'running', "mission keeps going")


def scenario_excluded_and_unknown_tools_bounce():
    _reset()
    mid = _mk()
    missions._llm = _script(
        {'action': 'propose', 'tool': 'send_direct_message', 'args': {}},
        {'action': 'tool', 'tool': 'add_errand', 'args': {}},
        {'action': 'give_up', 'reason': 'nope'})
    missions.step(storage.get_mission(mid))
    missions.step(storage.get_mission(mid))
    row = missions.step(storage.get_mission(mid))
    notes = [s for s in storage.get_mission_steps(mid) if s['kind'] == 'note']
    check(len(notes) >= 2, "DM propose and write-as-read both bounced to notes")
    check(row['status'] == 'blocked' and row['error'] == 'nope', "give_up blocks")


def scenario_ask_user_pauses():
    _reset()
    mid = _mk()
    missions._llm = _script({'action': 'ask_user', 'question': 'What is the budget?'})
    row = missions.step(storage.get_mission(mid))
    check(row['status'] == 'waiting_user', "ask pauses the mission")
    ask = [s for s in storage.get_mission_steps(mid) if s['kind'] == 'ask']
    check(ask and ask[0]['result_json']['question'] == 'What is the budget?',
          "the question is on the transcript")


def scenario_transient_error_waits_hard_errors_block():
    _reset()
    mid = _mk()
    missions._llm = _script({'error': '429 quota', 'transient': True})
    row = missions.step(storage.get_mission(mid))
    check(row['status'] == 'waiting_retry' and row['retry_at'], "transient = pause")
    storage.update_mission(mid, {'status': 'running', 'retry_at': None})
    missions._llm = _script({'error': 'boom', 'transient': False},
                            {'error': 'boom', 'transient': False},
                            {'error': 'boom', 'transient': False})
    missions.step(storage.get_mission(mid))
    missions.step(storage.get_mission(mid))
    row = missions.step(storage.get_mission(mid))
    check(row['status'] == 'blocked' and 'boom' in row['error'],
          "three straight hard errors give up honestly")


def scenario_step_cap_blocks():
    _reset()
    mid = _mk()
    storage.update_mission(mid, {'step_count': missions.CAPS_DEFAULT['steps']})
    missions._llm = _script({'action': 'finish', 'summary': 'x'})
    row = missions.step(storage.get_mission(mid))
    check(row['status'] == 'blocked' and 'cap' in row['error'],
          "step cap ends the mission before another LLM call")


def scenario_read_tools_exist_in_registry():
    from services import agent_tools
    missing = missions.READ_TOOLS - set(agent_tools.TOOL_HANDLERS)
    check(not missing, f"READ_TOOLS all real, missing: {missing}")
    check('send_direct_message' not in missions.proposable_tools()
          and 'send_direct_message' not in missions.READ_TOOLS,
          "DMs unreachable in any form")


def scenario_propose_widens_gate_for_non_admin_tool():
    """The propose test elsewhere uses add_errand, which is already in
    chat_actions.ADMIN_ACTIONS -- that suite would pass even if extra_allowed
    did nothing. start_drive is a real registry tool that is NOT in
    ADMIN_ACTIONS, so only the widened gate can let it become a proposal."""
    _reset()
    mid = _mk()
    missions._llm = _script(
        {'action': 'propose', 'tool': 'start_drive', 'args': {},
         'summary': 'Start the drive', 'why': 'time to go'})
    row = missions.step(storage.get_mission(mid))
    steps = storage.get_mission_steps(mid)
    prop = [s for s in steps if s['kind'] == 'proposal']
    check(len(prop) == 1 and prop[0]['result_json'].get('proposal_id'),
          "a tool outside ADMIN_ACTIONS still proposes via extra_allowed")
    check(row['status'] == 'running', "mission keeps going after a good proposal")
    from services import chat_actions
    bare = chat_actions.create_action_proposal('start_drive', 's', {})
    check(bare['status'] == 'error',
          "chat's own funnel (no extra_allowed) still refuses the same tool")


def scenario_draft_declines_on_ambiguous_title():
    _reset()
    storage.threads_table.truncate()
    storage.add_thread({'title': 'Roof repair'})
    storage.add_thread({'title': 'Roof repair'})
    mid = _mk()
    from services import threads as _threads
    orig = _threads.draft_message
    calls = []
    _threads.draft_message = lambda tid, intent='': calls.append((tid, intent)) or {'status': 'ok'}
    missions._llm = _script({'action': 'draft', 'thread_title': 'Roof repair',
                             'intent': 'ask for a status update'})
    try:
        missions.step(storage.get_mission(mid))
    finally:
        _threads.draft_message = orig
    check(not calls, "an ambiguous title never reaches draft_message")
    notes = [s for s in storage.get_mission_steps(mid) if s['kind'] == 'note']
    check(notes, "the tie is recorded as a declined note")


def scenario_draft_by_title_dispatches_once():
    _reset()
    storage.threads_table.truncate()
    tid = storage.add_thread({'title': 'Deck permit'})
    mid = _mk()
    from services import threads as _threads
    orig = _threads.draft_message
    calls = []
    def fake_draft(t_id, intent=''):
        calls.append((t_id, intent))
        return {'status': 'ok', 'subject': 'Following up', 'body': 'Hi there'}
    _threads.draft_message = fake_draft
    missions._llm = _script({'action': 'draft', 'thread_title': 'Deck permit',
                             'intent': 'ask for a status update'})
    try:
        missions.step(storage.get_mission(mid))
    finally:
        _threads.draft_message = orig
    check(calls == [(tid, 'ask for a status update')],
          f"draft_message called once, on the right thread, got {calls}")
    drafts = [s for s in storage.get_mission_steps(mid) if s['kind'] == 'draft']
    check(len(drafts) == 1, "draft step recorded")


def scenario_draft_origin_thread_wins_over_decoy():
    _reset()
    storage.threads_table.truncate()
    origin = storage.add_thread({'title': 'Fence quote'})
    storage.add_thread({'title': 'Fence quote'})  # same-titled decoy
    mid = storage.add_mission({'goal': 'follow up on the fence quote',
                               'origin_kind': 'thread', 'origin_ref': origin,
                               'created_by': 'mom', 'tier': 'mission'})
    from services import threads as _threads
    orig = _threads.draft_message
    calls = []
    def fake_draft(t_id, intent=''):
        calls.append(t_id)
        return {'status': 'ok', 'subject': 's', 'body': 'b'}
    _threads.draft_message = fake_draft
    missions._llm = _script({'action': 'draft', 'thread_title': 'Fence quote',
                             'intent': 'nudge'})
    try:
        missions.step(storage.get_mission(mid))
    finally:
        _threads.draft_message = orig
    check(calls == [origin], f"the origin thread wins over a same-titled decoy, got {calls}")


def scenario_research_action_dispatches_and_records():
    _reset()
    mid = _mk()
    from services import web
    orig = web.research
    calls = []
    def fake_research(question, **kw):
        calls.append(question)
        return {'status': 'ok', 'answer': 'x', 'facts': [], 'sources': []}
    web.research = fake_research
    missions._llm = _script({'action': 'research', 'question': 'best local magician'})
    try:
        missions.step(storage.get_mission(mid))
    finally:
        web.research = orig
    check(calls == ['best local magician'], "research question passed through")
    tool_steps = [s for s in storage.get_mission_steps(mid)
                  if s['kind'] == 'tool' and s['name'] == 'research']
    check(len(tool_steps) == 1 and tool_steps[0]['result_json'].get('answer') == 'x',
          "research step recorded with the result")


def scenario_pro_cap_exhausted_pauses_without_calling_llm():
    _reset()
    mid = _mk()
    storage.set_app_state(f"mission_calls:{date.today().isoformat()}",
                          {'pro': missions.CAPS_DEFAULT['pro_calls']})
    def _must_not_call(*a, **kw):
        raise AssertionError("_llm must not be called when the pro budget is exhausted")
    missions._llm = _must_not_call
    before = storage.get_mission(mid)['step_count']
    row = missions.step(storage.get_mission(mid))
    check(row['status'] == 'waiting_retry', "budget exhaustion pauses, doesn't error")
    check(row['retry_at'] is not None and abs(row['retry_at'] - (time.time() + 1800)) < 10,
          "retry_at is ~30 minutes out")
    check(row['step_count'] == before, "step_count untouched -- no LLM call happened")


def _enable(extra=None):
    s = {'missions_enabled': True, 'llm_gemini_api_key': 'FREE',
         'llm_gemini_paid_api_key': 'PAID'}
    s.update(extra or {})
    storage.get_settings = lambda: s      # harness already stubs get_settings
    return s


def scenario_launch_gates():
    _reset()
    storage.get_settings = lambda: {}
    disabled = missions.launch('x')
    check(disabled['status'] == 'disabled', "OFF means off")
    check(disabled.get('message'), f"a disabled launch says so, got {disabled}")
    _enable({'llm_gemini_paid_api_key': ''})
    check(missions.launch('x')['status'] == 'no_key',
          "mission tier without a paid key refuses at launch")
    _enable()
    empty = missions.launch('  ')
    check(empty['status'] == 'empty', "blank goal refused")
    check(empty.get('message'), f"an empty-goal launch says so, got {empty}")
    got = missions.launch('plan the party', created_by='mom')
    check(got['status'] == 'launched' and storage.get_mission(got['mission_id']),
          "launch creates a running mission")
    check(got.get('message'), f"a launched mission says so too, got {got}")
    storage.set_app_state(f"mission_calls:{date.today().isoformat()}",
                          {'launch': missions.CAPS_DEFAULT['launch']})
    check(missions.launch('another')['status'] == 'capped', "daily launch cap")


def scenario_launch_seeds_thread_context():
    """Review finding: a thread-origin mission shipped blind — its only clue
    was '(Opened from thread <id>)', an opaque id the model cannot use. Both
    thread doorways (the button and chat's fuzzy title match) funnel through
    launch(), so fixing it here covers both at once."""
    _reset()
    _enable()
    tid = storage.add_thread({
        'title': 'Pool guy', 'goal': 'get the pump fixed before summer',
        'kind': 'vendor', 'state': 'open',
        'counterparty_name': 'Ace Pools', 'counterparty_email': 'ace@example.com',
        'next_action': 'call them back', 'next_action_at': '2026-09-10',
        'history': [
            {'kind': 'opened', 'text': 'Opened: Pool guy', 'ts': 1},
            {'kind': 'note', 'text': 'Left a voicemail Tuesday', 'ts': 2},
            {'kind': 'advance', 'text': 'Next: call them back by 2026-09-10', 'ts': 3},
        ],
    })
    got = missions.launch('get the pool serviced', origin_kind='thread',
                          origin_ref=tid, created_by='mom')
    check(got['status'] == 'launched', f"thread-origin launch succeeds, got {got}")
    steps = storage.get_mission_steps(got['mission_id'])
    ctx = [s for s in steps if s['kind'] == 'note' and s['name'] == 'thread_context']
    check(len(ctx) == 1, f"exactly one thread_context note seeded, got {steps}")
    r = ctx[0]['result_json']
    check(r.get('title') == 'Pool guy' and r.get('goal') == 'get the pump fixed before summer',
          f"title + goal carried over, got {r}")
    check(r.get('counterparty', {}).get('counterparty_name') == 'Ace Pools'
          and r.get('counterparty', {}).get('counterparty_email') == 'ace@example.com',
          f"counterparty carried over, got {r.get('counterparty')}")
    check(r.get('state') == 'open' and r.get('next_action') == 'call them back'
          and r.get('next_action_at') == '2026-09-10',
          f"state + next action carried over, got {r}")
    tail = r.get('history_tail') or []
    check(len(tail) == 3 and tail[-1]['kind'] == 'advance'
          and 'call them back' in tail[-1]['text'],
          f"history tail present, oldest-first, got {tail}")
    # A 'manual' or unmatched-chat origin must NOT try to seed anything --
    # no thread means no context to seed, and it must not crash the launch.
    plain = missions.launch('unrelated goal', created_by='mom')
    check(plain['status'] == 'launched', f"manual launch unaffected, got {plain}")
    plain_steps = storage.get_mission_steps(plain['mission_id'])
    check(not any(s['kind'] == 'note' and s['name'] == 'thread_context'
                 for s in plain_steps),
          "a manual-origin mission gets no thread_context note")


def scenario_tick_advances_one_mission_serially():
    _reset()
    _enable()
    storage.set_app_state(f"mission_calls:{date.today().isoformat()}", {})
    a = missions.launch('first', created_by='mom')['mission_id']
    b = missions.launch('second', created_by='mom')['mission_id']
    seen = []
    def fake(mission, system, user, settings):
        seen.append(mission['id'])
        return {'action': 'ask_user', 'question': 'q?'}
    missions._llm = fake
    missions.tick()
    check(seen and all(x == seen[0] for x in seen),
          f"one tick works ONE mission only, got {seen}")
    check(len(seen) == 1, "ask_user leaves running-state, tick stops advancing")
    other = b if seen[0] == a else a
    check(storage.get_mission(other)['status'] == 'running',
          "the queued mission waits its turn untouched")


def scenario_tick_advances_exactly_one_step_per_beat():
    """Controller ruling (mission-engine flip review): STEPS_PER_TICK dropped
    3 -> 1 so a running mission can never make the family push loop's other
    30s beats (runway/presence/prep) wait behind it. Scripted action keeps
    the mission RUNNING (unlike ask_user in the serial scenario above, which
    already stops the loop after one step regardless of the cap) so this
    actually distinguishes 1 from 3 -- it would have failed at the old
    default of 3 before this fix."""
    _reset()
    _enable()
    mid = _mk()
    tool_call = {'action': 'tool', 'tool': 'get_current_state', 'args': {}}
    missions._llm = _script(tool_call, tool_call, tool_call)
    out = missions.tick()
    check(out['advanced'] == 1, f"exactly one step per tick, got {out}")
    row = storage.get_mission(mid)
    check(row['status'] == 'running' and row['step_count'] == 1,
          f"mission stays running after its one step, got {row}")


def scenario_tick_promotes_due_retries_and_respects_disabled():
    _reset()
    storage.get_settings = lambda: {}
    check(missions.tick()['status'] == 'disabled', "tick is inert when OFF")
    _enable()
    mid = _mk()
    storage.update_mission(mid, {'status': 'waiting_retry', 'retry_at': 1.0})
    missions._llm = _script({'action': 'finish', 'summary': 'ok'})
    missions.tick()
    check(storage.get_mission(mid)['status'] == 'done',
          "a due retry re-enters the loop and can finish")


def scenario_mission_findings_emit_and_hush():
    _reset()
    from services import watchers
    import datetime as _dt
    now = _dt.datetime.now()
    done = _mk(); storage.update_mission(done, {'status': 'done',
                                                'summary': '2 proposals ready'})
    waiting = _mk('q'); storage.update_mission(waiting, {'status': 'waiting_user'})
    acked = _mk('a'); storage.update_mission(acked, {'status': 'done',
                                                     'acknowledged_at': 1.0})
    rows = watchers._mission_states(now)
    kinds = sorted(f.kind for f in rows)
    check(kinds == ['mission_done', 'mission_waiting'],
          f"done + waiting page, acknowledged stays quiet, got {kinds}")
    for k in ('mission_done', 'mission_blocked', 'mission_waiting'):
        check(k in watchers.SCANNED_KINDS, f"{k} is a scanned kind")
    line = next(f.line for f in rows if f.kind == 'mission_done')
    check('proposal' in line, "the done line carries the next action")



def scenario_prompt_carries_home_and_endgame_rules():
    _reset()
    storage.members_table.truncate()
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'kid', 'name': 'Lily', 'role': 'child'})
    storage.add_member({'id': 'gone', 'name': 'Ghost', 'role': 'adult',
                        'status': 'archived'})
    mid = _mk()
    seen = {}
    storage.get_settings = lambda: {'missions_enabled': True,
                                    'llm_gemini_api_key': 'F',
                                    'llm_gemini_paid_api_key': 'P',
                                    'home_location': '123 Maple Ct, Cary, NC'}
    def fake(mission, system, user, settings):
        seen['system'] = system
        return {'action': 'finish', 'summary': 'x'}
    missions._llm = fake
    missions.step(storage.get_mission(mid))
    sp = seen['system']
    check('123 Maple Ct, Cary, NC' in sp, "home address rides the prompt")
    check('never guess a city' in sp, "location rule stated")
    check('Mom (parent)' in sp and 'Lily (child)' in sp,
          "family roster rides the prompt")
    check('Ghost' not in sp, "archived members stay off the roster")
    check('NEVER finish with a question' in sp, "ask-over-finish rule stated")
    check('ask_user EARLY' in sp, "ask-when-missing rule stated")
    check('PLAIN TEXT' in sp, "plain-text rule stated")
    check('create_thread' in sp, "outreach guidance names create_thread")


def scenario_prompt_omits_home_when_unset():
    _reset()
    mid = _mk()
    seen = {}
    storage.get_settings = lambda: {'missions_enabled': True,
                                    'llm_gemini_api_key': 'F',
                                    'llm_gemini_paid_api_key': 'P'}
    missions._llm = lambda m, sy, u, st: seen.update({'system': sy}) or {
        'action': 'finish', 'summary': 'x'}
    missions.step(storage.get_mission(mid))
    check('never guess a city' not in seen['system'],
          "no address = no home line, not an empty claim")


def scenario_create_thread_proposal_round_trip():
    _reset()
    storage.threads_table.truncate()
    storage.members_table.truncate()
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    mid = _mk()
    missions._llm = _script(
        {'action': 'propose', 'tool': 'create_thread',
         'args': {'title': "Ana's Cleaning — biweekly", 'kind': 'vendor',
                  'counterparty_name': 'Ana', 'goal': 'book a recurring clean'},
         'summary': "Open a thread with Ana's Cleaning", 'why': 'chosen vendor'})
    missions.step(storage.get_mission(mid))
    prop = [s for s in storage.get_mission_steps(mid) if s['kind'] == 'proposal'][0]
    pid = prop['result_json'].get('proposal_id')
    check(pid, "create_thread minted a real proposal")
    check(not storage.get_threads(include_closed=True),
          "no thread exists before approval")
    from services import chat_actions
    res = chat_actions.act_on_proposal(pid, 'approve',
                                       {'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    check(res.get('status') == 'success', f"approve executes on the rail, got {res}")
    ts = storage.get_threads(include_closed=True)
    check(len(ts) == 1 and ts[0]['title'] == "Ana's Cleaning — biweekly"
          and (ts[0].get('counterparty_name') or '') == 'Ana',
          "the thread exists with its counterparty")
    check('create_thread' not in missions.READ_TOOLS,
          "create_thread is write-classed (propose-only)")

if __name__ == '__main__':
    scenario_mission_rows_round_trip()
    scenario_prune_spares_active_and_steps_follow()
    scenario_read_tool_dispatches_and_transcribes()
    scenario_write_tool_becomes_proposal_never_executes()
    scenario_excluded_and_unknown_tools_bounce()
    scenario_ask_user_pauses()
    scenario_transient_error_waits_hard_errors_block()
    scenario_step_cap_blocks()
    scenario_read_tools_exist_in_registry()
    scenario_propose_widens_gate_for_non_admin_tool()
    scenario_draft_declines_on_ambiguous_title()
    scenario_draft_by_title_dispatches_once()
    scenario_draft_origin_thread_wins_over_decoy()
    scenario_research_action_dispatches_and_records()
    scenario_pro_cap_exhausted_pauses_without_calling_llm()
    scenario_launch_gates()
    scenario_launch_seeds_thread_context()
    scenario_tick_advances_one_mission_serially()
    scenario_tick_advances_exactly_one_step_per_beat()
    scenario_tick_promotes_due_retries_and_respects_disabled()
    scenario_mission_findings_emit_and_hush()
    scenario_prompt_carries_home_and_endgame_rules()
    scenario_prompt_omits_home_when_unset()
    scenario_create_thread_proposal_round_trip()
    print("test_missions_engine OK")

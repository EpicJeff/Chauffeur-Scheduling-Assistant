"""The whole-branch review's eleven findings on the subjects arc, each pinned
by running the real path (Codex adversarial review, 2026-10-14). The promise
under all of them is the spec's: a situation bound to a record never widens
who may read about that record, anywhere it surfaces.

  F1  PATCH /api/threads/{id} cannot set or clear subject fields.
  F2  Changing or clearing a subject never WIDENS who may see the situation:
      every record it was ever about still narrows it (subject_history).
  F3  A planner answer computed about the old subject is discarded when the
      subject changed while the model was thinking.
  F4  A thread about a thread inherits that thread's subject audience,
      transitively; a cycle fails closed (only the owner keeps it).
  F5  A voice-shared thread about a record that may not be said aloud is not
      speakable; an occasion read aloud never names a linked private list.
  F6  Argyle's list_threads tool and start_mission_for's dedupe and focus
      reuse never show or reuse a thread the asker may not see.
  F7  A proposal a bound mission makes carries the mission's audience: the
      global approvals list and the approve/dismiss endpoint apply it.
  F8  In a group channel, ABOUT is added only when every member may see it.
  F9  The Mind's snapshot leaves out threads whose record is not for the wall.
  F10 A lookup's withheld records reach an UNBOUND mission's model as kind and
      id only (never title or context); binding one makes ABOUT read it.
  F11 Argyle's chat actually dispatches find_in_chauffeur as the speaker.

Run from chauffeur/:  python tests/test_subject_hardening.py
"""
from harness import check  # noqa: F401
from services import storage, missions, situations, subjects, triage
from services import agent_tools_v2 as tools
from test_mission_subject import _fresh, _plan, _mission, _step, _steps, _thread, PROMPTS
from test_subject_audience import _as
from test_subjects import MOM, DAD, AUNT, KID


def _bound_thread(title, kind, sid, owner='mom'):
    return _thread(title, owner=owner, subject_kind=kind, subject_id=sid, subject_rev=1)


def scenario_f1_patch_cannot_touch_subject_fields():
    _fresh()
    import main
    tid = _bound_thread('Kate party', 'occasion', 'o1')
    main.patch_thread(tid, body={'subject_kind': None, 'subject_id': None, 'subject_rev': 9, 'title': 'Kate party plans',
                                 'member_id': 'mom'}, request=_as('mom'))
    t = storage.get_thread(tid)
    check(t['subject_kind'] == 'occasion' and t['subject_id'] == 'o1' and t['subject_rev'] == 1,
          f"the generic edit ignores subject fields: {t}")
    check(t['title'] == 'Kate party plans', "and still edits what it edits")


def scenario_f2_retarget_never_widens_the_audience():
    _fresh()
    tid = _bound_thread('Kate party', 'occasion', 'o1')
    mid = _mission(created_by='mom', origin=tid)
    check(not situations.can_see('thread', storage.get_thread(tid), AUNT), "parents-only to start")
    res = subjects.retarget('thread', tid, None, None, MOM)
    check(res['status'] == 'success', f"unlinked: {res}")
    check(not situations.can_see('thread', storage.get_thread(tid), AUNT), "unlinking does not publish the old history to the adult")
    check(not situations.can_see('mission', storage.get_mission(mid), AUNT), "nor its mission's transcript")
    subjects.retarget('thread', tid, 'occasion', 'o2', MOM)
    check(not situations.can_see('thread', storage.get_thread(tid), AUNT), "retargeting to a household record does not either")
    check(situations.view('thread', tid, MOM)['subject']['id'] == 'o2', "the chip shows the current record")
    fresh = _bound_thread('Thanksgiving', 'occasion', 'o2')
    check(situations.can_see('thread', storage.get_thread(fresh), AUNT), "a thread only ever about a household record is the adult's")


def scenario_f3_a_stale_planner_answer_is_discarded():
    _fresh()
    tid = _bound_thread('Disney dining', 'trip', 'ev_disney')
    mid = _mission(created_by='mom', origin=tid)
    calls = []
    missions._browse = lambda **kw: calls.append(kw) or {'outcome': 'done', 'text': 'ok', 'learned': {}, 'stopped_at': '', 'wanted_fields': [],
                                                        'turns': 1, 'tokens_in': 1, 'tokens_out': 1, 'seconds': 1, 'screenshots': [], 'filled': {}}

    def thinking_while_retargeted(mission, system, user, settings):
        subjects.retarget('thread', tid, 'trip', 'ev_hawaii', MOM)     # a parent changes it mid-thought
        return {'action': 'browse', 'goal': 'book Be Our Guest', 'site': 'disneyworld.disney.go.com'}
    missions._llm = thinking_while_retargeted
    _step(mid)
    check(not calls and not [s for s in _steps(mid) if s['kind'] == 'browse'], "the Disney browse never starts under Hawaii")
    check(_steps(mid, 'stale_plan'), f"a note says why: {[s['name'] for s in _steps(mid)]}")
    check(storage.get_mission(mid)['status'] == 'running', "the mission simply plans again")


def scenario_f4_a_thread_about_a_thread_inherits_its_audience():
    _fresh()
    inner = _bound_thread('Gift ideas', 'list', 'l2')
    outer = _bound_thread('Gift logistics', 'thread', inner)
    check(not situations.can_see('thread', storage.get_thread(outer), AUNT), "the adult may not see the inner thread's private list")
    check(not situations.can_see('thread', storage.get_thread(outer), DAD), "nor dad, whom the list excludes")
    check(situations.can_see('thread', storage.get_thread(outer), MOM), "mom may")
    a = _thread('Loop A', owner='aunt')
    b = _thread('Loop B', owner='aunt')
    storage.update_thread(a, {'subject_kind': 'thread', 'subject_id': b, 'subject_rev': 1})
    storage.update_thread(b, {'subject_kind': 'thread', 'subject_id': a, 'subject_rev': 1})
    check(situations.can_see('thread', storage.get_thread(a), MOM) is False, "a cycle fails closed")
    check(situations.can_see('thread', storage.get_thread(a), AUNT) is True, "except for the owner, who keeps her row")


def scenario_f5_spoken_safety_is_transitive():
    _fresh()
    tid = _bound_thread('Kate gift run', 'list', 'l2')
    storage.update_thread(tid, {'voice_shared': True})
    check(subjects.spoken_safe('thread', storage.get_thread(tid)) is False, "voice-shared, but about a private list: not speakable")
    out = tools.find_in_chauffeur('Kate gift run', kind='thread', acting_member=MOM, spoken=True)
    check(out['candidates'] == [] and not out['context'], f"never found aloud: {out}")
    storage.add_shopping_list({'id': 'l3', 'name': 'Pie secret', 'audience': 'private', 'shared_with': ['mom'], 'occasion_id': 'o2'})
    aloud = subjects.context('occasion', 'o2', MOM, spoken=True)
    check(aloud and 'Pie secret' not in aloud, f"a household occasion read aloud never names its private list:\n{aloud}")
    check('Pie secret' in subjects.context('occasion', 'o2', MOM), "by hand, to mom, it does")


def scenario_f6_argyle_never_lists_or_reuses_a_hidden_thread():
    _fresh()
    hidden = _bound_thread('Kate surprise party', 'occasion', 'o1')
    mid = _mission(created_by='mom', origin=hidden)
    storage.update_mission(mid, {'goal': 'order the cake'})
    shown = tools.list_threads(acting_member=AUNT).get('message') or ''
    check('surprise' not in shown, f"the adult's thread list leaves it out:\n{shown}")
    check('surprise' in (tools.list_threads(acting_member=MOM).get('message') or ''), "mom's has it")
    res = tools.start_mission_for('order the cake', acting_member=AUNT, focus_key='conv:aunt')
    check(res['status'] == 'success' and res['mission_id'] != mid and 'surprise' not in res['message'],
          f"no 'already under way' that names a thread she may not see: {res}")
    check(res['thread_id'] != hidden, "and never her work on it")
    quiet = _bound_thread('Kate surprise budget', 'occasion', 'o1')
    triage.set_focus('conv:aunt2', 'thread', quiet, 'Kate surprise budget')
    res = tools.start_mission_for('find balloons', acting_member=AUNT, focus_key='conv:aunt2')
    check(res['thread_id'] != quiet, f"a focus she may not see is not reused: {res}")


def scenario_f7_a_bound_missions_proposal_carries_its_audience():
    _fresh()
    import main
    from fastapi import HTTPException
    mid = _mission(created_by='mom', subject_kind='list', subject_id='l2', subject_rev=1)
    _plan({'action': 'propose', 'tool': 'add_shopping_items', 'args': {'items': ['engraved ring']}, 'summary': 'Add the engraved ring', 'why': 'gift'})
    _step(mid)
    prop = [s for s in _steps(mid) if s['kind'] == 'proposal']
    check(prop and prop[0]['result_json'].get('proposal_id'), f"the planner proposed: {[s['name'] for s in _steps(mid)]}")
    pid = prop[0]['result_json']['proposal_id']
    row = storage.get_action_proposal(pid)
    check(row.get('origin_kind') == 'mission' and row.get('origin_id') == mid, f"the proposal names its mission: {row}")
    dads = [r['id'] for r in main.list_action_proposals(request=_as('dad'))]
    check(pid not in dads, "dad, whom the private list excludes, does not see it among the approvals")
    check(pid in [r['id'] for r in main.list_action_proposals(request=_as('mom'))], "mom does")
    # Project access spec §4: a hidden record answers exactly like a missing
    # one. For action proposals that is the existing missing reply (access
    # rule follow-up A, ruling B4), never a 403 or a different shape.
    hidden_reply = main.act_on_action_proposal(pid, main.ActionProposalAct(act='dismiss', member_id='dad'),
                                               background_tasks=None, request=_as('dad'))
    missing_reply = main.act_on_action_proposal('no-such-proposal', main.ActionProposalAct(act='dismiss', member_id='dad'),
                                                background_tasks=None, request=_as('dad'))
    check(hidden_reply == missing_reply and hidden_reply.get('status') == 'error',
          f"dad may not act on it either, and learns nothing: {hidden_reply} vs {missing_reply}")
    check(storage.get_action_proposal(pid)['status'] == 'proposed', "untouched")


def scenario_f8_a_group_channel_gets_about_only_when_everyone_may_see_it():
    _fresh()
    from services import agent_router
    tid = _bound_thread('Kate party', 'occasion', 'o1')
    mixed = storage.get_or_create_group(['mom', 'aunt'], 'Mom and Jo')
    parents = storage.get_or_create_group(['mom', 'dad'], 'Parents')
    captured = []
    orig = agent_router.call_gemma_with_fallback
    agent_router.call_gemma_with_fallback = lambda prompt, tools_, system_prompt: captured.append(system_prompt) or {'message': 'ok', 'tool_calls': []}
    try:
        triage.set_focus(f"channel:{mixed['id']}", 'thread', tid, 'Kate party')
        agent_router.process_agent_request('what is left?', source='family', acting_member=MOM, focus_key=f"channel:{mixed['id']}")
        check("Kate's 10th birthday" not in captured[-1] and 'ABOUT:' not in captured[-1],
              "a channel with an adult the party excludes: the answer is posted there, so no ABOUT")
        triage.set_focus(f"channel:{parents['id']}", 'thread', tid, 'Kate party')
        agent_router.process_agent_request('what is left?', source='family', acting_member=MOM, focus_key=f"channel:{parents['id']}")
        check('ABOUT: occasion "Kate\'s 10th birthday"' in captured[-1], "a channel of parents only: ABOUT")
    finally:
        agent_router.call_gemma_with_fallback = orig


def scenario_f9_the_minds_snapshot_leaves_out_threads_not_for_the_wall():
    _fresh()
    from services import mind
    _bound_thread('Kate surprise party', 'occasion', 'o1')
    _thread('Gutter cleaning quote')
    snap = mind.snapshot()
    check('Gutter cleaning quote' in snap, "an unbound thread is in the snapshot, as before")
    check('Kate surprise party' not in snap, "a thread about a parents-only party is not (its insights reach the wall)")


def scenario_f10_an_unbound_mission_sees_withheld_records_as_ids_only():
    _fresh()
    mid = _mission(created_by='mom')
    _plan({'action': 'tool', 'tool': 'find_in_chauffeur', 'args': {'query': 'Kate gifts'}},
          {'action': 'subject', 'kind': 'list', 'id': 'l2'},
          {'action': 'ask_user', 'question': 'which shop?'})
    _step(mid)
    _step(mid)
    nxt = PROMPTS[1]['user']
    check("'l2'" in nxt or '"l2"' in nxt, f"the model gets the id to bind:\n{nxt[-600:]}")
    check('Kate gifts' not in nxt, "but not the title while the mission is unbound (its next words would land on an adult-readable transcript)")
    check(storage.get_mission(mid)['subject_id'] == 'l2', "it binds")
    _step(mid)
    check('ABOUT: list "Kate gifts"' in PROMPTS[2]['system'], "and from then on reads it through ABOUT")
    hm = _mission(created_by='mom')
    _plan({'action': 'tool', 'tool': 'find_in_chauffeur', 'args': {'query': 'Hawaii'}}, {'action': 'ask_user', 'question': 'ok?'})
    _step(hm)
    _step(hm)
    check('TRIP: Hawaii' in PROMPTS[-1]['user'], "a record any adult may see still reads in full")


def scenario_f11_chat_dispatches_find_in_chauffeur_as_the_speaker():
    _fresh()
    from services import agent_router
    seen = []
    orig_find = tools.find_in_chauffeur

    def spy(*a, **kw):
        seen.append(kw.get('acting_member'))
        return orig_find(*a, **kw)
    tools.find_in_chauffeur = spy
    replies = [{'message': '', 'tool_calls': [{'name': 'find_in_chauffeur', 'arguments': {'query': 'Disney World'}}]},
               {'message': 'Found it.', 'tool_calls': []}]
    orig = agent_router.call_gemma_with_fallback
    agent_router.call_gemma_with_fallback = lambda prompt, tools_, system_prompt: replies.pop(0) if replies else {'message': 'ok', 'tool_calls': []}
    try:
        res = agent_router.process_agent_request('what do we have for Disney?', source='family', acting_member=MOM)
    finally:
        agent_router.call_gemma_with_fallback = orig
        tools.find_in_chauffeur = orig_find
    check(seen and (seen[0] or {}).get('id') == 'mom', f"dispatched as mom: {seen}")
    check('Unknown tool' not in repr(res), f"not an unknown tool: {res}")



# --- Residuals from the scoped re-review of the fix wave ----------------------

def _router_capture(replies):
    from services import agent_router
    seen = []
    orig = agent_router.call_gemma_with_fallback

    def fake(prompt, tools_, system_prompt):
        seen.append((prompt or '') + '\n' + (system_prompt or ''))
        return replies.pop(0) if replies else {'message': 'ok', 'tool_calls': []}
    agent_router.call_gemma_with_fallback = fake
    return seen, lambda: setattr(agent_router, 'call_gemma_with_fallback', orig)


def scenario_r1_a_chat_lookup_in_a_group_channel_answers_for_everyone_in_it():
    _fresh()
    from services import agent_router
    mixed = storage.get_or_create_group(['mom', 'aunt'], 'Mom and Jo')
    parents = storage.get_or_create_group(['mom', 'dad'], 'Parents')
    call = {'name': 'find_in_chauffeur', 'arguments': {'query': "Kate's 10th birthday"}}
    seen, undo = _router_capture([{'message': '', 'tool_calls': [call]}, {'message': 'done', 'tool_calls': []}])
    try:
        agent_router.process_agent_request('what about the party?', source='family', acting_member=MOM, focus_key=f"channel:{mixed['id']}")
    finally:
        undo()
    check(len(seen) >= 2 and "OCCASION: Kate's 10th birthday" not in seen[1],
          "a lookup in a channel with an adult the party excludes reads nothing of it (the answer is posted there)")
    seen, undo = _router_capture([{'message': '', 'tool_calls': [call]}, {'message': 'done', 'tool_calls': []}])
    try:
        agent_router.process_agent_request('what about the party?', source='family', acting_member=MOM, focus_key=f"channel:{parents['id']}")
    finally:
        undo()
    check(len(seen) >= 2 and "OCCASION: Kate's 10th birthday" in seen[1], "a parents-only channel reads it")


def scenario_r2_a_phone_voice_lookup_is_display_only():
    from services import app_voice

    class _Turn(app_voice.Turn):
        def check(self):
            return None
    turn = _Turn(id='t1', member={'id': 'mom', 'role': 'parent'}, token='x', channel={'id': 'c1'})
    turn.before_tool('find_in_chauffeur', {'query': 'Kate gifts'})
    check(turn.speech_safe is False, "a lookup's words stay on the screen, never read aloud on the phone")


def scenario_r3_household_voice_still_names_the_mission_already_under_way():
    _fresh()
    from services import voice_tools
    from services import voice_identity as voice
    ctx = voice.VoiceContext('ha', 'assist_satellite.kitchen', 'r1', 'g1', service_revision=voice._revision(), paired=True)
    # Front door slice 1: the voice door is start_project; the second ask names the first project.
    first = voice_tools.dispatch('start_project', {'goal': 'fix the dishwasher'}, ctx, focus_key='voice:hh1')
    check(first.get('status') == 'success', f"household voice starts it: {first}")
    again = voice_tools.dispatch('start_project', {'goal': 'fix the dishwasher please'}, ctx, focus_key='voice:hh2')
    check(again.get('project_id') == first.get('project_id') and 'already' in (again.get('message') or '').lower(),
          f"the second ask names the first instead of paying for it twice: {again}")


def scenario_r4_a_retarget_between_the_check_and_the_browse_stops_the_browse():
    _fresh()
    tid = _bound_thread('Disney dining', 'trip', 'ev_disney')
    mid = _mission(created_by='mom', origin=tid)
    calls = []
    missions._browse = lambda **kw: calls.append(kw) or {'outcome': 'done', 'text': 'ok', 'learned': {}, 'stopped_at': '', 'wanted_fields': [],
                                                        'turns': 1, 'tokens_in': 1, 'tokens_out': 1, 'seconds': 1, 'screenshots': [], 'filled': {}}
    _plan({'action': 'browse', 'goal': 'book Be Our Guest', 'site': 'disneyworld.disney.go.com'})
    orig_add = storage.add_mission_step

    def add_and_race(mission_id, data):
        if data.get('kind') == 'browse':
            subjects.retarget('thread', tid, 'trip', 'ev_hawaii', MOM)    # lands after the post-plan check
        return orig_add(mission_id, data)
    storage.add_mission_step = add_and_race
    try:
        _step(mid)
    finally:
        storage.add_mission_step = orig_add
    check(not calls, "the runner never starts a Disney browse once the thread is about Hawaii")
    check(storage.get_mission(mid)['status'] != 'browsing', f"not left browsing: {storage.get_mission(mid)['status']}")
    check(_steps(mid, 'stale_plan'), "and the note says why")


def scenario_r5_a_proposal_is_born_with_its_origin():
    _fresh()
    mid = _mission(created_by='mom', subject_kind='list', subject_id='l2', subject_rev=1)
    inserted = []
    orig = storage.add_action_proposal
    storage.add_action_proposal = lambda proposal: inserted.append(dict(proposal)) or orig(proposal)
    try:
        _plan({'action': 'propose', 'tool': 'add_shopping_items', 'args': {'items': ['engraved ring']}, 'summary': 'Add the ring', 'why': 'gift'})
        _step(mid)
    finally:
        storage.add_action_proposal = orig
    check(inserted and inserted[0].get('origin_kind') == 'mission' and inserted[0].get('origin_id') == mid,
          f"the row is never stored, even for an instant, without its mission: {inserted}")


def scenario_r6_an_unbound_lookup_of_a_household_record_reads_as_any_adult():
    _fresh()
    storage.add_shopping_list({'id': 'l3', 'name': 'Pie secret', 'audience': 'private', 'shared_with': ['mom'], 'occasion_id': 'o2'})
    mid = _mission(created_by='mom')
    _plan({'action': 'tool', 'tool': 'find_in_chauffeur', 'args': {'query': 'Thanksgiving'}}, {'action': 'ask_user', 'question': 'ok?'})
    _step(mid)
    _step(mid)
    nxt = PROMPTS[-1]['user']
    check('Thanksgiving' in nxt and 'Pie secret' not in nxt,
          f"the household occasion reads in full, as any adult would see it; mom's private list is not in it:\n{nxt[-700:]}")


SCENARIOS = [
    scenario_f1_patch_cannot_touch_subject_fields,
    scenario_f2_retarget_never_widens_the_audience,
    scenario_f3_a_stale_planner_answer_is_discarded,
    scenario_f4_a_thread_about_a_thread_inherits_its_audience,
    scenario_f5_spoken_safety_is_transitive,
    scenario_f6_argyle_never_lists_or_reuses_a_hidden_thread,
    scenario_f7_a_bound_missions_proposal_carries_its_audience,
    scenario_f8_a_group_channel_gets_about_only_when_everyone_may_see_it,
    scenario_f9_the_minds_snapshot_leaves_out_threads_not_for_the_wall,
    scenario_f10_an_unbound_mission_sees_withheld_records_as_ids_only,
    scenario_f11_chat_dispatches_find_in_chauffeur_as_the_speaker,
    scenario_r1_a_chat_lookup_in_a_group_channel_answers_for_everyone_in_it,
    scenario_r2_a_phone_voice_lookup_is_display_only,
    scenario_r3_household_voice_still_names_the_mission_already_under_way,
    scenario_r4_a_retarget_between_the_check_and_the_browse_stops_the_browse,
    scenario_r5_a_proposal_is_born_with_its_origin,
    scenario_r6_an_unbound_lookup_of_a_household_record_reads_as_any_adult,
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

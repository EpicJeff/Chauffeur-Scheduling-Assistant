"""Who sees a planned mission's words (spec §7; Codex F9, F10). Task 11.

  * a KEEPER (the adult who started a mission a parent later linked to a
    parents-only record) keeps the row but reads only progress: the mission
    detail, the admin list and the view carry `planned.redacted(plan)` (states
    and counts, no questions, answers, titles, rows or drafts), the transcript
    steps carry no args or results, their DM is neutral with no card, and no
    approval option is offered to them;
  * approving a plan or a stage by WORDS (act_on_situation) happens only in a
    private conversation: the person's own Argyle DM or the widget (`conv:`);
    a group or family channel is refused ("yes" typed there approves nothing);
  * in a channel some member may not see, the chat prompt carries no plan
    words (no stage titles, no row summaries in the FOCUS line);
  * the speakers never hear presents rows; the Mind's snapshot never carries
    plan questions, answers or rows.

Run from chauffeur/:  python tests/test_planned_missions_audience.py
"""
from harness import check  # noqa: F401
from services import storage, missions, situations, triage
from services import agent_tools_v2 as tools
from test_planned_missions import _fresh, _plan_of, _ask_names
from test_mission_subject import _plan, _step, _mission, _thread
from test_subject_audience import _as
from test_subjects import MOM, DAD, AUNT

SECRET_Q = 'What is the ring budget?'
SECRET_ROW = 'Order the engraved ring'
STAGES = [{'id': 's1', 'kind': 'build', 'title': 'Buy the surprise gift', 'why': 'x', 'makes': ['the engraved ring']}]


def _planned_by(creator, link=None):
    mid = _mission(created_by=creator)
    if link:
        from services import subjects
        res = subjects.retarget('mission', mid, link[0], link[1], dict(MOM))
        check(res['status'] == 'success', f"a parent links it before the plan exists: {res}")
    _plan({'action': 'interview', 'questions': [{'key': 'ring_budget', 'ask': SECRET_Q, 'kind': 'number'}]})
    _step(mid)
    from services import planned
    # A linked party merges its template's questions first; the rest are "you decide".
    keys = [q['key'] for q in _plan_of(mid)['questions']]
    planned.answer_plan(mid, {k: (300 if k == 'ring_budget' else 'you_decide') for k in keys}, dict(MOM))
    _plan({'action': 'plan', 'stages': STAGES})
    _step(mid)
    return mid


def _secrets_in(blob):
    return [s for s in (SECRET_Q, SECRET_ROW, 'Buy the surprise gift', 'the engraved ring', '300') if s in blob]


def scenario_a_keeper_reads_progress_only():
    _fresh()
    mid = _planned_by('aunt', link=('occasion', 'o1'))
    import main
    detail = main.missions_detail(mid, request=_as('aunt'))
    check(not _secrets_in(repr(detail)), f"the keeper's detail carries none of the plan's words: {_secrets_in(repr(detail))}")
    check(detail.get('plan') and detail['plan'].get('state') == 'proposed' and 'stage_count' in detail['plan'],
          f"but does carry progress: {detail.get('plan')}")
    admin = main.missions_admin(request=_as('aunt'))
    row = next((m for m in admin['active'] if m['id'] == mid), None)
    check(row is not None and not _secrets_in(repr(row)), "the admin list too")
    v = situations.view('mission', mid, dict(AUNT))
    check(not _secrets_in(repr(v)), f"and the card view: {_secrets_in(repr(v))}")
    check(not [o for o in (v.get('options') or []) if o['verb'] in ('approve_plan', 'run_stage')], "and offers the keeper nothing to approve")
    full = main.missions_detail(mid, request=_as('mom'))
    check(SECRET_Q in repr(full), "a parent sees the whole plan")


def scenario_a_keepers_dm_is_neutral():
    _fresh()
    sent = []
    missions._post = lambda dm, argyle, body, card=None: sent.append((dm.get('member_ids'), body, card)) or {'id': f'm{len(sent)}'}
    mid = _planned_by('aunt', link=('occasion', 'o1'))
    sent.clear()
    missions._dm_person(storage.get_mission(mid), f'{SECRET_ROW}? Approve the stage.')
    to_aunt = [(b, c) for ids, b, c in sent if 'aunt' in (ids or [])]
    check(to_aunt and not _secrets_in(to_aunt[0][0]) and to_aunt[0][1] is None, f"neutral words, no card: {to_aunt}")


def scenario_approval_by_words_only_in_private():
    _fresh()
    mid = _planned_by('mom')
    rev = _plan_of(mid)['rev']
    group = storage.get_or_create_group(['mom', 'dad'], 'Parents')
    triage.set_focus(f"channel:{group['id']}", 'mission', mid, 'Plan')
    res = tools.act_on_situation(verb='approve_plan', option_id=f'approve_plan:{rev}:approve', acting_member=dict(MOM),
                                 focus_key=f"channel:{group['id']}")
    check(res['status'] == 'error' and 'private' in res['message'].lower() and _plan_of(mid)['state'] == 'proposed',
          f"never from a group channel: {res}")
    argyle = storage.ensure_argyle_member()
    dm = storage.get_or_create_dm(argyle['id'], 'mom')
    triage.set_focus(f"channel:{dm['id']}", 'mission', mid, 'Plan')
    res = tools.act_on_situation(verb='approve_plan', option_id=f'approve_plan:{rev}:approve', acting_member=dict(MOM),
                                 focus_key=f"channel:{dm['id']}")
    check(res['status'] == 'success' and _plan_of(mid)['state'] == 'approved', f"in her own Argyle DM, yes: {res}")
    mid2 = _planned_by('mom')
    rev2 = _plan_of(mid2)['rev']
    triage.set_focus('conv:widget1', 'mission', mid2, 'Plan')
    res = tools.act_on_situation(verb='approve_plan', option_id=f'approve_plan:{rev2}:approve', acting_member=dict(MOM), focus_key='conv:widget1')
    check(res['status'] == 'success', f"the widget is private too: {res}")


def scenario_a_mixed_channel_prompt_carries_no_plan_words():
    _fresh()
    from services import agent_router
    tid = _thread('Kate party planning', subject_kind='occasion', subject_id='o1', subject_rev=1)
    mid = _mission(created_by='mom', origin=tid)
    _plan({'action': 'interview', 'questions': [{'key': 'ring_budget', 'ask': SECRET_Q, 'kind': 'number'}]})
    _step(mid)
    from services import planned
    planned.answer_plan(mid, {'ring_budget': 300}, dict(MOM))
    _plan({'action': 'plan', 'stages': STAGES})
    _step(mid)
    mixed = storage.get_or_create_group(['mom', 'aunt'], 'Mom and Jo')
    triage.set_focus(f"channel:{mixed['id']}", 'thread', tid, 'Kate party planning')
    seen = []
    orig = agent_router.call_gemma_with_fallback
    agent_router.call_gemma_with_fallback = lambda prompt, tools_, system_prompt: seen.append(prompt + system_prompt) or {'message': 'ok', 'tool_calls': []}
    try:
        agent_router.process_agent_request('what is next?', source='family', acting_member=dict(MOM), focus_key=f"channel:{mixed['id']}")
    finally:
        agent_router.call_gemma_with_fallback = orig
    check(seen and not _secrets_in(seen[-1]), f"nothing of the plan in a channel the party excludes someone from: {_secrets_in(seen[-1])}")


def scenario_the_speakers_and_the_mind_never_carry_plan_words():
    _fresh()
    mid = _planned_by('mom')
    from services import mind
    snap = mind.snapshot()
    check(not _secrets_in(snap), f"the Mind's snapshot: {_secrets_in(snap)}")
    from services import agent_router, voice_tools
    from services import voice_identity as voice
    tid = _thread('Ring errand', subject_kind='occasion', subject_id='o2', subject_rev=1)
    storage.update_thread(tid, {'voice_shared': True})
    storage.update_mission(mid, {'origin_kind': 'thread', 'origin_ref': tid})
    triage.set_focus('voice:1', 'thread', tid, 'Ring errand')

    class _V(voice.VoiceContext):
        def verified_member(self):
            return storage.get_member('mom')
    ctx = _V('ha', 'assist_satellite.kitchen', 'r', 'g', level='verified', member_id='mom', service_revision=voice._revision(), paired=True)
    seen = []
    orig = agent_router.call_gemma_with_fallback
    agent_router.call_gemma_with_fallback = lambda prompt, tools_, system_prompt: seen.append(prompt + system_prompt) or {'message': 'ok', 'tool_calls': []}
    try:
        agent_router.process_agent_request("what's next on it", source='voice', voice_context=ctx, focus_key='voice:1')
    finally:
        agent_router.call_gemma_with_fallback = orig
    check(seen and SECRET_ROW not in seen[-1] and 'the engraved ring' not in seen[-1], "the speaker never hears the presents row")


SCENARIOS = [
    scenario_a_keeper_reads_progress_only,
    scenario_a_keepers_dm_is_neutral,
    scenario_approval_by_words_only_in_private,
    scenario_a_mixed_channel_prompt_carries_no_plan_words,
    scenario_the_speakers_and_the_mind_never_carry_plan_words,
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

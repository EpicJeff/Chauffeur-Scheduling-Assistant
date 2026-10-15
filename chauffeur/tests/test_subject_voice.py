"""Subjects on the satellite (spec 2026-10-14 §2, Codex review finding 9).

A speaker is a room, not a person's phone: what is said aloud must be safe to
say in the room. Pinned here (Task 8):

  * `find_in_chauffeur` is on the voice allowlist and dispatch runs it as the
    verified speaker (or nobody, for household voice) with spoken=True: a
    household-audience trip is found, a parents-default trip is not, even for
    a verified parent;
  * dispatch's `start_mission_for` forwards subject_kind/subject_id, and a
    subject that may not be said aloud is dropped (the mission starts unbound);
  * the spoken prompt carries ABOUT for a voice-shared focus thread only when
    its subject may be said aloud; otherwise neither ABOUT nor the title.

Run from chauffeur/:  python tests/test_subject_voice.py
"""
from harness import check  # noqa: F401
from services import storage, triage, voice_tools
from services import voice_identity as voice
from test_mission_subject import _fresh, _thread
from test_subjects import MOM


class _Verified(voice.VoiceContext):
    """A verified parent on the kitchen speaker (the session machinery is the
    identity tests' business; here only who is speaking matters)."""
    def verified_member(self):
        return storage.get_member('mom')

    def member(self):
        return storage.get_member('mom')


def _ctx(verified=True):
    cls = _Verified if verified else voice.VoiceContext
    return cls('ha', 'assist_satellite.kitchen', 'req1', 'gen1', level='verified' if verified else 'unknown',
               member_id='mom' if verified else None, service_revision=voice._revision(), paired=True)


def scenario_dispatch_finds_only_what_may_be_said_aloud():
    _fresh()
    check('find_in_chauffeur' in voice_tools.TOOLS, "on the voice allowlist")
    out = voice_tools.dispatch('find_in_chauffeur', {'query': 'Hawaii'}, _ctx())
    check(out.get('status') == 'success' and [c['id'] for c in out['candidates']] == ['ev_hawaii'], f"a household trip: {out}")
    out = voice_tools.dispatch('find_in_chauffeur', {'query': 'Disney World'}, _ctx())
    check(out.get('candidates') == [] and not out.get('context'), f"a parents-default trip is never said aloud, even to a parent: {out}")
    out = voice_tools.dispatch('find_in_chauffeur', {'query': 'Hawaii'}, _ctx(verified=False))
    check([c['id'] for c in out.get('candidates') or []] == ['ev_hawaii'], f"household voice finds household things: {out}")
    out = voice_tools.dispatch('find_in_chauffeur', {'query': 'Grandma'}, _ctx(verified=False))
    check(out.get('candidates') == [], "household voice looks up no person")


def scenario_dispatch_start_mission_for_forwards_a_speakable_subject():
    _fresh()
    # Front door slice 1: the voice door is start_project; a speakable subject becomes the project's first piece.
    out = voice_tools.dispatch('start_project', {'goal': 'book the condo', 'subject_kind': 'trip', 'subject_id': 'ev_hawaii'},
                               _ctx(), focus_key='voice:1')
    check(out.get('status') == 'success', f"started: {out}")
    p = storage.get_project(out['project_id'])
    check(any((x['kind'], x['id']) == ('trip', 'ev_hawaii') for x in p['pieces']) and p['audience'] == 'household',
          f"the speakable subject is a piece: {p}")
    out = voice_tools.dispatch('start_project', {'goal': 'book dining at the park', 'subject_kind': 'trip', 'subject_id': 'ev_disney'},
                               _ctx(), focus_key='voice:2')
    check(out.get('status') == 'success'
          and not any(x['kind'] == 'trip' for x in storage.get_project(out['project_id'])['pieces']),
          f"a subject that may not be said aloud is dropped, the project still starts: {out}")


def scenario_the_spoken_prompt_carries_about_only_when_safe():
    _fresh()
    from services import agent_router
    captured = []
    orig = agent_router.call_gemma_with_fallback
    agent_router.call_gemma_with_fallback = lambda prompt, tools_, system_prompt: captured.append(system_prompt) or {'message': 'ok', 'tool_calls': []}
    try:
        tid = _thread('Hawaii condo', subject_kind='trip', subject_id='ev_hawaii', subject_rev=1)
        storage.update_thread(tid, {'voice_shared': True})
        triage.set_focus('voice:1', 'thread', tid, 'Hawaii condo')
        agent_router.process_agent_request("what's left on it", source='voice', voice_context=_ctx(), focus_key='voice:1')
        check(captured and 'ABOUT: trip "Hawaii"' in captured[-1], f"a speakable subject heads the spoken prompt:\n{(captured or [''])[-1][-900:]}")
        did = _thread('Disney plans', subject_kind='trip', subject_id='ev_disney', subject_rev=1)
        storage.update_thread(did, {'voice_shared': True})
        triage.set_focus('voice:2', 'thread', did, 'Disney plans')
        agent_router.process_agent_request("what's left on it", source='voice', voice_context=_ctx(), focus_key='voice:2')
        check('ABOUT:' not in captured[-1] and 'Disney World' not in captured[-1],
              "a subject that may not be said aloud is not put in the room's prompt at all")
    finally:
        agent_router.call_gemma_with_fallback = orig


SCENARIOS = [
    scenario_dispatch_finds_only_what_may_be_said_aloud,
    scenario_dispatch_start_mission_for_forwards_a_speakable_subject,
    scenario_the_spoken_prompt_carries_about_only_when_safe,
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

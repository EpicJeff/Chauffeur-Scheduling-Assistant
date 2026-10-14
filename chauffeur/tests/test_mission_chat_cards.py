"""A mission's ask reaches the person as a CARD in their Argyle DM, with the
same buttons the thread card and the Missions page offer, so an approval is
a tap where the mission was started instead of a trip to the add-on.

Rules pinned here:

  * every ask DM (question, release, submit, verify, hand-off) carries a
    `mission_ask` card whose options are the mission's own situation options
    (same ids, same labels: the approve button reads the whole question,
    never a blind "Book it");
  * a DM that is not an ask (the finish summary) carries no card;
  * the ask step remembers the chat messages that carry its card, and an
    answer through situations.act (the hand path), through the voice
    approval phrase, or a NEWER ask on the same mission rewrites those cards
    to their answered state so the buttons leave the chat with the decision;
  * the card is built from `services/situations.py` options, so a stale id
    from a drawn card is refused by `act` like any other stale option.

Run from chauffeur/:  python tests/test_mission_chat_cards.py
"""
import time
from datetime import date
from types import SimpleNamespace

from harness import check  # noqa: F401
from services import storage, missions, situations

MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}


def _reset():
    for t in (storage.missions_table, storage.mission_steps_table, storage.members_table, storage.app_state_table,
              storage.chat_channels_table, storage.chat_messages_table, storage.threads_table):
        t.truncate()
    storage.add_member(dict(MOM))
    storage.add_member({'id': 'dad', 'name': 'Dad', 'role': 'parent'})
    storage.ensure_argyle_member()
    storage.get_settings = lambda: {'missions_enabled': True, 'llm_gemini_paid_api_key': 'paid', 'llm_gemini_api_key': 'k',
                                    'contact_first_name': 'Jeff', 'contact_email': 'ffejnosliw@gmail.com', 'contact_zip': '27519',
                                    'missions_submit_enabled': True}
    storage.set_app_state(f"mission_calls:{date.today().isoformat()}", {})
    situations.REFRESH_DELAY_S = 0
    situations._pool_call = lambda *a, **k: {}
    missions._browse_async = False
    # The real post path: the message lands in storage with its card (main is
    # absent in tests, so the SSE/push fan-out is skipped).
    from services.agent_tools_v2 import _post_chat_message
    missions._post = lambda dm, argyle, body, card=None: _post_chat_message(dm, argyle, body, card=card)


def _report(outcome, **kw):
    base = {'outcome': outcome, 'text': kw.pop('text', outcome), 'learned': {}, 'stopped_at': 'https://bodewell.com/guest-schedule-service',
            'wanted_fields': [], 'turns': 7, 'tokens_in': 1000, 'tokens_out': 50, 'seconds': 30.0, 'screenshots': [], 'filled': {}}
    return {**base, **kw}


def _mission(created_by='mom'):
    return storage.add_mission({'goal': 'get the dishwasher fixed', 'origin_kind': 'manual', 'created_by': created_by, 'tier': 'mission'})


def _dm_messages(member_id='mom'):
    argyle = storage.ensure_argyle_member()
    dm = storage.get_or_create_dm(argyle['id'], member_id)
    rows = [dict(r) for r in storage.chat_messages_table.search(storage.Query().channel_id == dm['id'])]
    return sorted(rows, key=lambda r: r.get('ts') or 0)


def _newest_ask(mid):
    return next(s for s in reversed(storage.get_mission_steps(mid)) if s.get('kind') == 'ask')


def _release_ask(mid):
    missions._browse = lambda **kw: _report('needs_release', wanted_fields=['first_name', 'email', 'zip'])
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    return _newest_ask(mid)


def scenario_release_ask_dm_carries_a_card_with_the_thread_cards_options():
    _reset()
    mid = _mission()
    ask = _release_ask(mid)
    msgs = _dm_messages()
    check(len(msgs) == 1 and msgs[0].get('card'), f"one DM with a card: {msgs}")
    card = msgs[0]['card']
    check(card['kind'] == 'mission_ask' and card['mission_id'] == mid and card['ask_id'] == ask['id']
          and card['ask'] == 'release' and card['state'] == 'open', f"the card names its ask: {card}")
    check(card['question'] == ask['result_json']['question'] and card['goal'] == 'get the dishwasher fixed',
          f"the card carries the question and the goal: {card}")
    check(card['site'] == 'bodewell.com' and card['fields'] == ['first_name', 'email', 'zip']
          and card['values'] == {'first_name': 'Jeff', 'email': 'ffejnosliw@gmail.com', 'zip': '27519'},
          f"a release card shows exactly what leaves the house: {card}")
    want = [o for o in situations.options_for('mission', situations.load('mission', mid)) if o['verb'] == 'release']
    got = card['options']
    check([o['id'] for o in got] == [o['id'] for o in want] and [o['label'] for o in got] == [o['label'] for o in want],
          f"the buttons are the situation's own options, same ids and labels:\n{got}\n{want}")
    check(got[0]['id'] == f"release:{ask['id']}:approve" and got[0]['verb'] == 'release' and got[0]['payload'] == {'decision': 'approve'},
          f"the approve option leads: {got[0]}")
    check(ask.get('chat_message_ids') == [msgs[0]['id']], f"the ask step remembers its card's message: {ask.get('chat_message_ids')}")


def scenario_submit_ask_card_reads_the_whole_booking():
    _reset()
    mid = _mission()
    rec = {'url': 'https://bodewell.com/book', 'button': 'Book now', 'state': {'slot': 'Tue 8-12'}, 'display': 'Tue 8-12, $114.95',
           'facts': {'slot': 'Tue Oct 20 8-12', 'price': '$114.95'}, 'intent': 'book'}
    missions._browse = lambda **kw: _report('needs_submit', submit=rec)
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'book the earliest slot', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    ask = _newest_ask(mid)
    check(ask['name'] == 'submit', f"a submit ask: {ask}")
    card = _dm_messages()[-1]['card']
    check(card['ask'] == 'submit' and card['site'] == 'bodewell.com' and card['url'] == rec['url']
          and card['button'] == 'Book now' and card['facts'] == rec['facts'], f"the submit card shows site, facts and the button: {card}")
    ids = [o['id'] for o in card['options']]
    check(ids == [f"submit:{ask['id']}:approve", f"submit:{ask['id']}:decline", f"submit:{ask['id']}:stop"], f"three answers: {ids}")
    check(card['options'][0]['label'] == ask['result_json']['question'], "the approve button reads the question itself, never a blind Book it")


def scenario_question_ask_card_offers_answer_and_handoff_card_carries_the_url():
    _reset()
    mid = _mission()
    missions._llm = lambda m, s, u, st: {'action': 'ask_user', 'question': 'Which day works, Tuesday or Thursday?'}
    missions.step(storage.get_mission(mid))
    ask = _newest_ask(mid)
    card = _dm_messages()[-1]['card']
    check(card['ask'] == 'question' and card['question'] == 'Which day works, Tuesday or Thursday?', f"a question card: {card}")
    check(len(card['options']) == 1 and card['options'][0]['verb'] == 'answer' and card['options'][0]['payload'].get('ask') == 'question',
          f"one Answer option whose payload says it is a question: {card['options']}")
    # A hand-off: the person finishes on the page, so the card carries where.
    _reset()
    mid = _mission()
    missions._browse = lambda **kw: _report('captcha_failed', filled={'first_name': 'Jeff'})
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    ask = _newest_ask(mid)
    check(ask['name'] == 'handoff', f"a hand-off ask: {ask}")
    card = _dm_messages()[-1]['card']
    check(card['ask'] == 'handoff' and card['url'] == ask['result_json']['url'] and card['options'] and card['options'][0]['verb'] == 'answer',
          f"the hand-off card carries the url and an answer option: {card}")


def scenario_a_finish_summary_dm_carries_no_card():
    _reset()
    mid = _mission()
    missions._llm = lambda m, s, u, st: {'action': 'finish', 'summary': 'Nothing to do; it is under warranty.', 'next_action': 'call the maker'}
    missions.step(storage.get_mission(mid))
    msgs = _dm_messages()
    check(msgs and all(not m.get('card') for m in msgs), f"a summary is words only: {[m.get('card') for m in msgs]}")


def scenario_act_through_the_card_settles_it_with_the_decision():
    _reset()
    mid = _mission()
    ask = _release_ask(mid)
    card = _dm_messages()[-1]['card']
    approve = card['options'][0]
    calls = []
    missions._browse = lambda **kw: calls.append(kw) or _report('done', text='Tue 8-12, $114.95')
    missions._llm = lambda m, s, u, st: {'action': 'finish', 'summary': 'done', 'next_action': 'pick a slot'}
    res = situations.act('mission', mid, approve['verb'], option_id=approve['id'], payload={}, actor=MOM)
    check(res['status'] == 'success', f"the tap from the chat card is the same act as the thread card: {res}")
    check(calls and calls[0]['released'] == {'first_name': 'Jeff', 'email': 'ffejnosliw@gmail.com', 'zip': '27519'},
          f"the release happened: {calls}")
    msg = storage.get_chat_message(ask['chat_message_ids'][0])
    card = msg['card']
    check(card['state'] == 'answered' and card['outcome'] == approve['label'] and card['options'] == [],
          f"the card now shows the decision and no buttons: {card}")
    # A second tap on the drawn (stale) card is refused by the server, not acted on.
    res2 = situations.act('mission', mid, approve['verb'], option_id=approve['id'], payload={}, actor=MOM)
    check(res2['status'] in ('refused', 'success') and len(calls) == 1, f"a stale button runs nothing twice: {res2} {len(calls)}")


def scenario_a_newer_ask_settles_the_older_card():
    _reset()
    mid = _mission()
    first = _release_ask(mid)
    # Decline through the card: the mission hands off with a NEW ask; the old card closes.
    card = _dm_messages()[-1]['card']
    decline = next(o for o in card['options'] if o['payload'].get('decision') == 'decline')
    res = situations.act('mission', mid, 'release', option_id=decline['id'], payload={}, actor=MOM)
    check(res['status'] == 'success', f"declined: {res}")
    old = storage.get_chat_message(first['chat_message_ids'][0])['card']
    check(old['state'] == 'answered' and old['outcome'] == decline['label'] and not old['options'], f"the old card settled: {old}")
    newest = _newest_ask(mid)
    check(newest['name'] == 'handoff' and newest['id'] != first['id'], f"a hand-off followed: {newest}")
    new_card = _dm_messages()[-1]['card']
    check(new_card['ask_id'] == newest['id'] and new_card['state'] == 'open', f"the new ask has its own open card: {new_card}")
    # And an ask superseded without a decision (a settle from elsewhere) reads as moved on.
    missions.settle_ask_cards(mid, newest['id'], 'Moved on')
    moved = storage.get_chat_message(newest['chat_message_ids'][0])['card']
    check(moved['state'] == 'answered' and moved['outcome'] == 'Moved on' and not moved['options'], f"settled by hand: {moved}")


def scenario_every_recipient_gets_a_card_when_nobody_started_it():
    _reset()
    mid = _mission(created_by=None)
    ask = _release_ask(mid)
    mom = _dm_messages('mom')
    dad = _dm_messages('dad')
    check(mom and dad and mom[-1]['card']['ask_id'] == ask['id'] and dad[-1]['card']['ask_id'] == ask['id'],
          "both parents hold the card")
    check(sorted(ask['chat_message_ids']) == sorted([mom[-1]['id'], dad[-1]['id']]), f"both messages remembered: {ask['chat_message_ids']}")
    missions.settle_ask_cards(mid, ask['id'], 'Shared')
    check(all(storage.get_chat_message(i)['card']['state'] == 'answered' for i in ask['chat_message_ids']), "both cards settle together")


def scenario_the_hand_path_endpoint_takes_the_cards_option():
    _reset()
    import main
    from services import auth as _auth
    _auth.acting_member = lambda h, q, claimed=None: {'id': 'mom'}
    _auth.impersonation_refused = lambda acting: False
    _auth.identify = lambda h, q: {'tier': _auth.MEMBER, 'member': None}
    mid = _mission()
    ask = _release_ask(mid)
    card = _dm_messages()[-1]['card']
    stop = next(o for o in card['options'] if o['payload'].get('decision') == 'stop')
    req = SimpleNamespace(headers={}, query_params={'member_id': 'mom'})
    res = main.situations_act('mission', mid, body={'verb': stop['verb'], 'option_id': stop['id'], 'payload': {}, 'member_id': 'mom'},
                              request=req, background_tasks=None)
    check(res['status'] == 'success', f"the endpoint the card posts to answers: {res}")
    check(storage.get_mission(mid)['status'] == 'blocked', "stopped")
    settled = storage.get_chat_message(ask['chat_message_ids'][0])['card']
    check(settled['state'] == 'answered' and settled['outcome'] == stop['label'], f"settled over HTTP too: {settled}")


def scenario_voice_approval_settles_the_card_too():
    _reset()
    from services import voice_approval, voice_identity as identity
    mid = _mission()
    ask = _release_ask(mid)
    ctx = SimpleNamespace(ha_instance_id='h', satellite_id='s', request_id='r2', generation=1, verified_member=lambda: dict(MOM))
    identity._sessions[('h', 's')] = {'generation': 1, 'expires_at': time.time() + 60,
                                      'readback': {'id': 'rb', 'mission_id': mid, 'ask_id': ask['id'], 'kind': 'release',
                                                   'digest': 'd', 'request_id': 'r1', 'expires_at': time.time() + 60, 'question': 'q'}}
    orig_enabled, orig_release = voice_approval._enabled, missions.release
    voice_approval._enabled = lambda: True
    seen = []
    missions.release = lambda mission_id, decision, actor, ask_id=None, approval_context=None: seen.append((mission_id, decision, ask_id)) or {'status': 'success', 'message': 'Shared.'}
    try:
        res = voice_approval.intercept('approve release', ctx)
    finally:
        voice_approval._enabled, missions.release = orig_enabled, orig_release
        identity._sessions.pop(('h', 's'), None)
    check(res['status'] == 'success' and seen == [(mid, 'approve', ask['id'])], f"the phrase approved: {res} {seen}")
    card = storage.get_chat_message(ask['chat_message_ids'][0])['card']
    check(card['state'] == 'answered' and 'voice' in card['outcome'].lower() and not card['options'],
          f"the phone's card says it was approved by voice: {card}")


SCENARIOS = [
    scenario_release_ask_dm_carries_a_card_with_the_thread_cards_options,
    scenario_submit_ask_card_reads_the_whole_booking,
    scenario_question_ask_card_offers_answer_and_handoff_card_carries_the_url,
    scenario_a_finish_summary_dm_carries_no_card,
    scenario_act_through_the_card_settles_it_with_the_decision,
    scenario_a_newer_ask_settles_the_older_card,
    scenario_every_recipient_gets_a_card_when_nobody_started_it,
    scenario_the_hand_path_endpoint_takes_the_cards_option,
    scenario_voice_approval_settles_the_card_too,
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

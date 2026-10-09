"""The asks ledger: every channel offered, a draft for each, the three answer
gates, and a yes that is claimed then applied exactly once — through
duplicate taps, a competing sibling, a moved event, a vanished event, a
failed effect and an interrupted claim."""
import datetime
import time
from unittest import mock

from harness import check  # noqa: F401
from services import storage, asks, situations

NOON = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
CALLS = []


def _reset():
    CALLS.clear()
    for t in (storage.asks_table, storage.findings_table, storage.members_table, storage.cache_table,
              storage.app_state_table, storage.assist_contacts_table, storage.assist_assignments_table,
              storage.assist_history_table, storage.chat_channels_table, storage.chat_messages_table,
              storage.drivers_table, storage.agent_action_proposals_table, storage.threads_table):
        t.truncate()
    storage.get_settings = lambda: {'calendar_ids': ['primary'], 'llm_gemini_api_key': ''}
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'dad', 'name': 'Dad', 'role': 'adult'})
    storage.add_member({'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True})
    storage.add_member({'id': 'nan', 'name': 'Nan', 'role': 'helper'})
    storage.add_assist_contact({'id': 'c1', 'name': 'Sarah', 'phone': '555-0100', 'kinds': ['driving'], 'active': True})
    storage.add_assist_contact({'id': 'c2', 'name': 'Mike', 'kinds': ['driving'], 'active': True})
    situations.REFRESH_DELAY_S = 0
    situations._pool_call = lambda *a, **k: {}


def _event(start=None):
    start = start or (NOON + datetime.timedelta(days=2)).replace(hour=16)
    storage.set_cached_schedule({'events': [{'id': 'ev1', 'title': 'Soccer', 'start': start.isoformat(),
                                             'end': (start + datetime.timedelta(hours=1)).isoformat()}],
                                 'assignments': {}, 'unassigned': ['ev1']})
    return start


def _finding(start):
    return storage.add_finding({'identity': 'unassigned:ev1', 'kind': 'unassigned', 'severity': 'decide',
                                'line': 'No driver yet: Soccer', 'subject_type': 'event', 'subject_id': 'ev1',
                                'due_at': start.timestamp(), 'state': 'open',
                                'fingerprint': f"ev1|{start.timestamp()}"})


def _unlocks(contact_id='c1'):
    return {'action_type': 'assist_assignment',
            'payload': {'event_id': 'ev1', 'contact_id': contact_id, 'event_title': 'Soccer',
                        'event_date': (NOON + datetime.timedelta(days=2)).date().isoformat()},
            'fingerprint': asks.fingerprint_for_event('ev1')}


MOM = {'id': 'mom', 'role': 'parent'}


def scenario_every_channel_is_offered_whatever_we_know():
    _reset()
    chans = {c['channel']: c for c in asks.channels_for({'name': 'Stranger'})}
    check(set(chans) == {'email', 'text', 'in_person'}, f"an outsider with nothing known: {set(chans)}")
    check(chans['email']['link'] is None and chans['text']['link'] is None, "no links without an address")
    chans = {c['channel']: c for c in asks.channels_for({'name': 'Sarah', 'contact_id': 'c1'})}
    check(chans['text']['link'] == 'sms:555-0100', f"a known number adds the one-tap link: {chans['text']}")
    chans = {c['channel']: c for c in asks.channels_for({'name': 'Dad', 'member_id': 'dad'})}
    check('chauffeur' in chans, "a member can be asked on Chauffeur")


def scenario_a_draft_for_every_channel():
    _reset()
    start = _event()
    fid = _finding(start)
    for ch in asks.CHANNELS:
        if ch == 'chauffeur':
            continue
        res = asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, 'drive Kate to Soccer Thursday',
                          ch, 'mom', unlocks=_unlocks())
        a = res['ask']
        check(res['status'] == 'success' and a['state'] == 'drafted' and a['draft_body'], f"{ch}: drafted")
        check('Sarah' in a['draft_body'] and 'Soccer' in a['draft_body'], f"{ch}: the draft names the ask")
        check(a['draft_source'] == 'template', "no key: the template draft")
    res = asks.create('finding', fid, {'name': 'Dad', 'member_id': 'dad'}, 'drive Kate Thursday', 'chauffeur', 'mom')
    a = res['ask']
    check(a['state'] == 'sent' and a['message_id'], "a Chauffeur ask is posted and sent at once")
    msg = storage.get_chat_message(a['message_id'])
    check(msg['card']['kind'] == 'ask' and msg['card']['what'] == 'drive Kate Thursday', f"the DM carries the ask card: {msg['card']}")
    check(msg['sender_member_id'] == 'mom', "the DM is from the asker")


def scenario_the_commitment_is_fixed():
    _reset()
    start = _event(); fid = _finding(start)
    a = asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, 'drive Kate', 'text', 'mom',
                    unlocks=_unlocks())['ask']
    check(storage.update_ask(a['id'], {'draft_body': 'Hi Sarah, could you grab Kate after?'}), "wording is editable")
    check(storage.get_ask(a['id'])['what'] == 'drive Kate', "the commitment did not move")
    res = asks.withdraw(a['id'], MOM)
    check(res['status'] == 'success' and storage.get_ask(a['id'])['state'] == 'withdrawn', "withdrawn")
    res = asks.answer(a['id'], 'yes', MOM, reported=True)
    check(res['status'] == 'refused', "a withdrawn ask cannot be answered")


def scenario_three_answer_gates():
    _reset()
    start = _event(); fid = _finding(start)
    a = asks.create('finding', fid, {'name': 'Nan', 'member_id': 'nan'}, 'drive Kate', 'chauffeur', 'mom')['ask']
    check(asks.answer(a['id'], 'yes', {'id': 'kid', 'role': 'child'})['status'] == 'refused', "a bystander child is refused")
    check(asks.answer(a['id'], 'yes', {'id': 'dad', 'role': 'adult'}, reported=False)['status'] == 'refused',
          "an adult who is not the recipient cannot answer AS the recipient")
    res = asks.answer(a['id'], 'yes', {'id': 'nan', 'role': 'helper'})
    check(res['status'] == 'success' and storage.get_ask(a['id'])['answered_by'] == 'nan', f"the helper answers her own ask: {res}")
    b = asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, 'drive Kate', 'text', 'mom')['ask']
    asks.mark_sent(b['id'], MOM)
    check(asks.answer(b['id'], 'no', {'id': 'kid', 'role': 'child'}, reported=True)['status'] == 'refused', "a child cannot report")
    check(asks.answer(b['id'], 'no', {'id': 'dad', 'role': 'adult'}, reported=True)['status'] == 'success', "an adult can report")
    check(asks.create('finding', fid, {'name': 'X'}, 'y', 'text', 'kid')['status'] == 'refused', "a child cannot create")


def _assignment_for(event_id='ev1'):
    v = storage.get_assist_assignment_map().get(event_id)
    return {'contact_id': v} if isinstance(v, str) else v


def scenario_yes_applies_exactly_once_through_duplicate_taps():
    _reset()
    start = _event(); fid = _finding(start)
    a = asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, 'drive Kate', 'text', 'mom',
                    unlocks=_unlocks())['ask']
    asks.mark_sent(a['id'], MOM)
    r1 = asks.answer(a['id'], 'yes', MOM, reported=True)
    r2 = asks.answer(a['id'], 'yes', MOM, reported=True)
    check(r1['status'] == 'success' and r1['outcome'] == 'applied', f"first yes applies: {r1}")
    check(r2['status'] == 'success' and r2['outcome'] == 'applied' and r2.get('already'), f"second yes is a no-op that reports: {r2}")
    check(_assignment_for() and _assignment_for().get('contact_id') == 'c1', "one assist assignment")
    row = storage.get_ask(a['id'])
    check(row['state'] == 'yes' and row['applied_at'] and row['outcome'] == 'applied', f"ledger: {row}")


def scenario_sibling_yes_is_superseded():
    _reset()
    start = _event(); fid = _finding(start)
    a = asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, 'drive Kate', 'text', 'mom', unlocks=_unlocks('c1'))['ask']
    b = asks.create('finding', fid, {'name': 'Mike', 'contact_id': 'c2'}, 'drive Kate', 'text', 'mom', unlocks=_unlocks('c2'))['ask']
    for x in (a, b):
        asks.mark_sent(x['id'], MOM)
    asks.answer(a['id'], 'yes', MOM, reported=True)
    r = asks.answer(b['id'], 'yes', MOM, reported=True)
    check(r['outcome'] == 'superseded' and 'Sarah' in r['message'], f"Mike's yes is recorded, not applied: {r}")
    check(_assignment_for().get('contact_id') == 'c1', "Sarah still has it")
    check(storage.get_ask(b['id'])['state'] == 'yes', "the yes itself is kept")


def scenario_moved_event_is_stale_and_vanished_event_is_stale():
    _reset()
    start = _event(); fid = _finding(start)
    a = asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, 'drive Kate', 'text', 'mom', unlocks=_unlocks())['ask']
    asks.mark_sent(a['id'], MOM)
    _event(start + datetime.timedelta(hours=2))
    r = asks.answer(a['id'], 'yes', MOM, reported=True)
    check(r['outcome'] == 'stale' and 'moved' in r['message'], f"a moved event: {r}")
    check(not _assignment_for(), "nothing applied")
    b = asks.create('finding', fid, {'name': 'Mike', 'contact_id': 'c2'}, 'drive Kate', 'text', 'mom', unlocks=_unlocks('c2'))['ask']
    asks.mark_sent(b['id'], MOM)
    storage.set_cached_schedule({'events': [], 'assignments': {}, 'unassigned': []})
    r = asks.answer(b['id'], 'yes', MOM, reported=True)
    check(r['outcome'] == 'stale', f"a vanished event is stale, never a crash: {r}")


def scenario_failed_effect_and_interrupted_claim_recover():
    _reset()
    start = _event(); fid = _finding(start)
    a = asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, 'drive Kate', 'text', 'mom', unlocks=_unlocks())['ask']
    asks.mark_sent(a['id'], MOM)
    with mock.patch.object(storage, 'set_assist_assignment', side_effect=RuntimeError('db away')):
        r = asks.answer(a['id'], 'yes', MOM, reported=True)
    check(r['outcome'] == 'failed' and storage.get_ask(a['id'])['unlock_error'], f"a failed effect is recorded: {r}")
    # Interrupted after the claim: outcome stuck at 'claimed'. Recovery finishes it.
    b = asks.create('finding', fid, {'name': 'Mike', 'contact_id': 'c2'}, 'drive Kate', 'text', 'mom', unlocks=_unlocks('c2'))['ask']
    asks.mark_sent(b['id'], MOM)
    storage.update_ask(b['id'], {'state': 'yes', 'answered_at': time.time(), 'answered_by': 'mom',
                                 'outcome': 'claimed', 'claim_ts': time.time() - 120})
    n = asks.recover()
    row = storage.get_ask(b['id'])
    check(n == 1 and row['outcome'] == 'applied' and _assignment_for().get('contact_id') == 'c2',
          f"the interrupted claim was finished once: {row}")
    # Interrupted after yes but before the claim: a retry proceeds to claim.
    c = asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, 'drive Kate', 'text', 'mom', unlocks=_unlocks('c1'))['ask']
    asks.mark_sent(c['id'], MOM)
    storage.update_ask(c['id'], {'state': 'yes', 'answered_at': time.time(), 'answered_by': 'mom', 'outcome': None})
    r = asks.answer(c['id'], 'yes', MOM, reported=True)
    check(r['outcome'] == 'superseded', f"a retry claims, and the sibling already applied: {r}")


def scenario_no_returns_the_situation_to_its_options():
    _reset()
    start = _event(); fid = _finding(start)
    a = asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, 'drive Kate', 'text', 'mom', unlocks=_unlocks())['ask']
    asks.mark_sent(a['id'], MOM)
    r = asks.answer(a['id'], 'no', MOM, reported=True)
    check(r['status'] == 'success' and storage.get_ask(a['id'])['state'] == 'no', "no is recorded")
    s = situations.view('finding', fid, viewer={'id': 'mom', 'role': 'parent'})
    check(any(x['state'] == 'no' and x['to_name'] == 'Sarah' for x in s['asks']), "the card shows who said no")
    check(any(o['verb'] == 'ask' for o in s['options']), "and the options are back")


SCENARIOS = [scenario_every_channel_is_offered_whatever_we_know, scenario_a_draft_for_every_channel,
             scenario_the_commitment_is_fixed, scenario_three_answer_gates,
             scenario_yes_applies_exactly_once_through_duplicate_taps, scenario_sibling_yes_is_superseded,
             scenario_moved_event_is_stale_and_vanished_event_is_stale,
             scenario_failed_effect_and_interrupted_claim_recover,
             scenario_no_returns_the_situation_to_its_options]

def scenario_a_yes_with_nothing_to_apply_is_manual_not_applied():
    _reset()
    start = _event(); fid = _finding(start)
    a = asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, 'bring the cones', 'text', 'mom')['ask']
    asks.mark_sent(a['id'], MOM)
    r = asks.answer(a['id'], 'yes', MOM, reported=True)
    row = storage.get_ask(a['id'])
    check(r['outcome'] == 'manual' and row['outcome'] == 'manual' and 'by hand' in r['message'],
          f"nothing was done for them, so it is not applied: {r}")
    check(asks.recover() == 0, "recovery leaves a manual yes alone")


def scenario_a_fresh_claim_is_never_run_twice():
    _reset()
    start = _event(); fid = _finding(start)
    a = asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, 'drive Kate', 'text', 'mom', unlocks=_unlocks())['ask']
    asks.mark_sent(a['id'], MOM)
    storage.update_ask(a['id'], {'state': 'yes', 'answered_at': time.time(), 'answered_by': 'mom',
                                 'outcome': 'claimed', 'claim_ts': time.time()})
    with mock.patch.object(storage, 'set_assist_assignment', wraps=storage.set_assist_assignment) as sa:
        r = asks.answer(a['id'], 'yes', MOM, reported=True)
        check(r.get('outcome') == 'claimed' and sa.call_count == 0,
              f"a duplicate tap while applying runs nothing: {r} / {sa.call_count}")
    r = asks.answer(a['id'], 'no', MOM, reported=True)
    check(r['status'] == 'refused' and storage.get_ask(a['id'])['state'] == 'yes',
          "a no cannot overwrite a yes being applied")


def scenario_a_new_contact_is_minted_once_per_ask():
    _reset()
    start = _event(); fid = _finding(start)
    u = _unlocks(); u['payload']['contact_id'] = ''
    a = asks.create('finding', fid, {'name': 'Beth'}, 'drive Kate', 'text', 'mom', unlocks=u)['ask']
    asks.mark_sent(a['id'], MOM)
    before = len(storage.get_assist_contacts())
    asks.answer(a['id'], 'yes', MOM, reported=True)
    storage.update_ask(a['id'], {'outcome': 'claimed', 'claim_ts': time.time() - 300})
    asks.recover()
    beths = [c for c in storage.get_assist_contacts() if c.get('name') == 'Beth']
    check(len(storage.get_assist_contacts()) == before + 1 and len(beths) == 1,
          f"one Beth, however many times the effect runs: {len(beths)}")
    check(storage.get_ask(a['id'])['outcome'] == 'applied', "and the ask ends applied")


def scenario_siblings_are_the_same_occurrence_only():
    _reset()
    start = _event(); fid = _finding(start)
    old_start = start - datetime.timedelta(days=7)
    storage.add_ask({'situation_kind': 'finding', 'situation_id': None, 'event_id': 'ev1',
                     'event_start': old_start.isoformat(), 'to_name': 'Sarah', 'to_contact_id': 'c1',
                     'what': 'take Soccer', 'channel': 'text', 'asked_by': 'mom', 'state': 'yes',
                     'outcome': 'applied', 'applied_at': time.time() - 7 * 86400,
                     'unlocks': {'action_type': 'assist_assignment',
                                 'payload': {'event_id': 'ev1', 'contact_id': 'c1'},
                                 'fingerprint': f"ev1|{old_start.timestamp()}"}})
    b = asks.create('finding', fid, {'name': 'Mike', 'contact_id': 'c2'}, 'drive Kate', 'text', 'mom', unlocks=_unlocks('c2'))['ask']
    asks.mark_sent(b['id'], MOM)
    r = asks.answer(b['id'], 'yes', MOM, reported=True)
    check(r['outcome'] == 'applied', f"last week's covered ride is not this week's sibling: {r}")


SCENARIOS += [scenario_a_yes_with_nothing_to_apply_is_manual_not_applied, scenario_a_fresh_claim_is_never_run_twice,
              scenario_a_new_contact_is_minted_once_per_ask, scenario_siblings_are_the_same_occurrence_only]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)

"""Stall detection is the whole value: the eleven days nobody was watching."""
import datetime
import time
from harness import check
from services import storage, threads


def _day(off):
    return (datetime.date.today() + datetime.timedelta(days=off)).isoformat()


def _reset():
    storage.threads_table.truncate()
    storage.get_settings = lambda: {}


def scenario_overdue_next_action_stalls():
    _reset()
    t = threads.create('Pest control', owner_member_id='m1',
                       next_action='Call them back', next_action_at=_day(-1))
    check(threads.is_stalled(storage.get_thread(t)) == 'overdue',
          "yesterday's next action is a stall")
    threads.advance(t, 'Call them back', _day(2))
    check(threads.is_stalled(storage.get_thread(t)) is None,
          "a future action is not")


def scenario_silence_stalls_even_with_no_date():
    _reset()
    t = threads.create('Gutters', owner_member_id='m1')
    row = storage.get_thread(t)
    check(threads.is_stalled(row) is None, "a fresh thread is not stalled")
    storage.update_thread(t, {'created_at': time.time() - 9 * 86400})
    check(threads.is_stalled(storage.get_thread(t)) == 'quiet',
          "nine days with nothing happening is")


def scenario_a_note_resets_the_quiet_clock():
    _reset()
    t = threads.create('Gutters', owner_member_id='m1')
    storage.update_thread(t, {'created_at': time.time() - 9 * 86400})
    threads.note(t, 'left a voicemail', who='m1')
    check(threads.is_stalled(storage.get_thread(t)) is None,
          "movement is movement, even when nothing was achieved")


def scenario_closed_threads_never_stall():
    _reset()
    t = threads.create('Old thing', owner_member_id='m1',
                       next_action='x', next_action_at=_day(-30))
    threads.close(t)
    check(threads.is_stalled(storage.get_thread(t)) is None,
          "a finished thread is not a problem")
    check(threads.stalled() == [], "and does not appear in the sweep")


def scenario_open_by_owner_counts_the_carrying():
    _reset()
    threads.create('A', owner_member_id='m1')
    threads.create('B', owner_member_id='m1')
    threads.create('C', owner_member_id='m2')
    d = threads.open_by_owner()
    check(d == {'m1': 2, 'm2': 1}, f"who is holding what, got {d}")


def scenario_a_stalled_thread_becomes_a_finding():
    _reset()
    from services import watchers
    t = threads.create('Pest control', owner_member_id='m1',
                       next_action='Call them back', next_action_at=_day(-3))
    found = [f for f in watchers.collect_findings()[0] if f.kind == 'thread_stall']
    check(len(found) == 1, f"the stall is a finding, got {found}")
    f = found[0]
    check('Pest control' in f.line and 'Call them back' in f.line,
          f"and it arrives with what to do next, got {f.line!r}")
    check(f.subject_id == t and f.subject_type == 'thread', f"got {f}")
    check('thread_stall' in watchers.SCANNED_KINDS,
          "registered, or reconcile will never close it")


def scenario_drafting_never_sends():
    _reset()
    sent = []
    from services import mailer as _m
    orig = _m.send
    threads._pool_call = lambda *a, **k: {'subject': 'Following up',
                                          'body': 'Hi — checking in.'}
    try:
        _m.send = lambda *a, **k: sent.append(a) or {'sent': True}
        t = threads.create('Pool', owner_member_id='m1',
                           counterparty_email='pool@example.com')
        d = threads.draft_message(t)
        check(d['status'] == 'ok' and d['subject'] == 'Following up', f"got {d}")
        check(not sent, "DRAFTING MUST NEVER SEND")
        check(not any(h.get('kind') == 'sent'
                      for h in storage.get_thread(t)['history']),
              "and must not claim it did")
    finally:
        _m.send = orig


def scenario_sending_records_what_went_out():
    _reset()
    from services import mailer as _m
    orig_send, orig_conf = _m.send, _m.configured
    try:
        _m.configured = lambda *a, **k: True
        _m.send = lambda to, subject, body, settings=None: {'sent': True}
        t = threads.create('Pool', owner_member_id='m1',
                           counterparty_email='pool@example.com')
        res = threads.send_drafted(t, 'Hi', 'Body text', 'pool@example.com', 'm1')
        check(res['status'] == 'ok', f"got {res}")
        h = storage.get_thread(t)['history'][-1]
        check(h['kind'] == 'sent' and 'Body text' in h['text'],
              f"the thread remembers what was actually said, got {h}")
        check(storage.get_thread(t)['state'] == 'waiting',
              "and that the ball is now with them")
    finally:
        _m.send, _m.configured = orig_send, orig_conf


def scenario_send_without_smtp_is_an_honest_refusal():
    _reset()
    from services import mailer as _m
    orig = _m.configured
    try:
        _m.configured = lambda *a, **k: False
        t = threads.create('Pool', owner_member_id='m1')
        res = threads.send_drafted(t, 'Hi', 'B', 'a@b.example', 'm1')
        check(res['status'] == 'not_configured', f"got {res}")
    finally:
        _m.configured = orig


def scenario_drafting_and_abandoning_does_not_silence_a_stall():
    _reset()
    t = threads.create('Nanny search', owner_member_id='m1')
    storage.update_thread(t, {'created_at': time.time() - 9 * 86400})
    check(threads.is_stalled(storage.get_thread(t)) == 'quiet',
          "nine days of silence is a stall")
    orig_pool_call = threads._pool_call
    try:
        threads._pool_call = lambda *a, **k: {'subject': 'Checking in',
                                              'body': 'Hi — any update?'}
        d = threads.draft_message(t)
        check(d['status'] == 'ok', f"got {d}")
        check(threads.is_stalled(storage.get_thread(t)) == 'quiet',
              "drafting and walking away accomplished nothing, so it "
              "stays stalled")
    finally:
        threads._pool_call = orig_pool_call


def scenario_actually_sending_resets_the_stall_clock():
    _reset()
    from services import mailer as _m
    orig_send, orig_conf = _m.send, _m.configured
    try:
        _m.configured = lambda *a, **k: True
        _m.send = lambda to, subject, body, settings=None: {'sent': True}
        t = threads.create('Nanny search', owner_member_id='m1',
                           counterparty_email='candidate@example.com')
        storage.update_thread(t, {'created_at': time.time() - 9 * 86400})
        check(threads.is_stalled(storage.get_thread(t)) == 'quiet',
              "nine days of silence is a stall")
        res = threads.send_drafted(t, 'Hi', 'Are you still available?',
                                   'candidate@example.com', 'm1')
        check(res['status'] == 'ok', f"got {res}")
        check(threads.is_stalled(storage.get_thread(t)) is None,
              "something real actually went out, so the clock resets")
    finally:
        _m.send, _m.configured = orig_send, orig_conf


def scenario_inbound_matches_by_counterparty_address():
    _reset()
    t = threads.create('Pool cleaning', owner_member_id='m1',
                       counterparty_email='service@poolco.example')
    matched = threads.match_inbound('Service@PoolCo.example', 'Re: your visit',
                                    'We can come Tuesday.')
    check(matched == t, f"case-insensitive address match, got {matched}")
    h = storage.get_thread(t)['history'][-1]
    check(h['kind'] == 'received' and 'Tuesday' in h['text'],
          f"the reply is logged, got {h}")


def scenario_inbound_from_a_stranger_matches_nothing():
    _reset()
    threads.create('Pool cleaning', owner_member_id='m1',
                   counterparty_email='service@poolco.example')
    matched = threads.match_inbound('nobody@unknown.example', 'Hello',
                                    'Random unrelated mail.')
    check(matched is None, f"a stranger matches nothing, got {matched}")


def scenario_shared_counterparty_disambiguated_by_subject():
    _reset()
    pool = threads.create('Pool opening for the season', owner_member_id='m1',
                          counterparty_email='ops@vendor.example')
    deck = threads.create('Deck permit renewal', owner_member_id='m1',
                          counterparty_email='ops@vendor.example')
    matched = threads.match_inbound('ops@vendor.example',
                                    'Re: deck permit renewal',
                                    'The renewal paperwork is attached.')
    check(matched == deck, f"subject overlap picks the deck thread, got {matched}")
    matched2 = threads.match_inbound('ops@vendor.example',
                                     'Re: pool opening for the season',
                                     'We can open the pool next week.')
    check(matched2 == pool, f"subject overlap picks the pool thread, got {matched2}")


def scenario_inbound_match_moves_waiting_back_to_open():
    _reset()
    from services import mailer as _m
    orig_send, orig_conf = _m.send, _m.configured
    try:
        _m.configured = lambda *a, **k: True
        _m.send = lambda to, subject, body, settings=None: {'sent': True}
        t = threads.create('Nanny search', owner_member_id='m1',
                           counterparty_email='candidate@example.com')
        threads.send_drafted(t, 'Hi', 'Are you still available?',
                             'candidate@example.com', 'm1')
        check(storage.get_thread(t)['state'] == 'waiting',
              "sending put the ball with them")
        matched = threads.match_inbound('candidate@example.com',
                                        'Re: Are you still available?',
                                        'Yes, I am!')
        check(matched == t, f"got {matched}")
        check(storage.get_thread(t)['state'] == 'open',
              "the ball is back with us")
    finally:
        _m.send, _m.configured = orig_send, orig_conf


def scenario_research_ok_appends_answer_and_url():
    _reset()
    t = threads.create('Nanny search', owner_member_id='m1')
    orig = threads._web_research
    try:
        threads._web_research = lambda q: {
            'status': 'ok',
            'answer': 'Most nanny agencies charge a 15-20% placement fee.',
            'facts': [{'claim': 'Agencies charge 15-20%',
                      'url': 'https://example.com/fees'}],
            'sources': [{'title': 'Example', 'url': 'https://example.com/fees'}],
            'dropped': 0, 'via': 'pages',
        }
        res = threads.research(t, 'What do nanny agencies charge?')
        check(res['status'] == 'ok', f"got {res}")
        h = storage.get_thread(t)['history'][-1]
        check(h['kind'] == 'research', f"got {h}")
        check('15-20%' in h['text'] and 'https://example.com/fees' in h['text'],
              f"the answer AND its citation both survive in the record, got {h}")
    finally:
        threads._web_research = orig


def scenario_research_disabled_appends_nothing():
    _reset()
    t = threads.create('Nanny search', owner_member_id='m1')
    before = len(storage.get_thread(t)['history'])
    orig = threads._web_research
    try:
        threads._web_research = lambda q: {'status': 'disabled'}
        res = threads.research(t, 'What do nanny agencies charge?')
        check(res['status'] == 'disabled', f"got {res}")
        check(len(storage.get_thread(t)['history']) == before,
              "an honest no doesn't get written as if something happened")
    finally:
        threads._web_research = orig


def scenario_research_resets_the_stall_clock():
    _reset()
    t = threads.create('Nanny search', owner_member_id='m1')
    storage.update_thread(t, {'created_at': time.time() - 9 * 86400})
    check(threads.is_stalled(storage.get_thread(t)) == 'quiet',
          "nine days of silence is a stall")
    orig = threads._web_research
    try:
        threads._web_research = lambda q: {
            'status': 'ok', 'answer': 'Answer.',
            'facts': [{'claim': 'Answer.', 'url': 'https://example.com/a'}],
            'sources': [{'title': 'A', 'url': 'https://example.com/a'}],
        }
        threads.research(t, 'A question?')
        check(threads.is_stalled(storage.get_thread(t)) is None,
              "finding something out is movement, so the clock resets")
    finally:
        threads._web_research = orig


def scenario_research_persists_only_urls_actually_read():
    """On the pages route (via == 'pages'), `sources` is every search
    result found — up to RESULTS_PER_SEARCH — while `facts` is the
    filtered list where each claim actually cites a page that was fetched
    and read. Two of these three sources were never opened; only the one
    fact's URL may reach the permanent record."""
    _reset()
    t = threads.create('Nanny search', owner_member_id='m1')
    orig = threads._web_research
    try:
        threads._web_research = lambda q: {
            'status': 'ok', 'answer': 'Background checks run $20-60.',
            'via': 'pages',
            'facts': [{'claim': 'Background checks run $20-60',
                      'url': 'https://example.com/read-page'}],
            'sources': [
                {'title': 'Read', 'url': 'https://example.com/read-page'},
                {'title': 'Never fetched', 'url': 'https://example.com/unread-1'},
                {'title': 'Also never fetched', 'url': 'https://example.com/unread-2'},
            ],
            'dropped': 1,
        }
        res = threads.research(t, 'What do background checks cost?')
        check(res['status'] == 'ok', f"got {res}")
        h = storage.get_thread(t)['history'][-1]
        check('https://example.com/read-page' in h['text'],
              f"the cited, actually-read page survives, got {h}")
        check('https://example.com/unread-1' not in h['text']
              and 'https://example.com/unread-2' not in h['text'],
              f"a page nobody read must never enter the permanent record, got {h}")
    finally:
        threads._web_research = orig


def scenario_research_surfaces_the_invention_rate():
    _reset()
    t = threads.create('Nanny search', owner_member_id='m1')
    orig = threads._web_research
    try:
        threads._web_research = lambda q: {
            'status': 'ok', 'answer': 'Answer.',
            'facts': [{'claim': 'Answer.', 'url': 'https://example.com/a'}],
            'sources': [{'title': 'A', 'url': 'https://example.com/a'}],
            'dropped': 3,
        }
        res = threads.research(t, 'A question?')
        check(res.get('dropped') == 3,
              f"the invention rate is surfaced, not discarded, got {res}")
    finally:
        threads._web_research = orig


def scenario_a_received_reply_resets_the_stall_clock():
    _reset()
    t = threads.create('Nanny search', owner_member_id='m1',
                       counterparty_email='candidate@example.com')
    storage.update_thread(t, {'created_at': time.time() - 9 * 86400})
    check(threads.is_stalled(storage.get_thread(t)) == 'quiet',
          "nine days of silence is a stall")
    matched = threads.match_inbound('candidate@example.com', 'Re: hello',
                                    'Sorry for the delay, still interested.')
    check(matched == t, f"got {matched}")
    check(threads.is_stalled(storage.get_thread(t)) is None,
          "a reply actually arriving is movement, so the clock resets")


if __name__ == '__main__':
    scenario_overdue_next_action_stalls()
    scenario_silence_stalls_even_with_no_date()
    scenario_a_note_resets_the_quiet_clock()
    scenario_closed_threads_never_stall()
    scenario_open_by_owner_counts_the_carrying()
    scenario_a_stalled_thread_becomes_a_finding()
    scenario_drafting_never_sends()
    scenario_sending_records_what_went_out()
    scenario_send_without_smtp_is_an_honest_refusal()
    scenario_drafting_and_abandoning_does_not_silence_a_stall()
    scenario_actually_sending_resets_the_stall_clock()
    scenario_research_ok_appends_answer_and_url()
    scenario_research_disabled_appends_nothing()
    scenario_research_resets_the_stall_clock()
    scenario_research_persists_only_urls_actually_read()
    scenario_research_surfaces_the_invention_rate()
    scenario_inbound_matches_by_counterparty_address()
    scenario_inbound_from_a_stranger_matches_nothing()
    scenario_shared_counterparty_disambiguated_by_subject()
    scenario_inbound_match_moves_waiting_back_to_open()
    scenario_a_received_reply_resets_the_stall_clock()
    print("test_threads OK")

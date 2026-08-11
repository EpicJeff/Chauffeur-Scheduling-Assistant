"""Tests for services/email_ingest.py (intake arc phase 2).

Covers MIME body extraction, allowlist matching, item normalization, dedupe,
and the run_ingest pipeline end-to-end with mocked IMAP + LLM.
No network, never touches data/.

Run from chauffeur/:  python tests/test_email_ingest.py
"""
import atexit
import datetime
import os
import shutil
import sys
import tempfile
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

_TMP = tempfile.mkdtemp(prefix="chauffeur_ingest_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import email_ingest, storage  # noqa: E402

PASS = 0
FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


NOW = datetime.datetime.now().astimezone()
IN_5_DAYS = (NOW + datetime.timedelta(days=5)).date().isoformat()


def test_mime_and_allowlist():
    print("MIME parsing + allowlist ...")
    msg = MIMEMultipart('alternative')
    msg['From'] = '"Coach Dan" <coach.dan@teamsnap.com>'
    msg['Subject'] = 'Game Saturday'
    msg.attach(MIMEText('Game at 10am Saturday at Riverside Park.', 'plain'))
    msg.attach(MIMEText('<html><body><p>Game at <b>10am</b></p></body></html>', 'html'))

    check(email_ingest._from_address(msg) == 'coach.dan@teamsnap.com', "From address extracted")
    body = email_ingest._body_text(msg)
    check('Riverside Park' in body and '<' not in body, f"plain body preferred: {body!r}")

    html_only = MIMEMultipart('alternative')
    html_only['From'] = 'no-reply@parentsquare.com'
    html_only.attach(MIMEText('<div>Picture Day is <b>Friday</b>!</div><style>x{}</style>', 'html'))
    body2 = email_ingest._body_text(html_only)
    check('Picture Day' in body2 and '<' not in body2, f"html stripped: {body2!r}")

    defaults = [{'pattern': '@teamsnap.com', 'calendar_id': 'ben@cal'},
                {'pattern': 'principal.smith', 'calendar_id': None}]
    check(email_ingest.sender_default('coach.dan@teamsnap.com', defaults)['calendar_id'] == 'ben@cal',
          "domain pattern matches with default calendar")
    check(email_ingest.sender_default('PRINCIPAL.SMITH@district.org', defaults) is not None,
          "case-insensitive name pattern matches")
    check(email_ingest.sender_default('unknown@somewhere.com', defaults) is None,
          "unmatched sender returns no default (but is still processed)")


def test_normalize():
    print("normalize_item ...")
    timed = email_ingest.normalize_item({
        'kind': 'event', 'title': 'Soccer Game', 'date': IN_5_DAYS,
        'start_time': '10:00', 'end_time': '11:30', 'location': 'Riverside Park',
        'member_name': 'Ben', 'confidence': 0.9})
    check(timed and not timed['all_day'] and timed['start'][:10] == IN_5_DAYS,
          f"timed event normalized: {timed}")
    check(timed['end'][11:16] == '11:30', "end time honored")

    allday = email_ingest.normalize_item({
        'kind': 'event', 'title': 'No School', 'date': IN_5_DAYS,
        'start_time': None, 'confidence': 0.8})
    check(allday and allday['all_day'] and allday['end'] > allday['start'],
          "all-day event normalized with exclusive end")

    task = email_ingest.normalize_item({
        'kind': 'task', 'title': 'Send $12 for field trip', 'date': IN_5_DAYS,
        'start_time': '09:00', 'confidence': 0.7})
    check(task and task['all_day'] and task['title'].startswith('📌'),
          "task is all-day and pin-prefixed")

    check(email_ingest.normalize_item({
        'kind': 'event', 'title': 'Old', 'date': '2020-01-01', 'confidence': 0.9}) is None,
        "past item dropped")
    check(email_ingest.normalize_item({
        'kind': 'event', 'title': 'Meh', 'date': IN_5_DAYS, 'confidence': 0.2}) is None,
        "low confidence dropped")
    check(email_ingest.normalize_item({
        'kind': 'event', 'title': '', 'date': IN_5_DAYS, 'confidence': 0.9}) is None,
        "missing title dropped")


def _fake_msg(uid, from_addr, subject, text):
    return {'uid': uid, 'from': from_addr, 'subject': subject, 'text': text}


def test_run_ingest():
    print("run_ingest end-to-end ...")
    storage.patch_settings({
        'ingest_email_enabled': True,
        'ingest_email_user': 'family@test',
        'ingest_email_password': 'x',
        'ingest_sender_defaults': [{'pattern': '@teamsnap.com', 'calendar_id': 'ben@cal'}],
        'default_calendar_id': 'family@cal',
    })

    storage.add_passenger({'name': 'Lily', 'hashtags': [], 'calendar_ids': ['lily@cal']})

    real_fetch = email_ingest.fetch_new_messages
    real_extract = email_ingest.extract_items
    try:
        msgs = [
            _fake_msg(11, 'coach.dan@teamsnap.com', 'Game Saturday', 'Game 10am'),
            _fake_msg(12, 'parent@personal.com', 'Fwd: Picture Day', 'Picture day info'),
        ]
        email_ingest.fetch_new_messages = lambda settings: (msgs, None)

        def fake_extract(subject, from_addr, body, names):
            if 'teamsnap' in from_addr:
                return [
                    {'kind': 'event', 'title': 'Soccer Game', 'date': IN_5_DAYS,
                     'start_time': '10:00', 'end_time': '11:00', 'location': 'Riverside',
                     'member_name': 'Ben', 'confidence': 0.9},
                    {'kind': 'event', 'title': 'Junk', 'date': IN_5_DAYS, 'confidence': 0.1},
                ]
            return [{'kind': 'event', 'title': 'Picture Day', 'date': IN_5_DAYS,
                     'member_name': 'Lily', 'confidence': 0.85},
                    {'kind': 'event', 'title': 'Fall Festival', 'date': IN_5_DAYS,
                     'member_name': None, 'confidence': 0.8}]
        email_ingest.extract_items = fake_extract

        s = email_ingest.run_ingest()
        check(s['checked'] == 2 and s['proposed'] == 3,
              f"every message analyzed, incl. a manual forward: {s}")
        props = {p['title']: p for p in storage.get_proposals('proposed')}
        check(props['Soccer Game']['calendar_id'] == 'ben@cal',
              "sender default prefills the target calendar (wins over member guess)")
        check(props['Picture Day']['calendar_id'] == 'lily@cal',
              "no sender default -> LLM member guess resolves to that kid's calendar")
        check(props['Fall Festival']['calendar_id'] == 'family@cal',
              "no owner -> starred family default calendar")
        check(props['Soccer Game']['source_from'] == 'coach.dan@teamsnap.com', "source recorded")
        log = storage.get_ingest_log()
        check(any(r['outcome'].startswith('proposed 1') for r in log)
              and any(r['outcome'].startswith('proposed 2') for r in log),
              "both messages logged as proposed")

        # Re-run with the same content: dedupe keeps the queue clean even
        # after the parent ignores the proposal.
        storage.update_proposal(props['Soccer Game']['id'], {'status': 'ignored'})
        s2 = email_ingest.run_ingest()
        check(s2['proposed'] == 0, f"duplicate (even vs ignored) not re-proposed: {s2}")

        # Extraction failure is logged, not fatal.
        def boom(*a, **kw):
            raise RuntimeError('llm down')
        email_ingest.extract_items = boom
        s3 = email_ingest.run_ingest()
        check(s3['checked'] == 2 and s3['proposed'] == 0, "extraction failure isolated")
        check(any(r['outcome'].startswith('error: extraction failed') for r in storage.get_ingest_log()),
              "extraction failure logged")

        # No mailbox configured: quiet no-op summary.
        storage.patch_settings({'ingest_email_user': ''})
        email_ingest.fetch_new_messages = real_fetch
        s4 = email_ingest.run_ingest()
        check(s4['error'] == 'no mailbox configured', f"unconfigured mailbox reported: {s4}")
    finally:
        email_ingest.fetch_new_messages = real_fetch
        email_ingest.extract_items = real_extract


def test_sender_blocklist():
    """The app used to spot a sender you kept ignoring and send you to Gmail to
    build a filter — advice, not an action, for something it could settle in
    one click. Blocking happens BEFORE extraction (so the LLM call is the
    saving, not just the clicks) and is always recorded, because mail that
    vanishes without trace is exactly what makes filters unnerving."""
    print("intake sender blocklist ...")
    storage.ingest_log_table.truncate()
    storage.patch_settings({
        'ingest_email_enabled': True,
        'ingest_email_user': 'family@test',
        'ingest_email_password': 'x',
        'ingest_sender_defaults': [],
        'ingest_sender_blocklist': [{'pattern': '@teamsnap.com'}],
    })

    # The matcher: one substring test shared with sender_default, so a domain
    # entry catches the rotating addresses these platforms actually send from.
    check(email_ingest.sender_blocked('coach.dan@teamsnap.com',
                                      [{'pattern': '@teamsnap.com'}]),
          "a domain entry blocks an address at that domain")
    check(email_ingest.sender_blocked('bounce+7f3a@teamsnap.com',
                                      [{'pattern': '@teamsnap.com'}]),
          "including the machine-generated ones a literal address would miss")
    check(not email_ingest.sender_blocked('coach@school.org',
                                          [{'pattern': '@teamsnap.com'}]),
          "and nothing else")

    real_fetch = email_ingest.fetch_new_messages
    real_extract = email_ingest.extract_items
    extracted = []
    try:
        email_ingest.fetch_new_messages = lambda settings: ([
            _fake_msg(21, 'coach.dan@teamsnap.com', 'Game Saturday', 'Game 10am'),
            _fake_msg(22, 'office@school.org', 'Picture Day', 'Picture day info'),
        ], None)

        def spy_extract(subject, from_addr, body, names):
            extracted.append(from_addr)
            return []
        email_ingest.extract_items = spy_extract

        s = email_ingest.run_ingest()
        check(extracted == ['office@school.org'],
              f"the blocked sender never reaches extraction — that is the whole "
              f"saving, one LLM call per message not made: {extracted}")
        check(s['checked'] == 2 and s['skipped'] == 1,
              f"still counted as seen, not silently dropped: {s}")
        check(any('skipped: sender blocked' in (r.get('outcome') or '')
                  for r in storage.get_ingest_log()),
              "and the skip is in the record, so the day that sender starts "
              "mailing something real there is evidence rather than a mystery")
    finally:
        email_ingest.fetch_new_messages = real_fetch
        email_ingest.extract_items = real_extract
        storage.patch_settings({'ingest_sender_blocklist': []})


def test_past_ignores_can_still_be_blocked():
    """The offer used to hang off a PENDING proposal card — the transient
    thing. Ignore everything a sender sends and the cards leave the queue, so
    the offer disappeared exactly when the family had most thoroughly
    demonstrated they wanted it. The ledger is never pruned, so the answer
    reaches back however long ago the ignoring happened."""
    print("retroactive sender blocking ...")
    import main
    storage.event_proposals_table.truncate()
    storage.patch_settings({'ingest_sender_blocklist': []})

    def _prop(sender, status, title='X'):
        pid = storage.add_proposal({'title': title, 'source_from': sender,
                                    'source_subject': 'Weekly newsletter'})
        storage.update_proposal(pid, {'status': status})

    for _ in range(4):
        _prop('news@spam-league.com', 'ignored')
    _prop('office@school.org', 'ignored')
    _prop('office@school.org', 'approved')
    _prop('coach@team.org', 'ignored')          # one ignore only

    rows = {r['sender']: r for r in main.ignored_senders(min_ignored=2)}
    check('news@spam-league.com' in rows and rows['news@spam-league.com']['ignored'] == 4,
          f"a sender with nothing but ignores is offered, with no live proposal "
          f"anywhere in the queue: {list(rows)}")
    check(rows['news@spam-league.com']['domain'] == '@spam-league.com',
          "and the domain reading is offered alongside the address")
    check('coach@team.org' not in rows,
          "a single ignore is not a pattern")

    both = main.ignored_senders(min_ignored=1)
    school = {r['sender']: r for r in both}.get('office@school.org')
    check(school and school['approved'] == 1,
          "a sender you sometimes act on still reports its approvals — a count "
          "of ignores alone would hide that this one is useful")
    check([r['sender'] for r in both][-1] == 'office@school.org',
          "and it sorts last, behind the senders you never keep anything from")

    # Blocking removes it from the offer: there is nothing left to decide.
    storage.patch_settings({'ingest_sender_blocklist': [{'pattern': '@spam-league.com'}]})
    after = [r['sender'] for r in main.ignored_senders(min_ignored=2)]
    check('news@spam-league.com' not in after,
          f"an already-blocked sender stops being offered: {after}")
    storage.patch_settings({'ingest_sender_blocklist': []})
    storage.event_proposals_table.truncate()


def test_the_block_is_reachable_by_hand():
    """Standing rule: no capability without a hand path. The offer has to be on
    the proposal itself — that is the moment the family is already looking at
    the sender they are tired of."""
    print("intake blocklist hand path ...")
    import os
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates')
    page = open(os.path.join(tpl, 'intake.html'), encoding='utf-8').read()
    check('blockSender' in page and 'senderDomain' in page,
          "both readings are offered from the card: this address, or the domain")
    check('Gmail filter' not in page,
          "and the old 'go build a Gmail filter yourself' advice is gone")
    check('unblockSender' in page and 'Blocked senders' in page,
          "the blocklist is visible and reversible on the page that made it")
    check('ignoredSenders' in page and 'Senders you keep ignoring' in page,
          "senders ignored in the PAST are reachable too — the offer must not "
          "depend on a proposal still sitting in the queue")
    check('canBlockRow' in page,
          "and Activity rows can block, which is the only place mail that never "
          "produced a proposal at all is visible")


def test_log_collapse():
    print("ingest log collapse ...")
    storage.ingest_log_table.truncate()
    # Repeated poll errors (mailbox unreachable, e.g. DNS outage) collapse
    # into one row with a count instead of flooding the capped log.
    for i in range(5):
        storage.add_ingest_log({'from': '', 'subject': '(poll)',
                                'outcome': 'error: IMAP error: [Errno -3] Temporary failure in name resolution',
                                'ts': 1000.0 + i * 600})
    log = storage.get_ingest_log()
    check(len(log) == 1, f"5 identical consecutive errors -> 1 row, got {len(log)}")
    check(log[0].get('count') == 5 and log[0].get('first_ts') == 1000.0
          and log[0].get('ts') == 1000.0 + 4 * 600,
          f"collapsed row carries count + first/latest ts, got {log[0]}")
    # A different outcome breaks the run; a later identical error starts a NEW
    # row (consecutive-only — chronology stays honest).
    storage.add_ingest_log({'from': 'a@b.c', 'subject': 'Newsletter',
                            'outcome': 'no actionable items', 'ts': 5000.0})
    storage.add_ingest_log({'from': '', 'subject': '(poll)',
                            'outcome': 'error: IMAP error: [Errno -3] Temporary failure in name resolution',
                            'ts': 6000.0})
    log = storage.get_ingest_log()
    check(len(log) == 3, f"non-identical rows never collapse, got {len(log)}")
    check(log[0].get('count') is None, "fresh error row after an interleaved row starts at count 1")
    storage.ingest_log_table.truncate()


def test_fuzzy_dedup():
    print("Fuzzy dedupe (ICS event vs rephrased email reminder) ...")
    day = IN_5_DAYS

    def prop(title, start_h=None, end_h=None):
        if start_h is None:
            return {'title': title, 'start': day, 'end': day}
        s = datetime.datetime.fromisoformat(f"{day}T{start_h}:00").astimezone()
        e = datetime.datetime.fromisoformat(f"{day}T{end_h}:00").astimezone()
        return {'title': title, 'start': s.isoformat(), 'end': e.isoformat()}

    def sched(title, start_h=None, end_h=None, day_offset=0):
        d = (datetime.date.fromisoformat(day) + datetime.timedelta(days=day_offset)).isoformat()
        if start_h is None:
            return {'title': title, 'start': d, 'end': d}
        s = datetime.datetime.fromisoformat(f"{d}T{start_h}:00").astimezone()
        e = datetime.datetime.fromisoformat(f"{d}T{end_h}:00").astimezone()
        return {'title': title, 'start': s.isoformat(), 'end': e.isoformat()}

    dup = email_ingest._is_duplicate

    # Same words, different order/punctuation, same times -> duplicate
    check(dup(prop('U12 Blue game vs. Eagles', '09:00', '10:30'),
              [], [sched('Game vs Eagles - U12 Blue', '09:00', '10:30')]),
          "reordered/punctuated title with matching times is a duplicate")

    # Rephrased with one extra word, same times -> duplicate (containment)
    check(dup(prop('Soccer game vs Eagles U12 Blue', '09:00', '10:30'),
              [], [sched('Game vs Eagles - U12 Blue', '09:00', '10:30')]),
          "superset word set with matching times is a duplicate")

    # Two DIFFERENT games, same 9am slot (two kids' teams) -> NOT duplicates
    check(not dup(prop('Game vs Hawks', '09:00', '10:30'),
                  [], [sched('Game vs Eagles', '09:00', '10:30')]),
          "different opponent at the same time is kept")

    # Same rephrased title on a DIFFERENT day -> not a duplicate
    check(not dup(prop('U12 Blue game vs. Eagles', '09:00', '10:30'),
                  [], [sched('Game vs Eagles - U12 Blue', '09:00', '10:30', day_offset=1)]),
          "same title on another day is kept")

    # All-day (no time evidence): identical word set still matches...
    check(dup(prop('Picture day - Riverside Elementary'),
              [], [sched('Riverside Elementary Picture Day')]),
          "all-day reordered title is a duplicate")
    # ...but moderate overlap without time evidence is kept
    check(not dup(prop('Fall festival setup'),
                  [], [sched('Fall festival cleanup')]),
          "moderate overlap without matching times is kept")

    # Fuzzy matching also applies against prior proposals (ignored included)
    check(dup(prop('U12 Blue game vs. Eagles', '09:00', '10:30'),
              [dict(sched('Game vs Eagles - U12 Blue', '09:00', '10:30'), status='ignored')], []),
          "rephrased duplicate of an ignored proposal stays suppressed")


if __name__ == '__main__':
    test_mime_and_allowlist()
    test_normalize()
    test_run_ingest()
    test_sender_blocklist()
    test_past_ignores_can_still_be_blocked()
    test_the_block_is_reachable_by_hand()
    test_log_collapse()
    test_fuzzy_dedup()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)

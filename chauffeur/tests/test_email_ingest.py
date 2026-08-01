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

    allow = [{'pattern': '@teamsnap.com', 'calendar_id': 'ben@cal'},
             {'pattern': 'principal.smith', 'calendar_id': None}]
    check(email_ingest.sender_allowed('coach.dan@teamsnap.com', allow)['calendar_id'] == 'ben@cal',
          "domain pattern matches with default calendar")
    check(email_ingest.sender_allowed('PRINCIPAL.SMITH@district.org', allow) is not None,
          "case-insensitive name pattern matches")
    check(email_ingest.sender_allowed('spam@promo.com', allow) is None, "unlisted sender rejected")


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
        'ingest_allowlist': [{'pattern': '@teamsnap.com', 'calendar_id': 'ben@cal'}],
    })

    real_fetch = email_ingest.fetch_new_messages
    real_extract = email_ingest.extract_items
    try:
        msgs = [
            _fake_msg(11, 'coach.dan@teamsnap.com', 'Game Saturday', 'Game 10am'),
            _fake_msg(12, 'spam@promo.com', 'SALE', 'Buy now'),
        ]
        email_ingest.fetch_new_messages = lambda settings: (msgs, None)
        email_ingest.extract_items = lambda subject, from_addr, body, names: [
            {'kind': 'event', 'title': 'Soccer Game', 'date': IN_5_DAYS,
             'start_time': '10:00', 'end_time': '11:00', 'location': 'Riverside',
             'member_name': 'Ben', 'confidence': 0.9},
            {'kind': 'event', 'title': 'Junk', 'date': IN_5_DAYS, 'confidence': 0.1},
        ]

        s = email_ingest.run_ingest()
        check(s['checked'] == 2 and s['proposed'] == 1 and s['skipped'] == 1,
              f"one proposal, spam skipped: {s}")
        props = storage.get_proposals('proposed')
        check(len(props) == 1 and props[0]['calendar_id'] == 'ben@cal',
              "proposal stored with allowlist default calendar")
        check(props[0]['source_from'] == 'coach.dan@teamsnap.com', "source recorded")
        log = storage.get_ingest_log()
        check(any('skipped' in r['outcome'] for r in log), "skip logged")
        check(any(r['outcome'].startswith('proposed 1') for r in log), "proposal logged")

        # Re-run with the same content: dedupe keeps the queue clean even
        # after the parent ignores the proposal.
        storage.update_proposal(props[0]['id'], {'status': 'ignored'})
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


if __name__ == '__main__':
    test_mime_and_allowlist()
    test_normalize()
    test_run_ingest()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)

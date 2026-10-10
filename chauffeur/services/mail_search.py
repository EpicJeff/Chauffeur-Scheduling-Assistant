"""The family's own mailbox, searched. Spec: docs/superpowers/specs/2026-10-10-browse-missions-design.md §3.

Read-only: a fresh IMAP connection, SELECT INBOX readonly, one SEARCH, a few
FETCHes, logout. The ingest cursor (email_ingest) is never touched; no model
is called; attachments are not read. The tools in agent_tools_v2 gate who
may ask (parent/adult); this module trusts its caller.
"""
import datetime
import email
import email.utils
import imaplib
import logging
import re
from typing import Optional

from services import storage

logger = logging.getLogger(__name__)

SNIPPET_CHARS = 400
BODY_CHARS = 6000
MAX_LIMIT = 10
QUERY_CHARS = 200
MAX_WORDS = 6          # a model's query is a few words; more only bloats the SEARCH
WORD_CHARS = 40
NO_MAILBOX = 'No family mailbox is set up (Intake settings).'


def _connect(settings: dict):
    """Test seam: tests replace this with a fake IMAP object."""
    from services.email_ingest import _mailbox
    host, user, password = _mailbox(settings)
    conn = imaplib.IMAP4_SSL(host)
    conn.login(user, password)
    return conn


def _configured(settings: dict) -> bool:
    from services.email_ingest import _mailbox
    _, user, password = _mailbox(settings)
    return bool(user and password)


def _fold(word: str) -> str:
    """7-bit: imaplib encodes every str criterion as ASCII, and an RFC 3501
    quoted-string is 7-bit anyway, so an accent is folded (café -> cafe) and
    a word with nothing left after folding is dropped by the caller."""
    import unicodedata
    w = unicodedata.normalize('NFKD', word or '').encode('ascii', 'ignore').decode()
    return re.sub(r'[\x00-\x1f\x7f]', '', w)


def _quote(word: str) -> str:
    # IMAP quoted-string: backslash-escape quotes and backslashes.
    w = word.replace('\\', '\\\\').replace('"', '\\"')
    return f'"{w}"'


def _criteria(query: str, since_days: int) -> list:
    words = [w for w in (_fold(w)[:WORD_CHARS] for w in re.split(r'\s+', (query or '').strip()[:QUERY_CHARS])) if w][:MAX_WORDS]
    since = (datetime.date.today() - datetime.timedelta(days=max(1, int(since_days or 365)))).strftime('%d-%b-%Y')
    if not words:
        return ['SINCE', since]
    # Each word may match FROM, SUBJECT or TEXT; words are OR'd so a model's
    # natural query ("cafe dishwasher") finds either.
    terms = []
    for w in words:
        q = _quote(w)
        terms.append(f'(OR (OR FROM {q} SUBJECT {q}) TEXT {q})')
    expr = terms[0]
    for t in terms[1:]:
        expr = f'(OR {expr} {t})'
    return ['SINCE', since, expr]


def _parse(raw: bytes, uid: int) -> dict:
    from services.email_ingest import _decode_header, _from_address, _body_text
    msg = email.message_from_bytes(raw)
    date = ''
    try:
        d = email.utils.parsedate_to_datetime(msg.get('Date', ''))
        date = d.isoformat()
    except Exception:
        pass
    return {'uid': uid, 'from': _from_address(msg), 'date': date,
            'subject': _decode_header(msg.get('Subject', '')) or '(no subject)',
            'text': _body_text(msg)}


def _fetch(conn, uid: int) -> Optional[dict]:
    status, data = conn.uid('FETCH', str(uid), '(RFC822)')
    if status != 'OK' or not data or data[0] is None:
        return None
    return _parse(data[0][1], uid)


def search(query: str, since_days: int = 365, limit: int = 5, settings: dict = None) -> dict:
    settings = settings if settings is not None else (storage.get_settings() or {})
    if not _configured(settings):
        return {'status': 'error', 'message': NO_MAILBOX}
    limit = max(1, min(int(limit or 5), MAX_LIMIT))
    try:
        conn = _connect(settings)
        try:
            conn.select('INBOX', readonly=True)
            status, data = conn.uid('SEARCH', None, *_criteria(query, since_days))
            if status != 'OK':
                return {'status': 'error', 'message': f'mailbox search failed: {status}'}
            uids = sorted((int(u) for u in (data[0].split() if data and data[0] else [])), reverse=True)[:limit]
            hits = []
            for u in uids:
                m = _fetch(conn, u)
                if not m:
                    continue
                hits.append({'uid': u, 'from': m['from'], 'date': m['date'], 'subject': m['subject'],
                             'snippet': ' '.join(m['text'].split())[:SNIPPET_CHARS]})
            return {'status': 'success', 'hits': hits}
        finally:
            try:
                conn.logout()
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"[mail_search] search failed: {e}")
        return {'status': 'error', 'message': f'mailbox error: {str(e)[:120]}'}


def read(uid: int, settings: dict = None) -> dict:
    settings = settings if settings is not None else (storage.get_settings() or {})
    if not _configured(settings):
        return {'status': 'error', 'message': NO_MAILBOX}
    try:
        conn = _connect(settings)
        try:
            conn.select('INBOX', readonly=True)
            m = _fetch(conn, int(uid))
            if not m:
                return {'status': 'error', 'message': 'No such message.'}
            return {'status': 'success', 'uid': int(uid), 'from': m['from'], 'date': m['date'],
                    'subject': m['subject'], 'text': m['text'][:BODY_CHARS]}
        finally:
            try:
                conn.logout()
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"[mail_search] read failed: {e}")
        return {'status': 'error', 'message': f'mailbox error: {str(e)[:120]}'}

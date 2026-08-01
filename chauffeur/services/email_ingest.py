"""Email intake (intake arc phase 2 — docs/roadmap.md).

A dedicated family mailbox (Gmail + app password, polled over IMAP — Gmail's
API doesn't allow service accounts on consumer accounts, and OAuth flows are
clunky in a headless add-on) receives auto-forwarded school/team email. Each
poll: fetch messages newer than the stored UID cursor, keep only allowlisted
senders, run LLM extraction ("date-bound actionable items for THIS family"),
normalize + dedupe, and store surviving items as PROPOSALS a parent approves
on /intake — approval writes a real Google Calendar event; nothing enters the
family calendar without a human tap.

Every message in the mailbox is analyzed — THE MAILBOX IS THE FILTER. The
family decides upstream what arrives (Gmail auto-forward filters, manual
forwards), so a Chauffeur-side sender gate would be a second copy of the same
decision — and would break manual forwards, which arrive From the forwarding
parent, not the original sender. Sender patterns survive only as optional
ROUTING hints (ingest_sender_defaults prefills a proposal's target calendar).

Noise defense (the design goal is precision — a noisy queue teaches the
parent to ignore it, which is worse than no queue):
1. the mailbox is curated by the family + Gmail's own spam filtering;
2. the extraction prompt is a relevance gate — newsletters with no
   date-bound family action return zero items;
3. confidence floor;
4. dedupe against existing proposals (any status — an ignored proposal must
   NOT reappear on the next newsletter resend) and the schedule cache;
5. every message logs an outcome row (ingest_log) so false negatives are
   auditable on /intake instead of silent.

First run on a mailbox stores the current max UID and processes nothing —
subscribing must not storm through years of backlog.
"""
import datetime
import email
import email.header
import imaplib
import re

from services import storage

DEFAULT_HOST = 'imap.gmail.com'
MAX_MESSAGES_PER_RUN = 20
MAX_BODY_CHARS = 7000
CONFIDENCE_FLOOR = 0.4
MAX_DAYS_AHEAD = 400


# --- message plumbing -------------------------------------------------------

def _decode_header(value) -> str:
    if not value:
        return ''
    parts = []
    for chunk, enc in email.header.decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(enc or 'utf-8', errors='replace'))
        else:
            parts.append(chunk)
    return ''.join(parts).strip()


def _from_address(msg) -> str:
    raw = _decode_header(msg.get('From', ''))
    m = re.search(r'<([^>]+)>', raw)
    return (m.group(1) if m else raw).strip().lower()


def _strip_html(html: str) -> str:
    html = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', ' ', html)
    html = re.sub(r'(?i)<br\s*/?>|</p>|</div>|</tr>|</li>', '\n', html)
    text = re.sub(r'<[^>]+>', ' ', html)
    text = (text.replace('&nbsp;', ' ').replace('&amp;', '&')
            .replace('&lt;', '<').replace('&gt;', '>').replace('&#39;', "'")
            .replace('&quot;', '"'))
    return re.sub(r'[ \t]{2,}', ' ', re.sub(r'\n{3,}', '\n\n', text)).strip()


def _body_text(msg) -> str:
    """Prefer text/plain; fall back to de-tagged text/html."""
    plain, html = [], []
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        ctype = part.get_content_type()
        if ctype not in ('text/plain', 'text/html'):
            continue
        if part.get('Content-Disposition', '').startswith('attachment'):
            continue
        try:
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or 'utf-8'
            text = payload.decode(charset, errors='replace')
        except Exception:
            continue
        (plain if ctype == 'text/plain' else html).append(text)
    body = '\n'.join(plain).strip() or _strip_html('\n'.join(html))
    return body[:MAX_BODY_CHARS]


def sender_default(from_addr: str, sender_defaults: list):
    """Optional routing hint: the first entry whose pattern (a lowercase
    substring, so '@school.org' and 'coach.dan' work) appears in the From
    address. None just means no prefilled calendar — never a skip."""
    addr = (from_addr or '').lower()
    for entry in sender_defaults or []:
        pattern = (entry.get('pattern') or '').strip().lower()
        if pattern and pattern in addr:
            return entry
    return None


def fetch_new_messages(settings: dict):
    """Fetch messages with UID greater than the stored cursor. Returns
    (messages, error) where each message is {uid, from, subject, text}."""
    host = settings.get('ingest_email_host') or DEFAULT_HOST
    user = (settings.get('ingest_email_user') or '').strip()
    password = (settings.get('ingest_email_password') or '').strip()
    if not user or not password:
        return [], 'no mailbox configured'

    cursor_key = f'ingest_last_uid::{user}'
    last_uid = int(storage.get_app_state(cursor_key) or 0)

    try:
        conn = imaplib.IMAP4_SSL(host)
        try:
            conn.login(user, password)
            conn.select('INBOX', readonly=True)
            status, data = conn.uid('SEARCH', None, 'ALL')
            if status != 'OK':
                return [], f'IMAP search failed: {status}'
            uids = [int(u) for u in (data[0].split() if data and data[0] else [])]
            if not uids:
                return [], None
            if last_uid == 0:
                # First contact: start the cursor at the top, skip backlog.
                storage.set_app_state(cursor_key, max(uids))
                return [], None
            new_uids = sorted(u for u in uids if u > last_uid)[:MAX_MESSAGES_PER_RUN]
            messages = []
            highest = last_uid
            for uid in new_uids:
                status, msg_data = conn.uid('FETCH', str(uid), '(RFC822)')
                highest = max(highest, uid)
                if status != 'OK' or not msg_data or msg_data[0] is None:
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                messages.append({
                    'uid': uid,
                    'from': _from_address(msg),
                    'subject': _decode_header(msg.get('Subject', '')) or '(no subject)',
                    'text': _body_text(msg),
                })
            if highest > last_uid:
                storage.set_app_state(cursor_key, highest)
            return messages, None
        finally:
            try:
                conn.logout()
            except Exception:
                pass
    except Exception as e:
        return [], f'IMAP error: {e}'


# --- extraction -------------------------------------------------------------

EXTRACTION_SYSTEM = """You extract family calendar items from a school/team email.
Return ONLY valid JSON: {"items": [...]}. Each item:
{
  "kind": "event" | "task",
  "title": "short title",
  "date": "YYYY-MM-DD",
  "start_time": "HH:MM" or null (null = all-day; for kind=task the deadline date),
  "end_time": "HH:MM" or null,
  "location": "..." or null,
  "member_name": one of the family names below, or null if unclear,
  "notes": one short sentence of context or null,
  "confidence": 0.0-1.0
}
Rules:
- Only include items that require this family to BE somewhere or DO something
  by a date (games, practices, concerts, picture day, permission slip due,
  payment due). kind=task for deadlines that are not appointments.
- Newsletters, promotions, general announcements with no date-bound action:
  return {"items": []}. Most emails contain NOTHING actionable — an empty
  list is the expected common answer, never invent items.
- Resolve relative dates ("this Friday", "next Tuesday") using the current
  date given below. If a date cannot be resolved to a specific day, omit the
  item entirely.
- One item per distinct date. A schedule listing 5 games = 5 items.
- Do not include items more than a year away, or in the past."""


def extract_items(subject: str, from_addr: str, body: str, member_names: list) -> list:
    """LLM relevance gate + extraction. Returns raw item dicts ([] on error)."""
    from services.llm import _call_llm_json
    settings = storage.get_settings() or {}
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key:
        raise RuntimeError('no LLM API key configured')
    model = settings.get('agent_primary_model') or 'gemini-3.5-flash'

    now = datetime.datetime.now().astimezone()
    prompt = (f"Current date: {now.strftime('%A %Y-%m-%d')}\n"
              f"Family members: {', '.join(member_names) or '(unknown)'}\n\n"
              f"Email from: {from_addr}\nSubject: {subject}\n\n{body}")
    res = _call_llm_json('gemini', '', api_key, model, EXTRACTION_SYSTEM, prompt,
                         temperature=0.1, timeout_s=60)
    if not isinstance(res, dict):
        return []
    if res.get('error'):
        raise RuntimeError(str(res['error']))
    items = res.get('items')
    return items if isinstance(items, list) else []


def normalize_item(item: dict, now=None) -> dict:
    """Raw LLM item -> proposal fields, or None if malformed/out of window."""
    if now is None:
        now = datetime.datetime.now().astimezone()
    try:
        kind = item.get('kind') if item.get('kind') in ('event', 'task') else 'event'
        title = (item.get('title') or '').strip()
        date_str = (item.get('date') or '').strip()
        if not title or not date_str:
            return None
        day = datetime.date.fromisoformat(date_str)
        confidence = float(item.get('confidence') or 0)
    except Exception:
        return None
    if confidence < CONFIDENCE_FLOOR:
        return None
    if day < now.date() or day > now.date() + datetime.timedelta(days=MAX_DAYS_AHEAD):
        return None

    start_time = (item.get('start_time') or '').strip() or None
    end_time = (item.get('end_time') or '').strip() or None
    all_day = kind == 'task' or not start_time
    if all_day:
        start = day.isoformat()
        end = (day + datetime.timedelta(days=1)).isoformat()
    else:
        try:
            h, m = [int(x) for x in start_time.split(':')[:2]]
            start_dt = datetime.datetime.combine(day, datetime.time(h, m)).astimezone()
            if end_time:
                eh, em = [int(x) for x in end_time.split(':')[:2]]
                end_dt = datetime.datetime.combine(day, datetime.time(eh, em)).astimezone()
                if end_dt <= start_dt:
                    end_dt = start_dt + datetime.timedelta(hours=1)
            else:
                end_dt = start_dt + datetime.timedelta(hours=1)
            start, end = start_dt.isoformat(), end_dt.isoformat()
        except Exception:
            return None

    return {
        'kind': kind,
        'title': title if kind == 'event' else f'📌 {title}',
        'start': start,
        'end': end,
        'all_day': all_day,
        'location': (item.get('location') or '').strip() or None,
        'notes': (item.get('notes') or '').strip() or None,
        'member_name': (item.get('member_name') or '').strip() or None,
        'confidence': round(confidence, 2),
    }


def _is_duplicate(prop: dict, existing: list, sched_events: list) -> bool:
    """Same title (case-insensitive) on the same day as any prior proposal
    (any status — ignored must stay ignored) or any scheduled event."""
    title = prop['title'].lower().lstrip('📌 ').strip()
    day = prop['start'][:10]
    for p in existing:
        if (p.get('start') or '')[:10] == day \
                and (p.get('title') or '').lower().lstrip('📌 ').strip() == title:
            return True
    for ev in sched_events:
        ev_title = (ev.get('title') or '').lower().strip()
        if (ev.get('start') or '')[:10] == day and ev_title \
                and (title in ev_title or ev_title in title):
            return True
    return False


def _calendar_for_member_name(name: str):
    """Resolve the LLM's member-name guess to that person's calendar (their
    passenger calendar first — kid events land there — else their driver
    calendar). Used to prefill a proposal's target when no sender default
    matched; the parent still confirms on /intake."""
    if not name:
        return None
    target = name.strip().lower()
    member = next((m for m in storage.get_all_members()
                   if (m.get('name') or '').strip().lower() == target), None)
    if not member:
        return None
    if member.get('passenger_id'):
        for p in storage.get_all_passengers():
            if p.get('id') == member['passenger_id'] and p.get('calendar_ids'):
                return p['calendar_ids'][0]
    if member.get('driver_id'):
        for d in storage.get_all_drivers():
            if d.get('id') == member['driver_id'] and d.get('calendar_ids'):
                return d['calendar_ids'][0]
    return None


# --- orchestration ----------------------------------------------------------

def run_ingest() -> dict:
    """One poll: fetch → allowlist → extract → normalize → dedupe → propose.
    Returns {'checked', 'proposed', 'error'}."""
    summary = {'checked': 0, 'proposed': 0, 'error': None}
    settings = storage.get_settings() or {}
    sender_defaults = settings.get('ingest_sender_defaults') or []

    messages, err = fetch_new_messages(settings)
    if err:
        summary['error'] = err
        if err != 'no mailbox configured':
            storage.add_ingest_log({'from': '', 'subject': '(poll)', 'outcome': f'error: {err}'})
        return summary

    if not messages:
        return summary

    member_names = [m.get('name') for m in storage.get_all_members() if m.get('name')]
    existing = storage.get_proposals()
    sched_events = (storage.get_cached_schedule() or {}).get('events', [])

    for msg in messages:
        summary['checked'] += 1
        log = {'from': msg['from'], 'subject': msg['subject'][:120]}
        entry = sender_default(msg['from'], sender_defaults)
        try:
            items = extract_items(msg['subject'], msg['from'], msg['text'], member_names)
        except Exception as e:
            storage.add_ingest_log({**log, 'outcome': f'error: extraction failed ({e})'})
            continue

        proposed_here = dropped = 0
        for item in items:
            prop = normalize_item(item)
            if prop is None:
                dropped += 1
                continue
            if _is_duplicate(prop, existing, sched_events):
                dropped += 1
                continue
            prop.update({
                'source': 'email',
                'source_from': msg['from'],
                'source_subject': msg['subject'][:200],
                'calendar_id': (entry or {}).get('calendar_id')
                    or _calendar_for_member_name(prop.get('member_name')),
            })
            storage.add_proposal(prop)
            existing.append(prop)
            proposed_here += 1

        summary['proposed'] += proposed_here
        if proposed_here:
            outcome = f'proposed {proposed_here} item{"s" if proposed_here != 1 else ""}'
            if dropped:
                outcome += f' ({dropped} dropped as duplicate/low-confidence)'
        elif dropped:
            outcome = f'nothing new ({dropped} dropped as duplicate/low-confidence)'
        else:
            outcome = 'no actionable items'
        storage.add_ingest_log({**log, 'outcome': outcome})

    return summary

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
import threading

from services import storage

# The 10-minute loop and the manual "Check mailbox now" button share the UID
# cursor; serializing them prevents interleaved fetches (and the confusing
# "checked 0" race is reported honestly by the caller instead).
_run_lock = threading.Lock()

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


def sender_blocked(from_addr: str, blocklist: list):
    """The entry blocking this sender, or None.

    Deliberately the SAME lowercase-substring test `sender_default` uses, so
    one matcher governs routing and blocking and the two can never drift. That
    is also what makes '@teamsnap.com' work as an entry: school and team
    platforms rotate their sending addresses (`noreply@`, `bounce+7f3a@`), so
    blocking the literal From line lets the next message straight through and
    the family concludes the button is broken."""
    addr = (from_addr or '').lower()
    for entry in blocklist or []:
        pattern = (entry.get('pattern') if isinstance(entry, dict) else entry) or ''
        pattern = str(pattern).strip().lower()
        if pattern and pattern in addr:
            return entry if isinstance(entry, dict) else {'pattern': pattern}
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
  "member_name": one of the family names below, or null if unclear OR if the
    item is for multiple family members / the whole family,
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
    from services import model_pools
    settings = storage.get_settings() or {}
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key:
        raise RuntimeError('no LLM API key configured')

    now = datetime.datetime.now().astimezone()
    prompt = (f"Current date: {now.strftime('%A %Y-%m-%d')}\n"
              f"Family members: {', '.join(member_names) or '(unknown)'}\n\n"
              f"Email from: {from_addr}\nSubject: {subject}\n\n{body}")
    # Background tier: nobody is waiting on ingest, so burn the huge gemma
    # quota first (180s cap for its 44-180s latency) and keep the fast lite
    # pool free for interactive chat.
    res = model_pools.call_pool_json('background', api_key, EXTRACTION_SYSTEM, prompt,
                                     temperature=0.1, timeout_s=60, gemma_timeout_s=180,
                                     settings=settings)
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


def _title_tokens(s: str) -> set:
    return set(re.findall(r'[a-z0-9]+', (s or '').lower()))


def _ts(iso: str):
    try:
        return datetime.datetime.fromisoformat(iso).timestamp()
    except Exception:
        return None


def _titles_similar(a_tokens: set, b_tokens: set, times_match: bool) -> bool:
    """Token-set comparison: word order and punctuation never matter. One
    title containing all of the other's words is a match outright; otherwise
    Jaccard overlap decides, with a looser bar when the clock times agree.
    Thresholds: 0.6 with matching times keeps 'Game vs Eagles' vs 'Game vs
    Hawks' (two kids, same 9am slot, overlap 0.5) as separate events while
    catching any real rephrasing; 0.75 without time evidence."""
    if not a_tokens or not b_tokens:
        return False
    if a_tokens <= b_tokens or b_tokens <= a_tokens:
        return True
    overlap = len(a_tokens & b_tokens) / len(a_tokens | b_tokens)
    return overlap >= (0.6 if times_match else 0.75)


def _is_duplicate(prop: dict, existing: list, sched_events: list) -> bool:
    """Same day as any prior proposal (any status — ignored must stay
    ignored) or any scheduled event, with the same/contained title OR a
    near-identical word set. Email reminders routinely rephrase what an ICS
    feed already created ('Game vs Eagles - U12 Blue' vs 'U12 Blue game vs.
    Eagles'), so exact/substring matching alone let duplicates through;
    matching start/end times lower the similarity bar."""
    title = prop['title'].lower().lstrip('📌 ').strip()
    tokens = _title_tokens(title)
    day = prop['start'][:10]
    p_start, p_end = _ts(prop.get('start')), _ts(prop.get('end'))

    def _same(o_title, o_start, o_end):
        o_title = (o_title or '').lower().lstrip('📌 ').strip()
        if not o_title:
            return False
        if title == o_title or title in o_title or o_title in title:
            return True
        times_match = (p_start is not None and (s := _ts(o_start)) is not None
                       and abs(p_start - s) <= 30 * 60
                       and (p_end is None or (e := _ts(o_end)) is None
                            or abs(p_end - e) <= 30 * 60))
        return _titles_similar(tokens, _title_tokens(o_title), times_match)

    for p in existing:
        if (p.get('start') or '')[:10] == day \
                and _same(p.get('title'), p.get('start'), p.get('end')):
            return True
    for ev in sched_events:
        if (ev.get('start') or '')[:10] == day \
                and _same(ev.get('title'), ev.get('start'), ev.get('end')):
            return True
    return False


def learned_route(from_addr: str, kind: str):
    """Deterministic learned prior (intake phase-2 (a)): the target a parent
    last APPROVED for this sender, recorded by main._record_intake_feedback.
    Explicit sender defaults still win. 'errand' targets are never prefilled
    (they need per-proposal location/duration), and a kid's task list only
    prefills for kind='task'."""
    if not from_addr:
        return None
    routes = storage.get_app_state('intake_learned_routes') or {}
    target = (routes.get(from_addr.lower()) or {}).get('target')
    if not target or target == 'errand':
        return None
    if target.startswith('tasks:') and kind != 'task':
        return None
    return target


def _calendar_for_member_name(name: str):
    """Resolve the LLM's member-name guess to that person's calendar. Calendars
    are person-level now, so their own list answers first — including for
    someone with no passenger or driver profile at all. The link mirrors stay as
    a fallback for a member the migration hasn't touched. Used to prefill a
    proposal's target when no sender default matched; the parent still confirms
    on /intake."""
    if not name:
        return None
    target = name.strip().lower()
    member = next((m for m in storage.get_all_members()
                   if (m.get('name') or '').strip().lower() == target), None)
    if not member:
        return None
    if member.get('calendar_ids'):
        return member['calendar_ids'][0]
    if member.get('passenger_id'):
        for p in storage.get_all_passengers():
            if p.get('id') == member['passenger_id'] and p.get('calendar_ids'):
                return p['calendar_ids'][0]
    if member.get('driver_id'):
        for d in storage.get_all_drivers():
            if d.get('id') == member['driver_id'] and d.get('calendar_ids'):
                return d['calendar_ids'][0]
    return None


# --- vision capture (intake phase 3) ----------------------------------------

def run_photo_ingest(image_b64: str, mime: str, caption: str = '') -> dict:
    """One photo/screenshot → the same normalize/dedupe/propose pipeline as
    email. The extraction runs on the VISION tier (flash first — flyers and
    message screenshots are the hard case and volume is family-scale; gemma
    is text-only and never sees images). Returns {'checked', 'proposed',
    'error'} like run_ingest."""
    import datetime as _dt
    from services import model_pools
    summary = {'checked': 1, 'proposed': 0, 'error': None}
    settings = storage.get_settings() or {}
    api_key = settings.get('llm_gemini_api_key', '')
    log = {'from': '📸 photo', 'subject': (caption or '(photo)')[:120]}
    if not api_key:
        summary['error'] = 'no LLM API key configured'
        return summary

    member_names = [m.get('name') for m in storage.get_all_members() if m.get('name')]
    now = _dt.datetime.now().astimezone()
    prompt = (f"Current date: {now.strftime('%A %Y-%m-%d')}\n"
              f"Family members: {', '.join(member_names) or '(unknown)'}\n\n"
              "The attached image is a photo of a school/team flyer, schedule,"
              " permission slip, or a screenshot of a message thread."
              + (f"\nParent's note: {caption}" if caption else "")
              + "\n\nExtract the items from the image.")
    try:
        res = model_pools.call_pool_json(
            'vision', api_key, EXTRACTION_SYSTEM, prompt, temperature=0.1,
            timeout_s=90, settings=settings,
            images=[{'mime': mime or 'image/jpeg', 'b64': image_b64}])
        if not isinstance(res, dict):
            raise RuntimeError('bad response')
        if res.get('error'):
            raise RuntimeError(str(res['error']))
        items = res.get('items')
        items = items if isinstance(items, list) else []
    except Exception as e:
        summary['error'] = f'extraction failed ({e})'
        storage.add_ingest_log({**log, 'outcome': f'error: {summary["error"]}'})
        return summary

    existing = storage.get_proposals()
    sched_events = (storage.get_cached_schedule() or {}).get('events', [])
    dropped = 0
    for item in items:
        prop = normalize_item(item)
        if prop is None or _is_duplicate(prop, existing, sched_events):
            dropped += 1
            continue
        prop.update({
            'source': 'photo',
            'source_from': '',
            'source_subject': (caption or '(photo)')[:200],
            # No sender to learn from — member guess > default calendar.
            'calendar_id': _calendar_for_member_name(prop.get('member_name'))
                or (settings.get('default_calendar_id') or None),
        })
        storage.add_proposal(prop)
        existing.append(prop)
        summary['proposed'] += 1

    n = summary['proposed']
    if n:
        outcome = f'proposed {n} item{"s" if n != 1 else ""}'
        if dropped:
            outcome += f' ({dropped} dropped as duplicate/low-confidence)'
    elif dropped:
        outcome = f'nothing new ({dropped} dropped as duplicate/low-confidence)'
    else:
        outcome = 'no actionable items'
    storage.add_ingest_log({**log, 'outcome': outcome})
    return summary


# --- orchestration ----------------------------------------------------------

def run_ingest() -> dict:
    """One poll: fetch → extract → normalize → dedupe → propose.
    Returns {'checked', 'proposed', 'error'}. Serialized under _run_lock."""
    with _run_lock:
        return _run_ingest_locked()


def _run_ingest_locked() -> dict:
    summary = {'checked': 0, 'proposed': 0, 'skipped': 0, 'error': None}
    settings = storage.get_settings() or {}
    sender_defaults = settings.get('ingest_sender_defaults') or []
    blocklist = settings.get('ingest_sender_blocklist') or []

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

        # Blocked senders are skipped BEFORE extraction — that is the whole
        # saving, one LLM call per message not made. Still counted, still
        # logged: silent disappearance is what makes mail filters unnerving,
        # and the day the athletics office starts sending real game schedules
        # from a blocked address, the Activity list is the evidence.
        blocked = sender_blocked(msg['from'], blocklist)
        if blocked:
            summary['skipped'] += 1
            storage.add_ingest_log({**log, 'outcome': 'skipped: sender blocked '
                                                      f"({blocked.get('pattern')})",
                                    'skipped': True})
            continue

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
                # Routing tiers: explicit sender default > learned prior
                # (last approved target for this sender) > LLM member guess >
                # the family's starred default calendar (whole-family events
                # land there; attendees get tagged after approval).
                'calendar_id': (entry or {}).get('calendar_id')
                    or learned_route(msg['from'], prop['kind'])
                    or _calendar_for_member_name(prop.get('member_name'))
                    or (settings.get('default_calendar_id') or None),
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

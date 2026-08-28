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


def sender_blocked(from_addr: str, blocklist: list, subject=None):
    """The skip rule that catches this message, or None.

    The address test is deliberately the SAME lowercase-substring test
    `sender_default` uses, so one matcher governs routing and skipping and the
    two can never drift. That is what makes '@teamsnap.com' work as an entry:
    school and team platforms rotate their sending addresses (`noreply@`,
    `bounce+7f3a@`), so a literal From-line block lets the next message
    straight through and the family concludes the button is broken.

    An entry may also carry `keywords`, which turns blocking into FILTERING —
    the real want is rarely "never hear from TeamSnap" and often "their
    reminders are useless because I subscribe to their calendar already".
    Keywords match the SUBJECT only: 'reminder' appears in half of all email
    footers, and matching the body would quietly eat real announcements.

    `subject=None` means no subject context (e.g. deciding whether a sender is
    fully handled), and then only unconditional entries can match — you cannot
    evaluate a keyword rule without the line it tests.
    """
    addr = (from_addr or '').lower()
    subj = (subject or '').lower()
    for entry in blocklist or []:
        if not isinstance(entry, dict):
            entry = {'pattern': entry}
        pattern = str(entry.get('pattern') or '').strip().lower()
        if not pattern or pattern not in addr:
            continue
        words = [str(k).strip().lower() for k in (entry.get('keywords') or [])
                 if str(k).strip()]
        if not words:
            return {**entry, 'pattern': pattern, 'matched_keyword': None}
        if subject is None:
            continue
        hit = next((w for w in words if w in subj), None)
        if hit:
            return {**entry, 'pattern': pattern, 'matched_keyword': hit}
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
  "confidence": 0.0-1.0,
  "duplicate_of": the exact title from ALREADY ON THE CALENDAR below that this
    item is the same real-world event as, or null,
  "supplies": [{"name": str, "qty": str or null, "why": short reason}] — things
    the family must BUY for this item, or [] (the usual answer)
}
Rules:
- ALREADY ON THE CALENDAR lists what the family has for these dates. Reminder
  emails usually describe something already there, and the family renames
  things ("Fall Picture Day Reminder" becomes "Lily - picture day"), so match
  on WHAT AND WHEN, not on wording. Set duplicate_of when it is plainly the
  same event: same day and the same activity, however differently named.
  Still return the item — never omit it, and never lower its confidence for
  this reason. Leave duplicate_of null if you are unsure.
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
- Do not include items more than a year away, or in the past.

SUPPLIES — physical things that have to be BOUGHT before the item happens
(poster board for the science fair, a shoebox for the food drive, cupcakes for
the class party). Rules, and they are strict because a wrong supply is worse
than a missed one:
- Buyable physical objects ONLY. Money is not a supply ("$5 for pizza day" is
  a payment — leave it in notes). Clothing the family already owns is not a
  supply ("wear team colours", "PE kit"). Things the school provides are not
  supplies.
- If you are not sure the family has to buy it, leave it out.
- NEVER invent a quantity. qty is what the source actually said, or null.
- why is a SHORT quote-like reason ("flyer says bring a shoebox").
- [] is the expected answer for most items. An empty list is correct and
  useful; a padded one poisons the list it lands on.
- An item that is ONLY a supply request with a deadline ("send in box tops by
  Friday") is kind=task with the supplies attached — never a supply with no
  item to hang it on."""


KNOWN_EVENTS_CAP = 120


def known_events_block(sched_events: list, existing: list = None) -> str:
    """A compact 'already on the calendar' list for the extraction prompt.

    Rides the extraction call that already happens, so semantic duplicate
    detection costs ZERO extra LLM requests. Titles and clock times only — the
    model needs to recognise the event, not schedule it.
    """
    seen, lines = set(), []
    for row in list(sched_events or []) + list(existing or []):
        start = str(row.get('start') or '')
        title = (row.get('title') or '').strip()
        if not title or len(start) < 10:
            continue
        stamp = f"{start[:10]} {start[11:16]}".strip() if len(start) > 10 else start[:10]
        line = f"- {stamp} {title}"
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
    lines.sort()
    return '\n'.join(lines[:KNOWN_EVENTS_CAP])


def extract_items(subject: str, from_addr: str, body: str, member_names: list,
                  known_block: str = '') -> list:
    """LLM relevance gate + extraction. Returns raw item dicts ([] on error)."""
    from services import model_pools
    settings = storage.get_settings() or {}
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key:
        raise RuntimeError('no LLM API key configured')

    now = datetime.datetime.now().astimezone()
    prompt = (f"Current date: {now.strftime('%A %Y-%m-%d')}\n"
              f"Family members: {', '.join(member_names) or '(unknown)'}\n\n"
              + (f"ALREADY ON THE CALENDAR:\n{known_block}\n\n" if known_block else '')
              + f"Email from: {from_addr}\nSubject: {subject}\n\n{body}")
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
        # The model's own duplicate call, carried through unjudged — the run
        # loop decides what to do with it, and always records the item.
        'duplicate_of': (item.get('duplicate_of') or '').strip() or None,
        'kind': kind,
        'title': title if kind == 'event' else f'📌 {title}',
        'start': start,
        'end': end,
        'all_day': all_day,
        'location': (item.get('location') or '').strip() or None,
        'notes': (item.get('notes') or '').strip() or None,
        'member_name': (item.get('member_name') or '').strip() or None,
        'confidence': round(confidence, 2),
        'supplies': _clean_supplies(item.get('supplies')),
    }


MAX_SUPPLIES = 8


def _clean_supplies(raw) -> list:
    """Sanitize the supplies array (A1).

    A malformed entry drops ON ITS OWN rather than killing the item: the date
    is the load-bearing half of a proposal and a garbled supply line must
    never cost the family the event. Same reasoning as the confidence floor
    applying per item and not per message.
    """
    out, seen = [], set()
    for s in (raw if isinstance(raw, list) else [])[:MAX_SUPPLIES]:
        if not isinstance(s, dict):
            continue
        name = str(s.get('name') or '').strip()[:80]
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        qty = s.get('qty')
        out.append({
            'name': name,
            # Free text, never parsed — the ShoppingItem rule, upheld here so
            # nothing downstream has to re-learn it.
            'qty': (str(qty).strip()[:24] or None) if qty else None,
            'why': str(s.get('why') or '').strip()[:120] or None,
        })
    return out


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


def _norm_place(s: str) -> str:
    """A location reduced to something comparable. An email says 'Riverside
    Park', a calendar says 'Riverside Park, 12 Mill Rd, Springfield' — same
    place, and neither string contains the other after punctuation."""
    return re.sub(r'[^a-z0-9]+', ' ', (s or '').lower()).strip()


def _places_match(a: str, b: str) -> bool:
    a, b = _norm_place(a), _norm_place(b)
    # 4 chars keeps 'gym' or a stray 'st' from matching half the calendar.
    if len(a) < 4 or len(b) < 4:
        return False
    return a == b or a in b or b in a


def _same_calendar(prop: dict, other: dict) -> bool:
    """Whether both land on the same person. The proposal's `calendar_id` is a
    routing GUESS, so this only ever corroborates — a wrong guess costs a
    missed dedupe (a visible duplicate), never a wrong one."""
    cal = (prop.get('calendar_id') or '').strip().lower()
    if not cal:
        return False
    others = other.get('calendar_ids') or ([other.get('calendar_id')]
                                           if other.get('calendar_id') else [])
    return cal in {str(c).strip().lower() for c in others if c}


def _is_duplicate(prop: dict, existing: list, sched_events: list):
    """What this proposal duplicates, or None.

    Two independent rules, because they fail in different directions:

    1. TITLE. Same day plus same/contained title or a near-identical word set.
       Catches rephrasing ('Game vs Eagles - U12 Blue' vs 'U12 Blue game vs.
       Eagles') but breaks the moment the family RENAMES an approved item —
       approval writes the edited title back onto the proposal and the
       calendar, so the next reminder's extraction is compared against your
       wording, not the school's. Adding a word ("Lily - picture day") drops
       the overlap under the bar, permanently, for that event.
    2. TIME + PLACE, title ignored. Same person at the same place at the same
       minute twice is a double-booking, not two events. Deliberately does NOT
       key on end time: `normalize_item` invents `end = start + 1h` whenever
       the email omits one, so requiring it to agree would fail against most
       real calendar entries. All-day items are excluded — they all share
       midnight, which would make "same start" meaningless.

    Returns {'title', 'start', 'source', 'rule'} describing the match, so the
    skip can be shown and undone rather than silently dropped.
    """
    title = prop['title'].lower().lstrip('📌 ').strip()
    tokens = _title_tokens(title)
    day = prop['start'][:10]
    p_start, p_end = _ts(prop.get('start')), _ts(prop.get('end'))
    p_timed = not prop.get('all_day') and len(str(prop.get('start') or '')) > 10

    def _rule(other):
        o_title = (other.get('title') or '').lower().lstrip('📌 ').strip()
        o_start, o_end = other.get('start'), other.get('end')
        if o_title and (title == o_title or title in o_title or o_title in title):
            return 'title'
        times_match = (p_start is not None and (s := _ts(o_start)) is not None
                       and abs(p_start - s) <= 30 * 60
                       and (p_end is None or (e := _ts(o_end)) is None
                            or abs(p_end - e) <= 30 * 60))
        if o_title and _titles_similar(tokens, _title_tokens(o_title), times_match):
            return 'title'
        # Rule 2. Start to the minute, not the 30-minute window rule 1 uses to
        # relax a title bar — this one carries the decision on its own.
        o_timed = not other.get('all_day') and len(str(o_start or '')) > 10
        if (p_timed and o_timed and p_start is not None
                and (s2 := _ts(o_start)) is not None and abs(p_start - s2) <= 60
                and (_places_match(prop.get('location'), other.get('location'))
                     or _same_calendar(prop, other))):
            return 'time_place'
        return None

    for source, rows in (('proposal', existing), ('event', sched_events)):
        for other in rows:
            if (other.get('start') or '')[:10] != day:
                continue
            rule = _rule(other)
            if rule:
                return {'title': other.get('title') or '', 'start': other.get('start') or '',
                        'source': source, 'rule': rule,
                        # A3: what a supply hangs off when the thing it is for
                        # is ALREADY on the calendar. Best effort — a match
                        # against a prior proposal only has an id once that
                        # proposal was approved, and a supply with no id is
                        # still a supply.
                        'id': other.get('id') or other.get('created_event_id') or None}
    return None


def _supplies_needing_a_home(supplies: list) -> list:
    """The supplies not already sitting open on some list (A3).

    A reminder email repeats the whole flyer, so the second one asks for the
    same tri-fold board. Filtering against what is already on a list is what
    keeps "already on the calendar, but it wants three things" from becoming
    a weekly card for the same three things — and it reuses the check the
    photo picker already greys candidates out with, rather than inventing a
    second notion of "we have this covered".
    """
    if not supplies:
        return []
    open_names = set()
    try:
        for l in storage.get_shopping_lists():
            for i in storage.get_shopping_items(l['id'], include_checked=False):
                open_names.add((i.get('name') or '').strip().lower())
    except Exception as e:
        # Never fatal: not knowing costs a re-offer, and losing the item to
        # an exception costs the family the board.
        print(f"[intake] could not read lists for supply dedupe: {e}")
    return [s for s in supplies
            if (s.get('name') or '').strip().lower() not in open_names]


def mark_duplicate(prop: dict, match: dict) -> str:
    """Record what this proposal duplicates — and decide whether it is a SKIP.

    Reminder emails outnumber announcement emails, so this branch carries most
    of the real traffic. A duplicate with nothing to offer is a skip, exactly
    as before. **A duplicate carrying supplies nobody has yet is not** (A3):
    "already on the calendar, but it wants three things" is a proposal, and
    rendering it as a skip is how the tri-fold board gets lost on the second
    email after surviving the first.

    Returns the status it set, so the caller can count it honestly.
    """
    prop.update({'duplicate_of': match['title'],
                 'duplicate_start': match['start'],
                 'duplicate_source': match['source'],
                 'duplicate_rule': match['rule']})
    fresh = _supplies_needing_a_home(prop.get('supplies'))
    if not fresh:
        prop['status'] = 'duplicate'
        return 'duplicate'
    # Stays 'proposed' so it lands in the queue the parent actually reads;
    # the flag is what stops the card offering a calendar (and what makes the
    # approve endpoint refuse one — a supplies-only card must never be able
    # to create the duplicate event dedupe just avoided).
    prop.update({'status': 'proposed', 'supplies_only': True,
                 'supplies': fresh, 'supplies_event_id': match.get('id')})
    return 'supplies_only'


def learned_route(from_addr: str, kind: str):
    """Deterministic learned prior (intake phase-2 (a)): the target a parent
    last APPROVED for this sender, recorded by main._record_intake_feedback.
    Explicit sender defaults still win. 'errand' targets are never prefilled
    (they need per-proposal location/duration), 'supplies' never is either
    (A3 — it is not a routing choice at all but what was LEFT of a duplicate,
    and prefilling it would point ordinary proposals at a target that refuses
    them), and a kid's task list only prefills for kind='task'."""
    if not from_addr:
        return None
    routes = storage.get_app_state('intake_learned_routes') or {}
    target = (routes.get(from_addr.lower()) or {}).get('target')
    if not target or target in ('errand', 'supplies'):
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
    _known = known_events_block(
        (storage.get_cached_schedule() or {}).get('events', []),
        [p for p in storage.get_proposals() if p.get('status') == 'proposed'])
    now = _dt.datetime.now().astimezone()
    prompt = (f"Current date: {now.strftime('%A %Y-%m-%d')}\n"
              f"Family members: {', '.join(member_names) or '(unknown)'}\n\n"
              + (f"ALREADY ON THE CALENDAR:\n{_known}\n\n" if _known else '')
              + "The attached image is a photo of a school/team flyer, schedule,"
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
    dropped = duped = supplies_only = 0
    for item in items:
        prop = normalize_item(item)
        if prop is None:
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
        # Same rule as email, same hedge: a photo of a flyer for something
        # already on the calendar is recorded and restorable, not dropped.
        match = _is_duplicate(prop, existing, sched_events)
        if match:
            status = mark_duplicate(prop, match)
            storage.add_proposal(prop)
            existing.append(prop)
            if status == 'duplicate':
                duped += 1
            else:
                summary['proposed'] += 1
                supplies_only += 1
            continue
        prop.pop('duplicate_of', None)
        storage.add_proposal(prop)
        existing.append(prop)
        summary['proposed'] += 1
    summary['duplicates'] = duped
    summary['supplies_only'] = supplies_only

    n = summary['proposed']
    bits = []
    if duped:
        bits.append(f'{duped} skipped as duplicate')
    if supplies_only:
        bits.append(f'{supplies_only} already on the calendar but needing supplies')
    if dropped:
        bits.append(f'{dropped} dropped as low-confidence')
    detail = f' ({", ".join(bits)})' if bits else ''
    if n:
        outcome = f'proposed {n} item{"s" if n != 1 else ""}{detail}'
    elif bits:
        outcome = f'nothing new{detail}'
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
    summary = {'checked': 0, 'proposed': 0, 'skipped': 0, 'duplicates': 0, 'error': None}
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
    # Built once per poll, not per message: the calendar does not change
    # between two messages of the same batch. Only PENDING proposals join the
    # real calendar here — an ignored proposal is precisely something the
    # family said is NOT happening, and listing it as already on the calendar
    # would be a lie the model reasons from. Deterministic dedupe still checks
    # every proposal whatever its status.
    known_block = known_events_block(
        sched_events, [p for p in existing if p.get('status') == 'proposed'])

    for msg in messages:
        summary['checked'] += 1
        log = {'from': msg['from'], 'subject': msg['subject'][:120]}

        # Blocked senders are skipped BEFORE extraction — that is the whole
        # saving, one LLM call per message not made. Still counted, still
        # logged: silent disappearance is what makes mail filters unnerving,
        # and the day the athletics office starts sending real game schedules
        # from a blocked address, the Activity list is the evidence.
        blocked = sender_blocked(msg['from'], blocklist, subject=msg['subject'])
        if blocked:
            summary['skipped'] += 1
            # Name the keyword that fired: a skip has to read as the rule the
            # family wrote, not as an unexplained absence.
            why = (f"{blocked['pattern']} + subject has {blocked['matched_keyword']}"
                   if blocked.get('matched_keyword') else blocked.get('pattern'))
            storage.add_ingest_log({**log, 'outcome': f'skipped: matched skip rule ({why})',
                                    'skipped': True})
            continue

        # Thread matching is additive and independent of event extraction —
        # a reply from a vendor can carry both a date-bound item AND be an
        # update to an open thread, and neither should suppress the other.
        # A match failure here must never break ingest, so it gets its own
        # try/except rather than sharing the extraction one below.
        try:
            from services import threads
            threads.match_inbound(msg['from'], msg['subject'], msg['text'])
        except Exception as e:
            print(f"[email_ingest] thread match failed: {e}")

        entry = sender_default(msg['from'], sender_defaults)
        try:
            items = extract_items(msg['subject'], msg['from'], msg['text'],
                                  member_names, known_block=known_block)
        except Exception as e:
            storage.add_ingest_log({**log, 'outcome': f'error: extraction failed ({e})'})
            continue

        proposed_here = dropped = duped = supplies_only = 0
        for item in items:
            prop = normalize_item(item)
            if prop is None:
                dropped += 1
                continue
            # Routing FIRST, then the duplicate check — the time+place rule
            # corroborates on the target calendar, which does not exist until
            # this runs. Judged before it was filled in, that rule was dead.
            # Tiers: explicit sender default > learned prior (last approved
            # target for this sender) > LLM member guess > the family's
            # starred default calendar (whole-family events land there;
            # attendees get tagged after approval).
            prop.update({
                'source': 'email',
                'source_from': msg['from'],
                'source_subject': msg['subject'][:200],
                'calendar_id': (entry or {}).get('calendar_id')
                    or learned_route(msg['from'], prop['kind'])
                    or _calendar_for_member_name(prop.get('member_name'))
                    or (settings.get('default_calendar_id') or None),
            })

            match = _is_duplicate(prop, existing, sched_events)
            if not match and prop.get('duplicate_of'):
                # The model's own read, kept separate so it is auditable: it
                # ANNOTATES, it never omits. An item the model believes is
                # already on the calendar is still recorded, still shown, and
                # still restorable — an omitted one would simply never exist.
                match = {'title': str(prop['duplicate_of'])[:200], 'start': '',
                         'source': 'llm', 'rule': 'llm', 'id': None}
            if match:
                # Recorded, not dropped. A skipped duplicate that leaves no
                # trace is indistinguishable from mail that never arrived, and
                # that is the failure the whole hedge exists to prevent. A3:
                # and one carrying supplies nobody has yet is not a skip at
                # all — see mark_duplicate.
                if mark_duplicate(prop, match) == 'duplicate':
                    duped += 1
                else:
                    proposed_here += 1
                    supplies_only += 1
                storage.add_proposal(prop)
                existing.append(prop)
                continue
            prop.pop('duplicate_of', None)
            storage.add_proposal(prop)
            existing.append(prop)
            proposed_here += 1

        summary['proposed'] += proposed_here
        summary['duplicates'] += duped
        summary['supplies_only'] = summary.get('supplies_only', 0) + supplies_only
        bits = []
        if duped:
            bits.append(f'{duped} skipped as duplicate')
        if supplies_only:
            bits.append(f'{supplies_only} already on the calendar but needing supplies')
        if dropped:
            bits.append(f'{dropped} dropped as low-confidence')
        detail = f' ({", ".join(bits)})' if bits else ''
        if proposed_here:
            outcome = f'proposed {proposed_here} item{"s" if proposed_here != 1 else ""}{detail}'
        elif bits:
            outcome = f'nothing new{detail}'
        else:
            outcome = 'no actionable items'
        storage.add_ingest_log({**log, 'outcome': outcome})

    return summary

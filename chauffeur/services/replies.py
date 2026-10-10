"""Replies — a counterparty's mail on a thread, read once. Spec:
docs/superpowers/specs/2026-10-10-triage-and-replies-design.md §2.

Runs inside the ingest poll, after `threads.match_inbound` filed the mail.
One Lite call per message_id, capped; the reading lands on the history entry;
a clear yes or no is RECORDED on the thread's one live ask and never applied
(`asks.record_reading`; `asks.apply` is never named here). The owner is told
once, inside the watcher's waking window.

Boundaries: never import a DM reader, never read gift records.
"""
import datetime
import logging
import time
from typing import Optional

from services import storage

logger = logging.getLogger(__name__)

ANSWERS = ('yes', 'no', 'question', 'info', 'unclear')
CAP_READS_DEFAULT = 40
READ_TIMEOUT_S = 20
REPLY_CHARS = 1500

READ_SYSTEM = (
    "You read ONE email reply that a family received from somebody outside "
    "the family, about one thing they asked for. Decide what the reply says "
    "about that ask: yes (they agree or will do it), no (they decline or "
    "cannot), question (they ask something back), info (news with no answer "
    "either way), unclear. Then summary: at most 20 words of what they said, "
    "plain, no advice. Return STRICT JSON: {\"answer\": \"yes|no|question|info|unclear\", "
    "\"summary\": \"...\"}. Never invent facts."
)


def _pool_call(tier, api_key, system, prompt, **kw):
    """Indirection so tests stub one attribute (situations.py precedent)."""
    from services import model_pools
    return model_pools.call_pool_json(tier, api_key, system, prompt, **kw)


def _entry(thread: dict, message_id: str) -> Optional[dict]:
    return next((h for h in (thread.get('history') or [])
                 if h.get('kind') == 'received' and h.get('message_id') == message_id), None)


def live_ask(thread_id: str) -> Optional[dict]:
    """The newest household-sent ask still waiting. Two mails with no reply
    are not ambiguous here: the newest sent mail is the one a reply answers."""
    rows = [a for a in storage.get_asks(situation_kind='thread', situation_id=thread_id)
            if a.get('state') in ('sent', 'drafted') and a.get('sent_via') == 'household']
    rows.sort(key=lambda a: a.get('sent_at') or a.get('asked_at') or 0)
    return rows[-1] if rows else None


def _classify(thread: dict, entry: dict, ask: Optional[dict], settings: dict) -> Optional[dict]:
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key:
        return None
    from services import situations as _sit
    cap = int(settings.get('reply_cap_reads', CAP_READS_DEFAULT))
    if not _sit._bump_call('reply', cap):
        return None
    text = (entry.get('text') or '')[:REPLY_CHARS]
    prompt = (f"Thread: {thread.get('title')}. "
              + (f"What was asked: {ask.get('what')}. " if ask else "Nothing specific was asked. ")
              + f"The reply:\n{text}")
    try:
        res = _pool_call('interactive', api_key, READ_SYSTEM, prompt, timeout_s=READ_TIMEOUT_S,
                         background=True, workflow='replies.read')
    except Exception as e:
        logger.warning(f"[replies] reading failed: {e}")
        return None
    if not isinstance(res, dict) or res.get('error'):
        return None
    answer = str(res.get('answer') or '').strip().lower()
    if answer not in ANSWERS:
        answer = 'unclear'
    summary = ' '.join(str(res.get('summary') or '').split())[:160]
    return {'answer': answer, 'summary': summary, 'ts': time.time(), 'source': 'argyle'}


def read(thread_id: str, message_id: str) -> Optional[dict]:
    """Read the reply filed as `message_id` on this thread, once. Returns the
    reading, or None when nothing was read (no key, cap, failure, already
    read, no such entry). Every path that stores a reading also records the
    answer on the live ask and notifies the owner."""
    thread = storage.get_thread(thread_id)
    if not thread or not message_id:
        return None
    entry = _entry(thread, message_id)
    if not entry or entry.get('reading'):
        return None if not entry else entry.get('reading')
    settings = storage.get_settings() or {}
    ask = live_ask(thread_id)
    reading = _classify(thread, entry, ask, settings)
    if reading is None:
        # No reading: the card's next step still names the reply (deterministic,
        # situations._options_thread) and the owner is still told.
        _notify(thread, entry, None, now=_now())
        return None
    storage.update_thread_history_entry(thread_id, {'message_id': message_id}, {'reading': reading})
    from services import asks as _asks, situations as _sit
    if ask and reading['answer'] in ('yes', 'no'):
        _asks.record_reading(ask['id'], reading['answer'], message_id, summary=reading['summary'])
    _sit.bump_rev('thread', thread_id)
    _sit.request_refresh('thread', thread_id)
    _notify(thread, entry, reading, now=_now())
    return reading


# --- one message to the owner ----------------------------------------------------

def _now() -> datetime.datetime:
    """The module's one clock, so a test can pin the hour."""
    return datetime.datetime.now()


def _post(dm: dict, argyle: dict, body: str, card: dict = None) -> dict:
    from services.agent_tools_v2 import _post_chat_message
    return _post_chat_message(dm, argyle, body, card=card)


def _in_window(now: datetime.datetime) -> bool:
    from services.watchers import QUIET_END_HOUR, QUIET_START_HOUR
    return QUIET_END_HOUR <= now.hour < QUIET_START_HOUR


def dm_line(thread: dict, entry: dict, reading: Optional[dict], next_label: str = '') -> str:
    who = thread.get('counterparty_name') or (entry.get('text') or '').split(':')[0].replace('Received from ', '') or 'They'
    title = thread.get('title') or 'a thread'
    if not reading:
        return f"{who} replied on '{title}' — read it."
    line = f"{who} replied on '{title}': {reading.get('summary') or reading.get('answer')}"
    return line + (f" → {next_label}" if next_label else '') + '.'


def _recipients(thread: dict) -> list:
    owner = storage.get_member(thread.get('owner_member_id') or '') if thread.get('owner_member_id') else None
    if owner and (owner.get('status') or 'active') == 'active':
        return [owner]
    return [m for m in storage.get_all_members() if m.get('role') == 'parent' and not m.get('system')]


def _send(thread: dict, entry: dict, reading: Optional[dict]) -> bool:
    from services import situations as _sit
    s = _sit.view('thread', thread['id'], _sit.parent_of_record())
    nxt = ((s or {}).get('next_step') or {}).get('label') or ''
    body = dm_line(thread, entry, reading, nxt)
    argyle = storage.ensure_argyle_member()
    sent = False
    for m in _recipients(thread):
        try:
            _post(storage.get_or_create_dm(argyle['id'], m['id']), argyle, body)
            sent = True
        except Exception as e:
            logger.warning(f"[replies] DM to {m.get('name')} failed: {e}")
    return sent


def _notify(thread: dict, entry: dict, reading: Optional[dict], now: datetime.datetime = None) -> None:
    """One message to the owner (the parents when none), at once inside the
    watcher's waking window, else deferred to the first in-window sweep.
    Never for a closed thread."""
    if thread.get('state') in ('done', 'dropped'):
        return
    now = now or _now()
    if _in_window(now) and _send(thread, entry, reading):
        storage.update_thread_history_entry(thread['id'], {'message_id': entry.get('message_id')}, {'dm_pending': False})
        return
    storage.update_thread_history_entry(thread['id'], {'message_id': entry.get('message_id')}, {'dm_pending': True})


def flush_pending_dms(now: datetime.datetime = None) -> int:
    """Called by run_watchers inside the window: post every deferred reply
    DM on an open thread, once. A failed post keeps the mark for next time."""
    now = now or _now()
    if not _in_window(now):
        return 0
    posted = 0
    for thread in storage.get_threads(include_closed=False):
        for h in list(thread.get('history') or []):
            if h.get('kind') == 'received' and h.get('dm_pending'):
                if _send(thread, h, h.get('reading')):
                    storage.update_thread_history_entry(thread['id'], {'message_id': h.get('message_id')}, {'dm_pending': False})
                    posted += 1
    return posted

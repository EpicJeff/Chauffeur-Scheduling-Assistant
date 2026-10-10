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
        _notify(thread, entry, None)
        return None
    storage.update_thread_history_entry(thread_id, {'message_id': message_id}, {'reading': reading})
    from services import asks as _asks, situations as _sit
    if ask and reading['answer'] in ('yes', 'no'):
        _asks.record_reading(ask['id'], reading['answer'], message_id, summary=reading['summary'])
    _sit.bump_rev('thread', thread_id)
    _sit.request_refresh('thread', thread_id)
    _notify(thread, entry, reading)
    return reading


def _notify(thread: dict, entry: dict, reading: Optional[dict]) -> None:
    """Filled in by Task 8 (one DM to the owner, deferred through quiet hours)."""
    return None

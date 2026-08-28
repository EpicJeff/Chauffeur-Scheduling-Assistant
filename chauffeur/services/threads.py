"""Threads — open loops with people outside the family.

A thread is a promise somebody made to a vendor or a project that hasn't
closed yet: the pest control company that said they'd call back, the deck
permit still waiting on the county. None of that is on anybody's calendar,
so nothing else in this app would ever notice it went quiet. The value this
module adds isn't the record — it's noticing when a record stops moving.

Two ways a thread stalls, and only two:

- `overdue` — there's a `next_action_at` and it's in the past. Somebody said
  "I'll do X by this date" and the date came and went.
- `quiet`   — nothing real has happened for `stall_days` (default
  `STALL_DAYS_DEFAULT`, overridable per household via the
  `thread_stall_days` setting). Measured from the timestamp of the last
  history entry *beyond the opening one* `create()` writes, or from
  `created_at` when nothing has happened since — the opening entry marks the
  thread coming into being, not movement, so it doesn't get to start the
  clock itself; that's also why it stays live against `created_at` rather
  than freezing at the opening entry's own timestamp.

A `waiting` thread with a future `next_action_at` is not stalled — it is
doing exactly what it should: sitting, on schedule, for somebody else's
move. And a closed thread (`done`/`dropped`) never stalls, no matter how
overdue its last next-action was when it closed — the stall signal exists
to make somebody look at something that's still open, not to relitigate
history.

Every append — `create`, `advance`, `note`, `close` — goes through
`storage.append_thread_history`, so the quiet clock and the audit trail are
the same write. There is no separate "last touched" field to fall out of
sync with the log that's supposed to explain it.

`draft_message` and `send_drafted` add two more history kinds (`drafted`,
`sent`) and one hard rule the rest of this file doesn't need: drafting and
sending are different functions calling different things. `draft_message`
talks to the model and returns words; it cannot reach `services.mailer` even
by accident, because it never imports it. `send_drafted` talks to
`services.mailer` and cannot reach the model, for the same reason. Nothing
about a badly-timed refactor can quietly merge "write this" and "send this"
into one call, because there is no shared function for it to collapse into —
a person's tap on Send is the only path from a drafted subject/body to an
outbound email, and it happens in a different function than the one that
proposed the words.
"""
import datetime
import time
from typing import Dict, List, Optional

from services import mailer, storage

STALL_DAYS_DEFAULT = 7


def _pool_call(tier, api_key, system, prompt, **kw):
    """Indirection so tests stub one attribute — same shape as
    services/web.py and services/mind.py, kept separate per module so a
    test stubbing one caller's model access can never accidentally stub
    another's."""
    from services import model_pools
    return model_pools.call_pool_json(tier, api_key, system, prompt, **kw)


DRAFT_SYSTEM = (
    "You are Argyle, drafting a short email on behalf of a family to "
    "someone outside it — a vendor, a school, a contractor, a candidate. "
    "Write in a warm, direct, ordinary-person voice: no corporate "
    "throat-clearing, no over-explaining, no filler sign-off paragraphs. "
    "Use the thread's title, goal and recent history so the message doesn't "
    "repeat or contradict what's already been said. You are proposing "
    "language for a person to review and edit — not sending anything "
    "yourself. Return STRICT JSON: "
    '{"subject": "<short subject line>", "body": "<the email body>"}'
)


def _draft_context(thread: dict, intent: str = '') -> str:
    lines = [f"Thread: {thread.get('title', '')}"]
    if thread.get('goal'):
        lines.append(f"Goal: {thread['goal']}")
    counterparty = (thread.get('counterparty_name')
                    or thread.get('counterparty_email') or 'the other party')
    lines.append(f"Writing to: {counterparty}")
    if thread.get('next_action'):
        na = f"Next action on file: {thread['next_action']}"
        if thread.get('next_action_at'):
            na += f" (by {thread['next_action_at']})"
        lines.append(na)
    history = thread.get('history') or []
    if history:
        lines.append("Recent history (oldest to newest):")
        for h in history[-5:]:
            lines.append(f"- ({h.get('kind')}) {h.get('text')}")
    lines.append(f"What this message should do: {intent}" if intent
                 else "What this message should do: a reasonable, natural "
                      "follow-up given the above.")
    return '\n'.join(lines)


def draft_message(thread_id: str, intent: str = '') -> dict:
    """Ask the model for a `{subject, body}` proposal and stop there.

    This is the only function in the module that talks to an LLM, and it is
    the boundary the whole feature exists to hold: it can propose words, it
    can never cause a message to leave the house. It writes nothing but an
    optional `drafted` history entry — a record that a draft was proposed,
    not that anything was said — and never touches `state`. See
    `send_drafted` for the only function that can actually send.
    """
    thread = storage.get_thread(thread_id)
    if not thread:
        return {'status': 'not_found'}

    settings = storage.get_settings() or {}
    api_key = settings.get('llm_gemini_api_key', '')
    prompt = _draft_context(thread, intent)
    res = _pool_call('interactive', api_key, DRAFT_SYSTEM, prompt, timeout_s=30)
    if not isinstance(res, dict) or res.get('error'):
        reason = res.get('error') if isinstance(res, dict) else 'no response'
        return {'status': 'error', 'reason': reason}

    subject = str(res.get('subject') or '').strip()
    body = str(res.get('body') or '').strip()
    if not subject or not body:
        return {'status': 'error', 'reason': 'model returned an incomplete draft'}

    storage.append_thread_history(thread_id, {
        'kind': 'drafted',
        'text': f'Drafted: {subject}',
        'who': 'argyle',
    })
    return {'status': 'ok', 'subject': subject, 'body': body,
            'to': thread.get('counterparty_email', '')}


def send_drafted(thread_id: str, subject: str, body: str, to: str,
                  who: str = None) -> dict:
    """Send exactly what is passed in — the client's editable box at the
    moment of the tap, edited or not — never what `draft_message` proposed
    a request ago. This function has no memory of the draft and never
    compares the two; the record afterward is of what was actually said.

    Refuses honestly (`not_configured`) rather than pretending to send when
    `services.mailer` has no sender set up — same degrade-gracefully rule
    every other mail path in this app follows. On success it appends the
    `sent` history entry (with the body, so the log is of what went out,
    not just that something did) and moves the thread to `waiting`: the
    ball is now with the other side.
    """
    thread = storage.get_thread(thread_id)
    if not thread:
        return {'status': 'not_found'}

    settings = storage.get_settings() or {}
    if not mailer.configured(settings):
        return {'status': 'not_configured'}

    subject = (subject or '').strip()
    body = (body or '').strip()
    to = (to or '').strip()
    if not to or not body:
        return {'status': 'error', 'reason': 'nothing to send'}

    result = mailer.send(to, subject, body, settings=settings)
    if not result.get('sent'):
        return {'status': 'error', 'reason': result.get('reason')}

    storage.append_thread_history(thread_id, {
        'kind': 'sent',
        'text': f'Sent to {to}: {subject}\n\n{body}',
        'who': who,
    })
    storage.update_thread(thread_id, {'state': 'waiting'})
    return {'status': 'ok'}


def _stall_days() -> int:
    return storage.get_settings().get('thread_stall_days', STALL_DAYS_DEFAULT)


def create(title: str, owner_member_id: str = None, goal: str = '',
           kind: str = 'project', contact_id: str = None,
           counterparty_name: str = '', counterparty_email: str = '',
           next_action: str = '', next_action_at: str = None,
           created_by: str = None) -> str:
    """Open a new thread and log the opening move as its first history entry.

    That entry is load-bearing, not decoration: `is_stalled` only trusts a
    history timestamp once there's a second entry past it, so that the
    FIRST real thing anyone logs (a note, an advance) is the one that
    resets the quiet clock, rather than getting absorbed as "no history
    yet" and ignored.
    """
    thread_id = storage.add_thread({
        'title': title,
        'goal': goal,
        'kind': kind,
        'owner_member_id': owner_member_id,
        'contact_id': contact_id,
        'counterparty_name': counterparty_name,
        'counterparty_email': counterparty_email,
        'next_action': next_action,
        'next_action_at': next_action_at,
        'created_by': created_by,
    })
    storage.append_thread_history(thread_id, {
        'kind': 'opened',
        'text': f'Opened: {title}',
        'who': created_by,
    })
    return thread_id


def advance(thread_id: str, next_action: str, next_action_at: str = None,
            note: str = None, who: str = None) -> bool:
    """Set the next thing that has to happen, and when, and log it.

    This is the normal heartbeat of a thread: the vendor called back, here's
    what happens next. Logging it (rather than just updating the fields)
    is what keeps the quiet clock honest.
    """
    ok = storage.update_thread(thread_id, {
        'next_action': next_action,
        'next_action_at': next_action_at,
    })
    if not ok:
        return False
    text = f'Next: {next_action}' if next_action else 'Next action updated'
    if next_action_at:
        text += f' by {next_action_at}'
    if note:
        text += f' — {note}'
    storage.append_thread_history(thread_id, {
        'kind': 'advance',
        'text': text,
        'who': who,
    })
    return True


def note(thread_id: str, text: str, who: str = None, url: str = None) -> bool:
    """Log movement that isn't a change of plan — a call made, a voicemail
    left, a document received. Nothing was decided, but somebody did
    something, and that alone resets the quiet clock (see module docstring:
    "movement is movement, even when nothing was achieved")."""
    entry = {'kind': 'note', 'text': text, 'who': who}
    if url:
        entry['url'] = url
    return storage.append_thread_history(thread_id, entry)


def close(thread_id: str, state: str = 'done', who: str = None) -> bool:
    """End a thread — `done` when it resolved, `dropped` when it didn't and
    won't. Either way it stops stalling immediately: a closed thread's stale
    next-action is history, not a live problem."""
    ok = storage.update_thread(thread_id, {
        'state': state,
        'closed_at': time.time(),
    })
    if not ok:
        return False
    storage.append_thread_history(thread_id, {
        'kind': 'closed',
        'text': f'Closed as {state}',
        'who': who,
    })
    return True


def is_stalled(thread: dict, today: datetime.date = None) -> Optional[str]:
    """`'overdue'`, `'quiet'`, or `None`. See module docstring for the rules."""
    if not thread or thread.get('state') in ('done', 'dropped'):
        return None

    today = today or datetime.date.today()

    next_action_at = thread.get('next_action_at')
    if next_action_at:
        try:
            due = datetime.date.fromisoformat(next_action_at)
        except (TypeError, ValueError):
            due = None
        if due is not None:
            if due < today:
                return 'overdue'
            # A future (or today's) next_action_at means somebody is
            # actively waiting on a known date — not quiet, whatever the
            # history says.
            return None

    # The opening entry `create()` writes isn't real movement, just the
    # thread coming into being -- so with nothing beyond it yet, the clock
    # runs from `created_at` (which stays live if that field is ever
    # corrected), not from the opening entry's frozen timestamp. Anything
    # appended after that (advance/note/close) is real movement and wins.
    history = thread.get('history') or []
    if len(history) > 1:
        last_ts = history[-1].get('ts', thread.get('created_at', 0))
    else:
        last_ts = thread.get('created_at', 0)

    stall_days = _stall_days()
    if last_ts and (time.time() - last_ts) >= stall_days * 86400:
        return 'quiet'
    return None


def stalled(today: datetime.date = None) -> List[dict]:
    """Every open thread with a live stall reason — the sweep a digest or a
    finding would read. Closed threads are excluded by `get_threads`
    already; `is_stalled` guards them again for anyone calling it directly."""
    result = []
    for thread in storage.get_threads(include_closed=False):
        reason = is_stalled(thread, today=today)
        if reason:
            thread = dict(thread)
            thread['stall_reason'] = reason
            result.append(thread)
    return result


def open_by_owner() -> Dict[str, int]:
    """How many non-closed threads each member is carrying — the count
    behind "who is holding what," not a judgment about whether that's too
    many."""
    counts: Dict[str, int] = {}
    for thread in storage.get_threads(include_closed=False):
        owner = thread.get('owner_member_id')
        if not owner:
            continue
        counts[owner] = counts.get(owner, 0) + 1
    return counts

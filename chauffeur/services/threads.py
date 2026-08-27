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
"""
import datetime
import time
from typing import Dict, List, Optional

from services import storage

STALL_DAYS_DEFAULT = 7


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

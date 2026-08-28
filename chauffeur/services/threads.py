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
sync with the log that's supposed to explain it. The one entry kind that
does NOT reset the clock is `drafted` (see below) — `is_stalled` skips it
on purpose, because proposing words and abandoning them is not movement,
it's the exact non-movement this module exists to catch.

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
import re
import time
from typing import Dict, List, Optional

from services import storage

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
    from services import mailer

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


def _web_research(question: str) -> dict:
    """Indirection so tests stub one attribute — same shape as `_pool_call`
    above and `services/web.py`'s own `_pool_call`."""
    from services import web
    return web.research(question)


def research(thread_id: str, question: str) -> dict:
    """Ask a practical question on this thread's behalf and — only when
    `services.web.research` actually answered it — log the answer with its
    source URLs written INTO the history text, not just returned to the
    caller. A fact in a thread that outlives its citation is exactly the
    failure `services/web.py` exists to prevent, and `web.research` already
    drops any fact citing a page it never read; this function's only job is
    to not throw the surviving citations away before they reach the record.

    Any non-'ok' status (`disabled`, `no_key`, `capped`, `reserved`,
    `no_results`, `error`) appends nothing and is returned as-is, so the UI
    can say honestly why there's no answer. A `research` entry is real
    movement — something was actually found out — so it is not on the
    `is_stalled` skip list the way `drafted` is; it resets the quiet clock.
    """
    thread = storage.get_thread(thread_id)
    if not thread:
        return {'status': 'not_found'}

    question = (question or '').strip()
    if not question:
        return {'status': 'error', 'reason': 'no question'}

    result = _web_research(question)
    if result.get('status') != 'ok':
        return result

    answer = (result.get('answer') or '').strip()
    sources = result.get('sources') or []
    facts = result.get('facts') or []
    # Facts first, not sources: on the pages route (via == 'pages'), `facts`
    # is the filtered list where every claim actually cites a page that was
    # fetched and read — unreadable/unverifiable citations already dropped
    # by web.research — while `sources` there is every search result found
    # (up to RESULTS_PER_SEARCH), most of which were never opened. Falling
    # back to `sources` whenever it happened to be non-empty meant a
    # thread's permanent record could carry a URL nobody ever read, which
    # is precisely what `services/web.py` exists to prevent. `sources` is
    # only trusted here when there are no facts at all — the grounding
    # route's shape, one synthetic fact standing in for an answer that has
    # no per-claim breakdown.
    urls = list(dict.fromkeys(f['url'] for f in facts if f.get('url')))
    if not urls:
        urls = list(dict.fromkeys(s['url'] for s in sources if s.get('url')))

    text = f'Researched: {question}\n\n{answer}'
    if urls:
        text += '\n\n' + '\n'.join(urls)

    storage.append_thread_history(thread_id, {
        'kind': 'research',
        'text': text,
        'who': 'argyle',
    })
    return {'status': 'ok', 'answer': answer, 'facts': facts,
            'sources': sources, 'dropped': result.get('dropped') or 0}


def _stall_days() -> int:
    # `or STALL_DAYS_DEFAULT`, not a plain default: the Settings model keeps
    # this field Optional and POST /api/settings accepts an explicit null, so
    # the key can be PRESENT with the value None — .get()'s default never
    # fires, and a None here would TypeError in is_stalled's comparison and
    # take down GET /api/threads and the nightly sweep with it.
    return (storage.get_settings() or {}).get(
        'thread_stall_days', STALL_DAYS_DEFAULT) or STALL_DAYS_DEFAULT


def _clean_next_action_at(value) -> Optional[str]:
    """A `next_action_at` that isn't a real YYYY-MM-DD string becomes None
    before it can reach storage. This field feeds `storage.get_threads`'s
    sort key (compared against other strings) and `is_stalled`'s date parse;
    one non-string row — a model emitting `20260901` as a number through the
    agent tools, which pass their JSON straight in — would make that sort
    raise TypeError forever: the Threads page 500s, `stalled()` raises, and
    the nightly `watchers.collect_findings()` dies for EVERY finding kind.
    Coerce, parse, or drop — a garbage date is no date."""
    if value is None:
        return None
    try:
        return datetime.date.fromisoformat(str(value).strip()).isoformat()
    except (TypeError, ValueError):
        return None


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
        'next_action_at': _clean_next_action_at(next_action_at),
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
    next_action_at = _clean_next_action_at(next_action_at)
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
    # appended after that (advance/note/close/sent) is real movement and
    # wins. A `drafted` entry is deliberately NOT real movement either: it
    # only records that Argyle proposed words, and tapping Draft then
    # walking away is exactly the non-movement this clock exists to catch —
    # letting it reset the clock would let a thread go quiet again for a
    # full stall_days on the strength of nothing having actually happened.
    history = [h for h in (thread.get('history') or []) if h.get('kind') != 'drafted']
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


def _tokens(text: str) -> set:
    return set(re.findall(r"[a-z0-9]+", (text or '').lower()))


def match_inbound(from_addr: str, subject: str = '', body: str = '') -> Optional[str]:
    """Does this piece of inbound mail belong to an open thread? If so,
    record it there and say which one. If not, do nothing and say so.

    Matching is `counterparty_email` first, case-insensitive — that alone
    resolves the common case, one thread per counterparty. When more than
    one open thread shares a counterparty (two vendors from the same
    company, a candidate re-contacted for a second role), subject/body
    token overlap against each thread's title breaks the tie. If nothing
    breaks the tie — no counterparty match, or a tie among candidates with
    no title word in common with this message — the answer is None and
    nothing is written. Guessing wrong here is worse than not filing: a
    reply filed on the wrong thread reads as an update nobody sent and
    buries the one nobody logged.

    A match appends a `received` history entry (which, unlike `drafted`,
    counts as movement and resets the quiet clock — a reply arriving is
    exactly the kind of thing `is_stalled` exists to notice) and, if the
    thread was `waiting` on the other side, moves it back to `open`: the
    ball just came back to us.
    """
    addr = (from_addr or '').strip().lower()
    if not addr:
        return None

    candidates = [t for t in storage.get_threads(include_closed=False)
                  if (t.get('counterparty_email') or '').strip().lower() == addr]
    if not candidates:
        return None

    thread = candidates[0]
    if len(candidates) > 1:
        text_tokens = _tokens(subject) | _tokens(body)
        best, best_score, best_count = None, 0, 0
        for t in candidates:
            score = len(text_tokens & _tokens(t.get('title', '')))
            if score > best_score:
                best, best_score, best_count = t, score, 1
            elif score and score == best_score:
                best_count += 1
        # A shared top score is a tie, and a tie declines: two threads that
        # overlap this message equally well means nothing actually broke it,
        # and filing on whichever came first in iteration order is exactly
        # the wrong-guess this function's contract forbids.
        if best is None or best_count > 1:
            return None
        thread = best

    thread_id = thread['id']
    body_trimmed = (body or '').strip()[:500]
    text = f'Received from {from_addr}: {subject}'.strip()
    if body_trimmed:
        text += f'\n\n{body_trimmed}'
    storage.append_thread_history(thread_id, {
        'kind': 'received',
        'text': text,
        'who': None,
    })
    if thread.get('state') == 'waiting':
        storage.update_thread(thread_id, {'state': 'open'})
    return thread_id


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

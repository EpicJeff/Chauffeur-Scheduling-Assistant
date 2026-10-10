"""Triage — the one thing that needs a person, spoken, and held as the
conversation's focus. Spec: docs/superpowers/specs/2026-10-10-triage-and-replies-design.md §1.

`situations.rank` orders the lanes for the eye; `triage_rank` orders for the
ear: what somebody should hear first. Focus is one app-state map keyed by
conversation key, pruned on every write, so "handle it" after "what needs
my attention" needs no title.

Boundaries (same as situations.py): never import a DM accessor, never read
gift records. Nothing here calls a model.
"""
import datetime
import time
from typing import Optional

from services import storage, situations

FOCUS_KEY = 'triage_focus'
# The option ids situations._reply_option highlights after a counterparty's reply.
REPLY_LEADS = ('advance:confirm', 'draft:reply', 'advance:read')
FOCUS_TTL_S = 24 * 3600
DAY_S = 24 * 3600


# --- rank ----------------------------------------------------------------------

def _due_ts(s: dict) -> Optional[float]:
    due = s.get('due')
    if due is None or due == '':
        return None
    if isinstance(due, (int, float)):
        return float(due)
    try:
        return datetime.datetime.fromisoformat(str(due)).timestamp()
    except (TypeError, ValueError):
        return None


def tier(s: dict, now: float = None) -> int:
    """0 overdue or due within 24h; 1 decide findings, stalled threads,
    missions with a pending proposal; 2 approve findings; 3 insights;
    4 fyi and everything else."""
    now = now or time.time()
    kind, state = s.get('kind'), s.get('state')
    due = _due_ts(s)
    if kind == 'finding':
        sev = s.get('severity')
        if sev == 'decide':
            return 0 if due is not None and due - now <= DAY_S else 1
        if sev == 'approve':
            return 2
        return 4
    if kind == 'thread':
        if due is not None and due < now:
            return 0
        # Somebody wrote back and is waiting on us: a reply nobody has acted
        # on (read as yes, a question, or not read at all) sits right after
        # today's business, never under the insights. A 'no' leaves the
        # ordinary options and the ordinary rank.
        if ((s.get('next_step') or {}).get('id') or '') in REPLY_LEADS:
            return 1
        return 1 if s.get('needs_attention') else 4
    if kind == 'mission':
        if state == 'waiting_user':
            return 0
        return 1 if s.get('needs_attention') else 4
    if kind == 'insight':
        return 3
    return 4


def triage_rank(rows: list, now: float = None) -> list:
    now = now or time.time()

    def key(s):
        t = tier(s, now)
        due = _due_ts(s)
        if s.get('kind') == 'insight':
            return (t, -(s.get('confidence') or 0), s.get('since') or 0)
        if s.get('kind') == 'thread' and t == 1:
            return (t, 0, s.get('since') or 0)          # stalled longest first (oldest since)
        return (t, due if due is not None else float('inf'), s.get('since') or 0)
    return sorted(rows, key=key)


# --- the sentence --------------------------------------------------------------

def _ask_clause(asks: list) -> str:
    live = [a for a in asks if a.get('state') != 'withdrawn'][-3:]
    parts = []
    for a in live:
        state = a.get('state')
        words = {'drafted': 'not sent yet', 'sent': 'waiting', 'yes': 'said yes', 'no': 'said no',
                 'expired': 'no answer'}.get(state, state or '')
        # A reading is never spoken as a tap: the ear has no card to tell them apart.
        if a.get('answered_by') == 'argyle' and state in ('yes', 'no'):
            words = f"Argyle read their reply as {state}"
        parts.append(f"asked {a.get('to_name')} by {a.get('channel')}, {words}")
    return '; '.join(parts)


def spoken(s: dict) -> str:
    """One or two sentences, built from the situation's own facts. No model."""
    title = (s.get('title') or '').strip().rstrip('.')
    out = f"{title}."
    if s.get('note_source') == 'argyle' and (s.get('status_note') or '').strip():
        note = s['status_note'].strip()
        out += f" {note}" + ('' if note.endswith(('.', '!', '?')) else '.')
    nxt = (s.get('next_step') or {}).get('label')
    if nxt:
        clause = _ask_clause(s.get('asks') or [])
        out += f" Next: {nxt}" + (f" — {clause}" if clause else '') + '.'
    return out


# --- focus ---------------------------------------------------------------------

def _load_map() -> dict:
    return dict(storage.get_app_state(FOCUS_KEY) or {})


def _prune(m: dict, now: float) -> dict:
    return {k: v for k, v in m.items() if isinstance(v, dict) and (v.get('set_at') or 0) >= now - FOCUS_TTL_S}


def set_focus(key: Optional[str], kind: str, sid: str, title: str, cursor: int = 0) -> Optional[dict]:
    if not key:
        return None
    now = time.time()
    f = {'kind': kind, 'id': sid, 'title': title or '', 'cursor': int(cursor or 0), 'set_at': now}
    with storage.db_lock:
        m = _prune(_load_map(), now)
        m[key] = f
        storage.set_app_state(FOCUS_KEY, m)
    return f


def clear_focus(key: Optional[str]) -> None:
    if not key:
        return
    with storage.db_lock:
        m = _load_map()
        if key in m:
            del m[key]
            storage.set_app_state(FOCUS_KEY, m)


def _alive(f: dict) -> bool:
    row = situations.load(f.get('kind'), f.get('id'))
    if not row:
        return False
    if (row.get('snoozed_until') or 0) > time.time():
        return False
    opts = situations.options_for(f['kind'], row)
    return not (situations._is_done(f['kind'], row) and not situations.needs_attention(f['kind'], row, opts))


def has_entry(key: Optional[str]) -> bool:
    """Whether the conversation has ANY focus entry, live or dead. A dead one
    still tells "next" where the list was; get_focus would delete it."""
    return bool(key) and key in _load_map()


def get_focus(key: Optional[str]) -> Optional[dict]:
    """The conversation's current situation, or None. A focus whose
    situation is gone, settled or snoozed is dropped here, so a follow-up
    can never act on a dead row."""
    if not key:
        return None
    f = _load_map().get(key)
    if not f:
        return None
    if (f.get('set_at') or 0) < time.time() - FOCUS_TTL_S or not _alive(f):
        clear_focus(key)
        return None
    return f


def next_for(viewer: Optional[dict], key: Optional[str], skip_current: bool = False) -> Optional[dict]:
    """The situation to speak now. The first on the ranked list, or the one
    after the focus when `skip_current`. Sets focus and cursor; clears the
    focus and returns None when the list is exhausted."""
    ranked = triage_rank(situations.list_situations(viewer, spoken=True))
    if not ranked:
        clear_focus(key)
        return None
    idx = 0
    if skip_current:
        # The RAW entry, not get_focus: a focus whose situation was handled
        # between turns is dead, but its cursor still says where the list
        # was. The row after it slid into its place, so the cursor itself is
        # the next one; only a row still listed moves one past itself.
        f = _load_map().get(key) if key else None
        if f:
            pos = next((i for i, s in enumerate(ranked) if s['kind'] == f['kind'] and s['id'] == f['id']), None)
            idx = (pos + 1) if pos is not None else int(f.get('cursor') or 0)
    if idx >= len(ranked):
        clear_focus(key)
        return None
    s = ranked[idx]
    set_focus(key, s['kind'], s['id'], s.get('title') or '', cursor=idx)
    return s


def focus_live_asks(key: Optional[str], viewer: Optional[dict]) -> list:
    f = get_focus(key)
    if not f:
        return []
    s = situations.view(f['kind'], f['id'], viewer)
    return [a for a in (s or {}).get('asks') or [] if a.get('state') in ('drafted', 'sent')]

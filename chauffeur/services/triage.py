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

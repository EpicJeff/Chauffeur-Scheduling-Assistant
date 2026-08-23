"""Needs You — a watcher finding with a lifecycle.

Before this module a finding was a line of text in a DM: it fired once, and
then nobody — including the app — knew whether it had been dealt with. That
put the tracking back on the parent, which is the exact load the watchers
exist to remove.

The idea that makes this cheap is that **absence is resolution**. The watchers
re-scan live state on every sweep, so an open record whose condition no longer
appears has been handled *somewhere*: verified on the chores page, covered by
the other parent, deadline met. No per-kind resolution code, no second place to
tick things off, and the surface empties itself.

Three rules keep it honest:

- **Identity is (kind, subject), not (kind, subject, day.)** The dated dedup
  keys in `app_state['watcher_notified']` stay exactly as they were — they
  govern how often we SPEAK. A record governs whether the thing is still true.
  Two concerns, two keys, so neither can quietly break the other.
- **A sweep only closes what it looked at.** Reconciliation is scoped to the
  kinds actually scanned. The weekly prep-kit check does not run on most
  sweeps, and a record it opened must not be auto-closed by a sweep that never
  asked the question.
- **Dismissed stays dismissed.** A parent who said "leave it" is not asked
  again while the finding says the same thing. If the LINE changes — a new
  time, a new deadline, a different gap — the situation has materially moved
  and it may open again.
"""
import time
from typing import NamedTuple, Optional

from services import storage

# Resolved rows are kept long enough to answer "what happened this month" for
# the digest, and no longer. Open rows are never pruned.
RETENTION_DAYS = 120


class Finding(NamedTuple):
    """One thing the sweep noticed.

    Tuple-shaped on purpose: `(key, line)` indexing is what every watcher
    already produced and what the existing tests read, so the extra fields
    ride along without a rewrite of the collectors.
    """
    key: str                     # dedup key — carries the day where cadence needs it
    line: str                    # the sentence a parent reads
    kind: str = 'other'
    severity: str = 'fyi'        # decide | approve | fyi
    dm: bool = True              # may this interrupt someone?
    subject_type: str = ''
    subject_id: str = ''
    due_at: Optional[float] = None
    proposal_id: Optional[str] = None
    action: Optional[dict] = None  # {'label', 'action_type', 'payload'}


def make(key, line, **kw) -> Finding:
    return Finding(key=key, line=line, **kw)


def identity(f: Finding) -> str:
    """What makes this the SAME trouble across days. Falls back to the dedup
    key when a finding has no subject, which keeps dateless kinds (the batched
    ones) from all collapsing onto one row."""
    if f.subject_id:
        return f"{f.kind}:{f.subject_id}"
    return f"{f.kind}:{f.key}"


def open_findings(severity: str = None) -> list:
    rows = storage.get_findings(state='open')
    if severity:
        rows = [r for r in rows if r.get('severity') == severity]
    order = {'decide': 0, 'approve': 1, 'fyi': 2}
    rows.sort(key=lambda r: (order.get(r.get('severity'), 3),
                             r.get('due_at') or float('inf'),
                             r.get('created_at') or 0))
    return rows


def reconcile(found, scanned_kinds, now_ts: float = None) -> dict:
    """Fold this sweep's findings into the record table.

    Returns the counts the digest reports — all of them real, none of them
    estimated. `scanned_kinds` is what this sweep actually looked for; records
    of other kinds are left alone (see the module docstring).
    """
    now_ts = now_ts or time.time()
    scanned = set(scanned_kinds or [])
    seen = {}
    for f in found:
        seen[identity(f)] = f

    opened = reopened = 0
    for ident, f in seen.items():
        existing = storage.get_finding_by_identity(ident)
        if existing and existing.get('state') == 'open':
            # Keep the sentence current — a deadline slips, a count changes —
            # without touching created_at, which is how long this has been true.
            storage.update_finding(existing['id'], {
                'line': f.line, 'severity': f.severity, 'due_at': f.due_at,
                'proposal_id': f.proposal_id or existing.get('proposal_id'),
                'last_seen_at': now_ts})
            continue
        if existing and existing.get('state') == 'dismissed':
            # Settled — unless the situation itself has changed.
            if (existing.get('line') or '') == f.line:
                continue
            reopened += 1
        storage.add_finding({
            'identity': ident, 'kind': f.kind, 'severity': f.severity,
            'line': f.line, 'subject_type': f.subject_type,
            'subject_id': f.subject_id, 'due_at': f.due_at,
            'proposal_id': f.proposal_id, 'created_at': now_ts,
            'last_seen_at': now_ts, 'state': 'open'})
        opened += 1

    closed = expired = 0
    for row in storage.get_findings(state='open'):
        if row.get('identity') in seen:
            continue
        if row.get('kind') not in scanned:
            # This sweep did not ask the question, so it cannot answer it.
            due = row.get('due_at')
            if due and due < now_ts:
                storage.update_finding(row['id'], {'state': 'expired',
                                                   'resolved_at': now_ts,
                                                   'resolved_by': 'expiry'})
                expired += 1
            continue
        due = row.get('due_at')
        if due and due < now_ts:
            storage.update_finding(row['id'], {'state': 'expired',
                                               'resolved_at': now_ts,
                                               'resolved_by': 'expiry'})
            expired += 1
            continue
        storage.update_finding(row['id'], {'state': 'done', 'resolved_at': now_ts,
                                           'resolved_by': 'auto'})
        closed += 1

    try:
        storage.prune_findings(now_ts - RETENTION_DAYS * 86400)
    except Exception as e:
        print(f"[findings] prune failed: {e}")

    return {'opened': opened, 'reopened': reopened,
            'closed_auto': closed, 'expired': expired}


def resolve(finding_id: str, how: str, member_id: str = None) -> dict:
    """A person acted: 'tap' (they did the thing) or 'dismiss' (leave it).

    Undo is deliberately part of this rail rather than a separate one — a
    lock-screen tap is easy to get wrong, and a wrong tap that cannot be taken
    back teaches people not to tap.
    """
    row = storage.get_finding(finding_id)
    if not row:
        return {'status': 'error', 'message': 'That finding is no longer here.'}
    if how == 'undo':
        storage.update_finding(finding_id, {'state': 'open', 'resolved_at': None,
                                            'resolved_by': None,
                                            'resolved_member_id': None})
        return {'status': 'success', 'message': 'Back on the list.'}
    if how not in ('tap', 'dismiss'):
        return {'status': 'error', 'message': f"Unknown resolution '{how}'."}
    storage.update_finding(finding_id, {
        'state': 'done' if how == 'tap' else 'dismissed',
        'resolved_at': time.time(), 'resolved_by': how,
        'resolved_member_id': member_id})
    return {'status': 'success',
            'message': 'Done.' if how == 'tap' else 'Left it.'}


def month_counts(since_ts: float) -> dict:
    """Real counts for the digest. Anything we cannot count, we do not say —
    there is no estimated-hours-saved here on purpose."""
    rows = [r for r in storage.get_findings()
            if (r.get('created_at') or 0) >= since_ts]
    out = {'watched': len(rows), 'cleared_themselves': 0, 'one_tap': 0,
           'decided': 0, 'expired': 0, 'still_open': 0}
    for r in rows:
        state, by = r.get('state'), r.get('resolved_by')
        if state == 'open':
            out['still_open'] += 1
        elif state == 'expired':
            out['expired'] += 1
        elif by == 'auto':
            out['cleared_themselves'] += 1
        elif by == 'tap':
            out['one_tap'] += 1
        else:
            out['decided'] += 1
    return out

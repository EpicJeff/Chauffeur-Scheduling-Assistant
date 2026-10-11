"""Situations — one shape for everything that needs a person.

Spec: docs/superpowers/specs/2026-10-09-situations-design.md. A situation is a
VIEW over a finding, insight, thread or mission row; nothing here owns a table.
Rows gain a few fields (rev, status_note, next_steps, note_ts, note_rev,
note_source, owner_member_id, owned_at) that this module alone writes.

Boundaries (same as the Mind's, enforced by tests on this file's source):
never import a DM accessor, never read gift records.
"""
import datetime
import json
import logging
import threading
import time
from typing import List, Optional

from services import storage

logger = logging.getLogger(__name__)

KINDS = ('finding', 'insight', 'thread', 'mission')
MISSION_HISTORY_CAP = 60      # the terminal rows /api/missions/admin ships; the lane matches it
VERBS = frozenset({'assign', 'ask', 'plan', 'prepare', 'do', 'done', 'skip',
                   'research', 'draft', 'advance', 'answer', 'close', 'snooze',
                   'dismiss', 'own', 'unread', 'release'})
WRITE_ROLES = ('parent', 'adult')
# Situation ownership ("I'll handle it myself") lives in its own fields: a
# thread row already uses owner_member_id for who CARRIES the thread.
OWNER = 'sit_owner_member_id'
OWNED_AT = 'sit_owned_at'


def _opt(verb: str, label: str, payload: dict = None, key: str = '') -> dict:
    """An option whose id is derived from what it does, so a stale id from an
    earlier view cannot be mistaken for a current one."""
    return {'id': f"{verb}:{key}" if key else verb, 'label': label,
            'verb': verb, 'payload': dict(payload or {})}


# --- loading ---------------------------------------------------------------

def load(kind: str, sid: str) -> Optional[dict]:
    if kind == 'finding':
        return storage.get_finding(sid)
    if kind == 'insight':
        return storage.get_mind_insight(sid)
    if kind == 'thread':
        return storage.get_thread(sid)
    if kind == 'mission':
        row = storage.get_mission(sid)
        if row:
            row = dict(row)
            row['steps'] = storage.get_mission_steps(sid)
        return row
    return None


def _update(kind: str, sid: str, fields: dict) -> bool:
    if kind == 'finding':
        return storage.update_finding(sid, fields)
    if kind == 'insight':
        return storage.update_mind_insight(sid, fields)
    if kind == 'thread':
        return storage.update_thread(sid, fields)
    if kind == 'mission':
        return storage.update_mission(sid, fields)
    return False


def _member_name(member_id) -> str:
    m = storage.get_member(member_id or '') if member_id else None
    return (m or {}).get('name') or ''


def _cached_event(event_id: str) -> Optional[dict]:
    sched = storage.get_cached_schedule() or {}
    return next((e for e in sched.get('events') or []
                 if str(e.get('id')) == str(event_id)), None)


def _parse(iso):
    try:
        return datetime.datetime.fromisoformat(str(iso).replace('Z', '+00:00')).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


# --- deterministic options, per kind ---------------------------------------

def _tail(kind: str, row: dict) -> list:
    """The options every kind ends with: take it, and leave it."""
    out = []
    if not row.get(OWNER):
        out.append(_opt('own', "I'll handle it myself"))
    else:
        out.append(_opt('done', 'Handled'))
    if kind in ('finding', 'insight'):
        out.append(_opt('snooze', 'Not now', {'days': 7}, '7'))
        out.append(_opt('dismiss', 'Dismiss'))
    elif kind == 'thread':
        out.append(_opt('close', 'Drop it', {'state': 'dropped'}, 'dropped'))
    elif kind == 'mission':
        out.append(_opt('close', 'Drop the mission', {'state': 'dropped'}, 'dropped'))
    return out


def _options_finding(row: dict) -> list:
    out = []
    if row.get('kind') == 'unassigned' and row.get('subject_id'):
        ev = _cached_event(row['subject_id'])
        if ev:
            from services import coverage_options as _cov
            try:
                rung = _cov.ladder(ev)
            except Exception as e:
                logger.warning(f"[situations] ladder failed for {row['subject_id']}: {e}")
                rung = {}
            title = ev.get('title') or 'the ride'
            start = _parse(ev.get('start'))
            when = start.strftime('%A %I:%M %p').replace(' 0', ' ') if start else ''
            what = f"drive {title}{' ' + when if when else ''}"
            fp = f"{row['subject_id']}|{start.timestamp() if start else ''}"
            for a in rung.get('actions') or []:
                if a.get('action_type') == 'reassign_driver':
                    out.append(_opt('assign', a['label'], a['payload'], a['payload'].get('driver_name', '')))
                elif a.get('action_type') == 'ask_outside_hand' and a['payload'].get('contact_id'):
                    out.append(_opt('ask', a['label'], {
                        'to': {'name': a['payload'].get('contact_name', ''),
                               'contact_id': a['payload']['contact_id']},
                        'what': what,
                        'unlocks': {'action_type': 'assist_assignment',
                                    'payload': {'event_id': row['subject_id'],
                                                'contact_id': a['payload']['contact_id'],
                                                'event_title': title,
                                                'event_date': start.date().isoformat() if start else ''},
                                    'fingerprint': fp}}, a['payload']['contact_id']))
            # Asking somebody new is always possible, whatever the ladder said.
            out.append(_opt('ask', 'Ask someone', {
                'to': {}, 'what': what,
                'unlocks': {'action_type': 'assist_assignment',
                            'payload': {'event_id': row['subject_id'], 'event_title': title,
                                        'event_date': start.date().isoformat() if start else ''},
                            'fingerprint': fp}}, 'new'))
    elif row.get('proposal_id'):
        prop = storage.get_action_proposal(row['proposal_id'])
        if prop and prop.get('status') == 'proposed':
            out.append(_opt('do', prop.get('summary') or 'Approve', {'proposal_id': prop['id']}, prop['id']))
    return out + _tail('finding', row)


def _options_insight(row: dict) -> list:
    out = []
    steps = ((row.get('plan_json') or {}).get('steps') or [])
    if not steps:
        prop = row.get('proposal_json') or {}
        if prop.get('proposal_id'):
            out.append(_opt('do', prop.get('summary') or 'Approve', {'proposal_id': prop['proposal_id']},
                            prop['proposal_id']))
        else:
            approach = (row.get('approach') or '').strip()
            out.append(_opt('plan', f"Plan: {approach}" if approach else 'Make a plan'))
    for s in steps:
        if s.get('status') != 'open':
            continue
        bound = (s.get('proposal_json') or {}).get('proposal_id')
        if s.get('kind') == 'tool' and not bound:
            out.append(_opt('prepare', s.get('text') or 'Line it up', {'step_id': s['id']}, s['id']))
        elif s.get('kind') == 'tool':
            out.append(_opt('do', s.get('text') or 'Approve', {'step_id': s['id'], 'proposal_id': bound}, s['id']))
        else:
            out.append(_opt('done', s.get('text') or 'Done', {'step_id': s['id']}, s['id']))
    for s in steps:
        if s.get('status') == 'open':
            out.append(_opt('skip', f"Skip: {s.get('text') or ''}".strip(), {'step_id': s['id']}, s['id']))
    return out + _tail('insight', row)


def _reply_option(row: dict):
    """The highlighted move after a counterparty's reply (spec 2026-10-10
    §2), while that reply is the newest real thing on the thread. Deterministic:
    the reading, when there is one, else the mail's first line."""
    history = [h for h in (row.get('history') or []) if h.get('kind') != 'drafted']
    if history and history[-1].get('kind') == 'mission' and (history[-1].get('next_action') or '').strip():
        # A mission just finished here: its pre-filled next step leads (browse missions §4).
        h = history[-1]
        return _opt('advance', h['next_action'], {'next_action': h['next_action'], 'next_action_at': h.get('next_action_at')}, 'mission')
    if not history or history[-1].get('kind') != 'received':
        return None
    h = history[-1]
    who = row.get('counterparty_name') or 'them'
    reading = h.get('reading') or {}
    answer = reading.get('answer') if not reading.get('disputed') else None
    summary = (reading.get('summary') or '').strip()
    if answer == 'yes':
        label = f"Confirm with {who}: {summary}" if summary else f"Confirm with {who}"
        return _opt('advance', label, {'next_action': label}, 'confirm')
    if answer == 'no':
        return None
    if answer == 'question':
        return _opt('draft', f"Reply: {summary}" if summary else 'Reply to them', {'text': summary}, 'reply')
    # The received entry reads "Received from {addr}: {subject}\n\n{body}":
    # the mail's first line is the first non-empty line after the blank one.
    body = (h.get('text') or '')
    first = next((ln.strip() for ln in body.split('\n')[2:] if ln.strip()), '') if '\n\n' in body else ''
    hint = summary or first
    label = f"Read their reply: {hint}" if hint else 'Read their reply'
    return _opt('advance', label, {'next_action': label}, 'read')


def _thread_mission(row: dict):
    """The newest live mission opened from this thread, or None."""
    rows = [m for m in storage.get_missions() if m.get('origin_kind') == 'thread' and m.get('origin_ref') == row.get('id')
            and m.get('status') in ('running', 'browsing', 'waiting_user', 'waiting_retry')]
    rows.sort(key=lambda m: m.get('created_at') or 0)
    return rows[-1] if rows else None


def _options_thread(row: dict) -> list:
    from services import threads as _th
    out = []
    # The thread carries its mission's ask (browse missions §4): the question
    # or the release leads, with ids that route to the mission in act().
    m = _thread_mission(row)
    if m and m.get('status') == 'waiting_user':
        mrow = load('mission', m['id'])
        for o in _options_mission(mrow or {}):
            if o['verb'] in ('answer', 'release'):
                sub = o['id'].split(':', 1)[1] if ':' in o['id'] else ''
                out.append(_opt(o['verb'], o['label'], o['payload'], f"mission:{m['id']}" + (f":{sub}" if sub else '')))
    lead = _reply_option(row)
    if lead:
        out.append(lead)
    stalled = _th.is_stalled(row)
    if stalled == 'overdue' or not row.get('next_action'):
        out.append(_opt('advance', 'Set the next step', {}))
    out.append(_opt('draft', 'Draft a message', {}))
    if stalled != 'overdue' and row.get('next_action'):
        out.append(_opt('advance', 'Change the next step', {}))
    out.append(_opt('research', 'Look something up', {}))
    from services import asks as _asks
    for a in _asks.asks_for('thread', row.get('id'), row):
        if a.get('answered_by') == 'argyle' and a.get('state') in ('yes', 'no'):
            out.append(_opt('unread', 'Argyle got it wrong', {'ask_id': a['id']}, a['id']))
    out.append(_opt('close', 'Done with it', {'state': 'done'}, 'done'))
    return out + _tail('thread', row)


def _options_mission(row: dict) -> list:
    out = []
    steps = row.get('steps') or []
    if row.get('status') == 'waiting_user':
        asked = next((s for s in reversed(steps) if s.get('kind') == 'ask'), None)
        rj = (asked or {}).get('result_json') or {}
        if (asked or {}).get('name') == 'release':
            # The contact card leaves the house only on this tap (browse missions §1).
            out.append(_opt('release', f"Share with {rj.get('site')}", {'decision': 'approve'}, 'approve'))
            out.append(_opt('release', 'Not these', {'decision': 'decline'}, 'decline'))
            out.append(_opt('release', 'Stop the mission', {'decision': 'stop'}, 'stop'))
        else:
            q = rj.get('question') or 'Argyle has a question'
            out.append(_opt('answer', q, {}))
    for s in steps:
        if s.get('kind') != 'proposal':
            continue
        pid = (s.get('result_json') or {}).get('proposal_id')
        prop = storage.get_action_proposal(pid) if pid else None
        if prop and prop.get('status') == 'proposed':
            out.append(_opt('do', prop.get('summary') or 'Approve', {'proposal_id': pid}, pid))
    if _is_done('mission', row):
        return out         # a finished mission keeps only the decisions it left behind
    return out + _tail('mission', row)


def options_for(kind: str, row: dict) -> list:
    builder = {'finding': _options_finding, 'insight': _options_insight,
               'thread': _options_thread, 'mission': _options_mission}[kind]
    if kind != 'mission' and _is_done(kind, row):
        return []          # a closed situation offers nothing; dismissed is dismissed
    opts = [o for o in builder(row) if o['verb'] in VERBS]
    if row.get(OWNER):
        # Somebody took it: finishing is the next step; the rest stays offered.
        opts.sort(key=lambda o: 0 if o['id'] == 'done' else 1)
    # Argyle's cached suggestions ride along on THREADS only (the verbs it may
    # suggest are thread moves), already verb-checked at refresh, and only
    # while the note describes the row as it stands.
    if kind == 'thread' and (row.get('note_rev') or 0) == (row.get('rev') or 0):
        for extra in (row.get('next_steps') or []):
            if extra.get('verb') in VERBS and extra.get('id') not in {o['id'] for o in opts}:
                opts.insert(0, extra)
    return opts


# --- facts and fallback note ------------------------------------------------

def _fmt_day(ts) -> str:
    try:
        return datetime.datetime.fromtimestamp(float(ts)).strftime('%b %d')
    except (TypeError, ValueError):
        return ''


def _last_ts(row: dict) -> float:
    hist = row.get('history') or []
    return (hist[-1].get('ts') if hist else None) or row.get('created_at') or 0


def fallback_note(kind: str, row: dict) -> str:
    if kind == 'finding':
        return row.get('line') or ''
    if kind == 'insight':
        return row.get('detail') or row.get('line') or ''
    if kind == 'thread':
        who = row.get('counterparty_name') or 'them'
        nxt = row.get('next_action') or 'no next action set'
        when = f" ({row['next_action_at']})" if row.get('next_action_at') else ''
        if row.get('state') == 'waiting':
            return f"Waiting on {who} since {_fmt_day(_last_ts(row))}; next: {nxt}{when}"
        return f"Next: {nxt}{when}"
    if kind == 'mission':
        last = (row.get('steps') or [{}])[-1]
        return f"{row.get('status')}: {last.get('name') or 'no steps yet'}"
    return ''


def _since(kind: str, row: dict) -> float:
    if kind == 'thread':
        return _last_ts(row)
    if kind == 'mission':
        steps = row.get('steps') or []
        return (steps[-1].get('ts') if steps else None) or row.get('created_at') or 0
    if kind == 'insight':
        return row.get('created_ts') or 0
    return row.get('created_at') or 0


def _people(kind: str, row: dict) -> list:
    if kind == 'insight':
        return [r for r in (row.get('refs') or []) if not str(r).startswith('#')]
    if kind == 'thread':
        return [n for n in (row.get('counterparty_name'), _member_name(row.get('owner_member_id'))) if n]
    if kind == 'mission':
        return [n for n in (_member_name(row.get('created_by')),) if n]
    return []


def _state(kind: str, row: dict) -> str:
    return row.get('status') if kind == 'mission' else (row.get('state') or '')


def _is_done(kind: str, row: dict) -> bool:
    st = _state(kind, row)
    if kind == 'finding':
        return st in ('done', 'dismissed', 'expired')
    if kind == 'insight':
        return st == 'retired'
    if kind == 'thread':
        return st in ('done', 'dropped')
    return st in ('done', 'blocked', 'dropped')


def needs_attention(kind: str, row: dict, opts: list) -> bool:
    """Independent of engine status: anything with a decision left is live."""
    if kind == 'mission':
        return any(o['verb'] in ('answer', 'do', 'release') for o in opts)
    if kind == 'thread':
        from services import threads as _th
        return bool(_th.is_stalled(row)) and not _is_done(kind, row)
    return not _is_done(kind, row) and not row.get(OWNER)


def _group(kind: str, row: dict, opts: list) -> str:
    if _is_done(kind, row) and not needs_attention(kind, row, opts):
        return 'done'
    if row.get(OWNER) or _state(kind, row) == 'in_hand':
        return 'in_hand'
    if needs_attention(kind, row, opts):
        return 'now'
    if kind == 'thread' and _state(kind, row) == 'waiting':
        return 'waiting'
    return 'moving'


def can_see(kind: str, row: dict, viewer: Optional[dict]) -> bool:
    role = (viewer or {}).get('role')
    if kind == 'insight':
        if row.get('sensitivity') == 'sensitive':
            return role == 'parent'
        return True
    if kind == 'finding':
        return role in WRITE_ROLES
    if kind == 'thread':
        return role in WRITE_ROLES or bool(viewer and row.get('owner_member_id') == viewer.get('id'))
    return role in WRITE_ROLES


def view(kind: str, sid: str, viewer: Optional[dict] = None) -> Optional[dict]:
    if kind not in KINDS:
        return None
    row = load(kind, sid)
    if not row:
        return None
    opts = options_for(kind, row)
    from services import asks as _asks
    note = row.get('status_note') or ''
    source = row.get('note_source') or 'fallback'
    if not note or source != 'argyle' or (row.get('note_rev') or 0) != (row.get('rev') or 0):
        note, source = fallback_note(kind, row), 'fallback'
    title = {'finding': row.get('line'), 'insight': row.get('line'),
             'thread': row.get('title'), 'mission': row.get('goal')}[kind] or ''
    return {
        'kind': kind, 'id': sid, 'title': title,
        'state': _state(kind, row), 'since': _since(kind, row),
        'people': _people(kind, row),
        'due': row.get('due_at') if kind == 'finding' else (
            row.get('next_action_at') if kind == 'thread' else None),
        'status_note': note, 'note_source': source, 'note_ts': row.get('note_ts'),
        'next_step': opts[0] if opts else None, 'options': opts,
        'asks': _asks.asks_for(kind, sid, row),
        'needs_attention': needs_attention(kind, row, opts),
        'group': _group(kind, row, opts),
        'owner_member_id': row.get(OWNER),
        'sensitivity': row.get('sensitivity') if kind == 'insight' else None,
        'severity': row.get('severity') if kind == 'finding' else None,
        'confidence': row.get('confidence') if kind == 'insight' else None,
        'rev': row.get('rev') or 0,
    }


# --- listing and ranking ---------------------------------------------------

_SEV = {'decide': 0, 'approve': 1, 'fyi': 3}


def rank(rows: list) -> list:
    """decide findings by due, then approve, then insights by confidence,
    then fyi — the order somebody would work down it."""
    def key(s):
        if s['kind'] == 'finding':
            return (_SEV.get(s.get('severity'), 3), s.get('due') or float('inf'), s['since'])
        if s['kind'] == 'insight':
            return (2, -(s.get('confidence') or 0), s['since'])
        return (2.5, 0, s['since'])
    return sorted(rows, key=key)


def _rows_of(kind: str, include_done: bool) -> list:
    if kind == 'finding':
        from services import findings as _f
        now_ts = time.time()
        return [('finding', r['id']) for r in _f.open_findings(include_in_hand=True)
                if (r.get('snoozed_until') or 0) <= now_ts]
    if kind == 'insight':
        from services import mind as _m
        return [('insight', r['id']) for r in _m.visible_insights({'role': 'parent'})]
    if kind == 'thread':
        return [('thread', t['id']) for t in storage.get_threads(include_closed=include_done)]
    if kind == 'mission':
        # Live rows always; terminal rows capped to the same 60 newest that
        # /api/missions/admin ships (get_missions is newest-first), so every
        # card on /missions has its details row and a 15-second poll never
        # views the whole retention window.
        # A done/blocked row still gets viewed without include_done: one with
        # a decision left behind is live (group 'now'), and the caller drops
        # the rest by group. Only 'dropped' is skipped outright.
        out, terminal = [], 0
        for m in storage.get_missions():
            st = m.get('status')
            if st in ('done', 'blocked', 'dropped'):
                if (st == 'dropped' and not include_done) or terminal >= MISSION_HISTORY_CAP:
                    continue
                terminal += 1
            out.append(('mission', m['id']))
        return out
    return []


def list_situations(viewer: Optional[dict], kinds=None, include_done: bool = False,
                    owner: str = None, spoken: bool = False) -> list:
    """`owner` narrows THREADS to one member's own (the PWA House tab's
    view); the other kinds have no owner and are unaffected. `spoken` is a
    room, not a hand: a sensitive insight is never read aloud, whatever the
    viewer's role (spec 2026-10-10 §1)."""
    out = []
    for kind in (kinds or KINDS):
        for k, sid in _rows_of(kind, include_done):
            row = load(k, sid)
            if not row or not can_see(k, row, viewer):
                continue
            if owner and k == 'thread' and row.get('owner_member_id') != owner:
                continue
            if spoken and k == 'insight' and row.get('sensitivity') == 'sensitive':
                continue
            s = view(k, sid, viewer)
            if s and (include_done or s['group'] != 'done'):
                out.append(s)
    return rank(out)


# --- acting ------------------------------------------------------------------

def bump_rev(kind: str, sid: str) -> int:
    """Every mutation of the row, or of one of its asks, moves the revision.
    Writing the cached note never does (see refresh)."""
    with storage.db_lock:
        row = load(kind, sid) or {}
        rev = int(row.get('rev') or 0) + 1
        _update(kind, sid, {'rev': rev})
    return rev


def _refused(msg: str) -> dict:
    return {'status': 'refused', 'message': msg}


def _can_write(actor) -> bool:
    return bool(actor) and actor.get('role') in WRITE_ROLES


def parent_of_record() -> Optional[dict]:
    """Who a surface with no person acts as: the household's first parent.
    main._approver_of_record and the router's voice path both nominate this
    one member, so an ask from a satellite is asked by somebody real."""
    return next((m for m in storage.get_all_members()
                 if m.get('role') == 'parent' and not m.get('system')), None)


def own(kind: str, sid: str, actor: dict) -> dict:
    fields = {OWNER: actor['id'], OWNED_AT: time.time()}
    if kind == 'finding':
        fields['state'] = 'in_hand'
    if not _update(kind, sid, fields):
        return {'status': 'error', 'message': 'That is no longer here.'}
    bump_rev(kind, sid)
    return {'status': 'success', 'message': f"{actor.get('name') or 'You'} took it."}


def done(kind: str, sid: str, actor: dict) -> dict:
    if kind == 'finding':
        from services import findings as _f
        res = _f.resolve(sid, 'tap', member_id=actor.get('id'))
    elif kind == 'insight':
        res = {'status': 'success'} if storage.update_mind_insight(sid, {
            'state': 'retired', 'outcome': 'acted', 'resolved_ts': time.time()}) else \
            {'status': 'error', 'message': 'No such insight'}
    elif kind == 'thread':
        from services import threads as _th
        res = {'status': 'success'} if _th.close(sid, 'done', who=actor.get('id')) else \
            {'status': 'error', 'message': 'No such thread'}
    else:
        res = {'status': 'success'} if storage.update_mission(sid, {
            'status': 'done', 'finished_at': time.time()}) else {'status': 'error', 'message': 'No such mission'}
    if res.get('status') == 'success':
        bump_rev(kind, sid)
        request_refresh(kind, sid)
    return res


def act(kind: str, sid: str, verb: str, option_id: str = None, payload: dict = None,
        actor: dict = None) -> dict:
    """The single implementation behind every card button and every agent
    tool. The option is re-derived from the row RIGHT NOW; an id from an
    earlier view that no longer exists is refused, nothing runs."""
    if kind not in KINDS or verb not in VERBS:
        return _refused("That is not something I can do here.")
    if not _can_write(actor):
        return _refused("Only a parent or adult can do that.")
    row = load(kind, sid)
    if not row:
        return {'status': 'error', 'message': 'That is no longer here.'}
    if not can_see(kind, row, actor):
        return _refused("That one is not yours to handle.")
    opts = options_for(kind, row)
    if _is_done(kind, row) and not needs_attention(kind, row, opts):
        return _refused("That one is already settled.")
    opt = next((o for o in opts if o['id'] == (option_id or verb) and o['verb'] == verb), None)
    if not opt:
        return _refused("That option is no longer on the table; the situation moved. Take another look.")
    if kind == 'thread' and opt['id'].startswith(f"{verb}:mission:"):
        # The thread's option is its mission's: act on the mission (its own
        # options re-derived, every gate kept), then the thread moved too.
        bits = opt['id'].split(':')
        mid, sub = bits[2], ':'.join(bits[3:])
        res = act('mission', mid, verb, option_id=f"{verb}:{sub}" if sub else verb, payload=payload, actor=actor)
        if res.get('status') in ('success', 'proposed', 'planned'):
            bump_rev(kind, sid)
            request_refresh(kind, sid)
        return res
    p = dict(opt['payload'])
    free = payload or {}
    if verb in ('answer', 'advance', 'draft', 'research'):
        # A blank free value never overwrites an option's pre-filled one (a
        # reading-built "Confirm with …" arrives with its next_action set).
        p.update({k: v for k, v in free.items()
                  if k in ('text', 'next_action', 'next_action_at', 'note') and v not in (None, '')})
    if verb == 'snooze' and isinstance(free.get('days'), int):
        p['days'] = max(1, min(60, free['days']))

    res = _run(kind, sid, verb, p, actor, row)
    if res.get('status') in ('success', 'proposed', 'planned'):
        bump_rev(kind, sid)
        request_refresh(kind, sid)
    return res


def _run(kind, sid, verb, p, actor, row) -> dict:
    if verb == 'own':
        return own(kind, sid, actor)
    if verb == 'done' and not p.get('step_id'):
        return done(kind, sid, actor)
    if verb == 'dismiss':
        if kind == 'finding':
            from services import findings as _f
            return _f.resolve(sid, 'dismiss', member_id=actor.get('id'))
        ok = storage.update_mind_insight(sid, {'state': 'retired', 'outcome': 'dismissed',
                                               'resolved_ts': time.time()})
        return {'status': 'success' if ok else 'error', 'message': 'Left it.'}
    if verb == 'snooze':
        days = int(p.get('days') or 7)
        if kind == 'insight':
            storage.update_mind_insight(sid, {'snoozed_until': time.time() + days * 86400})
        else:
            storage.update_finding(sid, {'snoozed_until': time.time() + days * 86400})
        return {'status': 'success', 'message': f"Parked for {days} days.", 'days': days}
    if verb == 'assign':
        from services.agent_tools_v2 import assign_driver_to_event_fuzzy
        res = assign_driver_to_event_fuzzy(p.get('event_name'), p.get('driver_name'), p.get('target_date'))
        if res.get('status') == 'success':
            res['schedule_dirty'] = True
        return res
    if verb == 'do':
        from services import chat_actions as _ca, mind as _mind
        res = _ca.act_on_proposal(p['proposal_id'], 'approve', actor)
        if res.get('status') == 'success' and kind == 'insight' and p.get('step_id'):
            closed = _mind.close_step(sid, p['step_id'], 'done')
            res['plan'] = closed.get('plan')
        if res.get('status') == 'success' and kind == 'insight' and not p.get('step_id'):
            storage.update_mind_insight(sid, {'state': 'retired', 'outcome': 'acted', 'resolved_ts': time.time()})
        return res
    if verb == 'plan':
        from services import mind as _mind
        return _mind.make_plan(sid, actor)
    if verb == 'prepare':
        from services import mind as _mind
        return _mind.bind_step(sid, p['step_id'], actor)
    if verb in ('done', 'skip'):
        from services import mind as _mind
        return _mind.close_step(sid, p['step_id'], 'done' if verb == 'done' else 'skipped')
    if verb == 'advance':
        from services import threads as _th
        if not (p.get('next_action') or '').strip():
            return {'status': 'error', 'message': 'Say what the next step is.'}
        ok = _th.advance(sid, p['next_action'], next_action_at=p.get('next_action_at'),
                         note=p.get('note'), who=actor.get('id'))
        return {'status': 'success' if ok else 'error', 'message': 'Next step set.'}
    if verb == 'draft':
        from services import threads as _th
        res = _th.draft_message(sid, intent=p.get('text') or '')
        return {**res, 'status': res.get('status') or 'success'}
    if verb == 'research':
        from services import threads as _th
        if not (p.get('text') or '').strip():
            return {'status': 'error', 'message': 'Say what to look up.'}
        return _th.research(sid, p['text'])
    if verb == 'answer':
        text = (p.get('text') or '').strip()
        if not text:
            return {'status': 'error', 'message': 'Say something to send.'}
        storage.add_mission_step(sid, {'kind': 'note', 'name': 'user_answer', 'result_json': {'text': text}})
        if row.get('status') == 'waiting_user':
            storage.update_mission(sid, {'status': 'running'})
        return {'status': 'success', 'message': 'Answered.'}
    if verb == 'close':
        state = p.get('state') or 'done'
        if kind == 'thread':
            from services import threads as _th
            ok = _th.close(sid, state, who=actor.get('id'))
        else:
            ok = storage.update_mission(sid, {'status': 'dropped' if state == 'dropped' else 'done',
                                              'finished_at': time.time()})
        return {'status': 'success' if ok else 'error', 'message': 'Closed.'}
    if verb == 'release':
        from services import missions as _m
        return _m.release(sid, p.get('decision'), actor)
    if verb == 'unread':
        from services import asks as _asks
        return _asks.unread(p.get('ask_id'), actor)
    if verb == 'ask':
        # The ask flow has its own endpoint/tool (asks.create); the option only
        # carries what the ask would be. Reaching here means a client posted
        # an ask verb to /act. Point it at the right door.
        return {'status': 'error', 'message': 'Start the ask with POST /api/asks.'}
    return _refused("That is not something I can do here.")


# --- refresh: Argyle's note, on state change only ----------------------------

REFRESH_DELAY_S = 2.0
NOTE_TIMEOUT_S = 20
CAP_NOTES_DEFAULT = 60

NOTE_SYSTEM = (
    "You are Argyle, a family home's assistant. You are shown ONE thing that "
    "needs a person: its facts, recent history and open asks. Write "
    "status_note: one or two plain sentences on where it stands (no advice, "
    "no praise). Then options: up to 3 concrete next moves, each with a verb "
    "from this closed list and ONLY this list: advance (payload next_action, "
    "next_action_at YYYY-MM-DD), draft (payload text: what the message should "
    "say), research (payload text: the question), close (payload state "
    "done|dropped). A move names a person or a thing. Return STRICT JSON: "
    '{"status_note": "...", "options": [{"label": "...", "verb": "...", '
    '"payload": {}}]}. Never invent facts.'
)

_pending: dict = {}
_pending_lock = threading.Lock()


def _pool_call(tier, api_key, system, prompt, **kw):
    """Indirection so tests stub one attribute (mind.py precedent)."""
    from services import model_pools
    return model_pools.call_pool_json(tier, api_key, system, prompt, **kw)


def _bump_call(kind: str, cap: int) -> bool:
    day = datetime.date.today().isoformat()
    key = f'situation_calls:{day}'
    # Locked: the ingest poll and a request thread both bump this.
    with storage.db_lock:
        counts = dict(storage.get_app_state(key) or {})
        if int(counts.get(kind, 0)) >= cap:
            return False
        counts[kind] = int(counts.get(kind, 0)) + 1
        storage.set_app_state(key, counts)
    return True


def _count_held(kind: str):
    day = datetime.date.today().isoformat()
    key = f'situation_held:{day}'
    counts = dict(storage.get_app_state(key) or {})
    counts[kind] = int(counts.get(kind, 0)) + 1
    storage.set_app_state(key, counts)


def held_notes_today() -> int:
    day = datetime.date.today().isoformat()
    return int((storage.get_app_state(f'situation_held:{day}') or {}).get('note', 0))


def _facts(kind: str, row: dict) -> str:
    lines = [f"kind: {kind}", f"state: {_state(kind, row)}",
             f"since: {_fmt_day(_since(kind, row))}", f"people: {', '.join(_people(kind, row)) or '-'}"]
    if kind == 'thread':
        lines.append(f"title: {row.get('title')}; goal: {row.get('goal') or '-'}; "
                     f"counterparty: {row.get('counterparty_name') or '-'}; "
                     f"next: {row.get('next_action') or '-'} ({row.get('next_action_at') or 'no date'})")
        for h in (row.get('history') or [])[-10:]:
            lines.append(f"- [{h.get('kind')}] {_fmt_day(h.get('ts'))} {h.get('who') or ''}: {(h.get('text') or '')[:200]}")
    elif kind == 'mission':
        lines.append(f"goal: {row.get('goal')}; summary: {row.get('summary') or '-'}; error: {row.get('error') or '-'}")
        for s in (row.get('steps') or [])[-10:]:
            lines.append(f"- [{s.get('kind')}] {s.get('name')}: {json.dumps(s.get('result_json') or {})[:200]}")
    elif kind == 'finding':
        lines.append(f"line: {row.get('line')}; severity: {row.get('severity')}; due: {_fmt_day(row.get('due_at'))}")
    else:
        lines.append(f"line: {row.get('line')}; detail: {row.get('detail') or '-'}; approach: {row.get('approach') or '-'}")
        for s in ((row.get('plan_json') or {}).get('steps') or []):
            lines.append(f"- step [{s.get('status')}] {s.get('text')}")
    from services import asks as _asks
    for a in _asks.asks_for(kind, row['id'], row):
        lines.append(f"- ask {a.get('to_name')} by {a.get('channel')}: {a.get('what')} -> {a.get('state')}"
                     f"{(' / ' + a['outcome']) if a.get('outcome') else ''}")
    return '\n'.join(lines)


def _write_fallback(kind, sid, row):
    _update(kind, sid, {'status_note': fallback_note(kind, row), 'next_steps': [],
                        'note_ts': time.time(), 'note_rev': int(row.get('rev') or 0),
                        'note_source': 'fallback'})


def refresh(kind: str, sid: str) -> dict:
    """One call, synchronous. Captures rev first; a result for an older rev is
    thrown away. Writing the note never bumps rev."""
    row = load(kind, sid)
    if not row:
        return {'status': 'not_found'}
    settings = storage.get_settings() or {}
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key:
        _write_fallback(kind, sid, row)
        return {'status': 'no_key'}
    cap = int(settings.get('situation_cap_notes', CAP_NOTES_DEFAULT))
    if not _bump_call('note', cap):
        _count_held('note')
        _write_fallback(kind, sid, row)
        return {'status': 'capped'}
    rev_at_start = int(row.get('rev') or 0)
    try:
        res = _pool_call('interactive', api_key, NOTE_SYSTEM, _facts(kind, row),
                         timeout_s=NOTE_TIMEOUT_S, background=True, workflow='situations.note')
    except Exception as e:
        logger.warning(f"[situations] note call failed for {kind}/{sid}: {e}")
        res = None
    if not isinstance(res, dict) or not (res.get('status_note') or '').strip():
        _write_fallback(kind, sid, row)
        return {'status': 'fallback'}
    fresh = load(kind, sid) or {}
    if int(fresh.get('rev') or 0) != rev_at_start:
        request_refresh(kind, sid)
        return {'status': 'superseded'}
    options = []
    for i, o in enumerate(res.get('options') or [] if kind == 'thread' else []):
        verb = (o or {}).get('verb')
        if verb not in ('advance', 'draft', 'research', 'close'):
            continue
        payload = dict((o.get('payload') or {}))
        if verb == 'close' and payload.get('state') not in ('done', 'dropped'):
            continue
        options.append({'id': f"{verb}:argyle:{i}", 'label': (o.get('label') or verb)[:120],
                        'verb': verb, 'payload': payload})
    _update(kind, sid, {'status_note': res['status_note'].strip()[:400], 'next_steps': options,
                        'note_ts': time.time(), 'note_rev': rev_at_start, 'note_source': 'argyle'})
    return {'status': 'noted'}


def request_refresh(kind: str, sid: str) -> None:
    """Coalesced: repeat requests inside REFRESH_DELAY_S for the same row
    collapse to one call, run on a timer thread so the mutator never waits."""
    key = (kind, sid)
    if REFRESH_DELAY_S <= 0:
        # Tests: no timer thread, no race with flush_refreshes.
        _run_pending(key)
        return
    with _pending_lock:
        old = _pending.pop(key, None)
        if old:
            old.cancel()
        t = threading.Timer(REFRESH_DELAY_S, _run_pending, args=(key,))
        t.daemon = True
        _pending[key] = t
        t.start()


def _run_pending(key):
    with _pending_lock:
        _pending.pop(key, None)
    try:
        refresh(*key)
    except Exception as e:
        logger.warning(f"[situations] refresh failed for {key}: {e}")


def flush_refreshes() -> int:
    """Tests only: run everything pending now, on this thread."""
    with _pending_lock:
        keys = list(_pending)
        for t in _pending.values():
            t.cancel()
        _pending.clear()
    for key in keys:
        _run_pending(key)
    return len(keys)


def touched(kind: str, sid: str) -> None:
    """A mutator says the row moved: bump rev, ask for a note."""
    bump_rev(kind, sid)
    request_refresh(kind, sid)

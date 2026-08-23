"""The solution ladder for an event nobody is driving.

`🚨 No driver yet: Soccer practice — Thu 5:00 PM` is a true sentence that
helps nobody. The parent still has to replay the whole day in their head to
work out whether anyone could take it, and if the answer is no, they have to
work out what to do instead. That replay is the load; this module does it.

Three tiers, in the order a person would think:

    1. Somebody at home is free at that hour. Say who, and offer the tap.
    2. Nobody is — but an outside hand has covered this before. Draft the ask.
    3. Nobody is, and nobody has. Say so, and NAME THE REASONS, because the
       reasons are what turn a ten-minute rethink into a ten-second decision.

Two honesty rules the tiers depend on:

**Tier 1 is an override, and says so.** The solver already tried and left this
event unassigned, so a driver who is merely clock-free was refused for some
other reason — a routing rule, a car, a knock-on cost elsewhere in the day.
Offering "Assign Jeff" is offering a manual override, which a family is
completely entitled to make. What it must never do is imply the solver
overlooked something.

**The reasons come from the clock, not from the model.** This runs in a sweep
that must stay free and deterministic, so it reads the cached schedule rather
than rebuilding the solver's world. Everything it reports is something a
parent can verify by looking: a drive at that time, a protected window, a day
marked away. `matcher.explain_assignment_conflicts` remains the deeper answer
for the override dialog, where the full model is already in hand.
"""
import datetime

from services import assist, storage

# Either side of the event, for the drive there and back. Coarse on purpose:
# this decides whether to OFFER somebody, and a near-miss the family knows how
# to make is theirs to judge.
BUFFER_MINS = 45


def _parse(val):
    try:
        return datetime.datetime.fromisoformat(str(val)).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def _fmt_span(a, b) -> str:
    def one(t):
        s = t.strftime('%I:%M %p').lstrip('0')
        return s.replace(':00 ', ' ').strip()
    return f"{one(a)}–{one(b)}"


def _driver_busy(driver_id, ev_start, ev_end, events, assignments):
    """The drive that stops them, or None. Overlap is measured with the buffer
    so a pickup twenty minutes after a dropoff across town is not offered as
    'free'."""
    lo = ev_start - datetime.timedelta(minutes=BUFFER_MINS)
    hi = ev_end + datetime.timedelta(minutes=BUFFER_MINS)
    for ev_id, d_id in (assignments or {}).items():
        if str(d_id) != str(driver_id):
            continue
        other = events.get(str(ev_id))
        if not other:
            continue
        o_start, o_end = _parse(other.get('start')), _parse(other.get('end'))
        if not o_start:
            continue
        o_end = o_end or o_start
        if o_start < hi and o_end > lo:
            return other
    return None


def _protected_window(member_id, ev_start):
    """A standing commitment (load arc A6) covering this hour. Protected time is
    a reason a person is not available, and naming it is the point — 'Sarah:
    Thursday run 6–7' reads as a decision the family already made."""
    for pc in storage.get_protected_commitments(member_id=member_id):
        if ev_start.weekday() not in set(pc.get('days_of_week') or []):
            continue
        try:
            sh, sm = [int(x) for x in (pc.get('time_start') or '18:00').split(':')[:2]]
            eh, em = [int(x) for x in (pc.get('time_end') or '20:00').split(':')[:2]]
        except (ValueError, TypeError):
            continue
        w_start = ev_start.replace(hour=sh, minute=sm, second=0, microsecond=0)
        w_end = ev_start.replace(hour=eh, minute=em, second=0, microsecond=0)
        if w_start <= ev_start <= w_end:
            return pc
    return None


def driver_options(ev, cache):
    """Every family driver, sorted into free and not, each with a reason.

    Returns (free, blocked) where free is [{id, name, span}] and blocked is
    [{id, name, reason}]. Both are returned because tier 3 needs the blocked
    list as much as tier 1 needs the free one.
    """
    ev_start = _parse(ev.get('start'))
    if not ev_start:
        return [], []
    ev_end = _parse(ev.get('end')) or ev_start + datetime.timedelta(hours=1)
    events = {str(e.get('id')): e for e in (cache.get('events') or [])}
    assignments = dict(cache.get('assignments') or {})
    members_by_driver = {}
    for m in storage.get_all_members():
        if m.get('driver_id'):
            members_by_driver[str(m['driver_id'])] = m

    free, blocked = [], []
    for d in storage.get_all_drivers():
        d_id = str(d.get('id') or d.get('doc_id') or '')
        name = d.get('name') or 'Somebody'
        if not d_id:
            continue
        member = members_by_driver.get(d_id) or {}
        # A disabled or archived member is not a driver any more (member status
        # ladder) — offering them would be offering somebody who cannot answer.
        if member.get('status') in ('disabled', 'archived'):
            continue
        busy = _driver_busy(d_id, ev_start, ev_end, events, assignments)
        if busy:
            blocked.append({'id': d_id, 'name': name,
                            'reason': f"driving {busy.get('title') or 'another event'}"})
            continue
        pc = _protected_window(member.get('id'), ev_start)
        if pc:
            blocked.append({'id': d_id, 'name': name,
                            'reason': f"{pc.get('title') or 'protected time'} "
                                      f"{pc.get('time_start')}–{pc.get('time_end')}"})
            continue
        free.append({'id': d_id, 'name': name,
                     'span': _fmt_span(ev_start - datetime.timedelta(minutes=BUFFER_MINS),
                                       ev_end + datetime.timedelta(minutes=BUFFER_MINS))})
    return free, blocked


def outside_hand_candidates(ev, limit: int = 2):
    """Contacts who have covered THIS event before, most recent first.

    History only — never a cold suggestion. Asking a family to text somebody
    the app picked out of a contact list is how an app gets uninstalled; asking
    them to text the person who drove this same practice last month is just
    what they were going to do anyway.
    """
    keys = set(assist.coverage_keys(ev))
    title = (ev.get('title') or '').strip().lower()
    contacts = {c['id']: c for c in storage.get_assist_contacts()}
    try:
        with storage.db_lock:
            history = [dict(h) for h in storage.assist_history_table.all()]
    except Exception as e:
        print(f"[coverage] history read failed: {e}")
        return []
    scored = {}
    for h in history:
        if h.get('action') != 'covered':
            continue
        cid = h.get('contact_id')
        contact = contacts.get(cid)
        if not contact or not assist.offers(contact, 'driving'):
            continue
        same = (str(h.get('event_id')) in keys
                or (title and (h.get('event_title') or '').strip().lower() == title))
        if not same:
            continue
        if h.get('ts', 0) >= scored.get(cid, {}).get('ts', -1):
            scored[cid] = {'contact': contact, 'ts': h.get('ts', 0)}
    rows = sorted(scored.values(), key=lambda r: r['ts'], reverse=True)
    return [r['contact'] for r in rows[:limit]]


def draft_ask(ev, contact_name: str = None) -> str:
    """The text a parent sends. Plain words, no link, no app branding — it goes
    into a conversation between friends, and anything that reads as generated
    makes the sender look like they could not be bothered to type."""
    start = _parse(ev.get('start'))
    title = ev.get('title') or 'an event'
    when = ''
    if start:
        when = f" {start.strftime('%A')} at {start.strftime('%I:%M %p').lstrip('0')}"
    who = f"{contact_name}, a" if contact_name else "A"
    return (f"{who}ny chance you could take {title}{when}? "
            f"We're stuck for a driver — no worries if not!")


def ladder(ev, cache=None, now=None) -> dict:
    """The whole answer for one uncovered event.

    Returns {tier, line, reasons, driver, contacts, actions}. `actions` are
    proposal-shaped so the caller can turn them into approve cards without
    knowing anything about what each one does.
    """
    cache = cache if cache is not None else (storage.get_cached_schedule() or {})
    now = now or datetime.datetime.now()
    title = ev.get('title') or 'Event'
    start = _parse(ev.get('start'))
    when = start.strftime('%a %m/%d %I:%M %p').replace(' 0', ' ').lstrip('0') if start else ''
    ev_id = str(ev.get('id'))
    date_str = start.date().isoformat() if start else ''

    # An ask already out for this event is the answer — the ladder must not
    # re-offer a rung the family is already standing on.
    waiting = [a for a in storage.get_coverage_asks(state='waiting')
               if str(a.get('event_id')) == ev_id]
    if waiting:
        who = waiting[0].get('contact_name') or 'someone'
        return {'tier': 0, 'line': f"⏳ {title} ({when}) — asked {who}, waiting to hear back.",
                'reasons': [], 'driver': None, 'contacts': [], 'actions': [],
                'severity': 'fyi', 'ask_id': waiting[0].get('id')}

    free, blocked = driver_options(ev, cache)
    reasons = [f"{b['name']}: {b['reason']}" for b in blocked]

    if free:
        pick = free[0]
        alt = f" ({free[1]['name']} is free too.)" if len(free) > 1 else ""
        return {
            'tier': 1, 'severity': 'approve',
            'line': (f"🚨 No driver yet: {title} — {when}. {pick['name']} is free "
                     f"{pick['span']}.{alt} Assigning is an override — the solver "
                     f"passed for some other reason."),
            'reasons': reasons, 'driver': pick, 'contacts': [],
            'actions': [{'label': f"Assign {pick['name']}",
                         'action_type': 'reassign_driver',
                         'payload': {'event_name': title, 'driver_name': pick['name'],
                                     'target_date': date_str}}],
        }

    contacts = outside_hand_candidates(ev)
    if contacts:
        c = contacts[0]
        why = f" ({'; '.join(reasons)})" if reasons else ""
        return {
            'tier': 2, 'severity': 'approve',
            'line': (f"🚨 {title} — {when}: nobody at home is free{why}. "
                     f"{c.get('name')} has covered this before."),
            'reasons': reasons, 'driver': None, 'contacts': contacts,
            'actions': [{'label': f"Ask {c.get('name')}",
                         'action_type': 'ask_outside_hand',
                         'payload': {'event_id': ev_id, 'contact_id': c.get('id'),
                                     'contact_name': c.get('name')}}],
        }

    why = '; '.join(reasons) if reasons else 'nobody at home is free'
    return {
        'tier': 3, 'severity': 'decide',
        'line': (f"🚨 {title} — {when}: can't cover with what we have. {why}. "
                 f"No outside hand has taken this one before."),
        'reasons': reasons, 'driver': None, 'contacts': [],
        'actions': [{'label': 'Ask someone new', 'action_type': 'ask_outside_hand',
                     'payload': {'event_id': ev_id}},
                    {'label': "We're skipping it", 'action_type': 'skip_occurrence',
                     'payload': {'event_id': ev_id}}],
    }


# --- The ask, and the way it comes back ------------------------------------
# The reply arrives as a text message the app cannot read, and on iOS there is
# no rail that would let it (Web Share Target is Android-only, which is why the
# share target was cut in v2.382). So the app does not chase the conversation.
# It holds the ASK, and asks the one question it actually needs answered — at
# the moments the answer is most likely to exist.

NUDGE_SCHEDULE_HOURS = (1, 6)      # after the ask, then again the same evening
FINAL_NUDGE_LEAD_HOURS = 18        # ... and once more before the event itself


def start_ask(event_id: str, contact_id: str = None, contact_name: str = None,
              asked_by: str = None) -> dict:
    """Record that a parent is asking somebody. Returns the drafted text — the
    parent sends it themselves, from their own phone, in their own thread."""
    cache = storage.get_cached_schedule() or {}
    ev = next((e for e in (cache.get('events') or [])
               if str(e.get('id')) == str(event_id)), None)
    if not ev:
        return {'status': 'error', 'message': 'That event is not in the current schedule.'}
    contact = storage.get_assist_contact(contact_id) if contact_id else None
    name = contact_name or (contact or {}).get('name') or ''
    start = _parse(ev.get('start'))
    ask_id = storage.add_coverage_ask({
        'event_id': str(event_id), 'event_title': ev.get('title') or '',
        'event_date': start.date().isoformat() if start else '',
        'event_start': ev.get('start') or '',
        'contact_id': contact_id or '', 'contact_name': name,
        'asked_by': asked_by or '', 'state': 'waiting'})
    text = draft_ask(ev, name or None)
    return {'status': 'success', 'ask_id': ask_id, 'text': text,
            'message': f"Asked{' ' + name if name else ''} — I'll check back. "
                       f"Send this:\n\n{text}"}


def answer_ask(ask_id: str, answer: str, member_id: str = None,
               contact_name: str = None) -> dict:
    """covered | no | waiting | undo. 'covered' writes the assist assignment,
    which is what actually takes the event out of the solve and closes the
    finding on the next sweep."""
    ask = storage.get_coverage_ask(ask_id)
    if not ask:
        return {'status': 'error', 'message': 'That ask is no longer here.'}
    name = contact_name or ask.get('contact_name') or 'They'

    if answer == 'waiting':
        # Re-arm rather than resolve: still waiting is an answer about the ask,
        # not about the drive.
        storage.update_coverage_ask(ask_id, {'nudges_sent': 0,
                                             'rearmed_at': _now_ts()})
        return {'status': 'success', 'message': "Fine — I'll ask again later."}

    if answer == 'undo':
        if ask.get('contact_id'):
            storage.clear_assist_assignment(ask['event_id'], actor=member_id)
        storage.update_coverage_ask(ask_id, {'state': 'waiting', 'resolved_at': None,
                                             'nudges_sent': 0})
        return {'status': 'success', 'message': 'Undone — still waiting to hear.'}

    if answer == 'no':
        storage.update_coverage_ask(ask_id, {'state': 'declined',
                                             'resolved_at': _now_ts(),
                                             'resolved_by': member_id or ''})
        return {'status': 'success', 'message': f"OK — {name} can't. Back to the list."}

    if answer != 'covered':
        return {'status': 'error', 'message': f"Unknown answer '{answer}'."}

    contact_id = ask.get('contact_id')
    if not contact_id:
        # Somebody new said yes. They become a real contact so that next time
        # they are a tier-2 candidate instead of a blank field.
        import uuid as _uuid
        new_name = (contact_name or '').strip() or 'A friend'
        contact_id = _uuid.uuid4().hex
        storage.add_assist_contact({'id': contact_id, 'name': new_name,
                                    'kinds': ['driving'], 'active': True})
        storage.update_coverage_ask(ask_id, {'contact_id': contact_id,
                                             'contact_name': new_name})
        name = new_name
    storage.set_assist_assignment(ask['event_id'], contact_id,
                                  note='confirmed by text',
                                  event_date=ask.get('event_date') or '',
                                  event_title=ask.get('event_title') or '',
                                  actor=member_id)
    storage.update_coverage_ask(ask_id, {'state': 'covered', 'resolved_at': _now_ts(),
                                         'resolved_by': member_id or ''})
    return {'status': 'success', 'schedule_dirty': True,
            'message': f"✓ {name} has {ask.get('event_title') or 'it'}."}


def _now_ts():
    import time as _t
    return _t.time()


def due_nudges(now=None) -> list:
    """Waiting asks whose next question is due. The cadence is written to match
    how a text conversation actually goes: soon after sending (most replies
    land inside the hour), once more that evening, and a last one before the
    event — after which silence has to be treated as a no."""
    now = now or datetime.datetime.now()
    now_ts = now.timestamp()
    out = []
    for ask in storage.get_coverage_asks(state='waiting'):
        base = ask.get('rearmed_at') or ask.get('asked_at') or 0
        sent = int(ask.get('nudges_sent') or 0)
        start = _parse(ask.get('event_start'))
        # The event has come and gone — stop asking, and say nothing further.
        if start and start < now:
            storage.update_coverage_ask(ask['id'], {'state': 'expired',
                                                    'resolved_at': now_ts})
            continue
        final_due = (start - datetime.timedelta(hours=FINAL_NUDGE_LEAD_HOURS)
                     if start else None)
        if sent < len(NUDGE_SCHEDULE_HOURS):
            if now_ts - base >= NUDGE_SCHEDULE_HOURS[sent] * 3600:
                out.append(ask)
        elif final_due and now >= final_due and sent == len(NUDGE_SCHEDULE_HOURS):
            out.append(ask)
    return out


def nudge_body(ask) -> str:
    who = ask.get('contact_name') or 'they'
    title = ask.get('event_title') or 'that drive'
    start = _parse(ask.get('event_start'))
    when = f" {start.strftime('%A')}" if start else ''
    return f"Did {who} take {title}{when}?"

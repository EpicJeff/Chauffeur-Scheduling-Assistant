"""Requests — the ask as a first-class object (load arc A3).

The design rules, in the order they matter:

1. **A request is always answered.** Silence is the failure mode this exists
   to fix, so an untouched request expires *loudly* rather than fading.
2. **Accepting performs the change.** The request IS the mechanism, not a
   note about one: accepting a drive swap reassigns the drive, accepting a
   task hand-off assigns the task.
3. **Declining is first-class and blameless.** A decline with a reason ("I'm
   in a meeting until 5") beats silence every single time, which is why
   `reason` sits on the object rather than being left to a chat message.
4. **One object for kid→parent and adult→adult**, because the state machine
   and the rails are identical — and because a teenager asking for a ride and
   a mother asking for Thursday evening deserve the same treatment.
"""
import datetime
import time

from services import storage

# How long an unanswered ask waits before it says so. Deliberately short: the
# whole point is that nothing sits unanswered, and a week-long window would
# make expiry meaningless for anything about today.
DEFAULT_TTL_HOURS = 20

KINDS = {
    'ride_change':  "a change to a ride",
    'pickup_early': "an earlier pickup",
    'swap_drive':   "somebody else to take a drive",
    'take_task':    "somebody to take a job",
    'cover':        "cover for an evening",
    'permission':   "permission",
    'other':        "something",
}


def _member(mid):
    return storage.get_member(mid) if mid else None


def _name(mid, fallback='Someone'):
    m = _member(mid)
    return (m or {}).get('name') or fallback


def _adults(exclude=()):
    return [m for m in storage.get_all_members()
            if m.get('role') in ('parent', 'adult')
            and m['id'] not in set(exclude) and not m.get('system')]


def _dm(member_id: str, body: str):
    """Argyle DM — push and HA fan-out come free with the chat rails."""
    try:
        from services.agent_tools_v2 import _post_chat_message
        argyle = storage.ensure_argyle_member()
        if member_id == argyle['id']:
            return
        dm = storage.get_or_create_dm(argyle['id'], member_id)
        _post_chat_message(dm, argyle, body)
    except Exception as e:
        print(f"[requests] DM to {member_id} failed: {e}")


def create(from_member_id: str, body: str, kind: str = 'other',
           to_member_id: str = None, subject_ref: str = None,
           subject_label: str = "", ttl_hours: int = None) -> dict:
    """Raise an ask and tell whoever owes the answer.

    An unaddressed request goes to every adult: "somebody please take this" is
    a real ask and must not require picking a victim.
    """
    from models.schemas import Request
    req = Request(from_member=from_member_id, to_member=to_member_id,
                  kind=kind if kind in KINDS else 'other',
                  subject_ref=subject_ref, subject_label=subject_label or "",
                  body=(body or '').strip(),
                  expires_at=time.time() + (ttl_hours or DEFAULT_TTL_HOURS) * 3600
                  ).model_dump()
    storage.add_request(req)

    asker = _name(from_member_id)
    about = f" about {subject_label}" if subject_label else ""
    line = f"🙋 {asker} is asking{about}: “{req['body']}”"
    targets = ([to_member_id] if to_member_id
               else [m['id'] for m in _adults(exclude=[from_member_id])])
    for t in targets:
        _dm(t, line + "\nTap Requests to answer — a yes or a no both work.")
    return req


def _perform(req: dict, decider: dict) -> str:
    """Do the thing the request was asking for. Returns a short suffix for the
    confirmation, or '' when the kind carries no automatic action.

    Only kinds that NAME something act. A `permission` or a bare `other` is a
    conversation, and inventing an action for it would be the app guessing at
    what a family meant.
    """
    kind, ref = req.get('kind'), req.get('subject_ref')
    if not ref:
        return ''
    try:
        if kind == 'take_task':
            if storage.get_household_task(ref):
                storage.update_household_task(ref, {'assigned_to': decider['id']})
                return " It's on your list now."
        elif kind == 'swap_drive':
            drv = decider.get('driver_id')
            if not drv:
                return " (You're not set up as a driver, so I left the schedule alone.)"
            storage.add_override({'event_id': ref, 'driver_id': drv,
                                  'created_at': time.time(), 'source': 'request'})
            return " The drive is yours — I'm re-solving the day."
    except Exception as e:
        print(f"[requests] perform {kind} failed: {e}")
        return " (I couldn't apply it automatically — worth a look.)"
    return ''


def decide(request_id: str, accept: bool, decider_id: str,
           reason: str = "") -> dict:
    """Answer an ask. Returns {'status', 'message', 'schedule_dirty'}."""
    req = storage.get_request(request_id)
    if not req:
        return {"status": "error", "message": "That request is gone."}
    if req.get('status') != 'open':
        return {"status": "error",
                "message": f"That one was already {req.get('status')}."}
    decider = _member(decider_id)
    if not decider:
        return {"status": "error", "message": "I don't know who's answering."}

    suffix = _perform(req, decider) if accept else ''
    storage.update_request(request_id, {
        'status': 'accepted' if accept else 'declined',
        'decided_by': decider_id, 'decided_at': time.time(),
        'reason': (reason or '').strip()})

    who = decider.get('name')
    if accept:
        note = f"✅ {who} said yes: “{req.get('body')}”" + suffix
    else:
        # Blameless, and a reason beats silence every time.
        because = f" — {reason.strip()}" if (reason or '').strip() else ""
        note = f"🙅 {who} can't{because}: “{req.get('body')}”"
    _dm(req['from_member'], note)

    return {"status": "success", "message": note.split('\n')[0],
            "schedule_dirty": bool(accept and req.get('kind') == 'swap_drive'
                                   and req.get('subject_ref'))}


def cancel(request_id: str, member_id: str) -> dict:
    req = storage.get_request(request_id)
    if not req:
        return {"status": "error", "message": "That request is gone."}
    if req.get('from_member') != member_id:
        return {"status": "error", "message": "Only the asker can take it back."}
    storage.update_request(request_id, {'status': 'cancelled'})
    return {"status": "success", "message": "Withdrawn."}


def sweep(now_ts: float = None) -> int:
    """Expire what nobody answered, and SAY SO — to the asker, who otherwise
    learns nothing, and to whoever owed the answer, because a request that
    quietly evaporates is the failure this object exists to prevent."""
    expired = storage.expire_stale_requests(now_ts)
    for r in expired:
        asker = _name(r.get('from_member'))
        _dm(r['from_member'],
            f"⌛ Nobody got back to you about “{r.get('body')}” — worth asking "
            f"out loud.")
        targets = ([r['to_member']] if r.get('to_member')
                   else [m['id'] for m in _adults(exclude=[r.get('from_member')])])
        for t in targets:
            _dm(t, f"⌛ {asker}'s request went unanswered: “{r.get('body')}”")
    return len(expired)


def summary_for(member_id: str) -> dict:
    """What this person is waiting on, and what is waiting on them."""
    waiting_on_me = [r for r in storage.get_requests(status='open', to_member=member_id)
                     if r.get('from_member') != member_id]
    mine = storage.get_requests(status='open', from_member=member_id)
    def _shape(r):
        return {'id': r['id'], 'from': _name(r.get('from_member')),
                'to': _name(r.get('to_member'), 'anyone') if r.get('to_member') else 'anyone',
                'body': r.get('body'), 'kind': r.get('kind'),
                'subject_label': r.get('subject_label') or '',
                'created_at': r.get('created_at')}
    return {'waiting_on_me': [_shape(r) for r in waiting_on_me],
            'mine': [_shape(r) for r in mine]}

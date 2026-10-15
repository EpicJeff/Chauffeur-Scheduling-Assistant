"""Exact readback followed by a separate deterministic release/submit approval."""
from dataclasses import dataclass
import hashlib
import json
import time
import uuid

from services import storage, voice_identity as identity


def tool_schema():
    return {'name': 'prepare_voice_approval', 'description': 'Read back one pending release or booking. Never approves it.',
            'parameters': {'type': 'object', 'properties': {
                'mission_ref': {'type': 'string', 'description': 'Mission ID or an unambiguous title/goal fragment.'},
                'kind': {'type': 'string', 'enum': ['release', 'submit']}}, 'required': ['mission_ref', 'kind']}}


def snapshot(ask, card=None):
    value = {'ask_id': ask['id'], 'kind': ask.get('name'), 'record': ask.get('result_json') or {}}
    if ask.get('name') == 'release':
        rj = ask.get('result_json') or {}
        fields = list(dict.fromkeys([*(rj.get('fields') or []), *(rj.get('missing') or [])]))
        value['contact_values'] = {field: (card or {}).get(field) for field in fields}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


@dataclass(frozen=True)
class ApprovalContext:
    voice_context: identity.VoiceContext
    readback_id: str
    ask_id: str
    kind: str
    digest: str
    approved_at: float

    def record(self):
        return {'channel': 'voice', 'member_id': self.voice_context.member_id,
                'session_generation': self.voice_context.generation, 'readback_id': self.readback_id,
                'approved_digest': self.digest, 'approved_at': self.approved_at,
                'satellite_id': self.voice_context.satellite_id, 'ha_instance_id': self.voice_context.ha_instance_id}


def valid(context, ask, actor, card=None):
    if not isinstance(context, ApprovalContext):
        return False
    ctx = context.voice_context
    # Domain callers hold db_lock: do not acquire the identity lock in reverse
    # order. Read the current generation, then validate member/config in storage.
    row = dict(identity._sessions.get((ctx.ha_instance_id, ctx.satellite_id)) or {})
    member = storage.get_member(ctx.member_id) if ctx.member_id else None
    from services.voice_tools import speech_safe
    mission = storage.get_mission(ask.get('mission_id')) or {}
    thread = storage.get_thread(mission.get('origin_ref')) if mission.get('origin_kind') == 'thread' else None
    if not speech_safe(mission) or not speech_safe(ask.get('result_json') or {}) or (thread and not speech_safe(thread)):
        return False
    return bool(member and storage.member_has_access(member) and actor and member['id'] == actor.get('id')
                and row.get('generation') == ctx.generation and row.get('level') == 'verified'
                and row.get('expires_at', 0) > time.time() and member.get('role') == row.get('role')
                and member.get('pin_hash') == row.get('pin_revision')
                and identity._paired(ctx.ha_instance_id, ctx.satellite_id, row.get('device_id'))
                and context.kind == ask.get('name') and context.ask_id == ask['id']
                and _enabled() and snapshot(ask, card) == context.digest)


def _enabled():
    config = identity.configuration()
    return config.get('enabled') and config.get('approvals_enabled', False)


def prepare(ctx, ref, kind):
    from services import missions, situations, browse
    from services.voice_tools import speech_safe
    if kind not in ('release', 'submit'):
        return {'status': 'refused', 'message': 'That needs your phone.'}
    if not _enabled():
        return {'status': 'refused', 'message': 'Voice approvals are not enabled. Use the card on your phone.'}
    member = ctx.verified_member()
    if not member:
        with identity._lock:
            row = identity._sessions.get((ctx.ha_instance_id, ctx.satellite_id))
            if ctx.paired and row:
                row['pending_prepare'] = {'ref': ref, 'kind': kind, 'request_id': ctx.request_id}
        return {'status': 'authentication', 'message': identity.challenge(ctx)}
    if member.get('role') not in ('parent', 'adult'):
        return {'status': 'refused', 'message': 'Only a parent or adult can approve this.'}
    candidates = []
    for mission in storage.get_missions(status=missions.ATTENTION):
        if not speech_safe(mission) or not situations.can_see('mission', mission, member):
            continue
        thread = storage.get_thread(mission.get('origin_ref')) if mission.get('origin_kind') == 'thread' else None
        if thread and not speech_safe(thread):
            continue
        hay = ' '.join(str(v or '') for v in (mission.get('goal'), (thread or {}).get('title'))).casefold()
        if ref and ref != mission['id'] and ref.strip().casefold() not in hay:
            continue
        ask = missions._pending_ask(mission['id'], kind)
        if ask:
            candidates.append((mission, ask))
    if len(candidates) != 1:
        return {'status': 'refused', 'message': 'Name the mission you want to approve, or choose its card on your phone.'}
    mission, ask = candidates[0]
    rj = ask.get('result_json') or {}
    if not speech_safe(rj):
        return {'status': 'refused', 'message': 'That question needs its private card on your phone.'}
    if kind == 'submit':
        # The complete DOM record remains the approved object, not just its spoken summary.
        if not rj.get('state') or not rj.get('facts') or not rj.get('button') or not rj.get('url'):
            return {'status': 'refused', 'message': 'This booking needs its complete card on your phone.'}
        question = missions.submit_question(browse._domain(rj.get('site') or rj.get('url')),
                                             missions._submit_verb(rj, mission.get('goal')),
                                             rj['facts'], rj['button'])
        card = None
        phrase = 'approve booking'
    else:
        fields = list(dict.fromkeys([*(rj.get('fields') or []), *(rj.get('missing') or [])]))
        card = browse.contact_card()
        allowed = set(browse.CONTACT_FIELDS)
        if not fields or not set(fields) <= allowed or any(not card.get(f) for f in fields):
            return {'status': 'refused', 'message': 'Review or complete those contact details on your phone.'}
        if not rj.get('site'):
            return {'status': 'refused', 'message': 'Review the destination on your phone first.'}
        question = f"Share with {browse._domain(rj['site'])}: " + '; '.join(f'{f.replace("_", " ")}: {card[f]}' for f in fields) + '?'
        phrase = 'approve release'
    question += f' Say {phrase}, or cancel.'
    with identity._lock:
        row = identity._sessions.get((ctx.ha_instance_id, ctx.satellite_id))
        if not row or row['generation'] != ctx.generation or not ctx.verified_member():
            return {'status': 'refused', 'message': 'Verify again before approving.'}
        row['readback'] = {'id': uuid.uuid4().hex, 'mission_id': mission['id'], 'ask_id': ask['id'],
                           'kind': kind, 'digest': snapshot(ask, card), 'request_id': ctx.request_id,
                           'expires_at': min(time.time() + 60, row['expires_at']), 'question': question}
    return {'status': 'success', 'message': question}


def after_verification(ctx):
    with identity._lock:
        row = identity._sessions.get((ctx.ha_instance_id, ctx.satellite_id))
        pending = row.pop('pending_prepare', None) if row else None
    return prepare(ctx, pending['ref'], pending['kind']) if pending else None


def intercept(text, ctx):
    phrase = (text or '').strip().lower().rstrip('.!?')
    if phrase not in ('approve booking', 'approve submission', 'approve release', 'cancel'):
        return None
    with identity._lock:
        row = identity._sessions.get((ctx.ha_instance_id, ctx.satellite_id))
        readback = row.pop('readback', None) if row else None
        if phrase == 'cancel':
            if row:
                row.pop('pending_prepare', None)
                row.update(pin_pending=False, name_pending=False)
            return {'status': 'cancelled', 'message': 'Cancelled. Nothing was approved.'}
        member = ctx.verified_member()
        if not _enabled() or not readback or not member or readback['expires_at'] <= time.time() \
                or readback['request_id'] == ctx.request_id:
            return {'status': 'refused', 'message': 'Ask me to read that back again before approving.'}
        expected_kind = 'release' if phrase == 'approve release' else 'submit'
        if readback['kind'] != expected_kind:
            return {'status': 'refused', 'message': 'That approval did not match. Ask me to read it back again.'}
        context = ApprovalContext(ctx, readback['id'], readback['ask_id'], readback['kind'], readback['digest'], time.time())
    from services import missions
    # Identity lock is released before the domain service starts a browser job.
    res = getattr(missions, readback['kind'])(readback['mission_id'], 'approve', member,
                                            ask_id=readback['ask_id'], approval_context=context)
    if res.get('status') == 'success' and not res.get('moved') and not res.get('already'):
        missions.settle_ask_cards(readback['mission_id'], readback['ask_id'], 'Approved by voice')
    return res


def current_readback(ctx):
    with identity._lock:
        row = identity._sessions.get((ctx.ha_instance_id, ctx.satellite_id)) or {}
        readback = row.get('readback') or {}
        if readback.get('request_id') == ctx.request_id:
            return readback.get('question')
        pending = row.get('pending_prepare') or {}
        return identity.challenge(ctx) if pending.get('request_id') == ctx.request_id else None

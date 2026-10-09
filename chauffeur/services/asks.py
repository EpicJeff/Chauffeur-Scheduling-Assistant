"""Asks — the one ledger of who was asked what, by which channel, and what
came back. Spec: docs/superpowers/specs/2026-10-09-situations-design.md §2.

Three facts are kept apart on purpose: the ask (a fixed commitment, `what`),
the answer (`state` yes/no, who said so), and what the app did with a yes
(`outcome`: claimed → applied | superseded | stale | failed). Only `applied`
means the promised work was done. The app never sends mail or texts for an
ask; a draft is copied and sent by the person. A Chauffeur ask is a DM from
the asker with Yes/No buttons.
"""
import datetime
import logging
import time
from typing import Optional

from services import storage

logger = logging.getLogger(__name__)

CHANNELS = ('chauffeur', 'email', 'text', 'in_person')
# Outcomes nothing moves past. `manual` is a yes the app had nothing to apply
# for; only `applied` ever means the promised work was done.
FINAL_OUTCOMES = ('applied', 'superseded', 'stale', 'failed', 'manual')
CLAIM_STALE_S = 60
CAP_DRAFTS_DEFAULT = 40
WRITE_ROLES = ('parent', 'adult')

DRAFT_SYSTEM = (
    "You draft a short message a parent will send THEMSELVES, in their own "
    "voice, asking somebody for one concrete thing. At most 80 words. Only "
    "the facts given (what, when, where); no invented details, no pressure, "
    "an easy out. Return STRICT JSON: {\"subject\": \"...\", \"body\": \"...\"}. "
    "For a text or in-person channel the subject is an empty string."
)


# --- who, and how to reach them ----------------------------------------------

def _resolve_to(to: dict) -> dict:
    to = dict(to or {})
    member = storage.get_member(to['member_id']) if to.get('member_id') else None
    contact = storage.get_assist_contact(to['contact_id']) if to.get('contact_id') else None
    name = to.get('name') or (member or {}).get('name') or (contact or {}).get('name') or 'them'
    return {'name': name, 'member_id': (member or {}).get('id'), 'contact_id': (contact or {}).get('id'),
            'email': (member or {}).get('email') or (contact or {}).get('email') or '',
            'phone': (contact or {}).get('phone') or '',
            'active_member': bool(member) and (member.get('status') or 'active') == 'active'}


def channels_for(to: dict) -> list:
    """Every channel, always; a known address only adds the one-tap link."""
    r = _resolve_to(to)
    out = []
    if r['active_member']:
        out.append({'channel': 'chauffeur', 'label': f"Message {r['name']} on Chauffeur", 'link': None})
    out.append({'channel': 'email', 'label': 'Email', 'link': f"mailto:{r['email']}" if r['email'] else None})
    out.append({'channel': 'text', 'label': 'Text', 'link': f"sms:{r['phone']}" if r['phone'] else None})
    out.append({'channel': 'in_person', 'label': 'Ask in person', 'link': None})
    return out


# --- drafting ------------------------------------------------------------------

def _pool_call(tier, api_key, system, prompt, **kw):
    from services import model_pools
    return model_pools.call_pool_json(tier, api_key, system, prompt, **kw)


def _template(ask: dict, channel: str, asker_name: str) -> dict:
    name = ask.get('to_name') or 'there'
    body = f"Hi {name}, any chance you could {ask.get('what')}? No worries if not. Thanks, {asker_name}"
    if channel == 'in_person':
        body = f"Ask {name}: could you {ask.get('what')}?"
    return {'subject': f"Could you {ask.get('what')}?" if channel == 'email' else '', 'body': body,
            'source': 'template'}


def draft(ask: dict, channel: str, settings: dict = None) -> dict:
    settings = settings if settings is not None else (storage.get_settings() or {})
    asker = (storage.get_member(ask.get('asked_by') or '') or {}).get('name') or 'us'
    fallback = _template(ask, channel, asker)
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key:
        return fallback
    from services import situations as _sit
    cap = int(settings.get('ask_cap_drafts', CAP_DRAFTS_DEFAULT))
    if not _sit._bump_call('draft', cap):
        return fallback
    prompt = (f"From: {asker}. To: {ask.get('to_name')}. Channel: {channel}. "
              f"The ask: {ask.get('what')}.")
    try:
        res = _pool_call('interactive', api_key, DRAFT_SYSTEM, prompt, timeout_s=20,
                         background=False, workflow='asks.draft')
    except Exception as e:
        logger.warning(f"[asks] draft failed: {e}")
        res = None
    if not isinstance(res, dict) or not (res.get('body') or '').strip():
        return fallback
    return {'subject': (res.get('subject') or '')[:120] if channel == 'email' else '',
            'body': res['body'].strip()[:600], 'source': 'argyle'}


# --- the ledger ----------------------------------------------------------------

def fingerprint_for_event(event_id: str) -> Optional[str]:
    """Only the facts that would invalidate an agreement to cover a ride: the
    occurrence and its start. Never rev, never a sibling ask."""
    from services.situations import _cached_event, _parse
    ev = _cached_event(event_id)
    if not ev:
        return None
    start = _parse(ev.get('start'))
    return f"{event_id}|{start.timestamp() if start else ''}"


def asks_for(kind: str, sid: str, row: dict = None) -> list:
    rows = storage.get_asks(situation_kind=kind, situation_id=sid)
    if kind == 'finding' and row and row.get('subject_type') == 'event' and row.get('subject_id'):
        ids = {a['id'] for a in rows}
        fp = row.get('fingerprint')
        for a in storage.get_asks(event_id=row['subject_id']):
            # A legacy or situation-less event ask attaches by occurrence.
            if a['id'] not in ids and (not fp or (a.get('unlocks') or {}).get('fingerprint') in (None, fp)):
                rows.append(a)
    rows.sort(key=lambda a: a.get('asked_at') or 0)
    return rows


def _can_write(actor) -> bool:
    return bool(actor) and actor.get('role') in WRITE_ROLES


def create(kind: str, sid: Optional[str], to: dict, what: str, channel: str, asked_by: str,
           unlocks: dict = None, draft_mode: str = 'model', event: dict = None,
           trusted: bool = False) -> dict:
    """Record the ask and draft it. A Chauffeur ask is posted at once (it is
    the asker speaking through Argyle); every other channel waits for the
    person to say it left. `trusted` is for the legacy coverage adapter,
    whose endpoints already gated the caller (`_needs_you_actor`)."""
    asker = storage.get_member(asked_by or '') or {'id': asked_by or '', 'role': 'parent' if trusted else ''}
    if not trusted and not _can_write(asker):
        return {'status': 'refused', 'message': 'Only a parent or adult can ask.'}
    if channel not in CHANNELS or not (what or '').strip():
        return {'status': 'error', 'message': 'Say what to ask, and how.'}
    r = _resolve_to(to)
    if channel == 'chauffeur' and not r['active_member']:
        return {'status': 'error', 'message': f"{r['name']} is not on Chauffeur: text, email or ask in person."}
    data = {'situation_kind': kind, 'situation_id': sid, 'to_name': r['name'],
            'to_member_id': r['member_id'], 'to_contact_id': r['contact_id'],
            'what': what.strip(), 'channel': channel, 'asked_by': asker.get('id') or asked_by or '',
            'unlocks': unlocks,
            'event_id': ((unlocks or {}).get('payload') or {}).get('event_id') or (event or {}).get('id'),
            'event_start': (event or {}).get('start') or '', 'event_title': (event or {}).get('title') or '',
            'event_date': ((unlocks or {}).get('payload') or {}).get('event_date') or ''}
    ask_id = storage.add_ask(data)
    row = storage.get_ask(ask_id)
    d = draft(row, channel) if draft_mode == 'model' else _template(row, channel, asker.get('name') or 'us')
    link = next((c['link'] for c in channels_for(to) if c['channel'] == channel), None)
    storage.update_ask(ask_id, {'draft_subject': d['subject'], 'draft_body': d['body'],
                                'draft_source': d['source'], 'link': link})
    if channel == 'chauffeur':
        _post(ask_id)
    _touch(kind, sid)
    return {'status': 'success', 'ask': storage.get_ask(ask_id)}


def _touch(kind, sid):
    if kind and sid:
        from services import situations as _sit
        _sit.touched(kind, sid)


def _card(ask: dict) -> dict:
    actions = [] if ask.get('state') in ('yes', 'no', 'withdrawn', 'expired') else [
        {'label': 'Yes', 'style': 'primary', 'ask_id': ask['id'], 'act': 'yes'},
        {'label': 'No', 'style': 'default', 'ask_id': ask['id'], 'act': 'no'}]
    return {'kind': 'ask', 'ask_id': ask['id'], 'what': ask.get('what'), 'state': ask.get('state'),
            'outcome': ask.get('outcome'), 'actions': actions}


def _post(ask_id: str) -> None:
    from services.agent_tools_v2 import _post_chat_message
    ask = storage.get_ask(ask_id)
    asker = storage.get_member(ask['asked_by']) or {}
    dm = storage.get_or_create_dm(ask['asked_by'], ask['to_member_id'])
    msg = _post_chat_message(dm, asker, ask.get('draft_body') or ask['what'], card=_card(ask))
    storage.update_ask(ask_id, {'state': 'sent', 'sent_at': time.time(),
                                'message_id': (msg or {}).get('id'), 'channel_id': dm.get('id')})


def _refresh_card(ask: dict) -> None:
    """The DM's Yes/No buttons follow the ledger, not the moment they were drawn."""
    if ask.get('message_id'):
        storage.update_chat_message_card(ask['message_id'], _card(ask))


def mark_sent(ask_id: str, actor: dict) -> dict:
    ask = storage.get_ask(ask_id)
    if not ask:
        return {'status': 'error', 'message': 'That ask is no longer here.'}
    if not (_can_write(actor) or (actor or {}).get('id') == ask.get('asked_by')):
        return {'status': 'refused', 'message': 'Only a parent or adult can do that.'}
    if ask['state'] != 'drafted':
        return {'status': 'success', 'message': 'Already noted.', 'ask': ask}
    storage.update_ask(ask_id, {'state': 'sent', 'sent_at': time.time()})
    _touch(ask.get('situation_kind'), ask.get('situation_id'))
    return {'status': 'success', 'message': f"Noted: asked {ask['to_name']}.", 'ask': storage.get_ask(ask_id)}


def withdraw(ask_id: str, actor: dict) -> dict:
    ask = storage.get_ask(ask_id)
    if not ask:
        return {'status': 'error', 'message': 'That ask is no longer here.'}
    if not _can_write(actor):
        return {'status': 'refused', 'message': 'Only a parent or adult can do that.'}
    if ask['state'] in ('yes', 'no'):
        return {'status': 'refused', 'message': 'That ask was already answered.'}
    storage.update_ask(ask_id, {'state': 'withdrawn', 'answered_at': time.time()})
    _refresh_card(storage.get_ask(ask_id))
    _touch(ask.get('situation_kind'), ask.get('situation_id'))
    return {'status': 'success', 'message': 'Withdrawn.'}


def answer(ask_id: str, answer: str, actor: dict, reported: bool = False) -> dict:
    """Three gates: the recipient answers their own ask (any role); the asker
    or a parent/adult REPORTS somebody else's answer. Answering never applies
    anything by itself; applying runs under the asker (see apply)."""
    ask = storage.get_ask(ask_id)
    if not ask:
        return {'status': 'error', 'message': 'That ask is no longer here.'}
    if answer not in ('yes', 'no'):
        return {'status': 'error', 'message': "Yes or no."}
    actor_id = (actor or {}).get('id')
    if reported:
        allowed = _can_write(actor) or actor_id == ask.get('asked_by')
    else:
        allowed = bool(actor_id) and actor_id == ask.get('to_member_id')
    if not allowed:
        return {'status': 'refused', 'message': "That ask isn't yours to answer."}
    with storage.db_lock:
        ask = storage.get_ask(ask_id)
        if ask['state'] in ('withdrawn', 'expired'):
            return {'status': 'refused', 'message': f"That ask was {ask['state']}."}
        if ask['state'] == 'no':
            return {'status': 'success', 'message': 'Already answered no.', 'already': True}
        if ask['state'] == 'yes' and answer == 'no':
            return {'status': 'refused', 'message': f"{ask['to_name']} already said yes."}
        if ask['state'] == 'yes' and ask.get('outcome') not in (None, 'claimed'):
            return {'status': 'success', 'outcome': ask['outcome'], 'already': True,
                    'message': _outcome_message(ask)}
        if answer == 'no':
            storage.update_ask(ask_id, {'state': 'no', 'answered_at': time.time(), 'answered_by': actor_id})
        elif ask['state'] != 'yes':
            storage.update_ask(ask_id, {'state': 'yes', 'answered_at': time.time(), 'answered_by': actor_id})
    if answer == 'no':
        _refresh_card(storage.get_ask(ask_id))
        _touch(ask.get('situation_kind'), ask.get('situation_id'))
        return {'status': 'success', 'message': f"OK, {ask['to_name']} can't. Back to the options."}
    res = apply(ask_id)
    _refresh_card(storage.get_ask(ask_id))
    _touch(ask.get('situation_kind'), ask.get('situation_id'))
    return {'status': 'success', **res}


def _outcome_message(ask: dict) -> str:
    o = ask.get('outcome')
    if o == 'applied':
        return f"✓ {ask.get('to_name')} has it."
    if o == 'superseded':
        return (f"{ask.get('to_name')} also said yes; {ask.get('superseded_by_name') or 'someone'} "
                f"already has it. Let them know.")
    if o == 'stale':
        return f"{ask.get('to_name')} said yes, but the time moved. Confirm with them."
    if o == 'failed':
        return f"{ask.get('to_name')} said yes; finish by hand: {ask.get('what')}."
    if o == 'manual':
        return f"{ask.get('to_name')} said yes; apply by hand: {ask.get('what')}."
    if o == 'claimed':
        return 'Still applying that; one moment.'
    return ''


def _siblings(ask: dict) -> list:
    same = []
    if ask.get('situation_id'):
        same = list(storage.get_asks(situation_kind=ask.get('situation_kind'),
                                     situation_id=ask.get('situation_id')))
    if ask.get('event_id'):
        ids = {a['id'] for a in same}
        same += [a for a in storage.get_asks(event_id=ask['event_id']) if a['id'] not in ids]
    # The same need is the same occurrence: a recurring event keeps its id
    # week to week, so last week's covered ride is not this week's sibling.
    fp = (ask.get('unlocks') or {}).get('fingerprint')
    if fp:
        same = [a for a in same if (a.get('unlocks') or {}).get('fingerprint') in (None, fp)]
    return [a for a in same if a['id'] != ask['id']]


def apply(ask_id: str) -> dict:
    """Claim under the lock, run the effect outside it, record the outcome.
    Idempotent: an ask already applied returns its outcome; a claim is taken
    only when no sibling on the same need holds one."""
    with storage.db_lock:
        ask = storage.get_ask(ask_id)
        if not ask or ask.get('state') != 'yes':
            return {'outcome': None, 'message': 'Not a yes.'}
        if ask.get('outcome') in FINAL_OUTCOMES:
            return {'outcome': ask['outcome'], 'already': True, 'message': _outcome_message(ask)}
        if ask.get('outcome') == 'claimed' and time.time() - float(ask.get('claim_ts') or 0) < CLAIM_STALE_S:
            # Somebody is applying this right now (a duplicate tap, or a tap
            # racing the sweep). Nothing runs twice.
            return {'outcome': 'claimed', 'message': 'Still applying that; one moment.'}
        unlocks = ask.get('unlocks') or {}
        if not unlocks:
            # A yes with nothing the app can do about it: recorded, never
            # pretended applied. The person finishes by hand.
            storage.update_ask(ask_id, {'outcome': 'manual', 'applied_at': time.time()})
            return {'outcome': 'manual', 'message': _outcome_message(storage.get_ask(ask_id))}
        if unlocks.get('fingerprint') and unlocks.get('action_type') == 'assist_assignment':
            now_fp = fingerprint_for_event((unlocks.get('payload') or {}).get('event_id'))
            if now_fp != unlocks['fingerprint']:
                storage.update_ask(ask_id, {'outcome': 'stale', 'applied_at': time.time()})
                return {'outcome': 'stale', 'message': _outcome_message(storage.get_ask(ask_id))}
        winner = next((s for s in _siblings(ask)
                       if s.get('state') == 'yes' and s.get('outcome') in ('claimed', 'applied')), None)
        if winner:
            storage.update_ask(ask_id, {'outcome': 'superseded', 'applied_at': time.time(),
                                        'superseded_by': winner['id'], 'superseded_by_name': winner.get('to_name')})
            return {'outcome': 'superseded', 'message': _outcome_message(storage.get_ask(ask_id))}
        storage.update_ask(ask_id, {'outcome': 'claimed', 'claim_ts': time.time()})
    try:
        _effect(storage.get_ask(ask_id))
    except Exception as e:
        logger.warning(f"[asks] effect failed for {ask_id}: {e}")
        storage.update_ask(ask_id, {'outcome': 'failed', 'unlock_error': str(e)[:300], 'applied_at': time.time()})
        return {'outcome': 'failed', 'message': _outcome_message(storage.get_ask(ask_id))}
    storage.update_ask(ask_id, {'outcome': 'applied', 'applied_at': time.time(), 'unlock_error': None})
    return {'outcome': 'applied', 'message': _outcome_message(storage.get_ask(ask_id)), 'schedule_dirty': True}


def _effect(ask: dict) -> None:
    """The promised work, keyed by the ask id so running it twice is one effect."""
    u = ask.get('unlocks') or {}
    p = dict(u.get('payload') or {})
    kind = u.get('action_type')
    asker_id = ask.get('asked_by')
    if kind == 'assist_assignment':
        contact_id = p.get('contact_id') or ask.get('to_contact_id')
        if not contact_id:
            contact_id = f"ask-{ask['id']}"
            if not storage.get_assist_contact(contact_id):
                storage.add_assist_contact({'id': contact_id, 'name': ask.get('to_name') or 'A friend',
                                            'kinds': ['driving'], 'active': True})
            storage.update_ask(ask['id'], {'to_contact_id': contact_id})
        storage.set_assist_assignment(p['event_id'], contact_id, note=f"ask {ask['id']}",
                                      event_date=p.get('event_date') or '', event_title=p.get('event_title') or '',
                                      actor=asker_id)
        return
    if kind == 'reassign_driver':
        from services.agent_tools_v2 import assign_driver_to_event_fuzzy
        res = assign_driver_to_event_fuzzy(p.get('event_name'), p.get('driver_name'), p.get('target_date'))
        if res.get('status') != 'success':
            raise RuntimeError(res.get('message') or 'assign failed')
        return
    if kind == 'approve_proposal':
        from services import chat_actions as _ca
        res = _ca.act_on_proposal(p['proposal_id'], 'approve', storage.get_member(asker_id))
        if res.get('status') != 'success' and 'already approved' not in (res.get('message') or ''):
            raise RuntimeError(res.get('message') or 'approve failed')
        return
    if kind == 'thread_advance':
        from services import threads as _th
        _th.advance(p['thread_id'], p.get('next_action') or ask.get('what'), next_action_at=p.get('next_action_at'),
                    note=f"{ask.get('to_name')} said yes", who=asker_id)
        return
    raise RuntimeError(f"unknown unlock {kind}")


def recover(now: datetime.datetime = None) -> int:
    """A claim older than CLAIM_STALE_S was interrupted between claim and
    completion. Finish it (the effect is idempotent) or record failed."""
    now_ts = (now or datetime.datetime.now()).timestamp()
    n = 0
    for a in storage.get_asks(state='yes'):
        if a.get('outcome') == 'claimed' and now_ts - float(a.get('claim_ts') or 0) > CLAIM_STALE_S:
            try:
                _effect(a)
                storage.update_ask(a['id'], {'outcome': 'applied', 'applied_at': time.time()})
            except Exception as e:
                storage.update_ask(a['id'], {'outcome': 'failed', 'unlock_error': str(e)[:300],
                                             'applied_at': time.time()})
            _refresh_card(storage.get_ask(a['id']))
            _touch(a.get('situation_kind'), a.get('situation_id'))
            n += 1
        elif a.get('outcome') is None:
            apply(a['id'])
            n += 1
    return n

"""Hold private satellite answers until their speaker chooses a destination."""
from contextvars import ContextVar
import logging
import re
import threading
import time

from services import storage, voice_tools

QUESTION = "That's private. Read it out, or send it to your chat?"
SENT = 'Sent to your chat.'
current = ContextVar('chauffeur_satellite_voice', default=None)
_held = {}
_lock = threading.RLock()
_READ = re.compile(r'\b(?:read|out loud|aloud|tell me|yes|go ahead)\b', re.I)
_SEND = re.compile(r'\b(?:send|chat|phone|no|later)\b', re.I)


class SatelliteTurn:
    def __init__(self, member):
        self.member = member
        self._safe = True
        self._name = None
        self._pending_safe = True

    @property
    def safe(self):
        return self._safe

    def before_tool(self, name, args):
        self._name = name
        self._pending_safe = (name in voice_tools.SPEAKABLE
                              and not (name == 'house' and args.get('action') == 'locate')
                              and voice_tools.row_checks_before(name, args, self.member))

    def tool_result(self, result):
        # A failed read discloses no private result. Unlike the phone, this
        # does not suppress its ordinary error message.
        if not isinstance(result, dict) or result.get('error') \
                or result.get('status') not in ('success', 'ok'):
            return
        if not self._pending_safe or not voice_tools.row_checks_after(self._name, result):
            self._safe = False


def _discard(key):
    entry = _held.pop(key, None)
    if entry and entry.get('timer'):
        entry['timer'].cancel()
    return entry


def _release(key):
    """Caller holds _lock; a failed post leaves the answer available to retry."""
    entry = _held.get(key)
    if not entry:
        return
    from services.agent_tools_v2 import _post_chat_message
    argyle = storage.ensure_argyle_member()
    channel = storage.get_or_create_dm(entry['member_id'], argyle['id'])
    card = entry['card']
    if card and card.get('proposal_id'):
        storage.update_action_proposal(card['proposal_id'], {'channel_id': channel['id']})
    if not _post_chat_message(channel, argyle, entry['reply'], card=card):
        raise RuntimeError('The private voice answer could not be sent to chat.')
    _discard(key)


def release(ctx, reason):
    with _lock:
        _release((ctx.ha_instance_id, ctx.satellite_id))


def expire(ha_instance_id, satellite_id):
    """Deliver once if this satellite still has an answer waiting."""
    with _lock:
        _release((ha_instance_id, satellite_id))


def release_all():
    """Reconfiguring identity ends every session, delivering pending answers."""
    with _lock:
        for key in list(_held):
            _release(key)


def hold(ctx, actor, reply, card):
    key = (ctx.ha_instance_id, ctx.satellite_id)
    with _lock:
        _release(key)
        entry = {'member_id': actor['id'], 'reply': reply, 'card': card,
                 'expires': time.time() + 60, 'reasks': 0}

        def timeout():
            try:
                with _lock:
                    # A cancelled timer already running must not expire a
                    # newer answer from the same satellite.
                    if _held.get(key) is entry:
                        expire(*key)
            except Exception:
                logging.getLogger(__name__).exception('Private voice answer delivery failed')

        timer = threading.Timer(60, timeout)
        timer.daemon = True
        entry['timer'] = timer
        _held[key] = entry
        timer.start()
    return QUESTION


def intercept(text, ctx):
    from services import voice_conversation
    key = (ctx.ha_instance_id, ctx.satellite_id)
    with _lock:
        entry = _held.get(key)
        if not entry:
            return None
        actor = ctx.actor()
        if entry['expires'] <= time.time() or voice_conversation.is_sign_off(text) \
                or not actor or actor['id'] != entry['member_id']:
            _release(key)
            return None
        # Prefer the private destination when a reply includes both choices
        # ("no, don't read it; send it"). Match words, never substrings.
        if _SEND.search(text or ''):
            _release(key)
            return {'message': SENT}
        if _READ.search(text or ''):
            _discard(key)
            return {'message': entry['reply']}
        if not entry['reasks']:
            entry['reasks'] += 1
            return {'message': QUESTION, 'continue': True}
        _release(key)
        return None

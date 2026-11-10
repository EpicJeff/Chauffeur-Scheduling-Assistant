"""Hold private satellite answers until their speaker chooses a destination."""
from contextvars import ContextVar
import logging
import re
import threading
import time

from services import storage, voice_tools

QUESTION = "That's private. Read it out, or send it to your chat?"
SENT = 'Sent to your chat.'
CHAT_NOTICE = " I've put that in your Argyle chat."
current = ContextVar('chauffeur_satellite_voice', default=None)
_held = {}
_lock = threading.RLock()
_READ = re.compile(r'\b(?:read|out loud|aloud|tell me|yes|go ahead)\b', re.I)
_SEND = re.compile(r"\b(?:send|chat|phone|no|later|don['’]t read|do not read|not out loud)\b", re.I)


class SatelliteTurn:
    def __init__(self, member):
        self.member = member
        self._safe = True
        self._name = None
        self._pending_safe = True

    @property
    def safe(self):
        return self._safe

    def before_tool(self, name, args=None):
        args = args or {}
        self._name = name
        # A private call can disclose records even in a refusal or bare result.
        if name not in voice_tools.SPEAKABLE:
            self._safe = False
        self._pending_safe = (name in voice_tools.SPEAKABLE
                              and not (name == 'house' and args.get('action') == 'locate')
                              and voice_tools.row_checks_before(name, args, self.member))

    def tool_result(self, result=None):
        # Speakable errors/refusals (such as a PIN request) remain audible.
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


def post_reply_to_chat(member_id, reply, card):
    """Shared actor reply/card delivery; only a successful post earns a notice."""
    try:
        from services.agent_tools_v2 import _post_chat_message
        argyle = storage.ensure_argyle_member()
        channel = storage.get_or_create_dm(member_id, argyle['id'])
        if card and card.get('proposal_id'):
            storage.update_action_proposal(card['proposal_id'], {'channel_id': channel['id']})
        if not _post_chat_message(channel, argyle, reply, card=card):
            raise RuntimeError('The voice answer could not be sent to chat.')
        return True
    except Exception:
        logging.getLogger(__name__).exception('Voice Argyle reply post failed')
        return False


def _release(key):
    """Caller holds _lock; a failed post leaves the answer available to retry."""
    entry = _held.get(key)
    if not entry:
        return True
    if not post_reply_to_chat(entry['member_id'], entry['reply'], entry['card']):
        return False
    _discard(key)
    return True


def _try_release(key):
    try:
        return _release(key)
    except Exception:
        logging.getLogger(__name__).exception('Private voice answer delivery failed')
        return False


def release(ctx, reason):
    with _lock:
        return _try_release((ctx.ha_instance_id, ctx.satellite_id))


def expire(ha_instance_id, satellite_id):
    """Deliver once if this satellite still has an answer waiting."""
    with _lock:
        return _try_release((ha_instance_id, satellite_id))


def release_all():
    """Reconfiguring identity ends every session, delivering pending answers."""
    with _lock:
        for key in list(_held):
            _try_release(key)


def hold(ctx, actor, reply, card):
    key = (ctx.ha_instance_id, ctx.satellite_id)
    with _lock:
        if not _try_release(key):
            # Do not overwrite an answer whose delivery must still be retried.
            return QUESTION
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
            _try_release(key)
            return None
        # Prefer the private destination when a reply includes both choices
        # ("no, don't read it; send it"). Match words, never substrings.
        if _SEND.search(text or ''):
            if _try_release(key):
                return {'message': SENT}
            return {'message': "I couldn't send that yet. Please try again.", 'continue': True}
        if _READ.search(text or ''):
            reply = entry['reply']
            if entry['card']:
                if _try_release(key):
                    reply = reply.rstrip() + CHAT_NOTICE
            else:
                _discard(key)
            return {'message': reply}
        if not entry['reasks']:
            entry['reasks'] += 1
            return {'message': QUESTION, 'continue': True}
        _try_release(key)
        return None

"""Listening policy for ordinary satellite replies; identity prompts own theirs."""
import re
import threading
import time
import unicodedata

from services import storage

CAP = 2
GAP_SECONDS = 30
SIGN_OFFS = frozenset({
    'thanks', 'thank you', "that's all", 'that is all', 'goodbye', 'bye',
    'never mind', 'nevermind', 'stop', 'cancel',
})
_lock = threading.Lock()
_turns = {}


def _trim(text):
    def edge(char):
        return char.isspace() or unicodedata.category(char).startswith('P')
    while text and edge(text[0]):
        text = text[1:]
    while text and edge(text[-1]):
        text = text[:-1]
    return text


def is_sign_off(text):
    phrase = _trim(text.lower().replace('\u2019', "'"))
    phrase = _trim(re.sub(r'\bargyle$', '', phrase))
    return phrase in SIGN_OFFS


def continue_conversation(ctx, text):
    """Count once, inside voice_identity.once, after an ordinary model answer."""
    if not ctx.satellite_id:
        return False
    key = (ctx.ha_instance_id, ctx.satellite_id)
    enabled = storage.get_settings().get('voice_conversation_mode', True) is not False
    now = time.monotonic()
    with _lock:
        # Expired satellites need neither a count nor a permanent memory row.
        for old, (_, last) in list(_turns.items()):
            if now - last > GAP_SECONDS:
                _turns.pop(old, None)
        if not enabled or is_sign_off(text):
            _turns.pop(key, None)
            return False
        count = 0 if ctx.recognized_this_turn else _turns.get(key, (0, now))[0] + 1
        if count >= CAP:
            _turns.pop(key, None)
            return False
        _turns[key] = (count, now)
        return True

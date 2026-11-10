"""Satellite conversation state and listening policy for ordinary replies."""
import re
import threading
import time
import unicodedata

from services import storage

CAP = 2
GAP_SECONDS = 30
SIGN_OFFS = frozenset({
    'thanks', 'thank you', 'thanks so much', 'thank you so much', 'thanks a lot',
    'no thanks', 'no thank you', "that's all", 'that is all', "that's it",
    "that'll be all", 'that will be all', "i'm done", 'i am done', "we're done",
    'we are done', 'all done', 'nothing else', 'goodbye', 'bye', 'bye bye',
    'good night', 'goodnight', 'never mind', 'nevermind', 'stop', 'cancel',
    'stop listening', 'you can stop listening', 'you can stop', 'i need you to stop',
    "don't listen", 'go to sleep', 'go away', 'be quiet', "that's enough",
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
    text = text.lower().replace('\u2018', "'").replace('\u2019', "'")
    found = False
    for part in re.split(r'[.!?;,]', text):
        phrase = _trim(part)
        # Check exact closings first, including "no thanks" / "no thank you".
        while phrase and phrase not in SIGN_OFFS:
            stripped = re.sub(
                r'^(?:no|ok|okay|alright|all right|well|so|yes|yeah|hey argyle|argyle)(?:\s+|$)',
                '', phrase)
            stripped = re.sub(
                r'(?:^|\s+)(?:for now|now|here|please|argyle|anymore|then)$', '', stripped)
            stripped = _trim(stripped)
            if stripped == phrase:
                return False
            phrase = stripped
        if phrase:
            found = True
    return found


def in_conversation(ctx) -> bool:
    """Read whether this satellite's previous turn left the mic open recently."""
    if not ctx.satellite_id:
        return False
    key = (ctx.ha_instance_id, ctx.satellite_id)
    with _lock:
        previous = _turns.get(key)
        return previous is not None and time.monotonic() - previous[1] < GAP_SECONDS


def close(ctx):
    """Record a closed mic, including answers handled before the model."""
    with _lock:
        _turns.pop((ctx.ha_instance_id, ctx.satellite_id), None)


def touch(ctx):
    """Record an open mic without spending or resetting its ordinary-turn cap."""
    if not ctx.satellite_id:
        return
    key = (ctx.ha_instance_id, ctx.satellite_id)
    now = time.monotonic()
    with _lock:
        count = _turns.get(key, (0, now))[0]
        _turns[key] = (count, now)


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

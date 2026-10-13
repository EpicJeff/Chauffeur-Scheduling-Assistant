"""Personal phone turns: typed authority, conservative audible output, no biometrics."""
from contextvars import ContextVar
from dataclasses import dataclass, field
import re
import threading
import time

from services import storage

current = ContextVar('chauffeur_phone_voice', default=None)
_lock = threading.RLock()
_turns = {}
DISPLAY_ONLY = 'I put that on your screen.'


class Stopped(Exception):
    pass


def personal(headers):
    from tinydb import Query
    from services import scope
    token = headers.get('x-member-token', '')
    member = storage.get_member_by_token(token)
    row = storage.member_tokens_table.get(Query().token == token) if token else None
    if not member or member.get('system') or not row or row.get('house_session'):
        raise PermissionError('Sign in on your personal device to talk to Argyle.')
    if not scope.can_see(member, 'chat.agent'):
        raise PermissionError('Argyle chat is not available to this account.')
    return member, token


def _credential(text):
    from services.voice_identity import normalize_pin
    digits = normalize_pin(text)
    return bool(digits and 4 <= len(digits) <= 8) or bool(
        re.search(r"\b(?:my\s+)?(?:pin|password|passcode)\s+(?:is|=)|\b(?:my\s+)?pin\b", text, re.I))


@dataclass
class Turn:
    id: str
    member: dict
    token: str = field(repr=False)
    channel: dict
    expires: float = field(default_factory=lambda: time.monotonic() + 600)
    stopped: bool = False
    stage: str = 'capture'
    transcript: str = ''
    credential: bool = False
    speech_safe: bool = True
    tools: list = field(default_factory=list)
    response: dict | None = None
    deadline: float = 0
    had_safe_history: bool = False

    def check(self):
        from services import scope
        member = storage.get_member_by_token(self.token)
        if self.stopped or self.expires <= time.monotonic() or not member \
                or member.get('id') != self.member['id'] or member.get('role') != self.member.get('role') \
                or not scope.can_see(member, 'chat.agent'):
            raise Stopped('This voice turn ended. Tap to start again.')
        channel = storage.get_channel(self.channel['id'])
        if not channel or channel.get('archived') or set(channel.get('member_ids', [])) != {self.member['id'], 'argyle'}:
            raise Stopped('This conversation is no longer available.')

    def remaining(self):
        self.check()
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise Stopped('The voice response took too long. Try again or use text.')
        return remaining

    def before_tool(self, name, args):
        self.check()  # immediately before dispatch; not only before the model call
        from services.voice_tools import TOOLS, speech_safe
        self.tools.append(name)
        if name not in TOOLS or name == 'prepare_voice_approval':
            self.speech_safe = False
        elif name in ('assign_driver_to_event_fuzzy', 'remove_override_for_event_fuzzy'):
            from services.agent_tools_v2 import _find_event_fuzzy
            row, error = _find_event_fuzzy(args.get('event_name') or '', args.get('target_date') or 'today')
            if error or not row or not speech_safe(row):
                self.speech_safe = False
        elif name in ('get_shopping_list_items', 'add_shopping_items', 'check_off_shopping_item'):
            from services.agent_tools_v2 import _resolve_shopping_list
            from services import scope
            row, error = _resolve_shopping_list(args.get('list_name') or '', self.member)
            if error or not row or not scope.audience_allows(row, 'shopping_list', None) \
                    or row.get('private') or row.get('sensitivity') == 'sensitive':
                self.speech_safe = False
        elif name == 'start_mission_for':
            self.speech_safe = False  # goal/focus/mission results can contain private details

    def tool_result(self, result):
        if not isinstance(result, dict) or result.get('error') or result.get('status') not in ('success', 'ok'):
            self.speech_safe = False
        if self.tools and self.tools[-1] == 'get_calendar_events' and isinstance(result, dict):
            from services.voice_tools import speech_safe
            # Slim typed rows omit privacy flags; inspect their original sources.
            sources = {r.get('id'): r for r in (storage.get_cached_schedule() or {}).get('events', [])}
            for row in result.get('events', []):
                source = sources.get(row.get('id'))
                if not source or not speech_safe(source):
                    self.speech_safe = False

    def audible(self, result):
        return self.speech_safe and (bool(self.tools) or self.had_safe_history) \
            and not result.get('error') and result.get('status') == 'success'

    def text(self, text):
        self.check()
        with _lock:
            if self.stage != 'capture':
                raise ValueError('This voice turn already has a transcript.')
            if not isinstance(text, str) or not text.strip() or len(text) > 4000:
                raise ValueError('No usable speech was recognized. Try again.')
            self.credential = _credential(text)
            self.transcript = '[Credential withheld]' if self.credential else text.strip()
            self.stage = 'ready'
        return {'transcript': self.transcript, 'credential': self.credential}


def begin(member, token, request_id, channel_id=None):
    if not isinstance(request_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,80}', request_id):
        raise ValueError('A new voice request ID is required.')
    storage.ensure_argyle_member()
    channel = storage.get_channel(channel_id) if channel_id else storage.get_or_create_dm(member['id'], 'argyle')
    if not channel or channel.get('kind') != 'dm' or channel.get('archived') \
            or set(channel.get('member_ids', [])) != {member['id'], 'argyle'}:
        raise PermissionError('Use your own conversation with Argyle.')
    from tinydb import Query
    with _lock, storage.db_lock:
        for key, row in list(_turns.items()):
            if row.expires <= time.monotonic():
                del _turns[key]
        key = (member['id'], request_id)
        if key in _turns or storage.chat_messages_table.get((Query().channel_id == channel['id']) &
                (Query().phone_request_id == request_id)):
            raise ValueError('This request was already accepted. Start a new turn.')
        if len(_turns) >= 256:
            raise ValueError('Voice is busy. Try again shortly.')
        for row in _turns.values():
            if row.member['id'] == member['id'] and row.channel['id'] == channel['id']:
                row.stopped = True
        turn = Turn(request_id, member, token, channel)
        _turns[key] = turn
    return turn


def get(member, token, request_id, *, active=True):
    with _lock:
        turn = _turns.get((member['id'], request_id))
    if not turn or turn.token != token:
        raise PermissionError('This voice turn belongs to another session or has ended.')
    if active:
        turn.check()
    return turn


def run(turn, worker):
    from services.agent_tools_v2 import _post_chat_message
    from services import triage
    with _lock, storage.db_lock:
        turn.check()
        if turn.stage != 'ready':
            raise ValueError('This voice request has already run or has no transcript.')
        turn.stage = 'running'
        turn.deadline = time.monotonic() + 6
        history = [m for m in storage.get_channel_messages(turn.channel['id'], limit=5)
                   if m.get('phone_speech_safe') is True and not m.get('edited_ts')]
        # Typed Argyle DMs currently inject focus, not message history. Phone
        # follow-ups add shared voice history only, without importing private
        # displayed answers or making every later turn permanently inaudible.
        turn.speech_safe = not turn.credential and not triage.get_focus('channel:' + turn.channel['id'])
        turn.had_safe_history = bool(history) and turn.speech_safe
        if not turn.credential:
            _post_chat_message(turn.channel, turn.member, turn.transcript,
                               phone_request_id=turn.id, phone_speech_safe=False)
    if turn.credential:
        result = {'message': 'Use the PIN control on your screen. Your spoken credential was withheld.'}
        _post_chat_message(turn.channel, storage.ensure_argyle_member(), result['message'])
    else:
        token = current.set(turn)
        try:
            result = worker(turn.channel, turn.member, turn.transcript) or {}
        finally:
            current.reset(token)
    reply = result.get('message') or 'I could not finish that request. Try again or use text.'
    eligible = turn.audible(result)
    if not turn.credential:
        from tinydb import Query
        with storage.db_lock:
            storage.chat_messages_table.update({'phone_speech_safe': eligible},
                (Query().channel_id == turn.channel['id']) & (Query().phone_request_id == turn.id))
    speech = reply[:1200] if eligible else DISPLAY_ONLY
    if turn.credential:
        speech = 'Use the PIN control on your screen.'
    turn.response = {'reply': reply, 'speech': speech, 'speech_safe': eligible,
                     'continue_conversation': bool(not turn.credential and reply.rstrip().endswith('?')),
                     'channel_id': turn.channel['id'], 'request_id': turn.id}
    turn.stage = 'complete'
    return turn.response

"""Satellite identity before conversation storage or model dispatch.

The service credential authenticates a place. Only the PIN verifies a member.
No member/browser token or approval authority is minted by this module.
"""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import dataclass
import hashlib
import hmac
import math
import re
import threading
import time
import uuid

from services import storage

SESSION_SECONDS = 600
DELIVERY_SECONDS = 60
_lock = threading.RLock()
_sessions = {}
_observed = {}
_requests = OrderedDict()


def _revision() -> str:
    token = str((storage.get_settings() or {}).get('service_token') or '')
    return hashlib.sha256(token.encode()).hexdigest() if token else ''


def service_authenticated(headers) -> bool:
    expected = str((storage.get_settings() or {}).get('service_token') or '')
    supplied = str(headers.get('x-service-token') or '')
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


def configuration() -> dict:
    return storage.get_app_state('voice_identity_config') or {'enabled': False, 'satellites': []}


def configure(enabled: bool, satellites: list, approvals_enabled: bool = False) -> None:
    """Parent endpoint owns this call; supplied rows cannot assert an identity."""
    if not isinstance(satellites, list) or len(satellites) > 128:
        raise ValueError('Invalid satellite list.')
    rows = []
    for item in satellites:
        installation = str(item.get('ha_instance_id') or '').strip()
        satellite = str(item.get('satellite_id') or '').strip()
        if not installation or not satellite or max(len(installation), len(satellite)) > 128:
            raise ValueError('Choose an observed satellite with its HA installation.')
        recognition = item.get('recognition_enabled') is True
        if recognition:
            from services import voice_fingerprint
            if not any(voice_fingerprint.usable_on(p, (installation, satellite))
                       for p in voice_fingerprint.profiles()):
                raise ValueError('Set up a voice before enabling recognition.')
        # The speaker Argyle answers through on this satellite (2026-10-30), a
        # media player or nothing; a satellite or any other entity is not one.
        speaker = str(item.get('answer_speaker') or '').strip()
        rows.append({'ha_instance_id': installation, 'satellite_id': satellite,
                     'device_id': item.get('device_id') or None,
                     'label': str(item.get('label') or satellite.split('.')[-1].replace('_', ' ').title())[:100],
                     'enabled': bool(item.get('enabled')), 'service_revision': _revision(),
                     'recognition_enabled': recognition,
                     'answer_speaker': speaker if speaker.startswith('media_player.') and len(speaker) <= 128 else ''})
    if enabled and not _revision():
        raise ValueError('Set an Argyle service token before enabling voice identity.')
    with _lock:
        storage.set_app_state('voice_identity_config', {'enabled': bool(enabled), 'satellites': rows,
                                                      'approvals_enabled': bool(approvals_enabled) and bool(enabled)})
        _sessions.clear()


def _active(member) -> bool:
    return bool(member and not member.get('system') and storage.member_has_access(member))


@dataclass(frozen=True)
class VoiceContext:
    ha_instance_id: str
    satellite_id: str
    request_id: str
    generation: str
    level: str = 'unknown'
    member_id: str | None = None
    expires_at: float = 0
    service_revision: str = ''
    paired: bool = False
    fingerprint: list | None = None
    greeting: str | None = None

    @property
    def scope_key(self):
        return hashlib.sha256(f'{self.ha_instance_id}:{self.satellite_id}:{self.generation}'.encode()).hexdigest()

    def member(self):
        """Revalidate before each tool; a concurrent revoke never grants authority."""
        with _lock:
            row = _sessions.get((self.ha_instance_id, self.satellite_id))
            if not row or row['generation'] != self.generation or row['expires_at'] <= time.time():
                return None
            if not _paired(self.ha_instance_id, self.satellite_id, row.get('device_id')):
                return None
            member = storage.get_member(self.member_id) if self.member_id else None
            if not _active(member) or row.get('role') != member.get('role'):
                return None
            if row.get('pin_revision') and row['pin_revision'] != member.get('pin_hash'):
                return None
            return member

    def verified_member(self):
        return self.member() if self.level == 'verified' else None

    def provenance(self):
        member = self.verified_member()
        return {'actor_kind': 'member' if member else 'household_voice',
                'actor_member_id': member['id'] if member else None,
                'ha_instance_id': self.ha_instance_id, 'satellite_id': self.satellite_id,
                'request_id': self.request_id}


def _adopt(installation, satellite, device, label):
    """A satellite this installation speaks through for the FIRST time, while
    identity is on, joins enabled, with recognition set the way the household
    has it. Device 2026-10-29: a second Voice PE answered 'set up my voice' with
    'I can't do that' because every identity door hangs on a Config row ticked
    by hand for that one satellite, and the user's standing call (2026-10-13)
    is one setup, every speaker. A row a parent unticked is never touched: the
    Config checkbox stays the per-speaker off switch. Only trusted metadata
    reaches here (context() checked the service token and the clock), so a row
    is written only for a satellite the household's own HA just spoke through."""
    config = configuration()
    if not config.get('enabled') or not _revision():
        return
    rows = list(config.get('satellites', []))
    if any(r.get('ha_instance_id') == installation and r.get('satellite_id') == satellite for r in rows):
        return
    everywhere = recognition_on_everywhere()
    rows.append({'ha_instance_id': installation, 'satellite_id': satellite, 'device_id': device,
                 'label': label, 'enabled': True, 'service_revision': _revision(),
                 'recognition_enabled': everywhere, 'answer_speaker': ''})
    storage.set_app_state('voice_identity_config', {**config, 'satellites': rows})


def _paired(installation, satellite, device):
    config = configuration()
    return bool(config.get('enabled') and any(
        r.get('enabled') and r.get('ha_instance_id') == installation
        and r.get('satellite_id') == satellite and r.get('service_revision') == _revision()
        and (not r.get('device_id') or r['device_id'] == device)
        for r in config.get('satellites', [])))


def _new_session(device=None):
    return {'generation': uuid.uuid4().hex, 'level': 'unknown', 'member_id': None,
            'expires_at': time.time() + SESSION_SECONDS, 'device_id': device,
            'role': None, 'pin_revision': None, 'pin_pending': False, 'name_pending': False}


def voice_names(member):
    aliases = member.get('voice_aliases') or []
    if isinstance(aliases, str):
        aliases = [aliases]
    return {' '.join(str(name).split()).casefold() for name in [member.get('name', ''), *aliases]}


def context(metadata, authenticated: bool) -> VoiceContext:
    """Missing/untrusted metadata never reuses another room's conversation."""
    metadata = metadata if isinstance(metadata, dict) else {}
    installation = metadata.get('ha_instance_id') or ''
    satellite = metadata.get('satellite_id') or ''
    device = metadata.get('device_id') or None
    request = metadata.get('request_id') or ''
    try:
        observed = float(metadata.get('observed_at', 0))
    except (TypeError, ValueError):
        observed = 0
    valid = authenticated and all(isinstance(v, str) and 0 < len(v) <= 128
                                  for v in (installation, satellite, request)) and math.isfinite(observed) \
        and abs(time.time() - observed) <= DELIVERY_SECONDS
    if not valid:
        nonce = uuid.uuid4().hex
        return VoiceContext('', '', nonce, nonce)
    with _lock:
        key = (installation, satellite)
        _observed[key] = {'ha_instance_id': installation, 'satellite_id': satellite,
                          'device_id': device, 'last_seen': time.time(),
                          'label': str(metadata.get('label') or satellite.split('.')[-1].replace('_', ' ').title())[:100]}
        bridge = metadata.get('fingerprint_bridge')
        if isinstance(bridge, dict) and isinstance(bridge.get('available'), bool):
            _observed[key]['fingerprint_bridge'] = {
                'available': bridge['available'], 'reason': str(bridge.get('reason', ''))[:200],
                'version': str(bridge.get('version', ''))[:30]}
        if len(_observed) > 256:
            _observed.pop(next(iter(_observed)))
        _adopt(installation, satellite, device, _observed[key]['label'])
        paired = _paired(installation, satellite, device)
        row = _sessions.get(key)
        if not row or row['expires_at'] <= time.time() or row.get('device_id') != device \
                or (not paired and row['level'] != 'unknown'):
            row = _new_session(device)
            _sessions[key] = row
        if len(_sessions) > 256:
            oldest = min(_sessions, key=lambda k: _sessions[k]['expires_at'])
            if oldest != key:
                _sessions.pop(oldest, None)
        if row.get('member_id'):
            member = storage.get_member(row['member_id'])
            if not _active(member) or member.get('role') != row.get('role') \
                    or (row.get('pin_revision') and member.get('pin_hash') != row['pin_revision']):
                row = _new_session(device)
                _sessions[key] = row
        return VoiceContext(installation, satellite, request, row['generation'],
                            row['level'], row['member_id'], row['expires_at'], _revision(), paired)


_DIGITS = dict(zip('zero one two three four five six seven eight nine'.split(), range(10)))
_DIGITS['oh'] = 0
_SMALL = {**_DIGITS, **dict(zip('ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split(), range(10, 20)))}
_TENS = dict(zip('twenty thirty forty fifty sixty seventy eighty ninety'.split(), range(20, 100, 10)))


def normalize_pin(text: str) -> str | None:
    """A strict English numeric grammar; do not try alternate credential guesses."""
    words = re.findall(r'[a-z]+|[0-9]+', (text or '').lower())
    if not words or re.search(r'[^a-z0-9\s,.-]|\d\.\d', (text or '').lower()):
        return None
    if all(w in _DIGITS or w.isdecimal() for w in words):
        return ''.join(str(_DIGITS[w]) if w in _DIGITS else w for w in words)

    def under_hundred(ws):
        if len(ws) == 1 and ws[0] in _SMALL:
            return _SMALL[ws[0]]
        if ws and ws[0] in _TENS and (len(ws) == 1 or len(ws) == 2 and ws[1] in _DIGITS and _DIGITS[ws[1]]):
            return _TENS[ws[0]] + (_DIGITS[ws[1]] if len(ws) == 2 else 0)
        return None

    def under_thousand(ws):
        if 'hundred' not in ws:
            return under_hundred(ws)
        if len(ws) < 2 or ws[0] not in _DIGITS or not _DIGITS[ws[0]] or ws[1] != 'hundred':
            return None
        tail = ws[2:]
        if tail and tail[0] == 'and':
            tail = tail[1:]
            if not tail:
                return None
        rest = under_hundred(tail) if tail else 0
        return _DIGITS[ws[0]] * 100 + rest if rest is not None else None

    if 'hundred' in words or 'thousand' in words:
        if words.count('thousand') > 1:
            return None
        if 'thousand' in words:
            index = words.index('thousand')
            head = under_thousand(words[:index])
            tail = words[index + 1:]
            if tail and tail[0] == 'and':
                tail = tail[1:]
                if not tail:
                    return None
            rest = under_thousand(tail) if tail else 0
            value = head * 1000 + rest if head and rest is not None else None
        else:
            value = under_thousand(words)
        return str(value) if value is not None else None
    chunks = []
    while words:
        size = 2 if words[0] in _TENS and len(words) > 1 and words[1] in _DIGITS and _DIGITS[words[1]] else 1
        value = under_hundred(words[:size])
        if value is None:
            return None
        chunks.append(str(value))
        words = words[size:]
    return ''.join(chunks)


def _lock_keys(ctx, member_id=None):
    keys = [f'voice:satellite:{ctx.ha_instance_id}:{ctx.satellite_id}']
    if member_id:
        keys.append(f'voice:member:{member_id}')
    return keys


def _locked(ctx, member_id=None):
    return any((storage.get_app_state(k) or {}).get('locked') for k in _lock_keys(ctx, member_id))


def _record(ctx, member_id, ok):
    with storage.db_lock, storage.db.transaction():
        for key in _lock_keys(ctx, member_id):
            row = storage.get_app_state(key) or {'fails': 0, 'locked': False}
            if row.get('locked'):
                continue
            row['fails'] = 0 if ok else row.get('fails', 0) + 1
            row['locked'] = row['fails'] >= 3
            storage.set_app_state(key, row)
        _audit(ctx.ha_instance_id, ctx.satellite_id, member_id,
               'verified' if ok else 'locked' if _locked(ctx, member_id) else 'wrong_pin')


def _audit(installation, satellite, member_id, outcome, by_member=None):
    """Bounded audit contains identity/outcome only, never audio or a PIN."""
    rows = storage.get_app_state('voice_auth_history') or []
    rows.append({'at': time.time(), 'ha_instance_id': installation, 'satellite_id': satellite,
                 'member_id': member_id, 'outcome': outcome, 'by_member': by_member})
    storage.set_app_state('voice_auth_history', rows[-100:])


def parents_named(name):
    want = ' '.join((name or '').split()).casefold()
    parents = [m for m in storage.get_all_members() if _active(m) and m.get('role') == 'parent']
    if not want:
        return parents
    return [m for m in parents if want in voice_names(m)]


def verify_parent_consent(ctx, parent_id, text, language='en'):
    """A parent's PIN spoken (or typed) to consent to a child's enrollment.
    Verifies THAT parent's record with that parent's limits; creates no
    session, anchor or readback. The credential turn is consumed here."""
    parent = storage.get_member(parent_id)
    if not _active(parent) or parent.get('role') != 'parent':
        return {'ok': False, 'message': 'Only a parent can give consent for voice setup.'}
    if not parent.get('pin_hash'):
        return {'ok': False, 'message': f"{parent.get('name')} has no PIN yet. Set one on your phone first."}
    if _locked(ctx, parent['id']) or storage.rate_locked(f"member:{parent['id']}"):
        return {'ok': False, 'message': 'Voice verification is locked for that parent. Clear the voice lock on your phone.'}
    request_key = f'voice:format:{ctx.ha_instance_id}:{ctx.satellite_id}'
    if storage.rate_locked(request_key):
        return {'ok': False, 'message': 'Too many attempts. Try again in a moment.'}
    storage.rate_record(request_key, False)
    match = re.search(r'(?i)\b(?:my\s+)?pin\s+is\b\s*(.*)$', text or '')
    pin = normalize_pin(match.group(1) if match else (text or '')) if language.startswith('en') else None
    if pin is None or not 4 <= len(pin) <= 8 or parent.get('pin_length') and len(pin) != parent['pin_length']:
        return {'ok': False, 'message': 'Say the PIN one digit at a time.'}
    ok = storage.verify_member_pin(parent['id'], pin)
    _record(ctx, parent['id'], ok)
    storage.rate_record(f"member:{parent['id']}", ok)
    if ok:
        storage.rate_clear(request_key)
        _audit(ctx.ha_instance_id, ctx.satellite_id, parent['id'], 'consent')
        return {'ok': True, 'message': 'Thanks.'}
    return {'ok': False, 'message': 'That PIN did not match.' if not _locked(ctx, parent['id'])
            else 'Voice verification is locked for that parent.'}


def set_recognition(installation, satellite, on):
    """One speaker's recognition switch, a parent's act: the hand path in
    Config for turning a single speaker off (or on) by itself."""
    config = configuration()
    rows = list(config.get('satellites', []))
    row = next((r for r in rows if r['ha_instance_id'] == installation and r['satellite_id'] == satellite), None)
    if not row:
        raise ValueError('That satellite is not set up for voice identity.')
    if on:
        from services import voice_fingerprint
        if not any(voice_fingerprint.usable_on(p, (installation, satellite)) for p in voice_fingerprint.profiles()):
            raise ValueError('Set up a voice before enabling recognition.')
    row['recognition_enabled'] = bool(on)
    with _lock:
        storage.set_app_state('voice_identity_config', {**config, 'satellites': rows})
    return row


def set_recognition_everywhere(on):
    """The household switch, a parent's act once (the user's call on device
    evidence, 2026-10-13: one setup, every speaker). Covers every enabled
    satellite; a single speaker can still be switched off by hand."""
    config = configuration()
    rows = list(config.get('satellites', []))
    if on:
        from services import voice_fingerprint
        if not voice_fingerprint.profiles():
            raise ValueError('Set up a voice before enabling recognition.')
    for row in rows:
        if row.get('enabled'):
            row['recognition_enabled'] = bool(on)
    with _lock:
        storage.set_app_state('voice_identity_config', {**config, 'satellites': rows})
    return rows


def recognition_on_everywhere():
    rows = [r for r in configuration().get('satellites', []) if r.get('enabled')]
    return bool(rows) and all(r.get('recognition_enabled') for r in rows)


def intercept(text: str, ctx: VoiceContext, language='en') -> dict | None:
    """Return a sanitized response when a turn is identity/authentication only."""
    low = (text or '').strip()
    pin_match = re.search(r'(?i)\b(?:my\s+)?pin\s+is\b\s*(.*)$', low)
    with _lock:
        key = (ctx.ha_instance_id, ctx.satellite_id)
        row = _sessions.get(key)
        pending = bool(row and row.get('pin_pending'))
        numeric_words = set(_SMALL) | set(_TENS) | {'hundred', 'thousand', 'and'}
        tokens = re.findall(r'[a-z]+|[0-9]+', low.lower())
        numeric_reply = pending and bool(tokens) and (tokens[0].isdecimal() or tokens[0] in numeric_words)
        credential = pin_match is not None or numeric_reply
        if credential:
            reply = {'status': 'authentication', 'message': 'Voice identity is not enabled for this satellite.'}
            if not ctx.paired or not row:
                return reply
            member = storage.get_member(row['member_id']) if row.get('member_id') else None
            if not _active(member):
                row['pin_pending'] = True
                row['name_pending'] = True
                reply['message'] = 'Tell me your name before your PIN.'
                return reply
            if not member.get('pin_hash'):
                row['pin_pending'] = False
                reply['message'] = 'Set up your member PIN on your phone first.'
                return reply
            row['pin_pending'] = True
            if _locked(ctx, member['id']) or storage.rate_locked(f"member:{member['id']}"):
                reply['message'] = 'Voice verification is locked. A parent can clear the voice lock on their phone.'
                return reply
            # Rate-limit ALL credential turns, including wrong length/format.
            request_key = f'voice:format:{ctx.ha_instance_id}:{ctx.satellite_id}'
            if storage.rate_locked(request_key):
                reply['message'] = 'Too many attempts. Try again in a moment.'
                return reply
            storage.rate_record(request_key, False)
            pin = normalize_pin(pin_match.group(1) if pin_match else low) if language.startswith('en') else None
            if pin is None or not 4 <= len(pin) <= 8 or member.get('pin_length') and len(pin) != member['pin_length']:
                reply['message'] = 'Say your PIN one digit at a time.'
                return reply
            ok = storage.verify_member_pin(member['id'], pin)
            _record(ctx, member['id'], ok)
            storage.rate_record(f"member:{member['id']}", ok)
            if not ok:
                row.pop('readback', None)
                row['level'] = 'named'
                row['pin_pending'] = True
                row['pin_revision'] = None
                row['generation'] = uuid.uuid4().hex
                reply['message'] = 'That PIN did not match.' if not _locked(ctx, member['id']) else 'Voice verification is locked. Ask a parent to clear it on their phone.'
                return reply
            row.pop('readback', None)
            row.pop('speaker_anchor', None)
            row.update(level='verified', pin_pending=False, expires_at=time.time() + SESSION_SECONDS,
                       pin_revision=member['pin_hash'], generation=uuid.uuid4().hex)
            from services import voice_fingerprint
            storage.rate_clear(request_key)
            if voice_fingerprint.enabled(ctx):
                if ctx.fingerprint:
                    row['speaker_anchor'] = ctx.fingerprint
                else:
                    reply['message'] = 'Verified here for ten minutes. Voice matching is unavailable; this is a room session.'
                    return reply
            reply['message'] = 'Verified here for ten minutes.'
            return reply
        if low.lower().rstrip('.!?') in ('forget who i am', "it's someone else", 'it is someone else', "that's not me", 'that is not me'):
            if row:
                _sessions[key] = _new_session(row.get('device_id'))
                _sessions[key]['recognition_suppressed'] = True
            return {'status': 'identity', 'message': 'I have cleared your identity here.'}
        name_match = re.fullmatch(r"(?i)(?:it['’]s|it is|this is|i am|i['’]m)\s+(.+?)[.!]?", low)
        if low.lower().rstrip('.!?') == 'cancel':
            return None
        if not name_match and not (row and row.get('name_pending')):
            return None
        if not ctx.paired or not row:
            return {'status': 'identity', 'message': 'Ask a parent to enable voice identity for this satellite on their phone.'}
        pending_prepare = row.get('pending_prepare') if row.get('level') == 'unknown' else None
        pending_pin = row.get('pin_pending') if row.get('level') == 'unknown' else False
        _sessions[key] = row = _new_session(row.get('device_id'))
        name = ' '.join((name_match.group(1) if name_match else low).rstrip('.!?').split()).casefold()
        matches = [m for m in storage.get_all_members() if _active(m) and name in voice_names(m)]
        if len(matches) != 1:
            row.update(name_pending=True, pin_pending=bool(pending_pin), pending_prepare=pending_prepare)
            return {'status': 'identity', 'message': 'Which family member? Say the full name.'}
        member = matches[0]
        row.update(level='named', member_id=member['id'], role=member.get('role'))
        if pending_prepare:
            row['pending_prepare'] = pending_prepare
        row['pin_pending'] = bool(pending_prepare or pending_pin)
        return {'status': 'identity', 'message': f"Hi {member.get('name')}." + (' Say your PIN to verify here.' if row['pin_pending'] else '')}


def expect_pin(installation, satellite):
    """After a setup dialog names the room, bare digits are the PIN (the
    intercept only reads a numeric reply while pin_pending is set)."""
    with _lock:
        row = _sessions.get((installation, satellite))
        if row and row.get('member_id'):
            row['pin_pending'] = True


def challenge(ctx):
    with _lock:
        row = _sessions.get((ctx.ha_instance_id, ctx.satellite_id))
        if ctx.paired and row and row['generation'] == ctx.generation:
            row['pin_pending'] = True
            row['name_pending'] = not bool(row.get('member_id'))
            return 'Say your PIN to verify here.' if row.get('member_id') else 'Tell me your name, then your PIN.'
    return 'Tell me your name, then your PIN.'


def expects_reply(ctx):
    with _lock:
        row = _sessions.get((ctx.ha_instance_id, ctx.satellite_id)) or {}
        if not ctx.paired or row.get('generation') != ctx.generation \
                or _locked(ctx, row.get('member_id')) \
                or storage.rate_locked(f"voice:format:{ctx.ha_instance_id}:{ctx.satellite_id}"):
            return False
        if row.get('pin_pending') or row.get('name_pending'):
            return True
        readback = row.get('readback') or {}
        return readback.get('request_id') == ctx.request_id and readback.get('expires_at', 0) > time.time()


def admin_state():
    with _lock:
        config = configuration()
        configured = {(r['ha_instance_id'], r['satellite_id']): r for r in config.get('satellites', [])}
        rows = []
        for key in set(configured) | set(_observed):
            row = {'answer_speaker': '', **_observed.get(key, {}), **configured.get(key, {})}
            row.pop('service_revision', None)
            session = _sessions.get(key) or {}
            member = storage.get_member(session.get('member_id')) if session.get('member_id') else None
            valid = session.get('expires_at', 0) > time.time() and _active(member) and _paired(*key, row.get('device_id')) \
                and session.get('role') == member.get('role') \
                and (not session.get('pin_revision') or session['pin_revision'] == member.get('pin_hash'))
            row.update(level=session.get('level', 'unknown') if valid else 'unknown',
                       member_id=member.get('id') if valid else None,
                       member_name=member.get('name') if valid else None,
                       expires_at=session.get('expires_at') if valid else None,
                       locked=bool((storage.get_app_state(f'voice:satellite:{key[0]}:{key[1]}') or {}).get('locked')))
            rows.append(row)
        locked_members = [{'id': m['id'], 'name': m.get('name') or 'Family member'} for m in storage.get_all_members()
                          if (storage.get_app_state(f"voice:member:{m['id']}") or {}).get('locked')]
        from services import announce
        return {'enabled': config.get('enabled', False), 'approvals_enabled': config.get('approvals_enabled', False),
                'satellites': rows, 'locked_members': locked_members,
                'speakers': announce.answer_speaker_choices(),
                'auth_history': storage.get_app_state('voice_auth_history') or [],
                'history': storage.get_app_state('voice_action_history') or []}


def recover(installation, satellite, clear_locks=False, member_id=None, by_member=None):
    with _lock, storage.db_lock, storage.db.transaction():
        _sessions.pop((installation, satellite), None)
        if clear_locks and installation and satellite:
            storage.set_app_state(f'voice:satellite:{installation}:{satellite}', {'fails': 0, 'locked': False})
        if clear_locks and member_id:
            storage.set_app_state(f'voice:member:{member_id}', {'fails': 0, 'locked': False})
        _audit(installation, satellite, member_id, 'voice_lock_cleared' if clear_locks else 'session_revoked', by_member)


def once(ctx, work):
    """Concurrent delivery of one request shares one sanitized result, not its text."""
    if not ctx.ha_instance_id:
        return work()
    key = (ctx.service_revision, ctx.ha_instance_id, ctx.satellite_id, ctx.request_id)
    with _lock:
        existing = _requests.get(key)
        if existing:
            future = existing[1]
            owner = False
        else:
            future = Future()
            _requests[key] = (time.time(), future)
            owner = True
        for old, (created, pending) in list(_requests.items()):
            if pending.done() and (time.time() - created > SESSION_SECONDS or len(_requests) > 256):
                _requests.pop(old, None)
    if not owner:
        return future.result(timeout=125)
    try:
        result = work()
        future.set_result(result)
        return result
    except Exception:
        result = {'error': 'I could not complete that request. Please try again.'}
        future.set_result(result)
        return result

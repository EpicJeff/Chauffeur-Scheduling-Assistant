"""Set up, check and switch on a voice by talking to Argyle (spec
docs/superpowers/specs/2026-10-13-voice-enrollment-design.md: Satellite flow,
Checking a phone voice on a speaker, Activation), plus the phone door's logic.

One small dialog state per satellite. While a dialog is open every utterance
on that satellite is intercepted here, before voice_identity, voice_approval
and the chat model: it is a sample, a yes or no, guidance, or a cancellation.
The enrollment core (voice_fingerprint) owns samples, tokens and templates;
this module only decides what Argyle says next and keeps the microphone open
between questions with HA's continue_conversation flag.
"""
import logging
import re
import threading
import time

from services import storage, voice_identity as identity, voice_fingerprint as fp

logger = logging.getLogger(__name__)
_dialogs = {}
_lock = threading.RLock()
EXPIRY = 600
YES = ('yes', 'yes please', 'yep', 'yeah', 'sure', 'ok', 'okay', 'do it', 'yes it was', 'correct')
NO = ('no', 'nope', 'no thanks', 'not now', 'leave it', 'no it was not', "no it wasn't")
START = ('set up my voice', 'setup my voice', 'set my voice up', 'enroll my voice', 'enrol my voice')
NAME_LEAD = r"^(for|it's|it is|this is|i am|i'm|its)\s+"


def _key(ctx):
    return (ctx.ha_instance_id, ctx.satellite_id)


def _reply(message, cont=False):
    return {'message': message, 'continue': bool(cont)}


def _refresh(ctx):
    """The session as it stands after an identity intercept on this turn."""
    return identity.context({'ha_instance_id': ctx.ha_instance_id, 'satellite_id': ctx.satellite_id,
                             'device_id': identity._observed.get(_key(ctx), {}).get('device_id'),
                             'request_id': ctx.request_id, 'observed_at': time.time()}, True)


def _locked_out(message):
    low = (message or '').lower()
    return 'locked' in low or 'too many' in low


def _activation_question(d):
    member = storage.get_member(d['member_id']) or {}
    who = 'you' if d.get('parent_id') == d['member_id'] else member.get('name', 'them')
    return f'Turn on voice recognition for {who} here? Say yes.'


def _finish_or_activate(key, d, lead):
    """After a save or a successful check: a parent present may switch it on
    (spec, Activation). Nobody else can, and the dialog says so."""
    if d.get('parent_id'):
        d['phase'] = 'activate'
        return _reply(f'{lead} {_activation_question(d)}', True)
    _dialogs.pop(key, None)
    return _reply(f'{lead} A parent can turn on recognition for you here.')


def _begin(key, ctx, d, anchor, exclude):
    try:
        fp.begin(ctx, d['member_id'], d.get('parent_id') or d['member_id'], anchor=anchor, exclude=exclude)
    except ValueError as error:
        _dialogs.pop(key, None)
        return _reply(str(error))
    d['phase'] = 'questions'
    asked = fp.ask(key)
    return _reply(f"Thanks. {asked['question']}", True)


def _next_question(key, conversation_id, lead):
    asked = fp.ask(key)
    fp.expect_conversation(key, conversation_id)
    return _reply(f"{lead} {asked['question']}".strip(), True)


def _apply_switch(key, on):
    _dialogs.pop(key, None)
    try:
        identity.set_recognition(key[0], key[1], on)
        return _reply('Voice recognition is on here.' if on else 'Voice recognition is off here.')
    except ValueError as error:
        return _reply(str(error))


def _verify_turn(ctx, text, want_parent):
    """One credential turn through the ordinary intercept: the name when the
    room is unnamed, then the PIN. Returns (refreshed_context, reply) where a
    non-None reply means keep talking."""
    out = identity.intercept(text, ctx)
    refreshed = _refresh(ctx)
    member = storage.get_member(refreshed.member_id) if refreshed.member_id else None
    if refreshed.level == 'verified' and member and (not want_parent or member.get('role') == 'parent'):
        return refreshed, None
    if out is None:
        return refreshed, _reply('Tell me your name, then your PIN. Or say cancel voice setup.', True)
    if _locked_out(out.get('message')):
        return refreshed, _reply(out['message'])
    if refreshed.level == 'verified' and want_parent:
        return refreshed, _reply("That is not a parent's PIN. A parent's PIN, please.", True)
    if refreshed.member_id and refreshed.level != 'verified' and out.get('status') == 'identity':
        return refreshed, _reply(out.get('message', '') + ' Say your PIN.', True)   # named; the PIN is next
    return refreshed, _reply(out.get('message', 'Say your PIN.') + ' Or say cancel voice setup.', True)


def _switch(key, ctx, on, name):
    """'turn on voice recognition for Lily here': a parent's act, PIN-verified
    through the ordinary intercept when the room is not already a verified parent."""
    member = storage.get_member(ctx.member_id) if ctx.member_id else None
    if ctx.level == 'verified' and member and member.get('role') == 'parent':
        return _apply_switch(key, on)
    _dialogs[key] = {'phase': 'switch_pin', 'on': on, 'name': name, 'expires_at': time.time() + EXPIRY}
    return _reply("A parent's PIN, please. " + ('Say your PIN.' if ctx.member_id else 'Tell me your name, then your PIN.'), True)


def intercept(text, ctx, evidence, conversation_id=None):
    """None when this is not a setup turn; otherwise what Argyle says and
    whether the satellite keeps listening."""
    if not ctx.paired:
        return None
    key = _key(ctx)
    low = ' '.join((text or '').lower().split()).rstrip('.!?')
    with _lock:
        for k, d in list(_dialogs.items()):
            if d['expires_at'] <= time.time():
                _dialogs.pop(k, None)
        d = _dialogs.get(key)
        if d is None and low != 'cancel voice setup':
            pending = fp._enrollments.get(key)
            if pending and pending.get('door') == 'satellite' and pending.get('phase') == 'questions':
                # Started from Config: adopt it, and the wake-up utterance earns question 1.
                d = _dialogs[key] = {'phase': 'questions', 'member_id': pending['member_id'],
                                     'expires_at': time.time() + EXPIRY}
                consenter = storage.get_member(pending.get('consent_actor') or '') or {}
                if consenter.get('role') == 'parent':
                    d['parent_id'] = consenter['id']
                if not pending.get('awaiting'):
                    return _next_question(key, conversation_id, 'Voice setup is ready.')
        if low == 'cancel voice setup':
            _dialogs.pop(key, None)
            return _reply(fp.cancel(key)['message'])
        if d is None:
            if low in START:
                _dialogs[key] = {'phase': 'who', 'expires_at': time.time() + EXPIRY}
                return _reply('Who is this for?', True)
            if low == 'check my voice':
                _dialogs[key] = {'phase': 'check_pin', 'expires_at': time.time() + EXPIRY}
                return _reply('Say your PIN.' if ctx.member_id else 'Tell me your name, then your PIN.', True)
            m = re.fullmatch(r'turn (on|off) voice recognition(?: for (.+?))?(?: here)?', low)
            if m:
                return _switch(key, ctx, m.group(1) == 'on', m.group(2) or '')
            return None
        d['expires_at'] = time.time() + EXPIRY
        vector = (evidence or {}).get('vector')
        phase = d['phase']

        if phase == 'who':
            name = re.sub(NAME_LEAD, '', low)
            matches = [m for m in storage.get_all_members() if identity._active(m) and name in identity.voice_names(m)]
            if len(matches) != 1:
                return _reply('Which family member? Say the full name.', True)
            member = matches[0]
            d['member_id'] = member['id']
            if member.get('role') == 'child':
                parents = identity.parents_named('')
                if len(parents) == 1:
                    d['parent_id'] = parents[0]['id']
                    d['phase'] = 'consent_pin'
                    return _reply(f"{parents[0]['name']}, a parent's PIN, please.", True)
                d['phase'] = 'consent_parent'
                return _reply("Which parent is giving consent? Say your name, then I'll ask for your PIN.", True)
            d['phase'] = 'pin'
            if member.get('role') == 'parent':
                d['parent_id'] = member['id']
            identity.intercept(f"it's {member['name']}", ctx)   # names the session so the PIN verifies this member
            return _reply('Say your PIN.', True)

        if phase == 'consent_parent':
            parents = identity.parents_named(re.sub(NAME_LEAD, '', low))
            if len(parents) != 1:
                return _reply('Which parent? Say the full name.', True)
            d['parent_id'] = parents[0]['id']
            d['phase'] = 'consent_pin'
            return _reply("A parent's PIN, please.", True)

        if phase == 'consent_pin':
            out = identity.verify_parent_consent(ctx, d['parent_id'], text)
            if not out['ok']:
                if _locked_out(out['message']):
                    _dialogs.pop(key, None)
                    return _reply(out['message'])
                return _reply(out['message'] + ' Try once more, or say cancel voice setup.', True)
            return _begin(key, ctx, d, anchor=None, exclude=vector)

        if phase == 'pin':
            out = identity.intercept(text, ctx)
            refreshed = _refresh(ctx)
            if out is None or refreshed.level != 'verified' or refreshed.member_id != d['member_id']:
                if out and _locked_out(out.get('message')):
                    _dialogs.pop(key, None)
                    return _reply(out['message'])
                return _reply((out or {}).get('message', 'Say your PIN.') + ' Try once more, or say cancel voice setup.', True)
            return _begin(key, ctx, d, anchor=vector, exclude=None)

        if phase == 'questions':
            out = fp.enrollment_turn(text, ctx, evidence, conversation_id=conversation_id)
            if out is None:
                _dialogs.pop(key, None)
                return _reply('Voice setup stopped.')
            status = out.get('status')
            if status in ('accepted', 'retry') and key in fp._enrollments:
                pending = fp._enrollments[key]
                if pending.get('awaiting'):
                    # A stale or unrelated turn: the open question stands; ask it again.
                    return _reply(f"{out['message']} {pending['awaiting'] and fp.QUESTIONS[pending['step']]}", True)
                return _next_question(key, conversation_id, out['message'])
            if status == 'confirm':
                d['phase'] = 'confirm'
                return _reply(out['message'], True)
            if status == 'done':
                return _finish_or_activate(key, d, out['message'])
            _dialogs.pop(key, None)
            return _reply(out['message'])

        if phase == 'confirm':
            if low in YES:
                out = fp.confirm(key, True)
                if out['status'] == 'done':
                    return _finish_or_activate(key, d, out['message'])
                _dialogs.pop(key, None)
                return _reply(out['message'])
            if low in NO:
                _dialogs.pop(key, None)
                return _reply(fp.confirm(key, False)['message'])
            return _reply('Say yes or no.', True)

        if phase == 'activate':
            _dialogs.pop(key, None)
            if low in YES:
                try:
                    identity.set_recognition(key[0], key[1], True)
                    return _reply('Voice recognition is on here.')
                except ValueError as error:
                    return _reply(str(error))
            return _reply('Left off. A parent can turn it on later.')

        if phase == 'check_pin':
            refreshed, reply = _verify_turn(ctx, text, want_parent=False)
            if reply is not None:
                if not reply['continue']:
                    _dialogs.pop(key, None)
                return reply
            d.update(member_id=refreshed.member_id, anchor=vector, phase='check_answer')
            member = storage.get_member(refreshed.member_id) or {}
            if member.get('role') == 'parent':
                d['parent_id'] = member['id']
            return _reply(fp.CHECK_QUESTION, True)

        if phase == 'check_answer':
            out = fp.check(key, d['member_id'], evidence, d.get('anchor'))
            if out['status'] == 'retry':
                return _reply(out['message'] + ' ' + fp.CHECK_QUESTION, True)
            if out['status'] == 'checked':
                return _finish_or_activate(key, d, out['message'])
            d.update(phase='check_offer', last_evidence=evidence)
            return _reply(out['message'] + ' Shall I set up your voice here now? Say yes.', True)

        if phase == 'check_offer':
            if low not in YES:
                _dialogs.pop(key, None)
                return _reply('Alright. Your phone voice stays off here.')
            reply = _begin(key, ctx, d, anchor=d.get('anchor'), exclude=None)
            pending = fp._enrollments.get(key)
            if not pending:
                return reply
            # The check's answer is already this voice, bound to this PIN: keep it as sample 1.
            first = fp.answer(key, {**(d.get('last_evidence') or {}), 'enrollment_id': pending['id']},
                              token=(pending.get('awaiting') or {}).get('token'))
            if first['status'] == 'accepted':
                return _next_question(key, conversation_id, 'Keeping that answer as the first sample.')
            return reply

        if phase == 'switch_pin':
            refreshed, reply = _verify_turn(ctx, text, want_parent=True)
            if reply is not None:
                if not reply['continue']:
                    _dialogs.pop(key, None)
                return reply
            return _apply_switch(key, d['on'])
    return None


# --- the phone door ---------------------------------------------------------

def _phone_ctx(member_id):
    return identity.VoiceContext('phone', member_id, '', '', service_revision=identity._revision(), paired=True)


def phone_begin(member, parent_id=None, parent_pin=None):
    """Set up my voice on the phone. The member is the signed-in personal
    session; a child's screen supplies a parent's PIN for the consent verifier."""
    consent_actor = member['id']
    if member.get('role') == 'child':
        if not parent_id or not parent_pin:
            raise PermissionError("A parent's PIN is needed to set up a child's voice.")
        out = identity.verify_parent_consent(_phone_ctx(member['id']), parent_id, f'my pin is {parent_pin}')
        if not out['ok']:
            raise PermissionError(out['message'])
        consent_actor = parent_id
    fp.begin(_phone_ctx(member['id']), member['id'], consent_actor, door='phone')
    asked = fp.ask(('phone', member['id']))
    return {**asked, 'total': len(fp.QUESTIONS)}


def phone_answer(member, enrollment_id, token, audio, content_type):
    """One recorded answer: decoded, embedded, admitted. Never transcribed,
    never the agent. Returns the next question and token while the
    enrollment is open."""
    from services import app_voice_audio
    key = ('phone', member['id'])
    pending = fp._enrollments.get(key)
    if not pending or pending['id'] != enrollment_id:
        raise ValueError('That voice setup has ended. Start again.')
    try:
        pcm = app_voice_audio.pcm(audio, content_type)
        vec, seconds = fp.extract(pcm, {'sample_rate': 16000}, enrollment=True)
        evidence = {'vector': vec, 'seconds': seconds, 'enrollment_id': enrollment_id}
    except ValueError:
        evidence = {'vector': None, 'seconds': 0, 'enrollment_id': enrollment_id}
    out = fp.answer(key, evidence, token=token)
    if out['status'] in ('accepted', 'retry') and key in fp._enrollments:
        current = fp._enrollments[key].get('awaiting')
        if current is None:
            asked = fp.ask(key)
        else:   # a stale token: the open question and its live token stand
            asked = {'question': fp.QUESTIONS[current['step']], 'token': current['token'], 'step': current['step'] + 1}
        return {**out, 'question': asked['question'], 'token': asked['token'], 'step': asked['step']}
    return out


def phone_cancel(member):
    return fp.cancel(('phone', member['id']))


def phone_state(member):
    pending = fp._enrollments.get(('phone', member['id']))
    rows = [r for r in fp.profiles() if r['member_id'] == member['id']]
    return {'enrolling': bool(pending), 'step': (pending['step'] + 1) if pending else 0,
            'question': fp.QUESTIONS[pending['step']] if pending and pending['step'] < len(fp.QUESTIONS) else '',
            'profiles': [{'provenance': r.get('provenance', 'satellite'),
                          'checks': r.get('checks') if isinstance(r.get('checks'), dict) else {}} for r in rows]}

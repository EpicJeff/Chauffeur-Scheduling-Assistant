"""Local CPU speaker evidence. Audio/observations/anchors never persist.

Templates live outside the general database and member JSON. Recognition
supplies a named lens, not a member credential or a payment approval.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import logging
import re
import json
import math
from pathlib import Path
import threading
import time
import uuid

from services import storage, voice_identity as identity

MODEL = 'wespeaker_en_voxceleb_resnet34.onnx'
MODEL_SHA = '5ef208a9da1453335308a6b6f4e6dfbd7e183a38b604de0a57664f45d257fe94'
MODEL_URL = 'https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/' + MODEL
REVISION = 'wespeaker-resnet34:' + MODEL_SHA + ':sherpa-1.13.8'
THRESHOLD, MARGIN, CONTINUITY = .70, .12, .65
DIFFERENT = .40  # uncertain similarities are neutral, not speaker changes
IDENTIFY_SECONDS = 1.2
MAX_AUDIO = 1_000_000
# Answers, not phrases: the speaker model is text-independent, and every
# sample is bound to its run and admitted by a one-use token (spec, core).
QUESTIONS = (
    'Tell me about your day so far, for about ten seconds.',
    'What is coming up for the family this week?',
    'Describe the room you are in.',
    'What would you like help with most mornings?',
    'Tell me something you are looking forward to.',
)
CHECK_QUESTION = 'Tell me what you did this morning, for about ten seconds.'
# Short answers fill the same five samples, with follow-ups after the fixed list.
KID_QUESTIONS = (
    ("What's your favorite color, and why?", 'your favorite color'),
    ("What's your favorite food?", 'your favorite food'),
    ('What do you like to do at the park?', 'the park'),
    ("What's your favorite animal?", 'your favorite animal'),
    ('What did you have for breakfast today?', 'breakfast'),
    ('Who is your best friend, and what do you play together?', 'your best friend'),
    ('What do you want to be when you grow up?', 'growing up'),
    ("What's the best part of school?", 'school'),
    ("What's a game you like to play?", 'that game'),
    ("Do you have a pet or a stuffed animal? What's its name?", 'your pet or stuffed animal'),
    ("What's your favorite thing to do on the weekend?", 'the weekend'),
    ('If you could go anywhere, where would you go?', 'where you would go'),
    ('What makes you laugh?', 'what makes you laugh'),
    ("What's your favorite song or show?", 'your favorite song or show'),
    ('What do you like to eat for dinner?', 'dinner'),
)
FOLLOW_UPS = ('Tell me more about {topic}.', 'What else about {topic}?')
SHORT_FOLLOW_UPS = ('Tell me more about that.', 'Why is that?')
INTERJECTIONS = ('Nice.', 'Cool.', 'Good one.')
POOL_SECONDS = 4
POOLED_ANSWER_SECONDS = 1
MAX_POOLED_TURNS = 40
MAX_DROPS = 3
MAX_POOL_RESTARTS = 2
PROMPTS = QUESTIONS   # the Config page and old tests read this name
MIN_SAMPLE_SECONDS = 4
MAX_RETRIES = 3
logger = logging.getLogger(__name__)
_lock = threading.RLock()
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='voice-fingerprint')
_slot = threading.BoundedSemaphore(1)
_extractor = None
_observations = {}
_enrollments = {}
_last = {}


def kid_question(index):
    n = len(KID_QUESTIONS)
    if index < n:
        return KID_QUESTIONS[index][0]
    lap, topic = divmod(index - n, n)
    return FOLLOW_UPS[lap % len(FOLLOW_UPS)].format(topic=KID_QUESTIONS[topic][1])


def current_question(pending):
    """The next question, or a same-topic follow-up after a short answer."""
    if not pending.get('pooled'):
        return QUESTIONS[pending['step']] if pending['step'] < len(QUESTIONS) else ''
    if pending.get('short'):
        return SHORT_FOLLOW_UPS[(pending['short'] - 1) % len(SHORT_FOLLOW_UPS)]
    return kid_question(pending['question_index'])


def root():
    path = Path(storage.DB_PATH).parent / 'voice_private'
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def model_ready():
    path = root() / MODEL
    try:
        return path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == MODEL_SHA
    except OSError:
        return False


def _load():
    try:
        return json.loads((root() / 'templates.json').read_text())
    except (FileNotFoundError, ValueError):
        return []


def _save(rows):
    path = root() / 'templates.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(rows), encoding='utf-8')
    temporary.chmod(0o600)
    temporary.replace(path)


def _prune():
    now = time.time()
    for oid in list(_observations):
        if _observations[oid]['expires'] <= now:
            _observations.pop(oid, None)
    for key in list(_enrollments):
        if _enrollments[key]['expires_at'] <= now:
            _enrollments.pop(key, None)


def profiles():
    """Hide inactive/incompatible templates without destroying reversible state."""
    with _lock:
        rows = _load()
        active = [r for r in rows if r.get('revision') == REVISION
                  and identity._active(storage.get_member(r.get('member_id')))]
        return active


def satellite(ctx):
    return next((r for r in identity.configuration().get('satellites', [])
                 if r['ha_instance_id'] == ctx.ha_instance_id and r['satellite_id'] == ctx.satellite_id), {})


def enabled(ctx):
    return bool(ctx.paired and satellite(ctx).get('recognition_enabled'))


def prepare_model():
    """Explicit parent setup downloads only a checksum-pinned public model."""
    import requests
    global _extractor
    path = root() / MODEL
    temporary = path.with_suffix('.download')
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != MODEL_SHA:
        try:
            with requests.get(MODEL_URL, stream=True, timeout=(10, 30)) as response:
                response.raise_for_status()
                count = 0
                with temporary.open('wb') as target:
                    for chunk in response.iter_content(65536):
                        count += len(chunk)
                        if count > 27_000_000:
                            raise ValueError('Voice model exceeded its pinned size.')
                        target.write(chunk)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != MODEL_SHA:
                raise ValueError('Voice model checksum failed.')
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    _extractor = None
    _engine()
    return status()


def _engine():
    global _extractor
    if _extractor is None:
        path = root() / MODEL
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != MODEL_SHA:
            raise ValueError('Prepare the voice model in Config first.')
        import sherpa_onnx
        _extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(path), num_threads=1, provider='cpu'))
    return _extractor


def normalized(vector):
    if len(vector) != 256 or any(not math.isfinite(v) for v in vector):
        raise ValueError('Invalid voice vector.')
    norm = math.sqrt(sum(v * v for v in vector))
    if norm <= 0:
        raise ValueError('Empty voice vector.')
    return [float(v / norm) for v in vector]


def score(a, b):
    return sum(x * y for x, y in zip(a, b))


def extract(audio, metadata, *, enrollment=False):
    import numpy as np
    if metadata.get('codec') != 'pcm' or metadata.get('format') != 'wav' \
            or metadata.get('bit_rate') != 16 or metadata.get('channel') != 1 \
            or metadata.get('sample_rate') not in (16000, 24000, 48000) or len(audio) % 2:
        raise ValueError('Recognition needs mono 16-bit PCM audio.')
    rate = metadata['sample_rate']
    samples = np.frombuffer(audio, dtype='<i2').astype('float32') / 32768
    if not rate * .3 <= len(samples) <= rate * 15:
        raise ValueError('Use a clear phrase between a third of a second and fifteen seconds.')
    frames = samples[:len(samples) // (rate // 50) * (rate // 50)].reshape(-1, rate // 50)
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    voiced_seconds = float(np.count_nonzero(rms > .008) / 50)
    if voiced_seconds < .3 or float(np.mean(np.abs(samples) >= .99)) > .03:
        raise ValueError('Audio was too quiet, clipped, or short.')
    engine = _engine()

    def embedding(waveform):
        stream = engine.create_stream()
        stream.accept_waveform(sample_rate=rate, waveform=waveform)
        stream.input_finished()
        if not engine.is_ready(stream):
            raise ValueError('Not enough usable speech.')
        return normalized(engine.compute(stream))

    vector = embedding(samples)
    if enrollment and len(samples) >= rate * 5:
        middle = len(samples) // 2
        if score(embedding(samples[:middle]), embedding(samples[middle:])) < .45:
            raise ValueError('Speaker evidence changed during the phrase.')
    return vector, voiced_seconds


async def observe(audio, metadata, ctx):
    if not ctx.paired or not all(isinstance(metadata.get(k), str) and 0 < len(metadata[k]) <= 128
                                for k in ('run_id', 'utterance_id')):
        raise ValueError('Enable identity for this satellite first.')
    if metadata['utterance_id'] != ctx.request_id:
        raise ValueError('Utterance does not match the request.')
    with _lock:
        _prune()
        key = (ctx.ha_instance_id, ctx.satellite_id)
        # A setup dialog (voice_setup) needs the PIN turn's fingerprint as its
        # anchor and the check's answer before any enrollment or recognition
        # exists on the satellite, so an open dialog admits audio too.
        try:
            from services import voice_setup
            dialog_open = key in voice_setup._dialogs
        except Exception:
            dialog_open = False
        if not enabled(ctx) and key not in _enrollments and not dialog_open:
            raise ValueError('Start voice enrollment or enable recognition on this satellite first.')
    if not _slot.acquire(blocking=False):
        raise ValueError('Voice worker is busy; try again.')
    revision = identity._revision()
    started = time.monotonic()
    key = (ctx.ha_instance_id, ctx.satellite_id)
    enrollment_id = None

    def compute():
        try:
            return extract(audio, metadata, enrollment=bool(enrollment_id))
        finally:
            _slot.release()

    with _lock:
        if revision != identity._revision() or not identity._paired(*key, metadata.get('device_id')):
            _slot.release()
            raise ValueError('Satellite authorization changed.')
        _prune()
        if len(_observations) >= 128:
            _slot.release()
            raise ValueError('Too many pending voice observations.')
        oid = uuid.uuid4().hex
        enrollment_id = (_enrollments.get(key) or {}).get('id')
        try:
            future = _pool.submit(compute)
        except Exception:
            _slot.release()
            raise
        _observations[oid] = {'key': (*key, metadata.get('device_id'), metadata['run_id'], metadata['utterance_id']),
                              'revision': revision, 'future': future, 'expires': time.time() + 60,
                              'enrollment_id': enrollment_id}
        _last[key] = {'available': False, 'message': 'Processing voice sample.'}
        if len(_last) > 256:
            _last.pop(next(iter(_last)))

    def finished(completed):
        try:
            completed.result()
            state = {'available': True, 'latency_ms': round((time.monotonic() - started) * 1000)}
        except Exception as error:
            state = {'available': False, 'message': str(error) if isinstance(error, ValueError) else 'Voice model unavailable.'}
        with _lock:
            if revision == identity._revision():
                _last[key] = state

    future.add_done_callback(finished)
    return {'observation_id': oid}


def consume(ctx, metadata, text=''):
    with _lock:
        _prune()
        oid = metadata.get('observation_id')
        row = _observations.get(oid)
        key = (ctx.ha_instance_id, ctx.satellite_id, metadata.get('device_id'),
               metadata.get('run_id'), metadata.get('utterance_id'))
        if not row or row['key'] != key or row['revision'] != ctx.service_revision \
                or ctx.request_id != metadata.get('utterance_id') or not ctx.paired:
            return None
        row = _observations.pop(oid)
        pending = _enrollments.get((ctx.ha_instance_id, ctx.satellite_id))
        setup_phrase = bool(pending and pending.get('awaiting'))
        if not setup_phrase:
            # A setup dialog's PIN anchor and check answer are long samples
            # too (device, 2026-10-13: every check answer timed out at .4 s
            # and was reported as "a little longer").
            try:
                from services import voice_setup
                setup_phrase = (ctx.ha_instance_id, ctx.satellite_id) in voice_setup._dialogs
            except Exception:
                pass
    if 'future' in row:
        try:
            # Evidence is best effort; a timeout never clears the current identity.
            # Answers to setup questions may wait 3s for the longer enrollment checks.
            vector, seconds = row['future'].result(timeout=3 if setup_phrase else .4)
        except Exception:
            return None
        row = {**row, 'vector': vector, 'seconds': seconds}
        row.pop('future', None)
    if row['revision'] != identity._revision() or not identity._paired(ctx.ha_instance_id, ctx.satellite_id, metadata.get('device_id')):
        return None
    return row


def _key_str(key):
    return f'{key[0]}:{key[1]}'


def _busy(member_id):
    return any(p['member_id'] == member_id for p in _enrollments.values())


def begin(ctx, member_id, consent_actor, *, door='satellite', anchor=None, exclude=None, pooled=False):
    """Open an enrollment. `anchor` is the enrollee's own credential fingerprint
    (self-enrollment binds every sample to it); `exclude` is the consenting
    parent's (a child's samples must not match it). Both live only here."""
    member = storage.get_member(member_id)
    if door == 'satellite' and (not ctx.paired or not identity._active(member)):
        raise ValueError('Choose an enabled satellite and active family member.')
    if door == 'phone' and not identity._active(member):
        raise ValueError('That family member is not active.')
    if not model_ready():
        raise ValueError('Prepare the voice model first.')
    key = ('phone', member_id) if door == 'phone' else (ctx.ha_instance_id, ctx.satellite_id)
    with _lock:
        _prune()
        if key in _enrollments:
            raise ValueError('Voice setup is already in progress here.')
        if _busy(member_id):
            raise ValueError('That person is already setting up a voice.')
        if len(_enrollments) >= 16:
            raise ValueError('Too many pending enrollments.')
        _enrollments[key] = {
            'id': uuid.uuid4().hex, 'member_id': member_id, 'consent_actor': consent_actor, 'door': door,
            'device_id': satellite(ctx).get('device_id') if door == 'satellite' else 'phone',
            'service_revision': ctx.service_revision if door == 'satellite' else identity._revision(),
            'samples': [], 'step': 0, 'retries': 0, 'awaiting': None, 'phase': 'questions',
            'pooled': bool(pooled), 'pool': [], 'pool_seconds': 0.0, 'question_index': 0,
            'turns': 0, 'short': 0, 'drops': 0, 'restarts': 0,
            'anchor': anchor, 'exclude': exclude, 'bound': anchor is not None or exclude is not None,
            'reference': None, 'expires_at': time.time() + 600}
    if door == 'satellite':
        identity.recover(ctx.ha_instance_id, ctx.satellite_id)
    return status()


def ask(key):
    """The current step's question with a fresh one-use token."""
    with _lock:
        _prune()
        pending = _enrollments.get(key)
        if not pending or pending['phase'] != 'questions':
            raise ValueError('No voice setup is waiting for an answer here.')
        token = uuid.uuid4().hex
        pending['awaiting'] = {'step': pending['step'], 'token': token, 'conversation_id': None, 'asked_at': time.time()}
        return {'enrollment_id': pending['id'], 'step': pending['step'] + 1,
                'question': current_question(pending), 'token': token}


def expect_conversation(key, conversation_id):
    """The satellite door records the question's conversation id once it is known."""
    with _lock:
        pending = _enrollments.get(key)
        if pending and pending.get('awaiting') and conversation_id:
            pending['awaiting']['conversation_id'] = conversation_id


def cancel(key):
    with _lock:
        _enrollments.pop(key, None)
    return {'status': 'ended', 'message': 'Voice setup cancelled.'}


def _end(key, message):
    _enrollments.pop(key, None)
    return {'status': 'ended', 'message': message, 'step': 0}


def answer(key, evidence, token=None, conversation_id=None):
    """Admit one answer: the token must be the current one (one use), the
    conversation id must match when both are known, the sample must be long
    enough, and the speaker must be the credential's (or not the parent's)."""
    with _lock:
        _prune()
        pending = _enrollments.get(key)
        if not pending or pending['phase'] != 'questions':
            return {'status': 'retry', 'message': 'No voice setup is waiting for an answer here.', 'step': 0}
        awaiting = pending.get('awaiting')
        step = pending['step']
        if not awaiting or awaiting['token'] != token or awaiting['step'] != step \
                or (conversation_id and awaiting['conversation_id'] and awaiting['conversation_id'] != conversation_id):
            return {'status': 'retry', 'step': step + 1,
                    'message': 'Voice setup is in progress. Answer the question, or say cancel voice setup.'}
        pending['awaiting'] = None   # one use, spent whatever happens next
        if pending.get('pooled'):
            return _pooled_answer(key, pending, evidence, step)
        if not evidence or evidence.get('enrollment_id') not in (None, pending['id']) \
                or evidence.get('seconds', 0) < MIN_SAMPLE_SECONDS or not evidence.get('vector'):
            pending['retries'] += 1
            if pending['retries'] >= MAX_RETRIES:
                return _end(key, 'I could not get a clear sample three times. Voice setup stopped; try again somewhere quieter.')
            return {'status': 'retry', 'step': step + 1, 'message': 'A little longer, please.'}
        vector = evidence['vector']
        if pending['anchor'] is not None and score(vector, pending['anchor']) < CONTINUITY:
            return _end(key, 'That did not sound like the voice that said the PIN. Voice setup stopped.')
        if pending['exclude'] is not None and score(vector, pending['exclude']) >= CONTINUITY:
            return _end(key, 'That sounded like the parent who gave consent, not the person being set up. Voice setup stopped.')
        samples = pending['samples']
        if samples and any(score(vector, other) < CONTINUITY for other in samples):
            return _end(key, 'The samples did not sound consistent. Voice setup stopped.')
        pending['retries'] = 0
        if step < 3:
            samples.append(vector)
        reference = normalized([sum(v[i] for v in samples) for i in range(256)])
        pending['reference'] = reference
        if step >= 3:
            rivals = [r for r in profiles() if r['member_id'] != pending['member_id']]
            competing = max((score(vector, r['vector']) for r in rivals), default=-1)
            if score(vector, reference) < THRESHOLD or score(vector, reference) - competing < MARGIN:
                return _end(key, 'I could not tell this voice apart reliably. Voice setup stopped; recognition stays off.')
        pending['step'] += 1
        if pending['step'] < len(QUESTIONS):
            return {'status': 'accepted', 'step': pending['step'] + 1, 'message': 'Got it.'}
        return _closing(key, pending)


def _closing(key, pending):
    """The dialog verifies the parent's closing PIN for someone else's voice."""
    if pending['door'] == 'satellite' and pending['consent_actor'] != pending['member_id']:
        pending['phase'] = 'confirm'
        name = (storage.get_member(pending['member_id']) or {}).get('name', 'them')
        lead = 'All done! ' if pending.get('pooled') else ''
        return {'status': 'confirm', 'step': 5, 'message': f'{lead}If that was {name}, say your PIN.'}
    return _finish(key, pending)


def _pooled_answer(key, pending, evidence, step):
    """Admit a short answer into this step only; check answers are scored alone."""
    name = (storage.get_member(pending['member_id']) or {}).get('name', 'them')
    pending['turns'] += 1
    if pending['turns'] > MAX_POOLED_TURNS:
        return _end(key, f"That's enough for today. I couldn't get all of {name}'s voice; try again another time.")
    usable = bool(evidence) and evidence.get('enrollment_id') in (None, pending['id']) \
        and bool(evidence.get('vector')) and evidence.get('seconds', 0) >= POOLED_ANSWER_SECONDS
    if not usable:
        pending['short'] += 1
        if pending['short'] >= MAX_RETRIES:
            return _end(key, f"I couldn't get enough of {name}'s voice. Try again another time.")
        return {'status': 'retry', 'step': step + 1, 'message': ''}
    vector, seconds = evidence['vector'], float(evidence['seconds'])
    pending['short'] = 0
    if pending['exclude'] is not None and score(vector, pending['exclude']) >= CONTINUITY:
        return _end(key, 'That sounded like the parent who gave consent, not the person being set up. Voice setup stopped.')
    if pending['anchor'] is None:
        # Until the parent names pool 1, no answer may seed a different voice.
        if any(score(vector, other) < CONTINUITY for other in pending['pool']):
            pending['restarts'] += 1
            if pending['restarts'] >= MAX_POOL_RESTARTS:
                return _end(key, 'The voices kept changing. Voice setup stopped.')
            pending['pool'], pending['pool_seconds'], pending['question_index'] = [], 0.0, 0
            return {'status': 'restart', 'step': step + 1, 'message': "Let's start over."}
    elif score(vector, pending['anchor']) < CONTINUITY:
        pending['drops'] += 1
        pending['question_index'] += 1
        if pending['drops'] >= MAX_DROPS:
            return _end(key, 'The voices kept changing. Voice setup stopped.')
        return {'status': 'dropped', 'step': step + 1, 'message': "Let's try another one."}
    pending['drops'] = 0
    pending['question_index'] += 1
    pending['pool'].append(vector)
    pending['pool_seconds'] += seconds
    interjection = INTERJECTIONS[(pending['turns'] - 1) % len(INTERJECTIONS)]
    if pending['pool_seconds'] < POOL_SECONDS:
        return {'status': 'accepted', 'step': step + 1, 'message': interjection}
    pool = pending['pool']
    if step < 3:
        mean = normalized([sum(v[i] for v in pool) for i in range(256)])
        pending['samples'].append(mean)
        pending['reference'] = normalized([sum(v[i] for v in pending['samples']) for i in range(256)])
    else:
        # A mean can pass when live recognition of its individual answers fails.
        rivals = [r for r in profiles() if r['member_id'] != pending['member_id']]
        for v in pool:
            competing = max((score(v, r['vector']) for r in rivals), default=-1)
            own = score(v, pending['reference'])
            if own < THRESHOLD or own - competing < MARGIN:
                return _end(key, 'I could not tell this voice apart reliably. Voice setup stopped; recognition stays off.')
    pending['pool'], pending['pool_seconds'] = [], 0.0
    pending['step'] += 1
    if pending['step'] == 1 and pending['anchor'] is None:
        pending['phase'] = 'name_voice'
        return {'status': 'name_voice', 'step': 2, 'message': f'Is that {name} talking? Say yes.'}
    if pending['step'] == 4:
        return {'status': 'accepted', 'step': 5, 'message': 'Almost done!'}
    if pending['step'] < 5:
        return {'status': 'accepted', 'step': pending['step'] + 1, 'message': interjection}
    return _closing(key, pending)


def name_voice(key, yes):
    """The parent's yes makes pool 1 the anchor for every later answer."""
    with _lock:
        pending = _enrollments.get(key)
        if not pending or pending['phase'] != 'name_voice':
            return {'status': 'retry', 'message': 'Nothing is waiting for a yes.', 'step': 0}
        if not yes:
            name = (storage.get_member(pending['member_id']) or {}).get('name', 'them')
            return _end(key, f"Not saved. Try again when it's just {name}.")
        pending['anchor'] = pending['samples'][0]
        pending['phase'] = 'questions'
        return {'status': 'accepted', 'step': 2, 'message': 'Great.'}


def confirm(key, yes):
    with _lock:
        pending = _enrollments.get(key)
        if not pending or pending['phase'] != 'confirm':
            return {'status': 'retry', 'message': 'Nothing is waiting for a yes.', 'step': 0}
        if not yes:
            return _end(key, 'Not saved. Say set up my voice to start again.')
        return _finish(key, pending)


def _finish(key, pending):
    member = storage.get_member(pending['member_id'])
    if not identity._active(member):
        return _end(key, 'That member is no longer active.')
    reference = pending['reference']
    rows = [r for r in _load() if not (r['member_id'] == member['id'] and r.get('provenance', 'satellite') == pending['door']
                                      and (pending['door'] == 'phone' or r['key'] == list(key)))]
    checks = {_key_str(key): 'checked'} if pending['door'] == 'satellite' else {}
    rows.append({'member_id': member['id'], 'key': list(key) if pending['door'] == 'satellite' else ['phone', member['id']],
                 'vector': reference, 'revision': REVISION, 'consent_actor': pending['consent_actor'],
                 'created_at': time.time(), 'checks': checks, 'calibrated': True,
                  'provenance': pending['door'], 'device_id': pending['device_id'],
                  'pooled': bool(pending.get('pooled'))})
    active = [r for r in rows if r.get('revision') == REVISION and identity._active(storage.get_member(r['member_id']))]
    for row in active:
        if any(r['member_id'] != row['member_id'] and score(r['vector'], row['vector']) >= THRESHOLD - MARGIN for r in active):
            row['calibrated'] = False
            if isinstance(row.get('checks'), dict):
                row['checks'] = {k: 'does_not_transfer' if v == 'checked' else v for k, v in row['checks'].items()}
    _save(rows)
    _enrollments.pop(key, None)
    note = '' if pending['bound'] else ' Voice matching was unavailable during setup, so this relied on the samples matching each other.'
    if pending['door'] == 'phone':
        return {'status': 'done', 'step': 5, 'message': 'Saved. Every speaker will use it. If one ever gets you wrong, say "Hey Argyle, check my voice" there.' + note}
    return {'status': 'done', 'step': 5, 'message': 'Your voice is saved, for every speaker.' + note}


def usable_on(row, key):
    """A voice set up anywhere names its person on every speaker, except a
    speaker where a check proved it does not transfer (device evidence
    2026-10-13: a phone-made voice passed the kitchen check twice). A legacy
    row has no check map and is usable everywhere."""
    if not row.get('calibrated', True):
        return False   # its two checks failed or a similar voice arrived: never used for naming
    checks = row.get('checks')
    if isinstance(checks, dict):
        return checks.get(_key_str(key)) != 'does_not_transfer'
    return True


def checked_on(row, key):
    """Compatibility name: whether the voice may be used on that speaker."""
    return usable_on(row, key)


def check(key, member_id, evidence, anchor):
    """One explicit spoken check of a phone template on a satellite: the answer
    must be the credential's voice, then it is scored like a held-out check."""
    if not evidence or evidence.get('seconds', 0) < MIN_SAMPLE_SECONDS or not evidence.get('vector'):
        return {'status': 'retry', 'message': 'A little longer, please.'}
    vector = evidence['vector']
    if anchor is not None and score(vector, anchor) < CONTINUITY:
        return {'status': 'retry', 'message': 'That did not sound like the voice that said the PIN. Try once more.'}
    with _lock:
        rows = _load()
        mine = [r for r in rows if r['member_id'] == member_id and r.get('provenance') == 'phone' and r.get('revision') == REVISION]
        if not mine:
            return {'status': 'retry', 'message': 'There is no phone voice to check. Set up your voice on your phone first.'}
        row = mine[-1]
        rivals = [r for r in rows if r['member_id'] != member_id and r.get('revision') == REVISION
                  and identity._active(storage.get_member(r['member_id'])) and usable_on(r, key)]
        competing = max((score(vector, r['vector']) for r in rivals), default=-1)
        own = score(vector, row['vector'])
        ok = own >= THRESHOLD and own - competing >= MARGIN
        logger.info(f"[voice-setup] check on {_key_str(key)}: voiced={evidence.get('seconds'):.1f}s own={own:.2f} "
                    f"rival={competing:.2f} -> {'checked' if ok else 'does_not_transfer'}")
        row.setdefault('checks', {})[_key_str(key)] = 'checked' if ok else 'does_not_transfer'
        _save(rows)
    if ok:
        return {'status': 'checked', 'message': 'Your phone voice works here.'}
    return {'status': 'does_not_transfer', 'message': 'Your phone voice does not match this microphone.'}


def on_member_status(member_id):
    """Archiving or disabling stops matching (profiles() already filters) and
    cancels a pending enrollment; it never deletes a template."""
    with _lock:
        for key in list(_enrollments):
            if _enrollments[key]['member_id'] == member_id and not identity._active(storage.get_member(member_id)):
                _enrollments.pop(key, None)


def enrollment_turn(text, ctx, evidence, conversation_id=None):
    """The satellite door's per-turn gate: during an enrollment every utterance
    is a cancellation, an answer, or guidance; it never reaches the model."""
    key = (ctx.ha_instance_id, ctx.satellite_id)
    with _lock:
        _prune()
        pending = _enrollments.get(key)
        if not pending:
            return None
        if not ctx.paired or pending['service_revision'] != ctx.service_revision \
                or pending['device_id'] != satellite(ctx).get('device_id'):
            _enrollments.pop(key, None)
            return None
        awaiting = pending.get('awaiting')
        phase = pending['phase']
    low = text.strip().lower().rstrip('.!?')
    if low == 'cancel voice setup':
        return cancel(key)
    if phase == 'confirm':
        return {'message': "Say the parent's PIN.", 'status': 'retry'}
    if awaiting:
        return answer(key, evidence, token=awaiting['token'], conversation_id=conversation_id)
    return {'message': 'Voice setup is in progress. Answer the question, or say cancel voice setup.', 'status': 'retry'}


def apply(ctx, evidence):
    """Run before intent/PIN parsing. A new speaker cannot spend old authority."""
    if not enabled(ctx):
        return ctx
    vector = evidence['vector'] if evidence else None
    with _lock:
        rows = [r for r in profiles() if usable_on(r, (ctx.ha_instance_id, ctx.satellite_id))]
    usable = bool(vector and evidence.get('seconds', 0) >= IDENTIFY_SECONDS)
    candidates = sorted(((score(vector, r['vector']), r['member_id']) for r in rows), reverse=True) if usable else []
    matched = candidates[0][1] if candidates and candidates[0][0] >= THRESHOLD \
        and (len(candidates) == 1 or candidates[0][0] - candidates[1][0] >= MARGIN) else None
    with identity._lock:
        key = (ctx.ha_instance_id, ctx.satellite_id)
        row = identity._sessions.get(key)
        if not row or row['generation'] != ctx.generation:
            return ctx
        if row.get('recognition_suppressed'):
            return replace(ctx, fingerprint=vector)
        anchor = row.get('speaker_anchor')
        references = [r['vector'] for r in rows if r['member_id'] == row.get('member_id')]
        # A PIN anchor is stronger continuity evidence than a stored template.
        references = [anchor] if anchor else references
        contradiction = usable and (bool(matched and matched != row.get('member_id'))
            or bool(references and max(score(vector, ref) for ref in references) < DIFFERENT))
        if (row['level'] == 'verified' or row.get('recognized')) and contradiction:
            identity._sessions[key] = row = identity._new_session(row.get('device_id'))
        greeting = None
        if matched and matched != row.get('member_id'):
            member = storage.get_member(matched)
            identity._sessions[key] = row = identity._new_session(row.get('device_id'))
            row.update(level='named', member_id=matched, role=member.get('role'), recognized=True)
            greeting = f"Hi {member.get('name')}."
        refreshed = identity.VoiceContext(ctx.ha_instance_id, ctx.satellite_id, ctx.request_id,
                    row['generation'], row['level'], row['member_id'], row['expires_at'], ctx.service_revision, ctx.paired)
        return replace(refreshed, fingerprint=vector, greeting=greeting)


def delete(member_id, key=None):
    with _lock:
        _save([r for r in _load() if not (r['member_id'] == member_id and (not key or r['key'] == list(key)))])
        for pending_key in list(_enrollments):
            if _enrollments[pending_key]['member_id'] == member_id:
                _enrollments.pop(pending_key, None)
    with identity._lock:
        for session_key, row in list(identity._sessions.items()):
            if row.get('member_id') == member_id:
                identity._sessions[session_key] = identity._new_session(row.get('device_id'))
    return status()


def status():
    with _lock:
        _prune()
        rows = profiles()
        return {'model_ready': model_ready(),
                'profiles': [{**{k: r[k] for k in ('member_id', 'key', 'created_at', 'calibrated')},
                              'provenance': r.get('provenance', 'satellite'),
                              'pooled': bool(r.get('pooled')),
                              'checks': r.get('checks') if isinstance(r.get('checks'), dict) else {}} for r in rows],
                'enrollments': [{'key': list(key), 'enrollment_id': p['id'], 'member_id': p['member_id'], 'step': p['step'] + 1,
                                 'question': current_question(p),
                                 'door': p['door'], 'phase': p['phase'], 'expires_at': p['expires_at']} for key, p in _enrollments.items()],
                'satellites': [{'key': list(key), **state} for key, state in _last.items()]}

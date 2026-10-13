"""Local CPU speaker evidence. Audio/observations/anchors never persist.

Templates live outside the general database and member JSON. Recognition
supplies a named lens, not a member credential or a payment approval.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import re
import threading
import time
import uuid

from services import storage, voice_identity as identity

MODEL = 'wespeaker_en_voxceleb_resnet34.onnx'
MODEL_SHA = '5ef208a9da1453335308a6b6f4e6dfbd7e183a38b604de0a57664f45d257fe94'
MODEL_URL = 'https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/' + MODEL
REVISION = 'wespeaker-resnet34:' + MODEL_SHA + ':sherpa-1.13.8'
THRESHOLD, MARGIN, CONTINUITY = .70, .12, .65
MAX_AUDIO = 1_000_000
PROMPTS = (
    'For my voice setup, our family has many things to do today and I want help keeping track of them.',
    'For my voice setup, please tell me what is on the calendar and which errands I can handle this afternoon.',
    'For my voice setup, I would like a reminder before I leave so I remember everything I need to bring.',
    'For my voice check, tomorrow morning I will review our plans before everyone heads out for the day.',
    'For my voice check, help me find a little time this evening to prepare for the rest of the week.',
)
_lock = threading.RLock()
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='voice-fingerprint')
_slot = threading.BoundedSemaphore(1)
_extractor = None
_observations = {}
_enrollments = {}
_last = {}


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
    """Drop disabled/deleted members and incompatible templates on every use."""
    with _lock:
        rows = _load()
        active = [r for r in rows if r.get('revision') == REVISION
                  and identity._active(storage.get_member(r.get('member_id')))]
        if rows != active:
            _save(active)
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


def extract(audio, metadata):
    import numpy as np
    if metadata.get('codec') != 'pcm' or metadata.get('format') != 'wav' \
            or metadata.get('bit_rate') != 16 or metadata.get('channel') != 1 \
            or metadata.get('sample_rate') not in (16000, 24000, 48000) or len(audio) % 2:
        raise ValueError('Recognition needs mono 16-bit PCM audio.')
    rate = metadata['sample_rate']
    samples = np.frombuffer(audio, dtype='<i2').astype('float32') / 32768
    if not rate * 1.2 <= len(samples) <= rate * 15:
        raise ValueError('Use a clear phrase between two and fifteen seconds.')
    frames = samples[:len(samples) // (rate // 50) * (rate // 50)].reshape(-1, rate // 50)
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    voiced_seconds = float(np.count_nonzero(rms > .008) / 50)
    if voiced_seconds < 1.2 or float(np.mean(np.abs(samples) >= .99)) > .03:
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
    if len(samples) >= rate * 5:
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
        if not enabled(ctx) and (ctx.ha_instance_id, ctx.satellite_id) not in _enrollments:
            raise ValueError('Start voice enrollment or enable recognition on this satellite first.')
    if not _slot.acquire(blocking=False):
        raise ValueError('Voice worker is busy; try again.')
    revision = identity._revision()
    started = time.monotonic()
    key = (ctx.ha_instance_id, ctx.satellite_id)

    def compute():
        try:
            return extract(audio, metadata)
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
        try:
            future = _pool.submit(compute)
        except Exception:
            _slot.release()
            raise
        _observations[oid] = {'key': (*key, metadata.get('device_id'), metadata['run_id'], metadata['utterance_id']),
                              'revision': revision, 'future': future, 'expires': time.time() + 60,
                              'enrollment_id': (_enrollments.get(key) or {}).get('id')}
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
        setup_phrase = pending and _clean_phrase(text) == _clean_phrase(PROMPTS[pending['step']])
    if 'future' in row:
        try:
            # Ordinary turns split 500ms: 100ms HA upload + 400ms inference.
            # Explicit setup phrases may wait 3s for the longer enrollment checks.
            vector, seconds = row['future'].result(timeout=3 if setup_phrase else .4)
        except Exception:
            return None
        row = {**row, 'vector': vector, 'seconds': seconds}
        row.pop('future', None)
    if row['revision'] != identity._revision() or not identity._paired(ctx.ha_instance_id, ctx.satellite_id, metadata.get('device_id')):
        return None
    return row


def _clean_phrase(text):
    return ' '.join(re.findall(r'[a-z]+', text.lower()))


def begin(ctx, member_id, consent_actor):
    if not ctx.paired or not identity._active(storage.get_member(member_id)):
        raise ValueError('Choose an enabled satellite and active family member.')
    if not model_ready():
        raise ValueError('Prepare the voice model first.')
    with _lock:
        _prune()
        if len(_enrollments) >= 16:
            raise ValueError('Too many pending enrollments.')
        _enrollments[(ctx.ha_instance_id, ctx.satellite_id)] = {
            'id': uuid.uuid4().hex, 'member_id': member_id, 'consent_actor': consent_actor,
            'device_id': satellite(ctx).get('device_id'), 'service_revision': ctx.service_revision,
            'samples': [], 'step': 0, 'expires_at': time.time() + 600}
    identity.recover(ctx.ha_instance_id, ctx.satellite_id)
    return status()


def enrollment_turn(text, ctx, evidence):
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
        if text.strip().lower().rstrip('.!?') == 'cancel voice setup':
            _enrollments.pop(key, None)
            return {'message': 'Voice setup cancelled.'}
        step = pending['step']
        if _clean_phrase(text) != _clean_phrase(PROMPTS[step]):
            return None  # unrelated conversation is never an enrollment sample
        if not evidence or evidence.get('enrollment_id') != pending['id'] or evidence['seconds'] < 4:
            return {'message': 'That sample was not usable. Speak the setup phrase clearly again, or check voice status on your phone.'}
        vector = evidence['vector']
        samples = pending['samples']
        if samples and any(score(vector, other) < CONTINUITY for other in samples):
            _enrollments.pop(key, None)
            return {'message': 'The samples did not sound consistent. Start voice setup again on your phone.'}
        if step < 3:
            samples.append(vector)
        reference = normalized([sum(v[i] for v in samples) for i in range(256)])
        if step >= 3:
            rivals = [r for r in profiles() if r['member_id'] != pending['member_id']]
            competing = max((score(vector, r['vector']) for r in rivals), default=-1)
            if score(vector, reference) < THRESHOLD or score(vector, reference) - competing < MARGIN:
                _enrollments.pop(key, None)
                return {'message': 'Voice recognition could not distinguish this check reliably. Leave recognition off and retry setup.'}
        pending['step'] += 1
        if pending['step'] < len(PROMPTS):
            return {'message': 'Sample accepted. Read the next phrase shown on your phone.'}
        member = storage.get_member(pending['member_id'])
        if not identity._active(member):
            _enrollments.pop(key, None)
            return {'message': 'That member is no longer active.'}
        rows = [r for r in profiles() if not (r['member_id'] == member['id'] and r['key'] == list(key))]
        rows.append({'member_id': member['id'], 'key': list(key), 'vector': reference,
                     'revision': REVISION, 'consent_actor': pending['consent_actor'], 'created_at': time.time(),
                     'checks': 2, 'calibrated': True})
        # A new rival can invalidate an older calibration; never silently retain it.
        for row in rows:
            if any(r['member_id'] != row['member_id'] and score(r['vector'], row['vector']) >= THRESHOLD - MARGIN for r in rows):
                row['calibrated'] = False
        _save(rows)
        _enrollments.pop(key, None)
        return {'message': 'Voice samples saved. Check recognition with your family, then enable it for this satellite on your phone.'}


def apply(ctx, evidence):
    """Run before intent/PIN parsing. A new speaker cannot spend old authority."""
    if not enabled(ctx):
        return ctx
    vector = evidence['vector'] if evidence else None
    with _lock:
        rows = [r for r in profiles() if r['key'] == [ctx.ha_instance_id, ctx.satellite_id] and r['calibrated']]
    candidates = sorted(((score(vector, r['vector']), r['member_id']) for r in rows), reverse=True) if vector else []
    matched = candidates[0][1] if candidates and candidates[0][0] >= THRESHOLD \
        and (len(candidates) == 1 or candidates[0][0] - candidates[1][0] >= MARGIN) else None
    with identity._lock:
        key = (ctx.ha_instance_id, ctx.satellite_id)
        row = identity._sessions.get(key)
        if not row or row['generation'] != ctx.generation:
            return ctx
        if row.get('recognition_suppressed'):
            return replace(ctx, fingerprint=vector)
        if row['level'] == 'verified':
            anchor = row.get('speaker_anchor')
            if vector and anchor and score(vector, anchor) >= CONTINUITY \
                    and (not matched or matched == row['member_id']):
                return replace(ctx, fingerprint=vector)
            identity._sessions[key] = row = identity._new_session(row.get('device_id'))
        elif row.get('recognized') and (not matched or matched != row.get('member_id')):
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
        _save([r for r in profiles() if not (r['member_id'] == member_id and (not key or r['key'] == list(key)))])
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
                'profiles': [{k: r[k] for k in ('member_id', 'key', 'created_at', 'checks', 'calibrated')} for r in rows],
                'enrollments': [{'key': list(key), 'enrollment_id': p['id'], 'member_id': p['member_id'], 'step': p['step'] + 1,
                                 'prompt': PROMPTS[p['step']], 'expires_at': p['expires_at']} for key, p in _enrollments.items()],
                'satellites': [{'key': list(key), **state} for key, state in _last.items()]}

"""Bounded transient phone audio through the household's existing HA providers."""
import io
import re
import shutil
import subprocess
import threading
import time
import wave

from services import ha_api

MAX_UPLOAD = 5_000_000
_cache = {}
_lock = threading.Lock()


def pipeline():
    with _lock:
        if _cache.get('expires', 0) > time.monotonic():
            return _cache['pipeline']
    chosen = ha_api._pick_argyle_pipeline(ha_api.ws_command('assist_pipeline/pipeline/list'))
    if not chosen:
        raise ValueError('Argyle speech is unavailable. Check the Home Assistant voice assistant.')
    with _lock:
        _cache.update(pipeline=chosen, expires=time.monotonic() + 300)
    return chosen


def _request(method, path, **kwargs):
    import requests
    base, token = ha_api._base_and_token()
    if not base:
        raise ValueError('Home Assistant speech is not connected. You can still type to Argyle.')
    try:
        response = requests.request(method, base + path, headers={'Authorization': 'Bearer ' + token,
                                    **kwargs.pop('headers', {})}, timeout=kwargs.pop('timeout', 12),
                                    allow_redirects=False, **kwargs)
        if not 200 <= response.status_code < 300:
            response.close()
            raise ValueError('The household speech provider is unavailable. Try again or use text.')
        return response
    except requests.RequestException:
        raise ValueError('The household speech provider could not be reached. Try again or use text.') from None


def pcm(audio, content_type):
    kind = content_type.split(';')[0].strip().lower()
    formats = {'audio/webm': 'matroska', 'audio/mp4': 'mov', 'audio/ogg': 'ogg',
               'audio/wav': 'wav', 'audio/x-wav': 'wav'}
    if kind not in formats or not audio or len(audio) > MAX_UPLOAD:
        raise ValueError('This recording format or size is not supported. Try again or use text.')
    if formats[kind] == 'wav':
        try:
            with wave.open(io.BytesIO(audio), 'rb') as sample:
                if sample.getnchannels() == 1 and sample.getsampwidth() == 2 and sample.getframerate() == 16000:
                    if sample.getnframes() > 15 * 16000:
                        raise ValueError('The recording exceeded fifteen seconds.')
                    if not sample.getnframes():
                        raise ValueError('The recording contained no audio.')
                    return sample.readframes(sample.getnframes())
        except (wave.Error, EOFError):
            raise ValueError('The recording was not usable. Please try again.') from None
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise ValueError('The phone audio decoder is unavailable. Use text while it is repaired.')
    try:
        decoded = subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-protocol_whitelist', 'pipe',
                                  '-f', formats[kind], '-i', 'pipe:0', '-map', '0:a:0',
                                  '-ac', '1', '-ar', '16000', '-t', '16', '-f', 's16le', 'pipe:1'],
                                 input=audio, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError('The recording could not be decoded. Please try again.') from None
    if decoded.returncode or not decoded.stdout or len(decoded.stdout) > 15 * 16000 * 2:
        raise ValueError('The recording was unusable or exceeded fifteen seconds.')
    return decoded.stdout


def transcribe(audio, content_type):
    raw = pcm(audio, content_type)
    chosen = pipeline()
    engine = chosen.get('stt_engine') or ''
    language = chosen.get('stt_language') or chosen.get('language') or 'en'
    if not re.fullmatch(r'[a-z0-9_.-]+', engine) or not re.fullmatch(r'[a-zA-Z0-9_-]+', language):
        raise ValueError('Choose a speech-to-text provider in the Argyle assistant.')
    # Calling the wrapper directly has no PipelineRun: it transcribes through
    # its real delegate without teeing/fingerprinting or inventing a satellite.
    with _request('GET', '/stt/' + engine) as response:
        support = response.json()
    required = {'formats': 'wav', 'codecs': 'pcm', 'sample_rates': 16000,
                'bit_rates': 16, 'channels': 1}
    if any(value not in support.get(key, []) for key, value in required.items()):
        raise ValueError('The Argyle transcription provider does not support phone audio.')
    header = f'format=wav;codec=pcm;sample_rate=16000;bit_rate=16;channel=1;language={language}'
    with _request('POST', '/stt/' + engine, data=raw,
                  headers={'Content-Type': 'application/octet-stream', 'X-Speech-Content': header}) as response:
        result = response.json()
    text = result.get('text')
    if result.get('result') != 'success' or not isinstance(text, str) or not text.strip():
        raise ValueError('I did not catch that. Tap the microphone to try again.')
    return text


def speak(text):
    chosen = pipeline()
    engine = chosen.get('tts_engine') or ''
    if not re.fullmatch(r'[a-z0-9_.-]+', engine):
        raise ValueError('Choose a text-to-speech voice in the Argyle assistant.')
    payload = {'engine_id': engine, 'message': text, 'cache': False,
               'language': chosen.get('tts_language') or chosen.get('language') or 'en'}
    if chosen.get('tts_voice'):
        payload['options'] = {'voice': chosen['tts_voice']}
    with _request('POST', '/tts_get_url', json=payload) as response:
        path = response.json().get('path') or ''
    if not re.fullmatch(r'/api/tts_proxy/[a-zA-Z0-9_.-]+', path):
        raise ValueError('The household voice returned an unavailable audio reference.')
    with _request('GET', path[4:], stream=True) as response:
        kind = response.headers.get('Content-Type', '').split(';')[0]
        if not kind.startswith('audio/'):
            raise ValueError('The household voice did not return playable audio.')
        chunks, size = [], 0
        for chunk in response.iter_content(32768):
            size += len(chunk)
            if size > MAX_UPLOAD:
                raise ValueError('The spoken reply exceeded its audio limit.')
            chunks.append(chunk)
    return b''.join(chunks), kind

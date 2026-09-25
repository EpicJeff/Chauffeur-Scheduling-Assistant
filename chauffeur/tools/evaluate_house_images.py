"""Opt-in paid Gemini exterior trial: two models, one request each, no retries.

Reads llm_gemini_paid_api_key from an explicit settings file, or --key-file.
No app imports, settings writes, provider fallback, or key logging. By default
only checks configuration and model access. --live generates the two images.
Use a new output directory; existing results are never regenerated implicitly.
"""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
MODELS = ('gemini-2.5-flash-image', 'gemini-3.1-flash-image')
INPUTS = (
    'chauffeur/static/house_hybrid/exterior-study/model-three-quarter.png',
    'docs/superpowers/specs/assets/2026-09-17-photo-farmhouse.jpg',
    'chauffeur/static/house_hybrid/living-habitat-day.png',
)


def paid_key(path):
    if path.suffix == '.sqlite3':
        with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
            rows = [json.loads(r[0]) for r in db.execute('SELECT data FROM settings')]
    else:
        document = json.loads(path.read_text(encoding='utf-8'))
        data = document.get('settings', document)
        if isinstance(data, dict) and 'llm_gemini_paid_api_key' in data:
            rows = [data]
        else:
            rows = list(data.values()) if isinstance(data, dict) else data
    return next((r.get('llm_gemini_paid_api_key') for r in rows
                 if isinstance(r, dict) and r.get('llm_gemini_paid_api_key')), '')


def request(key, model, payload=None):
    url = 'https://generativelanguage.googleapis.com/v1beta/models/' + model
    if payload is not None:
        url += ':generateContent'
    req = urllib.request.Request(url, headers={
        'x-goog-api-key': key, 'Content-Type': 'application/json'},
        data=json.dumps(payload).encode() if payload is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        # Do not print request objects, headers or provider bodies containing secrets.
        try:
            message = json.load(error).get('error', {}).get('message', '')
            message = re.sub(r'AIza[\w-]+', '[REDACTED]', message.replace(key, '[REDACTED]'))[:600]
        except Exception:
            message = ''
        raise RuntimeError('Provider HTTP ' + str(error.code) + ': ' + message) from None
    except Exception as error:
        raise RuntimeError(type(error).__name__ + ' during provider request') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    credentials = parser.add_mutually_exclusive_group(required=True)
    credentials.add_argument('--settings', type=Path)
    credentials.add_argument('--key-file', type=Path, help='Read a paid key without putting its value on the command line')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    try:
        key = args.key_file.read_text(encoding='utf-8-sig').strip() if args.key_file else paid_key(args.settings)
    except (OSError, ValueError, sqlite3.Error):
        parser.error('Could not read the supplied settings file')
    if not key:
        parser.error('No paid Gemini key configured in the supplied settings file')
    if not args.live:
        for model in MODELS:
            try:
                info = request(key, model)
            except RuntimeError as error:
                parser.error(str(error))
            print(json.dumps({'model': model, 'paid_key_present': True,
                              'methods': info.get('supportedGenerationMethods', [])}))
        return

    # Reserve the run before any paid call; even failures cannot auto-retry.
    try:
        args.out.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        parser.error('Output directory already exists; refusing to repeat paid calls')
    prompt_doc = (ROOT / 'docs/superpowers/reports/2026-09-24-personalized-exterior-prompts.md').read_text(encoding='utf-8')
    section = prompt_doc.split('## Combined model + photo treatment', 1)[1]
    prompt = re.search(r'```text\n(.*?)\n```', section, re.S).group(1)
    (args.out / 'prompt.txt').write_text(prompt + '\n', encoding='utf-8')
    parts = [{'text': prompt}]
    inputs = []
    for relative in INPUTS:
        raw = (ROOT / relative).read_bytes()
        mime = 'image/jpeg' if relative.endswith('.jpg') else 'image/png'
        parts.append({'inlineData': {'mimeType': mime, 'data': base64.b64encode(raw).decode()}})
        inputs.append({'path': relative, 'sha256': hashlib.sha256(raw).hexdigest()})
    report = {'api_version': 'v1beta', 'inputs': inputs, 'max_requests': 2, 'retries': 0, 'results': []}
    def save():
        (args.out / 'results.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    save()
    from PIL import Image
    for model in MODELS:
        image_config = {'aspectRatio': '3:2'}
        if model == 'gemini-3.1-flash-image':
            image_config['imageSize'] = '1K'
        config = {'responseModalities': ['TEXT', 'IMAGE'],
                  'imageConfig': image_config}
        entry = {'model': model, 'generation_config': config, 'status': 'started'}
        report['results'].append(entry)
        save()
        start = time.monotonic()
        try:
            response = request(key, model, {'contents': [{'role': 'user', 'parts': parts}],
                                            'generationConfig': config})
            entry.update(model_version=response.get('modelVersion'),
                         usage=response.get('usageMetadata'), images=[])
            for candidate in response.get('candidates', []):
                entry['finish_reason'] = candidate.get('finishReason')
                for part in candidate.get('content', {}).get('parts', []):
                    blob = part.get('inlineData')
                    if not blob or part.get('thought'):
                        continue
                    mime = blob.get('mimeType')
                    ext = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}.get(mime)
                    if not ext:
                        continue
                    raw = base64.b64decode(blob['data'], validate=True)
                    with Image.open(io.BytesIO(raw)) as image:
                        dimensions = list(image.size)
                        image.verify()
                    name = model + '-' + str(len(entry['images']) + 1) + ext
                    (args.out / name).write_bytes(raw)
                    entry['images'].append({'file': name, 'dimensions': dimensions,
                                             'sha256': hashlib.sha256(raw).hexdigest()})
            entry['status'] = 'ok' if entry['images'] else 'no_image'
        except Exception as error:
            entry.update(status='failed', error=str(error).replace(key, '[REDACTED]'))
        entry['seconds'] = round(time.monotonic() - start, 2)
        save()
        print(json.dumps(entry), flush=True)


if __name__ == '__main__':
    main()

"""Bounded scene-matched vehicle experiment: two paid edits, no retries.

Outputs full edits for review, not production-ready transparent cutouts. Never
called by presence updates. The approved exterior remains the immutable base.
"""
import argparse
import hashlib
import json
import time
from pathlib import Path
from PIL import Image
from generate_garage_bay import generate, MODEL


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--live', action='store_true', required=True)
    args = parser.parse_args()
    raw = args.base.read_bytes()
    key = args.key_file.read_text(encoding='utf-8-sig').strip()
    if not key: parser.error('Empty key')
    with Image.open(args.base) as im: mime = Image.MIME[im.format]
    args.out.mkdir(parents=True, exist_ok=False)
    shared = '''Edit this exact exterior photograph. Preserve camera, framing,
house, trees, driveway joints, road and ALL other pixels as closely as possible.
Add ONLY the requested vehicle and its physically correct contact and cast
shadows, subtle ground reflections. Match the late afternoon sunlight, scale,
lens perspective and photographic detail. No scenery changes, no people,
no added text, no crop, no camera move. Return the complete photograph, 3:2.
'''
    prompts = {
        'driveway': shared + '''Add one BLUE 2021 NISSAN MURANO parked on the
concrete driveway in front of the garage, wholly on concrete. Vehicle centered
at about x=72%, y=86%, fitting within x=57%-87%, y=74%-96%. Park with the
longitudinal axis aligned with the driveway approach to the garage, nose facing
out toward the street (lower left). Real blue painted body, black tires, chrome
trim, clear realistic windows reflecting this house and trees. Do not block or
change garage doors. No other vehicles.''',
        'bus': shared + '''Add one realistic yellow American school bus stopped
on the ASPHALT ROAD in the lower left foreground, parallel to the diagonal curb,
nose pointing toward the lower right. Bus mostly in lower left, approximately
x=0%-31%, y=78%-99%. All tires must touch asphalt, never sidewalk or grass. It is
acceptable for its rear to extend beyond the left edge. Correct scale relative
to house and road. No other vehicles.'''
    }
    report = {'model': MODEL, 'base_sha256': hashlib.sha256(raw).hexdigest(),
              'max_requests': 2, 'retries': 0, 'results': []}
    for name, prompt in prompts.items():
        (args.out / (name + '-prompt.txt')).write_text(prompt, encoding='utf-8')
        entry = {'stage': name}; report['results'].append(entry)
        started = time.monotonic()
        try:
            result_mime, data, metadata = generate(key, prompt, (mime, raw))
            suffix = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}[result_mime]
            filename = name + suffix
            (args.out / filename).write_bytes(data)
            with Image.open(args.out / filename) as result:
                alpha = result.getextrema()[-1] if result.mode == 'RGBA' else None
            entry.update(metadata, status='ok', file=filename, alpha_extrema=alpha)
        except Exception as error:
            entry.update(status='failed', error=str(error).replace(key, '[REDACTED]'))
        entry['seconds'] = round(time.monotonic() - started, 2)
        (args.out / 'results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(entry), flush=True)
        if entry['status'] != 'ok': break


if __name__ == '__main__':
    main()

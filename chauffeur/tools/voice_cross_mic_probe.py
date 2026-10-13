"""Read-only Jeff/room/phone transfer experiment; no enrollment or vector output.

Supply five consented phone recordings (three train, two held out), two fresh
satellite recordings, and the existing private template file. Source files are
temporary experiment artifacts owned by the caller; delete them after use.
Decoding needs ffmpeg unless input is supported mono 16-bit PCM WAV.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import voice_fingerprint as fp


def decode(path):
    if not path.is_file() or path.stat().st_size > 10_000_000:
        raise ValueError('A recording is missing or exceeds 10 MB.')
    try:
        with wave.open(str(path), 'rb') as recording:
            rate = recording.getframerate()
            if recording.getnchannels() == 1 and recording.getsampwidth() == 2 \
                    and rate in (16000, 24000, 48000):
                if recording.getnframes() > rate * 15:
                    raise ValueError('Recordings must be at most fifteen seconds.')
                return recording.readframes(recording.getnframes()), rate
    except (wave.Error, EOFError):
        pass
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise ValueError('ffmpeg is required for encoded/stereo/unsupported-rate recordings.')
    result = subprocess.run(
        [ffmpeg, '-nostdin', '-v', 'error', '-i', str(path.resolve()), '-map', '0:a:0',
         '-ac', '1', '-ar', '16000', '-t', '16', '-f', 's16le', 'pipe:1'],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20, check=False)
    if result.returncode or len(result.stdout) > 16000 * 2 * 15:
        raise ValueError('A recording could not be decoded or exceeded fifteen seconds.')
    return result.stdout, 16000


def embed(path, *, training=False):
    audio, rate = decode(path)
    started = time.monotonic()
    vector, seconds = fp.extract(audio, {'codec': 'pcm', 'format': 'wav',
                                       'bit_rate': 16, 'channel': 1, 'sample_rate': rate},
                                 enrollment=training)
    if seconds < (4 if training else fp.IDENTIFY_SECONDS):
        raise ValueError('A recording lacks sufficient voiced audio for this comparison.')
    return vector, {'voiced_seconds': round(seconds, 2),
                    'inference_ms': round((time.monotonic() - started) * 1000)}


def compare(vector, reference, rivals):
    if vector is None:
        return {'usable': False, 'passes': False}
    if reference is None:
        return {'usable': True, 'passes': False, 'reason': 'No consistent phone training reference.'}
    own = fp.score(vector, reference)
    competing = max((fp.score(vector, other) for other in rivals), default=None)
    margin = own - competing if competing is not None else None
    return {'usable': True, 'score': round(own, 4), 'margin': round(margin, 4) if margin is not None else None,
            'passes': own >= fp.THRESHOLD and (margin is None or margin >= fp.MARGIN)}


def transfer_report(phone, room, reference, rivals):
    training = phone[:3]
    consistent = all(v is not None for v in training) and all(fp.score(a, b) >= fp.CONTINUITY
                     for i, a in enumerate(training) for b in training[i + 1:])
    centroid = fp.normalized([sum(v[i] for v in training) for i in range(256)]) if consistent else None
    old_to_phone = [compare(v, reference, rivals) for v in phone]
    held_phone = [compare(v, centroid, rivals) for v in phone[3:]]
    fresh_room = [compare(v, centroid, rivals) for v in room]
    return {'threshold': fp.THRESHOLD, 'required_margin': fp.MARGIN,
            'rival_count': len(rivals), 'multi_member_margin_measured': bool(rivals),
            'training_consistent': consistent,
            'kitchen_reference_to_phone': old_to_phone,
            'phone_reference_to_held_out_phone': held_phone,
            'phone_reference_to_fresh_kitchen': fresh_room,
            'all_sample_scores_pass': consistent and all(r['passes'] for r in old_to_phone + held_phone + fresh_room),
            'candidate_set': 'all supplied compatible calibrated kitchen templates; may include inactive members',
            'pilot_only': True, 'profiles_changed': False}


def sample(path, *, training=False):
    try:
        vector, quality = embed(path, training=training)
        return vector, {'usable': True, **quality}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        # Include every failed sample in the report without printing input paths.
        return None, {'usable': False, 'reason': 'Audio quality/duration or decoding failed.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--templates', type=Path, required=True)
    parser.add_argument('--member', required=True)
    parser.add_argument('--installation', required=True)
    parser.add_argument('--satellite', required=True)
    parser.add_argument('--phone', type=Path, nargs=5, required=True)
    parser.add_argument('--room', type=Path, nargs=2, required=True)
    args = parser.parse_args()
    if hashlib.sha256(args.model.read_bytes()).hexdigest() != fp.MODEL_SHA:
        raise ValueError('Voice model checksum mismatch.')
    if args.templates.stat().st_size > 1_000_000:
        raise ValueError('Template input exceeds its experiment limit.')
    rows = json.loads(args.templates.read_text(encoding='utf-8'))
    key = [args.installation, args.satellite]
    rows = [r for r in rows if r.get('revision') == fp.REVISION and r.get('calibrated') and r.get('key') == key]
    target = [r for r in rows if r.get('member_id') == args.member]
    if len(target) != 1:
        raise ValueError('Choose exactly one compatible calibrated member/satellite reference.')
    reference = fp.normalized(target[0]['vector'])
    rivals = [fp.normalized(r['vector']) for r in rows if r.get('member_id') != args.member]
    import sherpa_onnx
    fp._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(args.model), num_threads=1, provider='cpu'))
    phone = [sample(path, training=i < 3) for i, path in enumerate(args.phone)]
    room = [sample(path) for path in args.room]
    report = transfer_report([r[0] for r in phone], [r[0] for r in room], reference, rivals)
    report['phone_audio'] = [r[1] for r in phone]
    report['kitchen_audio'] = [r[1] for r in room]
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        raise SystemExit('Experiment input/decoding failed. Check private inputs, model and audio limits; no profile was changed.') from None

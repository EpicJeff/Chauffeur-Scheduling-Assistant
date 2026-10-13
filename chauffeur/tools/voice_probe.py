"""Synthetic CPU/memory probe; never claims to measure recognition accuracy.

Run on the add-on host after preparing its model:
    python tools/voice_probe.py
Or use a checksum-pinned downloaded model on a development workstation:
    python tools/voice_probe.py --model /path/to/wespeaker_en_voxceleb_resnet34.onnx
No sample audio, templates or fingerprints are saved or printed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import voice_fingerprint as fp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, default=fp.root() / fp.MODEL)
    args = parser.parse_args()
    if hashlib.sha256(args.model.read_bytes()).hexdigest() != fp.MODEL_SHA:
        raise SystemExit('Voice model checksum mismatch.')
    import numpy as np
    import sherpa_onnx
    fp._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(args.model), num_threads=1, provider='cpu'))
    metadata = {'format': 'wav', 'codec': 'pcm', 'bit_rate': 16, 'channel': 1, 'sample_rate': 16000}
    cases = []
    for seconds in (2, 7, 14):
        t = np.arange(seconds * 16000) / 16000
        samples = sum(.025 / n * np.sin(2 * np.pi * 120 * n * t) for n in range(1, 8))
        audio = (samples * 32768).astype('<i2').tobytes()
        timings = []
        for _ in range(5):
            started = time.monotonic()
            vector, voiced = fp.extract(audio, metadata)
            timings.append(round((time.monotonic() - started) * 1000))
        cases.append({'seconds': seconds, 'median_ms': statistics.median(timings),
                      'max_ms': max(timings), 'dimensions': len(vector), 'energy_seconds': voiced})
    memory = None
    if sys.platform != 'win32':
        import resource
        memory = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    print(json.dumps({'synthetic_performance_only': True, 'model_sha256': fp.MODEL_SHA,
                      'cases': cases, 'peak_process_mb': memory}, indent=2))


if __name__ == '__main__':
    main()

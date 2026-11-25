"""Full release-card capture. Requires Chromium; no skip on a missing browser."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
NAMES = ['my-day', 'plan', 'wall-board', 'twin-overview', 'twin-editor', 'twin-gutters', 'twin-awning-editor']


def run():
    with tempfile.TemporaryDirectory(prefix='chauffeur_demo_shots_') as out:
        started = time.monotonic()
        result = subprocess.run([sys.executable, 'chauffeur/tools/demo_capture.py',
                                 '--timeout', '170', '--out', out],
                                cwd=ROOT, env=dict(os.environ, CAPTURE_OUT=out),
                                text=True, capture_output=True, timeout=180)
        elapsed = time.monotonic() - started
        assert result.returncode == 0, result.stderr
        assert result.stderr == '', result.stderr
        assert sorted(p.name for p in Path(out).iterdir()) == sorted(n + '.png' for n in NAMES)
        for name in NAMES:
            with Image.open(Path(out) / (name + '.png')) as shot:
                assert shot.format == 'PNG'
                assert shot.size == ((780, 1688) if name == 'my-day' else (1600, 900)), (name, shot.size)
        assert elapsed < 180, elapsed
        print(f'6/6 demo shots passed in {elapsed:.2f}s')


if __name__ == '__main__':
    run()

"""Make a forward-playing transparent loop from Blender RGBA frames.

Run with the application Python (Pillow and NumPy), with FFmpeg on PATH:
  python chauffeur/tools/encode_fire_loop.py scratch/log-surface-fire-varied/frames <output.webm>
"""
import argparse
import json
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image


def premultiply(frame):
    frame = frame.astype(np.float32) / 255
    frame[..., :3] *= frame[..., 3:4]
    return frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('frames', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--fps', type=int, default=24)
    parser.add_argument('--overlap', type=int, default=24, help='Overlap in frames')
    parser.add_argument('--pattern', default='fire_*.png', help='Rendered frame filename pattern')
    args = parser.parse_args()
    frames = [np.array(Image.open(p).convert('RGBA')) for p in sorted(args.frames.glob(args.pattern))]
    overlap = args.overlap
    if not 2 <= overlap < len(frames) / 2:
        parser.error('Overlap must be at least two frames and less than half the sequence')
    result = [f.copy() for f in frames[overlap:]]
    for i in range(overlap):
        t = i / (overlap - 1)
        weight = t * t * (3 - 2 * t)  # Smooth entry/exit, zero slope at both ends.
        a = premultiply(frames[-overlap+i])
        b = premultiply(frames[i])
        mixed = a * (1-weight) + b * weight
        # Blend coverage-weighted color: straight-RGBA fades darken thin flames.
        mixed[..., :3] = np.divide(mixed[..., :3], mixed[..., 3:4],
                                   out=np.zeros_like(mixed[..., :3]), where=mixed[..., 3:4] > 0)
        result[-overlap+i] = np.clip(np.rint(mixed * 255), 0, 255).astype(np.uint8)
    # The loop boundary is two consecutive simulation frames, never a reset.
    assert np.array_equal(premultiply(result[-1]), premultiply(frames[overlap-1]))
    assert np.array_equal(result[0], frames[overlap])
    height, width = result[0].shape[:2]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgba',
                    '-s', f'{width}x{height}', '-r', str(args.fps), '-i', 'pipe:0', '-an',
                    '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p', '-crf', '22', '-b:v', '0',
                    '-deadline', 'good', '-cpu-used', '4', '-auto-alt-ref', '0', str(args.output)],
                   input=b''.join(f.tobytes() for f in result), check=True)
    differences = [float(np.abs(premultiply(a)-premultiply(b)).mean())
                   for a,b in zip(result, result[1:]+result[:1])]
    print(json.dumps({'frames': len(result), 'duration': len(result)/args.fps,
                      'overlapFrames': overlap, 'boundaryDifference': differences[-1],
                      'medianFrameDifference': float(np.median(differences)),
                      'maxFrameDifference': max(differences)}, indent=2))


if __name__ == '__main__':
    main()

"""Extract a reviewed scene patch, keeping contact shadows and local ground.

The polygon is manually reviewed in source coordinates. This is NOT automatic
vehicle segmentation: do not reuse it for another generated image or camera.
"""
import argparse
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter


def compose(source, polygon, output, feather=6):
    with Image.open(source) as original:
        image = original.convert('RGBA')
    # Pad before feathering so shapes touching the frame remain opaque there.
    pad = feather * 3
    mask = Image.new('L', (image.width + pad * 2, image.height + pad * 2))
    points = [(x + pad, y + pad) for x, y in polygon]
    ImageDraw.Draw(mask).polygon(points, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(feather)).crop((pad,pad,pad+image.width,pad+image.height))
    image.putalpha(mask)
    image.save(output, lossless=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--polygon', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    compose(args.source, json.loads(args.polygon.read_text()), args.out)

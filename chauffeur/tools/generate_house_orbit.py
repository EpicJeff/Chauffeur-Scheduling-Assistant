"""Generate eight saved exterior views, explicitly using a paid Nano Banana 2 key.

One request per angle, no retries. Existing run directories are refused.
The source captures are frozen reviewed assets, never live household data.
"""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import time
from PIL import Image
from evaluate_house_images import request, ROOT

MODEL = 'gemini-3.1-flash-image'
LABELS = ['Front right', 'Front', 'Front left', 'Left side',
          'Rear left', 'Rear', 'Rear right', 'Right side']
PROMPT = '''Create one coherent photorealistic architectural exterior, landscape 3:2.
This is one of eight fixed camera views of the SAME personalized farmhouse.
IMAGE 1 is the exact rendered model for THIS VIEW. Match its camera direction,
elevation, framing, building silhouette, roof ridges, story heights, proportions,
doors, windows, garage bays and yard layout. It is the authority for geometry.
IMAGE 2 is the real front photograph: use its greige board-and-batten, cream/white
masonry, white trim, charcoal shingles, dark standing-seam porch roof, dark wood
glazed front doors and muted blue-gray shutters as surface references only.
IMAGE 3 is the furnished living room: use its warm natural photographic quality,
tactile materials, restrained colors and soft shadows as the shared art direction.
IMAGE 4 is an earlier photographic treatment: match its natural material finish
and level of realism ONLY. Do not copy its camera or its invented side windows.
Convert all low-poly foliage into real trees and shrubs. Replace the floating
lot and blue void with continuous ground, a wooded residential setting and sky.
Keep the model's fence, walks, planting areas, street and right-side driveway
in their world positions. Same warm afternoon and season across the series.
Do not add windows, doors, floors, dormers, chimneys, roof changes or projections.
Blank walls in IMAGE 1 MUST remain blank. The right front gable is low with no
upper window. Use only openings visible in the model for this viewpoint, even
when the photo or photographic treatment has more. On rear views DO NOT copy
the front entrance or front gables to the rear. Preserve any model rear openings.
Keep side-entry garage doors where visible in the model and connected to the
driveway. Do not turn garage doors into windows. Preserve all eight-view model
relationships, even if you would prefer a different design. Photographic detail,
realistic window reflections, siding grain, shingles and contact shadows.
No floating platform, toy appearance, polygonal trees, people, cars, text, signs,
watermarks, UI, cutaway, collage or room objects outside. Show the whole house.
Requested viewpoint: {label}, orbit stop {angle}. Image 1 determines the view.
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--angles', type=int, nargs='+', default=list(range(8)))
    parser.add_argument('--model-only', action='store_true', help='Correct camera drift using only the model capture')
    parser.add_argument('--appearance-reference', type=Path)
    parser.add_argument('--prompt-file', type=Path)
    parser.add_argument('--model-last', action='store_true', help='Put the target camera capture after appearance references')
    args = parser.parse_args()
    if len(set(args.angles)) != len(args.angles) or any(a not in range(8) for a in args.angles):
        parser.error('Angles must be unique integers from 0 to 7')
    if bool(args.appearance_reference) != bool(args.prompt_file) or (args.model_only and args.appearance_reference):
        parser.error('Use appearance-reference and prompt-file together, without model-only')
    key = args.key_file.read_text(encoding='utf-8-sig').strip()
    if not key:
        parser.error('Paid key file is empty')
    captures = ROOT/'docs/superpowers/reports/assets/house-orbit-2026-09-24'
    common = [ROOT/'docs/superpowers/specs/assets/2026-09-17-photo-farmhouse.jpg',
              ROOT/'chauffeur/static/house_hybrid/living-habitat-day.png',
              ROOT/'chauffeur/static/house_hybrid/exterior-study/nano-banana-2.jpg']
    prompt = PROMPT
    if args.model_only:
        common = []
        prompt = '''Photorealistically re-render the attached house model. EXACT SAME CAMERA.
Preserve every wall, roof ridge, opening, projection and building silhouette.
Do not rotate the house or move the camera. This is the {label} view, stop {angle}.
The model geometry and camera are absolute authority, including blank walls.
Use warm greige board-and-batten siding, white masonry and trim, charcoal asphalt
roof shingles, dark metal porch roofing, blue-gray shutters and natural dark wood
doors where shown. Realistic glass reflections, tactile materials and soft contact
shadows. Replace polygon trees with real trees in the same positions. Replace the
blue void with a wooded neighborhood and sky, extending the ground naturally.
Warm afternoon daylight, restrained natural colors, architectural photography.
Do not invent openings, chimneys, dormers, extra floors, porches or roof changes.
Preserve side-entry garage doors exactly where shown. No UI, text, people, cars,
floating platforms or toy appearance. Landscape 3:2. Show the entire house.
'''
    if args.appearance_reference:
        common = [args.appearance_reference.resolve()]
        prompt = args.prompt_file.read_text(encoding='utf-8')
    for path in [captures/f'model-{a}.png' for a in args.angles] + common:
        if not path.is_file(): parser.error('Missing reference: '+str(path))
    if args.out.exists(): parser.error('Run directory exists; refusing to repeat paid calls')
    args.out.mkdir(parents=True)
    (args.out/'prompt.txt').write_text(prompt, encoding='utf-8')
    report = {'model': MODEL, 'max_requests': len(args.angles), 'automatic_retries': 0, 'views': []}
    def save():
        (args.out/'results.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    save()
    for angle in args.angles:
        label = LABELS[angle]
        paths = [captures/f'model-{angle}.png'] + common
        if args.model_last:
            paths = common + [captures/f'model-{angle}.png']
        parts = [{'text': prompt.format(angle=angle, label=label)}]
        entry = {'angle': angle, 'label': label, 'status': 'started', 'inputs': []}
        for path in paths:
            raw = path.read_bytes()
            parts.append({'inlineData': {'mimeType':'image/png' if path.suffix=='.png' else 'image/jpeg',
                                          'data':base64.b64encode(raw).decode()}})
            entry['inputs'].append({'path':path.relative_to(ROOT).as_posix(), 'sha256':hashlib.sha256(raw).hexdigest()})
        config = {'responseModalities':['TEXT','IMAGE'], 'imageConfig':{'aspectRatio':'3:2','imageSize':'1K'}}
        entry['generation_config'] = config
        report['views'].append(entry)
        save()
        start = time.monotonic()
        try:
            response = request(key, MODEL, {'contents':[{'role':'user','parts':parts}], 'generationConfig':config})
            entry.update(model_version=response.get('modelVersion'), usage=response.get('usageMetadata'))
            outputs = [p['inlineData'] for c in response.get('candidates',[]) for p in c.get('content',{}).get('parts',[])
                       if p.get('inlineData') and not p.get('thought')]
            if len(outputs)!=1: raise ValueError('Expected exactly one final image')
            blob = outputs[0]
            ext = {'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp'}[blob['mimeType']]
            raw = base64.b64decode(blob['data'], validate=True)
            with Image.open(io.BytesIO(raw)) as picture:
                entry['dimensions'] = list(picture.size)
                picture.verify()
            filename = f'view-{angle}'+ext
            (args.out/filename).write_bytes(raw)
            entry.update(status='ok', file=filename, sha256=hashlib.sha256(raw).hexdigest())
        except Exception as error:
            entry.update(status='failed', error=str(error).replace(key,'[REDACTED]'))
        entry['seconds'] = round(time.monotonic()-start,2)
        save()
        print(json.dumps({k:entry[k] for k in ('angle','label','status','seconds')}),flush=True)


if __name__ == '__main__':
    main()

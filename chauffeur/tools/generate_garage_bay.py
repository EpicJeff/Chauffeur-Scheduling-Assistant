"""Bounded Gemini edit: one assigned vehicle bay in a supplied, fixed garage.

Explicit paid key and --live required. One call only, no retries; completed
assets are reused by the browser, never generated during presence changes.
"""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import time
from PIL import Image
from evaluate_house_images import request

MODEL = 'gemini-3.1-flash-image'


def occupied_prompt(vehicle, color, bay):
    center = '27%' if bay == 'left' else '73%'
    return f'''Edit the supplied empty two-car garage photograph. Park exactly ONE
{color} {vehicle} in the {bay.upper()} parking bay ONLY, centered horizontally at
x={center} of the full image. Other bay MUST remain completely empty and unchanged.
Back the car in STRAIGHT, longitudinal axis parallel to side walls, front facing
the open garage doorway, wheels straight, bumper parallel to back wall. This is
ordinary garage parking, not a rotated three-quarter showroom pose. Vehicle must
fit completely inside its half of the garage, with realistic side clearances and
no part crossing the center floor joint. Preserve the original centered camera:
do not recenter camera on the car or crop the other bay. Scale the SUV naturally
to the garage, about 2 meters wide in its 3.5 meter wide bay. Accurate model/year
body and {color} painted panels, natural glass, rubber and trim. Integrate actual
garage light, window/ceiling reflections, tire contact shadows, underbody occlusion
and subtle floor reflections, all in the occupied bay. Keep ALL architecture,
floor joints, cabinets, lighting, wall objects, camera and framing exactly aligned
with the source. Modify only the vehicle and its local shadows/reflections. Same
3:2 output. No people, no text, no second car, no scenery changes.'''


def generate(key, prompt, source=None):
    parts = [{'text': prompt}]
    if source:
        parts.append({'inlineData':{'mimeType': source[0], 'data':base64.b64encode(source[1]).decode()}})
    response = request(key, MODEL, {'contents':[{'role':'user','parts':parts}],
        'generationConfig':{'responseModalities':['TEXT','IMAGE'],
                            'imageConfig':{'aspectRatio':'3:2','imageSize':'1K'}}})
    outputs = [p['inlineData'] for c in response.get('candidates', [])
               for p in c.get('content', {}).get('parts', []) if p.get('inlineData') and not p.get('thought')]
    if len(outputs) != 1:
        raise ValueError('Expected one final image')
    result = outputs[0]
    raw = base64.b64decode(result['data'], validate=True)
    with Image.open(io.BytesIO(raw)) as image:
        size = image.size; image.verify()
    return result['mimeType'], raw, {'dimensions':size,'usage':response.get('usageMetadata'),
        'model_version':response.get('modelVersion'), 'sha256':hashlib.sha256(raw).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--base', type=Path, required=True, help='Approved empty garage; never generated per household')
    parser.add_argument('--vehicle', required=True, help='Year, make and model from the user')
    parser.add_argument('--color', required=True)
    parser.add_argument('--bay', choices=['left','right'], default='left')
    parser.add_argument('--cluster-only', action='store_true', help='Generate a dashboard lean-in instead of the occupied bay')
    parser.add_argument('--live', action='store_true', required=True)
    args = parser.parse_args()
    base_raw = args.base.read_bytes()
    with Image.open(io.BytesIO(base_raw)) as base_image:
        base_mime = Image.MIME[base_image.format]; base_image.verify()
    key = args.key_file.read_text(encoding='utf-8-sig').strip()
    if not key: parser.error('Empty paid key')
    try: args.out.mkdir(parents=True, exist_ok=False)
    except FileExistsError: parser.error('Run directory exists; refusing repeat paid calls')
    report = {'model':MODEL, 'max_requests':1, 'retries':0, 'vehicle':args.vehicle,
              'color':args.color, 'bay':args.bay, 'base_sha256':hashlib.sha256(base_raw).hexdigest(), 'results':[]}
    source = (base_mime, base_raw)
    stages = [('occupied',occupied_prompt(args.vehicle,args.color,args.bay))]
    if args.cluster_only:
        stages = [('cluster', f'''Photorealistic close-up from the driver's seat of a
{args.color} {args.vehicle} parked in a warm residential garage. Landscape 3:2.
Use the supplied garage as the parked environment visible through the windscreen. Camera square-on to the instrument cluster, slightly above the steering wheel,
natural close lean-in view. Focus on the actual driver instrument display behind
the wheel, not the infotainment screen. The large rectangular digital instrument
screen must be UNLIT blank near-black, unobstructed, front-on without perspective
skew, spanning approximately x=20% to 80%, y=30% to 58% of the image. No text,
gauges, icons or numbers anywhere on screen: live UI will be placed there later.
Steering wheel visible along bottom foreground BELOW the display, never crossing
or obscuring the screen. Real stitched leather, dark dashboard texture, believable
glass reflections, warm light from the garage entrance. Softly blurred garage
cabinetry visible through windscreen at top. Parked domestic vehicle interior,
not driving, not a car advertisement. No people, hands, labels or watermarks.''')]
    for name, prompt in stages:
        (args.out/(name+'-prompt.txt')).write_text(prompt,encoding='utf-8')
        entry = {'stage':name,'status':'started'}; report['results'].append(entry)
        def save():
            (args.out/'results.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        save(); start = time.monotonic()
        try:
            mime, raw, metadata = generate(key,prompt,source)
            ext = {'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp'}[mime]
            filename = name+ext; (args.out/filename).write_bytes(raw)
            entry.update(metadata, status='ok', file=filename)
            source = (mime,raw)
        except Exception as error:
            entry.update(status='failed',error=str(error).replace(key,'[REDACTED]'))
        entry['seconds'] = round(time.monotonic()-start,2); save()
        print(json.dumps({k:entry[k] for k in ['stage','status','seconds']}),flush=True)
        if entry['status'] != 'ok': break


if __name__ == '__main__':
    main()

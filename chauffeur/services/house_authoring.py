"""Bounded, resumable object-authoring jobs. Generated content is data, never code.

The worker's render callback owns the browser; this service owns validation,
the API budget, checkpoints and evidence. No automatic production publication.
"""
import base64
import json
import math
import re
import time
from pathlib import Path

PALETTE = {'wood': '#926744', 'oak': '#c39b67', 'ivory': '#eee5d3',
           'ink': '#292d30', 'brass': '#b99a57', 'sage': '#58978b', 'steel': '#858b8b'}
BRIEF = """Create a freestanding acoustic guitar on a stable floor stand for a cozy
stylized dollhouse. Recognizable curved guitar silhouette, waist, sound hole,
bridge, six strings, frets, neck, headstock and tuning pegs. Warm wood, ivory
binding and restrained brass. No neon colors. Match the furnished house image.
Origin at floor center, Y up, front faces +Z. Fit within x +/-0.72,
y -0.03..2.8, z +/-0.65, including stand. Do not build a pedestal or floor.
All parts must visibly connect. Detail must remain readable from a room camera.
One scene unit is 0.75m; the existing house stylizes instruments larger for touch.
Return ONLY a JSON object with version:1 and parts:[...]. At most 48 definitions,
140 rendered parts total. Keep the recipe compact: use repeat for strings/frets.
Each part has type, material, position:[x,y,z], rotation:[x,y,z] in radians.
Materials: wood, oak, ivory, ink, brass, sage, steel (house palette, no custom hex).
Available types and additional fields:
box: size:[width,height,depth]. Edges automatically get small bevels.
sphere: size:[width,height,depth] (diameters, ellipsoid allowed).
cylinder: size:[topRadius,bottomRadius,height], axis local Y.
rod: a:[x,y,z], b:[x,y,z], radius; omit position/rotation (endpoints are absolute).
shape: points:[[x,y],...] ordered polygon, depth, optional holes:[{x,y,radius}].
Shape has 6..64 polygon vertices; use many contour points for smooth guitar curves.
Shape extrudes around local z=0, with subtle bevels. Do not repeat final vertex.
Any part may include repeat:{count:N,step:[dx,dy,dz]}. This produces N copies,
starting at the part's position, each translated by i*step; N is 1..24.
For rods, repeat translates both endpoints. Use this for strings, frets and pegs.
Do not put many overlapping filled shapes in the sound hole. Use a real hole.
Dimensions positive; cylinder radii may be zero individually. No scripts, URLs,
textures, text, external assets, executable loops, references or other fields.
"""


def _numbers(value, count, limit=4):
    if not isinstance(value, list) or len(value) != count:
        raise ValueError('wrong vector length')
    if any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > limit for v in value):
        raise ValueError('invalid or unbounded number')
    return value


def validate(recipe):
    if not isinstance(recipe, dict) or set(recipe) != {'version', 'parts'} or type(recipe['version']) is not int or recipe['version'] != 1:
        raise ValueError('recipe must contain version 1 and parts only')
    parts = recipe['parts']
    if not isinstance(parts, list) or not 1 <= len(parts) <= 48:
        raise ValueError('part budget exceeded')
    expanded = 0
    allowed = {'box': {'size'}, 'sphere': {'size'}, 'cylinder': {'size'},
               'rod': {'a', 'b', 'radius'}, 'shape': {'points', 'depth', 'holes'}}
    for p in parts:
        if not isinstance(p, dict) or p.get('type') not in allowed or p.get('material') not in PALETTE:
            raise ValueError('unknown primitive or material')
        kind = p['type']
        if set(p) - ({'type', 'material', 'position', 'rotation', 'repeat'} | allowed[kind]):
            raise ValueError('unknown recipe fields')
        repeated = p.get('repeat', {'count':1,'step':[0,0,0]})
        if not isinstance(repeated,dict) or set(repeated) != {'count','step'}:
            raise ValueError('invalid repeated detail')
        if type(repeated['count']) is not int or not 1 <= repeated['count'] <= 24:
            raise ValueError('repeat count out of bounds')
        _numbers(repeated['step'],3,2)
        expanded += repeated['count']
        if expanded > 140:
            raise ValueError('expanded part budget exceeded')
        if kind == 'rod':
            if 'position' in p or 'rotation' in p:
                raise ValueError('rod uses endpoints only')
            a, b = _numbers(p.get('a'), 3), _numbers(p.get('b'), 3)
            radius = _numbers([p.get('radius')], 1)[0]
            if not 0.001 <= radius <= 0.15 or a == b:
                raise ValueError('invalid rod')
        else:
            _numbers(p.get('position'), 3)
            _numbers(p.get('rotation', [0, 0, 0]), 3, 6.284)
            if kind in ('box', 'sphere', 'cylinder'):
                size = _numbers(p.get('size'), 3)
                if kind == 'cylinder':
                    if min(size) < 0 or size[2] <= 0 or max(size[:2]) <= 0:
                        raise ValueError('invalid cylinder')
                elif min(size) <= 0:
                    raise ValueError('dimensions must be positive')
            else:
                points = p.get('points')
                if not isinstance(points, list) or not 6 <= len(points) <= 64:
                    raise ValueError('contour vertex budget exceeded')
                for point in points:
                    _numbers(point, 2)
                if not 0.005 <= _numbers([p.get('depth')], 1)[0] <= 1:
                    raise ValueError('invalid shape depth')
                holes = p.get('holes', [])
                if not isinstance(holes, list) or len(holes) > 3:
                    raise ValueError('hole budget exceeded')
                for hole in holes:
                    if not isinstance(hole, dict) or set(hole) != {'x', 'y', 'radius'}:
                        raise ValueError('invalid hole')
                    _numbers([hole['x'], hole['y']], 2)
                    if not 0.005 <= _numbers([hole['radius']], 1)[0] <= 0.5:
                        raise ValueError('invalid hole radius')
    return recipe


def _save(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')
    tmp.replace(path)


def create(directory, model):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'job.json'
    if path.exists():
        job = json.loads(path.read_text(encoding='utf-8'))
        if job['model'] != model:
            raise ValueError('resume must use the original model')
        return job
    job = {'version': 1, 'model': model, 'status': 'queued', 'calls': [], 'renders': {},
           'created_at': time.time(), 'brief': BRIEF, 'call_limit': 3}
    _save(path, job)
    return job


def run(directory, model, request, render):
    """request(stage,prompt,images,metrics)->dict; render(label,recipe)->evidence.

    A reserved call survives a crash: uncertain calls are never silently retried.
    A quota failure leaves a resumable job; no pool fallback or paid key is used.
    """
    directory = Path(directory)
    lock = directory / '.worker.lock'
    directory.mkdir(parents=True, exist_ok=True)
    try:
        fd = lock.open('x')
    except FileExistsError:
        raise RuntimeError('Job locked; verify the previous worker stopped before removing .worker.lock')
    try:
        fd.close()
        job = create(directory, model)
        path = directory / 'job.json'
        def save():
            _save(path, job)
        def capture(label, recipe):
            if label not in job['renders']:
                evidence = render(label, recipe)
                job['renders'][label] = evidence
                save()
            return job['renders'][label]
        def call(stage, prompt, image_paths):
            prior = next((c for c in job['calls'] if c['stage'] == stage and c['status'] == 'complete'), None)
            if prior:
                return json.loads((directory / (stage + '.json')).read_text(encoding='utf-8'))
            if any(c['status'] == 'running' for c in job['calls']):
                raise RuntimeError('Interrupted API call has unknown outcome; inspect job before resuming')
            if len(job['calls']) >= job['call_limit']:
                job['status'] = 'budget_exhausted'
                save()
                raise RuntimeError('Three-call budget exhausted')
            c = {'stage': stage, 'model':job['model'], 'status': 'running', 'metrics': {}, 'started_at': time.time()}
            (directory / (stage + '-prompt.txt')).write_text(prompt, encoding='utf-8')
            job['calls'].append(c)
            job['status'] = stage
            save()
            images = [{'mime': 'image/png', 'b64': base64.b64encode(Path(p).read_bytes()).decode('ascii')} for p in image_paths]
            try:
                result = request(stage, prompt, images, c['metrics'])
                if not isinstance(result, dict) or result.get('error'):
                    raise RuntimeError('API request did not produce a usable object')
                _save(directory / (stage + '.json'), result)
                c['status'] = 'complete'
                return result
            except Exception as e:
                c['status'] = 'failed'
                job['status'] = 'deferred'
                # Never persist raw API exceptions (they may include the key URL).
                c['error'] = type(e).__name__
                raise RuntimeError('Authoring API call failed; see sanitized job status') from None
            finally:
                c['seconds'] = round(time.time() - c['started_at'], 2)
                save()
        if job['status'] in ('review_required', 'rejected', 'abandoned'):
            return job
        base = capture('baseline', None)
        empty = capture('context', {'version': 1, 'parts': []})
        design = call('design', job['brief'], [empty['room_image']])
        try:
            validate(design)
            candidate = capture('candidate', design)
        except ValueError as e:
            candidate = {'gate_pass': False, 'validation_error': str(e)}
            job['renders']['candidate'] = candidate
            save()
        # The judge receives images and measurements, not the maker's reasoning.
        prompt = ('Judge two guitar assets in the same house. A is authored baseline; B is candidate. '
                  'Score EACH on 0..5: silhouette, construction, materials, scene_fit, touch_readability. '
                  '5 means matches this house quality, 3 usable with visible compromises, 1 unacceptable. '
                  'Return {baseline:{scores:{...}},candidate:{scores:{...}},blockers:[strings],'
                  'changes:[specific geometric fixes]}. Do not infer hidden geometry. '
                  'Be strict about disconnected necks, filled sound holes, floating stands, missing strings. '
                  'Measurements: ' + json.dumps({'A': base, 'B': candidate}))
        images = [base['room_image'], base['detail_image']]
        if candidate.get('room_image'):
            images += [candidate['room_image'], candidate['detail_image']]
        review = call('review', prompt, images)
        if len(job['calls']) >= job['call_limit']:
            job['status'] = 'review_required' if candidate.get('gate_pass') else 'rejected'
            job['budget_note'] = 'Failed request consumed correction slot; candidate reviewed without correction.'
            save()
            return job
        correction = call('correction', job['brief'] + '\nRevise this recipe:\n' + json.dumps(design) +
                          '\nJudge feedback:\n' + json.dumps(review), images)
        try:
            validate(correction)
            final = capture('final', correction)
            job['status'] = 'review_required' if final['gate_pass'] else 'rejected'
        except ValueError as e:
            job['status'] = 'rejected'
            job['validation_error'] = str(e)
        save()
        return job
    finally:
        lock.unlink(missing_ok=True)


def gemini_request(api_key, model):
    from services.llm import _call_llm_json
    if not re.fullmatch(r'gemini-[a-z0-9.\-]+', model):
        raise ValueError('explicit Gemini model required')
    def request(stage, prompt, images, metrics):
        metrics['request_parameters'] = {'thinking_level':'low', 'strict_json':True,
                                         'max_output_tokens':18000 if stage != 'review' else 4000}
        return _call_llm_json('gemini', '', api_key, model,
                              'You are an object authoring worker. Return only valid JSON.', prompt,
                              temperature=0.2, timeout_s=300, images=images, metrics=metrics,
                              max_output_tokens=18000 if stage != 'review' else 4000,
                              transient_retries=0, thinking_level='low', strict_json=True)
    return request

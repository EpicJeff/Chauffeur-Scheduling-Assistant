"""The setup reads of slice 1b-i on real recorded answers (plan
.superpowers/sdd/2026-11-07-house-editor-slice-1b-i, Task 9). Claude's answers
for the plot plan read, the photo parts read and the sheet roles read with a
part hint were recorded once on the user's own documents by
`python tools/twin_live.py record-place` and are replayed here through the
real readers by stubbing only model_pools.call_pool_json.

Fixtures (each {answer, usage, model}) under fixtures/twin_reads/recorded/claude/:
plot-place.json, photo_parts.json, sheet_roles-hint.json. While they do not
exist every scenario fails with "fixture missing: <path>".

The sources are blank PDFs and photos; this checks that the recorded shapes
parse and drive the place steps, not the drawing.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_place_replay.py
"""
import base64
import copy
import io
import json
import os
import shutil
import sys
import tempfile
import traceback

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_place_replay_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import model_pools, storage  # noqa: E402
from services import twin_build as tb  # noqa: E402
from services import twin_cost as tc  # noqa: E402
from services import twin_place as tp  # noqa: E402
from services import twin_place_reads as tpr  # noqa: E402
from services import twin_reads  # noqa: E402
from services import twin_store as ts  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RECORDED = os.path.join(HERE, 'fixtures', 'twin_reads', 'recorded', 'claude')
PLOT = os.path.join(RECORDED, 'plot-place.json')
PHOTOS = os.path.join(RECORDED, 'photo_parts.json')
ROLES = os.path.join(RECORDED, 'sheet_roles-hint.json')
PRICED = 'anthropic:claude-opus-5-5'


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _record(path):
    if not os.path.isfile(path):
        raise AssertionError(f'fixture missing: {path}')
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    check(isinstance(data, dict) and set(data) >= {'answer', 'usage', 'model'},
          f'{path} is not a recorded {{answer, usage, model}} file')
    check(isinstance(data['answer'], dict) and data['answer'], f'{path} has no answer object')
    return data


def _answer(path):
    return copy.deepcopy(_record(path)['answer'])


def _fresh():
    storage.patch_settings({'house_twin': None, 'house_twin_cost': None})
    shutil.rmtree(ts.DATA_DIR, ignore_errors=True)
    tb._forget()


def _pdf(pages=1, w=1224, h=792):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(w, h)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _photo(w=64, h=48):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (w, h), (120, 140, 160)).save(buf, format='PNG')
    return buf.getvalue()


class Pool:
    """Stands in for call_pool_json: one recorded answer for one read kind."""

    def __init__(self, kind, answer):
        self.kind, self.answer, self.calls = kind, answer, []

    def __call__(self, tier, api_key, system_prompt, user_prompt, **kw):
        kind = next(k for k, v in twin_reads.PROMPTS.items() if v == system_prompt)
        self.calls.append({'kind': kind, 'context': json.loads(user_prompt)['context'],
                           'images': len(kw.get('images') or [])})
        check(kind == self.kind, f'expected one {self.kind} read, got {kind}')
        if kw.get('usage') is not None:
            kw['usage'].append({'model': PRICED, 'input_tokens': 3000, 'output_tokens': 500,
                                'images': len(kw.get('images') or []), 'prompt_chars': len(user_prompt),
                                'max_output_tokens': kw.get('max_output_tokens') or 0})
        return copy.deepcopy(self.answer)


class stubbed:
    def __init__(self, pool):
        self.pool = pool

    def __enter__(self):
        storage.patch_settings({'llm_provider': 'anthropic', 'llm_anthropic_api_key': 'k'})
        self.original = model_pools.call_pool_json
        model_pools.call_pool_json = self.pool
        return self.pool

    def __exit__(self, *exc):
        model_pools.call_pool_json = self.original


def scenario_plot_answer_places_a_lot():
    answer = _answer(PLOT)
    fragment, problems = twin_reads.parse('plot', answer)
    check(problems == [], ('the recorded plot answer parses clean', problems))
    check(twin_reads._usable('plot', fragment, problems), 'the recorded plot answer is usable')
    _fresh()
    house = ts.save_source('drawing', 'house.pdf', _pdf(1))
    plot = ts.save_source('drawing', 'plot.pdf', _pdf(3), part='lot')
    ts.set_page_roles([
        {'source': house, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None, 'building': 'house'},
        {'source': plot, 'page': 1, 'role': 'plot', 'level': None, 'box': None, 'building': 'lot'}])
    with stubbed(Pool('plot', answer)) as pool:
        lot = tpr.read_plot()
    check(len(pool.calls) == 1 and pool.calls[0]['images'] == 1, pool.calls)
    read = lot['read']
    check(not read['fragment'].get('problems'), ('the real reader keeps no problems', read['fragment'].get('problems')))
    check(len(read['suggestions']) >= 2, ('at least two suggestions', len(read['suggestions'])))
    check(all(len(s['outline']) >= 3 and s['state'] == 'open' for s in read['suggestions']), read['suggestions'])
    check(len(read['lot']) >= 3, ('a lot outline', read['lot']))
    edge = read['street_edge']
    check(isinstance(edge, list) and len(edge) == 2 and all(isinstance(i, int) and 0 <= i < len(read['lot']) for i in edge)
          and edge[0] != edge[1], ('a lot with a street edge', edge))
    check(tc.total() > 0 and all(e['stage'] == 'step:plot' for e in tc.entries()), 'the read was metered')
    placed = tpr.confirm_placement(None, [])
    placement = placed['placement']
    check(placement and placement['confirmed'] is True and placement['street_edge'] == edge, placement)
    check(len(placement['outline']) >= 3, placement)


def scenario_photo_parts_answer_parses_and_reads():
    answer = _answer(PHOTOS)
    fragment, problems = twin_reads.parse('photo_parts', answer)
    check(problems == [], ('the recorded photo answer parses clean', problems))
    check(twin_reads._usable('photo_parts', fragment, problems), 'the recorded photo answer is usable')
    check(fragment.get('photos') or fragment.get('shells'), fragment)
    _fresh()
    house = ts.save_source('drawing', 'house.pdf', _pdf(1))
    ts.set_page_roles([{'source': house, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None,
                        'building': 'house'}])
    sources = [ts.save_source('photo', f'p{i}.png', _photo(), part='lot') for i in range(4)]
    with stubbed(Pool('photo_parts', answer)) as pool:
        read = tpr.suggest_photos()
    check(len(pool.calls) == 1 and pool.calls[0]['images'] == len(sources), pool.calls)
    check(isinstance(read['photos'], list) and isinstance(read['shells'], list), read)
    check(all(p['source'] in sources for p in read['photos']), read['photos'])


def scenario_sheet_roles_hint_rows_fit_their_part():
    answer = _answer(ROLES)
    fragment, problems = twin_reads.parse('sheet_roles', answer)
    check(problems == [], ('the recorded sheet roles answer parses clean', problems))
    rows = fragment['pages']
    check(rows, 'the recorded sheet roles answer has rows')
    _fresh()
    source = ts.save_source('drawing', 'plans.pdf', _pdf(max(r['page'] for r in rows)))
    images = [{'mime': 'image/png', 'b64': base64.b64encode(_photo()).decode('ascii')}]
    context = {'part': {'id': 'house', 'name': 'Main house', 'kind': 'main_house'},
               'parts': [{'id': 'house', 'name': 'Main house'}, {'id': tp.LOT, 'name': 'Lot'}]}
    with stubbed(Pool('sheet_roles', answer)) as pool:
        read = twin_reads.read('sheet_roles', images, context, run='place', step='sheet_roles')
    check(len(pool.calls) == 1 and 'error' not in read, read)
    check(not read.get('problems') and len(read['pages']) == len(rows), read)
    fitting = set(tp.BUILDING_ROLES) - {'skip'}
    for row in rows:
        check(1 <= row['page'] <= max(r['page'] for r in rows), row)
        if row.get('elsewhere') is None:
            # A row with no elsewhere is about the source's own part, a building.
            check(row['role'] in fitting, ('a role that fits a building', row))
        else:
            check(isinstance(row['elsewhere'], str) and row['elsewhere'], row)
            check(row['role'] in set(tp.LOT_ROLES) | set(tp.BUILDING_ROLES), row)
    check(source, 'a source was saved')


if __name__ == '__main__':
    failed = 0
    for fn in (scenario_plot_answer_places_a_lot,
               scenario_photo_parts_answer_parses_and_reads,
               scenario_sheet_roles_hint_rows_fit_their_part):
        try:
            fn()
            print('  ok ', fn.__name__)
        except Exception:
            failed += 1
            print('  FAIL', fn.__name__)
            traceback.print_exc()
    sys.exit(1 if failed else 0)

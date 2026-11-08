"""The live harness for the house editor (plan
docs/superpowers/plans/2026-11-07-house-editor-slice-1.md Task 12), offline:
the budget stops spending before a request, answers are recorded where the
replay tests find them, keys are never printed, and the comparison scores a
model against the hand-read Lot 58 answer key. No model is called here; a
fake reader stands in for twin_reads.read.

Run from chauffeur/:  python tests/test_twin_live_tool.py
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_live_tool_'))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

KEY = os.path.join(ROOT, 'tests', 'fixtures', 'twin_lot58_key.json')
FIXTURES = os.path.join(ROOT, 'tests', 'fixtures', 'twin_reads')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _tool():
    spec = importlib.util.spec_from_file_location('twin_live', os.path.join(ROOT, 'tools', 'twin_live.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pdf(pages=3):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(1224, 792)
    path = os.path.join(tempfile.mkdtemp(prefix='twin_live_pdf_'), 'lot58.pdf')
    doc.save(path)
    return path


def _keys():
    d = tempfile.mkdtemp(prefix='twin_live_keys_')
    for name in ('gemini_paid_api_key.txt', 'claude_api_key.txt'):
        with open(os.path.join(d, name), 'w', encoding='utf-8') as f:
            f.write('sk-SECRET-' + name)
    return d


class Reader:
    def __init__(self):
        self.calls = []

    def __call__(self, kind, images, context, *, run, step):
        from services import twin_cost
        self.calls.append(kind)
        twin_cost.record(f'step:{kind}', [{'model': next(iter(twin_cost.PRICES)), 'input_tokens': 2000,
                                            'output_tokens': 400, 'images': 1, 'prompt_chars': 10,
                                            'max_output_tokens': 4096}], run)
        with open(os.path.join(FIXTURES, f'{kind}.json'), encoding='utf-8') as f:
            return json.load(f)


def scenario_providers_and_reads_are_pinned():
    tool = _tool()
    check(set(tool.PROVIDERS) >= {'gemini', 'claude'}, tool.PROVIDERS)
    check(tool.PROVIDERS['claude']['llm_provider'] == 'anthropic'
          and tool.PROVIDERS['claude']['setting'] == 'llm_anthropic_api_key', tool.PROVIDERS['claude'])
    check(tool.PROVIDERS['gemini']['setting'] == 'llm_gemini_paid_api_key', tool.PROVIDERS['gemini'])
    check([r['kind'] for r in tool.COMPARE_READS] == ['outline', 'walls', 'walls', 'roof'], tool.COMPARE_READS)


def scenario_a_tiny_budget_makes_no_request():
    tool = _tool()
    reader = Reader()
    out = tempfile.mkdtemp(prefix='twin_live_out_')
    rows = tool.compare(_pdf(), budget=0.01, models=['gemini', 'claude'], key_dir=_keys(), out_dir=out,
                        key_path=KEY, reader=reader)
    check(reader.calls == [], reader.calls)
    check(all(r.get('stopped') == 'budget' for r in rows), rows)


def scenario_compare_records_scores_and_never_prints_keys():
    tool = _tool()
    reader = Reader()
    out = tempfile.mkdtemp(prefix='twin_live_out_')
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        rows = tool.compare(_pdf(), budget=3.0, models=['gemini', 'claude'], key_dir=_keys(), out_dir=out,
                            key_path=KEY, reader=reader)
        tool.print_table(rows)
    check(reader.calls == ['outline', 'walls', 'walls', 'roof'] * 2, reader.calls)
    for model in ('gemini', 'claude'):
        for name in ('outline-1.json', 'walls-2.json', 'walls-3.json', 'roof-4.json'):
            check(os.path.isfile(os.path.join(out, model, name)), (model, name, os.listdir(os.path.join(out, model))))
    row = rows[0]
    for field in ('model', 'cost', 'dimension_error_ft', 'outline_rms_ft', 'walls', 'roof_sections', 'roof_kinds'):
        check(field in row, (field, row))
    check(row['cost'] > 0 and row['walls'] == 10 and row['roof_sections'] == 3, row)
    check('SECRET' not in printed.getvalue(), 'keys never printed')


def scenario_the_budget_counts_what_this_run_spent():
    tool = _tool()
    reader = Reader()
    out = tempfile.mkdtemp(prefix='twin_live_out_')
    from services import twin_cost
    one_read = twin_cost.price(next(iter(twin_cost.PRICES)), 2000, 400)[0]
    rows = tool.compare(_pdf(), budget=one_read * 2.5, models=['gemini'], key_dir=_keys(), out_dir=out,
                        key_path=KEY, reader=reader, ceiling=lambda kind: one_read)
    check(len(reader.calls) == 2 and rows[0].get('stopped') == 'budget', (reader.calls, rows))


class ExactReader(Reader):
    """Answers the outline with the answer key itself, drawn at 70 ft = 0.5 page width."""

    def __init__(self, wings=2):
        super().__init__()
        self.wings = wings

    def __call__(self, kind, images, context, *, run, step):
        answer = super().__call__(kind, images, context, run=run, step=step)
        if kind == 'outline':
            with open(KEY, encoding='utf-8') as f:
                key = json.load(f)
            s = 70.0 / 2550
            pts = [[(x / s + 510) / 5100, (3000 - y / s) / 3300] for x, y in key['l1_outline_ft']]
            answer = {'dimension': {'a': [0.1, 0.97], 'b': [0.6, 0.97], 'feet': 70.0}, 'outline': pts,
                      'wings': [{'name': 'garage', 'box': [0.45, 0.5, 0.62, 0.92]},
                                {'name': 'main', 'box': [0.1, 0.2, 0.5, 0.92]}][:self.wings],
                      'confidence': 0.9, 'why': ''}
        return answer


def scenario_a_perfect_outline_scores_zero():
    tool = _tool()
    rows = tool.compare(_pdf(), budget=3.0, models=['gemini'], key_dir=_keys(),
                        out_dir=tempfile.mkdtemp(prefix='twin_live_out_'), key_path=KEY, reader=ExactReader())
    check(rows[0]['dimension_error_ft'] < 0.2 and rows[0]['outline_rms_ft'] < 0.2, rows[0])


def scenario_one_wing_still_reads_walls_and_roof():
    tool = _tool()
    reader = ExactReader(wings=1)
    rows = tool.compare(_pdf(), budget=3.0, models=['gemini'], key_dir=_keys(),
                        out_dir=tempfile.mkdtemp(prefix='twin_live_out_'), key_path=KEY, reader=reader)
    check(reader.calls == ['outline', 'walls', 'walls', 'roof'], reader.calls)
    check(rows[0]['roof_sections'] == 3, rows[0])


def scenario_the_table_shows_the_key_and_the_default_data_dir_is_scratch():
    tool = _tool()
    rows = tool.compare(_pdf(), budget=3.0, models=['gemini'], key_dir=_keys(),
                        out_dir=tempfile.mkdtemp(prefix='twin_live_out_'), key_path=KEY, reader=ExactReader())
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        tool.print_table(rows, key_path=KEY)
    text = printed.getvalue()
    check('key' in text.lower() and '70' in text and '5-9' in text, text)
    data_dir = os.path.abspath(tool.default_data_dir())
    check(not data_dir.startswith(os.path.abspath(ROOT)), data_dir)


class PlaceReader:
    """Stands in for twin_reads.read for record-place: every read costs exactly
    $0.40 on the ledger (100000 input tokens at $4 per million) and echoes the
    provider key into its answer, as a leaky provider error might."""

    def __init__(self, secret):
        self.calls, self.secret = [], secret

    def __call__(self, kind, images, context, *, run, step):
        from services import twin_cost
        self.calls.append({'kind': kind, 'images': len(images), 'context': context})
        twin_cost.record(f'step:{kind}', [{'model': 'anthropic:claude-opus-5-5', 'input_tokens': 100000,
                                            'output_tokens': 0}], run)
        with open(os.path.join(FIXTURES, f'{kind}.json'), encoding='utf-8') as f:
            answer = json.load(f)
        answer['why'] = 'echoed ' + self.secret
        return answer


def _jpgs(count=2):
    from PIL import Image
    d = tempfile.mkdtemp(prefix='twin_live_photos_')
    paths = []
    for i in range(count):
        path = os.path.join(d, f'p{i}.jpg')
        Image.new('RGB', (64, 48), (120, 140, 160)).save(path, format='JPEG')
        paths.append(path)
    return paths


def scenario_record_place_budget():
    """record_place(sheets, plot_page, photos, budget, models, *, key_dir, out_dir, reader, ceiling)
    makes the plot read, the photo_parts read, then the sheet_roles read, stops before
    any read whose estimate would pass the budget, writes {answer, usage, model} files
    under <out>/<model>/ (plot-place.json, photo_parts.json, sheet_roles-hint.json),
    redacts keys, prints the spend, and returns one row per model like compare."""
    import re
    tool = _tool()
    check(hasattr(tool, 'record_place'), 'tools/twin_live.py has no record_place (the record-place subcommand)')
    keys = _keys()
    secret = 'sk-SECRET-claude_api_key.txt'
    reader = PlaceReader(secret)
    out = tempfile.mkdtemp(prefix='twin_live_place_out_')
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        rows = tool.record_place(_pdf(3), 2, _jpgs(2), 1.0, ['claude'], key_dir=keys, out_dir=out,
                                 reader=reader, ceiling=lambda kind: 0.40)
    kinds = [c['kind'] for c in reader.calls]
    check(kinds == ['plot', 'photo_parts'], ('two reads, the third refused', kinds))
    check(len(rows) == 1 and rows[0]['model'] == 'claude' and rows[0].get('stopped') == 'budget', rows)
    check(abs(rows[0]['cost'] - 0.80) < 0.005, rows[0])
    check(reader.calls[0]['images'] == 1 and reader.calls[1]['images'] == 2, reader.calls)
    destination = os.path.join(out, 'claude')
    check(sorted(os.listdir(destination)) == ['photo_parts.json', 'plot-place.json'], os.listdir(destination))
    texts = []
    for name in ('plot-place.json', 'photo_parts.json'):
        with open(os.path.join(destination, name), encoding='utf-8') as f:
            text = f.read()
        texts.append(text)
        saved = json.loads(text)
        check(set(saved) == {'answer', 'usage', 'model'}, (name, sorted(saved)))
        check(isinstance(saved['answer'], dict) and saved['usage'] and saved['model'], (name, saved['model']))
    for text in texts:
        check('SECRET' not in text and not re.search(r'\bsk-|sk-ant-|AIza', text), 'a key was written to a fixture')
    shown = printed.getvalue()
    check('spent' in shown.lower() and '0.8' in shown, ('the printed spend is reported', shown))
    check('SECRET' not in shown, 'keys never printed')


class ImagePlaceReader(PlaceReader):
    def __init__(self):
        super().__init__('offline-placeholder')
        self.image_data = []

    def __call__(self, kind, images, context, *, run, step):
        self.image_data.append(images)
        return super().__call__(kind, images, context, run=run, step=step)


def _check_place_parts(reader):
    expected = {'house': ('Main house', 'main_house'),
                'pool_house': ('Pool house', 'pool_house'), 'lot': ('Lot', 'lot')}
    for call in reader.calls:
        if call['kind'] in ('photo_parts', 'sheet_roles'):
            parts = call['context']['parts']
            check({p['id']: (p['name'], p['kind']) for p in parts} == expected, parts)
        if call['kind'] == 'sheet_roles':
            check(call['context']['part']['id'] == 'house', call)


def scenario_record_place_separate_plot():
    from pathlib import Path
    from unittest import mock
    import pypdfium2 as pdfium
    from services import model_pools, twin_store

    sheets = Path(_pdf(2))
    plot_path = sheets.with_name('separate-plot.pdf')
    with pdfium.PdfDocument.new() as doc:
        doc.new_page(300, 600)
        doc.save(str(plot_path))
    sheet_source = twin_store.save_source('drawing', sheets.name, sheets.read_bytes(),
                                          content_type='application/pdf')
    plot_source = twin_store.save_source('drawing', plot_path.name, plot_path.read_bytes(),
                                         content_type='application/pdf')
    sheet_crop = twin_store.crop(sheet_source, 1, [0, 0, 1, 1])
    plot_crop = twin_store.crop(plot_source, 1, [0, 0, 1, 1])
    check(sheet_crop['b64'] != plot_crop['b64'], 'test PDFs must render differently')

    tool, reader = _tool(), ImagePlaceReader()
    out = tempfile.mkdtemp(prefix='twin_live_separate_plot_')
    with mock.patch.object(model_pools, 'call_pool_json', side_effect=AssertionError('provider call')):
        rows = tool.record_place(sheets, 1, _jpgs(4), 2.0, ['claude'], key_dir=_keys(),
                                 out_dir=out, reader=reader, ceiling=lambda kind: 0.40,
                                 plot_path=plot_path)
    check(not rows[0]['errors'], rows)
    check([c['kind'] for c in reader.calls] == ['plot', 'photo_parts', 'sheet_roles'], reader.calls)
    check(reader.image_data[0] == [{'mime': plot_crop['mime'], 'b64': plot_crop['b64']}],
          'plot read must receive the separate plot page image')
    check(reader.image_data[2] == twin_store.source_images(sheet_source),
          'sheet_roles must receive only the plans PDF pages')
    check(reader.calls[1]['images'] == 4, 'four photos remain supported')
    _check_place_parts(reader)

    with mock.patch.object(tool, 'record_place', return_value=rows) as record:
        check(tool.main(['record-place', '--sheets', str(sheets), '--plot', str(plot_path),
                         '--plot-page', '1', '--budget', '2', '--models', 'claude']) == 0,
              'separate plot CLI failed')
        check(record.call_args.kwargs['plot_path'] == plot_path, record.call_args)
        check(record.call_args.args[2] == [], record.call_args)


def scenario_record_place_without_photos():
    from pathlib import Path
    from unittest import mock
    from services import model_pools, twin_store

    tool, reader = _tool(), ImagePlaceReader()
    sheets = Path(_pdf(2))
    source = twin_store.save_source('drawing', sheets.name, sheets.read_bytes(),
                                    content_type='application/pdf')
    expected = twin_store.crop(source, 2, [0, 0, 1, 1])
    out = tempfile.mkdtemp(prefix='twin_live_no_photos_')
    with mock.patch.object(model_pools, 'call_pool_json', side_effect=AssertionError('provider call')):
        rows = tool.record_place(sheets, 2, [], 1.0, ['claude'], key_dir=_keys(), out_dir=out,
                                 reader=reader, ceiling=lambda kind: 0.40)
    check([c['kind'] for c in reader.calls] == ['plot', 'sheet_roles'], reader.calls)
    check(reader.image_data[0] == [{'mime': expected['mime'], 'b64': expected['b64']}],
          'without --plot, the plot page still comes from the sheets PDF')
    check(not rows[0]['errors'] and abs(rows[0]['cost'] - 0.8) < 0.005, rows)
    check(any('photo_parts' in note and 'skip' in note.lower()
              for note in rows[0].get('notes', [])), rows)
    check(sorted(os.listdir(os.path.join(out, 'claude'))) ==
          ['plot-place.json', 'sheet_roles-hint.json'], 'no photo_parts file should be written')
    _check_place_parts(reader)
    for photo_args in ([], ['--photos']):
        with mock.patch.object(tool, 'record_place', return_value=rows) as record:
            check(tool.main(['record-place', '--sheets', str(sheets), '--plot-page', '2',
                             '--budget', '1', '--models', 'claude'] + photo_args) == 0,
                  'no-photo CLI failed')
            check(record.call_args.args[2] == [], record.call_args)


def scenario_record_place_refuses_dev_data():
    from pathlib import Path
    from unittest import mock
    import builtins

    tool = _tool()
    original_import = builtins.__import__
    imports = []

    def no_services(name, *args, **kwargs):
        if name == 'services' or name.startswith('services.'):
            imports.append(name)
            raise AssertionError('services must not import before dev-data refusal')
        return original_import(name, *args, **kwargs)

    forbidden = [Path(ROOT) / 'data', Path(ROOT) / 'data' / 'nested',
                 Path(ROOT) / 'data' / '..' / 'data' / 'nested']
    for target in forbidden:
        for from_cli in (False, True):
            with mock.patch.dict(os.environ):
                if not from_cli:
                    os.environ['CHAUFFEUR_DATA_DIR'] = str(target)
                with mock.patch('builtins.__import__', side_effect=no_services):
                    if from_cli:
                        error = io.StringIO()
                        with contextlib.redirect_stderr(error):
                            code = tool.main(['record-place', '--sheets', 'missing.pdf',
                                              '--plot-page', '1', '--budget', '1',
                                              '--models', 'claude', '--data-dir', str(target)])
                        check(code == 1 and '(ValueError)' in error.getvalue(), error.getvalue())
                    else:
                        try:
                            tool.record_place('missing.pdf', 1, [], 1.0, ['claude'],
                                              key_dir='unused', out_dir='unused',
                                              reader=lambda *a, **k: check(False, 'reader called'))
                        except ValueError as exc:
                            check('chauffeur/data' in str(exc), str(exc))
                        else:
                            raise AssertionError('record_place must raise ValueError for dev data')
    check(imports == [], imports)


if __name__ == '__main__':
    for fn in (scenario_providers_and_reads_are_pinned,
               scenario_a_tiny_budget_makes_no_request,
               scenario_compare_records_scores_and_never_prints_keys,
               scenario_the_budget_counts_what_this_run_spent,
               scenario_a_perfect_outline_scores_zero,
               scenario_one_wing_still_reads_walls_and_roof,
               scenario_the_table_shows_the_key_and_the_default_data_dir_is_scratch,
               scenario_record_place_separate_plot,
               scenario_record_place_without_photos,
               scenario_record_place_refuses_dev_data,
               scenario_record_place_budget):
        fn()
        print('  ok ', fn.__name__)

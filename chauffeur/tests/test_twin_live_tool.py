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


if __name__ == '__main__':
    for fn in (scenario_providers_and_reads_are_pinned,
               scenario_a_tiny_budget_makes_no_request,
               scenario_compare_records_scores_and_never_prints_keys,
               scenario_the_budget_counts_what_this_run_spent):
        fn()
        print('  ok ', fn.__name__)

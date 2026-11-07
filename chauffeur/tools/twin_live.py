"""Local, budgeted twin comparisons. Running compare explicitly spends money.

Offline callers can supply a reader and a per-kind ceiling. No model request
is made at import time; the build command is reserved for the later slice.
"""
import argparse
import json
import math
import os
from pathlib import Path
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / 'tests' / 'fixtures' / 'twin_reads' / 'recorded'
DEFAULT_KEY = ROOT / 'tests' / 'fixtures' / 'twin_lot58_key.json'

PROVIDERS = {
    'gemini': {'llm_provider': 'gemini', 'key_file': 'gemini_paid_api_key.txt',
               'setting': 'llm_gemini_paid_api_key'},
    'claude': {'llm_provider': 'anthropic', 'key_file': 'claude_api_key.txt',
               'setting': 'llm_anthropic_api_key'},
    'openai': {'llm_provider': 'openai', 'key_file': 'openai_api_key.txt',
               'setting': 'llm_openai_api_key'},
}

COMPARE_READS = [
    {'kind': 'outline', 'page': 1, 'box': [0, 0, 1, 1]},
    {'kind': 'walls', 'page': 1, 'wing': 0},
    {'kind': 'walls', 'page': 1, 'wing': 1},
    {'kind': 'roof', 'page': 3, 'box': [0, 0, 1, 1]},
]


def _local_services():
    # Pin tooling to the checkout's local data, even on an add-on host. Tests
    # may supply their own isolated CHAUFFEUR_DATA_DIR before loading storage.
    if not os.environ.get('CHAUFFEUR_DATA_DIR'):
        os.environ['CHAUFFEUR_DATA_DIR'] = str(ROOT / 'data')
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from services import model_pools, storage, twin_cost, twin_reads, twin_register, twin_store
    return model_pools, storage, twin_cost, twin_reads, twin_register, twin_store


def _master_box(parent, box):
    """Compose a crop-relative wing into normalised full-sheet coordinates."""
    x0, y0, x1, y1 = parent
    return [x0 + box[0] * (x1 - x0), y0 + box[1] * (y1 - y0),
            x0 + box[2] * (x1 - x0), y0 + box[3] * (y1 - y0)]


def _redact(message, secrets):
    for secret in secrets:
        if secret:
            message = message.replace(secret, '[redacted]')
    return message


def compare(pdf_path, budget, models, *, key_dir, out_dir, key_path,
            reader=None, ceiling=None):
    """Run four reads per provider and return scores against a local hand key.

    Only entries appended since this invocation count toward its budget;
    lifetime checkpoints remain enforced by twin_cost. Answers are saved
    before interpreting them, including returned error answers, with any
    echoed credentials redacted. The answer key is used only for scoring
    and is never supplied to the reader.
    """
    if not math.isfinite(budget) or budget < 0:
        raise ValueError('Budget must be a finite, non-negative dollar amount.')
    pools, storage, costs, reads, register, store = _local_services()
    started = len(costs.entries())
    run = 'compare:' + uuid.uuid4().hex
    read = reader or reads.read
    key = json.loads(Path(key_path).read_text(encoding='utf-8'))
    pdf_path = Path(pdf_path)
    pdf = pdf_path.read_bytes()
    rows, secrets = [], []

    def spent_since(index):
        return math.fsum(entry['usd'] for entry in costs.entries()[index:])

    for model in models:
        row = {'model': model, 'cost': 0.0, 'dimension_error_ft': None,
               'outline_rms_ft': None, 'walls': 0, 'roof_sections': 0,
               'roof_kinds': []}
        rows.append(row)
        model_started = len(costs.entries())
        try:
            if model not in PROVIDERS:
                raise ValueError('Unknown provider; choose gemini, claude or openai.')
            provider = PROVIDERS[model]
            secret = (Path(key_dir) / provider['key_file']).read_text(encoding='utf-8').strip()
            secrets.append(secret)
            if not secret:
                raise ValueError('The provider key file is empty.')
            # A local pro-pool override could otherwise silently compare the
            # previous provider again. Use the selected provider's defaults.
            storage.patch_settings({'llm_provider': provider['llm_provider'],
                                    provider['setting']: secret, 'model_pool_pro': ''})
            source = store.save_source('drawing', pdf_path.name, pdf,
                                       content_type='application/pdf')
            destination = Path(out_dir) / model
            destination.mkdir(parents=True, exist_ok=True)
            outline, outline_crop = None, None

            for number, spec in enumerate(COMPARE_READS, 1):
                kind = spec['kind']
                if ceiling is None:
                    # A read sends one image and at most one provider request.
                    # Cover every eligible model, including unpriced models
                    # (which twin_cost.price charges at its highest rates).
                    candidates = pools.models_for('twin', storage.get_settings(), paid=True)
                    estimate = max(costs.price(candidate, 2000, reads.MAX_OUTPUT[kind])[0]
                                   for candidate in candidates)
                else:
                    estimate = ceiling(kind)
                if not math.isfinite(estimate) or estimate < 0:
                    raise ValueError('Read ceiling must be finite and non-negative.')
                if spent_since(started) + estimate > budget:
                    row['stopped'] = 'budget'
                    break

                box = spec.get('box')
                wing = None
                if 'wing' in spec:
                    wings = outline.get('wings', [])
                    if len(wings) <= spec['wing']:
                        raise ValueError('Outline must identify two wing boxes for the walls reads.')
                    wing = wings[spec['wing']]
                    box = _master_box(outline_crop['box'], wing['box'])
                crop = store.crop(source, spec['page'], box)
                images = [{'mime': crop['mime'], 'b64': crop['b64']}]
                context = {'page': spec['page'], 'box': crop['box'],
                           'level': 'L1', 'building': {'name': 'main'}}
                if wing is not None:
                    context['wing'] = wing['name']
                costs.require_clear()
                answer = read(kind, images, context, run=run, step=f'{kind}-{number}')
                raw = json.dumps(answer, ensure_ascii=False, indent=2, allow_nan=False)
                (destination / f'{kind}-{number}.json').write_text(
                    _redact(raw, secrets) + '\n', encoding='utf-8')
                if not isinstance(answer, dict):
                    raise ValueError(f'{kind} returned no answer object.')
                if 'error' in answer:
                    raise ValueError(str(answer['error']))

                if kind == 'outline':
                    outline, outline_crop = answer, crop
                    dimension = answer['dimension']
                    scale = register.from_dimension(
                        store.crop_to_master(crop, dimension['a']),
                        store.crop_to_master(crop, dimension['b']), dimension['feet'])
                    pixels = [store.crop_to_master(crop, point) for point in answer['outline']]
                    width = (max(p[0] for p in pixels) - min(p[0] for p in pixels)) * scale
                    row['dimension_error_ft'] = abs(width - key['overall']['width_ft'])
                    reg = register.make(scale)
                    feet = [register.apply(reg, point) for point in pixels]
                    _, row['outline_rms_ft'] = register.fit_outline(feet, key['l1_outline_ft'])
                elif kind == 'walls':
                    row['walls'] += len(answer['walls'])
                else:
                    row['roof_sections'] = len(answer['sections'])
                    row['roof_kinds'] = sorted({section['kind'] for section in answer['sections']})
        except Exception as exc:
            # Provider errors can contain credential-bearing URLs. Keep the
            # useful error but scrub every key loaded during this comparison.
            row['error'] = _redact(f'{type(exc).__name__}: {exc}', secrets)
        finally:
            row['cost'] = spent_since(model_started)
    return rows


def print_table(rows):
    """Print scores and partial-run status without settings or credentials."""
    cells = [['Model', 'Cost ($)', 'Dimension error (ft)', 'Outline RMS (ft)',
              'Walls', 'Roof sections', 'Roof kinds', 'Status']]
    for row in rows:
        def score(name):
            value = row.get(name)
            return '-' if value is None else f'{value:.3f}'

        status = row.get('error') or row.get('stopped') or 'ok'
        cells.append([str(row['model']), f"{row['cost']:.4f}",
                      score('dimension_error_ft'), score('outline_rms_ft'),
                      str(row['walls']), str(row['roof_sections']),
                      ','.join(row['roof_kinds']) or '-', ' '.join(str(status).split())])
    widths = [max(len(row[i]) for row in cells) for i in range(len(cells[0]))]
    for row in cells:
        print('  '.join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    comparison = commands.add_parser('compare', help='Run a paid, budgeted comparison locally.')
    comparison.add_argument('--sheets', required=True, type=Path)
    comparison.add_argument('--budget', required=True, type=float)
    comparison.add_argument('--models', required=True, help='Comma-separated gemini,claude,openai.')
    comparison.add_argument('--out', type=Path, default=DEFAULT_OUT)
    build = commands.add_parser('build', help='Not yet implemented.')
    build.add_argument('--sheets', type=Path)
    build.add_argument('--budget', type=float)
    args = parser.parse_args(argv)
    if args.command == 'build':
        print('Build is not yet implemented; this command makes no model requests.')
        return 2
    models = [model.strip() for model in args.models.split(',') if model.strip()]
    if not models or any(model not in PROVIDERS for model in models):
        parser.error('--models must name gemini, claude or openai.')
    if not math.isfinite(args.budget) or args.budget < 0:
        parser.error('--budget must be a finite, non-negative dollar amount.')
    try:
        rows = compare(args.sheets, args.budget, models, key_dir=ROOT,
                       out_dir=args.out, key_path=DEFAULT_KEY)
        print_table(rows)
        _, _, costs, _, _, _ = _local_services()
        print(f'Local ledger total: ${costs.total():.4f}')
        return 1 if any(row.get('error') for row in rows) else 0
    except Exception as exc:
        # Do not echo arbitrary exception text from an entry point that can
        # handle credentials. Per-model diagnostics above are already scrubbed.
        print(f'Comparison could not finish ({type(exc).__name__}).', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

"""Local, budgeted twin reads. Running compare or record-place spends money.

Offline callers can supply a reader and a per-kind ceiling. No model request
is made at import time; the build command is reserved for the later slice.
"""
import argparse
import json
import math
import os
from pathlib import Path
import sys
import tempfile
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


def default_data_dir():
    """Allocate fresh scratch storage outside the checkout, never live data."""
    parent = Path(tempfile.gettempdir()).resolve()
    if parent.is_relative_to(ROOT.parent):
        # TMP/TEMP may point into a checkout for other tools. Do not follow
        # that override when allocating this harness's isolated data.
        parent = Path.home()
    return tempfile.mkdtemp(prefix='chauffeur_twin_live_', dir=parent)


def _local_services():
    # Select storage before importing any services: storage binds its database
    # and other services derive their paths from it at import time.
    if not os.environ.get('CHAUFFEUR_DATA_DIR'):
        os.environ['CHAUFFEUR_DATA_DIR'] = default_data_dir()
    print(f"Data directory: {Path(os.environ['CHAUFFEUR_DATA_DIR']).resolve()}")
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
               'roof_kinds': [], 'errors': []}
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
                step = f'{kind}-{number}'
                try:
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
                        # An absent wing must not discard a walls or roof read.
                        # Fall back to the outline read's own full crop extent.
                        parent = outline_crop['box'] if outline_crop else COMPARE_READS[0]['box']
                        box = parent
                        wings = (outline or {}).get('wings') or []
                        if len(wings) > spec['wing']:
                            candidate = wings[spec['wing']]
                            if isinstance(candidate, dict) and candidate.get('box'):
                                wing = candidate
                                box = _master_box(parent, wing['box'])
                    crop = store.crop(source, spec['page'], box)
                    if kind == 'outline':
                        outline_crop = crop
                    images = [{'mime': crop['mime'], 'b64': crop['b64']}]
                    context = {'page': spec['page'], 'box': crop['box'],
                               'level': 'L1', 'building': {'name': 'main'}}
                    if wing is not None and wing.get('name'):
                        context['wing'] = wing['name']
                    costs.require_clear()
                    answer = read(kind, images, context, run=run, step=step)
                    raw = json.dumps(answer, ensure_ascii=False, indent=2, allow_nan=False)
                    (destination / f'{step}.json').write_text(
                        _redact(raw, secrets) + '\n', encoding='utf-8')
                    if not isinstance(answer, dict):
                        raise ValueError(f'{kind} returned no answer object.')
                    if 'error' in answer:
                        raise ValueError(str(answer['error']))

                    if kind == 'outline':
                        outline = answer
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
                    error = _redact(f'{step}: {type(exc).__name__}: {exc}', secrets)
                    row['errors'].append(error)
                    row['error'] = '; '.join(row['errors'])
        except Exception as exc:
            # Provider errors can contain credential-bearing URLs. Keep the
            # useful error but scrub every key loaded during this comparison.
            row['error'] = _redact(f'{type(exc).__name__}: {exc}', secrets)
        finally:
            row['cost'] = spent_since(model_started)
    return rows


def record_place(sheets_path, plot_page, photos, budget, models, *, key_dir,
                 out_dir, reader=None, ceiling=None):
    """Record three setup reads without publishing or accepting a place.

    Like compare, use local scratch storage and count only ledger entries
    appended during this invocation. Each saved answer includes its own
    metered usage and actual model, including answers reporting an error.
    """
    if not math.isfinite(budget) or budget < 0:
        raise ValueError('Budget must be a finite, non-negative dollar amount.')
    if type(plot_page) is not int or plot_page < 1:
        raise ValueError('Choose a positive plot page number.')
    photos = [Path(photo) for photo in photos]
    if not 1 <= len(photos) <= 4:
        raise ValueError('Choose one to four photos.')
    pools, storage, costs, reads, _, store = _local_services()
    started = len(costs.entries())
    run = 'record-place:' + uuid.uuid4().hex
    read = reader or reads.read
    sheets_path = Path(sheets_path)
    pdf = sheets_path.read_bytes()
    rows, secrets = [], []

    def spent_since(index):
        return math.fsum(entry['usd'] for entry in costs.entries()[index:])

    for model in models:
        row = {'model': model, 'cost': 0.0, 'errors': []}
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
            storage.patch_settings({'llm_provider': provider['llm_provider'],
                                    provider['setting']: secret, 'model_pool_pro': ''})
            source = store.save_source('drawing', sheets_path.name, pdf,
                                       content_type='application/pdf')
            # Validate the requested plot page before starting any paid reads.
            plot = store.crop(source, plot_page, [0, 0, 1, 1])
            photo_images = []
            for photo in photos:
                sid = store.save_source('photo', photo.name, photo.read_bytes())
                photo_images.extend(store.source_images(sid))
            part = {'id': 'building-1', 'name': 'Building', 'kind': 'other',
                    'has_drawings': True}
            parts = [part, {'id': 'lot', 'name': 'Lot', 'kind': 'lot',
                            'has_drawings': True}]
            requests = [
                ('plot', 'plot-place', [{'mime': plot['mime'], 'b64': plot['b64']}],
                 {'page': plot_page, 'box': plot['box']}),
                ('photo_parts', 'photo_parts', photo_images, {'parts': parts}),
                ('sheet_roles', 'sheet_roles-hint', store.source_images(source),
                 {'part': part, 'parts': parts}),
            ]
            destination = Path(out_dir) / model
            destination.mkdir(parents=True, exist_ok=True)
            for kind, step, images, context in requests:
                try:
                    if ceiling is None:
                        candidates = pools.models_for('twin', storage.get_settings(), paid=True)
                        inputs = 1500 + 1600 * len(images) + math.ceil(
                            len(json.dumps({'step': step, 'context': context})) / 4)
                        estimate = max(costs.price(candidate, inputs, reads.MAX_OUTPUT[kind])[0]
                                       for candidate in candidates)
                    else:
                        estimate = ceiling(kind)
                    if not math.isfinite(estimate) or estimate < 0:
                        raise ValueError('Read ceiling must be finite and non-negative.')
                    if spent_since(started) + estimate > budget:
                        row['stopped'] = 'budget'
                        break
                    costs.require_clear()
                    before = len(costs.entries())
                    answer = read(kind, images, context, run=run, step=step)
                    usage = costs.entries()[before:]
                    recorded = {'answer': answer, 'usage': usage,
                                'model': usage[-1]['model'] if usage else model}
                    raw = json.dumps(recorded, ensure_ascii=False, indent=2, allow_nan=False)
                    (destination / f'{step}.json').write_text(
                        _redact(raw, secrets) + '\n', encoding='utf-8')
                    if not isinstance(answer, dict):
                        raise ValueError(f'{kind} returned no answer object.')
                    if 'error' in answer:
                        raise ValueError(str(answer['error']))
                except Exception as exc:
                    row['errors'].append(_redact(f'{step}: {type(exc).__name__}: {exc}', secrets))
                    row['error'] = '; '.join(row['errors'])
        except Exception as exc:
            error = _redact(f'{type(exc).__name__}: {exc}', secrets)
            row['errors'].append(error)
            row['error'] = '; '.join(row['errors'])
        finally:
            row['cost'] = spent_since(model_started)
    print(f'Spent ${spent_since(started):.4f}')
    return rows


def print_table(rows, key_path=None):
    """Print scores and partial-run status without settings or credentials."""
    key = json.loads(Path(key_path or DEFAULT_KEY).read_text(encoding='utf-8'))
    roof = key['roof']
    cells = [['Model', 'Cost ($)', 'Dimension error (ft)', 'Outline RMS (ft)',
              'Key width (ft)', 'Walls', 'Key walls min', 'Roof sections',
              'Key roof sections', 'Roof kinds', 'Key roof kinds', 'Status']]
    for row in rows:
        def score(name):
            value = row.get(name)
            return '-' if value is None else f'{value:.3f}'

        status = row.get('error') or row.get('stopped') or 'ok'
        cells.append([str(row['model']), f"{row['cost']:.4f}",
                      score('dimension_error_ft'), score('outline_rms_ft'),
                      f"{key['overall']['width_ft']:g}", str(row['walls']),
                      str(key['l1_walls_min']), str(row['roof_sections']),
                      f"{roof['sections_min']}-{roof['sections_max']}",
                      ','.join(row['roof_kinds']) or '-',
                      ','.join(sorted(roof['kinds_present'])), ' '.join(str(status).split())])
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
    comparison.add_argument('--data-dir', type=Path,
                            help='Storage directory (default: CHAUFFEUR_DATA_DIR or fresh scratch).')
    recording = commands.add_parser('record-place', help='Record three paid, budgeted setup reads locally.')
    recording.add_argument('--sheets', required=True, type=Path)
    recording.add_argument('--plot-page', required=True, type=int)
    recording.add_argument('--photos', required=True, nargs='+', type=Path)
    recording.add_argument('--budget', required=True, type=float)
    recording.add_argument('--models', required=True, help='Comma-separated gemini,claude,openai.')
    recording.add_argument('--out', type=Path, default=DEFAULT_OUT)
    recording.add_argument('--data-dir', type=Path,
                           help='Storage directory (default: CHAUFFEUR_DATA_DIR or fresh scratch).')
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
        if args.data_dir is not None:
            os.environ['CHAUFFEUR_DATA_DIR'] = str(args.data_dir.resolve())
        if args.command == 'record-place':
            rows = record_place(args.sheets, args.plot_page, args.photos, args.budget,
                                models, key_dir=ROOT, out_dir=args.out)
            for row in rows:
                status = row.get('error') or row.get('stopped') or 'ok'
                print(f"{row['model']}: ${row['cost']:.4f} {status}")
        else:
            rows = compare(args.sheets, args.budget, models, key_dir=ROOT,
                           out_dir=args.out, key_path=DEFAULT_KEY)
            print_table(rows)
        from services import twin_cost as costs
        print(f'Local ledger total: ${costs.total():.4f}')
        return 1 if any(row.get('error') for row in rows) else 0
    except Exception as exc:
        # Do not echo arbitrary exception text from an entry point that can
        # handle credentials. Per-model diagnostics above are already scrubbed.
        action = 'Recording' if args.command == 'record-place' else 'Comparison'
        print(f'{action} could not finish ({type(exc).__name__}).', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

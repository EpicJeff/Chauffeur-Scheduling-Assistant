"""Sheets for the house editor (spec docs/superpowers/specs/
2026-11-07-house-editor-design.md sections 7.2, 7.3, 9; plan
docs/superpowers/plans/2026-11-07-house-editor-slice-1.md Task 5): 300 dpi
masters and full-resolution crops, page roles, registrations, a never-stale
update of the current plan, start over, and the parent's spend reset.

Run from chauffeur/:  python tests/test_twin_sheets.py
"""
import base64
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_sheets_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import storage  # noqa: E402
from services import twin_cost as tc  # noqa: E402
from services import twin_plan as tp  # noqa: E402
from services import twin_register as tr  # noqa: E402
from services import twin_store as ts  # noqa: E402

_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_poolhouse.plan.json')


def check(cond, msg):
    # Local on purpose: tests/harness.py stubs storage.get_settings.
    if not cond:
        raise AssertionError(msg)


def close(a, b, tol=1e-6):
    return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


def _plan():
    with open(_FIXTURE, encoding='utf-8') as f:
        return tp.normalize(json.load(f))[0]


def _fresh():
    storage.patch_settings({'house_twin': None, 'house_twin_cost': None})
    shutil.rmtree(ts.DATA_DIR, ignore_errors=True)


def _pdf(pages=3, w=1224, h=792):
    """A vector PDF whose pages are 17 x 11 inches (1224 x 792 points)."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(w, h)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _usage(inp=1000, out=100):
    model = next(iter(tc.PRICES))
    return {'model': model, 'input_tokens': inp, 'output_tokens': out, 'images': 0,
            'prompt_chars': 10, 'max_output_tokens': 1024}


def _png_size(data):
    from PIL import Image
    return Image.open(io.BytesIO(data)).size


def scenario_crop_is_full_resolution():
    _fresh()
    sid = ts.save_source('drawing', 'lot58.pdf', _pdf())
    full = ts.crop(sid, 1, [0, 0, 1, 1])
    quarter = ts.crop(sid, 1, [0.25, 0.25, 0.5, 0.5])
    check(full['master'] == [5100, 3300], full['master'])
    check(max(full['size']) == 2048 and full['mime'] == 'image/png', full['size'])
    check(quarter['size'] == [1275, 825], quarter['size'])
    check(_png_size(base64.b64decode(quarter['b64'])) == (1275, 825), 'the crop image is the crop size')
    check(close(ts.crop_to_master(quarter, [0.5, 0.5]), [1912.5, 1237.5]), 'crop centre on master')
    check(close(ts.crop_to_master(full, [1, 1]), [5100, 3300]), 'full crop corner')
    for bad in ([0.5, 0.5, 0.4, 0.6], [-0.2, 0, 1, 1], [0, 0, 1]):
        try:
            ts.crop(sid, 1, bad)
        except ValueError:
            continue
        raise AssertionError(f'bad box accepted: {bad}')


def scenario_old_sources_render_masters_lazily():
    _fresh()
    sid = ts.save_source('drawing', 'old.pdf', _pdf(pages=1))
    for path in (Path(ts.DATA_DIR) / 'sources' / sid).glob('master-*.png'):
        path.unlink()
    check(ts.crop(sid, 1, [0, 0, 1, 1])['master'] == [5100, 3300], 'lazy master')
    check((Path(ts.DATA_DIR) / 'sources' / sid / 'master-1.png').is_file(), 'kept after the first crop')


def scenario_page_image_is_the_underlay_png():
    _fresh()
    sid = ts.save_source('drawing', 'lot58.pdf', _pdf(pages=1))
    check(max(_png_size(ts.page_image(sid, 1))) == 2048, 'the 2048 px page')


def scenario_page_roles_and_registrations_round_trip():
    _fresh()
    sid = ts.save_source('drawing', 'lot58.pdf', _pdf())
    ts.set_page_roles([
        {'source': sid, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None},
        {'source': sid, 'page': 3, 'role': 'roof', 'level': None, 'box': None},
        {'source': sid, 'page': 3, 'role': 'floor', 'level': 'Bonus', 'box': [0.05, 0.2, 0.4, 0.8]}])
    rows = ts.page_roles()
    check(len(rows) == 3 and all(r['building'] == 'house' for r in rows), rows)
    for bad in ({'source': sid, 'page': 9, 'role': 'floor', 'level': 'x', 'box': None},
                {'source': sid, 'page': 1, 'role': 'attic', 'level': None, 'box': None},
                {'source': 'nope', 'page': 1, 'role': 'floor', 'level': 'x', 'box': None}):
        try:
            ts.set_page_roles([bad])
        except ValueError:
            continue
        raise AssertionError(f'bad role row accepted: {bad}')
    check(len(ts.page_roles()) == 3, 'a refused write changes nothing')
    ts.set_registration(sid, 1, 'L1', tr.make(0.05, origin_px=(10, 20)))
    check(ts.registration(sid, 1, 'L1')['scale'] == 0.05, 'reg saved')
    check(ts.registration(sid, 2, 'L2') is None, 'no reg yet')


def scenario_update_current_is_never_stale():
    _fresh()
    ts.push_round(_plan(), 'build')

    def darker(plan):
        plan['materials']['roof']['color'] = '#111111'
        return plan
    rid = ts.update_current(darker, 'edit', note='darker', step={'id': 'edit-1', 'label': 'Darker roof'})
    row = ts.rounds()[-1]
    check(ts.current_id() == rid and not row['stale'] and row['step'] == {'id': 'edit-1', 'label': 'Darker roof'}, row)
    check(ts.current()['materials']['roof']['color'] == '#111111', 'mutation saved')
    for kind in ('build', 'edit', 'start_over'):
        check(kind in ts._KINDS, kind)


def scenario_start_over_keeps_the_ledger():
    _fresh()
    sid = ts.save_source('drawing', 'lot58.pdf', _pdf(pages=1))
    ts.set_page_roles([{'source': sid, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None}])
    ts.set_registration(sid, 1, 'L1', tr.make(0.05))
    ts.push_round(_plan(), 'build')
    tc.record('step:outline', [_usage()])
    spent = tc.total()
    storage.patch_settings({'house_twin_perf': [{'tier': 'low'}]})
    ts.start_over()
    check(ts.current() is None and ts.rounds() == [] and ts.sources() == [] and ts.page_roles() == [], 'cleared')
    check(ts.registration(sid, 1, 'L1') is None, 'registrations cleared')
    check(not (Path(ts.DATA_DIR) / 'sources' / sid).exists(), 'files removed')
    check(tc.total() == spent and spent > 0, 'ledger kept')
    check(storage.get_settings().get('house_twin_perf') == [{'tier': 'low'}], 'perf kept')


def scenario_start_over_refuses_while_a_build_runs():
    _fresh()
    ts.push_round(_plan(), 'build')
    previous = ts.build_running
    ts.build_running = lambda: True
    try:
        try:
            ts.start_over()
        except ValueError:
            pass
        else:
            raise AssertionError('start over during a build must refuse')
    finally:
        ts.build_running = previous
    check(ts.current() is not None, 'nothing cleared')


def scenario_ledger_reset_is_recorded():
    _fresh()
    tc.record('step:outline', [_usage()])
    spent = tc.total()
    check(spent > 0, spent)
    tc.reset('parent-1')
    check(tc.total() == 0 and tc.entries() == [], 'live total cleared')
    last = tc.resets()[-1]
    check(last['by'] == 'parent-1' and abs(last['total'] - spent) < 1e-12 and last['at'], last)
    check(tc.blocking_checkpoint() is None, 'acknowledgements cleared with the total')
    tc.record('step:walls', [_usage()])
    check(tc.total() > 0 and len(tc.resets()) == 1, 'spending resumes from zero')


def scenario_v1_rounds_upgrade_on_read():
    # Review finding: an installed P0 house keeps v1 round files on disk.
    _fresh()
    with open(_FIXTURE, encoding='utf-8') as f:
        v1 = json.load(f)
    root = Path(ts.DATA_DIR) / 'rounds'
    root.mkdir(parents=True, exist_ok=True)
    (root / '1.json').write_text(json.dumps(v1), encoding='utf-8')
    storage.patch_settings({'house_twin': {'current': 1, 'fixes': [], 'sources': [], 'rounds': [
        {'id': 1, 'kind': 'draft', 'created': '2026-11-06T00:00:00+00:00', 'note': '', 'cost': None,
         'run': None, 'stale': False}]}})
    cur = ts.current()
    check(cur['schema'] == 'chauffeur.twin.plan/2' and cur['buildings'][0]['roof']['sections'][0]['id'] == 'roof-main',
          'current() upgrades a v1 round')
    rid = ts.revert(1)
    check(ts.current_id() == rid and ts.current()['schema'] == 'chauffeur.twin.plan/2', 'revert lands v2')


def scenario_late_result_after_start_over_is_refused():
    _fresh()
    ts.push_round(_plan(), 'build')
    generation = ts.generation()
    ts.start_over()
    check(ts.generation() != generation, 'start over bumps the generation')
    try:
        ts.update_current(lambda p: p, 'build', generation=generation)
    except ts.StaleGeneration:
        pass
    else:
        raise AssertionError('a late worker result must not write after start over')
    check(ts.current() is None, 'nothing written')


def scenario_tombstones_round_trip_and_clear():
    _fresh()
    ts.add_tombstone({'kind': 'wall', 'level': 'L1', 'geometry': {'from': [0, 0], 'to': [10, 0]},
                      'src': {'step': 'walls:L1:main'}})
    check(len(ts.tombstones()) == 1 and ts.tombstones()[0]['src']['step'] == 'walls:L1:main', ts.tombstones())
    ts.start_over()
    check(ts.tombstones() == [], 'cleared by start over')


def scenario_a_late_push_round_cannot_resurrect_the_house():
    # Review finding: drafts and critiques publish with push_round, which had no generation check.
    _fresh()
    generation = ts.generation()
    ts.start_over()
    try:
        ts.push_round(_plan(), 'director', generation=generation)
    except ts.StaleGeneration:
        pass
    else:
        raise AssertionError('a push_round from before the start over must refuse')
    check(ts.current() is None, 'nothing written')
    rid = ts.push_round(_plan(), 'director', generation=ts.generation())
    check(ts.current_id() == rid, 'the current generation still writes')


def scenario_a_draft_running_through_a_start_over_publishes_nothing():
    import test_twin_draft as drafts
    from services import model_pools, twin_draft
    _fresh()
    drawing, plot, photo = drafts._fresh()
    model = drafts.Model()
    calls = {'n': 0}

    def start_over_midway(*a, **k):
        calls['n'] += 1
        if calls['n'] == 1:
            ts.start_over()          # a parent presses Start over while the draft is reading
        return model(*a, **k)
    original = model_pools.call_pool_json
    model_pools.call_pool_json = start_over_midway
    try:
        twin_draft.draft([{'id': drawing}], [photo], {'id': plot})
    except Exception:
        pass
    finally:
        model_pools.call_pool_json = original
    check(ts.current() is None and ts.rounds() == [], 'the cleared house stays cleared')


def scenario_start_over_clears_the_row_before_the_files():
    _fresh()
    ts.push_round(_plan(), 'build')
    original = shutil.rmtree

    def failing(*a, **k):
        raise OSError('Directory not empty')
    shutil.rmtree = failing
    try:
        try:
            ts.start_over()
        except OSError:
            pass
    finally:
        shutil.rmtree = original
    check(ts.current() is None, 'the row never points at missing rounds')


def scenario_a_truncated_master_is_rendered_again():
    _fresh()
    sid = ts.save_source('drawing', 'lot58.pdf', _pdf(pages=1))
    master = Path(ts.DATA_DIR) / 'sources' / sid / 'master-1.png'
    master.write_bytes(bytes([0x89]) + b'PNG' + bytes([13, 10, 26, 10]) + b' truncated')
    check(ts.crop(sid, 1, [0, 0, 1, 1])['master'] == [5100, 3300], 'recovered by re-rendering')


if __name__ == '__main__':
    for fn in (scenario_crop_is_full_resolution,
               scenario_old_sources_render_masters_lazily,
               scenario_page_image_is_the_underlay_png,
               scenario_page_roles_and_registrations_round_trip,
               scenario_update_current_is_never_stale,
               scenario_start_over_keeps_the_ledger,
               scenario_start_over_refuses_while_a_build_runs,
               scenario_ledger_reset_is_recorded,
               scenario_v1_rounds_upgrade_on_read,
               scenario_late_result_after_start_over_is_refused,
               scenario_tombstones_round_trip_and_clear,
               scenario_a_late_push_round_cannot_resurrect_the_house,
               scenario_a_draft_running_through_a_start_over_publishes_nothing,
               scenario_start_over_clears_the_row_before_the_files,
               scenario_a_truncated_master_is_rendered_again):
        fn()
        print('  ok ', fn.__name__)

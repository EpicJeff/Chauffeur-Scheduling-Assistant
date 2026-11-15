"""Alpha records and image ingest through HTTP and services in a temp data dir."""
import hashlib
import io
import json
import sys
import traceback
from unittest.mock import patch

from PIL import Image
from test_twin_materials import API, Ctx, create, file_url, materials, seed, upload


ALPHA_DEFAULTS = dict(alpha_mode='opaque', opacity=1.0, alpha_cutoff=0.5)


def alpha_image(solid=False):
    image = Image.new('RGBA', (4, 4), (40, 100, 160, 255))
    if not solid:
        for y in range(2):
            for x in range(2):
                image.putpixel((x, y), (40, 100, 160, 0))
    out = io.BytesIO()
    image.save(out, format='PNG')
    return out.getvalue()


def assert_defaults(params):
    assert {key: params[key] for key in ALPHA_DEFAULTS} == ALPHA_DEFAULTS


def legacy_record(row):
    record = json.loads(json.dumps(row))
    for key in ALPHA_DEFAULTS:
        record['params'].pop(key, None)
    return record


def test_old_record_reads_as_opaque():
    seed()
    with Ctx() as c:
        row = create(c)
        path = materials.root() / row['id'] / 'material.json'
        materials._json(path, legacy_record(row))
        before = path.read_bytes()
        listed = c.client.get(API, headers=c.mum)
        assert listed.status_code == 200, listed.text
        entry = next(r for r in listed.json()['materials'] if r['id'] == row['id'])
        assert_defaults(entry['params'])
        assert_defaults(materials.page_manifest()[row['id']]['params'])
        assert_defaults(materials.get(row['id'])['params'])
        assert path.read_bytes() == before, 'reading must not rewrite an old record'
        changed = c.client.patch(f"{API}/{row['id']}", headers=c.mum,
                                 json={'params': {'tint': '#123456'}})
        assert changed.status_code == 200, changed.text
        assert_defaults(changed.json()['params'])


def test_params_validate_mode_and_clamp():
    seed()
    with Ctx() as c:
        row = create(c)
        path = f"{API}/{row['id']}"
        bad = c.client.patch(path, headers=c.mum, json={'params': {'alpha_mode': 'frosted'}})
        assert bad.status_code == 400 and bad.json()['detail'], bad.text
        for mode in ('opaque', 'cutout', 'blend'):
            response = c.client.patch(path, headers=c.mum,
                                      json={'params': {'alpha_mode': mode, 'opacity': 1.7, 'alpha_cutoff': -1}})
            assert response.status_code == 200, response.text
            assert response.json()['params']['alpha_mode'] == mode
            assert response.json()['params']['opacity'] == 1.0
            assert response.json()['params']['alpha_cutoff'] == 0.0
        response = c.client.patch(path, headers=c.mum, json={'params': {'opacity': -2, 'alpha_cutoff': 2}})
        assert response.status_code == 200, response.text
        assert response.json()['params']['opacity'] == 0.0
        assert response.json()['params']['alpha_cutoff'] == 1.0
        for key in ('opacity', 'alpha_cutoff'):
            for value in ('0.5', None, True, float('nan'), float('inf')):
                try:
                    materials.update(row['id'], {'params': {key: value}}, 'mum')
                except ValueError as exc:
                    assert key in str(exc)
                else:
                    raise AssertionError(f'{key} accepted {value!r}')


def test_base_colour_with_alpha_splits_an_opacity_map():
    seed()
    with Ctx() as c:
        row = create(c)
        data = alpha_image()
        response = upload(c, row['id'], data)
        assert response.status_code == 200, response.text
        row = response.json()
        assert row['params']['alpha_mode'] == 'cutout'
        assert row['revision'] == 2, 'base and alpha attach in one material revision'
        opacity = c.client.get(file_url(row, 'opacity'), headers=c.mum)
        assert opacity.status_code == 200, opacity.text
        decoded = Image.open(io.BytesIO(opacity.content)).convert('L')
        assert decoded.size == (4, 4)
        assert [decoded.getpixel((x, y)) for y in range(4) for x in range(4)] == [
            0 if x < 2 and y < 2 else 255 for y in range(4) for x in range(4)]
        # Frozen pre-alpha encoding: load, cap, RGB, JPEG quality 92.
        with Image.open(io.BytesIO(data)) as source:
            source.load()
            source.thumbnail((4096, 4096), Image.Resampling.LANCZOS)
            expected = io.BytesIO()
            source.convert('RGB').save(expected, format='JPEG', quality=92)
        base = c.client.get(file_url(row), headers=c.mum)
        assert base.status_code == 200 and base.content == expected.getvalue()
        assert Image.open(io.BytesIO(base.content)).size == (4, 4)
        undone = c.client.post(f"{API}/{row['id']}/undo", headers=c.mum).json()
        assert undone['maps'] == {} and undone['params']['alpha_mode'] == 'opaque'


def test_split_does_not_replace_an_existing_opacity_map():
    seed()
    with Ctx() as c:
        row = create(c, params={'alpha_mode': 'blend'})
        out = io.BytesIO()
        Image.new('L', (4, 4), 123).save(out, format='PNG')
        response = upload(c, row['id'], out.getvalue(), 'opacity')
        assert response.status_code == 200, response.text
        row = response.json()
        filename = row['maps']['opacity']
        before = hashlib.sha256((materials.root() / row['id'] / filename).read_bytes()).hexdigest()
        row = upload(c, row['id'], alpha_image()).json()
        assert row['maps']['opacity'] == filename
        assert hashlib.sha256((materials.root() / row['id'] / filename).read_bytes()).hexdigest() == before
        assert row['params']['alpha_mode'] == 'blend'
        opaque = create(c)
        assert upload(c, opaque['id'], out.getvalue(), 'opacity').status_code == 200
        opaque = upload(c, opaque['id'], alpha_image()).json()
        assert opaque['params']['alpha_mode'] == 'opaque'


def test_solid_alpha_changes_nothing():
    seed()
    with Ctx() as c:
        row = create(c)
        response = upload(c, row['id'], alpha_image(solid=True))
        assert response.status_code == 200, response.text
        assert set(response.json()['maps']) == {'base_color'}
        assert response.json()['params']['alpha_mode'] == 'opaque'


def test_opacity_map_upload_and_clear():
    seed()
    with Ctx() as c:
        row = create(c)
        response = upload(c, row['id'], alpha_image(), 'opacity')
        assert response.status_code == 200, response.text
        manifest = materials.page_manifest()[row['id']]
        assert manifest['maps']['opacity'].endswith(response.json()['maps']['opacity'])
        response = c.client.delete(f"{API}/{row['id']}/maps/opacity", headers=c.mum)
        assert response.status_code == 200, response.text
        assert 'opacity' not in response.json()['maps']
        assert 'opacity' not in materials.page_manifest()[row['id']]['maps']


def test_undo_to_a_pre_alpha_revision_reads_defaults():
    seed()
    with Ctx() as c:
        row = create(c)
        folder = materials.root() / row['id']
        old = legacy_record(row)
        materials._json(folder / 'material.json', old)
        materials._json(folder / 'revisions' / '1.json', old)
        changed = c.client.patch(f"{API}/{row['id']}", headers=c.mum,
                                 json={'params': {'alpha_mode': 'blend', 'opacity': .3}})
        assert changed.status_code == 200, changed.text
        response = c.client.post(f"{API}/{row['id']}/undo", headers=c.mum)
        assert response.status_code == 200, response.text
        assert_defaults(response.json()['params'])
        assert_defaults(materials.get(row['id'])['params'])
        assert_defaults(materials.page_manifest()[row['id']]['params'])
        redone = c.client.post(f"{API}/{row['id']}/redo", headers=c.mum).json()
        assert redone['params']['alpha_mode'] == 'blend' and redone['params']['opacity'] == .3


def test_staged_ingest_follows_the_same_rule():
    seed()
    mid = materials.new_id()
    filename = materials.ingest_image(mid, 'base_color', alpha_image(), staged=True)
    assert not (materials.root() / mid / 'material.json').exists()
    row = materials.create({'name': 'Downloaded', 'maps': {'base_color': filename}}, 'mum',
                           material_id=mid, source='polyhaven')
    assert row['params']['alpha_mode'] == 'cutout'
    assert 'opacity' in row['maps']
    assert row['source_snapshot']['maps'] == row['maps']
    assert row['source_snapshot']['params']['alpha_mode'] == 'cutout'
    materials.update(mid, {'params': {'alpha_mode': 'blend'}}, 'mum')
    assert materials.reset_to_source(mid, 'mum')['params']['alpha_mode'] == 'cutout'


def test_ingest_image_preserves_explicit_mode_and_existing_opacity():
    seed()
    row = materials.create({'name': 'Blend', 'params': {'alpha_mode': 'blend'}}, 'mum')
    filename = materials.ingest_image(row['id'], 'base_color', alpha_image())
    assert (materials.root() / row['id'] / filename).is_file()
    row = materials.get(row['id'])
    assert row['params']['alpha_mode'] == 'blend' and 'opacity' in row['maps']
    opacity = row['maps']['opacity']
    materials.ingest_image(row['id'], 'base_color', alpha_image())
    assert materials.get(row['id'])['maps']['opacity'] == opacity
    mid = materials.new_id()
    opacity = materials.ingest_image(mid, 'opacity', alpha_image(solid=True), staged=True)
    base = materials.ingest_image(mid, 'base_color', alpha_image(), staged=True)
    staged = materials.create({'name': 'Staged', 'maps': {'base_color': base, 'opacity': opacity}},
                              'mum', material_id=mid)
    assert staged['maps']['opacity'] == opacity
    assert staged['params']['alpha_mode'] == 'opaque'


def test_split_alpha_handles_palette_and_solid_images():
    source = Image.new('RGBA', (2, 1), (20, 40, 60, 255))
    source.putpixel((0, 0), (20, 40, 60, 32))
    alpha = materials._split_alpha(source)
    assert alpha.mode == 'L' and list(alpha.getdata()) == [32, 255]
    assert materials._split_alpha(Image.new('RGB', (2, 1))) is None
    assert materials._split_alpha(Image.new('RGBA', (2, 1), (0, 0, 0, 255))) is None
    palette = Image.new('P', (2, 1))
    palette.putdata([0, 1])
    palette.info['transparency'] = 0
    assert list(materials._split_alpha(palette).getdata()) == [0, 255]


def test_split_rejects_total_live_bytes_before_publishing_files():
    seed()
    row = materials.create({'name': 'Limited'}, 'mum')
    folder = materials.root() / row['id']
    before = (folder / 'material.json').read_bytes()
    with patch.object(materials, 'MAX_MATERIAL_BYTES', 650):
        try:
            materials.set_image(row['id'], 'base_color', alpha_image(), 'mum')
        except ValueError as exc:
            assert '200 MB' in str(exc)
        else:
            raise AssertionError('base and opacity together must respect the live byte limit')
    assert (folder / 'material.json').read_bytes() == before
    assert not list((folder / 'maps').glob('*'))


if __name__ == '__main__':
    tests = [value for name, value in sorted(globals().items()) if name.startswith('test_')]
    passed = 0
    for test in tests:
        try:
            test()
            passed += 1
            print('ok  ', test.__name__)
        except Exception:
            print('FAIL', test.__name__)
            traceback.print_exc(limit=8)
    print(f'{passed}/{len(tests)} passed')
    sys.exit(passed != len(tests))

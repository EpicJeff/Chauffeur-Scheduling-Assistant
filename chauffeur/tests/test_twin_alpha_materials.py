"""Alpha records and image ingest through HTTP and services in a temp data dir."""
import hashlib
import io
import json
import sys
import traceback
from pathlib import Path
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
    record.pop('opacity_derived', None)
    record.pop('opacity_derived_mode', None)
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
        assert_flags(materials.get(row['id']), False, False)
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
        for key in ('opacity_derived', 'opacity_derived_mode'):
            assert c.client.patch(path, headers=c.mum, json={'params': {key: True}}).status_code == 400
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
        assert_flags(materials.get(row['id']), False, False)
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
    assert_flags(row, True, True)
    assert not (materials.root() / mid / 'staged.json').exists()
    assert 'opacity' in row['maps']
    assert row['source_snapshot']['maps'] == row['maps']
    assert row['source_snapshot']['params']['alpha_mode'] == 'cutout'
    assert_flags(row['source_snapshot'], True, True)
    materials.update(mid, {'params': {'alpha_mode': 'blend'}}, 'mum')
    reset = materials.reset_to_source(mid, 'mum')
    assert reset['params']['alpha_mode'] == 'cutout'
    assert_flags(reset, True, True)
    mid = materials.new_id()
    materials.ingest_image(mid, 'base_color', alpha_image(), staged=True)
    try:
        materials.create({'name': ''}, 'mum', material_id=mid)
    except ValueError:
        pass
    else:
        raise AssertionError('invalid fields must fail create')
    assert not (materials.root() / mid / 'material.json').exists()
    assert not (materials.root() / mid / 'history.json').exists()
    assert not list((materials.root() / mid / 'revisions').glob('*.json'))
    assert all(r['id'] != mid for r in materials.catalogue()['materials'])


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
    with Ctx() as c:
        measured = create(c)
        rgb = upload(c, measured['id'], rgb_image()).json()
        base_size = len(c.client.get(file_url(rgb), headers=c.mum).content)
    with patch.object(materials, 'MAX_MATERIAL_BYTES', base_size + 1):
        try:
            materials.set_image(row['id'], 'base_color', alpha_image(), 'mum')
        except ValueError as exc:
            assert '200 MB' in str(exc)
        else:
            raise AssertionError('base and opacity together must respect the live byte limit')
    assert (folder / 'material.json').read_bytes() == before
    assert not list((folder / 'maps').glob('*'))


def rgb_image(fmt='PNG'):
    out = io.BytesIO()
    Image.open(io.BytesIO(alpha_image())).convert('RGB').save(out, format=fmt)
    return out.getvalue()


def assert_flags(row, derived, mode):
    assert row['opacity_derived'] is derived
    assert row['opacity_derived_mode'] is mode
    assert 'opacity_derived' not in row['params']
    assert 'opacity_derived_mode' not in row['params']


def checked(response):
    assert response.status_code == 200, response.text
    return response.json()


def test_replacing_an_rgba_base_with_an_rgb_one_drops_the_derived_mask_and_mode():
    seed()
    with Ctx() as c:
        for data in (rgb_image(), rgb_image('JPEG'), alpha_image(solid=True)):
            row = checked(upload(c, create(c)['id'], alpha_image()))
            assert_flags(row, True, True)
            changed = checked(upload(c, row['id'], data))
            assert 'opacity' not in changed['maps']
            assert changed['params']['alpha_mode'] == 'opaque'
            assert changed['revision'] == row['revision'] + 1
            assert_flags(changed, False, False)
            manifest = materials.page_manifest()[row['id']]
            assert set(manifest) == {'kind', 'household', 'revision', 'maps', 'params'}
            assert not ({'opacity_derived', 'opacity_derived_mode'} & set(manifest['params']))


def test_echoing_the_opacity_map_preserves_derived_cleanup():
    seed()
    with Ctx() as c:
        row = checked(upload(c, create(c)['id'], alpha_image()))
        assert_flags(row, True, True)
        echoed = checked(c.client.patch(f"{API}/{row['id']}", headers=c.mum,
                                        json={'maps': {'opacity': row['maps']['opacity']}}))
        assert echoed['maps']['opacity'] == row['maps']['opacity']
        assert_flags(echoed, True, True)
        changed = checked(upload(c, row['id'], rgb_image()))
        assert 'opacity' not in changed['maps']
        assert changed['params']['alpha_mode'] == 'opaque'
        assert_flags(changed, False, False)


def test_replacing_an_rgba_base_with_another_rgba_resplits():
    seed()
    with Ctx() as c:
        row = checked(upload(c, create(c)['id'], alpha_image()))
        second = Image.open(io.BytesIO(alpha_image()))
        second.putpixel((3, 3), (180, 50, 90, 64))
        out = io.BytesIO()
        second.save(out, format='PNG')
        changed = checked(upload(c, row['id'], out.getvalue()))
        assert changed['maps']['opacity'] != row['maps']['opacity']
        mask = c.client.get(file_url(changed, 'opacity'), headers=c.mum)
        assert mask.status_code == 200
        assert Image.open(io.BytesIO(mask.content)).convert('L').getpixel((3, 3)) == 64
        assert changed['params']['alpha_mode'] == 'cutout'
        assert_flags(changed, True, True)
        assert changed['revision'] == row['revision'] + 1


def test_clearing_the_base_drops_the_derived_mask():
    seed()
    with Ctx() as c:
        row = checked(upload(c, create(c)['id'], alpha_image()))
        changed = checked(c.client.delete(f"{API}/{row['id']}/maps/base_color", headers=c.mum))
        assert changed['maps'] == {}
        assert changed['params']['alpha_mode'] == 'opaque'
        assert_flags(changed, False, False)
        assert changed['revision'] == row['revision'] + 1


def test_hand_uploaded_opacity_survives_base_changes():
    seed()
    with Ctx() as c:
        row = checked(upload(c, create(c)['id'], alpha_image()))
        # Even re-uploading the identical mask makes it the person's map.
        mask = c.client.get(file_url(row, 'opacity'), headers=c.mum).content
        row = checked(upload(c, row['id'], mask, 'opacity'))
        assert_flags(row, False, False)
        opacity = row['maps']['opacity']
        for data in (rgb_image(), alpha_image()):
            row = checked(upload(c, row['id'], data))
            assert row['maps']['opacity'] == opacity
            assert_flags(row, False, False)
        row = checked(c.client.delete(f"{API}/{row['id']}/maps/base_color", headers=c.mum))
        assert row['maps'] == {'opacity': opacity}
        assert row['params']['alpha_mode'] == 'cutout'


def test_mode_chosen_by_hand_survives_the_mask_being_dropped():
    seed()
    with Ctx() as c:
        for mode in ('blend', 'cutout', 'opaque'):
            row = checked(upload(c, create(c)['id'], alpha_image()))
            row = checked(c.client.patch(f"{API}/{row['id']}", headers=c.mum,
                                         json={'params': {'alpha_mode': mode}}))
            assert_flags(row, True, False)
            row = checked(upload(c, row['id'], alpha_image()))
            assert row['params']['alpha_mode'] == mode
            assert_flags(row, True, False)
            row = checked(upload(c, row['id'], rgb_image()))
            assert 'opacity' not in row['maps']
            assert row['params']['alpha_mode'] == mode
            assert_flags(row, False, False)


def test_undo_restores_base_mask_mode_together():
    seed()
    with Ctx() as c:
        row = checked(upload(c, create(c)['id'], alpha_image()))
        before = {key: row[key] for key in ('maps', 'params', 'opacity_derived', 'opacity_derived_mode')}
        changed = checked(upload(c, row['id']))
        assert changed['maps']['base_color'] != row['maps']['base_color']
        assert 'opacity' not in changed['maps']
        assert changed['params']['alpha_mode'] == 'opaque'
        assert_flags(changed, False, False)
        undone = checked(c.client.post(f"{API}/{row['id']}/undo", headers=c.mum))
        assert {key: undone[key] for key in before} == before
        for slot in ('base_color', 'opacity'):
            assert c.client.get(file_url(undone, slot), headers=c.mum).status_code == 200
        redone = checked(c.client.post(f"{API}/{row['id']}/redo", headers=c.mum))
        assert {key: redone[key] for key in before} == {key: changed[key] for key in before}


def test_manual_opacity_clear_releases_both_flags():
    seed()
    with Ctx() as c:
        row = checked(upload(c, create(c)['id'], alpha_image()))
        row = checked(c.client.delete(f"{API}/{row['id']}/maps/opacity", headers=c.mum))
        assert_flags(row, False, False)
        row = checked(upload(c, row['id'], rgb_image()))
        assert row['params']['alpha_mode'] == 'cutout'


def test_duplicate_and_source_reset_carry_flags():
    seed()
    with Ctx() as c:
        row = checked(upload(c, create(c)['id'], alpha_image()))
        copy = checked(c.client.post(f"{API}/{row['id']}/duplicate", headers=c.mum))
        assert_flags(copy, True, True)
        assert_flags(copy['source_snapshot'], True, True)
        changed = checked(upload(c, copy['id'], rgb_image()))
        assert_flags(changed, False, False)
        reset = checked(c.client.post(f"{API}/{copy['id']}/reset", headers=c.mum))
        assert reset['maps'] == copy['maps']
        assert reset['params'] == copy['params']
        assert_flags(reset, True, True)
        changed = checked(upload(c, copy['id'], rgb_image()))
        assert 'opacity' not in changed['maps'] and changed['params']['alpha_mode'] == 'opaque'


def test_staged_unlink_failure_does_not_fail_published_create():
    seed()
    mid = materials.new_id()
    materials.ingest_image(mid, 'base_color', alpha_image(), staged=True)
    original = Path.unlink
    def unlink(path, *args, **kwargs):
        if path == materials.root() / mid / 'staged.json':
            raise OSError('cleanup refused')
        return original(path, *args, **kwargs)
    with patch.object(Path, 'unlink', unlink):
        row = materials.create({'name': 'Published'}, 'mum', material_id=mid)
    assert materials.get(mid) == row
    assert (materials.root() / mid / 'material.json').exists()


def test_palette_transparency_splits_through_upload_route():
    seed()
    with Ctx() as c:
        palette = Image.new('P', (2, 1))
        palette.putpalette([40, 100, 160, 200, 80, 60] + [0] * 762)
        palette.putdata([0, 1])
        out = io.BytesIO()
        palette.save(out, format='PNG', transparency=0)
        row = checked(upload(c, create(c)['id'], out.getvalue()))
        assert row['params']['alpha_mode'] == 'cutout'
        mask = c.client.get(file_url(row, 'opacity'), headers=c.mum)
        assert mask.status_code == 200
        assert list(Image.open(io.BytesIO(mask.content)).convert('L').getdata()) == [0, 255]
        assert_flags(row, True, True)


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

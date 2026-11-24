"""Owner-export Chromium check. Pass the private export by path; never copy it.

python tests/test_house_twin_bake_tier_key_live.py --owner-export PATH
The test creates an isolated harness store and does not start or upload a bake.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile

os.environ.pop('HA_BASE_URL', None)

DEFAULT_EXPORT = Path(r'C:\Users\ffejn\Downloads\Current house.chauffeur-house-11-20-2016.json')


def owner_fake(model):
    """Derive registries in memory; never embed private entities/areas in code."""
    from house_ha_fake import FakeHA
    rooms = [r for b in model.get('buildings', []) for r in b.get('rooms', [])]
    rooms += model.get('site', {}).get('yard_rooms', [])
    areas = sorted({r['ha_area'] for r in rooms if r.get('ha_area')})
    entities = {}
    for fixture in model.get('effect_fixtures', []):
        for key in ('entity', 'sensor'):
            eid = fixture.get(key)
            if not eid:
                continue
            domain = eid.partition('.')[0]
            state, attrs = entities.setdefault(eid, ['on', {}])
            if domain == 'light':
                attrs.update(brightness=255, supported_color_modes=['brightness'])
            elif domain in ('climate', 'water_heater'):
                attrs.update(hvac_action='heating', current_temperature=70, temperature=80)
            if key == 'sensor':
                value = (fixture.get('sensor_min', 0) + fixture.get('sensor_max', 1)) / 2
                if fixture.get('sensor_attribute'):
                    attrs[fixture['sensor_attribute']] = value
                else:
                    state = str(value)
            entities[eid][0] = state
    return FakeHA(
        areas=[{'area_id': aid, 'name': aid, 'floor_id': 'owner-floor'} for aid in areas],
        floors=[{'floor_id': 'owner-floor', 'name': 'Harness floor', 'level': 0}],
        devices=[{'id': f'owner-effect-{i}', 'name': f'Effect entity {i}',
                  'area_id': areas[0] if areas else None, 'entities': [(eid, state, attrs)]}
                 for i, (eid, (state, attrs)) in enumerate(sorted(entities.items()))])


def seed_owner(model):
    # H.seed/push_round accepts drafting plans: twin_plan.normalize deliberately
    # drops effect/light fixtures. Use the connected-model write path instead.
    from services import twin_store
    twin_store.update_model(lambda _: deepcopy(model), kind='build')
    return twin_store.current()


PAGE_DIAGNOSTICS = """async () => {
    const view=window.__twin, plan=view?.plan || {}, fixtures=plan.effect_fixtures || [];
    const {rippleSources}=await import(new URL((window.chfBase || '/') +
        'static/twin/effects/water_ripples.js', location.href).href);
    const yard=view?.scene.getObjectByName('yard'), state=view?.bake?.state();
    return {key:state?.key || null, tier:view?.tier || null, baking:!!state?.baking,
        workers:window.__tierAtlasWorkers || 0, fixtureCount:fixtures.length,
        orphanedFlags:fixtures.map(f=>!!f.orphaned),
        rippleSources:rippleSources(plan).length,
        simulatedBodies:yard?.userData.water?.simulations.size || 0};
}"""


def check_tiers(served, H, expected, keys, require):
    from live_app import goto_retry
    writes, diagnostics, errors = [], {}, {}
    # Each factory call starts an isolated Chromium context: no inherited IDB.
    # Force a server-atlas miss too, so both tiers exercise their own worker.
    for tier in ('low', 'high'):
        with served.browser(launch_args=H.GPU_ARGS) as page:
            H.signed_in(page)
            page.add_init_script("""window.__tierAtlasWorkers=0;
                const NativeWorker=window.Worker;
                window.Worker=class extends NativeWorker {
                    constructor(url,options){super(url,options);
                        if(String(url).includes('/bake/atlas_worker'))window.__tierAtlasWorkers++;
                    }
                };""")
            page.route('**/api/house/atlases/**', lambda route: route.fulfill(
                status=404 if route.request.method == 'GET' else 403, body=''))
            page.on('request', lambda request: writes.append(request.url)
                    if '/api/house/bakes' in request.url and request.method != 'GET' else None)
            try:
                goto_retry(page, served.url(f'house/twin?tier={tier}&test=1'))
                page.wait_for_function('window.__twin?.ready === true', timeout=180000)
                page.wait_for_function("() => window.__twin?.yardSettling === false && !window.__twin.yardError"
                                       " && window.__twin.scene.getObjectByName('yard')?.children.length > 0",
                                       timeout=180000)
                page.wait_for_function('() => /^[0-9a-f]{32}$/.test(window.__twin?.bake?.state().key || "")',
                                       timeout=180000)
            except Exception as exc:
                # Still collect this tier and attempt the other one, so failures
                # carry both keys rather than hiding the useful comparison.
                errors[tier] = f'{type(exc).__name__}: {exc}'
            try:
                diagnostics[tier] = page.evaluate(PAGE_DIAGNOSTICS)
                keys[tier] = diagnostics[tier]['key']
            except Exception as exc:
                errors[tier] = errors.get(tier, '') + f' diagnostics: {type(exc).__name__}: {exc}'
    print('TIER_DIAGNOSTICS ' + json.dumps({'keys': keys, 'tiers': diagnostics, 'errors': errors}), flush=True)
    detail = json.dumps(diagnostics)
    require(not errors, f'both tiers must finish loading; errors={errors}; diagnostics={detail}')
    for tier, row in diagnostics.items():
        require(row['tier'] == tier, f'{tier}: requested tier is active; diagnostics={detail}')
        require(not row['baking'], f'{tier}: viewer remains read only; diagnostics={detail}')
        require(row['workers'] > 0, f'{tier}: must build its own atlas; diagnostics={detail}')
        require(row['fixtureCount'] == len(expected), f'{tier}: all exported effects reach the page; diagnostics={detail}')
        require(row['orphanedFlags'] == expected, f'{tier}: fixture orphan flags match the export; diagnostics={detail}')
        require(row['rippleSources'] > 0, f'{tier}: rippleSources(plan).length must be positive; diagnostics={detail}')
    require(diagnostics['high']['simulatedBodies'] > 0,
            f'High yard must actually create water simulations; diagnostics={detail}')
    require(keys['low'] == keys['high'], f'Low and High atlas keys differ; diagnostics={detail}')
    require(not writes, 'viewer must never acquire a bake lease or upload pages')
    print(f"  ok   owner_export_high_low_same_atlas_key ({keys['high']})")
    print('1/1 passed')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--owner-export', type=Path, default=DEFAULT_EXPORT)
    args = parser.parse_args()
    keys = {'low': None, 'high': None}

    def require(cond, message):
        if not cond:
            raise AssertionError(f'{message}; keys={json.dumps(keys)}')

    require(args.owner_export.is_file(), 'Pass --owner-export with the existing house export path')
    model = json.loads(args.owner_export.read_text(encoding='utf-8'))['model']
    expected = [bool(f.get('orphaned')) for f in model.get('effect_fixtures', [])]
    require(bool(expected), 'the owner export must contain effect fixtures')
    # Owner data stays outside the repo even when TEMP uses the sandbox workaround.
    with tempfile.TemporaryDirectory(prefix='chauffeur_owner_tier_',
            dir=Path(os.environ['LOCALAPPDATA']) / 'Temp', ignore_cleanup_errors=True) as data:
        os.environ['CHAUFFEUR_DATA_DIR'] = data
        import house_editor_model_harness as H
        fake = owner_fake(model).install()
        served = None
        try:
            served = H.serve()
            require(served is not None, 'This acceptance test requires Chromium and Playwright')
            seeded = seed_owner(model)
            require([bool(f.get('orphaned')) for f in seeded.get('effect_fixtures', [])] == expected,
                    'connected-model seeding must retain every effect and its orphan flag')
            print('HARNESS_HA ' + json.dumps({'areas': len(fake.areas), 'entities': len(fake.states),
                'fixtures': len(expected), 'orphaned': sum(expected)}), flush=True)
            check_tiers(served, H, expected, keys, require)
        finally:
            if served is not None:
                served.stop()
            fake.uninstall()


if __name__ == '__main__':
    main()

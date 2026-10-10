"""Pro pool exists, mission tier never leaks into free pools, key routing."""
from harness import check
from services import model_pools


def scenario_pro_pool_and_mission_tier():
    s = {}
    check(model_pools.DEFAULT_POOLS['pro'] == ["gemini-3.1-pro-preview"],
          "pro pool defaults to the live preview id (2.5-pro is closed to new users)")
    models = model_pools.models_for('mission', s)
    check(models == ["gemini-3.1-pro-preview"],
          f"mission tier serves ONLY the pro pool, got {models}")
    free = set()
    for t in ('interactive', 'background', 'heavy', 'vision'):
        free.update(model_pools.models_for(t, s))
    check(not free.intersection(set(models)),
          "no free tier ever serves a pro model")


def scenario_mission_flash_is_pure_flash():
    models = model_pools.models_for('mission_flash', {})
    check(all('flash' in m and 'lite' not in m for m in models),
          f"mission_flash chain is flash models only, got {models}")


def scenario_key_routing():
    s = {'llm_gemini_api_key': 'FREE', 'llm_gemini_paid_api_key': 'PAID'}
    check(model_pools.api_key_for_pool('pro', s) == 'PAID', "pro pool gets the paid key")
    for p in ('lite', 'flash', 'gemma'):
        check(model_pools.api_key_for_pool(p, s) == 'FREE', f"{p} pool gets the free key")
    check(model_pools.api_key_for_pool('pro', {'llm_gemini_api_key': 'FREE'}) == '',
          "no paid key = empty string, never a silent fall back to the free key")


def scenario_pro_pool_overridable():
    s = {'model_pool_pro': 'my-pro-model'}
    check(model_pools.models_for('mission', s) == ['my-pro-model'],
          "model_pool_pro setting overrides the default like every other pool")


def scenario_retired_models_are_out_of_the_pools_and_out_of_settings():
    """Google retired gemini-3.5-flash (the household's email, 2026-10-09). A
    retired id in a pool default costs a 404 round trip per call until the 6h
    cooldown; a retired id in the trip planner's own setting fails every
    trip. So: the id is gone from the defaults, named in RETIRED_MODELS, and
    the migration moves a stored setting off it."""
    from services import storage, migrations
    check('gemini-3.5-flash' in model_pools.RETIRED_MODELS, "the retired id is named")
    for pool, models in model_pools.DEFAULT_POOLS.items():
        for m in model_pools.RETIRED_MODELS:
            check(m not in models, f"retired {m} still in the {pool} pool defaults")
    # harness.py pins storage.get_settings to a fixed dict; this scenario
    # needs the real settings row, so read it straight from the table.
    patched = storage.get_settings
    storage.get_settings = lambda: (dict(storage.settings_table.all()[0]) if storage.settings_table.all() else {})
    try:
        storage.update_settings({'llm_gemini_model': 'gemini-3.5-flash', 'calendar_ids': []})
        migrations.migrate_retired_gemini_models_v2499324()
        check(storage.get_settings().get('llm_gemini_model') == 'gemini-3.5-flash-lite',
              f"a stored retired model was not moved: {storage.get_settings().get('llm_gemini_model')}")
        check(storage.get_settings().get('calendar_ids') == [], "the migration rewrote other settings")
        migrations.migrate_retired_gemini_models_v2499324()     # idempotent, and leaves a live id alone
        check(storage.get_settings().get('llm_gemini_model') == 'gemini-3.5-flash-lite', "second run changed it")
    finally:
        storage.get_settings = patched


if __name__ == '__main__':
    scenario_retired_models_are_out_of_the_pools_and_out_of_settings()
    scenario_pro_pool_and_mission_tier()
    scenario_mission_flash_is_pure_flash()
    scenario_key_routing()
    scenario_pro_pool_overridable()
    print("test_missions_pools OK")

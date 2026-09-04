"""Pro pool exists, mission tier never leaks into free pools, key routing."""
from harness import check
from services import model_pools


def scenario_pro_pool_and_mission_tier():
    s = {}
    check(model_pools.DEFAULT_POOLS['pro'] == ["gemini-3.1-pro", "gemini-2.5-pro"],
          "pro pool defaults to 3.1-pro then 2.5-pro")
    models = model_pools.models_for('mission', s)
    check(models == ["gemini-3.1-pro", "gemini-2.5-pro"],
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


if __name__ == '__main__':
    scenario_pro_pool_and_mission_tier()
    scenario_mission_flash_is_pure_flash()
    scenario_key_routing()
    scenario_pro_pool_overridable()
    print("test_missions_pools OK")

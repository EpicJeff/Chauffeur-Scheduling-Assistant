# chauffeur/tests/test_provider_settings.py
"""The selector's settings persist, reach the page, and the test route reaches the branch."""
import os, sys, tempfile
os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_provset_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from harness import check  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402
from services import storage, settings_registry as reg, llm  # noqa: E402

NEW = {'llm_provider': 'anthropic', 'llm_anthropic_api_key': 'A', 'llm_openai_api_key': 'O',
       'llm_anthropic_daily_cap': 42, 'llm_openai_daily_cap': 0,
       'model_pool_lite': 'anthropic:claude-haiku-5-5', 'model_pool_flash': 'gemini-3.8-flash', 'model_pool_gemma': ''}


def _client():
    return TestClient(main.app)


def _parent_headers(mid='p1', name='Pat'):
    """The admin gate: a parent's member token, the way test_paid_fallback_ui.py does it."""
    storage.members_table.truncate()
    storage.add_member({'id': mid, 'name': name, 'role': 'parent'})
    return {'X-Member-Token': storage.create_member_token(mid)}


def scenario_every_new_field_round_trips():
    c = _client()
    r = c.post('/api/settings', json=NEW, headers=_parent_headers())
    check(r.status_code == 200, r.text)
    # harness.py stubs storage.get_settings; read what the table really holds
    got = dict(storage.settings_table.all()[0]) if storage.settings_table.all() else {}
    for k, v in NEW.items():
        check(got.get(k) == v, f'{k} did not persist: {got.get(k)!r}')


def scenario_registry_declares_them_reachable():
    keys = {e['key'] for e in reg.ENTRIES}
    for k in NEW:
        check(k in keys, f'{k} missing from the registry')
    unreachable = {e['key'] for e in reg.audit_ui()['unreachable']}
    check(not (set(NEW) & unreachable), f'unreachable on their page: {set(NEW) & unreachable}')


def scenario_config_page_offers_four_providers_and_test_route_branches():
    c = _client()
    h = _parent_headers()
    html = c.get('/config', headers=h).text
    for opt in ('value="gemini"', 'value="anthropic"', 'value="openai"', 'value="ollama"'):
        check(opt in html, f'selector lacks {opt}')
    seen = []
    real = llm.test_llm_connection
    llm.test_llm_connection = lambda provider, url=None, api_key=None, model=None: (seen.append(provider) or (True, 'ok'))
    try:
        r = c.post('/api/settings/test_llm', json={'provider': 'anthropic', 'api_key': 'A'}, headers=h)
        check(r.status_code == 200 and seen == ['anthropic'], f'{r.text} {seen}')
    finally:
        llm.test_llm_connection = real


if __name__ == '__main__':
    scenario_every_new_field_round_trips()
    scenario_registry_declares_them_reachable()
    scenario_config_page_offers_four_providers_and_test_route_branches()
    print('test_provider_settings OK')

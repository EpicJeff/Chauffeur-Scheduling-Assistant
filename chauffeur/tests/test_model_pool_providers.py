# chauffeur/tests/test_model_pool_providers.py
"""A provider is a column of the tier table; ids carry their provider; keys follow the id."""
import time
from harness import check
from services import model_pools as mp

CLAUDE = {'llm_provider': 'anthropic', 'llm_anthropic_api_key': 'A'}
OPENAI = {'llm_provider': 'openai', 'llm_openai_api_key': 'O'}
GEMINI = {'llm_gemini_api_key': 'FREE', 'llm_gemini_paid_api_key': 'PAID'}


def scenario_split_model():
    check(mp.split_model('anthropic:claude-haiku-5-5') == ('anthropic', 'claude-haiku-5-5'), 'claude prefix')
    check(mp.split_model('openai:gpt-6-luna') == ('openai', 'gpt-6-luna'), 'openai prefix')
    check(mp.split_model('gemini-3.8-flash') == ('gemini', 'gemini-3.8-flash'), 'bare id is gemini')
    check(mp.split_model('models/gemini-3.8-flash') == ('gemini', 'models/gemini-3.8-flash'), 'a models/ path is not a provider prefix')


def scenario_provider_tables_fill_the_tiers():
    mp.reset_cooldowns()
    check(mp.models_for('interactive', CLAUDE) == ['anthropic:claude-haiku-5-5'], f"claude chat: {mp.models_for('interactive', CLAUDE)}")
    check(mp.models_for('heavy', CLAUDE) == ['anthropic:claude-sonnet-5-5', 'anthropic:claude-haiku-5-5'], 'claude heavy = flash then lite, no gemma')
    check(mp.models_for('mission', CLAUDE) == ['anthropic:claude-opus-5-5'], 'claude mission = pro')
    check(mp.models_for('browse', CLAUDE) == ['anthropic:claude-sonnet-5-5'], 'claude browse = cu')
    check(mp.models_for('background', CLAUDE) == ['anthropic:claude-haiku-5-5'], 'empty gemma contributes nothing')
    check(mp.models_for('interactive', OPENAI) == ['openai:gpt-6-luna'], 'openai chat')
    check(mp.models_for('heavy', OPENAI) == ['openai:gpt-6.1-sol', 'openai:gpt-6-luna'], 'openai heavy')
    check(mp.models_for('mission', OPENAI) == ['openai:gpt-6.1-sol'], 'openai mission')
    check(mp.models_for('interactive', GEMINI) == list(mp.DEFAULT_POOLS['lite']) + mp.models_for('interactive', GEMINI)[3:],
          'gemini chain unchanged (lite first)')
    check(all(mp.split_model(m)[0] == 'gemini' for m in mp.models_for('heavy', GEMINI)), 'gemini ids stay bare')


def scenario_overrides_mix_and_win():
    mp.reset_cooldowns()
    s = {**GEMINI, 'model_pool_lite': 'anthropic:claude-haiku-5-5, gemini-3.5-flash-lite,'}
    got = mp.models_for('interactive', s)
    check(got[:2] == ['anthropic:claude-haiku-5-5', 'gemini-3.5-flash-lite'], f'override mixes providers in order: {got}')
    check('' not in got and all(m == m.strip() for m in got), 'trailing comma and spaces never yield an empty or padded id')
    s2 = {**CLAUDE, 'model_pool_flash': 'gemini-3.8-flash'}
    check(mp.models_for('mind', s2) == ['gemini-3.8-flash'], 'a bare override under Claude is still a Gemini id')


def scenario_key_routing_follows_the_id():
    check(mp.api_key_for('anthropic:claude-haiku-5-5', 'lite', {**CLAUDE, **GEMINI}) == 'A', 'claude id -> claude key')
    check(mp.api_key_for('openai:gpt-6-luna', 'lite', {**OPENAI, **GEMINI}) == 'O', 'openai id -> openai key')
    check(mp.api_key_for('gemini-3.1-pro-preview', 'pro', GEMINI) == 'PAID', 'gemini pro -> paid key')
    check(mp.api_key_for('gemini-3.8-flash', 'cu', GEMINI) == 'PAID', 'gemini cu -> paid key')
    check(mp.api_key_for('gemini-3.8-flash', 'flash', GEMINI) == 'FREE', 'gemini flash -> free key')
    check(mp.api_key_for('anthropic:claude-opus-5-5', 'pro', CLAUDE) == 'A', 'claude pro -> the one claude key')
    check(mp.api_key_for('anthropic:claude-opus-5-5', 'pro', {'llm_provider': 'anthropic'}) == '', 'no key = empty, never another provider key')
    # The old helper keeps its signature and follows the selected table.
    check(mp.api_key_for_pool('pro', {**GEMINI}) == 'PAID', 'gemini pro pool -> paid')
    check(mp.api_key_for_pool('pro', {**CLAUDE}) == 'A', 'claude pro pool -> claude key')
    check(mp.api_key_for_pool('cu', {**OPENAI}) == 'O', 'openai cu pool -> openai key')


def scenario_credentials_and_has_credentials():
    mp.reset_cooldowns()
    check(mp.credentials('interactive', CLAUDE) == ('anthropic:claude-haiku-5-5', 'A'), 'credentials = first model + its key')
    check(mp.credentials('interactive', {'llm_provider': 'anthropic'}) == ('', ''), 'no key -> empty pair')
    check(mp.credentials('mission', GEMINI) == ('gemini-3.1-pro-preview', 'PAID'), 'gemini mission credentials = pro + paid')
    check(mp.has_credentials(CLAUDE) and mp.has_credentials(OPENAI) and mp.has_credentials({'llm_gemini_api_key': 'k'}), 'each provider with its key')
    check(not mp.has_credentials({'llm_provider': 'anthropic', 'llm_gemini_api_key': 'k'}), 'a gemini key does not satisfy a claude selection')
    check(not mp.has_credentials({'llm_provider': 'gemini', 'llm_anthropic_api_key': 'A'}), 'switching back to gemini with no gemini key is honest')
    check(mp.has_credentials({'llm_provider': 'ollama'}), 'ollama needs no key')


def scenario_cooldown_rules_for_prefixed_ids():
    mp.reset_cooldowns()
    mp.note_failure('anthropic:claude-haiku-5-5', '429 Too Many Requests: per day quota exceeded')
    until = mp._cooldowns['anthropic:claude-haiku-5-5']
    check(0 < until - time.time() <= 121, 'a paid provider 429 cools two minutes, never until midnight Pacific')
    mp.note_failure('gemini-3.8-flash', '429 ... perDay ...')
    check(mp._cooldowns['gemini-3.8-flash'] - time.time() > 3600, 'the gemini per-day rule is untouched')
    check(not mp.is_gemma('anthropic:claude-haiku-5-5'), 'prefixed ids are never gemma')
    mp.reset_cooldowns()


def scenario_paid_fallback_is_gemini_only():
    calls = []
    def chain(key, paid):
        calls.append((key, paid))
        return {'error': '503', 'transient': True}
    s = {**CLAUDE, 'llm_gemini_paid_api_key': 'PAID', 'llm_paid_fallback_mode': 'auto'}
    mp.with_paid_fallback('interactive', 'A', s, False, chain)
    check(calls == [('A', False)], f'no paid-key retry when the first candidate is prefixed: {calls}')


def scenario_voice_lite_pool_per_provider():
    from services import app_voice
    class Turn:
        def remaining(self): return 30
    tok = app_voice.current.set(Turn())
    try:
        mp.reset_cooldowns()
        check(mp.models_for('interactive', CLAUDE) == ['anthropic:claude-haiku-5-5'], 'a voice turn on claude is haiku')
        check(mp.models_for('interactive', OPENAI) == ['openai:gpt-6-luna'], 'a voice turn on openai is luna')
        check(all('flash-lite' in m for m in mp.models_for('interactive', GEMINI)), 'a voice turn on gemini is flash-lite only')
        check(mp.is_lite('anthropic:claude-haiku-5-5', CLAUDE) and not mp.is_lite('anthropic:claude-sonnet-5-5', CLAUDE), 'is_lite reads the provider lite pool')
    finally:
        app_voice.current.reset(tok)


def scenario_candidates_dispatch_through_call_model():
    from services import llm
    seen = []
    def fake_call_model(model, key, system_prompt, user_prompt, **kw):
        seen.append((model, key))
        return {'ok': True}
    real = llm.call_model
    llm.call_model = fake_call_model
    try:
        mp.reset_cooldowns()
        attempts = []
        res = mp.call_pool_json('interactive', 'A', 'sys', 'hi', settings=CLAUDE, attempts=attempts)
        check(res.get('_model') == 'anthropic:claude-haiku-5-5', f'the prefixed id is the _model: {res}')
        check(seen == [('anthropic:claude-haiku-5-5', 'A')], f'call_model got the prefixed id and the claude key: {seen}')
        # `attempts` is written at the wire by llm_budget.urlopen (Task 3's tests); a faked call_model sends nothing.
    finally:
        llm.call_model = real


def scenario_pooled_or_direct_is_provider_aware():
    from services import llm
    seen = []
    real = llm.call_model
    llm.call_model = lambda model, key, *a, **kw: (seen.append(model) or {'ok': 1})
    try:
        mp.reset_cooldowns()
        mp.pooled_or_direct('anthropic', '', 'A', 'ignored-model', 'heavy', 'sys', 'user', settings=CLAUDE)
        check(seen == ['anthropic:claude-sonnet-5-5'], f'claude goes through the heavy chain: {seen}')
    finally:
        llm.call_model = real


if __name__ == '__main__':
    scenario_split_model()
    scenario_provider_tables_fill_the_tiers()
    scenario_overrides_mix_and_win()
    scenario_key_routing_follows_the_id()
    scenario_credentials_and_has_credentials()
    scenario_cooldown_rules_for_prefixed_ids()
    scenario_paid_fallback_is_gemini_only()
    scenario_voice_lite_pool_per_provider()
    scenario_candidates_dispatch_through_call_model()
    scenario_pooled_or_direct_is_provider_aware()
    print('test_model_pool_providers OK')

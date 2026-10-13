# Model Provider Selector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One Config › AI selector (Gemini | Claude | OpenAI | Ollama) moves every model call the app makes, browse missions and web research included, onto the chosen provider, with the Gemini free-tier machinery left in place.

**Architecture:** A provider is a column of the existing tier/pool table in `model_pools`; model ids carry a `anthropic:` / `openai:` prefix (bare = Gemini) everywhere they travel. Two raw-urllib wire branches join the Gemini and Ollama ones in `llm.py`; `llm_budget` meters the two new hosts and enforces a per-provider daily cap. Web research and browse missions get an adapter per provider behind the same seams they use today (`_gemini_grounded`, `_model_step`), plus five provider-neutral runner changes.

**Tech Stack:** Python 3 / FastAPI, `urllib` (no provider SDKs), SQLite via `llm_budget`, Jinja + Alpine (`config.html`), precompiled Tailwind, Playwright (browse tests). Tests are plain scripts run from `chauffeur/` with `HA_BASE_URL` unset.

**Spec:** `docs/superpowers/specs/2026-10-13-model-provider-selector-design.md` (revised after the Codex review; its §7 "observation turn" mechanism is refined here into two runner call names, `look` and `refuse`, so a turn keeps its one-to-one order between provider tool ids and runner results).

## Global Constraints

- Every test runs as `python tests/test_x.py` from `chauffeur/` with `HA_BASE_URL` unset; gate = the change's own tests plus the named neighbours, never the whole suite.
- No provider SDK: `urllib` + `llm_budget.urlopen` for every HTTP call to a model host.
- Claude requests never carry `temperature` or a `thinking` field; effort via `output_config.effort`. OpenAI requests never carry `temperature`; effort via `reasoning.effort`.
- Default effort: `low` for lite and flash models, `medium` for the pro pool; `thinking_level` maps low→low, medium→medium, high→high.
- Default `max_tokens` / `max_output_tokens` when none given: 8192.
- Model ids: Claude `claude-haiku-5-5` (lite), `claude-sonnet-5-5` (flash, cu), `claude-opus-5-5` (pro). OpenAI `gpt-6-luna` (lite), `gpt-6.1-sol` (flash, pro, cu). OpenAI ids are confirmed against `GET https://api.openai.com/v1/models` with the real key during Task 2's connection-test step before the table is committed; a missing id is a stop.
- Prefixed form everywhere a model id travels: `anthropic:claude-haiku-5-5`, `openai:gpt-6-luna`. Bare id = Gemini.
- The paid Gemini key is read only inside `model_pools` (source-pin test `tests/test_missions_pins.py`).
- Daily cap settings `llm_anthropic_daily_cap`, `llm_openai_daily_cap`, default 500, 0 = none, counted over the process-local day (same clock as `paid_fallback`).
- New settings: typed field on `Settings` (`models/schemas.py`) + registry entry (`services/settings_registry.py`, group `ai`, page `config`, anchor `general`) + a control in the AI section of `templates/config.html`; `python tools/build_tailwind.py` after the template change.
- Never `alert`/`confirm`/`prompt` in templates. Never remove anything a person can do today.
- Commit after each task: `git commit` with the task's subject, bump `chauffeur/config.yaml` only in the final task (Claude Code's rule).

## Review Focus

Inputs the spec implies but the tasks below would not otherwise exercise; each has its pin test added to the owning task:

1. A stored `model_pool_lite` override with a trailing comma or spaces (`"anthropic:claude-haiku-5-5, "`) must yield one clean id, not an empty entry that becomes a 404 → Task 1.
2. A Claude response whose only content is a `thinking` block (empty text under `display: omitted`) with `stop_reason: end_turn` must be reported as an empty-text error, not a JSON parse crash → Task 2.
3. An OpenAI response with `status: "incomplete"` and no `strict_json` must return the partial text, not raise → Task 2.
4. A provider cap of `0` must never defer, and a cap reached at 23:59 must lift at 00:00 local → Task 3.
5. Switching the selector from Claude back to Gemini with no Gemini key must make `has_credentials` false and the Intake page say so, not crash on an empty account hash → Task 5.

---

### Task 1: Provider tables, prefixed ids and key routing in `model_pools`

**Files:**
- Modify: `chauffeur/services/model_pools.py` (`DEFAULT_POOLS` region lines 58-80, `_pool` lines 96-108, `api_key_for_pool` lines 220-230, `note_failure` lines 240-280, `is_gemma`/`models_for` lines 281-308, `with_paid_fallback` lines 311-337, `_call_candidates` lines 400-485, `pooled_or_direct` lines 488-499)
- Create: `chauffeur/tests/test_model_pool_providers.py`
- Neighbours to keep green: `tests/test_missions_pools.py`, `tests/test_model_pool_overload.py`, `tests/test_missions_pins.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `PROVIDERS = ('gemini', 'anthropic', 'openai')`
  - `PROVIDER_POOLS: dict[str, dict[str, list[str]]]` for `anthropic` and `openai` (bare ids); `DEFAULT_POOLS` stays Gemini.
  - `split_model(model_id: str) -> tuple[str, str]` → `('anthropic', 'claude-haiku-5-5')`, `('gemini', 'gemini-3.8-flash')`.
  - `provider(settings: dict) -> str` → `llm_provider` or `'gemini'` (returns `'ollama'` as is).
  - `api_key_for(model_id: str, pool: str, settings: dict) -> str`
  - `api_key_for_pool(pool: str, settings: dict) -> str` (unchanged signature, now provider-aware)
  - `credentials(tier: str, settings: dict) -> tuple[str, str]` → `(model_id, api_key)`; `('', '')` when the selected provider has no key.
  - `has_credentials(settings: dict) -> bool`
  - `is_lite(model_id: str, settings: dict) -> bool` → the model is in the selected provider's lite pool (voice path).
  - `_call_candidates` calls `llm.call_model(model, api_key, ...)` (Task 2) instead of `_llm._call_llm_json('gemini', ...)`.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd chauffeur && python tests/test_model_pool_providers.py`
Expected: `AttributeError: module 'services.model_pools' has no attribute 'split_model'`

- [ ] **Step 3: Implement the tables, the parser and the key helpers**

In `model_pools.py`, after `DEFAULT_POOLS`:

```python
PROVIDERS = ('gemini', 'anthropic', 'openai')

# Each paid provider is a column of the same tier table (spec §1). Bare ids
# here; the prefix is stamped on by _pool so every id that leaves this module
# says where it goes. Gemma is a Gemini free-tier pool: empty elsewhere.
PROVIDER_POOLS = {
    'anthropic': {
        'lite': ['claude-haiku-5-5'],
        'flash': ['claude-sonnet-5-5'],
        'gemma': [],
        'pro': ['claude-opus-5-5'],
        'cu': ['claude-sonnet-5-5'],
    },
    'openai': {
        'lite': ['gpt-6-luna'],
        'flash': ['gpt-6.1-sol'],
        'gemma': [],
        'pro': ['gpt-6.1-sol'],
        'cu': ['gpt-6.1-sol'],
    },
}


def split_model(model_id: str):
    """('anthropic', 'claude-haiku-5-5') for a prefixed id; a bare id is Gemini.
    A 'models/' path is Gemini's own namespace, never a provider prefix."""
    head, sep, rest = (model_id or '').partition(':')
    if sep and head in PROVIDER_POOLS and rest:
        return head, rest
    return 'gemini', model_id or ''


def provider(settings: dict) -> str:
    return (settings or {}).get('llm_provider') or 'gemini'


def _prefixed(prov: str, bare: str) -> str:
    return bare if prov == 'gemini' else f'{prov}:{bare}'
```

Replace `_pool`:

```python
def _pool(name: str, settings: dict) -> list:
    raw = (settings or {}).get(f'model_pool_{name}') or ''
    if raw.strip():
        return [m.strip() for m in raw.split(',') if m.strip()]
    prov = provider(settings)
    if prov in PROVIDER_POOLS:
        return [_prefixed(prov, m) for m in PROVIDER_POOLS[prov].get(name, [])]
    if name == 'gemma':
        found = _discovered_gemma()
        if found:
            keep = [m for m in DEFAULT_POOLS['gemma'] if m in found]
            return keep + [m for m in found if m not in keep][:max(0, GEMMA_POOL_SIZE - len(keep))]
    return list(DEFAULT_POOLS[name])
```

Replace `api_key_for_pool` with the pair:

```python
def api_key_for(model_id: str, pool_name: str, settings: dict) -> str:
    """The key an id bills. Gemini: the pro and cu pools bill the paid key,
    every other pool the free key. This helper is the ONLY reader of
    llm_gemini_paid_api_key (source-pin test in test_missions_pins.py).
    A missing key returns '' so a caller fails loudly instead of quietly
    billing another provider's key."""
    s = settings or {}
    prov, _ = split_model(model_id)
    if prov == 'anthropic':
        return s.get('llm_anthropic_api_key', '') or ''
    if prov == 'openai':
        return s.get('llm_openai_api_key', '') or ''
    if pool_name in ('pro', 'cu'):
        return s.get('llm_gemini_paid_api_key', '') or ''
    return s.get('llm_gemini_api_key', '') or ''


def api_key_for_pool(pool_name: str, settings: dict) -> str:
    """The key for a pool's first model under the selected table. Kept with
    its old signature for the ten callers that only know a pool name."""
    models = _pool(pool_name, settings)
    return api_key_for(models[0] if models else '', pool_name, settings)


def credentials(tier: str, settings: dict = None):
    """(model_id, api_key) for a tier under the selected provider, or ('', '')
    when that provider has no key. Replaces the fifteen 'no Gemini key'
    preflights (spec §1): a Claude household is set up when it has a Claude key."""
    if settings is None:
        from services.storage import get_settings
        settings = get_settings()
    chain = TIER_CHAINS.get(tier) or ['lite']
    model = resolve_model(tier, settings)
    key = api_key_for(model, chain[0], settings)
    return (model, key) if key else ('', '')


def has_credentials(settings: dict = None) -> bool:
    if settings is None:
        from services.storage import get_settings
        settings = get_settings()
    prov = provider(settings)
    if prov == 'ollama':
        return True
    return bool(credentials('interactive', settings)[1])


def is_lite(model_id: str, settings: dict) -> bool:
    return model_id in _pool('lite', settings)
```

In `note_failure`, make the per-day rule Gemini-only:

```python
    if "429" in err:
        prov, _ = split_model(model)
        if prov == 'gemini' and ("perday" in low or "per day" in low or "daily" in low):
            until = _next_midnight_pacific()
            ...
        else:
            until = time.time() + 120
```

In `models_for`, the phone branch:

```python
    if phone_voice.get() is not None:
        chain = list(dict.fromkeys(_pool('lite', settings)))
```

(Gemini's lite pool is already flash-lite only; the explicit `'flash-lite' in m` filter stays for bare ids: `chain = [m for m in chain if split_model(m)[0] != 'gemini' or 'flash-lite' in m]`.)

In `with_paid_fallback`, first lines:

```python
    if background or tier not in ('interactive', 'vision', 'heavy'):
        return call_chain(api_key, False)
    if settings is None:
        from services.storage import get_settings
        settings = get_settings()
    first = models_for(tier, settings)
    if first and split_model(first[0])[0] != 'gemini':
        return call_chain(api_key, False)   # paid providers have nothing to fall over to (spec §3)
```

In `_call_candidates`, replace the `_llm._call_llm_json('gemini', '', api_key, model, ...)` call with:

```python
                res = _llm.call_model(model, api_key, system_prompt, user_prompt,
                                      temperature=temperature, timeout_s=t, images=images,
                                      transient_retries=0, strict_json=strict_json,
                                      **({"response_schema": response_schema} if response_schema is not None else {}),
                                      max_output_tokens=max_output_tokens,
                                      **({"thinking_level": thinking_level} if thinking_level is not None else {}))
```

`pooled_or_direct`:

```python
def pooled_or_direct(provider_name, url, api_key, model, tier, system_prompt, user_prompt,
                     temperature=0.1, timeout_s=180, settings=None):
    """Ollama keeps its one configured model; every other provider goes
    through the tier's pool chain on the selected table (retries, cooldowns,
    fallback), the passed model ignored."""
    if provider_name != 'ollama':
        return call_pool_json(tier, api_key, system_prompt, user_prompt,
                              temperature=temperature, timeout_s=timeout_s, settings=settings)
    from services import llm as _llm
    return _llm._call_llm_json(provider_name, url, api_key, model, system_prompt,
                               user_prompt, temperature=temperature, timeout_s=timeout_s)
```

Also `_maybe_discover`: return at once when `provider(settings) != 'gemini'` (discovery reads the Gemini key).

- [ ] **Step 4: Add a temporary `call_model` stub so Task 1 can pass before Task 2**

In `services/llm.py`, add (Task 2 replaces the body):

```python
def call_model(model_id: str, api_key: str, system_prompt: str, user_prompt: str, text: bool = False, **kw) -> dict:
    """Dispatch by the id's provider prefix (model_pools.split_model)."""
    from services import model_pools
    prov, bare = model_pools.split_model(model_id)
    return _call_llm_json(prov, '', api_key, bare, system_prompt, user_prompt, **kw)
```

- [ ] **Step 5: Run the new test and the neighbours**

Run: `cd chauffeur && python tests/test_model_pool_providers.py && python tests/test_missions_pools.py && python tests/test_model_pool_overload.py && python tests/test_missions_pins.py`
Expected: all four print their OK line. If `test_missions_pins` flags `api_key_for` as a second reader of the paid key, extend its allowed-callers set to `api_key_for` (the pin is "inside model_pools", which still holds).

- [ ] **Step 6: Commit**

```bash
git add chauffeur/services/model_pools.py chauffeur/services/llm.py chauffeur/tests/test_model_pool_providers.py chauffeur/tests/test_missions_pins.py
git commit -m "feat(ai): a provider is a column of the tier table - PROVIDER_POOLS, prefixed ids, split_model, api_key_for, credentials, the Gemini-only rules fenced"
```

---

### Task 2: Claude and OpenAI wire branches in `llm.py` (Codex, against Claude's tests)

**Files:**
- Modify: `chauffeur/services/llm.py` (`test_llm_connection` lines 8-65, `_call_llm_json` lines 67-257, `call_model` from Task 1, the voice guard lines 68-74)
- Create: `chauffeur/tests/test_llm_providers.py`
- Neighbours: `tests/test_agent_llm_errors.py`, `tests/test_model_pool_providers.py`

**Interfaces:**
- Consumes: `model_pools.split_model`, `model_pools.is_lite`, `llm_budget.urlopen`.
- Produces:
  - `_call_llm_json(provider in ('anthropic','openai'), url='', api_key, bare_model, system_prompt, user_prompt, temperature, tools=None, timeout_s, images, metrics, max_output_tokens, transient_retries, thinking_level, strict_json, response_schema, use_system_instruction, text=False)`.
  - `call_model(model_id, api_key, system_prompt, user_prompt, text=False, **kw) -> dict`; with `text=True` returns `{'text': str}`.
  - `test_llm_connection('anthropic'|'openai', url=None, api_key, model=None) -> (bool, str)`.
  - `ANTHROPIC_URL = 'https://api.anthropic.com/v1/messages'`, `OPENAI_URL = 'https://api.openai.com/v1/responses'`, `effort_for(bare_model, thinking_level, pool_hint) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# chauffeur/tests/test_llm_providers.py
"""The two paid wire branches: what goes on the wire, what comes back. No network."""
import io
import json
import urllib.error
import urllib.request
from unittest import mock
from harness import check
from services import llm, llm_budget

SENT = []


def _fake_urlopen(responses):
    """responses: list of (status, body-dict) popped per call; a status >= 400 raises HTTPError."""
    seq = list(responses)
    def f(request, timeout=60):
        SENT.append((request.full_url, dict(request.header_items()), json.loads(request.data.decode('utf-8')) if request.data else None, request.get_method()))
        status, body = seq.pop(0)
        raw = json.dumps(body).encode('utf-8')
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, 'err', {}, io.BytesIO(raw))
        return io.BytesIO(raw)
    return f


CLAUDE_OK = (200, {'content': [{'type': 'thinking', 'thinking': ''}, {'type': 'text', 'text': '{"a": 1}'}],
                   'stop_reason': 'end_turn', 'usage': {'input_tokens': 12, 'output_tokens': 5}})
OPENAI_OK = (200, {'status': 'completed', 'output': [{'type': 'reasoning'}, {'type': 'message', 'content': [{'type': 'output_text', 'text': '{"a": 1}'}]}],
                   'usage': {'input_tokens': 12, 'output_tokens': 5}})


def scenario_claude_request_shape():
    SENT.clear()
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([CLAUDE_OK])):
        metrics = {}
        res = llm._call_llm_json('anthropic', '', 'KEY', 'claude-haiku-5-5', 'SYS', 'USER', temperature=0.7,
                                 images=[{'mime': 'image/png', 'b64': 'AAAA'}], metrics=metrics, thinking_level='high',
                                 response_schema={'type': 'object'})
    url, headers, body, method = SENT[0]
    check(url == 'https://api.anthropic.com/v1/messages' and method == 'POST', url)
    check(headers.get('X-api-key') == 'KEY' and headers.get('Anthropic-version') == '2023-06-01', f'headers: {headers}')
    check(body['model'] == 'claude-haiku-5-5' and body['system'] == 'SYS', 'model and top-level system')
    check('temperature' not in body and 'thinking' not in body, 'no temperature, no thinking field')
    check(body['output_config']['effort'] == 'high', 'effort from thinking_level')
    check(body['output_config']['format'] == {'type': 'json_schema', 'schema': {'type': 'object'}}, 'schema -> output_config.format')
    check(body['max_tokens'] == 8192, 'default max_tokens')
    content = body['messages'][0]['content']
    check(content[0] == {'type': 'text', 'text': 'USER'}, 'user text first')
    check(content[1] == {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'AAAA'}}, 'image block')
    check(res == {'a': 1}, f'parsed JSON: {res}')
    check(metrics['promptTokenCount'] == 12 and metrics['candidatesTokenCount'] == 5 and metrics['modelVersion'] == 'claude-haiku-5-5', f'metrics mapped: {metrics}')


def scenario_claude_effort_defaults():
    SENT.clear()
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([CLAUDE_OK, CLAUDE_OK])):
        llm._call_llm_json('anthropic', '', 'K', 'claude-haiku-5-5', 's', 'u')
        llm._call_llm_json('anthropic', '', 'K', 'claude-opus-5-5', 's', 'u')
    check(SENT[0][2]['output_config']['effort'] == 'low', 'lite/flash default low')
    check(SENT[1][2]['output_config']['effort'] == 'medium', 'pro default medium')


def scenario_claude_refusal_and_truncation():
    refused = (200, {'content': [], 'stop_reason': 'refusal', 'stop_details': {'category': 'cyber'}, 'usage': {}})
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([refused])):
        res = llm._call_llm_json('anthropic', '', 'K', 'claude-haiku-5-5', 's', 'u')
    check(res.get('error', '').startswith('refused: cyber'), f'refusal is an error: {res}')
    cut = (200, {'content': [{'type': 'text', 'text': '{"a":'}], 'stop_reason': 'max_tokens', 'usage': {'output_tokens': 9}})
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([cut])):
        try:
            llm._call_llm_json('anthropic', '', 'K', 'claude-haiku-5-5', 's', 'u', strict_json=True)
            check(False, 'strict + max_tokens must raise')
        except RuntimeError as e:
            check('Incomplete' in str(e), str(e))
    empty = (200, {'content': [{'type': 'thinking', 'thinking': ''}], 'stop_reason': 'end_turn', 'usage': {}})
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([empty])):
        try:
            llm._call_llm_json('anthropic', '', 'K', 'claude-haiku-5-5', 's', 'u')
            check(False, 'an empty answer must raise the parse error, not crash elsewhere')
        except RuntimeError as e:
            check('Failed to parse' in str(e) or 'empty' in str(e).lower(), str(e))


def scenario_claude_429_and_5xx():
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([(429, {'error': {'message': 'slow down'}})])):
        res = llm._call_llm_json('anthropic', '', 'K', 'claude-haiku-5-5', 's', 'u')
    check(str(res.get('error', '')).startswith('429'), f'429 is a returned error: {res}')
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([(503, {'error': {'message': 'overloaded'}})])):
        try:
            llm._call_llm_json('anthropic', '', 'K', 'claude-haiku-5-5', 's', 'u', transient_retries=0)
            check(False, '503 raises')
        except RuntimeError as e:
            check('503' in str(e), str(e))


def scenario_openai_request_shape():
    SENT.clear()
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([OPENAI_OK])):
        metrics = {}
        res = llm._call_llm_json('openai', '', 'KEY', 'gpt-6-luna', 'SYS', 'USER', temperature=0.7,
                                 images=[{'mime': 'image/jpeg', 'b64': 'BBBB'}], metrics=metrics,
                                 response_schema={'type': 'object'}, max_output_tokens=2000)
    url, headers, body, method = SENT[0]
    check(url == 'https://api.openai.com/v1/responses' and method == 'POST', url)
    check(headers.get('Authorization') == 'Bearer KEY', f'bearer: {headers}')
    check(body['model'] == 'gpt-6-luna' and body['instructions'] == 'SYS', 'model and instructions')
    check('temperature' not in body, 'no temperature')
    check(body['reasoning'] == {'effort': 'low'} and body['max_output_tokens'] == 2000, 'effort + max_output_tokens')
    check(body['text']['format'] == {'type': 'json_schema', 'name': 'result', 'schema': {'type': 'object'}, 'strict': False}, body['text'])
    item = body['input'][0]
    check(item['role'] == 'user' and item['content'][0] == {'type': 'input_text', 'text': 'USER'}, 'input_text')
    check(item['content'][1] == {'type': 'input_image', 'image_url': 'data:image/jpeg;base64,BBBB', 'detail': 'auto'}, 'input_image')
    check(res == {'a': 1} and metrics['promptTokenCount'] == 12 and metrics['modelVersion'] == 'gpt-6-luna', f'{res} {metrics}')


def scenario_openai_json_object_and_incomplete():
    SENT.clear()
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([OPENAI_OK])):
        llm._call_llm_json('openai', '', 'K', 'gpt-6-luna', 's', 'u', strict_json=True)
    check(SENT[0][2]['text']['format'] == {'type': 'json_object'}, 'strict without a schema = json_object')
    partial = (200, {'status': 'incomplete', 'incomplete_details': {'reason': 'max_output_tokens'},
                     'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"a": 1} and more'}]}], 'usage': {}})
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([partial])):
        try:
            llm._call_llm_json('openai', '', 'K', 'gpt-6-luna', 's', 'u', strict_json=True)
            check(False, 'incomplete + strict raises')
        except RuntimeError as e:
            check('Incomplete' in str(e), str(e))
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([partial])):
        res = llm._call_llm_json('openai', '', 'K', 'gpt-6-luna', 's', 'u')
    check(res == {'a': 1}, f'incomplete without strict still yields the JSON it holds: {res}')


def scenario_call_model_dispatch_and_text():
    SENT.clear()
    title = (200, {'content': [{'type': 'text', 'text': 'Dishwasher repair appointment'}], 'stop_reason': 'end_turn', 'usage': {}})
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([title])):
        res = llm.call_model('anthropic:claude-haiku-5-5', 'K', 's', 'u', text=True)
    check(res == {'text': 'Dishwasher repair appointment'}, f'text=True returns prose untouched: {res}')
    check(SENT[0][2]['model'] == 'claude-haiku-5-5', 'the bare id goes on the wire')
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([OPENAI_OK])):
        res = llm.call_model('openai:gpt-6-luna', 'K', 's', 'u')
    check(res == {'a': 1}, 'openai dispatch')


def scenario_connection_tests_cost_no_tokens():
    SENT.clear()
    listing = (200, {'data': [{'id': 'claude-haiku-5-5'}, {'id': 'claude-sonnet-5-5'}]})
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([listing])):
        ok, msg = llm.test_llm_connection('anthropic', api_key='K', model='claude-opus-5-5')
    check(SENT[0][0] == 'https://api.anthropic.com/v1/models' and SENT[0][3] == 'GET', SENT[0][:1])
    check(ok and 'claude-opus-5-5' in msg and 'not' in msg, f'a table id the key cannot see is said loudly: {msg}')
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([(200, {'data': [{'id': 'gpt-6-luna'}]})])):
        ok, msg = llm.test_llm_connection('openai', api_key='K', model='gpt-6-luna')
    check(ok and '1 model' in msg, msg)
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([(401, {'error': {'message': 'bad key'}})])):
        ok, msg = llm.test_llm_connection('openai', api_key='K')
    check(not ok and 'bad key' in msg, msg)
    ok, msg = llm.test_llm_connection('anthropic', api_key='')
    check(not ok and 'key' in msg.lower(), msg)


def scenario_voice_guard_reads_the_lite_pool():
    from services import app_voice
    class Turn:
        def remaining(self): return 30
    tok = app_voice.current.set(Turn())
    try:
        with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([CLAUDE_OK])):
            from services import storage
            real = storage.get_settings
            storage.get_settings = lambda: {'llm_provider': 'anthropic', 'llm_anthropic_api_key': 'A'}
            try:
                res = llm.call_model('anthropic:claude-haiku-5-5', 'A', 's', 'u')
                check(res == {'a': 1}, f'haiku is allowed on a voice turn: {res}')
                res = llm.call_model('anthropic:claude-sonnet-5-5', 'A', 's', 'u')
                check('error' in res and 'voice' in res['error'], f'sonnet is not: {res}')
            finally:
                storage.get_settings = real
    finally:
        app_voice.current.reset(tok)


if __name__ == '__main__':
    scenario_claude_request_shape()
    scenario_claude_effort_defaults()
    scenario_claude_refusal_and_truncation()
    scenario_claude_429_and_5xx()
    scenario_openai_request_shape()
    scenario_openai_json_object_and_incomplete()
    scenario_call_model_dispatch_and_text()
    scenario_connection_tests_cost_no_tokens()
    scenario_voice_guard_reads_the_lite_pool()
    print('test_llm_providers OK')
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd chauffeur && python tests/test_llm_providers.py`
Expected: `ValueError: Unknown provider: anthropic` (or the voice-guard error first).

- [ ] **Step 3: Implement the branches**

Constants and the effort map near the top of `llm.py`:

```python
ANTHROPIC_URL = 'https://api.anthropic.com/v1/messages'
ANTHROPIC_MODELS_URL = 'https://api.anthropic.com/v1/models'
OPENAI_URL = 'https://api.openai.com/v1/responses'
OPENAI_MODELS_URL = 'https://api.openai.com/v1/models'
DEFAULT_MAX_OUTPUT = 8192
_EFFORT = {'low': 'low', 'medium': 'medium', 'high': 'high'}


def effort_for(bare_model: str, thinking_level, is_pro: bool) -> str:
    if thinking_level in _EFFORT:
        return _EFFORT[thinking_level]
    return 'medium' if is_pro else 'low'


def _is_pro(bare_model: str) -> bool:
    from services import model_pools
    return any(bare_model in pools['pro'] for pools in model_pools.PROVIDER_POOLS.values())
```

Voice guard at the top of `_call_llm_json` (replaces the `provider != 'gemini' or 'flash-lite' not in model` test):

```python
    if phone_turn is not None:
        from services import model_pools
        from services.storage import get_settings
        full = model if provider == 'gemini' else f'{provider}:{model}'
        if provider == 'ollama' or not model_pools.is_lite(full, get_settings()):
            return {'error': 'That work needs the text/background path; voice uses the interactive lite tier.'}
```

The Claude branch, after the Gemini `elif`:

```python
    elif provider == 'anthropic':
        content = [{"type": "text", "text": user_prompt}]
        for img in (images or []):
            content.append({"type": "image", "source": {"type": "base64", "media_type": img.get('mime') or 'image/jpeg', "data": img['b64']}})
        payload = {
            "model": model, "max_tokens": max_output_tokens or DEFAULT_MAX_OUTPUT,
            "system": system_prompt,
            "messages": [{"role": "user", "content": content}],
            "output_config": {"effort": effort_for(model, thinking_level, _is_pro(model))},
        }
        if response_schema is not None:
            payload["output_config"]["format"] = {"type": "json_schema", "schema": response_schema}
        req = urllib.request.Request(ANTHROPIC_URL, data=json.dumps(payload).encode('utf-8'), method="POST",
                                     headers={"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"})
        data = _send_with_retries(req, timeout_s, transient_retries, model, 'Claude', metrics)
        if isinstance(data, dict) and data.get('error'):
            return data                               # a 429 dict, as the Gemini branch returns
        if metrics is not None:
            usage = data.get('usage') or {}
            metrics.update({'promptTokenCount': usage.get('input_tokens', 0), 'candidatesTokenCount': usage.get('output_tokens', 0),
                            'modelVersion': model, 'finish_reason': data.get('stop_reason')})
        if data.get('stop_reason') == 'refusal':
            cat = (data.get('stop_details') or {}).get('category') or 'unspecified'
            return {'error': f'refused: {cat}'}
        if strict_json and data.get('stop_reason') != 'end_turn':
            usage = data.get('usage') or {}
            raise RuntimeError(f"Incomplete Claude JSON response (finish={data.get('stop_reason')}; output_tokens={usage.get('output_tokens', 0)}; limit={max_output_tokens})")
        raw_response = ''.join(b.get('text', '') for b in (data.get('content') or []) if b.get('type') == 'text')
```

`_send_with_retries` is a small helper factored out of the Gemini retry loop (same 5xx backoff, same 429 → `{"error": "429 ..."}` return, same `llm_budget.Deferred` pass-through, `RuntimeError(f"{label} API request failed: ...")` otherwise). The Gemini branch keeps its own loop as is; the helper is new code used by the two new branches only, so nothing Gemini-shaped changes.

The OpenAI branch:

```python
    elif provider == 'openai':
        content = [{"type": "input_text", "text": user_prompt}]
        for img in (images or []):
            content.append({"type": "input_image", "image_url": f"data:{img.get('mime') or 'image/jpeg'};base64,{img['b64']}", "detail": "auto"})
        payload = {
            "model": model, "instructions": system_prompt,
            "input": [{"role": "user", "content": content}],
            "max_output_tokens": max_output_tokens or DEFAULT_MAX_OUTPUT,
            "reasoning": {"effort": effort_for(model, thinking_level, _is_pro(model))},
        }
        if response_schema is not None:
            payload["text"] = {"format": {"type": "json_schema", "name": "result", "schema": response_schema, "strict": False}}
        elif strict_json:
            payload["text"] = {"format": {"type": "json_object"}}
        req = urllib.request.Request(OPENAI_URL, data=json.dumps(payload).encode('utf-8'), method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"})
        data = _send_with_retries(req, timeout_s, transient_retries, model, 'OpenAI', metrics)
        if isinstance(data, dict) and data.get('error'):
            return data
        if metrics is not None:
            usage = data.get('usage') or {}
            metrics.update({'promptTokenCount': usage.get('input_tokens', 0), 'candidatesTokenCount': usage.get('output_tokens', 0),
                            'modelVersion': model, 'finish_reason': data.get('status')})
        if strict_json and data.get('status') != 'completed':
            raise RuntimeError(f"Incomplete OpenAI JSON response (status={data.get('status')}; reason={(data.get('incomplete_details') or {}).get('reason')}; limit={max_output_tokens})")
        raw_response = ''.join(c.get('text', '') for item in (data.get('output') or []) if item.get('type') == 'message'
                               for c in (item.get('content') or []) if c.get('type') == 'output_text')
```

Both branches honour `text=True` (a new keyword on `_call_llm_json`, default False): right after `raw_response` is set, `if text: return {'text': raw_response.strip()}`. The Gemini and Ollama branches get the same two lines so `call_model(..., text=True)` works on every provider. `call_model` (Task 1 stub) passes `text` through.

`test_llm_connection` gains:

```python
    elif provider in ('anthropic', 'openai'):
        label = 'Claude' if provider == 'anthropic' else 'OpenAI'
        if not api_key:
            return False, f"{label} API key is required."
        url = ANTHROPIC_MODELS_URL if provider == 'anthropic' else OPENAI_MODELS_URL
        headers = ({"x-api-key": api_key, "anthropic-version": "2023-06-01"} if provider == 'anthropic'
                   else {"Authorization": f"Bearer {api_key}"})
        try:
            with llm_budget.urlopen(urllib.request.Request(url, headers=headers, method="GET"), timeout=8) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            ids = [m.get('id') for m in data.get('data', [])]
            from services import model_pools
            table = sorted({m for pool in model_pools.PROVIDER_POOLS[provider].values() for m in pool})
            missing = [m for m in table if m not in ids] + ([model] if model and model not in ids and model not in table else [])
            n = f"{len(ids)} model" + ('' if len(ids) == 1 else 's')
            if missing:
                return True, f"Connected to {label} ({n} listed), but this key does not list: {', '.join(missing)}. Pick another model in the pool settings."
            return True, f"Successfully connected to {label}! {n} listed."
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode('utf-8')).get('error', {}).get('message', str(e))
            except Exception:
                msg = f"{e.code} {e.reason}"
            return False, f"{label} API Error: {msg}"
        except Exception as e:
            return False, f"Unexpected error connecting to {label}: {str(e)}"
```

- [ ] **Step 4: Run the tests and the neighbours**

Run: `cd chauffeur && python tests/test_llm_providers.py && python tests/test_agent_llm_errors.py && python tests/test_model_pool_providers.py`
Expected: three OK lines.

- [ ] **Step 5: Confirm the OpenAI ids with the real key (the one network step)**

Run from a shell with the user's OpenAI key exported: `python -c "from services import llm; print(llm.test_llm_connection('openai', api_key=__import__('os').environ['OPENAI_KEY']))"`.
Expected: `(True, 'Successfully connected to OpenAI! N models listed.')`. If the message names a missing id, STOP and report; the table in `PROVIDER_POOLS['openai']` is corrected (`gpt-5.5` is the documented alternative for research) before this task is committed. Do the same for Claude with `ANTHROPIC_KEY` if the user has one at hand; otherwise note it as a device step.

- [ ] **Step 6: Commit**

```bash
git add chauffeur/services/llm.py chauffeur/tests/test_llm_providers.py
git commit -m "feat(ai): Claude and OpenAI wire branches - raw Messages and Responses calls, effort from thinking_level, schemas as output formats, refusal and truncation reported, tokenless connection tests"
```

---

### Task 3: Metering the two hosts and the per-provider daily cap (Codex)

**Files:**
- Modify: `chauffeur/services/llm_budget.py` (`_limit` lines 150-157, `_reserve` lines 190-229, `urlopen` lines 252-282)
- Modify: `chauffeur/tests/test_llm_budget.py` (append scenarios + main)
- Neighbours: `tests/test_model_pool_overload.py`

**Interfaces:**
- Consumes: `model_pools.split_model`; settings via `storage.get_settings` (lazy import inside `_reserve`, patched by tests).
- Produces: `urlopen` meters `api.anthropic.com/v1/messages` and `api.openai.com/v1/responses` with the prefixed model id; `provider_cap(prov, settings) -> int`; `_local_midnight(now) -> float`; `provider_attempts_today(key, prov) -> int`.

- [ ] **Step 1: Write the failing scenarios (append to `tests/test_llm_budget.py`)**

```python
def _req(url, model, key):
    body = json.dumps({'model': model}).encode('utf-8')
    hdr = {'x-api-key': key} if 'anthropic' in url else {'Authorization': 'Bearer ' + key}
    return urllib.request.Request(url, data=body, headers=hdr, method='POST')


def scenario_paid_hosts_are_metered_by_body_model():
    from services import storage
    real = storage.get_settings
    storage.get_settings = lambda: {'llm_anthropic_daily_cap': 500}
    try:
        with patch('urllib.request.urlopen', ok):
            with budget.request_scope('t', False):
                budget.urlopen(_req('https://api.anthropic.com/v1/messages', 'claude-haiku-5-5', 'A'))
                budget.urlopen(_req('https://api.openai.com/v1/responses', 'gpt-6-luna', 'O'))
        with contextlib_closing(budget._connect()) as db:
            rows = db.execute('SELECT model FROM attempts ORDER BY id DESC LIMIT 2').fetchall()
        check({r[0] for r in rows} == {'anthropic:claude-haiku-5-5', 'openai:gpt-6-luna'}, f'prefixed ids recorded: {rows}')
        check(budget._limit('anthropic:claude-haiku-5-5') is None and budget._limit('openai:gpt-6.1-sol') is None,
              'no guessed allowance for a paid provider')
        with patch('urllib.request.urlopen', ok):
            budget.urlopen(urllib.request.Request('https://api.anthropic.com/v1/models', headers={'x-api-key': 'A'}, method='GET'))
        with contextlib_closing(budget._connect()) as db:
            n = db.execute("SELECT COUNT(*) FROM attempts WHERE model LIKE 'anthropic:%'").fetchone()[0]
        check(n == 1, 'a models listing is not a model call and is not metered')
    finally:
        storage.get_settings = real


def scenario_provider_cap_counts_the_local_day():
    from services import storage
    real = storage.get_settings
    storage.get_settings = lambda: {'llm_openai_daily_cap': 2}
    try:
        with contextlib_closing(budget._connect()) as db, db:
            db.execute("DELETE FROM attempts WHERE model LIKE 'openai:%'")
        with patch('urllib.request.urlopen', ok):
            with budget.request_scope('t', False):
                budget.urlopen(_req('https://api.openai.com/v1/responses', 'gpt-6-luna', 'O'))
                budget.urlopen(_req('https://api.openai.com/v1/responses', 'gpt-6-luna', 'O'))
                try:
                    budget.urlopen(_req('https://api.openai.com/v1/responses', 'gpt-6-luna', 'O'))
                    check(False, 'the third request must defer')
                except budget.Deferred as e:
                    check(e.scope == 'allowance' and 'OpenAI' in str(e), f'{e} {e.scope}')
                    local_mid = budget._local_midnight(time.time())
                    check(abs(e.retry_at - local_mid) < 2, 'retry at local midnight, not Pacific')
        # yesterday's attempts do not count: move them back a day
        with contextlib_closing(budget._connect()) as db, db:
            db.execute("UPDATE attempts SET started = started - 86400 WHERE model LIKE 'openai:%'")
        with patch('urllib.request.urlopen', ok):
            with budget.request_scope('t', False):
                budget.urlopen(_req('https://api.openai.com/v1/responses', 'gpt-6-luna', 'O'))
        storage.get_settings = lambda: {'llm_openai_daily_cap': 0}
        with patch('urllib.request.urlopen', ok):
            with budget.request_scope('t', False):
                for _ in range(5):
                    budget.urlopen(_req('https://api.openai.com/v1/responses', 'gpt-6-luna', 'O'))
        check(budget.provider_attempts_today('O', 'openai') >= 6, 'cap 0 never defers')
    finally:
        storage.get_settings = real


def scenario_paid_429_pauses_two_minutes_only():
    def throttled(*a, **k):
        raise urllib.error.HTTPError('u', 429, 'rate', {}, io.BytesIO(b'{"error":{"message":"per day limit"}}'))
    with patch('urllib.request.urlopen', throttled):
        with budget.request_scope('t', False):
            try:
                budget.urlopen(_req('https://api.anthropic.com/v1/messages', 'claude-sonnet-5-5', 'A'))
            except urllib.error.HTTPError:
                pass
    with contextlib_closing(budget._connect()) as db:
        until = db.execute("SELECT until FROM pauses WHERE scope='model:anthropic:claude-sonnet-5-5'").fetchone()[0]
    check(0 < until - time.time() <= 121, 'a paid 429 with "per day" text is still a two-minute pause')
```

Add `import time` at the top if absent and the three calls to `__main__`.

- [ ] **Step 2: Run to verify it fails**

Run: `cd chauffeur && python tests/test_llm_budget.py`
Expected: the attempts rows are missing (`check` fails on `prefixed ids recorded`).

- [ ] **Step 3: Implement**

```python
PAID_HOSTS = {'api.anthropic.com': ('anthropic', '/v1/messages'), 'api.openai.com': ('openai', '/v1/responses')}
PROVIDER_LABEL = {'anthropic': 'Claude', 'openai': 'OpenAI'}


def _local_midnight(now):
    local = datetime.datetime.fromtimestamp(now).astimezone()
    nxt = datetime.datetime.combine(local.date() + datetime.timedelta(days=1), datetime.time(), tzinfo=local.tzinfo)
    return nxt.timestamp()


def provider_cap(prov, settings):
    try:
        return max(0, int((settings or {}).get(f'llm_{prov}_daily_cap', 500) or 0))
    except (TypeError, ValueError):
        return 500


def provider_attempts_today(key, prov):
    since = _local_midnight(time.time()) - 86400
    with contextlib.closing(_connect()) as db:
        return db.execute('SELECT COUNT(*) FROM attempts WHERE account=? AND model LIKE ? AND started >= ?',
                          (_account(key), prov + ':%', since)).fetchone()[0]
```

`_limit`: first line `if ':' in model: return None`.

In `_reserve`, after the pause checks and before the flash check, with `prov = model.split(':', 1)[0] if ':' in model else 'gemini'`:

```python
        if prov in PROVIDER_LABEL:
            from services.storage import get_settings
            cap = provider_cap(prov, get_settings())
            if cap:
                since = _local_midnight(now) - 86400
                used = db.execute('SELECT COUNT(*) FROM attempts WHERE account=? AND model LIKE ? AND started >= ?',
                                  (account, prov + ':%', since)).fetchone()[0]
                if used >= cap:
                    raise Deferred(f"{PROVIDER_LABEL[prov]}'s daily request cap ({cap}) is used up", _local_midnight(now), 'allowance')
```

In `urlopen`, replace the host test:

```python
    url = urllib.parse.urlsplit(request.full_url)
    paid = PAID_HOSTS.get(url.hostname)
    if paid and url.path == paid[1]:
        try:
            model = paid[0] + ':' + json.loads(request.data.decode('utf-8')).get('model', '')
        except Exception:
            model = paid[0] + ':unknown'
        key = request.get_header('X-api-key', '') or request.get_header('Authorization', '').replace('Bearer ', '')
    elif url.hostname == 'generativelanguage.googleapis.com' and '/models/' in url.path:
        model = url.path.split('/models/', 1)[1].split(':', 1)[0]
        key = urllib.parse.parse_qs(url.query).get('key', [''])[0] or request.get_header('X-goog-api-key', '')
    else:
        return urllib.request.urlopen(request, timeout=timeout)
```

(`import json` at the top.) In the 429 branch of the error handler: `until = _day(now)[1] if ':' not in model and any(...) else now + 120`.

- [ ] **Step 4: Run tests and neighbours**

Run: `cd chauffeur && python tests/test_llm_budget.py && python tests/test_model_pool_overload.py`
Expected: both OK.

- [ ] **Step 5: Commit**

```bash
git add chauffeur/services/llm_budget.py chauffeur/tests/test_llm_budget.py
git commit -m "feat(ai): llm_budget meters api.anthropic.com and api.openai.com by the body's model, a per-provider daily request cap over the local day, no guessed allowance for paid providers"
```

---

### Task 4: Settings, the Config › AI page and the connection test route (Claude)

**Files:**
- Modify: `chauffeur/models/schemas.py:1214-1222` and `:1591-1593`
- Modify: `chauffeur/services/settings_registry.py:468-499`
- Modify: `chauffeur/templates/config.html:488-535` (provider block), `:2511-2526` (load), `:2653-2666` (save), `:4205-4225` (`testLLMConnection`)
- Modify: `chauffeur/main.py:18388-18403` (`LLMTestPayload` / `test_llm`: no change needed beyond passing through; verify)
- Create: `chauffeur/tests/test_provider_settings.py`
- Run: `python tools/build_tailwind.py`
- Neighbours: `tests/test_settings_registry.py`

**Interfaces:**
- Produces settings keys: `llm_anthropic_api_key`, `llm_openai_api_key` (`Optional[str] = None`), `llm_anthropic_daily_cap`, `llm_openai_daily_cap` (`int = 500`), `model_pool_lite`, `model_pool_flash`, `model_pool_gemma` (`Optional[str] = ''`); `llm_provider` help text updated.

- [ ] **Step 1: Write the failing test**

```python
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
```

(The member-token header is the admin gate every TestClient test in the suite uses; `tests/test_paid_fallback_ui.py` is the model.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd chauffeur && python tests/test_provider_settings.py`
Expected: `llm_anthropic_api_key did not persist: None`.

- [ ] **Step 3: Schema and registry**

`models/schemas.py`, after `llm_gemini_api_key`:

```python
    # One key per paid provider; which one is used follows the model id's
    # prefix (services/model_pools.py: api_key_for).
    llm_anthropic_api_key: Optional[str] = None
    llm_openai_api_key: Optional[str] = None
    # Billed requests per local day per provider; 0 = no cap.
    llm_anthropic_daily_cap: int = 500
    llm_openai_daily_cap: int = 500
```

and beside `model_pool_pro`:

```python
    # Comma-separated pool overrides; an entry may carry a provider prefix
    # (anthropic:claude-haiku-5-5). Blank = the selected provider's default.
    model_pool_lite: Optional[str] = ''
    model_pool_flash: Optional[str] = ''
    model_pool_gemma: Optional[str] = ''
```

`settings_registry.py`, replace the `llm_provider` entry and add after `llm_ollama_model`:

```python
    _e('llm_provider', 'ai', 'Model provider', 'Gemini, Claude, OpenAI, or a local Ollama. Everything Argyle does runs on the one chosen.'),
    _e('llm_anthropic_api_key', 'ai', 'Claude API key', 'Every call runs on this key when Claude is the provider.'),
    _e('llm_openai_api_key', 'ai', 'OpenAI API key', 'Every call runs on this key when OpenAI is the provider.'),
    _e('llm_anthropic_daily_cap', 'ai', 'Claude requests per day', 'Billed requests per day before the app stops calling until midnight. Default 500; 0 for no cap.'),
    _e('llm_openai_daily_cap', 'ai', 'OpenAI requests per day', 'Billed requests per day before the app stops calling until midnight. Default 500; 0 for no cap.'),
    _e('model_pool_lite', 'ai', 'Lite model pool', 'Comma-separated ids for chat and background work; an entry may be anthropic:<id> or openai:<id>. Blank means the provider default.'),
    _e('model_pool_flash', 'ai', 'Flash model pool', 'Comma-separated ids for heavy, Mind and vision work; prefixes as above.'),
    _e('model_pool_gemma', 'ai', 'Gemma model pool', 'Comma-separated Gemma ids for free background volume (Gemini only).'),
```

- [ ] **Step 4: The page**

In `config.html` provider block (lines 488-535): the `<select>` gains `<option value="anthropic">Claude (Anthropic)</option>` and `<option value="openai">OpenAI</option>`; the Gemini key `<div>` gets `x-show="llmProvider === 'gemini'"`; two new key fields and two cap fields:

```html
<div x-show="llmProvider === 'anthropic'">
    <label for="llmAnthropicApiKey" class="block text-gray-400 mb-2 font-semibold text-sm uppercase tracking-wider">Claude API key</label>
    <input type="password" id="llmAnthropicApiKey" x-model="llmAnthropicApiKey" @change="saveSettings()" placeholder="sk-ant-..."
        class="w-full bg-gray-900 border border-gray-600 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none rounded-lg p-3 text-white font-mono">
</div>
<div x-show="llmProvider === 'anthropic'">
    <label for="llmAnthropicDailyCap" class="block text-gray-400 mb-2 font-semibold text-sm uppercase tracking-wider">Claude requests per day</label>
    <input type="number" min="0" id="llmAnthropicDailyCap" x-model.number="llmAnthropicDailyCap" @change="saveSettings()"
        class="w-full bg-gray-900 border border-gray-600 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none rounded-lg p-3 text-white">
    <p class="text-gray-600 text-xs mt-1">Every call is billed. The app stops at this many a day until midnight; 0 for no cap.</p>
</div>
```

(the same pair for `openai`: `llmOpenaiApiKey`, `llmOpenaiDailyCap`, placeholder `sk-...`), and an "Advanced: model pools" row of three text inputs `modelPoolLite` / `modelPoolFlash` / `modelPoolGemma` with the registry help as the hint. The paid-fallback block (lines ~540-570) gets `x-show="llmProvider === 'gemini'"`.

Alpine state: declare `llmAnthropicApiKey: ''`, `llmOpenaiApiKey: ''`, `llmAnthropicDailyCap: 500`, `llmOpenaiDailyCap: 500`, `modelPoolLite: ''`, `modelPoolFlash: ''`, `modelPoolGemma: ''` next to `llmProvider: ''` (line 2213); load them in the block at 2511 (`this.llmAnthropicApiKey = data.llm_anthropic_api_key || ''; ... this.llmAnthropicDailyCap = data.llm_anthropic_daily_cap ?? 500; ... this.modelPoolLite = data.model_pool_lite || '';`); save them in the block at 2653 (`llm_anthropic_api_key: this.llmAnthropicApiKey, llm_anthropic_daily_cap: Math.max(0, parseInt(this.llmAnthropicDailyCap, 10) || 0), ... model_pool_lite: this.modelPoolLite, ...`).

`testLLMConnection` body:

```js
const keyFor = { gemini: this.llmGeminiApiKey, anthropic: this.llmAnthropicApiKey, openai: this.llmOpenaiApiKey }[this.llmProvider] || '';
const modelFor = { gemini: this.llmGeminiModel, ollama: this.llmOllamaModel }[this.llmProvider] || null;
body: JSON.stringify({ provider: this.llmProvider, url: this.llmOllamaUrl, api_key: keyFor, model: modelFor })
```

Then: `python tools/build_tailwind.py`.

- [ ] **Step 5: Run tests and neighbours**

Run: `cd chauffeur && python tests/test_provider_settings.py && python tests/test_settings_registry.py`
Expected: both OK.

- [ ] **Step 6: Commit**

```bash
git add chauffeur/models/schemas.py chauffeur/services/settings_registry.py chauffeur/templates/config.html chauffeur/static/css chauffeur/tests/test_provider_settings.py
git commit -m "feat(ai): the provider selector - Gemini, Claude, OpenAI or Ollama on Config > AI, a key and a daily cap per paid provider, the lite/flash/gemma pool overrides registered and editable"
```

---

### Task 5: The dead `llm_provider` readers and the keyless preflights come alive (Claude)

**Files:**
- Modify: `chauffeur/services/agent_router.py:39-41,92` (use `call_model`)
- Modify: `chauffeur/services/llm.py:380-424` (`auto_name_conversation`)
- Modify: `chauffeur/main.py:17410-17415` (rule deduction), `:7901`
- Modify: `chauffeur/services/trip_planner.py` six `provider` blocks (lines 100-108, 1091-1099, 1245-1253, 1370-1378, 1745-1753 and the top-up at 1557): keep as is except the non-Ollama branch takes `model, api_key = model_pools.credentials('heavy', settings)`; `pooled_or_direct` already routes.
- Modify the preflights: `services/planner_intake.py:123`, `services/email_ingest.py:193,541,890,1046`, `services/house_facade.py:1458,1628`, `services/mind.py:376,485,533,795,895,1056`, `services/meals.py:2758,3003,3100`, `services/threads.py:119,572`
- Create: `chauffeur/tests/test_provider_preflights.py`
- Neighbours: `tests/test_agent_llm_errors.py`, `tests/test_trip_planner.py`, `tests/test_meals.py`, `tests/test_program_lessons.py`, `tests/test_web_research.py` (it stubs `llm_gemini_api_key`; it keeps working because a bare Gemini selection still reads that key)

**Interfaces:**
- Consumes: `model_pools.credentials`, `model_pools.has_credentials`, `llm.call_model`.
- Produces: nothing new; every site's error text that said "Gemini API key" now says "an AI provider key (Config › AI)".

- [ ] **Step 1: Write the failing test**

```python
# chauffeur/tests/test_provider_preflights.py
"""A Claude-only household reaches the pool on every entry point that used to demand a Gemini key."""
import os, sys, tempfile
os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_preflight_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from harness import check  # noqa: E402
from services import storage, model_pools, llm  # noqa: E402

CLAUDE_ONLY = {'llm_provider': 'anthropic', 'llm_anthropic_api_key': 'A', 'mind_enabled': True, 'web_research_enabled': False}
SEEN = []


def _fake_pool(tier, api_key, system, prompt, **kw):
    SEEN.append((tier, api_key))
    return {'rows': [], 'items': [], 'insights': [], 'answer': '', 'summary': ''}


def setup():
    storage.get_settings = lambda: dict(CLAUDE_ONLY)
    model_pools.call_pool_json = _fake_pool
    SEEN.clear()


def scenario_intake_photo_reads_with_a_claude_key():
    setup()
    from services import planner_intake
    out = planner_intake.extract('m1', 'AAAA', 'image/png')
    check(not out.get('error'), f'photo intake must not demand a Gemini key: {out}')
    check(SEEN and SEEN[0][1] == 'A', f'the pool got the Claude key: {SEEN}')


def scenario_email_extract_and_mind_handle_reach_the_pool():
    setup()
    from services import email_ingest
    try:
        email_ingest.extract_items('subj', 'a@b', 'body', ['Jeff'])
    except RuntimeError as e:
        check(False, f'extract_items raised on a Claude-only household: {e}')
    check(SEEN[-1][1] == 'A', 'email extraction used the Claude key')
    from services import mind
    res = mind.deep_think(force=True)
    check(res.get('status') != 'no_key', f'the Mind sees a configured household: {res}')
    st = email_ingest.wait_status(CLAUDE_ONLY)
    check('used' in st, f'intake status computes on the Claude account: {st}')


def scenario_auto_name_stores_a_plain_title():
    setup()
    titles = []
    storage.update_conversation_title = lambda cid, t: titles.append((cid, t))
    real = llm.call_model
    llm.call_model = lambda model, key, s, u, text=False, **kw: {'text': 'Dishwasher repair appointment'}
    try:
        llm.auto_name_conversation('c1', 'my dishwasher is broken, who can fix it?')
    finally:
        llm.call_model = real
    check(titles == [('c1', 'Dishwasher repair appointment')], f'title stored: {titles}')


def scenario_switching_back_to_gemini_without_a_key_is_honest():
    storage.get_settings = lambda: {'llm_provider': 'gemini', 'llm_anthropic_api_key': 'A'}
    from services import email_ingest
    st = email_ingest.wait_status({'llm_provider': 'gemini', 'llm_anthropic_api_key': 'A'})
    check(st.get('used', 0) == 0, 'no key = nothing counted, no crash')
    check(not model_pools.has_credentials({'llm_provider': 'gemini', 'llm_anthropic_api_key': 'A'}), 'has_credentials says no')


if __name__ == '__main__':
    scenario_intake_photo_reads_with_a_claude_key()
    scenario_email_extract_and_mind_handle_reach_the_pool()
    scenario_auto_name_stores_a_plain_title()
    scenario_switching_back_to_gemini_without_a_key_is_honest()
    print('test_provider_preflights OK')
```

`planner_intake.extract` is the photo reader (line 117), `email_ingest.wait_status` the Intake status (line 185), `mind.deep_think` the Mind entry whose first check is the key (line 890).

- [ ] **Step 2: Run to verify it fails**

Run: `cd chauffeur && python tests/test_provider_preflights.py`
Expected: `photo intake must not demand a Gemini key: {... 'Reading photos needs the Gemini API key (Config).'}`.

- [ ] **Step 3: Implement the reroutes**

Pattern for every preflight (each site, same two lines):

```python
    model_id, api_key = model_pools.credentials('<tier the site's call_pool_json uses>', settings)
    if not api_key:
        <the site's existing no-key return, text changed to 'no AI provider key configured (Config › AI)'>
```

Sites that pass the key straight into `call_pool_json(tier, api_key, ...)` keep doing so with the resolved key. `email_ingest.py:193` and `mind.py:1056` (readiness and usage): `key = model_pools.credentials(WORKFLOW_TIER, settings)[1]` where `WORKFLOW_TIER` is the tier that workflow's calls use (`'background'` for intake, `'mind'` for the Mind). `mind.py:376,533` (`if not settings.get('llm_gemini_api_key')`): `if not model_pools.has_credentials(settings)`. `main.py:7901`: `model_pools.credentials('interactive', settings)[1]`.

`agent_router.call_gemma_with_fallback`: drop `provider = 'gemini'; url = ''`; `api_key = model_pools.credentials('interactive', settings)[1]`; the call becomes `_call_model(model, api_key, system_prompt, prompt, tools=None, timeout_s=timeout_s, **options)` with `from services.llm import call_model as _call_model`; `options['use_system_instruction']` is passed only when `split_model(model)[0] == 'gemini'` (the other branches ignore it anyway).

`auto_name_conversation`: the Ollama branch stays; the `elif provider == 'gemini'` branch becomes `else:` with

```python
            from services import model_pools
            model_id, api_key = model_pools.credentials('interactive', settings)
            if api_key:
                res = call_model(model_id, api_key, 'You name conversations.', prompt, text=True, timeout_s=30)
                title = res.get('text', '') if isinstance(res, dict) else ''
```

`main.py:17410-17415`: `llm_model = model_pools.resolve_model('heavy', settings) if llm_provider != 'ollama' else ...`; `llm_api_key = model_pools.credentials('heavy', settings)[1] if llm_provider != 'ollama' else ''`. `identify_override_patterns` / `deduce_rules_from_context` call `_call_llm_json(provider, ...)` directly: change their one line each to `model_pools.pooled_or_direct(provider, url, api_key, model, 'heavy', system_prompt, <user text>)`.

Trip planner six blocks: the `else:` arm becomes `url = ''; model, api_key = model_pools.credentials('heavy', settings)`; `pooled_or_direct` (Task 1) ignores `model` for non-Ollama.

- [ ] **Step 4: Run tests and neighbours**

Run: `cd chauffeur && python tests/test_provider_preflights.py && python tests/test_agent_llm_errors.py && python tests/test_trip_planner.py && python tests/test_meals.py && python tests/test_program_lessons.py && python tests/test_web_research.py`
Expected: all OK. `test_agent_llm_errors` patches `_call_llm_json` by name in `agent_router`; after this task it must patch `services.llm.call_model` or `agent_router._call_model` instead: update the patch target in that test, nothing else.

- [ ] **Step 5: Commit**

```bash
git add chauffeur/services chauffeur/main.py chauffeur/tests/test_provider_preflights.py chauffeur/tests/test_agent_llm_errors.py
git commit -m "feat(ai): the selector is honoured everywhere - credentials() replaces the fifteen Gemini-only preflights, Argyle and the trip planner dispatch by model id, conversation naming asks for text"
```

---

### Task 6: Web research on the chosen provider (Codex)

**Files:**
- Modify: `chauffeur/services/web.py:292-333` (beside `_gemini_grounded`), `:429-495` (`research` dispatch)
- Modify: `chauffeur/tests/test_web_research.py` (append scenarios)
- Modify: `chauffeur/services/settings_registry.py` (`web_research_via` help text)

**Interfaces:**
- Consumes: `model_pools.resolve_model`, `split_model`, `credentials`, `llm_budget.urlopen`, `llm.ANTHROPIC_URL`, `llm.OPENAI_URL`.
- Produces: `_anthropic_grounded(question, api_key, model=None) -> dict`, `_openai_grounded(question, api_key, model=None) -> dict`, same contract as `_gemini_grounded`; `_grounded_for(provider) -> callable`.

- [ ] **Step 1: Write the failing scenarios (append)**

```python
CLAUDE_GROUNDED = {'content': [
    {'type': 'server_tool_use', 'name': 'web_search'},
    {'type': 'web_search_tool_result', 'content': [{'type': 'web_search_result', 'url': 'https://justinguitar.com/g1', 'title': 'Justin Guitar'}]},
    {'type': 'text', 'text': 'Justin Guitar has a free beginner course.', 'citations': [{'url': 'https://justinguitar.com/g1', 'title': 'Justin Guitar', 'cited_text': 'free'}]},
    {'type': 'text', 'text': ' Start there.'}], 'stop_reason': 'end_turn', 'usage': {}}
OPENAI_GROUNDED = {'status': 'completed', 'output': [
    {'type': 'web_search_call', 'status': 'completed', 'action': {'type': 'search', 'sources': [{'url': 'https://blog.example/guitar'}]}},
    {'type': 'message', 'content': [{'type': 'output_text', 'text': 'Justin Guitar has a free course.',
                                     'annotations': [{'type': 'url_citation', 'url': 'https://justinguitar.com/g1', 'title': 'Justin Guitar', 'start_index': 0, 'end_index': 5}]}]}], 'usage': {}}


def _canned(body):
    import io
    def f(request, timeout=60):
        _canned.sent.append(json.loads(request.data.decode('utf-8')))
        return io.BytesIO(json.dumps(body).encode('utf-8'))
    _canned.sent = []
    return f


def scenario_claude_grounding_parses_citations_and_results():
    from unittest.mock import patch
    from services import llm_budget
    with patch.object(llm_budget, 'urlopen', _canned(CLAUDE_GROUNDED)):
        out = web._anthropic_grounded('guitar course?', 'A', model='claude-sonnet-5-5')
    body = _canned.sent[0]
    check(body['tools'] == [{'type': 'web_search_20260209', 'name': 'web_search', 'max_uses': 3}], body['tools'])
    check(body['model'] == 'claude-sonnet-5-5' and 'temperature' not in body, 'bare id, no temperature')
    check(out['answer'] == 'Justin Guitar has a free beginner course. Start there.', out)
    check(out['sources'] == [{'title': 'Justin Guitar', 'url': 'https://justinguitar.com/g1'}], out['sources'])
    check(out['suggestions_html'] == '', 'no Google chip off Gemini')
    with patch.object(llm_budget, 'urlopen', _canned({'content': [{'type': 'web_search_tool_result', 'content': {'type': 'web_search_tool_result_error', 'error_code': 'max_uses_exceeded'}}], 'stop_reason': 'end_turn'})):
        out = web._anthropic_grounded('q', 'A', model='claude-sonnet-5-5')
    check(out.get('error') == 'max_uses_exceeded', f'a server-tool error object is the error: {out}')


def scenario_openai_grounding_parses_annotations_and_sources():
    from unittest.mock import patch
    from services import llm_budget
    with patch.object(llm_budget, 'urlopen', _canned(OPENAI_GROUNDED)):
        out = web._openai_grounded('guitar course?', 'O', model='gpt-6.1-sol')
    body = _canned.sent[0]
    check(body['tools'] == [{'type': 'web_search', 'search_context_size': 'low'}], body['tools'])
    check(body['include'] == ['web_search_call.action.sources'], body.get('include'))
    check(out['answer'] == 'Justin Guitar has a free course.', out)
    check([s['url'] for s in out['sources']] == ['https://justinguitar.com/g1', 'https://blog.example/guitar'], out['sources'])


def scenario_research_dispatches_on_the_provider():
    _reset()
    storage.get_settings = lambda: {'llm_provider': 'anthropic', 'llm_anthropic_api_key': 'A', 'web_research_enabled': True, 'web_research_via': 'model'}
    calls = []
    web._anthropic_grounded = lambda q, key, model=None: (calls.append(('anthropic', key, model)) or {'answer': 'A.', 'sources': [{'title': 't', 'url': 'https://x.example/'}], 'suggestions_html': ''})
    res = web.research('q?')
    check(res['status'] == 'ok' and res['via'] == 'grounding' and calls == [('anthropic', 'A', None)], f'{res} {calls}')
    storage.get_settings = lambda: {'llm_provider': 'openai', 'llm_openai_api_key': 'O', 'web_research_enabled': True, 'web_research_via': 'model'}
    web._openai_grounded = lambda q, key, model=None: {'answer': 'B.', 'sources': [], 'suggestions_html': ''}
    storage.set_app_state('web_search_cache', {})
    res = web.research('q2?')
    check(res['status'] == 'ok' and res['answer'] == 'B.', res)
    storage.get_settings = lambda: {'llm_provider': 'ollama', 'web_research_enabled': True, 'web_research_via': 'model'}
    res = web.research('q3?')
    check(res['status'] == 'error' and "can't search" in res['message'], res)
```

Add the three calls to `__main__`; `_reset` must also stub the two new functions (`web._anthropic_grounded = web._openai_grounded = lambda q, key, model=None: {'error': 'not stubbed'}`) so existing scenarios stay isolated.

- [ ] **Step 2: Run to verify it fails**

Run: `cd chauffeur && python tests/test_web_research.py`
Expected: `AttributeError: module 'services.web' has no attribute '_anthropic_grounded'`.

- [ ] **Step 3: Implement**

```python
def _anthropic_grounded(question: str, api_key: str, model: str = None) -> dict:
    from services import model_pools, llm_budget, llm as _llm
    settings = storage.get_settings() or {}
    candidates = [model] if model else [model_pools.split_model(m)[1] for m in model_pools.models_for('heavy', settings)[:2]
                                        if model_pools.split_model(m)[0] == 'anthropic' and 'haiku' not in m]
    last_err = None
    for m in candidates:
        payload = {'model': m, 'max_tokens': 2048, 'system': GROUND_SYSTEM.replace('Google Search', 'web search'),
                   'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': f"QUESTION: {question}"}]}],
                   'tools': [{'type': 'web_search_20260209', 'name': 'web_search', 'max_uses': 3}],
                   'output_config': {'effort': 'low'}}
        req = urllib.request.Request(_llm.ANTHROPIC_URL, data=json.dumps(payload).encode('utf-8'), method='POST',
                                     headers={'Content-Type': 'application/json', 'x-api-key': api_key, 'anthropic-version': '2023-06-01'})
        try:
            with llm_budget.urlopen(req, timeout=SEARCH_TIMEOUT + 40) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            last_err = f"{e.code} {e.read().decode('utf-8', errors='replace')[:300]}"
            model_pools.note_failure('anthropic:' + m, last_err)
            continue
        except Exception as e:
            last_err = str(e)
            continue
        answer, sources, seen = '', [], set()
        def _add(url, title):
            if url and url not in seen:
                seen.add(url); sources.append({'title': (title or '').strip() or url, 'url': url})
        for b in data.get('content') or []:
            if b.get('type') == 'text':
                answer += b.get('text') or ''
                for c in b.get('citations') or []:
                    _add(c.get('url'), c.get('title'))
            elif b.get('type') == 'web_search_tool_result':
                c = b.get('content')
                if isinstance(c, dict):
                    return {'error': c.get('error_code') or 'web_search_error'}
                for r in c or []:
                    _add(r.get('url'), r.get('title'))
        if answer.strip():
            return {'answer': answer.strip(), 'sources': sources, 'suggestions_html': '', 'model': 'anthropic:' + m}
        last_err = 'empty answer'
    return {'error': last_err or 'no Claude model in the pool can search the web'}
```

`_openai_grounded` is the same loop over `[split_model(m)[1] for m in models_for('heavy') if provider openai]` with payload `{'model': m, 'instructions': ..., 'input': f"QUESTION: {question}", 'tools': [{'type': 'web_search', 'search_context_size': 'low'}], 'include': ['web_search_call.action.sources'], 'reasoning': {'effort': 'low'}}` to `_llm.OPENAI_URL` with the bearer header; answer = the `message` item's `output_text` texts; sources = each `url_citation` annotation first, then every `web_search_call.action.sources[].url` (title = url) not already seen.

In `research`, the `via == 'model'` branch:

```python
    if via == 'model':
        prov = model_pools.provider(settings)
        if prov == 'ollama':
            return {'status': 'error', 'message': "The local model can't search the web. Pick Brave or SerpApi for research in Config."}
        grounded_fn = {'gemini': _gemini_grounded, 'anthropic': _anthropic_grounded, 'openai': _openai_grounded}[prov]
        api_key = api_key or model_pools.credentials('heavy', settings)[1]
        ...
            if own_key and prov == 'gemini':
                <the existing flash-by-name loop>
            else:
                grounded = grounded_fn(question, api_key) or {}
        ...
            return {'status': 'error', 'message': f"{'Gemini' if prov == 'gemini' else 'Claude' if prov == 'anthropic' else 'OpenAI'} couldn't search the web: " + _plain_error(grounded.get('error'))}
```

and the earlier `api_key = api_key or settings.get('llm_gemini_api_key', '')` / `no_key` check becomes `api_key = api_key or model_pools.credentials('heavy', settings)[1]`. Registry help for `web_research_via`: "Your main AI model searches the web itself (Gemini, Claude and OpenAI all can) unless you pick Brave or SerpApi. Research only ever uses the one chosen."

- [ ] **Step 4: Run tests**

Run: `cd chauffeur && python tests/test_web_research.py`
Expected: OK, every pre-existing scenario included.

- [ ] **Step 5: Commit**

```bash
git add chauffeur/services/web.py chauffeur/services/settings_registry.py chauffeur/tests/test_web_research.py
git commit -m "feat(research): web research on the chosen provider - Claude web_search and OpenAI web_search grounded calls beside Gemini's, same sources contract, dispatch by provider"
```

---

### Task 7: Five provider-neutral runner changes in `browse.py` (Claude)

**Files:**
- Modify: `chauffeur/services/browse.py` (`_act` line 901, `_field_at` line 975 (add `_focused_field`), the finish-on-empty branch 1286-1300, the per-call loop 1387-1595)
- Modify: `chauffeur/tests/test_browse_runner.py` (append scenarios)
- Modify: `chauffeur/tests/browse_pages.py` if a page with a postal-code box that is not in the contact-required set is needed (the `/form` page may already have one; check its labels first)

**Interfaces:**
- Produces, in the step contract `{'calls', 'text', 'content', 'tokens'}`: two new runner call names, `look` (no action; the result is a fresh screenshot) and `refuse` (`args: {'reason': str}`; no action; result `{'error': reason}`); `function_responses` tuples become `(name, {'url': <url right after this action>, **response}, <shot right after this action>)`; the step dict's optional `'ids'` is passed through untouched (adapters' business).
- The CAPTCHA gate reads `args['safety_decision']` exactly as today; adapters produce it (Task 8).

- [ ] **Step 1: Write the failing scenarios (append to `tests/test_browse_runner.py`)**

```python
def scenario_coordinate_free_typing_meets_the_release_gate():
    """A click on the ZIP box, then a bare `type` with nothing released: the focused box's
    label is the field, and a guess is a release question (spec §7 change 1)."""
    _reset()
    storage.get_settings = lambda: {'missions_submit_enabled': True, 'llm_gemini_paid_api_key': 'paid'}   # empty card
    zx, zy = _xy(f'{URL}/form', 'input[name=zip]')
    browse._model_step = _script([_click((zx, zy))], [{'name': 'type', 'args': {'text': '35203'}}], 'DONE.')
    r = browse.run('fill the form', SITE, {}, {}, start_url=f'{URL}/form', out_dir=OUT)
    check(r['outcome'] == 'needs_release' and 'zip' in (r.get('wanted_fields') or []), r)
    from browse_pages import H
    check(not any('35203' in str(p) for p in H.posts), 'nothing was typed')


def scenario_look_and_refuse_turns_continue_then_cap():
    _reset()
    fake, seen = _recording([{'name': 'look', 'args': {}}], [{'name': 'refuse', 'args': {'reason': 'right_click is not available here'}}],
                            [{'name': 'look', 'args': {}}], [{'name': 'look', 'args': {}}], 'DONE.')
    browse._model_step = fake
    r = browse.run('read the page', SITE, {}, {}, start_url=URL, out_dir=OUT)
    check(r['outcome'] == 'capped' and 'looking' in r['text'], f'three idle turns in a row cap the run: {r}')
    frs = [c['function_responses'] for c in seen if isinstance(c, dict) and 'function_responses' in c]
    check(len(frs) >= 2 and frs[0][0][0] == 'look' and frs[0][0][2][:4] == b'\x89PNG', 'a look is answered with a screenshot')
    check(frs[1][0][1].get('error') == 'right_click is not available here', 'a refuse is answered with its reason')
    check(r['actions'] == 0, 'neither counts as an action')


def scenario_each_result_carries_its_own_screenshot_and_url():
    _reset()
    other = f'{URL}/other'
    fake, seen = _recording([{'name': 'navigate', 'args': {'url': other}}, {'name': 'go_back', 'args': {}}], 'DONE.')
    browse._model_step = fake
    browse.run('go there and back', SITE, {}, {}, start_url=URL, out_dir=OUT)
    fr = [c['function_responses'] for c in seen if isinstance(c, dict) and 'function_responses' in c][0]
    check(fr[0][1]['url'].rstrip('/') == other and fr[1][1]['url'].rstrip('/') == URL, f'each url is the page right after that action: {[x[1] for x in fr]}')
    check(fr[0][2] != fr[1][2], 'two screens, two different screenshots')
    import glob
    check(len(glob.glob(os.path.join(OUT, 'turn_01_*.png'))) == 2, 'one file per action, none overwritten')


def scenario_a_refusal_reaches_the_next_turn():
    _reset()
    blank = {'name': 'click_at', 'args': {'x': 5, 'y': 5}}
    fake, seen = _recording([blank], [blank], [blank], 'DONE.')
    browse._model_step = fake
    browse.run('click', SITE, {}, {}, start_url=URL, out_dir=OUT)
    errs = _errors(seen)
    check(any('same' in e or 'third' in e or 'loop' in e for e in errs), f'the repeated-action refusal is in the responses the model saw: {errs}')
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd chauffeur && python tests/test_browse_runner.py`
Expected: the first new scenario fails (`outcome` is `done`, the ZIP was typed) or the second (`look` is treated as an unknown action and the run says `done`).

- [ ] **Step 3: Implement**

`_focused_field(page)` beside `_field_at`: the same label-extraction JS run on `document.activeElement` instead of `elementFromPoint`, returning the contact-card field name or None.

In the per-call loop, the type gate (line ~1462):

```python
                if is_type and not press_now:
                    field = _field_at(page, *_px(args['x'], args['y'])) if 'x' in args else _focused_field(page)
                    if field and field not in released:
                        report['wanted_fields'] = [field]
                        return finish('needs_release', f"the page's {field} box wants the family's {field}; nothing was typed")
```

Idle turns: before the per-call loop, `idle_turns = 0` at run start; after the loop over calls, `idle_turns = idle_turns + 1 if all(c.get('name') in ('look', 'refuse') for c in calls) else 0`; `if idle_turns >= 3: return finish('capped', 'the model kept looking without acting')`.

In the loop, right after `name, args = ...` and the `sd`/`is_*` lines:

```python
                if name in ('look', 'refuse'):
                    res = {'error': str(args.get('reason') or 'not available here')} if name == 'refuse' else {}
                    shot = page.screenshot(type='png')
                    p = os.path.join(out_dir, f'turn_{turn:02d}_{i_call}.png')
                    with open(p, 'wb') as f:
                        f.write(shot)
                    report['screenshots'].append(p)
                    report['turns_log'].append({'turn': turn, 'action': name, 'url': page.url, 'model_ms': model_ms if i_call == 0 else 0, 'act_ms': 0})
                    results.append((name, args, {'url': page.url, **res}, shot))
                    continue
```

Every other `results.append((name, args, X))` in the loop becomes `results.append((name, args, {'url': page.url, **X}, page.screenshot(type='png')))` (the refusal branches included), and the end-of-call block:

```python
                shot = page.screenshot(type='png')
                p = os.path.join(out_dir, f'turn_{turn:02d}_{i_call}.png')
                ...
                results.append((name, args, {'url': page.url, **res}, shot))
            contents.append({'role': 'user', 'function_responses': [(n, r, s) for n, a, r, s in results]})
```

`report['actions'] += 1` is not reached for `look`/`refuse` (the `continue` is above it). The `pressed and name not in (...)` after-press refusal list gains `'look', 'refuse'`.

- [ ] **Step 4: Run the runner tests (real Playwright, ~2 min)**

Run: `cd chauffeur && python tests/test_browse_runner.py`
Expected: OK, all pre-existing scenarios included (the `function_responses` shape change is additive: `url` was already in the dict).

- [ ] **Step 5: Commit**

```bash
git add chauffeur/services/browse.py chauffeur/tests/test_browse_runner.py chauffeur/tests/browse_pages.py
git commit -m "feat(browse): runner changes every provider needs - coordinate-free typing meets the release gate by the focused box, look/refuse turns continue and cap, each result keeps its own screenshot and url"
```

---

### Task 8: Browse adapters for Claude and OpenAI (Codex, against Claude's tests)

**Files:**
- Modify: `chauffeur/services/browse.py` (`_model_step` dispatch line ~470, new `_model_step_anthropic`, `_model_step_openai`, `to_runner_call`, `TYPE_AT_SENTENCE`)
- Modify: `chauffeur/tests/test_browse_runner.py` (append scenarios; these need no browser)

**Interfaces:**
- Consumes: `model_pools.models_for('browse')`, `split_model`, `api_key_for_pool('cu')`, `llm_budget.urlopen`, `llm.ANTHROPIC_URL` / `OPENAI_URL`, the runner contract from Task 7 (`look`, `refuse`, `function_responses` tuples `(name, response, shot)`), `W, H`.
- Produces: `_model_step(contents, settings)` dispatches on the cu pool's provider; adapters return `{'calls': [...], 'text': str, 'content': <opaque entry>, 'tokens': (in, out)}` where the opaque entry is `{'_provider': 'anthropic', 'content': [...blocks...], 'ids': [tool_use_id, ...]}` or `{'_provider': 'openai', 'response_id': str, 'ids': [(call_id, 'computer'|'function'), ...]}`; `to_runner_call(provider, name, input) -> dict` (pure, tested).

- [ ] **Step 1: Write the failing scenarios (append)**

```python
def scenario_claude_members_become_runner_calls_in_permille():
    W, H = browse.W, browse.H
    f = browse.to_runner_call
    check(f('anthropic', 'left_click', {'coordinate': [720, 450]}) == {'name': 'click_at', 'args': {'x': 500, 'y': 500}}, f('anthropic', 'left_click', {'coordinate': [720, 450]}))
    check(f('anthropic', 'double_click', {'coordinate': [144, 90]})['name'] == 'double_click_at', 'double')
    check(f('anthropic', 'type', {'text': 'hi'}) == {'name': 'type', 'args': {'text': 'hi'}}, 'coordinate-free type')
    check(f('anthropic', 'key', {'text': 'ctrl+a'}) == {'name': 'key_combination', 'args': {'keys': ['ctrl', 'a']}}, 'keys split')
    check(f('anthropic', 'scroll', {'coordinate': [720, 450], 'scroll_direction': 'down', 'scroll_amount': 3}) == {'name': 'scroll_at', 'args': {'x': 500, 'y': 500, 'direction': 'down', 'magnitude': 300}}, 'scroll')
    check(f('anthropic', 'mouse_move', {'coordinate': [0, 0]})['name'] == 'hover_at', 'hover')
    d = f('anthropic', 'left_click_drag', {'start_coordinate': [0, 0], 'coordinate': [1440, 900]})
    check(d == {'name': 'drag_and_drop', 'args': {'x': 0, 'y': 0, 'destination_x': 1000, 'destination_y': 1000}}, d)
    check(f('anthropic', 'wait', {'duration': 1}) == {'name': 'wait', 'args': {}}, 'wait')
    check(f('anthropic', 'screenshot', {}) == {'name': 'look', 'args': {}}, 'screenshot is a look')
    r = f('anthropic', 'right_click', {'coordinate': [1, 1]})
    check(r['name'] == 'refuse' and 'right_click' in r['args']['reason'], r)
    check(f('anthropic', 'navigate', {'url': 'https://a.example/'}) == {'name': 'navigate', 'args': {'url': 'https://a.example/'}}, 'function tool')
    check(f('anthropic', 'go_back', {}) == {'name': 'go_back', 'args': {}}, 'go_back')


def scenario_openai_actions_become_runner_calls():
    f = browse.to_runner_call
    check(f('openai', 'click', {'button': 'left', 'x': 720, 'y': 450}) == {'name': 'click_at', 'args': {'x': 500, 'y': 500}}, 'click')
    check(f('openai', 'click', {'button': 'right', 'x': 1, 'y': 1})['name'] == 'refuse', 'right button refused')
    check(f('openai', 'keypress', {'keys': ['CTRL', 'A']}) == {'name': 'key_combination', 'args': {'keys': ['ctrl', 'a']}}, 'keypress')
    check(f('openai', 'scroll', {'x': 720, 'y': 450, 'scroll_x': 0, 'scroll_y': -600}) == {'name': 'scroll_at', 'args': {'x': 500, 'y': 500, 'direction': 'up', 'magnitude': 600}}, 'scroll up')
    check(f('openai', 'drag', {'path': [{'x': 0, 'y': 0}, {'x': 720, 'y': 450}, {'x': 1440, 'y': 900}]})['args']['destination_x'] == 1000, 'drag last point')
    check(f('openai', 'screenshot', {}) == {'name': 'look', 'args': {}} and f('openai', 'wait', {}) == {'name': 'wait', 'args': {}}, 'look/wait')


def scenario_claude_step_builds_the_request_and_reads_the_turn():
    from unittest.mock import patch
    from services import llm_budget
    import base64, io, json as _json
    sent = []
    turn = {'content': [{'type': 'thinking', 'thinking': ''},
                        {'type': 'text', 'text': 'CHALLENGE: the box says I am not a robot'},
                        {'type': 'tool_use', 'id': 'tu_1', 'name': 'left_click', 'input': {'coordinate': [720, 450]}, 'toolset_name': 'computer'},
                        {'type': 'tool_use', 'id': 'tu_2', 'name': 'screenshot', 'input': {}, 'toolset_name': 'computer'}],
            'stop_reason': 'tool_use', 'usage': {'input_tokens': 100, 'output_tokens': 20}}
    def fake(request, timeout=60):
        sent.append(_json.loads(request.data.decode('utf-8')))
        return io.BytesIO(_json.dumps(turn).encode('utf-8'))
    settings = {'llm_provider': 'anthropic', 'llm_anthropic_api_key': 'A', 'missions_captcha_attempts': True}
    contents = [{'role': 'user', 'parts': [{'text': browse.RUNNER_SYSTEM + '\n\nGOAL'}, {'image': b'\x89PNG1'}]}]
    with patch.object(llm_budget, 'urlopen', fake):
        step = browse._model_step_anthropic(contents, settings)
    body = sent[0]
    check(body['model'] == 'claude-sonnet-5-5' and body['output_config']['effort'] == 'low' and 'temperature' not in body, body.keys())
    types = [t.get('type') or t.get('name') for t in body['tools']]
    check(types[0] == 'computer_toolset_20260801' and body['tools'][0]['configs'] == {'zoom': {'enabled': False}}, body['tools'][0])
    check({'navigate', 'go_back'} <= set(types), 'navigate and go_back are function tools')
    check(body['messages'][0]['content'][1]['source']['data'] == base64.b64encode(b'\x89PNG1').decode(), 'the image went as base64')
    check('CHALLENGE:' in body['system'] and 'focused box' in body['system'], 'the adapter system text')
    check('type_text_at clicks the box itself' not in body['messages'][0]['content'][0]['text'], 'the Gemini-only sentence is stripped from the runner text')
    check(step['calls'][0] == {'name': 'click_at', 'args': {'x': 500, 'y': 500, 'safety_decision': {'decision': 'require_confirmation', 'explanation': 'CAPTCHA: the box says I am not a robot'}}}, step['calls'][0])
    check(step['calls'][1] == {'name': 'look', 'args': {}}, step['calls'][1])
    check(step['content']['_provider'] == 'anthropic' and step['content']['ids'] == ['tu_1', 'tu_2'], step['content'])
    check(step['tokens'] == (100, 20), step['tokens'])
    # the next turn: the runner's answers go back as tool_results, in order, with toolset_name on each
    contents += [step['content'], {'role': 'user', 'function_responses': [('click_at', {'url': 'u1', 'safety_acknowledgement': 'true'}, b'\x89PNG2'), ('look', {'url': 'u1'}, b'\x89PNG3')]}]
    with patch.object(llm_budget, 'urlopen', fake):
        browse._model_step_anthropic(contents, settings)
    msgs = sent[1]['messages']
    check(msgs[1]['role'] == 'assistant' and msgs[1]['content'] == turn['content'], 'the assistant turn is replayed unchanged, thinking included')
    results = msgs[2]['content']
    check([r['tool_use_id'] for r in results] == ['tu_1', 'tu_2'] and all(r.get('toolset_name') == 'computer' for r in results), results)
    check(results[0]['content'][0]['type'] == 'text' and 'u1' in results[0]['content'][0]['text'], 'the response text rides along')
    check(results[0]['content'][1]['type'] == 'image', 'every result carries its screenshot')


def scenario_openai_step_uses_previous_response_id_and_call_outputs():
    from unittest.mock import patch
    from services import llm_budget
    import io, json as _json
    sent = []
    turn = {'id': 'resp_1', 'status': 'completed', 'output': [
        {'type': 'computer_call', 'call_id': 'cc_1', 'actions': [{'type': 'click', 'button': 'left', 'x': 720, 'y': 450}], 'status': 'completed'},
        {'type': 'function_call', 'call_id': 'fc_1', 'name': 'navigate', 'arguments': '{"url": "https://a.example/"}'}],
        'usage': {'input_tokens': 50, 'output_tokens': 9}}
    def fake(request, timeout=60):
        sent.append(_json.loads(request.data.decode('utf-8')))
        return io.BytesIO(_json.dumps(turn).encode('utf-8'))
    settings = {'llm_provider': 'openai', 'llm_openai_api_key': 'O'}
    contents = [{'role': 'user', 'parts': [{'text': 'GOAL'}, {'image': b'\x89PNG1'}]}]
    with patch.object(llm_budget, 'urlopen', fake):
        step = browse._model_step_openai(contents, settings)
    body = sent[0]
    check(body['model'] == 'gpt-6.1-sol' and body['reasoning'] == {'effort': 'low'} and body['truncation'] == 'auto', body.keys())
    check(body['tools'][0] == {'type': 'computer'} and {t.get('name') for t in body['tools'][1:]} == {'navigate', 'go_back'}, body['tools'])
    check(step['calls'] == [{'name': 'click_at', 'args': {'x': 500, 'y': 500}}, {'name': 'navigate', 'args': {'url': 'https://a.example/'}}], step['calls'])
    check(step['content'] == {'_provider': 'openai', 'response_id': 'resp_1', 'ids': [('cc_1', 'computer'), ('fc_1', 'function')]}, step['content'])
    contents += [step['content'], {'role': 'user', 'function_responses': [('click_at', {'url': 'u1'}, b'\x89PNG2'), ('navigate', {'url': 'https://a.example/'}, b'\x89PNG3')]}]
    with patch.object(llm_budget, 'urlopen', fake):
        browse._model_step_openai(contents, settings)
    body = sent[1]
    check(body['previous_response_id'] == 'resp_1', 'continues the server-side thread')
    items = body['input']
    check(items[0]['type'] == 'computer_call_output' and items[0]['call_id'] == 'cc_1' and items[0]['output']['type'] == 'computer_screenshot' and items[0]['output']['image_url'].startswith('data:image/png;base64,'), items[0])
    check(items[1]['type'] == 'function_call_output' and items[1]['call_id'] == 'fc_1' and 'a.example' in items[1]['output'], items[1])
    check(len(items) == 2, 'only the new items go; the history is on the server')


def scenario_model_step_dispatches_on_the_cu_pool():
    seen = []
    reals = browse._model_step_live, browse._model_step_anthropic, browse._model_step_openai
    browse._model_step_live = lambda c, s: seen.append('gemini') or {}
    browse._model_step_anthropic = lambda c, s: seen.append('anthropic') or {}
    browse._model_step_openai = lambda c, s: seen.append('openai') or {}
    try:
        browse._model_step_dispatch([], {'llm_provider': 'anthropic'})
        browse._model_step_dispatch([], {'llm_provider': 'openai'})
        browse._model_step_dispatch([], {})
        browse._model_step_dispatch([], {'model_pool_cu': 'gemini-3.8-flash', 'llm_provider': 'anthropic'})
    finally:
        browse._model_step_live, browse._model_step_anthropic, browse._model_step_openai = reals
    check(seen == ['anthropic', 'openai', 'gemini', 'gemini'], f'dispatch follows the cu pool first model: {seen}')
```

(`scenario_pool_cu_bills_the_paid_key_only` and `scenario_live_step_builds_the_computer_use_call` stay as they are.) Add the five to `__main__`.

- [ ] **Step 2: Run to verify it fails**

Run: `cd chauffeur && python tests/test_browse_runner.py`
Expected: `AttributeError: module 'services.browse' has no attribute 'to_runner_call'`.

- [ ] **Step 3: Implement**

Shared pieces:

```python
ADAPTER_TYPING_TEXT = (" Type into the focused box: click it first, then type; there is no type-at-coordinates here."
                       " Before you click a verification widget (reCAPTCHA, 'I am not a robot', a puzzle), write a line"
                       " starting CHALLENGE: that says what it is; the click is then counted as a challenge attempt."
                       " Right, middle and triple clicks, held keys and the cursor position are not available.")
CHALLENGE_LINE = re.compile(r'^CHALLENGE:\s*(.*)$', re.I | re.M)
FUNCTION_TOOLS = [
    {'name': 'navigate', 'description': 'Open a URL in this browser tab.', 'input_schema': {'type': 'object', 'properties': {'url': {'type': 'string'}}, 'required': ['url']}},
    {'name': 'go_back', 'description': 'Go back one page.', 'input_schema': {'type': 'object', 'properties': {}}},
]
UNSUPPORTED = ('right_click', 'middle_click', 'triple_click', 'hold_key', 'left_mouse_down', 'left_mouse_up', 'cursor_position', 'zoom')


def _permille(x, y):
    return int(round(float(x) * 1000 / W)), int(round(float(y) * 1000 / H))


TYPE_AT_SENTENCE = "type_text_at clicks the box itself: no separate click first. "
```

(`TYPE_AT_SENTENCE` is the exact sentence inside `RUNNER_SYSTEM` at line 93; it is pulled out into this constant and concatenated back into `RUNNER_SYSTEM` so Gemini's text stays byte-identical. The runner puts the whole system text into the first user part, so an adapter does not build a system prompt of its own: it strips that sentence from the first user text on the way out and sends `ADAPTER_TYPING_TEXT` as the request's `system` / `instructions`.)

```python
def to_runner_call(provider: str, name: str, inp: dict) -> dict:
    inp = inp or {}
    if name in ('navigate', 'go_back'):
        return {'name': name, 'args': ({'url': inp.get('url', '')} if name == 'navigate' else {})}
    if name == 'screenshot':
        return {'name': 'look', 'args': {}}
    if name == 'wait':
        return {'name': 'wait', 'args': {}}
    if provider == 'anthropic':
        if name in UNSUPPORTED:
            return {'name': 'refuse', 'args': {'reason': f'{name} is not available here'}}
        c = inp.get('coordinate') or [0, 0]
        x, y = _permille(c[0], c[1])
        if name == 'left_click': return {'name': 'click_at', 'args': {'x': x, 'y': y}}
        if name == 'double_click': return {'name': 'double_click_at', 'args': {'x': x, 'y': y}}
        if name == 'type': return {'name': 'type', 'args': {'text': str(inp.get('text') or '')}}
        if name == 'key': return {'name': 'key_combination', 'args': {'keys': [k.strip().lower() for k in str(inp.get('text') or '').split('+') if k.strip()]}}
        if name == 'scroll': return {'name': 'scroll_at', 'args': {'x': x, 'y': y, 'direction': inp.get('scroll_direction', 'down'), 'magnitude': int(inp.get('scroll_amount') or 3) * 100}}
        if name == 'mouse_move': return {'name': 'hover_at', 'args': {'x': x, 'y': y}}
        if name == 'left_click_drag':
            s = inp.get('start_coordinate') or [0, 0]
            sx, sy = _permille(s[0], s[1])
            return {'name': 'drag_and_drop', 'args': {'x': sx, 'y': sy, 'destination_x': x, 'destination_y': y}}
        return {'name': 'refuse', 'args': {'reason': f'{name} is not available here'}}
    # openai
    if name == 'click':
        if (inp.get('button') or 'left') != 'left':
            return {'name': 'refuse', 'args': {'reason': f"{inp.get('button')} click is not available here"}}
        x, y = _permille(inp.get('x', 0), inp.get('y', 0)); return {'name': 'click_at', 'args': {'x': x, 'y': y}}
    if name == 'double_click':
        x, y = _permille(inp.get('x', 0), inp.get('y', 0)); return {'name': 'double_click_at', 'args': {'x': x, 'y': y}}
    if name == 'type': return {'name': 'type', 'args': {'text': str(inp.get('text') or '')}}
    if name == 'keypress': return {'name': 'key_combination', 'args': {'keys': [str(k).lower() for k in (inp.get('keys') or [])]}}
    if name == 'scroll':
        x, y = _permille(inp.get('x', 0), inp.get('y', 0))
        dx, dy = int(inp.get('scroll_x') or 0), int(inp.get('scroll_y') or 0)
        direction = ('down' if dy > 0 else 'up') if abs(dy) >= abs(dx) else ('right' if dx > 0 else 'left')
        return {'name': 'scroll_at', 'args': {'x': x, 'y': y, 'direction': direction, 'magnitude': max(abs(dx), abs(dy)) or 600}}
    if name == 'move':
        x, y = _permille(inp.get('x', 0), inp.get('y', 0)); return {'name': 'hover_at', 'args': {'x': x, 'y': y}}
    if name == 'drag':
        path = inp.get('path') or [{'x': 0, 'y': 0}]
        sx, sy = _permille(path[0]['x'], path[0]['y']); ex, ey = _permille(path[-1]['x'], path[-1]['y'])
        return {'name': 'drag_and_drop', 'args': {'x': sx, 'y': sy, 'destination_x': ex, 'destination_y': ey}}
    return {'name': 'refuse', 'args': {'reason': f'{name} is not available here'}}
```

Claude adapter:

```python
def _model_step_anthropic(contents, settings):
    from services import model_pools, llm_budget, llm as _llm
    import base64
    key = model_pools.api_key_for_pool('cu', settings)
    model = model_pools.split_model(model_pools.models_for('browse', settings)[0])[1]
    messages, pending_ids = [], None
    for c in contents:
        if isinstance(c, dict) and c.get('_provider') == 'anthropic':
            messages.append({'role': 'assistant', 'content': c['content']})
            pending_ids = c['ids']
        elif isinstance(c, dict) and 'function_responses' in c:
            blocks = []
            for tid, (name, resp, shot) in zip(pending_ids or [], c['function_responses']):
                note = resp.get('error') or f"ok; page: {resp.get('url', '')}"
                content = [{'type': 'text', 'text': note}]
                if shot:
                    content.append({'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': base64.b64encode(shot).decode()}})
                blocks.append({'type': 'tool_result', 'tool_use_id': tid, 'toolset_name': 'computer', 'content': content})
            messages.append({'role': 'user', 'content': blocks})
        elif isinstance(c, dict) and 'parts' in c:
            content = []
            for p in c['parts']:
                if 'text' in p: content.append({'type': 'text', 'text': p['text']})
                elif 'image' in p: content.append({'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': base64.b64encode(p['image']).decode()}})
            messages.append({'role': c.get('role', 'user'), 'content': content})
    if messages and messages[0]['content'] and messages[0]['content'][0].get('type') == 'text':
        messages[0]['content'][0]['text'] = messages[0]['content'][0]['text'].replace(TYPE_AT_SENTENCE, '')
    payload = {'model': model, 'max_tokens': 4096, 'system': ADAPTER_TYPING_TEXT, 'messages': messages,
               'output_config': {'effort': 'low'},
               'tools': [{'type': 'computer_toolset_20260801', 'configs': {'zoom': {'enabled': False}}}, *FUNCTION_TOOLS]}
    req = urllib.request.Request(_llm.ANTHROPIC_URL, data=json.dumps(payload).encode('utf-8'), method='POST',
                                 headers={'Content-Type': 'application/json', 'x-api-key': key, 'anthropic-version': '2023-06-01'})
    with llm_budget.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    blocks = data.get('content') or []
    text = ' '.join(b.get('text', '') for b in blocks if b.get('type') == 'text')
    m = CHALLENGE_LINE.search(text)
    calls, ids = [], []
    for b in blocks:
        if b.get('type') != 'tool_use':
            continue
        call = to_runner_call('anthropic', b.get('name'), b.get('input'))
        if m and call['name'].startswith('click'):
            call['args']['safety_decision'] = {'decision': 'require_confirmation', 'explanation': 'CAPTCHA: ' + m.group(1).strip()}
        calls.append(call); ids.append(b['id'])
    usage = data.get('usage') or {}
    return {'calls': calls, 'text': CHALLENGE_LINE.sub('', text).strip(), 'tokens': (usage.get('input_tokens', 0), usage.get('output_tokens', 0)),
            'content': {'_provider': 'anthropic', 'content': blocks, 'ids': ids}}
```

Only the tool_result blocks whose `tid` is the toolset's carry `toolset_name`; for a function tool id (navigate/go_back), omit it: track `kinds` beside `ids` as `('computer'|'function')` exactly as the OpenAI adapter does.

OpenAI adapter: the request's `input` is built from the entries after the last `_provider: 'openai'` entry: a `function_responses` entry becomes one `computer_call_output` (`{'type': 'computer_call_output', 'call_id': id, 'output': {'type': 'computer_screenshot', 'image_url': 'data:image/png;base64,...', 'detail': 'original'}}`) or `function_call_output` (`{'type': 'function_call_output', 'call_id': id, 'output': json.dumps(resp)}`) per tuple, zipped with the stored `ids`; a `parts` entry becomes `{'role': 'user', 'content': [input_text, input_image...]}`. `payload = {'model': model, 'instructions': ADAPTER_TYPING_TEXT, 'input': items, 'tools': [{'type': 'computer'}, *[{'type': 'function', **t} for t in FUNCTION_TOOLS_OPENAI]], 'reasoning': {'effort': 'low'}, 'truncation': 'auto', 'max_output_tokens': 4096}` plus `'previous_response_id'` when a prior entry exists (`FUNCTION_TOOLS_OPENAI` = the same two tools with `parameters` instead of `input_schema`). Output: each `computer_call` item's `actions[]` → `to_runner_call('openai', a['type'], a)` (all under that one `call_id`, kind `computer`; the runner answers each action, so the adapter answers the call with the LAST action's screenshot and ignores the rest for that id); each `function_call` → the runner call with `json.loads(arguments)`, kind `function`; `message` text → `text`, with the same `CHALLENGE:` rule for clicks. Return `{'content': {'_provider': 'openai', 'response_id': data['id'], 'ids': [(call_id, kind), ...]}}`. A `pending_safety_checks` list on a `computer_call` is echoed back as `acknowledged_safety_checks` on its output only if the runner's response for it has no `error` (the runner's gates are the authority).

Dispatch:

```python
def _model_step_dispatch(contents, settings):
    from services import model_pools
    prov = model_pools.split_model(model_pools.models_for('browse', settings)[0])[0]
    return {'anthropic': _model_step_anthropic, 'openai': _model_step_openai}.get(prov, _model_step_live)(contents, settings)


_model_step = _model_step_dispatch
```

(`browse.py:1081`'s `api_key_for_pool('cu')` precheck already follows the selected table after Task 1.)

- [ ] **Step 4: Run tests**

Run: `cd chauffeur && python tests/test_browse_runner.py && python tests/test_browse_mission.py`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add chauffeur/services/browse.py chauffeur/tests/test_browse_runner.py
git commit -m "feat(browse): missions on Claude or OpenAI - computer_toolset / computer tool adapters behind _model_step, navigate and go_back as function tools, permille coordinates, CHALLENGE lines carry the consent gate, every result answered by id"
```

---

### Task 9: Documentation, memory, version bump, final commit (Claude)

**Files:**
- Modify: `chauffeur/system_capabilities.md` (new top entry)
- Modify: `chauffeur/config.yaml` (version)
- Modify: `C:\Users\ffejn\.claude\projects\e--repositories-Chauffeur\memory\` (new arc file + `MEMORY.md` line)

- [ ] **Step 1: Run the whole gate once more**

Run from `chauffeur/` with `HA_BASE_URL` unset:
```
python tests/test_model_pool_providers.py && python tests/test_llm_providers.py && python tests/test_llm_budget.py && python tests/test_provider_settings.py && python tests/test_provider_preflights.py && python tests/test_web_research.py && python tests/test_browse_runner.py && python tests/test_missions_pools.py && python tests/test_missions_pins.py && python tests/test_model_pool_overload.py && python tests/test_agent_llm_errors.py && python tests/test_settings_registry.py && python tests/test_trip_planner.py && python tests/test_meals.py && python tests/test_browse_mission.py
```
Expected: every file prints its OK line.

- [ ] **Step 2: `system_capabilities.md` entry at the top**

One paragraph in the file's house style: the selector, the table, prefixed ids, the two wire branches and what they never send, the cap, research and browse adapters, the five runner changes, the spec and plan paths, the test files, and "NOT device-verified; device steps: Test connection per key, one chat turn, one research question, the dishwasher mission on Claude then OpenAI, nothing booked".

- [ ] **Step 3: Memory**

`model-provider-selector-arc.md` (type project): BUILT vX–vY, NOT device-verified, the device steps, the two OpenAI ids as confirmed in Task 2 step 5, and the parked items (refusal fallbacks not sent; cross-provider fallback inside one call; caching). One line in `MEMORY.md`.

- [ ] **Step 4: Bump and commit**

Bump `version:` in `chauffeur/config.yaml` by one patch, then:

```bash
git add chauffeur/system_capabilities.md chauffeur/config.yaml
git commit -m "docs(ai): model provider selector shipped - Gemini, Claude or OpenAI behind the whole agent (vX.Y.Z)"
git push
```

(Each of Tasks 1–8 is also bumped and committed with `(vX.Y.Z)` in its subject by Claude Code under the always-bump-and-commit rule; Codex leaves its tasks in the working tree with a note, and Claude gates, bumps and commits them.)

---

## Execution split (the standing coordination rule)

| Task | Who | Notes |
|---|---|---|
| 1 pools | Claude | tests first |
| 2 wire branches | Codex via `/codex:rescue` | against Claude's `test_llm_providers.py`; the one network step confirms OpenAI ids |
| 3 budget | Codex | against the appended `test_llm_budget.py` scenarios |
| 4 settings + page | Claude | Tailwind rebuild |
| 5 reroutes | Claude | |
| 6 research | Codex | |
| 7 runner changes | Claude | Playwright tests |
| 8 browse adapters | Codex | pure-function tests + canned turns |
| 9 docs/bump | Claude | |

Order: 1 → (2, 3 in parallel with 4) → 5 → (6, 7 in parallel) → 8 → 9. Codex reviews Claude's diff after 5 and after 7; Claude reviews Codex's after 3, 6 and 8.

"""Free-tier Gemini model pools with cooldown-aware rotation.

The Gemini free tier gives each MODEL its own daily request quota, so models
of similar ability are grouped into pools whose quotas combine (daily caps as
of 2026-08-30):

- lite:  gemini-3.5-flash-lite (500), gemini-3.1-flash-lite (500),
         gemini-2.5-flash-lite (20)  -> ~1,020/day, answers in seconds.
- flash: gemini-3.8/3.7/3.6/3/2.5-flash (20 each) -> ~100/day, highest quality
         (3.5-flash retired by Google 2026-10-09; see RETIRED_MODELS).
- gemma: gemma-4-31b-it (14,400) + whatever large Gemma the key lists (discovered daily), but
         44-180s per call measured on the free API (2026-07-30).
- pro:   gemini-3.1-pro-preview (paid key only, mission tier exclusive).

Tiers map a class of work onto an ordered chain of pools:

- interactive: lite -> gemma. The user is waiting; the scarce 20/day flash
  models are NEVER burned on chat turns.
- background:  gemma -> lite. Nobody is waiting; burn the huge gemma quota
  first and keep lite quota free for interactive traffic.
- heavy:       flash -> lite -> gemma. Rare quality-critical generation only
  (massive trip plans, philosophy -> rules).

A 429 puts the model on cooldown so later calls skip straight to a model with
quota left instead of burning a round-trip: until midnight Pacific (when free
daily quotas reset) if the error body names a per-day quota, else 2 minutes
(per-minute limit). An unknown-model error (404) cools the model for 6 hours
and logs loudly — it usually means a pool default has a stale model id.

HTTP 500/502/503/504 failures also cool a model for two minutes, so later
foreground requests can reach healthy candidates instead of repeating overloads.

The GEMMA pool is discovered, not trusted (2026-10-05): Google renames and
retires Gemma ids: gemma-4-26b-it worked for months, then began answering 404
(Google withdrew it, seen on device 2026-10-05) and left
background work with one real model. Once a day — and at once after a Gemma
404 — the API key's own model list is read (`refresh_gemma_models`) and the
pool becomes the defaults that exist plus any other large Gemma the key can
use. A `model_pool_gemma` setting still wins outright.

Pools are overridable without a code change via comma-separated settings keys
model_pool_lite / model_pool_flash / model_pool_gemma.
"""
import logging
import re
import threading
import time
import datetime

logger = logging.getLogger(__name__)

# Ids Google has withdrawn from the API. Kept so a stored setting that still
# names one can be moved off it (migrations.migrate_retired_gemini_models_*)
# and so a test refuses them in any pool default: a retired id costs a 404
# round trip per call until the 6-hour cooldown, every day.
#   gemini-3.5-flash — deprecation notice received 2026-10-09.
# gemini-3.7-flash and gemini-3-flash: gone from the API (404, 2026-10-11).
RETIRED_MODELS = ("gemini-3.5-flash", "gemini-3.7-flash", "gemini-3-flash")

DEFAULT_POOLS = {
    'lite': ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite"],
    'flash': ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-2.5-flash"],
    # Only a starting point: the Gemma pool is rebuilt from the key's own
    # model list once a day (refresh_gemma_models). gemma-4-26b-it was a
    # working default until Google withdrew it (404 on device, 2026-10-05).
    'gemma': ["gemma-4-31b-it", "gemma-3-27b-it"],
    # gemini-2.5-pro is closed to new users; the live pro id is the -preview
    # one (device-verified error text, 2026-09-06). Served via v1beta only.
    'pro': ["gemini-3.1-pro-preview"],
    # Browse missions (services/browse.py): Gemini Computer Use on flash,
    # billed on the paid key like the pro pool. One model; no free fallback.
    'cu': ["gemini-3.8-flash"],
}

PROVIDERS = ('gemini', 'anthropic', 'openai')

# Each paid provider is a column of the same tier table (spec
# docs/superpowers/specs/2026-10-13-model-provider-selector-design.md §1).
# Bare ids here; _pool stamps the provider prefix on so every id that leaves
# this module says where it goes. Gemma is a Gemini free-tier pool: empty
# elsewhere, and an empty pool contributes nothing to a chain.
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
    """('anthropic', 'claude-haiku-5-5') for a prefixed id; a bare id is
    Gemini. A 'models/' path is Gemini's own namespace, never a prefix."""
    head, sep, rest = (model_id or '').partition(':')
    if sep and head in PROVIDER_POOLS and rest:
        return head, rest
    return 'gemini', model_id or ''


def provider(settings: dict) -> str:
    return (settings or {}).get('llm_provider') or 'gemini'


def _prefixed(prov: str, bare: str) -> str:
    return bare if prov == 'gemini' else f'{prov}:{bare}'


TIER_CHAINS = {
    'interactive': ['lite', 'gemma'],
    'background': ['gemma', 'lite'],
    'mind': ['flash'],  # automated deep reasoning never silently downgrades
    'heavy': ['flash', 'lite', 'gemma'],
    # Image-input calls (intake vision capture). Gemma is text-only so it is
    # excluded; flash first because flyers/screenshots are the hard case and
    # volume is family-scale (dozens/week vs the ~120/day flash quota).
    'vision': ['flash', 'lite'],
    'browse': ['cu'],
    'house_photo': ['flash'],  # architecture must not silently fall back to Lite
    # Missions (services/missions.py). 'mission' is the ONLY tier that touches
    # the pro pool and it never falls back to a free pool — a mission pauses
    # rather than silently degrading. 'mission_flash' exists for benchmarking
    # the same mission on the free flash chain (pure flash: no lite/gemma, so
    # the comparison measures the model, not the fallback).
    'mission': ['pro'],
    'mission_flash': ['flash'],
}

# Free models use their id; paid cooldowns use (model, 'paid'). Keeping free
# ids preserves existing diagnostics that inspect this mapping.
_cooldowns: dict = {}
_lock = threading.Lock()


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
            # Defaults that really exist keep their order; then the rest of
            # what the key offers, largest first.
            keep = [m for m in DEFAULT_POOLS['gemma'] if m in found]
            return keep + [m for m in found if m not in keep][:max(0, GEMMA_POOL_SIZE - len(keep))]
    return list(DEFAULT_POOLS[name])


# --- Gemma discovery ---------------------------------------------------------
GEMMA_POOL_SIZE = 3
GEMMA_MIN_BILLIONS = 12          # smaller Gemmas are too weak for extraction
_DISCOVERY_STATE = 'gemma_models_discovered'
_DISCOVERY_FRESH = 24 * 3600
_DISCOVERY_RETRY = 3600
_discovery_lock = threading.Lock()


def _gemma_size(model: str) -> int:
    """Parameter count in billions from an id ('gemma-4-31b-it' -> 31); an
    'e4b' (effective) id or no size reads as 0."""
    m = re.search(r'-(e?)(\d+)b\b', model)
    return 0 if not m or m.group(1) else int(m.group(2))


def _discovery_row():
    try:
        from services import storage
        return storage.get_app_state(_DISCOVERY_STATE) or {}
    except Exception:
        return {}


def _discovered_gemma():
    row = _discovery_row()
    return list(row.get('models') or []) or None


def gemma_discovery_due() -> bool:
    row = _discovery_row()
    age = time.time() - float(row.get('ts') or 0)
    return age > (_DISCOVERY_FRESH if row.get('models') else _DISCOVERY_RETRY)


def mark_gemma_discovery_stale():
    """A Gemma id just 404'd: look again on the next call."""
    try:
        from services import storage
        row = dict(_discovery_row())
        row['ts'] = 0
        storage.set_app_state(_DISCOVERY_STATE, row)
    except Exception:
        pass


def refresh_gemma_models(api_key: str) -> list:
    """Read the key's model list (one unmetered GET — it is not a generation
    request) and keep the Gemma models that can generate and are at least
    GEMMA_MIN_BILLIONS, largest first. Records the attempt either way, so a
    failure retries in an hour rather than on every call."""
    import json
    import urllib.request
    from services import storage
    models, token = [], ''
    try:
        for _ in range(10):
            url = ('https://generativelanguage.googleapis.com/v1beta/models?pageSize=200'
                   + (f'&pageToken={token}' if token else ''))
            req = urllib.request.Request(url, headers={'x-goog-api-key': api_key})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.load(resp)
            for m in data.get('models', []):
                mid = str(m.get('name', '')).split('/', 1)[-1]
                if (mid.startswith('gemma') and 'generateContent' in (m.get('supportedGenerationMethods') or [])
                        and _gemma_size(mid) >= GEMMA_MIN_BILLIONS):
                    models.append(mid)
            token = data.get('nextPageToken')
            if not token:
                break
    except Exception as e:
        logger.warning(f"[model-pools] Gemma model discovery failed ({str(e)[:120]}) — keeping the current list")
        row = dict(_discovery_row())
        row['ts'] = time.time() - _DISCOVERY_FRESH + _DISCOVERY_RETRY if row.get('models') else time.time()
        storage.set_app_state(_DISCOVERY_STATE, row)
        return list(row.get('models') or [])
    models = sorted(dict.fromkeys(models), key=lambda m: (-_gemma_size(m), m))
    storage.set_app_state(_DISCOVERY_STATE, {'ts': time.time(), 'models': models})
    logger.info(f"[model-pools] Gemma models available to this key: {', '.join(models) or 'none'}")
    return models


def _maybe_discover(tier: str, api_key: str, settings: dict, wait: bool = False):
    """Refresh the Gemma list when a Gemma-using call is about to run and the
    list is stale — on a background thread, so no call ever waits on it (this
    call uses the list as it stands). One look at a time."""
    if not api_key or 'gemma' not in TIER_CHAINS.get(tier, []):
        return
    if provider(settings) != 'gemini':
        return          # discovery reads the Gemini key's model list; another provider has no Gemma
    if ((settings or {}).get('model_pool_gemma') or '').strip():
        return
    if not gemma_discovery_due() or not _discovery_lock.acquire(blocking=False):
        return

    def look():
        try:
            if gemma_discovery_due():
                refresh_gemma_models(api_key)
        finally:
            _discovery_lock.release()
    t = threading.Thread(target=look, name='gemma-discovery', daemon=True)
    t.start()
    if wait:
        t.join()


def api_key_for(model_id: str, pool_name: str, settings: dict) -> str:
    """The key an id bills. Gemini: the pro and cu pools bill the paid key,
    every other pool the free key. This helper is the ONLY reader of
    llm_gemini_paid_api_key — the source-pin test in test_missions_pins.py
    keeps all paid-key reads here. Claude and OpenAI have one key each; the
    pro/cu distinction is a Gemini free-tier artefact. A missing key returns
    '' so a caller fails loudly instead of quietly billing another key."""
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
    its old signature for the callers that only know a pool name."""
    models = _pool(pool_name, settings)
    return api_key_for(models[0] if models else '', pool_name, settings)


def credentials(tier: str, settings: dict = None):
    """(model_id, api_key) for a tier under the selected provider, or
    ('', '') when that provider has no key. Replaces the 'no Gemini key'
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
    if provider(settings) == 'ollama':
        return True
    return bool(credentials('interactive', settings)[1])


def is_lite(model_id: str, settings: dict) -> bool:
    """The model is in the selected provider's lite pool (the voice path)."""
    return model_id in _pool('lite', settings)


def _next_midnight_pacific() -> float:
    """Free-tier daily quotas reset at midnight Pacific."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Los_Angeles")
    except Exception:
        tz = datetime.timezone(datetime.timedelta(hours=-8))
    now = datetime.datetime.now(tz)
    tomorrow = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0,
                                                          second=30, microsecond=0)
    return tomorrow.timestamp()


def note_failure(model: str, err_str: str, paid: bool = False):
    """Record a per-model failure so subsequent calls route around it."""
    err = str(err_str)
    low = err.lower()
    if "429" in err:
        if split_model(model)[0] == 'gemini' and ("perday" in low or "per day" in low or "daily" in low):
            until = _next_midnight_pacific()
            logger.warning(f"[model-pools] {model} daily quota exhausted — "
                           f"cooling down until midnight Pacific")
        else:
            until = time.time() + 120
            logger.info(f"[model-pools] {model} rate limited (per-minute) — 120s cooldown")
    elif "404" in err or "not_found" in low or "not found" in low:
        until = time.time() + 6 * 3600
        if is_gemma(model):
            mark_gemma_discovery_stale()
        logger.error(f"[model-pools] {model} looks unknown to the API (404) — cooling "
                     f"6h. If this persists, fix the model id via the model_pool_* "
                     f"settings keys. Error: {err[:200]}")
    elif re.search(r"\b(?:500|502|503|504)\b", err) or 'timed out' in low or 'timeout' in low:
        until = time.time() + 120
        logger.info(f"[model-pools] {model} server unavailable - 120s cooldown")
    else:
        return  # Parse and other errors are not a model-availability signal.
    with _lock:
        key = (model, 'paid') if paid else model
        _cooldowns[key] = max(until, _cooldowns.get(key, 0))


def reset_cooldowns():
    """Test hook."""
    with _lock:
        _cooldowns.clear()


def is_gemma(model: str) -> bool:
    return model.startswith("gemma")


def models_for(tier: str, settings: dict = None, paid: bool = False) -> list:
    """Ordered candidate models for a tier, skipping cooled-down ones.
    If everything is cooling down, returns the full chain ordered by soonest
    cooldown expiry — the caller must always have something to try."""
    if settings is None:
        from services.storage import get_settings
        settings = get_settings()
    from services.app_voice import current as phone_voice
    if phone_voice.get() is not None:
        # The provider's lite pool; for Gemini, flash-lite only, as before.
        chain = list(dict.fromkeys(m for m in _pool('lite', settings)
                                   if split_model(m)[0] != 'gemini' or 'flash-lite' in m))
    else:
        chain = []
        for pool_name in TIER_CHAINS[tier]:
            for m in _pool(pool_name, settings):
                if m not in chain:
                    chain.append(m)
    now = time.time()
    def cooldown(model):
        return _cooldowns.get((model, 'paid') if paid else model, 0)
    with _lock:
        ready = [m for m in chain if cooldown(m) <= now]
        if ready:
            return ready
        return sorted(chain, key=cooldown)


def with_paid_fallback(tier, api_key, settings, background, call_chain):
    """Run a caller's chain, switching keys only for eligible foreground work.

    call_chain(key, paid) retains the caller's request and time limits and
    reserves each paid request with paid_fallback.count_call.
    """
    if background or tier not in ('interactive', 'vision', 'heavy'):
        return call_chain(api_key, False)
    if settings is None:
        from services.storage import get_settings
        settings = get_settings()
    first = models_for(tier, settings)
    if first and split_model(first[0])[0] != 'gemini':
        return call_chain(api_key, False)   # a paid provider has nothing to fall over to (spec §3)
    if settings.get('llm_paid_fallback_mode', 'ask') == 'off' or not api_key_for_pool('pro', settings):
        return call_chain(api_key, False)
    from services import paid_fallback
    st = paid_fallback.status(settings)
    paid = st['active']
    res = call_chain(api_key_for_pool('pro', settings) if paid else api_key, paid)
    if (not paid and isinstance(res, dict) and res.get('error') and res.get('transient')
            and not res.get('deferred') and 'time budget' not in str(res['error']).lower()):
        paid_fallback.note_throttle(settings)
        if paid_fallback.status(settings)['active']:
            res = call_chain(api_key_for_pool('pro', settings), True)
    st = paid_fallback.status(settings)
    if (isinstance(res, dict) and res.get('error') and st['configured']
            and st['used_today'] >= st['cap']):
        res['error'] = 'Paid fallback daily cap reached; ' + str(res['error'])
    return res


def resolve_model(tier: str, settings: dict = None) -> str:
    """First available model for a tier — for call sites that manage their own
    request/retry code and only need a model id."""
    return models_for(tier, settings)[0]


def call_pool_json(tier: str, api_key: str, system_prompt: str, user_prompt: str,
                   temperature: float = 0.1, timeout_s: int = 60,
                   gemma_timeout_s: int = None, max_models: int = 4,
                   settings: dict = None, images: list = None,
                   background: bool = None, workflow: str = None,
                   strict_json: bool = False, max_output_tokens: int = None,
                   attempts: list = None, total_timeout_s: float = None, thinking_level: str = None, response_schema: dict = None) -> dict:
    """JSON call with one HTTP attempt per candidate and persistent admission.

    Background work tries one candidate, then defers; foreground work may try
    up to max_models candidates. Success includes '_model'; failures return
    'error', with 'deferred'/'retry_at' when admission blocks background work.
    Ollama callers keep their own single-model path. An optional monotonic
    time budget caps each attempt's timeout to the remaining budget and stops
    launching candidates when it expires; existing callers remain unchanged.

    `attempts`, when a list is passed, collects the id of every model this
    call actually sends a PROVIDER REQUEST to, in order — so a caller can
    report what a stage really cost rather than guessing from `max_models`
    (the house photo pipeline writes it into its own notes). Nothing else
    changes; an admission deferral, which sends nothing, is not recorded.
    """
    from services import llm_budget
    background = tier in ('background', 'mind') if background is None else background
    workflow = workflow or tier
    try:
        _maybe_discover(tier, api_key, settings)
    except Exception as e:
        logger.warning(f"[model-pools] Gemma discovery skipped: {e}")
    if not background:
        return _call_chain(tier, api_key, system_prompt, user_prompt, temperature, timeout_s,
                           gemma_timeout_s, max_models, settings, images, background, workflow,
                           strict_json, max_output_tokens, attempts, total_timeout_s,
                           thinking_level, response_schema)
    # Background: the workflow pause is held until the whole call has failed,
    # so a fall-through to a sibling Gemma model is not blocked by the pause
    # its own first attempt would otherwise have written.
    with llm_budget.hold_workflow_pauses() as held:
        res = _call_chain(tier, api_key, system_prompt, user_prompt, temperature, timeout_s,
                          gemma_timeout_s, max_models, settings, images, background, workflow,
                          strict_json, max_output_tokens, attempts, total_timeout_s,
                          thinking_level, response_schema)
    if isinstance(res, dict) and res.get('error'):
        llm_budget.apply_held_pauses(held)   # no-op when nothing failed on the wire
    return res


def _call_chain(tier, api_key, system_prompt, user_prompt, temperature, timeout_s,
                gemma_timeout_s, max_models, settings, images, background, workflow,
                strict_json, max_output_tokens, attempts, total_timeout_s,
                thinking_level, response_schema):
    if settings is None and not background and tier in ('interactive', 'vision', 'heavy'):
        from services.storage import get_settings
        settings = get_settings()
    deadline = None if total_timeout_s is None else time.monotonic() + total_timeout_s
    return with_paid_fallback(tier, api_key, settings, background,
        lambda key, paid: _call_candidates(
            tier, key, system_prompt, user_prompt, temperature, timeout_s,
            gemma_timeout_s, max_models, settings, images, background, workflow,
            strict_json, max_output_tokens, attempts, deadline,
            thinking_level, response_schema, paid))


def _call_candidates(tier, api_key, system_prompt, user_prompt, temperature, timeout_s,
                     gemma_timeout_s, max_models, settings, images, background, workflow,
                     strict_json, max_output_tokens, attempts, deadline,
                     thinking_level, response_schema, paid):
    from services import llm as _llm
    from services import llm_budget
    last_err = "no models available"
    transient = False
    launched = 0
    deferred_until = None
    # Background work makes one attempt — except that a SERVER failure
    # (5xx/timeout) on a Gemma model may try the sibling Gemma model once.
    # Google's Gemma endpoints 500 often, and one sick model used to stall a
    # whole workflow for hours while its twin was healthy. Never past Gemma:
    # the Lite pool's daily allowance is shared with interactive chat.
    bg_limit = 1
    for model in models_for(tier, settings, paid=paid):
        if launched >= (bg_limit if background else max_models):
            break
        if background and launched and not is_gemma(model):
            break
        t = gemma_timeout_s if (gemma_timeout_s and is_gemma(model)) else timeout_s
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {"error": "Model pool time budget exhausted; last error: " + last_err,
                        "transient": True}
            t = min(t, remaining)
        if paid:
            from services import paid_fallback
            if not paid_fallback.count_call(settings):
                return {'error': 'Paid fallback inactive or daily cap reached', 'transient': True}
        try:
            with llm_budget.request_scope(workflow, background), llm_budget.record_attempts(attempts):
                res = _llm.call_model(model, api_key, system_prompt,
                                      user_prompt, temperature=temperature, timeout_s=t,
                                      images=images, transient_retries=0,
                                      strict_json=strict_json,
                                      **({"response_schema": response_schema} if response_schema is not None else {}),
                                      max_output_tokens=max_output_tokens,
                                      **({"thinking_level": thinking_level} if thinking_level is not None else {}))
        except llm_budget.Deferred as e:
            # Only the workflow's own backoff stops a background call. A
            # penalised or used-up MODEL is a reason to try the next one,
            # not to stall the whole workflow until that model recovers.
            if background and getattr(e, 'scope', 'workflow') == 'workflow':
                return {'error': str(e), 'deferred': True, 'retry_at': e.retry_at}
            last_err = str(e)
            deferred_until = min(deferred_until or e.retry_at, e.retry_at)
            transient = True
            continue
        except Exception as e:
            launched += 1
            last_err = str(e)
            note_failure(model, last_err, paid=paid)
            transient = any(c in last_err for c in ("429", "500", "502", "503", "504",
                                                    "timed out", "timeout"))
            if background and transient and is_gemma(model):
                bg_limit = 2
            logger.warning(f"[model-pools] {model} failed ({last_err[:160]}) — "
                           + ('trying next' if not background
                              else 'trying the other Gemma model' if launched < bg_limit
                              else 'deferring background work'))
            continue
        launched += 1
        if isinstance(res, dict) and res.get("error") and "429" in str(res["error"]):
            last_err = str(res["error"])
            note_failure(model, last_err, paid=paid)
            transient = True
            logger.warning(f"[model-pools] {model} rate limited — trying next")
            continue
        if isinstance(res, dict):
            res["_model"] = model
        return res
    return {"error": last_err, "transient": transient,
            **({"deferred": True, "retry_at": deferred_until} if deferred_until and launched == 0 else {})}


def pooled_or_direct(provider_name: str, url: str, api_key: str, model: str, tier: str,
                     system_prompt: str, user_prompt: str, temperature: float = 0.1,
                     timeout_s: int = 180, settings: dict = None) -> dict:
    """Drop-in for _call_llm_json at provider-branched call sites: Ollama keeps
    its one configured model; every other provider goes through the tier's
    pool chain on the selected table (retries, cooldowns, fallback), the
    passed model ignored."""
    if provider_name != 'ollama':
        return call_pool_json(tier, api_key, system_prompt, user_prompt,
                              temperature=temperature, timeout_s=timeout_s,
                              settings=settings)
    from services import llm as _llm
    return _llm._call_llm_json(provider_name, url, api_key, model, system_prompt,
                               user_prompt, temperature=temperature, timeout_s=timeout_s)

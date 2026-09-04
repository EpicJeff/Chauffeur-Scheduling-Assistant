"""Free-tier Gemini model pools with cooldown-aware rotation.

The Gemini free tier gives each MODEL its own daily request quota, so models
of similar ability are grouped into pools whose quotas combine (daily caps as
of 2026-08-30):

- lite:  gemini-3.5-flash-lite (500), gemini-3.1-flash-lite (500),
         gemini-2.5-flash-lite (20)  -> ~1,020/day, answers in seconds.
- flash: gemini-3.8/3.7/3.6/3.5/3.1/3/2.5-flash (20 each) -> ~140/day, highest quality.
- gemma: gemma-4-31b-it (14,400), gemma-4-26b-it (14,400) -> ~28,800/day, but
         44-180s per call measured on the free API (2026-07-30).
- pro:   gemini-3.1-pro, gemini-2.5-pro (paid key only, mission tier exclusive).

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

Pools are overridable without a code change via comma-separated settings keys
model_pool_lite / model_pool_flash / model_pool_gemma.
"""
import logging
import threading
import time
import datetime

logger = logging.getLogger(__name__)

DEFAULT_POOLS = {
    'lite': ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite"],
    'flash': ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash",
              "gemini-3.1-flash", "gemini-3-flash", "gemini-2.5-flash"],
    'gemma': ["gemma-4-31b-it", "gemma-4-26b-it"],
    'pro': ["gemini-3.1-pro", "gemini-2.5-pro"],
}

TIER_CHAINS = {
    'interactive': ['lite', 'gemma'],
    'background': ['gemma', 'lite'],
    'heavy': ['flash', 'lite', 'gemma'],
    # Image-input calls (intake vision capture). Gemma is text-only so it is
    # excluded; flash first because flyers/screenshots are the hard case and
    # volume is family-scale (dozens/week vs the ~120/day flash quota).
    'vision': ['flash', 'lite'],
    # Missions (services/missions.py). 'mission' is the ONLY tier that touches
    # the pro pool and it never falls back to a free pool — a mission pauses
    # rather than silently degrading. 'mission_flash' exists for benchmarking
    # the same mission on the free flash chain (pure flash: no lite/gemma, so
    # the comparison measures the model, not the fallback).
    'mission': ['pro'],
    'mission_flash': ['flash'],
}

# model -> unix timestamp until which it is skipped
_cooldowns: dict = {}
_lock = threading.Lock()


def _pool(name: str, settings: dict) -> list:
    raw = (settings or {}).get(f'model_pool_{name}') or ''
    if raw.strip():
        return [m.strip() for m in raw.split(',') if m.strip()]
    return list(DEFAULT_POOLS[name])


def api_key_for_pool(pool_name: str, settings: dict) -> str:
    """The pro pool bills the paid key; every other pool stays on the free
    key. This helper is the ONLY reader of llm_gemini_paid_api_key — the
    source-pin test in test_missions_pins.py is the fence that keeps regular
    traffic from ever spending paid money. Missing paid key returns '' so a
    caller fails loudly instead of quietly billing the free key."""
    s = settings or {}
    if pool_name == 'pro':
        return s.get('llm_gemini_paid_api_key', '') or ''
    return s.get('llm_gemini_api_key', '') or ''


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


def note_failure(model: str, err_str: str):
    """Record a per-model failure so subsequent calls route around it."""
    err = str(err_str)
    low = err.lower()
    if "429" in err:
        if "perday" in low or "per day" in low or "daily" in low:
            until = _next_midnight_pacific()
            logger.warning(f"[model-pools] {model} daily quota exhausted — "
                           f"cooling down until midnight Pacific")
        else:
            until = time.time() + 120
            logger.info(f"[model-pools] {model} rate limited (per-minute) — 120s cooldown")
    elif "404" in err or "not_found" in low or "not found" in low:
        until = time.time() + 6 * 3600
        logger.error(f"[model-pools] {model} looks unknown to the API (404) — cooling "
                     f"6h. If this persists, fix the model id via the model_pool_* "
                     f"settings keys. Error: {err[:200]}")
    else:
        return  # 5xx/parse errors: the caller already moves on; no quota signal
    with _lock:
        _cooldowns[model] = until


def reset_cooldowns():
    """Test hook."""
    with _lock:
        _cooldowns.clear()


def is_gemma(model: str) -> bool:
    return model.startswith("gemma")


def models_for(tier: str, settings: dict = None) -> list:
    """Ordered candidate models for a tier, skipping cooled-down ones.
    If everything is cooling down, returns the full chain ordered by soonest
    cooldown expiry — the caller must always have something to try."""
    if settings is None:
        from services.storage import get_settings
        settings = get_settings()
    chain = []
    for pool_name in TIER_CHAINS[tier]:
        for m in _pool(pool_name, settings):
            if m not in chain:
                chain.append(m)
    now = time.time()
    with _lock:
        ready = [m for m in chain if _cooldowns.get(m, 0) <= now]
        if ready:
            return ready
        return sorted(chain, key=lambda m: _cooldowns.get(m, 0))


def resolve_model(tier: str, settings: dict = None) -> str:
    """First available model for a tier — for call sites that manage their own
    request/retry code and only need a model id."""
    return models_for(tier, settings)[0]


def call_pool_json(tier: str, api_key: str, system_prompt: str, user_prompt: str,
                   temperature: float = 0.1, timeout_s: int = 60,
                   gemma_timeout_s: int = None, max_models: int = 4,
                   settings: dict = None, images: list = None) -> dict:
    """JSON LLM call that walks the tier's pool chain: 429/5xx/parse failures
    advance to the next model (marking quota cooldowns), success returns the
    parsed dict with '_model' set. Gemini only — ollama callers keep their own
    single-model path. Returns {'error': ..., 'transient': bool} when
    max_models candidates all failed."""
    from services import llm as _llm
    last_err = "no models available"
    transient = False
    for model in models_for(tier, settings)[:max_models]:
        t = gemma_timeout_s if (gemma_timeout_s and is_gemma(model)) else timeout_s
        try:
            res = _llm._call_llm_json('gemini', '', api_key, model, system_prompt,
                                      user_prompt, temperature=temperature, timeout_s=t,
                                      images=images)
        except Exception as e:
            last_err = str(e)
            note_failure(model, last_err)
            transient = any(c in last_err for c in ("429", "500", "502", "503", "504",
                                                    "timed out", "timeout"))
            logger.warning(f"[model-pools] {model} failed ({last_err[:160]}) — trying next")
            continue
        if isinstance(res, dict) and res.get("error") and "429" in str(res["error"]):
            last_err = str(res["error"])
            note_failure(model, last_err)
            transient = True
            logger.warning(f"[model-pools] {model} rate limited — trying next")
            continue
        if isinstance(res, dict):
            res["_model"] = model
        return res
    return {"error": last_err, "transient": transient}


def pooled_or_direct(provider: str, url: str, api_key: str, model: str, tier: str,
                     system_prompt: str, user_prompt: str, temperature: float = 0.1,
                     timeout_s: int = 180, settings: dict = None) -> dict:
    """Drop-in for _call_llm_json at provider-branched call sites: gemini goes
    through the tier's pool chain (ignoring the passed model), ollama keeps its
    single configured model."""
    if provider == 'gemini':
        return call_pool_json(tier, api_key, system_prompt, user_prompt,
                              temperature=temperature, timeout_s=timeout_s,
                              settings=settings)
    from services import llm as _llm
    return _llm._call_llm_json(provider, url, api_key, model, system_prompt,
                               user_prompt, temperature=temperature, timeout_s=timeout_s)

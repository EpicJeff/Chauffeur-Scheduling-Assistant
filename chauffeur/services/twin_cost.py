"""Persistent per-request costs and parent-acknowledged twin checkpoints.

Twin callers must require_clear() before each call, pass max_models=1 and a
usage list to call_pool_json, then record that list even when the call fails.
Recording never rejects the request that crossed a checkpoint.
"""
from copy import deepcopy
from datetime import datetime, timezone
import math

from services import storage

CHECKPOINTS = (10.0, 20.0, 30.0, 40.0)
HARD_STOP = 50.0
ROUND_CAP = 5
UNKNOWN_OUTPUT_TOKENS = 65536
IMAGE_TOKENS = {'draft': 5000, 'draft_level': 5000, 'draft_rooms': 5000, 'roof_check': 5000}

# USD per million input/output tokens, checked 2026-11-06.
PRICES: dict[str, tuple[float, float]] = {
    # CONSERVATIVE PLACEHOLDERS: the Google pricing page could not be fetched
    # on 2026-11-06 (unsupported Markdown/redirect). Verify before live spend:
    # https://ai.google.dev/gemini-api/docs/pricing
    'gemini-4-argon': (10.0, 60.0),
    'gemini-3.1-pro-preview': (10.0, 60.0),
    'gemini-3.8-flash': (10.0, 60.0),
    # Published standard base rates, 2026-11-06:
    # https://platform.claude.com/docs/en/about-claude/pricing
    'anthropic:claude-opus-5-5': (4.0, 20.0),
    'anthropic:claude-sonnet-5-5': (2.0, 10.0),
    'anthropic:claude-haiku-5-5': (0.1, 0.5),
    # Published standard short-context rates, 2026-11-06:
    # https://developers.openai.com/api/docs/pricing
    'openai:gpt-6.1-sol': (2.0, 10.0),
    'openai:gpt-6-luna': (0.1, 0.5),
}


class CheckpointReached(RuntimeError):
    def __init__(self, checkpoint: float, total: float):
        self.checkpoint = checkpoint
        self.total = total
        message = (f'Twin cost ${total:.2f} reached the ${HARD_STOP:g} hard stop; no more requests are allowed.'
                   if checkpoint == HARD_STOP else
                   f'Twin cost ${total:.2f} reached the ${checkpoint:g} checkpoint; '
                   'a parent must acknowledge before another request.')
        super().__init__(message)


def _highest_rates():
    return max(p[0] for p in PRICES.values()), max(p[1] for p in PRICES.values())


def price(model: str, input_tokens: int, output_tokens: int) -> tuple[float, bool]:
    rates = PRICES.get(model)
    priced = rates is not None
    inp, out = rates if priced else _highest_rates()
    return (input_tokens * inp + output_tokens * out) / 1_000_000, priced


def estimate(kind: str, images: int) -> float:
    """Conservative cost shown before a person requests a setup read."""
    from services import model_pools, twin_reads
    if not isinstance(kind, str) or kind not in twin_reads.MAX_OUTPUT:
        raise ValueError('Choose a supported drawing or photo read.')
    if type(images) is not int or images < 0:
        raise ValueError('Choose a nonnegative number of images.')
    settings = storage.get_settings()
    pool = model_pools._pool(model_pools.TIER_CHAINS['twin'][0], settings)
    rates = PRICES.get(pool[0]) if pool else None
    inp, out = rates if rates is not None else _highest_rates()
    usd = ((1500 + IMAGE_TOKENS.get(kind, 1600) * images) * inp
           + twin_reads.MAX_OUTPUT[kind] * out) / 1_000_000
    return math.ceil(usd * 100) / 100


def _state():
    row = deepcopy(storage.get_settings().get('house_twin_cost') or {})
    row.setdefault('entries', [])
    row.setdefault('acknowledged', [])
    row.setdefault('archived', [])
    row.setdefault('resets', [])
    return row


def reset(by: str) -> dict:
    """Archive live spend only at a person's explicit request."""
    if not isinstance(by, str) or not by.strip():
        raise ValueError('A spend reset needs the person who requested it.')
    with storage.db_lock:
        row = _state()
        record = {'at': datetime.now(timezone.utc).isoformat(), 'by': by, 'total': _total(row)}
        row['archived'].extend(row['entries'])
        row['entries'] = []
        row['acknowledged'] = []
        row['resets'].append(record)
        storage.patch_settings({'house_twin_cost': row})
    return deepcopy(record)


def resets() -> list[dict]:
    return _state()['resets']


def entries() -> list[dict]:
    return _state()['entries']


def _total(row):
    return math.fsum(e['usd'] for e in row['entries'])


def total() -> float:
    return _total(_state())


def _blocking(row, spent):
    if spent >= HARD_STOP:
        return HARD_STOP
    return next((c for c in CHECKPOINTS if c <= spent and c not in row['acknowledged']), None)


def blocking_checkpoint() -> float | None:
    row = _state()
    return _blocking(row, _total(row))


def require_clear() -> None:
    row = _state()
    spent = _total(row)
    checkpoint = _blocking(row, spent)
    if checkpoint is not None:
        raise CheckpointReached(checkpoint, spent)


def record(stage: str, usage: list[dict], run: str | None = None) -> list[dict]:
    added = []
    for request in usage:
        inp, out = request.get('input_tokens'), request.get('output_tokens')
        refused = isinstance(request.get('http_status'), int) and request['http_status'] >= 400
        estimated = inp is None or out is None
        if refused:
            inp, out, usd, priced = inp or 0, out or 0, 0, request['model'] in PRICES
        else:
            if estimated:
                if inp is None:
                    inp = 1600 * (request.get('images') or 0) + math.ceil((request.get('prompt_chars') or 0) / 4)
                if out is None:
                    out = request.get('max_output_tokens') or UNKNOWN_OUTPUT_TOKENS
            usd, priced = price(request['model'], inp, out)
        added.append({'stage': stage, 'model': request['model'],
                      'input_tokens': inp, 'output_tokens': out, 'usd': usd,
                      'priced': priced, 'basis': 'refused' if refused else 'estimated' if estimated else 'reported',
                      'run': run, 'at': datetime.now(timezone.utc).isoformat()})
    if added:
        # Serialize read/merge/write with the same lock used by patch_settings.
        with storage.db_lock:
            row = _state()
            row['entries'].extend(added)
            storage.patch_settings({'house_twin_cost': row})
    return added


def acknowledge(checkpoint: float) -> None:
    if checkpoint not in CHECKPOINTS:
        raise ValueError('Only the $10, $20, $30 and $40 checkpoints can be acknowledged; '
                         'the $50 hard stop cannot be acknowledged.')
    with storage.db_lock:
        row = _state()
        if checkpoint > _total(row):
            raise ValueError('Checkpoint has not been reached yet.')
        if checkpoint not in row['acknowledged']:
            row['acknowledged'].append(checkpoint)
            storage.patch_settings({'house_twin_cost': row})

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


def _state():
    row = deepcopy(storage.get_settings().get('house_twin_cost') or {})
    row.setdefault('entries', [])
    row.setdefault('acknowledged', [])
    return row


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
        estimated = inp is None or out is None
        if estimated:
            inp = 1600 * (request.get('images') or 0) + math.ceil((request.get('prompt_chars') or 0) / 4)
            out = request.get('max_output_tokens') or UNKNOWN_OUTPUT_TOKENS
            hi_in, hi_out = _highest_rates()
            usd, priced = (inp * hi_in + out * hi_out) / 1_000_000, False
        else:
            usd, priced = price(request['model'], inp, out)
        added.append({'stage': stage, 'model': request['model'],
                      'input_tokens': inp, 'output_tokens': out, 'usd': usd,
                      'priced': priced, 'basis': 'estimated' if estimated else 'reported',
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

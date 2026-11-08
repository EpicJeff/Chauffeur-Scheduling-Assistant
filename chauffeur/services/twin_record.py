"""Read-only diagnostics for the latest house build chain; never run a read."""
import json
from pathlib import Path
import re
from urllib.parse import quote

from services import twin_build, twin_cost, twin_store


def _root(build_id):
    if not isinstance(build_id, str) or not re.fullmatch(r'[a-f0-9]{32}', build_id):
        raise ValueError('The saved build record needs checking.')
    return Path(twin_store.DATA_DIR) / 'builds' / build_id


def _redact(value):
    """Keep credentials out even if a cached reply or error included one."""
    if isinstance(value, dict):
        return {_redact(k): _redact(v) for k, v in value.items()
                if not re.search(r'api[_ -]?key|password|secret|authorization|access_token|refresh_token', k, re.I)}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if isinstance(value, str):
        return re.sub(r'api_key|\bsk-[\w-]+|\bAIza[\w-]+', '[redacted]', value, flags=re.I)
    return value


def record():
    # Build publication and Start over use this same lock. All exported data
    # belongs to one generation, including caches written during a live build.
    with twin_store.LIFECYCLE:
        builds = []
        bid = twin_build.latest()
        seen = set()
        while bid:
            if bid in seen:
                raise ValueError('The saved build chain needs checking.')
            seen.add(bid)
            saved = json.loads((_root(bid) / 'state.json').read_text(encoding='utf-8'))
            if saved['generation'] != twin_store.generation():
                raise twin_store.StaleGeneration('The house was started over.')
            previous = saved.get('previous')
            if not previous:
                break
            bid = previous

        # latest() can name the tail or a predecessor saved at the handoff.
        # Walk back to the root above, then forward in the chain's own order.
        seen = set()
        while bid:
            if bid in seen:
                raise ValueError('The saved build chain needs checking.')
            seen.add(bid)
            build = twin_build.status(bid)
            for step in build['steps']:
                path = _root(bid) / 'steps' / (quote(step['id'], safe='') + '.json')
                try:
                    step['answer'] = json.loads(path.read_text(encoding='utf-8'))
                except FileNotFoundError:
                    step['answer'] = None  # Pending steps have no cached answer.
            builds.append(build)
            bid = build.get('next')

        # Select domain data explicitly: never include settings or build inputs.
        return _redact({'plan': twin_store.current(), 'builds': builds,
                        'place': twin_store.place(), 'registrations': twin_store.registrations(),
                        'ledger': twin_cost.entries()})

"""Asks — the ledger of who was asked what, by which channel, and what came
back. Spec §2. Filled in by the asks task; the view needs asks_for first."""
from services import storage


def asks_for(kind: str, sid: str, row: dict = None) -> list:
    rows = storage.get_asks(situation_kind=kind, situation_id=sid)
    if kind == 'finding' and row and row.get('subject_type') == 'event':
        ids = {a['id'] for a in rows}
        rows += [a for a in storage.get_asks(event_id=row.get('subject_id')) if a['id'] not in ids]
    return rows

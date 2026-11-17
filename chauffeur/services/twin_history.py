"""Bounded editor steps and durable session-start house snapshots. No model reads."""
from datetime import datetime

from services import storage, twin_house_saves as saves, twin_store as store


def _mark_cleaned(row):
    """Write only when the marker or legacy change records need it, so opening the editor stays a read."""
    stored = storage.get_settings().get('house_twin') or {}
    if stored.get('history_cleaned') is True and not row['fixes']:
        return
    row['history_cleaned'] = True
    store._save_with_fixes(row)


def start_session(member):
    with store.LIFECYCLE, store._LOCK:
        row = store._state()
        model = store.current_model()
        stamp = datetime.now().astimezone()
        saved = None
        if model is None:
            _mark_cleaned(row)
            return {'cleaned': 0, 'saved': None}
        if not row['history_cleaned'] and len(row['rounds']) > store.HISTORY_KEEP:
            # The durable named copy must exist before any history is removed.
            saved = saves.save_current(f'Before cleanup {stamp:%Y-%m-%d}', member)
            # Saving can migrate the place registry; retain that published state.
            row = store._state()
            row['history_cleaned'] = True
            dropped = store._prune_history(row)
            store._save_with_fixes(row)
            store._delete_round_files(dropped)
            return {'cleaned': len(dropped), 'saved': saved}

        # Persist the small-house marker and migrate legacy change records too.
        _mark_cleaned(row)
        newest = saves.list_saves()
        if not newest or saves.download(newest[0]['id'])['model'] != model:
            saved = saves.save_current(f'Auto-save {stamp:%Y-%m-%d %H:%M:%S}', member, auto=True)
        automatic = [s for s in saves.list_saves() if s.get('auto') is True]
        for old in automatic[10:]:
            saves.delete(old['id'])
        return {'cleaned': 0, 'saved': saved}

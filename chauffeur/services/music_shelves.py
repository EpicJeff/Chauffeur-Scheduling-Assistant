"""Music Assistant's own shelves, and playlists as a write surface.

Both exist only on the direct MA path — the HA bridge has no
recommendations, no recently-played, and no playlist verbs at all. Every
function here degrades to empty/absent rather than erroring: the shelves are
garnish on the wall panel's house view, and a missing garnish must never
break the card that carries it.

TYPING IS THE WORST PART of a wall music card, and these shelves are the
alternative: what the house has been playing and what MA thinks the house
would like, one tap each. They draw ONLY in house mode (nobody selected) —
a picked member sees their own shelf (slice 4), and mixing MA's house-wide
recommendations into a person's shelf would be the merging that slice
explicitly rejected.

PLAYLISTS are family-shaped writes: a shared "Road trip" list the kids add
to from their phones. MA's editable playlists (`is_editable`) are the
targets; `add_playlist_tracks` wants the LIBRARY item id (`db_playlist_id`),
which is why rows carry `item_id` and not just a uri.
"""

from services.music_search import _row_from_ma


def _rows(items, ma_base):
    return [_row_from_ma(i, ma_base) for i in items if isinstance(i, dict)]


def shelves(limit: int = 8) -> dict:
    """{available, recently_played: [...], recommendations: [{name, items}]}.

    The recommendations command answers with folders-of-items whose exact
    shape has moved between MA versions — parsed defensively: an entry with
    an `items` list is a folder, a bare media item becomes a folder of its
    own under a generic name, anything else is dropped.
    """
    from services import ma_api
    if not ma_api.available():
        return {'available': False, 'recently_played': [], 'recommendations': []}
    ma_base = ma_api.resolve_base()
    recent = ma_api.command('music/recently_played_items', limit=limit)
    recs_raw = ma_api.command('music/recommendations')
    recs = []
    for entry in (recs_raw if isinstance(recs_raw, list) else []):
        if not isinstance(entry, dict):
            continue
        if isinstance(entry.get('items'), list):
            rows = _rows(entry['items'], ma_base)[:limit]
            if rows:
                recs.append({'name': entry.get('name') or 'For the house',
                             'items': rows})
        elif entry.get('uri'):
            if not recs or recs[-1].get('name') != 'For the house':
                recs.append({'name': 'For the house', 'items': []})
            if len(recs[-1]['items']) < limit:
                recs[-1]['items'].append(_row_from_ma(entry, ma_base))
    return {
        'available': True,
        'recently_played': _rows(recent if isinstance(recent, list) else [],
                                 ma_base)[:limit],
        'recommendations': recs[:3],
    }


def editable_playlists() -> list:
    """[{item_id, name}] — the playlists a track can be added to. Empty when
    MA is absent, which the surfaces read as "hide the verb"."""
    from services import ma_api
    if not ma_api.available():
        return []
    items = ma_api.command('music/playlists/library_items', limit=100)
    out = []
    for p in (items if isinstance(items, list) else []):
        if isinstance(p, dict) and p.get('is_editable'):
            out.append({'item_id': p.get('item_id'), 'name': p.get('name')})
    return out


def add_to_playlist(playlist_id, uri) -> tuple:
    """(ok, detail)."""
    from services import ma_api
    if not ma_api.available():
        return False, ('Playlists need the Music Assistant token '
                       '(Config → Integrations).')
    result = ma_api.command('music/playlists/add_playlist_tracks',
                            db_playlist_id=playlist_id, uris=[uri])
    if result is None:
        return False, ma_api.health()['detail'] or 'Music Assistant refused.'
    return True, ''


def create_playlist(name, uri=None) -> tuple:
    """(ok, detail, playlist). Creates in MA's own library provider; when a
    uri rides along the new list starts with that track — the whole reason
    somebody makes a playlist from a row."""
    from services import ma_api
    if not ma_api.available():
        return False, ('Playlists need the Music Assistant token '
                       '(Config → Integrations).'), None
    created = ma_api.command('music/playlists/create_playlist', name=name)
    if not isinstance(created, dict):
        return False, ma_api.health()['detail'] or 'Music Assistant refused.', None
    playlist = {'item_id': created.get('item_id'), 'name': created.get('name')}
    if uri and playlist['item_id'] is not None:
        ok, detail = add_to_playlist(playlist['item_id'], uri)
        if not ok:
            return False, detail, playlist
    return True, '', playlist

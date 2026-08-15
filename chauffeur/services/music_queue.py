"""The queue as a thing you can SEE — and therefore fix.

"Add to queue" shipped in v2.239.0 fire-and-forget: you could enqueue three
things and never see what you queued, which makes the third ➕ an act of
faith. This module turns the queue into a list with rows that can be jumped
to, moved and removed.

Two paths, very different ceilings:

  * Music Assistant directly: `player_queues/get_active_queue` + `items`
    give the whole list with stable `queue_item_id`s, and `play_index` /
    `move_item` / `delete_item` / `clear` are the verbs. This is the real
    feature.
  * The HA bridge: `music_assistant.get_queue` answers with the CURRENT and
    NEXT item only, no ids. That is a two-row peek, drawn with the same
    shape and no edit verbs — the surfaces disable what the path cannot do
    (`can_edit: false`) rather than offering buttons that fail on press.

The MA player id comes off the HA entity itself: the integration stamps its
own player id into a `mass_player_id` attribute (the same attribute the
local-player lookup already matches on). No id, no MA path — an entity MA
never claimed has no MA queue to show.
"""

from services.music_search import _image_url


def _ma_player_id(entity_id):
    """The MA player id stamped on an HA entity, or None."""
    from services import ha_api
    state = ha_api.get_state(entity_id) or {}
    attrs = state.get('attributes') or {}
    pid = attrs.get('mass_player_id')
    if isinstance(pid, str) and pid:
        return pid
    return None


def _row_from_ma(item, index, current_index, ma_base):
    media = item.get('media_item') or {}
    artists = ', '.join(a.get('name') or '' for a in (media.get('artists') or []))
    album = (media.get('album') or {}).get('name') if media.get('album') else None
    subtitle = (f"{artists} · {album}" if artists and album
                else artists or album or '')
    return {
        'id': item.get('queue_item_id'),
        'index': index,
        'name': item.get('name') or media.get('name') or '',
        'subtitle': subtitle,
        'image': _image_url(media, ma_base) if media else None,
        'current': current_index is not None and index == current_index,
    }


def _ha_row(item, current):
    if not isinstance(item, dict):
        return None
    return {
        'id': None, 'index': None,
        'name': item.get('media_title') or item.get('name') or '',
        'subtitle': item.get('media_artist') or item.get('artist') or '',
        'image': item.get('media_image') or item.get('image') or None,
        'current': current,
    }


def get_queue(entity_id, limit=50):
    """{source, can_edit, queue_id, items: [...]} — or None when neither path
    can answer (the surface hides the queue rather than drawing an error)."""
    from services import ma_api
    pid = _ma_player_id(entity_id)
    if pid and ma_api.available():
        queue = ma_api.command('player_queues/get_active_queue', player_id=pid)
        if isinstance(queue, dict):
            qid = queue.get('queue_id') or pid
            current_index = queue.get('current_index')
            # Windowed around the playing item: the family cares about what
            # is NEXT, and a 500-song queue is not a wall document.
            offset = max(0, (current_index or 0))
            items = ma_api.command('player_queues/items', queue_id=qid,
                                   limit=limit, offset=offset)
            if isinstance(items, list):
                ma_base = ma_api.resolve_base()
                rows = [_row_from_ma(it, offset + i, current_index, ma_base)
                        for i, it in enumerate(items)]
                return {'source': 'ma', 'can_edit': True, 'queue_id': qid,
                        'total': queue.get('items') if isinstance(queue.get('items'), int) else None,
                        'items': rows}
    # HA fallback: the two-row peek.
    from services import ha_api
    result = ha_api.call_service('music_assistant', 'get_queue',
                                 {'entity_id': entity_id}, return_response=True)
    if result is None:
        return None
    data = result.get('service_response', result) or {}
    # The response is keyed by entity_id.
    q = data.get(entity_id) if isinstance(data.get(entity_id), dict) else data
    rows = []
    cur = _ha_row(q.get('current_item'), True)
    nxt = _ha_row(q.get('next_item'), False)
    if cur:
        rows.append(cur)
    if nxt:
        rows.append(nxt)
    return {'source': 'ha', 'can_edit': False, 'queue_id': None,
            'total': None, 'items': rows}


def command(entity_id, action, queue_item_id=None, index=None):
    """One queue edit. Returns (ok, detail). MA-only by nature — the HA
    bridge has no queue verbs at all."""
    from services import ma_api
    pid = _ma_player_id(entity_id)
    if not pid or not ma_api.available():
        return False, ('Editing the queue needs the Music Assistant token '
                       '(Config → Integrations).')
    queue = ma_api.command('player_queues/get_active_queue', player_id=pid)
    qid = (queue or {}).get('queue_id') or pid
    if action == 'clear':
        ok = ma_api.command('player_queues/clear', queue_id=qid) is not None
    elif action == 'play_index' and index is not None:
        ok = ma_api.command('player_queues/play_index', queue_id=qid,
                            index=index) is not None
    elif action in ('move_up', 'move_down') and queue_item_id:
        ok = ma_api.command('player_queues/move_item', queue_id=qid,
                            queue_item_id=queue_item_id,
                            pos_shift=-1 if action == 'move_up' else 1) is not None
    elif action == 'remove' and queue_item_id:
        ok = ma_api.command('player_queues/delete_item', queue_id=qid,
                            item_id_or_index=queue_item_id) is not None
    else:
        return False, f'Unknown queue action {action}'
    if not ok:
        return False, 'Music Assistant refused the queue change.'
    return True, ''

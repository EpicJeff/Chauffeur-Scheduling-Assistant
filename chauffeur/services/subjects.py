"""Resolve a thread or mission's optional subject to a Chauffeur record."""

import datetime
import difflib

from services import scope, storage


KINDS = ('trip', 'occasion', 'event', 'member', 'contact', 'thread', 'program', 'list')
FACETS = {
    'trip': ['flights', 'accommodations', 'dining', 'attractions'],
    'occasion': ['guests', 'menu', 'lists', 'errands'],
    'program': ['sessions'],
    'thread': ['history'],
    'event': [], 'member': [], 'contact': [], 'list': [],
}
PER_KIND, OVERALL, BUDGET = 5, 8, 1500
WRITE_ROLES = ('parent', 'adult')


def facets(kind):
    return list(FACETS.get(kind, []))


def _trip_rows():
    snapshot = {
        row.get('id'): row
        for row in (storage.get_cached_trips() or {}).get('trips') or []
    }
    rows = {}
    for metadata in storage.get_all_trip_metadata():
        event_id = metadata['event_id']
        cached = snapshot.get(event_id) or {}
        rows[event_id] = {
            **metadata,
            'id': event_id,
            'title': metadata.get('title') or cached.get('title') or 'Trip',
            'start': cached.get('start'),
            'end': cached.get('end'),
            'location': metadata.get('location') or cached.get('location'),
        }
    for event_id, cached in snapshot.items():
        rows.setdefault(event_id, {
            **cached,
            'id': event_id,
            'event_id': event_id,
            'title': cached.get('title') or 'Trip',
            'audience': 'household',
            'pois': [], 'accommodations': [], 'flights': [],
            '_calendar_only': True,
        })
    return list(rows.values())


def _rows(kind):
    if kind == 'trip':
        return _trip_rows()
    if kind == 'occasion':
        return storage.get_occasions(include_done=True)
    if kind == 'event':
        return list((storage.get_cached_schedule() or {}).get('events') or [])
    if kind == 'member':
        return [row for row in storage.get_all_members() if not row.get('system')]
    if kind == 'contact':
        return storage.get_assist_contacts()
    if kind == 'thread':
        return storage.get_threads(include_closed=True)
    if kind == 'program':
        return storage.get_programs(include_finished=True)
    if kind == 'list':
        return storage.get_shopping_lists()
    return []


def load(kind, sid):
    """Load a raw record; trips use the calendar event id as their subject id."""
    return next((row for row in _rows(kind) if str(row.get('id')) == str(sid)), None)


def title_of(kind, row):
    if kind == 'contact':
        return row.get('relation_label') or row.get('name') or ''
    return row.get('title') or row.get('name') or ''


def visible(kind, row, viewer, spoken=False):
    """Apply the owning kind's visibility before matching any title."""
    if row is None:
        return False
    role = (viewer or {}).get('role')
    if kind in ('trip', 'occasion'):
        allowed = scope.audience_allows(row, kind, viewer)
    elif kind == 'list':
        allowed = scope.audience_allows(row, 'shopping_list', viewer)
    elif kind == 'program':
        from services.agent_tools_v2 import _program_scope_id
        allowed = viewer is not None and (
            _program_scope_id(viewer) is None or row.get('member_id') == viewer.get('id')
        )
    elif kind == 'thread':
        from services import situations
        allowed = situations.can_see('thread', row, viewer)
    elif kind == 'event':
        allowed = scope.audience_allows(row, 'calendar_event', viewer)
    else:
        allowed = kind in ('member', 'contact') and role in WRITE_ROLES
    return bool(allowed) and (not spoken or spoken_safe(kind, row))


def spoken_safe(kind, row):
    obj_type = {
        'list': 'shopping_list', 'event': 'calendar_event',
        'trip': 'trip', 'occasion': 'occasion',
    }.get(kind, 'calendar_event')
    return (
        row is not None
        and bool(scope.audience_allows(row, obj_type, None))
        and row.get('sensitivity') != 'sensitive'
        and not row.get('private')
        and str(row.get('visibility') or '').lower() not in ('private', 'confidential')
    )


def _score(query, title):
    from services.agent_tools_v2 import _fold_name

    query, title = (query or '').strip().lower(), (title or '').strip().lower()
    if not query or not title:
        return 0.0
    if query == title:
        return 1.0
    if query in title or title in query:
        return 0.85
    if query.split()[0] == title.split()[0]:
        return 0.75
    folded_query, folded_title = _fold_name(query), _fold_name(title)
    if folded_query == folded_title:
        return 0.7
    ratio = difflib.SequenceMatcher(None, folded_query, folded_title).ratio()
    return ratio if ratio >= 0.8 else 0.0


def _when(kind, row):
    for key in ('start', 'anchor_date', 'next_action_at'):
        if row.get(key):
            return str(row[key])[:10]
    return ''


def _closed(kind, row):
    if kind in ('trip', 'occasion', 'event'):
        when = _when(kind, row)
        return bool(when) and when < datetime.date.today().isoformat()
    if kind in ('thread', 'program'):
        return row.get('state') in ('done', 'dropped')
    return False


def _rank(candidate):
    return (-candidate['score'], candidate['_closed'], candidate['when'] or '9999')


def _find(kind, query, viewer, spoken):
    candidates = []
    for row in _rows(kind):
        if not visible(kind, row, viewer, spoken):
            continue
        title = title_of(kind, row)
        score = _score(query, title)
        if score <= 0:
            continue
        candidates.append({
            'kind': kind, 'id': str(row.get('id')), 'title': title,
            'when': _when(kind, row), 'score': score, '_closed': _closed(kind, row),
        })
    candidates.sort(key=_rank)
    return candidates[:PER_KIND]


def _public(candidates):
    return [{key: value for key, value in row.items() if key != '_closed'}
            for row in candidates]


def find(kind, query, viewer, spoken=False):
    return _public(_find(kind, query, viewer, spoken))


def find_all(query, viewer, kinds=None, spoken=False):
    candidates = [candidate for kind in (kinds or KINDS)
                  for candidate in _find(kind, query, viewer, spoken)]
    candidates.sort(key=_rank)
    return _public(candidates[:OVERALL])


def resolve(query, viewer, kinds=None, spoken=False):
    candidates = find_all(query, viewer, kinds, spoken)
    if candidates and candidates[0]['score'] >= 0.7 and (
        len(candidates) == 1 or candidates[0]['score'] - candidates[1]['score'] >= 0.06
    ):
        return candidates[0], candidates
    return None, candidates


def link(kind, sid):
    return {
        'trip': f'/trip?event_id={sid}', 'occasion': f'/occasions#{sid}',
        'event': f'/app?event={sid}', 'member': f'/app?member={sid}',
        'contact': '/drives?settings=outside-hands', 'thread': '/threads',
        'program': f'/programs#{sid}', 'list': f'/shopping#{sid}',
    }.get(kind, '/')

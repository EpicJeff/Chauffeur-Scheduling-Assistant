"""Resolve a thread or mission's optional subject to a Chauffeur record."""

import datetime
import difflib
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass

from services import scope, storage


@dataclass
class Adapter:
    """A record kind's readers and rules; speaking requires an explicit opt-in."""

    rows: Callable[[], list]
    title: Callable[[dict], str]
    visible: Callable[[dict, dict | None], bool]
    closed: Callable[[dict], bool]
    link: Callable[[str], str]
    context: Callable[[dict, dict | None, bool, str | None], str | None]
    facets: list
    spoken_safe: Callable[[dict], bool] = lambda row: False


ADAPTERS: dict[str, Adapter] = {}
KINDS = ()
FACETS = {}
# Keep the legacy visited argument through the one-argument adapter hook,
# isolated between concurrent readers and reset after every call.
_spoken_visited = ContextVar('subject_spoken_visited', default=None)
PER_KIND, OVERALL, BUDGET = 5, 8, 1500
WRITE_ROLES = ('parent', 'adult')


def _rebuild_registry():
    global KINDS, FACETS
    KINDS = tuple(ADAPTERS)
    FACETS = {kind: adapter.facets for kind, adapter in ADAPTERS.items()}


def register(kind, adapter):
    """Add or replace a record kind, preserving registry order on replacement."""
    ADAPTERS[kind] = adapter
    _rebuild_registry()


def unregister(kind):
    """Remove a record kind and its discovery metadata, if present."""
    ADAPTERS.pop(kind, None)
    _rebuild_registry()


def channel_humans(focus_key):
    """Human recipients of a channel; None for a non-channel or unknown focus."""
    if not focus_key or not focus_key.startswith('channel:'):
        return None
    channel = storage.get_channel(focus_key[len('channel:'):])
    if not channel:
        return None
    members = ([storage.get_member(mid) for mid in channel.get('member_ids') or []]
               if channel.get('kind') in ('group', 'dm') else
               [m for m in storage.get_all_members() if (m.get('status') or 'active') == 'active'])
    return [m for m in members if not m or not (m.get('system') or m.get('id') == 'argyle')]


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
    adapter = ADAPTERS.get(kind)
    return adapter.rows() if adapter else []


def load(kind, sid):
    """Load a raw record; trips use the calendar event id as their subject id."""
    return next((row for row in _rows(kind) if str(row.get('id')) == str(sid)), None)


def _title(row):
    return row.get('title') or row.get('name') or ''


def title_of(kind, row):
    adapter = ADAPTERS.get(kind)
    return adapter.title(row) if adapter else _title(row)


def _program_visible(row, viewer):
    from services.agent_tools_v2 import _program_scope_id
    viewer = viewer or {'id': None, 'role': 'adult'}
    if row.get('member_id') == viewer.get('id'):
        return True
    return _program_scope_id(viewer) is None


def record_visible(kind, row, viewer, *, spoken=False, focus_key=None) -> bool:
    """One record gate: native audience, person-project, keeper, and channel.

    None is a household reader, never an impersonated project owner. Keepers
    (including a child's parents) retain the record, not its subject's words.
    """
    from services import situations, projects
    if not row or kind not in ('thread', 'mission', 'program'):
        return False
    reader = viewer or {'id': None, 'role': 'adult'}
    owner_key = {'thread': 'owner_member_id', 'mission': 'created_by', 'program': 'member_id'}[kind]
    owner_id = row.get(owner_key)
    keeper = bool(reader.get('id') and (reader['id'] == owner_id or (
        projects._parent(reader) and projects._child(storage.get_member(owner_id) or {}))))
    base = (_program_visible(row, reader) if kind == 'program'
            else situations._record_base_visible(kind, row, reader, keeper=keeper))
    if not base:
        return False
    project = containing_project(row)
    restricted = project and project.get('audience') != 'household'
    if restricted and (spoken or not reader.get('id') or not (keeper or projects.can_see(project, reader))):
        return False
    if spoken:
        if kind == 'mission':
            if any(not spoken_safe(k, r) for k, r in subject_records(kind, row)):
                return False
        elif not spoken_safe(kind, row):
            return False
    humans = channel_humans(focus_key)
    if humans is not None and project and not all(projects.can_see(project, h) for h in humans):
        return False
    return kind == 'program' or situations.channel_visible(kind, row, focus_key)


def containing_project(row):
    """A person's project narrows its pieces; wrappers depend on the piece."""
    project = storage.get_project(row['project_id']) if row.get('project_id') else None
    return project if project and not project.get('wrapped_from') else None


def _thread_visible(row, viewer):
    from services import situations
    return situations.can_see('thread', row, viewer)


def _people_visible(row, viewer):
    return (viewer or {}).get('role') in WRITE_ROLES


def visible(kind, row, viewer, spoken=False):
    """Apply the owning kind's visibility before matching any title."""
    if kind in ('thread', 'mission', 'program'):
        return record_visible(kind, row, viewer, spoken=spoken)
    adapter = ADAPTERS.get(kind)
    if row is None or adapter is None:
        return False
    return bool(adapter.visible(row, viewer)) and (not spoken or spoken_safe(kind, row))


def subject_records(kind, row):
    """Audience records, including a live mission's proposed project."""
    project = containing_project(row) if kind in ('thread', 'mission') else None
    proposed = (row.get('plan') or {}).get('project') if kind == 'mission' else None
    if kind == 'thread':
        from services import situations
        mission = situations._thread_mission(row) or {}
        proposed = (mission.get('plan') or {}).get('project')
    if kind == 'mission' and row.get('origin_kind') == 'thread' and row.get('origin_ref'):
        row = storage.get_thread(row['origin_ref']) or {}
    entries = list(row.get('subject_history') or [])
    if row.get('subject_kind'):
        entries.append({'kind': row['subject_kind'], 'id': row.get('subject_id')})
    seen, records = set(), []
    if project:
        records.append(('project', project))
        seen.add(('project', project['id']))
    for entry in entries:
        key = (entry.get('kind'), entry.get('id'))
        if key in seen:
            continue
        seen.add(key)
        record = load(*key) if key[0] and key[1] else None
        if record is not None:
            records.append((key[0], record))
    # A preview has no stored project yet, but its words already have that
    # audience. Read the current proposal each time so revisions can widen it;
    # after binding, the real project's current audience takes over.
    if (proposed and not proposed.get('id') and row.get('subject_kind') != 'project'
            and proposed.get('audience') != 'household'):
        records.append(('proposed_project', {
            **proposed, 'owner_member_id': proposed.get('owner')}))
    return records


def history_after_binding(row, kind=None, sid=None):
    """Preserve legacy current subjects too, before a change can erase them."""
    history = list(row.get('subject_history') or [])
    current = {'kind': row.get('subject_kind'), 'id': row.get('subject_id')}
    if current['kind'] and current['id'] and current not in history:
        history.append(current)
    if kind and sid:
        history.append({'kind': kind, 'id': sid})
    return history


def _audience_spoken_safe(row, obj_type='calendar_event'):
    return (
        row is not None
        and bool(scope.audience_allows(row, obj_type, None))
        and row.get('sensitivity') != 'sensitive'
        and not row.get('private')
        and str(row.get('visibility') or '').lower() not in ('private', 'confidential')
    )


def _thread_spoken_safe(row):
    # A thread is said aloud only once it was shared with the speakers (the voice
    # rail's own rule: start_mission_for and dispatch read voice_shared too).
    if not (row or {}).get('voice_shared'):
        return False
    visited = set(_spoken_visited.get() or ())
    key = row.get('id')
    if key in visited:
        return False
    visited.add(key)
    if any(not spoken_safe(k, record, visited) for k, record in subject_records('thread', row)):
        return False
    return _audience_spoken_safe(row)


def _program_spoken_safe(row):
    return _audience_spoken_safe(row) and record_visible('program', row, None)


def spoken_safe(kind, row, visited=None):
    adapter = ADAPTERS.get(kind)
    if adapter is None or row is None:
        return False
    token = _spoken_visited.set(visited)
    try:
        return bool(adapter.spoken_safe(row))
    finally:
        _spoken_visited.reset(token)


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


def _dated_closed(kind, row):
    when = _when(kind, row)
    return bool(when) and when < datetime.date.today().isoformat()


def _closed(kind, row):
    adapter = ADAPTERS.get(kind)
    return adapter.closed(row) if adapter else False


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
    # Relative, like every page link in the app: under Home Assistant ingress an
    # absolute path escapes the add-on's prefix. Only pages that exist.
    adapter = ADAPTERS.get(kind)
    return adapter.link(sid) if adapter else 'app'


def retarget(sit_kind, sid, new_kind, new_id, actor):
    """Change the subject, invalidating live work built about the old record."""
    from services import missions, situations

    if (actor or {}).get('role') not in WRITE_ROLES:
        return {'status': 'refused'}
    with storage.db_lock:
        row = situations.load(sit_kind, sid) if sit_kind in ('thread', 'mission') else None
        if not row:
            return {'status': 'error', 'message': 'That is no longer here.'}
        live = [m for m in storage.get_missions(status=missions.LIVE)
                if (sit_kind == 'mission' and m['id'] == sid)
                or (sit_kind == 'thread' and m.get('origin_kind') == 'thread' and m.get('origin_ref') == sid)]
        from services import planned
        if any(m.get('status') == 'browsing' or missions.tap_only_ask_pending(m['id'])
               or planned.stage_pending(m)
               or ((m.get('plan') or {}).get('state') == 'approved'
                   and any(s.get('state') not in ('done', 'skipped')
                           for s in m['plan'].get('stages', []))) for m in live):
            return {'status': 'refused',
                    'message': 'Finish or stop the pending step first; then change what this is about.'}
        new_row = load(new_kind, new_id) if new_kind else None
        if new_kind and (not new_row or not visible(new_kind, new_row, actor)):
            return {'status': 'error', 'message': 'Nothing by that name you can see.'}
        old_kind = row.get('subject_kind')
        old_row = load(old_kind, row.get('subject_id')) if old_kind else None
        old_title = title_of(old_kind, old_row) if old_row else None
        new_title = title_of(new_kind, new_row) if new_row else None
        rev = int(row.get('subject_rev') or 0) + 1
        fields = {'subject_kind': new_kind or None, 'subject_id': new_id or None, 'subject_rev': rev,
                  'subject_history': history_after_binding(row, new_kind, new_id)}
        update = storage.update_thread if sit_kind == 'thread' else storage.update_mission
        update(sid, fields)
        for m in live:
            storage.add_mission_step(m['id'], {
                'kind': 'note', 'name': 'subject_changed',
                'result_json': {'from': old_title, 'to': new_title, 'rev': rev,
                                'note': ('unlinked' if not new_kind else f'now about {new_title}')
                                        + '; re-read before acting'},
            })
            for step in storage.get_mission_steps(m['id']):
                pid = (step.get('result_json') or {}).get('proposal_id') if step.get('kind') == 'proposal' else None
                proposal = storage.get_action_proposal(pid) if pid else None
                if proposal and proposal.get('status') == 'proposed':
                    storage.update_action_proposal(pid, {'status': 'dismissed'})
    situations.bump_rev(sit_kind, sid)
    situations.request_refresh(sit_kind, sid)
    return {'status': 'success', 'message': 'Unlinked.' if not new_kind else f'Now about {new_title}.', 'rev': rev}


def trip_dates(event_id):
    """Read destination dates from draft metadata or the calendar snapshot."""
    import time

    metadata = storage.get_trip_metadata(event_id) or {}
    if metadata.get('is_draft') and metadata.get('mock_start_date') is not None:
        start = datetime.date.fromtimestamp(float(metadata['mock_start_date'])).isoformat()
        end_ts = metadata.get('mock_end_date')
        end = datetime.date.fromtimestamp(float(end_ts)).isoformat() if end_ts is not None else None
        return {'start': start, 'end': end, 'source': 'draft', 'age_s': 0}
    snapshot = storage.get_cached_trips() or {}
    row = next((t for t in snapshot.get('trips') or [] if t.get('id') == event_id), None)
    if row and row.get('start'):
        now = time.time()
        return {'start': row['start'], 'end': row.get('end'), 'source': 'calendar',
                'age_s': max(0, now - float(snapshot.get('at') or now))}
    return {'start': None, 'end': None, 'source': 'unknown', 'age_s': None}


def _age_words(age_s):
    if age_s is None or age_s < 3600:
        return ''
    hours = int(age_s // 3600)
    age = f'{hours} hours' if hours < 48 else f'{hours // 24} days'
    return f' (as the calendar had them {age} ago)'


def _clip(lines, budget=BUDGET):
    """Keep whole lines within the character budget, including separators."""
    out, used = [], 0
    for line in lines:
        size = len(line) + bool(out)
        if used + size > budget:
            break
        out.append(line)
        used += size
    return '\n'.join(out)


def _fmt_window(poi):
    if not poi.get('is_scheduled') or not poi.get('scheduled_start'):
        return 'not scheduled'
    start = datetime.datetime.fromtimestamp(float(poi['scheduled_start']))
    end_ts = poi.get('scheduled_end')
    end = datetime.datetime.fromtimestamp(float(end_ts)) if end_ts else None
    return (start.strftime('%a %b %d %I:%M %p').replace(' 0', ' ')
            + (end.strftime(' to %I:%M %p').replace(' 0', ' ') if end else ''))


def _poi_line(poi):
    meal = f" ({poi['meal_type']})" if poi.get('meal_type') else ''
    return (f"- {poi.get('name')}{meal}, {poi.get('category') or 'other'}: {_fmt_window(poi)}"
            + (f", {poi['location']}" if poi.get('location') else ''))


def _clip_pois(prefix, pois):
    """Reserve the omission count even when the header exhausts the budget."""
    total = len(pois)
    if not total:
        return _clip(prefix + ['- none on file'])
    reserve = len(f'- and {total} more') + 1
    text = _clip(prefix, BUDGET - reserve)
    shown = 0
    for poi in pois[:30]:
        candidate = '\n'.join(filter(None, (text, _poi_line(poi))))
        remaining = total - shown - 1
        tail = f'\n- and {remaining} more' if remaining else ''
        if len(candidate) + len(tail) > BUDGET:
            break
        text = candidate
        shown += 1
    if shown < total:
        text = '\n'.join(filter(None, (text, f'- and {total - shown} more')))
    return text


def _accommodation_lines(row):
    lines = []
    for accommodation in row.get('accommodations') or []:
        start = accommodation.get('check_in_date')
        end = accommodation.get('check_out_date')
        nights = ''
        try:
            count = (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)).days
            nights = f', {count} nights'
        except (TypeError, ValueError):
            pass
        lines.append(f"- {accommodation.get('name')}, {accommodation.get('location') or ''}: "
                     f"{start or '?'} to {end or '?'}{nights}")
    return lines or ['- none on file']


def _flight_lines(row):
    return [f"- {flight.get('airline') or ''} {flight.get('flight_number') or ''} "
            f"{flight.get('origin') or '?'} to {flight.get('destination') or '?'} "
            f"{flight.get('departure_time') or ''}".strip()
            for flight in row.get('flights') or []] or ['- none on file']


def _trip_context(row, viewer, spoken, facet):
    dates = trip_dates(row['event_id'])
    head = [f"TRIP: {title_of('trip', row)}"
            + (f", {row['location']}" if row.get('location') else '')]
    if dates['source'] == 'unknown':
        head.append('Dates unknown; confirm them before booking anything.')
    else:
        head.append(f"Dates: {dates['start']} to {dates['end'] or '?'}"
                    + _age_words(dates['age_s'])
                    + (' (draft)' if dates['source'] == 'draft' else ''))
    if row.get('travelers') is not None:
        head.append(f"{row['travelers']} travellers.")
    head.append('facets: ' + ', '.join(FACETS['trip']))
    pois = sorted(row.get('pois') or [], key=lambda p: (
        not p.get('is_scheduled'),
        (p.get('scheduled_start') or 0) if p.get('is_scheduled') else 0,
    ))
    if facet in ('dining', 'attractions'):
        selected = [p for p in pois if (p.get('category') == 'food') == (facet == 'dining')]
        return _clip_pois(head + [facet.upper() + ':'], selected)
    if facet == 'flights':
        return _clip(head + ['FLIGHTS:'] + _flight_lines(row))
    if facet == 'accommodations':
        return _clip(head + ['ACCOMMODATIONS:'] + _accommodation_lines(row))
    if row.get('_calendar_only') and not pois:
        return _clip(head + ['No itinerary on file for this trip.'])
    return _clip_pois(head + ['ACCOMMODATIONS:'] + _accommodation_lines(row)
                      + ['FLIGHTS:'] + _flight_lines(row)
                      + ['STOPS (dining is category food):'], pois)


def _occasion_context(row, viewer, spoken, facet):
    from services import occasions

    contents = occasions.contents(row['id'])
    head = [f"OCCASION: {title_of('occasion', row)}", f"Date: {row.get('anchor_date') or '?'}"]
    if contents.get('days_away') is not None:
        head.append(f"{contents['days_away']} days away.")
    head.append(f"Headcount: {contents.get('headcount', 0)}.")
    guests = [f"- {guest.get('name')}: {guest.get('headcount') or 1}"
              for guest in contents.get('guests') or []] or ['- no guests on file']
    lists = [f"- {linked.get('name')}" for linked in contents.get('lists') or []
             if scope.audience_allows(linked, 'shopping_list', None if spoken else viewer)] or ['- none on file']
    errands = contents.get('errands') or []
    pending = [errand for errand in errands if not errand.get('is_completed')]
    errand_lines = [f'Errands left: {len(pending)} open / {len(errands)} total.']
    if facet == 'guests':
        return _clip(head + ['GUESTS:'] + guests)
    if facet == 'menu':
        dishes = (occasions.menu(row['id']) or {}).get('dishes') or []
        return _clip(head + ['MENU:'] + ([f"- {dish.get('name')}" for dish in dishes]
                                      or ['- no menu yet']))
    if facet == 'lists':
        return _clip(head + ['LISTS:'] + lists)
    if facet == 'errands':
        return _clip(head + errand_lines)
    return _clip(head + ['GUESTS:'] + guests + ['LISTS:'] + lists + errand_lines)


def _event_context(row, viewer, spoken, facet):
    assignments = (storage.get_cached_schedule() or {}).get('assignments') or {}
    driver_id = assignments.get(row['id'])
    driver_name = next((driver.get('name') for driver in storage.get_all_drivers()
                        if driver.get('id') == driver_id), None)
    lines = [f"EVENT: {title_of('event', row)}",
             f"When: {str(row.get('start') or '?').replace('T', ' ')}",
             f"Location: {row.get('location') or 'not on file'}",
             f"Driver: {driver_name or 'no driver yet'}"]
    passengers = row.get('passenger_names') or row.get('passengers') or []
    if passengers:
        names = [str(p.get('name') or p.get('id') or '') if isinstance(p, dict) else str(p)
                 for p in passengers]
        lines.append('Passengers: ' + ', '.join(names))
    return _clip(lines)


def _member_context(row, viewer, spoken, facet):
    return _clip([f"{title_of('member', row)} ({row.get('role') or 'unknown role'})",
                  'Drives.' if row.get('driver_id') else 'Does not drive.'])


def _contact_context(row, viewer, spoken, facet):
    lines = [f"CONTACT: {title_of('contact', row)}"]
    if row.get('relation_label'):
        lines.append(f"Relation: {row['relation_label']}")
    if row.get('helps_with'):
        lines.append('Helps with: ' + ', '.join(row['helps_with']))
    for channel in ('phone', 'email'):
        if row.get(channel):
            lines.append(f'{channel} on file' if spoken else f"{channel}: {row[channel]}")
    return _clip(lines)


def _thread_context(row, viewer, spoken, facet):
    lines = [f"THREAD: {title_of('thread', row)}"]
    history = [f"- {entry['text']}" for entry in (row.get('history') or [])[-3:]
               if entry.get('text')]
    if facet != 'history':
        lines.extend([f"Goal: {row.get('goal') or 'not on file'}",
                      f"State: {row.get('state') or '?'}"])
        counterparty = row.get('counterparty_name') or row.get('counterparty_email')
        if not counterparty and row.get('contact_id'):
            contact = storage.get_assist_contact(row['contact_id'])
            counterparty = title_of('contact', contact) if contact else None
        lines.append(f"Counterparty: {counterparty or 'not on file'}")
        lines.append(f"Next action: {row.get('next_action') or 'not on file'}"
                     + (f" (by {row['next_action_at']})" if row.get('next_action_at') else ''))
    return _clip(lines + ['HISTORY:'] + (history or ['- none on file']))


def _program_context(row, viewer, spoken, facet):
    from services import programs

    member = storage.get_member(row.get('member_id')) or {}
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())
    sessions = programs.sessions_between(row, monday, today)
    lines = [f"PROGRAM: {title_of('program', row)}",
             f"For: {member.get('name') or 'unknown member'}",
             f"State: {row.get('state') or '?'}",
             f'{len(sessions)} sessions logged this week ({monday.isoformat()} to {today.isoformat()}).']
    if facet == 'sessions':
        for session in sessions:
            date = datetime.date.fromtimestamp(float(session['ts'])).isoformat()
            lines.append(f"- {date}: {session.get('minutes') or 0} minutes"
                         + (f", {session['note']}" if session.get('note') else ''))
    return _clip(lines)


def _list_context(row, viewer, spoken, facet):
    items = storage.get_shopping_items(row['id'])
    return _clip([f"LIST: {title_of('list', row)}", f'{len(items)} items.']
                 + [f"- {item.get('name')}" for item in items[:10]])


def context(kind, sid, viewer, spoken=False, facet=None) -> str | None:
    """Read fresh subject context only after authorising this viewer/surface."""
    row = load(kind, sid)
    if not visible(kind, row, viewer, spoken):
        return None
    if facet not in FACETS.get(kind, []):
        facet = None
    return ADAPTERS[kind].context(row, viewer, spoken, facet)


ADAPTERS.update({
    'trip': Adapter(
        rows=_trip_rows,
        title=_title,
        visible=lambda row, viewer: scope.audience_allows(row, 'trip', viewer),
        closed=lambda row: _dated_closed('trip', row),
        link=lambda sid: f'trip?event_id={sid}',
        context=_trip_context,
        facets=['flights', 'accommodations', 'dining', 'attractions'],
        spoken_safe=lambda row: _audience_spoken_safe(row, 'trip'),
    ),
    'occasion': Adapter(
        rows=lambda: storage.get_occasions(include_done=True),
        title=_title,
        visible=lambda row, viewer: scope.audience_allows(row, 'occasion', viewer),
        closed=lambda row: _dated_closed('occasion', row),
        link=lambda sid: 'occasions',
        context=_occasion_context,
        facets=['guests', 'menu', 'lists', 'errands'],
        spoken_safe=lambda row: _audience_spoken_safe(row, 'occasion'),
    ),
    'event': Adapter(
        rows=lambda: list((storage.get_cached_schedule() or {}).get('events') or []),
        title=_title,
        visible=lambda row, viewer: scope.audience_allows(row, 'calendar_event', viewer),
        closed=lambda row: _dated_closed('event', row),
        link=lambda sid: 'app',
        context=_event_context,
        facets=[],
        spoken_safe=_audience_spoken_safe,
    ),
    'member': Adapter(
        rows=lambda: [row for row in storage.get_all_members() if not row.get('system')],
        title=_title,
        visible=_people_visible,
        closed=lambda row: False,
        link=lambda sid: 'app',
        context=_member_context,
        facets=[],
        spoken_safe=_audience_spoken_safe,
    ),
    'contact': Adapter(
        rows=lambda: storage.get_assist_contacts(),
        title=lambda row: row.get('relation_label') or row.get('name') or '',
        visible=_people_visible,
        closed=lambda row: False,
        link=lambda sid: 'drive_setup',
        context=_contact_context,
        facets=[],
        spoken_safe=_audience_spoken_safe,
    ),
    'thread': Adapter(
        rows=lambda: storage.get_threads(include_closed=True),
        title=_title,
        visible=_thread_visible,
        closed=lambda row: row.get('state') in ('done', 'dropped'),
        link=lambda sid: f'projects?piece=thread:{sid}',
        context=_thread_context,
        facets=['history'],
        spoken_safe=_thread_spoken_safe,
    ),
    'program': Adapter(
        rows=lambda: storage.get_programs(include_finished=True),
        title=_title,
        visible=_program_visible,
        closed=lambda row: row.get('state') in ('done', 'dropped'),
        link=lambda sid: f'projects?piece=program:{sid}',
        context=_program_context,
        facets=['sessions'],
        spoken_safe=_program_spoken_safe,
    ),
    'list': Adapter(
        rows=lambda: storage.get_shopping_lists(),
        title=_title,
        visible=lambda row, viewer: scope.audience_allows(row, 'shopping_list', viewer),
        closed=lambda row: False,
        link=lambda sid: 'shopping',
        context=_list_context,
        facets=[],
        spoken_safe=lambda row: _audience_spoken_safe(row, 'shopping_list'),
    ),
})
_rebuild_registry()

# Register projects once the registry and built-in adapters are ready. Projects
# defines its service before importing this registry, so either import order works.
from services import projects as _projects

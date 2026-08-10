"""Optional events, phase 2 — per-occurrence decisions.

Phase 1 (v2.153.0) made `is_optional` a fact about an event: reduced solver
weight, dropped first on conflict, calm voice everywhere. This module adds
what the family chose about ONE occurrence:

    attend  — a real commitment now. Full solver weight, and if it still
              can't be covered that IS a siren: somebody promised a kid.
    skip    — out of the optimisation entirely, like an outside-hands event:
              not assignable, not unassigned, nothing to say. Still drawn.
    (none)  — undecided, the default that needs no answer: goes if it fits,
              dropped first if it doesn't, one calm line when that happens.

Decisions live in their own table (storage.optional_decisions), NEVER in the
event config: a config is what the event IS, a decision is what the family
chose that day — and a programmatic write into an instance config would
replace the series config wholesale (the lookup takes the first config it
finds), silently dropping passengers and attendance settings.

Keying mirrors the event-config lookup: the occurrence's own google id is
checked first, then the recurring series id — so "skip open gym today"
written against the instance never touches any sibling occurrence, while a
series-keyed decision (rare, but expressible) covers the date for whichever
occurrence falls on it. Decisions expire with the day and are pruned.
"""
import datetime

from services import storage


def candidate_google_ids(ev) -> list:
    """The google ids a decision (or config) for this event may be keyed by:
    instance id(s) first, recurring series id last — first hit wins."""
    get = ev.get if isinstance(ev, dict) else lambda k, d=None: getattr(ev, k, d)
    out = []
    for src in (get('source_event_ids') or [get('id')]):
        if not src:
            continue
        parts = str(src).split('::')
        gid = parts[-1] if len(parts) > 1 else str(src)
        if gid not in out:
            out.append(gid)
    rec = get('recurring_event_id')
    if rec and rec not in out:
        out.append(str(rec))
    return out


def _event_date(ev) -> str:
    get = ev.get if isinstance(ev, dict) else lambda k, d=None: getattr(ev, k, d)
    return str(get('start') or '')[:10]


def decision_for(ev):
    """'attend' | 'skip' | None for this occurrence."""
    date = _event_date(ev)
    if not date:
        return None
    return storage.get_optional_decision(candidate_google_ids(ev), date)


def stamp_decisions(events) -> None:
    """Refresh-pipeline pass: stamp `optional_decision` onto every event whose
    config says optional. Also prunes expired decisions — the sweep runs at
    least hourly, so the table never accumulates history."""
    storage.prune_optional_decisions(datetime.date.today().isoformat())
    for e in events:
        conf = getattr(e, 'app_config', None) or {}
        if conf.get('is_optional'):
            e.optional_decision = decision_for(e)


def record_decision(ev, decision: str, decided_by: str = None) -> dict:
    """Write a decision for one cached-schedule event (dict or Event).
    decision: 'attend' | 'skip' | 'clear'. Keys by the occurrence's own
    google id so recurring siblings are never touched."""
    if decision not in ('attend', 'skip', 'clear'):
        return {'status': 'error', 'message': "Decision must be attend, skip or clear."}
    date = _event_date(ev)
    ids = candidate_google_ids(ev)
    if not date or not ids:
        return {'status': 'error', 'message': 'Event has no usable id or date.'}
    storage.set_optional_decision(ids[0], date,
                                  decision if decision != 'clear' else '',
                                  decided_by=decided_by)
    get = ev.get if isinstance(ev, dict) else lambda k, d=None: getattr(ev, k, d)
    title = get('title') or 'Event'
    said = {'attend': f"{title} on {date} is happening — planning the drive.",
            'skip': f"{title} on {date} is skipped — nobody will be scheduled for it.",
            'clear': f"{title} on {date} is back to optional — it goes if it fits."}
    return {'status': 'success', 'message': said[decision], 'date': date,
            'google_id': ids[0], 'decision': None if decision == 'clear' else decision}


def decide_by_title(event_name: str, target_date: str, decision: str,
                    decided_by: str = None) -> dict:
    """Agent path (both stacks): resolve by fuzzy title + date, then record.
    The resolved event must actually BE optional — deciding attendance on a
    mandatory event is a category error the agent should hear about."""
    from services.agent_tools_v2 import _find_event_fuzzy
    ev, err = _find_event_fuzzy(event_name, target_date or 'today')
    if err:
        return {'status': 'error', 'message': err}
    if not ((ev.get('app_config') or {}).get('is_optional')):
        return {'status': 'error',
                'message': f"'{ev.get('title')}' is not marked optional — its "
                           f"attendance isn't a day-by-day choice. To make it "
                           f"optional, say so or tick Optional on its event config."}
    return record_decision(ev, decision, decided_by=decided_by)


def set_optional_flag(event_name: str, target_date: str, optional: bool,
                      scope: str = 'series') -> dict:
    """Agent path: flag an event (series by default) optional or not. Writes
    the event CONFIG — merged over whatever config already governs the event,
    so passengers/attendance settings survive (the config lookup replaces
    wholesale, never merges)."""
    from services.agent_tools_v2 import _find_event_fuzzy
    ev, err = _find_event_fuzzy(event_name, target_date or 'today')
    if err:
        return {'status': 'error', 'message': err}
    ids = candidate_google_ids(ev)
    if not ids:
        return {'status': 'error', 'message': 'Event has no usable google id.'}
    rec = ev.get('recurring_event_id')
    if scope == 'series' and rec:
        # Merge over the series config only — an instance config as template
        # would spread one occurrence's overrides across the whole series.
        target_gid = str(rec)
        existing = storage.get_event_config(target_gid)
    else:
        target_gid = ids[0]
        existing = storage.get_event_config(target_gid)
        if not existing and rec:
            # New instance override: start from the series config so the
            # wholesale-replacing lookup doesn't lose passengers/attendance.
            existing = storage.get_event_config(str(rec))
    conf = dict(existing or {})
    conf['google_id'] = target_gid
    conf['is_optional'] = bool(optional)
    storage.set_event_config(target_gid, conf)
    title = ev.get('title') or 'Event'
    span = 'and every occurrence of it' if (scope == 'series' and rec) else 'for this occurrence'
    return {'status': 'success',
            'message': (f"{title} is optional now {span} — scheduled when the day "
                        f"allows, first dropped when it doesn't."
                        if optional else
                        f"{title} is a firm commitment again {span}.")}

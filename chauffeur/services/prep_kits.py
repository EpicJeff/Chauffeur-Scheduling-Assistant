"""Prep kits: rule-filtered packing lists for events.

A kit is {name, items, enabled} plus the SAME filter criteria routing rules
use — keywords (any/all), passengers (any/all), days of week, time window,
date window, location substring. Matching delegates to the solver's
`does_event_match_rule`, so kit semantics are identical to rule semantics by
construction (AND across criteria types, at least one criterion required).
Items surface on My Day ride cards and in the tomorrow digest, so the "what
do we need to bring" scramble happens at kit-setup time — once — instead of
five minutes before every departure.

Setup itself is agent-assisted: suggest_kits() runs ONE LLM request over the
family's real upcoming event titles and returns proposed kits for the parent
to review/edit on the /routines page. Nothing is saved until approved.
"""
import datetime
from types import SimpleNamespace

from services import storage

# The rule-filter fields a kit shares with Rule (see _kit_rule_obj).
FILTER_FIELDS = ('keywords', 'keywords_match_all', 'passenger_ids',
                 'passengers_match_all', 'days_of_week', 'time_start',
                 'time_end', 'start_date', 'end_date', 'location')


def _event_obj(ev: dict):
    """Cache-event dict -> the attribute shape does_event_match_rule reads.
    None when the event has no parseable start (nothing to match on)."""
    try:
        start = datetime.datetime.fromisoformat(str(ev.get('start')))
        end = datetime.datetime.fromisoformat(str(ev.get('end') or ev.get('start')))
    except (TypeError, ValueError):
        return None
    return SimpleNamespace(
        title=ev.get('title') or '', description=ev.get('description') or '',
        start=start, end=end, location=ev.get('location') or '',
        calendar_ids=[str(c) for c in (ev.get('calendar_ids') or [])])


def _kit_rule_obj(kit: dict):
    return SimpleNamespace(
        keywords=kit.get('keywords') or [],
        keywords_match_all=bool(kit.get('keywords_match_all')),
        passenger_ids=[str(p) for p in (kit.get('passenger_ids') or [])],
        passengers_match_all=bool(kit.get('passengers_match_all')),
        days_of_week=kit.get('days_of_week') or [],
        time_start=kit.get('time_start') or None,
        time_end=kit.get('time_end') or None,
        start_date=kit.get('start_date') or None,
        end_date=kit.get('end_date') or None,
        location=kit.get('location') or None)


def passenger_objs(passengers: list = None) -> list:
    """Passenger records -> the shape the matcher resolves passenger filters
    against (id / calendar_ids / name). Compute once per request and reuse."""
    if passengers is None:
        passengers = storage.get_all_passengers()
    return [SimpleNamespace(id=str(p.get('id')),
                            calendar_ids=[str(c) for c in (p.get('calendar_ids') or [])],
                            name=p.get('name') or '')
            for p in passengers]


def match_kits_for_event(ev: dict, kits: list = None, passengers: list = None) -> list:
    """Enabled kits whose rule-filters match the event — exact routing-rule
    semantics via the solver's own does_event_match_rule."""
    from solver.matcher import does_event_match_rule
    if kits is None:
        kits = storage.get_prep_kits()
    event = _event_obj(ev)
    if event is None:
        return []
    if passengers is None:
        passengers = passenger_objs()
    return [k for k in kits
            if k.get('enabled') is not False
            and does_event_match_rule(event, _kit_rule_obj(k), passengers)]


def items_for_event(ev: dict, kits: list = None, passengers: list = None) -> list:
    """Deduped, order-preserving item list across every matching kit."""
    items, seen = [], set()
    for k in match_kits_for_event(ev, kits, passengers):
        for item in (k.get('items') or []):
            key = item.strip().lower()
            if key and key not in seen:
                seen.add(key)
                items.append(item.strip())
    return items


SUGGEST_SYSTEM = """You help a busy family prepare for their kids' activities.
Given the titles of the family's real upcoming calendar events, propose "prep
kits": reusable packing lists matched to recurring activity types.

Return STRICT JSON: {"kits": [{"name": "...", "keywords": ["..."],
"items": ["..."]}]}

Rules:
- Only propose kits for activities with predictable physical gear (sports
  practices/games, swim, dance, scouts, music lessons, camps, beach/pool
  outings). Skip appointments, parties, school pickups, and anything generic.
- keywords: 1-3 lowercase substrings that appear in the actual event titles
  given (e.g. "soccer" matches "Addison Soccer Practice"). Never invent
  keywords that match none of the titles.
- items: 3-8 concrete things to pack, most-forgettable first (gear, water
  bottle, snacks, sunscreen...). Title Case, short.
- One kit per activity type, not per event. Do not duplicate the existing
  kits listed; if an existing kit already covers an activity, skip it.
- No matching activities at all -> {"kits": []}."""


def suggest_kits(event_titles: list, existing_kits: list = None,
                 tier: str = 'interactive') -> list:
    """One LLM request -> proposed kit dicts (NOT saved). Raises RuntimeError
    when no key is configured or the call fails. tier='interactive' when a
    user clicked Suggest and is waiting (lite pool); the weekly watcher sweep
    passes 'background' (gemma-first — nobody is waiting)."""
    from services import model_pools
    settings = storage.get_settings() or {}
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key:
        raise RuntimeError('no LLM API key configured')

    existing = existing_kits if existing_kits is not None else storage.get_prep_kits()
    existing_desc = '\n'.join(
        f"- {k.get('name')}: keywords {', '.join(k.get('keywords') or [])}"
        for k in existing) or '(none)'
    titles = sorted({t.strip() for t in event_titles if t and t.strip()})
    prompt = (f"Existing kits (do not duplicate):\n{existing_desc}\n\n"
              f"Upcoming event titles:\n" + '\n'.join(f"- {t}" for t in titles[:60]))

    res = model_pools.call_pool_json(tier, api_key, SUGGEST_SYSTEM, prompt,
                                     temperature=0.2,
                                     timeout_s=60 if tier == 'interactive' else 120,
                                     settings=settings)
    if not isinstance(res, dict):
        return []
    if res.get('error'):
        raise RuntimeError(str(res['error']))

    out = []
    covered = {kw.strip().lower() for k in existing
               for kw in (k.get('keywords') or []) if kw and kw.strip()}
    for kit in res.get('kits') or []:
        if not isinstance(kit, dict):
            continue
        name = (kit.get('name') or '').strip()
        keywords = [str(kw).strip().lower() for kw in (kit.get('keywords') or [])
                    if str(kw).strip()]
        items = [str(i).strip() for i in (kit.get('items') or []) if str(i).strip()]
        # Ground the proposal: every keyword must hit a real title, and a kit
        # whose keywords are all already covered by an existing kit is noise.
        keywords = [kw for kw in keywords
                    if any(kw in t.lower() for t in titles)]
        if not name or not keywords or not items:
            continue
        if all(kw in covered for kw in keywords):
            continue
        out.append({'name': name, 'keywords': keywords[:3], 'items': items[:8]})
    return out

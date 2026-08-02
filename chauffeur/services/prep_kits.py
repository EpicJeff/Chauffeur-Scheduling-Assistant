"""Prep kits: keyword-matched packing lists for events.

A kit is {name, keywords, items, enabled}. Matching is the same family as
rule keywords: case-insensitive substring, any keyword matches. Items surface
on My Day ride cards and in the tomorrow digest, so the "what do we need to
bring" scramble happens at kit-setup time — once — instead of five minutes
before every departure.

Setup itself is agent-assisted: suggest_kits() runs ONE LLM request over the
family's real upcoming event titles and returns proposed kits for the parent
to review/edit on the /routines page. Nothing is saved until approved.
"""
from services import storage


def match_kits(title: str, kits: list = None) -> list:
    """Enabled kits whose any keyword appears in the event title."""
    if kits is None:
        kits = storage.get_prep_kits()
    title_l = (title or '').lower()
    if not title_l:
        return []
    out = []
    for k in kits:
        if k.get('enabled') is False:
            continue
        if any(kw.strip().lower() in title_l
               for kw in (k.get('keywords') or []) if kw and kw.strip()):
            out.append(k)
    return out


def items_for_title(title: str, kits: list = None) -> list:
    """Deduped, order-preserving item list across every matching kit."""
    items, seen = [], set()
    for k in match_kits(title, kits):
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


def suggest_kits(event_titles: list, existing_kits: list = None) -> list:
    """One LLM request -> proposed kit dicts (NOT saved). Raises RuntimeError
    when no key is configured or the call fails."""
    from services.llm import _call_llm_json
    settings = storage.get_settings() or {}
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key:
        raise RuntimeError('no LLM API key configured')
    model = settings.get('agent_primary_model') or 'gemini-3.5-flash'

    existing = existing_kits if existing_kits is not None else storage.get_prep_kits()
    existing_desc = '\n'.join(
        f"- {k.get('name')}: keywords {', '.join(k.get('keywords') or [])}"
        for k in existing) or '(none)'
    titles = sorted({t.strip() for t in event_titles if t and t.strip()})
    prompt = (f"Existing kits (do not duplicate):\n{existing_desc}\n\n"
              f"Upcoming event titles:\n" + '\n'.join(f"- {t}" for t in titles[:60]))

    res = _call_llm_json('gemini', '', api_key, model, SUGGEST_SYSTEM, prompt,
                         temperature=0.2, timeout_s=60)
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

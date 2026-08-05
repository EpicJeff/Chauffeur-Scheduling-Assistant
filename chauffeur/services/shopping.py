"""Shopping list support (meals & provisioning arc M1).

Photo capture aimed at the shots VOICE CANNOT DO — the open fridge shelf, the
pile of empty packages by the bin, the handwritten list on the counter.
Photographing an item you are holding is a worse interaction than saying its
name, so this path is deliberately not built around that.

Two design constraints from docs/meal_design.md:

- **Never claim to know what is in the house** (principle 2). A shelf photo
  answers "what should I add to the list", NOT "here is the inventory". The
  extraction is asked for restock CANDIDATES, and nothing here persists a
  belief about what the family has.
- Candidates are **staged, not auto-added**. That is not an approval gate
  (principle 4 — a list item costs nothing and needs nobody's permission); it
  is that a fridge photo yields a dozen guesses and the family should pick.
  A handwritten list is the high-confidence case and comes back pre-selected.
"""
from services import storage

EXTRACTION_SYSTEM = (
    "You read a photo taken by a busy parent and turn it into shopping-list "
    "candidates. Reply with STRICT JSON only, no prose, no code fences.\n\n"
    "Schema: {\"kind\": \"handwritten|shelf|packages|receipt|other\", "
    "\"candidates\": [{\"name\": str, \"qty\": str|null, \"suggested\": bool, "
    "\"why\": str}]}\n\n"
    "kind:\n"
    "- handwritten: a written or typed list someone made. TRANSCRIBE it. "
    "Every legible line is a candidate with suggested=true.\n"
    "- shelf: a fridge/pantry/cupboard photo. Name things that look EMPTY, "
    "NEARLY EMPTY, or absent from a spot they clearly belong in. "
    "suggested=true only for those. A full container is not a candidate.\n"
    "- packages: empty packaging someone kept to signal a restock. Every "
    "identifiable product is a candidate with suggested=true.\n"
    "- receipt: a past receipt being used as a reorder reference. "
    "suggested=false for everything — the family picks what to repeat.\n\n"
    "Rules:\n"
    "- name is what a shopper would write: 'milk', 'sourdough bread', "
    "'paper towels'. Use the brand ONLY when it is clearly what matters.\n"
    "- qty is free text ('2 lbs', 'a dozen') or null. NEVER invent a quantity.\n"
    "- why is a SHORT reason ('carton looks empty', 'line 3 of the list').\n"
    "- Do NOT guess at a full inventory of the photo. Only restock-worthy "
    "things.\n"
    "- Nothing legible or nothing running low: return an empty candidates "
    "list. An empty answer is correct and useful."
)

_MAX_CANDIDATES = 25


def extract_items_from_photo(image_b64: str, mime: str, caption: str = '') -> dict:
    """One photo -> staged shopping candidates.

    Runs on the VISION tier (flash first, then lite; gemma is text-only and
    never sees images), same as intake's vision capture.

    Returns {'candidates': [...], 'kind': str, 'error': str|None}.
    """
    from services import model_pools
    out = {'candidates': [], 'kind': 'other', 'error': None}
    settings = storage.get_settings() or {}
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key:
        out['error'] = 'no LLM API key configured'
        return out

    prompt = ("The attached image was taken to help build a family shopping "
              "list. Decide which kind of photo it is, then extract "
              "candidates.")
    if caption:
        prompt += f"\nThe person's note: {caption}"

    try:
        res = model_pools.call_pool_json(
            'vision', api_key, EXTRACTION_SYSTEM, prompt, temperature=0.1,
            timeout_s=90, settings=settings,
            images=[{'mime': mime or 'image/jpeg', 'b64': image_b64}])
        if not isinstance(res, dict):
            raise RuntimeError('bad response')
        if res.get('error'):
            raise RuntimeError(str(res['error']))
    except Exception as e:
        out['error'] = f'could not read the photo ({e})'
        return out

    kind = str(res.get('kind') or 'other').strip().lower()
    out['kind'] = kind if kind in ('handwritten', 'shelf', 'packages',
                                   'receipt', 'other') else 'other'
    raw = res.get('candidates')
    seen = set()
    for c in (raw if isinstance(raw, list) else [])[:_MAX_CANDIDATES]:
        if not isinstance(c, dict):
            continue
        name = str(c.get('name') or '').strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        qty = c.get('qty')
        out['candidates'].append({
            'name': name[:80],
            'qty': (str(qty).strip()[:40] or None) if qty else None,
            'suggested': bool(c.get('suggested', True)),
            'why': str(c.get('why') or '').strip()[:120],
        })
    return out


def already_on_list(list_id: str, candidates: list) -> list:
    """Flag candidates already open on the list so the picker can grey them
    out instead of silently deduping them at add time."""
    open_names = {(i.get('name') or '').strip().lower()
                  for i in storage.get_shopping_items(list_id, include_checked=False)}
    for c in candidates:
        c['already'] = (c.get('name') or '').strip().lower() in open_names
        if c['already']:
            c['suggested'] = False
    return candidates

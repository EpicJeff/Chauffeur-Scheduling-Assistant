"""Occasions — holidays, birthdays, parties (arc O1).

The load in a holiday is PLANNING: what to feed sixteen people, what a shark
party needs, what has to be bought by when, and who is doing all of it. It is
not storage and it is not visibility, which is why this module deliberately
does not implement a container.

An occasion owns nothing. Errands, shopping lists, trips and plates keep their
existing homes, their existing capture paths and their existing engines; the
occasion carries an anchor date, a window, a headcount and a set of dish tags,
and it gets passed IN to the things that generate work.

Two rules hold the design together (docs/occasion_design.md):

1. **Membership attaches to the coarsest entity the occasion wholly owns.**
   Tag the list, the trip, the errand — never the individual item. The one
   documented exception is `ShoppingItem.occasion_id`, for the standing
   grocery list, which is a container the occasion owns only part of.
2. **Eligibility is not selection.** A window makes occasion dishes available;
   a specific plate is what chooses them. Thanksgiving week is Wednesday to
   Sunday and exactly one meal in it is The Meal — Friday lunch is sandwiches.
"""

import datetime
import time
import uuid
from typing import List, Optional

from services import storage

KINDS = ('thanksgiving', 'christmas', 'easter', 'birthday', 'party', 'gathering')


def _today() -> datetime.date:
    return datetime.date.today()


def _d(s) -> Optional[datetime.date]:
    try:
        return datetime.date.fromisoformat(str(s))
    except (TypeError, ValueError):
        return None


def window(occasion: dict) -> tuple:
    """(start, end) as dates. An occasion with no explicit window is its own
    anchor day — never an empty range, which would make every "is this in the
    window" test silently false."""
    anchor = _d(occasion.get('anchor_date')) or _today()
    return (_d(occasion.get('window_start')) or anchor,
            _d(occasion.get('window_end')) or anchor)


def covers(occasion: dict, day) -> bool:
    lo, hi = window(occasion)
    d = _d(day) if not isinstance(day, datetime.date) else day
    return bool(d and lo <= d <= hi)


def active_on(day=None, occasions: List[dict] = None) -> List[dict]:
    """Every occasion whose window covers this day, soonest anchor first."""
    d = _d(day) if day and not isinstance(day, datetime.date) else (day or _today())
    rows = occasions if occasions is not None else storage.get_occasions()
    return [o for o in rows if covers(o, d)]


def dish_tags_for(day=None) -> set:
    """Which repertoire tags are in play on this day.

    ELIGIBILITY ONLY. This never puts a dish on a plate — it says the turkey
    is allowed to be chosen this week, which is a different statement from
    proposing turkey for four days running.
    """
    out = set()
    for o in active_on(day):
        out |= {str(t).strip().lower() for t in (o.get('dish_tags') or []) if str(t).strip()}
    return out


def create(title: str, anchor_date: str, kind: str = 'gathering',
           window_start: str = None, window_end: str = None,
           dish_tags: List[str] = None, notes: str = None,
           cooks: int = None) -> dict:
    """A new occasion, linked to last year's if one is recognisable.

    The carryover link is made HERE rather than asked for later, because the
    gap report's only way to surface an absence is a diff against the prior
    instance — and nobody goes back to fill in a "same as last year" field.
    """
    from models.schemas import Occasion
    anchor = _d(anchor_date) or _today()
    rec = Occasion(title=(title or '').strip() or 'Occasion',
                   kind=(kind if kind in KINDS else 'gathering'),
                   anchor_date=anchor.isoformat(),
                   window_start=window_start, window_end=window_end,
                   dish_tags=[str(t).strip().lower() for t in (dish_tags or [])
                              if str(t).strip()],
                   cooks=cooks, notes=notes,
                   prior_occasion_id=(find_prior(kind, title, anchor) or {}).get('id'),
                   ).model_dump()
    storage.save_occasion(rec)
    return rec


def find_prior(kind: str, title: str, anchor: datetime.date) -> Optional[dict]:
    """Last year's instance of the same thing.

    Matched on KIND first and title-word overlap second, and only ever
    backwards in time. A wrong link is worse than none — it would make the gap
    report compare Thanksgiving against a birthday — so the bar is match or
    nothing, never nearest.
    """
    words = {w for w in str(title or '').lower().split() if len(w) > 3
             and not w.isdigit()}
    best = None
    for o in storage.get_occasions(include_done=True):
        d = _d(o.get('anchor_date'))
        if not d or d >= anchor:
            continue
        if kind and kind != 'gathering' and o.get('kind') == kind:
            pass
        elif words and words & {w for w in str(o.get('title') or '').lower().split()}:
            pass
        else:
            continue
        if best is None or (_d(best['anchor_date']) or datetime.date.min) < d:
            best = o
    return best


def headcount(occasion_id: str) -> int:
    """Everyone eating: the family plus every guest's own count.

    Guests carry a headcount rather than one row each because "the Wilsons, 4"
    is how people actually answer, and making somebody type four rows to say
    it is the data entry this arc exists to avoid.
    """
    fam = len([m for m in storage.get_all_members()
               if (m.get('role') or '') != 'helper'])
    guests = sum(max(1, int(g.get('headcount') or 1))
                 for g in storage.get_occasion_guests(occasion_id)
                 if not g.get('member_id'))
    return fam + guests


def guest_diet(occasion_id: str) -> tuple:
    """(hard_avoid, soft_dislike) across the guests.

    Mirrors `meals._eater_diet` exactly — allergies hard, preferences soft —
    because a guest's allergy has to bind the same way a family member's does
    or the guest list is decorative.
    """
    avoid, dislike = set(), set()
    for g in storage.get_occasion_guests(occasion_id):
        avoid |= {str(t).strip().lower() for t in (g.get('dietary_avoid') or [])
                  if str(t).strip()}
        dislike |= {str(t).strip().lower() for t in (g.get('dietary_dislike') or [])
                    if str(t).strip()}
    return avoid, dislike


def diet_on(day=None) -> tuple:
    """The guest diet for whichever occasions cover this day."""
    avoid, dislike = set(), set()
    for o in active_on(day):
        a, d = guest_diet(o['id'])
        avoid |= a
        dislike |= d
    return avoid, dislike


def add_guest(occasion_id: str, name: str, headcount_n: int = 1,
              member_id: str = None, dietary_avoid: List[str] = None,
              dietary_dislike: List[str] = None, staying_over: bool = False,
              notes: str = None) -> dict:
    from models.schemas import OccasionGuest
    rec = OccasionGuest(
        occasion_id=occasion_id, name=(name or '').strip() or 'Guest',
        member_id=member_id, headcount=max(1, int(headcount_n or 1)),
        dietary_avoid=[str(t).strip().lower() for t in (dietary_avoid or []) if str(t).strip()],
        dietary_dislike=[str(t).strip().lower() for t in (dietary_dislike or []) if str(t).strip()],
        staying_over=bool(staying_over), notes=notes).model_dump()
    storage.save_occasion_guest(rec)
    return rec


def contents(occasion_id: str) -> dict:
    """Everything tagged with this occasion, gathered by DERIVATION.

    Nothing here is stored on the occasion. This is a query across the homes
    each thing already lives in, which is what keeps the occasion from being a
    second copy that can drift.
    """
    o = storage.get_occasion(occasion_id)
    if not o:
        return {}
    lists = [l for l in storage.get_shopping_lists()
             if l.get('occasion_id') == occasion_id]
    # The documented exception: items on a list the occasion does NOT own —
    # the turkey sitting on the standing grocery list, which is where it
    # belongs and where it will actually be bought.
    loose = [i for i in storage.get_shopping_items()
             if i.get('occasion_id') == occasion_id
             and i.get('list_id') not in {l['id'] for l in lists}]
    errands = [e for e in storage.get_all_errands()
               if e.get('occasion_id') == occasion_id]
    trips = [t for t in storage.get_all_trip_metadata()
             if t.get('occasion_id') == occasion_id]
    guests = storage.get_occasion_guests(occasion_id)
    lo, hi = window(o)
    return {
        'occasion': o, 'window': [lo.isoformat(), hi.isoformat()],
        'days_away': (_d(o['anchor_date']) - _today()).days if _d(o['anchor_date']) else None,
        'lists': lists, 'loose_items': loose, 'errands': errands,
        'trips': trips, 'guests': guests,
        'headcount': headcount(occasion_id),
    }


# --- Templates: an INTERVIEW, not a checklist (O2) ---------------------------
#
# This is the difference between planning help and a form. Each answer
# GENERATES logistics rather than recording them — "how many are coming?"
# cascades into scaling, shopping and oven capacity; "anyone staying over?"
# produces beds, towels and an errand.
#
# Work is stamped at OFFSETS from the anchor, because `Errand` already
# expresses a deadline as `starts_on` + `window_days`, so this is arithmetic
# against shipped primitives rather than new solver work.
#
# Deliberately static data, never an LLM call: a family answering the same
# question twice must get the same cascade, and a template that drifts is one
# nobody can trust as a diff baseline.

_ASK = {
    'headcount': ("How many are you feeding?",
                  "Everybody, your own family included."),
    'staying_over': ("Is anyone staying the night?", None),
    'cooking_hands': ("How many of you will be cooking?", None),
    'travelling': ("Are you travelling for it, or are they coming to you?", None),
    'cake': ("Is there a cake?", None),
    'gifts': ("Are there presents to buy?", None),
    'theme': ("Does it have a theme?", "Sharks, dinosaurs, whatever it is."),
}

_COMMON = [
    {'key': 'headcount', 'ask': 'headcount', 'kind': 'number'},
    {'key': 'cooking_hands', 'ask': 'cooking_hands', 'kind': 'number'},
]

TEMPLATES = {
    'thanksgiving': {
        'dish_tags': ['thanksgiving'],
        'questions': _COMMON + [
            {'key': 'staying_over', 'ask': 'staying_over', 'kind': 'yesno'},
        ],
        'checklist': [
            {'key': 'food_shop', 'label': 'Shop for the meal', 'type': 'errand',
             'offset_days': -4, 'location': 'Grocery', 'duration_mins': 90},
            {'key': 'turkey_thaw', 'label': 'Turkey out to thaw',
             'type': 'note', 'offset_days': -4},
            {'key': 'house', 'label': 'Tidy the house', 'type': 'errand',
             'offset_days': -1, 'location': 'Home', 'duration_mins': 60},
            {'key': 'beds', 'label': 'Beds and towels for guests', 'type': 'note',
             'offset_days': -1, 'needs': 'staying_over'},
        ],
    },
    'christmas': {
        'dish_tags': ['christmas'],
        'questions': _COMMON + [
            {'key': 'gifts', 'ask': 'gifts', 'kind': 'yesno'},
            {'key': 'travelling', 'ask': 'travelling', 'kind': 'yesno'},
            {'key': 'staying_over', 'ask': 'staying_over', 'kind': 'yesno'},
        ],
        'checklist': [
            {'key': 'food_shop', 'label': 'Shop for the meal', 'type': 'errand',
             'offset_days': -3, 'location': 'Grocery', 'duration_mins': 90},
            {'key': 'gifts', 'label': 'Presents', 'type': 'note',
             'offset_days': -14, 'needs': 'gifts'},
            {'key': 'beds', 'label': 'Beds and towels for guests', 'type': 'note',
             'offset_days': -1, 'needs': 'staying_over'},
        ],
    },
    'birthday': {
        'dish_tags': ['birthday'],
        'questions': _COMMON + [
            {'key': 'cake', 'ask': 'cake', 'kind': 'yesno'},
            {'key': 'theme', 'ask': 'theme', 'kind': 'text'},
            {'key': 'gifts', 'ask': 'gifts', 'kind': 'yesno'},
        ],
        'checklist': [
            {'key': 'cake', 'label': 'Order and collect the cake', 'type': 'errand',
             'offset_days': -1, 'location': 'Bakery', 'duration_mins': 20,
             'needs': 'cake'},
            {'key': 'party_supplies', 'label': 'Party supplies', 'type': 'list',
             'offset_days': -5, 'sourcing': 'party supplies and decorations'},
            {'key': 'gifts', 'label': 'Presents', 'type': 'note',
             'offset_days': -7, 'needs': 'gifts'},
        ],
    },
    'party': {
        'dish_tags': [],
        'questions': _COMMON + [
            {'key': 'theme', 'ask': 'theme', 'kind': 'text'},
        ],
        'checklist': [
            {'key': 'party_supplies', 'label': 'Party supplies', 'type': 'list',
             'offset_days': -4, 'sourcing': 'party supplies and decorations'},
            {'key': 'food_shop', 'label': 'Shop for the food', 'type': 'errand',
             'offset_days': -2, 'location': 'Grocery', 'duration_mins': 60},
            {'key': 'house', 'label': 'Tidy the house', 'type': 'errand',
             'offset_days': -1, 'location': 'Home', 'duration_mins': 45},
        ],
    },
    'gathering': {
        'dish_tags': [],
        'questions': _COMMON,
        'checklist': [
            {'key': 'food_shop', 'label': 'Shop for the food', 'type': 'errand',
             'offset_days': -2, 'location': 'Grocery', 'duration_mins': 60},
        ],
    },
}
TEMPLATES['easter'] = TEMPLATES['gathering']


def template_for(occasion: dict) -> dict:
    return TEMPLATES.get(occasion.get('kind') or 'gathering', TEMPLATES['gathering'])


def _needed(line: dict, answers: dict) -> bool:
    """A checklist line gated on an answer only counts once that answer is YES.

    Unanswered is NOT no: a family that has not been asked about a cake yet
    should not be told they are missing one — that is how a gap report becomes
    noise instead of a signal.
    """
    need = line.get('needs')
    if not need:
        return True
    return bool(answers.get(need))


def interview(occasion_id: str) -> dict:
    """The questions still unanswered, in order, with what each one unlocks."""
    o = storage.get_occasion(occasion_id)
    if not o:
        return {}
    answers = o.get('answers') or {}
    tpl = template_for(o)
    out = []
    for q in tpl['questions']:
        if q['key'] in answers:
            continue
        ask, hint = _ASK.get(q.get('ask') or q['key'], (q['key'], None))
        out.append({'key': q['key'], 'kind': q['kind'], 'ask': ask, 'hint': hint})
    return {'occasion_id': occasion_id, 'questions': out,
            'answered': answers, 'done': not out}


def answer(occasion_id: str, key: str, value) -> dict:
    """Record one answer and let it cascade.

    Headcount is the clearest case: answering it does not store a number, it
    scales every plate in the window, which is the difference between an
    interview and a form.
    """
    o = storage.get_occasion(occasion_id)
    if not o:
        return {'error': 'no such occasion'}
    answers = dict(o.get('answers') or {})
    answers[key] = value
    patch = {'answers': answers}
    if key == 'cooking_hands':
        try:
            patch['cooks'] = max(1, int(value))
        except (TypeError, ValueError):
            pass
    storage.update_occasion(occasion_id, patch)

    generated = []
    if key == 'headcount':
        generated += _apply_headcount(occasion_id, value)
    return {'occasion_id': occasion_id, 'answers': answers,
            'generated': generated, 'next': interview(occasion_id)}


def _apply_headcount(occasion_id: str, value) -> List[str]:
    """Headcount reaches the kitchen, which is the whole point of asking.

    Only days inside the window, and only days the family has not already
    marked themselves — an answer to a general question must not overwrite a
    specific statement somebody made about one night.
    """
    from services import meals
    o = storage.get_occasion(occasion_id)
    try:
        n = max(1, int(value))
    except (TypeError, ValueError):
        return []
    lo, hi = window(o)
    out, day = [], lo
    while day <= hi:
        saved = storage.get_plate(day.isoformat()) or {}
        if not saved.get('serving_for'):
            meals.set_plate_hosting(day.isoformat(), n, o.get('cooks') or 0)
            out.append(f"cooking for {n} on {day.isoformat()}")
        day += datetime.timedelta(days=1)
    return out


def apply_template(occasion_id: str, keys: List[str] = None) -> dict:
    """Stamp the template's work at its offsets from the anchor.

    Errands land as real errands with a real deadline: `starts_on` at the
    offset and `window_days` carrying it to the anchor, which is exactly how
    the intake arc already expresses "due by". Nothing new in the solver.
    """
    from models.schemas import Errand
    o = storage.get_occasion(occasion_id)
    if not o:
        return {'error': 'no such occasion'}
    anchor = _d(o['anchor_date']) or _today()
    answers = o.get('answers') or {}
    have = {e.get('occasion_key') for e in storage.get_all_errands()
            if e.get('occasion_id') == occasion_id}
    have |= {l.get('occasion_key') for l in storage.get_shopping_lists()
             if l.get('occasion_id') == occasion_id}
    made = []
    for line in template_for(o)['checklist']:
        if keys and line['key'] not in keys:
            continue
        if line['key'] in have or line['key'] in (o.get('dismissed') or []):
            continue
        if not _needed(line, answers):
            continue
        if line['type'] != 'errand':
            continue           # notes are report lines; lists come from sourcing
        due = anchor + datetime.timedelta(days=int(line.get('offset_days') or 0))
        start = min(due, _today())
        rec = Errand(title=f"{line['label']} — {o['title']}",
                     duration_mins=int(line.get('duration_mins') or 30),
                     location=line.get('location') or 'Home',
                     starts_on=time.mktime(start.timetuple()),
                     window_days=max(1, (due - start).days + 1),
                     occasion_id=occasion_id,
                     occasion_key=line['key']).model_dump()
        storage.add_errand(rec)
        made.append(rec)
    return {'created': made}


def gap_report(occasion_id: str) -> dict:
    """What is missing, not what is there.

    A list of what exists cannot answer "have I forgotten anything" — it shows
    what somebody remembered to add, and the gap is invisible by construction.
    Nine tidy green rows manufacture confidence about the exact thing being
    worried about. So this is a DIFF: against the template, and against last
    year's instance.

    Sorted by SLACK against the anchor and carrying no percentage. Six of
    fourteen presents unbought is fine in October and an emergency on the 23rd;
    one number cannot say both.
    """
    o = storage.get_occasion(occasion_id)
    if not o:
        return {}
    anchor = _d(o['anchor_date']) or _today()
    answers = o.get('answers') or {}
    dismissed = set(o.get('dismissed') or [])
    c = contents(occasion_id)
    covered = {e.get('occasion_key') for e in c['errands'] if e.get('occasion_key')}
    covered |= {l.get('occasion_key') for l in c['lists'] if l.get('occasion_key')}

    gaps = []
    for line in template_for(o)['checklist']:
        if line['key'] in covered or line['key'] in dismissed:
            continue
        if not _needed(line, answers):
            continue
        due = anchor + datetime.timedelta(days=int(line.get('offset_days') or 0))
        gaps.append({'key': line['key'], 'label': line['label'],
                     'type': line['type'], 'due': due.isoformat(),
                     'slack_days': (due - _today()).days,
                     'source': 'template',
                     'sourcing': line.get('sourcing')})

    # Last year is the only thing that can surface an absence the template
    # never knew about — the rented tables nobody thought to model.
    prior_id = o.get('prior_occasion_id')
    if prior_id:
        prior = contents(prior_id) or {}
        mine = {(e.get('title') or '').lower() for e in c['errands']}
        mine |= {(l.get('name') or '').lower() for l in c['lists']}
        prior_title = (prior.get('occasion') or {}).get('title') or 'last time'
        for e in (prior.get('errands') or []):
            stem = (e.get('title') or '').split('—')[0].strip().lower()
            if stem and not any(stem in m for m in mine):
                gaps.append({'key': 'prior:' + e['id'], 'label': stem,
                             'type': 'errand', 'due': anchor.isoformat(),
                             'slack_days': (anchor - _today()).days,
                             'source': 'prior', 'note': f"{prior_title} had this"})
        for l in (prior.get('lists') or []):
            nm = (l.get('name') or '').strip().lower()
            if nm and not any(nm in m for m in mine):
                gaps.append({'key': 'prior:' + l['id'], 'label': nm,
                             'type': 'list', 'due': anchor.isoformat(),
                             'slack_days': (anchor - _today()).days,
                             'source': 'prior', 'note': f"{prior_title} had this"})

    gaps.sort(key=lambda g: g['slack_days'])
    unanswered = interview(occasion_id).get('questions') or []
    return {'occasion': o, 'gaps': gaps, 'questions': unanswered,
            'days_away': (anchor - _today()).days,
            'has_prior': bool(prior_id)}


def dismiss(occasion_id: str, key: str) -> bool:
    """"No cake this year." A gap report that keeps raising a settled decision
    stops being read, which costs more than the line was ever worth."""
    o = storage.get_occasion(occasion_id)
    if not o:
        return False
    keys = list(o.get('dismissed') or [])
    if key not in keys:
        keys.append(key)
    return storage.update_occasion(occasion_id, {'dismissed': keys})


_SOURCING_SYSTEM = (
    "You turn a family's description of something they need to buy for an "
    "occasion into a flat SHOPPING LIST. Reply with STRICT JSON only, no "
    "prose, no code fences.\n\n"
    "Schema: {\"items\": [{\"name\": str, \"qty\": str|null, \"note\": str|null}]}\n\n"
    "- Concrete, buyable things a real shop stocks. 'blue paper plates', not "
    "'party supplies'. Somebody has to find it on a shelf or in a search box.\n"
    "- qty is FREE TEXT and optional ('2 packs', '16'). Never invent precision "
    "you were not given.\n"
    "- Scale to the headcount you are told, and say the count in qty where it "
    "matters ('16 favour bags').\n"
    "- 8 to 16 items. Cover the obvious things a person would forget, but do "
    "NOT pad: no generic 'napkins' filler when the request is specific.\n"
    "- note is a SHORT reason only when it is not obvious. Usually null.\n"
    "- No food unless the request asks for food."
)


def generate_list(occasion_id: str, request: str, list_name: str = None,
                  store: str = None, added_by: str = None) -> dict:
    """"I need party favours for a shark party" → a real list, ready for a cart.

    The generated list is OWNED by the occasion (list-level membership), which
    is what makes every later item added to it belong to the party too, from
    whichever page somebody happens to be standing on.
    """
    from models.schemas import ShoppingList, ShoppingItem
    from services import model_pools
    o = storage.get_occasion(occasion_id)
    if not o:
        return {'error': 'no such occasion'}
    raw = (request or '').strip()
    settings = storage.get_settings() or {}
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key or not raw:
        return {'error': 'no LLM API key configured' if not api_key
                else 'say what you need'}
    n = headcount(occasion_id)
    try:
        res = model_pools.call_pool_json(
            'interactive', api_key, _SOURCING_SYSTEM,
            f"Occasion: {o['title']} ({o.get('kind')}), about {n} people. "
            f"They need: {raw}",
            temperature=0.3, timeout_s=45, settings=settings)
        if not isinstance(res, dict) or res.get('error'):
            raise RuntimeError(res.get('error') if isinstance(res, dict) else 'bad response')
    except Exception as e:
        print(f"[occasions] sourcing failed for {raw!r}: {e}")
        return {'error': 'could not work that out'}

    lst = ShoppingList(name=(list_name or raw)[:60], store=store,
                       occasion_id=occasion_id).model_dump()
    storage.add_shopping_list(lst)
    added, seen = [], set()
    for it in (res.get('items') or [])[:25]:
        if not isinstance(it, dict):
            continue
        nm = str(it.get('name') or '').strip()[:80]
        if not nm or nm.lower() in seen:
            continue
        seen.add(nm.lower())
        rec = ShoppingItem(list_id=lst['id'], name=nm,
                           qty=str(it.get('qty') or '').strip()[:24] or None,
                           note=str(it.get('note') or '').strip()[:120] or None,
                           added_by=added_by, added_via='agent').model_dump()
        storage.add_shopping_item(rec)
        added.append(rec)
    return {'list': lst, 'items': added, 'headcount': n}


def set_status(occasion_id: str, status: str) -> bool:
    return storage.update_occasion(
        occasion_id, {'status': 'done' if status == 'done' else 'planning'})

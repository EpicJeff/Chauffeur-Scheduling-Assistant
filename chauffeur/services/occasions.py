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
import re
import time
import uuid
from typing import List, Optional

from services import storage

KINDS = ('thanksgiving', 'christmas', 'easter', 'birthday', 'party', 'gathering',
         # Supply intake A4: the INVERSE of every kind above. Those are all
         # host-side — headcount, cooking hands, tidy the house. Being invited
         # to somebody else's is one child, no kitchen, and somewhere that is
         # not home; the only work is a present and getting there.
         'invited')


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


def attends_by_default(member: dict, kind: str = None) -> bool:
    """Whether a household member is assumed in until somebody says otherwise.

    Role is the only signal the app has: `helper` is external by definition (a
    hired driver or nanny — driving surfaces only), so they start OUT; everyone
    else starts IN. It is deliberately a DEFAULT and not a rule — a helper who
    is genuinely invited to the party is one tap away, and so is a parent who
    will be travelling that week.

    What role cannot tell us is who lives elsewhere: an `adult` grandparent
    five hundred miles away looks exactly like a resident adult. That is
    precisely why every member is individually togglable rather than derived.

    **A4 inverts it for `invited`**: the household is not hosting, so nobody
    is in until somebody says who was asked. Defaulting the whole family in
    would report six people going to a classmate's party and would feed a
    meaningless headcount to everything downstream.
    """
    if kind == 'invited':
        return False
    return (member.get('role') or 'adult') != 'helper'


def attendance(occasion_id: str) -> List[dict]:
    """Every household member with their attendance for this occasion.

    Returns the whole roster, not just the attendees: a list you can only add
    to cannot express "Grandad isn't coming this year", and that absence was
    the original defect.
    """
    o = storage.get_occasion(occasion_id) or {}
    saved = o.get('attendance') or {}
    out = []
    for m in storage.get_all_members():
        default = attends_by_default(m, o.get('kind'))
        decided = m['id'] in saved
        out.append({'member_id': m['id'], 'name': m.get('name') or 'Someone',
                    'role': m.get('role') or 'adult',
                    'attending': bool(saved[m['id']]) if decided else default,
                    'decided': decided, 'default': default})
    out.sort(key=lambda r: (not r['attending'], r['name'].lower()))
    return out


def set_attendance(occasion_id: str, member_id: str, attending: bool) -> List[dict]:
    """One member, in or out. Recorded explicitly even when it matches the
    default, because "we thought about it and yes" and "nobody has said" are
    different states — the second one is what the gap report is allowed to ask
    about."""
    o = storage.get_occasion(occasion_id)
    if not o:
        return []
    saved = dict(o.get('attendance') or {})
    saved[member_id] = bool(attending)
    storage.update_occasion(occasion_id, {'attendance': saved})
    return attendance(occasion_id)


def headcount(occasion_id: str) -> int:
    """Everyone eating: the household members coming, plus every guest's count.

    Guests carry a headcount rather than one row each because "the Wilsons, 4"
    is how people actually answer, and making somebody type four rows to say it
    is the data entry this arc exists to avoid.

    A guest row that names a `member_id` is that member, so it must not be
    counted twice — the roster already has them.
    """
    fam = len([a for a in attendance(occasion_id) if a['attending']])
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
        'attendance': attendance(occasion_id),
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
    # A4. Deliberately three questions and no more: an invitation is a small
    # thing and an interview that outlasts the event is worse than no help.
    'whose_party': ("Whose party is it?", "The birthday child's name."),
    'their_age': ("How old are they turning?",
                  "Roughly is fine — it decides what a good present is."),
    'gift_budget': ("What's the budget for the present?",
                    "A number in dollars. It filters what gets suggested."),
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
    # A4 — the one template that is not about hosting.
    #
    # No `_COMMON`, and that is the whole point: headcount and cooking hands
    # are host questions, and answering headcount CASCADES into scaling every
    # plate in the window (`_apply_headcount`). Asking them here would have
    # the app cook for twelve because a child was invited to a party.
    #
    # The gift is a LIST line and not an errand, which departs from the brief
    # on purpose: an errand needs a location the app does not have (nobody
    # knows yet which shop), while a dated item on a list is exactly what A2
    # now notices and offers a trip for. The machinery that shipped two
    # slices ago is a better answer than a made-up "Home" errand.
    'invited': {
        'dish_tags': [],
        'questions': [
            {'key': 'whose_party', 'ask': 'whose_party', 'kind': 'text'},
            {'key': 'their_age', 'ask': 'their_age', 'kind': 'number'},
            {'key': 'gift_budget', 'ask': 'gift_budget', 'kind': 'number'},
        ],
        'checklist': [
            {'key': 'gift', 'label': 'A present', 'type': 'list',
             'offset_days': -3, 'sourcing': 'a birthday present'},
            # Its own line because it is the thing actually forgotten — the
            # present gets bought and then handed over in the shop bag.
            {'key': 'wrapping', 'label': 'Wrapping paper and a card',
             'type': 'note', 'offset_days': -1},
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


# --- The menu (O1b, 2026-08-07) ----------------------------------------------
#
# The gap this closes, in the family's words: there was nowhere to view an
# occasion's menu, and no way to curate one ahead of time in isolation from the
# day-to-day list.
#
# The brief deferred menu SELECTION to `set_plate_lock`, "one plate at a time",
# which was right about the mechanism and wrong about the reach: by hand, a
# plate is only editable through the week strip, and the week strip covers the
# next grocery window — a few days. A Thanksgiving menu three weeks out was
# reachable by voice (`plan_specific_dinner`) and by nothing else, which is the
# hand-path rule broken in the one place it mattered most.
#
# So this is a VIEW and an EDITOR over machinery that already existed. It
# stores nothing of its own: the menu IS the locked plate on the meal date,
# which is why it survives a bulk repropose and why the run sheet, the shopping
# drain and the kitchen totals all already understand it.


def meal_date(occasion: dict) -> str:
    """Which day the menu is for. The anchor is The Meal unless somebody has
    said otherwise — Thanksgiving week is five days and exactly one of them is
    the dinner everybody means."""
    return (occasion.get('anchor_date')
            or (occasion.get('window_start') or _today().isoformat()))


def menu(occasion_id: str, date_str: str = None) -> dict:
    """The occasion's menu, plus what it costs to cook.

    Returns the kitchen consequences alongside the dishes on purpose: choosing
    a menu and discovering it needs two ovens are the same decision, and
    splitting them across two screens is how a family finds out on the day.
    """
    from services import meals
    o = storage.get_occasion(occasion_id)
    if not o:
        return {}
    day = date_str or meal_date(o)
    plate = storage.get_plate(day) or {}
    dishes = storage.get_dishes_by_ids(
        [i['dish_id'] for i in (plate.get('items') or [])])
    totals = meals.plate_totals(dishes, day, plate=plate) if dishes else {}
    tags = {str(t).strip().lower() for t in (o.get('dish_tags') or [])}
    # What this occasion could draw on: its own dishes plus the everyday pool.
    # Occasion dishes belonging to a DIFFERENT occasion are left out — the
    # birthday cake has no business in the Thanksgiving picker.
    pool = []
    for d in storage.get_dishes():
        scope = str(d.get('scope') or 'everyday')
        if scope != 'occasion':
            pool.append(d)
            continue
        dtags = {str(t).strip().lower() for t in (d.get('tags') or [])}
        if not tags or (dtags & tags):
            pool.append(d)
    return {
        'occasion_id': occasion_id, 'date': day,
        'locked': bool(plate.get('locked')), 'note': plate.get('note'),
        'dishes': dishes, 'pool': pool,
        'serving_for': plate.get('serving_for'), 'cooks': plate.get('cooks'),
        'prep_ahead_mins': totals.get('prep_ahead_mins') or 0,
        'finish_mins': totals.get('finish_mins') or 0,
        'unattended_mins': totals.get('unattended_mins') or 0,
        'oven_conflicts': totals.get('oven_conflicts') or [],
    }


def set_menu(occasion_id: str, dish_ids: List[str], date_str: str = None) -> dict:
    """Pin these dishes to the occasion's meal.

    LOCKED, not merely edited: a menu chosen three weeks out is exactly the
    case `locked` was invented for — "this is Mom's birthday dinner" — and an
    ordinary edit would let a bulk repropose sweep it away a week early.
    """
    from services import meals
    o = storage.get_occasion(occasion_id)
    if not o:
        return {'error': 'no such occasion'}
    day = date_str or meal_date(o)
    meals.set_plate_lock(day, True, o.get('title'), list(dish_ids or []))
    return menu(occasion_id, day)


def clear_menu(occasion_id: str, date_str: str = None) -> dict:
    """Release the night entirely, back to whatever the composer would say."""
    from services import meals
    o = storage.get_occasion(occasion_id)
    if not o:
        return {'error': 'no such occasion'}
    day = date_str or meal_date(o)
    meals.reset_plate(day, force=True)
    return menu(occasion_id, day)


def add_dishes(occasion_id: str, description: str) -> dict:
    """Add dishes that belong to THIS occasion and nowhere else.

    The whole point: curating a Thanksgiving menu must not put turkey, stuffing
    and cranberry sauce into the list a family looks at on a Tuesday. Anything
    added here is born `scope='occasion'` carrying the occasion's tags, so it is
    eligible inside the window and invisible outside it — the same treatment the
    per-dish toggle applies, without anybody having to remember to apply it.
    """
    from services import meals
    o = storage.get_occasion(occasion_id)
    if not o:
        return {'error': 'no such occasion'}
    res = meals.add_dishes_from_text(description)
    if res.get('error'):
        return res
    tags = [str(t).strip().lower() for t in (o.get('dish_tags') or [])
            if str(t).strip()]
    if not tags:
        # An occasion with no tags of its own still needs its dishes marked, or
        # they fall back into the everyday pool the moment they are saved.
        tags = [(o.get('kind') or 'occasion').lower()]
        storage.update_occasion(occasion_id, {'dish_tags': tags})
    for d in (res.get('added') or []):
        merged = sorted({*(d.get('tags') or []), *tags})
        storage.update_dish(d['id'], {'scope': 'occasion', 'tags': merged})
        d['scope'], d['tags'] = 'occasion', merged
    return res


# --- O3: the planning intelligence -------------------------------------------
#
# Everything above this line is nouns, and every noun is a logistics noun. What
# makes this PLANNING help is what the app says unprompted, using what only it
# knows: where everyone is, who is driving, where the schedule has slack, how
# this family cooks, and what happened last year.
#
# Every finding here is guarded and fails silent. An insight that throws is
# worse than one that never appears.

def _sched():
    try:
        return storage.get_cached_schedule() or {}
    except Exception:
        return {}


def _load_balance(occasion_id: str) -> Optional[dict]:
    """Who is carrying this.

    The research this arc came from is about WHO carries the load, and the app
    has roles, assignment and a chore ledger. Every other product in this
    space ships a shared checklist and calls that equity — naming the
    imbalance is the actual intervention, and Chauffeur is the only thing in
    the house with the data to name it.

    Stated, never scored (the kid arc's calm-voice rule applies to adults).
    """
    errands = [e for e in storage.get_all_errands()
               if e.get('occasion_id') == occasion_id and not e.get('is_completed')]
    if len(errands) < 4:
        return None            # three items is not a fairness problem
    sched = _sched()
    assigns = sched.get('assignments') or {}
    by_id = {}
    for ev in (sched.get('events') or []):
        if ev.get('event_type') == 'errand':
            by_id[str(ev.get('id'))] = assigns.get(ev.get('id'))
    who = {}
    for e in errands:
        drv = None
        for eid, d in by_id.items():
            if e['id'] in eid:
                drv = d
                break
        if not drv:
            req = e.get('required_drivers') or []
            drv = req[0] if len(req) == 1 else None
        if drv:
            who[drv] = who.get(drv, 0) + 1
    if not who or len(who) < 2:
        # One name or none is not an imbalance to report — it is either a
        # solo effort nobody has divided yet or a schedule not yet solved.
        total = sum(who.values())
        if total and total >= 4 and len(who) == 1:
            name = next(iter(who))
            return {'kind': 'load', 'who': name, 'share': total, 'of': len(errands),
                    'text': f"Every one of the {len(errands)} jobs for this is on "
                            f"{name}. Worth splitting a couple before the week gets close."}
        return None
    top, n = max(who.items(), key=lambda kv: kv[1])
    total = sum(who.values())
    if total >= 4 and n / float(total) >= 0.7:
        return {'kind': 'load', 'who': top, 'share': n, 'of': total,
                'text': f"{n} of the {total} assigned jobs for this are {top}'s."}
    return None


def _open_decisions(occasion_id: str) -> List[dict]:
    """Decisions, with a cost that grows.

    Anticipate → identify → DECIDE → monitor. The first three are covered by
    the interview and the gap report; deciding is where people actually stall
    ("are we hosting or driving to Mum's?"). The app cannot decide. Making the
    price of not deciding concrete is most of the value.
    """
    o = storage.get_occasion(occasion_id)
    if not o:
        return []
    anchor = _d(o['anchor_date']) or _today()
    answers = o.get('answers') or {}
    tpl = template_for(o)
    gates = {}
    for line in tpl['checklist']:
        need = line.get('needs')
        if need and need not in answers:
            off = int(line.get('offset_days') or 0)
            if need not in gates or off < gates[need][0]:
                gates[need] = (off, line['label'])
    out = []
    for key, (off, label) in gates.items():
        by = anchor + datetime.timedelta(days=off)
        slack = (by - _today()).days
        ask, _hint = _ASK.get(key, (key, None))
        if slack < 0:
            cost = f"{label} is already past when it wanted doing"
        elif slack == 0:
            cost = f"{label} needs deciding today to still happen"
        else:
            cost = f"leaves {slack} day{'s' if slack != 1 else ''} for {label.lower()}"
        out.append({'kind': 'decision', 'key': key, 'ask': ask,
                    'slack_days': slack, 'text': f"{ask} Deciding now {cost}."})
    out.sort(key=lambda d: d['slack_days'])
    return out


def _busiest_first(days: List[datetime.date]) -> List[tuple]:
    """(day, committed_minutes) for each day, least committed first."""
    sched = _sched()
    mins = {d: 0 for d in days}
    for ev in (sched.get('events') or []):
        if ev.get('all_day') or ev.get('trip_suppressed'):
            continue
        try:
            start = datetime.datetime.fromisoformat(str(ev['start'])[:19])
            end = datetime.datetime.fromisoformat(str(ev['end'])[:19])
        except (KeyError, TypeError, ValueError):
            continue
        if start.date() in mins:
            mins[start.date()] += max(0, int((end - start).total_seconds() // 60))
    return sorted(mins.items(), key=lambda kv: kv[1])


def _when_to_do_it(occasion_id: str) -> Optional[dict]:
    """Not "buy the presents by the 20th" but "the only clear afternoon before
    the 20th is Saturday the 13th".

    The solver already knows the slack. This is the app's DNA pointed at a new
    problem, and no checklist can do it.
    """
    o = storage.get_occasion(occasion_id)
    gaps = [g for g in (gap_report(occasion_id).get('gaps') or [])
            if g['slack_days'] >= 0]
    if not o or not gaps:
        return None
    soonest = gaps[0]
    due = _d(soonest['due']) or _today()
    days = []
    d = _today()
    while d <= due and len(days) < 21:
        days.append(d)
        d += datetime.timedelta(days=1)
    if len(days) < 2:
        return None
    ranked = _busiest_first(days)
    if not ranked or ranked[0][1] == ranked[-1][1]:
        return None          # nothing solved, or a genuinely flat week
    best, load = ranked[0]
    return {'kind': 'when', 'day': best.isoformat(), 'busy_mins': load,
            'for': soonest['label'],
            'text': f"{best.strftime('%A the %d')} is the clearest day between "
                    f"now and then — best shot at {soonest['label'].lower()}."}


def _thaw_and_lead(occasion_id: str) -> List[dict]:
    """Deadlines that fall out of the food rather than being typed.

    A bird that needs thawing pushes the BUY date back from the serve date, and
    nobody types that deadline — the meal model already knows. Same for
    anything ordered with a lead time.
    """
    o = storage.get_occasion(occasion_id)
    if not o:
        return []
    lo, hi = window(o)
    out, seen = [], set()
    day = lo
    while day <= hi:
        plate = storage.get_plate(day.isoformat()) or {}
        ids = [i['dish_id'] for i in (plate.get('items') or [])]
        for dish in storage.get_dishes_by_ids(ids):
            nm = dish.get('short_name') or dish.get('name')
            if nm in seen:
                continue
            ahead = str(dish.get('needs_ahead') or 'none')
            if ahead == 'thaw':
                seen.add(nm)
                # A rule of thumb, and it says so: roughly a day in the fridge
                # per four servings, floor of two. The app does not know the
                # weight and must not pretend to.
                lead = max(2, int((dish.get('serves') or 4) / 4.0))
                by = day - datetime.timedelta(days=lead)
                out.append({'kind': 'lead', 'dish': nm, 'by': by.isoformat(),
                            'slack_days': (by - _today()).days,
                            'text': f"{nm} needs thawing — in the fridge by "
                                    f"{by.strftime('%a %d %b')} at the latest "
                                    f"(about {lead} days for that size), so it "
                                    f"has to be bought before then."})
            elif int(dish.get('order_lead_mins') or 0) >= 1440:
                seen.add(nm)
                lead = int(dish['order_lead_mins'] // 1440)
                by = day - datetime.timedelta(days=lead)
                out.append({'kind': 'lead', 'dish': nm, 'by': by.isoformat(),
                            'slack_days': (by - _today()).days,
                            'text': f"{nm} has to be ordered {lead} day"
                                    f"{'s' if lead != 1 else ''} ahead — "
                                    f"by {by.strftime('%a %d %b')}."})
        day += datetime.timedelta(days=1)
    out.sort(key=lambda r: r['slack_days'])
    return out


def _clashes(occasion_id: str) -> List[dict]:
    """"You're hosting sixteen at 2 and you're on pickup for a game that ends
    at 1." Trivial here, invisible to every list app."""
    o = storage.get_occasion(occasion_id)
    if not o:
        return []
    lo, hi = window(o)
    sched = _sched()
    assigns = sched.get('assignments') or {}
    out = []
    for ev in (sched.get('events') or []):
        if ev.get('all_day') or ev.get('event_type') == 'errand':
            continue
        try:
            start = datetime.datetime.fromisoformat(str(ev['start'])[:19])
        except (KeyError, TypeError, ValueError):
            continue
        if not (lo <= start.date() <= hi):
            continue
        # Only the hours a household is actually cooking or hosting.
        if not (10 <= start.hour <= 19):
            continue
        drv = assigns.get(ev.get('id'))
        if not drv:
            continue
        out.append({'kind': 'clash', 'day': start.date().isoformat(),
                    'text': f"{start.strftime('%a %d')}: {drv} is driving "
                            f"{ev.get('title')} at {start.strftime('%H:%M')}, "
                            "which is inside the cooking window."})
    return out[:4]


def insights(occasion_id: str) -> dict:
    """Everything the app can say that a checklist cannot.

    Each block is guarded independently: a broken schedule cache must cost the
    family the one insight that needed it, never the whole panel.
    """
    out = []
    for fn in (_load_balance, _when_to_do_it):
        try:
            r = fn(occasion_id)
            if r:
                out.append(r)
        except Exception as e:                       # pragma: no cover
            print(f"[occasions] insight {fn.__name__} skipped: {e}")
    for fn in (_open_decisions, _thaw_and_lead, _clashes):
        try:
            out.extend(fn(occasion_id) or [])
        except Exception as e:                       # pragma: no cover
            print(f"[occasions] insight {fn.__name__} skipped: {e}")
    return {'occasion_id': occasion_id, 'insights': out}


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
    # A4: a list generated for an occasion the household is INVITED to is a
    # gift list, and a gift list the recipient can read is not a gift list.
    # `private` is an allow-list (only `shared_with` sees it, with no parent
    # bypass and no panel bypass) rather than a deny-list, so the worst case
    # is "I cannot see what you are planning" instead of a ruined surprise.
    lst.update(_gift_visibility(o))
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


# --- A4: noticing an invitation the family already put on the calendar ------
#
# The party is usually on the calendar before anybody thinks about the
# present — somebody types "Jack's party 2pm" the day the invitation comes
# home, and the gift is remembered on the Saturday morning. That gap is the
# whole reason this exists.
#
# It PROPOSES and never creates. A party-shaped title is a guess, and an app
# that silently mints occasions off a keyword would fill the list with
# birthdays that were actually work meetings.

_PARTY_WORDS = re.compile(
    r"\b(birthday|bday|b-day|party|sleepover)\b", re.I)


def _party_shaped(title: str) -> bool:
    """A title that reads like a child being invited somewhere.

    Deliberately narrow, and deliberately blind to possessives — "Ellie's
    birthday" is OUR child's and is a `birthday` occasion (host-side), while
    "Jack's birthday party" is an invitation. The app cannot tell those apart
    from a title, which is exactly why the parent gets a card instead of a
    fait accompli.
    """
    return bool(_PARTY_WORDS.search(title or ''))


def invitation_candidates(now: datetime.datetime = None, ahead_days: int = 21) -> List[dict]:
    """Party-shaped events with a CHILD riding, and no occasion yet.

    The child is the load-bearing signal: an adult's birthday drink is not a
    thing that needs a wrapped present bought in a week, and requiring a kid
    passenger is what keeps every 'end of quarter party' off the list.
    """
    now = now or datetime.datetime.now()
    today = now.date()
    kids = {m['id'] for m in storage.get_all_members()
            if (m.get('role') or '') == 'child'}
    if not kids:
        return []
    known = {(o.get('answers') or {}).get('source_event_id')
             for o in storage.get_occasions(include_done=True)}
    out = []
    for ev in (storage.get_cached_schedule() or {}).get('events', []):
        gid = str(ev.get('id') or '')
        if not gid or gid in known or not _party_shaped(ev.get('title')):
            continue
        try:
            day = datetime.datetime.fromisoformat(str(ev.get('start'))).date()
        except (TypeError, ValueError):
            continue
        if day < today or (day - today).days > ahead_days:
            continue
        riding = [p for p in (ev.get('passenger_ids') or []) if p in kids]
        if not riding:
            continue
        out.append({'event_id': gid, 'title': ev.get('title') or 'A party',
                    'date': day.isoformat(), 'member_ids': riding})
    return out


def propose_invitations(now: datetime.datetime = None, deliver=None) -> dict:
    """Offer to track the present for a party already on the calendar.

    Fires once per event, marker set FIRST — the same discipline every sweep
    in the app follows, so an unreachable delivery never turns into a weekly
    re-offer for the same party.
    """
    now = now or datetime.datetime.now()
    settings = storage.get_settings() or {}
    if not settings.get('propose_invitations', True):
        return {'status': 'disabled'}
    seen = dict(storage.get_app_state('invitation_proposed') or {})
    cutoff = (now.date() - datetime.timedelta(days=60)).isoformat()
    seen = {k: v for k, v in seen.items() if str(v) >= cutoff}

    offered = []
    for cand in invitation_candidates(now):
        if cand['event_id'] in seen:
            continue
        seen[cand['event_id']] = now.date().isoformat()          # marker FIRST
        who = ', '.join(
            (storage.get_member(m) or {}).get('name') or 'Someone'
            for m in cand['member_ids'])
        when = datetime.date.fromisoformat(cand['date'])
        summary = f"Track the present for {cand['title']}"
        body = (f"🎁 {who} has '{cand['title']}' on {when.strftime('%A %d %B')}. "
                f"Want me to track it as an invitation — a present to buy, "
                f"wrapping paper, and a reminder before the day? "
                f"I'll keep the gift list off everyone else's screens.")
        payload = {'event_id': cand['event_id'], 'title': cand['title'],
                   'anchor_date': cand['date'], 'member_ids': cand['member_ids']}
        (deliver or _deliver_invitation_proposal)(summary, payload, body)
        offered.append(cand['event_id'])
    storage.set_app_state('invitation_proposed', seen)
    return {'status': 'proposed' if offered else 'nothing_to_offer',
            'events': offered}


def _deliver_invitation_proposal(summary: str, payload: dict, body: str):
    """Family channel + approvals banner, the same path the shopping trip and
    the car stop already use."""
    from services import chat_actions
    res = chat_actions.create_action_proposal('add_invited_occasion', summary, payload)
    if res.get('status') != 'success':
        return None
    pid = res['proposal_id']
    try:
        fam = storage.get_family_channel()
        if fam:
            storage.update_action_proposal(pid, {'channel_id': fam['id']})
            argyle = storage.ensure_argyle_member()
            from services.agent_tools_v2 import _post_chat_message
            _post_chat_message(fam['id'], argyle['id'], body, proposal_id=pid)
    except Exception as e:
        print(f"[occasions] invitation proposal delivery failed: {e}")
    return pid


def accept_invitation(event_id: str = None, title: str = None,
                      anchor_date: str = None, member_ids: List[str] = None) -> dict:
    """Turn an approved invitation card into a real `invited` occasion.

    The source event id is recorded in `answers` so the same party is never
    offered twice, and the invited children are marked attending — which for
    this kind is the only way anybody is (see `attends_by_default`).
    """
    day = _d(anchor_date) or _today()
    o = create(title or 'A party', day.isoformat(), 'invited')
    answers = dict(o.get('answers') or {})
    if event_id:
        answers['source_event_id'] = str(event_id)
    storage.update_occasion(o['id'], {'answers': answers})
    for mid in (member_ids or []):
        set_attendance(o['id'], mid, True)
    return {'status': 'success', 'occasion_id': o['id'],
            'message': f"Tracking {o['title']} on {day.strftime('%A %d %B')}. "
                       f"Ask me for present ideas whenever you're ready."}


def _gift_visibility(occasion: dict) -> dict:
    """Who may see a list generated for this occasion (A4).

    Only `invited` closes, and only when there is somebody to close it TO: a
    private list with nobody on it is a list NOBODY sees, which is the one
    failure worse than an open one. With no adults on the roster it stays
    household-visible and honest about it rather than disappearing.
    """
    if (occasion or {}).get('kind') != 'invited':
        return {}
    grown = [m['id'] for m in storage.get_all_members()
             if (m.get('role') or '') in ('parent', 'adult')
             and (m.get('status') or 'active') == 'active']
    if not grown:
        return {}
    return {'audience': 'private', 'shared_with': grown}


# --- A5: the gift shortlist -------------------------------------------------
#
# THE RULE THIS SLICE EXISTS TO ENFORCE: the model never names a product.
#
# Asked for gift ideas an LLM returns "LEGO Friends Beach House, $34.99" with
# an invented SKU and a price from its training data, and a parent cannot tell
# that from a real one until they are standing in a shop. The precedent for
# the fix already shipped twice — trips are LLM-proposes → Mapbox-verifies,
# and intake is LLM-extracts → the family approves. Here it is:
#
#     LLM emits SEARCH QUERIES → walmart.search() returns real itemIds and
#     real prices → the budget cap filters WALMART'S RESPONSE → survivors are
#     STAGED for a pick.
#
# The budget is applied to the retailer's answer, never to the model's
# imagination, and nothing is ever auto-added.

_GIFT_QUERY_SYSTEM = (
    "You help a parent find a present for another child's birthday party. "
    "Reply with STRICT JSON only, no prose, no code fences.\n\n"
    "Schema: {\"queries\": [{\"query\": str, \"why\": str}]}\n\n"
    "CRITICAL: `query` is what you would TYPE INTO A SHOP'S SEARCH BOX — a "
    "category plus the qualifiers that matter. NEVER a specific product, "
    "NEVER a brand's exact product name, NEVER a price. You do not know what "
    "any shop stocks or what anything costs; a real search answers that.\n"
    "  good: \"kids art set 7 year old\", \"dinosaur building blocks\", "
    "\"beginner science kit\"\n"
    "  bad:  \"LEGO Friends Beach House 41709\", \"Crayola Inspiration Art "
    "Case $29.99\"\n\n"
    "- 5 to 8 queries, genuinely DIFFERENT from each other — art, building, "
    "outdoor, science, books, games. One idea five ways is a bad shortlist.\n"
    "- Match the age you are told. A 4-year-old and a 10-year-old share "
    "almost nothing.\n"
    "- Use the party's theme or the child's interests when you are given "
    "them, but do not invent interests you were not told.\n"
    "- `why` is ONE short phrase a parent would find useful ('always a safe "
    "bet at this age'). Never a sales pitch.\n"
    "- Nothing consumable, nothing that needs sizing (clothes, shoes), "
    "nothing that needs another purchase to work."
)

MAX_GIFT_CANDIDATES = 12
_PER_QUERY = 4


def _gift_context(occasion: dict) -> dict:
    answers = occasion.get('answers') or {}
    try:
        budget = float(answers.get('gift_budget'))
    except (TypeError, ValueError):
        budget = None
    try:
        age = int(answers.get('their_age'))
    except (TypeError, ValueError):
        age = None
    return {'who': str(answers.get('whose_party') or '').strip() or None,
            'age': age, 'budget': budget if budget and budget > 0 else None}


def gift_ideas(occasion_id: str, extra: str = None) -> dict:
    """A shortlist of REAL products under the budget, staged for a pick.

    Degrades honestly. With no Walmart credentials there is no search, so
    there are no products — and the answer is the QUERIES as things to go and
    look for, explicitly marked unverified. It is never a made-up product
    list, because a plausible invented gift is worse than no suggestion: the
    parent has to evaluate it either way and now has to discover it is fake.
    """
    from services import model_pools, walmart
    o = storage.get_occasion(occasion_id)
    if not o:
        return {'error': 'no such occasion'}
    settings = storage.get_settings() or {}
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key:
        return {'error': 'no LLM API key configured'}

    ctx = _gift_context(o)
    bits = [f"The party is {o['title']}."]
    if ctx['who']:
        bits.append(f"It is for {ctx['who']}.")
    bits.append(f"They are turning {ctx['age']}." if ctx['age']
                else "Their age is unknown — keep the ideas broad.")
    if (extra or '').strip():
        bits.append(f"The parent adds: {extra.strip()}")
    # The budget is deliberately NOT in the prompt. It is a filter on real
    # prices; telling the model about it only invites it to quote one.
    try:
        res = model_pools.call_pool_json(
            'interactive', api_key, _GIFT_QUERY_SYSTEM, ' '.join(bits),
            temperature=0.6, timeout_s=45, settings=settings)
        if not isinstance(res, dict) or res.get('error'):
            raise RuntimeError(res.get('error') if isinstance(res, dict) else 'bad response')
    except Exception as e:
        print(f"[occasions] gift ideas failed for {occasion_id}: {e}")
        return {'error': 'could not think of anything'}

    queries, seen_q = [], set()
    for q in (res.get('queries') or [])[:8]:
        if not isinstance(q, dict):
            continue
        text = str(q.get('query') or '').strip()[:80]
        if not text or text.lower() in seen_q:
            continue
        seen_q.add(text.lower())
        queries.append({'query': text,
                        'why': str(q.get('why') or '').strip()[:100] or None})

    out = {'occasion_id': occasion_id, 'budget': ctx['budget'],
           'queries': queries, 'candidates': [], 'searched': False,
           'over_budget': 0}
    if not queries:
        out['error'] = 'could not think of anything'
        return out
    if not walmart.is_configured():
        # Honest, and still useful: these are CATEGORIES to go and look for,
        # not products anybody is claiming exist at a price.
        out['note'] = ('No shop search is configured, so these are things to '
                       'look for rather than real products.')
        return out

    out['searched'] = True
    seen_ids = set()
    for q in queries:
        try:
            found = walmart.search(q['query'], limit=_PER_QUERY)
        except Exception as e:
            print(f"[occasions] gift search failed for {q['query']!r}: {e}")
            continue
        for it in found:
            iid = str(it.get('item_id') or '')
            if not iid or iid in seen_ids or not it.get('available', True):
                continue
            price = it.get('price')
            # The cap bites on WALMART'S price. An item whose price the API
            # did not return is not silently assumed cheap — it is dropped,
            # because "probably under $25" is the exact guess this design
            # refuses to make.
            if ctx['budget'] is not None:
                if price is None:
                    continue
                try:
                    if float(price) > ctx['budget']:
                        out['over_budget'] += 1
                        continue
                except (TypeError, ValueError):
                    continue
            seen_ids.add(iid)
            out['candidates'].append({
                'item_id': iid, 'title': it.get('title'), 'price': price,
                'thumbnail': it.get('thumbnail'), 'url': it.get('url'),
                'brand': it.get('brand'), 'query': q['query'], 'why': q['why'],
            })
    # Cheapest first: a parent scanning a gift shortlist is deciding what is
    # enough, not what is best, and the price is the axis they are on.
    out['candidates'].sort(key=lambda c: (c['price'] is None, c['price'] or 0))
    out['candidates'] = out['candidates'][:MAX_GIFT_CANDIDATES]
    return out


def gift_lead_days() -> int:
    """How long before the party the present has to be in hand.

    A6 makes this a setting; until then three days is the honest default —
    enough for a pickup order, and it is the offset the invited template
    already stamps its gift line at.
    """
    try:
        return max(0, int((storage.get_settings() or {}).get('gift_lead_days') or 3))
    except (TypeError, ValueError):
        return 3


def add_gifts(occasion_id: str, picks: List[dict], added_by: str = None) -> dict:
    """Picked candidates → the occasion's PRIVATE gift list, cart-ready.

    Two things happen per pick and the second is what makes this worth doing:
    the row lands on a list, and `walmart.set_mapping` records name → itemId,
    so `cart_for_list` carts the exact product that was chosen rather than
    whatever a fresh search would turn up in a fortnight.
    """
    from models.schemas import ShoppingList, ShoppingItem
    from services import walmart
    o = storage.get_occasion(occasion_id)
    if not o:
        return {'error': 'no such occasion'}
    picks = [p for p in (picks or []) if isinstance(p, dict) and p.get('title')]
    if not picks:
        return {'error': 'nothing picked'}

    lst = next((l for l in storage.get_shopping_lists()
                if l.get('occasion_id') == occasion_id
                and l.get('occasion_key') == 'gift'), None)
    if not lst:
        lst = ShoppingList(name=f"{o['title']} — present"[:60],
                           occasion_id=occasion_id, occasion_key='gift').model_dump()
        lst.update(_gift_visibility(o))
        storage.add_shopping_list(lst)

    anchor = _d(o.get('anchor_date')) or _today()
    needed = (anchor - datetime.timedelta(days=gift_lead_days())).isoformat()
    added = []
    for p in picks:
        name = str(p['title']).strip()[:80]
        rec = ShoppingItem(list_id=lst['id'], name=name,
                           note=str(p.get('why') or '').strip()[:120] or None,
                           added_by=added_by, added_via='agent',
                           source_event_id=occasion_id, needed_by=needed,
                           occasion_id=occasion_id).model_dump()
        storage.add_shopping_item(rec)
        if p.get('item_id'):
            walmart.set_mapping(name, p['item_id'], title=name,
                                price=p.get('price'), thumbnail=p.get('thumbnail'))
        added.append(rec)
    return {'list': lst, 'items': added, 'needed_by': needed}


def set_status(occasion_id: str, status: str) -> bool:
    return storage.update_occasion(
        occasion_id, {'status': 'done' if status == 'done' else 'planning'})

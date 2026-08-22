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


# --- The trip itself (meals & provisioning arc M7) ---------------------------
# A standing list with no trip attached is half a system: the family can write
# down what they need and still have nowhere for it to happen. The binding
# already existed (ShoppingList.errand_tag against Errand.tags, chosen so it
# survives a recurring errand regenerating with a new id every cycle) — what
# was missing was any way to CREATE the errand, and any use of it once it
# exists. See docs/meal_week_design.md.

import datetime

DEFAULT_SHOP_MINS = 90          # a real grocery run, not a dash for milk
SHOP_WINDOW = ('08:00', '20:00')


def item_runs(list_id: str = None, today: datetime.date = None) -> dict:
    """The list, split by which shop RUN each item is for.

    A mid-week dash for the one thing tonight's re-planned dinner needs must
    not arrive carrying all of Saturday. That is the whole reason items know
    their run — and it is per item rather than per list because the grocery
    list is standing: the errand regenerates every cycle while the list
    persists across all of them, and a list per run is how a second list ends
    up rotting while everyone keeps adding milk to the main one.

    Three groups, in the order a shopper wants them:

    - `now`  — needed BEFORE the next run. The plan changed after the shopping
               was done. This is the top-up, and it is what a quick trip
               should open to.
    - `next` — the coming run's list, including everything added by hand
               (`buy_on` unset means "the next run", which is what somebody
               typing "milk" means). Offered alongside a top-up rather than
               hidden: standing in a store is the best moment to be asked
               whether you want the rest, and buying some of it just checks
               those rows off and leaves the remainder for Saturday.
    - `later` — runs beyond the next one, a group per run. Nothing to do with
               this trip; visible so a plan two shops out is not invisible.
    """
    from services import meals as _meals
    today = today or datetime.date.today()
    settings = storage.get_settings() or {}
    nxt, _, _ = _meals.shop_date(settings, today)
    shop = nxt.isoformat()
    now, nxt_items, later = [], [], {}
    for it in storage.get_shopping_items(list_id, include_checked=False):
        when = it.get('buy_on')
        if not when or when == shop:
            nxt_items.append(it)
        elif when < shop:
            now.append(it)
        else:
            later.setdefault(when, []).append(it)
    # §A2: the run each group actually happens on, which is what a deadline
    # is measured against. The `now` group IS the go-today trip, so it is
    # never late; `next` takes the solver's placement over the weekday guess
    # when there is one; a `later` run is its own date.
    runs = run_dates(list_id, today)
    groups = []
    if now:
        groups.append({'key': 'now', 'date': None,
                       'items': annotate_deadlines(now, today=today,
                                                   run_date=today.isoformat()),
                       'label': 'Needed before ' + nxt.strftime('%A')})
    groups.append({'key': 'next', 'date': shop,
                   'items': annotate_deadlines(nxt_items, today=today,
                                               run_date=runs['next']),
                   'label': nxt.strftime('%A') + "'s shop"})
    for when in sorted(later):
        d = datetime.date.fromisoformat(when)
        # Not %-d / %#d: those are platform-specific and this runs on both a
        # Windows dev box and an Alpine add-on container.
        groups.append({'key': 'later', 'date': when,
                       'items': annotate_deadlines(later[when], today=today,
                                                   run_date=when),
                       'label': f"{d.strftime('%b')} {d.day}"})
    late = [i for g in groups for i in g['items'] if (i.get('deadline') or {}).get('late')]
    return {'shop_date': shop, 'groups': groups, 'runs': runs,
            'late': [{'id': i['id'], 'name': i['name'],
                      'needed_by': i['deadline']['needed_by']} for i in late],
            'top_up': bool(now), 'counts': {g['key']: len(g['items']) for g in groups}}


def run_dates(list_id: str = None, today: datetime.date = None) -> dict:
    """When the family will actually be in a shop — guess AND decision.

    `meals.shop_date()` is a weekday setting: a guess made from average free
    time. A scheduled errand is a decision made against the real week. Both
    are returned because both are true at different moments — the guess is
    all there is until the solver has placed the trip, and the placement is
    the honest answer once it has.
    """
    from services import meals as _meals
    today = today or datetime.date.today()
    settings = storage.get_settings() or {}
    guess, _, _ = _meals.shop_date(settings, today)
    out = {'guess': guess.isoformat(), 'scheduled': None, 'next': guess.isoformat(),
           'has_trip': False}
    if not list_id:
        return out
    e = errand_for_list(list_id)
    out['has_trip'] = bool(e)
    nxt = next_scheduled_shop(list_id) if e else None
    if nxt and nxt.get('date'):
        out['scheduled'] = nxt['date']
        # The solver's placement wins — but only forward. A trip scheduled
        # for a day already gone says nothing about the shop that is coming.
        if nxt['date'] >= today.isoformat():
            out['next'] = nxt['date']
    return out


def deadline_state(item: dict, run_date: str, today: datetime.date = None) -> dict:
    """Does the run that will buy this thing land before it is needed?

    Supply intake §A2, and the reason `needed_by` exists at all. "Add poster
    board to the list" is worth almost nothing; "the fair is Friday and your
    shop run is Saturday" is the whole feature.

    Returns None for an item with no deadline — which is nearly all of them,
    and they must stay ordinary rows. No percentage and no completion count
    anywhere downstream (occasions §O2): three of eight supplies unbought is
    fine on Monday and an emergency on Thursday, and one number cannot say
    both.
    """
    needed = (item or {}).get('needed_by')
    if not needed:
        return None
    today = today or datetime.date.today()
    try:
        due = datetime.date.fromisoformat(str(needed))
    except (TypeError, ValueError):
        return None
    days_left = (due - today).days
    # No run date at all (nowhere to shop) is LATE by definition — a thing
    # with a deadline and no trip is exactly the quiet failure this catches.
    late = (not run_date) or str(run_date) > needed
    return {'needed_by': needed, 'days_left': days_left,
            'run_date': run_date or None, 'late': late,
            'missed': days_left < 0}


def annotate_deadlines(items: list, list_id: str = None, today: datetime.date = None,
                       run_date: str = None) -> list:
    """One implementation of the verdict, for every surface that shows items.

    Which run an item belongs to is already answered server-side rather than
    re-derived per page (see `item_runs`), and whether that run is in time is
    the same kind of question — a list page and a watcher disagreeing about
    whether the poster board is late is worse than neither saying anything.
    """
    today = today or datetime.date.today()
    if run_date is None:
        run_date = run_dates(list_id, today)['next']
    out = []
    for it in items:
        row = dict(it)
        state = deadline_state(row, run_date, today)
        if state:
            row['deadline'] = state
        out.append(row)
    return out


def errand_for_list(list_id: str) -> dict:
    """The errand this list is bound to, if one exists."""
    if not list_id:
        return None
    for e in storage.get_all_errands():
        if e.get('is_completed'):
            continue
        if any(l.get('id') == list_id for l in storage.find_shopping_lists_for_errand(e)):
            return e
    return None


def next_scheduled_shop(list_id: str) -> dict:
    """When the solver actually PUT the trip, not which weekday we guessed.

    This is the honest answer to "which day do we shop": a weekday setting is a
    guess made from average free time, while a scheduled errand is a decision
    made against the real week, with the drives and the detour accounted for.
    """
    e = errand_for_list(list_id)
    if not e:
        return None
    start = storage.get_all_scheduled_errands().get(e.get('id'))
    if not start:
        return {'errand': e, 'scheduled': False}
    try:
        when = datetime.datetime.fromisoformat(str(start).replace('Z', '+00:00'))
    except ValueError:
        return {'errand': e, 'scheduled': False}
    return {'errand': e, 'scheduled': True, 'start': start,
            'date': when.date().isoformat(), 'weekday': when.weekday(),
            'label': when.strftime('%A'),
            'time_label': when.strftime('%I:%M %p').lstrip('0')}


def create_errand_for_list(list_id: str = None, weekday: int = None,
                           duration_mins: int = None, location: str = None,
                           recurring: bool = True) -> dict:
    """Give a list somewhere to happen.

    `valid_days_of_week` is left OPEN by default rather than pinned to the
    chosen weekday: the whole point of having a solver is that it can find a
    good slot against the actual week, and pinning the day throws that away.
    A weekday is passed only when the family has explicitly said "we shop on
    Tuesdays" — then it is a constraint they chose, not one we invented.
    """
    from models.schemas import Errand
    lst = storage.get_shopping_list(list_id) if list_id \
        else storage.ensure_default_shopping_list()
    if not lst:
        return {'status': 'error', 'message': 'No such list.'}
    existing = errand_for_list(lst['id'])
    if existing:
        return {'status': 'exists', 'errand': existing, 'list': lst,
                'message': f"'{lst['name']}' already has a trip: {existing['title']}."}

    tag = (lst.get('errand_tag') or '').strip()
    if not tag:
        # Bind by tag from here on — a list tied to an errand ID would be
        # orphaned the first time the recurring errand regenerated.
        tag = (lst.get('name') or 'groceries').strip().lower().replace(' ', '_')
        storage.update_shopping_list(lst['id'], {'errand_tag': tag})
        lst = storage.get_shopping_list(lst['id'])

    where = (location or lst.get('store') or '').strip()
    if not where:
        return {'status': 'needs_location', 'list': lst,
                'message': f"Where do you shop for '{lst['name']}'? "
                           "I need a store to put the trip at."}

    errand = Errand(
        title=f"{lst['name']} run" if not lst['name'].lower().endswith('run')
              else lst['name'],
        location=where,
        duration_mins=int(duration_mins or DEFAULT_SHOP_MINS),
        priority=2,
        tags=[tag],
        recurrence_rule='weekly' if recurring else None,
        window_days=7 if recurring else 3,
        time_window_start=SHOP_WINDOW[0], time_window_end=SHOP_WINDOW[1],
        valid_days_of_week=[int(weekday)] if weekday is not None else [],
    )
    data = errand.model_dump()
    storage.add_errand(data)
    return {'status': 'success', 'errand': data, 'list': lst,
            'message': f"Added a {'weekly ' if recurring else ''}"
                       f"{data['duration_mins']}-minute trip to {where} for "
                       f"'{lst['name']}'. The solver will fit it into the week."}


def lists_needing_a_trip(min_items: int = 5, today: datetime.date = None) -> list:
    """Lists carrying real weight with nowhere to happen.

    Deliberately not a nag on every list: a list with two things on it is not a
    trip, and a list nobody is adding to does not need one either.

    §A2 adds the second reason, which weight cannot express: **a deadline with
    no trip to meet it**. One tri-fold board needed Friday on a list with
    nowhere to happen is a real failure and would never reach five items — so
    a dated item qualifies a list on its own, and the offer says which thing
    is driving it rather than quoting a count that is not the point.
    """
    today = today or datetime.date.today()
    out = []
    for l in storage.get_shopping_lists():
        if errand_for_list(l['id']):
            continue
        open_items = storage.get_shopping_items(l['id'], include_checked=False)
        # No trip means no run date, so every dated item here is late by
        # definition — the soonest one is the one worth naming.
        dated = sorted((i for i in open_items if i.get('needed_by')),
                       key=lambda i: str(i['needed_by']))
        soonest = dated[0] if dated else None
        if len(open_items) >= min_items or soonest:
            out.append({'list': l, 'open_count': len(open_items),
                        'because': 'deadline' if soonest else 'weight',
                        'deadline_item': soonest})
    return out


def deadline_findings(today: datetime.date = None) -> list:
    """(key, line) pairs for the watcher sweep — one per late item.

    Deliberately per ITEM and not per list: "2 things are late" is the
    percentage failure in another costume. The parent needs to know it is the
    poster board, because that is what tells them whether it matters.
    """
    today = today or datetime.date.today()
    out = []
    for l in storage.get_shopping_lists():
        run = run_dates(l['id'], today)
        items = storage.get_shopping_items(l['id'], include_checked=False)
        for it in annotate_deadlines(items, today=today, run_date=run['next']):
            d = it.get('deadline')
            if not d or not d['late']:
                continue
            when = datetime.date.fromisoformat(d['needed_by'])
            if d['missed']:
                tail = f"was needed {when.strftime('%A')}"
            elif not run['has_trip']:
                tail = (f"needed {when.strftime('%A')} and '{l['name']}' has no "
                        f"trip scheduled")
            else:
                shop = datetime.date.fromisoformat(d['run_date'])
                tail = (f"needed {when.strftime('%A')}, and the "
                        f"'{l['name']}' run is {shop.strftime('%A')}")
            out.append((f"supply_late:{it['id']}", f"🛒 {it['name']} — {tail}"))
    return out


def propose_shopping_errands(now=None, deliver=None, min_items: int = 5) -> dict:
    """Offer a trip for a list that has weight and nowhere to happen.

    Fires once per list until acted on. A list nobody can shop for is the
    quiet failure this whole slice exists to remove — the family writes things
    down all week and the trip lives only in someone's head.
    """
    now = now or datetime.datetime.now()
    settings = storage.get_settings() or {}
    if not settings.get('propose_shopping_errands', True):
        return {'status': 'disabled'}
    seen = dict(storage.get_app_state('shopping_errand_proposed') or {})
    cutoff = (now.date() - datetime.timedelta(days=30)).isoformat()
    seen = {k: v for k, v in seen.items() if str(v) >= cutoff}

    offered = []
    for row in lists_needing_a_trip(min_items, now.date()):
        lst, n = row['list'], row['open_count']
        if lst['id'] in seen:
            continue
        seen[lst['id']] = now.date().isoformat()          # marker FIRST
        store = (lst.get('store') or '').strip()
        due = row.get('deadline_item')
        if due:
            # Lead with the dated thing, not the count: a list of one is the
            # normal shape of this case and quoting "1 thing waiting" reads
            # as trivial when it is the opposite.
            when = datetime.date.fromisoformat(str(due['needed_by']))
            summary = (f"A trip for '{lst['name']}' — {due['name']} is needed "
                       f"{when.strftime('%A')}")
            body = (f"🛒 {due['name']} is needed by {when.strftime('%A')} and "
                    f"'{lst['name']}' has no trip scheduled — there is nowhere "
                    f"for it to be bought. Want me to add a weekly "
                    f"{DEFAULT_SHOP_MINS}-minute run"
                    + (f" to {store}" if store else "")
                    + " and let the solver fit it into the week?")
        else:
            summary = f"A weekly trip for '{lst['name']}' ({n} things waiting)"
            body = (f"🛒 '{lst['name']}' has {n} things on it and no trip scheduled — "
                    f"it only exists in someone's head right now. Want me to add a "
                    f"weekly {DEFAULT_SHOP_MINS}-minute run"
                    + (f" to {store}" if store else "")
                    + " and let the solver fit it into the week?")
        if not store:
            body += ("\n(I don't know where you shop for this — approving will "
                     "ask for the store.)")
        payload = {'list_id': lst['id'], 'recurring': True}
        (deliver or _deliver_errand_proposal)(summary, payload, body)
        offered.append(lst['id'])
    storage.set_app_state('shopping_errand_proposed', seen)
    return {'status': 'proposed' if offered else 'nothing_to_offer',
            'lists': offered}


def _deliver_errand_proposal(summary: str, payload: dict, body: str):
    """Family channel + approvals banner, same path as the car stop."""
    from services import chat_actions
    res = chat_actions.create_action_proposal('add_shopping_errand', summary, payload)
    if res.get('status') != 'success':
        return None
    pid = res['proposal_id']
    try:
        fam = storage.get_family_channel()
        if fam:
            storage.update_action_proposal(pid, {'channel_id': fam['id']})
            argyle = storage.ensure_argyle_member()
            from services.agent_tools_v2 import _post_chat_message
            _post_chat_message(fam, argyle, body, card=res['card'])
    except Exception as ex:
        print(f"shopping errand proposal delivery failed: {ex}")
    return pid

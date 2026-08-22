"""Supply intake A4 — the occasion the family is INVITED to.

Every occasion template that shipped before this one is host-side:
thanksgiving, christmas, birthday, party and gathering all ask headcount and
cooking hands and offer to tidy the house. Being invited to somebody else's
is the inverse — one child, no kitchen, somewhere that is not home — and the
only work is a present and getting there.

The properties that matter, and why:

  1. **No headcount question, ever.** Answering headcount CASCADES into
     scaling every plate in the window. Asked here, the app would cook for
     twelve because a child was invited to a party.
  2. **Nobody attends by default.** The household is not hosting, so the
     roster starts empty and the parent says who was actually asked.
  3. **A generated list is PRIVATE.** A gift list the recipient can read is
     not a gift list — and `private` is an allow-list with no parent bypass
     and no panel bypass, so the worst case is "I cannot see what you are
     planning" rather than a ruined surprise.
  4. **It PROPOSES, never creates.** A party-shaped title is a guess, and
     "Ellie's birthday" (ours) reads exactly like "Jack's birthday party" (an
     invitation). A child riding is what separates a real invitation from the
     end-of-quarter party on somebody's work calendar.
  5. **Once per event, marker FIRST** — the discipline every sweep follows,
     so an unreachable delivery never becomes a weekly re-offer.

Run from chauffeur/:  python tests/test_invited_occasions.py
"""
import datetime
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage
from services import occasions as _occ

TODAY = datetime.date.today()
SAT = TODAY + datetime.timedelta(days=5)


def _reset():
    with storage.db_lock:
        storage.occasions_table.truncate()
        storage.members_table.truncate()
        storage.shopping_lists_table.truncate()
        storage.shopping_items_table.truncate()
    storage.set_app_state('invitation_proposed', {})


def _member(mid, name, role):
    from models.schemas import FamilyMember
    m = FamilyMember(id=mid, name=name, role=role).model_dump()
    storage.add_member(m)
    return m


def _household():
    _member('mum', 'Mum', 'parent')
    _member('dad', 'Dad', 'parent')
    _member('ellie', 'Ellie', 'child')
    _member('tot', 'Tot', 'child')


def scenario_the_invited_template_never_asks_a_host_question():
    """Property 1. The cascade is the danger, not the extra tap."""
    _reset()
    o = _occ.create("Jack's party", SAT.isoformat(), 'invited')
    check(o['kind'] == 'invited', f"the kind is real, not silently coerced: {o['kind']}")
    keys = [q['key'] for q in _occ.interview(o['id'])['questions']]
    check('headcount' not in keys and 'cooking_hands' not in keys,
          f"no host questions: {keys}")
    check(keys == ['whose_party', 'their_age', 'gift_budget'],
          f"three questions and no more — an invitation is a small thing: {keys}")
    check(_occ.template_for(o)['dish_tags'] == [],
          "and it brings no dishes into play")


def scenario_the_checklist_is_a_present_and_the_thing_people_forget():
    """The gift is a LIST line rather than an errand on purpose: an errand
    needs a location nobody knows yet, and A2 already offers a trip for a
    dated thing with nowhere to happen."""
    _reset()
    o = _occ.create("Jack's party", SAT.isoformat(), 'invited')
    lines = {l['key']: l for l in _occ.template_for(o)['checklist']}
    check(set(lines) == {'gift', 'wrapping'}, f"two lines: {list(lines)}")
    check(lines['gift']['type'] == 'list',
          f"the present is sourced, not stamped as an errand: {lines['gift']['type']}")
    check(lines['wrapping']['type'] == 'note',
          "wrapping paper and a card get their own line — it is what gets forgotten")

    made = _occ.apply_template(o['id'])
    check(made['created'] == [],
          f"and nothing invents an errand at a location we do not have: {made}")


def scenario_nobody_is_going_until_somebody_says_so():
    """Property 2. Defaulting the family in would report six people at a
    classmate's party and feed a meaningless headcount to everything after."""
    _reset()
    _household()
    o = _occ.create("Jack's party", SAT.isoformat(), 'invited')
    rows = _occ.attendance(o['id'])
    check(len(rows) == 4 and not any(r['attending'] for r in rows),
          f"the whole roster is listed and nobody is in: {rows}")
    check(_occ.headcount(o['id']) == 0, "so the headcount is honest about it")

    _occ.set_attendance(o['id'], 'ellie', True)
    going = [r['name'] for r in _occ.attendance(o['id']) if r['attending']]
    check(going == ['Ellie'], f"one tap, one child: {going}")

    # And hosting kinds are untouched — this must not change every occasion.
    host = _occ.create("Thanksgiving", SAT.isoformat(), 'thanksgiving')
    check(len([r for r in _occ.attendance(host['id']) if r['attending']]) == 4,
          "a hosting occasion still starts with the household in")


def scenario_a_generated_list_is_private():
    """Property 3, and the reason the occasions brief called gift secrecy a
    blocker: the mechanism shipped, the noun did not."""
    _reset()
    _household()
    o = _occ.create("Jack's party", SAT.isoformat(), 'invited')
    with mock.patch('services.storage.get_settings',
                    return_value={'llm_gemini_api_key': 'k'}), \
         mock.patch('services.model_pools.call_pool_json',
                    return_value={'items': [{'name': 'LEGO set'}]}):
        res = _occ.generate_list(o['id'], 'a present for Jack')
    lst = res['list']
    check(lst['audience'] == 'private', f"closed, not open: {lst.get('audience')}")
    check(sorted(lst['shared_with']) == ['dad', 'mum'],
          f"to the grown-ups, and nobody else: {lst.get('shared_with')}")

    # A hosting occasion's list is NOT closed — party supplies are not secret,
    # and closing everything would teach the family to ignore the lock.
    host = _occ.create("Our party", SAT.isoformat(), 'party')
    with mock.patch('services.storage.get_settings',
                    return_value={'llm_gemini_api_key': 'k'}), \
         mock.patch('services.model_pools.call_pool_json',
                    return_value={'items': [{'name': 'balloons'}]}):
        res2 = _occ.generate_list(host['id'], 'party supplies')
    check(not res2['list'].get('audience'),
          f"the host list stays household-visible: {res2['list'].get('audience')}")


def scenario_a_private_list_with_nobody_on_it_is_never_created():
    """The one failure worse than an open list. With no adults on the roster
    it stays visible and honest rather than disappearing."""
    _reset()
    _member('ellie', 'Ellie', 'child')
    o = _occ.create("Jack's party", SAT.isoformat(), 'invited')
    with mock.patch('services.storage.get_settings',
                    return_value={'llm_gemini_api_key': 'k'}), \
         mock.patch('services.model_pools.call_pool_json',
                    return_value={'items': [{'name': 'LEGO set'}]}):
        res = _occ.generate_list(o['id'], 'a present')
    check(not res['list'].get('audience'),
          f"no grown-ups -> no lock, rather than a list nobody can see: {res['list']}")


def scenario_a_party_on_the_calendar_is_only_a_candidate():
    """Property 4. The child riding is the load-bearing signal."""
    _reset()
    _household()
    events = [
        {'id': 'e1', 'title': "Jack's birthday party",
         'start': f"{SAT.isoformat()}T14:00:00", 'passenger_ids': ['ellie']},
        {'id': 'e2', 'title': "End of quarter party",
         'start': f"{SAT.isoformat()}T17:00:00", 'passenger_ids': []},
        {'id': 'e3', 'title': "Dentist",
         'start': f"{SAT.isoformat()}T09:00:00", 'passenger_ids': ['tot']},
    ]
    with mock.patch('services.storage.get_cached_schedule',
                    return_value={'events': events}):
        cands = _occ.invitation_candidates(
            datetime.datetime.combine(TODAY, datetime.time(9, 0)))
    check([c['event_id'] for c in cands] == ['e1'],
          f"a kid at a party, and nothing else: {[c['event_id'] for c in cands]}")
    check(cands[0]['member_ids'] == ['ellie'], f"naming who is going: {cands[0]}")

    # Far-future parties are not anticipation, they are noise.
    far = [{'id': 'e9', 'title': "Sam's party", 'passenger_ids': ['ellie'],
            'start': f"{(TODAY + datetime.timedelta(days=60)).isoformat()}T14:00:00"}]
    with mock.patch('services.storage.get_cached_schedule',
                    return_value={'events': far}):
        check(_occ.invitation_candidates(
            datetime.datetime.combine(TODAY, datetime.time(9, 0))) == [],
            "two months out is not something to act on today")


def scenario_the_offer_fires_once_and_is_approved_into_a_real_occasion():
    """Property 5, then the accept path — proposing is only half of it."""
    _reset()
    _household()
    events = [{'id': 'e1', 'title': "Jack's birthday party",
               'start': f"{SAT.isoformat()}T14:00:00", 'passenger_ids': ['ellie']}]
    now = datetime.datetime.combine(TODAY, datetime.time(9, 0))
    sent = []

    with mock.patch('services.storage.get_cached_schedule',
                    return_value={'events': events}), \
         mock.patch('services.storage.get_settings',
                    return_value={'propose_invitations': True}):
        r1 = _occ.propose_invitations(now, deliver=lambda s, p, b: sent.append((s, p, b)))
        r2 = _occ.propose_invitations(now, deliver=lambda s, p, b: sent.append((s, p, b)))
    check(r1['status'] == 'proposed' and r2['status'] == 'nothing_to_offer',
          f"once per party, not once per sweep: {r1} then {r2}")
    check(len(sent) == 1, f"one card: {len(sent)}")
    summary, payload, body = sent[0]
    check('Ellie' in body and 'off everyone else' in body,
          f"it names who is going and promises the secrecy: {body!r}")

    res = _occ.accept_invitation(**payload)
    check(res['status'] == 'success', f"approving makes a real occasion: {res}")
    o = storage.get_occasion(res['occasion_id'])
    check(o['kind'] == 'invited' and o['anchor_date'] == SAT.isoformat(),
          f"with the right kind and day: {o['kind']} {o['anchor_date']}")
    check([r['name'] for r in _occ.attendance(o['id']) if r['attending']] == ['Ellie'],
          "and the invited child marked in")

    # The same party is never offered twice, even after the marker ages out.
    storage.set_app_state('invitation_proposed', {})
    with mock.patch('services.storage.get_cached_schedule',
                    return_value={'events': events}):
        check(_occ.invitation_candidates(now) == [],
              "an event already tracked is not a candidate at all")


def scenario_the_switch_and_the_action_type_exist():
    """Every agent capability needs a hand path, and every sweep needs an off
    switch — a family who finds this wrong must be able to stop it."""
    _reset()
    with mock.patch('services.storage.get_settings',
                    return_value={'propose_invitations': False}):
        check(_occ.propose_invitations(datetime.datetime.now())['status'] == 'disabled',
              "the toggle actually stops it")

    from services import chat_actions
    check('add_invited_occasion' in chat_actions.ADMIN_ACTIONS,
          "the approval card is a registered admin action")
    check(chat_actions.ACTION_LABELS.get('add_invited_occasion'),
          "with a human label on the badge")

    import os
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates')
    occ = open(os.path.join(tpl, 'occasions.html'), encoding='utf-8').read()
    check("'invited'" in occ, "the occasions page offers the kind by hand")
    shop = open(os.path.join(tpl, 'shopping.html'), encoding='utf-8').read()
    check('propose_invitations' in shop, "and the sweep has a visible toggle")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} invited-occasion scenarios passed")

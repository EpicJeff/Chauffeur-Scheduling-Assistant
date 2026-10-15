"""Acceptance: "help me plan Kate's birthday on March 20" (planned missions
spec §9). A scripted planner drives the REAL registry, the real runner and the
real occasion code; only model calls are faked. Task 12.

What a person would see, in order:
  1. an interview (the birthday template's questions, then the budget) they
     answer once on the card;
  2. a plan of five build stages — the party and its people, food, supplies,
     presents, invitations — they approve with one tap, which writes nothing;
  3. stage 1 makes the party (by id, never last year's of the same name),
     replays the interview answers into it (headcount reaches the kitchen),
     adds the guests and stamps the cake errand; the party becomes the
     mission's subject;
  4. stage 2 food: "make it pizza instead" sends the proposed stage back and
     Argyle re-proposes it; "yes, do the menu" in the private chat approves
     it; the dishes are party-only and the menu holds all of them
     (`{"$ref": row, "kind": "dish", "all": true}`);
  5. supplies, a private presents list Kate cannot see, three invitation
     drafts;
  6. the finish hands over the drafts and what is still open.

Run from chauffeur/:  python tests/test_planned_party.py
"""
from harness import check  # noqa: F401
from services import storage, missions, situations, triage, occasions, meals, scope
from services import agent_tools_v2 as tools
from test_planned_missions import _fresh, _plan_of
from test_mission_subject import _plan, _step, _steps, _mission
from test_subjects import MOM, KID

DMS = []


def _setup():
    _fresh(step_cap=200)
    DMS.clear()
    missions._post = lambda dm, argyle, body, card=None: DMS.append({'to': dm.get('member_ids'), 'body': body, 'card': card}) or {'id': f'm{len(DMS)}'}
    storage.save_occasion({'id': 'last', 'title': "Kate's birthday", 'kind': 'birthday', 'anchor_date': '2026-03-20', 'status': 'done'})

    def fake_dishes(description):
        rows = []
        for name in [s.strip() for s in description.split(',') if s.strip()]:
            row = {'id': f"d-{name.replace(' ', '-')}", 'name': name, 'tags': [], 'scope': 'everyday'}
            storage.add_dish(dict(row))
            rows.append(row)
        return {'added': rows}
    meals.add_dishes_from_text = fake_dishes

    def fake_generate(occasion_id, request, list_name=None, store=None, added_by=None):
        lid = f"gen-{occasion_id}"
        storage.add_shopping_list({'id': lid, 'name': list_name or 'Party supplies', 'occasion_id': occasion_id})
        return {'list': {'id': lid, 'name': list_name or 'Party supplies'}, 'items': []}
    occasions.generate_list = fake_generate


def _stage(mid, sid):
    return next(s for s in _plan_of(mid)['stages'] if s['id'] == sid)


def _approve(mid, sid):
    st = _stage(mid, sid)
    res = situations.act('mission', mid, 'run_stage', option_id=f"run_stage:{sid}:{st['snapshot']}:approve", payload={}, actor=dict(MOM))
    check(res['status'] == 'success', f"stage {sid} approved: {res}")
    return _stage(mid, sid)


def _new_party():
    rows = [o for o in storage.get_occasions(include_done=True) if o['title'] == "Kate's birthday" and o['id'] != 'last']
    return rows[0] if rows else None


STAGES = [
    {'id': 's1', 'kind': 'build', 'title': 'The party and its people', 'why': 'everything hangs off it', 'makes': ['the party', 'guests', 'the cake errand']},
    {'id': 's2', 'kind': 'build', 'title': 'Food', 'why': 'feed fourteen', 'makes': ['the menu']},
    {'id': 's3', 'kind': 'build', 'title': 'Supplies', 'why': 'dinosaur things', 'makes': ['a supplies list']},
    {'id': 's4', 'kind': 'build', 'title': 'Presents', 'why': 'kept from Kate', 'makes': ['a private presents list']},
    {'id': 's5', 'kind': 'build', 'title': 'Invitations', 'why': 'you send them', 'makes': ['three drafts']},
]


def scenario_the_whole_party():
    _setup()
    mid = _mission(created_by='mom')
    storage.update_mission(mid, {'goal': "help me plan Kate's birthday on March 20"})

    # 1. The interview.
    _plan({'action': 'interview', 'template': 'birthday',
           'questions': [{'key': 'budget', 'ask': 'What is the budget?', 'kind': 'number'}]})
    _step(mid)
    from services import planned
    planned.answer_plan(mid, {'headcount': 14, 'cooking_hands': 2, 'cake': True, 'theme': 'dinosaurs', 'gifts': True, 'budget': 40}, dict(MOM))
    check(storage.get_mission(mid)['status'] == 'running', "answered: Argyle plans")
    check(_new_party() is None and storage.get_plate('2027-03-20') is None, "nothing written by the interview")

    # 2. The plan.
    _plan({'action': 'plan', 'stages': STAGES})
    _step(mid)
    rev = _plan_of(mid)['rev']
    situations.act('mission', mid, 'approve_plan', option_id=f'approve_plan:{rev}:approve', payload={}, actor=dict(MOM))
    check(_plan_of(mid)['state'] == 'approved' and _new_party() is None, "approved; still nothing written")

    # 3. Stage 1: the party and its people.
    party_ref = {'$ref': 'r1', 'kind': 'occasion'}
    _plan({'action': 'stage', 'stage_id': 's1', 'rows': [
        {'id': 'r1', 'tool': 'add_occasion', 'args': {'title': "Kate's birthday", 'anchor_date': '2027-03-20', 'kind': 'birthday'},
         'summary': "Make Kate's birthday on March 20"},
        {'id': 'r2', 'tool': 'answer_occasion_question', 'args': {'occasion_id': party_ref, 'key': 'headcount', 'value': 14}, 'summary': '14 people', 'needs': ['r1']},
        {'id': 'r3', 'tool': 'answer_occasion_question', 'args': {'occasion_id': party_ref, 'key': 'cake', 'value': True}, 'summary': 'a cake', 'needs': ['r1']},
        {'id': 'r4', 'tool': 'answer_occasion_question', 'args': {'occasion_id': party_ref, 'key': 'theme', 'value': 'dinosaurs'}, 'summary': 'dinosaurs', 'needs': ['r1']},
        {'id': 'r5', 'tool': 'answer_occasion_question', 'args': {'occasion_id': party_ref, 'key': 'whose_party', 'value': 'Kate'}, 'summary': "Kate's party", 'needs': ['r1']},
        {'id': 'r6', 'tool': 'add_occasion_guests', 'args': {'occasion_id': party_ref, 'who': 'The Wilsons', 'headcount': 4}, 'summary': 'The Wilsons', 'needs': ['r1']},
        {'id': 'r7', 'tool': 'stamp_occasion_template', 'args': {'occasion_id': party_ref, 'keys': ['cake']}, 'summary': 'The cake errand', 'needs': ['r3']},
    ]})
    _step(mid)
    check(_new_party() is None, "proposing writes nothing")
    st = _approve(mid, 's1')
    check(st['state'] == 'done', f"stage 1 done: {[(r['id'], r['state'], (r.get('result') or {}).get('message')) for r in st['rows']]}")
    party = _new_party()
    check(party and party['id'] != 'last', "a NEW party")
    pid = party['id']
    check(party['answers'].get('headcount') == 14 and party['answers'].get('theme') == 'dinosaurs', f"the answers replayed: {party['answers']}")
    check((storage.get_plate('2027-03-20') or {}).get('serving_for') == 14, "the kitchen cooks for 14 that day")
    check([g['name'] for g in storage.get_occasion_guests(pid)] == ['The Wilsons'], "the guests")
    check([e.get('occasion_key') for e in storage.get_all_errands() if e.get('occasion_id') == pid] == ['cake'], "the cake errand")
    check(not storage.get_occasion_guests('last') and not (storage.get_occasion('last').get('answers') or {}), "last year's party untouched")
    check(missions.subject_of(storage.get_mission(mid))[:2] == ('occasion', pid), "the party is the mission's subject")

    # 4. Stage 2: food — steered once, then approved in words in the private chat.
    _plan({'action': 'stage', 'stage_id': 's2', 'rows': [
        {'id': 'r1', 'tool': 'add_occasion_dishes', 'args': {'occasion_id': pid, 'description': 'dino nuggets, chocolate cake'}, 'summary': 'Nuggets and cake'},
        {'id': 'r2', 'tool': 'set_occasion_menu', 'args': {'occasion_id': pid, 'dish_ids': {'$ref': 'r1', 'kind': 'dish', 'all': True}},
         'summary': 'Put them on the menu', 'needs': ['r1']}]})
    _step(mid)
    first = _stage(mid, 's2')
    old_props = [r['proposal_id'] for r in first['rows']]
    missions.answer(mid, 'make it pizza instead of nuggets', dict(MOM))
    st = _stage(mid, 's2')
    check(st['state'] == 'pending' and all(storage.get_action_proposal(p)['status'] == 'withdrawn' for p in old_props),
          f"a steer on a waiting stage withdraws it for re-proposal: {st['state']} {[storage.get_action_proposal(p)['status'] for p in old_props]}")
    _plan({'action': 'stage', 'stage_id': 's2', 'rows': [
        {'id': 'r1', 'tool': 'add_occasion_dishes', 'args': {'occasion_id': pid, 'description': 'dino pizza, chocolate cake'}, 'summary': 'Pizza and cake'},
        {'id': 'r2', 'tool': 'set_occasion_menu', 'args': {'occasion_id': pid, 'dish_ids': {'$ref': 'r1', 'kind': 'dish', 'all': True}},
         'summary': 'Put them on the menu', 'needs': ['r1']}]})
    _step(mid)
    check(_stage(mid, 's2')['state'] == 'proposed' and _stage(mid, 's2')['snapshot'] != first['snapshot'], "re-proposed")
    argyle = storage.ensure_argyle_member()
    dm = storage.get_or_create_dm(argyle['id'], 'mom')
    triage.set_focus(f"channel:{dm['id']}", 'mission', mid, 'Kate party')
    res = tools.act_on_situation(verb='run_stage', text='yes, do the menu', acting_member=dict(MOM), focus_key=f"channel:{dm['id']}")
    check(res['status'] == 'success' and _stage(mid, 's2')['state'] == 'done', f"approved in words in her own Argyle chat: {res}")
    menu = sorted(d['name'] for d in occasions.menu(pid)['dishes'])
    check(menu == ['chocolate cake', 'dino pizza'], f"the menu holds every dish the row made: {menu}")
    check(all(storage.get_dish(d)['scope'] == 'occasion' for d in ('d-dino-pizza', 'd-chocolate-cake')), "party-only dishes")

    # 5. Supplies, presents, invitations.
    _plan({'action': 'stage', 'stage_id': 's3', 'rows': [
        {'id': 'r1', 'tool': 'source_for_occasion', 'args': {'occasion_id': pid, 'needed': 'dinosaur plates, balloons, candles'}, 'summary': 'A supplies list'}]})
    _step(mid)
    _approve(mid, 's3')
    check(any(l.get('occasion_id') == pid for l in storage.get_shopping_lists()), "a supplies list for the party")
    _plan({'action': 'stage', 'stage_id': 's4', 'rows': [
        {'id': 'r1', 'tool': 'add_occasion_gift_list', 'args': {'occasion_id': pid}, 'summary': 'A private presents list'}]})
    _step(mid)
    st = _approve(mid, 's4')
    gift = storage.get_shopping_list(st['rows'][0]['result']['created'][0]['id'])
    check(gift['audience'] == 'private' and not scope.audience_allows(gift, 'shopping_list', dict(KID)), "Kate cannot see her presents list")
    _plan({'action': 'stage', 'stage_id': 's5', 'rows': [
        {'id': f'r{i}', 'tool': 'draft_message', 'args': {'to': who, 'words': f"Kate's dino party, March 20 at 2!"}, 'summary': f'Invite {who}'}
        for i, who in enumerate(('The Wilsons', 'Grandma', 'Aunt Jo'))]})
    _step(mid)
    _approve(mid, 's5')

    # 6. The finish.
    _plan({'action': 'finish', 'summary': "Kate's party is planned.", 'next_action': 'send the three invitations'})
    _step(mid)
    check(_plan_of(mid)['state'] == 'done', f"done: {_plan_of(mid)['state']}")
    done = [d['card'] for d in DMS if d['card'] and d['card'].get('kind') == 'mission_done']
    check(done and len(done[-1]['drafts']) == 3 and {d['to'] for d in done[-1]['drafts']} == {'The Wilsons', 'Grandma', 'Aunt Jo'},
          f"the three drafts are handed over: {done and done[-1]}")
    check(isinstance(done[-1]['open'], list), "with what is still open")


SCENARIOS = [scenario_the_whole_party]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)

"""Occasion tools a build stage can use (planned missions spec §3, Occasions
row; Codex F1, F5, F6, F7, F11).

Pinned here (Task 5):
  * `add_occasion` takes an `idem` (a repeat returns the same occasion) and
    says what it created (`created`, `occasion_id`);
  * guests, attendance and sourcing take an `occasion_id`, so a stage never
    writes to last year's party of the same name;
  * NEW `answer_occasion_question` runs the template's own cascade (headcount
    reaches the kitchen); NEW `stamp_occasion_template` stamps the template's
    work; NEW `add_occasion_dishes` makes occasion-scoped dishes, never the
    everyday repertoire, and returns their ids; NEW `set_occasion_menu`;
  * NEW `add_occasion_gift_list`: a PRIVATE presents list shared with every
    active parent except the person the party is for; refused when that leaves
    nobody; the hand path is `POST /api/occasions/{id}/gift-list`;
  * an approved proposal keeps the handler's `created` and stores the result
    on the proposal row;
  * every new tool is a proposable write declared to chat.

Run from chauffeur/:  python tests/test_planned_occasion_tools.py
"""
from harness import check  # noqa: F401
from services import storage, scope, missions, occasions, meals
from services import agent_tools_v2 as tools
from test_subjects import _reset, _seed, MOM, DAD, AUNT, KID
from test_subject_audience import _as

NEW_TOOLS = ('answer_occasion_question', 'stamp_occasion_template', 'add_occasion_dishes', 'set_occasion_menu', 'add_occasion_gift_list')


def _fresh():
    _reset()
    for t in (storage.dishes_table, storage.plates_table, storage.errands_table, storage.agent_action_proposals_table):
        t.truncate()
    _seed()
    storage.save_occasion({'id': 'old', 'title': "Kate's birthday", 'kind': 'birthday', 'anchor_date': '2026-02-14', 'status': 'done'})
    made = tools.execute_tool('add_occasion', {'title': "Kate's birthday", 'anchor_date': '2027-02-14', 'kind': 'birthday', 'idem': 'occ-1'},
                              actor=dict(MOM))
    return made


def _x(name, args, actor=MOM):
    return tools.execute_tool(name, args, actor=dict(actor) if actor else None)


def scenario_add_occasion_is_idempotent_and_says_what_it_made():
    made = _fresh()
    oid = made.get('occasion_id')
    check(made.get('status') == 'success' and oid and oid != 'old' and made.get('created') == [{'kind': 'occasion', 'id': oid}], f"{made}")
    again = _x('add_occasion', {'title': "Kate's birthday", 'anchor_date': '2027-02-14', 'kind': 'birthday', 'idem': 'occ-1'})
    check(again.get('occasion_id') == oid, f"a repeat returns the same occasion: {again}")
    check(len([o for o in storage.get_occasions(include_done=True) if o['title'] == "Kate's birthday"]) == 2, "last year's and this year's, no third")


def scenario_people_and_sourcing_go_to_the_occasion_by_id():
    oid = _fresh()['occasion_id']
    out = _x('add_occasion_guests', {'occasion_id': oid, 'who': 'The Wilsons', 'headcount': 4})
    check(out.get('status') == 'success', f"{out}")
    check([g['name'] for g in storage.get_occasion_guests(oid)] == ['The Wilsons'] and not storage.get_occasion_guests('old'),
          "this year's party, never last year's of the same name")
    out = _x('set_occasion_attendance', {'occasion_id': oid, 'who': 'Dad', 'coming': False})
    check(out.get('status') == 'success', f"attendance by id: {out}")
    seen = []
    orig = occasions.generate_list
    occasions.generate_list = lambda occasion_id, request, **k: seen.append(occasion_id) or {'list': {'id': 'gen', 'name': 'Party supplies'}, 'items': []}
    try:
        _x('source_for_occasion', {'occasion_id': oid, 'needed': 'party supplies and decorations'})
    finally:
        occasions.generate_list = orig
    check(seen == [oid], f"sourcing for this year's party: {seen}")


def scenario_the_interview_answer_and_template_tools():
    oid = _fresh()['occasion_id']
    out = _x('answer_occasion_question', {'occasion_id': oid, 'key': 'headcount', 'value': 14})
    check(out.get('status') == 'success' and storage.get_occasion(oid)['answers'].get('headcount') == 14, f"answered: {out}")
    plate = storage.get_plate('2027-02-14') or {}
    check(plate.get('serving_for') == 14, f"the cascade ran: the kitchen cooks for 14 that day: {plate}")
    _x('answer_occasion_question', {'occasion_id': oid, 'key': 'cake', 'value': True})
    out = _x('stamp_occasion_template', {'occasion_id': oid, 'keys': ['cake']})
    check(out.get('status') == 'success', f"stamped: {out}")
    errands = [e for e in storage.get_all_errands() if e.get('occasion_id') == oid]
    check([e.get('occasion_key') for e in errands] == ['cake'], f"the cake errand, from the template: {errands}")
    bad = _x('answer_occasion_question', {'occasion_id': 'nope', 'key': 'headcount', 'value': 3})
    check(bad.get('status') == 'error', "no such occasion")


def scenario_party_dishes_never_join_the_everyday_repertoire():
    oid = _fresh()['occasion_id']
    orig = meals.add_dishes_from_text

    def fake(description):
        rows = []
        for name in [s.strip() for s in description.split(',') if s.strip()]:
            row = {'id': f"d-{name.replace(' ', '-')}", 'name': name, 'tags': [], 'scope': 'everyday'}
            storage.add_dish(dict(row))
            rows.append(row)
        return {'added': rows}
    meals.add_dishes_from_text = fake
    try:
        out = _x('add_occasion_dishes', {'occasion_id': oid, 'description': 'chocolate cake, dino nuggets'})
    finally:
        meals.add_dishes_from_text = orig
    ids = [c['id'] for c in out.get('created') or [] if c.get('kind') == 'dish']
    check(out.get('status') == 'success' and len(ids) == 2, f"two dishes, by id: {out}")
    for did in ids:
        d = storage.get_dish(did)
        check(d['scope'] == 'occasion' and 'birthday' in d['tags'], f"occasion-scoped and tagged: {d}")
    out = _x('set_occasion_menu', {'occasion_id': oid, 'dish_ids': ids})
    check(out.get('status') == 'success' and sorted(d['id'] for d in occasions.menu(oid)['dishes']) == sorted(ids), f"the menu: {out}")


def scenario_the_presents_list_is_private_from_the_person_it_is_for():
    oid = _fresh()['occasion_id']
    storage.update_occasion(oid, {'answers': {'whose_party': 'Kate'}})
    out = _x('add_occasion_gift_list', {'occasion_id': oid, 'idem': 'g-1'})
    check(out.get('status') == 'success' and out.get('created') and out['created'][0]['kind'] == 'list', f"made: {out}")
    lst = storage.get_shopping_list(out['created'][0]['id'])
    check(lst['audience'] == 'private' and set(lst['shared_with']) == {'mom', 'dad'} and lst.get('occasion_id') == oid,
          f"private, the parents only: {lst}")
    check(not scope.audience_allows(lst, 'shopping_list', KID) and not scope.audience_allows(lst, 'shopping_list', AUNT),
          "Kate cannot see it, nor an adult who is not a parent")
    again = _x('add_occasion_gift_list', {'occasion_id': oid, 'idem': 'g-1'})
    check(again['created'][0]['id'] == lst['id'], "a repeat returns the same list")
    storage.save_occasion({'id': 'mom40', 'title': "Mom's 40th", 'kind': 'birthday', 'anchor_date': '2027-05-01',
                           'answers': {'whose_party': 'Mom'}})
    mine = _x('add_occasion_gift_list', {'occasion_id': 'mom40', 'idem': 'g-2'}, actor=DAD)
    row = storage.get_shopping_list(mine['created'][0]['id'])
    check(set(row['shared_with']) == {'dad'}, f"a parent's own birthday: hidden from her, shared with the other parent: {row}")
    storage.update_member('dad', {'status': 'archived'})
    alone = _x('add_occasion_gift_list', {'occasion_id': 'mom40', 'idem': 'g-3'})
    check(alone.get('status') == 'error', f"nobody left to share it with: refused, never a list nobody sees: {alone}")


def scenario_the_gift_list_hand_path():
    import main
    oid = _fresh()['occasion_id']
    storage.update_occasion(oid, {'answers': {'whose_party': 'Kate'}})
    res = main.occasion_gift_list(oid, request=_as('mom'))
    lst = storage.get_shopping_list(res['list']['id'])
    check(lst['audience'] == 'private' and set(lst['shared_with']) == {'mom', 'dad'}, f"the page makes the same list: {res}")
    from services import auth
    check(any(r[1] == '/api/occasions/*' for r in auth.RULES), "the route is classified")
    html = open('templates/occasions.html', encoding='utf-8').read()
    check('gift-list' in html, "the occasion page has the button")


def scenario_an_approved_proposal_keeps_what_it_created():
    _fresh()
    from services import chat_actions
    made = chat_actions.create_action_proposal('add_occasion', 'Make the party', {'title': 'Pool party', 'anchor_date': '2027-07-04',
                                                                                  'kind': 'party', 'idem': 'pp'},
                                               created_by_member_id='mom', extra_allowed=missions.proposable_tools())
    res = chat_actions.act_on_proposal(made['proposal_id'], 'approve', dict(MOM))
    check(res.get('status') == 'success' and res.get('created') and res['created'][0]['kind'] == 'occasion', f"the result says what it made: {res}")
    row = storage.get_action_proposal(made['proposal_id'])
    check((row.get('result') or {}).get('created') == res['created'], f"and the proposal row keeps it: {row.get('result')}")


def scenario_every_new_tool_is_a_proposable_write():
    declared = {t['name'] for t in tools.get_available_tools()}
    for name in NEW_TOOLS:
        check(name in declared and name in tools.TOOL_HANDLERS and name in tools.TOOL_SCHEMAS, f"{name} declared and registered")
        check(name in missions.proposable_tools() and name not in missions.READ_TOOLS, f"{name} proposable, not a READ")


SCENARIOS = [
    scenario_add_occasion_is_idempotent_and_says_what_it_made,
    scenario_people_and_sourcing_go_to_the_occasion_by_id,
    scenario_the_interview_answer_and_template_tools,
    scenario_party_dishes_never_join_the_everyday_repertoire,
    scenario_the_presents_list_is_private_from_the_person_it_is_for,
    scenario_the_gift_list_hand_path,
    scenario_an_approved_proposal_keeps_what_it_created,
    scenario_every_new_tool_is_a_proposable_write,
]

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

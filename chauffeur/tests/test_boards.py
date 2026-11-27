"""Presentation validation and public shape tests."""
import copy
import os
import json
from pathlib import Path
import traceback
from harness import check
from services import storage, boards as b, boards_contract as C

MISSION = {'id': 'mission', 'project_id': 'a' * 32, 'created_by': 'parent', 'goal': 'Concert outfit'}
def seed():
    storage.lookups_table.truncate(); storage.boards_table.truncate()
    for i, price in enumerate((118, 140, 167)):
        storage.lookups_table.insert(dict(id='lk_' + str(i) * 10, mission_id='mission', title='Shoes',
            url='https://store.test/item', final_url='https://store.test/final', image_url='https://store.test/i.png',
            store='Store', price=price, currency='USD', available=True))
    return dict(title='Concert outfit', layout='options', noun='looks', slots=[{'role': 'Shoes'}],
                options=[dict(title='Look ' + str(i), items=[dict(slot=0, lookup='lk_' + str(i) * 10, facts=[])]) for i in range(3)], commit='buy')

def build(action=None):
    fields, error = b.build_from_present(action or seed(), MISSION)
    check(error is None, error)
    return b.create(fields)

def scenario_present_builds_from_lookups():
    a = seed(); a['options'][0]['items'][0].update(url='javascript:x', price=1, store='Fake', image='bad')
    board = build(a); item = board['options'][0]['items'][0]
    check(item['url'] == 'https://store.test/final' and item['price']['amount'] == 118 and item['store'] == 'Store', item)
    a.pop('noun'); check(build(a)['noun'] == 'options', 'default noun')

def scenario_unknown_lookup_drops_item_and_option():
    a = seed(); a['options'][0]['items'][0]['lookup'] = 'lk_fake'
    check(len(build(a)['options']) == 2, 'invalid option dropped')
    a = seed(); a['slots'].append({'role': 'Top'})
    for option in a['options']: option['items'].append(dict(slot=1, lookup='lk_1111111111'))
    a['options'][0]['items'][1]['lookup'] = 'lk_fake'
    check(len(build(a)['options']) == 2, 'incomplete multi-slot option dropped')

def scenario_too_few_options_refuses_with_note():
    a = seed()
    for o in a['options'][:2]: o['items'][0]['lookup'] = 'lk_fake'
    fields, note = b.build_from_present(a, MISSION)
    check(fields is None and 'lookup' in note.lower(), note)
    check(b.build_from_present(seed(), {'id':'mission'})[0] is None, 'project required')

def scenario_limits():
    for mutate in (lambda a: a.update(options=a['options'] * 3), lambda a: a.update(slots=[{'role':'x'}]*7)):
        a = seed(); mutate(a); check(b.build_from_present(a, MISSION)[0] is None, 'limits')
    a=seed();a['options'][0]['items'][0]['facts']=[{'label':'x','value':'y'}]*5
    check(len(build(a)['options'])==2,'excess facts drop the item and its empty option')

def scenario_null_facts_and_bad_items_are_local():
    a=seed();a['options'][0]['items'][0]['facts']=None
    check(build(a)['options'][0]['items'][0]['facts']==[],'null facts normalize to empty')

def scenario_invalid_slot_and_facts_only_drop_the_item():
    for bad in (dict(slot=9,lookup='lk_0000000000'),dict(slot=0,lookup='lk_0000000000',facts='bad'),None):
        a=seed();a['options'][0]['items'].append(bad)
        board=build(a)
        check(len(board['options'])==3 and len(board['options'][0]['items'])==1,'one bad item cannot refuse a good board')

def scenario_unknown_layout_becomes_list():
    a = seed(); a['layout'] = 'new'; a['options'] = a['options'][:1]
    check(build(a)['layout'] == 'list', 'unknown layout')

def scenario_totals_and_summary_line():
    fixture = json.loads((Path(__file__).parent / 'fixtures/board_view_v1.json').read_text(encoding='utf-8'))
    for v in fixture['views'].values():
        check(b.summary_line(v) == v['summary_line'], 'fixture summary: ' + v['layout'])
        check([b._total(o) for o in v['options']] == [o['total'] for o in v['options']], 'fixture totals')
    board = build(); check(b.summary_line(board) == '3 looks' + C.SEPARATOR + 'from $118', b.summary_line(board))
    board['slots'].append({'id':'extra','role':'Top'})
    board['options'][0]['items'].append({**board['options'][0]['items'][0], 'price':None})
    check(b.view(board, {})['options'][0]['total'] is None, 'missing price has no partial total')
    board['options'][2]['items'][0]['price']['currency'] = 'EUR'
    check('from' not in b.summary_line(board), 'mixed currencies')
    for o in board['options']:
        for i in o['items']: i['price'] = None
    check(b.summary_line(board) == '3 looks', 'no prices')
    board['layout'] = 'list'; check(b.summary_line(board) == '4 looks', 'list counts items, never price')

def scenario_view_matches_contract():
    board = build(); v = b.view(board, {})
    check(set(v) == C.VIEW_KEYS and set(b.card(board)) == C.CARD_KEYS and set(b.row(board)) == C.ROW_KEYS, 'top keys')
    check(set(b.row(board)['sheet']) == C.ROW_SHEET_KEYS, 'row sheet')
    for o in v['options']:
        check(set(o) == C.OPTION_KEYS, 'option keys')
        for i in o['items']:
            check(set(i) == C.ITEM_KEYS and C.IMAGE_PATH.fullmatch(i['image']), i)
    check(set(v['can']) == C.CAN_KEYS and not any(v['can'].values()), 'read-only')

def scenario_spoken():
    board = build()
    check(b.spoken(board) == 'I found 3 looks for Concert outfit, from 118 to 167 dollars. Open the board on your phone to pick.', b.spoken(board))
    for o in board['options']: o['items'][0]['price']['amount'] = 118
    check(b.spoken(board) == 'I found 3 looks for Concert outfit, at 118 dollars. Open the board on your phone to pick.', b.spoken(board))
    board['title'] = 'The concert outfit'
    check('for the concert outfit' in b.spoken(board), 'only leading The is lowercased')
    board['title'] = 'Concert outfit'
    for o in board['options']: o['items'][0]['price'] = None
    check(b.spoken(board) == 'I found 3 looks for Concert outfit. Open the board on your phone to pick.', b.spoken(board))

def scenario_delete_for_project_removes_lookups_and_dir():
    board = build(); os.makedirs(b.image_dir(board['id']), exist_ok=True)
    check(b.delete_for_project(MISSION['project_id']) == [board['id']], 'deleted ids')
    check(not b.for_project(MISSION['project_id']) and not storage.lookups_table.all() and not os.path.exists(b.image_dir(board['id'])), 'cleanup')

if __name__ == '__main__':
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith('scenario_'):
            try: fn(); print('PASS', name)
            except Exception: failed += 1; print('FAIL', name); traceback.print_exc()
    raise SystemExit(bool(failed))

"""The presentation-board contract: the shared fixture keeps the agreed shapes.

Server and renderers both build against tests/fixtures/board_view_v1.json; this
test holds that fixture to services/boards_contract.py so neither side drifts.
Run from chauffeur/: python tests/test_board_contract.py
"""
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import boards_contract as C  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'board_view_v1.json')
DATA = json.load(open(FIXTURE, encoding='utf-8'))


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _keys(obj, want, where):
    check(isinstance(obj, dict), f'{where}: not an object')
    got = set(obj)
    check(got == set(want), f'{where}: keys {sorted(got ^ set(want))} differ from the contract')


def _money(m, where):
    if m is None:
        return
    _keys(m, C.MONEY_KEYS, where)
    check(isinstance(m['amount'], (int, float)) and isinstance(m['currency'], str), f'{where}: bad money')


def scenario_fixture_matches_contract():
    for name, view in DATA['views'].items():
        _keys(view, C.VIEW_KEYS, f'view {name}')
        check(view['layout'] in C.LAYOUTS, f'{name}: layout')
        check(view['commit'] in C.COMMITS, f'{name}: commit')
        _keys(view['can'], C.CAN_KEYS, f'{name}.can')
        check(not any(view['can'].values()), f'{name}: slice 1 draws no controls, can must be all false')
        slot_ids = set()
        for s in view['slots']:
            _keys(s, C.SLOT_KEYS, f'{name} slot')
            slot_ids.add(s['id'])
        for o in view['options']:
            _keys(o, C.OPTION_KEYS, f'{name} option {o.get("id")}')
            _money(o['total'], f'{name} option total')
            for i in o['items']:
                _keys(i, C.ITEM_KEYS, f'{name} item {i.get("id")}')
                check(i['slot_id'] in slot_ids, f'{name} item {i["id"]}: unknown slot')
                _money(i['price'], f'{name} item price')
                check(len(i['facts']) <= C.MAX_FACTS, f'{name} item {i["id"]}: too many facts')
                for fact in i['facts']:
                    _keys(fact, C.FACT_KEYS, f'{name} fact')
                check(i['url'].startswith(('http://', 'https://')), f'{name} item {i["id"]}: url scheme')
    for card in DATA['cards']:
        _keys(card, C.CARD_KEYS, 'card')
        check(card['kind'] == 'board', 'card kind')
        check(len(card['hero']) <= C.MAX_HERO and None not in card['hero'], 'card hero')
    for row in DATA['rows']:
        _keys(row, C.ROW_KEYS, 'row')
        check(row['kind'] == 'board' and row['group'] == 'now' and row['actions'] == [], 'row kind/group/actions')
        _keys(row['sheet'], C.ROW_SHEET_KEYS, 'row.sheet')
        check(row['sheet']['kind'] == 'board', 'row.sheet kind')
    done = DATA['mission_done']
    check(done['kind'] == 'mission_done', 'done card kind')
    for b in done[C.DONE_CARD_BOARD_KEY]:
        _keys(b, C.DONE_BOARD_KEYS, 'done card board')


def scenario_image_paths_relative():
    paths = [i['image'] for v in DATA['views'].values() for o in v['options'] for i in o['items'] if i['image']]
    paths += [p for c in DATA['cards'] for p in c['hero']]
    check(paths, 'fixture has images')
    for p in paths:
        check(not p.startswith('/'), f'{p}: image paths are relative (ingress)')
        m = C.IMAGE_PATH.match(p)
        check(m, f'{p}: not an image route path')


def scenario_summary_lines_follow_the_rule():
    sep = C.SEPARATOR
    v = DATA['views']
    check(v['options']['summary_line'] == f'3 looks{sep}from $118', v['options']['summary_line'])
    check(v['compare']['summary_line'] == f'3 camps{sep}from $310', v['compare']['summary_line'])
    check(v['list']['summary_line'] == '3 things', v['list']['summary_line'])
    totals = [o['total'] for o in v['options']['options']]
    check(totals[1] is None, 'an option missing a price has a null total')
    check(totals[0] == {'amount': 118, 'currency': 'USD'}, 'look 1 total is the sum of its prices')


def scenario_deep_links():
    links = DATA['deep_links']
    m = C.DEEP_LINK.match(links['good'])
    check(m and m.group(1) == DATA['views']['options']['project_id'] and m.group(2) == DATA['views']['options']['id'],
          'good deep link parses to project and board')
    for bad in links['bad']:
        check(not C.DEEP_LINK.match(bad), f'{bad} must not parse')


def scenario_fixture_carries_hostile_strings():
    o3 = DATA['views']['options']['options'][2]
    check('<script>' in o3['title'] and "'" in o3['title'] and '"' in o3['title'], 'option 3 title is hostile')
    check(any("'" in i['store'] and '<b>' in i['store'] for i in o3['items']), 'a hostile store name')


SCENARIOS = [v for k, v in list(globals().items()) if k.startswith('scenario_')]
if __name__ == '__main__':
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print('PASS', fn.__name__)
        except Exception:
            failed += 1
            print('FAIL', fn.__name__)
            traceback.print_exc()
    raise SystemExit(bool(failed))

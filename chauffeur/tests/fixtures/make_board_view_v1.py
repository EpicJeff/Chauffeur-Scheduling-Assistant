"""Writes tests/fixtures/board_view_v1.json, the presentation-board contract sample.

Run from chauffeur/: python tests/fixtures/make_board_view_v1.py
The JSON is committed; this script documents how it was built and keeps it
consistent (totals, summary lines, image paths) when it has to change.
"""
import json
import os

PID = '0f1e2d3c4b5a69788796a5b4c3d2e1f0'
BOARD = 'b0a7d1e2f3a4b5c6d7e8f90a1b2c3d4e'
CAMPS = 'c0a1e2f3a4b5c6d7e8f90a1b2c3d4e5f'
PACK = 'd0a1e2f3a4b5c6d7e8f90a1b2c3d4e5f'
NONE = {'react': False, 'keep': False, 'find_more': False, 'copy': False, 'commit': False}


def img(bid, n):
    return f'api/projects/{PID}/boards/{bid}/image/lk_{n:010x}'


def usd(x):
    return {'amount': x, 'currency': 'USD'}


def item(bid, iid, slot, title, store, n, price, facts=(), image=True):
    return {'id': iid, 'slot_id': slot, 'title': title, 'url': f'https://demo.invalid/{store.lower().replace(" ", "-")}/{n}',
            'store': store, 'image': img(bid, n) if image else None, 'price': price,
            'facts': [{'label': a, 'value': b} for a, b in facts]}


def board(bid, title, ask, layout, noun, commit, summary, slots, options):
    return {'id': bid, 'project_id': PID, 'title': title, 'ask': ask, 'layout': layout, 'noun': noun,
            'commit': commit, 'version': 1, 'copied_from': None, 'summary_line': summary,
            'slots': slots, 'options': options, 'keeps': {}, 'shortlist': [], 'reactions': {}, 'can': dict(NONE)}


outfit_slots = [{'id': 's0', 'role': 'Dress or top'}, {'id': 's1', 'role': 'Skirt'},
                {'id': 's2', 'role': 'Tights'}, {'id': 's3', 'role': 'Heels 2"'}]
outfit = board(BOARD, 'Concert outfit',
               'Find an outfit for a band concert: black dress, or black button-down and skirt, black tights, black 2-inch heels.',
               'options', 'looks', 'buy', '3 looks · from $118', outfit_slots, [
    {'id': 'o1', 'title': 'Look 1', 'note': 'Midi dress, opaque tights, block heel', 'round': 0, 'total': usd(118), 'items': [
        item(BOARD, 'i1', 's0', 'Black midi dress', 'Demo Dresses', 1, usd(79)),
        item(BOARD, 'i2', 's2', 'Opaque tights, 80 denier', 'Demo Hosiery', 2, usd(12), [('Pack', '2 pairs')]),
        item(BOARD, 'i3', 's3', 'Block heel pump, 2 in', 'Demo Shoes', 3, usd(27), [('Heel', '2 in'), ('Width', 'Regular')])]},
    {'id': 'o2', 'title': 'Look 2', 'note': 'Button-down and skirt; the heel price was not on the page', 'round': 0, 'total': None, 'items': [
        item(BOARD, 'i4', 's0', 'Black button-down shirt', 'Demo Shirts', 4, usd(34)),
        item(BOARD, 'i5', 's1', 'Black A-line skirt', 'Demo Skirts', 5, usd(41)),
        item(BOARD, 'i6', 's2', 'Sheer black tights', 'Demo Hosiery', 6, usd(9)),
        item(BOARD, 'i7', 's3', 'Pointed pump, 2 in', 'Demo Shoes', 7, None, image=False)]},
    {'id': 'o3', 'title': 'Look "3" <script>x</script> it\'s', 'note': '<img src=x onerror=alert(1)>', 'round': 0,
     'total': usd(167), 'items': [
        item(BOARD, 'i8', 's0', 'Wrap dress', 'O\'Neil "&" <b>', 8, usd(98)),
        item(BOARD, 'i9', 's2', 'Fleece-lined tights', 'Demo Hosiery', 9, usd(14)),
        item(BOARD, 'i10', 's3', 'Strap heel, 2 in', 'Demo Shoes', 10, usd(55))]},
])

camps = board(CAMPS, 'Summer day camps', 'Compare three day camps for week 2 of July.', 'compare', 'camps', 'book',
              '3 camps · from $310', [{'id': 's0', 'role': 'Camp'}], [
    {'id': f'o{n}', 'title': name, 'note': None, 'round': 0, 'total': usd(price), 'items': [
        item(CAMPS, f'i{n}', 's0', name, store, 20 + n, usd(price),
             [('Dates', dates), ('Ages', ages), ('Distance', dist), ('Hours', hours)])]}
    for n, (name, store, price, dates, ages, dist, hours) in enumerate([
        ('Lakeside Day Camp', 'Demo Parks', 310, 'Jul 13-17', '6-12', '4 mi', '9-3'),
        ('Maker Camp', 'Demo Makerspace', 395, 'Jul 13-17', '8-13', '7 mi', '9-4'),
        ('Nature Explorers', 'Demo Nature Center', 340, 'Jul 13-17', '5-10', '11 mi', '9-2')], 1)])

pack = board(PACK, 'Camp packing list', 'What to buy for sleepaway camp.', 'list', 'things', 'none', '3 things',
             [{'id': 's0', 'role': 'Thing'}], [
    {'id': 'o1', 'title': 'Packing list', 'note': None, 'round': 0, 'total': None, 'items': [
        item(PACK, 'i1', 's0', 'Water bottle, 24 oz', 'Demo Outdoors', 31, usd(18)),
        item(PACK, 'i2', 's0', 'Headlamp', 'Demo Outdoors', 32, None),
        item(PACK, 'i3', 's0', 'Name labels, 100', 'Demo Labels', 33, usd(8.5))]}])


def card(b, kept=0, note=None):
    hero = [i['image'] for i in b['options'][0]['items'] if i['image']][:4]
    return {'kind': 'board', 'board_id': b['id'], 'project_id': PID, 'title': b['title'],
            'summary_line': b['summary_line'], 'kept': kept, 'hero': hero, 'note': note}


def row(b, kept=0):
    sub = b['summary_line'] + (f' · {kept} kept' if kept else '')
    return {'kind': 'board', 'group': 'now', 'title': b['title'], 'subtitle': sub,
            'sheet': {'kind': 'board', 'id': b['id'], 'project_id': PID}, 'actions': []}


data = {
    '_about': 'Presentation-board contract sample. Keys are held by services/boards_contract.py; '
              'regenerate with python tests/fixtures/make_board_view_v1.py.',
    'views': {'options': outfit, 'compare': camps, 'list': pack},
    'cards': [card(outfit), card(camps), card(pack, kept=2, note='3 more looks around your kept dress and heels')],
    'rows': [row(outfit), row(pack, kept=2)],
    'mission_done': {'kind': 'mission_done', 'mission_id': 'e0a1e2f3a4b5c6d7e8f90a1b2c3d4e5f',
                     'summary': 'Three looks from $118 to $167.', 'drafts': [], 'open': [],
                     'boards': [{'board_id': BOARD, 'project_id': PID, 'title': 'Concert outfit'}]},
    'deep_links': {'good': f'#board-{PID}-{BOARD}', 'bad': ['#board-', '#board-xyz-123', '#board-abc', f'#board-{PID}-{BOARD}-x']},
}

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'board_view_v1.json')
with open(out, 'w', encoding='utf-8', newline='\n') as f:
    json.dump(data, f, indent=1, ensure_ascii=False)
    f.write('\n')
print(out)

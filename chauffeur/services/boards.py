"""Provenance-checked, read-only presentation boards (schema v1)."""
import copy
import io
import math
import os
import re
import shutil
import time
from uuid import uuid4
from tinydb import Query
from services import storage, page_lookup, boards_contract as C

def build_from_present(action: dict, mission: dict):
    if not mission.get('project_id'):
        return None, 'This mission has no project to hold a board.'
    try:
        title = action.get('title')
        if not isinstance(title, str) or not title.strip() or len(title) > 80:
            raise ValueError('Give the board a title of at most 80 characters.')
        noun = action.get('noun', 'options')
        if not isinstance(noun, str) or not re.fullmatch(r'[A-Za-z][A-Za-z ]{0,19}', noun):
            raise ValueError('Use a plural noun of at most 20 letters and spaces.')
        layout = action.get('layout') if action.get('layout') in C.LAYOUTS else 'list'
        slots, options = action.get('slots'), action.get('options')
        minimum = 1 if layout == 'list' else 2
        if not isinstance(slots, list) or not 1 <= len(slots) <= 6:
            raise ValueError('Use 1 to 6 slots.')
        if not isinstance(options, list) or not minimum <= len(options) <= 8:
            raise ValueError(f'Use {minimum} to 8 options.')
        slots = [dict(id=uuid4().hex, role=str(s['role'])[:80]) for s in slots]
        lookups = {r['id']: r for r in page_lookup.for_mission(mission['id'])}
        built, missing = [], []
        for option in options:
            items = option.get('items')
            if not isinstance(items, list) or not 1 <= len(items) <= 6:
                raise ValueError('Use 1 to 6 items per option.')
            kept = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                slot = item.get('slot')
                if type(slot) is not int or not 0 <= slot < len(slots):
                    continue
                facts = item.get('facts', [])
                if facts is None: facts = []
                if not isinstance(facts, list) or len(facts) > C.MAX_FACTS or any(
                    not isinstance(f, dict) or set(f) != C.FACT_KEYS or any(
                        not isinstance(f[k], str) or len(f[k]) > 40 for k in ('label', 'value')) for f in facts):
                    continue
                lookup_id = item.get('lookup')
                record = lookups.get(lookup_id) if isinstance(lookup_id, str) else None
                if not record or not page_lookup.http_url(record.get('final_url') or record.get('url')):
                    missing.append(str(lookup_id)); continue
                amount = record.get('price'); currency = record.get('currency')
                price = {'amount': amount, 'currency': currency} if (
                    isinstance(amount, (int, float)) and not isinstance(amount, bool)
                    and math.isfinite(amount) and amount >= 0 and currency) else None
                kept.append(dict(id=uuid4().hex, slot_id=slots[slot]['id'], title=record.get('title') or '',
                    url=record.get('final_url') or record['url'], store=record.get('store') or '',
                    image=lookup_id if page_lookup.http_url(record.get('image_url')) else None,
                    price=price, facts=copy.deepcopy(facts), lookup_id=lookup_id))
            if not kept or (len(slots) > 1 and layout == 'options' and
                            {i['slot_id'] for i in kept} != {s['id'] for s in slots}):
                continue
            built.append(dict(id=uuid4().hex, title=str(option.get('title') or '')[:140],
                              note=str(option.get('note') or '')[:300] or None, round=0, items=kept))
        if len(built) < minimum:
            if missing:
                raise ValueError('Look up every item you show. Items ' + ', '.join(dict.fromkeys(missing)) +
                                 ' are not lookups from this mission; too few complete options remain.')
            raise ValueError('Too few complete options remain. Check each item\'s slot and facts.')
        return dict(project_id=mission['project_id'], thread_id=mission.get('thread_id') or (
                    mission.get('origin_ref') if mission.get('origin_kind') == 'thread' else None),
                    title=title.strip(), ask=mission.get('goal') or '', layout=layout, noun=noun.strip(),
                    slots=slots, options=built, commit=action.get('commit') if action.get('commit') in C.COMMITS else 'none',
                    mission_id=mission['id'], started_by=mission.get('created_by')), None
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        return None, str(exc) or 'Check the board structure and look up every item.'

def create(fields):
    now = time.time(); board = copy.deepcopy(fields)
    board.update(id=uuid4().hex, version=1, keeps={}, shortlist=[], reactions={}, copied_from=None,
                 rounds=[dict(mission_id=fields['mission_id'], started_by=fields.get('started_by'),
                              started_at=now, note=None, kept_at_start={})], created_at=now, updated_at=now)
    with storage.db_lock: storage.boards_table.insert(board)
    return board

def get(board_id):
    with storage.db_lock: return storage.boards_table.get(Query().id == board_id)

def can_see(board, viewer):
    """A board may expose only what its project and source mission expose."""
    from services import access, projects, planned
    if not board: return False
    project = storage.get_project(board['project_id'])
    if not (access.project_visible(project, viewer) if access.is_house(viewer) else projects.can_see(project, viewer)):
        return False
    rounds = board.get('rounds') or []
    mission_id = rounds[0].get('mission_id') if rounds else board.get('mission_id')
    source = storage.get_mission(mission_id) if mission_id else None
    # _dm_person withholds the card's words from a keeper-only projection.
    return source is None or (access.record_visible('mission', source, viewer) and not planned.is_keeper(source, viewer))

def discard(board_id):
    """Roll back a presentation refused by its work stage; retain its lookups."""
    with storage.db_lock:
        storage.boards_table.remove(Query().id == board_id)

def for_project(project_id):
    with storage.db_lock:
        return sorted(storage.boards_table.search(Query().project_id == project_id),
                      key=lambda b: b.get('created_at', 0), reverse=True)

def lookup_ids(board):
    return {i['lookup_id'] for o in board.get('options', []) for i in o.get('items', []) if i.get('lookup_id')}

def surviving_lookup_ids():
    with storage.db_lock:
        return {lid for board in storage.boards_table.all() for lid in lookup_ids(board)}

def image_dir(board_id):
    if not re.fullmatch('[0-9a-f]{32}', board_id): raise ValueError('Invalid board id.')
    return os.path.join(os.path.dirname(storage.DB_PATH), 'board_images', board_id)

def delete_for_project(project_id):
    with storage.db_lock:
        removed = for_project(project_id)
        keep = {lid for board in storage.boards_table.all() if board['project_id'] != project_id for lid in lookup_ids(board)}
        for board in removed:
            mids = {r['mission_id'] for r in board.get('rounds', [])}
            mids.update(r['mission_id'] for lid in lookup_ids(board) if (r := page_lookup.get(lid)))
            for mid in mids: page_lookup.delete_for_mission(mid, keep)
            try: shutil.rmtree(image_dir(board['id']))
            except FileNotFoundError: pass
        storage.boards_table.remove(Query().project_id == project_id)
        return [b['id'] for b in removed]

def image_bytes(board, lookup_id):
    """Only a member lookup's stored image, normalized once and cached locally."""
    from PIL import Image
    from services import deletion
    if not re.fullmatch(r'lk_[0-9a-f]{10}', lookup_id) or lookup_id not in lookup_ids(board):
        raise ValueError('No image on this board.')
    path = os.path.join(image_dir(board['id']), lookup_id + '.jpg')
    if os.path.isfile(path):
        with open(path, 'rb') as f: return f.read()
    record = page_lookup.get(lookup_id)
    if not record or not record.get('image_url'): raise ValueError('No image on this board.')
    _, status, data = page_lookup.fetch(record['image_url'], 5 * 1024 * 1024, images=True)
    if status != 200: raise ValueError('The image could not be read.')
    with Image.open(io.BytesIO(data), formats=['JPEG', 'PNG', 'WEBP', 'GIF']) as source:
        if source.width * source.height > 40_000_000: raise ValueError('That image is too large.')
        source.thumbnail((800, 800))
        if source.mode in ('RGBA', 'LA') or (source.mode == 'P' and 'transparency' in source.info):
            rgba = source.convert('RGBA')
            image = Image.new('RGB', source.size, 'white')
            image.paste(rgba, mask=rgba.getchannel('A'))
        else:
            image = source.convert('RGB')
        buf = io.BytesIO(); image.save(buf, format='JPEG', quality=82)
        data = buf.getvalue()
    with storage.db_lock:
        deletion.check()
        if not get(board['id']): raise ValueError('This board is no longer available.')
        os.makedirs(image_dir(board['id']), exist_ok=True)
        temp = path + '.' + uuid4().hex + '.tmp'
        try:
            with open(temp, 'wb') as f: f.write(data)
            os.replace(temp, path)
        finally:
            try: os.remove(temp)
            except FileNotFoundError: pass
    return data

def _total(option):
    prices = [i.get('price') for i in option['items']]
    if not prices or any(p is None for p in prices) or len({p['currency'] for p in prices}) != 1: return None
    return {'amount': round(sum(p['amount'] for p in prices), 2), 'currency': prices[0]['currency']}

def _prices(board):
    if board['layout'] == 'list': return []
    prices = ([_total(o) for o in board['options']] if board['layout'] == 'options' and len(board['slots']) > 1
              else [i.get('price') for o in board['options'] for i in o['items']])
    prices = [p for p in prices if p is not None]
    return prices if len({p['currency'] for p in prices}) == 1 else []

def _number(amount):
    return str(int(amount)) if amount == int(amount) else f'{amount:.2f}'

def _count(board):
    return sum(len(o['items']) for o in board['options']) if board['layout'] == 'list' else len(board['options'])

def summary_line(board):
    text = f"{_count(board)} {board['noun']}"; prices = _prices(board)
    if prices:
        lo = min(p['amount'] for p in prices); currency = prices[0]['currency']
        text += C.SEPARATOR + 'from ' + ('$' + _number(lo) if currency == 'USD' else _number(lo) + ' ' + currency)
    return text

def spoken(board):
    title = board['title']; title = title[0].lower() + title[1:] if title.startswith('The ') else title
    text = f"I found {_count(board)} {board['noun']} for {title}"
    prices = _prices(board)
    if prices:
        lo, hi = min(p['amount'] for p in prices), max(p['amount'] for p in prices)
        text += (f', at {_number(lo)}' if lo == hi else f', from {_number(lo)} to {_number(hi)}')
        text += ' ' + ('dollars' if prices[0]['currency'] == 'USD' else prices[0]['currency'])
    return text + '. Open the board on your phone to pick.'

def view(board, viewer):
    out = {k: copy.deepcopy(board[k]) for k in C.VIEW_KEYS - {'summary_line', 'can'}}
    out.update(summary_line=summary_line(board), can={k: False for k in C.CAN_KEYS})
    for option in out['options']:
        option['total'] = _total(option)
        for item in option['items']:
            lid = item.get('image')
            item['image'] = f"api/projects/{board['project_id']}/boards/{board['id']}/image/{lid}" if lid else None
            for key in list(item):
                if key not in C.ITEM_KEYS: del item[key]
    return out

def card(board):
    v = view(board, None)
    return dict(kind='board', board_id=board['id'], project_id=board['project_id'], title=board['title'],
                summary_line=v['summary_line'], kept=len(board['keeps']) + len(board['shortlist']),
                hero=[i['image'] for i in v['options'][0]['items'] if i['image']][:C.MAX_HERO], note=None)

def row(board):
    kept = len(board['keeps']) + len(board['shortlist'])
    return dict(kind='board', group='now', title=board['title'],
                subtitle=summary_line(board) + (C.SEPARATOR + f'{kept} kept' if kept else ''),
                sheet=dict(kind='board', id=board['id'], project_id=board['project_id']), actions=[])

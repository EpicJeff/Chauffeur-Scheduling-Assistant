"""Supply intake A5 — the gift shortlist, and the rule it exists to enforce.

**The model never names a product.** Asked for gift ideas an LLM returns
"LEGO Friends Beach House, $34.99" with an invented SKU and a price from its
training data, and a parent cannot tell that from a real one until they are
standing in a shop. The precedent for the fix shipped twice already — trips
are LLM-proposes → Mapbox-verifies, intake is LLM-extracts → family approves.
Here it is LLM-emits-QUERIES → Walmart returns real items and real prices →
the budget filters WALMART'S RESPONSE → survivors are staged for a pick.

The properties that matter, and why:

  1. **The budget is applied to the retailer's answer**, never to the model's
     imagination — and an item whose price the API did not return is DROPPED,
     not assumed cheap. "Probably under $25" is the exact guess this refuses.
  2. **The budget is never even sent to the model.** Telling it about one
     only invites it to quote one.
  3. **No credentials → no products.** The honest degradation is the queries
     as things to look for, explicitly marked unverified. A plausible
     invented gift is worse than none: the parent has to evaluate it either
     way and now has to discover it is fake.
  4. **Nothing is auto-added**, and a pick carries the whole candidate — the
     itemId, title and price the parent SAW — so a fresh search a fortnight
     later cannot swap the product underneath them.
  5. **Picks land on the PRIVATE list and become cart-ready**: the
     name→itemId mapping is what makes `cart_for_list` carry the exact
     product chosen, with no new cart code at all.

Run from chauffeur/:  python tests/test_gift_shortlist.py
"""
import datetime
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage
from services import occasions as _occ

TODAY = datetime.date.today()
SAT = TODAY + datetime.timedelta(days=5)

QUERIES = {'queries': [
    {'query': 'kids art set 7 year old', 'why': 'safe bet at this age'},
    {'query': 'dinosaur building blocks', 'why': 'they like dinosaurs'},
]}


def _reset():
    with storage.db_lock:
        storage.occasions_table.truncate()
        storage.members_table.truncate()
        storage.shopping_lists_table.truncate()
        storage.shopping_items_table.truncate()
        storage.walmart_items_table.truncate()


def _household():
    from models.schemas import FamilyMember
    for mid, name, role in (('mum', 'Mum', 'parent'), ('dad', 'Dad', 'parent'),
                            ('ellie', 'Ellie', 'child')):
        storage.add_member(FamilyMember(id=mid, name=name, role=role).model_dump())


def _party(budget=25, age=7):
    o = _occ.create("Jack's party", SAT.isoformat(), 'invited')
    storage.update_occasion(o['id'], {'answers': {
        'whose_party': 'Jack', 'their_age': age, 'gift_budget': budget}})
    return storage.get_occasion(o['id'])


def _found(*rows):
    """Walmart search results, in the shape services/walmart.search returns."""
    return list(rows)


def _item(item_id, title, price, available=True):
    return {'item_id': item_id, 'title': title, 'price': price,
            'thumbnail': None, 'url': None, 'brand': None, 'size': None,
            'available': available}


def scenario_the_model_writes_queries_and_never_products():
    """Property 2, and the rule the whole slice is built around."""
    src = _occ._GIFT_QUERY_SYSTEM
    for needle, what in (('SEARCH BOX', 'that a query is a search term'),
                         ('NEVER a specific product', 'the no-product rule'),
                         ('NEVER a price', 'the no-price rule')):
        check(needle in src, f"the prompt states {what}")

    _reset(); _household()
    o = _party(budget=25)
    sent = {}

    def fake_llm(pool, key, system, prompt, **kw):
        sent['prompt'] = prompt
        return QUERIES

    with mock.patch('services.model_pools.call_pool_json', side_effect=fake_llm), \
         mock.patch('services.storage.get_settings',
                    return_value={'llm_gemini_api_key': 'k'}), \
         mock.patch('services.walmart.search_backend', return_value=None):
        _occ.gift_ideas(o['id'])
    check('Jack' in sent['prompt'] and 'turning 7' in sent['prompt'],
          f"the model gets who and how old: {sent['prompt']!r}")
    check('25' not in sent['prompt'] and 'budget' not in sent['prompt'].lower(),
          f"and is NEVER told the budget — that invites a quoted price: {sent['prompt']!r}")


def scenario_the_budget_filters_walmarts_answer():
    """Property 1. The cap bites on real prices, and a missing price is a
    drop rather than an optimistic guess."""
    _reset(); _household()
    o = _party(budget=25)
    results = {
        'kids art set 7 year old': _found(_item('1', 'Art Case', 19.97),
                                          _item('2', 'Deluxe Easel', 89.00)),
        'dinosaur building blocks': _found(_item('3', 'Dino Bricks', None),
                                           _item('4', 'Sold Out Dino', 12.00,
                                                 available=False),
                                           _item('5', 'Dino Set', 24.50)),
    }
    with mock.patch('services.model_pools.call_pool_json', return_value=QUERIES), \
         mock.patch('services.storage.get_settings',
                    return_value={'llm_gemini_api_key': 'k'}), \
         mock.patch('services.walmart.search_backend', return_value='affiliate'), \
         mock.patch('services.walmart.search',
                    side_effect=lambda q, limit=4, max_price=None: results.get(q, [])):
        res = _occ.gift_ideas(o['id'])

    titles = [c['title'] for c in res['candidates']]
    check(titles == ['Art Case', 'Dino Set'],
          f"over-budget, price-less and out-of-stock all dropped: {titles}")
    check(res['over_budget'] == 1, f"and the over-budget one is counted: {res}")
    # RELEVANCE order, not cheapest-first. An earlier cut sorted by price;
    # real results settled it — the cheapest thing matching "art set for a
    # 7-year-old" is a packet of pipe cleaners, and recommending that as a
    # present is worse than recommending nothing. The budget is already a
    # hard filter; within it, fit is the only axis left worth ordering on.
    check([c['query'] for c in res['candidates']]
          == ['kids art set 7 year old', 'dinosaur building blocks'],
          f"the model's own ordering survives: {[c['query'] for c in res['candidates']]}")
    check(res['searched'] is True and res['budget'] == 25.0, f"reported: {res['budget']}")

    # No budget answered -> no cap, and a price-less item is now allowed.
    _reset(); _household()
    o2 = _party(budget=None)
    with mock.patch('services.model_pools.call_pool_json', return_value=QUERIES), \
         mock.patch('services.storage.get_settings',
                    return_value={'llm_gemini_api_key': 'k'}), \
         mock.patch('services.walmart.search_backend', return_value='affiliate'), \
         mock.patch('services.walmart.search',
                    side_effect=lambda q, limit=4, max_price=None: results.get(q, [])):
        res2 = _occ.gift_ideas(o2['id'])
    check('Deluxe Easel' in [c['title'] for c in res2['candidates']],
          f"no cap set -> nothing is filtered on price: {[c['title'] for c in res2['candidates']]}")


def scenario_no_search_means_no_products():
    """Property 3. The honest answer, not a plausible invented one."""
    _reset(); _household()
    o = _party()
    with mock.patch('services.model_pools.call_pool_json', return_value=QUERIES), \
         mock.patch('services.storage.get_settings',
                    return_value={'llm_gemini_api_key': 'k'}), \
         mock.patch('services.walmart.search_backend', return_value=None):
        res = _occ.gift_ideas(o['id'])
    check(res['candidates'] == [] and res['searched'] is False,
          f"no products at all: {res['candidates']}")
    check([q['query'] for q in res['queries']] == [q['query'] for q in QUERIES['queries']],
          "the queries survive as things to LOOK FOR")
    check('rather than real products' in (res.get('note') or ''),
          f"and it says so plainly: {res.get('note')!r}")


def scenario_one_dead_search_never_kills_the_shortlist():
    """A shop erroring on one query is not a reason to have no ideas."""
    _reset(); _household()
    o = _party(budget=25)

    def flaky(q, limit=4, max_price=None):
        if q == 'kids art set 7 year old':
            raise RuntimeError('walmart 500')
        return _found(_item('5', 'Dino Set', 24.50))

    with mock.patch('services.model_pools.call_pool_json', return_value=QUERIES), \
         mock.patch('services.storage.get_settings',
                    return_value={'llm_gemini_api_key': 'k'}), \
         mock.patch('services.walmart.search_backend', return_value='affiliate'), \
         mock.patch('services.walmart.search', side_effect=flaky):
        res = _occ.gift_ideas(o['id'])
    check([c['title'] for c in res['candidates']] == ['Dino Set'],
          f"the surviving query still answers: {res['candidates']}")


def scenario_picks_land_private_and_cart_ready():
    """Properties 4 and 5. The mapping is what makes the shipped cart rails
    carry the exact product the parent chose."""
    from services import walmart
    _reset(); _household()
    o = _party(budget=25)
    picks = [{'item_id': '1', 'title': 'Art Case', 'price': 19.97,
              'why': 'safe bet at this age', 'thumbnail': None}]

    res = _occ.add_gifts(o['id'], picks, added_by='mum')
    lst = res['list']
    check(lst['audience'] == 'private' and sorted(lst['shared_with']) == ['dad', 'mum'],
          f"a gift list the child can read is not a gift list: {lst}")
    check(lst['occasion_key'] == 'gift' and lst['occasion_id'] == o['id'],
          "and it belongs to the party")

    item = res['items'][0]
    check(item['name'] == 'Art Case' and item['needed_by'] ==
          (SAT - datetime.timedelta(days=3)).isoformat(),
          f"needed BEFORE the party, not on the day (A2 reads this): {item['needed_by']}")

    mapped = walmart.get_mapping('Art Case')
    check(mapped and mapped['item_id'] == '1',
          f"name -> itemId recorded, so cart_for_list carts THIS one: {mapped}")

    cart = walmart.cart_for_list(lst['id'])
    check(cart['matched_count'] == 1 and cart['unmatched_count'] == 0,
          f"the existing cart rails carry it with no new code: {cart}")
    check('1' in (cart['url'] or ''), f"and the URL names the item: {cart['url']}")

    # A second pick joins the same list rather than starting a new one.
    _occ.add_gifts(o['id'], [{'item_id': '5', 'title': 'Dino Set', 'price': 24.50}])
    lists = [l for l in storage.get_shopping_lists() if l.get('occasion_id') == o['id']]
    check(len(lists) == 1 and len(storage.get_shopping_items(lists[0]['id'])) == 2,
          f"one gift list per party: {len(lists)} list(s)")

    check(_occ.add_gifts(o['id'], []).get('error') == 'nothing picked',
          "and picking nothing is an error, never an empty list quietly created")


def scenario_the_tool_is_in_both_stacks_and_never_invents():
    """Both agent stacks, and the chat answer stays a SUGGESTION — a present
    is not a thing to have chosen for you by a chat message."""
    from services import agent_tools, agent_tools_v2
    v2 = {t['name'] for t in agent_tools_v2.get_available_tools()}
    check('suggest_gift_ideas' in v2, "v2 has it")
    check('suggest_gift_ideas' in agent_tools.TOOL_SCHEMAS
          and 'suggest_gift_ideas' in agent_tools.TOOL_HANDLERS, "v1 has it")

    _reset(); _household()
    o = _party(budget=25)
    with mock.patch('services.model_pools.call_pool_json', return_value=QUERIES), \
         mock.patch('services.storage.get_settings',
                    return_value={'llm_gemini_api_key': 'k'}), \
         mock.patch('services.walmart.search_backend', return_value='affiliate'), \
         mock.patch('services.walmart.search',
                    side_effect=lambda q, limit=4, max_price=None: _found(_item('1', 'Art Case', 19.97))):
        res = agent_tools.execute_tool('suggest_gift_ideas',
                                       {'occasion_name': "Jack's party"})
    check(res['status'] == 'success' and 'Art Case' in res['message'],
          f"the v1 bridge answers with the REAL product: {res['message']!r}")
    check('pick' in res['message'].lower(),
          f"and hands the choosing back to a person: {res['message']!r}")
    check(storage.get_shopping_items() == [], "suggesting bought nothing")

    # Nothing found is said plainly rather than padded with something worse.
    with mock.patch('services.model_pools.call_pool_json', return_value=QUERIES), \
         mock.patch('services.storage.get_settings',
                    return_value={'llm_gemini_api_key': 'k'}), \
         mock.patch('services.walmart.search_backend', return_value='affiliate'), \
         mock.patch('services.walmart.search', return_value=[]):
        empty = agent_tools_v2.suggest_gift_ideas("Jack's party")
    check('nothing good' in empty['message'] and '$25' in empty['message'],
          f"an honest empty answer: {empty['message']!r}")


def scenario_the_hand_path_stages_and_never_auto_adds():
    """Every agent capability needs a hand path — and this one is the PRIMARY
    path, because picking a present is the parent's job."""
    import os
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates')
    occ = open(os.path.join(tpl, 'occasions.html'), encoding='utf-8').read()
    for needle, what in (('gift-ideas', 'the search call'),
                         ('gift-picks', 'the save call'),
                         ('toggleGift', 'per-candidate picking'),
                         ("o.kind === 'invited'", 'the section only on an invitation'),
                         ('private list', 'the promise that it stays hidden'),
                         ('searchUrl', 'a real shop search when nothing is configured'),
                         ('addGiftLink', 'the paste-a-product-link path')):
        check(needle in occ, f"the occasions page carries {what}")
    check(occ.index('toggleGift(o, c)') > 0 and 'saveGifts' in occ,
          "candidates are staged and saved by a separate tap, never on arrival")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} gift-shortlist scenarios passed")

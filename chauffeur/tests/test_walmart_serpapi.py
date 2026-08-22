"""A5b — the search backend a family can actually have.

A5 shipped resolving gift ideas through the Walmart I/O product API, which
needs a developer account AND an approved access request. That is not
something a household can go and get, so the shortlist was gated behind a
credential nobody had — the honest read is that the feature was aspirational.
`search()` now has two backends behind one shape:

  'affiliate' — Walmart I/O. Free and unmetered, and gated.
  'serpapi'   — the key the trip planner already uses. Self-serve, and
                METERED against an allowance shared with flight and hotel
                lookups, which is why everything here is written to spend as
                little of it as possible.
  None        — neither. The pasted product URL still needs nothing at all.

The properties that matter, and why:

  1. **One shape, two backends.** Every caller above `search()` is blind to
     which answered — so the grocery matcher got the same unlock for free.
  2. **Sponsored rows are dropped.** A family asking what to get Jack is not
     asking to be sold to, and an ad inside a shortlist is indistinguishable
     from a recommendation.
  3. **The budget is pushed DOWN into the query.** One search returns a fixed
     number of rows; spending them all on affordable things beats discarding
     two thirds of them.
  4. **Results stay in RELEVANCE order.** Sorting by price turns "a present
     for a seven-year-old" into the cheapest packet of pipe cleaners that
     matched the words.
  5. **Every unit is counted and repeats are cached**, because the allowance
     is shared and "why did my flight lookup stop working" must never have a
     gift shortlist as its unexplained answer.

Run from chauffeur/:  python tests/test_walmart_serpapi.py
"""
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage
from services import walmart

# One real organic_results row, trimmed to the fields the mapping reads.
def _row(item_id, title, price, sponsored=False, oos=False):
    return {'us_item_id': item_id, 'title': title, 'sponsored': sponsored,
            'out_of_stock': oos, 'thumbnail': f'https://img/{item_id}.jpg',
            'seller_name': 'Walmart.com',
            'product_page_url': f'https://www.walmart.com/ip/x/{item_id}',
            'primary_offer': {'offer_price': price, 'currency': 'USD'},
            'price_per_unit': {'unit': 'each'}}


def _payload(*rows):
    return {'search_metadata': {}, 'organic_results': list(rows)}


class _Resp:
    def __init__(self, data): self._d = data
    def raise_for_status(self): pass
    def json(self): return self._d


def _reset():
    storage.set_app_state('walmart_serp_cache', {})
    storage.set_app_state('serpapi_usage', {})


def scenario_the_backend_is_chosen_honestly():
    """Property 1. Affiliate wins when it exists because it is free and
    unmetered; SerpApi is the one a family can actually obtain."""
    with mock.patch('services.walmart.is_configured', return_value=True), \
         mock.patch('services.travel_api.get_serpapi_key', return_value='k'):
        check(walmart.search_backend() == 'affiliate',
              "the free unmetered one wins when it is available")
    with mock.patch('services.walmart.is_configured', return_value=False), \
         mock.patch('services.travel_api.get_serpapi_key', return_value='k'):
        check(walmart.search_backend() == 'serpapi', "otherwise the metered one")
        check(walmart.search_available() is True, "and search IS available")
    with mock.patch('services.walmart.is_configured', return_value=False), \
         mock.patch('services.travel_api.get_serpapi_key', return_value=None):
        check(walmart.search_backend() is None, "neither means neither")
        check(walmart.search_available() is False,
              "which the UI reads to offer the paste path instead")


def scenario_the_response_maps_onto_one_shape():
    """Property 1 again, at the row. `us_item_id` IS the itemId Add-To-Cart
    needs, which is what makes this backend worth having at all."""
    _reset()
    payload = _payload(_row('5067618339', 'Mermaid Art Kit', 24.98),
                       _row('999', 'Sponsored Junk', 5.00, sponsored=True),
                       _row('14940220', 'Colored Pencils', 0.97),
                       _row('888', 'Gone', 12.00, oos=True))
    with mock.patch('services.walmart.is_configured', return_value=False), \
         mock.patch('services.travel_api.get_serpapi_key', return_value='k'), \
         mock.patch('requests.get', return_value=_Resp(payload)):
        rows = walmart.search('kids art set', limit=8)

    check([r['item_id'] for r in rows] == ['5067618339', '14940220', '888'],
          f"sponsored dropped (property 2), the rest kept: {[r['item_id'] for r in rows]}")
    first = rows[0]
    check(first['price'] == 24.98 and first['title'] == 'Mermaid Art Kit',
          f"price comes out of primary_offer: {first}")
    check(first['url'].endswith('/5067618339') and first['thumbnail'],
          "url and thumbnail carried, so a person can check it before picking")
    check(rows[2]['available'] is False,
          "out_of_stock inverts into the same `available` the other backend sets")
    check([r['item_id'] for r in rows] == ['5067618339', '14940220', '888'],
          "and the order is the shop's relevance, not re-sorted by price (property 4)")


def scenario_the_budget_goes_into_the_query():
    """Property 3. The cap earns better rows for the same single unit."""
    _reset()
    sent = {}

    def fake_get(url, params=None, timeout=None):
        sent.update(params or {})
        return _Resp(_payload(_row('1', 'Art Case', 19.97)))

    with mock.patch('services.walmart.is_configured', return_value=False), \
         mock.patch('services.travel_api.get_serpapi_key', return_value='k'), \
         mock.patch('requests.get', side_effect=fake_get):
        walmart.search('kids art set', limit=4, max_price=25)
    check(sent.get('engine') == 'walmart' and sent.get('query') == 'kids art set',
          f"the Walmart engine, not a web search: {sent}")
    check(sent.get('max_price') == 25, f"and the cap rides along: {sent}")
    check('sort' not in sent,
          "no price sort — that is what surfaces 82-cent pipe cleaners")


def scenario_units_are_counted_and_repeats_are_free():
    """Property 5. The allowance is shared with the trip planner."""
    _reset()
    calls = []

    def counting_get(url, params=None, timeout=None):
        calls.append(params['query'])
        return _Resp(_payload(_row('1', 'Art Case', 19.97)))

    with mock.patch('services.walmart.is_configured', return_value=False), \
         mock.patch('services.travel_api.get_serpapi_key', return_value='k'), \
         mock.patch('requests.get', side_effect=counting_get):
        walmart.search('kids art set', 4, 25)
        walmart.search('KIDS  ART SET', 4, 25)      # same question, spelt loosely
        walmart.search('dinosaur blocks', 4, 25)
    check(calls == ['kids art set', 'dinosaur blocks'],
          f"the repeat was served from cache: {calls}")
    check(walmart.serp_usage()['count'] == 2,
          f"and only real calls are counted: {walmart.serp_usage()}")

    # A different budget is a different question and must not reuse the rows.
    with mock.patch('services.walmart.is_configured', return_value=False), \
         mock.patch('services.travel_api.get_serpapi_key', return_value='k'), \
         mock.patch('requests.get', side_effect=counting_get):
        walmart.search('kids art set', 4, 50)
    check(len(calls) == 3, f"a raised cap re-asks: {calls}")


def scenario_an_exhausted_allowance_says_so():
    """The one failure a family must be able to understand without reading a
    log: it is not broken, it is used up."""
    _reset()
    with mock.patch('services.walmart.is_configured', return_value=False), \
         mock.patch('services.travel_api.get_serpapi_key', return_value='k'), \
         mock.patch('requests.get',
                    return_value=_Resp({'error': 'You have exhausted your monthly allowance'})):
        try:
            walmart.search('kids art set', 4)
            check(False, "an exhausted allowance must not look like an empty shelf")
        except RuntimeError as e:
            check('allowance is used up' in str(e), f"named plainly: {e}")


def scenario_the_shortlist_spends_fewer_units_on_the_metered_backend():
    """Five ideas is still a shortlist; eight is a catalogue nobody reads and
    costs 60% more of a shared allowance."""
    from services import occasions as _occ
    check(_occ._MAX_QUERIES['serpapi'] < _occ._MAX_QUERIES['affiliate'],
          f"the metered backend asks fewer questions: {_occ._MAX_QUERIES}")

    _reset()
    many = {'queries': [{'query': f'idea {i}', 'why': ''} for i in range(8)]}
    searched = []
    o = _occ.create("Jack's party", '2026-12-01', 'invited')
    storage.update_occasion(o['id'], {'answers': {'their_age': 7, 'gift_budget': 25}})
    with mock.patch('services.model_pools.call_pool_json', return_value=many), \
         mock.patch('services.storage.get_settings',
                    return_value={'llm_gemini_api_key': 'k'}), \
         mock.patch('services.walmart.search_backend', return_value='serpapi'), \
         mock.patch('services.walmart.serp_usage', return_value={'month': 'x', 'count': 5}), \
         mock.patch('services.walmart.search',
                    side_effect=lambda q, limit=4, max_price=None: searched.append(q) or []):
        res = _occ.gift_ideas(o['id'])
    check(len(searched) == 5, f"eight ideas, five searches: {len(searched)}")
    check(len(res['queries']) == 5, "and the page is not shown ideas it never priced")
    check(res.get('usage', {}).get('count') == 5,
          f"with the month's spend reported back: {res.get('usage')}")


def scenario_the_family_chooses_how_much_to_spend():
    """SerpApi's allowance is ONE pool across every engine — flights, hotels
    and gift ideas draw on the same monthly total — so how eagerly to spend it
    is a household decision, not a default somebody discovers afterwards."""
    def _with(method, affiliate, serp_key):
        return (mock.patch('services.storage.get_settings',
                           return_value={'walmart_search_method': method}),
                mock.patch('services.walmart.is_configured', return_value=affiliate),
                mock.patch('services.travel_api.get_serpapi_key', return_value=serp_key))

    a, b, c = _with('links', False, 'k')
    with a, b, c:
        check(walmart.search_backend() is None,
              "'links' never spends a search, even with a key sitting right there")
    a, b, c = _with('links', True, 'k')
    with a, b, c:
        check(walmart.search_backend() is None,
              "and not even when the free backend is available — the family said no")

    a, b, c = _with('serpapi', True, 'k')
    with a, b, c:
        check(walmart.search_backend() == 'serpapi',
              "'serpapi' overrides the automatic preference for affiliate")

    a, b, c = _with('auto', True, 'k')
    with a, b, c:
        check(walmart.search_backend() == 'affiliate', "'auto' prefers the free one")
    a, b, c = _with('auto', False, 'k')
    with a, b, c:
        check(walmart.search_backend() == 'serpapi', "and falls back to the metered one")

    # A preference about SPENDING is not a vow of silence: asking for a
    # backend that is not configured falls back rather than breaking search.
    a, b, c = _with('serpapi', True, None)
    with a, b, c:
        check(walmart.search_backend() == 'affiliate',
              "'serpapi' with no key falls back to what does work")

    import os
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates')
    shop = open(os.path.join(tpl, 'shopping.html'), encoding='utf-8').read()
    check('walmart_search_method' in shop, "and it is settable by hand")
    check('serp_usage' in shop, "with the month's spend shown next to the choice")


def scenario_a_pasted_link_needs_nothing_at_all():
    """The path that always works, and the most honest verification in the
    arc: a person looked at the actual product page."""
    from services import occasions as _occ
    _reset()
    with storage.db_lock:
        storage.occasions_table.truncate()
        storage.shopping_lists_table.truncate()
        storage.shopping_items_table.truncate()
        storage.walmart_items_table.truncate()

    url = ('https://www.walmart.com/ip/LEGO-Creator-3-in-1-Fierce-Dinosaur'
           '/17096963941?classType=REGULAR')
    check(walmart.item_id_from_url(url) == '17096963941',
          "the itemId comes out of the URL, as it always has")
    check(walmart.title_from_url(url) == 'LEGO Creator 3 in 1 Fierce Dinosaur',
          f"and the slug prefills a name: {walmart.title_from_url(url)!r}")
    # The slug-less form the mapping path has always accepted must still work.
    check(walmart.item_id_from_url('https://www.walmart.com/ip/17096963941')
          == '17096963941', "a bare /ip/<id> URL still resolves")

    from models.schemas import FamilyMember
    with storage.db_lock:
        storage.members_table.truncate()
    storage.add_member(FamilyMember(id='mum', name='Mum', role='parent').model_dump())

    o = _occ.create("Jack's party", '2026-12-01', 'invited')
    res = _occ.gift_from_link(o['id'], url)
    check(res['matched'] is True and res['items'][0]['name'].startswith('LEGO Creator'),
          f"pasted straight in: {res['items'][0]['name']!r}")
    check(walmart.get_mapping(res['items'][0]['name'])['item_id'] == '17096963941',
          "mapped, so it carts like anything the search found")
    check(res['list']['audience'] == 'private', "and it is still the closed list")

    # A link with no item id is a plain row, not a refusal: somebody who has
    # decided on a present must not be blocked because the cart cannot help.
    res2 = _occ.gift_from_link(o['id'], 'https://example.com/thing',
                               name='Hand-made card')
    check(res2['matched'] is False and res2['items'][0]['name'] == 'Hand-made card',
          f"kept as an ordinary row: {res2['items'][0]['name']!r}")
    check(_occ.gift_from_link(o['id'], '', '')['error'],
          "but a nameless nothing is refused")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} walmart-serpapi scenarios passed")

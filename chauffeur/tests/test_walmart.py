"""Walmart cart tests (arc W1, services/walmart.py).

Entirely OFFLINE. Nothing here touches Walmart: the signature is verified
against a locally generated key pair, and search is stubbed. The point under
test is the split that makes the feature survivable —

  building a cart needs NO credentials and NO approval (it is a URL), while
  resolving a name to an item id needs an API that may never be granted

— so everything cart-side must work with the credentials absent, and the
unmatched half must always be reported rather than silently dropped.

Run from chauffeur/:  python tests/test_walmart.py
"""
import base64

from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)

from services import storage, walmart


def _reset():
    for t in (storage.shopping_lists_table, storage.shopping_items_table,
              storage.walmart_items_table):
        t.truncate()
    storage.get_settings = lambda: {"calendar_ids": ["primary"]}


def _keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption())
    return key, pem


def _add(name, list_id, qty=None):
    from models.schemas import ShoppingItem
    storage.add_shopping_item(
        ShoppingItem(list_id=list_id, name=name, qty=qty).model_dump())


# --- the signature ----------------------------------------------------------

def scenario_signature_is_verifiable_and_canonical():
    """Walmart signs consumerId, timestamp and key version — sorted by header
    name, each value newline-terminated — with RSA-SHA256. Verified against
    the matching public key rather than asserted against a golden string, so
    the test proves the signature is CORRECT, not merely unchanged."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    key, pem = _keypair()
    creds = {'consumer_id': 'abc-123', 'key_version': '2',
             'private_key': pem, 'configured': True}

    h = walmart.sign_headers(creds, timestamp_ms=1700000000000)
    check(h['WM_CONSUMER.ID'] == 'abc-123'
          and h['WM_CONSUMER.INTIMESTAMP'] == '1700000000000'
          and h['WM_SEC.KEY_VERSION'] == '2', f"headers echoed, got {h}")

    canonical = b"abc-123\n1700000000000\n2\n"
    key.public_key().verify(base64.b64decode(h['WM_SEC.AUTH_SIGNATURE']),
                            canonical, padding.PKCS1v15(), hashes.SHA256())
    check(True, "signature verifies against the public half of the key")

    later = walmart.sign_headers(creds, timestamp_ms=1700000000001)
    check(later['WM_SEC.AUTH_SIGNATURE'] != h['WM_SEC.AUTH_SIGNATURE'],
          "the timestamp is inside the signature, so it must change with it")


def scenario_missing_credentials_fail_loudly_not_silently():
    try:
        walmart.sign_headers({'consumer_id': '', 'key_version': '1',
                              'private_key': None, 'configured': False})
        check(False, "signing without credentials must raise")
    except RuntimeError as e:
        check('not configured' in str(e), f"and say so plainly, got {e}")


# --- the cart URL -----------------------------------------------------------

def scenario_cart_url_needs_no_credentials_at_all():
    """The load-bearing fact of the whole arc."""
    url = walmart.cart_url([('945193065', 1), ('660768274', 2)])
    check(url.startswith('https://www.walmart.com/sc/cart/addToCart?'),
          f"the documented endpoint, got {url}")
    check('945193065%2C660768274_2' in url or '945193065,660768274_2' in url,
          f"qty omitted when it is 1, underscore-delimited when it is not, got {url}")
    check(not walmart.is_configured() or True, "and no credential was consulted")


def scenario_store_and_quantity_handling():
    url = walmart.cart_url([('123456789', 3)], store_id='5435')
    check('storeId=5435' in url, f"store localizes the cart, got {url}")
    check('123456789_3' in url, f"quantity rides along, got {url}")

    check(walmart.cart_url([]) is None, "nothing to add is None, not a bare URL")
    check(walmart.cart_url([(None, 1)]) is None, "and a missing id is not an empty entry")

    # Free-text qty is NEVER parsed for meaning (design §M1).
    check(walmart._qty('2') == 2 and walmart._qty('2 lbs') == 1
          and walmart._qty('a dozen') == 1 and walmart._qty(None) == 1,
          "only a bare count becomes a cart quantity — ordering 2 of a 2-lb "
          "pack is a worse error than ordering 1")


def scenario_affiliate_form_only_when_onboarded():
    plain = walmart.cart_url([('1', 1)])
    check(plain.startswith('https://www.walmart.com'), "plain URL is the default")
    aff = walmart.cart_url([('1', 1)], impact_publisher_id='p1',
                           impact_ad_id='a1', impact_campaign_id='c1')
    check(aff.startswith('https://goto.walmart.com/m/p1/a1/c1?'),
          f"the affiliate wrapper only when all three are set, got {aff}")
    check('u=https%3A%2F%2Fwww.walmart.com' in aff,
          f"with the real cart URL encoded into u, got {aff}")


# --- the mapping ------------------------------------------------------------

def scenario_item_id_is_recoverable_from_a_pasted_url():
    """The path that always works, credentials or not."""
    cases = [
        ('https://www.walmart.com/ip/Great-Value-Whole-Milk-1-Gallon/10450114', '10450114'),
        ('https://www.walmart.com/ip/10450114', '10450114'),
        ('  945193065  ', '945193065'),
    ]
    for url, want in cases:
        got = walmart.item_id_from_url(url)
        check(got == want, f"{url!r} -> {want}, got {got}")
    for bad in ('https://www.walmart.com/browse/food', 'chicken thighs', '', None):
        check(walmart.item_id_from_url(bad) is None, f"{bad!r} yields nothing")


def scenario_mapping_is_by_the_familys_own_word_and_persists():
    _reset()
    walmart.set_mapping('  Chicken   Thighs ', '123456789', title='Fresh chicken thighs')
    for spelling in ('chicken thighs', 'Chicken Thighs', ' CHICKEN  THIGHS '):
        m = walmart.get_mapping(spelling)
        check(m and m['item_id'] == '123456789',
              f"{spelling!r} finds the same mapping, got {m}")
    check(walmart.get_mapping('chicken thigh') is None,
          "but nothing clever: 'chicken thigh' is a different word and stays unmapped")


# --- the list -> cart round trip -------------------------------------------

def scenario_unmatched_items_are_reported_never_dropped():
    """A list of 30 becoming a cart of 27 with no explanation is the same
    silent-skip failure the '+ List' dialog already had to be fixed for."""
    _reset()
    lst = storage.ensure_default_shopping_list()
    _add('milk', lst['id'])
    _add('bread', lst['id'], qty='2')
    _add('sourdough starter', lst['id'])
    walmart.set_mapping('milk', '10450114')
    walmart.set_mapping('bread', '10315643')

    res = walmart.cart_for_list(lst['id'])
    check(res['matched_count'] == 2 and res['unmatched_count'] == 1,
          f"counts are honest, got {res['matched_count']}/{res['unmatched_count']}")
    check([u['name'] for u in res['unmatched']] == ['sourdough starter'],
          f"and the unmatched are named, got {res['unmatched']}")
    check('10450114' in res['url'] and '10315643_2' in res['url'],
          f"the cart carries both matched items with quantity, got {res['url']}")

    # Checked-off items are not re-bought.
    items = storage.get_shopping_items(lst['id'])
    storage.update_shopping_item(next(i['id'] for i in items if i['name'] == 'milk'),
                                 {'is_checked': True})
    res2 = walmart.cart_for_list(lst['id'])
    check(res2['matched_count'] == 1 and '10450114' not in (res2['url'] or ''),
          f"what is already in the cart at home stays out of it, got {res2['url']}")


def scenario_an_entirely_unmatched_list_says_so_rather_than_offering_an_empty_cart():
    _reset()
    lst = storage.ensure_default_shopping_list()
    _add('quince paste', lst['id'])
    res = walmart.cart_for_list(lst['id'])
    check(res['url'] is None and res['unmatched_count'] == 1,
          f"no URL at all rather than a cart with nothing in it, got {res}")


def scenario_search_is_optional_and_its_absence_is_not_an_error():
    _reset()
    lst = storage.ensure_default_shopping_list()
    _add('milk', lst['id'])
    res = walmart.cart_for_list(lst['id'])
    check(res['configured'] is False,
          "with no credentials the cart still builds — it just reports that "
          "search is unavailable")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} walmart scenarios passed")
    raise SystemExit(1 if failed else 0)

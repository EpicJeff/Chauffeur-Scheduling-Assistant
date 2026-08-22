"""Walmart I/O — turn the shopping list into a Walmart cart (arc W1).

Two halves with very different costs, and keeping them separate is the whole
design:

**Add To Cart needs nothing.** It is not an authenticated API at all — it is a
URL (`walmart.com/sc/cart/addToCart?items=ID_QTY,...`), documented as available
"whether they are onboarded to Impact Radius or not". So once an item has an
itemId, one tap builds a real Walmart cart with no credentials, no approval and
no quota. That is the load-bearing fact: the feature still works for a family
who never gets API access.

**Resolving a name to an itemId needs the Affiliate API** (search / product
lookup), which the consumer ID + private key covers. Localized per-store price
and availability is the OPD tier, which is separately gated behind Impact
Radius and an approved partnership — deliberately not depended on here.

So the mapping is stored, once, per ingredient name. A family buys roughly the
same fifty things forever — the same premise the dish repertoire already rests
on — so a name→itemId map is a one-time cost that does not rot. Search fills it
in when credentials exist; a pasted product URL fills it in when they do not.
"""
import base64
import json
import os
import re
import time
import urllib.parse

from services import storage

BASE = "https://developer.api.walmart.com/api-proxy/service/affil/product/v2"
CART_URL = "https://www.walmart.com/sc/cart/addToCart"
_TIMEOUT = 12


# --- credentials ------------------------------------------------------------
# Same resolution order as the Mapbox key: add-on options, environment, then a
# file beside the app. The private key is a SECRET and never leaves the server
# — no endpoint returns it and it is never rendered into a page.

def _option(name):
    try:
        if os.path.exists('/data/options.json'):
            with open('/data/options.json') as f:
                v = json.load(f).get(name)
                if v:
                    return v
    except Exception:
        pass
    return os.environ.get(name.upper()) or None


def _local_file(*names):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for n in names:
        p = os.path.join(here, n)
        if os.path.exists(p):
            try:
                with open(p) as f:
                    v = f.read().strip()
                if v:
                    return v
            except Exception:
                pass
    return None


def get_credentials() -> dict:
    consumer = _option('walmart_consumer_id') or _local_file('walmart_consumer_id.txt')
    version = _option('walmart_key_version') or _local_file('walmart_key_version.txt') or '1'
    key = _option('walmart_private_key') or _local_file('walmart_private_key.pem',
                                                        'WM_IO_private_key.pem')
    return {'consumer_id': (consumer or '').strip(),
            'key_version': str(version).strip(),
            'private_key': key,
            'configured': bool(consumer and key)}


def is_configured() -> bool:
    return get_credentials()['configured']


# --- signing ----------------------------------------------------------------

def sign_headers(creds: dict = None, timestamp_ms: int = None) -> dict:
    """Walmart I/O auth: RSA-SHA256 over the canonicalized header values.

    Canonical form is the three signed headers sorted by NAME with each value
    followed by a newline — WM_CONSUMER.ID, WM_CONSUMER.INTIMESTAMP,
    WM_SEC.KEY_VERSION happens to already be alphabetical.
    """
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    creds = creds or get_credentials()
    if not creds['configured']:
        raise RuntimeError("Walmart credentials are not configured.")
    ts = str(int(timestamp_ms if timestamp_ms is not None else time.time() * 1000))
    canonical = f"{creds['consumer_id']}\n{ts}\n{creds['key_version']}\n"

    pem = creds['private_key']
    if isinstance(pem, str):
        pem = pem.encode()
    key = serialization.load_pem_private_key(pem, password=None)
    sig = key.sign(canonical.encode(), padding.PKCS1v15(), hashes.SHA256())
    return {
        'WM_CONSUMER.ID': creds['consumer_id'],
        'WM_CONSUMER.INTIMESTAMP': ts,
        'WM_SEC.KEY_VERSION': creds['key_version'],
        'WM_SEC.AUTH_SIGNATURE': base64.b64encode(sig).decode(),
        'Accept': 'application/json',
    }


def _get(path: str, params: dict) -> dict:
    import requests
    r = requests.get(f"{BASE}{path}", params=params,
                     headers=sign_headers(), timeout=_TIMEOUT)
    if r.status_code == 401 or r.status_code == 403:
        raise PermissionError(
            f"Walmart rejected the credentials ({r.status_code}). Check the "
            f"consumer ID, the key version, and that the private key matches "
            f"the public key you uploaded.")
    r.raise_for_status()
    return r.json()


# --- the mapping ------------------------------------------------------------

def name_key(name: str) -> str:
    """Normalized so 'Chicken Thighs', 'chicken thighs ' and 'chicken  thighs'
    are one entry. Deliberately gentle — no stemming, no singularization: this
    maps the family's own words, and a clever normalizer that collapses
    'green beans' and 'green bean paste' would be worse than none."""
    return re.sub(r'\s+', ' ', (name or '').strip().lower())


def get_mapping(name: str) -> dict:
    return storage.get_walmart_item(name_key(name))


def set_mapping(name: str, item_id: str, title: str = None, price=None,
                thumbnail: str = None, offer_id: str = None) -> dict:
    rec = {'name_key': name_key(name), 'name': (name or '').strip(),
           'item_id': str(item_id).strip() if item_id else None,
           'offer_id': (offer_id or '').strip() or None,
           'title': title, 'price': price, 'thumbnail': thumbnail,
           'updated_at': time.time()}
    storage.save_walmart_item(rec)
    return rec


ITEM_ID_IN_URL = re.compile(r'/ip/(?:[^/]+/)?(\d{6,})')
# Separate from the id pattern on purpose: the id has to keep matching the
# slug-less `/ip/<id>` form it always did, and widening one regex to serve
# both would have quietly changed which group carries the number.
SLUG_IN_URL = re.compile(r'/ip/([^/?#]+)/\d{6,}')


def title_from_url(url: str) -> str:
    """A rough product name out of the URL slug, to PREFILL a field.

    `/ip/LEGO-Creator-3-in-1-Fierce-Dinosaur/17096963941` is not a product
    title, but it is close enough that a parent edits two words instead of
    typing twelve — and it is the only name available when there is no search
    API to ask. Always editable; never presented as authoritative.
    """
    m = SLUG_IN_URL.search(url or '')
    if not m:
        return ''
    slug = urllib.parse.unquote(m.group(1)).replace('-', ' ').replace('_', ' ')
    slug = re.sub(r'\s+', ' ', slug).strip()
    return slug[:80]


def item_id_from_url(url: str) -> str:
    """Walmart product URLs carry the itemId: /ip/<slug>/<itemId>. Pasting the
    URL is the escape hatch when search is unavailable or wrong — and for a
    family it is often faster than picking from a list of eight similar items.
    """
    m = ITEM_ID_IN_URL.search(url or '')
    if m:
        return m.group(1)
    bare = (url or '').strip()
    return bare if bare.isdigit() and len(bare) >= 6 else None


# --- search -----------------------------------------------------------------

SERPAPI_URL = "https://serpapi.com/search.json"
_SERP_CACHE_DAYS = 14


def search_backend() -> str:
    """Which engine can answer a name→product question right now.

    'affiliate' — Walmart I/O, free and unmetered, but it needs a developer
        account AND an approved product-API access request, which is not
        something a family can simply go and get.
    'serpapi'  — the key the trip planner already uses. Self-serve, and
        METERED: the family's monthly allowance is shared with flight and
        hotel lookups, so everything here is written to spend as little of
        it as possible.
    None       — neither, or the family said not to. The pasted product URL
        is the path that always works and it needs nothing at all.

    `walmart_search_method` is the family's call because the SerpApi
    allowance is ONE pool across every engine — the trip planner's flight and
    hotel lookups draw on the same 250 a month — so a gift shortlist quietly
    spending five of them is a decision somebody should get to make.
    """
    method = str((storage.get_settings() or {}).get(
        'walmart_search_method') or 'auto').strip().lower()
    if method == 'links':
        return None
    if method != 'serpapi' and is_configured():
        return 'affiliate'
    try:
        from services.travel_api import get_serpapi_key
        if get_serpapi_key():
            return 'serpapi'
    except Exception:
        pass
    # 'serpapi' asked for, no key: fall back to affiliate rather than to
    # nothing. The setting is a preference about spending, not a vow.
    return 'affiliate' if is_configured() else None


def search_available() -> bool:
    return search_backend() is not None


def _serp_cache_get(key: str):
    rows = storage.get_app_state('walmart_serp_cache') or {}
    hit = rows.get(key)
    if not hit:
        return None
    if time.time() - float(hit.get('ts') or 0) > _SERP_CACHE_DAYS * 86400:
        return None
    return hit.get('items')


def _serp_cache_put(key: str, items: list) -> None:
    rows = dict(storage.get_app_state('walmart_serp_cache') or {})
    cutoff = time.time() - _SERP_CACHE_DAYS * 86400
    rows = {k: v for k, v in rows.items() if float(v.get('ts') or 0) >= cutoff}
    rows[key] = {'ts': time.time(), 'items': items}
    storage.set_app_state('walmart_serp_cache', rows)


def serp_usage(now_month: str = None) -> dict:
    """What this app has spent of the shared allowance this month.

    Counted rather than guessed, because the quota is shared with the trip
    planner and "why did my flight lookup stop working" is a question a gift
    shortlist should never be the unexplained answer to.
    """
    month = now_month or time.strftime('%Y-%m')
    rows = storage.get_app_state('serpapi_usage') or {}
    return {'month': month, 'count': int(rows.get(month) or 0)}


def _serp_count(month: str = None) -> None:
    month = month or time.strftime('%Y-%m')
    rows = dict(storage.get_app_state('serpapi_usage') or {})
    rows[month] = int(rows.get(month) or 0) + 1
    # Keep a year; the older months are what make a spike legible.
    for k in sorted(rows)[:-12]:
        rows.pop(k, None)
    storage.set_app_state('serpapi_usage', rows)


def _serp_search(query: str, limit: int = 8, max_price=None) -> list:
    """The metered backend, called over plain HTTP.

    Deliberately NOT through the `serpapi` package: it is a soft dependency
    the trip planner already guards against being absent, and this is one
    GET with three parameters.

    `max_price` is pushed DOWN into the query rather than filtered after: one
    search returns a fixed number of rows, so spending them all on things the
    family can afford is strictly better than discarding two thirds. Results
    stay in RELEVANCE order — sorting by price turns "a present for a
    seven-year-old" into the cheapest packet of pipe cleaners that matched.
    """
    import requests
    from services.travel_api import get_serpapi_key
    key = get_serpapi_key()
    if not key:
        return []
    ck = f"{name_key(query)}|{max_price if max_price is not None else ''}"
    cached = _serp_cache_get(ck)
    if cached is not None:
        return cached[:limit]

    params = {'engine': 'walmart', 'query': query, 'api_key': key}
    if max_price:
        params['max_price'] = max_price
    r = requests.get(SERPAPI_URL, params=params, timeout=_TIMEOUT + 18)
    r.raise_for_status()
    data = r.json()
    _serp_count()
    err = (data.get('error') or '')
    if err:
        if 'exhausted' in err.lower():
            raise RuntimeError("The SerpApi monthly allowance is used up.")
        raise RuntimeError(err)

    out = []
    for it in (data.get('organic_results') or []):
        # Sponsored rows are advertising. A family asking "what should we get
        # Jack" is not asking to be sold to, and an ad in a shortlist is
        # indistinguishable from a recommendation.
        if it.get('sponsored'):
            continue
        iid = it.get('us_item_id')
        if not iid:
            continue
        offer = it.get('primary_offer') or {}
        out.append({
            'item_id': str(iid),
            'title': it.get('title'),
            'price': offer.get('offer_price'),
            'thumbnail': it.get('thumbnail'),
            'size': (it.get('price_per_unit') or {}).get('unit'),
            'brand': it.get('seller_name'),
            'url': it.get('product_page_url'),
            'available': not it.get('out_of_stock'),
        })
    _serp_cache_put(ck, out)
    return out[:limit]


def search(query: str, limit: int = 8, max_price=None) -> list:
    """Candidates for one list item. Never auto-maps: the family picks, the
    same way photo candidates are staged rather than added.

    Two backends behind one shape, so every caller above this line is blind to
    which one answered. `max_price` is honoured by the metered backend (where
    it buys better rows for the same unit) and ignored by the free one, which
    returns few enough rows that filtering after costs nothing.
    """
    backend = search_backend()
    if backend == 'serpapi':
        return _serp_search(query, limit, max_price)
    if backend != 'affiliate':
        return []
    data = _get('/search', {'query': query, 'numItems': max(1, min(25, limit))})
    out = []
    for it in (data.get('items') or [])[:limit]:
        out.append({
            'item_id': str(it.get('itemId')) if it.get('itemId') is not None else None,
            'title': it.get('name'),
            'price': it.get('salePrice'),
            'thumbnail': it.get('thumbnailImage'),
            'size': it.get('size'),
            'brand': it.get('brandName'),
            'url': it.get('productUrl'),
            'available': it.get('stock') != 'Not available',
        })
    return [o for o in out if o['item_id']]


def lookup(item_ids: list) -> list:
    ids = [str(i) for i in item_ids if i]
    if not ids:
        return []
    data = _get('/items', {'ids': ','.join(ids[:20])})
    return data.get('items') or []


# --- the cart ---------------------------------------------------------------

def cart_url(pairs: list, store_id: str = None, access_point: str = None,
             impact_publisher_id: str = None, impact_ad_id: str = None,
             impact_campaign_id: str = None, source_id: str = None) -> str:
    """Build the Add To Cart URL. `pairs` is [(item_id, qty), ...].

    Quantity is only appended when it is not 1 — the documented shorthand, and
    it keeps the common case readable. Underscore is used as the delimiter
    rather than the legacy pipe because a pipe has to be percent-encoded and
    the docs give underscore as the current form.
    """
    parts = []
    for item_id, qty in pairs:
        if not item_id:
            continue
        try:
            n = max(1, int(qty or 1))
        except (TypeError, ValueError):
            n = 1
        parts.append(str(item_id) if n == 1 else f"{item_id}_{n}")
    if not parts:
        return None
    params = {'items': ','.join(parts)}
    if store_id:
        params['storeId'] = str(store_id)
    if access_point:
        params['ap'] = str(access_point)
    # safe=',_' so the separators stay literal, exactly as the ATC docs show
    # them. Percent-encoded commas would very probably work, but "very probably"
    # is not a thing to find out in a pickup bay.
    direct = f"{CART_URL}?{urllib.parse.urlencode(params, safe=',_')}"
    if impact_publisher_id and impact_ad_id and impact_campaign_id:
        # Affiliate-attributed form, per the ATC docs. Only used when the
        # family has actually onboarded to Impact Radius; the plain URL works
        # regardless and is the default.
        q = {'veh': 'aff', 'u': direct}
        if source_id:
            q['sourceid'] = source_id
        return (f"https://goto.walmart.com/m/{impact_publisher_id}/"
                f"{impact_ad_id}/{impact_campaign_id}?{urllib.parse.urlencode(q)}")
    return direct


def cart_for_list(list_id: str, store_id: str = None) -> dict:
    """Everything OPEN on the list, split into what can go in a cart and what
    still needs a Walmart item behind it.

    The unmatched half is returned in full rather than quietly dropped: a list
    of 30 becoming a cart of 27 with no explanation is exactly the silent-skip
    failure the "+ List" dialog already had to be fixed for once.
    """
    items = storage.get_shopping_items(list_id, include_checked=False)
    settings = storage.get_settings() or {}
    matched, unmatched = [], []
    for it in items:
        m = get_mapping(it['name'])
        if m and m.get('item_id'):
            matched.append({'item': it, 'mapping': m})
        else:
            unmatched.append(it)
    pairs = [(m['mapping']['item_id'], _qty(m['item'].get('qty'))) for m in matched]
    return {
        'url': cart_url(pairs, store_id or settings.get('walmart_store_id') or None,
                        impact_publisher_id=settings.get('walmart_impact_publisher_id'),
                        impact_ad_id=settings.get('walmart_impact_ad_id'),
                        impact_campaign_id=settings.get('walmart_impact_campaign_id')),
        'matched': [{'name': m['item']['name'], 'item_id': m['mapping']['item_id'],
                     'title': m['mapping'].get('title'),
                     'qty': _qty(m['item'].get('qty'))} for m in matched],
        'unmatched': [{'id': i['id'], 'name': i['name'], 'qty': i.get('qty')}
                      for i in unmatched],
        'matched_count': len(matched), 'unmatched_count': len(unmatched),
        'configured': is_configured(),
    }


_QTY_NUM = re.compile(r'^\s*(\d+)\s*(?:x)?\s*$', re.I)


def _qty(raw) -> int:
    """Quantity is FREE TEXT by design ("2 lbs", "a dozen") and is never
    parsed for meaning. Only a bare count becomes a cart quantity; anything
    else is 1, because ordering 2 of a 2-lb pack is a worse error than
    ordering one and letting the shopper adjust."""
    if raw is None:
        return 1
    m = _QTY_NUM.match(str(raw))
    if not m:
        return 1
    return max(1, min(24, int(m.group(1))))

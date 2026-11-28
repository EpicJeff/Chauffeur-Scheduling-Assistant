"""Bounded, non-LLM page lookups and their provenance records."""
import json
import math
import re
import time
import uuid
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
import requests
from tinydb import Query
from services import storage, net_guard, browse

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
CHALLENGE_TITLES = ('just a moment', 'attention required', 'access denied', 'are you a robot',
                    'please verify you are a human', 'checking your browser', 'pardon our interruption')
CHALLENGE_TEXT = ('click the button below to continue shopping', 'enter the characters you see below',
                  "sorry, we just need to make sure you're not a robot", 'to discuss automated access to amazon data',
                  'press & hold to confirm you are a human', 'please enable cookies', 'cookies are disabled')
BLOCKED_NOTE = 'That store blocks automated readers; try another store.'

def http_url(value, base=''):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        url = urljoin(base, value.strip())
        p = urlsplit(url)
        return url if p.scheme in ('http', 'https') and p.hostname and not p.username and not p.password else None
    except ValueError:
        return None

class _Page(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.meta, self.jsonld, self.text, self.titles = {}, [], [], []
        self.tag = ''; self.script = None; self.canonical = None
        self.feed(html)
    def handle_starttag(self, tag, attrs):
        a = dict(attrs); self.tag = tag
        if tag == 'meta':
            self.meta[(a.get('property') or a.get('name') or '').lower()] = a.get('content', '')
        if tag == 'link' and 'canonical' in (a.get('rel') or '').lower().split():
            self.canonical = a.get('href')
        if tag == 'script':
            self.script = [] if (a.get('type') or '').lower() == 'application/ld+json' else False
    def handle_data(self, data):
        if isinstance(self.script, list):
            self.script.append(data)
        elif self.script is None and self.tag != 'style':
            self.text.append(data)
            if self.tag == 'title': self.titles.append(data)
    def handle_endtag(self, tag):
        if tag == 'script':
            if isinstance(self.script, list):
                try: self.jsonld.append(json.loads(''.join(self.script)))
                except (ValueError, TypeError): pass
            self.script = None
        self.tag = ''

def _product(value):
    if isinstance(value, dict):
        types = value.get('@type', [])
        if 'Product' in (types if isinstance(types, list) else [types]): return value
        value = value.values()
    elif not isinstance(value, list): return None
    for child in value:
        found = _product(child)
        if found: return found
    return None

def _has_product_data(html):
    page = _Page(html)
    return bool(_product(page.jsonld)) or any(
        key in page.meta for key in ('product:price:amount', 'product:price:currency', 'og:price:amount', 'og:price:currency'))

def _usable(data):
    return (not data['title'].strip().casefold().startswith(CHALLENGE_TITLES) and
            bool(data['title'] or data['image_url'] or data['price'] is not None))

def _is_wall(data, final_url, *, has_product_data=False):
    return (data['title'].strip().casefold().startswith(CHALLENGE_TITLES) or
            (not has_product_data and data['price'] is None and (
                any(phrase in data['excerpt'].casefold() for phrase in CHALLENGE_TEXT) or
                any(segment in ('captcha', 'validatecaptcha', 'cookiefailure.do')
                    for segment in urlsplit(final_url).path.casefold().split('/')))))


def _generic_title(data, final_url):
    def normalize(value):
        return ''.join(c for c in value.casefold().strip().removeprefix('www.') if c.isalnum())
    title = normalize(data['title'])
    host = (urlsplit(final_url).hostname or '').removeprefix('www.')
    # With no og:site_name, extract's store is the host (Old Navy -> oldnavy.com).
    return bool(title) and title in (normalize(data['store']), normalize(host), normalize(host.split('.')[0]))


def extract(html: str, base_url: str) -> dict:
    p = _Page(html); m = p.meta; product = _product(p.jsonld) or {}
    clean = lambda v, n: ' '.join(str(v or '').split())[:n]
    image = product.get('image') or m.get('og:image')
    if isinstance(image, list): image = image[0] if image else None
    if isinstance(image, dict): image = image.get('url')
    offer = product.get('offers') or {}
    if isinstance(offer, list): offer = offer[0] if offer else {}
    if not isinstance(offer, dict): offer = {}
    price = offer.get('price', offer.get('lowPrice'))
    currency = offer.get('priceCurrency')
    if price is None:
        for prefix in ('product:price:', 'og:price:'):
            if prefix + 'amount' in m:
                price, currency = m[prefix + 'amount'], m.get(prefix + 'currency'); break
    try:
        price = float(price)
        if not math.isfinite(price) or price < 0: price = None
    except (ValueError, TypeError): price = None
    currency = clean(currency, 3).upper() or None
    if not currency or not re.fullmatch('[A-Z]{3}', currency): price = currency = None
    availability = str(offer.get('availability') or '')
    return dict(canonical=http_url(p.canonical or m.get('og:url'), base_url),
                title=clean(m.get('og:title') or ''.join(p.titles) or product.get('name'), 140),
                store=clean(m.get('og:site_name') or (urlsplit(base_url).hostname or '').removeprefix('www.'), 100),
                image_url=http_url(image, base_url), price=price, currency=currency,
                available=True if availability.endswith('InStock') else False if availability.endswith('OutOfStock') else None,
                excerpt=clean(' '.join(p.text), 300))

def fetch(url, cap, *, images=False):
    """Guard before every request, stream at most cap bytes, close every response."""
    deadline = time.monotonic() + (15 if images else 20)
    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise ValueError('The image took too long to read.' if images else 'The page took too long to read.')
        return seconds
    for hop in range(6):
        remaining()
        net_guard.check_public(url)
        r = requests.get(url, headers={'User-Agent': USER_AGENT}, allow_redirects=False, timeout=min(12, remaining()), stream=True)
        try:
            remaining()
            if r.status_code in (301, 302, 303, 307, 308):
                if hop == 5: raise ValueError('The page redirected too many times.')
                url = urljoin(url, r.headers.get('Location', ''))
                continue
            if r.status_code != 200: return url, r.status_code, b''
            if images and not r.headers.get('Content-Type', '').lower().startswith('image/'):
                raise ValueError('That page did not return an image.')
            body = bytearray()
            for chunk in r.iter_content(chunk_size=65536):
                remaining()
                body.extend(chunk)
                if len(body) > cap: raise ValueError('That page is too large.')
            remaining()
            return url, r.status_code, bytes(body)
        finally:
            r.close()

def get(lookup_id):
    with storage.db_lock:
        return storage.lookups_table.get(Query().id == lookup_id)

def for_mission(mission_id):
    with storage.db_lock:
        return list(storage.lookups_table.search(Query().mission_id == mission_id))

def delete_for_mission(mission_id, keep_ids):
    with storage.db_lock:
        return len(storage.lookups_table.remove((Query().mission_id == mission_id) & ~Query().id.one_of(list(keep_ids))))

def look_up_page(url: str, mission_id: str) -> dict:
    cap = (storage.get_settings() or {}).get('mission_cap_lookups', 30)
    cap = 30 if cap is None else int(cap)
    if len(for_mission(mission_id)) >= cap:
        return {'status': 'error', 'note': f'This mission has used its {cap} page look-ups.'}
    try:
        final, status, body = fetch(url, 2 * 1024 * 1024)
        html = body.decode('utf-8', errors='replace')
        data = extract(html, final)
        has_product_data = _has_product_data(html)
        raw_wall = _is_wall(data, final, has_product_data=has_product_data)
        generic = not has_product_data and _generic_title(data, final)
        if raw_wall or status in (401, 403, 429) or (status == 200 and not has_product_data):
            rendered_wall = False
            try:
                rendered = browse.render_page(final)
                if not rendered: raise ValueError('The page could not be read.')
                rendered_url, rendered_html = rendered
                net_guard.check_public(rendered_url)
                if len(rendered_html.encode('utf-8')) > 2 * 1024 * 1024: raise ValueError('That page is too large.')
                candidate = extract(rendered_html, rendered_url)
                product_data = _has_product_data(rendered_html)
                rendered_wall = _is_wall(candidate, rendered_url, has_product_data=product_data)
                if rendered_wall or not _usable(candidate) or (not raw_wall and status != 200 and not (
                        product_data or (candidate['title'] and (candidate['image_url'] or candidate['price'] is not None)))):
                    raise ValueError('The page could not be read.')
                better = raw_wall or (generic and candidate['title'] != data['title']) or (product_data and not has_product_data) or (
                    (not data['title'] or candidate['title'] == data['title']) and (
                        (data['price'] is None and candidate['price'] is not None) or
                        (not data['image_url'] and bool(candidate['image_url']))))
                if status != 200 or better:
                    final, data, has_product_data = rendered_url, candidate, product_data
            except Exception:
                if raw_wall or (generic and rendered_wall): raise ValueError(BLOCKED_NOTE)
                if status != 200: raise
                if generic and data['price'] is None and not data['image_url']:
                    raise ValueError('That page shows no product.')
        elif status != 200:
            raise ValueError('The page could not be read.')
        if _is_wall(data, final, has_product_data=has_product_data):
            raise ValueError(BLOCKED_NOTE)
        if not _usable(data):
            raise ValueError('The page could not be read.')
        record = {k: data[k] for k in ('title', 'store', 'image_url', 'price', 'currency', 'available')}
        record.update(id='lk_' + uuid.uuid4().hex[:10], mission_id=mission_id, url=url,
                      final_url=final, fetched_at=time.time())
        with storage.db_lock: storage.lookups_table.insert(record)
        compact = {k: record[k] for k in ('title', 'store', 'price', 'currency', 'available')}
        compact.update(lookup=record['id'], excerpt=data['excerpt'],
                       missing=[name for name, absent in (('price', record['price'] is None),
                                                         ('image', not record['image_url'])) if absent])
        return {'status': 'ok', 'lookup': compact}
    except Exception as exc:
        return {'status': 'error', 'note': str(exc)[:250] or 'The page could not be read.'}

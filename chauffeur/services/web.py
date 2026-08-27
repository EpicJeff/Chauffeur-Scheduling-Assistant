"""Web research — the only verb in the Mind's repertoire that reaches outside
the house, and therefore the one most able to make things up.

The whole module is built around a single rule: **a claim carries the page it
came from, or it does not survive.** The model is never asked what it knows —
it is handed text this app actually fetched and asked what that text says, and
any "fact" citing a page we did not read is dropped before the caller sees it.

Two backends, because the quotas are shaped very differently:

- **Brave** (`web_search_api_key`) — a dedicated allowance, generous enough
  that research can be an ordinary thing to do. Preferred whenever present.
- **SerpApi** — already configured for flights, gift shortlists and Walmart,
  and capped at 250 requests A MONTH ACROSS ALL OF THEM. Research is the
  newest and least urgent consumer, so it may only borrow from that pool
  above a reserve (`serpapi_reserve`); past that line the remaining calls
  belong to the features that had them first. "Why did my flight lookup stop
  working" must never have a research question as its unexplained answer.

Fetching is direct HTTP and costs nothing but time, so the metered call is
one search per question — cached for a month, because which beginner guitar
course is good does not change weekly.
"""
import html as _html
import json
import logging
import re
import time
from typing import Optional
from urllib.parse import urlparse

from services import storage

logger = logging.getLogger(__name__)

SERPAPI_URL = 'https://serpapi.com/search'
BRAVE_URL = 'https://api.search.brave.com/res/v1/web/search'

CACHE_DAYS = 30          # a curriculum does not change weekly
RESULTS_PER_SEARCH = 6
PAGES_READ = 3           # how many results are actually fetched and read
MAX_PAGE_CHARS = 12000   # per page, handed to the model
FETCH_TIMEOUT = 12
SEARCH_TIMEOUT = 20
DEFAULT_MONTHLY_CAP = 40         # research questions per month
DEFAULT_SERP_RESERVE = 100       # SerpApi calls research may never touch
SERPAPI_MONTHLY_LIMIT = 250      # the plan's hard ceiling, shared by everyone

_SKIP_EXT = ('.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
             '.zip', '.mp4', '.mp3', '.jpg', '.jpeg', '.png', '.gif', '.svg')


# ------------------------------------------------------------------ keys

def _serpapi_key() -> str:
    from services.travel_api import get_serpapi_key
    return get_serpapi_key() or ''


def _brave_key() -> str:
    return (storage.get_settings() or {}).get('web_search_api_key', '') or ''


# --------------------------------------------------------------- html

_TAG_BLOCKS = re.compile(r'<(script|style|noscript|template|svg)\b.*?</\1>',
                         re.I | re.S)
_COMMENTS = re.compile(r'<!--.*?-->', re.S)
_BREAKS = re.compile(r'</(p|div|li|tr|h[1-6]|section|article)>', re.I)
_TAGS = re.compile(r'<[^>]+>')
_WS = re.compile(r'[ \t\r\f\v]+')
_BLANKS = re.compile(r'\n{3,}')


def html_to_text(raw: str) -> str:
    """Readable text from a page. Deliberately dependency-free — a research
    verb is not worth adding a parser to the image for, and the consumer is a
    language model that copes fine with imperfect whitespace."""
    if not raw:
        return ''
    s = _TAG_BLOCKS.sub(' ', raw)
    s = _COMMENTS.sub(' ', s)
    s = _BREAKS.sub('\n', s)
    s = _TAGS.sub(' ', s)
    s = _html.unescape(s)
    s = _WS.sub(' ', s)
    s = '\n'.join(line.strip() for line in s.split('\n'))
    return _BLANKS.sub('\n\n', s).strip()


def _fetchable(url: str) -> bool:
    """Only ordinary web pages. Never a local file, never a binary."""
    try:
        p = urlparse(url or '')
    except ValueError:
        return False
    if p.scheme not in ('http', 'https') or not p.netloc:
        return False
    return not p.path.lower().endswith(_SKIP_EXT)


def _fetch(url: str, max_chars: int = MAX_PAGE_CHARS) -> Optional[str]:
    if not _fetchable(url):
        return None
    try:
        import requests
        r = requests.get(url, timeout=FETCH_TIMEOUT, stream=True, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; Chauffeur/1.0; family assistant)'})
        r.raise_for_status()
        ctype = (r.headers.get('Content-Type') or '').lower()
        if 'html' not in ctype and 'text' not in ctype:
            return None
        raw = r.raw.read(max_chars * 8, decode_content=True) or b''
        text = html_to_text(raw.decode(r.encoding or 'utf-8', errors='replace'))
        return text[:max_chars] if text else None
    except Exception as e:
        logger.info(f"[web] fetch failed {url}: {e}")
        return None


# ------------------------------------------------------------- searching

def _brave_search(query: str, count: int = RESULTS_PER_SEARCH) -> list:
    import requests
    r = requests.get(BRAVE_URL, timeout=SEARCH_TIMEOUT,
                     headers={'X-Subscription-Token': _brave_key(),
                              'Accept': 'application/json'},
                     params={'q': query, 'count': count})
    r.raise_for_status()
    data = r.json()
    return [{'title': it.get('title') or '', 'url': it.get('url') or '',
             'snippet': html_to_text(it.get('description') or '')}
            for it in ((data.get('web') or {}).get('results') or [])
            if it.get('url')][:count]


def _serp_search(query: str, count: int = RESULTS_PER_SEARCH) -> list:
    import requests
    r = requests.get(SERPAPI_URL, timeout=SEARCH_TIMEOUT,
                     params={'engine': 'google', 'q': query,
                             'num': count, 'api_key': _serpapi_key()})
    r.raise_for_status()
    data = r.json()
    err = data.get('error') or ''
    if err:
        raise RuntimeError(err)
    from services import walmart as _wm
    _wm._serp_count()          # the shared monthly tally, kept legible
    return [{'title': it.get('title') or '', 'url': it.get('link') or '',
             'snippet': it.get('snippet') or ''}
            for it in (data.get('organic_results') or [])
            if it.get('link')][:count]


def _serp_headroom(settings: dict) -> int:
    """SerpApi calls research is allowed to spend this month."""
    from services import walmart as _wm
    limit = int(settings.get('serpapi_monthly_limit') or SERPAPI_MONTHLY_LIMIT)
    reserve = int(settings.get('serpapi_reserve') or DEFAULT_SERP_RESERVE)
    used = int((_wm.serp_usage() or {}).get('count') or 0)
    return (limit - reserve) - used


# ----------------------------------------------------------- accounting

def _cache_get(key):
    rows = storage.get_app_state('web_search_cache') or {}
    hit = rows.get(key)
    if not hit or time.time() - float(hit.get('ts') or 0) > CACHE_DAYS * 86400:
        return None
    return hit.get('value')


def _cache_put(key, value):
    rows = dict(storage.get_app_state('web_search_cache') or {})
    cutoff = time.time() - CACHE_DAYS * 86400
    rows = {k: v for k, v in rows.items() if float(v.get('ts') or 0) >= cutoff}
    rows[key] = {'ts': time.time(), 'value': value}
    storage.set_app_state('web_search_cache', rows)


def _month_count(bump: bool = False) -> int:
    month = time.strftime('%Y-%m')
    rows = dict(storage.get_app_state('web_research_calls') or {})
    n = int(rows.get(month) or 0)
    if bump:
        n += 1
        rows[month] = n
        for k in sorted(rows)[:-12]:
            rows.pop(k, None)
        storage.set_app_state('web_research_calls', rows)
    return n


def _pool_call(tier, api_key, system, prompt, **kw):
    """Indirection so tests stub one attribute."""
    from services import model_pools
    return model_pools.call_pool_json(tier, api_key, system, prompt, **kw)


# ------------------------------------------------------------- research

EXTRACT_SYSTEM = (
    "You are answering a household's practical question using ONLY the page "
    "text provided below. Never use anything you remember — if the pages do "
    "not say it, you do not know it.\n\n"
    "Every fact must carry the exact URL of the page it came from, copied "
    "from the SOURCE line above that page's text. Prefer established, "
    "well-known resources over blogs. If the pages do not answer the "
    "question, say so plainly with an empty facts list.\n\n"
    'Return STRICT JSON: {"answer": "<2-4 plain sentences>", '
    '"facts": [{"claim": "<one specific fact>", "url": "<exact source url>"}]}'
)


def search(query: str, count: int = RESULTS_PER_SEARCH) -> dict:
    """Raw results, cached. Brave when configured, else SerpApi above its
    reserve. Never raises — a dead search is a status."""
    settings = storage.get_settings() or {}
    ck = f"s|{query.strip().lower()}|{count}"
    cached = _cache_get(ck)
    if cached is not None:
        return {'status': 'ok', 'results': cached, 'cached': True}

    if _brave_key():
        try:
            rows = _brave_search(query, count)
        except Exception as e:
            logger.warning(f"[web] brave search failed: {e}")
            return {'status': 'error', 'message': str(e)}
    elif _serpapi_key():
        head = _serp_headroom(settings)
        if head <= 0:
            return {'status': 'reserved',
                    'message': "The shared SerpApi allowance is down to its "
                               "reserve — what's left is kept for flight and "
                               "gift lookups. Add a web search key to give "
                               "research its own."}
        try:
            rows = _serp_search(query, count)
        except Exception as e:
            logger.warning(f"[web] serpapi search failed: {e}")
            return {'status': 'error', 'message': str(e)}
    else:
        return {'status': 'no_key'}

    _cache_put(ck, rows)
    return {'status': 'ok', 'results': rows, 'cached': False}


def research(question: str, read_pages: int = PAGES_READ) -> dict:
    """Answer a practical question from pages this app actually read.

    Returns {status, answer, facts:[{claim,url}], sources:[{title,url}],
    dropped}. `dropped` counts facts the model cited to a page we never
    fetched — the invention rate, surfaced rather than hidden.
    """
    settings = storage.get_settings() or {}
    if not settings.get('web_research_enabled', False):
        return {'status': 'disabled'}
    if not (_brave_key() or _serpapi_key()):
        return {'status': 'no_key'}
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key:
        return {'status': 'no_key'}

    ck = f"r|{question.strip().lower()}|{read_pages}"
    cached = _cache_get(ck)
    if cached is not None:
        return {**cached, 'cached': True}

    cap = int(settings.get('web_research_cap') or DEFAULT_MONTHLY_CAP)
    if _month_count() >= cap:
        return {'status': 'capped',
                'message': f"That's {cap} research questions this month."}

    found = search(question)
    if found['status'] != 'ok':
        return found
    results = found['results']
    if not results:
        return {'status': 'no_results'}

    read = []
    for r in results[:read_pages]:
        text = _fetch(r['url'])
        if text:
            read.append({'title': r['title'], 'url': r['url'], 'text': text})
    if not read:
        return {'status': 'no_results',
                'message': 'Found pages but none of them could be read.'}

    _month_count(bump=True)
    prompt = f"QUESTION: {question}\n\n" + '\n\n'.join(
        f"SOURCE: {p['url']}\nTITLE: {p['title']}\n{p['text']}" for p in read)
    res = _pool_call('heavy', api_key, EXTRACT_SYSTEM, prompt,
                     timeout_s=90, gemma_timeout_s=180)
    if not isinstance(res, dict) or res.get('error'):
        return {'status': 'error', 'message': str((res or {}).get('error'))}

    # The rule the module exists for: a citation to a page we never read is
    # not a citation. Drop it, and report how many were dropped.
    readable = {p['url'] for p in read}
    facts, dropped = [], 0
    for f in (res.get('facts') or []):
        url = (f.get('url') or '').strip()
        claim = (f.get('claim') or '').strip()
        if claim and url in readable:
            facts.append({'claim': claim, 'url': url})
        else:
            dropped += 1

    out = {'status': 'ok', 'answer': (res.get('answer') or '').strip(),
           'facts': facts, 'dropped': dropped,
           'sources': [{'title': r['title'], 'url': r['url']} for r in results]}
    _cache_put(ck, out)
    return out

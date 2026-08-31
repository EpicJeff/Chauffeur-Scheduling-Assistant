"""Web research — the only verb in the Mind's repertoire that reaches outside
the house, and therefore the one most able to make things up.

The whole module is built around a single rule: **a claim carries the page it
came from, or it does not survive.**

Three routes to an answer, tried in order:

1. **Gemini Search grounding** (the default, and nearly always the one used).
   `tools: [{"google_search": {}}]` lets the model run its own Google queries
   and return an answer annotated with the pages it used. Google does the
   searching, so there is no second API key and no separate allowance — it
   bills against the same Gemini pool everything else here already uses.
   Citations come back as redirect URLs, which are resolved to the real
   publisher page so a family can click through and check.
2. **Brave** (`web_search_api_key`) — its own allowance, for households that
   would rather not route research through Google, or whose model pool has
   no grounding support.
3. **SerpApi** — already configured for flights, gift shortlists and Walmart,
   and capped at 250 requests A MONTH ACROSS ALL OF THEM. Research is the
   newest and least urgent consumer, so it may only borrow from that pool
   above a reserve (`serpapi_reserve`); past that line the remaining calls
   belong to the features that had them first. "Why did my flight lookup stop
   working" must never have a research question as its unexplained answer.

Routes 2 and 3 search, then FETCH the top pages and ask the model what that
text says — never what it remembers — and any fact citing a page we did not
read is dropped before the caller sees it. Route 1 gets the same discipline
from Google's own grounding metadata.
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
    # A non-string url (an int, a list -- anything urlparse cannot coerce)
    # raises OUTSIDE the try block below, not inside it: _fetchable's own
    # `except ValueError` never sees it, because urlparse hands back
    # AttributeError for a non-str/bytes argument, not ValueError. Found by
    # `_fetch(12345)` escaping as a raw AttributeError. Guarded here, at the
    # front door, rather than only inside _fetchable, because every caller
    # of this function -- research() included -- shares the exposure.
    if not isinstance(url, str) or not _fetchable(url):
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


def read_page(url: str) -> Optional[str]:
    """One page, read for its text -- the single-page sibling of research().

    `_fetch` already runs `html_to_text` internally and never raises, so
    this is a thin, explicitly public door onto it: program_lessons.py's
    generator needs exactly one page re-read at write time, not a search,
    and callers outside this module have no business reaching past the
    underscore on `_fetch` to get it. None on any failure -- a page that
    will not load is a retry, and the caller decides what the silence
    means (for a cited lesson, program_lessons.py's own answer is: no
    script)."""
    try:
        # Load-bearing, not redundant, even now that _fetch is hardened
        # against a non-string url (the guard above _fetchable, in _fetch)
        # -- that guard closes the ONE hole this try/except was covering
        # today, but this function's contract is "None on any failure",
        # and that promise should not quietly depend on every frame
        # beneath it staying exception-safe forever. Keep this even if
        # _fetch looks exception-proof at a glance.
        return _fetch(url)
    except Exception as e:
        logger.info(f"[web] read_page failed for {url}: {e}")
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


# --------------------------------------------- gemini search grounding

GEMINI_URL = ('https://generativelanguage.googleapis.com/v1beta/models/'
              '{model}:generateContent?key={key}')

GROUND_SYSTEM = (
    "Answer this household's practical question using Google Search. Be "
    "concrete and local where the question is local. Prefer established, "
    "well-known sources over blogs and content farms. Two to four plain "
    "sentences, no preamble. If the web does not answer it, say so."
)


def _parse_grounded(data: dict) -> dict:
    """Pull the answer, its sources and the required search-suggestions HTML
    out of a grounded response.

    Handles BOTH shapes the API has used: `groundingMetadata.groundingChunks`
    and per-part `annotations[].url_citation`. Which one arrives depends on
    the model and endpoint version, and a research verb that breaks when
    Google ships a new response shape is a research verb that breaks."""
    cand = ((data or {}).get('candidates') or [{}])[0]
    parts = ((cand.get('content') or {}).get('parts') or [])
    answer = ''.join(p.get('text') or '' for p in parts).strip()

    sources, seen = [], set()

    def _add(url, title):
        url = (url or '').strip()
        if url and url not in seen:
            seen.add(url)
            sources.append({'title': (title or '').strip() or url, 'url': url})

    for p in parts:
        for ann in (p.get('annotations') or []):
            cit = ann.get('url_citation') or {}
            _add(cit.get('url'), cit.get('title'))

    gm = cand.get('groundingMetadata') or {}
    for chunk in (gm.get('groundingChunks') or []):
        web_c = chunk.get('web') or {}
        _add(web_c.get('uri'), web_c.get('title'))

    suggestions = ((gm.get('searchEntryPoint') or {}).get('renderedContent')
                   or (data or {}).get('search_suggestions') or '')
    return {'answer': answer, 'sources': sources,
            'suggestions_html': suggestions}


def _gemini_grounded(question: str, api_key: str, model: str = None) -> Optional[dict]:
    """One grounded call. Returns None when the pool has no model that can do
    it, so the caller falls through to a search backend."""
    import urllib.request
    import urllib.error
    from services import model_pools
    settings = storage.get_settings() or {}
    candidates = [model] if model else model_pools.models_for('heavy', settings)[:3]
    last_err = None
    for m in [c for c in candidates if c and not model_pools.is_gemma(c)]:
        payload = {
            'contents': [{'role': 'user',
                          'parts': [{'text': f"{GROUND_SYSTEM}\n\nQUESTION: {question}"}]}],
            'tools': [{'google_search': {}}],
            'generationConfig': {'temperature': 0.1},
        }
        req = urllib.request.Request(
            GEMINI_URL.format(model=m.replace('models/', ''), key=api_key),
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=SEARCH_TIMEOUT + 40) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')[:300]
            last_err = f"{e.code} {body}"
            model_pools.note_failure(m, last_err)
            # 400 usually means this model does not take the search tool at
            # all; anything else is worth trying the next model for.
            continue
        except Exception as e:
            last_err = str(e)
            continue
        out = _parse_grounded(data)
        if out.get('answer'):
            out['model'] = m
            return out
    if last_err:
        logger.info(f"[web] no pool model grounded the search: {last_err}")
    return None


def _resolve_url(url: str) -> str:
    """Follow a grounding redirect to the page it actually points at.

    Grounded citations come back as opaque redirect links. A source a family
    cannot recognise is barely a source, so they are resolved for display —
    and the original is kept if the resolve fails."""
    try:
        import requests
        r = requests.head(url, timeout=8, allow_redirects=True)
        return r.url or url
    except Exception:
        return url


def _resolve_sources(sources: list) -> list:
    out = []
    for s in sources:
        url = s.get('url') or ''
        real = _resolve_url(url) if 'grounding-api-redirect' in url \
            or 'redirect' in url else url
        out.append({'title': s.get('title') or real, 'url': real})
    return out


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

    # Route 1: let Google do the searching. No second key, no separate
    # allowance, and the citations arrive with the answer.
    if settings.get('llm_provider', 'gemini') == 'gemini':
        try:
            grounded = _gemini_grounded(question, api_key)
        except Exception as e:
            logger.warning(f"[web] grounding failed: {e}")
            grounded = None
        if grounded and grounded.get('answer'):
            _month_count(bump=True)
            sources = _resolve_sources(grounded.get('sources') or [])
            out = {'status': 'ok', 'answer': grounded['answer'],
                   'facts': [{'claim': grounded['answer'], 'url': s['url']}
                             for s in sources[:1]],
                   'dropped': 0, 'sources': sources, 'via': 'grounding',
                   'suggestions_html': grounded.get('suggestions_html') or ''}
            _cache_put(ck, out)
            return out

    # Routes 2 and 3: search a backend ourselves, read the pages, extract.
    if not (_brave_key() or _serpapi_key()):
        return {'status': 'no_key'}
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
           'facts': facts, 'dropped': dropped, 'via': 'pages',
           'sources': [{'title': r['title'], 'url': r['url']} for r in results]}
    _cache_put(ck, out)
    return out

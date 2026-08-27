"""Web research: search, fetch, and facts that carry where they came from.

The rule the whole capability exists to serve is that a claim without a source
is worse than no claim — research is the verb most likely to invent things, so
every scenario here is really about provenance.
"""
import json
from harness import check
from services import storage, web


CALLS = {'search': [], 'fetch': [], 'llm': []}


def _reset():
    for v in CALLS.values():
        v.clear()
    storage.set_app_state('web_search_cache', {})
    storage.set_app_state('serpapi_usage', {})
    storage.set_app_state('web_research_calls', {})
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k',
                                    'web_research_enabled': True}
    web._serpapi_key = lambda: 'serp-key'
    web._brave_key = lambda: ''
    # Grounding is the primary path, so every non-grounding scenario has to
    # switch it off explicitly or it would never reach the fallback.
    web._gemini_grounded = lambda q, key, model=None: None
    web._resolve_url = lambda u: u


def _fake_serp(results):
    def f(query, count):
        CALLS['search'].append(query)
        return results
    return f


def _fake_fetch(pages):
    def f(url, max_chars=None):
        CALLS['fetch'].append(url)
        return pages.get(url)
    return f


def _fake_llm(payload):
    def f(tier, api_key, system, prompt, **kw):
        CALLS['llm'].append(prompt)
        return payload
    return f


RESULTS = [
    {'title': 'Justin Guitar Beginner Course', 'url': 'https://justinguitar.com/g1',
     'snippet': 'A free structured course for absolute beginners.'},
    {'title': 'Some Blog', 'url': 'https://blog.example/guitar',
     'snippet': 'My thoughts on learning guitar.'},
]


# ------------------------------------------------- gemini search grounding

GROUNDED_CLASSIC = {
    'candidates': [{
        'content': {'parts': [{'text': 'Justin Guitar Grade 1 is the usual start.'}]},
        'groundingMetadata': {
            'groundingChunks': [
                {'web': {'uri': 'https://redirect.example/abc',
                         'title': 'justinguitar.com'}},
            ],
            'searchEntryPoint': {'renderedContent': '<div>suggestions</div>'},
        }}]}

GROUNDED_ANNOTATED = {
    'candidates': [{
        'content': {'parts': [{
            'text': 'Couch to 5K is a nine-week plan.',
            'annotations': [{'url_citation': {
                'url': 'https://nhs.uk/c25k', 'title': 'NHS Couch to 5K'}}]}]},
    }]}


def scenario_grounding_is_preferred_and_costs_no_extra_key():
    _reset()
    web._serpapi_key = lambda: 'serp-key'
    web._brave_key = lambda: 'brave-key'
    hits = []
    web._gemini_grounded = lambda q, key, model=None: (
        hits.append(q) or {'answer': 'Grounded answer.',
                           'sources': [{'title': 'A', 'url': 'https://a.example'}],
                           'suggestions_html': ''})
    web._serp_search = _fake_serp(RESULTS)
    web._brave_search = _fake_serp(RESULTS)
    res = web.research('what is a good beginner guitar course')
    check(res['status'] == 'ok' and res['answer'] == 'Grounded answer.',
          f"got {res}")
    check(hits and not CALLS['search'] and not CALLS['fetch'],
          "Google does the searching; no metered key and no page fetching")
    check(res['facts'][0]['url'] == 'https://a.example',
          f"grounded sources are the citations, got {res['facts']}")


def scenario_both_grounding_response_shapes_are_read():
    classic = web._parse_grounded(GROUNDED_CLASSIC)
    check(classic['answer'].startswith('Justin Guitar'), f"got {classic}")
    check(classic['sources'][0]['url'] == 'https://redirect.example/abc',
          f"classic groundingChunks, got {classic['sources']}")
    check('suggestions' in classic['suggestions_html'],
          "the search-suggestions HTML the terms require is kept")
    annotated = web._parse_grounded(GROUNDED_ANNOTATED)
    check(annotated['sources'][0]['url'] == 'https://nhs.uk/c25k',
          f"newer url_citation annotations, got {annotated['sources']}")


def scenario_grounding_failure_falls_back_to_search():
    _reset()
    web._brave_key = lambda: 'brave-key'

    def boom(q, key, model=None):
        raise RuntimeError('grounding unavailable on this model')
    web._gemini_grounded = boom
    web._brave_search = _fake_serp(RESULTS)
    web._fetch = _fake_fetch({'https://justinguitar.com/g1': 'Grade 1 text.',
                              'https://blog.example/guitar': 'Blog.'})
    web._pool_call = _fake_llm({'answer': 'From pages.', 'facts': [
        {'claim': 'x', 'url': 'https://justinguitar.com/g1'}]})
    res = web.research('anything')
    check(res['status'] == 'ok' and res['answer'] == 'From pages.',
          f"an old model without grounding still researches, got {res}")


def scenario_redirect_citations_resolve_to_the_real_page():
    _reset()
    web._resolve_url = lambda u: ('https://justinguitar.com/g1'
                                  if 'redirect.example' in u else u)
    out = web._resolve_sources([{'title': 'justinguitar.com',
                                 'url': 'https://redirect.example/abc'}])
    check(out[0]['url'] == 'https://justinguitar.com/g1',
          f"a family must be able to click through and check, got {out}")


# ------------------------------------------------------------- plumbing

def scenario_html_becomes_readable_text():
    html = ('<html><head><title>T</title><style>.a{color:red}</style>'
            '<script>var x=1;</script></head><body><h1>Grade 1</h1>'
            '<p>Three chords &amp; a strum.</p><!-- hidden --></body></html>')
    text = web.html_to_text(html)
    check('Grade 1' in text and 'Three chords & a strum.' in text,
          f"content survives, got {text!r}")
    check('var x' not in text and 'color:red' not in text,
          f"script and style do not, got {text!r}")
    check('hidden' not in text, f"comments do not either, got {text!r}")


def scenario_disabled_and_keyless_degrade_quietly():
    _reset()
    storage.get_settings = lambda: {'web_research_enabled': False}
    check(web.research('anything')['status'] == 'disabled', "off means off")
    storage.get_settings = lambda: {'web_research_enabled': True}
    web._serpapi_key = lambda: ''
    check(web.research('anything')['status'] == 'no_key',
          "no key is a status, never an exception")
    check(not CALLS['search'], "and nothing was called")


# -------------------------------------------------------------- research

def scenario_facts_carry_their_source():
    _reset()
    web._serp_search = _fake_serp(RESULTS)
    web._fetch = _fake_fetch({
        'https://justinguitar.com/g1': 'Grade 1 covers three chords over four weeks.',
        'https://blog.example/guitar': 'I like guitars.'})
    web._pool_call = _fake_llm({'answer': 'Justin Guitar Grade 1 is the usual start.',
                                'facts': [{'claim': 'Grade 1 covers three chords',
                                           'url': 'https://justinguitar.com/g1'}]})
    res = web.research('best free beginner guitar curriculum')
    check(res['status'] == 'ok', f"got {res}")
    check(res['facts'][0]['url'] == 'https://justinguitar.com/g1',
          f"every fact names its page, got {res['facts']}")
    check(len(res['sources']) == 2, f"sources are listed, got {res['sources']}")
    check('Grade 1 covers three chords over four weeks' in CALLS['llm'][0],
          "the model reads FETCHED page text, not its own memory")


def scenario_a_fact_citing_nothing_we_read_is_dropped():
    _reset()
    web._serp_search = _fake_serp(RESULTS)
    web._fetch = _fake_fetch({'https://justinguitar.com/g1': 'Grade 1 text.',
                              'https://blog.example/guitar': 'Blog text.'})
    web._pool_call = _fake_llm({'answer': 'Sure.', 'facts': [
        {'claim': 'Real one', 'url': 'https://justinguitar.com/g1'},
        {'claim': 'Invented one', 'url': 'https://totally-made-up.example/x'},
        {'claim': 'Uncited one', 'url': ''}]})
    res = web.research('anything')
    urls = [f['url'] for f in res['facts']]
    check(urls == ['https://justinguitar.com/g1'],
          f"a citation we never fetched is not a citation, got {urls}")
    check(res['dropped'] == 2, f"and the drop is reported, got {res}")


def scenario_search_is_cached_so_a_repeat_costs_nothing():
    _reset()
    web._serp_search = _fake_serp(RESULTS)
    web._fetch = _fake_fetch({'https://justinguitar.com/g1': 'x',
                              'https://blog.example/guitar': 'y'})
    web._pool_call = _fake_llm({'answer': 'a', 'facts': []})
    web.research('same question')
    web.research('same question')
    check(len(CALLS['search']) == 1,
          f"the metered call happens once, got {len(CALLS['search'])}")


def scenario_monthly_cap_stops_research():
    _reset()
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k',
                                    'web_research_enabled': True,
                                    'web_research_cap': 2}
    web._serp_search = _fake_serp(RESULTS)
    web._fetch = _fake_fetch({'https://justinguitar.com/g1': 'x',
                              'https://blog.example/guitar': 'y'})
    web._pool_call = _fake_llm({'answer': 'a', 'facts': []})
    check(web.research('q1')['status'] == 'ok', "first")
    check(web.research('q2')['status'] == 'ok', "second")
    check(web.research('q3')['status'] == 'capped', "third is refused")


def scenario_serpapi_reserve_protects_flights_and_gifts():
    """SerpApi is 250/month across EVERY consumer. Research is the newcomer
    and the least urgent, so it must never spend the last of a shared
    allowance the trip planner and gift shortlist also draw on."""
    _reset()
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k',
                                    'web_research_enabled': True,
                                    'serpapi_monthly_limit': 250,
                                    'serpapi_reserve': 100}
    web._brave_key = lambda: ''            # no dedicated backend configured
    web._serp_search = _fake_serp(RESULTS)
    web._fetch = _fake_fetch({'https://justinguitar.com/g1': 'x',
                              'https://blog.example/guitar': 'y'})
    web._pool_call = _fake_llm({'answer': 'a', 'facts': []})

    import time as _t
    month = _t.strftime('%Y-%m')
    storage.set_app_state('serpapi_usage', {month: 149})
    check(web.research('still fine')['status'] == 'ok',
          "under the reserve line research may borrow the shared quota")
    storage.set_app_state('serpapi_usage', {month: 151})
    r = web.research('now back off')
    check(r['status'] == 'reserved',
          f"past it, the remaining calls belong to flights and gifts, got {r}")
    check('flight' in (r.get('message') or '').lower()
          or 'reserve' in (r.get('message') or '').lower(),
          f"and it says why, got {r.get('message')}")


def scenario_a_dedicated_backend_is_preferred_over_the_shared_one():
    _reset()
    web._brave_key = lambda: 'brave-key'
    brave_hits = []

    def fake_brave(query, count):
        brave_hits.append(query)
        return RESULTS
    web._brave_search = fake_brave
    web._serp_search = _fake_serp(RESULTS)
    web._fetch = _fake_fetch({'https://justinguitar.com/g1': 'x',
                              'https://blog.example/guitar': 'y'})
    web._pool_call = _fake_llm({'answer': 'a', 'facts': []})
    res = web.research('who searches this')
    check(res['status'] == 'ok' and brave_hits and not CALLS['search'],
          "with its own key research never touches the shared allowance")


def scenario_nothing_found_is_an_honest_answer():
    _reset()
    web._serp_search = _fake_serp([])
    web._pool_call = _fake_llm({'answer': 'should not be called', 'facts': []})
    res = web.research('a question with no results')
    check(res['status'] == 'no_results', f"got {res}")
    check(not CALLS['llm'], "and no model was asked to fill the silence")


def scenario_only_http_urls_are_fetched():
    check(web._fetchable('https://a.example/x') is True, "https ok")
    check(web._fetchable('http://a.example/x') is True, "http ok")
    check(web._fetchable('file:///etc/passwd') is False, "file is not")
    check(web._fetchable('ftp://a.example/x') is False, "nor ftp")
    check(web._fetchable('https://a.example/f.pdf') is False,
          "nor things that are not pages")


if __name__ == '__main__':
    scenario_grounding_is_preferred_and_costs_no_extra_key()
    scenario_both_grounding_response_shapes_are_read()
    scenario_grounding_failure_falls_back_to_search()
    scenario_redirect_citations_resolve_to_the_real_page()
    scenario_html_becomes_readable_text()
    scenario_disabled_and_keyless_degrade_quietly()
    scenario_facts_carry_their_source()
    scenario_a_fact_citing_nothing_we_read_is_dropped()
    scenario_search_is_cached_so_a_repeat_costs_nothing()
    scenario_monthly_cap_stops_research()
    scenario_serpapi_reserve_protects_flights_and_gifts()
    scenario_a_dedicated_backend_is_preferred_over_the_shared_one()
    scenario_nothing_found_is_an_honest_answer()
    scenario_only_http_urls_are_fetched()
    print("test_web_research OK")

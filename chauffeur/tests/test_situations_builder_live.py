"""The card builder's page contract, in a real browser: bind resolves cards
through the page's lookup, a second bind never double-fires, intercept
wins over the default act, extraHtml lands inside the card."""
import datetime
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='situations_builder_live_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_app import live_app
from services import storage

NOON = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def seed():
    storage.update_settings({'llm_gemini_api_key': ''})
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent', 'color_code': '#6366f1'})
    from services import threads
    threads.create('Deck permit', owner_member_id='mom', next_action='call county', created_by='mom')


PAGE = """
<!doctype html><html><head><meta charset="utf-8"></head><body>
<div id="lane"></div>
<script>
  window.hits = []; window.intercepted = [];
  const origFetch = window.fetch;
  window.fetch = async (url, opts) => { if (String(url).includes('/act')) window.hits.push(String(url)); return origFetch(url, opts); };
</script>
<script src="/static/situations.js"></script>
</body></html>
"""


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        b = served.browser(color_scheme='dark')
        with b as page:
            # Land on the same origin first (a plain static file: no page script
            # of its own can add errors), then draw our own tiny page.
            page.goto(served.url('static/situations.js'), wait_until='networkidle')
            page.set_content(PAGE.replace('/static/', served.url('static/')), wait_until='networkidle')
            sits = page.evaluate("async () => (await (await fetch('%s')).json()).situations" % served.url('api/situations?kinds=thread'))
            check(sits and sits[0]['kind'] == 'thread', "a thread situation to draw")
            n_hits = page.evaluate("""(sits) => {
                const el = document.getElementById('lane');
                const byId = {}; sits.forEach(s => byId[s.id] = s);
                const ctx = { apiBase: '%s', canWrite: true, lookup: (k, id) => byId[id],
                              intercept: (s, o) => { if (o.verb === 'advance') { window.intercepted.push(o.id); return true; } return false; },
                              extraHtml: (s) => '<div class="sit-extra">EXTRA ' + s.title + '</div>' };
                el.innerHTML = sits.map(s => Situations.cardHtml(s, ctx)).join('');
                Situations.bind(el, ctx);
                Situations.bind(el, ctx);     // a second bind must not double-fire
                const adv = el.querySelector('[data-sit-act^="advance"]'); adv.click();
                const own = el.querySelector('[data-sit-act="own"]'); own.click();
                return new Promise(r => setTimeout(() => r({ hits: window.hits.length, intercepted: window.intercepted.length,
                    extra: !!el.querySelector('.situation-card .sit-extra'), details: !!el.querySelector('.situation-card details') }), 1200));
            }""" % served.url(''), sits)
            check(n_hits['intercepted'] == 1, f"intercept handled advance once, got {n_hits}")
            check(n_hits['hits'] == 1, f"own fired exactly one act request through two binds, got {n_hits}")
            check(n_hits['extra'], "extraHtml landed inside the card")
            check(not n_hits['details'], "the card draws no empty details element any more")
            check(not b.errors, f"script errors: {b.errors}")
    finally:
        served.stop()


if __name__ == '__main__':
    main()
    print("test_situations_builder_live OK")
